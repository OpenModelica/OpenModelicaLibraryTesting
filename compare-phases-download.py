#!/usr/bin/env python3

import glob
import re
import humanfriendly
import collections

data = collections.OrderedDict()

for f in sorted(glob.glob("br/*/ScalableTestSuite/files/ScalableTestSuite_*.err")):
  m = re.match("br/([^/]*)/ScalableTestSuite/files/ScalableTestSuite_(.*)[.]err", f)
  br = m[1]
  if br[0] == "v":
    br = br[1:]
  if br not in data:
    data[br] = collections.OrderedDict()
  res = collections.OrderedDict()
  for l in open(f).readlines():
    line = re.match("Notification: Performance of ([^:]*):.*time ([0-9.eE-]*).*allocations: ([^/]*)", l.strip())
    if line:
      num_bytes = humanfriendly.parse_size(line[3].strip())
      entry = line[1]
      if "(n=" in entry:
        print(entry)
        entry = (entry[0:entry.find("(")].strip() + " " + entry[entry.find(")")+1:].strip()).strip()
        print(entry)
      res[entry] = {"time": float(line[2].strip()), "allocations": num_bytes}
  data[br][m[2]] = res

for model in data["master"]:
  for x in data["master"][model]:
    print(x,)
    for br in data:
      e = data[br][model]
      if x in e:
        print(br,e[x]["time"],)
      else:
        print(br,None,)

fout = open("matching.csv", "w")

fout.write("Model,")
for br in data:
  fout.write(br)
  fout.write(" (time),")
  fout.write(br)
  fout.write(" (allocations),")
fout.write("\n")
for x in ["matching and sorting"]:
  for model in data["master"]:
    fout.write(model)
    fout.write(",")
    for br in data:
      e = data[br][model]
      if x in e:
        fout.write(str(e[x]["time"]))
        fout.write(",")
        fout.write(str(e[x]["allocations"]))
        fout.write(",")
      else:
        fout.write("-,-,")
    fout.write("\n")
# print(data)
