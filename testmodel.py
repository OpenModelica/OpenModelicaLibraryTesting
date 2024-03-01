#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse, os, sys, signal, threading, psutil, subprocess, shutil
from asyncio.subprocess import STDOUT
import simplejson as json
from monotonic import monotonic
from OMPython import FindBestOMCSession, OMCSession, OMCSessionZMQ
import shared

parser = argparse.ArgumentParser(description='OpenModelica library testing tool helper (single model)')
parser.add_argument('config')
parser.add_argument('--ompython_omhome', default='')
parser.add_argument('--libraries')
parser.add_argument('--docker')
parser.add_argument('--dockerExtraArgs')
parser.add_argument('--corba', action="store_true", default=False)
parser.add_argument('--win', action="store_true", help="Windows mode", default=False)
parser.add_argument('--msysEnvironment', help="MSYS2 Environment (ucrt64|mingw64)", default='ucrt64')

args = parser.parse_args()
config = args.config
ompython_omhome = args.ompython_omhome
libraries = args.libraries.replace("\\","/")
docker = args.docker if args.docker else None
dockerExtraArgs = args.dockerExtraArgs.split(" ") if args.dockerExtraArgs else []
corbaStyle = args.corba
isWin = args.win
msysEnvironment = args.msysEnvironment

try:
  os.mkdir("files")
except OSError:
  pass

class TimeoutError(Exception):
  pass

def writeResult():
  with open(statFile, 'w') as fp:
    json.dump(execstat, fp)
    fp.flush()
    os.fsync(fp.fileno())

def writeResultAndExit(exitStatus):
  writeResult()
  sys.exit(exitStatus)

def sendExpressionTimeout(omc, cmd, timeout):
  with open(errFile, 'a+') as fp:
    fp.write(cmd + "\n")
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
    with open(errFile, 'a+') as fp:
      fp.write("Thread is still alive.\n")
      if omc._omc_process.poll() is not None:
        fp.write("OMC died, but the thread is still running? This will end badly. The log-file of omc:\n")
        with open(os.path.normpath(omc._omc_log_file.name)) as omcLog:
          for line in omcLog:
            fp.write(line)
        print("OMC died, but the thread is still running? This will end badly.\n")
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
      with open(errFile, 'a+') as fp:
        fp.write("Aborted the command.\n")
      writeResultAndExit(0)
    if res[1] is None:
      res[1] = ""
  if res[1] is not None:
    raise TimeoutError(res[1])
  return res[0]

def checkOutputTimeout(cmd, timeout, conf=None):
  with open(errFile, 'a+') as fp:
    fp.write(cmd + "\n")
  def target(res):
    try:
      env = os.environ.copy()
      # add the environmentSimulation to the environment
      if conf:
        for e in conf["environmentSimulation"]:
          env[e[0]] = e[1]
      res[0] = subprocess.check_output(cmd, shell=True, stderr=subprocess.STDOUT, env = env).decode().strip()
    except subprocess.CalledProcessError as e:
      outputStr = e.output.decode("utf-8","backslashreplace")
      res[1] = cmd + " " + outputStr
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

try:
  shutil.rmtree(conf["fileName"])
except OSError:
  pass
os.mkdir(conf["fileName"])
os.chdir(conf["fileName"])

dockerExtraArgs = dockerExtraArgs + ["-w", conf["fileName"]]

errFile=os.path.normpath("../files/%s.err" % conf["fileName"])
simFile=os.path.normpath("../files/%s.sim" % conf["fileName"])
statFile=os.path.normpath("../files/%s.stat.json" % conf["fileName"])
try:
  os.unlink(errFile)
except OSError:
  pass
try:
  os.unlink(simFile)
except OSError:
  pass

with open(errFile, 'a+') as fp:
  fp.write("Running: %s\n" % " ".join(sys.argv))

