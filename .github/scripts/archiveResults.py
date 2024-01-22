#!/usr/bin/python3

import os
import shutil
import sys

def copyFiles(libraryName, libVersion, branchOM, targetDir):
  """
  Zip HTML files and save in target directory.

  Arguments
  libraryName     -- Name of Modelica library.
  libVersion      -- Branch or version of Modelica library.
  branchOM        -- Branch or version of OpenModelica.
  targetDir       -- Target directory.
  """

  libNameBranch = f"{libraryName}_{libVersion}"

  shutil.copytree("files",
                  os.path.join(targetDir, branchOM, libNameBranch, "files"),
                  dirs_exist_ok = True)

  shutil.copy2("overview.html",
               os.path.join(targetDir, "index.html"))

  # Copy library overview
  shutil.copy2(f"{libNameBranch}.html",
               os.path.join(targetDir, branchOM, libNameBranch, f"{libNameBranch}.html"))

  # Copy dygraph script
  shutil.copy2(os.path.join(".github", "scripts", "dygraph-combined.js"),
               os.path.join(targetDir, branchOM, libNameBranch, "files", "dygraph-combined.js"))

if len(sys.argv) != 5:
  raise Exception("Wrong number of input arguments.\nUsage:\narchieveResults.py libraryName libVersion branchOM omLibTestingDir zipFile")

libraryName     = sys.argv[1]
libVersion      = sys.argv[2]
branchOM        = sys.argv[3]
targetDir       = sys.argv[4]

# If running inside a pull request
if libVersion.endswith('/merge'):
  libVersion = 'dev-pr-' + libVersion.replace('/merge', '')

copyFiles(libraryName, libVersion, branchOM, targetDir)
