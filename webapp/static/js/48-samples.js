/* ---------------- D2D Relay: sample pages for the tour's guides (38-tour.js). The user, 2026-11-19: "instead showing the
   same screen can you prepare a sample screen and details of the same like prefilled". Each guide shows where a task
   starts in the app, then these pages filled in with a sample (a grocer's monthly store dashboard), each part lit in
   turn. Drawn into #main while the tour is open on #/welcome (renderTour draws the sample of the step on now); read
   only, behind the tour's layer: nothing here is saved, sent or charged. Prices come from the organisation's own
   costs (36-org.js costOf), so the samples say what the real steps take. ---------------- */
const TS_FILES = [['sales_2026.csv', '4.2 MB', '48,210 rows, 14 columns'], ['stores.csv', '3 KB', '36 rows, 6 columns'],
  ['products.csv', '96 KB', '1,240 rows, 9 columns'], ['targets_2026.csv', '12 KB', '432 rows, 5 columns']];
const TS_PROMPT = 'For store managers, every month: sales against target by store and region, gross margin by category, '
  + 'the top and bottom 10 stores, and what changed since last month.';
const TS_KPIS = [['Net sales', 'Sales amount minus returns', 'Higher'], ['Sales vs target %', 'Net sales / target - 1', 'Higher'],
  ['Gross margin %', '(Net sales - cost of goods) / net sales', 'Higher'], ['Average basket', 'Net sales / transactions', 'Higher'],
  ['Stock-outs', 'Days a product had no stock', 'Lower']];

