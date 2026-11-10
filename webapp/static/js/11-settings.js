/* ---------------- settings (phase 2): my AI provider, my workspace; workspace start on sign-in ---------------- */
const KIND_HELP = {
  claude_account: 'Claude Code with a Claude subscription. Leave the token empty to use this installation\'s Claude login (shared workspace only); paste your own token from `claude setup-token` so runs bill to your subscription.',
  anthropic_api: 'Your Anthropic API key; runs are billed to your API organisation.',
  litellm: 'Through the Relay LiteLLM gateway to Amazon Bedrock, Azure AI Foundry or Google Vertex AI, with the credentials your admin set up for your team.',
  enterprise: "Your organisation's own endpoint that speaks the Anthropic API (base URL + token).",
  codex: 'OpenAI Codex CLI in its own agent image, with your OpenAI API key. Same toolkit, guide and review gates; Claude stays the default and Ask D keeps using it.',
  gemini: 'Gemini CLI in its own agent image, with your Gemini API key (Google AI Studio). Same toolkit, guide and review gates.',
  antigravity: 'Antigravity CLI in its own agent image. Leave the key empty to use this installation\'s Google login (the antigravity-api container\'s sign-in); paste your own Gemini API key to use your key instead. Same toolkit, guide and review gates.'};
const CLI_KEY_OPTIONAL = {antigravity: true};
const CLI_KEY = {codex: ['openai_api_key', 'OpenAI API key', 'sk-…', 'gpt-5.5'], gemini: ['gemini_api_key', 'Gemini API key', 'AIza…', 'gemini-3.1-pro'],
  antigravity: ['gemini_api_key', 'Gemini API key', 'AIza…', 'gemini-3.8-flash-medium']};

