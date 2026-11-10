#= testmodel.py runs this for every model, in a process of its own:

     julia --project=<dir>/environment omjulia/simulate.jl <request>.json

   `--version` prints the versions instead. =#

const STARTED = time()

include(joinpath(@__DIR__, "run.jl"))

if ARGS == ["--version"]
  println("OMBackend.jl ", pkgversion(OMBackend), " (", readchomp(`git -C $(pkgdir(OMBackend)) log -1 --format=%h`),
          "), OMCompiler.jl ", pkgversion(OMCompiler), ", Julia ", VERSION)
  exit(0)
end

Logging.global_logger(Logging.ConsoleLogger(stdout, Logging.Warn))
println("Loaded Julia and OMBackend.jl in ", round(time() - STARTED; digits = 1), " s")

try
  runModel(Run(ARGS[1], STARTED))
catch e
  e isa PhaseFailed || rethrow()
  exit(1)
end
