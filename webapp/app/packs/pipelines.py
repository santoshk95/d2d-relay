"""Data pipelines & ETL (registry id `pipelines`) — pipelines written, fixed and moved between tools, rules first.

Platforms: the ETL tools' own APIs (Azure Data Factory, dbt Cloud, Airflow, Informatica Cloud, Talend Cloud, Fivetran —
`_w1` adapters, the mock-lab simulators stand in for each) and their exports (SSIS, Informatica PowerCenter, DataStage,
Talend, ODI, ADF, dbt, Airflow, AWS Glue, Fivetran), read into one neutral model (`pipelines_read`); the warehouse the
jobs load (Oracle REST-enabled SQL and the other W1 SQL kinds) for the data dictionary and the proofs.

Assess   Connect → Inventory → Health → Findings → Estimate: every job in the tool's own terms, its run history, health
         by rules (failing since, flaky, slower, a password in the definition, retire and merge candidates, no owner),
         findings a person keeps or ignores, waves with the time they take.
Develop  Describe → Shape → Build → Prove → Ship → Run: a new pipeline as a dbt model from named source tables — the
         mapping shaped by rules and confirmed by a person, built as dbt files, proven in DuckDB on a copy of the
         sources (row counts, keys unique and not null), a named approval, then the dbt Cloud job created through an
         approved write.
Change   Request → Diagnose → Fix → Prove → Approve → Learn: a failing job's cause from its error and the warehouse's
         dictionary (a renamed column, a late file, a transient outage, an expired sign-in), the change proposed by
         rules, proven against the dictionary, approved, written back to the tool through its own write approval and
         kept as a rule.
Migrate  Discover → Decide → Convert → Prove → Hand over → Run: an estate exported or read from the tool, Keep / Merge /
         Retire with reasons, Informatica PowerCenter mappings and ADF data flows converted to dbt models by rules
         (the agent drafts what no rule fits), every converted job proven against the table the legacy job loads, a
         named owner's sign-off on the evidence pack, then a Run item that watches the estate.
Run      Watch → Alert → Fix → Approve → Report: run history read on a schedule, failures grouped by job and cause, a
         person chooses Self-healing, a ticket or "expected" for each, and only then do the hand-offs go out.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from .. import auth, connectors, db, registry
from .. import workbench as wb
from . import _w1, _w1_sql  # noqa: F401 - _w1_sql registers the warehouse kinds the proofs read
from . import pipelines_expr as px
from . import pipelines_read as pr
from . import pipelines_rules as rules

MODULE = "pipelines"
SYSTEM = "Relay pipelines"
API_KINDS = _w1.kinds_of(_w1.ADF_, _w1.DBT, _w1.AIRFLOW, _w1.IICS_, _w1.TALEND, _w1.FIVETRAN)
DIALECTS = (("snowflake", "Snowflake"), ("bigquery", "BigQuery"), ("databricks", "Databricks"), ("tsql", "Microsoft Fabric / Synapse (T-SQL)"), ("redshift", "Redshift"),
            ("duckdb", "DuckDB"))
MINUTES = {"review a rules conversion": 20, "review an agent conversion": 90, "fix a failing job": 60, "retire or merge a job": 10}

db.register_schema("""
CREATE TABLE IF NOT EXISTS pipelines_fixes (
  id TEXT PRIMARY KEY, signature TEXT NOT NULL, tool TEXT, job TEXT, old TEXT, new TEXT, item TEXT, by TEXT, created REAL NOT NULL);
""")


class EtlApi(wb.Platform):
    label = "Your ETL tool, read through its API"
    kinds = API_KINDS
    simulator = "tests/mocklab/sims: adf, dbt, airflow, informatica_iics, talend, fivetran"
    reads = "pipelines, jobs, DAGs, mapping tasks, connections and their run history — read-only; a change only through its own write approval"


class EtlExports(wb.Platform):
    label = "Exports of your ETL tool"
    uploads = (".zip", ".xml", ".json", ".csv", ".txt", ".sql", ".yml", ".yaml")
    simulator = "tests/mocklab/fixtures: SSIS, Informatica PowerCenter, DataStage, Talend, ODI, ADF, dbt, Airflow, Glue, Fivetran"
    reads = ("the export as the tool writes it — a .zip of the SSIS project or .ispac with the SSISDB extracts, PowerCenter repository XML and parameter "
             "files, a DataStage .dsx, Talend items, an ODI Smart Export, the ADF ARM template, dbt's target/ folder, Airflow DAG files, Glue scripts")


class Warehouse(wb.Platform):
    label = "The warehouse the jobs load"
    kinds = ("oracle", "teradata", "db2", "snowflake_sqlapi", "databricks_sql") + wb.WarehousePlatform.kinds
    simulator = "tests/mocklab/sims: oracle_dw (Oracle REST-enabled SQL) and the other W1 warehouses"
    reads = "its data dictionary and, for the proofs, a read-only copy of the tables a job reads and the table it loads"


API, EXPORTS, WH = EtlApi(), EtlExports(), Warehouse()


# ------------------------------------------------------------------ the estate

def estate(ctx: wb.Ctx, days: int = 30) -> dict:
    """Every job and run the item's connections and uploads show (kept on the item for the later steps)."""
    since = time.time() - days * 86400
    jobs, runs, seen, unread = [], [], [], []
    for c in ctx.connections():
        if c["kind"] not in API_KINDS:
            continue
        try:
            j, r = pr.from_api(c, since)
        except connectors.ConnectorError as e:
            raise wb.StepFailed(f"{c['name']} could not be read: {e}") from e
        jobs += j
        runs += r
        seen.append({"source": c["name"], "kind": _w1.connectors.KINDS[c["kind"]]["label"], "jobs": len(j), "runs": len(r)})
    files = [ctx.dir / "data" / f["name"] for f in ctx.files(EXPORTS.uploads)]
    if files:
        j, r, u = pr.from_files(files)
        for x in j:
            x["where"] = "upload"
        jobs += j
        runs += r
        unread += u
        seen.append({"source": f"{len(files)} upload(s)", "kind": "Export", "jobs": len(j), "runs": len(r)})
    return {"jobs": jobs, "runs": runs, "seen": seen, "unread": unread}


def warehouse(ctx: wb.Ctx) -> dict | None:
    return next((c for c in ctx.connections() if c["kind"] in WH.kinds), None)


def dictionary(ctx: wb.Ctx) -> dict:
    c = warehouse(ctx)
    if not c:
        return {}
    a = connectors.sdk.get(c["kind"])
    try:
        if hasattr(a, "dictionary"):
            return a.dictionary(c)
        rows = connectors.query(c, "SELECT table_schema || '.' || table_name AS t, column_name AS c FROM information_schema.columns ORDER BY 1, ordinal_position", ctx.who or ctx.owner)["rows"]
        out = {}
        for r in rows:
            v = list(r.values())
            out.setdefault(str(v[0]).upper(), []).append(str(v[1]).upper())
        return out
    except connectors.ConnectorError as e:
        raise wb.StepFailed(f"{c['name']}: its data dictionary could not be read: {e}") from e


def _jobs(ctx: wb.Ctx) -> list[dict]:
    return ctx.get("jobs") or []


def _job(ctx: wb.Ctx, jid: str) -> dict | None:
    return next((j for j in _jobs(ctx) if j["id"] == jid), None)


def _hours(m: float) -> str:
    return f"{m / 60:.1f} h"


def _cost(h: float) -> str:
    b = registry.brand()
    rate, cur = float(b.get("hourly_rate") or 0), b.get("currency") or ""
    return f" · {cur}{rate * h:,.0f}" if rate else ""


def record_lineage(ctx: wb.Ctx, jobs: list[dict]) -> int:
    """Each job as a lineage job node (the tool's), reading its source tables and feeding its target (shared nodes)."""
    wh = warehouse(ctx)
    system = wh["kind"] if wh else "warehouse"
    n = 0
    for j in jobs[:300]:
        if not j.get("target") and not j.get("sources"):
            continue
        jn = ctx.lineage_node("job", j["tool"], j["name"], label=f"{j['name']} ({j['tool_label']})", own=False, properties={"kind": j["kind"], "schedule": j.get("schedule")})
        for s in j["sources"][:20]:
            ctx.lineage_edge(ctx.lineage_node("table", system, s, label=s, own=False), jn, "reads")
        if j.get("target") and not j["target"].endswith(".*"):
            ctx.lineage_edge(jn, ctx.lineage_node("table", system, j["target"], label=j["target"], own=False), "writes")
        n += 1
    return n


# ================================================================== Assess

def a_connect(ctx: wb.Ctx) -> dict:
    rows = []
    for p in (API, WH, EXPORTS):
        rows += p.test(ctx)
    if not rows:
        raise wb.StepFailed("Nothing to read: pick your ETL tool's connection or upload its export (a .zip of the project, the repository XML, the ARM template…).")
    good = [r for r in rows if r["ok"]]
    if not good:
        raise wb.StepFailed("None of the sources answered: " + "; ".join(f"{r['source']}: {r['sees']}" for r in rows)[:600])
    return {"summary": f"{len(good)} of {len(rows)} source(s) answered — read-only.", "counts": {"sources": len(rows), "answered": len(good)},
            "data": {"columns": ["Source", "Kind", "Status", "What Relay sees", "Access"], "rows": [[r["source"], r["kind"], "answered" if r["ok"] else "refused", r["sees"], r["scope"]] for r in rows]}}


def _inv_rows(jobs: list[dict], runs: list[dict]) -> list[dict]:
    n = {}
    for r in runs:
        n[r["job"].upper()] = n.get(r["job"].upper(), 0) + 1
    return [{"id": j["id"], "include": True, "tool": j["tool_label"], "kind": j["kind"], "job": j["name"], "folder": j.get("folder") or "", "schedule": j.get("schedule") or "",
             "owner": j.get("owner") or "", "reads": ", ".join(j["sources"][:6]), "loads": j.get("target") or "", "runs": n.get(j["name"].upper(), 0)} for j in jobs]


