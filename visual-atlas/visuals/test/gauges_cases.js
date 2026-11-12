// Test cases for Atlas Gauges in the mock host.
const GUID = Object.keys(powerbi.visuals.plugins)[0];
/* data view: optional Category and Trend columns; measures by role (values, target, minValue, maxValue, band1, band2) */
function dv(o) {
  const cats = [];
  if (o.cats) cats.push({ source: { displayName: o.catName || 'Region', queryName: 't.Category', roles: { category: true }, type: { text: true } }, values: o.cats });
  if (o.trend) cats.push({ source: { displayName: 'Month', queryName: 't.Month', roles: { trend: true }, type: { text: true } }, values: o.trend });
  const values = o.measures.map(mm => { const c = { source: { displayName: mm.name, queryName: 'm.' + mm.name, roles: { [mm.role || 'values']: true }, isMeasure: true, format: mm.fmt || o.fmt || '#,0' }, values: mm.values }; if (mm.hl) c.highlights = mm.hl; return c; });
  values.grouped = () => [{ values: values.slice() }];
  const objects = Object.assign({}, o.objects || {});
  objects.chart = Object.assign({ chartType: o.type }, objects.chart || {});
  return { metadata: { columns: [], objects }, categorical: { categories: cats, values } };
}
const C = (title, d, o) => { try { return renderCase(GUID, title, d, o || {}); } catch (e) { LOG.push(['THROW', title, String(e && e.stack || e)]); } };
const regions = ['North', 'South', 'East', 'West'], sales = [9.3e6, 7.1e6, 8.4e6, 5.2e6], tgt = [10e6, 6.8e6, 8.5e6, 6.5e6];
const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'], trendV = [6.1, 6.4, 6.2, 6.9, 7.2, 7.0, 7.6, 7.9, 8.1, 8.0, 8.6, 9.1].map(x => x * 1e6);
const reg3 = [], mon3 = [], val3 = [], tg3 = [];
['North', 'South', 'East'].forEach((r, k) => months.forEach((mm, j) => { reg3.push(r); mon3.push(mm); val3.push(Math.round((30 + k * 6 + j * (k === 1 ? -0.8 : 1.1) + ((j * 7 + k) % 5)) * 10) / 10); tg3.push(36 + k * 4); }));
const kpis = ['Sales', 'Margin', 'Orders', 'NPS', 'Returns', 'Delivery', 'Repeat rate', 'Basket'], kv = [9.3, 37.0, 48200, 61, 4.2, 2.8, 0.31, 84], kt = [10, 37.5, 45000, 55, 3.5, 2.5, 0.3, 80];

