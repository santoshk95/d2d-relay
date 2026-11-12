"""The workload schedulers of Job scheduling as Connector SDK adapters - one adapter + one mock-lab simulator each
(tests/mocklab/sims/schedulers.py: `controlm`, `autosys`, `cron`) - into the W2 neutral shape: each job an automation
(kind "job") with its schedule, its command, its parameters and the jobs it waits for (`deps`); each run a run.

  Control-M   Automation API: an API token in x-api-key (or a session token from session/login); deploy/jobs (the
              folders' JSON definitions), run/jobs/status by order date, run/job/{id}/output for a run that ended not
              OK. After approval: a changed folder deployed (build validates it first, without writing), the failed
              order rerun and the jobs that waited for it watched until they end.
  AutoSys     AEWS web services with basic auth: jobs, their JIL, run history (job-run-info, next links).
  cron        crontab files (/etc/crontab with a user column, a user's crontab without) and the cron log, uploaded.
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone

from .. import connectors
from .. import connectors_sdk as sdk
from . import _w2
from .n8n_platforms import _cached, _keep

PASS_ARG = re.compile(r"--[\w-]*pass(?:word)?\s+(\S+)", re.I)


def secrets_in_command(cmd: str, where: str) -> list[dict]:
    return [{"where": where, "kind": "a password on the command line"}] if PASS_ARG.search(cmd or "") else []


def _job(name, *, command, schedule, deps, active, owner=None, params=None, host="", folder="", platform="", definition=None, kind="job", **extra) -> dict:
    a = _w2.auto(f"{platform}:{name}", name, platform, kind=kind, active=active, trigger={"kind": "schedule" if schedule else "manual", "detail": schedule or "not scheduled"},
                 steps=[_w2.step(name, "code", detail=command or "")], definition=None, owner=owner, schedule=schedule, deps=[f"{platform}:{d}" for d in deps or []], params=dict(params or {}),
                 host=host, folder=folder, command=command or "", **extra)
    a["secrets"] = secrets_in_command(command, f"the command of {name}")
    a["definition"] = definition
    return a


# ================================================================== Control-M

def ctm_when(w: dict) -> str:
    """A job's When in words: daily 02:00, weekly MON 06:00, monthly 20 09:00, hourly :15."""
    if not w:
        return ""
    t = str(w.get("FromTime") or "")
    hm = f"{t[:2]}:{t[2:]}" if len(t) == 4 else t
    md, wd = w.get("MonthDays") or [], w.get("WeekDays") or []
    if wd:
        return f"weekly {' '.join(wd)} {hm}"
    if md and md != ["ALL"]:
        return f"monthly {','.join(md)} {hm}"
    return f"daily {hm}"


def ctm_dt(s: str) -> float | None:
    try:
        return datetime.strptime(s, "%b %d, %Y %I:%M:%S %p").replace(tzinfo=timezone.utc).timestamp() if s else None
    except ValueError:
        return None


