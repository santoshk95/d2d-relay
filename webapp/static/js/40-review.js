/* ---------------- D2D Relay: Semantic Review (#/review, item 55). Power BI semantic models checked against the
   organisation's KPI dictionary: one KPI, one meaning, one value (webapp/app/semreview.py, genbi_kit/semreview).
   A guided flow (the user, 2026-11-19: "a guided way rather than all visible and one step is done then the next shows"):
   #/review          New review, one step at a time: 1 Your KPIs, 2 Your models, 3 Check and start; Reviews: the list
   #/review/kpis     the KPI dictionary: add, edit, import (CSV, Excel, YAML, JSON), download (also #/ontology/kpis)
   #/review/<id>     one review as stages: Read, Check, Meaning, (Values), Findings, Fix, Apply and review again, under
                     "What was configured"; each stage opens what it did. It polls while the review or its fixes run.
   Styles: css/review.css (rv*) on top of org.css (sr*). ---------------- */
ICONS.wand = ICONS.wand || 'M4 20 14 10M14 4v2M14 14v2M18 8h2M8 8H6M17 5l1-1M17 13l1 1M11 5l-1-1';
const SR = {timer: null, sev: 'all', q: '', picks: [], files: [], kq: '', mq: '', sel: new Set(), data: null,
  fix: new Set(), fixMode: false, fixable: new Set(),                 // item 65: findings picked to fix
  step: 1, selfOnly: false, name: '', note: '', home: null,            // the guided start (its models: SR.files, SR.picks)
  rid: null, last: '', view: {}, sub: 'models', group: 'severity', open: new Set(), only: null};   // one review
const SR_FINAL = ['done', 'error'];
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
const SR_STAGE = {read: 'Read', check: 'Check', meaning: 'Meaning', values: 'Values', findings: 'Findings', fix: 'Fix', apply: 'Apply and review again'};
const SR_DOES = {
  read: 'Each model is read for its structure only: measures and their DAX, tables, columns, relationships, and which visuals show which fields. No rows of data.',
  check: 'Every measure is compared with your KPI dictionary and with the other models, and its DAX is checked for numbers that come out wrong or unstable.',
  meaning: "Relay's AI compares each KPI's measures with your definitions in words: the right columns, filters, time basis and aggregation.",
  values: 'For models in the Power BI service: the numbers of the KPIs that disagree, side by side, over the whole model.',
  findings: 'What to change, most important first. Open a finding for its detail, the measures and the DAX to copy.',
  fix: 'Relay writes the fixed DAX for findings in measures. Each fix is checked against the model before it is kept.',
  apply: 'Put the fixes into your model, then review the fixed model to see the findings gone.'};
const srLeave = () => { clearTimeout(SR.timer); SR.timer = null; };
const srTag = (sev) => { const [t, c] = SR_SEV[sev] || [sev, '']; return h('span', {class: 'tag ' + (c === 'err' ? 'srhigh' : c)}, t); };
const srPill = (s, step) => h('span', {class: 'pill ' + (s === 'done' ? 'ok' : s === 'error' ? 'err' : 'run')}, s === 'done' || s === 'error' ? SR_STATUS[s] : (step || SR_STATUS[s] || 'Running'));
const srCost = n => n ? `${n} credits` : '';
const srNum = v => (typeof v === 'number' ? (Math.abs(v) < 10 && v % 1 ? v.toLocaleString(undefined, {maximumFractionDigits: 4}) : v.toLocaleString(undefined, {maximumFractionDigits: 2})) : v == null ? 'blank' : String(v));
const srN = (n, one, many) => `${Number(n || 0).toLocaleString()} ${n === 1 ? one : many || one + 's'}`;
const srDictHref = () => typeof renderOntology === 'function' ? '#/ontology/kpis' : '#/review/kpis';
const srCredits = () => typeof ORG === 'function' && ORG().id ? Number(ORG().credits || 0) : null;
const srFixEach = r => ((r && r.fix_estimate) || {}).each || (typeof costOf === 'function' ? costOf('fix') : 0) || 1;
const srFileKind = name => { const m = /\.([a-z]+)$/i.exec(name || ''); return ({pbix: 'Power BI file', pbit: 'Power BI template', bim: 'model.bim', json: 'model.bim', zip: 'Power BI project'})[m ? m[1].toLowerCase() : ''] || 'File'; };
/* a redraw that keeps the focus on the control with the same id (a chip, a tab, the search box) */
function srKeepFocus(fn) {
  const id = document.activeElement && document.activeElement.id;
  fn();
  if (id) { const el = document.getElementById(id); if (el && el !== document.activeElement) el.focus({preventScroll: true}); }
}

