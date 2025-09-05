using DifferentialEquations

"""
Solver settings to solve ODE system.

If `solver` is `nothing` DifferentialEquations.jl will select a default solver.
"""
struct SolverSettings
  solver
  start_time::Real
  stop_time::Real
  interval::Real
  tolerance::Real

  function SolverSettings(;
    solver=nothing,
    start_time::Real=0.0,
    stop_time::Real=1.0,
    interval::Real=(stop_time-start_time)/500,
    tolerance::Real=1e-6
  )
    @assert stop_time >= start_time "Stop time is smaller than start time."
    @assert interval > 0 "Interval has to be greater than zero."
    @assert tolerance > 0 "Tolerance has to be greater than zero."

    new(
      solver,
      start_time,
      stop_time,
      interval,
      tolerance
    )
  end
end

struct TestSettings
  modelname::AbstractString
  output_directory::AbstractString
  resultfile::AbstractString
  time_measurements_file::AbstractString
  timeout_parsing::Integer
  timeout_simulating::Integer
  solver_settings::SolverSettings

  function TestSettings(;
    modelname::AbstractString,
    output_directory::AbstractString=pwd(),
    resultfile::AbstractString=joinpath(output_directory, modelname * "_res.csv"),
    time_measurements_file::AbstractString=joinpath(output_directory, modelname * "_times.csv"),
    timeout_parsing::Integer=300, # 5 minutes
    timeout_simulating::Integer=300, # 5 minutes
    solver_settings::SolverSettings=SolverSettings()
  )

    @assert timeout_parsing > 0 "Timeout for parsing must be greater than zero."
    @assert timeout_simulating > 0 "Timeout for simulating must be greater than zero."

    new(
      modelname,
      output_directory,
      resultfile,
      time_measurements_file,
      timeout_parsing,
      timeout_simulating,
      solver_settings)
  end
end
