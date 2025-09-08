using TestBaseModelica

solver_settings = SolverSettings(
  start_time = 0.0,
  stop_time = 1.0,
  interval = 0.02,
  tolerance = 1e-6
)

test_settings = TestSettings(
  modelname = "ExampleFirstOrder",
  output_directory = "ExampleFirstOrder",
  solver_settings = solver_settings)

run_test(joinpath("examples", "ExampleFirstOrder.mo"); settings = test_settings)

rm("ExampleFirstOrder", force=true, recursive=true)
