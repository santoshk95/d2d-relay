"""Data governance & catalogue (registry id `governance`) - who owns what, where it comes from and whether it can be
trusted, synced with your catalogue: Microsoft Purview, Collibra, Alation, Atlan and Unity Catalog through their APIs
(or a catalogue export), the mock lab's simulators standing in for each. Builds on what Relay already keeps: its
lineage graph (the catalogue's lineage joins it), its certified metrics (they become glossary terms) and its gates.

Assess   Connect -> Inventory -> Health -> Findings -> Estimate: every governed asset with its owner, certificate and
         classification; rules find what has no owner, personal data left unclassified, duplicate terms and terms without a definition,
         failing scans, deprecated assets still in use; the fixes estimated.
Develop  Describe -> Shape -> Build -> Prove -> Ship -> Run: a business glossary from Relay's certified metrics and the
         catalogue's terms - duplicates merged by rules, linked to the tables they come from, proven, approved, then
         written to the catalogue through its write approval.
Change   Request -> Diagnose -> Fix -> Prove -> Approve -> Learn: the catalogue's findings fixed - owners, classifications,
         definitions, descriptions; rules propose each value (Relay's agent drafts what no rule can), a person
         confirms, the approver releases, the catalogue is written only through its own approval; fixes are kept as
         rules for next time.
Migrate  Discover -> Decide -> Convert -> Prove -> Hand over -> Run: one catalogue's curation (owners, descriptions,
         classifications, certificates, terms) carried to another - matched asset by asset, proven, signed off,
         written with approval, then watched.
Run      Watch -> Alert -> Fix -> Approve -> Report: each round, failing scans and new gaps; a person routes each to
         Self-healing, a ticket or a Change item.
"""
from __future__ import annotations

import json
import re
import time

from .. import connectors, db, registry, semantic
from .. import workbench as wb
from . import _w1, _w1_cat
from . import governance_rules as gr

MODULE = "governance"
SYSTEM = "Relay governance"

db.register_schema("""
CREATE TABLE IF NOT EXISTS governance_rules (
  id TEXT PRIMARY KEY, kind TEXT NOT NULL, pattern TEXT NOT NULL, change TEXT NOT NULL, value TEXT NOT NULL, catalogue TEXT, item TEXT, by TEXT, created REAL NOT NULL);
""")


class Catalogue(wb.Platform):
    label = "Your data catalogue"
    kinds = _w1_cat.CATALOG_KINDS
    uploads = (".json", ".csv", ".zip")
    simulator = "tests/mocklab/sims: purview, collibra, alation, atlan (catalogs.py); Unity Catalog in databricks_sql"
    reads = "assets, owners, classifications, certificates, lineage, the glossary and scan runs - read-only; it writes only through its own approval per change"


CAT = Catalogue()


def _conns(ctx: wb.Ctx) -> list[dict]:
    return [c for c in ctx.connections() if c["kind"] in CAT.kinds]


def read(ctx: wb.Ctx, c: dict | None = None) -> dict:
    """The neutral catalogue: of the connection given, else the item's first catalogue, else its uploaded export."""
    if c is None:
        cs = _conns(ctx)
        c = cs[0] if cs and not ctx.files(CAT.uploads) else None
    if c:
        try:
            cat = _w1_cat.read(c)
        except connectors.Reconsent:
            raise
        except connectors.ConnectorError as e:
            raise wb.StepFailed(f"{c['name']} could not be read: {e}") from e
        cat["where"], cat["connection"] = c["name"], c["id"]
        return cat
    files = [ctx.dir / "data" / f["name"] for f in ctx.files(CAT.uploads)]
    if not files:
        raise wb.StepFailed("Pick the catalogue's connection (Purview, Collibra, Alation, Atlan or Unity Catalog) or upload its export (Atlas JSON or a Collibra CSV).")
    cat = gr.from_files(files)
    if not cat["assets"] and not cat["terms"]:
        raise wb.StepFailed("The export holds no assets or terms Relay can read (an Atlas JSON with entities, or a Collibra CSV export).")
    cat["where"], cat["connection"] = ", ".join(f.name for f in files), None
    return cat


def _who(v) -> str:
    return str(v or "-")


def _hours(m: float) -> str:
    return f"{m / 60:.1f} h"


def _cost(h: float) -> str:
    b = registry.brand()
    rate, cur = float(b.get("hourly_rate") or 0), b.get("currency") or ""
    return f" - {cur}{rate * h:,.0f}" if rate else ""


def _learned() -> list[dict]:
    return db.q("SELECT * FROM governance_rules ORDER BY created DESC LIMIT 200")


def _ask_write(ctx: wb.Ctx, c: dict, ops: list[dict], what: str) -> dict:
    try:
        cp = connectors.request_write(c, "catalogue", {"ops": ops}, ctx.who or ctx.owner, module=ctx.module_name, what=what,
                                      items=[o.get("what") or o.get("path") for o in ops][:40], link=wb.route_of(ctx.st))
    except Exception as e:  # noqa: BLE001 - ScopeError / ConnectorError: shown to the person
        raise wb.StepFailed(str(e)) from e
    ctx._handoff({"kind": "write", "label": what, "connection": c["name"], "checkpoint": cp["id"], "status": "awaiting approval", "link": "#/validate"})
    return cp


# ================================================================== Assess

def a_connect(ctx: wb.Ctx) -> dict:
    rows = CAT.test(ctx)
    if not rows:
        raise wb.StepFailed("Nothing to read: pick the catalogue's connection or upload its export.")
    good = [r for r in rows if r["ok"]]
    if not good:
        raise wb.StepFailed("No catalogue answered: " + "; ".join(f"{r['source']}: {r['sees']}" for r in rows)[:600])
    return {"summary": f"{len(good)} of {len(rows)} source(s) answered - read-only.", "counts": {"sources": len(rows), "answered": len(good)},
            "data": {"columns": ["Source", "Kind", "Status", "What Relay sees", "Access"], "rows": [[r["source"], r["kind"], "answered" if r["ok"] else "refused", r["sees"], r["scope"]] for r in rows]}}


def _inventory(cat: dict) -> list[dict]:
    cols: dict[str, list[dict]] = {}
    for a in cat["assets"]:
        if a["kind"] == "column" and a.get("parent"):
            cols.setdefault(a["parent"], []).append(a)
    rows = []
    for a in cat["assets"]:
        if a["kind"] not in gr.GOVERNED:
            continue
        cs = cols.get(a["key"], [])
        rows.append({"id": a["key"], "object": a["key"].split(":", 1)[-1] if a["kind"] in ("table", "view") else a["name"], "kind": a["kind"], "platform": a["platform"],
                     "owner": a.get("owner") or "", "certified": a.get("certified") or "", "columns": len(cs) or None,
                     "classified": sum(1 for x in cs if x.get("classification")) or None, "rows": a.get("rows"), "described": "yes" if a.get("description") else "no"})
    return rows


def a_inventory(ctx: wb.Ctx) -> dict:
    cat = read(ctx)
    ctx.put("catalog", cat)
    recs = _inventory(cat)
    n = {k: sum(1 for a in cat["assets"] if a["kind"] == k) for k in ("table", "view", "column", "report", "process")}
    ctx.evidence("The catalogue as read", {"where": cat["where"], "tool": cat["tool"], "counts": n, "terms": len(cat["terms"]), "scans": len(cat["scans"]), "edges": len(cat["edges"])},
                 kind="inventory", ok=True)
    return {"summary": f"{n['table']} table(s), {n['view']} view(s), {n['column']} column(s), {n['report']} report(s) and {n['process']} process(es); {len(cat['terms'])} glossary term(s), "
                       f"{len(cat['edges'])} lineage link(s) and {len(cat['scans'])} scan run(s) in {cat['where']}.",
            "counts": {**{k + "s": v for k, v in n.items()}, "terms": len(cat["terms"])}, "records": recs,
            "data": {"columns": ["Asset", "Kind", "Platform", "Owner", "Certificate", "Columns", "Classified", "Described"],
                     "rows": [[r["object"], r["kind"], r["platform"], r["owner"] or "-", r["certified"] or "-", r["columns"], r["classified"], r["described"]] for r in recs]}}


HIGH = ("owner", "personal", "scan", "deprecated", "duplicate")


def _gates(ctx: wb.Ctx, cat: dict, found: list[dict]) -> list[dict]:
    by: dict[str, list[dict]] = {}
    for f in found:
        by.setdefault(f["kind"], []).append(f)
    checks = []
    for k in ("owner", "personal", "duplicate", "no_definition", "steward", "scan", "deprecated", "uncertified", "description", "lineage"):
        fs = by.get(k, [])
        ev = ctx.evidence(gr.LABEL[k], {"findings": fs}, kind="proof", ok=not fs)
        checks.append({"name": k, "label": gr.LABEL[k], "status": ("fail" if k in HIGH else "warn") if fs else "pass", "measured": f"{len(fs)} found", "expected": "none",
                       "detail": "; ".join(f["issue"] for f in fs[:6])[:500] or "none found", "evidence": ev})
    ends = sorted({e["from"] for e in cat["edges"]} | {e["to"] for e in cat["edges"]})
    if ends:
        checks.append(ctx.proof("references_real", label="Every lineage link joins assets the catalogue holds", refs=ends, known=[a["key"] for a in cat["assets"]]))
    return checks


