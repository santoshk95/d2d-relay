/* ---------------- D2D Relay: deployment (item 70). A published dashboard's Power BI file sent to the Power BI service
   (Microsoft Fabric) as the organisation's own Entra app, and its Power BI project pushed to GitHub, where a workflow
   deploys it to a Fabric workspace with Microsoft's fabric-cicd (webapp/app/deploy.py).
   deployCard(st)    for a published dashboard's Overview: publish or push it now, the last publishes and pushes with
                     their links and errors (it checks again every few seconds while one runs)
   deploySettings()  the organisation's settings (the card's Settings dialog): the workspace and automatic publishing,
                     the GitHub repository, its token and automatic pushing; owners change them, everyone else reads them
   deployConnectorCards()  item 77: the same two as connectors on the Connections page, Power BI service and GitHub
                     ---------------- */
const DEP_KIND = {powerbi: 'Power BI service', github: 'GitHub'};
const DEP_STATE = {queued: ['Waiting', 'run'], running: ['Running', 'run'], done: ['Done', 'ok'], error: ['Failed', 'err']};
const depOpen = r => r.status === 'queued' || r.status === 'running';
const depPill = r => { const [t, c] = DEP_STATE[r.status] || [r.status, '']; return h('span', {class: 'pill ' + c}, depOpen(r) && r.step ? r.step : t); };
const DEP_DATA_NOTE = 'The model goes with the data it held when the Power BI file was made. To refresh it in the service, the data must be '
  + 'reachable from there: a warehouse connection, or a gateway for files.';

function depResult(r) {
  if (depOpen(r)) return depPill(r);
  if (r.status === 'error') return h('div', {class: 'small deperr'}, r.error || 'It did not work.');
  const link = r.url ? h('a', {href: r.url, target: '_blank', rel: 'noopener'}, r.kind === 'github' ? `Commit ${r.commit || ''}` : 'Open the report') : null;
  return h('div', {class: 'small'}, depPill(r), link ? ' ' : null, link,
    r.kind === 'powerbi' && r.item_name ? h('div', {class: 'depnote'}, r.item_name) : null,
    r.kind === 'github' && r.path ? h('div', {class: 'depnote'}, r.path) : null,
    r.note ? h('div', {class: 'depnote'}, r.note) : null);
}

