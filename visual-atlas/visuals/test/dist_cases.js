// Test cases for Atlas Distribution in the mock host.
const GUID = Object.keys(powerbi.visuals.plugins)[0];
const D = window.DATA;
// seeded generator so the sample data is the same on every run
let seed = 7;
const rnd = () => { seed = (seed * 1664525 + 1013904223) >>> 0; return seed / 4294967296; };
const gauss = () => { let u = 0, v = 0; while (!u) u = rnd(); while (!v) v = rnd(); return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v); };
const round = (x, d) => Math.round(x * 10 ** (d || 0)) / 10 ** (d || 0);

// observations: [group, id, value(s)...]
const orders = [];
for (let i = 0; i < 520; i++) orders.push(['Online', 'SO' + (10000 + i), round(Math.exp(5.2 + 0.45 * gauss()))]);
for (let i = 0; i < 380; i++) orders.push(['Retail', 'SO' + (20000 + i), round(Math.exp(5.75 + 0.35 * gauss()))]);
const carriers = [['Swift', 2.6, 0.8], ['Northline', 3.4, 1.1], ['Parcel+', 4.1, 1.6], ['Coastal', 3.0, 0.7], ['Freightway', 5.2, 1.9]];
const ship = [];
carriers.forEach(([c, mu, sd], k) => { for (let i = 0; i < 110; i++) ship.push([c, 'SH' + k + String(i).padStart(3, '0'), Math.max(0.5, round(mu + sd * gauss() + (i % 37 === 0 ? sd * 3.5 : 0), 1))]); });
const devices = ['App', 'Desktop', 'Tablet', 'Mobile web'];
const sess = [];
devices.forEach((dv, k) => { for (let i = 0; i < 160; i++) { const v = dv === 'App' ? (i % 2 ? 2.2 + 0.8 * gauss() : 11 + 2.4 * gauss()) : [0, 8.5, 6.4, 3.6][k] + [0, 2.8, 2.2, 1.4][k] * gauss(); sess.push([dv, 'S' + k + i, Math.max(0.2, round(v, 1))]); } });

/* categorical data view: Group and Sample by columns, one or more measures */
function distDV(rows, o) {
  o = o || {};
  const cats = [];
  if (o.group !== false) cats.push({ source: { displayName: o.groupName || 'Group', queryName: 't.Group', roles: { category: true }, type: { text: true } }, values: rows.map(r => r[0]), objects: o.groupObjects ? rows.map(r => o.groupObjects[r[0]]) : undefined });
  if (o.detail !== false) cats.push({ source: { displayName: o.detailName || 'ID', queryName: 't.ID', roles: { detail: true }, type: { text: true } }, values: rows.map(r => r[1]) });
  const ms = o.measures || [{ name: o.measure || 'Value', fmt: o.fmt }];
  const values = ms.map((mm, k) => {
    const c = { source: { displayName: mm.name, queryName: 'm.' + mm.name, roles: { values: true }, isMeasure: true, format: mm.fmt || '#,0.##' }, values: rows.map(r => r[2 + k]) };
    if (o.hl && k === 0) c.highlights = rows.map((r, i) => (o.hl(r, i) ? r[2] : null));
    return c;
  });
  (o.tips || []).forEach(t => values.push({ source: { displayName: t.name, queryName: 'm.' + t.name, roles: { tooltips: true }, isMeasure: true, format: t.fmt || '#,0' }, values: rows.map(t.f) }));
  values.grouped = () => [{ values: values.slice() }];
  const objects = Object.assign({}, o.objects || {});
  if (o.type) objects.chart = Object.assign({ chartType: o.type }, objects.chart || {});
  return { metadata: { columns: [], objects }, categorical: { categories: cats, values } };
}
const C = (title, dv, o) => { try { return renderCase(GUID, title, dv, o || {}); } catch (e) { LOG.push(['THROW', title, String(e && e.stack || e)]); } };
const ord1 = orders.map(r => ['All', r[1], r[2]]);