def _join_lineage(ctx: wb.Ctx, cat: dict) -> int:
    """The catalogue's lineage joins Relay's lineage graph (tables shared with the other modules)."""
    node = {}
    n = 0
    for e in cat["edges"][:2000]:
        for k in (e["from"], e["to"]):
            if k not in node:
                plat, name = k.split(":", 1)
                node[k] = ctx.lineage_node("report" if plat == "powerbi" else "table", plat, name, label=name, own=False)
        ctx.lineage_edge(node[e["from"]], node[e["to"]], "feeds", {"catalogue": cat.get("where"), "via": e.get("via")})
        n += 1
    return n


def a_health(ctx: wb.Ctx) -> dict:
    cat = ctx.get("catalog")
    found = gr.health(cat)
    ctx.put("findings", found)
    checks = _gates(ctx, cat, found)
    joined = _join_lineage(ctx, cat)
    return {"summary": f"{len(found)} finding(s) in {cat['where']}; {joined} lineage link(s) joined Relay's lineage graph.", "counts": {"findings": len(found), "lineage": joined},
            "data": {"checks": checks}}


def a_findings(ctx: wb.Ctx) -> dict:
    have = {r["id"]: r for r in ctx.records("findings")}
    recs = [{"id": f["id"], "kind": f["kind"], "object": f["name"], "issue": f["issue"], "route": f["route"], "decision": (have.get(f["id"]) or {}).get("decision", "keep")}
            for f in ctx.get("findings") or []]
    return {"summary": f"{len(recs)} finding(s) - keep what matters, ignore what does not.", "counts": {"findings": len(recs)}, "records": recs,
            "items": [f"{r['object']}: {r['issue']}" for r in recs[:6]],
            "data": {"columns": ["What", "Object", "Issue", "Who fixes it"], "rows": [[gr.LABEL[r["kind"]], r["object"], r["issue"], r["route"]] for r in recs]}}


FIND_EDIT = wb.Edit(columns=[wb.Column("decision", "Decision", "select", options=(("keep", "Keep"), ("ignore", "Ignore"))), wb.Column("object", "Object", readonly=True),
                             wb.Column("issue", "Issue", readonly=True)], add=False, remove=False, label="finding")
PLAN = (("change", "Fix in the catalogue: owners, classifications, terms and descriptions", "a Change item proposes every value; a person confirms; written with approval"),
        ("heal", "Scans to repair", "Self-healing renews the scan's credential and runs it again"),
        ("ticket", "Decisions for the data owner", "deprecated assets still in use, reports to certify"))


def a_estimate(ctx: wb.Ctx) -> dict:
    keep = {r["id"] for r in ctx.records("findings") if r.get("decision") != "ignore"} or {f["id"] for f in ctx.get("findings") or []}
    fs = [f for f in ctx.get("findings") or [] if f["id"] in keep]
    items, total = [], 0.0
    for route, title, how in PLAN:
        xs = [f for f in fs if f["route"] == route]
        if not xs:
            continue
        m = sum(f["minutes"] for f in xs)
        total += m
        kinds = sorted({gr.LABEL[f["kind"]].lower() for f in xs})
        items.append({"title": title, "detail": f"{len(xs)} finding(s) - {', '.join(kinds)}; {how}.", "effort": _hours(m) + _cost(m / 60)})
    note = "Assumptions: " + "; ".join(f"{v} min per {gr.LABEL[k].lower()}" for k, v in gr.MINUTES.items()) + "."
    ctx.output("governance-assessment.md", f"# Catalogue assessment: {ctx.title}\n\n" + "\n".join(f"## {i['title']}\n\n{i['detail']}\n\nEffort: {i['effort']}\n" for i in items) + f"\n{note}\n",
               label="Assessment (Markdown)")
    return {"summary": f"{len(items)} group(s) of fixes, about {_hours(total)}{_cost(total / 60)}.", "counts": {"groups": len(items), "hours": round(total / 60, 1)},
            "data": {"items": items, "total": _hours(total), "note": note + ("" if registry.brand().get("hourly_rate") else " Set an hourly rate under Admin > Branding to see the cost.")}}


# ================================================================== Fix / change

WHAT = (("all", "Everything the catalogue's health finds"), ("owner", "Owners"), ("personal", "Personal data classification"), ("glossary", "Glossary terms"),
        ("description", "Descriptions"))
KINDS_OF = {"all": ("owner", "personal", "duplicate", "no_definition", "steward", "description"), "owner": ("owner",), "personal": ("personal",),
            "glossary": ("duplicate", "no_definition", "steward"), "description": ("description",)}


def c_request(ctx: wb.Ctx) -> dict:
    cat = read(ctx)
    ctx.put("catalog", cat)
    want = KINDS_OF.get(ctx.scope.get("what") or "all", KINDS_OF["all"])
    names = {x.strip().upper() for x in re.split(r"[\n,]+", ctx.scope.get("objects") or "") if x.strip()}
    fs = [f for f in gr.health(cat) if f["kind"] in want and (not names or f["name"].upper() in names or f["object"].split(":", 1)[-1].upper() in names
                                                                 or f["name"].upper().split(".")[-1] in names)]
    if not fs:
        raise wb.StepFailed("Nothing to fix: the catalogue has no " + dict(WHAT)[ctx.scope.get("what") or "all"].lower() + " finding" + (f" for {', '.join(sorted(names))}" if names else "") + ".")
    ctx.put("findings", fs)
    return {"summary": f"{len(fs)} finding(s) to fix in {cat['where']}.", "counts": {"findings": len(fs)},
            "data": {"text": "\n".join(f"- {f['issue']}" for f in fs[:200])}}


def c_diagnose(ctx: wb.Ctx) -> dict:
    cat = ctx.get("catalog")
    learned = _learned()
    props, checks = [], []
    for f in ctx.get("findings") or []:
        p = gr.propose(f, cat, learned)
        props.append({**f, **p})
    ctx.put("proposals", props)
    by: dict[str, list[dict]] = {}
    for p in props:
        by.setdefault(p["kind"], []).append(p)
    for k, ps in by.items():
        known = [p for p in ps if p["value"] or p["change"] in ("rescan",)]
        checks.append({"name": k, "label": gr.LABEL[k], "status": "pass" if len(known) == len(ps) else "warn", "measured": f"{len(known)} of {len(ps)} proposed by rules",
                       "expected": "a value for each", "detail": "; ".join(f"{p['name']}: {p['change']} {p['value'] or '(a person or Relay\'s agent says)'} - {p['why']}" for p in ps[:5])[:600]})
    return {"summary": f"{sum(1 for p in props if p['value'])} of {len(props)} fix(es) proposed by rules"
                       + (f" ({sum(1 for p in props if 'kept as a rule' in p['why'])} from fixes approved before)" if any("kept as a rule" in p["why"] for p in props) else "")
                       + "; the rest wait for a person or Relay's agent.", "counts": {"proposed": sum(1 for p in props if p["value"]), "open": sum(1 for p in props if not p["value"])},
            "data": {"checks": checks}}


def c_fix(ctx: wb.Ctx) -> dict:
    have = {r["id"]: r for r in ctx.records(ctx.step_id)}
    recs = []
    for p in ctx.get("proposals") or []:
        r = {"id": p["id"], "object": p["object"], "name": p["name"], "change": p["change"], "value": p["value"], "why": p["why"], "origin": "rules" if p["value"] else ""}
        if p["id"] in have:
            r.update({k: have[p["id"]][k] for k in ("value", "change", "origin") if k in have[p["id"]]})
        recs.append(r)
    opn = [r for r in recs if not r["value"] and r["change"] not in ("rescan",)]
    return {"summary": f"{len(recs)} change(s); {len(opn)} without a value yet - fill them in, or ask Relay to draft the definitions and descriptions.",
            "counts": {"changes": len(recs), "open": len(opn)}, "records": recs,
            "data": {"columns": ["Object", "Change", "Value", "Why"], "rows": [[r["name"], r["change"], r["value"] or "-", r["why"]] for r in recs]}}


def _validate_fix(recs: list[dict], ctx: wb.Ctx | None = None) -> list[str]:
    out = []
    for r in recs:
        v = str(r.get("value") or "").strip()
        if r.get("change") == "classify" and v not in _w1_cat.CLASSES:
            out.append(f"{r.get('name')}: {v or '(empty)'} is not a classification Relay knows ({', '.join(sorted(_w1_cat.CLASSES))})")
        elif r.get("change") in ("define", "describe") and v and len(v.split()) < 5:
            out.append(f"{r.get('name')}: a definition or description is a sentence (five words or more)")
        elif r.get("change") in ("owner", "steward") and v and len(v) < 3:
            out.append(f"{r.get('name')}: name the owner (a person or a group)")
    return out


