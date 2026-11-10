// Test cases for Atlas Columns in the mock host.
const GUID = Object.keys(powerbi.visuals.plugins)[0];
const D = window.DATA;
function colDV(o) {
  const cats = (o.levels || []).map(l => ({ source: { displayName: l.name, queryName: 't.' + l.name, roles: { category: true }, type: { text: true } }, values: l.values, objects: l.objects }));
  let values;
  const tipCols = (o.tips || []).map(t => ({ source: { displayName: t.name, queryName: 'm.' + t.name, roles: { tooltips: true }, isMeasure: true, format: t.fmt || '#,0' }, values: t.values }));
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
    values = o.measures.map(mm => { const c = { source: { displayName: mm.name, queryName: 'm.' + mm.name, roles: { values: true }, isMeasure: true, format: mm.fmt || o.fmt || '#,0', objects: mm.objects }, values: mm.values }; if (mm.hl) c.highlights = mm.hl; return c; }).concat(tipCols);
    values.grouped = () => [{ values: values.slice() }];
  }
  return { metadata: { columns: [], objects: o.objects || {}, dataRoles: o.drill ? { drillableRoles: { category: o.drill } } : {} }, categorical: { categories: cats, values } };
}
const sum = (rows, key, val) => { const m = new Map(); rows.forEach(r => { const k = key(r); m.set(k, (m.get(k) || 0) + val(r)); }); return m; };
const C = (title, dv, o) => { try { const w = renderCase(GUID, title, dv, o || {}); return w; } catch (e) { LOG.push(['THROW', title, String(e && e.stack || e)]); } };

const years = ['2023', '2024', '2025'];
const ys = sum(D.hd, r => r[0], r => r[3]), yp = sum(D.hd, r => r[0], r => r[4]);
C('Clustered column · soft · report theme', colDV({ levels: [{ name: 'Year', values: years }], measures: [{ name: 'Sales', values: years.map(y => ys.get(y)) }, { name: 'Profit', values: years.map(y => yp.get(y)) }], fmt: '\\$#,0', objects: { labels: { show: true } } }));

const months = D.months, chans = ['Online', 'Retail', 'Partner'];
const chanVal = (m, c) => (D.chan.find(r => r[0] === m && r[1] === c) || [0, 0, 0])[2];
C('Stacked column · flat · total labels', colDV({ levels: [{ name: 'Month', values: months }], series: { name: 'Channel', groups: chans.map(c => ({ name: c, values: months.map(m => chanVal(m, c)) })) }, measure: 'Revenue', fmt: '\\$#,0', objects: { chart: { chartType: 'stackedColumn', look: 'flat' } } }));

const qOf = m => 'Q' + (Math.floor(months.indexOf(m) / 3) + 1), qs = ['Q1', 'Q2', 'Q3', 'Q4'];
C('100% stacked bar · 3D · brand color · percent labels', colDV({ levels: [{ name: 'Quarter', values: qs }], series: { name: 'Channel', groups: chans.map(c => ({ name: c, values: qs.map(q => months.filter(m => qOf(m) === q).reduce((s, m) => s + chanVal(m, c), 0)) })) }, measure: 'Revenue', objects: { chart: { chartType: 'percentBar', look: '3d' }, palette: { source: 'brand', brand: { solid: { color: '#7c3aed' } } }, labels: { show: true, content: 'percent' } } }));

const prods = D.hp.slice().sort((a, b) => b[3] - a[3]).slice(0, 12);
C('Clustered bar · lollipop · brand palette', colDV({ levels: [{ name: 'Product', values: prods.map(r => r[2]) }], measures: [{ name: 'Sales', values: prods.map(r => r[3]) }], fmt: '\\$#,0', objects: { chart: { chartType: 'clusteredBar', shape: 'lollipop' }, palette: { source: 'brand', brand: { solid: { color: '#0f766e' } } }, labels: { show: true } } }));

const yq = []; years.forEach(y => ['Qtr 1', 'Qtr 2', 'Qtr 3', 'Qtr 4'].forEach(q => yq.push([y, q])));
const yqs = sum(D.hd, r => r[0] + '|' + r[1], r => r[3]), yqp = sum(D.hd, r => r[0] + '|' + r[1], r => r[4]);
C('Expanded hierarchy · Year › Quarter · drill buttons', colDV({ levels: [{ name: 'Year', values: yq.map(x => x[0]) }, { name: 'Quarter', values: yq.map(x => x[1]) }], measures: [{ name: 'Sales', values: yq.map(x => yqs.get(x[0] + '|' + x[1])) }, { name: 'Profit', values: yq.map(x => yqp.get(x[0] + '|' + x[1])) }], fmt: '\\$#,0', drill: [1, 2, 3] }));

const m24 = D.hd.filter(r => r[0] === '2024');
C('Drilled into 2024 · stacked by channel', colDV({ levels: [{ name: 'Month', values: m24.map(r => r[2]) }], series: { name: 'Channel', groups: chans.map((c, k) => ({ name: c, values: m24.map(r => Math.round(r[3] * [0.42, 0.38, 0.2][k])) })) }, measure: 'Sales', fmt: '\\$#,0', drill: [1, 2, 3], objects: { chart: { chartType: 'stackedColumn' }, totals: { show: false }, legend: { position: 'bottomCenter' } } }));

