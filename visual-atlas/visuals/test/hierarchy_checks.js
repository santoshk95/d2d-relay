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
    treemapCards: card(tm, 'Treemap') && !card(tm, 'Sunburst') && !card(tm, 'Org chart / tree'), orgCards: card(orgc, 'Org chart / tree') && !card(orgc, 'Legend')
  };
  out.ok = Object.values(out.checks).every(Boolean);
  return out;
})()
