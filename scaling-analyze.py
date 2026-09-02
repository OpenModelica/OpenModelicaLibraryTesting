#!/usr/bin/env python3
"""
Find the phases that scale badly in the scalable libraries.

Reads the sqlite3 file scaling-extract.py wrote. The models of a family, say
BreakerNetwork_N_10_M_10 .. BreakerNetwork_N_1280_M_10, form series in which
one name parameter varies (M=10, N varies; N=160, M varies; or N=M, the size
being N*M). For every series and every timing - the coarse phases of the
result database, every execStat pass of the translation, every LOG_STATS timer
of the runtime - the time is fitted as t = c * size^exponent over the largest
points, and the series is reported when the exponent is above --threshold and
the time at the largest size is above --mintime.

The size is the number of equations the backend reports for the model, so
that the exponent means the same thing whatever the name parameters count:
the grids of ScalableTestGrids have N^2 equations for a given N. Where the
equation count does not grow along the series (BreakerNetworkDelayed's M is
the delay count) the size is the name parameter, and the x column says which.

The models that did not finish at the largest sizes are listed too: a phase
that times out is the worst scaling there is, and has no time to fit.
"""

import argparse
import collections
import math
import sqlite3

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("--db", default="scaling.db")
parser.add_argument("--branch", default="master")
parser.add_argument("--libs", nargs="*", help="default: every library in the file")
parser.add_argument("--family", help="only families whose name contains this")
parser.add_argument("--threshold", type=float, default=1.5, help="report exponents at or above this (default 1.5)")
parser.add_argument("--mintime", type=float, default=1.0, help="report only times at the largest size above this many seconds (default 1)")
parser.add_argument("--points", type=int, default=4, help="fit over the largest N sizes that ran (default 4)")
parser.add_argument("--floor", type=float, default=0.02, help="ignore times below this in the fit: they are overhead, not the phase")
parser.add_argument("--metric", choices=["time", "alloc"], default="time", help="fit the execStat times or their allocations")
parser.add_argument("--all", action="store_true", help="print every series, not only the badly scaling ones")
parser.add_argument("--phases-only", action="store_true", help="skip the execStat passes and runtime timers")
args = parser.parse_args()

PHASES = ["frontend", "backend", "simcode", "templates", "compile", "simulate", "verify", "exectime"]
# finalphase counts the phases that completed, parsing being the first; the
# time of the phase after it is how long the failure took, not the phase.
PHASEINDEX = {"parsing": 0, "frontend": 1, "backend": 2, "simcode": 3, "templates": 4, "compile": 5, "simulate": 6,
              "verify": 7, "exectime": 7}
FAILEDIN = {0: "frontend", 1: "backend", 2: "simcode", 3: "templates", 4: "compile", 5: "simulate", 6: "verify"}
SIGNALS = {137: "killed", 142: "alarm"}

Point = collections.namedtuple("Point", "size model eqs")


def series(models, eqs):
  """Split a family's models into series that vary one name parameter.

  models: {model: (n, m)}.  Yields (label, axis, [Point]) with the points
  ordered by size; a series needs three sizes to fit anything.
  """
  byN, byM, diag = collections.defaultdict(dict), collections.defaultdict(dict), {}
  for model, (n, m) in models.items():
    if n is None:
      continue
    if m is None:
      byM[None][n] = model
      continue
    byM[m][n] = model
    byN[n][m] = model
    if n == m:
      diag[n * m] = model
  out = []
  for m, points in byM.items():
    if len(points) >= 3:
      out.append(("N" if m is None else "M=%d, N varies" % m, "N", points))
  for n, points in byN.items():
    if len(points) >= 3:
      out.append(("N=%d, M varies" % n, "M", points))
  if len(diag) >= 3:
    out.append(("N=M", "N*M", diag))
  for label, axis, points in out:
    yield label, axis, [Point(size, points[size], eqs.get(points[size])) for size in sorted(points)]


