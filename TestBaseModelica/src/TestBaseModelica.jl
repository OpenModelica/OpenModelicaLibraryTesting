module TestBaseModelica

import BaseModelica
import CSV
import DataFrames
import DifferentialEquations

include("dump.jl")
include("settings.jl")

"""
Test coupling of Base Modelica and ModelingToolkit.jl.

  1. Parse given Base Modelica file using BaseModelica.jl and ModelingToolkit.jl
  2. Solve ODE problem
"""
function run_test(base_modelica_file::AbstractString; settings::TestSettings)
  mkpath(abspath(settings.output_directory))

  # Parse Base Modelica
  parsed_model = nothing
  time_parsing = @elapsed begin
    parsed_model = BaseModelica.parse_basemodelica(base_modelica_file)
  end
  open(settings.time_measurements_file, "w") do file
    write(file, "BaseModelica.parse_basemodelica, $(time_parsing)\n")
  end

  # Dump parsed model to file for debugging purpose
  open(joinpath(settings.output_directory, settings.modelname * "_dump.txt"), "w") do file
    dump_parsed_model(file, parsed_model)
  end
  open(joinpath(settings.output_directory, settings.modelname * ".jl"), "w") do file
    show(file, parsed_model)
  end

  # Create ODEProblem
  ode_problem = nothing
  time_ODEProblem = @elapsed begin
    ode_problem = DifferentialEquations.ODEProblem(parsed_model)
  end
  open(settings.time_measurements_file, "a") do file
    write(file, "DifferentialEquations.ODEProblem, $(time_ODEProblem)\n")
  end

  # Simulate
  ode_solution = nothing
  time_solve = @elapsed begin
    if isnothing(settings.solver_settings.solver)
      ode_solution = DifferentialEquations.solve(
        ode_problem,
        tspan = (settings.solver_settings.start_time, settings.solver_settings.stop_time),
        saveat = settings.solver_settings.interval)
    else
      ode_solution = DifferentialEquations.solve(
        ode_problem,
        settings.solver_settings.solver,
        tspan = (settings.solver_settings.start_time, settings.solver_settings.stop_time),
        saveat = settings.solver_settings.interval)
    end
  end
  open(settings.time_measurements_file, "a") do file
    write(file, "DifferentialEquations.solve, $(time_solve)\n")
  end

  # Save simulation result
  df = DataFrames.DataFrame(ode_solution)
  DataFrames.rename!(df,:timestamp => :time)
  CSV.write(joinpath(settings.output_directory, settings.modelname * "_res.csv"), df)
end

export TestSettings
export SolverSettings
export run_test

end
