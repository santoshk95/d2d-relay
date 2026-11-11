/* ---------------- phase 6: review before publish, GitHub, exports, channels, insight pages ---------------- */
const REVIEW_STATE = {pending: ['Waiting for review', 'warn'], approved: ['Approved', 'ok'], changes: ['Changes requested', 'err'], replaced: ['Replaced', '']};

function reviewCard(st) {
  const card = h('div', {class: 'card'}, h('h3', {}, 'Review'), skel('rows'));
  api(`/api/projects/${st.id}/reviews`).then(d => {
    const can = st.access && st.access.can_edit, mine = S.me && S.me.id;
    const latest = st.versions.length ? st.versions[st.versions.length - 1].v : null;
    const req = () => {
      const ver = h('select', {class: 'sel'}, st.versions.slice().reverse().map(v => h('option', {value: v.v}, `v${v.v}${v.label ? ' · ' + v.label : ''}`)));
      const who = h('select', {class: 'sel'}, d.reviewers.map(r => h('option', {value: r.id}, r.name)));
      const note = h('textarea', {rows: 3, placeholder: 'What should the reviewer look at?'});
      const m = modal('Request a review', h('div', {class: 'mbody'}, h('div', {class: 'opts'}, h('div', {}, h('label', {class: 'f', style: 'margin-top:0'}, 'Version'), ver),
        h('div', {}, h('label', {class: 'f', style: 'margin-top:0'}, 'Reviewer'), who)), h('label', {class: 'f'}, 'Note'), note,
        h('div', {class: 'hint'}, 'The reviewer gets view access if they did not have it.'),
        h('div', {class: 'row', style: 'justify-content:flex-end;margin-top:12px'}, h('button', {class: 'btn', onclick: () => m.remove()}, 'Cancel'),
          h('button', {class: 'btn primary', onclick: async () => { try { await api(`/api/projects/${st.id}/reviews`, {json: {version: +ver.value, reviewer: who.value, note: note.value}});
            notify('Review requested', 'ok'); m.remove(); S.key = null; render(); } catch (e) { notify(e.message, 'err'); } }}, 'Request review'))));
    };
    const rows = d.reviews.slice().reverse().filter(r => r.status !== 'replaced').slice(0, 4).map(r => {
      const comment = h('input', {type: 'text', placeholder: 'Comment…'});
      const act = decision => async () => { try { await api(`/api/reviews/${st.id}/${r.id}`, {json: {decision, comment: comment.value}}); notify(decision ? (decision === 'approve' ? 'Approved' : 'Changes requested') : 'Comment added', 'ok'); S.key = null; render(); } catch (e) { notify(e.message, 'err'); } };
      const [label, kind] = REVIEW_STATE[r.status] || [r.status, ''];
      return h('div', {class: 'cv'}, h('div', {class: 'ttl'}, h('b', {}, `v${r.v}`), h('span', {class: 'tag ' + kind}, label),
          h('span', {class: 'muted small'}, `${r.requested_by_name} asked ${r.reviewer_name} · ${ago(r.requested)}`)),
        r.comments.map(c => h('div', {class: 'small', style: 'margin-top:4px'}, h('b', {}, c.who_name + ': '), c.text)),
        r.status === 'pending' && (r.reviewer === mine || (S.me && S.me.admin && r.requested_by !== mine)) ? h('div', {class: 'row', style: 'margin-top:8px;flex-wrap:nowrap'}, comment,
          h('button', {class: 'btn', onclick: act('changes')}, 'Request changes'), h('button', {class: 'btn primary', onclick: act('approve')}, 'Approve')) :
        r.status === 'pending' ? h('div', {class: 'row', style: 'margin-top:8px;flex-wrap:nowrap'}, comment, h('button', {class: 'btn', onclick: act(null)}, 'Comment')) : null);
    });
    card.replaceChildren(...[h('div', {class: 'row'}, h('h3', {style: 'margin:0'}, 'Review'), d.policy.review_required ? h('span', {class: 'tag acc'}, 'Required before publishing') : h('span', {class: 'tag'}, 'Optional'),
        h('span', {class: 'spacer'}), can && latest && d.reviewers.length ? h('button', {class: 'btn', onclick: req}, 'Request review') : null),
      rows.length ? h('div', {}, rows) : h('div', {class: 'muted small'}, 'No review yet. Development → review → published: ask another BI Dev / Analyst to review a version before you publish it.')].filter(Boolean));
  }).catch(() => card.remove());
  return card;
}

