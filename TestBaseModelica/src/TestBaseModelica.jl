module TestBaseModelica

import BaseModelica
import CSV
import DataFrames
import SciMLBase
import OrdinaryDiffEq

include("settings.jl")

"""
Test coupling of Base Modelica and ModelingToolkit.jl.

  1. Parse given Base Modelica file using BaseModelica.jl and ModelingToolkit.jl
  2. Solve ODE problem
"""
function run_test(base_modelica_file::AbstractString; settings::TestSettings)
  mkpath(abspath(settings.output_directory))

  # Parse Base Modelica and create ODEProblem
  ode_problem = nothing
  time_parsing = @elapsed begin
    ode_problem = BaseModelica.create_odeproblem(base_modelica_file)
  end
  open(settings.time_measurements_file, "w") do file
    write(file, "BaseModelica.create_odeproblem, $(time_parsing)\n")
  end

  # Simulate ODEProblem
  ode_solution = nothing
  time_solve = @elapsed begin
    if isnothing(settings.solver_settings.solver)
      ode_solution = OrdinaryDiffEq.solve(ode_problem)
    else
      ode_solution = OrdinaryDiffEq.solve(ode_problem, settings.solver_settings.solver)
    end
  end
  open(settings.time_measurements_file, "a") do file
    write(file, "OrdinaryDiffEq.solve, $(time_solve)\n")
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
