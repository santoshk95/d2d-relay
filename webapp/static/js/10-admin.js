/* ---------------- administration (phase 1): people, teams, sign-in, AI providers, audit, instances ---------------- */
const ADMIN_GROUPS = [['People & access', [['people', 'People'], ['teams', 'Teams'], ['signin', 'Sign-in'], ['partner-access', 'Partner access']]],
  ['AI', [['ai', 'AI providers'], ['gateway', 'LLM gateway']]],
  ['Data & sharing', [['data', 'Data connectors'], ['publishing', 'Publishing'], ['scheduling', 'Scheduling']]],
  ['Operations', [['monitoring', 'Monitoring'], ['doctor', 'Relay Doctor'], ['costs', 'Costs & quotas'], ['audit', 'Audit log'], ['instances', 'Instances']]],
  ['Look & feel', [['branding', 'Branding']]]];
const ADMIN_TABS = ADMIN_GROUPS.flatMap(g => g[1]);
const ROLE = {dev: 'BI Dev / Analyst', viewer: 'Viewer'};

async function renderAdmin() {
  const tab = (location.hash.split('/')[2] || 'people').split('?')[0];
  const page = h('div', {class: 'page'});
  const bar = h('nav', {class: 'subnav', 'aria-label': 'Administration'}, ADMIN_GROUPS.map(([g, items]) => h('div', {class: 'sngroup'}, h('div', {class: 'snhead'}, g),
    items.map(([id, label]) => h('a', {href: '#/admin/' + id, class: id === tab ? 'on' : '', 'aria-current': id === tab ? 'page' : null}, label)))));
  const body = h('div', {class: 'subbody'}, skel('rows'));
  page.append(h('div', {class: 'phead'}, h('div', {}, h('h1', {}, 'Administration'),
    h('div', {class: 'meta'}, 'People, teams and roles, sign-in, which AI providers are allowed, costs and quotas, the audit log, the running services and the brand this install shows.'))),
    h('div', {class: 'subwrap'}, bar, body));
  $('#main').replaceChildren(page);
  try {
    const view = await ({people: adminPeople, teams: adminTeams, signin: adminSignin, ai: adminAI, gateway: adminGateway, data: adminData, publishing: adminPublishing, costs: adminCosts, scheduling: adminScheduling, monitoring: () => adminMonitoring(), doctor: () => adminDoctor(), audit: adminAudit, instances: adminInstances, branding: adminBranding, 'partner-access': adminPartnerAccess}[tab] || adminPeople)();
    if (location.hash.startsWith('#/admin') && (location.hash.split('/')[2] || 'people').split('?')[0] === tab) body.replaceChildren(view);
  } catch (e) { body.replaceChildren(h('div', {class: 'note err'}, e.message)); }
}
const reAdmin = () => renderAdmin();

/* people */
async function adminPeople() {
  const d = await api('/api/admin/users');
  const add = h('button', {class: 'btn primary', onclick: () => personDialog(null, d.teams)}, icon('plus'), 'Add person');
  const rows = d.users.map(u => h('tr', {class: u.active ? '' : 'off'},
    h('td', {}, h('b', {}, u.name), h('div', {class: 'muted small'}, u.email)),
    h('td', {}, u.org_role === 'admin' ? h('span', {class: 'tag acc'}, 'Admin') : h('span', {class: 'muted small'}, 'Member'),
      u.local ? h('span', {class: 'tag', title: 'Has the local (bootstrap) password', style: 'margin-left:4px'}, 'local') : null),
    h('td', {}, u.teams.length ? h('div', {class: 'chips'}, u.teams.map(t => h('span', {class: 'tag'}, `${t.name} · ${ROLE[t.role]}`))) : h('span', {class: 'faint small'}, 'No team')),
    h('td', {class: 'n'}, u.projects),
    h('td', {class: 'small'}, u.active ? (u.last_login ? ago(u.last_login) : 'Never signed in') : h('span', {class: 'tag err'}, 'Deactivated')),
    h('td', {style: 'white-space:nowrap;text-align:right'}, u.active
      ? [h('button', {class: 'btn sm', onclick: () => personDialog(u, d.teams)}, 'Edit'), ' ',
         S.me && u.id !== S.me.id ? h('button', {class: 'btn sm danger', onclick: () => offboardDialog(u, d.users)}, 'Deactivate') : null]
      : h('button', {class: 'btn sm', onclick: async () => { await api(`/api/admin/users/${u.id}/reactivate`, {method: 'POST'}); notify('Reactivated', 'ok'); reAdmin(); }}, 'Reactivate'))));
  return h('div', {}, h('div', {class: 'row', style: 'margin-bottom:12px'},
      h('div', {class: 'muted small'}, `${d.users.filter(u => u.active).length} active people · roles are held per team: BI Dev / Analyst builds and publishes, Viewer opens what is shared.`),
      h('span', {class: 'spacer'}), add),
    h('div', {class: 'card flat', style: 'padding:0;overflow:auto'}, h('table', {class: 'utable'},
      h('tr', {}, ['Person', 'Organisation', 'Teams and roles', 'Dashboards', 'Last sign-in', ''].map((t, i) => h('th', {class: i === 3 ? '' : 'l'}, t))), rows)));
}

