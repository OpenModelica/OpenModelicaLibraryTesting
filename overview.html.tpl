<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>#title#</title>
  <style>
  :root {
    --text: #1f2328;
    --muted: #59636e;
    --border: #d8dee4;
    --rule: #eaeef2;
    --head: #f3f5f8;
    --page: #f6f8fa;
    --card: #ffffff;
    --accent: #2f6fd0;
    --invalid: #f6c3c3;
    --invalid-text: #b42318;
  }
  body {
    margin: 0 24px 24px;
    background: var(--page);
    color: var(--text);
    font: 14px/1.45 system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  }
  a {color: var(--accent); text-decoration: none;}
  a:hover {text-decoration: underline;}
  h1 {font-size: 20px; margin: 0;}
  h2 {font-size: 17px; margin: 24px 0 8px;}
  h3 {font-size: 16px; margin: 0 0 4px;}

  header.toolbar {
    position: sticky; top: 0; z-index: 1;
    display: flex; flex-wrap: wrap; align-items: center; gap: 12px 24px;
    margin: 0 -24px 16px; padding: 10px 24px;
    background: var(--card); border-bottom: 1px solid var(--border);
  }
  header.toolbar .label {color: var(--muted);}

  .switch {display: inline-flex; border: 1px solid var(--border); border-radius: 6px; overflow: hidden; background: var(--card);}
  .switch button {
    font: inherit; font-size: 13px; padding: 4px 12px; margin: 0;
    border: 0; background: transparent; color: var(--text); cursor: pointer;
  }
  .switch button + button {border-left: 1px solid var(--border);}
  .switch button:hover {background: var(--head);}
  .switch button[aria-pressed="true"] {background: var(--accent); color: #fff;}
  .switch button:focus-visible {outline: 2px solid var(--accent); outline-offset: -2px;}

  .stats {display: flex; flex-wrap: wrap; gap: 12px;}
  .stat {background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 8px 16px; min-width: 120px;}
  .stat .value {display: block; font-size: 22px; font-weight: 600; font-variant-numeric: tabular-nums;}
  .stat .name {color: var(--muted);}
  .stat.invalid {border-color: var(--invalid);}
  .stat.invalid .value {color: var(--invalid-text);}
  p.note {color: var(--muted); max-width: 70em;}

  table {border-collapse: collapse; margin: 4px 0 12px; background: var(--card); font-variant-numeric: tabular-nums;}
  caption {caption-side: top; text-align: left; color: var(--muted); font-size: 12px; padding: 4px 0;}
  th, td {padding: 3px 10px; border-bottom: 1px solid var(--rule); text-align: right; white-space: nowrap;}
  th {background: var(--head); font-weight: 600; border-bottom: 1px solid var(--border);}
  th:first-child, td:first-child {text-align: left;}
  table.branches td:nth-child(-n+3) {text-align: left;}
  table.versions td, table.versions th {text-align: left;}
  td.warning {background-color: #ffd27a;}
  td.better {background-color: #9be89b;}
  td.warningPerformance {background-color: #FFFC66;}
  td.betterPerformance {background-color: #00FAFF;}
  .view-invalid th {background: #fbe3e3;}

  section.library {background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 12px 16px 4px; margin: 12px 0;}
  section.library table {background: transparent;}
  p.version {margin: 0 0 6px; color: var(--muted);}
  .badge {display: inline-block; margin: 6px 0; background: var(--invalid); color: var(--invalid-text); font-weight: 600; border-radius: 999px; padding: 2px 10px;}
  span.cross {color: #d00000; font-weight: bold;}
  details {margin: 4px 0 8px;}
  summary {cursor: pointer; color: var(--muted);}
  details p {margin: 4px 0 0 16px;}

  [data-view] > .view {display: none;}
  [data-view="valid"] > .view-valid,
  [data-view="all"] > .view-all,
  [data-view="invalid"] > .view-invalid {display: block;}
  </style>
</head>
<body>
<header class="toolbar">
  <h1>#title#</h1>
  <span class="label">Invalid models:</span>
  #viewSwitch#
</header>
<h2>Statistics</h2>
<div class="stats">
  <div class="stat"><span class="value">#numlibs#</span><span class="name">libraries</span></div>
  <div class="stat"><span class="value">#nummodels#</span><span class="name">models</span></div>
  <div class="stat invalid"><span class="value">#numinvalid#</span><span class="name">invalid models</span></div>
</div>
<p class="note">A model is invalid if the newest run of #invalidBranch# on its library translated it only because
--warnNonStandardModelica turned the errors of non-standard Modelica into warnings. The buttons at the top
select if the counts and times leave the invalid models out (the default), include them, or count only them.</p>
<h2>Tested branches</h2>
<div id="branches" data-view="valid">
#branches#
</div>
<h2>Libraries</h2>
#entries#
<script>
for (const button of document.querySelectorAll('.switch button')) {
  button.addEventListener('click', () => {
    for (const b of button.parentElement.querySelectorAll('button')) {
      b.setAttribute('aria-pressed', b === button);
    }
    for (const container of document.querySelectorAll('[data-view]')) {
      container.dataset.view = button.dataset.show;
    }
  });
}
</script>
</body>
</html>
