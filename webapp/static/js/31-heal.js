/* ---------------- Self-healing (P16): cases from what the platform watches (refreshes, gates, sign-ins, schedules,
   integration runs, the work rows of Service desk / Integration analytics / Data observability); the journey
   Watch → Diagnose → Fix → Prove → Approve → Learn per case; evidence, diagnosis, before / after, rules learned.
   GET /api/heal/overview, /api/heal/cases/<id>. Colours are tokens only. ---------------- */
(function healStyles() {
  document.head.append(h('style', {}, `
  .hjourney{margin:0 0 6px}.hjourney li.done .dot{background:var(--ok);border-color:var(--ok)}.hjourney li.on .dot{background:var(--accent);border-color:var(--accent);box-shadow:0 0 0 3px var(--ring)}
  .hjourney li.done::before{background:var(--ok)}.hjourney li.on .jl{color:var(--accent)}
  .hba{width:100%;border-collapse:collapse;font-size:13px}.hba th{text-align:left;color:var(--ink-2);font-weight:600;padding:4px 8px 4px 0}.hba td{padding:5px 8px 5px 0;border-top:1px solid var(--line);vertical-align:top;overflow-wrap:anywhere}
  .hba td.b{color:var(--muted)}.hba td.a{font-weight:600}
  .hconf{height:6px;border-radius:3px;background:var(--surface-3);overflow:hidden;margin:4px 0 8px}.hconf i{display:block;height:100%;background:var(--accent)}
  .hkv{display:grid;grid-template-columns:max-content 1fr;gap:4px 12px;font-size:13px;margin:0}.hkv dt{color:var(--muted)}.hkv dd{margin:0;overflow-wrap:anywhere}
  .hrule{display:flex;gap:10px;align-items:flex-start;padding:8px 0;border-top:1px solid var(--line)}.hrule:first-child{border-top:0}.hrule .grow{flex:1;min-width:0}
  .hev{font-family:var(--mono);font-size:12px;white-space:pre-wrap;max-height:60vh;overflow:auto;background:var(--surface-2);padding:10px;border-radius:var(--radius-sm)}
  .hsig{font-family:var(--mono);font-size:11.5px;color:var(--ink-2)}
  `));
})();

const HL = {status: 'open', q: '', timer: null};
const HL_STATUS = {waiting: 'mute', diagnosing: 'run', diagnosed: 'you', sent_back: 'you', fixing: 'run', held: 'err', proven: 'you', applying: 'run', applied: 'ok', needs_code: 'info', recovered: 'ok', closed: 'mute', error: 'err'};
const hlStatus = c => h('span', {class: 'pill plain ' + (HL_STATUS[c.status] || 'mute')}, c.status_label || c.status);
const hlAge = s => s < 3600 ? `${Math.max(1, Math.round(s / 60))} min` : s < 86400 ? `${(s / 3600).toFixed(s < 7200 ? 1 : 0)} h` : `${Math.round(s / 86400)} day${Math.round(s / 86400) === 1 ? '' : 's'}`;
// what a rule's fix does, in words (heal.FIX_KINDS)
const HEAL_FIX_SAID = {rerun_extract: 'pull the tables again', renew_connection: 'ask the owner to sign in again', notify_hold: 'tell the people responsible and hold what depends on it',
  dashboard_revise: 'revise the dashboard definition', rerun_integration: 'run the integration again', schedule_update: 'update the schedule and resume it',
  threshold: 'tune the check’s threshold', retry_policy: 'set how often it retries', needs_code: 'a code change through AI SDLC'};
const HL_SOURCE = {project: 'Dashboard', connection: 'Connection', daxcheck: 'DAX checker', schedule: 'Schedule', integration: 'Integration', intan_work: 'Integration analytics', observe_work: 'Data observability', itsm_work: 'Service desk', person: 'Opened by a person'};

