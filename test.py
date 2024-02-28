#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# TODO: When libraries hash changes, run with the old OMC against the new libs
#       Then run with the new OMC against the new libs

import sys
if (sys.version_info < (3, 0)):
  raise Exception("Python2 is no longer supported")

import html, shutil, os, re, glob, time, argparse, sqlite3, datetime, math, platform
from joblib import Parallel, delayed
import simplejson as json
import psutil, subprocess, threading, hashlib
from subprocess import call
from monotonic import monotonic
from omcommon import friendlyStr, multiple_replace
from natsort import natsorted
from shared import readConfig, getReferenceFileName, simulationAcceptsFlag, isFMPy
from platform import processor
import shared

import signal

parser = argparse.ArgumentParser(description='OpenModelica library testing tool')
parser.add_argument('configs', nargs='*')
parser.add_argument('--branch', default='master')
parser.add_argument('--fmi', default=False)
parser.add_argument('--output', default='')
parser.add_argument('--docker', default='')
parser.add_argument('--libraries', help="Directory omc will search in to load system libraries/libraries to test.", default='')
parser.add_argument('--extraflags', default='')
parser.add_argument('--extrasimflags', default='')
parser.add_argument('--ompython_omhome', default='')
parser.add_argument('--noclean', action="store_true", default=False)
parser.add_argument('--fmisimulator', default='')
parser.add_argument('--ulimitvmem', help="Virtual memory limit (in kB) (linux only)", type=int, default=8*1024*1024)
parser.add_argument('--default', action='append', help="Add a default value for some configuration key, such as --default=ulimitExe=60. The equals sign is mandatory.", default=[])
parser.add_argument('-j', '--jobs', default=0)
parser.add_argument('-v', '--verbose', action="store_true", help="Verbose mode.", default=False)
parser.add_argument('--execAllTests', action="store_true", help="Force all tests to be executed", default=False)
parser.add_argument('--noSync', action="store_true", help="Move files using python instead of rsync", default=False)
parser.add_argument('--timeout', default=0, help="=[value] timeout in seconds for each test, it overrides the timeout calculated by the script")

args = parser.parse_args()
configs = args.configs
branch = args.branch
result_location = os.path.abspath(args.output) if args.output else ''
n_jobs = int(args.jobs)
clean = not args.noclean
verbose = args.verbose
extraflags = args.extraflags
extrasimflags = args.extrasimflags
ompython_omhome = args.ompython_omhome
fmisimulator = args.fmisimulator or None
allTestsFmi = args.fmi
ulimitMemory = args.ulimitvmem
docker = args.docker
isWin = os.name == 'nt'
librariespath = ''
if args.libraries:
  librariespath = os.path.abspath(os.path.normpath(args.libraries))
else:
  if isWin:
    librariespath = os.path.normpath(os.path.join(os.environ.get('APPDATA'), '.openmodelica', 'libraries'))
  else:
    librariespath = os.path.normpath(os.path.join(os.environ.get('HOME'), '.openmodelica', 'libraries'))
overrideDefaults = [arg.split("=", 1) for arg in args.default]
execAllTests = args.execAllTests
noSync = args.noSync

exeExt = ".exe" if isWin else ""
customTimeout = int(args.timeout)

def rmtree(f):
  try:
    shutil.rmtree(f)
  except UnicodeDecodeError:
    # Yes, we can get UnicodeDecodeError because shutil.rmtree is poorly implemented
    subprocess.check_call(["rm", "-rf", f], stderr=subprocess.STDOUT)

def print_linenum(signum, frame):
  print("Currently at line", frame.f_lineno)

if not isWin:
  signal.signal(signal.SIGUSR1, print_linenum)

def runCommand(cmd, prefix, timeout):
  process = [None]
  def target():
    with open(os.devnull, 'w')  as FNULL:
      if isWin:
        process[0] = subprocess.Popen(cmd, shell=True, stdin=FNULL, stdout=FNULL, stderr=FNULL)
      else:
        process[0] = subprocess.Popen(cmd, shell=True, stdin=FNULL, stdout=FNULL, stderr=FNULL, preexec_fn=os.setpgrp)

      while process[0].poll() is None:
        print("process running... pid: " + str(process[0].pid) + " timeout: " + str(timeout) + " cmd: " + cmd.split('>',1)[0])
        process[0].communicate(1)
        process[0].wait(1)


  thread = threading.Thread(target=target)
  thread.start()
  thread.join(timeout)

  gotTimeout = False

  if thread.is_alive():
    gotTimeout = True
    print("process SIGTERM... pid: " + str(process[0].pid))
    if isWin:
      os.kill(process[0].pid, signal.SIGTERM)
    else:
      os.kill(-process[0].pid, signal.SIGTERM)
    thread.join(min(10, timeout))
    if thread.is_alive():
      print("process SIGKILL... pid: " + str(process[0].pid))
      if isWin:
        os.kill(process[0].pid, signal.SIGKILL)
      else:
        os.kill(-process[0].pid, signal.SIGKILL)
    thread.join()

  if clean:
    print("---> try clean")
    try:
      lines = open("%s.tmpfiles" % prefix).readlines()
    except:
      lines = []
    for suffix in [".so",".mos","",".o",".h",".c",".cpp","_info.json",".xml",".tmpfiles",".pipe",".tmpfiles",".libs",".log"]:
      for f in glob.glob(prefix+suffix):
        lines.append(f)
      for f in glob.glob("OM"+prefix+suffix):
        lines.append(f)
    for line in lines:
      f = line.strip()
      if os.path.isdir(f):
        rmtree(f)
      elif os.path.exists(f):
        os.unlink(f)
    try:
      rmtree(prefix)
    except OSError:
      pass

  return 1 if gotTimeout else process[0].returncode

try:
  subprocess.check_output(["python", "testmodel.py", "--help"], stderr=subprocess.STDOUT)

except subprocess.CalledProcessError as e:
  print("Sanity check failed (./testmodel.py --help):\n" + e.output.decode())
  sys.exit(1)

# If -j=0 is specified (or -j is not specified, defaults to 0) then use all available physical CPUS.
if n_jobs == 0:
  n_jobs = psutil.cpu_count(logical=False)

