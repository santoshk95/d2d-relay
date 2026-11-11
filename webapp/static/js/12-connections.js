/* ---------------- Connections (phase 3 warehouses; P10 hub): every system Relay can reach, in one place — how it signs in,
   what it may do (read-only by default; writes only with a per-change approval), who may use it, which modules rely on it,
   last test and status. The new-connection wizard (system → sign-in → scope → test & share) opens from the hub, from Start
   ("Connect systems too") and from every module page's Connections card. ---------------- */
const AUTH_LABEL = {oauth: 'Sign in (OAuth, offline access)', password: 'User name + password', keypair: 'Key pair (private key)',
  service_account: 'Service account (JSON key)', aws_keys: 'AWS access keys', api_key: 'API key or token', wallet: 'Wallet (mutual TLS) + password'};
const bigSecret = n => n.endsWith('_json') || n.endsWith('_pem') || n === 'private_key';     // pasted files get a text area
const AUTH_HINT = {wallet: 'for Autonomous Database with mutual TLS: the text of ewallet.pem from the wallet zip, its password and the database password — stored encrypted'};
const authLabel = (k, a) => a === 'service_account' && ((k.secrets || {})[a] || []).includes('client_secret') ? 'App sign-in (client id + secret)' : (AUTH_LABEL[a] || a);   // Entra ID app (SharePoint, OneDrive)
const CONN_STATE = {connected: ['Connected', 'ok'], connected_no_offline: ['Connected (no offline access)', 'warn'], new: ['Not tested yet', ''],
  reconsent: ['Renew sign-in', 'err'], error: ['Error', 'err']};
const SCOPE_TEXT = {read: ['Read-only', 'recommended — discover, read and compare'], comment: ['Read & comment', 'also post comments or summaries (e.g. on tickets)'],
  write: ['Read & write — with approval', 'changes only after a named person approves each one']};
const SHARE_TEXT = {me: 'Only me', team: 'My teams', org: 'The whole organisation'};
const connPill = c => { if (c.allowed === false) return h('span', {class: 'tag warn', title: 'PASDACS switched this connector off for your organisation'}, 'Switched off');
  if (c.enabled === false) return h('span', {class: 'tag'}, 'Disabled'); const [t, k] = CONN_STATE[c.status] || [c.status, '']; return h('span', {class: 'tag ' + k, title: c.error || ''}, t); };
const connDot = c => h('span', {class: 'cdot ' + (c.enabled === false ? '' : c.status === 'connected' ? 'ok' : c.status === 'reconsent' || c.status === 'error' ? 'err' : c.status === 'connected_no_offline' ? 'warn' : '')});
const CH = {cat: 'all', q: ''};
S.connCache = null;

async function loadConnections() {
  const [d, kinds] = await Promise.all([api('/api/connections'), api('/api/connectors')]);
  S.connCache = {d, kinds, when: Date.now()};
  return S.connCache;
}

/* ---------- the sources other modules read through (P12 Service desk, P13 Integration analytics): the hub lists them read-only.
   Each module's own screen manages them and keeps their credentials; the hub asks each module's own API, so a person sees
   exactly the sources that module shows them (a module that is off or not theirs answers nothing, and the hub leaves it out). ---------- */
const MOD_STATE = {ok: ['Connected', 'ok'], new: ['Not read yet', ''], sign_in: ['Sign in again', 'err'], error: ['Error', 'err'], paused: ['Paused', '']};
const modPill = x => { const [t, k] = MOD_STATE[x.state] || [x.state, '']; return h('span', {class: 'tag ' + k, title: x.error || ''}, x.status_label || t); };
async function moduleSources() {
  const [sd, ia] = [null, null];          // D2D Relay: no service desk or integration analytics
  const items = [];
  if (sd) items.push(...(sd.sources || []).map(x => ({id: x.id, name: x.name, label: x.label, module: x.module || 'Service desk', link: x.link || '#/servicedesk', category: x.category || 'crm',
    state: x.paused ? 'paused' : x.status, status_label: x.status_label, error: x.error, last: x.last_read, owner: x.owner, has_secret: !!x.has_secret, scope: x.scope || 'read',
    reads: (x.projects || []).length ? x.projects.join(', ') : 'every project or queue the account can see', extra: `${fmtN(x.open_tickets || 0, 0)} open tickets`})));
  if (ia) items.push(...(ia.items || []).map(x => { const sec = Object.values(x.secrets || {});
    return {id: x.id, name: x.name, label: x.label, module: x.module || 'Integration analytics', link: x.link || '#/integrations', category: x.category || 'integration',
      state: x.status, status_label: {ok: 'Connected', new: 'Not scanned yet', error: 'Error', paused: 'Paused'}[x.status] || x.status, error: x.error, last: x.last_scan, owner: x.owner,
      has_secret: sec.length ? sec.every(Boolean) : null, scope: x.scope || 'read', reads: `scanned every ${x.every_min} min`, extra: `${fmtN(x.integrations || 0, 0)} integrations`}; }));
  return {items, modules: [sd ? 'Service desk' : null, ia ? 'Integration analytics' : null].filter(Boolean)};
}
function moduleSourceDetail(x, cats) {
  const kv = (t, v) => [h('dt', {}, t), h('dd', {}, v)];
  const cat = ((cats || []).find(c => c.id === x.category) || {}).name || '';
  const m = modal(x.name, h('div', {class: 'mbody'},
    h('div', {class: 'row', style: 'gap:8px'}, modPill(x), h('span', {class: 'chipx'}, SCOPE_TEXT[x.scope] ? SCOPE_TEXT[x.scope][0] : x.scope), h('span', {class: 'small muted'}, x.last ? `read ${ago(x.last)}` : 'not read yet')),
    x.error ? h('div', {class: 'note err', style: 'margin:8px 0 0'}, x.error) : null,
    h('dl', {class: 'kv', style: 'margin-top:12px'}, kv('System', cat ? `${x.label} · ${cat}` : x.label), kv('Read by', x.module), kv('Reads', x.reads), kv('Holds', x.extra), kv('Owner', x.owner || '—'),
      kv('Sign-in', x.has_secret == null ? 'none needed' : x.has_secret ? 'in the secrets store, never shown' : `missing — add it in ${x.module}`),
      kv('May do', (SCOPE_TEXT[x.scope] ? SCOPE_TEXT[x.scope][0] : x.scope) + (x.scope === 'read' ? '' : ' · every write waits for a named person')), kv('Audit', 'every read and write logged with who and why')),
    h('div', {class: 'note small', style: 'margin-top:10px'}, icon('lock'), ` ${x.module} manages this source and its credential; the hub only lists it.`),
    h('div', {class: 'row', style: 'justify-content:flex-end;margin-top:12px;gap:8px'}, h('button', {class: 'btn', type: 'button', onclick: () => m.remove()}, 'Close'),
      h('a', {class: 'btn primary', href: x.link, onclick: () => m.remove()}, `Open in ${x.module}`))));
  return m;
}

