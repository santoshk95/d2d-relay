/* ---------------- Relay: the dashboards list (#/d2d) ---------------- */
/* Item 84 (the user, 2026-11-19: "so many time new dashboard and thing repeated rather than visual guide the user to
   start from a point"): until the organisation's first dashboard is published, the page starts with one guided journey:
   five steps, each done, now or later, worked out from where the organisation is (its setup, item 81, and its latest
   dashboard), and one button, for the step it is on. It replaces the empty list's button and the How it works card; the
   header's New dashboard shows once there are dashboards, and the sidebar keeps its one button. */
/* Item 87 (the user, 2026-11-19: "Visual Gallery is with power BI, but will be added other platform as well like tableau,
   qlik, metabase, looker as well as coming soon, and in D2D as well"): the BI platforms, Power BI today, the others coming
   soon (shown, never clickable): Relay Visual, the Dashboards page and New dashboard's Visuals step. */
const PLATFORMS = [['powerbi', 'Power BI', true], ['tableau', 'Tableau'], ['qlik', 'Qlik'], ['metabase', 'Metabase'], ['looker', 'Looker']];
function platformChips(lead) {
  return h('div', {class: 'platforms', role: 'group', 'aria-label': 'BI platforms'}, h('span', {class: 'small muted'}, lead || 'Platforms'),
    PLATFORMS.map(([id, name, on]) => h('span', {class: 'plat' + (on ? ' on' : ''), title: on ? `${name}: available now` : `${name}: coming soon`},
      on ? icon('check') : null, name, on ? null : h('small', {}, 'Coming soon'))));
}
/* Start here (the user, 2026-11-19: "start here should be initial configuration rather than building a dashboard, like org
   details, kpis, metrics, formula, about organisation, branding"): the organisation's one-time setup (item 81), in five
   steps, each done, now or later from /api/me's org.setup.next; the step on now opens that step of #/setup. Gone once
   the setup is finished (or for an organisation from before item 81): then New dashboard is among Home's quick actions. */
const JOURNEY = [
  ['context', 'About your organisation', 'Industry, what the business does, brands, regions, currency and fiscal calendar: Relay Model drafts what it understood, you check it.'],
  ['kpis', 'KPIs, metrics and formulas', 'Your KPI standard: each KPI with its definition and formula, from your industry and your own; keep, change or add.'],
  ['terms', 'Business terms and dictionaries', 'What your columns mean, in your words and abbreviations (sls is Sales), so every dashboard reads your data right.'],
  ['theme', 'Branding', 'Your palette and fonts: every report uses them.'],
  ['finish', 'Check and finish', 'Everything in one view; then dashboards, reviews and Ask Relay start from it.']];
