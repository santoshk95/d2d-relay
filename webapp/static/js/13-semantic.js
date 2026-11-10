/* ---------------- semantic layer (phase 4): metrics, ontology, terms, context, reviews ---------------- */
const MSTATUS = {published: ['Published', 'ok'], review: ['In review', 'warn'], draft: ['Draft', ''], rejected: ['Rejected', 'err'], superseded: ['Older version', '']};
const mPill = s => { const [t, k] = MSTATUS[s] || [s, '']; return h('span', {class: 'tag ' + k}, t); };
const SEM_TABS = [['metrics', 'Metrics'], ['ontology', 'Ontology'], ['terms', 'Business terms'], ['context', 'Context'], ['reviews', 'Reviews']];

/* project page: certified badges, promote */
function certBadge(st, name) {
  const c = (st.certification || {})[name];
  if (!c) return h('span', {class: 'faint small'}, '—');
  const update = h('button', {class: 'btn sm', onclick: async () => { try { await api(`/api/projects/${st.id}/certify`, {json: {measure: name}}); notify('Change request queued', 'ok'); poll(); } catch (e) { notify(e.message, 'err'); } }}, 'Update');
  if (c.status === 'certified') return h('span', {class: 'tag ok', title: `Matches the team's published definition v${c.version}`}, icon('check'), `Certified v${c.version}`);
  return h('span', {class: 'row', style: 'gap:6px'}, h('span', {class: 'tag ' + (c.status === 'outdated' ? 'warn' : 'err'),
    title: c.status === 'outdated' ? `Uses v${c.was_version}; v${c.version} is published` : `Differs from the certified definition: ${c.dax}`},
    c.status === 'outdated' ? `v${c.was_version} · v${c.version} published` : `Differs from certified v${c.version}`), st.access && st.access.can_edit ? update : null);
}
function certSummary(st) {
  const c = Object.values(st.certification || {});
  if (!c.length) return null;
  const ok = c.filter(x => x.status === 'certified').length;
  return h('span', {class: 'tag ' + (ok === c.length ? 'ok' : 'warn'), style: 'align-self:center', title: 'Measures that match the team\'s published metrics'},
    icon('check'), `${ok}/${c.length} certified`);
}
function teamMetricsCard(st, kpis) {   // not kpiCard: 06-project.js has the plan's kpiCard (one global scope)
  const pick = new Set();
  const can = st.access && st.access.can_edit;
  const send = h('button', {class: 'btn sm', disabled: true, onclick: async () => {
    try { const r = await api(`/api/projects/${st.id}/promote`, {json: {names: [...pick]}}); notify(`${r.metrics.length} sent for review as team metrics`, 'ok'); }
    catch (e) { notify(e.message, 'err'); } }}, 'Send to team metrics for review');
  return h('div', {class: 'card'}, h('div', {class: 'row'}, h('h3', {style: 'margin:0'}, 'KPIs ', h('span', {class: 'muted'}, `(${kpis.length}) — as confirmed`)),
      h('span', {class: 'spacer'}), can ? send : null),
    h('table', {class: 'ktable'}, h('tr', {}, [can ? '' : null, 'KPI', 'Meaning', 'DAX', 'Format', 'Team metric'].filter(x => x !== null).map(c => h('th', {}, c))),
      kpis.map(k => h('tr', {}, can ? h('td', {}, h('input', {type: 'checkbox', title: 'Send to team metrics', onchange: e => { e.target.checked ? pick.add(k.name) : pick.delete(k.name); send.disabled = !pick.size; }})) : null,
        h('td', {}, h('b', {}, k.label || k.name), h('div', {class: 'faint small mono'}, k.name)),
        h('td', {class: 'small'}, k.description || ''), h('td', {class: 'dax'}, k.dax || ''), h('td', {class: 'mono'}, k.format || ''), h('td', {}, certBadge(st, k.name))))),
    can ? h('div', {class: 'hint'}, 'Tick KPIs and send them to the team\'s metrics: another BI Dev / Analyst reviews them, and once published every dashboard of the team (and Ask D) uses the same definition.') : null);
}

/* the page */
async function renderSemantic() {
  const tab = (location.hash.split('/')[2] || 'metrics').split('?')[0];
  const body = h('div', {}, skel('rows'));
  $('#main').replaceChildren(h('div', {class: 'page wide'},
    h('div', {class: 'phead'}, h('div', {}, h('h1', {}, 'Metrics & ontology'),
      h('div', {class: 'meta'}, 'The semantic layer: what your data means — shared by every dashboard and every Ask D answer.'))),
    h('div', {class: 'opts', style: 'grid-template-columns:repeat(3,1fr);margin-bottom:16px'},
      [['context', '1 · Context', 'Automatic, from the data: tables, columns, keys, joins, examples.'],
       ['metrics', '2 · Team metrics', 'Reviewed definitions in DAX and SQL — certified once published.'],
       ['ontology', '3 · Organisation ontology', 'Shared entities, relationships and how each source identifies them.']].map(([id, t, d]) =>
        h('a', {href: '#/metrics/' + id, class: 'card flat', style: 'margin:0;text-decoration:none;color:inherit;' + (tab === id ? 'border-color:var(--accent);background:var(--accent-tint)' : '')},
          h('b', {}, t), h('div', {class: 'small muted'}, d)))),
    h('div', {class: 'tabs'}, SEM_TABS.map(([id, l]) => h('a', {href: '#/metrics/' + id, class: id === tab ? 'on' : ''}, l))), body));
  try {
    const view = await ({metrics: semMetrics, ontology: semOntology, terms: semTerms, context: semContext, reviews: semReviews}[tab] || semMetrics)();
    if (location.hash.startsWith('#/metrics')) body.replaceChildren(view);
  } catch (e) { body.replaceChildren(h('div', {class: 'note err'}, e.message)); }
}
const reSem = () => renderSemantic();

