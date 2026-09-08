#!/usr/bin/env python3

import re, os, signal, string, subprocess
import simplejson as json

# Windows has no SIGKILL, and no process group to signal instead; os.kill there
# is TerminateProcess whichever signal it is handed.
SIGKILL = getattr(signal, "SIGKILL", signal.SIGTERM)

# A job is named after the branch it tests, and takes the last part of the name:
# maintenance/v1.27 is stored and published as v1.27. A pull request is the
# exception - pr/16370 keeps the directory it is in, so that the branches
# directory holds branches and the pull requests sit together under one of them.
prBranchRe = re.compile(r"^pr/[0-9]+$")

def resultTable(branch):
  """The results of a job named after this branch: its table and its directory."""
  return branch if prBranchRe.match(branch) else branch.split("/")[-1]

# How long a model may simulate when nothing asks for longer; update-ulimit-exe.py
# derives it, and the exceptions, from the master results.
DEFAULT_ULIMIT_EXE = 240

simCodeTargetRe = re.compile('--simCodeTarget=([^"\'\\s,;)]+)')

def simCodeTargetFromCommands(target, commands):
  for cmd in commands:
    found = simCodeTargetRe.findall(str(cmd))
    if found:
      target = found[-1]
  return target

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
    data["defaultTolerance"] = float(data.get("defaultTolerance") or 1e-6)
    data["defaultNumberOfIntervals"] = int(data.get("defaultNumberOfIntervals") or 2500)
    data["reference_reltol"] = float(data.get("reference_reltol") or 3e-3)
    data["reference_reltolDiffMinMax"] = float(data.get("reference_reltolDiffMinMax") or 3e-3)
    data["reference_rangeDelta"] = float(data.get("reference_rangeDelta") or 1e-3)
    if data["simCodeTarget"]=="Cpp":
      defaultCustomCommands2 = defaultCustomCommands[:]
      defaultCustomCommands2.append('setCommandLineOptions("--simCodeTarget=Cpp")')
    else:
      defaultCustomCommands2 = defaultCustomCommands
    data["customCommands"] = (data.get("customCommands") or defaultCustomCommands2) + (data.get("extraCustomCommands") or [])
    # A --simCodeTarget in the commands (e.g. from --extraflags) is what omc will
    # actually use, so the rest of the testing scripts need to see it
    data["simCodeTarget"] = simCodeTargetFromCommands(data["simCodeTarget"], data["customCommands"])
    data["ulimitOmc"] = int(data.get("ulimitOmc") or 660) # 11 minutes to generate the C-code
    data["ulimitExe"] = int(data.get("ulimitExe") or DEFAULT_ULIMIT_EXE)
    data["ulimitExeModels"] = dict((k,int(v)) for (k,v) in (data.get("ulimitExeModels") or {}).items())
    data["ulimitLoadModel"] = int(data.get("ulimitLoadModel") or 3*60) # 3 minutes to load the files (could take a while if the ssd is doing backup)
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
    data["libraryVersionExactMatch"] = data.get("libraryVersionExactMatch") or False
    data["alarmFlag"] = data.get("alarmFlag") or (alarmFlag if data["simCodeTarget"] in ("C","C+Rust","wasm-jit") else "")
    data["abortSlowSimulation"] = data.get("abortSlowSimulation") or (abortSimulationFlag if data["simCodeTarget"] in ("C","C+Rust") else "")
    data["simFlags"] = simulationFlags(data, data["ulimitExe"])
    if "changeHash" in data: # Force rebuilding the library due to change in the testing script
      data["changeHash"] = data["changeHash"]
    return (data["library"],data)
  except:
    print("Failed to fix data for: %s with extra args: %s" % (str(data),str((abortSimulationFlag,alarmFlag,defaultCustomCommands))))
    raise