FIX_EDIT = wb.Edit(columns=[wb.Column("value", "Value", "longtext"), wb.Column("name", "Object", readonly=True), wb.Column("change", "Change", readonly=True),
                            wb.Column("why", "Why", readonly=True)], add=False, remove=True, label="change", validate=_validate_fix)

DRAFT_WORDS = ("Read drafts.json (the definitions and descriptions to write, with the catalogue's glossary, Relay's certified metrics and "
               "each table's columns). Write drafts_out.json: one entry per id, a plain British English sentence or two, no more than 60 words. "
               "Say only what the context supports; never invent a column, a table or a number. Then stop.")


def _draft_prompt(ctx: wb.Ctx) -> str:
    cat = ctx.get("catalog")
    cols: dict[str, list[str]] = {}
    for a in cat["assets"]:
        if a["kind"] == "column" and a.get("parent"):
            cols.setdefault(a["parent"], []).append(a["name"])
    todo = [{"id": r["id"], "kind": r["change"], "name": r["name"], "columns": cols.get(r["object"], [])[:60]} for r in ctx.records(ctx.step_id)
            if r["change"] in ("define", "describe") and not r.get("value")]
    metrics = [{"name": m["name"], "description": (m.get("body") or {}).get("description") or (m.get("body") or {}).get("label")} for m in _metrics()][:200]
    (ctx.dir / "drafts.json").write_text(json.dumps({"items": todo, "glossary": [{"name": t["name"], "definition": t["definition"]} for t in cat["terms"]], "metrics": metrics}, indent=1),
                                         encoding="utf-8")
    return DRAFT_WORDS


def _draft_check(ctx: wb.Ctx) -> list[str]:
    spec = json.loads((ctx.dir / "drafts.json").read_text(encoding="utf-8"))
    p = ctx.dir / "drafts_out.json"
    if not p.exists():
        return ["drafts_out.json was not written"]
    try:
        got = json.loads(p.read_text(encoding="utf-8"))
    except ValueError:
        return ["drafts_out.json is not JSON"]
    out = []
    for it in spec["items"]:
        v = str(got.get(it["id"]) or "").strip()
        if not v:
            out.append(f"no draft for {it['name']}")
        elif len(v.split()) < 5 or len(v.split()) > 80:
            out.append(f"the draft for {it['name']} is not one or two sentences ({len(v.split())} words)")
    return out


def _draft_after(ctx: wb.Ctx, res: dict) -> dict:
    got = json.loads((ctx.dir / "drafts_out.json").read_text(encoding="utf-8"))
    recs = ctx.records(ctx.step_id)
    n = 0
    for r in recs:
        if r["id"] in got and not r.get("value"):
            r.update(value=str(got[r["id"]]).strip(), origin="agent", why=r["why"] + " - drafted by Relay, check it")
            n += 1
    ctx.evidence("Definitions drafted by Relay", {"drafts": got, "summary": res.get("text") or ""}, kind="agent", ok=True)
    return {"summary": f"Relay drafted {n} definition(s) and description(s) - read them before you confirm.", "records": recs,
            "data": {"columns": ["Object", "Change", "Value", "Why"], "rows": [[r["name"], r["change"], r["value"] or "-", r["why"]] for r in recs]}}


def _changes(ctx: wb.Ctx) -> list[dict]:
    out = []
    for r in ctx.records("fix"):
        if not str(r.get("value") or "").strip() and r["change"] not in ("rescan",):
            continue
        ch = {"object": r["object"], "change": r["change"], "value": str(r.get("value") or "").strip(), "name": r["name"]}
        if r["change"] in ("define", "retire_term", "steward"):
            ch["object"] = r["object"]
            ch["name"] = r["name"]
        out.append(ch)
    return out


SUPPORTED = {"purview": {"owner", "classify", "describe", "rescan"}, "collibra": {"classify", "describe", "define", "retire_term"},
             "alation": {"describe"}, "atlan": {"owner", "classify", "describe", "define", "certify"}, "databricks_sql": {"owner", "describe"}}


def c_prove(ctx: wb.Ctx) -> dict:
    cs = _conns(ctx)
    c = cs[0] if cs else None
    cat = read(ctx, c) if c else ctx.get("catalog")                  # read again, live: the objects must still be there
    chs = _changes(ctx)
    keys = {a["key"] for a in cat["assets"]} | {f"term:{t['name']}" for t in cat["terms"]}
    checks = [ctx.proof("references_real", label="Every object changed is in the catalogue now", refs=[x["object"] for x in chs], known=sorted(keys))]
    bad = _validate_fix([{"name": x["name"], "change": x["change"], "value": x["value"]} for x in chs])
    checks.append({"name": "values", "label": "Every value is valid for its change", "status": "fail" if bad else "pass", "measured": f"{len(chs) - len(bad)} of {len(chs)}",
                   "expected": "all", "detail": "; ".join(bad)[:500] or "classifications known, definitions are sentences, owners named"})
    dup = sorted({f"{x['name']} ({x['change']})" for x in chs if sum(1 for y in chs if y["object"] == x["object"] and y["change"] == x["change"]) > 1})
    checks.append({"name": "conflicts", "label": "No object is changed twice the same way", "status": "fail" if dup else "pass", "detail": ", ".join(dup)[:400] or "none"})
    open_ = [r["name"] for r in ctx.records("fix") if not str(r.get("value") or "").strip() and r["change"] not in ("rescan",)]
    checks.append({"name": "open", "label": "Every change has its value", "status": "warn" if open_ else "pass", "measured": f"{len(open_)} without a value",
                   "detail": (", ".join(open_[:10]) + " - left out of this change") if open_ else "all filled in"})
    if c:
        can = SUPPORTED.get(c["kind"], set())
        no = sorted({x["change"] for x in chs if x["change"] not in can})
        checks.append({"name": "writable", "label": f"{c['name']} accepts these changes through its API", "status": "fail" if no else "pass",
                       "detail": (f"{', '.join(no)}: not written by Relay to {connectors.KINDS.get(c['kind'], {}).get('label', c['kind'])} yet (a pilot item) - remove them or make them by hand")
                       if no else "every change is one the catalogue's API takes"})
        ops = _w1_cat.ops(c, [x for x in chs if x["change"] in can], cat)
        ctx.put("ops", ops)
    return {"summary": f"{len(chs)} change(s) checked against the catalogue as it is now.", "counts": {"changes": len(chs)}, "data": {"checks": checks}}


def c_approve(ctx: wb.Ctx) -> dict:
    ops = ctx.get("ops") or []
    return {"summary": f"{len(ops)} write(s) to the catalogue, released by the named approver.", "counts": {"writes": len(ops)},
            "data": {"items": [{"title": o.get("what") or o.get("path"), "detail": f"{o.get('method', '')} {o.get('path', '')}".strip(), "effort": ""} for o in ops[:60]] or
                     [{"title": "Nothing to write", "detail": "the changes are made by hand", "effort": ""}], "total": f"{len(ops)} write(s)"}}


def c_learn(ctx: wb.Ctx) -> dict:
    cs = _conns(ctx)
    ops = ctx.get("ops") or []
    cp = _ask_write(ctx, cs[0], ops, f"Fix {len(ops)} catalogue finding(s) in {cs[0]['name']}") if cs and ops else None
    n = 0
    for x in _changes(ctx):
        if x["change"] == "classify":                       # a column of this name carries this class from now on
            col = x["name"].split(".")[-1]
            rid, kind, pat = f"gr-personal-{_w1.slug(col)}", "personal", re.escape(col.upper())
        elif x["change"] == "owner" and "." in x["object"].split(":", 1)[-1]:   # the schema's objects have this owner from now on
            sch = x["object"].split(":", 1)[-1].split(".")[0]
            rid, kind, pat = f"gr-owner-{_w1.slug(sch)}", "owner", re.escape(sch.upper())
        else:
            continue
        db.run("INSERT OR REPLACE INTO governance_rules (id, kind, pattern, change, value, catalogue, item, by, created) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
               (rid, kind, pat, x["change"], x["value"], cs[0]["kind"] if cs else "", ctx.id, ctx.who or ctx.owner, time.time()))
        n += 1
    db.audit("governance.fix.learned", ctx.id, {"changes": _changes(ctx)[:100]}, ctx.who or ctx.owner)
    return {"summary": (f"The {len(ops)} change(s) wait for their write approval in the Validation queue; " if cp else "Recorded; a person makes the changes by hand; ")
            + f"{n} fix(es) kept as rules for next time.", "counts": {"rules learned": n},
            "data": {"href": "#/validate" if cp else f"#/m/{MODULE}/run", "label": "Open the Validation queue" if cp else "Run & support", "text": f"Write approval {cp['id']}" if cp else ""}}


# ================================================================== Develop: a governed data domain

def _metrics() -> list[dict]:
    try:
        rows = db.q("SELECT m.id, m.name, m.team_id, v.version, v.body FROM metrics m JOIN metric_versions v ON v.metric_id = m.id WHERE v.status = 'published'")
    except Exception:  # noqa: BLE001 - the semantic layer's tables are optional here
        return []
    for r in rows:
        r["body"] = json.loads(r["body"]) if isinstance(r["body"], str) else r["body"]
    return rows


