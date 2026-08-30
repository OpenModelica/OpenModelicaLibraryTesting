#!/usr/bin/env python3
"""
Set how long every model of a library may spend simulating, from what it has
spent: `ulimitExe` for the library, `ulimitExeModels` for the models that have
earned longer than that.

  ./update-ulimit-exe.py --db postgresql://om@openmodelica.org/omdb configs/conf.json
  ./update-ulimit-exe.py --db postgresql://om@openmodelica.org/omdb --write configs/*.json

The first prints what would change, the second changes it in place, leaving the
rest of the file - key order, indentation, tabs and all - alone.  Neither writes
to the database, so a read-only user is enough for both.

A model is allowed --factor times the longest it has taken over --runs runs of
--branch, master by default: it runs on the slower of the test machines, so a
model fast enough there is fast enough everywhere.  Both halves of that matter -
the same model has been seen to take six times its usual time when the machine
is busy, so a handful of runs does not show what a model needs, and the longest
of a few months of them still wants a margin on top.  Only runs that finished
simulating are read; one killed by the timeout has no time to measure, and is
reported rather than guessed at.
"""

import argparse, math, re
import simplejson as json
import resultsdb, shared

# Rounding the timeouts keeps a re-run from rewriting them over rounding noise.
STEP = 30

# A run that spent this much of its timeout and still failed was killed by it.
KILLED_FRACTION = 0.95


def roundUp(seconds):
  return int(math.ceil(seconds / float(STEP)) * STEP)


def lastRuns(cursor, db, branch, runs):
  """The dates of the newest runs of that branch, newest first."""
  return [row[0] for row in cursor.execute(
      "SELECT DISTINCT date FROM %s ORDER BY date DESC LIMIT %d" % (db.quote(branch), runs))]


def simulationTimes(cursor, db, branches, runs):
  """For every model of every library, the longest it has been seen to simulate
  and the longest it ran before failing, over the newest runs of each branch."""
  best = {}
  failed = {}
  for branch in branches:
    dates = lastRuns(cursor, db, branch, runs)
    if not dates:
      print("No results for branch %s" % branch)
      continue
    holes = ",".join("?" * len(dates))
    for (libname, model, finalphase, simulate) in cursor.execute(
        "SELECT libname, model, finalphase, MAX(simulate) FROM %s WHERE date IN (%s) "
        "GROUP BY libname, model, finalphase" % (db.quote(branch), holes), tuple(dates)):
      key = (libname, model)
      target = best if finalphase >= 6 else failed
      target[key] = max(target.get(key, 0.0), simulate)
  return (best, failed)


def libraryLimit(entry, default):
  """The timeout the models of that library get without one of their own."""
  return int(entry.get("ulimitExe") or default)


def wanted(entry, libname, best, failed, default, factor):
  """That library's timeout, the models allowed longer and the models that were
  killed, or None for a library the database has never heard of - guessing there
  would replace a hand-written timeout with a default nobody measured."""
  measured = dict((model, t) for ((lib, model), t) in best.items() if lib == libname)
  killed = dict((model, t) for ((lib, model), t) in failed.items() if lib == libname)
  if not measured and not killed:
    return None
  # A timeout under the default is a deliberately short one and stays; a longer
  # one is what the named models replaced.
  limit = min(libraryLimit(entry, default), default)
  models = dict((model, roundUp(t * factor)) for (model, t) in measured.items() if t > limit)
  inForce = lambda model: (entry.get("ulimitExeModels") or {}).get(model) \
      or libraryLimit(entry, default)
  wasKilled = sorted(model for (model, t) in killed.items()
                     if t >= KILLED_FRACTION * inForce(model))
  return (limit, models, wasKilled)


def entrySpans(text):
  """Where each library entry starts and ends: the objects directly inside the
  outermost list. The files are edited as text rather than re-serialised, so
  that setting one number does not reformat the other ninety-five entries."""
  spans = []
  depth = 0
  start = None
  inString = False
  escaped = False
  for (i, ch) in enumerate(text):
    if inString:
      if escaped:
        escaped = False
      elif ch == "\\":
        escaped = True
      elif ch == '"':
        inString = False
      continue
    if ch == '"':
      inString = True
    elif ch in "[{":
      depth = depth + 1
      if depth == 2 and ch == "{":
        start = i
    elif ch in "]}":
      if depth == 2 and ch == "}" and start is not None:
        spans.append((start, i + 1))
        start = None
      depth = depth - 1
  return spans


keyRe = re.compile(r'^(\s*)"([A-Za-z]+)"\s*:')

# A new timeout goes after these, where the hand-written ones are.
AFTER_KEYS = ["ulimitOmc", "libraryVersionNameForTests", "libraryVersionExactMatch",
              "libraryVersion", "library"]


