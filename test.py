#!/usr/bin/env python2
# -*- coding: utf-8 -*-

# TODO: When libraries hash changes, run with the old OMC against the new libs
#       Then run with the new OMC against the new libs

import cgi
import sys
import os
import re
from joblib import Parallel, delayed
import time
import simplejson as json
import argparse
import sqlite3
import datetime
import psutil, subprocess, threading
from subprocess import call
from monotonic import monotonic
from omcommon import friendlyStr, multiple_replace

def runCommand(cmd, timeout):
  process = [None]
  def target():
    process[0] = subprocess.Popen(cmd, shell=True)
    process[0].communicate()

  thread = threading.Thread(target=target)
  thread.start()
  thread.join(timeout)

  if thread.is_alive():
    parent = psutil.Process(process[0].pid)
    killedSome = False
    for child in parent.children(recursive=True):
      if child.name() != "omc":
        print "Timeout, killing %s: %s" % (cmd.split(" ")[-1], child.name())
        child.kill()
        killedSome = True
    if killedSome:
      thread.join(min(10, timeout))
    if thread.is_alive():
      for child in parent.children(recursive=True):
        try:
          print "Timeout, killing %s: %s" % (cmd.split(" ")[-1], child.name())
          child.kill()
        except:
          pass
      try:
        process[0].terminate()
      except:
        pass
    thread.join()

  return process[0].returncode

parser = argparse.ArgumentParser(description='OpenModelica library testing tool')
parser.add_argument('configs', nargs='*')
parser.add_argument('--branch', default='master')
parser.add_argument('--output', default='')
parser.add_argument('-n', default=psutil.cpu_count(logical=False))

args = parser.parse_args()
configs = args.configs
branch = args.branch
result_location = args.output
n_jobs = args.n
print("branch: %s, n_jobs: %d" % (branch, n_jobs))

if result_location != "" and not os.path.exists(result_location):
  os.makedirs(result_location)

if configs == []:
  print("Error: Expected at least one configuration file to start the library test")
  sys.exit(1)

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
  return (data["library"],data)

def readConfig(c):
  return [fixData(data) for data in json.load(open(c))]

configs_lst = [readConfig(c) for c in configs]
configs = []
for c in configs_lst:
  configs = configs + c

from OMPython import OMCSession
omc = OMCSession()

omhome=omc.sendExpression('getInstallationDirectoryPath()')
omc_exe=os.path.join(omhome,"bin","omc")
omc_version=omc.sendExpression('getVersion()')
dygraphs=os.path.join(omhome,"share","doc","omc","testmodels","dygraph-combined.js")
print(omc_exe,dygraphs)

# Create mos-files

if not omc.sendExpression('setCommandLineOptions("-g=MetaModelica")'):
  print("Failed to set MetaModelica grammar")
  sys.exit(1)

stats_by_libname = {}
tests=[]
for (library,conf) in configs:
  omc.sendExpression('clear()')
  if not omc.sendExpression('loadModel(%s,{"%s"})' % (library,conf["libraryVersion"])):
    print("Failed to load library: " + omc.sendExpression('getErrorString()'))
    sys.exit(1)
  conf["libraryVersionRevision"]=omc.sendExpression('getVersion(%s)' % library)
  conf["libraryLastChange"]="" # TODO: FIXME
  librarySourceFile=omc.sendExpression('getSourceFile(%s)' % library)
  lastChange=(librarySourceFile[:-3]+".last_change") if not librarySourceFile.endswith("package.mo") else (os.path.dirname(librarySourceFile)+".last_change")
  if os.path.exists(lastChange):
    conf["libraryLastChange"] = " %s (revision %s)" % (conf["libraryVersionRevision"],"\n".join(open(lastChange).readlines()).strip())
  res=omc.sendExpression('{c for c guard isExperiment(c) and not regexBool(typeNameString(x), "^Modelica_Synchronous\\.WorkInProgress") in getClassNames(%s, recursive=true)}' % library)
  libName=library+"_"+conf["libraryVersion"]+(("_" + conf["configExtraName"]) if conf.has_key("configExtraName") else "")
  stats_by_libname[libName] = {"conf":conf, "stats":[]}
  tests = tests + [(r,library,libName,libName+"_"+r,conf) for r in res]

