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
      h('div', {class: 'small muted'}, `credits left · a new dashboard uses ${costOf('dashboard')}, a change ${costOf('change')}`),
      o.pending_request ? h('div', {class: 'small', style: 'margin-top:6px'}, h('span', {class: 'tag warn'}, 'Waiting for PASDACS'),
        ` ${Number(o.pending_request.credits).toLocaleString()} credits asked for`) : null),
    h('button', {class: 'pmitem', type: 'button', onclick: () => { closePopover(); creditsDialog(); }}, icon('plus'), h('span', {class: 'grow'}, 'Request credits')),
    h('a', {class: 'pmitem', href: '#/org', onclick: closePopover}, icon('building'), h('span', {class: 'grow'}, 'Organisation, people and credit history')),
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
    o.pending_request ? h('span', {class: 'tag warn'}, `${Number(o.pending_request.credits).toLocaleString()} credits asked for, waiting for PASDACS`) : null,
    h('button', {class: 'btn sm ghost', type: 'button', onclick: () => creditsDialog()}, icon('plus'), 'Request credits'));
}

/* ---------------- Request credits: PASDACS approves every request (the admin portal); one waiting at a time ---------------- */
function creditsDialog(reason) {
  const o = ORG(), me = S.me || {};
  if (!o.id) return;
  const contact = o.contact || 'info@pasdacs.com';
  if (o.pending_request) {                     // one request at a time: show it, and let it be withdrawn
    const p = o.pending_request, out = h('div', {role: 'status'});
    const wd = h('button', {class: 'btn', type: 'button'}, 'Withdraw it');
    wd.onclick = async () => {
      wd.disabled = true;
      try { await api(`/api/org/credit-request/${encodeURIComponent(p.id)}/withdraw`, {method: 'POST'}); await refreshOrg(true); m.remove();
        notify('Withdrawn. You can ask for a different amount now.', 'ok'); }
      catch (e) { wd.disabled = false; out.replaceChildren(h('div', {class: 'note err'}, e.message)); }
    };
    const m = modal('Request credits', h('div', {class: 'mbody'},
      reason ? h('div', {class: 'note warn', style: 'margin-top:0'}, reason) : null,
      h('p', {style: 'margin-top:0'}, h('b', {}, `${p.user_name || 'Someone'} asked PASDACS for ${Number(p.credits).toLocaleString()} credits `),
        `${ago(p.created)}. PASDACS approves every request and replies by email; the credits then appear here at once.`),
      h('p', {class: 'small muted'}, `To ask for a different amount, withdraw this request first. For anything urgent, write to ${contact}.`),
      out, h('div', {class: 'row', style: 'justify-content:flex-end;gap:10px;margin-top:12px'}, wd,
        h('button', {class: 'btn primary', type: 'button', onclick: () => m.remove()}, 'OK'))));
    return;
  }
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
      out.replaceChildren(r.sent ? h('div', {class: 'note ok'}, `Sent to PASDACS (${r.contact}). You will hear back at ${me.email}; once it is approved, the credits appear in ${o.name} at once.`)
        : h('div', {class: 'note warn'}, 'Your request is recorded and PASDACS sees it, but the email could not be sent from here. You can also ', mailLink(`email ${r.contact}`), '.'));
      send.lastChild.textContent = 'Sent';
      refreshOrg(true);
    } catch (e) {
      send.disabled = false;
      out.replaceChildren(h('div', {class: 'note err'}, e.message, ' You can also ', mailLink(`email ${contact}`), '.'));
    }
  };
  modal('Request credits', h('div', {class: 'mbody'},
    reason ? h('div', {class: 'note warn', style: 'margin-top:0'}, reason) : null,
    h('p', {style: 'margin-top:0'}, h('b', {}, 'PASDACS approves every credit request. '), `Tell us how many credits ${o.name} needs: we reply by email, and once it is approved the credits appear here at once. Paying online is coming later.`),
    h('dl', {class: 'kv small'}, h('dt', {}, 'Organisation'), h('dd', {}, `${o.name} · @${o.domain}`),
      h('dt', {}, 'Requested by'), h('dd', {}, `${me.name || ''} · ${me.email || ''}`), h('dt', {}, 'Credits now'), h('dd', {}, credits(o.credits))),
    h('label', {class: 'f'}, 'Credits you need'), h('div', {class: 'row', style: 'gap:10px;flex-wrap:wrap'}, picks, custom),
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
        h('div', {class: 'row', style: 'margin-top:12px;gap:10px;flex-wrap:wrap'}, h('button', {class: 'btn primary', type: 'button', onclick: () => creditsDialog()}, icon('plus'), 'Request credits'),
          h('span', {class: 'small muted'}, 'PASDACS approves every request. When a run fails or is stopped, its credits come back.'))),
      h('div', {class: 'card'}, h('h3', {}, 'Owners'),
        h('div', {class: 'stack', style: 'gap:6px'}, d.people.filter(p => p.owner).map(p => h('div', {},
          h('b', {}, p.name + (p.id === (S.me || {}).id ? ' (you)' : '')), p.primary ? h('span', {class: 'tag acc', style: 'margin-left:6px'}, 'Main owner') : null,
          h('div', {class: 'small muted'}, p.email)))),
        h('p', {class: 'small muted'}, `Owners manage the people, the organisation's name and its credit requests, and can open every dashboard in it. `
          + `Everyone who signs in with an @${d.domain} address joins ${d.name} as a member and shares its credits; each person's dashboards are private until they share them.`),
        d.is_primary && d.people.length > 1 ? h('button', {class: 'btn sm', type: 'button', onclick: () => transferDialog(d)}, icon('swap'), 'Transfer ownership') : null)),
    peopleCard(d, th),
    h('div', {class: 'card'}, h('h3', {}, 'Credit history'),
      d.ledger.length ? h('div', {class: 'orgwrap'}, h('table', {class: 'utable'}, th(['When', 'What', 'Who', 'Dashboard', 'Credits', 'Left'], 4),
        h('tbody', {}, d.ledger.map(r => h('tr', {}, h('td', {}, when(r.ts)), h('td', {}, LEDGER(r)), h('td', {}, r.user_name || 'Relay'),
          h('td', {}, r.project_open ? h('a', {href: '#/p/' + r.project_id}, r.project_name || r.project_id) : r.project_name || '—'),
          h('td', {class: 'n delta' + (r.delta > 0 ? ' plus' : '')}, (r.delta > 0 ? '+' : '') + r.delta), h('td', {class: 'n'}, r.balance))))))
        : h('div', {class: 'muted small'}, 'Nothing yet.')),
    h('div', {class: 'card'}, h('h3', {}, 'Credit requests'),
      (d.requests || []).length ? h('div', {class: 'orgwrap'}, h('table', {class: 'utable'}, th(['Asked', 'Who', 'Credits', 'Answer', ''], 2),
        h('tbody', {}, d.requests.map(r => h('tr', {}, h('td', {}, when(r.created)), h('td', {}, r.user_name || '—'),
          h('td', {class: 'n'}, Number(r.credits).toLocaleString()), h('td', {}, requestState(r)),
          h('td', {class: 'n'}, r.status === 'pending' && (d.may_manage || r.user_id === (S.me || {}).id)
            ? h('button', {class: 'btn sm ghost', type: 'button', onclick: async () => {
                try { await api(`/api/org/credit-request/${encodeURIComponent(r.id)}/withdraw`, {method: 'POST'}); await refreshOrg(true); renderOrg(); }
                catch (e) { notify(e.message, 'err'); } }}, 'Withdraw') : null))))))
        : h('div', {class: 'muted small'}, 'None yet. PASDACS approves every credit request: use Request credits.')));
}
/* ---------------- people: owners add people, make owners or members, remove and add back (app/orgs.py) ---------------- */
function peopleCard(d, th) {
  const me = (S.me || {}).id, manage = d.may_manage;
  const act = async (fn, ok) => { try { const r = await fn(); if (r && r.signed_out) { location.href = '/login.html'; return; }
    if (ok) notify(ok, 'ok'); await refreshOrg(true); renderOrg(); } catch (e) { notify(e.message, 'err'); } };
  const roleSel = p => {
    if (!manage || p.primary) return p.primary ? h('span', {class: 'tag acc'}, 'Main owner') : p.owner ? h('span', {class: 'tag acc'}, 'Owner') : 'Member';
    const sel = h('select', {class: 'sel', style: 'max-width:130px', 'aria-label': `Role of ${p.name}`},
      [['owner', 'Owner'], ['member', 'Member']].map(([v, t]) => h('option', {value: v, selected: (p.owner ? 'owner' : 'member') === v}, t)));
    sel.onchange = () => act(() => api(`/api/org/people/${encodeURIComponent(p.id)}`, {method: 'PATCH', json: {role: sel.value}}), `${p.name} is now ${sel.value === 'owner' ? 'an owner' : 'a member'}`);
    return sel;
  };
  const remove = p => manage && !p.primary ? h('button', {class: 'btn sm ghost danger', type: 'button', onclick: async () => {
    const self = p.id === me;
    if (await confirmBox(self ? `Leave ${d.name}?` : `Remove ${p.name}?`, (self ? 'You will be signed out and cannot sign in to it again unless an owner adds you back. '
      : `${p.name} is signed out and cannot sign in to ${d.name} again unless an owner adds them back. `) + 'Their dashboards stay; owners can still open them.', self ? 'Leave' : 'Remove'))
      act(() => api(`/api/org/people/${encodeURIComponent(p.id)}`, {method: 'DELETE'}), self ? null : `${p.name} removed`);
  }}, p.id === me ? 'Leave' : 'Remove') : null;
  return h('div', {class: 'card'},
    h('div', {class: 'row', style: 'gap:10px;flex-wrap:wrap;align-items:center'}, h('h3', {style: 'margin:0'}, `People (${d.people.length})`), h('span', {class: 'spacer'}),
      manage ? h('button', {class: 'btn sm primary', type: 'button', onclick: () => addPersonDialog(d)}, icon('plus'), 'Add people') : null),
    h('div', {class: 'orgwrap', style: 'margin-top:10px'}, h('table', {class: 'utable'}, th(['Name', 'Email', 'Role', 'Joined', 'Last sign-in', ''], 3),
      h('tbody', {}, d.people.map(p => h('tr', {}, h('td', {}, p.name + (p.id === me ? ' (you)' : '')), h('td', {}, p.email), h('td', {}, roleSel(p)),
        h('td', {class: 'n'}, when(p.created)), h('td', {class: 'n'}, p.last_login ? ago(p.last_login) : h('span', {class: 'muted'}, 'not yet')),
        h('td', {class: 'n'}, remove(p))))))),
    (d.removed || []).length ? h('details', {class: 'more', style: 'margin-top:10px'}, h('summary', {}, `Removed (${d.removed.length})`),
      h('div', {class: 'stack', style: 'gap:6px;margin-top:8px'}, d.removed.map(p => h('div', {class: 'row', style: 'gap:8px;flex-wrap:wrap'},
        h('span', {}, h('b', {}, p.name), ` · ${p.email}`, h('span', {class: 'small faint'}, ` · removed ${when(p.deactivated)}`)), h('span', {class: 'spacer'}),
        h('button', {class: 'btn sm', type: 'button', onclick: () => act(() => api('/api/org/people', {json: {email: p.email, role: 'member'}}), `${p.name} is back in ${d.name}`)}, 'Add back')))))
      : null);
}
function addPersonDialog(d) {
  const emails = h('textarea', {rows: 3, placeholder: `name@${d.domain}, one or more (one a line, or separated by commas)`});
  const role = h('select', {class: 'sel', style: 'max-width:200px'}, [['member', 'Member'], ['owner', 'Owner']].map(([v, t]) => h('option', {value: v}, t)));
  const out = h('div', {role: 'status'});
  const ok = h('button', {class: 'btn primary', type: 'button'}, icon('plus'), 'Add');
  const m = modal(`Add people to ${d.name}`, h('div', {class: 'mbody'},
    h('p', {class: 'muted small', style: 'margin-top:0'}, `@${d.domain} addresses only. They get an email; they sign in with a code like everyone else. Members build dashboards and share the credits; owners also manage the people.`),
    h('label', {class: 'f', style: 'margin-top:0'}, 'Email addresses'), emails, h('label', {class: 'f'}, 'As'), role, out,
    h('div', {class: 'row', style: 'justify-content:flex-end;margin-top:12px'}, ok)));
  ok.onclick = async () => {
    const list = [...new Set(emails.value.split(/[\s,;]+/).map(x => x.trim()).filter(Boolean))];
    if (!list.length) return out.replaceChildren(h('div', {class: 'note warn'}, 'Type at least one email address.'));
    ok.disabled = true;
    const lines = [];
    for (const e of list) {
      try { const r = await api('/api/org/people', {json: {email: e, role: role.value}});
        lines.push(h('div', {class: 'small'}, '✓ ', `${r.added.name} (${e}) `, r.added.back ? 'is back' : 'added', r.added.invited ? ', invitation emailed' : ', not emailed: tell them to sign in')); }
      catch (err) { lines.push(h('div', {class: 'small', style: 'color:var(--err)'}, `✗ ${e}: ${err.message}`)); }
    }
    out.replaceChildren(h('div', {class: 'note'}, lines));
    ok.disabled = false; emails.value = '';
    await refreshOrg(true); renderOrg();
  };
}
function transferDialog(d) {
  const others = d.people.filter(p => p.id !== (S.me || {}).id);
  const who = h('select', {class: 'sel'}, others.map(p => h('option', {value: p.id}, `${p.name} · ${p.email}${p.owner ? ' (owner)' : ''}`)));
  const stay = h('input', {type: 'checkbox', checked: true});
  const err = h('div', {class: 'err-msg', role: 'alert'});
  const ok = h('button', {class: 'btn primary', type: 'button'}, 'Transfer');
  const m = modal(`Transfer the main ownership of ${d.name}`, h('div', {class: 'mbody'},
    h('p', {class: 'muted small', style: 'margin-top:0'}, 'The main owner is the organisation\'s contact for PASDACS and its first-time setup. They become an owner too, and are told.'),
    h('label', {class: 'f', style: 'margin-top:0'}, 'New main owner'), who,
    h('label', {class: 'chk', style: 'margin-top:10px'}, stay, h('span', {}, 'Keep me as an owner')), err,
    h('div', {class: 'row', style: 'justify-content:flex-end;margin-top:12px'}, ok)));
  ok.onclick = async () => {
    ok.disabled = true;
    try { await api('/api/org/transfer', {json: {uid: who.value, stay_owner: stay.checked}}); m.remove(); notify('Main ownership transferred', 'ok');
      await loadMe(); renderOrg(); }
    catch (e) { ok.disabled = false; err.textContent = e.message; }
  };
}
/* a credit request's answer, in words (the Organisation page and the admin portal's Requests) */
function requestState(r) {
  if (r.status === 'pending') return h('span', {class: 'tag warn'}, 'Waiting for PASDACS');
  if (r.status === 'approved') return h('span', {}, h('span', {class: 'tag ok'}, `Approved +${Number(r.granted || 0).toLocaleString()}`),
    r.note ? h('span', {class: 'small muted'}, ` ${r.note}`) : null, h('span', {class: 'small faint'}, ` · ${when(r.decided)}`));
  if (r.status === 'declined') return h('span', {}, h('span', {class: 'tag err'}, 'Declined'), h('span', {class: 'small muted'}, ` ${r.note || ''}`),
    h('span', {class: 'small faint'}, ` · ${when(r.decided)}`));
  return h('span', {class: 'small muted'}, `Withdrawn${r.decided_name ? ' by ' + r.decided_name : ''}`);
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
        h('dt', {}, 'Credits'), h('dd', {}, (o.credits ? `${credits(o.credits)} to start` : 'none yet: PASDACS approves every credit request (Request credits)')
          + ` · a new dashboard uses ${costOf('dashboard')}, a change ${costOf('change')}`))),
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
  document.title = 'Organisations · D2D Relay admin';
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
  const kindLabel = k => (d.catalogue.find(c => c.kind === k) || {}).label || k;
  const connectorsDialog = o => {             // switch connectors on for one organisation (the public side is CSV only)
    const picked = new Set(o.connectors || []);
    const boxes = h('div', {class: 'stack', style: 'gap:6px'}, d.catalogue.map(c => {
      const cb = h('input', {type: 'checkbox', checked: picked.has(c.kind)});
      cb.onchange = () => { if (cb.checked) picked.add(c.kind); else picked.delete(c.kind); };
      return h('label', {class: 'chk'}, cb, h('span', {}, c.label));
    }));
    const err = h('div', {class: 'err-msg', role: 'alert'});
    const ok = h('button', {class: 'btn primary', type: 'button'}, 'Save');
    const m = modal(`Connectors for ${o.name}`, h('div', {class: 'mbody'},
      h('p', {class: 'muted small', style: 'margin-top:0'}, `Switched on, ${o.name} can add connections for it and build dashboards from it. `
        + 'Switched off, its connections stop working at once; they are kept, so switching it on again brings them back. The owner is told.'),
      boxes, err, h('div', {class: 'row', style: 'justify-content:flex-end;margin-top:12px'}, ok)));
    ok.onclick = async () => {
      ok.disabled = true;
      try { await api(`/api/admin/orgs/${encodeURIComponent(o.id)}/connectors`, {method: 'PUT', json: {kinds: [...picked]}}); m.remove();
        notify(`Saved: ${o.name}`, 'ok'); refreshOrg(true); renderOrgs(); }
      catch (e) { ok.disabled = false; err.textContent = e.message; }
    };
  };
  const th = (cols, left) => h('thead', {}, h('tr', {}, cols.map((c, i) => h('th', {class: i < left ? 'l' : null}, c))));
  page.append(
    h('div', {class: 'phead'}, h('div', {style: 'flex:1'}, h('div', {class: 'eyebrow'}, 'Platform'), h('h1', {}, 'Organisations'),
      h('div', {class: 'meta'}, `Every organisation on D2D Relay, each in its own workspace. ${d.start ? `Each starts with ${credits(d.start)}` : 'They start with no credits and get them when you approve a request'}; `
        + `a new dashboard uses ${d.costs.dashboard}, a change ${d.costs.change}. Organisations use CSV files until you switch a connector on.`))),
    h('div', {class: 'card'}, h('div', {class: 'orgwrap'}, h('table', {class: 'utable'},
      th(['Organisation', 'Owner', 'Connectors', 'People', 'Dashboards', 'Credits used', 'Credits left', 'Last sign-in', ''], 3),
      h('tbody', {}, d.orgs.map(o => h('tr', {},
        h('td', {}, h('b', {}, o.name), o.platform ? h('span', {class: 'tag', style: 'margin-left:6px'}, 'Platform') : null,
          o.status && o.status !== 'active' ? h('span', {class: 'tag err', style: 'margin-left:6px'}, o.status) : null,
          h('div', {class: 'small muted'}, '@' + o.domain)),
        h('td', {}, o.owner ? [o.owner.name, h('div', {class: 'small muted'}, o.owner.email)] : '—'),
        h('td', {class: 'small', style: 'white-space:nowrap', title: (o.connectors || []).map(kindLabel).join(', ') || null},
          !(o.connectors || []).length ? h('span', {class: 'muted'}, 'CSV only') : o.connectors.length === d.catalogue.length ? `All ${o.connectors.length}`
            : o.connectors.length > 2 ? `${kindLabel(o.connectors[0])} +${o.connectors.length - 1}` : o.connectors.map(kindLabel).join(', ')),
        h('td', {class: 'n'}, o.people), h('td', {class: 'n'}, o.dashboards), h('td', {class: 'n'}, o.spent),
        h('td', {class: 'n'}, h('b', {}, o.credits), o.pending ? h('div', {}, h('a', {href: '#/requests', class: 'tag warn', style: 'text-decoration:none'},
          `asks for ${Number(o.pending.credits).toLocaleString()}`)) : null),
        h('td', {class: 'n'}, o.last_login ? ago(o.last_login) : '—'),
        h('td', {class: 'n'}, h('div', {class: 'row', style: 'gap:6px;justify-content:flex-end;flex-wrap:nowrap'},
          h('button', {class: 'btn sm', type: 'button', onclick: () => connectorsDialog(o)}, icon('plug'), 'Connectors'),
          h('button', {class: 'btn sm', type: 'button', onclick: () => adjust(o)}, icon('plus'), 'Credits'))))))))),
    h('p', {class: 'small muted'}, 'What organisations ask for (credits, connectors) is under ', h('a', {href: '#/requests'}, 'Requests'), '.'));
}