function sqlTabs(by) {
  const keys = Object.keys(by || {}).filter(k => by[k]);
  if (!keys.length) return h('div', {class: 'muted small'}, 'No SQL yet — add it so Ask D can answer with this metric on live data.');
  const pre = h('pre', {class: 'mono small', style: 'background:var(--surface-2);padding:8px;border-radius:8px;white-space:pre-wrap'}, by[keys[0]]);
  const bar = h('div', {class: 'segbtn'}, keys.map((k, i) => h('button', {class: i ? '' : 'on', onclick: e => { pre.textContent = by[k];
    bar.querySelectorAll('button').forEach(b => b.classList.toggle('on', b === e.target)); }}, k)));
  return h('div', {}, bar, pre);
}

async function semMetrics() {
  const d = await api('/api/semantic/metrics');
  let sel = d.metrics[0] && d.metrics[0].id;
  const list = h('div', {class: 'vlist'}), detail = h('div', {});
  const teamName = id => (d.teams.find(t => t.id === id) || {}).name || id;
  const drawList = () => list.replaceChildren(...(d.metrics.length ? d.metrics.map(m => h('a', {class: 'vitem' + (m.id === sel ? ' on' : ''), onclick: () => { sel = m.id; drawList(); show(); }},
    h('div', {class: 'l1'}, h('span', {class: 'vn'}, m.name), mPill(m.status)), h('div', {class: 'l2'}, `${m.team}${m.published_version ? ' · v' + m.published_version : ''}`)))
    : [h('div', {class: 'vitem'}, h('div', {class: 'l2'}, 'No metrics yet. Send KPIs from a dashboard\'s Plan tab, or add one.'))]));
  async function show() {
    if (!sel) return detail.replaceChildren();
    const m = await api(`/api/semantic/metrics/${sel}`);
    const pub = m.published, open = m.open, b = (pub || open || {}).body || {};
    const canDev = S.me && (S.me.admin || (S.me.teams || []).some(t => t.id === m.team_id && t.role === 'dev'));
    const act = async (path, json, msg) => { try { await api(`/api/semantic/metrics/${m.id}/${path}`, {json}); notify(msg, 'ok'); reSem(); } catch (e) { notify(e.message, 'err'); } };
    detail.replaceChildren(h('div', {class: 'card'},
      h('div', {class: 'row'}, h('h2', {style: 'margin:0'}, m.name), pub ? h('span', {class: 'tag ok'}, icon('check'), `Certified v${pub.version}`) : null,
        open ? mPill(open.status) : null, m.org_default ? h('span', {class: 'tag acc'}, 'Organisation default') : null, h('span', {class: 'spacer'}),
        canDev && (!open || open.status === 'draft') ? h('button', {class: 'btn', onclick: () => metricDialog(m, d.teams)}, open ? 'Edit draft' : 'New version') : null,
        canDev && open && open.status === 'draft' ? h('button', {class: 'btn primary', onclick: () => act('submit', {version: open.version}, 'Sent for review')}, 'Send for review') : null),
      h('div', {class: 'muted', style: 'margin:4px 0 12px'}, `${b.label || ''}${b.label ? ' · ' : ''}${m.team} · ${b.description || ''}`),
      pub ? [h('h3', {}, `Published v${pub.version}`), h('div', {class: 'dax mono small', style: 'white-space:pre-wrap;background:var(--surface-2);padding:8px;border-radius:8px'}, pub.body.dax),
        h('div', {class: 'small', style: 'margin:8px 0'}, `Format ${pub.body.format || '—'}`, pub.body.synonyms ? ` · also called ${pub.body.synonyms.join(', ')}` : ''),
        h('b', {class: 'small'}, 'SQL by warehouse' + (pub.body.sql_derived ? ' (derived from the DAX)' : '')), sqlTabs(pub.sql_by_dialect)] : null,
      open && open.status === 'review' ? h('div', {class: 'note warn', style: 'margin-top:12px'}, `v${open.version} is waiting for review by another BI Dev / Analyst of ${m.team}.`,
        h('div', {class: 'dax mono small', style: 'white-space:pre-wrap;margin-top:6px'}, open.body.dax)) : null,
      h('h3', {style: 'margin-top:16px'}, 'Used in'), m.used_in.length ? h('div', {class: 'stack', style: 'gap:4px'}, m.used_in.map(u => h('div', {class: 'row'},
        h('a', {href: '#/p/' + u.project}, u.name), h('span', {class: 'tag ' + (u.status === 'certified' ? 'ok' : 'warn')}, u.status))))
        : h('div', {class: 'muted small'}, 'No dashboard of the team uses it yet.'),
      h('h3', {style: 'margin-top:16px'}, 'History'), h('table', {class: 'utable'}, h('tr', {}, ['Version', 'Status', 'When', 'Note'].map((t, i) => h('th', {class: i ? '' : 'l'}, t))),
        m.versions.slice().reverse().map(v => h('tr', {}, h('td', {}, 'v' + v.version), h('td', {}, mPill(v.status)), h('td', {class: 'n'}, when(v.decided || v.created)), h('td', {class: 'small'}, v.note || (v.source ? 'from a dashboard' : '')))))));
  }
  drawList(); show();
  return h('div', {}, h('div', {class: 'row', style: 'margin-bottom:12px'}, h('span', {class: 'muted small'}, `${d.metrics.length} metric(s) in ${d.teams.length} team(s)`),
    h('span', {class: 'spacer'}), S.me && S.me.builder ? h('button', {class: 'btn primary', onclick: () => metricDialog(null, d.teams)}, icon('plus'), 'New metric') : null),
    h('div', {class: 'vwrap'}, list, detail));
}

