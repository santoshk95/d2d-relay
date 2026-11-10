"""Ontology & semantic models (registry id `semantics`) — the industry packs on the workbench: finance, supply chain and
operations, each the entities of its industry with keys and relations, the metrics and KPIs a team certifies, and a
sample-data recipe whose tables they are built on. Built on what Relay has: the ontology (entities and relations),
Formulas & metrics (drafts and their four-eyes review) and Sample & synthetic data (genbi_kit.datagen recipes). The
module's own screens stay where they are (#/metrics); this pack adds its Develop work.

Develop  Describe → Shape → Build → Prove → Ship → Run: an industry pack compared with what the workspace already holds
         (an entity or metric of the same meaning is kept, not doubled); shaped by a person; the sample data generated
         from the pack's recipe; proven on it in DuckDB (every key unique, every relation joins, every metric gives a
         number, each KPI measured against its target, every planted story found); approved; installed — entities
         and relations into the ontology, metrics as drafts for their review, the recipe for new demos.
"""
from __future__ import annotations

import io
import json
import re
import zipfile

import yaml

from .. import db, semantic
from .. import workbench as wb
from . import semantics_industry as si

MODULE = "semantics"
CHOICES = tuple((k, p["title"]) for k, p in si.PACKS.items())


def _canon(s: str) -> str:
    w = re.findall(r"[a-z0-9%]+", (s or "").lower())
    return " ".join(x[:-1] if len(x) > 3 and x.endswith("s") and not x.endswith("ss") else x for x in w)


def _pack(ctx: wb.Ctx) -> dict:
    pid = ctx.scope.get("pack") or "finance"
    if pid not in si.PACKS:
        raise wb.StepFailed(f"Pick an industry pack: {', '.join(p['title'] for p in si.PACKS.values())}.")
    return si.PACKS[pid]


def d_describe(ctx: wb.Ctx) -> dict:
    p = _pack(ctx)
    have_e = {_canon(e["name"]): e for e in semantic.ontology()["entities"]}
    for e in semantic.ontology()["entities"]:
        for s in e.get("synonyms") or []:
            have_e.setdefault(_canon(s), e)
    have_m = {_canon(m["name"]): m for m in semantic.metrics()}
    rows = []
    for e in p["entities"]:
        hit = have_e.get(_canon(e["name"])) or next((have_e[_canon(s)] for s in e["synonyms"] if _canon(s) in have_e), None)
        rows.append(["entity", e["name"], f"already there as {hit['name']}" if hit else "new"])
    for m in p["metrics"]:
        hit = have_m.get(_canon(m["name"]))
        rows.append(["metric", m["name"], f"already there ({hit['status']})" if hit else "new"])
    ctx.put("existing", {"entities": {k: v["name"] for k, v in have_e.items()}, "metrics": {k: v["name"] for k, v in have_m.items()}})
    new = sum(1 for r in rows if r[2] == "new")
    return {"summary": f"The {p['title']} pack: {len(p['entities'])} entities, {len(p['relations'])} relations, {len(p['metrics'])} metrics — {new} new to this workspace, the rest already here.",
            "counts": {"entities": len(p["entities"]), "metrics": len(p["metrics"]), "new": new},
            "data": {"columns": ["Kind", "Name", "In this workspace"], "rows": rows}}


def d_shape(ctx: wb.Ctx) -> dict:
    p = _pack(ctx)
    ex = ctx.get("existing") or {"entities": {}, "metrics": {}}
    have = {r["id"]: r for r in ctx.records(ctx.step_id)}
    recs = []
    for e in p["entities"]:
        hit = ex["entities"].get(_canon(e["name"])) or next((ex["entities"][_canon(s)] for s in e["synonyms"] if _canon(s) in ex["entities"]), None)
        recs.append({"id": f"e:{e['name']}", "kind": "entity", "name": e["name"], "description": e["description"], "synonyms": ", ".join(e["synonyms"]),
                     "dax": "", "target": None, "action": "keep" if hit else "add", "why": f"already there as {hit}" if hit else "new", "existing": hit or ""})
    for m in p["metrics"]:
        hit = ex["metrics"].get(_canon(m["name"]))
        k = m.get("kpi") or {}
        recs.append({"id": f"m:{m['name']}", "kind": "metric", "name": m["name"], "description": m["description"], "synonyms": "", "dax": m["dax"],
                     "target": k.get("target"), "action": "keep" if hit else "add", "why": f"already there as {hit}" if hit else (f"a KPI: {k.get('better')} is better" if k else "a metric")})
    for r in recs:
        if r["id"] in have:
            r.update({x: have[r["id"]][x] for x in ("name", "description", "synonyms", "dax", "target", "action") if x in have[r["id"]]})
    n = {a: sum(1 for r in recs if r["action"] == a) for a in ("add", "keep", "skip")}
    return {"summary": f"Add {n['add']}, keep {n['keep']} already here, skip {n['skip']} — change names, definitions and targets before you confirm.", "counts": n, "records": recs,
            "data": {"columns": ["Kind", "Name", "Action", "Definition", "Target", "Why"], "rows": [[r["kind"], r["name"], r["action"], r["description"], r["target"], r["why"]] for r in recs]}}


