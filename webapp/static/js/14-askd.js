/* ---------------- Ask Relay (phase 5): questions about your data, checked at every step ---------------- */
const SCOPE_LABEL = {dashboard: 'One dashboard', team: 'All my data', org: 'All my data'};

/* An Ask Relay answer as an interactive widget. Everything comes from the answer's own data: filters for its category
   columns and its date range, a chip for each of its measures, "By" to regroup, Top N, Bar / Line / Table, totals that
   follow the filters, hover / keyboard values, click to ask about a point, "Ask about this view", and a PNG. */
const ASK_COLORS = ['#2C7A66', '#4E6E9E', '#B78A2A', '#A8475A'];      // enterprise sequence: forest teal, slate, muted gold, rose
const ASK_IN = (() => { try { return /Kolkata|Calcutta/.test(Intl.DateTimeFormat().resolvedOptions().timeZone) || /-IN$/.test(navigator.language); } catch (e) { return false; } })();
const RATIO = /(per|avg|average|mean|rate|ratio|share|pct|percent|margin|%|price)/i;
const MONEY = /(sales|revenue|amount|value|price|cost|profit|spend|gmv|income|turnover)/i;
const PCT = /(pct|percent|%|share|margin|rate|growth)/i;            // names of columns that may hold a percentage
const prettyCol = c => String(c).replace(/_/g, ' ').replace(/\b\w/g, m => m.toUpperCase());
// Columns holding percentages as fractions (0.845 = 84.5%), the way Ask Relay's queries return them: a rate, share,
// margin or growth whose values are (nearly all) between -1.5 and 1.5 and not all whole numbers
function askPctCols(cols, rows) {
  return new Set((cols || []).filter(c => {
    if (!PCT.test(c)) return false;
    const v = (rows || []).map(r => r[c]).filter(x => x != null && x !== '' && !isNaN(x)).map(Number);
    return v.length > 0 && v.filter(x => Math.abs(x) <= 1.5).length >= 0.8 * v.length && v.some(x => x !== Math.round(x));
  }));
}
function askNum(v, cur, pct) {
  if (v == null || isNaN(v)) return '-';
  if (pct) { const p = v * 100; return (+p.toFixed(Math.abs(p) < 1 && p !== 0 ? 2 : 1)).toLocaleString(ASK_IN ? 'en-IN' : undefined) + '%'; }
  const a = Math.abs(v), p = cur || '';
  if (ASK_IN && cur === '₹') return a >= 1e7 ? `${p}${(v / 1e7).toFixed(2).replace(/\.?0+$/, '')} Cr` : a >= 1e5 ? `${p}${(v / 1e5).toFixed(1).replace(/\.0$/, '')} L`
    : `${p}${(+v.toFixed(2)).toLocaleString('en-IN')}`;
  return a >= 1e9 ? `${p}${(v / 1e9).toFixed(1).replace(/\.0$/, '')}B` : a >= 1e6 ? `${p}${(v / 1e6).toFixed(1).replace(/\.0$/, '')}M`
    : a >= 1e4 ? `${p}${(v / 1e3).toFixed(1).replace(/\.0$/, '')}K` : a < 1 && v !== 0 ? String(+v.toFixed(3)) : `${p}${(+v.toFixed(2)).toLocaleString()}`;
}
const askFull = (v, cur, pct) => v == null || isNaN(v) ? '-' : pct ? (+(v * 100).toFixed(2)).toLocaleString(ASK_IN ? 'en-IN' : undefined) + '%'
  : (cur || '') + (+(+v).toFixed(4)).toLocaleString(ASK_IN ? 'en-IN' : undefined);