function metricDialog(m, teams) {
  const b = m ? ((m.open || m.published || {}).body || {}) : {};
  const mine = teams.filter(t => S.me && (S.me.admin || (S.me.teams || []).some(x => x.id === t.id && x.role === 'dev')));
  const team = h('select', {class: 'sel', disabled: !!m}, mine.map(t => h('option', {value: t.id, selected: m && t.id === m.team_id}, t.name)));
  const f = (v, ph, area) => area ? h('textarea', {rows: 3, class: 'mono'}, v || '') : h('input', {type: 'text', value: v || '', placeholder: ph || ''});
  const name = f(m ? m.name : '', 'Net Revenue'), label = f(b.label, 'Revenue'), desc = f(b.description, 'What it means, in business words');
  const dax = f(b.dax, '', true), sql = f(b.sql_derived ? '' : b.sql, '', true), fmt = f(b.format, '\\$#,0'), syn = f((b.synonyms || []).join(', '), 'sales, turnover');
  if (m) name.disabled = true;
  sql.placeholder = 'Optional. SQL over the model tables, e.g. SUM("Sales"."Net") — left empty, simple DAX is translated for you.';
  const mm = modal(m ? `${m.name}: ${m.open ? 'edit draft v' + m.open.version : 'new version'}` : 'New team metric', h('div', {class: 'mbody'},
    h('div', {class: 'opts'}, h('div', {}, h('label', {class: 'f', style: 'margin-top:0'}, 'Team'), team), h('div', {}, h('label', {class: 'f', style: 'margin-top:0'}, 'Name'), name)),
    h('div', {class: 'opts'}, h('div', {}, h('label', {class: 'f'}, 'Label on dashboards'), label), h('div', {}, h('label', {class: 'f'}, 'Format'), fmt)),
    h('label', {class: 'f'}, 'Meaning'), desc, h('label', {class: 'f'}, 'DAX (Power BI)'), dax, h('label', {class: 'f'}, 'SQL (Ask D, every warehouse)'), sql,
    h('label', {class: 'f'}, 'Also called'), syn,
    h('div', {class: 'row', style: 'justify-content:flex-end;margin-top:14px'}, h('button', {class: 'btn', onclick: () => mm.remove()}, 'Cancel'),
      h('button', {class: 'btn primary', onclick: async () => {
        try { await api('/api/semantic/metrics', {json: {team_id: m ? m.team_id : team.value, name: name.value, body: {label: label.value, description: desc.value,
          dax: dax.value, sql: sql.value, format: fmt.value, synonyms: syn.value}}}); notify('Draft saved — send it for review when ready', 'ok'); mm.remove(); reSem(); }
        catch (e) { notify(e.message, 'err'); } }}, 'Save draft'))), true);
}

async function semReviews() {
  const d = await api('/api/semantic/reviews');
  if (!d.reviews.length) return h('div', {class: 'card empty'}, h('h3', {}, 'Nothing to review'), 'Metric changes your teams send for review appear here.');
  return h('div', {class: 'stack'}, d.reviews.map(m => {
    const note = h('input', {type: 'text', placeholder: 'Note (shown in the history)'});
    const decide = approve => async () => { try { await api(`/api/semantic/metrics/${m.id}/decide`, {json: {version: m.open.version, approve, note: note.value}});
      notify(approve ? `${m.name} v${m.open.version} published` : 'Sent back', 'ok'); reSem(); } catch (e) { notify(e.message, 'err'); } };
    return h('div', {class: 'card', style: 'margin:0'}, h('div', {class: 'row'}, h('b', {}, `${m.name} · v${m.open.version}`), mPill('review'), h('span', {class: 'muted small'}, m.team)),
      h('div', {class: 'cmpgrid', style: 'margin-top:10px'},
        h('div', {}, h('small', {class: 'muted'}, m.published ? `Published v${m.published.version}` : 'New metric'), h('pre', {class: 'mono small', style: 'white-space:pre-wrap'}, m.published ? m.published.body.dax : '—')),
        h('div', {}, h('small', {class: 'muted'}, `Proposed v${m.open.version}`), h('pre', {class: 'mono small', style: 'white-space:pre-wrap'}, m.open.body.dax))),
      m.used_in.length ? h('div', {class: 'note warn small'}, `Affects ${m.used_in.map(u => u.name).join(', ')} — their measures are then flagged until updated.`) : null,
      m.can_decide ? h('div', {class: 'row', style: 'margin-top:10px'}, note, h('button', {class: 'btn', onclick: decide(false)}, 'Send back'), h('button', {class: 'btn primary', onclick: decide(true)}, 'Approve and publish'))
        : h('div', {class: 'muted small', style: 'margin-top:8px'}, 'You wrote this version: another BI Dev / Analyst of the team reviews it.'));
  }));
}

async function semTerms() {
  const d = await api('/api/semantic/terms');
  const term = h('input', {type: 'text', placeholder: 'Store'}), meaning = h('input', {type: 'text', placeholder: 'A physical shop, DIM_STORE'}), syn = h('input', {type: 'text', placeholder: 'shop, branch, outlet'});
  const team = h('select', {class: 'sel'}, (S.me && S.me.admin ? [h('option', {value: ''}, 'Whole organisation')] : []),
    d.teams.filter(t => S.me && (S.me.admin || (S.me.teams || []).some(x => x.id === t.id && x.role === 'dev'))).map(t => h('option', {value: t.id}, t.name)));
  const kind = h('select', {class: 'sel'}, ['term', 'entity', 'filter', 'value', 'time'].map(k => h('option', {value: k}, k)));
  return h('div', {}, S.me && S.me.builder ? h('div', {class: 'card flat'}, h('div', {class: 'opts', style: 'grid-template-columns:1fr 2fr 1.4fr 1fr .8fr'},
      ...[['Term', term], ['Means', meaning], ['Also called', syn], ['Team', team], ['Kind', kind]].map(([l, el]) => h('div', {}, h('small', {class: 'muted'}, l), el))),
    h('div', {class: 'row', style: 'justify-content:flex-end;margin-top:8px'}, h('button', {class: 'btn primary', onclick: async () => {
      try { await api('/api/semantic/terms', {json: {term: term.value, meaning: meaning.value, synonyms: syn.value, team_id: team.value || null, kind: kind.value}}); notify('Term added', 'ok'); reSem(); }
      catch (e) { notify(e.message, 'err'); } }}, icon('plus'), 'Add term'))) : null,
    h('div', {class: 'card flat', style: 'padding:0;overflow:auto'}, h('table', {class: 'utable'}, h('tr', {}, ['Term', 'Means', 'Also called', 'Kind', 'Team', ''].map(t => h('th', {class: 'l'}, t))),
      d.terms.map(t => h('tr', {}, h('td', {}, h('b', {}, t.term)), h('td', {}, t.meaning), h('td', {}, h('div', {class: 'chips'}, t.synonyms.map(s => h('span', {class: 'tag'}, s)))),
        h('td', {}, h('span', {class: 'tag'}, t.kind)), h('td', {}, t.team_id ? ((d.teams.find(x => x.id === t.team_id) || {}).name || t.team_id) : 'Organisation'),
        h('td', {}, h('button', {class: 'btn sm ghost', onclick: async () => { try { await api(`/api/semantic/terms/${t.id}`, {method: 'DELETE'}); reSem(); } catch (e) { notify(e.message, 'err'); } }}, icon('x'))))))));
}