function renderReview() {
  srLeave();
  const m = location.hash.match(/^#\/review(?:\/([^/?]+))?/);
  const sub = m && m[1];
  if (sub === 'kpis') return renderKpiDictionary();
  if (sub) return renderReviewRun(sub);
  return renderReviewHome();
}

/* ---------------- the landing page: New review (guided) and Reviews ---------------- */
async function renderReviewHome() {
  srLeave();
  document.title = 'Semantic Review - D2D Relay';
  const page = h('div', {class: 'page rvhome'});
  $('#main').replaceChildren(page);
  let d, kp = null, onto = null;
  try {   // the dictionary's entries and the industry pack say what step 1 holds; either may be missing
    [d, kp, onto] = await Promise.all([api('/api/semreview'), api('/api/semreview/kpis').catch(() => null), api('/api/ontology').catch(() => null)]);
  } catch (e) { return page.append(h('div', {class: 'note err'}, e.message)); }
  if (location.hash !== '#/review') return;
  SR.data = d;
  const st = {d, kpis: kp && kp.kpis, industry: onto && onto.industry && onto.industry.name ? onto.industry : null, reload: () => renderReviewHome()};
  if (!SR.home) SR.home = d.can.run || !d.runs.length ? 'new' : 'list';
  const tabNew = h('a', {href: '#', role: 'tab', id: 'rvtab-new', 'aria-controls': 'rvhomebody'}, icon('play'), 'New review');
  const tabList = h('a', {href: '#', role: 'tab', id: 'rvtab-list', 'aria-controls': 'rvhomebody'}, icon('clock'), 'Reviews', h('span', {class: 'count'}));
  const body = h('div', {role: 'tabpanel', id: 'rvhomebody'});
  const busyNote = h('div');
  const sync = () => {
    for (const [el, k] of [[tabNew, 'new'], [tabList, 'list']]) {
      el.className = SR.home === k ? 'on' : ''; el.setAttribute('aria-selected', String(SR.home === k)); el.tabIndex = SR.home === k ? 0 : -1;
    }
    const busy = d.runs.filter(x => !SR_FINAL.includes(x.status));
    tabList.lastChild.textContent = String(d.runs.length) + (busy.length ? `, ${busy.length} running` : '');
    body.setAttribute('aria-labelledby', 'rvtab-' + SR.home);
    busyNote.replaceChildren(...(SR.home === 'new' && busy.length ? [h('div', {class: 'note rvbusy'}, h('span', {class: 'spin sm'}),
      h('span', {}, busy.length === 1 ? ' A review is running: ' : ` ${busy.length} reviews are running: `,
        busy.map((x, i) => [i ? ', ' : '', h('a', {href: `#/review/${x.id}`}, x.name), x.step ? h('span', {class: 'muted'}, ` (${x.step})`) : null])))] : []));
  };
  const draw = () => { sync(); body.replaceChildren(SR.home === 'list' ? srReviewsPanel(d) : srGuided(st)); };
  const pick = k => { SR.home = k; draw(); (k === 'new' ? tabNew : tabList).focus(); };
  tabNew.addEventListener('click', e => { e.preventDefault(); pick('new'); });
  tabList.addEventListener('click', e => { e.preventDefault(); pick('list'); });
  const tabs = h('div', {class: 'tabs rvtabs', role: 'tablist', 'aria-label': 'Semantic Review', onkeydown: e => {
    if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') { e.preventDefault(); pick(SR.home === 'new' ? 'list' : 'new'); }
  }}, tabNew, tabList);
  page.append(
    h('div', {class: 'eyebrow'}, 'Semantic Review'),
    h('h1', {}, 'One KPI, one meaning, one value'),
    h('p', {class: 'muted lead'}, 'Check your Power BI semantic models against your KPI dictionary. Relay flags every KPI calculated more than one way '
      + 'or not the way your organisation defined it, and DAX that gives a wrong or unstable number, then helps you fix it.'),
    tabs, busyNote, body);
  draw();
  srHomePoll(d, () => { sync(); if (SR.home === 'list') body.replaceChildren(srReviewsPanel(d)); });
}

/* while a review runs, the list (and the tab's count) follow it; the guided start is left as it is */
function srHomePoll(d, after) {
  clearTimeout(SR.timer); SR.timer = null;
  if (!d.runs.some(x => !SR_FINAL.includes(x.status))) return;
  SR.timer = setTimeout(async () => {
    if (location.hash !== '#/review') return;
    try { const x = await api('/api/semreview'); if (location.hash !== '#/review') return; d.runs = x.runs; after(); } catch (e) { /* the next round */ }
    srHomePoll(d, after);
  }, 3000);
}

function srReviewsPanel(d) {
  return h('div', {}, h('p', {class: 'small muted', style: 'margin:0 0 10px'}, d.runs.length
    ? 'Every review of your organisation, newest first. Open one for its findings, fixes and what it read.' : ''), reviewsTable(d));
}

function reviewsTable(d) {
  if (!d.runs.length) return h('div', {class: 'card empty'}, h('h3', {}, 'No reviews yet'), h('div', {}, 'Start one under New review: your KPIs, your models, then check and start.'));
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

/* ---------------- the guided start: 1 Your KPIs, 2 Your models, 3 Check and start ---------------- */
function srGuided(st) {
  const d = st.d;
  if (!d.can.run) return h('div', {class: 'rvwiz'},
    h('div', {class: 'note'}, 'Your account can open reviews, not start them. A BI Dev or an owner of your organisation runs them.'),
    h('div', {class: 'card rvcard'}, ...srStepKpis(st, null, null)));
  const gate = typeof setupNotice === 'function' ? setupNotice('review', st.reload) : null;   // item 81: the organisation setup comes first (47-setup.js)
  if (gate) return h('div', {class: 'rvwiz'}, gate);
  const box = h('div', {class: 'rvwiz'});
  const msg = h('div', {class: 'rvmsg', role: 'status', 'aria-live': 'polite'});
  const say = (text, kind) => msg.replaceChildren(...(text ? [h('div', {class: 'note ' + (kind || '')}, text)] : []));
  const total = () => SR.files.length + SR.picks.length;
  const ok = [null, () => d.kpis > 0 || SR.selfOnly, () => total() > 0];
  const reach = () => !ok[1]() ? 1 : !ok[2]() ? 2 : 3;            // the furthest step that can open
  const why = n => n === 1 ? 'Add KPIs to your dictionary, or choose to compare your models without KPIs.' : 'Add a Power BI file, or pick a model from Power BI.';
  const go = n => { const to = Math.max(1, Math.min(n, reach())); SR.step = to; say(to < n ? why(to) : ''); draw(true); };
  const ctx = {st, say, go, redraw: () => srKeepFocus(() => draw(false))};
  const draw = focus => {
    SR.step = Math.max(1, Math.min(SR.step, reach()));
    const steps = [[1, 'Your KPIs', d.kpis ? srN(d.kpis, 'KPI') : SR.selfOnly ? 'Models only' : 'To choose'],
      [2, 'Your models', total() ? srN(total(), 'model') : 'None yet'], [3, 'Check and start', srCost(d.cost)]];
    const bar = h('ol', {class: 'rvsteps', 'aria-label': 'Steps of a new review'}, steps.map(([n, label, sub]) => {
      const cur = n === SR.step, done = !cur && n < 3 && ok[n]();
      return h('li', {class: cur ? 'cur' : done ? 'done' : 'todo', 'aria-current': cur ? 'step' : null},
        h('button', {type: 'button', id: 'rvstep-' + n, disabled: n > reach(), onclick: () => go(n),
          'aria-label': `Step ${n}, ${label}: ${sub}${cur ? ', this step' : done ? ', done' : ', not yet'}`},
          h('span', {class: 'rvn', 'aria-hidden': 'true'}, done ? icon('check') : String(n)),
          h('span', {class: 'rvsl', 'aria-hidden': 'true'}, h('b', {}, label), h('small', {}, sub))));
    }));
    const back = h('button', {class: 'btn', type: 'button', onclick: () => go(SR.step - 1)}, icon('chevl'), 'Back');
    let body, actions;
    if (SR.step === 1) {
      body = srStepKpis(st, ctx.redraw, () => go(2));
      actions = [h('button', {class: 'btn primary', type: 'button', id: 'rvnext', onclick: () => go(2)}, 'Next: your models', icon('chevr'))];
    } else if (SR.step === 2) {
      body = srStepModels(ctx);
      actions = [h('button', {class: 'btn primary', type: 'button', id: 'rvnext', onclick: () => go(3)}, 'Next: check and start', icon('chevr'))];
    } else {
      const s3 = srStepStart(ctx, back);
      body = s3.body; actions = s3.actions;
    }
    box.replaceChildren(bar, h('div', {class: 'card rvcard'}, ...body, msg,
      h('div', {class: 'rvfoot'}, SR.step > 1 ? back : null, h('span', {class: 'grow'}), ...actions)));
    if (focus) { const t = $('.rvh2', box); if (t) t.focus(); }
  };
  draw(false);
  return box;
}

/* step 1: what the KPI dictionary holds (ready when it has KPIs, or the person compares models only) */
function srStepKpis(st, redraw, next) {
  const d = st.d, n = d.kpis, list = st.kpis || [], ind = st.industry;
  const out = [h('h2', {class: 'rvh2', tabindex: -1}, 'Your KPIs'),
    h('p', {class: 'muted rvlead'}, 'A review checks your models against your KPI dictionary: what each KPI means, how it is calculated, and the other names it goes by.')];
  const dict = h('a', {class: 'btn', href: srDictHref()}, icon('book'), n ? 'Open the KPI dictionary' : 'Add KPIs');
  const imp = d.can.edit ? h('button', {class: 'btn', type: 'button', onclick: () => kpiImportDialog(st.reload)}, icon('publish'), 'Import a file') : null;
  const tpl = h('a', {class: 'btn ghost', href: '/api/semreview/kpis/template.csv'}, icon('download'), 'Template');
  if (n) {
    const has = f => list.filter(f).length;
    const defs = has(k => String(k.definition || '').trim()), dax = has(k => k.dax), syn = has(k => (k.synonyms || []).length);
    const doms = {};
    list.forEach(k => { if (k.domain) doms[k.domain] = (doms[k.domain] || 0) + 1; });
    const domText = Object.entries(doms).sort((a, b) => b[1] - a[1]).map(([k, v]) => `${k} (${v})`).join(', ');
    out.push(h('div', {class: 'rvkpihead'},
        h('div', {class: 'rvbig'}, h('b', {}, n.toLocaleString()), h('span', {}, n === 1 ? 'KPI in your dictionary' : 'KPIs in your dictionary')),
        h('dl', {class: 'kv rvkv'},
          h('dt', {}, 'Industry pack'), h('dd', {}, ind ? ind.name : h('span', {class: 'muted'}, 'None: your own KPIs')),
          list.length ? [
            h('dt', {}, 'Definitions in words'), h('dd', {}, `${defs} of ${n}`, h('span', {class: 'muted'}, defs ? " - Relay's AI checks what these mean" : " - add them and Relay's AI also checks meaning")),
            h('dt', {}, 'Reference DAX'), h('dd', {}, `${dax} of ${n}`, dax ? h('span', {class: 'muted'}, ' - measures are compared with it') : null),
            h('dt', {}, 'Other names'), h('dd', {}, `${syn} of ${n}`, syn ? h('span', {class: 'muted'}, ' - measures with these names count as the KPI') : null)] : null,
          domText ? [h('dt', {}, 'Domains'), h('dd', {}, domText)] : null)),
      list.length ? h('div', {class: 'rvnames', role: 'list', 'aria-label': 'KPIs in your dictionary'},
        list.slice(0, 24).map(k => h('span', {class: 'rvname', role: 'listitem', title: k.definition || k.formula || ''}, k.name)),
        list.length > 24 ? h('span', {class: 'small muted'}, `and ${list.length - 24} more`) : null) : null,
      h('div', {class: 'row rvtools'}, dict, imp, h('a', {class: 'btn ghost', href: '/api/semreview/kpis/export.csv'}, icon('download'), 'Download (CSV)'), tpl),
      next ? h('div', {class: 'note ok rvready'}, icon('check'), h('span', {}, `Ready: your models are checked against ${n === 1 ? 'this KPI' : `these ${n.toLocaleString()} KPIs`}.`)) : null);
    return out;
  }
  out.push(h('div', {class: 'rvchoice'},
    h('div', {class: 'rvopt'}, h('h3', {}, 'Add your KPIs'),
      h('p', {class: 'small muted'}, 'Start from an industry pack, import the file you keep them in (CSV, Excel, YAML or JSON), or add them one by one. '
        + 'The review then holds every measure to your definitions.'),
      h('div', {class: 'row rvtools'}, typeof renderOntology === 'function' ? h('a', {class: 'btn', href: '#/ontology'}, icon('layers'), 'Industry packs') : null, dict, imp, tpl)),
    next ? h('div', {class: 'rvopt' + (SR.selfOnly ? ' on' : '')}, h('h3', {}, 'Or compare your models only'),
      h('p', {class: 'small muted'}, 'Without KPIs the review checks your models against each other (the same name, the same number) and checks their DAX. '
        + 'You can start the dictionary from its measures afterwards.'),
      h('button', {class: 'btn' + (SR.selfOnly ? '' : ' primary'), type: 'button', id: 'rvself', 'aria-pressed': String(SR.selfOnly),
        onclick: () => { SR.selfOnly = !SR.selfOnly; if (SR.selfOnly) next(); else redraw(); }},
        SR.selfOnly ? icon('check') : null, SR.selfOnly ? 'Chosen: models only' : 'Continue without KPIs')) : null));
  return out;
}

/* step 2: files and Power BI models (connect Power BI here when it is not, owners only) */
function srStepModels(ctx) {
  const d = ctx.st.d, lim = d.limits || {files: 5, mb: 500}, pbi = d.pbi || {}, redraw = ctx.redraw;
  const total = () => SR.files.length + SR.picks.length;
  const input = h('input', {type: 'file', multiple: true, accept: '.pbix,.pbit,.bim,.json,.zip'});
  const add = files => {
    let warn = '';
    for (const f of files) {
      if (!/\.(pbix|pbit|bim|json|zip)$/i.test(f.name)) { warn = `"${f.name}" is not a .pbix, .pbit, model.bim or zipped Power BI project.`; continue; }
      if (f.size > lim.mb * 1048576) { warn = `"${f.name}" is bigger than ${lim.mb} MB. Save the report as a template (.pbit: no data, small) and upload that.`; continue; }
      if (SR.files.some(x => x.name === f.name && x.size === f.size)) continue;
      if (total() >= lim.files) { warn = `A review reads up to ${lim.files} models.`; break; }
      SR.files.push(f);
    }
    redraw(); ctx.say(warn, 'warn');
  };
  input.onchange = () => { add(input.files); input.value = ''; };
  const drop = h('div', {class: 'drop rvdrop', tabindex: 0, role: 'button', id: 'rvdrop', 'aria-label': 'Choose Power BI files', onclick: () => input.click(),
      onkeydown: e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); input.click(); } }},
    icon('publish'), h('div', {}, h('b', {}, 'Drop Power BI files here'), ' or click to choose'),
    h('div', {class: 'small muted'}, `.pbix, .pbit, model.bim or a zipped Power BI project folder - up to ${lim.files} models, ${lim.mb} MB each. Big files upload in parts.`), input);
  drop.addEventListener('dragover', e => { e.preventDefault(); drop.classList.add('over'); });
  drop.addEventListener('dragleave', () => drop.classList.remove('over'));
  drop.addEventListener('drop', e => { e.preventDefault(); drop.classList.remove('over'); add(e.dataTransfer.files); });
  const pbiBox = h('div', {class: 'rvpbi'}, icon('db'), h('div', {class: 'grow'},
      h('b', {}, 'Power BI service'), pbi.configured ? h('span', {class: 'tag ok', style: 'margin-left:8px'}, 'Connected') : null,
      h('div', {class: 'small muted'}, pbi.configured ? `Through your organisation's Entra app${pbi.tenant ? ' (' + pbi.tenant + ')' : ''}: pick semantic models from your workspaces. It only reads.`
        : d.can.connect ? "Not connected yet. Connect your organisation's own Entra app once, then pick models from your workspaces."
          : 'Not connected. To review models in the Power BI service, an owner of your organisation connects Power BI here.')),
    pbi.configured ? h('button', {class: 'btn', type: 'button', id: 'rvpick', onclick: () => pickModels(redraw)}, icon('db'), 'Pick models') : null,
    pbi.configured && d.can.connect ? h('button', {class: 'btn ghost sm', type: 'button', onclick: () => pbiDialog(pbi, redraw)}, icon('gear'), 'Connection') : null,
    !pbi.configured && d.can.connect ? h('button', {class: 'btn', type: 'button', id: 'rvconnect', onclick: () => pbiDialog(pbi, redraw)}, icon('plug'), 'Connect Power BI') : null);
  const rows = [...SR.files.map((f, i) => ({ic: 'file', name: f.name, meta: `${srFileKind(f.name)} - ${size(f.size)}`, rm: () => { SR.files.splice(i, 1); redraw(); }})),
    ...SR.picks.map((p, i) => ({ic: 'db', name: p.name, meta: `Power BI service${p.workspace_name ? ' - ' + p.workspace_name : ''}`, rm: () => { SR.picks.splice(i, 1); redraw(); }}))];
  const bytes = SR.files.reduce((a, f) => a + f.size, 0);
  return [h('h2', {class: 'rvh2', tabindex: -1}, 'Your models'),
    h('p', {class: 'muted rvlead'}, `Upload Power BI files, pick models from the Power BI service, or both: up to ${lim.files} models in one review, also compared with each other.`),
    SR.note ? h('div', {class: 'note rvprefill'}, icon('info'), h('span', {class: 'grow'}, SR.note),
      h('button', {class: 'btn ghost sm', type: 'button', onclick: () => { SR.note = ''; redraw(); }}, 'Dismiss')) : null,
    drop, pbiBox,
    h('div', {class: 'rvpicked'}, h('div', {class: 'rvpickedh'}, h('b', {}, rows.length ? `Picked: ${rows.length} of ${lim.files}` : 'Nothing picked yet'),
        bytes ? h('span', {class: 'small muted'}, `${size(bytes)} to upload`) : null),
      rows.length ? h('ul', {class: 'rvlist', 'aria-label': 'Models picked'}, rows.map((x, i) => h('li', {},
        icon(x.ic), h('span', {class: 'grow'}, h('b', {}, x.name), h('small', {class: 'muted'}, x.meta)),
        h('button', {class: 'btn ghost sm', type: 'button', id: 'rvrm-' + i, 'aria-label': `Remove ${x.name}`, onclick: x.rm}, icon('x'), 'Remove')))) : null)];
}

