/* ---------------- Proposals, decks & documents — the consulting studio (P11). Brief → Outline → Draft → Check → Review → Final:
   the brief with its sources goes in, Relay proposes an outline a person reorders / cuts / confirms, drafts the deck or document with
   every figure sourced, the app builds and checks it, a person reviews the HTML twin and accepts the final — then files or sends it.
   Routes #/studio (brief + my items) and #/studio/<id>. ---------------- */
const STUDIO_STEPS = [['Brief', 'what, for whom, by when'], ['Outline', 'the story line, confirmed'], ['Draft', 'every figure sourced'], ['Check', 'numbers, references, style'], ['Review', 'comments in place'], ['Final', 'filed or sent, with approval']];
const STUDIO_PILL = {queued: ['Queued', 'run'], outlining: ['Relay is outlining', 'run'], awaiting_outline: ['Your turn: the outline', 'you'], drafting: ['Relay is drafting', 'run'], building: ['Building and checking', 'run'],
  awaiting_review: ['Your turn: review', 'you'], final: ['Final', 'ok'], error: ['Needs attention', 'err']};
const STUDIO_STEP = {queued: 1, outlining: 1, awaiting_outline: 1, drafting: 2, building: 3, awaiting_review: 4, final: 5, error: 1};
const STUDIO_ACCEPT = '.docx,.xlsx,.csv,.pptx,.pdf,.png,.jpg,.jpeg,.webp,.txt,.md';
const DECK_LAYOUTS = ['title', 'bullets', 'two-column', 'table', 'chart', 'diagram', 'quote', 'image', 'closing'], DOC_BLOCKS = ['heading', 'paragraph', 'bullets', 'table', 'chart', 'diagram', 'quote', 'image'];
const studioPill = s => { const [t, c] = STUDIO_PILL[s] || [s, '']; return h('span', {class: 'pill ' + c}, t); };
const CHECK_PILL = {pass: ['Pass', 'ok'], warn: ['Warnings', 'warn'], fail: ['Fail', 'err']};
S.studioTimer = null;
S.studioTypes = {architecture: 'architecture', strategy: 'strategy', assess: 'proposal', delivery: 'steering', rfp: 'proposal'};   // module → deliverable type (the module pages' "Prepare the deck" link)