# If we are running one test at a time assume that omc is allowed to use multiple
# threads for each individual test.
if n_jobs == 1:
  single_thread="" # Alternative: single_thread="-n=0"
else:
  single_thread="-n=1"


print("branch: %s, n_jobs: %d" % (branch, n_jobs))

if clean:
  print("Removing temporary files, etc to the best ability of the script")

if not librariespath:
  print("Error: --libraries is a mandatory argument")
  sys.exit(1)

if docker:
  print("###")
  print("###")
  print("Warning: Using docker to run this will fail. It is not fully working and needs to be reworked to use docker exec instead of docker run")
  print("###")
  print("###")
  dir_path = os.path.normpath(os.path.dirname(os.path.realpath(__file__)))
  subprocess.check_output(["docker", "pull", docker], stderr=subprocess.STDOUT).strip()
  dockerExtraArgs = ["-w", dir_path, "-v", "%s:%s" % (dir_path,dir_path), "--env", "OPENMODELICALIBRARY=%s" % "/usr/lib/omlibrary", "--env", "GC_MARKERS=1", "-v", "%s:/usr/lib/omlibrary" % librariespath]
  commands = ["docker", "run", "--user", str(os.getuid())] + dockerExtraArgs + [docker]
  omc_cmd = commands + ["omc"]
else:
  commands = []
  dockerExtraArgs = []
  if os.environ.get("OPENMODELICAHOME"):
    omc_cmd = [os.path.normpath(os.path.join(os.environ.get("OPENMODELICAHOME"), 'bin', 'omc'))]
  else:
    omc_cmd = ["omc"]
if result_location != "" and not os.path.exists(result_location):
  os.makedirs(result_location)

if configs == []:
  print("Error: Expected at least one configuration file to start the library test")
  sys.exit(1)

from OMPython import OMCSession, OMCSessionZMQ

# Try to make the processes a bit nicer...
os.environ["GC_MARKERS"]="1"

print("Start OMC version")

if ompython_omhome != "":
  # Use a different OMC for running OMPython than for running the tests
  omhome = os.environ["OPENMODELICAHOME"]
  omc_version = subprocess.check_output(omc_cmd + ["--version"], stderr=subprocess.STDOUT).decode("ascii").strip()
  os.environ["OPENMODELICAHOME"] = ompython_omhome
  omc = OMCSessionZMQ()
  ompython_omc_version=omc.sendExpression('getVersion()')
  os.environ["OPENMODELICAHOME"] = omhome
else:
  omc = OMCSessionZMQ(docker=docker, dockerExtraArgs=dockerExtraArgs)
  omhome=omc.sendExpression('getInstallationDirectoryPath()')
  omc_version=omc.sendExpression('getVersion()')
  ompython_omc_version=omc_version
ompython_omc_version=ompython_omc_version.replace("OMCompiler","").strip()

def timeSeconds(f):
  return html.escape("%.2f" % f)

if not docker:
  omc.sendExpression('setModelicaPath("%s")' % librariespath.replace('\\','/'))
omc_exe=os.path.normpath(os.path.join(omhome,"bin","omc"))
dygraphs=os.path.normpath(os.path.join(ompython_omhome or omhome,"share","doc","omc","testmodels","dygraph-combined.js"))
print(omc_exe,omc_version,dygraphs)

sys.stdout.flush()

# Do feature checks. Handle things like old RML-style arguments...

subprocess.check_output(omc_cmd + ["-n=1", "--version"], stderr=subprocess.STDOUT).strip()

sys.stdout.flush()

fmisimulatorversion = None
if fmisimulator:
  try:
    if not isFMPy(fmisimulator):
      fmisimulatorversion = subprocess.check_output([fmisimulator, "-v"], stderr=subprocess.STDOUT).strip()
    else:
      fmisimulatorversion = subprocess.getoutput(fmisimulator + " -h | grep version | tr '\n' ' ' | tr -s ' '" ).strip().encode('ascii')
  except subprocess.CalledProcessError as e:
    print("Failure to run %s:\n%s" %(fmisimulator, e.output))
    raise e
  print(fmisimulatorversion)
else:
  if allTestsFmi:
    raise Exception("No OMSimulator; trying to simulate using FMI")
  print("No OMSimulator")

sys.stdout.flush()

try:
  os.unlink("HelloWorld"+exeExt)
except OSError:
  pass
subprocess.check_output(omc_cmd + ["--simCodeTarget=Cpp", "HelloWorld.mos"], stderr=subprocess.STDOUT)
if os.path.exists("HelloWorld"+exeExt):
  print("Have C++ HelloWorld simulation executable")
  haveCppRuntime=simulationAcceptsFlag("", isWin=isWin)
  if haveCppRuntime:
    print("Have C++ runtime")
  else:
    print("C++ HelloWorld simulation executable failed to run")
else:
  haveCppRuntime=False
  print("No C++ runtime")

sys.stdout.flush()

try:
  subprocess.check_output(omc_cmd + ["Architecture.mo"], stderr=subprocess.STDOUT)
except subprocess.CalledProcessError:
  print("Patching ModelicaServices for Architecture bug...")
  for f in glob.glob(librariespath + os.path.normpath("/ModelicaServices*/package.mo")) + glob.glob(omhome + os.path.normpath("/Modelica */Constants.mo")):
    with open(f) as fin:
      content = fin.read()
    assert(len(content) > 0)
    content = content.replace("OpenModelica.Internal.Architecture.integerMax()","2147483647")
    assert(len(content) > 0)
    with open(f, "w") as fout:
      open(f,"w").write(content)
  print("Done patching ModelicaServices...")

sys.stdout.flush()

defaultCustomCommands = []
if extraflags:
  defaultCustomCommands += [extraflags]

def testHelloWorld(cmd):
  with open("HelloWorld.mos") as fin:
    helloWorldContents = fin.read()
  try:
    os.unlink("HelloWorld"+exeExt)
  except OSError:
    pass
  open("HelloWorld.cmd.mos","w").write(cmd + "\n" + helloWorldContents)
  try:
    out=subprocess.check_output(omc_cmd + ["HelloWorld.cmd.mos"], stderr=subprocess.STDOUT)
    if os.path.exists("HelloWorld"+exeExt) and not "Error:" in out.decode():
      return True
  except subprocess.CalledProcessError as e:
    pass
  return False