const ORIGIN_TAG = c => c.origin === 'warehouse' ? h('span', {class: 'tag', title: "The source warehouse's own comment"}, 'From warehouse')
  : c.origin === 'ai' && c.status === 'suggested' ? h('span', {class: 'tag warn', title: 'Drafted by AI from the names, types and real values — check it, then accept or edit'}, 'AI suggested')
  : c.origin === 'ai' ? h('span', {class: 'tag ok', title: 'Drafted by AI and confirmed by a person'}, 'AI · confirmed') : null;

async function semContext() {
  const d = await api('/api/semantic/context');
  if (!d.tables.length) return h('div', {class: 'card empty'}, 'No data yet: the context fills in from your dashboards\' data.');
  const builder = S.me && S.me.builder;
  const tableCard = t => {
    const card = h('details', {class: 'card ctxcard', style: 'margin:0', open: t._open || null});
    const missing = t.columns.filter(c => !c.description).length + (t.description ? 0 : 1);
    const suggested = t.columns.filter(c => c.status === 'suggested' && c.description).map(c => c.name).concat(t.status === 'suggested' && t.description ? [''] : []);
    const redraw = nt => { nt._open = true; card.replaceWith(tableCard(nt)); };
    const draft = async (e, redo) => { const b = e.currentTarget; b.disabled = true; b.textContent = 'Drafting…';
      try { const r = await api('/api/semantic/context/draft', {json: {source: t.source, redo}}); notify(`${r.drafted} description(s) drafted — review them`, 'ok'); redraw(r.table); }
      catch (err) { notify(err.message, 'err'); b.disabled = false; b.textContent = 'Draft missing descriptions'; } };
    const acceptAll = async () => { try { await api('/api/semantic/context/accept', {json: {source: t.source, tbl: t.table, cols: suggested}});
      notify('Accepted', 'ok'); redraw({...t, status: t.status === 'suggested' ? 'confirmed' : t.status, columns: t.columns.map(c => c.status === 'suggested' ? {...c, status: 'confirmed'} : c)}); } catch (err) { notify(err.message, 'err'); } };
    const saveNote = async (col, text, sensitive) => api('/api/semantic/context/note', {method: 'PUT', json: {source: t.source, tbl: t.table, col, description: text, sensitive}});
    const tdesc = h('textarea', {rows: 2, placeholder: 'What this table holds, in business terms…', disabled: !builder, 'aria-label': `Description of ${t.table}`}, t.description || '');
    tdesc.onchange = async () => { try { await saveNote('', tdesc.value, false); notify('Saved', 'ok'); } catch (e) { notify(e.message, 'err'); } };
    card.append(
      h('summary', {style: 'cursor:pointer'}, h('b', {}, t.table),
        h('span', {class: 'muted small'}, `  ${t.source} · ${(t.rows || 0).toLocaleString()} rows · ${t.columns.length} columns · used by ${t.used_by.length} dashboard(s)`),
        t.warehouse ? h('span', {class: 'tag acc', style: 'margin-left:6px'}, 'warehouse') : null,
        missing ? h('span', {class: 'tag', style: 'margin-left:6px'}, `${missing} undescribed`) : h('span', {class: 'tag ok', style: 'margin-left:6px'}, 'described'),
        suggested.length ? h('span', {class: 'tag warn', style: 'margin-left:6px'}, `${suggested.length} to review`) : null,
        t.description ? h('div', {class: 'small muted', style: 'margin:4px 0 0'}, t.description) : null),
      h('div', {class: 'row', style: 'margin:10px 0 6px;align-items:flex-start'},
        h('div', {class: 'grow'}, h('label', {class: 'f', style: 'margin-top:0'}, 'Table description ', ORIGIN_TAG(t)), tdesc),
        builder ? h('div', {class: 'stack', style: 'gap:6px'},
          h('button', {class: 'btn sm primary', onclick: e => draft(e, false), disabled: !missing || null, title: 'Draft only what is missing; descriptions people wrote are never replaced'}, 'Draft missing descriptions'),
          suggested.length ? h('button', {class: 'btn sm', onclick: acceptAll}, icon('check'), `Accept ${suggested.length} suggestion(s)`) : null) : null),
      h('table', {class: 'utable', style: 'margin-top:8px'}, h('tr', {}, ['Column', 'Type', 'Examples', 'Detected', 'Description', 'Sensitive'].map(x => h('th', {class: 'l'}, x))),
        t.columns.map(c => {
          const desc = h('textarea', {rows: 2, class: 'cdesc', placeholder: 'Describe…', disabled: !builder, 'aria-label': `Description of ${c.name}`}, c.description || '');
          const sens = h('input', {type: 'checkbox', checked: c.sensitive, disabled: !builder, 'aria-label': `${c.name} is sensitive`});
          const save = async () => { try { await saveNote(c.name, desc.value, sens.checked); notify('Saved', 'ok'); c.description = desc.value; c.origin = 'person'; c.status = 'confirmed'; tagCell.replaceChildren(); } catch (e) { notify(e.message, 'err'); } };
          desc.onchange = save; sens.onchange = save;
          const tagCell = h('div', {class: 'row', style: 'gap:4px;margin-top:3px'}, ORIGIN_TAG(c),
            c.status === 'suggested' && c.description && builder ? h('button', {class: 'btn sm ghost', onclick: async () => {
              try { await api('/api/semantic/context/accept', {json: {source: t.source, tbl: t.table, cols: [c.name]}}); c.status = 'confirmed'; tagCell.replaceChildren(ORIGIN_TAG(c)); notify('Accepted', 'ok'); }
              catch (e) { notify(e.message, 'err'); } }}, icon('check'), 'Accept') : null);
          return h('tr', {}, h('td', {class: 'mono'}, c.name), h('td', {}, c.type), h('td', {class: 'small muted'}, (c.samples || []).slice(0, 4).join(', ')),
            h('td', {}, c.key ? h('span', {class: 'tag ok'}, 'unique key') : c.nulls ? h('span', {class: 'tag'}, `${c.nulls} blank`) : ''),
            h('td', {style: 'min-width:280px'}, desc, tagCell), h('td', {}, sens)); })),
      t.joins.length ? h('div', {class: 'small muted', style: 'margin-top:6px'}, 'Joins: ' + t.joins.map(j => `${j.many} → ${j.one} (${Math.round(j.matched * 100)}%)`).join(' · ')) : null);
    return card;
  };
  const undescribed = d.tables.reduce((n, t) => n + t.columns.filter(c => !c.description).length, 0);
  return h('div', {class: 'stack'},
    h('div', {class: 'note small'}, icon('info'), ' Tables and columns come from each dashboard\'s data. Descriptions come from the warehouse\'s own comments when it has them; ',
      'what is still missing can be drafted by AI from the names, types and real values, and stays “AI suggested” until someone accepts or edits it. ',
      `Ask D uses all of them. ${undescribed} column(s) are not described yet.`),
    d.tables.map(tableCard));
}

