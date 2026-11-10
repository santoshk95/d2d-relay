// Click, keyboard, highlight and Format pane checks for the Atlas Gauges test page (case order from gauges_cases.js)
(() => {
  const cases = [...document.querySelectorAll('.case')], out = {};
  const fire = (el, type, o) => el && el.dispatchEvent(new MouseEvent(type, Object.assign({ bubbles: true, cancelable: true, clientX: 120, clientY: 120 }, o || {})));
  const q = (c, s) => cases[c].querySelectorAll(s);
  LOG.length = 0;
  fire(q(5, '.mk')[1], 'mouseenter');
  fire(q(5, '.mk')[1], 'click');
  fire(q(5, '.mk')[2], 'click', { ctrlKey: true });
  out.stripDim = q(5, '.mk.dim').length + '/' + q(5, '.mk').length;
  fire(q(5, '.mk')[0], 'contextmenu');
  fire(q(1, '.mk')[2], 'mouseenter');
  fire(q(1, '.mk')[2], 'click');
  q(11, '.mk')[0].dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
  fire(cases[5].querySelector('svg.atl-svg'), 'click');
  out.dimAfterClear = q(5, '.mk.dim').length;
  out.highlightDims = q(18, '.mk.dim').length;
  out.card = [...q(0, 'text')].map(t => t.textContent).join(' | ');
  out.kpi = [...q(2, 'text')].map(t => t.textContent).join(' | ');
  out.liquid = [...q(9, 'text')].map(t => t.textContent).join(' | ');
  const tick = cases[14].querySelector('.atl-tick'); out.tickerAnim = tick ? getComputedStyle(tick).animationName : '';
  const bad = [];
  cases.forEach((c, k) => c.querySelectorAll('svg *').forEach(n => { for (const a of n.attributes) if (/NaN|Infinity|undefined/.test(a.value)) bad.push(k + ':' + n.tagName + '.' + a.name); }));
  out.bad = bad.slice(0, 10);
  out.log = LOG.filter(x => x[0] !== 'rendered');
  const has = (t, s) => out.log.some(x => x[0] === t && (!s || String(x[1]).includes(s)));
  const cardsOf = k => cases[k]._v.getFormattingModel().cards.map(c => c.displayName + ': ' + c.groups.map(g => g.slices.map(s => s.displayName).join(', ')).join(' / '));
  const cd = cardsOf(0), dl = cardsOf(6), kp = cardsOf(2);
  out.format = { cd, dl, kp };
  const card = (list, name) => list.some(x => x.startsWith(name + ':'));
  /* partial highlight: the card shows the highlighted value ($3.72M), not the total */
  out.partialCard = [...q(cases.length - 1, 'text')].map(t => t.textContent).join('|');
  out.cardCursor = [q(1, '.mk')[0] && q(1, '.mk')[0].style.cursor, q(cases.length - 2, '.mk')[0] && q(cases.length - 2, '.mk')[0].style.cursor];
  out.checks = {
    cursorOnlyWhenSelectable: out.cardCursor[0] === 'default' && out.cardCursor[1] === 'pointer',
    partialHighlight: /3.72M|3,720,000|3.7M/.test(out.partialCard) && !/9.3M/.test(out.partialCard),
    tooltip: has('tooltip', 'vs target:'), select: has('select', 'Region='), multiSelect: out.log.some(x => x[0] === 'select' && x[2] === true), contextMenu: has('context'),
    measureSelect: has('select', 'm=m.Orders'), keyboard: has('select', 'Measure='), backgroundClears: has('clear') && out.dimAfterClear === 0, highlights: out.highlightDims > 0,
    cardTarget: /Target \$10/.test(out.card) && /-7\.0%/.test(out.card), kpiGoal: /Goal:/.test(out.kpi), liquidPct: /62%/.test(out.liquid), tickerMoves: out.tickerAnim === 'atl-tick',
    landing: !!cases[17].querySelector('.atl-landing'), noNaN: bad.length === 0,
    dialCards: card(dl, 'Scale and bands') && card(dl, 'Target and status'), kpiTrendCard: card(kp, 'Trend'), cardNoScale: !card(cd, 'Scale and bands')
  };
  out.ok = Object.values(out.checks).every(Boolean);
  return out;
})()
