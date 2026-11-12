"""Observability (phase 8): metrics, structured logs and alerts on stuck work.

- `GET /metrics`: Prometheus text for this instance - jobs and queue depth per lane, the running job's age, the
  agent's lanes (busy and since when), the DAX checker (online, queue depth, oldest request), schedules, sessions,
  this month's cost, HTTP requests and errors, per-person workspaces, active alerts. It needs
  `Authorization: Bearer $D2D_METRICS_TOKEN`; without that variable the endpoint does not exist.
- Logs: one JSON line per event on stdout (`{"ts", "level", "instance", "event", ...}`): API writes, errors and slow
  requests (never query strings or bodies), job start / finish, alerts. `docker logs` / any log shipper reads them.
- Watchdog (every minute): rules for a stuck build or chat lane, a stalled queue, the agent or a workspace down, the
  DAX checker's backlog (one checker on one PC serves every build: the first bottleneck as people are added), overdue
  schedules, a burst of server errors. A new alert tells every Admin (in the app, and on the ops webhook when one is
  set); a cleared one says so. Admin > Monitoring shows the live view and the DAX checker's queue history.
"""
import asyncio
import collections
import json
import os
import re
import sys
import time
import traceback

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from genbi_kit import daxcheck

from . import auth, db, instances, notify, pbix, worker

router = APIRouter()

TOKEN = os.environ.get("D2D_METRICS_TOKEN", "")
TICK_S = int(os.environ.get("D2D_WATCH_S", "60"))
SLOW_S = 2.0
DEFAULTS = {"chat_stuck_min": 15, "queue_stalled_min": 5, "queue_deep": 5, "daxcheck_backlog": 3, "daxcheck_wait_min": 10,
            "schedule_late_min": 10, "errors_15min": 10, "build_grace_min": 10,
            "daxcheck_offline_min": 10, "backup_max_h": 36,            # pre-work 0.3 / 0.4 (build-plan v2)
            "pbix_offline_min": 10}                                    # D2D Relay: the Power BI file maker

HTTP: dict[tuple, list] = {}                       # (route, method, status class) -> [count, seconds]
ERRORS: collections.deque = collections.deque(maxlen=500)   # times of 5xx responses
DAXQ: collections.deque = collections.deque(maxlen=24 * 60)  # (time, pending, online) once a minute, last 24 h
STATE = {"agent_fail": 0, "last_tick": None}


# ---------------------------------------------------------------- structured logs

def log(event: str, level: str = "info", **fields) -> None:
    line = {"ts": round(time.time(), 3), "level": level, "instance": db.INSTANCE, "event": event, **fields}
    print(json.dumps(line, default=str), file=sys.stdout, flush=True)


def _route(path: str) -> str:
    """A low-cardinality route label: segments that carry an id (any digit, or a person / team id) become {id}."""
    out = []
    for p in [p for p in path.split("/") if p][:5]:
        out.append("{id}" if re.search(r"\d", p) or re.match(r"^(u|t)-", p) or len(p) > 40 else p)
    return "/" + "/".join(out)


async def middleware(request: Request, call_next):
    started = time.perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    finally:
        path = request.url.path
        secs = time.perf_counter() - started
        if path.startswith(("/api/", "/auth/", "/metrics")):
            key = (_route(path), request.method, f"{status // 100}xx")
            c = HTTP.setdefault(key, [0, 0.0])
            c[0] += 1
            c[1] += secs
            if status >= 500:
                ERRORS.append(time.time())
            if status >= 500 or secs > SLOW_S or request.method not in ("GET", "HEAD"):
                log("http", "error" if status >= 500 else "warn" if secs > SLOW_S else "info", method=request.method,
                    route=_route(path), status=status, ms=round(secs * 1000), user=getattr(request.state, "uid", None))


# ---------------------------------------------------------------- what is going on now

def thresholds() -> dict:
    return {**DEFAULTS, **json.loads(db.meta("ops_thresholds") or "{}")}


def daxcheck_queue() -> dict:
    req = daxcheck.QUEUE / "requests"
    files = [f for f in req.glob("*.json") if not f.name.endswith(".model.json")] if req.exists() else []
    oldest = min((f.stat().st_mtime for f in files), default=None)
    return {"online": bool(daxcheck.available()), "pending": len(files), "oldest_s": round(time.time() - oldest) if oldest else 0}


