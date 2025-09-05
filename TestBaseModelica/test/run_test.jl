using Test
using TestBaseModelica

function test_parse_and_simulate_ExampleFirstOrder()
  modelname = "ExampleFirstOrder"
  base_modelica_file = joinpath(dirname(@__DIR__), "examples", modelname * ".mo")

  output_directory = joinpath(@__DIR__, "test_out")
  rm("test_out", force=true, recursive=true)

  run_test(base_modelica_file;
            settings=Settings(
            modelname = modelname,
            output_directory=output_directory,
            timeout_parsing = 60))

  @test isfile(joinpath(output_directory, modelname * "_times.csv"))
end

@testset "run_test" begin
  @testset "ExampleFirstOrder" begin
    test_parse_and_simulate_ExampleFirstOrder()
  end
end
