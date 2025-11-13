#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import shared

parser = argparse.ArgumentParser(description='OpenModelica model testing report generation tool')
parser.add_argument('models', nargs='*')
parser.add_argument('--branch', default='')

args = parser.parse_args()

branch = args.branch.split("/")[-1]
models = args.models

dates = {}
dates_str = {}
fields = ["exectime", "frontend", "backend", "simcode", "templates", "compile", "simulate", "verify"]
entryhead = "<tr><th>Branch</th><th>Total</th><th>Frontend</th><th>Backend</th><th>SimCode</th><th>Templates</th><th>Compilation</th><th>Simulation</th><th>Verification</th>\n"

libs = {}

import sqlite3, datetime

conn = sqlite3.connect('sqlite3.db')
cursor = conn.cursor()

try:
  cursor.execute("SELECT name FROM [sqlite_master] WHERE type='table' AND name=?", (branch,))
  v = cursor.fetchone()[0]
except:
  raise Exception("No such table '%s'; specify it using --branch=XXX" % branch)

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