function hlJourney(steps, current, done) {
  return h('ol', {class: 'journey hjourney', 'aria-label': 'Journey'}, steps.map(([id, label], i) => h('li', {class: i < current ? 'done' : i === current ? 'on' : '', 'aria-current': i === current ? 'step' : null},
    h('span', {class: 'dot'}), h('div', {class: 'jl'}, `${i + 1} ${label}`), h('div', {class: 'js'}, i === current ? (done ? 'done' : 'now') : i < current ? 'done' : ' '))));
}

async function renderHeal() {
  const m = location.hash.match(/^#\/heal\/([\w-]+)/);
  clearTimeout(HL.timer);
  if (m) return renderHealCase(m[1]);
  const main = $('#main');
  const crumbs = [['Home', '#/'], ['All modules', '#/modules'], ['Self-healing']], eyebrow = brandName() + ' · Automation · Self-healing';
  const title = 'Failures fixed with approval';
  if (!$('#healpage')) main.replaceChildren(h('div', {class: 'page'}, pageHead({crumbs, eyebrow, title}), skel('cards')));
  let d;
  try { d = await api(`/api/heal/overview?status=${HL.status}`); }
  catch (e) { main.replaceChildren(h('div', {class: 'page'}, pageHead({crumbs, eyebrow, title}), h('div', {class: 'note err'}, e.message))); return; }
  if (!location.hash.startsWith('#/heal') || location.hash.match(/^#\/heal\//)) return;
  const s = d.summary, builder = !!d.can_edit;
  const head = pageHead({crumbs, eyebrow, title,
    promise: 'Refreshes, review gates, sign-ins, schedules, integration runs and the fixes other modules hand over are watched; each failure becomes a case — diagnosed with the logs and the lineage, fixed on a copy, applied only when a person approves, and kept as a rule for next time.',
    actions: [s.open ? h('span', {class: 'pill plain ' + (s.waiting_for_you ? 'you' : 'run')}, s.waiting_for_you ? `${s.waiting_for_you} waiting for you` : `${s.open} open`) : h('span', {class: 'pill plain ok'}, 'Nothing open'),
      builder ? h('button', {class: 'btn', type: 'button', onclick: async e => { e.target.disabled = true; try { const r = await api('/api/heal/watch', {method: 'POST'}); notify(`${r.opened.length} new case${r.opened.length === 1 ? '' : 's'} · ${r.seen} failure${r.seen === 1 ? '' : 's'} seen`, 'ok'); renderHeal(); } catch (err) { notify(err.message, 'err'); e.target.disabled = false; } }}, icon('play'), 'Watch now') : null,
      builder ? h('button', {class: 'btn', type: 'button', onclick: () => hlNewCase()}, icon('plus'), 'New case') : null,
      d.test_hooks && builder ? h('button', {class: 'btn', type: 'button', onclick: async e => { e.target.disabled = true; try { await api('/api/heal/test/seed', {method: 'POST'}); notify('Sample failures seeded', 'ok'); renderHeal(); } catch (err) { notify(err.message, 'err'); e.target.disabled = false; } }}, icon('dice'), 'Try the sample') : null]});
  const kpis = h('div', {class: 'g5'},
    kpiTile('Open cases', String(s.open), s.open ? `${s.waiting_for_you} need a person` : 'nothing open', {href: '#/heal', ...(s.open ? {} : {good: true})}),
    kpiTile('Fixed', String(s.fixed_30d), 'applied in the last 30 days'),
    kpiTile('Recovered', String(s.recovered), 'went away before a fix was needed'),
    kpiTile('Time to fix', s.median_fix_h == null ? '—' : hlAge(s.median_fix_h * 3600), 'median, seen to applied'),
    kpiTile('Rules', String(s.rules_total), `${(s.rules.learned || {}).n || 0} learned · ${(s.rules.builtin || {}).n || 0} built in`));
  const journey = h('div', {class: 'card', style: 'margin-top:16px'}, h('div', {class: 'card-head'}, h('h3', {}, 'The journey of every case'), h('span', {class: 'sp'}), h('span', {class: 'small muted'}, 'where the open cases are')),
    h('ol', {class: 'journey', 'aria-label': 'Journey'}, d.steps.map(([id, label], i) => h('li', {}, h('span', {class: 'dot', style: s.by_step[id] ? 'background:var(--accent);border-color:var(--accent)' : ''}), h('div', {class: 'jl'}, `${i + 1} ${label}`), h('div', {class: 'js'}, s.by_step[id] ? `${s.by_step[id]} case${s.by_step[id] === 1 ? '' : 's'}` : ' ')))),
    h('div', {class: 'confirm'}, [['Fix', 'the proposed fix and its test in a copy'], ['Approve', 'before it is applied']].map(([a, b]) => h('div', {}, h('span', {class: 'proven'}, icon('check')), h('span', {}, h('b', {}, a + ': '), b)))));
  const seg = h('div', {class: 'segbtn', role: 'group', 'aria-label': 'Status'}, [['open', 'Open'], ['applied', 'Applied'], ['recovered', 'Recovered'], ['needs_code', 'Needs code'], ['all', 'All']].map(([v, l]) => h('button', {type: 'button', class: HL.status === v ? 'on' : '', 'aria-pressed': String(HL.status === v), onclick: () => { HL.status = v; renderHeal(); }}, l)));
  const qIn = h('input', {type: 'search', placeholder: 'Find a case…', 'aria-label': 'Find a case', value: HL.q, style: 'max-width:260px', oninput: e => { HL.q = e.target.value; drawTable(); }});
  const tableBox = h('div', {});
  function drawTable() {
    const rows = d.cases.filter(c => !HL.q || `${c.title} ${c.place} ${c.signature} ${c.kind_label}`.toLowerCase().includes(HL.q.toLowerCase()));
    const row = c => h('tr', {tabindex: '0', role: 'button', 'aria-label': `${c.title}: ${c.status_label}. Open the case`, style: 'cursor:pointer', onclick: () => { location.hash = '#/heal/' + c.id; }, onkeydown: e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); location.hash = '#/heal/' + c.id; } }},
      h('td', {}, h('b', {}, c.title), h('div', {class: 'small muted'}, `${c.id} · ${c.kind_label}${c.rule ? ' · rule, seen ' + c.rule.seen + '×' : ''}`)),
      h('td', {}, c.place || '—', h('div', {class: 'small muted'}, HL_SOURCE[c.source] || c.source)), h('td', {}, hlAge(c.age_s)), h('td', {}, h('span', {class: 'chipx'}, c.route_label)), h('td', {}, hlStatus(c)),
      h('td', {}, h('span', {class: 'small muted'}, `${c.step_index + 1} ${d.steps[c.step_index][1]}`)));
    tableBox.replaceChildren(rows.length ? h('div', {class: 'card', style: 'padding:0;overflow:auto;margin:0'}, h('table', {class: 'utable'}, h('thead', {}, h('tr', {}, ['What', 'Where', 'Since', 'Route', 'Status', 'Step'].map(t => h('th', {class: 'l', scope: 'col'}, t)))), h('tbody', {}, rows.map(row))))
      : h('div', {class: 'card empty', style: 'margin:0'}, h('h3', {}, HL.status === 'open' ? 'Nothing to heal right now' : 'Nothing here'), h('div', {class: 'muted', style: 'max-width:600px;margin:0 auto'}, HL.status === 'open' ? 'Every refresh, gate, sign-in, schedule and integration run Relay watches is fine, and no module has handed over a fix. A failure becomes a case here within minutes; press Watch now to look at once.' : 'Change the filter.')));
  }
  drawTable();
  const rulesCard = h('div', {class: 'card', style: 'margin:0'}, h('div', {class: 'card-head'}, h('h3', {}, 'Rules learned'), h('span', {class: 'sp'}), h('span', {class: 'small muted'}, 'a matching case proposes the rule\'s fix at once')),
    d.rules.length ? h('div', {}, d.rules.slice(0, 40).map(r => h('div', {class: 'hrule'},
      h('div', {class: 'grow'}, h('div', {}, h('b', {}, r.title), ' ', h('span', {class: 'pill plain ' + (r.origin === 'learned' ? 'ok' : 'mute')}, r.origin === 'learned' ? 'learned' : 'built in'), r.enabled ? null : h('span', {class: 'pill plain err', style: 'margin-left:6px'}, 'off')),
        h('div', {class: 'small muted', title: r.signature}, [`Fix: ${HEAL_FIX_SAID[(r.fix || {}).kind] || ((r.fix || {}).kind || 'none yet').replace(/_/g, ' ')} · seen ${r.seen} time${r.seen === 1 ? '' : 's'} · applied ${r.applied} time${r.applied === 1 ? '' : 's'}`, r.learned_from ? ` · learned from case ${r.learned_from}` : ''])),
      builder ? h('button', {class: 'btn sm', type: 'button', 'aria-label': `${r.enabled ? 'Disable' : 'Enable'} the rule ${r.title}`, onclick: async e => { e.target.disabled = true; try { await api(`/api/heal/rules/${r.id}/enable`, {method: 'POST', json: ({enabled: !r.enabled})}); notify(r.enabled ? 'Rule disabled' : 'Rule enabled', 'ok'); renderHeal(); } catch (err) { notify(err.message, 'err'); e.target.disabled = false; } }}, r.enabled ? 'Disable' : 'Enable') : null)))
      : h('div', {class: 'muted small'}, 'No rules yet: the first applied fix becomes one.'));
  main.replaceChildren(h('div', {class: 'page', id: 'healpage'}, head, kpis, journey,
    h('div', {class: 'row', style: 'margin:16px 0 10px;gap:10px;flex-wrap:wrap'}, seg, qIn, h('span', {class: 'sp', style: 'flex:1'}), h('span', {class: 'small muted'}, agentNow(d.worker))),
    tableBox, h('div', {class: 'g2', style: 'margin-top:16px'}, rulesCard, hlInfoCard())));
  document.title = `Self-healing · ${S.brand ? S.brand.full : 'RELAY by PASDACS'}`;
  if (d.cases.some(c => ['diagnosing', 'fixing', 'applying'].includes(c.status))) HL.timer = setTimeout(() => { if (location.hash === '#/heal') renderHeal(); }, 5000);
}

