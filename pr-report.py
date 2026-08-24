#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Compare a pull request run against a run of another branch.

all-reports.py reports a branch against its own previous run, which is what a
pull request must not do: pr-<N> has no previous run, and the question is not
"what changed since yesterday" but "what does this pull request change against
master". The comparison itself is the same one - the phase a model reached and
what each phase cost - only the two runs it is given come from two branches.
"""

import argparse, codecs, datetime, html, json, os, re, subprocess, time
import urllib.error, urllib.request
import shared, resultsdb
from omcommon import friendlyStr, multiple_replace

parser = argparse.ArgumentParser(description='OpenModelica library testing pull request report')
parser.add_argument('pullrequest', help='the pull request number, or its branch name pr-<N>')
parser.add_argument('--baseline', default="master", help='the branch the pull request is compared against')
parser.add_argument('--date', type=int, default=0, help='the pull request run to report on (default: its newest)')
parser.add_argument('--baselinedate', type=int, default=0, help='the baseline run to compare against (default: its newest)')
parser.add_argument('--baseurl', default="http://libraries.openmodelica.org/branches")
parser.add_argument('--historyurl', default="http://libraries.openmodelica.org/branches/history")
parser.add_argument('--historypath', default="history")
parser.add_argument('--githuburl', default="https://github.com/OpenModelica/OpenModelica")
parser.add_argument('--markdown', default="", help='where to write the summary to comment on the pull request with (default: <historypath>/<branch>/00_comment.md)')
parser.add_argument('--comment', action='store_true', help='post that summary on the pull request, replacing the one posted by an earlier run')
resultsdb.addArgument(parser)
args = parser.parse_args()

os.environ['TZ'] = 'Europe/Stockholm'
time.tzset()

# The same thresholds all-reports.py uses, so that a change reported here means
# what it means in the nightly reports.
timeMinPhase = 4 # Need to have completed code generation to report performance regressions
timeRel = 1.7    # Minimum 1.7x time is registered as a performance regression
timeAbs = 10     # Ignore performance regressions for times <10s...

PHASES = [(1,"frontend"),(2,"backend"),(3,"simcode"),(4,"templates"),(5,"compile"),(6,"simulate")]

m = re.match(r"^(?:pr-)?([0-9]+)$", args.pullrequest.strip())
if not m:
  raise SystemExit("Expected a pull request number or a pr-<N> branch name, got '%s'" % args.pullrequest)
pr = m.group(1)
branch = "pr-%s" % pr
baseline = args.baseline.split("/")[-1]
prurl = "%s/pull/%s" % (args.githuburl, pr)
repo = args.githuburl.split("github.com/")[-1].strip("/")

db = resultsdb.connect(args.db)
cursor = db.cursor()

for tbl in [branch, baseline]:
  if not db.tableExists(tbl):
    raise SystemExit("No results for '%s'; run test.py --branch=%s first" % (tbl, tbl))
  db.createDateIndex(tbl)


def dateStr(dint):
  return str(datetime.datetime.fromtimestamp(dint).strftime('%Y-%m-%d %H:%M:%S'))

def newestRun(table, upto=0):
  """The newest run of a table, or the newest at or before upto."""
  if upto:
    (d,) = cursor.execute("SELECT max(date) FROM %s WHERE date<=?" % db.quote(table), (upto,)).fetchone()
  else:
    (d,) = cursor.execute("SELECT max(date) FROM %s" % db.quote(table)).fetchone()
  return d

def libraries(table, upto):
  return set(l for (l,) in cursor.execute(
      "SELECT DISTINCT libname FROM %s WHERE date<=?" % db.quote(table), (upto,)))

def libraryRun(table, libname, upto):
  """The newest run of one library at or before upto.

  A run does not necessarily hold every library: test.py skips a library whose
  version, compiler and configuration were tested before, so its results stay at
  the date of the run that produced them. Comparing two runs therefore means
  comparing, per library, the newest run each of them has of it.
  """
  (d,) = cursor.execute("SELECT max(date) FROM %s WHERE date<=? AND libname=?"
                        % db.quote(table), (upto, libname)).fetchone()
  return d

# A database written before the machine was recorded, #320, has no host column.
hostColumn = "host" if "host" in db.columns("libversion") else "NULL"

def libraryVersions(table, libname, date):
  """(libversion, confighash, host) of a library in a run."""
  row = cursor.execute(
      "SELECT libversion,confighash,%s FROM libversion WHERE %s AND date=? AND libname=?"
      % (hostColumn, db.likeNoCase("branch")), (table, date, libname)).fetchone()
  return row if row else (None, None, None)

def omcVersion(table, date):
  row = cursor.execute("SELECT omcversion FROM omcversion WHERE %s AND date=?"
                       % db.likeNoCase("branch"), (table, date)).fetchone()
  return row[0].strip() if row and row[0] else "unknown"

def models(table, libname, date):
  return set(mod for (mod,) in cursor.execute(
      "SELECT model FROM %s WHERE date=? AND libname=?" % db.quote(table), (date, libname)))

def changedModels(table1, date1, table2, date2, libnames):
  """The models whose phase or timings differ between the two runs.

  One query per set of libraries that share a pair of dates, as all-reports.py
  does. The values of both runs are aggregated into one string per column,
  ordered by which run they come from rather than by their date: a pull request
  run is normally the newer of the two, but need not be.
  """
  concat = ",".join(db.groupConcat(c, "ord") for c in
                    ["finalphase","frontend","backend","simcode","templates","compile","simulate"])
  cols = "model,libname,finalphase,frontend,backend,simcode,templates,compile,simulate"
  inlibs = ",".join("'%s'" % libname for libname in sorted(libnames))
  query = """SELECT model,libname,%s FROM
    (SELECT * FROM
      (SELECT %s,0 AS ord FROM %s WHERE date=? AND libname IN (%s)
       UNION ALL
       SELECT %s,1 AS ord FROM %s WHERE date=? AND libname IN (%s)) AS runs
     ORDER BY ord) AS phases
  GROUP BY model,libname HAVING
    (MIN(finalphase) <> MAX(finalphase)) OR
    (MIN(finalphase) >= ? AND (
      (MAX(frontend) > ?*MIN(frontend) AND MAX(frontend) > ?) OR
      (MAX(backend) > ?*MIN(backend) AND MAX(backend) > ?) OR
      (MAX(simcode) > ?*MIN(simcode) AND MAX(simcode) > ?) OR
      (MAX(templates) > ?*MIN(templates) AND MAX(templates) > ?) OR
      (MAX(compile) > ?*MIN(compile) AND MAX(compile) > ?) OR
      (MAX(simulate) > ?*MIN(simulate) AND MAX(simulate) > ?)))
  """ % (concat, cols, db.quote(table1), inlibs, cols, db.quote(table2), inlibs)
  cursor.execute(query, (date1, date2, timeMinPhase,
                         timeRel, timeAbs, timeRel, timeAbs, timeRel, timeAbs,
                         timeRel, timeAbs, timeRel, 2*timeAbs, timeRel, timeAbs))
  return cursor.fetchall()


prdate = newestRun(branch, args.date)
if not prdate:
  raise SystemExit("No results for %s%s" % (branch, " at or before %d" % args.date if args.date else ""))
basedate = newestRun(baseline, args.baselinedate)
if not basedate:
  raise SystemExit("No results for %s%s" % (baseline, " at or before %d" % args.baselinedate if args.baselinedate else ""))

prlibs = libraries(branch, prdate)
baselibs = libraries(baseline, basedate)
libnames = sorted(prlibs & baselibs)
if not libnames:
  raise SystemExit("%s and %s have no library in common" % (branch, baseline))

# Per library the newest run each side has of it, grouped by the pair of dates
# so that one query covers every library that shares it.
groups = {}
prlibdates = {}
baselibdates = {}
for libname in libnames:
  d1 = libraryRun(baseline, libname, basedate)
  d2 = libraryRun(branch, libname, prdate)
  baselibdates[libname] = d1
  prlibdates[libname] = d2
  groups.setdefault((d1, d2), []).append(libname)

changes = []
for ((d1, d2), libs) in sorted(groups.items()):
  changes += changedModels(baseline, d1, branch, d2, libs)
changes = sorted(changes, key=lambda x: (x[1], x[0]))

# Models one of the runs has and the other does not: a library that grew a model,
# or one whose test did not run at all. They cannot be compared, but leaving them
# out of the report without saying so would hide a library that failed to load.
onlyPr = []
onlyBaseline = []
numCompared = 0
for libname in libnames:
  inpr = models(branch, libname, prlibdates[libname])
  inbase = models(baseline, libname, baselibdates[libname])
  onlyPr += [(libname, mod) for mod in sorted(inpr - inbase)]
  onlyBaseline += [(libname, mod) for mod in sorted(inbase - inpr)]
  numCompared += len(inpr & inbase)


def modelLink(table, libname, modelname, extension, text):
  return '<a href="%s/%s/%s/files/%s_%s.%s">%s</a>' % (
      args.baseurl, table, libname, libname, modelname, extension, html.escape(text))

def libraryLink(table, libname):
  return '<a href="%s/%s/%s/%s.html">%s</a>' % (args.baseurl, table, libname, libname, html.escape(libname))

def classify(group, times):
  """(colour, message) for a model, in the terms all-reports.py uses."""
  (phase1, phase2) = [int(i) for i in group.split(",")]
  if phase2 != phase1:
    better = phase2 > phase1
    return ("better" if better else "warning",
            "%s &rarr; %s" % (shared.finalphaseName(phase1), shared.finalphaseName(phase2)),
            "improved" if better else "regression")
  msgs = []
  colour = None
  for ((phase, name), values) in zip(PHASES, times):
    (t1, t2) = [float(d) for d in values.split(",")]
    limit = 2*timeAbs if name == "compile" else timeAbs
    if t2 > timeRel*t1 and t2 > limit:
      colour = "warningPerformance"
      msgs.append("%s performance %s &rarr; %s" % (shared.finalphaseName(phase), friendlyStr(t1), friendlyStr(t2)))
    elif t1 > timeRel*t2 and t1 > limit:
      if colour is None:
        colour = "betterPerformance"
      msgs.append("%s performance %s &rarr; %s" % (shared.finalphaseName(phase), friendlyStr(t1), friendlyStr(t2)))
  if colour is None:
    # Both runs are below timeMinPhase, or the difference is under the threshold
    # in the direction the query did not test for.
    return (None, "", None)
  return (colour, " ".join(msgs),
          "performance improved" if colour == "betterPerformance" else "performance regression")

# A run of the same pull request replaces the comment of the one before it
# rather than adding to a pile; this is how it recognises its own.
COMMENTMARKER = "<!-- openmodelica-library-testing: pull request report -->"

def githubToken():
  """A token to post with: the environment, or whoever gh is logged in as."""
  for var in ["GITHUB_TOKEN", "GH_TOKEN"]:
    if os.environ.get(var):
      return os.environ[var]
  try:
    return subprocess.check_output(["gh", "auth", "token"],
                                   stderr=subprocess.DEVNULL).decode("utf-8").strip()
  except Exception:
    return None

def github(url, token, data=None, method=None):
  request = urllib.request.Request(
      url, method=method,
      data=json.dumps(data).encode("utf-8") if data is not None else None,
      headers={"Accept": "application/vnd.github+json",
               "Authorization": "Bearer %s" % token,
               "Content-Type": "application/json"})
  return json.loads(urllib.request.urlopen(request).read().decode("utf-8"))

def postComment(number, body):
  """Post the summary on the pull request, or update the one already there."""
  token = githubToken()
  if not token:
    return ("No token to comment with: set GITHUB_TOKEN, or log in with gh. "
            "The comment is in %s." % markdownname)
  api = "https://api.github.com/repos/%s/issues" % repo
  try:
    page = 1
    while True:
      comments = github("%s/%s/comments?per_page=100&page=%d" % (api, number, page), token)
      for comment in comments:
        if COMMENTMARKER in (comment.get("body") or ""):
          github(comment["url"], token, {"body": body}, method="PATCH")
          return "Updated %s" % comment["html_url"]
      if len(comments) < 100:
        break
      page += 1
    return "Commented on %s" % github("%s/%s/comments" % (api, number), token,
                                      {"body": body})["html_url"]
  except urllib.error.HTTPError as e:
    raise SystemExit("Could not comment on %s#%s: %s\n%s"
                     % (repo, number, e, e.read().decode("utf-8", "replace")))

counts = {"improved": 0, "regression": 0, "performance improved": 0, "performance regression": 0}
rows = []
markdownrows = []
for (model, libname, group, frontend, backend, simcode, templates, compile, simulate) in changes:
  (colour, msg, kind) = classify(group, [frontend, backend, simcode, templates, compile, simulate])
  if kind is None:
    continue
  counts[kind] += 1
  rows.append('<tr><td>%s</td><td>%s %s %s</td><td class="%s">%s</td></tr>'
              % (libraryLink(branch, libname),
                 modelLink(branch, libname, model, "err", model),
                 modelLink(branch, libname, model, "sim", "(sim)"),
                 modelLink(baseline, libname, model, "err", "(%s)" % baseline),
                 colour, msg))
  markdownrows.append((libname, model, msg.replace("&rarr;", "->")))

# What makes a difference mean something other than "the pull request did this".
caveats = []
prhosts = set()
basehosts = set()
libchanges = []
for libname in libnames:
  (lv1, lh1, host1) = libraryVersions(baseline, libname, baselibdates[libname])
  (lv2, lh2, host2) = libraryVersions(branch, libname, prlibdates[libname])
  prhosts.add(host2 or "unknown")
  basehosts.add(host1 or "unknown")
  if (lv1 or "").strip() != (lv2 or "").strip():
    libchanges.append("<tr><td>%s</td><td>Version %s in %s, %s in %s</td></tr>"
                      % (libraryLink(branch, libname), html.escape((lv1 or "").strip()), baseline,
                         html.escape((lv2 or "").strip()), branch))
  elif lh1 != lh2:
    libchanges.append("<tr><td>%s</td><td>Configuration hash (OMC settings, the testing script or a "
                      "reference file changed)</td></tr>" % libraryLink(branch, libname))

if prhosts != basehosts:
  caveats.append("The two runs were produced on different machines (%s against %s), so the timings "
                 "compare the hardware as much as the pull request. The phases a model reaches are "
                 "still comparable." % (", ".join(sorted(prhosts)), ", ".join(sorted(basehosts))))
if libchanges:
  caveats.append("%d of the %d libraries were not tested in the same version, or not with the same "
                 "configuration and reference files, in the two runs; see Library Changes below."
                 % (len(libchanges), len(libnames)))
if prlibs - baselibs:
  caveats.append("%d libraries of the pull request run have no counterpart in the baseline run: %s."
                 % (len(prlibs - baselibs), ", ".join(sorted(prlibs - baselibs))))
if baselibs - prlibs:
  caveats.append("%d libraries of the baseline run were not tested by the pull request run: %s."
                 % (len(baselibs - prlibs), ", ".join(sorted(baselibs - prlibs))))
# Always true, and in the report itself rather than among the caveats.
note = ("The baseline is the newest run of %s, not the commit the pull request is based on, so a "
        "difference can also come from something merged into %s since the pull request was "
        "branched." % (baseline, baseline))

reportname = "%s..%s.html" % (dateStr(basedate), dateStr(prdate))
historydir = os.path.join(args.historypath, branch)
os.makedirs(historydir, exist_ok=True)

with open("pr.html.tpl") as fin:
  tpl = fin.read()
tpl = multiple_replace(tpl,
  ("#PRURL#", prurl),
  ("#PR#", pr),
  ("#BRANCH#", branch),
  ("#BASELINE#", html.escape(baseline)),
  ("#CAVEATS#", "\n".join('<p class="caveat">%s</p>' % c for c in caveats)),
  ("#DATE1#", dateStr(basedate)),
  ("#DATE2#", dateStr(prdate)),
  ("#OMCVERSION1#", html.escape(omcVersion(baseline, basedate))),
  ("#OMCVERSION2#", html.escape(omcVersion(branch, prdate))),
  ("#HOST1#", html.escape(", ".join(sorted(basehosts)))),
  ("#HOST2#", html.escape(", ".join(sorted(prhosts)))),
  ("#NUMCOMPARED#", str(numCompared)),
  ("#NUMIMPROVE#", str(counts["improved"])),
  ("#NUMREGRESSION#", str(counts["regression"])),
  ("#NUMPERFIMPROVE#", str(counts["performance improved"])),
  ("#NUMPERFREGRESSION#", str(counts["performance regression"])),
  ("#NUMONLYPR#", str(len(onlyPr))),
  ("#NUMONLYBASELINE#", str(len(onlyBaseline))),
  ("#LIBCHANGES#", "\n".join(libchanges)),
  ("#MODELCHANGES#", "\n".join(rows)),
  ("#MODELSONLYINONE#", "\n".join(
      '<tr><td>%s</td><td>%s</td><td>%s</td></tr>' % (html.escape(libname), html.escape(model), where)
      for (where, lst) in [("only in %s" % branch, onlyPr), ("only in %s" % baseline, onlyBaseline)]
      for (libname, model) in lst)),
)
with codecs.open(os.path.join(historydir, reportname), "w", encoding="utf-8") as fout:
  fout.write(tpl)

# The index the history directory of every branch has, so that the report is
# reachable from the server without knowing its name.
reporturl = "%s/%s/%s" % (args.historyurl, branch, reportname.replace(" ", "%20"))
summary = ("%d improved, %d regressions; performance %d improved, %d regressions"
           % (counts["improved"], counts["regression"],
              counts["performance improved"], counts["performance regression"]))
indexname = os.path.join(historydir, "00_history.html")
index = []
if os.path.exists(indexname):
  with codecs.open(indexname, "r", encoding="utf-8") as fin:
    # A report of the same two runs is one that has just been overwritten, so
    # its line in the index is replaced rather than repeated.
    index = [line for line in fin.read().splitlines() if line.strip() and reporturl not in line]
entry = '<p><a href="%s">%s against %s %s</a> %s</p>' % (reporturl, branch, baseline, reportname, summary)
with codecs.open(indexname, "w", encoding="utf-8") as fout:
  fout.write("".join(line + "\n" for line in index + [entry]))

markdown = ["## Library testing for [#%s](%s) against `%s`" % (pr, prurl, baseline), "",
            "| | Branch | Run | Compiler | Machine |",
            "| --- | --- | --- | --- | --- |",
            "| Baseline | `%s` | %s | %s | %s |" % (baseline, dateStr(basedate), omcVersion(baseline, basedate), ", ".join(sorted(basehosts))),
            "| Pull request | `%s` | %s | %s | %s |" % (branch, dateStr(prdate), omcVersion(branch, prdate), ", ".join(sorted(prhosts))),
            "",
            "%d models compared, **%d improved, %d regressions**, performance %d improved, %d regressions."
            % (numCompared, counts["improved"], counts["regression"],
               counts["performance improved"], counts["performance regression"]),
            "", "[Full report](%s)" % reporturl, ""]
if markdownrows:
  markdown += ["<details><summary>%d models affected</summary>" % len(markdownrows), "",
               "| Library | Model | Change |", "| --- | --- | --- |"]
  markdown += ["| %s | %s | %s |" % (libname, model, msg) for (libname, model, msg) in markdownrows]
  markdown += ["", "</details>", ""]
markdown += ["<details><summary>Caveats</summary>", ""]
markdown += ["- %s" % c.replace("&rarr;", "->") for c in caveats + [note]]
markdown += ["", "</details>", "", "---", "Generated by the OpenModelica library testing"]
markdownname = args.markdown or os.path.join(historydir, "00_comment.md")
comment = "\n".join([COMMENTMARKER] + markdown) + "\n"
with codecs.open(markdownname, "w", encoding="utf-8") as fout:
  fout.write(comment)

if args.comment:
  print(postComment(pr, comment))

print("%s: %s" % (branch, summary))
print("Report:  %s" % os.path.join(historydir, reportname))
print("Comment: %s" % markdownname)
print("Published as %s" % reporturl)
