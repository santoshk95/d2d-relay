/* The prototype page. genbi_kit/prototype.py writes R (the report's data) before this script: the pages and their
   visuals, the slicers and the results of every visual for the slicer selections it computed.

   R.slicers[i] = {label, values (labels), d (the default: value indexes), single (Single select: always exactly one
   value), ctrl (Multi-select with CTRL), mode, page (null: a report filter, synced on every page), note (why the
   prototype cannot filter by it), more (only the first values are listed)}.
   A visual with q (the slicers that can change it) has k0, its key at the default selection (drawn from its own data),
   and k: key -> index into R.pool (-1: the same as its own data). A key lists, per slicer in q, the selected value
   indexes ("*" for none: All). b: report filters whose default its prototype SQL writes itself, so it cannot follow
   them. Globals R, current and draw() are what the Display check uses (genbi_kit/display.py). */
let current = 0;
const SEL = R.slicers.map(s => s.d.slice());
let pop = null;                       // the open slicer list: {i, el, msg}

// Table cells use the measure's format string, like the visuals do ("\\$#,0", "0.0%", "+0.0%;-0.0%;0.0%").
// Commas right after the last digit divide by 1,000 each: \\$#,0.0,,"M" shows millions.
function fmtNum(v, f) {
  if (typeof v !== 'number') return v ?? '';
  if (!isFinite(v)) return '';
  if (!f) return v.toLocaleString('en-US', {maximumFractionDigits: 2});
  const sec = f.split(';')[0].trim(), lits = sec.match(/"[^"]*"/g) || [];
  const suffix = lits.length && sec.endsWith(lits[lits.length - 1]) ? lits[lits.length - 1].slice(1, -1) : '';
  const core = sec.replace(/"[^"]*"/g, '').split(String.fromCharCode(92)).join('');
  const cur = (core.match(/[$€£¥₹]/) || [''])[0], pct = core.includes('%'), dm = core.match(/[.](0+)/);
  const sm = core.replace(/[$€£¥₹% ]/g, '').match(/[0#](?:[.][0#]+)?(,+)$/), scale = sm ? Math.pow(1000, sm[1].length) : 1;
  const d = dm ? dm[1].length : 0, signed = f.includes(';') && sec.startsWith('+');
  const s = v < 0 ? '-' : (signed && v > 0 ? '+' : '');
  return s + cur + (Math.abs(pct ? v * 100 : v) / scale).toLocaleString('en-US', {minimumFractionDigits: d, maximumFractionDigits: d}) + (pct ? '%' : '') + suffix;
}

function el(tag, cls, parent, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined && text !== null) e.textContent = text;
  if (parent) parent.appendChild(e);
  return e;
}

// ------------------------------------------------------------------ selections
const same = (a, b) => a.length === b.length && a.every((x, k) => x === b[k]);
const keyOf = (v, sel) => v.q.map(i => sel[i].length ? sel[i].join(',') : '*').join('|');
const onPage = s => s.page === null || s.page === current;

// What to draw for a visual at a selection: its own data, a computed result, or nothing computed for it.
function resultOf(v, sel) {
  if (!v.q || !v.q.length) return {own: true};
  const key = keyOf(v, sel);
  if (key === v.k0) return {own: true};
  const p = v.k ? v.k[key] : undefined;
  if (p === undefined) return {missing: true};
  return p < 0 ? {own: true} : {entry: R.pool[p]};
}
function reachable(sel) {             // every visual on this page has data for this selection
  return R.pages[current].visuals.every(v => !resultOf(v, sel).missing);
}
function withSel(i, next) { const s = SEL.slice(); s[i] = next; return s; }

// The selection a click gives (Power BI's rules): Single select keeps exactly one value; otherwise a click picks one
// value (or clears it when it is the only one) and Ctrl+click adds or removes a value (any click, without "Multi-select
// with CTRL").
function nextSel(i, idx, add) {
  const s = R.slicers[i], cur = SEL[i];
  if (s.single) return [idx];
  if (add || !s.ctrl) return cur.includes(idx) ? cur.filter(x => x !== idx) : [...cur, idx].sort((a, b) => a - b);
  return cur.length === 1 && cur[0] === idx ? [] : [idx];
}
function setSel(i, next) {
  if (same(next, SEL[i])) return true;
  if (!reachable(withSel(i, next))) return false;
  SEL[i] = next;
  draw();
  return true;
}
function selText(i) {
  const s = R.slicers[i], sel = SEL[i];
  if (!sel.length) return 'All';
  return sel.length === 1 ? s.values[sel[0]] : 'Multiple selections';
}
const canClear = i => !R.slicers[i].single && SEL[i].length > 0 && reachable(withSel(i, []));
function resetAll() {
  R.slicers.forEach((s, i) => { SEL[i] = s.d.slice(); });
  closePop();
  draw();
}

// ------------------------------------------------------------------ a visual for the current selection
function shown(v) {
  const r = resultOf(v, SEL);
  if (r.own) return v;
  const out = Object.assign({}, v, {header: Object.assign({}, v.header || {})});
  delete out.error;
  if (r.missing) {
    out.missing = true;
    if (v.tt !== undefined) out.header.title = v.tt;
    return out;
  }
  const e = r.entry;
  out.header.title = e.t != null ? e.t : (v.tt !== undefined ? v.tt : out.header.title);
  if (e.e) { out.error = e.e; return out; }
  if (e.n) { out.nodata = true; return out; }
  if (e.m) out.model = e.m;
  if (e.d) out.atlas = Object.assign({}, v.atlas, {dv: unpackDv(v, e.d)});
  if (e.r) out.stock = Object.assign({}, v.stock, {rows: e.r.v.map(row => Object.fromEntries(e.r.c.map((c, k) => [c, row[k]])))});
  if (e.s) out.stock = e.s;
  return out;
}
function unpackDv(v, d) {             // the default's column sources with this selection's values
  if (d.f) return d.f;
  const base = v.atlas.dv, out = {categories: d.c.map((vals, k) => ({source: base.categories[k].source, values: vals}))};
  if (d.g) {
    const tmpl = base.groups[0].values.map(c => c.source);
    out.groups = d.g.map(([name, cols]) => ({name, values: cols.map((vals, k) => ({source: Object.assign({}, tmpl[k], {groupName: name}), values: vals}))}));
    out.groupSource = base.groupSource;
  } else out.values = d.v.map((vals, k) => ({source: base.values[k].source, values: vals}));
  return out;
}
// A Relay visual's model with nothing to draw (its renderer would ask for fields instead).
function emptyModel(type, m) {
  if (!m) return true;
  const none = xs => !xs || !xs.length || xs.every(x => x === null || x === undefined);
  switch (type) {
    case 'kpiCard': return m.value === null || m.value === undefined;
    case 'trendLine': return !m.categories.length || none(m.actual);
    case 'driverBars': return none((m.rows || []).map(r => r.value));
    case 'quadrant': return !(m.points || []).some(p => p.x !== null && p.y !== null);
    case 'treemap': return none((m.items || []).map(r => r.size));
    case 'heatmap': return !(m.values || []).some(r => r.some(x => x !== null && x !== undefined));
    case 'funnel': return none((m.stages || []).map(r => r.value));
    case 'narrative': return !(m.items || []).some(x => String(x).trim());
    case 'table': return !(m.rows || []).length;
    default: return false;
  }
}
// A card with the visual's title and a short message in the middle: "No data", or why it shows nothing.
function notice(box, v, head, text) {
  const card = el('div', 'notice', box);
  const title = (v.header && v.header.title) || (v.model && (v.model.label || v.model.heading)) || '';
  if (title) el('h4', '', card, title);
  if (v.header && v.header.subtitle) el('small', '', card, v.header.subtitle);
  const body = el('div', 'nb', card);
  el(text ? 'b' : 'span', '', body, head);
  if (text) el('span', '', body, text);
}
// Report filters this visual's SQL fixes, when they are not at that value: a note on its top edge, over the page (a
// visual may redraw its own box when it resizes).
function badges(v) {
  const moved = (v.b || []).filter(i => !same(SEL[i], R.slicers[i].d));
  if (!moved.length) return;
  const at = el('div', 'vb', document.getElementById('page'));
  Object.assign(at.style, {left: v.x + 'px', top: v.y + 'px', width: v.w + 'px'});
  const b = el('div', 'vbadge', at, moved.map(i => R.slicers[i].label + ': ' + R.slicers[i].d.map(k => R.slicers[i].values[k]).join(', ') + ' only').join('; '));
  b.title = 'The prototype SQL of this visual writes this value itself, so it does not follow the slicer here. '
    + 'Power BI filters it like the other visuals.';
}

function drawVisual(box, v0) {
  const v = shown(v0);
  if (v.missing) {
    notice(box, v, 'Not computed for this selection', 'The prototype computes a limited number of slicer combinations: clear a slicer to see it.');
  } else if (v.error) {
    box.innerHTML = '<div class="err"><b></b><div></div></div>';
    box.querySelector('b').textContent = (v.header && v.header.title) || v.id;
    box.querySelector('div div').textContent = /^Prototype query failed/.test(v.error) ? v.error : 'Prototype query failed: ' + v.error;
  } else if (v.atlas && (v.nodata || !v.atlas.dv)) {
    // Visual Atlas: Power BI's themed container (title, subtitle); no rows for this selection
    const card = el('div', 'acard', box);
    if (v.header && v.header.title) el('h4', '', card, v.header.title);
    if (v.header && v.header.subtitle) el('small', '', card, v.header.subtitle);
    const body = el('div', 'abody', card);
    body.style.cssText = 'display:flex;align-items:center;justify-content:center;font-size:12px;color:' + (R.stock.muted || '#6F6761');
    body.textContent = 'No data';
  } else if (v.atlas) {
    // Visual Atlas: Power BI's themed container (title, subtitle) around the visual's own packaged code
    const card = el('div', 'acard', box);
    if (v.header && v.header.title) el('h4', '', card, v.header.title);
    if (v.header && v.header.subtitle) el('small', '', card, v.header.subtitle);
    const body = el('div', 'abody', card);
    try { GenBIAtlas.render(body, v.atlas, R.atlas); }
    catch (e) { body.className += ' aerr'; body.textContent = 'Could not draw this visual: ' + e.message; }
  } else if (v.stock || (v.nodata && v0.stock)) {
    // Power BI's own visual: drawn with Power BI's layout and its Format-pane settings ("No data" when no rows)
    const item = v.nodata ? Object.assign({}, v.stock || v0.stock, {rows: []}) : v.stock;
    try { RelayStock.render(box, Object.assign({}, v, {stock: item}), Object.assign({fmtNum}, R.stock)); }
    catch (e) { box.innerHTML = '<div class="err"><b></b><div></div></div>'; box.querySelector('b').textContent = (v.header && v.header.title) || v.id;
      box.querySelector('div div').textContent = 'Could not draw this visual: ' + e.message; }
  } else if (v.nodata || (v.model && emptyModel(v.type, v.model))) {
    notice(box, v, 'No data', null);
  } else if (v.type === 'table') {
    const m = v.model, t = el('div', 'tbl', box);
    t.innerHTML = '<h4></h4><table><thead><tr></tr></thead><tbody></tbody></table>';
    t.querySelector('h4').textContent = (v.header && v.header.title) || '';
    m.columns.forEach(c => { const th = document.createElement('th'); th.textContent = c; t.querySelector('tr').appendChild(th); });
    m.rows.forEach(r => { const tr = document.createElement('tr');
      r.forEach((c, i) => { const td = document.createElement('td'); td.textContent = fmtNum(c, (m.formats || [])[i]); if (typeof c === 'number') td.className = 'n'; tr.appendChild(td); });
      t.querySelector('tbody').appendChild(tr); });
  } else if (v.model) {
    GenBIVisuals.render(v.type, box, v.model, v.header || {}, R.tokens);
  }
}

// ------------------------------------------------------------------ slicers
function slicerApi(i) {
  const s = R.slicers[i];
  return {
    values: s.values, sel: SEL[i].slice(), single: s.single, ctrl: s.ctrl, note: s.note, more: s.more, text: selText(i),
    enabled: idx => reachable(withSel(i, nextSel(i, idx, false))) || (!s.single && s.ctrl && reachable(withSel(i, nextSel(i, idx, true)))),
    pick: (idx, ev) => { if (!setSel(i, nextSel(i, idx, !!(ev && (ev.ctrlKey || ev.metaKey))))) flash(i); },
    canClear: () => canClear(i), clear: () => setSel(i, []), open: anchor => togglePop(i, anchor),
  };
}
function flash(i) {                   // a click that would reach a selection the prototype did not compute
  if (pop && pop.i === i) { pop.msg = 'This combination was not computed for the prototype.'; fillPop(); }
}
// A report filter: Power BI's dropdown slicer (label, the selection, a list that opens below it).
function slicerBox(box, v) {
  const i = v.si, s = R.slicers[i];
  const wrap = el('div', 'slc', box), head = el('div', 'slc-head', wrap);
  el('small', '', head, v.label || (s && s.label) || '');
  if (!s) {
    const b = el('button', 'slc-box', wrap); b.disabled = true; el('span', 'slc-val', b, v.default ?? 'All');
    return;
  }
  if (canClear(i)) {
    const c = el('button', 'slc-clear', head, 'Clear');
    c.type = 'button'; c.title = 'Clear the selection';
    c.onclick = e => { e.stopPropagation(); setSel(i, []); };
  }
  const b = el('button', 'slc-box', wrap);
  b.type = 'button'; b.dataset.si = i;
  b.setAttribute('aria-haspopup', 'listbox'); b.setAttribute('aria-expanded', pop && pop.i === i ? 'true' : 'false');
  el('span', 'slc-val', b, selText(i));
  el('span', 'slc-chev', b);
  if (s.note) { b.disabled = true; b.title = s.note; return; }
  b.onclick = e => { e.stopPropagation(); togglePop(i, b); };
}
function togglePop(i, anchor) {
  if (pop && pop.i === i) { closePop(); return; }
  closePop();
  pop = {i, el: el('div', 'slc-pop', document.body), msg: null};
  pop.el.setAttribute('role', 'listbox');
  pop.el.addEventListener('mousedown', e => e.stopPropagation());
  pop.el.addEventListener('keydown', popKeys);
  if (anchor) anchor.setAttribute('aria-expanded', 'true');
  fillPop();
  placePop();
  const first = pop.el.querySelector('.sl-item.on') || pop.el.querySelector('.sl-item:not(.off)');
  if (first) first.focus();
}
function closePop() {
  if (!pop) return;
  pop.el.remove();
  const a = document.querySelector(`[data-si="${pop.i}"]`);
  if (a) a.setAttribute('aria-expanded', 'false');
  pop = null;
}
function placePop() {
  if (!pop) return;
  const a = document.querySelector(`[data-si="${pop.i}"]`);
  if (!a) { closePop(); return; }
  const r = a.getBoundingClientRect();
  pop.el.style.minWidth = Math.max(180, r.width) + 'px';
  const w = pop.el.offsetWidth, h = pop.el.offsetHeight, room = document.documentElement.clientWidth;
  pop.el.style.left = (window.scrollX + Math.max(4, r.left + w > room - 4 ? r.right - w : r.left)) + 'px';   // right-aligned at the edge
  // below the slicer; above it when the page ends first (the app sizes its frame to the page, not to the list)
  const bottom = document.getElementById('page').getBoundingClientRect().bottom;
  const up = r.bottom + 4 + h > bottom && r.top - 4 - h >= 0;
  pop.el.style.top = (window.scrollY + (up ? r.top - 4 - h : r.bottom + 4)) + 'px';
}
function fillPop() {
  const i = pop.i, s = R.slicers[i], box = pop.el, api = slicerApi(i);
  const act = document.activeElement, focusIdx = act && box.contains(act) && act.dataset ? act.dataset.idx : undefined;
  box.replaceChildren();
  if (!s.single && s.ctrl) el('div', 'pop-hint', box, 'Ctrl+click to select more than one');
  s.values.forEach((label, idx) => {
    const on = SEL[i].includes(idx), ok = on || api.enabled(idx);
    const it = el('div', 'sl-item' + (s.single ? ' radio' : '') + (on ? ' on' : '') + (ok ? '' : ' off'), box);
    it.setAttribute('role', 'option'); it.setAttribute('aria-selected', on ? 'true' : 'false'); it.tabIndex = -1;
    it.dataset.idx = idx;
    el('span', 'sl-mk', it);
    el('span', '', it, label);
    if (!ok) { it.setAttribute('aria-disabled', 'true'); it.title = 'Not computed for the prototype with your other selections'; }
    it.onclick = e => { pop.msg = null; api.pick(idx, e); };
  });
  if (s.more) el('div', 'pop-note', box, 'The prototype lists the first ' + s.values.length + ' values.');
  if (pop.msg) el('div', 'pop-note warn', box, pop.msg);
  if (R.budget && R.budget.cut && s.values.some((_, idx) => !SEL[i].includes(idx) && !api.enabled(idx))) {
    el('div', 'pop-note', box, 'Greyed values combine with your other selections in Power BI; the prototype computed a limited number of combinations.');
  }
  if (canClear(i)) {
    const f = el('div', 'pop-foot', box), c = el('button', '', f, 'Clear selection');
    c.type = 'button';
    c.onclick = () => { pop.msg = null; setSel(i, []); };
  }
  if (focusIdx !== undefined) { const f = box.querySelector(`.sl-item[data-idx="${focusIdx}"]`); if (f) f.focus(); }
}
function popKeys(e) {
  const items = [...pop.el.querySelectorAll('.sl-item')], at = items.indexOf(document.activeElement);
  if (e.key === 'Escape') { const i = pop.i; closePop(); const a = document.querySelector(`[data-si="${i}"]`); if (a) a.focus(); e.preventDefault(); }
  else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
    const next = items[Math.max(0, Math.min(items.length - 1, at + (e.key === 'ArrowDown' ? 1 : -1)))];
    if (next) next.focus();
    e.preventDefault();
  } else if ((e.key === 'Enter' || e.key === ' ') && at >= 0) {
    items[at].click();
    e.preventDefault();
  }
}
document.addEventListener('mousedown', e => {
  if (pop && !pop.el.contains(e.target) && !(e.target.closest && e.target.closest(`[data-si="${pop.i}"]`))) closePop();
});
window.addEventListener('resize', placePop);