C('Cross-highlighted · stacked column', colDV({ levels: [{ name: 'Month', values: months }], series: { name: 'Channel', groups: chans.map((c, k) => ({ name: c, values: months.map(m => chanVal(m, c)), hl: months.map(m => Math.round(chanVal(m, c) * [0.55, 0.3, 0.7][k])) })) }, measure: 'Revenue', objects: { chart: { chartType: 'stackedColumn' }, totals: { show: false } } }));

const target = 600000, vari = m24.map(r => r[3] - target);
C('Variance · negatives · average line · pill', colDV({ levels: [{ name: 'Month', values: m24.map(r => r[2]) }], measures: [{ name: 'Variance to target', values: vari }], fmt: '\\$#,0', objects: { chart: { shape: 'pill', spacing: 40 }, refLine: { show: true }, labels: { show: true, displayUnits: 1000 } } }));

const days = Array.from({ length: 120 }, (_, i) => 'Day ' + (i + 1));
C('Scrolls when crowded · 120 categories', colDV({ levels: [{ name: 'Day', values: days }], measures: [{ name: 'Orders', values: days.map((_, i) => Math.round(200 + 120 * Math.sin(i / 9) + 40 * Math.cos(i / 3.7))) }], objects: { chart: { look: 'flat' } } }));

C('Dark theme · stacked bar · soft · legend right', colDV({ levels: [{ name: 'Month', values: months.slice(0, 8) }], series: { name: 'Channel', groups: chans.map(c => ({ name: c, values: months.slice(0, 8).map(m => chanVal(m, c)) })) }, measure: 'Revenue', fmt: '\\$#,0', objects: { chart: { chartType: 'stackedBar' }, legend: { position: 'right' } } }), { dark: true });

const catS = sum(D.hp, r => r[0], r => r[3]), catNames = [...catS.keys()];
C('Color each category · custom list · square', colDV({ levels: [{ name: 'Category', values: catNames }], measures: [{ name: 'Sales', values: catNames.map(k => catS.get(k)) }], fmt: '\\$#,0', objects: { chart: { shape: 'square' }, palette: { source: 'custom', custom: '#1d4ed8, #db2777, #ca8a04, #059669', varyByCategory: true }, labels: { show: true, position: 'insideEnd' }, valueAxis: { title: true }, categoryAxis: { title: true } } }));

C('Concatenated labels · 3D clustered column', colDV({ levels: [{ name: 'Year', values: yq.slice(4).map(x => x[0]) }, { name: 'Quarter', values: yq.slice(4).map(x => x[1]) }], measures: [{ name: 'Sales', values: yq.slice(4).map(x => yqs.get(x[0] + '|' + x[1])) }, { name: 'Profit', values: yq.slice(4).map(x => yqp.get(x[0] + '|' + x[1])) }], fmt: '\\$#,0', objects: { chart: { look: '3d' }, categoryAxis: { concatenate: true } } }));

C('High contrast · clustered column', colDV({ levels: [{ name: 'Year', values: years }], measures: [{ name: 'Sales', values: years.map(y => ys.get(y)) }, { name: 'Profit', values: years.map(y => yp.get(y)) }], fmt: '\\$#,0' }), { hc: true });
renderCase(GUID, 'No fields yet (landing page)', null, {});

const subs = []; D.hp.forEach(r => { if (!subs.find(x => x[0] === r[0] && x[1] === r[1])) subs.push([r[0], r[1]]); });
const subS = sum(D.hp, r => r[0] + '|' + r[1], r => r[3]), subP = sum(D.hp, r => r[0] + '|' + r[1], r => r[4]);
C('Clustered bar · Category › Subcategory tiers', colDV({ levels: [{ name: 'Category', values: subs.map(x => x[0]) }, { name: 'Subcategory', values: subs.map(x => x[1]) }], measures: [{ name: 'Sales', values: subs.map(x => subS.get(x[0] + '|' + x[1])) }], fmt: '\\$#,0', drill: [1, 3], objects: { chart: { chartType: 'clusteredBar', look: 'flat' }, palette: { source: 'brand', brand: { solid: { color: '#c2410c' } } }, labels: { show: true } } }), { h: 520 });
const regions = ['North', 'South', 'East', 'West', 'Central', 'Online'];
C('Stacked column · gains and losses', colDV({ levels: [{ name: 'Region', values: regions }], series: { name: 'Line', groups: [{ name: 'Bikes', values: [320, 210, -60, 180, 90, 260] }, { name: 'Parts', values: [80, -40, -120, 60, 30, 110] }, { name: 'Service', values: [40, 25, -15, -30, 20, 70] }] }, measure: 'Margin', fmt: '\\$#,0K', objects: { chart: { chartType: 'stackedColumn', look: 'soft' }, labels: { show: true }, refLine: { show: true, kind: 'constant', value: 300 }, palette: { source: 'brand', brand: { solid: { color: '#0e7490' } }, mode: 'analogous' } } }), { h: 520 });

C('Conditional colors (fx rule results)', colDV({ levels: [{ name: 'Month', values: m24.map(r => r[2]), objects: vari.map(v => ({ dataColors: { fill: { solid: { color: v < 0 ? '#d64545' : '#1aab40' } } } })) }], measures: [{ name: 'Variance to target', values: vari }], fmt: '\\$#,0', objects: { chart: { look: 'soft' }, labels: { show: true } } }), { h: 300 });
