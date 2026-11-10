/* ---------------- phase 7: notifications, scheduled reports and alerts, email accounts, costs and quotas ---------------- */
const WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
const NOTE_ICON = {ops: 'shield', build: 'check', share: 'share', alert: 'alert', schedule: 'clock', report: 'download', quota: 'info', review: 'edit'};
const myTz = () => (S.me && S.me.tz) || Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
const tzList = cur => { let z = []; try { z = Intl.supportedValuesOf('timeZone'); } catch (e) {}
  return [...new Set([cur, myTz(), 'UTC', ...z].filter(Boolean))]; };

/* notifications: the count in the navigation, a toast when something new arrives, the list page */
S.unread = 0;
async function refreshNotes() {
  try {
    const n = await api('/api/notifications');
    if (S.notesSeen !== undefined && n.items.length && n.items[0].id !== S.notesSeen && !n.items[0].read) notify(n.items[0].title, n.items[0].kind === 'alert' ? 'err' : 'ok');
    S.notesSeen = n.items.length ? n.items[0].id : null;
    if (n.unread !== S.unread) { S.unread = n.unread; renderShell(); }
    if (location.hash === '#/notifications') drawNotes(n);
  } catch (e) {}
}
setInterval(refreshNotes, 20000);
setTimeout(refreshNotes, 800);

