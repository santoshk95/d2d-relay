/* ---------------- D2D Relay: the ontology (item 61, app/ontology.py): the organisation's business vocabulary, which every
   dashboard's planning reads. Industry packs to start from, its business terms (what columns mean, with the names they
   go by), its KPI dictionary (the same one Semantic Review checks models against), and "try a column name".
   #/ontology          industry packs and what the ontology holds
   #/ontology/terms    business terms: add, edit, remove, import, try column names
   #/ontology/kpis     the KPI dictionary (40-review.js renderKpiDictionary), with "change it in words" ---------------- */
ICONS.layers = ICONS.layers || 'M12 3 2 8l10 5 10-5-10-5zM2 13l10 5 10-5M2 18l10 5 10-5';
const ONTO = {q: ''};

function ontoTabs(on) {
  const t = (href, label, id) => h('a', {href, class: on === id ? 'on' : ''}, label);
  return h('nav', {class: 'ontotabs', 'aria-label': 'Ontology'}, t('#/ontology', 'Industry', 'home'), t('#/ontology/terms', 'Business terms', 'terms'),
    t('#/ontology/kpis', 'KPI dictionary', 'kpis'));
}
function ontoHead(on, d) {
  return [h('div', {class: 'phead'}, h('div', {style: 'flex:1;min-width:0'}, h('div', {class: 'eyebrow'}, 'Your organisation'), h('h1', {}, 'Ontology'),
    h('div', {class: 'meta'}, 'Your business vocabulary: what your columns mean and how your KPIs are defined. Relay reads every new dashboard\'s data with it, '
      + 'and Semantic Review checks your Power BI models against its KPIs.')),
    d ? h('a', {class: 'btn ghost', href: '/api/ontology/export.yaml'}, icon('download'), 'Download') : null), ontoTabs(on)];
}

