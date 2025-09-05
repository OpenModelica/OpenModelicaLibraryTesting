using ModelingToolkit

"""
    dump_parsed_model([io::IO=stdout], model::ModelingToolkit.AbstractODESystem)

Dumps equations, unknowns and parameters of `model`.
If `io` is not supplied, prints to the default output stream `stdout`.
"""
function dump_parsed_model(
  io::IO=stdout,
  model::Union{ModelingToolkit.AbstractODESystem,Nothing}=nothing
)

  if isnothing(model)
    return
  end

  println(io, "Model: $(ModelingToolkit.get_name(model))")
  println(io)
  println(io, "Equations:")
  for (eq_nr, eq) in enumerate(equations(model))
    println(io, "$eq_nr: $eq")
  end
  println(io)
  println(io, "Unknowns:")
  for (var_nr, var) in enumerate(ModelingToolkit.dump_unknowns(model))
    println(io, "$var_nr: $var")
  end
  println(io)
  println(io, "Parameters:")
  for (param_nr, param) in enumerate(ModelingToolkit.dump_parameters(model))
    println(io, "$param_nr: $param")
  end
end
