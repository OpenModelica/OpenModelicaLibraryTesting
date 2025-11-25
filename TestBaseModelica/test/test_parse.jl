using Test
using TestBaseModelica
using DataFrames
using CSV

function test_parse_and_simulate_FirstOrder()
  modelname = "FirstOrder"
  base_modelica_file = joinpath(dirname(@__DIR__), "examples", modelname * ".bmo")

  output_directory = joinpath(@__DIR__, "test_out")
  rm(output_directory, force=true, recursive=true)

  run_test(base_modelica_file;
            settings=TestSettings(
            modelname = modelname,
            output_directory=output_directory,
            timeout_parsing = 60))

  times_file = joinpath(output_directory, modelname * "_times.csv")
  @test isfile(times_file)
  content = readlines(times_file)
  @info content
  @test occursin(r"BaseModelica\.parse_basemodelica, [0-9]+\.[0-9]+", content[1])
  @test occursin(r"SciMLBase\.ODEProblem, [0-9]+\.[0-9]+", content[2])
  @test occursin(r"OrdinaryDiffEq\.solve, [0-9]+\.[0-9]+", content[3])

  dump_file = joinpath(output_directory, modelname * "_dump.txt")
  @test isfile(dump_file)
  @test read(dump_file, String) == """Model: sys

  Equations:
  1: Differential(t)(x(t)) ~ 1.0 - a*x(t)

  Unknowns:
  1: (var = x(t), variable_source = :variables, name = :x, variable_type = ModelingToolkit.VARIABLE, irreducible = false, tunable = false, type = Real, default = 0.0)

  Parameters:
  1: (var = a, variable_source = :parameters, name = :a, variable_type = ModelingToolkit.PARAMETER, irreducible = false, tunable = true, type = Real, default = 1.1)
  """

  jl_dump_file = joinpath(output_directory, modelname * ".jl")
  @test isfile(jl_dump_file)

  result_file = joinpath(output_directory, modelname * "_res.csv")
  @test isfile(result_file)
  df = CSV.read(result_file, DataFrame)
  filter!(row -> row.time in [0.0, 0.5, 1.0], df)
  @test df[1,2] == 0.0
  @test df[2,2] ≈ 0.38459131104319083
  @test df[3,2] ≈ 0.6064807012910736

  rm(output_directory, force=true, recursive=true)
end

@testset "run_test" begin
  @testset "FirstOrder" begin
    test_parse_and_simulate_FirstOrder()
  end
end
