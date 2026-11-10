"""Data quality & reconciliation (registry id `quality`) — the pilot module on the workbench.

Assess   Connect → Inventory → Health → Findings → Estimate: the connected warehouses (Snowflake, BigQuery, Fabric,
         Redshift, Athena, PostgreSQL, SQL Server) and uploaded CSV / Parquet / Excel files are profiled (DuckDB for
         uploads, the guarded read-only query for warehouses) and rules are suggested from what the data shows.
Develop  Describe → Shape → Build → Prove → Ship → Run: rules authored and confirmed by a person (not null, unique,
         range / accepted values, exists in, freshness, business totals — from an Excel tie-out — and reconciliation
         of a source with its target); rules first, the agent only drafts the plain-English wording when asked; Build
         writes the checks as SQL and as dbt tests, Soda checks and a Great Expectations suite; Prove runs every rule;
         Ship is a named approval; Run publishes the rule set and starts a scheduled Run item.
Change   Request → Diagnose → Fix → Prove → Approve → Learn: a live rule set edited with review — the current state,
         the edit, a dry run against the data, approval, a new version.
Run      Watch → Alert → Fix → Approve → Report: the live rule set on a schedule; breaks grouped with the likely cause
         and any Data observability incident on the same table; a person decides per break — ticket, Self-healing,
         expected — and only then do the hand-offs go out.
Rule sets are versioned in `quality_rulesets` / `quality_ruleset_versions`; lineage records each checked table,
the rule set as a job that reads it, and source → target reconciliations.
"""
from __future__ import annotations

import json
import secrets as _secrets
import time
from pathlib import Path

from .. import auth, connectors, db, registry
from .. import workbench as wb
from . import quality_rules as qr

MODULE = "quality"
SYSTEM = "Relay quality"

db.register_schema("""
CREATE TABLE IF NOT EXISTS quality_rulesets (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, item TEXT, version INTEGER NOT NULL DEFAULT 1, rules TEXT NOT NULL DEFAULT '[]', datasets TEXT NOT NULL DEFAULT '[]',
  connections TEXT NOT NULL DEFAULT '[]', run_item TEXT, owner_id TEXT, published_by TEXT, published REAL, status TEXT NOT NULL DEFAULT 'live', created REAL NOT NULL, updated REAL NOT NULL);
CREATE TABLE IF NOT EXISTS quality_ruleset_versions (
  ruleset_id TEXT NOT NULL, version INTEGER NOT NULL, rules TEXT NOT NULL, item TEXT, published_by TEXT, published REAL NOT NULL, note TEXT,
  PRIMARY KEY (ruleset_id, version));
""")

WAREHOUSE = wb.WarehousePlatform()
FILES = wb.FilesPlatform()
FILES.reads = "the files you upload (CSV, Parquet, Excel — an Excel workbook with an `expected` column is read as a tie-out): a copy in this work item's folder, read with DuckDB"
MINUTES = {"confirm a suggested rule": 5, "supply a tie-out figure": 15, "set up a reconciliation": 30}
CAUSE = {"not_null": "a load or an upstream form leaves the field empty", "unique": "rows loaded twice, or a key that is not really unique",
         "range": "a sign error, a unit change or a new code upstream", "referential": "the dimension is loaded after the facts, or a code was retired",
         "freshness": "the load did not run on time (schedule, credentials or an upstream delay)", "business_total": "missing or duplicated rows, a filter, or a late adjustment",
         "reconcile": "the copy is incomplete or transformed differently from the source"}
ROUTE_FOR = {"freshness": "heal", "reconcile": "heal"}


def _lc(s: str) -> str:
    return s[:1].lower() + s[1:]


# ------------------------------------------------------------------ rule sets (versioned, per tenant through db.q)

def _j(s, default):
    try:
        return json.loads(s) if s else default
    except ValueError:
        return default


def ruleset(rid: str, u: dict | None = None) -> dict | None:
    r = db.one("SELECT * FROM quality_rulesets WHERE id = ?", (rid,))
    if not r:
        return None
    if u is not None and r.get("item") and not auth.can_project(u, "view", db.project(r["item"])):
        return None
    return {**r, "rules": _j(r["rules"], []), "datasets": _j(r["datasets"], []), "connections": _j(r["connections"], [])}


def rulesets(u: dict) -> list[dict]:
    out = []
    for r in db.q("SELECT * FROM quality_rulesets WHERE status = 'live' ORDER BY updated DESC"):
        if r.get("item") and not auth.can_project(u, "view", db.project(r["item"])):
            continue
        out.append({**r, "rules": _j(r["rules"], []), "datasets": _j(r["datasets"], [])})
    return out


def ruleset_options(u: dict) -> list[tuple[str, str]]:
    return [(r["id"], f"{r['name']} · version {r['version']} · {len(r['rules'])} rules") for r in rulesets(u)]


def assess_options(u: dict) -> list[tuple[str, str]]:
    rows = db.q("SELECT id, title FROM wb_items WHERE module = ? AND work = 'assess' AND status = 'done' ORDER BY updated DESC LIMIT 50", (MODULE,))
    vis = auth.access_map(u, [r["id"] for r in rows])
    return [("", "No — start from the data")] + [(r["id"], r["title"]) for r in rows if r["id"] in vis]


def publish(ctx: wb.Ctx, rules: list[dict], dsets: list[dict], rid: str | None = None, note: str = "") -> dict:
    """A new rule set, or a new version of one; the versions are kept."""
    now = time.time()
    who = ctx.who or ctx.owner
    keep = [r for r in rules if r.get("active")]
    if rid and db.one("SELECT 1 FROM quality_rulesets WHERE id = ?", (rid,)):
        v = db.one("SELECT version FROM quality_rulesets WHERE id = ?", (rid,))["version"] + 1
        db.run("UPDATE quality_rulesets SET version = ?, rules = ?, datasets = ?, published_by = ?, published = ?, updated = ? WHERE id = ?",
               (v, json.dumps(keep), json.dumps(dsets), who, now, now, rid))
    else:
        rid, v = "qrs-" + _secrets.token_hex(4), 1
        db.run("INSERT INTO quality_rulesets (id, name, item, version, rules, datasets, connections, owner_id, published_by, published, status, created, updated) "
               "VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?, ?, 'live', ?, ?)", (rid, ctx.title[:160], ctx.id, json.dumps(keep), json.dumps(dsets),
                                                                       json.dumps(ctx.st.get("connections") or []), ctx.owner, who, now, now, now))
    db.run("INSERT OR REPLACE INTO quality_ruleset_versions (ruleset_id, version, rules, item, published_by, published, note) VALUES (?, ?, ?, ?, ?, ?, ?)",
           (rid, v, json.dumps(keep), ctx.id, who, now, note[:500] or None))
    db.audit("quality.ruleset.publish", rid, {"version": v, "rules": len(keep), "item": ctx.id}, who)
    return ruleset(rid)


