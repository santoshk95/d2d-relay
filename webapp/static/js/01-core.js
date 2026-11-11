/* ---------------- constants and state ---------------- */
const RUN = new Set(['queued', 'extracting', 'generating_data', 'planning', 'building', 'revising', 'building_pbi']);
const STATUS = {queued: ['Queued', 'run'], extracting: ['Pulling warehouse data', 'run'], generating_data: ['Generating data', 'run'], planning: ['Planning', 'run'], awaiting_kpis: ['Confirm KPIs', 'you'],
  building: ['Building prototype', 'run'], awaiting_review: ['Ready for review', 'you'], revising: ['Applying changes', 'run'],
  building_pbi: ['Publishing', 'run'], done: ['Published', 'ok'], error: ['Needs attention', 'err']};
const STAGES = {extract: 'Warehouse data', data: 'Demo data', plan: 'Plan', build: 'Build', revise: 'Change request', pbi: 'Power BI', check: 'Review gates'};
const STEPS = ['Plan', 'Confirm KPIs', 'Prototype', 'Review', 'Power BI'];
const TABS = [['overview', 'Overview'], ['plan', 'Plan'], ['versions', 'Versions'], ['activity', 'Activity'], ['details', 'Details']];
const FILES = {'request.md': 'Request and decisions', 'plan.yaml': 'Plan', 'definition.yaml': 'Report definition',
  'profile.md': 'Data profile', 'CLAUDE.md': "Relay's guide", 'datagen.yaml': 'Demo data recipe'};
const S = {projects: [], pid: null, tab: 'overview', project: null, events: [], after: 0, key: null, version: null, vsel: null,
  live: null, changes: {}, actMode: 'summary', actQuery: '', act: null, health: null};

