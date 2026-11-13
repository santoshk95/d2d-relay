"""Test stack only: item 42 (the user, 2026-11-13: "claude api key ... as primary and personal as backup"). Inside the
test web container (no AI call is made, no key is real):
- without RELAY_ANTHROPIC_API_KEY nothing changes: the installation's Claude login, no backup;
- with it: every run's main provider is the key (as the run's own ANTHROPIC_API_KEY), and the backup is the
  installation's Claude login (no credential passed, so the AI engine's own sign-in answers);
- Ask Relay falls back once on an authentication, credit, rate-limit or outage error, with an ai.fallback record; any
  other error is not retried; a failed answer (ok false) with such an error falls back too;
- the AI engine never holds the key itself (it would then answer every run with it, and the backup could not work).
A real-Claude run of the fallback is a separate, manual step (docs/LOG.md, item 42).
python -I -X utf8 item42_check.py <public> <admin>"""
import json
import os
import subprocess
import sys

sys.argv = [sys.argv[0], sys.argv[1], sys.argv[2]]
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import d2d_checks as c  # noqa: E402

check = c.check


def in_app(script: str) -> str:
    r = subprocess.run(["docker", "exec", "-i", "-u", "relay", "-w", "/srv", c.WEB_C, "/opt/relay/bin/launch", "web", "python", "-"],
                       input=script, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
    lines = (r.stdout or "").strip().splitlines()
    return lines[-1] if lines else (r.stderr or "")[-600:]


def as_json(text: str) -> dict:
    try:
        return json.loads(text)
    except ValueError:
        return {"raw": text}


print("\n== which provider runs, and which backs it")
r = as_json(in_app("""
import json
from app import providers as p
out = {}
m = p.run_config(None, 'sonnet', 60)
out['none'] = {'kind': m['kind'], 'env': sorted(m['env']), 'provider': m['provider'], 'backup': p.backup_kind(None),
               'key_set': bool(p.INSTALL_API_KEY)}
p.INSTALL_API_KEY = 'sk-ant-item42-not-a-real-key'
for who in (None, 'u-item42-nobody'):
    m = p.run_config(who, 'sonnet', 60)
    b = p.run_config(who, 'sonnet', 60, kind=p.backup_kind(who))
    out[str(who)] = {'kind': m['kind'], 'key_is_install_key': m['env'].get('ANTHROPIC_API_KEY') == p.INSTALL_API_KEY,
                     'other_env': sorted(k for k in m['env'] if k != 'ANTHROPIC_API_KEY'), 'provider': m['provider'],
                     'backup': p.backup_kind(who), 'backup_env': sorted(b['env']), 'backup_provider': b['provider']}
print(json.dumps(out))
"""))
none = r.get("none") or {}
check("no key: the installation's Claude login, no credential passed, no backup (as before)",
      none.get("key_set") is False and none.get("kind") == "claude_account" and none.get("env") == [] and none.get("backup") is None, r)
for who in ("None", "u-item42-nobody"):
    x = r.get(who) or {}
    check(f"key set ({'no owner' if who == 'None' else 'a person with no provider of their own'}): the key runs first, as the run's ANTHROPIC_API_KEY",
          x.get("kind") == "anthropic_api" and x.get("key_is_install_key") is True and x.get("other_env") == []
          and x.get("provider") == "Anthropic API (this installation's key)", x)
    check(f"key set ({'no owner' if who == 'None' else 'a person'}): the backup is the installation's Claude login (no credential)",
          x.get("backup") == "claude_account" and x.get("backup_env") == [] and x.get("backup_provider") == "Claude (this installation's login)", x)

print("\n== Ask Relay falls back once")
r = as_json(in_app("""
import asyncio, json
from app import askd, db, providers as p
p.INSTALL_API_KEY = 'sk-ant-item42-not-a-real-key'
u = {'id': 'u-item42-asker'}
calls = []
def fake(script):
    async def run(u, prompt, session, workdir, system, cfg):
        calls.append(cfg['provider'])
        step = script[len(calls) - 1]
        if isinstance(step, Exception):
            raise step
        return {**step, 'kind': 'done', 'provider': cfg['provider']}
    return run
out = {}
with db.use(db.PLATFORM):
    for name, script in (('auth', [askd.AskError('API Error: 401 {"error":{"type":"authentication_error","message":"invalid x-api-key"}}'), {'text': 'OK'}]),
                         ('credit', [{'ok': False, 'text': 'Credit balance is too low'}, {'text': 'OK'}]),
                         ('other', [askd.AskError('The AI provider stopped without an answer.')]),
                         ('fine', [{'text': 'OK'}])):
        calls.clear()
        askd._claude_run = fake(script)
        try:
            res = asyncio.run(askd._claude(u, 'Reply OK', None, '/tmp', model='sonnet', system='x'))
            out[name] = {'provider': res.get('provider'), 'fallback': bool(res.get('fallback')), 'calls': list(calls)}
        except askd.AskError as e:
            out[name] = {'error': str(e)[:80], 'calls': list(calls)}
    out['audits'] = db.one("SELECT count(*) AS n FROM audit WHERE action = 'ai.fallback' AND who = 'u-item42-asker'")['n']
print(json.dumps(out))
"""))
key, login = "Anthropic API (this installation's key)", "Claude (this installation's login)"
check("Ask Relay: a refused key (401) is answered once more on the Claude login",
      (r.get("auth") or {}).get("calls") == [key, login] and (r.get("auth") or {}).get("fallback") is True
      and (r.get("auth") or {}).get("provider") == login, r.get("auth") or r)
check("Ask Relay: an answer that failed for credit is answered on the Claude login",
      (r.get("credit") or {}).get("calls") == [key, login] and (r.get("credit") or {}).get("fallback") is True, r.get("credit") or r)
check("Ask Relay: any other error is not retried (one call, the error shown)",
      (r.get("other") or {}).get("calls") == [key] and "without an answer" in str((r.get("other") or {}).get("error")), r.get("other") or r)
check("Ask Relay: a good answer from the key stays the key's (no fallback)",
      (r.get("fine") or {}).get("calls") == [key] and (r.get("fine") or {}).get("fallback") is False, r.get("fine") or r)
check("Ask Relay: each fallback leaves an ai.fallback record", r.get("audits") == 2, r.get("audits"))

print("\n== the AI engine never holds the key itself")
pid = subprocess.run(["docker", "exec", c.WEB_C, "pgrep", "-u", "agent", "-o", "-f", "server"], capture_output=True, text=True).stdout.strip()
env = subprocess.run(["docker", "exec", "-u", "root", c.WEB_C, "sh", "-c", f"tr '\\0' '\\n' < /proc/{pid}/environ | cut -d= -f1"],
                     capture_output=True, text=True).stdout.split() if pid else []
check("the AI engine's own environment has no Anthropic key, whatever the web app holds",
      bool(env) and not any(k in env for k in ("ANTHROPIC_API_KEY", "D2D_ANTHROPIC_API_KEY", "RELAY_ANTHROPIC_API_KEY")),
      {"pid": pid, "keys": [k for k in env if "ANTHROPIC" in k]})

ok = sum(1 for _, x in c.RESULTS if x)
print(f"{ok}/{len(c.RESULTS)} checks passed")
sys.exit(0 if ok == len(c.RESULTS) else 1)
