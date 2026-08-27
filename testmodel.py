#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse, os, re, sys, signal, threading, psutil, subprocess, shutil
from asyncio.subprocess import STDOUT
import simplejson as json
from monotonic import monotonic
from OMPython import FindBestOMCSession, OMCSession, OMCSessionZMQ
import shared, glob

parser = argparse.ArgumentParser(description='OpenModelica library testing tool helper (single model)')
parser.add_argument('config')
parser.add_argument('--ompython_omhome', default='')
parser.add_argument('--libraries')
parser.add_argument('--docker')
parser.add_argument('--dockerExtraArgs')
parser.add_argument('--corba', action="store_true", default=False)
parser.add_argument('--win', action="store_true", help="Windows mode", default=False)
parser.add_argument('--msysEnvironment', help="MSYS2 Environment (ucrt64|mingw64)", default='ucrt64')
parser.add_argument('--addmsl', action="store_true", help="add the MSL path to the OPENMODELICAPATH if the MSL is not detected in the libraries path", default=False)

args = parser.parse_args()
config = args.config
ompython_omhome = args.ompython_omhome
libraries = args.libraries.replace("\\","/")
docker = args.docker if args.docker else None
dockerExtraArgs = args.dockerExtraArgs.split(" ") if args.dockerExtraArgs else []
corbaStyle = args.corba
isWin = args.win
msysEnvironment = args.msysEnvironment
addmsl = args.addmsl

# our OMPython sessions
omc = None
omc_new = None

# add openmodelica libraries path if the Modelica libraries are not found in the libraries path
MSLpath = ''
if addmsl and len(glob.glob('Modelica *', root_dir=libraries)) == 0:
  if isWin:
    MSLpath = ';' + os.path.normpath(os.path.join(os.environ.get('APPDATA'), '.openmodelica', 'libraries')).replace('\\','/')
  else:
    MSLpath = ':' + os.path.normpath(os.path.join(os.environ.get('HOME'), '.openmodelica', 'libraries'))

try:
  os.mkdir("files")
except OSError:
  pass

class TimeoutError(Exception):
  pass

runningPhase = None
"""What is running now, as (key of execstat, when it started).

A command the watchdog has to kill never returns to its caller -
sendExpressionTimeout ends the process itself - so the caller's own timeout
handler does not run and the phase reports no time at all. Recording it here
instead covers every way out, because they all write the results first.
"""

def phaseStarts(key):
  global runningPhase
  runningPhase = (key, monotonic())

def phaseEnded():
  global runningPhase
  runningPhase = None

def writeResult():
  if runningPhase is not None:
    (key, started) = runningPhase
    # Only if the phase did not get to report its own time.
    if not execstat.get(key):
      execstat[key] = monotonic() - started
  with open(statFile, 'w') as fp:
    json.dump(execstat, fp)
    fp.flush()
    os.fsync(fp.fileno())

startJob=monotonic()

def quit_omc(omc):
  if omc is None:
    return omc
  try:
    omc.sendExpression("quit()")
  except:
    pass
  try:
    del omc
  except:
    pass
  omc = None
  return omc

def writeResultAndExit(exitStatus, useOsExit=False, omc=None, omc_new=None):
  writeResult()
  print("Calling exit ...")
  with open(errFile, 'a+') as fp:
    if useOsExit:
      msg = "[Calling os._exit(%s), Time elapsed: %s]\n"
    else:
      msg = "[Calling sys.exit(%s), Time elapsed: %s]\n"
    fp.write(msg % (exitStatus, monotonic()-startJob))
    fp.flush()
  sys.stdout.flush()
  omc = quit_omc(omc)
  omc_new = quit_omc(omc_new)
  if useOsExit:
    os._exit(exitStatus)
  else:
    sys.exit(exitStatus)