/* ---------------- helpers ---------------- */
const $ = (s, el = document) => el.querySelector(s);
// D2D Relay: the admin portal (admin-d2d.pasdacs.com) runs the same screens with its own menu (portal.js, set by the server)
const isAdminPortal = () => !!(window.D2D_PORTAL && window.D2D_PORTAL.portal === 'admin');
function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k === 'style') el.style.cssText = v;
    else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else if (k === 'value') el.value = v;
    else el.setAttribute(k, v === true ? '' : v);
  }
  for (const kid of kids.flat(Infinity)) if (kid != null && kid !== false) el.append(kid.nodeType ? kid : String(kid));
  return el;
}
const ICONS = {
  grid: 'M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z', plus: 'M12 5v14M5 12h14', layers: 'M12 3l9 5-9 5-9-5 9-5zM3 13l9 5 9-5',
  external: 'M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5', check: 'M5 12l5 5L20 7',
  user: 'M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4 21a8 8 0 0 1 16 0', spark: 'M20 12a8 8 0 0 1-11.7 7.1L4 20l1-4.2A8 8 0 1 1 20 12zM8.5 10.5h7M8.5 13.5h4.5', thumbup: 'M7 11v9H4v-9zM7 11l4-7a2 2 0 0 1 3 2l-1 4h5.5a2 2 0 0 1 2 2.3l-1.2 6A2 2 0 0 1 17.3 20H7', thumbdown: 'M7 13V4H4v9zM7 13l4 7a2 2 0 0 0 3-2l-1-4h5.5a2 2 0 0 0 2-2.3l-1.2-6A2 2 0 0 0 17.3 4H7', clip: 'M20.5 11.5l-8.2 8.2a5 5 0 0 1-7.1-7.1l8.2-8.2a3.4 3.4 0 0 1 4.8 4.8l-8.2 8.2a1.7 1.7 0 0 1-2.4-2.4l7.5-7.5', image: 'M4 5h16v14H4zM4 15l4.5-4.5 4 4L16 11l4 4M9 9.5h.01', table: 'M4 5h16v14H4zM4 10h16M4 14.5h16M10 5v14',
  info: 'M12 8h.01M11 12h1v5h1M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z', alert: 'M12 9v4M12 17h.01M10.3 3.9L2.4 18a2 2 0 0 0 1.7 3h15.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z',
  x: 'M6 6l12 12M18 6L6 18', download: 'M12 4v11M7 10l5 5 5-5M5 20h14', gear: 'M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.6 1.6 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.6 1.6 0 0 0-1.8-.3 1.6 1.6 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.6 1.6 0 0 0-1-1.5 1.6 1.6 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.6 1.6 0 0 0 .3-1.8 1.6 1.6 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.6 1.6 0 0 0 1.5-1 1.6 1.6 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.6 1.6 0 0 0 1.8.3H9a1.6 1.6 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.6 1.6 0 0 0 1 1.5 1.6 1.6 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.6 1.6 0 0 0-.3 1.8V9a1.6 1.6 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.6 1.6 0 0 0-1.5 1z',
  play: 'M7 4v16l13-8z', clock: 'M12 7v5l3 2M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z', columns: 'M4 4h7v16H4zM13 4h7v16h-7z',
  file: 'M14 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8zM14 3v5h5', copy: 'M9 9h10v11H9zM5 15V4h10',
  edit: 'M4 20h4L19 9l-4-4L4 16zM14 6l4 4', back: 'M15 18l-6-6 6-6', publish: 'M12 16V4M7 9l5-5 5 5M5 20h14',
  share: 'M8.6 13.5l6.8 4M15.4 6.5l-6.8 4M18 8a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM6 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM18 22a3 3 0 1 0 0-6 3 3 0 0 0 0 6z',
  shield: 'M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z', lock: 'M6 11h12v10H6zM8 11V7a4 4 0 0 1 8 0v4', globe: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM3 12h18M12 3c2.5 3 2.5 15 0 18M12 3c-2.5 3-2.5 15 0 18',
  bell: 'M6 16V11a6 6 0 0 1 12 0v5l2 2H4zM10 20a2 2 0 0 0 4 0',
  search: 'M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14zM21 21l-5-5', pin: 'M12 17v5M8.5 3h7l-1 6.5 3.5 4H6l3.5-4z', chevl: 'M15 6l-6 6 6 6', chevr: 'M9 6l6 6-6 6', chevd: 'M6 9l6 6 6-6', menu: 'M4 6h16M4 12h16M4 18h16',
  users: 'M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM2 21a7 7 0 0 1 14 0M16 3.5a4 4 0 0 1 0 7M22 21a7 7 0 0 0-4.5-6.5',
  // P9: the module registry's icons (shared with the mockup)
  chart: 'M4 20V10M10 20V4M16 20v-7M22 20H2', plug: 'M9 2v6M15 2v6M6 8h12v4a6 6 0 0 1-12 0zM12 18v4',
  book: 'M4 5a2 2 0 0 1 2-2h13v16H6a2 2 0 0 0-2 2zM4 19V5M8 7h7', dice: 'M5 4h14a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1zM8.5 8.5h.01M15.5 15.5h.01M12 12h.01',
  send: 'M22 2L11 13M22 2l-7 20-4-9-9-4z', swap: 'M7 4L3 8l4 4M3 8h14M17 20l4-4-4-4M21 16H7', code: 'M8 7l-5 5 5 5M16 7l5 5-5 5',
  db: 'M12 3c4.4 0 8 1.3 8 3s-3.6 3-8 3-8-1.3-8-3 3.6-3 8-3zM4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3',
  scale: 'M12 3v18M5 21h14M6 7h12M6 7l-3 7a3 3 0 0 0 6 0zM18 7l-3 7a3 3 0 0 0 6 0z', heart: 'M12 20s-7-4.5-9-9a4.5 4.5 0 0 1 9-3 4.5 4.5 0 0 1 9 3c-2 4.5-9 9-9 9z',
  gauge: 'M12 14l4-4M3.5 18a9 9 0 1 1 17 0', cpu: 'M6 6h12v12H6zM9 9h6v6H9zM9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4', pulse: 'M3 12h4l3-8 4 16 3-8h4',
  route: 'M6 19a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM18 9a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM6 15V9a4 4 0 0 1 4-4h6M18 9v6a4 4 0 0 1-4 4H8',
  folder: 'M3 6a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z', sun: 'M12 17a5 5 0 1 0 0-10 5 5 0 0 0 0 10zM12 1v2M12 21v2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M1 12h2M21 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4',
  moon: 'M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z', graph: 'M5 6a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM19 9a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM8 22a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM19 21a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM6.5 5.5l10.7 1.8M5.5 6l2 12M9.8 20h7.4M18.8 9l.2 8',
  brush: 'M9.1 14.9c-1.7 0-3.1 1.4-3.1 3.1 0 1.2-1 2-2 2 1 1.3 2.6 2 4 2 2.8 0 5-2.2 5-5 0-1.7-1.4-3.1-3.1-3.1zM20.7 3.3a1.1 1.1 0 0 0-1.6 0L10 12.4l1.6 1.6 9.1-9.1a1.1 1.1 0 0 0 0-1.6z',
  target: 'M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20zM12 18a6 6 0 1 0 0-12 6 6 0 0 0 0 12zM12 14a2 2 0 1 0 0-4 2 2 0 0 0 0 4z'};