def alarmGrace(timeout):
  """How long omc keeps running past its own alarm before it kills itself.

  Mirrors SystemImpl__alarm. Waiting it out is what lets a timed-out command
  report the phases it did complete.
  """
  return min(60, max(5, timeout // 10))

def modelUlimitExe(conf, modelName):
  """How long that model may simulate: what its library allows, unless the model
  is one of the few named in ulimitExeModels."""
  return conf["ulimitExeModels"].get(modelName) or conf["ulimitExe"]

def simulationFlags(conf, ulimitExe):
  """The flags a simulation allowed that many seconds is run with."""
  if conf["alarmFlag"] == "":
    return "%s %s" % (conf["abortSlowSimulation"],conf["extraSimFlags"])
  return "%s %s=%d %s" % (conf["abortSlowSimulation"],conf["alarmFlag"],ulimitExe,conf["extraSimFlags"])

def readConfig(c,abortSimulationFlag="",alarmFlag="",overrideDefaults=[],defaultCustomCommands=[],extrasimflags="",environmentTranslation=[],environmentSimulation=[]):
  return [fixData(data,abortSimulationFlag,alarmFlag,overrideDefaults,defaultCustomCommands,extrasimflags,environmentTranslation,environmentSimulation) for data in json.load(open(c))]

def libname(library, conf):
  if "libraryVersionNameForTests" in conf:
    return library+"_"+conf["libraryVersionNameForTests"] if conf["libraryVersionNameForTests"] else library
  return library+("_"+conf["libraryVersion"] if conf["libraryVersion"]!="default" else "")+(("_" + conf["configExtraName"]) if "configExtraName" in conf else "")

# A model the run no longer found in its library; the reports ask for >= 0.
DELETED_PHASE = -1

def finalphaseName(finalphase):
  if finalphase == DELETED_PHASE:
    return "Removed"
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

# A subscript of a result variable: the [1] of a[1], the [3,7] of a[3,7].
arraySubscriptRe = re.compile(r"\[[0-9]+(?:,[0-9]+)*\]")
# Stands in for a subscript while the rest of the name is escaped. No Modelica
# name contains it.
subscriptPlaceholder = "\x00"

# How many alternations we are willing to hand the runtime. Its regcomp builds a
# state machine that grows with the square of the number of branches - 1000
# branches cost it 30 MB, 2000 cost 120 MB and 10000 cost 2.5 GB - so a filter
# with more than this is dropped rather than compiled.
MAX_VARIABLE_FILTER_BRANCHES = 2000

def variableFilterOf(variables):
  """The variableFilter that keeps these result variables.

  The names go in as the reference file writes them - a[1,2], der(x) - and come
  out as one regex branch each, except that all the elements of an array share a
  single branch: a reference file lists every element separately, so a model with
  a 280x280 parameter array would otherwise give a filter of 78400 branches.
  That branch also matches the elements the reference file leaves out, which
  costs a few columns in the result file and nothing else.

  A model with more distinct variables than regcomp can afford gets ".*": a
  result file with everything in it, rather than an expensive regex.
  """
  branches = []
  seen = set()
  for v in variables:
    # The subscript is put aside first, so that the escaping below cannot eat the
    # brackets it is recognized by.
    branch = arraySubscriptRe.sub(subscriptPlaceholder, v)
    # (), [] and " are regex metacharacters. Matching them with . rather than
    # escaping them is what this filter has always done; either way it matches
    # the names they appear in.
    for c in '[]()"':
      branch = branch.replace(c, ".")
    branch = branch.replace(subscriptPlaceholder, ".[0-9,]+.")
    if branch not in seen:
      seen.add(branch)
      branches.append(branch)
  if len(branches) > MAX_VARIABLE_FILTER_BRANCHES:
    return ".*"
  return "|".join(branches)

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

    #if (not os.path.exists("HelloWorld_res.mat")):
    #  print("Result file HelloWorld_res.mat WAS NOT generated running: ./HelloWorld with flags [%s]" % f)
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

def fmiSimulatorName(command):
  """The name of the simulator a bare --fmisimulator runs.

  Any of the known names appearing in the command wins; a command that names
  none of them is OMSimulator, which is how --fmisimulator was used before it
  could name its simulator.
  """
  for name in sorted(fmiSimulators(), key=len, reverse=True):
    if name.lower() in command.lower():
      return name
  return "OMSimulator"

def parseFmiSimulators(fmisimulators):
  """The --fmisimulator values as an ordered list of (name, command).

  A value is either "name=command" or just the command, whose name is then
  taken from the command itself.  The name decides which simulator of
  configs/fmi-simulators.json is run and which branch its results go to, see
  branchForSimulator.
  """
  res = []
  for s in fmisimulators or []:
    if not s:
      continue
    name, sep, command = s.partition("=")
    if not sep or "/" in name or " " in name:
      (name, command) = (fmiSimulatorName(s), s)
    res.append((name, command))
  names = [n for (n, _) in res]
  if len(set(names)) != len(names):
    raise Exception("The same FMI simulator name is used twice: %s" % ", ".join(names))
  for name in names:
    if fmiSimulator(name).get("untested"):
      print("Warning: nobody has run %s through the testing yet; if its flags in %s are wrong, "
            "every model will fail to simulate." % (name, FMI_SIMULATORS_FILE))
  return res

# The FMI simulators live in configs/fmi-simulators.json, so that adding one is
# an entry in a file rather than a change to the scripts.  A simulator stores
# its results in the branch of the job with its name appended, except
# OMSimulator, which has always had the plain -fmi table to itself; the mapping
# is keyed by the simulator and not by the order it was given in, so that a job
# running only FMPy still fills v1.27-fmi-fmpy and not v1.27-fmi.
FMI_SIMULATORS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "configs", "fmi-simulators.json")
_fmiSimulators = None

def fmiSimulators(path=None):
  """Everything the testing knows about the FMI simulators."""
  global _fmiSimulators
  if _fmiSimulators is None or path:
    with open(path or FMI_SIMULATORS_FILE) as fin:
      _fmiSimulators = dict((k, v) for (k, v) in json.load(fin).items() if not k.startswith("_"))
  return _fmiSimulators

def fmiSimulator(name):
  """What is known about an FMI simulator, by the name --fmisimulator gave it."""
  known = fmiSimulators()
  if name not in known:
    raise Exception("Unknown FMI simulator %s; known are %s. Adding one is an entry in %s."
                    % (name, ", ".join(sorted(known)), FMI_SIMULATORS_FILE))
  return known[name]

def fmiSimulatorCommand(name, command, **values):
  """The command line that runs one FMU with one simulator.

  arguments is a template over the values below plus anything the entry defines
  in optionalArguments, which are the flags that have to disappear when there
  is nothing to put in them: OMSimulator crashes on --stepSize=0 rather than
  ignoring it, while FMPy wants --output-interval 0 all the same and therefore
  writes the value straight into its arguments.
  """
  spec = fmiSimulator(name)
  values["simulator"] = command
  for (key, template) in (spec.get("optionalArguments") or {}).items():
    used = [f.split(":")[0].split(".")[0].split("[")[0]
            for (_, f, _, _) in string.Formatter().parse(template) if f]
    values[key] = template.format(**values) if all(values.get(u) for u in used) else ""
  return "%s %s" % (spec.get("command", "{simulator}").format(**values),
                    spec["arguments"].format(**values))

# The ways an exported wasm artifact can be simulated, in configs/wasm-jit-runners.json.
# The same shape as the FMI simulators above, except that a runner is not a tool
# to invoke: it is a set of simulation flags omc itself is given, since the
# artifact is run inside omc.
WASM_JIT_RUNNERS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     "configs", "wasm-jit-runners.json")
_wasmJitRunners = None