def record_lineage(ctx: wb.Ctx, rs: dict, results: list[dict] | None = None) -> list[str]:
    """Each checked table, the rule set as a job that reads it, and source → target reconciliations."""
    job = ctx.lineage_node("job", SYSTEM, f"Quality checks: {rs['name']}", label=f"Quality checks: {rs['name']} (v{rs['version']})",
                           properties={"ruleset": rs["id"], "version": rs["version"], "rules": len(rs["rules"])})
    tables = {}
    for d in rs["datasets"]:
        ref = d["ref"]
        if ref["source"] == "connection":
            try:
                c = connectors._row(ref["connection"])
                tables[d["key"]] = ctx.lineage_node("table", c["kind"], ref["object"], label=f"{ref['object']} ({connectors.KINDS.get(c['kind'], {}).get('label', c['kind'])})", own=False)
            except connectors.ConnectorError:
                continue
        else:
            tables[d["key"]] = ctx.lineage_node("table", ref.get("item") or ctx.id, ref["file"], label=f"{ref['file']} (upload)", own=False)
    for key, nid in tables.items():
        ctx.lineage_edge(nid, job, "reads", {"checks": sum(1 for r in rs["rules"] if r.get("dataset") == key)})
    by_id = {g["name"]: g for g in results or []}
    for r in rs["rules"]:
        if r.get("kind") == "reconcile":
            p, probs = qr.parse(r, {d["key"]: d for d in rs["datasets"]})
            if not probs and r["dataset"] in tables and p.get("target") in tables:
                ctx.lineage_edge(tables[r["dataset"]], tables[p["target"]], "feeds", {"reconciled": (by_id.get(r["id"]) or {}).get("status") or "defined", "rule": r["id"]})
    return [job, *tables.values()]


# ------------------------------------------------------------------ datasets

def _dmap(ctx: wb.Ctx) -> dict:
    return {d["key"]: d for d in ctx.get("datasets") or []}


def _ds_options(ctx: wb.Ctx):
    return [(d["key"], d["label"]) for d in ctx.get("datasets") or []]


def _unique_names(ds: list[dict]) -> list[dict]:
    seen: dict[str, int] = {}
    for d in ds:
        n = d["name"].lower()
        seen[n] = seen.get(n, 0) + 1
    for d in ds:
        if seen[d["name"].lower()] > 1 and d.get("where"):
            d["name"] = f"{d['name']}@{d['where']}"
    return ds


def sources(ctx: wb.Ctx, wanted: list[str] | None = None, cap: int = 25) -> list[dict]:
    """The datasets an item reads: the warehouse objects named in its scope (or the first few the connection shows) and
    the data files uploaded to it (an Excel tie-out is not a dataset)."""
    want = [w.lower() for w in (wanted if wanted is not None else [x.strip() for x in (ctx.scope.get("objects") or "").splitlines() if x.strip()])]
    out = []
    for c in ctx.connections():
        if c["kind"] not in WAREHOUSE.kinds:
            continue
        try:
            objs = [o["object"] for o in connectors.browse(c)[:500]]
        except connectors.ConnectorError as e:
            raise wb.StepFailed(f"{c['name']} could not be read: {e}") from e
        pick = [o for o in objs if not want or any(o.lower() == w or o.lower().endswith("." + w) for w in want)][:cap if not want else 200]
        for o in pick:
            out.append(qr.dataset({"source": "connection", "connection": c["id"], "object": o}, o, f"{o} · {c['name']}", c["name"]))
    for f in ctx.files():
        if not f.get("table"):
            continue
        if f["name"].lower().endswith(".xlsx") and qr.is_tieout(ctx.dir / "data" / f["name"]):
            continue
        stem = Path(f["name"]).stem                    # an upload is always in scope: the person chose it
        out.append(qr.dataset({"source": "file", "item": ctx.id, "file": f["table"]}, stem, f"{f['name']} (upload)", "upload"))
    return _unique_names(out)


def _shape_of(ctx: wb.Ctx, dsets: list[dict]) -> list[list]:
    rows = []
    for d in dsets:
        r = None
        try:
            r = ctx.reader(d["ref"])
            rows.append([d["name"], d["where"] or "upload", r.count(), len(r.columns()), "read"])
        except (wb.oc.ReadError, wb.StepFailed) as e:
            rows.append([d["name"], d["where"] or "upload", None, None, f"could not read: {str(e)[:120]}"])
        finally:
            wb._close(r)
    return rows


def _profiles(ctx: wb.Ctx, dsets: list[dict]) -> dict:
    out = {}
    for d in dsets:
        r = None
        try:
            r = ctx.reader(d["ref"])
            p = qr.profile(r)
            out[d["key"]] = p
            ctx.evidence(f"Profile of {d['name']}", {"dataset": d["label"], "rows": p["rows"], "columns": p["columns"]}, kind="profile", ok=True)
        except (wb.oc.ReadError, wb.StepFailed) as e:
            ctx.evidence(f"Profile of {d['name']} (could not read)", {"dataset": d["label"], "error": str(e)}, kind="profile", ok=False)
        finally:
            wb._close(r)
    return out


def _suggest(ctx: wb.Ctx, dsets: list[dict], profiles: dict) -> list[dict]:
    now = time.time()
    pairs = [(d, profiles[d["key"]]) for d in dsets if d["key"] in profiles]
    rules = []
    for d, p in pairs:
        rules += qr.suggest(d, p, pairs, now)
    rules += qr.reconcile_suggestions(dsets, profiles)
    for t in qr.tieouts(ctx):
        d = find_dataset(dsets, t.pop("dataset_name") or "")
        if d:
            t["dataset"] = d["key"]
            rules.append(t)
    return rules


def find_dataset(dsets: list[dict], text: str) -> dict | None:
    """A dataset by the name a person wrote: the exact name, else a warehouse object ending in it, else a file's stem."""
    t = text.strip().lower()
    if not t:
        return None
    return (next((d for d in dsets if d["name"].lower() == t), None)
            or next((d for d in dsets if d["ref"]["source"] == "connection" and d["ref"]["object"].lower().endswith("." + t)), None)
            or next((d for d in dsets if d["ref"]["source"] == "file" and Path(d["ref"]["file"]).stem.lower() == t), None))


def _rules_table(rules: list[dict], dmap: dict) -> dict:
    return {"columns": ["On", "Rule", "Dataset", "Column", "Check", "Severity", "Why"],
            "rows": [["yes" if r.get("active") else "no", qr.KINDS.get(r["kind"], r["kind"]), (dmap.get(r.get("dataset")) or {}).get("name", "?"), r.get("column") or "",
                      r.get("check") or "", r.get("severity"), r.get("why") or ""] for r in rules]}


def _gates(rows: list[dict]) -> dict:
    return {"checks": rows}


RULE_COLUMNS = [wb.Column("active", "On", "bool"), wb.Column("kind", "Rule", "select", options=tuple(qr.KINDS.items())),
                wb.Column("dataset", "Dataset", "select", options=_ds_options), wb.Column("column", "Column"),
                wb.Column("check", "Check", help=qr.CHECK_HELP), wb.Column("severity", "Severity", "select", options=qr.SEVERITIES),
                wb.Column("description", "In plain words", "longtext"), wb.Column("why", "Why Relay suggests it", readonly=True)]
