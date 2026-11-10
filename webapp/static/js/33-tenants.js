/* ---------------- P17 tenants, partners and editions: the workspace chip and switcher in the top bar, the band
   while acting in another workspace, the platform console (#/tenants: tree, create, a workspace's overview,
   modules, access, hand-over, usage and deployment), usage & statements (#/tenants/usage) and Admin › Partner access.
   Every rule is the server's (app/tenancy.py); this file only shows it. ---------------- */
const TKIND = {platform: ['Platform', 'info'], partner: ['Service partner', 'you'], client: ['Client', 'mute']};
const TSTATUS = {active: ['Active', 'ok'], suspended: ['Suspended', 'err'], closed: ['Closed', 'mute']};
const GSTATUS = {active: ['Active', 'ok'], pending: ['Waiting for approval', 'you'], revoked: ['Ended', 'mute'], expired: ['Expired', 'mute'], refused: ['Refused', 'err'], ended: ['Ended at hand-over', 'mute']};
const TTABS = [['overview', 'Overview'], ['modules', 'Modules'], ['access', 'Access'], ['handover', 'Hand-over'], ['usage', 'Usage'], ['deployment', 'Deployment']];
const tpill = (map, k) => { const [t, c] = map[k] || [k, 'mute']; return h('span', {class: 'pill plain ' + c}, t); };
const tleft = s => s <= 0 ? 'ended' : s < 3600 ? `${Math.max(1, Math.round(s / 60))} min left` : s < 86400 ? `${Math.round(s / 3600)} h left` : `${Math.round(s / 86400)} days left`;
const tmoney = (x, cur) => `${cur || ''} ${Number(x || 0).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}`.trim();
const tcompact = (x, cur) => `${cur || ''} ${Number(x || 0).toLocaleString(undefined, {notation: 'compact', maximumFractionDigits: 1})}`.trim();
const thisMonth = () => new Date().toISOString().slice(0, 7);
ICONS.building = ICONS.building || 'M4 21V5a1 1 0 0 1 1-1h9a1 1 0 0 1 1 1v16M15 9h4a1 1 0 0 1 1 1v11M3 21h18M8 8h3M8 12h3M8 16h3';

