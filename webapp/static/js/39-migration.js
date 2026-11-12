/* ---------------- D2D Relay: Migration D2D (#/migration, 2026-11-12), "Migrate any Dashboard to Dashboard". What it
   is (moving dashboards from one BI tool to another, in any direction) and a button that asks PASDACS to switch it on:
   POST /api/org/migration-request emails PASDACS what was asked (Reply-To the person) and lists it on the admin
   portal's Requests page. Not self-service yet; the ids are the server's (orgs.BI_TOOLS). ---------------- */
const BI_TOOLS = [['cognos', 'IBM Cognos Analytics'], ['qlik', 'Qlik Sense or QlikView'], ['looker', 'Looker'], ['powerbi', 'Power BI'],
  ['tableau', 'Tableau'], ['microstrategy', 'MicroStrategy'], ['businessobjects', 'SAP BusinessObjects'],
  ['ssrs', 'SQL Server Reporting Services'], ['other', 'Another tool']];

function renderMigration() {
  const o = ORG(), contact = o.contact || 'info@pasdacs.com';
  document.title = 'Migration D2D - D2D Relay';
  const chips = () => h('div', {class: 'chips'}, BI_TOOLS.filter(([k]) => k !== 'other').map(([, name]) => h('span', {class: 'tool'}, name)),
    h('span', {class: 'tool more'}, 'and more'));
  const tile = (ic, title, text) => h('div', {class: 'tile'}, icon(ic), h('h3', {}, title), h('div', {class: 'muted small'}, text));
  const ask = label => h('button', {class: 'btn primary', type: 'button', onclick: () => migrationDialog()}, icon('send'), label);
  $('#main').replaceChildren(h('div', {class: 'page migr'},
    h('div', {class: 'eyebrow'}, 'Migration D2D'),
    h('h1', {}, 'Migrate any dashboard to any dashboard'),
    h('p', {class: 'muted lead'}, 'Move your reports from one BI tool to another: Cognos, Qlik, Looker, Tableau, Power BI and more, in any direction. '
      + 'Each dashboard is rebuilt in the new tool, and its numbers are checked against the original.'),
    h('div', {class: 'row', style: 'gap:10px;flex-wrap:wrap;margin:6px 0 20px;align-items:center'}, ask('Contact PASDACS'),
      h('span', {class: 'small muted'}, `PASDACS switches Migration D2D on for each organisation. Tell us what you would like to move.`)),
    h('div', {class: 'migrmap'},
      h('div', {class: 'card'}, h('h3', {}, 'From'), chips()),
      h('div', {class: 'migrmid', 'aria-hidden': 'true'}, icon('swap')),
      h('div', {class: 'card'}, h('h3', {}, 'To'), chips())),
    h('h2', {}, 'How it works'),
    h('ol', {class: 'howto'},
      h('li', {}, h('div', {}, h('b', {}, 'Tell us what you have. '), 'The tools, roughly how many dashboards, and where their data lives.')),
      h('li', {}, h('div', {}, h('b', {}, 'Your reports are read, not changed. '), 'From your tool\'s own files and exports: the data model, measures and calculations, pages, visuals and filters. Your current tool keeps working as it is.')),
      h('li', {}, h('div', {}, h('b', {}, 'They are rebuilt in the new tool. '), 'Calculations are translated into its language (Qlik or Cognos expressions into DAX, for example), in your brand\'s colours.')),
      h('li', {}, h('div', {}, h('b', {}, 'You check them side by side. '), 'Each dashboard comes with a proof that its numbers match the original, and nothing goes live until you approve it.'))),
    h('h2', {}, 'What moves'),
    h('div', {class: 'tiles3'},
      tile('table', 'The data model', 'Tables, relationships, and the measures and calculations built on them.'),
      tile('chart', 'Pages and visuals', 'Charts, tables, KPIs, filters and prompts, laid out as they were, in the new tool\'s own visuals.'),
      tile('check', 'The proof', 'The same questions asked of the old and the new dashboard, and the answers compared.')),
    h('div', {class: 'card'}, h('h3', {}, 'Ready to move?'),
      h('p', {class: 'small muted', style: 'margin:4px 0 12px'}, `Migration D2D is not switched on for ${o.name || 'your organisation'} yet. `
        + 'Tell PASDACS what you would like to move: we reply by email to agree what moves and when, and switch it on for you.'),
      h('div', {class: 'row', style: 'gap:12px;flex-wrap:wrap;align-items:center'}, ask('Contact PASDACS'),
        h('span', {class: 'small muted'}, 'or write to ', h('a', {href: `mailto:${contact}?subject=${encodeURIComponent('Migration D2D')}`}, contact))))));
}