def sendExpressionTimeout(omc, cmd, timeout):
  with open(errFile, 'a+') as fp:
    fp.write("%s [Timeout %s]\n" % (cmd, timeout))
  def target(res):
    try:
      ignore = omc.sendExpression("alarm(%s)" % timeout)
      res[0] = omc.sendExpression(cmd)
      with open(errFile, 'a+') as fp:
        fp.write(omc.sendExpression('OpenModelica.Scripting.getErrorString()', parsed = False))
      elapsed = omc.sendExpression("alarm(0)")
      with open(errFile, 'a+') as fp:
        fp.write("[Timeout remaining time %s]\n" % elapsed)
    except Exception as e:
      res[1] = cmd + " " + str(e)

  res=[None,None]
  thread = threading.Thread(target=target, args=(res,))
  thread.start()
  # Poll instead of a single join: if omc dies (crash, ulimit, ...) the thread is
  # stuck in a ZMQ receive that never returns, so waiting out the timeout and then
  # exiting normally would hang forever on that non-daemon thread
  deadline = monotonic() + timeout
  while thread.is_alive() and monotonic() < deadline:
    thread.join(1)
    status = omc._omc_process.poll()
    if thread.is_alive() and status is not None:
      with open(errFile, 'a+') as fp:
        fp.write("OMC exited with status %s while running: %s\n" % (status, cmd))
        try:
          with open(os.path.normpath(omc._omc_log_file.name)) as omcLog:
            for line in omcLog:
              fp.write(line)
        except IOError:
          pass
      writeResultAndExit(0, True, omc, omc_new)

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
        with open(errFile, 'a+') as fp:
          fp.write("Could not SIGINT process: %s.\n" % process.pid)
        pass
    thread.join(2)
    if thread.is_alive():
      for process in psutil.Process().children(recursive=True):
        try:
          os.kill(process.pid, signal.SIGKILL)
        except OSError:
          with open(errFile, 'a+') as fp:
            fp.write("Could not SIGKILL process: %s.\n" % process.pid)
          pass
      with open(errFile, 'a+') as fp:
        fp.write("Aborted the command.\n")
      writeResultAndExit(0, True, omc, omc_new)
    if res[1] is None:
      res[1] = ""
  if res[1] is not None:
    raise TimeoutError(res[1])
  return res[0]

def checkOutputTimeout(cmd, timeout, conf=None):
  with open(errFile, 'a+') as fp:
    fp.write("%s [Timeout %s]\n" % (cmd, timeout))
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
        with open(errFile, 'a+') as fp:
          fp.write("Could not SIGINT process: %s.\n" % process.pid)
        pass
    thread.join(2)
    if thread.is_alive():
      for process in psutil.Process().children(recursive=True):
        try:
          os.kill(process.pid, signal.SIGKILL)
        except OSError:
          with open(errFile, 'a+') as fp:
            fp.write("Could not SIGKILL process: %s.\n" % process.pid)
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
  "simwall":None, # Wall clock; sim is what the tool says it spent
  "simcold":None,
  "diff":None,
  "phase":0,
  # One entry per FMI simulator beyond the first, which reports itself in the
  # keys above; see configs/fmi-simulators.json.
  "simulators":{}
}
simulators = execstat["simulators"]

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

if conf["simCodeTarget"] not in ["Cpp","C","wasm-jit"]:
  with open(errFile, 'a+') as fp:
    fp.write("Unknown simCodeTarget in %s" % conf["simCodeTarget"])
  writeResultAndExit(1)
# wasm-jit builds no makefile and no executable; the model is JIT-compiled inside
# the omc that translated it and simulated there via simulate(resimulateExecutable=)
isWasmJit = conf["simCodeTarget"]=="wasm-jit"
# --nobuildmodel: one simulate() instead of translateModel()+resimulate, so omc
# reports the build/simulation split itself
# --wasmjitrunner: export the model once as a wasm artifact and simulate that one
# artifact several ways (its own simulation runtime, FMI 3.0 ME, FMI 3.0 CS), so
# the model is translated and compiled once however many runs there are
useArtifact = isWasmJit and bool(conf.get("wasmjitrunners")) and not conf.get("fmi")
useSimulate = isWasmJit and conf.get("noBuildModel") and not conf.get("fmi") and not useArtifact
# --coldhot: simulate again in the same session, where the module is already
# compiled, and report that run instead
useColdHot = isWasmJit and conf.get("coldHot") and not conf.get("fmi") and not useArtifact
if isWasmJit and conf.get("fmi"):
  with open(errFile, 'a+') as fp:
    fp.write("FMI export is not supported for simCodeTarget=wasm-jit")
  writeResultAndExit(0)
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