def _tables_in(text: str, names: set[str]) -> list[str]:
    return [n for n in sorted(names) if re.search(rf"(?i)\b{re.escape(n.split('.')[-1])}\b", text or "")]


def _domain(cat: dict, spec: str) -> list[dict]:
    """The tables and views a domain covers: the names or schema prefixes given (DW., MART.V_SALES_DASHBOARD), else
    every table and view of DW and MART that is not deprecated."""
    pats = [x.strip().upper() for x in re.split(r"[\n,]+", spec or "") if x.strip()]
    out = []
    for a in cat["assets"]:
        if a["kind"] not in ("table", "view"):
            continue
        name = a["key"].split(":", 1)[-1].upper()
        if pats:
            if any(name == p or (p.endswith((".", "*")) and name.startswith(p.rstrip("*"))) for p in pats):
                out.append(a)
        elif gr.schema_of(a) in ("DW", "MART") and a.get("certified") != "Deprecated":
            out.append(a)
    return out


def _cols(cat: dict, keys) -> dict[str, list[dict]]:
    keys = set(keys)
    out: dict[str, list[dict]] = {}
    for a in cat["assets"]:
        if a["kind"] == "column" and a.get("parent") in keys:
            out.setdefault(a["parent"], []).append(a)
    return out


def d_catalogue(ctx: wb.Ctx) -> dict:
    cat = read(ctx)
    ctx.put("catalog", cat)
    dom = _domain(cat, ctx.scope.get("objects") or "")
    if not dom:
        raise wb.StepFailed("No table or view of the catalogue is in the domain: name them (one per line, e.g. DW.FACT_SALES, or a schema such as MART.).")
    ctx.put("domain", [a["key"] for a in dom])
    cols = _cols(cat, ctx.get("domain"))
    ms = _metrics()
    ctx.put("metrics", [{"name": m["name"], "description": (m["body"] or {}).get("description") or "", "label": (m["body"] or {}).get("label") or "", "sql": (m["body"] or {}).get("sql") or "",
                         "dax": (m["body"] or {}).get("dax") or ""} for m in ms])
    ctx.put("relay_terms", [{"name": t["term"], "definition": t["meaning"]} for t in semantic.terms(None)])
    return {"summary": f"{len(dom)} table(s) and view(s) in the domain, with {sum(len(v) for v in cols.values())} column(s); {len(cat['terms'])} glossary term(s) in {cat['where']} "
                       f"and {len(ms)} certified metric(s) in Relay.", "counts": {"assets": len(dom), "columns": sum(len(v) for v in cols.values()), "certified metrics": len(ms)},
            "data": {"columns": ["Asset", "Kind", "Platform", "Owner", "Columns", "Described"],
                     "rows": [[a["key"].split(":", 1)[-1], a["kind"], a["platform"], a.get("owner") or "-", len(cols.get(a["key"], [])), "yes" if a.get("description") else "no"] for a in dom]}}


def d_own(ctx: wb.Ctx) -> dict:
    cat = ctx.get("catalog")
    by = {a["key"]: a for a in cat["assets"]}
    learned = _learned()
    have = {r["id"]: r for r in ctx.records(ctx.step_id)}
    recs = []
    for k in ctx.get("domain") or []:
        a = by[k]
        p = gr.propose({"kind": "owner", "object": k, "name": a["name"], "evidence": {}}, cat, learned) if not a.get("owner") else {"value": a["owner"], "why": "the catalogue's owner"}
        r = {"id": k, "asset": k.split(":", 1)[-1], "platform": a["platform"], "owner": p["value"] or "", "steward": "", "was": a.get("owner") or "", "why": p["why"]}
        if k in have:
            r.update({x: have[k][x] for x in ("owner", "steward") if x in have[k]})
        recs.append(r)
    new = sum(1 for r in recs if r["owner"] and not r["was"])
    return {"summary": f"{len(recs)} asset(s): {sum(1 for r in recs if r['was'])} owned in the catalogue, {new} owner(s) proposed by rules - name the stewards and confirm.",
            "counts": {"assets": len(recs), "proposed": new}, "records": recs,
            "data": {"columns": ["Asset", "Platform", "Owner", "Steward", "Why"], "rows": [[r["asset"], r["platform"], r["owner"] or "-", r["steward"] or "-", r["why"]] for r in recs]}}


def _validate_own(recs: list[dict], ctx: wb.Ctx | None = None) -> list[str]:
    return [f"{r.get('asset')}: every asset of the domain needs an owner" for r in recs if not str(r.get("owner") or "").strip()]


OWN_EDIT = wb.Edit(columns=[wb.Column("owner", "Owner"), wb.Column("steward", "Steward"), wb.Column("asset", "Asset", readonly=True), wb.Column("why", "Why", readonly=True)],
                   add=False, remove=False, label="asset", validate=_validate_own)


def d_lineage(ctx: wb.Ctx) -> dict:
    cat = ctx.get("catalog")
    keys = set(ctx.get("domain") or [])
    edges = [e for e in cat["edges"] if e["from"] in keys or e["to"] in keys]
    joined = _join_lineage(ctx, {**cat, "edges": edges})
    lin = {k: {"up": sorted({e["from"].split(":", 1)[-1] for e in edges if e["to"] == k}), "down": sorted({e["to"].split(":", 1)[-1] for e in edges if e["from"] == k})} for k in keys}
    ctx.put("lineage", lin)
    rows = [[k.split(":", 1)[-1], ", ".join(v["up"])[:120] or "-", ", ".join(v["down"])[:120] or "-"] for k, v in sorted(lin.items())]
    return {"summary": f"{len(edges)} lineage link(s) for the domain, joined to Relay's lineage graph ({joined}).", "counts": {"links": len(edges)},
            "data": {"columns": ["Asset", "Comes from", "Feeds"], "rows": rows}}


def d_quality(ctx: wb.Ctx) -> dict:
    cat = ctx.get("catalog")
    cols = _cols(cat, ctx.get("domain") or [])
    recs = []
    for k in ctx.get("domain") or []:
        cs = cols.get(k, [])
        name = k.split(":", 1)[-1]
        key = next((c["name"] for c in cs if re.search(r"(_KEY|_ID)$", c["name"])), "")
        when = next((c["name"] for c in cs if re.search(r"(DATE|_AT|_TS|TIME)$", c["name"]) or "date" in str(c.get("type") or "").lower()), "")
        recs.append({"id": f"{k}|rows", "asset": name, "check": "has rows", "rule": "row_count > 0"})
        if key:
            recs.append({"id": f"{k}|unique", "asset": name, "check": f"{key} is unique and never empty", "rule": f"unique({key}); not_null({key})"})
        if when:
            recs.append({"id": f"{k}|fresh", "asset": name, "check": f"{when} is at most 2 days old", "rule": f"freshness({when}) <= 48h"})
    ctx.put("checks", recs)
    ctx.output("quality-rules.yaml", "# Quality rules for the domain - for Relay's Data quality module\n" + "".join(f"- asset: {r['asset']}\n  rule: \"{r['rule']}\"\n" for r in recs),
               label="Quality rules (YAML, for Data quality)")
    return {"summary": f"{len(recs)} quality check(s) proposed by rules for the domain's assets.", "counts": {"checks": len(recs)},
            "data": {"columns": ["Asset", "Check", "Rule"], "rows": [[r["asset"], r["check"], r["rule"]] for r in recs]}}


