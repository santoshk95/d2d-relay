// Format pane checks for Atlas Columns: which cards and slices are built for different data and settings
(() => {
  const cases = [...document.querySelectorAll('.case')];
  const sum = (k) => { const fm = cases[k]._v.getFormattingModel(); return fm.cards.map(c => (c.analyticsPane ? '[analytics] ' : '') + c.displayName + ': ' + c.groups.map(g => g.slices.map(s => s.displayName + (s.control && s.control.properties && s.control.properties.descriptor && s.control.properties.descriptor.instanceKind ? '(fx)' : '')).join(', ')).join(' / ')); };
  const single = sum(3), vary = sum(10), stacked = sum(1);
  const checks = {
    fxDefaultColor: single.some(x => /Colors: Default color\(fx\)/.test(x)),
    refLineInAnalytics: single.some(x => /^\[analytics\] Reference line/.test(x)),
    fxPerCategory: vary.some(x => /Colors: Bikes\(fx\)/.test(x)),
    totalsOnlyStacked: stacked.some(x => /^Total labels/.test(x)) && !single.some(x => /^Total labels/.test(x)),
    shadowHiddenWhenFlat: stacked.some(x => /^Chart: /.test(x) && !/Shadow strength/.test(x))
  };
  return { ok: Object.values(checks).every(Boolean), checks, single, vary, stacked };
})()