for cmd in [
  'setCommandLineOptions("-d=nogen");',
  'setCommandLineOptions("-d=initialization");',
  'setCommandLineOptions("-d=backenddaeinfo");',
  'setCommandLineOptions("-d=discreteinfo");',
  'setCommandLineOptions("-d=stateselection");',
  'setCommandLineOptions("-d=execstat");',
  'setMatchingAlgorithm("PFPlusExt");',
  'setIndexReductionMethod("dynamicStateSelection");'
]:
  if testHelloWorld(cmd):
    defaultCustomCommands.append(cmd)

canChangeOptLevel = False
if testHelloWorld("flags:=getCFlags();setCFlags(flags+\" -O1\");"):
  canChangeOptLevel = True
else:
  print("Cannot change optimization level")

fmiOK_C = False
fmiOK_Cpp = False
if allTestsFmi:
  try:
    out=subprocess.check_output(omc_cmd + ["--simCodeTarget=C", "FMI.mos"], stderr=subprocess.STDOUT)
    if os.path.exists("HelloWorldX.fmu") and not "Error:" in out.decode():
      fmiOK_C = True
      print("C FMU OK")
    else:
      print("No C-based FMUs (files not generated in correct location)")
  except subprocess.CalledProcessError as e:
    pass
  try:
    out=subprocess.check_output(omc_cmd + ["--simCodeTarget=Cpp", "FMI.mos"], stderr=subprocess.STDOUT)
    if os.path.exists("HelloWorldX.fmu") and not "Error:" in out.decode():
      fmiOK_Cpp = True
      print("C++ FMU OK")
    else:
      print("No C++-based FMUs (files not generated in correct location)")
  except subprocess.CalledProcessError as e:
    pass

try:
  os.unlink("HelloWorld"+exeExt)
except OSError:
  pass
print(subprocess.check_output(omc_cmd + ["HelloWorld.mos"], stderr=subprocess.STDOUT).decode().strip())
assert(os.path.exists("HelloWorld"+exeExt))
abortSimulationFlag="-abortSlowSimulation" if simulationAcceptsFlag("-abortSlowSimulation", isWin=isWin) else ""
alarmFlag="-alarm" if simulationAcceptsFlag("-alarm=480", isWin=isWin) else ""

configs_lst = [readConfig(c, abortSimulationFlag=abortSimulationFlag, alarmFlag=alarmFlag, overrideDefaults=overrideDefaults, defaultCustomCommands=defaultCustomCommands, extrasimflags=extrasimflags) for c in configs]
configs = []
preparedReferenceDirs = {}
for c in configs_lst:
  configs = configs + c
for (lib,c) in configs:
  if "referenceFiles" in c:
    c["referenceFilesURL"] = c["referenceFiles"]
    if isinstance(c["referenceFiles"], (str, bytes)):
      m = re.search("^[$][A-Z]+", c["referenceFiles"])
      if m:
        k = m.group(0)[1:]
        if k not in os.environ:
          raise Exception("Environment variable %s not defined, but used in JSON config for reference files" % k)
        c["referenceFiles"] = c["referenceFiles"].replace(m.group(0), os.environ[k])
    elif "giturl" in c["referenceFiles"]:
      refFilesGitTag = "origin/master"
      if "git-ref" in c["referenceFiles"]:
        refFilesGitTag = c["referenceFiles"]["git-ref"].strip()
      if c["referenceFiles"]["destination"] in preparedReferenceDirs:
        (c["referenceFiles"],c["referenceFilesURL"]) = preparedReferenceDirs[destination]
        continue
      giturl = c["referenceFiles"]["giturl"]
      destination = os.path.normpath(c["referenceFiles"]["destination"])
      destinationReal = os.path.normpath(os.path.realpath(destination))

      if not os.path.isdir(destination):
        if "git-directory" in c["referenceFiles"]:
          # Sparse clone
          os.makedirs(destination)
          subprocess.check_call(["git", "init"], stderr=subprocess.STDOUT, cwd=destinationReal)
          subprocess.check_call(["git", "remote", "add", "-f", "origin", giturl], stderr=subprocess.STDOUT, cwd=destinationReal)
          subprocess.check_call(["git", "config", "core.sparseCheckout", "true"], stderr=subprocess.STDOUT, cwd=destinationReal)
          file = open(os.path.join(destinationReal,".git", "info", "sparse-checkout"), "a")
          file.write(c["referenceFiles"]["git-directory"].strip())
          file.close()
        else:
          # Clone
          subprocess.check_call(["git", "clone", giturl, destination], stderr=subprocess.STDOUT)

      subprocess.check_call(["git", "clean", "-fdx", "--exclude=*.hash"], stderr=subprocess.STDOUT, cwd=destinationReal)
      subprocess.check_call(["git", "fetch", "origin"], stderr=subprocess.STDOUT, cwd=destination)
      subprocess.check_call(["git", "reset", "--hard", refFilesGitTag], stderr=subprocess.STDOUT, cwd=destinationReal)
      subprocess.check_call(["git", "clean", "-fdx", "--exclude=*.hash"], stderr=subprocess.STDOUT, cwd=destinationReal)
      if glob.glob(destinationReal + "/*.mat.xz"):
        subprocess.check_call(["find", ".", "-name", "*.mat.xz", "-exec", "xz", "--decompress", "--keep", "{}", ";"], stderr=subprocess.STDOUT, cwd=destinationReal)
      githash = subprocess.check_output(["git", "rev-parse", "--verify", "HEAD"], stderr=subprocess.STDOUT, cwd=destinationReal, encoding='utf8')

      if "git-directory" in c["referenceFiles"]:
        c["referenceFiles"] = os.path.join(destinationReal, c["referenceFiles"]['git-directory'])
        print(c["referenceFiles"])
      else:
        c["referenceFiles"] = destinationReal

      if giturl.startswith("https://github.com"):
        c["referenceFilesURL"] = '<a href="%s/tree/%s">%s (%s)</a>' % (giturl, githash.strip(), giturl, githash.strip())
      else:
        c["referenceFilesURL"] = "%s (%s)" % (giturl, githash.strip())
      preparedReferenceDirs[destination] = (c["referenceFiles"],c["referenceFilesURL"])
    else:
      raise Exception("Unknown referenceFiles in config: %s" % (str(c["referenceFiles"])))


  if allTestsFmi:
    c["fmi"] = "2.0"

