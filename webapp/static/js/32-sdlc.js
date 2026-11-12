/* ---------------- AI SDLC (P16): repositories and trackers, change requests through Request -> Plan -> Develop -> QA -> UAT ->
   Release -> Run, each step confirmed by a named person; the pull request with its test results; governance (one AI
   setup for the team, policies, audit per request). GET /api/sdlc/overview, /api/sdlc/requests/<id>. Tokens only. ---------------- */
(function sdlcStyles() {
  document.head.append(h('style', {}, `
  .sjourney{margin:0 0 6px}.sjourney li.done .dot{background:var(--ok);border-color:var(--ok)}.sjourney li.on .dot{background:var(--accent);border-color:var(--accent);box-shadow:0 0 0 3px var(--ring)}
  .sjourney li.done::before{background:var(--ok)}.sjourney li.on .jl{color:var(--accent)}
  .skv{display:grid;grid-template-columns:max-content 1fr;gap:4px 12px;font-size:13px;margin:0}.skv dt{color:var(--muted)}.skv dd{margin:0;overflow-wrap:anywhere}
  .stab{width:100%;border-collapse:collapse;font-size:13px}.stab th{text-align:left;color:var(--ink-2);font-weight:600;padding:4px 8px 4px 0}.stab td{padding:5px 8px 5px 0;border-top:1px solid var(--line);vertical-align:top;overflow-wrap:anywhere}
  .sfile{font-family:var(--mono);font-size:12px}.sdiff{font-family:var(--mono);font-size:12px;white-space:pre;overflow:auto;max-height:60vh;background:var(--surface-2);padding:10px;border-radius:var(--radius-sm)}
  .sdiff .add{color:var(--ok)}.sdiff .del{color:var(--err)}.sdiff .hunk{color:var(--accent)}
  .slog{font-size:12.5px}.slog>div{display:flex;gap:8px;padding:4px 0;border-top:1px solid var(--line)}.slog .k{flex:none;width:64px;color:var(--muted)}
  .srepo{display:flex;gap:10px;align-items:flex-start;padding:8px 0;border-top:1px solid var(--line)}.srepo:first-child{border-top:0}.srepo .grow{flex:1;min-width:0}
  .sstat{display:inline-flex;align-items:center;gap:6px;font-size:12.5px}
  `));
})();

const SD = {status: 'open', q: '', timer: null};
// the AI providers a policy allows, by name (providers.py kinds)
const SD_PROVIDER = {claude_account: 'Claude subscription', anthropic_api: 'Anthropic API', bedrock: 'Amazon Bedrock', vertex: 'Google Vertex AI', azure: 'Azure AI Foundry',
  foundry: 'Azure AI Foundry', litellm: 'LiteLLM gateway', codex: 'OpenAI Codex', gemini: 'Gemini CLI', antigravity: 'Antigravity'};
const providerSaid = k => SD_PROVIDER[k] || String(k || '').replace(/_/g, ' ');
const SD_STATUS = {waiting: 'you', blocked: 'err', planning: 'run', plan_review: 'you', developing: 'run', qa: 'run', reviewing: 'run', review: 'you', uat: 'you', release_review: 'you', releasing: 'run', released: 'ok', closed: 'mute', error: 'err'};
const sdStatus = r => h('span', {class: 'pill plain ' + (SD_STATUS[r.status] || 'mute')}, r.status_label || r.status);
const sdAge = s => s < 3600 ? `${Math.max(1, Math.round(s / 60))} min` : s < 86400 ? `${(s / 3600).toFixed(s < 7200 ? 1 : 0)} h` : `${Math.round(s / 86400)} day${Math.round(s / 86400) === 1 ? '' : 's'}`;
const sdRes = v => h('span', {class: 'pill plain ' + ({pass: 'ok', fail: 'err', timeout: 'err', skipped: 'mute', error: 'err'}[v] || 'mute')}, v || '-');

function sdJourney(stages, current, done) {
  return h('ol', {class: 'journey sjourney', 'aria-label': 'Journey'}, stages.map(([id, label], i) => h('li', {class: i < current ? 'done' : i === current ? 'on' : '', 'aria-current': i === current ? 'step' : null},
    h('span', {class: 'dot'}), h('div', {class: 'jl'}, `${i + 1} ${label}`), h('div', {class: 'js'}, i === current ? (done ? 'done' : 'now') : i < current ? 'done' : ' '))));
}

