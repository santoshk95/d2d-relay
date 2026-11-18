/* ---------------- D2D Relay: Semantic Review (#/review, item 55). Power BI semantic models checked against the
   organisation's KPI dictionary: one KPI, one meaning, one value (webapp/app/semreview.py, genbi_kit/semreview).
   #/review          new review (files or Power BI), the KPI dictionary card, the organisation's reviews
   #/review/kpis     the KPI dictionary: add, edit, import (CSV, Excel, YAML, JSON), download
   #/review/<id>     one review: findings, KPIs, measures, models (it polls while the review runs) ---------------- */
const SR = {timer: null, tab: 'findings', sev: 'all', q: '', picks: [], files: [], kq: '', mq: '', sel: new Set(), data: null};
const SR_SEV = {high: ['High', 'err'], medium: ['Medium', 'warn'], low: ['Low', ''], info: ['Info', '']};
const SR_STATUS = {queued: 'Starting', reading: 'Reading', checking: 'Checking', meaning: 'Meaning check', values: 'Values', done: 'Done', error: 'Failed'};
const SR_KPI = {consistent: ['One meaning', 'ok'], conflict: ['Calculated more than one way', 'err'], differs: ['Not as defined', 'err'],
  missing: ['In no model', ''], variants_only: ['Only variants found', ''], unreadable: ['Cannot be read', 'err']};
const SR_HOW = {name: 'name', synonym: 'other name', similar: 'similar name', variant: 'variant', ai: "Relay's AI"};
const SR_RULES = {conflict: 'One KPI, many formulas', differs: 'Not as defined', aggregation: 'Aggregation', average_of_ratios: 'Average of ratios',
  variant_drift: 'Variant drifts', time_basis: 'Year end', unit: 'Format', title: 'Visual title', implicit_visual: 'Visual works it out itself',
  broken: 'Cannot be read', frozen_variable: 'Frozen variable', iterator_aggregate: 'Same total on every row', filter_override: 'Ignores filters',
  duplicate: 'Two names, one number', base_not_reused: 'Repeats a formula', implicit_sum: 'Adds up by default', constant: 'Fixed numbers',
  unsafe_division: 'Division', bidirectional: 'Both-way filters', calc_groups: 'Calculation groups', missing: 'Missing KPIs',
  undocumented: 'Not in the dictionary', description: 'No description', dictionary: 'Dictionary', meaning: 'Meaning', meaning_match: 'Looks like a KPI'};
const srLeave = () => { clearTimeout(SR.timer); SR.timer = null; };
const srTag = (sev) => { const [t, c] = SR_SEV[sev] || [sev, '']; return h('span', {class: 'tag ' + (c === 'err' ? 'srhigh' : c)}, t); };
const srPill = (s, step) => h('span', {class: 'pill ' + (s === 'done' ? 'ok' : s === 'error' ? 'err' : 'run')}, s === 'done' || s === 'error' ? SR_STATUS[s] : (step || SR_STATUS[s] || 'Running'));
const srCost = n => n ? `${n} credits` : '';
const srNum = v => (typeof v === 'number' ? (Math.abs(v) < 10 && v % 1 ? v.toLocaleString(undefined, {maximumFractionDigits: 4}) : v.toLocaleString(undefined, {maximumFractionDigits: 2})) : v == null ? 'blank' : String(v));

