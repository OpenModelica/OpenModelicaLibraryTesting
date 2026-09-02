#!/usr/bin/env python3
"""
Collect the per-phase timings of the scalable libraries into a local sqlite3
file, for scaling-analyze.py to fit.

The result database only holds the coarse phases (frontend, backend, simcode,
templates, compile, simulate, verify) of every model. The published logs hold
more: the .err file has omc's execStat line for every pass of the translation,
and the .sim file has the runtime's LOG_STATS timers and counters. This script
reads the coarse phases of one run of a branch from the result database,
downloads the two logs of every model, and stores all of it:

  run        one row per (branch, library) with the date and versions
  model      the models, split into family (the name without _N_.._M_..) and size
  phase      the coarse phases, copied from the result database
  execstat   one row per execStat line of the translation, in log order
  simstat    the runtime's LOG_STATS timers
  simcounter the runtime's LOG_STATS counters (events, steps, jacobians)
  modelstat  a few numbers from the backend's "Model statistics" notification

The logs are cached in --logdir so that a second run only downloads what the
server has republished since (If-Modified-Since). The published logs are always
those of the latest run, and the result database gives the latest date, so the
two only disagree while a run is in progress.
"""

import argparse
import concurrent.futures
import email.utils
import os
import re
import sqlite3
import sys
import urllib.error
import urllib.request

import resultsdb

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
resultsdb.addArgument(parser)
parser.add_argument("--branch", default="master")
parser.add_argument("--libs", nargs="*", help="libraries to collect; default: every library named Scalable*")
parser.add_argument("--date", type=int, help="the run to read from the result database; default: the latest of each library")
parser.add_argument("--baseurl", default="https://libraries.openmodelica.org/branches")
parser.add_argument("--logdir", default="scaling-logs")
parser.add_argument("--out", default="scaling.db")
parser.add_argument("--jobs", type=int, default=8)
parser.add_argument("--offline", action="store_true", help="use the cached logs only")
args = parser.parse_args()

