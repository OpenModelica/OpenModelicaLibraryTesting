using TestBaseModelica

# Collect all .bmo files from examples directory
examples = [
  (splitext(basename(file))[1], file) for file in filter(
    f -> endswith(f, ".bmo"),
    readdir(joinpath(@__DIR__, "examples"), join=true)
  )
]

solver_settings = SolverSettings(
  start_time = 0.0,
  stop_time = 1.0,
  interval = 0.02,
  tolerance = 1e-6
)

for (modelname, bmo_file) in examples
  output_directory = "tmp_out_dir"
  test_settings = TestSettings(
    modelname = modelname,
    output_directory = output_directory,
    solver_settings = solver_settings
  )
  try
    @info "Running $modelname ..."
    run_test(bmo_file; settings = test_settings)
    @info "... done!"
  catch err
    @warn "... failed!"
    showerror(stdout, err)
  end
  rm(output_directory, force=true, recursive=true)
end
