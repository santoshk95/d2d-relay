/* ---------------- RFP & bid response (P11). Qualify -> Understand -> Answer -> Price -> Review -> Submit -> Learn: the pack goes in, Relay lists
   every requirement with its page reference, a named person decides go / no-go, the compliance matrix cites only library items and
   Relay's module facts, the price is computed from the rate cards, three reviews plus a red-team read, the submission pack is accepted
   by a named person and submitted by hand or by mail, and a won response feeds the library. Routes #/rfp and #/rfp/<id>. ---------------- */
const RFP_STEPS = [['Qualify', 'the pack read, go / no-go'], ['Understand', 'every requirement, confirmed'], ['Answer', 'compliance matrix with evidence'], ['Price', 'from your rate cards'], ['Review', 'technical, commercial, legal'], ['Submit', 'the pack, by a named person'], ['Learn', 'win / loss into the library']];
const RFP_STEP = {queued: 0, qualifying: 0, awaiting_requirements: 1, awaiting_gonogo: 0, no_go: 0, answering: 2, awaiting_matrix: 2, pricing: 3, awaiting_price: 3, redteam: 4, awaiting_reviews: 4, packing: 5, awaiting_submit: 5, ready: 5, submitted: 6, won: 6, lost: 6, withdrawn: 6, error: 0};
const RFP_PILL = {queued: ['Queued', 'run'], qualifying: ['Relay is reading the pack', 'run'], awaiting_requirements: ['Your turn: the requirements', 'you'], awaiting_gonogo: ['Go / no-go', 'you'], no_go: ['No-go', ''],
  answering: ['Relay is drafting', 'run'], awaiting_matrix: ['Your turn: the matrix', 'you'], pricing: ['Your turn: price it', 'you'], awaiting_price: ['Your turn: confirm the price', 'you'], redteam: ['Red-team read', 'run'],
  awaiting_reviews: ['Reviews', 'you'], packing: ['Building the pack', 'run'], awaiting_submit: ['Your turn: accept the pack', 'you'], ready: ['Ready to submit', 'ok'], submitted: ['Submitted', 'ok'], won: ['Won', 'ok'], lost: ['Lost', ''], withdrawn: ['Withdrawn', ''], error: ['Needs attention', 'err']};
const RFP_STATUS_CLS = {Comply: 'ok', Partial: 'warn', Alternative: 'acc', Not: ''};
const RFP_ACCEPT = '.pdf,.docx,.xlsx,.csv,.pptx,.txt,.md,.png,.jpg,.jpeg';
const rfpPill = s => { const [t, c] = RFP_PILL[s] || [s, '']; return h('span', {class: 'pill ' + c}, t); };
S.rfpTimer = null;