PHASES = ["exectime", "parsing", "frontend", "backend", "simcode", "templates", "compile", "simulate", "verify",
          "verifyfail", "verifytotal", "finalphase"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS run (
  branch text NOT NULL, libname text NOT NULL, date integer NOT NULL,
  omcversion text, libversion text, host text,
  PRIMARY KEY (branch, libname));
CREATE TABLE IF NOT EXISTS model (
  branch text NOT NULL, libname text NOT NULL, model text NOT NULL,
  family text NOT NULL, n integer, m integer, logtime integer, exitstatus integer,
  PRIMARY KEY (branch, libname, model));
CREATE TABLE IF NOT EXISTS phase (
  branch text NOT NULL, libname text NOT NULL, model text NOT NULL,
  %s,
  PRIMARY KEY (branch, libname, model));
CREATE TABLE IF NOT EXISTS execstat (
  branch text NOT NULL, libname text NOT NULL, model text NOT NULL,
  seq integer NOT NULL, key text NOT NULL, name text NOT NULL, section text,
  time real NOT NULL, cumulative real NOT NULL, alloc integer, alloctotal integer, n integer,
  PRIMARY KEY (branch, libname, model, seq));
CREATE TABLE IF NOT EXISTS simstat (
  branch text NOT NULL, libname text NOT NULL, model text NOT NULL,
  timer text NOT NULL, seconds real NOT NULL, percent real,
  PRIMARY KEY (branch, libname, model, timer));
CREATE TABLE IF NOT EXISTS simcounter (
  branch text NOT NULL, libname text NOT NULL, model text NOT NULL,
  counter text NOT NULL, value real NOT NULL,
  PRIMARY KEY (branch, libname, model, counter));
CREATE TABLE IF NOT EXISTS modelstat (
  branch text NOT NULL, libname text NOT NULL, model text NOT NULL,
  stat text NOT NULL, value integer NOT NULL,
  PRIMARY KEY (branch, libname, model, stat));
""" % ",\n  ".join("%s real" % p for p in PHASES)

UNITS = {"": 1, "kB": 1024, "MB": 1024**2, "GB": 1024**3, "TB": 1024**4}

# "time 0.01324/0.01786, allocations: 20.94 MB / 474.6 MB, free: ..."
EXECSTAT = re.compile(r"Notification: Performance of (?P<name>.*?): time (?P<time>[0-9.eE+-]+)/(?P<cum>[0-9.eE+-]+), "
                      r"allocations: (?P<alloc>[0-9.eE+-]+) ?(?P<au>[kMGT]?B)? / (?P<total>[0-9.eE+-]+) ?(?P<tu>[kMGT]?B)?")
SIZE = re.compile(r"\s*\(n=(\d+)(?: -> n=(\d+))?\)")
SECTION = re.compile(r"\s*\((initialization\w*|simulation)\)$")
FAMILY = re.compile(r"^(?P<family>.*?)(?:_N_(?P<n>\d+))?(?:_M_(?P<m>\d+))?$")
# "|                 | |       | | |     0.424875s [ 70.7%] event-handling"
SIMTIMER = re.compile(r"^\|[ |]*([0-9.eE+-]+)s(?: \[ *(-?[0-9.]+)%\])? +(.+?)\s*$")
SIMCOUNT = re.compile(r"^\|[ |]*([0-9.eE+-]+)s? +(.+?)\s*$")
MODELSTAT = {
  "states": re.compile(r"\* Number of states: (\d+)"),
  "discrete": re.compile(r"\* Number of discrete variables: (\d+)"),
  "subsystems": re.compile(r"\* Number of independent subsystems: (\d+)"),
  "components": re.compile(r"Strong component statistics for simulation \((\d+)\)"),
  "torn": re.compile(r"\* Torn equation systems: (\d+)"),
  "systems": re.compile(r"\* Equation systems \(not torn\): (\d+)"),
}
SYSTEMSIZE = re.compile(r"\{?\((\d+),[0-9.]+%\)")
# omc prints the execStat notifications when the command returns, so a killed
# translation leaves none: the exit status is all the log says about it.
EXITSTATUS = re.compile(r"^OMC exited with status (\d+) ")


def bytes(value, unit):
  return int(float(value) * UNITS[unit or ""])


def parseErr(text):
  """The execStat lines and the model statistics of a translation log.

  Only the model's own translation counts: the loadFile lines before it are
  the parsing phase, which the result database already times as one number.
  """
  stats = []
  seen = {}
  translating = False
  modelstat = {}
  largest = 0
  exitstatus = None
  for line in text.splitlines():
    if line.startswith("translateModel(") or line.startswith("buildModel(") or line.startswith("simulate("):
      translating = True
    m = EXITSTATUS.match(line)
    if m:
      exitstatus = int(m.group(1))
    m = EXECSTAT.search(line)
    if m and translating:
      name = m.group("name")
      n = SIZE.search(name)
      if n:
        name = name[:n.start()] + name[n.end():]
      s = SECTION.search(name)
      key = name
      count = seen.get(key, 0)
      seen[key] = count + 1
      if count:
        key = "%s#%d" % (key, count + 1)
      stats.append({
        "seq": len(stats), "key": key, "name": name, "section": s.group(1) if s else None,
        "time": float(m.group("time")), "cumulative": float(m.group("cum")),
        "alloc": bytes(m.group("alloc"), m.group("au")), "alloctotal": bytes(m.group("total"), m.group("tu")),
        "n": int(n.group(1)) if n else None,
      })
      continue
    # The initialization system's statistics come first; the simulation system's last.
    for stat, rx in MODELSTAT.items():
      m = rx.search(line)
      if m:
        modelstat[stat] = int(m.group(1))
    for m in SYSTEMSIZE.finditer(line):
      largest = max(largest, int(m.group(1)))
  if largest:
    modelstat["largestsystem"] = largest
  return stats, modelstat, exitstatus


def parseSim(text):
  """The LOG_STATS timers and counters of a simulation log."""
  timers, counters = {}, {}
  inStats = False
  for line in text.splitlines():
    if "### STATISTICS ###" in line:
      inStats = True
      continue
    if not inStats:
      continue
    if not line.startswith("|"):
      break
    m = SIMTIMER.match(line)
    if m:
      timers[m.group(3)] = (float(m.group(1)), float(m.group(2)) if m.group(2) else None)
      continue
    m = SIMCOUNT.match(line)
    if m:
      counters[m.group(2)] = float(m.group(1))
  return timers, counters


def fetch(url, path):
  """Download url to path unless the cached copy is as new as the server's."""
  headers = {}
  if os.path.exists(path):
    headers["If-Modified-Since"] = email.utils.formatdate(os.path.getmtime(path), usegmt=True)
  try:
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=120) as r:
      data = r.read()
      modified = r.headers.get("Last-Modified")
  except urllib.error.HTTPError as e:
    if e.code == 304:
      return True
    if e.code == 404:
      return False
    raise
  with open(path, "wb") as fp:
    fp.write(data)
  if modified:
    t = email.utils.parsedate_to_datetime(modified).timestamp()
    os.utime(path, (t, t))
  return True


