/* ---------------- plan tab (read-only) ---------------- */
function planTab(st) {
  const plan = st.plan;
  if (!plan) return [h('div', {class: 'card empty'}, h('h3', {}, 'No plan yet'), 'Relay writes the plan first: data model, KPIs with their formulas, and the pages.')];
  const kpis = plan.kpis || [], proposals = (st.visuals && st.visuals.proposals) || [];
  return [
    st.status === 'awaiting_kpis' ? h('div', {class: 'note'}, 'This is the plan waiting for you. ', h('a', {href: `#/p/${st.id}/overview`}, 'Edit and confirm it in Overview →')) : null,
    h('div', {class: 'card'}, h('h3', {}, 'Summary'), st.plan_summary ? notes(st.plan_summary) : null, plan.summary ? h('p', {class: 'muted'}, plan.summary) : null),
    dataCard(st),
    planModel(plan),
    teamMetricsCard(st, kpis),
    proposals.length ? h('div', {class: 'card'}, h('h3', {}, 'Custom visuals'), proposals.map(p => h('div', {class: 'cv'},
      h('div', {class: 'ttl'}, h('b', {}, p.title || p.name), h('span', {class: 'faint small mono'}, p.name),
        h('span', {class: 'tag ' + (p.decision === 'generate' ? 'acc' : p.decision ? '' : 'warn')}, p.decision === 'generate' ? 'Build it' : p.decision === 'available' ? 'Use available: ' + (p.fallback || '') : 'Not decided')),
      p.need ? h('div', {class: 'small'}, p.need) : null))) : null,
    planPages(plan),
  ];
}