function migrationDialog() {
  const o = ORG(), me = S.me || {}, contact = o.contact || 'info@pasdacs.com', org = o.name || 'our organisation';
  const picked = {source: new Set(), target: new Set()};
  const boxes = side => h('div', {class: 'toolpick'}, BI_TOOLS.map(([k, name]) => {
    const cb = h('input', {type: 'checkbox'});
    cb.onchange = () => { if (cb.checked) picked[side].add(k); else picked[side].delete(k); };
    return h('label', {class: 'chk'}, cb, h('span', {}, name));
  }));
  const count = h('input', {type: 'number', min: 1, step: 1, class: 'num', placeholder: 'For example 40', style: 'max-width:160px'});
  const msg = h('textarea', {rows: 3, placeholder: 'Where the data lives, what matters most, and by when (optional). For example: 40 Cognos reports on Oracle, moving to Power BI by March.'});
  const label = side => BI_TOOLS.filter(([k]) => picked[side].has(k)).map(([, n]) => n).join(', ') || '...';
  const mailto = () => {
    const body = `Hello PASDACS,\n\nWe would like to move our dashboards with Migration D2D.\n\nFrom: ${label('source')}\nTo: ${label('target')}\n`
      + (count.value ? `Dashboards, roughly: ${count.value}\n` : '') + `Organisation: ${org}${o.domain ? ` (@${o.domain})` : ''}\n`
      + `Requested by: ${me.name || ''} <${me.email || ''}>\n` + (msg.value.trim() ? `\n${msg.value.trim()}\n` : '');
    return `mailto:${contact}?subject=${encodeURIComponent(`D2D Relay: Migration D2D for ${org}`)}&body=${encodeURIComponent(body)}`;
  };
  const mailLink = text => h('a', {href: mailto(), onclick: e => { e.currentTarget.href = mailto(); }}, text);
  const out = h('div', {role: 'status'});
  const send = h('button', {class: 'btn primary', type: 'button'}, icon('send'), 'Send to PASDACS');
  send.onclick = async () => {
    if (!picked.source.size || !picked.target.size)
      return out.replaceChildren(h('div', {class: 'note warn'}, 'Choose where your dashboards are now and where they should go.'));
    send.disabled = true;
    try {
      const n = parseInt(count.value, 10);
      const r = await api('/api/org/migration-request', {json: {source: [...picked.source], target: [...picked.target],
        dashboards: n > 0 ? n : null, message: msg.value}});
      out.replaceChildren(r.sent ? h('div', {class: 'note ok'}, `Sent to ${r.contact}. PASDACS replies to ${me.email || 'you'} to agree what moves and when.`)
        : h('div', {class: 'note warn'}, 'Your request is recorded, but the email could not be sent from here. Please ', mailLink(`email ${r.contact}`), ' as well.'));
      send.lastChild.textContent = 'Sent';
    } catch (e) {
      send.disabled = false;
      out.replaceChildren(h('div', {class: 'note err'}, e.message, ' You can also ', mailLink(`email ${contact}`), '.'));
    }
  };
  modal('Migration D2D: tell PASDACS what to move', h('div', {class: 'mbody'},
    h('p', {style: 'margin-top:0'}, `PASDACS switches Migration D2D on for ${org} and replies by email. Nothing is moved or changed until you agree.`),
    h('label', {class: 'f', style: 'margin-top:0'}, 'Where are your dashboards now?'), boxes('source'),
    h('label', {class: 'f'}, 'Where should they go?'), boxes('target'),
    h('label', {class: 'f'}, 'Roughly how many dashboards? ', h('small', {}, 'optional')), count,
    h('label', {class: 'f'}, 'Anything else ', h('small', {}, 'optional')), msg, out,
    h('div', {class: 'row', style: 'justify-content:flex-end;gap:12px;margin-top:12px;align-items:center;flex-wrap:wrap'},
      h('span', {class: 'small muted'}, 'or ', mailLink(`email ${contact}`)), send)));
}
