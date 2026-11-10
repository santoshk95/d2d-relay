// Click, filter, keyboard, highlight and Format pane checks for the Atlas Time test page (case order from time_cases.js)
(() => {
  const cases = [...document.querySelectorAll('.case')], out = {};
  const fire = (el, type, o) => el && el.dispatchEvent(new MouseEvent(type, Object.assign({ bubbles: true, cancelable: true, clientX: 120, clientY: 120 }, o || {})));
  const q = (c, s) => cases[c].querySelectorAll(s);
  LOG.length = 0;
  fire(q(0, '.mk')[40], 'mouseenter');
  fire(q(0, '.mk')[40], 'click');
  out.calDim = q(0, '.mk.dim').length + '/' + q(0, '.mk').length;
  fire(q(3, '.mk')[10], 'click');
  fire(q(3, '.mk')[11], 'click', { ctrlKey: true });
  fire(q(3, '.mk')[12], 'contextmenu');
  fire(q(6, '.lg')[2], 'click');
  fire(q(6, '.grp')[1], 'mouseenter');
  q(4, '.mk')[5].dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
  /* timeline: click a month, shift-click another, then clear */
  fire(q(9, '.mk')[3], 'click');
  out.after1 = [...q(9, 'text')][0].textContent;
  const vis = e => !!e && e.style.display !== 'none'; const mk9 = () => cases[9].querySelector('.atl-mark'); out.markFilter = vis(mk9()) && mk9().classList.contains('atl-mark-filter');
  fire(q(9, '.mk')[7], 'click', { shiftKey: true });
  out.after2 = [...q(9, 'text')][0].textContent;
  fire(q(9, '.lg')[0], 'click');
  out.after3 = [...q(9, 'text')][0].textContent;
  out.markFilterOff = !vis(mk9());
  out.saved = [...q(10, 'text')][0].textContent;
  const sc = cases[11].querySelector('.vbox'); out.scroll = [sc.scrollWidth, sc.clientWidth];
  fire(cases[3].querySelector('svg.atl-svg'), 'click');
  out.dimAfterClear = q(3, '.mk.dim').length;
  out.highlightDims = q(15, '.grp.dim').length;
  const bad = [];
  cases.forEach((c, k) => c.querySelectorAll('svg *').forEach(n => { for (const a of n.attributes) if (/NaN|Infinity|undefined/.test(a.value)) bad.push(k + ':' + n.tagName + '.' + a.name); }));
  out.bad = bad.slice(0, 10);
  out.log = LOG.filter(x => x[0] !== 'rendered');
  const has = (t, s) => out.log.some(x => x[0] === t && (!s || String(x[1]).includes(s)));
  const filters = out.log.filter(x => x[0] === 'filter');
  const cardsOf = k => cases[k]._v.getFormattingModel().cards.map(c => c.displayName + ': ' + c.groups.map(g => g.slices.map(s => s.displayName).join(', ')).join(' / '));
  const cal = cardsOf(0), tl = cardsOf(9);
  out.format = { cal, tl };
  const card = (list, name) => list.some(x => x.startsWith(name + ':'));
  out.checks = {
    filterMarker: out.markFilter && out.markFilterOff,
    dayTooltip: has('tooltip', 'Date:'), daySelect: has('select', 'Order date='), multiSelect: out.log.some(x => x[0] === 'select' && x[2] === true), contextMenu: has('context'),
    legendSelects: has('select', 'series=E-bike'), streamTooltip: has('tooltip', 'Peak:'), keyboard: has('select', 'Weekday='),
    filterApplied: filters.length >= 2 && /GreaterThanOrEqual/.test(filters[0][1]) && /"table":"Orders"/.test(filters[0][1]) && filters[0][2] === 0,
    rangeExtends: out.after1 !== out.after2 && /–/.test(out.after2), filterCleared: filters.some(x => x[1] === 'none' && x[2] === 1) && /All periods/.test(out.after3),
    savedFilterShown: /Q2 2024 – Q4 2024/.test(out.saved), scrolls: out.scroll[0] > out.scroll[1],
    backgroundClears: has('clear') && out.dimAfterClear === 0, highlights: out.highlightDims > 0,
    landing: !!cases[14].querySelector('.atl-landing'), hint: !!cases[16].querySelector('.note'), noNaN: bad.length === 0,
    calendarCards: card(cal, 'Calendar') && card(cal, 'Color scale') && !card(cal, 'Timeline slicer'), timelineCards: card(tl, 'Timeline slicer') && !card(tl, 'Color scale')
  };
  out.ok = Object.values(out.checks).every(Boolean);
  return out;
})()