cmd = 'setCommandLineOptions("%s")' % conf["omc_thread_cmd"]
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
numberOfIntervalsInReference = 0
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
    # get the number of intervals from the file
    numberOfIntervalsInReference = omc_new.sendExpression('readSimulationResultSize("%s")' % referenceFile)
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

omc.sendExpression('setModelicaPath("%s")' % (libraries+MSLpath,), parsed = False)

if conf.get("ulimitMemory"):
  # Use at most 80% of the vmem for the GC heap; some memory will be used for other purposes than the GC itself
  # Note: Only works on 1.13+ OpenModelica; we still need to ulimit the process for safety
  omc.sendExpression(str("GC_set_max_heap_size(%d);" % (int(conf["ulimitMemory"]*1024*0.8))), parsed = False)

def loadModels(omc, conf):
  for f in conf["loadFiles"]:
    if not sendExpressionTimeout(omc, 'loadFile("%s", uses=false)' % f, conf["ulimitLoadModel"]):
      writeResultAndExit(0, False, omc, omc_new)
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
    assert(omc_new.sendExpression('setModelicaPath("%s")' % (libraries+MSLpath,)))
    loadModels(omc_new, conf)

start=monotonic()
try:
  loadModels(omc, conf)
except TimeoutError as e:
  execstat["parsing"]=monotonic()-start
  with open(errFile, 'a+') as fp:
    fp.write("Timeout error for cmd: %s\n%s"%(cmd,str(e)))
  writeResultAndExit(0, True, omc, omc_new)
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

haveFlagCheckModel=False
def wasmJitAcceptsFlag(flagVal):
  # There is no HelloWorld executable to probe: the wasm-jit runtime lives in
  # omc, so ask it directly whether a trivial model still simulates.
  global haveFlagCheckModel
  if not haveFlagCheckModel:
    sendExpressionOldOrNew('loadString("model OMLibTestFlagCheck Real x(start = 1, fixed = true); equation der(x) = -x; end OMLibTestFlagCheck;")')
    haveFlagCheckModel=True
  return bool((sendExpressionOldOrNew('simulate(OMLibTestFlagCheck,simflags="%s")' % flagVal) or {}).get("resultFile"))

annotationSimFlags=""
cmd = 'getSimulationOptions(%s,defaultTolerance=%s,defaultNumberOfIntervals=%s)' % (conf["modelName"], conf["defaultTolerance"], max(conf["defaultNumberOfIntervals"], numberOfIntervalsInReference))
try:
  (startTime,stopTime,tolerance,numberOfIntervals,stepSize)=sendExpressionOldOrNew(cmd)
except:
  # omc answers nothing when the call fails, and nothing else reads the buffer.
  raise Exception("%s failed:\n%s" % (cmd, omc.sendExpression("getErrorString()", parsed = False)))
if conf["simCodeTarget"] in ("C","wasm-jit") and sendExpressionOldOrNew('classAnnotationExists(%s, __OpenModelica_simulationFlags)' % conf["modelName"]):
  for flag in sendExpressionOldOrNew('getAnnotationNamedModifiers(%s,"__OpenModelica_simulationFlags")' % conf["modelName"]):
    if flag=="The searched annotation name not found":
      # Old, stupid API
      continue
    val=sendExpressionOldOrNew('getAnnotationModifierValue(%s,"__OpenModelica_simulationFlags","%s")' % (conf["modelName"],flag))
    flagVal=" -noemit -%s=%s" % (flag,val)
    if wasmJitAcceptsFlag("-%s=%s" % (flag,val)) if isWasmJit else shared.simulationAcceptsFlag(flagVal, checkOutput=False, cwd="..", isWin=isWin):
      annotationSimFlags+=" -%s=%s" % (flag,val)
    else:
      with open(errFile, 'a+') as fp:
        fp.write("Ignoring simflag %s since the simulation runtime does not accept it\n" % flagVal)

commandLineOptionsRe = re.compile(r'__OpenModelica_commandLineOptions\s*=\s*\\?"([^"\\]*)')

