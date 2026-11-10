/* ---------------- Start from an idea or a plan (P10): the brief and its attachments go in, Relay reads them and shows what it
   understood in three views — process map, fields & rules, plan & modules — and a person confirms or corrects each one before
   anything is built. Routes #/start (new start + my starts) and #/start/<id>. ---------------- */
const START_KIND = {video: ['play', 'Video'], audio: ['bell', 'Audio'], image: ['image', 'Image'], pdf: ['file', 'PDF'], doc: ['file', 'Document'],
  sheet: ['table', 'Spreadsheet'], deck: ['layers', 'Slides'], text: ['file', 'Text'], link: ['external', 'Link']};
const START_ACCEPT = '.mp4,.webm,.mov,.mp3,.wav,.m4a,.png,.jpg,.jpeg,.webp,.pdf,.docx,.xlsx,.csv,.pptx,.txt,.md';
const START_VIEWS = [['process', 'Process map', 'the work step by step, from the recording, the procedure and the screenshots'],
  ['fields', 'Fields & rules', 'every field, value and rule found, with how sure Relay is'], ['plan', 'Plan & modules', 'what gets built, in order, and where you confirm']];
const START_STATUS = {queued: ['Queued', 'run'], reading: ['Relay is reading', 'run'], awaiting_confirmation: ['Your turn: confirm the views', 'you'],
  planned: ['Planned', 'ok'], error: ['Needs attention', 'err']};
const START_STEPS = [['Tell us', 'idea, plan and attachments'], ['Relay reads it', 'analysis in the right views'], ['You confirm', 'each view, or correct it'], ['Plan starts', 'with your checkpoints']];
const startPill = s => { const [t, c] = START_STATUS[s] || [s, '']; return h('span', {class: 'pill ' + c}, t); };
const startKind = n => { const e = (n.split('.').pop() || '').toLowerCase(); return {mp4: 'video', webm: 'video', mov: 'video', mp3: 'audio', wav: 'audio', m4a: 'audio', png: 'image', jpg: 'image', jpeg: 'image', webp: 'image', pdf: 'pdf', docx: 'doc', xlsx: 'sheet', csv: 'sheet', pptx: 'deck', txt: 'text', md: 'text'}[e] || 'text'; };
S.startTimer = null;

