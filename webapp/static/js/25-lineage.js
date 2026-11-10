/* ---------------- Lineage & Knowledge map (P13): one SVG map component shared by Lineage (#/lineage), the Knowledge map
   (#/graph) and Integration analytics (#/integrations). Layouts: data flow (columns by hop), network, radial, or fixed
   columns; colour by type / status / direction (upstream orange, downstream blue); keyboard reachable (Tab between
   items, Enter opens, arrows move, Esc clears); readable at every zoom (labels never go below 11 px on screen); the
   table view underneath is the relief for screen readers and small screens. Colours are tokens only. ---------------- */
(function lineageStyles() {
  document.head.append(h('style', {}, `
  :root{--up:var(--c2);--down:var(--c1)}
  .lmap-wrap{position:relative;border:1px solid var(--line);border-radius:var(--radius);background:var(--surface);overflow:hidden;min-height:300px}
  .lmap{display:block;width:100%;height:100%;touch-action:none;cursor:grab;user-select:none}.lmap.panning{cursor:grabbing}
  .lmap text{font-family:var(--font);fill:var(--ink);pointer-events:none}
  .lmap .lnode{cursor:pointer;outline:none}.lmap .lnode rect{fill:var(--surface);stroke:var(--line-2);stroke-width:1.4}
  .lmap .lnode:focus-visible rect{stroke:var(--accent);stroke-width:3}
  .lmap .lnode.sel rect{stroke-width:2.8}.lmap .lnode.focus rect{stroke-width:2.4}
  .lmap .lnode.up rect{fill:color-mix(in srgb,var(--up) 12%,var(--surface));stroke:var(--up)}
  .lmap .lnode.down rect{fill:color-mix(in srgb,var(--down) 12%,var(--surface));stroke:var(--down)}
  .lmap .lnode.sel.up rect,.lmap .lnode.sel.down rect{stroke-width:2.8}
  .lmap .ledge{fill:none;stroke:var(--line-2);stroke-width:1.6}.lmap .ledge.up{stroke:var(--up)}.lmap .ledge.down{stroke:var(--down)}.lmap .ledge.hi{stroke:var(--accent)}.lmap .ledge.sel{stroke-width:2.8}
  .lmap .ledge.st-ok{stroke:var(--ok)}.lmap .ledge.st-warn{stroke:var(--warn);stroke-width:2.4}.lmap .ledge.st-bad{stroke:var(--err);stroke-width:2.4;stroke-dasharray:6 4}.lmap .ledge.st-mute{stroke:var(--faint);stroke-dasharray:2 4}
  .lmap .ehit{stroke:transparent;stroke-width:14;fill:none;cursor:pointer}
  .lmap .dim{opacity:.2}
  .lmap .elab{font-size:10.5px;fill:var(--ink-2)}
  .lmap .badge circle{fill:var(--err)}.lmap .badge text{fill:var(--primary-ink);font-weight:700;font-size:10.5px}
  .lmap .mk-line{fill:var(--line-2)}.lmap .mk-up{fill:var(--up)}.lmap .mk-down{fill:var(--down)}.lmap .mk-hi{fill:var(--accent)}.lmap .mk-ok{fill:var(--ok)}.lmap .mk-warn{fill:var(--warn)}.lmap .mk-bad{fill:var(--err)}.lmap .mk-mute{fill:var(--faint)}
  .lzoom{position:absolute;right:10px;bottom:10px;display:flex;gap:6px;z-index:2}
  .lzoom .iconbtn,.lzoom .btn{background:var(--surface);border:1px solid var(--line-2);min-width:30px;height:30px;border-radius:7px;display:inline-grid;place-items:center;cursor:pointer;color:var(--ink);padding:0 6px}
  .lzoom .iconbtn:disabled{opacity:.4;cursor:default}
  .lempty{position:absolute;inset:0;display:grid;place-items:center;color:var(--ink-2);padding:20px;text-align:center;font-size:13.5px}
  .lcombo{position:relative;flex:1;min-width:220px}.lcombo input{width:100%}
  .lcombo .lopts{position:absolute;left:0;right:0;top:100%;z-index:30;background:var(--surface);border:1px solid var(--line-2);border-radius:var(--radius-sm);box-shadow:var(--shadow-lg);max-height:280px;overflow:auto;margin-top:4px;padding:4px 0}
  .lcombo .lopt{padding:7px 10px;cursor:pointer;display:flex;gap:8px;align-items:center;font-size:13px}.lcombo .lopt.on,.lcombo .lopt:hover{background:var(--side-hover)}.lcombo .lopt small{color:var(--ink-2);margin-left:auto;white-space:nowrap}
  .kv-list{display:grid;grid-template-columns:110px 1fr;gap:5px 10px;font-size:13px;margin:0}.kv-list dt{color:var(--ink-2)}.kv-list dd{margin:0;overflow-wrap:anywhere}
  .lkind{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:5px;vertical-align:-1px}
  .lcheck{display:inline-flex;align-items:center;gap:6px;font-size:12.5px;border:1px solid var(--line-2);border-radius:var(--radius-sm);padding:4px 10px;background:var(--surface);cursor:pointer;color:var(--ink)}.lcheck.on{background:var(--accent-tint);border-color:var(--accent);color:var(--accent)}
  .lcheck input{margin:0}
  .lside{position:sticky;top:12px}.toolbar[hidden]{display:none}
  .lnote{font-size:12.5px;color:var(--ink-2);margin-top:6px}
  .risk{display:block;width:100%;text-align:left;border:1px solid var(--line);border-radius:var(--radius-sm);background:var(--surface);padding:10px 12px;cursor:pointer;color:var(--ink);font:inherit}.risk:hover{border-color:var(--accent)}
  @media (max-width:760px){.lmap-wrap{min-height:260px}.lside{position:static}.kv-list{grid-template-columns:90px 1fr}}
  `));
})();

const LIN_FAMILY = {table: 'data', column: 'data', entity: 'semantic', measure: 'semantic', report: 'consumer', page: 'consumer', job: 'mover', flow: 'mover', bot: 'mover', api: 'mover', queue: 'mover', file_drop: 'mover', system: 'system', owner: 'people'};
const LIN_FAMILY_COL = {data: 'var(--c1)', semantic: 'var(--c3)', consumer: 'var(--primary)', mover: 'var(--c2)', system: 'var(--ink)', people: 'var(--faint)'};
const LIN_FAMILY_NAME = {data: 'Tables & columns', semantic: 'Measures & entities', consumer: 'Reports & pages', mover: 'Jobs, flows, bots & APIs', system: 'Systems', people: 'Owners'};
const LIN_KIND_NAME = {table: 'Table', column: 'Column', job: 'Job', flow: 'Flow', bot: 'Bot', report: 'Report', page: 'Page', measure: 'Measure', api: 'API', file_drop: 'File drop', queue: 'Queue', system: 'System', owner: 'Owner', entity: 'Entity'};
const LIN_STATUS_COL = {ok: 'var(--ok)', warn: 'var(--warn)', bad: 'var(--err)', mute: 'var(--faint)', none: 'var(--line-2)'};
const kindColour = k => LIN_FAMILY_COL[LIN_FAMILY[k] || 'system'];
function statusKey(s) {
  const t = String(s || '').toLowerCase();
  if (!t) return 'none';
  if (/healthy|published|^ok$|success|active|online|proven/.test(t)) return 'ok';
  if (/fail|error|broken|expired|^bad$/.test(t)) return 'bad';
  if (/risk|degrad|slow|draft|warn|review|expir|paused/.test(t)) return 'warn';
  if (/owner|unknown|mute|retired|orphan/.test(t)) return 'mute';
  return 'none';
}
const hashParams = () => new URLSearchParams((location.hash.split('?')[1] || ''));
const lesc = s => String(s == null ? '' : s).replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));