/* step 3: what will be read, what happens, the credits; Start */
function srStepStart(ctx, back) {
  const d = ctx.st.d, n = d.kpis, cr = srCredits(), each = srFixEach(), lim = d.limits || {files: 5, mb: 500};
  const list = ctx.st.kpis || [], defs = list.some(k => String(k.definition || '').trim());
  const nameIn = h('input', {type: 'text', id: 'rvname', placeholder: 'For example: Sales and Finance models, November', maxlength: 120, value: SR.name,
    oninput: e => { SR.name = e.target.value; }});
  const change = (to, what) => h('button', {class: 'btn ghost sm', type: 'button', 'aria-label': `Change ${what}`, onclick: () => ctx.go(to)}, 'Change');
  const flow = [['Read', 'the models'], ['Check', n ? 'against your KPIs and each other' : 'the models against each other'],
    ...(n ? [['Meaning', defs || !list.length ? "Relay's AI, on your definitions in words" : 'not run: no definitions in words']] : []),
    ...(SR.picks.length ? [['Values', 'the numbers of KPIs that disagree, from Power BI']] : []), ['Findings', 'what to change']];
  const low = cr != null && cr < d.cost;
  const body = [h('h2', {class: 'rvh2', tabindex: -1}, 'Check and start'),
    h('p', {class: 'muted rvlead'}, 'What this review reads and does. Nothing is charged until you start it.'),
    h('dl', {class: 'rvsum'},
      h('dt', {}, 'KPIs'), h('dd', {}, h('div', {class: 'rvsumrow'}, h('span', {class: 'grow'}, n ? `${srN(n, 'KPI')} from your KPI dictionary` + (ctx.st.industry ? ` (${ctx.st.industry.name} pack)` : '')
        : 'No KPI dictionary: your models are compared with each other'), change(1, 'the KPIs'))),
      h('dt', {}, 'Models'), h('dd', {}, h('div', {class: 'rvsumrow'}, h('ul', {class: 'rvul grow'},
        SR.files.map(f => h('li', {}, icon('file'), h('span', {}, h('b', {}, f.name), ` - ${srFileKind(f.name)}, ${size(f.size)}`))),
        SR.picks.map(p => h('li', {}, icon('db'), h('span', {}, h('b', {}, p.name), ` - Power BI service${p.workspace_name ? ', ' + p.workspace_name : ''}`)))), change(2, 'the models'))),
      h('dt', {}, 'What is read'), h('dd', {}, 'Only the model: measures and their DAX, tables, columns, relationships, and which visuals show which fields. '
        + 'No rows of data are read or kept, and each uploaded file is deleted as soon as it is read.'),
      h('dt', {}, 'What happens'), h('dd', {}, h('ol', {class: 'rvflow'}, flow.map(([t, x]) => h('li', {}, h('b', {}, t), h('span', {}, x)))),
        h('div', {class: 'small muted'}, 'From a few seconds to a few minutes. You can leave the page; the review keeps going.')),
      h('dt', {}, 'Credits'), h('dd', {}, h('b', {}, srCost(d.cost)), ' when the review starts, given back if it does not finish.',
        cr != null ? h('span', {class: low ? 'rvlow' : 'muted'}, ` You have ${cr.toLocaleString()} left.`) : null,
        h('div', {class: 'small muted'}, `Fixing findings afterwards uses ${each} credit${each === 1 ? '' : 's'} a finding, shown before anything is charged.`),
        low && typeof requestDialog === 'function' ? h('button', {class: 'btn sm', type: 'button', style: 'margin-top:6px', onclick: () => requestDialog()}, icon('plus'), 'Request credits') : null)),
    h('label', {class: 'f', for: 'rvname'}, 'Name ', h('small', {}, 'optional')), nameIn];
  const bar = h('div', {class: 'srbar', hidden: true}, h('i'));
  const prog = h('span', {class: 'small muted', role: 'status'});
  const start = h('button', {class: 'btn primary', type: 'button', id: 'rvstart'}, icon('play'), 'Start review', h('span', {class: 'cost'}, ` - ${srCost(d.cost)}`));
  start.onclick = async () => {
    if (!SR.files.length && !SR.picks.length) return ctx.go(2);
    // item 64: big files go up in parts (01-core.js upload), so the limit is the review's own per file
    const mb = lim.mb || 500, tooBig = SR.files.find(f => f.size > mb * 1048576);
    if (tooBig) return ctx.say(`"${tooBig.name}" is larger than a review reads (${mb} MB a file). Save big reports as templates (.pbit: no data, small).`, 'warn');
    const fd = new FormData();
    SR.files.forEach(f => fd.append('files', f));
    fd.append('azure', JSON.stringify(SR.picks));
    fd.append('name', SR.name.trim());
    start.disabled = back.disabled = nameIn.disabled = true; bar.hidden = false; ctx.say('');
    prog.textContent = SR.files.length ? 'Uploading...' : 'Starting...';
    try {
      const r = await upload('/api/semreview/runs', fd, p => {
        bar.firstChild.style.width = Math.round(p * 100) + '%';
        if (SR.files.length) prog.textContent = p >= 0.99 ? 'Starting...' : `Uploading ${Math.round(p * 100)}%`;
      });
      Object.assign(SR, {files: [], picks: [], name: '', note: '', step: 1, selfOnly: false});
      if (typeof refreshOrg === 'function') refreshOrg(true);
      location.hash = `#/review/${r.id}`;
    } catch (e) {
      ctx.say(e.message, 'err');
      start.disabled = back.disabled = nameIn.disabled = false; bar.hidden = true; prog.textContent = '';
    }
  };
  return {body, actions: [bar, prog, start]};
}

/* ---------------- Power BI: the organisation's own Entra app ---------------- */
function pbiDialog(cur, after) {     // after: what to redraw once the connection is saved or removed
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
      if (after) after();
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
    try {
      const r = await api('/api/semreview/pbi', {method: 'DELETE'});
      for (const k of Object.keys(cur)) delete cur[k];
      Object.assign(cur, r || {configured: false});
      notify('Power BI connection removed', 'ok'); $('.modal') && $('.modal').remove();
      (after || renderReviewHome)();
    } catch (e) { out.replaceChildren(h('div', {class: 'note err'}, e.message)); }
  };
  modal('Connect Power BI (Azure)', h('div', {class: 'mbody'},
    h('p', {style: 'margin-top:0'}, 'D2D Relay connects to the Power BI service with an app of your own in Microsoft Entra ID. Semantic Review only reads your '
      + 'semantic models with it; publishing (Connections, Deployment) sends dashboards to the one workspace an owner chooses.'),
    h('ol', {class: 'small srsteps'},
      h('li', {}, 'In Microsoft Entra ID, register an app (App registrations) and add a client secret.'),
      h('li', {}, 'In the Fabric admin portal (Developer settings), allow service principals to use Fabric APIs, and the Execute queries REST API.'),
      h('li', {}, 'In each workspace to review or publish to, add the app as Contributor (or Member). Power BI shows a model\'s DAX only to identities that may change the model.')),
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
    SR.picks = all; m.remove(); after();
  };
  body.replaceChildren(h('label', {class: 'f', style: 'margin-top:0'}, 'Workspace'), sel, h('label', {class: 'f'}, 'Semantic models'), list, out,
    h('div', {class: 'row', style: 'justify-content:flex-end;margin-top:12px'}, ok));
}