function openNote(n) {
  api(`/api/notifications/${n.id}/read`, {method: 'POST'}).then(refreshNotes).catch(() => {});
  if (!n.link) return;
  if (n.link.startsWith('/api/')) window.open(n.link, '_blank'); else location.hash = n.link.replace(/^#/, '');
}
function drawNotes(n) {
  const list = $('#notelist');
  if (!list) return;
  list.replaceChildren(...(n.items.length ? n.items.map(x => h('div', {class: 'note-row' + (x.read ? '' : ' unread'), onclick: () => openNote(x)},
    h('span', {class: 'nicon ' + x.kind}, icon(NOTE_ICON[x.kind] || 'info')),
    h('div', {class: 'grow'}, h('b', {}, x.title), x.body ? h('div', {class: 'small muted'}, x.body) : null), h('span', {class: 'faint small'}, ago(x.created))))
    : [h('div', {class: 'muted'}, 'Nothing yet. Builds that finish, dashboards shared with you, alerts and schedules that need you show up here.')]));
}
async function renderNotes() {
  const page = h('div', {class: 'page'}, h('div', {class: 'phead'}, h('div', {}, h('h1', {}, 'Notifications'),
    h('div', {class: 'meta'}, 'Builds that finished, dashboards and pages shared with you, alerts, schedules that need you, AI budget warnings.'))),
    h('div', {class: 'row', style: 'justify-content:flex-end;margin-bottom:8px'}, h('button', {class: 'btn sm', onclick: async () => { drawNotes(await api('/api/notifications/read', {method: 'POST'})); refreshNotes(); }}, 'Mark all read')),
    h('div', {class: 'card flat', id: 'notelist'}, skel('rows')));
  $('#main').replaceChildren(page);
  try { drawNotes(await api('/api/notifications')); } catch (e) { page.append(h('div', {class: 'note err'}, e.message)); }
}

/* schedules page */
async function renderSchedules() {
  const page = h('div', {class: 'page'});
  $('#main').replaceChildren(skel('page'));
  let d;
  try { d = await api('/api/schedules'); } catch (e) { $('#main').replaceChildren(page); return page.append(h('div', {class: 'note err'}, e.message)); }
  if (!location.hash.startsWith('#/schedules')) return;
  $('#main').replaceChildren(page);
  const target = s => s.target.type === 'dashboard' ? `Dashboard · ${(d.dashboards.find(x => x.id === s.target.project) || {}).name || s.target.project}`
    : s.target.type === 'page' ? `Page · ${(d.pages.find(x => x.id === s.target.id) || {}).title || s.target.id}`
    : s.target.type === 'askd' ? `Ask D · “${s.target.question}”`
    : `${s.target.type === 'metric' ? '[' + s.target.measure + ']' : 'SQL'} ${s.target.op} ${s.target.threshold.toLocaleString()} · ${(d.dashboards.find(x => x.id === s.target.project) || {}).name || s.target.project}`;
  const act = (s, a, label, cls) => h('button', {class: 'btn sm' + (cls ? ' ' + cls : ''), onclick: async e => {
    e.target.disabled = true; if (a === 'run') notify('Running…');
    try { const r = await api(`/api/schedules/${s.id}/${a}`, {method: 'POST'});
      if (a === 'run') notify(r.ok ? r.result : r.error, r.ok ? 'ok' : 'err'); renderSchedules(); }
    catch (err) { notify(err.message, 'err'); e.target.disabled = false; } }}, label);
  const acct = id => (d.accounts.find(a => a.id === id) || {}).address;
  const card = s => h('div', {class: 'card flat sched'},
    h('div', {class: 'row'}, h('span', {class: 'nicon ' + (s.kind === 'alert' ? 'alert' : 'report')}, icon(s.kind === 'alert' ? 'alert' : 'clock')),
      h('div', {class: 'grow'}, h('b', {}, s.name), h('div', {class: 'small muted'}, target(s))),
      s.status === 'paused' ? h('span', {class: 'pill err'}, 'Paused') : s.kind === 'alert' && s.state.firing ? h('span', {class: 'pill you'}, 'Firing') : h('span', {class: 'pill ok'}, 'Active')),
    s.paused_reason ? h('div', {class: 'note warn small'}, s.paused_reason) : null,
    h('div', {class: 'kv small', style: 'margin-top:8px'},
      h('dt', {}, 'When'), h('dd', {}, s.when),
      h('dt', {}, 'Next'), h('dd', {}, s.status === 'active' && s.next_run ? new Date(s.next_run * 1000).toLocaleString() : '—'),
      h('dt', {}, 'Last'), h('dd', {}, s.last_run ? `${when(s.last_run)} · ${s.last_status}` + (s.last_error && s.last_status !== 'paused' ? ` — ${s.last_error}` : '') : 'not run yet'),
      s.kind === 'alert' ? [h('dt', {}, 'Value'), h('dd', {}, s.state.value == null ? '—' : Number(s.state.value).toLocaleString(undefined, {maximumFractionDigits: 4}))] : null,
      h('dt', {}, 'Sent'), h('dd', {}, s.email_account_id ? `by email from ${acct(s.email_account_id) || 'a removed account'} to ${s.recipients.map(r => (d.people.find(p => p.id === r) || {}).name || r).join(', ')}` : 'in Relay only')),
    h('div', {class: 'row', style: 'margin-top:10px'},
      act(s, 'run', s.kind === 'alert' ? 'Check now' : 'Send now'), s.status === 'active' ? act(s, 'pause', 'Pause') : act(s, 'resume', 'Resume', 'primary'),
      h('button', {class: 'btn sm', onclick: () => scheduleDialog(s.kind, d, s)}, icon('edit'), 'Edit'),
      s.kind === 'report' && s.state.file ? h('a', {class: 'btn sm', href: `/api/schedules/${s.id}/latest`}, icon('download'), 'Latest') : null,
      h('span', {class: 'spacer'}),
      h('button', {class: 'btn sm', onclick: async () => { if (!await confirmBox(`Delete “${s.name}”?`, s.kind === 'alert' ? 'The alert stops checking.' : 'The report is no longer sent; its last copy is deleted.', 'Delete')) return; await api(`/api/schedules/${s.id}`, {method: 'DELETE'}); renderSchedules(); }}, 'Delete')));
  const reports = d.schedules.filter(s => s.kind === 'report'), alerts = d.schedules.filter(s => s.kind === 'alert');
  page.append(h('div', {}, h('div', {class: 'phead'}, h('div', {class: 'grow'}, h('h1', {}, 'Schedules'),
      h('div', {class: 'meta'}, `Reports emailed on a schedule and alerts on your KPIs. New schedules use your time zone, ${myTz()} (change it in Settings).`)),
      h('button', {class: 'btn', onclick: () => scheduleDialog('alert', d)}, icon('alert'), 'New alert'),
      h('button', {class: 'btn primary', onclick: () => scheduleDialog('report', d)}, icon('clock'), 'New report')),
    !d.accounts.length ? h('div', {class: 'note'}, icon('info'), ' Connect a Gmail or Microsoft email account in ', h('a', {href: '#/settings'}, 'Settings'),
      ' to have reports and alerts emailed. Without one they arrive here, in Relay.') : null,
    scheduleAsk(d),
    h('h3', {}, 'Reports'), reports.length ? reports.map(card) : h('div', {class: 'muted small', style: 'margin-bottom:16px'}, 'No reports yet — for example, your Monday overview as a PDF at 8:00.'),
    h('h3', {style: 'margin-top:18px'}, 'Alerts'), alerts.length ? alerts.map(card) : h('div', {class: 'muted small'}, 'No alerts yet — for example, tell me when Net Sales falls under target.')));
}

function scheduleDialog(kind, d, s, prefill) {
  const v = s || prefill ? JSON.parse(JSON.stringify(s || prefill)) : {kind, name: '', tz: myTz(), recipients: [S.me.id], email_account_id: (d.accounts.find(a => a.status === 'connected') || {}).id || null,
    cadence: kind === 'report' ? {freq: 'weekly', weekday: 0, time: '08:00'} : {freq: 'daily', time: '07:00'},
    target: kind === 'report' ? {type: 'dashboard', project: (d.dashboards[0] || {}).id, format: 'pdf'} : {type: 'metric', project: (d.dashboards[0] || {}).id, measure: '', op: '<', threshold: 0}};
  const body = h('div', {class: 'mbody stack'});
  const err = h('div', {});
  let measures = null;
  const f = (label, el, hint) => h('div', {}, h('label', {class: 'f'}, label), el, hint ? h('div', {class: 'hint'}, hint) : null);
  const sel = (opts, cur, on) => { const el = h('select', {class: 'sel'}, opts.map(([val, lab]) => h('option', {value: val, selected: String(val) === String(cur)}, lab))); el.onchange = () => on(el.value); return el; };
  const inp = (cur, on, attrs) => { const el = h('input', {type: 'text', value: cur ?? '', ...(attrs || {})}); el.oninput = () => on(el.value); return el; };
  const loadMeasures = async () => { measures = null; if (!v.target.project) return; try { measures = (await api(`/api/schedules-measures/${v.target.project}`)).measures; } catch (e) { measures = []; } draw(); };
  const draw = () => {
    const t = v.target, c = v.cadence;
    const what = kind === 'report' ? [
      f('Send', sel([['dashboard', 'A dashboard (its prototype)'], ['page', 'An insight page'], ['askd', 'An Ask D question, answered fresh each time']], t.type, x => { v.target = {type: x, format: t.format || 'pdf'}; if (x === 'dashboard') v.target.project = (d.dashboards[0] || {}).id; if (x === 'page') v.target.id = (d.pages[0] || {}).id; if (x === 'askd') { v.target.scope = {kind: 'team'}; v.recipients = [S.me.id]; } draw(); })),
      t.type === 'dashboard' ? f('Dashboard', sel(d.dashboards.map(x => [x.id, x.name]), t.project, x => { t.project = x; })) : null,
      t.type === 'page' ? f('Page', d.pages.length ? sel(d.pages.map(x => [x.id, x.title]), t.id, x => { t.id = x; }) : h('div', {class: 'muted small'}, 'You have no pages yet.')) : null,
      t.type === 'askd' ? [f('Question', inp(t.question, x => { t.question = x; }, {placeholder: 'How did sales do last week, by region?'})),
        f('Look at', sel([['team', 'My team’s data'], ['org', 'Everything I can open'], ...d.dashboards.map(x => ['dashboard:' + x.id, 'Dashboard · ' + x.name])],
          t.scope.kind === 'dashboard' ? 'dashboard:' + t.scope.project : t.scope.kind, x => { t.scope = x.startsWith('dashboard:') ? {kind: 'dashboard', project: x.slice(10)} : {kind: x}; }),
          'Answered with your own access each time; it goes to you only.')] : null,
      f('Format', sel([['pdf', 'PDF'], ['png', 'PNG image']], t.format, x => { t.format = x; }))] : [
      f('Dashboard', sel(d.dashboards.map(x => [x.id, x.name]), t.project, x => { t.project = x; t.measure = ''; loadMeasures(); })),
      f('Check', sel([['metric', 'A measure of the dashboard'], ['sql', 'My own SQL (one number)']], t.type, x => { t.type = x; draw(); })),
      t.type === 'metric' ? f('Measure', measures === null ? h('div', {class: 'muted small'}, 'Loading measures…') : sel([['', 'Choose…'], ...measures.map(m => [m.name, m.name + (m.checkable ? '' : ' — use SQL')])], t.measure, x => { t.measure = x; }),
        'Measures built from one table (SUM, AVERAGE, COUNT, DIVIDE …) are checked on the dashboard’s data.')
        : f('SQL', (() => { const el = h('textarea', {rows: 3, class: 'mono', placeholder: 'SELECT SUM("Revenue") FROM "Sales" WHERE "Month" >= DATE \'2026-10-01\''}, t.sql || ''); el.oninput = () => { t.sql = el.value; }; return el; })(),
          'One read-only SELECT over the dashboard’s tables, returning one number.'),
      h('div', {class: 'row'}, f('Alert when it is', sel([['<', 'below'], ['<=', 'at or below'], ['>', 'above'], ['>=', 'at or above']], t.op, x => { t.op = x; })),
        f('Threshold', inp(t.threshold, x => { t.threshold = x; }, {type: 'number', step: 'any', style: 'width:160px'})),
        h('button', {class: 'btn sm', style: 'align-self:flex-end', onclick: async () => { try { const r = await api('/api/schedules-preview', {json: {target: t}}); notify(`Now: ${r.value == null ? 'no value' : Number(r.value).toLocaleString()}`, 'ok'); } catch (e) { notify(e.message, 'err'); } }}, 'Test value'))];
    body.replaceChildren(...[
      f('Name', inp(v.name, x => { v.name = x; }, {placeholder: kind === 'report' ? 'Monday overview' : 'Net Sales below target'})),
      ...what.flat().filter(Boolean),
      h('div', {class: 'row'},
        f('How often', sel((kind === 'alert' ? [['hourly', 'Every hour']] : []).concat([['daily', 'Every day'], ['weekdays', 'Weekdays'], ['weekly', 'Every week'], ['monthly', 'Every month']]), c.freq, x => { c.freq = x; if (x === 'weekly' && c.weekday == null) c.weekday = 0; if (x === 'monthly' && !c.day) c.day = 1; draw(); })),
        c.freq === 'weekly' ? f('On', sel(WEEKDAYS.map((w, i) => [i, w]), c.weekday, x => { c.weekday = +x; })) : null,
        c.freq === 'monthly' ? f('Day', sel([...Array(28).keys()].map(i => [i + 1, String(i + 1)]), c.day, x => { c.day = +x; })) : null,
        f(c.freq === 'hourly' ? 'Minute' : 'At', inp(c.freq === 'hourly' ? c.time : c.time, x => { c.time = x; }, {type: 'time', style: 'width:120px'})),
        f('Time zone', sel(tzList(v.tz).map(z => [z, z]), v.tz, x => { v.tz = x; }))),
      f('Email from', sel([['', 'Do not email — keep it in Relay'], ...d.accounts.map(a => [a.id, `${a.address} (${a.kind === 'gmail' ? 'Gmail' : 'Microsoft'}${a.status !== 'connected' ? ', ' + a.status : ''})`])],
        v.email_account_id || '', x => { v.email_account_id = x || null; draw(); }), d.accounts.length ? null : 'Connect an email account in Settings first.'),
      kind === 'report' && t.type !== 'askd' && v.email_account_id ? f('To', h('div', {class: 'opts'}, d.people.map(p => h('label', {class: 'chk'},
        h('input', {type: 'checkbox', checked: v.recipients.includes(p.id), onchange: e => { v.recipients = e.target.checked ? [...v.recipients, p.id] : v.recipients.filter(r => r !== p.id); }}), p.name))),
        'Everyone you pick must be able to open what is sent.') : null,
      err,
      h('div', {class: 'row', style: 'justify-content:flex-end'}, h('button', {class: 'btn primary', onclick: async () => {
        err.replaceChildren();
        try { await api(s ? `/api/schedules/${s.id}` : '/api/schedules', {method: s ? 'PUT' : 'POST', json: {kind, name: v.name, target: {...v.target, threshold: v.target.threshold === undefined ? undefined : Number(v.target.threshold)},
            cadence: v.cadence, tz: v.tz, email_account_id: v.email_account_id, recipients: v.recipients}});
          m.remove(); notify('Saved', 'ok'); renderSchedules(); }
        catch (e) { err.replaceChildren(h('div', {class: 'note err'}, e.message)); } }}, s ? 'Save' : kind === 'report' ? 'Schedule report' : 'Create alert'))].filter(x => x != null));
  };
  const m = modal(s ? `Edit ${kind}` : kind === 'report' ? 'New scheduled report' : 'New alert', body);
  draw();
  if (kind === 'alert') loadMeasures();
}

/* describe a report or an alert in words: the AI drafts it, Relay checks it against the real data, the person confirms */
function scheduleAsk(d) {
  const out = h('div', {class: 'stack', style: 'gap:10px'});
  const ta = h('textarea', {rows: 2, placeholder: 'e.g. “Every Monday at 9 send me the kirana dashboard as a PDF” or “Tell me when daily sales in Koramangala fall below ₹50,000”',
    'aria-label': 'Describe the report or alert'});
  let current = null;                                    // the draft on screen, revised by follow-ups
  const go = async (text, previous) => {
    text = (text || '').trim();
    if (!text) return ta.focus();
    btn.disabled = true; btn.textContent = 'Drafting…';
    out.replaceChildren(h('div', {class: 'card flat'}, skel('rows')));
    try { draw(await api('/api/schedules-draft', {json: {request: text, previous}}), text); }
    catch (e) { out.replaceChildren(h('div', {class: 'note err'}, e.message)); }
    finally { btn.disabled = false; btn.textContent = 'Draft it'; }
  };
  const btn = h('button', {class: 'btn primary', onclick: () => go(ta.value, null)}, 'Draft it');
  ta.onkeydown = e => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) go(ta.value, null); };
  const draw = (r, asked) => {
    if (r.question) { current = current || null;
      return out.replaceChildren(h('div', {class: 'note'}, icon('info'), ' ', r.question, h('div', {class: 'small muted', style: 'margin-top:4px'}, 'Add the detail above and draft again.'))); }
    if (r.problem) return out.replaceChildren(h('div', {class: 'note warn'}, r.problem, r.explanation ? h('div', {class: 'small muted', style: 'margin-top:4px'}, r.explanation) : null));
    current = r.draft;
    const dft = r.draft, sm = r.summary, t = dft.target;
    const pv = h('div', {});
    if (dft.kind === 'alert') {
      const v = r.preview.value;
      pv.append(h('div', {class: 'note ' + (r.preview.fires_now ? 'warn' : 'ok')}, h('b', {}, 'Right now: ', v == null ? 'no value' : Number(v).toLocaleString(undefined, {maximumFractionDigits: 4})),
        ' — ', r.preview.fires_now ? 'the condition is already met, so the first check will alert you.' : 'the condition is not met; you hear from it when it is.'));
    } else {
      pv.append(h('button', {class: 'btn sm', onclick: async e => {
        const b = e.currentTarget; b.disabled = true; b.textContent = t.type === 'askd' ? 'Answering and drawing…' : 'Drawing…';
        try { const res = await fetch('/api/schedules-draft/preview', {method: 'POST', headers: {'content-type': 'application/json'}, body: JSON.stringify({target: t})});
          if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || `Preview failed (${res.status})`);
          const img = h('img', {src: URL.createObjectURL(await res.blob()), alt: 'Preview of the report', class: 'sprev'}); pv.replaceChildren(h('div', {class: 'small muted'}, 'What it would send now:'), img); }
        catch (err) { notify(err.message, 'err'); b.disabled = false; b.textContent = 'Preview it'; } }},
        icon('file'), t.type === 'askd' ? 'Preview it (answers the question once)' : 'Preview it'));
    }
    const follow = h('input', {type: 'text', placeholder: 'Change something: “make it 7am”, “weekdays only”, “also send to Priya”…', 'aria-label': 'Change the draft'});
    follow.onkeydown = e => { if (e.key === 'Enter') go(follow.value, current); };
    out.replaceChildren(h('div', {class: 'card sdraft'},
      h('div', {class: 'row'}, h('span', {class: 'nicon ' + (dft.kind === 'alert' ? 'alert' : 'report')}, icon(dft.kind === 'alert' ? 'alert' : 'clock')),
        h('div', {class: 'grow'}, h('div', {class: 'faint small'}, dft.kind === 'alert' ? 'New alert · draft' : 'New report · draft'), h('b', {style: 'font-size:15px'}, dft.name))),
      r.explanation ? h('p', {class: 'small', style: 'margin:8px 0 0'}, r.explanation) : null,
      h('dl', {class: 'kv small', style: 'margin-top:10px'},
        h('dt', {}, dft.kind === 'alert' ? 'Checks' : 'Sends'), h('dd', {}, sm.what + (t.format ? ` (${t.format.toUpperCase()})` : '')),
        t.type === 'sql' ? [h('dt', {}, 'SQL'), h('dd', {}, h('code', {class: 'mono small'}, t.sql))] : null,
        h('dt', {}, 'When'), h('dd', {}, sm.when),
        h('dt', {}, 'First run'), h('dd', {}, new Date(sm.next_run * 1000).toLocaleString()),
        h('dt', {}, 'To'), h('dd', {}, sm.to.join(', ') + (sm.by_email ? ' · by email' : ' · in Relay'))),
      pv,
      h('div', {class: 'row', style: 'margin-top:12px;flex-wrap:wrap'},
        h('button', {class: 'btn primary', onclick: async e => { e.currentTarget.disabled = true;
          try { await api('/api/schedules', {json: dft}); notify(dft.kind === 'alert' ? 'Alert created' : 'Report scheduled', 'ok'); renderSchedules(); }
          catch (err) { notify(err.message, 'err'); e.currentTarget.disabled = false; } }}, icon('check'), dft.kind === 'alert' ? 'Create alert' : 'Schedule report'),
        h('button', {class: 'btn', onclick: () => scheduleDialog(dft.kind, d, null, dft)}, icon('edit'), 'Adjust in the form'),
        h('button', {class: 'btn ghost', onclick: () => { current = null; out.replaceChildren(); ta.focus(); }}, 'Discard')),
      h('div', {class: 'row', style: 'margin-top:10px'}, h('div', {class: 'grow'}, follow), h('button', {class: 'btn sm', onclick: () => go(follow.value, current)}, 'Update draft'))));
  };
  const ex = ['Every Monday at 8 email me the main dashboard as a PDF', 'Alert me when total sales drop below 1 lakh', 'Each weekday at 9, how did yesterday go by region?'];
  return h('div', {class: 'card sask'},
    h('div', {class: 'row', style: 'align-items:flex-start'}, h('span', {class: 'nicon'}, icon('spark')),
      h('div', {class: 'grow'}, h('b', {}, 'Describe it'), h('div', {class: 'small muted'}, 'Say what to send or what to watch, and when. Relay drafts it and checks it against your data; nothing runs until you confirm.'))),
    h('div', {class: 'row', style: 'margin-top:10px;align-items:flex-end'}, h('div', {class: 'grow'}, ta), btn),
    h('div', {class: 'chips', style: 'margin-top:8px'}, ex.map(x => h('button', {class: 'chip', onclick: () => { ta.value = x; ta.focus(); }}, x))),
    out);
}

