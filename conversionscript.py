#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from OMPython import OMCSessionZMQ, pyparsing
import argparse
import glob
import json
import os
import psutil
import shutil
import subprocess
from multiprocessing import Pool
import time


parser = argparse.ArgumentParser(description='OpenModelica library testing tool')
parser.add_argument('libdir', nargs=1)
parser.add_argument('--diff', action="store_true")
parser.add_argument('--allowErrorsInDiff', action="store_true")
parser.add_argument('-n', type=int, default=psutil.cpu_count(logical=False))
args = parser.parse_args()
libdir = args.libdir[0]
numThreads = args.n
createDiff = args.diff
allowErrorsInDiff = args.allowErrorsInDiff

try:
  shutil.rmtree("converted-libraries")
except:
  pass
os.mkdir("converted-libraries")
os.mkdir("converted-libraries/.openmodelica")
os.mkdir("converted-libraries/.openmodelica/libraries")

def omcAssert(omc, cmd, extra=""):
  res = omc.sendExpression(cmd)
  if not res:
    raise Exception(cmd + "\n" + extra + "\n" + (omc.sendExpression("getErrorString()") or ""))

def omcSendExpression(omc, cmd, extra=""):
  try:
    return omc.sendExpression(cmd)
  except pyparsing.ParseException as e:
    raise Exception(str(e) + "\n" + cmd + "\n" + extra + "\n" + (omc.sendExpression("getErrorString()") or ""))

mslPath = "%s/Modelica 4.0.0+maint.om/" % libdir
with open("%s/openmodelica.metadata.json" % mslPath) as f:
  mslData = json.load(f)
  convertFromVersion = mslData['convertFromVersion']
conversionScript = "%s/Resources/Scripts/Conversion/ConvertModelica_from_3.2.3_to_4.0.0.mos" % mslPath

