"""Team & agents (build-plan v2, P10): who - person or agent - is on what right now, what is waiting for a person,
where the time goes, how good the agents' work is, and the hours and FTE saved against the AI cost. Every number
comes from records the platform keeps: project runs (agent, model, provider, stage, duration, cost, outcome),
checkpoints (decided, accepted, sent back, seconds, by whom), usage rows and the job queue - nothing is estimated
beyond the hourly rate the admin sets under Admin > Branding. Viewers do not see this page.
"""
from __future__ import annotations

import json
import statistics
import time

from fastapi import APIRouter, HTTPException

from . import agents, auth, checkpoints, db, home, registry, store, worker

router = APIRouter()

PERIODS = home.PERIODS
AGENTS = agents.NAMES                  # job kind / run stage -> the agent's name: agents.py's dict, so a module's additions (the workbench's packs) name runs everywhere
STAGE_TEXT = {k: v[2] for k, v in agents.AGENTS.items()}
MODULE_OF = {"start": "Start", "dashboard": "D2D"}
# Subject folders that are not dashboards or starts say how this page names and links them (module workbench):
# kind -> fn(pid) -> {"module", "link", "agent"?, "doing"?}. The same dict as agents.SUBJECTS, so Home, the
# notifications and this page all link a work item to its own screen.
SUBJECTS: dict = agents.SUBJECTS


def subject(pid: str | None, kind: str | None) -> dict:
    fn = SUBJECTS.get(kind or "")
    if fn and pid:
        try:
            return {"module": MODULE_OF.get(kind, kind), "link": f"#/p/{pid}", **(fn(pid) or {})}
        except Exception:  # noqa: BLE001 - a module's naming never breaks the page
            pass
    return {"module": MODULE_OF.get(kind, "D2D"), "link": ("#/start/" if kind == "start" else "#/p/") + str(pid)}


def llm_stages() -> set[str]:
    """The stages whose run time is agent work: every AI job kind a module registered, plus the run stages inside
    them (a fix round, a conversion, the optional triage pass)."""
    return set(worker.LLM_KINDS) | {"fix", "convert", "triage"}


def work_stages() -> set[str]:
    return llm_stages() - {"fix"}


def is_agent_run(r: dict, llm: set | None = None) -> bool:
    """Agent work: an AI job kind, or a workbench step's run (stage "<module>.<step>" - an agent step, or rules and
    platform reads recorded with model "rules"), whichever module registered it."""
    st = str(r.get("stage") or "")
    return st in (llm if llm is not None else llm_stages()) or ("." in st and st.split(".", 1)[0] in _modules()) or r.get("model") == "rules"


def _modules() -> set[str]:
    from . import workbench
    return set(workbench.PACKS)


def _place(pid: str | None, u: dict, names: dict) -> dict:
    """The running job's folder as this person may see it: its name and link only when they can open it."""
    try:
        st = store.load(pid) if pid else {}
    except (KeyError, FileNotFoundError, ValueError):
        st = {}
    p = agents.place(pid, st)
    if not (pid in names or p["shared"] or auth.is_admin(u)):
        p.update(name=None, link=None)
    return p


def _visible(u: dict) -> list[dict]:
    ps = store.all_projects()
    access = auth.access_map(u, [p["id"] for p in ps])
    return [p for p in ps if p["id"] in access]


def _people(u: dict) -> list[dict]:
    rows = db.q("SELECT u.id, u.name, u.email, u.org_role, m.team_id, m.role FROM users u LEFT JOIN memberships m ON m.user_id = u.id "
                "WHERE u.active = 1 ORDER BY lower(u.name)")
    mine = {t["id"] for t in u.get("teams") or []}
    people: dict[str, dict] = {}
    for r in rows:
        p = people.setdefault(r["id"], {"id": r["id"], "name": r["name"], "email": r["email"], "admin": r["org_role"] == "admin", "teams": set(), "builder": False})
        if r["team_id"]:
            p["teams"].add(r["team_id"])
            p["builder"] |= r["role"] == "dev"
    out = []
    for p in people.values():
        if auth.is_admin(u) or p["id"] == u["id"] or p["teams"] & mine:
            p["role"] = "Lead / admin" if p["admin"] else "Builder" if p["builder"] else "Viewer"
            p["teams"] = sorted(p["teams"])
            out.append(p)
    return out


