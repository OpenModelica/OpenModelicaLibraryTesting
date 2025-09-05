struct TimeoutError <: Exception
  msg::String
end

function Base.showerror(io::IO, err::TimeoutError)
  print(io, "TimeoutError: ")
  print(io, err.msg)
end

# Copied from Julia discourse
# https://discourse.julialang.org/t/simple-timeout-of-function/99578/7
"""
    @timeout(seconds, expr_to_run, expr_when_fails)

A macro to run an expression with a timeout of `seconds`. If the `expr_to_run`
fails to finish in `seconds` seconds, `expr_when_fails` is returned. Note that
the timeout will fail when the expression to be evaluated does not yield control
back to the scheduler; in general, calls to libraries and tight loops will not
be interrupted.

# Example
```julia
julia> function cpu_burn(n)
           s = 0.0
           for i in 1:n
               s += sin(i)^2 + cos(i)^2
               i % 10_000 == 0 && yield()
           end
           return s
       end
cpu_burn (generic function with 1 method)

julia> @time X = @timeout 1 cpu_burn(10^8) (-1)
  1.021633 seconds (24.90 k allocations: 1.206 MiB, 2.66% compilation time)
-1

julia> @time cpu_burn(10^8)
  2.970053 seconds
1.0e8
"""
macro timeout(seconds, expr_to_run, expr_when_fails)
  quote
    tsk = @task $(esc(expr_to_run))
    schedule(tsk)
    Timer($(esc(seconds))) do timer
      istaskdone(tsk) || schedule(tsk, InterruptException(); error=true)
    end
    try
      fetch(tsk)
    catch _
      $(esc(expr_when_fails))
    end
  end
end
