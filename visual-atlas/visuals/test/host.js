// Minimal Power BI host for rendering packaged visuals outside Power BI.
window.LOG = [];
window.powerbi = { visuals: { plugins: {} } };
const THEME = ['#118dff','#12239e','#e66c37','#6b007b','#e044a7','#744ec2','#d9b300','#d64550','#197278','#1aab40','#15c6f4','#4092ff'];
function makeHost(opts) {
  opts = opts || {};
  const used = new Map();
  const pal = opts.theme || THEME;
  const fg = opts.dark ? '#f3f2f1' : '#252423', bg = opts.dark ? '#1f1f1f' : '#ffffff';
  const sid = (key) => ({ key, equals: o => o && o.key === key, getKey: () => key, getSelector: () => (key.split('&').every(p => p.startsWith('m=')) ? { metadata: key } : { data: [{ key }] }), hasIdentity: () => true, includes: o => o && o.key === key, getSelectorsByColumn: () => ({}) });
  return {
    colorPalette: { isHighContrast: !!opts.hc, foreground: { value: fg }, background: { value: bg }, foregroundNeutralSecondary: { value: '#605e5c' },
      getColor(k) { if (!used.has(k)) used.set(k, pal[used.size % pal.length]); return { value: used.get(k) }; }, reset() { used.clear(); return this; } },
    createSelectionIdBuilder() { const parts = []; const b = {
      withCategory(c, i) { parts.push(c.source.displayName + '=' + c.values[i]); return b; },
      withSeries(cols, g) { parts.push('series=' + (g && (g.name != null ? g.name : g.source && g.source.groupName))); return b; },
      withMeasure(m) { parts.push('m=' + m); return b; }, withMatrixNode() { return b; }, withTable() { return b; },
      createSelectionId() { return sid(parts.join('&')); } }; return b; },
    createSelectionManager() { let picked = []; return { select: (id, m) => { LOG.push(['select', Array.isArray(id) ? id.map(x => x.key).join(',') : id.key, !!m]); const list = Array.isArray(id) ? id : [id]; if (m) list.forEach(x => { const k = picked.findIndex(p => p.key === x.key); if (k >= 0) picked.splice(k, 1); else picked.push(x); }); else picked = list.slice(); return Promise.resolve(picked.slice()); },
      clear: () => { LOG.push(['clear']); picked = []; return Promise.resolve(); }, showContextMenu: (id, p) => { LOG.push(['context', id && id.key]); return Promise.resolve(); },
      hasSelection: () => picked.length > 0, getSelectionIds: () => picked.slice(), registerOnSelectCallback() {}, toggleExpandCollapse() { return Promise.resolve(); } }; },
    tooltipService: { enabled: () => true, show: o => LOG.push(['tooltip', o.dataItems.map(d => d.displayName + ': ' + d.value).join(' | ')]), move() {}, hide() {} },
    eventService: { renderingStarted() {}, renderingFinished() { LOG.push(['rendered']); }, renderingFailed(o, e) { LOG.push(['FAILED', String(e)]); } },
    hostCapabilities: { allowInteractions: opts.allowInteractions !== false },
    displayWarningIcon(t, d) { LOG.push(['warning', t]); },
    createLocalizationManager() { return { getDisplayName: k => k }; },
    drill(a) { LOG.push(['drill', a.roleName, a.drillType]); },
    applyJsonFilter(f, obj, prop, action) { LOG.push(['filter', f ? JSON.stringify(f) : 'none', action]); },
    persistProperties() {}, locale: 'en-US', refreshHostData() {}, launchUrl() {}, fetchMoreData() { return false; }
  };
}
// render a visual into a new box: guid, dataView, {w,h,host options}
window.renderCase = function (guid, title, dv, o) {
  o = o || {};
  const wrap = document.createElement('div'); wrap.className = 'case';
  const h = document.createElement('div'); h.className = 'cap'; h.textContent = title; wrap.appendChild(h);
  const box = document.createElement('div'); box.className = 'vbox' + (o.dark ? ' dark' : ''); box.style.width = (o.w || 560) + 'px'; box.style.height = (o.h || 340) + 'px';
  wrap.appendChild(box); document.getElementById('cases').appendChild(wrap);
  const host = makeHost(o);
  const v = window.powerbi.visuals.plugins[guid].create({ element: box, host });
  v.update({ dataViews: dv ? [dv] : [], viewport: { width: o.w || 560, height: o.h || 340 }, type: 2, jsonFilters: o.jsonFilters });
  wrap._v = v; wrap._host = host;
  return wrap;
};