function renderReview() {
  srLeave();
  const m = location.hash.match(/^#\/review(?:\/([^/?]+))?/);
  const sub = m && m[1];
  if (sub === 'kpis') return renderKpiDictionary();
  if (sub) return renderReviewRun(sub);
  return renderReviewHome();
}

/* ---------------- the landing page ---------------- */
async function renderReviewHome() {
  document.title = 'Semantic Review - D2D Relay';
  const page = h('div', {class: 'page'});
  $('#main').replaceChildren(page);
  let d;
  try { d = SR.data = await api('/api/semreview'); } catch (e) { return page.append(h('div', {class: 'note err'}, e.message)); }
  page.append(
    h('div', {class: 'eyebrow'}, 'Semantic Review'),
    h('h1', {}, 'One KPI, one meaning, one value'),
    h('p', {class: 'muted lead'}, 'Check your Power BI semantic models against your KPI dictionary. Every measure that calculates a KPI differently from the others, '
      + 'or not the way your organisation defined it, is flagged with what to change. So is DAX that gives a wrong or unstable number.'),
    h('div', {class: 'orggrid srgrid'}, newReviewCard(d), dictionaryCard(d)),
    h('h2', {}, 'Reviews'),
    reviewsTable(d));
  if (d.runs.some(r => !['done', 'error'].includes(r.status))) SR.timer = setTimeout(() => { if (location.hash === '#/review') renderReviewHome(); }, 3000);
}

function reviewsTable(d) {
  if (!d.runs.length) return h('div', {class: 'card empty'}, h('h3', {}, 'No reviews yet'), h('div', {}, 'Upload a .pbix (or pick a model from Power BI) to run the first one.'));
  const result = r => {
    if (r.status === 'error') return h('span', {class: 'small', style: 'color:var(--err)'}, r.error || 'Failed');
    if (r.status !== 'done' || !r.summary) return h('span', {class: 'small muted'}, r.step || '');
    const s = r.summary, f = s.findings || {};
    return h('span', {class: 'srcounts'}, s.score != null ? h('b', {}, `${s.kpis_consistent} of ${s.kpis_checked} KPIs one meaning`) : null,
      f.high ? h('span', {class: 'tag srhigh'}, `${f.high} high`) : null, f.medium ? h('span', {class: 'tag warn'}, `${f.medium} medium`) : null,
      f.low ? h('span', {class: 'tag'}, `${f.low} low`) : null, !f.high && !f.medium && !f.low ? h('span', {class: 'tag ok'}, 'No problems') : null);
  };
  return h('div', {class: 'card orgwrap', style: 'padding:6px 10px'}, h('table', {class: 'utable srtable'},
    h('thead', {}, h('tr', {}, ['Review', 'Models', 'Result', 'By', 'When', ''].map(t => h('th', {class: 'l'}, t)))),
    h('tbody', {}, d.runs.map(r => h('tr', {class: 'srrow', tabindex: 0, onclick: () => { location.hash = `#/review/${r.id}`; },
      onkeydown: e => { if (e.key === 'Enter') location.hash = `#/review/${r.id}`; }},
      h('td', {}, h('a', {href: `#/review/${r.id}`}, r.name)),
      h('td', {class: 'small'}, r.sources.map(s => s.file || s.name).join(', ')),
      h('td', {}, result(r)), h('td', {class: 'small'}, r.by || 'Former member'), h('td', {class: 'small'}, ago(r.created)),
      h('td', {}, srPill(r.status, null)))))));
}

function newReviewCard(d) {
  const can = d.can.run, lim = d.limits;
  const input = h('input', {type: 'file', multiple: true, accept: '.pbix,.pbit,.bim,.json,.zip'});
  const list = h('div', {class: 'flist attached'});
  const name = h('input', {type: 'text', placeholder: 'For example: Sales and Finance models, November', maxlength: 120});
  const out = h('div', {role: 'status'});
  const bar = h('div', {class: 'srbar', hidden: true}, h('i'));
  const total = () => SR.files.length + SR.picks.length;
  const show = () => list.replaceChildren(
    ...SR.files.map((f, i) => h('span', {}, icon('file'), ' ' + f.name + ' - ' + size(f.size),
      h('button', {type: 'button', title: 'Remove', 'aria-label': `Remove ${f.name}`, onclick: () => { SR.files.splice(i, 1); show(); }}, '×'))),
    ...SR.picks.map((p, i) => h('span', {}, icon('db'), ` ${p.name} (Power BI${p.workspace_name ? ': ' + p.workspace_name : ''})`,
      h('button', {type: 'button', title: 'Remove', 'aria-label': `Remove ${p.name}`, onclick: () => { SR.picks.splice(i, 1); show(); }}, '×'))));
  const add = files => {
    for (const f of files) {
      if (!/\.(pbix|pbit|bim|json|zip)$/i.test(f.name)) { out.replaceChildren(h('div', {class: 'note warn'}, `"${f.name}" is not a .pbix, .pbit, model.bim or zipped Power BI project.`)); continue; }
      if (f.size > lim.mb * 1048576) { out.replaceChildren(h('div', {class: 'note warn'}, `"${f.name}" is bigger than ${lim.mb} MB. Save the report as a template (.pbit: no data, small) and upload that.`)); continue; }
      if (total() >= lim.files) { out.replaceChildren(h('div', {class: 'note warn'}, `A review reads up to ${lim.files} models.`)); break; }
      SR.files.push(f);
    }
    show();
  };
  input.onchange = () => { add(input.files); input.value = ''; };
  const drop = h('div', {class: 'drop', tabindex: 0, role: 'button', 'aria-label': 'Choose Power BI files', onclick: () => input.click(),
      onkeydown: e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); input.click(); } }},
    icon('publish'), h('div', {}, h('b', {}, 'Drop Power BI files here'), ' or click to choose'),
    h('div', {class: 'small muted'}, `.pbix, .pbit, model.bim or a zipped Power BI project folder - up to ${lim.files} models, ${lim.mb} MB each`), input);
  drop.addEventListener('dragover', e => { e.preventDefault(); drop.classList.add('over'); });
  drop.addEventListener('dragleave', () => drop.classList.remove('over'));
  drop.addEventListener('drop', e => { e.preventDefault(); drop.classList.remove('over'); add(e.dataTransfer.files); });
  const pbiRow = d.pbi.configured
    ? h('div', {class: 'row', style: 'gap:8px;flex-wrap:wrap;align-items:center'},
        h('button', {class: 'btn', type: 'button', disabled: !can, onclick: () => pickModels(show)}, icon('db'), 'Pick models from Power BI'),
        d.can.connect ? h('button', {class: 'btn ghost sm', type: 'button', onclick: () => pbiDialog(d.pbi)}, icon('gear'), 'Connection') : null)
    : d.can.connect ? h('button', {class: 'btn', type: 'button', onclick: () => pbiDialog(d.pbi)}, icon('plug'), 'Connect Power BI (Azure)')
      : h('span', {class: 'small muted'}, 'To review models in the Power BI service, an owner of your organisation connects Power BI here.');
  const go = h('button', {class: 'btn primary', type: 'button', disabled: !can}, icon('play'), 'Start review', costTag('review'));
  go.onclick = async () => {
    if (!total()) return out.replaceChildren(h('div', {class: 'note warn'}, 'Add a Power BI file, or pick a model from Power BI.'));
    // the files go up in one request, and the site's network (Cloudflare) takes at most 100 MB in one
    if (SR.files.reduce((n, f) => n + f.size, 0) > 95 * 1048576) return out.replaceChildren(h('div', {class: 'note warn'},
      'These files add up to more than 95 MB, more than one upload can carry. Review them in two goes, or save big reports as templates (.pbit: no data, small).'));
    const fd = new FormData();
    SR.files.forEach(f => fd.append('files', f));
    fd.append('azure', JSON.stringify(SR.picks));
    fd.append('name', name.value.trim());
    go.disabled = true; bar.hidden = false;
    try {
      const r = await upload('/api/semreview/runs', fd, p => { bar.firstChild.style.width = Math.round(p * 100) + '%'; });
      SR.files = []; SR.picks = [];
      if (typeof refreshOrg === 'function') refreshOrg(true);
      location.hash = `#/review/${r.id}`;
    } catch (e) {
      out.replaceChildren(h('div', {class: 'note err'}, e.message));
      go.disabled = false; bar.hidden = true;
    }
  };
  show();
  return h('div', {class: 'card'}, h('h3', {}, 'New review'),
    can ? null : h('div', {class: 'note'}, 'Your account can open reviews, not start them. A BI Dev or an owner of your organisation runs them.'),
    drop, list, h('div', {style: 'margin:10px 0 4px'}, pbiRow),
    h('label', {class: 'f'}, 'Name ', h('small', {}, 'optional')), name,
    h('div', {class: 'row', style: 'gap:12px;align-items:center;flex-wrap:wrap;margin-top:12px'}, go, bar),
    h('div', {class: 'hint'}, 'A file is read for its model (measures and their DAX, tables, columns, relationships, which visuals show what) and deleted '
      + 'at once: the data in it is never kept. Several models are also compared with each other.'), out);
}