# Create mos-files

conn = sqlite3.connect('sqlite3.db')
cursor = conn.cursor()

user_version = cursor.execute("PRAGMA user_version").fetchone()[0]

if user_version==0:
  # BOOLEAN NOT NULL CHECK (verify IN (0,1) AND builds IN (0,1) AND simulates IN (0,1))
  # Table to lookup from a run (date, branch) to omcversion used
  cursor.execute("CREATE TABLE if not exists [omcversion] (date integer NOT NULL, branch text NOT NULL, omcversion text NOT NULL)")
  # Table to lookup from a run (date, branch) which library versions were used
  cursor.execute("CREATE TABLE if not exists [libversion] (date integer NOT NULL, branch text NOT NULL, libname text NOT NULL, libversion text NOT NULL, confighash integer NOT NULL)")
elif user_version==1:
  cursor.execute("ALTER TABLE [libversion] ADD COLUMN confighash integer NOT NULL DEFAULT(0)")
elif user_version==2:
  tables = [tbl for (tbl,) in cursor.execute("SELECT name FROM sqlite_master WHERE type='table'") if tbl not in ["libversion","omcversion"]]
  for tbl in tables:
    cursor.execute("ALTER TABLE [%s] ADD COLUMN parsing real NOT NULL DEFAULT(0.0)" % tbl)
elif user_version in [3]:
  pass
else:
  print("Unknown schema user_version=%d" % user_version)
  sys.exit(1)

cursor.execute('''CREATE TABLE if not exists [%s]
             (date integer NOT NULL, libname text NOT NULL, model text NOT NULL, exectime real NOT NULL,
             frontend real NOT NULL, backend real NOT NULL, simcode real NOT NULL, templates real NOT NULL, compile real NOT NULL, simulate real NOT NULL,
             verify real NOT NULL, verifyfail integer NOT NULL, verifytotal integer NOT NULL, finalphase integer NOT NULL, parsing real NOT NULL)''' % branch)
cursor.execute('''DROP INDEX IF EXISTS [idx_%s_date]''' % branch)
cursor.execute('''DROP INDEX IF EXISTS idx_omcversion_date''')
cursor.execute('''DROP INDEX IF EXISTS idx_libversion_date''')

# Set user_version to the current schema
cursor.execute("PRAGMA user_version=3")

def strToHashInt(s):
  return int(hashlib.sha1((s+"fixCorruptBuilds-2017-03-26").encode("utf-8")).hexdigest()[0:8],16)

def findAllFiles(d):
  res = []
  for root, dirs, files in os.walk(d):
    if "/." in root:
      continue
    res += [os.path.join(root, f) for f in files if f[0]!="."]
  return res

def getmd5(f):
  hf = os.path.normpath(f+".hash")
  if not os.path.exists(hf) or (os.path.getmtime(f) > os.path.getmtime(hf)):
    with open(hf, "w") as fout:
      with open(f, "rb") as fin:
        fout.write(hashlib.sha512(fin.read()).hexdigest())
  with open(hf) as fin:
    return fin.read()


def hashReferenceFiles(s):
  if s=="":
    return s
  files = [f for f in findAllFiles(s) if (not f.endswith(".hash"))]
  files = sorted(files)
  res = "".join([getmd5(f) for f in files])
  return res+"fixCorruptBuilds-2017-06-21"