def d_policy(ctx: wb.Ctx) -> dict:
    cat = ctx.get("catalog")
    keys = ctx.get("domain") or []
    cols = _cols(cat, keys)
    learned = _learned()
    personal = {f["object"]: f for f in gr.health(cat) if f["kind"] == "personal"}
    have = {r["id"]: r for r in ctx.records(ctx.step_id)}
    recs = []
    for k in keys:
        for col in cols.get(k, []):
            if col.get("classification"):
                r = {"id": col["key"], "kind": "column", "what": f"{k.split(':', 1)[-1]}.{col['name']}", "action": "keep", "value": col["classification"], "steward": "", "why": "classified in the catalogue"}
            elif col["key"] in personal:
                p = gr.propose(personal[col["key"]], cat, learned)
                r = {"id": col["key"], "kind": "column", "what": f"{k.split(':', 1)[-1]}.{col['name']}", "action": "classify", "value": p["value"], "steward": "", "why": p["why"]}
            else:
                continue
            recs.append(r)
    tables = {k.split(":", 1)[-1] for k in keys}
    by_canon: dict[str, dict] = {}
    for t in cat["terms"]:
        if t.get("status") != "Obsolete":
            by_canon.setdefault(gr.canon(t["name"]).replace("net ", "").strip(), t)
    seen = set()
    for m in (ctx.get("metrics") or []) + (ctx.get("relay_terms") or []):
        cn = gr.canon(m["name"]).replace("net ", "").strip()
        if cn in seen:
            continue
        seen.add(cn)
        t = by_canon.get(cn)
        defn = m.get("description") or m.get("definition") or m.get("label") or ""
        uses = _tables_in(m.get("sql") or m.get("dax") or "", tables)
        recs.append({"id": f"term:{m['name']}", "kind": "term", "what": t["name"] if t else m["name"], "action": "keep" if t and (t.get("definition") or "").strip() else "define" if t else "add",
                     "value": (t or {}).get("definition") or defn, "steward": (t or {}).get("steward") or "", "why": "a certified metric in Relay" + (f", read from {', '.join(uses)}" if uses else "")})
    for t in cat["terms"]:
        cn = gr.canon(t["name"]).replace("net ", "").strip()
        if t.get("status") == "Obsolete" or (cn in seen and by_canon.get(cn) is t):
            continue
        keep = by_canon.get(cn)
        dup = keep is not None and keep is not t
        recs.append({"id": f"term:{t['name']}", "kind": "term", "what": t["name"], "action": "retire" if dup else "keep" if (t.get("definition") or "").strip() else "define",
                     "value": t.get("definition") or "", "steward": t.get("steward") or "", "why": f"duplicates \"{keep['name']}\"" if dup else "in the catalogue's glossary"})
        seen.add(cn)
    for r in recs:
        if r["id"] in have:
            r.update({x: have[r["id"]][x] for x in ("action", "value", "steward") if x in have[r["id"]]})
    n = {k: sum(1 for r in recs if r["action"] == k) for k in ("classify", "add", "define", "retire")}
    return {"summary": f"Classify {n['classify']} column(s); glossary: add {n['add']}, define {n['define']}, retire {n['retire']} - change what you need and confirm.", "counts": n, "records": recs,
            "data": {"columns": ["Kind", "What", "Action", "Value", "Why"], "rows": [[r["kind"], r["what"], r["action"], r["value"] or "-", r["why"]] for r in recs]}}


def _validate_policy(recs: list[dict], ctx: wb.Ctx | None = None) -> list[str]:
    out = []
    for r in recs:
        r.setdefault("kind", "term")                     # a line a person adds is a glossary term
        if not r.get("kind"):
            r["kind"] = "term"
        if r.get("kind") == "column" and r.get("action") in ("classify", "keep") and r.get("value") and r["value"] not in _w1_cat.CLASSES:
            out.append(f"{r.get('what')}: {r['value']} is not a classification Relay knows ({', '.join(sorted(_w1_cat.CLASSES))})")
        if r.get("kind") == "term" and r.get("action") in ("add", "define") and len(str(r.get("value") or "").split()) < 5:
            out.append(f"{r.get('what')}: a term to {r.get('action')} needs a definition of five words or more")
    names = [gr.canon(r.get("what") or "") for r in recs if r.get("kind") == "term" and r.get("action") != "retire"]
    out += [f"two terms mean the same ({n}) - retire one" for n in sorted({n for n in names if names.count(n) > 1})]
    return out


POLICY_EDIT = wb.Edit(columns=[wb.Column("action", "Action", "select", options=(("keep", "Keep"), ("classify", "Classify"), ("add", "Add the term"), ("define", "Define the term"), ("retire", "Retire (a duplicate)"))),
                               wb.Column("value", "Classification or definition", "longtext"), wb.Column("steward", "Steward"), wb.Column("what", "Column or term", required=True),
                               wb.Column("kind", "Kind", "select", options=(("term", "Glossary term"), ("column", "Column"))), wb.Column("why", "Why", readonly=True)],
                      add=True, remove=True, label="policy line", validate=_validate_policy)


def d_prove(ctx: wb.Ctx) -> dict:
    cs = _conns(ctx)
    c = cs[0] if cs else None
    cat = read(ctx, c) if c else ctx.get("catalog")
    own, pol, chk, lin = ctx.records("own"), ctx.records("policy"), ctx.get("checks") or [], ctx.get("lineage") or {}
    keys = ctx.get("domain") or []
    unowned = [r["asset"] for r in own if not str(r.get("owner") or "").strip()]
    nostew = [r["asset"] for r in own if not str(r.get("steward") or "").strip()]
    nolin = [k.split(":", 1)[-1] for k in keys if not (lin.get(k) or {}).get("up") and gr.schema_of({"key": k, "kind": "table"}) != "STAGE"]
    nochk = [k.split(":", 1)[-1] for k in keys if not any(x["id"].startswith(k + "|") for x in chk)]
    personal = {f["object"] for f in gr.health(cat) if f["kind"] == "personal"}
    left = [r["what"] for r in pol if r["kind"] == "column" and r["id"] in personal and not (r["action"] == "classify" and r.get("value"))]
    terms = [r for r in pol if r["kind"] == "term" and r["action"] != "retire"]
    names = [gr.canon(r["what"]) for r in terms]
    dups = sorted({r["what"] for r in terms if names.count(gr.canon(r["what"])) > 1})
    undefined = [r["what"] for r in terms if len(str(r.get("value") or "").split()) < 5]
    checks = [ctx.proof("references_real", label="Every asset of the domain is in the catalogue now", refs=keys, known=[a["key"] for a in cat["assets"]]),
              {"name": "owned", "label": "Every asset has an owner", "status": "fail" if unowned else "pass", "measured": f"{len(own) - len(unowned)} of {len(own)}", "detail": ", ".join(unowned)[:300] or "all owned"},
              {"name": "stewards", "label": "Every asset has a steward", "status": "warn" if nostew else "pass", "measured": f"{len(own) - len(nostew)} of {len(own)}", "detail": ", ".join(nostew)[:300] or "all have one"},
              {"name": "lineage", "label": "Every asset beyond staging has lineage", "status": "warn" if nolin else "pass", "detail": ", ".join(nolin)[:300] or "all traced"},
              {"name": "quality", "label": "Every asset has quality checks", "status": "fail" if nochk else "pass", "detail": ", ".join(nochk)[:300] or f"{len(chk)} check(s)"},
              {"name": "personal", "label": "Every personal column is classified", "status": "fail" if left else "pass", "detail": ", ".join(left)[:300] or "all classified"},
              {"name": "terms", "label": "The glossary: each term once and defined", "status": "fail" if dups or undefined else "pass",
               "detail": "; ".join(x for x in (", ".join(dups) and f"the same meaning: {', '.join(dups)}", ", ".join(undefined) and f"not defined: {', '.join(undefined)}") if x) or f"{len(terms)} term(s)"}]
    chs = [{"object": r["id"], "name": r["asset"], "change": "owner", "value": r["owner"].strip()} for r in own if str(r.get("owner") or "").strip() and not gr.same_owner(r["owner"], r.get("was"))]
    chs += [{"object": r["id"], "name": r["what"], "change": "classify", "value": r["value"]} for r in pol if r["kind"] == "column" and r["action"] == "classify" and r.get("value")]
    chs += [{"object": r["id"], "name": r["what"], "change": "define", "value": r["value"]} for r in pol if r["kind"] == "term" and r["action"] in ("add", "define")]
    chs += [{"object": r["id"], "name": r["what"], "change": "retire_term", "value": ""} for r in pol if r["kind"] == "term" and r["action"] == "retire"]
    ctx.output("governed-domain.json", json.dumps({"assets": keys, "owners": own, "policy": pol, "quality": chk, "lineage": lin}, indent=1, default=str), label="The governed domain (JSON)")
    failed = [g for g in checks if g["status"] == "fail"]
    if failed or not c:
        return {"summary": f"{len(checks) - len(failed)} of {len(checks)} gate(s) pass" + (" - fix the failing ones before anything is written." if failed else "; no catalogue connection, so the files are the hand-over."),
                "data": {"checks": checks}}
    can = SUPPORTED.get(c["kind"], set())
    ops = _w1_cat.ops(c, [x for x in chs if x["change"] in can], cat)
    no = sorted({x["change"] for x in chs if x["change"] not in can})
    if no:
        checks.append({"name": "writable", "label": f"{c['name']} takes every change through its API", "status": "warn", "detail": f"{', '.join(no)}: by hand for now (a pilot item)"})
    cp = _ask_write(ctx, c, ops, f"Govern the domain in {c['name']}: {len(ops)} call(s)") if ops else None
    return {"summary": f"Every gate holds; {len(chs)} change(s) for {c['name']}" + (f" wait for their write approval in the Validation queue ({cp['id']})." if cp else "."), "counts": {"changes": len(chs)},
            "data": {"checks": checks}}


# ================================================================== Migrate: one catalogue's curation to another

def _pair(ctx: wb.Ctx) -> tuple[dict, dict, dict]:
    cs = _conns(ctx)
    if ctx.files(CAT.uploads):
        if not cs:
            raise wb.StepFailed("Connect the catalogue you move to (the export is the one you leave).")
        return _from_uploads(ctx), read(ctx, cs[0]), cs[0]
    if len(cs) < 2:
        raise wb.StepFailed("Pick two catalogue connections: the one you leave first, the one you move to second (or upload the old one's export).")
    return read(ctx, cs[0]), read(ctx, cs[1]), cs[1]