function renderStart() {
  clearTimeout(S.startTimer);
  const m = location.hash.match(/^#\/start\/([\w-]+)/);
  return m ? renderStartPage(m[1]) : renderStartForm();
}

function startJourney(cur) {
  return h('ol', {class: 'journey', 'aria-label': 'Start steps'}, START_STEPS.map(([l, sub], i) => h('li', {class: (i < cur ? 'done ' : '') + (i === cur ? 'on' : '')},
    h('span', {class: 'dot'}, i < cur ? '✓' : ''), h('div', {class: 'jl'}, `${i + 1} ${l}`), h('div', {class: 'js'}, sub))));
}

/* ---------- the form ---------- */
async function renderStartForm() {
  const main = $('#main');
  main.replaceChildren(skel('page'));
  let d;
  try { d = await api('/api/start'); } catch (e) { main.replaceChildren(h('div', {class: 'page'}, h('div', {class: 'note err'}, e.message))); return; }
  if (location.hash !== '#/start') return;
  const me = S.me || {}, viewer = !d.can_start;
  const brief = h('textarea', {rows: 5, placeholder: 'e.g. “Automate supplier invoice matching: AP clerks copy invoices from email into our finance system and check them against purchase orders in the warehouse. We want it automatic, with exceptions to a person, and a dashboard of what is stuck.”'});
  const name = h('input', {type: 'text', placeholder: 'optional — Relay names it from the brief'});
  const links = h('textarea', {rows: 2, placeholder: 'one per line — SharePoint, Confluence, Jira… (Relay notes them; access comes through Connections)'});
  const picked = [];
  const list = h('div', {class: 'stack', style: 'gap:8px'});
  const input = h('input', {type: 'file', multiple: true, accept: START_ACCEPT, style: 'display:none', 'aria-label': 'Attach files'});
  const show = () => list.replaceChildren(...picked.map((f, i) => h('div', {class: 'arow'},
    h('span', {class: 'aico'}, icon(START_KIND[startKind(f.name)][0])),
    h('div', {class: 'grow', style: 'min-width:0'}, h('div', {class: 'an'}, f.name), h('div', {class: 'small muted'}, `${START_KIND[startKind(f.name)][1]} · ${size(f.size)}`)),
    h('button', {class: 'iconbtn', type: 'button', 'aria-label': 'Remove ' + f.name, onclick: () => { picked.splice(i, 1); show(); }}, icon('x')))));
  const add = files => { for (const f of files) if (START_ACCEPT.includes('.' + (f.name.split('.').pop() || '').toLowerCase())) picked.push(f); else notify(`${f.name}: not a kind of file Relay reads`, 'err'); show(); };
  input.onchange = () => { add(input.files); input.value = ''; };
  const drop = h('div', {class: 'drop', role: 'button', tabindex: '0', 'aria-label': 'Add attachments', onclick: () => input.click(), onkeydown: e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); input.click(); } }},
    input, icon('download'), h('div', {}, h('b', {}, 'Drop files here, or click to add')),
    h('div', {class: 'hint'}, 'Video and screen recordings · images and screenshots · Word, PDF, slides · spreadsheets · audio and call recordings'));
  drop.ondragover = e => { e.preventDefault(); drop.classList.add('over'); }; drop.ondragleave = () => drop.classList.remove('over');
  drop.ondrop = e => { e.preventDefault(); drop.classList.remove('over'); add(e.dataTransfer.files); };
  const conns = new Set();
  const pickerEl = typeof connPicker === 'function' ? connPicker(conns, {suggest: []}) : h('div', {class: 'muted small'}, 'Connections are managed under Platform › Connections.');
  const del = h('input', {type: 'checkbox'});
  const bar = h('div', {class: 'bar'}, h('i'));
  const go = h('button', {class: 'btn primary', type: 'submit', disabled: viewer}, icon('play'), 'Let Relay read it');
  const form = h('form', {class: 'card', style: 'margin:0'},
    h('label', {class: 'f', style: 'margin-top:0'}, 'What do you want to do?'), brief,
    h('div', {style: 'margin-top:12px'}, drop), list,
    h('details', {class: 'more', style: 'margin-top:6px'}, h('summary', {}, 'Name and links'), h('label', {class: 'f'}, 'Name', h('small', {}, 'optional')), name, h('label', {class: 'f'}, 'Links'), links),
    h('div', {style: 'margin-top:14px'}, h('div', {class: 'small', style: 'font-weight:600'}, 'Connect systems too ', h('span', {class: 'muted', style: 'font-weight:400'}, '— the modules read live data, read-only, with these')), h('div', {style: 'margin-top:6px'}, pickerEl)),
    h('div', {class: 'row', style: 'margin-top:14px;gap:12px'},
      h('span', {class: 'small muted', style: 'display:inline-flex;gap:6px;align-items:center'}, icon('lock'), 'Attachments stay in your workspace'), h('label', {class: 'chk'}, del, 'Delete recordings after I confirm the process'),
      h('span', {class: 'spacer'}), go),
    viewer ? h('div', {class: 'hint'}, 'Starting work is for builders and leads; ask one to start it for you.') : h('div', {class: 'hint'}, 'Relay reads everything, shows what it understood in three views, and waits for your confirmation at every step. Nothing is built before you agree.'),
    bar);
  form.onsubmit = e => {
    e.preventDefault();
    if (brief.value.trim().length < 10) return toast(go, 'Describe what you want in a sentence or two.');
    const fd = new FormData();
    fd.append('brief', brief.value); fd.append('name', name.value); fd.append('links', links.value); fd.append('connections', JSON.stringify([...conns]));
    if (del.checked) fd.append('delete_recordings_after', '1');
    for (const f of picked) fd.append('files', f);
    bar.style.display = 'block'; go.disabled = true; go.lastChild.textContent = 'Uploading…';
    upload('/api/start', fd, p => { $('i', bar).style.width = (100 * p) + '%'; })
      .then(r => { location.hash = '#/start/' + r.id; })
      .catch(err => { go.disabled = false; go.lastChild.textContent = 'Let Relay read it'; bar.style.display = 'none'; toast(go, err.message); });
  };
  const mods = (S.registry ? S.registry.modules : []).filter(m => ['brd', 'processdocs', 'dwh', 'bi', 'rpa', 'apps', 'n8n', 'sdlc'].includes(m.id));
  main.replaceChildren(h('div', {class: 'page'},
    pageHead({crumbs: [['Home', '#/'], ['Start']], eyebrow: brandName() + ' · Start', title: 'Start from an idea or a plan',
      promise: 'Write it, say it or show it — attach videos, screenshots, documents, spreadsheets or links. Relay reads everything, shows you what it understood in the right view, and waits for your confirmation at every step.'}),
    startJourney(0),
    h('div', {class: 'g-side'},
      form,
      h('div', {class: 'stack'},
        h('div', {class: 'card', style: 'margin:0'}, h('h3', {}, 'Always a person in the loop'), h('div', {class: 'rules', style: 'margin-top:8px'},
          ['Relay shows what it understood before doing anything', 'You confirm in the view that fits — a process map, a field table, a plan', 'Corrections teach the agent; your confirmation is signed and logged', 'Nothing reaches a live system without a named approval'].map(t => h('div', {}, icon('check'), t)))),
        mods.length ? h('div', {class: 'card', style: 'margin:0'}, h('h3', {}, 'Or start from a module'), h('div', {class: 'row', style: 'gap:6px;margin-top:8px'}, mods.map(m => h('a', {class: 'chipx', href: m.state === 'available' ? m.route : '#/m/' + m.id}, m.short || m.name)))) : null,
        h('div', {class: 'card', style: 'margin:0'}, h('div', {class: 'card-head'}, h('h3', {}, 'Your starts'), h('span', {class: 'sp'}), h('span', {class: 'small muted'}, String(d.starts.length))),
          d.starts.length ? h('div', {class: 'stack', style: 'gap:6px'}, d.starts.slice(0, 12).map(s => h('a', {href: '#/start/' + s.id, class: 'wait'},
            h('div', {class: 'wt'}, h('b', {}, s.name), h('small', {}, `${s.attachments} attachment${s.attachments === 1 ? '' : 's'} · ${ago(s.updated || s.created)}`)), startPill(s.status))))
            : h('div', {class: 'muted small', style: 'padding:6px 0'}, 'Nothing started yet.'))))));
  document.title = `Start · ${S.brand ? S.brand.full : 'RELAY by PASDACS'}`;
}