function hlInfoCard() {
  return h('div', {class: 'card', style: 'margin:0'}, h('div', {class: 'card-head'}, h('h3', {}, 'What is watched')),
    h('ul', {class: 'small', style: 'margin:0;padding-left:18px;line-height:1.7'},
      h('li', {}, 'Dashboards: extract failures, stale daily extracts, review gates that fail'),
      h('li', {}, 'Connections whose sign-in expired; schedules that paused (mail account, sign-in, repeated failures)'),
      h('li', {}, 'The DAX checker\'s heartbeat; integration runs that failed with a retry-able error'),
      h('li', {}, 'Fixes handed over by Service desk, Integration analytics and Data observability')),
    h('div', {class: 'small muted', style: 'margin-top:8px'}, 'A fix is applied only through the owning module — the dashboard\'s own refresh or revise path, Connections (renew, or a guarded write with its own approval), Schedules, Data observability — never by editing files behind a module\'s back.'));
}

function hlNewCase() {
  const t = h('input', {type: 'text', placeholder: 'What failed? e.g. Finance pipeline load stopped on Sunday', 'aria-label': 'What failed', style: 'width:100%'});
  const w = h('textarea', {rows: 4, placeholder: 'What you saw, when, and anything the agent should read (optional)', 'aria-label': 'Details', style: 'width:100%'});
  const p = h('input', {type: 'text', placeholder: 'Where (system, dashboard, pipeline)', 'aria-label': 'Where', style: 'width:100%'});
  const r = h('select', {'aria-label': 'Route'}, h('option', {value: 'config'}, 'Configuration fix (Self-healing)'), h('option', {value: 'code'}, 'Code fix (AI SDLC)'));
  const mm = modal('New case', h('div', {}, h('p', {class: 'small muted'}, 'Open a case for something the watchers did not see. Relay diagnoses it with the evidence it can read; nothing changes until you approve the fix.'),
    h('label', {class: 'f'}, 'What failed'), t, h('label', {class: 'f', style: 'margin-top:8px'}, 'Details'), w, h('label', {class: 'f', style: 'margin-top:8px'}, 'Where'), p, h('label', {class: 'f', style: 'margin-top:8px'}, 'Route'), r,
    h('div', {class: 'row', style: 'justify-content:flex-end;margin-top:12px'}, h('button', {class: 'btn primary', type: 'button', onclick: async e => { e.target.disabled = true; try { const c = await api('/api/heal/cases', {method: 'POST', json: ({title: t.value, what: w.value, place: p.value, route: r.value})}); mm.remove(); location.hash = '#/heal/' + c.id; } catch (err) { notify(err.message, 'err'); e.target.disabled = false; } }}, 'Open the case'))));
}

