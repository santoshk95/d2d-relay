/* ---------------- D2D Relay: the organisation setup (item 81, #/setup; app/orgsetup.py). The user, 2026-11-19: "make
   the intial configuration and business/org context mandate ... it must be a guided way". An organisation's owners set
   it up once, before its first dashboard, one step at a time: Your business (the context), Prepare (Relay Model drafts
   it from the industry pack and the context, or the industry standard as it is), Understanding, KPI standard (into the
   KPI dictionary), Ontology and dictionaries (business terms), Theme (the brand: Branding drawn inside, 35-branding.js)
   and Check and finish; then they fine-tune it any time. #/setup?step=<id> opens a step (08-boot.js notes it; 38-tour.js
   hands #/setup here); everyone else sees what the owners set. Until it is finished New dashboard (04-new.js) and a new
   Semantic Review (40-review.js) show setupNotice(), and the Organisation page (36-org.js) has setupOrgCard().
   Every rule is the server's: this file only shows it. Styles: css/setup.css (su-*). ---------------- */
const SU_STEPS = [
  ['context', 'Your business', 'Tell Relay about your business once: every plan, build and answer starts from it.'],
  ['prepare', 'Prepare', "Relay Model drafts your setup from your industry's standard and your answers, or you start from the standard as it is."],
  ['understanding', 'Understanding', 'What Relay understood about your business. Correct anything, then accept it: it goes into every plan and build.'],
  ['kpis', 'KPI standard', 'The KPIs your reports are held to. Keep the ones that fit: they go into your KPI dictionary.'],
  ['terms', 'Ontology and dictionaries', 'The business terms Relay reads your data with, and your own names for them. Keep the ones that fit: they go into your ontology.'],
  ['theme', 'Theme', 'Your brand: the palette and fonts every report uses.'],
  ['finish', 'Check and finish', 'Everything in one view. Change any part, then finish: dashboards can be started after that.']];
const SU_MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
const SU_KINDS = [['measure', 'Measures'], ['key', 'Keys'], ['date', 'Dates'], ['attribute', 'Attributes']];
const SU = {seq: 0, timer: null, ask: '', packs: {}};      // packs: an industry pack's KPI and term names, to say what is standard

/* 08-boot.js: the step asked for in #/setup?step=<id>, noted before the address becomes #/setup */
function setupAt(hash) { SU.ask = (String(hash || '').match(/[?&]step=([a-z]+)/) || [])[1] || ''; }

/* ---------------- small helpers ---------------- */
const suFill = (el, ...kids) => { el.replaceChildren(...kids.flat(Infinity).filter(k => k != null && k !== false)); return el; };   // never "null" as text
const suList = v => (Array.isArray(v) ? v : typeof v === 'string' && v.trim() ? [v] : []).map(x => String(x == null ? '' : x).trim()).filter(Boolean);
const suSplit = (text, lines) => String(text || '').split(lines ? /\n+/ : /[,;\n]+/).map(x => x.trim()).filter(Boolean);
const suN = (n, one, many) => `${Number(n || 0).toLocaleString()} ${Number(n) === 1 ? one : many || one + 's'}`;
const suMonth = m => SU_MONTHS[Math.min(12, Math.max(1, Number(m) || 1)) - 1];
const suDate = t => { if (!t) return ''; if (Date.now() / 1000 - t < 86400) return ago(t); const d = new Date(t * 1000); return `${d.getDate()} ${SU_MONTHS[d.getMonth()].slice(0, 3)} ${d.getFullYear()}`; };
const suClip = (s, n) => { s = String(s || '').replace(/\s+/g, ' ').trim(); return s.length > n ? s.slice(0, n).replace(/\s+\S*$/, '') + '...' : s; };
const suOpt = x => x && typeof x === 'object' ? [String(x.code || x.id || x.kind || x.value || ''), String(x.label || x.name || x.code || x.id || x.value || '')] : [String(x), String(x)];
const suIndustry = (P, id) => id ? ((P.industries || []).find(x => x.id === id) || {}).name || id : '';
const suCalText = (P, c) => {                 // as the server words a time basis (orgsetup.calendar_words)
  if (!c || !c.kind) return '';
  if (c.kind === 'calendar') return ((P.calendars || []).find(x => x.kind === 'calendar') || {}).label || 'Calendar year (January to December)';
  return c.kind === 'fiscal' ? `Fiscal year starting 1 ${suMonth(c.start_month)}` : `Retail ${c.kind} weeks, the year starting in ${suMonth(c.start_month)}`;
};
const suCanEdit = (o = ORG()) => { const s = o.setup || {}; return s.can_edit != null ? !!s.can_edit : !!o.is_owner; };
const suStyle = b => (b && (b.style || (b.chosen != null && b.variants ? b.variants[b.chosen] : null))) || null;
const suReady = b => !!b && (b.ready != null ? !!b.ready : !!suStyle(b));
const suLook = v => [v.look === '3d' ? '3D look' : v.look ? `${v.look[0].toUpperCase()}${v.look.slice(1)} look` : '', v.dark ? 'dark background' : 'light background'].filter(Boolean).join(', ');
/* the organisation's setup in /api/me, kept in step with what the server last said */
function suSync(P) {
  if (S.me && S.me.org && P && P.status) S.me.org.setup = {...(S.me.org.setup || {}), status: P.status, done: P.status === 'done', can_edit: !!P.can_edit, next: P.next || null};
}
/* rows of a definition list; a list value is a bulleted list, a long text keeps its lines */
function suKv(rows) {
  const keep = rows.filter(r => Array.isArray(r[1]) ? r[1].length : r[1]);
  return h('dl', {class: 'kv su-kv'}, keep.map(([t, v, pre]) => [h('dt', {}, t),
    h('dd', {class: pre ? 'su-pre' : null}, Array.isArray(v) ? h('ul', {}, v.map(x => h('li', {}, x))) : String(v))]));
}
const suContextRows = (P, c) => [['Industry', suIndustry(P, c.industry)], ['What the business does', c.about, true],
  ['Brands or banners', suList(c.brands).join(', ')], ['Divisions or regions', suList(c.regions).join(', ')], ['Currency', c.currency],
  ['Fiscal calendar', suCalText(P, c.calendar)], ['Who reads the reports', suList(c.audiences).join(', ')],
  ['What matters most', typeof c.priorities === 'string' ? c.priorities : suList(c.priorities).join('\n'), true], ['Naming conventions', c.conventions, true]];
const suUnderRows = u => [['In short', u.summary, true], ['What the business does', u.business, true],
  ['Brands or banners', suList(u.brands).join(', ')], ['Divisions or regions', suList(u.regions).join(', ')],
  ['Calendar', typeof u.calendar === 'string' ? u.calendar : ''], ['Currency', typeof u.currency === 'string' ? u.currency : ''],
  ['Who reads the reports', suList(u.audiences).join(', ')], ['What matters most', suList(u.priorities)], ['What Relay assumed', suList(u.assumptions)]];
/* the brand in use, as New dashboard's Theme step shows it (newdash.css nd-theme) */
function suBrandBox(b) {
  const v = suStyle(b);
  if (!v) return h('div', {class: 'small muted'}, 'No palette yet.');
  const font = b.font || 'Segoe UI', head = b.heading_font || font, cols = v.colors || [];
  const inFont = (el, n, title) => typeof brandFont === 'function' ? brandFont(el, n, title) : el;
  return h('div', {class: 'nd-theme'},
    b.logo ? h('div', {class: 'nd-logo'}, h('img', {src: b.logo, alt: 'Your logo'})) : null,
    h('div', {class: 'nd-tinfo'},
      h('div', {}, h('b', {}, v.name || 'Your palette'), h('span', {class: 'muted small'}, ` - ${suLook(v)}`)),
      h('div', {class: 'nd-sws', role: 'img', 'aria-label': 'Palette colours: ' + cols.join(', ')}, cols.map(c => h('i', {class: 'nd-sw', style: `background:${c}`, title: c}))),
      h('div', {class: 'small'}, 'Fonts: ', inFont(h('b', {}, font), font),
        head !== font ? [' for text and numbers, ', inFont(h('b', {}, head), head, true), ' for titles'] : ' for titles, text and numbers')));
}

