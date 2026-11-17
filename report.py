#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys, argparse
import simplejson as json
import shared, resultsdb

parser = argparse.ArgumentParser(description='OpenModelica library testing report generation tool')
parser.add_argument('configs', nargs='*')
parser.add_argument('--branches', default='master')
parser.add_argument('--invalid-branch', default='master',
                    help="The branch whose newest run of each library says which models are invalid: "
                         "omc translated them only because --warnNonStandardModelica turned the errors of "
                         "non-standard Modelica into warnings. They are left out of the counts, whatever "
                         "the other branches say about them.")
resultsdb.addArgument(parser)
args = parser.parse_args()
configs = args.configs

if configs == []:
  raise Exception("Error: Expected at least one configuration file to start the library test")

branches = [shared.resultTable(br) for br in args.branches.split(" ")]
invalidBranch = shared.resultTable(args.invalid_branch)

dates = {}
dates_str = {}
fields = ["exectime", "parsing", "frontend", "backend", "simcode", "templates", "compile", "simulate", "verify"]

libs = {}

import html, time, datetime
from omcommon import friendlyStr, multiple_replace

configs_lst = [shared.readConfig(c) for c in configs]
configs = []
for c in configs_lst:
  configs = configs + c
libnames = set(shared.libname(library,conf) for (library,conf) in configs)
# What a data reconciliation run simulates is the model the reconciliation
# extracted, not the library's model.
simulationLabel = "Simulation (DR model)" if configs and all(conf.get("dataReconciliation") for (library,conf) in configs) else "Simulation"
entryhead = "<tr><th>Branch</th><th>Total</th><th>Parsing</th><th>Frontend</th><th>Backend</th><th>SimCode</th><th>Templates</th><th>Compilation</th><th>%s</th><th>Verification</th></tr>\n" % simulationLabel

db = resultsdb.connect(args.db)
cursor = db.cursor()

# (view, label): which models a library's tables count.
VIEWS = [("valid", "Exclude invalid"), ("all", "Include invalid"), ("invalid", "Only invalid")]

def inView(view, model, invalid):
  return view == "all" or (model in invalid) == (view == "invalid")

invalidModels = {}
if db.tableExists(invalidBranch) and "invalid" in db.columns(invalidBranch):
  for libname in libnames:
    v = cursor.execute("SELECT MAX(date) FROM %s WHERE libname=?" % db.quote(invalidBranch), (libname,)).fetchone()
    if v and v[0]:
      invalidModels[libname] = set(m for (m,) in cursor.execute(
        "SELECT model FROM %s WHERE libname=? AND date=? AND finalphase>=0 AND invalid=1" % db.quote(invalidBranch),
        (libname, v[0])))

rows = {}
missing_branches = []
for branch in branches:
  one = None
  if db.tableExists(branch):
    cursor.execute("SELECT date FROM %s ORDER BY date DESC LIMIT 1" % db.quote(branch))
    one = cursor.fetchone()
  if one is None:
    print("No such table '%s'; specify it using --branch=XXX when running test.py" % branch)
    missing_branches.append(branch)
    continue
  v = one[0]

  dates_str[branch] = str(datetime.datetime.fromtimestamp(v).strftime('%Y-%m-%d %H:%M:%S'))
  db.createDateIndex(branch)

  dates[branch] = {}
  rows[branch] = {}
  for libname in libnames:
    cursor.execute("SELECT date FROM %s WHERE libname=? ORDER BY date DESC LIMIT 1" % db.quote(branch), (libname,))
    v = cursor.fetchone()
    if v is None:
      dates[branch][libname] = 0
      continue
    dates[branch][libname] = v[0]
    rows[branch][libname] = cursor.execute("SELECT model,finalphase,%s FROM %s WHERE libname=? AND date=? AND finalphase>=0"
                                           % (",".join(fields), db.quote(branch)), (libname,v[0])).fetchall()
    for r in rows[branch][libname]:
      libs.setdefault(libname, set()).add(r[0])

# removing missing branches
for branch in missing_branches:
  branches.remove(branch)

def counts(branch, lib, view):
  """The number of models reaching each phase, and the time spent in each."""
  invalid = invalidModels.get(lib, set())
  selected = [r for r in rows[branch].get(lib, []) if inView(view, r[0], invalid)]
  vs = [sum(1 for r in selected if r[1] >= i) for i in range(0,8)]
  sums = [sum(r[2+i] or 0 for r in selected) for i in range(0,len(fields))]
  return (vs, sums)

totals = {}
for (view, _) in VIEWS:
  totals[view] = {}
  for branch in branches:
    t = {"simulate": 0, "verify": 0, "total": 0, "exectime": 0.0, "simtime": 0.0}
    for lib in libs:
      (vs, sums) = counts(branch, lib, view)
      t["simulate"] += vs[6]
      t["verify"] += vs[7]
      t["total"] += vs[0]
      t["exectime"] += sums[0]
      t["simtime"] += sums[7]
    totals[view][branch] = t

def countsTable(caption, rows):
  return '<table class="counts"><caption>%s</caption>\n%s%s</table>\n' % (caption, entryhead, "".join(rows))

