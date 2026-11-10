/* ---------------- Data observability (P14): health across the six layers, incidents with their impact path on the P13 map,
   warn / ticket / Self-healing / AI SDLC through a checkpoint, "mark as expected" (tunes the baseline), checks and
   thresholds per asset, sources and imports (GET /api/observe/overview). Colours are tokens only. ---------------- */
(function observeStyles() {
  document.head.append(h('style', {}, `
  .layers{display:grid;gap:10px;grid-template-columns:repeat(6,minmax(0,1fr))}
  .layer{text-align:left;border:1px solid var(--line);border-radius:var(--radius-sm);background:var(--surface);padding:10px 12px;cursor:pointer;color:var(--ink);font:inherit;position:relative}
  .layer:hover,.layer.on{border-color:var(--accent)}.layer.on{box-shadow:0 0 0 2px var(--ring)}
  .layer.has{border-left:3px solid var(--err)}.layer.warn{border-left:3px solid var(--warn)}.layer.ok{border-left:3px solid var(--ok)}
  .layer .ln{font-family:var(--font-head);font-weight:700;font-size:15.5px;margin:2px 0}
  .layer+.layer::before{content:"→";position:absolute;left:-13px;top:46%;color:var(--faint);font-size:12px}
  .obsev{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:6px;vertical-align:-1px}
  .obsev.high{background:var(--err)}.obsev.medium{background:var(--warn)}.obsev.low{background:var(--faint)}
  .obpath{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin-top:8px}
  .obpath .chipx.bad{border-color:var(--err);background:var(--err-tint);color:var(--ink);font-weight:600}
  .obwarn{border:1px solid var(--warn);background:var(--warn-tint);border-radius:var(--radius-sm);padding:10px 14px;margin:0 0 12px;display:flex;gap:10px;align-items:flex-start;color:var(--ink)}
  .obwarn .i{flex:none;color:var(--warn);width:18px;height:18px;margin-top:1px}
  .obkv dd b{font-weight:600}
  .obmeas{width:100%;border-collapse:collapse;font-size:13px}.obmeas th{text-align:left;color:var(--ink-2);font-weight:600;padding:4px 8px 4px 0}.obmeas td{padding:5px 8px 5px 0;border-top:1px solid var(--line);font-variant-numeric:tabular-nums}
  @media (max-width:1200px){.layers{grid-template-columns:repeat(3,minmax(0,1fr))}.layer+.layer::before{display:none}}
  @media (max-width:760px){.layers{grid-template-columns:1fr}}
  `));
})();

const OB = {layer: '', check: '', status: 'open', q: '', open: null, timer: null};
const OB_SEV = {high: ['High', 'err'], medium: ['Medium', 'you'], low: ['Low', 'mute']};
const OB_STATUS = {open: 'err', proposed: 'you', actioned: 'info', expected: 'mute', resolved: 'ok', dismissed: 'mute'};
const obSev = s => h('span', {class: 'pill plain ' + (OB_SEV[s] || ['?', 'mute'])[1]}, (OB_SEV[s] || [s])[0]);
const obStatus = i => h('span', {class: 'pill plain ' + (OB_STATUS[i.status] || 'mute')}, i.status_label || i.status);
const OB_ROUTE_BTN = {warn: ['alert', 'Warn report users'], ticket: ['bell', 'Raise ticket'], heal: ['heart', 'Fix with Self-healing'], sdlc: ['code', 'Fix with AI SDLC']};
// one approved / proposed action of an incident, with where it stands (a raised ticket links to the service desk; consolidation)
function obWorkRow(w) {
  const b = w.body || {}, t = b.ticket, tr = b.ticket_request || {};
  const [text, cls] = w.status === 'proposed' ? ['Waiting for approval', 'you'] : w.status === 'raised' ? ['Ticket raised', 'ok'] : w.status === 'handed' ? ['Handed to the Service desk', 'ok']
    : w.kind === 'ticket' && w.status === 'approved' ? (tr.status === 'waiting' ? ['Ticket waiting for approval', 'you'] : ['Approved — in the Service desk’s ticket drafts', 'mute'])
    : w.status === 'approved' ? ['Approved', 'ok'] : w.status === 'sent_back' ? ['Sent back', 'mute'] : w.status === 'withdrawn' ? ['Withdrawn', 'mute'] : [w.status, 'mute'];
  return h('div', {class: 'row small', style: 'gap:8px'}, h('span', {class: 'pill plain ' + cls}, text), h('span', {}, w.title),
    t && t.url ? h('a', {href: t.url, target: '_blank', rel: 'noopener'}, `${t.key} on ${t.source}`) : null,
    w.status === 'proposed' || tr.status === 'waiting' ? h('a', {class: 'btn sm', href: '#/validate'}, 'Open the validation queue')
      : w.kind === 'ticket' && w.status === 'approved' && !(b.handed || {}).checkpoint ? h('a', {class: 'btn sm', href: '#/servicedesk'}, 'Ticket drafts') : null);
}
const obAge = s => s < 3600 ? `${Math.max(1, Math.round(s / 60))} min` : s < 86400 ? `${(s / 3600).toFixed(s < 7200 ? 1 : 0)} h` : `${Math.round(s / 86400)} day${Math.round(s / 86400) === 1 ? '' : 's'}`;

/* the project page's banner (one fetch; shown only after a person accepted "Warn report users") */
function observeWarnings(pid) {
  const box = h('div', {});
  api(`/api/observe/warnings?pid=${encodeURIComponent(pid)}`).then(r => {
    box.replaceChildren(...(r.items || []).map(w => h('div', {class: 'obwarn', role: 'status'}, icon('alert'),
      h('div', {}, h('b', {}, 'Numbers under review'), ` since ${when(w.since)}: ${w.title} (${w.check_label}). `, h('a', {href: w.link}, 'See the incident')))));
  }).catch(() => {});
  return box;
}