const JOURNEY_AT = {context: 0, prepare: 0, understanding: 0, kpis: 1, terms: 2, theme: 3, finish: 4};
function homeJourney() {
  const o = ORG() || {}, su = o.setup;
  if (!su || su.done) return null;                                   // set up, or from before item 81: nothing to guide
  const at = JOURNEY_AT[su.next] !== undefined ? JOURNEY_AT[su.next] : 0;
  const step = ['prepare', 'understanding'].includes(su.next) ? su.next : JOURNEY[at][0];
  const action = su.can_edit !== false && o.is_owner
    ? h('a', {class: 'btn primary', href: `#/setup?step=${step}`}, icon('play'), at === 0 && su.status !== 'draft' ? 'Set up now' : 'Continue')
    : h('div', {class: 'small muted'}, `An owner of ${o.name || 'your organisation'} is setting it up. Dashboards start once they finish.`);
  return h('section', {class: 'card homejourney', 'aria-label': 'Start here'},
    h('div', {class: 'jhead'}, h('h2', {}, 'Start here'), h('span', {class: 'small muted'}, `Set up ${o.name || 'your organisation'}: step ${at + 1} of ${JOURNEY.length}`)),
    h('ol', {class: 'jsteps'}, JOURNEY.map(([id, title, text], i) => h('li', {class: i < at ? 'done' : i === at ? 'now' : 'later', 'aria-current': i === at ? 'step' : null},
      h('span', {class: 'jdot', 'aria-hidden': 'true'}, i < at ? icon('check') : String(i + 1)),
      h('div', {class: 'jbody'}, h('b', {}, title), h('div', {class: 'small muted'}, text), i === at && action ? h('div', {class: 'jact'}, action) : null)))));
}
const SCOPES = [['all', 'All'], ['mine', 'Mine'], ['shared', 'Shared with me']];
const inScope = (p, scope) => scope === 'mine' ? p.via === 'owner' : scope === 'shared' ? !['owner', 'admin'].includes(p.via) : true;
/* one dashboard's card: the Dashboards page and Home (item 88) */
function dashCard(p) {
  return h('a', {class: 'dcard', href: '#/p/' + p.id},
    h('div', {class: 'row', style: 'gap:8px;align-items:flex-start'}, h('div', {class: 'n', style: 'flex:1'}, p.name),
      (S.pins || []).includes(p.id) ? h('span', {class: 'pinmark', title: 'Pinned to your sidebar'}, icon('pin')) : null, pill(p.status)),
    h('div', {class: 'p'}, p.prompt || ''),
    h('div', {class: 'f'}, h('span', {}, p.versions ? `${p.versions} version${p.versions === 1 ? '' : 's'}` : 'No versions yet'),
      p.pages ? h('span', {}, `${p.pages} pages - ${p.visuals} visuals`) : null,
      p.published ? h('span', {class: 'tag ok'}, icon('check'), p.published_v ? 'Published v' + p.published_v : 'Published') : null,
      p.gates ? h('span', {class: 'tag ' + (p.gates.fail ? 'err' : 'ok'), title: 'Review gates of the latest version'},
        p.gates.fail ? `${p.gates.fail} gate${p.gates.fail === 1 ? '' : 's'} failed` : `${p.gates.pass + p.gates.warn} gates passed`) : null,
      h('span', {class: 'spacer'}),
      h('span', {title: 'Made by'}, icon('user'), ' ' + (p.made_by ? 'Former member' : p.via === 'owner' ? 'You' : (p.owner || '-'))),   // who made each one
      p.visibility ? h('span', {title: {private: 'Private', team: 'Shared with its team', org: 'Everyone in the organisation can view'}[p.visibility]},
        icon(p.visibility === 'private' ? 'lock' : p.visibility === 'org' ? 'globe' : 'users')) : null,
      h('span', {}, ago(p.updated || p.created))));
}
function renderDashboards() {
  const scope = S.scope || 'all';
  const ps = S.projects.filter(p => inScope(p, scope));
  const count = f => ps.filter(f).length;
  const yours = count(p => STATUS[p.status] && STATUS[p.status][1] === 'you'), running = count(p => RUN.has(p.status));
  const filter = S.hfilter || 'all';
  const keep = p => (filter === 'all' || (filter === 'you' && STATUS[p.status] && STATUS[p.status][1] === 'you') || (filter === 'run' && RUN.has(p.status))
    || (filter === 'pub' && p.published)) && (!S.hq || `${p.name} ${p.prompt || ''}`.toLowerCase().includes(S.hq.toLowerCase()));
  const shownCards = () => { const list = ps.filter(keep); return list.length ? list.map(card)
    : [h('div', {class: 'muted', style: 'padding:8px 2px'}, 'No dashboard matches. ', h('a', {href: '#/d2d', onclick: e => { e.preventDefault(); S.hq = ''; S.hfilter = 'all'; renderDashboards(); }}, 'Show all'))]; };
  const card = dashCard;
  $('#main').replaceChildren(h('div', {class: 'page'},
    h('div', {class: 'row'}, h('div', {}, h('div', {class: 'eyebrow'}, 'D2D - Data to Decision'), h('h1', {}, 'Dashboards'), h('div', {class: 'muted', style: 'margin-top:4px'},
      'Describe what you need - Relay builds the data model, KPIs and report, and a Power BI file (.pbix) you can open in Desktop.'),
      platformChips('Built for')),
      h('span', {class: 'spacer'}), S.me && !S.me.builder || !S.projects.length ? null : h('a', {class: 'btn primary', href: '#/new'}, icon('plus'), 'New dashboard')),
    S.projects.some(p => p.via && p.via !== 'owner') ? h('div', {class: 'segbtn', style: 'margin-top:14px'}, SCOPES.map(([k, l]) =>
      h('button', {class: k === scope ? 'on' : '', onclick: () => { S.scope = k; renderDashboards(); }}, l + ` (${S.projects.filter(p => inScope(p, k)).length})`))) : null,
    ps.length ? h('div', {class: 'stats', role: 'group', 'aria-label': 'Show dashboards'},
      [['all', ps.length, 'dashboards', ''], ['you', yours, 'waiting for you', yours ? 'color:var(--you)' : ''],
       ['run', running, 'in progress', running ? 'color:var(--run)' : ''], ['pub', count(p => p.published), 'published to Power BI', '']].map(([k, n, label, style]) =>
        h('button', {class: 'stat sbtn' + (filter === k ? ' on' : ''), type: 'button', 'aria-pressed': String(filter === k), title: k === 'all' ? 'Show all' : `Show only: ${label}`,
          onclick: () => { S.hfilter = filter === k ? 'all' : k; renderDashboards(); }}, h('b', {style}, n), h('span', {}, label)))) : null,
    typeof creditsLine === 'function' ? creditsLine() : null,      // D2D Relay: credits left (36-org.js); AI costs stay on the server
    ps.length > 3 ? h('div', {class: 'row hsearch'}, (() => {
      const q = h('input', {type: 'search', placeholder: 'Search dashboards by name or request', value: S.hq || '', 'aria-label': 'Search dashboards'});
      q.oninput = () => { S.hq = q.value; const g = $('#hgrid'); if (g) g.replaceChildren(...shownCards()); };
      return q; })(), filter !== 'all' ? h('button', {class: 'btn sm', onclick: () => { S.hfilter = 'all'; renderDashboards(); }}, icon('x'), 'Clear filter') : null) : null,
    ps.length ? h('div', {class: 'grid', id: 'hgrid'}, shownCards())
      : S.projects.length ? h('div', {class: 'card empty'}, h('h3', {}, 'Nothing here'), h('div', {}, 'No dashboard matches this view.'))
      : h('div', {class: 'card empty dempty'}, h('span', {class: 'dempty-i'}, icon('chart')), h('h3', {}, 'Your dashboards will be here'),     // item 88
          h('div', {class: 'muted'}, 'Each one: its plan, the review team\'s checks, the prototype and the Power BI file. Home has the steps to get started.'),
          h('div', {class: 'row', style: 'justify-content:center;gap:10px;margin-top:14px'},
            S.me && !S.me.builder ? null : h('a', {class: 'btn primary', href: '#/new'}, icon('plus'), 'Start your first dashboard'),
            h('a', {class: 'btn', href: '#/'}, icon('home'), 'Go to Home')))));
  if (false) api('/api/reviews').then(r => {          // D2D Relay: no review pages
 if (!r.reviews.length || !isDash()) return;
    $('#main .page').insertBefore(h('div', {class: 'banner you'}, h('div', {class: 'txt'}, h('div', {class: 't'}, `${r.reviews.length} dashboard version${r.reviews.length === 1 ? '' : 's'} waiting for your review`),
      h('div', {class: 'd'}, r.reviews.map(x => h('a', {href: `#/p/${x.project}`, style: 'margin-right:12px'}, `${x.name} v${x.v}`))))), $('#main .page').children[1]); }).catch(() => {});
}

