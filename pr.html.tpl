<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>OpenModelica pull request #PR# against #BASELINE#</title>
  <style>
  body {font-family:sans-serif;}
  table {border-collapse:collapse; margin-bottom:1em;}
  th,td {border:1px solid #CCC; padding:2px 6px; text-align:left;}
  td.warning {background-color:#FFCC66;}
  td.better {background-color:#00FF00;}
  td.warningPerformance {background-color:#FFFC66;}
  td.betterPerformance {background-color:#00FAFF;}
  p.caveat {background-color:#FFCC66; padding:6px; max-width:60em;}
  </style>
</head>
<body>
<h1>OpenModelica <a href="#PRURL#">pull request #PR#</a> against #BASELINE#</h1>

#CAVEATS#
<p>The baseline is the newest run of #BASELINE#, not the commit the pull request is
based on, so a difference can also come from something merged into #BASELINE# since
the pull request was branched.</p>

<h2>The two runs</h2>

<table>
<tr><th></th><th>Branch</th><th>Run</th><th>Compiler</th><th>Machine</th></tr>
<tr><td>Baseline</td><td>#BASELINE#</td><td>#DATE1#</td><td>#OMCVERSION1#</td><td>#HOST1#</td></tr>
<tr><td>Pull request</td><td>#BRANCH#</td><td>#DATE2#</td><td>#OMCVERSION2#</td><td>#HOST2#</td></tr>
</table>

<h2>Summary</h2>

<table>
<tr><td>Models compared</td><td>#NUMCOMPARED#</td></tr>
<tr><td>Number of Improvements</td><td>#NUMIMPROVE#</td></tr>
<tr><td>Number of Regressions</td><td>#NUMREGRESSION#</td></tr>
<tr><td>Number of Performance Improvements</td><td>#NUMPERFIMPROVE#</td></tr>
<tr><td>Number of Performance Regressions</td><td>#NUMPERFREGRESSION#</td></tr>
<tr><td>Models only in the pull request run</td><td>#NUMONLYPR#</td></tr>
<tr><td>Models only in the baseline run</td><td>#NUMONLYBASELINE#</td></tr>
</table>

<h2>Library Changes</h2>
<table>
<tr><th>Library</th><th>Change</th></tr>
#LIBCHANGES#
</table>

<h2>Models Affected</h2>
<table>
<tr><th>Library</th><th>Model</th><th>Change</th></tr>
#MODELCHANGES#
</table>

<h2>Models Only in One of the Runs</h2>
<table>
<tr><th>Library</th><th>Model</th><th>Where</th></tr>
#MODELSONLYINONE#
</table>

</body>
</html>
