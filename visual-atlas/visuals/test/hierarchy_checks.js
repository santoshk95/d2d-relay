// Zoom, expand, click, keyboard, highlight and Format pane checks for the Atlas Hierarchy test page (case order from hierarchy_cases.js)
(() => {
  const cases = [...document.querySelectorAll('.case')], out = {};
  const fire = (el, type, o) => el && el.dispatchEvent(new MouseEvent(type, Object.assign({ bubbles: true, cancelable: true, clientX: 120, clientY: 120 }, o || {})));
  const q = (c, s) => cases[c].querySelectorAll(s);
  LOG.length = 0;
  /* zoom: clicking a group in case 0 zooms in and shows a breadcrumb; the breadcrumb zooms out */
  const groups0 = q(0, '.grp').length;
  fire(q(0, '.grp')[0], 'click');
  out.zoomed = q(0, '.crumb').length === 1 && q(0, '.grp').length < groups0;
  fire(q(0, '.crumb text[style*="cursor"]')[0], 'click');
  out.zoomedOut = q(0, '.crumb').length === 0 && q(0, '.grp').length === groups0;
  /* circle packing with a legend: zoom two levels, the path sits under the legend, Back goes up one level at a time */
  const packG = q(5, '.grp').length;
  fire(q(5, '.grp')[0], 'click');
  fire(q(5, '.grp')[0], 'click');
  const lgB = Math.max(...[...q(5, '.lg')].map(e => e.getBoundingClientRect().bottom)), crT = Math.min(...[...q(5, '.crumb text')].map(e => e.getBoundingClientRect().top));
  out.zoomLegendDim = q(5, '.lg.dim').length;
  out.crumbBelowLegend = q(5, '.lg').length > 0 && crT >= lgB - 1;
  out.depth = q(5, '.crumb text[aria-label]').length;
  fire(q(5, '.crumb-back')[0], 'click');
  out.backOne = q(5, '.crumb text[aria-label]').length === out.depth - 1;
  for (let k = 0; k < 5 && q(5, '.crumb-back').length; k++) fire(q(5, '.crumb-back')[0], 'click');
  out.backToTop = q(5, '.grp').length === packG && !q(5, '.crumb-back').length;
  /* select mode: clicking a tile selects */
  const tiles = [...q(15, '.grp')];
  fire(tiles[tiles.length - 1], 'mouseenter');
  fire(tiles[tiles.length - 1], 'click');
  fire(tiles[tiles.length - 2], 'click', { ctrlKey: true });
  out.selectDims = q(15, '.grp.dim').length;
  fire(tiles[0], 'contextmenu');
  /* org chart: clicking a closed card opens it */
  const cards7 = q(7, '.grp').length;
  fire(q(7, '.grp')[1], 'click');
  out.expanded = q(7, '.grp').length > cards7;
  /* legend selects a branch; keyboard on a sunburst segment */
  fire(q(1, '.lg')[0], 'click');
  q(3, '.grp')[q(3, '.grp').length - 1].dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
  fire(cases[15].querySelector('svg.atl-svg'), 'click');
  out.dimAfterClear = q(15, '.grp.dim').length;
  out.highlightDims = q(13, '.grp.dim').length;
  /* sunburst labels (cases 3, 4, 11, 14 and the thin slices of 16): no label on another, each inside its own slice.
     A label is the rotated lines sharing one transform; its corners come from the lines' boxes in their own
     coordinates, taken to the page with the text's screen matrix. */
  const sunLabels = k => {
    const by = {};
    q(k, 'text[transform^="rotate"]').forEach(t => { (by[t.getAttribute('transform')] = by[t.getAttribute('transform')] || []).push(t); });
    return Object.values(by).map(ts => {
      const bs = ts.map(t => t.getBBox()), x0 = Math.min(...bs.map(b => b.x)), y0 = Math.min(...bs.map(b => b.y));
      const x1 = Math.max(...bs.map(b => b.x + b.width)), y1 = Math.max(...bs.map(b => b.y + b.height)), m = ts[0].getScreenCTM();
      const c = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]].map(([x, y]) => new DOMPoint(x, y).matrixTransform(m));
      return { s: ts.map(t => t.textContent).join(' '), c };
    });
  };
  const apart = (A, B) => [A, B].some(P => P.some((a, i) => {          /* separating axes, 1 px allowed */
    const b = P[(i + 1) % 4], nx = b.y - a.y, ny = a.x - b.x, len = Math.hypot(nx, ny) || 1, pr = Q => Q.map(p => (p.x * nx + p.y * ny) / len);
    const pa = pr(A), pb = pr(B);
    return Math.max(...pa) <= Math.min(...pb) + 1 || Math.max(...pb) <= Math.min(...pa) + 1;
  }));
  const centre = c => ({ x: (c[0].x + c[2].x) / 2, y: (c[0].y + c[2].y) / 2 });
  const inFill = (p, path) => path.isPointInFill(new DOMPoint(p.x, p.y).matrixTransform(path.getScreenCTM().inverse()));
  const shrink = c => { const m = centre(c); return c.map(p => { const dx = p.x - m.x, dy = p.y - m.y, d = Math.hypot(dx, dy) || 1; return { x: p.x - dx / d, y: p.y - dy / d }; }); };
  out.sunburst = {};
  [3, 4, 11, 14, 16].forEach(k => {
    const ls = sunLabels(k), slices = [...q(k, '.grp > path:not([transform])')], over = [], outside = [];
    ls.forEach((a, i) => ls.slice(i + 1).forEach(b => { if (!apart(a.c, b.c)) over.push(a.s + ' | ' + b.s); }));
    ls.forEach(l => { const home = slices.find(p => inFill(centre(l.c), p)); if (!home || !shrink(l.c).every(p => inFill(p, home))) outside.push(l.s); });
    out.sunburst[k] = { labels: ls.map(l => l.s), over, outside };
  });
  const thinShown = out.sunburst[16].labels;
  const bad = [];
  cases.forEach((c, k) => c.querySelectorAll('svg *').forEach(n => { for (const a of n.attributes) if (/NaN|Infinity|undefined/.test(a.value)) bad.push(k + ':' + n.tagName + '.' + a.name); }));
  out.bad = bad.slice(0, 10);
  out.log = LOG.filter(x => x[0] !== 'rendered');
  const has = (t, s) => out.log.some(x => x[0] === t && (!s || String(x[1]).includes(s)));
  const cardsOf = k => cases[k]._v.getFormattingModel().cards.map(c => c.displayName + ': ' + c.groups.map(g => g.slices.map(s => s.displayName).join(', ')).join(' / '));
  const tm = cardsOf(0), orgc = cardsOf(7);
  out.format = { tm, orgc };
  const card = (list, name) => list.some(x => x.startsWith(name + ':'));
  out.checks = {
    zoomIn: out.zoomed, zoomOut: out.zoomedOut, crumbBelowLegend: out.crumbBelowLegend, zoomLegend: out.zoomLegendDim === q(5, '.lg').length - 1, backButton: out.depth >= 2 && out.backOne && out.backToTop, tooltip: has('tooltip', 'Subcategory:'), select: has('select', 'Category='), multiSelect: out.log.some(x => x[0] === 'select' && x[2] === true),
    contextMenu: has('context'), expandCard: out.expanded, legendSelects: out.log.some(x => x[0] === 'select' && /Category=/.test(x[1]) && !/Subcategory/.test(x[1])),
    keyboard: out.log.filter(x => x[0] === 'select').length >= 3, backgroundClears: has('clear') && out.dimAfterClear === 0, highlights: out.highlightDims > 0,
    landing: !!cases[12].querySelector('.atl-landing'), noNaN: bad.length === 0,
    treemapCards: card(tm, 'Treemap') && !card(tm, 'Sunburst') && !card(tm, 'Org chart / tree'), orgCards: card(orgc, 'Org chart / tree') && !card(orgc, 'Legend'),
    sunburstLabelsApart: Object.values(out.sunburst).every(x => x.labels.length > 0 && x.over.length === 0),
    sunburstLabelsInside: Object.values(out.sunburst).every(x => x.outside.length === 0),
    thinSlicesKeepBigLabels: [/^Bikes \d+%$/, /^Comp\S*( 1\d%)?$/].every(re => thinShown.some(s => re.test(s))) && thinShown.filter(s => /^(Online|Retail) 3\d%$/.test(s)).length === 2
  };
  out.ok = Object.values(out.checks).every(Boolean);
  return out;
})()
