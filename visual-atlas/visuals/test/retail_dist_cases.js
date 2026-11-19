// Retail cases for Relay Distribution: basket sizes, store comps by division, weekly store sales. Data from retail_data.js.
let sd = 7; const rn = () => { sd = (sd * 1664525 + 1013904223) >>> 0; return sd / 4294967296; };
const baskets = Array.from({ length: 1500 }, (_, i) => ['All', 'T' + i, RT.round(Math.max(1.5, 12 + 45 * Math.pow(rn(), 1.7) + (rn() < 0.06 ? 120 * rn() : 0)), 2)]);
const cs = RT.stores.filter(s => s.ly);
// 0 histogram of basket values
C('Histogram - basket value per transaction', RDV({ cats: [{ name: 'Group', values: baskets.map(r => r[0]) }, { name: 'Transaction', role: 'detail', values: baskets.map(r => r[1]) }], measures: [{ name: 'Basket Value', values: baskets.map(r => r[2]) }], fmt: FMT.usd2, type: 'histogram', objects: { labels: { show: true } } }), { w: 620, h: 320 });
// 1 box: store comp % by division, long names
C('Box - store comp % by division', RDV({ cats: [{ name: 'Division', values: cs.map(s => s.division) }, { name: 'Store', role: 'detail', values: cs.map(s => s.name) }], measures: [{ name: 'Identical Store Sales %', values: cs.map(s => RT.round(s.sales / s.ly - 1, 4)) }], fmt: FMT.comp, type: 'box', objects: { labels: { show: true } } }), { w: 620, h: 360 });
// 2 violin, dark: weekly sales per store by division
C('Violin - dark, average weekly sales per store by division', RDV({ cats: [{ name: 'Division', values: RT.stores.map(s => s.division) }, { name: 'Store', role: 'detail', values: RT.stores.map(s => s.name) }], measures: [{ name: 'Average Weekly Sales', values: RT.stores.map(s => RT.round(s.sales / 52, 0)) }], fmt: FMT.usd, type: 'violin' }), { dark: true, w: 620, h: 340 });