function publishCard(st) {
  const card = h('div', {class: 'card'});
  const last = (st.publishes || [])[(st.publishes || []).length - 1] || {};
  const exp = fmt => async e => { e.target.disabled = true; notify(`Drawing the ${fmt.toUpperCase()}…`);
    try { const r = await fetch(`/api/export/project/${st.id}?fmt=${fmt}`, {method: 'POST'}); if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || 'Export failed');
      h('a', {href: URL.createObjectURL(await r.blob()), download: `${st.name}.${fmt}`}).click(); } catch (err) { notify(err.message, 'err'); } e.target.disabled = false; };
  // D2D Relay: the prototype as PDF / PNG, and a post to a channel (GitHub and insight pages are not part of D2D Relay)
  card.append(h('div', {class: 'row'}, h('h3', {style: 'margin:0'}, 'Publish & share'), h('span', {class: 'spacer'}),
      h('button', {class: 'btn', onclick: exp('pdf')}, icon('download'), 'PDF'), h('button', {class: 'btn', onclick: exp('png')}, icon('download'), 'PNG'),
      h('button', {class: 'btn', onclick: () => channelDialog('project', st.id, st.name)}, icon('share'), 'Post to a channel')),
    last.v ? h('div', {class: 'small muted', style: 'margin-top:8px'}, `Published v${last.v} ${ago(last.when)}` + (last.review ? ' · reviewed and approved' : '')
      + ((last.github || []).length ? ` · on GitHub: ` : '')) : h('div', {class: 'small muted', style: 'margin-top:8px'}, 'PDF and PNG draw the prototype in a headless browser. Approving a version gives you the Power BI file (.pbix) to download; Relay does not publish to the Power BI Service.'),
    ...((last.github || []).map(g => h('div', {class: 'small'}, icon('check'), ' ', h('a', {href: g.url, target: '_blank', rel: 'noopener'}, `${g.repo}@${g.branch} ${g.commit.slice(0, 7)}`), ` · ${g.files} files · ${ago(g.when)}`))));
  return card;
}

async function githubDialog(st) {
  let gh;
  try { gh = await api('/api/me/github'); } catch (e) { return notify(e.message, 'err'); }
  if (!gh.connected) return modal('Version to GitHub', h('div', {class: 'mbody'}, h('p', {}, gh.app_ready ? 'Connect your own GitHub account first; Relay commits with it, to a repository you choose.' : 'Your administrator has not set up GitHub yet (Admin › Publishing).'),
    gh.app_ready ? h('a', {class: 'btn primary', href: '/api/me/github/start'}, 'Connect GitHub') : null));
  const body = h('div', {class: 'mbody'}, h('div', {class: 'muted small'}, 'Loading your repositories…'));
  const m = modal(`Version “${st.name}” v${st.approved} to GitHub`, body);
  try {
    const {repos} = await api('/api/me/github/repos');
    const repo = h('select', {class: 'sel'}, repos.filter(r => r.can_push).map(r => h('option', {value: r.full_name, selected: r.full_name === gh.default_repo}, r.full_name + (r.private ? ' (private)' : ''))));
    const branch = h('input', {type: 'text', value: 'main'}), folder = h('input', {type: 'text', value: (st.name || '').replace(/[^\w -]+/g, '').trim()});
    const msg = h('input', {type: 'text', value: `${st.name} v${st.approved} (Relay)`});
    body.replaceChildren(h('div', {class: 'small'}, `Signed in to GitHub as ${gh.login}. The commit contains definition.yaml, the report's files and the check reports.`),
      h('label', {class: 'f'}, 'Repository'), repo, h('div', {class: 'opts'}, h('div', {}, h('label', {class: 'f'}, 'Branch'), branch, h('div', {class: 'hint'}, 'Created from the default branch if new.')),
        h('div', {}, h('label', {class: 'f'}, 'Folder in the repository'), folder)), h('label', {class: 'f'}, 'Commit message'), msg,
      h('div', {class: 'row', style: 'justify-content:flex-end;margin-top:12px'}, h('button', {class: 'btn', onclick: () => m.remove()}, 'Cancel'),
        h('button', {class: 'btn primary', onclick: async e => { e.target.disabled = true; try { const r = await api(`/api/projects/${st.id}/github`, {json: {repo: repo.value, branch: branch.value, folder: folder.value, message: msg.value}});
          notify(`Pushed ${r.files} files to ${r.repo}@${r.branch}`, 'ok'); m.remove(); S.key = null; poll(); } catch (err) { notify(err.message, 'err'); e.target.disabled = false; } }}, 'Commit and push')));
  } catch (e) { body.replaceChildren(h('div', {class: 'note err'}, e.message)); }
}