def modelCommandLineOptions():
  """The flags the model's __OpenModelica_commandLineOptions annotation sets.

  omc applies them itself inside simulate()/buildModelFMU(); the testing needs to
  know about them beforehand to pick how the model can be run at all.
  """
  if not sendExpressionOldOrNew('classAnnotationExists(%s, __OpenModelica_commandLineOptions)' % conf["modelName"]):
    return ""
  opts = []
  for i in range(1, (sendExpressionOldOrNew('getAnnotationCount(%s)' % conf["modelName"]) or 0) + 1):
    text = sendExpressionOldOrNew('getNthAnnotationString(%s, %d)' % (conf["modelName"], i)) or ""
    opts += commandLineOptionsRe.findall(text)
  return " ".join(opts)

# A --daeMode model has no explicit ODE, so it has no FMI Model Exchange
# interface: the export drops ME and the artifact serves Co-Simulation (and its
# own simulation) only. Drop the runners that ask for what is not there.
daeMode = useArtifact and "--daeMode" in (modelCommandLineOptions() + " " + " ".join(str(c) for c in conf["customCommands"]))

def simulateCmd(resimulate):
  simflags = ("%s %s %s -lv LOG_STATS" % (annotationSimFlags,conf["simFlags"],emit_protected)).strip()
  return 'simulate(%s,startTime=%g,stopTime=%g,tolerance=%g,numberOfIntervals=%d,outputFormat="%s",variableFilter="%s",fileNamePrefix="%s",simflags="%s"%s)' % (conf["modelName"],startTime,stopTime,tolerance,numberOfIntervals,outputFormat,variableFilter,conf["fileName"],simflags,(',resimulateExecutable="%s"' % conf["fileName"]) if resimulate else "")

# TODO: Detect and handle the case where RT_CLOCK is not available in OMC
total_before = omc.sendExpression("OpenModelica.Scripting.Internal.Time.timerTock(OpenModelica.Scripting.Internal.Time.RT_CLOCK_SIMULATE_TOTAL)")
start=monotonic()
timeout = conf["ulimitOmc"]
# If the command has to be killed there is no way to tell which phase it was in,
# so its time is charged to what the command itself is: building an FMU to the
# build, simulating to the simulation, translating to the front end - which is
# also the phase such a model is reported as having failed in.
if conf.get("fmi"):
  cmd='"" <> buildModelFMU(%s,fileNamePrefix="%s",fmuType="%s",version="%s",platforms={"static"})' % (conf["modelName"],conf["fileName"].replace(".","_"),conf["fmuType"],conf["fmi"])
  timedPhase = "build"
elif useArtifact:
  # One artifact for every runner, written unzipped: the model kernel alone,
  # which omc links against an adapter it compiled once into its cache. Nothing
  # here is packed, extracted or compiled but the model.
  sendExpressionOldOrNew('setCommandLineOptions("--fmuDirectory=true")')
  cmd='"" <> buildModelFMU(%s,fileNamePrefix="%s",fmuType="me_cs",version="3.0",platforms={"wasm"})' % (conf["modelName"],conf["fileName"].replace(".","_"))
  timedPhase = "build"
elif useSimulate:
  cmd=simulateCmd(resimulate=False)
  timeout = conf["ulimitOmc"] + conf["ulimitExe"]
  timedPhase = "sim"
else:
  cmd='translateModel(%s,tolerance=%g,outputFormat="%s",numberOfIntervals=%d,variableFilter="%s",fileNamePrefix="%s")' % (conf["modelName"],tolerance,outputFormat,numberOfIntervals,variableFilter,conf["fileName"])
  timedPhase = "frontend"
with open(errFile, 'a+') as fp:
  fp.write("Running command: %s\n"%(cmd))
try:
  phaseStarts(timedPhase)
  res=sendExpressionTimeout(omc, cmd, timeout)
  phaseEnded()
except TimeoutError as e:
  execstat[timedPhase]=monotonic()-start

  with open(errFile, 'a+') as fp:
    fp.write("Timeout error for cmd: %s\n%s"%(cmd,str(e)))
    try:
      name = os.path.normpath(omc._omc_log_file.name)
      del omc
      with open(name,"r") as fp2:
        fp.write("\n\nOMC output: %s" % fp2.read().decode().strip())
    except:
      pass

  writeResultAndExit(0, omc, omc_new)

# See which translateModel phases completed

execTimeTranslateModel=monotonic()-start
simres = None
buildFailed = False
if useSimulate:
  simres = res or {}
  # A failed translate/build is only reported in the messages of the record; the
  # translation clocks below say which of the two it was
  buildFailed = (simres.get("messages") or "").startswith("Failed to build model")
  res = True
