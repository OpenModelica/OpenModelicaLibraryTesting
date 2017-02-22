model HelloWorld
  Real x(start=0, fixed=true);
equation
  der(x) = 1.0;
end HelloWorld;