/* settings: time zone, email accounts, my AI spend this month */
async function scheduleSettings() {
  const [acc, use] = await Promise.all([api('/api/email/accounts'), api('/api/me/usage')]);
  const err = new URLSearchParams(location.hash.split('?')[1] || '').get('email_error');
  const tzSel = h('select', {class: 'sel', style: 'max-width:320px'}, tzList(myTz()).map(z => h('option', {value: z, selected: z === myTz()}, z)));
  tzSel.onchange = async () => { try { await api('/api/me/tz', {method: 'PUT', json: {tz: tzSel.value}}); S.me.tz = tzSel.value; notify('Time zone saved', 'ok'); } catch (e) { notify(e.message, 'err'); } };
  if (S.me && !S.me.tz) api('/api/me/tz', {method: 'PUT', json: {tz: myTz()}}).then(r => { S.me.tz = r.tz; }).catch(() => {});
  const accRows = h('div', {});
  const drawAcc = a => accRows.replaceChildren(...(a.accounts.length ? [h('table', {class: 'utable'}, h('tr', {}, ['Address', 'Kind', 'Status', ''].map((t, i) => h('th', {class: 'l'}, t))),
    a.accounts.map(x => h('tr', {}, h('td', {}, x.address), h('td', {}, x.kind === 'gmail' ? 'Gmail' : 'Microsoft'),
      h('td', {}, x.status === 'connected' ? h('span', {class: 'tag ok'}, 'Connected') : h('span', {class: 'tag err', title: x.error || ''}, x.status)),
      h('td', {class: 'n'}, h('button', {class: 'btn sm', onclick: async () => { try { drawAcc(await api(`/api/email/accounts/${x.id}/test`, {json: {}})); notify(`Test email sent to ${S.me.email}`, 'ok'); } catch (e) { notify(e.message, 'err'); } }}, 'Send test'),
        ' ', h('button', {class: 'btn sm', onclick: async () => { if (await confirmBox(`Remove ${x.address}?`, 'Its password or sign-in is deleted. Schedules that send from it pause until you choose another account.')) drawAcc(await api(`/api/email/accounts/${x.id}`, {method: 'DELETE'})); }}, 'Remove')))))]
    : [h('div', {class: 'muted small'}, 'No email account yet.')]));
  drawAcc(acc);
  const gmail = () => {
    const addr = h('input', {type: 'email', placeholder: 'you@gmail.com'}), pw = h('input', {type: 'password', placeholder: 'abcd efgh ijkl mnop', autocomplete: 'off'}), e2 = h('div', {});
    const m = modal('Connect Gmail', h('div', {class: 'mbody stack'},
      h('div', {class: 'small'}, 'Relay sends with an app password, never your Google password. In your Google account turn on 2-Step Verification, then open Security › App passwords, create one for “Relay” and paste the 16 letters here.'),
      h('label', {class: 'f'}, 'Gmail address'), addr, h('label', {class: 'f'}, 'App password'), pw, e2,
      h('div', {class: 'row', style: 'justify-content:flex-end'}, h('button', {class: 'btn primary', onclick: async ev => { ev.target.disabled = true;
        try { drawAcc(await api('/api/email/gmail', {json: {address: addr.value, app_password: pw.value}})); m.remove(); notify('Gmail connected', 'ok'); }
        catch (e) { e2.replaceChildren(h('div', {class: 'note err'}, e.message)); ev.target.disabled = false; } }}, 'Connect'))));
  };
  const microsoft = async () => { try { location.href = (await api('/api/email/microsoft/start', {method: 'POST'})).url; } catch (e) { notify(e.message, 'err'); } };
  const q = use.quotas || [];
  return [h('div', {class: 'card'}, h('h3', {}, 'Schedules and email'),
    err ? h('div', {class: 'note err'}, 'Microsoft sign-in: ' + err) : null,
    h('label', {class: 'f'}, 'My time zone'), tzSel, h('div', {class: 'hint'}, 'Scheduled reports and alerts run at this wall-clock time, daylight saving included.'),
    h('label', {class: 'f', style: 'margin-top:14px'}, 'Email accounts for reports and alerts'), accRows,
    h('div', {class: 'row', style: 'margin-top:10px'}, h('button', {class: 'btn', onclick: gmail}, 'Connect Gmail'),
      h('button', {class: 'btn', onclick: microsoft, disabled: !acc.microsoft_ready, title: acc.microsoft_ready ? '' : 'Your administrator has not set up Microsoft email yet'}, 'Connect Microsoft work account'),
      h('span', {class: 'spacer'}), h('a', {href: '#/schedules'}, 'My schedules →'))),
    h('div', {class: 'card'}, h('h3', {}, `My AI use in ${use.month}`),
      h('div', {class: 'stats', style: 'margin:6px 0 10px'}, h('div', {class: 'stat'}, h('b', {}, usd(use.cost_usd)), h('span', {}, 'estimated cost')),
        h('div', {class: 'stat'}, h('b', {}, tok(use.tokens)), h('span', {}, 'tokens'))),
      q.length ? q.map(x => quotaBar(x, x.scope === 'user' ? 'My monthly budget' : x.scope === 'workspace' ? 'This workspace' : `Team ${x.name}`)) : h('div', {class: 'muted small'}, 'No budget limit is set for you or your teams.'))];
}
function quotaBar(x, label) {
  const pct = Math.min(100, x.monthly_usd ? 100 * x.spent_usd / x.monthly_usd : 100);
  const col = x.level === 'stop' ? 'var(--err)' : x.level === 'warn' ? 'var(--warn)' : 'var(--ok)';
  return h('div', {style: 'margin:8px 0'}, h('div', {class: 'row small'}, h('b', {}, label), h('span', {class: 'spacer'}), `${usd(x.spent_usd)} of ${usd(x.monthly_usd)}`,
    x.level === 'stop' ? h('span', {class: 'tag err'}, 'limit reached') : x.level === 'warn' ? h('span', {class: 'tag warn'}, `over ${x.soft_pct}%`) : null),
    h('div', {class: 'qbar'}, h('i', {style: `width:${pct}%;background:${col}`}), h('s', {style: `left:${x.soft_pct}%`})));
}

