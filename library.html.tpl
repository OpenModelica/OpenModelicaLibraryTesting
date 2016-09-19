<!DOCTYPE html>
<html>
<head>
  <title>#fileName# test using OpenModelica</title>
</head>
<body>
<h1>#fileName# test using OpenModelica</h1>

<table>
<tr>
<th>Total</th>
<th>Frontend</th>
<th>Backend</th>
<th>SimCode</th>
<th>Templates</th>
<th>Compilation</th>
<th>Simulation</th>
<th>Verification</th>
</tr>
<tr>
<td>#Total#</td>
<td bgcolor="#FrontendColor#">#Frontend#</td>
<td bgcolor="#BackendColor#">#Backend#</td>
<td bgcolor="#SimCodeColor#">#SimCode#</td>
<td bgcolor="#TemplatesColor#">#Templates#</td>
<td bgcolor="#CompilationColor#">#Compilation#</td>
<td bgcolor="#SimulationColor#">#Simulation#</td>
<td bgcolor="#VerificationColor#">#Verification#</td>
</tr>
</table>

<p>Total time taken: #totalTime#</p>
<p>OpenModelica Version: #omcVersion#</p>
<p>Test started: #timeStart#</p>
<p>Tested Library: #libraryVersionRevision#</p>
<p>BuildModel time limit: #ulimitOmc#s</p>
<p>Simulation time limit: #ulimitExe#s</p>
<p>Default tolerance: #default_tolerance#</p>
Flags: <pre>#customCommands#</pre>
<p>Links are provided if getErrorString() or the simulation generates output. The links are coded with <font style="#FF0000">red</font> if there were errors, <font style="#FFCC66">yellow</font> if there were warnings, and normal links if there are only notifications.</p>
<table>
<tr><th>Model</th><th>Verified</th><th>Simulate</th><th>Total buildModel</th><th>Frontend</th><th>Backend</th><th>SimCode</th><th>Templates</th><th>Compile</th></tr>
#testsHTML#
</table>
</body>
</html>
