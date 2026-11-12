/* ---------------- Validation queue (P10): every checkpoint an agent is waiting at - accept, send back with a comment,
   reassign; the dashboard steps that existed before (KPIs, prototype review, publishing review) open their page ---------------- */
const VIEW_LABEL = {process: 'Process map', fields: 'Fields & rules', plan: 'Plan & modules', kpis: 'KPIs', prototype: 'Prototype', gates: 'Review gates',
  mapping: 'Field mapping', table: 'Table', text: 'Text', link: 'Link'};
const secsText = s => s == null ? '-' : s < 60 ? `${Math.round(s)} s` : s < 3600 ? `${Math.round(s / 60)} min` : `${(s / 3600).toFixed(1)} h`;
async function renderValidate() {
  const main = $('#main');
  main.replaceChildren(skel('page'));
  const period = S.vperiod || '30d';
  let d;
  try { d = await api('/api/validate?period=' + period); } catch (e) { main.replaceChildren(h('div', {class: 'page'}, h('div', {class: 'note err'}, e.message))); return; }
  if (location.hash !== '#/validate') return;
  const me = S.me || {}, m = d.metrics;
  const act = async (c, what, body) => {
    try { await api(`/api/validate/${c.id}/${what}`, {json: body || {}}); notify(what === 'accept' ? 'Accepted' : what === 'send-back' ? 'Sent back' : 'Reassigned', 'ok'); renderValidate(); }
    catch (e) { notify(e.message, 'err'); }
  };
  const sendBack = c => {
    const ta = h('textarea', {rows: 4, placeholder: 'What should change? The agent re-reads with this comment.'});
    const ok = h('button', {class: 'btn primary', onclick: () => { if (!ta.value.trim()) return notify('Say what to change.', 'err'); mm.remove(); act(c, 'send-back', {comment: ta.value}); }}, 'Send back');
    const mm = modal(`Send back: ${c.name}`, h('div', {class: 'mbody'}, h('label', {class: 'f'}, 'Your comment'), ta, h('div', {class: 'row', style: 'justify-content:flex-end;margin-top:12px'}, ok)));
  };
  const reassign = async c => {
    const dir = await api('/api/directory');
    const sel = h('select', {class: 'sel'}, dir.users.map(u => h('option', {value: u.id, selected: u.id === c.assignee_id}, `${u.name} - ${u.email}`)));
    const ok = h('button', {class: 'btn primary', onclick: () => { mm.remove(); act(c, 'reassign', {to: sel.value}); }}, 'Reassign');
    const mm = modal(`Reassign: ${c.name}`, h('div', {class: 'mbody'}, h('label', {class: 'f'}, 'To'), sel, h('div', {class: 'row', style: 'justify-content:flex-end;margin-top:12px'}, ok)));
  };
  const evidence = c => {
    const ev = c.evidence || {};
    const bits = [];
    if (ev.summary) bits.push(h('div', {class: 'small'}, ev.summary));
    if (ev.items && Array.isArray(ev.items)) bits.push(h('ul', {class: 'small', style: 'margin:6px 0 0;padding-left:18px'}, ev.items.slice(0, 6).map(x => h('li', {}, typeof x === 'string' ? x : JSON.stringify(x)))));
    if (ev.counts) bits.push(h('div', {class: 'row small muted', style: 'gap:12px;margin-top:4px'}, Object.entries(ev.counts).map(([k, v]) => h('span', {}, h('b', {}, String(v)), ' ' + k))));
    return bits.length ? h('div', {class: 'cpev'}, bits) : null;
  };
  const item = c => h('div', {class: 'card cpitem', style: 'margin:0'},
    h('div', {class: 'row', style: 'align-items:flex-start;flex-wrap:nowrap;gap:14px'},
      h('div', {style: 'flex:1;min-width:0'},
        h('div', {class: 'row', style: 'gap:8px'}, h('span', {class: 'pill plain info'}, c.label), h('span', {class: 'small muted'}, `${c.module} - ${VIEW_LABEL[c.view] || c.view}`), c.agent ? h('span', {class: 'small muted'}, '- by ' + c.agent) : null),
        h('h3', {style: 'margin:6px 0 2px'}, c.name),
        evidence(c),
        h('div', {class: 'small muted', style: 'margin-top:6px'}, `Waiting ${ago(c.created)}` + (c.assignee_id ? (c.assignee_id === me.id ? ' - assigned to you' : ' - assigned') : c.team_id ? ' - for your team' : ''))),
      h('div', {class: 'stack', style: 'gap:6px;flex:none'},
        c.link ? h('a', {class: 'btn sm', href: c.link}, icon('external'), c.derived ? 'Open and decide' : 'Look at it') : null,
        c.derived ? null : [h('button', {class: 'btn sm primary', onclick: () => act(c, 'accept')}, icon('check'), 'Accept'),
          h('button', {class: 'btn sm', onclick: () => sendBack(c)}, 'Send back'),
          h('button', {class: 'btn sm ghost', onclick: () => reassign(c)}, 'Reassign')])));
  const mine = d.items.filter(c => c.assignee_id === me.id || c.derived), team = d.items.filter(c => !(c.assignee_id === me.id || c.derived));
  main.replaceChildren(h('div', {class: 'page'},
    pageHead({crumbs: [['Home', '#/'], ['Validation queue']], eyebrow: brandName() + ' - Your practice', title: 'Validation queue',
      promise: 'Every step an agent is waiting at. Accept it, send it back with what to change, or hand it to someone else - each decision is signed and audited.',
      actions: h('div', {class: 'segbtn', role: 'group', 'aria-label': 'Period'}, [['7d', '7 days'], ['30d', '30 days'], ['6m', '6 months']].map(([k, l]) => h('button', {class: period === k ? 'on' : '', 'aria-pressed': String(period === k), onclick: () => { S.vperiod = k; renderValidate(); }}, l)))}),
    h('div', {class: 'g5', style: 'margin-bottom:18px'},
      kpiTile('Waiting now', String(d.count), `${mine.length} for you`),
      kpiTile('Decided', String(m.decided), `in the last ${PERIOD_LABEL[period]}`),
      kpiTile('Right first time', m.rft == null ? '-' : fmtN(m.rft) + ' %', 'accepted without a send-back'),
      kpiTile('Median time to decide', secsText(m.median_seconds), 'from the agent asking to your answer'),
      kpiTile('Sent back', String(m.sent_back), 'with a comment the agent used')),
    d.items.length ? [
      mine.length ? [h('div', {class: 'section-title'}, h('h2', {}, 'For you'), h('span', {class: 'hint'}, `${mine.length}`)), h('div', {class: 'stack', style: 'gap:10px'}, mine.map(item))] : null,
      team.length ? [h('div', {class: 'section-title'}, h('h2', {}, 'For your team'), h('span', {class: 'hint'}, `${team.length}`)), h('div', {class: 'stack', style: 'gap:10px'}, team.map(item))] : null]
      : h('div', {class: 'card empty'}, h('h3', {}, 'Nothing is waiting for a person'), h('div', {class: 'muted'}, 'Agents pause here whenever a step needs your confirmation.')),
    m.people && m.people.length ? [h('div', {class: 'section-title'}, h('h2', {}, 'Who decided'), h('span', {class: 'hint'}, PERIOD_LABEL[period])),
      h('div', {class: 'card', style: 'padding:0;overflow:auto;margin:0'}, h('table', {class: 'utable'}, h('tr', {}, ['Person', 'Decided', 'Accepted', 'Median time'].map((t, i) => h('th', {class: i ? '' : 'l'}, t))),
        m.people.map(p => h('tr', {}, h('td', {}, p.name), h('td', {class: 'n'}, p.decided), h('td', {class: 'n'}, p.accepted), h('td', {class: 'n'}, secsText(p.median_seconds))))))] : null));
  document.title = `Validation queue - ${S.brand ? S.brand.full : 'RELAY by PASDACS'}`;
}
