/* ---------------- shell (P9, RELAY by PASDACS): a light rail generated from the module registry (one pillar open
   at a time), a top bar with search, health, notifications, theme and profile, partner white-label, phone drawer,
   collapse to an icon rail, routing ---------------- */
const pref = (k, v) => { try { if (v === undefined) return JSON.parse(localStorage.getItem('d2d.' + k)); localStorage.setItem('d2d.' + k, JSON.stringify(v)); } catch (e) { return null; } };
const RECENT_SHOWN = 5;
// The RELAY by PASDACS lockup (branding/pasdacs, Relay group): the PASDACS fast-forward mark, RELAY in Manrope 800,
// BY PASDACS under it. Tile and chevrons follow --tile / --tile-ink (ink tile on light, white tile on dark); the cursor
// is always the logo mint #00C48C.
const RELAY_LOGO = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 176 48" role="img" aria-label="RELAY by PASDACS"><rect class="rl-tile" x="2" y="2" width="44" height="44" rx="11" fill="#111111"/><path class="rl-chev" d="M10 15l8 9-8 9" fill="none" stroke="#FFFFFF" stroke-width="3.8" stroke-linecap="round" stroke-linejoin="round"/><path class="rl-chev" d="M19 15l8 9-8 9" fill="none" stroke="#FFFFFF" stroke-width="3.8" stroke-linecap="round" stroke-linejoin="round"/><rect x="29" y="29.5" width="9" height="4.4" rx="2" fill="#00C48C"/><text class="rl-word" x="60" y="27" font-family="Manrope, Inter, Segoe UI, Arial, sans-serif" font-size="23" font-weight="800" letter-spacing="3" fill="#111111">RELAY</text><text class="rl-sub" x="61" y="42" font-family="Manrope, Inter, Segoe UI, Arial, sans-serif" font-size="9.5" font-weight="700" letter-spacing="2" fill="#525252">BY PASDACS</text></svg>';
const RELAY_MARK = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48" aria-hidden="true"><rect class="rl-tile" x="2" y="2" width="44" height="44" rx="11" fill="#111111"/><path class="rl-chev" d="M10 15l8 9-8 9" fill="none" stroke="#FFFFFF" stroke-width="4.6" stroke-linecap="round" stroke-linejoin="round"/><path class="rl-chev" d="M19 15l8 9-8 9" fill="none" stroke="#FFFFFF" stroke-width="4.6" stroke-linecap="round" stroke-linejoin="round"/><rect x="29" y="29" width="9" height="5" rx="2" fill="#00C48C"/></svg>';
const NAV_PICK = {hash: null, group: null};
S.registry = null; S.brand = null;

