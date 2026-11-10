/* ---------------- project page ---------------- */
function stepAt(st) {
  const byJob = {plan: 0, build: 2, revise: 3, pbi: 4};
  return {planning: 0, awaiting_kpis: 1, building: 2, awaiting_review: 3, revising: 3, building_pbi: 4, done: 5}[st.status] ?? byJob[(st.job || {}).kind] ?? 0;
}
const latestV = st => st.versions.length ? st.versions[st.versions.length - 1].v : null;
const published = (st, v) => (st.publishes || []).filter(p => p.v === v);
function header(st) {
  const runs = st.runs || [], mins = runs.reduce((a, r) => a + (r.duration_ms || 0), 0);
  const busy = RUN.has(st.status);
  const sel = h('select', {title: busy ? 'AI model — a change applies from the next run' : 'AI model for the next runs'}, modelOptions(st.model));
  if (st.access && !st.access.can_edit) sel.disabled = true;
  sel.onchange = async () => {
    try { S.project = await api(`/api/projects/${st.id}/model`, {json: {model: sel.value}}); notify(`AI model: ${modelName(sel.value)}`, 'ok'); S.key = null; render(); }
    catch (e) { notify(e.message, 'err'); sel.value = st.model; }
  };
  return h('div', {},
    h('div', {class: 'crumbs'}, h('a', {href: '#/'}, 'Dashboards'), '›', st.name),
    h('div', {class: 'phead'},
      h('div', {style: 'flex:1 1 320px;min-width:0'}, h('div', {class: 'row', style: 'gap:12px'}, h('h1', {}, st.name), h('span', {id: 'hpill'}, pill(st.status))),
        h('div', {class: 'meta'}, `Created ${when(st.created)} · ${st.files.length} data file${st.files.length === 1 ? '' : 's'}`,
          st.versions.length ? ` · ${st.versions.length} version${st.versions.length === 1 ? '' : 's'}` : '',
          runs.length ? ` · AI: ${dur(mins)}` : '')),
      h('span', {class: 'seg'}, h('em', {}, busy ? 'Model (next run)' : 'AI model'), sel),
      st.access ? accessBadge(st) : null,
      certSummary(st),
      st.versions && st.versions.length ? h('button', {class: 'btn', title: 'Ask a question about this dashboard', onclick: () => {
        const go = () => { const p = $('#askpanel'); if (!p) return false; p.scrollIntoView({behavior: 'smooth', block: 'center'}); const i = $('input', p); if (i) i.focus({preventScroll: true}); return true; };
        if (S.tab !== 'overview') { location.hash = `#/p/${st.id}`; setTimeout(go, 600); } else go(); }}, icon('spark'), 'Ask Relay') : null,
      h('button', {class: 'btn' + ((S.pins || []).includes(st.id) ? ' on' : ''), 'aria-pressed': String((S.pins || []).includes(st.id)),
        title: (S.pins || []).includes(st.id) ? 'Unpin from the sidebar' : 'Pin to the sidebar', onclick: async e => { await togglePin(st.id); S.key = null; render(); }},
        icon('pin'), (S.pins || []).includes(st.id) ? 'Pinned' : 'Pin'),
      st.access && st.access.can_share ? h('button', {class: 'btn', onclick: () => shareDialog(st)}, icon('share'), 'Share') : null),
    null);   // P14's "numbers under review" banner (observeWarnings): D2D Relay has no data observability, its API answers 404
}
function stepper(st) {
  // generated demo data adds a first step
  const dataJob = st.status === 'generating_data' || ((st.status === 'queued' || st.status === 'error') && (st.job || {}).kind === 'data');
  const steps = st.data ? ['Demo data', ...STEPS] : STEPS, at = st.data ? (dataJob ? 0 : stepAt(st) + 1) : stepAt(st);
  return h('div', {class: 'steps'}, steps.map((s, i) => h('div', {class: 'step' + (i < at ? ' done' : i === at ? ' cur' + (st.status === 'error' ? ' err' : '') : '')},
    h('b', {}, i < at ? '✓' : i + 1), h('span', {}, s))));
}
function banner(st) {
  const lv = latestV(st), v = st.versions.find(x => x.v === lv) || {};
  const box = (tone, ic, title, text, ...acts) => h('div', {class: 'banner ' + tone}, h('div', {class: 'ic'}, ic),
    h('div', {class: 'txt'}, h('div', {class: 't'}, title), h('div', {class: 'd', id: tone === 'run' ? 'btext' : null}, text)), acts);
  if (RUN.has(st.status)) {
    const kind = st.status === 'queued' ? (st.job || {}).kind : {generating_data: 'data', planning: 'plan', building: 'build', revising: 'revise', building_pbi: 'pbi'}[st.status];
    const title = st.status === 'queued' ? 'Waiting for the agent' : {data: 'Relay is designing and generating demo data for your business',
      plan: 'Relay is reading your data and planning the report',
      build: 'Relay is building the model, KPIs and prototype', revise: `Relay is applying your changes (v${(lv || 0) + 1})`,
      pbi: "Publishing: checking the DAX in Power BI's engine and writing the Power BI project"}[kind];
    return box('run', h('div', {class: 'spin'}), title, '', kind !== 'pbi' ? h('button', {class: 'btn', onclick: stopRun}, 'Stop') : null);
  }
  if (st.status === 'awaiting_kpis') return box('you', icon('user'), 'Action required: confirm the plan',
    'Check the KPIs and their formulas below, choose about any custom visuals, then confirm — Relay builds the prototype next.');
  if (st.status === 'awaiting_review') {
    const bad = gatesFailed(v);
    if (bad.length) return box('you', icon('alert'), `Action required: v${lv} needs a fix before it can be approved`,
      `${bad.length} review gate${bad.length === 1 ? '' : 's'} failed (${bad.map(g => g.name).join(', ')}). Ask Relay to fix them, or describe other changes below.`,
      h('button', {class: 'btn primary', title: "Fixing what failed in Relay's own review gates uses no credits", onclick: e => fixGates(st, v, e.currentTarget)}, 'Ask Relay to fix them'));
    return box('you', icon('user'), `Ready for review: prototype v${lv}`,
      (v.gates || []).length ? `It passed every review gate. Approve it to publish the Power BI project, or describe what should change.`
        : 'Approve it to publish the Power BI project, or describe what should change.',
      h('button', {class: 'btn', onclick: () => { const a = $('.sticky .btn.primary'); if (a) { a.scrollIntoView({behavior: 'smooth', block: 'center'}); a.focus({preventScroll: true}); } }},
        'Review and approve ↓'));
  }
  if (st.status === 'done') {
    const o = st.output || {};
    return box('ok', icon('check'), `Published to Power BI · v${st.approved}`,
      `${o.pbip || ''} · ${o.pages} pages · ${o.visuals} visuals · ${o.measures} measures` + (o.dax ? " · DAX checked in Power BI's engine" : ''),
      h('a', {class: 'btn primary', href: `/api/projects/${st.id}/download`}, icon('download'), 'Download'));
  }
  if (st.status === 'error') {
    const retryCost = (st.credits || {}).retry || 0;      // D2D Relay: the failed run's credits came back, so Retry pays again
    const retry = h('button', {class: 'btn primary', title: retryCost ? `Retry uses ${retryCost} credits` : 'Retry costs no credits', onclick: async () => { retry.disabled = true;
      try { S.project = await api(`/api/projects/${st.id}/retry`, {method: 'POST'}); S.key = null; render(); poll(); refreshOrg(true); } catch (e) { retry.disabled = false; notify(e.message, 'err'); } }},
      'Retry', retryCost ? h('span', {class: 'cost'}, ` · ${retryCost} credits`) : null);
    return box('err', icon('alert'), 'This step needs attention', st.error || 'Something went wrong.', st.job ? retry : null);
  }
  return null;
}
function tabsBar(st) {
  const counts = {versions: st.versions.length};
  return h('div', {class: 'tabs'}, TABS.map(([id, label]) => h('a', {href: `#/p/${st.id}/${id}`, class: S.tab === id ? 'on' : ''}, label,
    counts[id] ? h('span', {class: 'count'}, counts[id]) : null)));
}
async function stopRun(e) {
  e.target.disabled = true;
  try { await api(`/api/projects/${S.pid}/stop`, {method: 'POST'}); notify('Stopping…'); poll(); } catch (err) { e.target.disabled = false; notify(err.message, 'err'); }
}
async function approve(st, v) {
  try { S.project = await api(`/api/projects/${st.id}/approve`, {json: {version: v}}); notify(`v${v} approved — publishing to Power BI`, 'ok'); S.key = null; go('overview'); poll(); }
  catch (e) { notify(e.message, 'err'); }
}