stats_by_libname = {}
skipped_libs = {}
tests=[]
for (library,conf) in configs:
  c=conf.copy()
  del(c["configFromFile"])
  if "referenceFiles" in c:
    del(c["referenceFilesURL"])
    confighash = strToHashInt(str(c)+hashReferenceFiles(conf["referenceFiles"]))
  else:
    confighash = strToHashInt(str(c)+hashReferenceFiles(""))
  conf["confighash"] = confighash
  conf["omhome"] = omhome
  conf["single_thread_cmd"] = single_thread
  conf["haveCppRuntime"] = haveCppRuntime
  conf["ulimitMemory"] = conf.get("ulimitMemory") or ulimitMemory
  if conf.get("fmi"):
    conf["haveFMI"] = fmiOK_C
    conf["haveFMICpp"] = fmiOK_Cpp
    conf["fmisimulator"] = fmisimulator
    conf["fmuType"] = conf.get("fmuType", "me")
  if (not canChangeOptLevel) and "optlevel" in conf:
    print("Deleting optlevel")
    del conf["optlevel"]
  if not (omc.sendExpression('setCommandLineOptions("-g=Modelica")') or omc.sendExpression('setCommandLineOptions("+g=Modelica")')):
    print("Failed to set Modelica grammar")
    sys.exit(1)
  omc.sendExpression('clear()')
  if "loadFileCommands" in conf:
    for command in conf["loadFileCommands"]:
      if not omc.sendExpression(command):
        try:
          print("Failed to run command %s: %s" % (command,omc.sendExpression('OpenModelica.Scripting.getErrorString()')))
        except:
          print("Failed to run command %s OpenModelica.Scripting.getErrorString() failed..." % command)
    librariesToLoad = []
  else:
    librariesToLoad = [[library,conf["libraryVersion"]]] + conf.get("extraLibraries", [])
  for (lib,version) in librariesToLoad:
    if conf["libraryVersionLatestInPackageManager"]:
      availableVersions = omc.sendExpression('getAvailablePackageVersions(%s,"%s")' % (lib,version))
      if not availableVersions:
        try:
          print("Failed to getAvailablePackageVersions %s %s: %s" % (library,version,omc.sendExpression('OpenModelica.Scripting.getErrorString()')))
        except:
          print("Failed to getAvailablePackageVersions %s %s. OpenModelica.Scripting.getErrorString() failed..." % (library,conf["libraryVersion"]))
      versions = "{" + ",".join(['"'+v+'"' for v in availableVersions]) + "}"
    else:
      versions = '{"%s"}' % version
    if not omc.sendExpression('loadModel(%s,%s)' % (lib,versions)):
      try:
        print("Failed to load library %s %s: %s" % (library,versions,omc.sendExpression('OpenModelica.Scripting.getErrorString()')))
      except:
        print("Failed to load library %s %s. OpenModelica.Scripting.getErrorString() failed..." % (library,conf["libraryVersion"]))
  # adrpo: do not sort the top level names as sometimes that loads a bad MSL version
  # conf["loadFiles"] = sorted(omc.sendExpression("{getSourceFile(cl) for cl in getClassNames()}"))
  conf["loadFiles"] = omc.sendExpression("{getSourceFile(cl) for cl in getClassNames()}")

  if not (omc.sendExpression('setCommandLineOptions("-g=MetaModelica")') or omc.sendExpression('setCommandLineOptions("+g=Modelica")')):
    print("Failed to set MetaModelica grammar")
    sys.exit(1)

  try:
    conf["libraryLocation"]=omc.sendExpression('uriToFilename("modelica://%s/")' % library)
    conf["resourceLocation"]=omc.sendExpression('uriToFilename("modelica://%s/Resources")' % library)
  except:
    conf["libraryLocation"]=""
    conf["resourceLocation"]=""

  if "runOnceBeforeTesting" in conf:
    for cmd in conf["runOnceBeforeTesting"]:
      # replace the resource location in the command if present
      cmd = [c.replace("$resourceLocation", conf["resourceLocation"]) for c in cmd]
      cmd = [c.replace("$libraryLocation", conf["libraryLocation"]) for c in cmd]
      subprocess.check_call(cmd, stderr=subprocess.STDOUT)

  if "customCommands" in conf:
    cmd = conf["customCommands"]
    # replace the $libraryLocation in the customCommands if present
    cmd = [c.replace("$libraryLocation", conf["libraryLocation"]) for c in cmd]
    conf["customCommands"] = cmd
  if "environmentSimulation" in conf:
    cmd = conf["environmentSimulation"]
    # replace the $libraryLocation in the environmentSimulation if present
    cmd = [[el.replace("$libraryLocation", conf["libraryLocation"]) for el in c] for c in cmd]
    conf["environmentSimulation"] = cmd
  if "environmentTranslation" in conf:
    cmd = conf["environmentTranslation"]
    # replace the $libraryLocation in the environmentTraslation if present
    cmd = [[el.replace("$libraryLocation", conf["libraryLocation"]) for el in c] for c in cmd]
    conf["environmentTranslation"] = cmd

  conf["libraryVersionRevision"]=omc.sendExpression('getVersion(%s)' % library)
  librarySourceFile=os.path.normpath(omc.sendExpression('getSourceFile(%s)' % library))
  lastChange=(librarySourceFile[:-3]+".last_change") if not librarySourceFile.endswith("package.mo") else (os.path.dirname(librarySourceFile)+".last_change")
  if os.path.exists(lastChange):
    conf["libraryLastChange"] = " %s (revision %s)" % (conf["libraryVersionRevision"],"\n".join(open(lastChange).readlines()).strip())
  else:
    conf["libraryLastChange"] = "%s (%s)" % (conf["libraryVersionRevision"], librarySourceFile)
  metadataFile = os.path.join(os.path.dirname(librarySourceFile), "openmodelica.metadata.json")
  if os.path.exists(metadataFile):
    with open(metadataFile) as metadataIn:
      metadata = json.load(metadataIn)
      conf["libraryLastChange"] = "%s (%s)" % (metadata["version"],metadata.get("sha") or metadata["zipfile"])
      conf["metadata"] = json.dumps(metadata, indent=1)
  else:
    conf["metadata"] = ""
  if not conf["libraryVersionRevision"]:
    conf["libraryVersionRevision"] = conf["libraryLastChange"]
  if conf.get("fmi") and fmisimulatorversion:
    conf["libraryVersionRevision"] = conf["libraryVersionRevision"] + " " + fmisimulatorversion.decode("ascii")
    conf["libraryLastChange"] = conf["libraryLastChange"] + " " + fmisimulatorversion.decode("ascii")
  res=omc.sendExpression('{c for c guard isExperiment(c) and not regexBool(typeNameString(x), "^Modelica_Synchronous\\.WorkInProgress") in getClassNames(%s, recursive=true)}' % library)
  if conf.get("ignoreModelPrefix"):
    prefix = conf["ignoreModelPrefix"]
    res=list(filter(lambda x: not x.startswith(prefix), res))
  libName=shared.libname(library, conf)
  v = cursor.execute("""SELECT date,libversion,libname,branch,omcversion FROM [libversion] NATURAL JOIN [omcversion]
  WHERE libversion=? AND libname=? AND branch=? AND omcversion=? AND confighash=? ORDER BY date DESC LIMIT 1""", (conf["libraryLastChange"],libName,branch,omc_version,confighash)).fetchone()
  if libName in stats_by_libname or libName in skipped_libs:
    raise Exception("Duplicate libName found: %s" % libName)
  if v is None or execAllTests:
    stats_by_libname[libName] = {"conf":conf, "stats":[]}
    tests = tests + [(r,library,libName,libName+"_"+r,conf) for r in res]
    print("Running library %s (%d tests)" % (libName, len(res)))
  else:
    print("Skipping %s as we already have results for it: %s" % (libName,str(v)))
    skipped_libs[libName] = v[0]

try:
  del omc
except:
  pass

print("Checked which libraries to run")
sys.stdout.flush()