def _validate(recs: list[dict], ctx: wb.Ctx | None = None) -> list[str]:
    out = []
    names = [(_canon(r.get("name") or ""), r.get("kind")) for r in recs if r.get("action") == "add"]
    out += [f"two {k}s mean the same ({n}) — skip one" for n, k in sorted({x for x in names if names.count(x) > 1})]
    for r in recs:
        if r.get("action") == "add" and len(str(r.get("description") or "").split()) < 4:
            out.append(f"{r.get('name')}: a definition is a sentence (four words or more)")
        if r.get("kind") == "metric" and r.get("action") == "add" and not str(r.get("dax") or "").strip():
            out.append(f"{r.get('name')}: a metric needs its DAX")
    return out


SHAPE_EDIT = wb.Edit(columns=[wb.Column("action", "Action", "select", options=(("add", "Add"), ("keep", "Keep what is here"), ("skip", "Skip"))), wb.Column("name", "Name", required=True),
                              wb.Column("description", "Definition", "longtext"), wb.Column("synonyms", "Synonyms"), wb.Column("dax", "DAX", "longtext"), wb.Column("target", "KPI target", "number"),
                              wb.Column("kind", "Kind", readonly=True), wb.Column("why", "Why", readonly=True)], add=False, remove=False, label="part", validate=_validate)


def d_build(ctx: wb.Ctx) -> dict:
    from genbi_kit import datagen
    p = _pack(ctx)
    recipe = yaml.safe_load(p["recipe"])
    d = ctx.dir / "sample"
    (d / "data").mkdir(parents=True, exist_ok=True)
    (d / "datagen.yaml").write_text(p["recipe"], encoding="utf-8")
    probs, plan = datagen.check(recipe, d / "data")
    if probs:
        raise wb.StepFailed("The pack's sample-data recipe has problems: " + "; ".join(probs)[:400])
    gen = datagen.generate(plan, d / "data")
    files = sorted((d / "data").glob("*.csv"))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("datagen.yaml", p["recipe"])
        for f in files:
            z.write(f, f"data/{f.name}")
    ctx.output("sample-data.zip", buf.getvalue(), label="The sample data and its recipe (datagen.yaml)")
    ctx.output("datagen.yaml", p["recipe"], label="The sample-data recipe (Sample & synthetic data)")
    shaped = [r for r in ctx.records("shape") if r["action"] != "skip"]
    ctx.output("semantic-model.json", json.dumps({"pack": p["title"], "entities": [r for r in shaped if r["kind"] == "entity"], "relations": p["relations"],
                                                  "metrics": [r for r in shaped if r["kind"] == "metric"]}, indent=1, default=str), label="The semantic model (JSON)")
    rows = {f.stem: sum(1 for _ in f.open(encoding="utf-8")) - 1 for f in files}
    ctx.put("tables", rows)
    return {"summary": f"{len(files)} sample table(s), {sum(rows.values())} row(s), from the pack's recipe — the stories it plants: {'; '.join(recipe.get('story') or [])}.",
            "counts": {"tables": len(files), "rows": sum(rows.values())}, "data": {"text": "\n".join(f"{k}: {v} row(s)" for k, v in rows.items()) + f"\n\n{p['recipe']}"}}


def _con(ctx: wb.Ctx):
    import duckdb
    con = duckdb.connect()
    for f in sorted((ctx.dir / "sample" / "data").glob("*.csv")):
        con.execute(f"CREATE TABLE \"{f.stem}\" AS SELECT * FROM read_csv_auto('{f.as_posix()}')")
    return con