def _validate_rules(recs: list[dict], ctx: wb.Ctx) -> list[str]:
    """Rules first: a rule that cannot run is refused; each rule's `problem` is refreshed for the screen."""
    dmap = _dmap(ctx)
    for r in recs:
        r["problem"] = "; ".join(qr.parse(r, dmap)[1])
    return qr.validate(recs, dmap)


RULES_EDIT = wb.Edit(columns=RULE_COLUMNS, validate=_validate_rules, label="rule")


# ------------------------------------------------------------------ the agent helper: plain-English wording (never the rules)

WORDING = """Read WORK.md, then rules.json in this folder: the rule set a person is building, one object per rule (id, kind,
dataset, column, check, severity). Write rules_wording.yaml with one entry per rule id:

wording:
  not_null-orders-order_id: "Every order has an order number."
  range-orders-amount: "An order amount is never negative."

One plain-English sentence each that a business person understands, in British English, describing what the rule
checks. Never change, add or drop a rule; never name a table or column the rule does not name; no numbers that are
not in the rule's check."""


def _wording_prompt(ctx: wb.Ctx) -> str:
    rules = [{k: r.get(k) for k in ("id", "kind", "dataset", "column", "check", "severity")} for r in ctx.records(ctx.step_id)]
    (ctx.dir / "rules.json").write_text(json.dumps(rules, indent=1), encoding="utf-8")
    return WORDING


def _wording_check(ctx: wb.Ctx) -> list[str]:
    import yaml
    p = ctx.dir / "rules_wording.yaml"
    if not p.exists():
        return ["rules_wording.yaml was not written"]
    try:
        y = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        return [f"rules_wording.yaml does not parse: {str(e).splitlines()[0]}"]
    w = y.get("wording") if isinstance(y, dict) else None
    if not isinstance(w, dict):
        return ["rules_wording.yaml needs a mapping `wording:` from rule id to one sentence"]
    ids = {r["id"] for r in ctx.records(ctx.step_id)}
    out = [f"unknown rule id {k} (only the ids in rules.json)" for k in w if k not in ids]
    out += [f"rule {k}: the sentence is empty" for k, v in w.items() if k in ids and not str(v or "").strip()]
    missing = sorted(ids - set(w))
    if missing:
        out.append(f"no wording for {len(missing)} rule(s): {', '.join(missing[:6])}")
    return out


def _wording_after(ctx: wb.Ctx, res: dict) -> dict:
    import yaml
    w = (yaml.safe_load((ctx.dir / "rules_wording.yaml").read_text(encoding="utf-8")) or {}).get("wording") or {}
    recs = ctx.records(ctx.step_id)
    n = 0
    for r in recs:
        text = str(w.get(r["id"]) or "").strip()
        if text and (not r.get("description") or r.get("worded_by") == "agent"):
            r.update(description=text[:400], worded_by="agent")
            n += 1
    ctx.evidence("Wording drafted by Relay", {"wording": w, "summary": res.get("text") or ""}, kind="agent", ok=True)
    return {"summary": f"Relay drafted the wording of {n} rule(s) — check it before you confirm; the rules themselves did not change.", "records": recs,
            "data": _rules_table(recs, _dmap(ctx))}


# ------------------------------------------------------------------ Assess

def a_connect(ctx: wb.Ctx) -> dict:
    rows = []
    for p in (WAREHOUSE, FILES):
        rows += p.test(ctx)
    if not rows:
        raise wb.StepFailed("Nothing to read: pick a warehouse connection or upload files (CSV, Parquet or Excel).")
    good = [r for r in rows if r["ok"]]
    if not good:
        raise wb.StepFailed("None of the sources answered: " + "; ".join(f"{r['source']}: {r['sees']}" for r in rows)[:600])
    return {"summary": f"{len(good)} of {len(rows)} source(s) answered — read-only.", "counts": {"sources": len(rows), "answered": len(good)},
            "data": {"columns": ["Source", "Kind", "Status", "What Relay sees", "Access"], "rows": [[r["source"], r["kind"], "answered" if r["ok"] else "refused", r["sees"], r["scope"]] for r in rows]}}


def a_inventory(ctx: wb.Ctx) -> dict:
    want = [x.strip() for x in (ctx.scope.get("objects") or "").splitlines() if x.strip()]
    found = sources(ctx, wanted=[], cap=200)
    if not found:
        raise wb.StepFailed("The sources show no tables or files to look at.")
    keep = {d["key"] for d in sources(ctx, wanted=want)} if want else {d["key"] for d in found[:15]}
    shape = {d["key"]: row for d, row in zip(found[:60], _shape_of(ctx, found[:60]))}
    ctx.put("inventory", found)
    recs = [{"id": d["key"], "include": d["key"] in keep, "dataset": d["name"], "where": d["where"] or "upload",
             "rows": (shape.get(d["key"]) or [None] * 3)[2], "columns": (shape.get(d["key"]) or [None] * 4)[3]} for d in found]
    return {"summary": f"{len(found)} table(s) and file(s) found; {len(keep)} included for the health check — untick what is out of scope.",
            "counts": {"found": len(found), "included": len(keep)}, "records": recs,
            "data": {"columns": ["Include", "Table or file", "Where", "Rows", "Columns"], "rows": [["yes" if r["include"] else "no", r["dataset"], r["where"], r["rows"], r["columns"]] for r in recs]}}


def a_health(ctx: wb.Ctx) -> dict:
    inv = {d["key"]: d for d in ctx.get("inventory") or []}
    dsets = [inv[r["id"]] for r in ctx.records("inventory") if r.get("include") and r["id"] in inv]
    if not dsets:
        raise wb.StepFailed("No table or file is included: tick at least one in the inventory.")
    ctx.put("datasets", dsets)
    profiles = _profiles(ctx, dsets)
    rules = _suggest(ctx, dsets, profiles)
    results = qr.run_rules(ctx, rules, {d["key"]: d for d in dsets}, time.time(), label="Health check")
    by_rule = {r["id"]: r for r in rules}
    findings = []
    for g in results:
        if g["status"] in ("fail", "error"):
            r = by_rule.get(g["name"]) or {}
            findings.append({"id": g["name"], "dataset": next((d["name"] for d in dsets if d["key"] == g["dataset"]), "?"), "column": g.get("column") or "",
                             "issue": g["detail"], "measured": g.get("measured") or "", "severity": g.get("severity") or "medium",
                             "rule": f"{qr.KINDS.get(r.get('kind'), '')}: {r.get('check') or '(no parameter)'}", "decision": "keep", "evidence": g["evidence"]})
    for r in rules:
        if not r.get("active") and r["kind"] in ("freshness", "business_total"):
            findings.append({"id": r["id"], "dataset": next((d["name"] for d in dsets if d["key"] == r["dataset"]), "?"), "column": r.get("column") or "", "issue": r["why"],
                             "measured": "", "severity": "low", "rule": f"{qr.KINDS[r['kind']]}: {r['check']}", "decision": "keep"})
    ctx.put("profiles", {k: {"rows": v["rows"], "columns": len(v["columns"])} for k, v in profiles.items()})
    ctx.put("suggested", rules)
    ctx.put("findings", findings)
    checks = []
    for d in dsets:
        p = profiles.get(d["key"])
        fs = [f for f in findings if f["dataset"] == d["name"] and f.get("measured") != ""]
        high = [f for f in fs if f["severity"] == "high"]
        checks.append({"name": d["key"], "label": f"Health of {d['name']}", "status": "fail" if high else "warn" if fs else "pass" if p else "fail",
                       "measured": f"{p['rows']:,} rows · {len(p['columns'])} columns" if p else "not read", "expected": "",
                       "detail": f"{len(fs)} issue(s), {len(high)} high; {sum(1 for r in rules if r['dataset'] == d['key'])} rule(s) suggested" if p else "could not be read"})
    t = qr.tally(results)
    return {"summary": f"{len(dsets)} dataset(s) profiled; {len(rules)} rule(s) suggested from what the data shows; {t['fail']} fail today ({t['high fail']} high).",
            "counts": {"datasets": len(dsets), "rules suggested": len(rules), "failing": t["fail"]}, "data": _gates(checks + results)}