def a_inventory(ctx: wb.Ctx) -> dict:
    e = estate(ctx)
    if not e["jobs"]:
        raise wb.StepFailed("The sources show no jobs." + (f" Not read: {', '.join(e['unread'][:6])}." if e["unread"] else ""))
    ctx.put("jobs", e["jobs"])
    ctx.put("runs", e["runs"][-4000:])
    have = {r["id"]: r for r in ctx.records(ctx.step_id)}
    recs = [{**r, **({"include": have[r["id"]].get("include")} if r["id"] in have else {})} for r in _inv_rows(e["jobs"], e["runs"])]
    ctx.evidence("What the sources show", {"seen": e["seen"], "unread": e["unread"], "jobs": [{k: j.get(k) for k in ("id", "tool", "kind", "name", "folder", "schedule", "owner", "sources", "target")} for j in e["jobs"]]},
                 kind="inventory", ok=True)
    tools = sorted({j["tool_label"] for j in e["jobs"]})
    return {"summary": f"{len(e['jobs'])} job(s) in {', '.join(tools)} with {len(e['runs'])} run(s) in the last 30 days" + (f"; {len(e['unread'])} file(s) not read" if e["unread"] else "")
            + " — untick what is out of scope.", "counts": {"jobs": len(e["jobs"]), "runs": len(e["runs"])}, "records": recs,
            "items": [f"{s['source']} ({s['kind']}): {s['jobs']} job(s), {s['runs']} run(s)" for s in e["seen"]] + ([f"Not read: {', '.join(e['unread'][:5])}"] if e["unread"] else []),
            "data": {"columns": ["Tool", "Kind", "Job", "Folder", "Schedule", "Owner", "Reads", "Loads", "Runs (30 days)"],
                     "rows": [[r["tool"], r["kind"], r["job"], r["folder"], r["schedule"], r["owner"], r["reads"], r["loads"], r["runs"]] for r in recs]}}


INV_EDIT = wb.Edit(columns=[wb.Column("include", "Include", "bool"), wb.Column("job", "Job", readonly=True), wb.Column("tool", "Tool", readonly=True),
                            wb.Column("schedule", "Schedule", readonly=True), wb.Column("loads", "Loads", readonly=True)], add=False, remove=False, label="job")


def _included(ctx: wb.Ctx, step: str = "inventory") -> list[dict]:
    keep = {r["id"] for r in ctx.records(step) if r.get("include", True)}
    return [j for j in _jobs(ctx) if j["id"] in keep] if keep else []


def a_health(ctx: wb.Ctx) -> dict:
    jobs = _included(ctx)
    if not jobs:
        raise wb.StepFailed("No job is included: tick at least one in the inventory.")
    runs = ctx.get("runs") or []
    found = rules.health(jobs, runs, time.time())
    ctx.put("findings", found)
    checks = []
    worst = {}
    for f in found:
        worst.setdefault(f["job_id"], []).append(f)
    for j in jobs:
        fs = worst.get(j["id"], [])
        st = "fail" if any(f["severity"] == "high" for f in fs) else "warn" if fs else "pass"
        checks.append({"name": j["id"], "label": f"{j['name']} ({j['tool_label']})", "status": st, "measured": f"{len(fs)} finding(s)" if fs else "healthy",
                       "expected": "", "detail": "; ".join(f["issue"] for f in fs)[:400] or "runs on time, no password in its definition, used",
                       "evidence": ctx.evidence(f"Health of {j['name']}", {"job": {k: j.get(k) for k in ("id", "name", "schedule", "enabled", "owner", "sources", "target", "secrets")},
                                                                         "findings": fs, "runs": [r for r in runs if r["job"].upper() == j["name"].upper()][-30:]}, kind="health", ok=not fs)})
    dic = dictionary(ctx) if warehouse(ctx) else {}
    if dic:
        refs = sorted({t for j in jobs for t in ([j["target"]] if j.get("target") and "*" not in j["target"] else []) + j["sources"] if "." in t and not t.startswith("DBO.")})
        checks.append(ctx.proof("references_real", label="Every table a job reads or loads exists in the warehouse", refs=refs, known=list(dic)))
    n = rules.decide(jobs, found)
    ctx.put("decide", n)
    record_lineage(ctx, jobs)
    hi = sum(1 for f in found if f["severity"] == "high")
    return {"summary": f"{len(jobs)} job(s) checked: {len(found)} finding(s), {hi} high" + (" — and every table checked against the warehouse's dictionary" if dic else "") + ".",
            "counts": {"jobs": len(jobs), "findings": len(found), "high": hi}, "data": {"checks": checks}}


def a_findings(ctx: wb.Ctx) -> dict:
    have = {r["id"]: r for r in ctx.records("findings")}
    recs = [{**f, **({"decision": have[f["id"]].get("decision"), "severity": have[f["id"]].get("severity")} if f["id"] in have else {})} for f in ctx.get("findings") or []]
    hi = sum(1 for r in recs if r["severity"] == "high")
    return {"summary": (f"{len(recs)} finding(s), {hi} high — keep what matters, ignore what does not." if recs else "No issues: every job runs on time and is used."),
            "counts": {"findings": len(recs), "high": hi}, "records": recs, "items": [f"{r['job']}: {r['issue']}" for r in recs[:6]],
            "data": {"columns": ["Job", "Tool", "Issue", "Measured", "Severity"], "rows": [[r["job"], r["tool"], r["issue"], r["measured"], r["severity"]] for r in recs]}}


FINDINGS_EDIT = wb.Edit(columns=[wb.Column("decision", "Decision", "select", options=(("keep", "Keep"), ("ignore", "Ignore"))),
                                 wb.Column("severity", "Severity", "select", options=("high", "medium", "low")), wb.Column("job", "Job", readonly=True),
                                 wb.Column("issue", "Issue", readonly=True)], add=False, remove=False, label="finding")


def a_estimate(ctx: wb.Ctx) -> dict:
    kept = [f for f in ctx.records("findings") if f.get("decision") != "ignore"]
    dec = ctx.get("decide") or []
    fail = {f["job"] for f in kept if f["issue_kind"] in ("failing", "secret")}
    waves = [("Wave 1 — fix what fails or exposes a password", [d for d in dec if d["job"] in fail and d["decision"] == "keep"], "fix a failing job"),
             ("Wave 2 — convert by rules", [d for d in dec if d["decision"] == "keep" and d["route_kind"] == "rules" and d["job"] not in fail], "review a rules conversion"),
             ("Wave 3 — convert with Relay's agent", [d for d in dec if d["decision"] == "keep" and d["route_kind"] == "agent" and d["job"] not in fail], "review an agent conversion"),
             ("Retire or merge", [d for d in dec if d["decision"] in ("retire", "merge")], "retire or merge a job")]
    items, total = [], 0.0
    for title, ds, what in waves:
        if not ds:
            continue
        m = len(ds) * MINUTES[what]
        total += m
        items.append({"title": title, "detail": ", ".join(d["job"] for d in ds[:12]) + (f" and {len(ds) - 12} more" if len(ds) > 12 else ""), "effort": _hours(m) + _cost(m / 60)})
    assumptions = "; ".join(f"{v} min to {k}" for k, v in MINUTES.items())
    ctx.output("assessment.md", f"# Assessment: {ctx.title}\n\n" + "\n".join(f"## {i['title']}\n\n{i['detail']}\n\nEffort: {i['effort']}\n" for i in items)
               + f"\nAssumptions: {assumptions}.\n", label="Assessment (Markdown)")
    ctx.output("decisions.json", json.dumps(dec, indent=1), label="Keep / merge / retire, with the reasons (JSON)")
    return {"summary": f"{len(items)} wave(s), about {_hours(total)} of a person's time" + _cost(total / 60) + ".", "counts": {"waves": len(items), "hours": round(total / 60, 1)},
            "data": {"items": items, "total": _hours(total), "note": f"Assumptions: {assumptions}." + ("" if registry.brand().get("hourly_rate") else " Set an hourly rate under Admin › Branding to see the cost.")}}


# ================================================================== Develop: a new pipeline as a dbt model

def _sources_named(ctx: wb.Ctx) -> list[dict]:
    want = [x.strip() for x in (ctx.scope.get("objects") or "").splitlines() if x.strip()]
    out = []
    wh = warehouse(ctx)
    if wh and want:
        objs = [o["object"] for o in connectors.browse(wh)[:3000]]
        for w in want:
            hit = next((o for o in objs if o.upper() == w.upper() or o.upper().endswith("." + w.upper())), None)
            if not hit:
                raise wb.StepFailed(f"{w} is not a table {wh['name']} shows.")
            out.append({"name": hit.upper(), "ref": {"source": "connection", "connection": wh["id"], "object": hit}})
    for f in ctx.files((".csv", ".parquet")):
        out.append({"name": "UPLOAD." + re.sub(r"\W+", "_", Path(f["name"]).stem).upper(), "ref": {"source": "file", "item": ctx.id, "file": f["table"]}})
    return out


def d_describe(ctx: wb.Ctx) -> dict:
    srcs = _sources_named(ctx)
    if not srcs:
        raise wb.StepFailed("Name the source tables (one per line) with a warehouse connection, or upload CSV / Parquet files.")
    rows = []
    for s in srcs:
        r = None
        try:
            r = ctx.reader(s["ref"])
            cols = r.columns()
            s["columns"] = [{"name": c["name"].upper(), "kind": c["kind"]} for c in cols]
            s["rows"] = r.count()
            rows.append([s["name"], s["rows"], len(cols), ", ".join(c["name"] for c in cols[:10])])
        finally:
            wb._close(r)
    ctx.put("sources", srcs)
    return {"summary": f"{len(srcs)} source table(s) read.", "counts": {"sources": len(srcs)}, "data": {"columns": ["Source", "Rows", "Columns", "First columns"], "rows": rows}}


def d_shape(ctx: wb.Ctx) -> dict:
    srcs = ctx.get("sources") or []
    have = ctx.records(ctx.step_id)
    if have:
        recs = have
    else:
        recs, seen = [], set()
        base = srcs[0]
        keys = [c["name"] for c in base["columns"] if re.search(r"(_ID|_KEY|_NO|_CODE)$", c["name"])][:2]
        for i, s in enumerate(srcs):
            for c in s["columns"]:
                if c["name"] in seen or c["name"] in rules.TECH:
                    continue
                seen.add(c["name"])
                recs.append({"id": f"m-{i}-{c['name'].lower()}", "source": s["name"], "from": c["name"], "to": c["name"], "expression": "", "include": True,
                             "key": c["name"] in keys and i == 0, "kind": c["kind"]})
    joins = _joins(srcs)
    ctx.put("joins", joins)
    return {"summary": f"{sum(1 for r in recs if r.get('include'))} column(s) mapped from {len(srcs)} source(s)" + (f", joined on {', '.join(j['on'] for j in joins)}" if joins else "")
            + ". Rename, drop or derive columns (an expression in SQL), mark the key, then confirm the design.", "records": recs, "counts": {"columns": len(recs), "sources": len(srcs)},
            "data": {"pairs": [{"from": f"{r['source']}.{r['from']}", "to": r["to"] if r.get("include") else "(dropped)", "rule": r.get("expression") or ("key" if r.get("key") else "copy"),
                                "status": "key" if r.get("key") else "ok"} for r in recs]}}


