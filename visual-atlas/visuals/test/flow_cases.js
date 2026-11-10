const GUID = Object.keys(powerbi.visuals.plugins)[0];
function flowDV(rows, objects, o) {
  o = o || {};
  const col = (n, role, extra) => Object.assign({ displayName: n, queryName: 't.' + n, roles: { [role]: true }, type: { text: true } }, extra || {});
  const src = col(o.sn || 'Source', 'source'), tgt = col(o.tn || 'Target', 'target'), w = col(o.wn || 'Weight', 'weight', { isMeasure: true, format: o.fmt || '#,0', type: { numeric: true } });
  const vals = { source: w, values: rows.map(r => r[2]) };
  if (o.hl) vals.highlights = rows.map((r, i) => o.hl(r, i) ? r[2] : null);
  return { metadata: { columns: [src, tgt, w], objects: objects || {} }, categorical: { categories: [{ source: src, values: rows.map(r => r[0]) }, { source: tgt, values: rows.map(r => r[1]) }], values: [vals] } };
}
const D = window.DATA;
const C = (title, rows, obj, o) => { try { renderCase(GUID, title, flowDV(rows, obj, o), o); } catch (e) { LOG.push(['THROW', title, String(e && e.stack || e)]); } };
C('Sankey · soft · report theme', D.traffic, {}, { sn: 'Channel', tn: 'Page', wn: 'Sessions' });
C('Sankey · 3D · gradient links', D.traffic, { chart: { look: '3d' }, links: { colorBy: 'gradient' } }, {});
C('Sankey · income statement · flat · brand color', D.pnl, { chart: { look: 'flat' }, palette: { source: 'brand', brand: { solid: { color: '#e11d48' } } }, links: { colorBy: 'target' } }, { fmt: '\\$#,0' });
C('Chord · soft · custom colors', D.switching, { chart: { chartType: 'chord' }, palette: { source: 'custom', custom: '#0f766e, #ea580c, #7c3aed, #ca8a04, #2a78d6' } }, { sn: 'From', tn: 'To', wn: 'Customers' });
C('Chord · 3D · trade', D.trade, { chart: { chartType: 'chord', look: '3d' } }, { fmt: '\\$#,0' });
C('Network · soft · communities', D.net, { chart: { chartType: 'network' }, network: { colorBy: 'community' } }, { sn: 'Product A', tn: 'Product B', wn: 'Orders' });
C('Network · 3D · size by connections · dark theme', D.net, { chart: { chartType: 'network', look: '3d' }, nodes: { sizeBy: 'degree' } }, { dark: true });
C('Sankey · highlighted from another visual', D.traffic, {}, { hl: r => r[0] === 'Paid search' || r[0] === 'Product page' });
renderCase(GUID, 'No fields yet (landing page)', null, {});
C('Sankey · high contrast', D.traffic, {}, { hc: true });