def a_findings(ctx: wb.Ctx) -> dict:
    have = {r["id"]: r for r in ctx.records("findings")}
    recs = [{**f, **({"decision": have[f["id"]].get("decision"), "severity": have[f["id"]].get("severity")} if f["id"] in have else {})} for f in ctx.get("findings") or []]
    high = sum(1 for r in recs if r["severity"] == "high")
    return {"summary": (f"{len(recs)} finding(s), {high} high — keep what matters, ignore what does not." if recs else "No issues found: every suggested rule passes on today's data."),
            "counts": {"findings": len(recs), "high": high}, "records": recs, "items": [f"{r['dataset']}.{r['column']}: {r['issue']}" for r in recs[:6]],
            "data": {"columns": ["Dataset", "Column", "Issue", "Measured", "Severity", "Rule that catches it"],
                     "rows": [[r["dataset"], r["column"], r["issue"], r["measured"], r["severity"], r["rule"]] for r in recs]}}


FINDINGS_EDIT = wb.Edit(columns=[wb.Column("decision", "Decision", "select", options=(("keep", "Keep"), ("ignore", "Ignore"))),
                                 wb.Column("severity", "Severity", "select", options=qr.SEVERITIES), wb.Column("dataset", "Dataset", readonly=True),
                                 wb.Column("column", "Column", readonly=True), wb.Column("issue", "Issue", readonly=True)], add=False, remove=False, label="finding")


def a_estimate(ctx: wb.Ctx) -> dict:
    import yaml
    dsets = ctx.get("datasets") or []
    rules = ctx.get("suggested") or []
    kept = [f for f in ctx.records("findings") if f.get("decision") != "ignore"]
    hot = {f["dataset"] for f in kept if f.get("severity") == "high" and f.get("measured") != ""}
    waves = [("Wave 1 — tables with high-severity findings", [d for d in dsets if d["name"] in hot]), ("Wave 2 — the rest", [d for d in dsets if d["name"] not in hot])]
    b = registry.brand()
    rate, cur = float(b.get("hourly_rate") or 0), b.get("currency") or ""
    items, total_h = [], 0.0
    for name, ds in waves:
        if not ds:
            continue
        keys = {d["key"] for d in ds}
        rs = [r for r in rules if r["dataset"] in keys]
        n_rule = sum(1 for r in rs if r["kind"] not in ("business_total", "reconcile"))
        n_tie = sum(1 for r in rs if r["kind"] == "business_total")
        n_rec = sum(1 for r in rs if r["kind"] == "reconcile")
        h = (n_rule * MINUTES["confirm a suggested rule"] + n_tie * MINUTES["supply a tie-out figure"] + n_rec * MINUTES["set up a reconciliation"]) / 60
        total_h += h
        items.append({"title": name, "detail": f"{', '.join(d['name'] for d in ds)}: {n_rule} rule(s) to confirm, {n_tie} tie-out figure(s) to supply, {n_rec} reconciliation(s)",
                      "effort": f"{h:.1f} h" + (f" · {cur}{rate * h:,.0f}" if rate else "")})
    assumptions = "; ".join(f"{v} min to {k}" for k, v in MINUTES.items())
    ctx.output("assessment.md", "# Assessment: " + ctx.title + "\n\n" + "\n".join(f"## {i['title']}\n\n{i['detail']}\n\nEffort: {i['effort']}\n" for i in items)
               + f"\nAssumptions: {assumptions}.\n" + ("" if rate else "No hourly rate is set (Admin › Branding), so no cost is shown.\n"), label="Assessment (Markdown)")
    ctx.output("suggested-rules.yaml", yaml.safe_dump({"datasets": [{"key": d["key"], "name": d["name"], "label": d["label"]} for d in dsets],
                                                       "rules": [{k: r.get(k) for k in ("id", "kind", "dataset", "column", "check", "severity", "active", "why")} for r in rules]},
                                                      sort_keys=False, allow_unicode=True), label="Suggested rules (YAML)")
    return {"summary": f"{len(items)} wave(s), about {total_h:.1f} h of a person's time to confirm the rules" + (f" ({cur}{rate * total_h:,.0f} at the hourly rate)" if rate else "") + ".",
            "counts": {"waves": len(items), "hours": round(total_h, 1)},
            "data": {"items": items, "total": f"{total_h:.1f} h", "note": f"Assumptions: {assumptions}." + ("" if rate else " Set an hourly rate under Admin › Branding to see the cost.")}}


# ------------------------------------------------------------------ Develop

def d_describe(ctx: wb.Ctx) -> dict:
    dsets = sources(ctx)
    src_item = ctx.scope.get("from_item")
    if src_item and not dsets:
        prev = wb._load(src_item) if src_item else None
        dsets = list((prev or {}).get("data", {}).get("datasets") or [])
    if not dsets:
        raise wb.StepFailed("Nothing to check: pick a warehouse connection and name its tables, or upload the files (CSV, Parquet, Excel).")
    ctx.put("datasets", dsets)
    rows = _shape_of(ctx, dsets)
    ties = qr.tieouts(ctx)
    ctx.put("tieouts", len(ties))
    return {"summary": f"{len(dsets)} dataset(s) read" + (f" and {len(ties)} tie-out figure(s) from Excel" if ties else "") + ".",
            "counts": {"datasets": len(dsets), "tie-outs": len(ties)},
            "data": {"columns": ["Dataset", "Where", "Rows", "Columns", "Status"], "rows": rows}}