async function renderSdlc() {
  const m = location.hash.match(/^#\/sdlc\/([\w-]+)/);
  clearTimeout(SD.timer);
  if (m) return renderSdlcRequest(m[1]);
  const main = $('#main');
  const crumbs = [['Home', '#/'], ['All modules', '#/modules'], ['AI SDLC']], eyebrow = brandName() + ' - Systems - AI SDLC', title = 'Change requests by governed agents';
  if (!$('#sdlcpage')) main.replaceChildren(h('div', {class: 'page'}, pageHead({crumbs, eyebrow, title}), skel('cards')));
  let d;
  try { d = await api(`/api/sdlc/overview?status=${SD.status}`); }
  catch (e) { main.replaceChildren(h('div', {class: 'page'}, pageHead({crumbs, eyebrow, title}), h('div', {class: 'note err'}, e.message))); return; }
  if (!location.hash.startsWith('#/sdlc') || location.hash.match(/^#\/sdlc\//)) return;
  const s = d.summary, builder = !!d.can_edit;
  const head = pageHead({crumbs, eyebrow, title,
    promise: 'Bring your Git repository and tracker: a change request becomes an approved plan, agent development on a branch, generated tests with security and dependency scans, a reviewer agent and a named human review, UAT on synthetic data and a release a named approver accepts - one governed AI setup for the whole team, audited per request. Relay opens the pull request; it never merges.',
    actions: [s.open ? h('span', {class: 'pill plain ' + (s.waiting_for_you ? 'you' : 'run')}, s.waiting_for_you ? `${s.waiting_for_you} waiting for a person` : `${s.open} in flight`) : h('span', {class: 'pill plain ok'}, 'Nothing in flight'),
      builder ? h('button', {class: 'btn' + (d.repos.length ? ' primary' : ''), type: 'button', disabled: !d.repos.length, title: d.repos.length ? '' : 'Add a repository first', onclick: () => sdNewRequest(d)}, icon('plus'), 'New change request') : null,
      builder ? h('button', {class: 'btn' + (d.repos.length ? '' : ' primary'), type: 'button', onclick: () => sdRepoModal(d)}, icon('db'), 'Add a repository') : null,
      d.test_hooks && builder ? h('button', {class: 'btn', type: 'button', onclick: async e => { e.target.disabled = true; try { const r = await api('/api/sdlc/test/seed', {method: 'POST'}); notify('Sample repository and request ready', 'ok'); location.hash = '#/sdlc/' + r.request; } catch (err) { notify(err.message, 'err'); e.target.disabled = false; } }}, icon('dice'), 'Try the sample') : null]});
  const kpis = h('div', {class: 'g5'},
    kpiTile('In flight', String(s.open), s.open ? `${s.waiting_for_you} waiting for a person` : 'no change in flight', {href: '#/sdlc', ...(s.open ? {} : {good: true})}),
    kpiTile('Released', String(s.released_30d), 'pull requests opened in 30 days'),
    kpiTile('Repositories', String(s.repos), d.repos.filter(r => r.status === 'connected').length + ' connected'),
    kpiTile('AI spend', d.governance ? '$' + fmtN(d.governance.spend_month_usd) : '-', d.governance ? `${d.governance.runs_month} agent run${d.governance.runs_month === 1 ? '' : 's'} this month` : 'for builders and admins'),
    kpiTile('Audit', d.governance ? String(d.governance.audit_30d) : '-', 'signed decisions and events, 30 days'));
  const journey = h('div', {class: 'card', style: 'margin-top:16px'}, h('div', {class: 'card-head'}, h('h3', {}, 'The journey of every change'), h('span', {class: 'sp'}), h('span', {class: 'small muted'}, 'where the open requests are')),
    h('ol', {class: 'journey', 'aria-label': 'Journey'}, d.stages.map(([id, label], i) => h('li', {}, h('span', {class: 'dot', style: s.by_stage[id] ? 'background:var(--accent);border-color:var(--accent)' : ''}), h('div', {class: 'jl'}, `${i + 1} ${label}`), h('div', {class: 'js'}, s.by_stage[id] ? `${s.by_stage[id]} request${s.by_stage[id] === 1 ? '' : 's'}` : ' ')))),
    h('div', {class: 'confirm'}, [['Plan', 'the change plan: files, risks, tests'], ['QA', 'the pull request with test results'], ['UAT', 'business sign-off on synthetic data'], ['Release', 'named approver']].map(([a, b]) => h('div', {}, h('span', {class: 'proven'}, icon('check')), h('span', {}, h('b', {}, a + ': '), b)))));
  const seg = h('div', {class: 'segbtn', role: 'group', 'aria-label': 'Status'}, [['open', 'In flight'], ['released', 'Released'], ['closed', 'Closed'], ['all', 'All']].map(([v, l]) => h('button', {type: 'button', class: SD.status === v ? 'on' : '', 'aria-pressed': String(SD.status === v), onclick: () => { SD.status = v; renderSdlc(); }}, l)));
  const qIn = h('input', {type: 'search', placeholder: 'Find a request...', 'aria-label': 'Find a request', value: SD.q, style: 'max-width:260px', oninput: e => { SD.q = e.target.value; drawTable(); }});
  const tableBox = h('div', {});
  function drawTable() {
    const rows = d.requests.filter(r => !SD.q || `${r.title} ${r.ticket_key || ''} ${(r.repo || {}).name || ''} ${r.source_label}`.toLowerCase().includes(SD.q.toLowerCase()));
    const row = r => h('tr', {tabindex: '0', role: 'button', 'aria-label': `${r.title}: ${r.status_label}. Open the request`, style: 'cursor:pointer', onclick: () => { location.hash = '#/sdlc/' + r.id; }, onkeydown: e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); location.hash = '#/sdlc/' + r.id; } }},
      h('td', {}, h('b', {}, r.title), h('div', {class: 'small muted'}, `${r.id}${r.ticket_key ? ' - ' + r.ticket_key : ''} - ${r.source_label}`)),
      h('td', {}, r.repo ? [r.repo.name, h('div', {class: 'small muted'}, r.repo.provider_label)] : h('span', {class: 'muted'}, 'pick a repository')), h('td', {}, h('span', {class: 'small'}, `${r.stage_index + 1} ${d.stages[r.stage_index][1]}`)), h('td', {}, sdStatus(r)), h('td', {}, sdAge(r.age_s)));
    tableBox.replaceChildren(rows.length ? h('div', {class: 'card', style: 'padding:0;overflow:auto;margin:0'}, h('table', {class: 'utable'}, h('thead', {}, h('tr', {}, ['Change request', 'Repository', 'Step', 'Status', 'Age'].map(t => h('th', {class: 'l', scope: 'col'}, t)))), h('tbody', {}, rows.map(row))))
      : h('div', {class: 'card empty', style: 'margin:0'}, h('h3', {}, SD.status === 'open' ? 'No change in flight' : 'Nothing here'), h('div', {class: 'muted', style: 'max-width:600px;margin:0 auto'}, SD.status === 'open' ? (d.repos.length ? 'Open a change request from a tracker ticket or in plain words; a tech lead approves the plan before any code changes.' : 'Add a repository (GitHub with your own sign-in, or a Git host with a token) to start. Hand-offs from Service desk, Integration analytics and Data observability appear here as requests waiting to start.') : 'Change the filter.')));
  }
  drawTable();
  const reposCard = h('div', {class: 'card', style: 'margin:0'}, h('div', {class: 'card-head'}, h('h3', {}, 'Repositories & trackers'), h('span', {class: 'sp'}), builder ? h('button', {class: 'btn sm', type: 'button', onclick: () => sdRepoModal(d)}, icon('plus'), 'Add') : null),
    d.repos.length ? h('div', {}, d.repos.map(r => h('div', {class: 'srepo'},
      h('div', {class: 'grow'}, h('div', {}, h('b', {}, r.name), ' ', h('span', {class: 'chipx'}, r.provider_label), r.tracker_kind ? h('span', {class: 'chipx', style: 'margin-left:4px'}, r.tracker_kind === 'jira' ? 'Jira' : 'Azure Boards') : null, r.allowed ? null : h('span', {class: 'pill plain err', style: 'margin-left:6px'}, 'not in policy')),
        h('div', {class: 'small muted'}, `${r.url} - ${r.default_branch} - ${r.status === 'connected' ? 'connected' : r.status === 'error' ? 'error: ' + (r.error || '') : 'not tested yet'} - sign-in ${r.has_token ? 'stored by name' : 'missing'} - ${r.requests} request${r.requests === 1 ? '' : 's'}`),
        r.index ? h('div', {class: 'small muted'}, `${r.index.main_language || '?'} - tests: ${r.index.test_command || 'not found'} - lint: ${r.index.lint_command || 'none'} - CODEOWNERS ${(r.index.codeowners || []).length} rule(s) - ${(r.index.conventions || {}).indentation || ''}`) : null,
        r.tracker_kind && r.writeback ? h('div', {class: 'small muted'}, r.writeback.allowed ? 'Pull request link back on the ticket: allowed, each comment after a named approval' : `Pull request link back on the ticket: off - ${r.writeback.why}`) : null),
      builder ? h('div', {class: 'row', style: 'gap:6px;flex:none'}, h('button', {class: 'btn sm', type: 'button', onclick: async e => { e.target.disabled = true; try { const t = await api(`/api/sdlc/repos/${r.id}/test`, {method: 'POST'}); notify('Connected: ' + (t.sees || 'ok'), 'ok'); renderSdlc(); } catch (err) { notify(err.message, 'err'); e.target.disabled = false; } }}, 'Test'),
        h('button', {class: 'btn sm', type: 'button', onclick: () => sdRepoModal(d, r)}, 'Edit')) : null)))
      : h('div', {class: 'muted small'}, 'No repository yet. GitHub uses your own sign-in (Settings > GitHub); other hosts take an account and token kept in the secrets store by name.'));
  const gov = d.governance;
  const govCard = h('div', {class: 'card', style: 'margin:0'}, h('div', {class: 'card-head'}, h('h3', {}, 'One AI setup for the team'), h('span', {class: 'sp'}), d.admin ? h('button', {class: 'btn sm', type: 'button', onclick: () => sdPolicyModal(d)}, icon('shield'), 'Policies') : null),
    gov ? [h('dl', {class: 'skv'}, h('dt', {}, 'Providers allowed'), h('dd', {}, (gov.ai.policy.allowed || []).map(providerSaid).join(', ') + (gov.ai.policy.default ? ` - default ${providerSaid(gov.ai.policy.default)}` : '') + (gov.ai.policy.residency ? ` - ${gov.ai.policy.residency}` : '')),
        h('dt', {}, 'Model'), h('dd', {}, gov.ai.models[gov.ai.default_model] || gov.ai.default_model), h('dt', {}, 'Budgets'), h('dd', {}, gov.quotas.length ? gov.quotas.map(q => `${q.scope} ${q.target_id}: $${fmtN(q.monthly_usd)} / month`).join(' - ') : 'no quota set (Admin > Costs & quotas)'),
        h('dt', {}, 'This month'), h('dd', {}, `$${fmtN(gov.spend_month_usd)} on ${gov.runs_month} agent run${gov.runs_month === 1 ? '' : 's'}`),
        h('dt', {}, 'Repositories'), h('dd', {}, d.policy.repos.length ? d.policy.repos.map(id => ((d.repos.find(r => r.id === id) || {}).name || id)).join(', ') : 'every repository added here'),
        h('dt', {}, 'Who approves'), h('dd', {}, ['plan', 'review', 'uat', 'release'].map(k => `${k}: ${(gov.approver_names[k] || []).join(', ') || 'the request\'s owner'}`).join(' - ')),
        h('dt', {}, 'Required'), h('dd', {}, `secret scan always - dependency scan ${d.policy.scans.dependencies ? 'on' : 'off'} - tests must pass ${d.policy.scans.tests_must_pass ? 'on' : 'off'} - Relay never merges`)),
      h('div', {class: 'small muted', style: 'margin-top:8px'}, 'Every AI call, file change, commit, scan and decision is logged against its request (open a request > Audit).')]
      : h('div', {class: 'muted small'}, 'Builders and admins see the AI setup, budgets and policies here.'));
  main.replaceChildren(h('div', {class: 'page', id: 'sdlcpage'}, head, kpis, journey,
    h('div', {class: 'row', style: 'margin:16px 0 10px;gap:10px;flex-wrap:wrap'}, seg, qIn, h('span', {class: 'sp', style: 'flex:1'}), h('span', {class: 'small muted'}, agentNow(d.worker))),
    tableBox, h('div', {class: 'g2', style: 'margin-top:16px'}, reposCard, govCard)));
  document.title = `AI SDLC - ${S.brand ? S.brand.full : 'RELAY by PASDACS'}`;
  if (d.requests.some(r => ['planning', 'developing', 'qa', 'reviewing', 'releasing'].includes(r.status))) SD.timer = setTimeout(() => { if (location.hash === '#/sdlc') renderSdlc(); }, 5000);
}