def d_prove(ctx: wb.Ctx) -> dict:
    p = _pack(ctx)
    con = _con(ctx)
    checks = []
    names = {e["name"]: e for e in p["entities"]}
    bad = []
    for e in p["entities"]:
        for t, col in e["keys"]:
            try:
                n, u = con.execute(f'SELECT COUNT(*), COUNT(DISTINCT "{col}") FROM "{t}"').fetchone()
            except Exception as ex:  # noqa: BLE001
                bad.append(f"{e['name']}: {t}.{col} is not in the sample ({str(ex).splitlines()[0][:80]})")
                continue
            if n != u or not n:
                bad.append(f"{e['name']}: {t}.{col} is not unique ({u} of {n})")
    checks.append({"name": "keys", "label": "Every entity's key is in the sample and unique", "status": "fail" if bad else "pass", "detail": "; ".join(bad)[:400] or f"{len(p['entities'])} key(s)"})
    joins = []
    for a, verb, b in p["relations"]:
        ta, tb = names[a]["keys"][0][0], names[b]["keys"][0]
        try:
            cols = {r[0] for r in con.execute(f'DESCRIBE "{ta}"').fetchall()}
            if tb[1] not in cols:
                joins.append(f"{a} {verb} {b}: {ta} has no {tb[1]}")
                continue
            miss = con.execute(f'SELECT COUNT(*) FROM "{ta}" x WHERE x."{tb[1]}" IS NOT NULL AND x."{tb[1]}" NOT IN (SELECT "{tb[1]}" FROM "{tb[0]}")').fetchone()[0]
            if miss:
                joins.append(f"{a} {verb} {b}: {miss} row(s) of {ta} find no {b}")
        except Exception as ex:  # noqa: BLE001
            joins.append(f"{a} {verb} {b}: {str(ex).splitlines()[0][:80]}")
    checks.append({"name": "relations", "label": "Every relation joins", "status": "fail" if joins else "pass", "detail": "; ".join(joins)[:400] or f"{len(p['relations'])} relation(s)"})
    kpis = []
    for m in p["metrics"]:
        try:
            v = con.execute(m["query"]).fetchone()[0]
        except Exception as ex:  # noqa: BLE001
            checks.append({"name": f"m:{m['name']}", "label": f"{m['name']} gives a number", "status": "fail", "detail": str(ex).splitlines()[0][:200]})
            continue
        k = m.get("kpi") or {}
        good = None if not k or v is None else (float(v) >= k["target"] if k["better"] == "higher" else float(v) <= k["target"])
        kpis.append({"metric": m["name"], "value": None if v is None else round(float(v), 4), "target": k.get("target"), "on target": good})
        checks.append({"name": f"m:{m['name']}", "label": f"{m['name']} gives a number", "status": "pass" if v is not None else "fail", "measured": None if v is None else round(float(v), 4),
                       "expected": k.get("target"), "detail": (f"{round(float(v), 4)} against a target of {k['target']} ({'on target' if good else 'off target — a story to show'})" if k else f"{v}") if v is not None else "no value"})
    ctx.put("kpis", kpis)
    for s in p["stories"]:
        try:
            v = con.execute(s["query"]).fetchone()[0]
            ok_ = v is not None and bool(eval(f"{float(v)} {s['check']}", {"__builtins__": {}}))  # noqa: S307 - the pack's own comparison, e.g. "> 1.5"
        except Exception as ex:  # noqa: BLE001
            v, ok_ = str(ex).splitlines()[0][:80], False
        checks.append({"name": f"s:{s['story']}", "label": f"The story is in the data: {s['story']}", "status": "pass" if ok_ else "fail", "measured": v, "expected": s["check"],
                       "detail": f"measured {v} ({s['check']} expected)"})
    con.close()
    ev = ctx.evidence("KPIs measured on the sample", kpis, kind="proof", ok=True)
    checks.append({"name": "kpis", "label": "Each KPI measured against its target", "status": "pass", "detail": f"{sum(1 for k in kpis if k['on target'])} of {sum(1 for k in kpis if k['target'] is not None)} on target", "evidence": ev})
    return {"summary": f"{sum(1 for c in checks if c['status'] == 'pass')} of {len(checks)} proof(s) hold on the sample data.", "data": {"checks": checks}}


def d_ship(ctx: wb.Ctx) -> dict:
    recs = [r for r in ctx.records("shape") if r["action"] == "add"]
    return {"summary": "The named approver confirms the pack goes into the ontology and Formulas & metrics.",
            "data": {"items": [{"title": f"{r['kind'].title()}: {r['name']}", "detail": r["description"], "effort": ""} for r in recs], "total": f"{len(recs)} to add"}}