/* ---------------- a published dashboard's Overview ---------------- */
function deployCard(st) {
  const card = h('div', {class: 'card depcard'}, h('h3', {}, 'Deploy'), h('div', {class: 'muted small'}, 'Loading...'));
  const pid = encodeURIComponent(st.id);
  let timer = null, first = true;
  const load = async () => {
    clearTimeout(timer);
    if (!first && !card.isConnected) return;                 // the page moved on
    first = false;
    let d;
    try { d = await api(`/api/projects/${pid}/deploys`); }
    catch (e) { card.replaceChildren(h('h3', {}, 'Deploy'), h('div', {class: 'note err'}, e.message)); return; }
    draw(d);
    if (d.runs.some(depOpen)) timer = setTimeout(load, 3000);
  };
  const go = async (kind, btn) => {
    btn.disabled = true;
    try {
      const d = await api(`/api/projects/${pid}/deploy/${kind}`, {method: 'POST'});
      notify(kind === 'powerbi' ? 'Publishing to the Power BI service' : 'Pushing to GitHub', 'ok');
      draw(d);
      clearTimeout(timer); timer = setTimeout(load, 2000);
    } catch (e) { btn.disabled = false; notify(e.message, 'err'); }
  };
  const settings = () => {
    const m = modal('Deployment settings', h('div', {class: 'mbody'}, deploySettings()), true);
    new MutationObserver((_, o) => { if (!m.isConnected) { o.disconnect(); load(); } }).observe(document.body, {childList: true});
  };
  const section = (title, where, s, btn, hint) => h('div', {class: 'depsec'},
    h('div', {class: 'row', style: 'gap:8px'}, h('b', {}, title), s.auto ? h('span', {class: 'tag acc', title: 'As soon as its Power BI file is made'}, 'Automatic') : null),
    h('div', {class: 'small where'}, where),
    !s.ready && !s.running && s.why ? h('div', {class: 'small muted'}, s.why) : null,
    btn, h('div', {class: 'hint'}, hint));
  const draw = d => {
    const can = d.can && d.can.deploy, pb = d.powerbi, gh = d.github;
    const head = h('div', {class: 'row'}, h('h3', {style: 'margin:0'}, 'Deploy'), h('span', {class: 'spacer'}),
      d.can && d.can.manage ? h('button', {class: 'btn ghost sm', type: 'button', onclick: settings}, icon('gear'), 'Settings') : null);
    if (!d.published) return card.replaceChildren(head, h('div', {class: 'muted small', style: 'margin-top:6px'},
      'Once the dashboard is published, it can go to the Power BI service and to GitHub from here.'));
    let pbBtn = null, ghBtn = null;
    if (can) {
      pbBtn = h('button', {class: 'btn primary', type: 'button', disabled: !pb.ready}, icon('publish'), pb.running ? 'Publishing...' : 'Publish to Power BI');
      pbBtn.onclick = () => go('powerbi', pbBtn);
      ghBtn = h('button', {class: 'btn', type: 'button', disabled: !gh.ready}, icon('code'), gh.running ? 'Pushing...' : 'Push to GitHub');
      ghBtn.onclick = () => go('github', ghBtn);
    }
    const pbWhere = pb.workspace ? `Workspace: ${pb.workspace.name || pb.workspace.id}` : 'No workspace chosen yet.';
    const ghWhere = gh.repo ? `${gh.repo}, branch ${gh.branch}` + (gh.path ? `, folder ${gh.path}` : '') : 'No repository set up yet.';
    const rows = d.runs.slice(0, 10);
    card.replaceChildren(head,
      h('div', {class: 'depgrid'},
        section('Power BI service', pbWhere, pb, pbBtn, 'Publishes the Power BI file to the workspace as your organisation\'s Entra app, which needs Member '
          + 'or Contributor there. A report of the same name in the workspace is replaced. ' + DEP_DATA_NOTE),
        section('GitHub', ghWhere, gh, ghBtn, 'Commits the dashboard\'s Power BI project (the report and semantic model definitions, no data files) to '
          + 'the repository. The workflow D2D Relay adds there deploys it to a Fabric workspace.')),
      can ? '' : h('div', {class: 'small muted', style: 'margin-top:8px'}, 'Your account can see what was deployed. Someone who can publish this dashboard sends it.'),
      rows.length ? h('div', {class: 'depwrap'}, h('table', {class: 'utable deptable'},
        h('thead', {}, h('tr', {}, ['When', 'Where', 'By', 'Result'].map((t, i) => h('th', {class: 'l' + (i === 2 ? ' by' : '')}, t)))),
        h('tbody', {}, rows.map(r => h('tr', {},
          h('td', {class: 'small', title: when(r.created)}, ago(r.created)),
          h('td', {}, DEP_KIND[r.kind] || r.kind, r.target_name ? h('div', {class: 'small muted'}, r.target_name) : null),
          h('td', {class: 'small by'}, r.by || (r.via === 'auto' ? 'Automatic' : '-')),
          h('td', {}, depResult(r)))))))
        : h('div', {class: 'muted small', style: 'margin-top:10px'}, 'Nothing published or pushed yet.'));
  };
  load();
  return card;
}

/* ---------------- the organisation's settings ---------------- */
function deploySettings() {
  const box = h('div', {class: 'depset'}, h('div', {class: 'card'}, h('h3', {}, 'Deployment'), h('div', {class: 'muted small'}, 'Loading...')));
  const load = async () => {
    let d;
    try { d = await api('/api/deploy/settings'); }
    catch (e) { box.replaceChildren(h('div', {class: 'card'}, h('h3', {}, 'Deployment'), h('div', {class: 'note err'}, e.message))); return; }
    box.replaceChildren(depPowerBiSettings(d, load), depGitHubSettings(d, load));
  };
  load();
  return box;
}