function sdRepoModal(d, r) {
  const provs = Object.entries(d.providers);
  const prov = h('select', {'aria-label': 'Host'}, provs.map(([k, v]) => h('option', {value: k, selected: r && r.provider === k}, v.label)));
  const name = h('input', {type: 'text', placeholder: 'Name (optional)', 'aria-label': 'Name', value: r ? r.name : '', style: 'width:100%'});
  const url = h('input', {type: 'text', placeholder: d.providers[prov.value].url_hint, 'aria-label': 'Clone URL', value: r ? r.url : '', style: 'width:100%'});
  const api_url = h('input', {type: 'text', placeholder: 'API base URL (optional, e.g. https://git.example.com)', 'aria-label': 'API base URL', value: r && r.api_url ? r.api_url : '', style: 'width:100%'});
  const account = h('input', {type: 'text', placeholder: 'Account / user name on the host', 'aria-label': 'Account', value: r && r.account ? r.account : '', style: 'width:100%'});
  const token = h('input', {type: 'password', placeholder: r && r.has_token ? 'Token stored by name - enter a new one to replace it' : 'Token or app password (kept in the secrets store, by name)', 'aria-label': 'Token', autocomplete: 'new-password', style: 'width:100%'});
  const branch = h('input', {type: 'text', placeholder: 'main', 'aria-label': 'Default branch', value: r ? r.default_branch : 'main', style: 'width:100%'});
  const tracker = h('select', {'aria-label': 'Tracker'}, h('option', {value: ''}, 'No tracker (requests in plain words)'), h('option', {value: 'jira', selected: r && r.tracker_kind === 'jira'}, 'Jira - through the Service desk source'), h('option', {value: 'azure_boards', selected: r && r.tracker_kind === 'azure_boards'}, 'Azure Boards'));
  const jira = h('select', {'aria-label': 'Jira source'}, h('option', {value: ''}, d.jira_sources.length ? 'Pick the Jira source' : 'No Jira source in the Service desk yet'), d.jira_sources.map(s => h('option', {value: s.id, selected: r && r.tracker_source === s.id}, s.name)));
  const bOrg = h('input', {type: 'text', placeholder: 'https://dev.azure.com/your-org', 'aria-label': 'Azure DevOps organisation URL', style: 'width:100%'});
  const bProj = h('input', {type: 'text', placeholder: 'Project', 'aria-label': 'Azure Boards project', style: 'width:100%'});
  const bPat = h('input', {type: 'password', placeholder: 'Personal access token (Work items: read; read & write for the write-back)', 'aria-label': 'Azure Boards token', autocomplete: 'new-password', style: 'width:100%'});
  const bWrite = h('input', {type: 'checkbox', checked: !!(r && r.tracker_kind === 'azure_boards' && r.writeback && r.writeback.allowed)});   // consolidation: off unless granted
  const bWriteRow = h('label', {class: 'row small', style: 'gap:6px;margin-top:6px'}, bWrite, 'Write the pull request link back on the work item - each comment after a named approval');
  const jHint = h('div', {class: 'small muted', style: 'margin-top:4px'}, 'The pull request link goes back on the Jira issue as a comment when the Service desk source allows comments - each one after a named approval.');
  const hint = h('div', {class: 'small muted'});
  const trackerBox = h('div', {});
  const sync = () => { const p = d.providers[prov.value] || {}; hint.textContent = `Sign-in: ${p.signin || ''} - ${p.api || ''}`; url.placeholder = p.url_hint || ''; account.hidden = token.hidden = prov.value === 'github' || prov.value === 'local'; trackerBox.replaceChildren(tracker.value === 'jira' ? h('div', {}, jira, jHint) : tracker.value === 'azure_boards' ? h('div', {}, bOrg, bProj, bPat, bWriteRow) : h('span', {})); };
  prov.onchange = sync; tracker.onchange = sync; sync();
  const mm = modal(r ? 'Edit the repository' : 'Add a repository', h('div', {},
    h('p', {class: 'small muted'}, 'The agent works on a clone in the request folder through `genbi repo` only; the credential is injected per run and never written to disk. Relay pushes the branch and opens a pull request only after a named approver accepts the release - it never merges.'),
    h('label', {class: 'f'}, 'Host'), prov, hint, h('label', {class: 'f', style: 'margin-top:8px'}, 'Clone URL'), url, h('label', {class: 'f', style: 'margin-top:8px'}, 'Name'), name, h('label', {class: 'f', style: 'margin-top:8px'}, 'API base URL'), api_url,
    h('label', {class: 'f', style: 'margin-top:8px'}, 'Account'), account, h('label', {class: 'f', style: 'margin-top:8px'}, 'Token'), token, h('label', {class: 'f', style: 'margin-top:8px'}, 'Default branch'), branch,
    h('label', {class: 'f', style: 'margin-top:8px'}, 'Tracker'), tracker, trackerBox,
    h('div', {class: 'row', style: 'justify-content:flex-end;margin-top:12px;gap:8px'}, r ? h('button', {class: 'btn', type: 'button', onclick: async () => { if (!await confirmBox('Remove the repository?', `${r.name} and its stored token are removed; closed requests keep their records.`, 'Remove')) return; try { await api(`/api/sdlc/repos/${r.id}`, {method: 'DELETE'}); mm.remove(); notify('Repository removed', 'ok'); renderSdlc(); } catch (e) { notify(e.message, 'err'); } }}, 'Remove') : null,
      h('button', {class: 'btn primary', type: 'button', onclick: async e => { e.target.disabled = true; const body = {provider: prov.value, url: url.value, name: name.value || null, api_url: api_url.value || null, account: account.value || null, token: token.value || null, default_branch: branch.value || 'main', tracker_kind: tracker.value || null, tracker_source: tracker.value === 'jira' ? (jira.value || null) : null, boards_org_url: bOrg.value || null, boards_project: bProj.value || null, boards_pat: bPat.value || null, ...(tracker.value === 'azure_boards' ? {boards_write_back: bWrite.checked} : {})};
        try { const saved = await api(r ? `/api/sdlc/repos/${r.id}` : '/api/sdlc/repos', {method: r ? 'PUT' : 'POST', json: (body)}); mm.remove(); notify(`${saved.name} saved`, 'ok'); try { const t = await api(`/api/sdlc/repos/${saved.id}/test`, {method: 'POST'}); notify('Connected: ' + (t.sees || 'ok'), 'ok'); } catch (err) { notify('Saved, but the test failed: ' + err.message, 'err'); } renderSdlc(); } catch (err) { notify(err.message, 'err'); e.target.disabled = false; } }}, r ? 'Save' : 'Add & test'))), true);
}

