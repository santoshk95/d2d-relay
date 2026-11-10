/* ---------------- D2D Relay › Branding: logo + a few words -> 2-3 palettes from the Relay Model -> pick one ---------------- */
async function renderBranding() {
  const page = h('div', {class: 'page'});
  $('#main').replaceChildren(page);
  document.title = 'Branding · D2D Relay';
  let b;
  try { b = await api('/api/branding'); } catch (e) { return page.append(h('div', {class: 'note err'}, e.message)); }
  if (!location.hash.startsWith('#/branding')) return;

  const sw = (c, size) => h('i', {title: c, style: `display:inline-block;width:${size || 22}px;height:${size || 22}px;border-radius:5px;background:${c};border:1px solid rgba(0,0,0,.08)`});
  const logoBox = h('div');
  const file = h('input', {type: 'file', accept: 'image/png,image/jpeg,image/webp,image/svg+xml', style: 'display:none'});
  const desc = h('textarea', {rows: 4, placeholder: 'For example: "A premium outdoor-gear retailer. Calm, earthy and trustworthy; deep forest green with warm sand. Reports go to the board."'});
  desc.value = b.description || '';
  const genBtn = h('button', {class: 'btn primary', type: 'button'}, icon('spark'), 'Make palettes');
  const status = h('div', {class: 'muted small'});
  const variantsBox = h('div', {class: 'stack', style: 'margin-top:12px'});

  const drawLogo = () => logoBox.replaceChildren(
    b.logo ? h('div', {class: 'row', style: 'gap:16px;align-items:center'},
      h('div', {style: 'background:#fff;border:1px solid var(--line);border-radius:12px;padding:12px;display:grid;place-items:center;min-width:140px'},
        h('img', {src: b.logo, alt: 'Your logo', style: 'max-height:64px;max-width:200px;object-fit:contain'})),
      h('div', {}, h('div', {class: 'small muted', style: 'margin-bottom:6px'}, 'Colours found in your logo'),
        b.logo_colors.length ? h('div', {class: 'row', style: 'gap:6px'}, b.logo_colors.map(c => sw(c))) : h('span', {class: 'small muted'}, 'None found: describe your colours below.'),
        h('div', {class: 'row', style: 'gap:8px;margin-top:10px'},
          h('button', {class: 'btn sm', type: 'button', onclick: () => file.click()}, icon('edit'), 'Replace logo'),
          h('button', {class: 'btn sm ghost', type: 'button', onclick: async () => { b = await api('/api/branding/logo', {method: 'DELETE'}); drawLogo(); }}, icon('x'), 'Remove'))))
    : h('button', {class: 'card empty', type: 'button', style: 'width:100%;cursor:pointer;margin:0', onclick: () => file.click()},
        h('h3', {}, icon('image'), ' Add your logo'), 'PNG, JPG, WebP or SVG, up to 1.5 MB. Relay reads its colours.'));
  file.onchange = async () => {
    if (!file.files.length) return;
    const fd = new FormData(); fd.append('file', file.files[0]);
    status.textContent = 'Reading your logo…';
    try { b = await upload('/api/branding/logo', fd); status.textContent = ''; drawLogo(); }
    catch (e) { status.replaceChildren(h('span', {class: 'err-msg'}, e.message)); }
    file.value = '';
  };

  const preview = v => {       // a small report-like preview in the palette
    const bg = v.dark ? '#141414' : '#FFFFFF', ink = v.dark ? '#F5F5F5' : '#111111', card = v.dark ? '#1E1E1E' : '#FFFFFF';
    const radius = v.look === 'flat' ? 4 : v.look === '3d' ? 8 : 12;
    const shadow = v.look === 'flat' ? 'none' : v.look === '3d' ? '0 6px 14px rgba(0,0,0,.25)' : '0 2px 8px rgba(0,0,0,.08)';
    const bars = [0.9, 0.62, 0.78, 0.45, 0.7, 0.35];
    return h('div', {style: `background:${v.dark ? '#0A0A0A' : '#F4F4F4'};border-radius:10px;padding:10px;display:grid;grid-template-columns:1fr 1.4fr;gap:8px`},
      h('div', {style: `background:${card};color:${ink};border-radius:${radius}px;box-shadow:${shadow};padding:10px;border:${v.look === 'flat' ? '1px solid rgba(127,127,127,.25)' : '0'}`},
        h('div', {style: 'font-size:11px;opacity:.7'}, 'Revenue'), h('div', {style: `font-size:22px;font-weight:700;color:${v.accent}`}, '4.2M'),
        h('div', {style: 'font-size:11px;opacity:.7'}, '+8.1% vs last year')),
      h('div', {style: `background:${card};border-radius:${radius}px;box-shadow:${shadow};padding:10px;display:flex;align-items:flex-end;gap:5px;height:84px;border:${v.look === 'flat' ? '1px solid rgba(127,127,127,.25)' : '0'}`},
        bars.map((x, i) => h('i', {style: `flex:1;height:${x * 100}%;background:${v.colors[i % v.colors.length]};border-radius:3px 3px 0 0`}))));
  };
  const drawVariants = () => {
    if (!b.variants.length) { variantsBox.replaceChildren(h('div', {class: 'muted small'}, 'Your palettes appear here. Relay makes 3; pick the one you like.')); return; }
    variantsBox.replaceChildren(h('div', {class: 'grid3', style: 'display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px'},
      b.variants.map((v, i) => {
        const on = b.chosen === i;
        return h('div', {class: 'card', style: 'margin:0;' + (on ? 'outline:2px solid var(--accent);outline-offset:-2px' : '')},
          h('div', {class: 'row', style: 'gap:8px'}, h('b', {}, v.name), on ? h('span', {class: 'tag ok'}, icon('check'), 'In use') : null, h('span', {class: 'spacer'}),
            h('span', {class: 'tag'}, v.look === '3d' ? '3D' : v.look[0].toUpperCase() + v.look.slice(1)), v.dark ? h('span', {class: 'tag'}, 'Dark') : null),
          h('div', {class: 'row', style: 'gap:4px;margin:10px 0'}, v.colors.map(c => sw(c, 20))),
          preview(v),
          v.why ? h('p', {class: 'small muted', style: 'margin:8px 0'}, v.why) : null,
          on ? h('button', {class: 'btn sm', type: 'button', onclick: () => pick(null)}, 'Stop using it')
            : h('button', {class: 'btn sm primary', type: 'button', onclick: () => pick(i)}, icon('check'), 'Use this palette'));
      })),
      h('div', {class: 'muted small', style: 'margin-top:8px'}, 'The palette you pick is used for every new dashboard (you can untick it on New dashboard). Dashboards already built keep their colours until you ask for a change.'));
  };
  const pick = async i => {
    try { b = await api('/api/branding/choose', {json: {index: i}}); drawVariants(); notify(i == null ? 'Brand palette switched off' : `Using “${b.variants[i].name}” for new dashboards`, 'ok'); }
    catch (e) { notify(e.message, 'err'); }
  };
  genBtn.onclick = async () => {
    genBtn.disabled = true;
    status.replaceChildren(h('span', {class: 'spin', style: 'display:inline-block;vertical-align:middle;margin-right:8px'}), 'The Relay Model is designing 3 palettes from your logo and description…');
    try { b = await api('/api/branding/generate', {json: {description: desc.value}}); status.textContent = ''; drawVariants(); }
    catch (e) { status.replaceChildren(h('span', {class: 'err-msg'}, e.message)); }
    genBtn.disabled = false;
  };

  drawLogo(); drawVariants();
  page.append(
    h('div', {class: 'phead'}, h('div', {style: 'flex:1'}, h('h1', {}, 'Branding'),
      h('div', {class: 'meta'}, 'Your logo and a few words about your brand. The Relay Model turns them into report palettes; pick one and every new dashboard uses it.'))),
    h('div', {class: 'card'}, h('h3', {}, '1 · Your logo'), file, logoBox),
    h('div', {class: 'card'}, h('h3', {}, '2 · Describe your brand'), h('div', {class: 'muted small', style: 'margin-bottom:6px'}, 'Who you are, the feeling you want, colours to use or avoid, light or dark reports. Optional if you added a logo.'),
      desc, h('div', {class: 'row', style: 'margin-top:10px;gap:10px'}, genBtn, status)),
    h('div', {class: 'card'}, h('h3', {}, '3 · Pick a palette'), variantsBox));
}
