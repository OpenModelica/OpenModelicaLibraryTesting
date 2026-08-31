#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import urllib.request, urllib.error, urllib.parse
import codecs
import sys, argparse, subprocess, os, time
import simplejson as json
import shared, resultsdb
import re
from omcommon import friendlyStr

parser = argparse.ArgumentParser(description='OpenModelica model testing report generation tool')
parser.add_argument('branches', nargs='*')
parser.add_argument('--baseurl', default="http://libraries.openmodelica.org/branches")
parser.add_argument('--historyurl', default="http://libraries.openmodelica.org/branches/history")
parser.add_argument('--githuburl', default="https://github.com/OpenModelica/OpenModelica/commit")
parser.add_argument('--githuburltesting', default="https://github.com/OpenModelica/OpenModelicaLibraryTesting/commit")
parser.add_argument('--omcgitdir', default="../OpenModelica/OpenModelica")
parser.add_argument('--email', default=False, action='store_true')
parser.add_argument('--pending', default="pending-reports.json",
                    help="Where to leave this run's reports for publish-reports.py")
resultsdb.addArgument(parser)
args = parser.parse_args()

os.environ['TZ'] = 'Europe/Stockholm'
time.tzset()

branches = [shared.resultTable(branch) for branch in args.branches]
baseurl = args.baseurl
historyurl  = args.historyurl
githuburl = args.githuburl
githuburltesting = args.githuburltesting
omcgitdir = args.omcgitdir
doemail = args.email
pendingfile = args.pending

if not os.path.exists(omcgitdir):
  raise Exception("Could not find OpenModelica.git directory, set it with --omcgitdir. Tried: %s" % omcgitdir)

dates = {}
dates_str = {}
fields = ["exectime", "frontend", "backend", "simcode", "templates", "compile", "simulate", "verify"]
entryhead = "<tr><th>Branch</th><th>Total</th><th>Frontend</th><th>Backend</th><th>SimCode</th><th>Templates</th><th>Compilation</th><th>Simulation</th><th>Verification</th>\n"

timeMinPhase = 4 # Need to have completed code generation to report performance regressions
timeRel = 1.7 # Minimum 1.7x time is registered as a performance regression
timeAbs = 10 # Ignore performance regressions for times <10s...

libs = {}

import time, datetime
from omcommon import friendlyStr, multiple_replace

db = resultsdb.connect(args.db)
db.createHistoryTable()
cursor = db.cursor()

def dateStr(dint):
  return str(datetime.datetime.fromtimestamp(dint).strftime('%Y-%m-%d %H:%M:%S'))

def getTagOrVersion(v):
  v = v.replace("OpenModelica ","").replace("OMCompiler ","")
  v = re.sub(r"-rust$", "", v)
  m = re.search("[+]g([0-9a-f]{7}[0-9a-f]*)$", v)
  if m:
    return m.group(1)
  return v

def libraryLink(branch, libname):
  return '<a href="%s/%s/%s/%s.html">%s</a>' % (baseurl,branch,libname,libname,libname)

def modelLink(libname, modelname, extension, text):
  return '<a href="%s/%s/%s/files/%s_%s.%s">%s</a>' % (baseurl,branch,libname,libname,modelname,extension,text)

# 00_history.html, the index of the reports generated for a branch, lives on the
# web server next to them, and used to be the only record of what had already
# been reported: all-reports.py read it back over HTTP and skipped the branch
# when it could not, because starting from an empty index would have published a
# history with only today's report in it. A branch that had never been published
# had no index either, so its first run reported nothing until the file had been
# created on the server by hand.
#
# The [history] table now holds the same list, one row per report, so the index
# is a rendering of the database rather than the record itself. What the server
# has is still read - it is where the reports generated before the table existed
# are, and they are copied into it - but it is no longer needed to decide what
# has been reported, and a file that is missing, unreadable or out of date is
# rebuilt from the table instead of truncating the history.
#
# That leaves one case with nothing to go on: no rows in the table and no index
# to read, which is either a genuinely new branch or a server that is unwell.
# Two things have to agree before it is taken for a new branch, and anything
# else leaves it alone until a human has looked at it:
#
#  - the history root is served, so the site is up and the index is a missing
#    file rather than a broken deployment or something else answering;
#  - the database holds at most FIRSTREPORT runs of the branch, so the report
#    about to be generated is its first and none can have been lost.
FIRSTREPORT = 2

