/* ---------------- D2D Relay > Branding (app/branding.py): the organisation's brand, needed before any dashboard starts
   (2026-11-19). A palette (logo + a few words -> 2-3 palettes from the Relay Model, or a standard palette) and fonts (a body
   font and an optional heading font from Power BI's own list), with a live preview. Only owners change it; everyone else
   sees it. #/branding?return=new goes back to New dashboard once the brand is set (?return=setup: to the organisation
   setup's Theme step, item 81). The tour's brand step draws it inside its own box (opts.into). Only reports use the
   brand: the app and Ask Relay keep their own look. ---------------- */
const BRAND_RETURN = {new: '#/new', setup: '#/setup?step=theme'};      // #/branding?return=<key>: where Continue goes
const BRAND_BACK = {new: ['Continue to New dashboard', 'New dashboard'], setup: ['Continue the setup', 'The organisation setup']};   // its button, and what waits
/* a Power BI font as CSS for the previews: this device's fonts (Power BI serves Segoe UI and DIN itself) */
function brandFontCss(name) {
  const n = name || 'Segoe UI';
  const segoe = {'Segoe UI': 400, 'Segoe UI Light': 300, 'Segoe UI Semibold': 600, 'Segoe UI Bold': 700};
  if (n in segoe) return {family: `"${n}", "Segoe UI", system-ui, sans-serif`, weight: segoe[n]};
  if (n === 'DIN' || n === 'DIN Light') return {family: `"${n}", "Bahnschrift", "D-DIN", Arial, sans-serif`, weight: n === 'DIN' ? 400 : 300};
  const generic = ['Consolas', 'Courier New'].includes(n) ? 'monospace' : ['Cambria', 'Constantia', 'Georgia', 'Times New Roman'].includes(n) ? 'serif' : 'sans-serif';
  return {family: `"${n}", ${generic}`, weight: n === 'Arial Black' ? 900 : 400};
}
/* el in a brand font; a title is bold, as Power BI draws visual titles, unless its font is named for its weight */
function brandFont(el, name, title) {
  const f = brandFontCss(name);
  el.style.fontFamily = f.family;
  el.style.fontWeight = String(title && !/(Light|Semibold|Bold|Black)$/.test(name || '') ? 700 : f.weight);
  return el;
}