if conf["simCodeTarget"] not in ["Cpp","C"]:
  with open(errFile, 'a+') as fp:
    fp.write("Unknown simCodeTarget in %s" % conf["simCodeTarget"])
  writeResultAndExit(1)
if conf["simCodeTarget"]=="Cpp" and not conf["haveCppRuntime"]:
  with open(errFile, 'a+') as fp:
    fp.write("C++ runtime not supported in this installation (HelloWorld failed)")
  writeResultAndExit(0)
if conf.get("fmi"):
  if conf["simCodeTarget"]=="Cpp" and not conf["haveFMICpp"]:
    with open(errFile, 'a+') as fp:
      fp.write("C++ FMI runtime not supported in this installation (HelloWorld failed or did not respect fileNamePrefix)")
    writeResultAndExit(0)
  elif conf["simCodeTarget"]=="C" and not conf["haveFMI"]:
    with open(errFile, 'a+') as fp:
      fp.write("C FMI runtime not supported in this installation (HelloWorld failed or did not respect fileNamePrefix)")
    writeResultAndExit(0)

omhome = conf["omhome"]
os.environ["OPENMODELICAHOME"] = omhome

def createOmcSession():
  return OMCSession(docker=docker, dockerExtraArgs=dockerExtraArgs, timeout=5) if corbaStyle else OMCSessionZMQ(docker=docker, dockerExtraArgs=dockerExtraArgs, timeout=5)
def createOmcSessionNew():
  if ompython_omhome != "":
    os.environ["OPENMODELICAHOME"] = ompython_omhome
    return OMCSessionZMQ()
  else:
    return createOmcSession()
omc = createOmcSession()
omc_new = createOmcSessionNew()

cmd = 'setCommandLineOptions("%s")' % conf["single_thread_cmd"]
if not omc.sendExpression(cmd):
  raise Exception('Could not send %s' % cmd)

try:
  os.unlink(os.path.normpath("%s.tmpfiles" % conf["fileName"]))
except:
  pass
#cmd = 'setCommandLineOptions("--running-testsuite=%s.tmpfiles")' % conf["fileName"]
runningTestsuiteFiles = False
#if omc.sendExpression(cmd):
#  runningTestsuiteFiles = True

# Hide errors for old-school running-testsuite flags...
omc.sendExpression("getErrorString()", parsed = False)

outputFormat="mat"
referenceVars=[]
referenceFile = conf.get("referenceFile") or ""
if referenceFile != "":
  try:
    compSignals = os.path.normpath(os.path.join(os.path.dirname(referenceFile),"comparisonSignals.txt"))
    if os.path.exists(compSignals):
      referenceVars=[s.strip() for s in open(compSignals).readlines() if (s.strip() != "")] # s.strip().lower() != "time" and ??? I guess we should check time variable...
      print(referenceVars)
    else:
      referenceVars=omc_new.sendExpression('readSimulationResultVars("%s", readParameters=true, openmodelicaStyle=true)' % referenceFile)
    variableFilter="|".join([v.replace("[",".").replace("]",".").replace("(",".").replace(")",".").replace('"',".") for v in referenceVars])
    emit_protected="-emit_protected"
  except:
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
  omc.sendExpression(str(cmd), parsed = False)

if conf.get("optlevel"):
  cflags = omc.sendExpression("getCFlags()")
  cflags = cflags.replace("${MODELICAUSERCFLAGS}","").replace("-O0","").replace("-O1","").replace("-O2","").replace("-O3","").replace("-march=native","").strip()
  cflags += " " + conf["optlevel"]
  omc.sendExpression(str("setCFlags(\"%s\")" % cflags), parsed = False)

omc.sendExpression('setModelicaPath("%s")' % libraries, parsed = False)

if conf.get("ulimitMemory"):
  # Use at most 80% of the vmem for the GC heap; some memory will be used for other purposes than the GC itself
  # Note: Only works on 1.13+ OpenModelica; we still need to ulimit the process for safety
  omc.sendExpression(str("GC_set_max_heap_size(%d);" % (int(conf["ulimitMemory"]*1024*0.8))), parsed = False)