def pbix_queue() -> dict:
    """D2D Relay's Power BI file maker on the Windows PC: up, its waiting requests, and why it stopped (its own reason)."""
    req = pbix.QUEUE / "requests"
    files = list(req.glob("*.json")) if req.exists() else []
    oldest = min((f.stat().st_mtime for f in files), default=None)
    beat = pbix.heartbeat() or {}
    return {"online": bool(pbix.available()), "pending": len(files), "oldest_s": round(time.time() - oldest) if oldest else 0,
            "error": beat.get("error") if beat.get("state") == "error" else None}


async def _agent() -> dict:
    try:
        async with httpx.AsyncClient(timeout=3) as c:
            return {"ok": True, **(await c.get(f"{worker.AGENT_URL}/health")).json()}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": e.__class__.__name__}


async def _runners() -> dict:
    """The other agent CLIs' services (phase 8), when they run: up, and each lane's busy-since. Probed in parallel
    with a hard limit, so services that are not started (the opt-in profile) never slow the watchdog."""
    async def probe(c, name, url):
        try:
            h = (await asyncio.wait_for(c.get(f"{url}/health"), 2)).json()
            return name, {"ok": True, "lanes": h.get("lanes"), "since": h.get("since")}
        except Exception:  # noqa: BLE001 - not started
            return name, {"ok": False}
    if STATE.get("runners_at") and time.time() - STATE["runners_at"] < 60:     # at most one probe a minute
        return STATE["runners"]
    async with httpx.AsyncClient(timeout=2) as c:
        try:
            pairs = await asyncio.wait_for(asyncio.gather(*(probe(c, n, u) for n, u in worker.RUNNER_URLS.items())), 3)
        except TimeoutError:
            pairs = [(n, {"ok": False}) for n in worker.RUNNER_URLS]
    STATE.update(runners=dict(pairs), runners_at=time.time())
    return STATE["runners"]


async def _workspaces() -> list[dict]:
    if not instances.ENABLED:
        return []
    try:
        listing = await instances.listing()
    except Exception:  # noqa: BLE001
        return []
    out = []
    for i in listing.get("instances", []):
        row = {"user": i.get("user"), "state": i.get("state")}
        if i.get("state") == "running" and i.get("url"):
            try:
                async with httpx.AsyncClient(timeout=3) as c:
                    h = (await c.get(f"{i['url']}/health")).json()
                row.update(healthy=True, lanes=h.get("lanes"), since=h.get("since"))
            except Exception:  # noqa: BLE001
                row["healthy"] = False
        out.append(row)
    return out


async def snapshot() -> dict:
    now = time.time()
    agent = await _agent()
    jobs = {r["state"]: r["n"] for r in db.q("SELECT state, count(*) n FROM jobs GROUP BY state")}
    cur = {k: v for k, v in worker.current.items() if k != "task"}
    sched = {r["status"]: r["n"] for r in db.q("SELECT status, count(*) n FROM schedules GROUP BY status")}
    late = db.one("SELECT count(*) n, MIN(next_run) t FROM schedules WHERE status = 'active' AND next_run < ?",
                  (now - thresholds()["schedule_late_min"] * 60,))
    month = time.gmtime()
    start = time.mktime((month.tm_year, month.tm_mon, 1, 0, 0, 0, 0, 0, 0)) - time.timezone
    cost = {r["kind"]: r["c"] for r in db.q("SELECT kind, COALESCE(SUM(cost_usd), 0) c FROM usage WHERE ts >= ? GROUP BY kind", (start,))}
    return {"time": now, "instance": db.INSTANCE, "agent": agent, "jobs": jobs, "waiting": worker.waiting(),
            "running": {**cur, "age_s": round(now - cur["started"]) if cur.get("started") else None},
            "daxcheck": daxcheck_queue(), "pbix": pbix_queue(), "schedules": sched, "schedules_late": late["n"],
            "sessions": db.one("SELECT count(*) n FROM sessions WHERE expires > ?", (now,))["n"],
            "cost_month": cost, "errors_15min": sum(1 for t in ERRORS if t > now - 900),
            "workspaces": await _workspaces(), "runners": await _runners(), "alerts": active(), "last_tick": STATE["last_tick"],
            "database": db.BACKEND, "last_backup": json.loads(db.meta("last_backup") or "{}").get("started")}