/* ---------------- the workspace chip, the switcher and the acting band ---------------- */
function renderWorkspace() {
  const t = (S.me || {}).tenant || {}, chip = $('#ws'), band = $('#actband');
  if (!chip || !band) return;
  // D2D Relay: an organisation shows its own chip (organisation and credits, 36-org.js) instead of the workspace chip
  const show = !(S.me && S.me.org && S.me.org.id) && t.id && (t.console || t.acting || (t.enter || []).length || t.kind !== 'platform');
  chip.hidden = !show;
  if (show) {
    chip.replaceChildren(h('button', {class: 'wsbtn' + (t.acting ? ' acting' : ''), type: 'button', 'aria-haspopup': 'dialog',
        'aria-label': `Workspace: ${t.name}${t.acting ? ' (acting as a guest)' : ''}. Switch workspace`, onclick: e => workspaceMenu(e.currentTarget)},
      icon(t.kind === 'partner' ? 'users' : t.kind === 'platform' ? 'layers' : 'building'), h('span', {class: 'wsname'}, t.name),
      h('span', {class: 'wskind'}, (TKIND[t.kind] || [t.kind])[0]), icon('chevd', 'wschev')));
  }
  band.hidden = !t.acting;
  document.documentElement.classList.toggle('acting', !!t.acting);
  if (t.acting) {
    const until = t.expires ? new Date(t.expires * 1000).toLocaleString(undefined, {day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit'}) : '';
    band.replaceChildren(icon('info'), h('span', {class: 'grow'}, 'You are working in ', h('b', {}, t.name), ` as ${({admin: 'an admin', dev: 'a builder', viewer: 'a viewer'})[t.role] || 'a guest'}`,
      until ? ` until ${until}` : '', '. Everything you do here is in its audit log.'),
      h('button', {class: 'btn sm', type: 'button', onclick: tenancyReturn}, `Back to ${(t.home || {}).name || 'your workspace'}`));
  }
}
async function tenancySwitch(id) {
  try { await api('/api/tenancy/switch', {json: {tenant: id}}); location.hash = '#/'; location.reload(); }
  catch (e) { notify(e.message, 'err'); }
}
async function tenancyReturn() {
  try { await api('/api/tenancy/return', {method: 'POST'}); location.hash = '#/'; location.reload(); }
  catch (e) { notify(e.message, 'err'); }
}
function workspaceMenu(anchor) {
  const t = (S.me || {}).tenant || {}, home = t.home || {};
  const others = (t.enter || []).filter(g => g.id !== t.id);
  popover(anchor, [
    h('div', {class: 'pmhead'}, h('div', {class: 'small faint'}, 'Working in'), h('b', {}, t.name),
      h('div', {class: 'small muted'}, [(TKIND[t.kind] || [t.kind])[0], t.edition === 'both' ? 'both editions' : t.edition === 'partner' ? 'Service partner edition' : 'Enterprise edition'].join(' · '))),
    t.acting ? h('button', {class: 'pmitem', type: 'button', onclick: () => { closePopover(); tenancyReturn(); }}, icon('back'), h('span', {class: 'grow'}, `Back to ${home.name || 'your workspace'}`)) : null,
    others.length ? h('div', {class: 'pmsect small faint'}, 'You can enter') : null,
    others.map(g => h('button', {class: 'pmitem', type: 'button', onclick: () => { closePopover(); tenancySwitch(g.id); }},
      icon('building'), h('span', {class: 'grow'}, g.name, h('div', {class: 'small muted'}, `${({admin: 'Admin', dev: 'Builder', viewer: 'Viewer'})[g.role] || g.role} · until ${when(g.expires)}`)))),
    !others.length && !t.acting ? h('div', {class: 'small muted', style: 'padding:6px 12px 10px'}, t.console ? 'To work inside a client, give yourself access from its page in the console.' : 'You have no access to other workspaces.') : null,
    t.console ? h('a', {class: 'pmitem', href: '#/tenants', onclick: closePopover}, icon('layers'), h('span', {class: 'grow'}, 'Tenants & partners')) : null,
    t.console ? h('a', {class: 'pmitem', href: '#/tenants/usage', onclick: closePopover}, icon('pulse'), h('span', {class: 'grow'}, 'Usage & statements')) : null,
  ], 'profile');
}

/* ---------------- the console ---------------- */
async function renderTenants() {
  const main = $('#main'), parts = location.hash.split('?')[0].split('/');      // #/tenants[/usage | /<id>[/<tab>]]
  const t = (S.me || {}).tenant || {};
  if (!t.console) {
    main.replaceChildren(h('div', {class: 'page'}, pageHead({crumbs: [['Home', '#/'], ['Tenants & partners']], eyebrow: brandName() + ' · Platform', title: 'Tenants & partners'}),
      h('div', {class: 'card empty'}, h('h3', {}, 'For the platform’s admins and partner admins'), h('p', {}, t.tenancy === 'single'
        ? 'This is a dedicated install for one workspace, so there are no other tenants to manage here.'
        : 'Partners and clients are managed by the platform’s administrators and by each partner’s admins. Your own workspace is under Administration.'),
        h('a', {class: 'btn', href: '#/'}, 'Home'))));
    return;
  }
  if (parts[2] === 'usage') return renderUsage();
  if (parts[2]) return renderTenantPage(parts[2], parts[3] || 'overview');
  main.replaceChildren(skel('page'));
  let d;
  try { d = await api('/api/tenancy/tenants'); } catch (e) { main.replaceChildren(h('div', {class: 'page'}, h('div', {class: 'note err'}, e.message))); return; }
  if (location.hash.split('?')[0] !== '#/tenants') return;
  const rows = d.tenants, partners = rows.filter(r => r.kind === 'partner'), clients = rows.filter(r => r.kind === 'client');
  const grants = rows.reduce((n, r) => n + (r.counts ? r.counts.active_grants : 0), 0);
  const row = (r, depth) => h('tr', {},
    h('td', {}, h('div', {class: 'ttree', style: `padding-left:${Math.max(0, depth - 1) * 20}px`}, depth ? h('span', {class: 'tbranch', 'aria-hidden': 'true'}) : null,
      h('div', {}, h('a', {href: `#/tenants/${r.id}`}, h('b', {}, r.name)), h('div', {class: 'small muted mono'}, r.id)))),
    h('td', {class: 'l'}, tpill(TKIND, r.kind)), h('td', {class: 'l small'}, r.edition_label),
    h('td', {class: 'l'}, tpill(TSTATUS, r.status), r.partner_access === 'ended' ? h('div', {class: 'small muted'}, 'handed over') : r.partner_access === 'approval' ? h('div', {class: 'small muted'}, 'approves partner access') : null),
    h('td', {class: 'n'}, r.counts ? r.counts.people : '—'), h('td', {class: 'n'}, r.counts ? r.counts.items : '—'), h('td', {class: 'n'}, r.counts ? r.counts.active_grants : '—'),
    h('td', {class: 'l'}, r.my_access ? h('button', {class: 'btn sm primary', type: 'button', onclick: () => tenancySwitch(r.id)}, 'Enter') :
      r.kind !== 'platform' && r.id !== (t.home || {}).id ? h('button', {class: 'btn sm', type: 'button', onclick: () => accessDialog(r, true)}, 'Get access') : h('span', {class: 'small faint'}, r.id === (t.home || {}).id ? 'your workspace' : '')));
  const body = [];
  const tops = rows.filter(r => r.kind === 'platform');
  for (const p of tops) body.push(row(p, 0));
  for (const p of partners) { body.push(row(p, tops.length ? 1 : 0)); for (const c of clients.filter(c => c.parent_id === p.id)) body.push(row(c, tops.length ? 2 : 1)); }
  for (const c of clients.filter(c => !partners.some(p => p.id === c.parent_id))) body.push(row(c, tops.length ? 1 : 0));
  main.replaceChildren(h('div', {class: 'page'},
    pageHead({crumbs: [['Home', '#/'], ['Tenants & partners']], eyebrow: brandName() + ' · Platform', title: 'Tenants & partners',
      promise: d.platform ? 'Service partners, their clients and direct Enterprise clients: each a workspace of its own, with its edition and modules, who may enter it and until when, hand-overs, usage and how it is deployed.'
        : 'Your partner workspace and your clients: their modules, who from your team may enter them and until when, hand-overs, usage and deployment.',
      actions: h('div', {class: 'row'}, h('a', {class: 'btn', href: '#/tenants/usage'}, icon('pulse'), 'Usage & statements'),
        h('button', {class: 'btn primary', type: 'button', onclick: () => newTenantDialog(d)}, icon('plus'), d.platform ? 'New workspace' : 'New client'))}),
    h('div', {class: 'g4', style: 'margin-bottom:18px'},
      kpiTile('Service partners', String(partners.length), d.platform ? 'white-labelled, B2B2B' : 'your partner workspace'),
      kpiTile('Clients', String(clients.length), `${clients.filter(c => partners.some(p => p.id === c.parent_id)).length} through partners · ${clients.filter(c => !partners.some(p => p.id === c.parent_id)).length} direct`),
      kpiTile('Access open now', String(grants), 'time-boxed, with a reason, audited'),
      kpiTile('Suspended', String(rows.filter(r => r.status === 'suspended').length), 'no one can work in them')),
    h('div', {class: 'card', style: 'padding:0;overflow:auto'},
      h('div', {class: 'card-head', style: 'padding:14px 18px 0'}, h('h3', {}, 'Workspaces'), h('span', {class: 'sp'}), h('span', {class: 'small muted'}, `${rows.length} in all`)),
      rows.length ? h('table', {class: 'utable'}, h('tr', {}, ['Workspace', 'Kind', 'Edition', 'Status', 'People', 'Items', 'Access open', ''].map((x, i) => h('th', {class: [1, 2, 3, 7].includes(i) ? 'l' : i === 0 ? '' : ''}, x))), body)
        : h('div', {class: 'muted small', style: 'padding:8px 18px 16px'}, 'No workspaces yet. Create the first partner or client.'))));
}

function newTenantDialog(d) {
  const f = {name: h('input', {placeholder: 'e.g. Northwind Partners', maxlength: 80}), kind: h('select', {}, d.platform ? [h('option', {value: 'partner'}, 'Service partner'), h('option', {value: 'client', selected: true}, 'Client')] : [h('option', {value: 'client'}, 'Client')]),
    parent: h('select', {}, [d.platform ? h('option', {value: ''}, 'Direct (the platform)') : null, ...d.partners.map(p => h('option', {value: p.id}, p.name))]),
    edition: h('select', {}, [h('option', {value: ''}, 'The usual for its kind'), h('option', {value: 'enterprise'}, 'Enterprise'), h('option', {value: 'partner'}, 'Service partner'), d.platform ? h('option', {value: 'both'}, 'Both editions') : null]),
    admin_name: h('input', {placeholder: 'Full name'}), admin_email: h('input', {type: 'email', placeholder: 'name@company.com'}),
    deployment: h('select', {}, Object.entries(d.deployments).map(([k, v]) => h('option', {value: k}, v))),
    partner_access: h('select', {}, [h('option', {value: 'open'}, 'Partner admins grant access themselves'), h('option', {value: 'approval'}, 'The client approves every request')])};
  const err = h('div', {class: 'err-msg', role: 'alert'});
  const label = (t, el, hint) => h('label', {class: 'tf'}, h('span', {}, t), el, hint ? h('span', {class: 'small muted'}, hint) : null);
  const sync = () => { f.parent.closest('label').hidden = f.kind.value !== 'client'; f.partner_access.closest('label').hidden = f.kind.value !== 'client'; };
  f.kind.onchange = sync;
  const go = h('button', {class: 'btn primary', type: 'button', onclick: async () => {
    go.disabled = true; err.textContent = '';
    try {
      const r = await api('/api/tenancy/tenants', {json: {name: f.name.value, kind: f.kind.value, parent_id: f.kind.value === 'client' ? (f.parent.value || null) : null,
        edition: f.edition.value || null, admin_name: f.admin_name.value, admin_email: f.admin_email.value, deployment: f.deployment.value, partner_access: f.partner_access.value}});
      m.remove();
      setupLinkDialog(r.tenant.name, r.admin.email, r.setup_link);
      renderTenants();
    } catch (e) { err.textContent = e.message; go.disabled = false; }
  }}, 'Create workspace');
  const m = modal(d.platform ? 'New workspace' : 'New client', h('div', {class: 'mbody', style: 'max-width:560px'},
    h('p', {class: 'muted small', style: 'margin-top:0'}, 'A workspace of its own: its own data, folders, people, secrets and audit. Its first admin gets a one-time link to set a password (or signs in with the workspace’s identity provider once it is set up).'),
    h('div', {class: 'g2'}, label('Name', f.name), label('Kind', f.kind)),
    h('div', {class: 'g2'}, label('Belongs to', f.parent), label('Edition', f.edition, 'decides which modules it can have')),
    h('div', {class: 'g2'}, label('First admin', f.admin_name), label('Their work email', f.admin_email)),
    h('div', {class: 'g2'}, label('Deployment', f.deployment), label('Partner access', f.partner_access)),
    err, h('div', {class: 'row', style: 'justify-content:flex-end;margin-top:12px'}, go)));
  sync();
}
function setupLinkDialog(name, email, link) {
  const url = location.origin + link;
  modal(`Set-up link for ${name}`, h('div', {class: 'mbody', style: 'max-width:600px'},
    h('p', {style: 'margin-top:0'}, `Send this link to ${email}. It works once, for 72 hours, and lets them set the workspace’s first password. It is not shown again (make a new one from the workspace’s page if it is lost).`),
    h('div', {class: 'row', style: 'flex-wrap:nowrap'}, h('code', {class: 'mono setuplink'}, url), copyBtn(url))));
}

function accessDialog(r, self, onDone) {
  const role = h('select', {}, [h('option', {value: 'admin'}, 'Admin'), h('option', {value: 'dev'}, 'BI Dev / Analyst'), h('option', {value: 'viewer'}, 'Viewer')]);
  const hours = h('select', {}, [[1, '1 hour'], [4, '4 hours'], [8, '8 hours (a working day)'], [24, '1 day'], [72, '3 days'], [168, '1 week'], [720, '30 days']].map(([v, t]) => h('option', {value: v, selected: v === 8}, t)));
  const reason = h('textarea', {rows: 3, placeholder: 'Why access is needed — the client sees this and it is kept in the audit (e.g. “Migration wave 2: convert the finance reports”)', maxlength: 300});
  const who = h('select', {}, h('option', {value: ''}, 'Me'));
  if (!self) api('/api/tenancy/people').then(p => who.replaceChildren(h('option', {value: ''}, 'Me'), ...p.people.filter(x => x.id !== (S.me || {}).id).map(x => h('option', {value: x.id}, `${x.name} · ${x.email}`)))).catch(() => {});
  const err = h('div', {class: 'err-msg', role: 'alert'});
  const go = h('button', {class: 'btn primary', type: 'button', onclick: async () => {
    go.disabled = true; err.textContent = '';
    try {
      const g = await api(`/api/tenancy/tenants/${r.id}/access`, {json: {user_id: who.value || null, role: role.value, hours: Number(hours.value), reason: reason.value}});
      m.remove();
      if (g.status === 'pending') notify(`${r.name} approves partner access: the request is waiting for its admins.`, 'ok');
      else if (!who.value && await confirmBox(`Enter ${r.name} now?`, `Your access is open until ${when(g.expires)}. You will work inside ${r.name} as a guest until you go back.`, 'Enter now', false)) tenancySwitch(r.id);
      else notify('Access given.', 'ok');
      if (onDone) onDone();
    } catch (e) { err.textContent = e.message; go.disabled = false; }
  }}, self ? 'Get access' : 'Give access');
  const label = (t, el) => h('label', {class: 'tf'}, h('span', {}, t), el);
  const m = modal(`${self ? 'Get access to' : 'Give access to'} ${r.name}`, h('div', {class: 'mbody', style: 'max-width:540px'},
    h('p', {class: 'muted small', style: 'margin-top:0'}, `Access is time-boxed and audited in ${r.name}'s own log; its admins are told and can end it at any time.`),
    self ? null : label('Who', who), h('div', {class: 'g2'}, label('Role inside', role), label('For', hours)), label('Reason', reason),
    err, h('div', {class: 'row', style: 'justify-content:flex-end;margin-top:12px'}, go)));
}

async function renderTenantPage(id, tab) {
  const main = $('#main');
  if (!S.tview || S.tview.tenant.id !== id) main.replaceChildren(skel('page'));
  let d;
  try { d = S.tview = await api('/api/tenancy/tenants/' + encodeURIComponent(id)); }
  catch (e) { main.replaceChildren(h('div', {class: 'page'}, pageHead({crumbs: [['Home', '#/'], ['Tenants & partners', '#/tenants'], [id]], title: 'Workspace'}), h('div', {class: 'note err'}, e.message))); return; }
  if (!location.hash.startsWith('#/tenants/' + id)) return;
  const t = d.tenant, tabs = TTABS.filter(([k]) => k !== 'handover' || d.may.handover || d.handovers.length);
  const cur = tabs.some(x => x[0] === tab) ? tab : 'overview';
  const actions = h('div', {class: 'row'},
    d.may.enter && t.status === 'active' ? h('button', {class: 'btn', type: 'button', onclick: () => accessDialog(t, true, () => renderTenantPage(id, cur))}, icon('external'), 'Get access') : null,
    d.may.suspend ? h('button', {class: 'btn' + (t.status === 'active' ? ' danger' : ''), type: 'button', onclick: async () => {
      const off = t.status === 'active';
      if (off && !await confirmBox(`Suspend ${t.name}?`, 'Nobody can work in it until it is resumed: its people are refused, its schedules and background checks stop, and every switch into it ends. Its data stays as it is.', 'Suspend')) return;
      try { await api(`/api/tenancy/tenants/${id}`, {method: 'PATCH', json: {status: off ? 'suspended' : 'active'}}); notify(off ? 'Suspended.' : 'Resumed.', 'ok'); renderTenantPage(id, cur); } catch (e) { notify(e.message, 'err'); }
    }}, t.status === 'active' ? 'Suspend' : 'Resume') : null);
  const view = h('div', {class: 'subbody'});
  main.replaceChildren(h('div', {class: 'page'},
    pageHead({crumbs: [['Home', '#/'], ['Tenants & partners', '#/tenants'], [t.name]], eyebrow: `${(TKIND[t.kind] || [t.kind])[0]} · ${t.edition_label}${t.parent_name ? ' · ' + t.parent_name : ''}`, title: t.name,
      promise: t.kind === 'partner' ? 'A service partner: its own workspace, white-labelled, and the clients it serves.' : t.kind === 'platform' ? 'The platform’s own workspace.' : `A client${t.parent_name ? ' of ' + t.parent_name : ''}: its own data, people and audit.`,
      actions}),
    h('div', {class: 'row', style: 'gap:8px;margin:-6px 0 14px'}, tpill(TSTATUS, t.status), tpill(TKIND, t.kind), h('span', {class: 'chipx mono'}, t.id)),
    h('nav', {class: 'tabs', role: 'tablist', 'aria-label': 'Workspace'}, tabs.map(([k, l]) => h('a', {href: `#/tenants/${id}/${k}`, role: 'tab', class: k === cur ? 'on' : '', 'aria-selected': String(k === cur)}, l))),
    view));
  try { view.replaceChildren(await ({overview: tOverview, modules: tModules, access: tAccess, handover: tHandover, usage: tUsage, deployment: tDeploy}[cur])(d)); }
  catch (e) { view.replaceChildren(h('div', {class: 'note err'}, e.message)); }
}

function tOverview(d) {
  const t = d.tenant, c = t.counts || {};
  const policy = (d.policies || {})[t.partner_access] || t.partner_access;
  return h('div', {class: 'g-side'},
    h('div', {class: 'stack'},
      h('div', {class: 'g4'}, kpiTile('People', String(c.people || 0), c.guests ? `${c.guests} guest${c.guests === 1 ? '' : 's'} from outside` : 'its own people'),
        kpiTile('Items', String(c.items || 0), 'dashboards and module work'), kpiTile('Access open', String(c.active_grants || 0), 'from the platform or its partner'),
        kpiTile('This month', tcompact(d.usage.total, d.usage.currency), `AI and data at cost USD ${Number(d.usage.usage.cost_usd || 0).toFixed(2)}`, {href: `#/tenants/${t.id}/usage`})),
      h('div', {class: 'card', style: 'margin:0'}, h('div', {class: 'card-head'}, h('h3', {}, 'Admins'), h('span', {class: 'sp'}),
          h('button', {class: 'btn sm', type: 'button', onclick: async () => { try { const r = await api(`/api/tenancy/tenants/${t.id}/setup-link`, {json: {}}); setupLinkDialog(t.name, r.email, r.setup_link); } catch (e) { notify(e.message, 'err'); } }}, 'New set-up link')),
        d.admins.length ? h('table', {class: 'utable'}, h('tr', {}, ['Name', 'Email', 'Password', 'Last sign-in'].map(x => h('th', {class: 'l'}, x))),
          d.admins.map(a => h('tr', {}, h('td', {class: 'l'}, a.name), h('td', {class: 'l'}, a.email), h('td', {class: 'l'}, a.has_password ? h('span', {class: 'tag ok'}, 'set') : h('span', {class: 'tag warn'}, 'link not used yet')),
            h('td', {class: 'l'}, a.last_login ? ago(a.last_login) : '—')))) : h('p', {class: 'muted small'}, 'No admin yet.')),
      d.children.length ? h('div', {class: 'card', style: 'margin:0;padding:0;overflow:auto'}, h('div', {class: 'card-head', style: 'padding:14px 18px 0'}, h('h3', {}, 'Its clients')),
        h('table', {class: 'utable'}, h('tr', {}, ['Client', 'Status', 'Partner access'].map(x => h('th', {class: 'l'}, x))),
          d.children.map(ch => h('tr', {}, h('td', {class: 'l'}, h('a', {href: `#/tenants/${ch.id}`}, ch.name)), h('td', {class: 'l'}, tpill(TSTATUS, ch.status)), h('td', {class: 'l small'}, (d.policies || {})[ch.partner_access] || ch.partner_access))))) : null),
    h('div', {class: 'stack'},
      h('div', {class: 'card', style: 'margin:0'}, h('h3', {}, 'Details'),
        h('dl', {class: 'kv'}, [['Id', h('span', {class: 'mono'}, t.id)], ['Kind', (TKIND[t.kind] || [t.kind])[0]], ['Belongs to', t.parent_name || '—'], ['Edition', t.edition_label],
          ['Deployment', (d.deployments || {})[t.deployment] || t.deployment], ['Sign-in address', t.host || 'the platform’s'], t.kind === 'client' ? ['Partner access', policy] : null,
          ['Created', when(t.created)]].filter(Boolean).flatMap(([k, v]) => [h('dt', {}, k), h('dd', {}, v)])))));
}

function tModules(d) {
  const editable = d.may.modules;
  const changes = {};
  const groups = {};
  for (const m of d.modules) (groups[m.pillar] = groups[m.pillar] || []).push(m);
  const save = h('button', {class: 'btn primary', type: 'button', disabled: true, onclick: async () => {
    save.disabled = true;
    try { await api(`/api/tenancy/tenants/${d.tenant.id}/modules`, {method: 'PUT', json: {modules: changes}}); notify('Modules saved.', 'ok'); renderTenantPage(d.tenant.id, 'modules'); }
    catch (e) { notify(e.message, 'err'); save.disabled = false; }
  }}, 'Save changes');
  const pname = id => ((S.registry || {}).pillars || []).find(p => p.id === id)?.name || ({hidden: 'Inside the modules', platform: 'Platform'})[id] || id;
  return h('div', {class: 'stack'},
    h('div', {class: 'banner info'}, h('div', {class: 'ic'}, icon('info')), h('div', {class: 'txt'}, h('div', {class: 't'}, `${d.tenant.edition_label} edition`),
      h('div', {class: 'd'}, editable ? 'Switch modules on or off for this workspace. A module that is off disappears from its menu, its screens say so and its API answers that it is not switched on; nothing is deleted.'
        : 'Only the platform’s admins change what a service partner has.'))),
    Object.entries(groups).map(([pl, ms]) => h('div', {class: 'card', style: 'margin:0;padding:0;overflow:auto'}, h('div', {class: 'card-head', style: 'padding:14px 18px 0'}, h('h3', {}, pname(pl))),
      h('table', {class: 'utable'}, ms.map(m => {
        const box = h('input', {type: 'checkbox', checked: m.on, disabled: !editable || m.core || m.locked, 'aria-label': `${m.name}: switched ${m.on ? 'on' : 'off'}`,
          onchange: e => { changes[m.id] = e.target.checked; save.disabled = !Object.keys(changes).length; }});
        return h('tr', {}, h('td', {style: 'width:44px'}, box), h('td', {class: 'l'}, h('b', {}, m.name), h('div', {class: 'small muted'}, m.status === 'available' ? 'Live' : m.status === 'partly' ? 'Partly live' : 'Planned')),
          h('td', {class: 'l small'}, m.core ? 'Core — always on' : m.why === 'edition' ? 'Not in this edition' : m.why === 'partner' ? 'Its partner does not have it' : m.on ? 'On' : 'Off'));
      })))),
    editable ? h('div', {class: 'row', style: 'justify-content:flex-end'}, save) : null);
}

function grantRows(grants, canEnd, onEnd) {
  return grants.length ? h('table', {class: 'utable'}, h('tr', {}, ['Who', 'From', 'Role', 'Status', 'Until', 'Reason', ''].map(x => h('th', {class: 'l'}, x))),
    grants.map(g => h('tr', {}, h('td', {class: 'l'}, h('b', {}, g.person.name || g.person.id), h('div', {class: 'small muted'}, g.person.email || '')), h('td', {class: 'l'}, g.home_name || g.home_tenant),
      h('td', {class: 'l'}, g.role_label), h('td', {class: 'l'}, tpill(GSTATUS, g.status)), h('td', {class: 'l small'}, g.live ? `${when(g.expires)} · ${tleft(g.left_s)}` : g.expires ? when(g.expires) : '—'),
      h('td', {class: 'l small', style: 'max-width:280px'}, g.reason, g.end_reason ? h('div', {class: 'muted'}, 'Ended: ' + g.end_reason) : null),
      h('td', {class: 'l'}, canEnd && ['active', 'pending'].includes(g.status) ? h('button', {class: 'btn sm danger', type: 'button', onclick: async () => {
        if (!await confirmBox('End this access?', `${g.person.name || 'This person'} stops working in ${g.tenant_name} at once. Their work there stays.`, 'End access')) return;
        try { await api(`/api/tenancy/access/${g.id}/revoke`, {json: {reason: 'Ended by an admin'}}); notify('Access ended.', 'ok'); onEnd(); } catch (e) { notify(e.message, 'err'); }
      }}, 'End') : null))))
    : h('p', {class: 'muted small', style: 'padding:0 18px 12px'}, 'Nobody from outside has had access yet.');
}

function tAccess(d) {
  const t = d.tenant;
  return h('div', {class: 'stack'},
    h('div', {class: 'card', style: 'margin:0;padding:0;overflow:auto'}, h('div', {class: 'card-head', style: 'padding:14px 18px 0'}, h('h3', {}, 'Who from outside may act here'), h('span', {class: 'sp'}),
        d.may.enter && t.status === 'active' ? h('button', {class: 'btn sm primary', type: 'button', onclick: () => accessDialog(t, false, () => renderTenantPage(t.id, 'access'))}, icon('plus'), 'Give access') : null),
      grantRows(d.grants, true, () => renderTenantPage(t.id, 'access'))),
    h('p', {class: 'small muted'}, t.kind === 'client' ? `Policy: ${(d.policies || {})[t.partner_access] || t.partner_access}. ${t.name}'s own admins see the same list under Administration › Partner access and can end any of it.` : 'Access into a partner is for the platform’s support only.'));
}

async function tHandover(d) {
  const t = d.tenant;
  const done = h('div', {class: 'stack'}, d.handovers.map(x => h('div', {class: 'card', style: 'margin:0'}, h('div', {class: 'card-head'}, h('h3', {}, `Handed over ${when(x.created)}`), h('span', {class: 'sp'}), h('span', {class: 'pill plain ok'}, 'Recorded')),
    h('p', {style: 'white-space:pre-wrap'}, x.delivered), x.evidence.length ? h('ul', {class: 'small'}, x.evidence.map(e => h('li', {}, e))) : null,
    h('div', {class: 'small muted'}, `${x.summary.grants_ended || 0} access grant(s) ended · ${x.summary.guests || 0} guest(s) · work moved to ${x.summary.owner || '—'}${x.move_direct ? ' · now a direct client' : ''}`))));
  if (!d.may.handover) return h('div', {class: 'stack'}, d.handovers.length ? done : h('p', {class: 'muted'}, 'Nothing to hand over: this workspace is not a partner’s client, or it was already handed over.'));
  let people = [];
  try { people = (await api(`/api/tenancy/tenants/${t.id}/handover-people`)).people; } catch (e) {}
  const owner = h('select', {}, people.map(p => h('option', {value: p.id}, `${p.name} · ${p.email}`)));
  const delivered = h('textarea', {rows: 4, placeholder: 'What was delivered (scope, waves, what is proven and signed off)'});
  const evidence = h('textarea', {rows: 3, placeholder: 'Evidence, one per line (e.g. “Proof pack v3”, “UAT sign-off 2026-11-01”)'});
  const direct = h('input', {type: 'checkbox'});
  const err = h('div', {class: 'err-msg', role: 'alert'});
  const go = h('button', {class: 'btn danger solid', type: 'button', onclick: async () => {
    if (!await confirmBox(`Hand ${t.name} over?`, `Every access from ${t.parent_name} ends now, its people’s work in ${t.name} moves to the owner you chose, their stored keys there are removed, and partner access stays ended until ${t.name}'s own admin reopens it.`, 'Hand over')) return;
    go.disabled = true; err.textContent = '';
    try {
      await api(`/api/tenancy/tenants/${t.id}/handover`, {json: {owner_id: owner.value, delivered: delivered.value, evidence: evidence.value.split('\n').map(s => s.trim()).filter(Boolean), move_direct: direct.checked}});
      notify('Hand-over recorded.', 'ok'); renderTenantPage(t.id, 'handover');
    } catch (e) { err.textContent = e.message; go.disabled = false; }
  }}, 'Record the hand-over');
  return h('div', {class: 'g-side'},
    h('div', {class: 'card', style: 'margin:0'}, h('h3', {}, `Hand ${t.name} over`),
      h('p', {class: 'small muted'}, `When the engagement ends: access from ${t.parent_name} is ended, the work its people did here is handed to the client’s owner, and the hand-over is kept with its evidence.`),
      h('label', {class: 'tf'}, h('span', {}, 'Who takes over'), people.length ? owner : h('span', {class: 'small err'}, `${t.name} has nobody of its own yet.`)),
      h('label', {class: 'tf'}, h('span', {}, 'Delivered'), delivered), h('label', {class: 'tf'}, h('span', {}, 'Evidence'), evidence),
      h('label', {class: 'row', style: 'gap:8px;margin:6px 0'}, direct, h('span', {}, `Bill ${t.name} directly from now on (it becomes a direct client)`)),
      err, h('div', {class: 'row', style: 'justify-content:flex-end'}, go)),
    d.handovers.length ? done : h('div', {class: 'card', style: 'margin:0'}, h('h3', {}, 'History'), h('p', {class: 'muted small'}, 'No hand-over yet.')));
}

function statementCard(s) {
  return h('div', {class: 'card', style: 'margin:0;padding:0;overflow:auto'}, h('div', {class: 'card-head', style: 'padding:14px 18px 0'}, h('h3', {}, `Statement · ${s.month}`), h('span', {class: 'sp'}), h('b', {}, tmoney(s.total, s.currency))),
    h('table', {class: 'utable'}, h('tr', {}, ['Item', 'Qty', 'Unit', 'Amount'].map((x, i) => h('th', {class: i ? '' : 'l'}, x))),
      s.lines.map(li => h('tr', {}, h('td', {class: 'l'}, li.item), h('td', {class: 'n'}, li.qty), h('td', {class: 'n'}, tmoney(li.unit, s.currency)), h('td', {class: 'n'}, tmoney(li.amount, s.currency))))));
}
function tUsage(d) {
  const s = d.usage, u = s.usage;
  return h('div', {class: 'stack'},
    h('div', {class: 'g4'}, kpiTile('AI and data at cost', usd(u.cost_usd), `${u.ai_runs} AI run${u.ai_runs === 1 ? '' : 's'} this month`), kpiTile('People', String(u.people), 'its own, active'),
      kpiTile('Items', String(u.items), 'dashboards and module work'), kpiTile('Storage', size(u.storage_bytes || 0), 'its folders')),
    statementCard(s),
    h('p', {class: 'small muted'}, 'Priced by the platform’s price book (Usage & statements). Costs come from each AI run, warehouse query and extract recorded in this workspace.'));
}
function tDeploy(d) {
  const t = d.tenant;
  const dep = h('select', {}, Object.entries(d.deployments).map(([k, v]) => h('option', {value: k, selected: k === t.deployment}, v)));
  const host = h('input', {value: t.host || '', placeholder: 'e.g. relay.northwind.example (optional)'});
  const out = h('div');
  const saveBtn = h('button', {class: 'btn', type: 'button', onclick: async () => {
    try { await api(`/api/tenancy/tenants/${t.id}`, {method: 'PATCH', json: {deployment: dep.value, host: host.value}}); notify('Saved.', 'ok'); renderTenantPage(t.id, 'deployment'); } catch (e) { notify(e.message, 'err'); }
  }}, 'Save');
  const pack = h('button', {class: 'btn primary', type: 'button', onclick: async () => {
    pack.disabled = true; out.replaceChildren(h('div', {class: 'small muted'}, 'Packing the workspace…'));
    try {
      const r = await api(`/api/tenancy/tenants/${t.id}/pack`, {method: 'POST'});
      out.replaceChildren(h('div', {class: 'banner ok'}, h('div', {class: 'ic'}, icon('check')), h('div', {class: 'txt'}, h('div', {class: 't'}, 'The pack is ready (for 24 hours)'),
        h('div', {class: 'd'}, `${size(r.bytes)} · ${r.files.join(', ')}`))),
        h('p', {}, h('b', {}, 'The secrets key, shown once: '), 'keep it apart from the pack; the dedicated install needs it to open the workspace’s stored credentials.'),
        h('div', {class: 'row', style: 'flex-wrap:nowrap'}, h('code', {class: 'mono setuplink'}, r.key), copyBtn(r.key)),
        h('a', {class: 'btn', href: r.download, download: r.name, style: 'margin-top:10px'}, icon('download'), 'Download the pack'));
    } catch (e) { out.replaceChildren(h('div', {class: 'note err'}, e.message)); }
    pack.disabled = false;
  }}, icon('download'), 'Make the deployment pack');
  return h('div', {class: 'g-side'},
    h('div', {class: 'card', style: 'margin:0'}, h('h3', {}, 'Where it runs'),
      h('label', {class: 'tf'}, h('span', {}, 'Deployment'), dep), h('label', {class: 'tf'}, h('span', {}, 'Sign-in address'), host, h('span', {class: 'small muted'}, 'People who open this address see this workspace’s sign-in page and brand.')),
      h('div', {class: 'row', style: 'justify-content:flex-end'}, saveBtn)),
    h('div', {class: 'card', style: 'margin:0'}, h('h3', {}, 'Inside the client’s network'),
      h('p', {class: 'small muted'}, 'A dedicated install runs Relay for this one workspace inside the client’s own network. The pack holds the workspace’s export (data, folders, library, reports, secrets under a new key), the settings of a one-workspace install and a Kubernetes overlay with the optional AI runners.'),
      t.kind === 'platform' ? h('p', {class: 'small'}, 'The platform’s own workspace is this install.') : pack, out));
}

/* ---------------- usage & statements ---------------- */
async function renderUsage() {
  const main = $('#main');
  main.replaceChildren(skel('page', 'Adding up this month’s usage across every workspace. This can take a few seconds.'));
  const month = S.umonth || thisMonth();
  let d, pb;
  try { [d, pb] = await Promise.all([api('/api/tenancy/usage?month=' + month), api('/api/tenancy/prices')]); }
  catch (e) { main.replaceChildren(h('div', {class: 'page'}, h('div', {class: 'note err'}, e.message))); return; }
  if (!location.hash.startsWith('#/tenants/usage')) return;
  const pick = h('input', {type: 'month', class: 'tmonth', value: month, 'aria-label': 'Month', onchange: e => { S.umonth = e.target.value; renderUsage(); }});
  const names = Object.fromEntries(d.tenants.map(s => [s.tenant.id, s.tenant.name]));
  const p = pb.prices;
  const priceForm = () => {
    const f = {currency: h('input', {value: p.currency, maxlength: 3}), usd_rate: h('input', {type: 'number', step: '0.01', value: p.usd_rate}),
      enterprise: h('input', {type: 'number', value: p.edition_fee.enterprise}), partner: h('input', {type: 'number', value: p.edition_fee.partner}),
      module_fee: h('input', {type: 'number', value: p.module_fee}), ai_markup_pct: h('input', {type: 'number', value: p.ai_markup_pct})};
    const label = (t, el) => h('label', {class: 'tf'}, h('span', {}, t), el);
    return h('div', {}, h('div', {class: 'g3'}, label('Currency', f.currency), label('Value of 1 USD in it', f.usd_rate), label('AI mark-up %', f.ai_markup_pct),
        label('Enterprise / month', f.enterprise), label('Service partner / month', f.partner), label('Per module / month', f.module_fee)),
      h('div', {class: 'row', style: 'justify-content:flex-end'}, h('button', {class: 'btn primary', type: 'button', onclick: async () => {
        try { await api('/api/tenancy/prices', {method: 'PUT', json: {currency: f.currency.value.toUpperCase(), usd_rate: Number(f.usd_rate.value), module_fee: Number(f.module_fee.value), ai_markup_pct: Number(f.ai_markup_pct.value),
          edition_fee: {enterprise: Number(f.enterprise.value), partner: Number(f.partner.value)}}}); notify('Price book saved.', 'ok'); renderUsage(); } catch (e) { notify(e.message, 'err'); }
      }}, 'Save the price book')));
  };
  main.replaceChildren(h('div', {class: 'page'},
    pageHead({crumbs: [['Home', '#/'], ['Tenants & partners', '#/tenants'], ['Usage & statements']], eyebrow: brandName() + ' · Platform', title: 'Usage & statements',
      promise: 'Each workspace’s AI and data costs for the month, priced by the price book: per tenant, and rolled up for each partner with its clients.',
      actions: h('div', {class: 'row'}, pick, h('a', {class: 'btn', href: `/api/tenancy/usage.csv?month=${month}`, download: `relay-usage-${month}.csv`}, icon('download'), 'CSV'))}),
    h('div', {class: 'g4', style: 'margin-bottom:18px'}, kpiTile('Billed this month', tcompact(d.total, d.currency), `${tmoney(d.total, d.currency)} · ${d.tenants.length} workspace${d.tenants.length === 1 ? '' : 's'}`),
      kpiTile('AI and data at cost', usd(d.ai_cost_usd), 'before the mark-up'), kpiTile('Partners', String(d.partners.length), 'own workspace + clients'),
      kpiTile('Month', d.month, 'UTC calendar month')),
    d.partners.length ? h('div', {class: 'card', style: 'padding:0;overflow:auto'}, h('div', {class: 'card-head', style: 'padding:14px 18px 0'}, h('h3', {}, 'Per partner')),
      h('table', {class: 'utable'}, h('tr', {}, ['Partner', 'Own', 'Clients', 'Clients total', 'AI at cost', 'Total'].map((x, i) => h('th', {class: i ? '' : 'l'}, x))),
        d.partners.map(r => h('tr', {}, h('td', {class: 'l'}, h('a', {href: `#/tenants/${r.partner.id}`}, r.partner.name)), h('td', {class: 'n'}, tmoney(r.own, d.currency)), h('td', {class: 'n'}, r.clients),
          h('td', {class: 'n'}, tmoney(r.clients_total, d.currency)), h('td', {class: 'n'}, usd(r.ai_cost_usd)), h('td', {class: 'n'}, h('b', {}, tmoney(r.total, d.currency))))))) : null,
    h('div', {class: 'card', style: 'padding:0;overflow:auto'}, h('div', {class: 'card-head', style: 'padding:14px 18px 0'}, h('h3', {}, 'Per workspace')),
      h('table', {class: 'utable'}, h('tr', {}, ['Workspace', 'Kind', 'Through', 'AI runs', 'AI at cost', 'Modules', 'Total'].map((x, i) => h('th', {class: i < 3 ? 'l' : ''}, x))),
        d.tenants.map(s => h('tr', {}, h('td', {class: 'l'}, h('a', {href: `#/tenants/${s.tenant.id}/usage`}, s.tenant.name)), h('td', {class: 'l'}, tpill(TKIND, s.tenant.kind)),
          h('td', {class: 'l small'}, names[s.tenant.parent_id] || (s.tenant.kind === 'platform' ? '—' : 'direct')), h('td', {class: 'n'}, s.usage.ai_runs), h('td', {class: 'n'}, usd(s.usage.cost_usd)),
          h('td', {class: 'n'}, s.modules.length), h('td', {class: 'n'}, h('b', {}, tmoney(s.total, s.currency))))))),
    h('div', {class: 'card'}, h('div', {class: 'card-head'}, h('h3', {}, 'Price book'), h('span', {class: 'sp'}), h('span', {class: 'small muted'}, pb.editable ? 'per tenant + modules, metered AI cost' : 'set by the platform')),
      pb.editable ? priceForm() : h('dl', {class: 'kv'}, [['Currency', p.currency], ['Enterprise / month', tmoney(p.edition_fee.enterprise, p.currency)], ['Service partner / month', tmoney(p.edition_fee.partner, p.currency)],
        ['Per module / month', tmoney(p.module_fee, p.currency)], ['AI mark-up', p.ai_markup_pct + ' %']].flatMap(([k, v]) => [h('dt', {}, k), h('dd', {}, v)])))));
}

/* ---------------- Admin › Partner access (the workspace's own admins) ---------------- */
async function adminPartnerAccess() {
  const d = await api('/api/admin/partner-access');
  const t = d.tenant, wrap = h('div', {class: 'stack'});
  const seg = h('div', {class: 'segbtn', role: 'group', 'aria-label': 'Partner access policy'}, ['open', 'approval'].map(k => h('button', {type: 'button', class: d.policy === k ? 'on' : '', 'aria-pressed': String(d.policy === k),
    disabled: !d.editable || d.policy === k, onclick: async () => {
      try { await api('/api/admin/partner-access', {method: 'PUT', json: {policy: k}}); notify('Saved.', 'ok'); location.hash = '#/admin/partner-access'; renderAdmin(); } catch (e) { notify(e.message, 'err'); }
    }}, k === 'open' ? 'Partner admins grant it' : 'We approve every request')));
  wrap.append(
    h('div', {class: 'card', style: 'margin:0'}, h('h3', {}, d.partner ? `Access from ${d.partner.name}` : 'Access from outside'),
      h('p', {class: 'small muted'}, d.partner ? `${d.partner.name} serves ${t.name}. Its people can work here only with time-boxed access you can see and end, and only as the role it was given. Everything they do is in your audit log.`
        : `People from outside ${t.name} (the platform’s support) can work here only with time-boxed access you can see and end.`),
      t.kind === 'client' ? h('div', {class: 'row', style: 'gap:12px;align-items:center'}, h('span', {class: 'small'}, 'Who opens access:'), seg,
        d.policy === 'ended' ? h('span', {class: 'pill plain mute'}, 'Ended at hand-over — choose one to reopen') : null) : null,
      !d.editable ? h('p', {class: 'small faint'}, 'Only this workspace’s own admins change this.') : null),
    h('div', {class: 'card', style: 'margin:0;padding:0;overflow:auto'}, h('div', {class: 'card-head', style: 'padding:14px 18px 0'}, h('h3', {}, 'Access, newest first')),
      grantRows(d.grants, d.editable, () => renderAdmin())),
    d.guests.length ? h('div', {class: 'card', style: 'margin:0;padding:0;overflow:auto'}, h('div', {class: 'card-head', style: 'padding:14px 18px 0'}, h('h3', {}, 'Guests'), h('span', {class: 'sp'}), h('span', {class: 'small muted'}, 'their rows here, kept for the record')),
      h('table', {class: 'utable'}, h('tr', {}, ['Name', 'From', 'Role', 'Now'].map(x => h('th', {class: 'l'}, x))),
        d.guests.map(g => h('tr', {}, h('td', {class: 'l'}, g.name, h('div', {class: 'small muted'}, g.email)), h('td', {class: 'l'}, g.home_name || g.home_tenant), h('td', {class: 'l'}, g.org_role === 'admin' ? 'Admin' : 'Member'),
          h('td', {class: 'l'}, g.active ? h('span', {class: 'tag ok'}, 'can act') : h('span', {class: 'tag'}, 'no access')))))) : null,
    d.handovers.length ? h('div', {class: 'card', style: 'margin:0'}, h('h3', {}, 'Hand-overs'), d.handovers.map(x => h('div', {style: 'margin:8px 0'}, h('b', {}, when(x.created)), ' — ', x.delivered))) : null);
  return wrap;
}