// a name in the plural: "city" -> "cities", "order date" -> "order dates", "status" -> "statuses"; a word already
// ending in s (products, sales) stays as it is
function plural(phrase) {
  return String(phrase).replace(/([a-z]+)$/i, w => {
    const lw = w.toLowerCase(), odd = {person: 'people', child: 'children', man: 'men', woman: 'women'};
    if (odd[lw]) return odd[lw];
    if (/^(series|species|data|staff|news|info)$/.test(lw)) return w;
    if (/is$/.test(lw)) return w.slice(0, -2) + 'es';
    if (/(ss|us|x|z|ch|sh)$/.test(lw)) return w + 'es';
    if (/s$/.test(lw)) return w;
    return /[^aeiou]y$/.test(lw) ? w.slice(0, -1) + 'ies' : w + 's';
  });
}
function niceTicks(lo, hi, n = 4) {
  if (hi === lo) hi = lo + 1;
  const raw = (hi - lo) / n, mag = Math.pow(10, Math.floor(Math.log10(raw))), step = [1, 2, 2.5, 5, 10].map(f => f * mag).find(x => x >= raw) || raw;
  const out = [];
  for (let v = Math.floor(lo / step) * step; ; v += step) { out.push(+v.toFixed(10)); if (v >= hi - step * 1e-9) break; }   // the last tick covers the maximum
  return out;
}
function askChart(ans, opts = {}) {
  const d = ans.data, spec = (ans.result || {}).chart || {};
  if (!d || !d.rows || d.rows.length < 2) return null;        // one number: the headline says it
  const cols = d.columns, rows0 = d.rows.slice(0, 1000);
  const isNum = c => { const v = rows0.map(r => r[c]).filter(x => x != null && x !== ''); return v.length && v.filter(x => typeof x === 'number' || (!isNaN(+x) && /^-?[\d.,]+$/.test(String(x)))).length / v.length >= 0.9; };
  const isDate = c => rows0.slice(0, 20).every(r => r[c] == null || /^\d{4}-\d{2}(-\d{2})?/.test(String(r[c])));
  const nums = cols.filter(c => isNum(c) && !isDate(c)), dates = cols.filter(c => !nums.includes(c) && isDate(c)), cats = cols.filter(c => !nums.includes(c) && !dates.includes(c));
  const dims = [...dates, ...cats];
  if (!nums.length || !dims.length) return null;
  const text = `${(ans.result || {}).headline || ''} ${ans.summary || ''}`;
  const cur = (text.match(/[₹$€£]/) || [])[0] || '';
  const pcts = askPctCols(nums, rows0), ratio = c => RATIO.test(c) || pcts.has(c);      // percentages show as 84.5%, and average
  const curOf = c => cur && MONEY.test(c) && !pcts.has(c) && !/(share|pct|percent|%|margin)/i.test(c) ? cur : '';
  const short = (v, c) => askNum(v, curOf(c), pcts.has(c)), full = (v, c) => askFull(v, curOf(c), pcts.has(c));
  const st = {x: dims.includes(spec.x) ? spec.x : dims[0], on: new Set((spec.y || []).filter(c => nums.includes(c)).slice(0, 4)), view: 'bar', sort: false, top: 0,
    values: (d.rows || []).length <= 12, filters: {}, from: null, to: null};      // labels only where they fit; hover shows the rest
  if (!st.on.size) st.on.add(nums[0]);
  st.view = (ans.result || {}).type === 'table' ? 'table' : spec.kind === 'line' || (dates.includes(st.x) && rows0.length > 12) ? 'line' : 'bar';
  const distinct = c => [...new Set(rows0.map(r => r[c]).filter(v => v != null))];
  const filterable = cats.filter(c => { const n = distinct(c).length; return n > 1 && n <= 40; });
  const dateCol = dates[0], dateVals = dateCol ? distinct(dateCol).map(String).sort() : [];
  const wrap = h('div', {class: 'achart'});
  const head = h('div', {class: 'awhead'}), kpis = h('div', {class: 'akpis'}), tools = h('div', {class: 'atools'}), host = h('div', {class: 'aplot'}),
    tip = h('div', {class: 'atip', role: 'status', 'aria-live': 'polite'}), foot = h('div', {class: 'awfoot'});
  const NS = 'http://www.w3.org/2000/svg';
  let svg = null;
  const kept = () => rows0.filter(r => Object.entries(st.filters).every(([c, set]) => !set || set.has(r[c]))
    && (!dateCol || ((!st.from || String(r[dateCol]) >= st.from) && (!st.to || String(r[dateCol]) <= st.to))));
  const aggregate = rows => {                       // one row per value of "By": sums, or averages for ratio-like measures
    const g = new Map();
    for (const r of rows) { const k = r[st.x]; if (!g.has(k)) g.set(k, {k, n: 0, s: {}}); const e = g.get(k); e.n++; for (const c of nums) e.s[c] = (e.s[c] || 0) + (+r[c] || 0); }
    return [...g.values()].map(e => ({[st.x]: e.k, ...Object.fromEntries(nums.map(c => [c, ratio(c) ? e.s[c] / e.n : e.s[c]]))}));
  };
  const total = (rows, c) => { const v = rows.map(r => +r[c] || 0); return ratio(c) ? v.reduce((a, b) => a + b, 0) / (v.length || 1) : v.reduce((a, b) => a + b, 0); };
  function filterButton(c) {
    const set = st.filters[c], all = distinct(c);
    const label = !set ? 'All' : set.size === 1 ? String([...set][0]) : `${set.size} of ${all.length}`;
    return h('button', {class: 'btn sm afilter' + (set ? ' on' : ''), type: 'button', 'aria-haspopup': 'dialog', onclick: e => {
      const cur = new Set(st.filters[c] || all);
      const boxes = all.map(v => { const b = h('input', {type: 'checkbox', checked: cur.has(v)}); b.onchange = () => { if (b.checked) cur.add(v); else cur.delete(v); apply(); };
        return h('label', {class: 'chk'}, b, String(v)); });
      const apply = () => { st.filters[c] = cur.size === all.length || !cur.size ? null : new Set(cur); draw(); };
      popover(e.currentTarget, [h('div', {class: 'nphead'}, h('b', {}, prettyCol(c)), h('span', {class: 'spacer'}),
        h('button', {class: 'btn sm ghost', onclick: () => { all.forEach(v => cur.add(v)); boxes.forEach(l => { l.firstChild.checked = true; }); apply(); }}, 'All')),
        h('div', {class: 'afopts'}, boxes)], 'afpop');
    }}, prettyCol(c) + ': ', h('b', {}, label), icon('chevd'));
  }
  function draw() {
    const filtered = kept(), agg = aggregate(filtered), shown = nums.filter(c => st.on.has(c)), first = shown[0];
    let rows = st.sort || st.top ? [...agg].sort((a, b) => (+b[first] || 0) - (+a[first] || 0)) : agg;
    if (!st.sort && dates.includes(st.x)) rows = [...rows].sort((a, b) => String(a[st.x]).localeCompare(String(b[st.x])));
    if (st.top) rows = rows.slice(0, st.top);
    // filters and the measure / grouping pickers (from the answer's own columns)
    const dsel = (val, on) => { const s = h('select', {class: 'sel', 'aria-label': on}, h('option', {value: ''}, on === 'From' ? 'from start' : 'to end'),
      dateVals.map(v => h('option', {value: v, selected: v === val}, v))); s.onchange = () => { st[on === 'From' ? 'from' : 'to'] = s.value || null; draw(); }; return s; };
    head.replaceChildren(...[
      dims.length > 1 ? h('label', {class: 'amodel'}, 'By', (() => { const s = h('select', {class: 'sel', 'aria-label': 'Group by'}, dims.map(c => h('option', {value: c, selected: c === st.x}, prettyCol(c))));
        s.onchange = () => { st.x = s.value; draw(); }; return s; })()) : null,
      ...filterable.map(filterButton),
      dateCol && dateVals.length > 1 ? h('span', {class: 'amodel'}, prettyCol(dateCol), dsel(st.from, 'From'), '-', dsel(st.to, 'To')) : null,
      agg.length > 5 ? h('label', {class: 'amodel'}, 'Show', (() => { const s = h('select', {class: 'sel', 'aria-label': 'How many'}, [[0, 'All'], [5, 'Top 5'], [10, 'Top 10'], [20, 'Top 20']]
        .map(([v, l]) => h('option', {value: v, selected: st.top === v}, l))); s.onchange = () => { st.top = +s.value; draw(); }; return s; })()) : null,
      Object.values(st.filters).some(Boolean) || st.from || st.to || st.top ? h('button', {class: 'btn sm ghost', type: 'button',
        onclick: () => { st.filters = {}; st.from = st.to = null; st.top = 0; draw(); }}, icon('x'), 'Reset') : null].filter(Boolean));
    // measure chips and their totals for the current filters
    // D2D Relay: only the measures the answer charts (helper columns such as a repeated year total would add up to nonsense)
    const chartCols = (spec.y || []).filter(c => nums.includes(c));
    kpis.replaceChildren(...(chartCols.length ? chartCols : nums).slice(0, 8).map(c => {
      const i = nums.indexOf(c), on = st.on.has(c), color = ASK_COLORS[[...st.on].indexOf(c) % 4] || '#8E958E';
      return h('button', {class: 'akpi' + (on ? ' on' : ''), type: 'button', 'aria-pressed': String(on),
        title: `Show ${prettyCol(c)} - Shift+click to compare it with the others`, style: on ? `border-color:${color}` : '',
        onclick: e => {
          if (!e.shiftKey) st.on = new Set([c]);                      // measures differ in scale: one at a time by default
          else if (on && st.on.size > 1) st.on.delete(c);
          else if (!on) { if (st.on.size >= 4) st.on.delete([...st.on][0]); st.on.add(c); }
          if (st.view === 'table') st.tsort = c;
          draw(); }},
        h('span', {class: 'akl'}, on ? h('i', {style: `background:${color}`}) : null, prettyCol(c), ratio(c) ? h('em', {}, ' avg') : null),
        h('b', {}, short(total(filtered, c), c)), i === 0 ? null : null);
    }));
    tools.replaceChildren(...[...['bar', 'line', 'table'].map(v => h('button', {class: 'btn sm' + (st.view === v ? ' on' : ''), type: 'button', 'aria-pressed': String(st.view === v),
        onclick: () => { st.view = v; draw(); }}, {bar: 'Bar', line: 'Line', table: 'Table'}[v])),
      h('span', {class: 'asep'}),
      h('button', {class: 'btn sm' + (st.sort ? ' on' : ''), type: 'button', 'aria-pressed': String(st.sort), title: 'Highest first', onclick: () => { st.sort = !st.sort; draw(); }}, 'Sort'),
      st.view !== 'table' ? h('button', {class: 'btn sm' + (st.values ? ' on' : ''), type: 'button', 'aria-pressed': String(st.values), onclick: () => { st.values = !st.values; draw(); }}, 'Values') : null,
      h('span', {class: 'spacer'}),
      st.view !== 'table' ? h('button', {class: 'btn sm ghost', type: 'button', title: 'Download the chart as a PNG image',
        onclick: () => chartPng(svg, (ans.result || {}).headline || 'ask-d-chart')}, icon('download'), 'PNG') : null].filter(Boolean));
    if (st.view === 'table') drawTable(rows, shown);
    else drawChart(rows, shown);
    const active = [...Object.entries(st.filters).filter(([, s]) => s).map(([c, s]) => `${prettyCol(c)} = ${[...s].join(', ')}`),
      st.from || st.to ? `${prettyCol(dateCol)} ${st.from || '...'} to ${st.to || '...'}` : null, st.top ? `top ${st.top} by ${prettyCol(first)}` : null].filter(Boolean);
    const what = prettyCol(st.x).toLowerCase();
    foot.replaceChildren(h('span', {class: 'faint small'}, `${rows.length} ${rows.length === 1 ? what : plural(what)} - ${filtered.length} of ${rows0.length} rows` + (active.length ? ' - ' + active.join(' - ') : '')),
      h('span', {class: 'spacer'}),
      !opts.onAsk ? h('span', {}) : h('button', {class: 'btn sm', type: 'button', onclick: () => opts.onAsk(`Looking at ${shown.map(prettyCol).join(' and ')} by ${prettyCol(st.x)}`
        + (active.length ? ` with ${active.join('; ')}` : '') + ': what stands out, and why?')}, icon('spark'), 'Ask about this view'));
  }
  function drawTable(rows, shown) {
    const sortBy = st.tsort || shown[0];
    const sorted = [...rows].sort((a, b) => st.tsort === st.x ? String(a[st.x]).localeCompare(String(b[st.x])) : (+b[sortBy] || 0) - (+a[sortBy] || 0));
    const th = c => h('th', {class: c === st.x ? 'l' : '', 'aria-sort': c === sortBy ? 'descending' : 'none'},
      h('button', {class: 'athbtn', type: 'button', onclick: () => { st.tsort = c; draw(); }}, prettyCol(c), c === sortBy ? ' ▾' : ''));
    host.replaceChildren(h('div', {class: 'dprev', style: 'max-height:320px'}, h('table', {class: 'utable'}, h('tr', {}, [st.x, ...shown].map(th)),
      sorted.map(r => h('tr', {}, h('td', {}, String(r[st.x] ?? '')), shown.map(c => h('td', {class: 'n'}, full(+r[c], c))))))));
    svg = null;
  }
  function drawChart(rows, shown) {
    const W = 680, H = 236, L = 64, R = 10, T = 16, B = 34, pw = W - L - R, ph = H - T - B, n = Math.max(rows.length, 1), bw = pw / n;
    const vals = rows.flatMap(r => shown.map(s => +r[s] || 0));
    const ticks = niceTicks(Math.min(0, ...vals), Math.max(0, ...vals, 0.0001));
    const lo = ticks[0], hi = ticks[ticks.length - 1], Y = v => T + ph - (ph * ((+v || 0) - lo)) / (hi - lo || 1);
    const tick = t => shown.every(s => pcts.has(s)) ? askNum(t, '', true) : askNum(t, shown.length === 1 ? curOf(shown[0]) : '');
    svg = document.createElementNS(NS, 'svg');
    svg.setAttribute('viewBox', `0 0 ${W} ${H}`); svg.setAttribute('width', '100%'); svg.setAttribute('role', 'group');
    svg.setAttribute('aria-label', `${st.view === 'bar' ? 'Bar' : 'Line'} chart of ${shown.map(prettyCol).join(', ')} by ${prettyCol(st.x)}. Use the arrow keys to move between points.`);
    const el = (tag, attrs, txt) => { const e = document.createElementNS(NS, tag); for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v); if (txt != null) e.textContent = txt; svg.append(e); return e; };
    el('rect', {x: 0, y: 0, width: W, height: H, fill: '#fff'});
    ticks.forEach(t => { el('line', {x1: L, x2: W - R, y1: Y(t), y2: Y(t), stroke: t === 0 ? '#C9C4B5' : '#EEEBE3'});
      el('text', {x: L - 6, y: Y(t) + 3.5, 'font-size': 10, 'text-anchor': 'end', fill: '#6E756E'}, tick(t)); });
    const every = Math.max(1, Math.ceil(n / 12));
    rows.forEach((r, i) => { if (i % every === 0) el('text', {x: L + i * bw + bw / 2, y: H - B + 15, 'font-size': 10, 'text-anchor': 'middle', fill: '#5F655F'}, String(r[st.x] ?? '').slice(0, 13)); });
    el('text', {x: L + pw / 2, y: H - 4, 'font-size': 10, 'text-anchor': 'middle', fill: '#6E756E', 'font-weight': 600}, prettyCol(st.x));
    if (!rows.length) el('text', {x: W / 2, y: H / 2, 'font-size': 13, 'text-anchor': 'middle', fill: '#6E756E'}, 'Nothing matches the filters');
    const marks = shown.map(() => []), showVals = st.values && rows.length * shown.length <= 24;
    shown.forEach((s, si) => {
      const color = ASK_COLORS[si % 4];
      if (st.view === 'bar') {
        const gw = Math.max(2, bw - 8) / shown.length;
        rows.forEach((r, i) => { const v = +r[s] || 0, x = L + i * bw + 4 + si * gw;
          marks[si].push(el('rect', {x, y: Math.min(Y(v), Y(0)), width: Math.max(1.5, gw - 1), height: Math.abs(Y(v) - Y(0)), rx: 3, fill: color, class: 'amark'}));
          if (showVals) el('text', {x: x + gw / 2, y: Math.min(Y(v), Y(0)) - 4, 'font-size': 9.5, 'text-anchor': 'middle', fill: '#2F4039'}, short(v, s)); });
      } else {
        el('polyline', {points: rows.map((r, i) => `${L + i * bw + bw / 2},${Y(r[s])}`).join(' '), fill: 'none', stroke: color, 'stroke-width': 2.4, 'stroke-linejoin': 'round'});
        rows.forEach((r, i) => { marks[si].push(el('circle', {cx: L + i * bw + bw / 2, cy: Y(r[s]), r: n > 30 ? 2.2 : 3.5, fill: '#fff', stroke: color, 'stroke-width': 2, class: 'amark'}));
          if (showVals) el('text', {x: L + i * bw + bw / 2, y: Y(r[s]) - 8, 'font-size': 9.5, 'text-anchor': 'middle', fill: '#2F4039'}, short(+r[s], s)); });
      }
    });
    const show = (i, band) => {
      marks.forEach(ms => ms.forEach((m, j) => m.classList.toggle('dim', j !== i)));
      const r = rows[i];
      tip.replaceChildren(h('b', {}, String(r[st.x] ?? '')), ...shown.map((s, si) => h('div', {}, h('i', {style: `background:${ASK_COLORS[si % 4]}`}), `${prettyCol(s)}: `, h('b', {}, full(+r[s], s)))),
        ...(opts.onAsk ? [h('div', {class: 'faint'}, 'Click to ask about it')] : []));
      const bb = band.getBoundingClientRect(), wb = host.getBoundingClientRect();
      tip.style.left = Math.min(Math.max(0, bb.left - wb.left + bb.width / 2 - 95), Math.max(0, wb.width - 200)) + 'px';
      tip.classList.add('on');
    };
    const hide = () => { tip.classList.remove('on'); marks.forEach(ms => ms.forEach(m => m.classList.remove('dim'))); };
    const bands = rows.map((r, i) => {
      const band = el('rect', {x: L + i * bw, y: T, width: bw, height: ph, fill: 'transparent', class: 'aband', tabindex: 0, role: 'button',
        'aria-label': `${r[st.x]}: ` + shown.map(s => `${prettyCol(s)} ${full(+r[s], s)}`).join(', ')});
      const askIt = () => { if (opts.onAsk && shown.length) opts.onAsk(`Tell me more about ${r[st.x]}: why is ${prettyCol(shown[0])} ${full(+r[shown[0]], shown[0])}, and what drives it?`); };
      band.addEventListener('mouseenter', () => show(i, band)); band.addEventListener('focus', () => show(i, band));
      band.addEventListener('mouseleave', hide); band.addEventListener('blur', hide);
      band.addEventListener('click', askIt);
      band.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); askIt(); }
        if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') { e.preventDefault(); const nb = bands[i + (e.key === 'ArrowRight' ? 1 : -1)]; if (nb) nb.focus(); } });
      if (opts.onAsk) band.style.cursor = 'pointer';
      return band;
    });
    host.replaceChildren(svg, tip);
  }
  draw();
  wrap.append(head, kpis, tools, host, foot);
  return wrap;
}
function chartPng(svg, name) {
  const xml = new XMLSerializer().serializeToString(svg), img = new Image(), vb = svg.viewBox.baseVal, scale = 2;
  img.onload = () => {
    const c = document.createElement('canvas');
    c.width = vb.width * scale; c.height = vb.height * scale;
    c.getContext('2d').drawImage(img, 0, 0, c.width, c.height);
    c.toBlob(b => { const a = h('a', {href: URL.createObjectURL(b), download: name.replace(/[^\w\- ]+/g, '').slice(0, 60).trim() + '.png'}); a.click(); });
  };
  img.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(xml.replace('<svg', '<svg font-family="Segoe UI, Arial, sans-serif"'));
}

