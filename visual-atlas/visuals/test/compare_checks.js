// Click, keyboard, highlight and Format pane checks for the Atlas Compare test page (case order from compare_cases.js)
(() => {
  const cases = [...document.querySelectorAll('.case')], out = {};
  const fire = (el, type, o) => el && el.dispatchEvent(new MouseEvent(type, Object.assign({ bubbles: true, cancelable: true, clientX: 120, clientY: 120 }, o || {})));
  const q = (c, s) => cases[c].querySelectorAll(s);
  LOG.length = 0;
  fire(q(0, '.mk')[0], 'mouseenter');
  fire(q(0, '.mk')[0], 'click');
  fire(q(0, '.mk')[2], 'click', { ctrlKey: true });
  out.lolliDim = q(0, '.grp.dim').length + '/' + q(0, '.grp').length;
  fire(q(0, '.mk')[1], 'contextmenu');
  fire(q(2, '.lg')[1], 'click');
  q(3, '.mk')[0].dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
  fire(q(11, '.grp')[0], 'mouseenter');
  fire(q(17, '.mk')[1], 'mouseenter');
  fire(cases[0].querySelector('svg.atl-svg'), 'click');
  out.dimAfterClear = q(0, '.grp.dim').length;
  out.highlightDims = q(17, '.mk.dim').length;
  const bad = [];
  cases.forEach((c, k) => c.querySelectorAll('svg *').forEach(n => { for (const a of n.attributes) if (/NaN|Infinity|undefined/.test(a.value)) bad.push(k + ':' + n.tagName + '.' + a.name); }));
  out.bad = bad.slice(0, 10);
  out.log = LOG.filter(x => x[0] !== 'rendered');
  const has = (t, s) => out.log.some(x => x[0] === t && (!s || String(x[1]).includes(s)));
  const cardsOf = k => cases[k]._v.getFormattingModel().cards.map(c => (c.analyticsPane ? '[analytics] ' : '') + c.displayName + ': ' + c.groups.map(g => g.slices.map(s => s.displayName).join(', ')).join(' / '));
  const lol = cardsOf(0), rad = cardsOf(11), tor = cardsOf(9);
  out.format = { lol, rad, tor };
  const card = (list, name) => list.some(x => x.startsWith(name + ':'));
  out.checks = {
    tooltip: has('tooltip', 'Product:'), select: has('select', 'Product='), multiSelect: out.log.some(x => x[0] === 'select' && x[2] === true),
    contextMenu: has('context'), legendSelects: has('select', 'series=Retail'), keyboard: has('select', 'Month='),
    seriesTooltip: has('tooltip', 'Brand:'), tooltipMeasure: has('tooltip', 'Orders:'),
    backgroundClears: has('clear') && out.dimAfterClear === 0, highlights: out.highlightDims > 0,
    hints: !!cases[16].querySelector('.note'), landing: !!cases[15].querySelector('.atl-landing'), noNaN: bad.length === 0,
    styleCard: card(lol, 'Style'), radarCard: card(rad, 'Radar') && !card(rad, 'Tornado'), tornadoCard: card(tor, 'Tornado') && !card(tor, 'Radar'),
    noLegendForOneSeries: !card(lol, 'Legend')
  };
  out.ok = Object.values(out.checks).every(Boolean);
  return out;
})()