function personDialog(u, teams) {
  const email = h('input', {type: 'text', value: u ? u.email : '', placeholder: 'name@company.com', disabled: !!u});
  const name = h('input', {type: 'text', value: u ? u.name : '', placeholder: 'Full name'});
  const org = h('select', {class: 'sel'}, h('option', {value: 'member', selected: !u || u.org_role !== 'admin'}, 'Member'),
    h('option', {value: 'admin', selected: u && u.org_role === 'admin'}, 'Admin (whole organisation)'));
  const ms = (u ? u.teams : []).map(t => ({team_id: t.id, role: t.role}));
  const list = h('div', {class: 'stack', style: 'gap:6px'});
  const draw = () => list.replaceChildren(...ms.map((m, i) => {
    const ts = h('select', {class: 'sel'}, teams.map(t => h('option', {value: t.id, selected: t.id === m.team_id}, t.name)));
    const rs = h('select', {class: 'sel'}, Object.entries(ROLE).map(([k, v]) => h('option', {value: k, selected: k === m.role}, v)));
    ts.onchange = () => { m.team_id = ts.value; }; rs.onchange = () => { m.role = rs.value; };
    return h('div', {class: 'row', style: 'flex-wrap:nowrap'}, ts, rs, h('button', {class: 'btn sm ghost', onclick: () => { ms.splice(i, 1); draw(); }}, icon('x')));
  }), h('button', {class: 'btn sm', onclick: () => { ms.push({team_id: (teams[0] || {}).id, role: 'viewer'}); draw(); }}, icon('plus'), 'Add to a team'));
  draw();
  const save = h('button', {class: 'btn primary', onclick: async () => {
    try {
      const body = {name: name.value, org_role: org.value, teams: ms};
      if (u) await api(`/api/admin/users/${u.id}`, {method: 'PATCH', json: body});
      else await api('/api/admin/users', {json: {...body, email: email.value}});
      notify(u ? 'Saved' : 'Added — they can sign in with SSO', 'ok'); m.remove(); reAdmin();
    } catch (e) { notify(e.message, 'err'); }
  }}, u ? 'Save' : 'Add person');
  const m = modal(u ? `Edit ${u.name}` : 'Add a person', h('div', {class: 'mbody'},
    h('label', {class: 'f'}, 'Work email'), email, h('div', {class: 'hint'}, 'They sign in with this address through your SSO provider.'),
    h('label', {class: 'f'}, 'Name'), name, h('label', {class: 'f'}, 'Organisation role'), org,
    h('label', {class: 'f'}, 'Teams and roles'), list,
    h('div', {class: 'row', style: 'justify-content:flex-end;margin-top:16px'}, h('button', {class: 'btn', onclick: () => m.remove()}, 'Cancel'), save)));
}

