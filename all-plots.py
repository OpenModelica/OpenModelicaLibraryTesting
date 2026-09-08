#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse, os
import shared, resultsdb
import time, datetime
import collections, multiprocessing

import matplotlib as mpl
mpl.use('svg') # Disables the Tk dependency / DISPLAY dependency
import matplotlib.pyplot as plt

def defaultJobs():
  # The cpus this process may use, not the ones the machine has.
  count = getattr(os, "process_cpu_count", os.cpu_count)()
  return max(1, count or 1)

def plotLibrary(fnameprefix, branch, libname, xs, total, frontend,backend,simcode,template,compile,simulate,verify):
  f, ax = plt.subplots(1)
  lw = 0.5
  plt.plot(xs, total, label='total (%d)' % total[-1], linewidth=lw)
  plt.plot(xs, frontend, label='frontend (%d)' % frontend[-1], linewidth=lw)
  plt.plot(xs, backend, label='backend (%d)' % backend[-1], linewidth=lw)
  plt.plot(xs, simcode, label='simcode (%d)' % simcode[-1], linewidth=lw)
  plt.plot(xs, template, label='templates (%d)' % template[-1], linewidth=lw)
  plt.plot(xs, compile, label='compile (%d)' % compile[-1], linewidth=lw)
  plt.plot(xs, simulate, label='simulate (%d)' % simulate[-1], linewidth=lw)
  if not (min(verify)==0 and max(verify)==0):
    plt.plot(xs, verify, label='verify (%d)' % verify[-1], linewidth=lw)

  ax.set_ylim(ymin=0)
  ax.set_xlim(xmin=xs[0], xmax=xs[-1])

  plt.gcf().autofmt_xdate()

  plt.title("%s (%s branch)" % (libname, branch))

  # Shrink current axis by 20%
  box = ax.get_position()
  ax.set_position([box.x0, box.y0, box.width * 0.75, box.height])

  # Put a legend to the right of the current axis
  ax.legend(loc='center left', bbox_to_anchor=(1, 0.5))

  os.makedirs("%s/%s" % (fnameprefix,branch), exist_ok=True)

  plt.savefig("%s/%s/%s.svg" % (fnameprefix,branch,libname), format="svg")

  if len(xs)>=7:
    plt.title(libname + " (%s branch last 7 runs)" % branch)
    ax.set_ylim(ymin=None)
    ax.set_xlim(xmin=xs[-7], xmax=xs[-1])
    plt.savefig("%s/%s/%s-recent.svg" % (fnameprefix,branch,libname), format="svg")

  plt.close()

def plotJob(job):
  plotLibrary(*job)

def plotJobs(db, cursor, branches, fnameprefix):
  """One job per library; a generator, so a branch is queried while the plots
  of the previous one are still being rendered."""
  for branch in branches:
    if not db.tableExists(branch):
      print("No such table '%s'; specify it using --branch=XXX when running test.py" % branch)
      continue

    db.createDateIndex(branch)
    start = time.time()
    libs = {}
    for (date,libname,total,frontend,backend,simcode,template,compile,simulate,verify) in cursor.execute("""SELECT date,libname,%s
      FROM %s
      GROUP BY date,libname
      ORDER BY libname,date ASC
""" % (",".join(db.countIf("finalphase>=%d" % i) for i in range(0,8)), db.quote(branch))):
      if libname not in libs:
        libs[libname] = ([],[],[],[],[],[],[],[],[])
      libs[libname][0].append(datetime.datetime.fromtimestamp(date))
      libs[libname][1].append(total)
      libs[libname][2].append(frontend)
      libs[libname][3].append(backend)
      libs[libname][4].append(simcode)
      libs[libname][5].append(template)
      libs[libname][6].append(compile)
      libs[libname][7].append(simulate)
      libs[libname][8].append(verify)
    print("%s: %d libraries queried in %.1fs" % (branch, len(libs), time.time()-start), flush=True)
    for libname in libs.keys():
      yield (fnameprefix, branch, libname) + libs[libname]

def main():
  parser = argparse.ArgumentParser(description='OpenModelica model testing report generation tool')
  parser.add_argument('branches', nargs='*')
  parser.add_argument('--historypath', default="history")
  parser.add_argument('-j', '--jobs', type=int, default=defaultJobs(),
                      help="How many plots to render at the same time (default: %d)" % defaultJobs())
  resultsdb.addArgument(parser)
  args = parser.parse_args()

  branches = [shared.resultTable(branch) for branch in args.branches]

  db = resultsdb.connect(args.db)
  cursor = db.cursor()
  jobs = plotJobs(db, cursor, branches, args.historypath)

  if args.jobs > 1:
    # The queries stay in this process; only the rendering is handed out. A job
    # carries the whole history of a library, so keep the queue short.
    pending = collections.deque()
    with multiprocessing.Pool(args.jobs) as pool:
      for job in jobs:
        pending.append(pool.apply_async(plotJob, (job,)))
        while len(pending) > 4*args.jobs:
          pending.popleft().get()
      for result in pending:
        result.get()
  else:
    for job in jobs:
      plotJob(job)

if __name__ == '__main__':
  main()