/* Item 86 (the user, 2026-11-19: "can you add all approved custom visual as library to view only in the d2d site as well,
   so user can get an idea"): the Relay custom visuals of this release, tested and approved (item 69), drawn live on
   sample data with their variants and looks, view only (nothing to download): the gallery (custom_visuals/atlas/
   gallery.html, served at /gallery to signed-in people) inside the app. */
function renderVisualGallery() {             // not renderLibrary: 05-library.js has that (#/library, an organisation's own visuals)
  /* the user, 2026-11-19: "relay visual instead on new tab and all, can you make it part of D2D itself": a D2D page with
     D2D's own toolbar (search, kind, category, look, Reset), pinned on top, driving the framed gallery through its
     d2dGallery API (main.gallery); the gallery shows only its visuals and follows D2D's light or dark */
  document.title = 'Relay Visual - D2D Relay';
  const frame = h('iframe', {class: 'rv-frame', src: '/gallery', title: 'Relay Visual'});
  const G = () => { try { return frame.contentWindow && frame.contentWindow.d2dGallery; } catch (e) { return null; } };
  const q = h('input', {type: 'search', placeholder: 'Search visuals: sankey, drill, target', 'aria-label': 'Search visuals'});
  const kind = h('select', {class: 'sel', 'aria-label': 'Kind of visual'},
    [['all', 'All visuals'], ['builtin', "Power BI's built-in visuals"], ['custom', 'Custom visuals']].map(([v, t]) => h('option', {value: v}, t)));
  const cat = h('select', {class: 'sel', 'aria-label': 'Category'}, h('option', {value: ''}, 'Every category'));
  const count = h('span', {class: 'small muted', role: 'status'}, 'Loading the visuals...');
  const look = h('div', {class: 'segbtn', role: 'group', 'aria-label': 'Look'}, ['Flat', 'Soft', '3D'].map(l =>
    h('button', {type: 'button', class: l === 'Soft' ? 'on' : '', onclick: e => { const g = G(); if (g) g.press(l);
      [...look.children].forEach(b => b.classList.toggle('on', b === e.currentTarget)); }}, l)));
  const fillCats = () => { const g = G(); if (!g) return; const keep = cat.value;
    cat.replaceChildren(h('option', {value: ''}, 'Every category'), ...g.categories(kind.value).map(([id, name]) => h('option', {value: id}, name)));
    cat.value = [...cat.options].some(o => o.value === keep) ? keep : ''; };
  const apply = () => { const g = G(); if (!g) return; const n = g.apply(kind.value, cat.value); count.textContent = `${n} ${n === 1 ? 'visual' : 'visuals'} shown`; };
  kind.onchange = () => { fillCats(); apply(); const g = G(); if (g) g.jump(''); };
  cat.onchange = () => { apply(); const g = G(); if (g) g.jump(cat.value); };
  let t = null;
  q.oninput = () => { clearTimeout(t); t = setTimeout(() => { const g = G(); if (g) g.search(q.value.trim()); }, 250); };
  const reset = h('button', {class: 'btn sm', type: 'button', title: 'All visuals, every category, no search'}, icon('x'), 'Reset');
  reset.onclick = () => { q.value = ''; kind.value = 'all'; fillCats(); cat.value = ''; const g = G(); if (g) { g.search(''); apply(); g.jump(''); } };
  const theme = () => { const g = G(); if (g) g.press({dark: 'Dark', light: 'Light'}[document.documentElement.dataset.theme] || 'Auto'); };
  frame.addEventListener('load', () => { let n = 0;
    const wait = () => { const g = G(); if (g && g.ready()) { fillCats(); apply(); theme(); } else if (n++ < 75) setTimeout(wait, 200); }; wait(); });
  if (S.rvTheme) S.rvTheme.disconnect();
  S.rvTheme = new MutationObserver(() => { if (frame.isConnected) theme(); else S.rvTheme.disconnect(); });
  S.rvTheme.observe(document.documentElement, {attributes: true, attributeFilter: ['data-theme']});
  $('#main').replaceChildren(h('div', {class: 'page wide rv-page'},
    h('div', {class: 'rv-head'}, h('img', {src: '/relay-visual-mark.svg', alt: '', width: 40, height: 40}),
      h('div', {}, h('h1', {}, 'Relay Visual'), h('div', {class: 'small muted'}, 'Every visual a dashboard can use, Power BI\'s built-in ones and '
        + 'the custom ones, drawn live on sample data: hover a chart to see its values. View only.')),
      h('span', {class: 'spacer'}), platformChips('Visuals for')),
    h('div', {class: 'rv-bar', role: 'search'}, h('label', {class: 'rv-search'}, icon('search'), q), kind, cat, look, reset, count),
    frame));
}

