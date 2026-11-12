/* ---------------- Migrate BI (P15): Discover -> Decide -> Convert -> Prove -> Hand over -> Run for a BI estate.
   #/migrate-bi (start screen and programmes) - #/migrate-bi/<id>/<step>[/<sub>] (GET/POST /api/migrate-bi/...) ---------------- */
const MB = {id: null, p: null, step: 'discover', sub: null, timer: null, tab: 'Summary', focus: null, rules: null, pick: 'review', sel: new Set(), filter: {q: '', dec: 'keep', type: 'all', used: 'any', convert: 'all'}, page: 0,
  inv: {q: '', type: 'all', used: 'any', convert: 'all', decision: 'all', page: 0}, est: null, estTimer: null, prevTimer: null, feedShown: 0, detail: {}, logq: ''};
const MB_STEPS = [['discover', 'Discover'], ['decide', 'Decide'], ['convert', 'Convert'], ['prove', 'Prove'], ['handover', 'Hand over'], ['run', 'Run']];
const MB_SUBS = [['connect', 'Where it lives'], ['agents', 'Agents & AI'], ['scan', 'Scan'], ['found', 'What we found']];
const MB_DEC = {keep: ['Keep', 'ok'], merge: ['Merge', 'info'], retire: ['Retire', 'mute'], review: ['Needs a decision', 'you']};
const MB_RSTAT = {queued: 'mute', converting: 'run', converted: 'info', proven: 'ok', accepted: 'ok', sent_back: 'err', error: 'err', gates_failed: 'err', open_items: 'you'};
const mbSet = (el, ...kids) => el.replaceChildren(...kids.flat(Infinity).filter(k => k != null && k !== false));   // arrays flattened, nulls dropped (replaceChildren renders them as text)
const mbPill = (text, cls) => h('span', {class: 'pill plain ' + (cls || 'mute')}, text);
const mbTag = text => h('span', {class: 'tag warn', style: 'letter-spacing:.06em;font-size:10.5px'}, text);
const mbProven = text => h('span', {class: 'proven', style: 'display:inline-flex;align-items:center;gap:5px;font-weight:600'}, icon('check'), text);
const mbPct = (a, b) => b ? Math.round(100 * a / b) : 0;
const mbMins = m => m < 60 ? `${m} min` : `${(m / 60).toFixed(1)} h`;
function mbStyles() {
  if (document.getElementById('mb-css')) return;
  document.head.append(h('style', {id: 'mb-css'},
    '.mb-journey li a{display:block;text-decoration:none!important;color:inherit;padding-right:10px;border-radius:6px}.mb-journey li a:hover .jl{text-decoration:underline}' +
    '.mb-journey li.done .dot{background:var(--signal);border-color:var(--signal);color:var(--on-accent);font-size:9px;display:grid;place-items:center}.mb-journey li.done::before{background:var(--signal)}' +
    '.mb-journey li.on .jl{color:var(--accent)}.mb-journey li.on .dot{border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-tint)}.mb-journey li.locked a{opacity:.55;cursor:not-allowed}' +
    '.mb-sub{display:inline-flex;border:1px solid var(--line-2);border-radius:var(--radius-sm);overflow:hidden;background:var(--surface);margin:0 0 16px;flex-wrap:wrap}' +
    '.mb-sub a{padding:7px 14px;border-right:1px solid var(--line);color:var(--ink);text-decoration:none!important;font-size:13px}.mb-sub a:last-child{border-right:0}.mb-sub a.on{background:var(--accent-tint);color:var(--accent);font-weight:600}.mb-sub a.off{opacity:.55}' +
    '.mb-g4{display:grid;gap:14px;grid-template-columns:repeat(4,minmax(0,1fr))}.mb-g3{display:grid;gap:14px;grid-template-columns:repeat(3,minmax(0,1fr))}.mb-g2{display:grid;gap:14px;grid-template-columns:repeat(2,minmax(0,1fr))}' +
    '.mb-side{display:grid;gap:16px;grid-template-columns:minmax(0,1fr) 320px;align-items:start}' +
    '@media(max-width:1200px){.mb-g4{grid-template-columns:repeat(2,minmax(0,1fr))}.mb-g3{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:760px){.mb-g4,.mb-g3,.mb-g2,.mb-side{grid-template-columns:1fr}}' +
    '.mb-now{background:var(--surface-2);border-radius:var(--radius-sm);padding:9px 14px;font-size:13px;margin:12px 0;display:flex;gap:8px;align-items:center}' +
    '.mb-feed{display:flex;flex-direction:column;max-height:420px;overflow-y:auto}.mb-feed .fi{display:grid;grid-template-columns:62px 1fr;gap:10px;padding:7px 2px;border-bottom:1px solid var(--line);font-size:13px}' +
    '.mb-feed .ft{font-family:var(--mono);font-size:11.5px;color:var(--faint);padding-top:1px}.mb-feed .fi.warn .fx{color:var(--warn)}.mb-feed .fi.err .fx{color:var(--err)}' +
    '.mb-rule{display:grid;grid-template-columns:120px 1fr;gap:10px 16px;padding:14px 0;border-bottom:1px solid var(--line)}.mb-rule:last-child{border-bottom:0}.mb-rule .rl{padding-top:4px}' +
    '.mb-rule .rlines{display:flex;flex-direction:column;gap:10px}.mb-rline{display:flex;align-items:center;gap:10px;flex-wrap:wrap;font-size:13.5px}' +
    '.mb-rline input[type=number]{width:84px;border:1px solid var(--line-2);border-radius:var(--radius-sm);padding:6px 8px;background:var(--surface);color:var(--ink)}.mb-rline input[type=text]{width:240px}' +
    '.mb-def{font-size:12px;color:var(--faint)}.mb-def.changed{color:var(--warn);font-weight:600}@media(max-width:760px){.mb-rule{grid-template-columns:1fr}}' +
    '.mb-tile{cursor:pointer;text-align:left}.mb-tile.on{border-color:var(--accent);box-shadow:0 0 0 1px var(--accent) inset}' +
    '.mb-groups{display:grid;gap:10px;grid-template-columns:repeat(4,minmax(0,1fr))}@media(max-width:760px){.mb-groups{grid-template-columns:repeat(2,minmax(0,1fr))}}' +
    '.mb-stage{border:1px solid var(--line);background:var(--surface);border-radius:var(--radius-sm);padding:10px 12px;cursor:pointer;text-align:left;min-width:0;color:var(--ink)}.mb-stage:hover{border-color:var(--line-2)}' +
    '.mb-stage .st{font-weight:600;font-size:12.5px;display:flex;gap:6px;align-items:center}.mb-stage .ss{font-size:11.5px;color:var(--ink-2);margin-top:3px}' +
    '.mb-stage.done{border-color:var(--ok);background:var(--ok-tint)}.mb-stage.done .st{color:var(--ok)}.mb-stage.current{border-color:var(--accent);background:var(--accent-tint)}.mb-stage.current .st{color:var(--accent)}' +
    '.mb-row{cursor:pointer}.mb-row:hover td{background:var(--surface-2)}.mb-row.on td{background:var(--accent-tint)}' +
    '.mb-live{display:inline-flex;align-items:center;gap:6px;font-size:12px;border:1px solid var(--line);border-radius:99px;padding:3px 10px;background:var(--surface)}.mb-live::before{content:"";width:7px;height:7px;border-radius:50%;background:var(--accent);animation:pulse 1.4s infinite}.mb-live.idle::before{background:var(--ok);animation:none}' +
    '.mb-steps{display:flex;flex-direction:column;gap:8px;counter-reset:s}.mb-steps>div{display:flex;gap:12px;align-items:flex-start;border:1px solid var(--line);border-radius:var(--radius-sm);padding:10px 14px;background:var(--surface);font-size:13.5px}' +
    '.mb-steps>div::before{counter-increment:s;content:counter(s);width:24px;height:24px;border-radius:50%;background:var(--surface-2);color:var(--ink-2);font-size:12px;font-weight:700;display:grid;place-items:center;flex:none}' +
    '.mb-lin{width:100%;height:auto;max-height:520px;font-family:var(--font)}.mb-lin rect{fill:var(--surface);stroke:var(--line-2)}.mb-lin text{fill:var(--ink);font-size:11px}.mb-lin line{stroke:var(--line-2);stroke-width:1.2}.mb-lin .src rect{fill:var(--accent-tint)}' +
    '.mb-drop{border:1px dashed var(--line-2);border-radius:10px;padding:26px;text-align:center;color:var(--muted)}.mb-drop.over{border-color:var(--accent)}' +
    '.mb-chk{display:inline-flex;align-items:center;gap:6px;border:1px solid var(--line-2);border-radius:99px;padding:4px 10px;font-size:12.5px;cursor:pointer}.mb-chk.on{background:var(--accent-tint);border-color:var(--accent);color:var(--accent)}'));
}
function mbRoute() {
  const m = location.hash.match(/^#\/migrate-bi(?:\/(mig-[0-9a-f]+)(?:\/(\w+))?(?:\/(\w+))?)?(?:\?(.*))?$/);
  return {id: m ? m[1] : null, step: m && m[2] ? m[2] : null, sub: m && m[3] ? m[3] : null, query: Object.fromEntries(new URLSearchParams(m && m[4] ? m[4] : ''))};
}
async function renderMigrateBI() {
  mbStyles();
  const r = mbRoute();
  if (MB.timer) { clearInterval(MB.timer); MB.timer = null; }
  if (!r.id) { MB.id = null; return mbStart(); }
  if (MB.id !== r.id) { Object.assign(MB, {id: r.id, p: null, sel: new Set(), page: 0, focus: null, rules: null, detail: {}, feedShown: 0}); }
  MB.step = r.step || null; MB.sub = r.sub; MB.query = r.query;
  const main = $('#main');
  if (!MB.p) mbSet(main, skel('page'));
  try { MB.p = await api(`/api/migrate-bi/${r.id}`); } catch (e) { mbSet(main, h('div', {class: 'page'}, h('div', {class: 'card empty'}, h('h3', {}, 'Nothing here'), h('p', {}, e.message), h('a', {class: 'btn', href: '#/migrate-bi'}, 'BI migration')))); return; }
  if (mbRoute().id !== r.id) return;
  if (!MB.step) { location.replace(`#/migrate-bi/${r.id}/${MB.p.current_step}`); return; }
  mbDraw();
  const busy = () => MB.p && ((MB.p.scan.state === 'running' || MB.p.scan.state === 'queued') || MB.p.reports.some(x => ['queued', 'converting'].includes(x.status)) || MB.p.project_status === 'checking_drift');
  if (busy()) MB.timer = setInterval(async () => {
    if (mbRoute().id !== r.id) { clearInterval(MB.timer); MB.timer = null; return; }
    try { MB.p = await api(`/api/migrate-bi/${r.id}`); } catch (e) { return; }
    if (!document.activeElement || !/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)) mbDraw();
    if (!busy()) { clearInterval(MB.timer); MB.timer = null; }
  }, 1500);
}
/* ---------- start screen ---------- */
async function mbStart() {
  const main = $('#main');
  mbSet(main, skel('page'));
  let d;
  try { d = await api('/api/migrate-bi'); } catch (e) { mbSet(main, h('div', {class: 'page'}, h('div', {class: 'note err'}, e.message))); return; }
  if (location.hash !== '#/migrate-bi') return;
  const srcs = d.sources, tg = d.targets;
  const NEW = MB.NEW || (MB.NEW = {source: 'cognos', source_version: srcs[0].versions[0], target: 'powerbi', target_version: tg[0].versions[1] || tg[0].versions[0], read_from: 'sample', mode: 'rules_first', calls: 'live', visuals: 'relay', name: ''});
  const src = () => srcs.find(s => s.id === NEW.source) || srcs[0], tgt = () => tg.find(t => t.id === NEW.target) || tg[0];
  const box = h('div');
  const sel = (label, opts, value, on, extra) => h('div', {}, h('label', {class: 'f', style: 'margin-top:0'}, label), h('select', {class: 'sel', 'aria-label': label, onchange: e => on(e.target.value), ...(extra || {})}, opts));
  const seg = (opts, value, on, label) => h('div', {class: 'segbtn', role: 'group', 'aria-label': label}, opts.map(([k, l, dis]) => h('button', {type: 'button', class: value === k ? 'on' : '', 'aria-pressed': String(value === k), disabled: !!dis, title: dis || null, onclick: () => on(k)}, l)));
  const draw = () => mbSet(box, 
    h('div', {class: 'card'}, h('div', {class: 'card-head'}, h('h3', {}, 'New BI migration')),
      h('div', {class: 'mb-g4'},
        sel('Source tool', srcs.map(s => h('option', {value: s.id, selected: s.id === NEW.source, disabled: s.status !== 'available'}, s.label + (s.status !== 'available' ? ' - next' : ''))), NEW.source, v => { NEW.source = v; NEW.source_version = src().versions[0] || ''; if (v !== 'cognos' && NEW.read_from === 'sample') NEW.read_from = 'exports'; draw(); }),
        sel('Source version', src().versions.map(v => h('option', {value: v, selected: v === NEW.source_version}, v)), NEW.source_version, v => { NEW.source_version = v; }),
        sel('Target tool', tg.map(t => h('option', {value: t.id, selected: t.id === NEW.target, disabled: !!t.next}, t.label + (t.next ? ' - next' : ''))), NEW.target, v => { NEW.target = v; NEW.target_version = tgt().versions[0]; draw(); }),
        sel('Target version', tgt().versions.map(v => h('option', {value: v, selected: v === NEW.target_version}, v)), NEW.target_version, v => { NEW.target_version = v; })),
      h('div', {class: 'row', style: 'margin-top:14px'}, h('span', {class: 'small muted', style: 'min-width:150px'}, 'Where the estate lives'),
        seg([['server', 'Live server', src().server ? null : 'no live-server reader for this tool yet'], ['exports', 'Exports'], ['sample', 'Sample estate', NEW.source === 'cognos' ? null : 'the sample estate is a Cognos estate']], NEW.read_from, v => { NEW.read_from = v; draw(); }, 'Where the estate lives'),
        h('input', {type: 'text', style: 'flex:1;min-width:220px;width:auto', placeholder: 'Programme name, e.g. Contoso Cognos to Power BI', value: NEW.name, 'aria-label': 'Programme name', oninput: e => { NEW.name = e.target.value; }})),
      h('div', {class: 'row', style: 'margin-top:10px'}, h('span', {class: 'small muted', style: 'min-width:150px'}, 'Conversion'),
        seg(d.modes.map(m => [m.id, m.label]), NEW.mode, v => { NEW.mode = v; draw(); }, 'Conversion mode'),
        NEW.mode !== 'rules_only' ? seg([['live', 'Live AI calls'], ['batch', 'Batch AI calls']], NEW.calls, v => { NEW.calls = v; draw(); }, 'AI calls') : null,
        h('span', {class: 'spacer'})),
      h('div', {class: 'row', style: 'margin-top:10px'}, h('span', {class: 'small muted', style: 'min-width:150px'}, 'Target visuals'),
        seg([['relay', 'Visual Atlas visuals'], ['builtin', "Power BI's built-in visuals"]], NEW.visuals, v => { NEW.visuals = v; draw(); }, 'Target visuals'),
        h('span', {class: 'small muted'}, NEW.visuals === 'builtin' ? 'Nothing embedded: standard Power BI charts, cards and tables with their formatting - for tenants that block custom visuals.'
          : 'Designed visuals in the report theme, embedded in each report.'),
        h('span', {class: 'spacer'}),
        d.can_edit ? h('button', {class: 'btn primary', onclick: async () => { try { const p = await api('/api/migrate-bi', {json: NEW}); notify('Programme created - tell us where the estate lives', 'ok'); location.hash = `#/migrate-bi/${p.id}/discover/connect`; } catch (e) { notify(e.message, 'err'); } }}, 'Start a discovery')
          : h('span', {class: 'small muted'}, 'A BI Dev or an admin starts a migration.')),
      h('div', {class: 'note'}, h('b', {}, d.modes.find(m => m.id === NEW.mode).label.replace(' (recommended)', '') + ': '), d.modes.find(m => m.id === NEW.mode).help,
        NEW.mode !== 'rules_only' ? (NEW.calls === 'live' ? ' AI calls are answered live.' : ' AI calls are batched - cheaper, answers within hours.') : '', ' Discovering and deciding never need the AI.'),
      h('div', {class: 'note'}, h('b', {}, `${src().label} ${NEW.source_version}: `), 'objects in its own terms - ' + src().terms, h('div', {class: 'small muted', style: 'margin-top:4px'}, 'Accepts: ' + src().accepts)),
      NEW.read_from === 'sample' ? h('div', {class: 'hint'}, 'The sample estate is made up (1,842 objects with two and a half years of usage and the data behind its packages) so you can show the whole journey without a client server.') : null));
  draw();
  const rows = d.projects;
  mbSet(main, h('div', {class: 'page', id: 'mbstart'},
    pageHead({crumbs: [['Home', '#/'], ['BI migration']], eyebrow: brandName() + ' - Migrate - BI', title: 'Move a BI estate to Power BI - and prove it',
      promise: 'Discover what you have, decide what is worth keeping, convert only that, and prove every number against the source before anyone signs off.',
      actions: h('span', {class: 'small muted'}, `${d.rules.builtin} conversion rules - ${d.rules.learned.rules} learned`)}),
    box,
    h('div', {class: 'section-title'}, h('h2', {}, 'Programmes'), h('span', {class: 'hint'}, `${rows.length}`)),
    rows.length ? h('div', {class: 'card', style: 'padding:0;overflow:auto;margin:0'}, h('table', {class: 'utable'},
      h('tr', {}, ['Programme', 'Source', 'Target', 'Estate from', 'Conversion', 'Objects', 'Status', 'Created'].map((t, i) => h('th', {class: i === 5 ? '' : 'l'}, t))),
      rows.map(p => h('tr', {class: 'mb-row', onclick: () => { location.hash = `#/migrate-bi/${p.id}`; }}, h('td', {}, h('a', {href: `#/migrate-bi/${p.id}`}, p.name)), h('td', {}, p.source_label), h('td', {}, p.target_label),
        h('td', {}, p.read_from === 'sample' ? mbTag('SAMPLE') : p.read_from === 'server' ? 'live server' : 'exports'), h('td', {}, p.mode_label.replace(' (recommended)', '')), h('td', {class: 'n'}, fmtN(p.objects, 0)),
        h('td', {}, mbPill(p.status_label, {discovered: 'info', decided: 'info', converting: 'run', proven: 'ok', handed: 'ok', error: 'err', scanning: 'run'}[p.status] || 'mute')), h('td', {}, when(p.created))))))
      : h('div', {class: 'card empty'}, h('h3', {}, 'No programmes yet'), h('p', {}, 'Start a discovery above - the sample estate shows the whole journey without a client server.')),
    h('div', {class: 'mb-g3', style: 'margin-top:16px'},
      h('div', {class: 'card', style: 'margin:0'}, h('h3', {}, 'Discover'), h('p', {class: 'small muted'}, 'A live server, exports or the sample estate, read page by page with the activity shown; what we found in the tool\'s own terms, every number clickable.')),
      h('div', {class: 'card', style: 'margin:0'}, h('h3', {}, 'Decide & convert'), h('p', {class: 'small muted'}, 'Your rules with a live preview and a reason per object, signed by name; waves with time, AI cost and dependencies before anything runs; rules first, the agent only where no rule fits.')),
      h('div', {class: 'card', style: 'margin:0'}, h('h3', {}, 'Prove & hand over'), h('p', {class: 'small muted'}, 'Every number computed on both sides and compared; the review gates and Power BI\'s own engine; a hand-over pack with the owner\'s sign-off; nightly drift checks after go-live.')))));
  document.title = `BI migration - ${S.brand ? S.brand.full : 'RELAY by PASDACS'}`;
}
/* ---------- the programme: header, journey, steps ---------- */
function mbDraw() {
  const p = MB.p, main = $('#main');
  const steps = {discover: mbDiscover, decide: mbDecide, convert: mbConvert, prove: mbProve, handover: mbHandover, run: mbRun, log: mbLog};
  const body = (steps[MB.step] || mbDiscover)(p);
  const page = h('div', {class: 'page', id: 'mbpage'}, mbHead(p), body);
  const y = main.scrollTop;
  mbSet(main, page);
  main.scrollTop = y;
  document.title = `${p.name} - ${S.brand ? S.brand.full : 'RELAY by PASDACS'}`;
}
function mbHead(p) {
  const st = p.steps, busy = p.scan.state === 'running' || p.scan.state === 'queued', conv = p.reports.some(x => ['queued', 'converting'].includes(x.status));
  const statusCls = {discovered: 'info', decided: 'info', converting: 'run', proven: 'ok', handed: 'ok', error: 'err', scanning: 'run', scan_paused: 'you', scan_stopped: 'you'}[p.status] || 'mute';
  const head = pageHead({crumbs: [['Home', '#/'], ['BI migration', '#/migrate-bi'], [p.name]], eyebrow: `${brandName()} - Migrate - BI`,
    title: h('span', {}, p.name + ' ', p.sample ? mbTag('SAMPLE') : null),
    promise: `${p.source_label} ${p.source_version} ${p.target_label}${p.target_version ? ' (' + p.target_version + ')' : ''} - ${p.mode_label.replace(' (recommended)', '').toLowerCase()} - ${p.calls} AI calls${p.visuals === 'builtin' ? " - Power BI's built-in visuals" : ''}`,
    actions: h('div', {class: 'row', style: 'gap:8px;justify-content:flex-end'},
      busy ? h('span', {class: 'mb-live'}, `Scan running ${p.scan.pct} %`) : conv ? h('span', {class: 'mb-live'}, 'Converting') : mbPill(p.status_label, statusCls),
      h('a', {class: 'btn', href: `#/migrate-bi/${p.id}/log`}, icon('file'), 'Agent log'),
      h('button', {class: 'btn', onclick: () => mbLineage(p)}, icon('route'), 'Lineage'))});
  const first = {discover: 'discover/' + (st.done.discover ? 'found' : busy || p.scan.state === 'paused' ? 'scan' : 'connect'), decide: 'decide', convert: 'convert', prove: 'prove', handover: 'handover', run: 'run'};
  const journey = h('ol', {class: 'journey mb-journey', 'aria-label': 'Migration journey'}, MB_STEPS.map(([k, l], i) => {
    const locked = i > 0 && !st.done.discover, on = MB.step === k, done = st.done[k];
    return h('li', {class: (on ? 'on ' : '') + (done ? 'done ' : '') + (locked ? 'locked' : '')},
      h('a', {href: `#/migrate-bi/${p.id}/${first[k]}`, 'aria-current': on ? 'step' : null, 'aria-disabled': String(locked), onclick: e => { if (locked) { e.preventDefault(); notify('Discover the estate first', 'err'); } }},
        h('span', {class: 'dot'}, done ? '✓' : ''), h('div', {class: 'jl'}, `${i + 1} ${l}`), h('div', {class: 'js'}, st.sub[k] || ' ')));
  }));
  const subs = MB.step === 'discover' ? h('nav', {class: 'mb-sub', 'aria-label': 'Discover'}, MB_SUBS.map(([k, l]) => {
    const off = k === 'found' && !st.done.discover;
    return h('a', {href: `#/migrate-bi/${p.id}/discover/${k}`, class: ((MB.sub || 'connect') === k ? 'on' : '') + (off ? ' off' : ''), 'aria-current': (MB.sub || 'connect') === k ? 'page' : null,
      onclick: e => { if (off) { e.preventDefault(); notify('Run the scan first', 'err'); } }}, l);
  })) : null;
  return [head, journey, subs];
}
/* ---------- 1 Discover ---------- */
function mbDiscover(p) {
  const sub = MB.sub || 'connect';
  if (sub === 'agents') return mbAgents(p);
  if (sub === 'scan') return mbScan(p);
  if (sub === 'found') return mbFound(p);
  return mbConnect(p);
}
function mbConnect(p) {
  const c = p.connection || {}, edit = p.can_edit, info = c.info || {};
  const v = {url: c.url || (p.sample ? 'https://cognos-sample.relay.example/ibmcognos' : ''), namespace: c.namespace || '', user: c.user || (p.sample ? 'demo.analyst' : ''), secret: '', sign_in: c.sign_in || 'password', folders: c.folders || ''};
  const scope = {...(p.scope || {})};
  const right = h('div', {class: 'card', style: 'margin:0'});
  const drawRight = (testing) => mbSet(right, 
    testing ? [h('h3', {}, 'Testing the connection...'), skel('rows')]
    : c.ok ? [h('div', {class: 'row'}, h('h3', {style: 'margin:0'}, 'Connected'), mbPill('Read-only', 'ok')), h('dl', {class: 'kv', style: 'margin-top:12px'},
        ...[['Server', `${info.product || ''} ${info.version || ''}`], ['Content', `${fmtN(info.team_folders, 0)} team folders - ${fmtN(info.personal_folders, 0)} personal folders - ${fmtN(info.objects, 0)} objects`],
          ['Users', info.users != null ? `${fmtN(info.users, 0)}${c.namespace ? ' (' + c.namespace + ')' : ''}` : '-'], ['Usage source', info.usage_source ? `${info.usage_source} - ${fmtN(info.usage_days, 0)} days available` : 'none found'],
          ['Your permissions', info.permissions || '-'], ['Data', info.data_files ? `${info.data_files} table files behind the packages` : 'no table files (reports convert; proof needs the data)'],
          ['Estimated scan', info.estimate_seconds ? (info.estimate_seconds < 90 ? `about ${info.estimate_seconds} s` : `about ${Math.round(info.estimate_seconds / 60)} min`) : '-']].flatMap(([k, val]) => [h('dt', {}, k), h('dd', {}, val)])),
        h('div', {class: 'note', style: 'margin-top:12px'}, `Nothing is ever changed on ${p.source_label}. The scan reads pages slowly if the server asks it to.`)]
    : c.error ? [h('h3', {}, 'Not connected'), h('div', {class: 'note err'}, c.error), h('p', {class: 'small muted'}, 'Check the details and test again.')]
    : [h('h3', {}, 'Test the connection to see what the server reports'), h('p', {class: 'muted small'}, 'Version, folders, users, the usage source and your permissions appear here.')]);
  drawRight(false);
  const field = (label, k, type, ph, opt) => h('div', {}, h('label', {class: 'f', style: 'margin-top:0'}, label, opt ? h('small', {}, 'optional') : null), h('input', {type: type || 'text', value: v[k], placeholder: ph || '', disabled: !edit, autocomplete: 'off', 'aria-label': label, oninput: e => { v[k] = e.target.value; }}));
  const test = async btn => {
    if (edit && p.read_from === 'server') { try { await api(`/api/migrate-bi/${p.id}/connect`, {json: {...v, secret: v.secret || null, scope}}); } catch (e) { notify(e.message, 'err'); return; } }
    else if (edit) { try { await api(`/api/migrate-bi/${p.id}/connect`, {json: {scope}}); } catch (e) { /* scope only */ } }
    drawRight(true);
    try { const t = await api(`/api/migrate-bi/${p.id}/test`, {json: {}}); notify(t.ok ? 'Connection test passed' : (t.error || 'Not connected'), t.ok ? 'ok' : 'err'); }
    catch (e) { notify(e.message, 'err'); }
    MB.p = await api(`/api/migrate-bi/${p.id}`); mbDraw();
  };
  const scan = async () => { try { await api(`/api/migrate-bi/${p.id}/scan`, {json: {}}); location.hash = `#/migrate-bi/${p.id}/discover/scan`; } catch (e) { notify(e.message, 'err'); } };
  const checks = [['usage', 'Usage (Audit database)'], ['team', 'Team content folders'], ['views', 'Report views and schedules'], ['personal', 'Personal folders']];
  const upload = async files => {
    const fd = new FormData(); [...files].forEach(f => fd.append('files', f));
    try { const r = await api(`/api/migrate-bi/${p.id}/upload`, {method: 'POST', body: fd}); notify(`${r.files.length} file(s) received`, 'ok'); MB.p = await api(`/api/migrate-bi/${p.id}`); mbDraw(); } catch (e) { notify(e.message, 'err'); }
  };
  const input = h('input', {type: 'file', multiple: true, style: 'display:none', accept: '.zip,.xml,.json,.csv', onchange: e => upload(e.target.files)});
  const drop = h('div', {class: 'mb-drop', ondragover: e => { e.preventDefault(); drop.classList.add('over'); }, ondragleave: () => drop.classList.remove('over'), ondrop: e => { e.preventDefault(); drop.classList.remove('over'); upload(e.dataTransfer.files); }},
    icon('download'), h('h3', {style: 'margin:8px 0 4px'}, 'Drop deployment archives or exports'), h('p', {class: 'small', style: 'margin:0 0 10px'}, `${p.source_label}: ` + ((MB.srcInfo || {}).accepts || 'deployment archive (.zip) or the export folder: report specifications, dashboards, packages, content listing, Audit database export') + '. Nothing leaves your network until you upload.'),
    edit ? h('button', {class: 'btn', onclick: () => input.click()}, 'Choose files') : null, input,
    (MB.p.connection || {}).ok ? null : null);
  const files = (MB.p.files_list || []);
  return h('div', {class: 'mb-g2'},
    h('div', {class: 'card stack', style: 'margin:0'},
      h('div', {class: 'row'}, h('h3', {style: 'margin:0'}, p.read_from === 'server' ? `Connect to ${p.source_label}` : p.read_from === 'exports' ? `${p.source_label} exports` : `The sample ${p.source_label} estate`), p.sample ? mbTag('SAMPLE') : null,
        h('span', {class: 'spacer'}), h('span', {class: 'small muted'}, p.read_from === 'server' ? 'live server' : p.read_from === 'exports' ? 'exports' : 'sample estate')),
      p.read_from === 'exports' ? drop
        : p.read_from === 'server' ? [h('div', {class: 'mb-g2'}, field(`${p.source_label} URL`, 'url', 'text', 'https://'), field('Namespace', 'namespace', 'text', '', true),
            h('div', {}, h('label', {class: 'f', style: 'margin-top:0'}, 'Sign-in'), h('select', {class: 'sel', disabled: !edit, 'aria-label': 'Sign-in', onchange: e => { v.sign_in = e.target.value; }}, [['password', 'User and password'], ['apikey', 'API key']].map(([k, l]) => h('option', {value: k, selected: v.sign_in === k}, l)))),
            field('User', 'user'), field('Password / API key', 'secret', 'password', c.has_secret ? 'saved - type to change' : 'kept in the secrets store, by name'), field('Content to scan', 'folders', 'text', 'Team content: all folders', true))]
        : h('div', {class: 'note'}, h('b', {}, 'Sample estate: '), 'the sign-in is filled in for you. Test the connection to write the estate, then scan it.'),
      h('div', {}, h('div', {class: 'small', style: 'font-weight:600;margin-bottom:8px'}, 'What to scan'), h('div', {class: 'row'}, checks.map(([k, l]) => h('label', {class: 'mb-chk' + (scope[k] !== false ? ' on' : '')},
        h('input', {type: 'checkbox', checked: scope[k] !== false, disabled: !edit, style: 'margin:0', onchange: e => { scope[k] = e.target.checked; e.target.parentNode.classList.toggle('on', e.target.checked); }}), l)))),
      p.read_from === 'server' ? h('details', {}, h('summary', {class: 'small muted', style: 'cursor:pointer'}, 'Advanced - page size, rate limit, usage window'), h('div', {class: 'mb-g3', style: 'margin-top:10px'},
        h('div', {}, h('label', {class: 'f', style: 'margin-top:0'}, 'Page size'), h('input', {type: 'text', value: c.page_size || 100, 'aria-label': 'Page size', oninput: e => { v.page_size = +e.target.value; }})),
        h('div', {}, h('label', {class: 'f', style: 'margin-top:0'}, 'Max requests / s'), h('input', {type: 'text', value: c.max_rps || 4, 'aria-label': 'Max requests per second', oninput: e => { v.max_rps = +e.target.value; }})),
        h('div', {}, h('label', {class: 'f', style: 'margin-top:0'}, 'Usage window (days)'), h('input', {type: 'text', value: c.usage_days || 365, 'aria-label': 'Usage window', oninput: e => { v.usage_days = +e.target.value; }})))) : null,
      h('div', {class: 'row'}, edit ? h('button', {class: 'btn', onclick: e => test(e.currentTarget)}, 'Test connection') : null,
        edit ? h('button', {class: 'btn primary', disabled: !c.ok || p.scan.state === 'running', onclick: scan}, p.scan.state === 'done' ? 'Scan again' : 'Scan inventory') : h('span', {class: 'small muted'}, 'Read-only: a BI Dev or an admin connects and scans.'),
        p.scan.state === 'done' ? h('a', {class: 'btn', href: `#/migrate-bi/${p.id}/discover/found`}, 'What we found') : null),
      h('div', {class: 'hint'}, p.sample ? 'Sample estate: nothing is real; every name, folder and run is made up.' : p.read_from === 'server' ? 'Your password is stored encrypted, by name, and never shown again. The account only needs to read.' : 'Exports stay in this programme\'s folder; nothing is sent anywhere.')),
    right);
}
function mbAgents(p) {
  const agents = [['Discovery', 'Discover', 'Rules', 'reads objects page by page'], ['Usage', 'Discover', 'Rules', 'reads the Audit database'], ['Dependencies', 'Discover', 'Rules', 'links reports to packages and modules'],
    ['Decide', 'Decide', 'Rules', 'applies your rules, finds duplicates'], ['Parsing', 'Convert', 'Rules', 'reads each report definition'], ['Conversion rules', 'Convert', 'Rules', 'formulas, filters and visuals with a tested rule'],
    ['Gap filling', 'Convert', p.mode === 'rules_only' ? 'Nobody (rules only)' : 'Relay agent', p.mode === 'rules_only' ? 'calculations without a rule stay blank for a person' : 'writes the calculations no rule covers'],
    ['Review gates', 'Prove', 'Rules', 'definition, prototype, Power Query, data, schemas, consistency, best practices, accessibility, display'], ['DAX engine', 'Prove', 'Power BI (this PC)', 'every measure and visual evaluated by Power BI\'s own engine'],
    ['Checker', 'Prove', 'Rules', 'runs the source report\'s queries and compares every number'], ['Fixer', 'Prove', p.mode === 'rules_only' ? 'Nobody (rules only)' : 'Relay agent', 'fixes what the gates found, same session'], ['Packager', 'Hand over', 'Rules', 'builds the package and the proof pack']];
  const budget = h('input', {type: 'text', value: p.budget_usd, style: 'width:110px', 'aria-label': 'AI budget in USD', disabled: !p.can_edit});
  return h('div', {class: 'stack'},
    h('div', {class: 'mb-g3'}, kpiTile('AI provider', 'Relay agent', 'this installation\'s login (Admin > Runners)', {href: '#/admin/ai'}),
      h('div', {class: 'card kpi'}, h('div', {class: 'kl'}, 'Budget for this programme'), h('div', {class: 'row', style: 'gap:6px;margin:4px 0'}, h('span', {class: 'kv', style: 'font-size:22px'}, '$'), budget,
        p.can_edit ? h('button', {class: 'btn sm', onclick: async () => { try { MB.p = await api(`/api/migrate-bi/${p.id}/budget`, {method: 'PUT', json: {budget_usd: Number(budget.value || 0)}}); notify('Budget saved', 'ok'); mbDraw(); } catch (e) { notify(e.message, 'err'); } }}, 'Save') : null),
        h('div', {class: 'ks'}, `spent so far ${usd(p.ai.cost_usd)} in ${p.ai.calls} call(s) - a wave past the budget is refused`)),
      kpiTile('Agents', String(agents.length), `${agents.filter(a => a[2].includes('agent')).length} use AI - ${agents.length - agents.filter(a => a[2].includes('agent')).length} are rules or engines`)),
    h('div', {class: 'banner info'}, h('div', {class: 'ic'}, icon('info')), h('div', {class: 'txt'}, h('div', {class: 't'}, 'Agents take turns - one AI run at a time - so cost and logs stay predictable.'), h('div', {class: 'd'}, 'Reading the estate and every rule-based step never use the AI.'))),
    h('div', {class: 'card', style: 'padding:0;overflow:auto;margin:0'}, h('table', {class: 'utable'}, h('tr', {}, ['Agent', 'Step', 'Does', 'Uses'].map(t => h('th', {class: 'l'}, t))),
      agents.map(a => h('tr', {}, h('td', {}, h('b', {}, a[0])), h('td', {}, a[1]), h('td', {}, a[3]), h('td', {}, mbPill(a[2], a[2].includes('agent') ? 'info' : 'mute')))))),
    h('div', {class: 'note'}, h('b', {}, `${p.mode_label.replace(' (recommended)', '')}: `), p.mode_help, ' Rules learned from accepted answers in this ', p.tenant === 'default' ? 'installation' : 'partner\'s estates', ': ', String(p.rule_pack.rules), '.'));
}
function mbScan(p) {
  const s = p.scan, edit = p.can_edit, running = s.state === 'running' || s.state === 'queued', paused = s.state === 'paused', done = s.state === 'done';
  const elapsed = s.started ? (s.finished || Date.now() / 1000) - s.started : 0;
  const left = running && s.pct > 2 ? Math.max(0, Math.round(elapsed * (100 - s.pct) / s.pct)) : null;
  const ctl = async a => { try { MB.p = await api(`/api/migrate-bi/${p.id}/scan/${a}`, {json: {}}); notify({pause: 'Paused - resumes from the same page, even after a restart', resume: 'Resumed', stop: 'Stopping - objects read so far are kept'}[a], 'ok'); mbDraw(); if (!MB.timer) renderMigrateBI(); } catch (e) { notify(e.message, 'err'); } };
  const start = async () => { try { MB.p = await api(`/api/migrate-bi/${p.id}/scan`, {json: {}}); mbDraw(); renderMigrateBI(); } catch (e) { notify(e.message, 'err'); } };
  const found = s.found || {}, keys = ['Reports', 'Report views', 'Dashboards', 'Stories', 'Data modules', 'Packages', 'Apps', 'Documents'].filter(k => k in found).concat(Object.keys(found).filter(k => !['Reports', 'Report views', 'Dashboards', 'Stories', 'Data modules', 'Packages', 'Apps', 'Documents'].includes(k)));
  const max = Math.max(1, ...keys.map(k => found[k] || 0));
  const feed = h('div', {class: 'mb-feed', 'aria-live': 'polite'}, h('div', {class: 'muted small', style: 'padding:14px'}, 'Agent activity appears here as it happens.'));
  api(`/api/migrate-bi/${p.id}/activity`).then(r => {
    const ev = r.events.filter(e => e.kind === 'app').reverse();
    if (!ev.length) return;
    mbSet(feed, ...ev.map(e => h('div', {class: 'fi ' + (e.level || '')}, h('span', {class: 'ft'}, clock(e.ts)), h('span', {class: 'fx'}, h('b', {style: 'font-weight:600;margin-right:6px;letter-spacing:.04em;font-size:11px;color:var(--ink-2)'}, (e.stage || 'scan').toUpperCase()), e.text))));
  }).catch(() => {});
  return h('div', {class: 'stack'},
    h('div', {class: 'row'}, h('h3', {style: 'margin:0;font-size:17px'}, `Scan ${p.source_label}`), p.sample ? mbTag('SAMPLE') : null, h('span', {class: 'spacer'}),
      h('span', {class: 'small muted'}, done ? `Done in ${dur((s.seconds || elapsed) * 1000)}` : running ? `${s.pct} %${left != null ? ' - about ' + dur(left * 1000) + ' left' : ''}` : paused ? `Paused at ${s.pct} %` : s.state === 'stopped' ? `Stopped at ${s.pct} %` : 'Not started'),
      edit && running ? [h('button', {class: 'btn sm', onclick: () => ctl('pause')}, 'Pause'), h('button', {class: 'btn sm danger', onclick: async () => { if (await confirmBox('Stop the scan?', 'Objects read so far are kept; you can resume from the same page later.', 'Stop', true)) ctl('stop'); }}, 'Stop')] : null,
      edit && paused ? [h('button', {class: 'btn sm primary', onclick: () => ctl('resume')}, 'Resume'), h('button', {class: 'btn sm danger', onclick: () => ctl('stop')}, 'Stop')] : null,
      edit && s.state === 'stopped' ? h('button', {class: 'btn sm primary', onclick: () => ctl('resume')}, 'Resume from the same page') : null,
      edit && (!s.state || s.state === 'idle' || s.state === 'error') ? h('button', {class: 'btn primary', onclick: start}, 'Start scan') : null),
    h('div', {class: 'progress'}, h('div', {style: `width:${s.pct || 0}%`})),
    h('div', {class: 'mb-now'}, running ? h('span', {class: 'spin'}) : icon(done ? 'check' : 'info'), h('b', {}, 'Now: '), running ? (s.phase ? `${s.phase}${s.pages ? ` - page ${s.page} of ${s.pages}` : ''}` : 'starting') : done ? 'nothing - scan finished, inventory ready' : paused ? 'paused' : s.state === 'stopped' ? 'stopped - resume when ready' : 'waiting for you to start',
      s.waits ? h('span', {class: 'small muted'}, ` - the server asked to slow down ${s.waits} time${s.waits === 1 ? '' : 's'}`) : null),
    p.error && !running ? h('div', {class: 'note err'}, p.error) : null,
    h('div', {class: 'mb-g2'},
      h('div', {class: 'card', style: 'margin:0'}, h('div', {class: 'card-head'}, h('h3', {}, 'Objects found')), keys.length ? h('div', {class: 'bars'}, keys.map(k => bar2(k, found[k] || 0, max, `#/migrate-bi/${p.id}/discover/found`))) : h('div', {class: 'muted small'}, 'Nothing read yet.')),
      h('div', {class: 'card', style: 'margin:0'}, h('div', {class: 'card-head'}, h('h3', {}, 'Activity ', h('small', {class: 'muted'}, 'newest first')), h('span', {class: 'sp'}), h('a', {class: 'btn sm ghost', href: `#/migrate-bi/${p.id}/log`}, 'Full log')), feed)),
    h('div', {class: 'row'}, h('span', {class: 'small muted'}, 'Read-only. You can leave this page - the scan keeps running and tells you when it\'s done.'), h('span', {class: 'spacer'}),
      h('a', {class: 'btn' + (done ? ' primary' : ''), href: `#/migrate-bi/${p.id}/discover/found`, 'aria-disabled': String(!done), onclick: e => { if (!done) { e.preventDefault(); notify('The inventory opens when the scan finishes', 'err'); } }}, 'See the inventory')));
}
function mbFound(p) {
  const c = p.counts;
  if (!c) return h('div', {class: 'card empty'}, h('h3', {}, 'No inventory yet'), h('p', {}, 'Run the scan first.'), h('a', {class: 'btn primary', href: `#/migrate-bi/${p.id}/discover/scan`}, 'Go to scan'));
  const r = p.ready || {auto: 0, review: 0, no: 0};
  const types = Object.entries(c.by_type), folders = Object.entries(c.by_folder).slice(0, 8);
  const why = () => mbDrawer(`Why ${mbPct(r.auto, c.objects)} % are ready to convert`, 'Prediction from the definitions, before any conversion', [
    h('div', {class: 'note'}, 'An object is "automatic" when every formula, filter and visual in it has a tested conversion rule, or at most one formula needs the agent (checked by the review gates and the proof before use).'),
    h('table', {class: 'utable'}, h('tr', {}, ['Prediction', 'Objects', 'Main reason'].map((t, i) => h('th', {class: i === 1 ? '' : 'l'}, t))),
      [['Automatic', r.auto, 'every formula, filter and visual has a rule'], ['Needs a look', r.review, '1-3 calculations without a rule (running totals, ranks), a filter without a rule, or a crosstab shown as a chart'], ['Not yet', r.no, 'Active Reports, HTML items with scripts, maps, a missing package, or 4+ calculations without a rule']].map(x => h('tr', {}, h('td', {}, x[0]), h('td', {class: 'n'}, fmtN(x[1], 0)), h('td', {}, x[2])))),
    h('div', {class: 'small muted'}, 'Confidence: high for simple and medium objects; very complex ones are often "needs a look" even when every rule fits. Click any row of the table to see its reason.')]);
  const inv = h('div', {}, skel('rows'));
  mbInventory(p, inv, {decision: 'all'});
  return h('div', {class: 'stack'},
    h('div', {class: 'row'}, h('h3', {style: 'margin:0;font-size:17px'}, 'What we found'), p.sample ? mbTag('SAMPLE') : null, h('span', {class: 'small muted'}, c.usage_to ? `as of ${c.usage_to}` : ''), h('span', {class: 'spacer'}),
      h('a', {class: 'btn', href: `/api/migrate-bi/${p.id}/inventory.csv`}, icon('download'), 'Export to CSV'), h('a', {class: 'btn primary', href: `#/migrate-bi/${p.id}/decide`}, 'Decide what to keep')),
    h('div', {class: 'mb-g4'},
      kpiTile('Objects found', fmtN(c.objects, 0), types.map(([t, n]) => `${fmtN(n, 0)} ${(t.endsWith('y') ? t.slice(0, -1) + 'ies' : t + 's').toLowerCase()}`).join(' - '), {href: `#/migrate-bi/${p.id}/convert`}),
      kpiTile('Used in 90 days', mbPct(c.used_90, c.objects) + ' %', `${fmtN(c.used_90, 0)} used - ${fmtN(c.objects - c.used_90, 0)} not`),
      h('div', {class: 'card kpi click', role: 'button', tabindex: '0', onclick: why, onkeydown: e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); why(); } }}, h('div', {class: 'kl'}, 'Ready to convert'), h('div', {class: 'kv'}, mbPct(r.auto, c.objects) + ' %'),
        h('div', {class: 'ks'}, `${fmtN(r.review, 0)} need a look - ${fmtN(r.no, 0)} not yet - why?`)),
      kpiTile('Shared objects', fmtN(c.shared_objects, 0), `${fmtN(c.datasets['data module'], 0)} data modules - ${fmtN(c.datasets.package, 0)} packages - ${c.with_data} with data`)),
    h('div', {class: 'mb-g3'},
      h('div', {class: 'card', style: 'margin:0'}, h('div', {class: 'card-head'}, h('h3', {}, 'Last used')), h('div', {class: 'bars'}, Object.entries(c.last_used).map(([k, n]) => bar2(k, n, c.objects, `#/migrate-bi/${p.id}/convert`)))),
      h('div', {class: 'card', style: 'margin:0'}, h('div', {class: 'card-head'}, h('h3', {}, 'Complexity')), h('div', {class: 'bars'}, Object.entries(c.by_complexity).map(([k, n]) => bar2(k, n, c.objects, `#/migrate-bi/${p.id}/convert`)))),
      h('div', {class: 'card', style: 'margin:0'}, h('div', {class: 'card-head'}, h('h3', {}, 'By folder'), h('span', {class: 'sp'}), h('span', {class: 'small muted'}, `${c.folders} folders`)), h('div', {class: 'bars'}, folders.map(([k, n]) => bar2(k, n, folders[0][1], `#/migrate-bi/${p.id}/convert`))))),
    h('div', {class: 'card', style: 'margin:0'}, h('div', {class: 'card-head'}, h('h3', {}, `All objects in ${p.source_label} terms`)),
      h('div', {class: 'row'}, types.map(([t, n]) => mbPill(`${t}: ${fmtN(n, 0)}`, 'info')), mbPill(`Data modules: ${fmtN(c.datasets['data module'], 0)}`, 'mute'), mbPill(`Packages: ${fmtN(c.datasets.package, 0)}`, 'mute')),
      h('p', {class: 'small muted', style: 'margin:10px 0 0'}, `Usage: ${fmtN(c.runs, 0)} runs, ${c.usage_from || '?'} to ${c.usage_to || '?'} (${fmtN(c.usage_days, 0)} days). ` +
        (c.missing_dataset ? `${c.missing_dataset} reports point to packages that no longer exist - they need a decision. ` : '') + (c.failed_30 ? `${c.failed_30} failed in the last 30 days.` : '')),
      p.estate && p.estate.n_problems ? h('details', {class: 'astable'}, h('summary', {}, `${p.estate.n_problems} reading problem(s)`), h('ul', {class: 'small', style: 'margin:6px 0 0;padding-left:18px'}, p.estate.problems.map(x => h('li', {}, x)))) : null),
    inv);
}
async function mbInventory(p, box, extra) {
  const F = {...MB.inv, ...(extra || {})};
  const qs = new URLSearchParams({decision: F.decision, type: F.type, used: F.used, convert: F.convert, q: F.q, page: F.page}).toString();
  let d;
  try { d = await api(`/api/migrate-bi/${p.id}/inventory?${qs}`); } catch (e) { mbSet(box, h('div', {class: 'note err'}, e.message)); return; }
  const sel = (label, key, opts) => h('select', {class: 'sel', style: 'width:auto', 'aria-label': label, onchange: e => { MB.inv[key] = e.target.value; MB.inv.page = 0; mbInventory(p, box, extra); }}, opts.map(([v, l]) => h('option', {value: v, selected: F[key] === v}, l)));
  const search = h('input', {type: 'text', class: 'grow', style: 'flex:1;min-width:200px;width:auto', placeholder: 'Search objects...', value: F.q, 'aria-label': 'Search objects', oninput: e => { MB.inv.q = e.target.value; MB.inv.page = 0; clearTimeout(MB.invTimer); MB.invTimer = setTimeout(() => mbInventory(p, box, extra), 250); }});
  const conv = x => x.convert ? h('span', {style: `font-weight:600;color:var(${x.convert === 'auto' ? '--ok' : x.convert === 'review' ? '--warn' : '--err'})`, title: x.reason}, x.convert === 'no' ? 'not yet' : x.convert === 'review' ? 'needs a look' : 'automatic') : '-';
  mbSet(box, h('div', {class: 'card', style: 'margin:0'},
    h('div', {class: 'row', style: 'margin-bottom:10px'}, search, sel('Decision', 'decision', [['all', 'Decision: all'], ['keep', 'Keep'], ['review', 'Needs a decision'], ['merge', 'Merge'], ['retire', 'Retire']]),
      sel('Type', 'type', [['all', 'Type: all'], ...(d.types || []).map(t => [t, t + 's'])]), sel('Used', 'used', [['any', 'Used: any'], ['90', 'Used in 90 days'], ['never', 'Never run']]),
      sel('Converts', 'convert', [['all', 'Converts: all'], ['auto', 'automatic'], ['review', 'needs a look'], ['no', 'not yet']])),
    h('div', {style: 'overflow:auto'}, h('table', {class: 'utable'}, h('tr', {}, ['Name', 'Type', 'Folder', 'Runs', 'Last used', 'Complexity', 'Converts', 'Decision'].map((t, i) => h('th', {class: i === 3 ? '' : 'l'}, t))),
      d.rows.length ? d.rows.map(x => h('tr', {class: 'mb-row', onclick: () => mbObject(p, x.id)}, h('td', {}, h('a', {href: '#', onclick: e => { e.preventDefault(); mbObject(p, x.id); }}, x.name)), h('td', {}, x.type), h('td', {}, x.folder), h('td', {class: 'n'}, fmtN(x.runs_365, 0)),
        h('td', {}, x.last_used), h('td', {}, x.complexity), h('td', {}, conv(x)), h('td', {}, x.decision ? h('span', {title: x.decision_reason}, mbPill(MB_DEC[x.decision][0], MB_DEC[x.decision][1])) : '-')))
        : h('tr', {}, h('td', {colspan: 8, class: 'muted', style: 'padding:18px'}, 'Nothing matches this filter.')))),
    h('div', {class: 'row', style: 'margin-top:10px'}, h('span', {class: 'small muted'}, `${fmtN(d.total, 0)} objects`), h('span', {class: 'spacer'}),
      h('button', {class: 'btn sm', disabled: d.page === 0, onclick: () => { MB.inv.page = d.page - 1; mbInventory(p, box, extra); }}, 'Previous'), h('span', {class: 'small'}, `Page ${d.page + 1} of ${d.pages}`),
      h('button', {class: 'btn sm', disabled: d.page >= d.pages - 1, onclick: () => { MB.inv.page = d.page + 1; mbInventory(p, box, extra); }}, 'Next'))));
}
async function mbObject(p, rid) {
  let o;
  try { o = await api(`/api/migrate-bi/${p.id}/objects/${rid}`); } catch (e) { notify(e.message, 'err'); return; }
  const r = o.report, pr = o.prediction || {}, dc = o.decision;
  const kv = pairs => h('dl', {class: 'kv'}, pairs.flatMap(([k, v]) => [h('dt', {}, k), h('dd', {}, v)]));
  mbDrawer(r.name, `${r.type} - ${r.folder}`, [
    kv([['Decision', dc ? `${MB_DEC[dc.decision][0]} - ${dc.reason}` : 'not decided yet'], ['Runs (365 days)', fmtN(r.usage.runs_365, 0)], ['Last run', r.usage.last_run_days == null ? 'never' : `${r.usage.last_run_days} days ago`],
      ['Complexity', `${r.complexity} - ${r.calculations} calculations - ${o.pages.length} page(s) - ${o.pages.reduce((n, pg) => n + pg.visuals.length, 0)} visuals`],
      ['Converts', pr.convert ? `${pr.convert === 'auto' ? 'automatic' : pr.convert === 'review' ? 'needs a look' : 'not yet'} (${pr.confidence}) - ${pr.reason}` : '-'],
      ['Uses', o.dataset ? `${o.dataset.name} (${o.dataset.kind}${o.dataset.has_data ? ', data available' : ', no data files'})` : r.missing_dataset ? `missing package: ${r.missing_dataset}` : '-'], ['Owner', r.owner || '-'],
      ...(r.features && r.features.length ? [['Features', r.features.join(', ')]] : [])]),
    pr.gaps && pr.gaps.length ? [h('h4', {}, 'Calculations without a rule'), h('ul', {class: 'small', style: 'padding-left:18px'}, pr.gaps.map(g => h('li', {}, h('code', {class: 'mono'}, g.expression), ` - ${g.reason}`)))] : null,
    h('h4', {}, 'Queries'), h('div', {style: 'overflow:auto'}, h('table', {class: 'utable'}, h('tr', {}, ['Query', 'Item', 'Expression', 'Kind'].map(t => h('th', {class: 'l'}, t))),
      o.queries.flatMap(q => q.items.map(it => h('tr', {}, h('td', {}, q.name), h('td', {}, it.name), h('td', {}, h('code', {class: 'mono'}, it.expression)), h('td', {}, it.kind)))).slice(0, 40))),
    o.queries.some(q => q.filters.length) ? [h('h4', {}, 'Filters'), h('ul', {class: 'small', style: 'padding-left:18px'}, o.queries.flatMap(q => q.filters.map(f => h('li', {}, h('code', {class: 'mono'}, f.expression)))))] : null,
    h('h4', {}, 'Pages and visuals'), h('ul', {class: 'small', style: 'padding-left:18px'}, o.pages.map(pg => h('li', {}, h('b', {}, pg.name), ': ', pg.visuals.map(v => `${v.kind}${v.title ? ' "' + v.title + '"' : ''}`).join(', ') || 'no visuals'))),
    o.conversion ? h('div', {class: 'row', style: 'margin-top:12px'}, h('a', {class: 'btn', href: `#/migrate-bi/${p.id}/prove?report=${rid}`}, 'Conversion and proof')) : null,
    p.can_edit && p.decisions ? h('div', {class: 'row', style: 'margin-top:12px;gap:6px'}, h('span', {class: 'small muted'}, 'Your call:'), ['keep', 'retire', 'review'].map(d => h('button', {class: 'btn sm', onclick: () => mbOverride(p, rid, d, r.name)}, MB_DEC[d][0]))) : null]);
}
async function mbOverride(p, rid, decision, name) {
  const ta = h('textarea', {rows: 3, placeholder: 'Why (optional)'});
  const okb = h('button', {class: 'btn primary', onclick: async () => { try { const r = await api(`/api/migrate-bi/${p.id}/decide/override`, {json: {report: rid, decision, note: ta.value}}); mm.remove(); notify(`"${r.name}" ${MB_DEC[decision][0]} - recorded with your name (${r.override.by})`, 'ok'); if (MB.step === 'decide') { MB.p = await api(`/api/migrate-bi/${p.id}`); mbDraw(); } } catch (e) { notify(e.message, 'err'); } }}, 'Record my decision');
  const mm = modal(`${MB_DEC[decision][0]}: ${name}`, h('div', {class: 'mbody'}, h('p', {class: 'small muted'}, 'Your decision wins over the rules and is recorded with your name in the hand-over pack.'), h('label', {class: 'f'}, 'Note'), ta, h('div', {class: 'row', style: 'justify-content:flex-end;margin-top:12px'}, okb)));
}
function mbDrawer(title, sub, body) {
  return modal(title, h('div', {class: 'mbody'}, sub ? h('div', {class: 'small muted', style: 'margin-bottom:10px'}, sub) : null, body), true);
}
/* ---------- 2 Decide ---------- */
function mbDecide(p) {
  if (!p.counts) return h('div', {class: 'card empty'}, h('h3', {}, 'Nothing to decide yet'), h('p', {}, 'Discover the estate first.'), h('a', {class: 'btn primary', href: `#/migrate-bi/${p.id}/discover/connect`}, 'Discover'));
  const wrap = h('div', {class: 'stack'}, skel('cards'));
  (async () => {
    let d;
    try { d = await api(`/api/migrate-bi/${p.id}/decide`); } catch (e) { mbSet(wrap, h('div', {class: 'note err'}, e.message)); return; }
    if (!MB.rules || MB.rulesFor !== p.id) { MB.rules = {...d.rules}; MB.rulesFor = p.id; }
    const R = MB.rules, DEF = d.defaults, edit = p.can_edit, applied = d.applied;
    const tiles = h('div', {class: 'mb-g4'}), after = h('div'), list = h('div'), defs = {};
    let cur = d;
    const numIn = (k, label) => h('input', {type: 'number', value: R[k], 'aria-label': label, disabled: !edit, min: 0, oninput: e => { R[k] = Number(e.target.value) || 0; recompute(); }});
    const defTxt = k => { const el = h('span', {class: 'mb-def', 'data-def': k}); defs[k] = el; return el; };
    const syncDefs = () => Object.entries(defs).forEach(([k, el]) => { const ch = String(R[k]) !== String(DEF[k]); el.className = 'mb-def' + (ch ? ' changed' : ''); el.textContent = ch ? `changed - default ${DEF[k]}` : `default ${DEF[k]}`; });
    const drawTiles = () => {
      const c = cur.counts;
      mbSet(tiles, ...[['keep', 'used and ready to convert'], ['merge', `near-duplicates, into ${cur.kept_groups} kept`], ['retire', 'not used, per your rules'], ['review', 'a person decides']].map(([k, sub]) => {
        const diff = c[k] - d.counts[k];
        return h('div', {class: 'card kpi mb-tile' + (MB.pick === k ? ' on' : ''), role: 'button', tabindex: '0', 'aria-pressed': String(MB.pick === k), onclick: () => { MB.pick = k; drawTiles(); drawList(); }, onkeydown: e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); MB.pick = k; drawTiles(); drawList(); } }},
          mbPill(MB_DEC[k][0], MB_DEC[k][1]), h('div', {class: 'kv'}, fmtN(c[k], 0)), h('div', {class: 'ks'}, sub, diff && cur !== d ? h('span', {style: 'margin-left:6px;color:var(--warn);font-weight:600'}, `${diff > 0 ? '+' : ''}${diff} vs saved`) : null));
      }));
      mbSet(after, h('div', {class: 'row'}, h('span', {}, 'Reports to look after: ', h('b', {}, fmtN(cur.before, 0)), ' today ', h('b', {}, fmtN(cur.after, 0)), ' after'), h('span', {style: 'color:var(--ok);font-weight:600'}, `-${cur.reduction_pct} %`),
        h('span', {class: 'spacer'}), h('span', {class: 'small muted'}, applied ? `Signed by ${applied.by} ${ago(applied.at)}` + (Object.keys(cur.changed).length ? ' - unsaved changes above' : '') : 'Updates as you type - nothing is saved until you apply.')));
    };
    const drawList = () => {
      const rows = cur.top[MB.pick] || [];
      mbSet(list, h('div', {class: 'card', style: 'margin:0'}, h('div', {class: 'card-head'}, h('h3', {}, `${MB_DEC[MB.pick][0]}: ${fmtN(cur.counts[MB.pick], 0)} `, h('small', {class: 'muted'}, 'most used first, with the reason')), h('span', {class: 'sp'}),
          h('a', {class: 'btn sm', href: `#/migrate-bi/${p.id}/discover/found`, onclick: () => { MB.inv.decision = MB.pick; }}, 'See all')),
        h('div', {style: 'overflow:auto'}, h('table', {class: 'utable'}, h('tr', {}, ['Name', 'Folder', 'Runs', 'Why', edit ? 'Your call' : ''].map((t, i) => h('th', {class: i === 2 ? '' : 'l'}, t))),
          rows.length ? rows.map(x => h('tr', {class: 'mb-row', onclick: e => { if (!e.target.closest('button')) mbObject(p, x.id); }}, h('td', {}, x.name), h('td', {}, x.folder), h('td', {class: 'n'}, fmtN(x.runs, 0)), h('td', {}, h('span', {class: 'small muted'}, x.reason)),
            h('td', {}, edit ? h('div', {class: 'row', style: 'gap:4px'}, (MB.pick === 'review' ? ['keep', 'retire'] : MB.pick === 'keep' ? ['retire', 'review'] : ['keep']).map(dd => h('button', {class: 'btn sm', onclick: e => { e.stopPropagation(); mbOverride(p, x.id, dd, x.name); }}, MB_DEC[dd][0]))) : '')))
            : h('tr', {}, h('td', {colspan: 5, class: 'muted', style: 'padding:14px'}, 'None under these rules.'))))));
    };
    const recompute = () => { syncDefs(); clearTimeout(MB.prevTimer); MB.prevTimer = setTimeout(async () => { try { cur = await api(`/api/migrate-bi/${p.id}/decide/preview`, {json: {rules: R}}); drawTiles(); drawList(); } catch (e) { notify(e.message, 'err'); } }, 220); };
    const selIn = (k, opts, label) => h('select', {class: 'sel', style: 'width:auto', 'aria-label': label, disabled: !edit, onchange: e => { R[k] = e.target.value; recompute(); }}, opts.map(o => h('option', {value: o, selected: R[k] === o}, o)));
    const sumW = () => R.w_dataset + R.w_attr + R.w_metric + R.w_filter;
    const wSum = h('span', {class: 'mb-def'});
    const upd = () => { wSum.textContent = sumW() === 100 ? 'adds up to 100 ✓' : `adds up to ${sumW()} - should be 100`; };
    upd();
    const apply = async ask => {
      if (!ask && !await confirmBox('Apply my rules?', `${fmtN(cur.counts.keep, 0)} to keep, ${fmtN(cur.counts.merge, 0)} to merge, ${fmtN(cur.counts.retire, 0)} to retire, ${fmtN(cur.counts.review, 0)} need a decision. The decisions are saved and signed with your name; retired and merged objects are never converted (they stay on record with their reason).`, 'Apply and sign', false)) return;
      try { await api(`/api/migrate-bi/${p.id}/decide/apply`, {json: {rules: R, ask_queue: ask}}); notify(ask ? 'Added to the Validation queue - the decisions are applied when it is accepted' : `Decisions signed - ${fmtN(cur.counts.keep, 0)} objects to keep`, 'ok'); MB.p = await api(`/api/migrate-bi/${p.id}`); if (!ask) location.hash = `#/migrate-bi/${p.id}/convert`; else mbDraw(); }
      catch (e) { notify(e.message, 'err'); }
    };
    mbSet(wrap, 
      h('div', {class: 'row'}, h('h3', {style: 'margin:0;font-size:17px'}, `Decide what to keep: ${fmtN(p.counts.objects, 0)} objects`), p.sample ? mbTag('SAMPLE') : null, h('span', {class: 'spacer'}),
        edit ? h('button', {class: 'btn', onclick: () => { Object.assign(R, DEF); MB.rules = {...DEF}; mbDraw(); }}, 'Reset to defaults') : null,
        edit ? h('button', {class: 'btn', onclick: () => apply(true)}, 'Ask the queue') : null,
        edit ? h('button', {class: 'btn primary', onclick: () => apply(false)}, applied ? 'Apply again' : 'Apply my rules') : h('span', {class: 'small muted'}, 'Read-only: a BI Dev or an admin applies the rules.')),
      applied ? h('div', {class: 'banner ok'}, h('div', {class: 'ic'}, icon('check')), h('div', {class: 'txt'}, h('div', {class: 't'}, `Decisions signed by ${applied.by} ${ago(applied.at)}.`), h('div', {class: 'd'}, `${fmtN(d.counts.keep, 0)} keep - ${fmtN(d.counts.merge, 0)} merge - ${fmtN(d.counts.retire, 0)} retire - ${fmtN(d.counts.review, 0)} need a decision - ${Object.keys(d.overrides).length} personal calls`)), h('a', {class: 'btn', href: `#/migrate-bi/${p.id}/convert`}, 'Plan a wave'))
        : d.checkpoint && !applied ? h('div', {class: 'banner you'}, h('div', {class: 'ic'}, icon('user')), h('div', {class: 'txt'}, h('div', {class: 't'}, 'Waiting in the Validation queue.'), h('div', {class: 'd'}, 'The decisions apply when the checkpoint is accepted.')), h('a', {class: 'btn', href: '#/validate'}, 'Open the queue')) : null,
      h('div', {class: 'card', style: 'margin:0'}, h('div', {class: 'card-head', style: 'margin-bottom:0'}, h('h3', {}, 'Your rules ', h('small', {class: 'muted'}, 'the system default is shown next to each value'))),
        h('div', {class: 'mb-rule'}, h('div', {class: 'rl'}, mbPill('Retire', 'mute')), h('div', {class: 'rlines'},
          h('div', {class: 'mb-rline'}, 'not run for', numIn('retire_days', 'Retire when not run for days'), 'days', defTxt('retire_days')),
          h('div', {class: 'mb-rline'}, 'never run and older than', numIn('never_age', 'Never run and older than days'), 'days', defTxt('never_age')),
          h('div', {class: 'mb-rline'}, 'personal folders', selIn('personal', ['retire unless shared', 'treat like team content'], 'Personal folders')),
          h('div', {class: 'mb-rline'}, 'never retire when owned by', h('input', {type: 'text', placeholder: 'e.g. Finance, Audit', value: R.protect, disabled: !edit, 'aria-label': 'Never retire when owned by', oninput: e => { R.protect = e.target.value; recompute(); }})))),
        h('div', {class: 'mb-rule'}, h('div', {class: 'rl'}, mbPill('Merge', 'info')), h('div', {class: 'rlines'},
          h('div', {class: 'mb-rline'}, 'at least', numIn('sim_pct', 'Similarity percent'), '% the same', defTxt('sim_pct')),
          h('div', {class: 'mb-rline'}, 'weights: dataset', numIn('w_dataset', 'Dataset weight'), 'attributes', numIn('w_attr', 'Attributes weight'), 'metrics', numIn('w_metric', 'Metrics weight'), 'filters', numIn('w_filter', 'Filters weight'), wSum),
          h('div', {class: 'mb-rline'}, 'keep the', selIn('keep', ['most used', 'most recent'], 'Keep the')), h('div', {class: 'small muted'}, 'Near-duplicates are looked for among objects of the same package or data module.'))),
        h('div', {class: 'mb-rule'}, h('div', {class: 'rl'}, mbPill('Needs a decision', 'you')), h('div', {class: 'rlines'},
          h('div', {class: 'mb-rline'}, 'failed in the last', numIn('review_days', 'Failed in the last days'), 'days, or used but not convertible, or its package is missing', defTxt('review_days'))))),
      tiles, h('div', {class: 'card', style: 'padding:12px 18px;margin:0'}, after), list);
    wrap.querySelectorAll('input[type=number]').forEach(i => i.addEventListener('input', upd));
    syncDefs(); drawTiles(); drawList();
    if (Object.keys(cur.changed || {}).length === 0 && JSON.stringify(R) !== JSON.stringify(d.rules)) recompute();
  })();
  return wrap;
}
/* ---------- 3 Convert: select & plan, then the waves ---------- */
function mbConvert(p) {
  if (!p.decisions || !p.decisions.applied) return h('div', {class: 'card empty'}, h('h3', {}, 'Decide first'), h('p', {}, 'Sign the decisions, then pick a wave to convert.'), h('a', {class: 'btn primary', href: `#/migrate-bi/${p.id}/decide`}, 'Decide what to keep'));
  if (!p.waves.length || MB.sub === 'plan') return mbPlan(p);
  return mbWaves(p);
}
function mbPlan(p) {
  const box = h('div', {class: 'stack'});
  const F = MB.filter, PER = 25, side = h('div', {class: 'card stack', style: 'position:sticky;top:70px;margin:0'});
  const name = h('input', {type: 'text', value: MB.waveName || `Wave ${p.waves.length + 1}`, 'aria-label': 'Wave', oninput: e => { MB.waveName = e.target.value; }});
  let est = null;
  const drawSide = () => {
    const n = MB.sel.size;
    mbSet(side, h('div', {}, h('div', {class: 'small muted'}, 'Selected'), h('div', {style: 'font-size:28px;font-weight:650'}, fmtN(n, 0))),
      est ? h('div', {class: 'small muted'}, 'brings in ', h('b', {}, est.datasets.length), ` package${est.datasets.length === 1 ? '' : 's'} and data module${est.datasets.length === 1 ? '' : 's'}: ${est.datasets.map(x => x.name).join(', ') || '-'}`) : null,
      h('div', {}, h('label', {class: 'f', style: 'margin-top:0'}, 'Target'), h('div', {class: 'small'}, `${p.target_label}${p.target_version ? ' - ' + p.target_version : ''}`)),
      h('div', {}, h('label', {class: 'f', style: 'margin-top:6px'}, 'Wave'), name),
      n && est ? h('dl', {class: 'kv', style: 'grid-template-columns:110px 1fr;margin-top:8px'}, ...[['Estimated time', mbMins(est.minutes)], ['AI calls', est.ai_calls ? `≈ ${est.ai_calls} (formulas without a rule)` : 'none - rules cover all'],
        ['AI cost', `≈ ${usd(est.ai_cost_usd)} of ${usd(est.budget_usd)} budget` + (est.over_budget ? ' - over budget' : '')], ['Proof', 'every visual computed on both sides']].flatMap(([k, v]) => [h('dt', {}, k), h('dd', {style: est.over_budget && k === 'AI cost' ? 'color:var(--err)' : ''}, v)]))
        : h('div', {class: 'note', style: 'margin:0'}, 'Pick objects on the left; time, AI cost and what comes along appear here before anything runs.'),
      est && est.not_convertible.length ? h('div', {class: 'note warn', style: 'margin:0'}, `${est.not_convertible.length} of these are not convertible yet: ${est.not_convertible.slice(0, 3).map(x => x.name).join(', ')} - they convert as far as the rules go and the rest waits for a person.`) : null,
      p.can_edit ? h('button', {class: 'btn primary', disabled: !n || (est && est.over_budget), onclick: async () => {
        try { MB.p = await api(`/api/migrate-bi/${p.id}/waves`, {json: {name: name.value, reports: [...MB.sel]}}); MB.sel = new Set(); MB.sub = null; notify('Wave queued - the reports convert one at a time', 'ok'); location.hash = `#/migrate-bi/${p.id}/convert`; renderMigrateBI(); } catch (e) { notify(e.message, 'err'); }
      }}, `Convert ${fmtN(n, 0)} selected`) : h('div', {class: 'small muted'}, 'Read-only: a BI Dev or an admin starts a wave.'),
      h('div', {class: 'hint'}, 'Retired and merged objects stay on record with their reason - never converted, never deleted.'));
  };
  const estimate = () => { clearTimeout(MB.estTimer); MB.estTimer = setTimeout(async () => { if (!MB.sel.size) { est = null; drawSide(); return; } try { est = await api(`/api/migrate-bi/${p.id}/waves/estimate`, {json: {reports: [...MB.sel]}}); } catch (e) { est = null; } drawSide(); }, 200); };
  const table = h('div', {}, skel('rows'));
  const draw = async () => {
    const qs = new URLSearchParams({decision: F.dec, type: F.type, used: F.used, convert: F.convert, q: F.q, page: MB.page}).toString();
    let d;
    try { d = await api(`/api/migrate-bi/${p.id}/inventory?${qs}`); } catch (e) { mbSet(table, h('div', {class: 'note err'}, e.message)); return; }
    const sel = (label, key, opts) => h('select', {class: 'sel', style: 'width:auto', 'aria-label': label, onchange: e => { F[key] = e.target.value; MB.page = 0; draw(); }}, opts.map(([v, l]) => h('option', {value: v, selected: F[key] === v}, l)));
    const selectable = x => ['keep', 'review'].includes(x.decision);
    const conv = x => h('span', {style: `font-weight:600;color:var(${x.convert === 'auto' ? '--ok' : x.convert === 'review' ? '--warn' : '--err'})`, title: x.reason}, x.convert === 'no' ? 'not yet' : x.convert === 'review' ? 'needs a look' : 'automatic');
    mbSet(table, 
      h('div', {class: 'row', style: 'margin-bottom:10px'},
        h('input', {type: 'text', style: 'flex:1;min-width:180px;width:auto', placeholder: 'Search objects...', value: F.q, 'aria-label': 'Search objects', oninput: e => { F.q = e.target.value; MB.page = 0; clearTimeout(MB.invTimer); MB.invTimer = setTimeout(draw, 250); }}),
        sel('Decision', 'dec', [['all', 'Decision: all'], ['keep', 'Decision: Keep'], ['review', 'Decision: Needs a decision'], ['merge', 'Decision: Merge'], ['retire', 'Decision: Retire']]),
        sel('Type', 'type', [['all', 'Type: all'], ...(d.types || []).map(t => [t, t + 's'])]), sel('Used', 'used', [['any', 'Used: any'], ['90', 'Used in 90 days'], ['never', 'Never run']]),
        sel('Converts', 'convert', [['all', 'Converts: all'], ['auto', 'automatic'], ['review', 'needs a look'], ['no', 'not yet']]),
        h('button', {class: 'btn', onclick: async () => { const all = await api(`/api/migrate-bi/${p.id}/inventory?${new URLSearchParams({decision: F.dec === 'all' ? 'keep' : F.dec, type: F.type, used: F.used, convert: F.convert, q: F.q, page: 0, per: 5000}).toString()}`); const rows = all.rows.filter(selectable); rows.forEach(x => MB.sel.add(x.id)); draw(); estimate(); }}, `Select all matching`),
        h('button', {class: 'btn ghost', onclick: () => { MB.sel = new Set(); draw(); estimate(); }}, 'Unselect all')),
      h('div', {style: 'overflow:auto'}, h('table', {class: 'utable'}, h('tr', {}, [h('span', {class: 'sr'}, 'Select'), 'Name', 'Type', 'Folder', 'Runs', 'Complexity', 'Converts', 'Decision'].map((t, i) => h('th', {class: i === 4 ? '' : 'l'}, t))),
        d.rows.length ? d.rows.map(x => h('tr', {class: 'mb-row' + (MB.sel.has(x.id) ? ' on' : ''), onclick: e => { if (!e.target.closest('input, a, button')) mbObject(p, x.id); }},
          h('td', {}, h('input', {type: 'checkbox', checked: MB.sel.has(x.id), disabled: !selectable(x), 'aria-label': 'Select ' + x.name, onclick: e => e.stopPropagation(), onchange: e => { e.target.checked ? MB.sel.add(x.id) : MB.sel.delete(x.id); e.target.closest('tr').classList.toggle('on', e.target.checked); drawSide(); estimate(); }})),
          h('td', {}, x.name), h('td', {}, x.type), h('td', {}, x.folder), h('td', {class: 'n'}, fmtN(x.runs_365, 0)), h('td', {}, x.complexity), h('td', {}, conv(x)), h('td', {}, h('span', {title: x.decision_reason}, mbPill(MB_DEC[x.decision][0], MB_DEC[x.decision][1])))))
          : h('tr', {}, h('td', {colspan: 8, class: 'muted', style: 'padding:18px'}, 'Nothing matches this filter.')))),
      h('div', {class: 'row', style: 'margin-top:10px'}, h('span', {class: 'small muted'}, `${fmtN(d.total, 0)} objects`), h('span', {class: 'spacer'}),
        h('button', {class: 'btn sm', disabled: d.page === 0, onclick: () => { MB.page = d.page - 1; draw(); }}, 'Previous'), h('span', {class: 'small'}, `Page ${d.page + 1} of ${d.pages}`), h('button', {class: 'btn sm', disabled: d.page >= d.pages - 1, onclick: () => { MB.page = d.page + 1; draw(); }}, 'Next')));
  };
  draw(); drawSide(); if (MB.sel.size) estimate();
  box.append(h('div', {class: 'row'}, h('h3', {style: 'margin:0;font-size:17px'}, 'Select & plan a wave'), p.waves.length ? h('a', {class: 'btn sm', href: `#/migrate-bi/${p.id}/convert`}, 'Back to the waves') : null),
    h('div', {class: 'mb-side'}, h('div', {class: 'card', style: 'margin:0'}, table), side));
  return box;
}
function mbWaves(p) {
  const reps = p.reports, done = reps.filter(x => !['queued', 'converting'].includes(x.status)), running = reps.find(x => x.status === 'converting'), proven = reps.filter(x => x.proven);
  const stageIdx = {understand: 0, build: 1, prove: 2, package: 3, done: 4};
  const past = i => reps.filter(x => x.stage === 'done' || (x.stage && stageIdx[x.stage] > i)).length;
  const groups = [['understand', 'Understand', 'read, describe, plan'], ['build', 'Build', 'rules first, AI where none fits'], ['prove', 'Prove', 'review gates, numbers vs source'], ['package', 'Package', 'package and proof pack']];
  const f = reps.find(x => x.report === MB.focus) || reps[0];
  const look = p.decisions.counts.keep + (p.decisions.kept_groups || 0) + p.decisions.counts.review;
  const detail = h('div', {class: 'card stack', style: 'margin:0'}, skel('cards'));
  if (f) mbReportCard(p, f, detail);
  return h('div', {class: 'stack'},
    h('div', {class: 'row'}, h('h3', {style: 'margin:0;font-size:17px'}, `Converting to ${p.target_label}`), p.sample ? mbTag('SAMPLE') : null, h('span', {class: 'spacer'}),
      h('span', {class: 'mb-live' + (done.length === reps.length ? ' idle' : '')}, `AI: ${p.ai.calls} call${p.ai.calls === 1 ? '' : 's'} - ${usd(p.ai.cost_usd)}${done.length === reps.length ? ' - finished' : ' - running'}`),
      p.can_edit ? h('a', {class: 'btn', href: `#/migrate-bi/${p.id}/convert/plan`}, 'Plan another wave') : null,
      h('a', {class: 'btn', href: `#/migrate-bi/${p.id}/prove`}, 'Prove')),
    h('div', {class: 'banner ok'}, h('div', {class: 'ic'}, icon('check')), h('div', {class: 'txt'}, h('div', {class: 't'}, 'Packages stay with the programme and can be downloaded any time.'), h('div', {class: 'd'}, `Nothing is changed on ${p.source_label}. The agent is asked only where no rule fits; the DAX checker on this PC checks every measure in Power BI's own engine when it is running.`))),
    h('div', {class: 'mb-groups'}, groups.map(([id, g, line], i) => {
      const n = past(i), now = running && running.stage === id;
      return h('button', {class: 'mb-stage' + (n === reps.length && reps.length ? ' done' : now ? ' current' : ''), onclick: () => mbDrawer(g, line, [
          h('table', {class: 'utable'}, h('tr', {}, ['Report', 'Status'].map(t => h('th', {class: 'l'}, t))), reps.map(r => h('tr', {}, h('td', {}, r.name), h('td', {}, (r.stage === 'done' || (r.stage && stageIdx[r.stage] > i)) ? mbPill('Done', 'ok') : r.stage === id ? mbPill('Working', 'run') : mbPill('Waiting', 'mute')))))])},
        h('div', {class: 'st'}, n === reps.length && reps.length ? icon('check') : null, g), h('div', {class: 'ss'}, line), h('div', {class: 'ss', style: 'margin-top:6px'}, `${n} of ${reps.length} done`));
    })),
    h('div', {class: 'mb-g3'},
      h('div', {class: 'card', style: 'margin:0'}, h('h3', {}, p.waves.map(w => w.name).join(' - ')), h('div', {class: 'progress' + (done.length === reps.length ? ' ok' : ''), style: 'margin:12px 0 8px'}, h('div', {style: `width:${mbPct(done.length, reps.length)}%`})),
        h('div', {class: 'small muted'}, `${proven.length} proven - ${reps.filter(x => x.status === 'queued').length} queued - ${running ? 1 : 0} converting - ${reps.filter(x => ['gates_failed', 'open_items', 'converted', 'error', 'sent_back'].includes(x.status)).length} waiting for you`)),
      h('div', {class: 'card kpi'}, h('div', {class: 'kl'}, 'Reports to look after'), h('div', {class: 'kv', style: 'font-size:22px;white-space:nowrap'}, fmtN(p.decisions.before, 0), h('span', {style: 'font-size:13px;color:var(--ink-2);font-weight:400'}, ' today '), fmtN(look, 0), h('span', {style: 'font-size:13px;color:var(--ink-2);font-weight:400'}, ' after')),
        h('div', {class: 'ks'}, `${fmtN(p.decisions.counts.keep, 0)} kept - ${fmtN(p.decisions.counts.merge, 0)} merged into ${p.decisions.kept_groups} - ${fmtN(p.decisions.counts.retire, 0)} retired - ${fmtN(p.decisions.counts.review, 0)} need a decision`)),
      h('div', {class: 'card', style: 'margin:0'}, h('h3', {}, 'Where the proof comes from'), h('p', {class: 'small muted', style: 'margin:8px 0 0'}, `Definitions from the ${p.sample ? 'sample estate' : p.read_from === 'server' ? p.source_label + ' server' : 'exports'}. Every visual is computed on both sides and compared number by number; the review gates and Power BI's engine check the DAX.`))),
    h('div', {class: 'card', style: 'padding:0;overflow:auto;margin:0'}, h('table', {class: 'utable'}, h('tr', {}, ['Report', 'Wave', 'Stage', 'Status', 'Proof', 'AI'].map((t, i) => h('th', {class: i === 5 ? '' : 'l'}, t))),
      reps.map(r => h('tr', {class: 'mb-row' + (f && r.report === f.report ? ' on' : ''), onclick: () => { MB.focus = r.report; mbDraw(); }}, h('td', {}, h('a', {href: '#', onclick: e => { e.preventDefault(); MB.focus = r.report; mbDraw(); }}, r.name)), h('td', {}, String(r.wave)),
        h('td', {}, r.stage ? ({understand: 'Understand', build: 'Build', prove: 'Prove', package: 'Package', done: 'Done'}[r.stage] || r.stage) : '-'), h('td', {}, mbPill(r.status_label, MB_RSTAT[r.status] || 'mute')),
        h('td', {}, r.proof ? (r.proven ? mbProven(`${fmtN(r.proof.matched, 0)} numbers match`) : h('span', {style: 'color:var(--warn)'}, `${fmtN(r.proof.matched, 0)} of ${fmtN(r.proof.compared, 0)} match${r.proof.open && r.proof.open.length ? ` - ${r.proof.open.length} open` : ''}`)) : '-'),
        h('td', {class: 'n'}, r.ai_calls ? `${r.ai_calls} - ${usd(r.ai_cost)}` : '0'))))),
    f ? detail : null);
}
async function mbReportCard(p, r, box) {
  let d;
  try { d = await api(`/api/migrate-bi/${p.id}/reports/${r.report}`); } catch (e) { mbSet(box, h('div', {class: 'note err'}, e.message)); return; }
  const plan = d.plan || {}, pr = d.proof_detail || {}, s = plan.summary || {}, gates = (d.versions[0] || {}).gates || [], bad = gates.filter(g => g.status === 'fail');
  const tabs = {
    'Summary': () => [h('div', {class: 'row'}, d.proven ? mbProven('Proven') : mbPill(d.status_label, MB_RSTAT[d.status] || 'mute'), pr.compared != null ? h('span', {}, `${fmtN(pr.matched, 0)} of ${fmtN(pr.compared, 0)} numbers match the source`) : null,
        bad.length ? h('span', {style: 'color:var(--err)'}, `${bad.length} gate(s) fail: ${bad.map(g => g.name).join(', ')}`) : gates.length ? h('span', {class: 'muted'}, `- ${gates.filter(g => g.status === 'pass' || g.status === 'warn').length} review gates passed${gates.some(g => g.id === 'dax' && g.status === 'skip') ? ' (DAX gate skipped: checker off)' : ''}`) : null,
        h('span', {class: 'spacer'}), h('a', {class: 'btn', href: `#/migrate-bi/${p.id}/prove?report=${r.report}`}, 'Open the evidence - tests, gates, numbers')),
      h('div', {class: 'note'}, h('b', {}, `${plan.mode === 'ai_led' ? 'AI-led' : plan.mode === 'rules_only' ? 'Rules only' : 'Rules first'}: `), `${d.ai_calls} AI call(s) - ${s.measures || 0} calculations in ${p.source_label} terms; ${(s.measures || 0) - (plan.ai || 0)} converted by ${s.rules || 0} rule applications` + (plan.ai ? `, ${plan.ai} by the agent and checked by the gates` : ' - the agent was not needed') + (s.unsupported ? `; ${s.unsupported} visual(s) not converted (a person decides)` : '') + '.'),
      d.error ? h('div', {class: 'note err'}, d.error, p.can_edit ? h('div', {style: 'margin-top:8px'}, h('button', {class: 'btn sm', onclick: () => mbAgain(p, r)}, 'Convert again')) : null) : null,
      h('div', {class: 'row'}, h('span', {class: 'small muted'}, 'How it was converted:'), ['How it was read', 'Model', 'Decisions'].map(t => h('button', {class: 'btn sm', onclick: () => mbDrawer(t, r.name, h('pre', {class: 'mono', style: 'white-space:pre-wrap;font-size:12px'},
        t === 'How it was read' ? JSON.stringify({report: r.name, source: `${p.source} ${p.source_version}`, queries: (d.brief || {}).source_queries ? d.brief.source_queries.length : '?', visuals: (plan.visuals || []).length, gaps: (plan.gaps || []).length, filters: (plan.filters || []).length}, null, 2)
        : t === 'Decisions' ? (plan.decisions || []).map((x, i) => `${i + 1}  ${x}`).join('\n') : (plan.visuals || []).map(v => `${v.kind} "${v.title || v.id}" ${v.type ? v.type + (v.chart ? ' ' + v.chart : '') : 'not converted'} (${v.rule || '-'}, ${v.confidence}: ${v.reason})`).join('\n')))}, t)),
        h('button', {class: 'btn sm', onclick: () => mbLineage(p, r.report)}, 'Lineage'), d.files.pbip ? h('a', {class: 'btn sm', href: `/api/migrate-bi/${p.id}/reports/${r.report}/download`}, icon('download'), 'Package') : null,
        h('a', {class: 'btn sm', href: `#/p/${d.sub}`}, 'Open in the D2D dashboard builder'))],
    'What changed': () => [h('div', {style: 'overflow:auto'}, h('table', {class: 'utable'}, h('tr', {}, [`${p.source_label} item`, 'Expression', 'Power BI measure', 'Rules', 'Confidence'].map(t => h('th', {class: 'l'}, t))),
      (plan.measures || []).map(m => h('tr', {}, h('td', {}, m.item), h('td', {}, h('code', {class: 'mono', style: 'font-size:11.5px'}, ((d.brief || {}).source_queries || []).flatMap(q => q.items).find(it => it.name === m.item)?.expression || '')), h('td', {}, h('code', {class: 'mono', style: 'font-size:11.5px'}, m.dax || 'BLANK () - for the agent')), h('td', {}, (m.rules || []).join(', ') || (m.gaps && m.gaps.length ? 'agent' : '')), h('td', {}, mbPill(m.confidence, m.confidence === 'high' ? 'ok' : m.confidence === 'medium' ? 'you' : 'err'))))))],
    'AI use': () => [plan.gaps && plan.gaps.length ? h('table', {class: 'utable'}, h('tr', {}, ['Formula', 'Why the agent', 'Kind'].map(t => h('th', {class: 'l'}, t))), plan.gaps.map(g => h('tr', {}, h('td', {}, h('code', {class: 'mono', style: 'font-size:11.5px'}, g.expression)), h('td', {}, g.reason), h('td', {}, g.kind)))) : h('div', {class: 'note'}, 'No AI calls - every formula in this report has a tested rule.'),
      d.runs.length ? h('div', {class: 'small muted', style: 'margin-top:8px'}, d.runs.map(x => [x.stage + (modelName(x.model) ? `: ${modelName(x.model)}` : ''), dur(x.duration_ms || 0), usd(x.cost_usd)].join(' - ')).join(' - ')) : null],
    'Package': () => [d.output ? h('dl', {class: 'kv'}, ...[['File', d.output.pbip], ['Contents', `${d.output.pages} page(s) - ${d.output.measures} measures - ${d.output.visuals} visuals`], ['Proof', 'Review gates.txt, Numbers vs source.txt, Prototype.html'], ['DAX', d.output.dax && d.output.dax.checked ? 'checked in Power BI\'s engine' : `not checked (${(d.output.dax || {}).reason || 'checker off'})`]].flatMap(([k, v]) => [h('dt', {}, k), h('dd', {}, v)])) : h('div', {class: 'note'}, 'No package yet: every review gate must pass first.'),
      d.files.pbip ? h('a', {class: 'btn', href: `/api/migrate-bi/${p.id}/reports/${r.report}/download`}, icon('download'), 'Download package') : null],
    'Before go-live': () => [h('div', {class: 'mb-steps'}, ['Point the dataset at the client\'s gateway (DataFolder parameter or the warehouse connection)', `Map ${p.source_label} groups to Power BI roles (row-level security)`, 'Publish to the target workspace or report server folder', 'Ask the report owner to sign off with the numbers pack'].map(t => h('div', {}, t)))],
    'Log': () => { const el = h('div', {class: 'mb-feed'}, skel('rows')); api(`/api/migrate-bi/${p.id}/reports/${r.report}/activity`).then(a => mbSet(el, ...a.events.slice(-60).reverse().map(e => h('div', {class: 'fi ' + (e.level || '')}, h('span', {class: 'ft'}, clock(e.ts)), h('span', {class: 'fx'}, h('b', {style: 'font-weight:600;margin-right:6px;font-size:11px;letter-spacing:.04em;color:var(--ink-2)'}, (e.kind === 'app' ? (e.stage || 'app') : e.kind).toUpperCase()), e.text || e.detail || (e.tool ? `${e.tool}` : '')))))).catch(() => {}); return [el]; }};
  const tab = tabs[MB.tab] ? MB.tab : 'Summary';
  mbSet(box, h('div', {class: 'row'}, h('h3', {style: 'margin:0'}, r.name, ' ', h('small', {class: 'muted'}, `${d.stage ? (d.stage === 'done' ? 'done' : d.stage) : ''}${d.seconds ? ' - ' + dur(d.seconds * 1000) : ''}`)), h('span', {class: 'spacer'}),
    h('div', {class: 'segbtn', role: 'tablist'}, Object.keys(tabs).map(t => h('button', {role: 'tab', 'aria-selected': String(tab === t), class: tab === t ? 'on' : '', onclick: () => { MB.tab = t; mbReportCard(p, r, box); }}, t)))), ...tabs[tab]());
}
async function mbAgain(p, r) {
  const ta = h('textarea', {rows: 3, placeholder: 'What should change (optional) - the agent reads it'});
  const okb = h('button', {class: 'btn primary', onclick: async () => { try { await api(`/api/migrate-bi/${p.id}/reports/${r.report}/convert`, {json: {comment: ta.value}}); mm.remove(); notify('Queued to convert again - the earlier version is kept', 'ok'); MB.p = await api(`/api/migrate-bi/${p.id}`); mbDraw(); renderMigrateBI(); } catch (e) { notify(e.message, 'err'); } }}, 'Convert again');
  const mm = modal(`Convert again: ${r.name}`, h('div', {class: 'mbody'}, h('p', {class: 'small muted'}, 'Converts again with the latest rules (and anything learned since); the agent is asked only where no rule fits.'), h('label', {class: 'f'}, 'Comment'), ta, h('div', {class: 'row', style: 'justify-content:flex-end;margin-top:12px'}, okb)));
}
/* ---------- 4 Prove ---------- */
function mbProve(p) {
  const reps = p.reports;
  if (!reps.length) return h('div', {class: 'card empty'}, h('h3', {}, 'Nothing to prove yet'), h('p', {}, 'Convert a wave first.'), h('a', {class: 'btn primary', href: `#/migrate-bi/${p.id}/convert`}, 'Convert'));
  const want = (MB.query || {}).report;
  const f = reps.find(x => x.report === (want || MB.focus)) || reps[0];
  const proven = reps.filter(x => x.proven), accepted = reps.filter(x => x.status === 'accepted');
  const detail = h('div', {class: 'card stack', style: 'margin:0'}, skel('cards'));
  if (f) mbProofCard(p, f, detail);
  return h('div', {class: 'stack'},
    h('div', {class: 'row'}, h('h3', {style: 'margin:0;font-size:17px'}, 'Prove: numbers vs source'), p.sample ? mbTag('SAMPLE') : null, h('span', {class: 'spacer'}), proven.length === reps.length && reps.length ? mbProven(`${reps.length} of ${reps.length} proven`) : h('span', {class: 'small muted'}, `${proven.length} of ${reps.length} proven - ${accepted.length} accepted`),
      h('a', {class: 'btn', href: '#/validate'}, 'Validation queue')),
    h('div', {class: 'mb-g4'}, kpiTile('Reports', String(reps.length), `${reps.filter(x => ['queued', 'converting'].includes(x.status)).length} still converting`), kpiTile('Numbers compared', fmtN(reps.reduce((n, x) => n + ((x.proof || {}).compared || 0), 0), 0), 'every visual on both sides'),
      kpiTile('Differences', fmtN(reps.reduce((n, x) => n + ((x.proof || {}).differences || 0), 0), 0), 'to look at before accepting'), kpiTile('Accepted', String(accepted.length), 'proof signed by a person')),
    h('div', {class: 'card', style: 'padding:0;overflow:auto;margin:0'}, h('table', {class: 'utable'}, h('tr', {}, ['Report', 'Status', 'Numbers', 'Differences', 'Open', 'Gates', 'Accepted by'].map((t, i) => h('th', {class: i >= 2 && i <= 4 ? '' : 'l'}, t))),
      reps.map(r => { const pr = r.proof || {}, g = r.gates || [], bad = g.filter(x => x.status === 'fail');
        return h('tr', {class: 'mb-row' + (r.report === f.report ? ' on' : ''), onclick: () => { MB.focus = r.report; history.replaceState(null, '', `#/migrate-bi/${p.id}/prove?report=${r.report}`); mbDraw(); }}, h('td', {}, r.name), h('td', {}, r.proven ? mbProven('Proven') : mbPill(r.status_label, MB_RSTAT[r.status] || 'mute')),
          h('td', {class: 'n'}, pr.compared != null ? `${fmtN(pr.matched, 0)} / ${fmtN(pr.compared, 0)}` : '-'), h('td', {class: 'n'}, pr.differences != null ? fmtN(pr.differences, 0) : '-'), h('td', {class: 'n'}, pr.open ? pr.open.length : '-'),
          h('td', {}, g.length ? (bad.length ? h('span', {style: 'color:var(--err)'}, `${bad.length} fail`) : `${g.filter(x => x.status !== 'skip').length} passed${g.some(x => x.id === 'dax' && x.status === 'skip') ? ', DAX skipped' : ''}`) : '-'), h('td', {}, r.accepted_by || '-')); }))),
    detail);
}
async function mbProofCard(p, r, box) {
  let d;
  try { d = await api(`/api/migrate-bi/${p.id}/reports/${r.report}`); } catch (e) { mbSet(box, h('div', {class: 'note err'}, e.message)); return; }
  const pr = d.proof_detail || {}, gates = (d.versions[0] || {}).gates || [];
  const rows = (pr.visuals || []).flatMap(v => (v.differences || []).map(x => [v.title, x.key, x.measure, x.source, x.target, 'no']).concat(v.compared && !v.differences.length ? [[v.title, `${v.rows_target} rows`, 'all measures', `${v.compared} numbers`, 'the same', 'yes']] : v.skipped ? [[v.title, '-', '-', v.skipped, '', 'skipped']] : []));
  const accept = async () => {
    if (!await confirmBox('Accept the proof?', `${fmtN(pr.matched, 0)} of ${fmtN(pr.compared, 0)} numbers match the source${pr.differences ? `; ${pr.differences} differ` : ''}. Accepting signs the checkpoint with your name; what the agent wrote becomes a rule for the next reports.`, 'Accept the proof', false)) return;
    try { await api(`/api/migrate-bi/${p.id}/reports/${r.report}/accept`, {json: {}}); notify('Proof accepted - signed with your name', 'ok'); MB.p = await api(`/api/migrate-bi/${p.id}`); mbDraw(); } catch (e) { notify(e.message, 'err'); }
  };
  mbSet(box, h('div', {class: 'row'}, h('h3', {style: 'margin:0'}, r.name), d.proven ? mbProven('Proven') : mbPill(d.status_label, MB_RSTAT[d.status] || 'mute'), h('span', {class: 'spacer'}),
      p.can_edit && !['queued', 'converting', 'accepted'].includes(d.status) ? h('button', {class: 'btn primary', onclick: accept}, icon('check'), 'Accept the proof') : null,
      d.checkpoint_detail && d.checkpoint_detail.status === 'open' ? h('a', {class: 'btn', href: '#/validate'}, 'Send back from the queue') : null,
      p.can_edit && !['queued', 'converting'].includes(d.status) ? h('button', {class: 'btn', onclick: () => mbAgain(p, r)}, 'Convert again') : null),
    h('div', {class: 'mb-g3'}, kpiTile('Numbers', `${fmtN(pr.matched, 0)} / ${fmtN(pr.compared, 0)}`, pr.differences ? `${pr.differences} differ` : 'all the same'), kpiTile('Visuals', String((pr.visuals || []).length), `${(pr.visuals || []).filter(v => v.skipped).length} skipped`),
      kpiTile('Open calculations', String((pr.open || []).length), (pr.open || []).slice(0, 3).join(', ') || 'none - every measure written')),
    h('h4', {}, `Numbers: ${p.source_label} vs Power BI prototype`),
    h('div', {style: 'overflow:auto'}, h('table', {class: 'utable'}, h('tr', {}, ['Visual', 'Row', 'Measure', p.source_label, 'Power BI', 'Match'].map(t => h('th', {class: 'l'}, t))),
      rows.length ? rows.slice(0, 80).map(x => h('tr', {}, x.map((c, i) => h('td', {}, i === 5 ? (c === 'yes' ? h('span', {style: 'color:var(--ok);font-weight:700'}, '✓') : c === 'no' ? h('span', {style: 'color:var(--err);font-weight:700'}, '✗') : h('span', {class: 'muted'}, 'skipped')) : c)))) : h('tr', {}, h('td', {colspan: 6, class: 'muted', style: 'padding:14px'}, 'No comparison yet.')))),
    h('h4', {}, 'Review gates'), h('div', {class: 'row'}, gates.map(g => h('span', {class: 'pill plain ' + (g.status === 'pass' ? 'ok' : g.status === 'warn' ? 'you' : g.status === 'fail' ? 'err' : 'mute'), title: g.summary}, `${g.name}: ${g.status === 'skip' ? 'skipped' : g.status}`))),
    gates.some(g => g.id === 'dax' && g.status === 'skip') ? h('div', {class: 'small muted'}, 'The DAX gate is skipped because the DAX checker on this PC is not running - it counts as not checked, never as passed.') : null,
    d.checkpoint_detail ? h('div', {class: 'small muted'}, `Checkpoint ${d.checkpoint_detail.status}${d.checkpoint_detail.decided_by ? ' by ' + d.checkpoint_detail.decided_by : ''} - opened ${ago(d.checkpoint_detail.created)}`) : null);
}
/* ---------- 5 Hand over ---------- */
function mbHandover(p) {
  if (!p.waves.length) return h('div', {class: 'card empty'}, h('h3', {}, 'Nothing to hand over yet'), h('p', {}, 'Prove a wave first.'), h('a', {class: 'btn primary', href: `#/migrate-bi/${p.id}/convert`}, 'Convert'));
  const rows = {}; p.reports.forEach(r => { rows[r.report] = r; });
  return h('div', {class: 'stack'}, p.waves.map(w => {
    const rs = w.reports.map(i => rows[i]).filter(Boolean), ok = rs.filter(r => r.proven), hv = w.handover, ready = rs.length && rs.every(r => !['queued', 'converting'].includes(r.status));
    const build = async () => { try { MB.p = await api(`/api/migrate-bi/${p.id}/handover/${w.n}`, {json: {}}); notify('Hand-over pack built - waiting for the owner\'s sign-off', 'ok'); mbDraw(); } catch (e) { notify(e.message, 'err'); } };
    const assign = async () => {
      const dir = await api('/api/directory');
      const sel = h('select', {class: 'sel'}, dir.users.map(u => h('option', {value: u.id, selected: hv && hv.assignee === u.id}, `${u.name} - ${u.email}`)));
      const okb = h('button', {class: 'btn primary', onclick: async () => { try { MB.p = await api(`/api/migrate-bi/${p.id}/handover/${w.n}/assign`, {json: {to: sel.value}}); mm.remove(); notify('Sign-off assigned - they have been told', 'ok'); mbDraw(); } catch (e) { notify(e.message, 'err'); } }}, 'Ask to sign off');
      const mm = modal(`Owner sign-off: ${w.name}`, h('div', {class: 'mbody'}, h('label', {class: 'f'}, 'Who signs off'), sel, h('div', {class: 'small muted', style: 'margin-top:8px'}, 'The pack can be downloaded once they accept it in the Validation queue.'), h('div', {class: 'row', style: 'justify-content:flex-end;margin-top:12px'}, okb)));
    };
    return h('div', {class: 'mb-side'},
      h('div', {class: 'stack'},
        h('div', {class: 'card', style: 'margin:0'}, h('div', {class: 'card-head'}, h('h3', {}, `Hand-over pack - ${w.name}`), h('span', {class: 'sp'}), ok.length === rs.length && rs.length ? mbProven(`${ok.length} of ${rs.length} reports proven`) : h('span', {class: 'small muted'}, `${ok.length} of ${rs.length} reports proven`)),
          h('div', {class: 'stack', style: 'gap:8px'}, ['What we found and every decision, with the reason and who signed it', 'Each report: the Power BI package, the numbers compared with the source, the review gates passed', 'Lineage per report', 'Before go-live list: gateway, roles, workspace or report server folders', 'Rules learned in this wave, ready for the next'].map(t => h('div', {class: 'row'}, icon('check'), t))),
          hv ? h('div', {class: 'note', style: 'margin:12px 0 0'}, hv.accepted ? [h('b', {}, `Signed off by ${hv.accepted_by_name || hv.accepted_by} ${ago(hv.accepted)}. `), h('a', {href: `/api/migrate-bi/${p.id}/handover/${w.n}/pack.zip`}, 'Download the pack')] : hv.sent_back ? [h('b', {}, 'Sent back: '), hv.sent_back.comment] : [h('b', {}, 'Waiting for the owner\'s sign-off. '), 'Nothing is handed over before it; the download opens once the checkpoint is accepted. ', h('a', {href: '#/validate'}, 'Open the queue')]) : null),
        h('div', {class: 'card', style: 'padding:0;overflow:auto;margin:0'}, h('table', {class: 'utable'}, h('tr', {}, ['Report', 'Status', 'Proof', 'Accepted by'].map(t => h('th', {class: 'l'}, t))),
          rs.map(r => h('tr', {}, h('td', {}, r.name), h('td', {}, mbPill(r.status_label, MB_RSTAT[r.status] || 'mute')), h('td', {}, r.proven ? mbProven(`${fmtN((r.proof || {}).matched, 0)} numbers`) : mbPill('Waiting for proof', 'mute')), h('td', {}, r.accepted_by_name || r.accepted_by || '-')))))),
      h('div', {class: 'stack'},
        h('div', {class: 'card stack', style: 'margin:0'}, h('h3', {}, 'Send the pack'), h('div', {class: 'small muted'}, 'The pack (inventory, decisions, proof per report, packages) goes to the owner for sign-off; the download opens after it.'),
          p.can_edit ? h('button', {class: 'btn primary', disabled: !ready, onclick: build}, hv ? 'Build the pack again' : 'Build the hand-over pack') : null,
          p.can_edit && hv ? h('button', {class: 'btn', onclick: assign}, 'Ask the owner to sign off') : null,
          hv && hv.accepted ? h('a', {class: 'btn', href: `/api/migrate-bi/${p.id}/handover/${w.n}/pack.zip`}, icon('download'), 'Download the pack') : null,
          !ready ? h('div', {class: 'hint'}, 'Every report of the wave must finish converting first.') : null),
        h('div', {class: 'card', style: 'margin:0'}, h('h3', {}, 'Estimate vs actual'), h('dl', {class: 'kv'}, ...[['Estimated', `${mbMins(w.estimate.minutes)} - ${w.estimate.ai_calls} AI calls - ${usd(w.estimate.ai_cost_usd)}`], ['Actual', `${dur(rs.reduce((n, r) => n + (r.seconds || 0), 0) * 1000)} - ${rs.reduce((n, r) => n + r.ai_calls, 0)} AI calls - ${usd(rs.reduce((n, r) => n + r.ai_cost, 0))}`]].flatMap(([k, v]) => [h('dt', {}, k), h('dd', {}, v)])))));
  }));
}
/* ---------- 6 Run ---------- */
function mbRun(p) {
  const sch = p.schedules || [], rows = {}; p.reports.forEach(r => { rows[r.report] = r; });
  const live = p.waves.filter(w => w.status === 'handed').flatMap(w => w.reports).map(i => rows[i]).filter(Boolean);
  const drifted = sch.filter(s => s.last_result && s.last_result.includes('drifted')).length;
  return h('div', {class: 'stack'},
    h('div', {class: 'banner info'}, h('div', {class: 'ic'}, icon('info')), h('div', {class: 'txt'}, h('div', {class: 't'}, 'After go-live.'), h('div', {class: 'd'}, 'Migrated reports are watched like everything else: every night Relay re-runs each report\'s numbers against the source by itself and shows any drift here; "Run now" checks one at once.'))),
    h('div', {class: 'mb-g4'}, kpiTile('Live reports', String(live.length), 'handed over with sign-off'), kpiTile('Nightly checks', String(sch.filter(s => s.active).length), 'registered after sign-off'), kpiTile('Numbers drifted', String(drifted), 'in the last check'), kpiTile('Checks run', String(sch.reduce((n, s) => n + s.runs, 0)), 'so far')),
    sch.length ? h('div', {class: 'card', style: 'padding:0;overflow:auto;margin:0'}, h('table', {class: 'utable'}, h('tr', {}, ['Report', 'Check', 'Last run', 'Result', 'Next', ''].map(t => h('th', {class: 'l'}, t))),
      sch.map(s => h('tr', {}, h('td', {}, (rows[s.report] || {}).name || s.report), h('td', {}, `${s.kind} - ${s.cadence}`), h('td', {}, s.last_run ? ago(s.last_run) : 'never'), h('td', {}, s.last_result ? (s.last_result.includes('drifted') ? h('span', {style: 'color:var(--warn)'}, s.last_result) : mbProven(s.last_result)) : '-'), h('td', {}, s.next_run ? when(s.next_run) : '-'),
        h('td', {}, p.can_edit ? h('button', {class: 'btn sm', onclick: async () => { try { await api(`/api/migrate-bi/${p.id}/run/${s.id}/now`, {json: {}}); notify('Check queued', 'ok'); renderMigrateBI(); } catch (e) { notify(e.message, 'err'); } }}, 'Run now') : '')))))
      : h('div', {class: 'card empty'}, h('h3', {}, 'Nothing is live yet'), h('p', {}, 'Nightly checks are registered when a wave is signed off.')));
}
/* ---------- Agent log ---------- */
function mbLog(p) {
  const box = h('div', {class: 'card', style: 'padding:0;overflow:auto;margin:0'}, skel('rows'));
  const q = h('input', {type: 'text', style: 'flex:1;min-width:200px;width:auto', placeholder: 'Find an agent, report or message...', value: MB.logq, 'aria-label': 'Find in the agent log', oninput: e => { MB.logq = e.target.value; draw(); }});
  let events = [];
  const draw = () => {
    const qq = MB.logq.toLowerCase();
    const rows = events.filter(e => !qq || JSON.stringify(e).toLowerCase().includes(qq)).slice().reverse();
    mbSet(box, h('table', {class: 'utable'}, h('tr', {}, ['Time', 'Report', 'Stage', 'What happened', 'Who'].map(t => h('th', {class: 'l'}, t))),
      rows.length ? rows.slice(0, 400).map(e => h('tr', {}, h('td', {}, h('span', {class: 'mono'}, clock(e.ts))), h('td', {}, e.report_name || 'programme'), h('td', {}, e.stage || e.kind), h('td', {style: e.level === 'warn' ? 'color:var(--warn)' : e.level === 'error' ? 'color:var(--err)' : ''}, e.text || e.detail || (e.tool ? `${e.tool}` : e.kind) || ''), h('td', {}, e.who || ''))) : h('tr', {}, h('td', {colspan: 5, class: 'muted', style: 'padding:14px'}, 'Nothing logged yet.'))));
  };
  api(`/api/migrate-bi/${p.id}/log`).then(r => { events = r.events; draw(); }).catch(e => mbSet(box, h('div', {class: 'note err'}, e.message)));
  const runs = p.reports.reduce((n, r) => n + r.ai_calls, 0);
  return h('div', {class: 'stack'},
    h('div', {class: 'mb-g4'}, kpiTile('Agent runs', fmtN(runs, 0), 'AI calls, all logged'), kpiTile('AI cost', usd(p.ai.cost_usd), `of ${usd(p.ai.budget_usd)} budget`), kpiTile('Rate-limit waits', String(p.scan.waits || 0), 'server asked to slow down'), kpiTile('Needs attention', String(p.reports.filter(r => r.status === 'error').length), 'reports with an error')),
    h('div', {class: 'row'}, q, h('a', {class: 'btn', href: `#/migrate-bi/${p.id}/${p.current_step}`}, 'Back to the journey')), box);
}
/* ---------- Lineage drawer: source tables -> transformations -> target ---------- */
async function mbLineage(p, rid) {
  let g;
  try { g = await api(`/api/migrate-bi/${p.id}/lineage${rid ? '?report=' + rid : ''}`); } catch (e) { notify(e.message, 'err'); return; }
  if (!g.nodes.length) { mbDrawer('Lineage', p.name, h('div', {class: 'card empty'}, h('h3', {}, 'No lineage yet'), h('p', {}, 'Lineage is recorded when a report is converted: source tables -> transformations -> target model.'))); return; }
  const cols = {source: [], transform: [], target: []};
  g.nodes.forEach(n => (cols[n.kind] || cols.target).push(n));
  const W = 900, rowH = 22, H = Math.max(120, rowH * Math.max(cols.source.length, cols.transform.length, cols.target.length) + 40);
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`); svg.setAttribute('class', 'mb-lin'); svg.setAttribute('role', 'img'); svg.setAttribute('aria-label', 'Lineage: source tables, transformations, target model');
  const pos = {};
  const el = (t, a) => { const e = document.createElementNS('http://www.w3.org/2000/svg', t); Object.entries(a).forEach(([k, v]) => e.setAttribute(k, v)); return e; };
  [['source', 10, 'Source tables'], ['transform', 330, 'Transformations'], ['target', 650, 'Power BI model']].forEach(([k, x, label]) => {
    const t = el('text', {x, y: 16, 'font-weight': '700'}); t.textContent = label; svg.append(t);
    cols[k].forEach((n, i) => { const y = 30 + i * rowH; pos[n.id] = {x, y}; const gr = el('g', {class: k === 'source' ? 'src' : ''}); gr.append(el('rect', {x, y, width: 240, height: rowH - 4, rx: 4}));
      const tx = el('text', {x: x + 6, y: y + 13}); tx.textContent = n.label.length > 38 ? n.label.slice(0, 36) + '...' : n.label; gr.append(tx); svg.append(gr); });
  });
  g.edges.forEach(e => { const a = pos[e.from], b = pos[e.to]; if (!a || !b || a.x === b.x) return; const l = el('line', {x1: a.x + 240, y1: a.y + 9, x2: b.x, y2: b.y + 9}); const t = el('title'); t.textContent = `${e.from} ${e.to}${e.detail ? ': ' + e.detail : ''}`; l.append(t); svg.append(l); });
  mbDrawer('Lineage', rid ? (p.reports.find(r => r.report === rid) || {}).name : `${p.name} - every converted report`, [h('div', {class: 'small muted', style: 'margin-bottom:8px'}, `${cols.source.length} source tables ${cols.transform.length} transformations ${cols.target.length} target tables and measures. Hover a line for the expression.`), svg,
    h('details', {class: 'astable'}, h('summary', {}, 'Show as a table'), h('table', {class: 'utable'}, h('tr', {}, ['From', 'To', 'Kind', 'Detail'].map(t => h('th', {class: 'l'}, t))), g.edges.slice(0, 200).map(e => h('tr', {}, h('td', {}, e.from), h('td', {}, e.to), h('td', {}, e.kind), h('td', {}, h('code', {class: 'mono', style: 'font-size:11px'}, e.detail || ''))))))]);
}