def collect(lib, model):
  prefix = "%s_%s" % (lib, model)
  dir = os.path.join(args.logdir, args.branch, lib)
  os.makedirs(dir, exist_ok=True)
  found = {}
  for ext in ("err", "sim"):
    path = os.path.join(dir, prefix + "." + ext)
    if not args.offline:
      try:
        found[ext] = fetch("%s/%s/%s/files/%s.%s" % (args.baseurl, args.branch, lib, prefix, ext), path)
      except (urllib.error.URLError, OSError) as e:
        print("%s: %s" % (path, e), file=sys.stderr)
        found[ext] = os.path.exists(path)
    else:
      found[ext] = os.path.exists(path)
  result = {"model": model, "logtime": None, "exitstatus": None}
  path = os.path.join(dir, prefix + ".err")
  if found["err"]:
    result["logtime"] = int(os.path.getmtime(path))
    with open(path, errors="replace") as fp:
      result["execstat"], result["modelstat"], result["exitstatus"] = parseErr(fp.read())
  path = os.path.join(dir, prefix + ".sim")
  if found["sim"]:
    with open(path, errors="replace") as fp:
      result["simstat"], result["simcounter"] = parseSim(fp.read())
  return result


def store(out, lib, results):
  key = (args.branch, lib)
  for r in results:
    model = r["model"]
    m = FAMILY.match(model)
    out.execute("INSERT OR REPLACE INTO model VALUES (?,?,?,?,?,?,?,?)",
                key + (model, m.group("family"), m.group("n") and int(m.group("n")),
                       m.group("m") and int(m.group("m")), r["logtime"], r["exitstatus"]))
    for table in ("execstat", "simstat", "simcounter", "modelstat"):
      out.execute("DELETE FROM %s WHERE branch=? AND libname=? AND model=?" % table, key + (model,))
    for s in r.get("execstat", []):
      out.execute("INSERT INTO execstat VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                  key + (model, s["seq"], s["key"], s["name"], s["section"], s["time"], s["cumulative"],
                         s["alloc"], s["alloctotal"], s["n"]))
    for stat, value in r.get("modelstat", {}).items():
      out.execute("INSERT INTO modelstat VALUES (?,?,?,?,?)", key + (model, stat, value))
    for timer, (seconds, percent) in r.get("simstat", {}).items():
      out.execute("INSERT INTO simstat VALUES (?,?,?,?,?,?)", key + (model, timer, seconds, percent))
    for counter, value in r.get("simcounter", {}).items():
      out.execute("INSERT INTO simcounter VALUES (?,?,?,?,?)", key + (model, counter, value))


def connectResults(url):
  """The result database; the SSH tunnel to omdb hangs on connect when it is stale."""
  if url.startswith("postgres") and "connect_timeout" not in url:
    url += ("&" if "?" in url else "?") + "connect_timeout=10"
  try:
    return resultsdb.connect(url)
  except Exception as e:
    raise SystemExit("cannot connect to %s: %s\nIf this is the omdb tunnel, ask for it to be restarted." % (url, e))


def main():
  db = connectResults(args.db)
  table = db.quote(args.branch)
  if args.libs:
    libs = args.libs
  else:
    libs = [r[0] for r in db.execute("SELECT DISTINCT libname FROM %s WHERE libname LIKE 'Scalable%%' ORDER BY libname" % table)]
  out = sqlite3.connect(args.out)
  out.executescript(SCHEMA)
  for lib in libs:
    date = args.date
    if date is None:
      date = db.execute("SELECT MAX(date) FROM %s WHERE libname=?" % table, (lib,)).fetchone()[0]
    if date is None:
      print("%s: no results for branch %s" % (lib, args.branch), file=sys.stderr)
      continue
    omcversion = db.execute("SELECT omcversion FROM omcversion WHERE branch=? AND date=?", (args.branch, date)).fetchone()
    libversion = db.execute("SELECT libversion, host FROM libversion WHERE branch=? AND date=? AND libname=?",
                            (args.branch, date, lib)).fetchone()
    rows = db.execute("SELECT model, %s FROM %s WHERE libname=? AND date=? ORDER BY model" % (", ".join(PHASES), table),
                      (lib, date)).fetchall()
    print("%s: %d models, run %d, %s" % (lib, len(rows), date, omcversion[0] if omcversion else "?"))
    out.execute("INSERT OR REPLACE INTO run VALUES (?,?,?,?,?,?)",
                (args.branch, lib, date, omcversion and omcversion[0], libversion and libversion[0], libversion and libversion[1]))
    out.execute("DELETE FROM phase WHERE branch=? AND libname=?", (args.branch, lib))
    for row in rows:
      out.execute("INSERT INTO phase VALUES (?,?,?%s)" % (",?" * len(PHASES)), (args.branch, lib) + tuple(row))
    with concurrent.futures.ThreadPoolExecutor(args.jobs) as pool:
      results = list(pool.map(lambda row: collect(lib, row[0]), rows))
    store(out, lib, results)
    out.commit()
    missing = [r["model"] for r in results if r["logtime"] is None]
    if missing:
      print("%s: no .err log for %d models, e.g. %s" % (lib, len(missing), missing[0]), file=sys.stderr)
  out.close()


main()