def loadModels(omc, conf):
  for f in conf["loadFiles"]:
    if not sendExpressionTimeout(omc, 'loadFile("%s", uses=false)' % f, conf["ulimitLoadModel"]):
      with open(errFile, 'a+') as fp:
        fp.write(omc.sendExpression('OpenModelica.Scripting.getErrorString()'))
      writeResultAndExit(0)
  loadedFiles = sorted(omc.sendExpression("{getSourceFile(cl) for cl in getClassNames()}"))
  if sorted(conf["loadFiles"]) != loadedFiles:
    print("Loaded the wrong files. Expected:\n%s\nActual:\n%s" % ("\n".join(sorted(conf["loadFiles"])), "\n".join(loadedFiles)))
    sys.exit(1)
newOMLoaded = False
def loadLibraryInNewOM():
  global newOMLoaded
  if not newOMLoaded:
    newOMLoaded = True
    # Broken/old getSimulationOptions; use new one (requires parsing again)
    assert(ompython_omhome!="")
    assert(omc_new.sendExpression('setModelicaPath("%s")' % libraries))
    loadModels(omc_new, conf)

start=monotonic()
try:
  loadModels(omc, conf)
except TimeoutError as e:
  execstat["parsing"]=monotonic()-start
  with open(errFile, 'a+') as fp:
    fp.write("Timeout error for cmd: %s\n%s"%(cmd,str(e)))
  writeResultAndExit(0)
execstat["parsing"]=monotonic()-start

try:
  classNames = omc.sendExpression('getClassNames()')
except:
  classNames = []

for cl in classNames:
  try:
    classVersion = omc.sendExpression('getVersion(%s)' % cl)
  except:
    classVersion = "unknown"
  try:
    classSourceFile = omc.sendExpression('getSourceFile(%s)' % cl)
  except:
    classSourceFile = "??? unknown source location"
  with open(errFile, 'a+') as fp:
    fp.write("Using package %s with version %s (%s)\n" % (cl, classVersion, classSourceFile))

def sendExpressionOldOrNew(cmd):
  try:
    return omc.sendExpression(cmd)
  except:
    loadLibraryInNewOM()
    return omc_new.sendExpression(cmd)

annotationSimFlags=""
(startTime,stopTime,tolerance,numberOfIntervals,stepSize)=sendExpressionOldOrNew('getSimulationOptions(%s,defaultTolerance=%s,defaultNumberOfIntervals=2500)' % (conf["modelName"],conf["default_tolerance"]))
if conf["simCodeTarget"]=="C" and sendExpressionOldOrNew('classAnnotationExists(%s, __OpenModelica_simulationFlags)' % conf["modelName"]):
  for flag in sendExpressionOldOrNew('getAnnotationNamedModifiers(%s,"__OpenModelica_simulationFlags")' % conf["modelName"]):
    if flag=="The searched annotation name not found":
      # Old, stupid API
      continue
    val=sendExpressionOldOrNew('getAnnotationModifierValue(%s,"__OpenModelica_simulationFlags","%s")' % (conf["modelName"],flag))
    flagVal=" -noemit -%s=%s" % (flag,val)
    if shared.simulationAcceptsFlag(flagVal, checkOutput=False, cwd="..", isWin=isWin):
      annotationSimFlags+=" -%s=%s" % (flag,val)
    else:
      with open(errFile, 'a+') as fp:
        fp.write("Ignoring simflag %s since it seems broken on HelloWorld\n" % flagVal)