async function renderBranding(opts = {}) {    // opts.into: draw inside that box (the tour); opts.onChange(b): after it loads and after each change (null: it did not load)
  const route = opts.route || '#/branding';
  const page = opts.into || h('div', {class: 'page'});
  if (!opts.into) { $('#main').replaceChildren(page); document.title = 'Branding - D2D Relay'; }
  let b;
  try { b = await api('/api/branding'); } catch (e) { if (opts.onChange) opts.onChange(null); return page.append(h('div', {class: 'note err'}, e.message)); }
  if (!location.hash.startsWith(route)) return;
  const o = typeof ORG === 'function' ? ORG() : {}, org = o.name || 'Your organisation', edit = !!b.may_edit;
  const backKey = opts.into ? '' : new URLSearchParams(location.hash.split('?')[1] || '').get('return') || '';
  const back = Object.prototype.hasOwnProperty.call(BRAND_RETURN, backKey) ? BRAND_RETURN[backKey] : null;
  const backTo = BRAND_BACK[backKey] || BRAND_BACK.new;

  const sw = (c, size) => h('i', {title: c, style: `display:inline-block;width:${size || 22}px;height:${size || 22}px;border-radius:5px;background:${c};border:1px solid rgba(0,0,0,.08)`});
  const same = (x, y) => !!x && !!y && x.name === y.name && x.accent === y.accent && String(x.colors) === String(y.colors) && x.look === y.look && !!x.dark === !!y.dark;
  const lookName = v => v.look === '3d' ? '3D' : v.look[0].toUpperCase() + v.look.slice(1);
  const logoBox = h('div');
  const file = h('input', {type: 'file', accept: 'image/png,image/jpeg,image/webp,image/svg+xml', style: 'display:none'});
  const desc = h('textarea', {rows: 4, placeholder: 'For example: "A premium outdoor-gear retailer. Calm, earthy and trustworthy; deep forest green with warm sand. Reports go to the board."'});
  desc.value = b.description || '';
  const genBtn = h('button', {class: 'btn primary', type: 'button'}, icon('spark'), 'Make palettes');
  const status = h('div', {class: 'muted small'});
  const variantsBox = h('div', {class: 'stack', style: 'margin-top:12px'});
  const banner = h('div'), foot = h('div'), bigPreview = h('div');

  // the fonts: chosen here, used by every preview on the page as soon as they change
  const fontSel = (label, withSame) => h('select', {class: 'sel', 'aria-label': label, disabled: !edit},
    withSame ? h('option', {value: ''}, 'Same as the body font') : null,
    h('optgroup', {label: "Power BI's own fonts (the same on every device)"}, b.fonts.filter(f => f.served).map(f => h('option', {value: f.name}, f.name))),
    h('optgroup', {label: 'Windows and Office fonts'}, b.fonts.filter(f => !f.served).map(f => h('option', {value: f.name}, f.name))));
  const bodySel = fontSel('Body font', false), headSel = fontSel('Heading font', true);
  const setFonts = () => { bodySel.value = b.font; headSel.value = b.heading_font || ''; };
  const fonts = () => { const body = bodySel.value || b.font; return {body, head: headSel.value || body}; };
  setFonts();

  const drawLogo = () => logoBox.replaceChildren(
    b.logo ? h('div', {class: 'row', style: 'gap:16px;align-items:center;flex-wrap:wrap'},
      h('div', {style: 'background:#fff;border:1px solid var(--line);border-radius:12px;padding:12px;display:grid;place-items:center;min-width:140px'},
        h('img', {src: b.logo, alt: 'Your logo', style: 'max-height:64px;max-width:200px;object-fit:contain'})),
      h('div', {}, h('div', {class: 'small muted', style: 'margin-bottom:6px'}, 'Colours found in your logo'),
        b.logo_colors.length ? h('div', {class: 'row', style: 'gap:6px'}, b.logo_colors.map(c => sw(c))) : h('span', {class: 'small muted'}, 'None found: describe your colours below.'),
        h('div', {class: 'row', style: 'gap:8px;margin-top:10px'},
          h('button', {class: 'btn sm', type: 'button', onclick: () => file.click()}, icon('edit'), 'Replace logo'),
          h('button', {class: 'btn sm ghost', type: 'button', onclick: async () => {
            try { b = await api('/api/branding/logo', {method: 'DELETE'}); drawLogo(); } catch (e) { notify(e.message, 'err'); } }}, icon('x'), 'Remove'))))
    : h('button', {class: 'card empty', type: 'button', style: 'width:100%;cursor:pointer;margin:0', onclick: () => file.click()},
        h('h3', {}, icon('image'), ' Add your logo'), 'PNG, JPG, WebP or SVG, up to 1.5 MB. Relay reads its colours.'));
  file.onchange = async () => {
    if (!file.files.length) return;
    const fd = new FormData(); fd.append('file', file.files[0]);
    status.textContent = 'Reading your logo...';
    try { b = await upload('/api/branding/logo', fd); status.textContent = ''; drawLogo(); }
    catch (e) { status.replaceChildren(h('span', {class: 'err-msg'}, e.message)); }
    file.value = '';
  };

  const look = v => ({radius: v.look === 'flat' ? 4 : v.look === '3d' ? 8 : 12,
    shadow: v.look === 'flat' ? 'none' : v.look === '3d' ? '0 6px 14px rgba(0,0,0,.25)' : '0 2px 8px rgba(0,0,0,.08)',
    border: v.look === 'flat' ? '1px solid rgba(127,127,127,.25)' : '0',
    ink: v.dark ? '#F5F5F5' : '#111111', muted: v.dark ? '#A8A8A8' : '#6B6B6B', card: v.dark ? '#1E1E1E' : '#FFFFFF', page: v.dark ? '#0A0A0A' : '#F4F4F4'});
  const preview = v => {       // a small report-like preview in the palette and the fonts
    const s = look(v), f = fonts(), bars = [0.9, 0.62, 0.78, 0.45, 0.7, 0.35];
    const box = `background:${s.card};color:${s.ink};border-radius:${s.radius}px;box-shadow:${s.shadow};border:${s.border};padding:10px;min-width:0`;
    return h('div', {style: `background:${s.page};border-radius:10px;padding:10px;display:grid;grid-template-columns:1fr 1.4fr;gap:8px`},
      h('div', {style: box},
        brandFont(h('div', {style: 'font-size:11px'}, 'Revenue'), f.head, true), brandFont(h('div', {style: `font-size:22px;color:${v.accent}`}, '4.2M'), f.body),
        brandFont(h('div', {style: `font-size:11px;color:${s.muted}`}, '+8.1% vs last year'), f.body)),
      h('div', {style: box + ';display:flex;align-items:flex-end;gap:5px;height:84px'},
        bars.map((x, i) => h('i', {style: `flex:1;height:${x * 100}%;background:${v.colors[i % v.colors.length]};border-radius:3px 3px 0 0`}))));
  };
  const drawPreview = () => {  // the fonts card: a report page in the palette in use (or a stand-in until one is picked)
    const v = b.style || b.variants[0] || b.standard[0], s = look(v), f = fonts();
    const box = (...kids) => h('div', {style: `background:${s.card};color:${s.ink};border-radius:${s.radius}px;box-shadow:${s.shadow};border:${s.border};padding:12px;min-width:0`}, ...kids);
    const title = (text, sub) => [brandFont(h('div', {style: 'font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis'}, text), f.head, true),
      sub ? brandFont(h('div', {style: `font-size:11px;color:${s.muted};margin-bottom:6px`}, sub), f.body) : null];
    const text = (t, css) => brandFont(h('div', {style: css || ''}, t), f.body);
    const kpi = (name, value, note) => box(title(name), text(value, 'font-size:26px;line-height:1.2;margin-top:4px'), text(note, `font-size:11px;color:${s.muted}`));
    const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun'], now = [62, 70, 66, 78, 84, 90], last = [58, 61, 64, 69, 72, 80];
    const chart = box(title('Sales are 4% ahead of last year', 'Net sales by month, this year and last'),
      h('div', {style: 'display:flex;align-items:flex-end;gap:10px;height:96px;margin-top:4px'}, months.map((m, i) =>
        h('div', {style: 'flex:1;display:flex;flex-direction:column;align-items:center;gap:4px;height:100%;justify-content:flex-end'},
          h('div', {style: 'display:flex;align-items:flex-end;gap:2px;width:100%;height:100%'},
            h('i', {style: `flex:1;height:${now[i]}%;background:${v.colors[0]};border-radius:2px 2px 0 0`}),
            h('i', {style: `flex:1;height:${last[i]}%;background:${v.colors[1 % v.colors.length]};border-radius:2px 2px 0 0`})),
          text(m, `font-size:10.5px;color:${s.muted}`)))),
      h('div', {class: 'row', style: 'gap:12px;margin-top:6px'}, ...[['This year', v.colors[0]], ['Last year', v.colors[1 % v.colors.length]]].map(([t, c]) =>
        text([h('i', {style: `display:inline-block;width:9px;height:9px;border-radius:2px;background:${c};margin-right:5px`}), t], `font-size:11px;color:${s.muted}`))));
    const rows = [['Store', 'Sales', 'Margin'], ['Downtown', '1.24M', '31.5%'], ['Riverside', '0.98M', '28.2%'], ['Airport', '0.71M', '25.9%']];
    const table = box(title('Downtown leads on sales and margin', 'Top stores this year'),
      h('div', {style: 'display:grid;grid-template-columns:1.4fr 1fr 1fr;gap:5px 10px;margin-top:4px'}, rows.flatMap((r, k) =>
        r.map((c, j) => text(c, `font-size:12px;${j ? 'text-align:right;' : ''}${k ? '' : `color:${s.muted};font-weight:600;`}`)))));
    const nav = h('div', {style: `display:flex;gap:6px;background:${s.card};border-radius:20px;padding:4px;border:1px solid rgba(127,127,127,.2)`},
      ['Overview', 'Stores', 'Products'].map((p, i) => text(p, `flex:1;text-align:center;font-size:12px;padding:5px 8px;border-radius:16px;${i ? `color:${s.muted}` : `background:${v.accent};color:#FFFFFF;font-weight:700`}`)));
    bigPreview.replaceChildren(
      h('div', {style: `background:${s.page};border-radius:12px;padding:12px;display:grid;gap:10px`}, nav,
        h('div', {style: 'display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px'},
          kpi('Revenue', '4.2M', '+8.1% vs last year'), kpi('Margin', '29.4%', '+1.2 pts vs last year'), kpi('Orders', '18,240', '+5.6% vs last year')),
        h('div', {style: 'display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:10px'}, chart, table)),
      h('div', {class: 'small muted', style: 'margin-top:8px'}, `Titles in ${f.head}; text and numbers in ${f.body}`,
        b.style ? `, colours from "${b.style.name}". ` : `. Shown in "${v.name}" until a palette is picked. `,
        "The preview uses this device's fonts, so it can differ a little from Power BI."));
  };

  const paletteCard = (v, on, use) => h('div', {class: 'card', style: 'margin:0;' + (on ? 'outline:2px solid var(--accent);outline-offset:-2px' : '')},
    h('div', {class: 'row', style: 'gap:8px;flex-wrap:wrap'}, h('b', {}, v.name), on ? h('span', {class: 'tag ok'}, icon('check'), 'In use') : null, h('span', {class: 'spacer'}),
      v.standard ? h('span', {class: 'tag'}, 'Standard') : null, h('span', {class: 'tag'}, lookName(v)), v.dark ? h('span', {class: 'tag'}, 'Dark') : null),
    h('div', {class: 'row', style: 'gap:4px;margin:10px 0;flex-wrap:wrap'}, v.colors.map(c => sw(c, 20))),
    preview(v),
    v.why ? h('p', {class: 'small muted', style: 'margin:8px 0'}, v.why) : null,
    on || !use ? null : h('button', {class: 'btn sm primary', type: 'button', onclick: use}, icon('check'), 'Use this palette'));
  const grid = cards => h('div', {style: 'display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:12px'}, cards);
  const drawVariants = () => {
    if (!edit) {               // everyone else sees the palette in use
      variantsBox.replaceChildren(b.style ? grid([paletteCard(b.style, true)]) : h('div', {class: 'muted small'}, 'No palette yet.'));
      return;
    }
    const others = b.standard.map((s, i) => [s, i]).filter(([s]) => !same(s, b.style));
    variantsBox.replaceChildren(
      b.variants.length ? grid(b.variants.map((v, i) => paletteCard(v, b.chosen === i, () => pick(i, false))))
        : h('div', {class: 'muted small'}, 'Your palettes appear here: Relay makes 3 from your logo and words. Or start from a standard palette.'),
      h('h4', {style: 'margin:16px 0 8px'}, b.variants.length ? 'Or a standard palette' : 'Standard palettes'),
      grid(others.map(([s, i]) => paletteCard(s, false, () => pick(i, true)))),
      h('div', {class: 'muted small', style: 'margin-top:8px'}, 'The palette in use goes into every new dashboard. Dashboards already built keep their colours until you ask for a change.'));
  };
  const goBtn = () => h('button', {class: 'btn primary', type: 'button', disabled: !b.ready, onclick: () => { location.hash = back; }}, backTo[0]);
  const drawBanner = () => {
    const msg = !b.ready ? (edit ? (back ? `${backTo[1]} needs your brand first: pick a palette below and check the fonts.`
        : 'Pick a palette and check the fonts: a dashboard can only be started once your brand is set.')
      : `${org} has no brand yet: ${o.owner && o.owner.name ? o.owner.name + ' or another owner' : 'an owner'} sets it here, and then dashboards can be started.`)
      : back ? 'Your brand is set: every new dashboard uses it.' : edit ? null : `Every report in ${org} uses this brand. Only its owners change it.`;
    banner.replaceChildren(...(msg ? [h('div', {class: 'note row ' + (!b.ready ? 'warn' : back ? 'ok' : ''), style: 'gap:10px;flex-wrap:wrap;align-items:center'},
      h('span', {style: 'flex:1;min-width:200px'}, msg), back ? goBtn() : null)] : []));
    foot.replaceChildren(...(back ? [h('div', {class: 'row', style: 'gap:10px;margin:14px 0;flex-wrap:wrap;align-items:center'}, goBtn(),
      b.ready ? null : h('span', {class: 'muted small'}, edit ? 'Pick a palette first.' : 'An owner sets the brand first.'))] : []));
  };
  const changed = () => { drawVariants(); drawPreview(); drawBanner(); if (opts.onChange) opts.onChange(b); };
  const pick = async (i, standard) => {
    try { b = await api('/api/branding/choose', {json: {index: i, standard}}); changed(); notify(`Using "${b.style.name}" for new dashboards`, 'ok'); }
    catch (e) { notify(e.message, 'err'); }
  };
  const saveFonts = async () => {
    drawVariants(); drawPreview();                     // live: the previews follow the lists at once
    bodySel.disabled = headSel.disabled = true;
    try { b = await api('/api/branding/fonts', {json: {font: bodySel.value, heading_font: headSel.value || null}}); setFonts(); changed(); notify('Fonts saved: every new dashboard uses them', 'ok'); }
    catch (e) { notify(e.message, 'err'); setFonts(); drawVariants(); drawPreview(); }
    bodySel.disabled = headSel.disabled = !edit;
  };
  bodySel.onchange = saveFonts; headSel.onchange = saveFonts;
  genBtn.onclick = async () => {
    genBtn.disabled = true;
    status.replaceChildren(h('span', {class: 'spin', style: 'display:inline-block;vertical-align:middle;margin-right:8px'}), 'Relay Model is designing 3 palettes from your logo and description...');
    try { b = await api('/api/branding/generate', {json: {description: desc.value}}); status.textContent = ''; changed(); }
    catch (e) { status.replaceChildren(h('span', {class: 'err-msg'}, e.message)); }
    genBtn.disabled = false;
  };

  drawLogo(); drawVariants(); drawPreview(); drawBanner();
  page.append(...[
    opts.into ? null : h('div', {class: 'phead'}, h('div', {style: 'flex:1'}, h('h1', {}, 'Branding'),
      h('div', {class: 'meta'}, 'Your logo and a few words about your brand. Relay Model turns them into report palettes; pick one and the fonts, and every new dashboard uses them. A dashboard can only be started once the brand is set.'))),
    opts.into ? null : banner,
    edit ? h('div', {class: 'card'}, h('h3', {}, '1 - Your logo'), file, logoBox) : null,
    edit ? h('div', {class: 'card'}, h('h3', {}, '2 - Describe your brand'), h('div', {class: 'muted small', style: 'margin-bottom:6px'}, 'Who you are, the feeling you want, colours to use or avoid, light or dark reports. Optional if you added a logo.'),
      desc, h('div', {class: 'row', style: 'margin-top:10px;gap:10px;flex-wrap:wrap'}, genBtn, status)) : null,
    h('div', {class: 'card'}, h('h3', {}, edit ? '3 - Pick a palette' : 'Palette'), variantsBox),
    h('div', {class: 'card'}, h('h3', {}, edit ? '4 - Fonts' : 'Fonts'),
      h('div', {class: 'muted small', style: 'margin-bottom:6px'}, "Every report uses them. Power BI's own fonts look the same everywhere; Windows and Office fonts depend on the reader's device."),
      h('div', {class: 'opts'},
        h('div', {}, h('label', {class: 'f', style: 'margin-top:0'}, 'Body font', h('small', {}, 'text, numbers, tables, slicers')), bodySel),
        h('div', {}, h('label', {class: 'f', style: 'margin-top:0'}, 'Heading font', h('small', {}, 'visual titles')), headSel)),
      h('div', {style: 'margin-top:12px'}, bigPreview)),
    opts.into ? null : foot].filter(Boolean));
  if (opts.onChange) opts.onChange(b);
}
