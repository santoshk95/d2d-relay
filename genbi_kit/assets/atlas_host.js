// Mock Power BI host for the HTML prototype (after visual-atlas/visuals/test/host.js): runs the packaged
// Visual Atlas code in the browser, so the prototype draws what Power BI will. Adds tooltips, local dates and
// data-view hydration (values.grouped(), Date objects) on top of the test host.
window.powerbi = window.powerbi || { visuals: { plugins: {} } };
(function () {
  let mouse = [0, 0], tip = null;
  document.addEventListener('mousemove', e => { mouse = [e.clientX, e.clientY]; if (tip) place(); });
  function place() { tip.style.left = Math.min(mouse[0] + 14, innerWidth - tip.offsetWidth - 8) + 'px'; tip.style.top = Math.min(mouse[1] + 12, innerHeight - tip.offsetHeight - 8) + 'px'; }
  function showTip(items) {
    if (!tip) { tip = document.createElement('div'); tip.className = 'gba-tip'; document.body.appendChild(tip); }
    tip.replaceChildren(...(items || []).map(d => { const row = document.createElement('div');
      const k = document.createElement('span'); k.textContent = d.displayName || d.header || '';
      const v = document.createElement('b'); v.textContent = d.value == null ? '' : d.value; row.append(k, v); return row; }));
    place();
  }
  function hideTip() { if (tip) { tip.remove(); tip = null; } }

  function makeHost(opts) {
    opts = opts || {};
    const used = new Map(), pal = opts.palette || ['#118dff', '#12239e', '#e66c37', '#6b007b', '#e044a7', '#744ec2', '#d9b300', '#d64550'];
    const fg = opts.dark ? '#f3f2f1' : '#252423', bg = opts.dark ? '#1f1f1f' : '#ffffff';
    const sid = key => ({ key, equals: o => o && o.key === key, getKey: () => key, hasIdentity: () => true, includes: o => o && o.key === key,
      getSelector: () => (key.split('&').every(p => p.startsWith('m=')) ? { metadata: key } : { data: [{ key }] }), getSelectorsByColumn: () => ({}) });
    return {
      colorPalette: { isHighContrast: false, foreground: { value: fg }, background: { value: bg }, foregroundNeutralSecondary: { value: '#605e5c' },
        getColor(k) { if (!used.has(k)) used.set(k, pal[used.size % pal.length]); return { value: used.get(k) }; }, reset() { used.clear(); return this; } },
      createSelectionIdBuilder() { const parts = []; const b = {
        withCategory(c, i) { parts.push(c.source.displayName + '=' + c.values[i]); return b; },
        withSeries(cols, g) { parts.push('series=' + (g && (g.name != null ? g.name : g.source && g.source.groupName))); return b; },
        withMeasure(m) { parts.push('m=' + m); return b; }, withMatrixNode() { return b; }, withTable() { return b; },
        createSelectionId() { return sid(parts.join('&')); } }; return b; },
      createSelectionManager() { let picked = []; return {
        select: (id, multi) => { const list = Array.isArray(id) ? id : [id];
          if (multi) list.forEach(x => { const k = picked.findIndex(p => p.key === x.key); if (k >= 0) picked.splice(k, 1); else picked.push(x); });
          else picked = list.slice(); return Promise.resolve(picked.slice()); },
        clear: () => { picked = []; return Promise.resolve(); }, showContextMenu: () => Promise.resolve(),
        hasSelection: () => picked.length > 0, getSelectionIds: () => picked.slice(), registerOnSelectCallback() {}, toggleExpandCollapse: () => Promise.resolve() }; },
      tooltipService: { enabled: () => true, show: o => showTip(o.dataItems), move: o => showTip(o.dataItems), hide: hideTip },
      eventService: { renderingStarted() {}, renderingFinished() {}, renderingFailed(o, e) { console.warn('render failed', e); } },
      hostCapabilities: { allowInteractions: true },
      displayWarningIcon() {}, createLocalizationManager() { return { getDisplayName: k => k }; },
      drill() {}, applyJsonFilter() {}, persistProperties() {}, locale: 'en-US', refreshHostData() {}, launchUrl() {}, fetchMoreData() { return false; }
    };
  }

  const day = /^(\d{4})-(\d{2})-(\d{2})$/;
  const asDate = v => { if (v == null) return null; const m = day.exec(v); return m ? new Date(+m[1], +m[2] - 1, +m[3]) : new Date(v); };
  function hydrate(spec, objects) {
    const fix = col => ({ source: col.source, values: col.source.type && col.source.type.dateTime ? col.values.map(asDate) : col.values });
    const categories = (spec.categories || []).map(fix);
    let values;
    if (spec.groups) {
      const groups = spec.groups.map(g => ({ name: g.name, values: g.values, identity: { key: String(g.name) } }));
      values = [].concat(...groups.map(g => g.values));
      values.source = spec.groupSource;
      values.grouped = () => groups;
    } else {
      values = (spec.values || []).slice();
      values.grouped = () => [{ values: values.slice() }];
    }
    return { metadata: { columns: [], objects: objects || {} }, categorical: { categories, values } };
  }

  function render(box, item, theme) {
    const plugin = (window.powerbi.visuals.plugins || {})[item.guid];
    if (!plugin) throw new Error('visual code not loaded (' + item.guid + ')');
    const host = makeHost({ palette: theme && theme.palette, dark: theme && theme.dark });
    const v = plugin.create({ element: box, host });
    v.update({ dataViews: [hydrate(item.dv, item.objects)], viewport: { width: box.clientWidth, height: box.clientHeight }, type: 2 });
    return v;
  }
  window.GenBIAtlas = { render, hydrate, makeHost };
})();