/* ---------------- brand and theme ---------------- */
const svgEl = (markup, cls) => { const s = h('span', {class: cls}); s.innerHTML = markup; return s; };
const markEl = cls => svgEl(RELAY_MARK, cls || 'pm');
function partnerMark(b) { return h('span', {class: 'pmark', style: `background:${b.color || '#111111'}`}, b.mark || 'R'); }
function applyBrand() {
  const b = S.brand || {accent: 'signal', full: 'D2D Relay', name: 'D2D Relay', partner: false};
  const root = document.documentElement;
  if (b.accent && b.accent !== 'signal') root.dataset.accent = b.accent; else delete root.dataset.accent;
  document.title = isAdminPortal() ? 'D2D Relay admin' : b.full;
  const dark = root.dataset.theme === 'dark';
  const logo = $('#brandlogo');
  if (b.partner) {
    const src = (dark && b.logo_dark) || b.logo_light;
    logo.replaceChildren(src ? h('img', {src, alt: ''}) : partnerMark(b), h('span', {class: 'lbl bname'}, h('b', {}, b.full), h('small', {}, b.tagline || '')));
  } else logo.replaceChildren(svgEl(RELAY_LOGO, 'relaylogo'), svgEl(RELAY_MARK, 'railmark'));
  logo.setAttribute('aria-label', `${b.full} - Home`);
  $('#mlogo').replaceChildren(...(b.partner ? [partnerMark(b), h('b', {}, b.name)] : [markEl(), h('b', {}, 'RELAY')]));   // spread: an array is printed as "[object ...]"
  $('#powered').replaceChildren(...(b.partner ? [markEl(), h('span', {}, 'Powered by ', h('b', {}, 'PASDACS Relay'))]
    : [isAdminPortal() ? h('span', {class: 'faint'}, 'D2D Relay admin - PASDACS only')
      : h('span', {class: 'faint', style: 'line-height:1.35', title: 'D2D Relay: D2D means Data to Decision, a product of the Relay Platform by PASDACS'},
        h('b', {}, 'D2D'), ' - Data to Decision', h('br'), 'a Relay Platform product - PASDACS')]));
}
/* the look: 'light', 'dark' or 'system' (the device's setting, followed when it changes); keep: show it, don't save it */
const darkDevice = () => { try { return matchMedia('(prefers-color-scheme: dark)').matches; } catch (e) { return false; } };
const themeChoice = () => { const t = pref('theme'); return t === 'dark' || t === 'light' ? t : 'system'; };
function setTheme(t, keep) {
  const root = document.documentElement;
  if (t === 'dark' || (t === 'system' && darkDevice())) root.dataset.theme = 'dark'; else delete root.dataset.theme;
  if (!keep) pref('theme', t);
  t = root.dataset.theme === 'dark' ? 'dark' : 'light';
  const b = $('#themebtn');
  b.replaceChildren(icon(t === 'dark' ? 'sun' : 'moon'));
  b.setAttribute('aria-label', t === 'dark' ? 'Switch to light mode' : 'Switch to dark mode');
  b.title = b.getAttribute('aria-label');
  applyBrand();
}
async function loadRegistry() {
  try { S.registry = await api('/api/registry'); S.brand = S.registry.brand; applyBrand(); renderShell(); } catch (e) { console.error(e); }
}
const roleOf = () => { const me = S.me || {}; return me.admin ? 'admin' : me.builder ? 'dev' : 'viewer'; };
const moduleById = id => (S.registry ? S.registry.modules.find(m => m.id === id) : null);

