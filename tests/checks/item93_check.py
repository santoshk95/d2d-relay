"""Item 93 (2026-11-20): PASDACS chooses on the admin portal which Claude the Relay Model runs on first: the
subscription (the AI engine's login; the API key its backup) or the API key (paid per token; the subscription its
backup). Saved in the control plane, read by every run within about 15 seconds; the API needs the installation's key.

python -I -X utf8 item93_check.py http://127.0.0.1:8103 http://127.0.0.1:8104
"""
import json
import os
import subprocess
import sys

sys.argv = [sys.argv[0], sys.argv[1], sys.argv[2]]
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import d2d_checks as c  # noqa: E402

admin = c.signed_in("info@pasdacs.com", c.ADMIN_BASE)
s, a = admin.get("/api/admin/ai")
c.check("item 93: the admin portal says which Claude runs first", s == 200 and a.get("primary") in ("api", "subscription")
        and isinstance(a.get("key_set"), bool), (s, a))
p = c.Person(f"ana.ai@ai93{c.STAMP}.com")
s, r = p.sign_in("AI Choice", "Ana Owner")
s, r = p.get("/api/admin/ai")
c.check("item 93: the public site has no such route (404)", s == 404, (s, r))
s, r = admin.put("/api/admin/ai", {"primary": "gpt"})
c.check("item 93: only the subscription or the API key (400)", s == 400, (s, r))
s, r = admin.put("/api/admin/ai", {"primary": "subscription"})
c.check("item 93: PASDACS picks the subscription", s == 200 and r.get("primary") == "subscription", (s, r))
if not a.get("key_set"):
    s, r = admin.put("/api/admin/ai", {"primary": "api"})
    c.check("item 93: the API key needs a key set for the installation (400, says so)", s == 400 and "RELAY_ANTHROPIC_API_KEY" in json.dumps(r), (s, r))


def in_app(script: str) -> str:
    r = subprocess.run(["docker", "exec", "-i", "-u", "relay", "-w", "/srv", c.WEB_C, "/opt/relay/bin/launch", "web", "python", "-"],
                       input=script, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
    lines = (r.stdout or "").strip().splitlines()
    return lines[-1] if lines else (r.stderr or "")[-600:]


r = in_app("""
import json
from app import db, providers as p
p.INSTALL_API_KEY = p.INSTALL_API_KEY or 'sk-ant-item93-not-a-real-key'
out = {}
p.set_ai_primary('api')
out['api'] = [p.run_config(None, 'relay', 60)['kind'], p.backup_kind(None)]
p.set_ai_primary('subscription')
out['sub'] = [p.run_config(None, 'relay', 60)['kind'], p.backup_kind(None)]
db.set_ctl_meta('ai_primary', 'api'); p._PRIMARY['at'] = 0
out['read'] = p.ai_primary()
p.set_ai_primary('subscription')
print(json.dumps(out))
""")
try:
    d = json.loads(r)
except ValueError:
    d = {"raw": r}
c.check("item 93: API key first: runs take the key, the subscription backs them", d.get("api") == ["anthropic_api", "claude_account"], d)
c.check("item 93: subscription first: runs take the login, the key backs them", d.get("sub") == ["claude_account", "anthropic_api"], d)
c.check("item 93: a choice saved by the admin portal is what the runs read", d.get("read") == "api", d)
s, r = admin.get("/api/admin/ai")
c.check("item 93: back to the subscription", s == 200 and r.get("primary") == "subscription", (s, r))
bad = [n for n, ok in c.RESULTS if not ok]
print(f"\n{len(c.RESULTS) - len(bad)} of {len(c.RESULTS)} checks passed" + (f"; failed: {bad}" if bad else ""))
sys.exit(len(bad))