def _joins(srcs: list[dict]) -> list[dict]:
    if len(srcs) < 2:
        return []
    base = {c["name"] for c in srcs[0]["columns"]}
    out = []
    for i, s in enumerate(srcs[1:], 1):
        common = [c["name"] for c in s["columns"] if c["name"] in base and re.search(r"(_ID|_KEY|_NO|_CODE)$", c["name"])]
        if common:
            out.append({"source": s["name"], "alias": f"s{i}", "on": common[0]})
    return out


def _validate_mapping(recs: list[dict], ctx: wb.Ctx) -> list[str]:
    import sqlglot
    srcs = {s["name"]: {c["name"] for c in s["columns"]} for s in ctx.get("sources") or []}
    allcols = set().union(*srcs.values()) if srcs else set()
    probs, names = [], {}
    for r in recs:
        if not r.get("include"):
            continue
        to = (r.get("to") or "").strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", to):
            probs.append(f"{r.get('from')}: the target column needs a plain name (letters, digits, _)")
        names[to.upper()] = names.get(to.upper(), 0) + 1
        ex = (r.get("expression") or "").strip()
        if ex:
            try:
                tree = sqlglot.parse_one(ex, read="duckdb")
                used = {c.name.upper() for c in tree.find_all(sqlglot.exp.Column)}
                bad = sorted(used - allcols)
                if bad:
                    probs.append(f"{to}: {', '.join(bad)} is not a column of the sources")
            except sqlglot.errors.ParseError as e:
                probs.append(f"{to}: the expression does not parse as SQL ({str(e).splitlines()[0][:80]})")
        elif (r.get("from") or "").upper() not in srcs.get(r.get("source"), allcols):
            probs.append(f"{to}: {r.get('from')} is not a column of {r.get('source')}")
    probs += [f"{n}: two columns have this name" for n, k in names.items() if k > 1]
    if not any(r.get("key") and r.get("include") for r in recs):
        probs.append("Mark at least one key column (it is tested unique and not null)")
    return probs


MAP_EDIT = wb.Edit(columns=[wb.Column("include", "Include", "bool"), wb.Column("from", "From", readonly=True), wb.Column("to", "To (target column)"),
                            wb.Column("expression", "Expression (SQL, optional)", help="e.g. ROUND(QTY * UNIT_PRICE, 2) — only the sources' columns"),
                            wb.Column("key", "Key", "bool"), wb.Column("source", "Source", readonly=True)], add=True, remove=True, validate=_validate_mapping, label="column")


def _develop_sql(ctx: wb.Ctx) -> tuple[str, list[str], list[str]]:
    srcs = ctx.get("sources") or []
    recs = [r for r in ctx.records("shape") if r.get("include")]
    alias = {s["name"]: f"s{i}" for i, s in enumerate(srcs)}
    sel = []
    for r in recs:
        ex = (r.get("expression") or "").strip()
        sel.append(f"{ex} AS {r['to'].upper()}" if ex else f"{alias.get(r['source'], 's0')}.{r['from']} AS {r['to'].upper()}")
    frm = f"{srcs[0]['name']} s0" if srcs else ""
    for j in ctx.get("joins") or []:
        frm += f"\nLEFT JOIN {j['source']} {j['alias']} ON {j['alias']}.{j['on']} = s0.{j['on']}"
    keys = [r["to"].upper() for r in recs if r.get("key")]
    return "SELECT " + ",\n       ".join(sel) + "\nFROM " + frm, keys, [s["name"] for s in srcs]


def d_build(ctx: wb.Ctx) -> dict:
    sql, keys, inputs = _develop_sql(ctx)
    name = rules.model_name(ctx.scope.get("target") or ctx.title)
    dialect = ctx.scope.get("dialect") or "snowflake"
    conv = {"sql": sql, "inputs": inputs, "columns": [s.rsplit(" AS ", 1)[1] for s in sql.split("\nFROM")[0][7:].split(",\n       ")], "materialized": "table", "unique_key": keys, "target": f"DW.{name.upper()}"}
    j = {"name": name.upper(), "tool_label": "Relay", "kind": "pipeline", "description": ctx.brief[:300], "target": conv["target"]}
    path, text = rules.dbt_model(conv, j, {}, dialect)
    schema, src = rules.dbt_yaml([(j, conv)])
    ctx.output(path.replace("/", "__"), text, label=f"dbt model {path}")
    ctx.output("schema.yml", schema, label="dbt tests (schema.yml)")
    ctx.output("sources.yml", src, label="dbt sources (sources.yml)")
    ctx.put("model", {"name": name, "sql": sql, "keys": keys, "inputs": inputs, "path": path, "dialect": dialect})
    return {"summary": f"dbt model {name} written in {dict(DIALECTS).get(dialect, dialect)} SQL with its tests (unique and not null on {', '.join(keys)}) and sources.",
            "counts": {"files": 3, "columns": len(conv["columns"])}, "data": {"text": text}}


DATE_RX = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TS_RX = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(\.\d+)?$")


def _typed(rows: list[dict], cols: list[str]) -> list[dict]:
    """Dates and timestamps that arrived as text (a REST API's JSON) back as dates, as the warehouse holds them."""
    import datetime as dt
    conv = {}
    for k in cols:
        vals = [r.get(k) for r in rows if r.get(k) not in (None, "")]
        if vals and all(isinstance(v, str) and DATE_RX.match(v) for v in vals):
            conv[k] = lambda v: dt.date.fromisoformat(v) if isinstance(v, str) and v else None
        elif vals and all(isinstance(v, str) and TS_RX.match(v) for v in vals):
            conv[k] = lambda v: dt.datetime.fromisoformat(v.replace(" ", "T")) if isinstance(v, str) and v else None
    if not conv:
        return rows
    return [{k: (conv[k](v) if k in conv else v) for k, v in r.items()} for r in rows]


def _duck(ctx: wb.Ctx, tables: dict[str, list[dict]]):
    import duckdb
    import pyarrow as pa
    con = duckdb.connect()
    for t, rows in tables.items():
        sch, tab = t.split(".", 1) if "." in t else ("main", t)
        con.execute(f'CREATE SCHEMA IF NOT EXISTS "{sch}"')
        cols = list(dict.fromkeys(k for r in rows for k in r)) or ["EMPTY"]
        rows = _typed([{k: _w1._cell(r.get(k)) for k in cols} for r in rows], cols)
        tbl = pa.Table.from_pylist(rows) if rows else pa.table({c: pa.array([], pa.string()) for c in cols})
        con.register("_t", tbl)
        con.execute(f'CREATE OR REPLACE TABLE "{sch}"."{tab}" AS SELECT * FROM _t')
        con.unregister("_t")
    return con


def _rows_of(ctx: wb.Ctx, src: dict) -> list[dict]:
    if src["ref"]["source"] == "connection":
        c = ctx.connection(src["ref"]["connection"])
        return _w1.sql_rows(ctx, c["id"], f"SELECT * FROM {connectors.quote(c['kind'], src['ref']['object'])}")
    r = ctx.reader(src["ref"])
    try:
        return r.run(f"SELECT * FROM {wb.table_sql(r)}")
    finally:
        wb._close(r)


def d_prove(ctx: wb.Ctx) -> dict:
    m = ctx.get("model") or {}
    srcs = ctx.get("sources") or []
    con = _duck(ctx, {s["name"]: _rows_of(ctx, s) for s in srcs})
    try:
        out = [dict(zip([d[0] for d in con.description], r)) for r in con.execute(m["sql"]).fetchall()]
    except Exception as e:  # noqa: BLE001 - DuckDB's own message, for the person
        raise wb.StepFailed(f"The model does not run on the copy: {str(e).splitlines()[0][:300]}") from e
    finally:
        pass
    f_new = _w1.extract_parquet(ctx, out, f"x_{m['name']}_relay")
    f_src = _w1.extract_parquet(ctx, _rows_of(ctx, srcs[0]), f"x_{m['name']}_source")
    tests = []
    for k in m["keys"]:
        vals = [r.get(k) for r in out]
        tests.append({"name": f"not_null({k})", "status": "pass" if all(v is not None for v in vals) else "fail"})
        tests.append({"name": f"unique({k})" if len(m["keys"]) == 1 else f"unique({', '.join(m['keys'])})",
                      "status": "pass" if len({tuple(r.get(x) for x in m["keys"]) for r in out}) == len(out) else "fail"})
    checks = [ctx.proof("tests_run", label="dbt tests on the model's output (keys unique and not null)", results=tests[:2 if len(m["keys"]) > 1 else len(tests)])]
    if not ctx.get("joins"):
        checks.append(ctx.proof("row_count", label="One row out per row in", source={"source": "file", "file": f_src}, target={"source": "file", "file": f_new}))
    checks.append(ctx.proof("references_real", label="Every source column the model uses exists", refs=[r["from"] for r in ctx.records("shape") if r.get("include") and not r.get("expression")],
                            known=[c["name"] for s in srcs for c in s["columns"]]))
    con.close()
    bad = [c for c in checks if c["status"] == "fail"]
    return {"summary": f"The model ran on a copy of the sources: {len(out)} row(s); {len(checks) - len(bad)} of {len(checks)} proof(s) pass.", "counts": {"rows": len(out), "failing": len(bad)},
            "data": {"checks": checks}, "items": [f"{c['label']}: {c['detail']}" for c in bad]}


