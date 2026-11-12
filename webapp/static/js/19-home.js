/* ---------------- Home (P9): the platform's insight dashboard on real records (GET /api/home) ---------------- */
const NS_SVG = 'http://www.w3.org/2000/svg';
const sv = (t, a, txt) => { const e = document.createElementNS(NS_SVG, t); for (const k in a) e.setAttribute(k, a[k]); if (txt != null) e.textContent = txt; return e; };
// a label in a tooltip is text (a dashboard's or a person's name can hold anything), never markup
const tipEsc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
function tipOn(e, html) { const t = $('#tip'); t.innerHTML = html; t.hidden = false; const r = t.getBoundingClientRect(); t.style.left = Math.min(e.clientX + 14, innerWidth - r.width - 8) + 'px'; t.style.top = Math.max(4, e.clientY - r.height - 10) + 'px'; }
function tipOff() { $('#tip').hidden = true; }
const fmtN = (n, d = 1) => n == null ? '-' : Number(n).toLocaleString(undefined, {maximumFractionDigits: d});
// Column chart (one series, the last column labelled; hover for every value)
function colChart(rows, {height = 190, unit = '', fmtv = v => fmtN(v), label = 'chart'} = {}) {
  const W = 560, H = height, padL = 40, padB = 26, padT = 14;
  const max = Math.max(1e-9, ...rows.map(r => r[1])) * 1.15;
  const step = (W - padL) / rows.length, bw = Math.min(34, step * .5);
  const svg = sv('svg', {viewBox: `0 0 ${W} ${H}`, class: 'chart', role: 'img', 'aria-label': label});
  [0, .5, 1].forEach(f => { const y = padT + (H - padB - padT) * (1 - f); svg.append(sv('line', {x1: padL, x2: W, y1: y, y2: y, class: 'grid'})); svg.append(sv('text', {x: padL - 6, y: y + 4, 'text-anchor': 'end', class: 'ax'}, fmtv(max * f))); });
  rows.forEach(([l, v], i) => {
    const x = padL + step * i + (step - bw) / 2, hgt = (H - padB - padT) * v / max, y = H - padB - hgt;
    const last = i === rows.length - 1;
    svg.append(sv('rect', {x, y, width: bw, height: Math.max(0, hgt), rx: 3, class: 'mark' + (last ? '' : ' soft')}));
    if (last) svg.append(sv('text', {x: x + bw / 2, y: y - 6, 'text-anchor': 'middle', class: 'lbl'}, fmtv(v) + unit));
    svg.append(sv('text', {x: x + bw / 2, y: H - 8, 'text-anchor': 'middle', class: 'ax'}, l));
    const hit = sv('rect', {x: padL + step * i, y: padT, width: step, height: H - padB - padT, fill: 'transparent'});
    hit.addEventListener('mousemove', e => tipOn(e, `<b>${tipEsc(l)}</b><br>${tipEsc(fmtv(v) + unit)}`)); hit.addEventListener('mouseleave', tipOff);
    svg.append(hit);
  });
  return svg;
}
// Line chart with a crosshair
function lineChart(rows, {height = 160, min, max, fmtv = v => fmtN(v), unit = '', label = 'chart'} = {}) {
  const W = 360, H = height, padL = 38, padB = 24, padT = 14;
  if (rows.length < 2) return h('div', {class: 'muted small', style: 'padding:24px 0'}, 'Not enough months yet.');
  const vals = rows.map(r => r[1]);
  let lo = min ?? Math.min(...vals), hi = max ?? Math.max(...vals); if (hi === lo) { hi = lo + 1; lo = lo - 1; }
  const X = i => padL + (W - padL - 12) * i / (rows.length - 1), Y = v => padT + (H - padB - padT) * (1 - (v - lo) / (hi - lo));
  const svg = sv('svg', {viewBox: `0 0 ${W} ${H}`, class: 'chart', role: 'img', 'aria-label': label});
  [lo, (lo + hi) / 2, hi].forEach(v => { svg.append(sv('line', {x1: padL, x2: W, y1: Y(v), y2: Y(v), class: 'grid'})); svg.append(sv('text', {x: padL - 6, y: Y(v) + 4, 'text-anchor': 'end', class: 'ax'}, fmtv(v))); });
  svg.append(sv('path', {d: rows.map((r, i) => (i ? 'L' : 'M') + X(i) + ' ' + Y(r[1])).join(' '), class: 'line'}));
  rows.forEach((r, i) => { if (i % 2 === 0 || i === rows.length - 1) svg.append(sv('text', {x: X(i), y: H - 6, 'text-anchor': 'middle', class: 'ax'}, r[0])); });
  const lastI = rows.length - 1;
  svg.append(sv('circle', {cx: X(lastI), cy: Y(rows[lastI][1]), r: 4.5, class: 'dotm'}));
  svg.append(sv('text', {x: X(lastI) - 6, y: Y(rows[lastI][1]) - 9, 'text-anchor': 'end', class: 'lbl'}, fmtv(rows[lastI][1]) + unit));
  const cross = sv('line', {y1: padT, y2: H - padB, class: 'cross', style: 'display:none'}), dot = sv('circle', {r: 4.5, class: 'dotm', style: 'display:none'});
  svg.append(cross, dot);
  const hit = sv('rect', {x: padL, y: padT, width: W - padL, height: H - padB - padT, fill: 'transparent'});
  hit.addEventListener('mousemove', e => { const b = svg.getBoundingClientRect(); const xv = (e.clientX - b.left) / b.width * W; const i = Math.max(0, Math.min(lastI, Math.round((xv - padL) / (W - padL - 12) * lastI)));
    cross.setAttribute('x1', X(i)); cross.setAttribute('x2', X(i)); cross.style.display = ''; dot.setAttribute('cx', X(i)); dot.setAttribute('cy', Y(rows[i][1])); dot.style.display = ''; tipOn(e, `<b>${tipEsc(rows[i][0])}</b><br>${tipEsc(fmtv(rows[i][1]) + unit)}`); });
  hit.addEventListener('mouseleave', () => { cross.style.display = 'none'; dot.style.display = 'none'; tipOff(); });
  svg.append(hit);
  return svg;
}
const asTable = (cols, rows) => h('details', {class: 'astable'}, h('summary', {}, 'Show as a table'),
  h('table', {class: 'utable', style: 'margin-top:6px'}, h('tr', {}, cols.map((c, i) => h('th', {class: i ? '' : 'l'}, c))), rows.map(r => h('tr', {}, r.map((v, i) => h('td', {class: i ? 'n' : ''}, v))))));
