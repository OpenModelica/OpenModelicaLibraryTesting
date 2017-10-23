#!/usr/bin/env python3

import os
import simplejson as json
import subprocess

def fixData(data,rmlStyle,abortSimulationFlag,alarmFlag,defaultCustomCommands):
  try:
    data["simCodeTarget"] = data.get("simCodeTarget") or "C"
    data["referenceFileExtension"] = data.get("referenceFileExtension") or "mat"
    data["referenceFileNameDelimiter"] = data.get("referenceFileNameDelimiter") or "."
    data["default_tolerance"] = data.get("default_tolerance") or 1e-6
    data["reference_reltol"] = data.get("reference_reltol") or 3e-3
    data["reference_reltolDiffMinMax"] = data.get("reference_reltolDiffMinMax") or 3e-3
    data["reference_rangeDelta"] = data.get("reference_rangeDelta") or 1e-3
    debug = "+d" if rmlStyle else "-d"
    if data["simCodeTarget"]=="Cpp":
      defaultCustomCommands2 = defaultCustomCommands[:]
      defaultCustomCommands2.append('setCommandLineOptions("%ssimCodeTarget=Cpp")' % ("+" if rmlStyle else "--"))
    else:
      defaultCustomCommands2 = defaultCustomCommands
    data["customCommands"] = (data.get("customCommands") or defaultCustomCommands2) + (data.get("extraCustomCommands") or [])
    data["ulimitOmc"] = data.get("ulimitOmc") or 660 # 11 minutes to generate the C-code
    data["ulimitExe"] = data.get("ulimitExe") or 8*60 # 8 additional minutes to initialize and run the simulation
    data["ulimitLoadModel"] = data.get("ulimitLoadModel") or 90
    data["ulimitMemory"] = data.get("ulimitMemory") or 14000000 # ~14GB memory at most
    data["extraSimFlags"] = data.get("extraSimFlags") or "" # no extra sim flags
    data["libraryVersion"] = data.get("libraryVersion") or "default"
    data["alarmFlag"] = data.get("alarmFlag") or (alarmFlag if data["simCodeTarget"]=="C" else "")
    data["abortSlowSimulation"] = data.get("abortSlowSimulation") or (abortSimulationFlag if data["simCodeTarget"]=="C" else "")
    if "changeHash" in data: # Force rebuilding the library due to change in the testing script
      data["changeHash"] = data["changeHash"]
    return (data["library"],data)
  except:
    print("Failed to fix data for: %s with extra args: %s" % (str(data),str((rmlStyle,abortSimulationFlag,alarmFlag,defaultCustomCommands,defaultCustomCommands2))))
    raise

def readConfig(c,rmlStyle=False,abortSimulationFlag="",alarmFlag="",defaultCustomCommands=[]):
  return [fixData(data,rmlStyle,abortSimulationFlag,alarmFlag,defaultCustomCommands) for data in json.load(open(c))]

def libname(library, conf):
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
    referenceFile = conf["referenceFiles"]+"/"+modelName.replace(".",conf["referenceFileNameDelimiter"])+"."+conf["referenceFileExtension"]
    if not os.path.exists(referenceFile):
      if conf.get("allReferenceFilesExist"):
        raise Exception("Missing reference file %s for config %s" % (referenceFile,conf))
      else:
        referenceFile=""
  return referenceFile

def simulationAcceptsFlag(f, checkOutput=True):
  try:
    os.unlink("HelloWorld_res.mat")
  except OSError:
    pass
  try:
    subprocess.check_output("./HelloWorld %s" % f, shell=True, stderr=subprocess.STDOUT)
    if (not checkOutput) or os.path.exists("HelloWorld_res.mat"):
      return True
  except subprocess.CalledProcessError as e:
    pass
  return False