def metrics_text(s: dict) -> str:
    out = ["# TYPE d2d_up gauge", "d2d_up 1", f'd2d_instance_info{{instance="{s["instance"]}"}} 1', "# TYPE d2d_jobs gauge"]
    out += [f'd2d_jobs{{state="{k}"}} {v}' for k, v in sorted(s["jobs"].items())]
    out += [f'd2d_queue_waiting{{lane="build"}} {s["waiting"]}',
            f'd2d_job_running_seconds{{kind="{s["running"].get("kind") or ""}"}} {s["running"]["age_s"] or 0}']
    a = s["agent"]
    out.append(f"d2d_agent_up {int(bool(a.get('ok')))}")
    for lane, busy in (a.get("lanes") or {}).items():
        since = (a.get("since") or {}).get(lane)
        out += [f'd2d_agent_lane_busy{{lane="{lane}"}} {int(busy)}', f'd2d_agent_lane_busy_seconds{{lane="{lane}"}} {round(s["time"] - since) if since else 0}']
    d = s["daxcheck"]
    out += [f"d2d_daxcheck_up {int(d['online'])}", f"d2d_daxcheck_queue_pending {d['pending']}", f"d2d_daxcheck_queue_oldest_seconds {d['oldest_s']}"]
    m = s["pbix"]
    out += [f"d2d_pbix_up {int(m['online'])}", f"d2d_pbix_queue_pending {m['pending']}", f"d2d_pbix_queue_oldest_seconds {m['oldest_s']}"]
    out += [f'd2d_schedules{{status="{k}"}} {v}' for k, v in sorted(s["schedules"].items())] + [f"d2d_schedules_late {s['schedules_late']}"]
    out += [f"d2d_sessions_active {s['sessions']}"] + [f'd2d_cost_month_usd{{kind="{k}"}} {v:.4f}' for k, v in sorted(s["cost_month"].items())]
    out += ["# TYPE d2d_http_requests_total counter", "# TYPE d2d_http_request_seconds_total counter"]
    for (route, method, cls), (n, secs) in sorted(HTTP.items()):
        lab = f'route="{route}",method="{method}",status="{cls}"'
        out += [f"d2d_http_requests_total{{{lab}}} {n}", f"d2d_http_request_seconds_total{{{lab}}} {secs:.3f}"]
    for w in s["workspaces"]:
        out.append(f'd2d_workspace_up{{user="{w["user"]}",state="{w["state"]}"}} {int(bool(w.get("healthy")))}')
    out += [f'd2d_runner_up{{runner="{k}"}} {int(v["ok"])}' for k, v in sorted(s.get("runners", {}).items())]
    out.append(f'd2d_database_info{{backend="{s.get("database", "sqlite")}"}} 1')
    out.append(f"d2d_backup_age_seconds {round(s['time'] - s['last_backup']) if s.get('last_backup') else -1}")
    out.append(f"d2d_alerts_active {len(s['alerts'])}")
    out += [f'd2d_alert{{rule="{x["rule"]}",severity="{x["severity"]}"}} 1' for x in s["alerts"]]
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- rules and alerts