function sdNewRequest(d) {
  const repo = h('select', {'aria-label': 'Repository'}, d.repos.map(r => h('option', {value: r.id}, `${r.name} (${r.provider_label})`)));
  const ticket = h('input', {type: 'text', placeholder: 'Ticket key, e.g. DATA-142 (read through the tracker)', 'aria-label': 'Ticket key', style: 'width:100%'});
  const title = h('input', {type: 'text', placeholder: 'What should change (one line)', 'aria-label': 'Title', style: 'width:100%'});
  const text = h('textarea', {rows: 5, placeholder: 'In plain words: what is wrong or wanted, where, and how you will know it is done', 'aria-label': 'Request', style: 'width:100%'});
  const mm = modal('New change request', h('div', {}, h('p', {class: 'small muted'}, 'From a tracker ticket or in plain words. The agent indexes the repository\'s conventions and writes the plan - files, risks, tests, estimate - for a tech lead to approve before any code changes.'),
    h('label', {class: 'f'}, 'Repository'), repo, h('label', {class: 'f', style: 'margin-top:8px'}, 'Ticket'), ticket, h('label', {class: 'f', style: 'margin-top:8px'}, 'Title'), title, h('label', {class: 'f', style: 'margin-top:8px'}, 'Request'), text,
    h('div', {class: 'row', style: 'justify-content:flex-end;margin-top:12px'}, h('button', {class: 'btn primary', type: 'button', onclick: async e => { e.target.disabled = true; try { const r = await api('/api/sdlc/requests', {method: 'POST', json: ({repo_id: repo.value, ticket_key: ticket.value || null, title: title.value || null, text: text.value || null})}); mm.remove(); notify('Change request opened, the agent starts planning it next', 'ok'); location.hash = '#/sdlc/' + r.id; } catch (err) { notify(err.message, 'err'); e.target.disabled = false; } }}, 'Open the request'))));
}

