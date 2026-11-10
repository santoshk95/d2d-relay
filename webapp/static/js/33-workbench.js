/* ---------------- Module workbench: a module with a pack is live at #/m/<id>/<work> — its work items, the New work
   wizard, and each item's page at #/m/<id>/i/<item> (the journey, the step's view, confirm or correct in place,
   evidence one click away, outputs, activity, decisions, Run & support). Modules without a pack keep the placeholder
   (renderModule in 20-modules.js). GET /api/m/<id>/overview, /api/m/<id>/items/<item>. Colours are tokens only. ---------------- */
(function wbStyles() {
  document.head.append(h('style', {}, `
  .wbj li{padding-right:6px}.wbj li>button{display:block;width:100%;text-align:left;background:none;border:0;padding:0 0 4px;font:inherit;color:inherit;cursor:pointer;border-radius:6px}
  .wbj li>button:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
  .wbj li.wait .dot{background:var(--you);border-color:var(--you)}.wbj li.err .dot{background:var(--err);border-color:var(--err)}.wbj li.run .dot{border-color:var(--run);background:var(--run-tint)}
  .wbj li.sel .jl{text-decoration:underline;text-decoration-thickness:2px;text-underline-offset:5px}.wbj li.skip .jl{color:var(--ink-2)}
  .wbmeta{display:flex;flex-wrap:wrap;gap:4px 14px;font-size:12.5px;color:var(--ink-2);margin:-8px 0 14px}
  .wbscroll{overflow:auto;max-width:100%}
  .wbturn{border:1px solid var(--you);background:var(--you-tint);color:var(--ink);border-radius:var(--radius-sm);padding:12px 14px;margin:12px 0}
  .wbturn textarea{width:100%;margin-top:8px}
  .wbgate{display:flex;gap:10px;align-items:flex-start;padding:9px 0;border-top:1px solid var(--line)}.wbgate:first-child{border-top:0}.wbgate .grow{flex:1;min-width:0;overflow-wrap:anywhere}
  .wbgate .pill{flex:none;min-width:74px;justify-content:center}
  .wbrec td{vertical-align:top}.wbrec input[type=text],.wbrec input[type=number],.wbrec select,.wbrec textarea{width:100%;min-width:96px;box-sizing:border-box;font:inherit;font-size:12.5px}
  .wbrec textarea{min-width:180px}.wbrec td.ro{color:var(--ink-2);font-size:12.5px;max-width:260px;overflow-wrap:anywhere}
  .wbev{font-family:var(--mono);font-size:12px;white-space:pre-wrap;max-height:60vh;overflow:auto;background:var(--surface-2);padding:10px;border-radius:var(--radius-sm);margin:0}
  .wbkind{display:inline-block;font-size:11.5px;font-weight:600;border:1px solid var(--line-2);border-radius:4px;padding:1px 6px;color:var(--ink-2)}
  .wblist{display:flex;flex-direction:column;gap:6px}.wblist>div{display:flex;gap:8px;align-items:flex-start;font-size:13px;overflow-wrap:anywhere}
  .wbwork{display:grid;gap:8px;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));margin:6px 0 4px}
  .wbwork button{text-align:left;border:1px solid var(--line-2);border-radius:var(--radius-sm);background:var(--surface);padding:10px 12px;font:inherit;color:var(--ink);cursor:pointer}
  .wbwork button.on{border-color:var(--accent);box-shadow:0 0 0 2px var(--ring)}.wbwork button b{display:block;font-family:var(--font-head)}.wbwork button span{font-size:12px;color:var(--ink-2)}
  .wbform select.sel{width:auto;max-width:100%;min-width:220px}.wbcad{display:flex;flex-wrap:wrap;gap:6px;align-items:center}.wbcad input[type=text]{width:auto}
  .wbrec select{min-width:130px}
  `));
})();

const WB = {packs: null, timer: null, filter: 'open', q: '', sel: {}};
const WB_STATUS = {new: 'mute', queued: 'run', working: 'run', agent_working: 'run', waiting: 'you', attention: 'err', error: 'err', done: 'ok', scheduled: 'ok', closed: 'mute'};
const WB_STEP = {pending: ['to do', ''], queued: ['queued', 'run'], running: ['working…', 'run'], waiting: ['your turn', 'wait'], done: ['done', 'done'], sent_back: ['sent back', 'wait'],
  error: ['needs attention', 'err'], skipped: ['skipped', 'skip']};
const WB_GATE = {pass: ['Pass', 'ok'], warn: ['Warning', 'you'], fail: ['Fail', 'err'], skip: ['Skipped', 'mute'], error: ['Could not run', 'err']};
const WB_RUNNING = new Set(['queued', 'working', 'agent_working']);
// file extensions in words: ".docx · .pdf · .mp4" -> "Word, PDF, video" (the extensions stay in the tooltip)
const FILE_KIND = {docx: 'Word', doc: 'Word', dotx: 'Word', pdf: 'PDF', pptx: 'slides', ppt: 'slides', potx: 'slides', txt: 'text', md: 'text', rtf: 'text', vtt: 'subtitles', srt: 'subtitles',
  html: 'web pages', htm: 'web pages', mp4: 'video', webm: 'video', mov: 'video', mkv: 'video', mp3: 'audio', wav: 'audio', m4a: 'audio', png: 'images', jpg: 'images', jpeg: 'images', gif: 'images', webp: 'images',
  csv: 'spreadsheets', tsv: 'spreadsheets', xlsx: 'spreadsheets', xls: 'spreadsheets', xlsm: 'spreadsheets', ods: 'spreadsheets', parquet: 'Parquet', json: 'JSON', xml: 'XML', yaml: 'YAML', yml: 'YAML',
  xes: 'event logs', log: 'logs', vsdx: 'Visio', bpmn: 'BPMN', zip: 'zip files', sql: 'SQL', dtsx: 'SSIS packages', ispac: 'SSIS packages', pbix: 'Power BI files', twb: 'Tableau workbooks', twbx: 'Tableau workbooks', eml: 'emails', msg: 'emails'};
const fileKinds = exts => [...new Set(exts.map(e => { const k = String(e).replace(/^\./, '').toLowerCase(); return FILE_KIND[k] || k.toUpperCase(); }))].join(', ');
const WB_NONE = {assess: 'Nothing assessed yet', develop: 'Nothing built yet', change: 'No fixes or changes yet', migrate: 'No migrations yet', run: 'Nothing in run & support yet', engage: 'No engagements yet'};
const wbPill = (status, label) => h('span', {class: 'pill plain ' + (WB_STATUS[status] || 'mute')}, label || status);
const wbCell = v => v == null || v === '' ? '—' : typeof v === 'number' ? fmtN(v, 2) : typeof v === 'object' ? JSON.stringify(v) : String(v);

async function wbPacks() {          // asked on every visit: an admin may have switched a module off or on since
  try { WB.packs = (await api('/api/workbench/packs')).packs; } catch (e) { /* keep the last list */ }
  return WB.packs || [];
}

/* the route: #/m/<id>[/<work>] (live when a pack exists), #/m/<id>/i/<item>, and #/p/wb-… links from notifications.
   P17: a module switched off for this workspace (state 'off') gets its own page; not in the plan ('locked') is the registry's. */