async function renderObserve() {
  const main = $('#main');
  clearTimeout(OB.timer);
  const crumbs = [['Home', '#/'], ['All modules', '#/modules'], ['Data observability']], eyebrow = brandName() + ' · Data & Analytics · Data observability';
  if (!$('#obspage')) main.replaceChildren(h('div', {class: 'page'}, pageHead({crumbs, eyebrow, title: 'Is the data healthy — everywhere?'}), skel('cards')));
  const qp = hashParams();
  if (qp.get('open')) OB.open = qp.get('open');
  if (qp.get('layer')) OB.layer = qp.get('layer');
  let d;
  try { d = await api(`/api/observe/overview?status=${OB.status}${OB.layer ? '&layer=' + OB.layer : ''}${OB.check ? '&check=' + OB.check : ''}`); }
  catch (e) { main.replaceChildren(h('div', {class: 'page'}, pageHead({crumbs, eyebrow, title: 'Is the data healthy — everywhere?'}), h('div', {class: 'note err'}, e.message))); return; }
  if (!location.hash.startsWith('#/observability')) return;
  const s = d.summary, builder = !!d.can_edit, checking = ['queued', 'checking'].includes((d.state || {}).status);
  const head = pageHead({crumbs, eyebrow, title: 'Is the data healthy — everywhere?',
    promise: 'Freshness, volume, schema, distribution and reconciliation watched across every layer — from source systems and integrations to the reports, answers and agents that use them — with the impact traced before anyone acts on a wrong number.',
    actions: [checking ? h('span', {class: 'pill run'}, 'Checking…') : s.watched ? h('span', {class: 'pill plain ' + (s.high ? 'err' : s.open ? 'you' : 'ok')}, s.open ? `${s.open} open incident${s.open === 1 ? '' : 's'}` : 'All checks passing') : null,
      builder ? h('button', {class: 'btn', type: 'button', disabled: checking, onclick: async () => { try { await api('/api/observe/check', {method: 'POST'}); notify('Checks queued — every watched asset is read again, read-only', 'ok'); renderObserve(); } catch (e) { notify(e.message, 'err'); } }}, icon('play'), 'Check now') : null,
      h('button', {class: 'btn', type: 'button', onclick: () => obSettings(d)}, icon('gear'), 'Checks & thresholds'),
      h('button', {class: 'btn' + (s.watched ? '' : ' primary'), type: 'button', onclick: () => obSources(d)}, icon('plug'), 'Sources & imports')]});
  if (!s.watched && !d.incidents.length) {
    main.replaceChildren(h('div', {class: 'page', id: 'obspage'}, head,
      h('div', {class: 'card empty'}, h('h3', {}, 'Nothing watched yet'),
        h('div', {class: 'muted', style: 'max-width:640px;margin:0 auto'}, 'Relay watches every table, column, measure, report, flow and job on the knowledge map, plus what your connections expose — read-only. Publish a dashboard, add a connection to watch, or import the results of the tools you already run (OpenLineage, dbt tests, Great Expectations, Soda, or a webhook from Monte Carlo, Bigeye and others).'),
        h('div', {class: 'row', style: 'justify-content:center;margin-top:14px'},
          builder ? h('button', {class: 'btn primary', type: 'button', onclick: async e => { e.target.disabled = true; try { const r = await api('/api/observe/sync', {method: 'POST'}); notify(`${r.assets} asset${r.assets === 1 ? '' : 's'} watched`, 'ok'); if (r.assets) await api('/api/observe/check', {method: 'POST'}); renderObserve(); } catch (err) { notify(err.message, 'err'); e.target.disabled = false; } }}, icon('spark'), 'Watch my dashboards and connections') : h('div', {class: 'small muted'}, 'Ask a BI Dev / Analyst to start watching.'),
          builder ? h('button', {class: 'btn', type: 'button', onclick: () => obImport(d)}, icon('download'), 'Import from a tool') : null,
          d.test_hooks && builder ? h('button', {class: 'btn', type: 'button', onclick: async e => { e.target.disabled = true; try { await api('/api/observe/test/seed', {method: 'POST'}); notify('Sample estate added', 'ok'); renderObserve(); } catch (err) { notify(err.message, 'err'); e.target.disabled = false; } }}, icon('dice'), 'Try the sample estate') : null)),
      obInfoCards()));
    document.title = `Data observability · ${S.brand ? S.brand.full : 'RELAY by PASDACS'}`;
    return;
  }
  const pct = v => v == null ? '—' : fmtN(v) + ' %';
  const kpis = h('div', {class: 'g5'},
    kpiTile('Data health', pct(s.health_pct), s.readable ? `${fmtN(s.readable, 0)} of ${fmtN(s.watched, 0)} assets readable and checked` : 'assets passing every check'),
    kpiTile('Open incidents', String(s.open), s.open ? `${s.high} high · oldest ${obAge((s.oldest_h || 0) * 3600)}` : 'nothing open', {href: '#/observability', ...(s.open ? {} : {good: true})}),
    kpiTile('Assets watched', fmtN(s.watched, 0), 'tables, columns, models, reports, flows and jobs'),
    kpiTile('Caught before users', pct(s.caught_before_users_pct), 'incidents found before a ticket was raised'),
    kpiTile('Time to fix', s.time_to_fix_h == null ? '—' : obAge(s.time_to_fix_h * 3600), s.fixed ? `median, detection to resolved · ${s.fixed} fixed` : 'median, detection to resolved'));
  const layers = h('div', {class: 'card', style: 'margin-top:16px'}, h('div', {class: 'card-head'}, h('h3', {}, 'Health across every layer'), h('span', {class: 'sp'}), h('span', {class: 'small muted'}, OB.layer ? [`filtered to ${(s.layers.find(l => l.id === OB.layer) || {}).label} `, h('button', {class: 'btn sm ghost', type: 'button', onclick: () => { OB.layer = ''; renderObserve(); }}, 'show all')] : 'click a layer to filter incidents')),
    h('div', {class: 'layers'}, s.layers.map(l => h('button', {class: 'layer ' + (l.status === 'bad' ? 'has' : l.status) + (OB.layer === l.id ? ' on' : ''), type: 'button', 'aria-pressed': String(OB.layer === l.id), 'aria-label': `${l.label}: ${l.assets} assets, ${l.open} open incidents`, onclick: () => { OB.layer = OB.layer === l.id ? '' : l.id; renderObserve(); }},
      h('div', {class: 'small muted'}, `${l.n} · ${l.sub}`), h('div', {class: 'ln'}, l.label),
      h('div', {class: 'row', style: 'gap:6px'}, h('span', {class: 'small'}, `${fmtN(l.assets, 0)} ${l.id === 'consumers' ? 'consumers' : 'assets'}`), l.open ? h('span', {class: 'pill plain ' + (l.high ? 'err' : 'you')}, `${l.open} open`) : l.assets ? h('span', {class: 'pill plain ok'}, 'Healthy') : h('span', {class: 'pill plain mute'}, 'Nothing yet'))))),
    h('div', {class: 'small muted', style: 'margin-top:10px'}, 'Lineage joins the layers, so an incident in one shows everything downstream it touches.'));
  const onTime = s.on_time.filter(x => x.pct != null).map(x => [x.day, x.pct]);
  const maxCheck = Math.max(1, ...s.by_check.map(x => x.n)), maxFix = Math.max(1, ...s.fixed_by.map(x => x.n));
  const charts = h('div', {class: 'g3', style: 'margin-top:16px'},
    h('div', {class: 'card', style: 'margin:0'}, h('div', {class: 'card-head'}, h('h3', {}, 'On time'), h('span', {class: 'sp'}), h('span', {class: 'small muted'}, 'freshness SLA met')),
      onTime.length >= 2 ? [lineChart(onTime, {min: Math.max(0, Math.min(...onTime.map(r => r[1])) - 5), max: 100, unit: ' %', label: `Share of assets refreshed on time, last 7 days: ${onTime.map(r => `${r[0]} ${fmtN(r[1])} %`).join(', ')}`}), asTable(['Day', 'On time'], onTime.map(r => [r[0], fmtN(r[1]) + ' %']))] : h('div', {class: 'muted small', style: 'padding:24px 0'}, 'Not enough days of checks yet.')),
    h('div', {class: 'card', style: 'margin:0'}, h('div', {class: 'card-head'}, h('h3', {}, 'Incidents by check'), h('span', {class: 'sp'}), h('span', {class: 'small muted'}, '90 days')),
      s.by_check.length ? h('div', {class: 'bars'}, s.by_check.map(x => h('button', {class: 'bar2', type: 'button', style: 'border:0;background:none;padding:0;cursor:pointer;text-align:left;font:inherit', 'aria-pressed': String(OB.check === x.check), 'aria-label': `${x.label}: ${x.n}. Filter`, onclick: () => { OB.check = OB.check === x.check ? '' : x.check; renderObserve(); }},
        h('span', {class: 'bl'}, x.label), h('div', {class: 'bt'}, h('div', {class: 'bf', style: `width:${Math.round(100 * x.n / maxCheck)}%`})), h('span', {class: 'bv'}, fmtN(x.n, 0))))) : h('div', {class: 'muted small'}, 'No incidents yet.')),
    h('div', {class: 'card', style: 'margin:0'}, h('div', {class: 'card-head'}, h('h3', {}, 'How incidents were fixed'), h('span', {class: 'sp'}), h('span', {class: 'small muted'}, '90 days')),
      s.fixed_by.length ? h('div', {class: 'bars'}, s.fixed_by.map(x => bar2(x.how, x.n, maxFix, '#/observability'))) : h('div', {class: 'muted small'}, 'Nothing fixed yet.')));
  const openDrawer = id => obDrawer(id, d);
  const seg = h('div', {class: 'segbtn', role: 'group', 'aria-label': 'Status'}, [['open', 'Open'], ['expected', 'Expected'], ['resolved', 'Resolved'], ['all', 'All']].map(([v, l]) => h('button', {type: 'button', class: OB.status === v ? 'on' : '', 'aria-pressed': String(OB.status === v), onclick: () => { OB.status = v; renderObserve(); }}, l)));
  const qIn = h('input', {type: 'search', placeholder: 'Find an incident or asset…', 'aria-label': 'Find an incident', value: OB.q, style: 'max-width:280px', oninput: e => { OB.q = e.target.value; drawTable(); }});
  const tableBox = h('div', {});
  function drawTable() {
    const rows = d.incidents.filter(i => !OB.q || `${i.title} ${i.asset.label} ${i.check_label} ${i.tool_label}`.toLowerCase().includes(OB.q.toLowerCase()));
    const row = i => h('tr', {tabindex: '0', role: 'button', 'aria-label': `${i.title}: ${i.severity} ${i.status_label}. Open details`, style: 'cursor:pointer', onclick: () => openDrawer(i.id), onkeydown: e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openDrawer(i.id); } }},
      h('td', {}, h('div', {class: 'row', style: 'gap:6px;flex-wrap:nowrap'}, h('i', {class: 'obsev ' + i.severity, 'aria-hidden': 'true'}), h('b', {}, i.title)), h('div', {class: 'small muted'}, `${i.id} · ${i.asset.label}${i.cause ? ' · ' + i.cause.slice(0, 90) : ''}`)),
      h('td', {}, i.asset.layer_label), h('td', {}, h('span', {class: 'chipx'}, i.check_label)), h('td', {}, i.affects), h('td', {}, obAge(i.age_s)), h('td', {}, obStatus(i)), h('td', {}, h('span', {class: 'small', style: 'color:var(--accent)'}, i.route_label)), h('td', {}, h('span', {class: 'small muted'}, i.tool_label)));
    tableBox.replaceChildren(rows.length ? h('div', {class: 'card', style: 'padding:0;overflow:auto;margin:0'}, h('table', {class: 'utable'}, h('thead', {}, h('tr', {}, ['Incident', 'Layer', 'Check', 'Affects', 'Detected', 'Status', 'Route', 'Source'].map(t => h('th', {class: 'l', scope: 'col'}, t)))), h('tbody', {}, rows.map(row))))
      : h('div', {class: 'card empty', style: 'margin:0'}, h('h3', {}, OB.status === 'open' ? 'No open incidents' : 'Nothing here'), h('div', {class: 'muted'}, OB.status === 'open' ? 'Every watched asset passed its checks' + (OB.layer || OB.check ? ' in this view.' : '.') : 'Change the filter.')));
  }
  const srcLine = h('div', {class: 'row', style: 'margin-top:10px'}, h('span', {class: 'small muted'}, `${d.sources.length} source${d.sources.length === 1 ? '' : 's'}: ` + d.sources.map(x => `${x.name}${x.status === 'paused' ? ' (paused)' : ''}`).join(' · ') + (s.last_check ? ` · last check ${ago(s.last_check)}` : '')),
    h('span', {class: 'sp', style: 'flex:1'}), h('button', {class: 'btn sm', type: 'button', onclick: () => obAssets(d)}, icon('table'), `Watched assets (${fmtN(s.watched, 0)})`));
  main.replaceChildren(h('div', {class: 'page', id: 'obspage'}, head, kpis, layers, charts,
    h('div', {class: 'section-title', id: 'obs-inc'}, h('h2', {}, 'Incidents'), h('span', {class: 'hint'}, 'every one with its impact and a suggested route — a person decides')),
    h('div', {class: 'toolbar'}, seg, qIn, OB.check ? h('button', {class: 'btn sm ghost', type: 'button', onclick: () => { OB.check = ''; renderObserve(); }}, `check: ${d.labels[OB.check]} ×`) : null), tableBox, srcLine, obInfoCards()));
  drawTable();
  document.title = `Data observability · ${S.brand ? S.brand.full : 'RELAY by PASDACS'}`;
  if (OB.open) { const id = OB.open; OB.open = null; openDrawer(id); }
  if (checking) OB.timer = setTimeout(() => { if (location.hash.startsWith('#/observability') && !document.querySelector('.modal')) renderObserve(); }, 5000);
}
const obInfoCards = () => h('div', {class: 'g3', style: 'margin-top:16px'},
  h('div', {class: 'card', style: 'margin:0'}, h('h3', {}, 'Checks, everywhere'), h('p', {class: 'small muted', style: 'margin:0'}, 'Freshness, volume, schema, distribution, nulls and duplicates, reconciliation to source, and lineage breaks — learned baselines, thresholds you can tune, on warehouses, integrations, models and reports alike.')),
  h('div', {class: 'card', style: 'margin:0'}, h('h3', {}, 'Impact first'), h('p', {class: 'small muted', style: 'margin:0'}, 'Each incident shows which reports, schedules, Ask D answers, agents and people rely on the data — so owners can be warned before a wrong number reaches a meeting.')),
  h('div', {class: 'card', style: 'margin:0'}, h('h3', {}, 'Fix — with approval'), h('p', {class: 'small muted', style: 'margin:0'}, 'Route to Self-healing (configuration), AI SDLC (code), the source owner, or a ticket in Jira / Freshservice. A person confirms the warning, the ticket and the fix.')));

