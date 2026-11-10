"""Data warehouse & lakehouse (registry id `dwh`) — designed, built, tuned or migrated, with reconciliation.

Sources: Oracle DW / Exadata / Autonomous DW (REST-enabled SQL), Teradata (Query Service), IBM Db2 (REST) through their
APIs, and the exports of every one (SQL Server, Netezza, Greenplum and Hive have no HTTP API: their DDL, code and query
history are uploaded). Targets: Snowflake (SQL API) and Databricks (Statement Execution) live; BigQuery, Fabric /
Synapse and Redshift as converted DDL and SQL (their live load is a pilot item). The mock lab's warehouse simulators
stand in for each.

Assess   Connect → Inventory → Health → Findings → Estimate: tables, views and procedural code from the dictionary, how
         each is used (the query history), what to retire, what fails, what is slow, the waves with their time.
Develop  Sources → Model → Build → Prove → Ship → Run: a star schema from named tables — facts, dimensions and keys
         proposed by rules from the data, confirmed by a person, built as DDL and dbt models in the target's SQL,
         proven on a copy (row counts, every key found in its dimension, the business totals), approved, then created
         in the target through its write approval.
Change   Request → Diagnose → Fix → Prove → Approve → Learn: a slow table tuned — the columns its queries filter and
         group by, from the history; a clustering key proposed in the target's own syntax, proven, approved, written.
Migrate  Discover → Decide → Convert → Prove → Hand over → Run: the whole warehouse moved — keep / merge / retire from
         the query history, DDL by rules in the target's types with clustering, views transpiled, the data loaded in
         waves through the target's write approval, procedural code drafted by the agent; proven table by table and
         query by query on both sides; signed off; reconciled every day after by the Data quality module.
Run      Watch → Alert → Fix → Approve → Report: failed queries and scheduler jobs since the last round, grouped,
         routed to Self-healing or a ticket after a person approves.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from .. import auth, connectors, db, registry
from .. import workbench as wb
from . import _w1, _w1_sql
from . import dwh_rules as dr

MODULE = "dwh"
SYSTEM = "Relay warehouse"
MINUTES = {"table": 6, "view": 12, "routine line": 0.5, "retire": 5, "GB to move": 20}
LEGACY = _w1_sql.LEGACY_KINDS
CLOUD = _w1_sql.CLOUD_KINDS + ("snowflake", "bigquery", "fabric", "redshift")


class Legacy(wb.Platform):
    label = "The warehouse you have"
    kinds = LEGACY + ("oracle_db", "postgres", "sqlserver")
    uploads = (".zip", ".sql", ".csv", ".txt")
    simulator = "tests/mocklab/sims: oracle_dw, teradata, db2; Oracle Database Free in a throwaway container (oracle_db); the exports of sqlserver, netezza, greenplum, hive"
    reads = "its data dictionary, views, procedural code and query history — read-only; or the exports (DDL, code, history) you upload"


class Cloud(wb.Platform):
    label = "The warehouse you are moving to"
    kinds = CLOUD
    simulator = "tests/mocklab/sims: snowflake (SQL API), databricks_sql (Statement Execution)"
    reads = "its dictionary and, for the proofs, the tables Relay loaded; it writes only through its own approval per change"


SRC, TGT = Legacy(), Cloud()
TARGET_OF = {"snowflake_sqlapi": "snowflake", "snowflake": "snowflake", "databricks_sql": "databricks", "bigquery": "bigquery", "fabric": "tsql", "redshift": "redshift"}


def _src(ctx: wb.Ctx) -> dict | None:
    return next((c for c in ctx.connections() if c["kind"] in SRC.kinds), None)


def _tgt(ctx: wb.Ctx) -> dict | None:
    return next((c for c in ctx.connections() if c["kind"] in TGT.kinds), None)


def _adapter(c: dict):
    return connectors.sdk.get(c["kind"])


def estate(ctx: wb.Ctx, conn: dict | None = None) -> dict:
    c = conn or _src(ctx)
    if c:
        a = _adapter(c)
        if not hasattr(a, "execute"):
            raise wb.StepFailed(f"{c['name']} is read through its driver; Relay reads warehouses over their HTTP APIs here — upload the exports instead.")
        try:
            return dr.from_api(a, c)
        except connectors.ConnectorError as e:
            raise wb.StepFailed(f"{c['name']} could not be read: {e}") from e
    files = [ctx.dir / "data" / f["name"] for f in ctx.files(SRC.uploads)]
    if not files:
        raise wb.StepFailed("Pick the warehouse's connection or upload its exports (a .zip of the DDL, code and history folders).")
    est = dr.from_files(files)
    if ctx.scope.get("source_dialect"):
        est["dialect"] = ctx.scope["source_dialect"]
    return est


def _target(ctx: wb.Ctx) -> str:
    t = _tgt(ctx)
    return ctx.scope.get("target_dialect") or (TARGET_OF.get(t["kind"]) if t else None) or "snowflake"


def _hours(m: float) -> str:
    return f"{m / 60:.1f} h"


def _cost(h: float) -> str:
    b = registry.brand()
    rate, cur = float(b.get("hourly_rate") or 0), b.get("currency") or ""
    return f" · {cur}{rate * h:,.0f}" if rate else ""


def _store(ctx: wb.Ctx, est: dict) -> None:
    ctx.put("estate", {**{k: v for k, v in est.items() if k != "history"}, "history": est["history"][-1500:]})


# ================================================================== Assess

def a_connect(ctx: wb.Ctx) -> dict:
    rows = []
    for p in (SRC, TGT):
        rows += p.test(ctx)
    if not rows:
        raise wb.StepFailed("Nothing to read: pick the warehouse's connection or upload its exports (DDL, code and history).")
    good = [r for r in rows if r["ok"]]
    if not good:
        raise wb.StepFailed("None of the sources answered: " + "; ".join(f"{r['source']}: {r['sees']}" for r in rows)[:600])
    return {"summary": f"{len(good)} of {len(rows)} source(s) answered — read-only.", "counts": {"sources": len(rows), "answered": len(good)},
            "data": {"columns": ["Source", "Kind", "Status", "What Relay sees", "Access"], "rows": [[r["source"], r["kind"], "answered" if r["ok"] else "refused", r["sees"], r["scope"]] for r in rows]}}


def _inventory_rows(est: dict, use: dict) -> list[dict]:
    rows = []
    for t in est["tables"]:
        u = use.get(t["name"]) or {}
        rows.append({"id": t["name"], "object": t["name"], "type": t["kind"].lower(), "rows": t.get("rows"), "size_mb": round((t.get("bytes") or 0) / 1048576, 1) if t.get("bytes") else None,
                     "columns": len(t["columns"]), "queries": u.get("queries", 0), "users": ", ".join(u.get("users") or [])[:120], "last_used": (u.get("last") or "")[:10]})
    for v in sorted(set(est["views"]) - {t["name"] for t in est["tables"]}):
        u = use.get(v) or {}
        rows.append({"id": v, "object": v, "type": "view", "rows": None, "size_mb": None, "columns": None, "queries": u.get("queries", 0), "users": ", ".join(u.get("users") or [])[:120],
                     "last_used": (u.get("last") or "")[:10]})
    for r in est["routines"]:
        rows.append({"id": r["name"], "object": r["name"], "type": r["type"].lower(), "rows": None, "size_mb": None, "columns": None, "queries": None, "users": "", "last_used": "",
                     "lines": r["lines"]})
    return rows


def a_inventory(ctx: wb.Ctx) -> dict:
    est = estate(ctx)
    if not est["tables"]:
        raise wb.StepFailed("The source shows no tables.")
    _store(ctx, est)
    use = dr.usage(est)
    recs = _inventory_rows(est, use)
    ctx.evidence("The dictionary as read", {"dialect": est["dialect"], "tables": [{k: t.get(k) for k in ("name", "kind", "rows", "bytes", "keys", "partitioned", "comment")} for t in est["tables"]],
                                            "views": list(est["views"]), "routines": [{k: r[k] for k in ("name", "type", "lines")} for r in est["routines"]], "history": len(est["history"])}, kind="inventory", ok=True)
    nt = sum(1 for t in est["tables"] if t["kind"] == "TABLE")
    return {"summary": f"{nt} table(s), {len(est['views'])} view(s) and {len(est['routines'])} piece(s) of procedural code in {est['where']}; {len(est['history'])} queries in the history.",
            "counts": {"tables": nt, "views": len(est["views"]), "code": len(est["routines"]), "queries": len(est["history"])}, "records": recs,
            "data": {"columns": ["Object", "Type", "Rows", "Size (MB)", "Queries", "Used by", "Last used"],
                     "rows": [[r["object"], r["type"], r["rows"], r["size_mb"], r["queries"], r["users"], r["last_used"]] for r in recs]}}


def a_health(ctx: wb.Ctx) -> dict:
    est = ctx.get("estate")
    use = dr.usage(est)
    found = dr.health(est, use)
    ctx.put("findings", found)
    ctx.put("decide", dr.decide(est, found, use))
    by = {}
    for f in found:
        by.setdefault(f["object"], []).append(f)
    checks = []
    for t in est["tables"]:
        fs = by.get(t["name"], [])
        st = "fail" if any(f["severity"] == "high" for f in fs) else "warn" if fs else "pass"
        checks.append({"name": t["name"], "label": t["name"], "status": st, "measured": f"{(use.get(t['name']) or {}).get('queries', 0)} queries", "expected": "",
                       "detail": "; ".join(f["issue"] for f in fs)[:400] or "used, no failures"})
    checks.append({"name": "code", "label": "Procedural code to convert", "status": "warn" if est["routines"] else "pass", "measured": f"{sum(r['lines'] for r in est['routines'])} lines",
                   "detail": ", ".join(r["name"] for r in est["routines"])[:300] or "none"})
    refs = sorted({n for q in est["history"] for n in re.findall(r"(?i)\b(?:FROM|JOIN)\s+([A-Za-z_]\w*\.[A-Za-z_]\w*)", q.get("text") or "")})
    if refs:
        checks.append(ctx.proof("references_real", label="Every table the history reads is in the dictionary", refs=[r.upper() for r in refs], known=[t["name"] for t in est["tables"]]))
    for t in est["tables"][:400]:
        ctx.lineage_node("table", est.get("where") or "warehouse", t["name"], label=t["name"], own=False, properties={"rows": t.get("rows")})
    return {"summary": f"{len(est['tables'])} object(s) checked: {len(found)} finding(s).", "counts": {"findings": len(found)}, "data": {"checks": checks}}


def a_findings(ctx: wb.Ctx) -> dict:
    have = {r["id"]: r for r in ctx.records("findings")}
    recs = [{**f, **({"decision": have[f["id"]].get("decision")} if f["id"] in have else {})} for f in ctx.get("findings") or []]
    return {"summary": f"{len(recs)} finding(s) — keep what matters, ignore what does not.", "counts": {"findings": len(recs)}, "records": recs,
            "items": [f"{r['object']}: {r['issue']}" for r in recs[:6]],
            "data": {"columns": ["Object", "Issue", "Measured", "Severity"], "rows": [[r["object"], r["issue"], r["measured"], r["severity"]] for r in recs]}}


FIND_EDIT = wb.Edit(columns=[wb.Column("decision", "Decision", "select", options=(("keep", "Keep"), ("ignore", "Ignore"))), wb.Column("object", "Object", readonly=True),
                             wb.Column("issue", "Issue", readonly=True)], add=False, remove=False, label="finding")


def _plan(est: dict, dec: list[dict]) -> list[dict]:
    tabs = {t["name"]: t for t in est["tables"]}
    items, total = [], 0.0
    for w, title in ((1, "Wave 1 — staging and dimensions"), (2, "Wave 2 — facts"), (3, "Wave 3 — marts, views and procedural code")):
        ds = [d for d in dec if d["decision"] == "keep" and d["wave"] == w]
        if not ds:
            continue
        lines = sum(next((r["lines"] for r in est["routines"] if r["name"] == d["object"]), 0) for d in ds if d["type"] not in ("table", "view"))
        gb = sum((tabs.get(d["object"]) or {}).get("bytes") or 0 for d in ds) / 1e9
        m = sum(MINUTES["table"] if d["type"] == "table" else MINUTES["view"] if d["type"] == "view" else 0 for d in ds) + lines * MINUTES["routine line"] + gb * MINUTES["GB to move"]
        total += m
        items.append({"title": title, "detail": f"{len(ds)} object(s): " + ", ".join(d["object"] for d in ds[:10]) + (" …" if len(ds) > 10 else ""), "effort": _hours(m) + _cost(m / 60)})
    retire = [d for d in dec if d["decision"] in ("retire", "merge")]
    if retire:
        m = len(retire) * MINUTES["retire"]
        total += m
        items.append({"title": "Retire or merge", "detail": ", ".join(d["object"] for d in retire), "effort": _hours(m) + _cost(m / 60)})
    return items, total


def a_estimate(ctx: wb.Ctx) -> dict:
    est = ctx.get("estate")
    dec = ctx.get("decide") or []
    items, total = _plan(est, dec)
    note = "Assumptions: " + "; ".join(f"{v} min per {k}" for k, v in MINUTES.items()) + "."
    ctx.output("assessment.md", f"# Warehouse assessment: {ctx.title}\n\n" + "\n".join(f"## {i['title']}\n\n{i['detail']}\n\nEffort: {i['effort']}\n" for i in items) + f"\n{note}\n",
               label="Assessment (Markdown)")
    return {"summary": f"{len(items)} wave(s), about {_hours(total)}" + _cost(total / 60) + ".", "counts": {"waves": len(items), "hours": round(total / 60, 1)},
            "data": {"items": items, "total": _hours(total), "note": note + ("" if registry.brand().get("hourly_rate") else " Set an hourly rate under Admin › Branding to see the cost.")}}


# ================================================================== Migrate

def m_discover(ctx: wb.Ctx) -> dict:
    out = a_inventory(ctx)
    out.pop("records", None)
    return out


def m_decide(ctx: wb.Ctx) -> dict:
    est = ctx.get("estate")
    use = dr.usage(est)
    found = dr.health(est, use)
    ctx.put("findings", found)
    have = {r["id"]: r for r in ctx.records(ctx.step_id)}
    recs = [{**d, **({k: have[d["id"]][k] for k in ("decision", "into", "wave") if k in have[d["id"]]} if d["id"] in have else {})} for d in dr.decide(est, found, use)]
    items, total = _plan(est, recs)
    n = {k: sum(1 for r in recs if r["decision"] == k) for k in ("keep", "merge", "retire")}
    return {"summary": f"Keep {n['keep']}, merge {n['merge']}, retire {n['retire']} — from how each is used; {len(items)} wave(s), about {_hours(total)}{_cost(total / 60)}.",
            "counts": n, "records": recs, "items": [f"{r['object']}: {r['decision']} — {r['why']}" for r in recs if r["decision"] != "keep"][:6],
            "data": {"columns": ["Object", "Type", "Decision", "Why", "Wave", "Rows", "Used by"], "rows": [[r["object"], r["type"], r["decision"], r["why"], r["wave"], r["rows"], r["users"]] for r in recs]}}


def _validate_decide(recs: list[dict], ctx: wb.Ctx) -> list[str]:
    names = {r["object"]: r for r in recs}
    out = []
    for r in recs:
        if r.get("decision") not in ("keep", "merge", "retire"):
            out.append(f"{r['object']}: keep, merge or retire")
        if r.get("decision") == "merge" and (names.get(r.get("into") or "") or {}).get("decision") != "keep":
            out.append(f"{r['object']}: it merges into {r.get('into') or '(nothing)'}, which is not kept")
        try:
            if int(r.get("wave") or 1) not in (1, 2, 3, 4, 5):
                out.append(f"{r['object']}: the wave is 1 to 5")
        except (TypeError, ValueError):
            out.append(f"{r['object']}: the wave is a number")
    return out


DECIDE_EDIT = wb.Edit(columns=[wb.Column("decision", "Decision", "select", options=(("keep", "Keep"), ("merge", "Merge"), ("retire", "Retire"))), wb.Column("into", "Merge into"),
                               wb.Column("wave", "Wave", "number"), wb.Column("object", "Object", readonly=True), wb.Column("why", "Why", readonly=True)],
                      add=False, remove=False, validate=_validate_decide, label="object")


def m_convert(ctx: wb.Ctx) -> dict:
    est = ctx.get("estate")
    target = _target(ctx)
    keep = {r["id"]: r for r in ctx.records("decide") if r.get("decision") == "keep"}
    tabs = {t["name"]: t for t in est["tables"]}
    have = {r["id"]: r for r in ctx.records(ctx.step_id)}
    recs, ddl, views = [], [], []
    for name, d in sorted(keep.items(), key=lambda x: (x[1].get("wave") or 3, x[0])):
        prev = have.get(name) or {}
        if name in tabs and tabs[name]["kind"] == "TABLE":
            sql = prev.get("sql") if prev.get("origin") == "person" else dr.table_ddl(tabs[name], target)
            ddl.append(sql)
            recs.append({"id": name, "object": name, "type": "table", "how": "rules", "status": "converted", "wave": d.get("wave"), "sql": sql, "problems": "", "origin": prev.get("origin") or "rules"})
        elif name in est["views"] or (name in tabs and tabs[name]["kind"] == "VIEW"):
            sql, prob = (prev.get("sql"), "") if prev.get("sql") and prev.get("origin") in ("person", "agent") else dr.view_sql(name, est["views"].get(name, ""), est["dialect"], target)
            if sql:
                views.append(sql)
            recs.append({"id": name, "object": name, "type": "view", "how": "agent" if prev.get("origin") == "agent" or not sql else "rules", "status": "converted" if sql else "needs Relay's agent",
                         "wave": d.get("wave"), "sql": sql or "", "problems": prob, "origin": prev.get("origin") or ("rules" if sql else "")})
        else:
            r = next((x for x in est["routines"] if x["name"] == name), None)
            if not r:
                continue
            recs.append({"id": name, "object": name, "type": r["type"].lower(), "how": "agent", "status": "drafted by Relay — check it" if prev.get("sql") else "needs Relay's agent",
                         "wave": d.get("wave"), "sql": prev.get("sql") or "", "problems": "" if prev.get("sql") else f"{r['lines']} line(s) of {r['type'].lower()}: no rule converts procedural code",
                         "origin": prev.get("origin") or ""})
    for r in recs:
        if r["type"] not in ("table", "view") and r.get("sql"):
            views.append(r["sql"])
    ctx.output(f"target-ddl-{target}.sql", ";\n\n".join(ddl) + ";\n", label=f"Tables in {dict(dr.TARGETS).get(target, target)} SQL")
    if views:
        ctx.output(f"target-views-{target}.sql", ";\n\n".join(views) + ";\n", label="Views and converted code")
    ctx.put("target", target)
    load = _request_load(ctx, recs, est) if _tgt(ctx) and ctx.scope.get("load", True) is not False else None
    waiting = sum(1 for r in recs if not r["sql"])
    return {"summary": f"{sum(1 for r in recs if r['type'] == 'table')} table(s) and {sum(1 for r in recs if r['type'] == 'view' and r['sql'])} view(s) converted to "
                       f"{dict(dr.TARGETS).get(target, target)} by rules" + (f"; {waiting} piece(s) of code wait for Relay's agent" if waiting else "")
                       + (f"; the load into {load['connection']} waits for its write approval" if load else "") + ".",
            "counts": {"tables": sum(1 for r in recs if r["type"] == "table"), "views": sum(1 for r in recs if r["type"] == "view"), "agent": waiting},
            "records": recs, "items": [f"{r['object']}: {r['problems']}" for r in recs if r["problems"]][:6],
            "data": {"columns": ["Object", "Type", "How", "Status", "Wave", "Problems"], "rows": [[r["object"], r["type"], r["how"], r["status"], r["wave"], r["problems"]] for r in recs]}}


def _request_load(ctx: wb.Ctx, recs: list[dict], est: dict) -> dict | None:
    """The tables (DDL), their rows and the views, written to the target in one approved change per item run."""
    src, tgt = _src(ctx), _tgt(ctx)
    if not src or not connectors.may_write(tgt):
        ctx.put("load", {"status": "not requested", "why": "no source connection to read the rows from" if not src else f"{tgt['name']} is read-only: set its scope to write to load it"})
        return None
    tabs = {t["name"]: t for t in est["tables"]}
    stmts, moved = [], {}
    for r in recs:
        if r["type"] != "table":
            continue
        rows = _w1.sql_rows(ctx, src["id"], f"SELECT * FROM {connectors.quote(src['kind'], r['object'])}")
        cols = [c["name"] for c in tabs[r["object"]]["columns"]]
        rows = [{k.upper(): v for k, v in x.items()} for x in rows]
        stmts += [r["sql"]] + dr.inserts(r["object"], rows, cols)
        moved[r["object"]] = len(rows)
    stmts += [r["sql"] for r in recs if r["type"] != "table" and r.get("sql")]
    a = _adapter(tgt)
    if not getattr(a, "can_write", False):
        ctx.put("load", {"status": "not requested", "why": f"{tgt['name']} is written by its own loader (a pilot item)"})
        return None
    items = [f"{n}: create and load {k:,} row(s)" for n, k in moved.items()][:12] + [f"{sum(1 for r in recs if r['type'] != 'table' and r.get('sql'))} view(s) / converted code"]
    try:
        cp = connectors.request_write(tgt, "migration load", {"statements": stmts}, ctx.who or ctx.owner, module=ctx.module_name,
                                      what=f"Create and load {len(moved)} table(s) in {tgt['name']}", items=items, link=wb.route_of(ctx.st))
    except Exception as e:  # noqa: BLE001 - ScopeError / ConnectorError: shown to the person
        raise wb.StepFailed(str(e)) from e
    ctx._handoff({"kind": "write", "label": f"Create and load {len(moved)} table(s)", "connection": tgt["name"], "checkpoint": cp["id"], "status": "awaiting approval", "link": "#/validate"})
    ctx.put("load", {"status": "awaiting approval", "checkpoint": cp["id"], "connection": tgt["name"], "tables": moved, "statements": len(stmts)})
    return {"connection": tgt["name"], "checkpoint": cp["id"]}


CODE_WORDS = """Read WORK.md, then code.json in this folder: the procedural code of a warehouse being moved (PL/SQL packages,
procedures, BTEQ scripts, macros…), each with its name, type, text, the target platform (`target`) and the tables of
the estate with their columns (`tables`). For each item write code/<name>.sql: the same logic as SQL statements in the
target's dialect — set-based INSERT … SELECT, MERGE or CREATE OR REPLACE VIEW statements, separated by semicolons; only
the tables listed; no loops, no dynamic SQL. Then write code_notes.yaml: `notes: {<name>: "what you assumed"}`."""


def _code_prompt(ctx: wb.Ctx) -> str:
    est = ctx.get("estate")
    todo = [{"name": r["object"], "type": r["type"], "text": (next((x["text"] for x in est["routines"] if x["name"] == r["object"]), "") if r["type"] != "view"
                                                              else f"CREATE VIEW {r['object']} AS {est['views'].get(r['object'], '')}")[:20000]}
            for r in ctx.records(ctx.step_id) if r["type"] != "table" and not r.get("sql")]
    (ctx.dir / "code").mkdir(exist_ok=True)
    (ctx.dir / "code.json").write_text(json.dumps({"target": ctx.get("target") or _target(ctx), "items": todo,
                                                    "tables": {t["name"]: [c["name"] for c in t["columns"]] for t in est["tables"]}}, indent=1), encoding="utf-8")
    return CODE_WORDS


def _code_check(ctx: wb.Ctx) -> list[str]:
    import sqlglot
    spec = json.loads((ctx.dir / "code.json").read_text(encoding="utf-8"))
    known = {t.upper() for t in spec["tables"]}
    out = []
    for it in spec["items"]:
        p = ctx.dir / "code" / f"{it['name']}.sql"
        if not p.exists():
            out.append(f"code/{it['name']}.sql was not written")
            continue
        try:
            trees = [x for x in sqlglot.parse(p.read_text(encoding="utf-8"), read=spec["target"]) if x is not None]
        except Exception as e:  # noqa: BLE001
            out.append(f"{it['name']}.sql does not parse as {spec['target']} SQL: {str(e).splitlines()[0][:120]}")
            continue
        if not trees:
            out.append(f"{it['name']}.sql holds no statement")
        for tr in trees:
            for t in tr.find_all(sqlglot.exp.Table):
                full = f"{t.db}.{t.name}".upper() if t.db else t.name.upper()
                if full not in known and not any(k.endswith("." + full) for k in known):
                    out.append(f"{it['name']}.sql uses {full}, which is not a table of the estate")
    return out


def _code_after(ctx: wb.Ctx, res: dict) -> dict:
    spec = json.loads((ctx.dir / "code.json").read_text(encoding="utf-8"))
    recs = ctx.records(ctx.step_id)
    names = {it["name"] for it in spec["items"]}
    for r in recs:
        if r["object"] in names:
            r.update(sql=(ctx.dir / "code" / f"{r['object']}.sql").read_text(encoding="utf-8").strip(), origin="agent", status="drafted by Relay — check it", problems="")
    ctx.evidence("Procedural code drafted by Relay", {"items": sorted(names), "summary": res.get("text") or ""}, kind="agent", ok=True)
    return {"summary": f"Relay drafted {len(names)} piece(s) of code as {spec['target']} SQL — read them before you confirm.", "records": recs,
            "data": {"columns": ["Object", "Type", "How", "Status", "Wave", "Problems"], "rows": [[r["object"], r["type"], r["how"], r["status"], r["wave"], r["problems"]] for r in recs]}}


CONVERT_EDIT = wb.Edit(columns=[wb.Column("sql", "SQL in the target's dialect", "longtext"), wb.Column("object", "Object", readonly=True), wb.Column("type", "Type", readonly=True),
                                wb.Column("status", "Status", readonly=True), wb.Column("problems", "Problems", readonly=True)], add=False, remove=False, label="object")


def _load_done(ctx: wb.Ctx) -> None:
    ld = ctx.get("load") or {}
    if ld.get("status") == "awaiting approval":
        from .. import checkpoints
        cp = checkpoints.get(ld["checkpoint"]) or {}
        if cp.get("status") != "accepted":
            raise wb.StepFailed(f"The load into {ld['connection']} waits for its write approval in the Validation queue ({ld['checkpoint']}) — approve it, then Run again.")


def _pair_rows(ctx: wb.Ctx, cid: str, kind: str, table: str) -> list[dict]:
    return [{k.upper(): v for k, v in r.items()} for r in _w1.sql_rows(ctx, cid, f"SELECT * FROM {connectors.quote(kind, table)}")]


def m_prove(ctx: wb.Ctx) -> dict:
    src, tgt = _src(ctx), _tgt(ctx)
    if not (src and tgt):
        raise wb.StepFailed("Proving needs both warehouses connected: the one you have and the one you move to.")
    _load_done(ctx)
    est = ctx.get("estate")
    tabs = {t["name"]: t for t in est["tables"]}
    target = ctx.get("target") or _target(ctx)
    known_t = {o["object"].upper() for o in _adapter(tgt).list_objects(tgt)}
    pkeys: dict[str, list[str]] = {}
    checks = []
    for r in [x for x in ctx.records("convert") if x["type"] in ("table", "view") and x.get("sql")]:
        name = r["object"]
        if name.upper() not in known_t:
            if r.get("origin") == "agent":
                checks.append({"name": name, "label": name, "status": "skip", "detail": f"drafted by Relay; it reaches {tgt['name']} with the next approved load, and is proven then"})
            else:
                checks.append({"name": name, "label": name, "status": "fail", "detail": f"not in {tgt['name']} — the load did not create it"})
            continue
        try:
            a_rows, b_rows = _pair_rows(ctx, src["id"], src["kind"], name), _pair_rows(ctx, tgt["id"], tgt["kind"], name)
        except wb.StepFailed as e:
            checks.append({"name": name, "label": name, "status": "error", "detail": str(e)[:300]})
            continue
        if a_rows and not b_rows:
            checks.append({"name": name, "label": f"{name} ({r['type']})", "status": "fail", "detail": f"{len(a_rows)} row(s) in the source, nothing in {tgt['name']} — the load or the converted SQL did not produce them"})
            continue
        cols = [c for c in (a_rows[0] if a_rows else {}) if c in (b_rows[0] if b_rows else {})] if a_rows and b_rows else []
        f_a = _w1.extract_parquet(ctx, a_rows, f"x_{_w1.slug(name)}_source")
        f_b = _w1.extract_parquet(ctx, b_rows, f"x_{_w1.slug(name)}_target")
        sa, sb = {"source": "file", "file": f_a}, {"source": "file", "file": f_b}
        parts = [ctx.proof("row_count", source=sa, target=sb)]
        if cols:
            parts.append(ctx.proof("checksum", source=sa, target=sb, columns=cols, tolerance_pct=0.0001))
            t = tabs.get(name) or {"columns": []}
            nums = [c["name"] for c in t["columns"] if c["logical"].startswith("dec") and c["name"] in cols][:4]
            by = next((c for c in ("CURRENCY", "REGION", "STATUS") if c in cols), None)
            if nums:
                parts.append(ctx.proof("totals", source=sa, target=sb, measures=nums, by=by, tolerance_pct=0.01))
            keys = [k for k in (t.get("keys") or []) if k in cols] or _key_of(a_rows, cols)
            pkeys[name] = keys
            parts.append(ctx.proof("sample_diff", source=sa, target=sb, keys=keys, n=40, columns=cols))
        bad = [p for p in parts if p["status"] == "fail"]
        checks.append({"name": name, "label": f"{name} ({r['type']})", "status": "fail" if bad else "pass", "measured": f"{len(parts) - len(bad)} of {len(parts)} agree", "expected": "all agree",
                       "detail": "; ".join(f"{p['label']}: {p['detail']}" for p in parts)[:700], "parts": [{k: p.get(k) for k in ("label", "status", "detail", "evidence")} for p in parts]})
    keep = {x["object"] for x in ctx.records("convert") if x.get("sql")}
    asked = 0
    for q in est["history"]:
        if asked >= 5 or q.get("status") != "SUCCESS":
            continue
        tq = dr.replay(q.get("text") or "", est["dialect"], target)
        used = {n.upper() for n in re.findall(r"(?i)\b(?:FROM|JOIN)\s+([A-Za-z_]\w*\.[A-Za-z_]\w*)", q.get("text") or "")}
        if not tq or not used or not used <= {k.upper() for k in keep}:
            continue
        asked += 1
        try:
            a_rows = [{k.upper(): v for k, v in r.items()} for r in _w1.sql_rows(ctx, src["id"], q["text"])]
            b_rows = [{k.upper(): v for k, v in r.items()} for r in _w1.sql_rows(ctx, tgt["id"], tq)]
        except wb.StepFailed as e:
            checks.append({"name": f"query-{asked}", "label": f"Query {asked}: {q['text'][:80]}", "status": "skip", "detail": f"not asked of both: {str(e)[:240]}"})
            continue
        f_a = _w1.extract_parquet(ctx, a_rows, f"x_query{asked}_source")
        f_b = _w1.extract_parquet(ctx, b_rows, f"x_query{asked}_target")
        p1 = ctx.proof("row_count", source={"source": "file", "file": f_a}, target={"source": "file", "file": f_b}, label=f"Query {asked}: same rows on both sides")
        p2 = ctx.proof("checksum", source={"source": "file", "file": f_a}, target={"source": "file", "file": f_b}, label=f"Query {asked}: same values on both sides", tolerance_pct=0.0001)
        st = "fail" if "fail" in (p1["status"], p2["status"]) else "pass"
        checks.append({"name": f"query-{asked}", "label": f"Query {asked} asked of both: {q['text'][:90]}", "status": st, "measured": f"{p1['measured']} rows", "expected": f"{p1['expected']} rows",
                       "detail": f"{p1['detail']}; {p2['detail']}", "parts": [{k: p.get(k) for k in ("label", "status", "detail", "evidence")} for p in (p1, p2)],
                       "evidence": ctx.evidence(f"Query {asked} on both sides", {"source_sql": q["text"], "target_sql": tq}, kind="proof", ok=st == "pass")})
    ok = sum(1 for c in checks if c["status"] == "pass")
    ctx.put("proof", {c["name"]: c["status"] for c in checks})
    ctx.put("proof_keys", pkeys)                    # the keys each table was compared on: the daily reconciliation uses them
    return {"summary": f"{ok} of {len(checks)} proof(s) agree: every table compared on both sides (rows, column fingerprints, business totals, sampled rows) and {asked} real queries asked of both.",
            "counts": {"agree": ok, "differ": sum(1 for c in checks if c["status"] == "fail"), "queries": asked}, "data": {"checks": checks},
            "items": [f"{c['label']}: {c['detail'][:200]}" for c in checks if c["status"] != "pass"][:6]}


def _key_of(rows: list[dict], cols: list[str]) -> list[str]:
    """A table's key from its rows when the dictionary has none: the first id-like column that is unique, else the
    first pair or triple of columns that is, else every column that is not a measure. Only columns that read the same
    on every engine (whole numbers, codes and dates — not decimals or empty values) are candidates, so the daily
    reconciliation finds the same rows on both sides."""
    def unique(cs):
        return len({tuple(r.get(c) for c in cs) for r in rows}) == len(rows)

    def plain(c):
        return all(r.get(c) is not None and isinstance(r.get(c), (int, float, str)) and not (isinstance(r.get(c), float) and not r.get(c).is_integer()) for r in rows[:200])
    cand = [c for c in cols if plain(c)] or cols
    ids = [c for c in cand if re.search(r"(_KEY|_ID|_NO|_CODE)$", c)]
    for c in ids + cand[:3]:
        if unique([c]):
            return [c]
    pool = ids or cand[:4]
    for i, a in enumerate(pool):
        for b in pool[i + 1:]:
            if unique([a, b]):
                return [a, b]
    for i, a in enumerate(pool):
        for j, b in enumerate(pool[i + 1:], i + 1):
            for c in pool[j + 1:]:
                if unique([a, b, c]):
                    return [a, b, c]
    return [c for c in cand if not any(isinstance(r.get(c), float) for r in rows[:50])] or cand


def m_handover(ctx: wb.Ctx) -> dict:
    proof = ctx.get("proof") or {}
    dec = ctx.records("decide")
    use = dr.usage(ctx.get("estate"))
    consumers = sorted({u for t, v in use.items() for u in v["users"] if re.search(r"(?i)powerbi|tableau|bi|report|svc", u)})
    return {"summary": f"Hand-over: {sum(1 for v in proof.values() if v == 'pass')} of {len(proof)} proof(s) agree; {sum(1 for d in dec if d.get('decision') == 'retire')} object(s) retire with the old warehouse.",
            "data": {"items": [{"title": "Cut over report by report", "detail": ", ".join(consumers) or "no BI service in the history"},
                               {"title": "The old warehouse", "detail": "kept read-only until every consumer has moved, then retired"},
                               {"title": "Reconciled every day after", "detail": "a Data quality rule set compares each table on both sides until the old one is retired"},
                               {"title": "Owner sign-off", "detail": (db.user(ctx.st.get("approver") or "") or {}).get("name") or "the owner of this work item"}]}}


def m_run(ctx: wb.Ctx) -> dict:
    """Lineage (each source table feeds its copy) and the daily reconciliation, handed to the Data quality module."""
    src, tgt = _src(ctx), _tgt(ctx)
    est = ctx.get("estate")
    tabs = {t["name"]: t for t in est["tables"]}
    job = ctx.lineage_node("job", SYSTEM, f"Migration: {ctx.title}", label=f"Migration: {ctx.title}", properties={"tables": len(tabs)})
    rules, dsets = [], []
    from . import quality as qp
    from . import quality_rules as qr
    for r in [x for x in ctx.records("convert") if x["type"] == "table" and x.get("sql")]:
        n = r["object"]
        a = ctx.lineage_node("table", src["kind"] if src else "warehouse", n, label=f"{n} ({src['name'] if src else 'source'})", own=False)
        b = ctx.lineage_node("table", tgt["kind"] if tgt else "warehouse", n, label=f"{n} ({tgt['name'] if tgt else 'target'})", own=False)
        ctx.lineage_edge(a, job, "reads")
        ctx.lineage_edge(job, b, "writes")
        if not (src and tgt):
            continue
        ds_a = qr.dataset({"source": "connection", "connection": src["id"], "object": n}, f"{n}@source", f"{n} · {src['name']}", src["name"])
        ds_b = qr.dataset({"source": "connection", "connection": tgt["id"], "object": n}, f"{n}@target", f"{n} · {tgt['name']}", tgt["name"])
        dsets += [ds_a, ds_b]
        t = tabs.get(n) or {"columns": [], "keys": []}
        key = (ctx.get("proof_keys") or {}).get(n) or t.get("keys") or [c["name"] for c in t["columns"][:1]]
        nums = [c["name"] for c in t["columns"] if c["logical"].startswith("dec")][:3]
        rules.append({"id": f"reconcile-{_w1.slug(n)}", "kind": "reconcile", "dataset": ds_a["key"], "column": "", "check": f"with {n}@target on {', '.join(key)}" + (f"; totals {', '.join(nums)}" if nums else "") + "; sample 20",
                      "severity": "high", "active": True, "description": f"{n} agrees in both warehouses until the old one is retired", "why": f"migrated by {ctx.id}", "origin": "dwh"})
    if not rules:
        return {"summary": "Lineage recorded; connect both warehouses to hand the daily reconciliation to Data quality.", "data": {"text": "no reconciliation"}}
    rs = qp.publish(ctx, rules, dsets, ctx.get("ruleset"), note=f"reconciliation after the migration {ctx.id}")
    ctx.put("ruleset", rs["id"])
    cad = ctx.scope.get("cadence") or {"every": "day", "at": "06:00", "tz": "UTC"}
    run_id = rs.get("run_item")
    if not run_id:
        item = wb.create("quality", "run", f"Reconcile: {ctx.title}"[:160], who=ctx.owner, brief=f"Daily reconciliation of the warehouse migrated in {ctx.id}, until the old warehouse is retired.",
                         connections=[], scope={"ruleset": rs["id"], "schedule": cad}, visibility=(db.project(ctx.id) or {}).get("visibility") or "private",
                         team_id=(db.project(ctx.id) or {}).get("team_id"), parent=ctx.id)
        run_id = item["id"]
        db.run("UPDATE quality_rulesets SET run_item = ? WHERE id = ?", (run_id, rs["id"]))
    return {"summary": f"{len(rules)} table(s) reconciled {_w1.lc(wb.schedule_text(cad))} by Data quality (rule set “{rs['name']}” v{rs['version']}) until the old warehouse is retired.",
            "counts": {"reconciled": len(rules)}, "data": {"href": f"#/m/quality/i/{run_id}", "label": "Open the reconciliation", "text": wb.schedule_text(cad)}}


# ================================================================== Develop: a star schema from named tables

def d_sources(ctx: wb.Ctx) -> dict:
    from . import quality_rules as qr
    want = [x.strip() for x in (ctx.scope.get("objects") or "").splitlines() if x.strip()]
    c = _src(ctx) or _tgt(ctx)
    srcs = []
    if c and want:
        objs = [o["object"] for o in _adapter(c).list_objects(c)]
        for w in want:
            hit = next((o for o in objs if o.upper() == w.upper() or o.upper().endswith("." + w.upper())), None)
            if not hit:
                raise wb.StepFailed(f"{w} is not a table {c['name']} shows.")
            srcs.append({"name": hit.upper(), "ref": {"source": "connection", "connection": c["id"], "object": hit}})
    for f in ctx.files((".csv", ".parquet")):
        srcs.append({"name": re.sub(r"\W+", "_", Path(f["name"]).stem).upper(), "ref": {"source": "file", "item": ctx.id, "file": f["table"]}})
    if not srcs:
        raise wb.StepFailed("Name the source tables (one per line) with a warehouse connection, or upload CSV / Parquet files.")
    rows = []
    for s in srcs:
        if s["ref"]["source"] == "connection":        # profiled on a read-only copy in the work item (one SELECT per table; the statistics in DuckDB)
            cc = ctx.connection(s["ref"]["connection"])
            f = _w1.extract_parquet(ctx, _w1.sql_rows(ctx, cc["id"], f"SELECT * FROM {connectors.quote(cc['kind'], s['ref']['object'])}"), f"x_src_{_w1.slug(s['name'])}")
            s["ref"] = {"source": "file", "item": ctx.id, "file": f, "from": s["ref"]}
        r = ctx.reader(s["ref"])
        try:
            p = qr.profile(r)
        finally:
            wb._close(r)
        s["profile"] = {"rows": p["rows"], "columns": [{k: c2.get(k) for k in ("name", "kind", "unique", "nulls", "distinct")} for c2 in p["columns"]]}
        rows.append([s["name"], p["rows"], len(p["columns"]), ", ".join(c2["name"] for c2 in p["columns"] if c2.get("unique"))[:120] or "—"])
    ctx.put("sources", srcs)
    return {"summary": f"{len(srcs)} table(s) profiled — their unique columns are the candidate keys.", "counts": {"tables": len(srcs)},
            "data": {"columns": ["Table", "Rows", "Columns", "Unique (candidate keys)"], "rows": rows}}


def d_model(ctx: wb.Ctx) -> dict:
    srcs = ctx.get("sources") or []
    have = ctx.records(ctx.step_id)
    if have:
        recs = have
    else:
        keys = {}
        for s in srcs:
            u = [c["name"] for c in s["profile"]["columns"] if c.get("unique") and re.search(r"(?i)(_id|_key|_code|_no)$", c["name"])]
            if u:
                keys[s["name"]] = u[0]
        recs = []
        for s in srcs:
            cols = {c["name"]: c for c in s["profile"]["columns"]}
            fks = [f"{c} → {t}.{k}" for c in cols for t, k in keys.items() if t != s["name"] and c.lower() == k.lower()]
            measures = [c for c, v in cols.items() if v["kind"] in ("int", "decimal") and not re.search(r"(?i)(_id|_key|_no|_code)$", c)]
            role = "fact" if fks and measures else "dimension"
            recs.append({"id": s["name"], "table": s["name"], "role": role, "key": keys.get(s["name"], ""), "measures": ", ".join(measures) if role == "fact" else "",
                         "relationships": "; ".join(fks), "name": ("fct_" if role == "fact" else "dim_") + re.sub(r"^(stg_|dim_|fact_|fct_)", "", s["name"].split(".")[-1].lower())})
    return {"summary": f"{sum(1 for r in recs if r['role'] == 'fact')} fact(s) and {sum(1 for r in recs if r['role'] == 'dimension')} dimension(s) proposed from the keys and measures — change roles, keys and names, then confirm.",
            "records": recs, "counts": {"facts": sum(1 for r in recs if r["role"] == "fact"), "dimensions": sum(1 for r in recs if r["role"] == "dimension")},
            "data": {"columns": ["Table", "Role", "Key", "Measures", "Relationships", "Model"], "rows": [[r["table"], r["role"], r["key"], r["measures"], r["relationships"], r["name"]] for r in recs]}}


def _validate_model(recs: list[dict], ctx: wb.Ctx) -> list[str]:
    srcs = {s["name"]: {c["name"] for c in s["profile"]["columns"]} for s in ctx.get("sources") or []}
    out = []
    for r in recs:
        cols = srcs.get(r["table"], set())
        if r.get("role") == "dimension" and not r.get("key"):
            out.append(f"{r['table']}: a dimension needs its key")
        if r.get("key") and r["key"] not in cols:
            out.append(f"{r['table']}: {r['key']} is not one of its columns")
        for m in [x.strip() for x in (r.get("measures") or "").split(",") if x.strip()]:
            if m not in cols:
                out.append(f"{r['table']}: the measure {m} is not one of its columns")
        if not re.fullmatch(r"[a-z][a-z0-9_]*", r.get("name") or ""):
            out.append(f"{r['table']}: the model name is lower case letters, digits and _")
    if not any(r.get("role") == "fact" for r in recs):
        out.append("A star schema needs at least one fact")
    return out


MODEL_EDIT = wb.Edit(columns=[wb.Column("role", "Role", "select", options=(("fact", "Fact"), ("dimension", "Dimension"))), wb.Column("key", "Key"),
                              wb.Column("measures", "Measures (comma-separated)"), wb.Column("name", "Model name"), wb.Column("table", "Table", readonly=True),
                              wb.Column("relationships", "Relationships", readonly=True)], add=False, remove=False, validate=_validate_model, label="table")


def _model_sql(ctx: wb.Ctx) -> list[dict]:
    srcs = {s["name"]: s for s in ctx.get("sources") or []}
    recs = ctx.records("model")
    dims = {r["table"]: r for r in recs if r["role"] == "dimension"}
    out = []
    for r in recs:
        cols = [c["name"] for c in srcs[r["table"]]["profile"]["columns"]]
        if r["role"] == "dimension":
            sql = f"SELECT {', '.join(cols)} FROM {r['table']}"
        else:
            fk = [x.split(" → ") for x in (r.get("relationships") or "").split("; ") if " → " in x]
            sql = f"SELECT {', '.join('f.' + c for c in cols)} FROM {r['table']} f"
            for col, ref in fk:
                t, k = ref.rsplit(".", 1)
                if t in dims:
                    sql += f" JOIN {t} d_{_w1.slug(t, 12).replace('-', '_')} ON d_{_w1.slug(t, 12).replace('-', '_')}.{k} = f.{col}"
        out.append({**r, "sql": sql, "columns": cols})
    return out


def d_build(ctx: wb.Ctx) -> dict:
    import sqlglot
    target = _target(ctx)
    models = _model_sql(ctx)
    srcs = {s["name"]: s for s in ctx.get("sources") or []}
    ddl = []
    for mdl in models:
        t = {"name": f"DW.{mdl['name'].upper()}", "columns": [{"name": c["name"], "logical": "dec(18,2)" if c["kind"] == "decimal" else "bigint" if c["kind"] == "int" else "date" if c["kind"] == "date" else "str(255)"}
                                                               for c in srcs[mdl["table"]]["profile"]["columns"]], "keys": [mdl["key"]] if mdl.get("key") else []}
        ddl.append(dr.table_ddl(t, target))
        body = sqlglot.transpile(mdl["sql"], read="duckdb", write=target, pretty=True)[0]
        for name in sorted(srcs, key=len, reverse=True):
            sch, tab = name.split(".", 1) if "." in name else ("upload", name)
            body = re.sub(rf"(?<![\w.]){re.escape(name)}(?![\w])", "{{ source('" + sch.lower() + "', '" + tab.lower() + "') }}", body, flags=re.I)
        ctx.output(f"dbt__models__marts__{mdl['name']}.sql", "{{ config(materialized='table') }}\n" + body + "\n", label=f"dbt model {mdl['name']}")
    ctx.output(f"star-schema-{target}.sql", ";\n\n".join(ddl) + ";\n", label=f"Star schema DDL ({dict(dr.TARGETS).get(target, target)})")
    ctx.put("models", models)
    return {"summary": f"{len(models)} model(s) written as dbt models and {dict(dr.TARGETS).get(target, target)} DDL.", "counts": {"models": len(models)},
            "data": {"text": "\n\n".join(ddl)[:6000]}}


def d_prove(ctx: wb.Ctx) -> dict:
    from .pipelines import _duck, _rows_of
    srcs = ctx.get("sources") or []
    models = ctx.get("models") or []
    con = _duck(ctx, {s["name"]: _rows_of(ctx, s) for s in srcs})
    checks = []
    try:
        for mdl in models:
            cur = con.execute(mdl["sql"])
            out = [dict(zip([d[0] for d in cur.description], r)) for r in cur.fetchall()]
            f_new = _w1.extract_parquet(ctx, out, f"x_{mdl['name']}_model")
            src = next(s for s in srcs if s["name"] == mdl["table"])
            f_src = _w1.extract_parquet(ctx, _rows_of(ctx, src), f"x_{mdl['name']}_source")
            checks.append(ctx.proof("row_count", label=f"{mdl['name']}: every source row, once", source={"source": "file", "file": f_src}, target={"source": "file", "file": f_new}))
            ms = [m.strip() for m in (mdl.get("measures") or "").split(",") if m.strip()]
            if ms:
                checks.append(ctx.proof("totals", label=f"{mdl['name']}: business totals as in the source", source={"source": "file", "file": f_src}, target={"source": "file", "file": f_new}, measures=ms, tolerance_pct=0.0))
            for rel in [x for x in (mdl.get("relationships") or "").split("; ") if " → " in x]:
                col, ref = rel.split(" → ")
                t, k = ref.rsplit(".", 1)
                dim = next((s for s in srcs if s["name"] == t), None)
                if not dim:
                    continue
                vals = sorted({str(r.get(col)) for r in out if r.get(col) is not None})
                known = sorted({str(r.get(k)) for r in _rows_of(ctx, dim) if r.get(k) is not None})
                checks.append(ctx.proof("references_real", label=f"{mdl['name']}: every {col} is in {t}", refs=vals, known=known))
    finally:
        con.close()
    bad = [c for c in checks if c["status"] == "fail"]
    return {"summary": f"{len(checks) - len(bad)} of {len(checks)} proof(s) pass on a copy of the sources.", "counts": {"proofs": len(checks), "failing": len(bad)}, "data": {"checks": checks},
            "items": [f"{c['label']}: {c['detail']}" for c in bad][:6]}


def d_ship(ctx: wb.Ctx) -> dict:
    tgt = _tgt(ctx)
    return {"summary": f"Go live: {len(ctx.get('models') or [])} model(s) in {tgt['name'] if tgt else 'the outputs'}.",
            "data": {"items": [{"title": "The models", "detail": ", ".join(m["name"] for m in ctx.get("models") or [])},
                               {"title": "Where", "detail": f"created in {tgt['name']} through its write approval" if tgt else "the DDL and dbt models are in the outputs"},
                               {"title": "Named approval", "detail": (db.user(ctx.st.get("approver") or "") or {}).get("name") or "the owner of this work item"}]}}


def d_run(ctx: wb.Ctx) -> dict:
    tgt = _tgt(ctx)
    target = _target(ctx)
    srcs = {s["name"]: s for s in ctx.get("sources") or []}
    job = ctx.lineage_node("job", SYSTEM, f"Star schema: {ctx.title}", label=f"Star schema: {ctx.title}")
    for s in srcs:
        ctx.lineage_edge(ctx.lineage_node("table", "warehouse", s, label=s, own=False), job, "reads")
    if not tgt or not connectors.may_write(tgt):
        return {"summary": "The DDL and dbt models are in the outputs" + (f"; {tgt['name']} is read-only, so nothing was created there." if tgt else "."), "data": {"text": "outputs only"}}
    stmts = []
    for mdl in ctx.get("models") or []:
        t = {"name": f"DW.{mdl['name'].upper()}", "columns": [{"name": c["name"], "logical": "dec(18,2)" if c["kind"] == "decimal" else "bigint" if c["kind"] == "int" else "date" if c["kind"] == "date" else "str(255)"}
                                                               for c in srcs[mdl["table"]]["profile"]["columns"]]}
        stmts.append(dr.table_ddl(t, target))
        ctx.lineage_edge(job, ctx.lineage_node("table", tgt["kind"], t["name"], label=t["name"], own=False), "writes")
    try:
        cp = connectors.request_write(tgt, "star schema", {"statements": stmts}, ctx.who or ctx.owner, module=ctx.module_name, what=f"Create {len(stmts)} table(s) in {tgt['name']}",
                                      items=[s.split("(")[0].strip() for s in stmts], link=wb.route_of(ctx.st))
    except Exception as e:  # noqa: BLE001
        raise wb.StepFailed(str(e)) from e
    ctx._handoff({"kind": "write", "label": f"Create {len(stmts)} table(s)", "connection": tgt["name"], "checkpoint": cp["id"], "status": "awaiting approval", "link": "#/validate"})
    return {"summary": f"The tables wait for their write approval in the Validation queue ({cp['id']}).", "data": {"href": "#/validate", "label": "Open the Validation queue", "text": cp["id"]}}


# ================================================================== Change: tune a slow table

def c_request(ctx: wb.Ctx) -> dict:
    name = (ctx.scope.get("table") or "").strip().upper()
    c = _tgt(ctx) or _src(ctx)
    est = estate(ctx, c)
    _store(ctx, est)
    t = next((x for x in est["tables"] if x["name"] == name or x["name"].endswith("." + name)), None)
    if not t:
        raise wb.StepFailed(f"Name the table to tune — {name or 'nothing'} is not in {c['name'] if c else 'the source'}.")
    ctx.put("table", t["name"])
    qs = [q for q in est["history"] if t["name"].split(".")[-1].lower() in (q.get("text") or "").lower()]
    ctx.put("queries", qs[-200:])
    return {"summary": f"{t['name']}: {t.get('rows') or '?'} rows; {len(qs)} quer{'y' if len(qs) == 1 else 'ies'} in the history read it.", "counts": {"queries": len(qs)},
            "data": {"text": ctx.brief or "(no request text)"}}


def c_diagnose(ctx: wb.Ctx) -> dict:
    import sqlglot
    from sqlglot import exp
    t = ctx.get("table")
    qs = ctx.get("queries") or []
    est = ctx.get("estate")
    tab = next(x for x in est["tables"] if x["name"] == t)
    cols = {c["name"] for c in tab["columns"]}
    score: dict[str, float] = {}
    for q in qs:
        try:
            tree = sqlglot.parse_one(re.sub(r"(?i)^\s*SEL\b", "SELECT", q.get("text") or ""), read={"ansi": None}.get(est["dialect"], est["dialect"]))
        except Exception:  # noqa: BLE001
            continue
        w = (q.get("elapsed_ms") or 1000) / 1000
        for node in list(tree.find_all(exp.Where)) + list(tree.find_all(exp.Group)) + list(tree.find_all(exp.Join)):
            for c in node.find_all(exp.Column):
                if c.name.upper() in cols:
                    score[c.name.upper()] = score.get(c.name.upper(), 0) + w
    best = sorted(score.items(), key=lambda x: -x[1])[:2]
    ctx.put("cluster", [c for c, _ in best])
    slow = sorted(qs, key=lambda q: -(q.get("elapsed_ms") or 0))[:3]
    checks = [{"name": f"col-{c}", "label": f"{c} filters, joins or groups the queries", "status": "warn", "measured": f"{s:.0f} s of query time", "detail": "a clustering key candidate"} for c, s in best]
    checks += [{"name": f"slow-{i}", "label": f"Slow query {i + 1}", "status": "warn", "measured": f"{(q.get('elapsed_ms') or 0) / 1000:.0f} s", "detail": (q.get("text") or "")[:200]} for i, q in enumerate(slow)]
    return {"summary": f"The queries on {t} spend most of their time filtering, joining or grouping on {', '.join(c for c, _ in best) or 'no single column'}.",
            "counts": {"queries": len(qs)}, "data": {"checks": checks or [{"name": "none", "label": "No query history for the table", "status": "skip", "detail": ""}]}}


def c_fix(ctx: wb.Ctx) -> dict:
    t, cl = ctx.get("table"), ctx.get("cluster") or []
    target = _target(ctx)
    have = ctx.records(ctx.step_id)
    if have:
        recs = have
    else:
        stmt = {"snowflake": f"ALTER TABLE {t} CLUSTER BY ({', '.join(cl)})", "databricks": f"ALTER TABLE {t} CLUSTER BY ({', '.join(cl)})",
                "bigquery": f"CREATE OR REPLACE TABLE {t} CLUSTER BY {', '.join(cl)} AS SELECT * FROM {t}", "redshift": f"ALTER TABLE {t} ALTER SORTKEY ({', '.join(cl)})",
                "tsql": f"CREATE CLUSTERED COLUMNSTORE INDEX cci_{t.split('.')[-1].lower()} ON {t} ORDER ({', '.join(cl)})"}.get(target, "")
        recs = [{"id": "t-1", "change": "clustering", "statement": stmt if cl else "", "why": f"the queries filter and join on {', '.join(cl)}" if cl else "no column stands out: describe the change"}]
    return {"summary": "Proposed by rules: " + "; ".join(r["statement"] or r["why"] for r in recs) + ". Change it if needed, then confirm.", "records": recs,
            "data": {"columns": ["Change", "Statement", "Why"], "rows": [[r["change"], r["statement"], r["why"]] for r in recs]}}


def _validate_tune(recs: list[dict], ctx: wb.Ctx) -> list[str]:
    import sqlglot
    out = []
    for r in recs:
        if not (r.get("statement") or "").strip():
            out.append("Write the statement to run")
            continue
        try:
            sqlglot.parse_one(r["statement"], read=_target(ctx))
        except Exception as e:  # noqa: BLE001
            out.append(f"The statement does not parse as {_target(ctx)} SQL: {str(e).splitlines()[0][:100]}")
    return out


TUNE_EDIT = wb.Edit(columns=[wb.Column("statement", "Statement (target SQL)", "longtext"), wb.Column("why", "Why", readonly=True)], add=False, remove=False, validate=_validate_tune, label="change")


def c_prove(ctx: wb.Ctx) -> dict:
    import sqlglot
    from sqlglot import exp
    t = ctx.get("table")
    tab = next(x for x in ctx.get("estate")["tables"] if x["name"] == t)
    cols = {c["name"] for c in tab["columns"]}
    checks = []
    for r in ctx.records("fix"):
        tree = sqlglot.parse_one(r["statement"], read=_target(ctx))
        used = sorted({c.name.upper() for c in tree.find_all(exp.Column)} | {x.strip().upper() for x in re.findall(r"(?i)CLUSTER BY \(?([\w, ]+)\)?", r["statement"]) for x in x.split(",")})
        checks.append(ctx.proof("references_real", label="Every column of the change exists in the table", refs=[u for u in used if u], known=list(cols)))
        checks.append({"name": "readonly", "label": "The change alters the layout only (no rows change)", "status": "pass" if not re.search(r"(?i)\b(DELETE|UPDATE|INSERT|TRUNCATE|DROP)\b", r["statement"]) else "fail",
                       "detail": "a layout statement" if not re.search(r"(?i)\b(DELETE|UPDATE|INSERT|TRUNCATE|DROP)\b", r["statement"]) else "it changes rows"})
    bad = [c for c in checks if c["status"] == "fail"]
    return {"summary": f"{len(checks) - len(bad)} of {len(checks)} check(s) pass.", "data": {"checks": checks}, "counts": {"failing": len(bad)}}


def c_approve(ctx: wb.Ctx) -> dict:
    return {"summary": "Release: " + "; ".join(r["statement"] for r in ctx.records("fix")), "data": {"items": [{"title": "Statement", "detail": r["statement"]} for r in ctx.records("fix")]}}


def c_learn(ctx: wb.Ctx) -> dict:
    c = _tgt(ctx) or _src(ctx)
    stmts = [r["statement"] for r in ctx.records("fix") if r.get("statement")]
    if not c or not connectors.may_write(c):
        return {"summary": "Recorded; the connection is read-only, so a person runs the statement in the warehouse.", "data": {"text": ";\n".join(stmts)}}
    try:
        cp = connectors.request_write(c, "tuning", {"statements": stmts}, ctx.who or ctx.owner, module=ctx.module_name, what=f"Tune {ctx.get('table')}", items=stmts, link=wb.route_of(ctx.st))
    except Exception as e:  # noqa: BLE001
        raise wb.StepFailed(str(e)) from e
    ctx._handoff({"kind": "write", "label": f"Tune {ctx.get('table')}", "connection": c["name"], "checkpoint": cp["id"], "status": "awaiting approval", "link": "#/validate"})
    return {"summary": f"The change waits for its write approval in the Validation queue ({cp['id']}).", "data": {"href": "#/validate", "label": "Open the Validation queue", "text": cp["id"]}}


# ================================================================== Run & support

def r_watch(ctx: wb.Ctx) -> dict:
    conns = [x for x in ctx.connections() if x["kind"] in SRC.kinds + TGT.kinds and hasattr(_adapter(x), "execute")]
    if not conns:
        raise wb.StepFailed("Pick the warehouses to watch: their API connections (Oracle, Teradata, Db2, Snowflake or Databricks).")
    since = ctx.st.get("last_run") or 0

    def recent(v) -> bool:
        return not since or (_w1.ts(v) or 0) >= since - 3600

    failed: list[dict] = []
    jobs: list[dict] = []
    for x in conns:                                 # every warehouse of the item, each through its own API
        est = estate(ctx, x)
        failed += [{**q, "where": x["name"]} for q in est["history"] if q.get("status") == "FAILED" and recent(q.get("start"))]
        jobs += [{**j, "where": x["name"]} for j in est["jobs"] if str(j.get("status") or "").upper() in ("FAILED", "FAILURE", "ERROR") and recent(j.get("start"))]
    c = {"name": " and ".join(x["name"] for x in conns)}
    ctx.put("failed", failed[-200:])
    ctx.put("failed_jobs", jobs[-100:])
    checks = [{"name": "queries", "label": "Queries since the last round", "status": "fail" if failed else "pass", "measured": f"{len(failed)} failed", "detail": "; ".join(sorted({(q.get('error') or '')[:80] for q in failed}))[:300]},
              {"name": "jobs", "label": "Scheduler jobs since the last round", "status": "fail" if jobs else "pass", "measured": f"{len(jobs)} failed", "detail": ", ".join(sorted({str(j['job']) for j in jobs}))[:300]}]
    return {"summary": f"{len(failed)} failed quer{'y' if len(failed) == 1 else 'ies'} and {len(jobs)} failed job run(s) on {c['name'] if c else 'the warehouse'}.", "counts": {"failed queries": len(failed), "failed jobs": len(jobs)},
            "data": {"checks": checks}}


def r_alert(ctx: wb.Ctx) -> dict:
    groups: dict[str, dict] = {}
    for q in ctx.get("failed") or []:
        key = re.sub(r"\d+", "#", (q.get("error") or "unknown")[:80])
        g = groups.setdefault(f"q:{q.get('where')}:{key}", {"id": f"b-{_w1.slug(str(q.get('where') or ''))}-{_w1.slug(key)}"[:120],
                                                             "what": f"queries fail on {q.get('where') or 'the warehouse'}: {q.get('error') or 'unknown'}"[:300], "n": 0, "users": set(), "route": "ticket", "note": ""})
        g["n"] += 1
        g["users"].add(str(q.get("user") or ""))
    for j in ctx.get("failed_jobs") or []:
        g = groups.setdefault(f"j:{j.get('where')}:{j['job']}", {"id": f"b-job-{_w1.slug(str(j['job']))}", "what": f"the job {j['job']} on {j.get('where') or 'the warehouse'} fails: {(j.get('error') or '')[:200]}",
                                                                 "n": 0, "users": set(), "route": "heal", "note": ""})
        g["n"] += 1
    brk = [{**g, "users": ", ".join(sorted(u for u in g["users"] if u))} for g in groups.values()]
    ctx.put("breaks", brk)
    if not brk:
        return {"summary": "Nothing failed since the last round.", "next": "report", "counts": {"breaks": 0}}
    return {"summary": f"{len(brk)} group(s) of failures.", "counts": {"breaks": len(brk)}, "items": [b["what"] for b in brk[:6]],
            "data": {"columns": ["What fails", "Times", "Who ran it", "Proposed route"], "rows": [[b["what"], b["n"], b["users"], b["route"]] for b in brk]}}


def r_fix(ctx: wb.Ctx) -> dict:
    have = {r["id"]: r for r in ctx.records(ctx.step_id)}
    recs = [{**b, **({k: have[b["id"]][k] for k in ("route", "note") if k in have[b["id"]]} if b["id"] in have else {})} for b in ctx.get("breaks") or []]
    return {"summary": f"{len(recs)} group(s): choose who fixes each. Nothing goes out until you confirm.", "records": recs,
            "data": {"columns": ["What fails", "Proposed route"], "rows": [[r["what"], r["route"]] for r in recs]}}


RFIX_EDIT = wb.Edit(columns=[wb.Column("route", "Route", "select", options=(("heal", "Self-healing"), ("ticket", "Raise a ticket"), ("expected", "Expected — no action"))),
                             wb.Column("note", "Note", "longtext"), wb.Column("what", "What fails", readonly=True)], add=False, remove=False, label="failure")


def r_approve(ctx: wb.Ctx) -> dict:
    rows = []
    for b in ctx.records("fix"):
        if b["route"] == "heal":
            h = ctx.heal(b["what"][:120], b["what"] + (f"\n\nNote: {b['note']}" if b.get("note") else ""), place=registry.BY_ID[MODULE]["short"], signature=f"dwh:{b['id']}")
        elif b["route"] == "ticket":
            h = ctx.ticket(b["what"][:120], b["what"] + (f"\n\nNote: {b['note']}" if b.get("note") else ""), priority="P3", about=b["what"])
        else:
            h = {"kind": "expected", "status": "expected — recorded"}
        rows.append([b["what"][:160], b["route"], h.get("status"), h.get("case") or h.get("checkpoint") or h.get("output") or ""])
    return {"summary": f"{len(rows)} hand-off(s), as you approved.", "data": {"columns": ["What fails", "Route", "Status", "Reference"], "rows": rows}}


def r_report(ctx: wb.Ctx) -> dict:
    n = len(ctx.get("breaks") or [])
    ctx.output(f"warehouse-report-{time.strftime('%Y%m%d-%H%M', time.gmtime())}.md", f"# Warehouse run report: {ctx.title}\n\n" + "".join(f"- {b['what']} → {b.get('route')}\n" for b in ctx.records("fix")),
               label="Run report (Markdown)")
    return {"summary": f"{n} group(s) of failures this round.", "counts": {"groups": n}, "data": {"columns": ["Round", "Groups"], "rows": [[time.strftime("%d %b %H:%M", time.gmtime()), n]]}}


def _cards(u: dict) -> list[dict]:
    rows = []
    for r in db.q("SELECT id, title, status, updated FROM wb_items WHERE module = ? AND work = 'migrate' ORDER BY updated DESC LIMIT 20", (MODULE,)):
        if not auth.can_project(u, "view", db.project(r["id"])):
            continue
        st = wb._load(r["id"])
        proof = (st.get("data") or {}).get("proof") or {}
        rows.append([r["title"], wb.STATUS_LABEL.get(r["status"], r["status"]), f"{sum(1 for v in proof.values() if v == 'pass')} of {len(proof)}" if proof else "—", f"#/m/{MODULE}/i/{r['id']}"])
    return [{"title": "Migrations and their proofs", "columns": ["Migration", "Status", "Proofs agree", "Work item"], "rows": rows,
             "empty": "No migration yet: a Migrate item proves every table and real queries on both sides."}]


GUIDE = """# Data warehouse & lakehouse — the work item

