#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Drop the result tables of pull requests that have been dealt with.

Testing a pull request fills a pr-<N> table like any other branch, about 19500
rows and a few megabytes, and unlike a branch it is never written to again once
the pull request is merged or closed. This drops those tables, and the rows the
runs left in the other tables, for pull requests that are no longer open or that
were tested long enough ago not to matter.

Nothing is dropped without --yes; without it the tables are only listed.
"""

import argparse, datetime, json, os, re, time, urllib.error, urllib.request
import resultsdb

parser = argparse.ArgumentParser(description='OpenModelica library testing pull request cleanup')
parser.add_argument('--repo', default="OpenModelica/OpenModelica", help='the repository the pull requests belong to')
parser.add_argument('--older-than', type=int, default=60, metavar='DAYS',
                    help='also drop a pull request still open whose newest run is older than this (0: never)')
parser.add_argument('--yes', action='store_true', help='actually drop them')
resultsdb.addArgument(parser)
args = parser.parse_args()

prTableRe = re.compile(r"^pr-([0-9]+)$")

db = resultsdb.connect(args.db)
cursor = db.cursor()


def pullRequestState(number):
  """"open", "closed", "merged", or why we could not tell."""
  url = "https://api.github.com/repos/%s/pulls/%s" % (args.repo, number)
  request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
  # The rate limit is 60 requests an hour without one, which is enough for the
  # handful of tables this looks at, but a token raises it and costs nothing.
  token = os.environ.get("GITHUB_TOKEN")
  if token:
    request.add_header("Authorization", "Bearer %s" % token)
  try:
    pr = json.loads(urllib.request.urlopen(request).read().decode("utf-8"))
  except urllib.error.HTTPError as e:
    return "no answer from GitHub (%s)" % e
  except Exception as e:
    return "no answer from GitHub (%s)" % e
  if pr.get("merged_at"):
    return "merged"
  return pr.get("state") or "unknown"


def newestRun(table):
  (date,) = cursor.execute("SELECT max(date) FROM %s" % db.quote(table)).fetchone()
  return date


def drop(table, branch):
  """The table of a run, and everything the run wrote about itself elsewhere."""
  cursor.execute("DROP TABLE %s" % db.quote(table))
  for other in ["omcversion", "libversion", "history", "job_claim"]:
    if db.tableExists(other):
      cursor.execute("DELETE FROM %s WHERE branch=?" % db.quote(other), (branch,))
  db.commit()


tables = sorted((t for t in db.tables() if prTableRe.match(t)),
                key=lambda t: int(prTableRe.match(t).group(1)))
if not tables:
  raise SystemExit("No pull request tables in this database")

dropping = []
for table in tables:
  number = prTableRe.match(table).group(1)
  date = newestRun(table)
  age = (time.time() - date) / 86400.0 if date else 0
  state = pullRequestState(number)
  stale = args.older_than and date and age > args.older_than
  why = None
  if state in ("merged", "closed"):
    why = "%s, tested %d days ago" % (state, age)
  elif stale:
    why = "still %s, but tested %d days ago" % (state, age)
  print("%-12s %-8s %s%s" % (table, state,
                             "last run %s" % datetime.datetime.fromtimestamp(date) if date else "no runs",
                             ", dropping: %s" % why if why else ""))
  if why:
    dropping.append((table, why))

if not dropping:
  raise SystemExit(0)
if not args.yes:
  print("\n%d tables would be dropped; pass --yes to drop them" % len(dropping))
  raise SystemExit(0)
for (table, why) in dropping:
  print("Dropping %s (%s)" % (table, why))
  drop(table, table)
print("The reports and files published for them are not touched; they are on the web server.")
