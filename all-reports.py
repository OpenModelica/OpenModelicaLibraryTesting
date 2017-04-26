#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys, argparse, subprocess, os
import simplejson as json
import shared
import re
from omcommon import friendlyStr

parser = argparse.ArgumentParser(description='OpenModelica model testing report generation tool')
parser.add_argument('branches', nargs='*')
parser.add_argument('--baseurl', default="http://libraries.openmodelica.org/branches")
parser.add_argument('--historyurl', default="http://libraries.openmodelica.org/branches/history")
parser.add_argument('--historypath', default="/var/www/branches/history")
parser.add_argument('--githuburl', default="https://github.com/OpenModelica/OMCompiler/commit")
parser.add_argument('--omcgitdir', default="../OpenModelica/OMCompiler")
parser.add_argument('--email', default=False, action='store_true')
args = parser.parse_args()

branches = [branch.split("/")[-1] for branch in args.branches]
baseurl = args.baseurl
historyurl  = args.historyurl
githuburl = args.githuburl
omcgitdir = args.omcgitdir
fnameprefix = args.historypath
doemail = args.email

if not os.path.exists(omcgitdir):
  raise Exception("Could not find OMCompiler.git directory, set it with --omcgitdir. Tried: %s" % omcgitdir)

dates = {}
dates_str = {}
fields = ["exectime", "frontend", "backend", "simcode", "templates", "compile", "simulate", "verify"]
entryhead = "<tr><th>Branch</th><th>Total</th><th>Frontend</th><th>Backend</th><th>SimCode</th><th>Templates</th><th>Compilation</th><th>Simulation</th><th>Verification</th>\n"

timeRel = 1.7 # Minimum 1.7x time is registered as a performance regression
timeAbs = 10 # Ignore performance regressions for times <10s...

libs = {}

import cgi, sqlite3, time, datetime
from omcommon import friendlyStr, multiple_replace

conn = sqlite3.connect('sqlite3.db')
cursor = conn.cursor()

def dateStr(dint):
  return str(datetime.datetime.fromtimestamp(dint).strftime('%Y-%m-%d %H:%M:%S'))

def getTagOrVersion(v):
  v = v.replace("OpenModelica ","").replace("OMCompiler ","")
  m = re.search("[+]g([0-9a-f]{7})$", v)
  if m:
    return m.group(1)
  return v

def libraryLink(branch, libname):
  return '<a href="%s/%s/%s/%s.html">%s</a>' % (baseurl,branch,libname,libname,libname)