function renderOntology() {
  const sub = (location.hash.match(/^#\/ontology\/?([a-z]*)/) || [])[1] || '';
  if (sub === 'kpis') return renderKpiDictionary(true);
  if (sub === 'terms') return renderOntologyTerms();
  return renderOntologyHome();
}

async function renderOntologyHome() {
  document.title = 'Ontology - D2D Relay';
  const page = h('div', {class: 'page wide'});
  $('#main').replaceChildren(page);
  let d;
  try { d = await api('/api/ontology'); } catch (e) { return page.append(h('div', {class: 'note err'}, e.message)); }
  if (!location.hash.startsWith('#/ontology')) return;
  const applied = new Set((d.industry || {}).packs || []);
  const packCard = p => h('div', {class: 'pack' + (applied.has(p.id) ? ' on' : '')},
    h('div', {class: 'row', style: 'gap:6px'}, h('b', {}, p.name), applied.has(p.id) ? h('span', {class: 'tag ok'}, 'In use') : null),
    h('div', {class: 'pd'}, p.description),
    h('div', {class: 'small muted'}, `${p.terms} business terms - ${p.kpis} KPIs`),
    h('div', {class: 'row', style: 'gap:6px;flex-wrap:wrap'},
      h('button', {class: 'btn sm ghost', type: 'button', onclick: () => packPreview(p, d)}, 'Look inside'),
      d.may_edit ? h('button', {class: 'btn sm' + (applied.size ? '' : ' primary'), type: 'button', onclick: () => applyPack(p, d)}, icon('plus'), applied.has(p.id) ? 'Add again' : 'Use it') : null));
  const ind = d.industry || {};
  page.append(...ontoHead('home', d),
    h('div', {class: 'orggrid'},
      h('div', {class: 'card'}, h('h3', {}, 'What your ontology holds'),
        h('dl', {class: 'kv small'},
          h('dt', {}, 'Industry'), h('dd', {}, ind.name || h('span', {class: 'muted'}, 'not chosen yet')),
          h('dt', {}, 'Business terms'), h('dd', {}, d.using_default ? `none of your own yet: columns are read with ${d.default_terms} general business terms` : `${d.terms.length}`),
          h('dt', {}, 'KPIs'), h('dd', {}, `${d.kpis} in your KPI dictionary`),
          ind.applied ? [h('dt', {}, 'Last pack added'), h('dd', {}, `${when(ind.applied)}${ind.by ? ' by ' + ind.by : ''}`)] : null),
        (d.conflicts || []).length ? h('div', {class: 'note warn'}, h('b', {}, 'Two terms share a name: '), d.conflicts.slice(0, 4).join('; ')) : null,
        h('div', {class: 'row', style: 'gap:8px;flex-wrap:wrap;margin-top:10px'},
          h('a', {class: 'btn', href: '#/ontology/terms'}, 'Business terms'), h('a', {class: 'btn', href: '#/ontology/kpis'}, 'KPI dictionary'))),
      h('div', {class: 'card'}, h('h3', {}, 'How Relay uses it'),
        h('ul', {class: 'small', style: 'margin:0;padding-left:18px;line-height:1.6'},
          h('li', {}, 'Reading new data: each column gets its business term (sls_amt, net_sls and SalesAmount are all Sales), and the same term in several tables is combined.'),
          h('li', {}, 'Planning: KPIs come from your dictionary with your names and definitions; you can change any of them in words.'),
          h('li', {}, 'Semantic Review: your Power BI models are checked against the same KPIs: one KPI, one meaning, one value.'),
          h('li', {}, 'You teach it: when you correct a column\'s term on a plan, Relay can remember that name for next time.')),
        d.may_edit ? null : h('div', {class: 'note', style: 'margin-bottom:0'}, 'Your account can read the ontology. An owner or a BI Dev of your organisation changes it.'))),
    h('div', {class: 'card'}, h('h3', {}, 'Industry packs'),
      h('p', {class: 'small muted', style: 'margin-top:-4px'}, 'Starting points: an industry\'s business terms and its usual KPIs, with definitions. Using a pack adds what you do not have yet; '
        + 'what you already have stays as it is. Then change anything to fit how your organisation works.'),
      h('div', {class: 'packgrid'}, d.packs.map(packCard))));
}

async function packPreview(p, d) {
  let full;
  try { full = await api(`/api/ontology/packs/${encodeURIComponent(p.id)}`); } catch (e) { return notify(e.message, 'err'); }
  const m = modal(p.name, h('div', {class: 'mbody'},
    h('p', {class: 'small muted', style: 'margin-top:0'}, p.description),
    h('h4', {}, `KPIs (${full.kpis.length})`),
    h('div', {class: 'orgwrap', style: 'max-height:260px;overflow:auto'}, h('table', {class: 'utable'}, h('tbody', {}, full.kpis.map(k => h('tr', {},
      h('td', {}, h('b', {}, k.name), (k.synonyms || []).length ? h('div', {class: 'small muted'}, k.synonyms.slice(0, 4).join(', ')) : null),
      h('td', {class: 'small'}, k.definition || '', k.dax ? h('div', {class: 'mono faint'}, k.dax) : null)))))),
    h('h4', {}, `Business terms (${full.terms.length})`),
    h('div', {class: 'small', style: 'max-height:200px;overflow:auto;line-height:1.7'}, full.terms.map((t, i) => [i ? ', ' : '', h('span', {title: (t.synonyms || []).join(', ')}, t.name)])),
    full.questions.length ? [h('h4', {}, 'Questions it is made for'), h('ul', {class: 'small'}, full.questions.map(q => h('li', {}, q)))] : null,
    h('div', {class: 'row', style: 'justify-content:flex-end;gap:8px;margin-top:12px'},
      d.may_edit ? h('button', {class: 'btn primary', type: 'button', onclick: () => { m.remove(); applyPack(p, d); }}, 'Use it') : null,
      h('button', {class: 'btn', type: 'button', onclick: () => m.remove()}, 'Close'))), true);
}

function applyPack(p, d) {
  const replace = h('input', {type: 'checkbox'});
  const out = h('div', {role: 'status'});
  const ok = h('button', {class: 'btn primary', type: 'button'}, icon('plus'), `Use ${p.name}`);
  const m = modal(`Use ${p.name}`, h('div', {class: 'mbody'},
    h('p', {style: 'margin-top:0'}, `Adds ${p.name}'s ${p.terms} business terms and ${p.kpis} KPIs to your ontology. Terms and KPIs you already have stay as they are; `
      + 'a KPI whose name belongs to one of yours is left out (one name stands for one KPI).'),
    h('label', {class: 'chk'}, replace, h('span', {}, 'Where the names are the same, use the pack\'s version instead of mine')), out,
    h('div', {class: 'row', style: 'justify-content:flex-end;margin-top:12px'}, ok)));
  ok.onclick = async () => {
    ok.disabled = true;
    try {
      const r = await api('/api/ontology/industry', {json: {pack: p.id, replace: replace.checked}});
      const a = r.applied, n = x => `${x.added} added` + (x.replaced ? `, ${x.replaced} replaced` : '') + (x.kept ? `, ${x.kept} kept` : '') + (x.skipped ? `, ${x.skipped} left out` : '');
      m.remove(); notify(`${a.pack}: terms ${n(a.terms)}; KPIs ${n(a.kpis)}`, 'ok'); renderOntologyHome();
    } catch (e) { ok.disabled = false; out.replaceChildren(h('div', {class: 'note err'}, e.message)); }
  };
}

async function renderOntologyTerms() {
  document.title = 'Business terms - D2D Relay';
  const page = h('div', {class: 'page wide'});
  $('#main').replaceChildren(page);
  let d;
  try { d = await api('/api/ontology'); } catch (e) { return page.append(h('div', {class: 'note err'}, e.message)); }
  if (!location.hash.startsWith('#/ontology/terms')) return;
  const search = h('input', {type: 'search', placeholder: 'Find a term or a column name', value: ONTO.q, 'aria-label': 'Find a business term', class: 'srsearch'});
  const body = h('tbody');
  const draw = () => {
    const q = search.value.trim().toLowerCase(); ONTO.q = q;
    const rows = d.terms.filter(t => !q || [t.name, t.entity, t.kind, ...(t.synonyms || []), t.description].join(' ').toLowerCase().includes(q));
    body.replaceChildren(...(rows.length ? rows.map(t => h('tr', {class: 'termrow'},
      h('td', {}, h('b', {}, t.name), t.entity ? h('div', {class: 'small muted'}, t.entity) : null),
      h('td', {class: 'small'}, h('span', {class: 'semchip k-' + t.kind}, t.kind), t.family ? h('div', {class: 'muted', style: 'margin-top:3px'}, `family: ${t.family}`) : null),
      h('td', {class: 'small'}, [t.unit, t.aggregation && t.aggregation.replace('_', ' ')].filter(Boolean).join(', ') || '-'),
      h('td', {}, h('div', {class: 'syn'}, (t.synonyms || []).map(s => h('span', {}, s)))),
      h('td', {class: 'small muted'}, t.description || ''),
      h('td', {class: 'l', style: 'white-space:nowrap'}, d.may_edit ? [
        h('button', {class: 'btn sm', type: 'button', onclick: () => termDialog(t, d)}, icon('edit'), 'Edit'),
        h('button', {class: 'btn sm ghost danger', type: 'button', 'aria-label': `Remove ${t.name}`, onclick: async () => {
          if (!await confirmBox(`Remove ${t.name}?`, 'Columns with its names are no longer tagged with it in new plans. KPIs are not changed.', 'Remove')) return;
          try { await api(`/api/ontology/terms/${t.id}`, {method: 'DELETE'}); renderOntologyTerms(); } catch (e) { notify(e.message, 'err'); }
        }}, icon('x'))] : null)))
      : [h('tr', {}, h('td', {colspan: 6, class: 'muted', style: 'text-align:center;padding:24px'},
          d.terms.length ? 'No term matches.' : d.using_default ? 'None of your own yet: new data is read with the general business terms. Use an industry pack, or add terms.' : 'No terms yet.'))]));
  };
  search.oninput = draw;
  // try column names against the ontology
  const tryIn = h('input', {type: 'text', placeholder: 'Column names, e.g. sls_amt, str_nbr, cic, NetSalesAmt, fiscal_wk', 'aria-label': 'Column names to try'});
  const tryOut = h('div', {class: 'tryres'});
  const tryGo = h('button', {class: 'btn', type: 'button'}, 'Try');
  tryGo.onclick = async () => {
    const cols = tryIn.value.split(/[,\n]+/).map(x => x.trim()).filter(Boolean).slice(0, 50);
    if (!cols.length) return tryIn.focus();
    const guess = n => /(^|_)(dt|date|day)($|_)/i.test(n) ? 'date' : /(amt|amount|sales|sls|qty|units|count|cost|price|margin|pct|value|rate)/i.test(n) ? 'decimal' : 'string';
    try {
      const r = await api('/api/ontology/match', {json: {columns: cols.map(n => ({name: n, type: guess(n)}))}});
      tryOut.replaceChildren(...r.columns.map(c => h('div', {class: 'small'}, h('span', {class: 'mono'}, c.name), ' -> ',
        c.tag ? [h('span', {class: 'semchip k-' + c.tag.kind}, c.tag.term), c.tag.variant ? h('span', {class: 'muted'}, ` (${c.tag.variant})`) : null, h('span', {class: 'muted'}, ` - ${c.tag.why}`)]
          : h('span', {class: 'muted'}, 'no business term: add the name to a term\'s other names'))));
    } catch (e) { tryOut.replaceChildren(h('div', {class: 'note err'}, e.message)); }
  };
  tryIn.onkeydown = e => { if (e.key === 'Enter') { e.preventDefault(); tryGo.click(); } };
  page.append(...ontoHead('terms', d),
    h('div', {class: 'card'}, h('h3', {}, 'Try column names'),
      h('p', {class: 'small muted', style: 'margin-top:-4px'}, 'How Relay would read columns with these names (the type is guessed from the name here; on a plan it is the data\'s).'),
      h('div', {class: 'trybox'}, tryIn, tryGo), tryOut),
    h('div', {class: 'row', style: 'gap:8px;flex-wrap:wrap;margin:6px 0 12px;align-items:center'},
      d.may_edit ? h('button', {class: 'btn primary', type: 'button', onclick: () => termDialog(null, d)}, icon('plus'), 'Add a term') : null,
      d.may_edit ? h('button', {class: 'btn', type: 'button', onclick: () => termImport()}, icon('publish'), 'Import YAML') : null,
      h('span', {class: 'grow'}), search),
    h('div', {class: 'card orgwrap', style: 'padding:6px 10px'}, h('table', {class: 'utable'},
      h('thead', {}, h('tr', {}, ['Term', 'Kind', 'Unit', 'Other names in columns', 'Meaning', ''].map(x => h('th', {class: 'l'}, x)))), body)));
  draw();
}

function termDialog(t, d) {
  t = t || {kind: 'measure'};
  const f = (label, el, hint) => [h('label', {class: 'f'}, label), el, hint ? h('div', {class: 'hint'}, hint) : null];
  const name = h('input', {type: 'text', value: t.name || '', maxlength: 80, placeholder: 'For example: Net Sales'});
  const opts = (list, cur, none) => [none ? h('option', {value: ''}, none) : null, ...list.map(v => h('option', {value: v, selected: v === cur}, v.replace('_', ' ')))];
  const kind = h('select', {class: 'sel'}, opts(d.kinds, t.kind));
  const entity = h('input', {type: 'text', value: t.entity || '', maxlength: 80, placeholder: 'For example: Store, Product, Customer'});
  const unit = h('select', {class: 'sel'}, opts(d.units, t.unit, 'Not set'));
  const agg = h('select', {class: 'sel'}, opts(d.aggregations, t.aggregation, 'Not set'));
  const family = h('input', {type: 'text', value: t.family || '', maxlength: 80, placeholder: 'Optional: e.g. Sales, for Net Sales and Digital Sales'});
  const syn = h('textarea', {rows: 3, placeholder: 'Column names it goes by, separated by commas: sls, sales_amt, net_sls'}, (t.synonyms || []).join(', '));
  const desc = h('input', {type: 'text', value: t.description || '', maxlength: 400});
  const out = h('div', {role: 'status'});
  const save = h('button', {class: 'btn primary', type: 'button'}, t.id ? 'Save' : 'Add');
  save.onclick = async () => {
    save.disabled = true;
    const body = {name: name.value, kind: kind.value, entity: entity.value || null, unit: unit.value || null, aggregation: agg.value || null,
      family: family.value || null, synonyms: syn.value, description: desc.value || null};
    try { await api(t.id ? `/api/ontology/terms/${t.id}` : '/api/ontology/terms', {method: t.id ? 'PUT' : 'POST', json: body}); m.remove(); notify(t.id ? 'Saved' : 'Added', 'ok'); renderOntologyTerms(); }
    catch (e) { save.disabled = false; out.replaceChildren(h('div', {class: 'note err'}, e.message)); }
  };
  const m = modal(t.id ? `Edit ${t.name}` : 'Add a business term', h('div', {class: 'mbody'},
    f('Business term', name, 'The name Relay gives a column with this meaning in your Power BI model.'),
    h('div', {class: 'grid2'}, h('div', {}, f('Kind', kind)), h('div', {}, f('What it belongs to', entity))),
    h('div', {class: 'hint'}, 'Measure: a number to add up or average. Key: identifies a store, item, customer... Date: a day, week or period. Attribute: a name or category.'),
    h('div', {class: 'grid2'}, h('div', {}, f('Unit', unit)), h('div', {}, f('How it adds up', agg))),
    f('Other names in columns', syn, 'snake_case, camelCase and spaces read alike, and amt, qty, nbr, sls and other usual abbreviations are understood.'),
    f('Family', family), f('Meaning', desc), out,
    h('div', {class: 'row', style: 'justify-content:flex-end;margin-top:12px'}, save)));
  name.focus();
}

function termImport() {
  const file = h('input', {type: 'file', accept: '.yaml,.yml,.json'});
  const replace = h('input', {type: 'checkbox'});
  const out = h('div', {role: 'status'});
  const ok = h('button', {class: 'btn primary', type: 'button'}, 'Import');
  ok.onclick = async () => {
    if (!file.files[0]) return out.replaceChildren(h('div', {class: 'note warn'}, 'Choose a file first.'));
    const fd = new FormData(); fd.append('file', file.files[0]); fd.append('replace', replace.checked ? '1' : '0');
    ok.disabled = true;
    try { const r = await upload('/api/ontology/import', fd); const n = r.imported; m.remove();
      notify(`Business terms: ${n.added} added, ${n.replaced} replaced, ${n.kept} kept` + (n.skipped ? `, ${n.skipped} left out` : ''), 'ok'); renderOntologyTerms(); }
    catch (e) { ok.disabled = false; out.replaceChildren(h('div', {class: 'note err'}, e.message)); }
  };
  const m = modal('Import business terms', h('div', {class: 'mbody'},
    h('p', {style: 'margin-top:0'}, 'A YAML or JSON file with a list of terms (name, kind, entity, unit, aggregation, synonyms, description), like the file Download gives. '
      + 'KPIs are imported in the KPI dictionary.'),
    h('label', {class: 'f'}, 'File'), file, h('label', {class: 'chk', style: 'margin-top:8px'}, replace, h('span', {}, 'Where the names are the same, use the file\'s version')),
    out, h('div', {class: 'row', style: 'justify-content:flex-end;margin-top:12px'}, ok)));
}

/* item 63: a dictionary KPI changed in words (1 credit) */
function kpiWordsDialog(k, after) {
  const cost = costOf('kpi') || 1;
  const words = h('textarea', {rows: 3, placeholder: 'For example: "exclude returns and use the fiscal year ending in February", or "add Comp Sales as another name"'});
  const out = h('div', {role: 'status'});
  const ok = h('button', {class: 'btn primary', type: 'button'}, icon('wand'), 'Change', h('span', {class: 'cost'}, ` - ${cost} credit${cost === 1 ? '' : 's'}`));
  ok.onclick = async () => {
    if (!words.value.trim()) return words.focus();
    ok.disabled = true; out.replaceChildren(h('div', {class: 'muted small'}, 'Relay is rewriting the KPI...'));
    try { const r = await api(`/api/semreview/kpis/${k.id}/change`, {json: {instruction: words.value}}); m.remove(); notify(r.changed, 'ok'); refreshOrg(true); after(); }
    catch (e) { ok.disabled = false; out.replaceChildren(h('div', {class: 'note err'}, e.message)); }
  };
  const m = modal(`Change ${k.name} in words`, h('div', {class: 'mbody'},
    h('p', {class: 'small muted', style: 'margin-top:0'}, `Say what should change: Relay rewrites this KPI's definition, formula, DAX, other names or rules, and checks the result before saving. ${cost} credit${cost === 1 ? '' : 's'}, given back if no change comes of it.`),
    words, out, h('div', {class: 'row', style: 'justify-content:flex-end;margin-top:12px'}, ok)));
  words.focus();
}