/* ---------------- overview ---------------- */
function overviewTab(st) {
  if (RUN.has(st.status)) {
    const parts = [liveCard(st)];
    if (['building', 'revising'].includes(st.status) || (st.status === 'queued' && ['build', 'revise'].includes((st.job || {}).kind))) parts.push(previewCard(st));
    if (!st.versions.length) parts.push(dataCard(st), requestCard(st));
    return parts;
  }
  if (st.status === 'awaiting_kpis') return planView(st);
  if (st.status === 'done') return [doneCard(st), publishCard(st), reviewCard(st), ...reviewView(st), askPanel(st)];
  if (st.status === 'error') return st.versions.length ? [...reviewView(st), reviewCard(st), publishCard(st), askPanel(st)] : [requestCard(st)];
  return [...reviewView(st), reviewCard(st), publishCard(st), askPanel(st)];
}
function liveCard(st) {
  return h('div', {class: 'card'}, h('div', {class: 'row'}, h('h3', {style: 'margin:0'}, 'Live activity'), h('span', {class: 'spacer'}),
    h('a', {href: `#/p/${st.id}/activity`, class: 'small'}, 'Full activity log →')),
    h('div', {id: 'livelog'}), h('div', {class: 'live'}, h('div', {class: 'now', id: 'now'})));
}
function previewCard(st) {
  return h('div', {class: 'card'}, h('div', {class: 'row'}, h('h3', {style: 'margin:0'}, 'Live preview'),
    h('span', {class: 'muted small'}, 'refreshes each time Relay renders the prototype'), h('span', {class: 'spacer'}),
    h('a', {class: 'btn sm', href: `/api/projects/${st.id}/prototype/live`, target: '_blank'}, icon('external'), 'Open')), h('div', {id: 'liveframe'}));
}
function requestCard(st) {
  return h('div', {class: 'card'}, h('h3', {}, 'Your request'), h('div', {class: 'say'}, st.prompt),
    st.data ? h('div', {class: 'note', style: 'margin-bottom:0'}, h('b', {}, 'Demo data: '), st.data.brief,
      h('div', {class: 'muted small', style: 'margin-top:4px'}, `${{small: 'Small', medium: 'Medium', large: 'Large'}[st.data.size] || st.data.size} · ${st.data.start} to ${st.data.end}`)) : null,
    h('div', {class: 'flist', style: 'margin-top:10px'}, st.files.map(f => h('span', {style: 'cursor:pointer', title: 'Preview the first rows',
      onclick: () => previewData(st, f.name)}, icon('table'), ' ', f.name, ' · ', size(f.bytes), f.generated ? h('span', {class: 'tag acc', style: 'margin-left:4px'}, 'generated') : null))),
    st.images.length ? h('div', {class: 'thumbs'}, st.images.map(n => h('img', {src: `/api/projects/${st.id}/images/${encodeURIComponent(n)}`, alt: n}))) : null);
}
function dataCard(st) {
  // the demo data Relay generated: what it was made to show, and every table with a preview
  const tables = st.data_tables || [];
  if (!st.data || !tables.length) return null;
  return h('div', {class: 'card'},
    h('div', {class: 'row'}, h('h3', {style: 'margin:0'}, 'Demo data'), h('span', {class: 'tag acc'}, 'generated'),
      h('span', {class: 'muted small'}, `${tables.length} tables · ${(st.data_rows || 0).toLocaleString()} rows · ${st.data.start} to ${st.data.end}`),
      h('span', {class: 'spacer'}), st.files_available && st.files_available.includes('datagen.yaml') ? h('button', {class: 'btn sm ghost', onclick: () => viewFile('datagen.yaml')}, icon('file'), 'Recipe') : null),
    st.data_summary ? notes(st.data_summary) : st.data_regenerated ? h('div', {class: 'muted small', style: 'margin-top:6px'},
      `Regenerated ${when(st.data_regenerated)} after your comments — Relay's notes on the plan say what changed.`) : null,
    (st.data_story || []).length ? h('div', {}, h('div', {class: 'muted small', style: 'margin-top:8px;font-weight:600'}, 'What the data was made to show'),
      h('ul', {class: 'story small'}, st.data_story.map(s => h('li', {}, s)))) : null,
    h('div', {class: 'dtables'}, tables.map(t => h('button', {title: (t.columns || []).join(', '), onclick: () => previewData(st, t.file)},
      h('b', {}, t.table), h('small', {}, `${(t.rows || 0).toLocaleString()} rows · ${(t.columns || []).length} columns` + (t.generated === false ? ' · yours' : ''))))),
    st.status === 'awaiting_kpis' ? h('div', {class: 'muted small', style: 'margin-top:8px'}, 'Want different data? Say so in the comments below (e.g. "add a returns table", "make Europe grow faster") — Relay changes the recipe and regenerates it.') : null);
}
async function previewData(st, file) {
  let r;
  try { r = await api(`/api/projects/${st.id}/data/${encodeURIComponent(file)}?limit=25`); } catch (e) { return notify(e.message, 'err'); }
  modal(`${file} · ${r.total.toLocaleString()} rows`, h('div', {class: 'mbody'},
    h('div', {class: 'dprev'}, h('table', {}, h('thead', {}, h('tr', {}, r.columns.map(c => h('th', {}, c)))),
      h('tbody', {}, r.rows.map(row => h('tr', {}, row.map(v => h('td', {}, v === null ? '' : String(v)))))))),
    h('div', {class: 'muted small', style: 'margin-top:8px'}, `The first ${r.rows.length} of ${r.total.toLocaleString()} rows.`)), true);
}
function protoFrame(src) {
  const wrap = h('div', {class: 'proto'});
  const frame = h('iframe', {src, title: 'Prototype'});
  wrap.append(frame);
  let lastW = 0;
  const fit = () => {
    const doc = frame.contentDocument;
    if (!doc || !doc.documentElement) return;
    const s = Math.min(1, wrap.clientWidth / 1300), ht = doc.documentElement.scrollHeight;
    frame.style.height = ht + 'px'; frame.style.transform = `scale(${s})`; wrap.style.height = Math.ceil(ht * s) + 'px';
  };
  frame.addEventListener('load', () => { fit(); try { new ResizeObserver(fit).observe(frame.contentDocument.body); } catch (e) {} });
  new ResizeObserver(() => { if (wrap.clientWidth !== lastW) { lastW = wrap.clientWidth; fit(); } }).observe(wrap);
  return wrap;
}

