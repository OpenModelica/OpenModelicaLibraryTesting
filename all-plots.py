#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys, argparse, subprocess, os
import simplejson as json
import shared
import re, time, math
from omcommon import friendlyStr

import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.cbook as cbook
from matplotlib.ticker import MaxNLocator
from matplotlib.font_manager import FontProperties

parser = argparse.ArgumentParser(description='OpenModelica model testing report generation tool')
parser.add_argument('branches', nargs='*')
parser.add_argument('--historypath', default="/var/www/branches/history")
args = parser.parse_args()

branches = [branch.split("/")[-1] for branch in args.branches]
fnameprefix = args.historypath

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
  return '<a href="%s/%s/%s/%s.html">%s</a>' % (baseurl,branch,libname,libname,libname)

def plotLibrary(libname, xs, total, frontend,backend,simcode,template,compile,simulate,verify):
  f, ax = plt.subplots(1)
  lw = 0.5
  plt.plot(xs, total, label='total (%d)' % total[-1], linewidth=lw)
  plt.plot(xs, frontend, label='frontend (%d)' % frontend[-1], linewidth=lw)
  plt.plot(xs, backend, label='backend (%d)' % backend[-1], linewidth=lw)
  plt.plot(xs, simcode, label='simcode (%d)' % simcode[-1], linewidth=lw)
  plt.plot(xs, template, label='templates (%d)' % template[-1], linewidth=lw)
  plt.plot(xs, compile, label='compile (%d)' % compile[-1], linewidth=lw)
  plt.plot(xs, simulate, label='simulate (%d)' % simulate[-1], linewidth=lw)
  if not (min(verify)==0 and max(verify)==0):
    plt.plot(xs, verify, label='verify (%d)' % verify[-1], linewidth=lw)
  if False:
    ticksize = 5
    if len(total)<=10:
      ticksize = 1
    if len(total)>=200:
      ticksize = 25
    elif len(total)>=100:
      ticksize = 10
    #yint = range(0, ticksize, math.ceil(max(total))+10-(math.ceil(max(total))%10))
    #plt.yticks(yint)

  ax.set_ylim(ymin=0)
  ax.set_xlim(xmin=xs[0], xmax=xs[-1])

  plt.gcf().autofmt_xdate()

  plt.title(libname)

  # Shrink current axis by 20%
  box = ax.get_position()
  ax.set_position([box.x0, box.y0, box.width * 0.75, box.height])

  # Put a legend to the right of the current axis
  ax.legend(loc='center left', bbox_to_anchor=(1, 0.5))

  try:
    os.makedirs("%s/%s" % (fnameprefix,libname))
  except FileExistsError:
    pass

  plt.savefig("%s/%s/%s.svg" % (fnameprefix,libname,libname), format="svg")

  if len(xs)>=7:
    plt.title(libname + " (last 7 runs)")
    ax.set_ylim(ymin=None)
    ax.set_xlim(xmin=xs[-7], xmax=xs[-1])
    plt.savefig("%s/%s/%s-recent.svg" % (fnameprefix,libname,libname), format="svg")

  plt.close()

for branch in branches:
  try:
    cursor.execute("SELECT name FROM [sqlite_master] WHERE type='table' AND name=?", (branch,))
    v = cursor.fetchone()[0]
  except:
    raise Exception("No such table '%s'; specify it using --branch=XXX" % branch)

for branch in branches:
  cursor.execute('''CREATE INDEX IF NOT EXISTS idx_%s_date ON %s(date)''' % (branch,branch))
  libs = {}
  for (date,libname,total,frontend,backend,simcode,template,compile,simulate,verify) in cursor.execute("""SELECT date,libname,COUNT(finalphase),COUNT(finalphase>=1 or null),COUNT(finalphase>=2 or null),COUNT(finalphase>=3 or null),COUNT(finalphase>=4 or null),COUNT(finalphase>=5 or null),COUNT(finalphase>=6 or null),COUNT(finalphase>=7 or null)
    FROM [%s]
    GROUP BY date,libname
    ORDER BY libname,date ASC
""" % (branch)):
    if libname not in libs:
      libs[libname] = ([],[],[],[],[],[],[],[],[])
    libs[libname][0].append(datetime.datetime.fromtimestamp(date))
    libs[libname][1].append(total)
    libs[libname][2].append(frontend)
    libs[libname][3].append(backend)
    libs[libname][4].append(simcode)
    libs[libname][5].append(template)
    libs[libname][6].append(compile)
    libs[libname][7].append(simulate)
    libs[libname][8].append(verify)
  for libname in libs.keys():
    plotLibrary(libname, libs[libname][0], libs[libname][1], libs[libname][2], libs[libname][3], libs[libname][4], libs[libname][5], libs[libname][6], libs[libname][7], libs[libname][8])

"""
for branch in branches:
  cursor.execute('''CREATE TABLE if not exists [datelookup_%s]
             (date integer NOT NULL, runDate integer NOT NULL, libname text NOT NULL, branch text NOT NULL)''' % branch)

  cursor.execute('''CREATE INDEX IF NOT EXISTS idx_%s_date ON %s(date)''' % (branch,branch))
  cursor.execute('''CREATE INDEX IF NOT EXISTS idx_omcversion_date ON omcversion(date)''')
  cursor.execute('''CREATE INDEX IF NOT EXISTS idx_libversion_date ON libversion(date)''')

  cursor.execute('''SELECT DISTINCT V.date as date,L.libname as libname
    FROM [omcversion] as V
    CROSS JOIN (SELECT DISTINCT libname FROM [%s]) AS L
    LEFT JOIN [datelookup_%s] as D ON D.date=V.date AND D.branch=? AND D.libname=L.libname
    WHERE D.runDate IS NULL
    ORDER BY V.date ASC
''' % (branch,branch), (branch,))
  entries = cursor.fetchall()
  print(len(entries))
  progress = 0
  start = time.time()
  cursor.execute('''DROP INDEX IF EXISTS idx_datelookup_%s_date''' % branch)
  for (date,libname) in entries:
    cursor.execute("SELECT date FROM [%s] WHERE libname=? AND date <= ? ORDER BY date DESC LIMIT 1" % branch, (libname,date))
    (runDate,) = cursor.fetchone() or (0,)
    cursor.execute("INSERT INTO [datelookup_%s] VALUES (?,?,?,?)" % branch, (date,runDate,libname,branch))
    progress += 1
    if progress % 100 == 0:
      end = time.time()
      print("%d total insertions, %0.2g" % (progress,end-start))
      start = end
  cursor.execute('''CREATE INDEX IF NOT EXISTS idx_datelookup_%s_date ON datelookup_%s(date)''' % (branch,branch))
  conn.commit()
conn.commit()
"""
