"""D2D Relay: the dashboard product, cut down from RELAY by PASDACS.

What stays: Dashboards (describe -> plan -> KPIs -> prototype -> review -> Power BI project), the visual library,
CSV / flat-file uploads, and Connections with Google BigQuery only. Administration stays for the one admin.

Everything else in the copied code base is switched off here, in one place:
  - the module catalogue (registry.MODULES) keeps only KEEP_MODULES, so menus, Home and search never show the rest;
  - the APIs of every other module answer 404 (BLOCKED_API, checked by auth.check);
  - Connections offers only KEEP_KINDS;
  - the other modules' background pollers are not started (main.lifespan asks `wanted`).
"""
from __future__ import annotations

NAME = "D2D Relay"
KEEP_MODULES = {"d2d", "bi", "connect", "gates", "visuals", "demodata", "runners", "ops", "govern"}
KEEP_KINDS = {"bigquery"}

# APIs of screens that are not part of D2D Relay (on top of the dropped modules' own `api=[…]` prefixes)
EXTRA_BLOCKED = ("/api/askd", "/api/schedules", "/api/semantic", "/api/pages", "/api/reviews", "/api/studio", "/api/rfp",
                 "/api/servicedesk", "/api/lineage", "/api/graph", "/api/intan", "/api/observe", "/api/migrate-bi", "/api/heal",
                 "/api/sdlc", "/api/start", "/api/team", "/api/m/", "/api/tenancy/tenants", "/api/email")
ALLOWED_UNDER_BLOCKED = ("/api/m/connect",)   # the Connections module page

BLOCKED_API: tuple[str, ...] = EXTRA_BLOCKED
_applied = False


def apply() -> None:
    """Trim the catalogues. Called once by main.py after every module has registered itself."""
    global BLOCKED_API, _applied
    if _applied:
        return
    from . import connectors, registry
    dropped = [m for m in registry.MODULES if m["id"] not in KEEP_MODULES]
    prefixes = {p for m in dropped for p in m.get("api") or []}
    BLOCKED_API = tuple(sorted(prefixes | set(EXTRA_BLOCKED), key=len, reverse=True))
    registry.MODULES[:] = [m for m in registry.MODULES if m["id"] in KEEP_MODULES]
    registry.BY_ID.clear()
    registry.BY_ID.update({m["id"]: m for m in registry.MODULES})
    for k in list(connectors.KINDS):
        if k not in KEEP_KINDS:
            del connectors.KINDS[k]
    connectors.CATEGORIES[:] = [c for c in connectors.CATEGORIES if c[0] == "warehouse"]
    for k in list(connectors.OAUTH):
        if k not in KEEP_KINDS:
            del connectors.OAUTH[k]
    _applied = True


def blocked(path: str) -> bool:
    if path.startswith(ALLOWED_UNDER_BLOCKED):
        return False
    return any(path == p or path.startswith(p if p.endswith("/") else p + "/") or path.startswith(p + "?") for p in BLOCKED_API)