function renderStudio() {
  clearTimeout(S.studioTimer);
  const m = location.hash.match(/^#\/studio\/([\w-]+)/);
  return m ? renderStudioItem(m[1]) : renderStudioHome();
}
function studioJourney(cur) {
  return h('ol', {class: 'journey', 'aria-label': 'Studio steps'}, STUDIO_STEPS.map(([l, sub], i) => h('li', {class: (i < cur ? 'done ' : '') + (i === cur ? 'on' : '')},
    h('span', {class: 'dot'}, i < cur ? '✓' : ''), h('div', {class: 'jl'}, `${i + 1} ${l}`), h('div', {class: 'js'}, sub))));
}

/* ---------- the brief ---------- */
async function renderStudioHome() {
  const main = $('#main');
  main.replaceChildren(skel('page'));
  let d;
  try { d = await api('/api/studio'); } catch (e) { main.replaceChildren(h('div', {class: 'page'}, h('div', {class: 'note err'}, e.message))); return; }
  if (!location.hash.startsWith('#/studio')) return;
  const q = new URLSearchParams((location.hash.split('?')[1] || ''));
  const viewer = !d.can_create, src = d.sources || {};
  const preType = q.get('type') && d.types.some(t => t.id === q.get('type')) ? q.get('type') : 'proposal';
  const preModule = q.get('module') && (src.modules || []).some(m => m.id === q.get('module')) ? q.get('module') : null;
  const fromMod = preModule ? moduleById(preModule) : null;
  const title = h('input', {type: 'text', placeholder: fromMod ? `${fromMod.name}: deck for …` : 'e.g. Target architecture for Contoso Retail', value: fromMod ? `${fromMod.short || fromMod.name} — ` : ''});
  const type = h('select', {class: 'sel', 'aria-label': 'Deliverable type'}, d.types.map(t => h('option', {value: t.id, selected: t.id === preType}, `${t.label} (${t.kind === 'deck' ? 'PowerPoint' : 'Word'})`)));
  const audience = h('input', {type: 'text', placeholder: 'e.g. Steering committee'});
  const due = h('input', {type: 'date'});
  const template = h('select', {class: 'sel', 'aria-label': 'Template'}, [h('option', {value: 'relay'}, S.brand && S.brand.partner ? `${S.brand.full} (white-label, Powered by PASDACS Relay)` : 'RELAY house template'),
    h('option', {value: 'tenant', disabled: !d.templates.tenant}, d.templates.tenant ? `Your template (${[d.templates.names.pptx, d.templates.names.docx].filter(Boolean).join(', ')})` : 'Your template — none uploaded yet (Admin › Branding)')]);
  const brief = h('textarea', {rows: 5, placeholder: fromMod ? `What this ${fromMod.name.toLowerCase()} deck must achieve for the audience, and the decisions it should lead to.` : 'What must this deliverable achieve, for whom, and what should the reader decide or do afterwards?'});
  const picks = {dashboards: new Set(), starts: new Set(), rfps: new Set(), modules: new Set(preModule ? [preModule] : []), library: new Set(), practice: false};
  const pickList = (key, items, label, sub) => items.length ? h('details', {class: 'more', open: key === 'modules' && !!preModule}, h('summary', {}, `${label} (${items.length})`),
    h('div', {class: 'row', style: 'gap:6px;margin:4px 0 8px'}, items.map(x => { const cb = h('input', {type: 'checkbox', checked: picks[key].has(x.id)}); cb.onchange = () => cb.checked ? picks[key].add(x.id) : picks[key].delete(x.id);
      return h('label', {class: 'chk', title: sub ? sub(x) : ''}, cb, x.name || x.title); }))) : null;
  const practice = h('input', {type: 'checkbox'}); practice.onchange = () => { picks.practice = practice.checked; };
  const picked = [];
  const list = h('div', {class: 'stack', style: 'gap:8px'});
  const input = h('input', {type: 'file', multiple: true, accept: STUDIO_ACCEPT, style: 'display:none', 'aria-label': 'Attach files'});
  const show = () => list.replaceChildren(...picked.map((f, i) => h('div', {class: 'arow'}, h('span', {class: 'aico'}, icon('file')), h('div', {class: 'grow', style: 'min-width:0'}, h('div', {class: 'an'}, f.name), h('div', {class: 'small muted'}, size(f.size))),
    h('button', {class: 'iconbtn', type: 'button', 'aria-label': 'Remove ' + f.name, onclick: () => { picked.splice(i, 1); show(); }}, icon('x')))));
  const add = files => { for (const f of files) if (STUDIO_ACCEPT.includes('.' + (f.name.split('.').pop() || '').toLowerCase())) picked.push(f); else notify(`${f.name}: not a kind of file the studio reads`, 'err'); show(); };
  input.onchange = () => { add(input.files); input.value = ''; };
  const drop = h('div', {class: 'drop', role: 'button', tabindex: '0', 'aria-label': 'Add attachments', onclick: () => input.click(), onkeydown: e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); input.click(); } }},
    input, icon('download'), h('div', {}, h('b', {}, 'Drop source files here, or click to add')), h('div', {class: 'hint'}, 'Word, PDF, slides, spreadsheets, images — read by Relay and quotable as attachment:<file>'));
  drop.ondragover = e => { e.preventDefault(); drop.classList.add('over'); }; drop.ondragleave = () => drop.classList.remove('over');
  drop.ondrop = e => { e.preventDefault(); drop.classList.remove('over'); add(e.dataTransfer.files); };
  const bar = h('div', {class: 'bar'}, h('i'));
  const go = h('button', {class: 'btn primary', type: 'submit', disabled: viewer}, icon('play'), 'Brief the studio');
  const form = h('form', {class: 'card', style: 'margin:0'},
    h('div', {class: 'opts'}, h('div', {}, h('label', {class: 'f', style: 'margin-top:0'}, 'Title'), title), h('div', {}, h('label', {class: 'f', style: 'margin-top:0'}, 'Deliverable'), type)),
    h('div', {class: 'opts'}, h('div', {}, h('label', {class: 'f'}, 'Audience'), audience), h('div', {}, h('label', {class: 'f'}, 'Due'), due)),
    h('label', {class: 'f'}, 'Template'), template,
    h('label', {class: 'f'}, 'The brief'), brief,
    h('div', {style: 'margin-top:14px'}, h('div', {class: 'small', style: 'font-weight:600'}, 'Sources ', h('span', {class: 'muted', style: 'font-weight:400'}, '— the only facts Relay may quote; every figure links back to one')),
      pickList('dashboards', src.dashboards || [], 'Dashboards (measures with the values Power BI returned)', x => x.status),
      pickList('starts', src.starts || [], 'Starts (confirmed process, fields and plan)'),
      pickList('rfps', src.rfps || [], 'RFP responses (requirements, matrix, price)'),
      pickList('modules', src.modules || [], 'Module facts from the registry', x => x.pillar),
      pickList('library', src.library || [], 'Library items (past answers, case studies)', x => `${x.module || ''} ${x.buyer_type || ''}`),
      h('label', {class: 'chk', style: 'margin-top:6px'}, practice, 'Practice pulse — the Home KPIs of the last 30 days (hours, right first time, waiting)')),
    h('div', {style: 'margin-top:12px'}, drop), list,
    h('div', {class: 'row', style: 'margin-top:14px;gap:12px'}, h('span', {class: 'small muted'}, 'Relay proposes an outline first; nothing is drafted before you confirm it.'), h('span', {class: 'spacer'}), go),
    viewer ? h('div', {class: 'hint'}, 'Briefing the studio is for builders and leads; ask one to brief it for you.') : null, bar);
  form.onsubmit = e => {
    e.preventDefault();
    if (title.value.trim().length < 3) return toast(go, 'Give the deliverable a title.');
    if (brief.value.trim().length < 10) return toast(go, 'Say what it must achieve, in a sentence or two.');
    const fd = new FormData();
    fd.append('title', title.value); fd.append('type', type.value); fd.append('brief', brief.value); fd.append('audience', audience.value); fd.append('due', due.value); fd.append('template', template.value);
    fd.append('sources', JSON.stringify({dashboards: [...picks.dashboards], starts: [...picks.starts], rfps: [...picks.rfps], modules: [...picks.modules], library: [...picks.library], practice: picks.practice}));
    for (const f of picked) fd.append('files', f);
    bar.style.display = 'block'; go.disabled = true; go.lastChild.textContent = 'Uploading…';
    upload('/api/studio', fd, p => { $('i', bar).style.width = (100 * p) + '%'; }).then(r => { location.hash = '#/studio/' + r.id; })
      .catch(err => { go.disabled = false; go.lastChild.textContent = 'Brief the studio'; bar.style.display = 'none'; toast(go, err.message); });
  };
  main.replaceChildren(h('div', {class: 'page'},
    pageHead({crumbs: [['Home', '#/'], ['Studio']], eyebrow: brandName() + ' · Consulting services · Proposals, decks & documents', title: 'Every consulting deliverable, in your house style',
      promise: 'Proposal and submission decks, architecture decks, business cases, SoWs, steering and hand-over packs — drafted from Relay’s facts in your template, checked, reviewed and versioned. Nothing invented: a figure without a source fails the check.',
      actions: h('div', {class: 'row'}, h('a', {class: 'btn sm', href: '#/rfp'}, 'RFP & bid response'), h('a', {class: 'btn sm', href: '#/m/proposals'}, 'How it works'))}),
    studioJourney(0),
    h('div', {class: 'g-side'}, form,
      h('div', {class: 'stack'},
        h('div', {class: 'card', style: 'margin:0'}, h('h3', {}, 'Where you confirm'), h('div', {class: 'confirm', style: 'margin-top:8px'}, [['Outline', 'the story line before drafting'], ['Draft', 'every figure with its evidence'], ['Final', 'approval by a named owner before it is filed or sent']].map(([s, v]) => h('div', {}, h('span', {class: 'proven'}, icon('check')), h('span', {}, h('b', {}, s + ': '), v))))),
        h('div', {class: 'card', style: 'margin:0'}, h('h3', {}, 'The checks'), h('div', {class: 'rules', style: 'margin-top:8px'}, ['Numbers against their source', 'References real: a module, a record, an attachment or a library item', 'Nothing comes from another workspace', 'Contrast and alt text', 'House style: fonts, lengths, British spelling', 'No placeholder text'].map(t => h('div', {}, icon('check'), t)))),
        d.templates.house_style ? h('div', {class: 'card', style: 'margin:0'}, h('h3', {}, 'House style'), h('p', {class: 'small muted', style: 'white-space:pre-wrap'}, d.templates.house_style)) : null,
        h('div', {class: 'card', style: 'margin:0'}, h('div', {class: 'card-head'}, h('h3', {}, 'Your deliverables'), h('span', {class: 'sp'}), h('span', {class: 'small muted'}, String(d.items.length))),
          d.items.length ? h('div', {class: 'stack', style: 'gap:6px'}, d.items.slice(0, 15).map(s => h('a', {href: '#/studio/' + s.id, class: 'wait'}, h('div', {class: 'wt'}, h('b', {}, s.name), h('small', {}, `${s.type_label} · ${ago(s.updated || s.created)}`)), studioPill(s.status))))
            : h('div', {class: 'muted small', style: 'padding:6px 0'}, 'Nothing briefed yet.'))))));
  document.title = `Studio · ${S.brand ? S.brand.full : 'RELAY by PASDACS'}`;
}

