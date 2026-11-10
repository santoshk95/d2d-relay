"""Oracle Integration Cloud (OIC) — the Integrations REST API (…/ic/api/integration/v1): integrations with their
source / target endpoints, monitoring instances (runs), connections (credentials by name and security policy) and
the monitoring summary of messages used against the monthly message pack."""
from __future__ import annotations

import time

from . import base

KIND, LABEL, GROUP = "oic", "Oracle Integration Cloud", "Integration platform"
AUTH = "service account (basic) or OAuth token"
DOCS = "OIC REST API: GET /integrations, /monitoring/instances, /connections; monitoring summary for message-pack usage"
CONFIG = [{"name": "url", "label": "API base URL", "hint": "https://<instance>.integration.ocp.oraclecloud.com/ic/api/integration/v1", "required": True}]
SECRETS = [{"name": "username", "label": "Service account user"}, {"name": "password", "label": "Password or OAuth token"}]
STATUS = {"COMPLETED": "success", "SUCCEEDED": "success", "FAILED": "failed", "ABORTED": "failed", "ERRORED": "failed", "IN_PROGRESS": "running"}


def discover(cfg: dict, secrets: dict, now: float | None = None) -> dict:
    now = now or time.time()
    user, pw = secrets.get("username") or "", secrets.get("password") or ""
    c = base.Client(cfg["url"], base.Client.basic(user, pw) if user else base.Client.bearer(pw))
    out = base.empty()
    systems = {}
    for it in (c.get("/integrations", {"limit": 200}).get("items") or []):
        src = next((e for e in it.get("endPoints") or [] if (e.get("role") or "").upper() == "SOURCE"), {})
        dst = next((e for e in it.get("endPoints") or [] if (e.get("role") or "").upper() == "TARGET"), {})
        f, t = (src.get("connection") or {}).get("name"), (dst.get("connection") or {}).get("name")
        for s in (f, t):
            if s:
                systems[s] = {"name": s, "kind": "system"}
        sched = it.get("scheduleParams") or {}
        out["integrations"].append({"ext_id": it.get("code") or it["id"], "name": it.get("name") or it.get("code"), "kind": "Integration", "via": "OIC", "from_system": f, "to_system": t or "Oracle Integration Cloud",
                                    "schedule": base.schedule_text(sched.get("everyMinutes"), text=sched.get("text")) if sched else ("On event" if (it.get("pattern") or "").upper() != "SCHEDULED" else "Unknown"),
                                    "owner": base.owner_from([it.get("description")]), "writes": base.writes_from([it.get("description")]),
                                    "properties": {"status": it.get("status"), "pattern": it.get("pattern"), "version": it.get("version"), "updated_by": it.get("lastUpdatedBy")}})
        code = it.get("code") or it["id"]
        for r in (c.get("/monitoring/instances", {"q": "{integrationId:'%s'}" % code, "limit": 500}).get("items") or []):
            st = base.ts(r.get("creationDate")); en = base.ts(r.get("lastTrackedTime"))
            out["runs"].append({"integration": code, "ext_id": str(r.get("id")), "started": st, "ended": en, "status": STATUS.get((r.get("status") or "").upper(), "failed"),
                                "duration_s": round(en - st, 1) if st and en else None, "volume": r.get("messageCount"), "error": r.get("errorMessage")})
    for cn in (c.get("/connections", {"limit": 200}).get("items") or []):
        out["credentials"].append({"name": cn.get("name") or cn.get("id"), "kind": (cn.get("securityPolicy") or "").lower() or "connection", "integration": None,
                                   "expires": base.expires_from([cn.get("description")]), "status": (cn.get("status") or "").lower() or None})
    try:
        m = c.get("/monitoring/metrics")
        if m.get("messagePackLimit"):
            busiest = max(out["integrations"], key=lambda i: sum(1 for r in out["runs"] if r["integration"] == i["ext_id"]), default=None)
            pct = round(100 * (m.get("messagesProcessed") or 0) / m["messagePackLimit"])
            out["signals"].append({"kind": "usage", "integration": busiest["ext_id"] if busiest else None, "text": f"OIC message usage at {pct} % of the monthly pack", "value": m.get("messagesProcessed"), "limit": m["messagePackLimit"], "due": None})
    except base.SourceError:
        pass
    out["systems"] = list(systems.values())
    return out