function offboardDialog(u, users) {
  const to = h('select', {class: 'sel'}, users.filter(x => x.active && x.id !== u.id).map(x => h('option', {value: x.id, selected: S.me && x.id === S.me.id}, `${x.name} (${x.email})`)));
  const confirmBox = h('input', {type: 'text', placeholder: 'DEACTIVATE'});
  const go = h('button', {class: 'btn primary', onclick: async () => {
    if (confirmBox.value !== 'DEACTIVATE') return notify('Type DEACTIVATE to confirm', 'err');
    try {
      const r = await api(`/api/admin/users/${u.id}/deactivate`, {json: {transfer_to: to.value}});
      const s = r.summary;
      notify(`${u.name} deactivated · ${s.dashboards_transferred} dashboards and ${s.visuals_transferred} visuals transferred`, 'ok'); m.remove(); reAdmin();
    } catch (e) { notify(e.message, 'err'); }
  }}, 'Deactivate');
  const m = modal(`Deactivate ${u.name}`, h('div', {class: 'mbody'},
    h('p', {style: 'margin-top:0'}, `${u.name} loses access at once. Choose who takes over their ${u.projects} dashboard${u.projects === 1 ? '' : 's'} and their library visuals.`),
    h('label', {class: 'f'}, 'Transfer their work to'), to,
    h('ul', {class: 'small', style: 'margin:14px 0'}, h('li', {}, 'End their sign-in sessions'), h('li', {}, 'Revoke their stored keys and tokens (secrets store)'),
      h('li', {}, 'Remove their team memberships and personal shares'), h('li', {class: 'muted'}, 'Their workspace instance is removed once instances exist (phase 2)')),
    h('label', {class: 'f'}, 'Type DEACTIVATE to confirm'), confirmBox,
    h('div', {class: 'row', style: 'justify-content:flex-end;margin-top:16px'}, h('button', {class: 'btn', onclick: () => m.remove()}, 'Cancel'), go)));
}

/* teams */
async function adminTeams() {
  const d = await api('/api/admin/teams');
  const name = h('input', {type: 'text', placeholder: 'New team name', style: 'max-width:280px'});
  const add = h('button', {class: 'btn primary', onclick: async () => {
    try { await api('/api/admin/teams', {json: {name: name.value}}); notify('Team added', 'ok'); reAdmin(); } catch (e) { notify(e.message, 'err'); }
  }}, icon('plus'), 'Add team');
  return h('div', {}, h('div', {class: 'row', style: 'margin-bottom:12px'}, name, add),
    h('div', {class: 'card flat', style: 'padding:0;overflow:auto'}, h('table', {class: 'utable'},
      h('tr', {}, h('th', {class: 'l'}, 'Team'), h('th', {}, 'People'), h('th', {}, 'Dashboards'), h('th', {})),
      d.teams.map(t => h('tr', {}, h('td', {}, h('b', {}, t.name)), h('td', {class: 'n'}, t.members), h('td', {class: 'n'}, t.projects),
        h('td', {style: 'text-align:right;white-space:nowrap'},
          h('button', {class: 'btn sm', onclick: async () => { const n = prompt('Rename team', t.name); if (!n) return;
            try { await api(`/api/admin/teams/${t.id}`, {method: 'PATCH', json: {name: n}}); reAdmin(); } catch (e) { notify(e.message, 'err'); } }}, 'Rename'), ' ',
          h('button', {class: 'btn sm danger', onclick: async () => { if (!await confirmBox(`Remove the team ${t.name}?`, `Its members lose the access the team gave them; dashboards shared with the team stay with their owners.`)) return;
            try { await api(`/api/admin/teams/${t.id}`, {method: 'DELETE'}); reAdmin(); } catch (e) { notify(e.message, 'err'); } }}, 'Remove')))))));
}

/* sign-in */
const PRESETS = {entra: ['Microsoft', 'https://login.microsoftonline.com/<tenant-id>/v2.0'], google: ['Google', 'https://accounts.google.com'],
  okta: ['Okta', 'https://<your-org>.okta.com'], oidc: ['SSO', 'https://']};