template = open("BuildModel.mos.tpl").read()

for (modelName,library,libName,name,conf) in tests:
  simFlags="-abortSlowSimulation -alarm=%d %s" % (conf["ulimitExe"],conf["extraSimFlags"])
  replacements = (
    (u"#logFile#", "/tmp/OpenModelicaLibraryTesting.log"),
    (u"#library#", library),
    (u"#modelName#", modelName),
    (u"#fileName#", name),
    (u"#customCommands#", conf["customCommands"]),
    (u"#modelVersion#", conf["libraryVersionRevision"]),
    (u"#ulimitOmc#", str(conf["ulimitOmc"])),
    (u"#default_tolerance#", str(conf["default_tolerance"])),
    (u"#reference_reltol#", str(conf["reference_reltol"])),
    (u"#reference_reltolDiffMinMax#", str(conf["reference_reltolDiffMinMax"])),
    (u"#reference_rangeDelta#", str(conf["reference_rangeDelta"])),
    (u"#simFlags#", simFlags),
    (u"#referenceFiles#", str(conf.get("referenceFiles") or "")),
    (u"#referenceFileNameDelimiter#", conf["referenceFileNameDelimiter"]),
    (u"#referenceFileExtension#", conf["referenceFileExtension"]),
  )
  open(name + ".mos", "w").write(multiple_replace(template, *replacements))

def runScript(c, timeout):
  j = "files/%s.stat.json" % c
  if os.path.exists(j):
    os.remove(j)
  start=monotonic()
  runCommand("%s -n=1 %s.mos" % (omc_exe, c), timeout=timeout)
  execTime=monotonic()-start
  assert(execTime >= 0.0)
  if os.path.exists(j):
    data=json.load(open(j))
    data["exectime"] = execTime
    json.dump(data, open(j,"w"))
  else:
    data = {"exectime":execTime,"phase":0}
    json.dump(data, open(j,"w"))

conn = sqlite3.connect('sqlite3.db')
cursor = conn.cursor()
# BOOLEAN NOT NULL CHECK (verify IN (0,1) AND builds IN (0,1) AND simulates IN (0,1))
cursor.execute('''CREATE TABLE if not exists [%s]
             (date integer NOT NULL, libname text NOT NULL, model text NOT NULL, exectime real NOT NULL,
             frontend real NOT NULL, backend real NOT NULL, simcode real NOT NULL, templates real NOT NULL, compile real NOT NULL, simulate real NOT NULL,
             verify real NOT NULL, verifyfail integer NOT NULL, verifytotal integer NOT NULL, finalphase integer NOT NULL)''' % branch)

def expectedExec(c):
  (model,lib,libName,name,data) = c
  cursor.execute("SELECT exectime FROM [%s] WHERE libname = ? AND model = ? ORDER BY date DESC LIMIT 1" % branch, (libName,model))
  v = cursor.fetchone()
  return (v or (0.0,))[0]

tests=sorted(tests, key=lambda c: expectedExec(c), reverse=True)

cmd_res=[0]
start=monotonic()
start_as_time=time.localtime()
testRunStartTimeAsEpoch = int(start)
cmd_res=Parallel(n_jobs=n_jobs)(delayed(runScript)(name, 1.1*data["ulimitOmc"]+1.1*data["ulimitExe"]) for (model,lib,libName,name,data) in tests)
stop=monotonic()
print("Execution time: %.2f" % (stop-start))
assert(stop-start >= 0.0)

#if max(cmd_res) > 0:
#  raise Exception("A command failed with exit status")

