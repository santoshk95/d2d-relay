// Click, zoom, play, keyboard, highlight and Format pane checks for the Atlas Scatter test page (case order from scatter_cases.js)
(() => {
  const cases = [...document.querySelectorAll('.case')], out = {};
  const fire = (el, type, o) => el && el.dispatchEvent(new MouseEvent(type, Object.assign({ bubbles: true, cancelable: true, clientX: 120, clientY: 120 }, o || {})));
  const q = (c, s) => cases[c].querySelectorAll(s);
  LOG.length = 0;
  fire(q(1, '.mk')[3], 'mouseenter');
  fire(q(1, '.mk')[3], 'click');
  fire(q(1, '.mk')[5], 'click', { ctrlKey: true });
  out.dim = q(1, '.mk.dim').length + '/' + q(1, '.mk').length;
  fire(q(1, '.mk')[2], 'contextmenu');
  fire(q(1, '.lg')[1], 'click');
  q(10, '.mk')[1].dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
  fire(q(10, '.mk')[4], 'mouseenter');
  /* play axis: click the third frame dot */
  const before = [...q(5, 'text')].map(t => t.textContent).join('|');
  const dots = [...q(5, 'circle')].filter(cc => cc.getAttribute('style') === 'cursor:pointer');
  fire(dots[2], 'click');
  out.frameShown = [...q(5, 'text')].some(t => t.textContent === '2023');
  out.playChanged = before !== [...q(5, 'text')].map(t => t.textContent).join('|');
  /* zoom: drag a rectangle with pointer events on case 0 */
  const svg0 = cases[0].querySelector('svg.atl-svg'), box = svg0.getBoundingClientRect(), hit = [...q(0, 'rect')].find(r => r.getAttribute('fill') === 'transparent' && +r.getAttribute('width') > 100);
  const pe = (type, x, y) => new PointerEvent(type, { bubbles: true, clientX: box.left + x, clientY: box.top + y });
  hit.dispatchEvent(pe('pointerdown', 120, 60)); window.dispatchEvent(pe('pointermove', 300, 220)); window.dispatchEvent(pe('pointerup', 300, 220));
  out.zoomReset = !!cases[0].querySelector('[aria-label="Reset zoom"]');
  out.ticksAfterZoom = [...q(0, 'text.ax')].map(t => t.textContent).slice(0, 4).join(', ');
  const rb = cases[0].querySelector('.atl-reset'); out.resetShown = !!rb && rb.style.display !== 'none' && /Reset zoom/.test(rb.textContent);
  if (rb) rb.click(); out.resetHides = !!rb && rb.style.display === 'none';
  fire(cases[1].querySelector('svg.atl-svg'), 'click');
  out.highlightDims = q(9, '.mk.dim').length;
  out.gantt = [...q(10, 'text')].map(t => t.textContent).join(' | ');
  out.milestones = [...q(10, '.mk path')].length;
  const bad = [];
  cases.forEach((c, k) => c.querySelectorAll('svg *').forEach(n => { for (const a of n.attributes) if (/NaN|Infinity|undefined/.test(a.value)) bad.push(k + ':' + n.tagName + '.' + a.name); }));
  out.bad = bad.slice(0, 10);
  out.log = LOG.filter(x => x[0] !== 'rendered');
  const has = (t, s) => out.log.some(x => x[0] === t && (!s || String(x[1]).includes(s)));
  const cardsOf = k => cases[k]._v.getFormattingModel().cards.map(c => (c.analyticsPane ? '[analytics] ' : '') + c.displayName + ': ' + c.groups.map(g => g.slices.map(s => s.displayName).join(', ')).join(' / '));
  const scc = cardsOf(1), gc = cardsOf(10), pc = cardsOf(5);
  out.format = { scc, gc, pc };
  const card = (list, name) => list.some(x => x.replace('[analytics] ', '').startsWith(name + ':'));
  out.checks = {
    tooltip: has('tooltip', 'Customers:'), select: has('select', 'Store='), multiSelect: out.log.some(x => x[0] === 'select' && x[2] === true), contextMenu: has('context'),
    legendSelects: has('select', 'Format=Mall'), keyboard: has('select', 'Task='), ganttTooltip: has('tooltip', 'Complete:'), playFrame: out.frameShown && out.playChanged,
    zoom: out.zoomReset, resetButton: out.resetShown && out.resetHides, backgroundClears: has('clear'), highlights: out.highlightDims > 0, ganttHeader: /Owner/.test(out.gantt) && /Today/.test(out.gantt), milestones: out.milestones === 2,
    landing: !!cases[15].querySelector('.atl-landing'), noNaN: bad.length === 0,
    guidesInAnalytics: scc.some(x => x.startsWith('[analytics] Guides and axes')), ganttCards: card(gc, 'Gantt') && !card(gc, 'Markers'), playCard: card(pc, 'Play axis') && !card(scc, 'Play axis')
  };
  out.ok = Object.values(out.checks).every(Boolean);
  return out;
})()