/* ---------- D2D Relay: every connector, and the ones PASDACS switched on for this organisation (orgs.py) ---------- */
function connectorCards(cat, onAdd) {
  return h('div', {class: 'conncat'}, cat.connectors.map(c => h('div', {class: 'card' + (c.on ? ' on' : '')},
    h('div', {class: 'row', style: 'gap:8px;align-items:center;flex-wrap:nowrap'}, icon('db'), h('b', {}, c.label), h('span', {class: 'spacer'}),
      c.on ? h('span', {class: 'tag ok'}, 'Switched on') : h('span', {class: 'tag'}, 'On request')),
    h('div', {class: 'small muted grow', style: 'margin:6px 0 10px'}, c.note),
    c.on ? (onAdd ? h('button', {class: 'btn sm', type: 'button', onclick: () => onAdd(c.kind)}, icon('plus'), 'Add a connection') : null)
      : h('button', {class: 'btn sm', type: 'button', onclick: () => connectorRequestDialog(cat, [c.kind])}, icon('send'), 'Ask PASDACS to connect it'))));
}
function connectorRequestDialog(cat, preselect = []) {
  const me = S.me || {}, o = ORG(), org = o.name || cat.org, contact = cat.contact || 'info@pasdacs.com';
  const off = cat.connectors.filter(c => !c.on);
  if (!off.length) return notify('Every connector is already switched on for your organisation.', 'ok');
  const picked = new Set(preselect.filter(k => off.some(c => c.kind === k)));
  const boxes = h('div', {class: 'stack', style: 'gap:6px'}, off.map(c => {
    const cb = h('input', {type: 'checkbox', checked: picked.has(c.kind)});
    cb.onchange = () => { if (cb.checked) picked.add(c.kind); else picked.delete(c.kind); };
    return h('label', {class: 'chk', style: 'align-items:flex-start'}, cb, h('span', {}, h('b', {}, c.label), h('small', {class: 'muted', style: 'display:block'}, c.note)));
  }));
  const msg = h('textarea', {rows: 3, placeholder: 'Which data, roughly how much, and by when (optional). For example: our sales and stock tables, about 10 million rows, for a board report next month.'});
  const names = () => off.filter(c => picked.has(c.kind)).map(c => c.label).join(', ') || 'a warehouse';
  const mailto = () => {
    const body = `Hello PASDACS,\n\nPlease connect ${names()} for our D2D Relay organisation.\n\nOrganisation: ${org}${o.domain ? ` (@${o.domain})` : ''}\n`
      + `Requested by: ${me.name || ''} <${me.email || ''}>\n` + (msg.value.trim() ? `\n${msg.value.trim()}\n` : '');
    return `mailto:${contact}?subject=${encodeURIComponent(`D2D Relay: connect ${names()} for ${org}`)}&body=${encodeURIComponent(body)}`;
  };
  const mailLink = label => h('a', {href: mailto(), onclick: e => { e.currentTarget.href = mailto(); }}, label);
  const out = h('div', {role: 'status'});
  const send = h('button', {class: 'btn primary', type: 'button'}, icon('send'), 'Send request');
  send.onclick = async () => {
    if (!picked.size) return out.replaceChildren(h('div', {class: 'note warn'}, 'Choose at least one connector.'));
    send.disabled = true;
    try {
      const r = await api('/api/org/connector-request', {json: {kinds: [...picked], message: msg.value}});
      out.replaceChildren(r.sent ? h('div', {class: 'note ok'}, `Sent to ${r.contact}. PASDACS replies to ${me.email} and switches the connector on for ${org}.`)
        : h('div', {class: 'note warn'}, 'Your request is recorded, but the email could not be sent from here. Please ', mailLink(`email ${r.contact}`), ' as well.'));
      send.lastChild.textContent = 'Sent';
    } catch (e) {
      send.disabled = false;
      out.replaceChildren(h('div', {class: 'note err'}, e.message, ' You can also ', mailLink(`email ${contact}`), '.'));
    }
  };
  modal('Ask PASDACS to connect your data', h('div', {class: 'mbody'},
    h('p', {style: 'margin-top:0'}, `D2D Relay takes CSV files on its own. PASDACS connects warehouses and databases for ${org} on request and replies by email.`),
    h('label', {class: 'f', style: 'margin-top:0'}, 'Connectors'), boxes,
    h('label', {class: 'f'}, 'Message ', h('small', {}, 'optional')), msg, out,
    h('div', {class: 'row', style: 'justify-content:flex-end;gap:12px;margin-top:12px;align-items:center;flex-wrap:wrap'},
      h('span', {class: 'small muted'}, 'or ', mailLink(`email ${contact}`)), send)));
}