def d_ship(ctx: wb.Ctx) -> dict:
    m = ctx.get("model") or {}
    dbt = next((c for c in ctx.connections() if c["kind"] == "dbt_cloud"), None)
    cad = ctx.scope.get("cadence") or {"every": "day", "at": "05:00", "tz": "UTC"}
    approver = db.user(ctx.st.get("approver") or "") or {}
    return {"summary": f"Go live: model {m.get('name')} — {'a dbt Cloud job created on ' + dbt['name'] if dbt else 'the dbt files handed over for your repository'}, {_w1.lc(wb.schedule_text(cad))}.",
            "data": {"items": [{"title": "The model", "detail": f"{m.get('path')} ({m.get('dialect')}), tested unique and not null on {', '.join(m.get('keys') or [])}"},
                               {"title": "Where it runs", "detail": f"dbt Cloud job on {dbt['name']} (a write that waits for its own approval)" if dbt else "no dbt Cloud connection: the files are in the outputs"},
                               {"title": "Named approval", "detail": approver.get("name") or "the owner of this work item"}]}}


def _cron(cad: dict) -> str:
    hh, mm = (cad.get("at") or "05:00").split(":")
    return {"hour": f"{int(mm)} * * * *", "week": f"{int(mm)} {int(hh)} * * {(int(cad.get('weekday') or 0) + 1) % 7}"}.get(cad.get("every"), f"{int(mm)} {int(hh)} * * *")


def d_run(ctx: wb.Ctx) -> dict:
    m = ctx.get("model") or {}
    dbt = next((c for c in ctx.connections() if c["kind"] == "dbt_cloud"), None)
    jn = ctx.lineage_node("job", SYSTEM, f"dbt model {m.get('name')}", label=f"dbt model {m.get('name')} (Relay)", properties={"path": m.get("path")})
    for t in m.get("inputs") or []:
        ctx.lineage_edge(ctx.lineage_node("table", "warehouse", t, label=t, own=False), jn, "reads")
    ctx.lineage_edge(jn, ctx.lineage_node("table", "warehouse", f"DW.{(m.get('name') or 'model').upper()}", label=f"DW.{(m.get('name') or 'model').upper()}", own=False), "writes")
    if dbt:
        envs = ctx.scope.get("environment_id") or "3002"
        cp = ctx.request_write(dbt["id"], "job", {"op": "create_job", "job": {"name": f"Relay: {m.get('name')}", "environment_id": int(envs) if str(envs).isdigit() else envs,
                                                                             "execute_steps": [f"dbt build --select {m.get('name')}"], "schedule": {"cron": _cron(ctx.scope.get('cadence') or {})},
                                                                             "account_id": _w1.cfg(dbt, "account_id"), "project_id": ctx.scope.get("project_id") or None}},
                               f"Create the dbt Cloud job for {m.get('name')}")
        return {"summary": f"The dbt Cloud job waits for its write approval in the Validation queue ({cp['id']}); nothing is created until a person accepts it.",
                "data": {"href": "#/validate", "label": "Open the Validation queue", "text": f"Write: create the job “Relay: {m.get('name')}”"}}
    return {"summary": "No dbt Cloud connection: the model, its tests and its sources are in the outputs — commit them to your dbt repository (AI SDLC can open the pull request).",
            "data": {"href": f"#/m/{MODULE}/i/{ctx.id}", "label": "The outputs", "text": m.get("path") or ""}}


# ================================================================== Fix / change

def c_request(ctx: wb.Ctx) -> dict:
    name = (ctx.scope.get("job") or "").strip()
    e = estate(ctx, days=14)
    ctx.put("jobs", e["jobs"])
    ctx.put("runs", e["runs"][-2000:])
    j = next((x for x in e["jobs"] if x["name"].upper() == name.upper() or x["native"] == name or x["name"].upper().endswith(name.upper())), None) if name else None
    if not j:
        failing = [x["job"] for x in rules.health(e["jobs"], e["runs"], time.time()) if x["issue_kind"] == "failing"]
        raise wb.StepFailed(f"Name the job to fix ({'failing now: ' + ', '.join(failing[:6]) if failing else 'none of the jobs fails now'}).")
    ctx.put("job", j["id"])
    rs = [r for r in e["runs"] if r["job"].upper() == j["name"].upper()]
    return {"summary": f"{j['name']} ({j['tool_label']} {j['kind']}): {len(rs)} run(s) in 14 days, {sum(1 for r in rs if r['status'] == 'failed')} failed.",
            "counts": {"runs": len(rs), "failed": sum(1 for r in rs if r["status"] == "failed")},
            "data": {"text": (ctx.brief or "(no request text)") + f"\n\nReads: {', '.join(j['sources']) or '—'}\nLoads: {j.get('target') or '—'}\nSchedule: {j.get('schedule') or '—'}"}}


def c_diagnose(ctx: wb.Ctx) -> dict:
    j = _job(ctx, ctx.get("job"))
    rs = [r for r in ctx.get("runs") or [] if r["job"].upper() == j["name"].upper()]
    last = next((r for r in reversed(rs) if r["status"] == "failed"), None)
    if not last:
        return {"summary": f"{j['name']} has not failed in 14 days: nothing to diagnose — close the item or describe the change in the brief.", "ok": False,
                "data": {"checks": [{"name": "runs", "label": "Recent runs", "status": "pass", "detail": f"{len(rs)} run(s), none failed"}]}}
    dic = dictionary(ctx)
    learned = db.one("SELECT * FROM pipelines_fixes WHERE tool = ? AND old = ? ORDER BY created DESC LIMIT 1", (j["tool"], (rules.diagnose(last["error"])).get("column") or "")) if last.get("error") else None
    d = rules.diagnose(last.get("error") or "", dic, j["sources"])
    if d["cause"] == "schema" and not d.get("replacement") and learned:
        d.update(replacement=learned["new"], why=f"the same rename was fixed before ({learned['job']}): {learned['old']} → {learned['new']}")
    ctx.put("diagnosis", d)
    checks = [{"name": "cause", "label": f"Cause: {d['cause'].replace('_', ' ')}", "status": "fail", "measured": d.get("column") or "", "expected": d.get("replacement") or "",
               "detail": d["why"], "evidence": ctx.evidence("The failing run", {"run": last, "diagnosis": d}, kind="diagnosis", ok=False)}]
    if d["cause"] == "schema" and dic:
        cols = dic.get(d.get("table") or (j["sources"][0] if j["sources"] else ""), [])
        checks.append(ctx.proof("references_real", label="The column the job reads, in the source table now", refs=[d.get("column") or ""], known=cols))
    return {"summary": f"{j['name']} fails because {d['why']}." + (f" Proposed: read {d['replacement']} instead of {d['column']}." if d.get("replacement") else ""),
            "counts": {"failed runs": sum(1 for r in rs if r["status"] == "failed")}, "data": {"checks": checks},
            "items": [f"Error: {(last.get('error') or '')[:200]}", f"Cause: {d['why']}"]}


def _definition(ctx: wb.Ctx, j: dict) -> dict:
    """The job's current definition, where the tool lets Relay change it: an ADF data flow, an IICS mapping task's
    source query; anything else is changed in the tool (or its repository) by a person."""
    c = ctx.connection(j["where"]) if j.get("where") and j["where"] != "upload" else None
    if c and c["kind"] == "adf" and (j.get("logic") or {}).get("dataflow"):
        df = _w1.ADF_.item(c, "dataflows", j["logic"]["dataflow"])
        return {"kind": "adf_dataflow", "connection": c["id"], "name": df["name"], "properties": df.get("properties") or {}, "text": "\n".join(((df.get("properties") or {}).get("typeProperties") or {}).get("scriptLines") or [])}
    if c and c["kind"] == "iics":
        t = next((x for x in _w1.IICS_.tasks(c) if x["id"] == j["native"]), None)
        if t:
            q = next((p for p in t.get("parameters") or [] if p.get("name") == "$src_query$"), {})
            return {"kind": "iics_task", "connection": c["id"], "name": t["id"], "task": t, "text": q.get("text") or q.get("value") or ""}
    return {"kind": "elsewhere", "connection": c["id"] if c else None, "name": j["name"], "text": ""}


def c_fix(ctx: wb.Ctx) -> dict:
    j = _job(ctx, ctx.get("job"))
    d = ctx.get("diagnosis") or {}
    have = ctx.records(ctx.step_id)
    defn = _definition(ctx, j)
    ctx.put("definition", {k: v for k, v in defn.items() if k != "task"} | ({"task": defn["task"]} if defn.get("task") else {}))
    if have:
        recs = have
    elif d.get("cause") == "schema" and d.get("column"):
        recs = [{"id": "f-1", "change": "rename", "old": d["column"], "new": d.get("replacement") or "", "where": defn["kind"].replace("_", " "), "note": d["why"]}]
    else:
        recs = [{"id": "f-1", "change": {"late_file": "wait for the file", "transient": "retry", "signin": "renew the sign-in"}.get(d.get("cause"), "describe the change"),
                 "old": "", "new": "", "where": defn["kind"].replace("_", " "), "note": d.get("why") or ""}]
    preview = ""
    for r in recs:
        if r.get("change") == "rename" and r.get("old") and r.get("new") and defn.get("text"):
            preview, n = rules.patch_text(defn["text"], r["old"], r["new"])
            r["hits"] = n
    return {"summary": ("Proposed by rules: " + "; ".join(f"{r['change']} {r.get('old') or ''} → {r.get('new') or ''}".strip() for r in recs) + ". Change it if needed, then confirm."),
            "records": recs, "data": {"columns": ["Change", "Old", "New", "Where", "Why"], "rows": [[r["change"], r.get("old"), r.get("new"), r.get("where"), r.get("note")] for r in recs]},
            "items": [preview[:300]] if preview else []}


def _validate_fix(recs: list[dict], ctx: wb.Ctx) -> list[str]:
    out = []
    for r in recs:
        if r.get("change") == "rename" and not (r.get("old") and r.get("new")):
            out.append("A rename needs the old and the new column name")
        if r.get("change") == "rename" and r.get("new") and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$#]*", r["new"]):
            out.append(f"{r['new']} is not a column name")
    return out


FIX_EDIT = wb.Edit(columns=[wb.Column("change", "Change", "select", options=(("rename", "Rename a column"), ("wait for the file", "Wait for the file"), ("retry", "Retry"),
                                                                         ("renew the sign-in", "Renew the sign-in"), ("describe the change", "Something else"))),
                            wb.Column("old", "Old"), wb.Column("new", "New"), wb.Column("note", "Note", "longtext"), wb.Column("where", "Where", readonly=True)],
                   add=False, remove=False, validate=_validate_fix, label="change")