function tourSample(name) {
  const c = k => (typeof costOf === 'function' ? costOf(k) : 0) || {dashboard: 25, dashboard_custom: 50, change: 10, ask: 10, kpi: 1, fix: 1}[k];
  const extra = Math.max(0, c('dashboard_custom') - c('dashboard'));
  const page = (title, sub, ...body) => h('div', {class: 'page tsample', 'data-sample': name},
    h('div', {class: 'ts-banner', role: 'note'}, icon('info'), h('span', {}, h('b', {}, 'Sample. '),
      'Filled in to show how it works: nothing here is saved or charged.')),
    h('h1', {}, title), sub ? h('div', {class: 'muted', style: 'margin:4px 0 14px'}, sub) : null, ...body);
  const btn = (text, cls = '', ic = null) => h('button', {type: 'button', class: 'btn ' + cls, tabindex: '-1', 'aria-disabled': 'true'}, ic ? icon(ic) : null, text);
  const steps = cur => h('ol', {class: 'steps nd-steps', 'aria-label': 'Steps'}, ND_STEPS.map(([, t], i) =>
    h('li', {class: 'step' + (i < cur ? ' done' : i === cur ? ' cur' : '')},
      h('button', {type: 'button', disabled: true, tabindex: '-1'}, h('b', {}, i < cur ? icon('check') : String(i + 1)), h('span', {}, t)))));
  const card = (i, title, lead, body, next) => [steps(i), h('div', {class: 'card formcard nd'},
    h('section', {class: 'nd-step'}, h('div', {class: 'nd-kicker'}, `Step ${i + 1} of ${ND_STEPS.length}`), h('h2', {class: 'nd-h'}, title),
      lead ? h('p', {class: 'nd-lead'}, lead) : null, body),
    h('div', {class: 'nd-nav'}, i ? btn('Back', '', 'chevl') : null, h('span', {class: 'spacer'}), h('span', {class: 'ts-next'}, btn(next, 'primary'))))];
  const nd = (i, title, lead, body, next) => page('New dashboard', 'A few short steps. You confirm the KPIs before anything is built.', ...card(i, title, lead, body, next));
  const field = (label, value, area) => h('div', {}, h('label', {class: 'f'}, label),
    area ? h('textarea', {rows: 3, readonly: true, tabindex: '-1'}, value) : h('input', {value, readonly: true, tabindex: '-1'}));
  const table = (cls, head, rows) => h('table', {class: 'ts-table ' + cls}, h('thead', {}, h('tr', {}, head.map(x => h('th', {}, x)))),
    h('tbody', {}, rows.map(r => h('tr', {}, r.map(x => h('td', {}, x))))));
  const bars = (rows, unit = '') => { const top = Math.max(...rows.map(r => r[1]));
    return h('div', {class: 'ts-bars', role: 'img', 'aria-label': rows.map(r => `${r[0]} ${r[1]}${unit}`).join(', ')},
      rows.map(([k, v]) => h('div', {class: 'ts-bar'}, h('span', {}, k), h('i', {style: `width:${Math.round(v / top * 100)}%`}), h('b', {}, `${v}${unit}`)))); };
  const PAGES = {
    'nd-0': () => nd(0, 'Name the dashboard', 'Start with its name. Next you bring the data, and Relay suggests what to build from it.',
      h('div', {class: 'ts-name'}, field('Dashboard name', 'Retail performance 2026')), 'Next: Your data'),
    'nd-1': () => nd(1, 'Your data', 'Bring CSV files, generate demo data, or import a DAWB hand-off.', [
      h('div', {class: 'dmode ts-modes', role: 'group'}, btn('CSV files', 'primary', 'file'), btn('Generate demo data', '', 'spark'), btn('From a DAWB hand-off', '', 'folder')),
      h('div', {class: 'ts-files'}, TS_FILES.map(([n, s, r]) => h('div', {class: 'ts-file'}, icon('table'), h('b', {}, n), h('span', {class: 'muted small'}, `${s} - ${r}`),
        h('span', {class: 'tag ok'}, icon('check'), 'Checked')))),
      h('p', {class: 'small ts-cost'}, h('b', {}, `Going on takes ${c('dashboard')} credits`), ' for this dashboard, with Power BI\'s built-in visuals. They are not refunded.'
        + (extra ? ` Custom visuals, if you choose them, take ${extra} more.` : ''))], `Next: What to build - ${c('dashboard')} credits`),
    'nd-2': () => nd(2, 'What to build', 'Say what the dashboard should answer. Relay suggests ideas from your data.', [
      h('div', {class: 'ts-prompt'}, field('What should it show?', TS_PROMPT, true)),
      h('div', {class: 'chips ts-ideas'}, h('span', {class: 'muted small'}, 'Relay suggests: '),
        ['Sales vs target by region', 'Margin % by category', 'Top and bottom 10 stores', 'Basket size by month'].map(t => h('span', {class: 'chip'}, t)))], 'Next: Theme'),
    'nd-3': () => nd(3, 'Theme', 'Your organisation\'s brand: its palette and font family. It is set once on Branding and used by every new dashboard.',
      h('div', {class: 'nd-tinfo ts-theme'}, h('div', {}, h('b', {}, 'Fresh market'), h('span', {class: 'muted small'}, ' - light')),
        h('div', {class: 'nd-sws'}, ['#0B3D2E', '#00A676', '#F2B134', '#E4572E', '#5B8E7D'].map(x => h('i', {class: 'nd-sw', style: `background:${x}`}))),
        h('div', {class: 'small'}, 'Fonts: ', h('b', {}, 'Inter'), ' for titles, text and numbers')), 'Next: Visuals'),
    'nd-4': () => nd(4, 'Visuals', null, [
      h('fieldset', {class: 'nd-choice'}, h('legend', {}, 'Which visuals should the report use?'), ND_VIS.map(([v, t, d]) =>
        h('label', {class: 'nd-card' + (v === 'builtin' ? ' on' : '')}, h('input', {type: 'radio', checked: v === 'builtin', tabindex: '-1'}),
          h('span', {}, h('b', {}, t), h('span', {class: 'small muted'}, d), h('span', {class: 'cr'}, v === 'builtin' ? 'Included' : `+${extra} credits`))))),
      h('p', {class: 'small ts-vline'}, h('b', {}, `Uses ${c('dashboard')} credits in all, already taken.`),
        extra ? ` Choosing custom visuals takes ${extra} more credits when you go on; they are not refunded.` : '')], 'Next: Check and start'),
    'nd-5': () => nd(5, 'Check and start', 'Everything you chose. Change any of it, then start.', [
      h('dl', {class: 'nd-sum ts-sum'}, [['Name', 'Retail performance 2026'], ['Data', '4 CSV files, 4.3 MB: ' + TS_FILES.map(f => f[0]).join(', ')],
        ['What to build', TS_PROMPT], ['Theme', 'Fresh market - Inter'], ['Visuals', 'Power BI\'s built-in visuals'],
        ['Credits', `${c('dashboard')} credits, taken in the steps: starting uses no more`]].flatMap(([k, v]) => [h('dt', {}, k), h('dd', {}, v)])),
      h('p', {class: 'small muted', style: 'margin:14px 0 0'}, 'Relay reads your data and proposes a plan for you to confirm first. Nothing is built before you agree.')],
      'Start - Relay plans first'),
    'nd-kpis': () => page('Retail performance 2026', 'Confirm KPIs: Relay\'s plan, from your data and your KPI standard.',
      h('div', {class: 'card ts-kpis'}, h('h3', {}, 'KPIs in the plan'), table('', ['KPI', 'How it is worked out', 'Good when'], TS_KPIS.map(([k, f, g]) => [h('b', {}, k), f, `${g} is better`])),
        h('div', {class: 'row ts-kchange', style: 'gap:8px;margin-top:12px;flex-wrap:wrap;align-items:center'},
          h('input', {value: 'Net sales should leave out staff discounts', readonly: true, tabindex: '-1', style: 'flex:1;min-width:220px'}),
          btn(`Change - ${c('kpi')} credit${c('kpi') === 1 ? '' : 's'}`), btn('Confirm KPIs and build', 'primary', 'check')))),
    'nd-proto': () => page('Retail performance 2026', 'Version 1: the prototype, with your data. Every number is checked against the data.',
      h('div', {class: 'card ts-proto'},
        h('div', {class: 'ts-kpicards'}, [['Net sales', '12.4M', '+6.1% on last year'], ['Sales vs target', '+3.2%', '9 of 12 months on target'],
          ['Gross margin', '31.8%', '+0.9 pts'], ['Average basket', '742', '+18 on last year']].map(([k, v, s]) =>
          h('div', {class: 'ts-kpi'}, h('span', {class: 'muted small'}, k), h('b', {}, v), h('span', {class: 'small'}, s)))),
        h('h3', {style: 'margin:14px 0 6px'}, 'Net sales by region (M)'),
        bars([['West', 2.9], ['North', 2.7], ['South', 2.5], ['East', 2.3], ['Central', 2.0]])),
      h('div', {class: 'row ts-protoact', style: 'gap:8px;flex-wrap:wrap;margin-top:12px'}, btn('Download the Power BI file (.pbix)', 'primary', 'download'),
        btn('Publish to the Power BI service', '', 'publish'), btn(`Ask for a change - ${c('change')} credits`, '', 'edit'))),
    'kpi-std': () => page('Your organisation: business context', 'Step 4 of 7: the KPI standard your reports are held to.',
      h('div', {class: 'card ts-kstd'},
        h('div', {class: 'row', style: 'gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:10px'}, btn('Keep all', 'sm'), btn('Drop all', 'sm ghost'),
          h('input', {class: 'ts-kfind', value: 'margin', readonly: true, tabindex: '-1', style: 'max-width:220px'})),
        [['Sales (3)', TS_KPIS.slice(0, 2).concat([['Sales growth %', 'Net sales / last year\'s net sales - 1', 'Higher']])],
          ['Profit (1)', [TS_KPIS[2]]], ['Customers (1)', [TS_KPIS[3]]], ['Operations (1)', [TS_KPIS[4]]]].map(([g, rows], i) =>
          h('div', {class: 'ts-kgroup' + (i ? '' : ' first')}, h('h4', {}, g), rows.map(([k, f, gd]) => h('label', {class: 'ts-krow'},
            h('input', {type: 'checkbox', checked: true, tabindex: '-1'}), h('b', {}, k), h('span', {class: 'muted small'}, `${f} - ${gd.toLowerCase()} is better`)))))),
      h('div', {class: 'row', style: 'margin-top:12px'}, h('span', {class: 'spacer'}), btn('Next: Ontology and dictionaries', 'primary'))),
    'ask': () => page('Ask Relay', 'Ask about Retail performance 2026 in your own words.',
      h('div', {class: 'card ts-chat'},
        h('div', {class: 'ts-q'}, h('b', {}, 'You'), h('p', {}, 'Which region grew fastest this year?')),
        h('div', {class: 'ts-answer'}, h('b', {}, 'Relay'),
          h('p', {}, 'West grew fastest: net sales up 18.4% on last year, to 2.9M. North was next at 11.2%.'),
          table('', ['Region', 'Net sales 2026 (M)', 'Growth'], [['West', '2.9', '+18.4%'], ['North', '2.7', '+11.2%'], ['South', '2.5', '+4.0%']]),
          bars([['West', 18.4], ['North', 11.2], ['South', 4.0]], '%'),
          h('p', {class: 'muted small'}, 'Worked out with your KPI Net sales: sales amount minus returns.'))),
      h('div', {class: 'card ts-compose'}, h('div', {class: 'muted small'}, `Asking about Retail performance 2026. ${c('ask')} credits for ${(ORG().costs || {}).ask_questions || 5} questions.`),
        h('div', {class: 'row', style: 'gap:8px;align-items:center;margin-top:6px'},
          h('input', {value: 'And which stores drove it?', readonly: true, tabindex: '-1', style: 'flex:1'}), btn('Ask', 'primary', 'send')))),
    'review': () => page('One KPI, one meaning, one value', 'Semantic Review: 2 Power BI models checked against 12 KPIs.',
      h('div', {class: 'ts-tiles'}, [['12', 'KPIs checked'], ['9', 'agree'], ['2', 'differ'], ['1', 'missing']].map(([n, t], i) =>
        h('div', {class: 'tile ts-tile' + ['', ' ok', ' warn', ' err'][i]}, h('b', {}, n), h('span', {class: 'small'}, t)))),
      h('div', {class: 'card ts-findings'}, h('h3', {}, 'Findings'),
        h('div', {class: 'ts-finding ts-differs'}, h('span', {class: 'tag warn'}, 'Differs'), h('b', {}, 'Net sales'),
          h('p', {class: 'small'}, 'Sales model: SUM(Sales[Gross]) keeps returns in; your dictionary takes them out. Fix: subtract Returns[Amount].'),
          btn(`Fix - ${c('fix')} credit${c('fix') === 1 ? '' : 's'}`, 'sm ts-fixbtn')),
        h('div', {class: 'ts-finding'}, h('span', {class: 'tag ok'}, 'Agrees'), h('b', {}, 'Gross margin %'), h('p', {class: 'small'}, 'The same formula in both models.')),
        h('div', {class: 'ts-finding'}, h('span', {class: 'tag err'}, 'Missing'), h('b', {}, 'Average basket'), h('p', {class: 'small'}, 'Not in the Store operations model.')))),
    'onto': () => page('Ontology', 'Your business language: what each word means, and where it is in your data.',
      h('div', {class: 'card ts-pack'}, h('h3', {}, 'Industry pack: Grocery retail ', h('span', {class: 'tag ok'}, 'In use')),
        h('p', {class: 'small muted'}, '86 business terms and 24 KPIs a grocer uses, kept as a starting point and changed to fit you.')),
      h('div', {class: 'card ts-terms'}, h('h3', {}, 'Business terms'), table('', ['Term', 'What it means', 'In your data'], [
        [h('b', {}, 'Net sales'), 'Sales after returns and discounts', 'Sales[Amount], Returns[Amount]'],
        [h('b', {}, 'Basket'), 'One customer\'s purchase at the till', 'Sales[TransactionID]'],
        [h('b', {}, 'Store'), 'A shop, with its region and size', 'stores.csv'],
        [h('b', {}, 'Stock-out'), 'A day a product could not be bought', 'Inventory[OnHand] = 0']])))};
  const draw = PAGES[name];
  $('#main').replaceChildren(draw ? draw() : page('Sample'));
  window.scrollTo(0, 0);
}