# TODO: Detect and handle the case where RT_CLOCK is not available in OMC
total_before = omc.sendExpression("OpenModelica.Scripting.Internal.Time.timerTock(OpenModelica.Scripting.Internal.Time.RT_CLOCK_SIMULATE_TOTAL)")
start=monotonic()
if conf.get("fmi"):
  cmd='"" <> buildModelFMU(%s,fileNamePrefix="%s",fmuType="%s",version="%s",platforms={"static"})' % (conf["modelName"],conf["fileName"].replace(".","_"),conf["fmuType"],conf["fmi"])
else:
  cmd='translateModel(%s,tolerance=%g,outputFormat="%s",numberOfIntervals=%d,variableFilter="%s",fileNamePrefix="%s")' % (conf["modelName"],tolerance,outputFormat,2*numberOfIntervals,variableFilter,conf["fileName"])
with open(errFile, 'a+') as fp:
  fp.write("Running command: %s\n"%(cmd))
try:
  res=sendExpressionTimeout(omc, cmd, conf["ulimitOmc"])
except TimeoutError as e:
  execstat["frontend"]=monotonic()-start

  with open(errFile, 'a+') as fp:
    fp.write("Timeout error for cmd: %s\n%s"%(cmd,str(e)))
    try:
      name = os.path.normpath(omc._omc_log_file.name)
      del omc
      with open(name,"r") as fp2:
        fp.write("\n\nOMC output: %s" % fp2.read().decode().strip())
    except:
      pass

  writeResultAndExit(0)

# See which translateModel phases completed

execTimeTranslateModel=monotonic()-start
err=omc.sendExpression("OpenModelica.Scripting.getErrorString()")
total    = omc.sendExpression("OpenModelica.Scripting.Internal.Time.timerTock(OpenModelica.Scripting.Internal.Time.RT_CLOCK_SIMULATE_TOTAL)")-total_before
buildmodel= omc.sendExpression("OpenModelica.Scripting.Internal.Time.timerTock(OpenModelica.Scripting.Internal.Time.RT_CLOCK_BUILD_MODEL)")
templates= omc.sendExpression("OpenModelica.Scripting.Internal.Time.timerTock(OpenModelica.Scripting.Internal.Time.RT_CLOCK_TEMPLATES)")
simcode  = omc.sendExpression("OpenModelica.Scripting.Internal.Time.timerTock(OpenModelica.Scripting.Internal.Time.RT_CLOCK_SIMCODE)")
backend  = omc.sendExpression("OpenModelica.Scripting.Internal.Time.timerTock(OpenModelica.Scripting.Internal.Time.RT_CLOCK_BACKEND)")
frontend = omc.sendExpression("OpenModelica.Scripting.Internal.Time.timerTock(OpenModelica.Scripting.Internal.Time.RT_CLOCK_FRONTEND)")

writeResult()
try:
  omc.sendExpression("quit()")
except:
  pass
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
        execstat["templates"]=templates-max(buildmodel, 0.0)
        if res:
          execstat["phase"]=4
        else:
          execstat["phase"]=3
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

with open(errFile, 'a+') as fp:
  fp.write(err)

if execstat["phase"] < 4:
  writeResultAndExit(0)

start=monotonic()
try:
  if conf.get("fmi"):
    if res:
      fmuExpectedLocation = "%s.fmu" % conf["fileName"].replace(".","_")
      execstat["build"] = max(0.0, buildmodel) # Older versions didn't separate translate and build times
      if not os.path.exists(os.path.normpath(fmuExpectedLocation)):
        err += "\nFMU was not generated in the expected location: %s" % fmuExpectedLocation
        execstat["phase"]=4
        writeResultAndExit(0)
      execstat["phase"] = 5
  else:
    if isWin:
      res = checkOutputTimeout("\"%s\\share\\omc\\scripts\\Compile.bat\" %s gcc %s parallel dynamic 24 0" % (conf["omhome"], conf["fileName"], msysEnvironment), conf["ulimitOmc"], conf)
    else:
      res = checkOutputTimeout("make -j1 -f %s.makefile" % conf["fileName"], conf["ulimitOmc"], conf)

    execstat["build"] = monotonic()-start
    execstat["phase"] = 5
