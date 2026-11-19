// Checks every retail test page runs (scripts/test.sh, retail_* pages), case by case. They look for the defect classes
// D2D Relay's reports have shown: text on text (a KPI name on its value, labels on each other), text cut off at the
// visual's edge, NaN / undefined / Infinity, a value that is not zero shown as zero ("$0M") or units doubled ("$1.2MM"),
// typography that is not plain keyboard characters, and text too faint on what is behind it (light and dark).
// A case can allow one check by putting "[allow overlap]" (or clip, contrast) in its title.
(() => {
  const out = { cases: [], fails: [] };
  const TYPO = /[—–…“”‘’·•›‹→←↔]/;
  const BAD = [/NaN/, /undefined/, /Infinity/, /\bnull\b/, /\[object/];
  const parse = s => {
    if (!s) return null;
    s = String(s).trim();
    let m = s.match(/^#([0-9a-f]{6})$/i);
    if (m) return [parseInt(m[1].slice(0, 2), 16), parseInt(m[1].slice(2, 4), 16), parseInt(m[1].slice(4, 6), 16), 1];
    m = s.match(/^rgba?\(([^)]+)\)$/i);
    if (m) { const p = m[1].split(',').map(x => parseFloat(x)); return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1]; }
    return null;
  };
  const lin = c => { c /= 255; return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4); };
  const lum = c => 0.2126 * lin(c[0]) + 0.7152 * lin(c[1]) + 0.0722 * lin(c[2]);
  const ratio = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
  const over = (a, b, k) => [0, 1, 2].map(i => a[i] * k + b[i] * (1 - k));
  /* the color painted under a point: the topmost filled shape whose fill holds the point (found geometrically, so
     marks that take no pointer events count too; gradients: their middle stop), else the box's background */
  const shapesOf = box => [...box.querySelectorAll('svg rect, svg path, svg circle, svg ellipse, svg polygon')].filter(e => !e.closest('defs, clipPath, mask, pattern')).map(e => ({ e, r: e.getBoundingClientRect() })).filter(s => s.r.width > 0 && s.r.height > 0);
  const paintAt = (x, y, box, shapes) => {
    const bg = parse(getComputedStyle(box).backgroundColor) || [255, 255, 255, 1];
    for (let i = shapes.length - 1; i >= 0; i--) {
      const { e, r } = shapes[i];
      if (x < r.left || x > r.right || y < r.top || y > r.bottom) continue;
      const cs = getComputedStyle(e);
      if (cs.visibility === 'hidden' || cs.display === 'none') continue;
      let f = cs.fill, op = parseFloat(cs.fillOpacity) * parseFloat(cs.opacity);
      for (let p = e.parentElement; p && p !== box; p = p.parentElement) op *= parseFloat(getComputedStyle(p).opacity);
      if (!f || f === 'none' || op < 0.35) continue;
      const m = e.getScreenCTM(); if (!m) continue;
      const pt = e.ownerSVGElement.createSVGPoint(); pt.x = x; pt.y = y;
      if (!e.isPointInFill(pt.matrixTransform(m.inverse()))) continue;
      const u = f.match(/url\("?#([^")]+)"?\)/);
      if (u) { const g = box.querySelector('[id="' + u[1] + '"]') || document.getElementById(u[1]); const stops = g ? [...g.querySelectorAll('stop')] : []; if (!stops.length) continue; f = getComputedStyle(stops[Math.floor(stops.length / 2)]).stopColor; }
      const c = parse(f); if (!c || c[3] < 0.35) continue;
      return over(c, bg, Math.min(1, op * c[3]));
    }
    return bg;
  };
  document.querySelectorAll('.case').forEach((cs, k) => {
    const title = cs.querySelector('.cap').textContent, box = cs.querySelector('.vbox'), allow = n => title.includes('[allow ' + n + ']');
    const problems = [];
    /* text scrolled out of a scrolling area is not on screen: it is left out of the overlap and contrast checks */
    const shown = t => {
      const r = t.getBoundingClientRect(), x = r.left + r.width / 2, y = r.top + r.height / 2;
      for (let p = t.parentElement; p && p !== box.parentElement; p = p.parentElement) {
        if (p instanceof HTMLElement && getComputedStyle(p).overflow !== 'visible') { const q = p.getBoundingClientRect(); if (x < q.left || x > q.right || y < q.top || y > q.bottom) return false; }
      }
      return true;
    };
    const all = [...box.querySelectorAll('svg text')].filter(t => {
      if (!t.textContent.trim() || t.closest('.atl-tick')) return false;
      const st = getComputedStyle(t); if (st.display === 'none' || st.visibility === 'hidden' || parseFloat(st.opacity) === 0) return false;
      const r = t.getBoundingClientRect(); return r.width > 0 && r.height > 0;
    });
    const texts = all.filter(shown);
    const html = [...box.querySelectorAll('.atl-landing, .atl-corner')].map(e => e.textContent).join(' ');
    const words = all.map(t => t.textContent).concat([html]);
    words.forEach(s => { BAD.forEach(re => { if (re.test(s)) problems.push('bad text: ' + s); }); });
    words.forEach(s => { if (TYPO.test(s)) problems.push('typography: ' + s); });
    all.forEach(t => {
      const s = t.textContent;
      if (/(^|[^\d.,])[-+]?\$?0(\.0+)?\s?[KMB]n?\b/.test(s) && !/\$?0\.\d*[1-9]/.test(s)) problems.push('false zero: ' + s);
      if (/\d\s?([KMB])\1\b|\$\$|%%|\d[KMB][KMB]\b/.test(s)) problems.push('doubled unit: ' + s);
      if (/^[-+(]?\$?[\d.,]*\.\.\.$|^[-+]\.\.\.$/.test(s.trim())) problems.push('bad text, a number cut short: ' + s);
    });
    box.querySelectorAll('svg *').forEach(n => { for (const a of n.attributes) if (/NaN|Infinity|undefined/.test(a.value)) problems.push('bad attribute: ' + n.tagName + '.' + a.name + '=' + a.value.slice(0, 40)); });
    /* text on text: two labels whose boxes overlap by more than a sliver (rotated labels are left out) */
    const boxes = texts.filter(t => !/rotate/.test(t.getAttribute('transform') || '')).map(t => ({ t, r: t.getBoundingClientRect() }));
    if (!allow('overlap')) for (let i = 0; i < boxes.length; i++) for (let j = i + 1; j < boxes.length; j++) {
      const a = boxes[i].r, b = boxes[j].r, w = Math.min(a.right, b.right) - Math.max(a.left, b.left), h = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
      if (w > 1 && h > Math.min(a.height, b.height) * 0.3) problems.push('overlap: "' + boxes[i].t.textContent + '" / "' + boxes[j].t.textContent + '"');
    }
    /* cut off: a label running past its own drawing (an svg that scrolls is its full size, so scrolled text is fine) */
    if (!allow('clip')) all.map(t => ({ t, r: t.getBoundingClientRect() })).forEach(({ t, r }) => {
      const sv = t.ownerSVGElement.getBoundingClientRect();
      if (r.left < sv.left - 1.5 || r.right > sv.right + 1.5 || r.top < sv.top - 2 || r.bottom > sv.bottom + 2) problems.push('clipped: "' + t.textContent + '"');
    });
    /* contrast: text color against what is painted behind its middle (a halo label against the surface) */
    const shapes = allow('contrast') ? [] : shapesOf(box);
    if (!allow('contrast')) texts.forEach(t => {
      if (t.closest('.dim')) return;
      const st = getComputedStyle(t), fg = parse(st.fill); if (!fg) return;
      let op = parseFloat(st.opacity) * parseFloat(st.fillOpacity); for (let p = t.parentElement; p && p !== box; p = p.parentElement) op *= parseFloat(getComputedStyle(p).opacity);
      const r = t.getBoundingClientRect(), halo = t.classList.contains('lbl') && !t.classList.contains('in') && st.stroke !== 'none';
      const bg = halo ? (parse(getComputedStyle(box).backgroundColor) || [255, 255, 255]) : paintAt(r.left + r.width / 2, r.top + r.height / 2, box, shapes);
      const ink = over(fg, bg, Math.min(1, op * fg[3])), cr = ratio(ink, bg), size = parseFloat(st.fontSize);
      if (cr < (size >= 14 ? 2.6 : 3)) problems.push('contrast ' + cr.toFixed(2) + ': "' + t.textContent + '"');
    });
    /* the worst first: text on text, cut off, bad numbers, contrast, then typography */
    const rank = s => ['overlap', 'clipped', 'bad', 'false', 'doubled', 'contrast', 'typography'].findIndex(p => s.startsWith(p));
    const uniq = [...new Set(problems)].sort((a, b) => rank(a) - rank(b));
    const kinds = {}; uniq.forEach(p => { const n = p.split(/[ :]/)[0]; kinds[n] = (kinds[n] || 0) + 1; });
    out.cases.push({ k, title, texts: texts.length, problems: uniq.slice(0, 12) });
    if (uniq.length) out.fails.push(k + ' ' + title + ' ' + JSON.stringify(kinds) + ': ' + uniq.slice(0, 5).join(' | '));
  });
  out.thrown = LOG.filter(x => x[0] === 'THROW' || x[0] === 'FAILED').map(x => x.join(' ').slice(0, 300));
  out.ok = out.fails.length === 0 && out.thrown.length === 0;
  return { ok: out.ok, fails: out.fails, thrown: out.thrown, cases: out.cases.map(c => c.k + ' ' + c.title + ' (' + c.texts + ' texts)' + (c.problems.length ? ': ' + c.problems.join(' | ') : '')) };
})()
