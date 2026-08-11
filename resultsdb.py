#!/usr/bin/env python3
"""
The result database of the library testing, either local or shared.

Historically every test machine wrote its results to its own sqlite3 file,
copied in before a run and copied back afterwards, so two machines running the
same job overwrote each other.  The scripts can now talk to a shared PostgreSQL
database instead, where the machines coordinate through [job_claim] and nobody
overwrites anybody.

  db = connect("sqlite3.db")                                 # the old local file
  db = connect("postgresql://om@openmodelica.org/omdb")      # the shared database

Both backends take the same statements, with "?" as the placeholder.  Where the
two dialects genuinely differ - quoting a branch name, testing whether a table
exists, concatenating a group, counting a condition - ask the connection
instead of writing it out, see quote()/tableExists()/groupConcat()/countIf().

PostgreSQL needs psycopg2 (pip install psycopg2-binary) and reads the password
from PGPASSWORD or ~/.pgpass, never from the URL.
"""

import os
import re
import socket
import sqlite3
import threading
import time

# A claim older than this without a heartbeat belongs to a machine that died,
# and another machine may take the job over.
STALE_CLAIM_MINUTES = 30
HEARTBEAT_SECONDS = 60

# The columns of a per-branch result table, with the type spelled per backend.
BRANCH_COLUMNS = [
    ("date", "bigint"), ("libname", "text"), ("model", "text"), ("exectime", "real"),
    ("frontend", "real"), ("backend", "real"), ("simcode", "real"), ("templates", "real"),
    ("compile", "real"), ("simulate", "real"), ("verify", "real"),
    ("verifyfail", "int"), ("verifytotal", "int"), ("finalphase", "int"), ("parsing", "real"),
]
SQLITE_TYPES = {"bigint": "integer", "int": "integer", "real": "real", "text": "text"}
POSTGRES_TYPES = {"bigint": "bigint", "int": "integer", "real": "double precision", "text": "text"}

# What identifies a row, so that two machines writing the same shared table
# cannot store the same result twice.  Mirrors sqlite2postgres.py.
KEYS = {
    "omcversion": ["date", "branch"],
    "libversion": ["date", "branch", "libname", "confighash"],
}
BRANCH_KEY = ["date", "libname", "model"]

JOB_CLAIM = """
CREATE TABLE IF NOT EXISTS job_claim (
  branch     text   NOT NULL,
  libname    text   NOT NULL,
  libversion text   NOT NULL,
  omcversion text   NOT NULL,
  confighash bigint NOT NULL,
  host       text   NOT NULL,
  state      text   NOT NULL,
  claimed_at timestamptz NOT NULL DEFAULT now(),
  heartbeat  timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (branch, libname, libversion, omcversion, confighash)
)
"""


# Jenkins sets LIBTEST_DB once for the whole pipeline rather than passing --db
# to every script invocation.
DEFAULT_DB = os.environ.get("LIBTEST_DB") or "sqlite3.db"
DB_HELP = ("Result database: a local sqlite3 file, or a postgresql://user@host/database URL for "
           "the shared one, taken from the LIBTEST_DB environment variable when not given. "
           "Several machines can write to the shared database at the same time; a library "
           "another machine is already testing is skipped instead of tested twice. The password "
           "is read from PGPASSWORD or ~/.pgpass, never from the URL.")


def addArgument(parser):
  """Give a script the --db option, spelled the same way everywhere."""
  parser.add_argument("--db", default=DEFAULT_DB, help=DB_HELP)


def _fixPgpassPermissions():
  """libpq ignores a password file others can read, and then fails to connect.

  Jenkins hands the credential to the build as a file it created itself, so
  rather than have every job remember to chmod it, take a private copy.
  """
  path = os.environ.get("PGPASSFILE")
  if not path or not os.path.isfile(path):
    return
  if not (os.stat(path).st_mode & 0o077):
    return
  import shutil, tempfile
  fd, private = tempfile.mkstemp(prefix="pgpass.")
  os.close(fd)
  os.chmod(private, 0o600)
  shutil.copyfile(path, private)
  os.environ["PGPASSFILE"] = private


def connect(url):
  """Open the result database named by url: a path or a postgresql:// URL."""
  if url.startswith("postgres://") or url.startswith("postgresql://"):
    return _Postgres(url)
  return _Sqlite(url)