stats=dict([(name,(name,model,libname,json.load(open("files/%s.stat.json" % name)))) for (model,lib,libname,name,conf) in tests])
for k in sorted(stats.keys(), key=lambda c: stats[c][3]["exectime"], reverse=True):
  print("%s: exectime %.2f" % (k, stats[k][3]["exectime"]))

for key in stats.keys():
  #new_stats[key] = stats[key][2]
  try:
    lines = open("%s.tmpfiles" % key).readlines()
  except:
    lines = []
  for line in lines:
    try:
      os.unlink(line.strip())
    except:
      pass
      #print("Failed to unlink: %s" % line.strip())
  (name,model,libname,data)=stats[key]
  stats_by_libname[libname]["stats"].append(stats[key])
  values = (testRunStartTimeAsEpoch,
    libname,
    model,
    data.get("exectime") or 0.0,
    data.get("frontend") or 0.0,
    data.get("backend") or 0.0,
    data.get("simcode") or 0.0,
    data.get("templates") or 0.0,
    data.get("build") or 0.0,
    data.get("sim") or 0.0,
    (data.get("diff") or {}).get("time") or 0.0,
    len((data.get("diff") or {}).get("vars") or []),
    (data.get("diff") or {}).get("numCompared") or 0,
    data.get("phase") or 0
  )
  # print values
  cursor.execute("INSERT INTO [%s] VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)" % branch, values)
conn.commit()
conn.close()

def checkNumSucceeded(numSucceeded, n):
  if numSucceeded[n]==numSucceeded[n-1]:
    return "#00FF00"
  else:
    return "#FFCC66"

def checkPhase(phase, n):
  if phase >= n:
    return "#00FF00"
  else:
    return "#FFCC66"

def is_non_zero_file(fpath):
    return os.path.isfile(fpath) and os.path.getsize(fpath) > 0

