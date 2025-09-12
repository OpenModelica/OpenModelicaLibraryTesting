package 'FirstOrder'
  model 'FirstOrder'
    parameter Real 'x0' = 0 "Initial value for 'x'";
    Real 'x' "Real variable called 'x'";
  initial equation
    'x' = 'x0' "Set initial value of 'x' to 'x0'";
  equation
    der('x') = 1.0 - 'x';
  end 'FirstOrder';
end 'FirstOrder';
