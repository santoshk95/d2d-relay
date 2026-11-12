// Test cases for Atlas Compare in the mock host.
const GUID = Object.keys(powerbi.visuals.plugins)[0];
const D = window.DATA;
/* categorical data view: one category column, measures or a legend (same shape as Atlas Columns) */
function dv(o) {
  const cats = [{ source: { displayName: o.cat, queryName: 't.' + o.cat, roles: { category: true }, type: { text: true } }, values: o.cats, objects: o.catObjects }];
  let values;
  if (o.series) {
    const groups = o.series.groups.map(g => {
      const col = { source: { displayName: o.measure, queryName: 'm.' + o.measure, roles: { values: true }, isMeasure: true, format: o.fmt || '#,0', groupName: g.name }, values: g.values };
      if (g.hl) col.highlights = g.hl;
      return { name: g.name, values: [col], objects: g.objects, identity: { key: g.name } };
    });
    values = groups.map(g => g.values[0]);
    values.source = { displayName: o.series.name, queryName: 't.' + o.series.name, roles: { series: true } };
    values.grouped = () => groups;
  } else {
    values = o.measures.map(mm => { const c = { source: { displayName: mm.name, queryName: 'm.' + mm.name, roles: { values: true }, isMeasure: true, format: mm.fmt || o.fmt || '#,0', objects: mm.objects }, values: mm.values }; if (mm.hl) c.highlights = mm.hl; return c; });
    (o.tips || []).forEach(t => values.push({ source: { displayName: t.name, queryName: 'm.' + t.name, roles: { tooltips: true }, isMeasure: true, format: '#,0' }, values: t.values }));
    values.grouped = () => [{ values: values.slice() }];
  }
  const objects = Object.assign({}, o.objects || {});
  if (o.type) objects.chart = Object.assign({ chartType: o.type }, objects.chart || {});
  return { metadata: { columns: [], objects }, categorical: { categories: cats, values } };
}
const C = (title, d, o) => { try { return renderCase(GUID, title, d, o || {}); } catch (e) { LOG.push(['THROW', title, String(e && e.stack || e)]); } };
const sum = (rows, key, v) => { const m = new Map(); rows.forEach(r => m.set(key(r), (m.get(key(r)) || 0) + v(r))); return m; };

const top12 = D.hp.slice().sort((a, b) => b[3] - a[3]).slice(0, 12);
const months = D.months;
const by = (y) => months.map(mm => (D.hd.find(r => r[0] === y && r[2] === mm) || [0, 0, 0, 0])[3]);
const s24 = by('2024'), s25 = by('2025'), yoy = months.map((_, i) => +((s25[i] / s24[i] - 1) * 100).toFixed(1));
const chans = ['Online', 'Retail', 'Partner'], chanVal = (mm, c) => (D.chan.find(r => r[0] === mm && r[1] === c) || [0, 0, 0])[2];
const subs = [...new Set(D.hp.map(r => r[1]))];
const subSales = sum(D.hp, r => r[1], r => r[3]);
const growth = s => 0.82 + ((s.length * 17) % 40) / 100;