/* ---------------- versions: history, what changed, compare ---------------- */
function versionsTab(st) {
  const vs = st.versions;
  if (!vs.length) return [h('div', {class: 'card empty'}, h('h3', {}, 'No versions yet'), 'Relay makes version 1 after you confirm the plan. Every change request makes a new version; earlier versions are kept.')];
  const sel = vs.find(x => x.v === S.vsel) || vs[vs.length - 1];
  const list = h('div', {class: 'vlist'}, [...vs].reverse().map(x => {
    const pubs = published(st, x.v), latest = x.v === vs[vs.length - 1].v;
    return h('div', {class: 'vitem' + (x.v === sel.v ? ' on' : ''), onclick: () => { S.vsel = x.v; S.key = null; render(); }},
      h('div', {class: 'l1'}, h('span', {class: 'vn'}, 'v' + x.v), x.label ? h('span', {class: 'lab'}, x.label) : null, h('span', {class: 'spacer'}),
        latest ? h('span', {class: 'tag'}, 'Latest') : null, pubs.length ? h('span', {class: 'tag ok'}, icon('check'), 'Published') : null),
      h('div', {class: 'l2'}, when(x.created)),
      h('div', {class: 'l3'}, x.feedback ? '“' + x.feedback.replace(/^\(Start from[^)]*\)\s*/, '') + '”' : 'First build from the confirmed plan'));
  }));
  return [h('div', {class: 'vwrap'}, list, versionDetail(st, sel))];
}
function versionDetail(st, v) {
  const vs = st.versions, prev = vs.filter(x => x.v < v.v).pop(), pubs = published(st, v.v);
  const canAct = !RUN.has(st.status);
  const changes = h('div', {class: 'chg'}, h('div', {class: 'muted small'}, 'Loading changes…'));
  loadChanges(st, v.v).then(ch => changes.replaceChildren(changesView(ch))).catch(e => changes.replaceChildren(h('div', {class: 'note err'}, e.message)));
  const labelInput = h('input', {type: 'text', value: v.label || '', placeholder: 'Name this version, e.g. "Sent to CFO"', maxlength: 60});
  const saveLabel = async () => {
    try { S.project = await api(`/api/projects/${st.id}/versions/${v.v}/label`, {json: {label: labelInput.value}}); notify('Version name saved', 'ok'); S.key = null; render(); }
    catch (e) { notify(e.message, 'err'); }
  };
  labelInput.addEventListener('keydown', e => { if (e.key === 'Enter') saveLabel(); });
  const usage = st.usage && st.usage.by['v' + v.v];
  return h('div', {},
    h('div', {class: 'card'},
      h('div', {class: 'row'}, h('h2', {style: 'margin:0'}, `Version ${v.v}`), v.label ? h('span', {class: 'tag acc'}, v.label) : null,
        v.v === vs[vs.length - 1].v ? h('span', {class: 'tag'}, 'Latest') : null, pubs.length ? h('span', {class: 'tag ok'}, icon('check'), 'Published') : null,
        h('span', {class: 'spacer'}), h('span', {class: 'muted small'}, when(v.created))),
      h('div', {class: 'row', style: 'margin-top:12px'},
        h('a', {class: 'btn sm', href: `/api/projects/${st.id}/prototype/${v.v}`, target: '_blank'}, icon('external'), 'Open prototype'),
        h('button', {class: 'btn sm', onclick: () => go('overview', v.v)}, icon('play'), 'View in Overview'),
        prev ? h('button', {class: 'btn sm', onclick: () => compareModal(st, prev.v, v.v)}, icon('columns'), `Compare with v${prev.v}`) : null,
        canAct && v.v !== vs[vs.length - 1].v ? h('button', {class: 'btn sm', title: 'Your next change request starts from this version',
          onclick: () => { go('overview', v.v); setTimeout(() => { const f = $('#feedback'); if (f) { f.focus(); f.scrollIntoView({block: 'center'}); } }, 300); }}, icon('back'), 'Make changes from this version') : null,
        h('a', {class: 'btn sm ghost', href: `/api/projects/${st.id}/versions/${v.v}/definition`}, icon('download'), 'Definition (YAML)'),
        h('span', {class: 'spacer'}),
        canAct && !(st.status === 'done' && st.approved === v.v) ? h('button', {class: 'btn sm primary', disabled: gatesFailed(v).length > 0,
          title: gatesFailed(v).length ? 'Approval is locked until every review gate passes' : '', onclick: () => approve(st, v.v)}, icon('publish'), `Approve v${v.v} & publish`) : null),
      h('div', {class: 'labedit', style: 'margin-top:12px'}, labelInput, h('button', {class: 'btn sm', onclick: saveLabel}, 'Save name'))),
    h('div', {class: 'card'}, h('h3', {}, prev ? `What changed since v${prev.v}` : 'What this first version contains'),
      v.feedback ? h('div', {class: 'note'}, h('b', {}, 'Request: '), v.feedback.replace(/^\(Start from[^)]*\)\s*/, ''), attachedList(v.attachments)) : null,
      changes),
    h('div', {class: 'card'}, h('h3', {}, 'Review gates & contents'),
      gateFix(st, v), gatesPanel(st, v),
      h('dl', {class: 'kv', style: 'margin-top:14px'},
        (v.gates || []).length ? null : [
          h('dt', {}, 'Prototype'), h('dd', {}, v.problems && v.problems.length ? h('span', {style: 'color:var(--warn)'}, `${v.problems.length} item(s) flagged`) : h('span', {style: 'color:var(--ok)'}, '✓ every visual rendered')),
          h('dt', {}, 'Power BI engine'), h('dd', {}, v.dax ? daxLine(st, v.v, v.dax) : h('span', {class: 'muted'}, 'not recorded for this version'))],
        h('dt', {}, 'Contents'), h('dd', {}, `${v.pages.length} pages (${v.pages.join(', ')}) · ${v.visuals} visuals · ${v.measures} measures · ${v.tables} tables`),
        (v.custom_visuals || []).length ? [h('dt', {}, 'Custom visuals'), h('dd', {}, v.custom_visuals.map(c => `${c.title} (${c.origin === 'project' ? 'new' : 'library'})`).join(', '))] : null,
        usage ? [h('dt', {}, 'Relay'), h('dd', {}, `${spendModel(usage)} · ${dur(usage.duration_ms)}`)] : null,
        pubs.length ? [h('dt', {}, 'Published'), h('dd', {}, pubs.map(p => h('div', {}, `${when(p.when)} · ${p.pbip || ''}` + (p.dax ? ' · DAX checked' : ''))))] : null),
      !(v.gates || []).length && v.problems && v.problems.length ? h('details', {class: 'more'}, h('summary', {}, 'Show flagged items'), h('ul', {class: 'small'}, v.problems.map(p => h('li', {}, p)))) : null),
    v.summary ? h('div', {class: 'card'}, h('h3', {}, "Relay's notes"), notes(v.summary)) : null);
}
async function loadChanges(st, v, against) {
  const key = v + ':' + (against || '');
  if (!S.changes[key]) S.changes[key] = api(`/api/projects/${st.id}/versions/${v}/changes` + (against ? `?against=${against}` : ''));
  return S.changes[key];
}
function changesView(ch) {
  const sections = ch.sections || [];
  const mark = {added: '+', removed: '−', changed: '~'};
  return h('div', {},
    h('div', {class: 'chips'}, (ch.summary || []).map(s => h('span', {class: 'tag acc'}, s))),
    sections.map(sec => {
      const item = i => h('li', {}, h('span', {class: 'k ' + i.kind}, mark[i.kind]), h('div', {style: 'min-width:0'}, i.text,
        i.before || i.after ? h('details', {}, h('summary', {class: 'small', style: 'cursor:pointer;color:var(--accent)'}, i.before && i.after ? 'Show before / after' : 'Show formula'),
          h('div', {class: 'ba'}, i.before ? [h('span', {class: 'b'}, 'before'), h('span', {}, i.before)] : null, i.after ? [h('span', {class: 'a'}, 'after'), h('span', {}, i.after)] : null)) : null));
      const head = sec.items.slice(0, 10), rest = sec.items.slice(10);
      return h('div', {}, h('h4', {}, sec.title, h('span', {class: 'muted', style: 'font-weight:400'}, ` · ${sec.items.length}`)),
        h('ul', {}, head.map(item)), rest.length ? h('details', {class: 'more'}, h('summary', {}, `Show ${rest.length} more`), h('ul', {}, rest.map(item))) : null);
    }));
}
function compareModal(st, a, b) {
  const vs = st.versions.map(x => x.v);
  const pickA = h('select', {class: 'sel', style: 'width:auto'}, vs.map(n => h('option', {value: n, selected: n === a}, 'v' + n)));
  const pickB = h('select', {class: 'sel', style: 'width:auto'}, vs.map(n => h('option', {value: n, selected: n === b}, 'v' + n)));
  const body = h('div', {class: 'mbody'});
  const draw = () => {
    let x = +pickA.value, y = +pickB.value;
    if (x > y) [x, y] = [y, x];
    const chg = h('div', {class: 'chg'}, h('div', {class: 'muted small'}, 'Loading changes…'));
    loadChanges(st, y, x !== y ? x : undefined).then(c => chg.replaceChildren(x === y ? h('div', {class: 'muted'}, 'Same version.') : changesView(c)))
      .catch(e => chg.replaceChildren(h('div', {class: 'note err'}, e.message)));
    body.replaceChildren(h('div', {class: 'row', style: 'margin-bottom:12px'}, h('b', {}, 'Compare'), pickA, h('span', {class: 'muted'}, 'with'), pickB),
      h('div', {class: 'cmpgrid'}, [x, y].map(n => h('div', {}, h('div', {class: 'row'}, h('b', {}, 'v' + n), (st.versions.find(q => q.v === n) || {}).label ? h('span', {class: 'tag acc'}, st.versions.find(q => q.v === n).label) : null,
        h('span', {class: 'spacer'}), h('a', {class: 'btn sm', href: `/api/projects/${st.id}/prototype/${n}`, target: '_blank'}, icon('external'), 'Open')), protoFrame(`/api/projects/${st.id}/prototype/${n}`)))),
      h('h3', {style: 'margin-top:18px'}, `What changed from v${x} to v${y}`), chg);
  };
  pickA.onchange = pickB.onchange = draw;
  draw();
  modal(`Compare versions · ${st.name}`, body, true);
}

