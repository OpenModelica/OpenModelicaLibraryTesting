#!/usr/bin/env python2
# -*- coding: utf-8 -*-

# TODO: When libraries hash changes, run with the old OMC against the new libs
#       Then run with the new OMC against the new libs

import cgi, shutil, sys, os, re, glob, time, argparse, sqlite3, datetime
from joblib import Parallel, delayed
import simplejson as json
import psutil, subprocess, threading, hashlib
from subprocess import call
from monotonic import monotonic
from omcommon import friendlyStr, multiple_replace

def runCommand(cmd, prefix, timeout):
  process = [None]
  def target():
    with open(os.devnull, 'w')  as FNULL:
      process[0] = subprocess.Popen(cmd, shell=True, stdout=FNULL, stderr=subprocess.STDOUT)
      process[0].communicate()

  thread = threading.Thread(target=target)
  thread.start()
  thread.join(timeout)

  if thread.is_alive():
    parent = psutil.Process(process[0].pid)
    killedSome = False
    for child in parent.children(recursive=True):
      print("Timeout, killing %s: %s" % (cmd, child.name()))
      try:
        child.kill()
        killedSome = True
      except:
        pass
    if killedSome:
      thread.join(min(10, timeout))
    if thread.is_alive():
      for child in parent.children(recursive=True):
        try:
          print("Timeout, killing %s: %s" % (cmd, child.name()))
          child.kill()
        except:
          pass
      try:
        process[0].terminate()
      except:
        pass
    thread.join()

  try:
    lines = open("%s.tmpfiles" % prefix).readlines()
  except:
    lines = []
  for suffix in ["_*.o","_*.so","_*.h","_*.c","_*.cpp",".mos","",".c",".cpp","_info.json","_*.xml","_*.tmpfiles","_res.*"]:
    for f in glob.glob(prefix+suffix):
      lines.append(f)
    for f in glob.glob("OM"+prefix+suffix):
      lines.append(f)
  for line in lines:
    try:
      os.unlink(line.strip())
    except:
      pass
      #print("Failed to unlink: %s" % line.strip())

  return process[0].returncode

try:
  subprocess.check_output(["./testmodel.py", "--help"], stderr=subprocess.STDOUT)
except subprocess.CalledProcessError as e:
  print("Sanity check failed (./testmodel.py --help):\n" + e.output)
  sys.exit(1)

parser = argparse.ArgumentParser(description='OpenModelica library testing tool')
parser.add_argument('configs', nargs='*')
parser.add_argument('--branch', default='master')
parser.add_argument('--output', default='')
parser.add_argument('--ompython_omhome', default='')
parser.add_argument('-n', default=psutil.cpu_count(logical=False))

args = parser.parse_args()
configs = args.configs
branch = args.branch
result_location = args.output
n_jobs = args.n
ompython_omhome = args.ompython_omhome
print("branch: %s, n_jobs: %d" % (branch, n_jobs))

if result_location != "" and not os.path.exists(result_location):
  os.makedirs(result_location)

if configs == []:
  print("Error: Expected at least one configuration file to start the library test")
  sys.exit(1)

from OMPython import OMCSession

version_cmd = "--version"
single_thread="-n=1"
rmlStyle=False

if ompython_omhome != "":
  # Use a different OMC for running OMPython than for running the tests
  omhome = os.environ["OPENMODELICAHOME"]
  try:
    omc_version = subprocess.check_output(["%s/bin/omc" % omhome, "--version"], stderr=subprocess.STDOUT).strip()
  except:
    omc_version = subprocess.check_output(["%s/bin/omc" % omhome, "+version"], stderr=subprocess.STDOUT).strip()
    version_cmd = "+version"
    rmlStyle=True
    print("Work-around for RML-style command-line arguments (+version)")
  os.environ["OPENMODELICAHOME"] = ompython_omhome
  omc = OMCSession()
  os.environ["OPENMODELICAHOME"] = omhome
else:
  omc = OMCSession()
  omhome=omc.sendExpression('getInstallationDirectoryPath()')
  omc_version=omc.sendExpression('getVersion()')

omc.sendExpression('setModelicaPath("%s/lib/omlibrary")' % omhome)
omc_exe=os.path.join(omhome,"bin","omc")
dygraphs=os.path.join(omhome,"share","doc","omc","testmodels","dygraph-combined.js")
print(omc_exe,omc_version,dygraphs)

# Do feature checks. Handle things like old RML-style arguments...

try:
  subprocess.check_output(["%s/bin/omc" % omhome, "-n=1", version_cmd], stderr=subprocess.STDOUT).strip()
  single_thread="-n=1"