def c_prove(ctx: wb.Ctx) -> dict:
    j = _job(ctx, ctx.get("job"))
    defn = ctx.get("definition") or {}
    recs = ctx.records("fix")
    text, n = defn.get("text") or "", 0
    for r in recs:
        if r.get("change") == "rename":
            text, k = rules.patch_text(text, r["old"], r["new"])
            n += k
    ctx.put("patched", text)
    checks = []
    renames = [r for r in recs if r.get("change") == "rename"]
    if renames and defn.get("text"):
        left = [r["old"] for r in renames if re.search(rf"(?<![\w]){re.escape(r['old'])}(?![\w])", text, re.I)]
        checks.append({"name": "patched", "label": "The definition no longer reads the old column", "status": "fail" if left else "pass", "measured": f"{n} reference(s) changed",
                       "expected": "none left", "detail": f"still reads {', '.join(left)}" if left else f"{n} reference(s) renamed",
                       "evidence": ctx.evidence("The definition, before and after", {"before": defn.get("text"), "after": text}, kind="diff", ok=not left)})
        dic = dictionary(ctx)
        if dic:
            src = (ctx.get("diagnosis") or {}).get("table") or (j["sources"][0] if j["sources"] else "")
            checks.append(ctx.proof("references_real", label=f"Every renamed column exists in {src}", refs=[r["new"].upper() for r in renames], known=dic.get(src, [])))
        ctx.output(f"{rules.model_name(j['name'])}-fixed.txt", text, label="The changed definition")
    else:
        checks.append({"name": "manual", "label": "A change Relay cannot make in this tool", "status": "skip", "detail": f"{j['tool_label']}: a person makes it there; Approve records it"})
    bad = [c for c in checks if c["status"] == "fail"]
    return {"summary": f"{len(checks) - len(bad)} of {len(checks)} check(s) pass on the changed definition.", "counts": {"checks": len(checks), "failing": len(bad)}, "data": {"checks": checks}}


def c_approve(ctx: wb.Ctx) -> dict:
    j = _job(ctx, ctx.get("job"))
    defn = ctx.get("definition") or {}
    return {"summary": f"Release the change to {j['name']}: " + "; ".join(f"{r['change']} {r.get('old') or ''} → {r.get('new') or ''}".strip() for r in ctx.records("fix")) + ".",
            "data": {"items": [{"title": "Where it is written", "detail": {"adf_dataflow": f"the ADF data flow {defn.get('name')} (its own write approval)", "iics_task": "the IICS mapping task's source query (its own write approval)"}.get(defn.get("kind"), "in the tool, by a person")},
                               {"title": "Then", "detail": "the next run uses it; Run & support watches the job"}]}}


