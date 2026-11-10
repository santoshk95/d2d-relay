"""Apache Airflow — the stable REST API (…/api/v1): DAGs (owners, schedule, tags), DAG runs, connections by name.
Tags "source:<system>", "target:<system>" and "writes:<warehouse>:<object>" name what a DAG moves (Airflow itself
only knows tasks)."""
from __future__ import annotations

import time

from . import base

KIND, LABEL, GROUP = "airflow", "Apache Airflow", "Pipelines & ETL"
AUTH = "basic auth (a read-only Airflow user)"
DOCS = "Airflow REST API v1: GET /dags, /dags/{id}/dagRuns, /connections"
CONFIG = [{"name": "url", "label": "API base URL", "hint": "https://airflow.example.com/api/v1", "required": True}]
SECRETS = [{"name": "username", "label": "User"}, {"name": "password", "label": "Password"}]
STATUS = {"success": "success", "failed": "failed", "running": "running", "queued": "running"}


def discover(cfg: dict, secrets: dict, now: float | None = None) -> dict:
    now = now or time.time()
    c = base.Client(cfg["url"], base.Client.basic(secrets.get("username") or "", secrets.get("password") or ""))
    out = base.empty()
    systems = {}
    for d in (c.get("/dags", {"limit": 200}).get("dags") or []):
        tags = [t.get("name") or t for t in d.get("tags") or []]
        tag = lambda k: next((str(t).split(":", 1)[1].strip() for t in tags if str(t).lower().startswith(k + ":")), None)  # noqa: E731
        frm, to = tag("source"), tag("target")
        if not (frm and to):
            frm, to = frm or base.arrow(d.get("description") or "")[0], to or base.arrow(d.get("description") or "")[1]
        for s in (frm, to):
            if s:
                systems[s] = {"name": s, "kind": "system"}
        si = d.get("schedule_interval") or {}
        sched = base.schedule_text(cron=si.get("value")) if isinstance(si, dict) and si.get("__type") == "CronExpression" else (str(si.get("value") or "Manual") if isinstance(si, dict) else "Manual")
        if isinstance(si, dict) and si.get("__type") == "TimeDelta":
            sched = base.schedule_text(every_min=int((si.get("days", 0) * 86400 + si.get("seconds", 0)) / 60) or None)
        out["integrations"].append({"ext_id": d["dag_id"], "name": (d.get("description") or d["dag_id"])[:200], "kind": "Pipeline", "via": "Airflow", "from_system": frm, "to_system": to,
                                    "schedule": sched + (" (paused)" if d.get("is_paused") else ""), "owner": ", ".join(d.get("owners") or []) or None,
                                    "writes": [str(t).split(":", 1)[1].strip() for t in tags if str(t).lower().startswith("writes:")], "properties": {"paused": d.get("is_paused"), "tags": tags}})
        for r in (c.get(f"/dags/{d['dag_id']}/dagRuns", {"limit": 500, "order_by": "-start_date"}).get("dag_runs") or []):
            st, en = base.ts(r.get("start_date")), base.ts(r.get("end_date"))
            out["runs"].append({"integration": d["dag_id"], "ext_id": r.get("dag_run_id"), "started": st, "ended": en, "status": STATUS.get(r.get("state"), "failed"),
                                "duration_s": round(en - st, 1) if st and en else None, "volume": (r.get("conf") or {}).get("rows"), "error": (r.get("note") or None) if r.get("state") == "failed" else None})
    try:
        for cn in (c.get("/connections", {"limit": 200}).get("connections") or []):
            out["credentials"].append({"name": cn["connection_id"], "kind": cn.get("conn_type") or "connection", "integration": None, "expires": base.expires_from([cn.get("description")]), "status": None})
    except base.SourceError:
        pass
    out["systems"] = list(systems.values())
    return out