def d_run(ctx: wb.Ctx) -> dict:
    p = _pack(ctx)
    u = db.user(ctx.owner or "")
    team = (db.project(ctx.id) or {}).get("team_id") or next((t["id"] for t in (u or {}).get("teams", []) if t["role"] == "dev"), None)
    if not u or not team:
        raise wb.StepFailed("The pack is installed for a team: the work item's owner needs a team where they are a BI Dev / Analyst.")
    recs = ctx.records("shape")
    ids, made_e, made_m, skipped = {}, [], [], []
    for e in semantic.ontology()["entities"]:
        ids[_canon(e["name"])] = e["id"]
    for r in [x for x in recs if x["kind"] == "entity"]:
        src = next(e for e in p["entities"] if e["name"] in (r["name"], r["id"][2:]))
        if r["action"] == "add":
            try:
                e = semantic.save_entity({"name": r["name"], "description": r["description"], "synonyms": r.get("synonyms") or "", "status": "published", "owner_team_id": team,
                                          "keys": [{"source": f"pack:{p['title']}", "tbl": t, "col": c} for t, c in src["keys"]]}, u)
                ids[_canon(r["name"])] = e["id"]
                made_e.append(r["name"])
            except semantic.SemanticError as ex:
                skipped.append(f"{r['name']}: {ex}")
        ids.setdefault(_canon(src["name"]), ids.get(_canon(r["name"])) or ids.get(_canon(r.get("existing") or "")))   # kept: the entity already here
    for a, verb, b in p["relations"]:
        if ids.get(_canon(a)) and ids.get(_canon(b)):
            try:
                semantic.relate(ids[_canon(a)], verb, ids[_canon(b)], u)
            except semantic.SemanticError as ex:
                skipped.append(f"{a} {verb} {b}: {ex}")
    for r in [x for x in recs if x["kind"] == "metric" and x["action"] == "add"]:
        src = next(m for m in p["metrics"] if m["name"] in (r["name"], r["id"][2:]))
        k = src.get("kpi") or {}
        desc = r["description"] + (f" KPI target: {r.get('target')} ({k.get('unit')}, {k.get('better')} is better)." if r.get("target") is not None and k else "")
        try:
            semantic.save_draft(team, r["name"], {"label": r["name"], "description": desc, "dax": r.get("dax") or src["dax"], "sql": src["sql"], "format": src.get("format"), "folder": p["title"]},
                                u, source=f"wb:{ctx.id}")
            made_m.append(r["name"])
        except semantic.SemanticError as ex:
            skipped.append(f"{r['name']}: {ex}")
    db.audit("semantics.pack.installed", ctx.id, {"pack": p["title"], "entities": made_e, "metrics": made_m, "skipped": skipped}, ctx.who or ctx.owner)
    return {"summary": f"{len(made_e)} entit(ies) and their relations in the ontology; {len(made_m)} metric(s) as drafts in Formulas & metrics for their four-eyes review"
                       + (f"; not installed: {'; '.join(skipped)[:300]}" if skipped else "") + "; the sample data and its recipe are this item's outputs.",
            "counts": {"entities": len(made_e), "metrics": len(made_m)}, "data": {"href": "#/metrics", "label": "Formulas & metrics", "text": ", ".join(made_m[:6])}}


def _cards(u: dict) -> list[dict]:
    rows = [[p["title"], p["summary"], len(p["entities"]), len(p["metrics"])] for p in si.PACKS.values()]
    return [{"title": "Industry packs", "columns": ["Pack", "What it holds", "Entities", "Metrics"], "rows": rows, "empty": ""}]


GUIDE = """# Ontology & semantic models — an industry pack

This folder is one work item installing an industry pack: entities, relations, metrics with KPI targets and a
sample-data recipe. Every step is rules; no agent is needed. The sample data is generated from the recipe with
genbi_kit.datagen, and every metric is proven on it before anything is installed."""


wb.register(wb.Pack(
    module=MODULE, guide=GUIDE,
    lineage="the pack's entities and metrics over the tables of its sample data",
    platforms={"packs": type("IndustryPacks", (wb.Platform,), {"kinds": (), "label": "Relay's industry packs", "uploads": (),
                                                                 "reads": "finance, supply chain and operations — entities, metrics, KPIs and a sample-data recipe each"})()},
    schemas={"part": SHAPE_EDIT.columns},
    cards=_cards,
    work={
        "develop": wb.Work(title="Install an industry pack: entities, metrics and KPIs, proven on its sample data, then into the ontology and Formulas & metrics", needs_source=False, steps={
            "Describe": wb.Step(kind="deterministic", run=d_describe, agent="Ontologist", text="The pack, compared with the entities and metrics this workspace already has"),
            "Shape": wb.Step(kind="deterministic", run=d_shape, agent="Ontologist", edit=SHAPE_EDIT, text="Each entity and metric to add, keep or skip, with its definition, DAX and KPI target — you change and confirm them"),
            "Build": wb.Step(kind="deterministic", run=d_build, view="text", agent="Data generator", text="The sample data generated from the pack's recipe, with the stories it plants"),
            "Prove": wb.Step(kind="proof", run=d_prove, view="gates", agent="Prover", back_to="shape",
                             text="On the sample: every key unique, every relation joins, every metric gives a number, each KPI against its target, every story found"),
            "Ship": wb.Step(kind="person", run=d_ship, view="plan", approver=True, text="The named approver confirms the pack"),
            "Run": wb.Step(kind="deterministic", run=d_run, view="link", agent="Publisher", text="Entities and relations into the ontology; metrics as drafts for their four-eyes review")},
            fields=[wb.Field("pack", "Industry pack", "select", options=CHOICES, default="finance")]),
    }))