class ControlMApi(_w2.Adapter):
    kind, label, vendor, platform = "controlm_api", "Control-M", "Control-M", "Control-M"
    simulator = "tests/mocklab/sims/schedulers.py: controlm (Automation API)"
    fields = [("base_url", "Automation API endpoint (https://<em>:8443/automation-api)", True), ("server", "Control-M/Server name", True), ("username", "User (for a session token; blank with an API token)", False)]
    secrets = {"api_key": ["api_token", "password"]}
    can_write = True

    def signin_headers(self, c):
        try:
            return {"x-api-key": _w2.secret(c, "api_token")}
        except connectors.ConnectorError:
            pass
        tok = _cached(c)
        if not tok:
            d = _w2.call("Control-M", "POST", self.base(c) + "/session/login", json_body={"username": _w2.cfg(c, "username"), "password": _w2.secret(c, "password")}).json()
            tok = _keep(c, d["token"], 1700)
        return {"Authorization": f"Bearer {tok}"}

    def folders(self, c) -> dict:
        return self.req(c, "GET", "/deploy/jobs", params={"server": _w2.cfg(c, "server") or "*", "folder": "*", "format": "json"}).json()

    def estate(self, c):
        out = []
        for fname, f in self.folders(c).items():
            manual = f.get("OrderMethod") == "Manual"
            for jn, d in f.items():
                if not isinstance(d, dict) or not str(d.get("Type", "")).startswith("Job:"):
                    continue
                deps = [e["Event"].rsplit("-OK", 1)[0] for e in ((d.get("eventsToWaitFor") or {}).get("Events") or []) if str(e.get("Event", "")).endswith("-OK")]
                params = {k: v for x in d.get("Variables") or [] for k, v in x.items()}
                cmd = d.get("Command") or (f"watch {d.get('Path')} for {d.get('TimeLimit')} min" if d.get("Path") else "")
                out.append(_job(jn, command=cmd, schedule="" if manual else ctm_when(d.get("When") or {}), deps=deps, active=not manual, owner=d.get("CreatedBy"), params=params,
                                host=d.get("Host") or "", folder=fname, platform=self.kind, definition=d, watcher=d.get("Type") == "Job:FileWatcher:Create",
                                description=d.get("Description") or ""))
        return out

    def statuses(self, c, since_days: int = 14) -> list[dict]:
        frm = time.strftime("%y%m%d", time.gmtime(_w2.wb.lab_now() - since_days * 86400))
        return self.req(c, "GET", "/run/jobs/status", params={"orderDateFrom": frm, "limit": 10000}).json().get("statuses") or []

    def output(self, c, job_id: str) -> str:
        r = self.req(c, "GET", f"/run/job/{job_id}/output", ok=(200, 404))
        return r.text if r.status_code == 200 else ""

    def runs(self, c, autos, since=None):
        out, seen = [], {}
        for s in sorted(self.statuses(c), key=lambda x: (x.get("orderDate") or "", x.get("startTime") or ""), reverse=True):     # newest first: their output is read
            st = {"Ended OK": "success", "Ended Not OK": "failed", "Executing": "running", "Wait Condition": "waiting"}.get(s["status"], s["status"].lower())
            err = None
            if st == "failed":
                k = seen.get(s["name"], 0)
                if k < 3:                                   # the error words of the last three failures per job (each is one call)
                    txt = self.output(c, s["jobId"])
                    err = next((ln.split("ERROR:", 1)[1].strip() for ln in txt.splitlines() if "ERROR:" in ln), None) or next((ln for ln in reversed(txt.splitlines()) if "rc=" in ln), None) or next((ln for ln in reversed(txt.splitlines()) if ln.strip()), None) or "ended not OK"
                    seen[s["name"]] = k + 1
                else:
                    err = "ended not OK"
            start = ctm_dt(s.get("startTime")) or datetime.strptime(s["orderDate"], "%y%m%d").replace(tzinfo=timezone.utc).timestamp()
            out.append(_w2.run(s["jobId"], f"{self.kind}:{s['name']}", st, start, ctm_dt(s.get("endTime")), err, None, odate=s.get("orderDate"), held=s.get("held") == "true"))
        return [r for r in out if not since or (r["start"] or 0) >= since]

    def _form(self, folder: str, definition: dict) -> tuple[bytes, str]:
        b = "relay" + _w2.sha(definition)[:12]
        body = (f'--{b}\r\nContent-Disposition: form-data; name="definitionsFile"; filename="{folder}.json"\r\nContent-Type: application/json\r\n\r\n').encode() + \
               json.dumps({folder: definition}).encode() + f"\r\n--{b}--\r\n".encode()
        return body, f"multipart/form-data; boundary={b}"

    def build(self, c, folder: str, definition: dict) -> list[str]:
        """Control-M's own validation of a folder (build: nothing is written). Problems in its words, or []."""
        body, ct = self._form(folder, definition)
        r = self.req(c, "POST", "/build", content=body, headers={"Content-Type": ct}, ok=(200, 400))
        return [] if r.status_code == 200 else [e.get("message") for e in r.json().get("errors") or []]

    def _status(self, c, job_id) -> dict:
        return self.req(c, "GET", f"/run/job/{job_id}/status").json()

    def _wait(self, c, job_id, done=("Ended OK", "Ended Not OK"), tries=40) -> dict:
        s = {}
        for i in range(tries):
            s = self._status(c, job_id)
            if s.get("status") in done:
                return s
            time.sleep(min(0.5, 0.03 * (i + 1)))
        return s

    def write_now(self, c, obj, payload, approval):
        if obj == "deploy_rerun":
            probs = self.build(c, payload["folder"], payload["definition"])
            if probs:
                raise connectors.ConnectorError("Control-M refused the folder: " + "; ".join(probs[:3]))
            body, ct = self._form(payload["folder"], payload["definition"])
            self.req(c, "POST", "/deploy", content=body, headers={"Content-Type": ct}, approval=approval)
            reruns = []
            for jid in payload.get("rerun") or []:
                self.req(c, "POST", f"/run/job/{jid}/rerun", approval=approval)
                s = self._wait(c, jid)
                reruns.append({"of": jid, "id": jid, "status": "success" if s.get("status") == "Ended OK" else "failed", "error": None if s.get("status") == "Ended OK" else s.get("status")})
            after = []
            for jid in payload.get("watch") or []:
                s = self._wait(c, jid)
                after.append({"job": s.get("name"), "id": jid, "status": s.get("status")})
            return {"ok": all(r["status"] == "success" for r in reruns), "reruns": reruns, "downstream": after}
        if obj == "rerun":
            out = []
            for jid in payload.get("jobs") or []:
                self.req(c, "POST", f"/run/job/{jid}/rerun", approval=approval)
                s = self._wait(c, jid)
                out.append({"of": jid, "id": jid, "status": "success" if s.get("status") == "Ended OK" else "failed", "error": None if s.get("status") == "Ended OK" else s.get("status")})
            return {"ok": all(r["status"] == "success" for r in out), "reruns": out}
        if obj == "deploy_new":
            for folder, d in (payload.get("folders") or {}).items():
                probs = self.build(c, folder, d)
                if probs:
                    raise connectors.ConnectorError(f"Control-M refused {folder}: " + "; ".join(probs[:3]))
                body, ct = self._form(folder, d)
                self.req(c, "POST", "/deploy", content=body, headers={"Content-Type": ct}, approval=approval)
            have = self.req(c, "GET", "/deploy/jobs", params={"server": _w2.cfg(c, "server") or "*", "folder": "*", "format": "json"}).json()
            want = {f: sorted(k for k, v in d.items() if isinstance(v, dict) and str(v.get("Type", "")).startswith("Job:")) for f, d in (payload.get("folders") or {}).items()}
            missing = [f"{f}/{j}" for f, js in want.items() for j in js if j not in (have.get(f) or {})]
            if missing:
                raise connectors.ConnectorError("Control-M took the deploy but does not show " + ", ".join(missing[:6]))
            return {"ok": True, "folders": sorted(want), "jobs": sorted(j for js in want.values() for j in js)}
        raise sdk.ScopeError(f"Control-M: Relay does not write {obj!r}")


