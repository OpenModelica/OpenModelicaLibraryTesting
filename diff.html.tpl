<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>#title#</title>
<style>
body { margin: 0; font: 14px sans-serif; color: #222; background: #fff; display: flex; flex-direction: column; height: 100vh; }
header { padding: 8px 12px; border-bottom: 1px solid #ccc; }
h1 { font-size: 16px; margin: 0 0 4px; overflow-wrap: anywhere; }
main { flex: 1; display: flex; min-height: 0; }
nav { width: 340px; flex-shrink: 0; display: flex; flex-direction: column; border-right: 1px solid #ccc; }
input { margin: 8px; padding: 4px; }
ul { margin: 0; padding: 0; list-style: none; overflow-y: auto; flex: 1; }
li { padding: 3px 8px; cursor: pointer; overflow-wrap: anywhere; }
li:hover { background: #eee; }
li.selected { background: #cfe2ff; }
section { flex: 1; min-width: 0; padding: 8px; display: flex; flex-direction: column; }
canvas { flex: 1; min-height: 0; width: 100%; }
#legend span { margin-right: 16px; }
.reference { color: #1f6fd0; }
.result { color: #d03c3c; }
@media (max-width: 700px) { main { flex-direction: column; } nav { width: auto; height: 35%; border-right: 0; border-bottom: 1px solid #ccc; } }
</style>
</head>
<body>
<header>
<h1>#title#</h1>
<span id="summary"></span>
<a id="omplot" hidden>Tube comparison in OMPlot</a>
</header>
<main>
<nav><input id="filter" type="search" placeholder="Filter variables"><ul id="vars"></ul></nav>
<section>
<div id="legend"><span class="reference">&#9644; reference</span><span class="result">&#9644; result</span><span id="stats"></span></div>
<canvas id="plot"></canvas>
<small>Drag to zoom the time axis, double-click to reset.</small>
</section>
</main>
<script>
const FILES = { result: "#result#", reference: "#reference#" };

async function gunzip(base64) {
  const bytes = Uint8Array.from(atob(base64), (c) => c.charCodeAt(0));
  const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'));
  return new Response(stream).arrayBuffer();
}

// MATLAB v4 result file, as written by filterSimulationResults
function readMatrices(buffer) {
  const view = new DataView(buffer), matrices = {};
  const readers = { 0: ['getFloat64', 8], 1: ['getFloat32', 4], 2: ['getInt32', 4], 3: ['getInt16', 2], 4: ['getUint16', 2], 5: ['getUint8', 1] };
  let pos = 0;
  while (pos < buffer.byteLength) {
    const [mopt, rows, cols, , nameLength] = [0, 4, 8, 12, 16].map((o) => view.getInt32(pos + o, true));
    pos += 20;
    const name = new TextDecoder().decode(new Uint8Array(buffer, pos, nameLength - 1));
    pos += nameLength;
    const [get, size] = readers[Math.floor(mopt / 10) % 10];
    const data = new Float64Array(rows * cols);
    for (let i = 0; i < data.length; i++, pos += size) data[i] = view[get](pos, true);
    matrices[name] = { rows, cols, data };
  }
  return matrices;
}

function readResult(buffer) {
  const m = readMatrices(buffer);
  const aclass = m.Aclass;
  const at = (matrix, row, col) => matrix.data[col * matrix.rows + row];
  const text = (length, get) => String.fromCharCode(...Array.from({ length }, (_, k) => get(k)));
  // binTrans: a column per time step in data_*, a column per variable in name and dataInfo. binNormal: the opposite.
  const trans = text(8, (k) => at(aclass, 3, k)) === 'binTrans';
  const info = (matrix, variable, k) => (trans ? at(matrix, k, variable) : at(matrix, variable, k));
  const value = (matrix, variable, step) => (trans ? at(matrix, variable, step) : at(matrix, step, variable));
  const count = trans ? m.name.cols : m.name.rows, width = trans ? m.name.rows : m.name.cols;
  const steps = trans ? m.data_2.cols : m.data_2.rows, series = {};
  for (let i = 0; i < count; i++) {
    const name = text(width, (k) => info(m.name, i, k)).replace(/[\0 ]+$/, '');
    // Table 0 is the abscissa, the first variable of data_2. Table 1 holds constants.
    const index = info(m.dataInfo, i, 0), col = info(m.dataInfo, i, 1);
    const table = index === 1 ? m.data_1 : m.data_2;
    const c = Math.abs(col) - 1, sign = Math.sign(col) || 1;
    series[name] = Float64Array.from({ length: steps }, (_, k) => sign * value(table, c, index === 1 ? 0 : k));
    if (index === 0 || /^time$/i.test(name)) series.time = series[name];
  }
  return series;
}

function interpolate(xs, ys, x) {
  let lo = 0, hi = xs.length - 1;
  if (x <= xs[0]) return ys[0];
  if (x >= xs[hi]) return ys[hi];
  while (hi - lo > 1) { const mid = (lo + hi) >> 1; if (xs[mid] <= x) lo = mid; else hi = mid; }
  return xs[hi] === xs[lo] ? ys[hi] : ys[lo] + (ys[hi] - ys[lo]) * (x - xs[lo]) / (xs[hi] - xs[lo]);
}

function maxDifference(result, reference, name) {
  let max = 0;
  reference.time.forEach((t, i) => { max = Math.max(max, Math.abs(interpolate(result.time, result[name], t) - reference[name][i])); });
  return max;
}

function niceTicks(min, max, count) {
  const step = (max - min) / count || 1, base = 10 ** Math.floor(Math.log10(step));
  const nice = [1, 2, 5, 10].map((f) => f * base).find((s) => s >= step);
  const ticks = [];
  for (let t = Math.ceil(min / nice) * nice; t <= max + nice * 1e-9; t += nice) ticks.push(Math.abs(t) < nice * 1e-9 ? 0 : t);
  return ticks;
}

function draw(canvas, curves, range, dragFrom, dragTo) {
  const ratio = window.devicePixelRatio || 1, width = canvas.clientWidth, height = canvas.clientHeight;
  canvas.width = width * ratio;
  canvas.height = height * ratio;
  const g = canvas.getContext('2d');
  g.scale(ratio, ratio);
  const left = 80, right = 16, top = 8, bottom = 28;
  let min = Infinity, max = -Infinity;
  for (const { xs, ys } of curves) {
    xs.forEach((x, i) => { if (x >= range[0] && x <= range[1] && Number.isFinite(ys[i])) { min = Math.min(min, ys[i]); max = Math.max(max, ys[i]); } });
  }
  if (!(min < max)) { const v = Number.isFinite(min) ? min : 0, d = Math.abs(v) * 0.1 || 1; min = v - d; max = v + d; }
  const X = (x) => left + (x - range[0]) / (range[1] - range[0] || 1) * (width - left - right);
  const Y = (y) => height - bottom - (y - min) / (max - min) * (height - top - bottom);
  g.font = '12px sans-serif';
  g.strokeStyle = '#e4e4e4';
  g.fillStyle = '#444';
  g.textAlign = 'center';
  for (const t of niceTicks(range[0], range[1], 8)) {
    g.beginPath(); g.moveTo(X(t), top); g.lineTo(X(t), height - bottom); g.stroke();
    g.fillText(Number(t.toPrecision(6)), X(t), height - bottom + 16);
  }
  g.textAlign = 'right';
  for (const t of niceTicks(min, max, 6)) {
    g.beginPath(); g.moveTo(left, Y(t)); g.lineTo(width - right, Y(t)); g.stroke();
    g.fillText(Number(t.toPrecision(5)), left - 6, Y(t) + 4);
  }
  g.save();
  g.beginPath(); g.rect(left, top, width - left - right, height - top - bottom); g.clip();
  for (const { xs, ys, color } of curves) {
    g.strokeStyle = color;
    g.lineWidth = 1.5;
    g.beginPath();
    xs.forEach((x, i) => g.lineTo(X(x), Y(ys[i])));
    g.stroke();
  }
  g.restore();
  if (dragFrom !== undefined) {
    g.fillStyle = 'rgba(0, 0, 0, 0.1)';
    g.fillRect(Math.min(dragFrom, dragTo), top, Math.abs(dragTo - dragFrom), height - top - bottom);
  }
  return (px) => range[0] + (px - left) / (width - left - right) * (range[1] - range[0]);
}

(async () => {
  const result = readResult(await gunzip(FILES.result));
  const reference = readResult(await gunzip(FILES.reference));
  const canvas = document.getElementById('plot'), list = document.getElementById('vars');
  const names = Object.keys(reference).filter((n) => n in result && !/^time$/i.test(n)).sort();
  const fullRange = [Math.min(result.time[0], reference.time[0]),
                     Math.max(result.time[result.time.length - 1], reference.time[reference.time.length - 1])];
  let current = names[0], range = fullRange, toTime, dragFrom;

  const render = (dragTo) => {
    if (!current) return;
    toTime = draw(canvas, [
      { xs: reference.time, ys: reference[current], color: '#1f6fd0' },
      { xs: result.time, ys: result[current], color: '#d03c3c' },
    ], range, dragFrom, dragTo);
  };
  const select = (name) => {
    current = name;
    for (const li of list.children) li.classList.toggle('selected', li.textContent === name);
    document.getElementById('stats').textContent = current + ', largest difference ' + maxDifference(result, reference, current).toPrecision(3);
    render();
  };
  for (const name of names) {
    const li = document.createElement('li');
    li.textContent = name;
    li.onclick = () => select(name);
    list.append(li);
  }
  document.getElementById('summary').textContent = names.length + ' differing variables.';
  document.getElementById('filter').oninput = (e) => {
    const text = e.target.value.toLowerCase();
    for (const li of list.children) li.hidden = !li.textContent.toLowerCase().includes(text);
  };
  canvas.onmousedown = (e) => { dragFrom = e.offsetX; };
  canvas.onmousemove = (e) => { if (dragFrom !== undefined) render(e.offsetX); };
  canvas.onmouseup = (e) => {
    if (dragFrom !== undefined && Math.abs(e.offsetX - dragFrom) > 4) {
      const a = toTime(Math.min(dragFrom, e.offsetX)), b = toTime(Math.max(dragFrom, e.offsetX));
      range = [Math.max(a, fullRange[0]), Math.min(b, fullRange[1])];
    }
    dragFrom = undefined;
    render();
  };
  canvas.ondblclick = () => { range = fullRange; render(); };
  window.onresize = () => render();
  if (current) select(current);
})().catch((e) => { document.getElementById('summary').textContent = 'Could not read the results: ' + e; });

// The OMPlot page fetches the files itself, so they must be public and allow
// cross-origin reads: never the case for file://.
if (location.protocol.startsWith('http')) {
  const omplot = document.getElementById('omplot');
  const abs = (f) => encodeURIComponent(new URL(f, location.href).href);
  omplot.href = 'https://playground.openmodelica.org/latest/omplot/?result=' + abs("#basename#.mat") + '&reference=' + abs("#basename#.ref.mat");
  omplot.hidden = false;
}
</script>
</body>
</html>