async function adminSignin() {
  const d = await api('/api/admin/sso');
  const items = d.providers.map(p => ({...p, secret: '', domains: (p.allowed_domains || []).join(', ')}));
  const list = h('div', {class: 'stack'});
  const draw = () => list.replaceChildren(...items.map((p, i) => {
    const f = (label, el, hint) => h('div', {}, h('small', {class: 'muted'}, label), el, hint ? h('div', {class: 'hint'}, hint) : null);
    const inp = (k, ph, type) => { const el = h('input', {type: type || 'text', value: p[k] || '', placeholder: ph || ''}); el.oninput = () => { p[k] = el.value; }; return el; };
    const chk = (k, label) => { const el = h('input', {type: 'checkbox', checked: !!p[k]}); el.onchange = () => { p[k] = el.checked; }; return h('label', {class: 'chk'}, el, label); };
    return h('div', {class: 'card flat', style: 'margin:0'},
      h('div', {class: 'row'}, h('b', {}, `${PRESETS[p.kind] ? PRESETS[p.kind][0] : 'SSO'} · ${p.id || 'new'}`), h('span', {class: 'spacer'}),
        h('button', {class: 'btn sm ghost', onclick: () => { items.splice(i, 1); draw(); }}, icon('x'), 'Remove')),
      h('div', {class: 'opts', style: 'margin-top:8px'}, f('Id (in the redirect URL)', inp('id', 'entra')), f('Button label', inp('label', 'Microsoft')),
        f('Issuer URL', inp('issuer'), 'From your provider: the OpenID Connect issuer.'), f('Client id', inp('client_id')),
        f('Client secret', inp('secret', p.has_secret ? 'Stored — leave empty to keep' : 'Paste once; stored encrypted', 'password')),
        f('Allowed email domains', inp('domains', 'contoso.com, contoso.co.uk'), 'Empty = any domain the provider vouches for.')),
      h('div', {class: 'row', style: 'margin-top:8px'}, chk('auto_provision', 'Create people on first sign-in (they get no team until an Admin adds one)'), chk('enabled', 'Enabled')));
  }));
  draw();
  const addBtn = kind => h('button', {class: 'btn sm', onclick: () => { items.push({id: kind === 'oidc' ? 'sso' : kind, kind, label: PRESETS[kind][0], issuer: PRESETS[kind][1],
    client_id: '', secret: '', domains: '', auto_provision: false, enabled: true}); draw(); }}, icon('plus'), PRESETS[kind][0]);
  const save = h('button', {class: 'btn primary', onclick: async () => {
    try {
      await api('/api/admin/sso', {method: 'PUT', json: {providers: items.map(p => ({id: p.id, kind: p.kind, label: p.label, issuer: p.issuer, client_id: p.client_id,
        allowed_domains: (p.domains || '').split(',').map(s => s.trim()).filter(Boolean), auto_provision: !!p.auto_provision, enabled: p.enabled !== false})),
        secrets: Object.fromEntries(items.filter(p => p.secret).map(p => [p.id, p.secret]))}});
      notify('Sign-in settings saved', 'ok'); reAdmin();
    } catch (e) { notify(e.message, 'err'); }
  }}, 'Save sign-in settings');
  return h('div', {},
    h('div', {class: 'note ' + (d.mode === 'sso' ? 'ok' : 'warn')}, d.mode === 'sso'
      ? 'Sign-in is on: everyone signs in with SSO; only the bootstrap admin has a local password.'
      : ['Sign-in is off: Relay runs in single-user mode (everyone is the admin). To turn it on, set ', h('code', {}, 'Relay_AUTH=sso'),
         ' and ', h('code', {}, 'Relay_ADMIN_PASSWORD'), ' in the .env file next to docker-compose.yml, then restart. Set up a provider below first.']),
    h('div', {class: 'card flat'}, h('h3', {}, 'Register Relay with your identity provider'),
      h('div', {class: 'small'}, 'Create a web application (OpenID Connect, authorization code with PKCE) and add this redirect URL, with your provider id in place of <id>:'),
      h('div', {class: 'path'}, h('code', {}, d.redirect_uri), copyBtn(d.redirect_uri)),
      h('div', {class: 'hint'}, `Scopes: openid email profile. Sessions last ${d.session_hours} hours.`)),
    h('div', {class: 'row', style: 'margin:6px 0 10px'}, h('b', {}, 'Providers'), h('span', {class: 'spacer'}), ...['entra', 'google', 'okta', 'oidc'].map(addBtn)),
    items.length ? list : h('div', {class: 'card flat empty'}, 'No provider yet. Add Microsoft Entra ID, Google Workspace or Okta.'),
    h('div', {class: 'row', style: 'justify-content:flex-end;margin-top:12px'}, save));
}

