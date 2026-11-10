// Click, keyboard, highlight and Format pane checks for the Atlas Proportion test page (case order from proportion_cases.js)
(() => {
  const cases = [...document.querySelectorAll('.case')], out = {};
  const fire = (el, type, o) => el && el.dispatchEvent(new MouseEvent(type, Object.assign({ bubbles: true, cancelable: true, clientX: 120, clientY: 120 }, o || {})));
  const q = (c, s) => cases[c].querySelectorAll(s);
  LOG.length = 0;
  fire(q(0, '.mk')[0], 'mouseenter');
  fire(q(0, '.mk')[0], 'click');
  fire(q(0, '.mk')[4], 'click', { ctrlKey: true });
  out.mekkoDim = q(0, '.mk.dim').length + '/' + q(0, '.mk').length;
  fire(q(0, '.mk')[1], 'contextmenu');
  fire(q(0, '.lg')[1], 'click');
  fire(q(12, '.grp')[0], 'mouseenter');
  fire(q(12, '.grp')[0], 'click');
  q(7, '.mk')[0].dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
  fire(q(3, '.mk')[1], 'mouseenter');
  fire(cases[0].querySelector('svg.atl-svg'), 'click');
  out.dimAfterClear = q(0, '.mk.dim').length;
  out.highlightDims = q(17, '.mk.dim').length;
  out.wafflePct = [...q(2, 'text')].map(x => x.textContent).join(' | ');
  out.picto = [...q(5, 'text')].map(x => x.textContent).join(' | ');
  out.vennLabels = [...q(12, 'text')].map(x => x.textContent).join(' | ');
  const bad = [];
  cases.forEach((c, k) => c.querySelectorAll('svg *').forEach(n => { for (const a of n.attributes) if (/NaN|Infinity|undefined/.test(a.value)) bad.push(k + ':' + n.tagName + '.' + a.name); }));
  out.bad = bad.slice(0, 10);
  out.log = LOG.filter(x => x[0] !== 'rendered');
  const has = (t, s) => out.log.some(x => x[0] === t && (!s || String(x[1]).includes(s)));
  const cardsOf = k => cases[k]._v.getFormattingModel().cards.map(c => c.displayName + ': ' + c.groups.map(g => g.slices.map(s => s.displayName).join(', ')).join(' / '));
  const mek = cardsOf(0), waf = cardsOf(2);
  out.format = { mek, waf };
  const card = (list, name) => list.some(x => x.startsWith(name + ':'));
  /* rose: clicking a month name selects that whole month */
  const mLab = [...q(10, 'text')].find(t => t.textContent === 'Mar' && /pointer-events:all/.test(t.getAttribute('style') || ''));
  if (mLab) mLab.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
  out.monthSelect = !!mLab && LOG.some(x => x[0] === 'select' && /Month=Mar/.test(x[1]));
  out.checks = {
    monthLabelSelects: out.monthSelect,
    tooltip: has('tooltip', 'Region:'), select: has('select', 'Region='), multiSelect: out.log.some(x => x[0] === 'select' && x[2] === true),
    contextMenu: has('context'), legendSelects: has('select', 'series=Retail'), vennSetSelects: has('select', 'Shopped=Online'), keyboard: has('select', 'Attribute='),
    waffleTooltip: has('tooltip', 'Category:'), backgroundClears: has('clear') && out.dimAfterClear === 0, highlights: out.highlightDims > 0,
    wafflePercent: /68%/.test(out.wafflePct), pictoRatio: /7 in 10/.test(out.picto), vennHint: !!cases[13].querySelector('.note'), landing: !!cases[16].querySelector('.atl-landing'),
    noNaN: bad.length === 0, mekkoCards: card(mek, 'Mekko') && !card(mek, 'Waffle'), waffleCards: card(waf, 'Waffle') && !card(waf, 'Mekko')
  };
  out.ok = Object.values(out.checks).every(Boolean);
  return out;
})()