# ================================================================== AutoSys (AEWS)

def parse_jil(text: str) -> dict:
    """{job: {attribute: value}} from JIL (insert_job blocks; comments dropped)."""
    out, cur = {}, None
    for raw in (text or "").splitlines():
        ln = re.sub(r"/\*.*?\*/", "", raw).strip()
        if not ln:
            continue
        m = re.match(r"insert_job:\s*(\S+)\s+job_type:\s*(\S+)", ln)
        if m:
            cur = m.group(1)
            out[cur] = {"job_type": m.group(2)}
            continue
        if cur and ":" in ln:
            k, v = ln.split(":", 1)
            out[cur][k.strip()] = v.strip()
    return out


def jil_when(d: dict) -> str:
    if d.get("date_conditions") != "1":
        return ""
    t = (d.get("start_times") or "").strip('"')
    if d.get("start_mins"):
        return f"hourly :{int(d['start_mins']):02d}"
    if d.get("run_calendar"):
        return f"calendar {d['run_calendar']} {t}"
    dw = d.get("days_of_week") or "all"
    return f"daily {t}" if dw == "all" else f"weekly {dw} {t}"


class AutoSysAews(_w2.Adapter):
    kind, label, vendor, platform = "autosys_aews", "AutoSys", "AutoSys", "AutoSys"
    can_write = True
    simulator = "tests/mocklab/sims/schedulers.py: autosys (AEWS)"
    signin = ["password"]
    fields = [("base_url", "AEWS URL (https://<host>:9443/AEWS)", True), ("username", "User", True)]
    secrets = {"password": ["password"]}

    def signin_headers(self, c):
        import base64
        return {"Authorization": "Basic " + base64.b64encode(f"{_w2.cfg(c, 'username')}:{_w2.secret(c, 'password')}".encode()).decode(), "Accept": "application/json"}

    def estate(self, c):
        jil = parse_jil(self.req(c, "GET", "/jil/job", params={"name": "ALL"}).text)
        status = {j["name"]: j.get("status") for j in self.req(c, "GET", "/job", params={"filter": "name==*"}).json().get("job") or []}
        out = []
        for n, d in jil.items():
            if d["job_type"] == "BOX":
                continue
            deps = re.findall(r"s\((\w+)\)", d.get("condition") or "")
            params = dict(x.strip().split("=", 1) for x in (d.get("envvars") or "").split(",") if "=" in x)
            out.append(_job(n, command=d.get("command") or (f"watch {d.get('watch_file')}" if d.get("watch_file") else ""), schedule=jil_when(d), deps=deps, active=status.get(n) != "7",
                            owner=d.get("owner"), params=params, host=d.get("machine") or "", folder=d.get("box_name") or "", platform=self.kind, definition=d,
                            description=(d.get("description") or "").strip('"')))
        return out

    def runs(self, c, autos, since=None):
        out = []
        for a in autos or self.estate(c):
            url, p = f"/job-run-info/{a['name']}", {"count": 200}
            for _ in range(20):
                r = self.req(c, "GET", url, params=p, ok=(200, 404))
                if r.status_code == 404:
                    break
                d = r.json()
                for x in d.get("jobRun") or []:
                    st = {"4": "success", "5": "failed", "6": "failed", "1": "running"}.get(str(x.get("status")), "unknown")
                    out.append(_w2.run(f"{a['name']}:{x['runNum']}", a["id"], st, x.get("runStartTime"), x.get("runEndTime"), f"exit code {x.get('exitCode')}" if st == "failed" else None))
                nxt = (d.get("next") or {}).get("@href")
                if not nxt:
                    break
                url, p = nxt, None
        return [r for r in out if not since or (r["start"] or 0) >= since]

    def _state(self, c, name) -> str:
        return {"4": "Ended OK", "5": "failed", "6": "failed", "1": "running", "3": "running"}.get(str(self.req(c, "GET", f"/job/{name}").json().get("status")), "waiting")

    def _until(self, c, name, tries=40) -> str:
        st = "running"
        for i in range(tries):
            st = self._state(c, name)
            if st in ("Ended OK", "failed"):
                return st
            time.sleep(min(0.5, 0.03 * (i + 1)))
        return st

    def write_now(self, c, obj, payload, approval):
        if obj == "insert_jobs":
            from xml.sax.saxutils import escape
            body = f"<commandRequest><command>jil</command><inFile>{escape(payload['jil'])}</inFile></commandRequest>".encode()
            r = self.req(c, "POST", "/command/run", content=body, headers={"Content-Type": "application/xml", "Accept": "application/json"}, approval=approval).json()
            if int(r.get("exitCode", 1)) != 0:
                raise connectors.ConnectorError("AutoSys refused the JIL: " + str(r.get("output"))[:300])
            missing = [j for j in payload.get("jobs") or [] if self.req(c, "GET", f"/job/{j}", ok=(200, 404)).status_code != 200]
            if missing:
                raise connectors.ConnectorError("AutoSys took the JIL but does not show " + ", ".join(missing))
            return {"ok": True, "jobs": list(payload.get("jobs") or [])}
        if obj == "update_restart":
            from xml.sax.saxutils import escape
            body = f"<commandRequest><command>jil</command><inFile>{escape(payload['jil'])}</inFile></commandRequest>".encode()
            r = self.req(c, "POST", "/command/run", content=body, headers={"Content-Type": "application/xml", "Accept": "application/json"}, approval=approval).json()
            if int(r.get("exitCode", 1)) != 0:
                raise connectors.ConnectorError("AutoSys refused the JIL: " + str(r.get("output"))[:300])
            self.req(c, "POST", "/event/restart-job", json_body={"jobName": payload["job"], "comment": "Relay: restarted after the approved change"}, approval=approval, ok=(200, 201))
            st = self._until(c, payload["job"])
            after = [{"job": d, "id": d, "status": self._until(c, d)} for d in payload.get("watch") or []] if st == "Ended OK" else []
            return {"ok": st == "Ended OK", "reruns": [{"of": payload["job"], "id": payload["job"], "status": "success" if st == "Ended OK" else "failed", "error": None if st == "Ended OK" else st}],
                    "downstream": after}
        raise sdk.ScopeError(f"AutoSys: Relay does not write {obj!r}")