err        = omc.sendExpression("OpenModelica.Scripting.getErrorString()")
total      = omc.sendExpression("OpenModelica.Scripting.Internal.Time.timerTock(OpenModelica.Scripting.Internal.Time.RT_CLOCK_SIMULATE_TOTAL)")-total_before
buildmodel = omc.sendExpression("OpenModelica.Scripting.Internal.Time.timerTock(OpenModelica.Scripting.Internal.Time.RT_CLOCK_BUILD_MODEL)")
templates  = omc.sendExpression("OpenModelica.Scripting.Internal.Time.timerTock(OpenModelica.Scripting.Internal.Time.RT_CLOCK_TEMPLATES)")
simcode    = omc.sendExpression("OpenModelica.Scripting.Internal.Time.timerTock(OpenModelica.Scripting.Internal.Time.RT_CLOCK_SIMCODE)")
backend    = omc.sendExpression("OpenModelica.Scripting.Internal.Time.timerTock(OpenModelica.Scripting.Internal.Time.RT_CLOCK_BACKEND)")
frontend   = omc.sendExpression("OpenModelica.Scripting.Internal.Time.timerTock(OpenModelica.Scripting.Internal.Time.RT_CLOCK_FRONTEND)")

writeResult()
if not isWasmJit or (useSimulate and not useColdHot):
  # wasm-jit keeps the translated model in this session; it is needed to simulate
  omc = quit_omc(omc)

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
  writeResultAndExit(0, False, omc, omc_new)

start=monotonic()
try:
  if conf.get("fmi") or useArtifact:
    if res:
      fmuExpectedLocation = "%s.fmu" % conf["fileName"].replace(".","_")
      execstat["build"] = max(0.0, buildmodel) # Older versions didn't separate translate and build times
      if not os.path.exists(os.path.normpath(fmuExpectedLocation)):
        err += "\n%s was not generated in the expected location: %s" % ("The wasm artifact" if useArtifact else "FMU", fmuExpectedLocation)
        execstat["phase"]=4
        writeResultAndExit(0, False, omc, omc_new)
      execstat["phase"] = 5
  elif isWasmJit:
    # Nothing to build; simulate() reports the JIT compile as timeCompile, while
    # a resimulate leaves it in the simulation time
    execstat["build"] = simres["timeCompile"] if useSimulate else 0.0
    execstat["phase"] = 5
    if buildFailed:
      with open(errFile, 'a+') as fp:
        fp.write(simres.get("messages") or "")
      writeResultAndExit(0, False, omc, omc_new)
  else:
    if isWin:
      res = checkOutputTimeout("\"%s\\share\\omc\\scripts\\Compile.bat\" %s gcc %s parallel dynamic 24 0" % (conf["omhome"], conf["fileName"], msysEnvironment), conf["ulimitOmc"], conf)
    else:
      res = checkOutputTimeout("make -j%s -f %s.makefile" % (conf["procCCompile"], conf["fileName"]), conf["ulimitOmc"], conf)

    execstat["build"] = monotonic()-start
    execstat["phase"] = 5
except TimeoutError as e:
  execstat["build"] = monotonic()-start
  with open(errFile, 'a+') as fp:
    fp.write(str(e))
  writeResultAndExit(0, True, omc, omc_new)

writeResult()
# Do the simulation

# The FMU is built once and simulated with every tool the job asked for, so
# that testing FMPy no longer means building the same FMU a second time.  The
# tools are described in configs/fmi-simulators.json.
fmisimulator = conf.get("fmisimulator")
fmisimulators = shared.parseFmiSimulators(conf.get("fmisimulators")) if conf.get("fmi") else []
if conf.get("fmi") and not fmisimulators and fmisimulator:
  fmisimulators = shared.parseFmiSimulators([fmisimulator])
wasmjitrunners = shared.parseWasmJitRunners(conf.get("wasmjitrunners")) if useArtifact else []
if daeMode:
  meRunners = [name for (name, flags) in wasmjitrunners if ":me:" in flags or flags.endswith(":me")]
  if meRunners:
    with open(errFile, 'a+') as fp:
      fp.write("The model asks for --daeMode, which has no FMI Model Exchange interface: "
               "not running %s\n" % ", ".join(meRunners))
    wasmjitrunners = [r for r in wasmjitrunners if r[0] not in meRunners]
