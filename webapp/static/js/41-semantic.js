/* ---------------- D2D Relay: a dashboard's semantic model (items 61-64, app/ontology.py): while Relay reads the data and
   on the plan screen, the tables with their columns, keys and business terms, the relationships as a diagram, the
   business terms found in several tables, how much of the data is read (a sample of big tables), and each column's
   term, which the person can change (and teach the ontology). Also each plan KPI's "change it in words" (item 63) and
   whether it is a KPI of the organisation's dictionary. ---------------- */
ICONS.model = ICONS.model || 'M4 5h6v5H4zM14 14h6v5h-6zM14 5h6v5h-6zM7 10v4h7M17 10v4';
ICONS.wand = ICONS.wand || 'M4 20 14 10M14 4v2M14 14v2M18 8h2M8 8H6M17 5l1-1M17 13l1 1M11 5l-1-1';
const SEM = {cache: {}};
const KIND_LABEL = {measure: 'measure', key: 'key', date: 'date', attribute: 'attribute'};
const fmtRows = n => n == null ? '-' : Number(n).toLocaleString();

/* the plan's relationships: "Sales[StoreKey] -> Store[StoreKey]" (or {from, to}) as {from, fromCol, to, toCol} */
function semRel(r) {
  if (r && typeof r === 'object' && r.from && r.to) r = `${r.from} -> ${r.to}`;
  const m = String(r || '').match(/^\s*'?([^'[\]]+?)'?\s*\[([^\]]+)\]\s*-+>\s*'?([^'[\]]+?)'?\s*\[([^\]]+)\]\s*$/);
  return m ? {from: m[1].trim(), fromCol: m[2].trim(), to: m[3].trim(), toCol: m[4].trim()} : null;
}

/* nodes and edges: the plan's model when there is one, else the files and the relationships found in them */
function semGraph(st, view) {
  const plan = st.plan || {}, model = plan.model || {};
  const files = Object.fromEntries((view.tables || []).map(t => [t.file, t]));
  if ((model.tables || []).length) {
    const nodes = model.tables.map(t => typeof t === 'string' ? {id: t, label: t} : {id: t.name, label: t.name, role: t.role, csv: t.csv, grain: t.grain});
    nodes.forEach(n => { const f = files[n.csv]; if (f) { n.rows = f.rows; n.sample_of = f.sample_of; } });
    const edges = (model.relationships || []).map(semRel).filter(e => e && nodes.some(n => n.id === e.from) && nodes.some(n => n.id === e.to));
    return {nodes, edges, planned: true};
  }
  const nodes = (view.tables || []).map(t => ({id: t.file, label: t.file.replace(/\.(csv|parquet|tsv)$/i, ''), csv: t.file, rows: t.rows, sample_of: t.sample_of}));
  const edges = (view.relationships || []).map(r => {
    const a = String(r.many).match(/^(.*)\[(.*)\]$/), b = String(r.one).match(/^(.*)\[(.*)\]$/);
    return a && b ? {from: a[1], fromCol: a[2], to: b[1], toCol: b[2], matched: r.matched, by: r.by} : null;
  }).filter(Boolean);
  const many = new Set(edges.map(e => e.from)), one = new Set(edges.map(e => e.to));
  nodes.forEach(n => { n.role = many.has(n.id) ? 'fact' : one.has(n.id) ? 'dimension' : ''; });
  return {nodes, edges, planned: false};
}