/* plan review (editable) */
function kpiCard(k, i) {
  const str = v => v == null ? '' : String(v);
  const inc = h('input', {type: 'checkbox', checked: true, title: 'Include this KPI'});
  const card = h('div', {class: 'kpi', 'data-i': i},
    h('div', {class: 'top3'}, inc,
      h('div', {}, h('small', {}, 'Measure name'), h('input', {type: 'text', class: 'k-name', value: str(k.name)})),
      h('div', {}, h('small', {}, 'Label on the card'), h('input', {type: 'text', class: 'k-label', value: str(k.label)})),
      h('div', {}, h('small', {}, 'Format'), h('input', {type: 'text', class: 'k-format mono', value: str(k.format)})),
      h('button', {class: 'x', title: 'Remove', type: 'button', onclick: () => card.remove()}, '×')),
    h('div', {class: 'two'},
      h('div', {}, h('small', {}, 'What it means (formula in words)'), h('textarea', {class: 'k-desc', rows: 3, value: str(k.description)})),
      h('div', {}, h('small', {}, 'DAX formula'), h('textarea', {class: 'k-dax dax', rows: 3, value: str(k.dax)}))));
  inc.onchange = () => card.classList.toggle('off', !inc.checked);
  return card;
}
const POLICY = {ask: 'You choose for each one', auto: 'Built unless you pick the available one', never: 'Only available visuals'};
function proposalCard(v, policy) {
  const pick = v.decision || v.recommend || (policy === 'auto' ? 'generate' : 'available');
  const opt = (value, text) => {
    const input = h('input', {type: 'radio', name: 'cv-' + v.name, value, checked: pick === value});
    const label = h('label', {class: pick === value ? 'on' : ''}, input, text);
    input.onchange = () => { label.parentElement.querySelectorAll('label').forEach(l => l.classList.toggle('on', l === label)); };
    return label;
  };
  const pages = Array.isArray(v.pages) ? v.pages.join(', ') : v.pages;
  return h('div', {class: 'cv', 'data-name': v.name},
    h('div', {class: 'ttl'}, h('b', {}, v.title || v.name), h('span', {class: 'faint small mono'}, v.name),
      v.recommend ? h('span', {class: 'tag acc'}, 'Relay recommends: ' + (v.recommend === 'generate' ? 'build it' : 'use available')) : null),
    v.need ? h('div', {class: 'need small'}, v.need) : null,
    h('div', {class: 'muted small'}, [v.fields ? 'Fields: ' + v.fields : '', pages ? 'Pages: ' + pages : ''].filter(Boolean).join(' · ')),
    h('div', {class: 'choice'}, opt('generate', '✦ Build a new custom visual'), opt('available', 'Use available: ' + (v.fallback || 'closest visual'))));
}
function planVisuals(list) {
  const out = {};
  list.querySelectorAll('.cv').forEach(c => { const r = c.querySelector('input[type=radio]:checked'); if (r) out[c.dataset.name] = r.value; });
  return out;
}
function planModel(plan) {
  const model = plan.model || {};
  return model.tables ? h('div', {class: 'card'}, h('h3', {}, 'Data model'),
    h('div', {class: 'tables'}, model.tables.map(t => h('div', {}, h('b', {}, t.name), h('span', {class: 'muted small'}, [t.role, t.csv, t.grain].filter(Boolean).join(' · '))))),
    model.relationships ? h('div', {class: 'rels mono'}, model.relationships.map(r => h('span', {}, typeof r === 'string' ? r : JSON.stringify(r)))) : null) : null;
}
function planPages(plan) {
  return plan.pages ? h('div', {class: 'card'}, h('h3', {}, `Pages `, h('span', {class: 'muted'}, `(${plan.pages.length})`)),
    h('div', {class: 'pages'}, plan.pages.map(p => h('div', {}, h('b', {}, p.name), p.purpose ? h('div', {class: 'small'}, p.purpose) : null,
      h('ul', {}, (p.visuals || []).map(v => h('li', {}, typeof v === 'string' ? v : (v.title || v.type || JSON.stringify(v))))))))) : null;
}
function planView(st) {
  const plan = st.plan || {}, kpis = plan.kpis || [];
  const proposals = (st.visuals && st.visuals.proposals) || [];
  const cvs = h('div', {}, proposals.map(v => proposalCard(v, st.custom_visuals)));
  S.planKpis = kpis;
  const list = h('div', {class: 'kpis'}, kpis.map(kpiCard));
  const fb = h('textarea', {rows: 2, placeholder: 'Comments for Relay — needed to ask for a revised plan (or attach files), optional when confirming'});
  const askLabel = () => ['Ask Relay to revise the plan', costTag('change')];
  const ask = h('button', {class: 'btn', onclick: () => sendPlan('revise')}, ...askLabel());
  const ok = h('button', {class: 'btn primary', onclick: () => sendPlan('confirm')}, icon('check'), 'Confirm & build prototype');
  const att = attacher();
  async function sendPlan(action) {
    const files = att.files();
    if (action === 'confirm' && files.length) return toast(ok, 'New files change the plan: use "Ask Relay to revise the plan" so you can review the KPIs again.');
    const out = [...list.querySelectorAll('.kpi')].map(c => {
      const base = S.planKpis[+c.dataset.i] || {};
      return {...base, include: $('input[type=checkbox]', c).checked, name: $('.k-name', c).value, label: $('.k-label', c).value,
        format: $('.k-format', c).value, description: $('.k-desc', c).value, dax: $('.k-dax', c).value};
    });
    const fd = new FormData();
    fd.append('payload', JSON.stringify({action, kpis: out, feedback: fb.value, visuals: planVisuals(cvs)}));
    for (const f of files) fd.append(isImage(f) ? 'images' : 'files', f);
    ask.disabled = ok.disabled = att.button.disabled = true;
    try {
      S.project = await upload(`/api/projects/${st.id}/kpis`, fd, p => { if (files.length) ask.textContent = `Uploading ${Math.round(p * 100)}%…`; });
      notify(action === 'confirm' ? 'Plan confirmed — Relay is building the prototype' : 'Sent to Relay — the plan will be revised', 'ok');
      S.key = null; render(); poll(); refreshOrg(true);
    } catch (e) { ask.disabled = ok.disabled = att.button.disabled = false; ask.replaceChildren(...askLabel()); toast(ok, e.message); }
  }
  const actions = h('div', {class: 'card actions'}, h('div', {class: 'ask'}, fb, att.list), att.button, ask, ok, att.input);
  att.dropOn(actions);
  return [
    h('div', {class: 'card'}, h('div', {class: 'row', style: 'margin-bottom:8px'}, h('h3', {style: 'margin:0'}, "Relay's plan")),
      st.plan_summary ? notes(st.plan_summary) : null, plan.summary ? h('p', {class: 'muted'}, plan.summary) : null,
      st.plan_error ? h('div', {class: 'note err'}, st.plan_error) : null),
    dataCard(st),
    planModel(plan),
    h('div', {class: 'card'}, h('div', {class: 'row', style: 'margin-bottom:10px'}, h('h3', {style: 'margin:0'}, 'KPIs ', h('span', {class: 'muted'}, `(${kpis.length})`)),
      h('span', {class: 'muted small'}, 'Edit anything — names, labels, the meaning or the DAX. Untick to drop a KPI.'), h('span', {class: 'spacer'}),
      h('button', {class: 'btn sm', onclick: () => list.append(kpiCard({}, -1))}, icon('plus'), 'Add KPI')), list),
    proposals.length ? h('div', {class: 'card'}, h('div', {class: 'row'}, h('h3', {style: 'margin:0'}, `Custom visuals `, h('span', {class: 'muted'}, `(${proposals.length})`)),
      h('span', {class: 'spacer'}), h('span', {class: 'tag'}, POLICY[st.custom_visuals] || '')),
      h('div', {class: 'muted small', style: 'margin-top:4px'}, 'Nothing in the catalog or the visual library fits these needs well. For each: a new visual built for you (in your colors, added to the library), or the closest available one.'), cvs) : null,
    planPages(plan),
    h('div', {class: 'sticky'}, actions),
  ];
}