/* ---------------- activity log ---------------- */
function friendly(e) {
  const d = String(e.detail || '');
  if (e.tool === 'Bash') {
    const m = d.match(/genbi\s+(\w+)(?:\s+(\w+))?/);
    if (m) {
      const visual = {new: 'Started a custom visual', edit: 'Opened a library visual to change it', build: 'Compiled a custom visual',
        test: 'Tested a custom visual in a browser', list: 'Listed custom visuals', source: 'Read a visual template'};
      return m[1] === 'visual' ? visual[m[2]] || 'Worked on a custom visual' : {profile: 'Profiled the data', sql: 'Queried the data',
        validate: 'Checked the report definition', prototype: 'Rendered the prototype', daxcheck: "Checked the DAX in Power BI's engine",
        build: 'Wrote the Power BI files', catalog: 'Looked up the visual catalog'}[m[1]] || 'Ran a Relay tool';
    }
    return 'Ran a command';
  }
  const f = fileLabel(d);
  // Claude Code's tool names, and the other runners' (Codex, Gemini, Antigravity), in words; anything else as "Used …"
  const said = {Read: 'Read ' + f, Write: 'Wrote ' + f, Edit: 'Edited ' + f, MultiEdit: 'Edited ' + f, Glob: 'Searched for files', Grep: 'Searched in files',
    TodoWrite: 'Updated its task list', WebFetch: 'Read a web page', WebSearch: 'Searched the web', run_command: 'Ran a command', shell: 'Ran a command',
    exec_command: 'Ran a command', read_file: 'Read ' + f, read_many_files: 'Read some files', write_file: 'Wrote ' + f, edit_file: 'Edited ' + f, replace: 'Edited ' + f,
    apply_patch: 'Edited ' + f, list_directory: 'Listed files', list_dir: 'Listed files', glob: 'Searched for files', search_file_content: 'Searched in files',
    grep_search: 'Searched in files', web_fetch: 'Read a web page', google_web_search: 'Searched the web', update_plan: 'Updated its task list'}[e.tool];
  return said || (e.tool ? 'Used ' + String(e.tool).replace(/[_-]+/g, ' ').toLowerCase() : 'Step');
}
/* a project file in words: "request.md" -> "your request"; other files by their name, without the folders */
const FILE_WORDS = {'request.md': 'your request', 'plan.md': 'the plan', 'kpis.md': 'the KPIs', 'kpis.json': 'the KPIs', 'feedback.md': 'your feedback',
  'data.md': 'the data notes', 'model.bim': 'the data model', 'report.json': 'the report definition'};
