import subprocess
from juliacall import Main as jl

def print_julia_version():

  julia = None
  try:
    julia = subprocess.getoutput("which julia").strip()
  except subprocess.CalledProcessError as e:
    print("Couldn't find julia:\n%s" %(e.output))
    raise e
  print("Julia executable: %s" %(julia))

  jl.seval("using InteractiveUtils; versioninfo()")

def dev_testbasemodelica_jl():

  jl.seval("import Pkg; Pkg.develop(path=\"TestBaseModelica\")")