/* Item 88 (the user, 2026-11-19: "dashboards can look more better as well and there should be a home page as well"):
   Home, the front page (#/): a greeting, the organisation's credits, the BI platforms, the Start here guide until the
   first dashboard is published, quick actions (New dashboard only once the guide is done: its button starts the first
   one) and the latest dashboards, as cards (the Dashboards page lists them all). */
function renderD2DHome() {          // not renderHome: 19-home.js (RELAY) has one
  document.title = 'Home - D2D Relay';
  const o = ORG() || {}, first = ((S.me || {}).name || '').trim().split(/\s+/)[0];
  const hr = new Date().getHours(), hello = hr < 12 ? 'Good morning' : hr < 17 ? 'Good afternoon' : 'Good evening';
  const ps = [...S.projects].sort((a, b) => (b.updated || b.created || 0) - (a.updated || a.created || 0));
  const guide = homeJourney(S.projects), builder = !(S.me && S.me.builder === false);
  const tile = (href, ic, title, text) => h('a', {class: 'qtile', href}, h('span', {class: 'qi'}, icon(ic)), h('b', {}, title), h('span', {class: 'small muted'}, text));
  $('#main').replaceChildren(h('div', {class: 'page home'},
    h('div', {class: 'homehead'}, h('div', {}, h('div', {class: 'eyebrow'}, o.name || 'D2D - Data to Decision'), h('h1', {}, first ? `${hello}, ${first}` : hello),
      h('div', {class: 'muted', style: 'margin-top:4px'}, 'Describe what you need: Relay Model builds the data model, KPIs and report, checks every number and hands you a Power BI file.'),
      platformChips('Built for'))),
    typeof creditsLine === 'function' ? creditsLine() : null,
    guide,
    h('div', {class: 'section-title'}, h('h2', {}, 'Quick actions')),
    h('div', {class: 'qtiles'},
      !guide && builder ? tile('#/new', 'plus', 'New dashboard', 'Name it, add your data and say what it should answer.') : null,
      tile('#/askd', 'spark', 'Ask Relay', 'Questions about your data, answered with charts.'),
      tile('#/review', 'scale', 'Semantic Review', 'Check Power BI models against your KPI standard.'),
      tile('#/visuals', 'grid', 'Relay Visual', 'Every visual a dashboard can use, drawn live.'),
      tile('#/ontology', 'layers', 'Ontology', 'Your business terms and KPI dictionary.'),
      tile('#/connections', 'plug', 'Connections', 'Warehouses, the Power BI service and GitHub.')),
    ps.length ? [h('div', {class: 'section-title'}, h('h2', {}, 'Latest dashboards'), h('span', {class: 'spacer'}), h('a', {href: '#/d2d', class: 'small'}, `All dashboards (${ps.length})`)),
      h('div', {class: 'grid'}, ps.slice(0, 4).map(dashCard))] : null));
}