function sdPolicyModal(d) {
  const gov = d.governance || {people: []};
  const repoBoxes = d.repos.map(r => h('label', {class: 'row', style: 'gap:6px'}, h('input', {type: 'checkbox', checked: d.policy.repos.includes(r.id), value: r.id}), r.name));
  const pick = step => h('select', {multiple: true, size: 4, 'aria-label': `${step} approvers`, style: 'width:100%'}, gov.people.map(p => h('option', {value: p.id, selected: (d.policy.approvers[step] || []).includes(p.id)}, p.name)));
  const sel = {plan: pick('plan'), review: pick('review'), uat: pick('uat'), release: pick('release')};
  const deps = h('input', {type: 'checkbox', checked: d.policy.scans.dependencies}), tests = h('input', {type: 'checkbox', checked: d.policy.scans.tests_must_pass});
  const mm = modal('AI SDLC policies', h('div', {}, h('p', {class: 'small muted'}, 'Which repositories agents may work on (none ticked = every repository added here), who may approve each step (empty = the request\'s owner), and the scans a release needs. The secret scan always runs; Relay never merges.'),
    h('h4', {}, 'Repositories'), repoBoxes.length ? h('div', {}, repoBoxes) : h('div', {class: 'small muted'}, 'No repository yet.'),
    h('div', {class: 'g2', style: 'margin-top:10px'}, ...['plan', 'review', 'uat', 'release'].map(st => h('div', {}, h('label', {class: 'f'}, {plan: 'Plan - tech leads', review: 'Review - named reviewers', uat: 'UAT - business approvers', release: 'Release - named approvers'}[st]), sel[st]))),
    h('div', {class: 'row', style: 'gap:16px;margin-top:10px'}, h('label', {class: 'row', style: 'gap:6px'}, deps, 'Dependency scan (pip-audit / npm audit where present)'), h('label', {class: 'row', style: 'gap:6px'}, tests, 'Tests must pass before a release')),
    h('div', {class: 'row', style: 'justify-content:flex-end;margin-top:12px'}, h('button', {class: 'btn primary', type: 'button', onclick: async e => { e.target.disabled = true; const body = {repos: repoBoxes.map(l => l.querySelector('input')).filter(i => i.checked).map(i => i.value), approvers: Object.fromEntries(Object.entries(sel).map(([k, s]) => [k, [...s.selectedOptions].map(o => o.value)])), scans: {dependencies: deps.checked, tests_must_pass: tests.checked}};
      try { await api('/api/sdlc/policies', {method: 'PUT', json: (body)}); mm.remove(); notify('Policies saved - audited', 'ok'); renderSdlc(); } catch (err) { notify(err.message, 'err'); e.target.disabled = false; } }}, 'Save policies'))), true);
}

function sdDiffView(text) {
  const pre = h('pre', {class: 'sdiff'});
  for (const line of (text || '').split('\n').slice(0, 4000)) pre.append(h('span', {class: line.startsWith('+++') || line.startsWith('---') ? '' : line.startsWith('+') ? 'add' : line.startsWith('-') ? 'del' : line.startsWith('@@') ? 'hunk' : ''}, line + '\n'));
  return pre;
}