/* ---------- the hub ---------- */
async function renderConnections() {
  const page = h('div', {class: 'page'});
  $('#main').replaceChildren(skel('page'));
  const qs = new URLSearchParams(location.hash.split('?')[1] || '');
  let d, kinds, mods, cat;
  try { [{d, kinds}, mods, cat] = await Promise.all([loadConnections(), moduleSources(), api('/api/org/connectors')]); }
  catch (e) { return $('#main').replaceChildren(h('div', {class: 'page'}, h('div', {class: 'note err'}, e.message))); }
  if (!location.hash.startsWith('#/connections')) return;
  $('#main').replaceChildren(page);
  const all = d.connections, cats = d.categories, ms = mods.items;
  const onKinds = cat.connectors.filter(c => c.on);
  document.title = `Connections · ${S.brand ? S.brand.full : 'D2D Relay'}`;
  if (!onKinds.length && !all.length) {          // CSV files only: what PASDACS can connect, and how to ask
    page.append(...[
      pageHead({crumbs: [['Home', '#/'], ['Connections']], eyebrow: brandName() + ' · Connections', title: 'Connections',
        promise: `Upload CSV files on New dashboard. To use a warehouse or database, PASDACS connects it for ${cat.org} on request.`,
        actions: h('a', {class: 'btn primary', href: '#/new'}, icon('file'), 'Upload CSV files')}),
      qs.get('error') ? h('div', {class: 'note err'}, qs.get('error')) : null,
      h('div', {class: 'section-title'}, h('h2', {}, 'Connectors'), h('span', {class: 'hint'}, 'switched on by PASDACS for your organisation, on request')),
      connectorCards(cat),
      h('p', {class: 'small muted', style: 'margin-top:14px'}, `Questions about your data? Write to ${cat.contact}.`)].filter(Boolean));
    return;
  }
  const byCat = Object.fromEntries(cats.map(c => [c.id, kinds.kinds ? Object.values(kinds.kinds).filter(k => k.category === c.id).length : 0]));
  const shownMods = () => ms.filter(x => (CH.cat === 'all' || x.category === CH.cat) && (!CH.q || `${x.name} ${x.label} ${x.module}`.toLowerCase().includes(CH.q.toLowerCase())));
  const attention = all.filter(c => c.status === 'reconsent' || c.status === 'error').length + ms.filter(x => x.state === 'sign_in' || x.state === 'error').length;
  const everyone = all.length + ms.length;
  const readOnly = everyone ? Math.round(100 * (all.filter(c => c.scope === 'read').length + ms.filter(x => x.scope === 'read').length) / everyone) : 100;
  const search = h('input', {type: 'text', value: CH.q, placeholder: 'Find a connection or system…', 'aria-label': 'Find a connection', oninput: () => { CH.q = search.value; drawTable(); drawMods(); }});
  const tableWrap = h('div'), modWrap = h('div'), count = h('span', {class: 'small muted'});
  const catName = id => (cats.find(x => x.id === id) || {}).name || '';
  const drawMods = () => {
    if (!mods.modules.length) return modWrap.replaceChildren();          // neither module is open to this person: nothing to list
    const rs = shownMods();
    modWrap.replaceChildren(h('div', {class: 'section-title', style: 'margin-top:18px'}, h('h2', {}, 'Read by modules'), h('span', {class: 'hint'}, `${ms.length} source${ms.length === 1 ? '' : 's'} · listed here read-only; each module manages its own`)),
      rs.length ? h('div', {class: 'card', style: 'padding:0;overflow:auto;margin:0'}, h('table', {class: 'utable ctable'},
        h('tr', {}, ['Source', 'Read by', 'May do', 'Owner', 'Last read', 'Status', ''].map(t => h('th', {class: 'l'}, t))),
        rs.map(x => h('tr', {},
          h('td', {}, h('button', {class: 'linkbtn', type: 'button', onclick: () => moduleSourceDetail(x, cats)}, h('b', {}, x.name)), h('div', {class: 'small muted'}, [x.label, catName(x.category), x.extra].filter(Boolean).join(' · '))),
          h('td', {class: 'small'}, x.module), h('td', {}, h('span', {class: 'chipx'}, SCOPE_TEXT[x.scope] ? SCOPE_TEXT[x.scope][0] : x.scope)),
          h('td', {class: 'small'}, x.owner || '—'), h('td', {class: 'small'}, x.last ? ago(x.last) : 'never'), h('td', {}, modPill(x)),
          h('td', {}, h('a', {class: 'btn sm', href: x.link, 'aria-label': `Open ${x.name} in ${x.module}`}, 'Open'))))))
        : h('div', {class: 'card empty', style: 'margin:0'}, h('h3', {}, ms.length ? 'Nothing matches' : 'No module sources yet'),
          h('div', {}, ms.length ? 'Try another category or search.' : `Sources added in ${mods.modules.join(' or ')} appear here too, with their status and owner.`)));
  };
  const drawTable = () => {
    const rs = all.filter(c => (CH.cat === 'all' || c.category === CH.cat) && (!CH.q || (c.name + ' ' + c.label).toLowerCase().includes(CH.q.toLowerCase())));
    count.textContent = `${rs.length + shownMods().length} shown`;
    tableWrap.replaceChildren(rs.length ? h('div', {class: 'card', style: 'padding:0;overflow:auto;margin:0'}, h('table', {class: 'utable ctable'},
      h('tr', {}, ['Connection', 'Sign-in', 'May do', 'Shared with', 'Used by', 'Last test', 'Status', ''].map(t => h('th', {class: 'l'}, t))),
      rs.map(c => h('tr', {},
        h('td', {}, h('button', {class: 'linkbtn', type: 'button', onclick: () => connectionDetail(c.id)}, h('b', {}, c.name)), h('div', {class: 'small muted'}, `${c.label} · ${(cats.find(x => x.id === c.category) || {}).name || c.category}${c.own ? '' : ' · ' + c.owner}`)),
        h('td', {class: 'small'}, d.signin[c.signin] || c.signin), h('td', {}, h('span', {class: 'chipx'}, SCOPE_TEXT[c.scope] ? SCOPE_TEXT[c.scope][0] : c.scope), c.limits ? h('div', {class: 'small muted'}, c.limits) : null),
        h('td', {class: 'small'}, SHARE_TEXT[c.sharing] || c.sharing), h('td', {class: 'small'}, c.used_by.length ? c.used_by.slice(0, 3).map((u, i) => [i ? ', ' : null, h('a', {href: u.link}, u.name)]) : h('span', {class: 'muted'}, 'not used yet')),
        h('td', {class: 'small'}, c.last_test ? ago(c.last_test) : '—'), h('td', {}, connPill(c)),
        h('td', {}, h('button', {class: 'btn sm', type: 'button', onclick: () => connectionDetail(c.id)}, 'Open'))))))
      : h('div', {class: 'card empty', style: 'margin:0'}, h('h3', {}, all.length ? 'Nothing matches' : 'No connections yet'),
        h('div', {}, all.length ? 'Try another category or search.' : `Connect ${onKinds.length > 2 ? 'one of the connectors below' : onKinds.map(c => c.label).join(' or ')} to build dashboards straight from your tables, read-only. CSV files are uploaded on New dashboard.`)));
  };
  drawTable(); drawMods();
  const wizard = kind => connectionWizard({kind, onDone: () => renderConnections()});
  page.append(...[
    pageHead({crumbs: [['Home', '#/'], ['Connections']], eyebrow: brandName() + ' · Connections', title: 'Connections',
      promise: 'Your warehouse and database connections: how each signs in and which dashboards use it. Read-only; CSV files are uploaded on New dashboard.',
      actions: onKinds.length ? h('button', {class: 'btn primary', type: 'button', onclick: () => wizard(null)}, icon('plus'), 'New connection') : null}),
    qs.get('error') ? h('div', {class: 'note err'}, qs.get('error')) : null,
    qs.get('connected') ? h('div', {class: 'note ok'}, 'Signed in. Choose the tables Relay may use.') : null,
    h('div', {class: 'g5', style: 'margin-bottom:16px'},
      kpiTile('Connections', String(all.length), `${cats.length} categories · ${Object.keys(kinds.kinds || {}).length} systems available` + (ms.length ? ` · ${ms.length} more read by modules` : '')),
      kpiTile('Need attention', String(attention), attention ? 'sign-ins to renew or errors' : 'every sign-in works'),
      kpiTile('Read-only', `${readOnly} %`, 'writes always need a per-change approval'),
      kpiTile('Shared', String(all.filter(c => c.sharing !== 'me').length), 'with a team or the organisation'),
      kpiTile('In use', String(all.filter(c => c.used_by.length).length + ms.length), ms.length ? 'by dashboards, starts and modules' : 'by dashboards and starts')),
    h('div', {class: 'ccats'}, cats.map(c => h('button', {class: 'card ccat' + (CH.cat === c.id ? ' on' : ''), type: 'button', 'aria-pressed': String(CH.cat === c.id), onclick: () => { CH.cat = CH.cat === c.id ? 'all' : c.id; renderConnections(); }},
      h('b', {}, c.name), h('small', {}, `${all.filter(x => x.category === c.id).length + ms.filter(x => x.category === c.id).length} connected · ${byCat[c.id] || 0} available`)))),
    h('div', {class: 'toolbar'}, search, CH.cat !== 'all' ? h('button', {class: 'btn sm', type: 'button', onclick: () => { CH.cat = 'all'; renderConnections(); }}, 'All categories') : null,
      h('span', {class: 'spacer'}), count),
    tableWrap, modWrap,
    h('div', {class: 'section-title', style: 'margin-top:22px'}, h('h2', {}, 'Connectors'),
      h('span', {class: 'hint'}, `${onKinds.length} of ${cat.connectors.length} switched on for ${cat.org} · PASDACS switches the others on, on request`)),
    connectorCards(cat, wizard),
    h('p', {class: 'small muted', style: 'margin-top:14px'}, 'Secrets live in the secrets store by name and are never shown again; every use is audited with who and why.')].filter(Boolean));
}