def d_shape(ctx: wb.Ctx) -> dict:
    dsets = ctx.get("datasets") or []
    dmap = {d["key"]: d for d in dsets}
    profiles = _profiles(ctx, dsets)
    suggested = _suggest(ctx, dsets, profiles)
    src_item = ctx.scope.get("from_item")
    if src_item:
        try:
            prev = wb._load(src_item)
            ignored = {r["id"] for s in prev["steps"] if s["id"] == "findings" for r in s.get("records") or [] if r.get("decision") == "ignore"}
            earlier = list((prev.get("data") or {}).get("suggested") or [])
            suggested = [r for r in earlier + suggested if r["dataset"] in dmap and r["id"] not in ignored]
        except (KeyError, FileNotFoundError):
            pass
    have = ctx.records(ctx.step_id)                          # a person's edits survive a re-run
    ids = {r["id"] for r in have}
    rules = have + [r for r in suggested if r["id"] not in ids and not ids.add(r["id"])]
    for r in rules:
        _, probs = qr.parse(r, dmap)
        r["problem"] = "; ".join(probs)
    on = sum(1 for r in rules if r.get("active"))
    return {"summary": f"{len(rules)} rule(s) — {on} on — from what the data shows" + (" and the Excel tie-out" if any(r.get("origin") == "tie-out" for r in rules) else "")
            + ". Change, add or switch off rules, then confirm the design.", "counts": {"rules": len(rules), "on": on, "datasets": len(dsets)},
            "records": rules, "data": _rules_table(rules, dmap), "items": [f"{qr.KINDS[r['kind']]}: {(dmap.get(r['dataset']) or {}).get('name', '?')}.{r.get('column') or ''} {r.get('check') or ''}" for r in rules[:6]]}


def d_build(ctx: wb.Ctx) -> dict:
    dmap = _dmap(ctx)
    rules = [r for r in ctx.records("shape") if r.get("active")]
    probs = qr.validate(rules, dmap)
    if probs:
        raise wb.StepFailed("The confirmed rules have problems: " + "; ".join(probs[:6]))
    rows = []
    for r in rules:
        p, _ = qr.parse(r, dmap)
        ds = dmap[r["dataset"]]
        dialect = "duckdb"
        if ds["ref"]["source"] == "connection":
            try:
                dialect = connectors.KINDS[connectors._row(ds["ref"]["connection"])["kind"]].get("dialect") or "duckdb"
            except connectors.ConnectorError:
                pass
        ref = dmap.get(p.get("ref_dataset") or "") or {}
        sql = qr.compile_sql(r, p, ds, dialect, ref_name=ref.get("ref", {}).get("object") or Path(ref.get("ref", {}).get("file") or "ref").stem)
        r["sql"] = sql
        rows.append([r["id"], ds["name"], qr.KINDS[r["kind"]], dialect, sql[:160]])
    files = qr.exports(rules, dmap, ctx.title)
    for name, text in files.items():
        ctx.output(name, text, label={"dbt_schema.yml": "dbt tests (schema.yml)", "dbt_tests.sql": "dbt singular tests", "soda_checks.yml": "Soda checks",
                                      "great_expectations_suites.json": "Great Expectations suites"}.get(name, name))
    import yaml
    ctx.output("rules.yaml", yaml.safe_dump({"name": ctx.title, "datasets": [{"key": d["key"], "name": d["name"], "label": d["label"]} for d in dmap.values()],
                                             "rules": [{k: r.get(k) for k in ("id", "kind", "dataset", "column", "check", "severity", "description", "sql")} for r in rules]},
                                            sort_keys=False, allow_unicode=True), label="The rule set (YAML)")
    ctx.put("built", rules)
    return {"summary": f"{len(rules)} check(s) written as SQL in each dataset's own dialect, and exported as dbt tests, Soda checks and a Great Expectations suite.",
            "counts": {"checks": len(rules), "files": len(files) + 1}, "data": {"columns": ["Rule", "Dataset", "Kind", "Dialect", "SQL"], "rows": rows}}


def d_prove(ctx: wb.Ctx) -> dict:
    rules = ctx.get("built") or [r for r in ctx.records("shape") if r.get("active")]
    results = qr.run_rules(ctx, rules, _dmap(ctx), time.time(), label="Proof")
    t = qr.tally(results)
    ctx.put("proof", t)
    return {"summary": f"{t['rules']} rule(s) run on the data now: {t['pass']} pass, {t['fail']} fail ({t['high fail']} high)" + (f", {t['error']} could not run" if t["error"] else "")
            + ". Accept to take them to go-live as they are, or send them back to Shape.", "counts": {k: v for k, v in t.items() if k != "skip"}, "data": _gates(results),
            "items": [f"{g['label']}: {g['status']} — {g['detail']}" for g in results if g["status"] != "pass"][:6]}


def d_ship(ctx: wb.Ctx) -> dict:
    rules = ctx.get("built") or []
    t = ctx.get("proof") or {}
    cad = ctx.scope.get("cadence") or {"every": "day", "at": "06:00", "tz": "UTC"}
    approver = db.user(ctx.st.get("approver") or "") or {}
    return {"summary": f"Go live: {len(rules)} rule(s) on {len(ctx.get('datasets') or [])} dataset(s), checked {_lc(wb.schedule_text(cad))}.",
            "data": {"items": [{"title": "Rules going live", "detail": f"{len(rules)} rule(s): " + ", ".join(sorted({qr.KINDS[r['kind']] for r in rules}))},
                               {"title": "What the proof showed", "detail": f"{t.get('pass', 0)} pass, {t.get('fail', 0)} fail ({t.get('high fail', 0)} high) on today's data"},
                               {"title": "Then", "detail": f"A Run item checks them {_lc(wb.schedule_text(cad))}; breaks wait for a person before a ticket or Self-healing."},
                               {"title": "Named approval", "detail": approver.get("name") or "the owner of this work item"}]}}


def d_run(ctx: wb.Ctx) -> dict:
    rules = ctx.get("built") or []
    dsets = ctx.get("datasets") or []
    rid = ctx.get("ruleset")
    rs = publish(ctx, rules, dsets, rid, note="go-live from Develop")
    ctx.put("ruleset", rs["id"])
    record_lineage(ctx, rs)
    cad = ctx.scope.get("cadence") or {"every": "day", "at": "06:00", "tz": "UTC"}
    run_id = rs.get("run_item")
    if not run_id or not db.one("SELECT 1 FROM wb_items WHERE id = ? AND closed IS NULL", (run_id,)):
        item = wb.create(MODULE, "run", f"Run: {ctx.title}"[:160], who=ctx.owner, brief=f"Scheduled checks of the rule set “{rs['name']}”, published from {ctx.id}.",
                         connections=ctx.st.get("connections") or [], scope={"ruleset": rs["id"], "schedule": cad}, approver=ctx.st.get("approver"),
                         visibility=(db.project(ctx.id) or {}).get("visibility") or "private", team_id=(db.project(ctx.id) or {}).get("team_id"), parent=ctx.id)
        run_id = item["id"]
        db.run("UPDATE quality_rulesets SET run_item = ? WHERE id = ?", (run_id, rs["id"]))
    return {"summary": f"Rule set “{rs['name']}” version {rs['version']} is live; the Run item checks it {_lc(wb.schedule_text(cad))}.",
            "counts": {"version": rs["version"], "rules": len(rs["rules"])},
            "data": {"href": f"#/m/{MODULE}/i/{run_id}", "label": "Open the Run item", "text": f"Version {rs['version']} · {len(rs['rules'])} rule(s) · {wb.schedule_text(cad)}"}}


# ------------------------------------------------------------------ Change

