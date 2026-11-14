#= The Julia environment the omjulia target simulates in: OMBackend.jl and its sibling
   packages at the commits OM.jl pins as submodules (their masters need not fit together),
   and OMCompiler.jl from the OpenModelica checkout the tested omc was built from.
   --ombackend takes another branch, tag or commit of OMBackend.jl.

     JULIA_DEPOT_PATH=<dir>/depot: julia omjulia/setup.jl [--ombackend=<ref>]
         [--omhome=<omc installation> --libraries=<directory>] <dir> <OMCompiler.jl>

   <dir> keeps the checkouts (packages/), the environment (environment/) and the depot, so
   a later run only updates them. test.py --omjulia=<dir> then runs every model in it.

   With --omhome and --libraries (holding Modelica 4.1.0), it also compiles <dir>/sysimage.so
   from the models of workload.jl. Julia then starts with OMBackend.jl loaded and much of it
   compiled, which every model would pay for otherwise. It is compiled again only when a
   package or the workload changes. =#

const OPTIONS = Dict{String, String}()
const POSITIONAL = String[]
for a in ARGS
  local m = match(r"^--(ombackend|omhome|libraries)=(.*)$", a)
  m === nothing ? push!(POSITIONAL, a) : (OPTIONS[m[1]] = m[2])
end
if length(POSITIONAL) != 2 || haskey(OPTIONS, "omhome") != haskey(OPTIONS, "libraries")
  println(stderr, "usage: julia omjulia/setup.jl [--ombackend=<ref>] [--omhome=<dir> --libraries=<dir>] <dir> <OMCompiler.jl>")
  exit(2)
end

const DIR = abspath(POSITIONAL[1])
const OMCOMPILER = abspath(POSITIONAL[2])
const DEPOT = joinpath(DIR, "depot")
const ENVIRONMENT = joinpath(DIR, "environment")

mkpath(DEPOT)
if realpath(mkpath(first(DEPOT_PATH))) != realpath(DEPOT)
  println(stderr, "Run with JULIA_DEPOT_PATH=$DEPOT: so that test.py finds what this precompiles")
  exit(2)
end
isfile(joinpath(OMCOMPILER, "Project.toml")) || error("$OMCOMPILER is not the OMCompiler.jl package")

ENV["JULIA_PKG_PRECOMPILE_AUTO"] = "0"
import Libdl, Pkg, SHA

const SIBLINGS = ("Absyn.jl", "DAE.jl", "ImmutableList.jl", "ListUtil.jl", "MetaModelica.jl",
                  "OMFrontend.jl", "OMParser.jl", "OMRuntimeExternalC.jl", "SCode.jl")

function checkout(name::String, ref::AbstractString; url = "https://github.com/OpenModelica/$name.git")::String
  local path = joinpath(DIR, "packages", name)
  isdir(path) || run(`git clone --quiet $url $path`)
  run(`git -C $path fetch --quiet --force --tags origin`)
  local branch = success(`git -C $path rev-parse --verify --quiet origin/$ref`)
  branch || success(`git -C $path fetch --quiet origin $ref`)
  run(`git -C $path checkout --quiet --force --detach $(branch ? "origin/$ref" : ref)`)
  println(name, " ", ref, " ", readchomp(`git -C $path log -1 --format=%h\ %s`))
  return path
end

const OMJL = checkout("OM.jl", "master"; url = "https://github.com/JKRT/OM.jl.git")
pinned(name::String) = readchomp(`git -C $OMJL rev-parse HEAD:$name`)

const PATHS = vcat([checkout(p, pinned(p)) for p in SIBLINGS],
                   checkout("OMBackend.jl", get(OPTIONS, "ombackend", pinned("OMBackend.jl"))), OMCOMPILER)

const REGISTRIES = [r.name for r in Pkg.Registry.reachable_registries()]
"General" in REGISTRIES || Pkg.Registry.add("General")
"OpenModelicaRegistry" in REGISTRIES ||
  Pkg.Registry.add(Pkg.RegistrySpec(url = "https://github.com/OpenModelica/OpenModelicaRegistry.git"))
Pkg.Registry.update()

Pkg.activate(ENVIRONMENT)
Pkg.develop([Pkg.PackageSpec(path = p) for p in PATHS])
Pkg.add("JSON")
Pkg.instantiate()
Pkg.build()
Pkg.precompile(; strict = true)

const SYSIMAGE = joinpath(DIR, "sysimage." * Libdl.dlext)
const SYSIMAGE_KEY = joinpath(DIR, "sysimage.key")

#= What the sysimage is compiled from: the resolved packages, the sources of the developed
   ones (uncommitted changes included) and the workload. =#
function sysimageKey()::String
  local parts = [string(VERSION), read(joinpath(ENVIRONMENT, "Manifest.toml"), String)]
  for p in PATHS
    push!(parts, readchomp(`git -C $p rev-parse HEAD:./`), read(`git -C $p diff HEAD -- .`, String))
  end
  for f in ("run.jl", "workload.jl")
    push!(parts, read(joinpath(@__DIR__, f), String))
  end
  return bytes2hex(SHA.sha256(join(parts, "\n")))
end

const JULIA = joinpath(Sys.BINDIR, Base.julia_exename())

const BUILD_SYSIMAGE = """
import PackageCompiler
PackageCompiler.create_sysimage(["OMBackend", "OMCompiler", "JSON"]; project = ENV["OMJULIA_ENVIRONMENT"],
                                sysimage_path = ENV["OMJULIA_SYSIMAGE"],
                                precompile_execution_file = ENV["OMJULIA_WORKLOAD"])
"""

function buildSysimage(key::String, omhome::String, libraries::String)
  local compiler = joinpath(DIR, "packagecompiler")
  Pkg.activate(compiler)
  Pkg.add("PackageCompiler")
  local new = joinpath(DIR, "sysimage-new." * Libdl.dlext)
  local cmd = addenv(`$JULIA --startup-file=no --project=$compiler -e $BUILD_SYSIMAGE`,
                     "OMJULIA_ENVIRONMENT" => ENVIRONMENT, "OMJULIA_SYSIMAGE" => new,
                     "OMJULIA_WORKLOAD" => joinpath(@__DIR__, "workload.jl"),
                     "OMJULIA_OMHOME" => abspath(omhome), "OMJULIA_LIBRARIES" => abspath(libraries))
  #= Without one every model only starts slower, so a failure is not the end of the job. =#
  if success(pipeline(cmd; stdout, stderr))
    mv(new, SYSIMAGE; force = true)
    write(SYSIMAGE_KEY, key)
  else
    println(stderr, "WARNING: compiling the sysimage failed; models load OMBackend.jl themselves")
    rm(new; force = true)
  end
end

const KEY = sysimageKey()
if isfile(SYSIMAGE) && isfile(SYSIMAGE_KEY) && read(SYSIMAGE_KEY, String) == KEY
  println("The sysimage is up to date")
else
  #= test.py would start with it, and an outdated one runs the packages it was compiled from. =#
  rm(SYSIMAGE; force = true)
  rm(SYSIMAGE_KEY; force = true)
  haskey(OPTIONS, "omhome") && buildSysimage(KEY, OPTIONS["omhome"], OPTIONS["libraries"])
end

const SYSIMAGE_FLAGS = isfile(SYSIMAGE) ? ["--sysimage=$SYSIMAGE"] : String[]
run(`$JULIA $SYSIMAGE_FLAGS --startup-file=no --project=$ENVIRONMENT $(joinpath(@__DIR__, "simulate.jl")) --version`)