/* ---------------- the KPI dictionary ---------------- */
async function renderKpiDictionary(inOnto) {      // inOnto: shown as the Ontology's KPI dictionary (item 61, #/ontology/kpis)
  document.title = 'KPI dictionary - D2D Relay';
  const again = () => renderKpiDictionary(inOnto);
  const page = h('div', {class: 'page' + (inOnto ? ' wide' : '')});
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
        h('button', {class: 'btn sm', type: 'button', onclick: () => kpiDialog(k, d, again)}, icon('edit'), 'Edit'),
        typeof kpiWordsDialog === 'function' ? h('button', {class: 'btn sm ghost', type: 'button', title: 'Change it in words (item 63)',
          'aria-label': `Change ${k.name} in words`, onclick: () => kpiWordsDialog(k, again)}, icon('wand')) : null,
        h('button', {class: 'btn sm ghost danger', type: 'button', 'aria-label': `Delete ${k.name}`, onclick: async () => {
          if (!confirm(`Delete ${k.name} from the dictionary?`)) return;
          try { await api(`/api/semreview/kpis/${k.id}`, {method: 'DELETE'}); again(); } catch (e) { notify(e.message, 'err'); }
        }}, icon('x'))] : null)))
      : [h('tr', {}, h('td', {colspan: 6, class: 'muted', style: 'text-align:center;padding:24px'}, d.kpis.length ? 'No KPI matches.' : 'No KPIs yet.'))]));
  };
  search.oninput = draw;
  page.append(
    ...(inOnto && typeof ontoHead === 'function' ? ontoHead('kpis', true) : [
      h('div', {class: 'crumbs'}, h('a', {href: '#/review'}, 'Semantic Review'), icon('chevr'), 'KPI dictionary'), h('h1', {}, 'KPI dictionary')]),
    h('p', {class: 'muted lead'}, 'What each KPI means and how it is calculated, with the other names people use for it. Every review checks your models '
      + 'against it, and new dashboards plan their KPIs from it. One name stands for one KPI: a name or other name can belong to one KPI only.'),
    h('div', {class: 'row', style: 'gap:8px;flex-wrap:wrap;margin:6px 0 14px;align-items:center'},
      can ? h('button', {class: 'btn primary', type: 'button', onclick: () => kpiDialog(null, d, again)}, icon('plus'), 'Add a KPI') : null,
      can ? h('button', {class: 'btn', type: 'button', onclick: () => kpiImportDialog(again)}, icon('publish'), 'Import a file') : null,
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

/* ---------------- one review: what was configured, its stages, the stage open ---------------- */
async function renderReviewRun(rid) {
  const main = $('#main');
  let r;
  try { r = await api(`/api/semreview/runs/${rid}`); }
  catch (e) { return main.replaceChildren(h('div', {class: 'page'}, h('div', {class: 'card empty'}, h('h3', {}, 'Review not found'), h('a', {href: '#/review'}, 'Back to Semantic Review')))); }
  if (!location.hash.startsWith(`#/review/${rid}`)) return;
  const same = SR.rid === rid;
  if (!same) {                                  // another review: its own picks, filters and open findings
    Object.assign(SR, {rid, fixMode: false, sev: 'all', q: '', only: null, sub: 'models', mq: ''});
    SR.fix.clear(); SR.open.clear(); SR.sel.clear();
  }
  SR.last = srSig(r);
  drawRun(r, same);
  srPoll(r);
}

const srBusy = r => !SR_FINAL.includes(r.status) || !!(r.fixes && r.fixes.status === 'running');
const srSig = r => { const fx = r.fixes || {}, ai = r.ai || {}; return JSON.stringify([r.status, r.step, fx.status, (fx.items || []).length, ai.ran, ai.tries, r.finished]); };

/* while the review or its fixes run: ask again every 2.5 s, and redraw only when something changed */
function srPoll(r) {
  clearTimeout(SR.timer); SR.timer = null;
  if (!srBusy(r)) return;
  SR.timer = setTimeout(async () => {
    const here = () => location.hash.startsWith(`#/review/${r.id}`);
    if (!here()) return;
    let x;
    try { x = await api(`/api/semreview/runs/${r.id}`); } catch (e) { return srPoll(r); }
    if (!here()) return;
    const sig = srSig(x);
    if (sig !== SR.last) {
      if (!SR_FINAL.includes(r.status) && x.status === 'done' && !r.result) delete SR.view[x.id];   // finished: land on its findings
      if ((r.fixes || {}).status === 'running' && (x.fixes || {}).status !== 'running') SR.view[x.id] = 'fix';   // the fixes made
      SR.last = sig;
      drawRun(x, true);
    }
    srPoll(x);
  }, 2500);
}

function drawRun(r, keep) {
  const main = $('#main');
  if (!main || !location.hash.startsWith(`#/review/${r.id}`)) return;
  const top = main.scrollTop, wy = window.scrollY;
  document.title = `${r.name} - Semantic Review - D2D Relay`;
  const page = h('div', {class: 'page wide rvrun'});
  page.append(h('div', {class: 'crumbs'}, h('a', {href: '#/review'}, 'Semantic Review'), icon('chevr'), r.name), srRunHead(r));
  if (r.status === 'error') page.append(...srFailed(r));
  else {
    const st = srStages(r), view = srView(r, st);
    page.append(srConfigured(r, st), srStageBar(r, st, view), srPanel(r, st, view));
  }
  srKeepFocus(() => main.replaceChildren(page));
  if (keep) { main.scrollTop = top; if (window.scrollY !== wy) window.scrollTo(0, wy); }
  const bar = $('.rvstages', page), sel = bar && $('.rvst.sel', bar);       // a narrow screen: the stage open is in view
  if (sel && bar.scrollWidth > bar.clientWidth) bar.scrollLeft = Math.max(0, sel.offsetLeft - (bar.clientWidth - sel.offsetWidth) / 2);
}

/* open a stage (a click, a "Next" button, a drill-down) */
function srGo(r, key) {
  SR.view[r.id] = key;
  drawRun(r, true);
  const b = document.getElementById('rvst-' + key);
  if (b) { b.focus({preventScroll: true}); b.scrollIntoView({block: 'nearest', inline: 'nearest'}); }
}

function srRunHead(r) {
  const actions = h('div', {class: 'row rvacts'},
    r.status === 'done' ? h('a', {class: 'btn', href: `/api/semreview/runs/${r.id}/findings.csv`}, icon('download'), 'Findings (CSV)') : null,
    r.status === 'done' && r.can_run ? h('button', {class: 'btn', type: 'button', title: "The same models, as this review read them, against today's KPI dictionary",
      onclick: async e => {
        const b = e.currentTarget; b.disabled = true;
        try { const x = await api(`/api/semreview/runs/${r.id}/again`, {method: 'POST'}); if (typeof refreshOrg === 'function') refreshOrg(true); location.hash = `#/review/${x.id}`; }
        catch (err) { notify(err.message, 'err'); b.disabled = false; }
      }}, icon('play'), 'Review again', h('span', {class: 'cost'}, ' - ' + srCost(r.cost))) : null,
    r.can_delete && SR_FINAL.includes(r.status) ? h('button', {class: 'btn ghost danger', type: 'button', onclick: async () => {
      const yes = typeof confirmBox === 'function' ? await confirmBox('Delete this review?', `"${r.name}": its findings, its fixes and the models it read go with it.`, 'Delete')
        : confirm(`Delete the review "${r.name}"? Its findings and the models it read go with it.`);
      if (!yes) return;
      try { await api(`/api/semreview/runs/${r.id}`, {method: 'DELETE'}); location.hash = '#/review'; } catch (e) { notify(e.message, 'err'); }
    }}, icon('x'), 'Delete') : null);
  const took = r.status === 'done' && r.finished && r.finished > r.created ? ` - took ${dur((r.finished - r.created) * 1000)}` : '';
  return h('div', {class: 'phead'}, h('div', {class: 'grow'}, h('h1', {style: 'margin:0'}, r.name),
    h('div', {class: 'meta'}, srPill(r.status, null), ` ${r.by || 'Former member'} - ${when(r.created)}${took}`)), actions);
}

/* the stages: where the review is, what each did (state done/run/now/open/warn/skip/todo) */
function srStages(r) {
  const res = r.result, ai = r.ai || {}, fx = r.fixes || {}, est = r.fix_estimate || {};
  const report = !!res && (r.status === 'done' || r.status === 'meaning');
  const pbi = r.status === 'values' || (r.sources || []).some(s => s.kind === 'powerbi')
    || !!(res && (res.values || (res.models || []).some(m => (m.source || {}).kind === 'powerbi')));
  const keys = ['read', 'check', 'meaning', ...(pbi ? ['values'] : []), 'findings', 'fix', 'apply'];
  const list = keys.map(k => ({key: k, label: SR_STAGE[k], state: 'todo', sub: '', can: false}));
  const at = k => list.find(x => x.key === k);
  if (!report) {                               // still running: the stages before this one are done
    const now = {queued: 'read', reading: 'read', checking: 'check', meaning: 'meaning', values: 'values'}[r.status] || 'read';
    const i = keys.indexOf(now);
    list.forEach((x, j) => { x.state = j < i ? 'done' : j === i ? 'run' : 'todo'; x.sub = j < i ? 'Done' : j === i ? 'Now' : ''; });
    return {list, cur: now, report};
  }
  const s = res.summary, f = s.findings || {}, items = fx.items || [], good = items.filter(x => x.ok).length;
  list.forEach(x => { x.can = true; });
  Object.assign(at('read'), {state: 'done', sub: `${srN(s.models, 'model')}, ${srN(s.measures, 'measure')}`});
  Object.assign(at('check'), {state: 'done', sub: s.score != null ? `${s.kpis_consistent} of ${s.kpis_checked} KPIs one meaning`
    : res.kpis.length ? `${srN(res.kpis.length, 'KPI')} compared` : 'No KPIs to compare'});
  const m = at('meaning');
  if (r.status === 'meaning') Object.assign(m, {state: 'run', sub: 'Checking now'});
  else if (ai.ran) Object.assign(m, {state: 'done', sub: ai.partial ? 'Checked, in part' : 'Checked'});
  else if (ai.skipped) Object.assign(m, {state: 'skip', sub: 'Not needed'});
  else Object.assign(m, {state: 'warn', sub: 'Could not run'});
  if (pbi) Object.assign(at('values'), res.values ? {state: 'done', sub: srN(srValueRows(res).length, 'number')} : {state: 'skip', sub: 'None needed'});
  const fi = at('findings'), fs = at('fix'), ap = at('apply');
  fi.sub = res.findings.length ? `${res.findings.length} found` + (f.high ? `, ${f.high} high` : '') : 'None';
  fs.can = r.status === 'done'; ap.can = good > 0;
  let cur = 'findings';
  if (fx.status === 'running') {
    fi.state = 'done'; Object.assign(fs, {state: 'run', sub: `Fixing ${fx.count || ''}`.trim()}); ap.sub = 'After the fixes'; cur = 'fix';
  } else if (good) {
    fi.state = 'done'; Object.assign(fs, {state: 'done', sub: `${good} fixed`}); Object.assign(ap, {state: 'now', sub: 'Your next step'}); cur = 'apply';
  } else {
    fi.state = 'now'; ap.sub = 'After fixes';
    if (fx.status === 'error' || items.length) Object.assign(fs, {state: 'warn', sub: fx.status === 'error' ? 'Stopped' : 'None made'});
    else if (r.status !== 'done') Object.assign(fs, {state: 'todo', sub: 'After the meaning check'});
    else Object.assign(fs, {state: est.fixable ? 'open' : 'skip', sub: est.fixable ? `${est.fixable} can be fixed` : 'Nothing to fix'});
  }
  return {list, cur, report};
}
const srView = (r, st) => { const v = SR.view[r.id]; return st.report && v && st.list.some(x => x.key === v && x.can) ? v : st.cur; };
const srValueRows = res => { const out = []; (res.kpis || []).forEach(k => (k.implementations || []).forEach(i => { if (i.value !== undefined || i.value_error) out.push({k, i}); })); return out; };

/* What was configured: the KPIs, the models, the Power BI connection, the meaning check; each opens its stage */
function srConfigured(r, st) {
  const res = r.result, ai = r.ai || {}, src = r.sources || [];
  const ms = res ? res.models : null, s = res ? res.summary : null;
  const nDict = res ? (res.dictionary ? res.dictionary.length : s.kpis_defined || 0) : null;
  const defs = res ? (res.dictionary || []).filter(k => String(k.definition || '').trim()).length : 0;
  const pb = ms ? ms.map((m, i) => ({m, s: src[i] || {}})).filter(x => (x.m.source || {}).kind === 'powerbi') : src.filter(x => x.kind === 'powerbi').map(x => ({s: x}));
  const ws = [...new Set(pb.map(x => x.s.workspace_name).filter(Boolean))];
  const sum = k => (ms || []).reduce((a, m) => a + (m[k] || 0), 0);
  const tile = (label, main, detail, stage) => st.report
    ? h('button', {class: 'rvtile', type: 'button', onclick: () => srGo(r, stage), title: `Open ${SR_STAGE[stage]}`}, h('small', {}, label), h('b', {}, main), h('span', {}, detail),
      h('span', {class: 'rvvh'}, `. Open ${SR_STAGE[stage]}`))
    : h('div', {class: 'rvtile'}, h('small', {}, label), h('b', {}, main), h('span', {}, detail));
  let mean, meanD;
  if (!res) { mean = 'After the check'; meanD = "Relay's AI, when your KPIs have definitions in words"; }
  else if (r.status === 'meaning') { mean = 'Running'; meanD = "Relay's AI is checking what each KPI means"; }
  else if (ai.ran) { mean = ai.partial ? 'Ran, in part' : 'Ran'; meanD = `On ${srN(defs, 'definition')} in words`; }
  else if (ai.skipped) { mean = 'Not run'; meanD = String(ai.why || 'No definitions in words to check').replace(/[.\s]+$/, ''); }
  else { mean = 'Could not run'; meanD = 'Everything else is complete'; }
  return h('section', {class: 'rvconf', 'aria-label': 'What was configured'}, h('div', {class: 'rvconfh'}, 'What was configured'),
    h('div', {class: 'rvtiles'},
      tile('KPI dictionary', res ? (nDict ? srN(nDict, 'KPI') : 'No KPIs') : 'Read at the check',
        res ? (nDict ? 'from your dictionary when the review ran' : 'models compared with each other') : 'your KPI dictionary as it is then', 'check'),
      tile('Models read', srN(ms ? ms.length : src.length, 'model'),
        ms ? `${srN(sum('tables'), 'table')}, ${srN(sum('measures'), 'measure')}` : src.map(x => x.file || x.name).join(', '), 'read'),
      tile('Power BI connection', pb.length ? `${srN(pb.length, 'model')} from the service` : 'Not used',
        pb.length ? (ws.length ? ws.join(', ') : "your organisation's Entra app") + (res && res.values ? ' - values read' : '') : 'uploaded files only',
        pb.length && res && res.values ? 'values' : 'read'),
      tile('Meaning check', mean, meanD, 'meaning')));
}

function srStageBar(r, st, view) {
  const list = st.list;
  const marks = {done: ', done', run: ', running now', warn: ', needs a look', skip: ', not run', now: ', your next step', open: ', open', todo: ', not yet'};
  return h('div', {class: 'rvstages', role: 'tablist', 'aria-label': 'Stages of the review'}, list.map((x, i) => {
    const dot = x.state === 'done' ? icon('check') : x.state === 'run' ? h('span', {class: 'spin sm'}) : x.state === 'warn' ? '!' : x.state === 'skip' ? '-' : String(i + 1);
    return h('button', {type: 'button', role: 'tab', id: 'rvst-' + x.key, class: `rvst ${x.state}${x.key === view ? ' sel' : ''}`,
      'aria-selected': String(x.key === view), 'aria-controls': 'rvpanel', tabindex: x.key === view ? 0 : -1, disabled: !x.can && x.key !== view,
      title: SR_DOES[x.key], onclick: () => { if (x.can) srGo(r, x.key); },
      onkeydown: e => {
        const en = list.filter(y => y.can || y.key === view);
        let k = en.findIndex(y => y.key === x.key);
        if (e.key === 'ArrowRight') k = (k + 1) % en.length; else if (e.key === 'ArrowLeft') k = (k - 1 + en.length) % en.length;
        else if (e.key === 'Home') k = 0; else if (e.key === 'End') k = en.length - 1; else return;
        e.preventDefault();
        if (en[k].can) srGo(r, en[k].key);
      }},
      h('span', {class: 'rvdot', 'aria-hidden': 'true'}, dot),
      h('span', {class: 'rvsl'}, h('b', {}, x.label), h('small', {}, x.sub || '')),
      h('span', {class: 'rvvh'}, marks[x.state] || ''));
  }));
}

function srPanel(r, st, view) {
  const p = h('section', {class: 'rvpanel', id: 'rvpanel', role: 'tabpanel', 'aria-labelledby': 'rvst-' + view});
  if (!st.report) { p.append(...srRunning(r, st)); return p; }
  const draw ={read: srReadPanel, check: srCheckPanel, meaning: srMeaningPanel, values: srValuesPanel, findings: srFindingsPanel, fix: srFixPanel, apply: srApplyPanel}[view] || srFindingsPanel;
  p.append(...draw(r, st).filter(Boolean));
  return p;
}
const srHead = (title, does, ...extra) => h('div', {class: 'rvph'}, h('div', {class: 'grow'}, h('h2', {}, title), does ? h('p', {class: 'small muted'}, does) : null), ...extra);
const srNext = (r, key, label, note) => h('div', {class: 'rvnext'}, note ? h('span', {class: 'small muted'}, note) : null,
  h('button', {class: 'btn primary', type: 'button', onclick: () => srGo(r, key)}, label, icon('chevr')));

function srRunning(r, st) {
  const later = st.list.filter(x => x.state === 'todo' && !['findings', 'fix', 'apply'].includes(x.key)).map(x => x.label);
  return [h('div', {class: 'card srwait rvwait'}, h('div', {class: 'spin'}), h('div', {class: 'grow'},
    h('b', {}, r.step || SR_STATUS[r.status] || 'Starting'),
    h('div', {class: 'small muted'}, SR_DOES[st.cur]),
    h('div', {class: 'small muted', style: 'margin-top:6px'}, (later.length ? `Then: ${later.join(', ')}, and the findings. ` : 'Then the findings. ')
      + 'This takes from a few seconds to a few minutes. You can leave this page; the review keeps going.')))];
}

function srFailed(r) {
  const src = r.sources || [];
  return [h('div', {class: 'note err'}, h('b', {}, 'The review did not finish. '), r.error || ''),
    h('div', {class: 'card'}, h('h3', {}, 'What was configured'),
      h('ul', {class: 'rvlist'}, src.map(x => h('li', {}, icon(x.kind === 'powerbi' ? 'db' : 'file'), h('span', {class: 'grow'}, h('b', {}, x.file || x.name || 'Model'),
        h('small', {class: 'muted'}, x.kind === 'powerbi' ? `Power BI service${x.workspace_name ? ' - ' + x.workspace_name : ''}`
          : x.kind === 'stored' ? 'As an earlier review read it' : `${srFileKind(x.file)}${x.bytes ? ' - ' + size(x.bytes) : ''}`))))),
      h('p', {class: 'small muted', style: 'margin-bottom:0'}, 'A review that does not finish gives its credits back. Uploaded files are deleted.')),
    h('div', {class: 'row'}, h('a', {class: 'btn primary', href: '#/review', onclick: () => { SR.home = 'new'; }}, icon('play'), 'Start a new review'))];
}

/* ---- Read: the models and every measure */
function srReadPanel(r) {
  const res = r.result, sub = SR.sub === 'measures' ? 'measures' : 'models';
  const seg = h('div', {class: 'segbtn', role: 'group', 'aria-label': 'Show'}, [['models', `Models (${res.models.length})`], ['measures', `Measures (${res.measures.length})`]].map(([k, t]) =>
    h('button', {type: 'button', id: 'rvsub-' + k, class: sub === k ? 'on' : '', 'aria-pressed': String(sub === k), onclick: () => { SR.sub = k; drawRun(r, true); }}, t)));
  return [srHead('Read', SR_DOES.read + ' Each uploaded file was deleted as soon as it was read.', seg), sub === 'measures' ? measuresTab(r) : modelsTab(res, r)];
}

/* ---- Check: the KPIs, and what the checks found */
function srCheckPanel(r) {
  const res = r.result, s = res.summary, rules = {};
  res.findings.forEach(x => { rules[x.rule] = (rules[x.rule] || 0) + 1; });
  const stat = (n, label, bad) => h('div', {class: 'stat' + (bad ? ' bad' : '')}, h('b', {}, String(n)), h('span', {}, label));
  const found = Object.entries(rules).sort((a, b) => b[1] - a[1]);
  return [srHead('Check', SR_DOES.check),
    h('div', {class: 'stats rvstats'},
      stat(s.score != null ? `${s.kpis_consistent} of ${s.kpis_checked}` : '-', s.score != null ? 'KPIs with one meaning' : 'No KPIs to compare yet', s.kpis_conflicting || s.kpis_differing),
      stat(s.kpis_conflicting || 0, 'calculated more than one way', s.kpis_conflicting),
      stat(s.kpis_differing || 0, 'not as defined', s.kpis_differing),
      stat(s.kpis_missing || 0, 'in no model'),
      stat(s.kpis_defined || 0, 'KPIs in the dictionary used')),
    found.length ? h('div', {class: 'rvfound'}, h('h3', {}, 'What the checks found'),
      h('div', {class: 'chips'}, found.map(([k, n]) => h('button', {type: 'button', class: 'chip', title: 'Show these findings',
        onclick: () => { Object.assign(SR, {only: {rule: k}, group: 'rule', sev: 'all', q: ''}); srGo(r, 'findings'); }}, `${SR_RULES[k] || k} (${n})`))))
      : h('div', {class: 'note ok'}, 'No check found a problem.'),
    h('h3', {class: 'rvh3'}, `KPIs (${res.kpis.length})`), kpiTab(res, r)];
}

/* ---- Meaning: Relay's AI on the definitions in words */
function srMeaningNote(r) {
  const ai = r.ai || {};
  return h('div', {class: 'note warn'}, `The meaning check by Relay's AI could not run (${String(ai.why || 'no answer').replace(/[.\s]+$/, '')}). Everything else in this review is complete. `,
    ai.can_retry && (ai.tries || 1) < 2 && r.can_run ? h('button', {class: 'btn sm', type: 'button', onclick: async e => {
      const b = e.currentTarget; b.disabled = true;
      try { await api(`/api/semreview/runs/${r.id}/meaning`, {method: 'POST'}); SR.view[r.id] = 'meaning'; renderReviewRun(r.id); }
      catch (err) { notify(err.message, 'err'); b.disabled = false; }
    }}, 'Check meaning again (no credits)') : null);
}
function srMeaningPanel(r) {
  const ai = r.ai || {}, res = r.result, dict = res.dictionary || [];
  const defs = dict.filter(k => String(k.definition || '').trim()), aiF = res.findings.filter(x => x.source === 'ai');
  let state;
  if (r.status === 'meaning') state = h('div', {class: 'card srwait'}, h('div', {class: 'spin'}), h('b', {}, "Relay's AI is checking what each KPI means..."));
  else if (ai.ran) state = h('div', {class: 'note ok'}, "Relay's AI checked the measures against your definitions in words"
    + (ai.partial ? ` (part of the KPIs only${ai.why ? ': ' + String(ai.why).replace(/[.\s]+$/, '') : ''})` : '') + '.');
  else if (ai.skipped) state = h('div', {class: 'note'}, `${String(ai.why || 'There was nothing to check').replace(/[.\s]+$/, '')}. `, h('a', {href: srDictHref()}, 'Add definitions'),
    " and Relay's AI also checks what each KPI means.");
  else state = srMeaningNote(r);
  return [srHead('Meaning', SR_DOES.meaning), state,
    h('div', {class: 'card'}, h('dl', {class: 'kv rvkv'},
      h('dt', {}, 'Definitions in words'), h('dd', {}, defs.length ? `${srN(defs.length, 'KPI')}: ${defs.slice(0, 12).map(k => k.name).join(', ')}${defs.length > 12 ? ' and more' : ''}`
        : 'None in the dictionary this review used'),
      ai.ran ? [h('dt', {}, 'Findings it added'), h('dd', {}, aiF.length ? h('a', {href: '#', onclick: e => { e.preventDefault(); Object.assign(SR, {only: {ai: true}, sev: 'all', q: ''}); srGo(r, 'findings'); }},
        `${aiF.length}: show them`) : 'None: the measures match your definitions')] : null,
      ai.ran && ai.matched ? [h('dt', {}, 'Measures placed in a KPI'), h('dd', {}, `${ai.matched}, named otherwise but computing a KPI`)] : null,
      h('dt', {}, 'What it sees'), h('dd', {}, "Your KPI definitions, the measures' DAX and the models' table and column names. Never your data.")))];
}

/* ---- Values: the numbers of KPIs that disagree (Power BI service models) */
function srValuesPanel(r) {
  const res = r.result, rows = srValueRows(res), by = new Map();
  rows.forEach(x => { if (!by.has(x.k.name)) by.set(x.k.name, []); by.get(x.k.name).push(x); });
  return [srHead('Values', SR_DOES.values), ...(res.notes || []).map(n => h('div', {class: 'note warn'}, n)),
    rows.length ? h('div', {class: 'card orgwrap', style: 'padding:6px 10px'}, h('table', {class: 'utable srtable'},
      h('thead', {}, h('tr', {}, ['KPI', 'Measure', 'Model', 'Value (no filters)'].map((t, i) => h('th', {class: i < 3 ? 'l' : ''}, t)))),
      h('tbody', {}, [...by.entries()].map(([name, xs]) => {
        const vals = new Set(xs.filter(x => !x.i.value_error).map(x => String(x.i.value)));
        return xs.map((x, j) => h('tr', {}, h('td', {}, j ? '' : [h('b', {}, name), vals.size > 1 ? h('div', {}, h('span', {class: 'tag srhigh'}, 'Different numbers')) : null]),
          h('td', {class: 'small'}, `[${x.i.measure}]`), h('td', {class: 'small'}, x.i.model_name || ''),
          h('td', {class: 'v'}, x.i.value_error ? h('span', {class: 'small', style: 'color:var(--err)'}, 'error: ' + x.i.value_error) : srNum(x.i.value))));
      }))))
      : h('div', {class: 'card empty'}, h('h3', {}, 'No numbers needed'), h('div', {}, 'No KPI disagreed in the models from the Power BI service, so there was nothing to put side by side.'))];
}

/* ---- Findings: counts by severity, grouped by severity, KPI or check; each opens for its detail */
function srFindingsPanel(r) {
  const res = r.result, s = res.summary, all = res.findings, est = r.fix_estimate || {}, ai = r.ai || {};
  SR.fixable = new Set(est.ids || []);
  const out = [srHead('Findings', SR_DOES.findings)];
  if (r.status === 'done' && ai.ran === false && !ai.skipped) out.push(srMeaningNote(r));
  (res.notes || []).forEach(n => out.push(h('div', {class: 'note warn'}, n)));
  const score = h('div', {class: 'rvscore' + (s.kpis_conflicting || s.kpis_differing ? ' bad' : s.score != null ? ' good' : '')},
    h('b', {}, s.score != null ? `${s.kpis_consistent} of ${s.kpis_checked}` : '-'), h('span', {}, s.score != null ? 'KPIs with one meaning' : 'No KPIs to compare yet'));
  if (!all.length) return out.concat(h('div', {class: 'rvheadline'}, score),
    h('div', {class: 'card empty'}, h('h3', {}, 'Nothing to fix'), h('div', {}, 'Every measure was read and no rule found a problem.')));
  const SEV = ['high', 'medium', 'low', 'info'], rank = x => SEV.indexOf(x.severity);
  const counts = {all: all.length};
  all.forEach(x => { counts[x.severity] = (counts[x.severity] || 0) + 1; });
  const sevs = h('div', {class: 'rvsevs', role: 'group', 'aria-label': 'Show the findings of'});
  const groupBy = h('div', {class: 'segbtn', role: 'group', 'aria-label': 'Group by'});
  const search = h('input', {type: 'search', id: 'rvfq', placeholder: 'Find in findings (a KPI, a measure, a word)', value: SR.q, class: 'srsearch', 'aria-label': 'Find in findings'});
  const only = h('span', {class: 'rvonly'});
  const toggle = h('button', {class: 'btn ghost sm', type: 'button', id: 'rvexp'});
  const shown = h('div', {class: 'small muted rvshown', role: 'status'});
  const list = h('div', {class: 'rvgroups'});
  let visible = [];
  const sync = () => {
    const allOpen = visible.length && visible.every(x => SR.open.has(x.id));
    toggle.replaceChildren(icon(allOpen ? 'chevr' : 'chevd'), allOpen ? 'Collapse all' : 'Expand all'); toggle.disabled = !visible.length;
  };
  const draw = () => srKeepFocus(() => {
    sevs.replaceChildren(...['all', ...SEV].filter(k => k === 'all' || counts[k]).map(k => h('button', {type: 'button', id: 'rvsev-' + k,
      class: 'chip rvsevt sev-' + k + (SR.sev === k ? ' on' : ''), 'aria-pressed': String(SR.sev === k), onclick: () => { SR.sev = k; draw(); }},
      h('b', {}, String(counts[k] || 0)), h('span', {}, k === 'all' ? 'All' : SR_SEV[k][0]))));
    groupBy.replaceChildren(...[['severity', 'Severity'], ['kpi', 'KPI'], ['rule', 'Check']].map(([k, t]) => h('button', {type: 'button', id: 'rvgrp-' + k,
      class: SR.group === k ? 'on' : '', 'aria-pressed': String(SR.group === k), onclick: () => { SR.group = k; draw(); }}, t)));
    const o = SR.only;
    only.replaceChildren(...(o ? [h('button', {type: 'button', class: 'chip on', id: 'rvonly', title: 'Show every finding', onclick: () => { SR.only = null; draw(); }},
      o.kpi ? `KPI: ${o.kpi}` : o.rule ? `Check: ${SR_RULES[o.rule] || o.rule}` : "Found by Relay's AI", ' ', icon('x'))] : []));
    const q = search.value.trim().toLowerCase(); SR.q = q;
    visible = all.filter(x => (SR.sev === 'all' || x.severity === SR.sev) && (!o || (o.kpi ? x.kpi === o.kpi : o.rule ? x.rule === o.rule : x.source === 'ai'))
      && (!q || [x.title, x.detail, x.kpi, SR_RULES[x.rule], ...(x.measures || []).map(m => m.name)].join(' ').toLowerCase().includes(q)));
    const key = x => SR.group === 'kpi' ? x.kpi || '' : SR.group === 'rule' ? x.rule : x.severity;
    const groups = new Map();
    visible.forEach(x => { const k = key(x); if (!groups.has(k)) groups.set(k, []); groups.get(k).push(x); });
    const worst = xs => Math.min(...xs.map(rank));
    const order = [...groups.entries()].sort((a, b) => SR.group === 'severity' ? SEV.indexOf(a[0]) - SEV.indexOf(b[0])
      : (a[0] === '') - (b[0] === '') || worst(a[1]) - worst(b[1]) || b[1].length - a[1].length || String(a[0]).localeCompare(String(b[0])));
    list.replaceChildren(...(visible.length ? order.map(([k, xs]) => h('section', {class: 'rvgroup'},
      h('h3', {class: 'rvgh'}, h('span', {}, SR.group === 'severity' ? (SR_SEV[k] || [k])[0] : SR.group === 'kpi' ? (k || 'Not about one KPI') : (SR_RULES[k] || k)),
        h('span', {class: 'rvgn'}, String(xs.length)),
        SR.group !== 'severity' ? SEV.filter(v => xs.some(x => x.severity === v)).map(v =>
          h('span', {class: 'tag ' + (v === 'high' ? 'srhigh' : v === 'medium' ? 'warn' : '')}, `${xs.filter(x => x.severity === v).length} ${SR_SEV[v][0].toLowerCase()}`)) : null),
      xs.map(x => findingCard(x, r, sync)))) : [h('div', {class: 'card empty'}, 'No finding matches.')]));
    shown.textContent = visible.length === all.length ? `${srN(all.length, 'finding')}` : `${visible.length} of ${srN(all.length, 'finding')}`;
    sync();
  });
  toggle.onclick = () => {
    const openAll = !(visible.length && visible.every(x => SR.open.has(x.id)));
    visible.forEach(x => { if (openAll) SR.open.add(x.id); else SR.open.delete(x.id); });
    draw();
  };
  search.oninput = () => draw();
  draw();
  out.push(h('div', {class: 'rvheadline'}, score, sevs),
    h('div', {class: 'rvtool'}, h('span', {class: 'small muted'}, 'Group by'), groupBy, only, h('span', {class: 'grow'}), search, toggle),
    shown, list);
  if (r.status === 'done' && est.fixable) {
    const each = srFixEach(r);
    out.push(srNext(r, 'fix', 'Next: fix the findings', `Relay can fix ${srN(est.fixable, 'finding')}, ${each} credit${each === 1 ? '' : 's'} each. Nothing is charged until you choose.`));
  }
  return out;
}

function findingCard(x, r, sync) {
  const dax = (x.dax || []).filter(Boolean);
  const more = h('div', {hidden: true}, dax.map(t => h('pre', {class: 'srdax'}, t)));
  const ms = x.measures || [];
  const el = h('details', {class: 'srfind sev-' + x.severity, id: 'rvf-' + x.id, open: SR.open.has(x.id),
      ontoggle: () => { if (el.open) SR.open.add(x.id); else SR.open.delete(x.id); if (sync) sync(); }},
    h('summary', {}, srTag(x.severity), h('span', {class: 'rvft'}, x.title),
      h('span', {class: 'rvfm'},
        x.kpi && SR.group !== 'kpi' ? h('span', {class: 'tag acc'}, x.kpi) : null,
        SR.group !== 'rule' ? h('span', {class: 'tag'}, SR_RULES[x.rule] || x.rule) : null,
        SR.fixable.has(x.id) ? h('span', {class: 'tag ok', title: 'Relay can fix this one in the Fix step'}, icon('wand'), 'Fixable') : null,
        x.source === 'ai' ? h('span', {class: 'tag', title: "Found by Relay's AI from your definitions"}, icon('spark'), "Relay's AI") : null,
        ms.length ? h('span', {class: 'small muted'}, srN(ms.length, 'measure')) : null),
      icon('chevd', 'rvchev')),
    h('div', {class: 'rvfbody'},
      h('p', {}, x.detail),
      ms.length ? h('div', {class: 'flist'}, ms.map(m => h('span', {}, icon('code'), ` [${m.name}]`,
        h('small', {class: 'muted'}, ` ${m.table ? m.table + ', ' : ''}${m.model_name || ''}`)))) : null,
      x.fix || x.fix_dax ? h('div', {class: 'srfix'}, h('div', {class: 'row', style: 'gap:8px;align-items:center'}, h('b', {class: 'small'}, 'What to do'),
          h('span', {class: 'grow'}), x.fix_dax ? copyBtn(x.fix_dax) : null),
        x.fix ? h('div', {class: 'small'}, x.fix) : null, x.fix_dax ? h('pre', {class: 'srdax'}, x.fix_dax) : null) : null,
      dax.length ? h('button', {class: 'btn ghost sm', type: 'button', 'aria-expanded': 'false', onclick: e => {
        more.hidden = !more.hidden; e.currentTarget.setAttribute('aria-expanded', String(!more.hidden));
        e.currentTarget.lastChild.textContent = more.hidden ? 'Show the DAX' : 'Hide the DAX';
      }}, icon('code'), 'Show the DAX') : null, more));
  return el;
}

/* ---- Fix (item 65): what fixing uses, the findings to pick, the fixes made */
function fixCard(r) {
  const est = r.fix_estimate || {}, fx = r.fixes;
  SR.fixable = new Set(est.ids || []);
  if (fx && fx.status === 'running') return h('div', {class: 'card srwait srfixcard'}, h('div', {class: 'spin'}), h('div', {},
    h('b', {}, `Relay is fixing ${fx.count} finding${fx.count === 1 ? '' : 's'}...`),
    h('div', {class: 'small muted'}, 'Each fix is checked against the model before it is kept. A fix that does not check out gives its credit back. You can leave this page.')));
  if (!est.fixable && !(fx && fx.items && fx.items.length)) return null;
  const each = est.each || srFixEach(r);
  const cost = n => `${n * each} credit${n * each === 1 ? '' : 's'}`;
  const sev = est.by_severity || {};
  const go = h('button', {class: 'btn primary', type: 'button', id: 'rvfixgo', disabled: !SR.fix.size}, icon('wand'), SR.fix.size ? `Fix ${SR.fix.size} - ${cost(SR.fix.size)}` : 'Pick findings to fix');
  go.onclick = async () => {
    go.disabled = true;
    try {
      await api(`/api/semreview/runs/${r.id}/fixes`, {json: {findings: [...SR.fix]}});
      SR.fix.clear(); SR.fixMode = false; if (typeof refreshOrg === 'function') refreshOrg(true); SR.view[r.id] = 'fix'; renderReviewRun(r.id);
    } catch (e) { go.disabled = false; notify(e.message, 'err'); }
  };
  const pickAll = h('button', {class: 'btn', type: 'button'}, `Pick all ${est.fixable} - ${cost(est.fixable)}`);
  pickAll.onclick = () => { SR.fixMode = true; (est.ids || []).forEach(i => SR.fix.add(i)); SR.view[r.id] = 'fix'; renderReviewRun(r.id); };
  const pickHigh = (sev.high || 0) && sev.high < est.fixable ? h('button', {class: 'btn ghost', type: 'button'}, `Only the ${sev.high} high - ${cost(sev.high)}`) : null;
  if (pickHigh) pickHigh.onclick = () => {
    SR.fixMode = true; SR.fix.clear();
    r.result.findings.filter(x => SR.fixable.has(x.id) && x.severity === 'high').forEach(x => SR.fix.add(x.id)); SR.view[r.id] = 'fix'; renderReviewRun(r.id);
  };
  const choose = h('button', {class: 'btn ghost', type: 'button'}, SR.fixMode ? 'Stop choosing' : 'Choose findings');
  choose.onclick = () => { SR.fixMode = !SR.fixMode; if (!SR.fixMode) SR.fix.clear(); SR.view[r.id] = 'fix'; renderReviewRun(r.id); };
  const made = fx && fx.items ? fx.items.filter(x => x.ok).length : 0;
  const cr = srCredits();
  return h('div', {class: 'card srfixcard'},
    h('div', {class: 'row', style: 'gap:8px;flex-wrap:wrap;align-items:center'}, h('h3', {style: 'margin:0'}, icon('wand'), ' Fix the findings'),
      made ? h('span', {class: 'tag ok'}, `${made} fixed - below`) : null, h('span', {class: 'grow'}),
      cr != null ? h('span', {class: 'small muted'}, `${cr.toLocaleString()} credits left`) : null),
    est.fixable ? h('p', {class: 'small', style: 'margin:6px 0 10px'},
      `${est.fixable} of ${r.result.findings.length} findings can be fixed in the model's measures: ${est.ready} with the DAX this review already wrote, `
      + `${est.fixable - est.ready} written by Relay. Fixing uses ${each} credit${each === 1 ? '' : 's'} a finding: all of them ${cost(est.fixable)}`
      + (sev.high ? `, the ${sev.high} high ones ${cost(sev.high)}` : '') + '. You get the fixed DAX and a script to apply it to your model (TMDL view or Tabular Editor); '
      + 'findings about visuals and relationships are fixed in the report by hand.') : null,
    made && est.fixable ? h('div', {class: 'small muted', style: 'margin:-4px 0 10px'}, 'Fixing again replaces the fixes below: download their scripts first (Apply and review again).') : null,
    est.fixable && r.can_run ? h('div', {class: 'row', style: 'gap:8px;flex-wrap:wrap'}, pickAll, pickHigh, choose, go) : null);
}

function srPickList(r) {
  const xs = r.result.findings.filter(x => SR.fixable.has(x.id));
  const sync = () => { const c = $('.srfixcard'); if (c) srKeepFocus(() => c.replaceWith(fixCard(r))); };
  const groups = ['high', 'medium', 'low', 'info'].map(v => [v, xs.filter(x => x.severity === v)]).filter(g => g[1].length);
  return h('div', {class: 'card rvpick'}, h('div', {class: 'rvpickh'}, h('b', {}, 'Pick the findings to fix'), h('span', {class: 'small muted'}, `${xs.length} can be fixed`)),
    groups.map(([v, ys]) => h('fieldset', {class: 'rvpickg'}, h('legend', {}, `${SR_SEV[v][0]} (${ys.length})`),
      ys.map(x => h('label', {class: 'rvpickrow'},
        h('input', {type: 'checkbox', checked: SR.fix.has(x.id), 'aria-label': `Fix: ${x.title}`,
          onchange: e => { if (e.currentTarget.checked) SR.fix.add(x.id); else SR.fix.delete(x.id); sync(); }}),
        h('span', {class: 'grow'}, x.title, (x.measures || [])[0] ? h('small', {class: 'muted'}, ` - [${x.measures[0].name}]`) : null),
        x.kpi ? h('span', {class: 'tag acc'}, x.kpi) : null)))));
}

function srFixableList(r) {
  const xs = r.result.findings.filter(x => SR.fixable.has(x.id));
  return h('details', {class: 'card rvfixable'}, h('summary', {}, h('b', {}, `What Relay can fix (${xs.length})`), icon('chevd', 'rvchev')),
    h('ul', {class: 'rvplain'}, xs.map(x => h('li', {}, srTag(x.severity), ' ', x.title, (x.measures || [])[0] ? h('small', {class: 'muted'}, ` - [${x.measures[0].name}]`) : null))));
}

function fixesTab(r) {
  const fx = r.fixes || {}, items = fx.items || [];
  if (fx.status === 'error') return h('div', {class: 'note err'}, fx.error || 'The fixes stopped.');
  const good = items.filter(x => x.ok), bad = items.filter(x => !x.ok);
  return h('div', {class: 'rvfixes'},
    h('h3', {class: 'rvh3'}, `${good.length} fixed measure${good.length === 1 ? '' : 's'}`,
      fx.by || fx.finished ? h('small', {class: 'muted'}, ` - ${[fx.by, fx.finished ? when(fx.finished) : ''].filter(Boolean).join(', ')}`) : null),
    good.length ? h('p', {class: 'small muted', style: 'margin:-4px 0 10px'}, 'To use them: download the scripts, apply them to your model and save it, '
      + 'then review the fixed model in a new review (the next step: upload the saved file again, or pick the same Power BI models, which are read fresh). '
      + "Review again re-reads the models as this review kept them, without your fixes: it is for checking them against today's KPI dictionary.") : null,
    fx.given_back ? h('div', {class: 'note'}, `${fx.given_back} credit${fx.given_back === 1 ? ' was' : 's were'} given back for fixes that did not check out.`) : null,
    ...good.map(x => {
      const id = 'fx-' + x.finding;
      const el = h('details', {class: 'srfind rvfixd sev-' + x.severity, open: SR.open.has(id), ontoggle: () => { if (el.open) SR.open.add(id); else SR.open.delete(id); }},
        h('summary', {}, h('span', {class: 'rvft'}, `[${x.measure}]`, h('small', {class: 'muted'}, ` ${x.table || ''}${x.model_name ? ', ' + x.model_name : ''}`)),
          h('span', {class: 'rvfm'}, srTag(x.severity), h('span', {class: 'tag'}, SR_RULES[x.rule] || x.rule), x.kpi ? h('span', {class: 'tag acc'}, x.kpi) : null,
            h('span', {class: 'tag ok'}, x.how === 'rules' ? "The review's fix" : 'Written by Relay'), x.new ? h('span', {class: 'tag'}, 'New measure') : null),
          icon('chevd', 'rvchev')),
        h('div', {class: 'rvfbody'}, h('p', {class: 'small muted'}, x.title + (x.why ? ` - ${x.why}` : '')),
          x.old ? [h('div', {class: 'small'}, h('b', {}, 'Now')), h('pre', {class: 'srdax'}, x.old)] : null,
          h('div', {class: 'row', style: 'gap:8px;align-items:center;margin-top:8px'}, h('b', {class: 'small'}, 'Fixed'), h('span', {class: 'grow'}), copyBtn(`${x.measure} = ${x.dax}`)),
          h('pre', {class: 'srdax'}, x.dax), x.format ? h('div', {class: 'small muted'}, `Format: ${x.format}`) : null));
      return el;
    }),
    bad.length ? h('div', {class: 'card'}, h('h3', {}, `Not fixed (${bad.length})`),
      h('ul', {class: 'small'}, bad.map(x => h('li', {}, h('b', {}, `[${x.measure}] `), `${x.title}: ${x.why}`)))) : null);
}

function srFixPanel(r) {
  const res = r.result, est = r.fix_estimate || {}, fx = r.fixes || {};
  SR.fixable = new Set(est.ids || []);
  const items = fx.items || [], good = items.filter(x => x.ok).length, running = fx.status === 'running';
  const out = [srHead('Fix', SR_DOES.fix)];
  if (fx.status === 'error') out.push(fixesTab(r));             // stopped (an error, a restart): said first, then fix again
  const card = fixCard(r);
  if (card) out.push(card);
  if (!running && est.fixable) out.push(SR.fixMode ? srPickList(r) : srFixableList(r));
  if (!running && items.length && fx.status !== 'error') out.push(fixesTab(r));
  const hand = res.findings.length - (est.fixable || 0);
  if (!card && fx.status !== 'error') out.push(h('div', {class: 'card empty'}, h('h3', {}, 'Nothing to fix automatically'),
    h('div', {}, res.findings.length ? 'These findings are about visuals, relationships, calculation groups or the dictionary: each one says what to do under Findings.'
      : 'This review found nothing to fix.')));
  else if (hand > 0 && !running) out.push(h('p', {class: 'small muted'}, `${srN(hand, 'other finding')} ${hand === 1 ? 'is' : 'are'} fixed by hand `
    + '(visuals, relationships, calculation groups, the dictionary): each says what to do under Findings.'));
  if (good && !running) out.push(srNext(r, 'apply', 'Next: apply and review again', `${srN(good, 'fixed measure')} ready to apply.`));
  return out;
}

/* ---- Apply and review again: the scripts, how to apply them, the fixed model reviewed */
function srApplyPanel(r) {
  const fx = r.fixes || {}, good = (fx.items || []).filter(x => x.ok);
  const head = srHead('Apply and review again', SR_DOES.apply);
  if (!good.length) return [head, h('div', {class: 'card empty'}, h('h3', {}, 'No fixes yet'), h('div', {}, 'Fix findings first: their scripts show here.'),
    h('div', {style: 'margin-top:12px'}, h('button', {class: 'btn', type: 'button', onclick: () => srGo(r, 'fix')}, 'Go to Fix')))];
  const models = [...new Map(good.map(x => [x.model, x.model_name || `Model ${x.model + 1}`])).entries()];
  const kinds = (r.result.models || []).map(m => (m.source || {}).kind);
  return [head,
    h('ol', {class: 'rvhow'},
      h('li', {}, h('div', {}, h('b', {}, 'Download the fixes'),
        h('p', {class: 'small muted'}, `${srN(good.length, 'fixed measure')} in ${srN(models.length, 'model')}: one script for each model, for TMDL view or Tabular Editor.`),
        h('div', {class: 'rvdl'}, models.map(([mi, name]) => h('div', {class: 'rvdlrow'}, h('b', {class: 'grow'}, name),
            h('a', {class: 'btn sm', href: `/api/semreview/runs/${r.id}/fixes.tmdl?model=${mi}`}, icon('download'), 'TMDL script'),
            h('a', {class: 'btn sm ghost', href: `/api/semreview/runs/${r.id}/fixes.csx?model=${mi}`}, icon('download'), 'Tabular Editor script'))),
          h('div', {class: 'rvdlrow'}, h('span', {class: 'grow small muted'}, 'Every fix with its old and new DAX'),
            h('a', {class: 'btn sm ghost', href: `/api/semreview/runs/${r.id}/fixes.csv`}, icon('download'), 'All fixes (CSV)'))))),
      h('li', {}, h('div', {}, h('b', {}, 'Apply them to your model'),
        h('div', {class: 'rvways'},
          h('div', {class: 'rvway'}, h('b', {}, 'TMDL view'), h('ol', {class: 'small'}, h('li', {}, 'Open the model in Power BI and choose View > TMDL view.'),
            h('li', {}, 'Paste the TMDL script and press Apply.'), h('li', {}, 'Check the measures, then save.'))),
          h('div', {class: 'rvway'}, h('b', {}, 'Tabular Editor'), h('ol', {class: 'small'}, h('li', {}, 'Open the model.'),
            h('li', {}, 'Run the script as a C# script.'), h('li', {}, 'Check the measures, then save.')))),
        kinds.includes('powerbi') ? h('p', {class: 'small muted'}, 'A model in the Power BI service: publish it again once it is saved.') : null)),
      h('li', {}, h('div', {}, h('b', {}, 'Review the fixed model'),
        h('p', {class: 'small muted'}, 'A new review reads the saved model and shows the findings that are gone and any that are left. Uploaded files are uploaded again; '
          + 'models in the Power BI service are read again from the service.'),
        r.can_run ? h('button', {class: 'btn primary', type: 'button', id: 'rvfixed', onclick: () => srReviewFixed(r)}, icon('play'), 'Review the fixed models', h('span', {class: 'cost'}, ` - ${srCost(r.cost)}`))
          : h('div', {class: 'small muted'}, 'A BI Dev or an owner of your organisation starts reviews.'),
        r.can_run ? h('p', {class: 'small muted', style: 'margin:8px 0 0'}, "Review again, at the top, reads the models as this review kept them (without your fixes) against today's KPI dictionary: "
          + 'use it after changing the dictionary.') : null)))];
}

/* the guided start again, at step 2, with this review's Power BI models picked and its files to upload named */
function srReviewFixed(r) {
  const res = r.result || {models: []}, src = r.sources || [], lim = ((SR.data || {}).limits || {}).files || 5;
  const picks = [], files = [];
  res.models.forEach((m, i) => {
    const s = m.source || {}, x = src[i] || {};
    if (s.kind === 'powerbi' && s.workspace && s.model) picks.push({workspace: s.workspace, model: s.model, name: m.name || x.name || 'Power BI model', workspace_name: x.workspace_name || ''});
    else files.push(x.file || m.name || `Model ${i + 1}`);
  });
  Object.assign(SR, {files: [], picks: picks.slice(0, lim), name: `${r.name} (fixed)`.slice(0, 120), step: 2, home: 'new',
    selfOnly: !((res.dictionary || []).length || (res.summary || {}).kpis_defined),
    note: (files.length ? `Upload the fixed, saved files: ${files.join(', ')}.` : '') + (picks.length ? `${files.length ? ' ' : ''}The Power BI models are read again from the service.` : '')});
  location.hash = '#/review';
}

/* ---- the KPI table, the measures, the models (drill-downs of Check and Read) */
function kpiTab(res, r) {
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
        values ? h('td', {class: 'small v'}, impl ? impl.map(i => h('div', {title: i.value_error || null}, i.value_error ? 'error' : i.value !== undefined ? srNum(i.value) : '-')) : '-') : null,
        h('td', {}, k.findings.length ? h('a', {href: '#', onclick: e => {
          e.preventDefault(); Object.assign(SR, {only: {kpi: k.name}, sev: 'all', q: ''});
          if (r) srGo(r, 'findings'); else renderReviewRun(location.hash.split('/')[2]);
        }}, `${k.findings.length} finding${k.findings.length === 1 ? '' : 's'}`) : h('span', {class: 'muted'}, '-')));
    }))));
}