# One build, several runs: an FMU simulated by several tools and a wasm artifact
# run several ways fan out the same way, so they share the naming below.
runners = fmisimulators or wasmjitrunners

def resultFile(name=None):
  """Where a simulator writes its results.

  Every tool writes what its entry says, and they only need to be told apart
  when more than one of them runs on the same FMU.
  """
  if not name:
    return "%s_res.%s" % (conf["fileName"], outputFormat)
  # A wasm-jit runner is omc, which writes the format the model was translated for.
  extension = shared.fmiSimulator(name)["resultExtension"] if fmisimulators else outputFormat
  if len(runners) < 2:
    return "%s_res.%s" % (conf["fileName"], extension)
  return "%s_%s_res.%s" % (conf["fileName"], name, extension)

def artifactPrefix(name=None):
  """The files a simulator's results are written to, under files/."""
  if not name or len(runners) < 2:
    return os.path.abspath("../files/%s" % conf["fileName"]).replace('\\','/')
  return os.path.abspath("../files/%s_%s" % (conf["fileName"], name)).replace('\\','/')

resFile = resultFile(runners[0][0]) if runners else resultFile()

def simulateFmu(name, command, resFile, simFile):
  """Run the FMU with one simulator, writing what it says to simFile."""
  # Only tell the runs apart when more than one of them shares the directory.
  suffix = "_%s" % name if len(fmisimulators) > 1 else ""
  fmitmpdir = "temp_%s%s_fmu" % (conf["fileName"].replace(".","_"), suffix)
  with open("%s.tmpfiles" % conf["fileName"], "a+") as fp:
    fp.write("%s\n" % fmitmpdir)
  cmd = shared.fmiSimulatorCommand(name, command,
                                   fmu="%s.fmu" % conf["fileName"].replace(".","_"),
                                   result=resFile,
                                   requestedResult=resFile if outputFormat != "empty" else "",
                                   tempDir=fmitmpdir, startTime=startTime, stopTime=stopTime,
                                   tolerance=tolerance, timeout=conf["ulimitExe"],
                                   stepSize=stepSize)
  with open(simFile,"w") as fp:
    fp.write("%s\n" % cmd)
  pipe = "%s%s" % (conf["fileName"], suffix)
  return checkOutputTimeout("(rm -f %s.pipe ; mkfifo %s.pipe ; head -c 1048576 < %s.pipe >> %s & %s > %s.pipe 2>&1)"
                            % (pipe,pipe,pipe,simFile,cmd,pipe), 1.05*conf["ulimitExe"], conf)

def artifactCmd(runnerFlags, resFile):
  """The simulate() that runs the exported artifact one way.

  Nothing is translated: `resimulateExecutable` points at the artifact, `-s
  fmi3:...` picks which of its interfaces runs, and the experiment comes from
  the flags rather than from what the export baked in.
  """
  # An empty output format is a run with nothing to compare against, so it is
  # asked for no result file at all rather than one nobody reads.
  resultArgument = "-noemit" if outputFormat == "empty" else "-r=%s" % resFile
  simflags = " ".join(x for x in (annotationSimFlags, conf["simFlags"], emit_protected,
                                  "-lv LOG_STATS",
                                  "-startTime=%g -stopTime=%g -tolerance=%g -stepSize=%g" % (startTime,stopTime,tolerance,stepSize),
                                  resultArgument, runnerFlags) if x.strip())
  return 'simulate(%s,startTime=%g,stopTime=%g,tolerance=%g,numberOfIntervals=%d,outputFormat="%s",variableFilter="%s",fileNamePrefix="%s",simflags="%s",resimulateExecutable="%s.fmu")' % (
      conf["modelName"],startTime,stopTime,tolerance,numberOfIntervals,outputFormat,variableFilter,conf["fileName"],simflags,conf["fileName"].replace(".","_"))