function renderRfp() {
  clearTimeout(S.rfpTimer);
  const m = location.hash.match(/^#\/rfp\/([\w-]+)/);
  return m ? renderRfpItem(m[1]) : renderRfpHome();
}
function rfpJourney(cur) {
  return h('ol', {class: 'journey', 'aria-label': 'RFP steps'}, RFP_STEPS.map(([l, sub], i) => h('li', {class: (i < cur ? 'done ' : '') + (i === cur ? 'on' : '')}, h('span', {class: 'dot'}, i < cur ? '✓' : ''), h('div', {class: 'jl'}, `${i + 1} ${l}`), h('div', {class: 'js'}, sub))));
}

/* ---------- home: new response, responses, library, rate cards, platforms ---------- */
async function renderRfpHome() {
  const main = $('#main');
  main.replaceChildren(skel('page'));
  let d, dir = {users: []};
  try { [d, dir] = await Promise.all([api('/api/rfp'), api('/api/directory').catch(() => ({users: []}))]); } catch (e) { main.replaceChildren(h('div', {class: 'page'}, h('div', {class: 'note err'}, e.message))); return; }
  if (location.hash !== '#/rfp' && !location.hash.startsWith('#/rfp?')) return;
  const me = S.me || {}, viewer = !d.can_create;
  const name = h('input', {type: 'text', placeholder: 'e.g. Contoso Retail - BI migration RFP'}), buyer = h('input', {type: 'text', placeholder: 'Buyer (as on the pack)'});
  const btype = h('select', {class: 'sel', 'aria-label': 'Buyer type'}, [h('option', {value: ''}, 'Buyer type: from the pack'), ...d.buyer_types.map(t => h('option', {value: t}, t))]);
  const notes = h('textarea', {rows: 3, placeholder: 'What the bid team already knows: relationship, incumbents, what to avoid'});
  const person = (label, key) => { const sel = h('select', {class: 'sel', 'aria-label': label}, [h('option', {value: ''}, `${label}: the owner`), ...dir.users.map(u => h('option', {value: u.id}, `${u.name}`))]); sel.dataset.key = key; return sel; };
  const people = [person('Go / no-go decider', 'decider'), person('Technical reviewer', 'technical'), person('Commercial reviewer', 'commercial'), person('Legal reviewer', 'legal')];
  const picked = [];
  const list = h('div', {class: 'stack', style: 'gap:8px'});
  const input = h('input', {type: 'file', multiple: true, accept: RFP_ACCEPT, style: 'display:none', 'aria-label': 'Attach the RFP pack'});
  const show = () => list.replaceChildren(...picked.map((f, i) => h('div', {class: 'arow'}, h('span', {class: 'aico'}, icon('file')), h('div', {class: 'grow', style: 'min-width:0'}, h('div', {class: 'an'}, f.name), h('div', {class: 'small muted'}, size(f.size))), h('button', {class: 'iconbtn', type: 'button', 'aria-label': 'Remove ' + f.name, onclick: () => { picked.splice(i, 1); show(); }}, icon('x')))));
  const add = files => { for (const f of files) if (RFP_ACCEPT.includes('.' + (f.name.split('.').pop() || '').toLowerCase())) picked.push(f); else notify(`${f.name}: not a kind of file Relay reads`, 'err'); show(); };
  input.onchange = () => { add(input.files); input.value = ''; };
  const drop = h('div', {class: 'drop', role: 'button', tabindex: '0', 'aria-label': 'Add the RFP pack', onclick: () => input.click(), onkeydown: e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); input.click(); } }},
    input, icon('download'), h('div', {}, h('b', {}, 'Drop the RFP pack here, or click to add')), h('div', {class: 'hint'}, 'PDF, Word, Excel, slides or a portal export - every page is read'));
  drop.ondragover = e => { e.preventDefault(); drop.classList.add('over'); }; drop.ondragleave = () => drop.classList.remove('over'); drop.ondrop = e => { e.preventDefault(); drop.classList.remove('over'); add(e.dataTransfer.files); };
  const bar = h('div', {class: 'bar'}, h('i'));
  const go = h('button', {class: 'btn primary', type: 'submit', disabled: viewer}, icon('play'), 'Let Relay read the pack');
  const form = h('form', {class: 'card', style: 'margin:0'},
    h('label', {class: 'f', style: 'margin-top:0'}, 'Response'), name, h('div', {class: 'opts', style: 'margin-top:10px'}, buyer, btype),
    h('label', {class: 'f'}, 'What the bid team knows', h('small', {}, 'optional')), notes,
    h('div', {style: 'margin-top:12px'}, drop), list,
    h('div', {style: 'margin-top:12px'}, h('div', {class: 'small', style: 'font-weight:600;margin-bottom:6px'}, 'Named people ', h('span', {class: 'muted', style: 'font-weight:400'}, '- who decides go / no-go and who reviews')), h('div', {class: 'opts'}, people)),
    h('div', {class: 'row', style: 'margin-top:14px;gap:12px'}, h('span', {class: 'small muted'}, 'Nothing is submitted by Relay: a named person accepts the pack and submits it.'), h('span', {class: 'spacer'}), go),
    viewer ? h('div', {class: 'hint'}, 'Starting a response is for builders and leads; ask one to start it for you.') : null, bar);
  form.onsubmit = e => {
    e.preventDefault();
    if (name.value.trim().length < 3) return toast(go, 'Name the response.');
    if (!picked.length) return toast(go, 'Attach the RFP pack.');
    const fd = new FormData();
    fd.append('name', name.value); fd.append('buyer', buyer.value); fd.append('buyer_type', btype.value); fd.append('notes', notes.value);
    fd.append('people', JSON.stringify(Object.fromEntries(people.map(s => [s.dataset.key, s.value]).filter(([, v]) => v))));
    for (const f of picked) fd.append('files', f);
    bar.style.display = 'block'; go.disabled = true; go.lastChild.textContent = 'Uploading...';
    upload('/api/rfp', fd, p => { $('i', bar).style.width = (100 * p) + '%'; }).then(r => { location.hash = '#/rfp/' + r.id; })
      .catch(err => { go.disabled = false; go.lastChild.textContent = 'Let Relay read the pack'; bar.style.display = 'none'; toast(go, err.message); });
  };
  const libCard = h('div', {class: 'card', style: 'margin:0'}, h('div', {class: 'card-head'}, h('h3', {}, 'Past-responses library'), h('span', {class: 'sp'}), h('span', {class: 'small muted'}, `${d.library.count} items - ${d.library.won} from wins`)),
    d.library.recent.length ? h('div', {class: 'stack', style: 'gap:6px'}, d.library.recent.map(i => h('div', {class: 'nextrow'}, h('span', {class: 'tag ' + (i.won ? 'ok' : '')}, i.won ? 'won' : i.kind), h('div', {class: 'grow', style: 'min-width:0'}, h('b', {}, i.title), h('div', {class: 'small muted'}, (i.module ? moduleById(i.module) ? moduleById(i.module).name : i.module : '') + (i.buyer_type ? ' - ' + i.buyer_type : '')))))) : h('div', {class: 'muted small'}, 'Empty - answers from won responses land here; you can also add case studies by hand.'),
    me.builder !== false ? h('div', {class: 'row', style: 'margin-top:10px'}, h('button', {class: 'btn sm', onclick: () => rfpLibraryAdd()}, icon('plus'), 'Add an item'), h('span', {class: 'small muted'}, 'Searchable full-text; the agent may cite only these and Relay\'s modules.')) : null);
  const rcCard = h('div', {class: 'card', style: 'margin:0'}, h('div', {class: 'card-head'}, h('h3', {}, 'Rate cards'), h('span', {class: 'sp'}), me.admin ? h('button', {class: 'btn sm', onclick: () => rfpRateCards(d.rate_cards)}, 'Edit') : null),
    d.rate_cards.length ? h('table', {class: 'utable'}, h('tr', {}, h('th', {class: 'l'}, 'Role'), h('th', {}, 'Rate'), h('th', {}, 'Per')), d.rate_cards.map(r => h('tr', {}, h('td', {}, r.role), h('td', {class: 'n'}, `${fmtN(r.rate, 2)} ${r.currency}`), h('td', {class: 'n'}, r.unit))))
      : h('div', {class: 'muted small'}, 'No rate cards yet - an admin adds roles and day rates; prices are computed from them, never by the agent.'));
  main.replaceChildren(h('div', {class: 'page'},
    pageHead({crumbs: [['Home', '#/'], ['RFP & bid response']], eyebrow: brandName() + ' - Consulting services - RFP & bid response', title: 'From RFP to a submitted response',
      promise: 'An RFP, RFI or tender read in full; go / no-go with reasons; a compliance matrix; answers drafted from your past responses and Relay\'s own module facts; priced from your rate cards; reviewed and submitted as a pack. Never an invented reference.',
      actions: h('div', {class: 'row'}, h('a', {class: 'btn sm', href: '#/studio'}, 'Studio'), h('a', {class: 'btn sm', href: '#/m/rfp'}, 'How it works'))}),
    rfpJourney(0),
    h('div', {class: 'g-side'}, h('div', {class: 'stack'}, form,
        h('div', {class: 'card', style: 'margin:0'}, h('div', {class: 'card-head'}, h('h3', {}, 'Your responses'), h('span', {class: 'sp'}), h('span', {class: 'small muted'}, String(d.responses.length))),
          d.responses.length ? h('div', {class: 'stack', style: 'gap:6px'}, d.responses.slice(0, 20).map(r => h('a', {href: '#/rfp/' + r.id, class: 'wait'}, h('div', {class: 'wt'}, h('b', {}, r.name), h('small', {}, [r.buyer, r.requirements ? `${r.requirements} requirements` : null, r.deadline ? `due ${r.deadline}` : null, ago(r.updated || r.created)].filter(Boolean).join(' - '))), rfpPill(r.status))))
            : h('div', {class: 'muted small', style: 'padding:6px 0'}, 'No responses yet.'))),
      h('div', {class: 'stack'},
        h('div', {class: 'card', style: 'margin:0'}, h('h3', {}, 'Where you confirm'), h('div', {class: 'confirm', style: 'margin-top:8px'}, [['Requirements', 'the list the agent read from the RFP pack'], ['Go / no-go', 'the decision, with reasons, by a named person'], ['Matrix', 'the compliance matrix and every drafted answer'], ['Price', 'effort, licences and terms before they go in'], ['Submit', 'the final pack - a person submits it']].map(([s, v]) => h('div', {}, h('span', {class: 'proven'}, icon('check')), h('span', {}, h('b', {}, s + ': '), v))))),
        libCard, rcCard,
        h('div', {class: 'card', style: 'margin:0'}, h('h3', {}, 'Portals'), h('div', {class: 'small muted', style: 'margin:4px 0 8px'}, 'Listed, not integrated: Relay exports the pack and the portal fields; a person uploads them. API submission comes with the pilot.'),
          h('div', {class: 'stack', style: 'gap:4px'}, d.platforms.map(p => h('div', {class: 'small'}, h('b', {}, p.name + ': '), p.how))))))));
  document.title = `RFP & bid response - ${S.brand ? S.brand.full : 'RELAY by PASDACS'}`;
}
function rfpLibraryAdd() {
  const t = h('input', {type: 'text', placeholder: 'Title, e.g. Cognos to Power BI migration for a retailer'}), txt = h('textarea', {rows: 6, placeholder: 'The reusable answer or case study, in the bid team\'s voice'});
  const mod = h('select', {class: 'sel', 'aria-label': 'Module'}, [h('option', {value: ''}, 'Module: none'), ...(S.registry ? S.registry.modules.filter(m => !['hidden', 'platform'].includes(m.pl)).map(m => h('option', {value: m.id}, m.name)) : [])]);
  const kind = h('select', {class: 'sel', 'aria-label': 'Kind'}, [['answer', 'Answer'], ['case_study', 'Case study'], ['reference', 'Reference']].map(([v, l]) => h('option', {value: v}, l)));
  const bt = h('select', {class: 'sel', 'aria-label': 'Buyer type'}, [h('option', {value: ''}, 'Buyer type: any'), ...['public', 'private', 'ngo', 'government'].map(x => h('option', {value: x}, x))]);
  const ok = h('button', {class: 'btn primary', onclick: async () => { try { await api('/api/rfp/library', {json: {title: t.value, text: txt.value, module: mod.value || null, buyer_type: bt.value || null, kind: kind.value}}); mm.remove(); notify('Added to the library', 'ok'); renderRfpHome(); } catch (e) { notify(e.message, 'err'); } }}, 'Add');
  const mm = modal('Add a library item', h('div', {class: 'mbody'}, h('label', {class: 'f', style: 'margin-top:0'}, 'Title'), t, h('label', {class: 'f'}, 'Text'), txt, h('div', {class: 'opts', style: 'margin-top:10px'}, mod, kind), h('div', {style: 'margin-top:10px'}, bt),
    h('div', {class: 'row', style: 'justify-content:flex-end;margin-top:12px'}, h('button', {class: 'btn', onclick: () => mm.remove()}, 'Cancel'), ok)));
}
function rfpRateCards(rows) {
  const data = rows.map(r => ({...r}));
  const box = h('div', {class: 'stack', style: 'gap:6px'});
  const draw = () => box.replaceChildren(...data.map((r, i) => h('div', {class: 'row', style: 'flex-wrap:nowrap'},
    h('input', {type: 'text', value: r.role, placeholder: 'Role', style: 'flex:2', oninput: e => { r.role = e.target.value; }}), h('input', {type: 'number', min: 0, step: 100, value: r.rate, placeholder: 'Rate', style: 'flex:1', oninput: e => { r.rate = e.target.value; }}),
    h('input', {type: 'text', value: r.currency || 'INR', maxlength: 6, style: 'width:70px', oninput: e => { r.currency = e.target.value; }}), h('select', {class: 'sel', style: 'width:90px', onchange: e => { r.unit = e.target.value; }}, ['day', 'hour'].map(u => h('option', {value: u, selected: (r.unit || 'day') === u}, u))),
    h('button', {class: 'iconbtn', type: 'button', 'aria-label': 'Remove', onclick: () => { data.splice(i, 1); draw(); }}, icon('x')))), h('button', {class: 'btn sm', type: 'button', onclick: () => { data.push({role: '', rate: 0, currency: 'INR', unit: 'day'}); draw(); }}, icon('plus'), 'Add a role'));
  draw();
  const ok = h('button', {class: 'btn primary', onclick: async () => { try { await api('/api/rfp/rate-cards', {method: 'PUT', json: {rows: data}}); mm.remove(); notify('Rate cards saved', 'ok'); renderRfpHome(); } catch (e) { notify(e.message, 'err'); } }}, 'Save');
  const mm = modal('Rate cards', h('div', {class: 'mbody'}, h('div', {class: 'small muted', style: 'margin-bottom:8px'}, 'One line per role; the price step multiplies days by these rates and converts into the buyer\'s currency.'), box, h('div', {class: 'row', style: 'justify-content:flex-end;margin-top:12px'}, h('button', {class: 'btn', onclick: () => mm.remove()}, 'Cancel'), ok)), true);
}

