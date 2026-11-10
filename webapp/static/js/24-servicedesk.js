/* ---------------- Service desk (P12): Jira / Freshservice tickets summarised, duplicates grouped, priority from business
   impact with the reason, routed to an agent or a person, turned into work - summary and priority written back only
   after a person accepts the group's checkpoint (GET/POST /api/servicedesk/…) ---------------- */
const SD_PRI = {P1: ['P1 · Critical', 'err'], P2: ['P2 · High', 'you'], P3: ['P3 · Medium', 'info'], P4: ['P4 · Low', 'mute']};
const SD_STATUS_CLS = {open: 'mute', awaiting: 'you', sent_back: 'err', written: 'ok', partly: 'you', sent: 'info', handed: 'ok', closed: 'mute'};
const SD_SRC_CLS = {ok: 'ok', sign_in: 'err', error: 'err', paused: 'mute', new: 'mute'};
const sdPill = (text, cls) => h('span', {class: 'pill plain ' + (cls || 'mute')}, text);
const sdPri = p => sdPill((SD_PRI[p] || [p, 'mute'])[0], (SD_PRI[p] || [p, 'mute'])[1]);
const sdRoute = r => r === 'agent' ? sdPill('Agent can handle', 'info') : sdPill('Needs a person', 'you');
const sdIn = t => { if (!t) return '—'; const m = Math.round((t - Date.now() / 1000) / 60); return m <= 0 ? 'now' : m < 60 ? `in ${m} min` : `in ${Math.round(m / 60)} h`; };
const sdSla = t => { if (!t) return '—'; const hrs = (t - Date.now() / 1000) / 3600; return hrs < 0 ? `breached ${fmtN(-hrs, 0)} h ago` : hrs < 48 ? `${fmtN(hrs, 0)} h left` : when(t); };
function sdStyles() {
  if (document.getElementById('sd-css')) return;
  document.head.append(h('style', {id: 'sd-css'}, '.sd-g4{display:grid;gap:14px;grid-template-columns:repeat(4,minmax(0,1fr))}' +
    '@media(max-width:1200px){.sd-g4{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:760px){.sd-g4{grid-template-columns:1fr}}' +
    '.sd-row{cursor:pointer}.sd-row:hover td{background:var(--surface-2)}.sd-row td{vertical-align:top}.sd-row a{color:var(--ink);font-weight:600;text-decoration:none}.sd-row a:hover{color:var(--accent)}' +
    '.sd-src{display:flex;flex-direction:column;gap:6px}.sd-chips{display:flex;gap:6px;flex-wrap:wrap}.sd-chips .chipx{font-size:12px}' +
    '.sd-why{display:grid;gap:8px;grid-template-columns:1fr;margin:10px 0}.sd-why b{display:block;margin-bottom:2px}'));
}
async function renderServiceDesk() {
  sdStyles();
  const main = $('#main');
  if (!$('#sdpage')) main.replaceChildren(skel('page'));
  let d;
  try { d = await api('/api/servicedesk'); } catch (e) { main.replaceChildren(h('div', {class: 'page'}, h('div', {class: 'note err'}, e.message))); return; }
  if (!location.hash.startsWith('#/servicedesk')) return;
  const me = S.me || {}, s = d.summary, canEdit = !!d.can_edit;
  const filter = S.sdFilter || 'all';
  const bySource = s.by_source.map(x => `${x.label} ${fmtN(x.open, 0)}`).join(' · ');
  const groups = d.groups.filter(g => filter === 'all' ? true : filter === 'act' ? ['open', 'awaiting', 'sent_back'].includes(g.status) : filter === 'agent' ? g.route === 'agent' && ['open', 'awaiting', 'sent_back'].includes(g.status) : filter === 'done' ? ['written', 'partly', 'handed', 'sent'].includes(g.status) : true);
  const pct = s.open_tickets && s.groups ? Math.round(100 - s.groups * 100 / s.open_tickets) : null;
  const sourcePills = s.by_source.map(x => h('a', {class: 'pill plain ' + (SD_SRC_CLS[x.status] || 'mute'), href: '#/servicedesk', title: x.status_label, onclick: e => { e.preventDefault(); document.getElementById('sd-sources').scrollIntoView({behavior: 'smooth'}); }},
    `${x.name} · ${x.status_label}`));
  const head = pageHead({crumbs: [['Home', '#/'], ['Service desk']], eyebrow: brandName() + ' · Service desk', title: 'Tickets, summarised and grouped',
    promise: 'Jira, Freshservice and ServiceNow tickets for the data & analytics team, read by an agent: summarised, duplicates grouped, priority set by business impact, and routed — nothing is written back without your approval.',
    actions: h('div', {class: 'row', style: 'gap:8px;justify-content:flex-end'}, sourcePills, canEdit ? h('button', {class: 'btn primary', onclick: () => sdSourceEditor(d)}, icon('plus'), 'Add a source') : null)});
  const kpis = h('div', {class: 'sd-g4'},
    kpiTile('Open tickets', fmtN(s.open_tickets, 0), bySource || 'no source connected yet'),
    kpiTile('Groups to act on', fmtN(s.to_act, 0), s.open_tickets ? `${fmtN(s.open_tickets, 0)} tickets → ${fmtN(s.groups, 0)} pieces of work` : 'duplicates and same-cause tickets clubbed', pct != null && pct > 0 ? {delta: `−${pct} % to read`, good: true} : {}),
    kpiTile('An agent can handle', fmtN(s.agent, 0), 'access, refresh fixes, known issues'),
    kpiTile('Near SLA breach', fmtN(s.near_sla, 0), `tickets due within ${fmtN(d.near_sla_h, 0)} h`));
  const empty = h('div', {class: 'card empty'}, h('h3', {}, 'Connect Jira, Freshservice or ServiceNow'),
    h('div', {class: 'muted'}, 'Give a limited service account and the projects or queues to read. Tickets are read every few minutes; nothing is written back without your approval.'),
    canEdit ? h('div', {style: 'margin-top:14px'}, h('button', {class: 'btn primary', onclick: () => sdSourceEditor(d)}, icon('plug'), 'Add a source')) : h('div', {class: 'small muted', style: 'margin-top:10px'}, 'A BI Dev or an admin connects the sources.'));
  const seg = h('div', {class: 'segbtn', role: 'group', 'aria-label': 'Show'}, [['all', 'All'], ['act', 'To act on'], ['agent', 'Agent can handle'], ['done', 'Done']].map(([k, l]) =>
    h('button', {class: filter === k ? 'on' : '', 'aria-pressed': String(filter === k), onclick: () => { S.sdFilter = k; renderServiceDesk(); }}, l)));
  const row = g => h('tr', {class: 'sd-row', onclick: e => { if (e.target.closest('a, button')) return; sdOpenGroup(g.id, d); }},
    h('td', {}, h('a', {href: '#/servicedesk/' + g.id, onclick: e => { e.preventDefault(); sdOpenGroup(g.id, d); }}, g.title), h('div', {class: 'small muted'}, g.summary),
      g.note ? h('div', {class: 'small', style: 'color:var(--warn);margin-top:2px'}, g.note) : null),
    h('td', {class: 'n'}, fmtN(g.tickets, 0)), h('td', {}, g.team || '—'), h('td', {}, sdPri(g.priority)), h('td', {}, sdRoute(g.route)),
    h('td', {}, g.target_label || '—'), h('td', {}, sdPill(g.status_label, SD_STATUS_CLS[g.status])));
  const table = h('div', {class: 'card', style: 'padding:0;overflow:auto;margin:0'}, h('table', {class: 'utable'},
    h('tr', {}, [['Group', 1], ['Tickets', 0], ['Team', 1], ['Priority', 1], ['Route', 1], ['Goes to', 1], ['Status', 1]].map(([t, l]) => h('th', {class: l ? 'l' : ''}, t))),
    groups.length ? groups.map(row) : h('tr', {}, h('td', {colspan: 7, class: 'muted', style: 'padding:18px'}, d.groups.length ? 'Nothing matches this filter.' : 'No open tickets have been read yet. Press “Read now” on a source.'))));
  const q = d.quality;
  const quality = h('div', {class: 'card', style: 'margin:0'}, h('div', {class: 'card-head'}, h('h3', {}, 'Quality'), h('span', {class: 'sp'}), h('span', {class: 'small muted'}, 'grouping vs the labelled fixture')),
    q ? [h('div', {class: 'g3', style: 'gap:10px'}, [['Precision', q.precision], ['Recall', q.recall], ['F1', q.f1]].map(([l, v]) => h('div', {class: 'mini'}, h('div', {class: 'mv'}, fmtN(v * 100, 1) + ' %'), h('div', {class: 'small muted'}, l)))),
      h('div', {class: 'small muted', style: 'margin-top:10px'}, `${fmtN(q.labelled, 0)} labelled tickets of ${fmtN(q.of, 0)} · ${fmtN(q.groups_true, 0)} true groups, ${fmtN(q.groups_predicted, 0)} formed · pairs of tickets put together rightly vs the labels`)]
      : h('div', {class: 'muted small', style: 'padding:8px 0'}, 'No labelled tickets read yet. The mock lab’s Jira and Freshservice simulators carry the true duplicate groups, so precision and recall can be measured here; a real queue has no labels.'));
  const work = h('div', {class: 'card', style: 'margin:0'}, h('div', {class: 'card-head'}, h('h3', {}, 'Turned into work'), h('span', {class: 'sp'}), h('span', {class: 'small muted'}, `${d.work.length} recent`)),
    d.work.length ? h('div', {class: 'stack', style: 'gap:6px'}, d.work.slice(0, 8).map(w => h('a', {href: w.link || '#/servicedesk', class: 'wait'},
      h('div', {class: 'wt'}, h('b', {}, w.target_label), h('small', {}, `${w.status === 'created' ? 'created' : 'recorded until the module ships'} · ${ago(w.created)}`)), sdPill(w.status === 'created' ? 'Created' : 'Recorded', w.status === 'created' ? 'ok' : 'mute'))))
      : h('div', {class: 'muted small', style: 'padding:8px 0'}, 'Nothing handed over yet. Open a group and choose “Turn into work”.'));
  const srcCard = x => h('div', {class: 'card sd-src', style: 'margin:0'},
    h('div', {class: 'row', style: 'flex-wrap:nowrap;align-items:flex-start'}, h('div', {style: 'flex:1;min-width:0'}, h('h3', {style: 'margin:0'}, x.name), h('div', {class: 'small muted'}, `${x.label} · ${x.base_url}`)), sdPill(x.status_label, SD_SRC_CLS[x.paused ? 'paused' : x.status])),
    h('div', {class: 'sd-chips'}, (x.projects.length ? x.projects : ['every project or queue the account can see']).map(p => h('span', {class: 'chipx'}, p))),
    h('div', {class: 'row small', style: 'gap:8px'}, h('span', {class: 'muted'}, 'May do:'), sdPill(x.scope_label || 'Read-only', x.scope === 'read' ? 'mute' : 'info'),   // consolidation: read-only unless granted; every write still approved
      x.can_grant ? h('button', {class: 'btn sm ghost', type: 'button', onclick: () => sdScopeDialog(x, d)}, 'Change') : null),
    h('div', {class: 'small muted'}, `Last read ${x.last_read ? ago(x.last_read) : 'never'} · next ${x.paused ? 'paused' : sdIn(x.next_read)} · every ${x.poll_min} min · ${fmtN(x.open_tickets, 0)} open · ${fmtN(x.reads, 0)} reads` + (x.retries ? ` · ${x.retries} retries after rate limits or server errors` : '')),
    x.error ? h('div', {class: 'note err', style: 'margin:4px 0 0'}, x.status === 'sign_in' ? 'Sign in again: ' : '', x.error) : null,
    canEdit ? h('div', {class: 'row', style: 'gap:6px'},
      h('button', {class: 'btn sm primary', onclick: () => sdAct(`/api/servicedesk/sources/${x.id}/read`, r => r.ok ? `Read ${fmtN(r.open, 0)} open tickets · ${fmtN(r.groups, 0)} groups` : (r.error || 'The read failed'), d)}, icon('play'), 'Read now'),
      h('button', {class: 'btn sm', onclick: () => sdAct(`/api/servicedesk/sources/${x.id}/test`, r => r.ok ? `Connected as ${r.account}` : (r.error || 'Not connected'), d)}, 'Test'),
      h('button', {class: 'btn sm', onclick: () => sdAct(`/api/servicedesk/sources/${x.id}/pause`, () => x.paused ? 'Reading again' : 'Paused', d, {paused: !x.paused})}, x.paused ? 'Resume' : 'Pause'),
      h('button', {class: 'btn sm', onclick: () => sdSourceEditor(d, x)}, 'Edit'),
      h('button', {class: 'btn sm ghost', onclick: async () => { if (await confirmBox('Remove this source?', `${x.name} and its cached tickets are removed; the stored credential is deleted. Nothing changes on the service desk itself.`)) { try { await api(`/api/servicedesk/sources/${x.id}`, {method: 'DELETE'}); notify('Source removed', 'ok'); renderServiceDesk(); } catch (e) { notify(e.message, 'err'); } } }}, 'Remove')) : null);
  // a service desk that is listed but not connectable yet shows as "Next" (none today: ServiceNow is connectable since the consolidation)
  const nextCard = Object.values(d.kinds).filter(k => !k.connectable).map(k => h('div', {class: 'card sd-src', style: 'margin:0;opacity:.85'},
    h('div', {class: 'row', style: 'flex-wrap:nowrap;align-items:flex-start'}, h('div', {style: 'flex:1'}, h('h3', {style: 'margin:0'}, k.label), h('div', {class: 'small muted'}, 'Listed, not connectable yet')), sdPill('Next', 'outline')),
    h('div', {class: 'small muted'}, k.note || '')));
  // consolidation: what other modules asked the service desk to write (each after its own approval), and the ticket drafts waiting for a source
  const writes = d.writes || [], drafts = d.drafts || [];
  const writesCard = h('div', {class: 'card', style: 'margin:0'}, h('div', {class: 'card-head'}, h('h3', {}, 'Written for other modules'), h('span', {class: 'sp'}), h('span', {class: 'small muted'}, 'new tickets and comments, each approved')),
    writes.length ? h('div', {class: 'stack', style: 'gap:6px'}, writes.slice(0, 8).map(w => h('button', {class: 'wait', type: 'button', style: 'text-align:left;width:100%', onclick: () => sdWriteDialog(w)},
      h('div', {class: 'wt'}, h('b', {}, w.title), h('small', {}, `${w.op_label} · ${w.source} · for ${w.module} · ${ago(w.created)}`)), sdPill(w.status === 'written' && w.result ? `${w.result.key}` : w.status_label, SD_WRITE_CLS[w.status] || 'mute'))))
      : h('div', {class: 'muted small', style: 'padding:8px 0'}, 'Nothing yet. When Data observability, Integration analytics or AI SDLC need a ticket or a comment, it waits here and in the Validation queue for a named person.'));
  const draftsCard = drafts.length ? h('div', {class: 'card', style: 'margin:0'}, h('div', {class: 'card-head'}, h('h3', {}, 'Ticket drafts'), h('span', {class: 'sp'}), h('span', {class: 'small muted'}, `${drafts.length} waiting for a source`)),
    h('div', {class: 'stack', style: 'gap:8px'}, drafts.slice(0, 8).map(x => h('div', {class: 'row', style: 'gap:8px;flex-wrap:nowrap;align-items:flex-start'},
      h('div', {style: 'flex:1;min-width:0'}, h('b', {}, x.title), h('div', {class: 'small muted'}, `${x.module} · ${(SD_PRI[x.priority] || [x.priority])[0]} · approved ${ago(x.created)}`), x.cause ? h('div', {class: 'small muted'}, x.cause.slice(0, 160)) : null),
      h('a', {class: 'btn sm ghost', href: x.link, 'aria-label': `Open ${x.title} in ${x.module}`}, 'Open'),
      canEdit ? h('button', {class: 'btn sm primary', type: 'button', disabled: !d.ticket_target, title: d.ticket_target ? '' : 'No source may raise tickets yet', onclick: () => sdRaise(x, d)}, 'Raise it') : null))),
    d.ticket_target ? h('div', {class: 'small muted', style: 'margin-top:8px'}, `“Raise it” asks a named person to approve the ticket on ${d.ticket_target}; nothing is written before.`)
      : h('div', {class: 'hint'}, 'No source may raise tickets yet: an admin, or the person who added a source, sets its “May do” to Read & write — with approval.')) : null;
  main.replaceChildren(h('div', {class: 'page', id: 'sdpage'},
    head, kpis,
    s.sources ? [
      h('div', {class: 'section-title', style: 'margin-top:18px'}, h('h2', {}, 'Groups by business impact'), h('span', {class: 'hint'}, `${groups.length} of ${d.groups.length}`), h('span', {class: 'sp'}), seg),
      canEdit ? null : h('div', {class: 'note', style: 'margin:0 0 10px'}, 'You can read the queue. A BI Dev or an admin accepts write-backs, sends groups to people and turns them into work.'),
      table,
      h('div', {class: 'g2', style: 'margin-top:16px'}, quality, work),
      h('div', {class: 'g2', style: 'margin-top:16px'}, writesCard, draftsCard)]
      : [empty, drafts.length ? h('div', {style: 'margin-top:16px'}, draftsCard) : null],
    h('div', {class: 'section-title', id: 'sd-sources', style: 'margin-top:18px'}, h('h2', {}, 'Sources'), h('span', {class: 'hint'}, `${s.sources} connected`)),
    h('div', {class: 'g3'}, d.sources.map(srcCard), nextCard),
    h('div', {class: 'g3', style: 'margin-top:16px'},
      h('div', {class: 'card', style: 'margin:0'}, h('h3', {}, 'Read'), h('p', {class: 'small muted'}, 'New and updated tickets every few minutes, with comments and attachments, using a service account limited to the data & analytics queues.')),
      h('div', {class: 'card', style: 'margin:0'}, h('h3', {}, 'Understand'), h('p', {class: 'small muted'}, 'Summary in two lines, duplicates grouped, priority from business impact (who is blocked, which report, which deadline), with the reason shown.')),
      h('div', {class: 'card', style: 'margin:0'}, h('h3', {}, 'Act'), h('p', {class: 'small muted'}, 'Route to an agent (access, refresh fixes) or a person; turn the group into work; write back to the tickets only after approval.')))));
  document.title = `Service desk · ${S.brand ? S.brand.full : 'RELAY by PASDACS'}`;
  const gid = (location.hash.match(/^#\/servicedesk\/(g-[0-9a-f]+)/) || [])[1];
  if (gid && !document.querySelector('.modal')) sdOpenGroup(gid, d);
  const wid = new URLSearchParams(location.hash.split('?')[1] || '').get('write');    // a write's link from the Validation queue
  const wr = wid && writes.find(w => w.id === wid);
  if (wr && !document.querySelector('.modal')) sdWriteDialog(wr);
}
const SD_WRITE_CLS = {waiting: 'you', written: 'ok', failed: 'err', refused: 'err', sent_back: 'mute', withdrawn: 'mute'};
function sdWriteDialog(w) {
  const rows = w.op === 'create' ? [['Where', `${w.source}${w.payload.project ? ' · ' + w.payload.project : ''}`], ['Title', w.payload.title], ['Priority', (SD_PRI[w.payload.priority] || [w.payload.priority])[0]],
    ['Labels', (w.payload.labels || []).join(', ')], ['Description', w.payload.description]] : [['Ticket', w.payload.key], ['Comment', w.payload.text]];
  const m = modal(`${w.op_label}: ${w.title}`, h('div', {class: 'mbody'},
    h('div', {class: 'row', style: 'gap:8px'}, sdPill(w.status_label, SD_WRITE_CLS[w.status] || 'mute'), h('span', {class: 'small muted'}, `for ${w.module} · asked ${ago(w.created)}${w.requested_by_name ? ' by ' + w.requested_by_name : ''}`)),
    w.error ? h('div', {class: 'note ' + (w.status === 'sent_back' ? '' : 'err'), style: 'margin:10px 0 0'}, w.error) : null,
    h('dl', {class: 'kv-list', style: 'grid-template-columns:110px 1fr;margin-top:12px'}, rows.flatMap(([k, v]) => [h('dt', {}, k), h('dd', {style: 'white-space:pre-wrap'}, v || '—')])),
    w.status === 'written' && w.result ? h('div', {class: 'note ok', style: 'margin:10px 0 0'}, `Written ${when(w.written)}${w.decided_by_name ? ', approved by ' + w.decided_by_name : ''}: `,
      w.result.url ? h('a', {href: w.result.url, target: '_blank', rel: 'noopener'}, w.result.key || 'open it') : (w.result.key || '')) : null,
    h('div', {class: 'row', style: 'justify-content:flex-end;gap:8px;margin-top:12px'}, w.link ? h('a', {class: 'btn', href: w.link, onclick: () => m.remove()}, `Open in ${w.module}`) : null,
      w.status === 'waiting' ? h('a', {class: 'btn primary', href: '#/validate', onclick: () => m.remove()}, 'Decide in the queue') : null)));
  new MutationObserver((_, o) => { if (!m.isConnected) { o.disconnect(); if (location.hash.includes('write=')) history.replaceState(null, '', '#/servicedesk'); } }).observe(document.body, {childList: true});
}
async function sdRaise(x, d) {
  if (!await confirmBox('Raise this ticket?', `A ticket for “${x.title}” goes to the Validation queue first: a named person approves exactly what is written to ${d.ticket_target}.`, 'Ask for approval', false)) return;
  try { await api('/api/servicedesk/drafts/raise', {json: {origin: x.origin}}); notify('Waiting for approval in the Validation queue', 'ok'); renderServiceDesk(); }
  catch (e) { notify(e.message, 'err'); }
}
function sdScopeDialog(x, d) {
  let scope = x.scope || 'read';
  const opts = {...(x.options || {})};
  const fields = Object.entries((d.options || {})[x.kind] || {}).map(([k, l]) => { const el = h('input', {type: 'text', value: opts[k] || '', placeholder: l}); el.oninput = () => { opts[k] = el.value; };
    return h('div', {}, h('label', {class: 'f'}, l, h('small', {}, 'optional')), el); });
  const radios = h('div', {class: 'stack', style: 'gap:6px'}, Object.entries(d.scopes || {}).map(([k, t]) => { const r = h('input', {type: 'radio', name: 'sdscope', checked: k === scope});
    r.onchange = () => { scope = k; [...radios.children].forEach(el => el.classList.toggle('on', el.querySelector('input').checked)); };
    return h('label', {class: 'radio' + (k === scope ? ' on' : '')}, r, h('span', {}, h('b', {}, t), h('small', {}, {read: 'Relay only reads the queues (recommended to start)', comment: 'also comments and notes: the triage summary, a pull request link',
      write: 'also new tickets and the triage priority — each change approved by a named person'}[k] || ''))); }));
  const m = modal(`What may Relay write to ${x.name}?`, h('div', {class: 'mbody'}, radios,
    h('div', {class: 'hint'}, 'Whatever you allow, every single write waits in the Validation queue for a named person, who sees exactly what will be written.'),
    h('details', {class: 'more', style: 'margin-top:10px', open: scope === 'write'}, h('summary', {}, 'How new tickets are raised'), fields),
    h('div', {class: 'row', style: 'justify-content:flex-end;gap:8px;margin-top:12px'}, h('button', {class: 'btn', type: 'button', onclick: () => m.remove()}, 'Cancel'),
      h('button', {class: 'btn primary', type: 'button', onclick: async () => { try { await api(`/api/servicedesk/sources/${x.id}/scope`, {method: 'PUT', json: {scope, options: opts}}); m.remove(); notify('Saved — audited', 'ok'); renderServiceDesk(); } catch (e) { notify(e.message, 'err'); } }}, 'Save'))));
}
async function sdAct(path, text, d, body) {
  try { const r = await api(path, {json: body || {}}); const t = text(r); notify(t, r.ok === false ? 'err' : 'ok'); renderServiceDesk(); }
  catch (e) { notify(e.message, 'err'); }
}
function sdSourceEditor(d, x) {
  const kinds = Object.entries(d.kinds);
  const v = {kind: x ? x.kind : 'jira', name: x ? x.name : '', base_url: x ? x.base_url : '', account: x ? x.account || '' : '', projects: x ? x.projects.join(', ') : '', poll_min: x ? x.poll_min : 5, token: ''};
  const kindSel = h('select', {class: 'sel', disabled: !!x}, kinds.map(([id, k]) => h('option', {value: id, selected: id === v.kind, disabled: !k.connectable}, k.label + (k.connectable ? '' : ' — next'))));
  const field = (k, ph, type) => { const el = h('input', {type: type || 'text', value: v[k], placeholder: ph || '', autocomplete: 'off'}); el.oninput = () => { v[k] = type === 'number' ? +el.value : el.value; }; return el; };
  const accountIn = field('account', 'service-account e-mail (Jira API token)'), tokenIn = field('token', x && x.has_secret ? 'Stored — leave empty to keep' : 'kept in the secrets store, by name', 'password');
  const accountLab = h('label', {class: 'f'}, 'Service account'), tokenLab = h('label', {class: 'f'}, 'API token');
  const projLab = h('label', {class: 'f'}, 'Projects to read', h('small', {}, 'comma-separated'));
  const urlIn = field('base_url', d.kinds[v.kind].url_hint);
  const sync = () => { const k = d.kinds[kindSel.value]; v.kind = kindSel.value; accountLab.style.display = k.account_label ? '' : 'none'; accountIn.style.display = k.account_label ? '' : 'none';
    accountLab.textContent = k.account_label || ''; tokenLab.textContent = k.secret_label || 'Token'; projLab.firstChild.textContent = k.projects_label; urlIn.placeholder = k.url_hint; };
  kindSel.onchange = sync; sync();
  const save = async test => {
    const body = {...v, projects: v.projects};
    try {
      const r = await api(x ? `/api/servicedesk/sources/${x.id}` : '/api/servicedesk/sources', {method: x ? 'PUT' : 'POST', json: body});
      m.remove();
      if (test) { const t = await api(`/api/servicedesk/sources/${r.id}/test`, {json: {}}); notify(t.ok ? `Connected as ${t.account}` : (t.error || 'Not connected'), t.ok ? 'ok' : 'err'); }
      else notify(x ? 'Source saved' : 'Source added — press “Read now” or wait for the next read', 'ok');
      renderServiceDesk();
    } catch (e) { notify(e.message, 'err'); }
  };
  const m = modal(x ? `Edit source: ${x.name}` : 'Add a service desk source', h('div', {class: 'mbody'},
    h('label', {class: 'f'}, 'Service desk'), kindSel,
    h('label', {class: 'f'}, 'Name', h('small', {}, 'as shown here')), field('name', 'Jira · DATA project'),
    h('label', {class: 'f'}, 'Base URL'), urlIn,
    accountLab, accountIn, tokenLab, tokenIn,
    projLab, field('projects', 'DATA, BI'),
    h('label', {class: 'f'}, 'Read every', h('small', {}, 'minutes')), field('poll_min', '5', 'number'),
    h('div', {class: 'note', style: 'margin-top:14px'}, h('b', {}, 'Read-only by default. '), 'The account only needs to read the queues you list. What Relay may write — comments, new tickets — is set per source under “May do” once it is added, and every write still waits for a named person’s approval of exactly what is written.'),
    h('div', {class: 'row', style: 'justify-content:flex-end;margin-top:12px'}, h('button', {class: 'btn', onclick: () => save(true)}, 'Save & test'), h('button', {class: 'btn primary', onclick: () => save(false)}, x ? 'Save' : 'Add source'))));
}
async function sdOpenGroup(gid, d) {
  let g;
  try { g = await api(`/api/servicedesk/groups/${gid}`); } catch (e) { notify(e.message, 'err'); return; }
  history.replaceState(null, '', '#/servicedesk/' + gid);
  const canEdit = !!d.can_edit, acting = ['open', 'awaiting', 'sent_back', 'sent', 'partly'].includes(g.status);
  const srcName = t => t.source || '';
  const tickets = h('div', {style: 'overflow:auto;margin-top:12px'}, h('table', {class: 'utable'},
    h('tr', {}, ['Ticket', 'Source', 'Title', 'Reporter', 'Team', 'Opened', 'SLA'].map(t => h('th', {class: 'l'}, t))),
    g.ticket_list.map(t => h('tr', {}, h('td', {}, t.url ? h('a', {href: t.url, target: '_blank', rel: 'noopener'}, t.key) : t.key), h('td', {}, srcName(t)), h('td', {}, t.title),
      h('td', {}, t.reporter || '—'), h('td', {}, t.team || '—'), h('td', {}, when(t.created)), h('td', {}, sdSla(t.due))))));
  const decisions = g.decisions.length ? h('details', {class: 'astable', style: 'margin-top:10px'}, h('summary', {}, `What happened (${g.decisions.length})`),
    h('ul', {class: 'small', style: 'margin:6px 0 0;padding-left:18px'}, g.decisions.map(x => h('li', {}, `${when(x.ts)} · ${x.action.replace('_', ' ')} · ${x.who_name || 'Relay'}` +
      (x.detail && x.detail.written ? ` · ${x.detail.written.length} tickets written` : '') + (x.detail && x.detail.comment ? ` · “${x.detail.comment}”` : '') + (x.detail && x.detail.target ? ` · ${x.detail.target}` : ''))))) : null;
  const close = () => { m.remove(); history.replaceState(null, '', '#/servicedesk'); };
  const refresh = () => { close(); renderServiceDesk(); };
  const accept = async () => {
    if (!await confirmBox('Accept and write back?', `The summary, the priority ${g.priority} and the group link are written to ${g.tickets} ticket${g.tickets === 1 ? '' : 's'} on the service desk, signed with your name. Send it back from the Validation queue instead if something is wrong.`, 'Accept & write back', false)) return;
    try { const r = await api(`/api/servicedesk/groups/${gid}/accept`, {json: {}}); const gg = r.group; notify(gg.status === 'written' ? `Written back to ${g.tickets} ticket${g.tickets === 1 ? '' : 's'}` : (gg.note || 'Partly written back'), gg.status === 'written' ? 'ok' : 'err'); refresh(); }
    catch (e) { notify(e.message, 'err'); }
  };
  const queue = async () => { try { await api(`/api/servicedesk/groups/${gid}/checkpoint`, {json: {}}); notify('Added to the Validation queue', 'ok'); refresh(); } catch (e) { notify(e.message, 'err'); } };
  const person = async () => {
    const dir = await api('/api/directory');
    const sel = h('select', {class: 'sel'}, dir.users.map(u => h('option', {value: u.id}, `${u.name} · ${u.email}`)));
    const ta = h('textarea', {rows: 3, placeholder: 'A note for them (optional)'});
    const ok = h('button', {class: 'btn primary', onclick: async () => { try { await api(`/api/servicedesk/groups/${gid}/person`, {json: {to: sel.value, note: ta.value}}); mm.remove(); notify('Sent — they have been told', 'ok'); refresh(); } catch (e) { notify(e.message, 'err'); } }}, 'Send');
    const mm = modal(`Send to a person: ${g.title}`, h('div', {class: 'mbody'}, h('label', {class: 'f'}, 'To'), sel, h('label', {class: 'f'}, 'Note'), ta, h('div', {class: 'row', style: 'justify-content:flex-end;margin-top:12px'}, ok)));
  };
  const work = async () => {
    const targets = Object.entries(d.targets);
    const sel = h('select', {class: 'sel'}, targets.map(([id, t]) => h('option', {value: id, selected: id === g.target}, `${t.label} — ${t.what}`)));
    const projWrap = h('div', {}, h('label', {class: 'f'}, 'Dashboard', h('small', {}, 'the change request goes to it')));
    const projSel = h('select', {class: 'sel'}, h('option', {value: ''}, 'Choose a dashboard…'));
    try { (await api('/api/projects')).forEach(p => projSel.append(h('option', {value: p.id}, p.name))); } catch (e) { /* no dashboards */ }
    projWrap.append(projSel);
    const ta = h('textarea', {rows: 3, placeholder: 'What the work should do (optional)'});
    const sync = () => { projWrap.style.display = sel.value === 'd2d' ? '' : 'none'; };
    sel.onchange = sync; sync();
    const ok = h('button', {class: 'btn primary', onclick: async () => { try { const r = await api(`/api/servicedesk/groups/${gid}/work`, {json: {target: sel.value, project: projSel.value || null, note: ta.value}}); mm.remove();
      notify(r.work.status === 'created' ? `Change request created in ${r.work.target_label}` : `Recorded for ${r.work.target_label} — created when that module ships`, 'ok'); refresh(); } catch (e) { notify(e.message, 'err'); } }}, 'Turn into work');
    const mm = modal(`Turn into work: ${g.title}`, h('div', {class: 'mbody'}, h('label', {class: 'f'}, 'Where it goes'), sel, projWrap, h('label', {class: 'f'}, 'Note'), ta,
      h('div', {class: 'small muted', style: 'margin-top:8px'}, 'The group’s summary, reason and ticket keys travel with the work item.'),
      h('div', {class: 'row', style: 'justify-content:flex-end;margin-top:12px'}, ok)));
  };
  const m = modal(g.title, h('div', {class: 'mbody'},
    h('div', {class: 'row', style: 'gap:8px'}, sdPri(g.priority), sdRoute(g.route), sdPill(g.status_label, SD_STATUS_CLS[g.status]), h('span', {class: 'small muted'}, `${g.tickets} ticket${g.tickets === 1 ? '' : 's'} · ${g.people} ${g.people === 1 ? 'person' : 'people'}${g.team ? ' · ' + g.team : ''}${g.near_sla ? ` · ${g.near_sla} near SLA breach` : ''}`)),
    h('div', {class: 'note', style: 'margin:12px 0'}, h('b', {}, 'Summary: '), g.summary),
    h('div', {class: 'sd-why'}, h('div', {}, h('b', {}, `Why ${g.priority}`), h('span', {class: 'muted'}, g.reason)), h('div', {}, h('b', {}, 'Route'), h('span', {class: 'muted'}, g.route_reason)),
      h('div', {}, h('b', {}, 'Goes to'), h('span', {class: 'muted'}, `${g.target_label} — ${(d.targets[g.target] || {}).what || ''}`)),
      g.note ? h('div', {}, h('b', {}, 'Note'), h('span', {style: 'color:var(--warn)'}, g.note)) : null,
      g.written ? h('div', {}, h('b', {}, 'Written back'), h('span', {class: 'muted'}, `${when(g.written)} by ${g.written_by_name || 'a person'}`)) : null,
      g.writable === false ? h('div', {}, h('b', {}, 'Read-only'), h('span', {class: 'muted'}, 'These tickets’ sources are read-only: nothing is written back until an admin, or the person who added the source, allows comments (Sources › May do).')) : null),
    tickets, decisions,
    canEdit ? h('div', {class: 'row', style: 'margin-top:16px;gap:8px'},
      acting && g.status !== 'written' && g.writable !== false ? h('button', {class: 'btn primary', onclick: accept}, icon('check'), 'Accept & write back') : null,
      (g.status === 'open' || g.status === 'sent_back') && g.writable !== false ? h('button', {class: 'btn', onclick: queue}, 'Ask the queue') : null,
      g.status === 'awaiting' ? h('a', {class: 'btn', href: '#/validate'}, 'Open in the queue') : null,
      h('button', {class: 'btn', onclick: person}, icon('user'), 'Send to a person'),
      h('button', {class: 'btn', onclick: work}, icon('external'), 'Turn into work'))
      : h('div', {class: 'small muted', style: 'margin-top:14px'}, 'Read-only: a BI Dev or an admin acts on this group.'),
    h('div', {class: 'small muted', style: 'margin-top:10px'}, 'Accepting writes the summary and the group link — and the priority where the source allows writes — to every ticket here whose source allows comments, signed with your name; it is recorded as a checkpoint in the Validation queue.')), true);
  // however the dialog closes (Close, Escape, backdrop, an action), the address goes back to the list
  new MutationObserver((_, o) => { if (!m.isConnected) { o.disconnect(); if (location.hash.startsWith('#/servicedesk/')) history.replaceState(null, '', '#/servicedesk'); } }).observe(document.body, {childList: true});
}