except:
  subprocess.check_output(["%s/bin/omc" % omhome, "+n=1", version_cmd], stderr=subprocess.STDOUT).strip()
  single_thread="+n=1"
  rmlStyle=True
  print("Work-around for RML-style command-line arguments (+n=1)")

def simulationAcceptsFlag(f):
  try:
    os.unlink("HelloWorld_res.mat")
  except OSError:
    pass
  try:
    subprocess.check_output("./HelloWorld %s" % f, shell=True, stderr=subprocess.STDOUT)
    if os.path.exists("HelloWorld_res.mat"):
      return True
  except subprocess.CalledProcessError as e:
    pass
  return False

try:
  os.unlink("HelloWorld")
except OSError:
  pass
print(subprocess.check_output(["%s/bin/omc" % omhome, "HelloWorld.mos"], stderr=subprocess.STDOUT))
assert(os.path.exists("HelloWorld"))
abortSimulationFlag="-abortSlowSimulation" if simulationAcceptsFlag("-abortSlowSimulation") else ""
alarmFlag="-alarm" if simulationAcceptsFlag("-alarm=480") else ""

try:
  os.unlink("HelloWorld")
except OSError:
  pass
subprocess.check_output(["%s/bin/omc" % omhome, "%ssimCodeTarget=Cpp" % ("+" if rmlStyle else "--"), "HelloWorld.mos"], stderr=subprocess.STDOUT)
if os.path.exists("HelloWorld"):
  haveCppRuntime=simulationAcceptsFlag("")
else:
  haveCppRuntime=False

defaultCustomCommands = []
debug = "+d" if rmlStyle else "-d"
helloWorldContents = open("HelloWorld.mos").read()
for cmd in [
  'setCommandLineOptions("%s=nogen");' % debug,
  'setCommandLineOptions("%s=initialization);' % debug,
  'setCommandLineOptions("%s=backenddaeinfo);' % debug,
  'setCommandLineOptions("%s=discreteinfo);' % debug,
  'setCommandLineOptions("%s=stateselection);' % debug,
  'setCommandLineOptions("%s=execstat");' % debug,
  'setMatchingAlgorithm("PFPlusExt");',
  'setIndexReductionMethod("dynamicStateSelection");'
]:
  try:
    os.unlink("HelloWorld")
  except OSError:
    pass
  open("HelloWorld.cmd.mos","w").write(cmd + "\n" + helloWorldContents)
  try:
    out=subprocess.check_output(["%s/bin/omc" % omhome, "HelloWorld.cmd.mos"], stderr=subprocess.STDOUT)
    if os.path.exists("HelloWorld") and not "Error:" in out:
      defaultCustomCommands.append(cmd)
  except subprocess.CalledProcessError as e:
    pass

from shared import readConfig
import shared

configs_lst = [readConfig(c, rmlStyle=rmlStyle, abortSimulationFlag=abortSimulationFlag, alarmFlag=alarmFlag, defaultCustomCommands=defaultCustomCommands) for c in configs]
configs = []
for c in configs_lst:
  configs = configs + c

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
# Set user_version to the current schema
cursor.execute("PRAGMA user_version=3")

def strToHashInt(s):
  return int(hashlib.sha1(s+"fixCorruptBuilds-2017-02-23v4").hexdigest()[0:8],16)