/* ---------- the map component ---------- */
function lineageMap(opts = {}) {
  const st = {layout: opts.layout || 'flow', colour: opts.colour || 'type', data: {nodes: [], edges: []}, pos: {}, sel: null, focus: null,
    vb: {x: 0, y: 0, w: 1000, h: 560}, ext: {x: 0, y: 0, w: 1000, h: 560}, nodeH: opts.nodeH || 32, big: !!opts.big, dimOthers: opts.dimOthers !== false};
  const svg = sv('svg', {class: 'lmap', role: 'group', 'aria-label': opts.label || 'Map', preserveAspectRatio: 'xMidYMid meet'});
  const defs = sv('defs');
  ['line', 'up', 'down', 'hi', 'ok', 'warn', 'bad', 'mute'].forEach(k => { const m = sv('marker', {id: 'lm-' + k, viewBox: '0 0 10 10', refX: 9, refY: 5, markerWidth: 7, markerHeight: 7, orient: 'auto-start-reverse'}); m.append(sv('path', {d: 'M0 0L10 5L0 10z', class: 'mk-' + k})); defs.append(m); });
  const gE = sv('g'), gN = sv('g');
  svg.append(defs, gE, gN);
  const empty = h('div', {class: 'lempty', hidden: true});
  const zin = h('button', {class: 'iconbtn', type: 'button', 'aria-label': 'Zoom in', title: 'Zoom in (+)', onclick: () => zoomBy(1.25)}, icon('plus'));
  const zout = h('button', {class: 'iconbtn', type: 'button', 'aria-label': 'Zoom out', title: 'Zoom out (−)', onclick: () => zoomBy(0.8)}, icon('x'));
  zout.replaceChildren(h('span', {'aria-hidden': 'true', style: 'font-weight:700;font-size:16px;line-height:1'}, '−'));
  const zfit = h('button', {class: 'iconbtn', type: 'button', 'aria-label': 'Fit the map to the screen', title: 'Fit', onclick: () => fit()}, icon('target'));
  const wrap = h('div', {class: 'lmap-wrap', style: `height:${opts.height || 520}px`}, svg, empty, h('div', {class: 'lzoom'}, zout, zfit, zin));
  const byId = () => Object.fromEntries(st.data.nodes.map(n => [n.id, n]));
  const flow = e => e.kind === 'contains' ? [e.to, e.from] : [e.from, e.to];        // [upstream, downstream]
  const labelOf = n => { const l = n.label || n.name || n.id; return l.length > 32 ? l.slice(0, 31) + '…' : l; };
  const widthOf = n => st.big ? Math.max(150, Math.min(220, labelOf(n).length * 7.2 + 36)) : Math.max(110, Math.min(230, labelOf(n).length * 6.8 + 34));

  function layout() {
    const nodes = st.data.nodes, edges = st.data.edges, pos = {};
    if (!nodes.length) { st.pos = pos; return; }
    const H = st.big ? 48 : st.nodeH, rowGap = H + (st.big ? 24 : 14);
    const adj = {}; edges.forEach(e => { (adj[e.from] = adj[e.from] || []).push(e.to); (adj[e.to] = adj[e.to] || []).push(e.from); });
    const ring = {};                                                     // BFS distance from the focus (for radial / network)
    const focus = st.focus && nodes.some(n => n.id === st.focus) ? st.focus : nodes[0].id;
    { const q = [focus]; ring[focus] = 0; while (q.length) { const a = q.shift(); (adj[a] || []).forEach(b => { if (ring[b] == null) { ring[b] = ring[a] + 1; q.push(b); } }); } }
    nodes.forEach(n => { if (ring[n.id] == null) ring[n.id] = 1 + Math.max(0, ...Object.values(ring)); });
    if (st.layout === 'flow' || st.layout === 'columns') {
      const colOf = n => st.layout === 'columns' && n.col != null ? n.col : (n.hop != null ? n.hop : ring[n.id]);
      const cols = {}; nodes.forEach(n => (cols[colOf(n)] = cols[colOf(n)] || []).push(n));
      const keys = Object.keys(cols).map(Number).sort((a, b) => a - b);
      keys.forEach(k => cols[k].sort((a, b) => labelOf(a).localeCompare(labelOf(b))));
      const order = {}; const setOrder = () => keys.forEach(k => cols[k].forEach((n, i) => order[n.id] = i));
      setOrder();
      for (let pass = 0; pass < 3; pass++) {                              // barycentre ordering reduces crossings
        keys.forEach((k, ki) => { if (!ki) return;
          cols[k].sort((a, b) => { const bc = n => { const nb = (adj[n.id] || []).filter(x => order[x] != null && colOf(byId()[x]) === keys[ki - 1]); return nb.length ? nb.reduce((s, x) => s + order[x], 0) / nb.length : order[n.id]; }; return bc(a) - bc(b); });
          setOrder(); });
      }
      const colW = {}; keys.forEach(k => colW[k] = Math.max(...cols[k].map(widthOf)));
      let x = 0;
      keys.forEach((k, ki) => {
        if (ki) x += colW[keys[ki - 1]] / 2 + 70 + colW[k] / 2;
        const n = cols[k].length;
        cols[k].forEach((nd, i) => { pos[nd.id] = {x, y: (i - (n - 1) / 2) * rowGap, w: widthOf(nd), h: H}; });
      });
    } else {
      const rings = {}; nodes.forEach(n => (rings[ring[n.id]] = rings[ring[n.id]] || []).push(n));
      const ang = {};
      Object.keys(rings).map(Number).sort((a, b) => a - b).forEach(r => {
        const list = rings[r];
        if (r > 0) list.sort((a, b) => { const pa = n => { const p = (adj[n.id] || []).find(x => ring[x] === r - 1); return p ? ang[p] : 0; }; return pa(a) - pa(b); });
        const R = r === 0 ? 0 : Math.max(190 * r, list.length * (st.big ? 150 : 120) / (2 * Math.PI));
        list.forEach((n, i) => { const a = -Math.PI / 2 + i * 2 * Math.PI / Math.max(1, list.length); ang[n.id] = a; pos[n.id] = {x: Math.cos(a) * R * 1.3, y: Math.sin(a) * R, w: widthOf(n), h: H}; });
      });
      if (st.layout === 'network' && nodes.length > 1) {                     // a few deterministic force steps from the radial start
        const ids = nodes.map(n => n.id), k = 150, N = ids.length;
        for (let it = 0, t = 40; it < 120 && N <= 400; it++, t *= .97) {
          const dx = {}, dy = {}; ids.forEach(i => { dx[i] = 0; dy[i] = 0; });
          for (let a = 0; a < N; a++) for (let b = a + 1; b < N; b++) { const pa = pos[ids[a]], pb = pos[ids[b]]; let vx = pa.x - pb.x, vy = pa.y - pb.y; let d = Math.hypot(vx, vy) || .1; const f = k * k / d / d * 8; vx /= d; vy /= d; dx[ids[a]] += vx * f; dy[ids[a]] += vy * f; dx[ids[b]] -= vx * f; dy[ids[b]] -= vy * f; }
          edges.forEach(e => { const pa = pos[e.from], pb = pos[e.to]; if (!pa || !pb) return; const vx = pb.x - pa.x, vy = pb.y - pa.y, d = Math.hypot(vx, vy) || .1; const f = (d - k) / d * .12; dx[e.from] += vx * f; dy[e.from] += vy * f; dx[e.to] -= vx * f; dy[e.to] -= vy * f; });
          ids.forEach(i => { const p = pos[i]; if (i === focus) return; dx[i] -= p.x * .012; dy[i] -= p.y * .012; const d = Math.hypot(dx[i], dy[i]) || .1, m = Math.min(d, t); p.x += dx[i] / d * m * 1.25; p.y += dy[i] / d * m; });
        }
      }
    }
    st.pos = pos;
    const xs = Object.values(pos), pad = 30;
    const minX = Math.min(...xs.map(p => p.x - p.w / 2)) - pad, maxX = Math.max(...xs.map(p => p.x + p.w / 2)) + pad;
    const minY = Math.min(...xs.map(p => p.y - p.h / 2)) - pad, maxY = Math.max(...xs.map(p => p.y + p.h / 2)) + pad;
    st.ext = {x: minX, y: minY, w: Math.max(200, maxX - minX), h: Math.max(120, maxY - minY)};
  }

  function edgePath(e) {
    const a = st.pos[e.from], b = st.pos[e.to];
    if (!a || !b) return null;
    if (st.layout === 'flow' || st.layout === 'columns') {
      const [u, d] = flow(e), pu = st.pos[u], pd = st.pos[d];
      if (Math.abs(pd.x - pu.x) < 20) {                                   // same column: bulge out to the right
        const x1 = pu.x + pu.w / 2, x2 = pd.x + pd.w / 2;
        return `M ${x1} ${pu.y} C ${x1 + 80} ${pu.y}, ${x2 + 80} ${pd.y}, ${x2} ${pd.y}`;
      }
      const left = pu.x <= pd.x;
      const x1 = pu.x + (left ? pu.w / 2 : -pu.w / 2), x2 = pd.x + (left ? -pd.w / 2 : pd.w / 2), y1 = pu.y, y2 = pd.y;
      const c = (x2 - x1) / 2;
      return `M ${x1} ${y1} C ${x1 + c} ${y1}, ${x2 - c} ${y2}, ${x2} ${y2}`;
    }
    const [u, d] = flow(e), pu = st.pos[u], pd = st.pos[d];
    const dx = pd.x - pu.x, dy = pd.y - pu.y, len = Math.hypot(dx, dy) || 1, ux = dx / len, uy = dy / len;
    const cut = (p, sign) => { const kx = Math.abs(ux) < 1e-6 ? 1e9 : (p.w / 2 + 6) / Math.abs(ux), ky = Math.abs(uy) < 1e-6 ? 1e9 : (p.h / 2 + 6) / Math.abs(uy); return Math.min(kx, ky); };
    const t1 = cut(pu), t2 = cut(pd);
    return `M ${pu.x + ux * t1} ${pu.y + uy * t1} L ${pd.x - ux * t2} ${pd.y - uy * t2}`;
  }

  function colourKey(e) {
    if (st.colour === 'status') return 'st-' + statusKey(e.status || (byId()[e.from] || {}).status);
    return '';
  }
  function markerFor(cls) {
    const m = /(?:^|\s)(up|down|hi|st-(ok|warn|bad|mute))(?:\s|$)/.exec(cls);
    return m ? (m[2] || m[1]) : 'line';
  }

  function render() {
    layout();
    gE.replaceChildren(); gN.replaceChildren();
    const nodes = byId();
    const sorted = [...st.data.nodes].sort((a, b) => (st.pos[a.id].x - st.pos[b.id].x) || (st.pos[a.id].y - st.pos[b.id].y));
    const els = {};
    st.data.edges.forEach(e => {
      const d = edgePath(e); if (!d) return;
      const p = sv('path', {d, class: 'ledge ' + colourKey(e), 'data-from': e.from, 'data-to': e.to});
      p.setAttribute('marker-end', `url(#lm-${markerFor(p.getAttribute('class'))})`);
      const hit = sv('path', {d, class: 'ehit'});
      const txt = `<b>${lesc((nodes[e.from] || {}).label || e.from)}</b> → <b>${lesc((nodes[e.to] || {}).label || e.to)}</b><br>${lesc(e.label || e.kind)}${e.status ? ' · ' + lesc(e.status) : ''}${e.signal ? '<br>' + lesc(e.signal) : ''}`;
      hit.addEventListener('mousemove', ev => tipOn(ev, txt)); hit.addEventListener('mouseleave', tipOff);
      hit.addEventListener('click', () => { if (opts.onEdge) opts.onEdge(e); });
      if (e.label && (st.layout === 'radial' || st.layout === 'network')) {
        const a = st.pos[e.from], b = st.pos[e.to];
        gE.append(sv('text', {x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 - 4, 'text-anchor': 'middle', class: 'elab'}, e.label));
      }
      gE.append(p, hit);
      e._el = p;
    });
    sorted.forEach((n, i) => {
      const p = st.pos[n.id], fam = LIN_FAMILY[n.kind] || 'system';
      const g = sv('g', {class: 'lnode' + (n.id === st.focus ? ' focus' : ''), tabindex: '0', role: 'button', 'data-id': n.id, transform: `translate(${p.x} ${p.y})`,
        'aria-label': `${n.label || n.name}, ${LIN_KIND_NAME[n.kind] || n.kind}${n.status ? ', ' + n.status : ''}${n.role === 'up' ? ', upstream' : n.role === 'down' ? ', downstream' : ''}`});
      const rx = fam === 'consumer' ? p.h / 2 : fam === 'people' ? 4 : 7;
      const rect = sv('rect', {x: -p.w / 2, y: -p.h / 2, width: p.w, height: p.h, rx});
      if (st.colour === 'type') rect.style.stroke = kindColour(n.kind);
      else if (st.colour === 'status') rect.style.stroke = LIN_STATUS_COL[statusKey(n.status)];
      if (fam === 'system') rect.style.strokeWidth = '1.8';
      if (fam === 'people') rect.setAttribute('stroke-dasharray', '4 3');
      g.append(rect);
      const dot = st.colour !== 'direction' && opts.dots !== false;
      if (dot) g.append(sv('circle', {cx: -p.w / 2 + 13, cy: 0, r: 4.5, style: `fill:${st.colour === 'status' ? LIN_STATUS_COL[statusKey(n.status)] : kindColour(n.kind)}`}));
      g.append(sv('text', {x: dot ? 6 : 0, y: 4.5, 'text-anchor': 'middle', style: `font-size:${st.big ? 14 : 12.5}px;font-weight:${n.id === st.focus || st.big ? 600 : 500}`}, labelOf(n)));
      if (n.badge) { const b = sv('g', {class: 'badge'}); b.append(sv('circle', {cx: p.w / 2 - 6, cy: -p.h / 2 + 2, r: 10}), sv('text', {x: p.w / 2 - 6, y: -p.h / 2 + 6, 'text-anchor': 'middle'}, String(n.badge))); g.append(b); }
      const tip = `<b>${lesc(n.label || n.name)}</b><br>${lesc(LIN_KIND_NAME[n.kind] || n.kind)}${n.system ? ' · ' + lesc(n.system) : ''}${n.status ? '<br>' + lesc(n.status) : ''}${n.owner ? '<br>Owner: ' + lesc(n.owner) : ''}`;
      g.addEventListener('mousemove', ev => tipOn(ev, tip)); g.addEventListener('mouseleave', tipOff);
      g.addEventListener('click', ev => { ev.stopPropagation(); activate(n.id); });
      g.addEventListener('keydown', ev => {
        if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); activate(n.id); }
        else if (ev.key === 'ArrowRight' || ev.key === 'ArrowDown') { ev.preventDefault(); const nx = sorted[i + 1]; if (nx) els[nx.id].focus(); }
        else if (ev.key === 'ArrowLeft' || ev.key === 'ArrowUp') { ev.preventDefault(); const pv = sorted[i - 1]; if (pv) els[pv.id].focus(); }
        else if (ev.key === 'Escape') { select(null); }
        else if (ev.key === '+' || ev.key === '=') zoomBy(1.25); else if (ev.key === '-') zoomBy(.8);
      });
      els[n.id] = g; n._el = g;
      gN.append(g);
    });
    empty.hidden = !!st.data.nodes.length;
    fit();
    if (st.sel) applySelection();
  }

  function activate(id) { select(id); if (opts.onSelect) opts.onSelect(byId()[id]); }
  function applySelection() {
    const nodes = byId(), id = st.sel;
    st.data.nodes.forEach(n => n._el && n._el.classList.remove('sel', 'up', 'down', 'dim'));
    st.data.edges.forEach(e => e._el && e._el.classList.remove('up', 'down', 'hi', 'dim', 'sel'));
    if (!id || !nodes[id]) return;
    const upAdj = {}, downAdj = {};
    st.data.edges.forEach(e => { const [u, d] = flow(e); (downAdj[u] = downAdj[u] || []).push([d, e]); (upAdj[d] = upAdj[d] || []).push([u, e]); });
    const walk = adj => { const seen = new Set(), es = new Set(), q = [id]; while (q.length) { const a = q.shift(); (adj[a] || []).forEach(([b, e]) => { es.add(e); if (!seen.has(b) && b !== id) { seen.add(b); q.push(b); } }); } return [seen, es]; };
    const [ups, upE] = walk(upAdj), [downs, downE] = walk(downAdj);
    const dir = st.colour === 'direction';
    st.data.nodes.forEach(n => {
      if (!n._el) return;
      if (n.id === id) n._el.classList.add('sel');
      else if (dir && ups.has(n.id)) n._el.classList.add('up');
      else if (dir && downs.has(n.id)) n._el.classList.add('down');
      else if (st.dimOthers && !(ups.has(n.id) || downs.has(n.id))) n._el.classList.add('dim');
    });
    st.data.edges.forEach(e => {
      if (!e._el) return;
      const inUp = upE.has(e), inDown = downE.has(e);
      if (dir && inUp) e._el.classList.add('up'); else if (dir && inDown) e._el.classList.add('down');
      else if (!dir && (e.from === id || e.to === id)) e._el.classList.add('hi');
      else if (!(inUp || inDown)) e._el.classList.add('dim');
      if (e.from === id || e.to === id) e._el.classList.add('sel');
      e._el.setAttribute('marker-end', `url(#lm-${markerFor(e._el.getAttribute('class'))})`);
    });
  }
  function select(id) { st.sel = id; applySelection(); }

  /* zoom: the viewBox; the smallest zoom keeps a 12.5 px label at 11 px on screen */
  const setVB = () => svg.setAttribute('viewBox', `${st.vb.x} ${st.vb.y} ${st.vb.w} ${st.vb.h}`);
  const screenW = () => Math.max(200, svg.clientWidth || wrap.clientWidth || 800), screenH = () => Math.max(160, svg.clientHeight || wrap.clientHeight || 500);
  const maxW = () => screenW() * 12.5 / 11;                                // widest viewBox that keeps labels readable
  function fit() {
    const sw = screenW(), sh = screenH();
    let w = st.ext.w, hh = st.ext.h;
    if (w / hh < sw / sh) w = hh * sw / sh; else hh = w * sh / sw;
    if (w > maxW()) { w = maxW(); hh = w * sh / sw; }
    const f = st.pos[st.focus] || st.pos[st.sel], big = st.ext.w > 1.8 * w || st.ext.h > 1.8 * hh;   // a map far wider than the screen centres on the focus
    const cx = f && big ? f.x : st.ext.x + st.ext.w / 2, cy = f && big ? f.y : st.ext.y + st.ext.h / 2;
    st.vb = {x: cx - w / 2, y: cy - hh / 2, w, h: hh};
    setVB(); zout.disabled = st.vb.w >= maxW() - .5;
  }
  function zoomBy(f) {
    const cx = st.vb.x + st.vb.w / 2, cy = st.vb.y + st.vb.h / 2;
    let w = st.vb.w / f; w = Math.max(screenW() / 3, Math.min(maxW(), w));
    const hh = w * st.vb.h / st.vb.w;
    st.vb = {x: cx - w / 2, y: cy - hh / 2, w, h: hh}; setVB(); zout.disabled = st.vb.w >= maxW() - .5;
  }
  let drag = null;
  svg.addEventListener('pointerdown', e => { if (e.target.closest('.lnode')) return; drag = {x: e.clientX, y: e.clientY, vx: st.vb.x, vy: st.vb.y}; svg.classList.add('panning'); svg.setPointerCapture(e.pointerId); });
  svg.addEventListener('pointermove', e => { if (!drag) return; const k = st.vb.w / screenW(); st.vb.x = drag.vx - (e.clientX - drag.x) * k; st.vb.y = drag.vy - (e.clientY - drag.y) * k; setVB(); });
  const endDrag = () => { drag = null; svg.classList.remove('panning'); };
  svg.addEventListener('pointerup', endDrag); svg.addEventListener('pointercancel', endDrag);
  svg.addEventListener('wheel', e => { if (!(e.ctrlKey || e.metaKey)) return; e.preventDefault(); zoomBy(e.deltaY < 0 ? 1.15 : .87); }, {passive: false});
  svg.addEventListener('click', e => { if (!e.target.closest('.lnode')) { select(null); if (opts.onClear) opts.onClear(); } });
  new ResizeObserver(() => { if (st.data.nodes.length) fit(); }).observe(wrap);

  function png(name) {
    const clone = svg.cloneNode(true);
    const walk = (a, b) => { const cs = getComputedStyle(a); ['fill', 'stroke', 'stroke-width', 'stroke-dasharray', 'opacity', 'font-size', 'font-weight', 'font-family'].forEach(p => { const v = cs.getPropertyValue(p); if (v) b.style.setProperty(p, v); });
      for (let i = 0; i < a.children.length; i++) if (b.children[i]) walk(a.children[i], b.children[i]); };
    walk(svg, clone);
    clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg'); clone.setAttribute('width', screenW() * 2); clone.setAttribute('height', screenH() * 2);
    const img = new Image(), url = URL.createObjectURL(new Blob([new XMLSerializer().serializeToString(clone)], {type: 'image/svg+xml'}));
    img.onload = () => { const c = document.createElement('canvas'); c.width = screenW() * 2; c.height = screenH() * 2; const ctx = c.getContext('2d'); ctx.fillStyle = getComputedStyle(document.documentElement).getPropertyValue('--surface') || '#fff'; ctx.fillRect(0, 0, c.width, c.height); ctx.drawImage(img, 0, 0); URL.revokeObjectURL(url);
      const a = document.createElement('a'); a.download = (name || 'map') + '.png'; a.href = c.toDataURL('image/png'); a.click(); };
    img.src = url;
  }
  return {
    el: wrap, state: st,
    draw(data, o = {}) { st.data = {nodes: (data.nodes || []).map(n => ({...n})), edges: (data.edges || []).map(e => ({...e}))}; st.focus = o.focus || data.focus || null; if (o.layout) st.layout = o.layout; if (o.colour) st.colour = o.colour; st.sel = o.select === undefined ? st.focus : o.select; render(); },
    select, fit, zoom: zoomBy, png, setLayout(l) { st.layout = l; render(); }, setColour(c) { st.colour = c; render(); },
    setEmpty(text) { empty.textContent = text; empty.hidden = false; }, nodes: () => st.data.nodes,
  };
}