/* ---------- the outline editor ---------- */
function studioOutlineEditor(st, id, canEdit) {
  const deck = st.deliverable_kind === 'deck', layouts = deck ? DECK_LAYOUTS : DOC_BLOCKS, o = st.outline, unit = deck ? 'slide' : 'block';
  const sections = o.sections.map(s => ({title: s.title, units: s.units.map(u => ({...u}))}));
  let story = o.story, dirty = false;
  const box = h('div', {class: 'stack'});
  const save = async () => { try { await api(`/api/studio/${id}/outline`, {method: 'PUT', json: {story, sections}}); dirty = false; notify('Outline saved', 'ok'); renderStudioItem(id); } catch (e) { notify(e.message, 'err'); } };
  const draw = () => {
    const rows = [];
    sections.forEach((s, si) => {
      rows.push(h('div', {class: 'row', style: 'margin-top:8px'}, h('b', {}, s.title), h('span', {class: 'small muted'}, `${s.units.length} ${unit}${s.units.length === 1 ? '' : 's'}`), h('span', {class: 'spacer'}),
        canEdit ? [h('button', {class: 'iconbtn', type: 'button', 'aria-label': 'Move section up', disabled: !si, onclick: () => { sections.splice(si - 1, 0, sections.splice(si, 1)[0]); dirty = true; draw(); }}, '↑'),
          h('button', {class: 'iconbtn', type: 'button', 'aria-label': 'Move section down', disabled: si === sections.length - 1, onclick: () => { sections.splice(si + 1, 0, sections.splice(si, 1)[0]); dirty = true; draw(); }}, '↓'),
          h('button', {class: 'btn sm ghost', type: 'button', onclick: async () => { const t = await askText('Rename the section', {label: 'Section title', value: s.title, rows: 1, required: true, ok: 'Rename'}); if (t) { s.title = t; dirty = true; draw(); } }}, 'Rename'),
          h('button', {class: 'btn sm ghost danger', type: 'button', onclick: () => { sections.splice(si, 1); dirty = true; draw(); }}, 'Cut')] : null));
      s.units.forEach((u, ui) => rows.push(h('div', {class: 'nextrow', style: 'margin-left:14px'},
        h('span', {class: 'tag'}, u.layout || unit),
        h('div', {class: 'grow', style: 'min-width:0'}, h('b', {}, u.title), u.intent ? h('div', {class: 'small muted'}, u.intent) : null, u.sources.length ? h('div', {class: 'row', style: 'gap:4px;margin-top:3px'}, u.sources.map(r => h('span', {class: 'chipx mono', title: 'source'}, r))) : null),
        canEdit ? h('div', {class: 'row', style: 'gap:2px;flex:none'},
          h('button', {class: 'iconbtn', type: 'button', 'aria-label': `Move ${unit} up`, disabled: !ui, onclick: () => { s.units.splice(ui - 1, 0, s.units.splice(ui, 1)[0]); dirty = true; draw(); }}, '↑'),
          h('button', {class: 'iconbtn', type: 'button', 'aria-label': `Move ${unit} down`, disabled: ui === s.units.length - 1, onclick: () => { s.units.splice(ui + 1, 0, s.units.splice(ui, 1)[0]); dirty = true; draw(); }}, '↓'),
          h('button', {class: 'btn sm ghost', type: 'button', onclick: () => editUnit(s, u)}, 'Edit'),
          h('button', {class: 'btn sm ghost danger', type: 'button', 'aria-label': `Cut ${u.title}`, onclick: () => { s.units.splice(ui, 1); dirty = true; draw(); }}, 'Cut')) : null)));
      if (canEdit) rows.push(h('div', {style: 'margin-left:14px'}, h('button', {class: 'btn sm', type: 'button', onclick: () => editUnit(s, null)}, icon('plus'), `Add a ${unit}`)));
    });
    box.replaceChildren(
      h('div', {class: 'note'}, h('b', {}, 'Story line: '), story),
      ...rows,
      canEdit ? h('div', {class: 'row', style: 'margin-top:10px;gap:8px'}, h('button', {class: 'btn sm', type: 'button', onclick: async () => { const t = await askText('Add a section', {label: 'Section title', rows: 1, required: true, ok: 'Add'}); if (t) { sections.push({title: t, units: []}); dirty = true; draw(); } }}, icon('plus'), 'Add a section'),
        h('button', {class: 'btn sm', type: 'button', onclick: async () => { const t = await askText('Edit the story line', {label: 'Story line', value: story, rows: 4, ok: 'Save'}); if (t !== null) { story = t; dirty = true; draw(); } }}, 'Edit the story line'),
        h('span', {class: 'spacer'}), dirty ? h('button', {class: 'btn sm primary', type: 'button', onclick: save}, 'Save changes') : h('span', {class: 'small muted'}, 'Saved')) : null);
  };
  const editUnit = (s, u) => {
    const t = h('input', {type: 'text', value: u ? u.title : '', placeholder: `${unit} title`}), lay = h('select', {class: 'sel', 'aria-label': 'Layout'}, layouts.map(l => h('option', {value: l, selected: u && u.layout === l}, l)));
    const intent = h('textarea', {rows: 2, value: u ? u.intent : '', placeholder: 'what it says and which source it draws on'}), srcs = h('input', {type: 'text', value: u ? u.sources.join(', ') : '', placeholder: 'record:assess#estate, dashboard:<id>/<measure>, module:<id>'});
    const ok = h('button', {class: 'btn primary', onclick: () => { if (!t.value.trim()) return notify('Give it a title.', 'err'); const row = {title: t.value.trim(), layout: lay.value, intent: intent.value.trim(), sources: srcs.value.split(',').map(x => x.trim()).filter(Boolean)}; if (u) Object.assign(u, row); else s.units.push(row); dirty = true; mm.remove(); draw(); }}, u ? 'Change' : 'Add');
    const mm = modal(u ? `Edit “${u.title}”` : `Add a ${unit} to “${s.title}”`, h('div', {class: 'mbody'}, h('label', {class: 'f', style: 'margin-top:0'}, 'Title'), t, h('label', {class: 'f'}, 'Layout'), lay, h('label', {class: 'f'}, 'Intent'), intent, h('label', {class: 'f'}, 'Sources'), srcs,
      h('div', {class: 'row', style: 'justify-content:flex-end;margin-top:12px'}, h('button', {class: 'btn', onclick: () => mm.remove()}, 'Cancel'), ok)));
  };
  draw();
  return box;
}