htmltpl=open("library.html.tpl").read()
for libname in stats_by_libname.keys():
  filesList = open(libname + ".files", "w")
  filesList.write("/\n")
  filesList.write("/%s.html\n" % libname)
  filesList.write("/files/\n")
  conf = stats_by_libname[libname]["conf"]
  stats = stats_by_libname[libname]["stats"]
  for s in stats:
    filename_prefix = "files/%s_%s" % (s[2],s[1])
    if is_non_zero_file(filename_prefix+".sim"):
      filesList.write("/%s.sim\n" % filename_prefix)
    if is_non_zero_file(filename_prefix+".err"):
      filesList.write("/%s.err\n" % filename_prefix)
    variables = (s[3].get("diff") or {}).get("vars") or []
    if len(variables)>0:
      filesList.write("/%s.diff.html\n" % filename_prefix)
    for v in variables:
      filesList.write("/%s.diff.%s.csv\n" % (filename_prefix, v))
      filesList.write("/%s.diff.%s.html\n" % (filename_prefix, v))
  filesList.close()
  testsHTML = "\n".join(['<tr><td>%s%s</td><td bgcolor="%s">%s</td><td bgcolor="%s">%s</td><td bgcolor="%s">%s</td><td bgcolor="%s">%s</td><td bgcolor="%s">%s</td><td bgcolor="%s">%s</td><td bgcolor="%s">%s</td><td bgcolor="%s">%s</td></tr>\n' %
    (lambda filename_prefix:
      (
      ('<a href="%s">%s</a>' % (filename_prefix + ".err", cgi.escape(s[1]))) if is_non_zero_file(filename_prefix + ".err") else cgi.escape(s[1]),
      (' (<a href="%s">sim</a>)' % (filename_prefix + ".sim")) if is_non_zero_file(filename_prefix + ".sim") else "",
      checkPhase(s[3]["phase"], 7) if s[3]["phase"]>=6 else "#FFFFFF",
      ("%s (%d verified)" % (friendlyStr(s[3]["diff"]["time"]), s[3]["diff"]["numCompared"])) if s[3]["phase"]>=7 else ("&nbsp;" if s[3]["diff"] is None else
      ('%s (<a href="%s.diff.html">%d/%d failed</a>)' % (friendlyStr(s[3]["diff"]["time"]), filename_prefix, len(s[3]["diff"]["vars"]), s[3]["diff"]["numCompared"]))),
      checkPhase(s[3]["phase"], 6),
      friendlyStr(s[3].get("sim") or 0),
      checkPhase(s[3]["phase"], 5),
      friendlyStr(sum(s[3].get(x) or 0.0 for x in ["frontend","backend","simcode","templates","build"])),
      checkPhase(s[3]["phase"], 1),
      friendlyStr(s[3].get("frontend") or 0),
      checkPhase(s[3]["phase"], 2),
      friendlyStr(s[3].get("backend") or 0),
      checkPhase(s[3]["phase"], 3),
      friendlyStr(s[3].get("simcode") or 0),
      checkPhase(s[3]["phase"], 4),
      friendlyStr(s[3].get("templates") or 0),
      checkPhase(s[3]["phase"], 5),
      friendlyStr(s[3].get("build") or 0)
    ))(filename_prefix="files/%s_%s" % (s[2], s[1]))
    for s in sorted(stats, key=lambda s: s[1])])
  numSucceeded = [len(stats)] + [sum(1 if s[3]["phase"]>=i else 0 for s in stats) for i in range(1,8)]
  replacements = (
    (u"#omcVersion#", cgi.escape(omc_version)),
    (u"#timeStart#", cgi.escape(time.strftime('%Y-%m-%d %H:%M:%S', start_as_time))),
    (u"#fileName#", cgi.escape(libname)),
    (u"#customCommands#", cgi.escape(conf["customCommands"])),
    (u"#libraryVersionRevision#", cgi.escape(conf["libraryVersionRevision"])),
    (u"#ulimitOmc#", cgi.escape(str(conf["ulimitOmc"]))),
    (u"#ulimitExe#", cgi.escape(str(conf["ulimitExe"]))),
    (u"#default_tolerance#", cgi.escape(str(conf["default_tolerance"]))),
    (u"#simFlags#", cgi.escape(simFlags)),
    (u"#Total#", cgi.escape(str(numSucceeded[0]))),
    (u"#FrontendColor#", checkNumSucceeded(numSucceeded, 1)),
    (u"#BackendColor#", checkNumSucceeded(numSucceeded, 2)),
    (u"#SimCodeColor#", checkNumSucceeded(numSucceeded, 3)),
    (u"#TemplatesColor#", checkNumSucceeded(numSucceeded, 4)),
    (u"#CompilationColor#", checkNumSucceeded(numSucceeded, 5)),
    (u"#SimulationColor#", checkNumSucceeded(numSucceeded, 6)),
    (u"#VerificationColor#", checkNumSucceeded(numSucceeded, 7)),
    (u"#Frontend#", cgi.escape(str(numSucceeded[1]))),
    (u"#Backend#", cgi.escape(str(numSucceeded[2]))),
    (u"#SimCode#", cgi.escape(str(numSucceeded[3]))),
    (u"#Templates#", cgi.escape(str(numSucceeded[4]))),
    (u"#Compilation#", cgi.escape(str(numSucceeded[5]))),
    (u"#Simulation#", cgi.escape(str(numSucceeded[6]))),
    (u"#Verification#", cgi.escape(str(numSucceeded[7]))),
    (u"#totalTime#", cgi.escape(str(datetime.timedelta(seconds=int(sum(s[3]["exectime"] for s in stats)))))),
    (u"#testsHTML#", testsHTML)
  )
  open("%s.html" % libname, "w").write(multiple_replace(htmltpl, *replacements))
  if result_location != "":
    cmd = ["rsync", "-a", "--delete-excluded", "--include-from=%s.files" % libname, "--exclude=*", "./", "%s/%s" % (result_location, s[2])]
    if 0 != call(cmd):
      print("Error: Failed to rsync files: %s" % cmd)
      sys.exit(1)

#json.dump(new_stats, open(".db","w"))

# Upload omc directory to build slaves


# Run jobs on slaves in parallel
