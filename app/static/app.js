const state = { tf: 'H1', window: window.DEFAULT_WINDOW || 50, pair: 'EURUSD', index: 'DXY' };
let chart = null;

const fmtPair = p => p.slice(0, 3) + '/' + p.slice(3);
const idxName = i => (i === 'DXY' ? 'DXY' : i.replace('-EW', ' index'));
const signed = (x, d = 2) => (x == null ? '–' : (x > 0 ? '+' : '') + x.toFixed(d));
const pct = x => (x == null ? '–' : Math.round(x * 100) + '%');
const cap = s => (s ? s[0].toUpperCase() + s.slice(1) : '');
const setText = (id, t) => { document.getElementById(id).textContent = t; };

document.querySelectorAll('#tf button').forEach(b => b.addEventListener('click', () => {
  document.querySelectorAll('#tf button').forEach(x => x.classList.remove('on')); b.classList.add('on');
  state.tf = b.dataset.v; refresh();
}));
document.querySelectorAll('#win button').forEach(b => b.addEventListener('click', () => {
  document.querySelectorAll('#win button').forEach(x => x.classList.remove('on')); b.classList.add('on');
  state.window = parseInt(b.dataset.v, 10); refresh();
}));

async function getJSON(url, attempt = 0) {
  try {
    const r = await fetch(url, { cache: 'no-store' });
    if (!r.ok) throw new Error(`${url}: ${r.status}`);
    return await r.json();
  } catch (e) {                      // dropped connection mid-request: retry a couple of times
    if (attempt < 2 && !(e.message || '').includes(': 4')) {
      await new Promise(res => setTimeout(res, 500 * (attempt + 1)));
      return getJSON(url, attempt + 1);
    }
    throw e;
  }
}

async function refresh() {
  await loadSummary();
  await loadPair();
  if (activeTab === 'map') await loadMap();
}

// ---------------------------------------------------------------- tabs
let activeTab = 'grid';
document.querySelectorAll('.tabs button').forEach(b => b.addEventListener('click', () => {
  document.querySelectorAll('.tabs button').forEach(x => x.classList.remove('on')); b.classList.add('on');
  activeTab = b.dataset.tab;
  document.getElementById('tab-grid').hidden = activeTab !== 'grid';
  document.getElementById('tab-map').hidden = activeTab !== 'map';
  if (activeTab === 'map') loadMap().catch(e => setText('map-info', `Could not load the map (${e.message}).`));
}));

// ---------------------------------------------------------------- 3D currency map
const BLOC_COLOR = { dollar: '#2a78d6', other: '#d95926' };
let Graph = null, mapData = null, mapKey = '', mapFrozen = false, mapIs3D = true;

function linkColor(l) {
  if (l.health === 'BREAKDOWN') return '#B4B2A9';
  if ((l.health || '').startsWith('WARNING')) return '#EF9F27';
  return l.rho > 0 ? '#1D9E75' : '#E24B4A';
}

function visibleLinks(d) {
  const min = document.getElementById('map-strong').checked ? 0.6 : 0.3;
  return d.links.filter(l => l.rho != null && (Math.abs(l.rho) >= min || l.health === 'BREAKDOWN'))
    .map(l => ({ source: l.source, target: l.target, rho: l.rho, health: l.health, rho_lo: l.rho_lo, rho_hi: l.rho_hi }));
}

async function loadMap() {
  const key = `${state.tf}|${state.window}`;
  if (key !== mapKey || !mapData) {
    mapData = await getJSON(`/api/map?tf=${state.tf}&window=${state.window}`);
    mapKey = key;
  }
  const d = mapData;
  setText('map-asof', `${d.tf}, ${d.window}-bar window · latest bar ${d.asof.slice(0, 16).replace('T', ' ')} UTC`);
  const names = Object.keys(d.blocs);
  setText('leg-dollar', `${names[0]}: ${d.blocs[names[0]].join(' ')}`);
  setText('leg-other', `${names[1]}: ${d.blocs[names[1]].join(' ')}`);
  if (!Graph) initGraph();
  const nodes = d.nodes.map(n => ({ id: n.id, s: n.strength_pct, bloc: n.bloc, bloc_name: n.bloc_name }));
  Graph.graphData({ nodes, links: visibleLinks(d) });
  if (!document.getElementById('map-info').textContent) {
    const broken = d.links.filter(l => l.health === 'BREAKDOWN').length;
    const off = d.links.filter(l => (l.health || '').startsWith('WARNING')).length;
    setText('map-info', `Sphere size = move over the last ${d.bars} ${d.tf} bars. Bloc colours come from the ${d.bloc_basis}; links from the current ${d.window}-bar window. ${off} link${off === 1 ? '' : 's'} outside the normal band, ${broken} broken. Click a sphere for detail.`);
  }
}