/* ---------- the incident drawer: measurements, the impact path on the map, the four actions, mark as expected ---------- */
async function obDrawer(id, d) {
  const builder = !!(S.me || {}).builder;
  const body = h('div', {class: 'mbody'}, skel('rows'));
  const m = modal('Incident', body, true);
  window.addEventListener('hashchange', () => m.remove(), {once: true});
  let i;
  try { i = await api(`/api/observe/incidents/${encodeURIComponent(id)}`); } catch (e) { body.replaceChildren(h('div', {class: 'note err'}, e.message)); return; }
  $('header b', m).textContent = i.title;
  const imp = i.impact, path = imp.path || {nodes: [], edges: []};
  const chain = path.nodes.filter(n => !n.virtual).sort((a, b) => a.hop - b.hop).slice(0, 7);
  const act = route => {
    const p = i.proposals[route], label = OB_ROUTE_BTN[route][1];
    const ok = h('button', {class: 'btn primary', type: 'button', onclick: async () => { ok.disabled = true; try { await api(`/api/observe/incidents/${i.id}/act`, {json: {route}}); mm.remove(); m.remove(); notify(`${label}: drafted — confirm it in the validation queue`, 'ok'); obDrawer(id, d); renderObserve(); } catch (e) { notify(e.message, 'err'); ok.disabled = false; } }}, 'Draft it');
    const mm = modal(`${label} — ${i.id}`, h('div', {class: 'mbody'}, h('p', {style: 'margin:0 0 10px'}, p.next),
      route === 'warn' && p.banner ? h('div', {class: 'obwarn', style: 'margin:0 0 10px'}, icon('alert'), h('div', {}, p.banner)) : null,
      h('div', {class: 'note', style: 'margin:0 0 12px'}, 'Nothing changes yet. You will confirm the ', route === 'warn' ? 'banner and the message' : route === 'ticket' ? 'ticket' : 'fix plan', ' in the validation queue before it goes anywhere.'),
      h('div', {class: 'row', style: 'justify-content:flex-end'}, h('button', {class: 'btn', type: 'button', onclick: () => mm.remove()}, 'Cancel'), ok)));
  };
  const expected = () => {
    const ta = h('textarea', {rows: 3, placeholder: 'Why this is normal (kept with the audit; the baseline learns from it)'});
    const ok = h('button', {class: 'btn primary', type: 'button', onclick: async () => { if (!ta.value.trim()) return notify('Say why.', 'err'); try { await api(`/api/observe/incidents/${i.id}/expected`, {json: {comment: ta.value}}); mm.remove(); m.remove(); notify('Marked as expected — the baseline now allows it', 'ok'); renderObserve(); } catch (e) { notify(e.message, 'err'); } }}, 'Mark as expected');
    const mm = modal(`Mark as expected: ${i.check_label}`, h('div', {class: 'mbody'}, h('p', {class: 'small muted', style: 'margin:0 0 8px'}, 'The measured value joins the learned baseline for this asset and this check, so the same reading is not an incident next time.'), h('label', {class: 'f', style: 'margin-top:0'}, 'Reason'), ta, h('div', {class: 'row', style: 'justify-content:flex-end;margin-top:12px'}, ok)));
  };
  const resolve = async () => { if (!await confirmBox('Mark as resolved?', 'The incident closes and any banner on the affected dashboards is cleared. The checks keep running.', 'Resolved', false)) return; try { await api(`/api/observe/incidents/${i.id}/resolve`, {json: {comment: 'Resolved by hand'}}); m.remove(); notify('Resolved', 'ok'); renderObserve(); } catch (e) { notify(e.message, 'err'); } };
  const mapBox = h('div', {});
  if (path.nodes.length > 1) {
    const map = lineageMap({layout: 'flow', colour: 'status', height: 280, dimOthers: false, dots: false, label: `Impact path: ${chain.map(n => n.label).join(' to ')}`});
    mapBox.append(map.el);
    setTimeout(() => map.draw({nodes: path.nodes.map(n => ({...n, status: n.id === i.asset.node_id ? (i.severity === 'high' ? 'Failing' : 'At risk') : (n.virtual ? null : 'Healthy')})), edges: path.edges, focus: i.asset.node_id}, {select: null}), 30);
  }
  const workRows = i.work || [];
  body.replaceChildren(h('div', {},
    h('div', {class: 'small muted', style: 'margin-top:-6px'}, `${i.id} · ${i.check_label} · ${i.asset.layer_label} · found by ${i.tool_label}`),
    h('div', {class: 'row', style: 'margin:10px 0'}, obStatus(i), obSev(i.severity), h('span', {class: 'muted'}, `detected ${when(i.first_seen)} · last seen ${ago(i.last_seen)}`)),
    h('div', {}, h('b', {}, 'Where it starts and what it touches'),
      h('div', {class: 'obpath'}, chain.map((n, k) => [k ? h('span', {class: 'muted', 'aria-hidden': 'true'}, '→') : null, h('span', {class: 'chipx' + (n.id === i.asset.node_id ? ' bad' : '')}, n.label)]),
        imp.schedules ? [h('span', {class: 'muted', 'aria-hidden': 'true'}, '→'), h('span', {class: 'chipx'}, `${imp.schedules} schedule${imp.schedules === 1 ? '' : 's'}`)] : null,
        imp.answers ? [h('span', {class: 'muted', 'aria-hidden': 'true'}, '→'), h('span', {class: 'chipx'}, `${imp.answers} Ask D answer${imp.answers === 1 ? '' : 's'}`)] : null,
        imp.people ? [h('span', {class: 'muted', 'aria-hidden': 'true'}, '→'), h('span', {class: 'chipx'}, `${imp.people} ${imp.people === 1 ? 'person' : 'people'}`)] : null),
      mapBox, path.nodes.length > 1 ? asTable(['Item', 'Kind', 'Hops'], path.nodes.map(n => [n.label, LIN_KIND_NAME[n.kind] || n.kind, n.virtual ? 'consumer' : String(n.hop)])) : null),
    h('dl', {class: 'kv-list obkv', style: 'grid-template-columns:130px 1fr;margin-top:12px'}, ['Check', i.check_label, 'Asset', `${i.asset.label} (${i.asset.layer_label})`, 'What moved', i.what || '—', 'Affects', imp.text, 'Likely cause', i.cause || '—', 'Suggested route', i.route_label, 'Also affected', i.also.length ? i.also.map(a => a.label).join(', ') : '—'].map((t, k) => h(k % 2 ? 'dd' : 'dt', {}, t))),
    i.rows.length ? h('table', {class: 'obmeas', style: 'margin-top:12px'}, h('thead', {}, h('tr', {}, ['What', 'Measured', 'Expected'].map(t => h('th', {scope: 'col'}, t)))), h('tbody', {}, i.rows.map(r => h('tr', {}, r.map(v => h('td', {}, String(v == null ? '—' : v))))))) : null,
    i.history.length >= 2 ? h('div', {style: 'margin-top:12px'}, colChart(i.history.map(x => [new Date(x.ts * 1000).toLocaleDateString(undefined, {weekday: 'short'}), x.rows]), {height: 140, label: `Rows per day, last ${i.history.length} checks`, fmtv: v => fmtN(v, 0)})) : null,
    i.status === 'resolved' || i.status === 'expected' ? h('div', {class: 'note ok', style: 'margin:12px 0 0'}, `${i.status_label}${i.resolved ? ' ' + when(i.resolved) : ''}${i.resolved_how ? ' · ' + i.resolved_how : ''}${i.note ? ' · ' + i.note : ''}`) : null,
    workRows.length ? h('div', {class: 'stack', style: 'gap:6px;margin-top:12px'}, workRows.map(obWorkRow)) : null,
    ['open', 'proposed', 'actioned'].includes(i.status) ? [h('div', {class: 'note', style: 'margin:12px 0 0'}, `Affected report owners can be told now, with a banner on the reports: “numbers under review since ${when(i.first_seen)}”.`),
      builder ? h('div', {class: 'row', style: 'margin-top:10px'},
        Object.entries(OB_ROUTE_BTN).map(([r, [ic, l]]) => h('button', {class: 'btn' + (r === i.route ? ' primary' : ''), type: 'button', onclick: () => act(r)}, icon(ic), l)),
        h('span', {class: 'sp', style: 'flex:1'}), h('button', {class: 'btn ghost', type: 'button', onclick: expected}, 'Mark as expected'), h('button', {class: 'btn ghost', type: 'button', onclick: resolve}, 'Resolved'))
        : h('div', {class: 'small muted', style: 'margin-top:8px'}, 'A BI Dev / Analyst can warn the users, raise the ticket or the fix.')] : null,
    h('div', {class: 'row', style: 'margin-top:12px'}, i.asset.node_id ? [h('a', {class: 'btn sm', href: `#/lineage?focus=${encodeURIComponent(i.asset.node_id)}`}, icon('route'), 'Lineage'), h('a', {class: 'btn sm', href: `#/graph?focus=${encodeURIComponent(i.asset.node_id)}`}, icon('graph'), 'Knowledge map')] : null,
      h('button', {class: 'btn sm', type: 'button', onclick: () => { m.remove(); obAsset(i.asset.id, d); }}, icon('gear'), 'Checks for this asset'))));
}

