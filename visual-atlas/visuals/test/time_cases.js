// Test cases for Atlas Time in the mock host.
const GUID = Object.keys(powerbi.visuals.plugins)[0];
/* data view: Time (+ Rows) categories, values (optionally grouped by a Legend) */
function dv(o) {
  const cats = [{ source: { displayName: o.time, queryName: o.query || 'Orders.' + o.time, roles: { time: true }, type: o.dates ? { dateTime: true } : { text: true } }, values: o.times }];
  if (o.rows) cats.push({ source: { displayName: o.rowsName, queryName: 'Orders.' + o.rowsName, roles: { rows: true }, type: { text: true } }, values: o.rows });
  let values;
  if (o.series) {
    const groups = o.series.groups.map(g => { const col = { source: { displayName: o.measure, queryName: 'm.' + o.measure, roles: { values: true }, isMeasure: true, format: o.fmt || '#,0', groupName: g.name }, values: g.values }; if (g.hl) col.highlights = g.hl; return { name: g.name, values: [col], identity: { key: g.name } }; });
    values = groups.map(g => g.values[0]);
    values.source = { displayName: o.series.name, queryName: 't.' + o.series.name, roles: { series: true } };
    values.grouped = () => groups;
  } else {
    const col = { source: { displayName: o.measure, queryName: 'm.' + o.measure, roles: { values: true }, isMeasure: true, format: o.fmt || '#,0' }, values: o.values };
    if (o.hl) col.highlights = o.hl;
    values = [col]; values.grouped = () => [{ values: values.slice() }];
  }
  const objects = Object.assign({}, o.objects || {});
  objects.chart = Object.assign({ chartType: o.type }, objects.chart || {});
  return { metadata: { columns: [], objects }, categorical: { categories: cats, values } };
}
const C = (title, d, o) => { try { return renderCase(GUID, title, d, o || {}); } catch (e) { LOG.push(['THROW', title, String(e && e.stack || e)]); } };
/* daily orders: weekday pattern, a summer bulge and a Black Friday spike */
const days = (from, to) => { const out = []; for (let d = new Date(from); d <= to; d = new Date(d.getFullYear(), d.getMonth(), d.getDate() + 1)) out.push(d); return out; };
const orders = d => { const wk = [0.75, 1, 1.02, 1.05, 1.1, 1.3, 0.9][(d.getDay() + 6) % 7], season = 1 + 0.25 * Math.sin((d.getMonth() - 3) / 12 * 2 * Math.PI), spike = d.getMonth() === 10 && d.getDate() >= 27 && d.getDate() <= 30 ? 2.6 : 1; return Math.round(120 * wk * season * spike + ((d.getDate() * 37) % 23)); };
const y25 = days(new Date(2025, 0, 1), new Date(2025, 11, 31)), y2 = days(new Date(2024, 0, 1), new Date(2025, 11, 31));
const nd = days(new Date(2025, 10, 1), new Date(2025, 11, 31));
/* weekday by hour */
const wd = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'], hours = Array.from({ length: 24 }, (_, h) => (h < 10 ? '0' : '') + h + ':00');
const hg = []; wd.forEach((d, i) => hours.forEach((h, j) => { const wkend = i >= 5, base = wkend ? 30 * Math.exp(-((j - 13) ** 2) / 18) : 26 * Math.exp(-((j - 12.5) ** 2) / 3) + 34 * Math.exp(-((j - 20) ** 2) / 5); hg.push([d, h, Math.round(base + 2 + (i * 7 + j * 3) % 5)]); }));
/* streams: six subcategories over 24 months */
const subs = ['Road', 'Mountain', 'E-bike', 'Touring', 'Helmets', 'Jerseys'], m24 = []; for (let k = 0; k < 24; k++) m24.push(['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][k % 12] + ' ' + (24 + Math.floor(k / 12)));
const sv = (s, k) => Math.round((40 + s * 9) * (1 + 0.35 * Math.sin((k + s * 2) / 3)) * (s === 2 ? 0.4 + k / 14 : 1));

// 0-2 calendar
C('Calendar · a year of daily orders · color by rank', dv({ time: 'Order date', dates: true, times: y25, measure: 'Orders', values: y25.map(orders), type: 'calendar', objects: { scale: { mode: 'quantile' } } }));
C('Calendar · month pages · values', dv({ time: 'Order date', dates: true, times: nd, measure: 'Orders', values: nd.map(orders), type: 'calendar', objects: { calendar: { view: 'month' }, labels: { show: true } } }));
C('Calendar · two years · Sunday first · 5 steps · custom colors · flat', dv({ time: 'Order date', dates: true, times: y2, measure: 'Orders', values: y2.map(orders), type: 'calendar', objects: { chart: { look: 'flat' }, calendar: { weekStart: 'sunday' }, scale: { steps: 5, lowColor: { solid: { color: '#fef3c7' } }, highColor: { solid: { color: '#b45309' } } } } }));
// 3-5 heat grid
C('Heat grid · weekday by hour', dv({ time: 'Hour', times: hg.map(r => r[1]), rows: hg.map(r => r[0]), rowsName: 'Weekday', measure: 'Orders', values: hg.map(r => r[2]), type: 'heatgrid' }));
C('Punch card · circles sized by value', dv({ time: 'Hour', times: hg.map(r => r[1]), rows: hg.map(r => r[0]), rowsName: 'Weekday', measure: 'Orders', values: hg.map(r => r[2]), type: 'heatgrid', objects: { heatgrid: { shape: 'circle' } } }));
const hg8 = hg.filter(r => +r[1].slice(0, 2) >= 8 && +r[1].slice(0, 2) <= 21);
C('Heat grid · business hours · labels · 3D · brand', dv({ time: 'Hour', times: hg8.map(r => r[1]), rows: hg8.map(r => r[0]), rowsName: 'Weekday', measure: 'Orders', values: hg8.map(r => r[2]), type: 'heatgrid', objects: { chart: { look: '3d' }, labels: { show: true }, palette: { source: 'brand', brand: { solid: { color: '#0f766e' } } } } }));
// 6-8 stream
C('Stream · wiggle · labels', dv({ time: 'Month', times: m24, series: { name: 'Subcategory', groups: subs.map((s, k) => ({ name: s, values: m24.map((_, j) => sv(k, j)) })) }, measure: 'Sales', type: 'stream', objects: { labels: { show: true } } }));
C('Stream · silhouette', dv({ time: 'Month', times: m24, series: { name: 'Subcategory', groups: subs.map((s, k) => ({ name: s, values: m24.map((_, j) => sv(k, j)) })) }, measure: 'Sales', type: 'stream', objects: { stream: { offset: 'silhouette' } } }));
C('Stream · 100% stacked · straight · flat · legend bottom', dv({ time: 'Month', times: m24, series: { name: 'Subcategory', groups: subs.map((s, k) => ({ name: s, values: m24.map((_, j) => sv(k, j)) })) }, measure: 'Sales', type: 'stream', objects: { chart: { look: 'flat' }, stream: { offset: 'expand', smooth: false }, legend: { position: 'bottomCenter' } } }));
// 9-11 timeline slicer
C('Timeline · months', dv({ time: 'Order date', dates: true, times: y2, measure: 'Orders', values: y2.map(orders), type: 'timeline' }));
const saved = [{ $schema: 'x', target: { table: 'Orders', column: 'Order date' }, logicalOperator: 'And', filterType: 0, conditions: [{ operator: 'GreaterThanOrEqual', value: new Date(2024, 3, 1).toISOString() }, { operator: 'LessThan', value: new Date(2025, 0, 1).toISOString() }] }];
C('Timeline · quarters · saved filter (Q2–Q4 2024)', dv({ time: 'Order date', dates: true, times: y2, measure: 'Orders', values: y2.map(orders), type: 'timeline', objects: { timeline: { granularity: 'quarter' } } }), { jsonFilters: saved });
C('Timeline · days (scrolls)', dv({ time: 'Order date', dates: true, times: nd, measure: 'Orders', values: nd.map(orders), type: 'timeline', objects: { timeline: { granularity: 'day' } } }));
// 12-16 modes and edge cases
C('Calendar · dark', dv({ time: 'Order date', dates: true, times: y25, measure: 'Orders', values: y25.map(orders), type: 'calendar' }), { dark: true });
C('Heat grid · high contrast', dv({ time: 'Hour', times: hg.map(r => r[1]), rows: hg.map(r => r[0]), rowsName: 'Weekday', measure: 'Orders', values: hg.map(r => r[2]), type: 'heatgrid' }), { hc: true });
C('Landing page (no fields)', null);
C('Stream · cross-highlighted (E-bike)', dv({ time: 'Month', times: m24, series: { name: 'Subcategory', groups: subs.map((s, k) => ({ name: s, values: m24.map((_, j) => sv(k, j)), hl: m24.map((_, j) => (k === 2 ? sv(k, j) : null)) })) }, measure: 'Sales', type: 'stream' }));
C('Calendar without dates · hint', dv({ time: 'Region', times: ['North', 'South'], measure: 'Orders', values: [3, 4], type: 'calendar' }), { w: 360, h: 200 });
