#!/usr/bin/env python3

import argparse, sys
import resultsdb
from datetime import datetime

parser = argparse.ArgumentParser(description='OpenModelica library testing tool')
resultsdb.addArgument(parser)

args = parser.parse_args()

db = resultsdb.connect(args.db)
cursor = db.cursor()

entries = cursor.execute("SELECT date,branch FROM omcversion").fetchall()
dropped=0
branches=set()
branchDates = {}
for (date,branch) in entries:
  branches.add(branch)
  if branch not in branchDates:
    branchDates[branch] = set()
  branchDates[branch].add(date)
for branch in branches:
  # The shared database holds the branches of every machine, including ones
  # this one never created a result table for.
  if not db.tableExists(branch):
    continue
  data=cursor.execute("SELECT DISTINCT date FROM %s" % db.quote(branch)).fetchall()
  for (date,) in data:
    try:
      branchDates[branch].remove(date)
    except KeyError:
      pass
  for date in branchDates[branch]:
    print("Dropping empty omcversion entry (%d,%s)" % (date,branch))
    cursor.execute("DELETE FROM omcversion WHERE date=? AND branch=?", (date,branch))
    dropped += 1

db.commit()
if dropped>0:
  db.vacuum()
db.close()