function icon(name, cls) {
  const s = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  s.setAttribute('viewBox', '0 0 24 24'); s.setAttribute('class', 'i' + (cls ? ' ' + cls : ''));
  const p = document.createElementNS('http://www.w3.org/2000/svg', 'path'); p.setAttribute('d', ICONS[name] || ''); s.append(p);
  return s;
}
const toSignIn = () => { if (!location.pathname.startsWith('/login')) location.href = '/login.html?next=' + encodeURIComponent(location.hash); };
async function api(path, opts = {}) {
  const init = {...opts};
  if (opts.json !== undefined) { init.method = init.method || 'POST'; init.body = JSON.stringify(opts.json); init.headers = {'Content-Type': 'application/json'}; }
  const r = await fetch(path, init);
  if (r.status === 401) { toSignIn(); throw new Error('Signed out'); }
  if (!r.ok) {
    let msg = r.status + ' ' + r.statusText;
    try { const j = await r.json(); msg = Array.isArray(j.detail) ? j.detail.map(d => d.msg).join('; ') : (j.detail || msg); } catch (e) {}
    if (r.status === 402 && typeof onNoCredits === 'function') onNoCredits(msg);     // D2D Relay: not enough credits (36-org.js)
    throw new Error(msg);
  }
  return (r.headers.get('content-type') || '').includes('json') ? r.json() : r.text();
}
const size = n => n < 1024 ? n + ' B' : n < 1048576 ? (n / 1024).toFixed(1) + ' KB' : n < 1073741824 ? (n / 1048576).toFixed(1) + ' MB' : (n / 1073741824).toFixed(2) + ' GB';
const dur = ms => { const s = Math.round(ms / 1000); return s < 60 ? s + 's' : s < 3600 ? Math.floor(s / 60) + 'm ' + String(s % 60).padStart(2, '0') + 's' : Math.floor(s / 3600) + 'h ' + String(Math.floor(s % 3600 / 60)).padStart(2, '0') + 'm'; };
const tok = n => n >= 1e6 ? (n / 1e6).toFixed(2) + 'M' : n >= 1e5 ? Math.round(n / 1e3) + 'K' : n >= 1e3 ? (n / 1e3).toFixed(1) + 'K' : String(n || 0);
const usd = x => '$' + (x || 0).toFixed(2);
const runTokens = u => (u.input || 0) + (u.cache_write || 0) + (u.cache_read || 0) + (u.output || 0);
const spend = g => g && g.runs ? `${g.complete ? '' : '≥ '}${tok(g.tokens)} tokens · ${usd(g.cost_usd)}` : '';
let CATALOG = {default: 'sonnet', models: []};
const catalogEntry = id => CATALOG.models.find(m => m.id === id);
// Only admins see which AI models run behind Relay. Everyone else sees a model only when it is one they can pick
// themselves (Relay's own, or the provider they chose in Settings); otherwise modelName is '' and callers leave it out.
// D2D Relay: "admins" here means the platform admin; an organisation's owner is an admin of their own workspace only.
const modelSeen = id => !!(S.me && (S.me.org ? S.me.org.platform_admin : S.me.admin)) || !!catalogEntry(id);
/* the person's role in words (D2D Relay: an organisation's owner, the platform admin) */
const roleText = (me, dev = 'Builder / Analyst') => me.org && me.org.platform_admin ? 'Platform admin' : me.org && me.org.is_owner ? 'Owner'
  : me.admin ? 'Admin' : me.builder ? dev : 'Viewer';