// 0-3 cards and KPIs
C('Card · single value with target', dv({ measures: [{ name: 'Sales', values: [9.3e6], fmt: '\\$#,0' }, { name: 'Target', role: 'target', values: [10e6] }], type: 'card' }));
C('Cards · four measures', dv({ measures: [{ name: 'Sales', values: [9.3e6], fmt: '\\$#,0' }, { name: 'Profit', values: [1.4e6], fmt: '\\$#,0' }, { name: 'Orders', values: [48210] }, { name: 'Return rate', values: [0.042], fmt: '0.0%' }], type: 'card' }));
C('KPI · trend and goal', dv({ trend: months, measures: [{ name: 'Sales', values: trendV, fmt: '\\$#,0' }, { name: 'Goal', role: 'target', values: months.map(() => 8.5e6) }], type: 'kpi' }));
C('KPI · per region · columns · lower is better', dv({ cats: reg3, trend: mon3, measures: [{ name: 'Delivery hours', values: val3, fmt: '0.0' }, { name: 'Target', role: 'target', values: tg3 }], type: 'kpi', objects: { trend: { style: 'column' }, status: { direction: 'lower', colorValue: true } } }));
// 4-7 gauges and dials
C('Gauge · value vs target', dv({ measures: [{ name: 'Sales', values: [9.3e6], fmt: '\\$#,0' }, { name: 'Target', role: 'target', values: [10e6] }, { name: 'Max', role: 'maxValue', values: [12e6] }], type: 'gauge' }));
C('Gauge strip · % of target by region', dv({ cats: regions, measures: [{ name: '% of target', values: sales.map((v, i) => v / tgt[i]), fmt: '0%' }, { name: 'Target', role: 'target', values: regions.map(() => 1) }], type: 'gauge', objects: { scale: { min: '0', max: '1.5' }, status: { colorValue: true } } }));
C('Dial · bands from data · target · three quarters', dv({ measures: [{ name: 'Customer score', values: [72], fmt: '0' }, { name: 'Target', role: 'target', values: [80] }, { name: 'Min', role: 'minValue', values: [0] }, { name: 'Max', role: 'maxValue', values: [100] }, { name: 'Fair', role: 'band1', values: [50] }, { name: 'Good', role: 'band2', values: [75] }], type: 'dial', objects: { scale: { angle: '240' } } }));
C('Dial · lower is better · open ring · flat', dv({ measures: [{ name: 'Days to deliver', values: [3.4], fmt: '0.0' }, { name: 'Target', role: 'target', values: [3] }, { name: 'Max', role: 'maxValue', values: [8] }], type: 'dial', objects: { chart: { look: 'flat' }, scale: { angle: '270', band1: 40, band2: 65 }, status: { direction: 'lower' } } }));
// 8-10 radial and liquid
C('Radial bars · progress to target', dv({ cats: ['Sales', 'Margin', 'Orders', 'NPS'], catName: 'Measure', measures: [{ name: 'Actual', values: [9.3, 37, 48.2, 61] }, { name: 'Target', role: 'target', values: [10, 37.5, 45, 70] }], type: 'radialBar' }));
C('Liquid fill · progress to goal', dv({ measures: [{ name: 'Sales QTD', values: [6.2e6], fmt: '\\$#,0' }, { name: 'Quarter goal', role: 'maxValue', values: [10e6] }], type: 'liquid' }));
C('Liquid fill · three tanks · square', dv({ cats: ['Online', 'Retail', 'Partner'], catName: 'Channel', measures: [{ name: 'Stock', values: [82, 47, 21], fmt: '0' }, { name: 'Capacity', role: 'maxValue', values: [100, 100, 100] }], type: 'liquid', objects: { liquid: { shape: 'square', wave: 10 } } }));
// 11-14 bullets, rows and ticker
const bul = [['Revenue', 275, 250, 300, 180, 240], ['Profit', 22.4, 26, 30, 18, 24], ['New customers', 1680, 1500, 2000, 1000, 1400], ['Order size', 320, 380, 450, 250, 340], ['Satisfaction', 4.4, 4.5, 5, 3.5, 4.2]];
C('Bullet · KPI scorecard · bands from data', dv({ cats: bul.map(b => b[0]), catName: 'Measure', measures: [{ name: 'Actual', values: bul.map(b => b[1]) }, { name: 'Target', role: 'target', values: bul.map(b => b[2]) }, { name: 'Max', role: 'maxValue', values: bul.map(b => b[3]) }, { name: 'Poor', role: 'band1', values: bul.map(b => b[4]) }, { name: 'Fair', role: 'band2', values: bul.map(b => b[5]) }], type: 'bullet' }));
C('Bullet · vertical · colored by status', dv({ cats: bul.map(b => b[0]), catName: 'Measure', measures: [{ name: 'Actual', values: bul.map(b => b[1]) }, { name: 'Target', role: 'target', values: bul.map(b => b[2]) }, { name: 'Max', role: 'maxValue', values: bul.map(b => b[3]) }], type: 'bullet', objects: { bullet: { orientation: 'vertical' }, status: { colorValue: true } } }));
C('Multi-row card · regions with targets', dv({ cats: regions, measures: [{ name: 'Sales', values: sales, fmt: '\\$#,0' }, { name: 'Target', role: 'target', values: tgt }], type: 'multirow' }));
C('Ticker · eight KPIs vs target', dv({ cats: kpis, catName: 'KPI', measures: [{ name: 'Value', values: kv }, { name: 'Target', role: 'target', values: kt }], type: 'ticker', objects: { ticker: { speed: 20 } } }));
// 15-18 modes and edge cases
C('Card · high contrast', dv({ measures: [{ name: 'Sales', values: [9.3e6], fmt: '\\$#,0' }, { name: 'Target', role: 'target', values: [10e6] }], type: 'card' }), { hc: true });
C('Gauge strip · dark', dv({ cats: regions, measures: [{ name: 'Sales', values: sales, fmt: '\\$#,0' }, { name: 'Target', role: 'target', values: tgt }], type: 'gauge' }), { dark: true });
C('Landing page (no fields)', null);
// 18: a long name in a low KPI tile does not run into the value (2026-11-12); the last two cases stay last (checks count from the end)
C('KPI · long name in a low tile', dv({ trend: months, measures: [{ name: 'Average selling price per order', values: trendV.map(v => v / 30000), fmt: '\\$#,0.00' }, { name: 'Goal', role: 'target', values: months.map(() => 290) }], type: 'kpi' }), { w: 270, h: 96 });
// 19: the usual case, a medium name: the value moves right, clear of it, at its full size (2026-11-12)
C('KPI · name and value side by side in a low tile', dv({ trend: months, measures: [{ name: 'Revenue Growth %', values: months.map((_, i) => 0.08 + i * 0.003), fmt: '+0.0%;-0.0%;0.0%' }, { name: 'Goal', role: 'target', values: months.map(() => 0.1) }], type: 'kpi' }), { w: 270, h: 96 });
C('Multi-row card · cross-highlighted (East)', dv({ cats: regions, measures: [{ name: 'Sales', values: sales, fmt: '\\$#,0', hl: sales.map((v, i) => (i === 2 ? v : null)) }, { name: 'Target', role: 'target', values: tgt }], type: 'multirow' }));
// a selection in another visual (40% of the sales): the card shows the highlighted value, as a filter would
C('Card · partly highlighted (40%)', dv({ measures: [{ name: 'Sales', values: [9.3e6], fmt: '\$#,0', hl: [3.72e6] }, { name: 'Target', role: 'target', values: [10e6], hl: [4e6] }], type: 'card' }));