/* ---------------- navigation from the registry ---------------- */
const routeOn = href => { const r = location.hash || '#/'; if (href === '#/') return !S.pid && (r === '#/' || r === '#' || r === ''); return r === href || r.startsWith(href + '/'); };
function navGroups(route) {          // D2D Relay: dashboards, Ask Relay, branding and connections only
  const on = p => route.startsWith(p);
  const me = S.me || {};
  if (isAdminPortal()) return [{id: 'top', label: '', items: [   // the admin portal: every organisation and what they ask for
    ['#/orgs', 'layers', 'Organisations', route === '#/orgs' || route === '' || route === '#/'],
    ['#/requests', 'send', 'Requests', route === '#/requests'],
    ['#/payments', 'coin', 'Payments', route === '#/payments'],        // credits bought online (37-payments.js)
    ['#/notifications', 'bell', 'Notifications', route === '#/notifications']]}];
  const top = {id: 'top', label: '', items: [['#/d2d', 'chart', 'Dashboards', routeOn('#/') || on('#/d2d') || !!S.pid]]};
  if (me.builder !== false) top.items.push(['#/new', 'plus', 'New dashboard', on('#/new')]);
  top.items.push(['#/askd', 'spark', 'Ask Relay', on('#/askd')]);
  top.items.push(['#/migration', 'swap', 'Migration D2D', route === '#/migration']);   // moving dashboards between BI tools (39-migration.js)
  const setup = [['#/org', 'building', 'Organisation', route === '#/org'],       // D2D Relay: owner, people, credits (36-org.js)
    ['#/branding', 'palette', 'Branding', on('#/branding')],
    ['#/connections', 'plug', 'Connections', on('#/connections')],
    ['#/notifications', 'bell', 'Notifications', route === '#/notifications']];
  return [top, {id: 'platform', label: 'Setup', items: setup}];
}
function groupOpen(g, route) {
  if (!g.label) return true;
  if (!g.pillar) return !((pref('folded') || {})[g.id]);
  if (NAV_PICK.hash === route) return NAV_PICK.group === g.id;     // a header click, until the page changes
  return g.items.some(i => i[3]);                                    // otherwise the pillar holding the open page
}
function setRail(rail) {
  $('.app').classList.toggle('rail', rail);
  pref('rail', rail);
  const t = $('#railbtn');
  t.setAttribute('aria-expanded', String(!rail));
  t.setAttribute('aria-label', rail ? 'Expand the sidebar' : 'Collapse the sidebar');
  t.title = (rail ? 'Expand' : 'Collapse') + ' the sidebar  (Ctrl+B)';
  t.replaceChildren(icon(rail ? 'chevr' : 'chevl'));
}
function setDrawer(open) {
  $('.app').classList.toggle('drawer', open);
  $('#menubtn').setAttribute('aria-expanded', String(open));
  if (open) setTimeout(() => { const f = $('.side .nav a.on') || $('.side .nav a'); if (f) f.focus(); }, 50);
}
function renderShell() {
  const nb = $('#newbtn');
  if (!nb.childElementCount) {      // the + opens Start new work (19-home.js); without script its link still leads somewhere to start
    nb.append(icon('plus'), h('span', {class: 'lbl'}, 'New dashboard')); nb.dataset.tip = 'New dashboard'; nb.setAttribute('aria-label', 'New dashboard');
    nb.setAttribute('href', '#/new'); nb.onclick = () => setDrawer(false);
  }
  nb.hidden = !!(S.me && S.me.builder === false);
  const route = location.hash;
  const bell = $('#bellbtn');
  bell.querySelectorAll('.nbadge').forEach(x => x.remove());
  if (S.unread) bell.append(h('span', {class: 'nbadge', 'aria-hidden': 'true'}, S.unread > 99 ? '99+' : S.unread));
  bell.setAttribute('aria-label', S.unread ? `Notifications, ${S.unread} unread` : 'Notifications');
  const link = ([href, ic, label, on, extra]) => {
    const st = extra && extra.state;
    return h('a', {href, class: on ? 'on' : '', 'aria-current': on ? 'page' : null, 'data-tip': label, 'aria-label': label + (st === 'planned' ? ' (planned)' : st === 'preview' ? ' (preview)' : st === 'locked' ? ' (not in your plan)' : ''),
        title: extra && extra.tip ? extra.tip : null},
      icon(ic), h('span', {class: 'lbl'}, label),
      st === 'planned' ? h('span', {class: 'plan lbl'}, 'Planned') : st === 'preview' ? h('span', {class: 'plan lbl'}, 'Preview') : st === 'locked' ? h('span', {class: 'plan lbl'}, 'Not in plan') : null,
      extra && extra.badge ? h('span', {class: 'nbadge', 'aria-label': `${extra.badge} waiting`}, extra.badge > 99 ? '99+' : extra.badge) : null);
  };
  $('#nav').replaceChildren(...navGroups(route).map(g => {
    if (!g.label) return h('div', {class: 'ngroup'}, h('div', {class: 'nitems'}, g.items.map(link)));
    const open = groupOpen(g, route);
    const live = g.pillar ? g.items.filter(i => ['available', 'partly'].includes(i[4].state)).length : 0;
    return h('div', {class: 'ngroup' + (g.pillar ? ' pillar' : '') + (open ? '' : ' closed')},
      h('button', {class: 'nghead' + (g.pillar ? ' pillar' : ''), type: 'button', 'aria-expanded': String(open), title: g.pillar ? `${g.label}: ${live} of ${g.items.length} live` : (open ? `Hide ${g.label}` : `Show ${g.label}`),
        onclick: () => {
          if (g.pillar) { NAV_PICK.hash = route; NAV_PICK.group = open ? null : g.id; }
          else { const f = pref('folded') || {}; f[g.id] = open; pref('folded', f); }
          const sc = $('.sidescroll'), y = sc.scrollTop; renderShell(); sc.scrollTop = y;
        }},
        h('span', {}, g.label), g.pillar ? h('em', {class: 'navc'}, g.items.length) : null, icon('chevd', 'chev')),
      h('div', {class: 'nitems'}, g.items.map(link)));
  }));
  // pinned dashboards (the person's own list, kept on the server)
  const pinned = (S.pins || []).map(id => S.projects.find(p => p.id === id)).filter(Boolean), pclosed = !!pref('pinClosed');
  $('#pinbox').hidden = !pinned.length;
  $('#pinbox').classList.toggle('closed', pclosed);
  $('#pinhead').replaceChildren(h('button', {class: 'nghead', type: 'button', 'aria-expanded': String(!pclosed), onclick: () => { pref('pinClosed', !pclosed); renderShell(); }},
    h('span', {}, 'Pinned', h('em', {}, ` ${pinned.length}`)), icon('chevd', 'chev')));
  $('#pinlist').replaceChildren(...pinned.map(p => h('a', {class: 'ritem' + (p.id === S.pid ? ' on' : ''), href: '#/p/' + p.id, title: p.name},
    h('div', {class: 'n'}, p.name), h('div', {class: 'm'}, pill(p.status), ago(p.updated || p.created)))));
  $('#recentbox').hidden = route === '#/d2d' || !(S.me && S.me.builder !== false);     // the Dashboards page already lists them all
  const rclosed = !!pref('recentClosed'), all = !!S.recentAll;
  $('#recenthead').replaceChildren(h('button', {class: 'nghead', type: 'button', 'aria-expanded': String(!rclosed),
      onclick: () => { pref('recentClosed', !rclosed); renderShell(); }},
    h('span', {}, 'Recent dashboards', S.projects.length ? h('em', {}, ` ${S.projects.length}`) : null), icon('chevd', 'chev')));
  $('#recentbox').classList.toggle('closed', rclosed);
  const list = $('#plist'), shown = all ? S.projects.slice(0, 30) : S.projects.slice(0, RECENT_SHOWN);
  list.replaceChildren(...shown.map(p => h('a', {class: 'ritem' + (p.id === S.pid ? ' on' : ''), href: '#/p/' + p.id, title: p.name},
    h('div', {class: 'n'}, p.name), h('div', {class: 'm'}, pill(p.status), ago(p.updated || p.created)))));
  if (S.projects.length > RECENT_SHOWN)
    list.append(h('button', {class: 'rmore', type: 'button', onclick: () => { S.recentAll = !all; renderShell(); }},
      all ? 'Show fewer' : `Show all ${Math.min(S.projects.length, 30)}`));
  if (!S.projects.length) list.append(h('div', {class: 'rempty'}, 'No dashboards yet.'));
}
(function shellControls() {
  setRail(pref('rail') ?? window.innerWidth < 1200);
  setTheme(themeChoice(), true);
  try { matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => { if (themeChoice() === 'system') setTheme('system', true); }); } catch (e) { /* an old browser keeps the look it opened with */ }
  $('#railbtn').onclick = () => setRail(!$('.app').classList.contains('rail'));
  $('#menubtn').onclick = () => setDrawer(!$('.app').classList.contains('drawer'));
  $('#scrim').onclick = () => setDrawer(false);
  $('#themebtn').onclick = () => setTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark');
  $('#searchbtn').onclick = () => palette();
  $('#msearchbtn').onclick = () => palette();
  $('#bellbtn').onclick = e => { if (window.innerWidth > 900) notesPanel(e.currentTarget); else location.hash = '#/notifications'; };
  document.addEventListener('keydown', e => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'b' && !/INPUT|TEXTAREA|SELECT/.test(e.target.tagName)) { e.preventDefault(); setRail(!$('.app').classList.contains('rail')); }
    if (e.key === 'Escape' && $('.app').classList.contains('drawer')) setDrawer(false);
  });
  window.addEventListener('hashchange', () => setDrawer(false));     // a link was followed: close the phone drawer
  // rail tooltips: one floating label (a scrolling sidebar would clip CSS ones)
  const tip = document.body.appendChild(h('div', {class: 'railtip', 'aria-hidden': 'true'}));     // the link itself carries the name
  const show = e => { const a = e.target.closest && e.target.closest('.app.rail .side [data-tip]');
    if (!a || window.innerWidth <= 900) return; const r = a.getBoundingClientRect(); tip.textContent = a.dataset.tip;
    tip.style.top = (r.top + r.height / 2) + 'px'; tip.style.left = (r.right + 10) + 'px'; tip.classList.add('on'); };
  const hide = () => tip.classList.remove('on');
  $('#side').addEventListener('mouseover', show); $('#side').addEventListener('focusin', show);
  $('#side').addEventListener('mouseout', hide); $('#side').addEventListener('focusout', hide); $('#side').addEventListener('scroll', hide, true);
})();
async function refreshList() {
  try {
    const ps = await api('/api/projects'), sig = JSON.stringify(ps), changed = sig !== S.psig;
    S.psig = sig; S.projects = ps; renderShell();
    if (changed && isDash()) renderDashboards();          // only when something changed: keeps the scroll position
  } catch (e) {}
}
async function refreshSys() {
  const a = $('#agent'), d = $('#daxchk');
  try {
    const r = S.health = await api('/api/health'), ag = r.agent || {};
    a.className = 'health ' + (!ag.ok ? 'down' : ag.busy ? 'busy' : 'ok');
    $('span', a).textContent = !ag.ok ? 'Agent offline' : ag.busy ? 'Agent running' + (r.running_model && modelName(r.running_model) ? ` - ${modelName(r.running_model)}` : '')
      + (r.queue ? ` - ${r.queue} waiting` : '') : 'Agents ready';
    d.className = 'health ' + (!r.daxcheck ? 'down' : r.daxcheck.state === 'checking' ? 'busy' : 'ok');
    $('span', d).textContent = !r.daxcheck ? 'DAX checker off' : r.daxcheck.state === 'checking' ? 'Checking DAX...' : 'DAX checker on';
    d.title = r.daxcheck ? "Power BI's own engine checks every measure and visual before a report is published"
      : 'Start daxcheck\\start-daxcheck.cmd on this PC - publishing to Power BI needs it';
    a.title = a.dataset.tip = $('span', a).textContent; d.dataset.tip = $('span', d).textContent;
  } catch (e) { a.className = 'health down'; $('span', a).textContent = 'App offline'; }
  if (S.me && S.me.builder !== false) {
    try { const n = (await api('/api/validate/count')).count; if (n !== S.vcount) { S.vcount = n; renderShell(); } } catch (e) {}
  }
}