def rules(s: dict) -> dict[str, dict]:
    """rule -> {severity, text} for every problem seen now."""
    t, now, found = thresholds(), s["time"], {}
    a = s["agent"]
    if not a.get("ok"):
        STATE["agent_fail"] += 1
        if STATE["agent_fail"] >= 2:
            found["agent_down"] = {"severity": "critical", "text": "The AI agent service does not answer; builds and Ask D are stopped."}
    else:
        STATE["agent_fail"] = 0
    run = s["running"]
    if run.get("kind") and run.get("age_s") is not None:
        limit = worker.TIMEOUT_S.get(run["kind"], 3600) + t["build_grace_min"] * 60
        if run["age_s"] > limit:
            found["build_stuck"] = {"severity": "critical", "text": f"A {run['kind']} job on {run.get('pid')} has run {run['age_s'] // 60} min, past its "
                                    f"{limit // 60}-minute limit; nothing else can build until it ends. Stop it on the dashboard."}
    since = (a.get("since") or {})
    if since.get("build") and not run.get("kind") and now - since["build"] > 600:
        found["build_orphan"] = {"severity": "warning", "text": f"The agent's build lane has been busy {round((now - since['build']) / 60)} min with no job "
                                 "in the app (a run left behind by a restart?)."}
    if since.get("chat") and now - since["chat"] > t["chat_stuck_min"] * 60:
        found["chat_stuck"] = {"severity": "warning", "text": f"Ask D's lane has been busy {round((now - since['chat']) / 60)} min; new questions wait."}
    if s["waiting"] and not run.get("kind"):
        STATE.setdefault("idle_since", now)
        if now - STATE["idle_since"] > t["queue_stalled_min"] * 60:
            found["queue_stalled"] = {"severity": "critical", "text": f"{s['waiting']} job(s) are waiting but nothing has started for "
                                      f"{round((now - STATE['idle_since']) / 60)} min."}
    else:
        STATE.pop("idle_since", None)
    if s["waiting"] >= t["queue_deep"]:
        found["queue_deep"] = {"severity": "warning", "text": f"{s['waiting']} builds are waiting for the one build lane."}
    d = s["daxcheck"]
    if d["pending"] and not d["online"]:
        found["daxcheck_down"] = {"severity": "critical", "text": f"{d['pending']} DAX check(s) are waiting and the DAX checker on the Windows PC is "
                                  "not running (start daxcheck\\start-daxcheck.cmd)."}
    elif d["pending"] >= t["daxcheck_backlog"] or d["oldest_s"] > t["daxcheck_wait_min"] * 60:
        found["daxcheck_backlog"] = {"severity": "warning", "text": f"The DAX checker has {d['pending']} request(s) waiting, the oldest "
                                     f"{d['oldest_s'] // 60} min: it is becoming the bottleneck (plan: a checker on a server)."}
    if not d["online"]:                                   # offline with an empty queue still blocks every approval
        STATE.setdefault("dax_off_since", now)
        if not d["pending"] and now - STATE["dax_off_since"] > t["daxcheck_offline_min"] * 60:
            found["daxcheck_offline"] = {"severity": "warning", "text": f"The DAX checker on the Windows PC has been offline for "
                                         f"{round((now - STATE['dax_off_since']) / 60)} min: nothing can be approved or published until "
                                         "daxcheck\\start-daxcheck.cmd runs."}
    else:
        STATE.pop("dax_off_since", None)
    m = s["pbix"]                                         # D2D Relay: every publish ends with the Power BI file maker
    if not m["online"]:
        STATE.setdefault("pbix_off_since", now)
        why = f" It stopped: {m['error']}" if m.get("error") else ""
        if m["pending"]:
            found["pbix_down"] = {"severity": "critical", "text": f"{m['pending']} Power BI file(s) are waiting and the Power BI file maker on "
                                  f"the Windows PC is not running (start pbix\\start-pbix.cmd).{why}"}
        elif now - STATE["pbix_off_since"] > t["pbix_offline_min"] * 60:
            found["pbix_offline"] = {"severity": "warning", "text": f"The Power BI file maker on the Windows PC has been offline for "
                                     f"{round((now - STATE['pbix_off_since']) / 60)} min: nothing can be published until "
                                     f"pbix\\start-pbix.cmd runs.{why}"}
    else:
        STATE.pop("pbix_off_since", None)
    lb = s.get("last_backup")
    if lb and now - lb > t["backup_max_h"] * 3600:
        found["backup_old"] = {"severity": "warning", "text": f"The last backup was {round((now - lb) / 3600)} h ago (the nightly one runs at "
                               f"{os.environ.get('D2D_BACKUP_HOUR_UTC', '21')}:00 UTC when the app is up). Run Admin > Operations > Back up now."}
    if s["schedules_late"]:
        found["schedules_late"] = {"severity": "warning", "text": f"{s['schedules_late']} schedule(s) are more than {t['schedule_late_min']} min overdue."}
    if s["errors_15min"] >= t["errors_15min"]:
        found["errors"] = {"severity": "warning", "text": f"{s['errors_15min']} server errors in the last 15 minutes (see the logs)."}
    for w in s["workspaces"]:
        if w["state"] == "running" and w.get("healthy") is False:
            found[f"workspace_down:{w['user']}"] = {"severity": "warning", "text": f"The workspace of {w['user']} is running but does not answer."}
    try:
        from . import doctor                               # Relay Doctor stopped, or problems it could not fix by itself
        found.update(doctor.rules(now))
    except Exception:  # noqa: BLE001 - the Doctor's files must never stop the other checks
        traceback.print_exc()
    return found


