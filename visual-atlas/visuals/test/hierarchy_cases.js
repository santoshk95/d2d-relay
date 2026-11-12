// Test cases for Atlas Hierarchy in the mock host.
const GUID = Object.keys(powerbi.visuals.plugins)[0];
const D = window.DATA;
/* levels data view: level columns + Size (+ Color value) */
function lv(levels, o) {
  o = o || {};
  const names = ['Category', 'Subcategory', 'Product'];
  const rows = D.hp;
  const cats = levels.map(k => ({ source: { displayName: names[k], queryName: 't.' + names[k], roles: { levels: true }, type: { text: true } }, values: rows.map(r => r[k]) }));
  const values = [{ source: { displayName: 'Sales', queryName: 'm.Sales', roles: { values: true }, isMeasure: true, format: '\\$#,0' }, values: rows.map(r => r[3]) }];
  if (o.hl) values[0].highlights = rows.map(r => (o.hl(r) ? r[3] : null));
  if (o.color) values.push({ source: { displayName: 'Margin %', queryName: 'm.Margin', roles: { colorValue: true }, isMeasure: true, format: '0.0' }, values: rows.map(r => +(r[4] / r[3] * 100).toFixed(1)) });
  values.grouped = () => [{ values: values.slice() }];
  return { metadata: { columns: [], objects: o.objects || {} }, categorical: { categories: cats, values } };
}
/* org data view: ID, Parent ID, Label, Size */
const people = [['E1', '', 'Avery Chen (CEO)', 410]];
const vps = ['Sales', 'Product', 'Operations', 'Finance', 'People'];
let n = 2;
vps.forEach((vp, k) => {
  const vid = 'E' + n++; people.push([vid, 'E1', vp + ' VP', 260]);
  for (let j = 0; j < 2 + (k % 3); j++) {
    const mid = 'E' + n++; people.push([mid, vid, vp + ' manager ' + (j + 1), 150]);
    for (let i = 0; i < 2 + ((k + j) % 3); i++) people.push(['E' + n++, mid, vp + ' analyst ' + (j + 1) + '.' + (i + 1), 90 + ((k * 7 + i * 3) % 30)]);
  }
});
function org(o) {
  o = o || {};
  const col = (name, role, i) => ({ source: { displayName: name, queryName: 't.' + name, roles: { [role]: true }, type: { text: true } }, values: people.map(p => p[i]) });
  const cats = [col('Employee', 'nodeId', 0), col('Manager', 'parentId', 1), col('Name', 'label', 2)];
  const values = [{ source: { displayName: 'Salary (K)', queryName: 'm.Salary', roles: { values: true }, isMeasure: true, format: '#,0' }, values: people.map(p => p[3]) }];
  values.grouped = () => [{ values: values.slice() }];
  return { metadata: { columns: [], objects: o.objects || {} }, categorical: { categories: cats, values } };
}
const C = (title, d, o) => { try { return renderCase(GUID, title, d, o || {}); } catch (e) { LOG.push(['THROW', title, String(e && e.stack || e)]); } };
/* objects for a chart type plus extra card settings */
const T = (type, extra) => { const o = Object.assign({}, extra || {}); o.chart = Object.assign({ chartType: type }, o.chart || {}); return o; };
const clean = o => o;

// 0-2 treemaps
C('Treemap · category › subcategory · headers · name and value', lv([0, 1], { objects: clean(T('treemap')) }));
C('Treemap · three levels · flat · balanced tiling · percent', lv([0, 1, 2], { objects: clean(T('treemap', { chart: { look: 'flat', content: 'namePercent' }, treemap: { tile: 'binary' } })) }));
C('Treemap · color by margin (gradient)', lv([1], { color: true, objects: clean(T('treemap', { hcolor: { colorBy: 'value' } })) }));
// 3-6 sunburst and packing
C('Sunburst · two levels · soft', lv([0, 1], { objects: clean(T('sunburst')) }));
C('Sunburst · three levels · 3D · large hole', lv([0, 1, 2], { objects: clean(T('sunburst', { chart: { look: '3d' }, sunburst: { hole: 40 } })) }));
C('Circle packing · three levels', lv([0, 1, 2], { objects: clean(T('pack')) }));
C('Circle packing · color by level · legend', lv([0, 1, 2], { objects: clean(T('pack', { hcolor: { colorBy: 'level' } })) }));
// 7-9 org chart and tree
C('Org chart · top down · two levels open', org({ objects: clean(T('tree')) }), { w: 560, h: 340 });
C('Org chart · three levels · straight links · flat', org({ objects: clean(T('tree', { chart: { look: 'flat' }, tree: { expanded: 3, links: 'straight', cardWidth: 110, cardHeight: 38 } })) }));
C('Hierarchy tree · left to right · value bars', lv([0, 1], { objects: clean(T('tree', { tree: { orientation: 'leftRight', expanded: 3, links: 'curve', cardWidth: 110, cardHeight: 26 } })) }));
// 10-15 modes and edge cases
C('Treemap · high contrast', lv([0, 1], { objects: clean(T('treemap')) }), { hc: true });
C('Sunburst · dark', lv([0, 1], { objects: clean(T('sunburst')) }), { dark: true });
C('Landing page (no fields)', null);
C('Treemap · cross-highlighted (bikes)', lv([0, 1], { hl: r => r[0] === 'Bikes', objects: clean(T('treemap')) }));
C('Sunburst · small tile', lv([0, 1, 2], { objects: clean(T('sunburst')) }), { w: 300, h: 200 });
C('Treemap · clicking selects', lv([0, 1], { objects: clean(T('treemap', { chart: { click: 'select' } })) }));
// 16: thin slices as in an AI-made sales report (Clothing 4.9%, Accessories 3.7%; 2.5% and 2.4% outside): every label
// stays inside its own slice, none on another (D2D Relay item 37)
const thin = [['Bikes', 'Online', 2430], ['Bikes', 'Retail', 2310], ['Components', 'Online', 474], ['Components', 'Retail', 449],
  ['Clothing', 'Online', 156], ['Clothing', 'Retail', 150], ['Accessories', 'Online', 118], ['Accessories', 'Retail', 112]];
function tv(o) {
  const cats = ['Category', 'Channel'].map((name, k) => ({ source: { displayName: name, queryName: 't.' + name, roles: { levels: true }, type: { text: true } }, values: thin.map(r => r[k]) }));
  const values = [{ source: { displayName: 'Revenue', queryName: 'm.Revenue', roles: { values: true }, isMeasure: true, format: '\\$#,0' }, values: thin.map(r => r[2] * 1000) }];
  values.grouped = () => [{ values: values.slice() }];
  return { metadata: { columns: [], objects: o.objects || {} }, categorical: { categories: cats, values } };
}
C('Sunburst · thin slices · name and percent', tv({ objects: clean(T('sunburst', { chart: { content: 'namePercent' } })) }), { w: 600, h: 270 });
