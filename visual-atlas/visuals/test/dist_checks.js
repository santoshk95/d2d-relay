// Click, keyboard, highlight and Format pane checks for the Atlas Distribution test page (case order from dist_cases.js)
(() => {
  const cases = [...document.querySelectorAll('.case')], out = {};
  const fire = (el, type, o) => el && el.dispatchEvent(new MouseEvent(type, Object.assign({ bubbles: true, cancelable: true, clientX: 120, clientY: 120 }, o || {})));
  const q = (c, s) => cases[c].querySelectorAll(s);
  LOG.length = 0;
  fire(q(0, '.bar')[3], 'mouseenter');
  fire(q(0, '.bar')[3], 'click');
  out.histDim = q(0, '.bar.dim').length + '/' + q(0, '.bar').length;
  fire(q(4, '.grp')[0], 'mouseenter');
  fire(q(4, '.grp')[0], 'click');
  fire(q(4, '.grp')[2], 'click', { ctrlKey: true });
  out.boxDim = q(4, '.grp.dim').length + '/' + q(4, '.grp').length;
  fire(q(4, '.grp')[1], 'contextmenu');
  fire(q(1, '.lg')[1], 'click');
  q(5, '.pt')[0].dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
  fire(q(12, '.pl')[0], 'mouseenter');
  fire(q(21, '.pt')[0], 'mouseenter');
  fire(q(8, '.grp')[0], 'mouseenter');
  fire(cases[4].querySelector('svg.atl-svg'), 'click');
  out.boxDimAfterClear = q(4, '.grp.dim').length;
  /* highlights from another visual */
  const pl = [...q(13, '.pl')].map(p => +p.getAttribute('stroke-opacity'));
  out.parallelHighlight = pl.filter(v => v < 0.1).length + ' dim / ' + pl.length;
  out.histGhosts = q(15, '.ghost').length;
  /* no NaN or Infinity anywhere in the drawings */
  const bad = [];
  cases.forEach((c, k) => c.querySelectorAll('svg *').forEach(n => { for (const a of n.attributes) if (/NaN|Infinity/.test(a.value)) bad.push(k + ':' + n.tagName + '.' + a.name); }));
  out.bad = bad.slice(0, 10);
  out.log = LOG.filter(x => x[0] !== 'rendered');
  const has = (t, s) => out.log.some(x => x[0] === t && (!s || String(x[1]).includes(s)));
  /* Format pane */
  const cardsOf = k => cases[k]._v.getFormattingModel().cards.map(c => (c.analyticsPane ? '[analytics] ' : '') + c.displayName + ': ' + c.groups.map(g => g.slices.map(s => s.displayName).join(', ')).join(' / '));
  const hist = cardsOf(0), boxc = cardsOf(4), par = cardsOf(12), vio = cardsOf(10);
  out.format = { hist, boxc, par, vio };
  const card = (list, name) => list.some(x => x.replace('[analytics] ', '').startsWith(name + ':'));
  out.checks = {
    binTooltip: has('tooltip', 'Bin:'), binSelect: has('select', 'ID=SO'), histDims: +out.histDim.split('/')[0] > 0,
    boxTooltip: has('tooltip', 'Median:'), groupSelect: has('select', 'Carrier=Swift'), multiSelect: out.log.some(x => x[0] === 'select' && x[2] === true),
    contextMenu: has('context'), legendSelects: has('select', 'Channel=Retail'), keyboard: has('select', 'Shipment=SH'),
    lineTooltip: has('tooltip', 'Margin %'), pointTooltip: has('tooltip', 'Weight kg'), violinTooltip: has('tooltip', 'Observations'),
    backgroundClears: has('clear') && out.boxDimAfterClear === 0,
    highlights: /^[1-9]\d* dim/.test(out.parallelHighlight) && out.histGhosts > 0,
    landing: !!cases[17].querySelector('.atl-landing'), oneMeasureHint: !!cases[18].querySelector('.note'),
    noNaN: bad.length === 0,
    zeroWithoutUnit: ![...document.querySelectorAll('.case text')].some(t => /^-?\$?0(\.0+)?[KMB]$/.test(t.textContent.trim())),
    histCards: card(hist, 'Histogram') && !card(hist, 'Box and whisker') && !card(hist, 'Violin'),
    boxCards: card(boxc, 'Box and whisker') && !card(boxc, 'Histogram') && !card(boxc, 'Legend'),
    analytics: hist.some(x => x.startsWith('[analytics] Mean and median')),
    parallelCards: card(par, 'Parallel coordinates') && !card(par, 'Data labels'),
    violinCards: card(vio, 'Violin') && card(vio, 'Data points'),
    colorsPerGroup: boxc.some(x => /^Colors: Swift, Northline/.test(x))
  };
  out.ok = Object.values(out.checks).every(Boolean);
  return out;
})()
