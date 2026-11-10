// Click, drill, keyboard, highlight and Format pane checks for the Atlas Parts test page (case order from parts_cases.js)
(() => {
  const cases = [...document.querySelectorAll('.case')], out = {};
  const fire = (el, type, o) => el && el.dispatchEvent(new MouseEvent(type, Object.assign({ bubbles: true, cancelable: true, clientX: 120, clientY: 120 }, o || {})));
  const q = (c, s) => cases[c].querySelectorAll(s);
  LOG.length = 0;
  fire(q(0, '.mk')[0], 'mouseenter');
  fire(q(0, '.mk')[0], 'click');
  fire(q(0, '.mk')[2], 'click', { ctrlKey: true });
  out.dim = q(0, '.mk.dim').length + '/' + q(0, '.mk').length;
  /* a plain click replaces this visual's selection by toggling (old ids off, the new one on) instead of select(ids, false), which would drop other visuals' selections */
  fire(q(0, '.mk')[1], 'click');
  const rep = LOG.filter(x => x[0] === 'select').pop(); out.replace = rep ? [rep[1].split(',').length, rep[2]] : null;
  fire(q(0, '.mk')[1], 'contextmenu');
  fire(q(6, '.lg')[1], 'click');
  q(11, '.mk')[1].dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
  q(4, '.atl-drill-b').forEach(b => b.click());
  fire(cases[0].querySelector('svg.atl-svg'), 'click');
  out.dimAfterClear = q(0, '.mk.dim').length;
  out.highlightDims = q(15, '.mk.dim').length;
  out.other = [...q(3, 'text')].map(t => t.textContent).join(' | ');
  out.center = [...q(9, 'text')].map(t => t.textContent).join(' | ');
  /* outside labels never overlap */
  const r = [...q(1, 'text.lbl')].map(t => t.getBoundingClientRect()); let ov = 0;
  for (let i = 0; i < r.length; i++) for (let j = i + 1; j < r.length; j++) { const a = r[i], b = r[j]; if (a.left < b.right && b.left < a.right && a.top < b.bottom - 2 && b.top < a.bottom - 2) ov++; }
  out.labelOverlaps = ov;
  const bad = [];
  cases.forEach((c, k) => c.querySelectorAll('svg *').forEach(n => { for (const a of n.attributes) if (/NaN|Infinity|undefined/.test(a.value)) bad.push(k + ':' + n.tagName + '.' + a.name); }));
  out.bad = bad.slice(0, 10);
  out.log = LOG.filter(x => x[0] !== 'rendered');
  const has = (t, s) => out.log.some(x => x[0] === t && (!s || String(x[1]).includes(s)));
  const cardsOf = k => cases[k]._v.getFormattingModel().cards.map(c => c.displayName + ': ' + c.groups.map(g => g.slices.map(s => s.displayName).join(', ')).join(' / '));
  const pie = cardsOf(0), dn = cardsOf(6);
  out.format = { pie, dn };
  /* partial highlight: the donut's total and slices follow the highlighted values */
  const nP = cases.length, txt = k => [...q(k, 'text')].map(t => t.textContent).join('|');
  out.partial = [txt(nP - 2).slice(0, 80), txt(nP - 1).slice(0, 80)];
  out.checks = {
    keepOtherVisuals: !!out.replace && out.replace[0] === 3 && out.replace[1] === true,
    partialHighlight: out.partial[0] !== out.partial[1] && q(nP - 1, '.mk.dim').length === 0,
    tooltip: has('tooltip', 'Share:'), select: has('select', 'Category=Bikes'), multiSelect: out.log.some(x => x[0] === 'select' && x[2] === true), contextMenu: has('context'),
    legendSelects: has('select', 'Channel=Retail'), keyboard: has('select', 'series='), drill: out.log.filter(x => x[0] === 'drill').length === 4, drillNames: [...q(4, 'text')].some(t => / › /.test(t.textContent)),
    backgroundClears: has('clear') && out.dimAfterClear === 0, highlights: out.highlightDims > 0, other: /Other/.test(out.other), progress: /68%/.test(out.center),
    noLabelOverlap: out.labelOverlaps === 0, landing: !!cases[14].querySelector('.atl-landing'), noNaN: bad.length === 0,
    holeOnlyDonut: pie.some(x => /^Chart:/.test(x) && !/Inner radius/.test(x)) && dn.some(x => /Inner radius/.test(x))
  };
  out.ok = Object.values(out.checks).every(Boolean);
  return out;
})()