function dictionaryCard(d) {
  return h('div', {class: 'card'}, h('h3', {}, 'KPI dictionary'),
    h('div', {class: 'credbig'}, String(d.kpis)), h('div', {class: 'muted small', style: 'margin-bottom:10px'}, d.kpis === 1 ? 'KPI defined' : 'KPIs defined'),
    h('p', {class: 'small', style: 'margin:0 0 12px'}, d.kpis ? 'What each KPI means, how it is calculated, and the other names people use for it. Every review checks your models against it.'
      : 'No KPIs yet. A review still compares your models with themselves (the same name, the same number). Add your KPI definitions, import the file you keep them in, '
        + 'or start the dictionary from a review.'),
    h('div', {class: 'row', style: 'gap:8px;flex-wrap:wrap'},
      h('a', {class: 'btn primary', href: '#/review/kpis'}, icon('book'), d.kpis ? 'Open the dictionary' : 'Add KPIs'),
      d.can.edit ? h('button', {class: 'btn', type: 'button', onclick: () => kpiImportDialog(() => renderReviewHome())}, icon('publish'), 'Import a file') : null,
      h('a', {class: 'btn ghost', href: '/api/semreview/kpis/template.csv'}, icon('download'), 'Template')));
}

/* ---------------- Power BI: the organisation's own Entra app ---------------- */
function pbiDialog(cur) {
  const tenant = h('input', {type: 'text', value: cur.tenant || '', placeholder: 'contoso.onmicrosoft.com or the tenant id', autocomplete: 'off'});
  const client = h('input', {type: 'text', value: '', placeholder: cur.configured ? `${cur.client_id} (enter it again to change it)` : 'Application (client) id', autocomplete: 'off'});
  const secret = h('input', {type: 'password', value: '', placeholder: cur.has_secret ? 'Kept - enter a new one to change it' : 'Client secret value', autocomplete: 'new-password'});
  const out = h('div', {role: 'status'});
  const save = h('button', {class: 'btn primary', type: 'button'}, 'Save');
  const test = h('button', {class: 'btn', type: 'button', hidden: !cur.configured}, 'Test the connection');
  const remove = h('button', {class: 'btn danger', type: 'button', hidden: !cur.configured}, 'Remove');
  save.onclick = async () => {
    if (!client.value.trim() && cur.configured) return out.replaceChildren(h('div', {class: 'note warn'}, 'Enter the client id again to save a change.'));
    save.disabled = true;
    try {
      const r = await api('/api/semreview/pbi', {method: 'PUT', json: {tenant: tenant.value.trim(), client_id: client.value.trim(), client_secret: secret.value.trim() || null}});
      Object.assign(cur, r); secret.value = ''; test.hidden = false; remove.hidden = false;
      out.replaceChildren(h('div', {class: 'note ok'}, 'Saved. Test the connection to make sure Microsoft accepts the app.'));
    } catch (e) { out.replaceChildren(h('div', {class: 'note err'}, e.message)); }
    save.disabled = false;
  };
  test.onclick = async () => {
    test.disabled = true; out.replaceChildren(h('div', {class: 'note'}, 'Asking Microsoft...'));
    try { const r = await api('/api/semreview/pbi/test', {method: 'POST'});
      out.replaceChildren(h('div', {class: 'note ok'}, `Connected: the app sees ${r.workspaces} workspace${r.workspaces === 1 ? '' : 's'}.`));
    } catch (e) { out.replaceChildren(h('div', {class: 'note err'}, e.message)); }
    test.disabled = false;
  };
  remove.onclick = async () => {
    if (!confirm('Remove the Power BI connection? Reviews already made stay.')) return;
    try { await api('/api/semreview/pbi', {method: 'DELETE'}); notify('Power BI connection removed', 'ok'); renderReviewHome(); $('.modal') && $('.modal').remove(); }
    catch (e) { out.replaceChildren(h('div', {class: 'note err'}, e.message)); }
  };
  modal('Connect Power BI (Azure)', h('div', {class: 'mbody'},
    h('p', {style: 'margin-top:0'}, 'D2D Relay reads your semantic models from the Power BI service with an app of your own in Microsoft Entra ID. It only reads.'),
    h('ol', {class: 'small srsteps'},
      h('li', {}, 'In Microsoft Entra ID, register an app (App registrations) and add a client secret.'),
      h('li', {}, 'In the Fabric admin portal (Developer settings), allow service principals to use Fabric APIs, and the Execute queries REST API.'),
      h('li', {}, 'In each workspace to review, add the app as Contributor. Power BI shows a model\'s DAX only to identities that may change the model.')),
    h('label', {class: 'f'}, 'Tenant'), tenant,
    h('label', {class: 'f'}, 'Client id'), client,
    h('label', {class: 'f'}, 'Client secret'), secret,
    h('div', {class: 'hint'}, 'The secret is kept encrypted and never shown again.'), out,
    h('div', {class: 'row', style: 'justify-content:space-between;gap:8px;margin-top:12px;flex-wrap:wrap'}, remove,
      h('span', {class: 'row', style: 'gap:8px'}, test, save))));
}

