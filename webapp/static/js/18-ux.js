/* ---------------- UX round 2 (ui-ux-audit.md, items B–H): confirm dialog, skeletons, popovers, notifications panel,
   command palette (Ctrl+K), profile menu, pinned dashboards ---------------- */

/* D: one confirm dialog in the app's style. Resolves true when confirmed. */
function confirmBox(title, text, ok = 'Remove', danger = true) {
  return new Promise(resolve => {
    let done = false;
    const finish = v => { if (done) return; done = true; m.remove(); resolve(v); };
    const yes = h('button', {class: 'btn ' + (danger ? 'danger solid' : 'primary'), onclick: () => finish(true)}, ok);
    const no = h('button', {class: 'btn', onclick: () => finish(false)}, 'Cancel');
    const m = modal(title, h('div', {class: 'mbody'}, h('p', {style: 'margin:0 0 16px;max-width:520px'}, text),
      h('div', {class: 'row', style: 'justify-content:flex-end'}, no, yes)));
    m.classList.add('confirm');
    new MutationObserver((_, o) => { if (!m.isConnected) { o.disconnect(); finish(false); } }).observe(document.body, {childList: true});
    setTimeout(() => no.focus(), 40);                   // the safe choice has the focus
  });
}

/* E: skeletons of the final layout while a page loads */
function skel(kind = 'page', say = '') {      // say: a line for pages that take a while to work out, so a slow page is not a blank one
  const bar = (w, hgt = 12) => h('i', {class: 'sk', style: `width:${w};height:${hgt}px`});
  const card = () => h('div', {class: 'card skc'}, bar('40%', 14), bar('92%'), bar('76%'), bar('60%'));
  if (kind === 'rows') return h('div', {class: 'skwrap', 'aria-busy': 'true', 'aria-label': 'Loading'}, [1, 2, 3, 4].map(() => h('div', {class: 'skrow'}, bar('28px', 28), bar('55%'), bar('15%'))));
  if (kind === 'cards') return h('div', {class: 'grid skwrap', 'aria-busy': 'true', 'aria-label': 'Loading'}, [1, 2, 3].map(card));
  return h('div', {class: 'page skwrap', 'aria-busy': 'true', 'aria-label': 'Loading'}, h('div', {class: 'skhead'}, bar('220px', 22), bar('420px')),
    say ? h('p', {class: 'small muted', role: 'status', style: 'margin:0 0 12px'}, say) : null, card(), card());
}

/* popovers next to an anchor (sidebar items) or below it; Esc / outside click closes, focus returns */
let POP = null;
function popover(anchor, content, cls = '') {
  closePopover();
  const r = anchor.getBoundingClientRect(), back = document.activeElement;
  const p = h('div', {class: 'pop ' + cls, role: 'dialog'}, content);
  document.body.append(p);
  const side = r.right < 320 && window.innerWidth > 900;            // a sidebar item: open to its right
  const top = side ? Math.min(r.top, window.innerHeight - p.offsetHeight - 12) : r.bottom + 6;
  p.style.top = Math.max(8, top) + 'px';
  p.style.left = (side ? r.right + 10 : Math.max(8, Math.min(r.left, window.innerWidth - p.offsetWidth - 8))) + 'px';
  const outside = e => { if (!p.contains(e.target) && !anchor.contains(e.target)) closePopover(); };
  const esc = e => { if (e.key === 'Escape') { closePopover(); if (back && back.focus) back.focus(); } };
  setTimeout(() => { document.addEventListener('mousedown', outside); document.addEventListener('keydown', esc); }, 0);
  POP = {p, off: () => { document.removeEventListener('mousedown', outside); document.removeEventListener('keydown', esc); }};
  setTimeout(() => { const f = p.querySelector('button, a[href], input'); if (f) f.focus(); }, 30);
  window.addEventListener('hashchange', closePopover, {once: true});
  return p;
}
function closePopover() { if (POP) { POP.off(); POP.p.remove(); POP = null; } }