/* ---------- watched assets, checks and thresholds ---------- */
function obAssets(d) {
  const q = h('input', {type: 'search', placeholder: 'Find an asset…', 'aria-label': 'Find an asset', style: 'max-width:280px', oninput: () => draw()});
  const layerSel = h('select', {class: 'sel', 'aria-label': 'Layer', style: 'width:auto', onchange: () => draw()}, h('option', {value: ''}, 'All layers'), d.layers.filter(l => l[0] !== 'consumers').map(l => h('option', {value: l[0]}, l[1])));
  const box = h('div', {});
  const ST = {Healthy: 'ok', Warning: 'you', Failing: 'err', 'Not readable': 'mute', Watched: 'info', Unknown: 'mute', Gone: 'mute'};
  const draw = () => {
    const rows = d.assets.filter(a => (!layerSel.value || a.layer === layerSel.value) && (!q.value || `${a.label} ${a.name} ${a.system} ${a.kind}`.toLowerCase().includes(q.value.toLowerCase()))).slice(0, 300);
    box.replaceChildren(rows.length ? h('div', {style: 'overflow:auto'}, h('table', {class: 'utable'}, h('thead', {}, h('tr', {}, ['Asset', 'Kind', 'Layer', 'Read through', 'Checks', 'Status', 'Last check'].map(t => h('th', {class: 'l', scope: 'col'}, t)))),
      h('tbody', {}, rows.map(a => h('tr', {tabindex: '0', role: 'button', 'aria-label': `${a.label}: ${a.status}. Open its checks`, style: 'cursor:pointer', onclick: () => { m.remove(); obAsset(a.id, d); }, onkeydown: e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); m.remove(); obAsset(a.id, d); } }},
        h('td', {}, h('b', {}, a.label), a.signal ? h('div', {class: 'small muted'}, a.signal.slice(0, 100)) : null), h('td', {}, LIN_KIND_NAME[a.kind] || a.kind), h('td', {}, a.layer_label), h('td', {}, {duckdb: 'dashboard extract', connection: 'warehouse (read-only)', sdk: 'platform (read-only)', intan: 'runs (P13)', project: 'dashboard', none: '—'}[a.reader] || a.reader),
        h('td', {class: 'n'}, a.checks ? `${a.checks}${a.failing ? ' · ' + a.failing + ' failing' : ''}` : '—'), h('td', {}, h('span', {class: 'pill plain ' + (ST[a.status] || 'mute')}, a.status)), h('td', {}, a.last_check ? ago(a.last_check) : '—'))))))
      : h('div', {class: 'muted small'}, 'Nothing matches.'));
  };
  const m = modal('Watched assets', h('div', {class: 'mbody'}, h('div', {class: 'toolbar'}, q, layerSel), box, h('div', {class: 'small muted', style: 'margin-top:8px'}, 'Every table, column, measure, report, flow and job on the knowledge map, plus what the watched connections expose. Click one to see its checks and tune its thresholds.')), true);
  draw();
}
async function obAsset(aid, d) {
  const builder = !!(S.me || {}).builder;
  const body = h('div', {class: 'mbody'}, skel('rows'));
  const m = modal('Asset', body, true);
  let a;
  try { a = await api(`/api/observe/assets/${encodeURIComponent(aid)}`); } catch (e) { body.replaceChildren(h('div', {class: 'note err'}, e.message)); return; }
  $('header b', m).textContent = a.label || a.name;
  const fields = {};
  const checkRow = c => {
    const f = fields[c.check] = {};
    const en = f.__en = h('input', {type: 'checkbox', checked: c.enabled, disabled: !builder, 'aria-label': `${c.label} enabled`});
    const inputs = Object.entries(c.help).map(([k, help]) => {
      const v = c.override[k];
      const inp = f[k] = h('input', {type: 'text', value: v == null ? '' : String(v), placeholder: String(c.defaults[k] == null ? 'learned' : c.defaults[k]), disabled: !builder, 'aria-label': `${c.label}: ${k}`, title: help});
      return h('div', {}, h('label', {class: 'f', style: 'margin-top:6px'}, k.replace(/_/g, ' '), h('small', {}, help)), inp);
    });
    const last = c.last_status === 'incident' ? h('span', {class: 'pill plain err'}, 'incident') : c.last_status === 'error' ? h('span', {class: 'pill plain mute'}, 'could not read') : c.last_run ? h('span', {class: 'pill plain ok'}, 'ok') : h('span', {class: 'pill plain mute'}, 'not run yet');
    return h('details', {class: 'card', style: 'margin:0;padding:10px 14px'}, h('summary', {style: 'cursor:pointer;display:flex;gap:10px;align-items:center'}, en, h('b', {}, c.label), last, h('span', {class: 'small muted'}, c.last_text ? c.last_text.slice(0, 80) : (c.last_run ? ago(c.last_run) : '')), c.accepted.length ? h('span', {class: 'small muted'}, `· ${c.accepted.length} marked expected`) : null),
      h('div', {class: 'g2', style: 'gap:8px;margin-top:6px'}, inputs.length ? inputs : h('div', {class: 'small muted'}, 'No thresholds: this check compares with the last observation.')),
      c.accepted.length ? h('div', {class: 'small muted', style: 'margin-top:6px'}, 'Expected readings: ' + c.accepted.map(x => Object.entries(x).filter(([k]) => !['when', 'by', 'column'].includes(k) && x[k] != null).map(([k, v]) => `${k} ${typeof v === 'number' ? fmtN(v) : v}`).join(', ')).join(' · ')) : null);
  };
  const save = h('button', {class: 'btn primary', type: 'button', onclick: async () => {
    const checks = {};
    for (const c of a.checks) { const f = fields[c.check] || {}; const config = {}; for (const [k, inp] of Object.entries(f)) if (k !== '__en' && inp.value !== '') { const n = Number(inp.value); config[k] = inp.value === '' ? null : (Number.isFinite(n) && inp.value.trim() !== '' && !/^[a-z_]+$/i.test(inp.value) ? n : inp.value); }
      checks[c.check] = {enabled: f.__en ? f.__en.checked : c.enabled, config}; }
    save.disabled = true;
    try { await api(`/api/observe/assets/${a.id}/checks`, {method: 'PUT', json: {checks}}); notify('Thresholds saved — audited', 'ok'); m.remove(); renderObserve(); } catch (e) { notify(e.message, 'err'); save.disabled = false; }
  }}, 'Save thresholds');
  body.replaceChildren(h('div', {},
    h('div', {class: 'small muted', style: 'margin-top:-6px'}, `${LIN_KIND_NAME[a.kind] || a.kind} · ${a.layer_label}${a.system ? ' · ' + a.system : ''} · read through ${{duckdb: 'the dashboard extract', connection: 'the warehouse connection (read-only)', sdk: 'the platform (read-only)', intan: "P13's runs", project: 'the dashboard', none: 'nothing yet'}[a.reader] || a.reader}`),
    h('div', {class: 'row', style: 'margin:10px 0'}, h('span', {class: 'pill plain ' + ({Healthy: 'ok', Warning: 'you', Failing: 'err'}[a.status] || 'mute')}, a.status), a.signal ? h('span', {class: 'muted small'}, a.signal) : null, a.impact ? h('span', {class: 'small muted'}, '· ' + a.impact.text) : null),
    a.history.volume.length >= 2 ? colChart(a.history.volume.map(x => [new Date(x.ts * 1000).toLocaleDateString(undefined, {weekday: 'short'}), x.rows]), {height: 130, label: `Rows per check, last ${a.history.volume.length}`, fmtv: v => fmtN(v, 0)}) : null,
    h('div', {class: 'section-title', style: 'margin:12px 0 8px'}, h('h2', {}, 'Checks and thresholds'), h('span', {class: 'hint'}, 'blank = the default or a learned baseline')),
    a.checks.length ? h('div', {class: 'stack', style: 'gap:8px'}, a.checks.map(checkRow)) : h('div', {class: 'muted small'}, 'No checks run on this asset directly; incidents reach it through its table or the lineage.'),
    a.incidents.length ? [h('div', {class: 'section-title', style: 'margin:12px 0 8px'}, h('h2', {}, 'Incidents on this asset')), h('div', {class: 'stack', style: 'gap:4px'}, a.incidents.slice(0, 8).map(i => h('div', {class: 'row small', style: 'gap:8px'}, obStatus(i), h('span', {}, i.title), h('span', {class: 'muted'}, ago(i.first_seen)))))] : null,
    h('div', {class: 'row', style: 'justify-content:flex-end;margin-top:12px;gap:8px'}, builder && a.reader !== 'none' ? h('button', {class: 'btn', type: 'button', onclick: async () => { try { await api(`/api/observe/assets/${a.id}/check`, {method: 'POST'}); notify('Check queued', 'ok'); } catch (e) { notify(e.message, 'err'); } }}, icon('play'), 'Check now') : null, builder && a.checks.length ? save : null)));
}
function obSettings(d) {
  const builder = !!(S.me || {}).builder, fields = {};
  const sec = ([k, cfg]) => h('details', {class: 'card', style: 'margin:0;padding:10px 14px'}, h('summary', {style: 'cursor:pointer'}, h('b', {}, d.labels[k])),
    h('div', {class: 'g2', style: 'gap:8px;margin-top:6px'}, Object.entries(d.help[k] || {}).map(([f, help]) => { const inp = h('input', {type: 'text', value: cfg[f] == null ? '' : String(cfg[f]), placeholder: 'learned', disabled: !builder, 'aria-label': `${d.labels[k]}: ${f}`, title: help}); (fields[k] = fields[k] || {})[f] = inp; return h('div', {}, h('label', {class: 'f', style: 'margin-top:6px'}, f.replace(/_/g, ' '), h('small', {}, help)), inp); })));
  const save = h('button', {class: 'btn primary', type: 'button', onclick: async () => {
    const settings = {};
    for (const [k, fs] of Object.entries(fields)) { settings[k] = {}; for (const [f, inp] of Object.entries(fs)) { const v = inp.value.trim(); if (v === '') continue; const n = Number(v); settings[k][f] = Number.isFinite(n) && !/^[a-z_]+$/i.test(v) ? n : v; } }
    save.disabled = true;
    try { await api('/api/observe/settings', {method: 'PUT', json: {settings}}); notify('Thresholds saved for every asset — audited', 'ok'); m.remove(); renderObserve(); } catch (e) { notify(e.message, 'err'); save.disabled = false; }
  }}, 'Save');
  const m = modal('Checks & thresholds', h('div', {class: 'mbody'}, h('p', {class: 'small muted', style: 'margin:0 0 10px'}, 'The defaults every asset starts from. Baselines are learned from each asset’s own history (by weekday where it has one); a reading a person marks “expected” widens that asset’s band. An asset can override any of these under its own checks.'),
    h('div', {class: 'stack', style: 'gap:8px'}, Object.entries(d.settings).filter(([k]) => d.help[k] && Object.keys(d.help[k]).length).map(sec)),
    h('div', {class: 'row', style: 'justify-content:flex-end;margin-top:12px'}, h('button', {class: 'btn', type: 'button', onclick: () => m.remove()}, 'Cancel'), builder ? save : null)), true);
}

