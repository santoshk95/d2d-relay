/* ---------------- All modules, module pages and Admin › Branding (P9) ---------------- */
const WORK_NAME = {assess: 'Assess', develop: 'Develop', change: 'Fix / change', migrate: 'Migrate', run: 'Run & support', engage: 'Engagement'};
const STATE_PILL = {available: ['Live', 'ok'], partly: ['Partly live', 'info'], preview: ['Design preview', 'info'], planned: ['Planned', 'mute'], locked: ['Not in your plan', 'outline'],
  off: ['Not switched on', 'mute']};
const statePill = st => { const [t, c] = STATE_PILL[st] || [st, 'mute']; return h('span', {class: 'pill plain ' + c}, t); };
const brandName = () => (S.brand && S.brand.partner) ? S.brand.name : 'Relay';
function pageHead({crumbs, eyebrow, title, promise, actions}) {
  return h('div', {class: 'ph'},
    crumbs ? h('div', {class: 'crumbs'}, crumbs.map((c, i) => [i ? h('span', {'aria-hidden': 'true'}, '/') : null, c[1] ? h('a', {href: c[1]}, c[0]) : h('span', {}, c[0])])) : null,
    h('div', {class: 'ph-row'}, h('div', {}, eyebrow ? h('div', {class: 'eyebrow'}, eyebrow) : null, h('h1', {}, title), promise ? h('div', {class: 'promise'}, promise) : null),
      actions ? h('div', {class: 'ph-actions'}, actions) : null));
}
function moduleCard(m) {
  const st = m.state, open = st === 'available' ? m.route : '#/m/' + m.id;
  return h(st === 'locked' ? 'div' : 'a', {class: 'pcard ' + st, href: st === 'locked' ? null : open, 'aria-label': `${m.name}: ${STATE_PILL[st] ? STATE_PILL[st][0] : st}`},
    h('div', {class: 'ptop'}, h('div', {class: 'pico'}, icon(m.icon)), statePill(st)),
    h('div', {class: 'pname'}, m.name), h('div', {class: 'psub'}, m.sub), h('div', {class: 'ptext'}, m.text),
    m.platforms.length ? h('div', {class: 'pchips'}, m.platforms.slice(0, 3).map(p => h('span', {class: 'chipx'}, p)), m.platforms.length > 3 ? h('span', {class: 'chipx'}, '+' + (m.platforms.length - 3)) : null) : null,
    h('div', {class: 'pstat'}, m.work.length ? m.work.map(w => WORK_NAME[w]).join(' · ') : m.pl === 'consulting' ? 'Engagement' : (m.stat || '')),
    h('div', {class: 'popen'}, st === 'available' ? 'Open →' : st === 'locked' ? 'Ask about this module' : m.pl === 'consulting' ? 'Engage PASDACS →' : 'How it will work →'));
}
async function renderModules() {
  if (!S.registry) await loadRegistry();
  const reg = S.registry, me = S.me || {};
  if (!reg) { $('#main').replaceChildren(h('div', {class: 'page'}, h('div', {class: 'note err'}, 'The module registry could not be loaded.'))); return; }
  const sections = reg.pillars.map(p => [p, reg.modules.filter(m => m.pl === p.id)]).filter(x => x[1].length);
  const total = sections.reduce((n, s) => n + s[1].length, 0);
  $('#main').replaceChildren(h('div', {class: 'page'},
    pageHead({crumbs: [['Home', '#/'], ['All modules']], eyebrow: brandName() + ' · All modules', title: 'Everything Relay does, by pillar',
      promise: `Six pillars, ${total} modules. Live ones open their screen; planned ones show how they will work, step by step, before they are built.`,
      actions: me.builder === false ? null : h('a', {class: 'btn primary', href: '#/new'}, icon('plus'), 'New dashboard')}),
    h('div', {class: 'row', style: 'gap:8px'}, sections.map(([p]) => h('button', {class: 'btn sm', type: 'button', onclick: () => document.getElementById('pl-' + p.id).scrollIntoView({behavior: 'smooth'})}, p.name))),
    h('div', {class: 'note', style: 'margin:16px 0 4px'}, h('b', {}, 'Every module lists the work it does: '), 'Assess · Develop · Fix / change · Migrate · Run & support. Consulting modules are engagements.'),
    ...sections.flatMap(([p, ms]) => [
      h('div', {class: 'section-title', id: 'pl-' + p.id}, h('h2', {}, p.name), h('span', {class: 'small muted'}, p.line),
        h('span', {class: 'hint'}, `${ms.filter(m => ['available', 'partly', 'preview'].includes(m.state)).length} of ${ms.length} ready`)),
      h('div', {class: 'products'}, ms.map(moduleCard))]),
    me.admin ? null : h('p', {class: 'small muted', style: 'margin-top:24px'}, 'You see the modules your role uses. Ask an admin if you need another.')));
  document.title = `All modules · ${S.brand ? S.brand.full : 'RELAY by PASDACS'}`;
}
async function renderModule(id, work) {
  const main = $('#main');
  main.replaceChildren(skel('page'));
  let m;
  try { m = await api(`/api/registry/${id}` + (work ? `?work=${encodeURIComponent(work)}` : '')); }
  catch (e) { main.replaceChildren(h('div', {class: 'page'}, h('div', {class: 'card empty'}, h('h3', {}, 'Nothing here'), h('p', {}, e.message), h('a', {class: 'btn', href: '#/modules'}, 'All modules')))); return; }
  if (!location.hash.startsWith('#/m/' + id)) return;
  const pillar = (S.registry && S.registry.pillars.find(p => p.id === m.pl)) || {name: ''};
  const w = m.work_type, b = S.brand || {};
  // P11: the consulting modules whose last step is a deck or pack ("Present", "Deck", "Propose") hand it to the studio with the module's facts as a source
  const studioType = (S.studioTypes || {})[m.id], viaStudio = m.state === 'partly' && m.live[w] === '#/studio';
  const liveRoute = viaStudio ? null : (m.live[w] || (m.state === 'available' && !m.work.length ? m.route : null));
  const studioHref = `#/studio?type=${encodeURIComponent(studioType || 'proposal')}&module=${encodeURIComponent(m.id)}`;
  if (m.state === 'locked') {
    main.replaceChildren(h('div', {class: 'page'},
      pageHead({crumbs: [['Home', '#/'], ['All modules', '#/modules'], [m.name]], eyebrow: brandName() + ' · ' + pillar.name, title: m.name, promise: m.text, actions: statePill('locked')}),
      h('div', {class: 'card', style: 'max-width:720px'}, h('h3', {}, 'This module isn’t part of your plan yet'),
        h('p', {class: 'muted'}, b.partner ? `${b.full} can add it.` : 'A PASDACS consultant can switch it on. Your data and work stay as they are.'),
        h('button', {class: 'btn primary', type: 'button', onclick: () => interest(m)}, b.partner ? 'Ask ' + b.name : 'Ask a PASDACS consultant'))));
    return;
  }
  if (m.state === 'off') {                      // P17: switched off for this workspace — the same page the workbench shows
    if (typeof wbOff === 'function') return wbOff(id, false);
    const t = (S.me || {}).tenant || {};
    main.replaceChildren(h('div', {class: 'page'},
      pageHead({crumbs: [['Home', '#/'], ['All modules', '#/modules'], [m.name]], eyebrow: brandName() + ' · ' + pillar.name, title: m.name, promise: m.text, actions: statePill('off')}),
      h('div', {class: 'card', style: 'max-width:720px'}, h('h3', {}, `Not switched on for ${t.name || 'this workspace'}`),
        h('p', {class: 'muted'}, `${m.name} is not switched on for this workspace, so its screens cannot be opened here. Nothing is deleted: what was made with it comes back when it is switched on again.`),
        h('button', {class: 'btn primary', type: 'button', onclick: () => interest(m)}, 'Ask your administrator'))));
    return;
  }
  main.replaceChildren(h('div', {class: 'page'},
    pageHead({crumbs: [['Home', '#/'], ['All modules', '#/modules'], [m.name]], eyebrow: `${brandName()} · ${pillar.name} · ${m.name}`, title: m.sub, promise: m.text, actions: statePill(m.state)}),
    m.work.length ? h('div', {class: 'row', style: 'margin-bottom:12px'}, h('span', {class: 'small muted'}, 'What do you need?'),
      h('nav', {class: 'worktabs', 'aria-label': 'Work type'}, m.work.map(k => h('a', {href: `#/m/${id}/${k}`, class: k === w ? 'on' : '', 'aria-current': k === w ? 'page' : null}, (m.live[k] ? '● ' : '') + WORK_NAME[k])))) : null,
    h('ol', {class: 'journey', 'aria-label': 'How it works'}, m.plan.journey.map((j, i) => h('li', {class: viaStudio && i === m.plan.journey.length - 1 ? 'on' : ''}, h('span', {class: 'dot'}), h('div', {class: 'jl'}, `${i + 1} ${j}`), h('div', {class: 'js'}, i === 0 ? 'starts here' : viaStudio && i === m.plan.journey.length - 1 ? 'in the studio' : ' ')))),
    h('div', {class: 'g-side'},
      h('div', {class: 'stack'},
        liveRoute ? h('div', {class: 'banner ok'}, h('div', {class: 'ic'}, icon('check')), h('div', {class: 'txt'}, h('div', {class: 't'}, 'Live today.'), h('div', {class: 'd'}, 'This work runs in the app now.')), h('a', {class: 'btn primary', href: liveRoute}, 'Open'))
          : viaStudio ? h('div', {class: 'banner ok'}, h('div', {class: 'ic'}, icon('check')), h('div', {class: 'txt'}, h('div', {class: 't'}, `Partly live: the last step, ${m.plan.journey[m.plan.journey.length - 1]}, runs in the studio.`), h('div', {class: 'd'}, `The deck or pack is drafted from this module's facts and the records you pick, in your template, every figure sourced — ${m.stat || 'through Proposals & decks'}.`)),
            (S.me || {}).builder === false ? null : h('a', {class: 'btn primary', href: studioHref}, icon('file'), 'Prepare the deck in the studio'))
          : h('div', {class: 'banner info'}, h('div', {class: 'ic'}, icon('info')), h('div', {class: 'txt'}, h('div', {class: 't'}, m.state === 'partly' ? 'Partly live.' : m.state === 'preview' ? 'Designed, not built yet.' : 'Planned.'),
            h('div', {class: 'd'}, m.plan.live || 'This page shows how it will work; it is designed step by step before it is built.'))),
        h('div', {class: 'card', style: 'margin:0'}, h('div', {class: 'card-head'}, h('h3', {}, 'How it works — ' + (WORK_NAME[w] || 'engagement').toLowerCase())), h('div', {class: 'ph-steps'}, m.plan.steps.map(s => h('div', {}, s)))),
        m.platforms.length ? h('div', {class: 'card', style: 'margin:0'}, h('div', {class: 'card-head'}, h('h3', {}, 'Platforms'), h('span', {class: 'sp'}), h('span', {class: 'small muted'}, m.platforms.length + ' covered')),
          h('div', {class: 'row', style: 'gap:8px'}, m.platforms.map(p => h('span', {class: 'chipx'}, p))),
          h('p', {class: 'small muted', style: 'margin:10px 0 0'}, 'Missing one? Tell us — new platforms are added as connectors and rules, and reused by every client.')) : null),
      h('div', {class: 'stack'},
        h('div', {class: 'card', style: 'margin:0'}, h('h3', {}, 'Where you confirm'), h('div', {class: 'small muted', style: 'margin:4px 0 10px'}, 'Always a person in the loop — the agent waits at each of these:'),
          h('div', {class: 'confirm'}, m.confirm.map(([s, v]) => h('div', {}, h('span', {class: 'proven'}, icon('check')), h('span', {}, h('b', {}, s + ': '), v))))),
        typeof connectionsCard === 'function' && m.platforms.length && (S.me || {}).builder !== false ? connectionsCard(m) : null,     // P10: the module's connections and the wizard
        h('div', {class: 'card', style: 'margin:0'}, h('h3', {}, 'Same rules as everywhere'), h('div', {class: 'rules', style: 'margin-top:8px'}, m.rules.map(t => h('div', {}, icon('check'), t)))),
        m.plan.builds ? h('div', {class: 'card', style: 'margin:0'}, h('h3', {}, 'Works with'), h('div', {class: 'row', style: 'gap:6px;margin-top:8px'}, m.plan.builds.map(x => h('span', {class: 'chipx'}, x)))) : null,
        h('div', {class: 'card', style: 'margin:0'}, h('h3', {}, m.state === 'available' ? 'Need something else?' : 'Want it sooner?'),
          h('p', {class: 'small muted'}, 'Tell us the systems involved — it decides what we build first.'),
          h('button', {class: 'btn', type: 'button', onclick: () => interest(m)}, 'I need this'))))));
  document.title = `${m.name} · ${b.full || 'RELAY by PASDACS'}`;
}
async function interest(m) {
  try { await api(`/api/registry/${m.id}/interest`, {method: 'POST'}); notify(`Noted — ${m.name} is on the list; the admins have been told.`, 'ok'); }
  catch (e) { notify(e.message, 'err'); }
}