This folder is one work item of Relay's Data warehouse & lakehouse module. Relay reads the warehouse's dictionary and
history and converts tables and views by rules; you are asked only for procedural code (PL/SQL packages, BTEQ
scripts, macros, stored procedures) no rule converts.

- `code.json` (written by the app before your run): the target platform, the code to convert and the estate's tables
  with their columns.
- `code/<name>.sql`: what you write — set-based SQL statements in the target's dialect, separated by semicolons.
- `code_notes.yaml`: one sentence per item on what you assumed.

Never invent a table or a column; no loops or dynamic SQL; say what you assumed."""


wb.register(wb.Pack(
    module=MODULE, guide=GUIDE,
    lineage="every table of the source and its copy in the target, joined by the migration as a job (system “Relay warehouse”); star schemas as jobs reading their source tables",
    platforms={"legacy": SRC, "cloud": TGT},
    schemas={"object": DECIDE_EDIT.columns, "finding": FIND_EDIT.columns, "converted": CONVERT_EDIT.columns, "model": MODEL_EDIT.columns},
    cards=_cards,
    work={
        "assess": wb.Work(title="See what the warehouse holds, how it is used and what to move, merge or retire", steps={
            "Connect": wb.Step(kind="platform", run=a_connect, agent="Connector", text="The warehouse answers through its API with your sign-in — or its exports are opened"),
            "Inventory": wb.Step(kind="platform", run=a_inventory, agent="Dictionary reader", text="Every table, view and piece of procedural code, with rows, size and who queries it"),
            "Health": wb.Step(kind="proof", run=a_health, view="gates", agent="Usage analyst", text="Never queried, copies and backups, failing and slow queries, procedural code — from the dictionary and the history"),
            "Findings": wb.Step(kind="person", run=a_findings, edit=FIND_EDIT, text="What needs attention — you keep or ignore each finding"),
            "Estimate": wb.Step(kind="deterministic", run=a_estimate, view="plan", agent="Estimator", text="Waves — staging and dimensions, facts, marts and code — with the time and cost")}),
        "develop": wb.Work(title="A star schema from named tables: proposed by rules, proven on a copy, created with approval", steps={
            "Sources": wb.Step(kind="platform", run=d_sources, agent="Profiler", text="The tables you name are profiled: rows, columns and the unique ones that can be keys"),
            "Model": wb.Step(kind="deterministic", run=d_model, agent="Modeller", edit=MODEL_EDIT, text="Facts, dimensions, keys and relationships proposed from the data — you change and confirm them"),
            "Build": wb.Step(kind="deterministic", run=d_build, view="text", agent="Model builder", text="DDL and dbt models in the target warehouse's SQL"),
            "Prove": wb.Step(kind="proof", run=d_prove, view="gates", agent="Prover", back_to="model", text="Built on a copy: every source row once, business totals equal, every key found in its dimension"),
            "Ship": wb.Step(kind="person", run=d_ship, view="plan", approver=True, text="The named approver confirms go-live"),
            "Run": wb.Step(kind="platform", run=d_run, view="link", agent="Publisher", text="The tables are created in the target through its write approval")},
            fields=[wb.Field("objects", "Source tables", "longtext", help="One per line, e.g. STAGE.STG_ORDERS"), wb.Field("target_dialect", "Target warehouse", "select", options=dr.TARGETS, default="snowflake")]),
        "change": wb.Work(title="Tune a slow table: the columns its queries use, a clustering key proven and approved", steps={
            "Request": wb.Step(kind="platform", run=c_request, view="text", agent="Dictionary reader", text="The table you name and the queries in the history that read it"),
            "Diagnose": wb.Step(kind="deterministic", run=c_diagnose, view="gates", agent="Tuner", text="The columns the queries filter, join and group on, weighted by their time"),
            "Fix": wb.Step(kind="deterministic", run=c_fix, agent="Tuner", edit=TUNE_EDIT, text="A clustering key in the target's own syntax — you confirm or change it"),
            "Prove": wb.Step(kind="proof", run=c_prove, view="gates", agent="Prover", back_to="fix", text="The statement parses, every column exists, no row changes"),
            "Approve": wb.Step(kind="person", run=c_approve, view="plan", approver=True, text="The named approver releases it"),
            "Learn": wb.Step(kind="platform", run=c_learn, view="link", agent="Publisher", text="Written through the warehouse's own write approval")},
            fields=[wb.Field("table", "Table to tune", required=True, help="e.g. DW.FACT_SALES"), wb.Field("target_dialect", "Warehouse SQL", "select", options=dr.TARGETS, default="snowflake")]),
        "migrate": wb.Work(title="Move a legacy warehouse to the cloud — decided from its use, converted by rules, proven on both sides", steps={
            "Discover": wb.Step(kind="platform", run=m_discover, agent="Dictionary reader", text="The source warehouse read through its API or its exports: tables, views, code, history and jobs"),
            "Decide": wb.Step(kind="deterministic", run=m_decide, agent="Rationaliser", edit=DECIDE_EDIT, text="Keep, merge or retire each object from how it is used, in waves with their time"),
            "Convert": wb.Step(kind="deterministic", run=m_convert, agent="Converter", edit=CONVERT_EDIT, confirm="the converted objects — and the load into the target, which waits for its own write approval",
                               text="Tables by rules in the target's types with clustering, views transpiled, the rows loaded in one approved write; procedural code drafted by Relay's agent",
                               actions={"code": wb.Action(label="Ask Relay to convert the procedural code", kind="agent", prompt=_code_prompt, check=_code_check, after=_code_after, agent="Code converter (AI)",
                                                          help="The agent writes set-based SQL in the target's dialect for each package, script or macro; each is checked against the estate's tables.")}),
            "Prove": wb.Step(kind="proof", run=m_prove, view="gates", agent="Reconciler", back_to="convert",
                             text="Every table on both sides — row counts, column fingerprints, business totals, sampled rows — and real queries from the history asked of both"),
            "Hand over": wb.Step(kind="person", run=m_handover, view="plan", approver=True, text="Cut over report by report; the owner signs off the evidence pack"),
            "Run": wb.Step(kind="deterministic", run=m_run, view="link", agent="Publisher", text="Lineage recorded; the Data quality module reconciles both warehouses every day until the old one is retired")},
            fields=[wb.Field("target_dialect", "Target warehouse", "select", options=dr.TARGETS, default="snowflake"),
                    wb.Field("source_dialect", "Source SQL (exports only)", "select", options=(("", "Read it from the DDL"),) + dr.SOURCES, default=""),
                    wb.Field("cadence", "Reconcile both sides", "cadence", default={"every": "day", "at": "06:00", "tz": "UTC"})]),
        "run": wb.Work(title="Watch failed queries and jobs; each group goes to a person before Self-healing or a ticket", needs_source=True, steps={
            "Watch": wb.Step(kind="platform", run=r_watch, view="gates", agent="Watcher", text="Failed queries and scheduler jobs since the last round, from the warehouse's own history"),
            "Alert": wb.Step(kind="deterministic", run=r_alert, agent="Triage", text="Failures grouped by their error"),
            "Fix": wb.Step(kind="deterministic", run=r_fix, agent="Triage", edit=RFIX_EDIT, text="Relay proposes who fixes each group; you confirm or change it"),
            "Approve": wb.Step(kind="platform", run=r_approve, agent="Dispatcher", text="The approved hand-offs go out"),
            "Report": wb.Step(kind="deterministic", run=r_report, agent="Reporter", confirm_if=lambda ctx, out: bool(ctx.get("breaks")), text="A run report; you confirm it when something failed")},
            fields=[wb.Field("schedule", "Watch it", "cadence", default={"every": "day", "at": "07:00", "tz": "UTC"})]),
    }))
