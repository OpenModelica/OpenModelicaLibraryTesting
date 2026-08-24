#!/usr/bin/env python3

import argparse, sys
import resultsdb
from datetime import datetime

parser = argparse.ArgumentParser(description='OpenModelica library testing tool')
parser.add_argument('startDate')
parser.add_argument('stopDate')
resultsdb.addArgument(parser)

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

db = resultsdb.connect(args.db)
cursor = db.cursor()

tables = [tbl for tbl in db.tables() if tbl not in resultsdb.NON_RESULT_TABLES]
for tbl in tables:
  cursor.execute("DELETE FROM %s WHERE date<? AND date>?" % db.quote(tbl), (stopTime.timestamp(),startTime.timestamp()))
db.commit()
db.vacuum()
db.close()