async function pickModels(after) {
  const body = h('div', {class: 'mbody'}, h('div', {class: 'muted'}, 'Loading your workspaces...'));
  const m = modal('Pick models from Power BI', body);
  let ws;
  try { ws = (await api('/api/semreview/pbi/workspaces')).workspaces; } catch (e) { return body.replaceChildren(h('div', {class: 'note err'}, e.message)); }
  if (!ws.length) return body.replaceChildren(h('div', {class: 'note warn'}, 'The app sees no workspace. Add it to the workspaces to review (Contributor).'));
  const sel = h('select', {class: 'sel'}, h('option', {value: ''}, 'Choose a workspace'), ws.map(w => h('option', {value: w.id}, w.name)));
  const list = h('div', {class: 'srpick'});
  const out = h('div', {role: 'status'});
  const picked = new Map(SR.picks.map(p => [p.model, p]));
  sel.onchange = async () => {
    const w = ws.find(x => x.id === sel.value);
    if (!w) return list.replaceChildren();
    list.replaceChildren(h('div', {class: 'muted small'}, 'Loading its semantic models...'));
    try {
      const ms = (await api(`/api/semreview/pbi/workspaces/${w.id}/models`)).models;
      list.replaceChildren(...(ms.length ? ms.map(md => {
        const cb = h('input', {type: 'checkbox', checked: picked.has(md.id)});
        cb.onchange = () => { if (cb.checked) picked.set(md.id, {workspace: w.id, model: md.id, name: md.name, workspace_name: w.name}); else picked.delete(md.id); };
        return h('label', {class: 'chk'}, cb, h('span', {}, md.name, md.description ? h('small', {class: 'muted'}, ' - ' + md.description) : null));
      }) : [h('div', {class: 'muted small'}, 'No semantic models in this workspace.')]));
    } catch (e) { list.replaceChildren(h('div', {class: 'note err'}, e.message)); }
  };
  const ok = h('button', {class: 'btn primary', type: 'button'}, 'Add to the review');
  ok.onclick = () => {
    const lim = (SR.data || {}).limits || {files: 5};
    const all = [...picked.values()];
    if (all.length + SR.files.length > lim.files) return out.replaceChildren(h('div', {class: 'note warn'}, `A review reads up to ${lim.files} models.`));
    SR.picks = all; after(); m.remove();
  };
  body.replaceChildren(h('label', {class: 'f', style: 'margin-top:0'}, 'Workspace'), sel, h('label', {class: 'f'}, 'Semantic models'), list, out,
    h('div', {class: 'row', style: 'justify-content:flex-end;margin-top:12px'}, ok));
}

/* ---------------- the KPI dictionary ---------------- */
async function renderKpiDictionary() {
  document.title = 'KPI dictionary - D2D Relay';
  const page = h('div', {class: 'page'});
  $('#main').replaceChildren(page);
  let d, ov;
  try { [d, ov] = await Promise.all([api('/api/semreview/kpis'), api('/api/semreview')]); } catch (e) { return page.append(h('div', {class: 'note err'}, e.message)); }
  const can = ov.can.edit;
  const search = h('input', {type: 'search', placeholder: 'Find a KPI', value: SR.kq, 'aria-label': 'Find a KPI', class: 'srsearch'});
  const body = h('tbody');
  const draw = () => {
    const q = search.value.trim().toLowerCase(); SR.kq = q;
    const rows = d.kpis.filter(k => !q || [k.name, ...(k.synonyms || []), k.definition, k.domain].join(' ').toLowerCase().includes(q));
    body.replaceChildren(...(rows.length ? rows.map(k => h('tr', {},
      h('td', {}, h('b', {}, k.name), k.domain ? h('div', {class: 'small muted'}, k.domain) : null),
      h('td', {class: 'small'}, (k.synonyms || []).join(', ')),
      h('td', {class: 'small'}, k.definition || h('span', {class: 'muted'}, '-'), k.formula ? h('div', {class: 'muted'}, 'Formula: ' + k.formula) : null),
      h('td', {class: 'small'}, [k.unit, k.aggregation && k.aggregation.replace('_', ' '), k.year_end && k.year_end !== '12-31' ? `year ends ${k.year_end}` : null].filter(Boolean).join(', ') || '-'),
      h('td', {class: 'small'}, k.dax ? h('code', {class: 'srcode', title: k.dax}, k.dax.length > 60 ? k.dax.slice(0, 57) + '...' : k.dax) : h('span', {class: 'muted'}, 'none')),
      h('td', {class: 'l', style: 'white-space:nowrap'}, can ? [
        h('button', {class: 'btn sm', type: 'button', onclick: () => kpiDialog(k, d, renderKpiDictionary)}, icon('edit'), 'Edit'),
        h('button', {class: 'btn sm ghost danger', type: 'button', 'aria-label': `Delete ${k.name}`, onclick: async () => {
          if (!confirm(`Delete ${k.name} from the dictionary?`)) return;
          try { await api(`/api/semreview/kpis/${k.id}`, {method: 'DELETE'}); renderKpiDictionary(); } catch (e) { notify(e.message, 'err'); }
        }}, icon('x'))] : null)))
      : [h('tr', {}, h('td', {colspan: 6, class: 'muted', style: 'text-align:center;padding:24px'}, d.kpis.length ? 'No KPI matches.' : 'No KPIs yet.'))]));
  };
  search.oninput = draw;
  page.append(
    h('div', {class: 'crumbs'}, h('a', {href: '#/review'}, 'Semantic Review'), icon('chevr'), 'KPI dictionary'),
    h('h1', {}, 'KPI dictionary'),
    h('p', {class: 'muted lead'}, 'What each KPI means and how it is calculated, with the other names people use for it. Every review checks your models '
      + 'against it. One name stands for one KPI: a name or other name can belong to one KPI only.'),
    h('div', {class: 'row', style: 'gap:8px;flex-wrap:wrap;margin:6px 0 14px;align-items:center'},
      can ? h('button', {class: 'btn primary', type: 'button', onclick: () => kpiDialog(null, d, renderKpiDictionary)}, icon('plus'), 'Add a KPI') : null,
      can ? h('button', {class: 'btn', type: 'button', onclick: () => kpiImportDialog(renderKpiDictionary)}, icon('publish'), 'Import a file') : null,
      h('a', {class: 'btn ghost', href: '/api/semreview/kpis/export.csv'}, icon('download'), 'CSV'),
      h('a', {class: 'btn ghost', href: '/api/semreview/kpis/export.yaml'}, icon('download'), 'YAML'),
      h('a', {class: 'btn ghost', href: '/api/semreview/kpis/template.csv'}, icon('file'), 'Template'),
      h('span', {class: 'grow'}), search),
    can ? null : h('div', {class: 'note'}, 'Your account can read the dictionary. A BI Dev or an owner of your organisation changes it.'),
    h('div', {class: 'card orgwrap', style: 'padding:6px 10px'}, h('table', {class: 'utable srtable'},
      h('thead', {}, h('tr', {}, ['KPI', 'Other names', 'Definition', 'Unit and rules', 'Reference DAX', ''].map(t => h('th', {class: 'l'}, t)))), body)));
  draw();
}

