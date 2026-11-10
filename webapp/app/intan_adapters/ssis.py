"""SSIS catalog (SSISDB) — read with SQL: catalog.executions (package runs with status and times),
catalog.execution_data_statistics (rows moved between source and destination components), catalog.operation_messages
(errors), catalog.packages / projects / folders. The same queries run on SQL Server (pyodbc) and, for the mock lab, on
a SQLite copy of the catalog where each view is a table named catalog_<view>. The package description may carry
"schedule: …" and "owner: …" (SQL Agent schedules are not in SSISDB)."""
from __future__ import annotations

import time

from . import base

KIND, LABEL, GROUP = "ssis", "SSIS catalog", "Pipelines & ETL"
AUTH = "SQL login (read on SSISDB)"
DOCS = "SSISDB views catalog.executions, catalog.execution_data_statistics, catalog.operation_messages, catalog.packages"
CONFIG = [{"name": "dsn", "label": "Catalog", "hint": "mssql://host/SSISDB or sqlite:///path (mock lab)", "required": True}]
SECRETS = [{"name": "username", "label": "SQL user"}, {"name": "password", "label": "Password"}]
STATUS = {7: "success", 4: "failed", 6: "failed", 3: "failed", 2: "running", 5: "running", 1: "running", 8: "running", 9: "success"}


def _connect(dsn: str, secrets: dict):
    if dsn.startswith("sqlite:///"):
        import sqlite3
        c = sqlite3.connect(dsn[len("sqlite:///"):])
        c.row_factory = sqlite3.Row
        return c, (lambda v: f"catalog_{v}")
    if dsn.startswith("mssql://"):
        try:
            import pyodbc
        except ImportError as e:
            raise base.SourceError("pyodbc is not installed in this image; the SSIS catalog needs it.") from e
        host, _, dbn = dsn[len("mssql://"):].partition("/")
        c = pyodbc.connect(f"DRIVER={{ODBC Driver 18 for SQL Server}};SERVER={host};DATABASE={dbn or 'SSISDB'};UID={secrets.get('username', '')};PWD={secrets.get('password', '')};TrustServerCertificate=yes", timeout=10)
        return c, (lambda v: f"catalog.{v}")
    raise base.SourceError("The catalog must be mssql://host/SSISDB or sqlite:///path.")


def _rows(conn, sql: str, args=()) -> list[dict]:
    cur = conn.execute(sql, args) if hasattr(conn, "row_factory") else conn.cursor().execute(sql, args)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def discover(cfg: dict, secrets: dict, now: float | None = None) -> dict:
    now = now or time.time()
    conn, T = _connect(cfg["dsn"], secrets)
    out = base.empty()
    try:
        pk = _rows(conn, f"SELECT p.name AS package, p.description AS description, pr.name AS project, f.name AS folder FROM {T('packages')} p JOIN {T('projects')} pr ON pr.project_id = p.project_id JOIN {T('folders')} f ON f.folder_id = pr.folder_id")
        ex = _rows(conn, f"SELECT execution_id, package_name, status, start_time, end_time, created_by_name FROM {T('executions')} ORDER BY start_time")
        stats = _rows(conn, f"SELECT execution_id, source_component_name, destination_component_name, SUM(rows_sent) AS rows_sent FROM {T('execution_data_statistics')} GROUP BY execution_id, source_component_name, destination_component_name")
        msgs = _rows(conn, f"SELECT operation_id, message FROM {T('operation_messages')} WHERE message_type = 120")
    finally:
        conn.close()
    by_exec: dict[str, list] = {}
    for s in stats:
        by_exec.setdefault(str(s["execution_id"]), []).append(s)
    errs = {str(m["operation_id"]): m["message"] for m in msgs}
    systems = {}
    for p in pk:
        desc = p.get("description") or ""
        mine = [e for e in ex if e["package_name"] == p["package"]]
        comps = [s for e in mine for s in by_exec.get(str(e["execution_id"]), [])]
        f = (comps[-1]["source_component_name"] if comps else None) or base.arrow(desc)[0]
        t = (comps[-1]["destination_component_name"] if comps else None) or base.arrow(desc)[1]
        for s in (f, t):
            if s:
                systems[s] = {"name": s, "kind": "system"}
        sched = next((x.split(":", 1)[1].strip() for x in desc.split(";") if x.strip().lower().startswith("schedule")), None)
        out["integrations"].append({"ext_id": p["package"], "name": p["package"].replace(".dtsx", ""), "kind": "Package", "via": "SSIS", "from_system": f, "to_system": t, "schedule": sched or "Unknown",
                                    "owner": base.owner_from([desc]) or (mine[-1].get("created_by_name") if mine else None), "writes": base.writes_from([desc]),
                                    "properties": {"project": p["project"], "folder": p["folder"]}})
        for e in mine:
            st, en = base.ts(e["start_time"]), base.ts(e["end_time"])
            out["runs"].append({"integration": p["package"], "ext_id": str(e["execution_id"]), "started": st, "ended": en, "status": STATUS.get(int(e["status"] or 0), "failed"),
                                "duration_s": round(en - st, 1) if st and en else None, "volume": sum(s["rows_sent"] or 0 for s in by_exec.get(str(e["execution_id"]), [])) or None,
                                "error": errs.get(str(e["execution_id"]))})
    out["systems"] = list(systems.values())
    return out