async function renderSettings() {
  const page = h('div', {class: 'page'}, h('div', {class: 'phead'}, h('div', {}, h('h1', {}, 'Settings'),
    h('div', {class: 'meta'}, 'Which AI provider your dashboards run on, your workspace, time zone, email for schedules, and your AI use this month.'))));
  $('#main').replaceChildren(page);
  let ai, ws;
  try { [ai, ws] = await Promise.all([api('/api/me/ai'), api('/api/workspace')]); }
  catch (e) { return page.append(h('div', {class: 'note err'}, e.message)); }
  if (!location.hash.startsWith('#/settings')) return;
  const s = {...ai.settings};
  const box = h('div', {});
  const secretInput = (field, has, ph) => { const el = h('input', {type: 'password', placeholder: has ? 'Stored — leave empty to keep' : ph, autocomplete: 'off'});
    el.oninput = () => { s[field] = el.value; }; return el; };
  const draw = () => {
    const kinds = Object.entries(ai.kinds);
    box.replaceChildren(
      h('div', {class: 'card'}, h('h3', {}, 'My AI provider'),
        h('div', {class: 'opts'}, kinds.map(([k, label]) => h('label', {class: 'chk', style: s.kind === k ? 'border-color:var(--accent);background:var(--accent-tint)' : ''},
          h('input', {type: 'radio', name: 'kind', checked: s.kind === k, onchange: () => { s.kind = k; draw(); }}), label))),
        h('div', {class: 'hint', style: 'margin-top:10px'}, KIND_HELP[s.kind] || ''),
        s.kind === 'claude_account' ? [h('label', {class: 'f'}, 'Claude subscription token ', h('small', {}, 'optional')),
          secretInput('claude_oauth_token', ai.settings.has_secret.claude_oauth_token, 'sk-ant-oat… from: claude setup-token'),
          ai.instances ? h('div', {class: 'hint'}, 'With personal workspaces on, your own token is needed: the installation\'s login stays with the shared agent.') : null] : null,
        s.kind === 'anthropic_api' ? [h('label', {class: 'f'}, 'Anthropic API key'), secretInput('anthropic_api_key', ai.settings.has_secret.anthropic_api_key, 'sk-ant-api…')] : null,
        s.kind === 'litellm' ? [h('label', {class: 'f'}, 'Model route'), (() => { const sel = h('select', {class: 'sel'}, ai.routes.map(r =>
          h('option', {value: r.alias, selected: r.alias === s.route}, `${r.label} · ${r.provider}`))); if (!s.route && ai.routes[0]) s.route = ai.routes[0].alias;
          sel.onchange = () => { s.route = sel.value; }; return sel; })(), h('div', {class: 'hint'}, 'The model picker on your dashboards then lists these routes.')] : null,
        CLI_KEY[s.kind] ? [h('label', {class: 'f'}, CLI_KEY[s.kind][1], CLI_KEY_OPTIONAL[s.kind] ? h('small', {}, ' optional') : null), secretInput(CLI_KEY[s.kind][0], ai.settings.has_secret[CLI_KEY[s.kind][0]], CLI_KEY[s.kind][2]),
          CLI_KEY_OPTIONAL[s.kind] && ai.settings.has_secret[CLI_KEY[s.kind][0]] ? h('label', {class: 'chk', style: 'margin-top:6px'},
            h('input', {type: 'checkbox', checked: !!s['clear_' + CLI_KEY[s.kind][0]], onchange: e => { s['clear_' + CLI_KEY[s.kind][0]] = e.target.checked; }}),
            'Forget my key and use this installation\'s Google login') : null,
          h('label', {class: 'f'}, 'Model ', h('small', {}, 'optional: empty = the CLI\'s default')),
          (() => { const el = h('input', {type: 'text', value: s.cli_model || '', placeholder: 'e.g. ' + CLI_KEY[s.kind][3]}); el.oninput = () => { s.cli_model = el.value; }; return el; })(),
          h('div', {class: 'hint'}, 'Runs need the ' + ai.kinds[s.kind] + ' service: docker compose --profile runners up -d' + (s.kind === 'antigravity' ? ' agent-antigravity' : '') + '. Costs show as tokens (these CLIs report no price).')] : null,
        s.kind === 'enterprise' ? [h('label', {class: 'f'}, 'Endpoint base URL'), (() => { const el = h('input', {type: 'text', value: s.base_url || '', placeholder: 'https://ai-gateway.contoso.com'});
          el.oninput = () => { s.base_url = el.value; }; return el; })(), h('label', {class: 'f'}, 'Token'), secretInput('enterprise_token', ai.settings.has_secret.enterprise_token, 'Bearer token')] : null,
        h('label', {class: 'f'}, 'Backup when this provider fails'),
        (() => { const sel = h('select', {class: 'sel'}, h('option', {value: '', selected: !s.backup}, `Organisation default${ai.policy_backup ? ' (' + ai.policy_backup + ')' : ' (none)'}`),
          ['claude_account', 'litellm'].filter(k => ai.kinds[k] && k !== s.kind).map(k => h('option', {value: k, selected: s.backup === k}, ai.kinds[k])));
          sel.onchange = () => { s.backup = sel.value || null; }; return sel; })(),
        h('div', {class: 'hint'}, 'Used once, automatically, when a run fails with a sign-in, quota, rate-limit or outage error; the activity log says so.'),
        h('div', {class: 'row', style: 'justify-content:flex-end;margin-top:14px'}, h('button', {class: 'btn primary', onclick: async () => {
          try { const r = await api('/api/me/ai', {method: 'PUT', json: s}); Object.assign(ai, r); Object.assign(s, r.settings);
            ['claude_oauth_token', 'anthropic_api_key', 'enterprise_token', 'openai_api_key', 'gemini_api_key'].forEach(f => { delete s[f]; delete s['clear_' + f]; }); await loadModels(); notify('AI provider saved', 'ok'); draw(); }
          catch (e) { notify(e.message, 'err'); } }}, 'Save'))),
      h('div', {class: 'card'}, h('h3', {}, 'My workspace'), workspaceCard(ws)));
  };
  draw();
  page.append(box, ...(await scheduleSettings().catch(e => [h('div', {class: 'note err'}, e.message)])), ...(await publishingSettings().catch(() => [])));
}

function workspaceCard(ws) {
  if (!ws.enabled) return h('div', {class: 'small'}, 'Runs use the shared agent of this installation. Personal workspaces (one per person, started at sign-in, stopped when idle) are switched off: ',
    h('code', {}, 'Relay_INSTANCES=off'), '.');
  const label = {running: 'Running', starting: 'Starting…', stopped: 'Stopped (starts again when you work)', queued: `Waiting for a free slot (#${ws.position})`, absent: 'Not created yet', error: 'Unavailable'}[ws.state] || ws.state;
  return h('div', {class: 'kv'}, h('dt', {}, 'Status'), h('dd', {}, label), h('dt', {}, 'Container'), h('dd', {class: 'mono'}, ws.name || '—'),
    h('dt', {}, 'Started'), h('dd', {}, ws.started && !ws.started.startsWith('0001') ? new Date(ws.started).toLocaleString() : '—'),
    h('dt', {}, 'Image'), h('dd', {}, ws.image_current === false ? 'Update waiting (applied at the next start)' : 'Current'));
}

