function csvFileToVariable
  input String str;
  output String out;
protected
  String matches[2];
algorithm
  (,matches) := OpenModelica.Scripting.regex(str,"^.*[.]diff[.](.*)$",2);
  out := matches[2];
end csvFileToVariable;