errorOccurred=False
for (modelName,library,libName,name,conf) in tests:
  if conf["alarmFlag"]!="":
    conf["simFlags"]="%s %s=%d %s" % (conf["abortSlowSimulation"],conf["alarmFlag"],conf["ulimitExe"],conf["extraSimFlags"])
  else:
    conf["simFlags"]="%s %s" % (conf["abortSlowSimulation"],conf["extraSimFlags"])
  replacements = (
    (u"#logFile#", "/tmp/OpenModelicaLibraryTesting.log"),
    (u"#library#", library),
    (u"#modelName#", modelName),
    (u"#fileName#", name),
    (u"#customCommands#", conf["customCommands"]),
    (u"#modelVersion#", conf["libraryVersion"]),
    (u"#ulimitOmc#", str(conf["ulimitOmc"])),
    (u"#default_tolerance#", str(conf["default_tolerance"])),
    (u"#reference_reltol#", str(conf["reference_reltol"])),
    (u"#reference_reltolDiffMinMax#", str(conf["reference_reltolDiffMinMax"])),
    (u"#reference_rangeDelta#", str(conf["reference_rangeDelta"])),
    (u"#simFlags#", conf["simFlags"]),
    (u"#referenceFiles#", str(conf.get("referenceFilesURL") or conf.get("referenceFiles") or "")),
    (u"#referenceFileNameDelimiter#", conf["referenceFileNameDelimiter"]),
    (u"#referenceFileExtension#", conf["referenceFileExtension"]),
  )
  with open(name + ".conf.json", 'w') as fp:
    newconf = dict(conf.items())
    newconf["referenceFiles"] = newconf["referenceFiles"].replace("\\","/")
    newconf["referenceFilesURL"] = newconf["referenceFilesURL"].replace("\\","/")
    newconf["libraryLocation"] = newconf["libraryLocation"].replace("\\","/")
    newconf["libraryLastChange"] = newconf["libraryLastChange"].replace("\\","/")
    newconf["library"] = library
    newconf["modelName"] = modelName
    newconf["fileName"] = name
    try:
      newconf["referenceFile"] = getReferenceFileName(newconf).replace("\\","/")
    except Exception as e:
      # Find all such errors
      print(e)
      errorOccurred = True
    json.dump(newconf, fp)
if errorOccurred:
  sys.exit(1)

print("Created .conf.json files")
sys.stdout.flush()

def runScript(c, timeout, memoryLimit, verbose):
  j = os.path.normpath("files/%s.stat.json" % c)
  try:
    os.remove(j)
  except:
    pass
  start=monotonic()
  # runCommand("%s %s %s.mos" % (omc_exe, single_thread, c), prefix=c, timeout=timeout)
  if verbose:
    print("Starting test: %s" % c)
    sys.stdout.flush()

  if (isWin and (0 != runCommand("python testmodel.py --win --libraries=%s %s --ompython_omhome=%s %s.conf.json > files/%s.cmdout 2>&1" % (librariespath, ("--docker %s --dockerExtraArgs '%s'" % (docker, " ".join(dockerExtraArgs))) if docker else "", ompython_omhome, c, c), prefix=c, timeout=timeout))) \
     or \
     ((not isWin) and (0 != runCommand("ulimit -v %d; ./testmodel.py --libraries=%s %s --ompython_omhome=%s %s.conf.json > files/%s.cmdout 2>&1" % (memoryLimit, librariespath, ("--docker %s --dockerExtraArgs '%s'" % (docker, " ".join(dockerExtraArgs))) if docker else "", ompython_omhome, c, c), prefix=c, timeout=timeout))):

    print("files/%s.err" % c)
    with open(os.path.normpath("files/%s.err" % c), "a+") as errfile:
      errfile.write("Failed to read output from testmodel.py, exit status != 0:\n")
      try:
        with open(os.path.normpath("files/%s.cmdout" % c)) as cmdout:
          errfile.write(cmdout.read())
      except IOError:
        pass
      except OSError:
        pass

  if clean:
    try:
      os.unlink(os.path.normpath("files/%s.cmdout" % c))
    except OSError:
      pass

  execTime=monotonic()-start
  assert(execTime >= 0.0)
  try:
    data=json.load(open(j))
  except:
    data = {"phase":0}
  data["exectime"] = execTime
  json.dump(data, open(j,"w"))
  if verbose:
    print("Finished test: %s - %d[s]" % (c, execTime))
    sys.stdout.flush()

def expectedExec(c):
  (model,lib,libName,name,data) = c
  if "expectedExec" in data:
    return data["expectedExec"]
  cursor.execute("SELECT exectime FROM [%s] WHERE libname = ? AND model = ? ORDER BY date DESC LIMIT 1" % branch, (libName,model))
  v = cursor.fetchone()
  data["expectedExec"] = (v or (0.0,))[0]
  return data["expectedExec"]

start=monotonic()
tests=sorted(tests, key=lambda c: expectedExec(c), reverse=True)
stop=monotonic()
print("Querying expected execution time: %s" % friendlyStr(stop-start))
sys.stdout.flush()

# Cleanup old runs
try:
  if clean:
    rmtree("./files")
    print("Cleaned files directory")
except OSError:
  pass
try:
  os.mkdir("files")
except OSError:
  pass
print("Created files directory")
sys.stdout.flush()

if len(tests)==0:
  print("Everything already up to date. Not executing any tests.")
  sys.exit(0)


print("Starting execution of %d tests. Estimated execution time %s (wrong if there are new or few tests)." % (len(tests), friendlyStr(sum(expectedExec(c) for c in tests)/(1.0*n_jobs))))
sys.stdout.flush()
cmd_res=[0]
start=monotonic()
start_as_time=time.localtime()
testRunStartTimeAsEpoch = int(time.time())
# Need translateModel + make + exe...
if customTimeout > 0.0:
  cmd_res=Parallel(n_jobs=n_jobs)(delayed(runScript)(name, customTimeout, data["ulimitMemory"], verbose) for (model,lib,libName,name,data) in tests)
else:
  cmd_res=Parallel(n_jobs=n_jobs)(delayed(runScript)(name, 2*data["ulimitOmc"]+data["ulimitExe"]+25, data["ulimitMemory"], verbose) for (model,lib,libName,name,data) in tests)
stop=monotonic()
print("Execution time: %s" % friendlyStr(stop-start))
assert(stop-start >= 0.0)

#if max(cmd_res) > 0:
#  raise Exception("A command failed with exit status")

def loadJsonOrEmptySet(f):
  if os.stat(f).st_size == 0:
    return {}
  else:
    return json.load(open(f))

stats=dict([(name,(name,model,libname,loadJsonOrEmptySet("files/%s.stat.json" % name))) for (model,lib,libname,name,conf) in tests])
#for k in sorted(stats.keys(), key=lambda c: stats[c][3]["exectime"], reverse=True):
#  print("%s: exectime %.2f" % (k, stats[k][3]["exectime"]))

for key in stats.keys():
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
    data.get("phase") or 0,
    data.get("parsing") or 0.0
  )
  # print values
  cursor.execute("INSERT INTO [%s] VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)" % branch, values)