/* "Starting your workspace" on sign-in, when personal workspaces are on */
async function ensureWorkspace() {
  let ws;
  try { ws = await api('/api/workspace'); } catch (e) { return; }
  if (!ws.enabled || ws.state === 'running') return;
  const msg = h('div', {class: 'muted small'}, 'Starting…');
  const overlay = h('div', {class: 'modal'}, h('div', {style: 'max-width:440px;padding:28px'},
    h('h2', {style: 'margin:0 0 6px'}, 'Starting your workspace'),
    h('div', {class: 'muted'}, 'Your workspace was paused while you were away. Everything is where you left it.'),
    h('div', {class: 'bar', style: 'display:block;margin:18px 0'}, h('i', {style: 'width:60%'})), msg));
  document.body.append(overlay);
  const t0 = Date.now();
  for (let i = 0; i < 300; i++) {
    try {
      const s = await api('/api/workspace/start', {method: 'POST'});
      msg.textContent = s.state === 'queued' ? `The host is busy: you are number ${s.position} in line.` : s.state === 'running' ? 'Ready' : `Starting… ${Math.round((Date.now() - t0) / 1000)}s`;
      if (s.state === 'running') break;
    } catch (e) { msg.textContent = e.message; }
    await new Promise(r => setTimeout(r, 2000));
  }
  overlay.remove();
}

/* admin: LiteLLM gateway routes */
async function adminGateway() {
  const d = await api('/api/admin/llm-routes');
  const items = d.routes.map(r => ({...r}));
  const creds = {};
  const list = h('div', {class: 'stack'});
  const PRESET = {bedrock: ['bedrock-sonnet', 'us.anthropic.claude-sonnet-4-5-20250929-v1:0', 'us-east-1'],
    azure_foundry: ['azure-sonnet', 'azure_ai/claude-sonnet-4-5', ''], vertex: ['vertex-sonnet', 'claude-sonnet-4-5@20250929', 'us-east5'],
    anthropic: ['anthropic-sonnet', 'claude-sonnet-4-5', '']};
  const draw = () => list.replaceChildren(...items.map((r, i) => {
    const inp = (k, ph) => { const el = h('input', {type: 'text', value: r[k] || '', placeholder: ph || ''}); el.oninput = () => { r[k] = el.value; }; return el; };
    const f = (label, el, hint) => h('div', {}, h('small', {class: 'muted'}, label), el, hint ? h('div', {class: 'hint'}, hint) : null);
    const teams = h('select', {class: 'sel', multiple: true, size: Math.min(4, d.teams.length || 1)}, d.teams.map(t => h('option', {value: t.id, selected: (r.teams || []).includes(t.id)}, t.name)));
    teams.onchange = () => { r.teams = [...teams.selectedOptions].map(o => o.value); };
    return h('div', {class: 'card flat', style: 'margin:0'},
      h('div', {class: 'row'}, h('b', {}, `${d.providers[r.provider]} · ${r.alias || 'new route'}`), h('span', {class: 'spacer'}),
        h('button', {class: 'btn sm ghost', onclick: () => { items.splice(i, 1); draw(); }}, icon('x'), 'Remove')),
      h('div', {class: 'opts', style: 'margin-top:8px'},
        f('Model name in Relay', inp('alias', 'bedrock-sonnet'), 'Lowercase; what Claude Code asks the gateway for.'), f('Label', inp('label', 'Claude Sonnet on Bedrock')),
        f("Provider's model id", inp('target'), r.provider === 'bedrock' ? 'Bedrock model or inference profile id' : r.provider === 'vertex' ? 'Vertex model id, e.g. claude-sonnet-4-5@20250929' : 'Deployment / model name'),
        r.provider === 'azure_foundry' || r.provider === 'anthropic' ? f('API base URL', inp('api_base', r.provider === 'azure_foundry' ? 'https://<resource>.services.ai.azure.com' : 'optional')) : f('Region', inp('region')),
        r.provider === 'vertex' ? f('Google Cloud project', inp('project')) : null,
        f('Small/fast model name (optional)', inp('small', 'e.g. bedrock-haiku'), 'Another route used for quick background calls.'),
        f('Teams that may use it', teams, 'None selected = every team.')));
  }));
  draw();
  const credBox = h('div', {class: 'opts'}, Object.entries(d.secrets).map(([prov, names]) => h('div', {class: 'card flat', style: 'margin:0'},
    h('b', {}, d.providers[prov]), names.map(n => { const has = d.routes.some(r => r.provider === prov && r.has_secrets && r.has_secrets[n]);
      const el = h('input', {type: n === 'service_account_json' ? 'text' : 'password', placeholder: has ? 'Stored — leave empty to keep' : n.replace(/_/g, ' '), autocomplete: 'off'});
      el.oninput = () => { (creds[prov] = creds[prov] || {})[n] = el.value; }; return h('div', {style: 'margin-top:6px'}, h('small', {class: 'muted'}, n.replace(/_/g, ' ')), el); }))));
  const add = prov => h('button', {class: 'btn sm', onclick: () => { const [alias, target, region] = PRESET[prov];
    items.push({alias, provider: prov, target, region, label: '', teams: [], api_base: '', project: '', small: ''}); draw(); }}, icon('plus'), d.providers[prov]);
  return h('div', {},
    h('div', {class: 'note small'}, icon('info'), ` People choose “LiteLLM gateway” under Settings › My AI provider. Each run gets a key signed for that run; the gateway (${d.gateway}) checks it and the route's teams.`),
    h('div', {class: 'row', style: 'margin:6px 0 10px'}, h('b', {}, 'Routes'), h('span', {class: 'spacer'}), ...Object.keys(d.providers).map(add)),
    items.length ? list : h('div', {class: 'card flat empty'}, 'No routes yet. Add Amazon Bedrock, Azure AI Foundry or Google Vertex AI.'),
    h('h3', {style: 'margin-top:18px'}, 'Provider credentials'), h('div', {class: 'hint', style: 'margin:-6px 0 10px'}, 'Stored encrypted; written only into the gateway\'s private config.'), credBox,
    h('div', {class: 'row', style: 'justify-content:flex-end;margin-top:12px'}, h('button', {class: 'btn primary', onclick: async () => {
      try { await api('/api/admin/llm-routes', {method: 'PUT', json: {routes: items.map(({has_secrets, ...r}) => r), credentials: creds}}); notify('Gateway routes saved; the gateway reloads', 'ok'); reAdmin(); }
      catch (e) { notify(e.message, 'err'); } }}, 'Save gateway')));
}