emails_to_send = {}
for branch in branches:
  try:
    cursor.execute("SELECT name FROM [sqlite_master] WHERE type='table' AND name=?", (branch,))
    v = cursor.fetchone()[0]
  except:
    raise Exception("No such table '%s'; specify it using --branch=XXX" % branch)
  cursor.execute("SELECT date,omcversion FROM [omcversion] WHERE branch=? ORDER BY date ASC", (branch,))
  entries = cursor.fetchall()
  n = len(entries)
  for i in range(1,n):
    d1 = entries[i-1][0]
    d2 = entries[i][0]
    fname = "%s/%s/%s..%s.html" % (fnameprefix,branch,dateStr(d1),dateStr(d2))
    if os.path.exists(fname):
      continue
    v1 = getTagOrVersion(entries[i-1][1])
    v2 = getTagOrVersion(entries[i][1])
    with open("history.html.tpl") as fin:
      tpl = fin.read()
    emails_current = set(["openmodelicabuilds@ida.liu.se"])
    if v1 != v2:
      try:
        gitlog = subprocess.check_output(["git", "log", '--pretty=<tr><td><a href="%s/%%h">%%h</a></td><td>%%an</td><td>%%s</td></tr>' % githuburl, "%s..%s" % (v1,v2)], cwd=omcgitdir).decode("utf-8")
        for email in [email.strip() for email in subprocess.check_output(["git", "log", '--pretty=%ae', "%s..%s" % (v1,v2)], cwd=omcgitdir).decode("utf-8").split("\n")]:
          if "@" not in email:
            continue
          emails_current.add(email)
      except subprocess.CalledProcessError:
        gitlog = "<tr><td>%s..%s</td></tr>" % (v1,v2)
    else:
      gitlog = ""
    tpl = tpl.replace("#OMCGITLOG#",gitlog).replace("#NUMCOMMITS#",str(gitlog.count("<tr>")))
    # Order by date so we can select and know which is the older and which is the newer value... for finalphase, and the execution times
    # Note: GROUP_CONCAT returns both values as a string... So you need to split it later
    cursor.execute("""SELECT model,libname,GROUP_CONCAT(finalphase),GROUP_CONCAT(frontend),GROUP_CONCAT(backend),GROUP_CONCAT(simcode),GROUP_CONCAT(templates),GROUP_CONCAT(compile),GROUP_CONCAT(simulate) FROM
  (SELECT model,libname,finalphase,frontend,backend,simcode,templates,compile,simulate FROM [%s] WHERE date IN (?,?) ORDER BY date)
GROUP BY model,libname HAVING MIN(finalphase) <> MAX(finalphase) OR
  (MAX(frontend) > ?*MIN(frontend) AND MAX(frontend) > ?) OR
  (MAX(backend) > ?*MIN(backend) AND MAX(backend) > ?) OR
  (MAX(simcode) > ?*MIN(simcode) AND MAX(simcode) > ?) OR
  (MAX(templates) > ?*MIN(templates) AND MAX(templates) > ?) OR
  (MAX(compile) > ?*MIN(compile) AND MAX(compile) > ?) OR
  (MAX(simulate) > ?*MIN(simulate) AND MAX(simulate) > ?)
  ORDER BY libname,model
""" % branch, (d1,d2,timeRel,timeAbs,timeRel,timeAbs,timeRel,timeAbs,timeRel,timeAbs,timeRel,2*timeAbs,timeRel,timeAbs))
    regressions = cursor.fetchall()
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
      else:
        msgs = []
        for (phase,times) in [(1,frontend),(2,backend),(3,simcode),(4,templates),(5,compile),(6,simulate)]:
          (t1,t2) = [float(d) for d in times.split(",")]
          if t2 > timeRel*t1 and t2 > timeAbs:
            color = "warning"
            msgs.append("%s performance %s &rarr; %s" % (shared.finalphaseName(phase),friendlyStr(t1),friendlyStr(t2)))
          elif t1 > timeRel*t2 and t1 > timeAbs:
            if color is None:
              color = "better"
            msgs.append("%s performance %s &rarr; %s" % (shared.finalphaseName(phase),friendlyStr(t1),friendlyStr(t2)))
        if color is None:
          raise Exception("Unknown regression/improvement...")
        if color == "better":
          numPerformanceImproved += 1
        else:
          numPerformanceRegression += 1
        msg = " ".join(msgs)
      regstrs.append('<tr><td>%s</td><td>%s</td><td class="%s">%s</td></tr>' % (libraryLink(branch, libname),model,color,msg))
    tpl = tpl.replace("#NUMIMPROVE#",str(numImproved)).replace("#NUMREGRESSION#",str(numRegression)).replace("#NUMPERFIMPROVE#",str(numPerformanceImproved)).replace("#NUMPERFREGRESSION#",str(numPerformanceRegression)).replace("#MODELCHANGES#", "\n".join(regstrs))
    tpl = tpl.replace("#BRANCH#",branch).replace("#DATE1#",dateStr(d1)).replace("#DATE2#",dateStr(d2))

    libstrs = []
    for libname in sorted(list(libs)):
      cursor.execute("SELECT libversion,confighash FROM [libversion] WHERE branch=? AND date<=? AND libname=? ORDER BY date DESC LIMIT 1", (branch,d1,libname))
      (lv1,lh1) = cursor.fetchone()
      lv1 = lv1.strip()
      cursor.execute("SELECT libversion,confighash FROM [libversion] WHERE branch=? AND date<=? AND libname=? ORDER BY date DESC LIMIT 1", (branch,d2,libname))
      (lv2,lh2) = cursor.fetchone()
      lv2 = lv2.strip()
      if lv1 != lv2:
        libstrs.append("<tr><td>%s</td><td>From version %s to %s</td></tr>" % (libraryLink(branch, libname),lv1,lv2))
      elif lh1 != lh2:
        libstrs.append("<tr><td>%s</td><td>Configuration hash (OMC settings or the testing script changed)</td></tr>" % libraryLink(branch, libname))
    tpl = tpl.replace("#LIBCHANGES#","\n".join(libstrs)).replace("#NUMLIBS#",str(len(libstrs)))

    email_summary_html = '<p><a href="%s/%s/%s">%s</a> %d improved, %d regressions; performance %d improved, %d regressions</p>' % (historyurl, branch, os.path.basename(fname).replace(" ","%20"), os.path.basename(fname),numImproved,numRegression,numPerformanceImproved,numPerformanceRegression)
    email_summary_plain = '%s/%s/%s: %d improved, %d regressions; performance %d improved, %d regressions</p>' % (historyurl, branch, os.path.basename(fname).replace(" ","%20"), numImproved, numRegression, numPerformanceImproved, numPerformanceRegression)
    if sum([numImproved,numRegression,numPerformanceImproved,numPerformanceRegression])>0:
      for email in emails_current:
        if email not in emails_to_send:
          emails_to_send[email] = {"plain":[],"html":[]}
        emails_to_send[email]["plain"].append(email_summary_plain)
        emails_to_send[email]["html"].append(email_summary_html)
    if not os.path.exists(os.path.dirname(fname)):
      os.makedirs(os.path.dirname(fname))
    with open(fname, "w") as fout:
      fout.write(tpl)
    if not os.path.exists(os.path.dirname("%s/%s" % (fnameprefix,branch))):
      os.makedirs("%s/%s" % (fnameprefix,branch))
    with open("%s/%s/00_history.html" % (fnameprefix,branch), "a+") as fout:
      fout.write(email_summary_html)
      fout.write("\n")

if not doemail:
  # We are done
  sys.exit(0)

# OK; send the emails :D
import smtplib

from email.message import EmailMessage
from email.headerregistry import Address
from email.utils import make_msgid

for email in sorted(emails_to_send.keys()):
  msg = EmailMessage()
  msg['Subject'] = 'OpenModelica Library Testing Regressions'
  msg['From'] = Address("OM Hudson", "openmodelicabuilds", "ida.liu.se")
  msg['To'] = email
  msg.set_content("""\
The following reports contain regressions your account was involved with:
""" + "\n".join(reversed(emails_to_send[email]["plain"])))
  msg.add_alternative("""\
<html>
<head></head>
<body>
%s
</body>
</html>
""" % "\n".join(reversed(emails_to_send[email]["html"])), subtype='html')
  with smtplib.SMTP('localhost') as s:
    s.send_message(msg)