def _from_uploads(ctx: wb.Ctx) -> dict:
    files = [ctx.dir / "data" / f["name"] for f in ctx.files(CAT.uploads)]
    cat = gr.from_files(files)
    cat["where"], cat["connection"] = ", ".join(f.name for f in files), None
    return cat


def m_discover(ctx: wb.Ctx) -> dict:
    src, dst, tc = _pair(ctx)
    ctx.put("catalog", src)
    ctx.put("target_catalog", dst)
    ctx.put("target", tc["id"])
    m = gr.match(src, dst)
    ctx.put("match", m)
    gov = [a for a in src["assets"] if a["kind"] in gr.GOVERNED]
    hit = sum(1 for a in gov if a["key"] in m)
    return {"summary": f"{len(gov)} governed asset(s) and {len(src['terms'])} term(s) in {src['where']}; {hit} of the assets are already scanned in {dst['where']}.",
            "counts": {"assets": len(gov), "matched": hit, "terms": len(src["terms"])},
            "data": {"columns": ["Asset", "Kind", "Owner", "Certificate", "In the target"], "rows": [[a["name"], a["kind"], _who(a.get("owner")), a.get("certified") or "-", "yes" if a["key"] in m else "not yet"] for a in gov]}}


def m_decide(ctx: wb.Ctx) -> dict:
    src = ctx.get("catalog")
    m = ctx.get("match") or {}
    have = {r["id"]: r for r in ctx.records(ctx.step_id)}
    recs = []
    for a in src["assets"]:
        if a["kind"] not in gr.GOVERNED:
            continue
        if a.get("certified") == "Deprecated":
            d, why = "retire", "certified Deprecated in the old catalogue"
        elif a["key"] not in m:
            d, why = "skip", "not scanned in the target yet - scan it there, then run this again"
        else:
            d, why = "carry", "matched in the target"
        r = {"id": a["key"], "object": a["name"], "kind": a["kind"], "decision": d, "why": why, "owner": a.get("owner") or "", "certified": a.get("certified") or ""}
        if a["key"] in have:
            r["decision"] = have[a["key"]].get("decision", d)
        recs.append(r)
    dups = {f["name"]: f["evidence"].get("keep") for f in gr.health({**src, "assets": [], "scans": []}) if f["kind"] == "duplicate"}
    for t in src["terms"]:
        if t.get("status") == "Obsolete":
            continue
        defined = bool((t.get("definition") or "").strip())
        d, why = ("retire", f"duplicates \"{dups[t['name']]}\"") if t["name"] in dups else ("carry", "a defined term") if defined else ("skip", "no definition to carry")
        r = {"id": f"term:{t['name']}", "object": t["name"], "kind": "term", "decision": d, "why": why, "owner": t.get("steward") or "", "certified": t.get("status") or ""}
        if r["id"] in have:
            r["decision"] = have[r["id"]].get("decision", r["decision"])
        recs.append(r)
    n = {k: sum(1 for r in recs if r["decision"] == k) for k in ("carry", "retire", "skip")}
    return {"summary": f"Carry {n['carry']}, retire {n['retire']}, skip {n['skip']} - change what you need.", "counts": n, "records": recs,
            "items": [f"{r['object']}: {r['decision']} - {r['why']}" for r in recs if r["decision"] != "carry"][:6],
            "data": {"columns": ["Object", "Kind", "Decision", "Why", "Owner"], "rows": [[r["object"], r["kind"], r["decision"], r["why"], r["owner"] or "-"] for r in recs]}}


DECIDE_EDIT = wb.Edit(columns=[wb.Column("decision", "Decision", "select", options=(("carry", "Carry"), ("retire", "Retire"), ("skip", "Skip"))), wb.Column("object", "Object", readonly=True),
                               wb.Column("kind", "Kind", readonly=True), wb.Column("why", "Why", readonly=True)], add=False, remove=False, label="object")


def _carry(ctx: wb.Ctx) -> list[dict]:
    """The neutral changes that carry the old catalogue's curation onto the target's assets."""
    src, dst, m = ctx.get("catalog"), ctx.get("target_catalog"), ctx.get("match") or {}
    carry = {r["id"] for r in ctx.records("decide") if r["decision"] == "carry"}
    tby = {a["key"]: a for a in dst["assets"]}
    tool = dst.get("tool") or ""
    out = []
    for a in src["assets"]:
        if a["kind"] in gr.GOVERNED:
            if a["key"] not in carry:
                continue
        elif a["kind"] != "column" or a.get("parent") not in carry:  # a column goes with its table
            continue
        tk = m.get(a["key"])
        if not tk:
            continue
        t = tby[tk]
        if a.get("owner") and a["kind"] in gr.GOVERNED and not gr.same_owner(a["owner"], t.get("owner")):
            out.append({"object": tk, "name": t["name"], "change": "owner", "value": a["owner"], "from": a["key"]})
        if a.get("description") and a["description"] != t.get("description"):
            out.append({"object": tk, "name": t["name"], "change": "describe", "value": a["description"], "from": a["key"]})
        if a.get("classification") and not gr.same_class(a["classification"], t.get("classification"), tool):
            out.append({"object": tk, "name": t["name"], "change": "classify", "value": a["classification"], "from": a["key"]})
        if a.get("certified") == "Certified" and t.get("certified") != "Certified" and a["kind"] in gr.GOVERNED:
            out.append({"object": tk, "name": t["name"], "change": "certify", "value": "Certified", "from": a["key"]})
    tterms = {t["name"].lower(): t for t in dst["terms"]}
    for t in src["terms"]:
        if f"term:{t['name']}" in carry and (t.get("definition") or "").strip() and (tterms.get(t["name"].lower()) or {}).get("definition") != t["definition"]:
            out.append({"object": f"term:{t['name']}", "name": t["name"], "change": "define", "value": t["definition"], "from": f"term:{t['name']}"})
    return out


def m_convert(ctx: wb.Ctx) -> dict:
    tc = ctx.connection(ctx.get("target"))
    chs = _carry(ctx)
    can = SUPPORTED.get(tc["kind"], set())
    ops = _w1_cat.ops(tc, [x for x in chs if x["change"] in can], ctx.get("target_catalog"))
    ctx.put("changes", chs)
    ctx.put("ops", ops)
    ctx.output("catalogue-migration.json", json.dumps({"changes": chs, "calls": ops}, indent=1), label="The changes and the target's API calls (JSON)")
    n = {k: sum(1 for x in chs if x["change"] == k) for k in ("owner", "describe", "classify", "certify", "define")}
    no = sorted({x["change"] for x in chs if x["change"] not in can})
    recs = [{"id": f"{x['object']}|{x['change']}", "object": x["name"], "change": x["change"], "value": x["value"], "status": "carried" if x["change"] in can else "by hand (pilot item)"} for x in chs]
    return {"summary": f"{len(chs)} change(s) for {tc['name']}: {n['owner']} owner(s), {n['describe']} description(s), {n['classify']} classification(s), {n['certify']} certificate(s), "
                       f"{n['define']} term(s) - {len(ops)} API call(s)" + (f"; {', '.join(no)} not written by Relay to this catalogue yet" if no else "") + ".",
            "counts": {**n, "calls": len(ops)}, "records": recs,
            "data": {"columns": ["Object", "Change", "Value", "Status"], "rows": [[r["object"], r["change"], r["value"], r["status"]] for r in recs[:500]]}}


def m_prove(ctx: wb.Ctx) -> dict:
    tc = ctx.connection(ctx.get("target"))
    dst = read(ctx, tc)                                   # the target as it is now
    src = ctx.get("catalog")
    chs = ctx.get("changes") or []
    keys = {a["key"] for a in dst["assets"]} | {f"term:{t['name']}" for t in dst["terms"]}
    checks = [ctx.proof("references_real", label="Every object written is in the target catalogue", refs=[x["object"] for x in chs if x["change"] != "define"], known=sorted(keys))]
    carry = {r["id"] for r in ctx.records("decide") if r["decision"] == "carry"}
    m = ctx.get("match") or {}
    tby = {a["key"]: a for a in dst["assets"]}
    want = sum(1 for a in src["assets"] if a["key"] in carry and a.get("owner") and m.get(a["key"]) and not gr.same_owner(tby.get(m[a["key"]], {}).get("owner"), a["owner"]))
    got = sum(1 for x in chs if x["change"] == "owner")
    checks.append({"name": "owners", "label": "Every owner of the old catalogue is carried", "status": "pass" if got == want else "fail", "measured": got, "expected": want,
                   "detail": f"{got} owner(s) to write, {want} differ between the catalogues"})
    sby = {a["key"]: a for a in src["assets"]} | {f"term:{t['name']}": {"description": t["definition"]} for t in src["terms"]}
    sample = chs[:20]
    bad = [x for x in sample if str({"owner": sby.get(x["from"], {}).get("owner"), "describe": sby.get(x["from"], {}).get("description"),
                                     "classify": sby.get(x["from"], {}).get("classification"), "certify": "Certified",
                                     "define": sby.get(x["from"], {}).get("description")}.get(x["change"])) != str(x["value"])]
    checks.append({"name": "sample", "label": "Sampled values match the old catalogue field by field", "status": "fail" if bad else "pass", "measured": f"{len(sample) - len(bad)} of {len(sample)}",
                   "detail": "; ".join(f"{x['name']} {x['change']}" for x in bad)[:300] or "identical"})
    dep = [x["name"] for x in chs if sby.get(x["from"], {}).get("certified") == "Deprecated"]
    checks.append({"name": "deprecated", "label": "Nothing deprecated is carried", "status": "fail" if dep else "pass", "detail": ", ".join(dep) or "none"})
    skipped = [r["object"] for r in ctx.records("decide") if r["decision"] == "skip" and r["kind"] != "term"]
    checks.append({"name": "skipped", "label": "Assets the target has not scanned yet", "status": "warn" if skipped else "pass", "measured": len(skipped), "detail": ", ".join(skipped[:12]) or "none"})
    return {"summary": f"{len(chs)} change(s) proven against {tc['name']} as it is now.", "data": {"checks": checks}}


