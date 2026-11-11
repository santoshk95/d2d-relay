/* ---------------- Relay: the dashboards list (#/d2d) ---------------- */
const SCOPES = [['all', 'All'], ['mine', 'Mine'], ['shared', 'Shared with me']];
const inScope = (p, scope) => scope === 'mine' ? p.via === 'owner' : scope === 'shared' ? !['owner', 'admin'].includes(p.via) : true;
function renderDashboards() {
  const scope = S.scope || 'all';
  const ps = S.projects.filter(p => inScope(p, scope));
  const count = f => ps.filter(f).length;
  const yours = count(p => STATUS[p.status] && STATUS[p.status][1] === 'you'), running = count(p => RUN.has(p.status));
  const how = h('div', {class: 'card'}, h('h3', {}, 'How it works'), h('div', {class: 'how'},
    [['1 · Describe', 'Upload CSVs — or let Relay generate realistic demo data — and say what the dashboard should answer. Add a picture of a design you like.'],
     ['2 · Confirm the plan', 'Relay proposes the data model, KPIs with formulas and pages; you edit and confirm.'],
     ['3 · Review', 'Relay builds a clickable prototype from your data. Ask for changes until it is right.'],
     ['4 · Review gates', "Every version passes Power Query, data, DAX in Power BI's own engine, Microsoft's report schemas, best-practice, accessibility and display checks — before you approve and again before publishing."],
     ['5 · Published', 'Download the Power BI file (.pbix) with its data, ready to open in Power BI Desktop.']].map(([t, d]) => h('div', {}, h('b', {}, t), d))));
  const filter = S.hfilter || 'all';
  const keep = p => (filter === 'all' || (filter === 'you' && STATUS[p.status] && STATUS[p.status][1] === 'you') || (filter === 'run' && RUN.has(p.status))
    || (filter === 'pub' && p.published)) && (!S.hq || `${p.name} ${p.prompt || ''}`.toLowerCase().includes(S.hq.toLowerCase()));
  const shownCards = () => { const list = ps.filter(keep); return list.length ? list.map(card)
    : [h('div', {class: 'muted', style: 'padding:8px 2px'}, 'No dashboard matches. ', h('a', {href: '#/d2d', onclick: e => { e.preventDefault(); S.hq = ''; S.hfilter = 'all'; renderDashboards(); }}, 'Show all'))]; };
  const card = p => h('a', {class: 'dcard', href: '#/p/' + p.id},
    h('div', {class: 'row', style: 'gap:8px;align-items:flex-start'}, h('div', {class: 'n', style: 'flex:1'}, p.name),
      (S.pins || []).includes(p.id) ? h('span', {class: 'pinmark', title: 'Pinned to your sidebar'}, icon('pin')) : null, pill(p.status)),
    h('div', {class: 'p'}, p.prompt || ''),
    h('div', {class: 'f'}, h('span', {}, p.versions ? `${p.versions} version${p.versions === 1 ? '' : 's'}` : 'No versions yet'),
      p.pages ? h('span', {}, `${p.pages} pages · ${p.visuals} visuals`) : null,
      p.published ? h('span', {class: 'tag ok'}, icon('check'), p.published_v ? 'Published v' + p.published_v : 'Published') : null,
      p.gates ? h('span', {class: 'tag ' + (p.gates.fail ? 'err' : 'ok'), title: 'Review gates of the latest version'},
        p.gates.fail ? `${p.gates.fail} gate${p.gates.fail === 1 ? '' : 's'} failed` : `${p.gates.pass + p.gates.warn} gates passed`) : null,
      h('span', {class: 'spacer'}),
      p.via && p.via !== 'owner' && p.owner ? h('span', {title: 'Owner'}, icon('user'), ' ' + p.owner) : null,
      p.visibility ? h('span', {title: {private: 'Private', team: 'Shared with its team', org: 'Everyone in the organisation can view'}[p.visibility]},
        icon(p.visibility === 'private' ? 'lock' : p.visibility === 'org' ? 'globe' : 'users')) : null,
      h('span', {}, ago(p.updated || p.created))));
  $('#main').replaceChildren(h('div', {class: 'page'},
    h('div', {class: 'row'}, h('div', {}, h('div', {class: 'eyebrow'}, 'D2D · Data to Dashboard'), h('h1', {}, 'Dashboards'), h('div', {class: 'muted', style: 'margin-top:4px'},
      'Describe what you need — Relay builds the data model, KPIs and report, and a Power BI file (.pbix) you can open in Desktop.')),
      h('span', {class: 'spacer'}), S.me && !S.me.builder ? null : h('a', {class: 'btn primary', href: '#/new'}, icon('plus'), 'New dashboard')),
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
    ps.length ? h('div', {class: 'grid', id: 'hgrid'}, shownCards()) : h('div', {class: 'card empty'}, h('h3', {}, 'No dashboards yet'),
      h('div', {}, 'Start with your CSV files and a sentence about what the dashboard should answer.'),
      h('div', {style: 'margin-top:14px'}, h('a', {class: 'btn primary', href: '#/new'}, icon('plus'), 'New dashboard'))),
    S.projects.length <= 2 ? h('div', {style: 'margin-top:20px'}, how) : null));        // onboarding only
  if (false) api('/api/reviews').then(r => {          // D2D Relay: no review pages
 if (!r.reviews.length || !isDash()) return;
    $('#main .page').insertBefore(h('div', {class: 'banner you'}, h('div', {class: 'txt'}, h('div', {class: 't'}, `${r.reviews.length} dashboard version${r.reviews.length === 1 ? '' : 's'} waiting for your review`),
      h('div', {class: 'd'}, r.reviews.map(x => h('a', {href: `#/p/${x.project}`, style: 'margin-right:12px'}, `${x.name} v${x.v}`))))), $('#main .page').children[1]); }).catch(() => {});
}
