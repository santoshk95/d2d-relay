/* ---------------- D2D Relay: the organisation and its credits (app/orgs.py): the chip in the top bar (organisation and
   credits left), Organisation (#/org: owner, people, credits and their history), Add credits, the first-time setup of
   a new organisation's owner (#/setup: the brand), and Organisations for the platform admins (#/orgs).
   Every rule is the server's; this file only shows it. ---------------- */
ICONS.palette = ICONS.palette || 'M12 3a9 9 0 0 0 0 18c1 0 1.6-.7 1.6-1.5 0-.4-.2-.8-.4-1.1-.3-.3-.4-.7-.4-1.1 0-.8.7-1.5 1.5-1.5H16a5 5 0 0 0 5-5c0-4.3-4-7.8-9-7.8zM6.5 12.5h.01M8.5 8h.01M13 6.5h.01M17 9.5h.01';
ICONS.coin = ICONS.coin || 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM15 9.4a4 4 0 1 0 0 5.2';
ICONS.building = ICONS.building || 'M4 21V5a1 1 0 0 1 1-1h9a1 1 0 0 1 1 1v16M15 9h4a1 1 0 0 1 1 1v11M3 21h18M8 8h3M8 12h3M8 16h3';

const ORG = () => (S.me && S.me.org) || {};
const credits = n => `${Number(n || 0).toLocaleString()} credit${n === 1 ? '' : 's'}`;
const costOf = what => (ORG().costs || {})[what] || 0;
/* " · 15 credits" after a button's label (nothing outside an organisation) */
const costTag = what => ORG().id && costOf(what) ? h('span', {class: 'cost'}, ` · ${costOf(what)} credits`) : null;

/* ---------------- the chip in the top bar ---------------- */
function renderOrgChip() {
  const o = ORG(), chip = $('#orgchip');
  if (!chip) return;
  chip.hidden = !o.id;
  if (!o.id) return chip.replaceChildren();
  const low = (o.credits || 0) < costOf('change');
  chip.replaceChildren(h('button', {class: 'orgbtn', type: 'button', 'aria-haspopup': 'dialog',
      'aria-label': `${o.name}: ${credits(o.credits)} left. Organisation and credits`, onclick: e => orgMenu(e.currentTarget)},
    icon('building'), h('span', {class: 'oname'}, o.name), h('span', {class: 'ocred' + (low ? ' low' : '')}, credits(o.credits)), icon('chevd', 'wschev')));
}
function orgMenu(anchor) {
  const o = ORG();
  popover(anchor, [
    h('div', {class: 'pmhead'}, h('div', {class: 'small faint'}, 'Your organisation'), h('b', {}, o.name),
      h('div', {class: 'small muted'}, 'Owner: ', o.owner ? (o.is_owner ? 'you' : o.owner.name) : '—', ` · @${o.domain}`)),
    h('div', {style: 'padding:2px 12px 10px'}, h('div', {class: 'credbig'}, Number(o.credits || 0).toLocaleString()),
      h('div', {class: 'small muted'}, `credits left · a new dashboard uses ${costOf('dashboard')}, a change ${costOf('change')}`)),
    h('button', {class: 'pmitem', type: 'button', onclick: () => { closePopover(); creditsDialog(); }}, icon('plus'), h('span', {class: 'grow'}, 'Add credits')),
    h('a', {class: 'pmitem', href: '#/org', onclick: closePopover}, icon('building'), h('span', {class: 'grow'}, 'Organisation, people and credit history')),
    o.platform_admin ? h('a', {class: 'pmitem', href: '#/orgs', onclick: closePopover}, icon('layers'), h('span', {class: 'grow'}, 'All organisations')) : null,
  ], 'profile');
}
/* the credits left, fetched again after something used or added credits (and now and then) */
let ORG_AT = 0;
async function refreshOrg(force) {
  if (!S.me || (!force && Date.now() - ORG_AT < 30000)) return;
  ORG_AT = Date.now();
  try { const me = await api('/api/me'); S.me.org = me.org; renderOrgChip(); } catch (e) { /* the chip keeps its last value */ }
}
/* after /api/me: the chip, and a new organisation's owner goes to the first-time setup */
function orgAfterMe(me) {
  ORG_AT = Date.now();
  renderOrgChip();
  const o = (me && me.org) || {};
  if (o.setup_needed && o.is_owner && !location.hash.startsWith('#/setup')) location.hash = '#/setup';
}
/* the credits line on Dashboards */
function creditsLine() {
  const o = ORG();
  if (!o.id) return null;
  return h('div', {class: 'credline'}, icon('coin'), h('span', {}, h('b', {}, credits(o.credits)), ` left in ${o.name}`),
    h('span', {}, `· a new dashboard uses ${costOf('dashboard')}, a change ${costOf('change')}`),
    h('button', {class: 'btn sm ghost', type: 'button', onclick: () => creditsDialog()}, icon('plus'), 'Add credits'));
}