/* admin: costs and quotas */
async function adminCosts() {
  const month = new URLSearchParams(location.hash.split('?')[1] || '').get('month') || '';
  const [r, ud, td] = await Promise.all([api('/api/admin/costs' + (month ? '?month=' + month : '')), api('/api/admin/users'), api('/api/admin/teams')]);
  const users = ud.users, teams = td.teams;
  const months = [...Array(12).keys()].map(i => { const d = new Date(); d.setUTCDate(1); d.setUTCMonth(d.getUTCMonth() - i); return d.toISOString().slice(0, 7); });
  const msel = h('select', {class: 'sel', style: 'width:auto', 'aria-label': 'Month'}, months.map(m => h('option', {value: m, selected: m === r.month}, m)));
  msel.onchange = () => { location.hash = '#/admin/costs?month=' + msel.value; };
  const tile = (t, v, s) => h('div', {class: 'stat'}, h('b', {}, v), h('span', {}, t), s ? h('div', {class: 'faint small'}, s) : null);
  const bars = (rows, label) => { const top = Math.max(...rows.map(x => x.cost_usd), 0.0001);
    return h('table', {class: 'utable'}, h('tr', {}, h('th', {class: 'l'}, label), h('th', {class: 'l', style: 'width:40%'}, ''), h('th', {}, 'Runs'), h('th', {}, 'Tokens'), h('th', {}, 'Cost')),
      rows.length ? rows.map(x => h('tr', {}, h('td', {}, label === 'Model' ? modelName(x.name) : label === 'Step' ? (STAGES[x.name] || {askd: 'Ask D', describe: 'Descriptions', schedule_draft: 'Report & alert drafts', start_read: 'Reading a start'}[x.name] || String(x.name).replace(/_/g, ' ').replace(/^./, c => c.toUpperCase())) : x.name),
        h('td', {}, h('div', {class: 'cbar'}, h('i', {style: `width:${100 * x.cost_usd / top}%`}))), h('td', {class: 'n'}, x.runs), h('td', {class: 'n'}, tok(x.tokens)), h('td', {class: 'n'}, usd(x.cost_usd))))
        : h('tr', {}, h('td', {colspan: 5, class: 'muted'}, 'Nothing this month.'))); };
  const top = Math.max(...r.by_day.map(x => x.cost_usd), 0.0001);
  const trend = h('div', {class: 'daybars', title: 'LLM cost per day (UTC)'}, r.by_day.map(x => h('i', {style: `height:${Math.max(2, 100 * x.cost_usd / top)}%`, title: `${x.day}: ${usd(x.cost_usd)}`})));
  const t = r.total, change = t.previous_llm_usd ? (t.llm_usd - t.previous_llm_usd) / t.previous_llm_usd : null;
  // quotas
  const qs = {scope: 'team', target_id: (teams[0] || {}).id, monthly_usd: '', soft_pct: 80};
  const qform = () => { const box = h('div', {class: 'row'});
    const draw = () => box.replaceChildren(
      (() => { const s = h('select', {class: 'sel', style: 'width:auto', 'aria-label': 'Quota for'}, h('option', {value: 'team', selected: qs.scope === 'team'}, 'Team'), h('option', {value: 'user', selected: qs.scope === 'user'}, 'Person'), h('option', {value: 'workspace', selected: qs.scope === 'workspace'}, 'The whole workspace'));
        s.onchange = () => { qs.scope = s.value; qs.target_id = qs.scope === 'workspace' ? 'workspace' : (qs.scope === 'team' ? teams : users)[0].id; draw(); }; return s; })(),
      qs.scope === 'workspace' ? h('span', {class: 'small muted'}, 'every person and team here together') : (() => { const s = h('select', {class: 'sel', style: 'width:auto', 'aria-label': qs.scope === 'team' ? 'Team' : 'Person'}, (qs.scope === 'team' ? teams : users.filter(u => u.active)).map(x => h('option', {value: x.id, selected: x.id === qs.target_id}, x.name)));
        s.onchange = () => { qs.target_id = s.value; }; return s; })(),
      (() => { const el = h('input', {type: 'number', min: 0, step: 1, placeholder: 'USD per month', style: 'width:150px', value: qs.monthly_usd, 'aria-label': 'Monthly limit in USD'}); el.oninput = () => { qs.monthly_usd = el.value; }; return el; })(),
      h('span', {class: 'small muted'}, 'warn at'),
      (() => { const el = h('input', {type: 'number', min: 1, max: 100, style: 'width:70px', value: qs.soft_pct, 'aria-label': 'Warn at percent'}); el.oninput = () => { qs.soft_pct = +el.value; }; return el; })(), h('span', {class: 'small muted'}, '%'),
      h('button', {class: 'btn primary sm', onclick: async () => { try { await api('/api/admin/quotas', {method: 'PUT', json: {...qs, monthly_usd: Number(qs.monthly_usd)}}); notify('Quota saved', 'ok'); reAdmin(); } catch (e) { notify(e.message, 'err'); } }}, 'Set quota'));
    draw(); return box; };
  const price = h('input', {type: 'number', min: 0, step: 0.25, value: r.price_tb, style: 'width:90px', 'aria-label': 'Price per TB scanned in USD'});
  return h('div', {},
    h('div', {class: 'row'}, h('span', {class: 'muted small'}, 'Month (UTC)'), msel, h('span', {class: 'spacer'}),
      h('span', {class: 'faint small'}, 'LLM costs are the providers’ list-price estimates per run; warehouse cost is bytes scanned × the price per TB.')),
    h('div', {class: 'stats'}, tile('LLM cost', usd(t.llm_usd), change == null ? '' : `${change >= 0 ? '+' : ''}${(100 * change).toFixed(0)}% vs previous month`),
      tile('tokens', tok(t.tokens), `${t.runs} runs`), tile('warehouse', usd(t.warehouse_usd), `${t.queries} live queries · ${size(t.bytes_scanned)} scanned`),
      tile('extracts', size(t.extract_bytes), `${t.extracts} refreshed this month`)),
    h('div', {class: 'card flat'}, h('h3', {}, 'LLM cost per day'), r.by_day.length ? trend : h('div', {class: 'muted small'}, 'Nothing this month.')),
    h('div', {class: 'grid2'}, h('div', {class: 'card flat'}, h('h3', {}, 'Per team'), bars(r.by_team, 'Team')), h('div', {class: 'card flat'}, h('h3', {}, 'Per person'), bars(r.by_user, 'Person'))),
    h('div', {class: 'grid2'}, h('div', {class: 'card flat'}, h('h3', {}, 'Per model'), bars(r.by_model, 'Model')), h('div', {class: 'card flat'}, h('h3', {}, 'Per step'), bars(r.by_step, 'Step'))),
    h('div', {class: 'card flat'}, h('h3', {}, 'Warehouse queries'),
      r.warehouse.length ? h('table', {class: 'utable'}, h('tr', {}, h('th', {class: 'l'}, 'Connection'), h('th', {class: 'l'}, 'Kind'), h('th', {class: 'l'}, 'People'), h('th', {}, 'Queries'), h('th', {}, 'Scanned'), h('th', {}, 'Cost')),
        r.warehouse.map(x => h('tr', {}, h('td', {}, x.name || x.connection), h('td', {}, x.kind), h('td', {}, x.people.join(', ')), h('td', {class: 'n'}, x.queries), h('td', {class: 'n'}, x.bytes ? size(x.bytes) : '—'), h('td', {class: 'n'}, usd(x.cost_usd)))))
        : h('div', {class: 'muted small'}, 'No live warehouse queries this month.'),
      h('div', {class: 'row small', style: 'margin-top:10px'}, h('span', {class: 'muted'}, 'Price per TB scanned (USD)'), price,
        h('button', {class: 'btn sm', onclick: async () => { try { await api('/api/admin/costs/price', {method: 'PUT', json: {price_tb: Number(price.value)}}); notify('Saved', 'ok'); reAdmin(); } catch (e) { notify(e.message, 'err'); } }}, 'Save'),
        h('span', {class: 'faint'}, 'Only BigQuery reports bytes before a query runs; other warehouses show their query count.'))),
    h('div', {class: 'card flat'}, h('h3', {}, 'Extract storage'),
      r.extracts.length ? h('table', {class: 'utable'}, h('tr', {}, h('th', {class: 'l'}, 'Dashboard'), h('th', {}, 'Tables'), h('th', {}, 'Rows'), h('th', {}, 'Size')),
        r.extracts.map(x => h('tr', {}, h('td', {}, h('a', {href: '#/p/' + x.project}, x.name || x.project)), h('td', {class: 'n'}, x.tables), h('td', {class: 'n'}, x.rows.toLocaleString()), h('td', {class: 'n'}, size(x.bytes)))))
        : h('div', {class: 'muted small'}, 'No warehouse extracts.')),
    h('div', {class: 'card flat'}, h('h3', {}, 'Quotas'),
      h('div', {class: 'hint', style: 'margin-bottom:10px'}, 'A monthly AI budget per person or team. At the warning level people are told once; at the limit new builds and Ask D questions wait until next month (running work finishes).'),
      r.quotas.length ? r.quotas.map(x => h('div', {class: 'row'}, h('div', {class: 'grow'}, quotaBar({...x, level: x.spent_usd >= x.monthly_usd ? 'stop' : x.spent_usd >= x.monthly_usd * x.soft_pct / 100 ? 'warn' : 'ok'}, x.scope === 'workspace' ? 'The whole workspace' : `${x.scope === 'team' ? 'Team' : 'Person'} · ${x.name}`)),
        h('button', {class: 'btn sm', onclick: async () => { await api('/api/admin/quotas', {method: 'PUT', json: {scope: x.scope, target_id: x.target_id, monthly_usd: null}}); reAdmin(); }}, 'Remove')))
        : h('div', {class: 'muted small'}, 'No quotas.'),
      h('div', {style: 'margin-top:12px'}, qform())));
}

