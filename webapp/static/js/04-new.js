/* ---------------- new dashboard ---------------- */
function picker(name, accept, multiple, hint) {
  const input = h('input', {type: 'file', name, accept, multiple});
  const list = h('div', {class: 'flist'});
  const hintEl = h('div', {class: 'hint'}, hint);
  const zone = h('div', {class: 'drop'}, input, h('div', {}, h('b', {}, 'Choose files'), ' or drop them here'), hintEl, list);
  const show = () => list.replaceChildren(...[...input.files].map(f => h('span', {}, f.name, ' - ', size(f.size))));
  zone.onclick = e => { if (e.target !== input) input.click(); };
  input.onchange = show;
  zone.ondragover = e => { e.preventDefault(); zone.classList.add('over'); };
  zone.ondragleave = () => zone.classList.remove('over');
  zone.ondrop = e => { e.preventDefault(); zone.classList.remove('over'); input.files = e.dataTransfer.files; show(); };
  return {zone, input, hint: hintEl};
}
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
function renderNew() {
  const csv = picker('files', '.csv,text/csv', true, 'CSV files - one per table (facts and dimensions). Large files are fine.');
  const img = picker('images', 'image/*', true, 'Optional: screenshots or sketches of the design you want.');
  const name = h('input', {type: 'text', placeholder: 'e.g. Retail performance 2026'});
  const prompt = h('textarea', {rows: 6, placeholder: 'Who is it for, and what decisions should it support? e.g. "Show leadership whether we are on plan this year and why - by store, category and channel - where to act, and how customers are trending. Several pages, like the attached image."'});
  const bar = h('div', {class: 'bar'}, h('i'));
  const goBtn = h('button', {class: 'btn primary', type: 'submit'}, icon('play'), 'Start - Relay plans first');
  const modelSel = h('select', {class: 'sel'}, modelOptions(CATALOG.default));
  const modelNote = h('div', {class: 'hint'});
  const describe = () => {
    const m = catalogEntry(modelSel.value) || {};
    modelNote.textContent = [m.note, costHint(m), m.latest ? `Follows the newest ${(m.label || '').split(' ')[0]} automatically${m.version ? ` (now ${m.version})` : ''}.` : m.model ? `Pinned to ${m.model}.` : ''].filter(Boolean).join(' ');
  };
  modelSel.onchange = describe; describe();
  const look = h('select', {class: 'sel'}, [['', 'Relay decides (Soft)'], ['soft', 'Soft - rounded cards, gentle shadow'],
    ['flat', 'Flat - clean borders, no shadow'], ['3d', '3D - deeper shadows']].map(([v, t]) => h('option', {value: v}, t)));
  const useBrand = h('input', {type: 'checkbox'}), brand = h('input', {type: 'color', value: '#0F766E', class: 'swatch', 'aria-label': 'Brand colour'});
  const palette = h('select', {class: 'sel'}, [['spectrum', 'Spectrum - distinct hues'], ['analogous', 'Analogous - neighbouring hues'],
    ['mono', 'Mono - shades of the brand']].map(([v, t]) => h('option', {value: v}, t)));
  const dark = h('input', {type: 'checkbox'});
  brand.oninput = () => { useBrand.checked = true; };
  // D2D Relay: the palette chosen under Branding is used unless unticked
  const houseUse = h('input', {type: 'checkbox', checked: false});
  const houseBox = h('div', {class: 'note small', style: 'margin:0 0 12px'}, 'Loading your brand...');
  api('/api/branding').then(b => {
    const v = b.chosen != null ? b.variants[b.chosen] : null;
    if (!v) { houseBox.replaceChildren(icon('brush'), ' No brand palette yet. ', h('a', {href: '#/branding'}, 'Set up your brand'), ' to give every dashboard your colours.'); return; }
    houseUse.checked = true;
    houseBox.replaceChildren(h('label', {class: 'chk', style: 'margin:0;display:flex;align-items:center;gap:10px'}, houseUse,
      b.logo ? h('img', {src: b.logo, alt: '', style: 'height:26px;max-width:90px;object-fit:contain'}) : null,
      h('span', {}, h('b', {}, 'Use my brand: ' + v.name), h('span', {style: 'display:inline-flex;gap:3px;margin-left:8px;vertical-align:middle'},
        v.colors.map(c => h('i', {style: `display:inline-block;width:14px;height:14px;border-radius:3px;background:${c}`, title: c})))),
      h('span', {class: 'spacer'}), h('a', {href: '#/branding', class: 'small'}, 'Change')));
  }).catch(() => houseBox.replaceChildren(''));
  const custom = h('select', {class: 'sel'}, [['ask', 'Ask me - Relay proposes them in the plan, I choose'],
    ['auto', 'Build them when they fit better than the available visuals'], ['never', 'Only use the available visuals']].map(([v, t]) => h('option', {value: v}, t)));
  // Which visuals the report uses, in the order offered (the user, 2026-11-12): Power BI's own (built-in) visuals only
  // by default, then built-in first with a custom visual only where none fits, and last Relay / Visual Atlas custom visuals
  // item 44: each choice with its credits inside an organisation (25 built-in only, 50 with custom visuals)
  const inOrg = typeof ORG === 'function' && !!ORG().id && typeof dashCost === 'function' && dashCost('builtin') > 0;
  const visualsSel = h('select', {class: 'sel', 'aria-label': 'Visuals'}, [['builtin', "Power BI's built-in visuals only"],
    ['mixed', 'Built-in first, custom where needed'], ['relay', 'Relay custom visuals']]
    .map(([v, t]) => h('option', {value: v}, inOrg ? `${t} (${dashCost(v)} credits)` : t)));
  const visualsHint = h('div', {class: 'hint'});
  const useLine = h('b', {class: 'useline'});
  let customChoice = custom.value;          // Custom visuals as chosen, given back when built-in only is left
  custom.onchange = () => { customChoice = custom.value; };
  const syncVisuals = () => {
    const builtin = visualsSel.value === 'builtin';
    custom.disabled = builtin;
    custom.value = builtin ? 'never' : customChoice;
    visualsHint.textContent = {relay: 'Designed visuals in your colors (embedded in the report).',
      builtin: 'Every Format-pane option. Nothing embedded: works where custom visuals are blocked, in exports, subscriptions and mobile.',
      mixed: 'Standard Power BI visuals, plus a custom one where no built-in visual can show it.'}[visualsSel.value];
    useLine.textContent = inOrg ? `Uses ${dashCost(visualsSel.value)} credits (${ORG().name} has ${Number(ORG().credits || 0).toLocaleString()}). ` : '';
  };
  visualsSel.onchange = syncVisuals;
  syncVisuals();
  const sect = (n, title, sub, ...body) => h('div', {class: 'sect'}, h('h3', {}, h('span', {class: 'num'}, n), title, sub ? h('small', {class: 'muted', style: 'font-weight:400'}, sub) : null), body);
  // the data: upload CSVs, or let Relay generate a realistic demo dataset
  let mode = 'upload';
  const brief = h('textarea', {rows: 3, placeholder: 'Any business - what it is and what happens in it, e.g. "A regional airline: flights, delays and their causes, aircraft, crew" or "A city council: service requests, response times, budgets by department".'});
  const dsize = h('select', {class: 'sel'}, [['small', 'Small - about 5,000 rows (fastest)'], ['medium', 'Medium - about 50,000 rows'],
    ['large', 'Large - about 500,000 rows']].map(([v, t]) => h('option', {value: v, selected: v === 'medium'}, t)));
  const dmonths = h('select', {class: 'sel'}, [[12, 'The last 12 months'], [24, 'The last 24 months'], [36, 'The last 36 months']].map(([v, t]) => h('option', {value: v}, t)));
  const genPanel = h('div', {class: 'genpanel', style: 'display:none'},
    h('label', {class: 'f', style: 'margin-top:0'}, 'What should the data be about?', h('small', {}, 'the business, what happens in it, the tables you expect')), brief,
    h('div', {class: 'muted small', style: 'margin:8px 0 5px'}, 'Any industry works - or start from an example (fills in the description and the request):'),
    h('div', {class: 'chips'}, IDEAS.map(([t, b, p]) => h('button', {type: 'button', class: 'chip', onclick: () => {
      brief.value = b; if (!prompt.value.trim()) prompt.value = p; if (!name.value.trim()) name.value = t; }}, t))),
    h('div', {class: 'opts', style: 'margin-top:12px'}, h('div', {}, h('label', {class: 'f'}, 'Size'), dsize), h('div', {}, h('label', {class: 'f'}, 'Period'), dmonths)),
    h('div', {class: 'hint', style: 'margin-top:8px'}, 'Relay designs the tables, keys and realistic values - with trends, seasonality and a few stories for the dashboard to find - and the app generates them. The same recipe always gives the same data.'));
  // a warehouse: one of my connections and the tables I configured on it (they are pulled with my own login).
  // D2D Relay: only once PASDACS has switched a connector on for the organisation; otherwise CSV files (or demo data).
  const connectorsOn = typeof ORG === 'function' && (ORG().connectors || []).length > 0;
  const whSel = h('select', {class: 'sel'}), whTables = h('div', {class: 'tables', style: 'margin-top:8px'});
  const whPanel = h('div', {class: 'genpanel', style: 'display:none'}, h('div', {class: 'muted small'}, 'Loading your connections...'));
  let whConns = [];
  const whHint = h('div', {class: 'hint', style: 'margin-top:8px'});
  const drawTables = () => { const c = whConns.find(x => x.id === whSel.value);
    whHint.textContent = c && c.native === false ? `The app pulls these objects with your own sign-in before Relay plans. ${c.label} has no Power BI connector, so the Power BI file reads the pulled files - refresh them on the dashboard's Details tab or on a daily schedule.`
      : 'The app pulls these tables with your own login before Relay plans. The Power BI file then refreshes from the warehouse directly.';
    whTables.replaceChildren(...(c && c.tables.length ? c.tables.map(t => h('label', {class: 'chk'}, h('input', {type: 'checkbox', value: t.object, checked: true}),
      h('span', {}, h('b', {}, t.object), h('small', {class: 'muted', style: 'display:block'}, t.rows != null ? `${t.rows.toLocaleString()} rows` : 'not pulled yet'))))
      : [h('div', {class: 'muted small'}, 'No tables configured on this connection yet - ', h('a', {href: '#/connections'}, 'choose them'), '.')])); };
  whSel.onchange = drawTables;
  if (connectorsOn) api('/api/connections').then(r => {
    whConns = r.connections.filter(c => c.tables.length && c.allowed !== false);
    whPanel.replaceChildren(...(whConns.length ? [h('label', {class: 'f', style: 'margin-top:0'}, 'Connection'), whSel, whTables, whHint]
      : [h('div', {}, 'You have no warehouse connection with tables yet. ', h('a', {href: '#/connections'}, 'Add one on Connections'), ' first.')]));
    whSel.replaceChildren(...whConns.map(c => h('option', {value: c.id}, `${c.name} - ${c.label}`)));
    drawTables();
  }).catch(() => {});
  const MODES = [['upload', 'file', 'Upload my CSV files'], ...(connectorsOn ? [['warehouse', 'layers', 'From a warehouse']] : []), ['generate', 'spark', 'Generate demo data']];
  const modeBtns = MODES.map(([m, ic, t]) => h('button', {type: 'button', class: m === mode ? 'on' : '', onclick: () => setMode(m)}, icon(ic), t));
  const onRequest = connectorsOn ? null : h('div', {class: 'hint', style: 'margin-top:8px'},
    'Data in a warehouse or database (Google BigQuery, Snowflake and others)? PASDACS connects it for your organisation on request: ',
    h('a', {href: '#/connections'}, 'see Connections'), '.');
  const startText = () => mode === 'generate' ? 'Start - Relay generates the data, then plans' : mode === 'warehouse' ? 'Start - pull the tables, then Relay plans' : 'Start - Relay plans first';
  function setMode(m) {
    mode = m;
    modeBtns.forEach((b, i) => b.classList.toggle('on', MODES[i][0] === m));
    genPanel.style.display = m === 'generate' ? '' : 'none';
    whPanel.style.display = m === 'warehouse' ? '' : 'none';
    csv.zone.style.display = m === 'warehouse' ? 'none' : '';
    csv.hint.textContent = m === 'generate' ? 'Optional: tables of your own to keep as they are (e.g. your product list) - Relay generates the rest around them.'
      : 'CSV files - one per table (facts and dimensions). Large files are fine.';
    goBtn.lastChild.textContent = startText();
  }
  const form = h('form', {class: 'card formcard'},
    sect('1', 'What do you need?', null, h('label', {class: 'f'}, 'Dashboard name', h('small', {}, 'optional')), name,
      h('label', {class: 'f'}, 'Describe it in your own words'), prompt),
    sect('2', 'Your data', null, h('div', {class: 'dmode'}, modeBtns), onRequest, genPanel, whPanel, h('div', {style: 'margin-top:10px'}, csv.zone)),
    sect('3', 'Design reference', ' optional', h('div', {style: 'margin-top:10px'}, img.zone)),
    sect('4', 'Options', ' you can keep the defaults',
      houseBox,
      h('div', {class: 'opts'}, h('div', {}, h('label', {class: 'f'}, 'Visuals', h('small', {}, 'can be changed for later versions')), visualsSel, visualsHint),
        h('div', {}, h('label', {class: 'f'}, 'Custom visuals', h('small', {}, 'new Relay visuals in your colors')), custom,
          h('div', {class: 'hint'}, 'When no available chart fits a need, Relay can build a new Power BI visual.'))),
      h('label', {class: 'f'}, 'Visual style', h('small', {}, 'optional')),
      h('div', {class: 'style'}, h('div', {}, h('small', {}, 'Look'), look),
        h('div', {}, h('small', {}, 'Brand color'), h('label', {class: 'chk'}, useBrand, brand, h('span', {}, 'use my brand color'))),
        h('div', {}, h('small', {}, 'Palette from the brand'), palette),
        h('div', {}, h('small', {}, 'Background'), h('label', {class: 'chk'}, dark, h('span', {}, 'dark report'))))),
    h('div', {class: 'row', style: 'margin-top:22px'}, goBtn, h('span', {class: 'muted small'},
      inOrg ? useLine : null,
      'Relay reads your data and proposes a plan for you to confirm first. Nothing is built before you agree.')), bar);
  form.onsubmit = e => {
    e.preventDefault();
    if (!prompt.value.trim()) return toast(goBtn, 'Describe what you need.');
    if (mode === 'upload' && !csv.input.files.length) return toast(goBtn, 'Add at least one CSV file - or choose Generate demo data.');
    if (mode === 'generate' && !brief.value.trim()) return toast(goBtn, 'Describe the business the demo data should be about.');
    const picked = [...whTables.querySelectorAll('input:checked')].map(i => i.value);
    if (mode === 'warehouse' && !picked.length) return toast(goBtn, 'Pick at least one warehouse table.');
    const fd = new FormData();
    fd.append('name', name.value); fd.append('prompt', prompt.value); fd.append('model', modelSel.value); fd.append('look', look.value);
    fd.append('data_mode', mode);
    if (mode === 'generate') { fd.append('data_brief', brief.value); fd.append('data_size', dsize.value); fd.append('data_months', dmonths.value); }
    if (mode === 'warehouse') { fd.append('connection_id', whSel.value); fd.append('tables', JSON.stringify(picked)); }
    fd.append('use_brand', houseUse.checked ? '1' : '0');
    if (useBrand.checked && !houseUse.checked) { fd.append('brand', brand.value); fd.append('palette', palette.value); }
    if (dark.checked) fd.append('dark', '1');
    fd.append('custom_visuals', custom.value);
    fd.append('visuals_mode', visualsSel.value);
    if (mode !== 'warehouse') for (const f of csv.input.files) fd.append('files', f);
    for (const f of img.input.files) fd.append('images', f);
    bar.style.display = 'block'; goBtn.disabled = true; goBtn.lastChild.textContent = 'Uploading...';
    upload('/api/projects', fd, p => { $('i', bar).style.width = (100 * p) + '%'; })
      .then(r => { refreshList(); if (typeof refreshOrg === 'function') refreshOrg(true); location.hash = '#/p/' + r.id; })
      .catch(err => { goBtn.disabled = false; goBtn.lastChild.textContent = startText(); toast(goBtn, err.message); });
  };
  $('#main').replaceChildren(h('div', {class: 'page'},
    h('div', {class: 'crumbs'}, h('a', {href: '#/'}, 'Dashboards'), '>', 'New'),
    h('h1', {}, 'New dashboard'), h('div', {class: 'muted', style: 'margin:4px 0 16px'}, 'Four short steps. Bring your CSVs, or let Relay generate demo data. Relay plans first - you confirm the KPIs before anything is built.'),
    typeof ORG === 'function' && ORG().id && (ORG().credits || 0) < costOf('dashboard')       // D2D Relay: say it before the form is filled in
      ? h('div', {class: 'note warn row', style: 'gap:10px;flex-wrap:wrap'}, h('span', {style: 'flex:1;min-width:220px'},
          `Not enough credits for a new dashboard: it uses ${costOf('dashboard')} credits`
          + (typeof twoPrices === 'function' && twoPrices() ? ` with Power BI's built-in visuals (${costOf('dashboard_custom')} with custom visuals)` : '')
          + ` and ${ORG().name} has ${ORG().credits}.`),
        h('button', {class: 'btn sm primary', type: 'button', onclick: () => creditsDialog()}, icon('plus'),
          ORG().pending_request ? 'Credits requested' : isPersonal() ? 'Buy credits' : 'Request credits')) : null,
    form));
}