function depPowerBiSettings(d, reload) {
  const p = d.powerbi, own = d.can_manage;
  const card = h('div', {class: 'card'}, h('h3', {}, 'Publish to the Power BI service'),
    h('p', {class: 'small muted', style: 'margin-top:0'}, 'A published dashboard\'s Power BI file goes to a workspace in the Power BI service (Microsoft Fabric), '
      + 'as your organisation\'s own Entra app: the one Semantic Review uses. Add the app to the workspace as Member or Contributor.'));
  if (!p.connected) {
    card.append(h('div', {class: 'note'}, own ? 'Connect Power BI first: enter your organisation\'s Entra app under Semantic Review (Connect Power BI).'
      : 'Not set up yet: an owner of your organisation connects Power BI under Semantic Review.'),
      own ? h('a', {class: 'btn', href: '#/review'}, icon('plug'), 'Open Semantic Review') : '');     // '' not null: append writes null as text
    return card;
  }
  if (!own) {
    card.append(h('dl', {class: 'kv'}, h('dt', {}, 'Workspace'), h('dd', {}, p.workspace_name || 'None chosen yet'),
      h('dt', {}, 'Automatic'), h('dd', {}, p.auto ? 'Every dashboard is published as soon as its Power BI file is made' : 'Off: dashboards are published from their Overview')),
      h('div', {class: 'hint'}, 'An owner of your organisation changes these.'));
    return card;
  }
  const sel = h('select', {class: 'sel', 'aria-label': 'Workspace'}, h('option', {value: p.workspace_id || ''}, p.workspace_name || 'Loading the workspaces...'));
  const auto = h('input', {type: 'checkbox', checked: p.auto});
  const out = h('div', {role: 'status'});
  const save = h('button', {class: 'btn primary', type: 'button'}, 'Save');
  (async () => {
    try {
      const ws = (await api('/api/deploy/powerbi/workspaces')).workspaces;
      sel.replaceChildren(h('option', {value: ''}, ws.length ? 'Choose a workspace' : 'The app sees no workspace yet'),
        ...ws.map(w => h('option', {value: w.id, selected: w.id === p.workspace_id}, w.name)));
      if (p.workspace_id && !ws.some(w => w.id === p.workspace_id))
        sel.append(h('option', {value: p.workspace_id, selected: true}, `${p.workspace_name || p.workspace_id} (the app does not see it now)`));
    } catch (e) { out.replaceChildren(h('div', {class: 'note err'}, e.message)); }
  })();
  save.onclick = async () => {
    save.disabled = true;
    try { await api('/api/deploy/settings', {method: 'PUT', json: {powerbi: {workspace_id: sel.value || null, auto: auto.checked}}}); notify('Saved', 'ok'); reload(); }
    catch (e) { out.replaceChildren(h('div', {class: 'note err'}, e.message)); save.disabled = false; }
  };
  card.append(h('label', {class: 'f'}, 'Workspace'), sel,
    h('label', {class: 'chk depchk'}, auto, h('span', {}, 'Publish every dashboard to this workspace as soon as its Power BI file is made')),
    h('div', {class: 'hint'}, 'A report of the same name in the workspace is replaced. ' + DEP_DATA_NOTE),
    out, h('div', {class: 'row depbtns'}, save));
  return card;
}