_w2.register(ControlMApi(), AutoSysAews())
SCHEDULERS = ("controlm_api", "autosys_aews")


# ================================================================== cron (files)

CRON_LINE = re.compile(r"^\s*(?P<min>\S+)\s+(?P<hour>\S+)\s+(?P<dom>\S+)\s+(?P<mon>\S+)\s+(?P<dow>\S+)\s+(?P<rest>.+)$")
JOB_NAME = re.compile(r"run_job\.sh\s+(\w+)|start_process\.cmd\s+(\w+)|refresh_dataset\.sh\s+'?([\w ]+)'?")


def cron_when(mi, hr, dom, mon, dow) -> str:
    if hr == "*" and mi.isdigit():
        return f"hourly :{int(mi):02d}"
    t = f"{int(hr):02d}:{int(mi):02d}" if hr.isdigit() and mi.isdigit() else f"{hr} {mi}"
    if dom != "*" and dow == "*":
        return f"monthly {dom} {t}"
    if dow not in ("*", "0-6", "0-7"):
        return f"weekly {dow} {t}"
    return f"daily {t}"


def parse_crontab(name: str, text: str) -> list[dict]:
    """Jobs from a crontab: /etc/crontab (a user column) or a user's crontab; a commented-out line is a job switched off."""
    out = []
    for raw in text.splitlines():
        off = raw.lstrip().startswith("#")
        ln = raw.lstrip("# ").rstrip() if off else raw.strip()
        if not ln or re.match(r"^\w+=", ln) or ln.startswith("@"):
            continue
        m = CRON_LINE.match(ln)
        if not m:
            continue
        rest = m.group("rest")
        user = None
        tok = rest.split(None, 1)                      # /etc/crontab has a user column before the command
        if len(tok) == 2 and re.fullmatch(r"[a-z_][\w-]*", tok[0]) and tok[1].lstrip().startswith(("/", "cd ", "find ", "C:")):
            user, rest = tok[0], tok[1]
        if not re.search(r"[/\\]", rest):
            continue
        jm = JOB_NAME.search(rest)
        jn = next((g for g in (jm.groups() if jm else ()) if g), None) or _w2.slug(rest, 40).upper()
        params = dict(re.findall(r"--param\s+(\w+)=(\S+)", rest))
        out.append(_job(jn.replace(" ", "_").upper(), command=re.sub(r"\s*>>.*$", "", rest), schedule=cron_when(*(m.group(k) for k in ("min", "hour", "dom", "mon", "dow"))), deps=[],
                        active=not off, owner=user, params=params, host=name, folder="cron", platform="cron", definition={"line": ln, "user": user, "fields": [m.group(k) for k in ("min", "hour", "dom", "mon", "dow")]}))
    return out