def _cps(u: dict, since: float) -> tuple[list[dict], list[dict]]:
    """Decided checkpoints in the period and the open ones, as this person may see them."""
    decided = [checkpoints._public(r) for r in db.q("SELECT * FROM checkpoints WHERE decided >= ? AND status IN ('accepted', 'sent_back')", (since,))]
    open_ = [checkpoints._public(r) for r in db.q("SELECT * FROM checkpoints WHERE status = 'open' ORDER BY created")]
    if not auth.is_admin(u):
        teams = {t["id"] for t in u.get("teams") or []}
        vis = lambda c: c.get("decided_by") == u["id"] or c.get("assignee_id") == u["id"] or c.get("team_id") in teams or c.get("opened_by") == u["id"]  # noqa: E731
        decided = [c for c in decided if vis(c)]
        open_ = [c for c in open_ if checkpoints.visible(u, c)]
    return decided, open_


def build(u: dict, period: str = "30d") -> dict:
    now = time.time()
    span = PERIODS.get(period, PERIODS["30d"])
    since = now - span
    b = registry.brand()
    projects = _visible(u)
    names = {p["id"]: p["name"] for p in projects}
    runs = []
    for p in projects:
        try:
            st = store.load(p["id"])
        except (KeyError, FileNotFoundError, ValueError):
            continue
        for r in st.get("runs") or []:
            if r.get("ended"):
                runs.append({**r, "pid": p["id"], "name": p["name"], "module": agents.place(p["id"], st)["module"]})
    in_period = [r for r in runs if r["ended"] >= since]
    decided, open_ = _cps(u, since)
    people = _people(u)
    user_names = {x["id"]: x["name"] for x in db.q("SELECT id, name FROM users")}

    # ---- agents: one row per agent role (the stage names a role), quality from the checkpoints it opened
    roles: dict[str, dict] = {}
    for r in in_period:
        a = roles.setdefault(agents.name(r.get("stage")), {"agent": agents.name(r.get("stage")), "does": agents.does(r.get("stage")), "runs": 0, "ok": 0, "hours": 0.0,
                                                          "cost_usd": 0.0, "models": set(), "providers": set(), "fix_rounds": 0, "stages": set()})
        a["runs"] += 1
        a["ok"] += 1 if r.get("ok") is not False else 0
        a["hours"] += (r.get("duration_ms") or 0) / 3.6e6
        a["cost_usd"] += r.get("cost_usd") or 0
        a["fix_rounds"] += 1 if home.is_fix(r) else 0
        a["stages"].add(r.get("stage") or "")
        if r.get("model"):
            a["models"].add(r["model"])
        if r.get("provider"):
            a["providers"].add(r["provider"])
    by_agent_cp: dict[str, dict] = {}
    for c in decided:
        g = by_agent_cp.setdefault(c.get("agent") or "Relay", {"accepted": 0, "sent_back": 0})
        g["accepted" if c["status"] == "accepted" else "sent_back"] += 1
    agent_rows = []
    for a in roles.values():
        q = next((v for k, v in by_agent_cp.items() if a["agent"].lower() in k.lower() or k.lower() in a["agent"].lower()), {"accepted": 0, "sent_back": 0})
        agent_rows.append({**a, "hours": round(a["hours"], 2), "cost_usd": round(a["cost_usd"], 2), "models": sorted(a["models"]), "providers": sorted(a["providers"]),
                           "stages": sorted(a["stages"]), "ok_pct": round(100 * a["ok"] / a["runs"], 1) if a["runs"] else None, **q})
    agent_rows.sort(key=lambda a: -a["hours"])

    # ---- people: decisions, time to decide, what they hold now
    by_person: dict[str, dict] = {p["id"]: {**p, "decided": 0, "accepted": 0, "sent_back": 0, "seconds": [], "open": 0, "oldest_open": None,
                                             "runs": 0, "cost_usd": 0.0, "on": None, "on_status": "idle", "on_since": None, "on_link": None} for p in people}
    for c in decided:
        p = by_person.get(c.get("decided_by"))
        if p:
            p["decided"] += 1
            p["accepted" if c["status"] == "accepted" else "sent_back"] += 1
            if c.get("seconds") is not None:
                p["seconds"].append(c["seconds"])
    for c in open_:
        p = by_person.get(c.get("assignee_id"))
        if p:
            p["open"] += 1
            if p["oldest_open"] is None or c["created"] < p["oldest_open"]:
                p["oldest_open"] = c["created"]
                p.update(on=f"Validating: {c['name']}", on_status="validating", on_since=c["created"], on_link=c.get("link") or "#/validate", on_module=c.get("module"))
    for r in in_period:
        p = by_person.get(r.get("owner"))
        if p:
            p["runs"] += 1
            p["cost_usd"] += r.get("cost_usd") or 0
    cur = {k: v for k, v in worker.current.items() if k != "task"}
    here = _place(cur.get("pid"), u, names) if cur.get("kind") else None      # a work item's folder names itself (SUBJECTS, the workbench)
    if here and cur.get("owner") in by_person and by_person[cur["owner"]]["on"] is None:
        by_person[cur["owner"]].update(on=f"Waiting for Relay: {here['name'] or here['module']}", on_status="waiting", on_since=cur.get("started"),
                                       on_link=here["link"], on_module=here["module"])
    last_by: dict[str, dict] = {}
    for c in sorted(decided, key=lambda c: c.get("decided") or 0):
        last_by[c.get("decided_by")] = c
    for uid, c in last_by.items():
        p = by_person.get(uid)
        if p and p["on"] is None:
            p.update(on=f"Decided: {c['name']}", on_status="done", on_since=c.get("decided"), on_link=c.get("link") or "#/validate", on_module=c.get("module"))
    person_rows = [{**{k: v for k, v in p.items() if k != "seconds"}, "median_seconds": round(statistics.median(p["seconds"]), 1) if p["seconds"] else None,
                    "hours_deciding": round(sum(p["seconds"]) / 3600, 2), "cost_usd": round(p["cost_usd"], 2)} for p in by_person.values()]
    person_rows.sort(key=lambda p: (-p["open"], -p["decided"], p["name"].lower()))

    # ---- now: who is on what
    now_rows = []
    if here:
        role = here.get("agent") or agents.name(cur["kind"])                  # a workbench step names its own agent and what it is doing
        doing = here.get("doing") or agents.doing(cur["kind"])
        doing = doing[:1].upper() + doing[1:]
        now_rows.append({"who": f"Agent - {role}", "kind": "agent", "role": role, "does": agents.does(cur["kind"]),
                         "on": f"{doing}: {here['name']}" if here["name"] else f"{doing} for someone else",
                         "module": here["module"], "status": "working", "since": cur.get("started"), "link": here["link"], "model": cur.get("model")})
    for p in person_rows:
        if p["on"]:
            now_rows.append({"who": p["name"], "kind": "person", "role": p["role"], "on": p["on"], "module": p.get("on_module") or "", "status": p["on_status"],
                             "since": p["on_since"], "link": p["on_link"]})
    queued = worker.waiting()

    # ---- where time goes, quality, value
    llm, work_kinds = llm_stages(), work_stages()
    agent_hours = sum((r.get("duration_ms") or 0) for r in in_period if is_agent_run(r, llm)) / 3.6e6
    people_hours = sum((c.get("seconds") or 0) for c in decided) / 3600
    acc = sum(1 for c in decided if c["status"] == "accepted")
    work = [r for r in in_period if r.get("stage") in work_kinds and not home.is_fix(r)]
    fixes = [r for r in in_period if home.is_fix(r)]
    cost_runs = sum((r.get("cost_usd") or 0) for r in in_period)
    # the cost rows mirrored from agent runs (source run:...) are already in cost_runs, whatever module ran them
    cost_other = db.one("SELECT COALESCE(SUM(cost_usd), 0) AS c FROM usage WHERE ts >= ? AND NOT (kind = 'llm' AND COALESCE(source, '') LIKE 'run:%')", (since,))["c"]
    ai_cost = round(cost_runs + cost_other, 2)
    months = []
    all_decided = [checkpoints._public(r) for r in db.q("SELECT * FROM checkpoints WHERE decided >= ? AND status IN ('accepted', 'sent_back')", (now - 190 * 86400,))]
    if not auth.is_admin(u):
        ids = {c["id"] for c in decided}
        teams = {t["id"] for t in u.get("teams") or []}
        all_decided = [c for c in all_decided if c["id"] in ids or c.get("decided_by") == u["id"] or c.get("team_id") in teams]
    for label, start, end in home._month_keys():
        rs = [r for r in runs if start <= r["ended"] < end]
        cs = [c for c in all_decided if start <= (c.get("decided") or 0) < end]
        months.append({"month": label, "agent_hours": round(sum((r.get("duration_ms") or 0) for r in rs if is_agent_run(r, llm)) / 3.6e6, 2),
                       "people_hours": round(sum((c.get("seconds") or 0) for c in cs) / 3600, 2), "decided": len(cs),
                       "accepted_pct": round(100 * sum(1 for c in cs if c["status"] == "accepted") / len(cs), 1) if cs else None,
                       "cost_usd": round(sum((r.get("cost_usd") or 0) for r in rs), 2), "runs": len(rs)})
    rate = float(b.get("hourly_rate") or 0)
    try:
        fx = float(json.loads(db.meta("branding") or "{}").get("usd_rate") or 1)
    except (ValueError, TypeError):
        fx = 1.0
    working_hours = span / 86400 * 40 / 7
    ages = [(now - c["created"]) / 3600 for c in open_]
    return {
        "period": period, "since": since, "brand": {k: b[k] for k in ("name", "full", "partner", "currency", "hourly_rate")},
        "kpis": {"people": len(people), "builders": sum(1 for p in people if p["builder"] and not p["admin"]), "leads": sum(1 for p in people if p["admin"]),
                 "agents_now": 1 if cur.get("kind") else 0, "agents": len(agent_rows), "runs": len(in_period), "queued": queued,
                 "waiting": len(open_), "waiting_oldest_h": round(max(ages), 1) if ages else 0, "waiting_median_h": round(statistics.median(ages), 1) if ages else 0,
                 "agent_hours": round(agent_hours, 1), "people_hours": round(people_hours, 1),
                 "decided": len(decided), "accepted": acc, "sent_back": len(decided) - acc, "rft": round(100 * acc / len(decided), 1) if decided else None,
                 "fix_rounds": len(fixes), "work_runs": len(work), "run_rft": round(100 * (1 - len(fixes) / len(work)), 1) if work else None,
                 "ai_cost_usd": ai_cost},
        "value": {"hours": round(agent_hours, 1), "fte": round(agent_hours / working_hours, 2) if working_hours else 0, "working_hours": round(working_hours),
                  "rate": rate, "currency": b.get("currency"), "usd_rate": fx, "value": round(agent_hours * rate, 0) if rate else None,
                  "ai_cost": round(ai_cost * fx, 0), "net": round(agent_hours * rate - ai_cost * fx, 0) if rate else None},
        "now": now_rows, "people": person_rows, "agents": agent_rows, "months": months, "catalogue": agents.catalogue(),
        "waiting": [{"id": c["id"], "name": c["name"], "module": c["module"], "view": c["view"], "created": c["created"], "link": c.get("link"),
                     "assignee": user_names.get(c.get("assignee_id")), "agent": c.get("agent")} for c in open_[:12]],
        "running": {**cur, "name": here["name"], "agent": agents.name(cur["kind"]), "doing": agents.doing(cur["kind"]), "module": here["module"], "link": here["link"],
                    "age_s": round(now - cur["started"]) if cur.get("started") else None} if here else None,
    }


@router.get("/api/team")
def get_team(period: str = "30d"):
    u = auth.current.get()
    if not u:
        raise HTTPException(401, "Sign in.")
    if not auth.is_dev(u):
        raise HTTPException(403, "Team & agents is for builders and leads.")
    return build(u, period if period in PERIODS else "30d")
