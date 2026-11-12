/* ---------------- Integration analytics (P13): every integration discovered across the sources, mapped and watched;
   "act before it breaks" with a person's approval; sources and the RACI table (GET /api/intan/overview) ---------------- */
const IA = {filter: 'all', q: '', source: '', type: '', open: null, timer: null};
const HEALTH_PILL = {Healthy: 'ok', 'At risk': 'you', Degraded: 'you', Failing: 'err', 'No owner': 'mute', Unknown: 'mute'};
const healthPill = s => h('span', {class: 'pill plain ' + (HEALTH_PILL[s] || 'mute')}, s || 'Unknown');
const SRC_PILL = {ok: ['Scanned', 'ok'], new: ['Not scanned yet', 'mute'], error: ['Needs attention', 'err'], paused: ['Paused', 'mute']};
const srcPill = s => { const [t, c] = SRC_PILL[s] || [s, 'mute']; return h('span', {class: 'pill plain ' + c}, t); };
const ROUTE_BTN = {ticket: ['bell', 'Raise ticket'], heal: ['heart', 'Self-healing'], sdlc: ['code', 'Fix with AI SDLC'], owner: ['users', 'Assign an owner']};
const pct = v => v == null ? '-' : fmtN(v) + ' %';
const durText = s => s == null ? '-' : s < 10 ? `${fmtN(s)} s` : s < 90 ? `${Math.round(s)} s` : s < 5400 ? `${Math.round(s / 60)} min` : `${fmtN(s / 3600)} h`;

