"""Home: the platform's insight dashboard on real records (build-plan v2, P9). Every number comes from what the app
already keeps - project runs (agent time, cost, outcome), versions and their review gates, publishes, Ask Relay
questions, schedules, the job queue and the agent's lanes. Nothing is estimated; where a measure needs data the
platform does not record yet (people's time, checkpoints - P10), it is left out rather than invented.
"""
from __future__ import annotations

import json
import statistics
import time
import traceback

from fastapi import APIRouter

from . import agents, auth, db, registry, store, worker

router = APIRouter()

PERIODS = {"7d": 7 * 86400, "30d": 30 * 86400, "6m": 183 * 86400}
LLM_STAGES = {"plan", "build", "revise", "data", "fix"}
WAITING = {"awaiting_kpis": "Confirm the KPIs", "awaiting_review": "Review the prototype"}
RUNNING = {"queued", "extracting", "generating_data", "planning", "building", "revising", "building_pbi"}
# Module workbench: modules add their rows to "Work in flight" - fn(u) -> [{"id", "name", "n", "running", "route"}].
INFLIGHT: list = []


def _month_keys(n: int = 6) -> list[tuple[str, float, float]]:
    """(label, start, end) for the last n calendar months, oldest first (UTC)."""
    t = time.gmtime()
    y, m = t.tm_year, t.tm_mon
    out = []
    for _ in range(n):
        start = time.mktime((y, m, 1, 0, 0, 0, 0, 0, 0)) - time.timezone
        m2, y2 = (m + 1, y) if m < 12 else (1, y + 1)
        end = time.mktime((y2, m2, 1, 0, 0, 0, 0, 0, 0)) - time.timezone
        out.append((time.strftime("%b", time.gmtime(start + 86400)), start, end))
        m, y = (m - 1, y) if m > 1 else (12, y - 1)
    return list(reversed(out))


def is_fix(run: dict) -> bool:
    """A fix round: the agent resumed to repair what a gate rejected (worker.agent records it), or an older run whose
    stage was 'fix'."""
    return run.get("stage") == "fix" or bool(run.get("fix"))


def _visible_projects(u: dict | None) -> list[dict]:
    ps = [p for p in store.all_projects() if p.get("kind", "dashboard") == "dashboard"]     # starts (P10) are not dashboards
    if u is None:
        return ps
    access = auth.access_map(u, [p["id"] for p in ps])
    return [p for p in ps if p["id"] in access]


