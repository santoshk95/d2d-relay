// Click, keyboard, highlight and Format pane checks for the Atlas Finance test page (case order from finance_cases.js)
(() => {
  const cases = [...document.querySelectorAll('.case')], out = {};
  const fire = (el, type, o) => el && el.dispatchEvent(new MouseEvent(type, Object.assign({ bubbles: true, cancelable: true, clientX: 120, clientY: 120 }, o || {})));
  const q = (c, s) => cases[c].querySelectorAll(s);
  LOG.length = 0;
  fire(q(0, '.mk')[10], 'mouseenter');
  fire(q(0, '.mk')[10], 'click');
  out.candleDim = q(0, '.mk.dim').length + '/' + q(0, '.mk').length;
  fire(q(3, '.mk')[2], 'mouseenter');
  fire(q(3, '.mk')[2], 'click');
  fire(q(3, '.mk')[3], 'click', { ctrlKey: true });
  fire(q(3, '.mk')[1], 'contextmenu');
  fire(q(7, '.lg')[2], 'click');
  q(9, '.mk')[1].dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
  fire(q(9, '.mk')[1], 'mouseenter');
  fire(cases[3].querySelector('svg.atl-svg'), 'click');
  out.dimAfterClear = q(3, '.mk.dim').length;
  out.highlightDims = q(13, '.mk.dim').length;
  out.pnl = [...q(5, 'text')].map(t => t.textContent).join(' | ');
  out.breakdown = [...q(4, 'text')].map(t => t.textContent).join(' | ');
  out.funnel = [...q(9, 'text')].map(t => t.textContent).join(' | ');
  const sc = cases[0].querySelector('.vbox'); out.scroll = [sc.scrollWidth, sc.clientWidth];
  const bad = [];
  cases.forEach((c, k) => c.querySelectorAll('svg *').forEach(n => { for (const a of n.attributes) if (/NaN|Infinity|undefined/.test(a.value)) bad.push(k + ':' + n.tagName + '.' + a.name); }));
  out.bad = bad.slice(0, 10);
  out.log = LOG.filter(x => x[0] !== 'rendered');
  const has = (t, s) => out.log.some(x => x[0] === t && (!s || String(x[1]).includes(s)));
  const cardsOf = k => cases[k]._v.getFormattingModel().cards.map(c => c.displayName + ': ' + c.groups.map(g => g.slices.map(s => s.displayName).join(', ')).join(' / '));
  const cdl = cardsOf(0), wf = cardsOf(3), fn = cardsOf(9);
  out.format = { cdl, wf, fn };
  const card = (list, name) => list.some(x => x.startsWith(name + ':'));
  // labels fixed to millions on a bridge of small steps: no step reads $0M, each keeps its own unit
  out.fixedUnits = [...cases[16].querySelectorAll('text.lbl')].map(t => t.textContent);
  out.checks = {
    noFalseZero: out.fixedUnits.length >= 7 && out.fixedUnits.every(s => /[1-9]/.test(s)) && ['+$240K', '-$59K', '-$4K'].every(s => out.fixedUnits.includes(s)),
    candleTooltip: has('tooltip', 'Open:'), candleSelect: has('select', 'Date='), waterfallTooltip: has('tooltip', 'Running total:'), select: has('select', 'Driver='),
    multiSelect: out.log.some(x => x[0] === 'select' && x[2] === true), contextMenu: has('context'), legendSelects: has('select', 'series=E-bike'), keyboard: has('select', 'Stage='),
    funnelTooltip: has('tooltip', '% of previous:'), backgroundClears: has('clear') && out.dimAfterClear === 0, highlights: out.highlightDims > 0,
    subtotals: /Gross[\s|]+profit/.test(out.pnl) && /Net profit/.test(out.pnl), breakdownEnds: /2024/.test(out.breakdown) && /2025/.test(out.breakdown), conversion: /Conversion rate: 7\.4%/.test(out.funnel),
    candlesScroll: out.scroll[0] > out.scroll[1], landing: !!cases[12].querySelector('.atl-landing'), hint: !!cases[15].querySelector('.note'), noNaN: bad.length === 0,
    candleCards: card(cdl, 'Candlestick') && !card(cdl, 'Waterfall'), waterfallCards: card(wf, 'Waterfall') && !card(wf, 'Funnel'), funnelCards: card(fn, 'Funnel') && !card(fn, 'Value axis')
  };
  out.ok = Object.values(out.checks).every(Boolean);
  return out;
})()
