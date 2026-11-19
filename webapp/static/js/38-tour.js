/* ---------------- D2D Relay: the tour (#/welcome). Since 2026-11-19 a guided walk over the app itself (the user: "take
   tour should explain all like how to use and all in a guide way ... have quick actions like what they want to do",
   "like a callout, background dim and focused on what to do with next/skip", "a full guide on how to build dashboard,
   kpi configuration, ask relay using, semantic review, ontology, relay visual"). The screen dims, one part of it is lit,
   and a callout says what it is and what to do there, with Next, Back and Skip. It opens with what the person wants to
   do: a guide for each of those (it opens the pages and lights each part in turn), or a walk through everything.
   Shown once to someone new when they open the front page (tourAfterMe); finished or skipped it is not shown on its own
   again (POST /api/me/tour), and Take the tour (above the foot of the menu, and in the organisation menu) opens it again.
   A new organisation's setup (item 81, #/setup, 47-setup.js) is still needed before its first dashboard: while it is
   open, an owner's walk-through ends there, and the front page sends the owner on to it. Home is drawn under the tour;
   the tour is a layer over the page (#coach), so the pages a guide opens draw as usual underneath. ---------------- */
const TOUR = {step: 0};                                          // kept for older callers
const TOUR_LANDING = ['', '#', '#/', '#/d2d', '#/new'];        // a link to anything else (a shared dashboard) opens as asked
const tourSetupOpen = (o = ORG()) => !!(o.setup && !o.setup.done && o.setup.status !== 'done');     // item 81
const COACH = {open: false, flow: '', i: 0, steps: [], meta: null, seq: 0, drawer: false, timer: null, raf: 0, sample: null};
const TOUR_GUIDES = ['build', 'kpis', 'ask', 'review', 'ontology', 'visuals'];

/* after /api/me: someone new, or a new organisation's main owner, opening the front page gets the tour; a main owner
   who has seen it goes on with the organisation setup until it is finished (item 81) */
function tourAfterMe(me) {
  const o = (me && me.org) || {};
  if (!me || COACH.open || !TOUR_LANDING.includes(location.hash)) return;
  if (me.tour || (o.setup_needed && o.is_owner && !o.setup)) location.hash = '#/welcome';
  else if (o.setup_needed && o.is_owner && tourSetupOpen(o)) location.hash = '#/setup';
}

function renderTour() {
  if (location.hash.startsWith('#/setup') && typeof renderSetup === 'function') return renderSetup();   // item 81: the organisation setup
  if (COACH.open && COACH.sample && typeof tourSample === 'function') {                                // a guide's sample page (48-samples.js)
    document.title = 'Take the tour - D2D Relay';
    return tourSample(COACH.sample);
  }
  renderD2DHome();                                               // Home under the tour (03-home.js)
  document.title = 'Take the tour - D2D Relay';
  if (!COACH.open) coachStart('welcome');
}

/* ---------------- what the tour says: the walk through everything, and a guide for each task ---------------- */
const navAt = href => `.side .nav a[href="${href}"]`;
const cardAt = title => () => [...document.querySelectorAll('#main .card')]
  .find(c => { const t = c.querySelector('h2, h3'); return t && t.textContent.trim().startsWith(title); });

