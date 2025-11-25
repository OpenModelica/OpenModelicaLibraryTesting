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
    timeout_parsing = 60)
  )

  times_file = joinpath(output_directory, modelname * "_times.csv")
  @test isfile(times_file)
  content = readlines(times_file)
  @info content
  @test occursin(r"BaseModelica\.create_odeproblem, [0-9]+\.[0-9]+", content[1])
  @test occursin(r"OrdinaryDiffEq\.solve, [0-9]+\.[0-9]+", content[2])

  result_file = joinpath(output_directory, modelname * "_res.csv")
  @test isfile(result_file)
  df = CSV.read(result_file, DataFrame)
  filter!(row -> row.time in [0.0, 1.0], df)
  @test df[1,2] == 0.0
  @test df[2,2] ≈ 0.6064807012910736

  rm(output_directory, force=true, recursive=true)
end

@testset "run_test" begin
  @testset "FirstOrder" begin
    test_parse_and_simulate_FirstOrder()
  end
end