entryRe = re.compile(r'^<p><a href="[^"]*/(?P<fname>[^/"]+)">[^<]*</a> '
                     r'(?P<improved>\d+) improved, (?P<regressions>\d+) regressions; '
                     r'performance (?P<perfimproved>\d+) improved, '
                     r'(?P<perfregressions>\d+) regressions</p>$')
fnameRe = re.compile(r'^(.+)[.][.](.+)[.]html$')

def epochOf(datestr):
  return int(time.mktime(datetime.datetime.strptime(datestr, "%Y-%m-%d %H:%M:%S").timetuple()))

def parseIndex(text):
  """The reports an index lists, and whatever else it holds, kept verbatim."""
  entries = []
  preamble = []
  for line in text.splitlines():
    if not line.strip():
      continue
    m = entryRe.match(line.strip())
    dates = fnameRe.match(urllib.parse.unquote(m.group("fname"))) if m else None
    try:
      (d1, d2) = (epochOf(dates.group(1)), epochOf(dates.group(2))) if dates else (None, None)
    except ValueError:
      (d1, d2) = (None, None)
    if d1 is None:
      preamble.append(line)
      continue
    entries.append((d1, d2, urllib.parse.unquote(m.group("fname")),
                    int(m.group("improved")), int(m.group("regressions")),
                    int(m.group("perfimproved")), int(m.group("perfregressions"))))
  return (entries, preamble)

def renderEntry(branch, entry):
  """One line of an index; the same line the report generator has always written."""
  (d1, d2, fname, improved, regressions, perfimproved, perfregressions) = entry
  return ('<p><a href="%s/%s/%s">%s %s</a> %d improved, %d regressions; '
          'performance %d improved, %d regressions</p>'
          % (historyurl, branch, fname.replace(" ", "%20"), branch, fname,
             improved, regressions, perfimproved, perfregressions))

def renderIndex(branch, entries, preamble):
  return "".join(line + "\n" for line in preamble + [renderEntry(branch, e) for e in entries])

# The reports generated by this run. A row in [history] means the report is
# never generated again, so publish-reports.py writes them once they are up.
pending_entries = {}

def storedEntries(branch):
  """The reports there are for a branch, oldest first."""
  stored = [tuple(row) for row in cursor.execute(
      "SELECT date1,date2,fname,improved,regressions,perfimproved,perfregressions "
      "FROM history WHERE %s ORDER BY date1,date2" % db.likeNoCase("branch"), (branch,))]
  return sorted(stored + pending_entries.get(branch, []))

historyRootServed = None

def historyRootIsServed():
  """Is the server actually serving the history tree right now?"""
  global historyRootServed
  if historyRootServed is None:
    url = historyurl if historyurl.endswith("/") else historyurl + "/"
    try:
      urllib.request.urlopen(url).read()
      historyRootServed = True
    except Exception as e:
      print("%s could not be read (%s)" % (url, e))
      historyRootServed = False
  return historyRootServed

def readPublishedIndex(branch):
  """The index published for a branch, or None when it could not be read."""
  url = "%s/%s/00_history.html" % (historyurl, branch)
  try:
    return urllib.request.urlopen(url).read().decode('utf-8')
  except urllib.error.HTTPError as e:
    if e.code == 404:
      print("%s is not there" % url)
    else:
      print("%s failed to open: %s" % (url, e))
    return None
  except Exception as e:
    print("%s failed to open: %s" % (url, e))
    return None

def historyOf(branch, nruns):
  """What has been reported for a branch: its entries, anything else its index
  holds, and the index as published, or None to leave the branch alone.

  The database decides; the published index is read to fill it in with the
  reports that predate it, and to say whether the two are in step.
  """
  historyindex = "history/%s/00_history.html" % branch
  if os.path.exists(historyindex):
    # Already started in this workspace, either by an earlier invocation or
    # because the branch was named twice; that copy is the newer one.
    with codecs.open(historyindex, "r", encoding="utf-8") as fin:
      published = fin.read()
  else:
    published = readPublishedIndex(branch)
  stored = storedEntries(branch)
  if published is None:
    if stored:
      print("Rebuilding the index of %s from the %d reports in the database"
            % (branch, len(stored)))
      return (stored, [], None)
    if not historyRootIsServed():
      print("Neither the database nor the history root knows about %s; leaving it alone" % branch)
      return None
    if nruns > FIRSTREPORT:
      print("%s has no index and no reports in the database although it has %d runs; "
            "leaving it alone rather than publishing a history with only the newest "
            "report in it" % (branch, nruns))
      return None
    print("Starting a new history for %s" % branch)
    return ([], [], None)
  (entries, preamble) = parseIndex(published)
  known = set((e[0], e[1]) for e in stored)
  missing = [e for e in entries if (e[0], e[1]) not in known]
  if missing:
    print("Copying %d reports of %s from its index into the database" % (len(missing), branch))
    db.insertHistory(branch, missing)
    stored = sorted(stored + missing)
  inindex = set((e[0], e[1]) for e in entries)
  onlyStored = [e for e in stored if (e[0], e[1]) not in inindex]
  if onlyStored:
    print("%d reports of %s are in the database but not in its index, which is "
          "rewritten with all of them" % (len(onlyStored), branch))
  return (stored, preamble, published)

