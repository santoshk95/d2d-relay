"""D2D Relay: the dashboard product, cut down from RELAY by PASDACS.

What stays: Ask Relay (Ask D: questions about your data, answered with charts), Dashboards (describe -> plan -> KPIs -> prototype -> review -> Power BI project), the visual library,
CSV / flat-file uploads, and Connections. Platform administration is the admin portal's (portal.py), not the public site's.

Data: the public side takes CSV files (and demo data Relay generates). The warehouses and databases in CONNECTORS are
listed for everyone, but each one is switched on per organisation by PASDACS, on request (orgs.py: relay.tn_orgs
.connectors, set by a platform admin): until then the organisation cannot add, test, query or pull from it.

Everything else in the copied code base is switched off here, in one place:
  - the module catalogue (registry.MODULES) keeps only KEEP_MODULES, so menus, Home and search never show the rest;
  - the APIs of every other module answer 404 (BLOCKED_API, checked by auth.check);
  - Connections offers only KEEP_KINDS, and only the ones switched on for the organisation;
  - the other modules' background pollers are not started (main.lifespan asks `wanted`).
"""
from __future__ import annotations

NAME = "D2D Relay"
KEEP_MODULES = {"d2d", "bi", "connect", "gates", "visuals", "demodata", "runners", "ops", "govern"}
# The connectors PASDACS can switch on for an organisation (connectors.KINDS), in the order they are listed, with what
# each one reads. Every one has a Power BI connector of its own (genbi_kit.report_builder.NATIVE_KINDS).
CONNECTORS = {
    "bigquery": "Tables and views in Google BigQuery, with a service account or Sign in with Google.",
    "snowflake": "Snowflake tables and views, with OAuth, a password or a key pair.",
    "fabric": "A Microsoft Fabric warehouse or lakehouse (its SQL endpoint), with your Microsoft sign-in.",
    "redshift": "Amazon Redshift tables and views.",
    "athena": "Amazon Athena tables over your S3 data lake.",
    "oracle_db": "Oracle Database, including Autonomous Database.",
}
KEEP_KINDS = set(CONNECTORS)

# APIs of screens that are not part of D2D Relay (on top of the dropped modules' own `api=[…]` prefixes)
EXTRA_BLOCKED = ("/api/schedules", "/api/semantic", "/api/pages", "/api/reviews", "/api/studio", "/api/rfp",
                 "/api/servicedesk", "/api/lineage", "/api/graph", "/api/intan", "/api/observe", "/api/migrate-bi", "/api/heal",
                 "/api/sdlc", "/api/start", "/api/team", "/api/m/", "/api/tenancy/tenants", "/api/email",
                 "/api/home", "/api/me/usage")          # AI costs and tokens are kept on the server only (orgs.py)
ALLOWED_UNDER_BLOCKED = ("/api/m/connect", "/api/askd")   # the Connections module page; Ask Relay (Ask D)

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
