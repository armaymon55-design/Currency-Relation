// Static edition: every number is precomputed into data/*.json by public/build.py.
const state = { window: 50, pair: 'EURUSD', index: 'USD-EW' };
let META = null, SUMMARY = null, ATT = null, chart = null;
const seriesCache = {};

const fmtPair = p => p.slice(0, 3) + '/' + p.slice(3);
const idxName = i => i.replace('-EW', ' basket');
const signed = (x, d = 2) => (x == null ? '–' : (x > 0 ? '+' : '') + x.toFixed(d));
const pct = x => (x == null ? '–' : Math.round(x * 100) + '%');
const cap = s => (s ? s[0].toUpperCase() + s.slice(1) : '');
const setText = (id, t) => { document.getElementById(id).textContent = t; };
const LINK = 0.4;

async function getJSON(url, attempt = 0) {
  try {
    const r = await fetch(url, { cache: 'no-cache' });
    if (!r.ok) throw new Error(`${url}: ${r.status}`);
    return await r.json();
  } catch (e) {
    if (attempt < 2) { await new Promise(res => setTimeout(res, 500 * (attempt + 1))); return getJSON(url, attempt + 1); }
    throw e;
  }
}

document.querySelectorAll('#win button').forEach(b => b.addEventListener('click', () => {
  document.querySelectorAll('#win button').forEach(x => x.classList.remove('on')); b.classList.add('on');
  state.window = parseInt(b.dataset.v, 10); refresh();
}));

async function boot() {
  META = await getJSON('data/meta.json');
  ATT = await getJSON('data/attribution.json');
  document.getElementById('src-link').href = META.source.url;
  const gen = META.generated.slice(0, 16).replace('T', ' ');
  setText('asof', `Daily · latest ECB fix ${META.asof_date} · ${META.days.toLocaleString()} trading days since ${META.history_from}`);
  const live = document.getElementById('live');
  live.className = 'live on'; live.textContent = `Rebuilt ${gen} UTC · refreshes every working day after the 16:00 CET fix`;
  fillIndexOptions(META.indices);
  await refresh();
}

async function refresh() {
  SUMMARY = await getJSON(`data/summary_w${state.window}.json`);
  renderGrid(SUMMARY); renderAnomalies(SUMMARY);
  await loadPair();
  if (activeTab === 'map') await loadMap();
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
      html += `<td class="c ${cls}${h}${sel}" data-p="${p}" data-i="${i}" title="${fmtPair(p)} vs ${idxName(i)} — correlation ${signed(c.rho)}, ${d.labels[c.health].toLowerCase()}">${signed(c.beta)}</td>`;
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
  setText('counts', Object.entries(d.health_counts).map(([k, v]) => `${d.labels[k]}: ${v}`).join(' · '));
  document.getElementById('anomalies').innerHTML = d.anomalies.length ? d.anomalies.map(a =>
    `<li class="${a.health}"><b>${fmtPair(a.pair)}</b> vs ${idxName(a.index)} — ${d.labels[a.health].toLowerCase()}: correlation ${signed(a.rho)}, normal ${signed(a.rho_lo)} to ${signed(a.rho_hi)}, ratio ${signed(a.beta)}×</li>`).join('')
    : '<li>Nothing outside its normal band.</li>';
}

async function loadPair() {
  const cell = (SUMMARY.cells[state.pair] || {})[state.index];
  renderTiles(cell); renderSplit(); await renderChart(); renderWhatIf();
}

function renderTiles(r) {
  const P = fmtPair(state.pair), I = idxName(state.index);
  setText('focus-title', `${P} vs ${I}`);
  const pill = document.getElementById('pill');
  pill.textContent = r ? META.labels[r.health] : 'Not enough history';
  pill.className = 'pill ' + (r ? r.health : '');
  if (!r) { ['t-way', 't-ratio', 't-rel'].forEach(id => setText(id, '–')); return; }
  setText('t-way', r.sign === 'INVERSE' ? 'Inverse' : r.sign === 'DIRECT' ? 'Direct' : 'None');
  setText('t-way-s', r.sign === 'INVERSE' ? `${I} up → ${P} down` : r.sign === 'DIRECT' ? `${I} up → ${P} up` : 'no reliable relationship right now');
  setText('t-ratio', `${signed(r.beta)}×`);
  setText('t-ratio-s', `${I} +1% → ${P} ${signed(r.beta)}% · normal ${signed(r.beta_lo)} to ${signed(r.beta_hi)}`);
  setText('t-rel', cap(r.strength));
  setText('t-rel-s', `correlation ${signed(r.rho)} · R² ${r.r2.toFixed(2)} · normal ${signed(r.rho_lo)} to ${signed(r.rho_hi)}`);
}