/* ---------- the views ---------- */
function startProcessView(a) {
  const p = a.process, byId = Object.fromEntries(p.steps.map(s => [s.id, s]));
  return h('div', {class: 'stack'},
    h('ol', {class: 'pmap', 'aria-label': `Process map: ${p.counts.steps} steps`}, p.steps.map(s => h('li', {class: 'pstep ' + s.kind},
      h('div', {class: 'pshead'}, h('span', {class: 'pactor ' + s.kind}, icon(s.kind === 'agent' ? 'cpu' : 'user'), s.actor || '—'), s.screen ? h('span', {class: 'chipx'}, s.screen) : null, h('span', {class: 'spacer'}), h('span', {class: 'small faint mono'}, s.id)),
      h('div', {class: 'paction'}, s.action),
      s.decision ? h('div', {class: 'pdecision'}, icon('route'), h('b', {}, 'Decision: '), s.decision) : null,
      s.rule ? h('div', {class: 'prule small'}, icon('shield'), h('b', {}, 'Rule: '), s.rule) : null,
      s.fields.length ? h('div', {class: 'row', style: 'gap:4px;margin-top:4px'}, s.fields.map(f => h('span', {class: 'tag'}, f))) : null))),
    p.handoffs.length ? h('div', {class: 'note'}, h('b', {}, 'Hand-offs: '), p.handoffs.map((x, i) => [i ? ' · ' : null, h('span', {class: 'mono small'}, x.from), ' → ', h('span', {class: 'mono small'}, x.to), x.when ? h('span', {class: 'muted'}, ` (${x.when})`) : null, byId[x.to] ? '' : ' ?'])) : null,
    h('div', {class: 'small muted'}, `${p.counts.agent_steps} of ${p.counts.steps} steps become agent work; the rest stay with people. Correct anything that is not how the work runs.`));
}
function startFieldsView(a) {
  const f = a.fields;
  return h('div', {class: 'stack'},
    h('div', {style: 'overflow:auto'}, h('table', {class: 'utable ftable'}, h('tr', {}, ['Field or rule', 'Found', 'Type', 'Rule', 'Confidence', 'From'].map((t, i) => h('th', {class: i === 4 ? '' : 'l'}, t))),
      f.rows.map(r => h('tr', {class: r.confidence != null && r.confidence < 0.8 ? 'low' : ''},
        h('td', {}, h('b', {}, r.field)), h('td', {class: 'mono small'}, r.example || '—'), h('td', {class: 'small'}, r.type || ''), h('td', {class: 'small'}, r.rule || ''),
        h('td', {class: 'n'}, r.confidence == null ? '—' : h('span', {class: 'conf', title: `${Math.round(r.confidence * 100)} %`}, h('span', {class: 'cbar'}, h('i', {style: `width:${Math.round(r.confidence * 100)}%`})), h('span', {class: 'small'}, `${Math.round(r.confidence * 100)} %`))),
        h('td', {class: 'small'}, r.source ? h('span', {class: 'chipx'}, r.source) : null, r.where ? h('span', {class: 'muted'}, ' ' + r.where) : null))))),
    h('div', {class: 'small muted'}, `${f.counts.fields} fields and values, ${f.counts.rules} rules` + (f.counts.low_confidence ? ` · ${f.counts.low_confidence} below 80 % confidence — check those first` : '') + '.'));
}
function startPlanView(a, st) {
  const p = a.plan, next = st.next || [];
  const info = id => next.find(n => n.id === id) || {};
  return h('div', {class: 'stack'},
    h('div', {class: 'plancards'}, p.modules.map(m => { const n = info(m.id); const mod = moduleById(m.id);
      return h('div', {class: 'pcard', style: 'min-height:0'}, h('div', {class: 'ptop'}, h('div', {class: 'pico'}, icon(mod ? mod.icon : 'grid')), n.state ? statePill(n.state) : null),
        h('div', {class: 'pname'}, `${m.position}. ${m.name}`), h('div', {class: 'ptext', style: '-webkit-line-clamp:4'}, m.builds),
        h('div', {class: 'confirm', style: 'margin-top:8px'}, m.checkpoints.map(c => h('div', {}, h('span', {class: 'proven'}, icon('check')), h('span', {}, h('b', {}, 'You confirm: '), c)))),
        n.link ? h('a', {class: 'popen', href: n.link}, n.live ? 'Open →' : 'How it will work →') : null); })),
    h('div', {class: 'g3'}, kpiTile('Modules', String(p.counts.modules), 'in the order they run'), kpiTile('Checkpoints', String(p.counts.checkpoints), 'nothing moves on without you'),
      kpiTile(p.estimate ? 'Estimated' : 'Hours saved', p.estimate || (p.hours_saved_month != null ? `≈ ${fmtN(p.hours_saved_month, 0)} / month` : '—'), p.estimate ? 'including your reviews' : p.hours_saved_month != null ? 'as the attachments suggest' : 'not stated in the attachments')));
}
const START_VIEW_FN = {process: startProcessView, fields: startFieldsView, plan: startPlanView};

