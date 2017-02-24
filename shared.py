#!/usr/bin/env python3

import simplejson as json

def fixData(data,rmlStyle,abortSimulationFlag,alarmFlag,defaultCustomCommands):
  data["simCodeTarget"] = data.get("simCodeTarget") or "C"
  data["referenceFileExtension"] = data.get("referenceFileExtension") or "mat"
  data["referenceFileNameDelimiter"] = data.get("referenceFileNameDelimiter") or "."
  data["default_tolerance"] = data.get("default_tolerance") or 1e-6
  data["reference_reltol"] = data.get("reference_reltol") or 3e-3
  data["reference_reltolDiffMinMax"] = data.get("reference_reltolDiffMinMax") or 3e-3
  data["reference_rangeDelta"] = data.get("reference_rangeDelta") or 1e-3
  debug = "+d" if rmlStyle else "-d"
  if data["simCodeTarget"]!="C":
    defaultCustomCommands.append('setCommandLineOptions("%ssimCodeTarget=cpp")' % ("+" if rmlStyle else "--"))
  data["customCommands"] = (data.get("customCommands") or defaultCustomCommands) + (data.get("extraCustomCommands") or [])
  data["ulimitOmc"] = data.get("ulimitOmc") or 660 # 11 minutes to generate the C-code
  data["ulimitExe"] = data.get("ulimitExe") or 8*60 # 8 additional minutes to initialize and run the simulation
  data["ulimitLoadModel"] = data.get("ulimitLoadModel") or 90
  data["ulimitMemory"] = data.get("ulimitMemory") or 14000000 # ~14GB memory at most
  data["extraSimFlags"] = data.get("extraSimFlags") or "" # no extra sim flags
  data["libraryVersion"] = data.get("libraryVersion") or "default"
  data["alarmFlag"] = data.get("alarmFlag") or (alarmFlag if data["simCodeTarget"]=="C" else "")
  data["abortSlowSimulation"] = data.get("abortSlowSimulation") or (abortSimulationFlag if data["simCodeTarget"]=="C" else "")
  return (data["library"],data)

def readConfig(c,rmlStyle=False,abortSimulationFlag="",alarmFlag="",defaultCustomCommands=[]):
  return [fixData(data,rmlStyle,abortSimulationFlag,alarmFlag,defaultCustomCommands) for data in json.load(open(c))]

def libname(library, conf):
  return library+("_"+conf["libraryVersion"] if conf["libraryVersion"]!="default" else "")+(("_" + conf["configExtraName"]) if "configExtraName" in conf else "")
