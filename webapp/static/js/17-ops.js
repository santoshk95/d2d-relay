/* ---------------- phase 8: Admin > Monitoring (live state, alerts on stuck work, the DAX checker's queue) ---------------- */
const OPS_LABELS = {chat_stuck_min: 'Ask Relay lane busy longer than (min)', queue_stalled_min: 'Jobs waiting, nothing started for (min)',
  queue_deep: 'Builds waiting at once', daxcheck_backlog: 'DAX checks waiting at once', daxcheck_wait_min: 'Oldest DAX check waiting (min)',
  schedule_late_min: 'Schedule overdue by (min)', errors_15min: 'Server errors in 15 min', build_grace_min: 'Minutes past a job\'s time limit',
  daxcheck_offline_min: 'DAX checker offline, queue empty, for (min)', backup_max_h: 'Last backup older than (hours)'};

async function adminMonitoring(data) {
  const m = data || await api('/api/admin/monitoring');
  const mins = s => s == null ? '-' : s < 90 ? `${Math.round(s)} s` : `${Math.round(s / 60)} min`;
  const tile = (t, v, s, bad) => h('div', {class: 'stat' + (bad ? ' bad' : '')}, h('b', {}, v), h('span', {}, t), s ? h('div', {class: 'faint small'}, s) : null);
  const ag = m.agent || {}, since = ag.since || {}, now = m.time, d = m.daxcheck;
  const lane = l => !ag.ok ? '-' : ag.lanes && ag.lanes[l] ? 'busy' : 'free';
  const laneFor = l => since[l] ? `for ${mins(now - since[l])}` : '';
  const sev = a => h('span', {class: 'tag ' + (a.severity === 'critical' ? 'err' : 'warn')}, a.severity);
  const redraw = async p => { const view = await adminMonitoring(await p); const host = $('#opsview'); if (host) host.replaceWith(view); };
  // the DAX checker's queue: the last 24 hours, one bar a minute (grouped to 96 bars), and the daily peaks
  const hist = m.daxcheck_history, buckets = [];
  for (let i = 0; i < hist.length; i += Math.max(1, Math.ceil(hist.length / 96))) {
    const part = hist.slice(i, i + Math.max(1, Math.ceil(hist.length / 96)));
    buckets.push({t: part[0].t, pending: Math.max(...part.map(x => x.pending)), offline: part.some(x => !x.online)});
  }
  const top = Math.max(1, ...buckets.map(b => b.pending));
  const daxChart = buckets.length ? h('div', {class: 'daybars ops'}, buckets.map(b => h('i', {class: b.offline ? 'off' : '', title: `${new Date(b.t * 1000).toLocaleTimeString()} - ${b.pending} waiting${b.offline ? ' - checker offline' : ''}`,
    style: `height:${b.pending ? Math.max(6, 100 * b.pending / top) : 3}%`})))
    : h('div', {class: 'muted small'}, 'Samples start a minute after the app starts.');
  const days = Object.entries(m.daxcheck_days).reverse();
  const t = {...m.thresholds};
  const hookUrl = h('input', {type: 'text', 'aria-label': 'Ops channel webhook URL', placeholder: m.webhook.set ? 'Stored - paste a new URL to replace' : 'https://hooks.slack.com/services/...'});
  const hookKind = h('select', {class: 'sel', style: 'width:auto', 'aria-label': 'Ops channel type'}, h('option', {value: 'slack', selected: m.webhook.kind !== 'teams'}, 'Slack'), h('option', {value: 'teams', selected: m.webhook.kind === 'teams'}, 'Microsoft Teams'));
  const hist2 = [...m.history].sort((a, b) => b.ts - a.ts).slice(0, 30);
  return h('div', {id: 'opsview'},
    h('div', {class: 'row'}, h('span', {class: 'muted small'}, `Instance ${m.instance} - checked ${m.last_tick ? ago(m.last_tick) : 'not yet'} (every minute)`), h('span', {class: 'spacer'}),
      h('button', {class: 'btn sm', onclick: e => { e.target.disabled = true; redraw(api('/api/admin/monitoring/check', {method: 'POST'})); }}, 'Check now')),
    m.alerts.length ? h('div', {class: 'card flat'}, h('h3', {}, 'Open problems'), m.alerts.map(a => h('div', {class: 'row', style: 'margin:6px 0'}, sev(a), h('div', {class: 'grow'}, a.text), h('span', {class: 'faint small'}, 'since ' + ago(a.since)))))
      : h('div', {class: 'note ok'}, icon('check'), ' No open problems.'),
    h('div', {class: 'stats'},
      tile('Agent', ag.ok ? 'online' : 'offline', ag.ok ? (ag.runners || []).join(', ') : ag.error, !ag.ok),
      tile('build lane', lane('build'), laneFor('build') || (m.running.kind ? `${m.running.kind} - ${mins(m.running.age_s)}` : '')),
      tile('Ask Relay lane', lane('chat'), laneFor('chat')), tile('waiting', m.waiting, 'builds in the queue', m.waiting >= t.queue_deep),
      tile('DAX checker', d.online ? 'online' : 'offline', `${d.pending} waiting${d.pending ? ' - oldest ' + mins(d.oldest_s) : ''}`, !d.online && d.pending),
      tile('schedules', (m.schedules.active || 0) + ' active', `${m.schedules.paused || 0} paused - ${m.schedules_late} overdue`, m.schedules_late),
      tile('signed in', m.sessions, 'sessions'), tile('server errors', m.errors_15min, 'last 15 min', m.errors_15min >= t.errors_15min),
      tile('database', m.database === 'postgres' ? 'Postgres' : 'SQLite', m.database === 'postgres' ? 'Relay_DATABASE_URL' : 'state volume file'),
      tile('other runners', Object.values(m.runners || {}).filter(r => r.ok).length + ' up', Object.entries(m.runners || {}).map(([k, v]) => `${k} ${v.ok ? '✓' : '-'}`).join(' - ')),
      (() => { const dr = m.doctor || {}; const el = tile('Relay Doctor', !dr.installed ? 'not running' : !dr.online ? 'offline' : dr.paused ? 'paused' : 'watching',
        dr.installed ? `${dr.open || 0} open - ${dr.needs_person || 0} need a person` : 'doctor\\start-doctor.cmd', dr.installed && (!dr.online || dr.needs_person));
        el.style.cursor = 'pointer'; el.onclick = () => { location.hash = '#/admin/doctor'; }; return el; })()),
    h('div', {class: 'card flat'}, h('h3', {}, 'DAX checker queue - last 24 hours'),
      h('div', {class: 'hint', style: 'margin-bottom:8px'}, 'One checker on the Windows PC serves every build in turn, so it is the first bottleneck as people are added. Red bars: the checker was offline. When the daily peaks keep rising, move it to a server (platform plan, phase 8).'),
      daxChart,
      days.length ? h('table', {class: 'utable', style: 'margin-top:12px'}, h('tr', {}, h('th', {class: 'l'}, 'Day (UTC)'), h('th', {}, 'Most waiting'), h('th', {}, 'Longest wait'), h('th', {}, 'Offline')),
        days.slice(0, 14).map(([day, p]) => h('tr', {}, h('td', {}, day), h('td', {class: 'n'}, p.max_pending), h('td', {class: 'n'}, mins(p.max_wait_s)), h('td', {class: 'n'}, `${Math.round(p.offline_min)} min`)))) : null),
    m.workspaces.length ? h('div', {class: 'card flat'}, h('h3', {}, 'Personal workspaces'), h('table', {class: 'utable'}, h('tr', {}, ['Person', 'State', 'Answers', 'Lanes'].map(x => h('th', {class: 'l'}, x))),
      m.workspaces.map(w => h('tr', {}, h('td', {}, w.user), h('td', {}, w.state), h('td', {}, w.healthy === false ? h('span', {class: 'tag err'}, 'no') : w.healthy ? h('span', {class: 'tag ok'}, 'yes') : '-'),
        h('td', {}, w.lanes ? Object.entries(w.lanes).map(([k, v]) => `${k}: ${v ? 'busy' : 'free'}`).join(' - ') : '-'))))) : null,
    h('div', {class: 'grid2'},
      h('div', {class: 'card flat'}, h('h3', {}, 'Alert rules'), h('div', {class: 'kv rules'}, Object.keys(OPS_LABELS).map(k => [h('dt', {}, OPS_LABELS[k]),
        h('dd', {}, (() => { const el = h('input', {type: 'number', min: 1, value: t[k], style: 'width:90px', 'aria-label': OPS_LABELS[k]}); el.oninput = () => { t[k] = Number(el.value); }; return el; })())])),
        h('div', {class: 'hint'}, 'Always on: agent offline, a job past its time limit, a lane busy with no job, the DAX checker offline with checks waiting, a workspace that does not answer.'),
        h('label', {class: 'f', style: 'margin-top:12px'}, 'Ops channel (optional): every new and cleared problem is also posted here'),
        h('div', {class: 'row'}, hookKind, h('div', {class: 'grow'}, hookUrl)),
        h('div', {class: 'row', style: 'justify-content:flex-end;margin-top:10px'}, h('button', {class: 'btn primary', onclick: async () => {
          try { await redraw(api('/api/admin/monitoring', {method: 'PUT', json: {thresholds: t, webhook_url: hookUrl.value || null, webhook_kind: hookKind.value}})); notify('Saved', 'ok'); } catch (e) { notify(e.message, 'err'); } }}, 'Save'))),
      h('div', {class: 'card flat'}, h('h3', {}, 'Metrics and logs'),
        h('div', {class: 'small'}, m.metrics_endpoint ? ['Prometheus metrics: ', h('code', {}, 'GET /metrics'), ' with ', h('code', {}, 'Authorization: Bearer $Relay_METRICS_TOKEN'), '. The agent also serves ', h('code', {}, '/metrics'), ' on the internal network.']
          : ['Set ', h('code', {}, 'Relay_METRICS_TOKEN'), ' in .env to turn on ', h('code', {}, 'GET /metrics'), ' (Prometheus text) for a scraper.']),
        h('div', {class: 'small', style: 'margin-top:8px'}, 'Logs: one JSON line per event on the containers\' output (', h('code', {}, 'docker logs gen-bi-webapp-1'), '): API writes, errors, slow requests, job start / end, alerts.'),
        h('h3', {style: 'margin-top:14px'}, 'Busiest API routes'),
        h('table', {class: 'utable'}, h('tr', {}, h('th', {class: 'l'}, 'Route'), h('th', {}, 'Status'), h('th', {}, 'Calls'), h('th', {}, 'Avg')),
          m.http.slice(0, 12).map(r => h('tr', {}, h('td', {class: 'mono small'}, `${r.method} ${r.route}`), h('td', {class: 'n'}, r.status), h('td', {class: 'n'}, r.count), h('td', {class: 'n'}, r.avg_ms + ' ms')))))),
    h('div', {class: 'card flat'}, h('h3', {}, 'Recent problems'), hist2.length ? h('table', {class: 'utable'}, h('tr', {}, ['When', 'What', ''].map(x => h('th', {class: 'l'}, x))),
      hist2.map(a => h('tr', {}, h('td', {}, when(a.ts)), h('td', {}, a.action === 'ops.resolved' ? `Resolved after ${a.detail.minutes} min: ${a.object}` : a.detail.text),
        h('td', {}, a.action === 'ops.resolved' ? h('span', {class: 'tag ok'}, 'resolved') : sev(a.detail))))) : h('div', {class: 'muted small'}, 'None so far.')));
}
