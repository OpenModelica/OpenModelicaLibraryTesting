#!/usr/bin/env python2
# -*- coding: utf-8 -*-

import argparse, os, sys, signal, threading, psutil, subprocess
import simplejson as json
from monotonic import monotonic
from OMPython import OMCSession

parser = argparse.ArgumentParser(description='OpenModelica library testing tool helper (single model)')
parser.add_argument('config')
parser.add_argument('--ompython_omhome', default='')

args = parser.parse_args()
config = args.config
ompython_omhome = args.ompython_omhome

try:
  os.mkdir("files")
except OSError:
  pass

class TimeoutError(Exception):
  pass

def sendExpressionTimeout(omc, cmd, timeout):
  def target(res):
    try:
      res[0] = omc.sendExpression(cmd)
    except Exception as e:
      res[1] = cmd + " " + str(e)

  res=[None,None]
  thread = threading.Thread(target=target, args=(res,))
  thread.start()
  thread.join(timeout)

  if thread.is_alive():
    for process in psutil.Process().children(recursive=True):
      try:
        os.kill(process.pid, signal.SIGINT)
      except OSError:
        pass
    thread.join(2)
    if thread.is_alive():
      for process in psutil.Process().children(recursive=True):
        try:
          os.kill(process.pid, signal.SIGKILL)
        except OSError:
          pass
      thread.join()
    if res[1] is None:
      res[1] = ""
  if res[1] is not None:
    raise TimeoutError(res[1])
  return res[0]

