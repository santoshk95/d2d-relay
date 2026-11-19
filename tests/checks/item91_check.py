"""Item 91 (2026-11-19): /status.json, what status.pasdacs.com (a Cloudflare Worker, status/worker.js) reads with no
sign-in: each service up or not and how many alerts are open, nothing about anyone's work, data or organisation.

python -I -X utf8 item91_check.py http://127.0.0.1:8103 http://127.0.0.1:8104
"""
import json
import os
import sys
import urllib.request

sys.argv = [sys.argv[0], sys.argv[1], sys.argv[2]]
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import d2d_checks as c  # noqa: E402

req = urllib.request.Request(c.BASE + "/status.json", headers={"cf-connecting-ip": "198.18.91.1"})
with urllib.request.urlopen(req, timeout=20) as r:
    status, headers, body = r.status, dict(r.headers), r.read().decode("utf-8")
d = json.loads(body)
c.check("item 91: /status.json answers with no sign-in", status == 200, status)
c.check("item 91: it is never cached", "no-store" in headers.get("Cache-Control", ""), headers.get("Cache-Control"))
c.check("item 91: every service is listed", set(d.get("services", {})) == {"app", "database", "ai_engine", "job_runner", "dax_checker", "pbix_maker", "sign_in_mail"},
        d.get("services"))
c.check("item 91: the app and its database are up", d["services"]["app"] is True and d["services"]["database"] is True, d["services"])
c.check("item 91: each service is up, down or not used (true, false, null)", all(v in (True, False, None) for v in d["services"].values()), d["services"])
c.check("item 91: open alerts are counts only", set(d.get("alerts", {})) == {"critical", "all"} and all(isinstance(v, int) for v in d["alerts"].values()), d.get("alerts"))
c.check("item 91: the rest is the overall state, errors in 15 minutes, the version and the time",
        set(d) == {"ok", "services", "alerts", "errors_15min", "version", "time"} and isinstance(d["ok"], bool), sorted(d))
c.check("item 91: nothing personal in it (no addresses, no organisation or dashboard names)", "@" not in body and "tenant" not in body and "pid" not in body, body[:300])
s, r = c.Person("nobody@status91.example").get("/api/admin/orgs")
c.check("item 91: the admin APIs stay closed to it (no session: 401/403/404)", s in (401, 403, 404), s)
bad = [n for n, ok in c.RESULTS if not ok]
print(f"\n{len(c.RESULTS) - len(bad)} of {len(c.RESULTS)} checks passed" + (f"; failed: {bad}" if bad else ""))
sys.exit(len(bad))