for libname in stats_by_libname.keys():
  confighash = stats_by_libname[libname]["conf"]["confighash"]
  cursor.execute("INSERT INTO [libversion] VALUES (?,?,?,?,?)", (testRunStartTimeAsEpoch, branch, libname, stats_by_libname[libname]["conf"]["libraryLastChange"], confighash))
cursor.execute("INSERT INTO [omcversion] VALUES (?,?,?)", (testRunStartTimeAsEpoch, branch, omc_version))
"""
# Not really a good thing to do; was just done to make generation of the report simpler
for libname in skipped_libs.keys():
  values = (testRunStartTimeAsEpoch, skipped_libs[libname], libname)
  cursor.execute("UPDATE [libversion] SET date = ? WHERE date = ? AND libname = ? AND branch = ? AND confighash = ?", (testRunStartTimeAsEpoch, skipped_libs[libname], libname, branch, confighash))
  cursor.execute("UPDATE [%s] SET date = ? WHERE date = ? AND libname = ?" % branch, values)
"""

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
    return os.path.isfile(os.path.normpath(fpath)) and os.path.getsize(os.path.normpath(fpath)) > 0

def cpu_name():
  if isWin:
    return processor()
  else:
    for line in open("/proc/cpuinfo").readlines():
      if "model name" in line.strip():
        return (re.sub( ".*model name.*:", "", line,1)).strip()

if isWin:
  lsb_release = ""
else:
  try:
    lsb_release = subprocess.check_output(commands + ["cat","/etc/lsb-release"]).decode().strip()
    lsb_release = dict(a.split("=") for a in lsb_release.split("\n"))["DISTRIB_DESCRIPTION"].strip('"')
  except:
    lsb_release = ""

sysInfo = "%s, %d GB RAM, %s%s" % (cpu_name(), int(math.ceil(psutil.virtual_memory().total / (1024.0**3))), ("Docker " + docker + " ") if docker else "", lsb_release)

# create target dir to move results without sync operations (win or when --noSync is used)
resRootPath = os.path.join(result_location, branch)
if result_location != "" and (isWin or noSync):
  if os.path.exists(resRootPath):
    rmtree(resRootPath)
  os.mkdir(resRootPath)

