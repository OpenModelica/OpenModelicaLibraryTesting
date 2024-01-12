#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys, argparse
import simplejson as json
import shared

parser = argparse.ArgumentParser(description='OpenModelica library testing report generation tool')
parser.add_argument('configs', nargs='*')
parser.add_argument('--branches', default='master')
args = parser.parse_args()
configs = args.configs

if configs == []:
  raise Exception("Error: Expected at least one configuration file to start the library test")

branches = [br.split("/")[-1] for br in args.branches.split(" ")]

dates = {}
dates_str = {}
fields = ["exectime", "parsing", "frontend", "backend", "simcode", "templates", "compile", "simulate", "verify"]
entryhead = "<tr><th>Branch</th><th>Total</th><th>Parsing</th><th>Frontend</th><th>Backend</th><th>SimCode</th><th>Templates</th><th>Compilation</th><th>Simulation</th><th>Verification</th></tr>\n"

libs = {}

import html, sqlite3, time, datetime
from omcommon import friendlyStr, multiple_replace

configs_lst = [shared.readConfig(c) for c in configs]
configs = []
for c in configs_lst:
  configs = configs + c
libnames = set(shared.libname(library,conf) for (library,conf) in configs)

conn = sqlite3.connect('sqlite3.db')
cursor = conn.cursor()

nmodels = {}
nsimulate = {}
exectime = {}

for branch in branches:
  cursor.execute("SELECT date FROM [%s] ORDER BY date DESC LIMIT 1" % branch)
  v = cursor.fetchone()[0]
  dates_str[branch] = str(datetime.datetime.fromtimestamp(v).strftime('%Y-%m-%d %H:%M:%S'))
  cursor.execute('''CREATE INDEX IF NOT EXISTS [idx_%s_date] ON [%s](date)''' % (branch,branch))

  dates[branch] = {}
  branch_nmodels = 0
  for libname in libnames:
    cursor.execute("SELECT date FROM [%s] WHERE libname=? ORDER BY date DESC LIMIT 1" % branch, (libname,))
    v = cursor.fetchone()
    if v is None:
      dates[branch][libname] = 0
      continue
    dates[branch][libname] = v[0]
    for x in cursor.execute("SELECT model FROM [%s] WHERE libname=? AND date=?" % branch, (libname,v[0])):
      if libname not in libs:
        libs[libname] = set()
      libs[libname].add(x[0])
      branch_nmodels += 1
  nmodels[branch] = branch_nmodels
  nsimulate[branch] = 0
  exectime[branch] = 0.0

entries = ""

def checkEqual(iterator):
   return len(set(iterator)) <= 1