/* ---------------- Add credits: online payment is coming; until then a request to PASDACS ---------------- */
function creditsDialog(reason) {
  const o = ORG(), me = S.me || {};
  if (!o.id) return;
  const contact = o.contact || 'info@pasdacs.com';
  let amount = 100;
  const custom = h('input', {type: 'number', min: 1, max: 100000, step: 1, placeholder: 'Other', 'aria-label': 'Other number of credits', style: 'max-width:120px'});
  const picks = h('div', {class: 'segbtn', role: 'group', 'aria-label': 'Credits to add'}, [100, 250, 500, 1000].map(n =>
    h('button', {type: 'button', class: n === amount ? 'on' : '', 'aria-pressed': String(n === amount), onclick: e => {
      amount = n; custom.value = '';
      [...picks.children].forEach(b => { b.classList.toggle('on', b === e.currentTarget); b.setAttribute('aria-pressed', String(b === e.currentTarget)); });
    }}, n.toLocaleString())));
  custom.oninput = () => { const n = parseInt(custom.value, 10); if (n > 0) { amount = n; [...picks.children].forEach(b => { b.classList.remove('on'); b.setAttribute('aria-pressed', 'false'); }); } };
  const msg = h('textarea', {rows: 3, placeholder: 'Anything we should know (optional): an invoice or purchase order reference, a deadline…'});
  const mailto = () => {
    const subject = `D2D Relay: ${amount} credits for ${o.name}`;
    const body = `Hello PASDACS,\n\nPlease add ${amount} credits to our D2D Relay organisation.\n\nOrganisation: ${o.name} (@${o.domain})\n`
      + `Requested by: ${me.name || ''} <${me.email || ''}>\nCredits now: ${o.credits}\n` + (msg.value.trim() ? `\n${msg.value.trim()}\n` : '');
    return `mailto:${contact}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
  };
  const mailLink = label => h('a', {href: mailto(), onclick: e => { e.currentTarget.href = mailto(); }}, label);
  const out = h('div', {role: 'status'});
  const send = h('button', {class: 'btn primary', type: 'button'}, icon('send'), 'Send request');
  send.onclick = async () => {
    send.disabled = true;
    try {
      const r = await api('/api/org/credit-request', {json: {credits: amount, message: msg.value}});
      out.replaceChildren(r.sent ? h('div', {class: 'note ok'}, `Sent to ${r.contact}. PASDACS will reply to ${me.email} and add the credits to ${o.name}.`)
        : h('div', {class: 'note warn'}, 'Your request is recorded, but the email could not be sent from here. Please ', mailLink(`email ${r.contact}`), ' as well.'));
      send.lastChild.textContent = 'Sent';
    } catch (e) {
      send.disabled = false;
      out.replaceChildren(h('div', {class: 'note err'}, e.message, ' You can also ', mailLink(`email ${contact}`), '.'));
    }
  };
  modal('Add credits', h('div', {class: 'mbody'},
    reason ? h('div', {class: 'note warn', style: 'margin-top:0'}, reason) : null,
    h('p', {style: 'margin-top:0'}, h('b', {}, 'Paying online is coming soon. '), `For now, tell us how many credits you need: PASDACS replies by email and adds them to ${o.name}.`),
    h('dl', {class: 'kv small'}, h('dt', {}, 'Organisation'), h('dd', {}, `${o.name} · @${o.domain}`),
      h('dt', {}, 'Requested by'), h('dd', {}, `${me.name || ''} · ${me.email || ''}`), h('dt', {}, 'Credits now'), h('dd', {}, credits(o.credits))),
    h('label', {class: 'f'}, 'Credits to add'), h('div', {class: 'row', style: 'gap:10px;flex-wrap:wrap'}, picks, custom),
    h('div', {class: 'hint'}, `A new dashboard uses ${costOf('dashboard')} credits; a change uses ${costOf('change')}.`),
    h('label', {class: 'f'}, 'Message ', h('small', {}, 'optional')), msg,
    out,
    h('div', {class: 'row', style: 'justify-content:flex-end;gap:12px;margin-top:12px;align-items:center;flex-wrap:wrap'},
      h('span', {class: 'small muted'}, 'or ', mailLink(`email ${contact}`)), send)));
}

/* ---------------- Organisation (#/org) ---------------- */
const LEDGER = r => r.kind === 'start' ? 'Starting credits'
  : r.kind === 'adjust' ? (r.delta > 0 ? 'Added by PASDACS' : 'Taken back by PASDACS') + (r.note ? ` · ${r.note}` : '')
  : (r.kind === 'refund' ? 'Given back: ' : '') + (r.what === 'dashboard' ? 'new dashboard' : 'change') + (r.note && r.kind === 'charge' ? ` · ${r.note}` : '');
async function renderOrg() {
  const page = h('div', {class: 'page'});
  $('#main').replaceChildren(page);
  document.title = 'Organisation · D2D Relay';
  let d;
  try { d = await api('/api/org'); } catch (e) { return page.append(h('div', {class: 'note err'}, e.message)); }
  if (location.hash !== '#/org') return;
  if (S.me) { S.me.org = {...(S.me.org || {}), credits: d.credits, name: d.name}; renderOrgChip(); }
  const rename = d.may_manage ? h('button', {class: 'btn sm', type: 'button', onclick: async () => {
    const name = await askText('Rename your organisation', {value: d.name, rows: 1, ok: 'Rename', required: true});
    if (!name || name === d.name) return;
    try { await api('/api/org', {method: 'PATCH', json: {name}}); notify('Renamed', 'ok'); await refreshOrg(true); renderOrg(); } catch (e) { notify(e.message, 'err'); }
  }}, icon('edit'), 'Rename') : null;
  const th = (cols, left) => h('thead', {}, h('tr', {}, cols.map((c, i) => h('th', {class: i < left ? 'l' : null}, c))));
  page.append(
    h('div', {class: 'phead'}, h('div', {style: 'flex:1;min-width:0'}, h('div', {class: 'eyebrow'}, 'Organisation'),
      h('div', {class: 'row', style: 'gap:10px;flex-wrap:wrap'}, h('h1', {}, d.name), rename),
      h('div', {class: 'meta'}, `@${d.domain} · since ${when(d.created)} · ${d.people.length} ${d.people.length === 1 ? 'person' : 'people'} · `
        + `${d.dashboards} dashboard${d.dashboards === 1 ? '' : 's'}`))),
    h('div', {class: 'orggrid'},
      h('div', {class: 'card'}, h('h3', {}, 'Credits'),
        h('div', {class: 'credbig'}, Number(d.credits || 0).toLocaleString()), h('div', {class: 'muted small'}, `credits left, shared by everyone in ${d.name}`),
        h('dl', {class: 'kv small', style: 'margin-top:12px'},
          h('dt', {}, 'New dashboard'), h('dd', {}, credits(d.costs.dashboard)),
          h('dt', {}, 'A change'), h('dd', {}, `${credits(d.costs.change)}: revising the plan, a change request, building a custom visual Relay suggested`),
          h('dt', {}, 'Free'), h('dd', {}, 'Confirming the plan, fixing failed review gates, approving and publishing, Ask Relay questions')),
        h('div', {class: 'row', style: 'margin-top:12px;gap:10px;flex-wrap:wrap'}, h('button', {class: 'btn primary', type: 'button', onclick: () => creditsDialog()}, icon('plus'), 'Add credits'),
          h('span', {class: 'small muted'}, 'When a run fails or is stopped, its credits come back.'))),
      h('div', {class: 'card'}, h('h3', {}, 'Owner'),
        d.owner ? [h('b', {}, d.owner.name + (d.is_owner ? ' (you)' : '')), h('div', {class: 'small muted'}, d.owner.email)] : h('div', {class: 'muted'}, '—'),
        h('p', {class: 'small muted'}, `The first person from @${d.domain} created ${d.name} and owns it. Everyone who signs in with an @${d.domain} `
          + 'address joins it and shares its credits. Each person\'s dashboards are private until they share them.'))),
    h('div', {class: 'card'}, h('h3', {}, `People (${d.people.length})`), h('div', {class: 'orgwrap'}, h('table', {class: 'utable'}, th(['Name', 'Email', 'Role', 'Joined', 'Last sign-in'], 3),
      h('tbody', {}, d.people.map(p => h('tr', {}, h('td', {}, p.name), h('td', {}, p.email), h('td', {}, p.owner ? h('span', {class: 'tag acc'}, 'Owner') : 'Member'),
        h('td', {class: 'n'}, when(p.created)), h('td', {class: 'n'}, p.last_login ? ago(p.last_login) : '—'))))))),
    h('div', {class: 'card'}, h('h3', {}, 'Credit history'),
      d.ledger.length ? h('div', {class: 'orgwrap'}, h('table', {class: 'utable'}, th(['When', 'What', 'Who', 'Dashboard', 'Credits', 'Left'], 4),
        h('tbody', {}, d.ledger.map(r => h('tr', {}, h('td', {}, when(r.ts)), h('td', {}, LEDGER(r)), h('td', {}, r.user_name || 'Relay'),
          h('td', {}, r.project_id ? h('a', {href: '#/p/' + r.project_id}, r.project_name || r.project_id) : '—'),
          h('td', {class: 'n delta' + (r.delta > 0 ? ' plus' : '')}, (r.delta > 0 ? '+' : '') + r.delta), h('td', {class: 'n'}, r.balance))))))
        : h('div', {class: 'muted small'}, 'Nothing yet.')));
}

/* ---------------- the first-time setup of a new organisation (its owner, once): the brand ---------------- */
function renderSetup() {
  const o = ORG();
  if (!o.id || !o.is_owner || !o.setup_needed) { history.replaceState(null, '', '#/d2d'); return renderDashboards(); }
  document.title = 'Set up · D2D Relay';
  const brandBox = h('div');
  const finish = async (skip, btn) => {
    btn.disabled = true;
    try { await api('/api/org/setup', {method: 'POST'}); } catch (e) { btn.disabled = false; return notify(e.message, 'err'); }
    S.me.org.setup_needed = false;
    notify(skip ? 'You can set your brand any time under Branding.' : `${o.name} is set up.`, 'ok');
    location.hash = '#/new';
  };
  const skipBtn = h('button', {class: 'btn', type: 'button', onclick: () => finish(true, skipBtn)}, 'Skip for now');
  const doneBtn = h('button', {class: 'btn primary', type: 'button', onclick: () => finish(false, doneBtn)}, icon('check'), 'Finish and start a dashboard');
  $('#main').replaceChildren(h('div', {class: 'page'},
    h('div', {class: 'eyebrow'}, 'Welcome to D2D Relay'), h('h1', {}, `Set up ${o.name}`),
    h('div', {class: 'muted', style: 'margin:4px 0 16px'}, 'Done once, at the start. Everyone in your organisation uses it.'),
    h('div', {class: 'steps'}, [['Organisation', 'done'], ['Brand', 'cur'], ['First dashboard', '']].map(([s, c], i) =>
      h('div', {class: 'step ' + c}, h('b', {}, c === 'done' ? '✓' : i + 1), h('span', {}, s)))),
    h('div', {class: 'card'}, h('h3', {}, `${o.name} is ready`),
      h('dl', {class: 'kv small'}, h('dt', {}, 'Owner'), h('dd', {}, `you (${(S.me || {}).email || ''})`),
        h('dt', {}, 'Who joins'), h('dd', {}, `everyone who signs in with an @${o.domain} address`),
        h('dt', {}, 'Credits'), h('dd', {}, `${credits(o.credits)} to start · a new dashboard uses ${costOf('dashboard')}, a change ${costOf('change')}`))),
    h('h2', {style: 'margin:22px 0 4px'}, 'Your brand'),
    h('div', {class: 'muted', style: 'margin-bottom:10px'}, 'Add your logo and a few words about your brand. Relay makes report palettes from them; pick one and every new dashboard uses it.'),
    brandBox,
    h('div', {class: 'row', style: 'justify-content:flex-end;gap:10px;margin-top:16px;flex-wrap:wrap'}, skipBtn, doneBtn)));
  renderBranding({into: brandBox, route: '#/setup'});
}

/* ---------------- Organisations (#/orgs, the platform's admins) ---------------- */
async function renderOrgs() {
  const page = h('div', {class: 'page wide'});
  $('#main').replaceChildren(page);
  document.title = 'Organisations · D2D Relay';
  let d;
  try { d = await api('/api/admin/orgs'); } catch (e) { return page.append(h('div', {class: 'note err'}, e.message)); }
  if (location.hash !== '#/orgs') return;
  const adjust = o => {
    const n = h('input', {type: 'number', step: 1, value: 100, style: 'max-width:160px'});
    const note = h('input', {type: 'text', placeholder: 'For example: Invoice 2026-031 paid'});
    const err = h('div', {class: 'err-msg', role: 'alert'});
    const ok = h('button', {class: 'btn primary', type: 'button'}, 'Save');
    const m = modal(`Credits for ${o.name}`, h('div', {class: 'mbody'},
      h('p', {class: 'muted small', style: 'margin-top:0'}, `${o.name} has ${credits(o.credits)}. A negative number takes credits back.`),
      h('label', {class: 'f', style: 'margin-top:0'}, 'Credits to add'), n,
      h('label', {class: 'f'}, 'Why ', h('small', {}, 'shown in their credit history')), note, err,
      h('div', {class: 'row', style: 'justify-content:flex-end;margin-top:12px'}, ok)));
    ok.onclick = async () => {
      ok.disabled = true;
      try { await api(`/api/admin/orgs/${encodeURIComponent(o.id)}/credits`, {json: {credits: parseInt(n.value, 10) || 0, note: note.value}}); m.remove();
        notify(`Saved: ${o.name}`, 'ok'); refreshOrg(true); renderOrgs(); }
      catch (e) { ok.disabled = false; err.textContent = e.message; }
    };
  };
  const th = (cols, left) => h('thead', {}, h('tr', {}, cols.map((c, i) => h('th', {class: i < left ? 'l' : null}, c))));
  page.append(
    h('div', {class: 'phead'}, h('div', {style: 'flex:1'}, h('div', {class: 'eyebrow'}, 'Platform'), h('h1', {}, 'Organisations'),
      h('div', {class: 'meta'}, `Every organisation on D2D Relay, each in its own workspace. Each starts with ${credits(d.start)}; `
        + `a new dashboard uses ${d.costs.dashboard}, a change ${d.costs.change}.`))),
    h('div', {class: 'card'}, h('div', {class: 'orgwrap'}, h('table', {class: 'utable'},
      th(['Organisation', 'Owner', 'People', 'Dashboards', 'Credits used', 'Credits left', 'Last sign-in', ''], 2),
      h('tbody', {}, d.orgs.map(o => h('tr', {},
        h('td', {}, h('b', {}, o.name), o.platform ? h('span', {class: 'tag', style: 'margin-left:6px'}, 'Platform') : null,
          o.status && o.status !== 'active' ? h('span', {class: 'tag err', style: 'margin-left:6px'}, o.status) : null,
          h('div', {class: 'small muted'}, '@' + o.domain)),
        h('td', {}, o.owner ? [o.owner.name, h('div', {class: 'small muted'}, o.owner.email)] : '—'),
        h('td', {class: 'n'}, o.people), h('td', {class: 'n'}, o.dashboards), h('td', {class: 'n'}, o.spent), h('td', {class: 'n'}, h('b', {}, o.credits)),
        h('td', {class: 'n'}, o.last_login ? ago(o.last_login) : '—'),
        h('td', {class: 'n'}, h('button', {class: 'btn sm', type: 'button', onclick: () => adjust(o)}, icon('plus'), 'Credits')))))))),
    h('div', {class: 'card'}, h('h3', {}, 'Credit requests'), h('div', {class: 'muted small', style: 'margin:-6px 0 8px'},
      'Sent from Add credits. Each one also went to the contact mailbox by email (unless shown otherwise).'),
      d.requests.length ? h('div', {class: 'orgwrap'}, h('table', {class: 'utable'}, th(['When', 'Organisation', 'Who', 'Message', 'Credits', 'Emailed'], 4),
        h('tbody', {}, d.requests.map(r => h('tr', {}, h('td', {}, when(r.ts)), h('td', {}, r.org_name), h('td', {}, `${r.name || ''} · ${r.email || ''}`),
          h('td', {}, r.message || '—'), h('td', {class: 'n'}, Number(r.credits || 0).toLocaleString()), h('td', {class: 'n'}, r.sent ? 'yes' : h('span', {class: 'tag warn'}, 'no')))))))
        : h('div', {class: 'muted small'}, 'None yet.')));
}

/* a request refused for lack of credits (HTTP 402) opens Add credits with the reason (01-core.js api / upload) */
function onNoCredits(message) { refreshOrg(true).then(() => creditsDialog(message)); }