def fit(points):
  """Least-squares slope of log t over log size, and the slope of the last pair.

  points: [(size, t)] in size order, t > 0.
  """
  xs = [math.log(s) for s, t in points]
  ys = [math.log(t) for s, t in points]
  n = len(xs)
  mx, my = sum(xs) / n, sum(ys) / n
  sxx = sum((x - mx) ** 2 for x in xs)
  slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx if sxx else float("nan")
  tail = (ys[-1] - ys[-2]) / (xs[-1] - xs[-2]) if n >= 2 and xs[-1] != xs[-2] else float("nan")
  return slope, tail


class Analysis:
  def __init__(self, db, lib):
    self.db = db
    self.lib = lib
    self.branch = args.branch
    self.models = {}
    self.phase = {}
    self.exitstatus = {}
    # The first pass that reports its size is "pre-optimization done (n=...)".
    self.eqs = dict(db.execute(
      "SELECT model, n FROM execstat e WHERE branch=? AND libname=? AND seq="
      "(SELECT MIN(seq) FROM execstat x WHERE x.branch=e.branch AND x.libname=e.libname AND x.model=e.model AND x.n IS NOT NULL)",
      (self.branch, lib)))
    for model, family, n, m, exitstatus, *phases in db.execute(
        "SELECT m.model, m.family, m.n, m.m, m.exitstatus, %s, p.finalphase FROM model m JOIN phase p "
        "ON p.branch=m.branch AND p.libname=m.libname AND p.model=m.model WHERE m.branch=? AND m.libname=?"
        % ", ".join("p." + p for p in PHASES), (self.branch, lib)):
      self.models[model] = (family, n, m)
      self.phase[model] = dict(zip(PHASES + ["finalphase"], phases))
      self.exitstatus[model] = exitstatus

  def values(self, table, column, key, keycolumn):
    return dict(self.db.execute(
      "SELECT model, %s FROM %s WHERE branch=? AND libname=? AND %s=?" % (column, table, keycolumn),
      (self.branch, self.lib, key)))

  def timings(self):
    """Every timing there is, as (group, name, {model: value})."""
    for phase in PHASES:
      yield "phase", phase, {m: p[phase] for m, p in self.phase.items()
                             if p[phase] > 0 and p["finalphase"] >= PHASEINDEX[phase]}
    if args.phases_only:
      return
    column = "time" if args.metric == "time" else "alloc"
    keys = [r[0] for r in self.db.execute(
      "SELECT key FROM execstat WHERE branch=? AND libname=? GROUP BY key ORDER BY MIN(seq)", (self.branch, self.lib))]
    for key in keys:
      yield "pass", key, self.values("execstat", column, key, "key")
    if args.metric != "time":
      return
    for (timer,) in self.db.execute(
        "SELECT DISTINCT timer FROM simstat WHERE branch=? AND libname=? ORDER BY timer", (self.branch, self.lib)):
      yield "runtime", timer, self.values("simstat", "seconds", timer, "timer")

  def report(self):
    families = collections.defaultdict(dict)
    for model, (family, n, m) in self.models.items():
      if not args.family or args.family in family:
        families[family][model] = (n, m)
    allSeries = []
    for family in sorted(families):
      for label, axis, points in series(families[family], self.eqs):
        allSeries.append((family, label, axis, points))
    if not allSeries:
      return
    print("=" * 100)
    print("%s (%s)" % (self.lib, self.branch))
    print("=" * 100)
    self.failures(allSeries)
    findings = []
    for group, name, values in self.timings():
      for family, label, axis, points in allSeries:
        f = self.fitSeries(points, axis, values)
        if f is None:
          continue
        slope, tail, x, largest, tmax, count = f
        bad = slope >= args.threshold and tmax >= args.mintime
        if bad or args.all:
          findings.append((family, label, group, name, slope, tail, x, largest, tmax, count))
    if not findings:
      print("nothing scales worse than size^%g above %g s\n" % (args.threshold, args.mintime))
      return findings
    unit = "s" if args.metric == "time" else "B"
    print("%-6s %-6s %-6s %-4s %8s %9s %-7s  %s" % ("exp", "tail", "points", "x", "largest", "t(max)", "", "phase / pass / timer"))
    for family, label in sorted({(f, l) for f, l, *_ in findings}):
      print("\n%s\n  series %s" % (family, label))
      rows = [f for f in findings if f[0] == family and f[1] == label]
      for _, _, group, name, slope, tail, x, largest, tmax, count in sorted(rows, key=lambda f: -f[8]):
        print("  %-6.2f %-6.2f %-6d %-4s %8d %9s %-7s %s" % (slope, tail, count, x, largest, self.fmt(tmax, unit), group, name))
    print()
    return findings

  def fitSeries(self, points, axis, values):
    """Fit the largest --points sizes of a series that have a value above --floor.

    The size is the equation count when every point has one and it grows
    along the series, else the name parameter.
    """
    ran = [p for p in points if p.model in values and values[p.model] >= args.floor][-args.points:]
    if len(ran) < 3:
      return None
    eqs = [p.eqs for p in ran]
    if all(eqs) and all(a < b for a, b in zip(eqs, eqs[1:])):
      x, sizes = "eqs", eqs
    else:
      x, sizes = axis, [p.size for p in ran]
    slope, tail = fit([(size, values[p.model]) for size, p in zip(sizes, ran)])
    return slope, tail, x, sizes[-1], values[ran[-1].model], len(ran)

  def failures(self, allSeries):
    """The models of each series that did not simulate; a failed verification is not a scaling problem."""
    seen = set()
    lines = []
    for family, label, axis, points in allSeries:
      for p in points:
        final = int(self.phase[p.model]["finalphase"])
        if final < 6 and p.model not in seen:
          seen.add(p.model)
          exectime = self.phase[p.model]["exectime"]
          status = self.exitstatus[p.model]
          if status is not None and final < 5:
            # omc died before it could say how far it got; the timer ladder then says "frontend"
            where = "omc %s" % SIGNALS.get(status, "exit %d" % status)
          else:
            where = FAILEDIN[final]
          lines.append("  %-11s %8.0f s  %s" % (where, exectime, p.model))
    if lines:
      print("did not simulate (phase that failed, total time):")
      print("\n".join(lines))
      print()

  @staticmethod
  def fmt(value, unit):
    if unit == "B":
      for u in ["B", "kB", "MB", "GB", "TB"]:
        if value < 1024 or u == "TB":
          return "%.3g %s" % (value, u)
        value /= 1024
    return "%.3g s" % value


