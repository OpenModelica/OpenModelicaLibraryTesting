//! base 0.1.0
package 'Parameter'
 model 'Parameter'
  Real 'x'(fixed = true, start = 1.0);
  parameter Real 'T_ref'(nominal = 300.0, start = 288.15,
    min = 0.0, displayUnit = "degC", unit = "K",
    quantity = "ThermodynamicTemperature") = 300.15;
  equation
   der('x') = 'x';
 end 'Parameter';
end 'Parameter';