async function channelDialog(kind, id, title) {
  const {channels} = await api('/api/me/channels');
  if (!channels.length) return modal('Post to a channel', h('div', {class: 'mbody'}, 'Add a Slack or Teams channel first (Settings › Channels).', h('div', {style: 'margin-top:10px'}, h('a', {class: 'btn', href: '#/settings'}, 'Open Settings'))));
  const sel = h('select', {class: 'sel'}, channels.map(c => h('option', {value: c.id}, `${c.name} · ${c.kind}`)));
  const text = h('textarea', {rows: 3, placeholder: 'A line about what to look at (optional)'});
  const m = modal(`Post “${title}”`, h('div', {class: 'mbody'}, h('label', {class: 'f', style: 'margin-top:0'}, 'Channel'), sel, h('label', {class: 'f'}, 'Message'), text,
    h('div', {class: 'hint'}, 'The post carries a link back to Relay: people still sign in, and see it only if it is shared with them.'),
    h('div', {class: 'row', style: 'justify-content:flex-end;margin-top:12px'}, h('button', {class: 'btn', onclick: () => m.remove()}, 'Cancel'),
      h('button', {class: 'btn primary', onclick: async () => { try { await api('/api/share/channel', {json: {channel: sel.value, kind, id, text: text.value}}); notify('Posted', 'ok'); m.remove(); } catch (e) { notify(e.message, 'err'); } }}, 'Post'))));
}

/* settings: GitHub and channels */
async function publishingSettings() {
  const [gh, ch] = await Promise.all([api('/api/me/github'), api('/api/me/channels')]);
  const name = h('input', {type: 'text', placeholder: 'Retail leads'}), url = h('input', {type: 'password', placeholder: 'https://hooks.slack.com/services/…'});
  const kind = h('select', {class: 'sel', 'aria-label': 'Channel type'}, h('option', {value: 'slack'}, 'Slack'), h('option', {value: 'teams'}, 'Microsoft Teams (workflow webhook)'));
  return [h('div', {class: 'card'}, h('h3', {}, 'GitHub'), gh.connected
      ? h('div', {class: 'row'}, h('span', {}, `Connected as ${gh.login}`), h('span', {class: 'spacer'}), h('button', {class: 'btn', onclick: async () => { await api('/api/me/github', {method: 'DELETE'}); renderSettings(); }}, 'Disconnect'))
      : gh.app_ready ? h('div', {class: 'row'}, h('span', {class: 'muted small'}, 'Version published dashboards to your own repositories.'), h('span', {class: 'spacer'}), h('a', {class: 'btn primary', href: '/api/me/github/start'}, 'Connect GitHub'))
        : h('div', {class: 'muted small'}, 'Your administrator has not set up GitHub yet.')),
    h('div', {class: 'card'}, h('h3', {}, 'Channels'), h('div', {class: 'muted small', style: 'margin-bottom:8px'}, 'Your own Slack or Teams incoming webhooks: share dashboards and pages there with a link back to Relay.'),
      ch.channels.length ? h('div', {class: 'stack', style: 'gap:4px'}, ch.channels.map(c => h('div', {class: 'row'}, h('b', {}, c.name), h('span', {class: 'tag'}, c.kind), h('span', {class: 'spacer'}),
        h('button', {class: 'btn sm ghost', onclick: async () => { await api(`/api/me/channels/${c.id}`, {method: 'DELETE'}); renderSettings(); }}, icon('x'))))) : null,
      h('div', {class: 'opts', style: 'grid-template-columns:1fr 1fr 2fr;margin-top:8px'}, name, kind, url),
      h('div', {class: 'row', style: 'justify-content:flex-end;margin-top:8px'}, h('button', {class: 'btn', onclick: async () => { try { await api('/api/me/channels', {json: {name: name.value, kind: kind.value, url: url.value}}); notify('Channel added', 'ok'); renderSettings(); } catch (e) { notify(e.message, 'err'); } }}, icon('plus'), 'Add channel')))];
}