/* the diagram: facts in the middle, the tables they point to on either side; lines from the many side to the one side */
function semDiagram(g) {
  const NS = 'http://www.w3.org/2000/svg';
  const el = (tag, attrs, ...kids) => { const e = document.createElementNS(NS, tag); for (const [k, v] of Object.entries(attrs || {})) e.setAttribute(k, v); kids.forEach(k => e.append(k)); return e; };
  if (!g.nodes.length) return null;
  const isFact = n => /fact/i.test(n.role || '') || g.edges.some(e => e.from === n.id);
  const facts = g.nodes.filter(isFact), others = g.nodes.filter(n => !isFact(n));
  const W = 820, BW = 190, BH = 50, GAP = 22, cx = (W - BW) / 2;
  const left = [], right = [];
  // put each table on the side where its fact is; alternate to balance
  others.sort((a, b) => (/date/i.test(a.role || '') ? 1 : 0) - (/date/i.test(b.role || '') ? 1 : 0)).forEach((n, i) => (i % 2 ? right : left).push(n));
  const rowsN = Math.max(facts.length, left.length, right.length, 1);
  const H = rowsN * (BH + GAP) + 30;
  const pos = {};
  const place = (list, x) => { const top = (H - list.length * (BH + GAP) + GAP) / 2; list.forEach((n, i) => { pos[n.id] = {x, y: top + i * (BH + GAP)}; }); };
  if (facts.length) { place(facts, cx); place(left, 16); place(right, W - BW - 16); }
  else {                                      // nothing related: a grid
    const cols = 4, w = (W - 32 - (cols - 1) * 12) / cols;
    g.nodes.forEach((n, i) => { pos[n.id] = {x: 16 + (i % cols) * (w + 12), y: 15 + Math.floor(i / cols) * (BH + GAP), w}; });
  }
  const height = facts.length ? H : Math.ceil(g.nodes.length / 4) * (BH + GAP) + 30;
  const svg = el('svg', {viewBox: `0 0 ${W} ${height}`, class: 'semdia', role: 'img', 'aria-label': `Diagram of ${g.nodes.length} tables and ${g.edges.length} relationships`});
  for (const e of g.edges) {
    const a = pos[e.from], b = pos[e.to];
    if (!a || !b) continue;
    const aw = a.w || BW, bw = b.w || BW;
    const toRight = b.x > a.x;
    const x1 = toRight ? a.x + aw : a.x, y1 = a.y + BH / 2, x2 = toRight ? b.x : b.x + bw, y2 = b.y + BH / 2;
    const mx = (x1 + x2) / 2;
    svg.append(el('path', {d: `M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`, class: 'semline' + (e.by ? ' byterm' : '')}));
    svg.append(el('text', {x: x1 + (toRight ? 6 : -6), y: y1 - 5, class: 'semcard', 'text-anchor': toRight ? 'start' : 'end'}, '*'));
    svg.append(el('text', {x: x2 + (toRight ? -6 : 6), y: y2 - 5, class: 'semcard', 'text-anchor': toRight ? 'end' : 'start'}, '1'));
    const label = e.fromCol === e.toCol ? e.fromCol : `${e.fromCol} = ${e.toCol}`;
    const t = el('text', {x: mx, y: (y1 + y2) / 2 - 4, class: 'semkey', 'text-anchor': 'middle'}, label.length > 26 ? label.slice(0, 25) + '...' : label);
    t.append(el('title', {}, `${e.from}[${e.fromCol}] -> ${e.to}[${e.toCol}]` + (e.matched != null ? ` - ${Math.round(e.matched * 100)}% of values match` : '') + (e.by ? ` - found by ${e.by}` : '')));
    svg.append(t);
  }
  for (const n of g.nodes) {
    const p = pos[n.id];
    if (!p) continue;
    const w = p.w || BW, fact = isFact(n), date = /date/i.test(n.role || '');
    const box = el('g', {class: 'semnode' + (fact ? ' fact' : date ? ' date' : '')});
    box.append(el('rect', {x: p.x, y: p.y, width: w, height: BH, rx: 8}));
    const name = n.label.length > 24 ? n.label.slice(0, 23) + '...' : n.label;
    box.append(el('text', {x: p.x + 10, y: p.y + 20, class: 'semname'}, name));
    const sub = [fact ? 'fact' : date ? 'date' : (n.role || 'table'), n.sample_of ? `sample ${fmtRows(n.rows)} of ${fmtRows(n.sample_of)}` : n.rows != null ? `${fmtRows(n.rows)} rows` : ''].filter(Boolean).join(' - ');
    box.append(el('text', {x: p.x + 10, y: p.y + 38, class: 'semsub'}, sub));
    box.append(el('title', {}, [n.label, n.csv ? `from ${n.csv}` : '', n.grain ? `grain: ${n.grain}` : ''].filter(Boolean).join(' - ')));
    svg.append(box);
  }
  return h('div', {class: 'semdiawrap'}, svg);
}

