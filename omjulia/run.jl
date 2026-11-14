#= Translates and simulates one model with OMBackend.jl, reading the flat model of omc's
   frontend through OMCompiler.jl: what simulate.jl runs for each model, and workload.jl for
   the models the sysimage is compiled with. =#

import JSON, Logging, OMBackend, OMCompiler

struct PhaseFailed <: Exception
  phase::String
end

struct Run
  request::Any
  stats::Dict{String, Any}
  started::Float64
end

Run(requestFile::String, started::Float64) =
  Run(JSON.parsefile(requestFile), Dict{String, Any}("startup" => time() - started, "startedAt" => Dict{String, Float64}()), started)

function saveStats(r::Run)
  local tmp = r.request["statsFile"] * ".tmp"
  write(tmp, JSON.json(r.stats))
  mv(tmp, r.request["statsFile"]; force = true)
end

#= The statistics file is rewritten after every phase, so a run that is killed still says
   how far it came. =#
function phase(f::Function, r::Run, name::String)
  local started = time()
  r.stats["running"] = name
  r.stats["startedAt"][name] = started - r.started
  saveStats(r)
  local result = try
    f()
  catch e
    r.stats[name] = time() - started
    r.stats["failed"] = name
    delete!(r.stats, "running")
    saveStats(r)
    println("Failed in ", name, ": ", sprint(showerror, e))
    Base.show_backtrace(stdout, catch_backtrace())
    println()
    throw(PhaseFailed(name))
  end
  r.stats[name] = time() - started
  delete!(r.stats, "running")
  saveStats(r)
  return result
end

function evaluate(cmd::String)::String
  local res = OMCompiler.evaluate(cmd)
  local err = OMCompiler.evaluate("getErrorString()")
  println(cmd, " => ", strip(res), isempty(strip(err, ['\n', '"'])) ? "" : "\n" * err)
  return strip(res)
end

const OMC_STARTED = Ref(false)

function startOMC(omhome::String)
  OMC_STARTED[] && return
  OMCompiler.init(omhome = omhome)
  OMC_STARTED[] = true
end

#= Values at every point the solver saved; a parameter's is constant. OMBackend names the
   derivative of x $DER_x. =#
function savedValues(sol, name::String)::Union{Nothing, Vector{Float64}}
  name == "time" && return Float64.(sol.t)
  local vals = solverValues(sol, name)
  if vals === nothing && startswith(name, "der(") && endswith(name, ")")
    vals = solverValues(sol, "\$DER_" * name[5:end-1])
  end
  vals === nothing || return vals
  local p = try
    sol.ps[OMBackend.canonicalSymbol(name)]
  catch
    nothing
  end
  return p isa Real ? fill(Float64(p), length(sol.t)) : nothing
end

function solverValues(sol, name::String)::Union{Nothing, Vector{Float64}}
  local vals = Logging.with_logger(Logging.NullLogger()) do
    try
      OMBackend.getVariableValues(sol, name)
    catch
      nothing
    end
  end
  return vals isa AbstractVector{<:Real} ? Float64.(vals) : nothing
end

#= Values at times between the saved points, from the solver's interpolation where it
   has one for that name, else linear. =#
function interpolatedValues(sol, name::String, saved::Vector{Float64}, ts::Vector{Float64})::Vector{Float64}
  name == "time" && return ts
  local dense = try
    Float64.(sol(ts; idxs = OMBackend.canonicalSymbol(name)).u)
  catch
    nothing
  end
  dense === nothing || return dense
  return [linear(sol.t, saved, t) for t in ts]
end

function linear(t::AbstractVector, v::Vector{Float64}, x::Float64)::Float64
  local i = clamp(searchsortedlast(t, x), 1, length(t) - 1)
  t[i + 1] == t[i] && return v[i + 1]
  return v[i] + (v[i + 1] - v[i]) * (x - t[i]) / (t[i + 1] - t[i])
end

csvName(name::String) = "\"" * replace(name, "\"" => "\"\"") * "\""

#= The solver's points and the experiment's output grid, events kept as two rows. =#
function writeResult(r::Run, sol, file::String, names::Vector{String})
  local t0, t1 = Float64(r.request["startTime"]), Float64(r.request["stopTime"])
  local n = max(Int(r.request["numberOfIntervals"]), 1)
  local saved = Set(sol.t)
  local grid = Float64[t for t in range(t0, t1; length = n + 1) if !(t in saved)]
  local order = sortperm(vcat(Float64.(sol.t), grid); alg = MergeSort)
  local columns = Vector{Float64}[]
  local written = String[]
  for name in names
    local s = savedValues(sol, name)
    if s === nothing
      println("No values for ", name)
      continue
    end
    push!(columns, vcat(s, interpolatedValues(sol, name, s, grid))[order])
    push!(written, name)
  end
  open(file, "w") do io
    println(io, join(csvName.(written), ","))
    for row in eachindex(order)
      println(io, join((repr(c[row]) for c in columns), ","))
    end
  end
  r.stats["variables"] = length(written)
end

function runModel(r::Run)
  local req = r.request
  phase(r, "parsing") do
    startOMC(req["omhome"])
    evaluate("setModelicaPath(\"$(escape_string(req["modelicaPath"]))\")")
    for f in req["loadFiles"]
      evaluate("loadFile(\"$(escape_string(f))\", uses=false)") == "true" || error("Failed to load $f")
    end
    for cmd in req["commands"]
      evaluate(cmd)
    end
  end
  local (flat, functions) = phase(() -> OMCompiler.instantiate(req["model"]), r, "frontend")
  local model = phase(() -> OMBackend.lowerOMCFlatModel(flat, functions), r, "backend")
  local name = phase(() -> first(OMBackend.translate(model)), r, "simcode")
  local SciMLBase = OMBackend.Runtime.ModelingToolkit.SciMLBase
  local sol = phase(r, "sim") do
    local s = OMBackend.simulateModel(name; tspan = (Float64(req["startTime"]), Float64(req["stopTime"])),
                                      reltol = Float64(req["tolerance"]))
    s isa SciMLBase.AbstractODESolution || error("No result file for a $(typeof(s))")
    println("Solver: ", s.retcode, " at t = ", last(s.t), " after ", length(s.t), " points")
    SciMLBase.successful_retcode(s) || error("The solver stopped: $(s.retcode)")
    s
  end
  if !isempty(req["resultFile"])
    phase(() -> writeResult(r, sol, req["resultFile"], String.(req["variables"])), r, "result")
  end
end