function kpiDialog(k, d, after) {
  k = k || {};
  const f = (label, el, hint) => [h('label', {class: 'f'}, label), el, hint ? h('div', {class: 'hint'}, hint) : null];
  const name = h('input', {type: 'text', value: k.name || '', maxlength: 120});
  const syn = h('input', {type: 'text', value: (k.synonyms || []).join(', '), placeholder: 'For example: Net Sales, Turnover'});
  const def = h('textarea', {rows: 2, placeholder: 'What the number means, in business words'}, k.definition || '');
  const formula = h('textarea', {rows: 2, placeholder: 'For example: (Revenue - Cost of goods sold) / Revenue'}, k.formula || '');
  const dax = h('textarea', {rows: 3, class: 'mono', placeholder: 'For example: DIVIDE ( [Revenue] - [COGS], [Revenue] )', spellcheck: 'false'}, k.dax || '');
  const opts = (list, cur, none) => [h('option', {value: ''}, none), ...list.map(v => h('option', {value: v, selected: v === cur}, v.replace('_', ' ')))];
  const unit = h('select', {class: 'sel'}, opts(d.units, k.unit, 'Not set'));
  const agg = h('select', {class: 'sel'}, opts(d.aggregations, k.aggregation, 'Not set'));
  const filters = h('textarea', {rows: 2, placeholder: 'One per line, for example: Status = Completed'}, (k.filters || []).join('\n'));
  const time = h('input', {type: 'text', value: k.time || '', placeholder: 'For example: fiscal year ending 31 March, or calendar year'});
  const owner = h('input', {type: 'text', value: k.owner || '', maxlength: 120});
  const domain = h('input', {type: 'text', value: k.domain || '', maxlength: 120});
  const out = h('div', {role: 'status'});
  const save = h('button', {class: 'btn primary', type: 'button'}, k.id ? 'Save' : 'Add');
  save.onclick = async () => {
    const body = {name: name.value, synonyms: syn.value, definition: def.value, formula: formula.value, dax: dax.value, unit: unit.value, aggregation: agg.value,
      filters: filters.value.split('\n').map(x => x.trim()).filter(Boolean), time: time.value, owner: owner.value, domain: domain.value};
    save.disabled = true;
    try {
      await api(k.id ? `/api/semreview/kpis/${k.id}` : '/api/semreview/kpis', {method: k.id ? 'PUT' : 'POST', json: body});
      mm.remove(); notify(k.id ? 'KPI saved' : 'KPI added', 'ok'); after();
    } catch (e) { out.replaceChildren(h('div', {class: 'note err'}, e.message)); save.disabled = false; }
  };
  const mm = modal(k.id ? `Edit ${k.name}` : 'Add a KPI', h('div', {class: 'mbody'},
    f('KPI', name), f('Other names', syn, 'Names that mean this same KPI, separated by commas. The review holds every measure with one of these names to this definition.'),
    f('Definition', def), f('Formula in words', formula, 'Optional. Relay\'s AI checks each measure against the definition and this formula.'),
    f('Reference DAX', dax, 'Optional. Refer to other KPIs by [name]. Measures that compute something else are flagged.'),
    h('div', {class: 'grid2'}, h('div', {}, f('Unit', unit)), h('div', {}, f('Aggregation', agg))),
    f('Rules that are part of the meaning', filters), f('Time basis', time),
    h('div', {class: 'grid2'}, h('div', {}, f('Owner', owner)), h('div', {}, f('Domain', domain))), out,
    h('div', {class: 'row', style: 'justify-content:flex-end;margin-top:12px'}, save)));
}

function kpiImportDialog(after) {
  const file = h('input', {type: 'file', accept: '.csv,.xlsx,.xlsm,.yaml,.yml,.json,.txt,.tsv'});
  const merge = h('input', {type: 'radio', name: 'srmode', value: 'merge', checked: true});
  const replace = h('input', {type: 'radio', name: 'srmode', value: 'replace'});
  const out = h('div', {role: 'status'});
  const check = h('button', {class: 'btn', type: 'button'}, 'Check the file');
  const apply = h('button', {class: 'btn primary', type: 'button', hidden: true}, 'Apply');
  const send = async (doApply) => {
    if (!file.files[0]) return out.replaceChildren(h('div', {class: 'note warn'}, 'Choose a file first.'));
    const fd = new FormData();
    fd.append('file', file.files[0]); fd.append('mode', replace.checked ? 'replace' : 'merge'); fd.append('apply', doApply ? '1' : '0');
    return upload('/api/semreview/kpis/import', fd);
  };
  const names = (label, xs) => xs.length ? h('div', {class: 'small'}, h('b', {}, `${label} (${xs.length}): `), xs.slice(0, 30).join(', ') + (xs.length > 30 ? ' and more' : '')) : null;
  check.onclick = async () => {
    check.disabled = true;
    try {
      const r = await send(false);
      out.replaceChildren(h('div', {class: 'note'}, h('div', {}, `Read ${r.read} KPI${r.read === 1 ? '' : 's'} from the file.`),
        names('New', r.added), names('Changed', r.updated), r.unchanged ? h('div', {class: 'small'}, `${r.unchanged} unchanged.`) : null,
        names('Removed from the dictionary', r.removed)),
        r.problems.length ? h('div', {class: 'note warn'}, h('b', {}, 'Left out:'), h('ul', {}, r.problems.slice(0, 12).map(p => h('li', {}, p)))) : null);
      apply.hidden = !(r.added.length || r.updated.length || r.removed.length);
    } catch (e) { out.replaceChildren(h('div', {class: 'note err'}, e.message)); }
    check.disabled = false;
  };
  apply.onclick = async () => {
    apply.disabled = true;
    try { const r = await send(true); mm.remove(); notify(`Dictionary updated: ${r.added.length} new, ${r.updated.length} changed` + (r.removed.length ? `, ${r.removed.length} removed` : ''), 'ok'); after(); }
    catch (e) { out.replaceChildren(h('div', {class: 'note err'}, e.message)); apply.disabled = false; }
  };
  file.onchange = () => { apply.hidden = true; out.replaceChildren(); };
  const mm = modal('Import a KPI dictionary', h('div', {class: 'mbody'},
    h('p', {style: 'margin-top:0'}, 'A CSV or Excel file with one row per KPI and a header row (the usual titles are understood: KPI, Name, Metric, Definition, '
      + 'Description, Formula, Calculation, DAX, Synonyms, Aliases, Unit, Aggregation, Filters, Time, Owner, Domain), or a YAML or JSON list.'),
    h('a', {href: '/api/semreview/kpis/template.csv'}, icon('download'), ' Download a template'),
    h('label', {class: 'f'}, 'File'), file,
    h('label', {class: 'f'}, 'How'), h('label', {class: 'chk'}, merge, h('span', {}, 'Add to the dictionary (KPIs with the same name are updated)')),
    h('label', {class: 'chk'}, replace, h('span', {}, 'Replace the dictionary with the file')), out,
    h('div', {class: 'row', style: 'justify-content:flex-end;gap:8px;margin-top:12px'}, check, apply)));
}