/* ---------------- until the organisation is set up (/api/me org.setup), new dashboards and new reviews wait; the
   server refuses them too (400). what: 'dashboard' or 'review'. onReady: when a fresh /api/me says it is done. ---------------- */
function setupPending() {
  const s = typeof ORG === 'function' ? ORG().setup : null;
  return !!(s && s.status !== 'done' && !s.done);
}
function setupWhy() {
  if (!setupPending()) return '';
  const o = ORG();
  return suCanEdit(o) ? 'Finish setting up your organisation first: use Finish the setup, above.'
    : `${o.name || 'Your organisation'} is still being set up: an owner finishes it first.`;
}
function setupNotice(what, onReady) {
  if (!setupPending()) return null;
  const o = ORG(), edit = suCanEdit(o), review = what === 'review';
  const el = h('div', {class: 'note warn su-gate', role: 'status'},
    h('div', {class: 'su-gtext'}, edit
      ? [h('b', {}, 'Finish setting up your organisation first. '), review
        ? 'Semantic Review checks your models against your KPI standard and business terms: set them up once, it takes a few minutes.'
        : 'Relay plans every dashboard with your business context, KPI standard, business terms and brand: set them up once, it takes a few minutes.']
      : [h('b', {}, `${o.name || 'Your organisation'} is still being set up. `), `An owner finishes it, and then ${review ? 'reviews' : 'dashboards'} can be started.`]),
    edit ? h('a', {class: 'btn sm primary', href: '#/setup'}, icon('play'), 'Finish the setup') : null);
  if (typeof refreshOrg === 'function') refreshOrg(true).then(() => { if (el.isConnected && !setupPending()) { if (onReady) onReady(); else el.remove(); } });
  return el;
}

/* ---------------- the Organisation page's "Business context" card (36-org.js) ---------------- */
function setupOrgCard() {
  const tag = h('span'), body = h('div', {}, h('div', {class: 'small muted'}, 'Loading...'));
  const card = h('div', {class: 'card su-orgcard'}, h('div', {class: 'row su-ochead'}, h('h3', {}, 'Business context'), tag), body);
  api('/api/org/profile').then(P => {
    if (P.personal) return card.remove();
    const o = ORG(), edit = !!P.can_edit, done = P.status === 'done', c = P.context || {}, u = P.understanding || {}, d = P.dictionary;
    const [tone, text] = done && (!P.legacy || P.context) ? ['ok', 'Set up'] : P.legacy ? ['', 'Business context to add']
      : P.status === 'draft' ? ['warn', 'Being set up'] : ['warn', 'Not set up yet'];
    suFill(tag, h('span', {class: 'tag ' + tone}, text));
    const short = u.summary || c.about || '';
    suFill(body,
      short ? h('p', {class: 'su-short'}, suClip(short, 280))
        : h('p', {class: 'small muted su-short'}, edit ? 'Tell Relay about your business once: every plan, build and answer starts from it.' : `An owner of ${o.name || 'your organisation'} sets it up.`),
      suKv([['Industry', suIndustry(P, c.industry)], ['Currency', c.currency], ['Fiscal calendar', suCalText(P, c.calendar)],
        ['Brands or banners', suList(c.brands).join(', ')], ['Divisions or regions', suList(c.regions).join(', ')],
        ['KPI dictionary', d ? suN(d.kpis, 'KPI') : ''], ['Business terms', d ? suN(d.terms, 'term') : '']]),
      h('div', {class: 'row su-ocact'}, h('a', {class: 'btn sm' + (edit && !done ? ' primary' : ''), href: '#/setup'}, icon(edit ? (done ? 'edit' : 'play') : 'book'),
        edit ? (done ? 'Review and fine-tune' : 'Finish the setup') : 'See what is set up')));
  }).catch(e => suFill(body, h('div', {class: 'note err'}, e.message)));
  return card;
}

/* ---------------- #/setup ---------------- */
async function renderSetup() {
  clearTimeout(SU.timer);
  const seq = ++SU.seq, ask = SU.ask || (location.hash.match(/[?&]step=([a-z]+)/) || [])[1] || '';
  SU.ask = '';
  const here = () => seq === SU.seq && location.hash.startsWith('#/setup');
  document.title = 'Organisation setup - D2D Relay';
  $('#main').replaceChildren(typeof skel === 'function' ? skel('page') : h('div', {class: 'page'}));
  let P;
  try { P = await api('/api/org/profile'); }
  catch (e) {
    if (here()) $('#main').replaceChildren(h('div', {class: 'page su-page'}, h('h1', {}, 'Organisation setup'), h('div', {class: 'note err'}, e.message),
      h('button', {class: 'btn', type: 'button', onclick: () => renderSetup()}, 'Try again')));
    return;
  }
  if (!here()) return;
  if (P.personal) return suPersonal();
  suSync(P);
  return P.can_edit ? suWizard(P, ask, here) : suReadOnly(P);
}

function suHead(P, edit) {
  const set = P.status === 'done';            // finished, or an organisation from before this guide (legacy)
  return [h('div', {class: 'crumbs'}, h('a', {href: '#/org'}, 'Organisation'), h('span', {'aria-hidden': 'true'}, '>'), h('span', {}, 'Setup')),
    h('h1', {}, set || !edit ? `${ORG().name || 'Your organisation'}: business context` : `Set up ${ORG().name || 'your organisation'}`),
    h('div', {class: 'muted su-meta'}, !edit ? "What your organisation's owners set up. Every plan and build uses it."
      : set ? 'Your business, its KPI standard, business terms and brand. Every plan and build uses them: change any part here.'
      : 'Once, before the first dashboard: your business, a KPI standard, business terms and your brand. Relay Model drafts them from your industry; you check and fine-tune each part, and every plan and build uses them.')];
}

function suPersonal() {
  $('#main').replaceChildren(h('div', {class: 'page su-page'}, h('h1', {}, 'Organisation setup'),
    h('div', {class: 'note'}, 'A personal workspace needs no organisation setup: dashboards can be started at once.'),
    h('p', {class: 'small muted'}, 'Your brand is under ', h('a', {href: '#/branding'}, 'Branding'), '; your business terms and KPI dictionary are under ',
      h('a', {href: '#/ontology'}, 'Ontology'), '.')));
}

/* everyone who is not an owner: what the owners set, or that an owner is setting it up */
function suReadOnly(P) {
  const org = ORG().name || 'Your organisation', done = P.status === 'done', d = P.dictionary || {};
  const theme = h('div', {class: 'card'}, h('h3', {}, 'Theme'), h('div', {class: 'small muted'}, 'Loading...'));
  $('#main').replaceChildren(h('div', {class: 'page su-page su-ro'}, suHead(P, false),
    h('div', {class: 'note ' + (done ? 'ok' : 'warn')}, done ? `${org} is set up. Its owners fine-tune it; every plan and build uses it.`
      : `An owner of ${org} is setting it up. Dashboards can be started once it is finished.`),
    P.context ? h('div', {class: 'card'}, h('h3', {}, 'Your business'), suKv(suContextRows(P, P.context))) : null,
    P.understanding && Object.keys(P.understanding).length ? h('div', {class: 'card'}, h('h3', {}, 'What Relay understood'), suKv(suUnderRows(P.understanding))) : null,
    h('div', {class: 'card'}, h('h3', {}, 'KPI standard and business terms'),
      h('p', {class: 'small', style: 'margin-top:0'}, `${suN(d.kpis, 'KPI')} in the KPI dictionary and ${suN(d.terms, 'business term')} in the ontology.`),
      h('div', {class: 'row'}, h('a', {class: 'btn sm', href: '#/ontology/kpis'}, icon('book'), 'KPI dictionary'), h('a', {class: 'btn sm', href: '#/ontology/terms'}, icon('layers'), 'Business terms'))),
    theme));
  api('/api/branding').then(b => { if (theme.isConnected) suFill(theme, h('h3', {}, 'Theme'), suReady(b) ? suBrandBox(b) : h('div', {class: 'small muted'}, `${org} has no brand yet: an owner sets it.`)); },
    () => theme.remove());
}