/* ---------- attachments and what was read ---------- */
function attachmentRow(st, a) {
  const [ic, kind] = START_KIND[a.kind] || ['file', a.kind];
  const file = p => `/api/start/${st.id}/file/${encodeURIComponent(p).replace(/%2F/g, '/')}`;
  const body = [];
  if (a.deleted) body.push(h('div', {class: 'small muted'}, 'Deleted after confirmation.'));
  else if (!a.present) body.push(h('div', {class: 'small muted'}, 'Missing.'));
  else if (a.kind === 'image') body.push(h('a', {href: file(a.name), target: '_blank', rel: 'noopener'}, h('img', {class: 'athumb', src: file(a.name), alt: `Preview of ${a.name}`, loading: 'lazy'})));
  if (a.read && !a.deleted) {
    if (a.frames && a.frames.length) body.push(h('div', {class: 'frames'}, a.frames.map((f, i) => h('a', {href: file(f.replace(/^attachments\//, '')), target: '_blank', rel: 'noopener'}, h('img', {src: file(f.replace(/^attachments\//, '')), alt: `Frame ${i + 1} of ${a.name}`, loading: 'lazy'})))));
    if (a.sheets && a.sheets.length) body.push(h('div', {class: 'small muted'}, a.sheets.map(s => `${s.sheet}: ${fmtN(s.rows, 0)} rows × ${s.columns.length} columns`).join(' · ')));
    if (a.note) body.push(h('div', {class: 'small muted'}, a.note));
    if (a.text && a.kind !== 'image') body.push(h('details', {class: 'more'}, h('summary', {}, 'What Relay read' + (a.pages ? ` (${a.pages} ${a.kind === 'deck' ? 'slides' : 'pages'})` : '')), h('pre', {class: 'atext'}, a.text + (a.truncated ? '\n…' : ''))));
  }
  return h('div', {class: 'arow', style: 'flex-wrap:wrap'},
    h('span', {class: 'aico'}, icon(ic)),
    h('div', {class: 'grow', style: 'min-width:0'}, h('div', {class: 'an'}, a.name), h('div', {class: 'small muted'}, `${kind} · ${size(a.bytes)}` + (a.width ? ` · ${a.width} × ${a.height}` : '') + (a.meta && a.meta.duration_s ? ` · ${a.meta.duration_s} s` : ''))),
    a.deleted ? h('span', {class: 'tag'}, 'Deleted') : a.read ? h('span', {class: 'tag ok'}, 'Read') : h('span', {class: 'tag'}, st.status === 'reading' ? 'Reading…' : 'Waiting'),
    body.length ? h('div', {class: 'abody'}, body) : null);
}

/* ---------- the start page ---------- */
async function renderStartPage(id) {
  const main = $('#main');
  if (!$('#startpage') || $('#startpage').dataset.id !== id) main.replaceChildren(skel('page'));
  let st;
  try { st = await api('/api/start/' + id); } catch (e) {
    main.replaceChildren(h('div', {class: 'page'}, h('div', {class: 'card empty'}, h('h3', {}, 'No such start'), h('p', {}, e.message), h('a', {class: 'btn', href: '#/start'}, 'Start from an idea')))); return;
  }
  if (!location.hash.startsWith('#/start/' + id)) return;
  const me = S.me || {}, canEdit = st.access && st.access.can_edit, a = st.analysis, running = st.status === 'queued' || st.status === 'reading';
  const confirmed = st.confirmed || {}, nConf = START_VIEWS.filter(v => confirmed[v[0]]).length;
  const cur = running ? 1 : st.status === 'planned' ? 3 : st.status === 'awaiting_confirmation' ? 2 : st.status === 'error' ? 1 : 0;
  if (!S.startTab || !START_VIEWS.some(v => v[0] === S.startTab)) S.startTab = 'process';
  if (st.status === 'awaiting_confirmation' && confirmed[S.startTab]) { const nx = START_VIEWS.find(v => !confirmed[v[0]]); if (nx) S.startTab = nx[0]; }
  const act = async (path, body, okMsg) => { try { await api(`/api/start/${id}${path}`, {json: body || {}}); if (okMsg) notify(okMsg, 'ok'); renderStartPage(id); } catch (e) { notify(e.message, 'err'); } };
  const correct = view => {
    const ta = h('textarea', {rows: 4, placeholder: 'Tell Relay what is wrong, e.g. “Exceptions go to the AP lead, not the clerk”'});
    const ok = h('button', {class: 'btn primary', onclick: () => { if (!ta.value.trim()) return notify('Say what is wrong.', 'err'); mm.remove(); act(`/views/${view}/correct`, {comment: ta.value}, 'Sent — Relay re-reads with your correction'); }}, 'Send correction');
    const mm = modal(`Correct “${START_VIEWS.find(v => v[0] === view)[1]}”`, h('div', {class: 'mbody'}, h('label', {class: 'f', style: 'margin-top:0'}, 'What is wrong?'), ta,
      h('div', {class: 'hint'}, 'Relay re-reads the attachments with your correction and shows all three views again; every correction is kept in the record.'),
      h('div', {class: 'row', style: 'justify-content:flex-end;margin-top:12px'}, h('button', {class: 'btn', onclick: () => mm.remove()}, 'Cancel'), ok)));
  };
  const banner = st.status === 'error' ? h('div', {class: 'banner err'}, h('div', {class: 'ic'}, icon('alert')), h('div', {class: 'txt'}, h('div', {class: 't'}, 'Relay could not finish reading.'), h('div', {class: 'd'}, st.error || '')),
      canEdit ? h('button', {class: 'btn primary', onclick: () => act('/retry', {}, 'Queued again')}, 'Retry') : null)
    : running ? h('div', {class: 'banner run'}, h('div', {class: 'ic'}, h('span', {class: 'spin'})), h('div', {class: 'txt'}, h('div', {class: 't'}, st.status === 'queued' ? (st.position ? `${st.position} job(s) ahead of this one.` : 'Starting next…') : 'Relay is reading your attachments.'),
      h('div', {class: 'd'}, st.running_since ? `Running for ${dur(Date.now() - st.running_since * 1000)} · one agent, one job at a time` : 'Documents, sheets, images and recordings, one at a time; the views appear when it is done.')))
    : st.status === 'planned' ? h('div', {class: 'banner ok'}, h('div', {class: 'ic'}, icon('check')), h('div', {class: 'txt'}, h('div', {class: 't'}, 'Confirmed and planned.'), h('div', {class: 'd'}, `${st.promised.length} checkpoint${st.promised.length === 1 ? '' : 's'} promised — each appears in your validation queue when its module opens it.`)))
    : h('div', {class: 'banner you'}, h('div', {class: 'ic'}, icon('info')), h('div', {class: 'txt'}, h('div', {class: 't'}, nConf ? `${nConf} of 3 views confirmed.` : 'Your turn.'), h('div', {class: 'd'}, 'Here is what Relay understood. Confirm each view, or correct it — nothing starts until all three are confirmed.')));
  const tab = START_VIEWS.find(v => v[0] === S.startTab);
  const viewCard = !a ? h('div', {class: 'card', style: 'margin:0'}, h('div', {class: 'stack'}, [80, 65, 72, 50].map(w => h('i', {class: 'sk', style: `width:${w}%;height:12px`}))), h('div', {class: 'small muted', style: 'margin-top:8px'}, 'The views appear here when Relay has read everything.'))
    : h('div', {class: 'card', style: 'margin:0'},
      h('div', {class: 'row', style: 'margin-bottom:10px'}, h('div', {class: 'tabs', role: 'tablist', style: 'margin:0;border:0'}, START_VIEWS.map(([k, l]) => h('a', {href: '#', role: 'tab', class: S.startTab === k ? 'on' : '', 'aria-selected': String(S.startTab === k), onclick: e => { e.preventDefault(); S.startTab = k; renderStartPage(id); }}, confirmed[k] ? '✓ ' + l : l))),
        h('span', {class: 'spacer'}), h('span', {class: 'small muted'}, tab[2])),
      a.summary && S.startTab === 'process' ? h('div', {class: 'note'}, h('b', {}, 'What Relay understood: '), a.summary) : null,
      START_VIEW_FN[S.startTab](a, st),
      h('div', {class: 'row', style: 'border-top:1px solid var(--line);padding-top:12px;margin-top:14px'},
        confirmed[S.startTab] ? h('span', {class: 'row small', style: 'gap:6px'}, h('span', {class: 'proven'}, icon('check')), `Confirmed by ${confirmed[S.startTab].by_name || confirmed[S.startTab].by} · ${when(confirmed[S.startTab].when)}`)
          : h('span', {class: 'small muted'}, st.status === 'awaiting_confirmation' ? 'Is this right?' : running ? 'Relay is re-reading; the view will reopen.' : ''),
        h('span', {class: 'spacer'}),
        st.status === 'awaiting_confirmation' && canEdit && !confirmed[S.startTab] ? [h('button', {class: 'btn', onclick: () => correct(S.startTab)}, 'Correct something'),
          h('button', {class: 'btn primary', onclick: () => act(`/views/${S.startTab}/confirm`, {}, 'Confirmed — signed and logged')}, icon('check'), 'Confirm this view')] : null));
  const feed = h('div', {class: 'feed', id: 'startfeed'});
  api(`/api/start/${id}/activity?after=0`).then(evs => { const keep = evs.filter(e => e.kind !== 'tool' && e.kind !== 'result').slice(-10);
    feed.replaceChildren(...(keep.length ? keep.map(e => h('div', {class: 'fi'}, h('span', {class: 'ft'}, clock(e.ts)), h('span', {}, String(e.text || (e.kind === 'start' ? 'Relay started' : e.kind === 'done' ? `Finished: ${e.turns || 0} steps, ${usd(e.cost_usd)}` : e.kind))))) : [h('div', {class: 'muted small'}, 'Nothing yet.')])); }).catch(() => {});
  const nextCard = st.status === 'planned' && st.next.length ? h('div', {class: 'card', style: 'margin:0'}, h('h3', {}, 'Next'), h('div', {class: 'small muted', style: 'margin:-4px 0 10px'}, 'In this order; live modules open now, planned ones show how they will work.'),
    h('div', {class: 'stack', style: 'gap:8px'}, st.next.map(n => h('div', {class: 'nextrow'},
      h('div', {class: 'grow'}, h('b', {}, `${n.position}. ${n.name}`), h('div', {class: 'small muted'}, n.builds), n.promised.length ? h('div', {class: 'small', style: 'margin-top:3px'}, n.promised.map(p => h('span', {class: 'tag ' + (p.status === 'done' ? 'ok' : p.status === 'open' ? 'acc' : ''), style: 'margin:2px 4px 0 0'}, p.name + (p.status === 'upcoming' ? ' · upcoming' : p.status === 'open' ? ' · open' : ' · done')))) : null),
      n.can_start_dashboard && canEdit ? h('button', {class: 'btn sm primary', onclick: async () => { try { const r = await api(`/api/start/${id}/dashboard`, {method: 'POST'}); notify('Dashboard started — Relay plans it first', 'ok'); refreshList(); location.hash = '#/p/' + r.project.id; } catch (e) { notify(e.message, 'err'); } }}, icon('play'), 'Start the dashboard')
        : n.link ? h('a', {class: 'btn sm', href: n.link}, n.live ? 'Open' : 'How it will work') : null))))
    : null;
  main.replaceChildren(h('div', {class: 'page', id: 'startpage', 'data-id': id},
    pageHead({crumbs: [['Home', '#/'], ['Start', '#/start'], [st.name]], eyebrow: brandName() + ' · Start', title: st.name, promise: st.prompt,
      actions: h('div', {class: 'row'}, h('span', {id: 'startpill'}, startPill(st.status)), st.owner_name ? h('span', {class: 'small muted'}, 'started by ' + st.owner_name) : null)}),
    startJourney(cur), banner,
    h('div', {class: 'g-side'},
      h('div', {class: 'stack'}, viewCard,
        h('div', {class: 'card', style: 'margin:0'}, h('div', {class: 'card-head'}, h('h3', {}, 'Activity'), h('span', {class: 'sp'}), running ? h('span', {class: 'pill run'}, 'Working') : null), feed)),
      h('div', {class: 'stack'},
        h('div', {class: 'card', style: 'margin:0'}, h('div', {class: 'card-head'}, h('h3', {}, 'What was read'), h('span', {class: 'sp'}), h('span', {class: 'small muted'}, `${st.attachments.filter(x => x.read).length} of ${st.attachments.length}`)),
          h('div', {class: 'stack', style: 'gap:8px'}, st.attachments.length ? st.attachments.map(x => attachmentRow(st, x)) : h('div', {class: 'muted small'}, 'No attachments — Relay works from the brief.'),
            st.connection_details.map(c => h('div', {class: 'arow'}, h('span', {class: 'aico'}, icon('plug')), h('div', {class: 'grow'}, h('div', {class: 'an'}, c.name), h('div', {class: 'small muted'}, `${c.label} · live, read-only`)), h('span', {class: 'tag'}, c.status === 'gone' ? 'Removed' : 'Picked'))),
            (st.links || []).map(l => h('div', {class: 'arow'}, h('span', {class: 'aico'}, icon('external')), h('div', {class: 'grow', style: 'min-width:0'}, h('div', {class: 'an'}, l), h('div', {class: 'small muted'}, 'Link · noted, not opened'))))),
          st.has_recordings && canEdit && (st.status === 'planned' || confirmed.process) ? h('div', {style: 'margin-top:10px'}, h('button', {class: 'btn sm danger', onclick: async () => { if (await confirmBox('Delete the recordings now?', 'The video and audio files are removed from this workspace; the process map you confirmed stays. This is recorded in the audit log.', 'Delete recordings')) act('/recordings/delete', {}, 'Recordings deleted'); }}, 'Delete the recordings now')) : null,
          h('div', {class: 'hint'}, 'Attachments stay inside your workspace; they are never sent anywhere else.')),
        h('div', {class: 'card', style: 'margin:0'}, h('h3', {}, 'Your confirmations'),
          h('div', {class: 'stack', style: 'gap:6px'}, START_VIEWS.map(([k, l]) => h('div', {class: 'row', style: 'flex-wrap:nowrap'}, confirmed[k] ? h('span', {class: 'proven'}, icon('check')) : h('span', {class: 'faint'}, '○'), h('span', {class: confirmed[k] ? '' : 'muted'}, l), h('span', {class: 'spacer'}),
            h('span', {class: 'small muted'}, confirmed[k] ? `${confirmed[k].by_name || ''} · ${when(confirmed[k].when)}` : st.status === 'awaiting_confirmation' ? 'waiting' : '')))),
          (st.corrections || []).length ? h('details', {class: 'more'}, h('summary', {}, `${st.corrections.length} correction${st.corrections.length === 1 ? '' : 's'}`), h('ul', {class: 'small', style: 'margin:4px 0 0;padding-left:18px'}, st.corrections.map(c => h('li', {}, h('b', {}, (START_VIEWS.find(v => v[0] === c.view) || [c.view, c.view])[1] + ': '), c.comment)))) : null,
          st.status === 'planned' ? h('div', {class: 'small muted', style: 'margin-top:8px'}, `Planned ${when(st.planned)} · plan.yaml is final`) : h('div', {class: 'small muted', style: 'margin-top:8px'}, 'When all three are confirmed, the plan starts and its checkpoints are promised to your queue.')),
        nextCard,
        h('div', {class: 'row'}, h('a', {class: 'btn sm', href: '#/start'}, 'Start another'), h('a', {class: 'btn sm', href: '#/validate'}, 'Validation queue'),
          canEdit && st.status !== 'reading' ? h('button', {class: 'btn sm ghost danger', onclick: async () => { if (await confirmBox(`Remove “${st.name}”?`, 'The brief, its attachments and the analysis are deleted; its checkpoints are withdrawn.')) { try { await api('/api/start/' + id, {method: 'DELETE'}); notify('Removed', 'ok'); location.hash = '#/start'; } catch (e) { notify(e.message, 'err'); } } }}, 'Remove') : null)))));
  document.title = `${st.name} · Start · ${S.brand ? S.brand.full : 'RELAY by PASDACS'}`;
  if (running) S.startTimer = setTimeout(() => { if (location.hash.startsWith('#/start/' + id)) renderStartPage(id); }, 2500);
}
