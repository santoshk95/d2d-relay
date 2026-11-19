/* status.pasdacs.com: D2D Relay's status page and its alerts (item 91, the user, 2026-11-19: "build a status.pasdacs.com
   (if possible to be outside from this docker may be in cloudflare directly) ... to view all the status of the d2d
   application and services and alerts as well to info@pasdacs.com in case of any issues").

   A Cloudflare Worker, outside the D2D PC, so it still answers and still emails when the PC, Docker or the tunnel is
   down. Every three minutes (cron) it checks, from Cloudflare's edge: the public site (/healthz: the app and its
   database), its sign-in page, the admin portal, and the site's /status.json for each service behind it (AI engine,
   build runner, DAX checker, Power BI file maker, sign-in mail). It keeps the state, 90 days of daily uptime and the
   last incidents in KV, in one write a run. Something down for two checks in a row is an incident: info@pasdacs.com is
   emailed through Microsoft Graph (the mail app D2D uses, app-only; secrets MS_TENANT, MS_CLIENT_ID, MS_CLIENT_SECRET),
   again every REMIND_HOURS while it lasts, and once more when it is back. GET / is the page, GET /api/status the JSON.
   Plain keyboard characters only in what people read. */

const SERVICES = [
  ['site', 'D2D Relay website', 'd2d.pasdacs.com: the app and its database'],
  ['signin', 'Sign-in', 'The sign-in page and the emailed sign-in codes'],
  ['admin', 'Admin portal', 'admin.pasdacs.com, for PASDACS'],
  ['ai_engine', 'AI engine', 'Relay Model: plans, builds and Ask Relay'],
  ['job_runner', 'Build runner', 'Each dashboard build in its own container'],
  ['dax_checker', 'DAX checker', 'Checks every measure before a file is made'],
  ['pbix_maker', 'Power BI file maker', 'Makes the .pbix files'],
];
const NAME = Object.fromEntries(SERVICES.map(([k, n]) => [k, n]));
const DAYS = 90, KEEP_INCIDENTS = 40, KEEP_MS = 120;
const TZ = 'Asia/Kolkata';

/* ---------------- checks ---------------- */
async function probe(url, wantBody) {
  const t0 = Date.now();
  try {
    const r = await fetch(url, {redirect: 'manual', headers: {'user-agent': 'pasdacs-status/1.0 (+https://status.pasdacs.com)'},
      signal: AbortSignal.timeout(10000)});
    return {status: r.status, ms: Date.now() - t0, location: r.headers.get('location') || '', body: wantBody ? await r.text() : ''};
  } catch (e) {
    return {status: 0, ms: Date.now() - t0, error: String(e && e.name || e).slice(0, 80)};
  }
}
const parse = t => { try { return JSON.parse(t); } catch (e) { return null; } };

async function checkAll(env) {
  const site = env.SITE || 'd2d.pasdacs.com', admin = env.ADMIN || '';
  const [health, login, adm, st] = await Promise.all([probe(`https://${site}/healthz`, true), probe(`https://${site}/login.html`),
    admin ? probe(`https://${admin}/healthz`) : Promise.resolve(null), probe(`https://${site}/status.json`, true)]);
  const h = parse(health.body), s = parse(st.body), svc = (s && s.services) || {};
  const siteUp = health.status === 200 && !!h && h.ok === true;
  const why = r => r.status ? `HTTP ${r.status}` : (r.error || 'no answer');
  const out = {site: siteUp ? ['up', ''] : ['down', h ? 'the database does not answer' : why(health)]};
  out.signin = !siteUp ? ['unknown', 'the site is down'] : login.status !== 200 ? ['down', `sign-in page ${why(login)}`]
    : svc.sign_in_mail === false ? ['down', 'sign-in mail is not set up'] : ['up', ''];
  if (adm) {                     // 200, or Cloudflare Access's sign-in in front of it (the portal is PASDACS only)
    const access = adm.status >= 300 && adm.status < 400 && /cloudflareaccess\.com/.test(adm.location);
    out.admin = adm.status === 200 || access ? ['up', ''] : adm.status === 0 ? ['unknown', 'not reachable from Cloudflare yet'] : ['down', why(adm)];
  }
  for (const k of ['ai_engine', 'job_runner', 'dax_checker', 'pbix_maker']) {
    out[k] = !siteUp || !s ? ['unknown', 'the site is down'] : svc[k] === true ? ['up', ''] : svc[k] === false ? ['down', 'does not answer'] : ['off', 'not used'];
  }
  return {results: out, ms: siteUp ? health.ms : null, alerts: s && s.alerts, version: s && s.version};
}

