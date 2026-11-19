/* ---------------- D2D Relay: Relay's team on a dashboard (items 68 and 73). The plan's "Review and approve" (the gaps
   and assumptions found, and each KPI that differs from the organisation's KPI dictionary, approved one by one before
   the build), the analyst review behind it, and each version's review team (UI/UX, story, accuracy) with what every
   reviewer checked: the analyst plans, the developer builds, QA runs the review gates, the reviewers check, each on
   their own. ---------------- */
ICONS.team = ICONS.team || 'M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75';
const TEAM_KIND = {gap: ['Gap', 'What the request or your KPI dictionary asks for that this data cannot give'],
  assumption: ['Assumption', 'How Relay read your data or your request'],
  deviation: ['Differs from your KPI dictionary', 'A KPI that computes something other than your dictionary defines']};
const ROLE_ICON = {analyst: 'search', ux: 'palette', story: 'book', accuracy: 'check'};

/* the reviewer's findings, folded: what it checked, what it asks, its notes */
function reviewerDetails(r) {
  if (!r) return null;
  if (!r.ran) return h('div', {class: 'small muted'}, `Could not run (${r.why || 'no answer'}).`);
  const must = (r.issues || []).filter(i => i.severity === 'must'), should = (r.issues || []).filter(i => i.severity !== 'must');
  return h('div', {class: 'teamdet'},
    r.summary ? h('p', {class: 'small', style: 'margin:4px 0 8px'}, r.summary) : null,
    must.length ? h('div', {}, h('b', {class: 'small'}, r.round === 2 ? 'Still open after the fix round' : 'Asked for changes'),
      h('ul', {class: 'small'}, must.map(i => h('li', {}, h('b', {}, i.where ? i.where + ': ' : ''), i.issue, i.fix ? h('span', {class: 'muted'}, ` - ${i.fix}`) : null)))) : null,
    should.length ? h('details', {class: 'more'}, h('summary', {}, `Suggestions (${should.length})`),
      h('ul', {class: 'small'}, should.map(i => h('li', {}, h('b', {}, i.where ? i.where + ': ' : ''), i.issue, i.fix ? h('span', {class: 'muted'}, ` - ${i.fix}`) : null)))) : null,
    (r.checked || []).length ? h('details', {class: 'more'}, h('summary', {}, `What it checked (${r.checked.length})`),
      h('ul', {class: 'small'}, r.checked.map(c => h('li', {}, c)))) : null,
    (r.fenced || []).length ? h('div', {class: 'small muted'}, 'It tried to change files it may only read: they were put back.') : null);
}

/* the plan: approve each gap, assumption and deviation before Confirm (item 73) */
function approvalsCard(st, onChange) {
  const items = st.approval_items || [], pr = st.plan_review || {};
  const boxes = new Map();
  const status = h('span', {class: 'small muted', role: 'status'});
  const update = () => {
    const left = items.filter(i => !(boxes.get(i.id) || {}).checked).length;
    status.textContent = items.length ? (left ? `${left} of ${items.length} still to approve` : `All ${items.length} approved`) : '';
    if (onChange) onChange(left === 0);
  };
  const groups = ['deviation', 'gap', 'assumption'].map(kind => {
    const list = items.filter(i => i.kind === kind);
    if (!list.length) return null;
    return h('div', {class: 'apgroup'}, h('div', {class: 'apgh'}, h('b', {}, `${TEAM_KIND[kind][0]}s`.replace('Differs from your KPI dictionarys', 'Different from your KPI dictionary')),
      h('span', {class: 'small muted'}, ` - ${TEAM_KIND[kind][1]}`)),
      list.map(i => { const cb = h('input', {type: 'checkbox', 'aria-label': `Approve: ${i.text}`}); boxes.set(i.id, cb); cb.onchange = update;
        return h('label', {class: 'apitem k-' + kind}, cb, h('span', {}, i.text, h('small', {class: 'muted'}, i.source === 'review' ? ' (analyst review)' : ' (the plan)'))); }));
  });
  const all = h('button', {class: 'btn sm', type: 'button', onclick: () => { boxes.forEach(cb => { cb.checked = true; }); update(); }}, icon('check'), 'Approve all');
  const verdict = pr.verdict ? h('span', {class: 'tag ' + (pr.verdict === 'approve' ? 'ok' : 'warn')}, pr.verdict === 'approve' ? 'Analyst review: approved' : 'Analyst review: changes made') : null;
  const card = h('div', {class: 'card apcard'},
    h('div', {class: 'row', style: 'gap:8px;flex-wrap:wrap;align-items:center'}, h('h3', {style: 'margin:0'}, icon('team'), ' Review and approve'), verdict,
      h('span', {class: 'spacer'}), items.length ? all : null),
    h('p', {class: 'small muted', style: 'margin:4px 0 10px'}, items.length
      ? 'Before anything is built: check what Relay could not find in your data, what it assumed, and where a KPI differs from your KPI dictionary. Approve each one, or say what to change in the comments and ask Relay to revise the plan.'
      : pr.verdict ? 'Relay\'s analyst review checked the plan against your data and your KPI dictionary and found nothing for you to approve.'
      : 'Nothing to approve for this plan.'),
    ...groups.filter(Boolean),
    pr.ran ? h('details', {class: 'more'}, h('summary', {}, 'The analyst review'), reviewerDetails(pr)) : null,
    items.length ? status : null);
  update();
  return {el: card, ids: () => items.filter(i => (boxes.get(i.id) || {}).checked).map(i => i.id), ready: () => items.every(i => (boxes.get(i.id) || {}).checked)};
}