/* ---------- one connection: the detail dialog with every action ---------- */
async function connectionDetail(cid) {
  const {d, kinds} = S.connCache || await loadConnections();
  const c = d.connections.find(x => x.id === cid);
  if (!c) return notify('That connection is gone.', 'err');
  const k = kinds.kinds[c.kind], me = S.me || {}, canManage = c.own || me.admin;
  const body = h('div', {class: 'mbody'});
  const act = async (fn, okMsg) => { try { const r = await fn(); if (okMsg) notify(okMsg, 'ok'); S.connCache = null; m.remove(); if (location.hash.startsWith('#/connections')) renderConnections(); return r; } catch (e) { notify(e.message, 'err'); } };
  const kv = (t, v) => [h('dt', {}, t), h('dd', {}, v)];
  const scopeDialog = () => {
    let scope = c.scope; const lim = h('input', {type: 'text', value: c.limits || '', placeholder: 'e.g. company codes 1000, 2000 · folders · projects · schemas'});
    const opts = h('div', {class: 'stack', style: 'gap:6px'}, Object.entries(SCOPE_TEXT).map(([kk, [t, s]]) => { const r = h('input', {type: 'radio', name: 'scope', checked: kk === scope}); r.onchange = () => { scope = kk; [...opts.children].forEach((el, i) => el.classList.toggle('on', Object.keys(SCOPE_TEXT)[i] === kk)); };
      return h('label', {class: 'radio' + (kk === scope ? ' on' : '')}, r, h('span', {}, h('b', {}, t), h('small', {}, s))); }));
    const mm = modal(`What may Relay do in ${c.name}?`, h('div', {class: 'mbody'}, opts, h('label', {class: 'f'}, 'Limit to', h('small', {}, 'optional')), lim,
      h('div', {class: 'hint'}, 'Even with write access, every change waits for a named person in the Validation queue.'),
      h('div', {class: 'row', style: 'justify-content:flex-end;margin-top:12px'}, h('button', {class: 'btn', onclick: () => mm.remove()}, 'Cancel'),
        h('button', {class: 'btn primary', onclick: () => { mm.remove(); act(() => api(`/api/connections/${c.id}/scope`, {method: 'PUT', json: {scope, limits: lim.value}}), 'Scope saved'); }}, 'Save'))));
  };
  const shareDialog = () => {
    const sel = h('select', {class: 'sel'}, Object.entries(SHARE_TEXT).map(([kk, t]) => h('option', {value: kk, selected: kk === c.sharing}, t)));
    const mm = modal(`Share ${c.name}`, h('div', {class: 'mbody'}, h('label', {class: 'f', style: 'margin-top:0'}, 'Who may use it'), sel,
      h('div', {class: 'hint'}, 'Shared connections run with your stored sign-in; every use is audited with who asked. Only you can change or remove it.'),
      h('div', {class: 'row', style: 'justify-content:flex-end;margin-top:12px'}, h('button', {class: 'btn', onclick: () => mm.remove()}, 'Cancel'),
        h('button', {class: 'btn primary', onclick: () => { mm.remove(); act(() => api(`/api/connections/${c.id}/sharing`, {method: 'PUT', json: {sharing: sel.value}}), 'Sharing saved'); }}, 'Save'))));
  };
  const renew = async () => {
    if (c.auth_mode === 'oauth') { location.href = `/api/connections/${c.id}/oauth/start`; return; }
    const names = k.secrets[c.auth_mode] || []; const vals = {};
    const inputs = names.map(n => { const el = h('input', {type: 'password', autocomplete: 'off', placeholder: 'new ' + n.replace(/_/g, ' ')}); el.oninput = () => { vals[n] = el.value; }; return h('div', {}, h('label', {class: 'f'}, n.replace(/_/g, ' ')), el); });
    const mm = modal(`Renew ${c.name}`, h('div', {class: 'mbody'}, h('div', {class: 'small muted'}, 'Enter the new key or password; the old one is replaced in the secrets store and the connection is tested again.'), inputs,
      h('div', {class: 'row', style: 'justify-content:flex-end;margin-top:12px'}, h('button', {class: 'btn', onclick: () => mm.remove()}, 'Cancel'),
        h('button', {class: 'btn primary', onclick: async () => { mm.remove(); const r = await act(() => api(`/api/connections/${c.id}/renew`, {json: {secrets: vals}}), 'Renewed'); if (r) api(`/api/connections/${c.id}/test`, {method: 'POST'}).then(() => notify('Connection works', 'ok')).catch(e => notify(e.message, 'err')); }}, 'Renew'))));
  };
  const readDialog = async () => {
    const list = h('div', {class: 'stack', style: 'gap:4px;max-height:40vh;overflow:auto'}, h('div', {class: 'muted small'}, 'Loading what this sign-in can see…'));
    const out = h('div', {style: 'margin-top:10px'});
    const mm = modal(`Read from ${c.name}`, h('div', {class: 'mbody'}, h('div', {class: 'note small'}, icon('shield'), ' Read-only: one object at a time, audited.'), list, out), true);
    try {
      const r = await api(`/api/connections/${c.id}/browse?q=`);
      list.replaceChildren(...(r.tables.length ? r.tables.map(t => h('button', {class: 'btn sm', type: 'button', onclick: async () => { out.replaceChildren(h('div', {class: 'muted small'}, 'Reading…'));
        try { const x = await api(`/api/connections/${c.id}/read`, {json: {object: t.object, limit: 50}});
          out.replaceChildren(h('div', {class: 'muted small'}, `${(x.row_count || 0).toLocaleString()} row(s)`), h('div', {class: 'dprev'}, h('table', {}, h('tr', {}, x.columns.map(col => h('th', {}, col))), x.rows.slice(0, 50).map(row => h('tr', {}, x.columns.map(col => h('td', {}, row[col] == null ? '' : String(row[col])))))))); }
        catch (e) { out.replaceChildren(h('div', {class: 'note err'}, e.message)); } }}, h('span', {class: 'mono'}, t.object), t.type ? h('span', {class: 'tag'}, t.type) : null)) : [h('div', {class: 'muted small'}, 'Nothing to read.')]));
    } catch (e) { list.replaceChildren(h('div', {class: 'note err'}, e.message)); }
    return mm;
  };
  body.append(...[                                  // native append renders a null as the text "null": filtered below
    c.allowed === false ? h('div', {class: 'note warn', style: 'margin-top:0'}, `PASDACS has switched ${c.label} off for your organisation, so this connection cannot be tested, queried or pulled from. You can still share, disable or remove it.`) : null,
    h('div', {class: 'row', style: 'gap:8px'}, connPill(c), h('span', {class: 'chipx'}, SCOPE_TEXT[c.scope] ? SCOPE_TEXT[c.scope][0] : c.scope), h('span', {class: 'small muted'}, c.last_test ? `tested ${ago(c.last_test)}` : 'never tested')),
    c.error ? h('div', {class: 'note ' + (c.status === 'connected_no_offline' ? 'warn' : 'err'), style: 'margin:8px 0 0'}, c.error) : null,
    h('dl', {class: 'kv', style: 'margin-top:12px'}, kv('System', `${c.label} · ${(d.categories.find(x => x.id === c.category) || {}).name || ''}`), kv('Sign-in', d.signin[c.signin] || c.signin),
      kv('May do', (SCOPE_TEXT[c.scope] ? SCOPE_TEXT[c.scope][0] : c.scope) + (c.limits ? ` · limited to ${c.limits}` : '')), kv('Owner', c.owner), kv('Shared with', SHARE_TEXT[c.sharing] || c.sharing),
      kv('Used by', c.used_by.length ? h('span', {}, c.used_by.map((u, i) => [i ? ', ' : null, h('a', {href: u.link}, `${u.name} (${u.module})`)])) : '—'),
      kv('Settings', Object.entries(c.config).filter(([, v]) => v).map(([kk, v]) => `${kk}: ${v}`).join(' · ') || '—'),
      kv('Secrets', 'in the secrets store, never shown'), kv('Audit', 'every use logged with who and why')),
    c.tables && (c.sql || c.extract) ? h('div', {style: 'margin-top:10px'}, h('b', {class: 'small'}, `Configured ${c.sql ? 'tables' : 'objects'} (${c.tables.length})`),
      c.tables.length ? h('div', {class: 'chips', style: 'margin-top:6px'}, c.tables.map(t => h('span', {class: 'tag'}, t.object, t.rows != null ? ` · ${t.rows.toLocaleString()} rows` : '')))
        : h('div', {class: 'muted small'}, c.sql ? 'None yet — dashboards and Ask Relay can only use the tables chosen here.' : 'None yet — dashboards can only pull the objects chosen here.')) : null,
    h('div', {class: 'row', style: 'margin-top:14px;gap:6px'},
      h('button', {class: 'btn', type: 'button', disabled: c.enabled === false, onclick: () => act(() => api(`/api/connections/${c.id}/test`, {method: 'POST'}), 'Connection works')}, 'Test now'),
      c.own ? h('button', {class: 'btn' + (c.status === 'reconsent' ? ' primary' : ''), type: 'button', onclick: renew}, c.auth_mode === 'oauth' && c.status === 'new' ? 'Sign in' : 'Renew sign-in') : null,
      (c.sql || c.extract) && c.own ? h('button', {class: 'btn', type: 'button', onclick: () => { m.remove(); tablesDialog(c); }}, c.sql ? 'Choose tables' : 'Choose objects') : null,
      c.sql ? h('button', {class: 'btn', type: 'button', disabled: c.enabled === false, onclick: () => { m.remove(); queryDialog(c, kinds.guardrails); }}, 'Query') : h('button', {class: 'btn', type: 'button', disabled: c.enabled === false, onclick: readDialog}, 'Read'),
      c.own ? h('button', {class: 'btn', type: 'button', onclick: scopeDialog}, 'Scope') : null,
      canManage ? h('button', {class: 'btn', type: 'button', onclick: shareDialog}, 'Sharing') : null,
      c.own ? h('button', {class: 'btn ghost', type: 'button', onclick: () => { m.remove(); connectionDialog(c, kinds.kinds); }}, 'Edit') : null,
      canManage ? h('button', {class: 'btn ghost' + (c.enabled === false ? '' : ' danger'), type: 'button', onclick: async () => {
        if (c.enabled === false) return act(() => api(`/api/connections/${c.id}/enable`, {method: 'POST'}), 'Enabled');
        const stops = c.used_by.length ? ` Stops working: ${c.used_by.map(u => u.name).join(', ')}.` : ' Nothing uses it yet.';
        if (await confirmBox(`Disable ${c.name}?`, `Nothing can use it until it is enabled again.${stops}`, 'Disable')) act(() => api(`/api/connections/${c.id}/disable`, {method: 'POST'}), 'Disabled'); }}, c.enabled === false ? 'Enable' : 'Disable') : null,
      canManage ? h('button', {class: 'btn ghost danger', type: 'button', onclick: async () => { if (await confirmBox(`Remove ${c.name}?`, 'Its stored credentials are deleted. Dashboards keep their extracts but cannot refresh them.')) act(() => api(`/api/connections/${c.id}`, {method: 'DELETE'}), 'Removed'); }}, 'Remove') : null)].filter(Boolean));
  const m = modal(c.name, body);
}