def active() -> list[dict]:
    return sorted(json.loads(db.meta("ops_alerts") or "{}").values(), key=lambda x: x["since"])


def _admins() -> list[str]:
    return [r["id"] for r in db.q("SELECT id FROM users WHERE org_role = 'admin' AND active = 1")]


def _webhook(text: str) -> None:
    hook = json.loads(db.meta("ops_webhook") or "{}")
    if not hook.get("url"):
        return
    try:
        body = {"text": text} if hook.get("kind") == "slack" else {"type": "message", "text": text}
        httpx.post(hook["url"], json=body, timeout=10)
    except httpx.HTTPError as e:
        log("ops.webhook_failed", "warn", error=str(e)[:200])


def workspace_rules(s: dict) -> dict[str, dict]:
    """What a workspace's own admins need to know (P17: one pass per workspace, the platform's checks stay above):
    its overdue schedules, its AI budget at the limit, work items stopped on an error for more than an hour."""
    t, now, found = thresholds(), s["time"], {}
    late = db.one("SELECT count(*) n FROM schedules WHERE status = 'active' AND next_run < ?", (now - t["schedule_late_min"] * 60,))["n"]
    if late:
        found["schedules_late"] = {"severity": "warning", "text": f"{late} of this workspace's schedule(s) are more than {t['schedule_late_min']} min overdue."}
    try:
        from . import usage
        q = next((x for x in usage.status("system") if x["scope"] == "workspace"), None)
        if q and q["level"] == "stop":
            found["budget_stop"] = {"severity": "critical", "text": f"This workspace's AI budget for {q['month']} is used up (${q['spent_usd']:.2f} of ${q['monthly_usd']:.2f}): "
                                    "new builds and questions wait until an Admin raises it."}
        elif q and q["level"] == "warn":
            found["budget_warn"] = {"severity": "warning", "text": f"This workspace's AI budget is {q['spent_usd'] / max(q['monthly_usd'], 1e-9):.0%} used in {q['month']}."}
    except Exception:  # noqa: BLE001 - no usage tables yet in a brand-new workspace
        pass
    if "wb_items" in db.tables():
        n = db.one("SELECT count(*) n FROM wb_items WHERE status = 'error' AND updated < ?", (now - 3600,))["n"]
        if n:
            found["work_errors"] = {"severity": "warning", "text": f"{n} work item(s) have been stopped on an error for more than an hour (Run again on each, or close it)."}
    return found


def evaluate(s: dict, rule_fn=None) -> dict:
    """Compare what is wrong now with what was already reported; tell Admins about the changes."""
    now = (rule_fn or rules)(s)
    was = json.loads(db.meta("ops_alerts") or "{}")
    keep = {}
    for rule, a in now.items():
        keep[rule] = {**a, "rule": rule, "since": was.get(rule, {}).get("since") or s["time"]}
        if rule not in was:
            log("ops.alert", "error" if a["severity"] == "critical" else "warn", rule=rule, text=a["text"])
            db.audit("ops.alert", rule, {"severity": a["severity"], "text": a["text"]}, "system")
            notify.add_many(_admins(), "ops", f"{'Problem' if a['severity'] == 'critical' else 'Warning'}: {a['text'][:120]}", a["text"], "#/admin/monitoring")
            _webhook(f"D2D ({db.INSTANCE}) {a['severity']}: {a['text']}")
    for rule, a in was.items():
        if rule not in now:
            mins = round((s["time"] - a["since"]) / 60)
            log("ops.resolved", rule=rule, minutes=mins)
            db.audit("ops.resolved", rule, {"minutes": mins}, "system")
            notify.add_many(_admins(), "ops", f"Resolved after {mins} min: {a['text'][:110]}", "", "#/admin/monitoring")
            _webhook(f"D2D ({db.INSTANCE}) resolved after {mins} min: {a['text']}")
    db.set_meta("ops_alerts", json.dumps(keep))
    return keep