stats_by_libname = {}
skipped_libs = {}
tests=[]
for (library,conf) in configs:
  confighash = strToHashInt(str(conf))
  conf["confighash"] = confighash
  conf["omhome"] = omhome
  conf["single_thread_cmd"] = single_thread
  conf["haveCppRuntime"] = haveCppRuntime
  if not (omc.sendExpression('setCommandLineOptions("-g=Modelica")') or omc.sendExpression('setCommandLineOptions("+g=Modelica")')):
    print("Failed to set Modelica grammar")
    sys.exit(1)
  omc.sendExpression('clear()')
  if not omc.sendExpression('loadModel(%s,{"%s"})' % (library,conf["libraryVersion"])):
    try:
      print("Failed to load library %s %s: %s" % (library,conf["libraryVersion"],omc.sendExpression('OpenModelica.Scripting.getErrorString()')))
    except:
      print("Failed to load library %s %s. OpenModelica.Scripting.getErrorString() failed..." % (library,conf["libraryVersion"]))
    sys.exit(1)
  if not (omc.sendExpression('setCommandLineOptions("-g=MetaModelica")') or omc.sendExpression('setCommandLineOptions("+g=Modelica")')):
    print("Failed to set MetaModelica grammar")
    sys.exit(1)
  try:
    conf["resourceLocation"]=omc.sendExpression('uriToFilename("modelica://%s/Resources")' % library)[0]
  except:
    conf["resourceLocation"]=""

  conf["libraryVersionRevision"]=omc.sendExpression('getVersion(%s)' % library)
  conf["libraryLastChange"]="" # TODO: FIXME
  librarySourceFile=omc.sendExpression('getSourceFile(%s)' % library)
  lastChange=(librarySourceFile[:-3]+".last_change") if not librarySourceFile.endswith("package.mo") else (os.path.dirname(librarySourceFile)+".last_change")
  if os.path.exists(lastChange):
    conf["libraryLastChange"] = " %s (revision %s)" % (conf["libraryVersionRevision"],"\n".join(open(lastChange).readlines()).strip())
  res=omc.sendExpression('{c for c guard isExperiment(c) and not regexBool(typeNameString(x), "^Modelica_Synchronous\\.WorkInProgress") in getClassNames(%s, recursive=true)}' % library)
  libName=shared.libname(library, conf)
  v = cursor.execute("""SELECT date,libversion,libname,branch,omcversion FROM [libversion] NATURAL JOIN [omcversion]
  WHERE libversion=? AND libname=? AND branch=? AND omcversion=? AND confighash=? ORDER BY date DESC LIMIT 1""", (conf["libraryLastChange"],libName,branch,omc_version,confighash)).fetchone()
  if v is None:
    stats_by_libname[libName] = {"conf":conf, "stats":[]}
    tests = tests + [(r,library,libName,libName+"_"+r,conf) for r in res]
  else:
    print("Skipping %s as we already have results for it: %s" % (libName,str(v)))
    skipped_libs[libName] = v[0]

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
    (u"#referenceFiles#", str(conf.get("referenceFiles") or "")),
    (u"#referenceFileNameDelimiter#", conf["referenceFileNameDelimiter"]),
    (u"#referenceFileExtension#", conf["referenceFileExtension"]),
  )
  with open(name + ".conf.json", 'w') as fp:
    json.dump(dict(conf.items()+{"library":library, "modelName":modelName, "fileName":name}.items()), fp)

def runScript(c, timeout, memoryLimit):
  j = "files/%s.stat.json" % c
  try:
    os.remove(j)
  except:
    pass
  start=monotonic()
  # runCommand("%s %s %s.mos" % (omc_exe, single_thread, c), prefix=c, timeout=timeout)
  if 0 != runCommand("ulimit -v %d; ./testmodel.py --ompython_omhome=%s %s.conf.json > files/%s.cmdout 2>&1" % (memoryLimit, ompython_omhome, c, c), prefix=c, timeout=timeout):
    print("files/%s.err" % c)
    with open("files/%s.err" % c, "a+") as errfile:
      errfile.write("Failed to read output from testmodel.py, exit status != 0:\n")
      try:
        with open("files/%s.cmdout" % c) as cmdout:
          errfile.write(cmdout.read())
      except OSError:
        pass
  try:
    os.unlink("files/%s.cmdout" % c)
  except OSError:
    pass

  execTime=monotonic()-start
  assert(execTime >= 0.0)
  if os.path.exists(j):
    data=json.load(open(j))
    data["exectime"] = execTime
    json.dump(data, open(j,"w"))
  else:
    data = {"exectime":execTime,"phase":0}
    json.dump(data, open(j,"w"))

def expectedExec(c):
  (model,lib,libName,name,data) = c
  cursor.execute("SELECT exectime FROM [%s] WHERE libname = ? AND model = ? ORDER BY date DESC LIMIT 1" % branch, (libName,model))
  v = cursor.fetchone()
  return (v or (0.0,))[0]

tests=sorted(tests, key=lambda c: expectedExec(c), reverse=True)

# Cleanup old runs
try:
  shutil.rmtree("./files")
except OSError:
  pass
try:
  os.mkdir("files")
except OSError:
  pass

print("Starting execution of %d tests" % len(tests))
cmd_res=[0]
start=monotonic()
start_as_time=time.localtime()
testRunStartTimeAsEpoch = int(time.time())
cmd_res=Parallel(n_jobs=n_jobs)(delayed(runScript)(name, 1.1*data["ulimitOmc"]+1.1*data["ulimitExe"], data["ulimitMemory"]) for (model,lib,libName,name,data) in tests)
stop=monotonic()
print("Execution time: %.2f" % (stop-start))
assert(stop-start >= 0.0)

#if max(cmd_res) > 0:
#  raise Exception("A command failed with exit status")

stats=dict([(name,(name,model,libname,json.load(open("files/%s.stat.json" % name)))) for (model,lib,libname,name,conf) in tests])
#for k in sorted(stats.keys(), key=lambda c: stats[c][3]["exectime"], reverse=True):
#  print("%s: exectime %.2f" % (k, stats[k][3]["exectime"]))

