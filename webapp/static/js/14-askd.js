/* ---------------- Ask D (phase 5): questions about your data, checked at every step ---------------- */
const SCOPE_LABEL = {dashboard: 'One dashboard', team: 'All my data', org: 'All my data'};

/* An Ask D answer as an interactive widget. Everything comes from the answer's own data: filters for its category
   columns and its date range, a chip for each of its measures, "By" to regroup, Top N, Bar / Line / Table, totals that
   follow the filters, hover / keyboard values, click to ask about a point, "Ask about this view", and a PNG. */
const ASK_COLORS = ['#2C7A66', '#4E6E9E', '#B78A2A', '#A8475A'];      // enterprise sequence: forest teal, slate, muted gold, rose
const ASK_IN = (() => { try { return /Kolkata|Calcutta/.test(Intl.DateTimeFormat().resolvedOptions().timeZone) || /-IN$/.test(navigator.language); } catch (e) { return false; } })();
const RATIO = /(per|avg|average|mean|rate|ratio|share|pct|percent|margin|%|price)/i;
const MONEY = /(sales|revenue|amount|value|price|cost|profit|spend|gmv|income|turnover)/i;
const prettyCol = c => String(c).replace(/_/g, ' ').replace(/\b\w/g, m => m.toUpperCase());
function askNum(v, cur) {
  if (v == null || isNaN(v)) return '—';
  const a = Math.abs(v), p = cur || '';
  if (ASK_IN && cur === '₹') return a >= 1e7 ? `${p}${(v / 1e7).toFixed(2).replace(/\.?0+$/, '')} Cr` : a >= 1e5 ? `${p}${(v / 1e5).toFixed(1).replace(/\.0$/, '')} L`
    : `${p}${(+v.toFixed(2)).toLocaleString('en-IN')}`;
  return a >= 1e9 ? `${p}${(v / 1e9).toFixed(1).replace(/\.0$/, '')}B` : a >= 1e6 ? `${p}${(v / 1e6).toFixed(1).replace(/\.0$/, '')}M`
    : a >= 1e4 ? `${p}${(v / 1e3).toFixed(1).replace(/\.0$/, '')}K` : a < 1 && v !== 0 ? String(+v.toFixed(3)) : `${p}${(+v.toFixed(2)).toLocaleString()}`;
}
const askFull = (v, cur) => v == null || isNaN(v) ? '—' : (cur || '') + (+(+v).toFixed(4)).toLocaleString(ASK_IN ? 'en-IN' : undefined);
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
  const curOf = c => cur && MONEY.test(c) && !/(share|pct|percent|%|margin)/i.test(c) ? cur : '';
  const st = {x: dims.includes(spec.x) ? spec.x : dims[0], on: new Set((spec.y || []).filter(c => nums.includes(c)).slice(0, 4)), view: 'bar', sort: false, top: 0,
    values: true, filters: {}, from: null, to: null};
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
    return [...g.values()].map(e => ({[st.x]: e.k, ...Object.fromEntries(nums.map(c => [c, RATIO.test(c) ? e.s[c] / e.n : e.s[c]]))}));
  };
  const total = (rows, c) => { const v = rows.map(r => +r[c] || 0); return RATIO.test(c) ? v.reduce((a, b) => a + b, 0) / (v.length || 1) : v.reduce((a, b) => a + b, 0); };
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
      dateCol && dateVals.length > 1 ? h('span', {class: 'amodel'}, prettyCol(dateCol), dsel(st.from, 'From'), '–', dsel(st.to, 'To')) : null,
      agg.length > 5 ? h('label', {class: 'amodel'}, 'Show', (() => { const s = h('select', {class: 'sel', 'aria-label': 'How many'}, [[0, 'All'], [5, 'Top 5'], [10, 'Top 10'], [20, 'Top 20']]
        .map(([v, l]) => h('option', {value: v, selected: st.top === v}, l))); s.onchange = () => { st.top = +s.value; draw(); }; return s; })()) : null,
      Object.values(st.filters).some(Boolean) || st.from || st.to || st.top ? h('button', {class: 'btn sm ghost', type: 'button',
        onclick: () => { st.filters = {}; st.from = st.to = null; st.top = 0; draw(); }}, icon('x'), 'Reset') : null].filter(Boolean));
    // measure chips and their totals for the current filters
    kpis.replaceChildren(...nums.slice(0, 8).map(c => {
      const i = nums.indexOf(c), on = st.on.has(c), color = ASK_COLORS[[...st.on].indexOf(c) % 4] || '#8E958E';
      return h('button', {class: 'akpi' + (on ? ' on' : ''), type: 'button', 'aria-pressed': String(on),
        title: `Show ${prettyCol(c)} · Shift+click to compare it with the others`, style: on ? `border-color:${color}` : '',
        onclick: e => {
          if (!e.shiftKey) st.on = new Set([c]);                      // measures differ in scale: one at a time by default
          else if (on && st.on.size > 1) st.on.delete(c);
          else if (!on) { if (st.on.size >= 4) st.on.delete([...st.on][0]); st.on.add(c); }
          if (st.view === 'table') st.tsort = c;
          draw(); }},
        h('span', {class: 'akl'}, on ? h('i', {style: `background:${color}`}) : null, prettyCol(c), RATIO.test(c) ? h('em', {}, ' avg') : null),
        h('b', {}, askNum(total(filtered, c), curOf(c))), i === 0 ? null : null);
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
      st.from || st.to ? `${prettyCol(dateCol)} ${st.from || '…'} to ${st.to || '…'}` : null, st.top ? `top ${st.top} by ${prettyCol(first)}` : null].filter(Boolean);
    foot.replaceChildren(h('span', {class: 'faint small'}, `${rows.length} ${prettyCol(st.x).toLowerCase()}${rows.length === 1 ? '' : 's'} · ${filtered.length} of ${rows0.length} rows` + (active.length ? ' · ' + active.join(' · ') : '')),
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
      sorted.map(r => h('tr', {}, h('td', {}, String(r[st.x] ?? '')), shown.map(c => h('td', {class: 'n'}, askFull(+r[c], curOf(c)))))))));
    svg = null;
  }
  function drawChart(rows, shown) {
    const W = 680, H = 236, L = 64, R = 10, T = 16, B = 34, pw = W - L - R, ph = H - T - B, n = Math.max(rows.length, 1), bw = pw / n;
    const vals = rows.flatMap(r => shown.map(s => +r[s] || 0));
    const ticks = niceTicks(Math.min(0, ...vals), Math.max(0, ...vals, 0.0001));
    const lo = ticks[0], hi = ticks[ticks.length - 1], Y = v => T + ph - (ph * ((+v || 0) - lo)) / (hi - lo || 1);
    const cur0 = curOf(shown[0]);
    svg = document.createElementNS(NS, 'svg');
    svg.setAttribute('viewBox', `0 0 ${W} ${H}`); svg.setAttribute('width', '100%'); svg.setAttribute('role', 'group');
    svg.setAttribute('aria-label', `${st.view === 'bar' ? 'Bar' : 'Line'} chart of ${shown.map(prettyCol).join(', ')} by ${prettyCol(st.x)}. Use the arrow keys to move between points.`);
    const el = (tag, attrs, txt) => { const e = document.createElementNS(NS, tag); for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v); if (txt != null) e.textContent = txt; svg.append(e); return e; };
    el('rect', {x: 0, y: 0, width: W, height: H, fill: '#fff'});
    ticks.forEach(t => { el('line', {x1: L, x2: W - R, y1: Y(t), y2: Y(t), stroke: t === 0 ? '#C9C4B5' : '#EEEBE3'});
      el('text', {x: L - 6, y: Y(t) + 3.5, 'font-size': 10, 'text-anchor': 'end', fill: '#6E756E'}, askNum(t, shown.length === 1 ? cur0 : '')); });
    const every = Math.max(1, Math.ceil(n / 12));
    rows.forEach((r, i) => { if (i % every === 0) el('text', {x: L + i * bw + bw / 2, y: H - B + 15, 'font-size': 10, 'text-anchor': 'middle', fill: '#5F655F'}, String(r[st.x] ?? '').slice(0, 13)); });
    el('text', {x: L + pw / 2, y: H - 4, 'font-size': 10, 'text-anchor': 'middle', fill: '#6E756E', 'font-weight': 600}, prettyCol(st.x));
    if (!rows.length) el('text', {x: W / 2, y: H / 2, 'font-size': 13, 'text-anchor': 'middle', fill: '#6E756E'}, 'Nothing matches the filters');
    const marks = shown.map(() => []), showVals = st.values && rows.length * shown.length <= 24;
    shown.forEach((s, si) => {
      const color = ASK_COLORS[si % 4], cs = curOf(s);
      if (st.view === 'bar') {
        const gw = Math.max(2, bw - 8) / shown.length;
        rows.forEach((r, i) => { const v = +r[s] || 0, x = L + i * bw + 4 + si * gw;
          marks[si].push(el('rect', {x, y: Math.min(Y(v), Y(0)), width: Math.max(1.5, gw - 1), height: Math.abs(Y(v) - Y(0)), rx: 3, fill: color, class: 'amark'}));
          if (showVals) el('text', {x: x + gw / 2, y: Math.min(Y(v), Y(0)) - 4, 'font-size': 9.5, 'text-anchor': 'middle', fill: '#2F4039'}, askNum(v, cs)); });
      } else {
        el('polyline', {points: rows.map((r, i) => `${L + i * bw + bw / 2},${Y(r[s])}`).join(' '), fill: 'none', stroke: color, 'stroke-width': 2.4, 'stroke-linejoin': 'round'});
        rows.forEach((r, i) => { marks[si].push(el('circle', {cx: L + i * bw + bw / 2, cy: Y(r[s]), r: n > 30 ? 2.2 : 3.5, fill: '#fff', stroke: color, 'stroke-width': 2, class: 'amark'}));
          if (showVals) el('text', {x: L + i * bw + bw / 2, y: Y(r[s]) - 8, 'font-size': 9.5, 'text-anchor': 'middle', fill: '#2F4039'}, askNum(+r[s], cs)); });
      }
    });
    const show = (i, band) => {
      marks.forEach(ms => ms.forEach((m, j) => m.classList.toggle('dim', j !== i)));
      const r = rows[i];
      tip.replaceChildren(h('b', {}, String(r[st.x] ?? '')), ...shown.map((s, si) => h('div', {}, h('i', {style: `background:${ASK_COLORS[si % 4]}`}), `${prettyCol(s)}: `, h('b', {}, askFull(+r[s], curOf(s))))),
        ...(opts.onAsk ? [h('div', {class: 'faint'}, 'Click to ask about it')] : []));
      const bb = band.getBoundingClientRect(), wb = host.getBoundingClientRect();
      tip.style.left = Math.min(Math.max(0, bb.left - wb.left + bb.width / 2 - 95), Math.max(0, wb.width - 200)) + 'px';
      tip.classList.add('on');
    };
    const hide = () => { tip.classList.remove('on'); marks.forEach(ms => ms.forEach(m => m.classList.remove('dim'))); };
    const bands = rows.map((r, i) => {
      const band = el('rect', {x: L + i * bw, y: T, width: bw, height: ph, fill: 'transparent', class: 'aband', tabindex: 0, role: 'button',
        'aria-label': `${r[st.x]}: ` + shown.map(s => `${prettyCol(s)} ${askFull(+r[s], curOf(s))}`).join(', ')});
      const askIt = () => { if (opts.onAsk && shown.length) opts.onAsk(`Tell me more about ${r[st.x]}: why is ${prettyCol(shown[0])} ${askFull(+r[shown[0]], curOf(shown[0]))}, and what drives it?`); };
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
  return h('div', {class: 'dprev', style: 'max-height:280px'}, h('table', {}, h('tr', {}, d.columns.map(c => h('th', {}, c))),
    d.rows.slice(0, max || 100).map(r => h('tr', {}, d.columns.map(c => h('td', {}, r[c] == null ? '' : typeof r[c] === 'number' ? r[c].toLocaleString() : String(r[c])))))));
}

function answerCard(m, opts) {
  const a = m.body || m, v = a.validation || {}, u = a.usage || {};
  const fb = m.feedback;
  const rate = async (rating, extra) => { try { await api(`/api/askd/messages/${m.id || a.message_id}/feedback`, {json: {rating, ...(extra || {})}}); notify('Thanks — noted', 'ok'); } catch (e) { notify(e.message, 'err'); } };
  const mid = m.id || a.message_id;
  const chart = askChart(a, {onAsk: opts && opts.onAsk});
  return h('div', {class: 'card', style: 'margin:0'},
    h('div', {class: 'row', style: 'gap:6px'}, icon('spark'), h('b', {}, 'Ask Relay'),
      v.where ? h('span', {class: 'tag ' + (v.where === 'live' ? 'acc' : '')}, v.where === 'live' ? 'Live from BigQuery' : 'From your dashboard data') : null,
      a.cached ? h('span', {class: 'tag', title: 'The same question was answered recently; no new AI cost'}, 'Answered before') : null, h('span', {class: 'spacer'}),
      h('span', {class: 'faint small', title: 'What this answer cost in AI'}, ['AI cost ' + aiUsd(u.cost_usd), a.seconds ? `${a.seconds}s` : null].filter(Boolean).join(' · '))),
    (a.result || {}).headline ? h('div', {style: 'font-size:19px;font-weight:600;line-height:1.35;margin:8px 0 2px'}, a.result.headline) : null,
    chart,
    a.summary ? h('p', {style: 'margin:8px 0'}, h('b', {}, 'What this means. '), a.summary) : null,
    (a.actions || []).length ? h('div', {}, h('b', {class: 'small'}, 'What you could do next'), h('ul', {style: 'margin:4px 0 8px'}, a.actions.map(x => h('li', {}, x)))) : null,
    !chart ? askTable(a.data, 50) : h('details', {class: 'more'}, h('summary', {}, `See the numbers (${(a.data || {}).row_count || 0} rows)`), askCsvBtn(a.data), askTable(a.data, 100)),
    (v.not_included || []).length ? h('div', {class: 'note warn small'}, h('b', {}, 'Could not include: '), v.not_included.join(' · ')) : null,
    !(v.queries || []).length ? null : h('details', {class: 'more'}, h('summary', {}, 'How Relay worked this out (for analysts)'),
      (v.queries || []).map(q => h('div', {style: 'margin:8px 0;padding-left:8px;border-left:3px solid ' + (q.error ? 'var(--err)' : 'var(--line-2)')},
        h('div', {class: 'small'}, h('b', {}, q.id), ` · ${q.where || q.engine || ''}`, q.why ? ` · ${q.why}` : '', q.row_count != null ? ` · ${q.row_count.toLocaleString()} rows${q.limited ? ' (limit reached)' : ''} in ${q.seconds}s` : ''),
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
  notify('Drawing the snapshot…');
  try {
    const r = await fetch(`/api/askd/messages/${mid}/snapshot`, {method: 'POST'});
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || 'Snapshot failed');
    const a = h('a', {href: URL.createObjectURL(await r.blob()), download: `ask-relay-${mid}.png`}); a.click();
  } catch (e) { notify(e.message, 'err'); }
}
async function sendToDashboard(mid, project) {
  const note = await askText('Send to the dashboard', {label: 'Anything Relay should know when adding it?', hint: 'Optional. It goes to the dashboard as a change request.', ok: 'Send'});
  if (note === null) return;
  try { await api(`/api/askd/messages/${mid}/to-dashboard`, {json: {project, note}}); notify('Sent to the dashboard as a change request', 'ok'); } catch (e) { notify(e.message, 'err'); }
}
async function pickDashboard(mid) {
  const o = await api('/api/askd/options');
  const sel = h('select', {class: 'sel'}, o.dashboards.map(d => h('option', {value: d.id}, d.name)));
  const m = modal('Add this answer to a dashboard', h('div', {class: 'mbody'}, h('div', {class: 'muted small'}, 'It becomes a change request: Relay adds a visual or a page that answers the question, and the review gates check it.'),
    h('label', {class: 'f'}, 'Dashboard'), sel, h('div', {class: 'row', style: 'justify-content:flex-end;margin-top:12px'}, h('button', {class: 'btn', onclick: () => m.remove()}, 'Cancel'),
      h('button', {class: 'btn primary', onclick: () => { m.remove(); sendToDashboard(mid, sel.value); }}, 'Continue'))));
}

/* the Ask Relay page (D2D Relay): a plain-words conversation with your data */
const aiUsd = x => !x ? '$0.00' : x < 0.01 ? 'under $0.01' : '$' + x.toFixed(2);
const ASK_STEPS = ['Looking at your data…', 'Running the numbers…', 'Double-checking every figure…', 'Drawing the chart…', 'Writing it up in plain words…'];
async function renderAskD() {
  const tid = (location.hash.split('/')[2] || '').split('?')[0] || null;
  const page = h('div', {class: 'page wide askpage'});
  $('#main').replaceChildren(page);
  document.title = 'Ask Relay · D2D Relay';
  let opts, list, th = null, cost = null;
  try {
    [opts, list, cost] = await Promise.all([api('/api/askd/options'), api('/api/askd/threads'),
      api('/api/askd/costs' + (tid ? '?thread=' + encodeURIComponent(tid) : '')).catch(() => null)]);
    if (tid) th = await api(`/api/askd/threads/${tid}`);
  } catch (e) { return page.append(h('div', {class: 'note err'}, e.message)); }
  if (!location.hash.startsWith('#/askd')) return;
  if (opts.brand_colors && opts.brand_colors.length >= 3) ASK_COLORS.splice(0, ASK_COLORS.length, ...opts.brand_colors);   // charts in the brand palette

  // what the question is about: everything, or one dashboard (a simple drop-down, fixed once a conversation starts)
  let scope = th ? th.scope : {kind: 'team'};
  const scopeSel = h('select', {class: 'sel', 'aria-label': 'What to ask about', disabled: !!th, style: 'width:auto;max-width:360px'},
    h('option', {value: ''}, 'All my data'),
    opts.dashboards.map(d => h('option', {value: d.id, selected: scope.kind === 'dashboard' && scope.project === d.id}, 'Dashboard: ' + d.name)));
  scopeSel.onchange = () => { scope = scopeSel.value ? {kind: 'dashboard', project: scopeSel.value} : {kind: 'team'}; };

  // the AI cost box: this conversation, this month
  const costBox = h('div', {class: 'card flat askcost', style: 'margin:0 0 12px'});
  const drawCost = () => {
    if (!cost) return costBox.replaceChildren();
    const row = (k, v, strong) => [h('dt', {}, strong ? h('b', {}, k) : k), h('dd', {}, strong ? h('b', {}, v) : v)];
    costBox.replaceChildren(h('div', {class: 'row', style: 'gap:6px'}, icon('gauge'), h('b', {class: 'small'}, 'AI cost')),
      h('dl', {class: 'kv small', style: 'margin:6px 0 0'},
        th ? row('This conversation', `${aiUsd(cost.thread_usd)} · ${cost.thread_questions} question${cost.thread_questions === 1 ? '' : 's'}`) : null,
        row(`Questions in ${cost.month}`, `${aiUsd(cost.ask_usd)} · ${cost.ask_questions} asked`),
        row('Dashboards', aiUsd(cost.dashboards_usd)),
        cost.branding_usd ? row('Branding', aiUsd(cost.branding_usd)) : null,
        row('Total this month', aiUsd(cost.total_usd), true)));
  };
  const refreshCost = async id => { try { cost = await api('/api/askd/costs' + (id ? '?thread=' + encodeURIComponent(id) : '')); drawCost(); } catch (e) { /* the answer matters more */ } };
  drawCost();

  const threadsBox = h('div', {class: 'vlist'},
    h('a', {class: 'btn primary', href: '#/askd', style: 'width:100%;justify-content:center;margin-bottom:10px'}, icon('plus'), 'New question'),
    h('div', {class: 'small muted', style: 'margin:4px 2px 6px'}, 'Your conversations'),
    list.threads.length ? list.threads.map(t => h('a', {class: 'vitem' + (t.id === tid ? ' on' : ''), href: `#/askd/${t.id}`},
      h('div', {class: 'l1'}, h('span', {class: 'lab'}, t.title)), h('div', {class: 'l2'}, `${t.scope.kind === 'dashboard' ? 'One dashboard' : 'All my data'} · ${ago(t.updated)}`)))
      : h('div', {class: 'vitem'}, h('div', {class: 'l2'}, 'Your questions will appear here.')));

  const chat = h('div', {class: 'stack', 'aria-live': 'polite'});
  const input = h('textarea', {rows: 2, placeholder: 'Ask a question about your business, in your own words…', 'aria-label': 'Your question'});
  const go = h('button', {class: 'btn primary'}, icon('send'), 'Ask');
  const you = q => h('div', {class: 'row', style: 'justify-content:flex-end'},
    h('div', {class: 'card flat askq', style: 'margin:0;background:var(--ink);color:var(--paper);max-width:75%'}, q));
  const ask = async q => {
    q = (q || input.value).trim(); if (!q) return;
    go.disabled = true; input.value = '';
    const hello = chat.querySelector('.askhello'); if (hello) hello.remove();
    chat.append(you(q));
    let i = 0;
    const msg = h('span', {}, ASK_STEPS[0]);
    const wait = h('div', {class: 'card flat', style: 'margin:0'}, h('span', {class: 'spin', style: 'display:inline-block;vertical-align:middle;margin-right:10px'}), msg);
    const tick = setInterval(() => { i = Math.min(i + 1, ASK_STEPS.length - 1); msg.textContent = ASK_STEPS[i]; }, 3500);
    chat.append(wait); wait.scrollIntoView({block: 'end', behavior: 'smooth'});
    const t0 = Date.now();
    try {
      const r = await api('/api/askd/ask', {json: {question: q, scope, thread_id: th ? th.id : null, model: CATALOG.default}});
      clearInterval(tick); wait.remove();
      if (!th) { location.hash = `#/askd/${r.thread_id}`; return; }
      chat.append(answerCard({id: r.message_id, body: {...r, seconds: Math.round((Date.now() - t0) / 1000)}}, {onAsk: ask}));
      refreshCost(th.id);
    } catch (e) {
      clearInterval(tick);
      wait.replaceChildren(h('div', {class: 'note err', style: 'margin:0'}, 'Relay could not answer that: ' + e.message + ' Try asking it a different way.'));
    }
    go.disabled = false; input.focus();
  };
  go.onclick = () => ask();
  input.onkeydown = e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); ask(); } };

  for (const m of (th ? th.messages : [])) chat.append(m.role === 'user' ? you(m.body.text) : answerCard(m, {onAsk: ask}));
  if (!th) {
    chat.append(h('div', {class: 'card askhello', style: 'margin:0;text-align:center;padding:28px 20px'},
      h('h2', {style: 'margin:0 0 6px'}, 'What would you like to know?'),
      h('p', {class: 'muted', style: 'margin:0 auto 16px;max-width:560px'}, opts.dashboards.length
        ? 'Ask in your own words. Relay answers with the numbers, a chart you can explore, what it means and what you could do next.'
        : 'Build a dashboard first (or connect BigQuery), then Relay can answer questions about that data.'),
      h('div', {class: 'chips', style: 'justify-content:center'}, (opts.suggestions || []).map(x => h('button', {class: 'chip', type: 'button', onclick: () => ask(x)}, icon('spark'), ' ' + x))),
      h('div', {class: 'small muted', style: 'margin-top:16px'}, 'Tip: ask about a trend ("month by month"), a comparison ("vs last year"), the best or worst ("top 5") or a cause ("why did … drop?").')));
  }
  page.append(h('div', {class: 'phead'}, h('div', {style: 'flex:1'}, h('h1', {}, 'Ask Relay'),
      h('div', {class: 'meta'}, 'Ask a question about your business. Get the answer, a chart and what to do next.'))),
    h('div', {class: 'vwrap'}, h('div', {}, costBox, threadsBox),
      h('div', {class: 'stack'}, chat, h('div', {class: 'card', style: 'margin:0;position:sticky;bottom:8px'},
        h('div', {class: 'row', style: 'gap:8px;margin-bottom:8px'}, h('span', {class: 'small muted'}, 'Asking about'), scopeSel), input,
        h('div', {class: 'row', style: 'margin-top:8px'}, h('span', {class: 'faint small'}, 'Enter to ask · Shift+Enter for a new line'), h('span', {class: 'spacer'}), go)))));
  if (th) setTimeout(() => chat.lastChild && chat.lastChild.scrollIntoView({block: 'end'}), 50);
  else input.focus();
}

/* the dashboard panel (Overview tab) */
function askPanel(st) {
  const card = h('div', {class: 'card', id: 'askpanel'});
  const filters = {}, out = h('div', {class: 'stack', style: 'margin-top:10px'});
  let page = '', thread = null;
  const input = h('input', {type: 'text', placeholder: `Ask about ${st.name}, e.g. "Which store grew fastest?"`});
  const go = h('button', {class: 'btn primary'}, icon('spark'), 'Ask');
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
    const wait = h('div', {class: 'muted small'}, 'Ask Relay is working…'); out.prepend(wait);
    try {
      const r = await api('/api/askd/ask', {json: {question: q, thread_id: thread, model: msel.value(), scope: {kind: 'dashboard', project: st.id, page: page || null, filters: {...filters}}}});
      thread = r.thread_id; wait.replaceWith(answerCard({id: r.message_id, body: r}, {project: st.access && st.access.can_edit ? st.id : null, thread, onAsk: ask}));
    } catch (e) { wait.replaceWith(h('div', {class: 'note err'}, e.message)); }
    go.disabled = false;
  };
  go.onclick = () => ask();
  input.onkeydown = e => { if (e.key === 'Enter') ask(); };
  card.append(h('div', {class: 'row'}, h('h3', {style: 'margin:0'}, icon('spark'), ' Ask about this dashboard'), h('span', {class: 'spacer'}), h('a', {class: 'small', href: '#/askd'}, 'Open Ask Relay →')),
    h('div', {class: 'muted small'}, 'Answers use this dashboard\'s model, its measures and the filters you set here, on its data.'), bar,
    h('div', {class: 'row askrow', style: 'margin-top:8px'}, input, msel.el, go), out);
  return card;
}
