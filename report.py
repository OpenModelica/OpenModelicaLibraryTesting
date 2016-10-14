#!/usr/bin/env python3
# -*- coding: utf-8 -*-

branches = ["v1.9","v1.10","master"]
dates = {}
dates_str = {}
fields = ["exectime", "frontend", "backend", "simcode", "templates", "compile", "simulate", "verify"]
entryhead = "<tr><th>Branch</th><th>Total</th><th>Frontend</th><th>Backend</th><th>SimCode</th><th>Templates</th><th>Compilation</th><th>Simulation</th><th>Verification</th>\n"

libs = {}

import cgi, sqlite3, time, datetime
from omcommon import friendlyStr, multiple_replace

conn = sqlite3.connect('sqlite3.db')
cursor = conn.cursor()

for branch in branches:

  cursor.execute("SELECT date FROM [%s] ORDER BY date DESC LIMIT 1" % branch)
  v = cursor.fetchone()[0]
  dates[branch] = v
  dates_str[branch] = str(datetime.datetime.fromtimestamp(v).strftime('%Y-%m-%d %H:%M:%S'))

  for v in cursor.execute("SELECT libname,model FROM [%s] WHERE date=?" % branch, (v,)):
    if v[0] not in libs:
      libs[v[0]] = set()
    libs[v[0]].add(v[1])

entries = ""

for lib in sorted(libs.keys()):
  models = libs[lib]
  entries += "<h3>%s</h3>\n" % lib
  entries += "<table>\n"
  entries += entryhead
  for branch in branches:
    vs = [cursor.execute("SELECT COUNT(*) FROM [%s] WHERE date=? AND finalphase>=? AND libname=?" % (branch), (dates[branch],i,lib)).fetchone()[0] for i in range(0,8)]
    entries += ("<tr><td>%s</td><td>%d</td><td>%d</td><td>%d</td><td>%d</td><td>%d</td><td>%d</td><td>%d</td><td>%d</td></tr>\n" % (branch,vs[0],vs[1],vs[2],vs[3],vs[4],vs[5],vs[6],vs[7]))
  entries += "</table>\n"
  entries += "<table>\n"
  entries += entryhead
  for branch in branches:
    vs = [cursor.execute("SELECT COUNT(*) FROM [%s] WHERE date=? AND finalphase>=? AND libname=?" % (branch), (dates[branch],i,lib)).fetchone()[0] for i in range(0,8)]
    sums = [cursor.execute("SELECT SUM(%s) FROM [%s] WHERE date=? AND libname=?" % (fields[i],branch), (dates[branch],lib)).fetchone()[0] or 0 for i in range(0,8)]
    entries += ("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>\n" % (branch,friendlyStr(sums[0]),friendlyStr(sums[1]),friendlyStr(sums[2]),friendlyStr(sums[3]),friendlyStr(sums[4]),friendlyStr(sums[5]),friendlyStr(sums[6]),friendlyStr(sums[7])))
  entries += "</table>\n"
  # print(sorted(list(libs[lib])))

nummodels = sum(len(l) for l in libs.values())
branches_lines = [("<tr><td>%s</td><td>%s</td><td>%s</td><td%s>%d</td></tr>\n" % (cgi.escape(branch), cgi.escape(dates_str[branch]), friendlyStr(
  cursor.execute("SELECT SUM(exectime) FROM [%s] WHERE date=?" % branch, (dates[branch],)).fetchone()[0]
),
  " class=\"warning\"" if nummodels!=cursor.execute("SELECT COUNT(*) FROM [%s] WHERE date=?" % branch, (dates[branch],)).fetchone()[0] else "",
  cursor.execute("SELECT COUNT(*) FROM [%s] WHERE date=?" % branch, (dates[branch],)).fetchone()[0]
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