async function entityDetails(eid) {
  const body = h('div', {class: 'mbody'}, skel('rows'));
  const m = modal('Entity', body, true);
  const draw = d => {
    $('header b', m).textContent = d.name;
    const sec = (title, ...kids) => h('section', {class: 'esec'}, h('h4', {}, title), ...kids);
    const draftBtn = d.can_edit ? h('button', {class: 'btn sm' + (d.definition ? '' : ' primary'), onclick: async e => {
      const b = e.currentTarget; b.disabled = true; b.textContent = 'Drafting…';
      try { draw(await api(`/api/semantic/entities/${eid}/draft`, {method: 'POST'})); notify('Drafted — review it, then accept or edit', 'ok'); }
      catch (err) { notify(err.message, 'err'); b.disabled = false; b.textContent = d.definition ? 'Redraft with AI' : 'Draft with AI'; } }}, d.definition ? 'Redraft with AI' : 'Draft with AI') : null;
    const acceptBtn = d.can_edit && d.drafted_by === 'ai' ? h('button', {class: 'btn sm primary', onclick: async () => {
      try { await api(`/api/semantic/entities/${eid}`, {method: 'PUT', json: {name: d.name, description: d.description, definition: d.definition, examples: d.examples, synonyms: d.synonyms, status: d.status}});
        draw({...d, drafted_by: null}); notify('Accepted', 'ok'); reSem(); } catch (err) { notify(err.message, 'err'); } }}, icon('check'), 'Accept draft') : null;
    body.replaceChildren(
      h('div', {class: 'row', style: 'gap:8px'}, mPill(d.status === 'published' ? 'published' : 'draft'),
        d.owner_team ? h('span', {class: 'tag'}, 'Owner: ' + d.owner_team) : null,
        d.drafted_by === 'ai' ? h('span', {class: 'tag warn', title: 'Drafted by AI from where this entity lives in the data — check it'}, 'AI draft · to review') : null,
        h('span', {class: 'spacer'}), draftBtn, acceptBtn,
        d.can_edit ? h('button', {class: 'btn sm', onclick: async () => { m.remove(); entityDialog(d, await api('/api/semantic/ontology')); }}, icon('edit'), 'Edit') : null),
      d.description ? h('p', {style: 'font-size:15px;margin:12px 0 4px'}, d.description) : null,
      d.synonyms.length ? h('div', {class: 'small muted'}, 'Also called: ' + d.synonyms.join(', ')) : null,
      sec('What it is in the business', d.definition ? h('p', {style: 'margin:0;max-width:820px'}, d.definition)
        : h('div', {class: 'muted small'}, 'No business definition yet.' + (d.can_edit ? ' Draft one with AI from where it lives in the data, then review it.' : ''))),
      sec('Examples', d.examples.length ? h('ul', {class: 'eex'}, d.examples.map(x => h('li', {}, x))) : h('div', {class: 'muted small'}, 'No examples written yet.')),
      d.live_examples.length ? sec('Real records from the data', h('div', {class: 'egrid'},
        [...new Set(d.live_examples.map(x => x.source))].map(src => { const rows = d.live_examples.filter(x => x.source === src);
          return h('div', {}, h('div', {class: 'small muted', style: 'margin-bottom:4px'}, rows[0].table), h('table', {class: 'utable'},
            h('tr', {}, Object.keys(rows[0].values).map(k => h('th', {class: 'l'}, k))),
            rows.map(x => h('tr', {}, Object.values(x.values).map(v => h('td', {}, v ?? '—')))))); }))) : null,
      sec('Where it lives', d.where.length ? h('table', {class: 'utable'}, h('tr', {}, ['Source', 'Table', 'Key column', 'Rows', 'Meaning'].map(x => h('th', {class: 'l'}, x))),
        d.where.map(w => h('tr', {}, h('td', {class: 'small mono'}, w.source), h('td', {}, w.tbl), h('td', {class: 'mono'}, w.col),
          h('td', {class: 'n'}, w.rows != null ? w.rows.toLocaleString() : '—'),
          h('td', {class: 'small'}, w.visible === false ? h('span', {class: 'muted'}, 'You cannot open this source') : [w.column_description || '', w.table_description ? h('div', {class: 'muted'}, w.table_description) : null]))))
        : h('div', {class: 'muted small'}, 'Not mapped to any source yet — confirm a key match in “Needs a decision”.')),
      sec('Related to', d.relations.length ? h('ul', {class: 'eex'}, d.relations.map(r => h('li', {}, r.direction === 'out' ? [h('b', {}, d.name), ` ${r.verb} `, h('a', {href: '#', onclick: e => { e.preventDefault(); m.remove(); entityDetails(r.to_id); }}, r.to)]
        : [h('a', {href: '#', onclick: e => { e.preventDefault(); m.remove(); entityDetails(r.to_id); }}, r.to), ` ${r.verb} `, h('b', {}, d.name)])))
        : h('div', {class: 'muted small'}, 'No relationships yet.')),
      sec('Used in', d.used_in.length || d.metrics.length ? h('div', {class: 'stack', style: 'gap:6px'},
        d.used_in.length ? h('div', {class: 'chips'}, d.used_in.map(p => h('a', {class: 'chip', href: '#/p/' + p.id, onclick: () => m.remove()}, icon('grid'), ' ', p.name))) : null,
        d.metrics.length ? h('div', {class: 'small'}, 'Certified metrics: ', d.metrics.map(x => `${x.name} (${x.team})`).join(' · ')) : null)
        : h('div', {class: 'muted small'}, 'Not used by a dashboard or certified metric you can see.')));
  };
  try { draw(await api(`/api/semantic/entities/${eid}/details`)); } catch (e) { body.replaceChildren(h('div', {class: 'note err'}, e.message)); }
}