async function renderIntegrations() {
  const main = $('#main');
  clearTimeout(IA.timer);
  if (!$('#intanpage')) main.replaceChildren(h('div', {class: 'page'}, pageHead({crumbs: [['Home', '#/'], ['All modules', '#/modules'], ['Integration analytics']], eyebrow: brandName() + ' - Systems - Integration analytics', title: 'Every integration, mapped and watched'}), skel('cards')));
  const qp = hashParams();
  if (qp.get('open')) IA.open = qp.get('open');
  let d, items;
  try { [d, items] = await Promise.all([api('/api/intan/overview'), api('/api/intan/integrations')]); items = items.items; }
  catch (e) { main.replaceChildren(h('div', {class: 'page'}, h('div', {class: 'note err'}, e.message))); return; }
  if (!location.hash.startsWith('#/integrations')) return;
  const me = S.me || {}, builder = !!me.builder, k = d.kpis, scanning = ['queued', 'scanning'].includes(d.scan.status);
  const head = pageHead({crumbs: [['Home', '#/'], ['All modules', '#/modules'], ['Integration analytics']], eyebrow: brandName() + ' - Systems - Integration analytics', title: 'Every integration, mapped and watched',
    promise: 'What runs between your systems - APIs, flows, bots, pipelines and file transfers - whether it is healthy, what is about to break, and one click to a ticket or a fix you approve.',
    actions: [scanning ? h('span', {class: 'pill run'}, 'Scanning...') : d.sources.length ? h('span', {class: 'pill plain ' + (d.sources.some(s => s.status === 'error') ? 'err' : 'ok')}, `${k.scanned} of ${k.sources} source${k.sources === 1 ? '' : 's'} scanned`) : null,
      builder && d.sources.length ? h('button', {class: 'btn', type: 'button', disabled: scanning, onclick: async () => { try { await api('/api/intan/scan', {method: 'POST'}); notify('Discovery queued - the sources are read again, read-only', 'ok'); renderIntegrations(); } catch (e) { notify(e.message, 'err'); } }}, icon('search'), 'Discover again') : null,
      h('button', {class: 'btn' + (d.sources.length ? '' : ' primary'), type: 'button', onclick: () => sourcesDialog(d)}, icon('plug'), d.sources.length ? 'Sources' : 'Add a source')]});
  if (!d.sources.length) {
    main.replaceChildren(h('div', {class: 'page', id: 'intanpage'}, head,
      h('div', {class: 'card empty'}, h('h3', {}, 'No sources yet'), h('div', {class: 'muted', style: 'max-width:620px;margin:0 auto'}, 'Point Relay at the tools that run your integrations - read-only, credentials by name - and it maps what talks to what, watches every run and flags what is about to break.'),
        builder ? h('div', {class: 'row', style: 'justify-content:center;margin-top:14px'}, h('button', {class: 'btn primary', type: 'button', onclick: () => sourceEditor(d, null)}, icon('plus'), 'Add a source'),
          h('button', {class: 'btn', type: 'button', onclick: async e => { e.target.disabled = true; try { const s = await api('/api/intan/sources', {json: {kind: 'sample', name: 'Sample estate'}}); await api(`/api/intan/sources/${s.id}/scan`, {method: 'POST'}); notify('Sample estate added - scanning', 'ok'); renderIntegrations(); } catch (err) { notify(err.message, 'err'); e.target.disabled = false; } }}, icon('dice'), 'Try the sample estate')) : h('div', {class: 'small muted', style: 'margin-top:10px'}, 'Ask a BI Dev / Analyst to add a source.')),
      infoCards()));
    document.title = `Integration analytics - ${S.brand ? S.brand.full : 'RELAY by PASDACS'}`;
    return;
  }
  const risky = d.risks, st = d.stats;
  const openDrawer = id => intDrawer(id, d);
  const map = lineageMap({layout: 'columns', colour: 'status', height: 460, big: true, dots: false, dimOthers: false, label: `Integration map: ${d.map.nodes.length} systems and ${d.map.edges.length} integrations, coloured by health`,
    onEdge: e => openDrawer(e.id), onSelect: n => { IA.q = n.label; renderTable(); }});
  map.draw({nodes: d.map.nodes.map(n => ({...n, badge: n.issues || 0, status: null})), edges: d.map.edges.map(e => ({...e, kind: 'feeds'}))}, {select: null});
  const kpiBox = h('div', {class: 'g5'},
    kpiTile('Integrations found', String(k.found), `${k.sources} source${k.sources === 1 ? '' : 's'} - ${k.scanned} scanned`),
    kpiTile('Healthy', String(k.healthy), k.found ? `${Math.round(100 * k.healthy / k.found)} % - runs on time, numbers in range` : 'nothing scanned yet'),
    kpiTile('At risk', String(k.at_risk), 'expiring tokens, odd volumes, upcoming changes', {href: '#/integrations?filter=At risk'}),
    kpiTile('Failing or degraded', String(k.failing), risky.filter(r => r.health === 'Failing').length ? `${risky.filter(r => r.health === 'Failing').length} failing now` : 'nothing failing now', {href: '#/integrations?filter=issues'}),
    kpiTile('No owner', String(k.no_owner), 'running, but in no inventory', {href: '#/integrations?filter=No owner'}));
  if (qp.get('filter')) IA.filter = qp.get('filter');
  const tableBox = h('div', {});
  const srcSel = h('select', {class: 'sel', 'aria-label': 'Source', style: 'width:auto', onchange: e => { IA.source = e.target.value; renderTable(); }}, h('option', {value: ''}, 'All sources'), d.sources.map(s => h('option', {value: s.id, selected: IA.source === s.id}, s.name)));
  const qIn = h('input', {type: 'search', placeholder: 'Find an integration, system or owner...', 'aria-label': 'Find an integration', value: IA.q, style: 'max-width:280px', oninput: e => { IA.q = e.target.value; renderTable(); }});
  const seg = h('div', {class: 'segbtn', role: 'group', 'aria-label': 'Filter'}, [['all', 'All'], ['issues', 'Needs attention'], ['At risk', 'At risk'], ['No owner', 'No owner']].map(([v, l]) => h('button', {type: 'button', class: IA.filter === v ? 'on' : '', 'aria-pressed': String(IA.filter === v), onclick: e => { IA.filter = v; [...e.currentTarget.parentElement.children].forEach(b => { const on = b === e.currentTarget; b.classList.toggle('on', on); b.setAttribute('aria-pressed', String(on)); }); renderTable(); }}, l)));
  const typeNote = h('span', {class: 'small muted'});
  function renderTable() {
    const rows = items.filter(i => (IA.filter === 'all' || (IA.filter === 'issues' ? i.health !== 'Healthy' : i.health === IA.filter)) && (!IA.source || i.source_id === IA.source) && (!IA.type || i.kind === IA.type)
      && (!IA.q || `${i.display_name} ${i.from_system} ${i.to_system} ${i.via} ${i.owner} ${i.kind} ${i.ext_id}`.toLowerCase().includes(IA.q.toLowerCase())));
    typeNote.replaceChildren(...(IA.type ? [`type: ${IA.type} `, h('button', {class: 'btn sm ghost', type: 'button', onclick: () => { IA.type = ''; renderTable(); }}, 'clear')] : []));
    const row = i => h('tr', {tabindex: '0', role: 'button', 'aria-label': `${i.display_name}: ${i.health}. Open details`, style: 'cursor:pointer', onclick: () => openDrawer(i.id), onkeydown: e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openDrawer(i.id); } }},
      h('td', {}, h('b', {}, i.display_name), h('div', {class: 'small muted'}, `${i.ext_id} - ${i.from_system || '-'} ${i.to_system || '-'}`)), h('td', {}, i.via || '-'), h('td', {}, i.kind), h('td', {}, i.schedule || '-'),
      h('td', {}, i.last_run ? `${clockOrDate(i.last_run)}${i.last_status && i.last_status !== 'success' ? ' - ' + i.last_status : ''}` : '-'), h('td', {class: 'n'}, pct(i.success_30)), h('td', {}, healthPill(i.health)), h('td', {}, i.owner || '-'));
    tableBox.replaceChildren(rows.length ? h('div', {class: 'card', style: 'padding:0;overflow:auto;margin:0'}, h('table', {class: 'utable'}, h('thead', {}, h('tr', {}, ['Integration', 'Via', 'Type', 'Schedule', 'Last run', 'Success 30 d', 'Status', 'Owner'].map((t, i) => h('th', {class: i === 5 ? '' : 'l', scope: 'col'}, t)))), h('tbody', {}, rows.map(row))))
      : h('div', {class: 'card empty', style: 'margin:0'}, h('h3', {}, 'Nothing matches'), h('div', {class: 'muted'}, 'Change the filter, or scan the sources again.')));
  }
  const runs = st.runs_per_day.map(x => [x.day, x.runs]), rate = st.success_rate.filter(w => w.pct != null).map(w => [w.week, w.pct]);
  const maxType = Math.max(1, ...st.by_type.map(t => t.n));
  main.replaceChildren(h('div', {class: 'page', id: 'intanpage'}, head, kpiBox,
    h('div', {class: 'stack', style: 'margin-top:16px'},
      h('div', {class: 'card', style: 'margin:0'}, h('div', {class: 'card-head'}, h('h3', {}, 'Integration map'), h('span', {class: 'sp'}), mapLegend('status')),
        d.map.edges.length ? [map.el, h('div', {class: 'small muted', style: 'margin-top:6px'}, 'Hover a line for details; click it to act. Red counts show issues per system. Click a system to filter the table.'), asTable(['Integration', 'From', 'To', 'Status'], d.map.edges.map(e => [e.label, e.from.slice(4), e.to.slice(4), e.status]))]
          : h('div', {class: 'muted small', style: 'padding:18px 0'}, scanning ? 'Scanning the sources - the map fills in as they answer.' : 'Nothing on the map yet: scan a source.')),
      h('div', {class: 'card', style: 'margin:0'}, h('div', {class: 'card-head'}, h('h3', {}, 'Act before it breaks'), h('span', {class: 'sp'}), h('span', {class: 'small muted'}, risky.length ? `${risky.length} item${risky.length === 1 ? '' : 's'} - click one to raise a ticket or a fix` : 'nothing to act on')),
        risky.length ? h('div', {class: 'g3', style: 'gap:10px'}, risky.map(r => h('button', {class: 'risk', type: 'button', onclick: () => openDrawer(r.integration_id)},
          h('div', {class: 'row', style: 'flex-wrap:nowrap'}, healthPill(r.health), h('b', {style: 'flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap'}, r.integration_name)),
          h('div', {class: 'small muted', style: 'margin-top:4px'}, r.reason, ' - ', h('span', {style: 'color:var(--accent)'}, r.status === 'proposed' ? 'waiting for approval' : r.status === 'actioned' ? 'approved - drafted' : r.then)))))
          : h('div', {class: 'muted small', style: 'padding:8px 0'}, 'Every integration found is healthy and owned.'))),
    h('div', {class: 'g3', style: 'margin-top:16px'},
      h('div', {class: 'card', style: 'margin:0'}, h('div', {class: 'card-head'}, h('h3', {}, 'Runs per day'), h('span', {class: 'sp'}), h('span', {class: 'small muted'}, 'all integrations - last 7 days')),
        colChart(runs, {height: 170, label: `Integration runs per day: ${runs.map(r => `${r[0]} ${fmtN(r[1], 0)}`).join(', ')}`, fmtv: v => fmtN(v, 0)}), asTable(['Day', 'Runs'], runs.map(r => [r[0], fmtN(r[1], 0)]))),
      h('div', {class: 'card', style: 'margin:0'}, h('div', {class: 'card-head'}, h('h3', {}, 'Success rate'), h('span', {class: 'sp'}), h('span', {class: 'small muted'}, 'by week')),
        rate.length >= 2 ? [lineChart(rate, {min: Math.max(0, Math.min(...rate.map(r => r[1])) - 2), max: 100, unit: ' %', label: `Integration success rate by week: ${rate.map(r => `${r[0]} ${fmtN(r[1])} %`).join(', ')}`}), asTable(['Week', 'Success'], rate.map(r => [r[0], fmtN(r[1]) + ' %']))]
          : h('div', {class: 'muted small', style: 'padding:24px 0'}, 'Not enough weeks of runs yet.'),
        rate.length >= 2 && rate[rate.length - 1][1] < rate[0][1] - 0.5 ? h('div', {class: 'small muted', style: 'margin-top:6px'}, `Down from ${fmtN(rate[0][1])} % to ${fmtN(rate[rate.length - 1][1])} %: ${risky.filter(r => r.health === 'Failing').map(r => r.integration_name).slice(0, 2).join(' and ') || 'see the list above'}.`) : null),
      h('div', {class: 'card', style: 'margin:0'}, h('div', {class: 'card-head'}, h('h3', {}, 'Found by type'), h('span', {class: 'sp'}), typeNote),
        st.by_type.length ? h('div', {class: 'bars'}, st.by_type.map(t => h('button', {class: 'bar2', type: 'button', style: 'border:0;background:none;padding:0;cursor:pointer;text-align:left;font:inherit', 'aria-label': `${t.type}: ${t.n}. Show these`, onclick: () => { IA.type = IA.type === t.type ? '' : t.type; renderTable(); $('#intan-table').scrollIntoView({behavior: 'smooth', block: 'start'}); }},
          h('span', {class: 'bl'}, t.type), h('div', {class: 'bt'}, h('div', {class: 'bf', style: `width:${Math.round(100 * t.n / maxType)}%`})), h('span', {class: 'bv'}, fmtN(t.n, 0))))) : h('div', {class: 'muted small'}, 'Nothing yet.'))),
    h('div', {class: 'section-title', id: 'intan-table'}, h('h2', {}, 'All integrations'), h('span', {class: 'hint'}, `${items.length} found`)),
    h('div', {class: 'toolbar'}, seg, qIn, srcSel), tableBox,
    h('div', {class: 'section-title'}, h('h2', {}, 'Sources'), h('span', {class: 'hint'}, builder ? h('button', {class: 'btn sm', type: 'button', onclick: () => sourceEditor(d, null)}, icon('plus'), 'Add a source') : null)),
    h('div', {class: 'card', style: 'padding:0;overflow:auto;margin:0'}, h('table', {class: 'utable'}, h('thead', {}, h('tr', {}, ['Source', 'Platform', 'Status', 'Last scan', 'Found', 'Every', ''].map((t, i) => h('th', {class: 'l', scope: 'col'}, t)))),
      h('tbody', {}, d.sources.map(s => h('tr', {}, h('td', {}, h('b', {}, s.name), s.error ? h('div', {class: 'small', style: 'color:var(--err)'}, s.error) : null), h('td', {}, s.label), h('td', {}, srcPill(s.status)), h('td', {}, s.last_scan ? ago(s.last_scan) + (s.seconds != null ? ` - ${fmtN(s.seconds)} s` : '') : '-'), h('td', {class: 'n'}, String(s.integrations)), h('td', {}, `${s.every_min} min`),
        h('td', {}, builder ? h('div', {class: 'row', style: 'gap:6px;flex-wrap:nowrap;justify-content:flex-end'},
          s.status !== 'paused' ? h('button', {class: 'btn sm', type: 'button', disabled: scanning, onclick: async () => { try { await api(`/api/intan/sources/${s.id}/scan`, {method: 'POST'}); notify(`Scan of ${s.name} queued`, 'ok'); renderIntegrations(); } catch (e) { notify(e.message, 'err'); } }}, 'Scan now') : null,
          h('button', {class: 'btn sm', type: 'button', onclick: async () => { try { await api(`/api/intan/sources/${s.id}/${s.status === 'paused' ? 'resume' : 'pause'}`, {method: 'POST'}); renderIntegrations(); } catch (e) { notify(e.message, 'err'); } }}, s.status === 'paused' ? 'Resume' : 'Pause'),
          h('button', {class: 'btn sm', type: 'button', onclick: () => sourceEditor(d, s)}, 'Edit'),
          h('button', {class: 'btn sm ghost danger', type: 'button', onclick: async () => { if (!await confirmBox(`Remove ${s.name}?`, 'Its integrations, runs, risks and credentials are removed; nothing is written to the source itself.')) return; try { await api(`/api/intan/sources/${s.id}`, {method: 'DELETE'}); notify('Source removed', 'ok'); renderIntegrations(); } catch (e) { notify(e.message, 'err'); } }}, 'Remove')) : null)))))),
    h('div', {class: 'row', style: 'margin-top:10px'}, h('span', {class: 'small muted'}, `Owners (RACI): ${d.owners.length} rule${d.owners.length === 1 ? '' : 's'} - used when a tool does not name an owner.`), builder ? h('button', {class: 'btn sm', type: 'button', onclick: () => ownersDialog(d)}, icon('users'), 'Edit the RACI table') : null),
    infoCards()));
  renderTable();
  document.title = `Integration analytics - ${S.brand ? S.brand.full : 'RELAY by PASDACS'}`;
  if (IA.open) { const id = IA.open; IA.open = null; openDrawer(id); }
  if (scanning) IA.timer = setTimeout(() => { if (location.hash.startsWith('#/integrations') && !document.querySelector('.modal')) renderIntegrations(); }, 5000);
}
const clockOrDate = t => (Date.now() / 1000 - t) < 86400 ? new Date(t * 1000).toLocaleTimeString(undefined, {hour: '2-digit', minute: '2-digit'}) : when(t);
const infoCards = () => h('div', {class: 'g3', style: 'margin-top:16px'},
  h('div', {class: 'card', style: 'margin:0'}, h('h3', {}, 'Discover'), h('p', {class: 'small muted', style: 'margin:0'}, 'Reads Oracle Integration Cloud, SSIS catalogs, ADF / Airflow, SAP CPI and PI/PO, MuleSoft, Boomi, Logic Apps, Glue, n8n and Power Automate, UiPath / Blue Prism / Automation Anywhere, API gateways, SFTP and mail rules, and system logs - read-only - and joins them into one map with owners from the RACI.')),
  h('div', {class: 'card', style: 'margin:0'}, h('h3', {}, 'Watch'), h('p', {class: 'small muted', style: 'margin:0'}, 'Runs, durations, volumes, error rates, expiring credentials and announced schema changes; unusual patterns flagged before they fail, with the reports each integration feeds.')),
  h('div', {class: 'card', style: 'margin:0'}, h('h3', {}, 'Act - with approval'), h('p', {class: 'small muted', style: 'margin:0'}, 'Raise a Jira or Freshservice ticket with the evidence; configuration fixes go to Self-healing, code fixes to AI SDLC. You confirm the ticket, the plan and the release.')));