function askModelSel() {          // D2D Relay: always the Relay Model, no picker
  return {el: null, value: () => CATALOG.default};
}

function askCsvBtn(d) {             // the answer's numbers as a CSV file, for Excel
  if (!d || !d.rows || !d.rows.length) return null;
  const cell = v => v == null ? '' : /[",\n]/.test(String(v)) ? '"' + String(v).replace(/"/g, '""') + '"' : String(v);
  return h('button', {class: 'btn sm ghost', type: 'button', style: 'margin:6px 0', onclick: () => {
    const csv = [d.columns.map(cell).join(','), ...d.rows.map(r => d.columns.map(c => cell(r[c])).join(','))].join('\r\n');
    const a = h('a', {href: URL.createObjectURL(new Blob([csv], {type: 'text/csv'})), download: 'ask-relay-answer.csv'}); a.click(); }}, icon('download'), 'Download for Excel (CSV)');
}
function askTable(d, max) {
  if (!d || !d.rows.length) return null;
  const pcts = askPctCols(d.columns, d.rows);           // a percentage held as a fraction reads 84.5%, as in the chart
  return h('div', {class: 'dprev', style: 'max-height:280px'}, h('table', {}, h('tr', {}, d.columns.map(c => h('th', {}, c))),
    d.rows.slice(0, max || 100).map(r => h('tr', {}, d.columns.map(c => h('td', {}, r[c] == null ? '' : pcts.has(c) && r[c] !== '' && !isNaN(r[c]) ? askFull(Number(r[c]), '', true)
      : typeof r[c] === 'number' ? r[c].toLocaleString() : String(r[c])))))));
}

function answerCard(m, opts) {
  const a = m.body || m, v = a.validation || {}, u = a.usage || {};
  const fb = m.feedback;
  const rate = async (rating, extra) => { try { await api(`/api/askd/messages/${m.id || a.message_id}/feedback`, {json: {rating, ...(extra || {})}}); notify('Thanks - noted', 'ok'); } catch (e) { notify(e.message, 'err'); } };
  const mid = m.id || a.message_id;
  const chart = askChart(a, {onAsk: opts && opts.onAsk});
  return h('div', {class: 'card', style: 'margin:0'},
    h('div', {class: 'row', style: 'gap:6px'}, icon('spark'), h('b', {}, 'Ask Relay'),
      v.where ? h('span', {class: 'tag ' + (v.where === 'live' ? 'acc' : '')}, v.where === 'live' ? 'Live from BigQuery' : 'From your dashboard data') : null,
      a.cached ? h('span', {class: 'tag', title: 'The same question was answered recently; no new AI cost'}, 'Answered before') : null, h('span', {class: 'spacer'}),
      a.seconds ? h('span', {class: 'faint small', title: 'How long the answer took'}, `${a.seconds}s`) : null),     // D2D Relay: no cost per answer
    (a.result || {}).headline ? h('div', {style: 'font-size:19px;font-weight:600;line-height:1.35;margin:8px 0 2px'}, a.result.headline) : null,
    chart,
    a.summary ? h('p', {style: 'margin:8px 0'}, h('b', {}, 'What this means. '), a.summary) : null,
    (a.actions || []).length ? h('div', {}, h('b', {class: 'small'}, 'What you could do next'), h('ul', {style: 'margin:4px 0 8px'}, a.actions.map(x => h('li', {}, x)))) : null,
    !chart ? askTable(a.data, 50) : h('details', {class: 'more'}, h('summary', {}, `See the numbers (${(a.data || {}).row_count || 0} rows)`), askCsvBtn(a.data), askTable(a.data, 100)),
    (v.not_included || []).length ? h('div', {class: 'note warn small'}, h('b', {}, 'Could not include: '), v.not_included.join(' - ')) : null,
    !(v.queries || []).length ? null : h('details', {class: 'more'}, h('summary', {}, 'How Relay worked this out (for analysts)'),
      (v.queries || []).map(q => h('div', {style: 'margin:8px 0;padding-left:8px;border-left:3px solid ' + (q.error ? 'var(--err)' : 'var(--line-2)')},
        h('div', {class: 'small'}, h('b', {}, q.id), ` - ${q.where || q.engine || ''}`, q.why ? ` - ${q.why}` : '', q.row_count != null ? ` - ${q.row_count.toLocaleString()} rows${q.limited ? ' (limit reached)' : ''} in ${q.seconds}s` : ''),
        h('pre', {class: 'mono small', style: 'white-space:pre-wrap;margin:4px 0'}, q.sql || ''),
        q.error ? h('div', {class: 'err-msg'}, q.error) : h('div', {class: 'checks small'}, (q.checks || []).map(c => h('span', {class: 'tag ok', style: 'margin:0 4px 4px 0'}, icon('check'), c)),
          q.tables && q.tables.length ? h('span', {class: 'muted'}, ' tables: ' + q.tables.join(', ')) : null)))),
    !mid ? null : h('div', {class: 'row', style: 'margin-top:8px;gap:6px'},
      h('button', {class: 'btn sm ghost' + (fb && fb.rating > 0 ? ' on' : ''), title: 'This answer was helpful', onclick: () => rate(1)}, icon('thumbup'), 'Helpful'),
      h('button', {class: 'btn sm ghost' + (fb && fb.rating < 0 ? ' on' : ''), title: 'Wrong or unhelpful', onclick: async () => {
        const sql = await askText('Not helpful', {label: 'What was wrong?', hint: 'Optional. You can paste a corrected SQL query here too.', ok: 'Send'}); if (sql !== null) rate(-1, /select/i.test(sql) ? {corrected_sql: sql} : {comment: sql}); }}, icon('thumbdown'), 'Not helpful'),
      h('span', {class: 'spacer'}),
      h('a', {class: 'btn sm', href: `/api/askd/messages/${mid}/snapshot`, onclick: e => { e.preventDefault(); snapshotAnswer(mid); }}, icon('download'), 'Save as image'),
      opts && opts.project ? h('button', {class: 'btn sm', onclick: () => sendToDashboard(mid, opts.project)}, icon('plus'), 'Add to dashboard')
        : h('button', {class: 'btn sm', onclick: () => pickDashboard(mid)}, icon('plus'), 'Add to a dashboard'),
      opts && opts.thread ? h('a', {class: 'btn sm', href: `#/askd/${opts.thread}`}, 'Open in Ask Relay') : null),
    (a.next_questions || []).length && opts && opts.onAsk ? h('div', {class: 'chips', style: 'margin-top:10px;align-items:center'}, h('span', {class: 'small muted'}, 'Ask next:'), a.next_questions.map(q => h('button', {class: 'chip', onclick: () => opts.onAsk(q)}, q))) : null);
}

async function snapshotAnswer(mid) {
  notify('Drawing the snapshot...');
  try {
    const r = await fetch(`/api/askd/messages/${mid}/snapshot`, {method: 'POST'});
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || 'Snapshot failed');
    const a = h('a', {href: URL.createObjectURL(await r.blob()), download: `ask-relay-${mid}.png`}); a.click();
  } catch (e) { notify(e.message, 'err'); }
}
async function sendToDashboard(mid, project) {
  const uses = typeof ORG === 'function' && ORG().id ? ` and uses ${costOf('change')} credits` : '';
  const note = await askText('Send to the dashboard', {label: 'Anything Relay should know when adding it?', hint: `Optional. It goes to the dashboard as a change request${uses}.`, ok: 'Send'});
  if (note === null) return;
  try { await api(`/api/askd/messages/${mid}/to-dashboard`, {json: {project, note}}); notify('Sent to the dashboard as a change request', 'ok'); if (typeof refreshOrg === 'function') refreshOrg(true); }
  catch (e) { notify(e.message, 'err'); }
}
async function pickDashboard(mid) {
  const o = await api('/api/askd/options');
  const sel = h('select', {class: 'sel'}, o.dashboards.map(d => h('option', {value: d.id}, d.name)));
  const m = modal('Add this answer to a dashboard', h('div', {class: 'mbody'}, h('div', {class: 'muted small'}, 'It becomes a change request: Relay adds a visual or a page that answers the question, and the review gates check it.'),
    h('label', {class: 'f'}, 'Dashboard'), sel, h('div', {class: 'row', style: 'justify-content:flex-end;margin-top:12px'}, h('button', {class: 'btn', onclick: () => m.remove()}, 'Cancel'),
      h('button', {class: 'btn primary', onclick: () => { m.remove(); sendToDashboard(mid, sel.value); }}, 'Continue'))));
}

