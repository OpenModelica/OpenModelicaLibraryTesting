#!/usr/bin/env python3
"""
Propose the models for configs/heavy-models.json, from the memory the database
has seen them use.

  ./heavy-models.py --db postgresql://omread@localhost/omdb
  ./heavy-models.py --db postgresql://omread@localhost/omdb --threshold 2 > configs/heavy-models.json

It prints the file and never writes it: the list is meant to be read and edited
before it is used.  What it proposes is the most a model has been measured at
over the newest runs of every branch given, because a model that dies early on
one branch reports what it had reached rather than what it needs - the several
dozen models that report 7.01 GiB on the C branches are all sitting on the
8 GB `ulimit -v`, not asking for 7 GiB.  So the maximum over branches is a lower
bound worth believing, and a single branch is not.

Runs older than the maxrss column read 0 and are skipped; a model that has never
completed anywhere cannot be proposed at all, and is reported instead.
"""

import argparse, collections, sys
import simplejson as json
import resultsdb, shared

GiB = float(1 << 30)

# Right at a ulimit -v is where a translation died, not what it wanted.
ULIMIT_WALL_GiB = [7.01, 15.01]
ULIMIT_WALL_TOLERANCE = 0.02


def atUlimitWall(gib):
  return any(abs(gib - wall) < ULIMIT_WALL_TOLERANCE for wall in ULIMIT_WALL_GiB)


def peaks(cursor, db, branches, runs):
  """The most every model has been seen to use, and which branch saw it."""
  best = {}
  for branch in branches:
    dates = [row[0] for row in cursor.execute(
        "SELECT DISTINCT date FROM %s ORDER BY date DESC LIMIT %d" % (db.quote(branch), runs))]
    if not dates:
      print("No results for branch %s" % branch)
      continue
    holes = ",".join("?" * len(dates))
    for (libname, model, maxrss) in cursor.execute(
        "SELECT libname, model, MAX(maxrss) FROM %s WHERE date IN (%s) AND maxrss > 0 "
        "GROUP BY libname, model" % (db.quote(branch), holes), tuple(dates)):
      key = (libname, model)
      if maxrss / GiB > best.get(key, (0.0, None))[0]:
        best[key] = (maxrss / GiB, branch)
  return best


def unmeasured(cursor, db, branches, runs):
  """Models no run has ever reported memory for: killed before they could, or
  only ever tested before the column existed."""
  seen = set()
  measured = set()
  for branch in branches:
    dates = [row[0] for row in cursor.execute(
        "SELECT DISTINCT date FROM %s ORDER BY date DESC LIMIT %d" % (db.quote(branch), runs))]
    if not dates:
      continue
    holes = ",".join("?" * len(dates))
    for (libname, model, maxrss) in cursor.execute(
        "SELECT libname, model, MAX(maxrss) FROM %s WHERE date IN (%s) AND finalphase >= 0 "
        "GROUP BY libname, model" % (db.quote(branch), holes), tuple(dates)):
      seen.add((libname, model))
      if maxrss:
        measured.add((libname, model))
  return seen - measured


def main():
  parser = argparse.ArgumentParser(
      description="Propose the heavy-model list from measured memory use",
      formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
  parser.add_argument("--branch", default="master wasm-jit cpp newInst-newBackend",
                      help="Branches whose results are read, separated by spaces. Each model is "
                           "credited with the most any of them used.")
  parser.add_argument("--runs", type=int, default=20,
                      help="How many of the newest runs of each branch to read (default 20)")
  parser.add_argument("--threshold", type=float, default=4.0,
                      help="How many GiB a model has to have used to be proposed (default 4)")
  resultsdb.addArgument(parser)
  args = parser.parse_args()

  db = resultsdb.connect(args.db)
  cursor = db.cursor()
  branches = [shared.resultTable(b) for b in args.branch.split(" ") if b]

  best = peaks(cursor, db, branches, args.runs)
  out = collections.defaultdict(dict)
  walls = []
  for ((libname, model), (gib, branch)) in best.items():
    if gib < args.threshold:
      continue
    if atUlimitWall(gib):
      walls.append((libname, model, gib))
    out[libname][model] = round(gib, 2)

  print(json.dumps(dict((lib, dict(sorted(models.items()))) for (lib, models) in sorted(out.items())),
                   indent=1, sort_keys=True))

  # The report goes to stderr, so that stdout is the file.
  heavy = sum(len(models) for models in out.values())
  report = ["%d models over %g GiB in %d libraries" % (heavy, args.threshold, len(out))]
  for (libname, model, gib) in sorted(walls):
    report.append("  ! %s %s stopped at %.2f GiB, which is a ulimit -v rather than what it needs"
                  % (libname, model, gib))
  never = unmeasured(cursor, db, branches, args.runs)
  if never:
    report.append("  ? %d models have never reported memory (killed before writing, or only "
                  "tested before the column existed); they are scheduled as light ones" % len(never))
  sys.stderr.write("\n".join(report) + "\n")


if __name__ == "__main__":
  main()