function initGraph() {
  const el = document.getElementById('map');
  const webgl = !!document.createElement('canvas').getContext('webgl');
  mapIs3D = webgl && typeof ForceGraph3D !== 'undefined';
  const factory = mapIs3D ? ForceGraph3D : (typeof ForceGraph !== 'undefined' ? ForceGraph : null);
  if (!factory) { el.textContent = 'The map library could not be loaded (no internet for the CDN?).'; return; }
  Graph = factory()(el)
    .width(el.clientWidth).height(el.clientHeight)
    .nodeColor(n => BLOC_COLOR[n.bloc] || '#888')
    .nodeVal(n => 1.5 + Math.min(Math.abs(n.s || 0), 2) * 2)
    .nodeLabel(n => `${n.id} · ${signed(n.s)}% over the last ${mapData.bars} ${mapData.tf} bars · ${n.bloc_name}`)
    .linkColor(linkColor)
    .linkWidth(l => Math.max(0.4, Math.abs(l.rho) * 2.2))
    .onNodeClick(n => renderNodeInfo(n));
  if (mapIs3D) {
    Graph.backgroundColor('#f4f3ef').showNavInfo(false).nodeOpacity(0.95).linkOpacity(0.55);
    Graph.cameraPosition({ x: 0, y: 40, z: 330 });
    const ctl = Graph.controls(); ctl.autoRotate = true; ctl.autoRotateSpeed = 0.6;
    startLabelLoop(el);
  } else {
    Graph.nodeCanvasObjectMode(() => 'after').nodeCanvasObject((n, ctx) => {
      ctx.font = '4px sans-serif'; ctx.fillStyle = BLOC_COLOR[n.bloc]; ctx.textAlign = 'center';
      ctx.fillText(`${n.id} ${signed(n.s, 1)}%`, n.x, n.y - 7);
    });
  }
  Graph.d3Force('link').distance(l => (l.rho > 0 ? 40 + (1 - l.rho) * 90 : 170 + Math.abs(l.rho) * 60));
  Graph.d3Force('charge').strength(-140);
  window.addEventListener('resize', () => Graph.width(el.clientWidth));
  document.getElementById('map-freeze').addEventListener('click', function () {
    mapFrozen = !mapFrozen;
    if (mapIs3D) { Graph.controls().autoRotate = !mapFrozen; if (mapFrozen) Graph.pauseAnimation(); else Graph.resumeAnimation(); }
    else { if (mapFrozen) Graph.pauseAnimation(); else Graph.resumeAnimation(); }
    this.textContent = mapFrozen ? 'Resume' : 'Freeze';
  });
  document.getElementById('map-strong').addEventListener('change', () => { if (mapData) loadMap(); });
}

// HTML labels floated over the 3D canvas, repositioned every frame from the graph's own
// projection — no dependency on the graph library's internal three.js instance.
function startLabelLoop(el) {
  const box = document.getElementById('map-labels');
  const labels = new Map();
  (function tick() {
    if (Graph && !document.getElementById('tab-map').hidden) {
      const { nodes } = Graph.graphData();
      for (const n of nodes) {
        if (n.x == null) continue;
        let lbl = labels.get(n.id);
        if (!lbl) {
          lbl = document.createElement('div'); lbl.className = 'lbl'; lbl.style.color = BLOC_COLOR[n.bloc] || '#444';
          box.appendChild(lbl); labels.set(n.id, lbl);
        }
        const p = Graph.graph2ScreenCoords(n.x, n.y, n.z);
        lbl.textContent = `${n.id} ${signed(n.s, 1)}%`;
        lbl.style.color = BLOC_COLOR[n.bloc] || '#444';
        lbl.style.left = `${p.x}px`; lbl.style.top = `${p.y - 10}px`;
        lbl.hidden = p.x < 0 || p.y < 0 || p.x > el.clientWidth || p.y > el.clientHeight;
      }
    }
    requestAnimationFrame(tick);
  })();
}