/* how much of the data Relay reads (item 64) */
function dataSizeLine(size) {
  if (!size || !(size.files || []).length) return null;
  const sampled = size.sampled || {}, names = Object.keys(sampled);
  return h('div', {class: 'note' + (names.length ? ' warn' : ''), style: 'margin:8px 0 0'},
    h('b', {}, names.length ? 'Built on a sample. ' : 'All of your data is used. '),
    `${size.files.length} file${size.files.length === 1 ? '' : 's'}, ${fmtRows(size.total_rows)} rows` + (size.bytes ? `, ${sizeText(size.bytes)}` : '') + '. ',
    names.length ? names.map(n => `${n}: ${sampled[n].method === 'recent' ? 'the latest' : 'a random sample of'} ${fmtRows(sampled[n].rows)} of ${fmtRows(sampled[n].of)} rows`
      + ` (${(100 * sampled[n].rows / Math.max(1, sampled[n].of)).toFixed(1)}%)`).join('; ') + '. Every other table is used in full. '
      + 'The prototype and the Power BI file use the sample (totals are the sample\'s); Ask Relay answers from all rows. ' : '',
    h('span', {class: 'muted'}, 'Credits do not depend on how much data you have.'));
}
const sizeText = b => b >= 1073741824 ? `${(b / 1073741824).toFixed(1)} GB` : b >= 1048576 ? `${(b / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(b / 1024))} KB`;

/* the semantic model card: filled once /api/projects/<id>/semantic answers (cached per dashboard and plan round) */
function semanticCard(st) {
  const card = h('div', {class: 'card semcard-box', id: 'semcard'}, h('div', {class: 'row'}, h('h3', {style: 'margin:0'}, icon('model'), ' Semantic model'),
    h('span', {class: 'muted small'}, 'Reading your data...')));
  const key = [st.id, st.semantic_ready, st.plan_rounds, st.status].join('|');
  const fill = d => card.replaceChildren(...semanticBody(st, d).filter(Boolean));
  if (SEM.cache[key]) fill(SEM.cache[key]);
  else api(`/api/projects/${st.id}/semantic`).then(d => { SEM.cache = {[key]: d}; if (card.isConnected) fill(d); })
    .catch(e => card.replaceChildren(h('h3', {}, 'Semantic model'), h('div', {class: 'muted small'}, e.message)));
  return card;
}

