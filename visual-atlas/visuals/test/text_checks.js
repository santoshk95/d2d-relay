// Click, keyboard, highlight and Format pane checks for the Atlas Text test page (case order from text_cases.js)
(() => {
  const cases = [...document.querySelectorAll('.case')], out = {};
  const fire = (el, type, o) => el && el.dispatchEvent(new MouseEvent(type, Object.assign({ bubbles: true, cancelable: true, clientX: 120, clientY: 120 }, o || {})));
  const q = (c, s) => cases[c].querySelectorAll(s);
  LOG.length = 0;
  fire(q(0, '.mk')[0], 'mouseenter');
  fire(q(0, '.mk')[0], 'click');
  fire(q(0, '.mk')[3], 'click', { ctrlKey: true });
  out.dim = q(0, '.mk.dim').length + '/' + q(0, '.mk').length;
  fire(q(0, '.mk')[1], 'contextmenu');
  fire(q(1, '.lg')[1], 'click');
  q(4, '.mk')[0].dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
  fire(cases[0].querySelector('svg.atl-svg'), 'click');
  out.dimAfterClear = q(0, '.mk.dim').length;
  out.highlightDims = q(9, '.mk.dim').length;
  out.placed = cases.map(c => c.querySelectorAll('.mk').length);
  out.reviewWords = [...q(2, 'text')].map(t => t.textContent).slice(0, 12).join(', ');
  out.ranked = [...q(5, 'text')].map(t => t.textContent).join(', ');
  /* no two words in a cloud overlap */
  const overlaps = k => { const r = [...q(k, '.mk text')].map(t => t.getBoundingClientRect()); let n = 0; for (let i = 0; i < r.length; i++) for (let j = i + 1; j < r.length; j++) { const a = r[i], b = r[j]; if (a.left < b.right - 2 && b.left < a.right - 2 && a.top < b.bottom - 3 && b.top < a.bottom - 3) n++; } return n; };
  out.overlap = [0, 3, 10].map(overlaps);
  const bad = [];
  cases.forEach((c, k) => c.querySelectorAll('svg *').forEach(n => { for (const a of n.attributes) if (/NaN|Infinity|undefined/.test(a.value)) bad.push(k + ':' + n.tagName + '.' + a.name); }));
  out.bad = bad.slice(0, 10);
  out.log = LOG.filter(x => x[0] !== 'rendered');
  const has = (t, s) => out.log.some(x => x[0] === t && (!s || String(x[1]).includes(s)));
  const cardsOf = k => cases[k]._v.getFormattingModel().cards.map(c => c.displayName + ': ' + c.groups.map(g => g.slices.map(s => s.displayName).join(', ')).join(' / '));
  const cl = cardsOf(0), br = cardsOf(4);
  out.format = { cl, br };
  const card = (list, name) => list.some(x => x.startsWith(name + ':'));
  out.checks = {
    tooltip: has('tooltip', 'Word: fast delivery'), select: has('select', 'Phrase=fast delivery'), multiSelect: out.log.some(x => x[0] === 'select' && x[2] === true), contextMenu: has('context'),
    legendSelects: has('select', 'Topic=Price'), keyboard: out.log.filter(x => x[0] === 'select').length >= 3, backgroundClears: has('clear') && out.dimAfterClear === 0, highlights: out.highlightDims > 0,
    allPlaced: out.placed[0] >= 28 && out.placed[1] >= 28, noOverlap: out.overlap.every(n => n === 0), stopWords: !/\b(the|and|was)\b/.test(out.reviewWords) && /delivery|great/.test(out.reviewWords),
    extraStopWords: !/\bgreat\b/.test(out.ranked), landing: !!cases[8].querySelector('.atl-landing'), noNaN: bad.length === 0,
    cloudCards: card(cl, 'Word cloud') && !card(cl, 'Data labels'), barsCards: card(br, 'Data labels') && !card(br, 'Word cloud')
  };
  out.ok = Object.values(out.checks).every(Boolean);
  return out;
})()