function renderNodeInfo(n) {
  const d = mapData;
  const mine = d.links.filter(l => l.source === n.id || l.target === n.id)
    .map(l => ({ other: l.source === n.id ? l.target : l.source, rho: l.rho, health: l.health }))
    .filter(l => l.rho != null).sort((a, b) => b.rho - a.rho);
  const withC = mine.filter(l => l.rho >= 0.4).map(l => `${l.other} ${signed(l.rho)}`).join(', ') || 'none';
  const against = mine.filter(l => l.rho <= -0.4).reverse().map(l => `${l.other} ${signed(l.rho)}`).join(', ') || 'none';
  const odd = mine.filter(l => l.health !== 'HEALTHY' && l.health !== 'NO_LINK').map(l => `${l.other} (${d.labels[l.health].toLowerCase()})`).join(', ');
  setText('map-info', `${n.id} · ${signed(n.s)}% over the last ${d.bars} ${d.tf} bars · ${n.bloc_name}. Moves with: ${withC}. Moves against: ${against}.${odd ? ' Not normal: ' + odd + '.' : ''}`);
}

async function loadSummary() {
  const d = await getJSON(`/api/summary?tf=${state.tf}&window=${state.window}`);
  setText('asof', d.asof ? `Latest bar ${d.asof.slice(0, 16).replace('T', ' ')} UTC · ${d.tf}, ${d.window}-bar window` : '');
  fillIndexOptions(d.indices);
  renderGrid(d);
  renderAnomalies(d);
}

function renderGrid(d) {
  const t = document.getElementById('grid');
  let html = '<thead><tr><th></th>' + d.indices.map(i => `<th>${idxName(i)}</th>`).join('') + '</tr></thead><tbody>';
  for (const p of d.pairs) {
    html += `<tr><th class="p">${fmtPair(p)}</th>`;
    for (const i of d.indices) {
      const c = (d.cells[p] || {})[i];
      if (!c) { html += '<td class="c non">–</td>'; continue; }
      const cls = c.sign === 'INVERSE' ? 'inv' : c.sign === 'DIRECT' ? 'dir' : 'non';
      const h = c.health === 'BREAKDOWN' ? ' broken' : (c.health || '').startsWith('WARNING') ? ' warn' : '';
      const sel = (p === state.pair && i === state.index) ? ' sel' : '';
      const title = `${fmtPair(p)} vs ${idxName(i)} — correlation ${signed(c.rho)}, ${d.labels[c.health].toLowerCase()}`;
      html += `<td class="c ${cls}${h}${sel}" data-p="${p}" data-i="${i}" title="${title}">${signed(c.beta)}</td>`;
    }
    html += '</tr>';
  }
  t.innerHTML = html + '</tbody>';
  t.querySelectorAll('td.c[data-p]').forEach(td => td.addEventListener('click', () => {
    state.pair = td.dataset.p; state.index = td.dataset.i;
    t.querySelectorAll('td.sel').forEach(x => x.classList.remove('sel')); td.classList.add('sel');
    loadPair();
    document.getElementById('focus').scrollIntoView({ behavior: 'smooth', block: 'start' });
  }));
}

function renderAnomalies(d) {
  const counts = Object.entries(d.health_counts).map(([k, v]) => `${d.labels[k]}: ${v}`).join(' · ');
  setText('counts', counts);
  const ul = document.getElementById('anomalies');
  ul.innerHTML = d.anomalies.length ? d.anomalies.map(a =>
    `<li class="${a.health}"><b>${fmtPair(a.pair)}</b> vs ${idxName(a.index)} — ${d.labels[a.health].toLowerCase()}: ` +
    `correlation ${signed(a.rho)}, normal ${signed(a.rho_lo)} to ${signed(a.rho_hi)}, ratio ${signed(a.beta)}×</li>`).join('')
    : '<li>Nothing outside its normal band.</li>';
}

async function loadPair() {
  const d = await getJSON(`/api/pair/${state.pair}?index=${state.index}&tf=${state.tf}&window=${state.window}`);
  renderTiles(d);
  renderSplit(d);
  renderChart(d);
  await loadWhatIf();
}