/* ---------------- one review ---------------- */
async function renderReviewRun(rid) {
  const main = $('#main');
  let r;
  try { r = await api(`/api/semreview/runs/${rid}`); }
  catch (e) { return main.replaceChildren(h('div', {class: 'page'}, h('div', {class: 'card empty'}, h('h3', {}, 'Review not found'), h('a', {href: '#/review'}, 'Back to Semantic Review')))); }
  if (!location.hash.startsWith(`#/review/${rid}`)) return;
  document.title = `${r.name} - Semantic Review - D2D Relay`;
  const page = h('div', {class: 'page wide'});
  const actions = h('div', {class: 'row', style: 'gap:8px;flex-wrap:wrap'},
    r.status === 'done' ? h('a', {class: 'btn', href: `/api/semreview/runs/${rid}/findings.csv`}, icon('download'), 'Findings (CSV)') : null,
    r.status === 'done' && r.can_run ? h('button', {class: 'btn', type: 'button', title: "The same models against today's KPI dictionary", onclick: async e => {
      e.currentTarget.disabled = true;
      try { const x = await api(`/api/semreview/runs/${rid}/again`, {method: 'POST'}); if (typeof refreshOrg === 'function') refreshOrg(true); location.hash = `#/review/${x.id}`; }
      catch (err) { notify(err.message, 'err'); e.target.disabled = false; }
    }}, icon('play'), 'Review again', h('span', {class: 'cost'}, ' - ' + srCost(r.cost))) : null,
    r.can_delete && ['done', 'error'].includes(r.status) ? h('button', {class: 'btn ghost danger', type: 'button', onclick: async () => {
      if (!confirm(`Delete the review "${r.name}"? Its findings and the models it read go with it.`)) return;
      try { await api(`/api/semreview/runs/${rid}`, {method: 'DELETE'}); location.hash = '#/review'; } catch (e) { notify(e.message, 'err'); }
    }}, icon('x'), 'Delete') : null);
  page.append(h('div', {class: 'crumbs'}, h('a', {href: '#/review'}, 'Semantic Review'), icon('chevr'), r.name),
    h('div', {class: 'phead'}, h('div', {class: 'grow'}, h('h1', {style: 'margin:0'}, r.name),
      h('div', {class: 'meta'}, srPill(r.status, null), ` ${r.by || 'Former member'} - ${when(r.created)} - `,
        r.sources.map(s => s.file || (s.name + ' (Power BI)')).join(', '))), actions));
  if (r.status === 'error') page.append(h('div', {class: 'note err'}, r.error || 'The review did not finish.'), h('a', {href: '#/review'}, 'Start a new review'));
  else if (r.status !== 'done' && r.status !== 'meaning') page.append(h('div', {class: 'card srwait'}, h('div', {class: 'spin'}), h('div', {}, h('b', {}, r.step || 'Starting'),
    h('div', {class: 'small muted'}, 'This takes from a few seconds to a few minutes. You can leave this page; the review keeps going.'))));
  else if (r.result) page.append(...reviewReport(r));
  else page.append(h('div', {class: 'card srwait'}, h('div', {class: 'spin'}), h('b', {}, r.step || 'Working')));
  main.replaceChildren(page);
  if (!['done', 'error'].includes(r.status)) SR.timer = setTimeout(() => { if (location.hash.startsWith(`#/review/${rid}`)) renderReviewRun(rid); }, 2000);
}

function reviewReport(r) {
  const res = r.result, s = res.summary, f = s.findings || {}, out = [];
  out.push(h('div', {class: 'stats'},
    h('div', {class: 'stat' + (s.kpis_conflicting || s.kpis_differing ? ' bad' : '')}, h('b', {}, s.score != null ? `${s.kpis_consistent} of ${s.kpis_checked}` : '-'),
      h('span', {}, s.score != null ? 'KPIs with one meaning' : 'No KPIs to compare yet')),
    h('div', {class: 'stat' + (f.high ? ' bad' : '')}, h('b', {}, String(f.high || 0)), h('span', {}, 'High findings')),
    h('div', {class: 'stat'}, h('b', {}, String((f.medium || 0) + (f.low || 0))), h('span', {}, 'Medium and low')),
    h('div', {class: 'stat'}, h('b', {}, String(s.measures)), h('span', {}, `Measures in ${s.models} model${s.models === 1 ? '' : 's'}`)),
    h('div', {class: 'stat'}, h('b', {}, String(s.kpis_defined)), h('span', {}, 'KPIs in the dictionary used'))));
  const ai = r.ai || {};
  if (r.status === 'meaning') out.push(h('div', {class: 'note'}, h('span', {class: 'spin sm'}), " Relay's AI is checking what each KPI means..."));
  else if (ai.ran === false && !ai.skipped) out.push(h('div', {class: 'note warn'}, `The meaning check by Relay's AI could not run (${String(ai.why || 'no answer').replace(/[.\s]+$/, '')}). Everything else in this review is complete. `,
    ai.can_retry && (ai.tries || 1) < 2 && r.can_run ? h('button', {class: 'btn sm', type: 'button', onclick: async e => {
      e.currentTarget.disabled = true;
      try { await api(`/api/semreview/runs/${r.id}/meaning`, {method: 'POST'}); renderReviewRun(r.id); } catch (err) { notify(err.message, 'err'); }
    }}, 'Check meaning again (no credits)') : null));
  else if (ai.skipped) out.push(h('div', {class: 'note'}, ai.why + ' ', h('a', {href: '#/review/kpis'}, 'Add definitions'), ' and Relay\'s AI also checks what each KPI means.'));
  else if (ai.ran) out.push(h('div', {class: 'small muted', style: 'margin:-8px 0 12px'}, "Relay's AI checked the measures against your definitions in words"
    + (ai.matched ? ` and placed ${ai.matched} measure${ai.matched === 1 ? '' : 's'} in no KPI` : '') + (ai.partial ? ' (part of the KPIs only)' : '') + '.'));
  (res.notes || []).forEach(n => out.push(h('div', {class: 'note warn'}, n)));
  const tabs = [['findings', `Findings (${res.findings.length})`], ['kpis', `KPIs (${res.kpis.length})`], ['measures', `Measures (${res.measures.length})`], ['models', 'Models']];
  const body = h('div');
  const bar = h('div', {class: 'tabs', role: 'tablist'});
  const draw = () => {
    bar.replaceChildren(...tabs.map(([k, t]) => h('a', {href: '#', role: 'tab', 'aria-selected': String(SR.tab === k), class: SR.tab === k ? 'on' : '',
      onclick: e => { e.preventDefault(); SR.tab = k; draw(); }}, t)));
    body.replaceChildren(SR.tab === 'kpis' ? kpiTab(res) : SR.tab === 'measures' ? measuresTab(r) : SR.tab === 'models' ? modelsTab(res) : findingsTab(res));
  };
  if (!tabs.some(([k]) => k === SR.tab)) SR.tab = 'findings';
  draw();
  out.push(bar, body);
  return out;
}