function semanticBody(st, d) {
  const view = d.view;
  if (!view) return [h('h3', {}, icon('model'), ' Semantic model'), h('div', {class: 'muted small'}, 'It appears as soon as Relay has read your data.')];
  const g = semGraph(st, view), sem = view.semantic || {}, c = sem.counts || {};
  const changes = {};                    // file[column] -> term ('' = none), not saved yet
  const save = h('button', {class: 'btn sm primary', type: 'button', hidden: true}, icon('check'), 'Save the tags');
  const teach = h('input', {type: 'checkbox', checked: true});
  const teachLabel = d.may_teach ? h('label', {class: 'chk small', hidden: true}, teach, h('span', {}, 'Also teach the ontology, so these column names get these terms next time')) : null;
  const status = h('span', {class: 'small muted', role: 'status'});
  save.onclick = async () => {
    save.disabled = true; status.textContent = 'Saving...';
    try {
      const fresh = await api(`/api/projects/${st.id}/semantic`, {method: 'PUT', json: {overrides: changes}});
      if (d.may_teach && teach.checked) {
        for (const [ref, term] of Object.entries(changes)) {
          if (!term) continue;
          const col = ref.slice(ref.indexOf('[') + 1, -1);
          try { await api('/api/ontology/teach', {json: {term, synonym: col}}); } catch (e) { notify(`${col}: ${e.message}`, 'err'); }
        }
      }
      SEM.cache = {}; notify('Tags saved: Relay builds with them', 'ok');
      const box = $('#semcard'); if (box) box.replaceChildren(...semanticBody(st, fresh).filter(Boolean));
    } catch (e) { save.disabled = false; status.textContent = ''; notify(e.message, 'err'); }
  };
  const termOpts = (d.terms || []).slice().sort((a, b) => a.name.localeCompare(b.name));
  const picker = (ref, col) => {
    const sel = h('select', {class: 'sel semsel', 'aria-label': `Business term of ${ref}`},
      h('option', {value: ''}, '(no business term)'),
      termOpts.map(t => h('option', {value: t.name, selected: col.tag && col.tag.term === t.name}, `${t.name} (${KIND_LABEL[t.kind] || t.kind})`)));
    sel.onchange = () => { changes[ref] = sel.value; save.hidden = false; if (teachLabel) teachLabel.hidden = false; status.textContent = `${Object.keys(changes).length} change(s) not saved`; };
    return sel;
  };
  const chip = col => col.tag ? h('span', {class: 'semchip k-' + col.tag.kind, title: (col.tag.why || '') + (col.tag.variant ? ` - ${col.tag.variant}` : '')},
    col.tag.term, col.tag.variant ? h('small', {}, ` ${col.tag.variant}`) : null, col.tag.how === 'person' ? h('small', {}, ' (yours)') : null) : h('span', {class: 'faint small'}, '-');
  const tableBlock = t => {
    const node = g.nodes.find(n => n.csv === t.file);
    const tagged = t.columns.filter(x => x.tag).length;
    return h('details', {class: 'semtable'},
      h('summary', {}, h('b', {}, node && node.label !== t.file.replace(/\.(csv|parquet|tsv)$/i, '') ? `${node.label} ` : ''), h('span', {class: 'mono small'}, t.file),
        h('span', {class: 'muted small'}, ` - ${t.sample_of ? `sample of ${fmtRows(t.rows)} of ${fmtRows(t.sample_of)} rows` : `${fmtRows(t.rows)} rows`} - ${t.columns.length} columns, ${tagged} with a business term`)),
      h('div', {class: 'orgwrap'}, h('table', {class: 'utable semcols'},
        h('thead', {}, h('tr', {}, ['Column', 'Type', 'Business term', ''].map((x, i) => h('th', {class: i < 3 ? 'l' : null}, x)))),
        h('tbody', {}, t.columns.map(col => {
          const ref = `${t.file}[${col.name}]`;
          return h('tr', {}, h('td', {class: 'mono'}, col.name, col.unique ? h('span', {class: 'tag', style: 'margin-left:6px'}, 'unique') : null),
            h('td', {class: 'small'}, col.type), h('td', {}, d.may_tag ? picker(ref, col) : chip(col)),
            h('td', {class: 'small muted'}, col.tag && d.may_tag ? chip(col) : col.tag ? (col.tag.why || '') : ''));
        })))));
  };
  const callouts = [];
  for (const x of sem.combine || []) callouts.push(h('li', {}, h('b', {}, x.term), ` is in ${x.columns.length} columns (${x.columns.join(', ')}): one business number, so Relay combines them.`));
  for (const x of sem.related || []) callouts.push(h('li', {}, h('b', {}, x.family), `: ${x.columns.join(', ')} (${x.terms.join(', ')}): related, maybe one number under two names; Relay checks the values before combining.`));
  for (const x of sem.keys || []) callouts.push(h('li', {}, h('b', {}, x.entity), ` keys under different names: ${x.columns.join(', ')}: linked as one relationship.`));
  const dict = Object.keys(d.plan_dictionary || {}).length;
  return [
    h('div', {class: 'row', style: 'gap:8px;flex-wrap:wrap'}, h('h3', {style: 'margin:0'}, icon('model'), ' Semantic model'),
      h('span', {class: 'tag acc'}, `${c.tagged || 0} of ${c.columns || 0} columns matched`), d.industry ? h('span', {class: 'tag'}, d.industry) : h('span', {class: 'tag'}, 'General business terms'),
      dict ? h('span', {class: 'tag ok'}, `${dict} KPI${dict === 1 ? '' : 's'} from your dictionary`) : null,
      h('span', {class: 'spacer'}), h('a', {class: 'small', href: '#/ontology'}, 'Your ontology')),
    h('div', {class: 'muted small', style: 'margin-top:4px'}, g.planned ? 'The tables and relationships Relay planned, from your data. ' : 'What Relay found in your data so far; the plan follows. ',
      'Each column\'s business term comes from your ontology', d.may_tag ? ': change one if it is wrong, and Relay builds with yours.' : '.'),
    ((st.plan || {}).model || {}).note ? h('div', {class: 'muted small', style: 'margin-top:6px'}, st.plan.model.note) : null,   // item 58: a hand-off's note
    dataSizeLine(d.data_size),
    semDiagram(g),
    g.edges.length ? null : h('div', {class: 'muted small'}, 'No relationships found yet.'),
    callouts.length ? h('ul', {class: 'semcallouts small'}, callouts) : null,
    h('div', {class: 'semtables'}, (view.tables || []).map(tableBlock)),
    (view.unreadable || []).length ? h('div', {class: 'note err'}, 'Files that could not be read: ' + view.unreadable.join('; ')) : null,
    d.may_tag ? h('div', {class: 'row', style: 'gap:10px;margin-top:10px;flex-wrap:wrap'}, save, teachLabel, status) : null];
}