/* B: notifications from the bell, as a panel */
async function notesPanel(anchor) {
  const list = h('div', {class: 'nplist'}, skel('rows'));
  const p = popover(anchor, [h('div', {class: 'nphead'}, h('b', {}, 'Notifications'), h('span', {class: 'spacer'}),
      h('button', {class: 'btn sm ghost', onclick: async () => { draw(await api('/api/notifications/read', {method: 'POST'})); refreshNotes(); }}, 'Mark all read')),
    list, h('a', {class: 'npall', href: '#/notifications'}, 'See all notifications →')], 'notes');
  const draw = n => list.replaceChildren(...(n.items.length ? n.items.slice(0, 10).map(x => h('button', {class: 'note-row' + (x.read ? '' : ' unread'), type: 'button',
      onclick: () => { closePopover(); openNote(x); }},
    h('span', {class: 'nicon ' + x.kind}, icon(NOTE_ICON[x.kind] || 'info')),
    h('span', {class: 'grow'}, h('b', {}, x.title), x.body ? h('span', {class: 'small muted nb'}, x.body) : null), h('span', {class: 'faint small'}, ago(x.created))))
    : [h('div', {class: 'muted small', style: 'padding:14px'}, 'Nothing yet. Builds that finish, shares, alerts and schedules that need you show up here.')]));
  try { draw(await api('/api/notifications')); } catch (e) { list.replaceChildren(h('div', {class: 'note err'}, e.message)); }
  return p;
}

/* F: pinned dashboards (kept per person on the server) */
S.pins = [];
async function loadPins() { try { S.pins = (await api('/api/me/pins')).pins; renderShell(); } catch (e) {} }
async function togglePin(pid) {
  const pins = S.pins.includes(pid) ? S.pins.filter(x => x !== pid) : [...S.pins, pid];
  try { S.pins = (await api('/api/me/pins', {method: 'PUT', json: {pins}})).pins; renderShell(); notify(S.pins.includes(pid) ? 'Pinned to the sidebar' : 'Unpinned', 'ok'); }
  catch (e) { notify(e.message, 'err'); }
}
setTimeout(loadPins, 600);

/* C: command palette — every page, dashboard, insight page and the common actions, from the keyboard */
async function palette() {
  closePopover();
  const route = location.hash;
  const go = href => () => { if (href.startsWith('/')) window.open(href, '_blank'); else location.hash = href.slice(1); };
  const items = [
    ...(S.me && S.me.builder !== false ? [{k: 'Action', t: 'New dashboard', ic: 'plus', run: go('#/new')}] : []),
    {k: 'Action', t: 'Ask Relay a question', ic: 'spark', run: go('#/askd')},
    {k: 'Action', t: 'New scheduled report', ic: 'clock', run: () => { location.hash = '/schedules'; setTimeout(async () => scheduleDialog('report', await api('/api/schedules')), 500); }},
    {k: 'Action', t: 'New alert', ic: 'alert', run: () => { location.hash = '/schedules'; setTimeout(async () => scheduleDialog('alert', await api('/api/schedules')), 500); }},
    {k: 'Action', t: 'Collapse or expand the sidebar', ic: 'chevl', hint: 'Ctrl+B', run: () => setRail(!$('.app').classList.contains('rail'))},
    {k: 'Action', t: 'Mark all notifications read', ic: 'bell', run: async () => { await api('/api/notifications/read', {method: 'POST'}); refreshNotes(); notify('All read', 'ok'); }},
    ...navGroups(route).flatMap(g => g.items.map(([href, ic, label]) => ({k: 'Go to', t: label, ic, run: go(href)}))),
    ...(S.me && S.me.admin ? ADMIN_TABS.map(([id, label]) => ({k: 'Admin', t: label, ic: 'shield', run: go('#/admin/' + id)})) : []),
    ...S.projects.map(p => ({k: 'Dashboard', t: p.name, ic: 'grid', sub: (STATUS[p.status] || [p.status])[0], run: go('#/p/' + p.id)})),
  ];
  const input = h('input', {type: 'text', placeholder: 'Search dashboards, pages, settings — or type an action', role: 'combobox',
    'aria-expanded': 'true', 'aria-controls': 'palist', 'aria-autocomplete': 'list', 'aria-label': 'Command palette'});
  const listEl = h('div', {class: 'palist', id: 'palist', role: 'listbox'});
  let shown = [], at = 0;
  const draw = () => {
    const q = input.value.trim().toLowerCase(), words = q.split(/\s+/).filter(Boolean);
    const score = it => { const s = `${it.t} ${it.k} ${it.sub || ''}`.toLowerCase(); if (!words.every(w => s.includes(w))) return -1;
      return (it.t.toLowerCase().startsWith(q) ? 3 : 0) + (it.k === 'Dashboard' ? 1 : 0); };
    shown = items.map(it => [score(it), it]).filter(x => x[0] >= 0).sort((a, b) => b[0] - a[0]).map(x => x[1]).slice(0, 40);
    at = Math.min(at, Math.max(0, shown.length - 1));
    listEl.replaceChildren(...(shown.length ? shown.map((it, i) => h('div', {class: 'paitem' + (i === at ? ' on' : ''), role: 'option', id: 'pa' + i, 'aria-selected': String(i === at),
        onmousemove: () => { if (at !== i) { at = i; draw(); } }, onclick: () => pick(i)},
      icon(it.ic), h('span', {class: 'grow'}, it.t, it.sub ? h('span', {class: 'faint small'}, ' · ' + it.sub) : null),
      it.hint ? h('kbd', {}, it.hint) : null, h('span', {class: 'pak'}, it.k)))
      : [h('div', {class: 'muted small', style: 'padding:14px'}, 'Nothing matches.')]));
    input.setAttribute('aria-activedescendant', shown.length ? 'pa' + at : '');
    const on = $('.paitem.on', listEl); if (on) on.scrollIntoView({block: 'nearest'});
  };
  const pick = i => { const it = shown[i]; if (!it) return; m.remove(); it.run(); };
  input.oninput = () => { at = 0; draw(); };
  input.onkeydown = e => {
    if (e.key === 'ArrowDown') { e.preventDefault(); at = Math.min(at + 1, shown.length - 1); draw(); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); at = Math.max(at - 1, 0); draw(); }
    else if (e.key === 'Enter') { e.preventDefault(); pick(at); }
  };
  const m = modal('Go to…', h('div', {class: 'pabody'}, input, listEl, h('div', {class: 'pafoot faint small'}, '↑ ↓ to move · Enter to open · Esc to close')));
  m.classList.add('palette');
  draw();
  setTimeout(() => input.focus(), 40);
  try {                                                     // insight pages arrive a moment later
    const pg = await api('/api/pages');
    items.push(...(Array.isArray(pg) ? pg : pg.pages || []).map(p => ({k: 'Page', t: p.title, ic: 'file', run: go('#/pages/' + p.id)})));
    if (m.isConnected) draw();
  } catch (e) {}
}
document.addEventListener('keydown', e => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); if (!$('.modal.palette')) palette(); }
});

