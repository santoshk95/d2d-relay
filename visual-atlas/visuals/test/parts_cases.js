// Test cases for Atlas Parts in the mock host.
const GUID = Object.keys(powerbi.visuals.plugins)[0];
const D = window.DATA;
function dv(o) {
  const cats = (o.levels || [{ name: o.cat, values: o.cats }]).map(l => ({ source: { displayName: l.name, queryName: 't.' + l.name, roles: { category: true }, type: { text: true } }, values: l.values }));
  let values;
  if (o.series) {
    const groups = o.series.groups.map(g => ({ name: g.name, values: [{ source: { displayName: o.measure, queryName: 'm.' + o.measure, roles: { values: true }, isMeasure: true, format: o.fmt || '#,0', groupName: g.name }, values: g.values }], identity: { key: g.name } }));
    values = groups.map(g => g.values[0]); values.source = { displayName: o.series.name, queryName: 't.' + o.series.name, roles: { series: true } }; values.grouped = () => groups;
  } else {
    values = o.measures.map(mm => { const c = { source: { displayName: mm.name, queryName: 'm.' + mm.name, roles: { values: true }, isMeasure: true, format: mm.fmt || o.fmt || '#,0' }, values: mm.values }; if (mm.hl) c.highlights = mm.hl; return c; });
    values.grouped = () => [{ values: values.slice() }];
  }
  const objects = Object.assign({}, o.objects || {});
  objects.chart = Object.assign({ chartType: o.type || 'pie' }, objects.chart || {});
  return { metadata: { columns: [], objects, dataRoles: o.drill ? { drillableRoles: { category: o.drill } } : {} }, categorical: { categories: cats, values } };
}
const C = (title, d, o) => { try { return renderCase(GUID, title, d, o || {}); } catch (e) { LOG.push(['THROW', title, String(e && e.stack || e)]); } };
const cats4 = ['Bikes', 'Components', 'Clothing', 'Accessories'], cat4s = cats4.map(c => D.hp.filter(r => r[0] === c).reduce((a, r) => a + r[3], 0));
const subs = [...new Set(D.hp.map(r => r[1]))], subS = subs.map(sb => D.hp.filter(r => r[1] === sb).reduce((a, r) => a + r[3], 0));
const chans = ['Online', 'Retail', 'Partner'], chanTot = chans.map(c => D.chan.filter(r => r[1] === c).reduce((a, r) => a + r[2], 0));
const cs = D.hp.map(r => [r[0], r[1]]).filter((x, i, a) => a.findIndex(y => y[0] === x[0] && y[1] === x[1]) === i);

// 0-5 pie
C('Pie · legend on the right', dv({ cat: 'Category', cats: cats4, measures: [{ name: 'Sales', values: cat4s }], fmt: '\\$#,0', objects: { legend: { position: 'right' } } }));
C('Pie · labels outside with leader lines', dv({ cat: 'Subcategory', cats: subs, measures: [{ name: 'Sales', values: subS }], fmt: '\\$#,0', objects: { legend: { show: false } } }));
C('Pie · category, value and share', dv({ cat: 'Category', cats: cats4, measures: [{ name: 'Sales', values: cat4s }], fmt: '\\$#,0', objects: { slices: { content: 'all' }, legend: { show: false } } }));
C('Pie · top 5 plus Other', dv({ cat: 'Subcategory', cats: subs, measures: [{ name: 'Sales', values: subS }], fmt: '\\$#,0', objects: { chart: { topN: 5 } } }));
C('Pie · drill: Category › Subcategory expanded · buttons', dv({ levels: [{ name: 'Category', values: cs.map(x => x[0]) }, { name: 'Subcategory', values: cs.map(x => x[1]) }], measures: [{ name: 'Sales', values: cs.map(x => D.hp.filter(r => r[0] === x[0] && r[1] === x[1]).reduce((a, r) => a + r[3], 0)) }], fmt: '\\$#,0', drill: [1, 2, 3], objects: { slices: { labelPosition: 'auto', content: 'percent' } } }));
C('Pie · legend bottom · rotated · no labels · flat', dv({ cat: 'Category', cats: cats4, measures: [{ name: 'Sales', values: cat4s }], fmt: '\\$#,0', objects: { chart: { look: 'flat', startAngle: 90 }, labels: { show: false }, legend: { position: 'bottomCenter' } } }));
// 6-11 donut
C('Donut · three channels', dv({ cat: 'Channel', cats: chans, measures: [{ name: 'Revenue', values: chanTot }], fmt: '\\$#,0', type: 'donut' }));
C('Donut · thin ring · inside labels', dv({ cat: 'Channel', cats: chans, measures: [{ name: 'Revenue', values: chanTot }], fmt: '\\$#,0', type: 'donut', objects: { chart: { hole: 82 }, slices: { labelPosition: 'auto', content: 'percent' } } }));
C('Donut · total in the center · 3D', dv({ cat: 'Category', cats: cats4, measures: [{ name: 'Sales', values: cat4s }], fmt: '\\$#,0', type: 'donut', objects: { chart: { look: '3d' }, slices: { centerLabel: 'Sales 2025' } } }));
C('Donut · progress ring (68% done)', dv({ cat: 'Status', cats: ['Done', 'Remaining'], measures: [{ name: 'Tasks', values: [68, 32] }], type: 'donut', objects: { chart: { sort: 'none', hole: 72 }, slices: { track: true }, labels: { show: false }, legend: { show: false } } }));
C('Donut · half circle', dv({ cat: 'Channel', cats: chans, measures: [{ name: 'Revenue', values: chanTot }], fmt: '\\$#,0', type: 'donut', objects: { chart: { half: true } } }));
C('Donut · details ring (category by channel)', dv({ cat: 'Category', cats: cats4, series: { name: 'Channel', groups: chans.map((ch, k) => ({ name: ch, values: cat4s.map((v, i) => Math.round(v * [0.45, 0.35, 0.2][k] * (1 + (i - k) * 0.06))) })) }, measure: 'Sales', fmt: '\\$#,0', type: 'donut', objects: { slices: { labelPosition: 'auto', content: 'percent' } } }));
// 12-16 modes and edge cases
C('Pie · high contrast', dv({ cat: 'Category', cats: cats4, measures: [{ name: 'Sales', values: cat4s }], fmt: '\\$#,0' }), { hc: true });
C('Donut · dark', dv({ cat: 'Category', cats: cats4, measures: [{ name: 'Sales', values: cat4s }], fmt: '\\$#,0', type: 'donut' }), { dark: true });
C('Landing page (no fields)', null);
C('Donut · cross-highlighted (bikes)', dv({ cat: 'Category', cats: cats4, measures: [{ name: 'Sales', values: cat4s, hl: cat4s.map((v, i) => (i === 0 ? v : null)) }], fmt: '\\$#,0', type: 'donut' }));
C('Pie · small tile', dv({ cat: 'Subcategory', cats: subs, measures: [{ name: 'Sales', values: subS }], fmt: '\\$#,0' }), { w: 300, h: 200 });
// a selection in another visual covers part of every slice (Online sales of each category): the donut shows those parts
C('Donut · same data, no highlight', dv({ cat: 'Category', cats: cats4, measures: [{ name: 'Sales', values: cat4s }], fmt: '\$#,0', type: 'donut' }));
C('Donut · partly highlighted (online share of each)', dv({ cat: 'Category', cats: cats4, measures: [{ name: 'Sales', values: cat4s, hl: cat4s.map((v, i) => v * [0.6, 0.3, 0.5, 0.2][i]) }], fmt: '\$#,0', type: 'donut' }));