/* ---------- a search box with suggestions from /api/lineage/search ---------- */
function lineageSearch({placeholder, label, onPick, kinds}) {
  const input = h('input', {type: 'search', placeholder: placeholder || 'Find a table, report, flow or bot…', 'aria-label': label || 'Search the map', role: 'combobox', 'aria-expanded': 'false', 'aria-autocomplete': 'list'});
  const list = h('div', {class: 'lopts', role: 'listbox', hidden: true}), box = h('div', {class: 'lcombo'}, input, list);
  let items = [], at = 0, timer = null;
  const close = () => { list.hidden = true; input.setAttribute('aria-expanded', 'false'); };
  const draw = () => {
    list.replaceChildren(...(items.length ? items.map((n, i) => h('div', {class: 'lopt' + (i === at ? ' on' : ''), role: 'option', 'aria-selected': String(i === at), onmousedown: e => { e.preventDefault(); pick(i); }},
      h('i', {class: 'lkind', style: `background:${kindColour(n.kind)}`}), h('span', {}, n.label), h('small', {}, `${LIN_KIND_NAME[n.kind] || n.kind}${n.system ? ' · ' + n.system : ''}`)))
      : [h('div', {class: 'lopt muted'}, 'Nothing matches.')]));
    list.hidden = false; input.setAttribute('aria-expanded', 'true');
  };
  const pick = i => { const n = items[i]; if (!n) return; input.value = n.label; close(); onPick(n); };
  input.addEventListener('input', () => { clearTimeout(timer); const q = input.value.trim(); if (!q) return close(); timer = setTimeout(async () => { try { items = (await api(`/api/lineage/search?q=${encodeURIComponent(q)}${kinds ? '&kind=' + kinds : ''}`)).items; at = 0; draw(); } catch (e) { notify(e.message, 'err'); } }, 180); });
  input.addEventListener('keydown', e => {
    if (list.hidden) { if (e.key === 'Enter' && input.value.trim()) { e.preventDefault(); input.dispatchEvent(new Event('input')); } return; }
    if (e.key === 'ArrowDown') { e.preventDefault(); at = Math.min(at + 1, items.length - 1); draw(); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); at = Math.max(at - 1, 0); draw(); }
    else if (e.key === 'Enter') { e.preventDefault(); pick(at); }
    else if (e.key === 'Escape') close();
  });
  input.addEventListener('blur', () => setTimeout(close, 120));
  return box;
}
const kindDot = k => h('i', {class: 'lkind', style: `background:${kindColour(k)}`, 'aria-hidden': 'true'});
const mapLegend = (mode, extra) => h('div', {class: 'legend'}, mode === 'status'
  ? [['Healthy', 'ok'], ['At risk / degraded', 'warn'], ['Failing (dashed)', 'bad'], ['No owner (dotted)', 'mute']].map(([l, k]) => h('span', {}, h('i', {style: `background:${LIN_STATUS_COL[k]}`}), l))
  : mode === 'direction' ? [h('span', {}, h('i', {style: 'background:var(--up)'}), 'Upstream — where its data comes from'), h('span', {}, h('i', {style: 'background:var(--down)'}), 'Downstream — what changes if it changes')]
  : Object.entries(LIN_FAMILY_NAME).map(([f, l]) => h('span', {}, h('i', {style: `background:${LIN_FAMILY_COL[f]}`}), l)), extra || null);
