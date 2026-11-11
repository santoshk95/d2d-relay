/* ---------------- render loop ---------------- */
function render() {
  const st = S.project;
  if (!st || !S.pid || !location.hash.startsWith('#/p/')) return;
  const key = JSON.stringify([st.id, st.status, st.versions.length, st.plan_rounds, st.approved, st.error, S.version, S.vsel, (st.job || {}).kind, S.tab,
    S.actMode, st.versions.map(v => v.label || ''), (st.publishes || []).length, st.model, (st.visuals && st.visuals.proposals || []).map(p => p.decision || '').join()]);
  const main = $('#main');
  if (key !== S.key) {
    S.key = key; S.live = null;
    const body = {overview: overviewTab, plan: planTab, versions: versionsTab, activity: activityTab, details: detailsTab}[S.tab](st);
    const ro = st.access && !st.access.can_edit;
    main.replaceChildren(h('div', {class: 'page' + (S.tab === 'overview' || S.tab === 'versions' ? ' wide' : '') + (ro ? ' readonly' : '')}, header(st), stepper(st),
      ro ? h('div', {class: 'note'}, icon('lock'), ' You can view this dashboard. Changes, approval and publishing are for its owner and the BI Devs it is shared with.') : banner(st), tabsBar(st), body));
  }
  // in-place updates while Relay works
  const bt = $('#btext');
  if (bt) bt.textContent = st.status === 'queued' ? (st.position ? `${st.position} job(s) ahead of this one` : 'Starting next…')
    : st.running_since ? `Running for ${dur(Date.now() - st.running_since * 1000)}` + (['pbi', 'pbix'].includes((st.job || {}).kind)
      ? ' · Power BI Desktop on the D2D Relay PC, one file at a time' : ' · one agent, one step at a time') : '';
  renderLive();
  const lf = $('#liveframe');
  if (lf && st.live_prototype && st.live_prototype !== S.live) { S.live = st.live_prototype; lf.replaceChildren(protoFrame(`/api/projects/${st.id}/prototype/live?t=${st.live_prototype}`)); }
  else if (lf && !st.live_prototype && !lf.childElementCount) lf.append(h('div', {class: 'muted small'}, 'Appears after Relay renders the first page.'));
  const list = $('#actlist');
  if (list && S.act && S.act.count !== S.events.length) {
    const stick = RUN.has(st.status) && main.scrollHeight - main.scrollTop - main.clientHeight < 160;   // follow a live run only
    buildTimeline(list, S.events, S.actMode, S.actQuery); S.act.count = S.events.length;
    if (stick) main.scrollTop = main.scrollHeight;
  }
}

/* ---------------- polling ---------------- */
let timer = null;
async function poll() {
  clearTimeout(timer);
  const pid = S.pid;
  if (pid) {
    try {
      const st = await api(`/api/projects/${pid}`);
      if (pid !== S.pid) return;
      const pillEl = $('#hpill');
      if (pillEl && S.project && S.project.status !== st.status) pillEl.replaceChildren(pill(st.status));
      if (S.project && S.project.status !== st.status && typeof refreshOrg === 'function') refreshOrg(true);   // D2D Relay: a run ended, its credits may have come back
      const first = !S.project;
      S.project = st;
      if (first) render();                           // draw the page at once; the log follows
      for (let i = 0; i < 40; i++) {                 // catch up on a long log, 400 events at a time
        const evs = await api(`/api/projects/${pid}/activity?after=${S.after}`);
        if (pid !== S.pid) return;
        if (evs.length) { S.events.push(...evs); S.after = evs[evs.length - 1].seq; }
        if (evs.length < 400) break;
      }
      if (pid === S.pid) render();
    } catch (e) {
      if (String(e.message).startsWith('404')) $('#main').replaceChildren(h('div', {class: 'page'}, h('div', {class: 'card empty'}, h('h3', {}, 'Dashboard not found'), h('a', {href: '#/'}, 'Back to dashboards'))));
    }
  }
  timer = setTimeout(poll, S.project && RUN.has(S.project.status) ? 1500 : 5000);
}
if (isAdminPortal()) {             // D2D Relay's admin portal: organisations and requests only (no dashboards, agent or models)
  loadMe();
  loadRegistry().then(() => route());
} else {
  setInterval(() => { refreshList(); refreshSys(); if (typeof refreshOrg === 'function') refreshOrg(); }, 5000);   // refreshOrg: at most every 30 s
  loadMe().then(ensureWorkspace);
  Promise.all([loadModels(), loadRegistry()]).then(() => { refreshList(); refreshSys(); route(); });
}