except TimeoutError as e:
  execstat["build"] = monotonic()-start
  with open(errFile, 'a+') as fp:
    fp.write(str(e))
  writeResultAndExit(0)

writeResult()
# Do the simulation

# FMPy generates csv, OMSimulator generates mat (outputFormat)
fmisimulator = conf.get("fmisimulator")
resFile = "%s_res.%s" % (conf["fileName"], outputFormat if not shared.isFMPy(fmisimulator) else 'csv')

start=monotonic()
try:
  # TODO: Timeout more reliably...
  if conf.get("fmi"):
    if not conf.get("fmisimulator"):
      with open(simFile,"w") as fp:
        fp.write("OMSimulator not available\n")
      writeResultAndExit(0)
    fmitmpdir = "temp_%s_fmu" % conf["fileName"].replace(".","_")
    with open("%s.tmpfiles" % conf["fileName"], "a+") as fp:
      fp.write("%s\n" % fmitmpdir)
    if shared.isFMPy(fmisimulator):
      fmisimulator = "%s simulate " % fmisimulator
      cmd = "%s --start-time %g --stop-time %g --timeout %g --relative-tolerance %g %s.fmu" % (("--output-file %s" % resFile),startTime,stopTime,conf["ulimitExe"],tolerance,conf["fileName"].replace(".","_"))
    else: # OMSimulator
      cmd = "%s --tempDir=%s --startTime=%g --stopTime=%g --timeout=%g --tolerance=%g %s.fmu" % (("-r=%s" % resFile) if outputFormat != "empty" else "",fmitmpdir,startTime,stopTime,conf["ulimitExe"],tolerance,conf["fileName"].replace(".","_"))
    with open(simFile,"w") as fp:
      fp.write("%s %s\n" % (fmisimulator, cmd))
    res = checkOutputTimeout("(rm -f %s.pipe ; mkfifo %s.pipe ; head -c 1048576 < %s.pipe >> %s & %s %s > %s.pipe 2>&1)" % (conf["fileName"],conf["fileName"],conf["fileName"],simFile,fmisimulator,cmd,conf["fileName"]), 1.05*conf["ulimitExe"], conf)
  else:
    if isWin:
      cmd = (".\\%s.bat %s %s %s" % (conf["fileName"],annotationSimFlags,conf["simFlags"],emit_protected)).strip()
    else:
      cmd = ("./%s %s %s %s" % (conf["fileName"],annotationSimFlags,conf["simFlags"],emit_protected)).strip()

    if conf["simCodeTarget"]=="C":
      cmd = cmd + " -lv LOG_STATS"
    with open(simFile,"w") as fp:
      fp.write("Environment - simulationEnvironment:\n")
      for e in conf["environmentSimulation"]:
        fp.write("%s = %s\n" % (e[0], e[1]))
      fp.write("startTime=%g\nstopTime=%g\ntolerance=%g\nnumberOfIntervals=%d\nstepSize=%g\n" % (startTime,stopTime,tolerance,numberOfIntervals,stepSize))
      fp.write("Regular simulation: %s\n" % cmd)
    if isWin:
      res = checkOutputTimeout("%s >> %s" % (cmd,simFile), conf["ulimitExe"], conf)
    else:
      res = checkOutputTimeout("(rm -f %s.pipe ; mkfifo %s.pipe ; head -c 1048576 < %s.pipe >> %s & %s > %s.pipe 2>&1)" % (conf["fileName"],conf["fileName"],conf["fileName"],simFile,cmd,conf["fileName"]), conf["ulimitExe"], conf)
  execstat["sim"] = monotonic()-start
  execstat["phase"] = 6
except TimeoutError as e:
  execstat["sim"] = monotonic()-start
  writeResultAndExit(0)