const modelName = id => {
  if (id && !modelSeen(id)) return '';
  const m = /^claude-([a-z]+)-(\d+)(?:-(\d{1,2}))?(?:-\d{8})?$/.exec(id || '');
  return m ? `${m[1][0].toUpperCase()}${m[1].slice(1)} ${m[2]}${m[3] ? '.' + m[3] : ''}` : (catalogEntry(id) || {}).label || id || 'unknown';
};
const costHint = m => m.relative_cost == null ? '' : m.relative_cost === 1 ? 'Same price per token as Sonnet (latest).' : `About ${m.relative_cost}× Sonnet's price per token.`;
function modelOptions(selected) {
  const own = [...new Set(CATALOG.models.filter(m => m.group).map(m => m.group))];
  const rest = CATALOG.models.filter(m => !m.group);
  const fams = [...new Set(rest.filter(m => !m.latest).map(m => m.family))];
  const groups = [...own.map(g => [g, CATALOG.models.filter(m => m.group === g)]),
    ['Always the newest version', rest.filter(m => m.latest)],
    ...fams.map(f => [`${f[0].toUpperCase()}${f.slice(1)} versions`, rest.filter(m => !m.latest && m.family === f)])];
  const known = catalogEntry(selected);
  return [known || !selected ? null : h('option', {value: selected, selected: true}, modelName(selected) ? `${modelName(selected)} (not in the list any more)` : 'Set by an admin'),
    ...groups.filter(g => g[1].length).map(([label, ms]) => h('optgroup', {label}, ms.map(m => h('option', {value: m.id, selected: m.id === selected},
      m.label + (m.latest && m.version ? ` · now ${m.version}` : '') + (m.relative_cost != null ? ` · ${m.relative_cost}× price` : '')))))];
}
async function loadModels() { try { CATALOG = await api('/api/models'); } catch (e) { console.error(e); } }
const modelsText = list => (list || []).map(modelName).filter(Boolean).join(' + ');
const spendModel = g => [spend(g), g && g.runs ? modelsText(g.models) : ''].filter(Boolean).join(' · ');
function ago(t) { if (!t) return ''; const s = Date.now() / 1000 - t; return s < 60 ? 'just now' : s < 3600 ? Math.floor(s / 60) + ' min ago' : s < 86400 ? Math.floor(s / 3600) + ' h ago' : when(t); }
const when = t => t ? new Date(t * 1000).toLocaleString(undefined, {day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit'}) : '';
const clock = t => t ? new Date(t * 1000).toLocaleTimeString(undefined, {hour: '2-digit', minute: '2-digit', second: '2-digit'}) : '';
const pill = s => { const [t, c] = STATUS[s] || [s, '']; return h('span', {class: 'pill ' + c}, t); };
function rich(text) {
  const out = h('div', {class: 'say'});
  for (const part of String(text || '').split(/(\*\*[^*]+\*\*|`[^`]+`)/g)) {
    if (/^\*\*[^*]+\*\*$/.test(part)) out.append(h('b', {}, part.slice(2, -2)));
    else if (/^`[^`]+`$/.test(part)) out.append(h('code', {class: 'mono'}, part.slice(1, -1)));
    else if (part) out.append(part.replace(/^#{1,4} /gm, ''));
  }
  return out;
}
function toast(el, msg) { let m = $('.err-msg', el.parentElement) || el.parentElement.appendChild(h('div', {class: 'err-msg'})); m.textContent = msg; }
function notify(msg, kind) { const t = h('div', {class: 'toast ' + (kind || '')}, msg); $('#toasts').append(t); setTimeout(() => t.remove(), 3800); }
const copyBtn = text => h('button', {class: 'btn sm', title: 'Copy', onclick: e => { navigator.clipboard.writeText(text); notify('Copied', 'ok'); }}, icon('copy'), 'Copy');
const isImage = f => /\.(png|jpe?g|webp|gif)$/i.test(f.name);
function attacher() {
  let picked = [];
  const input = h('input', {type: 'file', multiple: true, accept: '.csv,text/csv,image/*', style: 'display:none'});
  const list = h('div', {class: 'flist attached'});
  const show = () => list.replaceChildren(...picked.map((f, i) => h('span', {}, icon(isImage(f) ? 'image' : 'table'), ' ' + f.name + ' · ' + size(f.size),
    h('button', {type: 'button', title: 'Remove', onclick: () => { picked.splice(i, 1); show(); }}, '×'))));
  const add = files => { picked.push(...[...files].filter(f => /\.csv$/i.test(f.name) || isImage(f))); show(); };
  input.onchange = () => { add(input.files); input.value = ''; };
  const button = h('button', {class: 'btn', type: 'button', title: 'Attach CSV files (more or updated data) or images', onclick: () => input.click()}, icon('clip'), 'Attach');
  const dropOn = el => {
    el.addEventListener('dragover', e => { e.preventDefault(); el.classList.add('over'); });
    el.addEventListener('dragleave', () => el.classList.remove('over'));
    el.addEventListener('drop', e => { e.preventDefault(); el.classList.remove('over'); add(e.dataTransfer.files); });
  };
  return {input, list, button, dropOn, files: () => picked};
}
function upload(url, fd, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.upload.onprogress = ev => { if (ev.lengthComputable && onProgress) onProgress(ev.loaded / ev.total); };
    xhr.onload = () => {
      let r = {}; try { r = JSON.parse(xhr.responseText); } catch (e) {}
      if (xhr.status === 401) { toSignIn(); return reject(new Error('Signed out')); }
      if (xhr.status === 200) resolve(r);
      else {
        const msg = Array.isArray(r.detail) ? r.detail.map(d => d.msg).join('; ') : r.detail || `Request failed (${xhr.status})`;
        if (xhr.status === 402 && typeof onNoCredits === 'function') onNoCredits(msg);   // D2D Relay: not enough credits (36-org.js)
        reject(new Error(msg));
      }
    };
    xhr.onerror = () => reject(new Error('Upload failed — is the app running?'));
    xhr.open('POST', url); xhr.send(fd);
  });
}
const attachedList = paths => paths && paths.length ? h('div', {class: 'flist'}, paths.map(p => h('span', {}, icon('clip'), ' ' + p))) : null;
function modal(title, body, wide) {
  const back = document.activeElement;                          // focus returns here when the dialog closes
  const close = () => { m.remove(); document.removeEventListener('keydown', keys); if (back && back.focus) back.focus(); };
  const focusable = () => [...m.querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])')].filter(e => !e.disabled && e.offsetParent);
  const keys = e => {
    if (!m.isConnected) { document.removeEventListener('keydown', keys); return; }   // closed by its own code (m.remove())
    if (e.key === 'Escape') close();
    if (e.key === 'Tab') {                                       // keep Tab inside the dialog
      const f = focusable(); if (!f.length) return;
      if (e.shiftKey && document.activeElement === f[0]) { e.preventDefault(); f[f.length - 1].focus(); }
      else if (!e.shiftKey && document.activeElement === f[f.length - 1]) { e.preventDefault(); f[0].focus(); }
    }
  };
  const tid = 'mt' + Math.random().toString(36).slice(2, 8);
  const m = h('div', {class: 'modal' + (wide ? ' xl' : ''), onclick: e => { if (e.target === m) close(); }},
    h('div', {role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': tid}, h('header', {}, h('b', {id: tid}, title), h('button', {class: 'btn sm', onclick: close}, 'Close')), body));
  document.addEventListener('keydown', keys);
  document.body.append(m);
  setTimeout(() => { const f = focusable(); const first = f.find(e => !/Close/.test(e.textContent)) || f[0]; if (first) first.focus(); }, 30);
  return m;
}
/* A question in the app's own dialog, in place of the browser's prompt(): resolves to the text ('' when left empty and
   not required), or null when the person cancels or closes it. rows: 1 for a one-line answer (Enter submits). */
function askText(title, {label = '', value = '', placeholder = '', hint = '', required = false, ok = 'OK', rows = 3} = {}) {
  return new Promise(resolve => {
    let answer = null;
    const field = rows > 1 ? h('textarea', {rows, placeholder, 'aria-label': label || title}, value || '') : h('input', {type: 'text', value: value || '', placeholder, 'aria-label': label || title});
    const err = h('div', {class: 'err-msg', role: 'alert'});
    const shut = () => { const b = mm.querySelector('header button'); if (b) b.click(); else mm.remove(); };      // the dialog's own Close: focus goes back
    const submit = () => { const v = field.value.trim(); if (required && !v) { err.textContent = 'Write a few words first.'; field.focus(); return; } answer = v; shut(); };
    if (rows <= 1) field.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); submit(); } });
    const mm = modal(title, h('div', {class: 'mbody'}, label ? h('label', {class: 'f', style: 'margin-top:0'}, label) : null, field, hint ? h('div', {class: 'hint'}, hint) : null, err,
      h('div', {class: 'row', style: 'justify-content:flex-end;gap:8px;margin-top:12px'}, h('button', {class: 'btn', type: 'button', onclick: shut}, 'Cancel'), h('button', {class: 'btn primary', type: 'button', onclick: submit}, ok))));
    new MutationObserver((_, o) => { if (!mm.isConnected) { o.disconnect(); resolve(answer); } }).observe(document.body, {childList: true});
  });
}
/* What the one agent is doing, in words (Self-healing, AI SDLC): {running, kind, waiting} from the server */
function agentNow(w) {
  w = w || {};
  const more = w.waiting ? ` · ${w.waiting} more waiting` : '';
  return w.running ? 'The agent is busy right now' + more : w.waiting ? `${w.waiting} waiting for the agent` : 'The agent is free';
}


/* Accessibility (UI audit): every visible field gets a name. A `label.f` (or a small label inside a .row column)
   followed by its field is linked with aria-labelledby; a field with only a placeholder is named by it. */
(function nameFields() {
  let n = 0;
  const fix = root => {
    for (const el of root.querySelectorAll('input:not([type=hidden]):not([type=checkbox]):not([type=radio]), select, textarea')) {
      if (el.getAttribute('aria-label') || el.getAttribute('aria-labelledby') || (el.labels && el.labels.length)) continue;
      let lab = el.previousElementSibling;
      while (lab && !(lab.tagName === 'LABEL' || (lab.tagName === 'SMALL' && lab.classList.contains('muted')))) lab = lab.tagName === 'DIV' && lab.classList.contains('hint') ? lab.previousElementSibling : null;
      if (!lab && el.parentElement && /^(LABEL|DIV)$/.test(el.parentElement.tagName)) {
        const first = el.parentElement.firstElementChild;
        if (first && first !== el && /^(LABEL|SMALL|B|SPAN)$/.test(first.tagName) && first.textContent.trim()) lab = first;
      }
      if (lab && lab.textContent.trim()) { lab.id = lab.id || 'lab' + (++n); el.setAttribute('aria-labelledby', lab.id); }
      else if (el.placeholder) el.setAttribute('aria-label', el.placeholder);
    }
  };
  new MutationObserver(muts => { for (const m of muts) for (const node of m.addedNodes) if (node.nodeType === 1) fix(node); })
    .observe(document.body, {childList: true, subtree: true});
})();