def checkOutputTimeout(cmd, timeout):
  def target(res):
    try:
      res[0] = subprocess.check_output(cmd, shell=True, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as e:
      res[1] = cmd + " " + str(e.output)
    except Exception as e:
      res[1] = cmd + " " + str(e)

  res=[None,None]
  thread = threading.Thread(target=target, args=(res,))
  thread.start()
  thread.join(timeout)

  if thread.is_alive():
    for process in psutil.Process().children(recursive=True):
      try:
        os.killpg(process.pid, signal.SIGINT)
      except OSError:
        pass
    thread.join(2)
    if thread.is_alive():
      for process in psutil.Process().children(recursive=True):
        try:
          os.kill(process.pid, signal.SIGKILL)
        except OSError:
          pass
      thread.join()
    if res[1] is None:
      res[1] = ""
  if res[1] is not None:
    raise TimeoutError(res[1])
  return res[0]

execstat = {
  "parsing":None,
  "frontend":None,
  "backend":None,
  "simcode":None,
  "templates":None,
  "build":None,
  "sim":None,
  "diff":None,
  "phase":0
}

with open(config) as fp:
  conf = json.load(fp)

errFile="files/%s.err" % conf["fileName"]
simFile="files/%s.sim" % conf["fileName"]
statFile="files/%s.stat.json" % conf["fileName"]
try:
  os.unlink(errFile)
except OSError:
  pass
try:
  os.unlink(simFile)
except OSError:
  pass

def writeResult():
  with open(statFile, 'w') as fp:
    json.dump(execstat, fp)
    fp.flush()
    os.fsync(fp.fileno())

def writeResultAndExit(exitStatus):
  writeResult()
  sys.exit(exitStatus)

if conf["simCodeTarget"] not in ["Cpp","C"]:
  with open(errFile, 'w+') as fp:
    fp.write("Unknown simCodeTarget in %s" % conf["simCodeTarget"])
  writeResultAndExit(1)
if conf["simCodeTarget"]=="Cpp" and not conf["haveCppRuntime"]:
  with open(errFile, 'w+') as fp:
    fp.write("C++ runtime not supported in this installation (HelloWorld failed)")
  writeResultAndExit(0)

omhome = conf["omhome"]
os.environ["OPENMODELICAHOME"] = omhome

omc = OMCSession()
if ompython_omhome != "":
  os.environ["OPENMODELICAHOME"] = ompython_omhome
  omc_new = OMCSession()
else:
  omc_new = omc

cmd = 'setCommandLineOptions("%s")' % conf["single_thread_cmd"]
if not omc.sendExpression(cmd):
  raise Exception('Could not send %s' % cmd)

try:
  os.unlink("%s.tmpfiles" % conf["fileName"])
except:
  pass
cmd = 'setCommandLineOptions("--running-testsuite=%s.tmpfiles")' % conf["fileName"]
runningTestsuiteFiles = False
if omc.sendExpression(cmd):
  runningTestsuiteFiles = True

# Hide errors for old-school running-testsuite flags...
omc._omc.sendExpression("getErrorString()")

outputFormat="mat"
referenceVars=[]
referenceFile = conf.get("referenceFile") or ""
if "referenceFiles" in conf:
  modelName = conf["modelName"]
  if "referenceFileNameExtraName" in conf:
    if conf["referenceFileNameExtraName"] == "$ClassName":
      modelName += "."+(modelName.split(".")[-1])
    else:
      modelName += "."+conf["referenceFileNameExtraName"]
  referenceFile = conf["referenceFiles"]+"/"+modelName.replace(".",conf["referenceFileNameDelimiter"])+"."+conf["referenceFileExtension"]
  if os.path.exists(referenceFile):
    try:
      referenceVars=omc_new.sendExpression('readSimulationResultVars("%s", readParameters=true, openmodelicaStyle=true)' % referenceFile)
      variableFilter="|".join([v.replace("[",".").replace("]",".").replace("(",".").replace(")",".").replace('"',".") for v in referenceVars])
      emit_protected="-emit_protected"
    except:
      referenceFile=""
  else:
    referenceFile=""
if referenceFile=="":
  variableFilter=""
  outputFormat="empty"
  emit_protected=""
"""TODO:
compareVarsUri := "modelica://" + /*libraryString*/ "Buildings" + "/Resources/Scripts/OpenModelica/compareVars/#modelName#.mos";
(compareVarsFile,compareVarsFileMessages) := uriToFilename(compareVarsUri);

if regularFileExists(compareVarsFile) then
  runScript(compareVarsFile);
  vars := compareVars;
  variableFilter := sum(stringReplace(stringReplace(s,"[","."),"]",".") + "|" for s in vars) + "time";
  numCompared := size(vars,1);
  emit_protected := " -emit_protected";
"""
# print(variableFilter)

for cmd in conf["customCommands"]:
  omc._omc.sendExpression(cmd)

cmd = 'loadModel(%s, {"%s"})' % (conf["library"], conf["libraryVersion"])
start=monotonic()
try:
  if not sendExpressionTimeout(omc, cmd, conf["ulimitLoadModel"]):
    print(omc.sendExpression('OpenModelica.Scripting.getErrorString()'))
    sys.exit(1)
except TimeoutError as e:
  execstat["parsing"]=monotonic()-start
  with open(errFile, 'a+') as fp:
    fp.write("Timeout error for cmd: %s\n%s"%(cmd,str(e)))
  writeResultAndExit(0)
execstat["parsing"]=monotonic()-start

try:
  (startTime,stopTime,tolerance,numberOfIntervals,stepSize)=omc.sendExpression('getSimulationOptions(%s,defaultTolerance=%s,defaultNumberOfIntervals=2500)' % (conf["modelName"],conf["default_tolerance"]))
except:
  # Broken/old getSimulationOptions; use new one (requires parsing again)
  assert(ompython_omhome!="")
  assert(omc_new.sendExpression('setModelicaPath("%s/lib/omlibrary")' % omhome))
  if not omc_new.sendExpression(cmd):
    print(omc_new.sendExpression('OpenModelica.Scripting.getErrorString()'))
    sys.exit(1)
  (startTime,stopTime,tolerance,numberOfIntervals,stepSize)=omc_new.sendExpression('getSimulationOptions(%s,defaultTolerance=%s,defaultNumberOfIntervals=2500)' % (conf["modelName"],conf["default_tolerance"]))

# TODO: Detect and handle the case where RT_CLOCK is not available in OMC
total_before = omc.sendExpression("OpenModelica.Scripting.Internal.Time.timerTock(OpenModelica.Scripting.Internal.Time.RT_CLOCK_SIMULATE_TOTAL)")
start=monotonic()
cmd='translateModel(%s,tolerance=%g,outputFormat="%s",numberOfIntervals=%d,variableFilter="%s",fileNamePrefix="%s")' % (conf["modelName"],tolerance,outputFormat,2*numberOfIntervals,variableFilter,conf["fileName"])
try:
  res=sendExpressionTimeout(omc, cmd, conf["ulimitOmc"])
except TimeoutError as e:
  execstat["frontend"]=monotonic()-start
  with open(errFile, 'a+') as fp:
    fp.write("Timeout error for cmd: %s\n%s"%(cmd,str(e)))
  writeResultAndExit(0)

# See which translateModel phases completed

execTimeTranslateModel=monotonic()-start
err=omc.sendExpression("OpenModelica.Scripting.getErrorString()")
total    = omc.sendExpression("OpenModelica.Scripting.Internal.Time.timerTock(OpenModelica.Scripting.Internal.Time.RT_CLOCK_SIMULATE_TOTAL)")-total_before
templates= omc.sendExpression("OpenModelica.Scripting.Internal.Time.timerTock(OpenModelica.Scripting.Internal.Time.RT_CLOCK_TEMPLATES)")
simcode  = omc.sendExpression("OpenModelica.Scripting.Internal.Time.timerTock(OpenModelica.Scripting.Internal.Time.RT_CLOCK_SIMCODE)")
backend  = omc.sendExpression("OpenModelica.Scripting.Internal.Time.timerTock(OpenModelica.Scripting.Internal.Time.RT_CLOCK_BACKEND)")
frontend = omc.sendExpression("OpenModelica.Scripting.Internal.Time.timerTock(OpenModelica.Scripting.Internal.Time.RT_CLOCK_FRONTEND)")

writeResult()
try:
  del omc
except:
  pass

print(execTimeTranslateModel,frontend,backend)
if backend != -1:
  execstat["frontend"]=frontend-backend
  if templates != -1:
    execstat["backend"]=backend-simcode
    if simcode != -1:
      execstat["simcode"]=simcode-templates
      if templates != -1:
        # assert(res) ?
        execstat["templates"]=templates
        execstat["phase"]=4 if res else 3
      else:
        execstat["phase"]=3
        execstat["templates"]=templates
    else:
      execstat["phase"]=2
      execstat["simcode"]=simcode
  else:
    execstat["phase"]=1
    execstat["backend"]=backend
else:
  execstat["phase"]=0
  execstat["frontend"]=frontend

with open(errFile, 'w') as fp:
  fp.write(err)

if execstat["phase"] < 4:
  writeResultAndExit(0)

start=monotonic()
try:
  res = checkOutputTimeout("make -j1 -f %s.makefile" % conf["fileName"], conf["ulimitOmc"])
  execstat["build"] = monotonic()-start
  execstat["phase"] = 5
except TimeoutError as e:
  execstat["build"] = monotonic()-start
  with open(errFile, 'a') as fp:
    fp.write(str(e))
  writeResultAndExit(0)

writeResult()
# Do the simulation

start=monotonic()
try:
  # TODO: Timeout more reliably...
  res = checkOutputTimeout("(rm -f %s.pipe ; mkfifo %s.pipe ; head -c 1048576 < %s.pipe > %s & ./%s %s %s 2>&1 > %s.pipe)" % (conf["fileName"],conf["fileName"],conf["fileName"],simFile,conf["fileName"],conf["simFlags"],emit_protected,conf["fileName"]), conf["ulimitExe"])
  execstat["sim"] = monotonic()-start
  execstat["phase"] = 6
except TimeoutError as e:
  execstat["sim"] = monotonic()-start
  writeResultAndExit(0)

if referenceFile=="":
  writeResultAndExit(0)

# Check the reference file...

prefix = "files/%s.diff" % conf["fileName"]
resFile = "%s_res.%s" % (conf["fileName"], outputFormat)

if not os.path.exists(resFile):
  with open(errFile, 'a') as fp:
    fp.write("TODO: How the !@#!# did the simulation report success but not simulation result exists to compare?")
  writeResultAndExit(0)

start=monotonic()
(referenceOK,diffVars) = sendExpressionTimeout(omc_new, 'diffSimulationResults("%s","%s","%s",relTol=%g,relTolDiffMinMax=%g,rangeDelta=%g)' %
                             (resFile, referenceFile, prefix,conf["reference_reltol"],conf["reference_reltolDiffMinMax"],conf["reference_rangeDelta"]), conf["ulimitOmc"])
execstat["diff"] = {"time":monotonic()-start, "vars":[], "numCompared":len(referenceVars)}
if len(diffVars)==0 and referenceOK:
  execstat["phase"]=7
else:
  with open(errFile, 'a') as fp:
    fp.write(omc_new._omc.sendExpression('OpenModelica.Scripting.getErrorString()'))
    fp.write("\nVariables in the reference:" )
    fp.write(",".join(referenceVars)+"\n")
    resVars=omc_new.sendExpression('readSimulationResultVars("%s", readParameters=true, openmodelicaStyle=true)' % resFile)
    fp.write("\nVariables in the result:" )
    fp.write(",".join(resVars)+"\n")
  diffFiles = [prefix + "." + var for var in diffVars]
  execstat["diff"]["vars"]=diffVars

  # Create a file containing only the calibrated variables, for easy display
  lstfiles = "\n".join(['<li>%s <a href="%s.html">(javascript)</a> <a href="%s.csv">(csv)</a></li>' % (str.split(f,".diff.",1)[1],str(os.path.basename(f)),str(os.path.basename(f))) for f in diffFiles])
  with open(prefix+".html", 'w') as fp:
    fp.write("<html><body><h1>%s differences from the reference file</h1><p>startTime: %g</p><p>stopTime: %g</p><p>Simulated using tolerance: %g</p><ul>%s</ul></body></html>" % (conf["modelName"], startTime, stopTime, tolerance, lstfiles));
  for var in diffVars:
    if "/" in var:
      continue # Quoted identifier, or possibly an error message... Either way, avoid crapping out below
    with open(prefix+"."+var+".html", 'w') as fp:
      fp.write("""<html>
<head>
<script type="text/javascript" src="dygraph-combined.js"></script>
    <style type="text/css">
    #graphdiv {
      position: absolute;
      left: 10px;
      right: 10px;
      top: 40px;
      bottom: 10px;
    }
    </style>
</head>
<body>
<div id="graphdiv"></div>
<p><input type=checkbox id="0" checked onClick="change(this)">
<label for="0">reference</label>
<input type=checkbox id="1" checked onClick="change(this)">
<label for="1">actual</label>
<input type=checkbox id="2" checked onClick="change(this)">
<label for="2">high</label>
<input type=checkbox id="3" checked onClick="change(this)">
<label for="3">low</label>
<input type=checkbox id="4" checked onClick="change(this)">
<label for="4">error</label>
<input type=checkbox id="5" onClick="change(this)">
<label for="5">actual (original)</label>
Parameters used for the comparison: Relative tolerance %g (local), %g (relative to max-min). Range delta %g.</p>
<script type="text/javascript">
g = new Dygraph(document.getElementById("graphdiv"),
                 "%s",{title: '"%s"',
  legend: 'always',
  connectSeparatedPoints: true,
  xlabel: ['time'],
  y2label: ['error'],
  series : { 'error': { axis: 'y2' } },
  colors: ['blue','red','teal','lightblue','orange','black'],
  visibility: [true,true,true,true,true,false]
});
function change(el) {
  g.setVisibility(parseInt(el.id), el.checked);
}
</script>
</body>
</html>""" % (tolerance, conf["reference_reltolDiffMinMax"], conf["reference_rangeDelta"], os.path.basename(prefix + "." + var + ".csv"), var))

writeResultAndExit(0)