async function renderSdlcRequest(id) {
  const main = $('#main');
  let r;
  try { r = await api('/api/sdlc/requests/' + id); }
  catch (e) { main.replaceChildren(h('div', {class: 'page'}, pageHead({crumbs: [['Home', '#/'], ['AI SDLC', '#/sdlc'], ['Request']], eyebrow: brandName() + ' - AI SDLC', title: 'Change request'}), h('div', {class: 'note err'}, e.message))); return; }
  if (location.hash !== '#/sdlc/' + id) return;
  let people = [];                      // the approver by name, not by user id
  if (r.checkpoint && r.checkpoint.assignee_id) { try { people = (await api('/api/directory')).users || []; } catch (e) { people = []; } }
  const personName = uid => { const p = people.find(u => u.id === uid); return p ? p.name || p.email : 'a named approver'; };
  const builder = !!(S.me && (S.me.admin || S.me.builder));
  const stages = [['request', 'Request'], ['plan', 'Plan'], ['develop', 'Develop'], ['qa', 'QA'], ['uat', 'UAT'], ['release', 'Release'], ['run', 'Run']];
  const running = ['planning', 'developing', 'qa', 'reviewing', 'releasing'].includes(r.status);
  const openCp = r.checkpoint && r.checkpoint.status === 'open' ? r.checkpoint : null;
  const decide = async (cp, accept) => {
    let comment = null;
    if (!accept) { comment = await askText('Send it back', {label: 'What should change?', hint: 'The agent gets your note and corrects it.', required: true, ok: 'Send back'}); if (!comment) return; }
    try { await api(`/api/validate/${cp.id}/${accept ? 'accept' : 'send-back'}`, {method: 'POST', json: ({comment})}); notify(accept ? 'Accepted - signed and audited' : 'Sent back', 'ok'); renderSdlcRequest(id); } catch (e) { notify(e.message, 'err'); }
  };
  const cpLabel = {'sdlc.plan': 'Approve the plan', 'sdlc.review': 'Approve the pull request', 'sdlc.uat': 'Sign off UAT', 'sdlc.release': 'Approve the release'};
  const head = pageHead({crumbs: [['Home', '#/'], ['AI SDLC', '#/sdlc'], [r.id]], eyebrow: brandName() + ' - AI SDLC - ' + r.source_label + (r.repo ? ' - ' + r.repo.name : ''), title: r.title, promise: (r.text || '').slice(0, 400),
    actions: [sdStatus(r), running ? h('span', {class: 'pill run'}, 'Working...') : null,
      openCp && builder ? h('button', {class: 'btn primary', type: 'button', onclick: () => decide(openCp, true)}, icon('check'), cpLabel[openCp.kind] || 'Accept') : null, openCp && builder ? h('button', {class: 'btn', type: 'button', onclick: () => decide(openCp, false)}, 'Send back') : null,
      builder && !r.repo && !r.closed ? h('button', {class: 'btn primary', type: 'button', onclick: () => sdStartModal(r)}, icon('play'), 'Start on a repository') : null,
      builder && r.repo && r.status === 'waiting' ? h('button', {class: 'btn primary', type: 'button', onclick: async e => { e.target.disabled = true; try { await api(`/api/sdlc/requests/${id}/start`, {method: 'POST', json: ({repo_id: r.repo.id})}); notify('The agent starts planning it next', 'ok'); renderSdlcRequest(id); } catch (err) { notify(err.message, 'err'); e.target.disabled = false; } }}, icon('play'), 'Start planning') : null,
      builder && r.repo && ['error', 'blocked'].includes(r.status) ? h('button', {class: 'btn', type: 'button', onclick: async e => { e.target.disabled = true; try { await api(`/api/sdlc/requests/${id}/retry`, {method: 'POST'}); notify('Queued again', 'ok'); renderSdlcRequest(id); } catch (err) { notify(err.message, 'err'); e.target.disabled = false; } }}, icon('play'), 'Run again') : null,
      builder && !r.closed ? h('button', {class: 'btn', type: 'button', onclick: async () => { const why = await askText('Close this request', {label: 'Why does it close?', hint: 'Kept in the audit log.', required: true, ok: 'Close the request'}); if (!why) return; try { await api(`/api/sdlc/requests/${id}/close`, {method: 'POST', json: ({comment: why})}); notify('Closed', 'ok'); renderSdlcRequest(id); } catch (e) { notify(e.message, 'err'); } }}, 'Close') : null]});
  const journey = h('div', {class: 'card'}, sdJourney(stages, r.stage_index, ['released', 'closed'].includes(r.status)),
    h('div', {class: 'small muted'}, r.note ? [h('b', {}, 'Note: '), r.note] : openCp ? `Waiting for a person: ${cpLabel[openCp.kind] || openCp.name}${openCp.assignee_id ? ' (assigned to ' + personName(openCp.assignee_id) + ')' : ''} - also in the validation queue.` : r.status === 'waiting' ? 'Pick the repository this change belongs to; the agent then learns its conventions and plans.' : running ? 'The agent is working on it; every call is logged against this request.' : r.status === 'released' ? 'The pull request is open on the host for the team to merge; Relay never merges. Self-healing watches what it touches once live.' : ''));
  const req = h('div', {class: 'card', style: 'margin:0'}, h('div', {class: 'card-head'}, h('h3', {}, 'Request')),
    h('dl', {class: 'skv'}, h('dt', {}, 'Source'), h('dd', {}, r.source_label + (r.ticket_key ? ` - ${r.ticket_url ? '' : ''}${r.ticket_key}` : '') + (r.work ? ` (${r.work.table} ${r.work.id})` : '')), r.ticket_url ? [h('dt', {}, 'Ticket'), h('dd', {}, h('a', {href: r.ticket_url, target: '_blank', rel: 'noopener'}, r.ticket_key))] : null,
      h('dt', {}, 'Repository'), h('dd', {}, r.repo ? `${r.repo.name} (${r.repo.provider_label}) - ${r.repo.url}` : '- not chosen yet'), h('dt', {}, 'Branch'), h('dd', {}, r.branch ? `${r.branch} from ${r.base} @ ${(r.base_sha || '').slice(0, 8)}` : '-'),
      h('dt', {}, 'Opened'), h('dd', {}, `${when(r.created)} by ${r.owner_id || '-'}`), h('dt', {}, 'AI'), h('dd', {}, `${r.ai_calls} call${r.ai_calls === 1 ? '' : 's'} - $${fmtN(r.cost_usd || 0)} - ${r.file_changes} file change${r.file_changes === 1 ? '' : 's'}`),
      r.repo && r.repo.index ? [h('dt', {}, 'Conventions'), h('dd', {}, `${r.repo.index.main_language || '?'} - tests: ${r.repo.index.test_command || 'not found'} - lint: ${r.repo.index.lint_command || 'none'} - ${(r.repo.index.conventions || {}).indentation || ''}, ${(r.repo.index.conventions || {}).line_endings || ''} - CODEOWNERS ${(r.repo.index.codeowners || []).length}`)] : null),
    r.text ? h('div', {class: 'small', style: 'margin-top:10px;white-space:pre-wrap;max-height:200px;overflow:auto'}, r.text) : null,
    r.files.length ? h('div', {class: 'row', style: 'margin-top:10px;gap:6px;flex-wrap:wrap'}, r.files.map(f => h('button', {class: 'btn sm', type: 'button', onclick: async () => { try { const x = await api(`/api/sdlc/requests/${id}/file/${f}`); modal(f, h('pre', {class: 'sdiff'}, x.text), true); } catch (e) { notify(e.message, 'err'); } }}, f))) : null);
  const p = r.plan;
  const plan = h('div', {class: 'card', style: 'margin:0'}, h('div', {class: 'card-head'}, h('h3', {}, 'Plan'), h('span', {class: 'sp'}), p && p.estimate ? h('span', {class: 'small muted'}, `estimate ${p.estimate.hours || '-'} h - ${p.estimate.commits || '-'} commit(s)`) : null),
    p ? [h('div', {}, p.summary), h('table', {class: 'stab', style: 'margin-top:8px'}, h('thead', {}, h('tr', {}, ['File', 'Change'].map(t => h('th', {scope: 'col'}, t)))), h('tbody', {}, (p.files || []).slice(0, 12).map(f => h('tr', {}, h('td', {class: 'sfile'}, `${f.kind || 'modify'} ${f.path}`), h('td', {}, f.change))))),
      (p.risks || []).length ? h('div', {class: 'small', style: 'margin-top:8px'}, h('b', {}, 'Risks: '), (p.risks || []).map(x => `${x.risk} - ${x.mitigation}`).join(' - ')) : null,
      (p.tests || []).length ? h('div', {class: 'small', style: 'margin-top:4px'}, h('b', {}, 'Tests: '), (p.tests || []).map(t => `${t.name} (${t.file})`).join(' - ')) : null,
      h('div', {class: 'small muted', style: 'margin-top:4px'}, `Touches data: ${p.touches_data ? 'yes - UAT on synthetic data' : 'no'} - roll back: ${p.rollback || '-'}`),
      openCp && openCp.kind === 'sdlc.plan' ? h('div', {class: 'note', style: 'margin-top:10px'}, h('b', {}, 'Tech lead: '), 'approve the plan and the agent develops it on a branch; nothing in the repository changes before that.') : null]
      : h('div', {class: 'muted small'}, r.status === 'planning' ? 'The agent is indexing the repository and planning...' : 'No plan yet.'));
  const qa = r.qa, t = qa && qa.tests;
  const qaCard = h('div', {class: 'card', style: 'margin:0'}, h('div', {class: 'card-head'}, h('h3', {}, 'QA - the pull request with test results'), h('span', {class: 'sp'}), r.changed_files.length ? h('button', {class: 'btn sm', type: 'button', onclick: async () => { try { const x = await api(`/api/sdlc/requests/${id}/diff`); modal(`Diff ${r.branch} from ${r.base}`, sdDiffView(x.diff || x.note), true); } catch (e) { notify(e.message, 'err'); } }}, 'View diff') : null),
    qa ? [h('div', {class: 'row', style: 'gap:14px;flex-wrap:wrap'}, h('span', {class: 'sstat'}, 'Tests', sdRes(t.status)), h('span', {class: 'sstat'}, 'Secret scan', sdRes(qa.secret_scan.status)), h('span', {class: 'sstat'}, 'Dependencies', sdRes((qa.dependency_scan || {}).status)), h('span', {class: 'sstat'}, 'Lint', sdRes((qa.lint || {}).status)), h('span', {class: 'sstat'}, `${(qa.generated_tests || []).length} test file(s) in the change`)),
      t.note ? h('div', {class: 'small muted', style: 'margin-top:6px'}, `Tests: ${t.note}`) : h('div', {class: 'small muted', style: 'margin-top:6px'}, `${t.cmd || ''} in ${t.image || ''} - ${t.seconds || 0} s - exit ${t.exit}`),
      t.output ? h('details', {style: 'margin-top:6px'}, h('summary', {class: 'small'}, 'Test output'), h('pre', {class: 'sdiff', style: 'max-height:260px'}, t.output)) : null,
      (qa.secret_scan.findings || []).length ? h('div', {class: 'small', style: 'margin-top:6px;color:var(--err)'}, h('b', {}, `Secrets found (${qa.secret_scan.findings.length}, ${qa.secret_scan.in_change.length} in this change): `), qa.secret_scan.findings.slice(0, 5).map(x => `${x.file}:${x.line} ${x.kind} ${x.match}`).join(' - ')) : null,
      (qa.dependency_scan || {}).note ? h('div', {class: 'small muted', style: 'margin-top:4px'}, `Dependencies: ${qa.dependency_scan.note}`) : null,
      h('div', {class: 'small', style: 'margin-top:8px'}, h('b', {}, `${(qa.commits || []).length} commit(s): `), (qa.commits || []).map(c => `${c.sha} ${c.message}`).join(' - ')),
      h('div', {class: 'small muted', style: 'margin-top:4px'}, (qa.files || []).map(f => `${f.status} ${f.path}`).join(' - '))]
      : h('div', {class: 'muted small'}, r.status === 'developing' ? 'The agent is developing on the branch in small commits...' : r.status === 'qa' ? 'QA is running: tests in a throwaway container, scans...' : 'QA has not run yet.'));
  const rv = r.review;
  const reviewCard = h('div', {class: 'card', style: 'margin:0'}, h('div', {class: 'card-head'}, h('h3', {}, 'Review - agent, then a named person'), h('span', {class: 'sp'}), rv ? h('span', {class: 'pill plain ' + (rv.verdict === 'approve' ? 'ok' : 'you')}, rv.verdict === 'approve' ? 'Reviewer agent: approve' : 'Reviewer agent: changes requested') : null),
    rv ? [h('div', {}, rv.summary), (rv.findings || []).length ? h('table', {class: 'stab', style: 'margin-top:8px'}, h('thead', {}, h('tr', {}, ['File', 'Severity', 'Finding', 'Fix'].map(x => h('th', {scope: 'col'}, x)))), h('tbody', {}, rv.findings.slice(0, 12).map(f => h('tr', {}, h('td', {class: 'sfile'}, `${f.file || ''}${f.line ? ':' + f.line : ''}`), h('td', {}, h('span', {class: 'pill plain ' + (f.severity === 'high' ? 'err' : f.severity === 'medium' ? 'you' : 'mute')}, f.severity)), h('td', {}, f.text), h('td', {}, f.fix || ''))))) : h('div', {class: 'small muted', style: 'margin-top:6px'}, 'No findings.'),
      rv.checks ? h('div', {class: 'small muted', style: 'margin-top:6px'}, Object.entries(rv.checks).map(([k, v]) => `${k.replace('_', ' ')}: ${v ? 'yes' : 'no'}`).join(' - ')) : null,
      openCp && openCp.kind === 'sdlc.review' ? h('div', {class: 'note', style: 'margin-top:10px'}, h('b', {}, 'Named reviewer: '), 'approve the pull request (tests, scans and findings above) or send it back with a note; UAT follows.') : null]
      : h('div', {class: 'muted small'}, r.status === 'reviewing' ? 'The reviewer agent is reading the diff...' : 'No review yet.'));
  const u = r.uat, rel = r.release;
  const uatCard = h('div', {class: 'card', style: 'margin:0'}, h('div', {class: 'card-head'}, h('h3', {}, 'UAT on synthetic data')),
    u ? [u.data && u.data.tables ? h('div', {class: 'small'}, h('b', {}, `Synthetic data: `), `${u.data.tables.length} table(s), ${fmtN(u.data.rows, 0)} rows (DemoData recipe, no real data): ` + u.data.tables.map(x => `${x.table} ${fmtN(x.rows, 0)}`).join(' - ')) : h('div', {class: 'small muted'}, u.data && u.data.error ? u.data.error : 'The change touches no data: sign off on the steps against the plan\'s acceptance criteria.'),
      h('ol', {class: 'small', style: 'margin:8px 0 0;padding-left:18px'}, (u.steps || []).map(s => h('li', {}, s))), u.tests ? h('div', {class: 'small', style: 'margin-top:6px'}, 'Tests on the synthetic data: ', sdRes(u.tests.status), u.tests.note ? ` ${u.tests.note}` : '') : null,
      openCp && openCp.kind === 'sdlc.uat' ? h('div', {class: 'note', style: 'margin-top:10px'}, h('b', {}, 'Business user: '), 'sign off UAT (or send it back with what you saw); the release then waits for its named approver.') : null]
      : h('div', {class: 'muted small'}, 'UAT starts after the review is approved.'));
  const relCard = h('div', {class: 'card', style: 'margin:0'}, h('div', {class: 'card-head'}, h('h3', {}, 'Release & run'), h('span', {class: 'sp'}), rel ? h('span', {class: 'pill plain ok'}, 'Pull request open - not merged') : null),
    rel ? [h('div', {}, 'Pull request ', h('a', {href: rel.pr.url, target: '_blank', rel: 'noopener'}, `#${rel.pr.number}`), ` on ${r.repo ? r.repo.name : ''} - ${r.branch} ${r.base} (head ${(rel.pushed.head || '').slice(0, 8)}) - released by ${rel.who_name || 'a person'} at ${when(rel.when)}.`),
      sdWriteback(r),
      h('div', {class: 'small muted', style: 'margin-top:6px'}, `Roll back: ${rel.rollback || 'revert the merge commit'} - change record: release.md`), h('div', {class: 'small', style: 'margin-top:6px'}, 'Run: once merged and live, ', h('a', {href: '#/heal'}, 'Self-healing'), ' watches the runs, refreshes and schedules this change touches', r.heal_cases.length ? ` - ${r.heal_cases.length} related case(s): ${r.heal_cases.map(c => c.title).join(' - ')}` : '.')]
      : openCp && openCp.kind === 'sdlc.release' ? h('div', {class: 'note'}, h('b', {}, 'Named approver: '), `accept and Relay pushes ${r.branch} and opens the pull request against ${r.base}; nothing is merged. Roll back: ${(p || {}).rollback || 'revert the merge commit'}.`)
      : h('div', {class: 'muted small'}, r.status === 'blocked' ? r.note : 'The release waits for UAT and its named approver.'));
  const log = h('div', {class: 'card', style: 'margin:0'}, h('div', {class: 'card-head'}, h('h3', {}, 'Audit per request'), h('span', {class: 'sp'}), h('span', {class: 'small muted'}, `${r.log.length} event${r.log.length === 1 ? '' : 's'}`)),
    r.log.length ? h('div', {class: 'slog', style: 'max-height:320px;overflow:auto'}, r.log.slice(0, 60).map(x => h('div', {}, h('span', {class: 'k'}, clock(x.ts)), h('span', {class: 'chipx', style: 'flex:none'}, x.kind), h('span', {style: 'min-width:0;overflow-wrap:anywhere'}, x.text), h('span', {class: 'muted', style: 'flex:none'}, x.who_name || '')))) : h('div', {class: 'muted small'}, 'Nothing yet.'));
  main.replaceChildren(h('div', {class: 'page', id: 'sdlcreq'}, head, journey, h('div', {class: 'g2', style: 'margin-top:16px'}, req, plan), h('div', {class: 'g2', style: 'margin-top:16px'}, qaCard, reviewCard), h('div', {class: 'g2', style: 'margin-top:16px'}, uatCard, relCard), h('div', {style: 'margin-top:16px'}, log)));
  document.title = `${r.title} - AI SDLC - ${S.brand ? S.brand.full : 'RELAY by PASDACS'}`;
  if (running) SD.timer = setTimeout(() => { if (location.hash === '#/sdlc/' + id) renderSdlcRequest(id); }, 4000);
}