/* ---------------- state: one KV value ---------------- */
async function load(env) {
  const st = parse(await env.STATUS.get('state')) || {};
  return {components: {}, days: {}, incidents: [], ms: [], ...st};
}
const day = t => new Date(t + 5.5 * 3600e3).toISOString().slice(0, 10);       // IST days

async function tick(env) {
  const now = Date.now(), st = await load(env), {results, ms, alerts, version} = await checkAll(env);
  const changes = [];
  for (const [k, [raw, detail]] of Object.entries(results)) {
    const c = st.components[k] || {status: 'unknown', since: now, fails: 0};
    c.raw = raw; c.detail = detail; c.checked = now;
    c.fails = raw === 'down' ? (c.fails || 0) + 1 : 0;
    // down needs two checks in a row; up or not used is taken at once; unknown (the site itself is down) keeps a down
    let next = c.status;
    if (raw === 'down') { if (c.fails >= 2) next = 'down'; }
    else if (raw === 'up' || raw === 'off') next = raw;
    else next = c.status === 'down' ? 'down' : 'unknown';
    if (next !== c.status) {
      if (next === 'down') {
        st.incidents.unshift({k, start: c.checked - 3 * 60e3, end: null, detail});
        changes.push({k, to: 'down', detail});
      } else if (c.status === 'down') {
        const inc = st.incidents.find(i => i.k === k && !i.end);
        if (inc) inc.end = now;
        changes.push({k, to: 'up', detail: inc ? `down for ${mins(now - inc.start)}` : ''});
      }
      c.status = next; c.since = now;
    }
    if (raw === 'up' || raw === 'down') {
      const d = (st.days[day(now)] = st.days[day(now)] || {});
      const v = (d[k] = d[k] || [0, 0]);
      v[1] += 1; if (raw === 'up') v[0] += 1;
    }
    st.components[k] = c;
  }
  st.days = Object.fromEntries(Object.entries(st.days).sort().slice(-DAYS));
  st.incidents = st.incidents.slice(0, KEEP_INCIDENTS);
  if (ms != null) st.ms = [...st.ms, ms].slice(-KEEP_MS);
  st.updated = now; st.alerts = alerts || null; st.version = version || st.version || '';
  const down = Object.entries(st.components).filter(([, c]) => c.status === 'down').map(([k]) => k);
  const remind = down.length && now - (st.reminded || 0) > Number(env.REMIND_HOURS || 6) * 3600e3 && !changes.length;
  if (changes.length || remind) {
    try {
      await mail(env, subject(changes, down), text(st, changes, down, remind));
      st.mailed = now; st.mail_error = null;
      if (down.length) st.reminded = now;
    } catch (e) { st.mail_error = String(e && e.message || e).slice(0, 160); }
  }
  await env.STATUS.put('state', JSON.stringify(st));
  return st;
}
const mins = ms => { const m = Math.max(1, Math.round(ms / 60e3)); return m < 90 ? `${m} min` : `${Math.round(m / 60 * 10) / 10} h`; };