/* ---------------- the owners' guided setup ---------------- */
function suWizard(P0, ask, here) {
  let P = P0, cur = 0, busy = false, brand = null, brandErr = '';
  const org = ORG().name || 'your organisation', ids = SU_STEPS.map(s => s[0]);
  const name = id => (SU_STEPS.find(s => s[0] === id) || ['', id])[1];
  const st = () => P.steps || {};
  const running = () => !!(P.job && P.job.status === 'running');
  const themeOk = () => brand ? suReady(brand) : !!P.theme_ready;
  const reach = () => (P.status === 'done' && !P.legacy) || !P.next ? ids.length - 1 : Math.max(0, ids.indexOf(P.next));
  const doneOf = id => id === 'context' ? !!st().context : id === 'prepare' ? !!P.proposal : id === 'theme' ? themeOk() : id === 'finish' ? !!P.done : !!st()[id];
  const say = msg => { const el = document.getElementById('su-live'); if (el) el.textContent = msg; };
  const lbl = (text, id, small) => h('label', {class: 'f', for: id}, text, small ? h('small', {}, small) : null);
  const errs = SU_STEPS.map(() => h('div', {class: 'err-msg su-err', role: 'alert'}));
  const bodies = SU_STEPS.map(() => h('div', {class: 'su-body'}));
  const secs = SU_STEPS.map(([, title, lead], i) => h('section', {class: 'su-step', hidden: true, 'aria-labelledby': `su-h${i}`},
    h('div', {class: 'su-kicker'}, `Step ${i + 1} of ${SU_STEPS.length}`), h('h2', {class: 'su-h', id: `su-h${i}`, tabindex: '-1'}, title),
    h('p', {class: 'su-lead'}, lead), bodies[i], errs[i]));

  /* ---- 1: your business (the context form) */
  const C = P.context || {}, cal0 = C.calendar || {};
  const indSel = h('select', {class: 'sel', id: 'su-ind'}, h('option', {value: ''}, 'Choose your industry'),
    (P.industries || []).map(x => h('option', {value: x.id, selected: x.id === C.industry}, x.name)));
  const indHint = h('div', {class: 'hint'}), indWarn = h('div'), savedLine = h('div', {class: 'small muted su-src'});
  const drawInd = () => {
    const x = (P.industries || []).find(y => y.id === indSel.value), was = (P.context || {}).industry;
    indHint.textContent = !x ? 'Its standard KPIs and business terms are where your setup starts.'
      : [x.description, x.terms != null && x.kpis != null ? `Its standard: ${suN(x.terms, 'business term')} and ${suN(x.kpis, 'KPI')}.` : ''].filter(Boolean).join(' ');
    savedLine.textContent = P.saved && st().context ? `Saved ${suDate(P.saved)}${P.saved_by ? ' by ' + P.saved_by : ''}.` : '';
    suFill(indWarn, was && indSel.value && indSel.value !== was ? h('div', {class: 'note warn'}, `Saving adds ${x ? x.name : 'that industry'}'s business terms and KPIs to your ontology (what you have stays as it is)`
      + (P.proposal ? ', and the draft you have is dropped: you prepare it again next.' : '.')) : null);
  };
  indSel.onchange = drawInd;
  // item 92 (the user, 2026-11-19: "whoever first signs in org, they will put the meta data of the organisation like
  // name"): an organisation that signed up is named from its email domain until its owner names it here
  const nameIn = h('input', {type: 'text', id: 'su-orgname', maxlength: '80', autocomplete: 'organization', value: ORG().name || '',
    placeholder: 'e.g. FreshWay Markets'});
  const about = h('textarea', {id: 'su-about', rows: 4, maxlength: '3000', placeholder: 'e.g. A regional grocery chain with 220 stores in 3 states: fresh food, pharmacy and fuel, with home delivery and store pickup.'});
  about.value = C.about || '';
  const aboutCount = h('div', {class: 'hint'});
  const drawCount = () => { const n = about.value.trim().length; aboutCount.textContent = n < 20 ? `At least 20 characters: ${20 - n} to go.` : `${n.toLocaleString()} of 3,000 characters.`; };
  about.addEventListener('input', drawCount);
  const textIn = (id, v, ph) => h('input', {type: 'text', id, maxlength: '600', autocomplete: 'off', placeholder: ph, value: v});
  const brandsIn = textIn('su-brands', suList(C.brands).join(', '), 'e.g. FreshWay, FreshWay Express, Daily Basket');
  const regionsIn = textIn('su-regions', suList(C.regions).join(', '), 'e.g. North, South, West, Online');
  const curSel = h('select', {class: 'sel', id: 'su-cur'}, (P.currencies || []).map(suOpt).map(([v, t]) => h('option', {value: v, selected: v === (C.currency || 'USD')}, t)));
  const calSel = h('select', {class: 'sel', id: 'su-cal'}, (P.calendars || []).map(c => h('option', {value: String(c.kind), selected: c.kind === (cal0.kind || 'calendar')}, String(c.label || c.kind))));
  const monSel = h('select', {class: 'sel', id: 'su-month'}, SU_MONTHS.map((m, i) => h('option', {value: String(i + 1), selected: i + 1 === (Number(cal0.start_month) || 1)}, m)));
  const monWrap = h('div', {}, lbl('The year starts in', 'su-month'), monSel);
  const drawCal = () => { monWrap.hidden = !calSel.value || calSel.value === 'calendar'; };
  calSel.onchange = drawCal;
  const audKnown = (P.audiences || []).map(a => suOpt(a)[1]).filter(Boolean), audHave = suList(C.audiences);
  const known = a => audKnown.some(k => k.toLowerCase() === a.toLowerCase());
  const audBoxes = audKnown.map(a => h('input', {type: 'checkbox', value: a, checked: audHave.some(x => x.toLowerCase() === a.toLowerCase())}));
  const audOther = textIn('su-aud-other', audHave.filter(a => !known(a)).join(', '), 'Others, separated by commas');
  audOther.setAttribute('aria-label', 'Other readers, separated by commas');
  const prio = h('textarea', {id: 'su-prio', rows: 4, maxlength: '3000', placeholder: 'e.g. Are we on plan this year, by division and store? Where is shrink rising? Which promotions pay back?'});
  prio.value = typeof C.priorities === 'string' ? C.priorities : suList(C.priorities).join('\n');
  const conv = h('textarea', {id: 'su-conv', rows: 3, maxlength: '3000', placeholder: 'e.g. sls = sales, str = store, upc = item barcode, wk = fiscal week'});
  conv.value = C.conventions || '';
  const ctxValue = () => ({industry: indSel.value, about: about.value.trim(), brands: suSplit(brandsIn.value), regions: suSplit(regionsIn.value),
    currency: curSel.value, calendar: {kind: calSel.value, start_month: calSel.value === 'calendar' ? 1 : Number(monSel.value) || 1},
    audiences: [...audBoxes.filter(b => b.checked).map(b => b.value), ...suSplit(audOther.value)], priorities: prio.value.trim(), conventions: conv.value.trim()});
  const ctxState = () => JSON.stringify([nameIn.value.trim(), ctxValue()]);
  let ctxSaved = ctxState();
  const ctxBody = [savedLine, lbl('Organisation name', 'su-orgname', 'as your people and your reports should name it'), nameIn,
    lbl('Industry', 'su-ind', 'its standard is where your setup starts'), indSel, indHint, indWarn,
    lbl('What the business does', 'su-about', 'what you sell, to whom, where'), about, aboutCount,
    h('div', {class: 'su-grid'}, h('div', {}, lbl('Brands or banners', 'su-brands', 'optional'), brandsIn), h('div', {}, lbl('Divisions or regions', 'su-regions', 'optional'), regionsIn)),
    h('div', {class: 'su-grid su-grid3'}, h('div', {}, lbl('Currency', 'su-cur'), curSel), h('div', {}, lbl('Fiscal calendar', 'su-cal'), calSel), monWrap),
    h('label', {class: 'f', id: 'su-aud-l'}, 'Who reads the reports', h('small', {}, 'pick any')),
    audKnown.length ? h('div', {class: 'su-auds', role: 'group', 'aria-labelledby': 'su-aud-l'}, audKnown.map((a, i) => h('label', {class: 'su-aud'}, audBoxes[i], h('span', {}, a)))) : null,
    audOther,
    lbl('The questions and decisions that matter most', 'su-prio', 'optional'), prio,
    lbl('Naming conventions in your data', 'su-conv', 'optional: the abbreviations your columns use'), conv,
    h('div', {class: 'hint'}, 'Relay reads your columns with them: str_sls_amt is then a store\'s sales.')];
  const ctxWhy = () => nameIn.value.trim().length < 2 ? 'Give your organisation its name.' : !indSel.value ? 'Choose your industry.' : about.value.trim().length < 20 ? 'Say what the business does in a sentence or two: at least 20 characters.' : '';
  async function saveContext() {
    const name = nameIn.value.trim().replace(/\s+/g, ' ');
    if (name && name !== (ORG().name || '')) {                       // item 92: renamed with the organisation's own PATCH
      await api('/api/org', {method: 'PATCH', json: {name}});
      if (S.me && S.me.org) S.me.org.name = name;
      if (typeof renderOrgChip === 'function') renderOrgChip();
    }
    P = await api('/api/org/profile/context', {method: 'PUT', json: ctxValue()});
    ctxSaved = ctxState(); suSync(P); drawInd();
    const ap = P.applied;                // a new industry: its pack's terms and KPIs went into the ontology
    if (ap && ap.pack) notify(`${ap.pack}: ${suN((ap.terms || {}).added, 'business term')} and ${suN((ap.kpis || {}).added, 'KPI')} added to your ontology.`, 'ok');
    say('Your business is saved.');
    return true;
  }

  /* ---- 2: prepare: Relay Model drafts it (in the background; polled every 3 s), or the industry standard at once */
  const prepBox = h('div');
  const drawPrepare = () => {
    const job = P.job || {}, run = running(), pr = P.proposal, left = P.generations_left, per = P.generations_per_day;
    const dropped = (pr && Array.isArray(pr.dropped) ? pr.dropped : []).filter(x => x && x.name);
    const ind = suIndustry(P, (P.context || {}).industry) || 'your industry';
    const counts = pr ? `an understanding of your business, ${suN((pr.kpis || []).length, 'KPI')} and ${suN((pr.terms || []).length, 'business term')}`
      + (Object.keys(pr.abbreviations || {}).length ? `, with ${suN(Object.keys(pr.abbreviations).length, 'abbreviation')} of yours` : '') : '';
    suFill(prepBox,
      run ? h('div', {class: 'su-prog', role: 'status'}, h('span', {class: 'spin'}), h('div', {},
        h('b', {}, 'Relay Model is reading your industry standard and your answers'),
        h('div', {class: 'small muted'}, (job.started ? `${dur(Math.max(0, Date.now() - job.started * 1000))} so far. ` : '') + 'It takes a minute or two. You can leave this page: the draft goes on.'))) : null,
      !run && job.status === 'error' ? h('div', {class: 'note err', role: 'alert'}, h('b', {}, 'Relay Model could not draft it. '),
        job.error || 'Try again, or use the industry standard as it is.') : null,
      pr && !run ? h('div', {class: 'note ok su-ready'}, icon('check'), h('span', {}, h('b', {}, pr.source === 'relay' ? 'Relay Model drafted it' : 'The industry standard is ready'),
        `${pr.made ? ' (' + suDate(pr.made) + ')' : ''}: ${counts}. Check each part next.`)) : null,
      pr && !run && dropped.length ? h('details', {class: 'su-more su-dropped'}, h('summary', {}, `${suN(dropped.length, 'item')} Relay Model proposed did not pass the checks`),
        h('ul', {}, dropped.map(x => h('li', {}, h('b', {}, String(x.name)), x.why ? ` - ${x.why}` : '')))) : null,
      h('div', {class: 'su-choice'},
        h('div', {class: 'su-opt' + (pr && pr.source === 'relay' ? ' on' : '')}, h('h3', {}, icon('spark'), 'Let Relay Model draft it'),
          h('p', {class: 'small muted'}, `Relay Model reads ${ind}'s standard and your answers, then proposes an understanding of your business, KPIs fitted to your priorities and business terms with your own names, each with why. Free; it takes a minute or two.`),
          h('div', {class: 'row su-optact'}, h('button', {class: 'btn' + (pr ? '' : ' primary'), type: 'button', id: 'su-gen', disabled: run || busy || left === 0, onclick: generate},
            icon('spark'), pr ? 'Draft it again' : 'Let Relay Model draft it'),
            left != null ? h('span', {class: 'small muted'}, left ? `${per ? `${left} of ${per}` : left} ${left === 1 && !per ? 'draft' : 'drafts'} left today`
              : 'No drafts left today: use the standard, or draft it again tomorrow.') : null)),
        h('div', {class: 'su-opt' + (pr && pr.source === 'standard' ? ' on' : '')}, h('h3', {}, icon('book'), 'Use the industry standard as it is'),
          h('p', {class: 'small muted'}, `${ind}'s KPIs and business terms as they are, with your abbreviations added as other names. No AI; ready at once.`),
          h('div', {class: 'row su-optact'}, h('button', {class: 'btn', type: 'button', id: 'su-std', disabled: run || busy, onclick: useStandard},
            icon('book'), pr && pr.source === 'standard' ? 'Start again from the standard' : 'Use the standard')))));
  };
  const replaceOk = async (title, ok) => !P.proposal || typeof confirmBox !== 'function'
    || confirmBox(title, 'It replaces the draft you have. What you already accepted stays in your KPI dictionary and ontology.', ok, false);
  async function generate() {
    if (busy || !await replaceOk('Draft it again?', 'Draft it again')) return;
    busy = true; errs[cur].textContent = ''; drawPrepare(); drawNav();
    let err = '';
    try { P = await api('/api/org/profile/generate', {method: 'POST'}); say('Relay Model is drafting your setup.'); }
    catch (e) { err = e.message; try { P = await api('/api/org/profile'); } catch (x) { /* keep what is shown */ } }
    busy = false;
    if (!here()) return;
    changed(); errs[cur].textContent = err;            // after changed(): its recheck() would take the server's words away
  }
  async function useStandard() {
    if (busy || !await replaceOk('Start again from the standard?', 'Use the standard')) return;
    busy = true; errs[cur].textContent = ''; drawPrepare(); drawNav();
    let err = '';
    try { P = await api('/api/org/profile/standard', {method: 'POST'}); notify('The industry standard is ready: check each part next.', 'ok'); }
    catch (e) { err = e.message; }
    busy = false;
    if (!here()) return;
    changed(); errs[cur].textContent = err;
  }
  function poll() {                     // while Relay Model drafts: the profile every 3 s, until the job is done or failed
    clearTimeout(SU.timer);
    if (!running()) return;
    SU.timer = setTimeout(async () => {
      if (!here()) return;
      let r;
      try { r = await api('/api/org/profile'); } catch (e) { return poll(); }     // the next round
      if (!here()) return;
      P = r;
      if (!running()) {
        if ((P.job || {}).status === 'error') notify('Relay Model could not draft it: see Prepare.', 'err');
        else if (P.proposal) notify("Relay Model's draft is ready: check each part next.", 'ok');
      }
      changed();
    }, 3000);
  }

  /* ---- 3: understanding: an editable form of its sections */
  const uBox = h('div');
  let uf = null, uSaved = '', uKey = null;
  const uNewer = () => !!(P.proposal && P.understanding && st().understanding && (P.proposal.made || 0) > st().understanding);
  const uValue = () => ({summary: uf.summary.value.trim(), business: uf.business.value.trim(), brands: suSplit(uf.brands.value), regions: suSplit(uf.regions.value),
    calendar: uf.calendar.value.trim(), currency: uf.currency.value.trim(), audiences: suSplit(uf.audiences.value),
    priorities: suSplit(uf.priorities.value, true), assumptions: suSplit(uf.assumptions.value, true)});
  function buildUnder(from) {
    const u = from || (st().understanding && P.understanding) || (P.proposal || {}).understanding || P.understanding || {};
    const ta = (id, rows, v, ph, max) => { const t = h('textarea', {id, rows, maxlength: String(max || 3000), placeholder: ph}); t.value = v || ''; return t; };
    const short = (el, max) => { el.setAttribute('maxlength', String(max)); return el; };    // the server's limits (orgsetup._clean_understanding)
    uf = {summary: ta('su-u-sum', 3, u.summary, 'Your business in one or two sentences', 600), business: ta('su-u-bus', 4, u.business, 'What it sells, to whom, where, and how'),
      brands: textIn('su-u-brands', suList(u.brands).join(', '), 'Separated by commas'), regions: textIn('su-u-regions', suList(u.regions).join(', '), 'Separated by commas'),
      calendar: short(textIn('su-u-cal', typeof u.calendar === 'string' ? u.calendar : '', 'e.g. Fiscal year from February, 4-5-4 weeks'), 200),
      currency: short(textIn('su-u-cur', typeof u.currency === 'string' ? u.currency : '', 'e.g. USD'), 60),
      audiences: textIn('su-u-aud', suList(u.audiences).join(', '), 'Separated by commas'),
      priorities: ta('su-u-prio', 4, suList(u.priorities).join('\n'), 'One a line'), assumptions: ta('su-u-ass', 3, suList(u.assumptions).join('\n'), 'One a line')};
    uSaved = from ? '' : JSON.stringify(uValue());
    const pr = P.proposal;
    suFill(uBox,
      h('div', {class: 'small muted su-src'}, from ? "Relay Model's newer draft: check it, then accept."
        : st().understanding ? `Accepted ${suDate(st().understanding)}. Change anything and accept it again.`
        : pr ? `From ${pr.source === 'relay' ? "Relay Model's draft" : 'the industry standard and your answers'}. Correct anything, then accept it.` : ''),
      !from && uNewer() ? h('div', {class: 'note row su-newer'}, h('span', {class: 'grow'}, `There is a newer draft (${suDate(pr.made)}).`),
        h('button', {class: 'btn sm', type: 'button', onclick: () => { buildUnder(pr.understanding || {}); drawNav(); }}, 'Use it')) : null,
      lbl('In short', 'su-u-sum'), uf.summary, lbl('What the business does', 'su-u-bus'), uf.business,
      h('div', {class: 'su-grid'}, h('div', {}, lbl('Brands or banners', 'su-u-brands'), uf.brands), h('div', {}, lbl('Divisions or regions', 'su-u-regions'), uf.regions)),
      h('div', {class: 'su-grid su-grid3 su-gu'}, h('div', {}, lbl('Calendar', 'su-u-cal'), uf.calendar), h('div', {}, lbl('Currency', 'su-u-cur'), uf.currency),
        h('div', {}, lbl('Who reads the reports', 'su-u-aud'), uf.audiences)),
      lbl('What matters most', 'su-u-prio', 'one a line'), uf.priorities,
      lbl('What Relay assumed', 'su-u-ass', 'one a line: correct or remove any that are wrong'), uf.assumptions);
  }
  const uWhy = () => !uf || (!uf.summary.value.trim() && !uf.business.value.trim()) ? 'Say in a sentence or two what the business is.' : '';
  async function saveUnder() {
    P = await api('/api/org/profile/understanding', {method: 'PUT', json: uValue()});
    suSync(P); uSaved = JSON.stringify(uValue());
    say('The understanding is accepted.');
    return true;
  }

  /* ---- 4 and 5: the proposed KPIs and business terms, kept or dropped one by one */
  const packOf = () => SU.packs[(P.context || {}).industry] || null;
  function needPack() {                 // a proposal without "from_pack" is told apart by the industry pack's own names
    const ind = (P.context || {}).industry, pr = P.proposal || {};
    if (!ind || SU.packs[ind] || [...(pr.kpis || []), ...(pr.terms || [])].every(x => Object.prototype.hasOwnProperty.call(x, 'from_pack'))) return;
    SU.packs[ind] = {loading: true, kpis: [], terms: []};
    api(`/api/ontology/packs/${encodeURIComponent(ind)}`).then(pk => { SU.packs[ind] = pk || {kpis: [], terms: []}; },
      () => { SU.packs[ind] = {failed: true, kpis: [], terms: []}; }).then(() => { if (here()) { K.draw(); T.draw(); } });
  }
  const origin = (x, kind) => {         // 'Industry standard', 'Adapted from <name>', 'New', or nothing while it is not known
    let f = null;
    if (Object.prototype.hasOwnProperty.call(x, 'from_pack')) f = x.from_pack ? String(x.from_pack) : '';
    else if ((P.proposal || {}).source === 'standard') f = String(x.name);
    else { const pk = packOf(); if (pk && !pk.loading && !pk.failed) f = (pk[kind] || []).some(y => String(y.name).toLowerCase() === String(x.name).toLowerCase()) ? String(x.name) : ''; }
    if (f == null) return null;
    return !f ? h('span', {class: 'tag acc'}, 'New') : h('span', {class: 'tag su-std'}, f.toLowerCase() === String(x.name).toLowerCase() ? 'Industry standard' : `Adapted from ${f}`);
  };
  const detail = rows => { const keep = rows.filter(r => r[1]); return keep.length ? h('dl', {}, keep.map(([t, v, mono]) => [h('dt', {}, t), h('dd', {class: mono ? 'mono' : null}, String(v))])) : null; };
  function picker(kind) {
    const isK = kind === 'kpis', noun = isK ? 'KPI' : 'term';
    const S2 = {keep: new Set(), touched: false, key: null, res: null};
    const list = () => (P.proposal || {})[kind] || [];
    const accepted = () => !!st()[kind] && st()[kind] >= ((P.proposal || {}).made || 0);
    const stat = h('span', {class: 'small muted su-stat', role: 'status'});
    const find = h('input', {type: 'text', class: 'su-find', autocomplete: 'off', placeholder: isK ? 'Find a KPI' : 'Find a term', 'aria-label': isK ? 'Find a KPI' : 'Find a business term',
      onkeydown: e => { if (e.key === 'Enter') e.preventDefault(); }});
    const items = h('div', {class: 'su-items'}), note = h('div'), abbr = h('div');
    // saving the business already added the industry pack's own KPIs and terms: by default these fitted versions replace them
    const replace = h('input', {type: 'checkbox', checked: true});
    const touch = () => { S2.touched = true; drawStat(); drawNav(); drawSteps(); };
    const all = h('button', {class: 'btn sm', type: 'button', onclick: () => { list().forEach(x => S2.keep.add(x.name)); touch(); draw(); }}, icon('check'), 'Keep all');
    const none = h('button', {class: 'btn sm ghost', type: 'button', onclick: () => { S2.keep.clear(); touch(); draw(); }}, 'Drop all');
    const drawStat = () => { const n = list().length; stat.textContent = n ? `${S2.keep.size} of ${n} kept` : ''; };
    const item = x => {
      const on = S2.keep.has(x.name), syn = suList(x.synonyms);
      const cb = h('input', {type: 'checkbox', checked: on, 'aria-label': `Keep ${x.name}`});
      const drop = h('span', {class: 'tag su-drop', hidden: on}, 'Dropped');
      const el = h('div', {class: 'su-item' + (on ? '' : ' off')},
        h('label', {class: 'su-keep'}, cb, h('span', {class: 'su-ith'}, h('b', {}, x.name), isK ? null : h('span', {class: 'semchip k-' + (x.kind || 'attribute')}, x.kind || 'attribute'),
          origin(x, kind), drop)),
        (isK ? x.definition : x.description) ? h('div', {class: 'su-def'}, isK ? x.definition : x.description) : null,
        !isK && syn.length ? h('div', {class: 'su-syn'}, h('span', {class: 'small muted'}, 'Other names:'), syn.map(s => h('code', {}, s))) : null,
        x.why ? h('div', {class: 'su-why'}, h('b', {}, 'Why: '), x.why) : null,
        (() => { const dl = isK ? detail([['Formula', x.formula], ['DAX', x.dax, true], ['Unit', x.unit], ['Adds up as', x.aggregation && String(x.aggregation).replace('_', ' ')],
          ['Time basis', x.time], ['Filters', suList(x.filters).join('; ')], ['Other names', syn.join(', ')], ['Owner', x.owner], ['Notes', x.notes]])
          : detail([['What it belongs to', x.entity], ['Unit', x.unit], ['Adds up as', x.aggregation && String(x.aggregation).replace('_', ' ')], ['Family', x.family]]);
          return dl ? h('details', {class: 'su-more'}, h('summary', {}, isK ? 'How it is worked out' : 'More about it'), dl) : null; })());
      cb.onchange = () => { if (cb.checked) S2.keep.add(x.name); else S2.keep.delete(x.name); el.classList.toggle('off', !cb.checked); drop.hidden = cb.checked; touch(); };
      return el;
    };
    const groupsOf = xs => {
      if (!isK) return [...SU_KINDS, ['', 'Other terms']].map(([k, t]) => [t, xs.filter(x => k ? x.kind === k : !SU_KINDS.some(y => y[0] === x.kind))]).filter(g => g[1].length);
      const m = new Map();
      xs.forEach(x => { const g = x.domain || 'Other KPIs'; if (!m.has(g)) m.set(g, []); m.get(g).push(x); });
      return [...m.entries()];
    };
    const draw = () => {
      const q = find.value.trim().toLowerCase(), xs = list();
      const shown = xs.filter(x => !q || [x.name, x.definition, x.description, x.domain, x.kind, x.why, ...suList(x.synonyms)].join(' ').toLowerCase().includes(q));
      suFill(items, shown.length ? groupsOf(shown).map(([g, ys]) => h('div', {class: 'su-group'}, h('h4', {}, g, h('span', {class: 'muted'}, ` (${ys.length})`)), ys.map(item)))
        : h('div', {class: 'muted small su-none'}, xs.length ? `No ${noun} matches "${find.value.trim()}".`
          : !P.proposal ? `There is no draft now (a new industry drops it): prepare one on Prepare to see the ${isK ? 'KPIs' : 'business terms'} it proposes, or accept to keep ${isK ? 'your KPI dictionary' : 'your terms'} as ${isK ? 'it is' : 'they are'}.`
          : isK ? 'No KPIs were proposed. Accept to keep your KPI dictionary as it is.' : 'No business terms were proposed. Accept to keep your terms as they are.'));
      all.disabled = none.disabled = !xs.length;
      find.hidden = xs.length < 8;
      drawStat();
    };
    const count = v => Array.isArray(v) ? v.reduce((a, x) => a + (x && Array.isArray(x.synonyms) ? x.synonyms.length : 1), 0) : Number(v) || 0;
    const result = r => `${suN(r.added, isK ? 'KPI' : 'business term')} added to your ${isK ? 'KPI dictionary' : 'ontology'}`
      + (r.replaced ? `, ${r.replaced} replaced with ${r.replaced === 1 ? 'its fitted version' : 'their fitted versions'}` : '')
      + (r.kept ? `, ${r.kept} already there kept as ${r.kept === 1 ? 'it is' : 'they are'}` : '')
      + (count(r.synonyms_added) ? `, your own names added to ${suN(count(r.synonyms_added), 'term')} you had` : '') + '.';
    const drawNote = () => {
      const r = S2.res, sk = (r && r.skipped) || [];
      suFill(note,
        r ? h('div', {class: 'note ' + (sk.length ? 'warn' : 'ok')}, h('b', {}, 'Accepted. '), result(r),
          sk.length ? [h('div', {class: 'su-skiph'}, h('b', {}, `${sk.length} left out:`)), h('ul', {}, sk.map(s => h('li', {}, h('b', {}, String(s.name || '')), s.why ? ` - ${s.why}` : '')))] : null) : null,
        accepted() ? h('div', {class: 'hint su-tune'}, isK
          ? ['Fine-tune them any time in ', h('a', {href: '#/ontology/kpis'}, 'your KPI dictionary'), ': edit a KPI, change it in words, add or remove one.']
          : ['Fine-tune them any time in ', h('a', {href: '#/ontology/terms'}, 'Business terms'), ': edit a term and the names it goes by, add or remove one.']) : null);
    };
    const drawAbbr = () => {
      const ab = Object.entries((P.proposal || {}).abbreviations || {});
      suFill(abbr, !isK && ab.length ? h('div', {class: 'su-abbr'}, h('div', {class: 'small'}, h('b', {}, 'Your abbreviations'),
        h('span', {class: 'muted'}, ': added as other names of the terms they stand for')),
        h('div', {class: 'su-abs'}, ab.map(([a, w]) => h('span', {class: 'su-ab'}, h('code', {}, a), ` = ${w}`)))) : null);
    };
    find.oninput = draw;
    const el = h('div', {}, abbr, h('div', {class: 'su-tools'}, all, none, stat, h('span', {class: 'spacer'}), find), items,
      h('label', {class: 'chk su-repl'}, replace, h('span', {}, isK
        ? 'Replace KPIs of the same name already in your dictionary with these (recommended: they fit your calendar, currency and names)'
        : 'Replace terms of the same name already in your ontology with these (recommended: they carry your own names)')), note);
    return {el, draw, keep: () => S2.keep.size,
      build() {
        const key = `${(P.proposal || {}).made || ''}:${list().length}`;
        if (key !== S2.key) { S2.key = key; S2.keep = new Set(list().map(x => x.name)); S2.touched = false; S2.res = null; find.value = ''; replace.checked = true; needPack(); }
        drawAbbr(); draw(); drawNote();
      },
      needs: () => !accepted() || S2.touched,
      label: () => S2.keep.size ? `Accept ${suN(S2.keep.size, noun)}` : isK ? 'Accept: keep the dictionary as it is' : 'Accept: keep the terms as they are',
      async save() {
        const accept = list().filter(x => S2.keep.has(x.name)).map(x => x.name);
        const r = await api(`/api/org/profile/${kind}`, {json: {accept, replace: replace.checked}});
        P = r; S2.res = r; S2.touched = false; suSync(P); drawNote();
        notify(result(r), 'ok');
        return !(r.skipped || []).length;          // what was left out stays on the screen, with why
      }};
  }
  const K = picker('kpis'), T = picker('terms');

  /* ---- 6: theme: the brand (35-branding.js), drawn inside for owners, as New dashboard's Theme step does */
  const thSum = h('div', {'aria-live': 'polite'}), thEdit = h('div', {class: 'nd-brand-edit su-brand-edit', hidden: true});
  let editing = false, editSeq = 0;
  async function loadBrand() {
    if (!brand && cur === ids.indexOf('theme')) suFill(thSum, h('div', {class: 'row', role: 'status'}, h('span', {class: 'spin'}), 'Loading your brand...'));
    try { brand = await api('/api/branding'); brandErr = ''; } catch (e) { brandErr = e.message; }
    if (!here()) return;
    drawTheme(); drawSteps(); drawNav();
    if (ids[cur] === 'finish') drawFinish();
  }
  function openEditor(open) {
    editing = open && typeof renderBranding === 'function';
    thEdit.hidden = !editing;
    if (editing) {
      const mine = ++editSeq, box = h('div');
      thEdit.replaceChildren(box);
      renderBranding({into: box, route: '#/setup', onChange: b => { if (mine === editSeq && b) { brand = b; brandErr = ''; drawTheme(); drawSteps(); drawNav(); recheck(); } }});
    } else thEdit.replaceChildren();
    drawTheme();
  }
  function drawTheme() {
    if (brandErr && !brand) return suFill(thSum, h('div', {class: 'err-msg', style: 'margin-top:0'}, brandErr),
      h('button', {type: 'button', class: 'btn sm', style: 'margin-top:8px', onclick: loadBrand}, 'Try again'));
    if (!brand) return;
    const edit = !!brand.may_edit;
    if (!suReady(brand)) {
      suFill(thSum, h('div', {class: 'note warn'}, h('b', {}, 'Set up your brand. '), 'Every dashboard is built in it: a palette and fonts. Pick them below (it takes a minute), or ',
        h('a', {href: '#/branding?return=setup'}, 'open Branding'), '.'));
      if (edit && !editing && ids[cur] === 'theme') openEditor(true);     // owners pick it right here
      return;
    }
    suFill(thSum, suBrandBox(brand),
      h('div', {class: 'row su-thact'}, edit ? h('button', {type: 'button', class: 'btn sm', 'aria-expanded': String(editing), onclick: () => openEditor(!editing)},
        icon(editing ? 'check' : 'edit'), editing ? 'Done' : 'Change it here') : null,
        h('a', {class: 'btn sm ghost', href: '#/branding?return=setup'}, icon('palette'), 'Open Branding')),
      h('div', {class: 'hint'}, 'Every new dashboard uses it. A change applies to the dashboards started after it.'));
  }
  const themeWhy = () => themeOk() ? '' : brand && !brand.may_edit ? 'An owner sets the brand first.' : 'Set up your brand first: pick a palette (and check the fonts), then go on.';

  /* ---- 7: check and finish */
  const finBox = h('div');
  function drawFinish() {
    const s = st(), pr = P.proposal, d = P.dictionary || {}, c = P.context, u = P.understanding || {}, v = brand ? suStyle(brand) : null;
    const rows = [
      ['context', c ? [suIndustry(P, c.industry), c.currency, suCalText(P, c.calendar)].filter(Boolean).join(' - ') : 'Not saved yet', c && c.about ? suClip(c.about, 160) : ''],
      ['prepare', running() ? 'Relay Model is drafting' : pr ? `${pr.source === 'relay' ? 'Drafted by Relay Model' : 'The industry standard'}${pr.made ? ', ' + suDate(pr.made) : ''}` : 'Not prepared yet',
        pr ? `${suN((pr.kpis || []).length, 'KPI')} and ${suN((pr.terms || []).length, 'business term')} proposed` : ''],
      ['understanding', s.understanding ? `Accepted ${suDate(s.understanding)}` : 'Not accepted yet', s.understanding && u.summary ? suClip(u.summary, 200) : ''],
      ['kpis', s.kpis ? `Accepted ${suDate(s.kpis)}` : 'Not accepted yet', P.dictionary ? `${suN(d.kpis, 'KPI')} in your KPI dictionary` : ''],
      ['terms', s.terms ? `Accepted ${suDate(s.terms)}` : 'Not accepted yet', P.dictionary ? `${suN(d.terms, 'business term')} in your ontology` : ''],
      ['theme', themeOk() ? (v ? v.name || 'Your palette' : 'Your brand is set') : 'No brand yet',
        v && themeOk() ? h('span', {class: 'nd-sws inl', role: 'img', 'aria-label': 'Palette colours: ' + (v.colors || []).join(', ')}, (v.colors || []).map(x => h('i', {class: 'nd-sw', style: `background:${x}`}))) : '']];
    const nx = P.next;
    suFill(finBox,
      h('div', {class: 'su-sum'}, rows.map(([id, line, more]) => {
        const i = ids.indexOf(id), ok = doneOf(id);
        return h('div', {class: 'su-sumrow' + (ok ? ' ok' : '')},
          h('span', {class: 'su-n', 'aria-hidden': 'true'}, ok ? icon('check') : String(i + 1)),
          h('div', {class: 'su-sumt'}, h('b', {}, name(id)), h('span', {class: 'tag ' + (ok ? 'ok' : 'warn')}, ok ? 'Done' : 'To do'), h('div', {class: 'small'}, line), more ? h('div', {class: 'small muted'}, more) : null),
          h('button', {class: 'btn sm ghost', type: 'button', disabled: i > reach(), 'aria-label': `Change: ${name(id)}`, onclick: () => go(i)}, 'Change'));
      })),
      !P.done && nx && nx !== 'finish' ? h('div', {class: 'note warn row su-left'}, h('span', {class: 'grow'}, `Finish opens once every step is done. Next to do: ${name(nx)}.`),
        h('button', {class: 'btn sm', type: 'button', onclick: () => go(ids.indexOf(nx))}, `Go to ${name(nx)}`)) : null,
      !P.done && nx === 'finish' ? h('p', {class: 'small muted su-fintext'}, `Finish marks ${org} as set up: everyone in it can start dashboards, and its people are told.`) : null);
  }
  async function finish() {
    if (busy || P.next !== 'finish') return;
    busy = true; errs[cur].textContent = ''; drawNav(); drawSteps();
    try {
      P = await api('/api/org/profile/done', {method: 'POST'});
      suSync(P);
      if (S.me && S.me.org) S.me.org.setup_needed = false;
      notify(`${ORG().name || 'Your organisation'} is set up: dashboards can be started.`, 'ok');
      if (typeof refreshOrg === 'function') refreshOrg(true);
      location.hash = '#/d2d';
    } catch (e) {
      busy = false;
      if (!here()) return;
      try { P = await api('/api/org/profile'); } catch (x) { /* keep what is shown */ }
      changed(); errs[cur].textContent = e.message;
    }
  }

  /* ---- the steps: what each needs before Next, what Next saves, how each is drawn */
  const STEP = {
    context: {why: ctxWhy, needs: () => !st().context || ctxState() !== ctxSaved, save: saveContext, label: 'Save and go on',
      draw: () => { if (!bodies[0].childElementCount) { suFill(bodies[0], ctxBody); drawInd(); drawCount(); drawCal(); } }},
    prepare: {why: () => running() ? 'Wait for Relay Model to finish the draft.' : !P.proposal ? 'Let Relay Model draft it, or use the industry standard, to go on.' : '',
      needs: () => false, draw: () => { if (!bodies[1].childElementCount) suFill(bodies[1], prepBox); drawPrepare(); }},
    understanding: {why: uWhy, needs: () => !st().understanding || !uf || JSON.stringify(uValue()) !== uSaved, save: saveUnder, label: 'Accept and go on',
      draw: () => {
        const key = `${st().understanding || ''}:${(P.proposal || {}).made || ''}`;
        if (!bodies[2].childElementCount) suFill(bodies[2], uBox);
        if (key !== uKey) { uKey = key; buildUnder(); }
      }},
    kpis: {why: () => '', needs: () => K.needs(), save: () => K.save(), label: () => K.label(), draw: () => { if (!bodies[3].childElementCount) suFill(bodies[3], K.el); K.build(); }},
    terms: {why: () => '', needs: () => T.needs(), save: () => T.save(), label: () => T.label(), draw: () => { if (!bodies[4].childElementCount) suFill(bodies[4], T.el); T.build(); }},
    theme: {why: themeWhy, needs: () => true, label: '', draw: () => { if (!bodies[5].childElementCount) suFill(bodies[5], thSum, thEdit); drawTheme(); loadBrand(); },
      save: async () => { P = await api('/api/org/profile'); suSync(P); return true; }},     // the server's word on the brand and what is next
    finish: {why: () => '', needs: () => false, draw: () => { if (!bodies[6].childElementCount) suFill(bodies[6], finBox); drawFinish(); }}};

  const stateOf = id => {
    const s = st(), pr = P.proposal, d = P.dictionary || {};
    if (id === 'context') return s.context ? 'Saved' : 'To do';
    if (id === 'prepare') return running() ? 'Relay Model is drafting' : pr ? (pr.source === 'relay' ? 'Drafted by Relay Model' : 'The industry standard') : (P.job || {}).status === 'error' ? 'The draft failed' : 'To do';
    if (id === 'understanding') return s.understanding ? 'Accepted' : pr ? 'To check' : 'To do';
    if (id === 'kpis') return s.kpis ? (P.dictionary ? `Accepted: ${suN(d.kpis, 'KPI')}` : 'Accepted') : pr ? `${suN((pr.kpis || []).length, 'KPI')} proposed` : 'To do';
    if (id === 'terms') return s.terms ? (P.dictionary ? `Accepted: ${suN(d.terms, 'term')}` : 'Accepted') : pr ? `${suN((pr.terms || []).length, 'term')} proposed` : 'To do';
    if (id === 'theme') return themeOk() ? 'Brand set' : 'To do';
    return P.done ? 'Finished' : P.next === 'finish' ? 'Ready to finish' : 'To do';
  };
  const stepsEl = h('ol', {class: 'su-steps', 'aria-label': 'Steps of the setup'});
  function drawSteps() {
    const r = reach();
    suFill(stepsEl, SU_STEPS.map(([id, title], i) => {
      const on = i === cur, done = doneOf(id);
      return h('li', {class: 'su-st' + (on ? ' cur' : '') + (done ? ' done' : '') + (i > r ? ' todo' : ''), 'aria-current': on ? 'step' : null},
        h('button', {type: 'button', disabled: on || i > r || busy, onclick: () => go(i),
          'aria-label': `Step ${i + 1} of ${SU_STEPS.length}: ${title}, ${on ? 'this step' : done ? 'done' : i > r ? 'not yet' : 'to do'}`},
          h('span', {class: 'su-n', 'aria-hidden': 'true'}, done && !on ? icon('check') : String(i + 1)),
          h('span', {class: 'su-sl', 'aria-hidden': 'true'}, h('b', {}, title), h('small', {}, stateOf(id)))));
    }));
  }
  const backBtn = h('button', {type: 'button', class: 'btn', onclick: () => go(cur - 1)}, icon('chevl'), 'Back');
  const nextBtn = h('button', {type: 'submit', class: 'btn primary', id: 'su-next'});
  const startLink = h('a', {class: 'btn primary', href: '#/new', hidden: true}, icon('plus'), 'Start a dashboard');
  function drawNav() {
    const id = ids[cur], s = STEP[id];
    backBtn.hidden = cur === 0; backBtn.disabled = busy;
    startLink.hidden = !(id === 'finish' && P.done);
    nextBtn.hidden = id === 'finish' && !!P.done;
    if (busy) { nextBtn.disabled = true; return suFill(nextBtn, h('span', {class: 'spin'}), id === 'finish' ? 'Finishing...' : 'Saving...'); }
    if (id === 'finish') { nextBtn.disabled = P.next !== 'finish'; return suFill(nextBtn, icon('check'), 'Finish the setup'); }
    nextBtn.disabled = false;
    const label = typeof s.label === 'function' ? s.label() : s.label;
    suFill(nextBtn, label && s.needs() ? label : `Next: ${SU_STEPS[cur + 1][1]}`, icon('chevr'));
  }
  function recheck() { if (errs[cur].textContent && !STEP[ids[cur]].why()) errs[cur].textContent = ''; }    // a step's message goes once it is right
  function changed() {                  // the profile changed: the step list, the buttons and the step on the screen follow
    suSync(P);
    drawSteps(); drawNav();
    const id = ids[cur];
    if (id === 'prepare') drawPrepare();
    if (id === 'finish') drawFinish();
    recheck();
    poll();
  }
  function show(n, first) {
    cur = n;
    secs.forEach((s, i) => { s.hidden = i !== n; });
    errs[n].textContent = '';
    STEP[ids[n]].draw();
    drawSteps(); drawNav();
    try { history.replaceState(null, '', `#/setup?step=${ids[n]}`); } catch (e) { /* the address keeps #/setup */ }
    const hd = $('h2', secs[n]);
    if (hd && !first) hd.focus();      // a step change moves the focus to its title; the page itself opens at the top
  }
  async function go(n) {
    if (busy || n < 0 || n >= ids.length || n === cur) return;
    if (n > cur) {                      // forward: this step must be right, and what it holds is saved first
      const s = STEP[ids[cur]], why = s.why();
      if (why) { errs[cur].textContent = why; return; }
      if (s.needs() && s.save) {
        busy = true; errs[cur].textContent = ''; drawNav(); drawSteps();
        let ok = false, err = '';
        try { ok = await s.save(); } catch (e) { err = e.message; }
        busy = false;
        if (!here()) return;
        if (!ok) { changed(); STEP[ids[cur]].draw(); errs[cur].textContent = err; return; }
      }
      n = Math.min(n, reach());         // the server says how far the setup can go
      if (n <= cur) { changed(); STEP[ids[cur]].draw(); if (P.next && ids.indexOf(P.next) <= cur) errs[cur].textContent = `Next to do: ${name(P.next)}.`; return; }
    }
    show(n);
    poll();
  }

  const form = h('form', {class: 'card su-card', novalidate: true}, secs,
    h('div', {class: 'su-nav'}, backBtn, h('span', {class: 'spacer'}), startLink, nextBtn));
  form.addEventListener('input', () => { recheck(); drawNav(); });
  form.addEventListener('change', () => { recheck(); drawNav(); });
  form.onsubmit = e => { e.preventDefault(); if (busy) return; if (ids[cur] === 'finish') finish(); else go(cur + 1); };
  form.addEventListener('keydown', e => {          // Ctrl+Enter in a text area is Next too
    if (e.key !== 'Enter' || e.isComposing || !(e.ctrlKey || e.metaKey) || e.target.tagName !== 'TEXTAREA' || e.target.closest('.su-brand-edit')) return;
    e.preventDefault(); if (!nextBtn.disabled && !nextBtn.hidden) form.requestSubmit(nextBtn);
  });
  const set = P.status === 'done' && !P.legacy;
  $('#main').replaceChildren(h('div', {class: 'page su-page'}, suHead(P, true),
    P.legacy && !st().context ? h('div', {class: 'note su-top'}, h('b', {}, `${ORG().name || 'Your organisation'} was set up before this guide. `),
      'Dashboards can be started as before. Add your business context, and Relay plans every dashboard with it.') : null,
    set ? h('div', {class: 'note ok su-top su-fin'}, icon('check'),
      ` Set up${P.done ? ' ' + suDate(P.done) : ''}${P.done_by ? ' by ' + P.done_by : ''}. Change any part: the next plans and builds use it.`) : null,
    h('div', {class: 'su-wrap'}, stepsEl, form), h('div', {id: 'su-live', class: 'su-sr', 'aria-live': 'polite'})));
  const a = ids.indexOf(ask);
  const asked = a >= 0 && a <= reach();          // a step in the address (back from Branding, say): its title takes the focus
  show(asked ? a : set ? ids.length - 1 : P.next ? Math.max(0, ids.indexOf(P.next)) : st().context ? ids.length - 1 : 0, !asked);
  poll();
  if (ids[cur] !== 'theme') loadBrand();       // the step list knows about the brand from the start
}
