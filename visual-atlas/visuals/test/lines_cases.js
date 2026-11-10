// Test cases for Atlas Lines in the mock host.
const GUID = Object.keys(powerbi.visuals.plugins)[0];
const D = window.DATA;
/* categorical data view: category levels, measures by role (values, lineValues, lower, upper) or a legend */
function dv(o) {
  const cats = (o.levels || []).map(l => ({ source: { displayName: l.name, queryName: 't.' + l.name, roles: { category: true }, type: { text: true } }, values: l.values }));
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
  objects.chart = Object.assign({ chartType: o.type || 'line' }, objects.chart || {});
  return { metadata: { columns: [], objects, dataRoles: o.drill ? { drillableRoles: { category: o.drill } } : {} }, categorical: { categories: cats, values } };
}
const C = (title, d, o) => { try { return renderCase(GUID, title, d, o || {}); } catch (e) { LOG.push(['THROW', title, String(e && e.stack || e)]); } };
const m36 = D.hd.map(r => r[2] + ' ' + r[0].slice(2)), s36 = D.hd.map(r => r[3]), p36 = D.hd.map(r => r[4]);
const months = D.months, by = y => months.map(mm => (D.hd.find(r => r[0] === y && r[2] === mm) || [0, 0, 0, 0])[3]);
const s24 = by('2024'), s25 = by('2025');
const chans = ['Online', 'Retail', 'Partner'], chanVal = (mm, c) => (D.chan.find(r => r[0] === mm && r[1] === c) || [0, 0, 0])[2];
const anom = s36.map((v, i) => (i === 9 ? v * 1.55 : i === 22 ? v * 0.4 : v));
const yq = []; ['2023', '2024', '2025'].forEach(y => ['Qtr 1', 'Qtr 2', 'Qtr 3', 'Qtr 4'].forEach(q => yq.push([y, q])));
const yqs = yq.map(([y, q]) => D.hd.filter(r => r[0] === y && r[1] === q).reduce((a, r) => a + r[3], 0));