missing_branches = []
emails_to_send = {}
for branch in branches:
  try:
    one = (branch,) if db.tableExists(branch) else None
    if one == None:
      print("No such table '%s'; specify it using --branch=XXX when running test.py" % branch)
      # ignore this table and continue
      missing_branches.append(branch)
      continue
    else:
      v = one[0]
  except:
    #raise Exception("No such table '%s'; specify it using --branch=XXX" % branch)
    print("No such table '%s'; specify it using --branch=XXX when running test.py" % branch)
    # ignore this table and continue
    missing_branches.append(branch)
    continue

  db.createDateIndex(branch)
  cursor.execute("SELECT date,omcversion FROM omcversion WHERE %s ORDER BY date ASC" % db.likeNoCase("branch"), (branch,))
  entries = cursor.fetchall()
  n = len(entries)
  historydir = "history/%s" % branch
  historyindex = "%s/00_history.html" % historydir
  history = historyOf(branch, n)
  if history is None:
    missing_branches.append(branch)
    continue
  (reports, preamble, published) = history
  reported = set((d1, d2) for (d1, d2, _, _, _, _, _) in reports)

  for i in range(1,n):
    d1 = entries[i-1][0]
    d2 = entries[i][0]
    if (d1, d2) in reported:
      continue
    fname = "history/%s/%s..%s.html" % (branch,dateStr(d1),dateStr(d2))
    print("Generate %s" % fname)
    v1 = getTagOrVersion(entries[i-1][1])
    v2 = getTagOrVersion(entries[i][1])
    thirdPartyChanged = ""
    with open("history.html.tpl") as fin:
      tpl = fin.read()
    emails_current = set(["openmodelicabuilds@ida.liu.se"])
    if v1 != v2:
      try:
        gitlog = subprocess.check_output(["git", "log", '--pretty=<tr><td><a href="%s/%%h">%%h</a></td><td>%%ai</td><td>%%an</td><td>%%s</td></tr>' % (githuburl), "%s..%s" % (v1,v2)], cwd=omcgitdir).decode("utf-8")
        print("Do git ls-tree for %s %s" % (v1,v2))
        try:
          t1 = subprocess.check_output(["git", "ls-tree", v1, "OMCompiler/3rdParty"], cwd=omcgitdir).decode("utf-8").strip().split(" ")[2].split("\t")[0]
          t2 = subprocess.check_output(["git", "ls-tree", v2, "OMCompiler/3rdParty"], cwd=omcgitdir).decode("utf-8").strip().split(" ")[2].split("\t")[0]
          if t1 != t2:
            try:
              tv2 = len(subprocess.check_output(["git", "rev-list", "%s..%s" % (t2,t1)], cwd=omcgitdir+"/OMCompiler/3rdParty").decode("utf-8").strip().split("\n"))
            except subprocess.CalledProcessError as e:
              tv2 = 0
            if tv2 > 0:
              thirdPartyChanged = '<h3>3rdParty changes</h3>Note that the 3rdParty libraries <b>REVERTED TO AN OLD COMMIT</b>: <a href="%s">%s..%s</a>' % (githuburl.replace("OMCompiler/commit", "OMCompiler-3rdParty/compare/%s...%s" % (t2,t1)), t1[:12], t2[:12])
            else:
              thirdPartyChanged = '<h3>3rdParty changes</h3>Note that the 3rdParty libraries changed: <a href="%s">%s..%s</a>' % (githuburl.replace("OMCompiler/commit", "OMCompiler-3rdParty/compare/%s...%s" % (t1,t2)), t1[:12], t2[:12])
        except:
          pass
        for email in [email.strip() for email in subprocess.check_output(["git", "log", '--pretty=%ae', "%s..%s" % (v1,v2)], cwd=omcgitdir).decode("utf-8").split("\n")]:
          if "@" not in email:
            continue
          # adrpo: if email domain doesn't have "." in it, skip it
          if "." not in email[email.find("@"):]:
            continue
          emails_current.add(email)
      except subprocess.CalledProcessError as e:
        print(str(e))
        gitlog = "<tr><td>%s..%s</td></tr>" % (v1,v2)
    else:
      gitlog = ""

    try:
      gitloglibrarytesting = subprocess.check_output(["git", "log", '--pretty=<tr><td><a href="%s/%%h">%%h</a></td><td>%%ai</td><td>%%an</td><td>%%s</td></tr>' % (githuburltesting), "-2"], cwd="./").decode("utf-8")
    except subprocess.CalledProcessError as e:
      print(str(e))
      gitloglibrarytesting = "<tr><td>could not get the git log for OpenModelicaLibraryTesting</td></tr>"

    tpl = tpl.replace("#OMCGITLOG#",gitlog).replace("#NUMCOMMITS#",str(gitlog.count("<tr>"))).replace("#3rdParty#",thirdPartyChanged).replace("#OMCLIBRARYTESTINGGITLOG#",gitloglibrarytesting)
    libnames = [libname for (libname,) in cursor.execute("""SELECT libname FROM %s WHERE date=? GROUP BY libname""" % db.quote(branch), (d2,))]
    startdates = {}
    # Get previous date of each library run and group them together for fast queries later
    for libname in libnames:
      ds = cursor.execute("""SELECT date FROM %s WHERE date<? AND libname=? ORDER BY date DESC LIMIT 1""" % db.quote(branch), (d2,libname)).fetchall()
      if len(ds)==0:
        continue
      ((d1lib,),) = ds
      if d1lib not in startdates:
        startdates[d1lib] = []
      startdates[d1lib] += [libname]
    regressions = []
    for d1lib in startdates.keys():
    # Order by date so we can select and know which is the older and which is the newer value... for finalphase, and the execution times
    # Note: the group concatenation returns both values as a string... So you need to split it
    # later. The order is the one of the dates, which PostgreSQL only guarantees when the
    # aggregate says so, hence the date column in the inner query.
      concat = ",".join(db.groupConcat(c, "date") for c in
                        ["finalphase","frontend","backend","simcode","templates","compile","simulate"])
      query = ("""SELECT model,libname,%s FROM
    (SELECT model,libname,date,finalphase,frontend,backend,simcode,templates,compile,simulate FROM %%s WHERE date IN (?,?) AND libname IN (%%s) ORDER BY date) AS phases
  GROUP BY model,libname HAVING""" % concat + """
    MIN(finalphase) >= 0 AND (
    (MIN(finalphase) <> MAX(finalphase)) OR
    ((MIN(finalphase) >= ?) AND
      (MAX(frontend) > ?*MIN(frontend) AND MAX(frontend) > ?) OR
      (MAX(backend) > ?*MIN(backend) AND MAX(backend) > ?) OR
      (MAX(simcode) > ?*MIN(simcode) AND MAX(simcode) > ?) OR
      (MAX(templates) > ?*MIN(templates) AND MAX(templates) > ?) OR
      (MAX(compile) > ?*MIN(compile) AND MAX(compile) > ?) OR
      (MAX(simulate) > ?*MIN(simulate) AND MAX(simulate) > ?)
    ))
  """) % (db.quote(branch),",".join(["'%s'" % libname for libname in startdates[d1lib]]))
      cursor.execute(query, (d1lib,d2,timeMinPhase,timeRel,timeAbs,timeRel,timeAbs,timeRel,timeAbs,timeRel,timeAbs,timeRel,2*timeAbs,timeRel,timeAbs))
      regressions += cursor.fetchall()
    regressions = sorted(regressions, key = lambda x: (x[1],x[0]))
    libs = set()

    numImproved = 0
    numRegression = 0
    numPerformanceImproved = 0
    numPerformanceRegression = 0
    regstrs = []
    for (model,libname,group,frontend,backend,simcode,templates,compile,simulate) in regressions:
      libs.add(libname)
      (phase1,phase2) = [int(i) for i in group.split(",")]
      color = None
      if phase2 > phase1:
        color = "better"
        numImproved += 1
      if phase2 < phase1:
        color = "warning"
        numRegression += 1
      if color is not None:
        msg = "%s &rarr; %s" % (shared.finalphaseName(phase1),shared.finalphaseName(phase2))
      elif min(phase1,phase2) >= timeMinPhase:
        msgs = []
        for (phase,times) in [(1,frontend),(2,backend),(3,simcode),(4,templates),(5,compile),(6,simulate)]:
          (t1,t2) = [float(d) for d in times.split(",")]
          if t2 > timeRel*t1 and t2 > timeAbs:
            color = "warningPerformance"
            msgs.append("%s performance %s &rarr; %s" % (shared.finalphaseName(phase),friendlyStr(t1),friendlyStr(t2)))
          elif t1 > timeRel*t2 and t1 > timeAbs:
            if color is None:
              color = "betterPerformance"
            msgs.append("%s performance %s &rarr; %s" % (shared.finalphaseName(phase),friendlyStr(t1),friendlyStr(t2)))
        if color is None:
          raise Exception("Unknown regression/improvement...")
        if color == "betterPerformance":
          numPerformanceImproved += 1
        else:
          numPerformanceRegression += 1
        msg = " ".join(msgs)
      else:
        msg = "" # Happens if we try to generate a report without previous results
      regstrs.append('<tr><td>%s</td><td>%s %s</td><td class="%s">%s</td></tr>' % (libraryLink(branch, libname),modelLink(libname, model, "err", model),modelLink(libname, model, "sim", "(sim)"),color,msg))
    tpl = tpl.replace("#NUMIMPROVE#",str(numImproved)).replace("#NUMREGRESSION#",str(numRegression)).replace("#NUMPERFIMPROVE#",str(numPerformanceImproved)).replace("#NUMPERFREGRESSION#",str(numPerformanceRegression)).replace("#MODELCHANGES#", "\n".join(regstrs))
    tpl = tpl.replace("#BRANCH#",branch).replace("#DATE1#",dateStr(d1)).replace("#DATE2#",dateStr(d2))

    libstrs = []
    for libname in sorted(list(libs)):
      cursor.execute("SELECT libversion,confighash FROM libversion WHERE %s AND date<=? AND libname=? ORDER BY date DESC LIMIT 1" % db.likeNoCase("branch"), (branch,d1,libname))
      (lv1,lh1) = cursor.fetchone()
      lv1 = lv1.strip()
      cursor.execute("SELECT libversion,confighash FROM libversion WHERE %s AND date<=? AND libname=? ORDER BY date DESC LIMIT 1" % db.likeNoCase("branch"), (branch,d2,libname))
      (lv2,lh2) = cursor.fetchone()
      lv2 = lv2.strip()
      if lv1 != lv2:
        libstrs.append("<tr><td>%s</td><td>From version %s to %s</td></tr>" % (libraryLink(branch, libname),lv1,lv2))
      elif lh1 != lh2:
        libstrs.append("<tr><td>%s</td><td>Configuration hash (OMC settings or the testing script changed)</td></tr>" % libraryLink(branch, libname))
    tpl = tpl.replace("#LIBCHANGES#","\n".join(libstrs)).replace("#NUMLIBS#",str(len(libstrs)))

    entry = (d1, d2, os.path.basename(fname), numImproved, numRegression,
             numPerformanceImproved, numPerformanceRegression)
    email_summary_html = renderEntry(branch, entry)
    email_summary_plain = '%s/%s/%s: %d improved, %d regressions; performance %d improved, %d regressions</p>' % (historyurl, branch, os.path.basename(fname).replace(" ","%20"), numImproved, numRegression, numPerformanceImproved, numPerformanceRegression)
    if sum([numImproved,numRegression,numPerformanceImproved,numPerformanceRegression])>0:
      for email in emails_current:
        if email not in emails_to_send:
          emails_to_send[email] = {"plain":[],"html":[]}
        emails_to_send[email]["plain"].append(email_summary_plain)
        emails_to_send[email]["html"].append(email_summary_html)
    os.makedirs(historydir, exist_ok=True)
    with codecs.open(fname, "w", encoding="utf-8") as fout:
      fout.write(tpl)
    pending_entries.setdefault(branch, []).append(entry)
    reports = sorted(reports + [entry])

  # The index is written whenever it does not already say what the database
  # says, which covers the reports generated just now, an index that went
  # missing or lost entries, and a branch that has none at all: publishing the
  # directory is what creates it on the server.
  index = renderIndex(branch, reports, preamble)
  if published is None or index != published:
    os.makedirs(historydir, exist_ok=True)
    with codecs.open(historyindex, "w", encoding="utf-8") as fout:
      fout.write(index)

pending = {"entries": {b: [list(e) for e in es] for (b, es) in pending_entries.items() if es},
           "emails": emails_to_send if doemail else {},
           "missing_branches": missing_branches}
with codecs.open(pendingfile, "w", encoding="utf-8") as fout:
  json.dump(pending, fout, indent=1)
print("Generated %d reports, listed in %s for publish-reports.py to record after the upload"
      % (sum(len(es) for es in pending["entries"].values()), pendingfile))