/* admin: publishing */
async function adminPublishing() {
  const d = await api('/api/admin/publishing');
  const req = h('input', {type: 'checkbox', checked: d.policy.review_required});
  const cid = h('input', {type: 'text', value: d.github.client_id || '', placeholder: 'GitHub OAuth app client id'});
  const sec = h('input', {type: 'password', placeholder: d.github.has_secret ? 'Stored — leave empty to keep' : 'client secret'});
  const cb = `${location.origin}/auth/github/callback`;
  return h('div', {}, h('div', {class: 'card flat'}, h('h3', {}, 'Publishing'), h('label', {class: 'chk'}, req, 'A version must be reviewed and approved by someone other than the publisher before it is published'),
      h('div', {class: 'hint'}, 'Off: anyone who can edit a dashboard publishes it (reviews stay optional). Relay never publishes to the Power BI Service: publishing produces the Power BI file (.pbix) to download.')),
    h('div', {class: 'card flat'}, h('h3', {}, 'GitHub'), h('div', {class: 'hint', style: 'margin:-6px 0 8px'}, 'Register a GitHub OAuth app (GitHub › Settings › Developer settings) with this callback URL; each person then connects their own account.'),
      h('div', {class: 'path'}, h('code', {}, cb), copyBtn(cb)), h('div', {class: 'opts', style: 'margin-top:8px'}, cid, sec)),
    h('div', {class: 'row', style: 'justify-content:flex-end'}, h('button', {class: 'btn primary', onclick: async () => {
      try { await api('/api/admin/publishing', {method: 'PUT', json: {review_required: req.checked, github_client_id: cid.value, github_client_secret: sec.value || null}}); notify('Saved', 'ok'); reAdmin(); }
      catch (e) { notify(e.message, 'err'); } }}, 'Save')));
}

/* insight pages */
async function renderPages() {
  const pid = (location.hash.split('/')[2] || '').split('?')[0];
  if (pid) return renderPage(pid);
  const page = h('div', {class: 'page'});
  $('#main').replaceChildren(page);
  const d = await api('/api/pages').catch(e => ({error: e.message}));
  if (d.error) return page.append(h('div', {class: 'note err'}, d.error));
  page.append(h('div', {class: 'phead'}, h('div', {style: 'flex:1'}, h('h1', {}, 'Pages'), h('div', {class: 'meta'}, 'Insight pages made from Ask D answers and dashboards — private until you share them.')),
      h('button', {class: 'btn primary', onclick: async () => { const p = await api('/api/pages', {json: {title: 'New page', source: {kind: 'blank'}}}); location.hash = `#/pages/${p.id}`; }}, icon('plus'), 'New page')),
    d.pages.length ? h('div', {class: 'grid'}, d.pages.map(p => h('a', {class: 'dcard', href: `#/pages/${p.id}`}, h('div', {class: 'n'}, p.title),
      h('div', {class: 'f'}, h('span', {}, `${p.blocks} block(s)`), h('span', {}, p.access === 'owner' ? 'Yours' : `by ${p.owner}`),
        h('span', {}, icon(p.visibility === 'private' ? 'lock' : p.visibility === 'org' ? 'globe' : 'users')), h('span', {class: 'spacer'}), h('span', {}, ago(p.updated))))))
      : h('div', {class: 'card empty'}, h('h3', {}, 'No pages yet'), 'In Ask D, press “Save as page” on an answer or a conversation; on a dashboard, “Make a page”.'));
}