const bar2 = (label, value, max, href, shown) => h('a', {class: 'bar2', href}, h('span', {class: 'bl'}, label), h('div', {class: 'bt'}, h('div', {class: 'bf', style: `width:${max ? Math.min(100, value * 100 / max) : 0}%`})), h('span', {class: 'bv'}, shown || fmtN(value, 0)));
function kpiTile(label, value, sub, opts = {}) {
  return h(opts.href ? 'a' : 'div', {class: 'card kpi', href: opts.href || null, 'aria-label': opts.href ? `${label}: ${value}` : null},
    h('div', {class: 'kl'}, label), h('div', {class: 'kv'}, value), opts.delta ? h('div', {class: 'kd ' + (opts.good ? 'good' : opts.bad ? 'bad' : '')}, opts.delta) : null, h('div', {class: 'ks'}, sub));
}
const PERIOD_LABEL = {'7d': '7 days', '30d': '30 days', '6m': '6 months'};

/* ---------------- Start new work: what people come to Relay for, then where (Home and the + button) ---------------- */
const INTENTS = [
  {id: 'discover', work: 'assess', icon: 'search', title: 'Discover what you have', line: 'See what runs today, how healthy it is and what changing it would take. Read-only.'},
  {id: 'document', work: null, icon: 'route', title: 'Document a process', line: 'Process maps, SOPs, requirements and RACI from interviews, recordings or old documents.'},
  {id: 'develop', work: 'develop', icon: 'spark', title: 'Build something new', line: 'Describe it. The agent shapes it with you, builds it in small steps and proves it.'},
  {id: 'migrate', work: 'migrate', icon: 'swap', title: 'Move to a new platform', line: 'Reports, data, bots or flows moved across, with old and new proven side by side.'},
  {id: 'fix', work: 'change', icon: 'heart', title: 'Fix a problem or make a change', line: 'A bug, a failure or a change request: the cause found, fixed on a copy, released after your OK.'},
];
// Document a process: the ways in, by what the person has in hand (module, work type, what it is, what it starts from)
const DOC_WAYS = [
  ['processdocs', 'develop', 'Map a process and write its SOP', 'From interviews, a screen recording or system logs'],
  ['processdocs', 'migrate', 'Bring old process documents up to date', 'Visio, Word or slides, turned into BPMN maps and your SOP template'],
  ['processdocs', 'assess', 'Check documents against the real work', 'Where the documents and what people actually do have drifted apart'],
  ['processdocs', 'change', 'Update a process document', 'After a system, a bot or a rule changed'],
  ['brd', 'develop', 'Write the requirements (a BRD)', 'From workshop notes, call recordings and whiteboard photos'],
  ['raci', 'develop', 'Agree who does what (RACI)', 'Who does, approves and is told, step by step'],
  ['mining', 'assess', 'Find how the work really runs', 'From the event logs in your ERP or ticketing system'],
  ['testdocs', 'develop', 'Write test plans and UAT scripts', 'From the requirements and their acceptance criteria'],
];
// Fix a problem: the screens made for it come before the modules
const FIX_WAYS = [
  ['#/heal', 'heart', 'Something failed', 'A refresh, pipeline, flow or bot: diagnosed from its logs and fixed on a copy'],
  ['#/sdlc', 'code', 'Change the code in a repository', 'A change request becomes a tested pull request'],
  ['#/servicedesk', 'bell', 'Work through service desk tickets', 'Summarised, duplicates grouped, routed to an agent or a person'],
];
function intentHref(m, w, packs) {
  if (m.id === 'bi' && w === 'develop') return '#/new';
  if (packs.some(p => p.module === m.id && p.on && (p.work || []).includes(w))) return `#/m/${m.id}/${w}?new=1`;      // the module's own New work form opens on that work type
  return (m.live || {})[w] || `#/m/${m.id}/${w}`;
}
async function startChooser(intent) {
  if (!S.registry && typeof loadRegistry === 'function') await loadRegistry();
  const reg = S.registry;
  if (!reg) { notify('The list of modules could not be loaded. Try again in a moment.', 'err'); return; }
  const packs = typeof wbPacks === 'function' ? await wbPacks() : [];
  const usable = m => !['off', 'locked'].includes(m.state);
  const body = h('div', {class: 'mbody'});
  let mm = null;
  const go = href => { if (mm) mm.remove(); location.hash = href.replace(/^#/, ''); };
  const row = (href, ic, name, sub, extra) => h('a', {class: 'ichoice', href, onclick: e => { e.preventDefault(); go(href); }},
    h('span', {class: 'iico'}, icon(ic)), h('span', {class: 'grow'}, h('b', {}, name), h('small', {}, sub), extra ? h('small', {class: 'faint'}, extra) : null), icon('chevr'));
  const footer = () => h('p', {class: 'small muted', style: 'margin:16px 0 0'}, 'Not sure where it belongs? ', h('a', {href: '#/start', onclick: e => { e.preventDefault(); go('#/start'); }}, 'Describe it and attach anything'), ` - ${brandName()} reads it and suggests where it goes.`);
  const pickIntent = () => {
    body.replaceChildren(h('p', {class: 'small muted', style: 'margin-top:0'}, `Pick the kind of work. Next you choose the system or area, and ${brandName()} takes you to the right place to start.`),
      h('div', {class: 'ichoices'}, INTENTS.map(it => h('button', {class: 'ichoice', type: 'button', onclick: () => pickArea(it)},
        h('span', {class: 'iico'}, icon(it.icon)), h('span', {class: 'grow'}, h('b', {}, it.title), h('small', {}, it.line)), icon('chevr')))),
      h('p', {class: 'small muted', style: 'margin:16px 0 0'}, 'Or ', h('a', {href: '#/new', onclick: e => { e.preventDefault(); go('#/new'); }}, 'start a dashboard'), ', or ',
        h('a', {href: '#/start', onclick: e => { e.preventDefault(); go('#/start'); }}, 'describe an idea and attach anything'), '.'));
  };
  const pickArea = it => {
    const back = intent ? null : h('button', {class: 'btn sm ghost', type: 'button', onclick: pickIntent}, icon('chevl'), 'Other kinds of work');
    const q = h('input', {type: 'search', placeholder: 'Find a system or area, e.g. SAP, Power BI, invoices...', 'aria-label': 'Find a system or area'});
    const list = h('div', {});
    const draw = () => {
      const s = q.value.trim().toLowerCase();
      const hit = (...t) => !s || t.join(' ').toLowerCase().includes(s);
      const parts = [];
      if (it.id === 'document') {
        const ways = DOC_WAYS.map(([mid, w, name, sub]) => [reg.modules.find(m => m.id === mid), w, name, sub]).filter(([m, w, name, sub]) => m && usable(m) && (m.live || {})[w] && hit(name, sub, m.name));
        if (ways.length) parts.push(h('div', {class: 'ichoices'}, ways.map(([m, w, name, sub]) => row(intentHref(m, w, packs), m.icon, name, sub, m.name))));
      } else {
        if (it.id === 'fix') {
          const ways = FIX_WAYS.filter(([href, , name, sub]) => hit(name, sub) && reg.modules.some(m => m.route === href && usable(m)));
          if (ways.length) parts.push(h('div', {class: 'ichead'}, 'Made for this'), h('div', {class: 'ichoices'}, ways.map(([href, ic, name, sub]) => row(href, ic, name, sub))));
        }
        for (const p of reg.pillars) {
          const ms = reg.modules.filter(m => m.pl === p.id && usable(m) && (m.live || {})[it.work] && hit(m.name, m.sub, (m.platforms || []).join(' ')));
          if (ms.length) parts.push(h('div', {class: 'ichead'}, p.name), h('div', {class: 'ichoices'}, ms.map(m => row(intentHref(m, it.work, packs), m.icon, m.name, m.sub, (m.platforms || []).slice(0, 4).join(' - ')))));
        }
        if (it.id === 'discover') {
          const est = reg.modules.find(m => m.id === 'assess' && usable(m));
          if (est && hit(est.name, est.sub, 'estimate size price')) parts.push(h('div', {class: 'ichead'}, 'Size and price it'), h('div', {class: 'ichoices'}, row(est.route, est.icon, est.name, 'Read the estate, size it and estimate the effort and cost per wave')));
        }
      }
      list.replaceChildren(...(parts.length ? parts : [h('div', {class: 'muted small', style: 'padding:12px 0'}, `Nothing matches "${q.value.trim()}". `, h('a', {href: '#/start', onclick: e => { e.preventDefault(); go('#/start'); }}, 'Describe it instead'), ` and ${brandName()} will suggest where it goes.`)]));
    };
    q.oninput = draw;
    body.replaceChildren(...[back ? h('div', {style: 'margin-bottom:8px'}, back) : null, h('p', {style: 'margin:0 0 10px'}, h('b', {}, it.title + '. '), h('span', {class: 'muted'}, it.line)),
      it.id === 'document' ? null : q, list, footer()].filter(Boolean));          // replaceChildren prints a null as "null"
    draw();
    setTimeout(() => (it.id === 'document' ? body.querySelector('.ichoice') : q).focus(), 40);
  };
  const first = intent && INTENTS.find(x => x.id === intent);
  mm = modal('Start new work', body);
  mm.classList.add('chooser');
  if (first) pickArea(first); else pickIntent();
}
function intentStrip() {
  return h('section', {class: 'intents', 'aria-labelledby': 'intents-h'},
    h('div', {class: 'section-title', style: 'margin-top:0'}, h('h2', {id: 'intents-h'}, 'What do you want to do?'), h('span', {class: 'hint'}, h('a', {href: '#/new'}, 'New dashboard'), ' - ', h('a', {href: '#/modules'}, 'All modules'))),
    h('div', {class: 'intent-grid'}, INTENTS.map(it => h('button', {class: 'intent', type: 'button', 'aria-haspopup': 'dialog', onclick: () => startChooser(it.id)},
      h('span', {class: 'iico'}, icon(it.icon)), h('b', {}, it.title), h('span', {class: 'il'}, it.line))),
      h('a', {class: 'intent', href: '#/start'}, h('span', {class: 'iico'}, icon('clip')), h('b', {}, 'Start from an idea'),
        h('span', {class: 'il'}, `Not sure where it fits? Write it, say it or show it, attach anything, and ${brandName()} works out where it goes.`))));
}

async function renderHome() {
  const period = S.period || '30d', main = $('#main');
  if (!$('#homepage')) main.replaceChildren(skel('page'));
  let d, sd = null, ob = null, su = null, hl = null, sl = null;
  try { [d, sd, ob, su, hl, sl] = await Promise.all([api('/api/home?period=' + period), api('/api/servicedesk/summary').catch(() => null), api('/api/observe/summary').catch(() => null), api('/api/studio/summary').catch(() => null), api('/api/heal/summary').catch(() => null), api('/api/sdlc/summary').catch(() => null)]); }   // P12 / P14 / P11 / P16: the Service desk, Data health, Studio, Self-healing and Changes in flight cards never fail the page
  catch (e) { main.replaceChildren(h('div', {class: 'page'}, h('div', {class: 'note err'}, e.message))); return; }
  if (!isHome()) return;
  const b = S.brand || {}, me = S.me || {}, reg = S.registry, k = d.kpis, viewer = me.builder === false;
  const first = (me.name || '').split(/\s+/)[0], hour = new Date().getHours();
  const greet = hour < 12 ? 'Good morning' : hour < 17 ? 'Good afternoon' : 'Good evening';
  const pl = PERIOD_LABEL[period];
  const promise = viewer ? 'Your reports, answers and alerts - and how fresh and proven they are.'
    : k.runs ? `Agents did ${fmtN(k.agent_hours)} hours of work in the last ${pl}: ${k.runs} runs, ${k.delivered} dashboard${k.delivered === 1 ? '' : 's'} published after every review gate.`
    : `No agent runs in the last ${pl} yet. Start a dashboard and the numbers below fill in from real work.`;
  const delta = (cur, prev, unit) => prev == null || cur == null || (!prev && !cur) ? {} : {delta: `${cur - prev >= 0 ? '+' : ''}${fmtN(cur - prev)}${unit} vs previous ${pl}`, good: cur - prev > 0, bad: cur - prev < 0};
  const kpis = h('div', {class: 'g5'},
    kpiTile('Hours of agent work', fmtN(k.agent_hours), 'run time of plan, build, revise and fix rounds', {href: '#/d2d', ...delta(k.agent_hours, k.agent_hours_prev, ' h')}),
    kpiTile('Right first time', k.rft == null ? '-' : fmtN(k.rft) + ' %', k.runs ? `${k.runs} runs - ${k.fix_rounds} fix round${k.fix_rounds === 1 ? '' : 's'}` : 'runs that needed no fix round', {href: '#/d2d', ...delta(k.rft, k.rft_prev, ' pts')}),
    kpiTile('Delivered & proven', String(k.delivered), 'published after every review gate', {href: '#/d2d'}),
    kpiTile('Waiting for a person', String(k.waiting), k.waiting ? `oldest ${fmtN(k.waiting_oldest_h)} h - median ${fmtN(k.waiting_median_h)} h` : 'nothing waiting for you', {href: '#/d2d'}),
    k.net_value != null
      ? kpiTile('Net value', `${b.currency || ''}${fmtN(k.net_value, 0)}`, `hours × rate - AI cost (${usd(k.ai_cost_usd)})`, {href: me.admin ? '#/admin/costs' : null})
      : kpiTile('AI cost', usd(k.ai_cost_usd), me.admin ? 'set an hourly rate under Admin > Branding to see net value' : 'models and warehouse queries', {href: me.admin ? '#/admin/costs' : null}));
  const hours = d.months.map(m => [m.month, m.hours]), cost = d.months.map(m => [m.month, m.cost_usd]), rft = d.months.filter(m => m.rft != null).map(m => [m.month, m.rft]);
  const now = d.now, inf = d.inflight, maxMod = Math.max(1, ...inf.modules.map(m => m.n)), busy = inf.modules.filter(m => m.n || m.running || m.paused);
  const ag = (S.health || {}).agent || {};
  main.replaceChildren(h('div', {class: 'page', id: 'homepage'},
    h('section', {class: 'hero'}, h('div', {class: 'row', style: 'align-items:flex-end'},
      h('div', {style: 'flex:1;min-width:280px'}, h('div', {class: 'eyebrow'}, (b.partner ? b.full : 'RELAY by PASDACS') + ' - Data & analytics practice'),
        h('h1', {}, greet + (first ? ', ' + first : '')), h('div', {class: 'promise'}, promise)),
      h('div', {class: 'row', style: 'gap:10px'},
        h('div', {class: 'segbtn', role: 'group', 'aria-label': 'Period'}, Object.entries(PERIOD_LABEL).map(([kk, l]) => h('button', {class: period === kk ? 'on' : '', 'aria-pressed': String(period === kk), onclick: () => { S.period = kk; renderHome(); }}, l))),
        viewer ? null : h('button', {class: 'btn primary', type: 'button', 'aria-haspopup': 'dialog', onclick: () => startChooser()}, icon('plus'), 'Start new work')))),
    viewer ? null : intentStrip(),
    kpis,
    h('div', {class: 'dash-a', style: 'margin-top:16px'},
      h('div', {class: 'card', style: 'margin:0'}, h('div', {class: 'card-head'}, h('h3', {}, 'Hours of work done by agents'), h('span', {class: 'sp'}), h('span', {class: 'small muted'}, 'per month, checked by people')),
        colChart(hours, {label: `Agent hours per month: ${hours.map(r => `${r[0]} ${fmtN(r[1])}`).join(', ')}`, unit: ' h'}), asTable(['Month', 'Hours'], hours.map(r => [r[0], fmtN(r[1])]))),
      h('div', {class: 'card', style: 'margin:0'}, h('div', {class: 'card-head'}, h('h3', {}, 'AI cost per month'), h('span', {class: 'sp'}), h('span', {class: 'small muted'}, 'models and warehouse queries')),
        colChart(cost, {label: `AI cost per month: ${cost.map(r => `${r[0]} ${usd(r[1])}`).join(', ')}`, fmtv: v => usd(v)}), asTable(['Month', 'Cost'], cost.map(r => [r[0], usd(r[1])])))),
    h('div', {class: 'g3', style: 'margin-top:16px'},
      h('div', {class: 'card', style: 'margin:0'}, h('div', {class: 'card-head'}, h('h3', {}, 'Right first time'), h('span', {class: 'sp'}), h('span', {class: 'small muted'}, 'runs with no fix round')),
        lineChart(rft, {min: 0, max: 100, unit: ' %', label: `Right first time by month: ${rft.map(r => `${r[0]} ${fmtN(r[1])} %`).join(', ')}`}),
        h('div', {class: 'small muted', style: 'margin-top:6px'}, 'A fix round is the agent repairing what a review gate or the DAX engine rejected.')),
      h('div', {class: 'card', style: 'margin:0'}, h('div', {class: 'card-head'}, h('h3', {}, 'Work in flight'), h('span', {class: 'sp'}), h('span', {class: 'small muted'}, `${inf.by_status.running} running - ${inf.by_status.waiting} waiting`)),
        busy.length ? h('div', {class: 'bars'}, busy.map(m => bar2(m.name, m.n, maxMod, m.route, m.unit ? `${fmtN(m.n, 0)} ${m.unit}` : (m.running ? `${fmtN(m.n, 0)} - ${m.running} running` : m.paused ? `${fmtN(m.n, 0)} - ${m.paused} paused` : fmtN(m.n, 0)))))
          : h('div', {class: 'muted small', style: 'padding:8px 0'}, 'Nothing in flight. Work you start shows here, module by module.'),
        busy.length && busy.length < inf.modules.length ? h('div', {class: 'small muted', style: 'margin-top:8px'}, `Modules with nothing in flight are left out (${inf.modules.length - busy.length}).`) : null,
        inf.by_status.attention ? h('div', {class: 'note err', style: 'margin:10px 0 0'}, `${inf.by_status.attention} dashboard${inf.by_status.attention === 1 ? '' : 's'} need attention.`) : null),
      h('div', {class: 'card', style: 'margin:0'}, h('div', {class: 'card-head'}, h('h3', {}, 'Waiting for a person'), h('span', {class: 'sp'}), h('a', {class: 'small', href: '#/d2d'}, 'All dashboards')),
        d.waiting.length ? h('div', {class: 'stack', style: 'gap:6px'}, d.waiting.map(w => h('a', {href: '#/p/' + w.pid, class: 'wait'},
          h('div', {class: 'wt'}, h('b', {}, w.name), h('small', {}, `${w.module} - ${w.what}`)), h('span', {class: 'pill ' + ((Date.now() / 1000 - w.since) > 86400 ? 'err' : (Date.now() / 1000 - w.since) > 3600 ? 'you' : 'plain')}, ago(w.since)))))
          : h('div', {class: 'muted small', style: 'padding:8px 0'}, 'Nothing is waiting for you.'))),
    h('div', {class: 'g3', style: 'margin-top:16px'},
      h('div', {class: 'card', style: 'margin:0'}, h('div', {class: 'card-head'}, h('h3', {}, 'Agents right now'), h('span', {class: 'sp'}), h('span', {class: 'pill ' + (now.running ? 'run' : ag.ok === false ? 'err' : 'ok') + ' plain'}, now.running ? 'Working' : ag.ok === false ? 'Agent offline' : 'Idle')),
        now.running ? h('div', {class: 'feed'}, h('div', {class: 'fi'}, h('span', {class: 'ft'}, dur((now.running.age_s || 0) * 1000)), h('span', {}, h('b', {}, now.running.agent || 'Agent'), ` - ${now.running.doing || 'working'} - `,   // any module's agent, by name; the folder only for people who may open it
            now.running.link ? h('a', {href: now.running.link}, now.running.name || now.running.module) : h('span', {class: 'muted'}, `${now.running.module || 'a module'} - someone else's work`))),
          now.queue ? h('div', {class: 'fi'}, h('span', {class: 'ft'}, 'queue'), h('span', {}, `${now.queue} job${now.queue === 1 ? '' : 's'} waiting for the build lane`)) : null)
          : h('div', {class: 'muted small', style: 'padding:8px 0'}, now.queue ? `${now.queue} job(s) queued; the agent is about to start.` : 'One agent, one job at a time. Nothing is running.'),
        h('div', {class: 'small muted', style: 'margin-top:10px'}, (S.health && S.health.daxcheck) ? "DAX checker on: Power BI's engine checks every measure before publishing." : 'DAX checker off: publishing waits until it runs on this PC.')),
      h('div', {class: 'card', style: 'margin:0'}, h('div', {class: 'card-head'}, h('h3', {}, 'Recently proven'), h('span', {class: 'sp'}), h('a', {class: 'small', href: '#/d2d'}, 'Dashboards')),
        d.recent.length ? h('div', {class: 'stack', style: 'gap:10px'}, d.recent.map(r => h('a', {href: `#/p/${r.pid}/versions`, class: 'wait'}, h('span', {class: 'proven'}, icon('check')),
          h('div', {class: 'wt'}, h('b', {}, `${r.name} v${r.v}`), h('small', {}, `${r.checks} of ${r.gates} review gates passed - published ${ago(r.when)}`)))))
          : h('div', {class: 'muted small', style: 'padding:8px 0'}, 'Nothing published yet.')),
      h('div', {class: 'card', style: 'margin:0'}, h('div', {class: 'card-head'}, h('h3', {}, 'Questions to Ask D'), h('span', {class: 'sp'}), h('a', {class: 'small', href: '#/askd'}, 'Open')),
        h('div', {class: 'g2', style: 'gap:10px'}, h('div', {class: 'mini'}, h('div', {class: 'mv'}, fmtN(k.questions, 0)), h('div', {class: 'small muted'}, `questions in ${pl}`)),
          h('div', {class: 'mini'}, h('div', {class: 'mv'}, fmtN(inf.modules.find(m => m.id === 'schedule').n, 0)), h('div', {class: 'small muted'}, 'reports and alerts scheduled'))),
        h('div', {class: 'small muted', style: 'margin-top:10px'}, 'Answers use each person\'s own access; every query is audited.'))),
    // P12: Service desk triage (tickets -> groups -> an agent can handle -> near SLA); empty state until a source is connected
    sd ? h('div', {class: 'card', style: 'margin:16px 0 0'}, h('div', {class: 'card-head'}, h('h3', {}, 'Service desk'), h('span', {class: 'sp'}), h('a', {class: 'small', href: '#/servicedesk'}, 'Open')),
      sd.sources ? [h('div', {style: 'display:grid;gap:10px;grid-template-columns:repeat(auto-fit,minmax(150px,1fr))'},
        [[sd.open_tickets, 'open tickets'], [sd.to_act, 'groups to act on'], [sd.agent, 'an agent can handle'], [sd.near_sla, 'near SLA breach']].map(([v, l]) => h('div', {class: 'mini'}, h('div', {class: 'mv'}, fmtN(v, 0)), h('div', {class: 'small muted'}, l)))),
        h('div', {class: 'small muted', style: 'margin-top:10px'}, sd.by_source.map(x => `${x.label} ${fmtN(x.open, 0)}`).join(' - ') + ' - summaries written back after approval')]
        : h('div', {class: 'muted small', style: 'padding:8px 0'}, (sd.hint || 'Connect Jira, Freshservice or ServiceNow') + ' - tickets summarised, duplicates grouped, priority by business impact; nothing written back without your approval.')) : null,
    // P14: Data health (health across the watched assets, open incidents); empty state until something is watched
    ob ? h('div', {class: 'card', style: 'margin:16px 0 0'}, h('div', {class: 'card-head'}, h('h3', {}, 'Data health'), h('span', {class: 'sp'}), h('a', {class: 'small', href: '#/observability'}, 'Open')), ob.watched ? [h('div', {style: 'display:grid;gap:10px;grid-template-columns:repeat(auto-fit,minmax(150px,1fr))'}, [[ob.health_pct == null ? '-' : fmtN(ob.health_pct) + ' %', 'assets passing every check'], [fmtN(ob.open, 0), 'open incidents'], [fmtN(ob.watched, 0), 'assets watched'], [ob.time_to_fix_h == null ? '-' : fmtN(ob.time_to_fix_h) + ' h', 'median time to fix']].map(([v, l]) => h('div', {class: 'mini'}, h('div', {class: 'mv'}, v), h('div', {class: 'small muted'}, l)))), h('div', {class: 'small muted', style: 'margin-top:10px'}, ob.layers.map(l => `${l.label} ${l.open ? l.open + ' open' : 'ok'}`).join(' - ') + ' - warnings, tickets and fixes only after your approval')] : h('div', {class: 'muted small', style: 'padding:8px 0'}, (ob.hint || 'Nothing watched yet') + ' - freshness, volume, schema, distribution and reconciliation checked across every layer, with the impact traced before anyone acts on a wrong number.')) : null,
    // P11: the consulting studio (proposals, decks, documents, RFP responses); a small empty state until something is briefed
    su && !viewer ? h('div', {class: 'card', style: 'margin:16px 0 0'}, h('div', {class: 'card-head'}, h('h3', {}, 'Studio'), h('span', {class: 'sp'}), h('a', {class: 'small', href: '#/studio'}, 'Open')),
      su.items ? [h('div', {style: 'display:grid;gap:10px;grid-template-columns:repeat(auto-fit,minmax(150px,1fr))'},
        [[su.items, 'deliverables'], [su.awaiting, 'waiting for you'], [su.running, 'Relay is working on'], [su.final, 'final']].map(([v, l]) => h('div', {class: 'mini'}, h('div', {class: 'mv'}, fmtN(v, 0)), h('div', {class: 'small muted'}, l)))),
        h('div', {class: 'small muted', style: 'margin-top:10px'}, su.recent.slice(0, 3).map(r => h('a', {href: '#/studio/' + r.id, style: 'margin-right:12px'}, `${r.name} - ${r.status_label}`)))]
        : h('div', {class: 'muted small', style: 'padding:8px 0'}, su.hint, ' ', h('a', {href: '#/rfp'}, 'RFP & bid response'))) : null,
    // P16: Self-healing (open cases, fixed, rules) and AI SDLC changes in flight - small cards with safe empty states
    hl || sl ? h('div', {class: 'g2', style: 'margin:16px 0 0'},
      hl ? h('div', {class: 'card', style: 'margin:0'}, h('div', {class: 'card-head'}, h('h3', {}, 'Self-healing'), h('span', {class: 'sp'}), h('a', {class: 'small', href: '#/heal'}, 'Open')), hl.open || hl.fixed_30d ? [h('div', {style: 'display:grid;gap:10px;grid-template-columns:repeat(auto-fit,minmax(120px,1fr))'}, [[fmtN(hl.open, 0), 'open cases'], [fmtN(hl.waiting_for_you, 0), 'need a person'], [fmtN(hl.fixed_30d, 0), 'fixed in 30 days'], [fmtN(hl.rules_total, 0), 'rules']].map(([v, l]) => h('div', {class: 'mini'}, h('div', {class: 'mv'}, v), h('div', {class: 'small muted'}, l)))), h('div', {class: 'small muted', style: 'margin-top:10px'}, 'diagnosed with the logs and the lineage, fixed on a copy, applied only after your approval')] : h('div', {class: 'muted small', style: 'padding:8px 0'}, (hl.hint || 'Nothing to heal right now') + ' - refreshes, gates, sign-ins, schedules and integration runs are watched; a failure becomes a case here.')) : null,
      sl ? h('div', {class: 'card', style: 'margin:0'}, h('div', {class: 'card-head'}, h('h3', {}, 'Changes in flight'), h('span', {class: 'sp'}), h('a', {class: 'small', href: '#/sdlc'}, 'Open')), sl.open || sl.released_30d ? [h('div', {style: 'display:grid;gap:10px;grid-template-columns:repeat(auto-fit,minmax(120px,1fr))'}, [[fmtN(sl.open, 0), 'in flight'], [fmtN(sl.waiting_for_you, 0), 'waiting for a person'], [fmtN(sl.released_30d, 0), 'released in 30 days'], [fmtN(sl.repos, 0), 'repositories']].map(([v, l]) => h('div', {class: 'mini'}, h('div', {class: 'mv'}, v), h('div', {class: 'small muted'}, l)))), h('div', {class: 'small muted', style: 'margin-top:10px'}, 'plan, pull request, UAT and release each confirmed by a named person; Relay never merges')] : h('div', {class: 'muted small', style: 'padding:8px 0'}, (sl.hint || 'No change in flight') + ' - bring a repository and a change request becomes a tested pull request through approved steps.')) : null) : null,
    reg ? [h('div', {class: 'section-title'}, h('h2', {}, 'Modules by pillar'), h('span', {class: 'hint'}, h('a', {href: '#/modules'}, 'All modules'))),
      h('div', {class: 'g6'}, reg.pillars.map(p => { const ms = reg.modules.filter(m => m.pl === p.id), live = ms.filter(m => ['available', 'partly'].includes(m.state)).length;
        return h('a', {class: 'card pillar-tile', href: '#/modules', onclick: () => setTimeout(() => { const el = document.getElementById('pl-' + p.id); if (el) el.scrollIntoView(); }, 60)},
          h('div', {class: 'small muted'}, p.name), h('div', {class: 'mv'}, String(live), h('span', {class: 'small muted', style: 'font-weight:400'}, ` of ${ms.length} live`)),
          h('div', {class: 'progress', style: 'margin-top:8px'}, h('div', {style: `width:${ms.length ? live * 100 / ms.length : 0}%`}))); }))] : null));
}