function tourFlows() {
  const o = ORG(), me = S.me || {}, org = o.name || 'your organisation', owner = !!o.is_owner, open = tourSetupOpen(o);
  const first = String(me.name || '').trim().split(/\s+/)[0] || '';
  const dom = o.id ? atDomains(o) : '';
  const list = items => h('ol', {class: 'howto coach-howto'}, items.map(([b, t]) => h('li', {}, h('div', {}, h('b', {}, b + ' '), t))));
  const looks = () => {                                          // light, dark or the device's own setting (02-shell.js setTheme)
    const box = h('div', {class: 'coach-looks', role: 'radiogroup', 'aria-label': 'How D2D Relay looks'});
    const draw = pick => box.replaceChildren(...[['light', 'Light'], ['dark', 'Dark'], ['system', 'Match my device']].map(([id, name]) =>
      h('button', {type: 'button', class: 'btn sm' + (pick === id ? ' primary' : ''), role: 'radio', 'aria-checked': String(pick === id),
        onclick: () => { setTheme(id); draw(id); }}, pick === id ? icon('check') : null, name)));
    draw(themeChoice());
    return box;
  };
  const setupStep = {at: '.homejourney', route: '#/', optional: true,
    title: owner ? `Set up ${org} first` : `${org} is being set up`,
    text: owner ? 'Your business, its KPI standard, business terms and brand, in a few short steps: Relay Model drafts each one from your '
        + 'industry and your answers, and you check it. It is needed before the first dashboard; fine-tune any of it later.'
      : `An owner of ${org} is setting up its business context, KPIs, terms and brand. Dashboards can be started once it is finished.`};
  const atWork = {title: 'Your KPIs at work', extra: () => list([
    ['In every plan.', 'A new dashboard takes its KPIs from your standard: at Confirm KPIs you check each one and how it is worked out, before anything is built.'],
    ['In Semantic Review.', 'Your Power BI models are checked against your KPIs: one KPI, one meaning, one value.'],
    ['In your ontology.', 'Your KPIs sit with your business terms, and every plan, answer and review uses them.']])};

  const cost = k => (typeof costOf === 'function' ? costOf(k) : 0) || {dashboard: 25, dashboard_custom: 50, change: 10, ask: 10, kpi: 1, fix: 1}[k];
  const plural = n => `${n} credit${n === 1 ? '' : 's'}`;
  const base = cost('dashboard'), more = Math.max(0, cost('dashboard_custom') - base), kpi = cost('kpi'), fix = cost('fix');
  const sampleNote = 'Here is a sample, filled in: nothing in it is saved or charged.';
  // the user, 2026-11-19: guides show sample pages, filled in (48-samples.js), after the place where the task starts
  const guides = {
    build: {title: 'Build a dashboard', icon: 'plus', blurb: 'From your data to a Power BI file',
      done: open ? (owner ? [`Set up ${org} first`, '#/setup'] : ['Go to Home', '#/']) : ['Start building', '#/new', () => { const n = $('#nd-name'); if (n) n.focus(); }],
      steps: [
        {at: '#newbtn', title: 'Start with New dashboard', text: `Every dashboard starts from this button: six short steps, then Relay plans and builds it with you. ${sampleNote}`},
        {sample: 'nd-0', at: '.tsample .ts-name', title: '1. Name', text: 'Give the dashboard a name your colleagues will know, like Retail performance 2026.'},
        {sample: 'nd-1', at: '.tsample .ts-files', title: '2. Your data', text: 'Bring CSV files, let Relay generate demo data, or import a DAWB hand-off (.zip). Each file is checked as it arrives: its rows and its columns.'},
        {sample: 'nd-1', at: '.tsample .ts-next', title: 'Credits are taken here', text: `Going on from Your data takes ${plural(base)} for the dashboard, with Power BI's built-in visuals. They are not refunded; going back, or coming back later, takes nothing more.`},
        {sample: 'nd-2', at: '.tsample .ts-prompt', title: '3. What to build', text: 'Say in your own words who it is for and what it should answer.'},
        {sample: 'nd-2', at: '.tsample .ts-ideas', title: 'Ideas from your data', text: 'Relay suggests what to show from the columns it found in your files.'},
        {sample: 'nd-3', at: '.tsample .ts-theme', title: '4. Theme', text: `${org}'s brand: its palette and fonts, set once under Branding and used by every new dashboard.`},
        {sample: 'nd-4', at: '.tsample .nd-choice', title: '5. Visuals', text: `Power BI's built-in visuals are included. Custom visuals (Relay's own, or both) take ${plural(more)} more when you go on, not refunded.`},
        {sample: 'nd-5', at: '.tsample .ts-sum', title: '6. Check and start', text: 'Everything you chose, and the credits already taken: starting uses no more. Relay plans first.'},
        {sample: 'nd-kpis', at: '.tsample .ts-kpis', title: 'Confirm KPIs', text: `Relay proposes the KPIs and how each one is worked out, from your KPI standard. Change one in your own words (${plural(kpi)}), then confirm: nothing is built before you agree.`},
        {sample: 'nd-proto', at: '.tsample .ts-proto', title: 'The prototype', text: 'Version 1 with your data, every number checked. Ask for changes in your own words until it is right.'},
        {sample: 'nd-proto', at: '.tsample .ts-protoact', title: 'Your Power BI file', text: 'Download the .pbix with its data, or publish it to the Power BI service once it is connected under Connections.'}]},
    kpis: {title: 'Set up your KPIs', icon: 'target', blurb: 'Your KPI standard and formulas',
      done: owner ? (open ? ['Set up now', '#/setup'] : ['Open the KPI standard', '#/setup?step=kpis']) : ['Open the Ontology', '#/ontology'],
      steps: [
        owner ? {at: navAt('#/org'), title: 'Your KPIs start with your organisation', text: `${org}'s KPI standard is part of its setup: Organisation, then Business context. ${sampleNote}`}
          : {at: navAt('#/ontology'), title: 'Your KPIs', text: `${org}'s KPIs and business terms are in its ontology; its owners set the KPI standard. ${sampleNote}`},
        {sample: 'kpi-std', at: '.tsample .ts-kgroup.first', title: 'The KPI standard', text: 'Relay Model drafts it from your industry and your business: each KPI with its formula and which way is good, grouped by area. You keep the ones that fit.'},
        {sample: 'kpi-std', at: '.tsample .ts-kfind', title: 'Find a KPI', text: 'Look a KPI up by name. Keep all and Drop all work on the whole list.'},
        {sample: 'nd-kpis', at: '.tsample .ts-kchange', title: 'Change a KPI in your own words', text: `In a dashboard's plan, say what you mean, like "Net sales should leave out staff discounts", and Relay rewrites the formula: ${plural(kpi)} a change.`},
        atWork]},
    ask: {title: 'Ask Relay', icon: 'spark', blurb: 'Questions about your data, in plain words',
      done: ['Ask a question', '#/askd', () => { const t = $('#askinput'); if (t) t.focus(); }],
      steps: [
        {at: navAt('#/askd'), title: 'Ask Relay', text: `Ask about your data in your own words and get a number, a table or a chart back. It answers from your dashboards' data. ${sampleNote}`},
        {sample: 'ask', at: '.tsample .ts-q', title: 'Ask in your own words', text: 'Like: which region grew fastest this year? No formulas and no column names.'},
        {sample: 'ask', at: '.tsample .ts-answer', title: 'The answer', text: 'A short answer, the table behind it and a chart, worked out with your KPIs.'},
        {sample: 'ask', at: '.tsample .ts-compose', title: 'Ask the next question', text: `Follow up in the same conversation. ${plural(cost('ask'))} pay for ${(o.costs || {}).ask_questions || 5} questions.`}]},
    review: {title: 'Semantic Review', icon: 'scale', blurb: 'Check Power BI models against your KPIs', done: ['Start a review', '#/review'],
      steps: [
        {at: navAt('#/review'), title: 'Semantic Review', text: `One KPI, one meaning, one value: Relay checks your Power BI models against your KPI dictionary, and against each other. ${sampleNote}`},
        {sample: 'review', at: '.tsample .ts-tiles', title: 'The result at a glance', text: 'How many KPIs were checked, and how many agree, differ or are missing.'},
        {sample: 'review', at: '.tsample .ts-differs', title: 'What differs, and why', text: 'Each finding names the model and its formula, and what makes it match your dictionary.'},
        {sample: 'review', at: '.tsample .ts-fixbtn', title: 'Fix it', text: `Relay makes the fix in the model for you: ${plural(fix)} a finding.`}]},
    ontology: {title: 'Ontology', icon: 'layers', blurb: 'Your business terms and industry pack', done: ['Open the Ontology', '#/ontology'],
      steps: [
        {at: navAt('#/ontology'), title: 'Ontology', text: `${org}'s business language: what each word and each KPI means in your business. ${sampleNote}`},
        {sample: 'onto', at: '.tsample .ts-pack', title: 'Start from your industry', text: 'An industry pack holds the business terms and KPIs a business like yours uses; change them to fit.'},
        {sample: 'onto', at: '.tsample .ts-terms', title: 'Business terms', text: 'What each word means, and where it is in your data. New data is read with these words, and plans, answers and reviews use them.'}]},
    visuals: {title: 'Relay Visual', icon: 'grid', blurb: 'Every visual a dashboard can use', done: ['Browse visuals', null],
      steps: [
        {at: navAt('#/visuals'), title: 'Relay Visual', text: 'Every visual a dashboard can use, Power BI\'s built-in ones and the Relay custom ones, drawn live on sample data. View only.'},
        {route: '#/visuals', at: '.rv-bar', title: 'Find a visual', text: 'Search by name or use (sankey, drill, target), pick built-in or custom and a category, and switch the look: Flat, Soft or 3D. Reset shows them all again.'},
        {route: '#/visuals', at: '.rv-frame', title: 'Live on sample data', text: 'Hover a chart to see its values; some let you drill down. A dashboard\'s Visuals step picks from these.'},
        {route: '#/visuals', at: '.rv-head .platforms', title: 'Power BI now, more soon', text: 'Tableau, Qlik, Metabase and Looker are coming soon.'}]}};

  const all = {title: 'The tour', done: owner && open ? [`Set up ${org}`, '#/setup'] : ['Done', null], steps: [
    {at: navAt('#/'), title: 'Home', text: 'Where you start: what to do next, your credits and your latest dashboards.'},
    open ? setupStep : null,
    {at: '#newbtn', title: 'New dashboard', text: 'Every dashboard starts here: name it, bring your data, say what to build, and Relay plans it with you, shows a prototype and gives you a Power BI file (.pbix).'},
    {at: navAt('#/d2d'), title: 'Dashboards', text: `Every dashboard in ${org}: where each one stands, its plan, its prototype and its files. Open one to carry on where it stopped.`},
    {at: navAt('#/askd'), title: 'Ask Relay', text: guides.ask.steps[0].text},
    {at: navAt('#/review'), title: 'Semantic Review', text: guides.review.steps[0].text},
    {at: navAt('#/ontology'), title: 'Ontology', text: `${org}'s business language: its industry, business terms and KPIs. Plans, answers and reviews all use it.`},
    {at: navAt('#/visuals'), title: 'Relay Visual', text: guides.visuals.steps[0].text},
    {at: navAt('#/migration'), title: 'Migration D2D', text: 'Moving from another BI tool? Dashboards move between Cognos, Qlik, Looker, Tableau, Power BI and more, with their numbers checked. PASDACS switches it on for you.'},
    {at: navAt('#/dawb'), title: 'DAWB, coming soon', text: 'The Data Analytics Work Bench: AI agents build and run your data pipelines and lakehouse, your people approve each step, and each finished build comes to D2D ready for dashboards.'},
    {at: navAt('#/org'), title: 'Organisation', text: owner ? `Your people, owners, credits and business context. Only the people you add can sign in to ${org}.`
      : `Who is in ${org}, its owners and its credits. Only the people its owners add can sign in.`},
    {at: navAt('#/branding'), title: 'Branding', text: `Your logo, palette and fonts: every report ${org} makes uses them.`},
    {at: navAt('#/connections'), title: 'Connections', text: 'The Power BI service and GitHub: publish finished dashboards to your workspace and keep them in your repository. An owner sets them up.'},
    {at: navAt('#/notifications'), title: 'Notifications', text: 'What happened while you were away: builds finished, credits added, requests answered. The bell at the top shows how many are new.'},
    {at: '#orgchip', optional: true, title: `${org} and its credits`, text: `Dashboards and questions use credits: ${costLine()}. Click here to buy or request more.`},
    {at: '#themebtn', title: 'Light or dark', text: 'How D2D looks on this device. Your reports keep your brand\'s colours.', extra: looks},
    {at: '#tourlink', title: 'Come back any time', text: 'Take the tour again from here, with a step-by-step guide for each part of D2D. Questions: info@pasdacs.com.'}].filter(Boolean)};

  const welcome = {title: 'Welcome', steps: [{wide: true,
    title: first ? `Welcome to D2D Relay, ${first}` : 'Welcome to D2D Relay',
    text: 'What would you like to do? Pick a guide: it opens each page and shows you what to do there, step by step. Or let the tour show you around.',
    extra: () => [
      open ? h('div', {class: 'coach-first'}, icon(owner ? 'target' : 'info'),
        h('div', {class: 'grow'}, h('b', {}, owner ? `First, set up ${org}` : `${org} is being set up`),
          h('div', {class: 'small muted'}, owner ? 'Your business, KPI standard, terms and brand: needed before the first dashboard.'
            : 'An owner is setting it up: dashboards can be started once it is finished.')),
        owner ? h('button', {class: 'btn primary sm', type: 'button', onclick: () => coachEnd('done', '#/setup')}, 'Set up now') : null) : null,
      h('div', {class: 'coach-acts'}, TOUR_GUIDES.map(k => h('button', {class: 'coach-act', type: 'button', onclick: () => coachRun(k)},
        icon(guides[k].icon), h('span', {}, h('b', {}, guides[k].title), h('small', {}, guides[k].blurb))))),
      o.id ? h('p', {class: 'coach-org'}, `${org}: ${credits(o.credits)} left. Who is in it: `
        + (owner ? 'the people you add under Organisation, People' : 'the people its owners add') + (dom ? ` (${dom} addresses).` : '.')) : null]}]};
  return {welcome, all, ...guides};
}