function depGitHubSettings(d, reload) {
  const g = d.github, own = d.can_manage;
  const card = h('div', {class: 'card'}, h('h3', {}, 'CI/CD with GitHub'),
    h('p', {class: 'small muted', style: 'margin-top:0'}, 'Push to GitHub commits a published dashboard\'s Power BI project (the report and the semantic model, '
      + 'no data files) to a repository of yours. With the first push, D2D Relay adds a GitHub Actions workflow there that deploys each changed '
      + 'dashboard to a Fabric workspace with Microsoft\'s fabric-cicd.'));
  const secretsNote = h('div', {class: 'note depsecrets'}, 'For the workflow, add these repository secrets on GitHub (Settings, Secrets and variables, Actions): ',
    (g.secrets || []).map((s, i) => [i ? ', ' : '', h('code', {}, s)]),
    '. The first three are an Entra app (a service principal) that is Contributor on the workspace; the last is that workspace\'s id.');
  if (!own) {
    card.append(g.repo ? h('dl', {class: 'kv'}, h('dt', {}, 'Repository'), h('dd', {}, g.repo), h('dt', {}, 'Branch'), h('dd', {}, g.branch),
        h('dt', {}, 'Folder'), h('dd', {}, g.folder), h('dt', {}, 'Automatic'), h('dd', {}, g.auto ? 'Every dashboard is pushed as soon as its Power BI file is made' : 'Off'))
      : h('div', {class: 'muted small'}, 'Not set up yet.'),
      g.repo ? secretsNote : '', h('div', {class: 'hint'}, 'An owner of your organisation changes these.'));
    return card;
  }
  const field = (value, placeholder) => h('input', {type: 'text', value: value || '', placeholder, autocomplete: 'off', spellcheck: 'false'});
  const repo = field(g.repo, 'owner/repository, for example contoso/bi-dashboards');
  const branch = field(g.branch || 'main', 'main');
  const folder = field(g.folder || 'd2d-relay', 'd2d-relay');
  const tok = h('input', {type: 'password', value: '', placeholder: g.has_token ? 'Kept - enter a new one to change it' : 'github_pat_...', autocomplete: 'new-password'});
  const auto = h('input', {type: 'checkbox', checked: g.auto});
  const out = h('div', {role: 'status'});
  const save = h('button', {class: 'btn primary', type: 'button'}, 'Save');
  const test = h('button', {class: 'btn', type: 'button'}, 'Test');
  const remove = g.repo || g.has_token ? h('button', {class: 'btn danger', type: 'button'}, 'Remove') : null;
  const form = () => ({repo: repo.value.trim(), branch: branch.value.trim(), folder: folder.value.trim(), token: tok.value.trim() || null});
  save.onclick = async () => {
    save.disabled = true;
    try { await api('/api/deploy/settings', {method: 'PUT', json: {github: {...form(), auto: auto.checked}}}); notify('Saved', 'ok'); reload(); }
    catch (e) { out.replaceChildren(h('div', {class: 'note err'}, e.message)); save.disabled = false; }
  };
  test.onclick = async () => {
    test.disabled = true; out.replaceChildren(h('div', {class: 'note'}, 'Asking GitHub...'));
    try {
      const f = form(), t = await api('/api/deploy/github/test', {method: 'POST', json: {repo: f.repo, branch: f.branch, token: f.token}});
      const same = (g.repo || '').toLowerCase() === (t.repo || '').toLowerCase();
      out.replaceChildren(h('div', {class: 'note ok'}, `Connected to ${t.repo}${t.private ? ' (private)' : ''}: the token can write to it. `
        + (t.branch_exists ? `The branch ${t.branch} is there. ` : `The branch ${t.branch} does not exist yet: the first push makes it from ${t.default_branch}. `)
        + (t.workflow_exists ? 'The deployment workflow is there already.' : g.workflow_added && same ? '' : 'The first push adds the deployment workflow.')));
    } catch (e) { out.replaceChildren(h('div', {class: 'note err'}, e.message)); }
    test.disabled = false;
  };
  if (remove) remove.onclick = async () => {
    if (!confirm('Remove the GitHub repository and its token? What was pushed stays on GitHub.')) return;
    try { await api('/api/deploy/github', {method: 'DELETE'}); notify('GitHub settings removed', 'ok'); reload(); }
    catch (e) { out.replaceChildren(h('div', {class: 'note err'}, e.message)); }
  };
  card.append(h('label', {class: 'f'}, 'Repository'), repo,
    h('div', {class: 'depcols'}, h('div', {}, h('label', {class: 'f'}, 'Branch'), branch), h('div', {}, h('label', {class: 'f'}, 'Folder'), folder)),
    h('div', {class: 'hint'}, 'Each dashboard goes to its own folder in it: <folder>/<dashboard name>/. D2D Relay replaces that folder with each push.'),
    h('label', {class: 'f'}, 'Token'), tok,
    h('div', {class: 'hint'}, 'A fine-grained personal access token for this repository only, with Contents: Read and write, and Workflows: Read and '
      + 'write (for the workflow file, added once). It is kept encrypted and never shown again.'),
    h('label', {class: 'chk depchk'}, auto, h('span', {}, 'Push every dashboard as soon as its Power BI file is made')),
    secretsNote,
    g.workflow_added ? h('div', {class: 'hint'}, `The workflow (${g.workflow}) is in this repository; D2D Relay does not change it again.`) : '',
    out, h('div', {class: 'row depbtns'}, remove, h('span', {class: 'spacer'}), test, save));
  return card;
}

/* ---------------- item 77 (the user, 2026-11-19: "github is a connector [that] needs to be available for the customer to
   configure ci/cd and auto deployment to power bi service"): the two deployment connectors on the Connections page.
   Every organisation has them (PASDACS switches nothing on); its owners set them up, everyone else sees how they are
   set. Power BI service: the organisation's own Entra app (the one Semantic Review reads with: pbiDialog, 40-review.js)
   and the workspace dashboards are published to. GitHub: the repository and its token, for CI/CD with fabric-cicd. */
