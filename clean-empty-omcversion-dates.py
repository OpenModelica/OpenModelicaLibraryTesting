#!/usr/bin/env python3

import argparse, sqlite3, sys
from datetime import datetime

parser = argparse.ArgumentParser(description='OpenModelica library testing tool')

args = parser.parse_args()

conn = sqlite3.connect('sqlite3.db')
cursor = conn.cursor()

entries = cursor.execute("SELECT date,branch FROM omcversion").fetchall()
dropped=0
for (date,branch) in entries:
  i=0
  (i,) = cursor.execute("SELECT COUNT(date) FROM [%s] WHERE date=?" % branch, (date,)).fetchone()
  if i==0:
    print("Dropping empty omcversion entry (%d,%s)" % (date,branch))
    cursor.execute("DELETE FROM [omcversion] WHERE date=? AND branch=?", (date,branch))
    dropped += 1

conn.commit()
if dropped>0:
  conn.execute("VACUUM")
conn.close()