def wasmJitRunners(path=None):
  """Everything the testing knows about the wasm-jit artifact runners."""
  global _wasmJitRunners
  if _wasmJitRunners is None or path:
    with open(path or WASM_JIT_RUNNERS_FILE) as fin:
      _wasmJitRunners = dict((k, v) for (k, v) in json.load(fin).items() if not k.startswith("_"))
  return _wasmJitRunners

def wasmJitRunner(name):
  known = wasmJitRunners()
  if name not in known:
    raise Exception("Unknown wasm-jit runner %s; known are %s. Adding one is an entry in %s."
                    % (name, ", ".join(sorted(known)), WASM_JIT_RUNNERS_FILE))
  return known[name]

def parseWasmJitRunners(names):
  """The --wasmjitrunner values as an ordered list of (name, simflags)."""
  res = []
  for spec in names or []:
    for name in spec.split(","):
      name = name.strip()
      if name:
        res.append((name, wasmJitRunner(name).get("simflags") or ""))
  seen = [n for (n, _) in res]
  if len(set(seen)) != len(seen):
    raise Exception("The same wasm-jit runner name is used twice: %s" % ", ".join(seen))
  return res

def branchForWasmJitRunner(branch, name):
  """Where the results of one wasm-jit runner are stored: --branch, then -<name>."""
  return branch + wasmJitRunner(name).get("branchSuffix", "-%s" % name)

# The solvers one built model can be run with, in configs/solvers.json. Like the
# wasm-jit runners, a solver is not a tool but a set of simulation flags, so
# cvode, gbode and ida share one translation and one compilation.
SOLVERS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "configs", "solvers.json")
_solvers = None

def solvers(path=None):
  """Everything the testing knows about the solvers."""
  global _solvers
  if _solvers is None or path:
    with open(path or SOLVERS_FILE) as fin:
      _solvers = dict((k, v) for (k, v) in json.load(fin).items() if not k.startswith("_"))
  return _solvers

def solver(name):
  known = solvers()
  if name not in known:
    raise Exception("Unknown solver %s; known are %s. Adding one is an entry in %s."
                    % (name, ", ".join(sorted(known)), SOLVERS_FILE))
  return known[name]

def parseSolvers(names):
  """The --solver values as an ordered list of (name, simflags)."""
  res = []
  for spec in names or []:
    for name in spec.split(","):
      name = name.strip()
      if name:
        res.append((name, solver(name).get("simflags") or ""))
  seen = [n for (n, _) in res]
  if len(set(seen)) != len(seen):
    raise Exception("The same solver name is used twice: %s" % ", ".join(seen))
  return res

def branchForSolver(branch, name):
  """Where the results of one solver are stored: the table its entry names, as a
  template over the branch of the job and the name of the solver."""
  return (solver(name).get("branch") or "{name}").format(branch=branch, name=name)

def branchForSimulator(branch, name):
  """Where the results of one FMI simulator of a run are stored.

  --branch names the job, v1.27-fmi, and every simulator derives its own from
  it: OMSimulator fills v1.27-fmi, FMPy v1.27-fmi-fmpy, whether they run
  together or on their own.
  """
  return branch + fmiSimulator(name).get("branchSuffix", "-%s" % name)