def m_handover(ctx: wb.Ctx) -> dict:
    ops = ctx.get("ops") or []
    return {"summary": f"{len(ops)} API call(s) to the target catalogue; the named owner signs off.",
            "data": {"items": [{"title": o.get("what") or o.get("path"), "detail": f"{o.get('method', '')} {o.get('path', '')}", "effort": ""} for o in ops[:60]], "total": f"{len(ops)} call(s)"}}


def m_run(ctx: wb.Ctx) -> dict:
    tc = ctx.connection(ctx.get("target"))
    ops = ctx.get("ops") or []
    cp = _ask_write(ctx, tc, ops, f"Carry the catalogue's curation into {tc['name']} ({len(ops)} call(s))") if ops else None
    cad = ctx.scope.get("cadence") or {"every": "day", "at": "06:00", "tz": "UTC"}
    item = wb.create(MODULE, "run", f"Watch: {tc['name']}"[:160], who=ctx.owner, brief=f"Scans and new gaps in {tc['name']} after the catalogue move {ctx.id}.",
                     connections=[tc["id"]], scope={"schedule": cad}, visibility=(db.project(ctx.id) or {}).get("visibility") or "private",
                     team_id=(db.project(ctx.id) or {}).get("team_id"), parent=ctx.id)
    ctx.put("run_item", item["id"])
    return {"summary": ("The changes wait for their write approval in the Validation queue; " if cp else "Nothing to write; ") + f"a Run item watches {tc['name']} from now on.",
            "data": {"href": f"#/m/{MODULE}/i/{item['id']}", "label": "Open the Run item", "text": cp["id"] if cp else ""}}


# ================================================================== Run & support

def r_watch(ctx: wb.Ctx) -> dict:
    cs = _conns(ctx)
    if not cs:
        raise wb.StepFailed("Pick the catalogues to watch (their API connections).")
    since = ctx.st.get("last_run") or 0
    seen = set(ctx.get("seen") or [])
    fresh, scans, total = [], [], 0
    for c in cs:
        cat = read(ctx, c)
        found = gr.health(cat)
        total += len(found)
        for f in found:
            if f["kind"] == "scan":
                if str(f["evidence"].get("start") or "") >= (time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(since - 3600)) if since else ""):
                    scans.append({**f, "where": c["name"]})
            elif f["kind"] in ("owner", "personal") and f"{c['id']}|{f['id']}" not in seen:
                fresh.append({**f, "where": c["name"]})
        seen |= {f"{c['id']}|{f['id']}" for f in found}
    ctx.put("seen", sorted(seen)[-5000:])
    ctx.put("fresh", fresh[-300:])
    ctx.put("scans", scans[-100:])
    checks = [{"name": "scans", "label": "Scans since the last round", "status": "fail" if scans else "pass", "measured": f"{len(scans)} failing", "detail": "; ".join(s["issue"] for s in scans)[:400] or "all succeeded"},
              {"name": "gaps", "label": "New gaps (no owner, personal data unclassified)", "status": "warn" if fresh else "pass", "measured": f"{len(fresh)} new",
               "detail": "; ".join(f["issue"] for f in fresh[:6])[:400] or "none new"}]
    return {"summary": f"{len(scans)} failing scan(s) and {len(fresh)} new gap(s) in {' and '.join(c['name'] for c in cs)} ({total} finding(s) in all).",
            "counts": {"failing scans": len(scans), "new gaps": len(fresh)}, "data": {"checks": checks}}


def r_alert(ctx: wb.Ctx) -> dict:
    groups: dict[str, dict] = {}
    for s in ctx.get("scans") or []:
        groups[f"s:{s['where']}:{s['name']}"] = {"id": f"b-scan-{_w1.slug(s['where'] + '-' + s['name'])}"[:120], "what": f"the scan of {s['name']} in {s['where']} fails: {(s['evidence'].get('error') or '')[:200]}",
                                                 "n": 1, "route": "heal", "note": "", "kind": "scan", "where": s["where"], "objects": s["name"]}
    for f in ctx.get("fresh") or []:
        g = groups.setdefault(f"g:{f['where']}:{f['kind']}", {"id": f"b-{f['kind']}-{_w1.slug(f['where'])}", "what": f"{gr.LABEL[f['kind']].lower()} in {f['where']}", "n": 0, "route": "change",
                                                              "note": "", "kind": f["kind"], "where": f["where"], "objects": ""})
        g["n"] += 1
        g["objects"] = (g["objects"] + ", " if g["objects"] else "") + f["name"]
    brk = list(groups.values())
    for b in brk:
        if b["kind"] != "scan":
            b["what"] = f"{b['n']} × {b['what']}: {b['objects'][:200]}"
    ctx.put("breaks", brk)
    if not brk:
        return {"summary": "Nothing new since the last round.", "next": "report", "counts": {"breaks": 0}}
    return {"summary": f"{len(brk)} group(s) to route.", "counts": {"breaks": len(brk)}, "items": [b["what"] for b in brk[:6]],
            "data": {"columns": ["What", "Times", "Proposed route"], "rows": [[b["what"], b["n"], b["route"]] for b in brk]}}


def r_fix(ctx: wb.Ctx) -> dict:
    have = {r["id"]: r for r in ctx.records(ctx.step_id)}
    recs = [{**b, **({k: have[b["id"]][k] for k in ("route", "note") if k in have[b["id"]]} if b["id"] in have else {})} for b in ctx.get("breaks") or []]
    return {"summary": f"{len(recs)} group(s): choose who fixes each. Nothing goes out until you confirm.", "records": recs,
            "data": {"columns": ["What", "Proposed route"], "rows": [[r["what"], r["route"]] for r in recs]}}


RFIX_EDIT = wb.Edit(columns=[wb.Column("route", "Route", "select", options=(("heal", "Self-healing"), ("change", "A Change item (fix in the catalogue)"), ("ticket", "Raise a ticket"),
                                                                            ("expected", "Expected - no action"))),
                             wb.Column("note", "Note", "longtext"), wb.Column("what", "What", readonly=True)], add=False, remove=False, label="group")


def r_approve(ctx: wb.Ctx) -> dict:
    rows = []
    cs = {c["name"]: c for c in _conns(ctx)}
    for b in ctx.records("fix"):
        if b["route"] == "heal":
            h = ctx.heal(b["what"][:120], b["what"] + (f"\n\nNote: {b['note']}" if b.get("note") else ""), place=registry.BY_ID[MODULE]["short"], signature=f"governance:{b['id']}")
        elif b["route"] == "ticket":
            h = ctx.ticket(b["what"][:120], b["what"] + (f"\n\nNote: {b['note']}" if b.get("note") else ""), priority="P3", about=b["what"])
        elif b["route"] == "change":
            c = cs.get(b.get("where"))
            item = wb.create(MODULE, "change", f"Fix: {b['what']}"[:120], who=ctx.owner, brief=b["what"] + (f"\n\nNote: {b['note']}" if b.get("note") else ""),
                             connections=[c["id"]] if c else [], scope={"what": b.get("kind") if b.get("kind") in ("owner", "personal") else "all", "objects": b.get("objects", "").replace(", ", "\n")},
                             visibility=(db.project(ctx.id) or {}).get("visibility") or "private", team_id=(db.project(ctx.id) or {}).get("team_id"), parent=ctx.id)
            h = ctx._handoff({"kind": "change", "label": b["what"][:120], "status": "Change item started", "link": f"#/m/{MODULE}/i/{item['id']}", "output": item["id"]})
        else:
            h = {"kind": "expected", "status": "expected - recorded"}
        rows.append([b["what"][:160], b["route"], h.get("status"), h.get("case") or h.get("checkpoint") or h.get("output") or ""])
    return {"summary": f"{len(rows)} hand-off(s), as you approved.", "data": {"columns": ["What", "Route", "Status", "Reference"], "rows": rows}}


