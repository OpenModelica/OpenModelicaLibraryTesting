using Test
using TestBaseModelica
using ModelingToolkit
using ModelingToolkit: t_nounits as t, D_nounits as D

function test_first_order_dump()

  @mtkmodel FirstOrder begin
    @parameters begin
      x0 = 0.0
    end
    @variables begin
      x(t)
    end
    @equations begin
      D(x) ~ 1.0 - x
    end
  end

  @mtkbuild firstOrder = FirstOrder()

  io = IOBuffer()
  TestBaseModelica.dump_parsed_model(io, firstOrder)
  dump = String(take!(io))

  @test dump == """Model: firstOrder

  Equations:
  1: Differential(t)(x(t)) ~ 1.0 - x(t)

  Unknowns:
  1: (var = x(t), variable_source = :variables, name = :x, variable_type = ModelingToolkit.VARIABLE, irreducible = false, tunable = false, type = Real)

  Parameters:
  1: (var = x0, variable_source = :variables, name = :x0, variable_type = ModelingToolkit.PARAMETER, irreducible = false, tunable = true, type = Real, default = 0.0)
  """
end

@testset "dump.jl" begin
  @testset "Dump First Order" begin
    test_first_order_dump()
  end
end
