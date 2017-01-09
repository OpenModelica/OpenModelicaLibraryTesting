#!/usr/bin/env python3

import simplejson as json

def fixData(data):
  data["referenceFileExtension"] = data.get("referenceFileExtension") or "mat"
  data["referenceFileNameDelimiter"] = data.get("referenceFileNameDelimiter") or "."
  data["default_tolerance"] = data.get("default_tolerance") or 1e-6
  data["reference_reltol"] = data.get("reference_reltol") or 3e-3
  data["reference_reltolDiffMinMax"] = data.get("reference_reltolDiffMinMax") or 3e-3
  data["reference_rangeDelta"] = data.get("reference_rangeDelta") or 1e-3
  defaultCustomCommands = """
setCommandLineOptions("-d=nogen,initialization,backenddaeinfo,discreteinfo,stateselection,execstat");
setMatchingAlgorithm("PFPlusExt");
setIndexReductionMethod("dynamicStateSelection");
"""
  data["customCommands"] = (data.get("customCommands") or defaultCustomCommands) + (data.get("extraCustomCommands") or "")
  data["ulimitOmc"] = data.get("ulimitOmc") or 660 # 11 minutes to generate the C-code
  data["ulimitExe"] = data.get("ulimitExe") or 8*60 # 8 additional minutes to initialize and run the simulation
  data["ulimitMemory"] = data.get("ulimitMemory") or 16000000 # ~16GB memory at most
  data["extraSimFlags"] = data.get("extraSimFlags") or "" # no extra sim flags
  data["libraryVersion"] = data.get("libraryVersion") or "default"
  data["alarmFlag"] = data.get("alarmFlag") or "-alarm"
  data["abortSlowSimulation"] = data.get("abortSlowSimulation") or "-abortSlowSimulation"
  return (data["library"],data)

def readConfig(c):
  return [fixData(data) for data in json.load(open(c))]

def libname(library, conf):
  return library+("_"+conf["libraryVersion"] if conf["libraryVersion"]!="default" else "")+(("_" + conf["configExtraName"]) if "configExtraName" in conf else "")