htmltpl=open("library.html.tpl").read()
for libname in stats_by_libname.keys():
  if libname in skipped_libs:
    continue
  s = None # Make sure I don't use this
  filesList = open(libname + ".files", "w")
  filesList.write("/\n")
  filesList.write("/%s.html\n" % libname)
  filesList.write("/files/\n")
  conf = stats_by_libname[libname]["conf"]
  stats = stats_by_libname[libname]["stats"]
  for s in stats:
    filename_prefix = "files/%s_%s" % (s[2],s[1])
    filesList.write("/%s*diff*csv\n" % filename_prefix)
    filesList.write("/%s*diff*html\n" % filename_prefix)
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
  testsHTML = "\n".join(['<tr><td>%s%s</td><td bgcolor="%s">%s</td><td bgcolor="%s">%s</td><td bgcolor="%s">%s</td><td>%s</td><td bgcolor="%s">%s</td><td bgcolor="%s">%s</td><td bgcolor="%s">%s</td><td bgcolor="%s">%s</td><td bgcolor="%s">%s</td><td>%s</td></tr>\n' %
    (lambda filename_prefix, diff:
      (
      ('<a href="%s">%s</a>' % (filename_prefix + ".err", html.escape(s[1]))) if is_non_zero_file(filename_prefix + ".err") else html.escape(s[1]),
      (' (<a href="%s">sim</a>)' % (filename_prefix + ".sim")) if is_non_zero_file(filename_prefix + ".sim") else "",
      checkPhase(s[3]["phase"], 7) if s[3]["phase"]>=6 else "#FFFFFF",
      ("%s (%d verified)" % (timeSeconds(diff.get("time")), diff.get("numCompared"))) if s[3]["phase"]>=7 else ("&nbsp;" if diff is None else
      ('%s (<a href="%s.diff.html">%d/%d failed</a>)' % (timeSeconds(diff.get("time")), filename_prefix, len(diff.get("vars")), diff.get("numCompared")))),
      checkPhase(s[3]["phase"], 6),
      timeSeconds(s[3].get("sim") or 0),
      checkPhase(s[3]["phase"], 5),
      timeSeconds(sum(s[3].get(x) or 0.0 for x in ["frontend","backend","simcode","templates","build"])),
      timeSeconds(s[3].get("parsing") or 0),
      checkPhase(s[3]["phase"], 1),
      timeSeconds(s[3].get("frontend") or 0),
      checkPhase(s[3]["phase"], 2),
      timeSeconds(s[3].get("backend") or 0),
      checkPhase(s[3]["phase"], 3),
      timeSeconds(s[3].get("simcode") or 0),
      checkPhase(s[3]["phase"], 4),
      timeSeconds(s[3].get("templates") or 0),
      checkPhase(s[3]["phase"], 5),
      timeSeconds(s[3].get("build") or 0),
      timeSeconds(s[3].get("exectime") or 0)
    ))(filename_prefix="files/%s_%s" % (s[2], s[1]), diff=s[3].get("diff"))
    for s in natsorted(stats, key=lambda s: s[1])])
  numSucceeded = [len(stats)] + [sum(1 if s[3]["phase"]>=i else 0 for s in stats) for i in range(1,8)]

  try:
    githuburltesting = "https://github.com/OpenModelica/OpenModelicaLibraryTesting/commit/"
    gitloglibrarytesting = subprocess.check_output(["git", "log", '--pretty=<table><tr><th>Commit</th><th>Date</th><th>Author</th><th>Summary</th></tr><tr><td><a href="%s/%%h">%%h</a></td><td>%%ai</td><td>%%an</td><td>%%s</td></tr></table>' % (githuburltesting), "-1"], cwd="./").decode("utf-8")
  except subprocess.CalledProcessError as e:
    print(str(e))
    gitloglibrarytesting = "<table><tr><td>could not get the git log for OpenModelicaLibraryTesting</td></tr></table>"

  replacements = (
    (u"#sysInfo#", html.escape(sysInfo)),
    (u"#omcVersion#", html.escape(omc_version)),
    (u"#fmi#", ("<p>"+html.escape("FMI version: %s" % conf.get("fmi"))+"</p>") if conf.get("fmi") else ""),
    (u"#optlevel#", html.escape(conf.get("optlevel")) if (canChangeOptLevel and conf.get("optlevel")) else "Tool default"),
    (u"#timeStart#", html.escape(time.strftime('%Y-%m-%d %H:%M:%S', start_as_time))),
    (u"#fileName#", html.escape(libname)),
    (u"#customCommands#", html.escape("\n".join(conf["customCommands"]))),
    (u"#libraryVersionRevision#", html.escape(conf["libraryVersionRevision"])),
    (u"#OpenModelicaLibraryTesting#", gitloglibrarytesting),
    (u"#metadata#", html.escape(conf["metadata"])),
    (u"#ulimitOmc#", html.escape(str(conf["ulimitOmc"]))),
    (u"#ulimitExe#", html.escape(str(conf["ulimitExe"]))),
    (u"#default_tolerance#", html.escape(str(conf["default_tolerance"]))),
    (u"#simFlags#", html.escape(conf.get("simFlags") or "")),
    (u"#referenceFiles#", ('<p>Reference Files: %s</p>' % conf["referenceFilesURL"].replace(os.path.dirname(os.path.realpath(__file__)),"")) if ((conf.get("referenceFilesURL") or "") != "") else ""),
    (u"#referenceTool#", ('<p>Verified using: %s (diffSimulationResults)</p>' % html.escape(ompython_omc_version)) if ((conf.get("referenceFiles") or "") != "") else ""),
    (u"#Total#", html.escape(str(numSucceeded[0]))),
    (u"#FrontendColor#", checkNumSucceeded(numSucceeded, 1)),
    (u"#BackendColor#", checkNumSucceeded(numSucceeded, 2)),
    (u"#SimCodeColor#", checkNumSucceeded(numSucceeded, 3)),
    (u"#TemplatesColor#", checkNumSucceeded(numSucceeded, 4)),
    (u"#CompilationColor#", checkNumSucceeded(numSucceeded, 5)),
    (u"#SimulationColor#", checkNumSucceeded(numSucceeded, 6)),
    (u"#VerificationColor#", checkNumSucceeded(numSucceeded, 7)),
    (u"#Frontend#", html.escape(str(numSucceeded[1]))),
    (u"#Backend#", html.escape(str(numSucceeded[2]))),
    (u"#SimCode#", html.escape(str(numSucceeded[3]))),
    (u"#Templates#", html.escape(str(numSucceeded[4]))),
    (u"#Compilation#", html.escape(str(numSucceeded[5]))),
    (u"#Simulation#", html.escape(str(numSucceeded[6]))),
    (u"#Verification#", html.escape(str(numSucceeded[7]))),
    (u"#totalTime#", html.escape(str(datetime.timedelta(seconds=int(sum(s[3].get("exectime") or 0.0 for s in stats)))))),
    (u"#config#", html.escape(json.dumps(conf["configFromFile"], indent=1, sort_keys=True))),
    (u"#testsHTML#", testsHTML)
  )
  open("%s.html" % libname, "w").write(multiple_replace(htmltpl, *replacements))

  # move results by sync operations (not available under win)
  if result_location != "" and not isWin and not noSync:
    result_location_libname = "%s/%s" % (result_location, libname)
    try:
      os.mkdir("emptydir")
    except:
      pass
    subprocess.check_output(["rsync", "-aR", "emptydir/", result_location])
    subprocess.check_output(["rsync", "-aR", "emptydir/", result_location_libname])
    subprocess.check_output(["rsync", "-aR", "emptydir/", result_location_libname+"/files"])
    try:
      subprocess.check_output(["rsync", "-aR", "--delete-excluded", "--include-from=%s.files" % libname, "--exclude=*", "./", result_location_libname])
    except:
      subprocess.check_output(["rsync", "-aR", "emptydir/", result_location])
      subprocess.check_output(["rsync", "-aR", "emptydir/", result_location_libname])
      subprocess.check_output(["rsync", "-aR", "emptydir/", result_location_libname+"/files"])
      subprocess.check_output(["rsync", "-aR", "--delete-excluded", "--include-from=%s.files" % libname, "--exclude=*", "./", result_location_libname])
    if (conf.get("referenceFiles") or "") != "":
      subprocess.check_output(["rsync", "-a", dygraphs, result_location_libname+"/files"])

  # move results without sync operations (win or when --noSync is used)
  if result_location != "" and (isWin or noSync):
    print("--> copy res file of library: " + libname)
    libPath = os.path.join(resRootPath, libname)
    if not os.path.exists(libPath):
      os.makedirs(libPath)
    libFilesPath = os.path.join(libPath, 'files')
    if os.path.exists(libFilesPath):
      rmtree(libFilesPath)
    os.makedirs(libFilesPath)
    try:
      if clean:
        shutil.move("./" + libname + ".html", libPath)
      else:
        shutil.copy2("./" + libname + ".html", libPath)
    except:
      print("-- problem durin copy/move of html file of lib: " + libname)

    for file in glob.glob("./files/" + libname + '*.err') \
              + glob.glob("./files/" + libname + '*.sim') \
              + glob.glob("./files/" + libname + '*.csv') \
              + glob.glob("./files/" + libname + '*.json') \
              + glob.glob("./files/" + libname + '*.html'):
      try:
        print("copy: " + file)
        shutil.copy2(file, libFilesPath)
      except:
        print("-- problem during file copy... maybe the file is still hooked by a process... :" + file)
        pass

if clean:
  for g in ["*.o","*.so","*.h","*.c","*.cpp","*.simsuccess","*.conf.json","*.tmpfiles","*.log","*.libs","OMCpp*","*.fmu*","temp_*", "*.exe", "HelloWorld.bat", "*.makefile", "*.mat","*.xml", "*.bin", "*.json"]:
    for f in glob.glob(g):
      try:
        if os.path.isdir(f):
          rmtree(f)
        elif os.path.exists(f):
          os.unlink(f)
      except:
        print("-- problem during clean of: " + f)
        pass

if clean and (result_location == "" or (not isWin and not noSync)):
  try:
    rmtree("files/")
  except:
    print("-- problemduring removing of ./files dir")

# Do not commit until we have generated and uploaded the reports
conn.commit()
conn.close()

print("all tests done ...")