def c_learn(ctx: wb.Ctx) -> dict:
    j = _job(ctx, ctx.get("job"))
    defn = ctx.get("definition") or {}
    text = ctx.get("patched") or ""
    handed = None
    if defn.get("kind") == "adf_dataflow" and text:
        props = json.loads(json.dumps(defn["properties"]))
        props.setdefault("typeProperties", {})["scriptLines"] = text.split("\n")
        handed = ctx.request_write(defn["connection"], f"dataflows/{defn['name']}", {"op": "put_dataflow", "name": defn["name"], "properties": props}, f"Change the ADF data flow {defn['name']}")
    elif defn.get("kind") == "iics_task" and text:
        t = dict(defn["task"])
        t["parameters"] = [{**p, "text": text} if p.get("name") == "$src_query$" else p for p in t.get("parameters") or []]
        handed = ctx.request_write(defn["connection"], f"mttask/{defn['name']}", {"op": "update_task", "id": defn["name"], "task": {k: t[k] for k in ("name", "description", "parameters") if k in t}},
                                   f"Change the IICS mapping task {j['name']}")
    for r in ctx.records("fix"):
        if r.get("change") == "rename":
            db.run("INSERT OR REPLACE INTO pipelines_fixes (id, signature, tool, job, old, new, item, by, created) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                   (f"fx-{_w1.slug(j['tool'] + '-' + r['old'] + '-' + r['new'])}", f"schema:{r['old'].upper()}", j["tool"], j["name"], r["old"].upper(), r["new"].upper(), ctx.id, ctx.who or ctx.owner, time.time()))
    db.audit("pipelines.fix.learned", ctx.id, {"job": j["name"], "changes": ctx.records("fix")}, ctx.who or ctx.owner)
    return {"summary": ("The change waits for its write approval in the Validation queue; once accepted the tool runs the fixed definition. " if handed else "Recorded; a person makes the change in the tool. ")
            + "The fix is kept as a rule for the next failure like it.", "counts": {"rules learned": len([r for r in ctx.records("fix") if r.get("change") == "rename"])},
            "data": {"href": "#/validate" if handed else f"#/m/{MODULE}/run", "label": "Open the Validation queue" if handed else "Run & support", "text": f"Write approval {handed['id']}" if handed else ""}}


# ================================================================== Migrate

def m_discover(ctx: wb.Ctx) -> dict:
    out = a_inventory(ctx)
    out["summary"] = out["summary"].replace(" — untick what is out of scope.", ".")
    out.pop("records", None)
    return out


def m_decide(ctx: wb.Ctx) -> dict:
    jobs = _jobs(ctx)
    found = rules.health(jobs, ctx.get("runs") or [], time.time())
    ctx.put("findings", found)
    have = {r["id"]: r for r in ctx.records(ctx.step_id)}
    recs = [{**d, **({k: have[d["id"]][k] for k in ("decision", "into") if k in have[d["id"]]} if d["id"] in have else {})} for d in rules.decide(jobs, found)]
    n = {k: sum(1 for r in recs if r["decision"] == k) for k in ("keep", "merge", "retire")}
    return {"summary": f"Keep {n['keep']}, merge {n['merge']}, retire {n['retire']} — each with its reason; {sum(1 for r in recs if r['route_kind'] == 'rules' and r['decision'] == 'keep')} ready to convert by rules.",
            "counts": n, "records": recs, "items": [f"{r['job']}: {r['decision']} — {r['why']}" for r in recs if r["decision"] != "keep"][:6],
            "data": {"columns": ["Job", "Tool", "Decision", "Why", "Conversion"], "rows": [[r["job"], r["tool"], r["decision"], r["why"], r["route"] if r["decision"] == "keep" else "—"] for r in recs]}}


DECIDE_EDIT = wb.Edit(columns=[wb.Column("decision", "Decision", "select", options=(("keep", "Keep"), ("merge", "Merge"), ("retire", "Retire"))),
                               wb.Column("into", "Merge into", help="the job that stays"), wb.Column("job", "Job", readonly=True), wb.Column("why", "Why", readonly=True),
                               wb.Column("route", "Conversion", readonly=True)], add=False, remove=False, validate=lambda recs, ctx: rules.validate_decisions(recs), label="job")


def _check_columns(conv: dict, dic: dict) -> list[dict]:
    """Columns the converted SQL reads that the warehouse's tables do not have (a renamed column), with the likely new name."""
    import sqlglot
    from sqlglot import exp
    out = []
    if not dic or not conv.get("sql"):
        return out
    try:
        tree = sqlglot.parse_one(conv["sql"], read="duckdb")
    except Exception:  # noqa: BLE001 - SQL the parser does not read is reported by the proof
        return out
    alias = {}
    for t in tree.find_all(exp.Table):
        full = f"{t.db}.{t.name}".upper() if t.db else t.name.upper()
        alias[(t.alias or t.name).upper()] = full
    for c in tree.find_all(exp.Column):
        tab = alias.get((c.table or "").upper())
        if tab and tab in dic and c.name.upper() not in dic[tab]:
            out.append({"table": tab, "column": c.name.upper(), "replacement": rules.renamed(c.name.upper(), dic[tab])})
    uniq = {(x["table"], x["column"]): x for x in out}
    return list(uniq.values())


def m_convert(ctx: wb.Ctx) -> dict:
    keep = {r["id"] for r in ctx.records("decide") if r.get("decision") == "keep"}
    jobs = [j for j in _jobs(ctx) if j["id"] in keep]
    dic = dictionary(ctx) if warehouse(ctx) else {}
    have = {r["id"]: r for r in ctx.records(ctx.step_id)}
    convs, recs = {}, []
    for j in jobs:
        prev = have.get(j["id"]) or {}
        if prev.get("origin") == "agent" and prev.get("sql"):
            cv = {"sql": prev["sql"], "inputs": prev.get("inputs") or [], "columns": prev.get("columns") or [], "materialized": prev.get("materialized") or "table",
                  "unique_key": prev.get("unique_key") or [], "problems": [], "notes": ["drafted by Relay's agent"], "route": "agent", "target": j.get("target")}
        else:
            cv = rules.convert(j, dic)
        if cv.get("sql") and cv.get("problems") == [] and "__p_" in cv["sql"]:
            cv["problems"].append("a parameter is left in the SQL")
        fixes = []
        for miss in _check_columns(cv, dic):
            if miss["replacement"]:
                cv["sql"], _ = rules.patch_text(cv["sql"], miss["column"], miss["replacement"])
                fixes.append(f"{miss['table']} has no {miss['column']}: {miss['replacement']} used instead (check it)")
            else:
                cv["problems"].append(f"{miss['table']} has no column {miss['column']}")
        cv.setdefault("target", j.get("target"))
        if prev.get("sql") and cv["sql"] and prev["sql"].strip() != cv["sql"].strip():      # a person's (or the agent's) edit survives a re-run
            cv = {**cv, "sql": prev["sql"], "problems": [], "notes": cv.get("notes", []) + ["edited by a person"]}
            fixes = []
        convs[j["id"]] = cv
        recs.append({"id": j["id"], "job": j["name"], "tool": j["tool_label"], "model": rules.model_name(j["name"]), "route": "rules" if cv["route"] == "rules" else "agent",
                     "status": "converted" if cv["sql"] else "needs Relay's agent", "problems": "; ".join(cv["problems"] + fixes)[:600], "sql": cv["sql"],
                     "inputs": cv["inputs"], "columns": cv["columns"], "materialized": cv["materialized"], "unique_key": cv["unique_key"], "target": cv.get("target") or j.get("target"),
                     "origin": prev.get("origin") or ("rules" if cv["sql"] else "")})
    ctx.put("conversions", {k: {kk: v for kk, v in cv.items()} for k, cv in convs.items()})
    _write_project(ctx, jobs, recs)
    done = [r for r in recs if r["sql"]]
    return {"summary": f"{len(done)} of {len(recs)} kept job(s) converted to dbt models" + (f"; {len(recs) - len(done)} wait for Relay's agent (Ask Relay to convert the rest)" if len(done) < len(recs) else "")
            + ".", "counts": {"converted": len(done), "agent": len(recs) - len(done)}, "records": recs,
            "data": {"columns": ["Job", "Tool", "dbt model", "How", "Status", "Problems"], "rows": [[r["job"], r["tool"], r["model"], r["route"], r["status"], r["problems"]] for r in recs]},
            "items": [f"{r['job']}: {r['problems']}" for r in recs if r["problems"]][:6]}


def _write_project(ctx: wb.Ctx, jobs: list[dict], recs: list[dict]) -> None:
    dialect = ctx.scope.get("dialect") or "snowflake"
    byid = {j["id"]: j for j in jobs}
    models = {r["target"].upper(): r["model"] for r in recs if r.get("sql") and r.get("target")}
    pairs = []
    for r in recs:
        if not r.get("sql"):
            continue
        cv = {"sql": r["sql"], "inputs": r["inputs"], "columns": r["columns"], "materialized": r["materialized"], "unique_key": r["unique_key"], "target": r["target"]}
        path, text = rules.dbt_model(cv, byid[r["id"]], {k: v for k, v in models.items() if k != (r["target"] or "").upper()}, dialect)
        ctx.output("dbt__" + path.replace("/", "__"), text, label=f"dbt {path}")
        pairs.append((byid[r["id"]], cv))
    if pairs:
        schema, src = rules.dbt_yaml(pairs)
        ctx.output("dbt__models__schema.yml", schema, label="dbt tests (schema.yml)")
        ctx.output("dbt__models__sources.yml", src, label="dbt sources (sources.yml)")
        ctx.output("dbt__dbt_project.yml", f"name: relay_migrated\nversion: '1.0'\nconfig-version: 2\nprofile: relay\nmodel-paths: [models]\n# converted by Relay from {', '.join(sorted({j['tool_label'] for j, _ in pairs}))}; target dialect {dialect}\n",
                   label="dbt_project.yml")


CONVERT_WORDS = """Read WORK.md, then convert.json in this folder: the ETL jobs no rule could convert, each with its tool, name,
the tables it reads and loads, the warehouse columns of those tables (`dictionary`) and its definition as the export holds
it. For each job write models/<model>.sql — ONE SELECT in DuckDB's SQL that produces the rows the job loads into its
target: the target's columns, in order, named as the target names them; read only the tables listed for the job, with
schema-qualified names (STAGE.STG_ORDERS); no INSERT, MERGE, CREATE or DELETE; no columns that are not in `dictionary`.
A Type 2 history (a conditional split or router on a row hash) becomes the current-state SELECT; say so in the first
line as a SQL comment. Then write convert_notes.yaml: `notes: {<model>: "one sentence on what you assumed"}`."""


def _convert_prompt(ctx: wb.Ctx) -> str:
    dic = dictionary(ctx) if warehouse(ctx) else {}
    todo = []
    for r in ctx.records(ctx.step_id):
        if r.get("sql"):
            continue
        j = _job(ctx, r["id"]) or {}
        tabs = [t for t in (j.get("sources") or []) + ([j["target"]] if j.get("target") else [])]
        todo.append({"model": r["model"], "job": j.get("name"), "tool": j.get("tool_label"), "reads": j.get("sources"), "loads": j.get("target"),
                     "dictionary": {t: dic.get(t, []) for t in tabs}, "definition": json.dumps(j.get("logic") or {}, default=str)[:12000]})
    (ctx.dir / "models").mkdir(exist_ok=True)
    (ctx.dir / "convert.json").write_text(json.dumps(todo, indent=1), encoding="utf-8")
    return CONVERT_WORDS


def _convert_check(ctx: wb.Ctx) -> list[str]:
    import sqlglot
    from sqlglot import exp
    out = []
    todo = json.loads((ctx.dir / "convert.json").read_text(encoding="utf-8"))
    for t in todo:
        p = ctx.dir / "models" / f"{t['model']}.sql"
        if not p.exists():
            out.append(f"models/{t['model']}.sql was not written")
            continue
        try:
            trees = [x for x in sqlglot.parse(p.read_text(encoding="utf-8"), read="duckdb") if x is not None]
        except sqlglot.errors.ParseError as e:
            out.append(f"{t['model']}.sql does not parse as DuckDB SQL: {str(e).splitlines()[0][:120]}")
            continue
        if len(trees) != 1 or not isinstance(trees[0], (exp.Select, exp.Union, exp.Subquery)):
            out.append(f"{t['model']}.sql must be exactly one SELECT")
            continue
        allowed = {x.upper() for x in (t.get("reads") or []) + [t.get("loads") or ""] if x}
        for tb in trees[0].find_all(exp.Table):
            full = f"{tb.db}.{tb.name}".upper() if tb.db else tb.name.upper()
            if full not in allowed and not any(a.endswith("." + full) for a in allowed):
                out.append(f"{t['model']}.sql reads {full}, which the job does not read")
        known = {c for cols in (t.get("dictionary") or {}).values() for c in cols}
        if known:
            bad = sorted({c.name.upper() for c in trees[0].find_all(exp.Column)} - known - {a.alias.upper() for a in trees[0].find_all(exp.Alias)})
            if bad:
                out.append(f"{t['model']}.sql uses column(s) the tables do not have: {', '.join(bad[:6])}")
    return out


def _convert_after(ctx: wb.Ctx, res: dict) -> dict:
    import sqlglot
    from sqlglot import exp
    todo = {t["model"]: t for t in json.loads((ctx.dir / "convert.json").read_text(encoding="utf-8"))}
    recs = ctx.records(ctx.step_id)
    n = 0
    for r in recs:
        t = todo.get(r["model"])
        if r.get("sql") or not t:
            continue
        sql = (ctx.dir / "models" / f"{r['model']}.sql").read_text(encoding="utf-8").strip().rstrip(";")
        tree = sqlglot.parse_one(sql, read="duckdb")
        r.update(sql=sql, origin="agent", route="agent", status="drafted by Relay — prove it", inputs=sorted({(f"{tb.db}.{tb.name}" if tb.db else tb.name).upper() for tb in tree.find_all(exp.Table)}),
                 columns=[e.alias_or_name.upper() for e in tree.expressions] if isinstance(tree, exp.Select) else [], problems="")
        n += 1
    ctx.evidence("Conversions drafted by Relay", {"models": list(todo), "summary": res.get("text") or ""}, kind="agent", ok=True)
    jobs = [j for j in _jobs(ctx) if j["id"] in {r["id"] for r in recs}]
    _write_project(ctx, jobs, recs)
    return {"summary": f"Relay drafted {n} model(s) — the proof runs them against the tables the legacy jobs load before anyone relies on them.", "records": recs,
            "data": {"columns": ["Job", "Tool", "dbt model", "How", "Status", "Problems"], "rows": [[r["job"], r["tool"], r["model"], r["route"], r["status"], r["problems"]] for r in recs]}}


CONVERT_EDIT = wb.Edit(columns=[wb.Column("sql", "Model SQL (DuckDB)", "longtext", help="one SELECT; the proof runs it on a copy of the warehouse tables"),
                                wb.Column("job", "Job", readonly=True), wb.Column("model", "dbt model", readonly=True), wb.Column("route", "How", readonly=True),
                                wb.Column("problems", "Problems", readonly=True)], add=False, remove=False, label="model")


def m_prove(ctx: wb.Ctx) -> dict:
    wh = warehouse(ctx)
    recs = [r for r in ctx.records("convert") if r.get("sql")]
    if not recs:
        raise wb.StepFailed("Nothing converted to prove yet.")
    if not wh:
        raise wb.StepFailed("Add the warehouse the jobs load (a connection) to prove the converted models against the tables they replace.")
    a = connectors.sdk.get(wh["kind"])
    checks, cache = [], {}

    def rows(t):
        if t not in cache:
            cache[t] = _w1.sql_rows(ctx, wh["id"], f"SELECT * FROM {connectors.quote(wh['kind'], t)}")
        return cache[t]
    known = {o["object"].upper() for o in a.list_objects(wh)} if hasattr(a, "list_objects") else set()
    uploads = {re.sub(r"\W+", "_", Path(f["name"]).stem).upper(): f for f in ctx.files((".csv", ".parquet"))}
    for r in recs:
        tgt = (r.get("target") or "").upper()
        missing = [t for t in r["inputs"] if t not in known and t.split(".")[-1] not in uploads]
        if missing:
            checks.append({"name": r["id"], "label": f"{r['job']} → {r['model']}", "status": "skip",
                           "detail": f"not compared: {', '.join(missing)} is not in {wh['name']} — upload an extract of it (CSV or Parquet named after the table) to prove this job"})
            continue
        try:
            con = _duck(ctx, {t: (rows(t) if t in known else _rows_of(ctx, {"ref": {"source": "file", "item": ctx.id, "file": uploads[t.split('.')[-1]]["table"]}})) for t in r["inputs"]})
            try:
                cur = con.execute(r["sql"])
                out = [dict(zip([d[0].upper() for d in cur.description], x)) for x in cur.fetchall()]
            finally:
                con.close()
        except wb.StepFailed as e:
            checks.append({"name": r["id"], "label": f"{r['job']} → {r['model']}", "status": "error", "detail": str(e)[:300]})
            continue
        except Exception as e:  # noqa: BLE001 - DuckDB's message, for the person
            checks.append({"name": r["id"], "label": f"{r['job']} → {r['model']}", "status": "fail", "detail": f"the model does not run: {str(e).splitlines()[0][:300]}",
                           "evidence": ctx.evidence(f"{r['model']} does not run", {"sql": r["sql"], "error": str(e)}, kind="proof", ok=False)})
            continue
        if not tgt or tgt not in known:
            checks.append({"name": r["id"], "label": f"{r['job']} → {r['model']}", "status": "skip", "detail": f"ran: {len(out)} row(s); the legacy target {tgt or '—'} is not in {wh['name']} to compare with"})
            continue
        legacy = [{k.upper(): v for k, v in x.items()} for x in rows(tgt)]
        common = [c for c in r["columns"] if c in (legacy[0] if legacy else {}) and c not in rules.TECH]
        f_old = _w1.extract_parquet(ctx, [{c: x.get(c) for c in common} for x in legacy], f"x_{r['model']}_legacy")
        f_new = _w1.extract_parquet(ctx, [{c: x.get(c) for c in common} for x in out], f"x_{r['model']}_relay")
        src, new = {"source": "file", "file": f_old}, {"source": "file", "file": f_new}
        keys = [k for k in r.get("unique_key") or [] if k in common] or common          # no key: every column (a row matches only an identical row)
        parts = [ctx.proof("row_count", source=src, target=new), ctx.proof("checksum", source=src, target=new, columns=common, tolerance_pct=0.001),
                 ctx.proof("sample_diff", source=src, target=new, keys=keys, n=50, columns=common)]
        bad = [p for p in parts if p["status"] == "fail"]
        checks.append({"name": r["id"], "label": f"{r['job']} → {r['model']}", "status": "fail" if bad else "pass", "measured": f"{len(parts) - len(bad)} of {len(parts)} agree",
                       "expected": "all agree", "detail": "; ".join(f"{p['label']}: {p['detail']}" for p in parts)[:700], "severity": "high",
                       "parts": [{k: p.get(k) for k in ("label", "status", "detail", "evidence")} for p in parts]})
    ok = sum(1 for c in checks if c["status"] == "pass")
    ctx.put("proof", {c["name"]: c["status"] for c in checks})
    return {"summary": f"{ok} of {len(checks)} converted job(s) produce exactly what the legacy job loads; {sum(1 for c in checks if c['status'] == 'fail')} differ (the evidence shows the rows).",
            "counts": {"proven": ok, "differ": sum(1 for c in checks if c["status"] == "fail"), "not compared": sum(1 for c in checks if c["status"] in ("skip", "error"))},
            "data": {"checks": checks}, "items": [f"{c['label']}: {c['detail'][:200]}" for c in checks if c["status"] != "pass"][:6]}


def m_handover(ctx: wb.Ctx) -> dict:
    proof = ctx.get("proof") or {}
    recs = ctx.records("convert")
    dec = ctx.records("decide")
    return {"summary": f"Hand-over: {sum(1 for v in proof.values() if v == 'pass')} proven model(s), {sum(1 for d in dec if d.get('decision') == 'retire')} job(s) to retire, "
                       f"{sum(1 for d in dec if d.get('decision') == 'merge')} to merge — the evidence pack holds every proof.",
            "data": {"items": [{"title": "dbt project", "detail": f"{sum(1 for r in recs if r.get('sql'))} model(s) with tests and sources, in the outputs"},
                               {"title": "Proven", "detail": ", ".join(r["model"] for r in recs if proof.get(r["id"]) == "pass") or "—"},
                               {"title": "Differences accepted", "detail": ", ".join(r["model"] for r in recs if proof.get(r["id"]) == "fail") or "—"},
                               {"title": "Owner sign-off", "detail": (db.user(ctx.st.get("approver") or "") or {}).get("name") or "the owner of this work item"}]}}


def m_run(ctx: wb.Ctx) -> dict:
    cad = ctx.scope.get("cadence") or {"every": "day", "at": "07:00", "tz": "UTC"}
    jobs = [j for j in _jobs(ctx) if j["id"] in {r["id"] for r in ctx.records("convert") if r.get("sql")}]
    record_lineage(ctx, jobs)
    for r in ctx.records("convert"):
        if r.get("sql"):
            mn = ctx.lineage_node("job", SYSTEM, f"dbt model {r['model']}", label=f"dbt model {r['model']} (converted)", properties={"from": r["job"]})
            if r.get("target"):
                ctx.lineage_edge(mn, ctx.lineage_node("table", (warehouse(ctx) or {}).get("kind") or "warehouse", r["target"], label=r["target"], own=False), "writes")
    api = [c["id"] for c in ctx.connections() if c["kind"] in API_KINDS]
    if not api:
        return {"summary": "The dbt project is in the outputs; connect the tool's API to watch the legacy jobs until cut-over (Run & support).",
                "data": {"href": f"#/m/{MODULE}/run", "label": "Run & support", "text": "no API connection to watch"}}
    item = wb.create(MODULE, "run", f"Run: {ctx.title}"[:160], who=ctx.owner, brief=f"Watches the estate migrated in {ctx.id} until cut-over.", connections=api,
                     scope={"schedule": cad}, visibility=(db.project(ctx.id) or {}).get("visibility") or "private", team_id=(db.project(ctx.id) or {}).get("team_id"), parent=ctx.id)
    return {"summary": f"A Run item watches the jobs {_w1.lc(wb.schedule_text(cad))} until cut-over.", "data": {"href": f"#/m/{MODULE}/i/{item['id']}", "label": "Open the Run item", "text": wb.schedule_text(cad)}}


# ================================================================== Run & support

def r_watch(ctx: wb.Ctx) -> dict:
    last = ctx.st.get("last_run") or (time.time() - 86400)
    e = estate(ctx, days=2)
    runs = [r for r in e["runs"] if (r.get("end") or r.get("start") or 0) >= last - 3600]
    ctx.put("jobs", e["jobs"])
    ctx.put("runs", runs)
    by = {}
    for r in sorted(runs, key=lambda r: r.get("start") or 0):
        by[r["job"]] = r
    checks = [{"name": f"run-{_w1.slug(k)}", "label": k, "status": "fail" if v["status"] == "failed" else "pass" if v["status"] == "succeeded" else "skip",
               "measured": v["status"], "detail": (v.get("error") or "")[:300]} for k, v in sorted(by.items())]
    f = sum(1 for c in checks if c["status"] == "fail")
    return {"summary": f"{len(runs)} run(s) since the last round: {len(by)} job(s), {f} failing now.", "counts": {"runs": len(runs), "jobs": len(by), "failing": f}, "data": {"checks": checks}}


def r_alert(ctx: wb.Ctx) -> dict:
    runs = ctx.get("runs") or []
    latest = {}
    for r in sorted(runs, key=lambda r: r.get("start") or 0):
        latest[r["job"]] = r
    brk = []
    for k, r in latest.items():
        if r["status"] != "failed":
            continue
        d = rules.diagnose(r.get("error") or "")
        brk.append({"id": f"b-{_w1.slug(k)}", "job": k, "tool": pr.TOOLS.get(r["tool"], r["tool"]), "cause": d["cause"], "why": d["why"], "route": d["route"] if d["route"] != "change" else "heal",
                    "error": (r.get("error") or "")[:400], "note": "", "failed": sum(1 for x in runs if x["job"] == k and x["status"] == "failed")})
    ctx.put("breaks", brk)
    if not brk:
        return {"summary": "Every job's latest run succeeded: nothing to alert.", "next": "report", "counts": {"breaks": 0}}
    return {"summary": f"{len(brk)} job(s) failing, grouped by cause: " + ", ".join(f"{c} {sum(1 for b in brk if b['cause'] == c)}" for c in sorted({b['cause'] for b in brk})) + ".",
            "counts": {"breaks": len(brk)}, "items": [f"{b['job']}: {b['why']}" for b in brk[:6]],
            "data": {"columns": ["Job", "Tool", "Likely cause", "Failed runs", "Error"], "rows": [[b["job"], b["tool"], b["why"], b["failed"], b["error"][:200]] for b in brk]}}


def r_fix(ctx: wb.Ctx) -> dict:
    have = {r["id"]: r for r in ctx.records(ctx.step_id)}
    recs = [{**b, **({k: have[b["id"]][k] for k in ("route", "note") if k in have[b["id"]]} if b["id"] in have else {})} for b in ctx.get("breaks") or []]
    return {"summary": f"{len(recs)} failing job(s): choose who fixes each — Self-healing, a ticket, or expected. Nothing goes out until you confirm.", "records": recs,
            "counts": {"self-healing": sum(1 for r in recs if r["route"] == "heal"), "tickets": sum(1 for r in recs if r["route"] == "ticket")},
            "data": {"columns": ["Job", "Likely cause", "Proposed route"], "rows": [[r["job"], r["why"], r["route"]] for r in recs]}}


RUNFIX_EDIT = wb.Edit(columns=[wb.Column("route", "Route", "select", options=(("heal", "Self-healing"), ("ticket", "Raise a ticket"), ("expected", "Expected — no action"), ("ignore", "Ignore this time"))),
                               wb.Column("note", "Note for whoever fixes it", "longtext"), wb.Column("job", "Job", readonly=True), wb.Column("why", "Likely cause", readonly=True)],
                      add=False, remove=False, label="failing job")


def r_approve(ctx: wb.Ctx) -> dict:
    rows, done = [], []
    for b in ctx.records("fix"):
        title = f"{b['job']} ({b['tool']}) fails: {b['cause'].replace('_', ' ')}"
        body = f"{b['error']}\n\nLikely cause: {b['why']}\n\n{('Note: ' + b['note']) if b.get('note') else ''}\nWork item: {wb.route_of(ctx.st)}"
        if b["route"] == "heal":
            h = ctx.heal(title, body, place=f"{b['job']} ({registry.BY_ID[MODULE]['short']})", signature=f"pipelines:{b['cause']}", subject={"job": b["job"]})
        elif b["route"] == "ticket":
            h = ctx.ticket(title, body, priority="P2" if b["cause"] in ("signin", "schema") else "P3", about=b["job"])
        else:
            h = {"kind": b["route"], "label": title, "status": "expected — recorded" if b["route"] == "expected" else "ignored this time"}
        done.append(h)
        rows.append([b["job"], {"heal": "Self-healing", "ticket": "Ticket", "expected": "Expected", "ignore": "Ignored"}[b["route"]], h.get("status"), h.get("case") or h.get("checkpoint") or h.get("output") or ""])
    return {"summary": f"{sum(1 for h in done if h['kind'] == 'heal')} to Self-healing, {sum(1 for h in done if h['kind'] == 'ticket')} ticket(s), "
                       f"{sum(1 for h in done if h['kind'] in ('expected', 'ignore'))} without action — as you approved.", "counts": {"hand-offs": len(done)},
            "data": {"columns": ["Job", "Route", "Status", "Reference"], "rows": rows}}


def r_report(ctx: wb.Ctx) -> dict:
    runs = ctx.get("runs") or []
    ok = sum(1 for r in runs if r["status"] == "succeeded")
    rate = round(100 * ok / len(runs), 1) if runs else None
    hist = [[time.strftime("%d %b %H:%M", time.gmtime(r["ended"])), (next((s for s in r["steps"] if s["id"] == "watch"), {}).get("counts") or {}).get("failing")] for r in (ctx.st.get("rounds") or [])[-11:]]
    hist.append([time.strftime("%d %b %H:%M", time.gmtime()), len(ctx.get("breaks") or [])])
    ctx.output(f"run-report-{time.strftime('%Y%m%d-%H%M', time.gmtime())}.md", f"# Pipelines run report: {ctx.title}\n\nRuns: {len(runs)} · succeeded: {ok}" + (f" ({rate} %)" if rate is not None else "")
               + "\n\n" + "".join(f"- {b['job']}: {b['why']} → {b.get('route')}\n" for b in ctx.records("fix")), label="Run report (Markdown)")
    return {"summary": f"{ok} of {len(runs)} run(s) succeeded" + (f" ({rate} %)" if rate is not None else "") + f"; {len(ctx.get('breaks') or [])} failing job(s) this round.",
            "counts": {"succeeded %": rate or 0, "failing": len(ctx.get("breaks") or [])}, "data": {"columns": ["Round", "Failing jobs"], "rows": hist}}


def _cards(u: dict) -> list[dict]:
    rows = [[r["job"], r["tool"], f"{r['old']} → {r['new']}", time.strftime("%d %b %Y", time.gmtime(r["created"])), f"#/m/{MODULE}/i/{r['item']}" if r.get("item") else ""]
            for r in db.q("SELECT * FROM pipelines_fixes ORDER BY created DESC LIMIT 20")
            if not r.get("item") or auth.can_project(u, "view", db.project(r["item"]))]
    return [{"title": "Fixes kept as rules", "columns": ["Job", "Tool", "Change", "When", "Work item"], "rows": rows,
             "empty": "No fix yet: a Fix / change item's Learn step keeps each one, so the next failure like it is diagnosed at once."}]


GUIDE = """# Data pipelines & ETL — the work item

This folder is one work item of Relay's Data pipelines & ETL module. Relay reads the ETL tools' APIs and exports into
one neutral model and applies its rules (health, keep / merge / retire, diagnosis, conversion). You are asked only for
what no rule fits — today, converting an ETL job into one dbt model.

- `convert.json` (written by the app before your run): the jobs to convert — tool, name, the tables each reads and loads,
  the warehouse's columns of those tables (`dictionary`) and the definition as the export holds it.
- `models/<model>.sql`: what you write — ONE SELECT in DuckDB's SQL producing the rows the job loads.
- `convert_notes.yaml`: one sentence per model on what you assumed.
- `data/`: the uploads and the read-only copies the proofs use; `evidence/`: what the steps measured.

Never invent a table or a column; never write INSERT, MERGE, CREATE or DELETE; say what you assumed."""


wb.register(wb.Pack(
    module=MODULE, guide=GUIDE,
    lineage="each job as a node of its tool reading its source tables and writing its target; converted dbt models (system “Relay pipelines”) writing the same targets",
    platforms={"api": API, "exports": EXPORTS, "warehouse": WH},
    schemas={"job": INV_EDIT.columns, "finding": FINDINGS_EDIT.columns, "decision": DECIDE_EDIT.columns, "model": CONVERT_EDIT.columns, "failing job": RUNFIX_EDIT.columns},
    cards=_cards,
    work={
        "assess": wb.Work(title="See every job, how healthy it is and what to fix, merge or retire first", steps={
            "Connect": wb.Step(kind="platform", run=a_connect, agent="Connector", text="Each ETL tool's API is tested with its own sign-in and each export opened — read-only"),
            "Inventory": wb.Step(kind="platform", run=a_inventory, agent="Scanner", edit=INV_EDIT,
                                 text="Every pipeline, package, mapping, DAG, task and connection in the tool's own terms, with its schedule, owner, what it reads and loads and its runs"),
            "Health": wb.Step(kind="proof", run=a_health, view="gates", agent="Health checker",
                              text="Rules over the run history and the definitions: failing since, flaky, slower than usual, a password in the definition, retire and merge candidates, no owner"),
            "Findings": wb.Step(kind="person", run=a_findings, edit=FINDINGS_EDIT, text="What needs attention, with its evidence — you keep or ignore each finding"),
            "Estimate": wb.Step(kind="deterministic", run=a_estimate, view="plan", agent="Estimator", text="Waves — fix, convert by rules, convert with the agent, retire — with the time a person needs")}),
        "develop": wb.Work(title="A new pipeline as a dbt model: mapped by rules, proven on a copy, then scheduled", steps={
            "Describe": wb.Step(kind="platform", run=d_describe, agent="Connector", text="The source tables you name (or upload) are read — their columns and rows"),
            "Shape": wb.Step(kind="deterministic", run=d_shape, view="mapping", agent="Mapper", edit=MAP_EDIT, confirm="the column mapping — what is copied, renamed, derived and the key",
                             text="Rules map every source column to the target, join on the shared keys and mark the key; you rename, drop or derive columns"),
            "Build": wb.Step(kind="deterministic", run=d_build, view="text", agent="Model builder", text="The mapping becomes a dbt model in your warehouse's SQL, with its tests and sources"),
            "Prove": wb.Step(kind="proof", run=d_prove, view="gates", agent="Prover", back_to="shape", text="The model runs on a copy of the sources: keys unique and not null, one row out per row in, every column real"),
            "Ship": wb.Step(kind="person", run=d_ship, view="plan", approver=True, text="The named approver confirms what goes live and how often it runs"),
            "Run": wb.Step(kind="platform", run=d_run, view="link", agent="Publisher", text="The dbt Cloud job is created through its own write approval (or the files are handed to your repository)")},
            fields=[wb.Field("objects", "Source tables", "longtext", help="One per line, e.g. STAGE.STG_ORDERS (or upload CSV / Parquet files)."),
                    wb.Field("target", "Target model name", help="e.g. fct_orders"), wb.Field("dialect", "Warehouse SQL", "select", options=DIALECTS, default="snowflake"),
                    wb.Field("cadence", "Once live, run it", "cadence", default={"every": "day", "at": "05:00", "tz": "UTC"})]),
        "change": wb.Work(title="Fix a failing job: the cause from its error, the change proven, then written back with approval", needs_source=True, steps={
            "Request": wb.Step(kind="platform", run=c_request, view="text", agent="Connector", text="The job you name and its recent runs, read from the tool"),
            "Diagnose": wb.Step(kind="deterministic", run=c_diagnose, view="gates", agent="Diagnostician",
                                text="The failure's cause from its error and the warehouse's dictionary — a renamed column, a late file, a transient outage, an expired sign-in"),
            "Fix": wb.Step(kind="deterministic", run=c_fix, agent="Fixer", edit=FIX_EDIT, text="Rules propose the change (rename the column the source renamed) — you confirm or change it"),
            "Prove": wb.Step(kind="proof", run=c_prove, view="gates", agent="Prover", back_to="fix", text="The changed definition no longer reads the old column, and every column it reads exists"),
            "Approve": wb.Step(kind="person", run=c_approve, view="plan", approver=True, text="The named approver releases the change"),
            "Learn": wb.Step(kind="platform", run=c_learn, view="link", agent="Publisher", text="The change is written to the tool through its own write approval and kept as a rule for next time")},
            fields=[wb.Field("job", "Job to fix", required=True, help="Its name in the tool, e.g. PL_FACT_GL_LOAD")]),
        "migrate": wb.Work(title="Move an ETL estate to dbt: decide, convert by rules, prove against the legacy tables", steps={
            "Discover": wb.Step(kind="platform", run=m_discover, agent="Scanner", text="Every job of the estate, from the tool's API or its export, with its run history"),
            "Decide": wb.Step(kind="deterministic", run=m_decide, agent="Rationaliser", edit=DECIDE_EDIT,
                              text="Keep, merge or retire each job — with the reason from its runs and definition — and whether rules or the agent convert it"),
            "Convert": wb.Step(kind="deterministic", run=m_convert, agent="Converter", edit=CONVERT_EDIT, confirm="the models no rule converted — ask Relay to draft them first, or go on without them",
                               confirm_if=lambda ctx, out: bool((out.get("counts") or {}).get("agent")),
                               text="Informatica PowerCenter mappings and ADF data flows become dbt models by rules; a column the source renamed is caught on the way; Relay's agent drafts what no rule fits",
                               actions={"agent": wb.Action(label="Ask Relay to convert the rest", kind="agent", prompt=_convert_prompt, check=_convert_check, after=_convert_after, agent="Converter (AI)",
                                                           help="The agent writes one SELECT per job no rule converts; each is checked, then proven like the others.")}),
            "Prove": wb.Step(kind="proof", run=m_prove, view="gates", agent="Prover", back_to="convert",
                             text="Each model runs on a copy of the tables it reads and is compared with the table the legacy job loads: row counts, checksums, sample rows"),
            "Hand over": wb.Step(kind="person", run=m_handover, view="plan", approver=True, text="The named owner signs off the evidence pack"),
            "Run": wb.Step(kind="deterministic", run=m_run, view="link", agent="Publisher", text="Lineage is recorded and a Run item watches the legacy jobs until cut-over")},
            fields=[wb.Field("dialect", "Target warehouse SQL", "select", options=DIALECTS, default="snowflake"),
                    wb.Field("cadence", "Watch the estate", "cadence", default={"every": "day", "at": "07:00", "tz": "UTC"})]),
        "run": wb.Work(title="Watch the runs on a schedule; failures go to a person before Self-healing or a ticket", platforms=("api",), steps={
            "Watch": wb.Step(kind="platform", run=r_watch, view="gates", agent="Watcher", text="Every job's runs since the last round, read from the tool"),
            "Alert": wb.Step(kind="deterministic", run=r_alert, agent="Triage", text="Failures grouped by job and likely cause"),
            "Fix": wb.Step(kind="deterministic", run=r_fix, agent="Triage", edit=RUNFIX_EDIT, text="Relay proposes who fixes each failure; you confirm or change it"),
            "Approve": wb.Step(kind="platform", run=r_approve, agent="Dispatcher", text="The approved hand-offs go out: Self-healing (it tests a fix before anything changes) or a ticket"),
            "Report": wb.Step(kind="deterministic", run=r_report, agent="Reporter", confirm_if=lambda ctx, out: bool(ctx.get("breaks")), text="A run report; you confirm it when something failed")},
            fields=[wb.Field("schedule", "Watch it", "cadence", default={"every": "hour", "tz": "UTC"})]),
    }))
