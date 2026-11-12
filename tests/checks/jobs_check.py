"""Test stack only: item 31, each AI build in a container of its own (docker/job_runner.py). Without a Claude sign-in
on the stack the runs fail at once, which is enough to check the plumbing: a build goes through a job container that
holds only its dashboard's folder, the run fails cleanly with credits back, nothing is left running; the runner's
socket is only the AI engine's, and it refuses anything but a claude command in a dashboard folder.
python -I -X utf8 jobs_check.py <public> <admin>"""
import json
import os
import subprocess
import sys
import time

sys.argv = [sys.argv[0], sys.argv[1], sys.argv[2]]
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import d2d_checks as c  # noqa: E402

check = c.check
RUNNER = os.environ.get("D2D_TEST_RUNNER", "d2d-relay-test-runner")


def sh(container: str, user: str, cmd: str, timeout: int = 120) -> str:
    r = subprocess.run(["docker", "exec", "-u", user, container, "sh", "-c", cmd], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout)
    return (r.stdout + r.stderr).strip()


def runner_call(user: str, body: dict) -> str:
    code = ("import httpx, json, sys\n"
            "c = httpx.Client(transport=httpx.HTTPTransport(uds='/run/relay-runner/runner.sock'), base_url='http://runner', timeout=120)\n"
            f"r = c.post('/jobs', json=json.loads({json.dumps(json.dumps(body))}))\n"
            "print(r.status_code, r.text[-400:].replace(chr(10), ' | '))\n")
    r = subprocess.run(["docker", "exec", "-i", "-u", user, c.WEB_C, "/usr/local/bin/python3", "-P", "-"], input=code,
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
    return (r.stdout + r.stderr).strip()


def logs(container: str, since: str = "10m") -> str:
    r = subprocess.run(["docker", "logs", "--since", since, container], capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.stdout + r.stderr


def jobs_left() -> list[str]:
    r = subprocess.run(["docker", "ps", "-a", "--filter", "label=d2d-relay.job=1", "--format", "{{.Names}}"], capture_output=True, text=True)
    return [x for x in r.stdout.split() if x]


# ---------------------------------------------------------------- a build goes through a job container
p = c.Person(f"jo.jobs@jobs{c.STAMP}.com")
s, r = p.sign_in("Jobs Test", "Jo Jobs")
check("setup: an organisation signs up", s == 200, (s, r))
before = (p.get("/api/me")[1].get("org") or {}).get("credits")
s, d = c.new_dashboard(p)
pid = (d or {}).get("id")
check("setup: a dashboard is made (its plan run starts)", s == 200 and pid, (s, str(d)[:150]))
st = {}
for _ in range(90):
    st = p.get(f"/api/projects/{pid}")[1] or {}
    if st.get("status") == "error":
        break
    time.sleep(2)
rl = logs(RUNNER)
started = [ln for ln in rl.splitlines() if "[runner] started" in ln and pid in ln]
check("jobs: the plan run went to a job container of its own", bool(started), rl[-600:])
line = started[0] if started else ""
mounted = [x.strip() for x in line.split(": ", 1)[1].split(",")] if ": " in line else []
check("jobs: the job container holds only that dashboard's folder and the Claude sign-in (no /data, no other folders)",
      len([m for m in mounted if m.startswith("/data")]) == 1 and mounted[0].endswith("/" + pid) and "/home/agent/.claude" in mounted
      and all(m.startswith(("/data/projects/", "/home/agent/.claude", "/opt/genbi/library", "/opt/genbi/config")) for m in mounted), mounted)
check("jobs: it was removed when the run ended", any("[runner] removed" in ln for ln in rl.splitlines()) and not jobs_left(), (jobs_left(), rl[-300:]))
acts = p.get(f"/api/projects/{pid}/activity")[1]
texts = " ".join(str(e.get("text", "")) for e in acts) if isinstance(acts, list) else ""
check("jobs: the run failed cleanly (no Claude sign-in on the test stack), saying why", st.get("status") == "error" and texts, texts[-300:])
after = (p.get("/api/me")[1].get("org") or {}).get("credits")
check("jobs: the failed run's credits came back", after == before, (before, after))

# ---------------------------------------------------------------- the runner's socket and its rules
perm = sh(c.WEB_C, "root", "stat -c '%U %a' /run/relay-runner/runner.sock")
check("runner: its socket belongs to the AI engine's user only (agent, 600)", perm == "agent 600", perm)
out = runner_call("relay", {"cwd": "/data/projects/x", "argv": ["claude", "--version"]})
check("runner: the web app's user cannot use it (permission denied)", "ermission" in out or "PermissionError" in out, out[-200:])
for name, body in (("a command other than claude", {"cwd": f"/data/projects/{pid}", "argv": ["sh", "-c", "id"]}),
                   ("a folder outside the projects", {"cwd": "/data/state", "argv": ["claude", "--version"]}),
                   ("a path that climbs out", {"cwd": f"/data/projects/{pid}/../..", "argv": ["claude", "--version"]}),
                   ("a library outside the library", {"cwd": f"/data/projects/{pid}", "argv": ["claude", "--version"], "library": "/data"}),
                   ("a folder that does not exist", {"cwd": "/data/projects/no-such-dashboard-x1", "argv": ["claude", "--version"]})):
    out = runner_call("agent", body)
    check(f"runner: refuses {name}", out[:3] in ("400", "404"), out[-200:])
folder = sh(c.WEB_C, "root", f"find /data/projects -maxdepth 3 -type d -name {pid} | head -1")
out = runner_call("agent", {"cwd": folder, "argv": ["claude", "--version"]})
check("runner: a claude command in a dashboard folder runs in a job container and streams back", out.startswith("200") and '"x": 0' in out,
      out[-300:])
check("runner: nothing is left behind", not jobs_left(), jobs_left())
nets = subprocess.run(["docker", "inspect", "-f", "{{.HostConfig.NetworkMode}}", RUNNER], capture_output=True, text=True).stdout.strip()
check("runner: has no network of its own", nets == "none", nets)

ok = sum(1 for _, x in c.RESULTS if x)
print(f"{ok}/{len(c.RESULTS)} checks passed")