function measuresTab(r) {
  const res = r.result, ms = res.measures;
  const search = h('input', {type: 'search', id: 'rvmq', placeholder: 'Find a measure', value: SR.mq, class: 'srsearch', 'aria-label': 'Find a measure'});
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
      canAdd ? addBtn : null, canAdd ? h('span', {class: 'small muted'}, 'Pick the measures that are your KPIs to start (or grow) the dictionary. Click a name for its DAX.') : null, h('span', {class: 'grow'}), search), out,
    h('div', {class: 'card orgwrap', style: 'padding:6px 10px'}, h('table', {class: 'utable srtable'},
      h('thead', {}, h('tr', {}, [canAdd ? '' : null, 'Measure', 'Table', 'Model', 'KPI', 'In visuals', 'Format'].filter(x => x !== null).map(t => h('th', {class: 'l'}, t)))), body)));
}

function modelsTab(res, r) {
  const kind = {pbix: 'Power BI file (.pbix)', pbit: 'Power BI template (.pbit)', bim: 'model.bim', pbip: 'Power BI project', powerbi: 'Power BI service'};
  const src = (r && r.sources) || [];
  return h('div', {class: 'srmodels'}, res.models.map((m, i) => {
    const s = m.source || {}, f = src[i] || {};
    const inKpi = (res.measures || []).filter(x => x.model === i && x.kpi).length;
    return h('div', {class: 'card'}, h('h3', {}, m.name || 'Model'),
      h('dl', {class: 'kv'}, h('dt', {}, 'Source'), h('dd', {}, kind[s.kind] || s.kind || ''),
        f.kind === 'file' && f.file ? [h('dt', {}, 'File'), h('dd', {}, f.file + (f.bytes ? ` - ${size(f.bytes)}` : ''))] : null,
        s.kind === 'powerbi' && f.workspace_name ? [h('dt', {}, 'Workspace'), h('dd', {}, f.workspace_name)] : null,
        s.kind === 'powerbi' && s.via ? [h('dt', {}, 'Read from'), h('dd', {}, s.via === 'definition' ? 'the model definition' : "the model's INFO views")] : null,
        h('dt', {}, 'Tables'), h('dd', {}, String(m.tables)), h('dt', {}, 'Measures'), h('dd', {}, String(m.measures) + (inKpi ? `, ${inKpi} of them KPIs` : '')),
        h('dt', {}, 'Relationships'), h('dd', {}, String(m.relationships)),
        m.pages != null ? [h('dt', {}, 'Report'), h('dd', {}, `${m.pages} page${m.pages === 1 ? '' : 's'}, ${m.visuals} visual${m.visuals === 1 ? '' : 's'} with fields`)] : null));
  }));
}