def _sample(s: dict) -> None:
    d = s["daxcheck"]
    DAXQ.append((round(s["time"]), d["pending"], d["online"]))
    day = time.strftime("%Y-%m-%d", time.gmtime(s["time"]))
    peaks = json.loads(db.meta("daxcheck_peaks") or "{}")
    p = peaks.setdefault(day, {"max_pending": 0, "max_wait_s": 0, "offline_min": 0})
    p["max_pending"] = max(p["max_pending"], d["pending"])
    p["max_wait_s"] = max(p["max_wait_s"], d["oldest_s"])
    p["offline_min"] += 0 if d["online"] else round(TICK_S / 60, 2)
    db.set_meta("daxcheck_peaks", json.dumps(dict(sorted(peaks.items())[-30:])))


async def tick() -> dict:
    s = await snapshot()
    _sample(s)
    alerts = evaluate(s)
    STATE["last_tick"] = s["time"]
    for t in db.each_tenant():                       # P17: each other workspace's own checks, to its own admins
        if t == db.PLATFORM:
            continue
        try:
            evaluate({"time": s["time"]}, workspace_rules)
        except Exception:  # noqa: BLE001 - one workspace must not stop the others' checks
            traceback.print_exc()
    return alerts


async def watchdog() -> None:
    while True:
        await asyncio.sleep(TICK_S)
        try:
            await tick()
        except Exception:  # noqa: BLE001
            traceback.print_exc()


# ---------------------------------------------------------------- endpoints

@router.get("/metrics", response_class=PlainTextResponse)
async def prometheus(request: Request):
    if not TOKEN:
        raise HTTPException(404, "Not Found")
    if request.headers.get("authorization") != f"Bearer {TOKEN}":
        raise HTTPException(401, "Bearer token required")
    return metrics_text(await snapshot())


@router.get("/api/admin/monitoring")
async def admin_monitoring():
    from . import doctor
    s = await snapshot()
    return {**{k: v for k, v in s.items()}, "thresholds": thresholds(), "metrics_endpoint": bool(TOKEN), "doctor": doctor.brief(),
            "webhook": {k: v for k, v in json.loads(db.meta("ops_webhook") or "{}").items() if k != "url"} | {"set": bool(json.loads(db.meta("ops_webhook") or "{}").get("url"))},
            "daxcheck_history": [{"t": t, "pending": p, "online": o} for t, p, o in DAXQ],
            "daxcheck_days": json.loads(db.meta("daxcheck_peaks") or "{}"),
            "history": db.audit_log(50, "ops.alert") + db.audit_log(50, "ops.resolved"),
            "http": [{"route": r, "method": m, "status": c, "count": n, "avg_ms": round(1000 * secs / n)} for (r, m, c), (n, secs) in sorted(HTTP.items(), key=lambda kv: -kv[1][0])][:40]}


class OpsSettings(BaseModel):
    thresholds: dict = {}
    webhook_url: str | None = None
    webhook_kind: str = "slack"


@router.put("/api/admin/monitoring")
async def admin_set_monitoring(body: OpsSettings):
    t = {k: v for k, v in body.thresholds.items() if k in DEFAULTS}
    if any(not isinstance(v, (int, float)) or v <= 0 for v in t.values()):
        raise HTTPException(400, "Thresholds must be positive numbers.")
    db.set_meta("ops_thresholds", json.dumps(t))
    if body.webhook_url is not None:
        from . import publishing
        if body.webhook_url and (body.webhook_kind not in ("slack", "teams") or not publishing._webhook_ok(body.webhook_url)):   # noqa: SLF001
            raise HTTPException(400, "Use a Slack or Microsoft Teams incoming webhook URL.")
        db.set_meta("ops_webhook", json.dumps({"url": body.webhook_url, "kind": body.webhook_kind} if body.webhook_url else {}))
    db.audit("ops.settings", None, {"thresholds": t, "webhook": bool(body.webhook_url)}, auth.who())
    return await admin_monitoring()


@router.post("/api/admin/monitoring/check")
async def admin_check_now():
    await tick()
    return await admin_monitoring()