def rewriteEntry(entry, limit, models, default):
  """That entry's text with its timeouts replaced by these, and nothing else
  touched. The keys are dropped rather than written out when they say nothing."""
  lines = entry.split("\n")
  out = []
  indent = "    "
  skipTo = None
  for (i, line) in enumerate(lines):
    if skipTo is not None:
      if i < skipTo:
        continue
      skipTo = None
    m = keyRe.match(line)
    if m and m.group(2) in ("ulimitExe", "ulimitExeModels"):
      indent = m.group(1)
      if m.group(2) == "ulimitExeModels" and not line.rstrip().endswith(("}", "},")):
        # A block spanning several lines ends at the first line that closes it.
        skipTo = next(j for j in range(i + 1, len(lines))
                      if lines[j].strip() in ("}", "},")) + 1
      continue
    if m and m.group(2) in AFTER_KEYS:
      indent = m.group(1)
    out.append(line)
  written = []
  if limit != default:
    written.append('%s"ulimitExe":%d,' % (indent, limit))
  if models:
    written.append('%s"ulimitExeModels":{' % indent)
    for (i, model) in enumerate(sorted(models)):
      written.append('%s  "%s":%d%s' % (indent, model, models[model],
                                        "" if i == len(models) - 1 else ","))
    written.append("%s}," % indent)
  # After the last of the keys that name the library, or first if it has none.
  at = 1
  for (i, line) in enumerate(out):
    m = keyRe.match(line)
    if m and m.group(2) in AFTER_KEYS:
      at = i + 1
  lines = out[:at] + written + out[at:]
  # Inserting or removing a block moves which key is the last one, the only one
  # without a comma.
  if written and at > 0:
    lines[at - 1] = lines[at - 1].rstrip().rstrip(",") + ","
  if len(lines) > 1 and lines[-1].strip() == "}":
    lines[-2] = lines[-2].rstrip().rstrip(",")
  return "\n".join(lines)


def describe(libname, entry, limit, models, wasKilled, default):
  """What changes for that library, or nothing when it already says this."""
  was = (libraryLimit(entry, default), entry.get("ulimitExeModels") or {})
  now = (limit, models)
  lines = []
  if was[0] != now[0]:
    lines.append("  timeout %ds -> %ds" % (was[0], now[0]))
  for model in sorted(set(list(was[1]) + list(now[1]))):
    old = was[1].get(model)
    new = now[1].get(model)
    if old == new:
      continue
    elif old is None:
      lines.append("  + %s %ds" % (model, new))
    elif new is None:
      lines.append("  - %s (was %ds, no longer needed)" % (model, old))
    else:
      lines.append("  ~ %s %ds -> %ds" % (model, old, new))
  for model in wasKilled:
    lines.append("  ! %s ran into the timeout in force, so there is nothing to measure" % model)
  if lines:
    lines.insert(0, "%s:" % libname)
  return lines


def main():
  parser = argparse.ArgumentParser(
      description="Set the simulation timeouts of the tested libraries from their results",
      formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
  parser.add_argument("configs", nargs="+")
  parser.add_argument("--branch", default="master",
                      help="Branch whose results decide the timeouts, or several separated by "
                           "spaces, in which case each model is allowed what the slowest of them "
                           "needed. Defaults to master, which runs on the slower test machines.")
  parser.add_argument("--runs", type=int, default=100,
                      help="How many of the newest runs of each branch to read (default 100). "
                           "Fewer than a few dozen and the occasional slow run is missed.")
  parser.add_argument("--factor", type=float, default=1.25,
                      help="How much longer than it has ever taken a model is allowed "
                           "(default 1.25)")
  parser.add_argument("--default", type=int, default=shared.DEFAULT_ULIMIT_EXE,
                      help="The timeout a model gets when nothing asks for another, which is "
                           "what shared.py says unless overridden here")
  parser.add_argument("--write", action="store_true",
                      help="Change the configuration files instead of only saying what would change")
  resultsdb.addArgument(parser)
  args = parser.parse_args()

  db = resultsdb.connect(args.db)
  cursor = db.cursor()
  branches = [shared.resultTable(b) for b in args.branch.split(" ") if b]
  (best, failed) = simulationTimes(cursor, db, branches, args.runs)

  changed = False
  for path in args.configs:
    entries = shared.readConfig(path)
    text = open(path).read()
    spans = entrySpans(text)
    if len(spans) != len(entries):
      raise SystemExit("%s: found %d entries but %d objects in the file"
                       % (path, len(entries), len(spans)))
    report = []
    pieces = []
    intended = []
    at = 0
    for ((library, conf), (start, end)) in zip(entries, spans):
      raw = conf["configFromFile"]
      libname = shared.libname(library, conf)
      w = wanted(raw, libname, best, failed, args.default, args.factor)
      pieces.append(text[at:start])
      at = end
      if w is None:
        report.append("%s: no results on %s, left alone" % (libname, ", ".join(branches)))
        pieces.append(text[start:end])
        intended.append(dict(raw))
        continue
      (limit, models, wasKilled) = w
      report.extend(describe(libname, raw, limit, models, wasKilled, args.default))
      pieces.append(rewriteEntry(text[start:end], limit, models, args.default))
      entry = dict(raw)
      entry.pop("ulimitExe", None)
      entry.pop("ulimitExeModels", None)
      if limit != args.default:
        entry["ulimitExe"] = limit
      if models:
        entry["ulimitExeModels"] = models
      intended.append(entry)
    pieces.append(text[at:])
    new = "".join(pieces)

    print("== %s" % path)
    print("\n".join(report) if report else "  nothing to change")
    if new == text:
      continue
    changed = True
    # Editing the text keeps the formatting; it must not cost the contents.
    if json.loads(new) != intended:
      raise SystemExit("%s: the rewritten file does not say what it was meant to say; "
                       "not writing it" % path)
    if args.write:
      open(path, "w").write(new)
      print("  written")

  if changed and not args.write:
    print("\nNothing was written. Pass --write to change the files.")


if __name__ == "__main__":
  main()
