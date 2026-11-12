// Test cases for Atlas Finance in the mock host.
const GUID = Object.keys(powerbi.visuals.plugins)[0];
const D = window.DATA;
/* data view: one category column, measures by role (values, open, high, low, close, volume) or a legend */
function dv(o) {
  const cats = [{ source: { displayName: o.cat, queryName: 't.' + o.cat, roles: { category: true }, type: { text: true } }, values: o.cats }];
  let values;
  if (o.series) {
    const groups = o.series.groups.map(g => { const col = { source: { displayName: o.measure, queryName: 'm.' + o.measure, roles: { values: true }, isMeasure: true, format: o.fmt || '#,0', groupName: g.name }, values: g.values }; if (g.hl) col.highlights = g.hl; return { name: g.name, values: [col], identity: { key: g.name } }; });
    values = groups.map(g => g.values[0]);
    values.source = { displayName: o.series.name, queryName: 't.' + o.series.name, roles: { series: true } };
    values.grouped = () => groups;
  } else {
    values = o.measures.map(mm => { const c = { source: { displayName: mm.name, queryName: 'm.' + mm.name, roles: { [mm.role || 'values']: true }, isMeasure: true, format: mm.fmt || o.fmt || '#,0' }, values: mm.values }; if (mm.hl) c.highlights = mm.hl; return c; });
    values.grouped = () => [{ values: values.slice() }];
  }
  const objects = Object.assign({}, o.objects || {});
  objects.chart = Object.assign({ chartType: o.type }, objects.chart || {});
  return { metadata: { columns: [], objects }, categorical: { categories: cats, values } };
}
const C = (title, d, o) => { try { return renderCase(GUID, title, d, o || {}); } catch (e) { LOG.push(['THROW', title, String(e && e.stack || e)]); } };
/* six months of trading days: a seeded random walk */
let seed = 11; const rnd = () => { seed = (seed * 1664525 + 1013904223) >>> 0; return seed / 4294967296; };
const tdays = [], ohlc = []; let price = 84;
for (let d = new Date(2025, 4, 1); d <= new Date(2025, 9, 31); d = new Date(d.getFullYear(), d.getMonth(), d.getDate() + 1)) {
  if (d.getDay() === 0 || d.getDay() === 6) continue;
  const o = price, c = Math.max(20, o * (1 + (rnd() - 0.48) * 0.04)), h = Math.max(o, c) * (1 + rnd() * 0.012), l = Math.min(o, c) * (1 - rnd() * 0.012);
  tdays.push(`${['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][d.getMonth()]} ${d.getDate()}`); ohlc.push([o, h, l, c, Math.round(1e6 * (0.6 + rnd()))]); price = c;
}
const om = (k) => ['Open', 'High', 'Low', 'Close', 'Volume'].map((nm, i) => ({ name: nm, role: nm.toLowerCase(), values: ohlc.map(r => +r[i].toFixed(2)), fmt: i === 4 ? '#,0' : '\\$0.00' })).slice(0, k);
const months = D.months;
const bridge = [['Last year', 4.12e6], ['Price', 0.31e6], ['Volume', 0.48e6], ['Mix', -0.12e6], ['FX', -0.09e6], ['New stores', 0.22e6]];
const pnl = [['Revenue', 4.77e6], ['Cost of goods', -2.86e6], ['Gross profit', 0], ['Marketing', -0.42e6], ['Staff', -0.68e6], ['Rent', -0.21e6], ['Operating profit', 0], ['Tax', -0.15e6]];
const cash = months.map((_, i) => Math.round((i % 4 === 3 ? -1 : 1) * (40 + (i * 37) % 90) * 1000));
const qs = []; ['24', '25'].forEach(y => ['Q1', 'Q2', 'Q3', 'Q4'].forEach(q => qs.push(q + ' ' + y)));
const subs = ['Road', 'Mountain', 'E-bike', 'Touring', 'Helmets'];
const rv = (s, k) => Math.round((140 - s * 18) * (s === 2 ? 0.35 + k * 0.28 : 1 + 0.12 * Math.sin(k + s)));
const pipe = [['Leads', 1240], ['Qualified', 610], ['Proposal', 290], ['Negotiation', 148], ['Closed won', 92]];