// 0-11 lines
C('Line · three years of monthly sales', dv({ levels: [{ name: 'Month', values: m36 }], measures: [{ name: 'Sales', values: s36 }], fmt: '\\$#,0' }));
C('Line · this year vs last year (dashed) · last marker', dv({ levels: [{ name: 'Month', values: months }], measures: [{ name: 'Sales 2025', values: s25 }, { name: 'Sales 2024', values: s24 }], fmt: '\\$#,0', objects: { lines: { dashed: 'Sales 2024', markers: 'last', markerSize: 5 } } }));
C('Line · smooth · markers and labels', dv({ levels: [{ name: 'Month', values: months }], measures: [{ name: 'Sales', values: s25 }], fmt: '\\$#,0', objects: { chart: { curve: 'smooth' }, lines: { markers: 'all' }, labels: { show: true } } }));
C('Line · stepped (list price)', dv({ levels: [{ name: 'Month', values: months }], measures: [{ name: 'List price', values: [1199, 1199, 1199, 1249, 1249, 1249, 1249, 1299, 1299, 1199, 1149, 1149], fmt: '\\$#,0' }], objects: { chart: { curve: 'step' } } }));
C('Line · series names at the ends', dv({ levels: [{ name: 'Month', values: months }], series: { name: 'Channel', groups: chans.map(c => ({ name: c, values: months.map(mm => chanVal(mm, c)) })) }, measure: 'Revenue', fmt: '\\$#,0', objects: { lines: { endLabels: true } } }));
C('Line · forecast 6 months · trend line', dv({ levels: [{ name: 'Month', values: m36 }], measures: [{ name: 'Sales', values: s36 }], fmt: '\\$#,0', objects: { analytics: { forecast: 6, trend: true } } }));
C('Line · anomalies', dv({ levels: [{ name: 'Month', values: m36 }], measures: [{ name: 'Sales', values: anom }], fmt: '\\$#,0', objects: { analytics: { anomalies: true } } }));
C('Line · min, max, average · target zone', dv({ levels: [{ name: 'Month', values: months }], measures: [{ name: 'Sales', values: s25 }], fmt: '\\$#,0', objects: { analytics: { minMax: true, average: true, target: '850000' } } }));
C('Line · error band (lower and upper)', dv({ levels: [{ name: 'Month', values: months }], measures: [{ name: 'Sales', values: s25 }, { name: 'Low', role: 'lower', values: s25.map(v => v * 0.9) }, { name: 'High', role: 'upper', values: s25.map(v => v * 1.1) }], fmt: '\\$#,0' }));
C('Line · drill: Year › Quarter expanded · buttons', dv({ levels: [{ name: 'Year', values: yq.map(x => x[0]) }, { name: 'Quarter', values: yq.map(x => x[1]) }], measures: [{ name: 'Sales', values: yqs }], fmt: '\\$#,0', drill: [1, 2, 3], objects: { lines: { markers: 'all' } } }));
C('Line · zoom slider on 36 months', dv({ levels: [{ name: 'Month', values: m36 }], measures: [{ name: 'Sales', values: s36 }, { name: 'Profit', values: p36 }], fmt: '\\$#,0', objects: { chart: { zoom: true } } }));
C('Line · focus on one series', dv({ levels: [{ name: 'Month', values: months }], series: { name: 'Channel', groups: chans.map(c => ({ name: c, values: months.map(mm => chanVal(mm, c)) })) }, measure: 'Revenue', fmt: '\\$#,0', objects: { lines: { focus: 'Retail', width: 3 } } }));
// 12-16 areas and combos
C('Area · soft', dv({ levels: [{ name: 'Month', values: m36 }], measures: [{ name: 'Sales', values: s36 }], fmt: '\\$#,0', type: 'area' }));
C('Stacked area · smooth · channels', dv({ levels: [{ name: 'Month', values: months }], series: { name: 'Channel', groups: chans.map(c => ({ name: c, values: months.map(mm => chanVal(mm, c)) })) }, measure: 'Revenue', fmt: '\\$#,0', type: 'stackedArea', objects: { chart: { curve: 'smooth' } } }));
C('100% stacked area', dv({ levels: [{ name: 'Month', values: months }], series: { name: 'Channel', groups: chans.map(c => ({ name: c, values: months.map(mm => chanVal(mm, c)) })) }, measure: 'Revenue', fmt: '\\$#,0', type: 'percentArea' }));
C('Line and stacked column · margin on a secondary axis', dv({ levels: [{ name: 'Month', values: months }], measures: [{ name: 'Profit', values: by('2025').map((v, i) => p36[24 + i]) }, { name: 'Cost', values: s25.map((v, i) => v - p36[24 + i]) }, { name: 'Margin %', role: 'lineValues', values: s25.map((v, i) => p36[24 + i] / v), fmt: '0%' }], fmt: '\\$#,0', type: 'comboStacked', objects: { lines: { markers: 'all' } } }));
C('Line and clustered column · TY vs LY with growth % · 3D', dv({ levels: [{ name: 'Month', values: months }], measures: [{ name: 'Sales 2025', values: s25 }, { name: 'Sales 2024', values: s24 }, { name: 'Growth %', role: 'lineValues', values: s25.map((v, i) => v / s24[i] - 1), fmt: '0.0%' }], fmt: '\\$#,0', type: 'comboClustered', objects: { chart: { look: '3d' } } }));
// 17-20 modes and edge cases
C('Line · high contrast', dv({ levels: [{ name: 'Month', values: months }], measures: [{ name: 'Sales 2025', values: s25 }, { name: 'Sales 2024', values: s24 }], fmt: '\\$#,0' }), { hc: true });
C('Stacked area · dark', dv({ levels: [{ name: 'Month', values: months }], series: { name: 'Channel', groups: chans.map(c => ({ name: c, values: months.map(mm => chanVal(mm, c)) })) }, measure: 'Revenue', fmt: '\\$#,0', type: 'stackedArea' }), { dark: true });
C('Landing page (no fields)', null);
C('Line · cross-highlighted (Q2)', dv({ levels: [{ name: 'Month', values: months }], measures: [{ name: 'Sales', values: s25, hl: s25.map((v, i) => (i >= 3 && i <= 5 ? v : null)) }], fmt: '\\$#,0', objects: { lines: { markers: 'all' } } }));
// 21: another visual's selection highlights months 7 to 12 of 2024: the chart zooms to them and fades the rest of the line
C('Line · zoom slider · zooms to a highlighted range', dv({ levels: [{ name: 'Month', values: m36 }], measures: [{ name: 'Sales', values: s36, hl: s36.map((v, i) => (i >= 18 && i <= 23 ? v : null)) }], fmt: '\$#,0', objects: { chart: { zoom: true } } }));
