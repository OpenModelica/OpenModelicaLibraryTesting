<html>
<head>
  <title>#title#</title>
  <style>
  td.warning {background-color:#FFCC66;}
  td.better {background-color:#00FF00;}
  a span.tooltip {display:none;}
  a:hover span.tooltip {position:fixed;top:30px;left:20px;display:inline;border:2px solid black;background-color:white;}
  a.dot {border-bottom: 1px dotted #000; text-decoration: none;}
  </style>
</head>
<body>
<h2>Statistics</h2>
<table>
<tr><td>Number of libraries</td><td>#numlibs#</td></tr>
<tr><td>Number of models</td><td>#nummodels#</td></tr>
</table>
<h2>Tested branches</h2>
<table>
<tr><th>Branch</th><th>Version</th><th>Build time</th><th>Execution time</th><th># Simulate</th><th># Total</th></tr>
#branches#
</table>
#entries#
</body>
</html>