def _rs_or_fail(ctx: wb.Ctx) -> dict:
    rs = ruleset(ctx.scope.get("ruleset") or "", db.user(ctx.owner or "") or {})
    if not rs:
        raise wb.StepFailed("The rule set this work item changes is not one its owner can see any more.")
    return rs


def c_request(ctx: wb.Ctx) -> dict:
    rs = _rs_or_fail(ctx)
    ctx.put("ruleset", rs["id"])
    ctx.put("current", rs["rules"])
    ctx.put("datasets", rs["datasets"])
    ctx.put("version", rs["version"])
    return {"summary": f"Change to “{rs['name']}” (version {rs['version']}, {len(rs['rules'])} rule(s) on {len(rs['datasets'])} dataset(s)).",
            "counts": {"rules": len(rs["rules"]), "version": rs["version"]}, "data": {"text": ctx.brief or "(no request text)"}}


def c_diagnose(ctx: wb.Ctx) -> dict:
    rules = ctx.get("current") or []
    results = qr.run_rules(ctx, rules, _dmap(ctx), time.time(), label="Today")
    words = {w.lower() for w in ctx.brief.replace(",", " ").replace(".", " ").split() if len(w) > 3}
    touched = [r for r in rules if (r.get("column") or "").lower() in words or (_dmap(ctx).get(r["dataset"]) or {}).get("name", "").lower() in words]
    ctx.put("before", {g["name"]: g["status"] for g in results})
    t = qr.tally(results)
    return {"summary": f"Today {t['pass']} pass and {t['fail']} fail; the request mentions {len(touched)} rule(s).", "counts": {"pass": t["pass"], "fail": t["fail"], "mentioned": len(touched)},
            "data": _gates(results), "items": [f"Mentioned: {qr.KINDS[r['kind']]} on {r.get('column')}" for r in touched[:6]]}


def c_fix(ctx: wb.Ctx) -> dict:
    recs = ctx.records(ctx.step_id) or [dict(r) for r in ctx.get("current") or []]
    return {"summary": "Edit the rules: change a check, add or switch off rules. Confirm when the change is right; Relay proves it on the data next.", "records": recs,
            "data": _rules_table(recs, _dmap(ctx)), "counts": {"rules": len(recs)}}


def _diff(before: list[dict], after: list[dict]) -> dict:
    b, a = {r["id"]: r for r in before}, {r["id"]: r for r in after}
    keys = ("kind", "dataset", "column", "check", "severity", "active")
    return {"added": [r for k, r in a.items() if k not in b], "removed": [r for k, r in b.items() if k not in a],
            "changed": [r for k, r in a.items() if k in b and any(b[k].get(x) != r.get(x) for x in keys)]}


def c_prove(ctx: wb.Ctx) -> dict:
    after = ctx.records("fix")
    probs = qr.validate([r for r in after if r.get("active")], _dmap(ctx))
    if probs:
        raise wb.StepFailed("The edited rules have problems: " + "; ".join(probs[:6]))
    results = qr.run_rules(ctx, after, _dmap(ctx), time.time(), label="Dry run")
    before = ctx.get("before") or {}
    dif = _diff(ctx.get("current") or [], after)
    newly = [g for g in results if g["status"] == "fail" and before.get(g["name"]) != "fail"]
    ctx.put("diff", {k: [r["id"] for r in v] for k, v in dif.items()})
    t = qr.tally(results)
    return {"summary": f"{len(dif['added'])} added, {len(dif['changed'])} changed, {len(dif['removed'])} removed; on the data now {t['pass']} pass, {t['fail']} fail"
            + (f" — {len(newly)} newly failing" if newly else "") + ".", "counts": {"added": len(dif["added"]), "changed": len(dif["changed"]), "removed": len(dif["removed"]), "fail": t["fail"]},
            "data": _gates(results), "items": [f"Newly failing: {g['label']} — {g['detail']}" for g in newly[:6]]}


def c_approve(ctx: wb.Ctx) -> dict:
    d = ctx.get("diff") or {}
    return {"summary": f"Release version {(ctx.get('version') or 0) + 1}: {len(d.get('added') or [])} added, {len(d.get('changed') or [])} changed, {len(d.get('removed') or [])} removed.",
            "data": {"items": [{"title": "Added", "detail": ", ".join(d.get("added") or []) or "—"}, {"title": "Changed", "detail": ", ".join(d.get("changed") or []) or "—"},
                               {"title": "Removed", "detail": ", ".join(d.get("removed") or []) or "—"}]}}


def c_learn(ctx: wb.Ctx) -> dict:
    rs = publish(ctx, ctx.records("fix"), ctx.get("datasets") or [], ctx.get("ruleset"), note=(ctx.brief or "")[:300])
    record_lineage(ctx, rs)
    return {"summary": f"Version {rs['version']} of “{rs['name']}” is live; the Run item uses it from its next check.", "counts": {"version": rs["version"], "rules": len(rs["rules"])},
            "data": {"href": f"#/m/{MODULE}/i/{rs['run_item']}" if rs.get("run_item") else f"#/m/{MODULE}/run", "label": "Open the Run item" if rs.get("run_item") else "Run & support",
                     "text": f"Version {rs['version']} · {len(rs['rules'])} rule(s)"}}


# ------------------------------------------------------------------ Run & support

def r_watch(ctx: wb.Ctx) -> dict:
    rs = _rs_or_fail(ctx)
    ctx.put("ruleset", rs["id"])
    ctx.put("datasets", rs["datasets"])
    results = qr.run_rules(ctx, rs["rules"], {d["key"]: d for d in rs["datasets"]}, time.time(), label=f"Run {len(ctx.st.get('rounds') or []) + 1}")
    record_lineage(ctx, rs, results)
    ctx.put("results", results)
    t = qr.tally(results)
    return {"summary": f"Version {rs['version']}: {t['rules']} rule(s) checked — {t['pass']} pass, {t['fail']} fail ({t['high fail']} high)" + (f", {t['error']} could not run" if t["error"] else "") + ".",
            "counts": {"rules": t["rules"], "pass": t["pass"], "fail": t["fail"]}, "data": _gates(results)}


def _breaks(ctx: wb.Ctx) -> list[dict]:
    res = [g for g in ctx.get("results") or [] if g["status"] in ("fail", "error")]
    dmap = _dmap(ctx)
    groups: dict = {}
    for g in res:
        groups.setdefault((g.get("dataset"), g.get("kind")), []).append(g)
    out = []
    for (key, kind), gs in groups.items():
        sev = "high" if any(g.get("severity") == "high" for g in gs) else "medium" if any(g.get("severity") == "medium" for g in gs) else "low"
        out.append({"id": f"b-{qr.slug(key)[:30]}-{kind}", "dataset": (dmap.get(key) or {}).get("name", "?"), "kind": qr.KINDS.get(kind, kind), "rules": len(gs), "severity": sev,
                    "what": "; ".join(g["detail"] for g in gs)[:500], "cause": CAUSE.get(kind, "see the evidence"), "route": ROUTE_FOR.get(kind, "ticket"), "note": "",
                    "evidence": [g["evidence"] for g in gs], "dataset_key": key, "rule_kind": kind})
    return out