/* ---------- sources and imports ---------- */
function obSources(d) {
  const builder = !!(S.me || {}).builder;
  const srcPill = s => h('span', {class: 'pill plain ' + ({ok: 'ok', new: 'mute', error: 'err', paused: 'mute'}[s.status] || 'mute')}, {ok: 'Checked', new: 'Not checked yet', error: 'Needs attention', paused: 'Paused'}[s.status] || s.status);
  const list = h('div', {class: 'stack', style: 'gap:8px'}, d.sources.map(s => h('div', {class: 'card', style: 'margin:0;padding:10px 14px'},
    h('div', {class: 'row'}, h('b', {}, s.name), h('span', {class: 'small muted'}, s.label + (s.tool_label ? ' · ' + s.tool_label : '') + (s.connection ? ` · ${s.connection.kind} · ${({read: 'read-only', comment: 'read & comment', write: 'read & write'})[s.connection.scope] || s.connection.scope}` : '')), srcPill(s), h('span', {class: 'sp', style: 'flex:1'}),
      h('span', {class: 'small muted'}, s.kind === 'import' ? `${s.incidents} incident${s.incidents === 1 ? '' : 's'} · webhook ${s.hook} · token ${s.has_token ? 'stored' : 'missing'}` : `${s.assets} asset${s.assets === 1 ? '' : 's'}${s.last_check ? ' · checked ' + ago(s.last_check) : ''}`)),
    s.error ? h('div', {class: 'small', style: 'color:var(--err);margin-top:4px'}, s.error) : null,
    builder ? h('div', {class: 'row', style: 'margin-top:8px;gap:6px'},
      s.kind !== 'import' && s.status !== 'paused' ? h('button', {class: 'btn sm', type: 'button', onclick: async () => { try { await api(`/api/observe/sources/${s.id}/check`, {method: 'POST'}); m.remove(); notify('Check queued', 'ok'); renderObserve(); } catch (e) { notify(e.message, 'err'); } }}, 'Check now') : null,
      s.kind === 'import' ? h('button', {class: 'btn sm', type: 'button', onclick: () => { m.remove(); obImport(d, s); }}, 'Upload results') : null,
      s.kind !== 'import' ? h('button', {class: 'btn sm', type: 'button', onclick: async () => { try { await api(`/api/observe/sources/${s.id}/${s.status === 'paused' ? 'resume' : 'pause'}`, {method: 'POST'}); m.remove(); renderObserve(); } catch (e) { notify(e.message, 'err'); } }}, s.status === 'paused' ? 'Resume' : 'Pause') : null,
      !['dashboards', 'integrations'].includes(s.kind) ? h('button', {class: 'btn sm ghost danger', type: 'button', onclick: async () => { if (!await confirmBox(`Remove ${s.name}?`, 'Its assets stop being watched; nothing is written to the source itself.')) return; try { await api(`/api/observe/sources/${s.id}`, {method: 'DELETE'}); m.remove(); notify('Source removed', 'ok'); renderObserve(); } catch (e) { notify(e.message, 'err'); } }}, 'Remove') : null) : null)));
  const m = modal('Sources & imports', h('div', {class: 'mbody'}, h('p', {class: 'small muted', style: 'margin:0 0 10px'}, 'Dashboards and the integrations P13 discovered are always watched. Add a connection to watch its tables through the Connector SDK (its scope stays read-only), or another tool’s results — credentials and webhook tokens are kept in the secrets store by name and never shown back.'), list,
    builder ? h('div', {class: 'row', style: 'margin-top:12px;justify-content:flex-end;gap:8px'}, h('button', {class: 'btn', type: 'button', onclick: () => { m.remove(); obImport(d); }}, icon('download'), 'Add a tool’s results'), h('button', {class: 'btn primary', type: 'button', onclick: () => { m.remove(); obAddConnection(d); }}, icon('plug'), 'Watch a connection')) : null), true);
}
async function obAddConnection(d) {
  let conns = [];
  try { conns = (await api('/api/connections')).connections || []; } catch (e) { conns = []; }
  conns = conns.filter(c => c.enabled !== false);
  const sel = h('select', {class: 'sel', 'aria-label': 'Connection'}, conns.length ? conns.map(c => h('option', {value: c.id}, `${c.name} (${c.label || c.kind}) · ${({read: 'read-only', comment: 'read & comment', write: 'read & write'})[c.scope] || 'read-only'}`)) : h('option', {value: ''}, 'No connections yet'));
  const objs = h('textarea', {rows: 3, placeholder: 'Tables or objects to watch, one per line (blank: the tables configured on the connection)'});
  const nameIn = h('input', {type: 'text', placeholder: 'A name for this source (optional)', 'aria-label': 'Name'});
  const everySel = h('select', {class: 'sel', 'aria-label': 'Check every'}, [[30, 'Every 30 min'], [60, 'Hourly'], [180, 'Every 3 h'], [360, 'Every 6 h'], [1440, 'Daily']].map(([v, l]) => h('option', {value: v, selected: v === 60}, l)));
  const save = h('button', {class: 'btn primary', type: 'button', disabled: !conns.length, onclick: async () => { save.disabled = true; try { const r = await api('/api/observe/sources', {json: {kind: 'connection', name: nameIn.value, config: {connection_id: sel.value, objects: objs.value.split(/\n|,/).map(x => x.trim()).filter(Boolean)}, every_min: +everySel.value}}); m.remove(); notify(`${r.name}: ${r.assets} asset${r.assets === 1 ? '' : 's'} watched — checking`, 'ok'); try { await api(`/api/observe/sources/${r.id}/check`, {method: 'POST'}); } catch (e) {} renderObserve(); } catch (e) { notify(e.message, 'err'); save.disabled = false; } }}, 'Watch and check');
  const m = modal('Watch a connection', h('div', {class: 'mbody'}, h('label', {class: 'f', style: 'margin-top:0'}, 'Connection'), sel, conns.length ? null : h('div', {class: 'hint'}, h('a', {href: '#/connections'}, 'Add a connection first'), ' — your own or one shared with you.'),
    h('label', {class: 'f'}, 'Objects'), objs, h('label', {class: 'f'}, 'Name'), nameIn, h('label', {class: 'f'}, 'Check'), everySel,
    h('div', {class: 'note', style: 'margin:14px 0 0'}, h('b', {}, 'Read-only. '), 'Checks run one guarded SELECT per table with the connection owner’s stored sign-in; the connection’s scope and limits apply. Nothing is written.'),
    h('div', {class: 'row', style: 'justify-content:flex-end;margin-top:12px'}, h('button', {class: 'btn', type: 'button', onclick: () => m.remove()}, 'Cancel'), save)), true);
}
function obImport(d, src) {
  const toolSel = h('select', {class: 'sel', 'aria-label': 'Tool', disabled: !!src}, Object.entries(d.tools || {}).map(([k, l]) => h('option', {value: k, selected: src ? src.tool === k : k === 'openlineage'}, l)));
  const nameIn = h('input', {type: 'text', value: src ? src.name : '', placeholder: 'A name for this source (optional)', 'aria-label': 'Name'});
  const tokenIn = h('input', {type: 'password', autocomplete: 'off', placeholder: src && src.has_token ? '•••••••• (stored; leave blank to keep)' : 'webhook token (kept by name in the secrets store)', 'aria-label': 'Webhook token'});
  const file = h('input', {type: 'file', accept: '.json,application/json', 'aria-label': 'Results file (JSON)'});
  const ta = h('textarea', {rows: 6, placeholder: 'or paste the JSON here: OpenLineage events, dbt run_results.json, a Great Expectations validation result, a Soda scan result, or {"incidents": [...]}'});
  const go = h('button', {class: 'btn primary', type: 'button', onclick: async () => {
    go.disabled = true;
    try {
      let sid = src ? src.id : null;
      if (!src) { const r = await api('/api/observe/sources', {json: {kind: 'import', name: nameIn.value, config: {tool: toolSel.value}, token: tokenIn.value}}); sid = r.id; }
      else if (tokenIn.value) await api(`/api/observe/sources/${src.id}`, {method: 'PUT', json: {token: tokenIn.value}});
      let text = ta.value.trim();
      if (!text && file.files[0]) text = await file.files[0].text();
      if (text) { const r = await api('/api/observe/import', {json: {tool: toolSel.value, payload: JSON.parse(text), source: sid}}); notify(`${r.items} result${r.items === 1 ? '' : 's'} read: ${r.new} new incident${r.new === 1 ? '' : 's'}`, 'ok'); }
      else notify(src ? 'Nothing uploaded' : 'Import source added — post results to its webhook or upload a file', 'ok');
      m.remove(); renderObserve();
    } catch (e) { notify(e.message, 'err'); go.disabled = false; }
  }}, src ? 'Upload' : 'Add and import');
  const m = modal(src ? `Upload results: ${src.name}` : 'Import another tool’s results', h('div', {class: 'mbody'}, h('label', {class: 'f', style: 'margin-top:0'}, 'Tool'), toolSel, src ? null : [h('label', {class: 'f'}, 'Name'), nameIn], h('label', {class: 'f'}, 'Webhook token'), tokenIn,
    h('div', {class: 'hint'}, src ? `Tools post to ${src.hook} with the token in the X-Relay-Token header.` : 'After saving, tools post to /auth/observe/hook/<source id> with the token in the X-Relay-Token header. Monte Carlo, Bigeye, Acceldata, Metaplane, Elementary and Datadog monitors use this.'),
    h('label', {class: 'f'}, 'Results file'), file, ta,
    h('div', {class: 'row', style: 'justify-content:flex-end;margin-top:12px'}, h('button', {class: 'btn', type: 'button', onclick: () => m.remove()}, 'Cancel'), go)), true);
}