const mapTable = nodes => asTable(['Item', 'Kind', 'System', 'Role', 'Status'], nodes.map(n => [n.label || n.name, LIN_KIND_NAME[n.kind] || n.kind, n.system || '—', n.role === 'focus' ? 'focus' : n.role === 'up' ? `upstream (${Math.abs(n.hop || 0)} hop${Math.abs(n.hop || 0) === 1 ? '' : 's'})` : n.role === 'down' ? `downstream (${n.hop || 0} hop${n.hop === 1 ? '' : 's'})` : '—', n.status || '—']));
const LIN_KIND_GROUPS = [['Tables', ['table']], ['Columns', ['column']], ['Measures & entities', ['measure', 'entity']], ['Reports & pages', ['report', 'page']], ['Jobs, flows & bots', ['job', 'flow', 'bot', 'api', 'file_drop', 'queue']], ['Systems & owners', ['system', 'owner']]];
function kindChecks(state, onChange) {
  return LIN_KIND_GROUPS.map(([label, ks]) => { const on = ks.every(k => state.has(k));
    const cb = h('input', {type: 'checkbox', checked: on, onchange: () => { ks.forEach(k => cb.checked ? state.add(k) : state.delete(k)); onChange(); }});
    return h('label', {class: 'lcheck' + (on ? ' on' : '')}, cb, label); });
}
async function emptyMap(main, crumbs, title) {
  const me = S.me || {};
  main.replaceChildren(h('div', {class: 'page'}, pageHead({crumbs, eyebrow: brandName() + ' · Knowledge map', title}),
    h('div', {class: 'card empty'}, h('h3', {}, 'Nothing on the map yet'),
      h('div', {class: 'muted', style: 'max-width:560px;margin:0 auto'}, 'Relay builds the map from your dashboards (sources → model tables → measures → pages → report), the organisation ontology and the integrations it discovers. Publish a dashboard, add entities under Metrics & ontology, or scan a source under Integration analytics.'),
      h('div', {class: 'row', style: 'justify-content:center;margin-top:14px'},
        me.builder ? h('button', {class: 'btn primary', type: 'button', onclick: async e => { e.target.disabled = true; try { await api('/api/lineage/sync', {method: 'POST'}); route(); } catch (err) { notify(err.message, 'err'); e.target.disabled = false; } }}, icon('spark'), 'Build the map now') : null,
        h('a', {class: 'btn', href: '#/integrations'}, 'Integration analytics'), h('a', {class: 'btn', href: '#/metrics'}, 'Metrics & ontology')))));
}

