#!/usr/bin/env python3

import argparse, sys
import resultsdb

parser = argparse.ArgumentParser(description='OpenModelica library testing tool')
resultsdb.addArgument(parser)

args = parser.parse_args()

db = resultsdb.connect(args.db)
cursor = db.cursor()

branches = [b for (b,) in cursor.execute("SELECT DISTINCT branch FROM omcversion").fetchall()]
dropped=0
for branch in branches:
  # The shared database holds the branches of every machine, including ones
  # this one never created a result table for.
  if not db.tableExists(branch):
    continue
  empty = cursor.execute("""SELECT date FROM omcversion o WHERE branch=?
      AND NOT EXISTS (SELECT 1 FROM %s r WHERE r.date=o.date)""" % db.quote(branch), (branch,)).fetchall()
  for (date,) in empty:
    print("Dropping empty omcversion entry (%d,%s)" % (date,branch))
    cursor.execute("DELETE FROM omcversion WHERE date=? AND branch=?", (date,branch))
    dropped += 1

db.commit()
if dropped>0:
  db.vacuum()
db.close()
