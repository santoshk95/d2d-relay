/* ---------------- sharing (phase 1): who can see and change a dashboard ---------------- */
function accessBadge(st) {
  const a = st.access || {};
  const label = a.via === 'admin' ? 'Admin access' : a.level === 'owner' ? 'Owner' : a.level === 'edit' ? 'Can edit' : 'View only';
  const tip = {owner: 'You own this dashboard', admin: 'You can open everything as an admin', user: 'Shared with you',
    team: 'Shared with your team', org: 'Shared with everyone in the organisation'}[a.via] || '';
  return h('span', {class: 'tag ' + (a.level === 'view' ? '' : 'acc'), title: tip, style: 'align-self:center'}, icon(a.level === 'view' ? 'lock' : 'users'), label);
}

const visLabel = v => ({private: 'Private', team: 'Team', org: 'Organisation'}[v] || v);
const DAY = 86400;
function expiryLabel(t) { return t ? (t * 1000 < Date.now() ? 'Expired ' : 'Until ') + new Date(t * 1000).toLocaleDateString() : 'No end date'; }

async function shareDialog(st) {
  let data;
  try { data = await api(`/api/projects/${st.id}/shares`); } catch (e) { return notify(e.message, 'err'); }
  let vis = data.visibility, team = data.team ? data.team.id : (data.teams[0] || {}).id;
  const grants = data.shares.map(s => ({principal_type: s.principal_type, principal_id: s.principal_id, permission: s.permission,
    expires: s.expires, name: s.name, email: s.email}));
  const body = h('div', {class: 'mbody share'});
  const results = h('div', {class: 'dir'});
  const search = h('input', {type: 'text', placeholder: 'Add people or teams…', autocomplete: 'off'});
  let timer;
  search.oninput = () => { clearTimeout(timer); timer = setTimeout(find, 200); };
  async function find() {
    const q = search.value.trim();
    if (!q) return results.replaceChildren();
    const d = await api('/api/directory?q=' + encodeURIComponent(q));
    const taken = new Set(grants.map(g => g.principal_type + ':' + g.principal_id));
    const items = [...d.users.filter(u => u.id !== data.owner.id).map(u => ({principal_type: 'user', principal_id: u.id, name: u.name, email: u.email})),
      ...d.teams.map(t => ({principal_type: 'team', principal_id: t.id, name: t.name, email: `Team · ${t.members} people`}))]
      .filter(x => !taken.has(x.principal_type + ':' + x.principal_id));
    results.replaceChildren(...(items.length ? items.map(x => h('button', {type: 'button', onclick: () => {
      grants.push({...x, permission: 'view', expires: null}); search.value = ''; results.replaceChildren(); draw(); }},
      icon(x.principal_type === 'team' ? 'users' : 'user'), h('span', {}, h('b', {}, x.name), h('small', {}, x.email)))) : [h('div', {class: 'muted small'}, 'No one found.')]));
  }
  function row(g, i) {
    const perm = h('select', {class: 'sel'}, h('option', {value: 'view', selected: g.permission === 'view'}, 'Can view'),
      h('option', {value: 'edit', selected: g.permission === 'edit'}, 'Can edit'));
    perm.onchange = () => { g.permission = perm.value; };
    const exp = h('select', {class: 'sel'}, h('option', {value: '', selected: !g.expires}, 'No end date'),
      g.expires ? h('option', {value: g.expires, selected: true}, expiryLabel(g.expires)) : null,
      ...[7, 30, 90].map(d => h('option', {value: 'd' + d}, `For ${d} days`)));
    exp.onchange = () => { g.expires = !exp.value ? null : exp.value.startsWith('d') ? Date.now() / 1000 + +exp.value.slice(1) * DAY : +exp.value; };
    return h('div', {class: 'grant'}, icon(g.principal_type === 'team' ? 'users' : g.principal_type === 'org' ? 'globe' : 'user'),
      h('span', {class: 'who'}, h('b', {}, g.name), h('small', {}, g.principal_type === 'org' ? 'Everyone who can sign in' : g.email || '')),
      perm, exp, h('button', {class: 'btn sm ghost', title: 'Remove', onclick: () => { grants.splice(i, 1); draw(); }}, icon('x')));
  }
  function draw() {
    const visSel = h('select', {class: 'sel'}, ...['private', 'team', 'org'].map(v => h('option', {value: v, selected: v === vis},
      {private: 'Private: only the owner and people added below', team: 'Team: the team below', org: 'Organisation: everyone can view'}[v])));
    visSel.onchange = () => { vis = visSel.value; draw(); };
    const teamSel = h('select', {class: 'sel'}, data.teams.map(t => h('option', {value: t.id, selected: t.id === team}, t.name)));
    teamSel.onchange = () => { team = teamSel.value; };
    body.replaceChildren(...[
      h('div', {class: 'row', style: 'gap:8px'}, icon('user'), h('span', {}, h('b', {}, data.owner.name), h('span', {class: 'muted small'}, ` · owner · ${data.owner.email}`))),
      h('label', {class: 'f'}, 'General access'), visSel,
      vis === 'team' ? h('div', {style: 'margin-top:8px'}, teamSel, h('div', {class: 'hint'}, "The team's BI Devs / Analysts can edit; its Viewers can view.")) : null,
      h('label', {class: 'f'}, 'People and teams'), search, results,
      h('div', {class: 'grants'}, grants.length ? grants.map(row) : h('div', {class: 'muted small'}, 'Not shared with anyone yet.')),
      h('div', {class: 'note small'}, icon('info'), ' Only BI Devs / Analysts can edit, even when a share says “Can edit”. Shares stay inside Relay.'),
      h('div', {class: 'row', style: 'justify-content:flex-end;margin-top:12px'},
        h('button', {class: 'btn', onclick: () => m.remove()}, 'Cancel'),
        h('button', {class: 'btn primary', onclick: save}, 'Save'))].filter(Boolean));
  }
  async function save(e) {
    e.target.disabled = true;
    try {
      await api(`/api/projects/${st.id}/shares`, {method: 'PUT', json: {visibility: vis, team_id: vis === 'team' ? team : null,
        shares: grants.map(({principal_type, principal_id, permission, expires}) => ({principal_type, principal_id, permission, expires: expires || null}))}});
      notify('Sharing saved', 'ok'); m.remove(); refreshList();
    } catch (err) { notify(err.message, 'err'); e.target.disabled = false; }
  }
  draw();
  const m = modal(`Share “${st.name}”`, body);
}