/* ---------- the check report ---------- */
function studioReport(st) {
  const r = st.report;
  if (!r) return h('div', {class: 'muted small'}, 'No check report yet.');
  return h('div', {class: 'stack', style: 'gap:8px'},
    h('div', {class: 'row small', style: 'gap:12px'}, h('b', {}, r.ok ? 'Every check passed' : `${r.counts.fails} problem${r.counts.fails === 1 ? '' : 's'}`), r.counts.warnings ? h('span', {class: 'muted'}, `${r.counts.warnings} warning${r.counts.warnings === 1 ? '' : 's'}`) : null, h('span', {class: 'muted'}, `${r.counts.refs} source reference${r.counts.refs === 1 ? '' : 's'} · template ${r.template}`)),
    ...r.checks.map(c => { const [t, cls] = CHECK_PILL[c.status] || [c.status, '']; return h('div', {class: 'nextrow', style: 'flex-direction:column;gap:4px'},
      h('div', {class: 'row', style: 'gap:8px'}, h('span', {class: 'pill plain ' + cls}, t), h('b', {}, c.label), h('span', {class: 'small muted'}, c.summary)),
      c.items.length ? h('ul', {class: 'small', style: 'margin:0;padding-left:18px'}, c.items.slice(0, 12).map(i => h('li', {class: i.level === 'fail' ? '' : 'muted'}, i.text)), c.items.length > 12 ? h('li', {class: 'muted'}, `… and ${c.items.length - 12} more`) : null) : null); }));
}

