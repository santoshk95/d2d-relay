// Hover, click, drill, zoom, keyboard, highlight and Format pane checks for the Atlas Lines test page (case order from lines_cases.js)
(() => {
  const cases = [...document.querySelectorAll('.case')], out = {};
  const fire = (el, type, o) => el && el.dispatchEvent(new MouseEvent(type, Object.assign({ bubbles: true, cancelable: true, clientX: 120, clientY: 120 }, o || {})));
  const q = (c, s) => cases[c].querySelectorAll(s);
  LOG.length = 0;
  fire(q(1, '.band')[4], 'mouseenter');
  fire(q(1, '.band')[4], 'click');
  fire(q(1, '.band')[6], 'click', { ctrlKey: true });
  const vis = e => !!e && e.style.display !== 'none'; const mk1 = cases[1].querySelector('.atl-mark'); out.markOn = vis(mk1);
  if (mk1) mk1.click(); out.markClears = !vis(mk1) && q(1, '.dim').length === 0;
  fire(q(1, '.band')[2], 'contextmenu');
  fire(q(2, '.mk')[3], 'click');
  fire(q(11, '.lg')[0], 'click');
  fire(q(13, '.grp')[0], 'click');
  q(9, '.mk')[2].dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
  /* select a point on the drill case: a Clear selection button appears; clicking it clears */
  fire(q(9, '.mk')[1], 'click');
  const clearBtn = [...q(9, '.atl-drill-b')].find(b => b.title === 'Clear selection');
  out.clearShown = !!clearBtn; if (clearBtn) clearBtn.click();
  out.dimAfterClearButton = q(9, '.mk.dim').length;
  q(9, '.atl-drill-b').forEach(b => b.click());
  out.drillButtons = [...q(9, '.atl-drill-b')].map(b => b.title);
  /* click and drag across case 2 selects months 3 to 8 */
  { const svg2 = cases[2].querySelector('svg.atl-svg'), b2 = q(2, '.band'), r3 = b2[3].getBoundingClientRect(), r8 = b2[8].getBoundingClientRect(), y = r3.top + 20;
    b2[3].dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, button: 0, clientX: r3.left + r3.width / 2, clientY: y }));
    window.dispatchEvent(new PointerEvent('pointermove', { clientX: r8.left + r8.width / 2, clientY: y }));
    window.dispatchEvent(new PointerEvent('pointerup', { clientX: r8.left + r8.width / 2, clientY: y }));
    const sel = LOG.filter(x => x[0] === 'select').pop(); out.dragSelect = sel ? sel[1].split(',').length : 0; out.dragDims = q(2, '.mk.dim').length; void svg2; }
  /* zoom: move the start handle to the right with the keyboard */
  const labelsBefore = q(10, 'text.ax').length;
  const hA = q(10, '.zoom rect[role=slider]')[0];
  for (let k = 0; k < 12; k++) (q(10, '.zoom rect[role=slider]')[0] || hA).dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
  out.zoomBands = q(10, '.band').length;
  out.zoomLabels = [labelsBefore, q(10, 'text.ax').length];
  /* wheel over the plot zooms in; double-click shows everything again */
  q(10, '.band')[10].dispatchEvent(new WheelEvent('wheel', { deltaY: -100, clientX: 200, bubbles: true, cancelable: true }));
  out.wheelBands = q(10, '.band').length;
  fire(q(10, '.band')[3], 'dblclick');
  out.resetBands = q(10, '.band').length;
  /* a point inside a filled area hits a category band (a click picks that month, not the whole series) */
  cases[12].scrollIntoView();
  const ab = q(12, '.grp path')[0].getBoundingClientRect(), hit = document.elementFromPoint(ab.left + ab.width / 2, ab.bottom - 6);
  out.areaHit = hit ? hit.getAttribute('class') : null;
  out.forecast = [...q(5, 'text')].some(t => /Forecast/.test(t.textContent));
  out.anomalies = q(6, '.anomaly').length;
  fire(cases[1].querySelector('svg.atl-svg'), 'click');
  out.highlightDims = q(20, '.mk.dim').length;
  const bad = [];
  cases.forEach((c, k) => c.querySelectorAll('svg *').forEach(n => { for (const a of n.attributes) if (/NaN|Infinity|undefined/.test(a.value)) bad.push(k + ':' + n.tagName + '.' + a.name); }));
  out.bad = bad.slice(0, 10);
  out.log = LOG.filter(x => x[0] !== 'rendered');
  const has = (t, s) => out.log.some(x => x[0] === t && (!s || String(x[1]).includes(s)));
  const cardsOf = k => cases[k]._v.getFormattingModel().cards.map(c => (c.analyticsPane ? '[analytics] ' : '') + c.displayName + ': ' + c.groups.map(g => g.slices.map(s => s.displayName).join(', ')).join(' / '));
  const ln = cardsOf(0), cb = cardsOf(15);
  out.format = { ln, cb };
  /* case 21: zoomed to the six highlighted months (a window of 7), the selected stretch drawn on top */
  out.zoomToSel = [q(21, '.band').length, q(21, '.sel-run').length, [...q(21, '.atl-reset')].some(b => b.style.display !== 'none')];
  { const lab = [...q(3, 'text.ax')].find(t => t.textContent === 'Jul'); if (lab) lab.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
    out.axisLabelSelect = !!lab && lab.style.pointerEvents === 'all' && LOG.some(x => x[0] === 'select' && /^Month=Jul$/.test(x[1])); }
  out.bandCursor = q(0, '.band')[0].style.cursor;
  out.checks = {
    axisLabelSelects: out.axisLabelSelect, bandArrow: out.bandCursor === 'default',
    zoomToSelection: out.zoomToSel[0] === 7 && out.zoomToSel[1] === 1 && out.zoomToSel[2],
    selectionMarker: out.markOn && out.markClears,
    dragSelect: out.dragSelect >= 5 && out.dragDims === 6,
    bandTooltip: has('tooltip', 'Sales 2025:') && has('tooltip', 'Sales 2024:'), bandSelect: has('select', 'Month=May'), multiSelect: out.log.some(x => x[0] === 'select' && x[2] === true),
    contextMenu: has('context'), markerSelect: has('select', 'Month=Apr&m=m.Sales'), legendSelects: has('select', 'series=Online'), areaSelects: has('select', 'series='),
    keyboard: has('select', 'Year=2023'), drill: out.log.filter(x => x[0] === 'drill').length === 4, clearButton: out.clearShown && out.dimAfterClearButton === 0, legendDrawn: q(13, '.lg').length === 3 && q(15, '.lg').length === 3, zoomed: out.zoomBands === 24, wheelZoom: out.wheelBands < 24, dblclickResets: out.resetBands === 36, areaClickHitsCategory: out.areaHit === 'band',
    forecast: out.forecast, anomalies: out.anomalies === 2, backgroundClears: has('clear'), highlights: out.highlightDims > 0,
    landing: !!cases[19].querySelector('.atl-landing'), noNaN: bad.length === 0,
    analyticsPane: ln.some(x => x.startsWith('[analytics] Analytics')), comboSettings: cb.some(x => /Lines on a secondary axis/.test(x)) && !ln.some(x => /Lines on a secondary axis/.test(x))
  };
  out.ok = Object.values(out.checks).every(Boolean);
  return out;
})()