async function semOntology() {
  const d = await api('/api/semantic/ontology');
  const box = h('div', {});
  const draw = o => {
    const ents = o.entities, n = ents.length, W = 760, H = 380, cx = W / 2, cy = H / 2, R = Math.min(150, 50 + n * 18);
    const pos = Object.fromEntries(ents.map((e, i) => [e.id, [cx + R * Math.cos(2 * Math.PI * i / Math.max(n, 1) - Math.PI / 2), cy + R * Math.sin(2 * Math.PI * i / Math.max(n, 1) - Math.PI / 2)]]));
    const svg = n ? `<svg viewBox="0 0 ${W} ${H}" width="100%" style="max-height:380px">` +
      o.relations.map(r => { const [x1, y1] = pos[r.from_id] || [0, 0], [x2, y2] = pos[r.to_id] || [0, 0];
        return `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="#D3CFC2" stroke-width="1.5"/><text x="${(x1 + x2) / 2}" y="${(y1 + y2) / 2 - 4}" text-anchor="middle" font-size="11" fill="#5F655F" style="paint-order:stroke" stroke="#fff" stroke-width="4">${esc(r.verb)}</text>`; }).join('') +
      ents.map(e => { const [x, y] = pos[e.id]; return `<g data-eid="${esc(e.id)}"><title>${esc(e.name)}: open details</title><rect x="${x - 64}" y="${y - 22}" width="128" height="44" rx="12" fill="${e.status === 'published' ? '#EAF3F0' : '#fff'}" stroke="${e.status === 'published' ? '#0E5A4A' : '#CBD0D7'}" stroke-width="1.5"/>` +
        `<text x="${x}" y="${y - 2}" text-anchor="middle" font-size="13" font-weight="600" fill="#0F2A23">${esc(e.name)}</text><text x="${x}" y="${y + 13}" text-anchor="middle" font-size="10" fill="#5F655F">${e.keys.length} source key(s)</text></g>`; }).join('') + '</svg>' : '';
    const graph = h('div', {class: 'card'}, h('div', {class: 'row'}, h('h3', {style: 'margin:0'}, 'Entities and relationships'), h('span', {class: 'spacer'}),
      S.me && S.me.builder ? h('button', {class: 'btn', onclick: async e => { e.target.disabled = true; try { const r = await api('/api/semantic/ontology/scan', {method: 'POST'}); notify(`Scan done: ${r.found} new possible match(es)`, 'ok'); draw(r); groups.reload(); e.target.disabled = false; } catch (err) { notify(err.message, 'err'); e.target.disabled = false; } }}, icon('spark'), 'Scan sources for matches') : null,
      S.me && S.me.builder ? h('button', {class: 'btn primary', onclick: () => entityDialog(null, o)}, icon('plus'), 'Entity') : null));
    const g = h('div', {}); g.innerHTML = svg || '<div class="oempty"><b>No entities yet.</b> An entity is a business thing — a Store, a Product, a Customer — and the columns that identify it in each dashboard&rsquo;s data. '
      + 'Confirm the possible entities below (Relay found them by matching values across tables), or add one yourself with <b>+ Entity</b>.</div>';
    g.querySelectorAll('g[data-eid]').forEach(n => { n.style.cursor = 'pointer'; n.addEventListener('click', () => entityDetails(n.dataset.eid)); });
    graph.append(g);
    const words = o.suggestions.filter(x => x.kind === 'same_word');
    const sugg = words.length || o.defaults.length ? h('div', {class: 'card'}, h('h3', {style: 'margin-top:0'}, 'Same metric name, different definitions ', h('span', {class: 'tag ' + (words.length ? 'warn' : '')}, words.length)),
      h('div', {class: 'small muted', style: 'margin-bottom:6px'}, 'Two teams define a metric with the same name differently. Both stay; an Admin picks the organisation default that Ask D uses for organisation-wide questions.'),
      words.map(s => h('div', {style: 'padding:8px 0;border-bottom:1px solid var(--line)'}, h('b', {}, `“${s.payload.term}” — ${s.payload.options.length} definitions`),
        s.payload.options.map(op => h('div', {class: 'row', style: 'margin-top:6px'}, h('span', {class: 'tag'}, op.team), h('code', {class: 'small', style: 'flex:1'}, op.dax),
          S.me && S.me.admin ? h('button', {class: 'btn sm', onclick: () => decideSugg(s.id, true, op.metric_id)}, 'Make default') : null)))),
      o.defaults.length ? h('div', {class: 'small', style: 'margin-top:8px'}, 'Organisation defaults: ' + o.defaults.map(x => `${x.term} → ${x.team}`).join(' · ')) : null) : null;
    const list = h('div', {class: 'card'}, h('h3', {}, 'Entities'), ents.length ? h('table', {class: 'utable'}, h('tr', {}, ['Entity', 'Same thing in', 'Owner', 'Status', ''].map(t => h('th', {class: 'l'}, t))),
      ents.map(e => h('tr', {}, h('td', {}, h('a', {href: '#', class: 'ename', onclick: ev => { ev.preventDefault(); entityDetails(e.id); }}, e.name),
          h('div', {class: 'small muted'}, e.description || (e.definition || '').slice(0, 140)),
          e.drafted_by === 'ai' ? h('span', {class: 'tag warn'}, 'AI draft · to review') : !e.definition ? h('span', {class: 'tag'}, 'No business definition') : null),
        h('td', {class: 'small mono'}, e.keys.map(k => `${k.source} › ${k.tbl}[${k.col}]`).join('\n') || '—'), h('td', {}, e.owner_team || '—'), h('td', {}, mPill(e.status === 'published' ? 'published' : 'draft')),
        h('td', {style: 'white-space:nowrap'}, h('button', {class: 'btn sm', onclick: () => entityDetails(e.id)}, 'Details'), ' ',
          h('button', {class: 'btn sm', onclick: () => entityDialog(e, o)}, 'Edit'))))) : h('div', {class: 'muted small'}, 'None yet.'));
    box.replaceChildren(graph, groups, sugg, list);
  };
  const groups = matchGroupsCard(r => draw(r));
  const decideSugg = async (id, accept, choice) => { try { draw(await api(`/api/semantic/suggestions/${id}`, {json: {accept, choice}})); notify(accept ? 'Confirmed' : 'Dismissed', 'ok'); } catch (e) { notify(e.message, 'err'); } };
  draw(d);
  return box;
}
/* possible entities: key matches grouped so each business thing is one decision */
function matchGroupsCard(onChange) {
  const card = h('div', {class: 'card'});
  let tab = 'high', data = null;
  const decide = async (g, accept, name, btn) => {
    if (btn) btn.disabled = true;
    try { const r = await api('/api/semantic/match-groups/decide', {json: {ids: g.suggestions, accept, name}});
      notify(accept ? `${name}: entity ${g.existing && g.existing.toLowerCase() === (name || '').toLowerCase() ? 'extended' : 'created'} with ${g.places.length} columns` : `${g.name}: dismissed`, 'ok');
      data.groups = r.groups; draw(); onChange(r); }
    catch (e) { notify(e.message, 'err'); if (btn) btn.disabled = false; }
  };
  const groupRow = g => {
    const name = h('input', {type: 'text', value: g.existing || g.name, style: 'width:180px', 'aria-label': 'Entity name'});
    const roleTag = p => p.role === 'master' ? h('span', {class: 'tag ok', title: 'Every value appears once: this table is the list of them'}, 'Master list')
      : h('span', {class: 'tag', title: 'Many rows point to the master list'}, 'Refers to it');
    const ex = g.samples.length ? 'e.g. ' + g.samples.slice(0, 4).join(', ') : g.range ? `values ${g.range[0]} to ${g.range[1]}` : '';
    const det = h('details', {},
      h('summary', {},
        h('div', {class: 'mg-head'},
          h('div', {class: 'mg-title'}, icon('columns'), h('b', {}, g.name),
            g.confidence === 'high' ? h('span', {class: 'tag ok'}, 'Likely') : h('span', {class: 'tag warn'}, 'Less likely'),
            g.existing ? h('span', {class: 'tag acc', title: 'An entity with this name exists'}, 'Entity exists') : null),
          h('div', {class: 'mg-meta'},
            h('span', {}, h('b', {}, g.places.length), ' columns'), h('span', {}, h('b', {}, g.tables), ' tables'),
            h('span', {}, h('b', {}, g.dashboards.length), g.dashboards.length === 1 ? ' dashboard' : ' dashboards'),
            h('span', {}, h('b', {}, Math.round(g.match * 100) + '%'), ' values match'))),
        h('div', {class: 'small', style: 'margin-top:4px'}, g.reason, ex ? h('span', {class: 'muted'}, ' ' + ex + '.') : null),
        h('div', {class: 'small muted', style: 'margin-top:2px'}, g.dashboards.join(' · ')),
        g.why_low.length ? h('div', {class: 'small warnt', style: 'margin-top:4px'}, 'Why less likely: ' + g.why_low.join('; ') + '.') : null),
      h('div', {class: 'mg-body'},
        h('table', {class: 'utable'}, h('tr', {}, ['Dashboard', 'Table', 'Column', 'Role', 'Rows', 'Distinct values', 'Meaning'].map(x => h('th', {class: x === 'Rows' || x === 'Distinct values' ? 'n' : 'l'}, x))),
          g.places.map(p => h('tr', {}, h('td', {}, p.dashboard), h('td', {}, p.tbl), h('td', {class: 'mono'}, p.col), h('td', {}, roleTag(p)),
            h('td', {class: 'n'}, p.rows != null ? p.rows.toLocaleString() : '—'), h('td', {class: 'n'}, p.distinct != null ? p.distinct.toLocaleString() : '—'),
            h('td', {class: 'small muted'}, p.entity ? h('span', {class: 'tag acc'}, 'In ' + p.entity) : p.description || '')))),
        g.hidden ? h('div', {class: 'small muted', style: 'margin-top:6px'}, `${g.hidden} more column(s) in sources you cannot open.`) : null,
        g.existing ? h('div', {class: 'note small', style: 'margin-top:8px'}, icon('info'), ` Confirming as “${g.existing}” adds these columns to the existing entity. If this is a different thing (for example another business's stores), give it its own name.`) : null));
    const el = h('div', {class: 'mgroup' + (g.confidence === 'low' ? ' low' : '')}, det);
    if (data.can_decide) {
      const act = h('div', {class: 'mg-actions'}, h('label', {class: 'small muted'}, 'Create as'), name,
        h('button', {class: 'btn sm primary', onclick: e => { e.preventDefault(); decide(g, true, name.value.trim(), e.currentTarget); }}, icon('check'), 'Confirm entity'),
        h('button', {class: 'btn sm', onclick: e => { e.preventDefault(); decide(g, false, null, e.currentTarget); }}, 'Not an entity'),
        h('span', {class: 'spacer'}), h('button', {class: 'btn sm ghost', onclick: () => { det.open = !det.open; }}, 'Show columns'));
      el.append(act);
    }
    return el;
  };
  const draw = () => {
    const gs = data.groups, hi = gs.filter(g => g.confidence === 'high'), lo = gs.filter(g => g.confidence === 'low');
    if (tab === 'high' && !hi.length && lo.length) tab = 'low';
    const shown = tab === 'high' ? hi : lo;
    const seg = (k, label, n) => h('button', {class: 'mtab' + (tab === k ? ' on' : ''), onclick: () => { tab = k; draw(); }}, label, h('span', {class: 'cnt'}, n));
    card.replaceChildren(
      h('div', {class: 'row', style: 'align-items:flex-start'},
        h('div', {class: 'grow'}, h('h3', {style: 'margin:0'}, 'Possible entities found in your data ', h('span', {class: 'tag ' + (gs.length ? 'warn' : '')}, gs.length)),
          h('div', {class: 'small muted', style: 'margin-top:4px;max-width:820px'},
            'Relay compared the identifier columns of every dashboard’s data. Where the same values appear in several tables, they probably identify the same business thing — a store, a product, a customer. ',
            'Confirm it to create an entity: Ask D then knows how to join those tables, and the ontology shows where each thing lives. Open a row to see every column.'))),
      gs.length ? h('div', {class: 'row', style: 'margin:12px 0 4px'},
        h('div', {class: 'mtabs'}, seg('high', 'Likely', hi.length), seg('low', 'Less likely', lo.length)), h('span', {class: 'spacer'}),
        data.can_decide && tab === 'low' && lo.length ? h('button', {class: 'btn sm', onclick: async e => {
          if (!await confirmBox(`Dismiss ${lo.length} less likely matches?`, 'They are copies of the same table, labels or settings. A new scan finds them again only if the data changes.', 'Dismiss all')) return;
          e.currentTarget.disabled = true;
          try { const r = await api('/api/semantic/match-groups/decide', {json: {ids: lo.flatMap(g => g.suggestions), accept: false}}); data.groups = r.groups; draw(); onChange(r); notify(`Dismissed ${lo.length}`, 'ok'); }
          catch (err) { notify(err.message, 'err'); } }}, 'Dismiss all less likely') : null) : null,
      gs.length ? h('div', {class: 'mglist'}, shown.map(groupRow)) : h('div', {class: 'muted small', style: 'margin-top:10px'}, 'Nothing waiting. Run “Scan sources for matches” after adding data.'));
  };
  card.reload = async () => { data = await api('/api/semantic/match-groups'); draw(); };
  card.append(skel('rows'));
  card.reload().catch(e => card.replaceChildren(h('div', {class: 'note err'}, e.message)));
  return card;
}
const esc = s => String(s).replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));

