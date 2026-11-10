// Click, keyboard, drill and scroll checks for the Atlas Columns test page (case order from cols_cases.js)
(() => {
  const cases = [...document.querySelectorAll('.case')], out = {};
  const fire = (el, type, o) => el && el.dispatchEvent(new MouseEvent(type, Object.assign({ bubbles: true, cancelable: true, clientX: 120, clientY: 120 }, o || {})));
  LOG.length = 0;
  const q = (c, s) => cases[c].querySelectorAll(s);
  fire(q(0, '.bar')[0], 'mouseenter');
  fire(q(0, '.bar')[0], 'click');
  fire(q(0, '.bar')[2], 'click', { ctrlKey: true });
  out.dimAfterSelect = q(0, '.bar.dim').length + '/' + q(0, '.bar').length;
  const vis = e => !!e && e.style.display !== 'none'; out.markOn = vis(cases[0].querySelector('.atl-mark'));
  fire(q(0, '.bar')[1], 'contextmenu');
  fire(q(1, '.lg')[1], 'click');
  out.legendDim = q(1, '.bar.dim').length + '/' + q(1, '.bar').length + ' legendItemsDim=' + q(1, '.lg.dim').length;
  q(4, '.atl-drill-b').forEach(b => b.click());
  out.drillButtons = [...q(4, '.atl-drill-b')].map(b => b.title + (b.disabled ? ' (off)' : ''));
  q(3, '.bar')[0].dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
  fire(cases[0].querySelector('.atl-scroll svg'), 'click');
  out.dimAfterClear = q(0, '.bar.dim').length;
  out.markOff = !vis(cases[0].querySelector('.atl-mark'));
  fire(q(6, '.bar')[5], 'mouseenter');
  const sc = cases[8].querySelector('.atl-scroll'); out.scroll = [sc.scrollWidth, sc.clientWidth];
  out.labels8 = [...q(7, '.lbl')].map(t => t.textContent).join(' ');
  out.axis8 = [...q(7, '.ax')].map(t => t.textContent).join(' ');
  out.log = LOG.filter(x => x[0] !== 'rendered');
  const has = (t, s) => out.log.some(x => x[0] === t && (!s || String(x[1]).includes(s)));
  { const lab = [...cases[0].querySelectorAll('.cax text')].find(t => t.style.pointerEvents === 'all'); if (lab) lab.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
    out.catLabel = !!lab && LOG.some(x => x[0] === 'select' && /^Year=/.test(String(x[1]))); }
  out.checks = {
    categoryLabelSelects: out.catLabel,
    selectionMarker: out.markOn && out.markOff,
    tooltip: has('tooltip', 'Year: 2023'), select: has('select', 'Year=2023'), multiSelect: out.log.some(x => x[0] === 'select' && x[2] === true),
    contextMenu: has('context'), legendSelectsSeries: has('select', 'series=Retail'), drillButtons: out.log.filter(x => x[0] === 'drill').length === 4 && out.drillButtons.some(t => /Back to the top/.test(t)),
    keyboard: has('select', 'Product=Road 100'), backgroundClears: has('clear') && out.dimAfterClear === 0, scrolls: out.scroll[0] > out.scroll[1],
    highlightTooltip: has('tooltip', 'Highlighted')
  };
  out.ok = Object.values(out.checks).every(Boolean);
  return out;
})()