/* the Ask Relay page (item 66, the user 2026-11-19: "ask relay should be able to have more better ui and navigations"):
   your conversations on the left (find one, pinned ones first, then by day; rename, pin, delete), the conversation in the
   middle with its own header (its name, what it asks about, the questions in it to jump to, the credits it used), and a
   side panel to start from: suggested questions (your industry's and your dashboards'), your KPIs and your data.
   Keys: "/" goes to the question box, Ctrl+K to the search, Esc closes a panel on a small screen.
   Pins and the open side-panel tab are this browser's own (localStorage). */
ICONS.list = ICONS.list || 'M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01';
const ASK_STEPS = ['Relay Model is reading your data...', 'Running the numbers...', 'Double-checking every figure...', 'Drawing the chart...', 'Writing it up in plain words...'];
const ASK_PREF = (() => { try { return JSON.parse(localStorage.getItem('askPrefs') || '{}') || {}; } catch (e) { return {}; } })();
const askSave = () => { try { localStorage.setItem('askPrefs', JSON.stringify(ASK_PREF)); } catch (e) { /* a private window: the preference is not kept */ } };
let ASK_KEYS = false;
function askKeys() {
  if (ASK_KEYS) return;
  ASK_KEYS = true;
  document.addEventListener('keydown', e => {
    if (!location.hash.startsWith('#/askd')) return;
    const typing = /^(INPUT|TEXTAREA|SELECT)$/.test((document.activeElement || {}).tagName || '') || (document.activeElement || {}).isContentEditable;
    if (e.key === '/' && !typing && !e.ctrlKey && !e.metaKey) { const i = $('#askinput'); if (i) { e.preventDefault(); i.focus(); } }
    else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { const s = $('#asksearch'); if (s) { e.preventDefault(); s.focus(); s.select(); } }
    else if (e.key === 'Escape') { const p = $('.askx'); if (p) p.classList.remove('rail-open', 'side-open'); }
  });
}
const askDay = ts => {
  const d = new Date(ts * 1000), now = new Date(), start = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime() / 1000;
  return ts >= start ? 'Today' : ts >= start - 86400 ? 'Yesterday' : ts >= start - 6 * 86400 ? 'This week' : ts >= start - 30 * 86400 ? 'This month' : 'Earlier';
};