class _Db:
  """What the testing and report scripts use; the backends fill in the rest."""

  def cursor(self):
    return _Cursor(self, self.conn.cursor())

  def execute(self, sql, params=()):
    return self.cursor().execute(sql, params)

  def commit(self):
    self.conn.commit()

  def close(self):
    self.conn.close()

  # The errors that mean the connection is gone rather than the statement bad.
  lostConnection = ()

  def record(self, statement, params):
    """Remember a statement in case the transaction has to be replayed."""

  def recover(self):
    """Reconnect after the connection was lost and replay the transaction."""
    raise NotImplementedError

  def insertIgnore(self):
    """The clause that makes an INSERT skip a row that is already there."""
    return ""

  def createDateIndex(self, branch):
    """The index the report queries need; test.py drops it before a run."""
    self.execute("CREATE INDEX IF NOT EXISTS %s ON %s (date)"
                 % (self.quote("idx_%s_date" % branch), self.quote(branch)))

  def claim(self, branch, libname, libversion, omcversion, confighash):
    """True when this machine may test that library, False when another one is.

    Only the shared database can say no; a local file has a single writer.
    """
    return True

  def claimedBy(self, branch, libname, libversion, omcversion, confighash):
    return ("this machine", None)

  def release(self):
    """Mark the claims of this run as finished."""

  def vacuum(self):
    self.conn.execute("VACUUM")


class _Cursor:
  """A cursor that takes "?" placeholders whatever the backend wants."""

  def __init__(self, db, cursor):
    self.db = db
    self.cursor = cursor

  def execute(self, sql, params=()):
    # psycopg2 only looks for placeholders when parameters are passed, so a
    # statement without any must not be handed an empty tuple.
    params = tuple(params)
    statement = self.db.sql(sql, bool(params))
    try:
      self.cursor.execute(statement, self.db.params(params))
    except self.db.lostConnection as e:
      # The results of a run are written in one transaction at the end of it,
      # after the connection has been idle for hours, which is exactly when a
      # firewall or a restarted server has dropped it. Reconnecting and
      # replaying what the transaction had so far costs nothing and saves the
      # whole run; the keys make replaying it harmless.
      print("Lost the connection to the database (%s); reconnecting" % str(e).strip())
      self.cursor = self.db.recover()
      self.cursor.execute(statement, self.db.params(params))
    self.db.record(statement, self.db.params(params))
    return self

  def fetchone(self):
    return self.cursor.fetchone()

  def fetchall(self):
    return self.cursor.fetchall()

  def __iter__(self):
    return iter(self.cursor)


class _Sqlite(_Db):
  """The per-machine sqlite3 file the testing has always used."""

  name = "sqlite3"

  def __init__(self, path):
    self.conn = sqlite3.connect(path)
    self.path = path

  def sql(self, sql, hasParams=False):
    return sql

  def params(self, params):
    return params

  def quote(self, ident):
    """Quote a table or column name, typically a branch name."""
    return "[%s]" % ident

  def createTables(self, branch):
    """The schema migration test.py has always done, plus the branch table."""
    cursor = self.cursor()
    user_version = self.userVersion()
    if user_version == 0:
      # Table to lookup from a run (date, branch) to omcversion used
      cursor.execute("CREATE TABLE if not exists [omcversion] (date integer NOT NULL, branch text NOT NULL, omcversion text NOT NULL)")
      # Table to lookup from a run (date, branch) which library versions were used
      cursor.execute("CREATE TABLE if not exists [libversion] (date integer NOT NULL, branch text NOT NULL, libname text NOT NULL, libversion text NOT NULL, confighash integer NOT NULL)")
    elif user_version == 1:
      cursor.execute("ALTER TABLE [libversion] ADD COLUMN confighash integer NOT NULL DEFAULT(0)")
    elif user_version == 2:
      for tbl in [t for t in self.tables() if t not in ["libversion", "omcversion"]]:
        cursor.execute("ALTER TABLE [%s] ADD COLUMN parsing real NOT NULL DEFAULT(0.0)" % tbl)
    elif user_version != 3:
      raise SystemExit("Unknown schema user_version=%d" % user_version)

    cols = ", ".join("%s %s NOT NULL" % (c, SQLITE_TYPES[t]) for c, t in BRANCH_COLUMNS)
    cursor.execute("CREATE TABLE if not exists %s (%s)" % (self.quote(branch), cols))
    # The indexes only slow the run's inserts down; the report scripts add them back.
    cursor.execute("DROP INDEX IF EXISTS [idx_%s_date]" % branch)
    cursor.execute("DROP INDEX IF EXISTS idx_omcversion_date")
    cursor.execute("DROP INDEX IF EXISTS idx_libversion_date")
    self.setUserVersion(3)

  def tables(self):
    return [t for (t,) in self.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]

  def tableExists(self, name):
    return self.conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None

  def groupConcat(self, expr, orderBy=None):
    # sqlite keeps the order of the subquery that feeds the aggregate.
    return "GROUP_CONCAT(%s)" % expr

  def countIf(self, cond):
    return "COUNT(%s or null)" % cond

  def likeNoCase(self, column):
    """A case insensitive comparison against a "?" placeholder."""
    return "%s LIKE ? COLLATE NOCASE" % column

  def userVersion(self):
    return self.conn.execute("PRAGMA user_version").fetchone()[0]

  def setUserVersion(self, v):
    self.conn.execute("PRAGMA user_version=%d" % v)