/* ---------- the response page ---------- */
function rfpRequirementsTable(rv, opts = {}) {
  return h('div', {style: 'overflow:auto'}, h('table', {class: 'utable ftable'}, h('tr', {}, ['Id', 'Requirement', 'Kind', 'Where', 'Confidence'].map((t, i) => h('th', {class: i === 4 ? '' : 'l'}, t))),
    rv.requirements.slice(0, opts.limit || 500).map(r => h('tr', {class: r.confidence != null && r.confidence < 0.8 ? 'low' : ''}, h('td', {class: 'mono small'}, r.id), h('td', {}, r.text), h('td', {class: 'small'}, h('span', {class: 'tag ' + (r.kind === 'mandatory' ? 'warn' : '')}, r.kind)),
      h('td', {class: 'small muted'}, `${r.source}${r.page ? ' p. ' + r.page : ''}${r.section ? ' §' + r.section : ''}`), h('td', {class: 'n small'}, r.confidence == null ? '-' : Math.round(r.confidence * 100) + ' %')))));
}
function rfpMatrixTable(st, id, canEdit, act) {
  const mv = st.matrix;
  const editRow = r => {
    const status = h('select', {class: 'sel', 'aria-label': 'Status'}, ['Comply', 'Partial', 'Not', 'Alternative'].map(s => h('option', {value: s, selected: s === r.status}, s))), ans = h('textarea', {rows: 5, value: r.answer}), ev = h('input', {type: 'text', value: r.evidence.map(e => e.ref).join(', '), placeholder: 'module:<id>, library:<id>'});
    const ok = h('button', {class: 'btn primary', onclick: () => { mm.remove(); act('/matrix', {rows: [{id: r.id, status: status.value, answer: ans.value, evidence: ev.value.split(',').map(x => x.trim()).filter(Boolean)}]}, 'Row saved', 'PUT'); }}, 'Save');
    const mm = modal(`${r.id}: ${r.requirement.slice(0, 80)}`, h('div', {class: 'mbody'}, h('label', {class: 'f', style: 'margin-top:0'}, 'Status'), status, h('label', {class: 'f'}, 'Answer'), ans, h('label', {class: 'f'}, 'Evidence'), ev, h('div', {class: 'hint'}, 'Only module:<id> (Relay\'s registry) and library:<id> (items picked for this response) may be cited.'),
      h('div', {class: 'row', style: 'justify-content:flex-end;margin-top:12px'}, h('button', {class: 'btn', onclick: () => mm.remove()}, 'Cancel'), ok)));
  };
  return h('div', {class: 'stack'},
    h('div', {class: 'row small', style: 'gap:10px'}, ['Comply', 'Partial', 'Alternative', 'Not'].map(s => h('span', {class: 'tag ' + RFP_STATUS_CLS[s]}, `${s} ${mv.counts[s.toLowerCase()]}`)), h('span', {class: 'muted'}, `${mv.counts.rows} rows - ${mv.evidence_used.length} pieces of evidence`)),
    h('div', {style: 'overflow:auto'}, h('table', {class: 'utable'}, h('tr', {}, ['Id', 'Requirement', 'Status', 'Answer', 'Evidence', ''].map(t => h('th', {class: 'l'}, t))),
      mv.rows.map(r => h('tr', {}, h('td', {class: 'mono small'}, r.id), h('td', {class: 'small'}, r.requirement.slice(0, 140) + (r.requirement.length > 140 ? '...' : '')), h('td', {}, h('span', {class: 'tag ' + RFP_STATUS_CLS[r.status]}, r.status)),
        h('td', {class: 'small'}, r.answer.slice(0, 220) + (r.answer.length > 220 ? '...' : '')), h('td', {class: 'small'}, r.evidence.map(e => h('span', {class: 'chipx' + (e.ok ? '' : ' err'), title: e.ref, style: 'margin:1px'}, (e.kind === 'module' ? '◆ ' : '◇ ') + (e.name || e.ref)))),
        h('td', {}, canEdit && st.status === 'awaiting_matrix' ? h('button', {class: 'btn sm ghost', onclick: () => editRow(r)}, 'Edit') : null))))));
}
function rfpPriceForm(st, id, act) {
  const roles = st.rate_cards.map(r => r.role);
  const p = st.pricing || {currency: (st.requirements && st.requirements.buyer.currency) || 'INR', fx: {}, waves: [{name: 'Wave 1', lines: [{role: roles[0] || '', days: 10, module: ''}]}], licences: [], run_support: [], discount_pct: 0};
  const data = JSON.parse(JSON.stringify(p));
  const mods = S.registry ? S.registry.modules.filter(m => !['hidden', 'platform'].includes(m.pl)) : [];
  const box = h('div', {class: 'stack'});
  const num = (obj, k, w = '90px') => h('input', {type: 'number', min: 0, step: 'any', value: obj[k], style: `width:${w}`, 'aria-label': k, oninput: e => { obj[k] = e.target.value; }});
  const draw = () => box.replaceChildren(
    h('div', {class: 'row'}, h('label', {class: 'small'}, 'Buyer currency ', h('input', {type: 'text', value: data.currency, maxlength: 6, style: 'width:70px', oninput: e => { data.currency = e.target.value.toUpperCase(); }})),
      h('label', {class: 'small'}, 'Exchange rates (card currency -> buyer), e.g. INR=0.011 ', h('input', {type: 'text', value: Object.entries(data.fx || {}).map(([k, v]) => `${k}=${v}`).join(', '), style: 'min-width:200px', oninput: e => { data.fx = Object.fromEntries(e.target.value.split(',').map(x => x.split('=')).filter(x => x.length === 2 && x[0].trim()).map(([k, v]) => [k.trim().toUpperCase(), Number(v)])); }}))),
    ...data.waves.map((w, wi) => h('div', {class: 'nextrow', style: 'flex-direction:column;align-items:stretch'},
      h('div', {class: 'row'}, h('input', {type: 'text', value: w.name, style: 'font-weight:600', oninput: e => { w.name = e.target.value; }}), h('span', {class: 'spacer'}), h('button', {class: 'btn sm ghost danger', onclick: () => { data.waves.splice(wi, 1); draw(); }}, 'Remove wave')),
      ...w.lines.map((ln, li) => h('div', {class: 'row', style: 'flex-wrap:nowrap'}, h('select', {class: 'sel', style: 'flex:1', 'aria-label': 'Role', onchange: e => { ln.role = e.target.value; }}, roles.map(r => h('option', {value: r, selected: r === ln.role}, r))), num(ln, 'days'), h('span', {class: 'small muted'}, 'days'),
        h('select', {class: 'sel', style: 'flex:1', 'aria-label': 'Module', onchange: e => { ln.module = e.target.value; }}, [h('option', {value: ''}, 'module: any'), ...mods.map(m => h('option', {value: m.id, selected: m.id === ln.module}, m.name))]), h('button', {class: 'iconbtn', 'aria-label': 'Remove line', onclick: () => { w.lines.splice(li, 1); draw(); }}, icon('x')))),
      h('button', {class: 'btn sm', onclick: () => { w.lines.push({role: roles[0] || '', days: 5, module: ''}); draw(); }}, icon('plus'), 'Add a line'))),
    h('button', {class: 'btn sm', onclick: () => { data.waves.push({name: `Wave ${data.waves.length + 1}`, lines: []}); draw(); }}, icon('plus'), 'Add a wave'),
    h('div', {class: 'small', style: 'font-weight:600;margin-top:6px'}, 'Licences'), ...data.licences.map((lc, i) => h('div', {class: 'row', style: 'flex-wrap:nowrap'}, h('input', {type: 'text', value: lc.item, placeholder: 'Item', style: 'flex:2', oninput: e => { lc.item = e.target.value; }}), num(lc, 'qty'), h('span', {class: 'small muted'}, '×'), num(lc, 'unit'), h('span', {class: 'small muted'}, '×'), num(lc, 'months', '70px'), h('span', {class: 'small muted'}, 'months'), h('button', {class: 'iconbtn', 'aria-label': 'Remove', onclick: () => { data.licences.splice(i, 1); draw(); }}, icon('x')))),
    h('button', {class: 'btn sm', onclick: () => { data.licences.push({item: '', qty: 1, unit: 0, months: 12}); draw(); }}, icon('plus'), 'Add a licence'),
    h('div', {class: 'small', style: 'font-weight:600;margin-top:6px'}, 'Run & support'), ...data.run_support.map((r, i) => h('div', {class: 'row', style: 'flex-wrap:nowrap'}, h('input', {type: 'text', value: r.item, placeholder: 'Item', style: 'flex:2', oninput: e => { r.item = e.target.value; }}), num(r, 'months', '70px'), h('span', {class: 'small muted'}, 'months ×'), num(r, 'per_month'), h('span', {class: 'small muted'}, 'per month'), h('button', {class: 'iconbtn', 'aria-label': 'Remove', onclick: () => { data.run_support.splice(i, 1); draw(); }}, icon('x')))),
    h('button', {class: 'btn sm', onclick: () => { data.run_support.push({item: '', months: 12, per_month: 0}); draw(); }}, icon('plus'), 'Add run & support'),
    h('div', {class: 'row', style: 'margin-top:8px'}, h('label', {class: 'small'}, 'Discount % ', num(data, 'discount_pct', '70px')), h('span', {class: 'spacer'}), h('button', {class: 'btn primary', onclick: () => act('/price', data, 'Price computed - confirm it')}, 'Compute the price')));
  draw();
  return h('div', {class: 'stack'}, st.rate_cards.length ? null : h('div', {class: 'note err'}, 'No rate cards yet: an admin adds them on the RFP page first.'), box);
}
function rfpPriceTable(p) {
  const t = p.totals, cur = p.currency;
  return h('div', {class: 'stack', style: 'gap:8px'},
    h('table', {class: 'utable'}, h('tr', {}, ['Line', 'Days', 'Rate', 'Amount'].map((x, i) => h('th', {class: i ? '' : 'l'}, x))),
      p.waves.flatMap(w => w.lines.map(ln => h('tr', {}, h('td', {}, `${w.name}: ${ln.role}${ln.module_name && ln.module ? ' (' + ln.module_name + ')' : ''}`), h('td', {class: 'n'}, ln.days), h('td', {class: 'n small'}, `${fmtN(ln.rate, 2)} ${ln.rate_currency}/${ln.unit}${ln.fx !== 1 ? ' × ' + ln.fx : ''}`), h('td', {class: 'n'}, fmtN(ln.amount, 2))))),
      p.licences.map(l => h('tr', {}, h('td', {}, `Licence: ${l.item}`), h('td', {class: 'n small'}, `${l.qty} × ${l.months} mo`), h('td', {class: 'n small'}, fmtN(l.unit, 2)), h('td', {class: 'n'}, fmtN(l.amount, 2)))),
      p.run_support.map(r => h('tr', {}, h('td', {}, `Run & support: ${r.item}`), h('td', {class: 'n small'}, `${r.months} mo`), h('td', {class: 'n small'}, fmtN(r.per_month, 2)), h('td', {class: 'n'}, fmtN(r.amount, 2)))),
      t.discount ? h('tr', {}, h('td', {}, `Discount ${p.discount_pct} %`), h('td'), h('td'), h('td', {class: 'n'}, '-' + fmtN(t.discount, 2))) : null,
      h('tr', {class: 'total'}, h('td', {}, `Total in ${cur}`), h('td', {class: 'n'}, t.days), h('td'), h('td', {class: 'n'}, fmtN(t.total, 2)))),
    h('div', {class: 'small muted'}, 'Computed from the rate cards in Python; the agent never prices.'));
}
async function renderRfpItem(id) {
  const main = $('#main');
  if (!$('#rfppage') || $('#rfppage').dataset.id !== id) main.replaceChildren(skel('page'));
  let st;
  try { st = await api('/api/rfp/' + id); } catch (e) { main.replaceChildren(h('div', {class: 'page'}, h('div', {class: 'card empty'}, h('h3', {}, 'No such response'), h('p', {}, e.message), h('a', {class: 'btn', href: '#/rfp'}, 'RFP & bid response')))); return; }
  if (!location.hash.startsWith('#/rfp/' + id)) return;
  const me = S.me || {}, canEdit = st.access && st.access.can_edit, running = ['queued', 'qualifying', 'answering', 'redteam', 'packing'].includes(st.status);
  const act = async (path, body, okMsg, method) => { try { await api(`/api/rfp/${id}${path}`, {method: method || 'POST', json: body || {}}); if (okMsg) notify(okMsg, 'ok'); renderRfpItem(id); } catch (e) { notify(e.message, 'err'); } };
  const sendBack = (path, title, hint, label = 'Send back') => {
    const ta = h('textarea', {rows: 4, placeholder: hint});
    const ok = h('button', {class: 'btn primary', onclick: () => { if (!ta.value.trim()) return notify('Say what to change.', 'err'); mm.remove(); act(path, {comment: ta.value}, 'Recorded'); }}, label);
    const mm = modal(title, h('div', {class: 'mbody'}, h('label', {class: 'f', style: 'margin-top:0'}, 'Your comment'), ta, h('div', {class: 'row', style: 'justify-content:flex-end;margin-top:12px'}, h('button', {class: 'btn', onclick: () => mm.remove()}, 'Cancel'), ok)));
  };
  const rv = st.requirements;
  const banner = st.status === 'error' ? h('div', {class: 'banner err'}, h('div', {class: 'ic'}, icon('alert')), h('div', {class: 'txt'}, h('div', {class: 't'}, 'Relay could not finish this step.'), h('div', {class: 'd'}, st.error || '')), canEdit ? h('button', {class: 'btn primary', onclick: () => act('/retry', {}, 'Queued again')}, 'Retry') : null)
    : running ? h('div', {class: 'banner run'}, h('div', {class: 'ic'}, h('span', {class: 'spin'})), h('div', {class: 'txt'}, h('div', {class: 't'}, RFP_PILL[st.status][0] + '.'), h('div', {class: 'd'}, st.running_since ? `Running for ${dur(Date.now() - st.running_since * 1000)} - one agent, one job at a time` : (st.position ? `${st.position} job(s) ahead of this one.` : 'The page refreshes itself.'))))
    : st.status === 'no_go' ? h('div', {class: 'banner'}, h('div', {class: 'ic'}, icon('info')), h('div', {class: 'txt'}, h('div', {class: 't'}, `No-go, decided by ${st.people_names.decider || st.owner_name || st.gonogo.by}.`), h('div', {class: 'd'}, st.gonogo.comment || '')), canEdit ? h('button', {class: 'btn', onclick: () => act('/gonogo/reopen', {}, 'Reopened')}, 'Reopen') : null)
    : ['awaiting_requirements', 'awaiting_gonogo', 'awaiting_matrix', 'pricing', 'awaiting_price', 'awaiting_reviews', 'awaiting_submit'].includes(st.status) ? h('div', {class: 'banner you'}, h('div', {class: 'ic'}, icon('info')), h('div', {class: 'txt'}, h('div', {class: 't'}, RFP_PILL[st.status][0] + '.'), h('div', {class: 'd'}, {awaiting_requirements: 'Every requirement with its page reference. Confirm the list, or correct it and Relay reads the pack again.', awaiting_gonogo: `Relay recommends ${(rv && rv.gonogo.recommendation || '-').toUpperCase()}; ${st.people_names.decider || 'the owner'} decides, with reasons.`, awaiting_matrix: 'Each requirement marked Comply, Partial, Not or Alternative with its evidence - only library items and Relay\'s modules. Edit, confirm or send back.', pricing: 'Effort per wave and module against your rate cards, licences, run & support - computed here, never by the agent.', awaiting_price: 'The price with its maths. Confirm it or send it back.', awaiting_reviews: 'Technical, commercial and legal reviews, with the red-team findings beside them.', awaiting_submit: 'The submission pack in the buyer\'s format plus the proposal deck. A named person accepts it; then it is submitted by hand or by mail.'}[st.status])))
    : st.status === 'ready' ? h('div', {class: 'banner ok'}, h('div', {class: 'ic'}, icon('check')), h('div', {class: 'txt'}, h('div', {class: 't'}, 'Ready to submit.'), h('div', {class: 'd'}, 'Download the pack and upload it on the portal, or send it by mail from your own account - then record it as submitted.')))
    : ['submitted', 'won', 'lost', 'withdrawn'].includes(st.status) ? h('div', {class: 'banner ok'}, h('div', {class: 'ic'}, icon('check')), h('div', {class: 'txt'}, h('div', {class: 't'}, `${RFP_PILL[st.status][0]}${st.submitted ? ' via ' + st.submitted.how + ' - ' + when(st.submitted.when) : ''}.`), h('div', {class: 'd'}, st.outcome ? `Outcome: ${st.outcome.result}${st.outcome.promoted && st.outcome.promoted.length ? ' - ' + st.outcome.promoted.length + ' answers now in the library' : ''}.` : 'Record the outcome and the buyer\'s feedback when you have them; a win feeds the library.')))
    : null;
  // ---- the main card by stage
  const cards = [];
  if (rv) cards.push(h('div', {class: 'card', style: 'margin:0'}, h('div', {class: 'card-head'}, h('h3', {}, 'Requirements'), h('span', {class: 'sp'}), h('span', {class: 'small muted'}, `${rv.counts.requirements} (${rv.counts.mandatory} mandatory, ${rv.counts.scored} scored, ${rv.counts.information} information) - ${rv.counts.sections} sections`)),
    h('div', {class: 'row small', style: 'gap:12px;margin-bottom:8px'}, h('span', {}, h('b', {}, 'Buyer: '), `${rv.buyer.name || st.buyer || '-'}${rv.buyer.type ? ' (' + rv.buyer.type + ')' : ''}${rv.buyer.currency ? ' - ' + rv.buyer.currency : ''}`), h('span', {}, h('b', {}, 'Deadline: '), rv.deadline || 'not stated'), h('span', {}, h('b', {}, 'Submission: '), [rv.format.submission, rv.format.portal].filter(Boolean).join(' - ') || '-')),
    rv.format.rules.length ? h('div', {class: 'small muted', style: 'margin-bottom:6px'}, h('b', {}, 'Format rules: '), rv.format.rules.join(' - ')) : null,
    rv.evaluation.length ? h('div', {class: 'small muted', style: 'margin-bottom:8px'}, h('b', {}, 'Evaluation: '), rv.evaluation.map(e => `${e.criterion}${e.weight != null ? ' ' + e.weight + '%' : ''}`).join(' - ')) : null,
    st.read_summary && st.status === 'awaiting_requirements' ? h('div', {class: 'note'}, h('b', {}, 'Relay: '), st.read_summary) : null,
    h('details', {class: 'more', open: st.status === 'awaiting_requirements'}, h('summary', {}, 'Every requirement'), rfpRequirementsTable(rv)),
    st.status === 'awaiting_requirements' && canEdit ? h('div', {class: 'row', style: 'border-top:1px solid var(--line);padding-top:12px;margin-top:14px'}, h('span', {class: 'small muted'}, 'Is this everything the pack asks for?'), h('span', {class: 'spacer'}),
      h('button', {class: 'btn', onclick: () => sendBack('/requirements/send-back', 'Correct the requirements', 'e.g. "Section 5 of the Excel sheet holds 6 more requirements; R-012 is information, not mandatory"')}, 'Correct something'),
      h('button', {class: 'btn primary', onclick: () => act('/requirements/confirm', {}, 'Requirements confirmed - go / no-go is next')}, icon('check'), 'Confirm the requirements')) : null));
  if (rv && ['awaiting_gonogo', 'no_go'].includes(st.status)) {
    const g = rv.gonogo;
    cards.push(h('div', {class: 'card', style: 'margin:0'}, h('div', {class: 'card-head'}, h('h3', {}, 'Go / no-go'), h('span', {class: 'sp'}), h('span', {class: 'tag ' + (g.recommendation === 'go' ? 'ok' : 'warn')}, `Relay recommends ${g.recommendation || '-'}`)),
      h('div', {class: 'g2'}, h('div', {}, h('b', {class: 'small'}, 'Reasons'), h('ul', {class: 'small', style: 'margin:4px 0;padding-left:18px'}, g.reasons.map(r => h('li', {}, r)))), h('div', {}, h('b', {class: 'small'}, 'Risks'), h('ul', {class: 'small', style: 'margin:4px 0;padding-left:18px'}, g.risks.length ? g.risks.map(r => h('li', {}, r)) : [h('li', {class: 'muted'}, 'none listed')]))),
      g.fit.length ? h('div', {class: 'row', style: 'gap:6px;margin-top:6px'}, g.fit.map(f => h('span', {class: 'chipx'}, `${f.name}: ${f.requirements}`))) : null,
      h('div', {class: 'small muted', style: 'margin-top:6px'}, [g.effort ? `Effort: ${g.effort}` : null, g.deadline_ok != null ? `Deadline ${g.deadline_ok ? 'achievable' : 'at risk'}` : null].filter(Boolean).join(' - ')),
      st.status === 'awaiting_gonogo' && canEdit ? h('div', {class: 'row', style: 'border-top:1px solid var(--line);padding-top:12px;margin-top:14px'}, h('span', {class: 'small muted'}, `${st.people_names.decider || st.owner_name || 'The owner'} decides.`), h('span', {class: 'spacer'}),
        h('button', {class: 'btn', onclick: () => sendBack('/gonogo/no-go', 'No-go', 'The reasons, for the record', 'Record the no-go')}, 'No-go'), h('button', {class: 'btn primary', onclick: () => act('/gonogo/go', {}, 'Go - Relay drafts the matrix')}, icon('check'), 'Go')) : null));
  }
  if (st.matrix && !['awaiting_requirements', 'awaiting_gonogo', 'no_go'].includes(st.status)) cards.push(h('div', {class: 'card', style: 'margin:0'}, h('div', {class: 'card-head'}, h('h3', {}, 'Compliance matrix'), h('span', {class: 'sp'}), st.matrix_confirmed ? h('span', {class: 'tag ok'}, 'confirmed') : null),
    st.answer_summary && st.status === 'awaiting_matrix' ? h('div', {class: 'note'}, h('b', {}, 'Relay: '), st.answer_summary) : null,
    rfpMatrixTable(st, id, canEdit, act),
    st.status === 'awaiting_matrix' && canEdit ? h('div', {class: 'row', style: 'border-top:1px solid var(--line);padding-top:12px;margin-top:14px'}, h('span', {class: 'small muted'}, 'Every answer with its evidence?'), h('span', {class: 'spacer'}),
      h('button', {class: 'btn', onclick: () => sendBack('/matrix/send-back', 'Send the matrix back', 'e.g. "R-017: we cannot comply on-premises - mark it Alternative with the hosting option"')}, 'Send back'),
      h('button', {class: 'btn primary', onclick: () => act('/matrix/confirm', {}, 'Matrix confirmed')}, icon('check'), 'Confirm the matrix')) : null));
  if (['pricing', 'awaiting_price'].includes(st.status) || (st.pricing && !['awaiting_requirements', 'awaiting_gonogo', 'no_go', 'answering', 'awaiting_matrix'].includes(st.status))) {
    cards.push(h('div', {class: 'card', style: 'margin:0'}, h('div', {class: 'card-head'}, h('h3', {}, 'Price'), h('span', {class: 'sp'}), st.price_confirmed ? h('span', {class: 'tag ok'}, 'confirmed') : st.pricing ? h('span', {class: 'small muted'}, `${fmtN(st.pricing.totals.total, 2)} ${st.pricing.currency}`) : null),
      st.pricing ? rfpPriceTable(st.pricing) : null,
      canEdit && ['pricing', 'awaiting_price'].includes(st.status) ? h('details', {class: 'more', open: st.status === 'pricing'}, h('summary', {}, st.pricing ? 'Change the inputs' : 'Effort, licences, run & support'), rfpPriceForm(st, id, act)) : null,
      st.status === 'awaiting_price' && canEdit ? h('div', {class: 'row', style: 'border-top:1px solid var(--line);padding-top:12px;margin-top:14px'}, h('span', {class: 'small muted'}, 'Effort, licences and terms before they go in.'), h('span', {class: 'spacer'}),
        h('button', {class: 'btn', onclick: () => sendBack('/price/send-back', 'Send the price back', 'e.g. "Wave 2 needs a second developer; add 20 days"')}, 'Send back'),
        h('button', {class: 'btn primary', onclick: () => act('/price/confirm', {}, 'Price confirmed - the red team reads it next')}, icon('check'), 'Confirm the price')) : null));
  }
  if (st.redteam && ['awaiting_reviews', 'packing', 'awaiting_submit', 'ready', 'submitted', 'won', 'lost', 'withdrawn'].includes(st.status)) {
    const rt = st.redteam;
    cards.push(h('div', {class: 'card', style: 'margin:0'}, h('div', {class: 'card-head'}, h('h3', {}, 'Reviews'), h('span', {class: 'sp'}), h('span', {class: 'small muted'}, `red team: ${rt.counts.high} high - ${rt.counts.medium} medium - ${rt.counts.low} low`)),
      rt.summary ? h('div', {class: 'note'}, h('b', {}, 'Red team: '), rt.summary) : null,
      h('div', {class: 'stack', style: 'gap:4px;margin-bottom:10px'}, rt.findings.slice(0, 12).map(f => h('div', {class: 'nextrow'}, h('span', {class: 'tag ' + (f.severity === 'high' ? 'warn' : '')}, f.severity), h('div', {class: 'grow small'}, h('b', {}, f.requirement + ': '), f.finding, f.suggestion ? h('div', {class: 'muted'}, '-> ' + f.suggestion) : null)))),
      h('div', {class: 'stack', style: 'gap:6px'}, st.reviews_needed.map(r => { const open = (st.open_checkpoints || []).find(c => c.kind === 'rfp.review' && c.review === r.key);
        return h('div', {class: 'row', style: 'flex-wrap:nowrap'}, r.done ? h('span', {class: 'proven'}, icon('check')) : h('span', {class: 'faint'}, '○'), h('span', {class: r.done ? '' : 'muted'}, r.label), h('span', {class: 'small muted'}, `- ${st.people_names[r.key] || st.owner_name || 'the owner'}`), h('span', {class: 'spacer'}),
          r.done ? h('span', {class: 'small muted'}, `${(st.reviews[r.key] || {}).by} - ${when((st.reviews[r.key] || {}).when)}`) : open && canEdit && st.status === 'awaiting_reviews' ? h('div', {class: 'row', style: 'gap:4px'}, h('button', {class: 'btn sm', onclick: () => sendBack(`/reviews/${r.key}/send-back`, `${r.label}: send back`, 'What must change before this review passes?')}, 'Send back'), h('button', {class: 'btn sm primary', onclick: () => act(`/reviews/${r.key}/accept`, {}, `${r.label} accepted`)}, 'Accept')) : h('span', {class: 'small muted'}, 'waiting')); }))));
  }
  if (st.latest_pack) {
    const p = st.latest_pack;
    cards.push(h('div', {class: 'card', style: 'margin:0'}, h('div', {class: 'card-head'}, h('h3', {}, `Submission pack v${p.v}`), h('span', {class: 'sp'}), h('span', {class: 'tag ' + (p.ok ? 'ok' : 'warn')}, p.ok ? 'checks passed' : `${p.fails} problem(s)`), h('span', {class: 'small muted'}, `the buyer wants: ${p.required}${p.portal ? ' (' + p.portal + ')' : ''}`)),
      h('div', {class: 'row', style: 'gap:6px'}, [['doc_docx', 'Word response'], ['doc_pdf', 'PDF'], ['xlsx', 'Excel matrix'], ['portal', 'Portal fields (JSON)'], ['deck_pptx', 'Proposal deck']].filter(([k]) => p.links[k]).map(([k, l]) => h('a', {class: 'btn sm', href: p.links[k]}, icon('download'), l))),
      h('div', {class: 'row', style: 'gap:10px;margin-top:8px'}, h('a', {class: 'small', href: p.preview.doc, target: '_blank', rel: 'noopener'}, 'Preview the response'), h('a', {class: 'small', href: p.preview.deck, target: '_blank', rel: 'noopener'}, 'Preview the deck'), h('span', {class: 'small muted'}, `${p.counts.rows} answers - ${p.counts.slides || 0} slides`)),
      st.status === 'awaiting_submit' && canEdit ? h('div', {class: 'row', style: 'border-top:1px solid var(--line);padding-top:12px;margin-top:14px'}, h('span', {class: 'small muted'}, `${st.people_names.decider || st.owner_name || 'A named person'} accepts the pack.`), h('span', {class: 'spacer'}),
        h('button', {class: 'btn', onclick: () => sendBack('/submit/send-back', 'Send the pack back', 'What must change before it can go out?')}, 'Send back'), h('button', {class: 'btn primary', onclick: () => act('/submit/accept', {}, 'Pack accepted - ready to submit')}, icon('check'), 'Accept the pack')) : null,
      st.status === 'ready' && canEdit ? h('div', {class: 'row', style: 'border-top:1px solid var(--line);padding-top:12px;margin-top:14px;gap:8px'},
        h('button', {class: 'btn', onclick: () => { const how = h('select', {class: 'sel', 'aria-label': 'How it was submitted'}, [['portal', 'On the portal'], ['hand', 'By hand / courier'], ['other', 'Other']].map(([v, l]) => h('option', {value: v}, l))), note = h('input', {type: 'text', placeholder: 'reference, confirmation number'});
          const ok = h('button', {class: 'btn primary', onclick: () => { mm.remove(); act('/submitted', {how: how.value, note: note.value}, 'Recorded as submitted'); }}, 'Record');
          const mm = modal('Record the submission', h('div', {class: 'mbody'}, h('label', {class: 'f', style: 'margin-top:0'}, 'How'), how, h('label', {class: 'f'}, 'Note'), note, h('div', {class: 'row', style: 'justify-content:flex-end;margin-top:12px'}, h('button', {class: 'btn', onclick: () => mm.remove()}, 'Cancel'), ok))); }}, 'Submitted on the portal'),
        h('button', {class: 'btn primary', onclick: async () => { let accts = []; try { accts = (await api('/api/email/accounts')).accounts; } catch (e) { return notify(e.message, 'err'); } if (!accts.length) return notify('Connect an email account under Settings first.', 'err');
          const sel = h('select', {class: 'sel', 'aria-label': 'From account'}, accts.map(a => h('option', {value: a.id}, a.address))), to = h('input', {type: 'text', placeholder: 'buyer addresses, comma-separated'}), subj = h('input', {type: 'text', value: `Response: ${st.name}`}), txt = h('textarea', {rows: 3});
          const ok = h('button', {class: 'btn primary', onclick: () => { mm.remove(); act('/mail', {account: sel.value, to: to.value.split(/[,;\s]+/).filter(Boolean), subject: subj.value, text: txt.value}, 'Sent and recorded as submitted'); }}, 'Send');
          const mm = modal('Submit by mail', h('div', {class: 'mbody'}, h('label', {class: 'f', style: 'margin-top:0'}, 'From'), sel, h('label', {class: 'f'}, 'To'), to, h('label', {class: 'f'}, 'Subject'), subj, h('label', {class: 'f'}, 'Message'), txt, h('div', {class: 'hint'}, 'The Word response, PDF, Excel matrix and the deck go as attachments; audited.'), h('div', {class: 'row', style: 'justify-content:flex-end;margin-top:12px'}, h('button', {class: 'btn', onclick: () => mm.remove()}, 'Cancel'), ok))); }}, icon('send'), 'Submit by mail')) : null));
  }
  if (['submitted', 'won', 'lost', 'withdrawn'].includes(st.status)) cards.push(h('div', {class: 'card', style: 'margin:0'}, h('h3', {}, 'Learn'),
    st.outcome ? h('div', {class: 'small', style: 'margin-top:6px'}, h('b', {}, `${st.outcome.result.toUpperCase()} - `), st.outcome.feedback || 'no feedback recorded', st.outcome.promoted && st.outcome.promoted.length ? h('div', {class: 'muted'}, `${st.outcome.promoted.length} answers promoted into the library (audited).`) : null) : h('div', {class: 'small muted', style: 'margin-top:6px'}, 'Record the outcome; the answers of a won response become reusable library items.'),
    canEdit ? h('div', {class: 'row', style: 'margin-top:10px;gap:6px'}, ['won', 'lost', 'withdrawn'].map(r => h('button', {class: 'btn sm' + (r === 'won' ? ' primary' : ''), onclick: () => { const fb = h('textarea', {rows: 4, placeholder: 'The buyer\'s feedback, as given'});
      const ok = h('button', {class: 'btn primary', onclick: () => { mm.remove(); act('/outcome', {result: r, feedback: fb.value}, 'Outcome recorded'); }}, 'Record');
      const mm = modal(`Outcome: ${r}`, h('div', {class: 'mbody'}, h('label', {class: 'f', style: 'margin-top:0'}, 'Buyer feedback'), fb, h('div', {class: 'row', style: 'justify-content:flex-end;margin-top:12px'}, h('button', {class: 'btn', onclick: () => mm.remove()}, 'Cancel'), ok))); }}, r.charAt(0).toUpperCase() + r.slice(1)))) : null));
  if (!cards.length) cards.push(h('div', {class: 'card', style: 'margin:0'}, h('div', {class: 'stack'}, [80, 65, 72, 50].map(w => h('i', {class: 'sk', style: `width:${w}%;height:12px`}))), h('div', {class: 'small muted', style: 'margin-top:8px'}, 'The requirements appear here when Relay has read the pack.')));
  const feed = h('div', {class: 'feed'});
  api(`/api/rfp/${id}/activity?after=0`).then(evs => { const keep = evs.filter(e => e.kind !== 'tool' && e.kind !== 'result').slice(-10);
    feed.replaceChildren(...(keep.length ? keep.map(e => h('div', {class: 'fi'}, h('span', {class: 'ft'}, clock(e.ts)), h('span', {}, String(e.text || (e.kind === 'start' ? 'Relay started' : e.kind === 'done' ? `Finished: ${e.turns || 0} steps, ${usd(e.cost_usd)}` : e.kind))))) : [h('div', {class: 'muted small'}, 'Nothing yet.')])); }).catch(() => {});
  main.replaceChildren(h('div', {class: 'page', id: 'rfppage', 'data-id': id},
    pageHead({crumbs: [['Home', '#/'], ['RFP & bid response', '#/rfp'], [st.name]], eyebrow: brandName() + ' - RFP & bid response', title: st.name, promise: [st.buyer ? `Buyer: ${st.buyer}` : null, st.deadline ? `Deadline: ${st.deadline}` : null].filter(Boolean).join(' - ') || st.notes,
      actions: h('div', {class: 'row'}, rfpPill(st.status), st.owner_name ? h('span', {class: 'small muted'}, 'started by ' + st.owner_name) : null)}),
    rfpJourney(RFP_STEP[st.status] ?? 0), banner,
    h('div', {class: 'g-side'},
      h('div', {class: 'stack'}, ...cards, h('div', {class: 'card', style: 'margin:0'}, h('div', {class: 'card-head'}, h('h3', {}, 'Activity'), h('span', {class: 'sp'}), running ? h('span', {class: 'pill run'}, 'Working') : null), feed)),
      h('div', {class: 'stack'},
        h('div', {class: 'card', style: 'margin:0'}, h('div', {class: 'card-head'}, h('h3', {}, 'The pack'), h('span', {class: 'sp'}), h('span', {class: 'small muted'}, `${st.attachments.filter(a => a.read).length} of ${st.attachments.length} read`)),
          h('div', {class: 'stack', style: 'gap:6px'}, st.attachments.map(a => h('div', {class: 'arow', style: 'flex-wrap:wrap'}, h('span', {class: 'aico'}, icon('file')), h('div', {class: 'grow', style: 'min-width:0'}, h('a', {class: 'an', href: `/api/rfp/${id}/file/${encodeURIComponent(a.name)}`, target: '_blank', rel: 'noopener'}, a.name), h('div', {class: 'small muted'}, `${a.kind} - ${size(a.bytes)}${a.pages ? ' - ' + a.pages + (a.kind === 'deck' ? ' slides' : ' pages') : ''}`)), a.read ? h('span', {class: 'tag ok'}, 'Read') : h('span', {class: 'tag'}, 'Waiting'),
            a.text ? h('div', {class: 'abody'}, h('details', {class: 'more'}, h('summary', {}, 'What Relay read'), h('pre', {class: 'atext'}, a.text))) : null))),
          h('div', {class: 'hint'}, 'The pack stays inside your workspace; it never seeds another workspace\'s library.')),
        h('div', {class: 'card', style: 'margin:0'}, h('h3', {}, 'Named people'), h('div', {class: 'stack small', style: 'gap:4px;margin-top:6px'}, [['decider', 'Go / no-go and submit'], ['technical', 'Technical review'], ['commercial', 'Commercial review'], ['legal', 'Legal review']].map(([k, l]) => h('div', {}, h('b', {}, l + ': '), st.people_names[k] || st.owner_name || 'the owner')))),
        h('div', {class: 'card', style: 'margin:0'}, h('h3', {}, 'Your confirmations'), h('div', {class: 'stack', style: 'gap:6px'}, [['Requirements', st.requirements_confirmed], ['Go / no-go', st.gonogo && st.gonogo.decision === 'go' ? st.gonogo : null], ['Matrix', st.matrix_confirmed], ['Price', st.price_confirmed], ['Submit', st.submit_accepted]].map(([l, c]) => h('div', {class: 'row', style: 'flex-wrap:nowrap'}, c ? h('span', {class: 'proven'}, icon('check')) : h('span', {class: 'faint'}, '○'), h('span', {class: c ? '' : 'muted'}, l), h('span', {class: 'spacer'}), h('span', {class: 'small muted'}, c ? `${c.by} - ${when(c.when)}` : 'waiting'))))),
        h('div', {class: 'row'}, h('a', {class: 'btn sm', href: '#/rfp'}, 'All responses'), h('a', {class: 'btn sm', href: '#/validate'}, 'Validation queue'), h('a', {class: 'btn sm', href: `#/studio?type=proposal&module=rfp`}, 'Deck in the studio'),
          canEdit && !running ? h('button', {class: 'btn sm ghost danger', onclick: async () => { if (await confirmBox(`Remove "${st.name}"?`, 'The pack, the requirements, the matrix and the builds are deleted; open checkpoints are withdrawn.')) { try { await api('/api/rfp/' + id, {method: 'DELETE'}); notify('Removed', 'ok'); location.hash = '#/rfp'; } catch (e) { notify(e.message, 'err'); } } }}, 'Remove') : null)))));
  document.title = `${st.name} - RFP - ${S.brand ? S.brand.full : 'RELAY by PASDACS'}`;
  if (running) S.rfpTimer = setTimeout(() => { if (location.hash.startsWith('#/rfp/' + id)) renderRfpItem(id); }, 2500);
}