/* ---------- the new-connection wizard: system → sign-in → scope → test & share (reused by Start and the module pages) ---------- */
async function connectionWizard({suggest = [], kind = null, onDone = null} = {}) {
  let kinds;
  try { kinds = (await api('/api/connectors')); } catch (e) { return notify(e.message, 'err'); }
  const K = kinds.kinds, cats = kinds.categories;
  const sugg = (suggest || []).map(s => String(s).toLowerCase());
  const match = k => sugg.some(s => k.label.toLowerCase().includes(s.split(' ')[0]) || s.includes(k.label.toLowerCase()));
  const firstKind = kind && K[kind] ? kind : (Object.keys(K).find(id => match(K[id])) || null);
  const W = {step: 1, cat: firstKind ? K[firstKind].category : (cats[0] || {}).id, kind: firstKind, name: '', auth: null, config: {}, secrets: {}, scope: 'read', limits: '', sharing: 'me', saved: null, tested: null, testing: false};
  const body = h('div', {class: 'mbody'}), foot = h('div', {class: 'row', style: 'justify-content:flex-end;gap:8px;padding:0 18px 16px'});
  const steps = ['System', 'Sign-in', 'Scope', 'Test & share'];
  const fieldsOk = () => { const k = K[W.kind]; if (!k) return false; const a = W.auth; return k.fields.every(f => !f.required || (a === 'oauth' && f.key === 'user') || (W.config[f.key] || '').trim()) && (k.secrets[a] || []).every(n => !!W.secrets[n] || a === 'oauth'); };
  const draw = () => {
    const k = K[W.kind];
    if (k && (!W.auth || !k.auth.includes(W.auth))) W.auth = k.auth.find(a => a !== 'oauth' || k.oauth_ready) || k.auth[0];
    body.replaceChildren(h('div', {class: 'wsteps'}, steps.map((s, i) => h('span', {class: 'pill plain ' + (i + 1 < W.step ? 'ok' : i + 1 === W.step ? 'info' : 'mute')}, `${i + 1} ${s}`))));
    if (W.step === 1) {
      const list = Object.entries(K).filter(([, v]) => v.category === W.cat);
      body.append(...[h('div', {class: 'row', style: 'gap:6px'}, cats.map(c => h('button', {class: 'btn sm' + (W.cat === c.id ? ' primary' : ''), type: 'button', onclick: () => { W.cat = c.id; draw(); }}, c.name))),
        h('div', {class: 'wgrid'}, list.length ? list.map(([id, v]) => h('button', {class: 'wopt' + (W.kind === id ? ' on' : ''), type: 'button', onclick: () => { W.kind = id; W.name = W.name || v.label; W.auth = null; draw(); }}, h('b', {}, v.label), h('small', {}, v.signin.map(s => (kinds.signin[s] || s).split(' (')[0].split(' — ')[0]).join(' · '))))
          : [h('div', {class: 'muted small'}, 'No connector in this category yet — platforms are added as connectors (one adapter + one mock) and reused by every client. Use REST API (OpenAPI) under Integration & automation for anything with a documented API.')]),
        sugg.length ? h('div', {class: 'hint'}, `Suggested for this work: ${suggest.join(', ')}.`) : null].filter(Boolean));   // append renders a null as the text "null"
    } else if (W.step === 2) {
      const nameIn = h('input', {type: 'text', value: W.name, placeholder: `${k.label} · production`}); nameIn.oninput = () => { W.name = nameIn.value; };
      const authSel = h('div', {class: 'stack', style: 'gap:6px'}, k.auth.map(a => { const r = h('input', {type: 'radio', name: 'wauth', checked: a === W.auth, disabled: a === 'oauth' && !k.oauth_ready}); r.onchange = () => { W.auth = a; draw(); };
        return h('label', {class: 'radio' + (a === W.auth ? ' on' : '')}, r, h('span', {}, h('b', {}, authLabel(k, a)), h('small', {}, a === 'oauth' ? (k.oauth_ready ? 'uses your own access, so nobody sees more than they could already' : 'not set up by your admin yet') : AUTH_HINT[a] || (a === 'service_account' || a === 'api_key' || a === 'aws_keys' || a === 'keypair' ? 'stored encrypted in the secrets store — never shown again' : 'stored encrypted; prefer a read-only role')))); }));
      body.append(h('label', {class: 'f', style: 'margin-top:0'}, 'Connection name'), nameIn, h('label', {class: 'f'}, `How Relay signs in to ${k.label}`), authSel,
        ...k.fields.filter(f => !(W.auth === 'oauth' && f.key === 'user')).map(f => { const el = h('input', {type: 'text', value: W.config[f.key] || ''}); el.oninput = () => { W.config[f.key] = el.value; drawFoot(); }; return h('div', {}, h('label', {class: 'f'}, f.label, f.required ? null : h('small', {}, 'optional')), el); }),
        ...(k.secrets[W.auth] || []).map(n => { const el = bigSecret(n) ? h('textarea', {rows: 4, placeholder: n.replace(/_/g, ' ')}) : h('input', {type: 'password', autocomplete: 'off', placeholder: n.replace(/_/g, ' ')}); el.oninput = () => { W.secrets[n] = el.value; drawFoot(); }; return h('div', {}, h('label', {class: 'f'}, n.replace(/_/g, ' ')), el); }));
    } else if (W.step === 3) {
      const opts = h('div', {class: 'stack', style: 'gap:6px'}, Object.entries(SCOPE_TEXT).map(([kk, [t, s]]) => { const r = h('input', {type: 'radio', name: 'wscope', checked: kk === W.scope, disabled: kk === 'write' && !k.can_write}); r.onchange = () => { W.scope = kk; draw(); };
        return h('label', {class: 'radio' + (kk === W.scope ? ' on' : '')}, r, h('span', {}, h('b', {}, t), h('small', {}, kk === 'write' && !k.can_write ? `${k.label} connections are read-only in Relay` : s))); }));
      const lim = h('input', {type: 'text', value: W.limits, placeholder: 'e.g. company codes 1000, 2000 · folders · projects · schemas'}); lim.oninput = () => { W.limits = lim.value; };
      body.append(h('label', {class: 'f', style: 'margin-top:0'}, `What may Relay do in ${k.label}?`), opts, h('label', {class: 'f'}, 'Limit to', h('small', {}, 'optional')), lim,
        h('div', {class: 'hint'}, 'Read-only is the default everywhere. Even with write access, every change waits for a named person in the Validation queue.'));
    } else {
      const res = W.testing ? h('div', {class: 'row'}, h('span', {class: 'spin'}), 'Testing the connection…')
        : W.tested && W.tested.ok ? h('dl', {class: 'kv'}, ...[['Result', 'Connected ✓'], ['System', k.label], ['Signed in', authLabel(k, W.auth)], ['Can see', W.tested.sees || 'what this sign-in allows'], ['Scope', SCOPE_TEXT[W.scope][0]]].flatMap(([t, v]) => [h('dt', {}, t), h('dd', {}, v)]))
        : W.tested ? h('div', {class: 'note err'}, W.tested.error) : h('div', {class: 'small muted'}, W.auth === 'oauth' ? 'Save, then sign in at the system: Relay keeps a refresh token (offline access) so scheduled work keeps running.' : 'Test before saving — Relay shows what this sign-in can actually see.');
      const share = h('select', {class: 'sel'}, Object.entries(SHARE_TEXT).map(([kk, t]) => h('option', {value: kk, selected: kk === W.sharing}, t))); share.onchange = () => { W.sharing = share.value; };
      body.append(h('div', {class: 'card flat', style: 'margin:0;background:var(--surface-2)'}, res), h('label', {class: 'f'}, 'Share with'), share,
        h('div', {class: 'hint'}, 'Single sign-on and OAuth use each person’s own access; a shared key or service account runs with yours, audited per use.'));
    }
    drawFoot();
  };
  const save = async () => {
    const k = K[W.kind];
    try {
      const r = await api(W.saved ? `/api/connections/${W.saved.id}` : '/api/connections', {method: W.saved ? 'PATCH' : 'POST', json: {kind: W.kind, name: W.name || k.label, auth_mode: W.auth, config: W.config, secrets: W.secrets, scope: W.scope, limits: W.limits, sharing: W.sharing}});
      W.saved = r; W.secrets = {}; return r;
    } catch (e) { notify(e.message, 'err'); return null; }
  };
  const drawFoot = () => {
    foot.replaceChildren(
      W.step > 1 ? h('button', {class: 'btn', type: 'button', onclick: () => { W.step--; draw(); }}, 'Back') : h('button', {class: 'btn', type: 'button', onclick: () => m.remove()}, 'Cancel'),
      W.step < 4 ? h('button', {class: 'btn primary', type: 'button', disabled: W.step === 1 ? !W.kind : W.step === 2 ? !fieldsOk() : false, onclick: () => { W.step++; draw(); }}, 'Next')
        : W.auth === 'oauth' ? h('button', {class: 'btn primary', type: 'button', onclick: async () => { const r = await save(); if (r) { S.connCache = null; location.href = `/api/connections/${r.id}/oauth/start`; } }}, 'Save and sign in')
        : !(W.tested && W.tested.ok) ? h('button', {class: 'btn primary', type: 'button', disabled: W.testing, onclick: async () => { W.testing = true; draw(); const r = await save(); if (!r) { W.testing = false; draw(); return; }
            try { const t = await api(`/api/connections/${r.id}/test`, {method: 'POST'}); W.tested = {ok: true, sees: t.sees}; } catch (e) { W.tested = {ok: false, error: e.message}; } W.testing = false; draw(); }}, 'Test connection')
        : h('button', {class: 'btn primary', type: 'button', onclick: async () => { const r = await api(`/api/connections/${W.saved.id}/sharing`, {method: 'PUT', json: {sharing: W.sharing}}).catch(e => { notify(e.message, 'err'); return null; }); if (!r) return;
            S.connCache = null; m.remove(); notify('Connection saved — available everywhere in Relay', 'ok'); if (onDone) onDone(r); }}, 'Save connection'));
  };
  const m = modal('New connection', h('div', {}, body, foot), true);
  draw();
  return m;
}