function deployConnectorCards() {
  const box = h('div', {class: 'conncat depconn'}, h('div', {class: 'card'}, h('div', {class: 'muted small'}, 'Loading...')));
  const load = async () => {
    let d, p;
    try { d = await api('/api/deploy/settings'); }
    catch (e) { box.replaceChildren(h('div', {class: 'card'}, h('div', {class: 'note err'}, e.message))); return; }
    try { p = await api('/api/semreview/pbi'); } catch (e) { p = {configured: !!d.powerbi.connected}; }
    if (!box.isConnected && box.dataset.drawn) return;                 // the page moved on
    box.dataset.drawn = '1';
    const own = d.can_manage, pb = d.powerbi, gh = d.github;
    const pbOn = !!p.configured, ghOn = !!(gh.repo && gh.has_token);
    const dialog = (title, make) => {          // the settings in a dialog; saving there draws it and these cards again
      const body = h('div', {class: 'mbody depset'});
      const fill = async () => {
        try { body.replaceChildren(make(await api('/api/deploy/settings'), fill)); }
        catch (e) { body.replaceChildren(h('div', {class: 'note err'}, e.message)); }
        load();
      };
      body.append(make(d, fill));
      modal(title, body, true);
    };
    const kv = (rows) => h('dl', {class: 'kv'}, rows.map(([t, v]) => [h('dt', {}, t), h('dd', {}, v)]));
    const state = (on, text) => h('span', {class: 'tag' + (on ? ' ok' : '')}, text);
    const pbCard = h('div', {class: 'card' + (pbOn ? ' on' : ''), id: 'conn-powerbi'},
      h('div', {class: 'row', style: 'gap:8px;align-items:center;flex-wrap:nowrap'}, icon('publish'), h('b', {}, 'Power BI service'), h('span', {class: 'spacer'}),
        pbOn ? state(true, pb.workspace_id ? 'Connected' : 'Connected, no workspace yet') : state(false, 'Not set up')),
      h('div', {class: 'small muted', style: 'margin:6px 0 8px'}, 'Publishes each dashboard to a workspace in the Power BI service (Microsoft Fabric) '
        + 'with your organisation\'s own Entra app: from the dashboard, or by itself as soon as its Power BI file is made. Semantic Review reads your '
        + 'models with the same app.'),
      kv([['Entra app', pbOn && p.client_id ? `${p.client_id}, tenant ${p.tenant}` : pbOn ? 'Connected' : 'Not connected yet'],
        ['Workspace', pb.workspace_name || 'None chosen yet'], ['Automatic', pb.auto ? 'On: each new Power BI file is published' : 'Off']]),
      h('span', {class: 'grow'}),
      own ? h('div', {class: 'row', style: 'gap:8px;margin-top:10px;flex-wrap:wrap'},
          typeof pbiDialog === 'function' ? h('button', {class: 'btn sm' + (pbOn ? '' : ' primary'), type: 'button', onclick: () => pbiDialog(p, load)},
            icon('plug'), pbOn ? 'Entra app' : 'Connect Power BI') : '',
          pbOn ? h('button', {class: 'btn sm primary', type: 'button', onclick: () => dialog('Publish to the Power BI service', depPowerBiSettings)},
            icon('gear'), 'Workspace and automatic publishing') : '')
        : h('div', {class: 'row', style: 'gap:8px;margin-top:10px;flex-wrap:wrap;align-items:center'},
          h('button', {class: 'btn sm', type: 'button', onclick: () => dialog('Publish to the Power BI service', depPowerBiSettings)}, 'Details'),
          h('span', {class: 'small muted'}, 'An owner of your organisation sets this up.')));
    const ghCard = h('div', {class: 'card' + (ghOn ? ' on' : ''), id: 'conn-github'},
      h('div', {class: 'row', style: 'gap:8px;align-items:center;flex-wrap:nowrap'}, icon('code'), h('b', {}, 'GitHub'), h('span', {class: 'spacer'}),
        ghOn ? state(true, 'Connected') : state(false, 'Not set up')),
      h('div', {class: 'small muted', style: 'margin:6px 0 8px'}, 'CI/CD: pushes each dashboard\'s Power BI project (the report and the semantic model, '
        + 'no data files) to a repository of yours. The GitHub Actions workflow D2D Relay adds there deploys it to a Fabric workspace with '
        + 'Microsoft\'s fabric-cicd.'),
      kv([['Repository', gh.repo ? `${gh.repo}, branch ${gh.branch}, folder ${gh.folder}` : 'None yet'],
        ['Automatic', gh.auto ? 'On: each new Power BI file is pushed' : 'Off'],
        ['Workflow', gh.workflow_added ? `In the repository (${gh.workflow})` : 'Added with the first push']]),
      h('span', {class: 'grow'}),
      h('div', {class: 'row', style: 'gap:8px;margin-top:10px;flex-wrap:wrap;align-items:center'},
        h('button', {class: 'btn sm' + (own && !ghOn ? ' primary' : ''), type: 'button', onclick: () => dialog('CI/CD with GitHub', depGitHubSettings)},
          own ? icon('gear') : '', own ? (ghOn ? 'Change' : 'Set up') : 'Details'),
        own ? '' : h('span', {class: 'small muted'}, 'An owner of your organisation sets this up.')));
    box.replaceChildren(pbCard, ghCard);
  };
  load();
  return box;
}