async function renderAskD() {
  askKeys();
  const tid = (location.hash.split('/')[2] || '').split('?')[0] || null;
  const page = h('div', {class: 'page wide askpage'});
  $('#main').replaceChildren(page);
  document.title = 'Ask Relay - D2D Relay';
  let opts, list, th = null, cost = null;
  try {
    [opts, list, cost] = await Promise.all([api('/api/askd/options'), api('/api/askd/threads'),
      api('/api/askd/costs' + (tid ? '?thread=' + encodeURIComponent(tid) : '')).catch(() => null)]);
    if (tid) th = await api(`/api/askd/threads/${tid}`);
  } catch (e) { return page.append(h('div', {class: 'note err'}, e.message)); }
  if (!location.hash.startsWith('#/askd')) return;
  if (opts.brand_colors && opts.brand_colors.length >= 3) ASK_COLORS.splice(0, ASK_COLORS.length, ...opts.brand_colors);   // charts in the brand palette
  const dashName = id => (opts.dashboards.find(d => d.id === id) || {}).name;
  const scopeText = s => s && s.kind === 'dashboard' ? (dashName(s.project) || 'One dashboard') : 'All my data';

  // what a new question is about: everything, or one dashboard (fixed once the conversation starts)
  let scope = th ? th.scope : (ASK_PREF.scope && dashName(ASK_PREF.scope) ? {kind: 'dashboard', project: ASK_PREF.scope} : {kind: 'team'});
  const scopeSel = h('select', {class: 'sel askscope', 'aria-label': 'What to ask about', disabled: !!th},
    h('option', {value: ''}, 'All my data'),
    opts.dashboards.map(d => h('option', {value: d.id, selected: scope.kind === 'dashboard' && scope.project === d.id}, d.name)));
  scopeSel.onchange = () => { scope = scopeSel.value ? {kind: 'dashboard', project: scopeSel.value} : {kind: 'team'}; ASK_PREF.scope = scopeSel.value || null; askSave(); };

  // the credits a conversation uses (Ask Relay's credits pay for up to N answered questions)
  const meter = h('div', {class: 'askmeter'});
  const go = h('button', {class: 'btn primary', type: 'button'}, icon('send'), 'Ask');
  const drawCost = () => {
    const per = costOf('ask'), n = costOf('ask_questions') || 5, c = cost || {used: 0, left: 0};
    go.replaceChildren(icon('send'), 'Ask', per && !c.left ? costTag('ask') : '');
    if (!per || !ORG().id) return meter.replaceChildren();
    const left = c.left || 0;
    meter.replaceChildren(h('div', {class: 'dots', 'aria-hidden': 'true'}, Array.from({length: n}, (_, i) => h('i', {class: i < left ? 'on' : ''}))),
      h('span', {class: 'small'}, left ? `${left} of ${n} questions left` : `Next question: ${per} credits for ${n}`),
      th && c.used ? h('span', {class: 'small muted'}, ` - ${credits(c.used)} used here`) : '');     // '' not null: replaceChildren writes null as text
    meter.title = `${per} credits pay for up to ${n} answered questions in one conversation; a question that gets no answer gives them back.`;
  };
  const refreshCost = async id => { try { cost = await api('/api/askd/costs' + (id ? '?thread=' + encodeURIComponent(id) : '')); drawCost(); } catch (e) { /* the answer matters more */ } };
  drawCost();

  // ---- the conversations rail
  const pins = new Set(ASK_PREF.pins || []);
  const search = h('input', {type: 'search', id: 'asksearch', placeholder: 'Find a conversation (Ctrl+K)', 'aria-label': 'Find a conversation'});
  const railList = h('div', {class: 'askrail-list', role: 'list'});
  const rename = async t => {
    const name = await askText('Rename the conversation', {value: t.title, rows: 1, ok: 'Rename', required: true});
    if (!name || name === t.title) return;
    try { await api(`/api/askd/threads/${encodeURIComponent(t.id)}`, {method: 'PATCH', json: {title: name}}); t.title = name; drawRail(); if (th && th.id === t.id) { th.title = name; titleEl.textContent = name; } }
    catch (e) { notify(e.message, 'err'); }
  };
  const remove = async t => {
    if (!await confirmBox('Delete this conversation?', 'Its questions and answers are deleted. This cannot be undone.', 'Delete conversation')) return;
    try { await api(`/api/askd/threads/${encodeURIComponent(t.id)}`, {method: 'DELETE'}); notify('Conversation deleted', 'ok');
      list.threads = list.threads.filter(x => x.id !== t.id); pins.delete(t.id); ASK_PREF.pins = [...pins]; askSave();
      if (th && th.id === t.id) location.hash = '#/askd'; else drawRail(); }
    catch (e) { notify(e.message, 'err'); }
  };
  const drawRail = () => {
    const q = search.value.trim().toLowerCase();
    const rows = list.threads.filter(t => !q || [t.title, scopeText(t.scope)].join(' ').toLowerCase().includes(q));
    const groups = {};
    rows.forEach(t => { const g = pins.has(t.id) ? 'Pinned' : askDay(t.updated); (groups[g] = groups[g] || []).push(t); });
    const order = ['Pinned', 'Today', 'Yesterday', 'This week', 'This month', 'Earlier'];
    railList.replaceChildren(...(rows.length ? order.filter(g => groups[g]).map(g => h('div', {class: 'askgroup'}, h('div', {class: 'gh'}, g),
      groups[g].map(t => h('div', {class: 'askitem' + (th && t.id === th.id ? ' on' : ''), role: 'listitem'},
        h('a', {href: `#/askd/${t.id}`, class: 'it', title: t.title}, h('span', {class: 't1'}, t.title),
          h('span', {class: 't2'}, `${scopeText(t.scope)} - ${ago(t.updated)}`)),
        h('div', {class: 'acts'},
          h('button', {type: 'button', class: 'ib' + (pins.has(t.id) ? ' on' : ''), title: pins.has(t.id) ? 'Unpin' : 'Pin to the top', 'aria-label': (pins.has(t.id) ? 'Unpin ' : 'Pin ') + t.title,
            onclick: () => { if (pins.has(t.id)) pins.delete(t.id); else pins.add(t.id); ASK_PREF.pins = [...pins]; askSave(); drawRail(); }}, icon('pin')),
          h('button', {type: 'button', class: 'ib', title: 'Rename', 'aria-label': 'Rename ' + t.title, onclick: () => rename(t)}, icon('edit')),
          h('button', {type: 'button', class: 'ib', title: 'Delete', 'aria-label': 'Delete ' + t.title, onclick: () => remove(t)}, icon('x')))))))
      : [h('div', {class: 'small muted', style: 'padding:10px 4px'}, list.threads.length ? 'No conversation matches.' : 'Your conversations appear here.')]));
  };
  search.oninput = drawRail;
  drawRail();
  const rail = h('aside', {class: 'askrail', 'aria-label': 'Your conversations'},
    h('a', {class: 'btn primary', href: '#/askd', style: 'width:100%;justify-content:center'}, icon('plus'), 'New question'),
    search, railList);

  // ---- the conversation
  const chat = h('div', {class: 'askchat', 'aria-live': 'polite'});
  const input = h('textarea', {id: 'askinput', rows: 2, placeholder: 'Ask about your business in your own words ( / to come back here)', 'aria-label': 'Your question'});
  const grow = () => { input.style.height = 'auto'; input.style.height = Math.min(220, input.scrollHeight + 2) + 'px'; };
  input.oninput = grow;
  let qn = 0;
  const outline = h('select', {class: 'sel askoutline', 'aria-label': 'Jump to a question'});
  const addOutline = (text, id) => { outline.append(h('option', {value: id}, text.length > 70 ? text.slice(0, 67) + '...' : text)); outline.hidden = outline.options.length < 3; };
  outline.append(h('option', {value: ''}, 'Jump to a question'));
  outline.onchange = () => { const el = document.getElementById(outline.value); if (el) el.scrollIntoView({behavior: 'smooth', block: 'start'}); outline.value = ''; };
  const you = q => { const id = `askq-${++qn}`; addOutline(q, id);
    return h('div', {class: 'askyou', id}, h('div', {class: 'bubble'}, q)); };
  const fill = (q, now) => { input.value = q; grow(); input.focus(); if (now) ask(); };
  const ask = async q => {
    q = (q || input.value).trim(); if (!q) return;
    go.disabled = true; input.value = ''; grow();
    const hello = chat.querySelector('.askhello'); if (hello) hello.remove();
    chat.append(you(q));
    let i = 0;
    const msg = h('span', {}, ASK_STEPS[0]);
    const wait = h('div', {class: 'card flat askwait'}, h('span', {class: 'spin'}), msg);
    const tick = setInterval(() => { i = Math.min(i + 1, ASK_STEPS.length - 1); msg.textContent = ASK_STEPS[i]; }, 3500);
    chat.append(wait); wait.scrollIntoView({block: 'end', behavior: 'smooth'});
    const t0 = Date.now();
    try {
      const r = await api('/api/askd/ask', {json: {question: q, scope, thread_id: th ? th.id : null, model: CATALOG.default}});
      clearInterval(tick); wait.remove();
      if (typeof refreshOrg === 'function') refreshOrg(true);
      if (!th) { location.hash = `#/askd/${r.thread_id}`; return; }
      chat.append(answerCard({id: r.message_id, body: {...r, seconds: Math.round((Date.now() - t0) / 1000)}}, {onAsk: q2 => fill(q2, true)}));
      if (r.credits) { cost = r.credits; drawCost(); } else refreshCost(th.id);
    } catch (e) {
      clearInterval(tick);
      wait.replaceChildren(h('div', {class: 'note err', style: 'margin:0'}, 'Relay could not answer that: ' + e.message + ' Try asking it a different way.'));
    }
    go.disabled = false; input.focus();
  };
  go.onclick = () => ask();
  input.onkeydown = e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); ask(); } };

  for (const m of (th ? th.messages : [])) chat.append(m.role === 'user' ? you(m.body.text) : answerCard(m, {onAsk: q2 => fill(q2, true)}));
  const titleEl = h('h2', {class: 'asktitle'}, th ? th.title : 'New question');
  if (!th) {
    const groups = [];
    if ((opts.questions || []).length) groups.push([opts.industry ? `For ${opts.industry.toLowerCase()}` : 'For your industry', opts.questions.slice(0, 6)]);
    if ((opts.suggestions || []).length) groups.push(['From your dashboards', opts.suggestions.slice(0, 4)]);
    chat.append(h('div', {class: 'card askhello'},
      h('h2', {}, 'What would you like to know?'),
      h('p', {class: 'muted'}, opts.dashboards.length
        ? 'Ask in your own words. Relay answers with the numbers, a chart you can explore, what it means and what you could do next, checked at every step.'
        : 'Build a dashboard first, then Relay can answer questions about its data.'),
      groups.map(([label, qs]) => h('div', {class: 'askstart'}, h('div', {class: 'small muted gh'}, label),
        h('div', {class: 'chips'}, qs.map(x => h('button', {class: 'chip', type: 'button', title: 'Put it in the question box', onclick: () => fill(x)}, icon('spark'), ' ' + x))))),
      h('div', {class: 'small muted', style: 'margin-top:14px'}, 'Tip: ask for a trend ("week by week"), a comparison ("vs last year"), the best or worst ("top 10 stores") or a cause ("why did shrink rise?").')));
  }
  const head = h('div', {class: 'askhead'},
    h('button', {class: 'btn sm ghost askrail-toggle', type: 'button', 'aria-label': 'Your conversations', onclick: () => page.querySelector('.askx').classList.toggle('rail-open')}, icon('list')),
    h('div', {class: 'grow', style: 'min-width:0'}, titleEl,
      h('div', {class: 'small muted'}, th ? [h('span', {class: 'tag'}, scopeText(th.scope)), ` - started ${ago(th.created)} - ${th.messages.filter(m => m.role === 'user').length} question(s)`]
        : 'Choose what to ask about below, then ask.')),
    outline,
    th ? h('button', {class: 'btn sm ghost', type: 'button', title: 'Rename', onclick: () => rename(list.threads.find(t => t.id === th.id) || th)}, icon('edit')) : null,
    th ? h('button', {class: 'btn sm ghost danger', type: 'button', title: 'Delete this conversation', onclick: () => remove(list.threads.find(t => t.id === th.id) || th)}, icon('x')) : null,
    h('button', {class: 'btn sm ghost askside-toggle', type: 'button', 'aria-label': 'Suggestions, KPIs and data', onclick: () => page.querySelector('.askx').classList.toggle('side-open')}, icon('spark')));
  const composer = h('div', {class: 'card askcompose'},
    h('div', {class: 'row', style: 'gap:8px;margin-bottom:8px;flex-wrap:wrap;align-items:center'}, h('span', {class: 'small muted'}, 'Asking about'), scopeSel,
      th ? h('span', {class: 'faint small'}, 'fixed for this conversation') : null, h('span', {class: 'spacer'}), meter),
    input,
    h('div', {class: 'row', style: 'margin-top:8px'}, h('span', {class: 'faint small'}, 'Enter to ask - Shift+Enter for a new line'), h('span', {class: 'spacer'}), go));

  // ---- the side panel: start from a suggestion, a KPI or your data
  let tab = ASK_PREF.tab || 'suggest';
  const sideBody = h('div', {class: 'askside-body'});
  const sideTabs = h('div', {class: 'asktabs', role: 'tablist'});
  const kq = h('input', {type: 'search', placeholder: 'Find a KPI', 'aria-label': 'Find a KPI'});
  const kpiList = h('div', {class: 'askkpis'});
  const drawKpis = () => {
    const q = kq.value.trim().toLowerCase();
    const rows = (opts.kpis || []).filter(k => !q || [k.name, k.definition, k.domain].join(' ').toLowerCase().includes(q)).slice(0, 120);
    kpiList.replaceChildren(...(rows.length ? rows.map(k => h('button', {type: 'button', class: 'askkpi', title: k.definition || '',
      onclick: () => fill(`How did ${k.name} change week by week, compared with last year?`)},
      h('b', {}, k.name), h('small', {}, [k.unit, k.domain, k.from && k.from !== 'dictionary' ? `in ${k.from}` : null].filter(Boolean).join(' - '))))
      : [h('div', {class: 'small muted'}, (opts.kpis || []).length ? 'No KPI matches.' : 'No KPIs yet: your KPI dictionary and your dashboards\' KPIs appear here.')]));
  };
  const drawSide = () => {
    sideTabs.replaceChildren(...[['suggest', 'Ideas'], ['kpis', `KPIs (${(opts.kpis || []).length})`], ['data', 'Data']].map(([k, t]) =>
      h('button', {type: 'button', role: 'tab', 'aria-selected': String(tab === k), class: tab === k ? 'on' : '', onclick: () => { tab = k; ASK_PREF.tab = k; askSave(); drawSide(); }}, t)));
    if (tab === 'kpis') {
      drawKpis();
      sideBody.replaceChildren(kq, kpiList, h('a', {class: 'small', href: '#/ontology/kpis'}, 'Your KPI dictionary'));
    } else if (tab === 'data') {
      sideBody.replaceChildren(
        h('button', {type: 'button', class: 'askds' + (scope.kind !== 'dashboard' ? ' on' : ''), onclick: () => pickScope('')}, h('b', {}, 'All my data'), h('small', {}, `${opts.dashboards.length} dashboard${opts.dashboards.length === 1 ? '' : 's'}`)),
        ...opts.dashboards.map(d => h('button', {type: 'button', class: 'askds' + (scope.kind === 'dashboard' && scope.project === d.id ? ' on' : ''), onclick: () => pickScope(d.id)},
          h('b', {}, d.name), h('small', {}, d.status === 'done' ? 'Published' : 'In progress'))),
        th ? h('div', {class: 'small muted', style: 'margin-top:8px'}, 'A conversation asks about one thing: choosing another starts a new question.') : null);
    } else {
      const sets = [];
      if ((opts.questions || []).length) sets.push([opts.industry || 'Your industry', opts.questions]);
      if ((opts.suggestions || []).length) sets.push(['Your dashboards', opts.suggestions]);
      sideBody.replaceChildren(...(sets.length ? sets.map(([label, qs]) => h('div', {class: 'askideas'}, h('div', {class: 'gh small muted'}, label),
        qs.map(x => h('div', {class: 'askidea'}, h('button', {type: 'button', class: 'q', onclick: () => fill(x)}, x),
          h('button', {type: 'button', class: 'ib', title: 'Ask it now', 'aria-label': 'Ask now: ' + x, onclick: () => fill(x, true)}, icon('send'))))))
        : [h('div', {class: 'small muted'}, 'Suggestions appear once you have a dashboard.')]));
    }
  };
  const pickScope = id => {
    if (th && (id || '') !== (scope.kind === 'dashboard' ? scope.project : '')) { ASK_PREF.scope = id || null; askSave(); location.hash = '#/askd'; return; }
    scope = id ? {kind: 'dashboard', project: id} : {kind: 'team'}; scopeSel.value = id || ''; ASK_PREF.scope = id || null; askSave(); drawSide();
  };
  kq.oninput = drawKpis;
  drawSide();
  const side = h('aside', {class: 'askside', 'aria-label': 'Suggestions, KPIs and data'}, sideTabs, sideBody);

  page.append(h('div', {class: 'phead', style: 'margin-bottom:10px'}, h('div', {style: 'flex:1'}, h('h1', {}, 'Ask Relay'),
    h('div', {class: 'meta'}, 'Ask a question about your business. Get the answer, a chart you can explore and what to do next.'))),
    h('div', {class: 'askx'}, rail, h('section', {class: 'askmain', 'aria-label': 'Conversation'}, head, chat, composer), side,
      h('div', {class: 'askveil', onclick: () => page.querySelector('.askx').classList.remove('rail-open', 'side-open')})));
  if (th) setTimeout(() => chat.lastChild && chat.lastChild.scrollIntoView({block: 'end'}), 50);
  else input.focus();
}

