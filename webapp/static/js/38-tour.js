/* ---------------- D2D Relay: the first-time tour (#/welcome, 2026-11-12). Shown once to someone new when they open the
   app's front page; finished or skipped at any step it is not shown on its own again (POST /api/me/tour), and "Take the
   tour" in the organisation menu opens it again. Steps: welcome; the brand (owners: Branding, drawn inside); light or
   dark (or the device's own setting); the basics (how a dashboard is made, credits, help). A new organisation's main
   owner sets it up here (POST /api/org/setup; #/setup, the old address, opens the brand step). ---------------- */
const TOUR = {step: 0};
const TOUR_NAMES = {welcome: 'Welcome', brand: 'Your brand', look: 'Light or dark', basics: 'The basics'};
const TOUR_LANDING = ['', '#', '#/', '#/d2d', '#/new'];        // a link to anything else (a shared dashboard) opens as asked
const tourSteps = () => ['welcome', ...(ORG().id && ORG().is_owner ? ['brand'] : []), 'look', 'basics'];
/* after /api/me: someone new, or a new organisation's main owner, opening the front page goes to the tour */
function tourAfterMe(me) {
  const o = (me && me.org) || {};
  if (me && (me.tour || (o.setup_needed && o.is_owner)) && TOUR_LANDING.includes(location.hash)) location.hash = '#/welcome';
}