function findingsTab(res) {
  const wrap = h('div');
  const counts = {all: res.findings.length};
  res.findings.forEach(x => { counts[x.severity] = (counts[x.severity] || 0) + 1; });
  const search = h('input', {type: 'search', placeholder: 'Find in findings (a KPI, a measure, a word)', value: SR.q, class: 'srsearch', 'aria-label': 'Find in findings'});
  const list = h('div');
  const chips = h('div', {class: 'chips', role: 'group', 'aria-label': 'Severity'});
  const draw = () => {
    chips.replaceChildren(...['all', 'high', 'medium', 'low', 'info'].filter(k => k === 'all' || counts[k]).map(k => h('button', {type: 'button',
      class: 'chip' + (SR.sev === k ? ' on' : ''), 'aria-pressed': String(SR.sev === k), onclick: () => { SR.sev = k; draw(); }},
      (k === 'all' ? 'All' : SR_SEV[k][0]) + ` (${counts[k] || 0})`)));
    const q = search.value.trim().toLowerCase(); SR.q = q;
    const rows = res.findings.filter(x => (SR.sev === 'all' || x.severity === SR.sev)
      && (!q || [x.title, x.detail, x.kpi, ...(x.measures || []).map(m => m.name)].join(' ').toLowerCase().includes(q)));
    list.replaceChildren(...(rows.length ? rows.map(findingCard) : [h('div', {class: 'card empty'}, res.findings.length ? 'No finding matches.' : h('div', {}, h('h3', {}, 'Nothing to fix'), 'Every measure was read and no rule found a problem.'))]));
  };
  search.oninput = draw;
  draw();
  wrap.append(h('div', {class: 'row', style: 'gap:10px;flex-wrap:wrap;align-items:center;margin-bottom:12px'}, chips, h('span', {class: 'grow'}), search), list);
  return wrap;
}

function findingCard(x) {
  const dax = (x.dax || []).filter(Boolean);
  const more = h('div', {hidden: true}, dax.map(t => h('pre', {class: 'srdax'}, t)));
  return h('div', {class: 'card srfind sev-' + x.severity},
    h('div', {class: 'row', style: 'gap:8px;align-items:center;flex-wrap:wrap'}, srTag(x.severity), h('span', {class: 'tag'}, SR_RULES[x.rule] || x.rule),
      x.kpi ? h('span', {class: 'tag acc'}, x.kpi) : null, x.source === 'ai' ? h('span', {class: 'tag', title: "Found by Relay's AI from your definitions"}, icon('spark'), "Relay's AI") : null),
    h('h3', {style: 'margin:8px 0 4px'}, x.title),
    h('p', {style: 'margin:0 0 8px'}, x.detail),
    x.measures && x.measures.length ? h('div', {class: 'flist'}, x.measures.map(m => h('span', {}, icon('code'), ` [${m.name}]`,
      h('small', {class: 'muted'}, ` ${m.table ? m.table + ', ' : ''}${m.model_name || ''}`)))) : null,
    x.fix || x.fix_dax ? h('div', {class: 'srfix'}, h('div', {class: 'row', style: 'gap:8px;align-items:center'}, h('b', {class: 'small'}, 'What to do'),
        h('span', {class: 'grow'}), x.fix_dax ? copyBtn(x.fix_dax) : null),
      x.fix ? h('div', {class: 'small'}, x.fix) : null, x.fix_dax ? h('pre', {class: 'srdax'}, x.fix_dax) : null) : null,
    dax.length ? h('button', {class: 'btn ghost sm', type: 'button', 'aria-expanded': 'false', onclick: e => {
      more.hidden = !more.hidden; e.currentTarget.setAttribute('aria-expanded', String(!more.hidden));
      e.currentTarget.lastChild.textContent = more.hidden ? 'Show the DAX' : 'Hide the DAX';
    }}, icon('code'), 'Show the DAX') : null, more);
}

