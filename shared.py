#!/usr/bin/env python3

import re, os, subprocess
import simplejson as json

def fixData(data,abortSimulationFlag,alarmFlag,overrideDefaults,defaultCustomCommands,extrasimflags,environmentTranslation,environmentSimulation):
  data["configFromFile"] = dict(data)
  for (key,default) in overrideDefaults:
    if key not in data:
      data[key] = default
  try:
    data["runOnceBeforeTesting"] = (data.get("runOnceBeforeTesting") or [])
    data["simCodeTarget"] = data.get("simCodeTarget") or "C"
    data["referenceFileExtension"] = data.get("referenceFileExtension") or "mat"
    data["referenceFileNameDelimiter"] = data.get("referenceFileNameDelimiter") or "."
    data["default_tolerance"] = float(data.get("default_tolerance") or 1e-6)
    data["reference_reltol"] = float(data.get("reference_reltol") or 3e-3)
    data["reference_reltolDiffMinMax"] = float(data.get("reference_reltolDiffMinMax") or 3e-3)
    data["reference_rangeDelta"] = float(data.get("reference_rangeDelta") or 1e-3)
    if data["simCodeTarget"]=="Cpp":
      defaultCustomCommands2 = defaultCustomCommands[:]
      defaultCustomCommands2.append('setCommandLineOptions("--simCodeTarget=Cpp")')
    else:
      defaultCustomCommands2 = defaultCustomCommands
    data["customCommands"] = (data.get("customCommands") or defaultCustomCommands2) + (data.get("extraCustomCommands") or [])
    data["ulimitOmc"] = int(data.get("ulimitOmc") or 660) # 11 minutes to generate the C-code
    data["ulimitExe"] = int(data.get("ulimitExe") or 8*60) # 8 additional minutes to initialize and run the simulation
    data["ulimitLoadModel"] = int(data.get("ulimitLoadModel") or 90)
    simflags = []
    if data.get("extraSimFlags"):
      simflags.append(data.get("extraSimFlags"))
    if extrasimflags:
      simflags.append(extrasimflags)
    data["extraSimFlags"] = " ".join(simflags) # no extra sim flags
    if data.get("environmentSimulation"):
      data["environmentSimulation"] = data.get("environmentSimulation") + environmentSimulation
    else:
      data["environmentSimulation"] = environmentSimulation
    if data.get("environmentTranslation"):
      data["environmentTranslation"] = data.get("environmentTranslation") + environmentTranslation
    else:
      data["environmentTranslation"] = environmentTranslation
    data["libraryVersion"] = data.get("libraryVersion") or "default"
    data["libraryVersionLatestInPackageManager"] = data.get("libraryVersionLatestInPackageManager") or False
    data["alarmFlag"] = data.get("alarmFlag") or (alarmFlag if data["simCodeTarget"]=="C" else "")
    data["abortSlowSimulation"] = data.get("abortSlowSimulation") or (abortSimulationFlag if data["simCodeTarget"]=="C" else "")
    if "changeHash" in data: # Force rebuilding the library due to change in the testing script
      data["changeHash"] = data["changeHash"]
    return (data["library"],data)
  except:
    print("Failed to fix data for: %s with extra args: %s" % (str(data),str((abortSimulationFlag,alarmFlag,defaultCustomCommands))))
    raise

def readConfig(c,abortSimulationFlag="",alarmFlag="",overrideDefaults=[],defaultCustomCommands=[],extrasimflags="",environmentTranslation=[],environmentSimulation=[]):
  return [fixData(data,abortSimulationFlag,alarmFlag,overrideDefaults,defaultCustomCommands,extrasimflags,environmentTranslation,environmentSimulation) for data in json.load(open(c))]

def libname(library, conf):
  if "libraryVersionNameForTests" in conf:
    return library+"_"+conf["libraryVersionNameForTests"] if conf["libraryVersionNameForTests"] else library
  return library+("_"+conf["libraryVersion"] if conf["libraryVersion"]!="default" else "")+(("_" + conf["configExtraName"]) if "configExtraName" in conf else "")

def finalphaseName(finalphase):
  return ("Failed","FrontEnd","BackEnd","SimCode","Templates","Compile","Simulate","Verify")[finalphase]

def getReferenceFileName(conf):
  referenceFile=""
  if "referenceFiles" in conf:
    modelName = conf["modelName"]
    if "referenceFileNameExtraName" in conf:
      if conf["referenceFileNameExtraName"] == "$ClassName":
        modelName += "."+(modelName.split(".")[-1])
      else:
        modelName += "."+conf["referenceFileNameExtraName"]
    referenceFile = conf["referenceFiles"]+"/"+modelName.replace(".",conf["referenceFileNameDelimiter"])+(conf.get("referenceFinalDot") or ".")+conf["referenceFileExtension"]
    if not os.path.exists(referenceFile) and not os.path.isdir(referenceFile):
      if conf.get("allReferenceFilesExist"):
        raise Exception("Missing reference file %s for config %s" % (referenceFile,conf))
      else:
        referenceFile=""
  return referenceFile

def simulationAcceptsFlag(f, checkOutput=True, cwd=None, isWin=False):
  try:
    os.unlink("HelloWorld_res.mat")
  except OSError:
    pass
  try:
    if isWin:
        subprocess.check_output("HelloWorld.bat %s" % f, shell=True, stderr=subprocess.STDOUT, cwd=cwd)
    else:
        subprocess.check_output("./HelloWorld %s" % f, shell=True, stderr=subprocess.STDOUT, cwd=cwd)

    if (not os.path.exists("HelloWorld_res.mat")):
      print("Result file HelloWorld_res.mat WAS NOT generated running: ./HelloWorld with flags [%s]" % f)
    if (not checkOutput) or os.path.exists("HelloWorld_res.mat"):
      return True
  except subprocess.CalledProcessError as e:
    pass
  return False

def isFMPy(fmisimulator):
  if fmisimulator:
    return 'fmpy' in fmisimulator
  else:
    return False


