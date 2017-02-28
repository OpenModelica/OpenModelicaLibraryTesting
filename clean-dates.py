#!/usr/bin/env python3

import argparse, sqlite3, sys
from datetime import datetime

parser = argparse.ArgumentParser(description='OpenModelica library testing tool')
parser.add_argument('startDate')
parser.add_argument('stopDate')

args = parser.parse_args()

startTime = datetime.strptime(args.startDate, '%Y-%m-%d')
stopTime = datetime.strptime(args.stopDate, '%Y-%m-%d')

print("Cleanup entries between %s and %s" % (startTime, stopTime))
print("Cleanup entries between %d and %d" % (startTime.timestamp(), stopTime.timestamp()))
print("Continue? (y/n)")

# raw_input returns the empty string for "enter"
yes = set(['yes','y', 'ye'])
no = set(['no','n', ''])

choice = input().lower()
if choice in yes:
   pass
elif choice in no:
   sys.exit(1)
else:
   sys.stdout.write("Please respond with 'yes' or 'no'")
   sys.exit(1)

conn = sqlite3.connect('sqlite3.db')
cursor = conn.cursor()

tables = [tbl for (tbl,) in cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")]
for tbl in tables:
  cursor.execute("DELETE FROM [%s] WHERE date<? AND date>?" % tbl, (stopTime.timestamp(),startTime.timestamp()))
conn.commit()
conn.execute("VACUUM")
conn.close()