function kpiTab(res) {
  if (!res.kpis.length) return h('div', {class: 'card empty'}, h('h3', {}, 'No KPIs to compare'), h('div', {}, 'Add KPIs to the dictionary, or review several models with the same measures.'));
  const values = !!res.values;
  return h('div', {class: 'card orgwrap', style: 'padding:6px 10px'}, h('table', {class: 'utable srtable'},
    h('thead', {}, h('tr', {}, ['KPI', 'Status', 'Measures found', values ? 'Value (no filters)' : null, 'Findings'].filter(Boolean).map(t => h('th', {class: 'l'}, t)))),
    h('tbody', {}, res.kpis.map(k => {
      const [st, c] = SR_KPI[k.status] || [k.status, ''];
      const impl = k.implementations.length ? k.implementations : null;
      return h('tr', {},
        h('td', {}, h('b', {}, k.name), k.defined ? null : h('div', {class: 'small muted'}, 'Same name in your models (not in the dictionary)')),
        h('td', {}, h('span', {class: 'pill ' + c}, st), k.versions > 1 ? h('div', {class: 'small muted'}, `${k.versions} different calculations`) : null),
        h('td', {class: 'small'}, impl ? impl.map(i => h('div', {}, k.versions > 1 && i.version ? h('span', {class: 'tag srv'}, `v${i.version}`) : null, ` [${i.measure}]`,
          h('span', {class: 'muted'}, ` ${i.model_name}${i.how && i.how !== 'name' ? ' - ' + (SR_HOW[i.how] || i.how) : ''}${i.error ? ' - cannot be read' : ''}`)))
          : h('span', {class: 'muted'}, k.variants && k.variants.length ? 'Variants: ' + k.variants.map(v => v.measure).join(', ') : 'None'),
          impl && k.variants && k.variants.length ? h('div', {class: 'muted'}, `and ${k.variants.length} variant${k.variants.length === 1 ? '' : 's'} (${k.variants.slice(0, 3).map(v => v.measure).join(', ')}${k.variants.length > 3 ? '...' : ''})`) : null),
        values ? h('td', {class: 'small v'}, impl ? impl.map(i => h('div', {}, i.value !== undefined ? srNum(i.value) : i.value_error ? 'error' : '-')) : '-') : null,
        h('td', {}, k.findings.length ? h('a', {href: '#', onclick: e => { e.preventDefault(); SR.tab = 'findings'; SR.sev = 'all'; SR.q = k.name.toLowerCase(); renderReviewRun(location.hash.split('/')[2]); }},
          `${k.findings.length} finding${k.findings.length === 1 ? '' : 's'}`) : h('span', {class: 'muted'}, '-')));
    }))));
}

function measuresTab(r) {
  const res = r.result, ms = res.measures;
  const search = h('input', {type: 'search', placeholder: 'Find a measure', value: SR.mq, class: 'srsearch', 'aria-label': 'Find a measure'});
  const body = h('tbody');
  const out = h('div', {role: 'status'});
  const addBtn = h('button', {class: 'btn', type: 'button', disabled: true}, icon('book'), 'Add to the KPI dictionary');
  const canAdd = r.can_run;
  SR.sel = new Set([...SR.sel].filter(id => ms.some(m => m.id === id)));
  const sync = () => { addBtn.disabled = !SR.sel.size; addBtn.lastChild.textContent = SR.sel.size ? `Add ${SR.sel.size} to the KPI dictionary` : 'Add to the KPI dictionary'; };
  addBtn.onclick = async () => {
    addBtn.disabled = true;
    try {
      const x = await api('/api/semreview/kpis/from-run', {json: {run: r.id, measures: [...SR.sel]}});
      SR.sel.clear();
      out.replaceChildren(h('div', {class: 'note ok'}, `Added to the dictionary: ${x.added.join(', ') || 'none'}.` + (x.skipped.length ? ` Left out (already there): ${x.skipped.join(', ')}.` : '')
        + ' Review again to check your models against it.'));
    } catch (e) { out.replaceChildren(h('div', {class: 'note err'}, e.message)); }
    sync(); draw();
  };
  const draw = () => {
    const q = search.value.trim().toLowerCase(); SR.mq = q;
    const rows = ms.filter(m => !q || [m.name, m.table, m.kpi, m.folder].join(' ').toLowerCase().includes(q)).slice(0, 1000);
    body.replaceChildren(...rows.map(m => {
      const cb = canAdd && !m.defined ? h('input', {type: 'checkbox', checked: SR.sel.has(m.id), 'aria-label': `Pick ${m.name}`,
        onchange: e => { if (e.target.checked) SR.sel.add(m.id); else SR.sel.delete(m.id); sync(); }}) : null;
      const dax = h('pre', {class: 'srdax', hidden: true}, m.dax || '');
      return h('tr', {}, canAdd ? h('td', {}, cb) : null,
        h('td', {}, h('a', {href: '#', onclick: e => { e.preventDefault(); dax.hidden = !dax.hidden; }}, m.name), m.error ? h('div', {class: 'small', style: 'color:var(--err)'}, 'Cannot be read: ' + m.error) : null, dax),
        h('td', {class: 'small'}, m.table || ''), h('td', {class: 'small'}, (res.models[m.model] || {}).name || ''),
        h('td', {class: 'small'}, m.kpi ? [h('span', {class: 'tag acc'}, m.kpi), ' ', h('span', {class: 'muted'}, m.how === 'variant' ? `variant${m.variant ? ' (' + m.variant + ')' : ''}` : SR_HOW[m.how] || '')] : h('span', {class: 'muted'}, '-')),
        h('td', {class: 'n'}, m.shows ? String(m.shows) : '-'), h('td', {class: 'small mono'}, m.format || ''));
    }));
  };
  search.oninput = draw;
  draw(); sync();
  return h('div', {}, h('div', {class: 'row', style: 'gap:10px;flex-wrap:wrap;align-items:center;margin-bottom:12px'},
      canAdd ? addBtn : null, canAdd ? h('span', {class: 'small muted'}, 'Pick the measures that are your KPIs to start (or grow) the dictionary.') : null, h('span', {class: 'grow'}), search), out,
    h('div', {class: 'card orgwrap', style: 'padding:6px 10px'}, h('table', {class: 'utable srtable'},
      h('thead', {}, h('tr', {}, [canAdd ? '' : null, 'Measure', 'Table', 'Model', 'KPI', 'In visuals', 'Format'].filter(x => x !== null).map(t => h('th', {class: 'l'}, t)))), body)));
}

function modelsTab(res) {
  const kind = {pbix: 'Power BI file (.pbix)', pbit: 'Power BI template (.pbit)', bim: 'model.bim', pbip: 'Power BI project', powerbi: 'Power BI service'};
  return h('div', {class: 'srmodels'}, res.models.map(m => h('div', {class: 'card'}, h('h3', {}, m.name || 'Model'),
    h('dl', {class: 'kv'}, h('dt', {}, 'Source'), h('dd', {}, kind[(m.source || {}).kind] || (m.source || {}).kind || ''),
      h('dt', {}, 'Tables'), h('dd', {}, String(m.tables)), h('dt', {}, 'Measures'), h('dd', {}, String(m.measures)),
      h('dt', {}, 'Relationships'), h('dd', {}, String(m.relationships)),
      m.pages != null ? [h('dt', {}, 'Report'), h('dd', {}, `${m.pages} page${m.pages === 1 ? '' : 's'}, ${m.visuals} visual${m.visuals === 1 ? '' : 's'} with fields`)] : null))));
}