/* ---------- #/lineage ---------- */
const LN = {focus: null, depth: 2, dir: 'both', kinds: new Set(['table', 'measure', 'entity', 'report', 'page', 'job', 'flow', 'bot', 'api', 'file_drop', 'queue', 'system', 'owner']), whole: false};
async function renderLineage() {
  const main = $('#main');
  if (!$('#lineagepage')) main.replaceChildren(h('div', {class: 'page'}, pageHead({crumbs: [['Home', '#/'], ['Knowledge map', '#/graph'], ['Lineage']], eyebrow: brandName() + ' · Knowledge map', title: 'Lineage'}), skel('cards')));
  const qp = hashParams();
  if (qp.get('focus')) { LN.focus = qp.get('focus'); LN.whole = false; }
  if (qp.get('depth')) LN.depth = Math.max(1, Math.min(6, +qp.get('depth') || 2));
  let sm;
  try { sm = await api('/api/lineage/summary'); } catch (e) { main.replaceChildren(h('div', {class: 'page'}, h('div', {class: 'note err'}, e.message))); return; }
  if (!location.hash.startsWith('#/lineage')) return;
  if (!sm.nodes) return emptyMap(main, [['Home', '#/'], ['Lineage']], 'Lineage');
  if (!LN.focus && sm.suggested) LN.focus = sm.suggested.id;
  const side = h('div', {class: 'card stack lside', style: 'gap:10px;margin:0'});
  const map = lineageMap({layout: 'flow', colour: 'direction', height: 540, label: 'Lineage map', onSelect: n => showSide(n.id), onClear: () => showSide(LN.focus)});
  const tableBox = h('div', {});
  const counts = h('div', {class: 'small muted', style: 'margin:8px 0 10px'});
  let data = null;
  const load = async () => {
    try {
      data = LN.whole ? await api(`/api/lineage/graph?limit=120&kinds=${[...LN.kinds].join(',')}`) : await api(`/api/lineage/slice?id=${encodeURIComponent(LN.focus)}&depth=${LN.depth}&direction=${LN.dir}&kinds=${[...LN.kinds].join(',')}`);
    } catch (e) { if (LN.focus && !LN.whole) { LN.focus = sm.suggested ? sm.suggested.id : null; LN.whole = !LN.focus; return LN.focus || LN.whole ? load() : null; } notify(e.message, 'err'); return; }
    map.draw(data, {focus: LN.whole ? null : LN.focus, layout: LN.whole ? 'network' : 'flow', colour: 'direction'});
    const c = data.counts || {};
    counts.textContent = LN.whole ? `Showing the ${data.nodes.length} most connected of ${c.nodes_total} items · ${data.edges.length} of ${c.edges_total} links` : `${c.upstream || 0} upstream · ${c.downstream || 0} downstream within ${LN.depth} hop${LN.depth === 1 ? '' : 's'} · ${data.nodes.length} of ${c.nodes_total} items shown`;
    tableBox.replaceChildren(mapTable(data.nodes));
    if (!LN.whole) showSide(LN.focus); else side.replaceChildren(h('h3', {}, 'Whole map'), h('div', {class: 'small muted'}, 'The busiest items and their links. Click one to see its impact, or search for anything.'));
  };
  const showSide = async id => {
    if (!id) return;
    side.replaceChildren(skel('rows'));
    let n;
    try { n = await api(`/api/lineage/node/${encodeURIComponent(id)}`); } catch (e) { side.replaceChildren(h('div', {class: 'note err'}, e.message)); return; }
    const im = n.impact, p = n.properties || {};
    side.replaceChildren(h('h3', {style: 'margin:0'}, n.label), h('div', {class: 'small muted'}, [LIN_KIND_NAME[n.kind] || n.kind, n.system, n.status, n.owner ? 'owner ' + n.owner : null].filter(Boolean).join(' · ')),
      h('div', {}, h('b', {}, 'Impact if this changes'), h('div', {class: 'muted'}, im.downstream ? `${im.downstream} downstream${im.reports.length ? ' · ' + im.reports.length + ' report' + (im.reports.length === 1 ? '' : 's') : ''}` : 'Nothing downstream.'),
        im.reports.length ? h('div', {class: 'small muted'}, im.reports.slice(0, 5).join(', ') + (im.reports.length > 5 ? ' …' : '')) : null),
      h('div', {class: 'row'}, id !== LN.focus || LN.whole ? h('button', {class: 'btn sm', type: 'button', onclick: () => { LN.whole = false; location.hash = `#/lineage?focus=${encodeURIComponent(id)}&depth=${LN.depth}`; }}, 'Focus here') : null,
        h('a', {class: 'btn sm', href: `#/graph?focus=${encodeURIComponent(id)}`}, 'Open in knowledge map'), p.link ? h('a', {class: 'btn sm', href: p.link}, 'Open') : null),
      n.upstream.length || n.downstream.length ? h('div', {class: 'small'}, h('b', {}, `${n.upstream.length} directly upstream · ${n.downstream.length} directly downstream`)) : null,
      h('div', {class: 'note', style: 'margin:0'}, h('b', {}, 'How to read this map: '), 'click a table, job or report — upstream (where its data comes from) is orange, downstream (what changes if it changes) is blue. Esc clears.'));
  };
  const depthSel = h('select', {class: 'sel', 'aria-label': 'Depth', style: 'width:auto', onchange: e => { LN.depth = +e.target.value; load(); }}, [1, 2, 3, 4].map(d => h('option', {value: d, selected: d === LN.depth}, 'Depth ' + d)));
  const dirSeg = h('div', {class: 'segbtn', role: 'group', 'aria-label': 'Direction'}, [['up', 'Upstream'], ['both', 'Both'], ['down', 'Downstream']].map(([k, l]) => h('button', {type: 'button', class: LN.dir === k ? 'on' : '', 'aria-pressed': String(LN.dir === k), onclick: () => { LN.dir = k; [...dirSeg.children].forEach(b => { b.classList.toggle('on', b.textContent === l); b.setAttribute('aria-pressed', String(b.textContent === l)); }); load(); }}, l)));
  main.replaceChildren(h('div', {class: 'page', id: 'lineagepage'},
    pageHead({crumbs: [['Home', '#/'], ['Knowledge map', '#/graph'], ['Lineage']], eyebrow: brandName() + ' · Knowledge map', title: 'Lineage',
      promise: 'Where each number comes from: sources → model tables → measures → pages → reports, and the jobs, flows and bots that move the data between your systems.',
      actions: [h('button', {class: 'btn', type: 'button', onclick: () => map.png('lineage')}, icon('download'), 'PNG'),
        (S.me || {}).builder ? h('button', {class: 'btn', type: 'button', onclick: async e => { e.target.disabled = true; try { const r = await api('/api/lineage/sync', {method: 'POST'}); notify(`Map rebuilt: ${r.dashboards.reports} dashboards, ${r.ontology.entities} entities`, 'ok'); sm = await api('/api/lineage/summary'); load(); } catch (err) { notify(err.message, 'err'); } e.target.disabled = false; }}, icon('spark'), 'Rebuild from today’s data') : null]}),
    h('div', {class: 'toolbar'}, lineageSearch({onPick: n => { LN.whole = false; location.hash = `#/lineage?focus=${encodeURIComponent(n.id)}&depth=${LN.depth}`; }}),
      kindChecks(LN.kinds, load), depthSel, dirSeg,
      h('button', {class: 'btn' + (LN.whole ? ' primary' : ''), type: 'button', 'aria-pressed': String(LN.whole), onclick: () => { LN.whole = !LN.whole; load(); }}, LN.whole ? 'Back to focus' : 'Whole map')),
    h('div', {class: 'row'}, counts, h('span', {class: 'sp', style: 'flex:1'}), mapLegend('direction')),
    h('div', {class: 'grid g-side'}, h('div', {}, map.el, tableBox), side)));
  document.title = `Lineage · ${S.brand ? S.brand.full : 'RELAY by PASDACS'}`;
  await load();
}