for key in stats.keys():
  (name,model,libname,data)=stats[key]
  stats_by_libname[libname]["stats"].append(stats[key])
  values = (testRunStartTimeAsEpoch,
    libname,
    model,
    data.get("exectime") or 0.0,
    data.get("parsing") or 0.0,
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
  cursor.execute("INSERT INTO [%s] VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)" % branch, values)
for libname in stats_by_libname.keys():
  confighash = stats_by_libname[libname]["conf"]["confighash"]
  cursor.execute("INSERT INTO [libversion] VALUES (?,?,?,?,?)", (testRunStartTimeAsEpoch, branch, libname, stats_by_libname[libname]["conf"]["libraryLastChange"], confighash))
cursor.execute("INSERT INTO [omcversion] VALUES (?,?,?)", (testRunStartTimeAsEpoch, branch, omc_version))
for libname in skipped_libs.keys():
  values = (testRunStartTimeAsEpoch, skipped_libs[libname], libname)
  cursor.execute("UPDATE [libversion] SET date = ? WHERE date = ? AND libname = ? AND branch = ? AND confighash = ?", (testRunStartTimeAsEpoch, skipped_libs[libname], libname, branch, confighash))
  cursor.execute("UPDATE [%s] SET date = ? WHERE date = ? AND libname = ?" % branch, values)

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
  s = None # Make sure I don't use this
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
  testsHTML = "\n".join(['<tr><td>%s%s</td><td bgcolor="%s">%s</td><td bgcolor="%s">%s</td><td bgcolor="%s">%s</td><td>%s</td><td bgcolor="%s">%s</td><td bgcolor="%s">%s</td><td bgcolor="%s">%s</td><td bgcolor="%s">%s</td><td bgcolor="%s">%s</td></tr>\n' %
    (lambda filename_prefix, diff:
      (
      ('<a href="%s">%s</a>' % (filename_prefix + ".err", cgi.escape(s[1]))) if is_non_zero_file(filename_prefix + ".err") else cgi.escape(s[1]),
      (' (<a href="%s">sim</a>)' % (filename_prefix + ".sim")) if is_non_zero_file(filename_prefix + ".sim") else "",
      checkPhase(s[3]["phase"], 7) if s[3]["phase"]>=6 else "#FFFFFF",
      ("%s (%d verified)" % (friendlyStr(diff.get("time")), diff.get("numCompared"))) if s[3]["phase"]>=7 else ("&nbsp;" if diff is None else
      ('%s (<a href="%s.diff.html">%d/%d failed</a>)' % (friendlyStr(diff.get("time")), filename_prefix, len(diff.get("vars")), diff.get("numCompared")))),
      checkPhase(s[3]["phase"], 6),
      friendlyStr(s[3].get("sim") or 0),
      checkPhase(s[3]["phase"], 5),
      friendlyStr(sum(s[3].get(x) or 0.0 for x in ["frontend","backend","simcode","templates","build"])),
      friendlyStr(s[3].get("parsing") or 0),
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
    ))(filename_prefix="files/%s_%s" % (s[2], s[1]), diff=s[3].get("diff"))
    for s in sorted(stats, key=lambda s: s[1])])
  numSucceeded = [len(stats)] + [sum(1 if s[3]["phase"]>=i else 0 for s in stats) for i in range(1,8)]
  replacements = (
    (u"#omcVersion#", cgi.escape(omc_version)),
    (u"#timeStart#", cgi.escape(time.strftime('%Y-%m-%d %H:%M:%S', start_as_time))),
    (u"#fileName#", cgi.escape(libname)),
    (u"#customCommands#", cgi.escape("\n".join(conf["customCommands"]))),
    (u"#libraryVersionRevision#", cgi.escape(conf["libraryVersionRevision"])),
    (u"#ulimitOmc#", cgi.escape(str(conf["ulimitOmc"]))),
    (u"#ulimitExe#", cgi.escape(str(conf["ulimitExe"]))),
    (u"#default_tolerance#", cgi.escape(str(conf["default_tolerance"]))),
    (u"#simFlags#", cgi.escape(conf.get("simFlags") or "")),
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
    cmd = ["rsync", "-a", "--delete-excluded", "--include-from=%s.files" % libname, "--exclude=*", "./", "%s/%s" % (result_location, libname)]
    if 0 != call(cmd):
      print("Error: Failed to rsync files: %s" % cmd)
      sys.exit(1)

# Do not commit until we have generated and uploaded the reports
conn.commit()
conn.close()