/* H: the profile menu under the avatar */
function shortcutsDialog() {
  modal('Keyboard shortcuts', h('div', {class: 'mbody'}, h('table', {class: 'utable'},
    [['Ctrl + K', 'Search and go anywhere (dashboards, pages, settings, actions)'], ['Ctrl + B', 'Collapse or expand the sidebar'],
     ['Esc', 'Close a dialog, panel or the phone menu'], ['Enter', 'Ask (in Ask Relay); Shift + Enter for a new line']]
      .map(([k, d]) => h('tr', {}, h('td', {}, h('kbd', {}, k)), h('td', {class: 'l'}, d))))));
}
function profileMenu(anchor) {
  const me = S.me || {};
  const role = me.admin ? 'Admin' : me.builder ? 'BI Dev / Analyst' : 'Viewer';
  const item = (ic, label, fn, hint) => h('button', {class: 'pmitem', type: 'button', onclick: () => { closePopover(); fn(); }}, icon(ic), h('span', {class: 'grow'}, label), hint ? h('kbd', {}, hint) : null);
  popover(anchor, [
    h('div', {class: 'pmhead'}, h('b', {}, me.name || me.email), h('div', {class: 'small muted'}, me.email),
      h('div', {class: 'small faint'}, role + (me.teams && me.teams.length ? ' · ' + me.teams.map(t => t.name).join(', ') : '') + (me.auth === 'single' ? ' · single-user mode' : ''))),
    me.tenant && me.tenant.name ? h('div', {class: 'small muted', style: 'padding:0 12px 6px'}, 'Workspace: ', h('b', {}, me.tenant.name), me.tenant.acting ? ' (as a guest)' : '') : null,
    me.tenant && ((me.tenant.enter || []).length || me.tenant.acting) ? item('building', 'Switch workspace', () => workspaceMenu($('#ws button') || $('#me button'))) : null,
    item('gear', 'My settings', () => { location.hash = '/settings'; }),
    item('clock', 'My time zone, email and AI use', () => { location.hash = '/settings'; }),
    item('bell', 'Notifications', () => { location.hash = '/notifications'; }),
    item('search', 'Search and go anywhere', palette, 'Ctrl K'),
    item('info', 'Keyboard shortcuts', shortcutsDialog),
    me.auth === 'sso' ? item('external', 'Sign out', async () => { await fetch('/auth/logout', {method: 'POST'}); location.href = '/login.html'; }) : null,
  ], 'profile');
}