for lib in sorted(libs.keys()):
  models = libs[lib]
  entries += "<hr><h3>%s</h3>\n" % lib
  branches_versions = [(cursor.execute("SELECT libversion FROM [libversion] WHERE libname=? AND branch=? ORDER BY date DESC LIMIT 1", (lib,branch)).fetchone() or ["unknown"])[0] for branch in branches]
  all_equal = checkEqual(branches_versions)
  if not all_equal:
    entries += "<table>\n"
    entries += "<tr><th>&nbsp;</th>%s</tr>\n" % "".join(["<th>%s</th>" % branch for branch in branches])
    entries += "<tr><td>Version</td>"
    for ver in branches_versions:
      entries += "<td%s>%s</td>" % (' class="warning"', ver)
    entries += "</tr>\n"
    entries += "</table>\n"
  else:
    entries += "<p><strong>Library version:</strong> %s</p>" % branches_versions[0]
  entries += "<table>\n"
  entries += entryhead
  old_vs = None
  models = {}
  for branch in branches:
    master_models = []
    for i in range(0,8):
      i_models = set()
      for v in cursor.execute("SELECT model FROM [%s] WHERE date=? AND finalphase>=? AND libname=?" % (branch), (dates[branch][lib],i,lib)):
        i_models.add(v[0])
      master_models.append(i_models)
    models[branch] = master_models
  for branch in branches:
    vs = [cursor.execute("SELECT COUNT(*) FROM [%s] WHERE date=? AND finalphase>=? AND libname=?" % (branch), (dates[branch][lib],i,lib)).fetchone()[0] for i in range(0,8)]
    warnings = []
    entries += '<tr><td><a href="%s/%s/%s.html">%s</a></td>' % (branch,lib,lib,branch)
    for i in [0]+list(range(0,len(vs))):
      diff1 = models[branch][i] - models[branches[-1]][i]
      diff2 = models[branches[-1]][i] - models[branch][i]
      diff_text = ""
      if len(diff2)>0:
        diff_text += "<p>Now working in %s, failed in %s:<br>\n" % (branches[-1],branch) + "<br>\n".join(sorted(diff2)) + "</p>"
      if len(diff1)>0:
        diff_text += "<p>Now failing in %s, worked in %s:<br>\n" % (branches[-1],branch) + "<br>\n".join(sorted(diff1)) + "</p>"
      if False and diff_text:
        diff_text += "<p>Debug:<br>\n" + "<br>\n".join(models[branch][i]) + "</p>"
      entries += '<td%s><a%s>%s%s</a></td>' % (' class="warning"' if old_vs and old_vs[i]>vs[i] else (' class="better"' if old_vs and old_vs[i]<vs[i] else ""),' class="dot"' if diff_text else "",vs[i],('<span class="tooltip">%s</span>' % diff_text) if diff_text else "")
    entries += "</tr>"
    nsimulate[branch] += vs[6]
    if old_vs:
      old_vs = [max(vs[i], old_vs[i]) for i in range(0, len(vs))]
    else:
      old_vs = vs
  entries += "</table>\n"
  entries += "<table>\n"
  entries += entryhead
  for branch in branches:
    vs = [cursor.execute("SELECT COUNT(*) FROM [%s] WHERE date=? AND finalphase>=? AND libname=?" % (branch), (dates[branch][lib],i,lib)).fetchone()[0] for i in range(0,8)]
    sums = [cursor.execute("SELECT SUM(%s) FROM [%s] WHERE date=? AND libname=?" % (fields[i],branch), (dates[branch][lib],lib)).fetchone()[0] or 0 for i in range(0,9)]
    entries += '<tr><td><a href="%s/%s/%s.html">%s</a></td>' % (branch,lib,lib,branch)
    entries += ("<td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>\n" % (friendlyStr(sums[0]),friendlyStr(sums[1]),friendlyStr(sums[2]),friendlyStr(sums[3]),friendlyStr(sums[4]),friendlyStr(sums[5]),friendlyStr(sums[6]),friendlyStr(sums[7]),friendlyStr(sums[8])))
    exectime[branch] += sums[0]
  entries += "</table>\n"
  # print(sorted(list(libs[lib])))

nummodels = sum(len(l) for l in libs.values())
branches_lines = [("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td%s>%d</td><td>%d</td></tr>\n" % (html.escape(branch), html.escape(
  (cursor.execute("SELECT omcversion FROM [omcversion] WHERE date=? AND branch=?", (max(dates[branch][lib] for lib in libnames),branch)).fetchone() or ["unknown"])[0]
  ), html.escape(dates_str[branch]), friendlyStr(exectime[branch]),
  " class=\"warning\"" if nummodels!=nmodels[branch] else "",
  nsimulate[branch],
  nmodels[branch]
)) for branch in branches]
template = open("overview.html.tpl").read()
replacements = (
  (u"#title#", "OpenModelica Library Testing Overview"),
  (u"#branches#", "\n".join(branches_lines)),
  (u"#numlibs#", str(len(libs))),
  (u"#nummodels#", str(nummodels)),
  (u"#entries#", entries)
)
open("overview.html", "w").write(multiple_replace(template, *replacements))
