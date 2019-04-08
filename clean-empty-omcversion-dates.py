#!/usr/bin/env python3

import argparse, sqlite3, sys
from datetime import datetime

parser = argparse.ArgumentParser(description='OpenModelica library testing tool')

args = parser.parse_args()

conn = sqlite3.connect('sqlite3.db')
cursor = conn.cursor()

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
  data=cursor.execute("SELECT DISTINCT date FROM [%s]" % branch).fetchall()
  for (date,) in data:
    try:
      branchDates[branch].remove(date)
    except KeyError:
      pass
  for date in branchDates[branch]:
    print("Dropping empty omcversion entry (%d,%s)" % (date,branch))
    cursor.execute("DELETE FROM [omcversion] WHERE date=? AND branch=?", (date,branch))
    dropped += 1

conn.commit()
if dropped>0:
  conn.execute("VACUUM")
conn.close()