/* admin: Microsoft email app, every schedule */
async function adminScheduling() {
  const [e, s] = await Promise.all([api('/api/admin/email'), api('/api/admin/schedules')]);
  const cid = h('input', {type: 'text', value: e.client_id || '', placeholder: 'Application (client) ID'}), ten = h('input', {type: 'text', value: e.tenant || 'organizations'}),
    sec = h('input', {type: 'password', placeholder: e.has_secret ? 'Stored — leave empty to keep' : 'Client secret', autocomplete: 'off'});
  return h('div', {},
    h('div', {class: 'card flat'}, h('h3', {}, 'Microsoft work email'),
      h('div', {class: 'hint'}, 'Register an app in Microsoft Entra ID with the delegated permissions Mail.Send, User.Read and offline_access, and this redirect URI. Each person then connects their own mailbox in Settings; Relay can only send as them.'),
      h('div', {class: 'row', style: 'margin:8px 0'}, h('code', {class: 'mono'}, e.redirect_uri), copyBtn(e.redirect_uri)),
      h('label', {class: 'f'}, 'Client ID'), cid, h('label', {class: 'f'}, 'Tenant'), ten, h('div', {class: 'hint'}, 'Your tenant ID or domain; “organizations” accepts any work account.'),
      h('label', {class: 'f'}, 'Client secret'), sec,
      h('div', {class: 'row', style: 'justify-content:flex-end;margin-top:10px'}, h('button', {class: 'btn primary', onclick: async () => {
        try { await api('/api/admin/email', {method: 'PUT', json: {client_id: cid.value, tenant: ten.value, client_secret: sec.value || null}}); notify('Saved', 'ok'); reAdmin(); } catch (err) { notify(err.message, 'err'); } }}, 'Save'))),
    h('div', {class: 'card flat'}, h('h3', {}, 'Every schedule'),
      s.schedules.length ? h('table', {class: 'utable'}, h('tr', {}, ['Name', 'Owner', 'Kind', 'When', 'Status', 'Last run'].map(t => h('th', {class: 'l'}, t))),
        s.schedules.map(x => h('tr', {}, h('td', {}, x.name), h('td', {}, x.owner), h('td', {}, x.kind), h('td', {}, x.when),
          h('td', {}, x.status === 'paused' ? h('span', {class: 'tag err', title: x.paused_reason || ''}, 'paused') : h('span', {class: 'tag ok'}, 'active')),
          h('td', {}, x.last_run ? `${when(x.last_run)} · ${x.last_status}` : '—'))))
        : h('div', {class: 'muted small'}, 'No schedules yet.'),
      s.accounts.length ? h('div', {class: 'hint', style: 'margin-top:10px'}, `Email accounts: ${s.accounts.map(a => `${a.address} (${a.owner}, ${a.status})`).join(' · ')}`) : null));
}
