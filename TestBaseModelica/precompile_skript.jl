using TestBaseModelica

solver_settings = SolverSettings(
  start_time = 0.0,
  stop_time = 1.0,
  interval = 0.02,
  tolerance = 1e-6
)

output_directory = "tmp_out_dir"
test_settings = TestSettings(
  modelname = "ExampleFirstOrder",
  output_directory = output_directory,
  solver_settings = solver_settings
)

run_test(joinpath(@__DIR__, "examples", "ExampleFirstOrder.mo"); settings = test_settings)
rm(output_directory, force=true, recursive=true)