async function renderPage(id) {
  const page = h('div', {class: 'page'});
  $('#main').replaceChildren(page);
  let p;
  try { p = await api(`/api/pages/${id}`); } catch (e) { return page.append(h('div', {class: 'card empty'}, h('h3', {}, 'Page not found'), h('a', {href: '#/pages'}, 'All pages'))); }
  const can = p.access === 'owner' || p.access === 'edit';
  let blocks = p.body.slice();
  const save = async () => { try { p = await api(`/api/pages/${id}`, {method: 'PUT', json: {title: titleIn.value, blocks}}); blocks = p.body.slice(); notify('Saved', 'ok'); draw(); } catch (e) { notify(e.message, 'err'); } };
  const titleIn = h('input', {type: 'text', value: p.title, style: 'font-size:22px;font-weight:650;border:0;background:transparent;padding:0', disabled: !can});
  titleIn.onchange = save;
  const body = h('div', {class: 'stack'});
  const exp = fmt => async () => { notify(`Drawing the ${fmt.toUpperCase()}…`); try { const r = await fetch(`/api/pages/${id}/export?fmt=${fmt}`, {method: 'POST'}); if (!r.ok) throw new Error('Export failed');
    h('a', {href: URL.createObjectURL(await r.blob()), download: `${p.title}.${fmt}`}).click(); } catch (e) { notify(e.message, 'err'); } };
  function block(b, i) {
    const tools = can ? h('div', {class: 'row', style: 'justify-content:flex-end;gap:4px'},
      i > 0 ? h('button', {class: 'btn sm ghost', onclick: () => { [blocks[i - 1], blocks[i]] = [blocks[i], blocks[i - 1]]; save(); }}, '↑') : null,
      i < blocks.length - 1 ? h('button', {class: 'btn sm ghost', onclick: () => { [blocks[i + 1], blocks[i]] = [blocks[i], blocks[i + 1]]; save(); }}, '↓') : null,
      h('button', {class: 'btn sm ghost', onclick: () => { blocks.splice(i, 1); save(); }}, icon('x'))) : null;
    if (b.type === 'text') {
      if (!can) return h('div', {class: 'card', style: 'margin:0'}, rich(b.text));
      const ta = h('textarea', {rows: 3}, b.text); ta.onchange = () => { blocks[i] = {type: 'text', text: ta.value}; save(); };
      return h('div', {class: 'card', style: 'margin:0'}, tools, ta);
    }
    if (b.type === 'prototype') return h('div', {class: 'card', style: 'margin:0'}, tools, h('div', {class: 'row'}, h('b', {}, `${b.name} · v${b.version}`), h('span', {class: 'spacer'}), h('a', {href: `#/p/${b.project}`}, 'Open dashboard →')),
      h('div', {class: 'proto', style: 'height:620px'}, h('iframe', {src: `/api/projects/${b.project}/prototype/${b.version}`, style: 'width:100%;height:100%;transform:none'})));
    return h('div', {style: 'position:relative'}, tools, answerCard({body: {result: {headline: b.headline, chart: b.chart}, summary: b.summary, actions: b.actions, data: b.data,
      validation: {certified: b.certified, certified_metrics: b.certified_metrics, where: b.where, queries: []}}, id: null}, null), h('div', {class: 'faint small'}, b.question));
  }
  const draw = () => body.replaceChildren(...(blocks.length ? blocks.map(block) : [h('div', {class: 'card empty'}, 'An empty page: add text, or save Ask D answers here.')]));
  draw();
  page.append(h('div', {class: 'crumbs'}, h('a', {href: '#/pages'}, 'Pages'), '›', p.title),
    h('div', {class: 'phead'}, h('div', {style: 'flex:1;min-width:0'}, titleIn, h('div', {class: 'meta'}, `${p.owner} · ${{private: 'Private', team: 'Shared with the team', org: 'Everyone in the organisation'}[p.visibility]} · updated ${ago(p.updated)}`)),
      h('button', {class: 'btn', onclick: exp('pdf')}, icon('download'), 'PDF'), h('button', {class: 'btn', onclick: exp('png')}, icon('download'), 'PNG'),
      h('button', {class: 'btn', onclick: () => channelDialog('page', id, p.title)}, icon('share'), 'Post'),
      p.access === 'owner' ? h('button', {class: 'btn', onclick: () => pageShareDialog(p)}, icon('share'), 'Share') : null,
      p.access === 'owner' ? h('button', {class: 'btn ghost danger', onclick: async () => { if (await confirmBox('Delete this page?', `${p.title} is deleted for everyone it is shared with. Exports already made are not affected.`, 'Delete')) { await api(`/api/pages/${id}`, {method: 'DELETE'}); location.hash = '#/pages'; } }}, 'Delete') : null),
    body, can ? h('div', {class: 'row', style: 'margin-top:10px'}, h('button', {class: 'btn', onclick: () => { blocks.push({type: 'text', text: 'Write here…'}); save(); }}, icon('plus'), 'Text')) : null);
}

async function pageShareDialog(p) {
  const teams = (await api('/api/askd/options')).teams;
  const vis = h('select', {class: 'sel'}, [['private', 'Private: only me'], ['team', 'My team can view'], ['org', 'Everyone in the organisation can view']].map(([v, l]) => h('option', {value: v, selected: p.visibility === v}, l)));
  const team = h('select', {class: 'sel'}, teams.map(t => h('option', {value: t.id, selected: t.id === p.team_id}, t.name)));
  const m = modal(`Share “${p.title}”`, h('div', {class: 'mbody'}, h('label', {class: 'f', style: 'margin-top:0'}, 'Who can see it'), vis, h('label', {class: 'f'}, 'Team'), team,
    h('div', {class: 'hint'}, 'Pages stay inside Relay: people sign in to see them.'),
    h('div', {class: 'row', style: 'justify-content:flex-end;margin-top:12px'}, h('button', {class: 'btn', onclick: () => m.remove()}, 'Cancel'),
      h('button', {class: 'btn primary', onclick: async () => { try { await api(`/api/pages/${p.id}/shares`, {method: 'PUT', json: {visibility: vis.value, team_id: team.value, shares: []}}); notify('Sharing saved', 'ok'); m.remove(); renderPage(p.id); } catch (e) { notify(e.message, 'err'); } }}, 'Save'))));
}

async function saveAsPage(source) {
  try { const p = await api('/api/pages', {json: {source}}); notify('Saved as a page', 'ok'); location.hash = `#/pages/${p.id}`; } catch (e) { notify(e.message, 'err'); }
}
