# TestBaseModelica

Test coupling of Base Modelica export off OpenModelica and
[ModelingToolkit.jl](https://github.com/SciML/ModelingToolkit.jl).

For a Base Modelica file exported by OpenModelica parsing with
[BaseModelica.jl](https://github.com/SciML/BaseModelica.jl) and simulating with
[DifferentialEquations.jl](https://github.com/SciML/DifferentialEquations.jl) is
tested.

## Dependencies

  - Julia
  - Julia packages

## Precompilation

To speed up the execution of the test and reduce the TTFP-overhad of Julia there are two options:

1. Precompile this package with
   [PackageCompiler.jl](https://github.com/JuliaLang/PackageCompiler.jl) and
   start a new Julia session for each test.

  ```julia
  julia> using PackageCompiler
  (@v1.11) pkg> activate .
  julia> create_sysimage(["TestBaseModelica"]; sysimage_path="TestBaseModelica.so", precompile_execution_file="precompile_skript.jl" )
  ```

2. Keep a Julia daemon running in the background for all tests by using
   [DaemonMode.jl](https://github.com/dmolina/DaemonMode.jl)

## How to use

```julia
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
```