/* admin: personal workspaces (shown on the Instances tab) */
async function workspacesSection() {
  const d = await api('/api/admin/workspaces');
  if (!d.enabled) return h('div', {class: 'card flat'}, h('h3', {}, 'Personal workspaces'),
    h('div', {class: 'small'}, 'Off: every run uses the shared agent. Set ', h('code', {}, 'Relay_INSTANCES=on'), ' in .env and restart to give every person their own workspace, created at first sign-in and stopped after idle time.'));
  const act = (uid, a) => h('button', {class: 'btn sm', onclick: async () => { try { await api(`/api/admin/workspaces/${uid}/${a}`, {method: 'POST'}); notify(`Workspace ${a}`, 'ok'); reAdmin(); } catch (e) { notify(e.message, 'err'); } }}, a === 'start' ? 'Start' : 'Stop');
  return h('div', {class: 'card flat'}, h('h3', {}, `Personal workspaces · ${d.instances.filter(i => i.state === 'running').length} of ${d.max} running · stop after ${d.idle_minutes} min idle`),
    d.error ? h('div', {class: 'note err'}, d.error) : null,
    d.waiting && d.waiting.length ? h('div', {class: 'note warn'}, `${d.waiting.length} waiting for a free slot`) : null,
    h('table', {class: 'utable'}, h('tr', {}, ['Person', 'State', 'Started', 'Last active', 'Image', ''].map((t, i) => h('th', {class: i < 2 ? 'l' : ''}, t))),
      d.instances.map(i => h('tr', {}, h('td', {}, i.name_of_user || i.user), h('td', {}, h('span', {class: 'tag ' + (i.state === 'running' ? 'ok' : '')}, i.state)),
        h('td', {class: 'n'}, i.started && !i.started.startsWith('0001') ? new Date(i.started).toLocaleString() : '—'), h('td', {class: 'n'}, i.last_active ? ago(i.last_active) : '—'),
        h('td', {class: 'n'}, i.image_current ? 'current' : 'update at next start'), h('td', {style: 'text-align:right'}, act(i.user, i.state === 'running' ? 'stop' : 'start'))))));
}