// ---------------------------------------------------------------- what if
const wiIndex = document.getElementById('wi-index');
const wiMove = document.getElementById('wi-move');
let wiTouched = false;   // once the user picks an index, stop following the focused cell

wiIndex.addEventListener('change', () => { wiTouched = true; loadWhatIf(); });
wiMove.addEventListener('input', () => { clearTimeout(wiMove._t); wiMove._t = setTimeout(loadWhatIf, 250); });

function fillIndexOptions(indices) {
  if (wiIndex.options.length === indices.length) return;
  wiIndex.innerHTML = indices.map(i => `<option value="${i}">${idxName(i)}</option>`).join('');
}

async function loadWhatIf() {
  if (!wiIndex.options.length) return;
  if (!wiTouched) wiIndex.value = state.index;
  const move = parseFloat(wiMove.value);
  const tbody = document.getElementById('wi-table');
  if (!Number.isFinite(move) || move < -25 || move > 25) {
    setText('wi-note', 'enter a move between −25 and +25%');
    tbody.innerHTML = '';
    return;
  }
  const d = await getJSON(`/api/whatif?index=${wiIndex.value}&move=${move}&tf=${state.tf}&window=${state.window}`);
  setText('wi-note', `${d.reliable_count} of ${d.results.length} pairs have a reliable link right now`);
  const rows = d.results.map(r => {
    const cls = r.implied_pct > 0 ? 'up' : r.implied_pct < 0 ? 'down' : '';
    const conf = r.reliable
      ? `${cap(r.strength)} · explains ${Math.round(r.r2 * 100)}%${r.beta_normal ? '' : ' · ratio not normal'}`
      : 'no reliable link';
    return `<tr class="${r.reliable ? '' : 'dim'}"><td>${fmtPair(r.pair)}</td>` +
      `<td class="num ${cls}">${signed(r.implied_pct)}%</td>` +
      `<td class="num">${signed(r.implied_lo)}% to ${signed(r.implied_hi)}%</td>` +
      `<td>${conf}</td></tr>`;
  }).join('');
  tbody.innerHTML = '<thead><tr><th>Pair</th><th class="num">Implied move</th>' +
    '<th class="num">Usual range for that ratio</th><th>Reliability</th></tr></thead><tbody>' + rows + '</tbody>';
}

function renderTiles(d) {
  const r = d.reading, P = fmtPair(d.pair), I = idxName(d.index);
  setText('focus-title', `${P} vs ${I}`);
  const pill = document.getElementById('pill');
  pill.textContent = d.label || 'Not enough history';
  pill.className = 'pill ' + (r ? r.health : '');
  if (!r) { ['t-way', 't-ratio', 't-rel'].forEach(id => setText(id, '–')); return; }
  const way = r.sign === 'INVERSE' ? 'Inverse' : r.sign === 'DIRECT' ? 'Direct' : 'None';
  setText('t-way', way);
  setText('t-way-s', r.sign === 'INVERSE' ? `${I} up → ${P} down` : r.sign === 'DIRECT' ? `${I} up → ${P} up` : 'no reliable relationship right now');
  setText('t-ratio', `${signed(r.beta)}×`);
  setText('t-ratio-s', `${I} +1% → ${P} ${signed(r.beta)}% · normal ${signed(r.beta_lo)} to ${signed(r.beta_hi)}`);
  setText('t-rel', cap(r.strength));
  setText('t-rel-s', `correlation ${signed(r.rho)} · R² ${r.r2.toFixed(2)} · normal ${signed(r.rho_lo)} to ${signed(r.rho_hi)}`);
}

function renderSplit(d) {
  const a = d.attribution, P = fmtPair(d.pair);
  setText('split-pair', P);
  const base = document.getElementById('seg-base'), quote = document.getElementById('seg-quote');
  if (!a) { setText('split-text', 'No attribution available.'); base.style.flex = quote.style.flex = 1; return; }
  setText('split-window', `last ${a.bars} ${d.tf} bars`);
  const b = Math.abs(a.base_contrib_pct), q = Math.abs(a.quote_contrib_pct), tot = (b + q) || 1;
  base.style.flex = String(Math.max(b / tot, 0.04)); quote.style.flex = String(Math.max(q / tot, 0.04));
  base.textContent = `${d.base} ${signed(a.base_contrib_pct)}%`;
  quote.textContent = `${d.quote} ${signed(a.quote_contrib_pct)}%`;
  const driver = Math.abs(a.quote_share) >= Math.abs(a.base_share) ? d.quote : d.base;
  setText('split-text', `${P} moved ${signed(a.move_pct)}%: the ${d.base} side contributed ${signed(a.base_contrib_pct)}% (${pct(a.base_share)} of the move), ` +
    `the ${d.quote} side ${signed(a.quote_contrib_pct)}% (${pct(a.quote_share)}). Mostly a ${driver} move.`);
}