async function renderHealCase(id) {
  const main = $('#main');
  let c;
  try { c = await api('/api/heal/cases/' + id); }
  catch (e) { main.replaceChildren(h('div', {class: 'page'}, pageHead({crumbs: [['Home', '#/'], ['Self-healing', '#/heal'], ['Case']], eyebrow: brandName() + ' · Self-healing', title: 'Case'}), h('div', {class: 'note err'}, e.message))); return; }
  if (location.hash !== '#/heal/' + id) return;
  const builder = !!(S.me && (S.me.admin || S.me.builder));
  const steps = [['watch', 'Watch'], ['diagnose', 'Diagnose'], ['fix', 'Fix'], ['prove', 'Prove'], ['approve', 'Approve'], ['learn', 'Learn']];
  const running = ['diagnosing', 'fixing', 'applying'].includes(c.status);
  const crumbs = [['Home', '#/'], ['Self-healing', '#/heal'], [c.id]], eyebrow = brandName() + ' · Self-healing · ' + (HL_SOURCE[c.source] || c.source);
  const openCp = c.checkpoint && c.checkpoint.status === 'open' ? c.checkpoint : null;
  const decide = async (cp, accept) => {
    let comment = null;
    if (!accept) { comment = await askText('Send it back', {label: 'What should change?', hint: 'The agent gets your note and works on it again.', required: true, ok: 'Send back'}); if (!comment) return; }
    try { await api(`/api/validate/${cp.id}/${accept ? 'accept' : 'send-back'}`, {method: 'POST', json: ({comment})}); notify(accept ? 'Accepted — signed and audited' : 'Sent back', 'ok'); renderHealCase(id); } catch (e) { notify(e.message, 'err'); }
  };
  const head = pageHead({crumbs, eyebrow, title: c.title, promise: c.what || '',
    actions: [hlStatus(c), running ? h('span', {class: 'pill run'}, 'Working…') : null,
      builder && !c.closed && !running ? h('button', {class: 'btn', type: 'button', onclick: async e => { const btn = e.currentTarget; const note = await askText(c.diagnosis ? 'Diagnose again' : 'Diagnose with the agent', {label: 'Anything the agent should know?', hint: 'Optional. The agent reads the logs and the lineage either way.', ok: 'Diagnose'}); if (note === null) return; btn.disabled = true; try { await api(`/api/heal/cases/${id}/diagnose`, {method: 'POST', json: ({comment: note || null})}); notify('Diagnosis queued, the agent starts on it next', 'ok'); renderHealCase(id); } catch (err) { notify(err.message, 'err'); btn.disabled = false; } }}, icon('spark'), c.diagnosis ? 'Diagnose again with the agent' : 'Diagnose with the agent') : null,
      builder && !c.closed ? h('button', {class: 'btn', type: 'button', onclick: async () => { const why = await askText('Close this case', {label: 'Why does it close?', hint: 'Kept in the audit log.', required: true, ok: 'Close the case'}); if (!why) return; try { await api(`/api/heal/cases/${id}/close`, {method: 'POST', json: ({comment: why})}); notify('Case closed', 'ok'); renderHealCase(id); } catch (e) { notify(e.message, 'err'); } }}, 'Close case') : null]});
  const journey = h('div', {class: 'card'}, hlJourney(steps, c.step_index, ['applied', 'closed', 'recovered'].includes(c.status)),
    h('div', {class: 'small muted'}, c.note ? [h('b', {}, 'Note: '), c.note] : c.status === 'waiting' ? 'Waiting for a diagnosis: a rule did not match, so the agent reads the evidence (queued) — or press Diagnose.' : c.status === 'diagnosed' ? 'The proposed fix waits for you: confirm it (or send it back with a note) and Relay tests it on a copy.' : c.status === 'proven' ? 'Proven on a copy. Approve to apply it through the owning module; nothing has changed yet.' : c.status === 'applying' ? 'Applying through the owning module' + (c.applied && c.applied.write_checkpoint ? ' — the guarded write waits for its own approval in the validation queue.' : '…') : ''));
  const seen = h('div', {class: 'card', style: 'margin:0'}, h('div', {class: 'card-head'}, h('h3', {}, 'What the watcher saw')),
    h('dl', {class: 'hkv'}, h('dt', {}, 'Where'), h('dd', {}, c.place || '—'), h('dt', {}, 'Since'), h('dd', {}, `${when(c.since)} (${hlAge(c.age_s)})`), h('dt', {}, 'Source'), h('dd', {}, (HL_SOURCE[c.source] || c.source) + ' · ' + c.source_id),
      h('dt', {}, 'Signature'), h('dd', {}, h('span', {class: 'hsig'}, c.signature), ' · ', c.kind_label), h('dt', {}, 'Route'), h('dd', {}, h('span', {class: 'chipx'}, c.route_label)),
      c.rule ? [h('dt', {}, 'Rule'), h('dd', {}, `${c.rule.title} — ${c.rule.origin === 'learned' ? 'learned' : 'built in'}, seen ${c.rule.seen} time${c.rule.seen === 1 ? '' : 's'}, applied ${c.rule.applied}`)] : null,
      c.work ? [h('dt', {}, 'Handed over by'), h('dd', {}, `${{intan: 'Integration analytics', observe: 'Data observability', itsm: 'Service desk'}[c.work.module] || c.work.module} (${c.work.id})`)] : null),
    c.what ? h('div', {class: 'small', style: 'margin-top:10px;white-space:pre-wrap'}, c.what) : null);
  const evidence = h('div', {class: 'card', style: 'margin:0'}, h('div', {class: 'card-head'}, h('h3', {}, 'Evidence'), h('span', {class: 'sp'}), h('span', {class: 'small muted'}, `${c.evidence_rows.length} row${c.evidence_rows.length === 1 ? '' : 's'} · ${c.evidence_files.length} file${c.evidence_files.length === 1 ? '' : 's'}`)),
    c.evidence_rows.length ? h('table', {class: 'hba'}, h('thead', {}, h('tr', {}, ['When', 'What', 'Detail'].map(t => h('th', {scope: 'col'}, t)))), h('tbody', {}, c.evidence_rows.slice(0, 12).map(r => h('tr', {}, h('td', {class: 'b'}, r.when || ''), h('td', {}, r.what || ''), h('td', {}, r.detail || ''))))) : h('div', {class: 'muted small'}, 'No evidence rows yet.'),
    c.evidence_files.length ? h('div', {class: 'row', style: 'margin-top:10px;gap:6px;flex-wrap:wrap'}, c.evidence_files.map(f => h('button', {class: 'btn sm', type: 'button', onclick: async () => { try { const r = await api(`/api/heal/cases/${id}/file/${encodeURIComponent(f)}`); modal(f, h('pre', {class: 'hev'}, r.text), true); } catch (e) { notify(e.message, 'err'); } }}, f))) : null);
  const dg = c.diagnosis;
  const fx = dg && dg.fix ? dg.fix : null;
  const diagnosis = h('div', {class: 'card', style: 'margin:0'}, h('div', {class: 'card-head'}, h('h3', {}, 'Diagnosis'), h('span', {class: 'sp'}), dg ? h('span', {class: 'small muted'}, dg.from_rule ? 'from a rule — the agent run was skipped' : 'by the agent') : null),
    dg ? [h('div', {}, dg.cause), h('div', {class: 'small muted', style: 'margin-top:6px'}, `Confidence ${Math.round((dg.confidence || 0) * 100)} %`), h('div', {class: 'hconf', role: 'img', 'aria-label': `Confidence ${Math.round((dg.confidence || 0) * 100)} %`}, h('i', {style: `width:${Math.round((dg.confidence || 0) * 100)}%`})),
      fx ? h('dl', {class: 'hkv'}, h('dt', {}, 'Fix'), h('dd', {}, h('b', {}, fx.text || fx.kind), ` — ${fx.kind} through ${fx.module || '—'} · risk ${fx.risk || 'low'}`), Object.keys(fx.change || {}).length ? [h('dt', {}, 'Change'), h('dd', {}, Object.entries(fx.change).map(([k, v]) => `${k}: ${typeof v === 'object' ? JSON.stringify(v) : v}`).join(' · '))] : null,
        dg.test ? [h('dt', {}, 'Test on a copy'), h('dd', {}, `${dg.test.what || ''} ${dg.test.how ? '— ' + dg.test.how : ''} ${dg.test.expect ? '(pass: ' + dg.test.expect + ')' : ''}`)] : null, dg.notes ? [h('dt', {}, 'Notes'), h('dd', {}, dg.notes)] : null) : null,
      openCp && openCp.kind === 'heal.diagnosis' ? h('div', {class: 'note', style: 'margin-top:10px'}, h('b', {}, 'Your turn: '), 'confirm the proposed fix and Relay tests it on a copy. ', h('a', {href: '#/validate'}, 'In the validation queue'), builder ? h('div', {class: 'row', style: 'margin-top:8px;gap:8px'}, h('button', {class: 'btn primary sm', type: 'button', onclick: () => decide(openCp, true)}, 'Confirm the fix'), h('button', {class: 'btn sm', type: 'button', onclick: () => decide(openCp, false)}, 'Send back')) : null) : null]
      : h('div', {class: 'muted small'}, c.status === 'diagnosing' ? 'The agent is reading the evidence…' : 'No diagnosis yet.'));
  const f = c.fix;
  const rows = f ? (() => { const keys = {}; (f.before || []).forEach(([k, v]) => { (keys[k] = keys[k] || ['', ''])[0] = v; }); (f.after || []).forEach(([k, v]) => { (keys[k] = keys[k] || ['', ''])[1] = v; }); return Object.entries(keys); })() : [];
  const proof = h('div', {class: 'card', style: 'margin:0'}, h('div', {class: 'card-head'}, h('h3', {}, 'Fix on a copy: before / after'), h('span', {class: 'sp'}), f && f.test ? h('span', {class: 'pill plain ' + (f.test.ok ? 'ok' : f.test.recovered ? 'ok' : 'err')}, f.test.ok ? 'Test passed' : f.test.recovered ? 'Recovered' : 'Test failed') : null),
    f ? [rows.length ? h('table', {class: 'hba'}, h('thead', {}, h('tr', {}, ['Setting', 'Before', 'After'].map(t => h('th', {scope: 'col'}, t)))), h('tbody', {}, rows.map(([k, [b, a]]) => h('tr', {}, h('td', {}, k), h('td', {class: 'b'}, b || '—'), h('td', {class: 'a'}, a || '—'))))) : null,
      h('div', {class: 'small', style: 'margin-top:8px'}, h('b', {}, 'Test: '), (f.test || {}).text || '—'), f.test && f.test.diff && f.test.diff.length ? h('ul', {class: 'small muted', style: 'margin:6px 0 0;padding-left:18px'}, f.test.diff.slice(0, 10).map(x => h('li', {}, x))) : null,
      openCp && openCp.kind === 'heal.apply' ? h('div', {class: 'note', style: 'margin-top:10px'}, h('b', {}, 'Your turn: '), `approve and Relay applies it through ${f.module}. `, h('a', {href: '#/validate'}, 'In the validation queue'), builder ? h('div', {class: 'row', style: 'margin-top:8px;gap:8px'}, h('button', {class: 'btn primary sm', type: 'button', onclick: () => decide(openCp, true)}, 'Approve & apply'), h('button', {class: 'btn sm', type: 'button', onclick: () => decide(openCp, false)}, 'Send back')) : null) : null]
      : h('div', {class: 'muted small'}, c.status === 'fixing' ? 'Relay is applying the change on a copy and running the test…' : 'Not fixed on a copy yet — it happens after you confirm the diagnosis.'));
  const ap = c.applied;
  const applied = h('div', {class: 'card', style: 'margin:0'}, h('div', {class: 'card-head'}, h('h3', {}, 'Applied & learned')),
    ap ? [h('div', {}, ap.result || '—'), h('div', {class: 'small muted', style: 'margin-top:6px'}, `${ap.module || ''} · by ${ap.who || ''} · ${when(ap.when)}`), ap.write_checkpoint ? h('div', {class: 'small', style: 'margin-top:6px'}, 'The guarded write has its own approval: ', h('a', {href: '#/validate'}, 'validation queue')) : null,
      ap.sdlc ? h('div', {class: 'small', style: 'margin-top:6px'}, 'Change request: ', h('a', {href: ap.sdlc.link}, ap.sdlc.id)) : null, c.rule ? h('div', {class: 'small', style: 'margin-top:6px'}, h('b', {}, 'Rule kept: '), `${c.rule.title} (applied ${c.rule.applied} time${c.rule.applied === 1 ? '' : 's'})`) : null]
      : h('div', {class: 'muted small'}, c.status === 'recovered' ? 'The failure went away before a fix was needed; nothing was applied.' : 'Nothing applied yet.'));
  const runs = h('div', {class: 'card', style: 'margin:0'}, h('div', {class: 'card-head'}, h('h3', {}, 'Runs and activity'), h('span', {class: 'sp'}), h('span', {class: 'small muted'}, `${c.runs.length} agent run${c.runs.length === 1 ? '' : 's'}`)),
    c.runs.length ? h('div', {class: 'small muted', style: 'margin-bottom:6px'}, c.runs.map(r => `${r.stage} · ${r.model || ''} · ${r.turns || 0} turns · $${(r.cost_usd || 0).toFixed(2)} · ${r.ok ? 'ok' : 'failed'}`).join(' | ')) : null,
    c.activity.length ? h('div', {class: 'small', style: 'max-height:260px;overflow:auto'}, c.activity.slice(-20).map(e => h('div', {class: 'row', style: 'gap:8px;padding:3px 0;border-top:1px solid var(--line)'}, h('span', {class: 'muted', style: 'flex:none;width:74px'}, clock(e.ts)), h('span', {style: 'min-width:0;overflow-wrap:anywhere;color:' + (e.level === 'error' ? 'var(--err)' : e.level === 'warn' ? 'var(--warn)' : 'inherit')}, e.text || (e.tool ? `${e.tool}: ${e.detail || ''}` : e.kind))))) : h('div', {class: 'muted small'}, 'Nothing yet.'));
  main.replaceChildren(h('div', {class: 'page', id: 'healcase'}, head, journey, h('div', {class: 'g2', style: 'margin-top:16px'}, seen, evidence), h('div', {class: 'g2', style: 'margin-top:16px'}, diagnosis, proof), h('div', {class: 'g2', style: 'margin-top:16px'}, applied, runs)));
  document.title = `${c.title} · Self-healing · ${S.brand ? S.brand.full : 'RELAY by PASDACS'}`;
  if (running) HL.timer = setTimeout(() => { if (location.hash === '#/heal/' + id) renderHealCase(id); }, 4000);
}
