/* Prototype renderer for Power BI's own visuals (Relay `pbi.*` types).
   Each visual is drawn the way Power BI lays it out — container (title, subtitle, background, border, shadow,
   padding), axes, gridlines, legend, data labels with display units, series and category colors, field-value and
   gradient colors — from the rows of its prototype SQL (one column per field, named after the field) and its
   Format-pane settings. Settings it does not draw are still written to the report: Power BI applies all of them.
   API: RelayStock.render(box, visual, ctx) where visual = {stock: {vt, renderer, fields, rows, format, sort},
   header: {title, subtitle}} and ctx = {palette, card, border, radius, text, muted, font, frame, fmtNum}. */
(function () {
  'use strict';
  const NS = 'http://www.w3.org/2000/svg', PT = 4 / 3;
  const UNITS = [[1e12, 'T'], [1e9, 'bn'], [1e6, 'M'], [1e3, 'K']];
  const GOOD = '#1AAB40', BAD = '#D64550', NEUTRAL = '#E6B700';
  let measureCtx = null, tip = null;

  // ------------------------------------------------------------------ small helpers
  function measure(s, size, weight) {
    if (!measureCtx) measureCtx = document.createElement('canvas').getContext('2d');
    measureCtx.font = `${weight || 400} ${size}px "Segoe UI", system-ui, sans-serif`;
    return measureCtx.measureText(String(s)).width;
  }
  function el(tag, attrs, parent) {
    const e = document.createElementNS(NS, tag);
    for (const k in attrs || {}) if (attrs[k] !== undefined && attrs[k] !== null && attrs[k] !== false) e.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(e);
    return e;
  }
  function text(parent, x, y, s, o) {
    o = o || {};
    const t = el('text', {x, y, 'font-size': o.size || 11, fill: o.color || '#605E5C', 'text-anchor': o.anchor || 'start',
      'dominant-baseline': o.base || 'central', 'font-weight': o.bold ? 600 : 400, 'font-style': o.italic ? 'italic' : null,
      'text-decoration': o.underline ? 'underline' : null, 'font-family': o.font ? `${o.font}, "Segoe UI", sans-serif` : null,
      transform: o.rotate ? `rotate(${o.rotate} ${x} ${y})` : null}, parent);
    t.textContent = s;
    return t;
  }
  function fit(s, w, size, weight) {
    s = String(s === null || s === undefined ? '' : s);
    if (w <= 8) return '';
    if (measure(s, size, weight) <= w) return s;
    while (s.length > 1 && measure(s + '…', size, weight) > w) s = s.slice(0, -1);
    return s.length > 1 ? s + '…' : '';
  }
  function rgb(hex) {
    const h = String(hex || '#000000').replace('#', '');
    return [0, 2, 4].map(i => parseInt(h.slice(i, i + 2), 16) || 0);
  }
  function toHex(c) { return '#' + c.map(v => Math.max(0, Math.min(255, Math.round(v))).toString(16).padStart(2, '0')).join('').toUpperCase(); }
  function shade(hex, p) {           // Power BI ThemeDataColor Percent: + lighter, - darker
    const c = rgb(hex);
    return toHex(c.map(v => p >= 0 ? v + (255 - v) * p : v * (1 + p)));
  }
  function mix(a, b, t) { const x = rgb(a), y = rgb(b); return toHex(x.map((v, i) => v + (y[i] - v) * t)); }
  function alpha(hex, transparency) {
    const [r, g, b] = rgb(hex);
    return `rgba(${r},${g},${b},${1 - Math.max(0, Math.min(100, +transparency || 0)) / 100})`;
  }
  function color(v, ctx, fallback) {
    if (typeof v === 'string') {
      if (/^#[0-9a-f]{6}$/i.test(v)) return v;
      const m = v.match(/^theme:(\d+)([+-]\d+(?:\.\d+)?)?$/);
      if (m) return shade(ctx.palette[+m[1] % ctx.palette.length], +(m[2] || 0));
    }
    if (v && typeof v === 'object' && v.theme !== undefined) return shade(ctx.palette[+v.theme % ctx.palette.length], +(v.percent || 0));
    return fallback;
  }
  const isMeasureRef = v => typeof v === 'string' && /^\[[^\]]+\]$/.test(v.trim());
  const refName = v => String(v).trim().replace(/^\[|\]$/g, '').replace(/^'?[^'[]+'?\[/, '').replace(/\]$/, '');

  // ------------------------------------------------------------------ format settings
  function settings(item) {
    const f = item.format || {};
    const get = (obj, prop, d) => {
      const o = f[obj];
      return o && o._ && o._[prop] !== undefined && o._[prop] !== null ? o._[prop] : d;
    };
    get.targets = obj => (f[obj] && f[obj].for) || [];
    get.has = obj => !!f[obj];
    return get;
  }
  // A per-series / per-value override: `for: "[Measure]"` or `for: {"Table[Column]": value}`.
  function override(get, obj, prop, who) {
    for (const t of get.targets(obj)) {
      if (t.props[prop] === undefined) continue;
      const tg = t.target;
      if (typeof tg === 'string' && who.measure && refName(tg) === who.measure) return t.props[prop];
      if (tg && typeof tg === 'object') {
        const [ref, val] = Object.entries(tg)[0];
        const col = refName(ref);
        for (const [c, v] of who.values || []) if (c === col && String(v) === String(val)) return t.props[prop];
      }
    }
    return undefined;
  }

  // ------------------------------------------------------------------ numbers
  function fmtParts(fmt) {
    const sec = String(fmt || '').split(';')[0].replace(/"[^"]*"/g, '').split(String.fromCharCode(92)).join('');
    const dm = sec.match(/[.](0+)/);
    return {pct: sec.includes('%'), cur: (sec.match(/[$€£¥₹]/) || [''])[0], dec: dm ? dm[1].length : 0};
  }
  function autoUnit(m) { for (const [u] of UNITS) if (Math.abs(m) >= u) return u; return 1; }
  // A value as Power BI prints it: the measure's format, or display units (0 auto, 1 none, 1000 …) and a precision.
  function num(v, fmt, units, prec, scaleRef, ctx) {
    if (v === null || v === undefined || v === '') return '(Blank)';
    if (typeof v !== 'number') return String(v);
    const p = fmtParts(fmt);
    let u = units === undefined || units === null ? 0 : +units;
    if (p.pct && (u === 0 || u === 1)) {
      if (prec === undefined || prec === null) return ctx.fmtNum(v, fmt);      // the measure's own format (signs, decimals)
      const sign = String(fmt || '').includes(';') && String(fmt).trim().startsWith('+') && v > 0 ? '+' : '';
      return sign + (v * 100).toLocaleString('en-US', {minimumFractionDigits: +prec, maximumFractionDigits: +prec}) + '%';
    }
    if (u === 0) u = autoUnit(scaleRef === undefined ? v : scaleRef);
    if (u <= 1) return prec === undefined || prec === null ? ctx.fmtNum(v, fmt)
      : (v < 0 ? '-' : '') + p.cur + Math.abs(v).toLocaleString('en-US', {minimumFractionDigits: +prec, maximumFractionDigits: +prec});
    const s = v / u, suffix = (UNITS.find(x => x[0] === u) || [u, ''])[1];
    const d = prec === undefined || prec === null ? (Math.abs(s) < 10 ? 2 : Math.abs(s) < 100 ? 1 : 0) : +prec;
    return (v < 0 ? '-' : '') + p.cur + Math.abs(s).toLocaleString('en-US', {minimumFractionDigits: d, maximumFractionDigits: d}) + suffix;
  }
  // Decimals a tick label needs at these display units (0 for 250K steps, 1 for 2.5K steps).
  function tickPrec(ticks, fmt, units) {
    if (ticks.length < 2) return 0;
    const step = Math.abs(ticks[1] - ticks[0]), p = fmtParts(fmt);
    if (p.pct) return Math.max(0, Math.ceil(-Math.log10(step * 100) + 1e-9));
    const u = units ? (+units <= 1 ? 1 : +units) : autoUnit(Math.max(...ticks.map(Math.abs)));
    return Math.max(0, Math.min(3, Math.ceil(-Math.log10(step / u) + 1e-9)));
  }
  function niceTicks(lo, hi, n) {
    if (!(isFinite(lo) && isFinite(hi))) { lo = 0; hi = 1; }
    if (lo === hi) { if (lo === 0) hi = 1; else if (lo > 0) lo = 0; else hi = 0; }
    const raw = (hi - lo) / Math.max(1, n), mag = Math.pow(10, Math.floor(Math.log10(raw))), r = raw / mag;
    const step = (r <= 1 ? 1 : r <= 2 ? 2 : r <= 2.5 ? 2.5 : r <= 5 ? 5 : 10) * mag;
    const start = Math.floor(lo / step + 1e-9) * step, end = Math.ceil(hi / step - 1e-9) * step, out = [];
    for (let v = start; v <= end + step / 2; v += step) out.push(Math.abs(v) < step / 1e6 ? 0 : v);
    return out;
  }
  function dateLabel(v) {
    const m = String(v).match(/^(\d{4})-(\d{2})-(\d{2})/);
    if (!m) return String(v);
    const mon = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][+m[2] - 1];
    return m[3] === '01' ? `${mon} ${m[1]}` : `${+m[3]} ${mon} ${m[1]}`;
  }
  function catLabel(v, field) {
    if (v === null || v === undefined || v === '') return '(Blank)';
    return field && field.type === 'dateTime' ? dateLabel(v) : String(v);
  }

  // ------------------------------------------------------------------ tooltip
  function showTip(ev, lines) {
    if (!tip) { tip = document.createElement('div'); tip.className = 'gba-tip'; document.body.appendChild(tip); }
    tip.replaceChildren();
    for (const [k, v] of lines) {
      const row = document.createElement('div'), a = document.createElement('span'), b = document.createElement('b');
      a.textContent = k; b.textContent = v; row.append(a, b); tip.appendChild(row);
    }
    tip.style.display = 'block';
    const x = Math.min(ev.clientX + 14, window.innerWidth - tip.offsetWidth - 8);
    tip.style.left = x + 'px'; tip.style.top = (ev.clientY + 14) + 'px';
  }
  function hideTip() { if (tip) tip.style.display = 'none'; }
  function hover(node, lines) {
    node.addEventListener('mousemove', e => showTip(e, lines()));
    node.addEventListener('mouseleave', hideTip);
    node.style.cursor = 'default';
  }

  // ------------------------------------------------------------------ data
  const fieldsOf = (item, role) => (item.fields && item.fields[role]) || [];
  function uniq(rows, col) {
    const seen = new Map();
    for (const r of rows) { const k = r[col]; if (!seen.has(String(k))) seen.set(String(k), k); }
    return [...seen.values()];
  }
  function total(rows, col, pred) {
    let s = null;
    for (const r of rows) if (!pred || pred(r)) { const v = r[col]; if (typeof v === 'number') s = (s || 0) + v; }
    return s;
  }
  function first(rows, col) { for (const r of rows) if (r[col] !== null && r[col] !== undefined) return r[col]; return null; }
  // A gradient or field-value color for one data point (rows = the point's rows).
  function pointColor(spec, rows, ctx, base, scaleCols) {
    if (isMeasureRef(spec)) {
      const c = first(rows, refName(spec));
      return typeof c === 'string' && /^#[0-9a-f]{6}$/i.test(c.trim()) ? c.trim() : base;
    }
    if (spec && typeof spec === 'object' && spec.gradient) {
      const g = spec.gradient, col = refName(g.input), v = total(rows, col);
      const range = scaleCols && scaleCols[col];
      if (v === null || !range) return g.min;
      const lo = g.minValue !== undefined ? g.minValue : range[0], hi = g.maxValue !== undefined ? g.maxValue : range[1];
      const t = hi === lo ? 1 : Math.max(0, Math.min(1, (v - lo) / (hi - lo)));
      if (g.mid) {
        const mid = g.midValue !== undefined ? g.midValue : (lo + hi) / 2, tm = mid === lo ? 1 : (v - lo) / (mid - lo);
        return v <= mid ? mix(g.min, g.mid, Math.max(0, Math.min(1, tm))) : mix(g.mid, g.max, Math.max(0, Math.min(1, (v - mid) / ((hi - mid) || 1))));
      }
      return mix(g.min, g.max, t);
    }
    return color(spec, ctx, base);
  }

  // ------------------------------------------------------------------ container (Power BI's visual container)
  function frame(box, v, ctx) {
    const item = v.stock, get = settings(item), head = v.header || {};
    const card = document.createElement('div');
    card.className = 'pbi-card';
    const bgShow = get('background', 'show', true);
    const st = card.style;
    st.cssText = 'height:100%;box-sizing:border-box;display:flex;flex-direction:column;overflow:hidden;position:relative';
    st.background = bgShow ? alpha(color(get('background', 'color'), ctx, ctx.card), get('background', 'transparency', 0)) : 'transparent';
    if (get.has('border')) {
      const show = get('border', 'show', true);
      st.border = show ? `${get('border', 'width', 1)}px solid ${color(get('border', 'color'), ctx, ctx.border)}` : 'none';
    } else if (bgShow) st.cssText += ';' + ctx.frame;
    st.borderRadius = get('border', 'radius', ctx.radius) + 'px';
    if (get('dropShadow', 'show', false)) st.boxShadow = '0 3px 10px rgba(0,0,0,.18)';
    const pad = k => get('padding', k, k === 'top' || k === 'bottom' ? 10 : 12);
    st.padding = `${pad('top')}px ${pad('right')}px ${pad('bottom')}px ${pad('left')}px`;
    const titleText = get('title', 'text', head.title);
    const title = isMeasureRef(titleText) ? (head.title || refName(titleText)) : titleText;
    if (get('title', 'show', !!title) && title) {
      const h = document.createElement('div');
      h.textContent = title;
      h.style.cssText = `flex:none;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;line-height:1.3;font-size:${get('title', 'fontSize', 12) * PT}px;`
        + `color:${color(get('title', 'fontColor'), ctx, ctx.text)};font-weight:${get('title', 'bold', true) ? 600 : 400};`
        + `font-style:${get('title', 'italic', false) ? 'italic' : 'normal'};text-align:${get('title', 'alignment', 'left')};`
        + `text-decoration:${get('title', 'underline', false) ? 'underline' : 'none'};font-family:${get('title', 'fontFamily', ctx.font)}, 'Segoe UI', sans-serif;`
        + (get('title', 'background') ? `background:${color(get('title', 'background'), ctx, 'transparent')};` : '');
      card.appendChild(h);
    }
    const sub = get('subTitle', 'text', head.subtitle);
    if (get('subTitle', 'show', !!sub) && sub) {
      const s = document.createElement('div');
      s.textContent = sub;
      s.style.cssText = `flex:none;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-top:1px;font-size:${get('subTitle', 'fontSize', 10) * PT}px;`
        + `color:${color(get('subTitle', 'fontColor'), ctx, ctx.muted)};text-align:${get('subTitle', 'alignment', 'left')};`
        + `font-weight:${get('subTitle', 'bold', false) ? 600 : 400}`;
      card.appendChild(s);
    }
    const body = document.createElement('div');
    body.style.cssText = 'flex:1;min-height:0;position:relative;margin-top:4px';
    card.appendChild(body);
    box.appendChild(card);
    return {body, get, title};
  }

  // ------------------------------------------------------------------ legend
  function legend(svg, W, items, get, ctx, opts) {
    // Returns {top, bottom, left, right} space used. items = [{name, color, shape}]
    const show = get('legend', 'show', items.length > 1 || !!opts.title);
    const out = {top: 0, bottom: 0, left: 0, right: 0};
    if (!show || !items.length) return out;
    const pos = String(get('legend', 'position', opts.position || 'Top'));
    const size = get('legend', 'fontSize', 8) * PT, col = color(get('legend', 'labelColor'), ctx, ctx.muted);
    const ttl = get('legend', 'showTitle', !!opts.title) ? get('legend', 'titleText', opts.title) : null;
    const vertical = /^(Left|Right)/.test(pos);
    const g = el('g', {class: 'legend'}, svg);
    if (vertical) {
      const w = Math.min(W * 0.3, Math.max(...items.map(i => measure(i.name, size))) + 26);
      const x0 = pos.startsWith('Left') ? 0 : W - w;
      let y = 6;
      if (ttl) { text(g, x0 + 2, y + 2, fit(ttl, w, size, 600), {size, color: col, bold: true}); y += size + 6; }
      for (const it of items) {
        swatch(g, x0 + 6, y + 2, it, size);
        text(g, x0 + 16, y + 2, fit(it.name, w - 18, size), {size, color: col});
        y += size + 6;
      }
      out[pos.startsWith('Left') ? 'left' : 'right'] = w + 6;
      return out;
    }
    let x = 2, y = 0, rows = 1;
    const lines = [[]];
    if (ttl) { lines[0].push({title: true, name: ttl, w: measure(ttl, size, 600) + 10}); x += measure(ttl, size, 600) + 10; }
    for (const it of items) {
      const w = measure(it.name, size) + 24;
      if (x + w > W && x > 2) { lines.push([]); x = 2; rows++; }
      lines[lines.length - 1].push({...it, w}); x += w;
      if (rows > 2) break;
    }
    const lh = size + 8;
    const top = !pos.startsWith('Bottom'), y0 = top ? 2 : null;
    lines.slice(0, 2).forEach((line, li) => {
      const width = line.reduce((s, i) => s + i.w, 0);
      let lx = /Center$/.test(pos) ? (W - width) / 2 : /Right$/.test(pos) ? W - width : 2;
      const ly = (top ? y0 : opts.height - lh * Math.min(2, lines.length)) + li * lh + lh / 2;
      for (const it of line) {
        if (it.title) text(g, lx, ly, it.name, {size, color: col, bold: true});
        else { swatch(g, lx + 5, ly, it, size); text(g, lx + 14, ly, fit(it.name, it.w - 16, size), {size, color: col}); }
        lx += it.w;
      }
    });
    out[top ? 'top' : 'bottom'] = lh * Math.min(2, lines.length) + 4;
    return out;
  }
  function swatch(g, x, y, it, size) {
    const r = Math.max(3.5, size * 0.32);
    if (it.shape === 'line') el('line', {x1: x - 5, y1: y, x2: x + 5, y2: y, stroke: it.color, 'stroke-width': 3, 'stroke-linecap': 'round'}, g);
    else if (it.shape === 'square') el('rect', {x: x - r, y: y - r, width: 2 * r, height: 2 * r, fill: it.color}, g);
    else el('circle', {cx: x, cy: y, r, fill: it.color}, g);
  }

  // ------------------------------------------------------------------ cartesian charts (columns, bars, lines, areas, combos, ribbon)
  function seriesOf(item, rows, ctx, get) {
    const cat = fieldsOf(item, 'Category')[0], ser = fieldsOf(item, 'Series')[0], ys = fieldsOf(item, 'Y'), y2s = fieldsOf(item, 'Y2');
    const out = [];
    if (ser && ys.length) uniq(rows, ser.col).forEach(sv => out.push({name: catLabel(sv, ser), field: ys[0], sv, serCol: ser.col, axis: 1}));
    else ys.forEach(y => out.push({name: y.name, field: y, axis: 1}));
    y2s.forEach(y => out.push({name: y.name, field: y, axis: 2}));
    out.forEach((s, i) => {
      const who = {measure: s.field.name, values: s.sv !== undefined ? [[ser.name, s.sv]] : []};
      const own = override(get, 'dataPoint', 'fill', who) ?? override(get, 'lineStyles', 'strokeColor', who);
      const base = ctx.palette[i % ctx.palette.length];
      const all = get('dataPoint', 'fill', get('dataPoint', 'defaultColor'));
      // a color without `for` is the series' color when it is the only series (in a combo: the only column series)
      const alone = out.length === 1 || (y2s.length && s.axis === 1 && out.filter(x => x.axis === 1).length === 1);
      s.color = color(own, ctx, null) || (alone && all && !isMeasureRef(all) && !(all && all.gradient) ? color(all, ctx, base) : base);
      s.pointSpec = alone ? all : null;
      s.who = who;
    });
    return {cat, ser, series: out};
  }
  function valueAt(rows, catCol, c, s) {
    return total(rows, s.field.col, r => (!catCol || String(r[catCol]) === String(c)) && (s.sv === undefined || String(r[s.serCol]) === String(s.sv)));
  }
  function sortCats(item, rows, cat, cats) {
    const sort = item.sort;
    if (!sort || !cat) return cats;
    const [ref, dir] = Array.isArray(sort) ? sort : [sort, 'asc'];
    const desc = String(dir || '').toLowerCase().startsWith('d');
    const name = refName(ref);
    const f = Object.values(item.fields).flat().find(x => x.name === name);
    const key = c => f && f.measure ? (total(rows, f.col, r => String(r[cat.col]) === String(c)) || 0) : c;
    return [...cats].sort((a, b) => { const x = key(a), y = key(b); return (x > y ? 1 : x < y ? -1 : 0) * (desc ? -1 : 1); });
  }

  function cartesian(svg, W, H, item, ctx, get, kind) {
    // kind: {bars: 'clustered'|'stacked'|'percent'|null, horizontal, lines: true|false, area: null|'area'|'stacked'|'percent', combo, ribbon}
    const rows = item.rows;
    const {cat, ser, series} = seriesOf(item, rows, ctx, get);
    if (!series.length) return note(svg, W, H, 'Add a measure to the Y well', ctx);
    let cats = cat ? sortCats(item, rows, cat, uniq(rows, cat.col)) : [null];
    const sm = fieldsOf(item, 'Rows')[0];
    const legendItems = series.map(s => ({name: s.name, color: s.color, shape: (kind.lines && !kind.area && (!kind.combo || s.axis === 2)) ? 'line' : 'circle'}));
    const space = legend(svg, W, legendItems, get, ctx, {title: ser ? ser.name : null, height: H});
    const panels = sm ? uniq(rows, sm.col).map(v => ({title: catLabel(v, sm), rows: rows.filter(r => String(r[sm.col]) === String(v))})) : [{title: null, rows}];
    // shared value domain
    const dom = (axis, rs) => {
      let lo = 0, hi = 0;
      const ss = series.filter(s => (s.axis || 1) === axis && (axis === 2 || !kind.combo || true));
      if (!ss.length) return null;
      const stackedBars = axis === 1 && (kind.bars === 'stacked' || kind.ribbon || kind.area === 'stacked');
      if (kind.bars === 'percent' || kind.area === 'percent') return [0, 1];
      for (const c of cats) {
        let pos = 0, neg = 0;
        for (const s of ss) {
          const v = valueAt(rs, cat && cat.col, c, s) || 0;
          if (stackedBars) { if (v >= 0) pos += v; else neg += v; } else { pos = Math.max(pos, v); neg = Math.min(neg, v); }
        }
        hi = Math.max(hi, pos); lo = Math.min(lo, neg);
      }
      return [lo, hi];
    };
    const d1 = dom(1, rows), d2 = dom(2, rows);
    const cols = sm ? Math.max(1, Math.min(get('smallMultiplesLayout', 'columnCount', Math.min(3, panels.length)), panels.length)) : 1;
    const nrows = Math.ceil(panels.length / cols);
    const area = {x: space.left, y: space.top, w: W - space.left - space.right, h: H - space.top - space.bottom};
    const pw = area.w / cols, ph = area.h / nrows;
    panels.forEach((p, i) => {
      const g = el('g', {transform: `translate(${area.x + (i % cols) * pw},${area.y + Math.floor(i / cols) * ph})`}, svg);
      let top = 0;
      if (p.title !== null) { text(g, pw / 2, 9, fit(p.title, pw - 8, 11, 600), {size: 11, color: ctx.text, anchor: 'middle', bold: true}); top = 18; }
      plot(g, pw, ph - top, top, p.rows, cats, cat, series, d1, d2, item, ctx, get, kind, i === 0 || !sm);
    });
    return null;
  }

  function plot(g, W, H, top, rows, cats, cat, series, d1, d2, item, ctx, get, kind, firstPanel) {
    const horiz = !!kind.horizontal;
    const axisSize = get('categoryAxis', 'fontSize', 9) * PT, vSize = get('valueAxis', 'fontSize', 9) * PT;
    const axCol = color(get('categoryAxis', 'labelColor'), ctx, ctx.muted), vCol = color(get('valueAxis', 'labelColor'), ctx, ctx.muted);
    const showCat = get('categoryAxis', 'show', true), showVal = get('valueAxis', 'show', true);
    const y2 = d2 && series.some(s => s.axis === 2);
    const fmt1 = (series.find(s => s.axis === 1) || series[0]).field.format, fmt2 = y2 ? series.find(s => s.axis === 2).field.format : null;
    const lo1 = get('valueAxis', 'start', d1 ? d1[0] : 0), hi1 = get('valueAxis', 'end', d1 ? d1[1] : 1);
    const t1 = d1 ? niceTicks(lo1, hi1, Math.max(2, Math.round((horiz ? W : H) / 70))) : [];
    const t2 = y2 ? niceTicks(get('y2Axis', 'secStart', d2[0]), get('y2Axis', 'secEnd', d2[1]), Math.max(2, Math.round(H / 70))) : [];
    const pct = kind.bars === 'percent' || kind.area === 'percent';
    const prec1 = get('valueAxis', 'labelPrecision', tickPrec(t1, fmt1, get('valueAxis', 'labelDisplayUnits', 0)));
    const tickLabel = (v, f, axisObj) => pct ? Math.round(v * 100) + '%' : num(v, f, get(axisObj, 'labelDisplayUnits', 0), prec1, Math.max(...t1.map(Math.abs)), ctx);
    const vLabels = t1.map(v => tickLabel(v, fmt1, 'valueAxis'));
    const prec2 = get('y2Axis', 'secLabelPrecision', tickPrec(t2, fmt2, get('y2Axis', 'secLabelDisplayUnits', 0)));
    const v2Labels = t2.map(v => pct ? Math.round(v * 100) + '%' : num(v, fmt2, get('y2Axis', 'secLabelDisplayUnits', 0), prec2, Math.max(...t2.map(Math.abs)), ctx));
    const catTitle = get('categoryAxis', 'showAxisTitle', true) && cat ? get('categoryAxis', 'titleText', cat.name) : null;
    const valTitle = get('valueAxis', 'showAxisTitle', true) ? get('valueAxis', 'titleText', [...new Set(series.filter(s => s.axis === 1).map(s => s.field.name))].join(' and ')) : null;
    const catLabels = cats.map(c => catLabel(c, cat));
    let left, right, bottom, topPad = 6;
    if (horiz) {
      left = showCat ? Math.min(W * 0.32, Math.max(...catLabels.map(s => measure(s, axisSize))) + 14) + (catTitle ? 16 : 0) : 6;
      right = 10; bottom = (showVal ? vSize + 8 : 4) + (valTitle ? 16 : 0);
    } else {
      left = (showVal ? Math.max(...vLabels.map(s => measure(s, vSize))) + 8 : 4) + (valTitle ? 16 : 0);
      right = y2 ? Math.max(...v2Labels.map(s => measure(s, vSize))) + 10 : 10;
      bottom = (showCat ? axisSize + 10 : 4) + (catTitle ? 16 : 0);
    }
    const px = left, py = top + topPad, pw = Math.max(10, W - left - right), ph = Math.max(10, H - topPad - bottom);
    const vmin = t1.length ? t1[0] : 0, vmax = t1.length ? t1[t1.length - 1] : 1;
    const scale = v => horiz ? px + (v - vmin) / ((vmax - vmin) || 1) * pw : py + ph - (v - vmin) / ((vmax - vmin) || 1) * ph;
    const v2min = t2[0], v2max = t2[t2.length - 1];
    const scale2 = v => py + ph - (v - v2min) / ((v2max - v2min) || 1) * ph;
    // gridlines and value labels
    const gridShow = get('valueAxis', 'gridlineShow', true), gridCol = color(get('valueAxis', 'gridlineColor'), ctx, mix(ctx.border, '#FFFFFF', 0.25));
    const dash = {dotted: '1 3', dashed: '4 3', solid: null}[get('valueAxis', 'gridlineStyle', 'solid')] || null;
    t1.forEach((v, i) => {
      const p = scale(v);
      if (gridShow) el('line', horiz ? {x1: p, x2: p, y1: py, y2: py + ph} : {x1: px, x2: px + pw, y1: p, y2: p},
        g).setAttribute('style', `stroke:${gridCol};stroke-width:${get('valueAxis', 'gridlineThickness', 1)};${dash ? 'stroke-dasharray:' + dash : ''}`);
      if (showVal) text(g, horiz ? p : px - 6, horiz ? py + ph + vSize / 2 + 5 : p, vLabels[i], {size: vSize, color: vCol, anchor: horiz ? 'middle' : 'end'});
    });
    if (y2 && get('y2Axis', 'show', true)) t2.forEach((v, i) => text(g, px + pw + 6, scale2(v), v2Labels[i], {size: vSize, color: vCol}));
    if (valTitle && firstPanel) {
      if (horiz) text(g, px + pw / 2, py + ph + bottom - 7, fit(valTitle, pw, vSize), {size: vSize, color: color(get('valueAxis', 'titleColor'), ctx, vCol), anchor: 'middle'});
      else text(g, 8, py + ph / 2, fit(valTitle, ph, vSize), {size: vSize, color: color(get('valueAxis', 'titleColor'), ctx, vCol), anchor: 'middle', rotate: -90});
    }
    if (catTitle && firstPanel) {
      if (horiz) text(g, 8, py + ph / 2, fit(catTitle, ph, axisSize), {size: axisSize, color: color(get('categoryAxis', 'titleColor'), ctx, axCol), anchor: 'middle', rotate: -90});
      else text(g, px + pw / 2, py + ph + bottom - 7, fit(catTitle, pw, axisSize), {size: axisSize, color: color(get('categoryAxis', 'titleColor'), ctx, axCol), anchor: 'middle'});
    }
    // bands
    const n = cats.length, band = (horiz ? ph : pw) / Math.max(1, n);
    const inner = get('categoryAxis', 'innerPadding', 20) / 100;
    const bpos = i => (horiz ? py : px) + i * band;
    if (showCat) {
      const every = Math.max(1, Math.ceil((horiz ? axisSize + 4 : Math.max(...catLabels.map(s => measure(s, axisSize))) + 8) / band));
      catLabels.forEach((s, i) => {
        if (i % every) return;
        if (horiz) text(g, px - 6, bpos(i) + band / 2, fit(s, left - 8 - (catTitle ? 16 : 0), axisSize), {size: axisSize, color: axCol, anchor: 'end'});
        else text(g, bpos(i) + band / 2, py + ph + axisSize / 2 + 6, fit(s, band * every - 4, axisSize), {size: axisSize, color: axCol, anchor: 'middle'});
      });
    }
    const zero = scale(Math.max(vmin, Math.min(0, vmax)));
    const labelsOn = get('labels', 'show', false);
    const lSize = get('labels', 'fontSize', 9) * PT, lCol = color(get('labels', 'color'), ctx, ctx.text);
    const lUnits = get('labels', 'labelDisplayUnits', 0), lPrec = get('labels', 'labelPrecision', null);
    const barSeries = series.filter(s => kind.bars && (!kind.combo || s.axis === 1) && !(kind.lines && !kind.combo));
    const lineSeries = series.filter(s => !barSeries.includes(s));
    // ------------- bars
    if (barSeries.length) {
      const clustered = kind.bars === 'clustered';
      const bw = band * (1 - inner), slot = clustered ? bw / barSeries.length : bw;
      const ranges = {};
      if (kind.ribbon || kind.bars !== 'clustered') {
        // stacked positions per category
        cats.forEach((c, ci) => {
          let pos = 0, neg = 0;
          const tot = kind.bars === 'percent' ? barSeries.reduce((s, x) => s + Math.abs(valueAt(rows, cat && cat.col, c, x) || 0), 0) || 1 : 1;
          barSeries.forEach((s, si) => {
            let v = valueAt(rows, cat && cat.col, c, s);
            if (v === null) return;
            v = v / tot;
            const a = v >= 0 ? pos : neg, b = a + v;
            if (v >= 0) pos = b; else neg = b;
            ranges[ci + '|' + si] = [a, b, v * tot, v];
          });
        });
      }
      const scaleCols = colRanges(rows, item);
      // ribbons between neighbouring columns
      if (kind.ribbon && !horiz) {
        barSeries.forEach((s, si) => {
          for (let ci = 0; ci + 1 < n; ci++) {
            const a = ranges[ci + '|' + si], b = ranges[(ci + 1) + '|' + si];
            if (!a || !b) continue;
            const x1 = bpos(ci) + (band + bw) / 2, x2 = bpos(ci + 1) + (band - bw) / 2;
            el('path', {d: `M${x1},${scale(a[1])}L${x2},${scale(b[1])}L${x2},${scale(b[0])}L${x1},${scale(a[0])}Z`, fill: s.color, 'fill-opacity': 0.35}, g);
          }
        });
      }
      cats.forEach((c, ci) => {
        barSeries.forEach((s, si) => {
          let a, b, raw;
          if (clustered && !kind.ribbon) { raw = valueAt(rows, cat && cat.col, c, s); if (raw === null) return; a = 0; b = raw; }
          else { const r = ranges[ci + '|' + si]; if (!r) return; [a, b, raw] = r; }
          const off = clustered && !kind.ribbon ? (band - bw) / 2 + si * slot : (band - bw) / 2;
          // screen positions of the bar's two ends, smaller first (the value scale runs upwards for columns)
          const e1 = scale(a), e2 = scale(b), p1 = Math.min(e1, e2), p2 = Math.max(e1, e2);
          const sel = cat ? rows.filter(r => String(r[cat.col]) === String(c)) : rows;
          const who = {measure: s.field.name, values: [...(s.who.values || []), ...(cat ? [[cat.name, c]] : [])]};
          const own = override(get, 'dataPoint', 'fill', who);
          let fill = own !== undefined ? pointColor(own, sel, ctx, s.color, scaleCols) : s.pointSpec ? pointColor(s.pointSpec, sel, ctx, s.color, scaleCols) : s.color;
          const grad = fieldsOf(item, 'Gradient')[0];
          if (grad && own === undefined) { const v = total(sel, grad.col), r = scaleCols[grad.col]; if (v !== null && r) fill = mix(shade(s.color, 0.75), s.color, r[1] === r[0] ? 1 : (v - r[0]) / (r[1] - r[0])); }
          const rect = horiz
            ? el('rect', {x: p1, y: bpos(ci) + off, width: Math.max(0, p2 - p1), height: Math.max(0, slot - (clustered ? 1 : 0)), fill}, g)
            : el('rect', {x: bpos(ci) + off, y: p1, width: Math.max(0, slot - (clustered ? 1 : 0)), height: Math.max(0, p2 - p1), fill}, g);
          if (get('dataPoint', 'fillTransparency', 0)) rect.setAttribute('fill-opacity', 1 - get('dataPoint', 'fillTransparency', 0) / 100);
          hover(rect, () => [[cat ? cat.name : 'Value', cat ? catLabel(c, cat) : s.name], [s.name, num(raw, s.field.format, 1, null, null, ctx)]]);
          if (labelsOn && p2 - p1 > (horiz ? 24 : 12)) {
            const s_ = pct ? Math.round((b - a) * 100) + '%' : num(raw, s.field.format, lUnits, lPrec, Math.max(Math.abs(vmin), Math.abs(vmax)), ctx);
            const inside = !clustered || kind.ribbon, wide = measure(s_, lSize);
            if (horiz) {
              if (!inside || wide < p2 - p1 - 4) text(g, inside ? (p1 + p2) / 2 : (raw >= 0 ? p2 + 4 : p1 - 4), bpos(ci) + off + slot / 2, s_,
                {size: lSize, color: inside ? '#FFFFFF' : lCol, anchor: inside ? 'middle' : raw >= 0 ? 'start' : 'end'});
            } else if (wide <= slot - (inside ? 4 : 2)) {           // Power BI hides a label that does not fit its column
              text(g, bpos(ci) + off + slot / 2, inside ? (p1 + p2) / 2 : (raw >= 0 ? p1 - lSize * 0.7 : p2 + lSize * 0.7), s_, {size: lSize, color: inside ? '#FFFFFF' : lCol, anchor: 'middle'});
            }
          }
        });
      });
      el('line', horiz ? {x1: zero, x2: zero, y1: py, y2: py + ph} : {x1: px, x2: px + pw, y1: zero, y2: zero}, g).setAttribute('style', `stroke:${ctx.border}`);
    }
    // ------------- lines and areas
    if (lineSeries.length) {
      const cum = {};
      const stackedArea = kind.area === 'stacked' || kind.area === 'percent';
      const totals = cats.map(c => lineSeries.reduce((s, x) => s + Math.abs(valueAt(rows, cat && cat.col, c, x) || 0), 0) || 1);
      lineSeries.forEach((s, si) => {
        const sc = s.axis === 2 ? scale2 : scale;
        const own = w => override(get, 'lineStyles', w, s.who);
        const width = own('strokeWidth') ?? get('lineStyles', 'strokeWidth', 3);
        const marker = own('showMarker') ?? get('lineStyles', 'showMarker', false);
        const style = own('lineStyle') ?? get('lineStyles', 'lineStyle', 'solid');
        const smooth = (own('lineChartType') ?? get('lineStyles', 'lineChartType', 'linear')) === 'smooth';
        const step = (own('lineChartType') ?? get('lineStyles', 'lineChartType', 'linear')) === 'step';
        const pts = [];
        cats.forEach((c, ci) => {
          let v = valueAt(rows, cat && cat.col, c, s);
          if (v === null) return;
          let base = 0;
          if (stackedArea) { const k = ci; base = cum[k] || 0; if (kind.area === 'percent') v = v / totals[ci]; cum[k] = base + v; v = base + v; }
          pts.push({x: bpos(ci) + band / 2, y: sc(v), y0: sc(stackedArea ? base : Math.max(vmin, Math.min(0, vmax))), raw: valueAt(rows, cat && cat.col, c, s), c});
        });
        if (!pts.length) return;
        const path = linePath(pts, smooth, step);
        if (kind.area && s.axis !== 2) {
          const back = linePath([...pts].reverse().map(p => ({x: p.x, y: p.y0})), smooth, step).replace(/^M/, 'L');
          el('path', {d: path + back + 'Z', fill: s.color, 'fill-opacity': 1 - (get('lineStyles', 'areaTransparency', 60)) / 100}, g);
        }
        el('path', {d: path, fill: 'none', stroke: s.color, 'stroke-width': width * 0.8, 'stroke-linejoin': 'round', 'stroke-linecap': 'round',
          'stroke-dasharray': style === 'dashed' ? '6 4' : style === 'dotted' ? '1.5 3.5' : null}, g);
        pts.forEach(p => {
          const dot = el('circle', {cx: p.x, cy: p.y, r: marker ? get('lineStyles', 'markerSize', 5) * 0.8 : 7, fill: marker ? color(get('lineStyles', 'markerColor'), ctx, s.color) : 'transparent'}, g);
          hover(dot, () => [[cat ? cat.name : 'Value', cat ? catLabel(p.c, cat) : s.name], [s.name, num(p.raw, s.field.format, 1, null, null, ctx)]]);
          if (labelsOn) text(g, p.x, p.y - lSize * 0.9, num(p.raw, s.field.format, lUnits, lPrec, null, ctx), {size: lSize, color: lCol, anchor: 'middle'});
        });
      });
    }
    return null;
  }
  function linePath(pts, smooth, step) {
    if (step) return pts.map((p, i) => i ? `H${(pts[i - 1].x + p.x) / 2}V${p.y}H${p.x}` : `M${p.x},${p.y}`).join('');
    if (!smooth || pts.length < 3) return pts.map((p, i) => (i ? 'L' : 'M') + p.x + ',' + p.y).join('');
    let d = `M${pts[0].x},${pts[0].y}`;
    for (let i = 0; i < pts.length - 1; i++) {
      const p0 = pts[i - 1] || pts[i], p1 = pts[i], p2 = pts[i + 1], p3 = pts[i + 2] || p2;
      d += `C${p1.x + (p2.x - p0.x) / 6},${p1.y + (p2.y - p0.y) / 6} ${p2.x - (p3.x - p1.x) / 6},${p2.y - (p3.y - p1.y) / 6} ${p2.x},${p2.y}`;
    }
    return d;
  }
  function colRanges(rows, item) {
    const out = {};
    for (const r of rows) for (const k in r) if (typeof r[k] === 'number') { const o = out[k] || (out[k] = [Infinity, -Infinity]); o[0] = Math.min(o[0], r[k]); o[1] = Math.max(o[1], r[k]); }
    return out;
  }
  function note(svg, W, H, s, ctx) { text(svg, W / 2, H / 2, s, {size: 12, color: ctx.muted, anchor: 'middle'}); return null; }

  // ------------------------------------------------------------------ waterfall
  function waterfall(svg, W, H, item, ctx, get) {
    const rows = item.rows, cat = fieldsOf(item, 'Category')[0] || fieldsOf(item, 'Breakdown')[0], y = fieldsOf(item, 'Y')[0];
    if (!cat || !y) return note(svg, W, H, 'Needs a category and a measure', ctx);
    const cats = sortCats(item, rows, cat, uniq(rows, cat.col));
    const inc = color(get('sentimentColors', 'increaseFill'), ctx, GOOD), dec = color(get('sentimentColors', 'decreaseFill'), ctx, BAD);
    const tot = color(get('sentimentColors', 'totalFill'), ctx, ctx.palette[0]);
    const steps = [];
    let run = 0;
    for (const c of cats) { const v = total(rows, y.col, r => String(r[cat.col]) === String(c)) || 0; steps.push({c, a: run, b: run + v, v}); run += v; }
    steps.push({c: 'Total', a: 0, b: run, v: run, total: true});
    const lo = Math.min(0, ...steps.map(s => Math.min(s.a, s.b))), hi = Math.max(0, ...steps.map(s => Math.max(s.a, s.b)));
    const t = niceTicks(lo, hi, Math.max(2, Math.round(H / 70)));
    const vSize = get('valueAxis', 'fontSize', 9) * PT, axisSize = get('categoryAxis', 'fontSize', 9) * PT;
    const labels = t.map(v => num(v, y.format, get('valueAxis', 'labelDisplayUnits', 0), tickPrec(t, y.format, get('valueAxis', 'labelDisplayUnits', 0)), Math.max(...t.map(Math.abs)), ctx));
    const left = Math.max(...labels.map(s => measure(s, vSize))) + 10, bottom = axisSize + 12, top = 8;
    const pw = W - left - 8, ph = H - top - bottom, band = pw / steps.length;
    const sc = v => top + ph - (v - t[0]) / ((t[t.length - 1] - t[0]) || 1) * ph;
    t.forEach((v, i) => { el('line', {x1: left, x2: left + pw, y1: sc(v), y2: sc(v), stroke: mix(ctx.border, '#FFFFFF', 0.25)}, svg); text(svg, left - 6, sc(v), labels[i], {size: vSize, color: ctx.muted, anchor: 'end'}); });
    const labelsOn = get('labels', 'show', true), lSize = get('labels', 'fontSize', 9) * PT;
    steps.forEach((s, i) => {
      const x = left + i * band + band * 0.15, w = band * 0.7, y1 = sc(Math.max(s.a, s.b)), y2 = sc(Math.min(s.a, s.b));
      const r = el('rect', {x, y: y1, width: w, height: Math.max(1, y2 - y1), fill: s.total ? tot : s.v >= 0 ? inc : dec}, svg);
      hover(r, () => [[cat.name, s.total ? 'Total' : catLabel(s.c, cat)], [y.name, num(s.v, y.format, 1, null, null, ctx)]]);
      if (i + 1 < steps.length) el('line', {x1: x + w, x2: x + band, y1: sc(s.b), y2: sc(s.b), stroke: ctx.muted, 'stroke-dasharray': '2 2'}, svg);
      text(svg, x + w / 2, top + ph + axisSize / 2 + 6, fit(s.total ? 'Total' : catLabel(s.c, cat), band - 4, axisSize), {size: axisSize, color: ctx.muted, anchor: 'middle'});
      if (labelsOn && band > 26) text(svg, x + w / 2, y1 - lSize * 0.8, num(s.v, y.format, get('labels', 'labelDisplayUnits', 0), get('labels', 'labelPrecision', null), Math.abs(hi), ctx), {size: lSize, color: ctx.text, anchor: 'middle'});
    });
    return null;
  }

  // ------------------------------------------------------------------ pie / donut
  function pie(svg, W, H, item, ctx, get, donut) {
    const rows = item.rows, cat = fieldsOf(item, 'Category')[0], ys = fieldsOf(item, 'Y');
    if (!ys.length) return note(svg, W, H, 'Add a measure to Values', ctx);
    const slices = cat ? sortCats(item, rows, cat, uniq(rows, cat.col)).map((c, i) => ({name: catLabel(c, cat), raw: c, v: total(rows, ys[0].col, r => String(r[cat.col]) === String(c)) || 0, i, field: ys[0]}))
      : ys.map((y, i) => ({name: y.name, v: total(rows, y.col) || 0, i, field: y}));
    const sum = slices.reduce((s, x) => s + Math.max(0, x.v), 0) || 1;
    slices.forEach(s => {
      const own = override(get, 'dataPoint', 'fill', {measure: s.field.name, values: cat ? [[cat.name, s.raw]] : []});
      s.color = color(own, ctx, null) || ctx.palette[s.i % ctx.palette.length];
    });
    const space = legend(svg, W, slices.map(s => ({name: s.name, color: s.color})), get, ctx, {title: cat ? cat.name : null, height: H, position: 'Top'});
    const labelsOn = get('labels', 'show', true), style = get('labels', 'labelStyle', 'Category'), lSize = get('labels', 'fontSize', 9) * PT;
    const shownOf = s => {
      const val = num(s.v, s.field.format, get('labels', 'labelDisplayUnits', 0), get('labels', 'labelPrecision', null), sum, ctx);
      const share = (s.v / sum * 100).toFixed(get('labels', 'percentageLabelPrecision', 0)) + '%';
      return {Category: s.name, Data: val, 'Percent of total': share, Both: `${val} (${share})`, 'Category, percent of total': `${s.name} ${share}`,
        'Data value, percent of total': `${val} (${share})`, 'Category, data value': `${s.name} ${val}`,
        'Category, data value, percent of total': `${s.name} ${val} (${share})`, 'All detail labels': `${s.name} ${val} (${share})`}[style] || s.name;
    };
    const cx = space.left + (W - space.left - space.right) / 2, cy = space.top + (H - space.top - space.bottom) / 2;
    const room = labelsOn ? Math.min((W - space.left - space.right) * 0.34, Math.max(...slices.map(s => measure(shownOf(s), lSize))) + 22) : 6;
    const R = Math.max(10, Math.min((W - space.left - space.right) / 2 - room, (H - space.top - space.bottom - (labelsOn ? 2 * lSize + 8 : 10)) / 2));
    const inner = donut ? R * get('slices', 'innerRadiusRatio', 50) / 100 : 0;
    let a0 = (get('slices', 'startAngle', 0) - 90) * Math.PI / 180;
    for (const s of slices) {
      const a1 = a0 + Math.max(0, s.v) / sum * Math.PI * 2, large = a1 - a0 > Math.PI ? 1 : 0;
      const p = (r, a) => [cx + r * Math.cos(a), cy + r * Math.sin(a)];
      const [x0, y0] = p(R, a0), [x1, y1] = p(R, a1), [x2, y2] = p(inner, a1), [x3, y3] = p(inner, a0);
      const d = inner ? `M${x0},${y0}A${R},${R} 0 ${large} 1 ${x1},${y1}L${x2},${y2}A${inner},${inner} 0 ${large} 0 ${x3},${y3}Z`
        : `M${cx},${cy}L${x0},${y0}A${R},${R} 0 ${large} 1 ${x1},${y1}Z`;
      const path = el('path', {d: slices.length === 1 ? (inner ? `M${cx - R},${cy}a${R},${R} 0 1 1 ${2 * R},0a${R},${R} 0 1 1 ${-2 * R},0M${cx - inner},${cy}a${inner},${inner} 0 1 0 ${2 * inner},0a${inner},${inner} 0 1 0 ${-2 * inner},0` : `M${cx - R},${cy}a${R},${R} 0 1 1 ${2 * R},0a${R},${R} 0 1 1 ${-2 * R},0`) : d,
        fill: s.color, stroke: ctx.card, 'stroke-width': 1, 'fill-rule': 'evenodd'}, svg);
      hover(path, () => [[cat ? cat.name : 'Measure', s.name], [s.field.name, num(s.v, s.field.format, 1, null, null, ctx)], ['Share', (s.v / sum * 100).toFixed(1) + '%']]);
      if (labelsOn && (a1 - a0) > 0.18) {
        const mid = (a0 + a1) / 2, [lx, ly] = p(R + 12, mid), right = Math.cos(mid) >= 0;
        el('line', {x1: p(R, mid)[0], y1: p(R, mid)[1], x2: lx, y2: ly, stroke: ctx.muted, 'stroke-width': 0.8}, svg);
        text(svg, lx + (right ? 3 : -3), ly, fit(shownOf(s), Math.max(30, (right ? W - lx : lx) - 4), lSize), {size: lSize, color: color(get('labels', 'color'), ctx, ctx.text), anchor: right ? 'start' : 'end'});
      }
      a0 = a1;
    }
    if (donut && get('centerValue', 'show', false)) text(svg, cx, cy, num(sum, ys[0].format, 0, null, sum, ctx), {size: 14 * PT, color: ctx.text, anchor: 'middle', bold: true});
    return null;
  }

  // ------------------------------------------------------------------ treemap
  function squarify(items, x, y, w, h) {
    const out = [], total_ = items.reduce((s, i) => s + i.v, 0) || 1;
    let rest = items.map(i => ({...i, a: i.v / total_ * w * h})).filter(i => i.a > 0);
    while (rest.length) {
      const short = Math.min(w, h);
      let row = [rest[0]], worst = Infinity;
      for (let k = 1; k <= rest.length; k++) {
        const r = rest.slice(0, k), s = r.reduce((a, i) => a + i.a, 0);
        const wst = Math.max(...r.map(i => Math.max(short * short * i.a / (s * s), (s * s) / (short * short * i.a))));
        if (wst <= worst) { worst = wst; row = r; } else break;
      }
      const s = row.reduce((a, i) => a + i.a, 0), thick = s / short;
      let off = 0;
      for (const i of row) {
        const len = i.a / thick;
        out.push(w >= h ? {...i, x, y: y + off, w: thick, h: len} : {...i, x: x + off, y, w: len, h: thick});
        off += len;
      }
      if (w >= h) { x += thick; w -= thick; } else { y += thick; h -= thick; }
      rest = rest.slice(row.length);
    }
    return out;
  }
  function treemap(svg, W, H, item, ctx, get) {
    const rows = item.rows, grp = fieldsOf(item, 'Group')[0], det = fieldsOf(item, 'Details')[0], vals = fieldsOf(item, 'Values');
    if (!vals.length) return note(svg, W, H, 'Add a measure to Values', ctx);
    const groups = grp ? uniq(rows, grp.col).map((g, i) => ({name: catLabel(g, grp), raw: g, i, v: total(rows, vals[0].col, r => String(r[grp.col]) === String(g)) || 0}))
      : vals.map((m, i) => ({name: m.name, i, v: total(rows, m.col) || 0, field: m}));
    groups.sort((a, b) => b.v - a.v);
    const scaleCols = colRanges(rows, item), spec = get('dataPoint', 'fill');
    groups.forEach(g => {
      const own = override(get, 'dataPoint', 'fill', {measure: (g.field || vals[0]).name, values: grp ? [[grp.name, g.raw]] : []});
      const sel = grp ? rows.filter(r => String(r[grp.col]) === String(g.raw)) : rows;
      g.color = own !== undefined ? pointColor(own, sel, ctx, ctx.palette[g.i % ctx.palette.length], scaleCols)
        : spec !== undefined ? pointColor(spec, sel, ctx, ctx.palette[g.i % ctx.palette.length], scaleCols) : ctx.palette[g.i % ctx.palette.length];
    });
    const byMeasure = isMeasureRef(spec) || (spec && spec.gradient);          // colors encode a measure: no category legend
    const space = legend(svg, W, grp && !byMeasure ? groups.map(g => ({name: g.name, color: g.color, shape: 'square'})) : [], get, ctx, {title: grp ? grp.name : null, height: H});
    const lab = get('categoryLabels', 'show', true), dl = get('labels', 'show', false), lSize = get('categoryLabels', 'fontSize', 9) * PT;
    const ink = fill => { const [r, g, b] = rgb(fill); return 0.299 * r + 0.587 * g + 0.114 * b > 165 ? ctx.text : '#FFFFFF'; };   // readable on light fills
    for (const r of squarify(groups, space.left, space.top, W - space.left - space.right, H - space.top - space.bottom)) {
      const rect = el('rect', {x: r.x + 0.5, y: r.y + 0.5, width: Math.max(0, r.w - 1), height: Math.max(0, r.h - 1), fill: r.color}, svg);
      hover(rect, () => [[grp ? grp.name : 'Measure', r.name], [vals[0].name, num(r.v, (r.field || vals[0]).format, 1, null, null, ctx)]]);
      if (det) {
        const kids = uniq(rows.filter(x => String(x[grp.col]) === String(r.raw)), det.col).map(k => ({name: catLabel(k, det), v: total(rows, vals[0].col, x => String(x[grp.col]) === String(r.raw) && String(x[det.col]) === String(k)) || 0}));
        for (const k of squarify(kids.sort((a, b) => b.v - a.v), r.x, r.y, r.w, r.h)) el('rect', {x: k.x + 0.5, y: k.y + 0.5, width: Math.max(0, k.w - 1), height: Math.max(0, k.h - 1), fill: r.color, stroke: ctx.card, 'stroke-width': 1}, svg);
      }
      if (lab && r.w > 40 && r.h > 18) text(svg, r.x + 6, r.y + lSize, fit(r.name, r.w - 10, lSize), {size: lSize, color: color(get('categoryLabels', 'color'), ctx, ink(r.color))});
      if (dl && r.w > 40 && r.h > 34) text(svg, r.x + 6, r.y + lSize * 2.3, num(r.v, (r.field || vals[0]).format, get('labels', 'labelDisplayUnits', 0), get('labels', 'labelPrecision', null), null, ctx), {size: lSize, color: color(get('labels', 'color'), ctx, ink(r.color))});
    }
    return null;
  }

  // ------------------------------------------------------------------ funnel
  function funnel(svg, W, H, item, ctx, get) {
    const rows = item.rows, cat = fieldsOf(item, 'Category')[0], ys = fieldsOf(item, 'Y');
    if (!ys.length) return note(svg, W, H, 'Add a measure to Values', ctx);
    const stages = cat ? uniq(rows, cat.col).map(c => ({name: catLabel(c, cat), raw: c, v: total(rows, ys[0].col, r => String(r[cat.col]) === String(c)) || 0, field: ys[0]}))
      : ys.map(y => ({name: y.name, v: total(rows, y.col) || 0, field: y}));
    const max = Math.max(...stages.map(s => s.v), 1), axisSize = get('categoryAxis', 'fontSize', 9) * PT;
    const left = get('categoryAxis', 'show', true) ? Math.min(W * 0.3, Math.max(...stages.map(s => measure(s.name, axisSize))) + 10) : 4;
    const pctBar = get('percentBarLabel', 'show', true) ? 16 : 0;
    const ph = H - 2 * pctBar, band = ph / stages.length, pw = W - left - 6;
    const base = color(get('dataPoint', 'fill', get('dataPoint', 'defaultColor')), ctx, ctx.palette[0]);
    const style = get('labels', 'funnelLabelStyle', 'Data'), lSize = get('labels', 'fontSize', 9) * PT;
    if (pctBar) text(svg, left + pw / 2, 8, '100%', {size: 10, color: ctx.muted, anchor: 'middle'});
    stages.forEach((s, i) => {
      const w = Math.max(2, s.v / max * pw), x = left + (pw - w) / 2, y = pctBar + i * band + band * 0.08;
      const own = override(get, 'dataPoint', 'fill', {measure: s.field.name, values: cat ? [[cat.name, s.raw]] : []});
      const fill = color(own, ctx, null) || (get('dataPoint', 'showAllDataPoints', false) ? ctx.palette[i % ctx.palette.length] : base);
      const r = el('rect', {x, y, width: w, height: band * 0.84, fill}, svg);
      hover(r, () => [[cat ? cat.name : 'Stage', s.name], [s.field.name, num(s.v, s.field.format, 1, null, null, ctx)], ['% of first', (s.v / (stages[0].v || 1) * 100).toFixed(1) + '%']]);
      text(svg, left - 6, y + band * 0.42, fit(s.name, left - 10, axisSize), {size: axisSize, color: ctx.muted, anchor: 'end'});
      if (get('labels', 'show', true)) {
        const val = num(s.v, s.field.format, get('labels', 'labelDisplayUnits', 0), get('labels', 'labelPrecision', null), max, ctx);
        const p1 = (s.v / (stages[0].v || 1) * 100).toFixed(1) + '%', pp = i ? (s.v / (stages[i - 1].v || 1) * 100).toFixed(1) + '%' : '100%';
        const shown = {Data: val, 'Percent of first': p1, 'Percent of previous': pp, 'Data, percent of first': `${val} (${p1})`, 'Data, percent of previous': `${val} (${pp})`}[style] || val;
        text(svg, left + pw / 2, y + band * 0.42, shown, {size: lSize, color: w > measure(shown, lSize) + 8 ? '#FFFFFF' : ctx.text, anchor: 'middle'});
      }
    });
    if (pctBar && stages.length) text(svg, left + pw / 2, H - 8, (stages[stages.length - 1].v / (stages[0].v || 1) * 100).toFixed(1) + '%', {size: 10, color: ctx.muted, anchor: 'middle'});
    return null;
  }

  // ------------------------------------------------------------------ scatter
  function scatter(svg, W, H, item, ctx, get) {
    const rows = item.rows, cat = fieldsOf(item, 'Category')[0], ser = fieldsOf(item, 'Series')[0];
    const xf = fieldsOf(item, 'X')[0], yf = fieldsOf(item, 'Y')[0], sf = fieldsOf(item, 'Size')[0];
    if (!xf || !yf) return note(svg, W, H, 'Needs measures on X and Y', ctx);
    const keyCol = cat ? cat.col : ser ? ser.col : null;
    const pts = (keyCol ? uniq(rows, keyCol) : [null]).map(k => {
      const sel = keyCol ? rows.filter(r => String(r[keyCol]) === String(k)) : rows;
      return {k, x: total(sel, xf.col), y: total(sel, yf.col), s: sf ? total(sel, sf.col) : null, ser: ser ? first(sel, ser.col) : null};
    }).filter(p => p.x !== null && p.y !== null);
    const sers = ser ? uniq(rows, ser.col) : [];
    const colorOf = p => ser ? ctx.palette[sers.findIndex(s => String(s) === String(p.ser)) % ctx.palette.length] : color(get('dataPoint', 'fill', get('dataPoint', 'defaultColor')), ctx, ctx.palette[0]);
    const space = legend(svg, W, sers.map((s, i) => ({name: catLabel(s, ser), color: ctx.palette[i % ctx.palette.length]})), get, ctx, {title: ser ? ser.name : null, height: H});
    // Power BI fits a scatter's axes to the data (with a margin) unless a start / end is set
    const span = (vals, lo, hi) => {
      const a = Math.min(...vals), b = Math.max(...vals), pad = (b - a || Math.abs(b) || 1) * 0.08;
      return [lo ?? (a >= 0 && a - pad < 0 ? 0 : a - pad), hi ?? b + pad];      // never below zero for all-positive data
    };
    const [x0, x1] = span(pts.map(p => p.x), get('categoryAxis', 'start'), get('categoryAxis', 'end')), [y0, y1] = span(pts.map(p => p.y), get('valueAxis', 'start'), get('valueAxis', 'end'));
    const tx = niceTicks(x0, x1, 5), ty = niceTicks(y0, y1, 5);
    const vSize = get('valueAxis', 'fontSize', 9) * PT;
    const yl = ty.map(v => num(v, yf.format, 0, tickPrec(ty, yf.format, 0), Math.max(...ty.map(Math.abs)), ctx));
    const xl = tx.map(v => num(v, xf.format, 0, tickPrec(tx, xf.format, 0), Math.max(...tx.map(Math.abs)), ctx));
    const left = space.left + Math.max(...yl.map(s => measure(s, vSize))) + 24, top = space.top + 8, bottom = space.bottom + vSize + 26, right = space.right + 12;
    const pw = W - left - right, ph = H - top - bottom;
    const sx = v => left + (v - tx[0]) / ((tx[tx.length - 1] - tx[0]) || 1) * pw, sy = v => top + ph - (v - ty[0]) / ((ty[ty.length - 1] - ty[0]) || 1) * ph;
    ty.forEach((v, i) => { el('line', {x1: left, x2: left + pw, y1: sy(v), y2: sy(v), stroke: mix(ctx.border, '#FFFFFF', 0.25)}, svg); text(svg, left - 6, sy(v), yl[i], {size: vSize, color: ctx.muted, anchor: 'end'}); });
    tx.forEach((v, i) => text(svg, sx(v), top + ph + vSize / 2 + 6, xl[i], {size: vSize, color: ctx.muted, anchor: 'middle'}));
    text(svg, left + pw / 2, H - space.bottom - 7, xf.name, {size: vSize, color: ctx.muted, anchor: 'middle'});
    text(svg, space.left + 8, top + ph / 2, yf.name, {size: vSize, color: ctx.muted, anchor: 'middle', rotate: -90});
    const smax = Math.max(...pts.map(p => Math.abs(p.s || 0)), 1), bubble = get('bubbles', 'bubbleSize', 0);
    const labels = get('categoryLabels', 'show', false);
    for (const p of pts.sort((a, b) => (b.s || 0) - (a.s || 0))) {
      const r = sf ? 4 + Math.sqrt(Math.abs(p.s || 0) / smax) * (18 + bubble / 4) : 5 + bubble / 10;
      const c = el('circle', {cx: sx(p.x), cy: sy(p.y), r, fill: colorOf(p), 'fill-opacity': get('fillPoint', 'style', 'Fill only') === 'Border only' ? 0 : 0.75, stroke: colorOf(p)}, svg);
      hover(c, () => [[cat ? cat.name : ser ? ser.name : 'Point', catLabel(p.k, cat || ser)], [xf.name, num(p.x, xf.format, 1, null, null, ctx)], [yf.name, num(p.y, yf.format, 1, null, null, ctx)]].concat(sf ? [[sf.name, num(p.s, sf.format, 1, null, null, ctx)]] : []));
      if (labels && cat) text(svg, sx(p.x) + r + 3, sy(p.y), fit(catLabel(p.k, cat), 90, 10), {size: 10, color: ctx.text});
    }
    if (fieldsOf(item, 'Play')[0]) text(svg, W - 6, H - 6, '▶ play axis animates in Power BI', {size: 9, color: ctx.muted, anchor: 'end', base: 'auto'});
    return null;
  }

  // ------------------------------------------------------------------ gauge
  function gauge(svg, W, H, item, ctx, get) {
    const rows = item.rows, y = fieldsOf(item, 'Y')[0];
    if (!y) return note(svg, W, H, 'Add a measure to Value', ctx);
    const val = total(rows, y.col) || 0, f = role => { const x = fieldsOf(item, role)[0]; return x ? total(rows, x.col) : null; };
    const min = get('axis', 'min', f('MinValue') ?? 0), max = get('axis', 'max', f('MaxValue') ?? (val > 0 ? val * 2 : 1)), target = get('axis', 'target', f('TargetValue'));
    const cx = W / 2, cy = H * 0.78, R = Math.max(10, Math.min(W / 2 - 20, H * 0.7)), inner = R * 0.62;
    const ang = v => Math.PI + Math.max(0, Math.min(1, (v - min) / ((max - min) || 1))) * Math.PI;
    const arc = (a0, a1, fill) => {
      const p = (r, a) => [cx + r * Math.cos(a), cy + r * Math.sin(a)];
      const [x0, y0] = p(R, a0), [x1, y1] = p(R, a1), [x2, y2] = p(inner, a1), [x3, y3] = p(inner, a0);
      return el('path', {d: `M${x0},${y0}A${R},${R} 0 0 1 ${x1},${y1}L${x2},${y2}A${inner},${inner} 0 0 0 ${x3},${y3}Z`, fill}, svg);
    };
    arc(Math.PI, 2 * Math.PI, color(get('dataPoint', 'target'), ctx, mix(ctx.border, '#FFFFFF', 0.2)));
    const fillArc = arc(Math.PI, ang(val), color(get('dataPoint', 'fill'), ctx, ctx.palette[0]));
    hover(fillArc, () => [[y.name, num(val, y.format, 1, null, null, ctx)]].concat(target !== null && target !== undefined ? [['Target', num(target, y.format, 1, null, null, ctx)]] : []));
    if (target !== null && target !== undefined) {
      const a = ang(target);
      el('line', {x1: cx + (inner - 4) * Math.cos(a), y1: cy + (inner - 4) * Math.sin(a), x2: cx + (R + 4) * Math.cos(a), y2: cy + (R + 4) * Math.sin(a), stroke: color(get('target', 'color'), ctx, ctx.text), 'stroke-width': 2}, svg);
      if (get('target', 'show', true)) text(svg, cx + (R + 8) * Math.cos(a), cy + (R + 8) * Math.sin(a) - 4, num(target, y.format, get('target', 'labelDisplayUnits', 0), get('target', 'labelPrecision', null), max, ctx), {size: 10, color: ctx.muted, anchor: a > 1.5 * Math.PI ? 'start' : 'end'});
    }
    if (get('calloutValue', 'show', true)) text(svg, cx, cy - inner * 0.25, num(val, y.format, get('calloutValue', 'labelDisplayUnits', 0), get('calloutValue', 'labelPrecision', null), max, ctx),
      {size: Math.min(28, R * 0.32), color: color(get('calloutValue', 'color'), ctx, ctx.text), anchor: 'middle', bold: get('calloutValue', 'bold', false)});
    if (get('labels', 'show', true)) {
      const ls = get('labels', 'fontSize', 9) * PT, lc = color(get('labels', 'color'), ctx, ctx.muted);
      text(svg, cx - (R + inner) / 2, cy + ls, num(min, y.format, get('labels', 'labelDisplayUnits', 0), null, max, ctx), {size: ls, color: lc, anchor: 'middle'});
      text(svg, cx + (R + inner) / 2, cy + ls, num(max, y.format, get('labels', 'labelDisplayUnits', 0), null, max, ctx), {size: ls, color: lc, anchor: 'middle'});
    }
    return null;
  }

  // ------------------------------------------------------------------ cards
  function cardVisual(svg, W, H, item, ctx, get) {
    const rows = item.rows, data = fieldsOf(item, 'Data'), refs = fieldsOf(item, 'ReferenceLabels');
    if (!data.length) return note(svg, W, H, 'Add measures to Data', ctx);
    const cols = Math.max(1, Math.min(get('layout', 'columnCount', data.length), data.length)), nrows = Math.ceil(data.length / cols);
    const cw = W / cols, ch = H / nrows;
    const accent = get('accentBar', 'show', false), accW = get('accentBar', 'width', 4), accPos = get('accentBar', 'position', 'Left');
    const accCol = color(get('accentBar', 'color'), ctx, ctx.palette[0]);
    const outline = get('outline', 'show', false);
    const vSize = get('value', 'fontSize', Math.min(27, ch / 3.2 / PT)) * PT, lSize = get('label', 'fontSize', 10) * PT;
    data.forEach((m, i) => {
      const x = (i % cols) * cw, y = Math.floor(i / cols) * ch, g = el('g', {transform: `translate(${x},${y})`}, svg);
      const bg = get('cardCalloutArea', 'backgroundFillColor');
      if (bg || data.length > 1) el('rect', {x: 3, y: 3, width: cw - 6, height: ch - 6, rx: get('cardCalloutArea', 'rectangleRoundedCurve', 6), fill: bg ? alpha(color(bg, ctx, ctx.card), get('cardCalloutArea', 'backgroundTransparency', 0)) : 'transparent', stroke: outline ? ctx.border : 'none'}, g);
      else if (outline) el('rect', {x: 1, y: 1, width: cw - 2, height: ch - 2, rx: 6, fill: 'none', stroke: ctx.border}, g);
      if (accent) {
        const r = {Left: [3, 3, accW, ch - 6], Right: [cw - 3 - accW, 3, accW, ch - 6], Top: [3, 3, cw - 6, accW], Bottom: [3, ch - 3 - accW, cw - 6, accW]}[accPos] || [3, 3, accW, ch - 6];
        el('rect', {x: r[0], y: r[1], width: r[2], height: r[3], fill: accCol}, g);
      }
      const align = get('value', 'horizontalAlignment', 'left'), ax = align === 'center' ? cw / 2 : align === 'right' ? cw - 14 : 14 + (accent && accPos === 'Left' ? accW : 0);
      const anchor = align === 'center' ? 'middle' : align === 'right' ? 'end' : 'start';
      const v = first(rows, m.col);
      const valueText = num(v, m.format, get('value', 'labelDisplayUnits', 0), get('value', 'labelPrecision', null), undefined, ctx);
      const vy = ch * (refs.length ? 0.36 : 0.44);
      const t = text(g, ax, vy, fit(valueText, cw - 20, vSize, 600), {size: vSize, color: color(get('value', 'fontColor'), ctx, ctx.text), anchor, bold: get('value', 'bold', true)});
      hover(t, () => [[m.name, num(v, m.format, 1, null, null, ctx)]]);
      if (get('label', 'show', true)) text(g, ax, vy + vSize * 0.72, fit(get('label', 'text', m.name), cw - 20, lSize), {size: lSize, color: color(get('label', 'fontColor'), ctx, ctx.muted), anchor});
      refs.forEach((r, k) => {
        const rv = first(rows, r.col), ry = vy + vSize * 0.72 + lSize * (1.6 + k * 1.3);
        if (ry > ch - 6) return;
        const title = get('referenceLabelTitle', 'titleText', r.name), rs = get('referenceLabelValue', 'valueFontSize', 9) * PT;
        text(g, ax, ry, fit(`${title}: ${num(rv, r.format, get('referenceLabelValue', 'valueDisplayUnits', 0), get('referenceLabelValue', 'valuePrecision', null), undefined, ctx)}`, cw - 20, rs),
          {size: rs, color: color(get('referenceLabelValue', 'valueFontColor'), ctx, ctx.muted), anchor});
      });
    });
    return null;
  }
  function card(svg, W, H, item, ctx, get) {
    const f = fieldsOf(item, 'Values')[0];
    if (!f) return note(svg, W, H, 'Add a field', ctx);
    const v = f.measure ? first(item.rows, f.col) : first(item.rows, f.col);
    const size = get('labels', 'fontSize', Math.min(27, H / 2.6 / PT)) * PT;
    const t = text(svg, W / 2, H * 0.45, fit(num(v, f.format, get('labels', 'labelDisplayUnits', 0), get('labels', 'labelPrecision', null), undefined, ctx), W - 10, size),
      {size, color: color(get('labels', 'color'), ctx, ctx.text), anchor: 'middle', bold: get('labels', 'bold', false)});
    hover(t, () => [[f.name, num(v, f.format, 1, null, null, ctx)]]);
    if (get('categoryLabels', 'show', true)) text(svg, W / 2, H * 0.45 + size * 0.75, fit(f.name, W - 10, get('categoryLabels', 'fontSize', 12) * PT * 0.8), {size: get('categoryLabels', 'fontSize', 12) * PT * 0.8, color: color(get('categoryLabels', 'color'), ctx, ctx.muted), anchor: 'middle'});
    return null;
  }
  function multiRowCard(svg, W, H, item, ctx, get) {
    const fs = fieldsOf(item, 'Values');
    if (!fs.length) return note(svg, W, H, 'Add fields', ctx);
    const cols = fs.filter(f => !f.measure), meas = fs.filter(f => f.measure);
    const rows = item.rows.slice(0, 30), rh = Math.max(44, Math.min(70, H / Math.max(1, rows.length)));
    const bar = get('card', 'barShow', true), barCol = color(get('card', 'barColor'), ctx, ctx.palette[0]);
    rows.forEach((r, i) => {
      const y = i * rh;
      if (y + rh > H + 1) return;
      if (bar) el('rect', {x: 0, y: y + 4, width: get('card', 'barWeight', 3), height: rh - 8, fill: barCol}, svg);
      const title = cols.map(c => catLabel(r[c.col], c)).join(' · ');
      if (title) text(svg, 12, y + 12, fit(title, W - 20, 12, 600), {size: get('cardTitle', 'fontSize', 9) * PT, color: color(get('cardTitle', 'color'), ctx, ctx.text), bold: true});
      const w = (W - 12) / Math.max(1, meas.length);
      meas.forEach((m, k) => {
        text(svg, 12 + k * w, y + rh * 0.55, fit(num(r[m.col], m.format, 0, null, undefined, ctx), w - 6, 15), {size: get('dataLabels', 'fontSize', 12) * PT, color: color(get('dataLabels', 'color'), ctx, ctx.text)});
        if (get('categoryLabels', 'show', true)) text(svg, 12 + k * w, y + rh * 0.8, fit(m.name, w - 6, 10), {size: get('categoryLabels', 'fontSize', 8) * PT, color: color(get('categoryLabels', 'color'), ctx, ctx.muted)});
      });
      el('line', {x1: 0, x2: W, y1: y + rh, y2: y + rh, stroke: mix(ctx.border, '#FFFFFF', 0.3)}, svg);
    });
    return null;
  }
  function kpi(svg, W, H, item, ctx, get) {
    const rows = item.rows, ind = fieldsOf(item, 'Indicator')[0], axis = fieldsOf(item, 'TrendLine')[0], goals = fieldsOf(item, 'Goal');
    if (!ind) return note(svg, W, H, 'Add a measure to Value', ctx);
    const xs = axis ? uniq(rows, axis.col) : [null];
    const series = xs.map(x => ({x, v: total(rows, ind.col, r => !axis || String(r[axis.col]) === String(x))})).filter(p => p.v !== null);
    const last = series[series.length - 1] || {v: total(rows, ind.col)};
    const goal = goals[0] ? total(rows.filter(r => !axis || String(r[axis.col]) === String(last.x)), goals[0].col) : null;
    const lowGood = String(get('goals', 'direction', get('status', 'direction', 'High is good'))).startsWith('Low') || get('status', 'direction', 'Positive') === 'Negative';
    const good = goal === null || (lowGood ? last.v <= goal : last.v >= goal);
    const col = goal === null ? color(get('status', 'neutralColor'), ctx, ctx.palette[0]) : good ? color(get('status', 'goodColor'), ctx, GOOD) : color(get('status', 'badColor'), ctx, BAD);
    if (get('trendline', 'show', true) && series.length > 1) {
      const lo = Math.min(...series.map(p => p.v)), hi = Math.max(...series.map(p => p.v));
      const pts = series.map((p, i) => ({x: i / (series.length - 1) * W, y: H - 6 - (p.v - lo) / ((hi - lo) || 1) * H * 0.42}));
      el('path', {d: linePath(pts) + `L${W},${H}L0,${H}Z`, fill: col, 'fill-opacity': 1 - get('trendline', 'transparency', 80) / 100}, svg);
    }
    const size = get('indicator', 'fontSize', Math.min(28, H / 3.4 / PT)) * PT;
    const icon = get('indicator', 'showIcon', true) && goal !== null ? (good ? '✓ ' : '! ') : '';
    const t = text(svg, W / 2, H * 0.32, fit(icon + num(last.v, ind.format, get('indicator', 'indicatorDisplayUnits', 0), get('indicator', 'indicatorPrecision', null), undefined, ctx), W - 10, size, 600),
      {size, color: color(get('indicator', 'fontColor'), ctx, goal === null ? ctx.text : col), anchor: 'middle', bold: true});
    hover(t, () => [[ind.name, num(last.v, ind.format, 1, null, null, ctx)]].concat(goal !== null ? [[goals[0].name, num(goal, goals[0].format, 1, null, null, ctx)]] : []));
    if (goal !== null && get('goals', 'showGoal', true)) {
      const dist = (last.v - goal) / (Math.abs(goal) || 1);
      const what = get('goals', 'distanceLabel', 'Percent');
      const d = what === 'Value' ? num(last.v - goal, ind.format, 0, null, undefined, ctx) : (dist >= 0 ? '+' : '') + (dist * 100).toFixed(get('goals', 'labelPrecision', 1)) + '%';
      text(svg, W / 2, H * 0.32 + size * 0.85, `${get('goals', 'goalText', 'Goal')}: ${num(goal, goals[0].format, 0, null, undefined, ctx)}` + (get('goals', 'showDistance', true) ? ` (${d})` : ''),
        {size: get('goals', 'fontSize', 9) * PT, color: color(get('goals', 'goalFontColor'), ctx, ctx.muted), anchor: 'middle'});
    }
    return null;
  }

  // ------------------------------------------------------------------ tables, matrix, slicer
  function htmlTable(body, item, ctx, get, head, rowsOut, totalsRow) {
    const wrap = document.createElement('div');
    wrap.style.cssText = 'position:absolute;inset:0;overflow:auto';
    const t = document.createElement('table');
    const fsz = get('values', 'fontSize', get('grid', 'textSize', 9)) * PT;
    t.style.cssText = `border-collapse:collapse;width:100%;font-size:${fsz}px;color:${color(get('values', 'fontColor'), ctx, ctx.text)}`;
    const hr = document.createElement('tr');
    head.forEach((h, i) => {
      const th = document.createElement('th');
      th.textContent = h.text; th.colSpan = h.span || 1;
      th.style.cssText = `position:sticky;top:${h.row ? 22 : 0}px;text-align:${h.num ? 'right' : get('columnHeaders', 'alignment', 'Auto') === 'Center' ? 'center' : 'left'};padding:4px 6px;`
        + `font-weight:${get('columnHeaders', 'bold', true) ? 600 : 400};color:${color(get('columnHeaders', 'fontColor'), ctx, ctx.muted)};`
        + `background:${color(get('columnHeaders', 'backColor'), ctx, ctx.card)};border-bottom:1px solid ${ctx.border};white-space:nowrap;font-size:${get('columnHeaders', 'fontSize', 9) * PT}px`;
      hr.appendChild(th);
    });
    t.appendChild(hr);
    const p1 = get('values', 'backColorPrimary'), p2 = get('values', 'backColorSecondary');
    const grid = get('grid', 'gridHorizontal', true), gcol = color(get('grid', 'gridHorizontalColor'), ctx, mix(ctx.border, '#FFFFFF', 0.4));
    const pad = get('grid', 'rowPadding', 3);
    rowsOut.forEach((r, i) => {
      const tr = document.createElement('tr');
      tr.style.background = i % 2 ? (p2 ? color(p2, ctx, '') : '') : (p1 ? color(p1, ctx, '') : '');
      r.forEach(c => {
        const td = document.createElement('td');
        td.textContent = c.text;
        td.style.cssText = `padding:${pad + 1}px 6px;text-align:${c.num ? 'right' : 'left'};white-space:nowrap;${grid ? 'border-bottom:1px solid ' + gcol : ''};${c.bold ? 'font-weight:600' : ''}`;
        if (c.color) td.style.color = c.color;
        if (c.bg) td.style.background = c.bg;
        tr.appendChild(td);
      });
      t.appendChild(tr);
    });
    if (totalsRow) {
      const tr = document.createElement('tr');
      totalsRow.forEach(c => { const td = document.createElement('td'); td.textContent = c.text; td.style.cssText = `padding:${pad + 1}px 6px;text-align:${c.num ? 'right' : 'left'};font-weight:600;border-top:1px solid ${ctx.border};background:${color(get('total', 'backColor'), ctx, 'transparent')}`; tr.appendChild(td); });
      t.appendChild(tr);
    }
    wrap.appendChild(t);
    body.appendChild(wrap);
  }
  const additive = f => !fmtParts(f.format).pct;
  function cellStyle(get, f, row, rows, ctx) {
    // conditional formatting on values: `for: "[Measure]"` entries with backColor / fontColor (gradient or field value)
    const out = {};
    for (const prop of ['backColor', 'fontColor']) {
      const spec = override(get, 'values', prop, {measure: f.name, values: []});
      if (spec !== undefined) out[prop === 'backColor' ? 'bg' : 'color'] = pointColor(spec, [row], ctx, null, colRanges(rows));
    }
    return out;
  }
  function table(body, item, ctx, get) {
    const fs = fieldsOf(item, 'Values'), rows = item.rows.slice(0, 500);
    const head = fs.map(f => ({text: f.name, num: f.measure}));
    const out = rows.map(r => fs.map(f => ({text: f.measure ? num(r[f.col], f.format, 1, null, null, ctx) : catLabel(r[f.col], f), num: f.measure, ...(f.measure ? cellStyle(get, f, r, rows, ctx) : {})})));
    const totals = get('total', 'totals', true) && fs.some(f => f.measure) ? fs.map((f, i) => ({text: i === 0 && !f.measure ? get('total', 'label', 'Total') : f.measure && additive(f) ? num(total(rows, f.col), f.format, 1, null, null, ctx) : '', num: f.measure})) : null;
    htmlTable(body, item, ctx, get, head, out, totals);
  }
  function matrix(body, item, ctx, get) {
    const rf = fieldsOf(item, 'Rows')[0], cf = fieldsOf(item, 'Columns')[0], vs = fieldsOf(item, 'Values'), rows = item.rows;
    const rkeys = rf ? uniq(rows, rf.col) : [null], ckeys = cf ? uniq(rows, cf.col) : [null];
    const rowTotal = get('rowTotal', 'show', get('subTotals', 'rowSubtotals', true)), colTotal = get('columnTotal', 'show', get('subTotals', 'columnSubtotals', true));
    const head = [{text: rf ? rf.name : ''}];
    ckeys.forEach(c => vs.forEach(v => head.push({text: (cf ? catLabel(c, cf) + (vs.length > 1 ? ' · ' : '') : '') + (vs.length > 1 || !cf ? v.name : ''), num: true})));
    if (cf && colTotal) vs.forEach(v => head.push({text: 'Total' + (vs.length > 1 ? ' · ' + v.name : ''), num: true}));
    const cell = (pred, v) => ({text: num(total(rows, v.col, pred), v.format, 1, null, null, ctx), num: true});
    const out = rkeys.map(rk => {
      const line = [{text: rf ? catLabel(rk, rf) : 'Total', bold: !rf}];
      ckeys.forEach(ck => vs.forEach(v => line.push({...cell(r => (!rf || String(r[rf.col]) === String(rk)) && (!cf || String(r[cf.col]) === String(ck)), v), ...cellStyle(get, v, Object.assign({}, ...rows.filter(r => (!rf || String(r[rf.col]) === String(rk)) && (!cf || String(r[cf.col]) === String(ck)))), rows, ctx)})));
      if (cf && colTotal) vs.forEach(v => line.push(additive(v) ? {...cell(r => !rf || String(r[rf.col]) === String(rk), v), bold: true} : {text: '', num: true}));
      return line;
    });
    const totals = rf && rowTotal ? [{text: 'Total'}].concat(...ckeys.map(ck => vs.map(v => additive(v) ? cell(r => !cf || String(r[cf.col]) === String(ck), v) : {text: '', num: true})),
      cf && colTotal ? vs.map(v => additive(v) ? cell(() => true, v) : {text: '', num: true}) : []) : null;
    htmlTable(body, item, ctx, get, head, out, totals);
  }
  function slicer(body, item, ctx, get) {
    const f = fieldsOf(item, 'Values')[0];
    if (!f) return;
    const values = uniq(item.rows, f.col).slice(0, 200);
    const mode = get('data', 'mode', 'VerticalList');
    const wrap = document.createElement('div');
    wrap.style.cssText = `position:absolute;inset:0;overflow:auto;font-size:${get('items', 'textSize', 10) * PT}px;color:${color(get('items', 'fontColor'), ctx, ctx.text)}`;
    if (get('header', 'show', true)) {
      const h = document.createElement('div');
      h.textContent = get('header', 'text', f.name);
      h.style.cssText = `font-weight:600;margin-bottom:6px;color:${color(get('header', 'fontColor'), ctx, ctx.text)};font-size:${get('header', 'textSize', 10) * PT}px`;
      wrap.appendChild(h);
    }
    if (mode === 'Dropdown') {
      const b = document.createElement('div');
      b.textContent = 'All';
      b.style.cssText = `border:1px solid ${ctx.border};border-radius:4px;padding:5px 8px;display:flex;justify-content:space-between`;
      const a = document.createElement('span'); a.textContent = '⌄'; b.appendChild(a);
      wrap.appendChild(b);
    } else if (mode === 'HorizontalList') {
      const row = document.createElement('div');
      row.style.cssText = 'display:flex;flex-wrap:wrap;gap:4px';
      values.forEach(v => { const t = document.createElement('span'); t.textContent = catLabel(v, f); t.style.cssText = `border:1px solid ${ctx.border};border-radius:4px;padding:4px 10px`; row.appendChild(t); });
      wrap.appendChild(row);
    } else if (mode === 'Between') {
      const t = document.createElement('div');
      t.textContent = `${catLabel(values[0], f)}  –  ${catLabel(values[values.length - 1], f)}`;
      t.style.cssText = `border:1px solid ${ctx.border};border-radius:4px;padding:5px 8px`;
      wrap.appendChild(t);
    } else {
      values.forEach(v => { const r = document.createElement('div'); r.style.cssText = 'display:flex;align-items:center;gap:6px;padding:2px 0'; const box = document.createElement('span'); box.style.cssText = `width:12px;height:12px;border:1px solid ${ctx.muted};border-radius:2px;flex:none`; const t = document.createElement('span'); t.textContent = catLabel(v, f); r.append(box, t); wrap.appendChild(r); });
    }
    body.appendChild(wrap);
  }

  // ------------------------------------------------------------------ maps and AI visuals: what the prototype can show
  function mapList(svg, W, H, item, ctx, get, filled) {
    const loc = fieldsOf(item, 'Category')[0], size = fieldsOf(item, 'Size')[0] || fieldsOf(item, 'Tooltips')[0];
    el('rect', {x: 0, y: 0, width: W, height: H, fill: '#EEF3F7', rx: 4}, svg);
    for (let i = 1; i < 8; i++) el('line', {x1: 0, x2: W, y1: H * i / 8, y2: H * i / 8, stroke: '#DCE6EE'}, svg);
    for (let i = 1; i < 12; i++) el('line', {x1: W * i / 12, x2: W * i / 12, y1: 0, y2: H, stroke: '#DCE6EE'}, svg);
    text(svg, 10, 14, filled ? 'Filled map — Power BI shades the regions (map tiles online)' : 'Map — Power BI places the bubbles (map tiles online)', {size: 10, color: ctx.muted});
    if (!loc) return null;
    const pts = uniq(item.rows, loc.col).map(k => ({k, v: size ? total(item.rows, size.col, r => String(r[loc.col]) === String(k)) : null}));
    pts.sort((a, b) => (b.v || 0) - (a.v || 0));
    const max = Math.max(...pts.map(p => Math.abs(p.v || 0)), 1);
    pts.slice(0, Math.floor((H - 30) / 18)).forEach((p, i) => {
      const y = 34 + i * 18, r = size ? 3 + Math.sqrt(Math.abs(p.v || 0) / max) * 6 : 4;
      el('circle', {cx: 20, cy: y, r, fill: ctx.palette[0], 'fill-opacity': 0.8}, svg);
      text(svg, 34, y, fit(catLabel(p.k, loc), W * 0.5, 11), {size: 11, color: ctx.text});
      if (size) text(svg, W - 10, y, num(p.v, size.format, 0, null, max, ctx), {size: 11, color: ctx.text, anchor: 'end'});
    });
    return null;
  }
  function decomposition(svg, W, H, item, ctx, get) {
    const m = fieldsOf(item, 'Analyze')[0], by = fieldsOf(item, 'ExplainBy')[0], rows = item.rows;
    if (!m) return note(svg, W, H, 'Add a measure to Analyze', ctx);
    const tot = total(rows, m.col) || 0, nodeW = Math.min(150, W * 0.3);
    el('rect', {x: 6, y: H / 2 - 22, width: nodeW, height: 44, rx: 4, fill: ctx.palette[0]}, svg);
    text(svg, 14, H / 2 - 8, fit(m.name, nodeW - 16, 10), {size: 10, color: '#FFFFFF'});
    text(svg, 14, H / 2 + 9, num(tot, m.format, 0, null, undefined, ctx), {size: 13, color: '#FFFFFF', bold: true});
    if (!by) return null;
    const kids = uniq(rows, by.col).map(k => ({k, v: total(rows, m.col, r => String(r[by.col]) === String(k)) || 0})).sort((a, b) => b.v - a.v).slice(0, Math.floor(H / 30));
    const max = Math.max(...kids.map(k => Math.abs(k.v)), 1), x0 = nodeW + 40, bw = W - x0 - 10;
    text(svg, x0, 10, by.name, {size: 10, color: ctx.muted, bold: true});
    kids.forEach((k, i) => {
      const y = 22 + i * ((H - 26) / kids.length), h = Math.min(22, (H - 26) / kids.length - 6);
      el('path', {d: `M${6 + nodeW},${H / 2}C${x0 - 20},${H / 2} ${x0 - 20},${y + h / 2} ${x0},${y + h / 2}`, fill: 'none', stroke: ctx.border}, svg);
      el('rect', {x: x0, y, width: Math.max(2, Math.abs(k.v) / max * bw * 0.6), height: h, fill: ctx.palette[0], 'fill-opacity': 0.75}, svg);
      text(svg, x0 + 4, y + h / 2, fit(`${catLabel(k.k, by)}  ${num(k.v, m.format, 0, null, max, ctx)}`, bw, 10), {size: 10, color: ctx.text});
    });
    return null;
  }
  function keyDrivers(svg, W, H, item, ctx) {
    const t = fieldsOf(item, 'Target')[0], ex = fieldsOf(item, 'ExplainBy');
    text(svg, 10, 14, 'Key influencers — Power BI runs the analysis on the model', {size: 11, color: ctx.muted});
    if (t) text(svg, 10, 40, `What influences ${t.name}`, {size: 13, color: ctx.text, bold: true});
    ex.forEach((e, i) => text(svg, 18, 66 + i * 18, '• ' + e.name, {size: 11, color: ctx.text}));
    return null;
  }

  // ------------------------------------------------------------------ entry
  const SVG = {
    bar: (s, W, H, it, c, g) => cartesian(s, W, H, it, c, g, {
      bars: /hundredPercent/.test(it.vt) ? 'percent' : /^clustered/.test(it.vt) ? 'clustered' : 'stacked',
      horizontal: /BarChart$|^barChart$/.test(it.vt), ribbon: it.vt === 'ribbonChart'}),
    line: (s, W, H, it, c, g) => cartesian(s, W, H, it, c, g, {
      lines: true, area: it.vt === 'areaChart' ? 'area' : it.vt === 'stackedAreaChart' ? 'stacked' : it.vt === 'hundredPercentStackedAreaChart' ? 'percent' : null}),
    combo: (s, W, H, it, c, g) => cartesian(s, W, H, it, c, g, {bars: /Clustered/.test(it.vt) ? 'clustered' : 'stacked', lines: true, combo: true}),
    waterfall, pie: (s, W, H, it, c, g) => pie(s, W, H, it, c, g, it.vt === 'donutChart'), treemap, funnel, scatter, gauge,
    cardVisual, card, multiRowCard, kpi, map: (s, W, H, it, c, g) => mapList(s, W, H, it, c, g, it.vt === 'filledMap'),
    decomposition, keyDrivers,
  };
  const HTML = {table, matrix, slicer};

  function render(box, v, ctx) {
    const item = v.stock;
    const {body, get, title} = frame(box, v, ctx);
    if (HTML[item.renderer]) { HTML[item.renderer](body, item, ctx, get); return; }
    const W = Math.max(20, body.clientWidth), H = Math.max(20, body.clientHeight);
    const svg = el('svg', {width: W, height: H, viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': title || item.vt, 'font-family': '"Segoe UI", system-ui, sans-serif'}, null);
    svg.style.display = 'block';
    svg.style.overflow = 'visible';
    body.appendChild(svg);
    const fn = SVG[item.renderer];
    if (!fn) { note(svg, W, H, item.vt + ' — drawn by Power BI', ctx); return; }
    if (!item.rows || !item.rows.length) { note(svg, W, H, 'No data', ctx); return; }
    fn(svg, W, H, item, ctx, get);
  }

  window.RelayStock = {render};
})();
