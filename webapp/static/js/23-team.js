/* ---------------- Team & agents (P10): who — person or agent — is on what right now, what is waiting for a person, where the
   time goes, agent quality, hours and FTE saved against the AI cost — all from run records, checkpoints and usage (GET /api/team).
   Builders and leads only. ---------------- */
const TEAM_STATUS = {working: ['Working', 'run'], validating: ['Validating', 'you'], waiting: ['Waiting for Relay', 'run'], done: ['Done', 'ok'], idle: ['Idle', 'plain']};
async function renderTeam() {
  const main = $('#main'), me = S.me || {};
  if (me.builder === false) {
    main.replaceChildren(h('div', {class: 'page'}, pageHead({crumbs: [['Home', '#/'], ['Team & agents']], eyebrow: brandName() + ' · Your practice', title: 'Team & agents'}),
      h('div', {class: 'card empty'}, h('h3', {}, 'For builders and leads'), h('p', {}, 'This page shows what the team and the agents are working on. Your reports, answers and alerts are on Home.'), h('a', {class: 'btn', href: '#/'}, 'Home'))));
    return;
  }
  main.replaceChildren(skel('page'));
  const period = S.tperiod || '30d';
  let d;
  try { d = await api('/api/team?period=' + period); } catch (e) { main.replaceChildren(h('div', {class: 'page'}, h('div', {class: 'note err'}, e.message))); return; }
  if (location.hash !== '#/team') return;
  const k = d.kpis, v = d.value, b = d.brand || {}, pl = PERIOD_LABEL[period];
  const cur = b.currency || '';
  const money = x => x == null ? '—' : `${cur}${fmtN(x, 0)}`;
  const nowRow = r => h('tr', {},
    h('td', {}, h('span', {class: 'row', style: 'gap:8px;flex-wrap:nowrap'}, h('span', {class: 'tav ' + r.kind}, r.kind === 'agent' ? icon('cpu') : (r.who || '?').split(/\s+/).map(x => x[0]).join('').slice(0, 2).toUpperCase()), h('span', {}, h('b', {}, r.who), h('div', {class: 'small muted'}, r.role)))),
    h('td', {class: 'l'}, r.link ? h('a', {href: r.link}, r.on) : r.on, r.model && modelName(r.model) ? h('div', {class: 'small muted'}, modelName(r.model)) : null),
    h('td', {class: 'l'}, r.module || ''), h('td', {class: 'l'}, (([t, c]) => h('span', {class: 'pill ' + c}, t))(TEAM_STATUS[r.status] || [r.status, 'plain'])),
    h('td', {class: 'n'}, r.since ? ago(r.since) : '—'));
  const agentHours = d.months.map(m => [m.month, m.agent_hours]), peopleHours = d.months.map(m => [m.month, m.people_hours]);
  const accepted = d.months.filter(m => m.accepted_pct != null).map(m => [m.month, m.accepted_pct]);
  main.replaceChildren(h('div', {class: 'page'},
    pageHead({crumbs: [['Home', '#/'], ['Team & agents']], eyebrow: brandName() + ' · Your practice', title: 'Team & agents',
      promise: 'What your people and your agents are working on right now, what is waiting for a person, and where the time goes — from the run records, the validation queue and the cost ledger.',
      actions: h('div', {class: 'segbtn', role: 'group', 'aria-label': 'Period'}, Object.entries(PERIOD_LABEL).map(([kk, l]) => h('button', {class: period === kk ? 'on' : '', 'aria-pressed': String(period === kk), onclick: () => { S.tperiod = kk; renderTeam(); }}, l)))}),
    h('div', {class: 'g5', style: 'margin-bottom:18px'},
      kpiTile('People', String(k.people), `${k.builders} builder${k.builders === 1 ? '' : 's'} · ${k.leads} lead${k.leads === 1 ? '' : 's'}`),
      kpiTile('Agents working', String(k.agents_now), `${k.runs} run${k.runs === 1 ? '' : 's'} in ${pl}${k.queued ? ` · ${k.queued} queued` : ''} · one AI job at a time`),
      kpiTile('Waiting for a person', String(k.waiting), k.waiting ? `oldest ${fmtN(k.waiting_oldest_h)} h · median ${fmtN(k.waiting_median_h)} h` : 'nothing waiting', {href: '#/validate'}),
      kpiTile('Hours of agent work', fmtN(k.agent_hours), `people spent ${fmtN(k.people_hours)} h deciding`),
      kpiTile('Accepted without changes', k.rft == null ? '—' : fmtN(k.rft) + ' %', k.decided ? `${k.accepted} accepted · ${k.sent_back} sent back` : 'no decisions yet')),
    h('div', {class: 'g-side'},
      h('div', {class: 'stack'},
        h('div', {class: 'card', style: 'margin:0;padding:0;overflow:auto'}, h('div', {class: 'card-head', style: 'padding:14px 18px 0'}, h('h3', {}, 'Who is working on what'), h('span', {class: 'sp'}), h('span', {class: 'small muted'}, 'right now')),
          d.now.length ? h('table', {class: 'utable'}, h('tr', {}, ['Who', 'Working on', 'Module', 'Status', 'For'].map((t, i) => h('th', {class: i < 4 ? 'l' : ''}, t))), d.now.map(nowRow))
            : h('div', {class: 'muted small', style: 'padding:8px 18px 16px'}, 'Nothing is running and nothing is waiting for a person.')),
        h('div', {class: 'g2'},
          h('div', {class: 'card', style: 'margin:0'}, h('div', {class: 'card-head'}, h('h3', {}, 'Hours of agent work'), h('span', {class: 'sp'}), h('span', {class: 'small muted'}, 'per month')),
            colChart(agentHours, {label: `Agent hours per month: ${agentHours.map(r => `${r[0]} ${fmtN(r[1])}`).join(', ')}`, unit: ' h'}), asTable(['Month', 'Agent hours'], agentHours.map(r => [r[0], fmtN(r[1])]))),
          h('div', {class: 'card', style: 'margin:0'}, h('div', {class: 'card-head'}, h('h3', {}, 'People’s time to decide'), h('span', {class: 'sp'}), h('span', {class: 'small muted'}, 'from the agent asking to the answer')),
            colChart(peopleHours, {label: `Hours people spent deciding per month: ${peopleHours.map(r => `${r[0]} ${fmtN(r[1])}`).join(', ')}`, unit: ' h'}), asTable(['Month', 'Hours deciding', 'Decisions'], d.months.map(m => [m.month, fmtN(m.people_hours), String(m.decided)])))),
        h('div', {class: 'card', style: 'margin:0;padding:0;overflow:auto'}, h('div', {class: 'card-head', style: 'padding:14px 18px 0'}, h('h3', {}, 'People'), h('span', {class: 'sp'}), h('span', {class: 'small muted'}, pl)),
          h('table', {class: 'utable'}, h('tr', {}, ['Person', 'Role', 'Decided', 'Accepted', 'Sent back', 'Median time', 'Hours deciding', 'Open now'].map((t, i) => h('th', {class: i < 2 ? 'l' : ''}, t))),
            d.people.map(p => h('tr', {}, h('td', {}, p.name), h('td', {class: 'l'}, p.role), h('td', {class: 'n'}, p.decided), h('td', {class: 'n'}, p.accepted), h('td', {class: 'n'}, p.sent_back),
              h('td', {class: 'n'}, secsText(p.median_seconds)), h('td', {class: 'n'}, fmtN(p.hours_deciding, 2)), h('td', {class: 'n'}, p.open ? h('a', {href: '#/validate'}, String(p.open)) : '0'))))),
        h('div', {class: 'card', style: 'margin:0;padding:0;overflow:auto'}, h('div', {class: 'card-head', style: 'padding:14px 18px 0'}, h('h3', {}, 'Agents'), h('span', {class: 'sp'}), h('span', {class: 'small muted'}, `${pl} · one role per stage`)),
          d.agents.length ? h('table', {class: 'utable'}, h('tr', {}, ['Agent', 'Runs', 'Finished', 'Hours', 'AI cost', 'Accepted', 'Sent back', 'Models'].map((t, i) => h('th', {class: i === 0 || i === 7 ? 'l' : ''}, t))),
            d.agents.map(a => h('tr', {}, h('td', {}, h('b', {}, a.agent), h('div', {class: 'small muted'}, a.does || '')), h('td', {class: 'n'}, a.runs), h('td', {class: 'n'}, a.ok_pct == null ? '—' : fmtN(a.ok_pct) + ' %'),
              h('td', {class: 'n'}, fmtN(a.hours, 2)), h('td', {class: 'n'}, usd(a.cost_usd)), h('td', {class: 'n'}, a.accepted), h('td', {class: 'n'}, a.sent_back), h('td', {class: 'l small'}, a.models.map(modelName).join(', ')))))
            : h('div', {class: 'muted small', style: 'padding:8px 18px 16px'}, `No agent runs in the last ${pl}.`),
          (d.catalogue || []).length ? h('details', {class: 'astable', style: 'padding:0 18px 14px'}, h('summary', {}, `Every Relay agent (${d.catalogue.length})`),   // the roles behind every module's jobs, by name
            h('table', {class: 'utable', style: 'margin-top:6px'}, h('tr', {}, h('th', {class: 'l'}, 'Agent'), h('th', {class: 'l'}, 'What it does')),
              d.catalogue.map(a => h('tr', {}, h('td', {}, h('b', {}, a.agent)), h('td', {class: 'l small'}, a.does))))) : null)),
      h('div', {class: 'stack'},
        h('div', {class: 'card', style: 'margin:0'}, h('div', {class: 'card-head'}, h('h3', {}, 'Agent quality'), h('span', {class: 'sp'}), h('span', {class: 'small muted'}, pl)),
          lineChart(accepted, {min: 0, max: 100, unit: ' %', label: `Accepted without changes by month: ${accepted.map(r => `${r[0]} ${fmtN(r[1])} %`).join(', ')}`}),
          h('dl', {class: 'kv', style: 'grid-template-columns:1fr auto;margin-top:10px'}, [['Accepted without changes', k.rft == null ? '—' : fmtN(k.rft) + ' %'], ['Sent back with a comment', k.decided ? fmtN(100 * k.sent_back / k.decided) + ' %' : '—'],
            ['Fix rounds', `${k.fix_rounds} in ${k.work_runs} run${k.work_runs === 1 ? '' : 's'}`], ['Runs right first time', k.run_rft == null ? '—' : fmtN(k.run_rft) + ' %']].flatMap(([t, x]) => [h('dt', {}, t), h('dd', {style: 'font-weight:600;text-align:right'}, x)]))),
        h('div', {class: 'card', style: 'margin:0'}, h('div', {class: 'card-head'}, h('h3', {}, 'Saved vs AI cost'), h('span', {class: 'sp'}), h('span', {class: 'small muted'}, pl)),
          h('div', {class: 'mv', style: 'font-size:26px'}, `${fmtN(v.hours)} h`), h('div', {class: 'small muted'}, `≈ ${fmtN(v.fte, 2)} FTE of repeated work (${fmtN(v.working_hours, 0)} working hours in the period)`),
          h('dl', {class: 'kv', style: 'grid-template-columns:1fr auto;margin-top:10px'}, [['Value at the hourly rate', v.rate ? money(v.value) : 'set a rate'], ['AI cost', `${usd(k.ai_cost_usd)}${v.usd_rate !== 1 ? ` · ${money(v.ai_cost)}` : ''}`], ['Net', v.rate ? money(v.net) : '—']].flatMap(([t, x]) => [h('dt', {}, t), h('dd', {style: 'font-weight:600;text-align:right'}, x)])),
          v.rate ? null : h('div', {class: 'hint'}, me.admin ? [h('a', {href: '#/admin/branding', style: 'text-decoration:underline'}, 'Set the hourly rate'), ' under Admin › Branding to see the value and the net.'] : 'An admin sets the hourly rate under Admin › Branding to show the value and the net.')),
        h('div', {class: 'card', style: 'margin:0'}, h('div', {class: 'card-head'}, h('h3', {}, 'Waiting for a person'), h('span', {class: 'sp'}), h('a', {class: 'small', href: '#/validate'}, 'Queue →')),
          d.waiting.length ? h('div', {class: 'stack', style: 'gap:6px'}, d.waiting.map(w => h('a', {href: w.link || '#/validate', class: 'wait'}, h('div', {class: 'wt'}, h('b', {}, w.name), h('small', {}, `${w.module} · ${VIEW_LABEL[w.view] || w.view}${w.assignee ? ' · ' + w.assignee : ''}`)), h('span', {class: 'pill ' + ((Date.now() / 1000 - w.created) > 86400 ? 'err' : (Date.now() / 1000 - w.created) > 3600 ? 'you' : 'plain')}, ago(w.created)))))
            : h('div', {class: 'muted small', style: 'padding:6px 0'}, 'Nothing is waiting.')),
        h('div', {class: 'card', style: 'margin:0'}, h('h3', {}, 'How these are counted'), h('div', {class: 'rules', style: 'margin-top:8px'},
          ['Agent hours: run time of every agent stage', 'People’s time: from a checkpoint opening to the decision', 'Accepted without changes: accepted ÷ decided', 'AI cost: the agent’s own estimate per run, plus warehouse queries'].map(t => h('div', {}, icon('info'), t))))))));
  document.title = `Team & agents · ${S.brand ? S.brand.full : 'RELAY by PASDACS'}`;
}
