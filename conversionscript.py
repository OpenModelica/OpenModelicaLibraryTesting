#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from OMPython import OMCSessionZMQ
import argparse
import glob
import json
import os
import shutil
import subprocess
from multiprocessing import Pool


parser = argparse.ArgumentParser(description='OpenModelica library testing tool')
parser.add_argument('libdir', nargs=1)
parser.add_argument('--diff', action="store_true")
parser.add_argument('-n', type=int, default=12)
args = parser.parse_args()
libdir = args.libdir[0]
numThreads = args.n
createDiff = args.diff

try:
  shutil.rmtree("converted-libraries")
except:
  pass
os.mkdir("converted-libraries")

def omcAssert(omc, cmd, extra=""):
  res = omc.sendExpression(cmd)
  if not res:
    raise Exception(cmd + "\n" + extra + "\n" + (omc.sendExpression("getErrorString()") or ""))

mslPath = "%s/Modelica 4.0.0+maint.om/" % libdir
with open("%s/openmodelica.metadata.json" % mslPath) as f:
  mslData = json.load(f)
  convertFromVersion = mslData['convertFromVersion']
conversionScript = "%s/Resources/Scripts/Conversion/ConvertModelica_from_3.2.3_to_4.0.0.mos" % mslPath

def convertPackage(p):
  with open(p) as f:
    data = json.load(f)
  uses=data.get('uses',{})
  libnameOnFile = os.path.basename(os.path.dirname(p))
  libname = libnameOnFile.split(" ")[0]
  shutil.copytree(os.path.dirname(p), "converted-libraries/%s" % libnameOnFile)
  for root, dir, files in os.walk("converted-libraries/%s" % libnameOnFile):
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
      return
  if not uses.get('Modelica','0.0.0') in convertFromVersion:
    return
  if libname in ["Modelica", "ModelicaServices", "Complex", "ModelicaTest", "ModelicaTestOverdetermined"]:
    return
  if libname in ["AixLib", "FCSys", "SiemensPower", "ScalableTestSuite", "ThermoSysPro", "ThermoPower"]:
    # conversion broken
    return
  omc = OMCSessionZMQ()
  omcAssert(omc, 'loadFile("converted-libraries/%s/package.mo", uses=false)' % libnameOnFile)
  errString = omc.sendExpression("getErrorString()")
  if errString:
    print(errString)
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
  for (newFile, newClass) in fileMapping.items():
    oldFile = os.path.join(libdir, newFile.split("converted-libraries/")[1])
    assert(newFile != oldFile)
    before = omc.sendExpression('before := readFile("%s")' % newFile)
    after = omc.sendExpression('after := listFile(%s)' % newClass)
    if (not before) or (not after):
      raise Exception("%s %s (%s). %s. before: %s after: %s" % (oldFile, newFile, newClass, omc.sendExpression('getErrorString()'), str(type(before)), str(type(after))))
    omc.sendExpression("getErrorString()")
    if libname in []: # If we have libraries where the diff algorithm fails in the future
      res = omc.sendExpression('res := after') # Skip the diff
    else:
      res = omc.sendExpression('res := diffModelicaFileListings(before, after, OpenModelica.Scripting.DiffFormat.plain)')
    if not res:
      omc.sendExpression('writeFile("%s", after)' % newFile)
      print(omc.sendExpression("getErrorString()"))
      raise Exception('before:=readFile("%s");\nafter:=readFile("%s");\ndiffModelicaFileListings(before, after, OpenModelica.Scripting.DiffFormat.plain);\ngetErrorString();' % (oldFile, newFile))
      
    omcAssert(omc, 'writeFile("%s", res)' % (newFile))
  path = "converted-libraries/%s/openmodelica.metadata.json" % libnameOnFile
  with open(path, "w") as f:
    print("Converted %s" % path)
    data["uses"] = dict(uses)
    data["extraInfo"] = "Conversion script %s was applied" % conversionScript
    json.dump(data, f)
  if createDiff:
    diffOutput = subprocess.run(["diff", "-ur", os.path.dirname(p), "converted-libraries/%s" % libnameOnFile], capture_output=True)
    diffOutputFile = "converted-libraries/%s.diff" % libnameOnFile
    print("Creating %s" % diffOutputFile)
    with open(diffOutputFile, "wb") as diffOut:
      diffOut.write(diffOutput.stdout)
  del omc
  
pat = "%s/*/openmodelica.metadata.json" % libdir
with Pool(processes=numThreads) as pool:
  res = pool.map(convertPackage, sorted(glob.glob(pat)))