if referenceFile=="":
  writeResultAndExit(0)
if len(referenceVars)==0:
  execstat["diff"] = {"time":0.0, "vars":[], "numCompared":0}
  execstat["phase"]=7
  writeResultAndExit(0)

# Check the reference file...

prefix = os.path.abspath("../files/%s.diff" % conf["fileName"]).replace('\\','/')


if not os.path.exists(os.path.normpath(resFile)):
  with open(errFile, 'a+') as fp:
    fp.write("TODO: How the !@#!# did the simulation report success but simulation result %s does not exist to compare? outputFormat=%s" % (resFile,outputFormat))
  writeResultAndExit(0)

start=monotonic()
if False and conf["simCodeTarget"] in ["Cpp"]: # This is a work-around for older C++ runtime not supporting variable filters. We don't really need it for master, so let's no use it.
  if not sendExpressionTimeout(omc_new, 'filterSimulationResults("%s", "updated%s", vars={%s}, removeDescription=false, hintReadAllVars=false)' % (resFile, resFile, ", ".join(['"%s"' % s for s in referenceVars])), conf["ulimitOmc"]):
    with open(errFile, 'a+') as fp:
      fp.write("Failed to filter simulation results. Took time: %.2f\n" % (monotonic()-start))
    writeResultAndExit(0)
  os.remove(resFile)
  os.rename("updated" + resFile, resFile)
  with open(errFile, 'a+') as fp:
    fp.write("Filtered simulation results in time: %.2f\n" % (monotonic()-start))
start=monotonic()
try:
  (referenceOK,diffVars) = sendExpressionTimeout(omc_new, 'diffSimulationResults("%s","%s","%s",relTol=%g,relTolDiffMinMax=%g,rangeDelta=%g)' %
                             (resFile, referenceFile, prefix, conf["reference_reltol"],conf["reference_reltolDiffMinMax"], conf["reference_rangeDelta"]), conf["ulimitOmc"])
except TimeoutError as e:
  with open(errFile, 'a+') as fp:
    fp.write("Timeout error for diffSimulationResults")
  writeResultAndExit(0)

execstat["diff"] = {"time":monotonic()-start, "vars":[], "numCompared":len(referenceVars)}
if len(diffVars)==0 and referenceOK:
  execstat["phase"]=7
  with open(errFile, 'a+') as fp:
    fp.write("Reference file matches\n")
else:
  with open(errFile, 'a+') as fp:
    fp.write(omc_new.sendExpression('OpenModelica.Scripting.getErrorString()', parsed = False))
    fp.write("\nVariables in the reference:" )
    fp.write(",".join(referenceVars)+"\n")
    resVars=omc_new.sendExpression('readSimulationResultVars("%s", readParameters=true, openmodelicaStyle=true)' % resFile)
    fp.write("\nVariables in the result:" )
    fp.write(",".join(resVars)+"\n")
  diffFiles = [prefix + "." + var for var in diffVars]
  execstat["diff"]["vars"]=diffVars

  # Create a file containing only the calibrated variables, for easy display
  lstfiles = "\n".join(['<li>%s <a href="%s.html">(javascript)</a> <a href="%s.csv">(csv)</a></li>' % (str.split(str(f),".diff.",1)[1],str(os.path.basename(f)),str(os.path.basename(f))) for f in diffFiles])
  with open(prefix+".html", 'w') as fp:
    fp.write('<html lang="en"><body><h1>%s differences from the reference file</h1><p>startTime: %g</p><p>stopTime: %g</p><p>Simulated using tolerance: %g</p><ul>%s</ul></body></html>' % (conf["modelName"], startTime, stopTime, tolerance, lstfiles))
  for var in diffVars:
    if "/" in var:
      continue # Quoted identifier, or possibly an error message... Either way, avoid crapping out below
    with open(prefix+"."+var+".html", 'w') as fp:
      fp.write("""<html lang="en">
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
