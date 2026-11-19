/* ---------------- new dashboard: a guided flow ----------------
   The user, 2026-11-19: "title first and then data is uploaded and then what needs to done or built is prefilled and
   user can change it and confirm and it will be a guided way rather then all visible and one step is done then the next
   shows"; "prototype and theme needs to be set mandate before starting ... including fonts family"; "have only 2 type
   built and built plus custom and it can be changed initially or even request a change".
   Six steps, one on the screen at a time: Name, Your data, What to build (prefilled from the data: POST
   /api/projects/suggest, app/newdash.py), Theme (the organisation's brand: required), Visuals (Power BI's built-in, or
   built-in plus custom), Check and start. Each file goes up as soon as it is picked (uploadParts, 01-core.js); the
   choices and the upload ids stay in sessionStorage, so leaving for Branding and coming back resumes (a reload loses only
   the files still on their way up). Start sends what the one long form sent (POST /api/projects, or /api/projects/import
   for a hand-off), with the upload ids in `uploads` instead of files. */
const IDEAS = [   // demo data starting points: [name, the business, what the dashboard should answer]
  ['Coffee chain', 'A coffee chain with 12 stores in 4 US regions: orders and order lines, products, customers with a loyalty program, staff hours and monthly sales targets per store.',
    'Show the leadership team sales against target by store and region, the product mix, what loyalty members are worth and where service is slow.'],
  ['Pharma supply & quality', 'A biopharma company with 6 medicines made at 3 manufacturing sites: batches, QC tests, quality events, distribution centers, inventory snapshots and customer orders.',
    'Show operations whether supply is reliable - on time in full, stock cover, batch release, right first time and quality events - and where to act.'],
  ['SaaS subscriptions', 'A B2B software company: 1,500 accounts in 5 segments, subscriptions with plans and seats, monthly recurring revenue, upgrades, churn and support tickets.',
    'Show MRR growth, churn and expansion by segment and plan, and which accounts are at risk.'],
  ['Hospital operations', 'A hospital group with 4 hospitals: admissions by department, length of stay, readmissions, bed occupancy and staff on shift.',
    'Show occupancy, length of stay and readmissions by hospital and department, and where capacity is tight.'],
  ['Online retail', 'An online retailer: orders and order lines, products in 8 categories, customers by country, marketing channels, returns and delivery times.',
    'Show revenue, margin and returns by category and channel, customer growth and delivery performance.'],
  ['Logistics fleet', 'A logistics company with 120 trucks in 5 depots: trips, routes, fuel, deliveries on time, maintenance events and drivers.',
    'Show on-time delivery, cost per km and fleet use by depot and route, and which trucks need attention.'],
  ['Airline operations', 'A regional airline with 40 aircraft and 25 airports: flights, departure delays and their causes, cancellations, load factor, maintenance events and crew.',
    'Show on-time performance, delay causes, load factor and aircraft reliability by route, airport and aircraft type.'],
  ['Insurance claims', 'A property and motor insurer: policies by product and region, claims with amounts, handling time, settlement status, fraud flags and adjusters.',
    'Show claim volumes, loss ratio, handling time and suspected fraud by product, region and adjuster.'],
  ['HR & workforce', 'A 3,000-person company: employees by department, location and level, hires, leavers with reasons, salaries, engagement scores and training hours.',
    'Show headcount, attrition and its reasons, hiring, pay and engagement by department and location.'],
  ['Manufacturing plant', 'A plant with 4 lines and 20 machines: daily output per machine and shift, downtime events with causes, scrap, maintenance and energy use.',
    'Show OEE, output against plan, downtime causes and scrap by line, machine and shift.'],
  ['Energy utility', 'An electricity utility: 50,000 customers in 6 regions, daily consumption by tariff, outages with duration, billing and payment behaviour.',
    'Show demand by region and tariff over time, outage minutes, revenue and late payments.'],
  ['Bank lending', 'A retail bank: loan applications by product and channel, approvals, loan book, repayments, arrears and defaults by customer segment.',
    'Show approval rate, loan growth, arrears and defaults by product, segment and channel, and where risk is rising.']];

const ND_KEY = 'd2d.newdash';
const ND_STEPS = [['name', 'Name'], ['data', 'Your data'], ['build', 'What to build'], ['theme', 'Theme'], ['visuals', 'Visuals'], ['check', 'Check and start']];
const ND_KEEP = 23 * 3600 * 1000;     // an upload not used within a day is removed (uploads.py): an older draft starts again
const ND_BIG = 1024 * 1048576;        // item 64: about 1 GB of CSV, roughly where building on a sample starts to pay
const ND_LIVE = [];                   // files on their way up: {field, file, name, size, pct, err, gone} (a reload loses them)
const ND_OK = new Set();              // upload ids the server still has (checked in this page session)
let ND_ST = null;                     // the draft (also in sessionStorage)
let ND_DRAW = null;                   // the open wizard's redraw when an upload ends (null on other pages)
const ND_POLICY = [['auto', 'Automatic: a sample of tables over 2 million rows (recommended)'],
  ['sample', 'A sample of every table over 1 million rows'], ['all', 'Every row (slower for big files)']];
const ND_METHOD = [['random', 'Random rows (keeps the whole date range)'], ['recent', 'The most recent rows (exact totals for the latest weeks)']];
const ND_SIZES = [['small', 'Small - about 5,000 rows (fastest)'], ['medium', 'Medium - about 50,000 rows'], ['large', 'Large - about 500,000 rows']];
const ND_MONTHS = [['12', 'The last 12 months'], ['24', 'The last 24 months'], ['36', 'The last 36 months']];
const ND_VIS = [['builtin', "Power BI's built-in visuals", 'Every Format-pane option and nothing embedded: works where custom visuals are blocked, in exports, subscriptions and on mobile.'],
  ['mixed', 'Built-in plus custom visuals', "Power BI's own visuals first, plus a custom visual in your colours where no built-in one can show what is needed."]];
const ND_CUSTOM = [['ask', 'Ask me: Relay proposes them in the plan and I choose', 'Relay asks before it builds a custom visual'],
  ['auto', 'Build them where they fit better than a built-in visual', 'Relay builds custom visuals where they fit better']];

const ndFresh = () => ({v: 1, step: 0, reached: 0, name: '', mode: 'upload', files: [], zip: null, images: [], policy: 'auto', method: 'random',
  brief: '', dsize: 'medium', dmonths: '12', conn: '', tables: null, prompt: '', from: '', offer: '', added: '', sug: null, sugKey: '',
  visuals: 'builtin', custom: 'ask', started: Date.now()});
const ndWho = () => [(S.me || {}).id || '', (typeof ORG === 'function' && ORG().id) || ''].join('|');
function ndLoad() {
  try {
    const s = JSON.parse(sessionStorage.getItem(ND_KEY) || 'null');
    if (s && s.v === 1 && s.who === ndWho() && Date.now() - (s.started || 0) < ND_KEEP) return Object.assign(ndFresh(), s);
  } catch (e) { /* storage blocked or unreadable: a fresh start */ }
  return null;
}
function ndSave() {
  if (!ND_ST) return;
  try { sessionStorage.setItem(ND_KEY, JSON.stringify({...ND_ST, who: ndWho()})); } catch (e) { /* full or blocked: the page still works */ }
}
const ndDrop = u => { if (u && u.id) api(`/api/uploads/${u.id}`, {method: 'DELETE'}).catch(() => {}); };
/* the draft is done with (started) or thrown away (drop: its uploads are removed now rather than in a day) */
function ndForget(drop) {
  const st = ND_ST;
  ND_LIVE.splice(0).forEach(it => { it.gone = true; });
  ND_ST = null;
  try { sessionStorage.removeItem(ND_KEY); } catch (e) { /* nothing kept */ }
  if (drop && st) [...st.files, ...st.images, st.zip].forEach(ndDrop);
}
const ndSay = msg => { const el = document.getElementById('nd-live'); if (el) el.textContent = msg; };
/* The draft's uploads the server still has: one it removed (not used within a day, or used by a start that failed) leaves
   the draft, and its name is returned so the page can say so. */