def main():
  db = sqlite3.connect(args.db)
  libs = args.libs or [r[0] for r in db.execute("SELECT libname FROM run WHERE branch=? ORDER BY libname", (args.branch,))]
  for (lib, date, omcversion) in db.execute(
      "SELECT libname, date, omcversion FROM run WHERE branch=? ORDER BY libname", (args.branch,)):
    if lib in libs:
      print("%s: run %d, %s" % (lib, date, omcversion))
  print()
  findings = []
  for lib in libs:
    findings += [(lib,) + f for f in Analysis(db, lib).report() or []]
  summary(findings)


def summary(findings):
  """Every phase, pass and timer that scales badly somewhere, worst time first."""
  if not findings or args.all:
    return
  byName = collections.defaultdict(list)
  for lib, family, label, group, name, slope, tail, x, largest, tmax, count in findings:
    byName[(group, name)].append((tmax, slope, family.split(".")[-1], lib))
  print("=" * 100)
  print("summary: series where each phase, pass or timer scales badly (t(max), exponent, family, library)")
  print("=" * 100)
  for (group, name), rows in sorted(byName.items(), key=lambda kv: -max(r[0] for r in kv[1])):
    rows.sort(reverse=True)
    print("%-7s %s: %d series" % (group, name, len(rows)))
    for tmax, slope, family, lib in rows[:5]:
      print("    %8.3g s  ^%-5.2f %s (%s)" % (tmax, slope, family, lib))


main()