// 0-3 histograms
C('Histogram · soft · auto bins · labels', distDV(ord1, { group: false, measure: 'Order value', fmt: '\\$#,0', objects: { labels: { show: true } } }));
C('Histogram · two groups overlapping · flat', distDV(orders, { groupName: 'Channel', measure: 'Order value', fmt: '\\$#,0', objects: { chart: { look: 'flat' } } }));
C('Histogram · 3D · mean, median, normal curve', distDV(ord1, { group: false, measure: 'Order value', fmt: '\\$#,0', objects: { chart: { look: '3d' }, histogram: { normalCurve: true, binMode: 'count', binCount: 16 }, stats: { mean: true, median: true } } }));
C('Histogram · stacked · $50 bins · percent · brand', distDV(orders, { groupName: 'Channel', measure: 'Order value', fmt: '\\$#,0', objects: { histogram: { layout: 'stacked', binMode: 'width', binWidth: 50, yMeasure: 'percent' }, palette: { source: 'brand', brand: { solid: { color: '#7c3aed' } } }, legend: { position: 'bottomCenter' } } }));
// 4-7 box plots
C('Box · delivery days by carrier · soft', distDV(ship, { type: 'box', groupName: 'Carrier', detailName: 'Shipment', measure: 'Delivery days', fmt: '0.0', objects: { valueAxis: { title: true } } }));
C('Box · every point jittered · mean · flat', distDV(ship, { type: 'box', groupName: 'Carrier', detailName: 'Shipment', measure: 'Delivery days', fmt: '0.0', objects: { chart: { look: 'flat' }, box: { points: 'jitter', mean: true } } }));
C('Box · horizontal · sorted by median · 3D · labels', distDV(ship, { type: 'box', groupName: 'Carrier', detailName: 'Shipment', measure: 'Delivery days', fmt: '0.0', objects: { chart: { look: '3d', orientation: 'horizontal', sort: 'medianAsc' }, labels: { show: true }, categoryAxis: { title: true } } }));
C('Box · points beside · min-max whiskers · custom palette', distDV(ship, { type: 'box', groupName: 'Carrier', detailName: 'Shipment', measure: 'Delivery days', fmt: '0.0', objects: { box: { points: 'beside', whiskers: 'minmax', mean: true }, palette: { source: 'custom', custom: '#0f766e, #d97706, #be123c, #4338ca, #15803d' } } }));
// 8-11 violins
C('Violin · session length by device · soft', distDV(sess, { type: 'violin', groupName: 'Device', detailName: 'Session', measure: 'Minutes', fmt: '0.0' }));
C('Violin · box inside · horizontal · 3D', distDV(sess, { type: 'violin', groupName: 'Device', detailName: 'Session', measure: 'Minutes', fmt: '0.0', objects: { chart: { chartType: 'violin', look: '3d', orientation: 'horizontal' }, violin: { inner: 'box' } } }));
C('Raincloud · half violin, box, points · brand', distDV(sess, { type: 'violin', groupName: 'Device', detailName: 'Session', measure: 'Minutes', fmt: '0.0', objects: { chart: { chartType: 'violin' }, violin: { side: 'half', inner: 'box', points: 'jitter' }, palette: { source: 'brand', brand: { solid: { color: '#0e7490' } }, mode: 'analogous' }, labels: { show: true } } }));
C('Violin · quartiles · barcode · dark', distDV(sess, { type: 'violin', groupName: 'Device', detailName: 'Session', measure: 'Minutes', fmt: '0.0', objects: { chart: { chartType: 'violin' }, violin: { inner: 'quartiles', points: 'barcode', trim: false } } }), { dark: true });
// 12-13 parallel coordinates
const prows = D.hp.map(r => [r[0], r[2], r[3], r[4], round(r[4] / r[3] * 100, 1), Math.round(r[3] / (300 + (r[2].length * 37) % 900)), round(300 + (r[2].length * 37) % 900)]);
const pms = [{ name: 'Sales', fmt: '\\$#,0' }, { name: 'Profit', fmt: '\\$#,0' }, { name: 'Margin %', fmt: '0.0' }, { name: 'Units', fmt: '#,0' }, { name: 'Avg price', fmt: '\\$#,0' }];
C('Parallel coordinates · by category · soft', distDV(prows, { groupName: 'Category', detailName: 'Product', measures: pms, objects: { chart: { chartType: 'parallel' } } }), { w: 560, h: 340 });
C('Parallel · cross-highlighted · smooth · all ticks', distDV(prows, { groupName: 'Category', detailName: 'Product', measures: pms, hl: r => r[0] === 'Bikes', objects: { chart: { chartType: 'parallel' }, parallel: { curve: 'smooth', ticks: 'full', opacity: 45 }, legend: { position: 'right' } } }));
// 14-17 modes and edge cases
C('Box · high contrast', distDV(ship, { type: 'box', groupName: 'Carrier', detailName: 'Shipment', measure: 'Delivery days', fmt: '0.0', objects: { chart: { chartType: 'box' }, box: { mean: true } } }), { hc: true });
C('Histogram · dark · cross-highlighted (retail)', distDV(orders, { groupName: 'Channel', measure: 'Order value', fmt: '\\$#,0', hl: r => r[0] === 'Retail' || +r[1].slice(2) % 4 === 0, objects: { histogram: { layout: 'stacked' } } }), { dark: true });
const twoM = orders.map(r => ['', r[1], r[2], round(r[2] * (0.18 + 0.1 * rnd()))]);
C('Box · no group, two measures · by measure', distDV(twoM, { group: false, measures: [{ name: 'Order value', fmt: '\\$#,0' }, { name: 'Margin', fmt: '\\$#,0' }], objects: { chart: { chartType: 'box' }, box: { mean: true } } }));
C('Landing page (no fields)', null);
// 18-21
C('Parallel with one measure · hint', distDV(prows, { groupName: 'Category', detailName: 'Product', measures: pms.slice(0, 1), objects: { chart: { chartType: 'parallel' } } }), { w: 360, h: 200 });
C('Violin · small tile', distDV(sess, { type: 'violin', groupName: 'Device', detailName: 'Session', measure: 'Minutes', fmt: '0.0', objects: { chart: { chartType: 'violin' }, violin: { inner: 'box' } } }), { w: 300, h: 200 });
C('Histogram · every value the same', distDV(ord1.slice(0, 40).map(r => [r[0], r[1], 120]), { group: false, measure: 'Order value', fmt: '\\$#,0' }), { w: 360, h: 200 });
C('Box · blanks and a one-value group · tooltips', distDV(ship.slice(0, 120).map((r, i) => (i % 9 === 0 ? [r[0], r[1], null] : r)).concat([['Solo', 'X1', 4.2]]), { type: 'box', groupName: 'Carrier', detailName: 'Shipment', measure: 'Delivery days', fmt: '0.0', tips: [{ name: 'Weight kg', f: r => (r[1].length * 3.7) % 20 }], objects: { chart: { chartType: 'box' }, box: { points: 'jitter' } } }), { w: 360, h: 200 });