async function ndCheckUploads() {
  const st = ND_ST;
  if (!st) return [];
  const gone = [];
  await Promise.all([...st.files, ...st.images, st.zip].filter(u => u && !ND_OK.has(u.id)).map(u =>
    api(`/api/uploads/${u.id}/done`, {method: 'POST'}).then(() => ND_OK.add(u.id))
      .catch(e => { if (/no such upload/i.test(e.message)) gone.push(u); })));
  if (gone.length && ND_ST === st) {
    st.files = st.files.filter(u => !gone.includes(u));
    st.images = st.images.filter(u => !gone.includes(u));
    if (gone.includes(st.zip)) st.zip = null;
    ndSave();
  }
  return gone.map(u => u.name);
}
/* One file up at once, in parts: its row shows the progress; when it is done its id joins the draft, even while the
   person is on another page (Branding) */
function ndSend(file, field) {
  const it = {field, file, name: file.name, size: file.size, pct: 0, err: '', gone: false};
  ND_LIVE.push(it);
  if (ND_DRAW) ND_DRAW();
  uploadParts(file, p => { it.pct = p; ndPaint(it); })
    .then(id => {
      const i = ND_LIVE.indexOf(it);
      if (i >= 0) ND_LIVE.splice(i, 1);
      const st = ND_ST;
      if (it.gone || !st) return ndDrop({id});
      ND_OK.add(id);
      const u = {id, name: file.name, size: file.size};
      if (field === 'handoff') { ndDrop(st.zip); st.zip = u; } else (field === 'images' ? st.images : st.files).push(u);
      ndSave();
      ndSay(`${file.name} is uploaded.`);
    })
    .catch(e => { it.err = String(e.message || e).replace(/^"[^"]*": /, ''); ndPaint(it); ndSay(`${file.name} did not upload: ${it.err}`); })
    .finally(() => { if (ND_DRAW) ND_DRAW(); });
}
function ndPaint(it) {
  if (!it.el) return;
  const p = Math.floor(100 * (it.pct || 0));
  it.el.classList.toggle('err', !!it.err);
  it.bar.style.width = (it.err ? 100 : p) + '%';
  it.pb.setAttribute('aria-valuenow', String(it.err ? 0 : p));
  it.meta.textContent = it.err ? it.err : `${size(it.size)} - uploading ${p}%`;
}
/* a file in the draft (uploaded), or one on its way up (with its progress, Cancel, or Try again after a failure) */
function ndRow(u, remove) {
  return h('div', {class: 'nd-fr'}, h('div', {class: 'nd-fn'}, h('div', {class: 'n'}, u.name), h('div', {class: 'm'}, `${size(u.size)} - uploaded`)),
    h('div', {class: 'nd-fa'}, h('button', {class: 'btn sm ghost', type: 'button', 'aria-label': `Remove ${u.name}`, onclick: remove}, icon('x'), 'Remove')));
}
function ndLiveRow(it, redraw) {
  if (!it.el) {
    it.bar = h('i');
    it.meta = h('div', {class: 'm'});
    it.pb = h('div', {class: 'pb', role: 'progressbar', 'aria-valuemin': '0', 'aria-valuemax': '100', 'aria-label': `Uploading ${it.name}`}, it.bar);
    it.acts = h('div', {class: 'nd-fa'});
    it.el = h('div', {class: 'nd-fr'}, h('div', {class: 'nd-fn'}, h('div', {class: 'n'}, it.name), it.meta), it.acts, it.pb);
  }
  const leave = () => { it.gone = true; const i = ND_LIVE.indexOf(it); if (i >= 0) ND_LIVE.splice(i, 1); redraw(); };
  it.acts.replaceChildren(...(it.err
    ? [h('button', {class: 'btn sm', type: 'button', 'aria-label': `Try ${it.name} again`, onclick: () => { leave(); ndSend(it.file, it.field); }}, 'Try again'),
       h('button', {class: 'btn sm ghost', type: 'button', 'aria-label': `Remove ${it.name}`, onclick: leave}, icon('x'), 'Remove')]
    : [h('button', {class: 'btn sm ghost', type: 'button', 'aria-label': `Cancel ${it.name}`, onclick: leave}, icon('x'), 'Cancel')]));
  ndPaint(it);
  return it.el;
}
/* a place to choose or drop files; take(file) says which it accepts, the others are named and left out */
function ndZone({accept, multiple, hint, take, wrong, onFiles}) {
  const input = h('input', {type: 'file', accept, multiple: multiple || null, tabindex: '-1', 'aria-hidden': 'true'});
  const msg = h('div', {class: 'err-msg', role: 'alert'});
  const hintEl = h('div', {class: 'hint'}, hint);
  const pick = list => {
    const fs = [...list], ok = fs.filter(take), bad = fs.filter(f => !take(f));
    msg.textContent = bad.length ? `${wrong}: ${bad.map(f => f.name).join(', ')} left out.` : '';
    if (ok.length) onFiles(multiple ? ok : ok.slice(0, 1));
  };
  input.onchange = () => { pick(input.files); input.value = ''; };
  const zone = h('div', {class: 'drop nd-drop', onclick: e => { if (e.target !== input) input.click(); }}, input,
    h('button', {class: 'btn sm', type: 'button'}, icon('plus'), multiple ? 'Choose files' : 'Choose a file'),
    h('span', {class: 'muted'}, multiple ? ' or drop them here' : ' or drop it here'), hintEl);
  zone.addEventListener('dragover', e => { e.preventDefault(); zone.classList.add('over'); });
  zone.addEventListener('dragleave', () => zone.classList.remove('over'));
  zone.addEventListener('drop', e => { e.preventDefault(); zone.classList.remove('over'); pick(e.dataTransfer.files); });
  return {el: h('div', {}, zone, msg), hint: hintEl, msg};
}
const ndOpts = (list, sel) => list.map(([v, t]) => h('option', {value: v, selected: String(sel) === v}, t));
/* the brand (app/branding.py, GET /api/branding): the palette in use (`style`), and whether a dashboard can start (`ready`) */
const ndStyle = b => (b && (b.style || (b.chosen != null && b.variants ? b.variants[b.chosen] : null))) || null;
const ndReady = b => !!b && (b.ready != null ? !!b.ready : !!ndStyle(b));
const ndInFont = (el, name, title) => typeof brandFont === 'function' ? brandFont(el, name, title) : el;   // 35-branding.js
const ndLook = v => [v.look === '3d' ? '3D look' : v.look ? `${v.look[0].toUpperCase()}${v.look.slice(1)} look` : '', v.dark ? 'dark background' : 'light background'].filter(Boolean).join(', ');

function renderNew() {
  ND_DRAW = null;
  document.title = 'New dashboard - D2D Relay';
  const me = S.me || {}, org = typeof ORG === 'function' ? ORG() : {};
  const crumbs = h('div', {class: 'crumbs'}, h('a', {href: '#/'}, 'Dashboards'), '>', 'New');
  if (me.builder === false) {
    $('#main').replaceChildren(h('div', {class: 'page'}, crumbs, h('h1', {}, 'New dashboard'),
      h('div', {class: 'note'}, `Your account cannot create dashboards${org.name ? ' in ' + org.name : ''}. Ask an owner of your organisation.`)));
    return;
  }
  if (!ND_ST || ND_ST.who !== ndWho()) { ND_ST = ndLoad() || ndFresh(); ND_ST.who = ndWho(); }
  const st = ND_ST;
  const inOrg = !!org.id && typeof dashCost === 'function' && dashCost('builtin') > 0;
  const connectorsOn = (org.connectors || []).length > 0;
  if (st.mode === 'warehouse' && !connectorsOn) st.mode = 'upload';
  const save = () => ndSave();
  const hadDraft = !!(st.step || st.name.trim() || st.files.length || st.zip || st.brief.trim());
  const errs = ND_STEPS.map(() => h('div', {class: 'err-msg nd-err', role: 'alert'}));
  const label = (text, id, small) => h('label', {class: 'f', for: id}, text, small ? h('small', {}, small) : null);
  const live = field => ND_LIVE.filter(it => it.field === field);
  const busy = field => live(field).some(it => !it.err);
  const failed = field => live(field).some(it => it.err);
  const num = n => Number(n || 0).toLocaleString();

  /* ---- 1: name */
  const nameIn = h('input', {type: 'text', id: 'nd-name', maxlength: '120', autocomplete: 'off', placeholder: 'e.g. Retail performance 2026', value: st.name});
  nameIn.oninput = () => { st.name = nameIn.value; save(); drawNameTip(); };
  const nameTip = h('div', {class: 'hint'});
  const drawNameTip = () => {
    const s = st.sug && st.sug.name_suggestion;
    nameTip.replaceChildren(...(s && s !== st.name.trim()
      ? ['Suggested from your data: ', h('button', {type: 'button', class: 'chip', onclick: () => { nameIn.value = st.name = s; save(); drawNameTip(); }}, s)]
      : ['You can rename it any time.']));
  };

  /* ---- 2: your data */
  const MODES = [['upload', 'file', 'Upload CSV files'], ...(connectorsOn ? [['warehouse', 'layers', 'From a warehouse']] : []),
    ['generate', 'spark', 'Generate demo data'], ['handoff', 'folder', 'From a DAWB hand-off']];
  const modeBtns = MODES.map(([m, ic, t]) => h('button', {type: 'button', onclick: () => setMode(m)}, icon(ic), t));
  const onRequest = connectorsOn ? null : h('div', {class: 'hint', style: 'margin-top:8px'},
    'Data in a warehouse or database (Google BigQuery, Snowflake and others)? PASDACS connects it for your organisation on request: ',
    h('a', {href: '#/connections'}, 'see Connections'), '.');
  const csvHint = () => st.mode === 'generate' ? 'Optional: tables of your own to keep as they are (e.g. your product list) - Relay generates the rest around them.'
    : 'CSV files - one per table (facts and dimensions). Each file goes up as soon as you pick it; large files are fine.';
  const csv = ndZone({accept: '.csv,text/csv', multiple: true, hint: csvHint(), take: f => /\.csv$/i.test(f.name), wrong: 'Only .csv files can be used',
    onFiles: fs => fs.forEach(f => ndSend(f, 'files'))});
  const csvList = h('div', {class: 'nd-files'});
  const policySel = h('select', {class: 'sel', id: 'nd-policy'}, ndOpts(ND_POLICY, st.policy));
  const methodSel = h('select', {class: 'sel', id: 'nd-method'}, ndOpts(ND_METHOD, st.method));
  const sizeText = h('div');
  const sizePanel = h('div', {class: 'note', hidden: true}, sizeText,
    h('div', {class: 'opts', style: 'margin-top:8px'}, h('div', {}, label('Data used to build', 'nd-policy'), policySel),
      h('div', {}, label('How to sample', 'nd-method'), methodSel)),
    h('div', {class: 'hint'}, 'Ask Relay always answers from every row.'));
  const drawSize = () => {      // item 64: how much data, and for big data a sample (recommended) or every row
    const going = live('files').filter(it => !it.err);
    const n = st.files.length + going.length, total = st.files.reduce((a, f) => a + f.size, 0) + going.reduce((a, it) => a + it.size, 0);
    sizePanel.hidden = !n || st.mode !== 'upload';
    if (sizePanel.hidden) return;
    const big = total >= ND_BIG;
    sizePanel.className = 'note' + (big ? ' warn' : '');
    methodSel.disabled = policySel.value === 'all';
    sizeText.replaceChildren(h('b', {}, `${n} file${n === 1 ? '' : 's'}, ${size(total)}. `),
      big ? 'That is a lot of data: Relay plans, builds and checks the dashboard on a sample of the big tables, so it stays fast; '
        + 'lookup tables (stores, products) are always used in full. The Power BI file loads the sample, and you point it at your full files to refresh. '
        : 'Relay reads all of it. ', h('span', {class: 'muted'}, 'Credits do not depend on how much data you have.'));
  };
  policySel.onchange = () => { st.policy = policySel.value; save(); drawSize(); };
  methodSel.onchange = () => { st.method = methodSel.value; save(); };
  const brief = h('textarea', {id: 'nd-brief', rows: 3, placeholder: 'Any business - what it is and what happens in it, e.g. "A regional airline: flights, delays and their causes, aircraft, crew" or "A city council: service requests, response times, budgets by department".'});
  brief.value = st.brief;
  brief.oninput = () => { st.brief = brief.value; save(); };
  const dsize = h('select', {class: 'sel', id: 'nd-dsize'}, ndOpts(ND_SIZES, st.dsize));
  const dmonths = h('select', {class: 'sel', id: 'nd-dmonths'}, ndOpts(ND_MONTHS, st.dmonths));
  dsize.onchange = () => { st.dsize = dsize.value; save(); };
  dmonths.onchange = () => { st.dmonths = dmonths.value; save(); };
  const genPanel = h('div', {class: 'genpanel'},
    label('What should the data be about?', 'nd-brief', 'the business, what happens in it, the tables you expect'), brief,
    h('div', {class: 'muted small', style: 'margin:8px 0 5px'}, 'Any industry works - or start from an example (fills in the description and the request):'),
    h('div', {class: 'chips'}, IDEAS.map(([t, b, p]) => h('button', {type: 'button', class: 'chip', onclick: () => {
      brief.value = st.brief = b;
      if (!st.prompt.trim()) { promptIn.value = st.prompt = p; st.from = ''; }
      if (!st.name.trim()) nameIn.value = st.name = t;
      save(); ndSay(`${t}: the description is filled in.`);
    }}, t))),
    h('div', {class: 'opts', style: 'margin-top:12px'}, h('div', {}, label('Size', 'nd-dsize'), dsize), h('div', {}, label('Period', 'nd-dmonths'), dmonths)),
    h('div', {class: 'hint', style: 'margin-top:8px'}, 'Relay designs the tables, keys and realistic values - with trends, seasonality and a few stories for the dashboard to find - and the app generates them. The same recipe always gives the same data.'));
  // a warehouse: one of my connections and the tables configured on it (pulled with my own login), only once PASDACS has
  // switched a connector on for the organisation
  const whSel = h('select', {class: 'sel', id: 'nd-conn'}), whTables = h('div', {class: 'tables', style: 'margin-top:8px'});
  const whPanel = h('div', {class: 'genpanel'}, h('div', {class: 'muted small'}, 'Loading your connections...'));
  const whHint = h('div', {class: 'hint', style: 'margin-top:8px'});
  let whConns = [];
  const whPicked = () => [...whTables.querySelectorAll('input:checked')].map(i => i.value);
  const drawTables = () => {
    const c = whConns.find(x => x.id === whSel.value);
    if (c && st.conn !== c.id) { st.conn = c.id; st.tables = null; }
    const picked = st.tables || (c ? c.tables.map(t => t.object) : []);
    whHint.textContent = c && c.native === false ? `The app pulls these objects with your own sign-in before Relay plans. ${c.label} has no Power BI connector, so the Power BI file reads the pulled files - refresh them on the dashboard's Details tab or on a daily schedule.`
      : 'The app pulls these tables with your own login before Relay plans. The Power BI file then refreshes from the warehouse directly.';
    whTables.replaceChildren(...(c && c.tables.length ? c.tables.map(t => h('label', {class: 'chk'},
      h('input', {type: 'checkbox', value: t.object, checked: picked.includes(t.object), onchange: () => { st.tables = whPicked(); save(); }}),
      h('span', {}, h('b', {}, t.object), h('small', {class: 'muted', style: 'display:block'}, t.rows != null ? `${num(t.rows)} rows` : 'not pulled yet'))))
      : [h('div', {class: 'muted small'}, 'No tables configured on this connection yet - ', h('a', {href: '#/connections'}, 'choose them'), '.')]));
    save();
  };
  whSel.onchange = () => { st.conn = whSel.value; st.tables = null; drawTables(); };
  if (connectorsOn) api('/api/connections').then(r => {
    whConns = (r.connections || []).filter(c => c.tables.length && c.allowed !== false);
    whPanel.replaceChildren(...(whConns.length ? [label('Connection', 'nd-conn'), whSel, whTables, whHint]
      : [h('div', {}, 'You have no warehouse connection with tables yet. ', h('a', {href: '#/connections'}, 'Add one on Connections'), ' first.')]));
    whSel.replaceChildren(...whConns.map(c => h('option', {value: c.id, selected: c.id === st.conn}, `${c.name} - ${c.label}`)));
    drawTables();
  }).catch(e => whPanel.replaceChildren(h('div', {class: 'err-msg'}, e.message)));
  // item 58: a DAWB hand-off - the folder DAWB writes after a lakehouse build, as one .zip, with its plan: the dashboard
  // waits at Confirm KPIs and Relay does not plan it again
  const zip = ndZone({accept: '.zip,application/zip,application/x-zip-compressed', multiple: false, take: f => /\.zip$/i.test(f.name),
    wrong: 'The hand-off must be one .zip file', hint: 'The hand-off folder as one .zip: project.json, manifest.json and data/ with the CSVs.',
    onFiles: fs => { live('handoff').forEach(it => { it.gone = true; ND_LIVE.splice(ND_LIVE.indexOf(it), 1); }); ndSend(fs[0], 'handoff'); }});
  const zipList = h('div', {class: 'nd-files'});
  const handoffPanel = h('div', {class: 'genpanel'},
    h('div', {class: 'muted small', style: 'margin-bottom:10px'}, 'DAWB, the lakehouse builder, writes a hand-off after every build: the gold tables with their descriptions, and a proposed plan (KPIs, pages and visuals). '
      + "D2D checks every file against the hand-off's manifest, then shows that plan at Confirm KPIs - Relay does not plan it again."), zip.el, zipList);
  const csvWrap = h('div', {style: 'margin-top:12px'}, csv.el, csvList);
  const drawMode = () => {
    modeBtns.forEach((b, i) => { const on = MODES[i][0] === st.mode; b.classList.toggle('on', on); b.setAttribute('aria-pressed', String(on)); });
    genPanel.hidden = st.mode !== 'generate';
    whPanel.hidden = st.mode !== 'warehouse';
    handoffPanel.hidden = st.mode !== 'handoff';
    csvWrap.hidden = st.mode === 'warehouse' || st.mode === 'handoff';
    csv.hint.textContent = csvHint();
    drawSize();
  };
  function setMode(m) { st.mode = m; save(); errs[1].textContent = ''; drawMode(); }

  /* ---- 3: what to build */
  const promptHint = 'Who is it for, and what decisions should it support? e.g. "Show leadership whether we are on plan this year and why - by store, category and channel - where to act, and how customers are trending. Several pages, like the attached image."';
  const promptIn = h('textarea', {id: 'nd-prompt', rows: 8, placeholder: promptHint});
  promptIn.value = st.prompt;
  promptIn.oninput = () => { st.prompt = promptIn.value; save(); drawOffer(); };
  const addedIn = h('textarea', {id: 'nd-added', rows: 4, placeholder: 'e.g. "Leadership reads it on Monday mornings: lead with last week."'});
  addedIn.value = st.added;
  addedIn.oninput = () => { st.added = addedIn.value; save(); };
  const buildIntro = h('p', {class: 'nd-lead'});
  const promptLabel = label('What should the dashboard show?', 'nd-prompt');
  const promptWrap = h('div', {}, promptLabel, promptIn);
  const addedWrap = h('div', {}, label('Anything to add', 'nd-added', "optional - the hand-off says what the dashboard should answer"), addedIn);
  const offerBox = h('div');
  const ctxBox = h('div', {class: 'nd-ctx', 'aria-live': 'polite'});
  const img = ndZone({accept: 'image/png,image/jpeg,image/webp,image/gif', multiple: true, take: f => /\.(png|jpe?g|webp|gif)$/i.test(f.name),
    wrong: 'Only PNG, JPEG, WebP or GIF images', hint: 'Optional: screenshots or sketches of the design you want.', onFiles: fs => fs.forEach(f => ndSend(f, 'images'))});
  const imgList = h('div', {class: 'nd-files'});
  let sugSeq = 0, sugBusy = false, sugErr = '';
  const sugKey = () => st.files.map(f => f.id).sort().join(',');
  const drawOffer = () => {
    const show = st.mode === 'upload' && st.offer && st.offer !== st.prompt;
    offerBox.replaceChildren(...(show ? [h('div', {class: 'note row', style: 'gap:10px'}, h('span', {style: 'flex:1;min-width:200px'},
      'Your data changed since you edited this. Relay has a new suggestion for it (your own words are kept at the start).'),
      h('button', {type: 'button', class: 'btn sm', onclick: () => { promptIn.value = st.prompt = st.from = st.offer; st.offer = ''; save(); drawOffer(); promptIn.focus(); }}, 'Use it'))] : []));
  };
  async function fetchSug(force) {
    if (st.mode !== 'upload' || !st.files.length) return drawCtx();
    if (!force && st.sug && st.sugKey === sugKey()) return drawCtx();
    const mine = ++sugSeq, key = sugKey(), edited = !!st.prompt.trim() && st.prompt !== st.from;
    sugBusy = true; sugErr = ''; drawCtx();
    try {
      const r = await api('/api/projects/suggest', {json: {uploads: st.files.map(f => f.id), prompt: edited ? st.prompt : ''}});
      if (mine !== sugSeq) return;
      st.sug = r; st.sugKey = key;
      if (!st.prompt.trim() || st.prompt === st.from) { promptIn.value = st.prompt = st.from = r.suggestion || ''; st.offer = ''; }
      else st.offer = r.suggestion || '';
      save();
    } catch (e) {
      if (mine !== sugSeq) return;
      sugErr = e.message;
      if (/no such upload/i.test(e.message)) ndCheckUploads().then(() => { if (ND_DRAW) ND_DRAW(); });
    } finally {
      if (mine === sugSeq) { sugBusy = false; drawCtx(); drawOffer(); drawNameTip(); }
    }
  }
  const drawCtx = () => {
    const m = st.mode;
    if (m === 'handoff') return ctxBox.replaceChildren(h('div', {class: 'small'}, icon('info'), " DAWB's plan comes with the hand-off: you confirm its KPIs next, and Relay does not plan it again."));
    if (m === 'generate') return ctxBox.replaceChildren(h('h3', {}, 'The demo data'), h('div', {class: 'small'}, st.brief || 'Describe the business on Your data.'),
      h('div', {class: 'small muted', style: 'margin-top:4px'}, `${(ND_SIZES.find(x => x[0] === st.dsize) || [, ''])[1]} - ${(ND_MONTHS.find(x => x[0] === String(st.dmonths)) || [, ''])[1]}`));
    if (m === 'warehouse') {
      const c = whConns.find(x => x.id === st.conn), t = whPicked();
      return ctxBox.replaceChildren(h('h3', {}, 'The warehouse tables'), h('div', {class: 'small'}, c ? `${c.name}: ${t.join(', ') || 'none picked'}` : 'Pick them on Your data.'),
        h('div', {class: 'small muted', style: 'margin-top:4px'}, 'The app pulls them before Relay plans; the plan shows what Relay found in them.'));
    }
    if (sugBusy) return ctxBox.replaceChildren(h('div', {class: 'row', role: 'status'}, h('span', {class: 'spin'}), 'Reading your data and your KPI dictionary...'));
    if (sugErr) return ctxBox.replaceChildren(h('div', {class: 'err-msg', style: 'margin-top:0'}, sugErr),
      h('div', {class: 'row', style: 'margin-top:8px'}, h('button', {type: 'button', class: 'btn sm', onclick: () => fetchSug(true)}, 'Try again'),
        h('span', {class: 'muted small'}, 'Or write the request yourself.')));
    const r = st.sugKey === sugKey() ? st.sug : null;
    if (!r) return ctxBox.replaceChildren();
    const tagged = (r.tables || []).reduce((a, t) => a + t.columns.filter(c => c.term).length, 0);
    const lead = (r.kpis || []).filter(k => k.lead), more = (r.kpis || []).filter(k => !k.lead);
    const kpiItem = k => h('li', {}, h('b', {}, k.name), h('span', {class: 'muted'}, ' - ' + k.why));
    ctxBox.replaceChildren(
      h('h3', {}, 'What Relay read', h('small', {class: 'muted'}, ` ${r.tables.length} table${r.tables.length === 1 ? '' : 's'}, ${tagged} column${tagged === 1 ? '' : 's'} with a business term${r.industry ? ' - ' + r.industry : ''}`)),
      ...(r.unreadable || []).map(u => h('div', {class: 'note warn'}, h('b', {}, u.file), `: ${u.why}. Remove it on Your data, or the dashboard cannot start.`)),
      h('div', {class: 'nd-tbls'}, (r.tables || []).map((t, i) => h('details', {class: 'nd-tbl', open: i === 0 && r.tables.length < 4 ? true : null},
        h('summary', {}, h('b', {}, t.file), h('span', {class: 'muted'}, ` - ${t.estimated ? 'about ' : ''}${num(t.rows)} rows`
          + Object.values(t.dates || {}).filter(d => d.from && d.to).slice(0, 1).map(d => `, ${d.from} to ${d.to}`).join(''))),
        h('div', {class: 'nd-cols'}, t.columns.map(c => h('span', {class: 'nd-col'}, c.name, c.term ? h('em', {}, ' ' + c.term + (c.variant ? ' ' + c.variant : '')) : null)),
          t.more_columns ? h('span', {class: 'muted small'}, `and ${t.more_columns} more`) : null)))),
      h('h3', {}, 'KPIs your data supports', h('small', {class: 'muted'}, r.kpi_source === 'general'
        ? ' from the general KPI list: your organisation has no KPI dictionary yet'
        : ` from ${org.name ? org.name + "'s" : 'your'} KPI dictionary (${r.dictionary} KPIs)`)),
      r.kpis && r.kpis.length ? h('ul', {class: 'nd-kpis'}, lead.map(kpiItem)) : h('div', {class: 'small muted'}, 'None of the dictionary KPIs match the columns yet: the plan proposes KPIs from the data, and you confirm them.'),
      more.length ? h('details', {class: 'nd-more'}, h('summary', {}, `${more.length} more`), h('ul', {class: 'nd-kpis'}, more.map(kpiItem))) : null,
      r.kpi_source === 'general' ? h('div', {class: 'hint'}, 'Add your own KPIs and business terms on ', h('a', {href: '#/ontology'}, 'Ontology'), ': the next dashboards use them.') : null);
  };
  const drawBuild = () => {
    const m = st.mode;
    buildIntro.textContent = m === 'upload' ? 'Relay read your data and wrote what it would build. Change anything: who it is for, the KPIs, the breakdowns, the time comparisons.'
      : m === 'generate' ? 'Say what the dashboard should answer. Relay designs the demo data around it.'
        : m === 'warehouse' ? 'Say who the dashboard is for and what decisions it should support.'
          : "The hand-off comes with DAWB's plan. Add anything Relay should know.";
    promptWrap.hidden = m === 'handoff';
    addedWrap.hidden = m !== 'handoff';
    drawOffer(); drawCtx();
  };

  /* ---- 4: theme - the organisation's brand (app/branding.py): a palette and fonts, required (the server refuses a new
     dashboard without one). Owners set or change it right here, in Branding's own editor (35-branding.js renderBranding
     drawn into this step), or on the Branding page (#/branding?return=new comes back here); everyone else sees it, and
     is told that an owner sets it while there is none. */
  const themeSum = h('div', {'aria-live': 'polite'});
  const editWrap = h('div', {class: 'nd-brand-edit', hidden: true});
  const themeBox = h('div', {}, themeSum, editWrap);
  let brand = null, brandErr = '', editing = false, editSeq = 0;
  const brandOk = () => ndReady(brand);
  const toBranding = e => { if (e) e.preventDefault(); st.step = 3; save(); location.hash = '#/branding?return=new'; };
  async function loadBrand() {
    if (!brand) themeSum.replaceChildren(h('div', {class: 'row', role: 'status'}, h('span', {class: 'spin'}), 'Loading your brand...'));
    try { brand = await api('/api/branding'); brandErr = ''; } catch (e) { brandErr = e.message; }
    drawTheme();
  }
  function openEditor(open) {
    editing = open && typeof renderBranding === 'function';
    editWrap.hidden = !editing;
    if (editing) {
      const mine = ++editSeq, box = h('div');
      editWrap.replaceChildren(box);
      renderBranding({into: box, route: '#/new', onChange: b => { if (mine === editSeq && b) { brand = b; brandErr = ''; drawTheme(); } }});
    } else editWrap.replaceChildren();
    drawTheme();
  }
  const drawTheme = () => {
    if (brandErr && !brand) return themeSum.replaceChildren(h('div', {class: 'err-msg', style: 'margin-top:0'}, brandErr),
      h('button', {type: 'button', class: 'btn sm', style: 'margin-top:8px', onclick: loadBrand}, 'Try again'));
    if (!brand) return;
    const v = ndStyle(brand), edit = !!brand.may_edit, who = org.name || 'Your organisation';
    if (!brandOk()) {
      themeSum.replaceChildren(h('div', {class: 'note warn'}, ...(edit
        ? [h('b', {}, 'Set up your brand first. '), 'Every dashboard is built in your brand: a palette and fonts. Pick them below - it takes a minute - or ',
          h('a', {href: '#/branding?return=new', onclick: toBranding}, 'open Branding'), '.']
        : [h('b', {}, `${who} has no brand yet. `), 'An owner of your organisation sets it under Branding, and then dashboards can be started.'])));
      if (edit && !editing) openEditor(true);   // owners pick it right here
      return;
    }
    const font = brand.font || 'Segoe UI', head = brand.heading_font || font;
    themeSum.replaceChildren(h('div', {class: 'nd-theme'},
      brand.logo ? h('div', {class: 'nd-logo'}, h('img', {src: brand.logo, alt: 'Your logo'})) : null,
      h('div', {class: 'nd-tinfo'},
        h('div', {}, h('b', {}, v.name), h('span', {class: 'muted small'}, ` - ${ndLook(v)}`)),
        h('div', {class: 'nd-sws', role: 'img', 'aria-label': 'Palette colours: ' + v.colors.join(', ')}, v.colors.map(c => h('i', {class: 'nd-sw', style: `background:${c}`, title: c}))),
        h('div', {class: 'small'}, 'Fonts: ', ndInFont(h('b', {}, font), font),
          head !== font ? [' for text and numbers, ', ndInFont(h('b', {}, head), head, true), ' for titles'] : ' for titles, text and numbers')),
      edit ? h('button', {type: 'button', class: 'btn sm', 'aria-expanded': String(editing), onclick: () => openEditor(!editing)},
        icon(editing ? 'check' : 'edit'), editing ? 'Done' : 'Change') : null),
      h('div', {class: 'hint', style: 'margin-top:10px'}, edit
        ? 'Every new dashboard uses your brand. A change applies to the dashboards started after it; dashboards already built keep their look until you ask for a change.'
        : `Every report in ${who} uses this brand. Only its owners change it.`));
    if (cur === 3) recheck();
  };

  /* ---- 5: visuals - two choices, each with its credits (item 44); changed later by a change request */
  const visRadios = ND_VIS.map(([v]) => h('input', {type: 'radio', name: 'nd-visuals', value: v, checked: st.visuals === v, onchange: () => { st.visuals = v; save(); drawVis(); drawNav(); }}));
  const visCr = ND_VIS.map(() => h('span', {class: 'cr'}));
  const visCards = ND_VIS.map(([v, t, d], i) => h('label', {class: 'nd-card'}, visRadios[i],
    h('span', {}, h('b', {}, t), h('span', {class: 'small muted'}, d), inOrg ? visCr[i] : null)));
  const customSel = h('select', {class: 'sel', id: 'nd-custom'}, ndOpts(ND_CUSTOM, st.custom));
  customSel.onchange = () => { st.custom = customSel.value; save(); };
  const customWrap = h('div', {}, label('When no built-in visual fits', 'nd-custom'), customSel,
    h('div', {class: 'hint'}, 'Relay builds a new Power BI visual in your colours only where none of the built-in ones can show what is needed.'));
  const visLine = h('p', {class: 'small', style: 'margin:12px 0 0'});
  const drawVis = () => {
    visCards.forEach((c, i) => c.classList.toggle('on', visRadios[i].checked));
    customWrap.hidden = st.visuals !== 'mixed';
    visCr.forEach((el, i) => { el.textContent = ND_VIS[i][0] === 'builtin' ? (paid.base ? 'Included' : `${costOf('dashboard')} credits`)
      : paid.custom ? 'Paid' : paid.base ? `+${extra()} credits` : `${dashCost(ND_VIS[i][0])} credits`; });
    visLine.replaceChildren(...(!inOrg ? [] : st.visuals === 'builtin' || paid.custom
      ? [h('b', {}, `Uses ${dashCost(st.visuals)} credits in all`), paid.base ? ', already taken. ' : '. ', `${org.name} has ${num(org.credits)}.`]
      : [h('b', {}, `Custom visuals take ${extra()} more credits when you go on.`), ` They are not refunded. ${org.name} has ${num(org.credits)}.`]));
  };

  /* item 90 (the user, 2026-11-19): a new dashboard's credits are taken as the person goes on: from Your data at the
     built-in visuals' price, and from Visuals with custom visuals the difference; not refunded; once per draft, so
     going back or opening the steps again takes nothing more (GET and POST /api/new-dashboard/credits, orgs.draft_pay) */
  const paid = {base: false, custom: false};
  const extra = () => Math.max(0, costOf('dashboard_custom') - costOf('dashboard'));
  const due = () => (paid.base ? 0 : costOf('dashboard')) + (st.visuals !== 'builtin' && !paid.custom ? extra() : 0);
  const dataCost = h('p', {class: 'small nd-cost', style: 'margin:14px 0 0'});
  const drawCost = () => dataCost.replaceChildren(...(!inOrg ? [] : paid.base
    ? [icon('check'), ' The credits for this dashboard are taken: going on uses no more.']
    : [h('b', {}, `Going on takes ${costOf('dashboard')} credits`), ' for this dashboard, with Power BI\'s built-in visuals. They are not refunded.'
      + (extra() ? ` Custom visuals, if you choose them, take ${extra()} more.` : '') + ` ${org.name} has ${num(org.credits)}.`]));
  async function payStep(stage) {
    if (!inOrg) return true;
    try {
      const r = await api('/api/new-dashboard/credits', {json: {stage, name: st.name.trim(), visuals_mode: st.visuals}});
      paid.base = !!r.base; paid.custom = !!r.custom;
      if (r.charged) {
        if (r.credits != null) org.credits = r.credits;
        ndSay(`${r.charged} credits taken for this dashboard.`);
        if (typeof refreshOrg === 'function') refreshOrg(true);
      }
      drawCost(); drawVis(); drawLow();
      return true;
    } catch (e) { errs[stage === 'data' ? 1 : 4].textContent = e.message; return false; }
  }

  /* ---- 6: check and start */
  const sumBox = h('dl', {class: 'nd-sum'});
  const creditBox = h('div');
  const planNote = h('p', {class: 'small muted', style: 'margin:14px 0 0'});
  const startText = () => st.mode === 'generate' ? 'Start - Relay generates the data, then plans' : st.mode === 'warehouse' ? 'Start - pull the tables, then Relay plans'
    : st.mode === 'handoff' ? "Import - confirm DAWB's plan next" : 'Start - Relay plans first';
  const dataLine = () => {
    const n = st.files.length, total = st.files.reduce((a, f) => a + f.size, 0);
    const own = n ? ` With ${n} file${n === 1 ? '' : 's'} of your own: ${st.files.map(f => f.name).join(', ')}.` : '';
    if (st.mode === 'generate') return `Demo data: ${st.brief.trim()} (${(ND_SIZES.find(x => x[0] === st.dsize) || [, ''])[1].split(' - ')[0]}, ${(ND_MONTHS.find(x => x[0] === String(st.dmonths)) || [, ''])[1].toLowerCase()}).${own}`;
    if (st.mode === 'warehouse') { const c = whConns.find(x => x.id === st.conn); return `${c ? c.name : 'Warehouse'}: ${whPicked().join(', ')}`; }
    if (st.mode === 'handoff') return st.zip ? `DAWB hand-off: ${st.zip.name} (${size(st.zip.size)})` : 'No hand-off yet';
    return `${n} CSV file${n === 1 ? '' : 's'}, ${size(total)}: ${st.files.map(f => f.name).join(', ')}`;
  };
  const drawCheck = () => {
    const v = brandOk() ? ndStyle(brand) : null, font = brand && brand.font, head = brand && brand.heading_font;
    const req = st.mode === 'handoff' ? st.added.trim() : st.prompt.trim();
    const rows = [
      ['Name', st.name.trim(), 0],
      ['Data', dataLine(), 1],
      st.mode === 'upload' ? ['Data used to build', (ND_POLICY.find(x => x[0] === st.policy) || [, ''])[1]
        + (st.policy === 'all' ? '' : ` - ${(ND_METHOD.find(x => x[0] === st.method) || [, ''])[1].toLowerCase()}`), 1] : null,
      [st.mode === 'handoff' ? 'Anything to add' : 'What to build', h('div', {class: 'pre'}, req || 'Nothing added'), 2],
      ['Design reference', st.images.length ? st.images.map(f => f.name).join(', ') : 'None', 2],
      ['Theme', v ? h('span', {}, h('b', {}, v.name), ' ', h('span', {class: 'nd-sws inl', role: 'img', 'aria-label': 'Palette colours: ' + v.colors.join(', ')},
        v.colors.map(c => h('i', {class: 'nd-sw', style: `background:${c}`}))), font ? ` - ${font}${head && head !== font ? `, titles in ${head}` : ''}` : '')
        : brand ? 'No brand yet' : 'Loading...', 3],
      ['Visuals', (ND_VIS.find(x => x[0] === st.visuals) || [, ''])[1] + (st.visuals === 'mixed' ? `. ${(ND_CUSTOM.find(x => x[0] === st.custom) || [, , ''])[2]}.` : ''), 4],
      inOrg ? ['Credits', `${dashCost(st.visuals)} credits` + (due() ? `: ${due()} still to take when you start` : ', taken in the steps: starting uses no more')
        + ` (${org.name} has ${num(org.credits)})`, null] : null].filter(Boolean);
    sumBox.replaceChildren(...rows.flatMap(([t, val, step]) => [h('dt', {}, t), h('dd', {}, val),
      h('dd', {class: 'nd-edit'}, step == null ? null : h('button', {type: 'button', class: 'btn sm ghost', 'aria-label': `Change: ${t}`, onclick: () => go(step)}, 'Change'))]));
    const short = inOrg && Number(org.credits || 0) < due();
    creditBox.replaceChildren(...(short ? [h('div', {class: 'note warn row', style: 'gap:10px'}, h('span', {style: 'flex:1;min-width:200px'},
      `Not enough credits: starting this dashboard takes ${due()} more and ${org.name} has ${num(org.credits)}.`),
      h('button', {class: 'btn sm primary', type: 'button', onclick: () => creditsDialog()}, icon('plus'), org.pending_request ? 'Credits requested' : 'Request credits'))] : []));
    planNote.textContent = st.mode === 'handoff' ? "D2D checks the hand-off against its manifest and shows DAWB's plan for you to confirm. Nothing is built before you agree."
      : 'Relay reads your data and proposes a plan for you to confirm first. Nothing is built before you agree.';
  };

  /* ---- the steps */
  const section = (i, title, lead, ...body) => h('section', {class: 'nd-step', hidden: true, 'aria-labelledby': `nd-h${i}`},
    h('div', {class: 'nd-kicker'}, `Step ${i + 1} of ${ND_STEPS.length}`), h('h2', {class: 'nd-h', id: `nd-h${i}`, tabindex: '-1'}, title),
    lead ? (lead.nodeType ? lead : h('p', {class: 'nd-lead'}, lead)) : null, body, errs[i]);
  const secs = [
    section(0, 'Name the dashboard', 'Start with its name. Next you bring the data, and Relay suggests what to build from it.',
      typeof setupNotice === 'function' ? setupNotice('dashboard') : null,      // item 81: until the organisation is set up (47-setup.js)
      label('Dashboard name', 'nd-name'), nameIn, nameTip),
    section(1, 'Your data', 'Bring CSV files, generate demo data, or import a DAWB hand-off.', h('div', {class: 'dmode', role: 'group', 'aria-label': 'Where the data comes from'}, modeBtns), onRequest,
      genPanel, whPanel, handoffPanel, csvWrap, sizePanel, dataCost),
    section(2, 'What to build', buildIntro, promptWrap, addedWrap, offerBox, ctxBox,
      h('div', {class: 'nd-sub'}, h('h3', {}, 'Design reference', h('small', {class: 'muted'}, ' optional')), img.el, imgList)),
    section(3, 'Theme', 'Your organisation\'s brand: its palette and font family. It is set once on Branding and used by every new dashboard.', themeBox),
    section(4, 'Visuals', null, typeof platformChips === 'function' ? platformChips('Built for') : null,      // item 87
      h('fieldset', {class: 'nd-choice'}, h('legend', {}, 'Which visuals should the report use?'), visCards), customWrap, visLine,
      h('div', {class: 'hint'}, 'You can change this here now, or later with a change request on the dashboard.')),
    section(5, 'Check and start', 'Everything you chose. Change any of it, then start.', sumBox, creditBox, planNote)];
  const checks = [
    () => (typeof setupWhy === 'function' && setupWhy()) || (!st.name.trim() ? 'Give the dashboard a name.' : ''),   // item 81: the setup comes first
    () => {
      if (st.mode === 'upload' || st.mode === 'generate') {
        if (busy('files')) return 'Wait for the files to finish uploading.';
        if (failed('files')) return 'A file did not upload: try it again or remove it.';
      }
      if (st.mode === 'upload' && !st.files.length) return 'Add at least one CSV file - or choose another way to bring your data.';
      if (st.mode === 'generate' && !st.brief.trim()) return 'Describe the business the demo data should be about.';
      if (st.mode === 'warehouse' && !whPicked().length) return 'Pick at least one warehouse table.';
      if (st.mode === 'handoff') {
        if (busy('handoff')) return 'Wait for the hand-off to finish uploading.';
        if (!st.zip) return 'Choose the hand-off .zip: the folder DAWB wrote, zipped.';
      }
      return '';
    },
    () => {
      if (st.mode !== 'handoff' && !st.prompt.trim()) return 'Say what the dashboard should show.';
      if (busy('images')) return 'Wait for the design images to finish uploading.';
      if (failed('images')) return 'A design image did not upload: try it again or remove it.';
      return '';
    },
    () => brandOk() ? '' : brand && !brand.may_edit
      ? `${org.name || 'Your organisation'} has no brand yet: an owner sets it under Branding before a dashboard can start.`
      : 'Set up your brand first: pick a palette (and check the fonts), then go on.',
    () => '',
    () => ''];
  const stepsEl = h('ol', {class: 'steps nd-steps', 'aria-label': 'Steps'});
  const backBtn = h('button', {type: 'button', class: 'btn', onclick: () => go(cur - 1)}, icon('chevl'), 'Back');
  const nextBtn = h('button', {type: 'submit', class: 'btn primary'});
  let cur = Math.max(0, Math.min(Number(st.step) || 0, ND_STEPS.length - 1)), starting = false;
  const drawSteps = () => stepsEl.replaceChildren(...ND_STEPS.map(([, t], i) => h('li', {class: 'step' + (i < cur ? ' done' : i === cur ? ' cur' : ''), 'aria-current': i === cur ? 'step' : null},
    h('button', {type: 'button', disabled: i === cur || i > (st.reached || 0) || starting, onclick: () => go(i),
      'aria-label': `Step ${i + 1} of ${ND_STEPS.length}: ${t}${i < cur ? ', done' : i === cur ? ', this step' : ''}`},
      h('b', {}, i < cur ? icon('check') : String(i + 1)), h('span', {}, t)))));
  const drawNav = () => {
    backBtn.hidden = cur === 0;
    const take = !inOrg ? 0 : cur === 1 && !paid.base ? costOf('dashboard') : cur === 4 && st.visuals !== 'builtin' && !paid.custom ? extra() : 0;
    nextBtn.replaceChildren(...(cur === ND_STEPS.length - 1 ? [icon('play'), startText()]
      : [`Next: ${ND_STEPS[cur + 1][1]}` + (take ? ` - ${take} credits` : ''), icon('chevr')]));
  };
  const drawLists = () => {
    const redraw = () => { save(); drawLists(); drawSize(); };
    const rows = (field, done, remove) => [...done.map(u => ndRow(u, () => { remove(u); ndDrop(u); ndSay(`${u.name} is removed.`); redraw(); })),
      ...live(field).map(it => ndLiveRow(it, redraw))];
    csvList.replaceChildren(...rows('files', st.files, u => { st.files = st.files.filter(x => x !== u); }));
    zipList.replaceChildren(...rows('handoff', st.zip ? [st.zip] : [], () => { st.zip = null; }));
    imgList.replaceChildren(...rows('images', st.images, u => { st.images = st.images.filter(x => x !== u); }));
  };
  function show(n) {
    cur = n; st.step = n; st.reached = Math.max(st.reached || 0, n); save();
    secs.forEach((s, i) => { s.hidden = i !== n; });
    errs[n].textContent = '';
    drawSteps(); drawNav();
    if (n === 0) drawNameTip();
    if (n === 1) { drawMode(); drawLists(); drawCost(); }
    if (n === 2) { drawBuild(); drawLists(); fetchSug(false); }
    if (n === 3) loadBrand();
    if (n === 4) drawVis();
    if (n === 5) { drawCheck(); if (!brand) loadBrand().then(drawCheck); }
    const hd = $('h2', secs[n]);
    if (hd) hd.focus();
  }
  async function go(n) {
    if (starting || n < 0 || n >= ND_STEPS.length) return false;
    for (let s = cur; s < n; s++) {             // going forward checks every step on the way
      if (s === 3 && !brand) await loadBrand();
      const why = checks[s]();
      if (why) { if (s !== cur) show(s); errs[s].textContent = why; return false; }
    }
    // item 90: going on from Your data, and from Visuals with custom visuals, takes the credits (once per draft)
    if (cur <= 1 && n > 1 && !paid.base && !(await payStep('data'))) { if (cur !== 1) show(1); return false; }
    if (cur <= 4 && n > 4 && st.visuals !== 'builtin' && !paid.custom && !(await payStep('visuals'))) { if (cur !== 4) show(4); return false; }
    show(n);
    return true;
  }
  async function start() {
    for (let s = 0; s < ND_STEPS.length - 1; s++) {
      if (s === 3) await loadBrand();
      const why = checks[s]();
      if (why) { show(s); errs[s].textContent = why; return; }
    }
    if (inOrg && !paid.base && !(await payStep('data'))) { show(1); return; }                 // item 90: steps restored from a draft
    if (inOrg && st.visuals !== 'builtin' && !paid.custom && !(await payStep('visuals'))) { show(4); return; }
    const fd = new FormData(), ups = [];
    const model = typeof catalogEntry === 'function' && typeof CATALOG !== 'undefined' && catalogEntry(CATALOG.default) ? CATALOG.default : '';
    fd.append('name', st.name.trim());
    fd.append('prompt', st.mode === 'handoff' ? st.added.trim() : st.prompt.trim());
    fd.append('model', model);
    fd.append('look', '');                     // the brand's own look (Branding)
    if (st.mode !== 'handoff') fd.append('data_mode', st.mode);
    if (st.mode === 'generate') { fd.append('data_brief', st.brief.trim()); fd.append('data_size', st.dsize); fd.append('data_months', String(st.dmonths)); }
    if (st.mode === 'warehouse') { fd.append('connection_id', st.conn); fd.append('tables', JSON.stringify(whPicked())); }
    if (st.mode === 'upload') fd.append('data_policy', JSON.stringify({mode: st.policy, method: st.method}));   // item 64
    fd.append('use_brand', '1');
    fd.append('custom_visuals', st.visuals === 'builtin' ? 'never' : st.custom);
    fd.append('visuals_mode', st.visuals);
    if (st.mode === 'upload' || st.mode === 'generate') st.files.forEach(f => ups.push({field: 'files', id: f.id}));
    if (st.mode === 'handoff' && st.zip) ups.push({field: 'handoff', id: st.zip.id});
    st.images.forEach(f => ups.push({field: 'images', id: f.id}));
    fd.append('uploads', JSON.stringify(ups));
    starting = true; nextBtn.disabled = backBtn.disabled = true; drawSteps();
    nextBtn.replaceChildren(h('span', {class: 'spin'}), st.mode === 'handoff' ? 'Checking the hand-off...' : 'Starting...');
    errs[5].textContent = '';
    try {
      const r = await sendForm(st.mode === 'handoff' ? '/api/projects/import' : '/api/projects', fd);
      // what the start did not use is removed now rather than in a day
      [...(st.mode === 'upload' || st.mode === 'generate' ? [] : st.files), st.mode === 'handoff' ? null : st.zip].forEach(ndDrop);
      ndForget(false);
      if (typeof refreshList === 'function') refreshList();
      if (typeof refreshOrg === 'function') refreshOrg(true);
      location.hash = '#/p/' + r.id;
    } catch (e) {
      starting = false; nextBtn.disabled = backBtn.disabled = false; drawSteps(); drawNav();
      errs[5].textContent = e.message;
      const gone = await ndCheckUploads();       // a start that failed may have used up its uploads
      if (gone.length) { errs[5].textContent = `${e.message} ${gone.join(', ')} must be uploaded again: see Your data.`; drawCheck(); }
    }
  }

  function recheck() { if (errs[cur].textContent && !checks[cur]()) errs[cur].textContent = ''; }   // a step's message goes once it is right
  const form = h('form', {class: 'card formcard nd', novalidate: true}, secs, h('div', {class: 'nd-nav'}, backBtn, h('span', {class: 'spacer'}), nextBtn));
  form.addEventListener('input', recheck);
  form.addEventListener('change', recheck);
  form.onsubmit = e => { e.preventDefault(); if (starting) return; if (cur === ND_STEPS.length - 1) start(); else go(cur + 1); };
  form.addEventListener('keydown', e => {       // Enter is Next from any field but a text area (Ctrl+Enter there) or a button
    if (e.key !== 'Enter' || e.isComposing) return;
    const t = e.target;
    if (t.closest('.nd-brand-edit')) return;    // Branding's own editor, drawn into the Theme step
    if ((t.tagName === 'TEXTAREA' && (e.ctrlKey || e.metaKey)) || t.tagName === 'SELECT' || (t.tagName === 'INPUT' && /^(checkbox|radio)$/.test(t.type))) {
      e.preventDefault(); form.requestSubmit(nextBtn);
    }
  });
  const draftNote = hadDraft ? h('div', {class: 'note row nd-draft', style: 'gap:10px'}, h('span', {style: 'flex:1;min-width:200px'}, icon('info'), ' Picking up where you left off.'),
    h('button', {type: 'button', class: 'btn sm ghost', onclick: () => { ndForget(true); renderNew(); }}, 'Start again')) : null;
  const goneNote = h('div');
  const lowBox = h('div');
  function drawLow() {                          // D2D Relay: say it before the steps are filled in (unless already paid)
    lowBox.replaceChildren(...(org.id && !paid.base && (org.credits || 0) < costOf('dashboard')
      ? [h('div', {class: 'note warn row', style: 'gap:10px;flex-wrap:wrap'}, h('span', {style: 'flex:1;min-width:220px'},
          `Not enough credits for a new dashboard: it uses ${costOf('dashboard')} credits`
          + (typeof twoPrices === 'function' && twoPrices() ? ` with Power BI's built-in visuals (${costOf('dashboard_custom')} with custom visuals)` : '')
          + ` and ${org.name} has ${org.credits}.`),
        h('button', {class: 'btn sm primary', type: 'button', onclick: () => creditsDialog()}, icon('plus'),
          org.pending_request ? 'Credits requested' : 'Request credits'))] : []));
  }
  $('#main').replaceChildren(h('div', {class: 'page nd-page'}, crumbs,
    h('h1', {}, 'New dashboard'), h('div', {class: 'muted', style: 'margin:4px 0 14px'}, 'A few short steps. You confirm the KPIs before anything is built.'),
    lowBox, draftNote, goneNote, stepsEl, form, h('div', {id: 'nd-live', class: 'nd-sr', 'aria-live': 'polite'})));
  drawLow();
  api('/api/new-dashboard/credits').then(r => {                 // item 90: what an open draft has paid already
    paid.base = !!r.base; paid.custom = !!r.custom;
    if (!form.isConnected) return;
    drawCost(); drawVis(); drawNav(); drawLow(); if (cur === 5) drawCheck();
  }, () => {});
  ND_DRAW = () => {
    if (!form.isConnected) { ND_DRAW = null; return; }
    drawLists(); drawSize(); recheck();
    if (cur === 2 && st.mode === 'upload' && st.files.length && st.sugKey !== sugKey() && !busy('files')) fetchSug(false);
    if (cur === 5) drawCheck();
  };
  drawMode();
  show(cur);
  ndCheckUploads().then(gone => {
    if (!gone.length || !form.isConnected) return;
    goneNote.replaceChildren(h('div', {class: 'note warn'}, `${gone.join(', ')} must be uploaded again: an upload not used within a day is removed.`));
    if (ND_DRAW) ND_DRAW();
  });
}