def r_alert(ctx: wb.Ctx) -> dict:
    brks = _breaks(ctx)
    ctx.put("breaks", brks)
    if not brks:
        return {"summary": "Every check passed: nothing to alert.", "next": "report", "counts": {"breaks": 0}}
    overlap = wb._observe_overlap({**ctx.st, "data": ctx.data})
    items = [f"{b['dataset']}: {b['kind']} — {b['what'][:160]}" for b in brks[:6]]
    if overlap:
        items.append("Data observability watches the same table(s): " + ", ".join(o["label"] + (f" (open incident: {o['incident_title']})" if o.get("incident") else "") for o in overlap))
    return {"summary": f"{len(brks)} break(s) on {len({b['dataset'] for b in brks})} dataset(s), grouped by what failed, each with its likely cause.",
            "counts": {"breaks": len(brks), "high": sum(1 for b in brks if b["severity"] == "high")}, "items": items,
            "data": {"columns": ["Dataset", "What failed", "Rules", "Severity", "Likely cause", "Measured"], "rows": [[b["dataset"], b["kind"], b["rules"], b["severity"], b["cause"], b["what"][:200]] for b in brks]}}


def r_fix(ctx: wb.Ctx) -> dict:
    have = {r["id"]: r for r in ctx.records(ctx.step_id)}
    recs = [{**b, **({k: have[b["id"]][k] for k in ("route", "note") if k in have[b["id"]]} if b["id"] in have else {})} for b in ctx.get("breaks") or []]
    return {"summary": f"{len(recs)} break(s): choose who fixes each — a ticket to the service desk, Self-healing, or mark it expected. Nothing goes out until you confirm.",
            "records": recs, "counts": {"tickets": sum(1 for r in recs if r["route"] == "ticket"), "self-healing": sum(1 for r in recs if r["route"] == "heal")},
            "data": {"columns": ["Dataset", "What failed", "Severity", "Proposed route", "Likely cause"], "rows": [[r["dataset"], r["kind"], r["severity"], r["route"], r["cause"]] for r in recs]}}


FIX_EDIT = wb.Edit(columns=[wb.Column("route", "Route", "select", options=(("ticket", "Raise a ticket"), ("heal", "Self-healing"), ("expected", "Expected — no action"), ("ignore", "Ignore this time"))),
                            wb.Column("note", "Note for whoever fixes it", "longtext"), wb.Column("dataset", "Dataset", readonly=True), wb.Column("kind", "What failed", readonly=True),
                            wb.Column("severity", "Severity", readonly=True)], add=False, remove=False, label="break")


def r_approve(ctx: wb.Ctx) -> dict:
    rows, done = [], []
    for b in ctx.records("fix"):
        title = f"{b['dataset']}: {b['kind']} check failed"
        body = f"{b['what']}\n\nLikely cause: {b['cause']}\n\n{('Note: ' + b['note']) if b.get('note') else ''}\nWork item: {wb.route_of(ctx.st)}"
        if b["route"] == "heal":
            h = ctx.heal(title, body, place=f"{b['dataset']} ({wb.registry.BY_ID[MODULE]['short']})", signature=f"quality:{b['rule_kind']}", subject={"dataset": b["dataset"]})
        elif b["route"] == "ticket":
            h = ctx.ticket(title, body, priority={"high": "P2", "medium": "P3"}.get(b["severity"], "P4"), about=b["dataset"])
        else:
            h = {"kind": b["route"], "label": title, "status": "expected — recorded" if b["route"] == "expected" else "ignored this time"}
        done.append(h)
        rows.append([b["dataset"], b["kind"], {"heal": "Self-healing", "ticket": "Ticket", "expected": "Expected", "ignore": "Ignored"}[b["route"]], h.get("status"), h.get("case") or h.get("checkpoint") or h.get("output") or ""])
    return {"summary": f"{sum(1 for h in done if h['kind'] == 'heal')} to Self-healing, {sum(1 for h in done if h['kind'] == 'ticket')} ticket(s), {sum(1 for h in done if h['kind'] in ('expected', 'ignore'))} without action — as you approved.",
            "data": {"columns": ["Dataset", "What failed", "Route", "Status", "Reference"], "rows": rows}, "counts": {"hand-offs": len(done)}}


def r_report(ctx: wb.Ctx) -> dict:
    rounds = (ctx.st.get("rounds") or [])[-11:]
    t = qr.tally(ctx.get("results") or [])
    hist = []
    for r in rounds:
        w = next((s for s in r["steps"] if s["id"] == "watch"), {})
        c = w.get("counts") or {}
        hist.append([time.strftime("%d %b %H:%M", time.gmtime(r["ended"])), c.get("pass"), c.get("fail")])
    hist.append([time.strftime("%d %b %H:%M", time.gmtime()), t["pass"], t["fail"]])
    rate = round(100 * t["pass"] / t["rules"], 1) if t["rules"] else None
    text = f"# Quality report: {ctx.title}\n\n{time.strftime('%d %B %Y %H:%M UTC', time.gmtime())}\n\n- Rules checked: {t['rules']}\n- Passed: {t['pass']}\n- Failed: {t['fail']} ({t['high fail']} high)\n" \
           + "".join(f"- Break: {b['dataset']} · {b['kind']} → {b['route']}\n" for b in ctx.records("fix")) + "\n## Recent runs\n\n" + "".join(f"- {h[0]}: {h[1]} pass, {h[2]} fail\n" for h in hist)
    ctx.output(f"report-{time.strftime('%Y%m%d-%H%M', time.gmtime())}.md", text, label="Run report (Markdown)")
    return {"summary": f"{t['pass']} of {t['rules']} rule(s) passed" + (f" ({rate} %)" if rate is not None else "") + f"; {t['fail']} break(s) this run.",
            "counts": {"passed %": rate if rate is not None else 0, "breaks": t["fail"]}, "data": {"columns": ["Run", "Passed", "Failed"], "rows": hist}}


def _cards(u: dict) -> list[dict]:
    rows = [[r["name"], f"v{r['version']}", len(r["rules"]), len(r["datasets"]), (db.user(r.get("published_by") or "") or {}).get("name") or "—",
             time.strftime("%d %b %Y", time.gmtime(r["published"])) if r.get("published") else "—", f"#/m/{MODULE}/i/{r['run_item']}" if r.get("run_item") else ""] for r in rulesets(u)]
    return [{"title": "Live rule sets", "columns": ["Rule set", "Version", "Rules", "Datasets", "Published by", "When", "Run item"], "rows": rows,
             "empty": "No rule set is live yet: a Develop item's Run step publishes one."}]


GUIDE = """# Data quality & reconciliation — the work item

This folder is one work item of Relay's Data quality & reconciliation module. Rules are written by people and by the
app's own rules engine; the agent is only asked to draft the plain-English wording of rules a person already chose.

- `rules.json` (written by the app before your run): the rules — id, kind, dataset, column, check, severity.
- Rule kinds: not_null (no blanks), unique (no repeats), range (a number range or accepted values), referential
  (every value exists in another dataset's column), freshness (the newest value is recent enough), business_total (a
  total ties out to a figure from Finance), reconcile (a target agrees with its source: counts, checksums, totals,
  sample rows).
- `rules_wording.yaml`: what you write when asked — `wording:` mapping each rule id to one sentence.
- `data/`: the person's uploads; `evidence/`: what earlier steps measured (profiles, check results).

Never change a rule, never invent a table, column or number; say what you assumed."""