/* ---------- the item page ---------- */
async function renderStudioItem(id) {
  const main = $('#main');
  if (!$('#studiopage') || $('#studiopage').dataset.id !== id) main.replaceChildren(skel('page'));
  let st;
  try { st = await api('/api/studio/' + id); } catch (e) { main.replaceChildren(h('div', {class: 'page'}, h('div', {class: 'card empty'}, h('h3', {}, 'No such deliverable'), h('p', {}, e.message), h('a', {class: 'btn', href: '#/studio'}, 'Studio')))); return; }
  if (!location.hash.startsWith('#/studio/' + id)) return;
  const canEdit = st.access && st.access.can_edit, running = ['queued', 'outlining', 'drafting', 'building'].includes(st.status), deck = st.deliverable_kind === 'deck', unit = deck ? 'slide' : 'block';
  const cur = STUDIO_STEP[st.status] ?? 0;
  if (!S.studioTab || !['preview', 'check', 'yaml', 'comments', 'files'].includes(S.studioTab)) S.studioTab = 'preview';
  const act = async (path, body, okMsg, method) => { try { await api(`/api/studio/${id}${path}`, {method: method || 'POST', json: body || {}}); if (okMsg) notify(okMsg, 'ok'); renderStudioItem(id); } catch (e) { notify(e.message, 'err'); } };
  const sendBack = (path, title, hint) => {
    const ta = h('textarea', {rows: 4, placeholder: hint});
    const ok = h('button', {class: 'btn primary', onclick: () => { if (!ta.value.trim()) return notify('Say what to change.', 'err'); mm.remove(); act(path, {comment: ta.value}, 'Sent back — Relay works on it'); }}, 'Send back');
    const mm = modal(title, h('div', {class: 'mbody'}, h('label', {class: 'f', style: 'margin-top:0'}, 'What should change?'), ta, h('div', {class: 'row', style: 'justify-content:flex-end;margin-top:12px'}, h('button', {class: 'btn', onclick: () => mm.remove()}, 'Cancel'), ok)));
  };
  const banner = st.status === 'error' ? h('div', {class: 'banner err'}, h('div', {class: 'ic'}, icon('alert')), h('div', {class: 'txt'}, h('div', {class: 't'}, 'Relay could not finish this step.'), h('div', {class: 'd'}, st.error || '')), canEdit ? h('button', {class: 'btn primary', onclick: () => act('/retry', {}, 'Queued again')}, 'Retry') : null)
    : running ? h('div', {class: 'banner run'}, h('div', {class: 'ic'}, h('span', {class: 'spin'})), h('div', {class: 'txt'}, h('div', {class: 't'}, st.status === 'queued' ? (st.position ? `${st.position} job(s) ahead of this one.` : 'Starting next…') : st.status === 'building' ? 'Building the deliverable and running the checks.' : st.status === 'outlining' ? 'Relay is reading the sources and proposing an outline.' : 'Relay is drafting — every figure with its source.'),
      h('div', {class: 'd'}, st.running_since ? `Running for ${dur(Date.now() - st.running_since * 1000)} · one agent, one job at a time` : 'The page refreshes itself.')))
    : st.status === 'awaiting_outline' ? h('div', {class: 'banner you'}, h('div', {class: 'ic'}, icon('info')), h('div', {class: 'txt'}, h('div', {class: 't'}, 'Your turn: the outline.'), h('div', {class: 'd'}, `Reorder, cut or add ${unit}s, then confirm it — or send it back with a comment. Nothing is drafted before you confirm.`)))
    : st.status === 'awaiting_review' ? h('div', {class: 'banner you'}, h('div', {class: 'ic'}, icon('info')), h('div', {class: 'txt'}, h('div', {class: 't'}, `Your turn: review draft v${st.latest ? st.latest.v : ''}.`), h('div', {class: 'd'}, st.latest && !st.latest.ok ? `The checks still find ${st.latest.fails} problem(s): look at the Check tab before accepting.` : 'Look at the preview, comment in place, then accept it as final or send it back.')))
    : st.status === 'final' ? h('div', {class: 'banner ok'}, h('div', {class: 'ic'}, icon('check')), h('div', {class: 'txt'}, h('div', {class: 't'}, `Final: v${st.final.version}, accepted by ${st.final.by_name || 'someone'} · ${when(st.final.when)}.`), h('div', {class: 'd'}, 'Download it, file it to SharePoint, OneDrive or Drive (with a write approval), or send it by mail. Later edits re-run the checks.')))
    : null;
  // ---- main card
  let mainCard;
  if (st.status === 'awaiting_outline' && st.outline) {
    mainCard = h('div', {class: 'card', style: 'margin:0'}, h('div', {class: 'card-head'}, h('h3', {}, 'Outline'), h('span', {class: 'sp'}), h('span', {class: 'small muted'}, `${st.outline.counts.sections} sections · ${st.outline.counts.units} ${unit}s`)),
      st.outline_summary ? h('div', {class: 'note'}, h('b', {}, 'Relay: '), st.outline_summary) : null,
      studioOutlineEditor(st, id, canEdit),
      canEdit ? h('div', {class: 'row', style: 'border-top:1px solid var(--line);padding-top:12px;margin-top:14px'}, h('span', {class: 'small muted'}, 'Is this the story you want told?'), h('span', {class: 'spacer'}),
        h('button', {class: 'btn', onclick: () => sendBack('/outline/send-back', 'Send the outline back', 'e.g. “Lead with the business case, not the estate; add a slide on risks”')}, 'Send back'),
        h('button', {class: 'btn primary', onclick: () => act('/outline/confirm', {}, 'Outline confirmed — Relay is drafting')}, icon('check'), 'Confirm the outline')) : null);
  } else if (st.latest) {
    const v = st.latest, tabs = [['preview', 'Preview'], ['check', 'Check'], ['comments', `Comments${(st.comments || []).filter(c => c.stage === 'review').length ? ' · ' + (st.comments || []).filter(c => c.stage === 'review').length : ''}`], ['yaml', st.spec_name], ['files', 'Files']];
    const body = S.studioTab === 'preview' ? h('div', {class: 'stack'}, h('iframe', {src: v.preview, title: `Preview of ${st.name} v${v.v}`, sandbox: '', style: 'width:100%;height:640px;border:1px solid var(--line);border-radius:8px;background:#fff'}),
        h('div', {class: 'small muted'}, `The HTML twin of v${v.v}: the same content as the ${deck ? 'PowerPoint' : 'Word'} file; every figure links to its source. `, v.links.pdf ? h('a', {href: v.links.pdf, target: '_blank', rel: 'noopener'}, 'Open the PDF') : 'PDF: the agent was not available to draw it.'))
      : S.studioTab === 'check' ? studioReport(st)
      : S.studioTab === 'yaml' ? (() => { const ta = h('textarea', {rows: 22, class: 'mono', style: 'width:100%;font-size:12px', readonly: !canEdit}, st.spec); return h('div', {class: 'stack'}, ta,
          canEdit && !running ? h('div', {class: 'row'}, h('span', {class: 'small muted'}, 'Edit by hand if you must — the checks run again and the review reopens.'), h('span', {class: 'spacer'}), h('button', {class: 'btn sm primary', onclick: () => act('/yaml', {yaml: ta.value}, 'Saved — rebuilding and checking', 'PUT')}, 'Save and re-check')) : null); })()
      : S.studioTab === 'comments' ? (() => { const n = h('input', {type: 'number', min: 1, style: 'max-width:90px', placeholder: unit}), t = h('input', {type: 'text', placeholder: `What should change on this ${unit}?`, style: 'flex:1'});
          const cs = (st.comments || []).filter(c => c.stage === 'review');
          return h('div', {class: 'stack'}, cs.length ? h('div', {class: 'stack', style: 'gap:6px'}, cs.map(c => h('div', {class: 'nextrow'}, h('span', {class: 'tag'}, c.unit ? `${unit} ${c.unit}` : `v${c.version || ''}`), h('div', {class: 'grow'}, c.text, h('div', {class: 'small muted'}, `${c.who_name || 'someone'} · ${when(c.when)}` + (c.sent_back ? ' · sent back' : '')))))) : h('div', {class: 'muted small'}, 'No comments yet.'),
            canEdit ? h('div', {class: 'row'}, n, t, h('button', {class: 'btn sm', onclick: () => { if (!t.value.trim()) return notify('Write the comment.', 'err'); act('/comments', {unit: n.value ? Number(n.value) : null, text: t.value}, 'Comment added'); }}, 'Add')) : null,
            h('div', {class: 'small muted'}, 'Comments travel with the next send-back; Relay revises with them.')); })()
      : h('div', {class: 'stack', style: 'gap:8px'}, st.builds.slice().reverse().map(b => h('div', {class: 'nextrow'}, h('span', {class: 'tag ' + (b.ok ? 'ok' : 'warn')}, `v${b.v}`), h('div', {class: 'grow'}, h('b', {}, Object.entries(b.counts).filter(([, x]) => x).map(([k, x]) => `${x} ${k}`).join(' · ') || 'build'), h('div', {class: 'small muted'}, `${when(b.when)} · ${b.ok ? 'checks passed' : b.fails + ' problem(s)'} · template ${b.template}` + (b.partner ? ' · Powered by PASDACS Relay' : ''))),
          h('div', {class: 'row', style: 'gap:6px'}, Object.entries(b.links).map(([k, href]) => h('a', {class: 'btn sm', href, target: k === 'twin' ? '_blank' : null, rel: 'noopener'}, icon('download'), k.toUpperCase()))))));
    mainCard = h('div', {class: 'card', style: 'margin:0'},
      h('div', {class: 'row', style: 'margin-bottom:10px'}, h('div', {class: 'tabs', role: 'tablist', style: 'margin:0;border:0'}, tabs.map(([k, l]) => h('a', {href: '#', role: 'tab', class: S.studioTab === k ? 'on' : '', 'aria-selected': String(S.studioTab === k), onclick: e => { e.preventDefault(); S.studioTab = k; renderStudioItem(id); }}, l))), h('span', {class: 'spacer'}), h('span', {class: 'small muted'}, `v${v.v} · ${v.ok ? 'checks passed' : v.fails + ' problem(s)'}`)),
      st.draft_summary && S.studioTab === 'preview' ? h('div', {class: 'note'}, h('b', {}, 'Relay: '), st.draft_summary) : null,
      body,
      st.status === 'awaiting_review' && canEdit ? h('div', {class: 'row', style: 'border-top:1px solid var(--line);padding-top:12px;margin-top:14px'}, h('span', {class: 'small muted'}, 'Is this ready to go out?'), h('span', {class: 'spacer'}),
        h('button', {class: 'btn', onclick: () => sendBack('/final/send-back', `Send draft v${v.v} back`, 'e.g. “Shorten section 2; the effort chart should be per module”')}, 'Send back'),
        h('button', {class: 'btn primary', onclick: () => act('/final/accept', {}, 'Accepted as final — signed and logged')}, icon('check'), 'Accept as final')) : null);
  } else {
    mainCard = h('div', {class: 'card', style: 'margin:0'}, h('div', {class: 'stack'}, [80, 65, 72, 50].map(w => h('i', {class: 'sk', style: `width:${w}%;height:12px`}))), h('div', {class: 'small muted', style: 'margin-top:8px'}, 'The outline appears here when Relay has read the brief and the sources.'));
  }
  // ---- final actions: file to a connection, send by mail
  const fileTo = async () => {
    let conns = [];
    try { conns = (await api('/api/connections')).connections.filter(c => c.scope === 'write' && c.enabled !== false); } catch (e) { return notify(e.message, 'err'); }
    if (!conns.length) return notify('No connection may write yet: set a SharePoint, OneDrive or Drive connection to “Read & write — with approval” under Connections.', 'err');
    const sel = h('select', {class: 'sel', 'aria-label': 'Connection'}, conns.map(c => h('option', {value: c.id}, `${c.name} · ${c.label}`))), fold = h('input', {type: 'text', placeholder: 'Folder, e.g. Clients/Contoso/Proposals'});
    const ok = h('button', {class: 'btn primary', onclick: async () => { try { const r = await api(`/api/studio/${id}/file`, {json: {connection: sel.value, folder: fold.value}}); mm.remove(); notify('A write approval is waiting in the Validation queue — nothing is filed until it is accepted', 'ok'); renderStudioItem(id); } catch (e) { notify(e.message, 'err'); } }}, 'Ask for the write approval');
    const mm = modal('File the final', h('div', {class: 'mbody'}, h('label', {class: 'f', style: 'margin-top:0'}, 'Connection (write with approval)'), sel, h('label', {class: 'f'}, 'Folder'), fold, h('div', {class: 'hint'}, 'The file is uploaded only when a named person accepts the write.'), h('div', {class: 'row', style: 'justify-content:flex-end;margin-top:12px'}, h('button', {class: 'btn', onclick: () => mm.remove()}, 'Cancel'), ok)));
  };
  const sendMail = async () => {
    let accts = [];
    try { accts = (await api('/api/email/accounts')).accounts; } catch (e) { return notify(e.message, 'err'); }
    if (!accts.length) return notify('Connect an email account under Settings first.', 'err');
    const sel = h('select', {class: 'sel', 'aria-label': 'From account'}, accts.map(a => h('option', {value: a.id}, `${a.address} (${a.kind})`))), to = h('input', {type: 'text', placeholder: 'recipients, comma-separated'}), subj = h('input', {type: 'text', value: st.name}), txt = h('textarea', {rows: 3, placeholder: 'A line or two for the recipient'});
    const ok = h('button', {class: 'btn primary', onclick: async () => { try { await api(`/api/studio/${id}/mail`, {json: {account: sel.value, to: to.value.split(/[,;\s]+/).filter(Boolean), subject: subj.value, text: txt.value}}); mm.remove(); notify('Sent', 'ok'); renderStudioItem(id); } catch (e) { notify(e.message, 'err'); } }}, 'Send');
    const mm = modal('Send the final by mail', h('div', {class: 'mbody'}, h('label', {class: 'f', style: 'margin-top:0'}, 'From'), sel, h('label', {class: 'f'}, 'To'), to, h('label', {class: 'f'}, 'Subject'), subj, h('label', {class: 'f'}, 'Message'), txt, h('div', {class: 'hint'}, `The ${deck ? 'PowerPoint' : 'Word'} file and the PDF go as attachments; the send is audited.`), h('div', {class: 'row', style: 'justify-content:flex-end;margin-top:12px'}, h('button', {class: 'btn', onclick: () => mm.remove()}, 'Cancel'), ok)));
  };
  const finalCard = st.status === 'final' && st.latest ? h('div', {class: 'card', style: 'margin:0'}, h('h3', {}, 'Final'), h('div', {class: 'stack', style: 'gap:8px;margin-top:8px'},
      h('div', {class: 'row', style: 'gap:6px'}, Object.entries(st.latest.links).filter(([k]) => k !== 'twin').map(([k, href]) => h('a', {class: 'btn sm primary', href}, icon('download'), k.toUpperCase()))),
      canEdit ? h('div', {class: 'row', style: 'gap:6px'}, h('button', {class: 'btn sm', onclick: fileTo}, icon('folder'), 'File to…'), h('button', {class: 'btn sm', onclick: sendMail}, icon('send'), 'Send by mail')) : null,
      (st.filed || []).length ? h('div', {class: 'stack', style: 'gap:6px'}, h('b', {class: 'small'}, 'Filing'), (st.filed || []).slice().reverse().map(f => h('div', {class: 'nextrow'},
        h('span', {class: 'tag ' + ({filed: 'ok', waiting: 'warn'}[f.status] || 'err')}, f.status_label || 'Waiting for the write approval'),
        h('div', {class: 'grow small'}, h('b', {}, f.target), ` → ${f.connection_name}`, h('div', {class: 'muted'}, `v${f.version} · asked by ${f.by_name || 'someone'} · ${when(f.requested)}` + (f.decided_by_name ? ` · decided by ${f.decided_by_name}` : '')
          + (f.converted ? ' · converted to a Google format' : '') + (f.note && f.status !== 'filed' ? ` · ${f.note}` : ''))),
        f.url ? h('a', {class: 'btn sm', href: f.url, target: '_blank', rel: 'noopener', 'aria-label': `Open ${f.target} on ${f.connection_name}`}, 'Open') : null))) : null,
      (st.sent || []).length ? h('div', {class: 'small'}, h('b', {}, 'Sent: '), (st.sent || []).map(s => `${s.to.join(', ')} · ${when(s.when)}`).join(' · ')) : null)) : null;
  const feed = h('div', {class: 'feed'});
  api(`/api/studio/${id}/activity?after=0`).then(evs => { const keep = evs.filter(e => e.kind !== 'tool' && e.kind !== 'result').slice(-10);
    feed.replaceChildren(...(keep.length ? keep.map(e => h('div', {class: 'fi'}, h('span', {class: 'ft'}, clock(e.ts)), h('span', {}, String(e.text || (e.kind === 'start' ? 'Relay started' : e.kind === 'done' ? `Finished: ${e.turns || 0} steps, ${usd(e.cost_usd)}` : e.kind))))) : [h('div', {class: 'muted small'}, 'Nothing yet.')])); }).catch(() => {});
  const srcFile = n => `/api/studio/${id}/source/${encodeURIComponent(n)}`;
  main.replaceChildren(h('div', {class: 'page', id: 'studiopage', 'data-id': id},
    pageHead({crumbs: [['Home', '#/'], ['Studio', '#/studio'], [st.name]], eyebrow: brandName() + ' · Studio · ' + st.type_label, title: st.name, promise: st.brief,
      actions: h('div', {class: 'row'}, studioPill(st.status), st.owner_name ? h('span', {class: 'small muted'}, 'briefed by ' + st.owner_name) : null)}),
    studioJourney(cur), banner,
    h('div', {class: 'g-side'},
      h('div', {class: 'stack'}, mainCard, finalCard, h('div', {class: 'card', style: 'margin:0'}, h('div', {class: 'card-head'}, h('h3', {}, 'Activity'), h('span', {class: 'sp'}), running ? h('span', {class: 'pill run'}, 'Working') : null), feed)),
      h('div', {class: 'stack'},
        h('div', {class: 'card', style: 'margin:0'}, h('div', {class: 'card-head'}, h('h3', {}, 'The brief'), h('span', {class: 'sp'}), h('span', {class: 'small muted'}, deck ? 'PowerPoint' : 'Word')),
          h('div', {class: 'small'}, h('b', {}, 'Audience: '), st.audience || '—'), h('div', {class: 'small'}, h('b', {}, 'Due: '), st.due || '—'), h('div', {class: 'small'}, h('b', {}, 'Template: '), st.template === 'tenant' ? 'your template' : (S.brand && S.brand.partner ? `${S.brand.full} · Powered by PASDACS Relay` : 'RELAY'))),
        h('div', {class: 'card', style: 'margin:0'}, h('div', {class: 'card-head'}, h('h3', {}, 'Sources'), h('span', {class: 'sp'}), h('span', {class: 'small muted'}, String((st.sources_list || []).length))),
          h('div', {class: 'stack', style: 'gap:4px'}, (st.sources_list || []).filter(n => n !== 'brand.json').map(n => h('a', {class: 'small', href: srcFile(n), target: '_blank', rel: 'noopener'}, n))),
          h('div', {class: 'hint'}, 'The only facts Relay may quote. Sources stay inside your tenant.')),
        h('div', {class: 'card', style: 'margin:0'}, h('h3', {}, 'Your confirmations'), h('div', {class: 'stack', style: 'gap:6px'},
          [['Outline', st.outline_confirmed], ['Final', st.final]].map(([l, c]) => h('div', {class: 'row', style: 'flex-wrap:nowrap'}, c ? h('span', {class: 'proven'}, icon('check')) : h('span', {class: 'faint'}, '○'), h('span', {class: c ? '' : 'muted'}, l), h('span', {class: 'spacer'}), h('span', {class: 'small muted'}, c ? `${c.by_name || 'someone'} · ${when(c.when)}` : 'waiting'))))),
        h('div', {class: 'row'}, h('a', {class: 'btn sm', href: '#/studio'}, 'Studio'), h('a', {class: 'btn sm', href: '#/validate'}, 'Validation queue'),
          canEdit && !running ? h('button', {class: 'btn sm ghost danger', onclick: async () => { if (await confirmBox(`Remove “${st.name}”?`, 'The brief, sources, drafts and builds are deleted; open checkpoints are withdrawn.')) { try { await api('/api/studio/' + id, {method: 'DELETE'}); notify('Removed', 'ok'); location.hash = '#/studio'; } catch (e) { notify(e.message, 'err'); } } }}, 'Remove') : null)))));
  document.title = `${st.name} · Studio · ${S.brand ? S.brand.full : 'RELAY by PASDACS'}`;
  if (running) S.studioTimer = setTimeout(() => { if (location.hash.startsWith('#/studio/' + id)) renderStudioItem(id); }, 2500);
}