def libraryTables(lib, view):
  phases = []
  times = []
  old_vs = None
  for branch in branches:
    (vs, sums) = counts(branch, lib, view)
    link = '<td><a href="%s/%s/%s.html">%s</a></td>' % (branch,lib,lib,branch)
    phases.append("<tr>%s%s</tr>\n" % (link, "".join('<td%s>%s</td>' % (' class="warning"' if old_vs and old_vs[i]>vs[i] else (' class="better"' if old_vs and old_vs[i]<vs[i] else ""), vs[i])
                                                    for i in [0]+list(range(0,len(vs))))))
    times.append("<tr>%s%s</tr>\n" % (link, "".join("<td>%s</td>" % friendlyStr(s) for s in sums)))
    if old_vs:
      old_vs = [max(vs[i], old_vs[i]) for i in range(0, len(vs))]
    else:
      old_vs = vs
  return countsTable("Models that completed each phase", phases) + countsTable("Time spent in each phase", times)

def viewSwitch():
  return '<div class="switch" role="group" aria-label="Invalid models">%s</div>' % "".join(
    '<button type="button" data-show="%s" aria-pressed="%s">%s</button>' % (view, "true" if view == "valid" else "false", label)
    for (view, label) in VIEWS)

def checkEqual(iterator):
   return len(set(iterator)) <= 1

entries = ""
for lib in sorted(libs.keys()):
  invalid = invalidModels.get(lib, set()) & libs[lib]
  entries += '<section class="library" data-view="valid">\n' if invalid else '<section class="library">\n'
  entries += "<h3>%s</h3>\n" % lib
  branches_versions = [(cursor.execute("SELECT libversion FROM libversion WHERE libname=? AND branch=? ORDER BY date DESC LIMIT 1", (lib,branch)).fetchone() or ["unknown"])[0] for branch in branches]
  all_equal = checkEqual(branches_versions)
  if not all_equal:
    entries += '<table class="versions">\n'
    entries += "<tr><th>&nbsp;</th>%s</tr>\n" % "".join(["<th>%s</th>" % branch for branch in branches])
    entries += "<tr><td>Version</td>"
    for ver in branches_versions:
      entries += "<td%s>%s</td>" % (' class="warning"', ver)
    entries += "</tr>\n"
    entries += "</table>\n"
  else:
    entries += '<p class="version">Library version: %s</p>\n' % branches_versions[0]
  if invalid:
    entries += '<p class="badge"><span class="cross">&#x2718;</span> %d invalid model%s</p>\n' % (len(invalid), "" if len(invalid) == 1 else "s")
    entries += "<details><summary>Invalid models</summary><p>%s</p></details>\n" % "<br>\n".join(html.escape(m) for m in sorted(invalid))
    for (view, _) in VIEWS:
      entries += '<div class="view view-%s">\n%s</div>\n' % (view, libraryTables(lib, view))
  else:
    entries += libraryTables(lib, "all")
  entries += "</section>\n"

nummodels = sum(len(models - invalidModels.get(lib, set())) for (lib, models) in libs.items())
numinvalid = sum(len(models & invalidModels.get(lib, set())) for (lib, models) in libs.items())
expected = {"valid": nummodels, "all": nummodels + numinvalid, "invalid": numinvalid}
omcversions = dict((branch, (cursor.execute("SELECT omcversion FROM omcversion WHERE date=? AND branch=?", (max(dates[branch][lib] for lib in libnames),branch)).fetchone() or ["unknown"])[0])
                   for branch in branches)
simulateLabel = "# " + simulationLabel if simulationLabel != "Simulation" else "# Simulate"

BRANCH_CAPTIONS = {"valid": "Invalid models left out", "all": "Invalid models included", "invalid": "Only the invalid models"}

def branchesTable(view):
  t = totals[view]
  lines = ["<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%d</td><td>%d</td><td%s>%d</td></tr>\n" % (
    html.escape(branch), html.escape(omcversions[branch]), html.escape(dates_str[branch]),
    friendlyStr(t[branch]["exectime"]), friendlyStr(t[branch]["simtime"]),
    t[branch]["simulate"], t[branch]["verify"],
    ' class="warning"' if expected[view] != t[branch]["total"] else "", t[branch]["total"]) for branch in branches]
  return ('<div class="view view-%s"><table class="branches"><caption>%s</caption>\n<tr><th>Branch</th><th>Version</th><th>Build time</th>'
          '<th>Execution time</th><th>Simulation time</th><th>%s</th><th># Verify</th><th># Total</th></tr>\n%s</table></div>\n'
          % (view, BRANCH_CAPTIONS[view], simulateLabel, "".join(lines)))

template = open("overview.html.tpl").read()
replacements = (
  (u"#title#", "OpenModelica Library Testing Overview"),
  (u"#branches#", "".join(branchesTable(view) for (view, _) in VIEWS)),
  (u"#viewSwitch#", viewSwitch()),
  (u"#numlibs#", str(len(libs))),
  (u"#nummodels#", str(nummodels)),
  (u"#numinvalid#", str(numinvalid)),
  (u"#invalidBranch#", html.escape(invalidBranch)),
  (u"#entries#", entries)
)
open("overview.html", "w").write(multiple_replace(template, *replacements))