/* AI providers policy */
async function adminAI() {
  const d = await api('/api/admin/ai-policy');
  const pol = {...d.policy, allowed: [...d.policy.allowed]};
  const box = h('div', {});
  const draw = () => {
    const sel = (k, opts, allowNone) => { const s = h('select', {class: 'sel'}, allowNone ? h('option', {value: '', selected: !pol[k]}, 'None') : null,
      opts.map(([v, l]) => h('option', {value: v, selected: pol[k] === v}, l))); s.onchange = () => { pol[k] = s.value || null; }; return s; };
    const allowed = Object.entries(d.providers).filter(([k]) => pol.allowed.includes(k));
    box.replaceChildren(
      h('div', {class: 'card flat'}, h('h3', {}, 'Allowed providers'), h('div', {class: 'hint', style: 'margin:-6px 0 10px'}, 'People can only connect the providers that are allowed here. Each person or team brings its own credentials, so the cost goes to their account.'),
        h('div', {class: 'stack', style: 'gap:6px'}, Object.entries(d.providers).map(([k, l]) => { const c = h('input', {type: 'checkbox', checked: pol.allowed.includes(k)});
          c.onchange = () => { pol.allowed = c.checked ? [...pol.allowed, k] : pol.allowed.filter(x => x !== k); draw(); }; return h('label', {class: 'chk'}, c, l); }))),
      h('div', {class: 'card flat'}, h('h3', {}, 'Data residency and defaults'), h('div', {class: 'opts'},
        h('div', {}, h('small', {class: 'muted'}, 'Data may be processed in'), sel('residency', Object.entries(d.residency))),
        h('div', {}, h('small', {class: 'muted'}, 'Default provider'), sel('default', allowed)),
        h('div', {}, h('small', {class: 'muted'}, 'Backup provider (used when the default fails)'), sel('backup', allowed, true)))),
      h('div', {class: 'note small'}, icon('info'), ' Each person picks one of the allowed providers under Settings › My AI provider; Bedrock, Azure AI Foundry and Vertex go through the LLM gateway routes.'),
      h('div', {class: 'row', style: 'justify-content:flex-end'}, h('button', {class: 'btn primary', onclick: async () => {
        try { await api('/api/admin/ai-policy', {method: 'PUT', json: pol}); notify('AI provider policy saved', 'ok'); } catch (e) { notify(e.message, 'err'); } }}, 'Save')));
  };
  draw();
  return box;
}