/* ---------------- Requests (#/requests, the admin portal): credits and connectors organisations asked for ---------------- */
async function renderRequests() {
  const page = h('div', {class: 'page wide'});
  $('#main').replaceChildren(page);
  document.title = 'Requests · D2D Relay admin';
  let d;
  try { d = await api('/api/admin/requests'); } catch (e) { return page.append(h('div', {class: 'note err'}, e.message)); }
  if (location.hash !== '#/requests') return;
  const kindLabel = k => (d.catalogue.find(c => c.kind === k) || {}).label || k;
  const th = (cols, left) => h('thead', {}, h('tr', {}, cols.map((c, i) => h('th', {class: i < left ? 'l' : null}, c))));
  const sent = r => r.sent ? 'yes' : h('span', {class: 'tag warn', title: 'The email could not be sent; the request is only here'}, 'no');
  const answer = (r, approve) => {           // approve (the amount may differ) or decline (with the reason they are told)
    const n = h('input', {type: 'number', min: 1, step: 1, value: r.credits, style: 'max-width:160px'});
    const note = h('input', {type: 'text', placeholder: approve ? 'Optional, shown in their credit history: e.g. Invoice 2026-031 paid' : 'For example: please write to us about a plan first'});
    const err = h('div', {class: 'err-msg', role: 'alert'});
    const ok = h('button', {class: 'btn primary' + (approve ? '' : ' danger'), type: 'button'}, approve ? 'Approve and add the credits' : 'Decline');
    const m = modal(`${approve ? 'Approve' : 'Decline'}: ${r.org_name} asks for ${Number(r.credits).toLocaleString()} credits`, h('div', {class: 'mbody'},
      h('p', {class: 'muted small', style: 'margin-top:0'}, `${r.user_name || ''} · ${r.email || ''} · ${when(r.created)}. ${r.org_name} has ${credits(r.org_credits)} now.`),
      r.message ? h('div', {class: 'note small', style: 'margin-top:0'}, r.message) : null,
      approve ? [h('label', {class: 'f'}, 'Credits to add'), n] : null,
      h('label', {class: 'f'}, approve ? 'Note ' : 'Why ', h('small', {}, approve ? 'optional' : 'they are told, in the app and by email')), note, err,
      h('div', {class: 'row', style: 'justify-content:flex-end;margin-top:12px'}, ok)));
    ok.onclick = async () => {
      ok.disabled = true;
      try { await api(`/api/admin/requests/${encodeURIComponent(r.id)}/${approve ? 'approve' : 'decline'}`, {json: approve ? {credits: parseInt(n.value, 10) || 0, note: note.value} : {note: note.value}});
        m.remove(); notify(approve ? `Approved: ${r.org_name}` : `Declined: ${r.org_name}`, 'ok'); renderRequests(); }
      catch (e) { ok.disabled = false; err.textContent = e.message; }
    };
  };
  page.append(
    h('div', {class: 'phead'}, h('div', {style: 'flex:1'}, h('div', {class: 'eyebrow'}, 'Platform'), h('h1', {}, 'Requests'),
      h('div', {class: 'meta'}, 'What organisations asked PASDACS for. Each request also went to the contact mailbox by email, unless shown otherwise.'))),
    h('div', {class: 'card'}, h('h3', {}, `Credit requests${d.pending ? ` · ${d.pending} waiting` : ''}`), h('div', {class: 'muted small', style: 'margin:-6px 0 8px'},
      'Organisations get credits only when you approve a request. Approving adds them at once; the organisation is told either way.'),
      d.credits.length ? h('div', {class: 'orgwrap'}, h('table', {class: 'utable'}, th(['Asked', 'Organisation', 'Who', 'Message', 'Credits', 'Answer', ''], 4),
        h('tbody', {}, d.credits.map(r => h('tr', {}, h('td', {}, when(r.created)), h('td', {}, h('b', {}, r.org_name)),
          h('td', {}, r.user_name || '', h('div', {class: 'small muted'}, r.email || '')), h('td', {class: 'small'}, r.message || '—'),
          h('td', {class: 'n'}, Number(r.credits || 0).toLocaleString()),
          h('td', {}, requestState(r), r.status === 'pending' && !r.emailed ? h('div', {class: 'small muted'}, 'not emailed') : null,
            r.decided_name && (r.status === 'approved' || r.status === 'declined') ? h('div', {class: 'small faint'}, 'by ' + r.decided_name) : null),
          h('td', {class: 'n'}, r.status === 'pending' ? h('div', {class: 'row', style: 'gap:6px;justify-content:flex-end;flex-wrap:nowrap'},
            h('button', {class: 'btn sm primary', type: 'button', onclick: () => answer(r, true)}, icon('check'), 'Approve'),
            h('button', {class: 'btn sm', type: 'button', onclick: () => answer(r, false)}, 'Decline')) : null))))))
        : h('div', {class: 'muted small'}, 'None yet.')),
    h('div', {class: 'card'}, h('h3', {}, 'Connector requests'), h('div', {class: 'muted small', style: 'margin:-6px 0 8px'},
      'Sent from Connections. Switch a connector on with Connectors on Organisations.'),
      d.connectors.length ? h('div', {class: 'orgwrap'}, h('table', {class: 'utable'}, th(['When', 'Organisation', 'Who', 'Connectors', 'Message', 'Emailed'], 5),
        h('tbody', {}, d.connectors.map(r => h('tr', {}, h('td', {}, when(r.ts)), h('td', {}, r.org_name), h('td', {}, `${r.name || ''} · ${r.email || ''}`),
          h('td', {}, (r.kinds || []).map(kindLabel).join(', ')), h('td', {}, r.message || '—'), h('td', {class: 'n'}, sent(r)))))))
        : h('div', {class: 'muted small'}, 'None yet.')));
}

/* a request refused for lack of credits (HTTP 402) opens Add credits with the reason (01-core.js api / upload) */
function onNoCredits(message) { refreshOrg(true).then(() => creditsDialog(message)); }