async function renderWorkbench() {
  clearTimeout(WB.timer);
  const p = location.hash.match(/^#\/p\/(wb-([a-z0-9]+)-[\w-]+)/);
  if (p) { location.replace(`#/m/${p[2]}/i/${p[1]}`); return; }
  const m = location.hash.match(/^#\/m\/(\w+)(?:\/([\w-]+))?(?:\/([\w-]+))?/);
  if (!m) return renderHome();
  const [, id, a, b] = m;
  const pk = (await wbPacks()).find(x => x.module === id);
  const rm = ((S.registry || {}).modules || []).find(x => x.id === id);
  if ((pk && pk.state === 'off') || (!pk && rm && rm.state === 'off')) return wbOff(id, !!pk);     // every #/m/ page comes here
  if (a === 'i' && b) return wbItem(id, b);
  if (!pk || !pk.on) return renderModule(id, a);
  return wbModule(id, a);
}

/* ---------------- switched off for this workspace: nothing is lost (and, for a pack, nothing of it runs) ---------------- */
async function wbOff(id, pack = true) {
  if (!S.registry && typeof loadRegistry === 'function') await loadRegistry();
  if (!location.hash.startsWith('#/m/' + id)) return;
  const reg = S.registry || {}, t = (S.me || {}).tenant || {}, b = S.brand || {};
  const m = (reg.modules || []).find(x => x.id === id) || {id, name: id, pl: '', text: ''};
  const pillar = (reg.pillars || []).find(x => x.id === m.pl) || {name: ''};
  $('#main').replaceChildren(h('div', {class: 'page'},
    pageHead({crumbs: [['Home', '#/'], ['All modules', '#/modules'], [m.name]], eyebrow: [brandName(), pillar.name].filter(Boolean).join(' · '), title: m.name, promise: m.text,
      actions: h('span', {class: 'pill plain mute'}, 'Switched off')}),
    h('div', {class: 'card', style: 'max-width:720px'}, h('h3', {}, `Switched off for ${t.name || 'this workspace'}`),
      h('p', {class: 'muted'}, pack
        ? `${m.name} is not switched on for this workspace, so its work items cannot be opened or changed here and nothing of it runs on a schedule. Nothing is deleted: the items, their evidence and their schedules come back when it is switched on again.`
        : `${m.name} is not switched on for this workspace, so its screens cannot be opened here. Nothing is deleted: what was made with it comes back when it is switched on again.`),
      t.console && t.id ? h('a', {class: 'btn primary', href: `#/tenants/${t.id}/modules`}, icon('layers'), 'Open this workspace’s modules')
        : h('button', {class: 'btn primary', type: 'button', onclick: () => interest(m)}, 'Ask your administrator'))));
  document.title = `${m.name} · ${b.full || 'RELAY by PASDACS'}`;
}

/* ---------------- the module page (live) ---------------- */
async function wbModule(id, work) {
  const main = $('#main');
  if (!$('#wbmod')) main.replaceChildren(skel('page'));
  let d;
  try { d = await api(`/api/m/${id}/overview` + (work ? `?work=${encodeURIComponent(work)}` : '')); }
  catch (e) {
    if (/not switched on/i.test(e.message)) return wbOff(id);
    if (/no workbench pack/i.test(e.message)) return renderModule(id, work);
    main.replaceChildren(h('div', {class: 'page'}, h('div', {class: 'card empty'}, h('h3', {}, 'This page could not load'), h('p', {}, e.message), h('a', {class: 'btn', href: '#/modules'}, 'All modules'))));
    return;
  }
  if (!location.hash.startsWith('#/m/' + id) || location.hash.includes('/i/')) return;
  const m = d.module, pk = d.pack, w = d.work_type, b = S.brand || {};
  const pillar = (S.registry && S.registry.pillars.find(x => x.id === m.pl)) || {name: ''};
  const steps = pk.work[w].steps;
  const items = d.items.filter(it => WB.filter === 'all' || (WB.filter === 'open' ? !['done', 'closed'].includes(it.status)
    : WB.filter === 'waiting' ? it.status === 'waiting' : ['done', 'scheduled'].includes(it.status)))
    .filter(it => !WB.q || `${it.title} ${it.id} ${it.owner || ''}`.toLowerCase().includes(WB.q.toLowerCase()));
  const live = d.items.filter(it => it.status === 'scheduled');
  const head = pageHead({crumbs: [['Home', '#/'], ['All modules', '#/modules'], [m.name]], eyebrow: `${brandName()} · ${pillar.name} · ${m.name}`, title: m.sub, promise: m.text,
    actions: [statePill(m.state), d.can_create ? h('button', {class: 'btn primary', type: 'button', onclick: () => wbNew(d, w)}, icon('plus'), 'New work') : null]});
  const tabs = h('nav', {class: 'worktabs', 'aria-label': 'Work type'}, pk.order.map(k => h('a', {href: `#/m/${id}/${k}`, class: k === w ? 'on' : '', 'aria-current': k === w ? 'page' : null},
    `${WORK_NAME[k] || k}` + (d.counts[k] && d.counts[k].open ? ` · ${d.counts[k].open}` : ''))));
  const journey = h('ol', {class: 'journey', 'aria-label': 'How it works'}, steps.map((s, i) => h('li', {},
    h('span', {class: 'dot'}), h('div', {class: 'jl'}, `${i + 1} ${s.name}`),
    h('div', {class: 'js'}, `${s.kind_label}${s.confirm ? ' · you confirm' : ''}`))));
  const seg = h('div', {class: 'segbtn', role: 'group', 'aria-label': 'Show'}, [['open', 'Open'], ['waiting', 'Waiting for you'], ['done', 'Done'], ['all', 'All']].map(([v, l]) =>
    h('button', {type: 'button', class: WB.filter === v ? 'on' : '', 'aria-pressed': String(WB.filter === v), onclick: () => { WB.filter = v; wbModule(id, w); }}, l)));
  const qIn = h('input', {type: 'search', placeholder: 'Find a work item…', 'aria-label': 'Find a work item', value: WB.q, style: 'max-width:240px',
    onchange: e => { WB.q = e.target.value; wbModule(id, w); }});
  const table = items.length ? h('div', {class: 'card wbscroll', style: 'padding:0;margin:0'}, h('table', {class: 'utable'},
      h('thead', {}, h('tr', {}, ['Work item', 'Step', 'Status', 'Owner', 'Updated'].map(t => h('th', {class: 'l', scope: 'col'}, t)))),
      h('tbody', {}, items.map(it => h('tr', {},
        h('td', {}, h('a', {href: it.route}, h('b', {}, it.title)), h('div', {class: 'small muted'}, `${it.id} · ${it.platform_label || ''}`)),
        h('td', {class: 'l'}, it.step ? `${it.step_index + 1} of ${it.steps_total} · ${it.step_name}` : 'All steps done', it.schedule_text ? h('div', {class: 'small muted'}, it.schedule_text) : null),
        h('td', {class: 'l'}, wbPill(it.status, it.status_label)), h('td', {class: 'l'}, it.owner || '—'), h('td', {class: 'l'}, ago(it.updated)))))))
    : h('div', {class: 'card empty', style: 'margin:0'}, h('h3', {}, d.items.length ? 'Nothing matches' : (WB_NONE[w] || `No ${(WORK_NAME[w] || w).toLowerCase()} work yet`)),
      h('p', {class: 'muted', style: 'max-width:560px;margin:0 auto 12px'}, d.items.length ? 'Change the filter or the search.' : (pk.work[w].title || 'Start a work item') + '. Every step is logged and a person confirms each one that matters.'),
      d.can_create && !d.items.length ? h('button', {class: 'btn primary', type: 'button', onclick: () => wbNew(d, w)}, icon('plus'), 'New work') : null);
  const platforms = h('div', {class: 'card', style: 'margin:0'}, h('div', {class: 'card-head'}, h('h3', {}, 'Platforms'), h('span', {class: 'sp'}), h('span', {class: 'small muted'}, 'read-only by default')),
    h('div', {class: 'wblist'}, Object.values(pk.platforms).filter(p => pk.work[w].platforms.includes(p.id)).map(p => h('div', {}, icon(p.kinds.length ? 'db' : 'clip'),
      h('span', {}, h('b', {}, p.label), p.kind_labels.length ? ` — ${p.kind_labels.join(', ')}` : p.uploads.length ? ` — ${p.uploads.join(', ')}` : '', h('div', {class: 'small muted'}, p.reads))))));
  const confirm = h('div', {class: 'card', style: 'margin:0'}, h('h3', {}, 'Where you confirm'), h('div', {class: 'small muted', style: 'margin:4px 0 10px'}, 'Always a person in the loop — the work waits at each of these:'),
    h('div', {class: 'confirm'}, steps.filter(s => s.confirm).map(s => h('div', {}, h('span', {class: 'proven'}, icon('check')), h('span', {}, h('b', {}, `${s.confirm_label || s.name}: `), s.confirm, s.approver ? ' (the named approver)' : '')))));
  const cards = (d.cards || []).map(c => h('div', {class: 'card', style: 'margin:0'}, h('h3', {}, c.title),
    c.rows && c.rows.length ? h('div', {class: 'wbscroll', tabindex: '0', role: 'region', 'aria-label': c.title}, h('table', {class: 'utable', style: 'margin-top:6px'}, h('thead', {}, h('tr', {}, c.columns.map(t => h('th', {class: 'l', scope: 'col'}, t)))),
      h('tbody', {}, c.rows.map(r => h('tr', {}, r.map((v, i) => h('td', {class: 'l'}, typeof v === 'string' && v.startsWith('#/') ? h('a', {href: v}, 'Open') : wbCell(v))))))))
      : h('div', {class: 'muted small', style: 'margin-top:6px'}, c.empty || 'Nothing yet.')));
  main.replaceChildren(h('div', {class: 'page', id: 'wbmod'}, head, tabs, journey,
    h('div', {class: 'g-side'},
      h('div', {class: 'stack'},
        live.length && w === 'run' ? h('div', {class: 'banner ok', style: 'margin:0'}, h('div', {class: 'ic'}, icon('check')), h('div', {class: 'txt'}, h('div', {class: 't'}, `${live.length} live and scheduled`), h('div', {class: 'd'}, live.map(x => `${x.title}: ${x.schedule_text}`).join(' · ')))) : null,
        h('div', {class: 'row', style: 'gap:10px;flex-wrap:wrap'}, seg, qIn, h('span', {style: 'flex:1'}), h('span', {class: 'small muted'}, `${d.items.length} work item${d.items.length === 1 ? '' : 's'}`)),
        table,
        d.can_create ? null : h('p', {class: 'small muted'}, 'You can look at the work shared with you; builders and admins start and change it.'),
        h('div', {class: 'card', style: 'margin:0'}, h('div', {class: 'card-head'}, h('h3', {}, 'How it works — ' + (WORK_NAME[w] || w).toLowerCase())),
          h('div', {class: 'ph-steps'}, steps.map(s => h('div', {}, h('span', {}, h('b', {}, s.name + ': '), s.text || '', ' ', h('span', {class: 'wbkind'}, s.kind_label + (s.agent ? ' · ' + s.agent : '')))))))),
      h('div', {class: 'stack'}, confirm, ...cards, platforms,
        (S.me || {}).builder !== false ? wbConnections(id, w, pk) : null,
        h('div', {class: 'card', style: 'margin:0'}, h('h3', {}, 'Same rules as everywhere'), h('div', {class: 'rules', style: 'margin-top:8px'}, d.rules.map(t => h('div', {}, icon('check'), t))))))));
  document.title = `${m.name} · ${b.full || 'RELAY by PASDACS'}`;
  if (hashParams().get('new') === '1') {          // from Start new work (Home, the + button): the New work form on this work type, once
    history.replaceState(null, '', `#/m/${id}/${w}`);
    if (d.can_create) wbNew(d, w);
  }
  if (d.items.some(it => WB_RUNNING.has(it.status))) WB.timer = setTimeout(() => { if (location.hash.startsWith('#/m/' + id) && !location.hash.includes('/i/') && !document.querySelector('.modal')) wbModule(id, w); }, 4000);
}

/* ---------------- New work: the wizard ---------------- */
async function wbNew(d, work) {
  const pk = d.pack, mid = pk.module;
  let w = pk.work[work] ? work : pk.order[0];
  const files = [];
  const picked = new Set();
  const vals = {};
  let conns = [], people = [];
  try { conns = (await api('/api/connections')).connections || []; } catch (e) { conns = []; }
  try { people = (await api('/api/directory')).users || []; } catch (e) { people = []; }
  const body = h('div', {class: 'mbody wbform'});
  const title = h('input', {type: 'text', placeholder: 'A short name you will recognise later', 'aria-label': 'Name of the work item', maxlength: 160});
  const brief = h('textarea', {rows: 3, 'aria-label': 'The brief'});
  const vis = h('select', {class: 'sel', 'aria-label': 'Who can see it'}, [['private', 'Only me'], ['team', 'My team'], ['org', 'Everyone in the organisation']].map(([v, l]) => h('option', {value: v}, l)));
  const appr = h('select', {class: 'sel', 'aria-label': 'Named approver'}, h('option', {value: ''}, 'Me (the owner)'), people.map(u => h('option', {value: u.id}, `${u.name} · ${u.email}`)));
  const fileIn = h('input', {type: 'file', multiple: true, 'aria-label': 'Upload files'});
  const fileList = h('div', {class: 'flist attached'});
  const err = h('div', {});
  fileIn.onchange = () => { files.push(...fileIn.files); fileIn.value = ''; drawFiles(); };
  const drawFiles = () => fileList.replaceChildren(...files.map((f, i) => h('span', {}, icon('clip'), ` ${f.name} · ${size(f.size)}`,
    h('button', {type: 'button', 'aria-label': `Remove ${f.name}`, onclick: () => { files.splice(i, 1); drawFiles(); }}, '×'))));
  const fieldEl = f => {
    const v = vals[f.key] !== undefined ? vals[f.key] : f.default;
    if (f.type === 'longtext') { const el = h('textarea', {rows: 3, 'aria-label': f.label, oninput: e => { vals[f.key] = e.target.value; }}, v || ''); return el; }
    if (f.type === 'select' && vals[f.key] === undefined && f.default == null && f.options.length) vals[f.key] = f.options[0][0];
    if (f.type === 'select') return h('select', {class: 'sel', 'aria-label': f.label, onchange: e => { vals[f.key] = e.target.value; }},
      (f.options.length ? f.options : [['', 'Nothing to pick yet']]).map(([ov, ol]) => h('option', {value: ov, selected: ov === v}, ol)));
    if (f.type === 'bool') return h('label', {class: 'chk'}, h('input', {type: 'checkbox', checked: !!v, onchange: e => { vals[f.key] = e.target.checked; }}), f.label);
    if (f.type === 'cadence') {
      const c = {every: 'day', at: '06:00', tz: myTz(), ...(v || {})}; vals[f.key] = c;
      const DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
      const wd = h('select', {class: 'sel', 'aria-label': `${f.label}: weekday`, onchange: e => { c.weekday = Number(e.target.value); }}, DAYS.map((d, i) => h('option', {value: i, selected: i === (c.weekday || 0)}, d)));
      const md = h('select', {class: 'sel', 'aria-label': `${f.label}: day of the month`, onchange: e => { c.day = e.target.value === 'last' ? 'last' : Number(e.target.value); }},
        [...Array.from({length: 28}, (_, i) => [String(i + 1), `day ${i + 1}`]), ['last', 'the last day']].map(([ov, ol]) => h('option', {value: ov, selected: ov === String(c.day || 1)}, ol)));
      const show = () => { wd.hidden = c.every !== 'week'; md.hidden = c.every !== 'month'; };
      const every = h('select', {class: 'sel', style: 'min-width:140px', 'aria-label': `${f.label}: how often`, onchange: e => { c.every = e.target.value; show(); }}, [['hour', 'Every hour'], ['day', 'Every day'], ['week', 'Every week'], ['month', 'Every month']].map(([ov, ol]) => h('option', {value: ov, selected: ov === c.every}, ol)));
      const at = h('input', {type: 'text', value: c.at, 'aria-label': `${f.label}: at (HH:MM)`, style: 'max-width:90px', oninput: e => { c.at = e.target.value; }});
      const tz = h('input', {type: 'text', value: c.tz, 'aria-label': `${f.label}: time zone`, style: 'max-width:160px', oninput: e => { c.tz = e.target.value; }});
      show();
      return h('div', {class: 'wbcad'}, every, wd, md, h('span', {class: 'small muted'}, 'at'), at, tz);
    }
    return h('input', {type: f.type === 'number' ? 'number' : 'text', value: v || '', 'aria-label': f.label, oninput: e => { vals[f.key] = e.target.value; }});
  };
  const draw = () => {
    const W = pk.work[w];
    const kinds = new Set(W.platforms.flatMap(p => (pk.platforms[p] || {}).kinds || []));
    const exts = [...new Set(W.platforms.flatMap(p => (pk.platforms[p] || {}).uploads || []))];
    fileIn.accept = exts.join(',');
    const usable = conns.filter(c => kinds.has(c.kind) && c.enabled !== false);
    const hasApprover = W.steps.some(s => s.approver);
    brief.placeholder = w === 'change' ? 'What should change, and why?' : 'What should it do? Anything the agent and the reviewers should know (optional).';
    body.replaceChildren(h('div', {},
      h('label', {class: 'f', style: 'margin-top:0'}, 'What do you need?'),
      h('div', {class: 'wbwork', role: 'group', 'aria-label': 'Work type'}, pk.order.map(k => h('button', {type: 'button', class: k === w ? 'on' : '', 'aria-pressed': String(k === w), onclick: () => { w = k; draw(); }},
        h('b', {}, WORK_NAME[k] || k), h('span', {}, pk.work[k].title || '')))),
      h('div', {class: 'small muted'}, 'Steps: ' + W.steps.map(s => s.name + (s.confirm ? ' ✓' : '')).join(' → ') + '  (✓ = you confirm)'),
      h('label', {class: 'f'}, 'Name'), title,
      h('label', {class: 'f'}, w === 'change' ? 'The change' : 'Brief'), brief,
      W.sources ? [h('label', {class: 'f'}, 'Where the data is', h('small', {}, W.needs_source ? 'a connection or an upload' : 'optional')),
        usable.length ? h('div', {class: 'row', style: 'gap:6px'}, usable.map(c => h('label', {class: 'chk'}, h('input', {type: 'checkbox', checked: picked.has(c.id), onchange: e => { e.target.checked ? picked.add(c.id) : picked.delete(c.id); }}),
          `${c.name} · ${c.label}`))) : h('div', {class: 'small muted'}, kinds.size ? 'You have no connection this work can read yet. Add one, or upload files.' : ''),
        kinds.size && typeof connectionWizard === 'function' ? h('div', {class: 'row', style: 'gap:8px;margin-top:6px'}, h('button', {class: 'btn sm', type: 'button', onclick: () => connectionWizard({suggest: [...kinds], onDone: async c => {
          try { conns = (await api('/api/connections')).connections || []; } catch (e) {} picked.add(c.id); draw(); }})}, icon('plus'), 'New connection')) : null,
        exts.length ? [h('div', {class: 'row', style: 'gap:8px;margin-top:8px'}, h('button', {class: 'btn sm', type: 'button', onclick: () => fileIn.click()}, icon('clip'), 'Upload files'), h('span', {class: 'small muted', title: exts.join(' ')}, fileKinds(exts))), fileIn, fileList] : null] : null,
      W.fields.map(f => f.type === 'bool' ? fieldEl(f) : [h('label', {class: 'f'}, f.label, f.required ? null : h('small', {}, 'optional')), fieldEl(f), f.help ? h('div', {class: 'hint'}, f.help) : null]),
      hasApprover ? [h('label', {class: 'f'}, 'Named approver', h('small', {}, 'confirms go-live')), appr] : null,
      h('label', {class: 'f'}, 'Who can see it'), vis,
      err,
      h('div', {class: 'row', style: 'justify-content:flex-end;margin-top:14px'}, h('button', {class: 'btn primary', type: 'button', onclick: create}, 'Create and start'))));
    fileIn.style.display = 'none';
  };
  const create = async e => {
    const W = pk.work[w];
    if (!title.value.trim()) { err.replaceChildren(h('div', {class: 'note err'}, 'Give the work item a name.')); title.focus(); return; }
    const missing = W.fields.filter(f => f.required && !(vals[f.key] !== undefined ? vals[f.key] : f.default));
    if (missing.length) { err.replaceChildren(h('div', {class: 'note err'}, `${missing.map(f => f.label).join(', ')} is needed.`)); return; }
    const fd = new FormData();
    fd.append('work', w); fd.append('title', title.value.trim()); fd.append('brief', brief.value); fd.append('connections', JSON.stringify([...picked]));
    const scope = {};
    for (const f of W.fields) { const v = vals[f.key] !== undefined ? vals[f.key] : f.default; if (v !== undefined && v !== null) scope[f.key] = v; }
    fd.append('scope', JSON.stringify(scope)); fd.append('visibility', vis.value); fd.append('approver', appr.value || '');
    if (W.sources) for (const f of files) fd.append('files', f, f.name);
    e.target.disabled = true; e.target.textContent = 'Creating…';
    try { const it = await upload(`/api/m/${mid}/items`, fd); mm.remove(); notify('Work item created — Relay is on the first step', 'ok'); location.hash = it.route.slice(1); }
    catch (x) { err.replaceChildren(h('div', {class: 'note err'}, x.message)); e.target.disabled = false; e.target.textContent = 'Create and start'; }
  };
  draw();
  const mm = modal(`New work · ${pk.name}`, body, true);
}

/* ---------------- a step's view: the payload the pack returned, drawn by its view type ---------------- */
function wbTable(cols, rows, max = 200) {
  const r = (rows || []).slice(0, max);
  return h('div', {class: 'wbscroll', tabindex: '0', role: 'region', 'aria-label': 'Table: ' + cols.slice(0, 3).join(', ')}, h('table', {class: 'utable'}, h('thead', {}, h('tr', {}, cols.map(c => h('th', {class: 'l', scope: 'col'}, c)))),
    h('tbody', {}, r.map(row => h('tr', {}, (Array.isArray(row) ? row : cols.map(c => row[c])).map(v => h('td', {class: 'l'}, wbCell(v))))))),
    (rows || []).length > max ? h('div', {class: 'small muted', style: 'margin-top:6px'}, `Showing ${max} of ${rows.length} rows — the full list is in the evidence.`) : null);
}
function wbPlural(w) {   // activity → activities, box → boxes, field → fields
  return /[^aeiou]y$/.test(w) ? w.slice(0, -1) + 'ies' : /(s|x|ch|sh)$/.test(w) ? w + 'es' : w + 's';
}
function wbCompare(mid, iid, cmp) {   // today against a what-if (or any two columns side by side), with its evidence
  return h('div', {style: 'margin-top:14px'}, h('div', {class: 'row', style: 'gap:8px;align-items:center;margin-bottom:6px'}, h('b', {}, cmp.title || 'Compared'),
    cmp.evidence ? h('button', {class: 'btn sm ghost', type: 'button', onclick: () => wbEvidence(mid, iid, cmp.evidence)}, icon('file'), 'Evidence') : null),
    wbTable(cmp.columns, cmp.rows));
}
function wbView(mid, iid, step) {
  const d = step.data;
  if (!d) return step.status === 'pending' ? h('div', {class: 'muted small'}, 'Not run yet.') : null;
  const ev = eid => eid ? h('button', {class: 'btn sm ghost', type: 'button', onclick: () => wbEvidence(mid, iid, eid)}, icon('file'), 'Evidence') : null;
  switch (step.view) {
    case 'gates': return h('div', {}, (d.checks || []).map(c => { const [t, k] = WB_GATE[c.status] || [c.status, 'mute'];
      return h('div', {class: 'wbgate'}, h('span', {class: 'pill plain ' + k}, t), h('div', {class: 'grow'}, h('b', {}, c.label), c.severity ? h('span', {class: 'small muted'}, ` · ${c.severity}`) : null,
        h('div', {class: 'small'}, c.detail || ''), c.measured != null || c.expected ? h('div', {class: 'small muted'}, `measured ${wbCell(c.measured)} · expected ${wbCell(c.expected)}`) : null,
        (c.parts || []).length ? h('ul', {class: 'small', style: 'margin:4px 0 0;padding-left:18px'}, c.parts.map(p => h('li', {}, `${p.label}: ${(WB_GATE[p.status] || [p.status])[0]} — ${p.detail}`, ' ', ev(p.evidence)))) : null), ev(c.evidence)); }));
    case 'plan': return h('div', {}, h('div', {class: 'wblist'}, (d.items || []).map(x => h('div', {}, icon('check'), h('span', {}, h('b', {}, x.title), x.detail ? ' — ' + x.detail : '', x.effort ? h('span', {class: 'chipx', style: 'margin-left:6px'}, x.effort) : null)))),
      d.total ? h('div', {style: 'margin-top:10px'}, h('b', {}, 'Total: '), d.total) : null, d.note ? h('div', {class: 'small muted', style: 'margin-top:6px'}, d.note) : null,
      d.compare ? wbCompare(mid, iid, d.compare) : null);
    case 'text': return h('div', {style: 'white-space:pre-wrap'}, d.text || '');
    case 'link': return h('div', {}, d.text ? h('p', {class: 'small muted', style: 'margin:0 0 8px'}, d.text) : null, d.href ? h('a', {class: 'btn', href: d.href}, d.label || 'Open') : null);
    case 'fields': return wbTable(['Field', 'Type', 'Rule', 'Confidence'], (d.fields || []).map(f => [f.name, f.type, f.rule || f.note, f.confidence]));
    case 'mapping': return wbTable(['From', 'To', 'Rule', 'Status'], (d.pairs || []).map(p => [p.from, p.to, p.rule, p.status]));
    case 'process': return h('ol', {class: 'small', style: 'padding-left:20px;margin:0'}, (d.steps || []).map(s => h('li', {}, h('b', {}, s.label), s.actor ? ` — ${s.actor}` : '', (s.next || []).length ? h('span', {class: 'muted'}, ` → ${s.next.join(', ')}`) : null)));
    case 'kpis': return h('div', {class: 'g3'}, (d.kpis || []).map(k => kpiTile(k.name, wbCell(k.value), k.formula || '')));
    case 'prototype': return d.href ? h('a', {class: 'btn', href: d.href}, 'Open the prototype') : null;
    default: return d.columns ? wbTable(d.columns, d.rows) : wbFacts(d);
  }
}
function wbFacts(d) {     // a result with no view of its own: its plain facts as a table; anything nested behind "Technical details"
  const all = Object.entries(d || {}), flat = all.filter(([, v]) => v == null || ['string', 'number', 'boolean'].includes(typeof v));
  const label = k => k.replace(/_/g, ' ').replace(/^./, c => c.toUpperCase());
  const val = v => v == null || v === '' ? '—' : typeof v === 'boolean' ? (v ? 'Yes' : 'No') : typeof v === 'number' ? fmtN(v, 2) : String(v);
  return h('div', {}, flat.length ? h('table', {class: 'utable'}, h('tbody', {}, flat.map(([k, v]) => h('tr', {}, h('th', {class: 'l', scope: 'row'}, label(k)), h('td', {class: 'l'}, val(v)))))) : null,
    flat.length < all.length ? h('details', {style: 'margin-top:8px'}, h('summary', {class: 'small'}, 'Technical details'), h('pre', {class: 'wbev', tabindex: '0'}, JSON.stringify(d, null, 1))) : null);
}

async function wbEvidence(mid, iid, eid) {
  let e;
  try { e = await api(`/api/m/${mid}/items/${iid}/evidence/${eid}`); } catch (x) { notify(x.message, 'err'); return; }
  const p = e.payload;
  const rows = Array.isArray(p) ? p : p && Array.isArray(p.rows) && p.rows.length && typeof p.rows[0] === 'object' ? p.rows : p && Array.isArray(p.columns) && p.columns.length && typeof p.columns[0] === 'object' ? p.columns : null;
  const cols = rows && rows.length && !Array.isArray(rows[0]) ? [...new Set(rows.flatMap(r => Object.keys(r)))].slice(0, 12) : null;
  modal(e.label, h('div', {class: 'mbody'}, h('div', {class: 'small muted', style: 'margin-bottom:8px'}, `Step ${e.step} · ${when(e.when)}` + (e.ok === false ? ' · did not pass' : e.ok ? ' · passed' : '')),
    cols ? [wbTable(cols, rows.map(r => cols.map(c => r[c]))), h('details', {style: 'margin-top:10px'}, h('summary', {}, 'All of it'), h('pre', {class: 'wbev', tabindex: '0'}, JSON.stringify(p, null, 1)))]
      : h('pre', {class: 'wbev', tabindex: '0'}, JSON.stringify(p, null, 1))), true);
}

/* ---------------- editable records: a person corrects the step's result in place ---------------- */
function wbRecords(mid, iid, step, onSaved) {
  const ed = step.edit, recs = (step.records || []).map(r => ({...r}));
  const state = {dirty: false};
  const box = h('div', {});
  const problems = h('div', {});
  const cell = (r, i, c) => {
    if (c.readonly) return h('td', {class: 'ro'}, wbCell(r[c.key]));
    const lab = `${c.label}, ${ed.label} ${i + 1}`;
    const set = v => { r[c.key] = v; state.dirty = true; };
    if (c.type === 'bool') return h('td', {}, h('input', {type: 'checkbox', checked: !!r[c.key], 'aria-label': lab, onchange: e => set(e.target.checked)}));
    if (c.type === 'select') return h('td', {}, h('select', {'aria-label': lab, onchange: e => set(e.target.value)}, [r[c.key] && !c.options.some(o => o[0] === r[c.key]) ? h('option', {value: r[c.key], selected: true}, r[c.key]) : null,
      ...c.options.map(([v, l]) => h('option', {value: v, selected: v === r[c.key]}, l))].filter(Boolean)));
    if (c.type === 'longtext') return h('td', {}, h('textarea', {rows: 2, 'aria-label': lab, oninput: e => set(e.target.value)}, r[c.key] || ''));
    return h('td', {}, h('input', {type: c.type === 'number' ? 'number' : 'text', value: r[c.key] == null ? '' : r[c.key], 'aria-label': lab, oninput: e => set(e.target.value)}));
  };
  const draw = () => box.replaceChildren(h('div', {}, h('div', {class: 'wbscroll', tabindex: '0', role: 'region', 'aria-label': `The ${wbPlural(ed.label)} to correct`}, h('table', {class: 'utable wbrec'},
      h('thead', {}, h('tr', {}, ed.columns.map(c => h('th', {class: 'l', scope: 'col'}, c.label)), ed.remove ? h('th', {class: 'l', scope: 'col'}, h('span', {class: 'small'}, 'Remove')) : null)),
      h('tbody', {}, recs.map((r, i) => h('tr', {}, ed.columns.map(c => cell(r, i, c)), ed.remove ? h('td', {}, h('button', {class: 'btn sm ghost', type: 'button', 'aria-label': `Remove ${ed.label} ${i + 1}`,
        onclick: () => { recs.splice(i, 1); state.dirty = true; draw(); }}, '×')) : null))))),
    recs.some(r => r.problem) ? h('div', {class: 'note warn'}, h('b', {}, 'Rows to look at: '), h('ul', {}, recs.filter(r => r.problem).slice(0, 8).map(r => h('li', {}, r.problem)))) : null,
    ed.columns.filter(c => c.help).map(c => h('div', {class: 'hint'}, h('b', {}, c.label + ': '), c.help)),
    problems,
    h('div', {class: 'row', style: 'gap:8px;margin-top:8px'}, ed.add ? h('button', {class: 'btn sm', type: 'button', onclick: () => { const r = {}; ed.columns.forEach(c => { r[c.key] = c.type === 'bool' ? true : c.type === 'select' && c.options[0] ? c.options[0][0] : ''; }); recs.push(r); state.dirty = true; draw(); }}, icon('plus'), `Add a ${ed.label}`) : null,
      h('button', {class: 'btn sm primary', type: 'button', onclick: () => save().catch(() => {})}, 'Save changes'), h('span', {class: 'small muted'}, `${recs.length} ${recs.length === 1 ? ed.label : wbPlural(ed.label)}`))));
  const save = async () => {
    const r = await api(`/api/m/${mid}/items/${iid}/steps/${step.id}/records`, {method: 'PUT', json: {records: recs}});
    if (!r.ok) { problems.replaceChildren(h('div', {class: 'note err', role: 'alert'}, h('b', {}, 'Not saved: '), h('ul', {}, r.problems.map(p => h('li', {}, p))))); throw new Error('not saved'); }
    problems.replaceChildren(); state.dirty = false; notify(`Saved — ${r.changes} change${r.changes === 1 ? '' : 's'}`, 'ok'); if (onSaved) onSaved(r.item);
  };
  draw();
  return {el: box, save, state};
}

/* ---------------- the work item page ---------------- */
async function wbItem(mid, iid) {
  const main = $('#main');
  if (!$('#wbitem') || $('#wbitem').dataset.id !== iid) main.replaceChildren(skel('page'));
  let it;
  try { it = await api(`/api/m/${mid}/items/${iid}`); }
  catch (e) {
    if (/not switched on/i.test(e.message)) return wbOff(mid);
    main.replaceChildren(h('div', {class: 'page'}, pageHead({crumbs: [['Home', '#/'], ['Module', `#/m/${mid}`], ['Work item']], eyebrow: brandName(), title: 'Work item'}),
      h('div', {class: 'card empty'}, h('h3', {}, /not found|no such/i.test(e.message) ? 'No such work item' : 'This page could not load'), h('p', {}, e.message), h('a', {class: 'btn', href: `#/m/${mid}`}, 'Back to the module'))));
    return;
  }
  if (!location.hash.startsWith(`#/m/${mid}/i/${iid}`)) return;
  wbDrawItem(mid, iid, it);
}

function wbDrawItem(mid, iid, it) {
  const main = $('#main');
  const can = !!(it.access && it.access.can_edit);
  const qs = hashParams();
  const linked = it.steps.find(s => s.id === qs.get('step') && ['waiting', 'error'].includes(s.status));
  const sid = WB.sel[iid] || (linked && linked.id) || it.step || (it.steps[it.steps.length - 1] || {}).id;
  const step = it.steps.find(s => s.id === sid) || it.steps[0];
  const running = WB_RUNNING.has(it.status);
  const post = async (path, json, okText) => { try { const r = await api(`/api/m/${mid}/items/${iid}${path}`, {method: 'POST', json: json || {}}); if (okText) notify(okText, 'ok'); wbDrawItem(mid, iid, r); return r; } catch (e) { notify(e.message, 'err'); return null; } };
  const head = pageHead({crumbs: [['Home', '#/'], [it.module_name, `#/m/${mid}`], [it.work_name, `#/m/${mid}/${it.work}`], [it.title]], eyebrow: `${brandName()} · ${it.module_name} · ${it.work_name}`,
    title: it.title, promise: it.brief || null,
    actions: [wbPill(it.status, it.status_label), running ? h('span', {class: 'pill run'}, it.status === 'queued' && it.position ? `Queued · ${it.position} ahead` : 'Working…') : null,
      can && running ? h('button', {class: 'btn', type: 'button', onclick: () => post('/stop', {}, 'Stopped')}, 'Stop') : null,
      it.pack_ready ? h('a', {class: 'btn primary', href: `/api/m/${mid}/items/${iid}/evidence-pack.zip`, download: `${iid}-evidence.zip`}, icon('download'), 'Evidence pack') : null,
      can && !it.closed ? h('button', {class: 'btn', type: 'button', onclick: () => wbClose(mid, iid, it)}, 'Close') : null]});
  const meta = h('div', {class: 'wbmeta'}, h('span', {}, it.platform_label), it.connections.length ? h('span', {}, 'Reads: ' + it.connections.map(c => `${c.name} (${c.label})`).join(', ')) : null,
    it.files.length ? h('span', {}, `${it.files.length} upload${it.files.length === 1 ? '' : 's'}`) : null, h('span', {}, `Owner: ${it.owner || '—'}`), it.approver ? h('span', {}, `Approver: ${it.approver}`) : null,
    h('span', {}, {private: 'Only the owner sees it', team: 'Shared with the team', org: 'Everyone can see it'}[it.visibility] || it.visibility), it.schedule_text ? h('span', {}, `${it.schedule_text} · next ${when(it.next_run)}`) : null);
  const journey = h('ol', {class: 'journey wbj', 'aria-label': 'Journey'}, it.steps.map((s, i) => { const [t, k] = WB_STEP[s.status] || [s.status, ''];
    return h('li', {class: `${k} ${s.id === step.id ? 'sel' : ''} ${s.id === it.step && (!k || k === 'run') ? 'on' : ''}`, 'aria-current': s.id === it.step ? 'step' : null},
      h('button', {type: 'button', 'aria-pressed': String(s.id === step.id), 'aria-label': `Step ${i + 1}, ${s.name}: ${s.status_label}`, onclick: () => { WB.sel[iid] = s.id; wbDrawItem(mid, iid, it); }},
        h('span', {class: 'dot'}, s.status === 'done' ? '✓' : ''), h('div', {class: 'jl'}, `${i + 1} ${s.name}`), h('div', {class: 'js'}, s.status === 'waiting' && !(s.checkpoint && s.checkpoint.can_decide) ? 'waiting' : t))); }));
  const banner = it.closed ? h('div', {class: 'banner info'}, h('div', {class: 'ic'}, icon('info')), h('div', {class: 'txt'}, h('div', {class: 't'}, 'Closed'), h('div', {class: 'd'}, it.close_note || '')))
    : it.status === 'done' ? h('div', {class: 'banner ok'}, h('div', {class: 'ic'}, icon('check')), h('div', {class: 'txt'}, h('div', {class: 't'}, 'Done — every step confirmed'), h('div', {class: 'd'}, 'The evidence pack holds the evidence, the outputs, every decision and a hand-over document.')))
    : it.status === 'scheduled' ? h('div', {class: 'banner ok'}, h('div', {class: 'ic'}, icon('clock')), h('div', {class: 'txt'}, h('div', {class: 't'}, `Live · ${it.schedule_text}`), h('div', {class: 'd'}, `Next run ${when(it.next_run)}; ${it.rounds} run${it.rounds === 1 ? '' : 's'} so far. Breaks wait for a person before anything goes out.`)))
    : null;
  main.replaceChildren(h('div', {class: 'page', id: 'wbitem', 'data-id': iid}, head, meta, journey, banner,
    h('div', {class: 'g-side'}, h('div', {class: 'stack'}, wbStepCard(mid, iid, it, step, can)), h('div', {class: 'stack'}, wbSide(mid, iid, it, can)))));
  document.title = `${it.title} · ${it.module_name} · ${S.brand ? S.brand.full : 'RELAY by PASDACS'}`;
  clearTimeout(WB.timer);
  if (running) WB.timer = setTimeout(() => { if (location.hash.startsWith(`#/m/${mid}/i/${iid}`) && !document.querySelector('.modal') && !(document.activeElement && /INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName))) wbItem(mid, iid); }, 2500);
}

function wbStepCard(mid, iid, it, step, can) {
  const cp = step.checkpoint;
  const mine = cp && cp.status === 'open' && cp.can_decide;
  const editable = step.edit && step.status === 'waiting' && can && mine;
  const rec = editable ? wbRecords(mid, iid, step, r => wbDrawItem(mid, iid, r)) : null;
  const decide = async (decision, comment) => {
    try {
      if (rec && rec.state.dirty) await rec.save();
      const r = await api(`/api/m/${mid}/items/${iid}/steps/${step.id}/decide`, {method: 'POST', json: {decision, comment}});
      notify(decision === 'accept' ? 'Confirmed — signed and audited' : 'Sent back — Relay runs the step again with your note', 'ok');
      delete WB.sel[iid]; wbDrawItem(mid, iid, r);
    } catch (e) { if (e.message !== 'not saved') notify(e.message, 'err'); }
  };
  const note = h('textarea', {rows: 2, placeholder: 'What should change? Needed to send it back; optional when you confirm.', 'aria-label': 'Your note'});
  const turn = mine ? h('div', {class: 'wbturn', role: 'region', 'aria-label': 'Your turn'}, h('b', {}, 'Your turn — '), h('span', {}, `${step.confirm_label || step.name}: ${step.confirm || 'confirm this step'}`),
      step.edit ? h('div', {class: 'small', style: 'margin-top:4px'}, 'Correct the rows below if you need to; your changes are saved when you confirm.') : null, note,
      h('div', {class: 'row', style: 'gap:8px;margin-top:8px'}, h('button', {class: 'btn primary', type: 'button', onclick: () => decide('accept', note.value.trim() || null)}, icon('check'), 'Confirm'),
        h('button', {class: 'btn', type: 'button', onclick: () => { if (!note.value.trim()) { notify('Say what to change when you send it back.', 'err'); note.focus(); return; } decide('send_back', note.value.trim()); }}, 'Send back'),
        h('a', {class: 'small', href: '#/validate', style: 'margin-left:auto'}, 'Also in the validation queue')))
    : cp && cp.status === 'open' ? h('div', {class: 'note'}, h('b', {}, 'Waiting for '), cp.assignee || 'a person', ` since ${ago(cp.created)} — ${step.confirm_label || step.name}: ${step.confirm || ''}`)
    : null;
  const err = step.status === 'error' ? h('div', {class: 'note err', role: 'alert'}, h('b', {}, 'This step needs attention: '), step.error || it.error || '',
      can ? h('div', {style: 'margin-top:8px'}, h('button', {class: 'btn sm', type: 'button', onclick: async e => { e.target.disabled = true; try { const r = await api(`/api/m/${mid}/items/${iid}/steps/${step.id}/run`, {method: 'POST', json: {}}); notify('Running the step again', 'ok'); wbDrawItem(mid, iid, r); } catch (x) { notify(x.message, 'err'); e.target.disabled = false; } }}, icon('play'), 'Run again')) : null) : null;
  const decided = step.decided_by_name ? h('div', {class: 'small muted', style: 'margin-top:8px'}, `${step.status === 'sent_back' ? 'Sent back' : 'Confirmed'} by ${step.decided_by_name} ${ago(step.decided)}` + (step.comment ? ` — “${step.comment}”` : '')) : null;
  const evs = (step.evidence || []).map(id => it.evidence.find(e => e.id === id)).filter(Boolean);
  const outs = it.outputs.filter(o => o.step === step.id);
  const actions = can && step.actions.length && ['waiting', 'done'].includes(step.status) && !WB_RUNNING.has(it.status) ? h('div', {class: 'row', style: 'gap:8px;margin-top:10px'}, step.actions.map(a => h('button', {class: 'btn sm', type: 'button', title: a.help || null,
    onclick: async e => { e.target.disabled = true; try { const r = await api(`/api/m/${mid}/items/${iid}/steps/${step.id}/run`, {method: 'POST', json: {action: a.id}}); notify(`${a.label}: queued, the agent picks it up next`, 'ok'); wbDrawItem(mid, iid, r); } catch (x) { notify(x.message, 'err'); e.target.disabled = false; } }},
    icon(a.kind === 'agent' ? 'spark' : 'play'), a.label))) : null;
  return h('div', {class: 'card', style: 'margin:0'},
    h('div', {class: 'card-head'}, h('h2', {style: 'margin:0;font-size:18px'}, step.name), h('span', {class: 'wbkind', style: 'margin-left:8px'}, step.kind_label + (step.agent ? ' · ' + step.agent : '')), h('span', {class: 'sp'}),
      h('span', {class: 'pill plain ' + ({done: 'ok', waiting: 'you', error: 'err', running: 'run', queued: 'run', sent_back: 'you'}[step.status] || 'mute')}, step.status_label)),
    step.text ? h('p', {class: 'small muted', style: 'margin:4px 0 10px'}, step.text) : null,
    step.summary ? h('p', {style: 'margin:0 0 10px'}, step.summary) : null,
    err, turn,
    step.status === 'running' || step.status === 'queued' ? h('div', {class: 'note'}, h('b', {}, step.kind === 'agent' ? 'Relay is working on it' : 'Working on it'), ' — this page refreshes by itself.') : null,
    rec ? rec.el : wbView(mid, iid, step),
    rec && step.data && step.data.compare ? wbCompare(mid, iid, step.data.compare) : null,
    !rec && step.records && step.records.length && step.edit && step.view !== 'table' ? wbTable(step.edit.columns.map(c => c.label), step.records.map(r => step.edit.columns.map(c => r[c.key]))) : null,
    actions, decided,
    evs.length || outs.length ? h('div', {style: 'margin-top:14px'}, h('div', {class: 'small muted', style: 'margin-bottom:6px'}, 'Evidence and outputs of this step'),
      h('div', {class: 'row', style: 'gap:6px'}, evs.slice(0, 40).map(e => h('button', {class: 'btn sm', type: 'button', onclick: () => wbEvidence(mid, iid, e.id)}, icon(e.ok === false ? 'alert' : 'file'), e.label.slice(0, 60))),
        outs.map(o => h('a', {class: 'btn sm', href: `/api/m/${mid}/items/${iid}/outputs/${encodeURIComponent(o.name)}`, download: o.name}, icon('download'), o.label)))) : null,
    !can ? h('p', {class: 'small muted', style: 'margin-top:12px'}, 'You can look at this work item; only its owner, or a builder it is shared with, can change it.') : null);
}

function wbSide(mid, iid, it, can) {
  const cards = [];
  if (it.outputs.length) cards.push(h('div', {class: 'card', style: 'margin:0'}, h('div', {class: 'card-head'}, h('h3', {}, 'Outputs'), h('span', {class: 'sp'}), h('span', {class: 'small muted'}, `${it.outputs.length} file${it.outputs.length === 1 ? '' : 's'}`)),
    h('div', {class: 'wblist'}, it.outputs.map(o => h('div', {}, icon('file'), h('span', {}, h('a', {href: `/api/m/${mid}/items/${iid}/outputs/${encodeURIComponent(o.name)}`, download: o.name}, o.label),
      h('div', {class: 'small muted'}, `${o.name} · ${size(o.bytes)}`)))))));
  // the item's uploads, and more of them when a later step reads what arrives after the start (POST …/files)
  const addIn = h('input', {type: 'file', multiple: true, 'aria-label': 'Add files to this work item', style: 'display:none', onchange: async e => {
    const fd = new FormData(); [...e.target.files].forEach(f => fd.append('files', f, f.name)); e.target.value = '';
    try { const r = await upload(`/api/m/${mid}/items/${iid}/files`, fd); notify(`${r.added.length} file${r.added.length === 1 ? '' : 's'} added`, 'ok'); wbItem(mid, iid); } catch (x) { notify(x.message, 'err'); } }});
  if (it.files.length || (can && !it.closed)) cards.push(h('div', {class: 'card', style: 'margin:0'}, h('div', {class: 'card-head'}, h('h3', {}, 'Files'), h('span', {class: 'sp'}), h('span', {class: 'small muted'}, `${it.files.length} upload${it.files.length === 1 ? '' : 's'}`)),
    it.files.length ? h('div', {class: 'wblist'}, it.files.map(f => h('div', {}, icon('clip'), h('span', {}, f.name, h('div', {class: 'small muted'}, size(f.bytes)))))) : h('div', {class: 'muted small'}, 'No uploads yet.'),
    can && !it.closed ? h('div', {class: 'row', style: 'margin-top:8px'}, h('button', {class: 'btn sm', type: 'button', onclick: () => addIn.click()}, icon('clip'), 'Add files'), addIn) : null));
  const byStep = {};
  it.evidence.forEach(e => { (byStep[e.step] = byStep[e.step] || []).push(e); });
  cards.push(h('div', {class: 'card', style: 'margin:0'}, h('div', {class: 'card-head'}, h('h3', {}, 'Evidence'), h('span', {class: 'sp'}), h('span', {class: 'small muted'}, `${it.evidence.length} item${it.evidence.length === 1 ? '' : 's'}`)),
    it.evidence.length ? h('div', {class: 'wblist'}, it.steps.filter(s => byStep[s.id]).map(s => h('div', {style: 'display:block'}, h('b', {class: 'small'}, s.name),
      h('div', {class: 'row', style: 'gap:4px;margin-top:4px'}, byStep[s.id].slice(-12).map(e => h('button', {class: 'btn sm ghost', type: 'button', onclick: () => wbEvidence(mid, iid, e.id), title: e.label}, icon(e.ok === false ? 'alert' : 'file'), e.label.slice(0, 34)))))))
      : h('div', {class: 'muted small'}, 'Evidence appears here as each step runs.')));
  const sched = it.schedule;
  const DAYS_ = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
  const sWd = h('select', {class: 'sel', style: 'min-width:0;width:auto', 'aria-label': 'Weekday'}, DAYS_.map((d, i) => h('option', {value: i, selected: i === ((sched || {}).weekday || 0)}, d)));
  const sMd = h('select', {class: 'sel', style: 'min-width:0;width:auto', 'aria-label': 'Day of the month'},
    [...Array.from({length: 28}, (_, i) => [String(i + 1), `day ${i + 1}`]), ['last', 'the last day']].map(([v, l]) => h('option', {value: v, selected: v === String((sched || {}).day || 1)}, l)));
  const sShow = () => { sWd.hidden = every.value !== 'week'; sMd.hidden = every.value !== 'month'; };
  const every = h('select', {class: 'sel', style: 'min-width:0;width:auto', 'aria-label': 'How often', onchange: () => sShow()}, [['hour', 'Every hour'], ['day', 'Every day'], ['week', 'Every week'], ['month', 'Every month']].map(([v, l]) => h('option', {value: v, selected: (sched || {every: 'day'}).every === v}, l)));
  sShow();
  const at = h('input', {type: 'text', value: (sched || {}).at || '06:00', 'aria-label': 'At (HH:MM)', style: 'width:72px'});
  const tz = h('input', {type: 'text', value: (sched || {}).tz || myTz(), 'aria-label': 'Time zone', style: 'width:96px'});
  const routeKind = h('select', {class: 'sel', 'aria-label': 'Hand it to'}, h('option', {value: 'ticket'}, 'The service desk (a ticket)'), h('option', {value: 'heal'}, 'Self-healing'));
  const routeTitle = h('input', {type: 'text', placeholder: 'What is wrong, in one line', 'aria-label': 'What is wrong'});
  const routeDetail = h('textarea', {rows: 2, placeholder: 'What you saw and where (optional)', 'aria-label': 'Details'});
  cards.push(h('div', {class: 'card', style: 'margin:0'}, h('h3', {}, 'Run & support'),
    h('div', {class: 'small', style: 'margin:6px 0'}, sched ? [h('b', {}, it.schedule_text), ` · next run ${when(it.next_run)}`, it.last_run ? ` · last ${ago(it.last_run)}` : ''] : 'No schedule: it runs when someone starts it.'),
    can && !it.closed ? h('div', {class: 'wbcad'}, every, sWd, sMd, at, tz, h('button', {class: 'btn sm', type: 'button', onclick: async () => { try { const r = await api(`/api/m/${mid}/items/${iid}/schedule`, {method: 'POST', json: {every: every.value, at: at.value, tz: tz.value, weekday: Number(sWd.value), day: sMd.value === 'last' ? 'last' : Number(sMd.value)}}); notify('Schedule saved', 'ok'); wbDrawItem(mid, iid, r); } catch (e) { notify(e.message, 'err'); } }}, sched ? 'Change' : 'Schedule'),
      sched ? h('button', {class: 'btn sm ghost', type: 'button', onclick: async () => { try { const r = await api(`/api/m/${mid}/items/${iid}/schedule`, {method: 'DELETE'}); notify('Schedule switched off', 'ok'); wbDrawItem(mid, iid, r); } catch (e) { notify(e.message, 'err'); } }}, 'Switch off') : null) : null,
    it.handoffs.length ? h('div', {class: 'wblist', style: 'margin-top:10px'}, it.handoffs.map(x => h('div', {}, icon(x.kind === 'heal' ? 'heart' : x.kind === 'ticket' ? 'bell' : 'send'),
      h('span', {}, h('b', {}, {heal: 'Self-healing', ticket: 'Ticket', write: 'Write', expected: 'Expected', ignore: 'Ignored'}[x.kind] || x.kind), `: ${x.label} — ${x.status}`, x.link ? [' ', h('a', {href: x.link}, 'Open')] : null)))) : null,
    can && !it.closed ? h('details', {style: 'margin-top:10px'}, h('summary', {class: 'small'}, 'Hand a problem on'), h('div', {class: 'stack', style: 'gap:6px;margin-top:6px'}, routeKind, routeTitle, routeDetail,
      h('button', {class: 'btn sm', type: 'button', onclick: async () => { if (!routeTitle.value.trim()) { notify('Say what is wrong.', 'err'); return; } try { await api(`/api/m/${mid}/items/${iid}/route`, {method: 'POST', json: {route: routeKind.value, title: routeTitle.value.trim(), detail: routeDetail.value}}); notify('Proposed — it goes out once it is approved in the validation queue', 'ok'); wbItem(mid, iid); } catch (e) { notify(e.message, 'err'); } }}, 'Propose the hand-off'),
      h('div', {class: 'hint'}, 'Nothing is raised until a named person approves it.'))) : null));
  if (it.decisions.length) cards.push(h('div', {class: 'card', style: 'margin:0'}, h('div', {class: 'card-head'}, h('h3', {}, 'Decisions'), h('span', {class: 'sp'}), h('a', {class: 'small', href: '#/validate'}, 'Queue →')),
    h('div', {class: 'wblist'}, it.decisions.slice(-12).reverse().map(c => h('div', {}, icon(c.status === 'accepted' ? 'check' : c.status === 'open' ? 'clock' : 'x'),
      h('span', {}, h('b', {}, c.name), h('div', {class: 'small muted'}, c.status === 'open' ? `waiting since ${ago(c.created)}` : `${c.status.replace('_', ' ')} by ${c.decided_by || '—'} ${ago(c.decided)}` + (c.comment ? ` — “${c.comment}”` : ''))))))));
  if (it.lineage.length || it.observe.length) cards.push(h('div', {class: 'card', style: 'margin:0'}, h('h3', {}, 'Lineage'),
    h('div', {class: 'wblist', style: 'margin-top:6px'}, it.lineage.map(n => h('div', {}, icon(n.kind === 'job' ? 'cpu' : 'db'), h('a', {href: `#/lineage?focus=${encodeURIComponent(n.id)}`}, n.label)))),
    it.observe.length ? h('div', {class: 'note', style: 'margin-top:10px'}, h('b', {}, 'Data observability watches this too: '), it.observe.map((o, i) => [i ? ', ' : '', h('a', {href: o.link}, o.label + (o.incident ? ` (open incident: ${o.incident_title})` : ''))])) : null));
  cards.push(h('div', {class: 'card', style: 'margin:0'}, h('div', {class: 'card-head'}, h('h3', {}, 'Activity'), h('span', {class: 'sp'}), h('span', {class: 'small muted'}, 'newest last')),
    it.activity.length ? h('div', {class: 'small', tabindex: '0', role: 'region', 'aria-label': 'Activity log', style: 'max-height:280px;overflow:auto'}, it.activity.slice(-25).map(e => h('div', {class: 'row', style: 'gap:8px;padding:3px 0;border-top:1px solid var(--line);flex-wrap:nowrap'},
      h('span', {class: 'muted', style: 'flex:none;width:70px'}, clock(e.ts)), h('span', {style: 'min-width:0;overflow-wrap:anywhere;color:' + (e.level === 'error' ? 'var(--err)' : e.level === 'warn' ? 'var(--warn)' : 'inherit')}, e.text || (e.tool ? `${e.tool}` : e.kind)))))
      : h('div', {class: 'muted small'}, 'Nothing yet.')));
  if (can && it.access && it.access.can_share && !it.closed) {
    const sel = h('select', {class: 'sel', style: 'width:auto', 'aria-label': 'Who can see it'}, [['private', 'Only me'], ['team', 'My team'], ['org', 'Everyone in the organisation']].map(([v, l]) => h('option', {value: v, selected: v === it.visibility}, l)));
    cards.push(h('div', {class: 'card', style: 'margin:0'}, h('h3', {}, 'Who can see it'), h('div', {class: 'row', style: 'gap:6px;margin-top:8px'}, sel,
      h('button', {class: 'btn sm', type: 'button', onclick: async () => { try { const r = await api(`/api/m/${mid}/items/${iid}/visibility`, {method: 'POST', json: {visibility: sel.value}}); notify('Saved', 'ok'); wbDrawItem(mid, iid, r); } catch (e) { notify(e.message, 'err'); } }}, 'Save'))));
  }
  return cards;
}

function wbClose(mid, iid, it) {
  const ta = h('textarea', {rows: 3, placeholder: 'Why does it close? (kept in the audit log)', 'aria-label': 'Why it closes'});
  const mm = modal(`Close: ${it.title}`, h('div', {class: 'mbody'}, h('p', {class: 'small muted', style: 'margin-top:0'}, 'Open checks are withdrawn and a running step is stopped. The folder, its evidence and the decisions stay.'), ta,
    h('div', {class: 'row', style: 'justify-content:flex-end;margin-top:12px'}, h('button', {class: 'btn danger solid', type: 'button', onclick: async () => {
      if (!ta.value.trim()) { notify('Say why it closes.', 'err'); return; }
      try { const r = await api(`/api/m/${mid}/items/${iid}/close`, {method: 'POST', json: {comment: ta.value.trim()}}); mm.remove(); notify('Closed', 'ok'); wbDrawItem(mid, iid, r); } catch (e) { notify(e.message, 'err'); } }}, 'Close the work item'))));
}

/* the module page's Connections card: the person's connections of the kinds this module reads, and the wizard */
function wbConnections(mid, work, pk) {
  const kinds = new Set(pk.work[work].platforms.flatMap(p => (pk.platforms[p] || {}).kinds || []));
  const card = h('div', {class: 'card', style: 'margin:0'}, h('h3', {}, 'Connections'), h('div', {class: 'muted small'}, 'Loading…'));
  if (!kinds.size) { card.replaceChildren(h('h3', {}, 'Connections'), h('div', {class: 'small muted'}, 'This work reads uploads: no connection needed.')); return card; }
  api('/api/connections').then(r => {
    const mine = (r.connections || []).filter(c => kinds.has(c.kind));
    card.replaceChildren(h('div', {}, h('h3', {}, 'Connections'),
      h('div', {class: 'small muted', style: 'margin:-4px 0 8px'}, mine.length ? `${mine.length} you can use here — read-only unless write was granted.` : 'You have no connection this module can read yet. Add one, or upload files when you start the work.'),
      mine.length ? h('div', {class: 'wblist'}, mine.map(c => h('div', {}, typeof connDot === 'function' ? connDot(c) : null, h('span', {}, h('b', {}, c.name), h('span', {class: 'small muted'}, ` · ${c.label}`))))) : null,
      h('div', {class: 'row', style: 'margin-top:10px;gap:8px'}, typeof connectionWizard === 'function' ? h('button', {class: 'btn sm', type: 'button', onclick: () => connectionWizard({suggest: [...kinds], onDone: () => wbModule(mid, work)})}, icon('plus'), 'New connection') : null,
        h('a', {class: 'small', href: '#/connections'}, 'All connections →'))));
  }).catch(e => card.replaceChildren(h('h3', {}, 'Connections'), h('div', {class: 'note err'}, e.message)));
  return card;
}