function entityDialog(e, o) {
  const name = h('input', {type: 'text', value: e ? e.name : '', placeholder: 'Store'}), desc = h('input', {type: 'text', value: e ? e.description || '' : ''});
  const syn = h('input', {type: 'text', value: e ? e.synonyms.join(', ') : '', placeholder: 'shop, branch'});
  const defin = h('textarea', {rows: 4, placeholder: 'What it is in the business, how it is identified, what decisions use it…'}, e ? e.definition || '' : '');
  const exs = h('textarea', {rows: 3, placeholder: 'One example per line, e.g. “Store S-104, a kirana in Koramangala (South zone)”'}, e ? (e.examples || []).join('\n') : '');
  const status = h('select', {class: 'sel'}, ['draft', 'published'].map(s => h('option', {value: s, selected: e && e.status === s}, s === 'published' ? 'Published (Ask D uses it)' : 'Draft')));
  const relTo = h('select', {class: 'sel'}, o.entities.filter(x => !e || x.id !== e.id).map(x => h('option', {value: x.id}, x.name)));
  const verb = h('input', {type: 'text', placeholder: 'sold at, belongs to, staffed by…'});
  const m = modal(e ? `Entity · ${e.name}` : 'New entity', h('div', {class: 'mbody'},
    h('div', {class: 'opts'}, h('div', {}, h('label', {class: 'f', style: 'margin-top:0'}, 'Name'), name), h('div', {}, h('label', {class: 'f', style: 'margin-top:0'}, 'Status'), status)),
    h('label', {class: 'f'}, 'Meaning (one line)'), desc, h('label', {class: 'f'}, 'What it is in the business'), defin,
    h('label', {class: 'f'}, 'Examples'), exs, h('label', {class: 'f'}, 'Also called'), syn,
    e ? [h('label', {class: 'f'}, 'Relationship to another entity'), h('div', {class: 'row', style: 'flex-wrap:nowrap'}, verb, relTo,
      h('button', {class: 'btn', onclick: async () => { try { await api('/api/semantic/relations', {json: {from_id: e.id, verb: verb.value, to_id: relTo.value}}); notify('Relationship added', 'ok'); m.remove(); reSem(); } catch (err) { notify(err.message, 'err'); } }}, 'Add'))] : null,
    h('div', {class: 'row', style: 'justify-content:flex-end;margin-top:14px'},
      e ? h('button', {class: 'btn danger', onclick: async () => { if (!await confirmBox(`Remove ${e.name}?`, `The entity, its keys and its relations leave the ontology. Ask D stops using them.`)) return; try { await api(`/api/semantic/entities/${e.id}`, {method: 'DELETE'}); m.remove(); reSem(); } catch (err) { notify(err.message, 'err'); } }}, 'Remove') : null,
      h('span', {class: 'spacer'}), h('button', {class: 'btn', onclick: () => m.remove()}, 'Cancel'),
      h('button', {class: 'btn primary', onclick: async () => { try { await api(e ? `/api/semantic/entities/${e.id}` : '/api/semantic/entities', {method: e ? 'PUT' : 'POST',
        json: {name: name.value, description: desc.value, synonyms: syn.value, status: status.value, definition: defin.value, examples: exs.value.split('\n')}}); notify('Saved', 'ok'); m.remove(); reSem(); } catch (err) { notify(err.message, 'err'); } }}, 'Save'))));
}