function renderChart(d) {
  const s = d.series, r = d.reading;
  const labels = s.t.map(x => x.slice(5, 16).replace('T', ' '));
  const flat = v => labels.map(() => v);
  const data = { labels, datasets: [
    { label: 'band top', data: flat(r ? r.rho_hi : null), borderWidth: 0, pointRadius: 0, backgroundColor: 'rgba(29,158,117,0.16)' },
    { label: 'band bottom', data: flat(r ? r.rho_lo : null), borderWidth: 0, pointRadius: 0, fill: '-1', backgroundColor: 'rgba(29,158,117,0.16)' },
    { label: 'correlation', data: s.rho, borderColor: '#2a78d6', borderWidth: 2, pointRadius: 0, tension: 0.15 },
    { label: 'no-link +', data: flat(0.4), borderColor: '#EF9F27', borderDash: [6, 4], borderWidth: 1, pointRadius: 0 },
    { label: 'no-link −', data: flat(-0.4), borderColor: '#EF9F27', borderDash: [6, 4], borderWidth: 1, pointRadius: 0 },
  ]};
  const options = {
    responsive: true, maintainAspectRatio: false, animation: false,
    interaction: { mode: 'index', intersect: false },
    plugins: { legend: { display: false }, tooltip: { filter: i => i.dataset.label === 'correlation',
      callbacks: { label: i => `correlation ${signed(i.parsed.y)}` } } },
    scales: {
      y: { min: -1, max: 1, ticks: { stepSize: 0.5, color: '#8c8b85' }, grid: { color: '#e6e5df' } },
      x: { ticks: { maxTicksLimit: 8, color: '#8c8b85', maxRotation: 0 }, grid: { display: false } },
    },
  };
  if (chart) { chart.data = data; chart.options = options; chart.update(); }
  else chart = new Chart(document.getElementById('chart'), { type: 'line', data, options });
}

// ---------------------------------------------------------------- live status
let lastSnapshot = null;
const fmtAge = min => (min < 1 ? 'just now' : min < 60 ? `${Math.round(min)} min ago` : `${(min / 60).toFixed(1)} h ago`);

function renderLive(s) {
  const el = document.getElementById('live'), hb = s.heartbeat;
  if (!hb) { el.className = 'live off'; el.textContent = 'Live updater not running — showing the last snapshot'; return; }
  const age = (Date.now() - Date.parse(hb.last_success_utc || hb.last_run_utc)) / 60000;
  if (hb.status === 'error') {
    el.className = 'live warn';
    el.textContent = `Updater hit an error (last good update ${fmtAge(age)}): ${hb.error}`;
  } else if (age > s.stale_minutes) {
    el.className = 'live warn';
    el.textContent = `Data is ${fmtAge(age).replace(' ago', ' old')} — the updater may have stopped`;
  } else {
    el.className = 'live on';
    el.textContent = `Live · updated ${fmtAge(age)} · every ${s.refresh_minutes} min${hb.market_open === false ? ' · market closed' : ''}`;
  }
}

async function pollStatus() {
  try {
    const s = await getJSON('/api/status');
    renderLive(s);
    if (lastSnapshot !== null && s.snapshot !== lastSnapshot) {   // a new snapshot landed: redraw, keep selection
      mapKey = '';
      await refresh();
    }
    lastSnapshot = s.snapshot;
  } catch (e) { /* keep the last known state; try again next round */ }
  setTimeout(pollStatus, 30000);
}

refresh().catch(e => {
  console.error(e);
  setText('asof', `Could not load data (${e && e.message ? e.message : e}) — if output/ is empty, run scripts/run_matrix.py first.`);
});
pollStatus();