class _Postgres(_Db):
  """The shared database several test machines write to at the same time."""

  name = "postgresql"

  def __init__(self, url):
    try:
      import psycopg2
    except ImportError:
      raise SystemExit("PostgreSQL support needs psycopg2: pip install psycopg2-binary")
    # The password belongs in PGPASSWORD or ~/.pgpass, not in the URL.
    _fixPgpassPermissions()
    self.url = url
    self.lostConnection = (psycopg2.OperationalError, psycopg2.InterfaceError)
    self.pending = []
    self.conn = self._connect()
    self.host = socket.gethostname()
    self.claims = []
    self.heartbeatThread = None
    self.execute(JOB_CLAIM)
    self.commit()

  def _connect(self):
    """Open the connection, asking the kernel to keep it alive.

    A run holds this connection open while it tests, which is hours during
    which nothing is sent on it, and an idle connection is what a firewall or
    a NAT quietly drops. The keepalives make that visible rather than fatal.
    """
    import psycopg2
    conn = psycopg2.connect(self.url, keepalives=1, keepalives_idle=60,
                            keepalives_interval=10, keepalives_count=5)
    conn.autocommit = False
    return conn

  # Only what changes the database has to be replayed; a run also makes tens of
  # thousands of queries, which would fill the buffer for nothing.
  WRITES = ("insert", "update", "delete", "create", "drop", "alter")

  def record(self, statement, params):
    first = statement.lstrip().split(None, 1)
    if first and first[0].lower() in self.WRITES:
      self.pending.append((statement, params))

  def recover(self):
    """Reconnect and replay the transaction that the lost connection took.

    Everything a run writes is an insert guarded by a key, so replaying it can
    only produce the rows that were lost, never a duplicate.
    """
    try:
      self.conn.close()
    except Exception:
      pass
    self.conn = self._connect()
    cursor = self.conn.cursor()
    for (statement, params) in self.pending:
      cursor.execute(statement, params)
    if self.pending:
      print("Replayed %d statements of the interrupted transaction" % len(self.pending))
    return cursor

  def commit(self):
    try:
      self.conn.commit()
    except self.lostConnection as e:
      print("Lost the connection to the database while committing (%s); reconnecting"
            % str(e).strip())
      self.recover()
      self.conn.commit()
    self.pending = []

  def sql(self, sql, hasParams=False):
    """sqlite spells the placeholder "?" and psycopg2 spells it "%s".

    psycopg2 also reads "%" itself, so a literal one has to be doubled - but
    only in a statement that has parameters at all.
    """
    if not hasParams:
      return sql
    return sql.replace("%", "%%").replace("?", "%s")

  def params(self, params):
    # psycopg2 only looks for placeholders when parameters are passed, so a
    # statement without any must not be handed an empty tuple.
    return params or None

  def quote(self, ident):
    return '"%s"' % ident.replace('"', '""')

  def createTables(self, branch):
    """Create the shared tables, with the keys that keep the machines apart.

    Unlike sqlite there is no schema migration and the indexes stay: other
    machines are reading the table while this one writes its few thousand rows.
    """
    cursor = self.cursor()
    cursor.execute("""CREATE TABLE IF NOT EXISTS omcversion (
        date bigint NOT NULL, branch text NOT NULL, omcversion text)""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS libversion (
        date bigint NOT NULL, branch text NOT NULL, libname text NOT NULL,
        libversion text, confighash bigint NOT NULL)""")
    cols = ", ".join("%s %s%s" % (c, POSTGRES_TYPES[t], " NOT NULL" if c in BRANCH_KEY else "")
                     for c, t in BRANCH_COLUMNS)
    cursor.execute("CREATE TABLE IF NOT EXISTS %s (%s)" % (self.quote(branch), cols))
    for tbl in ["omcversion", "libversion", branch]:
      key = KEYS.get(tbl, BRANCH_KEY)
      cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS %s ON %s (%s)"
                     % (self.quote(("uq_%s_%s" % (tbl, "_".join(key)))[:63]),
                        self.quote(tbl), ",".join(key)))
    cursor.execute("CREATE INDEX IF NOT EXISTS %s ON %s (libname, date)"
                   % (self.quote(("idx_%s_libname_date" % branch)[:63]), self.quote(branch)))
    self.commit()

  def tables(self):
    return [t for (t,) in self.execute(
        "SELECT tablename FROM pg_tables WHERE schemaname=current_schema()")]

  def tableExists(self, name):
    return self.execute("SELECT 1 FROM pg_tables WHERE schemaname=current_schema() AND tablename=?",
                        (name,)).fetchone() is not None

  def groupConcat(self, expr, orderBy=None):
    if orderBy:
      return "string_agg(%s::text, ',' ORDER BY %s)" % (expr, orderBy)
    return "string_agg(%s::text, ',')" % expr

  def countIf(self, cond):
    return "COUNT(*) FILTER (WHERE %s)" % cond

  def likeNoCase(self, column):
    return "%s ILIKE ?" % column

  def insertIgnore(self):
    # Another machine may have written the same run already; its row wins.
    return " ON CONFLICT DO NOTHING"

  def createDateIndex(self, branch):
    """Nothing to do: date is the first column of the table's unique key."""

  def userVersion(self):
    return 3

  def setUserVersion(self, v):
    pass

  def vacuum(self):
    """Nothing to do: PostgreSQL has autovacuum, and a manual VACUUM of a
    50 GB database after every test run would be a waste of the machine."""

  def claim(self, branch, libname, libversion, omcversion, confighash):
    """Take the job unless another machine is running it right now.

    The claim is one row per (branch, library version, omc version, config).
    A machine that dies stops sending its heartbeat, and after
    STALE_CLAIM_MINUTES its jobs are up for grabs again.
    """
    key = (branch, libname, libversion, omcversion, confighash)
    got = self.execute("""INSERT INTO job_claim
        (branch, libname, libversion, omcversion, confighash, host, state)
        VALUES (?,?,?,?,?,?,'running')
        ON CONFLICT (branch, libname, libversion, omcversion, confighash) DO UPDATE
        SET host = EXCLUDED.host, state = 'running', claimed_at = now(), heartbeat = now()
        WHERE job_claim.state <> 'running'
           OR job_claim.heartbeat < now() - interval '%d minutes'
        RETURNING host""" % STALE_CLAIM_MINUTES,
        key + (self.host,)).fetchone()
    self.commit()
    if got is None:
      return False
    self.claims.append(key)
    self._startHeartbeat()
    return True

  def claimedBy(self, branch, libname, libversion, omcversion, confighash):
    """The machine holding that job, for the message telling the user why we skip."""
    row = self.execute("""SELECT host, claimed_at FROM job_claim WHERE branch=? AND libname=?
                          AND libversion=? AND omcversion=? AND confighash=?""",
                       (branch, libname, libversion, omcversion, confighash)).fetchone()
    return row or ("unknown", None)

  def _startHeartbeat(self):
    if self.heartbeatThread is not None:
      return
    # A daemon thread: the run must not wait for it on the way out.
    def beat():
      while self.claims:
        time.sleep(HEARTBEAT_SECONDS)
        try:
          self._heartbeat()
        except Exception as e:
          print("Failed to update the job claims: %s" % e)
    self.heartbeatThread = threading.Thread(target=beat, daemon=True)
    self.heartbeatThread.start()

  def _heartbeat(self):
    # A separate connection: the main one is in the middle of the run's work.
    import psycopg2
    with psycopg2.connect(self.url) as conn:
      with conn.cursor() as cur:
        for (branch, libname, libversion, omcversion, confighash) in list(self.claims):
          cur.execute("""UPDATE job_claim SET heartbeat = now() WHERE branch=%s AND libname=%s
                         AND libversion=%s AND omcversion=%s AND confighash=%s AND host=%s""",
                      (branch, libname, libversion, omcversion, confighash, self.host))

  def release(self):
    for (b, libname, libversion, omcversion, confighash) in self.claims:
      self.execute("""UPDATE job_claim SET state='done', heartbeat=now()
                      WHERE branch=? AND libname=? AND libversion=? AND omcversion=? AND confighash=?
                        AND host=?""",
                   (b, libname, libversion, omcversion, confighash, self.host))
    self.claims = []
    self.commit()