/* item 63: under a plan KPI: whether it is a dictionary KPI, and "change it in words" (1 credit) */
function kpiWords(st, card, i) {
  if (i < 0) return null;                                      // a KPI added here: edit it by hand, it is not in the plan yet
  const dictName = () => ((S.semPlanDict || {})[($('.k-name', card) || {}).value] || (st.plan_dictionary || {})[(S.planKpis[i] || {}).name]);
  const badge = h('span', {class: 'kpidict'});
  // item 73: a KPI the analyst review found different from the dictionary says so (approved under Review and approve)
  const differs = () => { const nm = (($('.k-name', card) || {}).value || '').toLowerCase();
    return (st.approval_items || []).some(x => x.kind === 'deviation' && x.text.toLowerCase().startsWith(nm + ':')); };
  const showBadge = () => { const n = dictName(); badge.replaceChildren(differs() ? h('span', {class: 'tag warn', title: 'See Review and approve'}, 'Differs from your KPI dictionary')
    : n ? h('span', {class: 'tag ok', title: 'Its name and meaning come from your KPI dictionary'}, icon('check'), ` From your KPI dictionary: ${n}`)
    : h('span', {class: 'tag', title: 'Not in your KPI dictionary'}, 'New KPI')); };
  showBadge();
  const cost = costOf('kpi') || 1;
  const words = h('input', {type: 'text', class: 'kw-in', maxlength: 600, placeholder: 'Change it in words, e.g. "exclude returns" or "make it weekly"', 'aria-label': 'Change this KPI in words'});
  const go = h('button', {class: 'btn sm', type: 'button', title: `Relay rewrites this KPI as you say: ${cost} credit${cost === 1 ? '' : 's'}`}, icon('wand'), 'Change', h('span', {class: 'cost'}, ` - ${cost} credit${cost === 1 ? '' : 's'}`));
  const fix = h('button', {class: 'btn sm ghost', type: 'button', title: `Relay makes the DAX valid and doing what the description says: ${cost} credit${cost === 1 ? '' : 's'}`}, 'Fix it');
  const out = h('div', {class: 'small muted kw-out', role: 'status'});
  const send = async text => {
    const t = (text || '').trim();
    if (!t) { words.focus(); return toast(go, 'Say what to change.'); }
    go.disabled = fix.disabled = words.disabled = true; out.textContent = 'Relay is rewriting this KPI...';
    const current = {name: $('.k-name', card).value, label: $('.k-label', card).value, format: $('.k-format', card).value,
      description: $('.k-desc', card).value, dax: $('.k-dax', card).value};
    try {
      const r = await api(`/api/projects/${st.id}/kpis/change`, {json: {index: i, instruction: t, current}});
      const k = r.kpi;
      $('.k-name', card).value = k.name; $('.k-label', card).value = k.label; $('.k-format', card).value = k.format;
      $('.k-desc', card).value = k.description; $('.k-dax', card).value = k.dax;
      S.planKpis[i] = k; card.classList.add('kw-done'); setTimeout(() => card.classList.remove('kw-done'), 1600);
      out.textContent = r.changed + ` (${cost} credit${cost === 1 ? '' : 's'})`; words.value = '';
      try { const sd = await api(`/api/projects/${st.id}/semantic`); S.semPlanDict = sd.plan_dictionary || {}; } catch (e) { /* the badge keeps its last state */ }
      showBadge(); refreshOrg(true);
    } catch (e) { out.textContent = ''; toast(go, e.message); }
    go.disabled = fix.disabled = words.disabled = false;
  };
  go.onclick = () => send(words.value);
  fix.onclick = () => send('Fix it: make the DAX valid and computing exactly what the description says.');
  words.onkeydown = e => { if (e.key === 'Enter') { e.preventDefault(); send(words.value); } };
  return h('div', {class: 'kw'}, badge, words, go, fix, out);
}