function renderSplit() {
  const a = ATT.rows[state.pair], P = fmtPair(state.pair);
  setText('split-pair', P); setText('split-window', `latest trading day (${META.asof_date})`);
  const base = document.getElementById('seg-base'), quote = document.getElementById('seg-quote');
  if (!a) { setText('split-text', 'No attribution available.'); return; }
  const b = Math.abs(a.base_contrib_pct), q = Math.abs(a.quote_contrib_pct), tot = (b + q) || 1;
  base.style.flex = String(Math.max(b / tot, 0.04)); quote.style.flex = String(Math.max(q / tot, 0.04));
  base.textContent = `${a.base} ${signed(a.base_contrib_pct)}%`; quote.textContent = `${a.quote} ${signed(a.quote_contrib_pct)}%`;
  const driver = Math.abs(a.quote_share) >= Math.abs(a.base_share) ? a.quote : a.base;
  setText('split-text', `${P} moved ${signed(a.move_pct)}%: the ${a.base} side contributed ${signed(a.base_contrib_pct)}% (${pct(a.base_share)} of the move), the ${a.quote} side ${signed(a.quote_contrib_pct)}% (${pct(a.quote_share)}). Mostly a ${driver} move.`);
}

async function renderChart() {
  if (!seriesCache[state.pair]) seriesCache[state.pair] = await getJSON(`data/series/${state.pair}.json`);
  const s = seriesCache[state.pair], w = String(state.window), r = (SUMMARY.cells[state.pair] || {})[state.index];
  const labels = s.t[w], rho = s.rho[w][state.index];
  const flat = v => labels.map(() => v);
  const data = { labels, datasets: [
    { label: 'band top', data: flat(r ? r.rho_hi : null), borderWidth: 0, pointRadius: 0, backgroundColor: 'rgba(29,158,117,0.16)' },
    { label: 'band bottom', data: flat(r ? r.rho_lo : null), borderWidth: 0, pointRadius: 0, fill: '-1', backgroundColor: 'rgba(29,158,117,0.16)' },
    { label: 'correlation', data: rho, borderColor: '#2a78d6', borderWidth: 2, pointRadius: 0, tension: 0.15 },
    { label: 'no-link +', data: flat(LINK), borderColor: '#EF9F27', borderDash: [6, 4], borderWidth: 1, pointRadius: 0 },
    { label: 'no-link −', data: flat(-LINK), borderColor: '#EF9F27', borderDash: [6, 4], borderWidth: 1, pointRadius: 0 },
  ]};
  const options = { responsive: true, maintainAspectRatio: false, animation: false, interaction: { mode: 'index', intersect: false },
    plugins: { legend: { display: false }, tooltip: { filter: i => i.dataset.label === 'correlation', callbacks: { label: i => `correlation ${signed(i.parsed.y)}` } } },
    scales: { y: { min: -1, max: 1, ticks: { stepSize: 0.5, color: '#8c8b85' }, grid: { color: '#e6e5df' } },
              x: { ticks: { maxTicksLimit: 8, color: '#8c8b85', maxRotation: 0 }, grid: { display: false } } } };
  if (chart) { chart.data = data; chart.options = options; chart.update(); }
  else chart = new Chart(document.getElementById('chart'), { type: 'line', data, options });
}

// ---------------------------------------------------------------- what if (computed here from the grid's own ratios)
const wiIndex = document.getElementById('wi-index'), wiMove = document.getElementById('wi-move');
let wiTouched = false;
wiIndex.addEventListener('change', () => { wiTouched = true; renderWhatIf(); });
wiMove.addEventListener('input', () => { clearTimeout(wiMove._t); wiMove._t = setTimeout(renderWhatIf, 250); });
function fillIndexOptions(indices) { wiIndex.innerHTML = indices.map(i => `<option value="${i}">${idxName(i)}</option>`).join(''); }

