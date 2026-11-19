/* ---------------- D2D Relay: Migration D2D (#/migration, 2026-11-12), "Migrate any Dashboard to Dashboard". What it
   is (moving dashboards from one BI tool to another, in any direction) and a button that asks PASDACS to switch it on:
   POST /api/org/migration-request emails PASDACS what was asked (Reply-To the person) and lists it on the admin
   portal's Requests page. Not self-service yet; the ids are the server's (orgs.BI_TOOLS). One contact, the card at the end
   (the user, 2026-11-19: "in migration remove contact which is twice"). DAWB (#/dawb, renderDawb below): coming soon, what
   it is, and one contact. ---------------- */
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
      + (count.value ? `Dashboards, roughly: ${count.value}\n` : '') + `Organisation: ${org}${o.domain ? ` (${orgWhere(o)})` : ''}\n`
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

/* DAWB, the Data Analytics Work Bench (#/dawb): coming soon (the user, 2026-11-19: "Like Migration D2D, have DAWB as well as
   coming soon and explanation of it and contact"). PASDACS's lakehouse builder: AI agents do the data-engineering work,
   people approve it, and each finished build is handed to D2D (item 58, New dashboard, "From a DAWB hand-off"). */
function renderDawb() {
  const o = ORG(), me = S.me || {}, contact = o.contact || 'info@pasdacs.com', org = o.name || 'our organisation';
  document.title = 'DAWB - D2D Relay';
  const tile = (ic, title, text) => h('div', {class: 'tile'}, icon(ic), h('h3', {}, title), h('div', {class: 'muted small'}, text));
  const li = (b, text) => h('li', {}, h('div', {}, h('b', {}, b), text));
  const body = `Hello PASDACS,\n\nWe would like to hear about DAWB, the Data Analytics Work Bench, for ${org}.\n\n`
    + `Our data sources (optional): \n\nRequested by: ${me.name || ''} <${me.email || ''}>\n`;
  const mail = `mailto:${contact}?subject=${encodeURIComponent(`D2D Relay: DAWB for ${org}`)}&body=${encodeURIComponent(body)}`;
  $('#main').replaceChildren(h('div', {class: 'page migr dawb'},
    h('div', {class: 'eyebrow row', style: 'gap:8px;align-items:center'}, 'DAWB', h('span', {class: 'tag'}, 'Coming soon')),
    h('h1', {}, 'Data Analytics Work Bench'),
    h('p', {class: 'muted lead'}, 'AI agents do the data-engineering work; your people make the decisions. DAWB reads your source systems, '
      + 'builds and runs the pipelines and the lakehouse, and hands each finished build to D2D, ready for dashboards.'),
    h('h2', {}, 'How it works'),
    h('ol', {class: 'howto'},
      li('Connect your sources. ', 'Databases, warehouses and pipeline tools: SQL Server, PostgreSQL, MySQL, BigQuery, Azure Databricks, '
        + 'Azure Data Factory, Informatica, dbt, Airflow and more.'),
      li('Agents do the work. ', 'They read your sources, propose the data model and build the pipelines, always in the same six phases.'),
      li('People approve. ', 'The work stops at fixed points for a named person to approve, nothing is deployed until a second person '
        + 'agrees, and every action is logged.'),
      li('It runs, and D2D takes it from there. ', 'Pipelines run in DEV and TEST, then live, day and night. Each finished build comes to '
        + 'D2D with its tables and a proposed plan, waiting at Confirm KPIs.')),
    h('h2', {}, 'What it covers'),
    h('div', {class: 'tiles3'},
      tile('plus', 'Build new', 'A lakehouse and its pipelines, from your source systems.'),
      tile('swap', 'Change and migrate', 'Change what exists, or move off legacy tools, with lineage across platforms.'),
      tile('shield', 'Assess and run', 'Assess a data estate, and run its pipelines day and night, with an audit trail.')),
    h('div', {class: 'card'}, h('h3', {}, 'Interested in DAWB?'),
      h('p', {class: 'small muted', style: 'margin:4px 0 12px'}, `DAWB is coming soon. Tell PASDACS about your data sources: we reply by email, `
        + `show you DAWB, and tell you when it is ready for ${o.name || 'your organisation'}.`),
      h('div', {class: 'row', style: 'gap:12px;flex-wrap:wrap;align-items:center'},
        h('a', {class: 'btn primary', href: mail}, icon('send'), 'Contact PASDACS'),
        h('span', {class: 'small muted'}, 'or write to ', h('a', {href: `mailto:${contact}?subject=${encodeURIComponent('DAWB')}`}, contact))))));
}