def build(u: dict | None, period: str = "30d") -> dict:
    now = time.time()
    span = PERIODS.get(period, PERIODS["30d"])
    since = now - span
    b = registry.brand()
    projects = _visible_projects(u)
    states = {p["id"]: store.load(p["id"]) for p in projects}

    runs, versions, publishes, waiting, inflight = [], [], [], [], []
    for p in projects:
        st = states[p["id"]]
        for r in st.get("runs") or []:
            if r.get("ended"):
                runs.append({**r, "pid": p["id"], "name": p["name"]})
        for v in st.get("versions") or []:
            versions.append({**{k: v.get(k) for k in ("v", "created", "feedback")}, "gates": v.get("gates") or [], "pid": p["id"], "name": p["name"]})
        pubs = st.get("publishes") or ([{"v": st.get("approved"), "when": st.get("finished")}] if st.get("output") and st.get("approved") else [])
        for pb in pubs:
            if pb.get("when"):
                gates = next((v.get("gates") or [] for v in (st.get("versions") or []) if v.get("v") == pb.get("v")), [])
                publishes.append({"pid": p["id"], "name": p["name"], "v": pb.get("v"), "when": pb["when"],
                                  "checks": sum(1 for g in gates if g.get("status") in ("pass", "warn")), "gates": len(gates)})
        if p["status"] in WAITING:
            waiting.append({"pid": p["id"], "name": p["name"], "what": WAITING[p["status"]], "since": st.get("updated") or st.get("created") or now, "module": "D2D"})
        if p["status"] in RUNNING:
            inflight.append(p)

    in_period = [r for r in runs if r["ended"] >= since]
    agent_hours = sum((r.get("duration_ms") or 0) for r in in_period if r.get("stage") in LLM_STAGES) / 3.6e6
    prev = [r for r in runs if since - span <= r["ended"] < since]
    agent_hours_prev = sum((r.get("duration_ms") or 0) for r in prev if r.get("stage") in LLM_STAGES) / 3.6e6
    work = [r for r in in_period if r.get("stage") in ("build", "revise", "data", "plan") and not is_fix(r)]
    fixes = [r for r in in_period if is_fix(r)]
    rft = None if not work else max(0.0, min(100.0, 100.0 * (1 - len(fixes) / len(work))))
    work_prev = [r for r in prev if r.get("stage") in ("build", "revise", "data", "plan") and not is_fix(r)]
    rft_prev = None if not work_prev else max(0.0, min(100.0, 100.0 * (1 - sum(1 for r in prev if is_fix(r)) / len(work_prev))))
    cost_runs = sum((r.get("cost_usd") or 0) for r in in_period)
    cost_other = db.one("SELECT COALESCE(SUM(cost_usd), 0) AS c FROM usage WHERE ts >= ? AND NOT (kind = 'llm' AND step IN ('plan', 'build', 'revise', 'data', 'fix'))", (since,))["c"]
    ai_cost = round(cost_runs + cost_other, 2)
    delivered = [pb for pb in publishes if pb["when"] >= since]
    questions = db.one("SELECT COUNT(*) AS n FROM audit WHERE action = 'askd.question' AND ts >= ?", (since,))["n"]
    sched = {r["status"]: r["n"] for r in db.q("SELECT status, count(*) n FROM schedules GROUP BY status")}
    try:
        from . import publishing
        for r in publishing.my_reviews(u["id"]) if u else []:
            waiting.append({"pid": r["project"], "name": r["name"], "what": f"Review v{r.get('v')} for publishing", "since": r.get("requested") or now, "module": "D2D"})
    except Exception:  # noqa: BLE001 - reviews are optional on Home
        pass
    waiting.sort(key=lambda w: w["since"])
    ages = [(now - w["since"]) / 3600 for w in waiting]

    months = []
    for label, start, end in _month_keys():
        rs = [r for r in runs if start <= r["ended"] < end]
        w = [r for r in rs if r.get("stage") in ("build", "revise", "data", "plan") and not is_fix(r)]
        f = [r for r in rs if is_fix(r)]
        months.append({"month": label, "hours": round(sum((r.get("duration_ms") or 0) for r in rs if r.get("stage") in LLM_STAGES) / 3.6e6, 1),
                       "cost_usd": round(sum((r.get("cost_usd") or 0) for r in rs), 2),
                       "rft": None if not w else round(100 * (1 - len(f) / len(w)), 1),
                       "delivered": sum(1 for pb in publishes if start <= pb["when"] < end)})

    rate, fx = float(b.get("hourly_rate") or 0), 1.0
    try:
        fx = float(json.loads(db.meta("branding") or "{}").get("usd_rate") or 1)
    except (ValueError, TypeError):
        fx = 1.0
    net = round(agent_hours * rate - ai_cost * fx, 0) if rate else None

    cur = {k: v for k, v in worker.current.items() if k != "task"}
    running = None
    if cur.get("kind"):                    # any module's job: the agent's name, what it is doing, and the folder only for people who may open it
        try:
            st_run = store.load(cur["pid"]) if cur.get("pid") else {}
        except (KeyError, FileNotFoundError, ValueError):
            st_run = {}
        here = agents.place(cur.get("pid"), st_run)
        mine = u is None or here["shared"] or auth.is_admin(u) or bool(cur.get("pid") and auth.access_map(u, [cur["pid"]]))
        running = {**cur, "agent": here.get("agent") or agents.name(cur["kind"]), "doing": here.get("doing") or agents.doing(cur["kind"]), "module": here["module"],
                   "name": here["name"] if mine else None, "link": here["link"] if mine else None,
                   "age_s": round(now - cur["started"]) if cur.get("started") else None}
    recent = sorted(publishes, key=lambda pb: -pb["when"])[:5]
    by_status = {"running": len(inflight), "waiting": len([p for p in projects if p["status"] in WAITING]),
                 "published": len([p for p in projects if p.get("published")]), "attention": len([p for p in projects if p["status"] == "error"])}
    more = []
    for fn in INFLIGHT:
        try:
            more += fn(u) or []
        except Exception:  # noqa: BLE001 - a module's rows never break Home
            traceback.print_exc()
    return {
        "period": period, "since": since, "brand": {k: b[k] for k in ("name", "full", "partner", "currency", "hourly_rate")},
        "kpis": {
            "agent_hours": round(agent_hours, 1), "agent_hours_prev": round(agent_hours_prev, 1),
            "rft": None if rft is None else round(rft, 1), "rft_prev": None if rft_prev is None else round(rft_prev, 1),
            "delivered": len(delivered), "waiting": len(waiting), "waiting_oldest_h": round(max(ages), 1) if ages else 0,
            "waiting_median_h": round(statistics.median(ages), 1) if ages else 0,
            "ai_cost_usd": ai_cost, "net_value": net, "questions": questions, "runs": len(in_period), "fix_rounds": len(fixes)},
        "months": months,
        "waiting": waiting[:8],
        "inflight": {"by_status": by_status, "modules": [
            {"id": "bi", "name": "BI & dashboards", "n": len(projects), "running": len(inflight), "route": "#/d2d"},
            {"id": "askd", "name": "Conversational analytics", "n": questions, "unit": "questions", "route": "#/askd"},
            {"id": "schedule", "name": "Reports & alerts", "n": sum(sched.values()), "paused": sched.get("paused", 0), "route": "#/schedules"}, *more]},
        "now": {"running": running, "queue": worker.waiting()},
        "recent": recent,
    }


@router.get("/api/home")
def get_home(period: str = "30d"):
    return build(auth.current.get(), period if period in PERIODS else "30d")
