#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys, argparse
import simplejson as json
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

import cgi, sqlite3, time, datetime
from omcommon import friendlyStr, multiple_replace

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
  for (dint,libname) in cursor.execute("SELECT date,libname FROM [%s] WHERE model=? ORDER BY date ASC" % (branch), (model,)):
    c+=1
    dstr = str(datetime.datetime.fromtimestamp(dint).strftime('%Y-%m-%d %H:%M:%S'))
    cursor2 = conn.cursor()
    omcversion = cursor2.execute("SELECT omcversion FROM [omcversion] WHERE date=? AND branch=?", (dint,branch)).fetchone()[0]
    lines.insert(0, "%s %s" % (dstr,omcversion))
  if c==0:
    raise Exception("No such model: %s" % model)
  print(libname)
  print("\n".join(lines))