def r_report(ctx: wb.Ctx) -> dict:
    n = len(ctx.get("breaks") or [])
    ctx.output(f"governance-report-{time.strftime('%Y%m%d-%H%M', time.gmtime())}.md", f"# Catalogue run report: {ctx.title}\n\n" + "".join(f"- {b['what']} {b.get('route')}\n" for b in ctx.records("fix")),
               label="Run report (Markdown)")
    return {"summary": f"{n} group(s) this round.", "counts": {"groups": n}, "data": {"columns": ["Round", "Groups"], "rows": [[time.strftime("%d %b %H:%M", time.gmtime()), n]]}}


def _cards(u: dict) -> list[dict]:
    rows = [[r["value"], gr.LABEL.get(r["kind"], r["kind"]), r["pattern"].replace("\\", "")[:60], r["item"] or ""] for r in _learned()[:20]]
    return [{"title": "Fixes kept as rules", "columns": ["Value", "Kind", "Applies to", "Learned in"], "rows": rows,
             "empty": "None yet: a Change item that is approved keeps its classifications and owners as rules for the next catalogue round."}]


GUIDE = """# Data governance & catalogue - the work item

This folder is one work item of Relay's Data governance & catalogue module. Relay reads the catalogue's assets, owners,
classifications, lineage, glossary and scans, and proposes every fix by rules; you are asked only for what no rule can
say: a definition for a business term, or a description for a table.

- `drafts.json` (written by the app before your run): the terms and tables to describe, the catalogue's glossary,
  Relay's certified metrics and each table's columns.
- `drafts_out.json`: what you write - {"<id>": "one or two sentences"} for every item.

Plain British English; say only what the context supports; never invent a column, a table or a number."""


wb.register(wb.Pack(
    module=MODULE, guide=GUIDE,
    lineage="the catalogue's lineage (tables feeding views and reports, with the process in between) joined to Relay's graph; owners and certificates kept on the catalogue",
    platforms={"catalogue": CAT},
    schemas={"asset": [wb.Column("object", "Asset"), wb.Column("kind", "Kind"), wb.Column("owner", "Owner"), wb.Column("certified", "Certificate")],
             "finding": FIND_EDIT.columns, "change": FIX_EDIT.columns, "ownership": OWN_EDIT.columns, "policy": POLICY_EDIT.columns, "object": DECIDE_EDIT.columns},
    cards=_cards,
    work={
        "assess": wb.Work(title="See who owns what, what is classified and certified, and what the catalogue is missing", steps={
            "Connect": wb.Step(kind="platform", run=a_connect, agent="Connector", text="The catalogue answers through its API with your sign-in - or its export is opened"),
            "Inventory": wb.Step(kind="platform", run=a_inventory, agent="Cataloguer", text="Every table, view, report and process with its owner, certificate and classified columns; the glossary and the scans"),
            "Health": wb.Step(kind="proof", run=a_health, view="gates", agent="Steward",
                              text="Rules: no owner, personal data not classified, duplicate terms and terms without a definition, failing scans, deprecated but still used; the catalogue's lineage joins Relay's"),
            "Findings": wb.Step(kind="person", run=a_findings, edit=FIND_EDIT, text="What needs attention - you keep or ignore each finding"),
            "Estimate": wb.Step(kind="deterministic", run=a_estimate, view="plan", agent="Estimator", text="The fixes grouped - in the catalogue, scans to repair, decisions for the data owner - with the time")}),
        "develop": wb.Work(title="Govern a data domain: catalogued, owned, traced, checked and classified - proven, then written with approval", steps={
            "Catalogue": wb.Step(kind="platform", run=d_catalogue, agent="Cataloguer", text="The domain's tables and views from the catalogue, with their columns; Relay's certified metrics and terms"),
            "Own": wb.Step(kind="deterministic", run=d_own, agent="Steward", edit=OWN_EDIT, text="An owner and a steward for every asset - the catalogue's, or proposed by rules; you confirm"),
            "Lineage": wb.Step(kind="deterministic", run=d_lineage, agent="Cataloguer", text="Where each asset comes from and what it feeds, joined to Relay's lineage graph"),
            "Quality": wb.Step(kind="deterministic", run=d_quality, agent="Steward", text="Quality checks per asset by rules (rows, a unique key, freshness), for the Data quality module"),
            "Policy": wb.Step(kind="deterministic", run=d_policy, agent="Steward", edit=POLICY_EDIT,
                              text="Personal data classified (by rules and fixes kept before) and the glossary from Relay's certified metrics - duplicates retired; you confirm"),
            "Prove": wb.Step(kind="proof", run=d_prove, view="gates", agent="Prover", back_to="policy",
                             text="Every asset owned, traced and checked, every personal column classified, each term once and defined - then the catalogue is written through its write approval")},
            fields=[wb.Field("objects", "The domain's tables and views", "longtext", help="One per line, e.g. DW.FACT_SALES, or a schema such as MART. (empty: every DW and MART table)")]),
        "change": wb.Work(title="Fix the catalogue's findings: owners, classifications, definitions and descriptions, written back with approval", needs_source=True, steps={
            "Request": wb.Step(kind="platform", run=c_request, view="text", agent="Cataloguer", text="The findings you name, read from the catalogue as it is now"),
            "Diagnose": wb.Step(kind="deterministic", run=c_diagnose, view="gates", agent="Steward",
                                text="Rules propose each value: the schema's owner, the classification of the column of the same name, a fix approved before"),
            "Fix": wb.Step(kind="deterministic", run=c_fix, agent="Steward", edit=FIX_EDIT, confirm_if=lambda ctx, out: True,
                           text="The changes with their values - you confirm or change each; Relay's agent drafts the definitions and descriptions no rule can",
                           actions={"agent": wb.Action(label="Ask Relay to draft the definitions", kind="agent", prompt=_draft_prompt, check=_draft_check, after=_draft_after, agent="Definition writer (AI)",
                                                       help="The agent drafts one or two sentences per term or table from the glossary, the certified metrics and the columns; you read each before you confirm.")}),
            "Prove": wb.Step(kind="proof", run=c_prove, view="gates", agent="Prover", back_to="fix", text="Every object still in the catalogue, every value valid, no conflicts, every change one the catalogue's API takes"),
            "Approve": wb.Step(kind="person", run=c_approve, view="plan", approver=True, text="The named approver releases the changes"),
            "Learn": wb.Step(kind="platform", run=c_learn, view="link", agent="Publisher", text="The changes go to the catalogue through its own write approval; classifications and owners are kept as rules")},
            fields=[wb.Field("what", "What to fix", "select", options=WHAT, default="all"), wb.Field("objects", "Only these objects", "longtext", help="Optional, one per line, e.g. STG_CUSTOMERS.EMAIL")]),
        "migrate": wb.Work(title="Move to another catalogue: owners, descriptions, classifications, certificates and terms carried, proven and written with approval", steps={
            "Discover": wb.Step(kind="platform", run=m_discover, agent="Cataloguer", text="Both catalogues read - the one you leave (its API or its export) and the one you move to"),
            "Decide": wb.Step(kind="deterministic", run=m_decide, agent="Rationaliser", edit=DECIDE_EDIT, text="Carry, retire or skip each asset and term - deprecated ones retire, ones the target has not scanned wait"),
            "Convert": wb.Step(kind="deterministic", run=m_convert, agent="Mapper", text="Each carried owner, description, classification, certificate and term as the target's own API calls"),
            "Prove": wb.Step(kind="proof", run=m_prove, view="gates", agent="Reconciler", back_to="decide", text="Every object in the target, every owner carried, sampled values identical, nothing deprecated carried"),
            "Hand over": wb.Step(kind="person", run=m_handover, view="plan", approver=True, text="The named owner signs off"),
            "Run": wb.Step(kind="platform", run=m_run, view="link", agent="Publisher", text="The target is written through its write approval; a Run item watches it from now on")},
            fields=[wb.Field("cadence", "Watch the new catalogue", "cadence", default={"every": "day", "at": "06:00", "tz": "UTC"})]),
        "run": wb.Work(title="Watch the catalogue: failing scans and new gaps go to a person before Self-healing, a ticket or a Change item", needs_source=True, steps={
            "Watch": wb.Step(kind="platform", run=r_watch, view="gates", agent="Watcher", text="Scans since the last round and gaps that are new"),
            "Alert": wb.Step(kind="deterministic", run=r_alert, agent="Triage", text="Grouped by catalogue and kind"),
            "Fix": wb.Step(kind="deterministic", run=r_fix, agent="Triage", edit=RFIX_EDIT, text="Relay proposes who fixes each; you confirm or change it"),
            "Approve": wb.Step(kind="platform", run=r_approve, agent="Dispatcher", text="The approved hand-offs go out: Self-healing, a ticket or a Change item"),
            "Report": wb.Step(kind="deterministic", run=r_report, agent="Reporter", confirm_if=lambda ctx, out: bool(ctx.get("breaks")), text="A run report; you confirm it when something needed routing")},
            fields=[wb.Field("schedule", "Watch it", "cadence", default={"every": "day", "at": "07:00", "tz": "UTC"})]),
    }))