function renderWhatIf() {
  if (!wiTouched) wiIndex.value = state.index;
  const move = parseFloat(wiMove.value), tbody = document.getElementById('wi-table');
  if (!Number.isFinite(move) || move < -25 || move > 25) { setText('wi-note', 'enter a move between −25 and +25%'); tbody.innerHTML = ''; return; }
  const rows = SUMMARY.pairs.map(p => {
    const c = (SUMMARY.cells[p] || {})[wiIndex.value];
    if (!c || c.beta == null) return null;
    const ends = [c.beta_lo * move, c.beta_hi * move].sort((a, b) => a - b);
    return { pair: p, implied: c.beta * move, lo: ends[0], hi: ends[1], r2: c.r2, strength: c.strength,
             reliable: c.health !== 'NO_LINK' && Math.abs(c.rho) >= LINK, beta_normal: c.beta_normal };
  }).filter(Boolean).sort((a, b) => (a.reliable === b.reliable ? Math.abs(b.implied) - Math.abs(a.implied) : (a.reliable ? -1 : 1)));
  setText('wi-note', `${rows.filter(r => r.reliable).length} of ${rows.length} pairs have a reliable link right now`);
  tbody.innerHTML = '<thead><tr><th>Pair</th><th class="num">Implied move</th><th class="num">Usual range for that ratio</th><th>Reliability</th></tr></thead><tbody>' +
    rows.map(r => `<tr class="${r.reliable ? '' : 'dim'}"><td>${fmtPair(r.pair)}</td><td class="num ${r.implied > 0 ? 'up' : r.implied < 0 ? 'down' : ''}">${signed(r.implied)}%</td>` +
      `<td class="num">${signed(r.lo)}% to ${signed(r.hi)}%</td><td>${r.reliable ? `${cap(r.strength)} · explains ${Math.round(r.r2 * 100)}%${r.beta_normal ? '' : ' · ratio not normal'}` : 'no reliable link'}</td></tr>`).join('') + '</tbody>';
}

// ---------------------------------------------------------------- tabs + 3D map
let activeTab = 'grid';
document.querySelectorAll('.tabs button').forEach(b => b.addEventListener('click', () => {
  document.querySelectorAll('.tabs button').forEach(x => x.classList.remove('on')); b.classList.add('on');
  activeTab = b.dataset.tab;
  document.getElementById('tab-grid').hidden = activeTab !== 'grid';
  document.getElementById('tab-map').hidden = activeTab !== 'map';
  if (activeTab === 'map') loadMap().catch(e => setText('map-info', `Could not load the map (${e.message}).`));
}));