/* prototype review */
function notes(text) {
  const paras = String(text || '').trim().split(/\n\s*\n/);
  const box = h('div', {style: 'margin-top:6px'}, rich(paras[0]));
  if (paras.length > 1) box.append(h('details', {class: 'more'}, h('summary', {}, 'Show all notes'), rich(paras.slice(1).join('\n\n'))));
  return box;
}
function daxLine(st, v, dax) {
  if (!dax) return null;
  if (!dax.checked) return h('div', {class: 'daxline muted'}, 'DAX not checked in Power BI\'s engine yet' + (dax.reason ? ` (${dax.reason})` : '') + ' — it is checked before publishing.');
  const bad = dax.problems > 0, diff = Array.isArray(dax.differences) ? dax.differences.length : (dax.differences || 0);
  return h('div', {class: 'daxline'},
    h('span', {class: bad ? 'bad' : 'ok'}, bad ? `⚠ Power BI's engine found ${dax.problems} DAX problem(s)` : '✓ DAX checked in Power BI\'s engine'),
    diff ? h('span', {class: 'bad'}, `⚠ ${diff} value(s) differ from the prototype`) : dax.compared ? h('span', {class: 'ok'}, '✓ values match the prototype') : null,
    h('span', {class: 'muted'}, `${dax.measures} measures · ${dax.visuals} visual queries` + (dax.sampled && dax.sampled.length ? ' · large tables sampled' : '')),
    h('button', {class: 'btn sm', onclick: () => showDax(st, v)}, 'Show values'));
}
/* review gates: every check a version passes before it can be approved, and again before publishing */
const GMARK = {pass: '✓', warn: '!', fail: '✕', skip: '–'};
const gatesFailed = v => ((v && v.gates) || []).filter(g => g.status === 'fail');
function gatesPanel(st, v, opts = {}) {
  const gs = v.gates || [], busy = RUN.has(st.status);
  const run = (label, cls) => busy ? null : h('button', {class: 'btn sm ' + (cls || ''), title: 'Run every gate on this version now (the DAX check it has is reused)',
    onclick: e => runGates(st, v.v, e.currentTarget)}, icon('play'), label);
  if (!gs.length) return h('div', {class: 'gates'}, h('div', {class: 'gh'}, h('b', {}, 'Review gates'),
    h('span', {class: 'muted small'}, 'Not recorded for this version (made before the gates existed) — they run again before publishing.'),
    h('span', {class: 'spacer'}), opts.rerun === false ? null : run('Run review gates')));
  const c = {pass: 0, warn: 0, fail: 0, skip: 0};
  gs.forEach(g => c[g.status]++);
  let details = null;
  const rows = gs.map(g => {
    const n = (g.fails || 0) + (g.warns || 0);
    const gr = h('div', {class: 'gr', title: 'Show what this gate checked and found'}, h('span', {class: 'gi'}, GMARK[g.status]), h('span', {class: 'gn'}, g.name),
      h('span', {class: 'gs'}, g.summary), h('span', {class: 'gx'}, n ? `${n} item${n === 1 ? '' : 's'} ▾` : '▾'));
    const row = h('div', {class: 'gate ' + g.status}, gr);
    gr.onclick = async () => {
      const open = $('.gd', row);
      if (open) return open.remove();
      details = details || await api(`/api/projects/${st.id}/versions/${v.v}/gates`).catch(e => ({error: e.message}));
      const full = Array.isArray(details) ? details.find(x => x.id === g.id) : null;
      row.append(h('div', {class: 'gd'}, full ? h('div', {class: 'std'}, full.standard) : null,
        details.error ? h('div', {class: 'note err'}, details.error) : null,
        full && full.items.length ? h('ul', {}, full.items.map(i => h('li', {class: i.level}, (i.level === 'info' ? 'Note: ' : '') + i.text))) : null,
        g.id === 'dax' && v.dax && v.dax.checked ? h('button', {class: 'btn sm', style: 'margin-top:6px', onclick: () => showDax(st, v.v)}, 'Show every value') : null));
    };
    return row;
  });
  const folded = opts.fold && !c.fail && !S.gatesOpen;           // all passed: one line, open on request
  const toggle = opts.fold && !c.fail ? h('button', {class: 'btn sm ghost', 'aria-expanded': String(!folded),
    onclick: () => { S.gatesOpen = !S.gatesOpen; S.key = null; render(); }}, folded ? 'Show the checks' : 'Hide the checks') : null;
  return h('div', {class: 'gates' + (folded ? ' folded' : '')},
    h('div', {class: 'gh'}, h('b', {}, opts.title || 'Review gates'),
      c.pass ? h('span', {class: 'tag ok'}, `${c.pass} passed`) : null, c.warn ? h('span', {class: 'tag warn'}, `${c.warn} with warnings`) : null,
      c.fail ? h('span', {class: 'tag err'}, `${c.fail} failed`) : null, c.skip ? h('span', {class: 'tag'}, `${c.skip} skipped`) : null,
      h('span', {class: 'spacer'}), toggle, opts.rerun === false ? null : run('Run again', 'ghost')),
    folded ? null : rows);
}
async function runGates(st, v, btn) {
  btn.disabled = true; btn.lastChild.textContent = 'Running the gates…';
  try { S.project = await api(`/api/projects/${st.id}/versions/${v}/gates`, {method: 'POST'}); notify(`Review gates ran for v${v}`, 'ok'); S.key = null; render(); }
  catch (e) { btn.disabled = false; btn.lastChild.textContent = 'Run again'; notify(e.message, 'err'); }
}
function gateFix(st, v) {
  const bad = gatesFailed(v);
  if (!bad.length) return null;
  const btn = h('button', {class: 'btn sm primary', disabled: RUN.has(st.status), title: "Fixing what failed in Relay's own review gates uses no credits", onclick: () => fixGates(st, v, btn)}, 'Ask Relay to fix them');
  return h('div', {class: 'note err gatefix'}, h('span', {style: 'flex:1;min-width:220px'},
    h('b', {}, `v${v.v} did not pass ${bad.length} review gate${bad.length === 1 ? '' : 's'}`), ` (${bad.map(g => g.name).join(', ')}) — approval is locked until they pass.`), btn);
}
async function fixGates(st, v, btn) {
  btn.disabled = true;
  try {
    const all = await api(`/api/projects/${st.id}/versions/${v.v}/gates`);
    const items = all.filter(g => g.status === 'fail').flatMap(g => g.items.filter(i => i.level === 'fail').map(i => `${g.name}: ${i.text}`));
    const fd = new FormData();
    fd.append('text', 'Fix what failed in the review gates, and change nothing else:\n' + items.slice(0, 25).map(t => '- ' + t).join('\n'));
    fd.append('version', v.v);
    fd.append('fix_gates', '1');                 // D2D Relay: fixing what failed in Relay's own checks uses no credits
    S.project = await upload(`/api/projects/${st.id}/feedback`, fd);
    notify('Sent to Relay — it is fixing the failing gates', 'ok'); S.version = null; S.key = null; render(); poll();
  } catch (e) { btn.disabled = false; notify(e.message, 'err'); }
}
async function showDax(st, v) {
  let r;
  try { r = await api(`/api/projects/${st.id}/dax/${v}`); } catch (e) { return modal('DAX check', h('div', {class: 'mbody'}, e.message)); }
  const row = (name, shown, bad) => h('tr', {}, h('td', {}, name), h('td', {class: 'v', style: bad ? 'color:var(--err)' : ''}, shown));
  const show = x => x.error || (x.text !== null && x.text !== undefined && x.text !== '' ? x.text : x.value === null ? '(blank)' : String(x.value));
  modal(`DAX check · v${v}`, h('div', {class: 'mbody'},
    h('p', {class: 'muted small', style: 'margin-top:0'}, `Evaluated by Power BI's own engine (Power BI Desktop ${r.engine || ''}) under the report's default filters, in ${r.seconds} s.`
      + ((r.sampled || []).length ? ' Large tables were checked on a sample, so their values can differ from the full data: ' + r.sampled.join('; ') : '')),
    (r.problems || []).length ? h('div', {class: 'note warn'}, h('b', {}, 'Problems'), h('ul', {}, r.problems.map(p => h('li', {}, p)))) : null,
    (r.differences || []).length ? h('div', {class: 'note warn'}, h('b', {}, 'Values that differ from the prototype'), h('ul', {}, r.differences.map(p => h('li', {}, p))))
      : r.compared ? h('div', {class: 'note ok'}, 'Every visual\'s values and titles match the prototype.') : null,
    h('table', {class: 'utable dax'}, h('tr', {}, h('th', {class: 'l'}, 'Measure'), h('th', {}, 'Value')), (r.values || []).map(x => row(x.name, show(x), !!x.error))),
    h('h4', {class: 'uhead'}, 'Visual queries'),
    h('table', {class: 'utable dax'}, h('tr', {}, h('th', {class: 'l'}, 'Visual'), h('th', {}, 'Rows')), (r.visual_rows || []).map(x => row(x.name, x.error || String(x.rows), !!x.error)))));
}
function customCard(st, v) {
  const used = v.custom_visuals || [], open = ((st.visuals && st.visuals.proposals) || []).filter(p => !p.decision);
  if (!used.length && !open.length) return null;
  const busy = RUN.has(st.status);
  const decide = async (name, decision, btn) => {
    btn.disabled = true;
    try { S.project = await api(`/api/projects/${st.id}/custom-visuals`, {json: {name, decision}}); notify(decision === 'generate' ? 'Relay will build it' : 'Kept the available visual', 'ok'); S.key = null; render(); poll(); refreshOrg(true); }
    catch (e) { btn.disabled = false; toast(btn, e.message); }
  };
  const item = c => c.origin === 'project'
    ? h('a', {class: 'cvitem', href: `/api/projects/${st.id}/visuals/${c.name}/preview`, target: '_blank', title: 'Browser test of the visual'},
        h('img', {src: `/api/projects/${st.id}/visuals/${c.name}/preview`, alt: ''}), h('div', {}, h('b', {class: 'small'}, c.title), h('div', {class: 'muted small'}, `new · v${c.version}`)))
    : h('a', {class: 'cvitem', href: '#/library', title: 'From the visual library'},
        h('img', {src: `/api/library/${c.name}/preview`, alt: ''}), h('div', {}, h('b', {class: 'small'}, c.title), h('div', {class: 'muted small'}, 'from the library')));
  return h('div', {class: 'note'},
    used.length ? h('div', {}, h('b', {}, 'Custom visuals in this version'), h('div', {class: 'cvlist'}, used.map(item))) : null,
    open.map(p => {
      const gen = h('button', {class: 'btn sm primary', disabled: busy, onclick: e => decide(p.name, 'generate', e.currentTarget)}, '✦ Build it', costTag('change'));
      const keep = h('button', {class: 'btn sm', disabled: busy, onclick: e => decide(p.name, 'available', e.currentTarget)}, 'Keep ' + (p.fallback || 'the available visual'));
      return h('div', {class: 'cv'}, h('div', {class: 'ttl'}, h('b', {}, 'Relay suggests a custom visual: ' + (p.title || p.name))),
        p.need ? h('div', {class: 'need small'}, p.need) : null,
        h('div', {class: 'muted small'}, 'This version uses ' + (p.fallback || 'the closest available visual') + ' instead.'), h('div', {class: 'choice'}, gen, keep));
    }));
}
function reviewView(st) {
  const vs = st.versions;
  const v = vs.find(x => x.v === S.version) || vs[vs.length - 1];
  const latest = vs[vs.length - 1].v;
  const fb = h('textarea', {rows: 3, id: 'feedback', placeholder: (v.v === latest ? 'What should change? e.g. "Add a page for suppliers", "Show margin instead of sales on the quadrant", "Use blue as the accent"'
    : `Changes start from v${v.v} (it becomes the base again).`) + ' — attach CSVs or images if it needs more data or a design.'});
  const changeLabel = () => ['Request changes', costTag('change')];
  const change = h('button', {class: 'btn', onclick: send}, ...changeLabel());
  const approved = st.status === 'done' && st.approved === v.v, blocked = gatesFailed(v).length > 0;
  const approveBtn = h('button', {class: 'btn primary', onclick: doApprove, disabled: approved || blocked,
    title: blocked ? 'Approval is locked until every review gate passes' : ''}, icon('publish'), approved ? `v${v.v} published` : `Approve v${v.v} & publish`);
  const att = attacher();
  async function send() {
    const files = att.files();
    if (!fb.value.trim() && !files.length) return toast(approveBtn, 'Describe the changes you want, or attach files.');
    const fd = new FormData();
    fd.append('text', fb.value); fd.append('version', v.v);
    for (const f of files) fd.append(isImage(f) ? 'images' : 'files', f);
    change.disabled = approveBtn.disabled = att.button.disabled = true;
    try {
      S.project = await upload(`/api/projects/${st.id}/feedback`, fd, p => { if (files.length) change.textContent = `Uploading ${Math.round(p * 100)}%…`; });
      notify('Sent to Relay — a new version is on its way', 'ok'); S.version = null; S.key = null; render(); poll(); refreshOrg(true);
    } catch (e) { change.disabled = att.button.disabled = false; approveBtn.disabled = approved || blocked; change.replaceChildren(...changeLabel()); toast(approveBtn, e.message); }
  }
  async function doApprove() { change.disabled = approveBtn.disabled = true; await approve(st, v.v); }
  const actions = h('div', {class: 'card actions'}, h('div', {class: 'ask'}, fb, att.list), att.button, change, approveBtn, att.input);
  att.dropOn(actions);
  return [
    h('div', {class: 'card'},
      h('div', {class: 'row'}, h('h3', {style: 'margin:0'}, 'Prototype'),
        h('div', {class: 'vers'}, vs.map(x => h('button', {class: x.v === v.v ? 'on' : '', title: x.label || '',
          onclick: () => { S.version = x.v; S.key = null; render(); }}, 'v' + x.v, published(st, x.v).length ? h('span', {class: 'ap'}, '✓') : null))),
        v.label ? h('span', {class: 'tag acc'}, v.label) : null,
        h('span', {class: 'spacer'}), h('span', {class: 'muted small'}, `${v.pages.length} pages · ${v.visuals} visuals · ${v.measures} measures`),
        h('a', {class: 'btn sm ghost', href: `#/p/${st.id}/versions`, onclick: () => { S.vsel = v.v; }}, icon('clock'), 'History & changes'),
        h('a', {class: 'btn sm', href: `/api/projects/${st.id}/prototype/${v.v}`, target: '_blank'}, icon('external'), 'Open')),
      v.feedback ? h('div', {class: 'note'}, h('b', {}, 'You asked: '), v.feedback.replace(/^\(Start from[^)]*\)\s*/, ''), attachedList(v.attachments)) : null,
      v.summary ? h('div', {style: 'margin-top:8px'}, h('div', {class: 'muted small', style: 'font-weight:600'}, 'Relay'), notes(v.summary)) : null,
      protoFrame(`/api/projects/${st.id}/prototype/${v.v}`),
      customCard(st, v),
      (v.gates || []).length ? [gateFix(st, v), approved && (st.output || {}).gates ? null : gatesPanel(st, v, {fold: true})]
        : [daxLine(st, v.v, v.dax), v.problems && v.problems.length ? h('div', {class: 'note warn'}, `${v.problems.length} item(s) were still flagged when this version was made:`,
            h('ul', {}, v.problems.slice(0, 8).map(p => h('li', {}, p)))) : null, gatesPanel(st, v)]),
    h('div', {class: 'sticky'}, actions),
  ];
}
function doneCard(st) {
  const o = st.output || {};
  return h('div', {class: 'card'},
    h('div', {class: 'row'}, h('h3', {style: 'margin:0'}, 'Your Power BI project'), h('span', {class: 'spacer'}),
      h('a', {class: 'btn primary', href: `/api/projects/${st.id}/download`}, icon('download'), 'Download ', o.zip || 'zip')),
    h('div', {class: 'muted small', style: 'margin-top:4px'}, `${o.pbip} · ${o.pages} pages · ${o.visuals} visuals · ${o.measures} measures · from prototype v${st.approved}`),
    (o.gates || []).length ? gatesPanel(st, {v: st.approved, gates: o.gates, dax: {...(o.dax || {}), checked: true}}, {title: 'Review gates passed before publishing', rerun: false})
      : o.dax ? daxLine(st, st.approved, {...o.dax, problems: 0}) : null,
    (o.custom_visuals || []).length ? h('div', {class: 'small', style: 'margin-top:6px'}, '✦ Custom visuals: ' + o.custom_visuals.join(', ') + ' — embedded in the report; their .pbiviz files are in custom-visuals/ in the download.') : null,
    h('div', {class: 'done-grid'},
      h('div', {}, h('b', {}, 'Open it on this PC'), h('div', {class: 'small muted'}, 'Open the .pbip in Power BI Desktop and press Refresh. Close an open copy without saving first.'),
        o.pbip_path ? h('div', {class: 'path'}, h('code', {}, o.pbip_path), copyBtn(o.pbip_path)) : h('div', {class: 'small'}, 'Unzip the download and open the .pbip file.')),
      h('div', {}, h('b', {}, 'Data'), h('div', {class: 'small muted'}, 'The model loads the CSVs from the DataFolder parameter:'),
        h('div', {class: 'path'}, h('code', {}, o.data_folder || ''), copyBtn(o.data_folder || '')),
        h('div', {class: 'small muted', style: 'margin-top:4px'}, o.data_in_zip ? 'The zip also contains the CSVs.' : 'The CSVs are not in the zip (large) — they stay in the folder above.'))));
}