/* ---------- the integration drawer: details, likely cause, act before it breaks ---------- */
async function intDrawer(id, d) {
  const builder = !!(S.me || {}).builder;
  const body = h('div', {class: 'mbody'}, skel('rows'));
  const m = modal('Integration', body, true);
  window.addEventListener('hashchange', () => m.remove(), {once: true});       // a link inside the drawer leaves the page: the drawer goes with it
  let i;
  try { i = await api(`/api/intan/integrations/${encodeURIComponent(id)}`); } catch (e) { body.replaceChildren(h('div', {class: 'note err'}, e.message)); return; }
  $('header b', m).textContent = i.display_name;
  const open = i.risks.filter(r => r.status === 'open'), waiting = i.risks.filter(r => r.status === 'proposed'), done = i.risks.filter(r => r.status === 'actioned');
  const act = (r, route) => {
    const p = r.proposal, label = (ROUTE_BTN[route] || ROUTE_BTN.ticket)[1];
    const ownerIn = route === 'owner' ? h('input', {type: 'text', placeholder: 'Team or person who owns this integration', 'aria-label': 'Owner'}) : null;
    const text = {ticket: `A ticket goes to Service desk (Jira / Freshservice) with the summary, cause, evidence and priority ${p.priority}. Owner: ${i.owner || 'to be assigned'}.`,
      heal: 'Self-healing prepares a configuration fix (renew the token, restore the setting, re-run), tests it on a copy and waits for your approval.',
      sdlc: `A change request is opened from the ticket; agents plan the change${r.kind === 'screen_change' ? ' (replace screen steps with the system\'s API)' : ''}, develop and test it on a branch, run UAT on synthetic data - your tech lead approves the plan and the release.`,
      owner: 'The owner you name is recorded for this integration and the RACI table; failures and tickets then reach them.'}[route];
    const ok = h('button', {class: 'btn primary', type: 'button', onclick: async () => { ok.disabled = true; try { await api(`/api/intan/risks/${r.id}/act`, {json: {route, owner: ownerIn ? ownerIn.value : null}}); mm.remove(); m.remove(); notify(`${label}: drafted - waiting for your confirmation in the validation queue`, 'ok'); intDrawer(id, d); renderIntegrations(); } catch (e) { notify(e.message, 'err'); ok.disabled = false; } }}, 'Draft it');
    const mm = modal(`${label} - ${i.ext_id}`, h('div', {class: 'mbody'}, h('p', {style: 'margin:0 0 10px'}, text), ownerIn ? h('div', {style: 'margin-bottom:10px'}, h('label', {class: 'f', style: 'margin-top:0'}, 'Owner'), ownerIn) : null,
      h('div', {class: 'note', style: 'margin:0 0 12px'}, 'Nothing changes yet. You will confirm the ', route === 'ticket' ? 'ticket' : route === 'owner' ? 'owner' : 'fix plan', ' in the validation queue before it goes anywhere.'),
      h('div', {class: 'row', style: 'justify-content:flex-end'}, h('button', {class: 'btn', type: 'button', onclick: () => mm.remove()}, 'Cancel'), ok)));
  };
  const dismiss = r => {
    const ta = h('textarea', {rows: 3, placeholder: 'Why this is not a risk (kept with the audit)'});
    const ok = h('button', {class: 'btn primary', type: 'button', onclick: async () => { if (!ta.value.trim()) return notify('Say why.', 'err'); try { await api(`/api/intan/risks/${r.id}/dismiss`, {json: {comment: ta.value}}); mm.remove(); m.remove(); notify('Dismissed', 'ok'); intDrawer(id, d); renderIntegrations(); } catch (e) { notify(e.message, 'err'); } }}, 'Dismiss');
    const mm = modal(`Dismiss: ${r.label}`, h('div', {class: 'mbody'}, h('label', {class: 'f', style: 'margin-top:0'}, 'Reason'), ta, h('div', {class: 'row', style: 'justify-content:flex-end;margin-top:12px'}, ok)));
  };
  const evidence = r => h('details', {class: 'astable'}, h('summary', {}, `Evidence (${r.evidence.length} row${r.evidence.length === 1 ? '' : 's'})`),
    h('table', {class: 'utable', style: 'margin-top:6px'}, h('tr', {}, ['When', 'Status', 'Duration', 'Volume', 'Detail'].map(t => h('th', {class: 'l'}, t))), r.evidence.map(e => h('tr', {}, h('td', {}, e.when), h('td', {}, e.status), h('td', {}, e.duration || '-'), h('td', {class: 'n'}, e.volume == null ? '-' : fmtN(e.volume, 0)), h('td', {}, e.error || '-')))));
  const riskRow = r => h('div', {class: 'card', style: 'margin:0;padding:12px 14px;background:var(--surface-2)'},
    h('div', {class: 'row'}, healthPill(r.health), h('b', {}, r.label), h('span', {class: 'small muted'}, r.reason)),
    h('div', {class: 'small', style: 'margin-top:6px'}, h('b', {}, 'Likely cause: '), r.cause), evidence(r),
    r.status === 'proposed' ? h('div', {class: 'row', style: 'margin-top:8px'}, h('span', {class: 'pill you'}, 'Waiting for your approval'), h('a', {class: 'btn sm', href: '#/validate'}, 'Open the validation queue'))
      : r.status === 'actioned' ? h('div', {class: 'row', style: 'margin-top:8px'}, h('span', {class: 'pill ok'}, 'Approved'), h('span', {class: 'small muted'}, `${r.proposal.label} - drafted for ${r.proposal.target}`))
      : builder ? h('div', {class: 'row', style: 'margin-top:8px'},
        r.kind === 'no_owner' ? h('button', {class: 'btn primary', type: 'button', onclick: () => act(r, 'owner')}, icon('users'), 'Assign an owner')
          : [h('button', {class: 'btn', type: 'button', onclick: () => act(r, 'ticket')}, icon('bell'), 'Raise ticket'),
            h('button', {class: 'btn' + (r.route === 'heal' ? ' primary' : ''), type: 'button', onclick: () => act(r, 'heal')}, icon('heart'), 'Self-healing'),
            i.code ? h('button', {class: 'btn' + (r.route === 'sdlc' ? ' primary' : ''), type: 'button', onclick: () => act(r, 'sdlc')}, icon('code'), 'Fix with AI SDLC') : null],
        h('button', {class: 'btn ghost', type: 'button', onclick: () => dismiss(r)}, 'Not a risk'))
      : h('div', {class: 'small muted', style: 'margin-top:8px'}, 'A BI Dev / Analyst can raise the ticket or the fix.'));
  body.replaceChildren(h('div', {},
    h('div', {class: 'small muted', style: 'margin-top:-6px'}, `${i.ext_id} - ${i.from_system || '-'} ${i.to_system || '-'}${i.via ? ' - via ' + i.via : ''}`),
    h('div', {class: 'row', style: 'margin:10px 0'}, healthPill(i.health), i.signal ? h('span', {class: 'muted'}, i.signal) : null),
    h('dl', {class: 'kv-list', style: 'grid-template-columns:130px 1fr'}, ['Type', i.kind, 'Schedule', i.schedule || '-', 'Last run', i.last_run ? `${when(i.last_run)} - ${i.last_status}` : '-', 'Success, 30 days', pct(i.success_30), 'Usual duration', durText(i.usual_s),
      'Owner', i.owner ? `${i.owner}${i.owner_from ? ` (from ${{adapter: 'the tool', raci: 'the RACI table', person: 'a person'}[i.owner_from] || i.owner_from})` : ''}` : '- nobody has claimed it',
      'Feeds', i.feeds.reports.length ? `${i.feeds.reports.length} report${i.feeds.reports.length === 1 ? '' : 's'}: ${i.feeds.reports.slice(0, 4).join(', ')}` : i.feeds.downstream ? `${i.feeds.downstream} downstream item${i.feeds.downstream === 1 ? '' : 's'}, no report yet` : '-',
      'Source', `${i.source.name} (${i.source.label})`].map((t, k) => h(k % 2 ? 'dd' : 'dt', {}, t))),
    i.credentials.length ? h('div', {class: 'small muted', style: 'margin-top:8px'}, 'Credentials by name: ' + i.credentials.map(c => `${c.name}${c.expires ? ' (expires ' + when(c.expires) + ')' : ''}`).join(', ')) : null,
    h('div', {class: 'row', style: 'margin:10px 0'}, i.node_id ? [h('a', {class: 'btn sm', href: `#/graph?focus=${encodeURIComponent(i.node_id)}`}, icon('graph'), 'Open in knowledge map'), h('a', {class: 'btn sm', href: `#/lineage?focus=${encodeURIComponent(i.node_id)}`}, icon('route'), 'Lineage')] : null),
    i.risks.length ? [h('div', {class: 'section-title', style: 'margin:14px 0 8px'}, h('h2', {}, 'Act before it breaks - you approve each step'), h('span', {class: 'hint'}, `${open.length} open - ${waiting.length} waiting - ${done.length} approved`)), h('div', {class: 'stack', style: 'gap:8px'}, i.risks.map(riskRow))]
      : h('div', {class: 'note ok', style: 'margin:10px 0'}, 'Nothing to act on: runs on time, numbers in range, owner known.'),
    i.work.length ? h('div', {class: 'small muted', style: 'margin-top:8px'}, 'Approved work: ' + i.work.map(w => `${w.title} ${w.target} (${w.status})`).join('; ') + '. The ticket itself is raised by Service desk and fixes run through Self-healing / AI SDLC when those modules arrive; until then the approved draft is kept here.') : null,
    h('div', {class: 'section-title', style: 'margin:14px 0 8px'}, h('h2', {}, 'Recent runs'), h('span', {class: 'hint'}, `${i.runs.length} shown`)),
    i.runs.length ? h('div', {style: 'overflow:auto'}, h('table', {class: 'utable'}, h('tr', {}, ['When', 'Status', 'Duration', 'Volume', 'Error'].map(t => h('th', {class: 'l'}, t))), i.runs.slice(0, 12).map(r => h('tr', {}, h('td', {}, r.when), h('td', {}, r.status), h('td', {}, r.duration), h('td', {class: 'n'}, r.volume == null ? '-' : fmtN(r.volume, 0)), h('td', {}, r.error || '-'))))) : h('div', {class: 'muted small'}, 'No runs recorded yet.')));
}