def convertPackage(p):
  errorsInDiff = []
  with open(p) as f:
    data = json.load(f)
  uses=data.get('uses',{})
  libnameOnFile = os.path.basename(os.path.dirname(p))
  libname = libnameOnFile.split(" ")[0]
  shutil.copytree(os.path.dirname(p), "converted-libraries/.openmodelica/libraries/%s" % libnameOnFile)
  for root, dir, files in os.walk("converted-libraries/.openmodelica/libraries/%s" % libnameOnFile):
    for file in files:
      if file.endswith(".mo"):
        try:
          with open(os.path.join(root, file)) as fin:
            fin.read()
        except UnicodeDecodeError:
          with open(os.path.join(root, file), encoding="ISO-8859-1") as fin:
            latin1Data = fin.read()
          with open(os.path.join(root, file), "w", encoding="UTF-8") as fout:
            fout.write(latin1Data)
  
  if libname in ["Modelica", "ModelicaServices", "Complex", "ModelicaTest", "ModelicaTestOverdetermined"]:
    ver = libnameOnFile.split(" ")[1]
    if ver.startswith("1.") or ver.startswith("3."):
      return None
  if not uses.get('Modelica','0.0.0') in convertFromVersion:
    return None
  if libname in ["Modelica", "ModelicaServices", "Complex", "ModelicaTest", "ModelicaTestOverdetermined"]:
    return None
  omc = OMCSessionZMQ()
  libnameOnFileFullPath = "converted-libraries/.openmodelica/libraries/%s/package.mo" % libnameOnFile
  omcAssert(omc, 'loadFile("%s", uses=false)' % libnameOnFileFullPath)
  errString = omc.sendExpression("getErrorString()")
  if errString:
    print(errString)
  loadedFilePath = omc.sendExpression("getSourceFile(%s)" % libname)
  if libnameOnFileFullPath not in loadedFilePath:
    raise Exception("Expected to have loaded %s but got %s" % (libnameOnFileFullPath, loadedFilePath))
  gcProfStatsBeforeConversion = omc.sendExpression("GC_get_prof_stats()")
  timeBeforeConvert = time.time()
  omcAssert(omc, 'convertPackage(%s, "%s")' % (libname, conversionScript))
  uses = data["uses"]
  for (n,v) in data["uses"].items():
    if n in ["Modelica", "ModelicaServices", "Complex"]:
      omcAssert(omc, 'addClassAnnotation(%s, annotate=$annotation(uses(%s(version="4.0.0"))))' % (libname, n))
      data["uses"][n] = "4.0.0"
  names = omc.sendExpression('getClassNames(%s, sort=true, recursive=true)' % libname)
  names = list(names)
  names.reverse()
  fileMapping = {}
  for n in names:
    f = omc.sendExpression('getSourceFile(%s)' % n)
    fileMapping[f] = n
  statsByFile = []
  nFail = 0
  nDiff = 0
  gcProfStatsBefore = omc.sendExpression("GC_get_prof_stats()")
  timeAfterConvert = time.time()
  timeForConversion = timeAfterConvert - timeBeforeConvert
  for (newFile, newClass) in fileMapping.items():
    oldFile = os.path.join(libdir, newFile.split("converted-libraries/.openmodelica/libraries/")[1])
    assert(newFile != oldFile)
    before = omc.sendExpression('before := readFile("%s")' % newFile)
    after = omc.sendExpression('after := listFile(%s)' % newClass)
    if (not before) or (not after):
      raise Exception("%s %s (%s). %s. before: %s after: %s" % (oldFile, newFile, newClass, omc.sendExpression('getErrorString()'), str(type(before)), str(type(after))))
    omc.sendExpression("getErrorString()")
    start = time.time()
    if libname in []: # If we have libraries where the diff algorithm fails in the future
      res = omc.sendExpression('res := after') # Skip the diff
    else:
      try:
        res = omc.sendExpression('res := diffModelicaFileListings(before, after, OpenModelica.Scripting.DiffFormat.plain, failOnSemanticsChange=true)')
      except pyparsing.ParseException as e:
        errStr = omc.sendExpression('diffModelicaFileListings(before, after, OpenModelica.Scripting.DiffFormat.plain, failOnSemanticsChange=true)', parsed=False)
        if errStr.strip():
          print(errStr)
        res = None
        omc.sendExpression(omc, 'res := ""')
    end = time.time()
    isFail = False
    if not res:
      omc.sendExpression('writeFile("%s", after)' % newFile)
      if allowErrorsInDiff:
        errorsInDiff += [newFile]
        res = after
        nFail += 1
        isFail = True
      else:
        errStr = omc.sendExpression("getErrorString()")
        if errStr:
          print(errStr)
        raise Exception('echo(false);before:=readFile("%s");\nafter:=readFile("%s");echo(true);\ndiffModelicaFileListings(before, after, OpenModelica.Scripting.DiffFormat.plain, failOnSemanticsChange=true);\ngetErrorString();' % (oldFile, newFile))
    else:
      omcAssert(omc, 'writeFile("%s", res)' % (newFile))
    isDiff = before != res
    if before != res:
      nDiff += 1
    statsByFile +=[{"time": end-start, "size": len(before), "isDiff": isDiff, "fail": isFail}]
  path = "converted-libraries/.openmodelica/libraries/%s/openmodelica.metadata.json" % libnameOnFile
  with open(path, "w") as f:
    gcProfStats = omc.sendExpression("GC_get_prof_stats()")
    data["uses"] = dict(uses)
    data["extraInfo"] = "Conversion script %s was applied" % conversionScript
    json.dump(data, f)
  if createDiff:
    diffOutputFile = "converted-libraries/.openmodelica/libraries/%s.diff" % libnameOnFile
    print("Creating %s" % diffOutputFile)
    with open(diffOutputFile, "wb") as diffOut:
      diffOutput = subprocess.call(["diff", "-ur", os.path.dirname(p), "converted-libraries/.openmodelica/libraries/%s" % libnameOnFile], stdout=diffOut)
  del omc
  return {"errorsInDiff": errorsInDiff, "path": path, "timeForConversion": timeForConversion, "statsByFile": statsByFile, "gcProfStatsBeforeConversion": gcProfStatsBeforeConversion, "gcProfStatsBefore": gcProfStatsBefore, "gcProfStats": gcProfStats}
  
pat = "%s/*/openmodelica.metadata.json" % libdir
with Pool(processes=numThreads) as pool:
  res = pool.map(convertPackage, sorted(glob.glob(pat)))
for r in res:
  if r is None:
    continue
  for f in r["errorsInDiff"]:
    print("Ignored failed perform diff on %s" % f)
shutil.copyfile("%s/index.json" % libdir, "converted-libraries/.openmodelica/libraries/index.json")
with open("result.json", "w") as fout:
  json.dump([r for r in res if r], fout)
