module TestBaseModelica

import BaseModelica
import DataFrames
import CSV

include("dump.jl")
include("settings.jl")
include("timeout.jl")

"""
Test coupling of Base Modelica and ModelingToolkit.jl.

  1. Parse given Base Modelica file using BaseModelica.jl and ModelingToolkit.jl
  2. Solve ODE problem using
"""
function run_test(
  base_modelica_file::AbstractString;
  settings::Settings = Settings( modelname=splitext(basename(base_modelica_file))[1] )
)
  mkpath(settings.output_directory)

  # Parsing
  parsed_model = nothing
  time_parsing = @elapsed begin
    @timeout settings.timeout_parsing begin
    parsed_model = BaseModelica.parse_basemodelica(base_modelica_file)
    end throw(TimeoutError("Base Modelica parsing reached timeout $(settings.timeout_parsing)."))
  end

  write(settings.time_measurements_file, "BaseModelica.parse_basemodelica, $(time_parsing)\n")

  # Simulating
end

export Settings
export SolverSettings
export run_test

end