function fileLabel(path) {
  const base = String(path || '').split(/[\\/]/).pop();
  return FILE_WORDS[base.toLowerCase()] || base || 'a file';
}
/* Older activity lines name the model's maker ("Claude is reading your data…"); the app speaks as Relay, or the partner's
   brand. Display only: the saved log is unchanged. */
const brandSay = t => typeof t === 'string' ? t.replace(/\bClaude Code\b/g, 'the agent').replace(/\bClaude\b/g, typeof brandName === 'function' ? brandName() : 'Relay') : t;
/* the live "Now:" line says what Relay is doing, not what it did */
function doing(e) {
  const f = fileLabel(e.detail);
  return {Read: 'reading ' + f, Write: 'writing ' + f, Edit: 'editing ' + f, Glob: 'looking for files', Grep: 'searching the files',
    TodoWrite: 'updating its task list'}[e.tool] || friendly(e).replace(/^\w/, c => c.toLowerCase());
}
const isStep = e => e.kind === 'tool' || e.kind === 'result';
function eventRow(e) {
  const t = h('span', {class: 'faint'}, clock(e.ts));
  const row = (av, who, body, cls) => h('div', {class: 'ev ' + (cls || '')}, h('div', {class: 'av ' + av}, typeof who === 'string' ? who : who), body);
  if (e.kind === 'user') return row('you', icon('user'), h('div', {}, h('div', {class: 'hd'}, h('b', {}, 'You'), t), h('div', {class: 'bd'}, rich(e.text), attachedList(e.attachments))));
  if (e.kind === 'say') return row('claude', icon('spark'), h('div', {}, h('div', {class: 'hd'}, h('b', {}, 'Relay'), t), h('div', {class: 'bd'}, rich(e.text))));
  if (e.kind === 'app') {
    const lvl = {ok: 'ok', warn: 'warn', error: 'err'}[e.level] || 'neutral';
    return row(lvl, icon(lvl === 'ok' ? 'check' : lvl === 'neutral' ? 'info' : 'alert'), h('div', {}, h('div', {class: 'hd'}, h('b', {}, 'Relay'), t),
      h('div', {class: 'bd'}, brandSay(e.text), e.items ? h('ul', {}, e.items.slice(0, 15).map(i => h('li', {}, brandSay(i)))) : null)));
  }
  if (e.kind === 'start') return row('neutral', icon('play'), h('div', {class: 'bd'}, 'Relay started working', e.model && modelName(e.model) ? ` · ${modelName(e.model)}` : '', ' ', t), 'quiet');
  if (e.kind === 'done') return row(e.ok ? 'ok' : 'warn', icon(e.ok ? 'check' : 'alert'), h('div', {class: 'bd'}, e.ok ? 'Relay finished' : `Relay stopped (${e.subtype || 'error'})`,
    e.turns ? ` · ${e.turns} steps` : '', e.duration_ms ? ` · ${dur(e.duration_ms)}` : '', e.usage ? ` · ${tok(runTokens(e.usage))} tokens` : '', e.cost_usd != null ? ` · ${usd(e.cost_usd)}` : '', ' ', t), 'quiet');
  if (e.kind === 'error') return row('err', icon('alert'), h('div', {}, h('div', {class: 'hd'}, h('b', {}, 'Error'), t), h('div', {class: 'bd', style: 'color:var(--err)'}, e.text)));
  return null;
}
function stepRow(e, results) {
  const res = e.id && results[e.id];
  return h('div', {class: 'tstep'}, h('div', {class: 'w'}, friendly(e)), h('div', {class: 'dd'}, e.tool === 'Bash' || !['Read', 'Write', 'Edit'].includes(e.tool) ? e.detail || '' : ''),
    res ? h('div', {class: 'res' + (res.ok ? '' : ' bad')}, res.text || '(no output)') : null);
}
/* The timeline: business events in full, Relay's tool steps folded into "N steps" (or listed, in Everything mode). */
function buildTimeline(container, events, mode, query) {
  const results = {};
  events.forEach(e => { if (e.kind === 'result' && e.id) results[e.id] = e; });
  const q = (query || '').toLowerCase().trim();
  const match = e => !q || [e.text, e.detail, e.tool, (e.items || []).join(' ')].join(' ').toLowerCase().includes(q);
  let stage = null, group = null;
  const out = [];
  const flush = () => {
    if (!group) return;
    const g = group;
    const det = h('details', {class: 'steps-group'}, h('summary', {}, icon('gear'), `${g.length} step${g.length === 1 ? '' : 's'} by Relay`,
      h('span', {class: 'faint'}, ' — ' + friendly(g[g.length - 1])), h('span', {class: 'spacer'}), h('span', {class: 'faint'}, clock(g[0].ts))));
    det.addEventListener('toggle', () => { if (det.open && det.children.length === 1) det.append(...g.map(e => stepRow(e, results))); });
    out.push(det); group = null;
  };
  for (const e of events) {
    if (e.kind === 'result' || !match(e)) continue;
    if (e.stage && e.stage !== stage) { flush(); stage = e.stage; out.push(h('div', {class: 'stage'}, STAGES[e.stage] || e.stage, h('span', {class: 'faint', style: 'text-transform:none;letter-spacing:0;font-weight:500'}, when(e.ts)))); }
    if (e.kind === 'tool') {
      if (mode === 'all' || q) { flush(); out.push(stepRow(e, results)); }
      else (group = group || []).push(e);
      continue;
    }
    flush();
    const r = eventRow(e);
    if (r) out.push(r);
  }
  flush();
  container.replaceChildren(...(out.length ? out : [h('div', {class: 'empty'}, q ? 'Nothing matches.' : 'Nothing has happened yet.')]));
}
function activityTab(st) {
  const list = h('div', {class: 'tl', id: 'actlist'});
  const modeBtn = (m, label) => h('button', {class: S.actMode === m ? 'on' : '', onclick: () => { S.actMode = m; S.key = null; render(); }}, label);
  const search = h('input', {type: 'text', placeholder: 'Search the log…', value: S.actQuery});
  let t = null;
  search.oninput = () => { clearTimeout(t); t = setTimeout(() => { S.actQuery = search.value; buildTimeline(list, S.events, S.actMode, S.actQuery); }, 250); };
  const tz = new Date().getTimezoneOffset();
  const exp = (fmt, detail, label) => h('a', {class: 'btn sm', href: `/api/projects/${st.id}/activity/export?fmt=${fmt}&detail=${detail}&tz=${tz}`}, icon('download'), label);
  buildTimeline(list, S.events, S.actMode, S.actQuery);
  S.act = {count: S.events.length};
  return [h('div', {class: 'toolbar'}, h('div', {class: 'segbtn'}, modeBtn('summary', 'Summary'), modeBtn('all', 'Every step')), search, h('span', {class: 'spacer'}),
    exp('md', 'summary', 'Export summary'), exp('md', 'all', 'Export full log'), exp('csv', 'all', 'CSV')), list];
}
/* the compact live log on Overview while Relay works */
function renderLive() {
  const box = $('#livelog'), now = $('#now');
  if (!box) return;
  const shown = S.events.filter(e => !isStep(e)).slice(-6);
  const tl = h('div', {});
  buildTimeline(tl, shown, 'summary', '');
  box.replaceChildren(...tl.childNodes);
  const lastTool = [...S.events].reverse().find(e => e.kind === 'tool');
  const lastSay = [...S.events].reverse().find(e => e.kind === 'say' || e.kind === 'app');
  if (now) now.replaceChildren(h('div', {class: 'spin', style: 'width:12px;height:12px;border-width:2px'}),
    lastTool && (!lastSay || lastTool.seq > lastSay.seq) ? `Now ${doing(lastTool)}…` : 'Working…');
}