/* audit log */
async function adminAudit() {
  const [log, people] = await Promise.all([api('/api/admin/audit?limit=1000'), api('/api/admin/users')]);
  const names = Object.fromEntries(people.users.map(u => [u.id, u.name]));
  const actions = [...new Set(log.map(a => a.action))].sort();
  const pick = h('select', {class: 'sel', style: 'max-width:220px', 'aria-label': 'Event type'}, h('option', {value: ''}, 'All events'), actions.map(a => h('option', {value: a}, a)));
  const q = h('input', {type: 'text', placeholder: 'Search…', style: 'max-width:240px'});
  const table = h('table', {class: 'utable'});
  const draw = () => {
    const rows = log.filter(a => (!pick.value || a.action === pick.value) && (!q.value || JSON.stringify(a).toLowerCase().includes(q.value.toLowerCase())));
    table.replaceChildren(h('tr', {}, ['When', 'Who', 'Event', 'Object', 'Detail'].map(t => h('th', {class: 'l'}, t))),
      ...rows.slice(0, 500).map(a => h('tr', {}, h('td', {class: 'small', style: 'white-space:nowrap'}, when(a.ts)),
        h('td', {}, names[a.who] || a.who || '—'), h('td', {}, h('span', {class: 'tag'}, a.action)), h('td', {class: 'mono'}, a.object || ''),
        h('td', {class: 'mono', style: 'max-width:420px;overflow-wrap:anywhere;font-size:11.5px'}, a.detail ? JSON.stringify(a.detail) : ''))));
  };
  pick.onchange = draw; q.oninput = draw; draw();
  const csv = () => { const lines = [['time', 'who', 'instance', 'action', 'object', 'detail'], ...log.map(a => [new Date(a.ts * 1000).toISOString(), names[a.who] || a.who || '', a.instance, a.action, a.object || '', a.detail ? JSON.stringify(a.detail) : ''])];
    const blob = new Blob([lines.map(l => l.map(v => '"' + String(v).replace(/"/g, '""') + '"').join(',')).join('\n')], {type: 'text/csv'});
    h('a', {href: URL.createObjectURL(blob), download: 'd2d-audit.csv'}).click(); };
  return h('div', {}, h('div', {class: 'toolbar'}, pick, q, h('span', {class: 'spacer'}), h('button', {class: 'btn sm', onclick: csv}, icon('download'), 'CSV')),
    h('div', {class: 'card flat', style: 'padding:0;overflow:auto'}, table));
}

/* instances and services */
async function adminInstances() {
  const [d, b, ws] = await Promise.all([api('/api/admin/instances'), api('/api/admin/backups'), workspacesSection()]);
  const ag = d.agent || {};
  const tile = (t, v, s) => h('div', {class: 'stat'}, h('b', {}, v), h('span', {}, t), s ? h('div', {class: 'faint small'}, s) : null);
  const backupBtn = h('button', {class: 'btn', onclick: async e => { e.target.disabled = true; notify('Backing up…');
    try { const m = await api('/api/admin/backups', {method: 'POST'}); notify(`Backup ${m.name}: ${m.files} files, ${m.mb} MB`, 'ok'); reAdmin(); }
    catch (err) { notify(err.message, 'err'); e.target.disabled = false; } }}, icon('download'), 'Back up now');
  return h('div', {},
    h('div', {class: 'stats'}, tile('instance', d.instance, `sign-in: ${d.auth}`), tile('agent', ag.ok ? 'online' : 'offline', ag.runners ? 'runner: ' + ag.runners.join(', ') : ''),
      tile('build lane', ag.lanes ? (ag.lanes.build ? 'busy' : 'free') : '—', d.running && d.running.pid ? d.running.pid : ''),
      tile('chat lane', ag.lanes ? (ag.lanes.chat ? 'busy' : 'free') : '—', 'Ask D (phase 5)'), tile('waiting', d.waiting, 'jobs in the queue'),
      tile('DAX checker', d.daxcheck ? 'on' : 'off', 'Windows PC'), tile('signed in', d.sessions.people, `${d.sessions.n} sessions`)),
    h('div', {class: 'card flat'}, h('h3', {}, 'Jobs'), h('div', {class: 'chips'}, Object.entries(d.jobs).map(([k, v]) => h('span', {class: 'tag'}, `${k}: ${v}`)))),
    h('div', {class: 'card flat'}, h('div', {class: 'row'}, h('h3', {style: 'margin:0'}, 'Backups'), h('span', {class: 'spacer'}), backupBtn),
      h('div', {class: 'hint'}, `Nightly at ${b.hour_utc}:00 UTC to ${b.folder} (output/backups on this PC); the last ${b.keep} are kept; files over ${b.max_file_mb} MB are listed, not copied; extract caches unused for ${b.cache_days} days are removed.`),
      b.backups.length ? h('table', {class: 'utable', style: 'margin-top:8px'}, h('tr', {}, ['Backup', 'Files', 'MB', 'Large files left out'].map((t, i) => h('th', {class: i ? '' : 'l'}, t))),
        b.backups.map(x => h('tr', {}, h('td', {class: 'mono'}, x.name), h('td', {class: 'n'}, x.files ?? '—'), h('td', {class: 'n'}, x.mb ?? '—'),
          h('td', {class: 'n'}, x.skipped_large_files ? x.skipped_large_files.length : '—')))) : h('div', {class: 'muted small', style: 'margin-top:8px'}, 'No backup yet.')),
    ws);
}
