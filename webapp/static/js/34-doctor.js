/* ---------------- Admin › Operations › Relay Doctor: crashes in Relay's own code, found, fixed, proven and deployed ---------------- */
const DOC_MODES = {auto: 'Fix and deploy by itself', approve: 'Ask an Admin before each deploy', watch: 'Only report crashes'};
const DOC_STATUS = {new: ['In line', 'warn'], fixing: ['Fixing', 'warn'], proving: ['Proving the fix', 'warn'], ready: ['Ready to deploy', 'warn'],
  deploying: ['Deploying', 'warn'], verifying: ['Live, being watched', 'warn'], closed: ['Closed', 'ok'], needs_person: ['Needs a person', 'err'],
  rolled_back: ['Rolled back', 'err'], muted: ['Muted', '']};
const DOC_FILES = [['evidence', 'The crash'], ['ai', 'What the AI did'], ['diff', 'The change'], ['tests', 'Tests and checks'], ['deploy', 'Deploy']];

async function adminDoctor(data) {
  const d = data || await api('/api/admin/doctor');
  const redraw = async p => { try { const v = await adminDoctor(await p); const host = $('#docview'); if (host) host.replaceWith(v); } catch (e) { notify(e.message, 'err'); } };
  const act = (action, extra = {}) => redraw(api('/api/admin/doctor/control', {json: {action, ...extra}}));
  const tag = st => { const [t, c] = DOC_STATUS[st] || [st, '']; return h('span', {class: 'tag ' + c}, t); };
  const open = d.incidents.filter(i => !['closed', 'muted'].includes(i.status));
  const done = d.incidents.filter(i => ['closed', 'muted'].includes(i.status)).slice(0, 20);
  const lim = d.limits || {};
  const state = !d.installed ? ['Not running on this PC yet', 'warn'] : d.stopped ? ['Stopped', 'warn'] : !d.online ? ['Offline', 'err'] : d.paused ? ['Paused', 'warn'] : ['Watching', 'ok'];
  const modeSel = h('select', {class: 'sel', style: 'width:auto', 'aria-label': 'What Relay Doctor may do', disabled: !d.installed},
    Object.entries(DOC_MODES).map(([k, v]) => h('option', {value: k, selected: (d.control.mode || d.mode) === k}, v)));
  modeSel.onchange = () => act('mode', {mode: modeSel.value});

  const files = inc => h('div', {class: 'docfiles'}, DOC_FILES.filter(([k]) => (inc.files || []).includes(k)).map(([k, label]) => {
    const pre = h('pre', {class: 'mono small', style: 'max-height:360px;overflow:auto;white-space:pre-wrap'}, 'Loading…');
    const box = h('details', {}, h('summary', {}, label), pre);
    box.ontoggle = async () => { if (box.open && pre.dataset.loaded !== '1') { try { pre.textContent = await api(`/api/admin/doctor/incidents/${inc.id}/${k}`); pre.dataset.loaded = '1'; } catch (e) { pre.textContent = e.message; } } };
    return box;
  }));
  const buttons = inc => h('div', {class: 'row', style: 'gap:6px;flex-wrap:wrap'},
    inc.status === 'ready' ? h('button', {class: 'btn sm primary', onclick: () => act('approve', {incident: inc.id})}, 'Deploy the fix') : null,
    ['needs_person', 'rolled_back'].includes(inc.status) ? h('button', {class: 'btn sm', onclick: () => act('retry', {incident: inc.id})}, 'Try again') : null,
    inc.status === 'muted' ? h('button', {class: 'btn sm', onclick: () => act('unmute', {incident: inc.id})}, 'Unmute')
      : h('button', {class: 'btn sm', onclick: () => act('mute', {incident: inc.id}), title: 'Keep counting this crash but do not fix it'}, 'Mute'),
    inc.status !== 'closed' ? h('button', {class: 'btn sm', onclick: () => act('close', {incident: inc.id})}, 'Close') : null);
  const card = inc => h('div', {class: 'card flat docinc'},
    h('div', {class: 'row', style: 'gap:8px;align-items:flex-start'}, tag(inc.status),
      h('div', {class: 'grow'}, h('b', {}, inc.title), h('div', {class: 'small'}, inc.step || ''),
        h('div', {class: 'faint small'}, `${inc.where || ''}${inc.where ? ' · ' : ''}seen ${inc.count || 1}× · first ${ago(inc.first_seen)}${inc.last_seen ? ' · last ' + ago(inc.last_seen) : ''}`
          + (inc.attempts ? ` · attempt ${inc.attempts}` : '') + (inc.commit ? ` · commit ${inc.commit.slice(0, 8)}` : '') + (inc.cost_usd ? ` · AI cost $${inc.cost_usd.toFixed(2)}` : ''))),
      buttons(inc)),
    inc.summary ? h('div', {class: 'small', style: 'margin-top:6px'}, inc.summary) : null,
    inc.reason ? h('div', {class: 'note ' + (['needs_person', 'rolled_back'].includes(inc.status) ? 'err' : 'warn'), style: 'margin-top:6px'}, inc.reason) : null,
    files(inc));

  return h('div', {id: 'docview'},
    h('div', {class: 'row'}, h('span', {class: 'tag ' + state[1]}, state[0]),
      h('span', {class: 'muted small'}, d.installed ? `checked ${ago(d.time)}` + (d.version ? ` · version ${d.version}` : '') : 'Start doctor\\start-doctor.cmd on the Windows PC that runs Docker.'),
      h('span', {class: 'spacer'}), modeSel,
      d.installed ? h('button', {class: 'btn sm', onclick: () => act(d.paused ? 'resume' : 'pause')}, d.paused ? 'Resume' : 'Pause') : null,
      h('button', {class: 'btn sm', onclick: () => redraw(api('/api/admin/doctor'))}, 'Refresh')),
    d.busy ? h('div', {class: 'note'}, icon('clock'), ' Now: ', d.busy) : null,
    d.holding ? h('div', {class: 'note warn'}, `New jobs are waiting while Relay Doctor ${d.holding.reason === 'deploy' ? 'restarts the app' : 'runs its fix'} (since ${when(d.holding.since)}). Nothing is lost: they start when it is done.`) : null,
    h('div', {class: 'stats'},
      h('div', {class: 'stat'}, h('b', {}, String(open.length)), h('span', {}, 'open'), h('div', {class: 'faint small'}, `${open.filter(i => ['needs_person', 'rolled_back'].includes(i.status)).length} need a person`)),
      h('div', {class: 'stat'}, h('b', {}, String(d.incidents.filter(i => i.outcome === 'fixed').length)), h('span', {}, 'fixed'), h('div', {class: 'faint small'}, 'kept for 30 days')),
      h('div', {class: 'stat'}, h('b', {}, `${lim.fix_runs_today ?? 0} / ${lim.max_fix_runs_per_day ?? '—'}`), h('span', {}, 'AI fixes today')),
      h('div', {class: 'stat'}, h('b', {}, `${lim.deploys_today ?? 0} / ${lim.max_deploys_per_day ?? '—'}`), h('span', {}, 'deploys today')),
      h('div', {class: 'stat'}, h('b', {}, d.live.commit ? d.live.commit.slice(0, 8) : (d.app.commit || '—').slice(0, 8)), h('span', {}, 'live commit'), h('div', {class: 'faint small'}, d.live.at ? 'since ' + ago(d.live.at) : ''))),
    open.length ? [h('h3', {}, 'Open'), open.map(card)] : h('div', {class: 'note ok'}, icon('check'), ' No open problems in Relay’s own code.'),
    h('div', {class: 'grid2'},
      h('div', {class: 'card flat'}, h('h3', {}, 'Closed recently'), done.length ? h('table', {class: 'utable'}, h('tr', {}, ['When', 'What', ''].map(x => h('th', {class: 'l'}, x))),
        done.map(i => h('tr', {}, h('td', {}, when(i.closed_at || i.last_seen)), h('td', {}, i.title, i.summary ? h('div', {class: 'faint small'}, i.summary) : null),
          h('td', {}, i.outcome === 'fixed' ? h('span', {class: 'tag ok'}, 'fixed') : tag(i.status))))) : h('div', {class: 'muted small'}, 'Nothing yet.')),
      h('div', {class: 'card flat'}, h('h3', {}, 'Routine actions'), (d.actions || []).length ? h('table', {class: 'utable'}, h('tr', {}, ['When', 'What'].map(x => h('th', {class: 'l'}, x))),
        d.actions.slice(0, 15).map(a => h('tr', {}, h('td', {}, when(a.time)), h('td', {}, a.text)))) : h('div', {class: 'muted small'}, 'None so far — restarts, the DAX checker and roll-backs show here.'))),
    d.app.errors.length ? h('div', {class: 'card flat'}, h('h3', {}, 'Crashes this app has seen since it started'),
      h('table', {class: 'utable'}, h('tr', {}, ['Error', 'Where in the code', 'Times', 'Last'].map(x => h('th', {class: 'l'}, x))),
        d.app.errors.map(e => h('tr', {}, h('td', {}, e.type, h('div', {class: 'faint small'}, e.message)), h('td', {class: 'mono small'}, `${e.file} › ${e.func}`),
          h('td', {class: 'n'}, e.count), h('td', {}, ago(e.last)))))) : null,
    h('div', {class: 'card flat'}, h('h3', {}, 'How Relay Doctor works'),
      h('div', {class: 'small'}, 'Relay Doctor runs on the Windows PC next to Docker, so it keeps working when the app does not. When Relay’s own code crashes, it writes a test that shows the crash, fixes the code on a copy, and runs every test suite and a trial on a copy of the live data. Then, at a quiet moment, it swaps the new version in and watches it. If the app fails or the crash comes back, it puts the previous version back at once.'),
      h('div', {class: 'small', style: 'margin-top:8px'}, 'It never changes sign-in, tenants, secrets, the database layer, the Docker set-up or existing tests by itself: those fixes go to a person. Routine actions need no AI: starting the DAX checker, restarting the agent when it hangs, and rolling back a version that does not start.'),
      h('div', {class: 'hint', style: 'margin-top:8px'}, `Limits: ${lim.max_fix_runs_per_day ?? '—'} AI fixes and ${lim.max_deploys_per_day ?? '—'} deploys a day, ${lim.max_attempts_per_bug ?? '—'} tries per crash, ${lim.verify_minutes ?? '—'} minutes of watching after each deploy (doctor\\settings.json).`)));
}