/* ---------------- the layer: a dimmed screen with one part lit (.coach-hole) and the callout (.coach-tip) ---------------- */
function coachStart(flow) {
  if (!COACH.open) {
    COACH.open = true;
    COACH.hole = h('div', {class: 'coach-hole none', 'aria-hidden': 'true'});
    COACH.tip = h('div', {class: 'coach-tip wait', role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': 'coach-title'});
    COACH.root = h('div', {class: 'coach', id: 'coach'}, COACH.hole, COACH.tip);
    document.body.append(COACH.root);
    document.addEventListener('keydown', coachKey, true);
    window.addEventListener('resize', coachMove);
    window.addEventListener('scroll', coachMove, true);
    COACH.timer = setInterval(() => coachPlace(false), 500);    // pages draw late and the menu redraws: keep the light on its part
    if (typeof ResizeObserver === 'function') { COACH.ro = new ResizeObserver(coachMove); COACH.ro.observe(COACH.tip); }   // a callout that grows stays on the screen
  }
  coachRun(flow || 'welcome');
}
const coachMove = () => { if (!COACH.raf) COACH.raf = requestAnimationFrame(() => { COACH.raf = 0; coachPlace(false); }); };

function coachRun(flow) {
  const F = tourFlows();
  COACH.flow = F[flow] ? flow : 'welcome';
  COACH.meta = F[COACH.flow];
  COACH.steps = COACH.meta.steps;
  coachShow(0, 1);
}

function coachFind(st) {
  let el = null;
  try { el = typeof st.at === 'function' ? st.at() : st.at ? document.querySelector(st.at) : null; } catch (e) { el = null; }
  return el && el.isConnected && el.getClientRects().length ? el : null;
}
const coachOnRoute = r => location.hash === r || (r === '#/' && ['', '#', '#/welcome'].includes(location.hash));

async function coachShow(i, dir) {
  const seq = ++COACH.seq, st = COACH.steps[i];
  if (!st) return;
  COACH.i = i;
  COACH.tip.classList.add('wait');
  const was = COACH.sample;
  COACH.sample = st.sample || null;
  if (st.sample) {                                               // a sample page: on #/welcome, drawn by renderTour
    if (location.hash !== '#/welcome') location.hash = '#/welcome';
    else if (was !== st.sample || !$('#main .tsample')) tourSample(st.sample);
  } else {
    if (was && location.hash === '#/welcome') renderD2DHome();   // back from a sample: Home under the tour again
    if (st.route && !coachOnRoute(st.route)) location.hash = st.route;
  }
  const t0 = Date.now(), limit = st.route || st.sample ? 5000 : 900;
  let el = coachFind(st);
  while (!el && st.at && Date.now() - t0 < limit) {               // the page a guide opens draws its parts after a moment
    await new Promise(r => setTimeout(r, 120));
    if (seq !== COACH.seq || !COACH.open) return;
    el = coachFind(st);
  }
  if (!el && st.at && st.optional) {                             // not on this page for this person: the next step
    const k = i + dir;
    if (k >= 0 && k < COACH.steps.length) return coachShow(k, dir);
  }
  coachDraw();
  coachPlace(true);
  COACH.tip.classList.remove('wait');
  const go = COACH.tip.querySelector('.coach-go');
  if (go) { try { go.focus({preventScroll: true}); } catch (e) { go.focus(); } }
}

function coachDraw() {
  const st = COACH.steps[COACH.i], M = COACH.meta, n = COACH.steps.length, last = COACH.i === n - 1, hello = COACH.flow === 'welcome';
  const done = M.done || ['Done', null];
  const btn = (cls, label, fn) => h('button', {class: 'btn sm ' + cls, type: 'button', onclick: fn}, label);
  const go = hello ? btn('primary coach-go', 'Show me around', () => coachRun('all'))
    : last ? btn('primary coach-go', done[0], () => coachEnd('done', done[1], done[2]))
    : btn('primary coach-go', 'Next', () => coachShow(COACH.i + 1, 1));
  const back = hello ? null : btn('ghost', 'Back', () => (COACH.i ? coachShow(COACH.i - 1, -1) : coachRun('welcome')));
  const left = !hello && last ? btn('ghost', 'All guides', () => coachRun('welcome')) : btn('ghost coach-skip', 'Skip the tour', () => coachEnd(COACH.flow));
  const text = typeof st.text === 'function' ? st.text() : st.text;
  COACH.tip.classList.toggle('wide', !!st.wide);
  if (text) COACH.tip.setAttribute('aria-describedby', 'coach-text'); else COACH.tip.removeAttribute('aria-describedby');
  COACH.tip.replaceChildren(h('i', {class: 'coach-arrow'}),
    h('div', {class: 'coach-body'},
      hello ? null : h('div', {class: 'coach-count'}, `${M.title}: step ${COACH.i + 1} of ${n}`),
      hello ? null : h('div', {class: 'coach-bar', 'aria-hidden': 'true'}, h('i', {style: `width:${Math.round((COACH.i + 1) / n * 100)}%`})),
      h('h3', {id: 'coach-title'}, st.title),
      text ? h('p', {class: 'coach-text', id: 'coach-text'}, text) : null,
      st.extra ? st.extra() : null),
    h('div', {class: 'coach-foot'}, left, h('span', {class: 'spacer'}), back, go));
}

/* the lit part and the callout beside it: right of the menu, else below, above or left of the part; a part too big to
   sit beside (a page's main card, the gallery) gets the callout over its foot; on a phone the callout sits at the top or
   the foot of the screen, away from the part, and the menu opens as a drawer while the tour points into it */
function coachPlace(scroll) {
  if (!COACH.open || !COACH.tip) return;
  const st = COACH.steps[COACH.i];
  if (!st) return;
  const tip = COACH.tip, hole = COACH.hole, arrow = tip.querySelector('.coach-arrow');
  const W = document.documentElement.clientWidth, H = window.innerHeight, M = 12, G = 14, P = 6;
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(v, Math.max(lo, hi)));
  const el = coachFind(st);
  let r = null;
  if (el) {
    if (el.closest('.side')) {
      const q = el.getBoundingClientRect();
      if ((q.right <= 0 || q.left >= W) && !COACH.drawer) {
        COACH.drawer = true; setDrawer(true);
        setTimeout(() => { coachPlace(true); const g = tip.querySelector('.coach-go'); if (g) g.focus({preventScroll: true}); }, 360);
      }
    } else if (COACH.drawer) { COACH.drawer = false; setDrawer(false); }
    if (scroll) {
      const q = el.getBoundingClientRect();
      if (q.top < 64 || q.bottom > H - 16) el.scrollIntoView({block: q.height > H * 0.6 ? 'start' : 'center'});
    }
    r = el.getBoundingClientRect();
    if (r.right <= 0 || r.left >= W || (!r.width && !r.height)) r = null;
  } else if (COACH.drawer) { COACH.drawer = false; setDrawer(false); }
  hole.classList.toggle('none', !r);
  COACH.root.classList.toggle('center', !r);                      // nothing lit: the whole screen dims (a hole of no size draws no shade)
  if (r) Object.assign(hole.style, {left: `${r.left - P}px`, top: `${r.top - P}px`, width: `${r.width + 2 * P}px`, height: `${r.height + 2 * P}px`});
  else Object.assign(hole.style, {left: `${W / 2}px`, top: `${H / 2}px`, width: '0px', height: '0px'});
  const tw = tip.offsetWidth, th = tip.offsetHeight;
  let x, y, side = '';
  if (!r) { x = (W - tw) / 2; y = (H - th) / 2; }
  else if (W < 640) { x = (W - tw) / 2; y = r.top + r.height / 2 > H / 2 ? M : H - th - M; }
  else if (r.right + P + G + tw + M <= W) { side = 'right'; x = r.right + P + G; y = clamp(r.top + r.height / 2 - th / 2, M, H - th - M); }
  else if (r.bottom + P + G + th + M <= H) { side = 'bottom'; y = r.bottom + P + G; x = clamp(r.left + r.width / 2 - tw / 2, M, W - tw - M); }
  else if (r.top - P - G - th >= M) { side = 'top'; y = r.top - P - G - th; x = clamp(r.left + r.width / 2 - tw / 2, M, W - tw - M); }
  else if (r.left - P - G - tw >= M) { side = 'left'; x = r.left - P - G - tw; y = clamp(r.top + r.height / 2 - th / 2, M, H - th - M); }
  else { x = clamp(r.left + r.width / 2 - tw / 2, M, W - tw - M); y = H - th - M; }
  tip.style.left = `${Math.round(clamp(x, M, W - tw - M))}px`;
  tip.style.top = `${Math.round(clamp(y, M, H - th - M))}px`;
  if (!arrow) return;
  arrow.className = 'coach-arrow' + (side ? ' ' + side : '');
  arrow.style.top = arrow.style.left = '';
  if (side === 'right' || side === 'left') arrow.style.top = `${clamp(r.top + r.height / 2 - y - 7, 12, th - 26)}px`;
  if (side === 'top' || side === 'bottom') arrow.style.left = `${clamp(r.left + r.width / 2 - x - 7, 12, tw - 26)}px`;
}

function coachKey(e) {
  if (!COACH.open) return;
  const tip = COACH.tip;
  if (e.key === 'Escape') { e.preventDefault(); e.stopImmediatePropagation(); coachEnd(COACH.flow); return; }
  if ((e.key === 'ArrowRight' || e.key === 'ArrowLeft') && COACH.flow !== 'welcome') {
    e.preventDefault(); e.stopImmediatePropagation();
    const k = COACH.i + (e.key === 'ArrowRight' ? 1 : -1);
    if (k >= 0 && k < COACH.steps.length) coachShow(k, k > COACH.i ? 1 : -1);
    return;
  }
  if (e.key === 'Tab') {                                          // the keyboard stays in the callout
    const f = [...tip.querySelectorAll('button, a[href]')].filter(x => !x.disabled && x.offsetParent !== null);
    if (!f.length) return;
    const a = f[0], z = f[f.length - 1], at = document.activeElement;
    if (!tip.contains(at)) { e.preventDefault(); a.focus(); }
    else if (e.shiftKey && at === a) { e.preventDefault(); z.focus(); }
    else if (!e.shiftKey && at === z) { e.preventDefault(); a.focus(); }
    return;
  }
  if (!tip.contains(e.target)) e.stopImmediatePropagation();      // the page under the tour is shown, not used
}

function coachClose() {
  if (!COACH.open) return;
  COACH.open = false; COACH.seq++; COACH.sample = null;
  clearInterval(COACH.timer);
  if (COACH.ro) { COACH.ro.disconnect(); COACH.ro = null; }
  document.removeEventListener('keydown', coachKey, true);
  window.removeEventListener('resize', coachMove);
  window.removeEventListener('scroll', coachMove, true);
  if (COACH.root) COACH.root.remove();
  if (COACH.drawer) { COACH.drawer = false; setDrawer(false); }
}

/* finished ('done') or skipped (the guide it was in): not shown on its own again; an owner whose organisation still
   needs its setup goes on to it from the welcome or the walk-through (item 81) */
async function coachEnd(how, then, after) {
  const o = ORG(), here = location.hash, flow = COACH.flow;
  coachClose();
  const to = then || (o.is_owner && tourSetupOpen(o) && (flow === 'welcome' || flow === 'all') ? '#/setup' : here === '#/welcome' ? '#/' : null);
  try {
    await api('/api/me/tour', {json: {step: how}});
    // item 81: with the guided setup, only once it is finished (POST /api/org/profile/done marks it too): marking it
    // earlier, with a brand set, could count the organisation as set up before its business context is saved
    if (o.setup_needed && o.is_owner && (!o.setup || o.setup.done)) { await api('/api/org/setup', {method: 'POST'}); S.me.org.setup_needed = false; }
  } catch (e) { notify(e.message, 'err'); }
  if (S.me) S.me.tour = false;
  if (how !== 'done') notify('Take the tour again any time: Take the tour, at the foot of the menu.', 'ok');
  if (to && location.hash === here && to !== here) location.hash = to;     // unless the person went somewhere else meanwhile
  if (after) setTimeout(after, 800);
}