def simulateArtifact(name, runnerFlags, resFile, simFile):
  """Run the artifact one way, writing what omc says to simFile.

  Returns what simulate() answered; an empty resultFile is a failed run.
  """
  cmd = artifactCmd(runnerFlags, resFile)
  # The export is a directory, and a zipped one unpacks itself beside the .fmu on
  # the first run; the cleanup removes what this file names.
  with open("%s.tmpfiles" % conf["fileName"], "a+") as fp:
    fp.write("%s.fmu\n%s_artifact\n" % (conf["fileName"].replace(".","_"), conf["fileName"].replace(".","_")))
  with open(simFile, "w") as fp:
    fp.write("startTime=%g\nstopTime=%g\ntolerance=%g\nnumberOfIntervals=%d\nstepSize=%g\n" % (startTime,stopTime,tolerance,numberOfIntervals,stepSize))
    fp.write("wasm artifact (%s: %s): %s\n" % (name, shared.wasmJitRunner(name).get("description") or "", cmd))
  res = sendExpressionTimeout(omc, cmd, conf["ulimitExe"]) or {}
  with open(simFile, "a+") as fp:
    fp.write(res.get("messages") or "")
  return res

def simElapsed():
  # omc's own time: the wall clock here covers the wrong run for these flags
  if useSimulate or useColdHot or useArtifact:
    return (simres or {}).get("timeSimulation") or 0.0
  return monotonic()-start

start=monotonic()
# Set when the first FMI simulator fails and there are others waiting for the
# same FMU, so that its result file is not compared against the reference.
firstSimulatorFailed = False
try:
  # TODO: Timeout more reliably...
  if conf.get("fmi"):
    if not fmisimulators:
      with open(simFile,"w") as fp:
        fp.write("No FMI simulator available\n")
      writeResultAndExit(0, False, omc, omc_new)
    (name, command) = fmisimulators[0]
    res = simulateFmu(name, command, resFile, simFile)
  elif useArtifact:
    (name, runnerFlags) = wasmjitrunners[0]
    simres = simulateArtifact(name, runnerFlags, resFile, simFile)
    if not simres.get("resultFile"):
      # The same shape a failing FMI simulator takes: the handler below decides
      # whether the other runners of this artifact still get their turn.
      raise TimeoutError("%s failed to simulate the wasm artifact" % name)
  elif isWasmJit:
    if not useSimulate:
      cmd = simulateCmd(resimulate=True)
    with open(simFile,"w") as fp:
      fp.write("startTime=%g\nstopTime=%g\ntolerance=%g\nnumberOfIntervals=%d\nstepSize=%g\n" % (startTime,stopTime,tolerance,numberOfIntervals,stepSize))
      fp.write("wasm-jit simulation: %s\n" % cmd)
    if not useSimulate:
      simres = sendExpressionTimeout(omc, cmd, conf["ulimitExe"]) or {}
    with open(simFile,"a+") as fp:
      fp.write(simres.get("messages") or "")
    if not simres.get("resultFile"):
      execstat["sim"] = simElapsed()
      writeResultAndExit(0, False, omc, omc_new)
    if useColdHot:
      execstat["simcold"] = simElapsed()
      cmd = simulateCmd(resimulate=True)
      with open(simFile,"a+") as fp:
        fp.write("wasm-jit hot simulation: %s\n" % cmd)
      hotres = sendExpressionTimeout(omc, cmd, conf["ulimitExe"]) or {}
      with open(simFile,"a+") as fp:
        fp.write(hotres.get("messages") or "")
      if hotres.get("resultFile"):
        simres = hotres
      else:
        with open(errFile, 'a+') as fp:
          fp.write("The hot simulation failed; keeping the cold time\n")
  else:
    if isWin:
      cmd = (".\\%s.bat %s %s %s" % (conf["fileName"],annotationSimFlags,conf["simFlags"],emit_protected)).strip()
    else:
      cmd = ("./%s %s %s %s" % (conf["fileName"],annotationSimFlags,conf["simFlags"],emit_protected)).strip()

    if conf["simCodeTarget"]=="C":
      cmd = cmd + " -lv LOG_STATS"
    executable = os.path.normpath("%s.bat" % conf["fileName"] if isWin else conf["fileName"])
    if not os.path.exists(executable):
      with open(errFile, 'a+') as fp:
        fp.write("The simulation executable %s does not exist\n" % executable)
      execstat["sim"] = monotonic()-start
      writeResultAndExit(0, False, omc, omc_new)
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
  execstat["sim"] = simElapsed()
  execstat["simwall"] = monotonic()-start
  execstat["phase"] = 6