wb.register(wb.Pack(
    module=MODULE, guide=GUIDE,
    lineage="each checked table, the rule set as a job that reads it (system “Relay quality”), and source → target reconciliations as feeds edges",
    platforms={"warehouse": WAREHOUSE, "files": FILES},
    schemas={"rule": RULE_COLUMNS, "finding": FINDINGS_EDIT.columns, "break": FIX_EDIT.columns},
    cards=_cards,
    work={
        "assess": wb.Work(title="Profile what you have and get rules suggested from the data", steps={
            "Connect": wb.Step(kind="platform", run=a_connect, agent="Connector", text="Each connection is tested and each upload opened — read-only, with the person's own sign-in"),
            "Inventory": wb.Step(kind="platform", run=a_inventory, agent="Scanner", text="Every table and file the sources show, with its rows and columns — you untick what is out of scope", edit=wb.Edit(columns=[wb.Column("include", "Include", "bool"), wb.Column("dataset", "Table or file", readonly=True),
                                                                                                        wb.Column("where", "Where", readonly=True), wb.Column("rows", "Rows", "number", readonly=True),
                                                                                                        wb.Column("columns", "Columns", "number", readonly=True)], add=False, remove=False, label="table")),
            "Health": wb.Step(kind="proof", run=a_health, view="gates", agent="Profiler", text="Each included table is profiled — blanks, repeats, ranges, the newest date — and rules are suggested from what the data shows: rules first, no AI"),
            "Findings": wb.Step(kind="person", run=a_findings, edit=FINDINGS_EDIT, text="What fails today, with the rule that would catch it — you keep or ignore each finding"),
            "Estimate": wb.Step(kind="deterministic", run=a_estimate, view="plan", agent="Estimator", text="Waves by risk, with the time a person needs to confirm the rules — and the cost at your hourly rate when one is set")},
            fields=[wb.Field("objects", "Tables or views to look at", "longtext", help="One per line, e.g. SALES.ORDERS. Blank: the first tables the connection shows.")]),
        "develop": wb.Work(title="Author the rules with Relay's suggestions, prove them on the data, take them live", needs_source=False, steps={
            "Describe": wb.Step(kind="platform", run=d_describe, agent="Connector", text="The tables you named and the files you uploaded are read — rows and columns — and an Excel tie-out's figures are picked up"),
            "Shape": wb.Step(kind="deterministic", run=d_shape, agent="Rule writer", edit=RULES_EDIT, confirm="the rule set — every rule with its check and why it is suggested",
                             text="Rules suggested from the data — not null, unique, ranges and accepted values, exists in, freshness, totals from your tie-out, reconciliation; you add, change or switch off rules (Relay can draft the wording)",
                             actions={"wording": wb.Action(label="Ask Relay to draft the wording", kind="agent", prompt=_wording_prompt, check=_wording_check, after=_wording_after,
                                                           agent="Rule writer", help="The agent writes one plain-English sentence per rule; the rules do not change.")}),
            "Build": wb.Step(kind="deterministic", run=d_build, agent="Check builder", text="Each rule becomes SQL in its warehouse's own dialect; the set is exported as dbt tests, Soda checks and a Great Expectations suite"),
            "Prove": wb.Step(kind="proof", run=d_prove, view="gates", agent="Prover", back_to="shape", text="Every rule runs on the data now; failures come with sample rows as evidence"),
            "Ship": wb.Step(kind="person", run=d_ship, view="plan", approver=True, text="The named approver confirms what goes live and how often it is checked"),
            "Run": wb.Step(kind="deterministic", run=d_run, view="link", agent="Publisher", text="The rule set is published as a new version and a Run item checks it on the schedule you chose")},
            fields=[wb.Field("objects", "Tables or views to check", "longtext", help="One per line, e.g. SALES.ORDERS. Blank: the first tables the connection shows."),
                    wb.Field("from_item", "Start from an assessment", "select", options=assess_options, help="Its suggested rules (minus what you ignored) are the starting point."),
                    wb.Field("cadence", "Once live, check them", "cadence", default={"every": "day", "at": "06:00", "tz": "UTC"})]),
        "change": wb.Work(title="Change a live rule set, proven on the data before it is released", needs_source=False, sources=False, platforms=("warehouse", "files"), steps={
            "Request": wb.Step(kind="deterministic", run=c_request, view="text", agent="Rule librarian", text="The change in plain words, and the live rule set it changes"),
            "Diagnose": wb.Step(kind="proof", run=c_diagnose, view="gates", agent="Prover", text="Today's rules run on today's data, so you see what passes and fails before anything changes"),
            "Fix": wb.Step(kind="person", run=c_fix, edit=RULES_EDIT, confirm="the edited rule set", text="You edit the rules in place — change a check, add or switch off a rule"),
            "Prove": wb.Step(kind="proof", run=c_prove, view="gates", agent="Prover", back_to="fix", text="A dry run of the edited rules on the data, compared with today's results"),
            "Approve": wb.Step(kind="person", run=c_approve, view="plan", approver=True, text="The named approver releases the new version"),
            "Learn": wb.Step(kind="deterministic", run=c_learn, view="link", agent="Publisher", text="The new version is published and kept; the Run item uses it from its next check")},
            fields=[wb.Field("ruleset", "Rule set to change", "select", options=ruleset_options, required=True)]),
        "run": wb.Work(title="Check a live rule set on a schedule; breaks go to a person first", needs_source=False, sources=False, platforms=("warehouse", "files"), steps={
            "Watch": wb.Step(kind="proof", run=r_watch, view="gates", agent="Watcher", text="The live rule set runs on its schedule — every rule, read-only"),
            "Alert": wb.Step(kind="deterministic", run=r_alert, agent="Triage", text="Breaks grouped by table and what failed, each with its likely cause and any Data observability incident on the same table"),
            "Fix": wb.Step(kind="deterministic", run=r_fix, agent="Triage", edit=FIX_EDIT, text="Relay proposes who fixes each break — a ticket, Self-healing or expected — and you confirm or change it"),
            "Approve": wb.Step(kind="platform", run=r_approve, agent="Dispatcher",
                               text="The approved hand-offs go out: a Self-healing case (it proposes and tests a fix before anything changes) or a ticket through the service desk's own write approval"),
            "Report": wb.Step(kind="deterministic", run=r_report, agent="Reporter", confirm_if=lambda ctx, out: bool(ctx.get("breaks")),
                              text="A run report — what passed and failed, against the last runs; you confirm it when there were breaks")},
            fields=[wb.Field("ruleset", "Rule set to check", "select", options=ruleset_options, required=True),
                    wb.Field("schedule", "Check it", "cadence", default={"every": "day", "at": "06:00", "tz": "UTC"})]),
    }))
