#!/usr/bin/env python3
"""
Remove one test run from the database, all of its result tables together.

  ./remove-run.py --db postgresql://om@localhost/omdb wasm-jit
  ./remove-run.py --db postgresql://om@localhost/omdb wasm-jit --write

The first says what it would delete, the second deletes it.  Without --date or
--omcversion it takes the newest run of that branch.

A run of test.py --wasmjitrunner or --fmisimulator fills several tables from one
job - wasm-jit, wasm-jit-me and wasm-jit-cs share a date - and removing only the
first would leave the others describing a run that no longer exists.  So every
table whose name is the branch or begins with it, and that has rows of that
date, goes at once; --also names any further table, for the --solver runners,
whose tables are named after the solver rather than the branch.

The rows of a run are in the result table, in omcversion and in libversion.  Its
job_claim rows are left alone: they say who tested a library last, the next run
overwrites them, and a finished claim stops nobody.
"""

import argparse, sys
from datetime import datetime, timezone
import resultsdb, shared


def runDate(cursor, branch, date, omcversion):
  """The date of the run being removed, and the omc that ran it."""
  if date and omcversion:
    raise SystemExit("Give --date or --omcversion, not both")
  if omcversion:
    where = "branch=? AND omcversion=?"
    params = (branch, omcversion)
  elif date:
    where = "branch=? AND date=?"
    params = (branch, date)
  else:
    where = "branch=?"
    params = (branch,)
  rows = cursor.execute("SELECT date, omcversion FROM omcversion WHERE %s ORDER BY date DESC"
                        % where, params).fetchall()
  if not rows:
    raise SystemExit("No run of %s in omcversion matching that" % branch)
  if omcversion and len(rows) > 1:
    raise SystemExit("%s ran %s %d times; name one of them with --date %s"
                     % (branch, omcversion, len(rows), " --date ".join(str(r[0]) for r in rows)))
  return rows[0]


def resultTables(cursor, db, branch, date, also):
  """The tables one job of that branch wrote: itself, whichever of its runners
  has rows of that date, and whatever --also names."""
  candidates = [t for t in db.tables() if t not in resultsdb.NON_RESULT_TABLES
                and t.startswith(branch + "-")]
  ran = [t for t in candidates
         if cursor.execute("SELECT COUNT(*) FROM %s WHERE date=?" % db.quote(t), (date,)).fetchone()[0]]
  return sorted(set([branch] + ran + list(also)))


def counts(cursor, db, tables, date):
  """How many rows each table holds for that run, in the order they are deleted."""
  out = []
  for table in tables:
    out.append((table, "date=?", (date,)))
  for table in ("omcversion", "libversion"):
    for name in tables:
      out.append((table, "branch=? AND date=?", (name, date)))
  return [(table, where, params,
           cursor.execute("SELECT COUNT(*) FROM %s WHERE %s" % (db.quote(table), where),
                          params).fetchone()[0])
          for (table, where, params) in out]


def main():
  parser = argparse.ArgumentParser(
      description="Remove one test run, all of its result tables together",
      formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
  parser.add_argument("branch", help="The branch whose run to remove, as it is named in the database")
  parser.add_argument("--date", type=int, help="The run to remove, as the epoch second in its date column")
  parser.add_argument("--omcversion", help="The run to remove, as the omc version that produced it")
  parser.add_argument("--also", action="append", default=[],
                      help="A further table the same job wrote, for --solver runners, whose tables "
                           "are named after the solver. Repeatable.")
  parser.add_argument("--write", action="store_true", help="Delete, instead of only saying what would be deleted")
  resultsdb.addArgument(parser)
  args = parser.parse_args()

  branch = shared.resultTable(args.branch)
  db = resultsdb.connect(args.db)
  cursor = db.cursor()

  (date, omcversion) = runDate(cursor, branch, args.date, args.omcversion)
  tables = resultTables(cursor, db, branch, date, args.also)
  print("%s run of %s, date %d (%s)"
        % (branch, omcversion, date, datetime.fromtimestamp(date, tz=timezone.utc).isoformat()))
  print("Result tables: %s" % ", ".join(tables))

  rows = counts(cursor, db, tables, date)
  for (table, where, params, n) in rows:
    print("  %-24s %6d rows  (%s)" % (table, n, " ".join(str(p) for p in params)))
  total = sum(n for (_, _, _, n) in rows)
  print("  %-24s %6d rows" % ("total", total))
  if not total:
    raise SystemExit("Nothing to remove")

  if not args.write:
    print("\nNothing deleted. Run it again with --write to delete.")
    return

  for (table, where, params, n) in rows:
    cursor.execute("DELETE FROM %s WHERE %s" % (db.quote(table), where), params)
  db.commit()

  left = [(table, n) for (table, where, params, n) in counts(cursor, db, tables, date) if n]
  if left:
    print("Still there after deleting: %s" % ", ".join("%s (%d)" % t for t in left))
    sys.exit(1)
  print("Removed %d rows." % total)
  db.vacuum()
  db.close()


if __name__ == "__main__":
  main()