// 0-2 candlestick
C('Candlestick · six months · volume', dv({ cat: 'Date', cats: tdays, measures: om(5), type: 'candlestick' }));
C('Candlestick · OHLC bars · 10-day average · flat', dv({ cat: 'Date', cats: tdays, measures: om(5), type: 'candlestick', objects: { chart: { look: 'flat' }, candles: { style: 'ohlc', movingAverage: 10 } } }));
C('Candlestick · close line · no volume · dark', dv({ cat: 'Date', cats: tdays, measures: om(4), type: 'candlestick', objects: { candles: { style: 'line', movingAverage: 20 } } }), { dark: true });
// 3-6 waterfall
C('Waterfall · revenue bridge (start and end totals)', dv({ cat: 'Driver', cats: bridge.map(r => r[0]), measures: [{ name: 'Change', values: bridge.map(r => r[1]) }], fmt: '\\$#,0', type: 'waterfall', objects: { waterfall: { startTotal: true, endLabel: 'This year' } } }));
C('Waterfall · breakdown by category (2024 → 2025)', dv({ cat: 'Year', cats: ['2024', '2025'], series: { name: 'Category', groups: [['Bikes', 4.1e6, 4.77e6], ['Components', 1.9e6, 1.77e6], ['Clothing', 1.05e6, 1.24e6], ['Accessories', 0.88e6, 0.95e6]].map(g => ({ name: g[0], values: [g[1], g[2]] })) }, measure: 'Sales', fmt: '\\$#,0', type: 'waterfall' }));
C('Waterfall · P&L walk with subtotals', dv({ cat: 'Line', cats: pnl.map(r => r[0]), measures: [{ name: 'Amount', values: pnl.map(r => r[1]) }], fmt: '\\$#,0', type: 'waterfall', objects: { waterfall: { startTotal: true, subtotals: 'Gross profit, Operating profit', endLabel: 'Net profit', totColor: { solid: { color: '#4338ca' } } } } }));
C('Waterfall · monthly cash · 3D · no labels', dv({ cat: 'Month', cats: months, measures: [{ name: 'Net cash flow', values: cash }], fmt: '\\$#,0', type: 'waterfall', objects: { chart: { look: '3d' }, labels: { show: false }, waterfall: { endLabel: 'Year end' } } }));
// 7-8 ribbon
C('Ribbon · rank changes by quarter', dv({ cat: 'Quarter', cats: qs, series: { name: 'Subcategory', groups: subs.map((s, k) => ({ name: s, values: qs.map((_, j) => rv(k, j)) })) }, measure: 'Sales', type: 'ribbon', objects: { labels: { show: false } } }));
C('Ribbon · labels · solid ribbons', dv({ cat: 'Quarter', cats: qs.slice(4), series: { name: 'Subcategory', groups: subs.map((s, k) => ({ name: s, values: qs.slice(4).map((_, j) => rv(k, j + 4)) })) }, measure: 'Sales', type: 'ribbon', objects: { ribbon: { opacity: 70 } } }));
// 9-11 funnel
C('Funnel · pipeline · % of first · conversion', dv({ cat: 'Stage', cats: pipe.map(r => r[0]), measures: [{ name: 'Deals', values: pipe.map(r => r[1]) }], type: 'funnel' }));
C('Funnel · tapered · % of previous · darker by stage', dv({ cat: 'Stage', cats: pipe.map(r => r[0]), measures: [{ name: 'Deals', values: pipe.map(r => r[1]) }], type: 'funnel', objects: { funnel: { shape: 'tapered', content: 'previous', colors: 'gradient' } } }));
C('Funnel · a color per stage · high contrast', dv({ cat: 'Stage', cats: pipe.map(r => r[0]), measures: [{ name: 'Deals', values: pipe.map(r => r[1]) }], type: 'funnel', objects: { funnel: { colors: 'vary' } } }), { hc: true });
// 12-15 edge cases
C('Landing page (no fields)', null);
C('Waterfall · cross-highlighted', dv({ cat: 'Driver', cats: bridge.map(r => r[0]), measures: [{ name: 'Change', values: bridge.map(r => r[1]), hl: bridge.map((r, i) => (i === 2 ? r[1] : null)) }], fmt: '\\$#,0', type: 'waterfall', objects: { waterfall: { startTotal: true } } }));
C('Ribbon · small tile', dv({ cat: 'Quarter', cats: qs, series: { name: 'Subcategory', groups: subs.map((s, k) => ({ name: s, values: qs.map((_, j) => rv(k, j)) })) }, measure: 'Sales', type: 'ribbon' }), { w: 300, h: 200 });
C('Candlestick without prices · hint', dv({ cat: 'Stage', cats: pipe.map(r => r[0]), measures: [{ name: 'Deals', values: pipe.map(r => r[1]) }], type: 'candlestick' }), { w: 360, h: 200 });
// 16: labels fixed to millions on a bridge whose steps are thousands: a step is never shown as $0M (2026-11-12)
C('Waterfall · bridge fixed to millions, small steps · no $0M', dv({ cat: 'Driver', cats: ['Last year', 'Bikes - Online', 'Bikes - Retail', 'Components', 'Clothing', 'Accessories'], measures: [{ name: 'Change', values: [5910000, 240000, -59000, 15000, 33000, -4000] }], fmt: '$#,0', type: 'waterfall', objects: { labels: { show: true, displayUnits: 1000000, decimals: 0 }, waterfall: { startTotal: true, endLabel: 'This year' } } }), { w: 820, h: 320 });