except TimeoutError as e:
  execstat["sim"] = monotonic()-start
  execstat["simwall"] = execstat["sim"]
  # checkOutputTimeout raises TimeoutError for a command that fails as well as
  # for one that runs out of time, so this covers both.
  if len(runners) > 1:
    # The FMU is built and the other simulators are about to run it. What the
    # first one did says nothing about them, so record the failure and let them
    # have their turn. Ending the model here would write them all down as having
    # failed at this phase without ever being started, which is what the loop
    # below already avoids for a failure in any simulator but the first.
    firstSimulatorFailed = True
    with open(errFile, 'a+') as fp:
      fp.write("%s failed or timed out simulating it; the others still get to run it\n"
               % runners[0][0])
  else:
    writeResultAndExit(0, True, omc, omc_new)

def verifyAgainstReference(resFile, prefix, stat):
  """Compare one simulation result against the reference file.

  Fills stat["diff"] and stat["phase"] exactly as the single simulator code
  did, but returns instead of ending the run, so that the other simulators
  of the same FMU can be verified too.
  """
  if referenceFile=="":
    return
  if len(referenceVars)==0:
    stat["diff"] = {"time":0.0, "vars":[], "numCompared":0}
    stat["phase"]=7
    return


  if not os.path.exists(os.path.normpath(resFile)):
    with open(errFile, 'a+') as fp:
      fp.write("TODO: How the !@#!# did the simulation report success but simulation result %s does not exist to compare? outputFormat=%s" % (resFile,outputFormat))
    return

  start=monotonic()
  if False and conf["simCodeTarget"] in ["Cpp"]: # This is a work-around for older C++ runtime not supporting variable filters. We don't really need it for master, so let's no use it.
    if not sendExpressionTimeout(omc_new, 'filterSimulationResults("%s", "updated%s", vars={%s}, removeDescription=false, hintReadAllVars=false)' % (resFile, resFile, ", ".join(['"%s"' % s for s in referenceVars])), conf["ulimitOmc"]):
      with open(errFile, 'a+') as fp:
        fp.write("Failed to filter simulation results. Took time: %.2f\n" % (monotonic()-start))
      return
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
    return

  stat["diff"] = {"time":monotonic()-start, "vars":[], "numCompared":len(referenceVars)}
  if len(diffVars)==0 and referenceOK:
    stat["phase"]=7
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
    stat["diff"]["vars"]=diffVars

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


# The first simulator's results are the ones every non-FMI code path expects.
# There is nothing to compare when it never produced any.
if not firstSimulatorFailed:
  verifyAgainstReference(resFile, artifactPrefix(runners[0][0] if runners else None) + ".diff", execstat)

# The FMU is built; every other simulator the job asked for is now only a
# simulation and a comparison. A tool that times out or fails takes its own
# results down with it and leaves the others alone - the first one included,
# see the TimeoutError handler above.
for (name, command) in runners[1:]:
  stat = {"sim": None, "simwall": None, "diff": None, "phase": 5}
  simulators[name] = stat
  simFileOther = os.path.abspath("../files/%s_%s.sim" % (conf["fileName"], name)).replace('\\','/')
  other = resultFile(name)
  start = monotonic()
  try:
    if useArtifact:
      res = simulateArtifact(name, command, other, simFileOther)
      stat["sim"] = res.get("timeSimulation") or (monotonic()-start)
      stat["simwall"] = monotonic()-start
      if not res.get("resultFile"):
        writeResult()
        continue
    else:
      simulateFmu(name, command, other, simFileOther)
      stat["sim"] = monotonic()-start
      stat["simwall"] = stat["sim"]
    stat["phase"] = 6
    verifyAgainstReference(other, artifactPrefix(name) + ".diff", stat)
  except TimeoutError as e:
    stat["sim"] = monotonic()-start
    stat["simwall"] = stat["sim"]
    with open(errFile, 'a+') as fp:
      fp.write("%s timed out simulating the %s\n" % (name, "artifact" if useArtifact else "FMU"))
  writeResult()

# quit omc_new: every verification needed it
omc_new = quit_omc(omc_new)

writeResultAndExit(0)
