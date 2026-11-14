#= What setup.jl compiles the sysimage with: MSL examples through the same code as every
   tested model. OMJULIA_OMHOME is the omc to use and OMJULIA_LIBRARIES a directory holding
   Modelica 4.1.0. =#

include(joinpath(@__DIR__, "run.jl"))

const MODELS = [
  ("Modelica.Mechanics.Rotational.Examples.First", 1.0, ["time", "damper.phi_rel", "inertia3.phi"]),
  ("Modelica.Electrical.Analog.Examples.Rectifier", 0.1, ["Capacitor1.v", "Inductor2.i"]),
  ("Modelica.Blocks.Examples.PID_Controller", 4.0, ["PI.I.y", "inertia1.w"]),
  ("Modelica.Mechanics.MultiBody.Examples.Elementary.Pendulum", 5.0, ["rev.phi", "rev.w"]),
  ("Modelica.Media.Examples.SimpleLiquidWater", 100.0, ["medium.T"]),
  ("Modelica.Mechanics.Rotational.Examples.CoupledClutches", 1.5, ["J1.w", "clutch1.phi_rel"]),
  ("Modelica.Blocks.Examples.BooleanNetwork1", 10.0, ["and1.u[1]", "and1.u[2]"]),
]

for (model, stopTime, variables) in MODELS
  local dir = mktempdir()
  local request = joinpath(dir, "request.json")
  write(request, JSON.json(Dict(
    "omhome" => ENV["OMJULIA_OMHOME"], "modelicaPath" => ENV["OMJULIA_LIBRARIES"], "loadFiles" => String[],
    "commands" => ["loadModel(Modelica, {\"4.1.0\"})"], "model" => model, "startTime" => 0.0,
    "stopTime" => stopTime, "tolerance" => 1e-6, "numberOfIntervals" => 500, "variables" => variables,
    "resultFile" => joinpath(dir, "result.csv"), "statsFile" => joinpath(dir, "stats.json"))))
  local started = time()
  try
    runModel(Run(request, started))
    println("workload: ", model, " in ", round(time() - started; digits = 1), " s")
  catch e
    e isa PhaseFailed || rethrow()
    println("workload: ", model, " failed in ", e.phase)
  end
end