/* ---------------- Admin › Branding (white-label, hourly rate, edition) ---------------- */
async function adminBranding() {
  const d = await api('/api/admin/branding'), s = {...d.saved}, b = d.brand;
  const fld = (label, el, hint) => h('div', {}, h('label', {class: 'f'}, label), el, hint ? h('div', {class: 'hint'}, hint) : null);
  const partner = h('input', {type: 'checkbox', checked: !!b.partner});
  const name = h('input', {type: 'text', value: s.name || b.name, placeholder: 'Short name, e.g. Northwind'});
  const full = h('input', {type: 'text', value: s.full || b.full, placeholder: 'Full name, e.g. Northwind DataWorks'});
  const tagline = h('input', {type: 'text', value: s.tagline ?? b.tagline, placeholder: 'One line under the name'});
  const mark = h('input', {type: 'text', value: s.mark || b.mark, maxlength: 3, style: 'max-width:90px'});
  const color = h('input', {type: 'color', value: s.color || b.color, class: 'swatch', style: 'width:48px;height:32px'});
  const accent = h('select', {class: 'sel'}, d.accents.map(a => h('option', {value: a, selected: a === b.accent}, {signal: 'Mint (Relay, PASDACS brand)', gold: 'Gold', teal: 'Teal', ink: 'Ink'}[a] || a)));
  const sender = h('input', {type: 'text', value: s.sender || b.sender, placeholder: 'Name on outgoing mail'});
  const contact = h('input', {type: 'email', value: s.contact ?? b.contact ?? '', placeholder: 'info@pasdacs.com'});
  const edition = h('select', {class: 'sel'}, [['both', 'Both (enterprise and partner modules)'], ['enterprise', 'Enterprise: a company running its own data and analytics'], ['partner', 'Service partner: delivering for clients']].map(([v, l]) => h('option', {value: v, selected: v === b.edition}, l)));
  const rate = h('input', {type: 'number', min: 0, step: 50, value: b.hourly_rate || 0, style: 'max-width:160px', 'aria-label': 'Hourly rate'});
  const currency = h('input', {type: 'text', value: b.currency || '₹', maxlength: 4, style: 'max-width:80px', 'aria-label': 'Currency symbol'});
  const fx = h('input', {type: 'number', min: 0.0001, step: 0.01, value: b.usd_rate || 1, style: 'max-width:160px'});
  // P11: the studio's templates (PowerPoint and Word, up to 2 MB each) and the house-style notes its checks show
  const tpl = d.templates || {}, tplFiles = {};
  const tplBox = (key, label, accept) => { const cur = tpl[key] || {}; const inp = h('input', {type: 'file', accept, 'aria-label': label}); const txt = h('div', {class: 'small muted'}, cur.set ? `${cur.name || 'a template'} is set.` : 'None yet — the RELAY template is used.');
    inp.onchange = () => { const f = inp.files[0]; if (!f) return; if (f.size > 2 * 1024 * 1024) { notify('Keep the template under 2 MB.', 'err'); inp.value = ''; return; } const r = new FileReader(); r.onload = () => { tplFiles[key] = r.result; tplFiles[key + '_name'] = f.name; txt.textContent = `${f.name} · ${size(f.size)} (saved with the form)`; }; r.readAsDataURL(f); };
    const remove = cur.set ? h('button', {class: 'btn sm', type: 'button', onclick: () => { tplFiles[key] = ''; tplFiles[key + '_name'] = ''; txt.textContent = 'Removed (saved with the form).'; }}, 'Remove') : null;
    return h('div', {}, h('label', {class: 'f'}, label), h('div', {class: 'row'}, inp, remove), txt); };
  const house = h('textarea', {rows: 3, placeholder: 'e.g. “Titles in sentence case; no exclamation marks; say ‘client’, not ‘customer’; numbers with the Indian grouping”'}, tpl.house_style || '');
  const logos = {}, logoBox = (key, label) => { const inp = h('input', {type: 'file', accept: '.svg,.png,image/svg+xml,image/png', 'aria-label': label}); const cur = h('div', {class: 'small muted'}, s[key] ? 'A logo is set.' : 'None yet.');
    inp.onchange = () => { const f = inp.files[0]; if (!f) return; if (f.size > 200000) { notify('Keep the logo under 200 KB.', 'err'); inp.value = ''; return; } const r = new FileReader(); r.onload = () => { logos[key] = r.result; cur.textContent = `${f.name} · ${size(f.size)} (saved with the form)`; }; r.readAsDataURL(f); };
    const remove = s[key] ? h('button', {class: 'btn sm', type: 'button', onclick: () => { logos[key] = ''; cur.textContent = 'Removed (saved with the form).'; }}, 'Remove') : null;
    return h('div', {}, h('label', {class: 'f'}, label), h('div', {class: 'row'}, inp, remove), cur); };
  const save = h('button', {class: 'btn primary', onclick: async () => {
    const body = {partner: partner.checked, name: name.value, full: full.value, tagline: tagline.value, mark: mark.value, color: color.value, accent: accent.value, sender: sender.value, contact: contact.value,
      edition: edition.value, hourly_rate: Number(rate.value || 0), currency: currency.value, usd_rate: Number(fx.value || 1), house_style: house.value, ...logos, ...tplFiles};
    try { const r = await api('/api/admin/branding', {method: 'PUT', json: body}); S.brand = r.brand; if (S.registry) { S.registry.brand = r.brand; } await loadRegistry(); applyBrand(); notify('Branding saved', 'ok'); reAdmin(); }
    catch (e) { notify(e.message, 'err'); }
  }}, 'Save branding');
  const preview = h('div', {class: 'card', style: 'margin:0'}, h('h3', {}, 'How it shows'), h('div', {class: 'small muted', style: 'margin-bottom:10px'}, 'The rail, the sign-in page, outgoing mail and PDF covers use this.'),
    h('div', {class: 'row', style: 'gap:14px;align-items:center'}, b.partner ? [b.logo_light ? h('img', {src: b.logo_light, alt: '', style: 'height:36px'}) : partnerMark(b), h('div', {}, h('b', {}, b.full), h('div', {class: 'small muted'}, b.tagline))] : svgEl(RELAY_LOGO, 'relaylogo')),
    h('div', {class: 'powered', style: 'margin-top:14px;padding:10px 0 0;border-top:1px solid var(--line)'}, b.partner ? [markEl(), h('span', {}, 'Powered by ', h('b', {}, 'PASDACS Relay'))] : h('span', {class: 'faint'}, 'RELAY by PASDACS')),
    h('p', {class: 'small muted', style: 'margin:12px 0 0'}, 'Partners carry their own name, mark, colours and logos everywhere; the “Powered by PASDACS Relay” line stays. The platform’s own look cannot be renamed.'));
  return h('div', {class: 'grid2'},
    h('div', {class: 'card formcard', style: 'margin:0'},
      h('h3', {}, 'White-label'),
      h('label', {class: 'chk', style: 'margin:8px 0 4px'}, partner, ' This install is run by a service partner under its own brand'),
      h('div', {class: 'opts'}, fld('Short name', name), fld('Full name', full)),
      h('div', {class: 'opts'}, fld('Tagline', tagline), fld('Mark (up to 3 letters)', mark)),
      h('div', {class: 'opts'}, fld('Mark colour', color), fld('Accent', accent, 'Buttons, links and progress across the app.')),
      h('div', {class: 'opts'}, logoBox('logo_light', 'Logo for light mode (SVG or PNG)'), logoBox('logo_dark', 'Logo for dark mode')),
      fld('Sender name on mail', sender),
      fld('Contact address (shown on the sign-in page)', contact),
      h('h3', {style: 'margin-top:22px'}, 'Edition and value'),
      fld('Edition', edition, 'Decides which modules are in the plan; the catalogue, menu and Home follow it.'),
      h('div', {class: 'opts'}, fld('Hourly rate of the work agents replace', h('div', {class: 'row'}, currency, rate), 'Home shows net value = agent hours × rate − AI cost once a rate is set.'),
        fld('Exchange rate: one US dollar in your currency', fx, 'AI cost is recorded in US dollars.')),
      h('h3', {style: 'margin-top:22px'}, 'Studio templates and house style'),
      h('div', {class: 'opts'}, tplBox('template_pptx', 'PowerPoint template (.pptx or .potx)', '.pptx,.potx'), tplBox('template_docx', 'Word template (.docx or .dotx)', '.docx,.dotx')),
      fld('House style', house, 'Shown with every check report in the studio; the built-in rules cover fonts, title lengths, British spelling, contrast and alt text.'),
      h('div', {class: 'row', style: 'margin-top:16px'}, save)),
    preview);
}