/* ---------- #/graph (Knowledge map) ---------- */
const GR = {mode: 'explore', focus: null, hops: 1, layout: 'network', colour: 'type', kinds: new Set(Object.keys(LIN_KIND_NAME)), from: null, to: null};
async function renderGraph() {
  const main = $('#main');
  if (!$('#graphpage')) main.replaceChildren(h('div', {class: 'page'}, pageHead({crumbs: [['Home', '#/'], ['Knowledge map']], eyebrow: brandName() + ' · Knowledge map', title: 'Knowledge map'}), skel('cards')));
  const qp = hashParams();
  if (qp.get('focus')) { GR.focus = qp.get('focus'); GR.mode = 'explore'; }
  let sm;
  try { sm = await api('/api/lineage/summary'); } catch (e) { main.replaceChildren(h('div', {class: 'page'}, h('div', {class: 'note err'}, e.message))); return; }
  if (!location.hash.startsWith('#/graph')) return;
  if (!sm.nodes) return emptyMap(main, [['Home', '#/'], ['Knowledge map']], 'Knowledge map');
  if (!GR.focus && sm.suggested) GR.focus = sm.suggested.id;
  const me = S.me || {};
  const det = h('div', {class: 'card stack lside', style: 'gap:10px;margin:0'});
  const map = lineageMap({layout: GR.layout, colour: GR.colour, height: 540, label: 'Knowledge map', dimOthers: false, onSelect: n => showDetails(n.id)});
  const counts = h('div', {class: 'small muted'}), tableBox = h('div', {}), legend = h('div', {});
  let data = null;
  const load = async () => {
    try {
      if (GR.mode === 'path') {
        if (!(GR.from && GR.to)) { map.draw({nodes: [], edges: []}); map.setEmpty('Pick two items above and press Find path.'); counts.textContent = ''; tableBox.replaceChildren(); return; }
        data = await api(`/api/lineage/path?a=${encodeURIComponent(GR.from.id)}&b=${encodeURIComponent(GR.to.id)}`);
        if (!data.found) { map.draw({nodes: [], edges: []}); map.setEmpty(`No connection between ${GR.from.label} and ${GR.to.label} on the map.`); counts.textContent = 'No path found.'; tableBox.replaceChildren(); return; }
        map.draw(data, {focus: GR.from.id, layout: 'flow', colour: GR.colour, select: null});
        counts.textContent = `${data.nodes.length} items on the shortest path from ${GR.from.label} to ${GR.to.label}`;
      } else {
        data = await api(`/api/lineage/slice?id=${encodeURIComponent(GR.focus)}&depth=${GR.hops}&kinds=${[...GR.kinds].join(',')}`);
        map.draw(data, {focus: GR.focus, layout: GR.layout, colour: GR.colour});
        const c = data.counts;
        counts.replaceChildren(`Showing ${data.nodes.length} of ${fmtN(c.nodes_total, 0)} items · ${data.edges.length} of ${fmtN(c.edges_total, 0)} links · ${GR.hops} hop${GR.hops === 1 ? '' : 's'} from `, h('b', {}, (data.nodes.find(n => n.id === GR.focus) || {}).label || ''));
        showDetails(GR.focus);
      }
      legend.replaceChildren(mapLegend(GR.colour));
      tableBox.replaceChildren(mapTable(data.nodes));
    } catch (e) {
      if (GR.mode === 'explore' && sm.suggested && GR.focus !== sm.suggested.id) { GR.focus = sm.suggested.id; return load(); }
      notify(e.message, 'err');
    }
  };
  const showDetails = async id => {
    det.replaceChildren(skel('rows'));
    let n;
    try { n = await api(`/api/lineage/node/${encodeURIComponent(id)}`); } catch (e) { det.replaceChildren(h('div', {class: 'note err'}, e.message)); return; }
    const p = n.properties || {}, role = id === GR.focus ? 'focus' : (data && (data.nodes.find(x => x.id === id) || {}).role) || '—';
    const props = Object.entries(p).filter(([k, v]) => !k.startsWith('_') && v != null && v !== '' && !['link', 'tagged_by', 'tagged', 'personal', 'note'].includes(k) && typeof v !== 'object').slice(0, 8);
    const tag = async personal => { try { await api(`/api/lineage/node/${encodeURIComponent(id)}/tags`, {method: 'PUT', json: {personal}}); notify('Tag saved', 'ok'); showDetails(id); } catch (e) { notify(e.message, 'err'); } };
    det.replaceChildren(
      h('div', {class: 'row'}, h('span', {class: 'pill plain info'}, LIN_KIND_NAME[n.kind] || n.kind), n.status ? h('span', {class: 'pill plain ' + ({ok: 'ok', warn: 'you', bad: 'err', mute: 'mute', none: 'mute'}[statusKey(n.status)])}, n.status) : null, p.personal ? h('span', {class: 'pill plain you'}, p.personal === 'anonymised' ? 'Anonymised' : 'Personal data') : null),
      h('h3', {style: 'margin:0;font-family:var(--mono);font-size:14px;overflow-wrap:anywhere'}, n.label),
      h('div', {class: 'small muted'}, [n.system, n.owner ? 'owner ' + n.owner : null, n.source ? 'from ' + n.source : null].filter(Boolean).join(' · ')),
      h('div', {class: 'row'},
        h('button', {class: 'btn sm primary', type: 'button', onclick: () => { GR.focus = id; GR.hops = Math.min(3, GR.hops + 1); load(); }}, 'Expand'),
        h('button', {class: 'btn sm', type: 'button', onclick: () => { GR.focus = id; GR.hops = 1; location.hash = `#/graph?focus=${encodeURIComponent(id)}`; }}, 'Focus'),
        h('button', {class: 'btn sm', type: 'button', onclick: () => { const im = n.impact; modal(`Impact: ${n.label}`, h('div', {class: 'mbody'}, h('p', {}, im.text), im.items.length ? h('table', {class: 'utable'}, h('tr', {}, ['Item', 'Kind', 'Hops', 'Status'].map((t, i) => h('th', {class: i ? '' : 'l'}, t))), im.items.map(x => h('tr', {}, h('td', {}, x.label), h('td', {}, LIN_KIND_NAME[x.kind] || x.kind), h('td', {class: 'n'}, x.hop), h('td', {}, x.status || '—')))) : null)); }}, 'Impact'),
        h('a', {class: 'btn sm', href: `#/lineage?focus=${encodeURIComponent(id)}`}, 'Lineage map'), p.link ? h('a', {class: 'btn sm', href: p.link}, 'Open') : null),
      h('dl', {class: 'kv-list'}, ['Kind', LIN_KIND_NAME[n.kind] || n.kind, 'Role', role === 'up' ? 'upstream' : role === 'down' ? 'downstream' : role, 'Impact', n.impact.downstream ? `${n.impact.downstream} downstream` : 'nothing downstream', 'Links', `${n.upstream.length} in · ${n.downstream.length} out`, 'First seen', when(n.first_seen), 'Last seen', ago(n.last_seen), ...props.flatMap(([k, v]) => [k.replace(/_/g, ' '), String(v)])].map((t, i) => h(i % 2 ? 'dd' : 'dt', {}, t))),
      n.kind === 'column' || n.kind === 'table' ? h('div', {}, h('div', {class: 'small', style: 'font-weight:600;margin-bottom:6px'}, 'Personal data'),
        me.builder ? h('div', {class: 'row'}, [['personal', 'Tag as personal'], ['anonymised', 'Anonymised'], ['none', 'Not personal']].map(([k, l]) => h('button', {class: 'btn sm' + ((p.personal || 'none') === k ? ' primary' : ''), type: 'button', 'aria-pressed': String((p.personal || 'none') === k), onclick: () => tag(k)}, l))) : h('div', {class: 'small muted'}, p.personal ? `Tagged ${p.personal}.` : 'Not tagged.'),
        h('div', {class: 'lnote'}, 'A personal-data tag follows the column lineage. Hashing keeps data pseudonymised (still personal); only “Anonymised” stops it.')) : null);
  };
  const seg = (name, pairs, get, set) => h('div', {class: 'segbtn', role: 'group', 'aria-label': name}, pairs.map(([k, l]) => h('button', {type: 'button', class: get() === k ? 'on' : '', 'aria-pressed': String(get() === k), onclick: e => { set(k); [...e.currentTarget.parentElement.children].forEach(b => { const on = b === e.currentTarget; b.classList.toggle('on', on); b.setAttribute('aria-pressed', String(on)); }); }}, l)));
  const pathBar = h('div', {class: 'toolbar', hidden: GR.mode !== 'path'},
    lineageSearch({placeholder: 'From…', label: 'Path from', onPick: n => { GR.from = n; }}), h('span', {class: 'muted', 'aria-hidden': 'true'}, '→'),
    lineageSearch({placeholder: 'To…', label: 'Path to', onPick: n => { GR.to = n; }}),
    h('button', {class: 'btn primary', type: 'button', onclick: () => { if (!(GR.from && GR.to)) return notify('Pick both ends of the path.', 'err'); load(); }}, 'Find path'));
  const exploreBar = h('div', {class: 'toolbar', hidden: GR.mode !== 'explore'},
    lineageSearch({placeholder: 'Search tables, reports, bots, flows, entities… (/)', onPick: n => { GR.focus = n.id; location.hash = `#/graph?focus=${encodeURIComponent(n.id)}`; }}),
    seg('Layout', [['network', 'Network'], ['flow', 'Data flow'], ['radial', 'Radial']], () => GR.layout, v => { GR.layout = v; map.setLayout(v); }),
    seg('Colour', [['type', 'Colour: type'], ['status', 'Status']], () => GR.colour, v => { GR.colour = v; map.setColour(v); legend.replaceChildren(mapLegend(v)); }),
    seg('Hops', [[1, '1 hop'], [2, '2'], [3, '3']], () => GR.hops, v => { GR.hops = v; load(); }),
    kindChecks(GR.kinds, load));
  main.replaceChildren(h('div', {class: 'page', id: 'graphpage'},
    pageHead({crumbs: [['Home', '#/'], ['Knowledge map']], eyebrow: brandName() + ' · Knowledge map', title: 'Knowledge map',
      promise: 'Reports, pipelines, bots, workflows, APIs, tables and the entities that tie them together — on one map you can search.',
      actions: seg('Mode', [['explore', 'Explorer'], ['path', 'Path finder']], () => GR.mode, v => { GR.mode = v; exploreBar.hidden = v !== 'explore'; pathBar.hidden = v !== 'path'; load(); })}),
    exploreBar, pathBar,
    h('div', {class: 'row', style: 'margin-bottom:10px'}, counts, h('span', {style: 'flex:1'}), legend),
    h('div', {class: 'grid g-side'}, h('div', {}, map.el, tableBox), det)));
  document.addEventListener('keydown', function slash(e) { if (!$('#graphpage')) return document.removeEventListener('keydown', slash); if (e.key === '/' && !/INPUT|TEXTAREA|SELECT/.test(e.target.tagName)) { e.preventDefault(); const i = $('#graphpage .lcombo input'); if (i) i.focus(); } });
  document.title = `Knowledge map · ${S.brand ? S.brand.full : 'RELAY by PASDACS'}`;
  await load();
}