/* ---------- sources: the list, the editor and the RACI table ---------- */
function sourcesDialog(d) {
  const builder = !!(S.me || {}).builder;
  const list = h('div', {class: 'stack', style: 'gap:8px'}, d.sources.length ? d.sources.map(s => h('div', {class: 'card', style: 'margin:0;padding:10px 14px'},
    h('div', {class: 'row'}, h('b', {}, s.name), h('span', {class: 'small muted'}, s.label), srcPill(s.status), h('span', {class: 'sp', style: 'flex:1'}), h('span', {class: 'small muted'}, s.last_scan ? `scanned ${ago(s.last_scan)} - ${s.integrations} found` : 'not scanned yet')),
    s.error ? h('div', {class: 'small', style: 'color:var(--err);margin-top:4px'}, s.error) : null,
    h('div', {class: 'small muted', style: 'margin-top:4px'}, `Every ${s.every_min} min - credentials: ${Object.keys(s.secrets).length ? Object.entries(s.secrets).map(([n, v]) => `${n} ${v ? 'stored' : 'missing'}`).join(', ') : 'none needed'}`),
    builder ? h('div', {class: 'row', style: 'margin-top:8px;gap:6px'}, h('button', {class: 'btn sm', type: 'button', onclick: () => { m.remove(); sourceEditor(d, s); }}, 'Edit'),
      s.status !== 'paused' ? h('button', {class: 'btn sm', type: 'button', onclick: async () => { try { await api(`/api/intan/sources/${s.id}/scan`, {method: 'POST'}); m.remove(); notify('Scan queued', 'ok'); renderIntegrations(); } catch (e) { notify(e.message, 'err'); } }}, 'Scan now') : null) : null))
    : h('div', {class: 'muted small'}, 'No sources yet.'));
  const m = modal('Sources', h('div', {class: 'mbody'}, h('p', {class: 'small muted', style: 'margin:0 0 10px'}, 'Each source is read with its own read-only adapter; credentials are kept in the secrets store by name and never shown back.'), list,
    builder ? h('div', {class: 'row', style: 'margin-top:12px;justify-content:flex-end'}, h('button', {class: 'btn', type: 'button', onclick: () => { m.remove(); ownersDialog(d); }}, 'RACI table'), h('button', {class: 'btn primary', type: 'button', onclick: () => { m.remove(); sourceEditor(d, null); }}, icon('plus'), 'Add a source')) : null), true);
}
function sourceEditor(d, s) {
  const adapters = d.adapters, groups = [...new Set(adapters.map(a => a.group))];
  const kindSel = h('select', {class: 'sel', 'aria-label': 'Platform', disabled: !!s}, groups.map(g => h('optgroup', {label: g}, adapters.filter(a => a.group === g).map(a => h('option', {value: a.kind, selected: s ? s.kind === a.kind : a.kind === 'sample'}, a.label)))));
  const nameIn = h('input', {type: 'text', value: s ? s.name : '', placeholder: 'A name for this source', 'aria-label': 'Name'});
  const everySel = h('select', {class: 'sel', 'aria-label': 'Scan every'}, [[15, 'Every 15 min'], [30, 'Every 30 min'], [60, 'Hourly'], [180, 'Every 3 h'], [360, 'Every 6 h'], [1440, 'Daily']].map(([v, l]) => h('option', {value: v, selected: (s ? s.every_min : 60) === v}, l)));
  const fields = h('div', {}), docs = h('div', {class: 'hint'});
  const draw = () => {
    const a = adapters.find(x => x.kind === kindSel.value);
    docs.textContent = `${a.auth}. ${a.docs}.`;
    fields.replaceChildren(a.config.map(cf => h('div', {}, h('label', {class: 'f'}, cf.label, cf.required ? null : h('small', {}, 'optional')), cf.name === 'drops' || cf.name === 'rules' ? h('textarea', {rows: 3, placeholder: cf.hint || '', 'data-cf': cf.name}, (s && s.config[cf.name]) || '') : h('input', {type: 'text', placeholder: cf.hint || '', 'data-cf': cf.name, value: (s && s.config[cf.name]) || ''}))),
      a.secrets.map(sc => h('div', {}, h('label', {class: 'f'}, sc.label, h('small', {}, s && s.secrets[sc.name] ? 'stored - leave blank to keep' : 'kept in the secrets store by name')), h('input', {type: 'password', autocomplete: 'off', 'data-sc': sc.name, placeholder: s && s.secrets[sc.name] ? '--------' : ''}))),
      a.kind === 'sample' ? h('div', {class: 'note', style: 'margin:12px 0 0'}, 'Synthetic data (DemoData): the 17 integrations of the signed-off design with seeded failures - for demos, UAT and tests. Nothing is read from a real system.') : null);
  };
  kindSel.onchange = draw; draw();
  const save = h('button', {class: 'btn primary', type: 'button', onclick: async () => {
    const config = {}, secrets = {};
    fields.querySelectorAll('[data-cf]').forEach(el => { config[el.dataset.cf] = el.value; });
    fields.querySelectorAll('[data-sc]').forEach(el => { if (el.value) secrets[el.dataset.sc] = el.value; });
    save.disabled = true;
    try {
      const r = await api(s ? `/api/intan/sources/${s.id}` : '/api/intan/sources', {method: s ? 'PUT' : 'POST', json: {kind: kindSel.value, name: nameIn.value, config, secrets, every_min: +everySel.value}});
      m.remove(); notify(s ? 'Source saved' : 'Source added - scanning', 'ok');
      if (!s) { try { await api(`/api/intan/sources/${r.id}/scan`, {method: 'POST'}); } catch (e) { notify(e.message, 'err'); } }
      renderIntegrations();
    } catch (e) { notify(e.message, 'err'); save.disabled = false; }
  }}, s ? 'Save' : 'Add and scan');
  const m = modal(s ? `Edit source: ${s.name}` : 'Add a source', h('div', {class: 'mbody'},
    h('label', {class: 'f', style: 'margin-top:0'}, 'Platform'), kindSel, docs, h('label', {class: 'f'}, 'Name'), nameIn, fields, h('label', {class: 'f'}, 'Scan'), everySel,
    h('div', {class: 'note', style: 'margin:14px 0 0'}, h('b', {}, 'Read-only. '), 'The adapter only reads what the platform\'s API exposes; nothing is written to it.'),
    h('div', {class: 'row', style: 'justify-content:flex-end;margin-top:12px'}, h('button', {class: 'btn', type: 'button', onclick: () => m.remove()}, 'Cancel'), save)), true);
}
function ownersDialog(d) {
  const rows = d.owners.map(o => ({pattern: o.pattern, owner: o.owner}));
  const box = h('div', {class: 'stack', style: 'gap:6px'});
  const draw = () => box.replaceChildren(...(rows.length ? rows.map((r, k) => h('div', {class: 'row', style: 'flex-wrap:nowrap'},
    h('input', {type: 'text', value: r.pattern, placeholder: 'matches the integration, system or tool name', 'aria-label': `Pattern ${k + 1}`, oninput: e => { r.pattern = e.target.value; }}),
    h('input', {type: 'text', value: r.owner, placeholder: 'owner (team or person)', 'aria-label': `Owner ${k + 1}`, oninput: e => { r.owner = e.target.value; }}),
    h('button', {class: 'btn sm ghost', type: 'button', 'aria-label': 'Remove row', onclick: () => { rows.splice(k, 1); draw(); }}, icon('x')))) : [h('div', {class: 'muted small'}, 'No rules yet. Add one: a pattern (part of an integration, system or tool name) and who is accountable for it.')]));
  draw();
  const m = modal('Owners (RACI table)', h('div', {class: 'mbody'}, h('p', {class: 'small muted', style: 'margin:0 0 10px'}, 'When a tool does not name an owner, the first matching rule gives one. Integrations with no match are flagged "No owner".'), box,
    h('div', {class: 'row', style: 'margin-top:10px;justify-content:space-between'}, h('button', {class: 'btn sm', type: 'button', onclick: () => { rows.push({pattern: '', owner: ''}); draw(); }}, icon('plus'), 'Add a rule'),
      h('div', {class: 'row'}, h('button', {class: 'btn', type: 'button', onclick: () => m.remove()}, 'Cancel'), h('button', {class: 'btn primary', type: 'button', onclick: async () => { try { await api('/api/intan/owners', {method: 'PUT', json: {rows}}); m.remove(); notify('RACI table saved - owners and risks updated', 'ok'); renderIntegrations(); } catch (e) { notify(e.message, 'err'); } }}, 'Save')))), true);
}