function renderTour() {
  const o = ORG(), steps = tourSteps();
  let i = Math.min(TOUR.step || 0, steps.length - 1);
  if (location.hash === '#/setup') { i = Math.max(0, steps.indexOf('brand')); history.replaceState(null, '', '#/welcome'); }
  document.title = 'Welcome - D2D Relay';
  const page = h('div', {class: 'page tour'});
  $('#main').replaceChildren(page);

  const leave = async (how, then, btn) => {        // finished, or skipped at this step
    if (btn) btn.disabled = true;
    try {
      await api('/api/me/tour', {json: {step: how}});
      if (o.setup_needed && o.is_owner) { await api('/api/org/setup', {method: 'POST'}); S.me.org.setup_needed = false; }
    } catch (e) { if (btn) btn.disabled = false; return notify(e.message, 'err'); }
    S.me.tour = false;
    TOUR.step = 0;
    if (how !== 'done') notify('Take the tour again any time: click your organisation\'s name at the top, then Take the tour.', 'ok');
    location.hash = then || '#/d2d';
  };

  const tile = (ic, title, text) => h('div', {class: 'tile'}, icon(ic), h('h3', {}, title), h('div', {class: 'muted small'}, text));
  const welcome = () => [
    h('p', {class: 'muted lead'}, 'Two minutes to get set up. Skip at any step; everything here can be changed later.'),
    h('div', {class: 'tiles3'},
      tile('chart', 'Dashboards', 'Describe what you need and add your data. Relay plans it with you, shows a prototype, then gives you a Power BI file (.pbix).'),
      tile('spark', 'Ask Relay', 'Ask a question about your data in plain words and get a number, a table or a chart back.'),
      tile('palette', 'Your brand', o.is_owner ? 'Your logo and colours go into every report your organisation makes. Next step.'
        : `${o.owner ? o.owner.name : 'The owner'} sets the colours every report in ${o.name || 'your organisation'} uses.`)),
    o.id ? h('div', {class: 'card'}, h('h3', {}, o.is_owner ? `${o.name} is ready` : `You joined ${o.name}`),
      h('dl', {class: 'kv small'},
        h('dt', {}, 'Owner'), h('dd', {}, o.is_owner ? `you (${(S.me || {}).email || ''})` : (o.owner ? o.owner.name : '-')),
        h('dt', {}, 'Who joins'), h('dd', {}, `everyone who signs in with an @${o.domain} address`),
        h('dt', {}, 'Credits'), h('dd', {}, o.credits ? `${credits(o.credits)} left`
          : isStart(o.pending_request) ? `none yet: PASDACS is reviewing ${o.name} and adds ${credits(o.pending_request.credits)} to start when it approves (you get an email)`
          : 'none yet: ask for them with Request credits'))) : null];

  const brand = () => {
    const box = h('div');
    setTimeout(() => renderBranding({into: box, route: '#/welcome'}), 0);
    return [h('p', {class: 'muted lead'}, `Add your logo and a few words about your brand. Relay makes report palettes from them; pick one and every new dashboard in ${o.name} uses it. Or skip this and set it later under Branding.`), box];
  };

  const look = () => {
    const now = themeChoice();
    const sample = (bg, ink, bar) => h('div', {style: `background:${bg};padding:10px;display:flex;flex-direction:column;gap:6px`},
      h('i', {style: `display:block;height:8px;width:60%;border-radius:4px;background:${ink};opacity:.85`}),
      h('i', {style: `display:block;height:8px;width:40%;border-radius:4px;background:${ink};opacity:.45`}),
      h('i', {style: `display:block;height:18px;width:30%;border-radius:4px;background:${bar};margin-top:auto`}));
    const opts = [['light', 'Light', 'Dark text on white.', [sample('#FFFFFF', '#111111', '#007A57')]],
      ['dark', 'Dark', 'Light text on black, easier at night.', [sample('#0A0A0A', '#F5F5F5', '#00C48C')]],
      ['system', 'Match my device', 'Follows your computer or phone, light by day and dark at night if it is set so.',
        [sample('#FFFFFF', '#111111', '#007A57'), sample('#0A0A0A', '#F5F5F5', '#00C48C')]]];
    const group = h('div', {class: 'looks', role: 'radiogroup', 'aria-label': 'How D2D Relay looks'});
    const draw = pick => group.replaceChildren(...opts.map(([id, name, text, samples]) =>
      h('button', {class: 'look', type: 'button', role: 'radio', 'aria-checked': String(pick === id),
        onclick: () => { setTheme(id); draw(id); }},
        h('div', {class: 'sample'}, samples), h('div', {class: 'row', style: 'gap:6px'}, h('b', {}, name),
          pick === id ? h('span', {class: 'tag ok'}, icon('check'), 'Chosen') : null),
        h('div', {class: 'muted small'}, text))));
    draw(now);
    return [h('p', {class: 'muted lead'}, 'How D2D Relay looks on this device. Change it any time with the sun or moon button at the top.'), group,
      h('p', {class: 'muted small'}, 'Your reports keep their own colours: they come from your brand, not from this setting.')];
  };

  const basics = () => [
    h('h3', {style: 'margin:4px 0 0'}, 'How a dashboard is made'),
    h('ol', {class: 'howto'},
      h('li', {}, h('div', {}, h('b', {}, 'Describe it and add your data. '), 'A CSV file, or demo data Relay makes for you.')),
      h('li', {}, h('div', {}, h('b', {}, 'Check the plan. '), 'The KPIs and how each one is worked out, before anything is built.')),
      h('li', {}, h('div', {}, h('b', {}, 'Look at the prototype. '), 'Ask for changes in your own words until it is right.')),
      h('li', {}, h('div', {}, h('b', {}, 'Download the Power BI file. '), 'A .pbix that opens in Power BI Desktop, with its data.'))),
    o.id ? h('div', {class: 'card'}, h('h3', {}, 'Credits'),
      h('p', {class: 'small', style: 'margin:4px 0'}, `${o.name} has ${credits(o.credits)}: ${costLine()}.`),
      o.pending_request ? h('p', {class: 'small muted', style: 'margin:4px 0'}, isStart(o.pending_request)
        ? `PASDACS is reviewing ${o.name}: you get an email when your starting credits are added.`
        : `${credits(o.pending_request.credits)} asked for, waiting for PASDACS.`)
        : h('button', {class: 'btn sm', type: 'button', onclick: () => requestDialog()}, icon('plus'), 'Request credits')) : null,
    h('div', {class: 'card'}, h('h3', {}, 'Moving from another BI tool?'),
      h('p', {class: 'small muted', style: 'margin:4px 0'}, 'Migration D2D moves dashboards between Cognos, Qlik, Looker, Tableau, Power BI and more. Ask PASDACS to switch it on for you.'),
      h('button', {class: 'btn sm', type: 'button', onclick: e => leave('done', '#/migration', e.currentTarget)}, icon('swap'), 'About Migration D2D')),
    h('p', {class: 'small muted'}, 'Questions: ', h('a', {href: 'mailto:info@pasdacs.com'}, 'info@pasdacs.com'), '. How your data is handled: ',
      h('a', {href: '/privacy.html', target: '_blank', rel: 'noopener'}, 'privacy notice'), '.')];

  const draw = () => {
    const s = steps[i], last = i === steps.length - 1;
    TOUR.step = i;
    const go = k => { i = k; draw(); window.scrollTo(0, 0); };
    const skip = h('button', {class: 'btn ghost', type: 'button', onclick: () => leave(s, '#/d2d', skip)}, last ? 'Close' : 'Skip the tour');
    const start = h('button', {class: 'btn primary', type: 'button', onclick: () => leave('done', '#/new', start)}, icon('plus'), 'Start a dashboard');
    const done = h('button', {class: 'btn', type: 'button', onclick: () => leave('done', '#/d2d', done)}, 'Go to Dashboards');
    page.replaceChildren(
      h('div', {class: 'eyebrow'}, 'Welcome to D2D Relay'),
      h('h1', {}, s === 'welcome' ? 'A quick tour' : TOUR_NAMES[s]),
      h('div', {class: 'steps', 'aria-label': `Step ${i + 1} of ${steps.length}`}, steps.map((x, k) =>
        h('div', {class: 'step ' + (k < i ? 'done' : k === i ? 'cur' : '')}, h('b', {}, k < i ? '✓' : String(k + 1)), h('span', {}, TOUR_NAMES[x])))),
      h('div', {class: 'tourbody'}, ...({welcome, brand, look, basics}[s]())),
      h('div', {class: 'row tourfoot'}, last ? null : skip, h('span', {class: 'spacer'}),
        i > 0 ? h('button', {class: 'btn ghost', type: 'button', onclick: () => go(i - 1)}, 'Back') : null,
        last ? done : null,
        last ? start : h('button', {class: 'btn primary', type: 'button', onclick: () => go(i + 1)}, s === 'brand' ? 'Next: light or dark' : 'Next')));
  };
  draw();
}
