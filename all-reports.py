#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys, argparse, subprocess
import simplejson as json
import shared
import re

parser = argparse.ArgumentParser(description='OpenModelica model testing report generation tool')
parser.add_argument('branches', nargs='*')

args = parser.parse_args()

branches = [branch.split("/")[-1] for branch in args.branches]

dates = {}
dates_str = {}
fields = ["exectime", "frontend", "backend", "simcode", "templates", "compile", "simulate", "verify"]
entryhead = "<tr><th>Branch</th><th>Total</th><th>Frontend</th><th>Backend</th><th>SimCode</th><th>Templates</th><th>Compilation</th><th>Simulation</th><th>Verification</th>\n"

libs = {}

import cgi, sqlite3, time, datetime
from omcommon import friendlyStr, multiple_replace

conn = sqlite3.connect('sqlite3.db')
cursor = conn.cursor()

def dateStr(dint):
  return str(datetime.datetime.fromtimestamp(dint).strftime('%Y-%m-%d %H:%M:%S'))

def getTagOrVersion(v):
  v = v.replace("OpenModelica ","").replace("OMCompiler ","")
  m = re.search("[+]g([0-9a-f]{7})$", v)
  if m:
    return m.group(1)
  return v

def libraryLink(branch, libname):
  return '<a href="http://libraries.openmodelica.org/branches/%s/%s/%s.html">%s</a>' % (branch,libname,libname,libname)
for branch in branches:
  try:
    cursor.execute("SELECT name FROM [sqlite_master] WHERE type='table' AND name=?", (branch,))
    v = cursor.fetchone()[0]
  except:
    raise Exception("No such table '%s'; specify it using --branch=XXX" % branch)
  cursor.execute("SELECT date,omcversion FROM [omcversion] WHERE branch=? ORDER BY date ASC", (branch,))
  entries = cursor.fetchall()
  n = len(entries)
  for i in range(n-1,0,-1):
    d1 = entries[i-1][0]
    d2 = entries[i][0]
    v1 = getTagOrVersion(entries[i-1][1])
    v2 = getTagOrVersion(entries[i][1])
    fname = "%s/%s..%s.html" % (branch,dateStr(d1),dateStr(d2))
    print(fname)
    with open("history.html.tpl") as fin:
      tpl = fin.read()
    gitlog = subprocess.check_output(["git", "log", '--pretty=<tr><td><a href="https://github.com/OpenModelica/OMCompiler/commit/%h">%h</a></td><td>%an</td><td>%s</td></tr>', "%s..%s" % (v1,v2)], cwd="/home/martin/OpenModelica/OMCompiler").decode("utf-8")
    tpl = tpl.replace("#OMCGITLOG#",gitlog).replace("#NUMCOMMITS#",str(gitlog.count("<tr>")))
    cursor.execute("SELECT model,libname,GROUP_CONCAT(finalphase) FROM (SELECT model,libname,finalphase FROM [%s] WHERE date IN (?,?) ORDER BY date) GROUP BY model,libname HAVING MIN(finalphase) <> MAX(finalphase) ORDER BY libname,model" % branch, (d1,d2))
    regressions = cursor.fetchall()
    if len(regressions)==0:
      continue
    libs = set()
    for (model,libname,group) in regressions:
      libs.add(libname)
    libstrs = []
    for libname in sorted(list(libs)):
      cursor.execute("SELECT libversion,confighash FROM [libversion] WHERE branch=? AND date=? AND libname=?", (branch,d1,libname))
      (lv1,lh1) = cursor.fetchone()
      lv1 = lv1.strip()
      cursor.execute("SELECT libversion,confighash FROM [libversion] WHERE branch=? AND date=? AND libname=?", (branch,d2,libname))
      (lv2,lh2) = cursor.fetchone()
      lv2 = lv2.strip()
      if lv1 != lv2:
        libstrs.append("<tr><td>%s</td><td>From version %s to %s</td></tr>" % (libraryLink(branch, libname),lv1,lv2))
      elif lh1 != lh2:
        libstrs.add("<tr><td>%s</td><td>Configuration hash (OMC settings or the testing script changed)</td></tr>" % libraryLink(branch, libname))
    tpl = tpl.replace("#LIBCHANGES#","\n".join(libstrs)).replace("#NUMLIBS#",str(len(libstrs)))

    numImproved = 0
    numRegression = 0
    regstrs = []
    for (model,libname,group) in regressions:
      (phase1,phase2) = [int(i) for i in group.split(",")]
      if phase2 > phase1:
        color = "better"
        numImproved += 1
      elif phase2 < phase1:
        color = "warning"
        numRegression += 1
      else:
        raise Exception("Unknown regression/improvement...")
      regstrs.append('<tr><td><a href="http://libraries.openmodelica/branches/%s/%s/%s.html">%s</a></td><td>%s</td><td class="%s">%s &rarr; %s</td></tr>' % (branch,libname,libname,libname,model,color,shared.finalphaseName(phase1),shared.finalphaseName(phase2)))
    tpl = tpl.replace("#NUMIMPROVE#",str(numImproved)).replace("#NUMREGRESSION#",str(numRegression)).replace("#MODELCHANGES#", "\n".join(regstrs))
    tpl = tpl.replace("#BRANCH#",branch).replace("#DATE1#",dateStr(d1)).replace("#DATE2#",dateStr(d2))
    with open(fname, "w") as fout:
      fout.write(tpl)
    sys.exit(1)

sys.exit(1)
for model in models:
  lines=[]
  c=0
  libnames = [libname for (libname,) in cursor.execute("SELECT DISTINCT libname FROM [%s] WHERE model=? ORDER BY libname ASC" % (branch), (model,))]
  for libname in libnames:
    for (finalphase,dint,libversion) in cursor.execute("SELECT finalphase,date,libversion FROM [%s] NATURAL JOIN [libversion] WHERE model=? AND libname=? ORDER BY date ASC" % (branch), (model,libname)):
      c+=1
      dstr = str(datetime.datetime.fromtimestamp(dint).strftime('%Y-%m-%d %H:%M:%S'))
      cursor2 = conn.cursor()
      omcversion = cursor2.execute("SELECT omcversion FROM [omcversion] WHERE date=? AND branch=?", (dint,branch)).fetchone()[0]
      omcversion = omcversion.replace("OpenModelica ","").replace("OMCompiler ","")
      lines.insert(0, "%s %s %s %s" % (dstr,shared.finalphaseName(finalphase),omcversion,libversion.strip()))
    if c==0:
      raise Exception("No such model: %s" % model)
    print("%s - %s" % (libname,model))
    print("\n".join(lines))
    print("")