/* ---------------- email: Microsoft Graph, as the alert sender (app-only) ---------------- */
async function mail(env, subjectLine, body) {
  if (!env.MS_TENANT || !env.MS_CLIENT_ID || !env.MS_CLIENT_SECRET) throw new Error('mail is not set up (MS_* secrets)');
  const tr = await fetch(`https://login.microsoftonline.com/${env.MS_TENANT}/oauth2/v2.0/token`, {method: 'POST',
    headers: {'content-type': 'application/x-www-form-urlencoded'},
    body: new URLSearchParams({client_id: env.MS_CLIENT_ID, client_secret: env.MS_CLIENT_SECRET, scope: 'https://graph.microsoft.com/.default',
      grant_type: 'client_credentials'})});
  const tok = await tr.json().catch(() => ({}));
  if (!tok.access_token) throw new Error(`token: ${tok.error || tr.status}`);
  const from = env.ALERT_FROM || 'info@pasdacs.com';
  const r = await fetch(`https://graph.microsoft.com/v1.0/users/${encodeURIComponent(from)}/sendMail`, {method: 'POST',
    headers: {authorization: `Bearer ${tok.access_token}`, 'content-type': 'application/json'},
    body: JSON.stringify({saveToSentItems: false, message: {subject: subjectLine, body: {contentType: 'Text', content: body},
      toRecipients: (env.ALERT_TO || 'info@pasdacs.com').split(',').map(a => ({emailAddress: {address: a.trim()}}))}})});
  if (r.status !== 202) throw new Error(`sendMail: HTTP ${r.status}`);
}
const when = t => new Intl.DateTimeFormat('en-IN', {timeZone: TZ, day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false}).format(new Date(t)) + ' IST';
function subject(changes, down) {
  const d = changes.filter(c => c.to === 'down'), u = changes.filter(c => c.to === 'up');
  if (d.length) return `D2D Relay status: ${d.map(c => NAME[c.k]).join(', ')} down`;
  if (u.length && !down.length) return `D2D Relay status: all working again (${u.map(c => NAME[c.k]).join(', ')} back)`;
  if (u.length) return `D2D Relay status: ${u.map(c => NAME[c.k]).join(', ')} back; still down: ${down.map(k => NAME[k]).join(', ')}`;
  return `D2D Relay status: still down: ${down.map(k => NAME[k]).join(', ')}`;
}
function text(st, changes, down, remind) {
  const lines = ['D2D Relay status, checked from Cloudflare every 3 minutes.', ''];
  for (const c of changes) lines.push(`${c.to === 'down' ? 'DOWN' : 'BACK'}: ${NAME[c.k]}${c.detail ? ' - ' + c.detail : ''}`);
  if (remind) lines.push('Still down: ' + down.map(k => `${NAME[k]} (since ${when(st.components[k].since)})`).join(', '));
  lines.push('', 'Now:');
  for (const [k, n] of SERVICES) {
    const c = st.components[k];
    if (c) lines.push(`- ${n}: ${label(c.status)}${c.status === 'down' && c.detail ? ' (' + c.detail + ')' : ''}`);
  }
  lines.push('', 'Status page: https://status.pasdacs.com', 'Checked: ' + when(st.updated || Date.now()),
    '', 'What to look at first: is the PC on and Docker Desktop running? Then the D2D containers (docker ps), the tunnel',
    '(d2d-relay-tunnel), and the D2D Relay helpers. docs/d2d-relay.md, "After the PC restarts", has the steps.');
  return lines.join('\n');
}