// 0-4: list charts
C('Lollipop · ranked products · labels', dv({ cat: 'Product', cats: top12.map(r => r[2]), measures: [{ name: 'Sales', values: top12.map(r => r[3]) }], fmt: '\\$#,0', type: 'lollipop', objects: { chart: { sort: 'valueDesc' }, labels: { show: true } } }));
C('Lollipop · vertical · diverging change (sign colors)', dv({ cat: 'Month', cats: months, measures: [{ name: 'vs last year', values: yoy, fmt: '0.0' }], type: 'lollipop', objects: { chart: { orientation: 'vertical' }, marks: { colorBy: 'sign' }, labels: { show: true } } }));
C('Dot plot · channels by month · legend', dv({ cat: 'Month', cats: months, series: { name: 'Channel', groups: chans.map(c => ({ name: c, values: months.map(mm => chanVal(mm, c)) })) }, measure: 'Revenue', fmt: '\\$#,0', type: 'dot', objects: { chart: { look: 'flat' } } }));
C('Dumbbell · 2024 vs 2025 · sorted by change · % labels', dv({ cat: 'Month', cats: months, measures: [{ name: 'Sales 2024', values: s24 }, { name: 'Sales 2025', values: s25 }], fmt: '\\$#,0', type: 'dumbbell', objects: { chart: { sort: 'changeDesc' }, labels: { show: true } } }));
const pr = subs.map((sb, k) => { const lo = 120 + (k * 83) % 400, hi = lo + 180 + (k * 131) % 900; return [sb, lo, Math.round(lo + (hi - lo) * (0.3 + (k % 5) * 0.08)), hi]; });
C('Dumbbell · price range (min, avg, max) · 3D', dv({ cat: 'Subcategory', cats: pr.map(r => r[0]), measures: [{ name: 'Min price', values: pr.map(r => r[1]) }, { name: 'Avg price', values: pr.map(r => r[2]) }, { name: 'Max price', values: pr.map(r => r[3]) }], fmt: '\\$#,0', type: 'dumbbell', objects: { chart: { look: '3d' } } }));
// 5-8: slope and bump
C('Slope · subcategories 2024 to 2025', dv({ cat: 'Subcategory', cats: subs.slice(0, 7), measures: [{ name: '2024', values: subs.slice(0, 7).map(s => subSales.get(s)) }, { name: '2025', values: subs.slice(0, 7).map(s => Math.round(subSales.get(s) * growth(s))) }], fmt: '\\$#,0', type: 'slope' }));
C('Slope · focus one line · three periods', dv({ cat: 'Subcategory', cats: subs.slice(0, 7), measures: ['2023', '2024', '2025'].map((y, k) => ({ name: y, values: subs.slice(0, 7).map(s => Math.round(subSales.get(s) * (1 + (growth(s) - 1) * k))) })), fmt: '\\$#,0', type: 'slope', objects: { chart: { focus: subs[2] } } }));
const qs = []; ['2024', '2025'].forEach(y => ['Q1', 'Q2', 'Q3', 'Q4'].forEach(q => qs.push(y + ' ' + q)));
const bumpSubs = subs.slice(0, 6), bv = (s, k) => Math.round(subSales.get(s) * (1 + ((s.length * 7 + k * (s.length % 5 + 1) * 13) % 37 - 18) / 60));
C('Bump · subcategory rank by quarter · rank labels', dv({ cat: 'Quarter', cats: qs, series: { name: 'Subcategory', groups: bumpSubs.map(s => ({ name: s, values: qs.map((_, k) => bv(s, k)) })) }, measure: 'Sales', fmt: '\\$#,0', type: 'bump', objects: { labels: { show: true }, marks: { size: 9 } } }));
C('Bump · follow one line · dark', dv({ cat: 'Quarter', cats: qs, series: { name: 'Subcategory', groups: bumpSubs.map(s => ({ name: s, values: qs.map((_, k) => bv(s, k)) })) }, measure: 'Sales', fmt: '\\$#,0', type: 'bump', objects: { chart: { focus: bumpSubs[3] }, marks: { smooth: false } } }), { dark: true });
// 9-10: tornado
const ages = ['16-24', '25-34', '35-44', '45-54', '55-64', '65+'], women = [820, 1460, 1720, 1510, 1080, 640], men = [910, 1380, 1590, 1620, 1150, 520];
C('Tornado · customers by age and gender', dv({ cat: 'Age band', cats: ages, measures: [{ name: 'Women', values: women }, { name: 'Men', values: men }], type: 'tornado', objects: { labels: { show: true }, legend: { position: 'bottomCenter' } } }));
const drivers = ['Price', 'Volume', 'Material cost', 'Freight', 'FX rate', 'Labor'], lowC = [72, 80, 88, 93, 95, 97], highC = [131, 122, 109, 106, 104, 103];
C('Tornado · profit sensitivity around plan (100)', dv({ cat: 'Driver', cats: drivers, measures: [{ name: 'Low case', values: lowC }, { name: 'High case', values: highC }], type: 'tornado', objects: { tornado: { mode: 'base', base: 100 }, chart: { sort: 'changeDesc' }, labels: { show: true } } }));
// 11-13: radar
const attrs = ['Price', 'Quality', 'Range', 'Service', 'Delivery', 'Design'];
C('Radar · two brands · soft', dv({ cat: 'Attribute', cats: attrs, series: { name: 'Brand', groups: [{ name: 'Our bikes', values: [7, 8.5, 6, 9, 7.5, 8] }, { name: 'Market leader', values: [6, 8, 9, 6.5, 8, 7] }] }, measure: 'Score', fmt: '0.0', type: 'radar', objects: { radar: { max: '10' } } }));
C('Radar · circular grid · one series · 3D · labels', dv({ cat: 'Attribute', cats: attrs, measures: [{ name: 'Score', values: [7, 8.5, 6, 9, 7.5, 8], fmt: '0.0' }], type: 'radar', objects: { chart: { look: '3d' }, radar: { grid: 'circle', max: '10' }, labels: { show: true } } }));
C('Radar · one radar per series (small multiples)', dv({ cat: 'Attribute', cats: attrs, series: { name: 'Category', groups: ['Bikes', 'Components', 'Clothing', 'Accessories'].map((g, k) => ({ name: g, values: attrs.map((a, j) => 4 + ((k * 3 + j * 5) % 6)) })) }, measure: 'Score', fmt: '0.0', type: 'radar', objects: { radar: { multiples: true, max: '10' } } }));
// 14-18: modes and edge cases
C('Lollipop · high contrast', dv({ cat: 'Product', cats: top12.map(r => r[2]), measures: [{ name: 'Sales', values: top12.map(r => r[3]) }], fmt: '\\$#,0', type: 'lollipop' }), { hc: true });
C('Landing page (no fields)', null);
C('Bump with one series · hint', dv({ cat: 'Quarter', cats: qs, measures: [{ name: 'Sales', values: qs.map((_, k) => 100 + k) }], type: 'bump' }), { w: 360, h: 200 });
C('Dumbbell · vertical · squares · cross-highlighted', dv({ cat: 'Month', cats: months, measures: [{ name: 'Sales 2024', values: s24, hl: s24.map((v, i) => (i % 3 === 0 ? v : null)) }, { name: 'Sales 2025', values: s25, hl: s25.map((v, i) => (i % 3 === 0 ? v : null)) }], fmt: '\\$#,0', type: 'dumbbell', tips: [{ name: 'Orders', values: months.map((_, i) => 400 + i * 13) }], objects: { chart: { orientation: 'vertical', look: 'flat' }, marks: { shape: 'square' } } }));
C('Lollipop · 48 products in a small tile', dv({ cat: 'Product', cats: D.hp.map(r => r[2]), measures: [{ name: 'Sales', values: D.hp.map(r => r[3]) }], fmt: '\\$#,0', type: 'lollipop', objects: { chart: { sort: 'valueDesc' } } }), { w: 300, h: 220 });
// 19-20: a dumbbell's end label is a change that means something (2026-11-12)
C('Dumbbell · growth online vs retail (percentages, opposite signs) · labels in points', dv({ cat: 'Category', cats: ['Accessories', 'Components', 'Clothing', 'Bikes'], measures: [{ name: 'Online growth', values: [0.256, 0.231, 0.27, 0.249], fmt: '0.0%' }, { name: 'Retail growth', values: [-0.096, -0.089, -0.103, -0.111], fmt: '0.0%' }], type: 'dumbbell', objects: { labels: { show: true } } }), { w: 620, h: 300 });
C('Dumbbell · profit that turns into a loss · difference labels', dv({ cat: 'Region', cats: ['North', 'South', 'East'], measures: [{ name: 'Profit 2024', values: [120000, 45000, -20000] }, { name: 'Profit 2025', values: [-30000, 60000, 15000] }], fmt: '$#,0', type: 'dumbbell', objects: { labels: { show: true } } }), { w: 620, h: 260 });
