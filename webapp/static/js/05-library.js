/* ---------------- visual library ---------------- */
async function renderLibrary() {
  const main = $('#main');
  main.replaceChildren(skel('page'));
  let lib;
  try { lib = await api('/api/library'); } catch (e) { return main.replaceChildren(h('div', {class: 'page'}, h('div', {class: 'note err'}, 'Could not load the library: ' + e.message))); }
  if (location.hash !== '#/library') return;
  const fields = v => Object.entries(v.roles || {}).map(([r, k]) => {
    const info = (v.role_info || {})[r] || {}, need = (v.required || []).some(g => g.includes(r));
    return (info.displayName || r) + (k === 'Grouping' ? '' : ' (measure)') + (need ? '*' : '');
  }).join(', ');
  const card = v => {
    const rm = h('button', {class: 'btn sm ghost danger', onclick: async () => {
      if (!await confirmBox(`Remove ${v.title}?`, `It leaves the visual library. Reports that already use it keep their copy.`)) return;
      rm.disabled = true;
      try { await api(`/api/library/${v.name}`, {method: 'DELETE'}); notify(`${v.title} removed from the library`); renderLibrary(); } catch (e) { rm.disabled = false; toast(rm, e.message); }
    }}, 'Remove');
    return h('div', {class: 'libc'},
      h('a', {class: 'thumb', href: `/api/library/${v.name}/preview`, target: '_blank', title: 'Browser test screenshot'}, h('img', {src: `/api/library/${v.name}/preview`, alt: v.title, loading: 'lazy'})),
      h('div', {class: 'row', style: 'gap:6px'}, h('b', {}, v.title), h('span', {class: 'faint small mono'}, v.name), h('span', {class: 'spacer'}), h('span', {class: 'tag'}, 'v' + v.version)),
      v.description ? h('div', {class: 'small'}, v.description) : null,
      h('div', {class: 'muted small'}, 'Fields: ' + fields(v)),
      h('div', {class: 'muted small'}, 'Made for ', v.project ? h('a', {href: '#/p/' + v.project}, v.project_name || v.project) : 'an earlier report', ' - updated ', ago(v.updated)),
      h('div', {class: 'row', style: 'margin-top:4px'}, h('a', {class: 'btn sm', href: `/api/library/${v.name}/download`}, icon('download'), '.pbiviz'), rm));
  };
  main.replaceChildren(h('div', {class: 'page'},
    h('h1', {}, 'Visual library'),
    h('div', {class: 'muted', style: 'margin:4px 0 16px;max-width:820px'}, 'Custom Power BI visuals Relay built for earlier dashboards. Every new dashboard can use them - they take its colors and look - and Relay can adapt one for a new request. Each is a normal .pbiviz you can also import into any report by hand.'),
    lib.folder ? h('div', {class: 'path', style: 'max-width:820px;margin-bottom:16px'}, h('code', {}, lib.folder), copyBtn(lib.folder)) : null,
    lib.visuals.length ? h('div', {class: 'lib'}, lib.visuals.map(card))
      : h('div', {class: 'card empty'}, h('h3', {}, 'No custom visuals yet'), 'When a dashboard needs a chart nothing available draws, Relay proposes one in the plan; once built and tested it appears here.')));
}

