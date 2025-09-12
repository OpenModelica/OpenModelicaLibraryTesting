import monotonic
import os.path
import subprocess

from juliacall import Main as jl
from omcommon import friendlyStr

def print_julia_version() -> None:

  julia = None
  try:
    julia = subprocess.getoutput("which julia").strip()
  except subprocess.CalledProcessError as e:
    print("Couldn't find julia:\n%s" %(e.output))
    raise e
  print("Julia executable: %s" %(julia))

  jl.seval("using InteractiveUtils; versioninfo()")

def precompile_testbaesmodelica(systemImage: os.path) -> None:
  """Update and pre-compile TestBaseModelica to `sysimage`.

  Update dependencies of TestBaseModelica to get the latest version of
  BaseModelica.jl from branch main. Create a pre-compile system image of package
  TestBaseModelica with PackageCompiler.jl. This might take a wile!
  """

  start = monotonic.monotonic()
  print("Updating and pre-compiling Julia package TestBaseModelica. This might take a while, hang tight!")
  jl.seval('import Pkg;'
           "Pkg.activate();"
           'Pkg.add("PackageCompiler");'
           'using PackageCompiler;'
           'Pkg.activate("TestBaseModelica");'
           'Pkg.update();'
           'Pkg.status();'
           'create_sysimage(["TestBaseModelica"]; sysimage_path="%s", precompile_execution_file="TestBaseModelica/precompile_skript.jl")'
           % systemImage)
  execTime = monotonic.monotonic() - start
  print("Done pre-compiling in %s." % friendlyStr(execTime))

  if not os.path.isfile(systemImage):
    raise FileNotFoundError("Something went wrong, couldn't find %s" % systemImage)