/* ---------- the picker: choose saved connections, or create one, from any screen (Start, module pages) ---------- */
function connPicker(selected, {suggest = [], compact = false, onchange = null} = {}) {
  const box = h('div', {class: 'stack', style: 'gap:8px'}, h('div', {class: 'muted small'}, 'Loading your connections…'));
  const sugg = (suggest || []).map(s => String(s).toLowerCase());
  const rank = c => sugg.some(s => (c.label + ' ' + c.name).toLowerCase().includes(s.split(' ')[0])) ? 0 : 1;
  let list = [];
  const draw = () => {
    const shown = [...list].filter(c => c.enabled !== false).sort((a, b) => rank(a) - rank(b)).slice(0, compact ? 4 : 10);
    box.replaceChildren(
      shown.length ? h('div', {class: 'row', style: 'gap:6px'}, shown.map(c => { const cb = h('input', {type: 'checkbox', checked: selected.has(c.id)}); cb.onchange = () => { cb.checked ? selected.add(c.id) : selected.delete(c.id); count.textContent = selected.size ? `${selected.size} selected` : 'none selected — attachments only'; if (onchange) onchange(); };
        return h('label', {class: 'chk', title: `${c.label} · ${SCOPE_TEXT[c.scope] ? SCOPE_TEXT[c.scope][0] : c.scope}`}, cb, connDot(c), c.name); })) : h('div', {class: 'muted small'}, 'No connections yet.'),
      h('div', {class: 'row', style: 'gap:8px'}, h('button', {class: 'btn sm', type: 'button', onclick: () => connectionWizard({suggest, onDone: c => { selected.add(c.id); refresh(); if (onchange) onchange(); }})}, icon('plus'), 'New connection'),
        h('a', {class: 'small', href: '#/connections'}, 'Manage all connections →'), count));
  };
  const count = h('span', {class: 'small muted'}, selected.size ? `${selected.size} selected` : 'none selected — attachments only');
  const refresh = () => api('/api/connections').then(r => { list = r.connections; draw(); }).catch(e => box.replaceChildren(h('div', {class: 'note err'}, e.message)));
  refresh();
  return box;
}

/* ---------- the Connections card on a module page: connections that match the module's platforms, and the wizard ---------- */
function connectionsCard(m) {
  const card = h('div', {class: 'card', style: 'margin:0'}, h('h3', {}, 'Connections'), h('div', {class: 'muted small'}, 'Loading…'));
  const plats = (m.platforms || []).map(p => p.toLowerCase());
  api('/api/connections').then(r => {
    const mine = r.connections.filter(c => plats.some(p => p.includes(c.label.toLowerCase().split(' ')[0]) || c.label.toLowerCase().includes(p.split(' ')[0])) || (c.used_by || []).some(u => u.module === m.name));
    const shown = mine.length ? mine : r.connections.slice(0, 3);
    card.replaceChildren(...[h('h3', {}, 'Connections'),              // replaceChildren renders a null as the text "null": filter it out
      h('div', {class: 'small muted', style: 'margin:-4px 0 8px'}, mine.length ? `${mine.length} match${mine.length === 1 ? 'es' : ''} this module’s platforms.` : r.connections.length ? 'None match this module’s platforms yet.' : 'Nothing connected yet — read-only by default.'),
      shown.length ? h('div', {class: 'stack', style: 'gap:6px'}, shown.map(c => h('button', {class: 'linkbtn', type: 'button', style: 'text-align:left', onclick: () => connectionDetail(c.id)}, connDot(c), h('b', {}, c.name), h('span', {class: 'small muted'}, ` · ${c.label} · ${SCOPE_TEXT[c.scope] ? SCOPE_TEXT[c.scope][0] : c.scope}`)))) : null,
      h('div', {class: 'row', style: 'margin-top:10px;gap:8px'}, h('button', {class: 'btn sm', type: 'button', onclick: () => connectionWizard({suggest: m.platforms, onDone: () => renderModule(m.id, m.work_type)})}, icon('plus'), 'New connection'), h('a', {class: 'small', href: '#/connections'}, 'All connections →'))].filter(Boolean));
  }).catch(e => card.replaceChildren(h('h3', {}, 'Connections'), h('div', {class: 'note err'}, e.message)));
  return card;
}

