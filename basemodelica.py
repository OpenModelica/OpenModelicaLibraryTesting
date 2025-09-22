import monotonic
import os.path
import shutil
import subprocess
import warnings

from omcommon import friendlyStr

try:
  from juliacall import Main as jl
except ImportError:
  warnings.warn("No module named 'juliacall'. "
                "'--basemodelica-mtk-import' won't be supported.")
  juliacall = None
  class jl:
    def seval(any: any):
      raise ImportError("No module named 'juliacall'")

def print_julia_version() -> None:
  """Print Julia `versioninfo()`"""

  julia = shutil.which("julia")
  print("Julia executable: %s" %(julia))

  jl.seval("using InteractiveUtils; versioninfo()")

def precompile_testbaesmodelica(systemImage: os.PathLike | None = None) -> None:
  """Update and pre-compile TestBaseModelica to `sysimage`.

  Update dependencies of TestBaseModelica to get the latest version of
  BaseModelica.jl from branch main.
  Create a pre-compile system image of package TestBaseModelica with
  PackageCompiler.jl. Skipping this step if `systemImage` is `None`.
  This might take a wile!
  """

  start = monotonic.monotonic()
  print("Updating Julia package TestBaseModelica")

  jl.seval('import Pkg;'
           'Pkg.activate();'
           'Pkg.add("PackageCompiler");'
           'using PackageCompiler;'
           'Pkg.activate("TestBaseModelica");'
           'Pkg.update();'
           'Pkg.status();')

  if systemImage == None:
    jl.seval('Pkg.activate();'
             'Pkg.develop(path="TestBaseModelica");'
             'Pkg.precompile("TestBaseModelica")')
  else:
    print("Pre-compiling Julia system image %s for TestBaseModelica. "
          "This might take a while." % systemImage)

    jl.seval('create_sysimage(["TestBaseModelica"];'
             'sysimage_path="%s",'
             'precompile_execution_file="TestBaseModelica/precompile_skript.jl")'
            % systemImage)
    if not os.path.isfile(systemImage):
      raise FileNotFoundError("Something went wrong, couldn't find %s" % systemImage)

  execTime = monotonic.monotonic() - start
  print("Done pre-compiling in %s." % friendlyStr(execTime))