// ------------------------------------------------------------------ the page
function nav(box) {
  const n = el('div', 'nav', box);
  R.pages.forEach((p, i) => {
    const s = el('span', i === current ? 'on' : '', n, p.name);
    s.setAttribute('role', 'tab'); s.tabIndex = 0;
    s.onclick = () => { current = i; closePop(); draw(); window.scrollTo(0, 0); };
    s.onkeydown = e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); s.onclick(); } };
  });
}
function foot() {
  const f = document.getElementById('foot');
  if (!f) return;
  f.replaceChildren();
  const moved = R.slicers.map((s, i) => i).filter(i => onPage(R.slicers[i]) && !same(SEL[i], R.slicers[i].d));
  if (moved.length) {
    const said = i => { const sel = SEL[i]; return !sel.length ? 'All' : sel.length <= 3 ? sel.map(k => R.slicers[i].values[k]).join(', ') : sel.length + ' values'; };
    el('span', '', f, 'Filtered: ' + moved.map(i => R.slicers[i].label + ' ' + said(i)).join('; '));
    const b = el('button', '', f, 'Reset to default');
    b.type = 'button';
    b.onclick = resetAll;
  }
  if (R.budget && R.budget.cut) {
    el('span', '', f, 'The prototype computed ' + R.budget.states + ' slicer selections, up to its ' + (R.budget.cut === 'size' ? 'size' : 'time')
      + ' limit: a greyed value in a slicer was not computed with your other selections (Power BI filters any combination).');
  }
}
function draw() {
  const page = R.pages[current], root = document.getElementById('page');
  root.innerHTML = ''; root.style.height = page.height + 'px';
  for (const v of page.visuals) {
    const box = document.createElement('div'); box.className = 'v';
    Object.assign(box.style, {left: v.x + 'px', top: v.y + 'px', width: v.w + 'px', height: v.h + 'px'});
    root.appendChild(box);
    if (v.type === 'pageNavigator') nav(box);
    else if (v.type === 'slicer') slicerBox(box, v);
    else if (v.type === 'textbox') {
      (v.paragraphs || []).forEach(rs => { const p = document.createElement('div');
        p.textContent = (rs || []).map(r => (r && r.text != null) ? r.text : '').join(''); box.appendChild(p); });
    } else if (v.si !== undefined) {
      // a page's own slicer (pbi.slicer): Power BI's slicer in its style (list, tiles or dropdown)
      const item = v.stock || {vt: 'slicer', renderer: 'slicer', fields: {}, rows: [], format: {}};
      try { RelayStock.render(box, Object.assign({}, v, {stock: item}), Object.assign({fmtNum, slicer: slicerApi(v.si)}, R.stock)); }
      catch (e) { box.textContent = 'Could not draw this slicer: ' + e.message; }
      const a = box.querySelector('[data-slicer-open]');
      if (a) a.dataset.si = v.si;
    } else drawVisual(box, v);
  }
  page.visuals.forEach(badges);
  if (pop) {
    if (!document.querySelector(`[data-si="${pop.i}"]`) || !onPage(R.slicers[pop.i])) closePop();
    else { fillPop(); placePop(); const a = document.querySelector(`[data-si="${pop.i}"]`); a.setAttribute('aria-expanded', 'true'); }
  }
  foot();
}
draw();
