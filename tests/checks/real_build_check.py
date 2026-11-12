"""Test stack with the LIVE Claude sign-in volume mounted (never copied): one real dashboard, planned and built by real
Claude, each run in a job container of its own (item 31). While a run is going, the job container is looked at from
outside: what it holds, its network, its rights, and that another organisation's folder is not there.
python -I -X utf8 real_build_check.py <public> <admin>"""
import json
import os
import subprocess
import sys
import time
import urllib.request

sys.argv = [sys.argv[0], sys.argv[1], sys.argv[2]]
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import d2d_checks as c  # noqa: E402

check = c.check
seen: dict = {}


def jobs() -> list[str]:
    """This stack's running job containers only (labelled with its web container, or before that label in its web
    container's network): a live build on the same PC is never looked into."""
    ids = subprocess.run(["docker", "ps", "-q", "--filter", "label=d2d-relay.job=1"], capture_output=True, text=True).stdout.split()
    if not ids:
        return []
    web_id = subprocess.run(["docker", "inspect", "-f", "{{.Id}}", c.WEB_C], capture_output=True, text=True).stdout.strip()
    out = subprocess.run(["docker", "inspect", "-f", '{{.Name}}|{{index .Config.Labels "d2d-relay.web"}}|{{.HostConfig.NetworkMode}}', *ids],
                         capture_output=True, text=True).stdout
    mine = []
    for line in out.splitlines():
        name, web, net = (line.split("|") + ["", ""])[:3]
        if web == c.WEB_C or (web in ("", "<no value>") and net == f"container:{web_id}"):
            mine.append(name.lstrip("/"))
    return mine


def look(name: str) -> None:
    """The running job container, from outside (once per run)."""
    if name in seen:
        return
    i = json.loads(subprocess.run(["docker", "inspect", name], capture_output=True, text=True).stdout or "[{}]")[0]
    h = i.get("HostConfig") or {}
    ex = lambda cmd: subprocess.run(["docker", "exec", "-u", "agent", name, "sh", "-c", cmd], capture_output=True, text=True,
                                    encoding="utf-8", errors="replace").stdout.strip()
    seen[name] = {"cwd": (i.get("Config", {}).get("Labels") or {}).get("d2d-relay.cwd", ""),
                  "user": i.get("Config", {}).get("User"), "network": h.get("NetworkMode", ""), "caps": h.get("CapDrop"),
                  "mounts": [m.get("Destination") for m in i.get("Mounts") or []],
                  "projects_seen": ex("find /data/projects -maxdepth 3 -mindepth 1 | head -20"),
                  "data_seen": ex("ls -A /data"), "other_org": ex(f"ls /data/projects/.tenants 2>&1"),
                  "state_seen": ex("ls /data/state 2>&1 | head -3"), "sock_seen": ex("ls /run/relay-runner 2>&1; ls /var/run/docker.sock 2>&1")}


def wait_for(p, pid, wanted: tuple, minutes: int) -> dict:
    st, end = {}, time.time() + minutes * 60
    while time.time() < end:
        for j in jobs():
            try:
                look(j)
            except Exception:  # noqa: BLE001 - it may end while we look
                pass
        st = p.get(f"/api/projects/{pid}")[1] or {}
        if st.get("status") in wanted:
            return st
        time.sleep(8)
    return st


other = c.Person(f"oz.other@other{c.STAMP}.com")
other.sign_in("Other Org", "Oz Other")
s, od = c.new_dashboard(other)                     # another organisation's dashboard: its folder must never be in a job
p = c.Person(f"rita.real@real{c.STAMP}.com")
s, r = p.sign_in("Real Build", "Rita Real")
check("setup: an organisation signs up", s == 200, (s, r))
s, d = c.new_dashboard(p)
pid = (d or {}).get("id")
check("setup: a dashboard is made; its plan run starts", s == 200 and pid, (s, str(d)[:150]))
t0 = time.time()
st = wait_for(p, pid, ("awaiting_kpis", "error"), 25)
check("real: Claude planned the dashboard in a job container (awaiting the KPIs)", st.get("status") == "awaiting_kpis",
      (st.get("status"), (st.get("error") or "")[:300]))
print(f"  plan took {round((time.time() - t0) / 60, 1)} min", flush=True)
kpis = ((st.get("plan") or {}).get("kpis")) or []
if st.get("status") == "awaiting_kpis":
    s, r = p.form(f"/api/projects/{pid}/kpis", {"payload": json.dumps({"action": "confirm", "kpis": kpis, "feedback": ""})})
    check("real: the KPIs are confirmed; the build starts", s == 200, (s, str(r)[:200]))
    t1 = time.time()
    st = wait_for(p, pid, ("awaiting_review", "error", "done"), 45)
    check("real: Claude built the dashboard in a job container (awaiting review)", st.get("status") in ("awaiting_review", "done"),
          (st.get("status"), (st.get("error") or "")[:300]))
    print(f"  build took {round((time.time() - t1) / 60, 1)} min", flush=True)
    v = (st.get("versions") or [{}])[-1]
    gates = v.get("gates") or []
    print("  gates:", {g.get("id"): g.get("status") for g in gates}, flush=True)
    check("real: the version has a prototype and its review gates ran", bool(st.get("versions")) and bool(gates),
          {g.get("id"): g.get("status") for g in gates})
check("real: every run went to a job container, and each was looked at while running", len(seen) >= 1, list(seen))
for name, info in seen.items():
    print(f"  {name}: {json.dumps(info)[:900]}", flush=True)
    ok_mounts = all(m.startswith(("/data/projects/", "/home/agent/.claude", "/opt/genbi/library", "/opt/genbi/config")) for m in info["mounts"])
    check(f"isolation: {name} holds only its dashboard's folder (+ sign-in, library, config)", ok_mounts and
          sum(1 for m in info["mounts"] if m.startswith("/data/projects/")) == 1, info["mounts"])
    # each job is checked against its own dashboard (the other organisation's own plan runs in a job container too)
    own = info["cwd"]
    own_org = own.split("/.tenants/", 1)[1].split("/", 1)[0] if "/.tenants/" in own else ""
    foreign = [x for x in info["other_org"].split() if x != own_org]
    outside = [x for x in info["projects_seen"].split() if not (own.startswith(x) or x.startswith(own))]
    check(f"isolation: {name} sees no other organisation's folder, only its own dashboard's ({own})", bool(own) and not foreign
          and not outside, (own, info["other_org"][:200], outside[:5]))
    check(f"isolation: {name} has no /data/state, no Docker socket, no runner socket",
          "No such file" in info["state_seen"] and "No such file" in info["sock_seen"], (info["state_seen"], info["sock_seen"]))
    check(f"isolation: {name} runs as agent, every capability dropped, on the web container's network",
          info["user"] == "agent" and info["caps"] == ["ALL"] and info["network"].startswith("container:"), info)
check("real: no job container is left", not jobs(), jobs())
tids = subprocess.run(["docker", "exec", "-u", "postgres", c.DB_C, "psql", "-qtA", "-h", "/run/postgresql", "-d", "relay", "-c",
                       f"SELECT string_agg(tenant_id, ' ') FROM relay.tn_orgs WHERE domain IN ('real{c.STAMP}.com', 'other{c.STAMP}.com')"],
                      capture_output=True, text=True).stdout.strip()
print(f"\nTranscripts to delete afterwards, for each of the organisations {tids}: ./-data-projects--tenants-<organisation>-*")
ok = sum(1 for _, x in c.RESULTS if x)
print(f"{ok}/{len(c.RESULTS)} checks passed")
