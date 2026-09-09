<!DOCTYPE html>
<html lang="en">
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

<p>
Test started: #timeStart#<br/>
Total time taken: #totalTime#<br>
System info: #sysInfo#</p>
<p>OpenModelica Version: #omcVersion#<br>
#fmiToolVersion#
#fmi#
OpenModelicaLibraryTesting Changes<br>
#OpenModelicaLibraryTesting#</p>
<p>Tested Library: #fileName# #libraryVersionRevision#<pre>
#metadata#</pre></p>
<p>
BuildModel time limit: #ulimitOmc#s<br>
Simulation time limit: #ulimitExe#s<br>#ulimitExeModels#
Default tolerance: #defaultTolerance#<br>
Default number of intervals: #defaultNumberOfIntervals#<br>
Optimization level: #optlevel#</p>
#referenceFiles#
#referenceTool#
Flags: <pre>#customCommands#</pre>
Config: <pre>#config#</pre>
<p>Links are provided if getErrorString() or the simulation generates output. The links are coded with <font style="#FF0000">red</font> if there were errors, <font style="#FFCC66">yellow</font> if there were warnings, and normal links if there are only notifications.</p>
<table>
<tr><th>Model</th><th>Verified</th><th>Simulate</th><th>Total buildModel</th><th>Parsing</th><th>Frontend</th><th>Backend</th><th>SimCode</th><th>Templates</th><th>Compile</th><th>Total Execution</th></tr>
#testsHTML#
</table>
<script>
// A failed verification links its two .mat files (the differing variables of
// the result and of the reference) to the OMPlot page, which plots the tube
// comparison of each variable. The page needs absolute URLs.
const omplot = 'https://playground.openmodelica.org/latest/omplot/';
for (const a of document.querySelectorAll('a[data-omplot]')) {
  const abs = (f) => encodeURIComponent(new URL(f, location.href).href);
  a.href = omplot + '?result=' + abs(a.dataset.omplot + '.mat') + '&reference=' + abs(a.dataset.omplot + '.ref.mat');
}
</script>
</body>
</html>