// the pull request link back on the ticket (consolidation): a comment after a named approval, never without the tracker's grant
function sdWriteback(r) {
  const wb = (r.release || {}).writeback, me = S.me || {};
  if (!r.ticket_key) return null;
  if (!wb) return h('div', {class: 'small muted', style: 'margin-top:6px'}, `Ticket ${r.ticket_key}: the pull request link was not asked for.`);
  const again = me.builder !== false && ['not_allowed', 'sent_back', 'failed', 'refused', 'withdrawn'].includes(wb.status)
    ? h('button', {class: 'btn sm', type: 'button', style: 'margin-left:8px', onclick: async e => { e.target.disabled = true; try { await api(`/api/sdlc/requests/${r.id}/writeback`, {json: {}}); notify('Waiting for approval in the Validation queue', 'ok'); renderSdlcRequest(r.id); } catch (err) { notify(err.message, 'err'); e.target.disabled = false; } }}, 'Ask again') : null;
  const why = {sent_back: 'sent back', failed: 'the tracker did not take it', refused: 'no longer allowed', withdrawn: 'withdrawn'}[wb.status];
  return h('div', {class: 'small', style: 'margin-top:6px'},
    wb.status === 'written' ? [`Pull request link on ${wb.ticket} (${wb.tracker})${wb.by ? ', approved by ' + wb.by : ''} - `, wb.url ? h('a', {href: wb.url, target: '_blank', rel: 'noopener'}, 'open the ticket') : 'written']
      : wb.status === 'waiting' ? [`Pull request link on ${wb.ticket}: waiting for a named approval in the `, h('a', {href: '#/validate'}, 'Validation queue'), '.']
      : wb.status === 'not_allowed' ? `Pull request link not written to ${wb.ticket}: ${wb.note || 'not allowed on this tracker'}`
      : `Pull request link not written to ${wb.ticket}: ${why || wb.status}${wb.error ? ' - ' + wb.error : ''}.`, again);
}
async function sdStartModal(r) {
  let repos;
  try { repos = (await api('/api/sdlc/repos')).items; } catch (e) { notify(e.message, 'err'); return; }
  if (!repos.length) { notify('Add a repository first (AI SDLC > Add a repository)', 'err'); return; }
  const sel = h('select', {'aria-label': 'Repository'}, repos.map(x => h('option', {value: x.id}, `${x.name} (${x.provider_label})`)));
  const mm = modal('Start on a repository', h('div', {}, h('p', {class: 'small muted'}, 'The agent clones it, indexes its conventions and writes the plan for a tech lead to approve.'), h('label', {class: 'f'}, 'Repository'), sel,
    h('div', {class: 'row', style: 'justify-content:flex-end;margin-top:12px'}, h('button', {class: 'btn primary', type: 'button', onclick: async e => { e.target.disabled = true; try { await api(`/api/sdlc/requests/${r.id}/start`, {method: 'POST', json: ({repo_id: sel.value})}); mm.remove(); notify('The agent starts planning it next', 'ok'); renderSdlcRequest(r.id); } catch (err) { notify(err.message, 'err'); e.target.disabled = false; } }}, 'Start'))));
}