/* ---------- edit (settings and secrets of an existing connection; new ones go through the wizard) ---------- */
function connectionDialog(c, kinds) {
  let kind = c ? c.kind : Object.keys(kinds)[0];
  const body = h('div', {class: 'mbody'});
  const vals = {...(c ? c.config : {})}, sec = {};
  let auth = c ? c.auth_mode : null, name = c ? c.name : '';
  const draw = () => {
    const k = kinds[kind];
    if (!auth || !k.auth.includes(auth)) auth = k.auth.find(a => a !== 'oauth' || k.oauth_ready) || k.auth[0];
    const kindSel = h('select', {class: 'sel', disabled: !!c}, Object.entries(kinds).map(([id, v]) => h('option', {value: id, selected: id === kind}, v.label)));
    kindSel.onchange = () => { kind = kindSel.value; auth = null; draw(); };
    const authSel = h('select', {class: 'sel'}, k.auth.map(a => h('option', {value: a, selected: a === auth, disabled: a === 'oauth' && !k.oauth_ready},
      authLabel(k, a) + (a === 'oauth' && !k.oauth_ready ? ' — not set up by your admin yet' : ''))));
    authSel.onchange = () => { auth = authSel.value; draw(); };
    const nameIn = h('input', {type: 'text', value: name, placeholder: `${k.label} · production`}); nameIn.oninput = () => { name = nameIn.value; };
    body.replaceChildren(...[
      h('label', {class: 'f', style: 'margin-top:0'}, 'System'), kindSel,
      h('label', {class: 'f'}, 'Name'), nameIn,
      h('label', {class: 'f'}, 'How you sign in'), authSel,
      ...k.fields.filter(f => !(auth === 'oauth' && f.key === 'user')).map(f => { const el = h('input', {type: 'text', value: vals[f.key] || ''}); el.oninput = () => { vals[f.key] = el.value; };
        return h('div', {}, h('label', {class: 'f'}, f.label, f.required ? null : h('small', {}, 'optional')), el); }),
      ...(k.secrets[auth] || []).map(n => { const has = c && c.has_secret && c.has_secret[n];
        const el = bigSecret(n) ? h('textarea', {rows: 4, placeholder: has ? 'Stored — leave empty to keep' : n.replace(/_/g, ' ')})
          : h('input', {type: 'password', autocomplete: 'off', placeholder: has ? 'Stored — leave empty to keep' : n.replace(/_/g, ' ')});
        el.oninput = () => { sec[n] = el.value; }; return h('div', {}, h('label', {class: 'f'}, n.replace(/_/g, ' ')), el); }),
      h('div', {class: 'note small'}, icon('lock'), auth === 'oauth' ? ' After saving, press Sign in: you sign in at the system and Relay keeps a refresh token (offline access) so scheduled refreshes work.'
        : ' Stored encrypted and used only for queries and extracts through Relay. Prefer a read-only role.'),
      h('div', {class: 'row', style: 'justify-content:flex-end;margin-top:12px'}, h('button', {class: 'btn', onclick: () => m.remove()}, 'Cancel'),
        h('button', {class: 'btn primary', onclick: async () => {
          try {
            const r = await api(c ? `/api/connections/${c.id}` : '/api/connections', {method: c ? 'PATCH' : 'POST', json: {kind, name, auth_mode: auth, config: vals, secrets: sec}});
            m.remove(); S.connCache = null;
            if (auth === 'oauth' && (!c || r.status === 'new')) location.href = `/api/connections/${r.id}/oauth/start`;
            else { notify('Saved — testing…'); await api(`/api/connections/${r.id}/test`, {method: 'POST'}).then(() => notify('Connection works', 'ok')).catch(e => notify(e.message, 'err')); if (location.hash.startsWith('#/connections')) renderConnections(); }
          } catch (e) { notify(e.message, 'err'); }
        }}, auth === 'oauth' ? 'Save and sign in' : 'Save and test'))]);
  };
  draw();
  const m = modal(c ? `Edit ${c.name}` : 'Add a connection', body);
}

async function tablesDialog(c) {
  const picked = new Set(c.tables.map(t => t.object));
  const q = h('input', {type: 'text', placeholder: c.sql ? 'Find tables and views…' : 'Find objects…'});
  const list = h('div', {class: 'stack', style: 'gap:4px;max-height:50vh;overflow:auto;margin-top:8px'}, h('div', {class: 'muted small'}, 'Loading what your login can see…'));
  const count = h('b', {}, '');
  const showCount = () => { count.textContent = `${picked.size} chosen`; };
  let timer;
  const load = async () => {
    try {
      const r = await api(`/api/connections/${c.id}/browse?q=${encodeURIComponent(q.value)}`);
      list.replaceChildren(...(r.tables.length ? r.tables.map(t => { const cb = h('input', {type: 'checkbox', checked: picked.has(t.object)});
        cb.onchange = () => { cb.checked ? picked.add(t.object) : picked.delete(t.object); showCount(); };
        return h('label', {class: 'chk'}, cb, h('span', {class: 'mono'}, t.object), h('span', {class: 'tag'}, t.type || '')); })
        : [h('div', {class: 'muted small'}, 'Nothing matches.')]));
    } catch (e) { list.replaceChildren(h('div', {class: 'note err'}, e.message)); }
  };
  q.oninput = () => { clearTimeout(timer); timer = setTimeout(load, 300); };
  showCount();
  const m = modal(`${c.sql ? 'Tables' : 'Objects'} Relay may use · ${c.name}`, h('div', {class: 'mbody'},
    h('div', {class: 'muted small'}, c.sql ? 'Only these tables can be pulled into dashboards and asked about. Your login in the warehouse decides what you can see.'
      : `Only these objects can be pulled into dashboards — every record, read-only, with this connection's sign-in. ${c.native === false ? `${c.label} has no Power BI connector: the Power BI file reads the pulled files.` : ''}`),
    h('div', {style: 'margin-top:10px'}, q), list,
    h('div', {class: 'row', style: 'margin-top:12px'}, count, h('span', {class: 'spacer'}), h('button', {class: 'btn', onclick: () => m.remove()}, 'Cancel'),
      h('button', {class: 'btn primary', onclick: async () => { try { await api(`/api/connections/${c.id}/tables`, {method: 'PUT', json: {objects: [...picked]}});
        notify('Tables saved', 'ok'); m.remove(); S.connCache = null; if (location.hash.startsWith('#/connections')) renderConnections(); } catch (e) { notify(e.message, 'err'); } }}, 'Save'))));
  load();
}

function queryDialog(c, g) {
  const sql = h('textarea', {rows: 6, class: 'mono', placeholder: c.tables[0] ? `SELECT * FROM ${c.tables[0].object}` : 'SELECT …'});
  const out = h('div', {style: 'margin-top:10px'});
  const run = h('button', {class: 'btn primary', onclick: async () => {
    run.disabled = true; out.replaceChildren(h('div', {class: 'muted small'}, 'Running…'));
    try {
      const r = await api(`/api/connections/${c.id}/query`, {json: {sql: sql.value}});
      out.replaceChildren(h('div', {class: 'muted small'}, `${r.row_count.toLocaleString()} row(s) in ${r.seconds}s` + (r.limited ? ` — stopped at the ${r.guardrails.row_limit.toLocaleString()}-row limit` : '')
        + (r.bytes_estimate != null ? ` · dry run ${(r.bytes_estimate / 1e6).toFixed(1)} MB` : '')),
        h('details', {class: 'more'}, h('summary', {}, 'SQL as sent'), h('pre', {class: 'mono small'}, r.sql)),
        h('div', {class: 'dprev'}, h('table', {}, h('tr', {}, r.columns.map(col => h('th', {}, col))),
          r.rows.slice(0, 200).map(row => h('tr', {}, r.columns.map(col => h('td', {}, row[col] == null ? '' : String(row[col]))))))));
    } catch (e) { out.replaceChildren(h('div', {class: 'note err'}, e.message)); }
    run.disabled = false;
  }}, icon('play'), 'Run');
  modal(`Query · ${c.name}`, h('div', {class: 'mbody'},
    h('div', {class: 'note small'}, icon('shield'), ` Read-only: one SELECT, at most ${g.row_limit.toLocaleString()} rows, ${g.timeout_s}s` + (c.kind === 'bigquery' ? `, ${g.bigquery_max_gb} GB scanned (checked with a dry run first)` : '') + '. Ask D uses the same engine.'),
    sql, h('div', {class: 'row', style: 'margin-top:8px'}, run), out), true);
}