/* ---------------- the page ---------------- */
const label = s => ({up: 'Working', down: 'Down', unknown: 'Unknown', off: 'Not used'}[s] || 'Unknown');
const esc = s => String(s == null ? '' : s).replace(/[&<>"]/g, ch => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[ch]));
function page(st) {
  const comps = SERVICES.filter(([k]) => st.components[k]);
  const down = comps.filter(([k]) => st.components[k].status === 'down');
  const core = down.some(([k]) => k === 'site');
  const overall = !st.updated ? ['unknown', 'Waiting for the first check'] : core ? ['down', 'D2D Relay is down']
    : down.length ? ['part', `${down.length === 1 ? 'One service is' : down.length + ' services are'} down`] : ['up', 'All services are working'];
  const days = Array.from({length: DAYS}, (_, i) => day(Date.now() - (DAYS - 1 - i) * 86400e3));
  const bars = k => days.map(d => {
    const v = (st.days[d] || {})[k];
    const pct = v && v[1] ? v[0] / v[1] : null;
    const cls = pct == null ? 'none' : pct >= 0.999 ? 'ok' : pct >= 0.95 ? 'warn' : 'bad';
    return `<i class="${cls}" title="${esc(d)}: ${pct == null ? 'no data' : (Math.floor(pct * 1000) / 10) + '% working'}"></i>`;
  }).join('');
  const upPct = k => { let a = 0, b = 0; for (const d of days) { const v = (st.days[d] || {})[k]; if (v) { a += v[0]; b += v[1]; } }
    return b ? `${Math.floor(a / b * 1000) / 10}%` : '-'; };
  const rows = comps.map(([k, n, d]) => { const c = st.components[k];
    return `<li class="svc"><div class="top"><div><b>${esc(n)}</b><span class="desc">${esc(d)}</span></div>
      <span class="pill ${c.status}">${label(c.status)}</span></div>
      ${c.status === 'down' && c.detail ? `<div class="detail">${esc(c.detail)}, since ${esc(when(c.since))}</div>` : ''}
      <div class="bars" aria-label="${esc(n)}: 90 days">${bars(k)}</div>
      <div class="foot"><span>90 days ago</span><span>${upPct(k)} working</span><span>Today</span></div></li>`; }).join('');
  const incs = (st.incidents || []).slice(0, 12).map(i => `<li><b>${esc(NAME[i.k] || i.k)}</b> down ${esc(when(i.start))}${i.end
    ? ` to ${esc(when(i.end))} (${esc(mins(i.end - i.start))})` : ', <span class="open">still down</span>'}${i.detail ? `<span class="desc">${esc(i.detail)}</span>` : ''}</li>`).join('');
  const ms = (st.ms || []).slice(-60), top = Math.max(...ms, 1);
  const spark = ms.length ? `<div class="spark" aria-label="Response time, last 3 hours">${ms.map(v => `<i style="height:${Math.max(4, Math.round(v / top * 100))}%" title="${v} ms"></i>`).join('')}</div>
    <div class="foot"><span>Website response time, last ${Math.round(ms.length * 3 / 60 * 10) / 10} hours</span><span>now ${ms[ms.length - 1]} ms</span></div>` : '';
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>PASDACS status</title><meta name="description" content="Live status of D2D Relay and its services.">
<meta http-equiv="refresh" content="60"><meta name="color-scheme" content="light dark">
<link rel="icon" href="data:image/svg+xml,${encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48"><rect width="48" height="48" rx="11" fill="#111"/><circle cx="24" cy="24" r="9" fill="#00C48C"/></svg>')}">
<style>
:root{--bg:#F7F7F7;--card:#FFFFFF;--ink:#111111;--ink2:#525252;--line:#E5E5E5;--ok:#00A676;--warn:#E8A317;--bad:#DC2626;--none:#D4D4D4;--accent:#007A57}
@media (prefers-color-scheme:dark){:root{--bg:#0A0A0A;--card:#161616;--ink:#F5F5F5;--ink2:#A3A3A3;--line:#262626;--ok:#00C48C;--warn:#F2B134;--bad:#F87171;--none:#333333;--accent:#00C48C}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 Inter,"Segoe UI",system-ui,-apple-system,Arial,sans-serif}
.wrap{max-width:860px;margin:0 auto;padding:28px 16px 48px}
header{display:flex;align-items:center;gap:12px;margin-bottom:22px}
header .mark{width:40px;height:40px;border-radius:11px;background:#111;display:grid;place-items:center}
header .mark i{width:16px;height:16px;border-radius:50%;background:#00C48C}
header h1{font-size:20px;margin:0;line-height:1.2}header small{display:block;color:var(--ink2);font-size:12.5px}
.banner{display:flex;align-items:center;gap:12px;padding:16px 18px;border-radius:14px;color:#fff;font-weight:700;font-size:16px;margin-bottom:22px}
.banner.up{background:var(--ok)}.banner.part{background:var(--warn);color:#111}.banner.down{background:var(--bad)}.banner.unknown{background:#525252}
.banner small{display:block;font-weight:400;font-size:12.5px;opacity:.9}
h2{font-size:15px;margin:26px 0 10px}
ul{list-style:none;margin:0;padding:0}
.svc{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px;margin-bottom:10px}
.top{display:flex;justify-content:space-between;gap:12px;align-items:flex-start}
.desc{display:block;color:var(--ink2);font-size:12.5px;font-weight:400}
.pill{font-size:12px;font-weight:700;padding:3px 10px;border-radius:99px;white-space:nowrap;border:1px solid var(--line)}
.pill.up{color:var(--ok)}.pill.down{color:#fff;background:var(--bad);border-color:var(--bad)}.pill.unknown,.pill.off{color:var(--ink2)}
.detail{margin-top:6px;color:var(--bad);font-size:12.5px}
.bars{display:flex;gap:2px;margin-top:12px;height:28px}
.bars i{flex:1;border-radius:2px;background:var(--none)}.bars i.ok{background:var(--ok)}.bars i.warn{background:var(--warn)}.bars i.bad{background:var(--bad)}
.foot{display:flex;justify-content:space-between;color:var(--ink2);font-size:11.5px;margin-top:4px}
.spark{display:flex;align-items:flex-end;gap:2px;height:48px;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:8px}
.spark i{flex:1;background:var(--accent);border-radius:2px 2px 0 0;opacity:.8}
.inc li{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:10px 14px;margin-bottom:8px}
.open{color:var(--bad);font-weight:700}
.meta{color:var(--ink2);font-size:12px;margin-top:26px}
@media (max-width:520px){.bars{gap:1px}.wrap{padding:20px 16px 40px}}
</style></head><body><div class="wrap">
<header><div class="mark" aria-hidden="true"><i></i></div><div><h1>PASDACS status</h1><small>D2D Relay and the services behind it</small></div></header>
<div class="banner ${overall[0]}" role="status">${esc(overall[1])}<small>${st.updated ? 'Checked ' + esc(when(st.updated)) + ', every 3 minutes, from Cloudflare' : 'The first check runs within 3 minutes'}</small></div>
${rows ? `<ul>${rows}</ul>` : ''}
${spark ? `<h2>Response time</h2>${spark}` : ''}
<h2>Incidents</h2>${incs ? `<ul class="inc">${incs}</ul>` : '<p class="desc">None in the last 90 days.</p>'}
<p class="meta">Problems are emailed to PASDACS as they happen. Questions: <a href="mailto:info@pasdacs.com">info@pasdacs.com</a>.${st.version ? ' Version ' + esc(st.version) + '.' : ''}</p>
</div></body></html>`;
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === '/api/status') {
      const st = await load(env);
      const pub = Object.fromEntries(Object.entries(st.components).map(([k, c]) => [k, {status: c.status, since: c.since, checked: c.checked}]));
      return Response.json({updated: st.updated || null, components: pub, incidents: (st.incidents || []).slice(0, 12), version: st.version || ''},
        {headers: {'cache-control': 'no-store', 'access-control-allow-origin': '*'}});
    }
    if (url.pathname === '/api/check-now' && request.method === 'POST') {        // a check now, as the cron runs it
      if (!env.TEST_KEY || request.headers.get('x-test-key') !== env.TEST_KEY) return new Response('Not found', {status: 404});
      const st = await tick(env);
      return Response.json({updated: st.updated, components: Object.fromEntries(Object.entries(st.components).map(([k, c]) => [k, c.status])),
        mail_error: st.mail_error || null});
    }
    if (url.pathname === '/api/test-alert' && request.method === 'POST') {       // one email, to check the alert route works
      if (!env.TEST_KEY || request.headers.get('x-test-key') !== env.TEST_KEY) return new Response('Not found', {status: 404});
      const st = await load(env);
      try {
        await mail(env, 'D2D Relay status: alerts are set up', ['This is a test from status.pasdacs.com.', '',
          'From now on, when D2D Relay or one of its services is down for two checks in a row (about 6 minutes), an email',
          'comes here, a reminder every few hours while it lasts, and another when it is back.', '', 'Status page: https://status.pasdacs.com',
          st.updated ? 'Last check: ' + when(st.updated) : 'No check has run yet.'].join('\n'));
        return Response.json({sent: true});
      } catch (e) { return Response.json({sent: false, error: String(e && e.message || e)}, {status: 502}); }
    }
    if (url.pathname !== '/' && url.pathname !== '/index.html') return new Response('Not found', {status: 404});
    return new Response(page(await load(env)), {headers: {'content-type': 'text/html; charset=utf-8', 'cache-control': 'no-store',
      'x-content-type-options': 'nosniff', 'referrer-policy': 'no-referrer', 'content-security-policy': "default-src 'none'; style-src 'unsafe-inline'; img-src data:"}});
  },
  async scheduled(controller, env, ctx) {
    ctx.waitUntil(tick(env));
  },
};