const BLOC_COLOR = { dollar: '#2a78d6', other: '#d95926' };
let Graph = null, mapData = null, mapKey = '', mapFrozen = false, mapIs3D = true;
const linkColor = l => l.health === 'BREAKDOWN' ? '#B4B2A9' : (l.health || '').startsWith('WARNING') ? '#EF9F27' : (l.rho > 0 ? '#1D9E75' : '#E24B4A');
function visibleLinks(d) {
  const min = document.getElementById('map-strong').checked ? 0.6 : 0.3;
  return d.links.filter(l => l.rho != null && (Math.abs(l.rho) >= min || l.health === 'BREAKDOWN'))
    .map(l => ({ source: l.source, target: l.target, rho: l.rho, health: l.health }));
}
async function loadMap() {
  const key = String(state.window);
  if (key !== mapKey || !mapData) { mapData = await getJSON(`data/map_w${state.window}.json`); mapKey = key; }
  const d = mapData;
  setText('map-asof', `${d.window}-day window · latest fix ${META.asof_date}`);
  const names = Object.keys(d.blocs);
  setText('leg-dollar', `${names[0]}: ${d.blocs[names[0]].join(' ')}`); setText('leg-other', `${names[1]}: ${d.blocs[names[1]].join(' ')}`);
  if (!Graph) initGraph();
  Graph.graphData({ nodes: d.nodes.map(n => ({ id: n.id, s: n.strength_pct, bloc: n.bloc, bloc_name: n.bloc_name })), links: visibleLinks(d) });
  if (!document.getElementById('map-info').textContent) {
    const broken = d.links.filter(l => l.health === 'BREAKDOWN').length, off = d.links.filter(l => (l.health || '').startsWith('WARNING')).length;
    setText('map-info', `Bloc colours come from the ${d.bloc_basis}; links from the current ${d.window}-day window. ${off} link${off === 1 ? '' : 's'} outside the normal band, ${broken} broken. Click a sphere for detail.`);
  }
}
function initGraph() {
  const el = document.getElementById('map');
  mapIs3D = !!document.createElement('canvas').getContext('webgl') && typeof ForceGraph3D !== 'undefined';
  const factory = mapIs3D ? ForceGraph3D : (typeof ForceGraph !== 'undefined' ? ForceGraph : null);
  if (!factory) { el.textContent = 'The map library could not be loaded.'; return; }
  Graph = factory()(el).width(el.clientWidth).height(el.clientHeight)
    .nodeColor(n => BLOC_COLOR[n.bloc] || '#888').nodeVal(n => 1.5 + Math.min(Math.abs(n.s || 0), 2) * 2)
    .nodeLabel(n => `${n.id} · ${signed(n.s)}% on the latest day · ${n.bloc_name}`)
    .linkColor(linkColor).linkWidth(l => Math.max(0.4, Math.abs(l.rho) * 2.2)).onNodeClick(n => renderNodeInfo(n));
  if (mapIs3D) {
    Graph.backgroundColor('#f4f3ef').showNavInfo(false).nodeOpacity(0.95).linkOpacity(0.55).cameraPosition({ x: 0, y: 40, z: 330 });
    const ctl = Graph.controls(); ctl.autoRotate = true; ctl.autoRotateSpeed = 0.6;
    startLabelLoop(el);
  } else {
    Graph.nodeCanvasObjectMode(() => 'after').nodeCanvasObject((n, ctx) => { ctx.font = '4px sans-serif'; ctx.fillStyle = BLOC_COLOR[n.bloc]; ctx.textAlign = 'center'; ctx.fillText(`${n.id} ${signed(n.s, 1)}%`, n.x, n.y - 7); });
  }
  Graph.d3Force('link').distance(l => (l.rho > 0 ? 40 + (1 - l.rho) * 90 : 170 + Math.abs(l.rho) * 60));
  Graph.d3Force('charge').strength(-140);
  window.addEventListener('resize', () => Graph.width(el.clientWidth));
  document.getElementById('map-freeze').addEventListener('click', function () {
    mapFrozen = !mapFrozen;
    if (mapIs3D) Graph.controls().autoRotate = !mapFrozen;
    if (mapFrozen) Graph.pauseAnimation(); else Graph.resumeAnimation();
    this.textContent = mapFrozen ? 'Resume' : 'Freeze';
  });
  document.getElementById('map-strong').addEventListener('change', () => { if (mapData) loadMap(); });
}
function startLabelLoop(el) {
  const box = document.getElementById('map-labels'), labels = new Map();
  (function tick() {
    if (Graph && !document.getElementById('tab-map').hidden) {
      for (const n of Graph.graphData().nodes) {
        if (n.x == null) continue;
        let lbl = labels.get(n.id);
        if (!lbl) { lbl = document.createElement('div'); lbl.className = 'lbl'; box.appendChild(lbl); labels.set(n.id, lbl); }
        const p = Graph.graph2ScreenCoords(n.x, n.y, n.z);
        lbl.textContent = `${n.id} ${signed(n.s, 1)}%`; lbl.style.color = BLOC_COLOR[n.bloc] || '#444';
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
    .map(l => ({ other: l.source === n.id ? l.target : l.source, rho: l.rho, health: l.health })).filter(l => l.rho != null).sort((a, b) => b.rho - a.rho);
  const withC = mine.filter(l => l.rho >= LINK).map(l => `${l.other} ${signed(l.rho)}`).join(', ') || 'none';
  const against = mine.filter(l => l.rho <= -LINK).reverse().map(l => `${l.other} ${signed(l.rho)}`).join(', ') || 'none';
  const odd = mine.filter(l => l.health !== 'HEALTHY' && l.health !== 'NO_LINK').map(l => `${l.other} (${d.labels[l.health].toLowerCase()})`).join(', ');
  setText('map-info', `${n.id} · ${signed(n.s)}% on the latest day · ${n.bloc_name}. Moves with: ${withC}. Moves against: ${against}.${odd ? ' Not normal: ' + odd + '.' : ''}`);
}

boot().catch(e => { console.error(e); setText('asof', `Could not load data (${e.message}).`); document.getElementById('live').textContent = 'Data unavailable'; });