/* a dashboard's warehouse data (Details tab) */
function warehouseCard(st) {
  const card = h('div', {class: 'card'}, h('h3', {}, 'Warehouse data'), skel('rows'));
  api(`/api/projects/${st.id}/extracts`).then(d => {
    const sched = h('select', {class: 'sel', style: 'max-width:240px', disabled: !d.can_refresh}, h('option', {value: '', selected: !d.schedule.daily}, 'Refresh by hand'),
      ...[...Array(24).keys()].map(hh => h('option', {value: hh, selected: d.schedule.daily && d.schedule.hour_utc === hh}, `Every day at ${String(hh).padStart(2, '0')}:00 UTC`)));
    sched.onchange = async () => { try { await api(`/api/projects/${st.id}/extracts/schedule`, {method: 'PUT', json: {daily: sched.value !== '', hour_utc: +(sched.value || 5)}}); notify('Schedule saved', 'ok'); } catch (e) { notify(e.message, 'err'); } };
    const btn = h('button', {class: 'btn', disabled: !d.can_refresh, onclick: async () => { btn.disabled = true; notify('Pulling the tables again…');
      try { await api(`/api/projects/${st.id}/extracts/refresh`, {method: 'POST'}); notify('Warehouse data refreshed', 'ok'); S.key = null; poll(); } catch (e) { notify(e.message, 'err'); btn.disabled = false; } }}, icon('download'), 'Refresh now');
    card.replaceChildren(...[h('h3', {}, 'Warehouse data'),
      h('div', {class: 'muted small', style: 'margin:-6px 0 8px'}, `From ${(st.warehouse || {}).name || 'a warehouse'} — pulled into the project as Parquet for the prototype and the checks; `
        + (d.extracts.every(e => e.native !== false) ? 'the Power BI file refreshes from the warehouse itself.' : 'this source has no Power BI connector, so the Power BI file reads these files: refresh them here or on a schedule.')),
      h('table', {class: 'utable'}, h('tr', {}, ['Table', 'File', 'Rows', 'Pulled'].map((t, i) => h('th', {class: i < 2 ? 'l' : ''}, t))),
        d.extracts.map(e => h('tr', {}, h('td', {class: 'mono'}, e.object), h('td', {class: 'mono'}, e.file), h('td', {class: 'n'}, (e.rows || 0).toLocaleString()), h('td', {class: 'n'}, ago(e.extracted))))),
      h('div', {class: 'row', style: 'margin-top:10px'}, btn, sched),
      d.can_refresh ? null : h('div', {class: 'hint'}, 'Only the person whose connection pulled these tables can refresh them.')].filter(Boolean));
  }).catch(e => card.replaceChildren(h('h3', {}, 'Warehouse data'), h('div', {class: 'note err'}, e.message)));
  return card;
}

/* admin: OAuth apps per warehouse and query guardrails */
async function adminData() {
  const d = await api('/api/admin/data');
  const apps = Object.fromEntries(Object.entries(d.oauth).map(([k, v]) => [k, {client_id: v.client_id || '', tenant: v.tenant || '', role: v.role || ''}]));
  const secretsIn = {};
  const g = {...d.guardrails};
  const field = (obj, k, ph, type) => { const el = h('input', {type: type || 'text', value: obj[k] ?? '', placeholder: ph || ''}); el.oninput = () => { obj[k] = type === 'number' ? +el.value : el.value; }; return el; };
  return h('div', {},
    h('div', {class: 'card flat'}, h('h3', {}, 'Warehouse sign-in (OAuth apps)'),
      h('div', {class: 'hint', style: 'margin:-6px 0 10px'}, 'Register one OAuth app per warehouse with this redirect URL; people then sign in with their own login and Relay keeps a refresh token for scheduled refreshes.'),
      h('div', {class: 'path'}, h('code', {}, d.redirect_uri), copyBtn(d.redirect_uri)),
      h('div', {class: 'opts', style: 'margin-top:12px'}, Object.entries(d.oauth).map(([k, v]) => h('div', {class: 'card flat', style: 'margin:0'},
        h('b', {}, v.label), h('small', {class: 'muted', style: 'display:block;margin-top:6px'}, 'Client id'), field(apps[k], 'client_id'),
        k === 'fabric' ? [h('small', {class: 'muted', style: 'display:block;margin-top:6px'}, 'Entra tenant id'), field(apps[k], 'tenant')] : null,
        k === 'snowflake' ? [h('small', {class: 'muted', style: 'display:block;margin-top:6px'}, 'Role to request (optional)'), field(apps[k], 'role')] : null,
        h('small', {class: 'muted', style: 'display:block;margin-top:6px'}, 'Client secret'),
        (() => { const el = h('input', {type: 'password', placeholder: v.has_secret ? 'Stored — leave empty to keep' : 'client secret'}); el.oninput = () => { secretsIn[k] = el.value; }; return el; })())))),
    h('div', {class: 'card flat'}, h('h3', {}, 'Guardrails for live queries (Ask Relay)'), h('div', {class: 'opts'},
      h('div', {}, h('small', {class: 'muted'}, 'Row limit'), field(g, 'row_limit', '', 'number')),
      h('div', {}, h('small', {class: 'muted'}, 'Timeout (seconds)'), field(g, 'timeout_s', '', 'number')),
      h('div', {}, h('small', {class: 'muted'}, 'BigQuery: most GB one query may scan (dry run first)'), field(g, 'bigquery_max_gb', '', 'number'))),
      h('div', {class: 'hint'}, 'Always read-only: one SELECT, parsed in the warehouse\'s dialect; INSERT, UPDATE, DELETE, MERGE, CREATE, DROP, ALTER and other commands are refused.')),
    h('div', {class: 'card flat'}, h('h3', {}, `Connections in the organisation (${d.connections.length})`),
      d.connections.length ? h('table', {class: 'utable'}, h('tr', {}, ['Connection', 'System', 'Owner', 'May do', 'Shared with', 'Status', 'Last used'].map((t, i) => h('th', {class: i < 6 ? 'l' : ''}, t))),
        d.connections.map(c => h('tr', {}, h('td', {}, c.name), h('td', {}, c.kind), h('td', {}, c.owner), h('td', {}, SCOPE_TEXT[c.scope] ? SCOPE_TEXT[c.scope][0] : c.scope || 'Read-only'), h('td', {}, SHARE_TEXT[c.sharing] || c.sharing || 'Only me'), h('td', {}, connPill(c)), h('td', {class: 'n'}, c.last_used ? ago(c.last_used) : '—'))))
        : h('div', {class: 'muted small'}, 'Nobody has connected a system yet.'),
      h('div', {class: 'hint'}, 'Each connection belongs to its owner, who decides what it may do and who may use it. Admins see that it exists, never its credentials.')),
    h('div', {class: 'row', style: 'justify-content:flex-end'}, h('button', {class: 'btn primary', onclick: async () => {
      try { await api('/api/admin/data', {method: 'PUT', json: {oauth: apps, secrets: secretsIn, guardrails: g}}); notify('Data connector settings saved', 'ok'); reAdmin(); }
      catch (e) { notify(e.message, 'err'); } }}, 'Save')));
}
