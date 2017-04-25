<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>OpenModelica #BRANCH# from #DATE1# to #DATE2#</title>
  <style>
  td.warning {background-color:#FFCC66;}
  td.better {background-color:#00FF00;}
  </style>
</head>
<body>
<h1>OpenModelica #BRANCH# from #DATE1# to #DATE2#</h1>

<h2>Summary</h2>

<table>
<tr><td>OMC Commits</td><td>#NUMCOMMITS#</td></tr>
<tr><td>Libraries Changed</td><td>#NUMLIBS#</td></tr>
<tr><td>Number of Improvements</td><td>#NUMIMPROVE#</td></tr>
<tr><td>Number of Regressions</td><td>#NUMREGRESSION#</td></tr>
<tr><td>Number of Performance Improvements</td><td>#NUMPERFIMPROVE#</td></tr>
<tr><td>Number of Performance Regressions</td><td>#NUMPERFREGRESSION#</td></tr>
</table>

<h2>OpenModelica Changes</h2>
<table>
<tr><th>Commit</th><th>Author</th><th>Summary</th></tr>
#OMCGITLOG#
</table>

<h2>Library Changes</h2>
<table>
<tr><th>Library</th><th>Change</th></tr>
#LIBCHANGES#
</table>

<h2>Models Affected</h2>
<table>
#MODELCHANGES#
</table>

</body>
</html>