def parse_file(name: str, data: bytes) -> dict:
    low = name.lower()
    try:
        text = data.decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return {"kind": None, "autos": [], "runs": []}
    if low.endswith(".jil") or "insert_job:" in text:
        jil = parse_jil(text)
        autos = [_job(n, command=d.get("command") or "", schedule=jil_when(d), deps=re.findall(r"s\((\w+)\)", d.get("condition") or ""), active=True, owner=d.get("owner"),
                      host=d.get("machine") or "", folder=d.get("box_name") or "", platform="autosys_aews", definition=d) for n, d in jil.items() if d["job_type"] != "BOX"]
        return {"kind": "AutoSys JIL", "autos": autos, "runs": []}
    if "crontab" in low or low.endswith((".cron", ".tab")) or re.search(r"(?m)^\s*#?\s*[\d*/,-]+\s+[\d*/,-]+\s+[\d*/,-]+\s+[\d*/,-]+\s+[\d*/,-]+\s+\S", text):
        autos = parse_crontab(name, text)
        if autos:
            return {"kind": "crontab", "autos": autos, "runs": []}
    if low.endswith(".json") and "Job:" in text:
        try:
            d = json.loads(text)
        except ValueError:
            return {"kind": None, "autos": [], "runs": []}
        autos = []
        for fname, f in d.items():
            for jn, jd in (f or {}).items():
                if isinstance(jd, dict) and str(jd.get("Type", "")).startswith("Job:"):
                    autos.append(_job(jn, command=jd.get("Command") or "", schedule=ctm_when(jd.get("When") or {}), deps=[e["Event"].rsplit("-OK", 1)[0] for e in ((jd.get("eventsToWaitFor") or {}).get("Events") or [])],
                                      active=f.get("OrderMethod") != "Manual", owner=jd.get("CreatedBy"), host=jd.get("Host") or "", folder=fname, platform="controlm_api", definition=jd))
        return {"kind": "Control-M definitions", "autos": autos, "runs": []}
    return {"kind": None, "autos": [], "runs": []}