function askPanel(st) {
  const card = h('div', {class: 'card', id: 'askpanel'});
  const filters = {}, out = h('div', {class: 'stack', style: 'margin-top:10px'});
  let page = '', thread = null, left = 0;
  const input = h('input', {type: 'text', placeholder: `Ask about ${st.name}, e.g. "Which store grew fastest?"`});
  const go = h('button', {class: 'btn primary'});
  const label = () => go.replaceChildren(icon('spark'), 'Ask', left ? '' : costTag('ask'));    // D2D Relay: when the next question is charged
  label();
  const bar = h('div', {class: 'chips', style: 'margin-top:8px'});
  const msel = askModelSel();
  api(`/api/projects/${st.id}/askd-context`).then(ctx => {
    const pageSel = h('select', {class: 'sel', style: 'max-width:200px', 'aria-label': 'Dashboard page'}, h('option', {value: ''}, 'Any page'), ctx.pages.map(p => h('option', {value: p}, p)));
    pageSel.onchange = () => { page = pageSel.value; };
    bar.replaceChildren(pageSel, ...ctx.filters.map(f => { const s = h('select', {class: 'sel', style: 'max-width:200px', 'aria-label': `Filter: ${f.label}`}, h('option', {value: ''}, `${f.label}: all`), f.values.map(v => h('option', {value: v}, `${f.label}: ${v}`)));
      s.onchange = () => { if (s.value) filters[f.field] = s.value; else delete filters[f.field]; }; return s; }));
  }).catch(() => {});
  const ask = async q => {
    q = (q || input.value).trim(); if (!q) return;
    go.disabled = true; input.value = '';
    out.prepend(h('div', {class: 'muted small'}, h('b', {}, 'You: '), q, Object.keys(filters).length ? ` (${Object.entries(filters).map(([k, v]) => `${k} = ${v}`).join(', ')})` : ''));
    const wait = h('div', {class: 'muted small'}, 'Ask Relay is working...'); out.prepend(wait);
    try {
      const r = await api('/api/askd/ask', {json: {question: q, thread_id: thread, model: msel.value(), scope: {kind: 'dashboard', project: st.id, page: page || null, filters: {...filters}}}});
      thread = r.thread_id; wait.replaceWith(answerCard({id: r.message_id, body: r}, {project: st.access && st.access.can_edit ? st.id : null, thread, onAsk: ask}));
      left = (r.credits || {}).left || 0; label();
      if (typeof refreshOrg === 'function') refreshOrg(true);
    } catch (e) { wait.replaceWith(h('div', {class: 'note err'}, e.message)); }
    go.disabled = false;
  };
  go.onclick = () => ask();
  input.onkeydown = e => { if (e.key === 'Enter') ask(); };
  card.append(h('div', {class: 'row'}, h('h3', {style: 'margin:0'}, icon('spark'), ' Ask about this dashboard'), h('span', {class: 'spacer'}), h('a', {class: 'small', href: '#/askd'}, 'Open Ask Relay')),
    h('div', {class: 'muted small'}, 'Answers use this dashboard\'s model, its measures and the filters you set here, on its data.'
      + (costOf('ask') && ORG().id ? ` A conversation uses ${costOf('ask')} credits for up to ${costOf('ask_questions') || 5} questions.` : '')), bar,
    h('div', {class: 'row askrow', style: 'margin-top:8px'}, input, msel.el, go), out);
  return card;
}