/* ---------------- details tab ---------------- */
function usageTable(st) {
  const u = st.usage || {by: {}, total: {}}, vs = st.versions || [];
  const label = k => k === 'plan' ? 'Plan & KPIs' : /^v\d+$/.test(k) ? `${k} · ${(vs.find(x => 'v' + x.v === k) || {}).feedback ? 'change request' : 'first build'}` : k;
  const rank = k => k === 'plan' ? 0 : /^v\d+$/.test(k) ? +k.slice(1) : 1e6;
  const num = v => h('td', {class: 'n'}, v);
  const row = (name, g, cls) => h('tr', {class: cls || ''}, h('td', {}, name), h('td', {}, modelsText(g.models)), num(g.runs), num(dur(g.duration_ms)),
    num((g.complete ? '' : '≥ ') + tok(g.tokens)), num(tok(g.output)), num(usd(g.cost_usd)));
  const models = Object.entries(u.by_model || {}).sort((a, b) => b[1].cost_usd - a[1].cost_usd);
  return h('div', {},
    h('table', {class: 'utable'}, h('thead', {}, h('tr', {}, ['Step', 'Model', 'Runs', 'Time', 'Tokens', 'Written', 'Est. cost'].map(c => h('th', {class: c === 'Model' ? 'l' : null}, c)))),
      h('tbody', {}, Object.keys(u.by).sort((a, b) => rank(a) - rank(b)).map(k => row(label(k), u.by[k])),
        st.output ? h('tr', {}, h('td', {}, 'Power BI build'), h('td', {}, 'no AI'), num('–'), num('–'), num('0'), num('–'), num('$0.00')) : null,
        u.total.runs ? row('Whole dashboard', u.total, 'total') : null)),
    models.length ? [h('h4', {class: 'uhead'}, 'By model'), h('table', {class: 'utable'},
      h('thead', {}, h('tr', {}, ['Model', 'Runs', 'Tokens', 'Written', 'Est. cost'].map(c => h('th', {}, c)))),
      h('tbody', {}, models.map(([m, g]) => h('tr', {}, h('td', {}, modelName(m) || 'Set by an admin'), num(g.runs), num(tok(g.tokens)), num(tok(g.output)), num(usd(g.cost_usd))))))] : null,
    h('div', {class: 'unotes'}, h('p', {}, "Tokens count everything Relay processed; most are cache reads, which cost a fraction of normal input. Costs are the agent's own estimates at the list price of the model each run used.")));
}
const VISUALS_LABEL = {relay: 'Relay & Atlas custom visuals', builtin: "Power BI's built-in visuals only", mixed: 'Built-in first, custom where needed'};
// Which visuals the next versions use; editors can change it (the next plan, build or change follows it).
function visualsSetting(st) {
  const mode = st.visuals_mode || 'relay';
  if (!(st.access && st.access.can_edit)) return VISUALS_LABEL[mode] || mode;
  const sel = h('select', {class: 'sel', 'aria-label': 'Visuals for the next versions', style: 'max-width:340px'},
    Object.entries(VISUALS_LABEL).map(([v, t]) => h('option', {value: v, selected: v === mode}, t)));
  sel.onchange = async () => {
    sel.disabled = true;
    try { S.project = await api(`/api/projects/${st.id}/visuals`, {json: {mode: sel.value}}); notify(`Visuals: ${VISUALS_LABEL[sel.value]} — for the next versions`, 'ok'); S.key = null; render(); }
    catch (e) { notify(e.message, 'err'); sel.value = mode; sel.disabled = false; }
  };
  return [sel, h('div', {class: 'muted small'}, 'Applies from the next plan, build or change.')];
}
function detailsTab(st) {
  const style = st.style || {};
  const host = st.host_dir, o = st.output || {};
  return [h('div', {class: 'dgrid'},
    h('div', {},
      requestCard(st),
      h('div', {class: 'card'}, h('h3', {}, 'Settings'), h('dl', {class: 'kv'},
        h('dt', {}, 'AI model'), h('dd', {}, modelName(st.model) || 'Set by an admin', h('span', {class: 'muted small'}, ' — change it at the top of the page')),
        h('dt', {}, 'Visuals'), h('dd', {}, visualsSetting(st)),
        h('dt', {}, 'Custom visuals'), h('dd', {}, {ask: 'Ask me in the plan', auto: 'Build when they fit better', never: 'Only available visuals'}[st.custom_visuals] || st.custom_visuals),
        h('dt', {}, 'Visual style'), h('dd', {}, [style.look ? `look ${style.look}` : null, style.accent ? `brand ${style.accent} (${style.palette})` : null, style.dark ? 'dark' : null].filter(Boolean).join(', ') || 'Relay decides'))),
      h('div', {class: 'card'}, h('h3', {}, 'On this PC'), h('dl', {class: 'kv'},
        host ? [h('dt', {}, 'Project folder'), h('dd', {}, h('div', {class: 'path', style: 'margin:0'}, h('code', {}, host), copyBtn(host)))] : null,
        o.pbip_path ? [h('dt', {}, 'Power BI project'), h('dd', {}, h('div', {class: 'path', style: 'margin:0'}, h('code', {}, o.pbip_path), copyBtn(o.pbip_path)))] : null,
        o.data_folder ? [h('dt', {}, 'Data folder'), h('dd', {}, h('div', {class: 'path', style: 'margin:0'}, h('code', {}, o.data_folder), copyBtn(o.data_folder)))] : null))),
    h('div', {},
      st.warehouse || (st.files || []).some(f => f.warehouse) ? warehouseCard(st) : null,
      h('div', {class: 'card'}, h('h3', {}, 'Files'), h('div', {class: 'muted small', style: 'margin:-6px 0 6px'}, 'What Relay and you wrote along the way — the request log, the plan and the report definition.'),
        h('div', {class: 'files'}, (st.files_available || []).map(n => h('button', {onclick: () => viewFile(n)}, icon('file'), h('span', {}, FILES[n] || n), h('span', {class: 'faint mono'}, n))))),
      h('div', {class: 'card'}, h('h3', {}, 'AI usage'), usageTable(st))))];
}
async function viewFile(name) {
  const text = await api(`/api/projects/${S.pid}/files/${encodeURIComponent(name)}`).catch(e => 'Could not load: ' + e.message);
  modal(`${FILES[name] || name} · ${name}`, h('pre', {}, text));
}