/* a version: who checked it (developer, QA, reviewers) and what each found (item 68) */
function teamCard(st, v) {
  const team = v.team || {};
  const gates = v.gates || [];
  const qa = gates.filter(g => g.id !== 'team' && g.status !== 'skip');
  const qaBad = qa.filter(g => g.status === 'fail').length;
  const rows = [
    ['developer', 'code', 'Developer', `Built v${v.v}: ${(v.pages || []).length} pages, ${v.visuals || 0} visuals, ${v.measures || 0} measures`, 'ok', null],
    ['qa', 'shield', 'QA', qa.length ? (qaBad ? `${qaBad} of ${qa.length} review gates need a fix` : `${qa.length} review gates passed`) : 'Review gates run before publishing', qaBad ? 'warn' : 'ok', null],
    ...['ux', 'story', 'accuracy'].filter(r => team[r]).map(r => {
      const x = team[r], must = (x.issues || []).filter(i => i.severity === 'must').length;
      return [r, ROLE_ICON[r], x.label || r, !x.ran ? 'Could not run' : must ? `${must} thing(s) still open` : (x.summary || 'Approved'),
        !x.ran ? 'skip' : must ? 'warn' : 'ok', x];
    })];
  if (!Object.keys(team).length) rows.push(['team', 'team', 'Review team', 'Versions made from now on are checked by Relay\'s UI/UX, story and accuracy reviewers before you see them.', 'skip', null]);
  return h('div', {class: 'card teamcard'},
    h('div', {class: 'row', style: 'gap:8px;align-items:center'}, h('h3', {style: 'margin:0'}, icon('team'), ' Relay\'s team on this version'),
      h('span', {class: 'spacer'}), h('span', {class: 'small muted'}, 'Each reviewer works on its own and cannot change what it checks')),
    h('div', {class: 'teamrows'}, rows.map(([id, ic, label, text, tone, x]) => {
      const det = x ? reviewerDetails(x) : null;
      const row = h('div', {class: 'teamrow t-' + tone},
        h('span', {class: 'ti'}, icon(ic)), h('b', {}, label), h('span', {class: 'tt small'}, text),
        det ? h('button', {class: 'btn sm ghost', type: 'button', 'aria-expanded': 'false', onclick: e => {
          const open = !box.hidden; box.hidden = open; e.currentTarget.setAttribute('aria-expanded', String(!open)); e.currentTarget.textContent = open ? 'Details' : 'Hide'; }}, 'Details') : null);
      const box = h('div', {class: 'teambox', hidden: true}, det);
      return h('div', {}, row, det ? box : null);
    })));
}