/* ---------------- routing ---------------- */
const isHome = () => !S.pid && (location.hash === '' || location.hash === '#/' || location.hash === '#');
const isDash = () => location.hash === '#/d2d';
function route() {
  const m = location.hash.match(/^#\/p\/([\w-]+)(?:\/(\w+))?/);
  const pid = m ? m[1] : null, tab = m && m[2] && TABS.some(t => t[0] === m[2]) ? m[2] : 'overview';
  if (pid !== S.pid) {
    Object.assign(S, {pid, project: null, events: [], after: 0, key: null, version: null, vsel: null, live: null, changes: {}, act: null, actQuery: ''});
  }
  if (tab !== S.tab) { S.tab = tab; S.key = null; S.act = null; }
  renderShell();
  if (isAdminPortal()) {                     // D2D Relay's admin portal: four screens, everything else opens Organisations
    if (location.hash === '#/requests') return renderRequests();
    if (location.hash === '#/payments') return renderPayments();
    if (location.hash === '#/notifications') return renderNotes();
    if (location.hash !== '#/orgs') history.replaceState(null, '', '#/orgs');
    return renderOrgs();
  }
  if (!pid) document.title = 'D2D Relay';
  // D2D Relay: only these screens exist; anything else (old links, bookmarks) opens the dashboards list
  const D2D_ROUTES = ['#/new', '#/d2d', '#/askd', '#/branding', '#/notifications', '#/connections', '#/p/', '#/org', '#/setup', '#/welcome', '#/migration'];
  if (location.hash.startsWith('#/branding')) return renderBranding();
  if (location.hash === '#/org') return renderOrg();                               // D2D Relay: organisations and credits (36-org.js)
  if (location.hash === '#/welcome' || location.hash === '#/setup') return renderTour();   // the first-time tour (38-tour.js)
  if (location.hash === '#/migration') return renderMigration();                   // Migration D2D (39-migration.js)
  if (!pid && !D2D_ROUTES.some(r => location.hash === r || location.hash.startsWith(r.endsWith('/') ? r : r + '/'))) {
    if (location.hash && location.hash !== '#/' && location.hash !== '#') { history.replaceState(null, '', '#/d2d'); }
    return renderDashboards();
  }
  if (location.hash === '#/new') return renderNew();
  if (location.hash === '#/d2d') return renderDashboards();
  if (location.hash === '#/modules') return renderModules();
  if (location.hash === '#/validate') return renderValidate();
  if ((location.hash.startsWith('#/m/') || location.hash.startsWith('#/p/wb-')) && typeof renderWorkbench === 'function') return renderWorkbench();   // module workbench (33-workbench.js): live module pages and work items; modules without a pack keep renderModule
  const mm = location.hash.match(/^#\/m\/(\w+)(?:\/(\w+))?$/);
  if (mm) return renderModule(mm[1], mm[2]);
  if (location.hash === '#/library') return renderLibrary();
  if (location.hash.startsWith('#/admin')) return renderAdmin();
  if (location.hash.startsWith('#/settings')) return renderSettings();
  if (location.hash.startsWith('#/schedules')) return renderSchedules();
  if (location.hash === '#/notifications') return renderNotes();
  if (location.hash.startsWith('#/connections')) return renderConnections();
  if (location.hash.startsWith('#/metrics')) return renderSemantic();
  if (location.hash.startsWith('#/askd')) return renderAskD();
  if (location.hash.startsWith('#/pages')) return renderPages();
  if (location.hash.startsWith('#/start')) return renderStart();
  if (location.hash === '#/team') return renderTeam();
  if (location.hash.startsWith('#/servicedesk')) return renderServiceDesk();
  if (location.hash.startsWith('#/lineage')) return renderLineage();
  if (location.hash.startsWith('#/graph')) return renderGraph();
  if (location.hash.startsWith('#/integrations')) return renderIntegrations();
  if (location.hash.startsWith('#/observability')) return renderObserve();
  if (location.hash.startsWith('#/studio')) return renderStudio();                 // P11
  if (location.hash.startsWith('#/rfp')) return renderRfp();                       // P11
  if (location.hash.startsWith('#/migrate-bi')) return renderMigrateBI();
  if (location.hash.startsWith('#/heal')) return renderHeal();
  if (location.hash.startsWith('#/sdlc')) return renderSdlc();
  if (location.hash.startsWith('#/tenants')) return renderTenants();               // P17
  if (!pid) return renderHome();
  if (!S.project) $('#main').replaceChildren(skel('page'));
  else render();
  poll();
}
window.addEventListener('hashchange', route);
const go = (tab, version) => { if (version != null) S.version = version; S.key = null; location.hash = `#/p/${S.pid}/${tab}`; };

/* ---------------- who is signed in ---------------- */
async function loadMe() {
  try {
    const me = S.me = await api('/api/me');
    const role = roleText(me);
    const initials = (me.name || me.email || '?').split(/[\s@.]+/).filter(Boolean).slice(0, 2).map(w => w[0].toUpperCase()).join('');
    $('#me').replaceChildren(h('button', {class: 'mebtn', type: 'button', 'aria-haspopup': 'dialog', 'aria-label': `Your profile: ${me.name || me.email}`,
        'data-tip': me.name || me.email, onclick: e => profileMenu(e.currentTarget)},
      h('span', {class: 'av'}, initials),
      h('span', {class: 'who'}, h('b', {}, me.name || me.email), h('small', {}, role + (me.auth === 'single' ? ' - single-user mode' : ''))),
      icon('chevr', 'mechev')));
    renderShell();
    if (typeof renderWorkspace === 'function') renderWorkspace();                  // P17: the workspace chip and band
    if (typeof orgAfterMe === 'function' && !isAdminPortal()) orgAfterMe(me);     // D2D Relay: the organisation chip, first-time setup
    $('#me').title = `${me.email} - instance ${me.instance}`;
  } catch (e) {}
}
