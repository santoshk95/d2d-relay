"""Master data (registry id `mdm`) — one customer, supplier and product: golden records with match rules people
confirm; duplicates and gaps fixed at the source. Reltio through its tenant API and the masters kept in spreadsheets
(Excel or CSV) are read; the mock lab's Reltio simulator and supplier master workbook stand in.

Assess   Connect → Inventory → Health → Findings → Estimate: every record by source and type, how complete it is, the
         duplicates Relay's match rules find (and whether Reltio's own matching agrees), false friends, gaps, codes
         used twice; the steward's work estimated.
Develop  Describe → Shape → Build → Prove → Ship → Run: the match rules — proposed from the data, changed by a
         person, proven on the records (the false-friend guard holds, Reltio's potential matches are found, no group
         joins two tax ids), approved, then live for every Change and Run item.
Change   Request → Diagnose → Fix → Prove → Approve → Learn: the steward's queue — each candidate pair with the rule
         that found it, what agrees and what does not and the record that survives; a person decides merge or not a
         match; proven; released by the approver; written to Reltio only through its own approval; a 'not a match'
         is never proposed again.
Migrate  Discover → Decide → Convert → Prove → Hand over → Run: spreadsheet masters moved into Reltio — duplicates
         within the file folded into one golden record, records Reltio already holds linked, the rest created with a
         crosswalk per source row; every row accounted for; signed off; written with approval; then watched.
Run      Watch → Alert → Fix → Approve → Report: what changed in the hub since the last round — new duplicates go to
         the steward's queue (a Change item), gaps to the source system's owner, after a person approves.
"""
from __future__ import annotations

import json
import re
import time

from .. import connectors, db, registry
from .. import workbench as wb
from . import _w1
from . import mdm_rules as mr

MODULE = "mdm"

db.register_schema("""
CREATE TABLE IF NOT EXISTS mdm_decisions (
  id TEXT PRIMARY KEY, a TEXT NOT NULL, b TEXT NOT NULL, decision TEXT NOT NULL, rule TEXT, item TEXT, by TEXT, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS mdm_rulesets (
  id TEXT PRIMARY KEY, rules TEXT NOT NULL, item TEXT, by TEXT, created REAL NOT NULL);
""")


class Hub(wb.Platform):
    label = "Your MDM hub, read through its API"
    kinds = ("reltio",)
    simulator = "tests/mocklab/sims/mdm.py: reltio"
    reads = "entities with their crosswalks, potential matches and the activity log — read-only; merges and new records only through its own approval"


class Masters(wb.Platform):
    label = "Masters kept in spreadsheets"
    kinds = ()
    uploads = (".xlsx", ".xlsm", ".csv", ".zip")
    simulator = "tests/mocklab/fixtures/excel_models/Masters (the supplier master workbook)"
    reads = "every visible sheet with a header row (name, code, country, tax id, email …), or CSV files"


HUB, MASTERS = Hub(), Masters()


def _hub(ctx: wb.Ctx) -> dict | None:
    return next((c for c in ctx.connections() if c["kind"] in HUB.kinds), None)


def records(ctx: wb.Ctx, hub: bool = True, files: bool = True) -> list[dict]:
    out: list[dict] = []
    c = _hub(ctx) if hub else None
    if c:
        try:
            out += mr.from_reltio(c)
        except connectors.Reconsent:
            raise
        except connectors.ConnectorError as e:
            raise wb.StepFailed(f"{c['name']} could not be read: {e}") from e
    if files:
        fs = [ctx.dir / "data" / f["name"] for f in ctx.files(MASTERS.uploads)]
        if fs:
            got = mr.from_files(fs)
            if not got:
                raise wb.StepFailed("The uploaded masters hold no sheet with a header row Relay recognises (a Name column, with code, country, tax id or email).")
            out += got
    if not out and (hub or files):
        raise wb.StepFailed("Pick the MDM hub's connection (Reltio) or upload the masters (Excel or CSV).")
    return out


def rules_live() -> list[dict]:
    r = db.one("SELECT rules FROM mdm_rulesets ORDER BY created DESC LIMIT 1")
    return json.loads(r["rules"]) if r else [dict(x) for x in mr.DEFAULT_RULES]


def refused() -> set:
    return {frozenset((r["a"], r["b"])) for r in db.q("SELECT a, b FROM mdm_decisions WHERE decision = 'not_match'")}


def _by(recs: list[dict]) -> dict[str, dict]:
    return {r["id"]: r for r in recs}


def _hours(m: float) -> str:
    return f"{m / 60:.1f} h"


def _cost(h: float) -> str:
    b = registry.brand()
    rate, cur = float(b.get("hourly_rate") or 0), b.get("currency") or ""
    return f" · {cur}{rate * h:,.0f}" if rate else ""


def _reltio_matches(c: dict, recs: list[dict], cap: int = 400) -> list[dict]:
    """Reltio's own potential matches for the hub's organisations."""
    out, seen = [], set()
    for r in [x for x in recs if x.get("entity") and x["type"] != "product"][:cap]:
        for m in mr.RELTIO.matches(c, r["entity"]):
            k = frozenset((r["entity"], m["other"]))
            if k not in seen:
                seen.add(k)
                out.append({"a": r["entity"], "b": m["other"], "rule": m["rule"], "score": m["score"]})
    return out


def _ask_write(ctx: wb.Ctx, c: dict, ops: list[dict], what: str) -> dict:
    try:
        cp = connectors.request_write(c, "master data", {"ops": ops}, ctx.who or ctx.owner, module=ctx.module_name, what=what,
                                      items=[o.get("what") or o["op"] for o in ops][:40], link=wb.route_of(ctx.st))
    except Exception as e:  # noqa: BLE001 - ScopeError / ConnectorError: shown to the person
        raise wb.StepFailed(str(e)) from e
    ctx._handoff({"kind": "write", "label": what, "connection": c["name"], "checkpoint": cp["id"], "status": "awaiting approval", "link": "#/validate"})
    return cp


# ================================================================== Assess

def a_connect(ctx: wb.Ctx) -> dict:
    rows = HUB.test(ctx) + MASTERS.test(ctx)
    if not rows:
        raise wb.StepFailed("Nothing to read: pick the MDM hub's connection or upload the masters.")
    good = [r for r in rows if r["ok"]]
    if not good:
        raise wb.StepFailed("No source answered: " + "; ".join(f"{r['source']}: {r['sees']}" for r in rows)[:600])
    return {"summary": f"{len(good)} of {len(rows)} source(s) answered — read-only.", "counts": {"sources": len(rows), "answered": len(good)},
            "data": {"columns": ["Source", "Kind", "Status", "What Relay sees", "Access"], "rows": [[r["source"], r["kind"], "answered" if r["ok"] else "refused", r["sees"], r["scope"]] for r in rows]}}


def _pct(n: int, d: int) -> str:
    return f"{round(100 * n / d)} %" if d else "—"


def a_inventory(ctx: wb.Ctx) -> dict:
    recs = records(ctx)
    ctx.put("records", recs)
    groups: dict[tuple, list[dict]] = {}
    for r in recs:
        groups.setdefault((r["source"].split(" › ")[0], r["type"]), []).append(r)
    rows = []
    for (src, typ), rs in sorted(groups.items()):
        rows.append({"id": f"{src}|{typ}", "source": src, "type": typ, "records": len(rs), "tax_id": _pct(sum(1 for r in rs if r.get("tax_id")), len(rs)),
                     "email": _pct(sum(1 for r in rs if r.get("email")), len(rs)), "country": _pct(sum(1 for r in rs if r.get("country")), len(rs)),
                     "single": sum(1 for r in rs if len(r.get("sources") or []) <= 1)})
    ctx.evidence("The masters as read", {"records": len(recs), "by_source": {f"{k[0]} · {k[1]}": len(v) for k, v in groups.items()}}, kind="inventory", ok=True)
    n = {t: sum(1 for r in recs if r["type"] == t) for t in ("customer", "supplier", "product")}
    return {"summary": f"{n['customer']} customer(s), {n['supplier']} supplier(s) and {n['product']} product(s) from {len(groups)} source(s) and type(s).",
            "counts": {**{t + "s": v for t, v in n.items()}, "records": len(recs)}, "records": rows,
            "data": {"columns": ["Source", "Type", "Records", "With a tax id", "With an email", "With a country", "From one source only"],
                     "rows": [[r["source"], r["type"], r["records"], r["tax_id"], r["email"], r["country"], r["single"]] for r in rows]}}


def _findings(ctx: wb.Ctx, recs: list[dict]) -> tuple[list[dict], list[dict], dict]:
    by = _by(recs)
    ps = mr.pairs(recs, rules_live(), refused())
    c = _hub(ctx)
    theirs = _reltio_matches(c, recs) if c else []
    mine = {frozenset((p["a"], p["b"])) for p in ps}
    agree = [m for m in theirs if frozenset((m["a"], m["b"])) in mine]
    out = []
    for p in ps:
        a, b = by[p["a"]], by[p["b"]]
        kind = "false_friend" if p["action"] == "not_match" else "duplicate"
        out.append({"id": f"{kind}:{p['a']}|{p['b']}", "kind": kind, "object": f"{a['name']} ↔ {b['name']}", "issue": p["why"], "route": "steward" if kind == "duplicate" else "expected",
                    "minutes": 3 if kind == "duplicate" else 1, "pair": p})
    for g in mr.gaps(recs):
        out.append({"id": f"gap:{g['id']}", "kind": "gap", "object": g["name"], "issue": f"{g['name']} has no {', '.join(x.replace('_', ' ') for x in g['missing'])}", "route": "ticket", "minutes": 2})
    for code in mr.codes_twice(recs):
        out.append({"id": f"code:{code}", "kind": "code", "object": code, "issue": f"the code {code} is used by two records", "route": "steward", "minutes": 10})
    return out, ps, {"theirs": len(theirs), "agree": len(agree), "missed": [m for m in theirs if frozenset((m["a"], m["b"])) not in mine][:20]}


LABEL = {"duplicate": "Duplicates", "false_friend": "False friends (same name, two organisations)", "gap": "Gaps in golden records", "code": "Codes used twice"}


def a_health(ctx: wb.Ctx) -> dict:
    recs = ctx.get("records")
    found, ps, rel = _findings(ctx, recs)
    ctx.put("findings", found)
    ctx.put("pairs", ps)
    checks = []
    for k, label in LABEL.items():
        fs = [f for f in found if f["kind"] == k]
        ev = ctx.evidence(label, {"findings": fs[:500]}, kind="proof", ok=not fs)
        checks.append({"name": k, "label": label, "status": ("fail" if k in ("duplicate", "code") else "warn") if fs else "pass", "measured": f"{len(fs)} found", "expected": "none",
                       "detail": "; ".join(f"{f['object']}: {f['issue']}" for f in fs[:5])[:500] or "none found", "evidence": ev})
    if rel["theirs"]:
        ev = ctx.evidence("Reltio's potential matches compared with Relay's rules", rel, kind="proof", ok=rel["agree"] == rel["theirs"])
        checks.append({"name": "agreement", "label": "Reltio's own matching and Relay's rules agree", "status": "pass" if rel["agree"] == rel["theirs"] else "warn",
                       "measured": f"{rel['agree']} of {rel['theirs']}", "expected": "all", "evidence": ev,
                       "detail": f"{rel['agree']} of Reltio's {rel['theirs']} potential match(es) are found by the rules or held apart by the false-friend guard"})
    return {"summary": f"{sum(1 for f in found if f['kind'] == 'duplicate')} duplicate pair(s), {sum(1 for f in found if f['kind'] == 'false_friend')} false friend(s), "
                       f"{sum(1 for f in found if f['kind'] == 'gap')} gap(s), {sum(1 for f in found if f['kind'] == 'code')} code(s) used twice.",
            "counts": {"findings": len(found)}, "data": {"checks": checks}}


def a_findings(ctx: wb.Ctx) -> dict:
    have = {r["id"]: r for r in ctx.records("findings")}
    recs = [{"id": f["id"], "kind": f["kind"], "object": f["object"], "issue": f["issue"], "route": f["route"], "decision": (have.get(f["id"]) or {}).get("decision", "keep")}
            for f in ctx.get("findings") or []]
    return {"summary": f"{len(recs)} finding(s) — keep what matters, ignore what does not.", "counts": {"findings": len(recs)}, "records": recs,
            "items": [f"{r['object']}: {r['issue']}" for r in recs[:6]],
            "data": {"columns": ["What", "Records", "Why", "Who fixes it"], "rows": [[LABEL[r["kind"]], r["object"], r["issue"], r["route"]] for r in recs]}}


FIND_EDIT = wb.Edit(columns=[wb.Column("decision", "Decision", "select", options=(("keep", "Keep"), ("ignore", "Ignore"))), wb.Column("object", "Records", readonly=True),
                             wb.Column("issue", "Why", readonly=True)], add=False, remove=False, label="finding")


def a_estimate(ctx: wb.Ctx) -> dict:
    keep = {r["id"] for r in ctx.records("findings") if r.get("decision") != "ignore"} or {f["id"] for f in ctx.get("findings") or []}
    fs = [f for f in ctx.get("findings") or [] if f["id"] in keep]
    items, total = [], 0.0
    for kinds, title, how in ((("duplicate", "code"), "The steward's queue", "a Change item proposes each merge with the surviving record; a person decides; Reltio is written with approval"),
                              (("gap",), "Gaps to fix at the source", "a ticket to the source system's owner, with the records"),
                              (("false_friend",), "False friends held apart", "recorded as not a match, so no rule merges them")):
        xs = [f for f in fs if f["kind"] in kinds]
        if not xs:
            continue
        m = sum(f["minutes"] for f in xs)
        total += m
        items.append({"title": title, "detail": f"{len(xs)} finding(s); {how}.", "effort": _hours(m) + _cost(m / 60)})
    note = "Assumptions: 3 min per pair a steward reviews, 2 min per gap, 10 min per code used twice, 1 min per false friend."
    ctx.output("master-data-assessment.md", f"# Master data assessment: {ctx.title}\n\n" + "\n".join(f"## {i['title']}\n\n{i['detail']}\n\nEffort: {i['effort']}\n" for i in items) + f"\n{note}\n",
               label="Assessment (Markdown)")
    return {"summary": f"{len(items)} group(s) of work, about {_hours(total)}{_cost(total / 60)}.", "counts": {"groups": len(items), "hours": round(total / 60, 1)},
            "data": {"items": items, "total": _hours(total), "note": note + ("" if registry.brand().get("hourly_rate") else " Set an hourly rate under Admin › Branding to see the cost.")}}


# ================================================================== Fix / change: the steward's queue

def c_request(ctx: wb.Ctx) -> dict:
    recs = records(ctx)
    ctx.put("records", recs)
    names = [x.strip().lower() for x in re.split(r"[\n,]+", ctx.scope.get("names") or "") if x.strip()]
    by = _by(recs)
    ps = [p for p in mr.pairs(recs, rules_live(), refused()) if not names or any(n in by[p["a"]]["name"].lower() or n in by[p["b"]]["name"].lower() for n in names)]
    if not ps:
        raise wb.StepFailed("No candidate duplicates" + (f" for {', '.join(names)}" if names else "") + ": the masters are clean by the live match rules.")
    ctx.put("pairs", ps)
    return {"summary": f"{len(ps)} candidate pair(s) from {len(recs)} record(s).", "counts": {"pairs": len(ps)},
            "data": {"text": "\n".join(f"- {by[p['a']]['name']} ↔ {by[p['b']]['name']} — {p['rule']} ({p['score']})" for p in ps[:200])}}


def c_diagnose(ctx: wb.Ctx) -> dict:
    by = _by(ctx.get("records"))
    checks = []
    for p in ctx.get("pairs") or []:
        a, b = by[p["a"]], by[p["b"]]
        same = [f for f in mr.FIELDS if a.get(f) and b.get(f) and str(a[f]).strip().lower() == str(b[f]).strip().lower()]
        diff = [f for f in mr.FIELDS if a.get(f) and b.get(f) and f not in same]
        st = "fail" if p["action"] == "not_match" else "pass" if p["action"] == "merge" else "warn"
        checks.append({"name": f"{p['a']}|{p['b']}", "label": f"{a['name']} ↔ {b['name']}", "status": st, "measured": f"score {p['score']}", "expected": p["rule"],
                       "detail": (f"agree on {', '.join(same)}" if same else "agree on nothing but the name") + (f"; differ on {', '.join(diff)}" if diff else "") + f" — {p['why']}"})
    return {"summary": f"{sum(1 for c in checks if c['status'] == 'pass')} pair(s) a rule would merge, {sum(1 for c in checks if c['status'] == 'warn')} to judge, "
                       f"{sum(1 for c in checks if c['status'] == 'fail')} held apart by the false-friend guard.", "data": {"checks": checks}}


def c_fix(ctx: wb.Ctx) -> dict:
    by = _by(ctx.get("records"))
    have = {r["id"]: r for r in ctx.records(ctx.step_id)}
    recs = []
    for p in ctx.get("pairs") or []:
        a, b = by[p["a"]], by[p["b"]]
        win, lose = mr.survivor(a, b)
        rid = f"{p['a']}|{p['b']}"
        r = {"id": rid, "a": p["a"], "b": p["b"], "records": f"{a['name']} ↔ {b['name']}", "decision": "not_match" if p["action"] == "not_match" else "merge",
             "survives": f"{win['name']} ({', '.join(win.get('sources') or [])[:80]})", "winner": win["id"], "loser": lose["id"], "rule": p["rule"], "why": p["why"]}
        if rid in have:
            r["decision"] = have[rid].get("decision", r["decision"])
        recs.append(r)
    n = {k: sum(1 for r in recs if r["decision"] == k) for k in ("merge", "not_match", "later")}
    return {"summary": f"Merge {n['merge']}, not a match {n['not_match']}, later {n['later']} — change any decision before you confirm.", "counts": n, "records": recs,
            "data": {"columns": ["Records", "Decision", "Survives", "Rule"], "rows": [[r["records"], r["decision"], r["survives"], r["rule"]] for r in recs]}}


FIX_EDIT = wb.Edit(columns=[wb.Column("decision", "Decision", "select", options=(("merge", "Merge"), ("not_match", "Not a match"), ("later", "Decide later"))),
                            wb.Column("records", "Records", readonly=True), wb.Column("survives", "Survives", readonly=True), wb.Column("why", "Why", readonly=True)],
                   add=False, remove=False, label="pair")


def c_prove(ctx: wb.Ctx) -> dict:
    by = _by(ctx.get("records"))
    decs = [r for r in ctx.records("fix") if r["decision"] in ("merge", "not_match")]
    c = _hub(ctx)
    live = {r["entity"] for r in mr.from_reltio(c)} if c else set()
    gone = [r["records"] for r in decs if c and any(by[x].get("entity") and by[x]["entity"] not in live for x in (r["a"], r["b"]))]
    guard = [r["records"] for r in decs if r["decision"] == "merge" and mr.false_friend(by[r["a"]], by[r["b"]])]
    losers = [r["loser"] for r in decs if r["decision"] == "merge"]
    twice = sorted({by[x]["name"] for x in losers if losers.count(x) > 1})
    chain = sorted({by[r["winner"]]["name"] for r in decs if r["decision"] == "merge" and r["winner"] in losers})
    hand = [r["records"] for r in decs if r["decision"] == "merge" and not (by[r["a"]].get("entity") and by[r["b"]].get("entity"))]
    taxes = [r["records"] for r in decs if r["decision"] == "merge" and by[r["a"]].get("tax_id") and by[r["b"]].get("tax_id") and by[r["a"]]["tax_id"] != by[r["b"]]["tax_id"]]
    checks = [{"name": "exists", "label": "Every record is still in the hub", "status": "fail" if gone else "pass", "detail": ", ".join(gone)[:400] or "all there"},
              {"name": "guard", "label": "No merge of two organisations in different countries with nothing shared", "status": "fail" if guard else "pass", "detail": ", ".join(guard)[:400] or "the guard holds"},
              {"name": "taxid", "label": "No merge joins two different tax ids", "status": "fail" if taxes else "pass", "detail": ", ".join(taxes)[:400] or "none"},
              {"name": "once", "label": "Each record merges into one survivor only", "status": "fail" if twice or chain else "pass",
               "detail": (", ".join(twice + chain)[:400] + " — merge them in one pair at a time") if twice or chain else "no record in two merges"},
              {"name": "hub", "label": "Every merge is between records the hub holds", "status": "warn" if hand else "pass",
               "detail": (", ".join(hand)[:300] + " — a spreadsheet row is merged by moving it into the hub (Migrate)") if hand else "all in Reltio"}]
    ops = []
    for r in decs:
        a, b = by[r["a"]], by[r["b"]]
        if not (a.get("entity") and b.get("entity")):
            continue
        if r["decision"] == "merge":
            ops.append({"op": "merge", "winner": by[r["winner"]]["entity"], "loser": by[r["loser"]]["entity"], "what": f"merge {by[r['loser']]['name']} into {by[r['winner']]['name']}"})
        else:
            ops.append({"op": "not_match", "a": a["entity"], "b": b["entity"], "what": f"{a['name']} and {b['name']} are not a match"})
    ctx.put("ops", ops)
    return {"summary": f"{len(decs)} decision(s) proven; {len(ops)} change(s) for the hub.", "counts": {"decisions": len(decs), "changes": len(ops)}, "data": {"checks": checks}}


def c_approve(ctx: wb.Ctx) -> dict:
    ops = ctx.get("ops") or []
    return {"summary": f"{len(ops)} change(s) to the hub, released by the named approver.", "counts": {"changes": len(ops)},
            "data": {"items": [{"title": o["what"], "detail": o["op"].replace("_", " "), "effort": ""} for o in ops[:80]] or [{"title": "Nothing for the hub", "detail": "", "effort": ""}],
                     "total": f"{len(ops)} change(s)"}}


def c_learn(ctx: wb.Ctx) -> dict:
    c = _hub(ctx)
    ops = ctx.get("ops") or []
    cp = _ask_write(ctx, c, ops, f"{len(ops)} merge and not-a-match decision(s) in {c['name']}") if c and ops else None
    n = 0
    for r in ctx.records("fix"):
        if r["decision"] in ("merge", "not_match"):
            db.run("INSERT OR REPLACE INTO mdm_decisions (id, a, b, decision, rule, item, by, created) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                   (f"md-{r['a']}|{r['b']}"[:240], r["a"], r["b"], r["decision"], r["rule"], ctx.id, ctx.who or ctx.owner, time.time()))
            n += 1
    db.audit("mdm.decisions", ctx.id, {"decisions": n}, ctx.who or ctx.owner)
    return {"summary": (f"The {len(ops)} change(s) wait for their write approval in the Validation queue; " if cp else "Recorded; ") + f"{n} decision(s) kept — a pair called not a match is never proposed again.",
            "counts": {"decisions": n}, "data": {"href": "#/validate" if cp else f"#/m/{MODULE}/run", "label": "Open the Validation queue" if cp else "Run & support", "text": f"Write approval {cp['id']}" if cp else ""}}


# ================================================================== Develop: the match rules

def d_describe(ctx: wb.Ctx) -> dict:
    recs = records(ctx)
    ctx.put("records", recs)
    rows = []
    for t in ("customer", "supplier", "product"):
        rs = [r for r in recs if r["type"] == t]
        if not rs:
            continue
        for f in mr.FIELDS:
            vals = [r.get(f) for r in rs if r.get(f)]
            rows.append([t, f, _pct(len(vals), len(rs)), _pct(len(set(map(str, vals))), len(vals)) if vals else "—"])
    return {"summary": f"{len(recs)} record(s) profiled: how full and how distinct each attribute is.", "counts": {"records": len(recs)},
            "data": {"columns": ["Type", "Attribute", "Filled", "Distinct"], "rows": rows}}


def d_shape(ctx: wb.Ctx) -> dict:
    have = {r["id"]: r for r in ctx.records(ctx.step_id)}
    recs = [dict(have.get(r["id"]) or r) for r in rules_live()] + [r for k, r in have.items() if k not in {x["id"] for x in rules_live()}]
    return {"summary": f"{len(recs)} match rule(s), first match wins — change, add or switch off rules before you confirm.", "counts": {"rules": len(recs)}, "records": recs,
            "data": {"columns": ["Rule", "Attributes", "Compare", "Threshold", "Action", "On"], "rows": [[r["name"], r["attributes"], r["compare"], r["threshold"], r["action"], r.get("enabled", True)] for r in recs]}}


def _validate_rules(recs: list[dict], ctx: wb.Ctx | None = None) -> list[str]:
    out = []
    for r in recs:
        attrs = [a.strip() for spec in str(r.get("attributes") or "").split(",") for a in spec.split("|") if a.strip()]
        bad = [a for a in attrs if a not in mr.FIELDS]
        if not attrs or bad:
            out.append(f"{r.get('name') or 'a rule'}: attributes are {', '.join(mr.FIELDS)} (got {', '.join(bad) or 'none'})")
        try:
            th = float(r.get("threshold") or 0)
        except (TypeError, ValueError):
            th = -1
        if not 0.5 <= th <= 1:
            out.append(f"{r.get('name') or 'a rule'}: the threshold is between 0.5 and 1")
        if r.get("action") == "merge" and r.get("compare") == "similar":
            out.append(f"{r.get('name') or 'a rule'}: a similar-name rule only suggests; a person confirms the merge")
    return out


RULE_EDIT = wb.Edit(columns=[wb.Column("name", "Rule", required=True), wb.Column("attributes", "Attributes (a | b = either)"),
                             wb.Column("compare", "Name compared", "select", options=(("exact", "Exactly"), ("normalised", "Normalised (case, punctuation, Ltd)"), ("similar", "Similar"))),
                             wb.Column("threshold", "Threshold", "number"), wb.Column("action", "Then", "select", options=(("merge", "Merge (a person still confirms)"), ("suggest", "Suggest"))),
                             wb.Column("enabled", "On", "bool")], add=True, remove=True, label="rule", validate=_validate_rules)


def d_build(ctx: wb.Ctx) -> dict:
    rules = [r for r in ctx.records("shape") if r.get("enabled", True)]
    groups = [{"uri": f"configuration/entityTypes/Organization/matchGroups/{_w1.slug(r['name'])}", "label": r["name"], "type": "automatic" if r["action"] == "merge" else "suggested",
               "rule": {"and": [{"exact" if r["compare"] != "similar" else "fuzzy": [f"configuration/entityTypes/Organization/attributes/{f.strip().split('|')[0].title().replace('_', '')}"
                                                                                     for f in str(r["attributes"]).split(",")]}]}} for r in rules]
    ctx.output("reltio-match-groups.json", json.dumps({"matchGroups": groups}, indent=1), label="Reltio match groups (JSON)")
    ctx.output("relay-match-rules.json", json.dumps(rules, indent=1), label="Relay's match rules (JSON)")
    return {"summary": f"{len(rules)} rule(s) as Reltio match groups and as Relay's own rules.", "data": {"text": "\n".join(f"{i + 1}. {r['name']}: {r['attributes']} ({r['compare']}, ≥ {r['threshold']}) → {r['action']}"
                                                                                                         for i, r in enumerate(rules))}}


def d_prove(ctx: wb.Ctx) -> dict:
    recs = ctx.get("records")
    by = _by(recs)
    rules = [r for r in ctx.records("shape")]
    ps = mr.pairs(recs, rules, refused())
    merges = [p for p in ps if p["action"] in ("merge", "suggest")]
    guard = [p for p in merges if mr.false_friend(by[p["a"]], by[p["b"]])]
    groups: dict[str, set] = {}
    for p in merges:                                      # transitive groups: one tax id each
        g = groups.get(p["a"]) or groups.get(p["b"]) or set()
        g |= {p["a"], p["b"]}
        for x in g:
            groups[x] = g
    mixed = sorted({", ".join(sorted(by[x]["name"] for x in g))[:120] for g in {id(g): g for g in groups.values()}.values() if len({by[x]["tax_id"] for x in g if by[x].get("tax_id")}) > 1})
    checks = [{"name": "pairs", "label": "Candidate pairs the rules find", "status": "pass", "measured": len(merges), "detail": f"{sum(1 for p in merges if p['action'] == 'merge')} to merge, "
               f"{sum(1 for p in merges if p['action'] == 'suggest')} to suggest, {sum(1 for p in ps if p['action'] == 'not_match')} held apart"},
              {"name": "guard", "label": "The false-friend guard holds", "status": "fail" if guard else "pass", "detail": ", ".join(f"{by[p['a']]['name']} ↔ {by[p['b']]['name']}" for p in guard)[:300] or "no merge across countries with nothing shared"},
              {"name": "taxid", "label": "No group joins two tax ids", "status": "fail" if mixed else "pass", "detail": "; ".join(mixed)[:400] or "one tax id per group"}]
    c = _hub(ctx)
    if c:
        theirs = _reltio_matches(c, recs)
        mine = {frozenset((p["a"], p["b"])) for p in ps}
        found = [m for m in theirs if frozenset((m["a"], m["b"])) in mine]
        checks.append({"name": "reltio", "label": "Reltio's potential matches are found (or held apart)", "status": "pass" if len(found) >= 0.8 * len(theirs) else "warn",
                       "measured": f"{len(found)} of {len(theirs)}", "expected": "at least 80 %", "detail": f"{len(found)} of Reltio's {len(theirs)} potential match(es)"})
    return {"summary": f"The rules find {len(merges)} pair(s) on {len(recs)} record(s).", "counts": {"pairs": len(merges)}, "data": {"checks": checks}}


def d_ship(ctx: wb.Ctx) -> dict:
    rules = [r for r in ctx.records("shape") if r.get("enabled", True)]
    return {"summary": "The named approver confirms the match rules go live.", "data": {"items": [{"title": r["name"], "detail": f"{r['attributes']} → {r['action']}", "effort": ""} for r in rules],
                                                                                         "total": f"{len(rules)} rule(s)"}}


def d_run(ctx: wb.Ctx) -> dict:
    rules = ctx.records("shape")
    rid = f"mr-{_w1.slug(ctx.id)}"[:120]
    db.run("INSERT OR REPLACE INTO mdm_rulesets (id, rules, item, by, created) VALUES (?, ?, ?, ?, ?)", (rid, json.dumps(rules), ctx.id, ctx.who or ctx.owner, time.time()))
    db.audit("mdm.rules.live", ctx.id, {"rules": [r["name"] for r in rules]}, ctx.who or ctx.owner)
    return {"summary": f"{len(rules)} rule(s) are live for every Change and Run item; the Reltio match groups are handed over as a file (Reltio's configuration API is a pilot item).",
            "data": {"href": f"#/m/{MODULE}/change", "label": "The steward's queue", "text": "reltio-match-groups.json"}}


# ================================================================== Migrate: spreadsheet masters into Reltio

def m_discover(ctx: wb.Ctx) -> dict:
    src = records(ctx, hub=False)
    c = _hub(ctx)
    if not c:
        raise wb.StepFailed("Connect the MDM hub the masters move into (Reltio).")
    hub = mr.from_reltio(c)
    ctx.put("records", src)
    ctx.put("hub", hub)
    return {"summary": f"{len(src)} row(s) in the masters; {len(hub)} record(s) already in {c['name']}.", "counts": {"rows": len(src), "in the hub": len(hub)},
            "data": {"columns": ["Row", "Name", "Code", "Country", "Tax id"], "rows": [[r["row"], r["name"], r.get("code"), r.get("country"), r.get("tax_id")] for r in src[:500]]}}


def m_decide(ctx: wb.Ctx) -> dict:
    src, hub = ctx.get("records"), ctx.get("hub")
    rules = rules_live()
    by = _by(src + hub)
    have = {r["id"]: r for r in ctx.records(ctx.step_id)}
    into: dict[str, tuple[str, str]] = {}
    for p in mr.pairs(src + hub, rules, refused()):
        if p["action"] == "not_match":
            continue
        a, b = by[p["a"]], by[p["b"]]
        s, o = (a, b) if a.get("row") and not b.get("row") else (b, a) if b.get("row") and not a.get("row") else (None, None)
        if s and s["id"] not in into:
            into[s["id"]] = ("link", o["id"])                 # already in the hub
        elif a.get("row") and b.get("row"):
            first, later = (a, b) if a["row"] < b["row"] else (b, a)
            if later["id"] not in into:
                into[later["id"]] = ("fold", first["id"])     # a duplicate within the file
    recs = []
    for r in src:
        d, t = into.get(r["id"], ("new", ""))
        if d == "fold" and into.get(t, ("",))[0] == "link":
            d, t = "link", into[t][1]
        if not r.get("country"):
            d, t = "skip", ""
        why = ("not in the hub yet" if d == "new" else f"already in the hub as {by[t]['name']}" if d == "link" else
               f"the same record as row {by[t].get('row')} ({by[t]['name']})" if d == "fold" else "no country — fix the row first")
        rec = {"id": r["id"], "row": r["row"], "name": r["name"], "decision": d, "target": t, "why": why}
        if r["id"] in have:
            rec["decision"] = have[r["id"]].get("decision", d)
        recs.append(rec)
    n = {k: sum(1 for r in recs if r["decision"] == k) for k in ("new", "link", "fold", "skip")}
    return {"summary": f"Create {n['new']}, link {n['link']} already in the hub, fold {n['fold']} duplicate row(s), skip {n['skip']}.", "counts": n, "records": recs,
            "items": [f"row {r['row']} {r['name']}: {r['decision']} — {r['why']}" for r in recs if r["decision"] != "new"][:6],
            "data": {"columns": ["Row", "Name", "Decision", "Why"], "rows": [[r["row"], r["name"], r["decision"], r["why"]] for r in recs]}}


DECIDE_EDIT = wb.Edit(columns=[wb.Column("decision", "Decision", "select", options=(("new", "Create"), ("link", "Link to the hub's record"), ("fold", "Fold into an earlier row"), ("skip", "Skip"))),
                               wb.Column("name", "Name", readonly=True), wb.Column("why", "Why", readonly=True)], add=False, remove=False, label="row")


def _entity(r: dict, rows: list[dict], role: str) -> dict:
    def at(name, v):
        return [{"value": v}] if v not in (None, "") else []
    attrs = {"Name": at("Name", r["name"]), ("SupplierCode" if role == "supplier" else "CustomerCode"): at("Code", r.get("code")), "Country": at("Country", r.get("country")),
             "City": at("City", r.get("city")), "Email": at("Email", r.get("email")), "TaxId": at("TaxId", r.get("tax_id")), "Role": at("Role", role.title())}
    return {"type": mr.OT, "attributes": {k: v for k, v in attrs.items() if v},
            "crosswalks": [{"type": "configuration/sources/ExcelMaster", "value": str(x.get("code") or x["row"])} for x in rows]}


def m_convert(ctx: wb.Ctx) -> dict:
    src = _by(ctx.get("records"))
    decs = ctx.records("decide")
    golden = []
    for d in decs:
        if d["decision"] != "new":
            continue
        rows = [src[d["id"]]] + [src[x["id"]] for x in decs if x["decision"] == "fold" and x["target"] == d["id"]]
        golden.append({"id": d["id"], "name": d["name"], "rows": [x["row"] for x in rows], "entity": _entity(src[d["id"]], rows, src[d["id"]]["type"])})
    ctx.put("golden", golden)
    ctx.output("reltio-entities.json", json.dumps([g["entity"] for g in golden], indent=1), label="The golden records as Reltio entities (JSON)")
    recs = [{"id": g["id"], "name": g["name"], "rows": ", ".join(map(str, g["rows"])), "crosswalks": len(g["entity"]["crosswalks"])} for g in golden]
    return {"summary": f"{len(golden)} golden record(s) with {sum(r['crosswalks'] for r in recs)} crosswalk(s) to the spreadsheet rows.", "counts": {"golden": len(golden)},
            "records": recs, "data": {"columns": ["Golden record", "From rows", "Crosswalks"], "rows": [[r["name"], r["rows"], r["crosswalks"]] for r in recs]}}


def m_prove(ctx: wb.Ctx) -> dict:
    src = ctx.get("records")
    by = _by(src)
    decs = {d["id"]: d for d in ctx.records("decide")}
    golden = ctx.get("golden") or []
    cw = sum(len(g["entity"]["crosswalks"]) for g in golden)
    n = {k: sum(1 for d in decs.values() if d["decision"] == k) for k in ("new", "link", "fold", "skip")}
    folded_ok = all(decs.get(d["target"], {}).get("decision") == "new" for d in decs.values() if d["decision"] == "fold")
    guard = [d["name"] for d in decs.values() if d["decision"] == "fold" and d["target"] in by and mr.false_friend(by[d["id"]], by[d["target"]])]
    missing = [g["name"] for g in golden if not (g["entity"]["attributes"].get("Name") and g["entity"]["attributes"].get("Country"))]
    sample = golden[:20]
    bad = [g["name"] for g in sample if g["entity"]["attributes"]["Name"][0]["value"] != by[g["id"]]["name"] or (g["entity"]["attributes"].get("Country") or [{}])[0].get("value") != by[g["id"]].get("country")]
    checks = [{"name": "rows", "label": "Every spreadsheet row lands in exactly one place", "status": "pass" if cw + n["link"] + n["skip"] == len(src) and folded_ok else "fail",
               "measured": cw + n["link"] + n["skip"], "expected": len(src), "detail": f"{cw} crosswalk(s) on {len(golden)} new golden record(s), {n['link']} linked, {n['skip']} skipped"},
              {"name": "guard", "label": "No false friend folded together", "status": "fail" if guard else "pass", "detail": ", ".join(guard) or "the guard holds"},
              {"name": "required", "label": "Every golden record has a name and a country", "status": "fail" if missing else "pass", "detail": ", ".join(missing)[:300] or "all have them"},
              {"name": "sample", "label": "Sampled golden records match their source rows", "status": "fail" if bad else "pass", "measured": f"{len(sample) - len(bad)} of {len(sample)}", "detail": ", ".join(bad) or "identical"}]
    return {"summary": f"{len(src)} row(s) accounted for.", "data": {"checks": checks}}


def m_handover(ctx: wb.Ctx) -> dict:
    golden = ctx.get("golden") or []
    return {"summary": f"{len(golden)} golden record(s) to create in the hub; the named owner signs off.",
            "data": {"items": [{"title": g["name"], "detail": f"rows {', '.join(map(str, g['rows']))}", "effort": ""} for g in golden[:80]], "total": f"{len(golden)} record(s)"}}


def m_run(ctx: wb.Ctx) -> dict:
    c = _hub(ctx)
    golden = ctx.get("golden") or []
    ops = [{"op": "create", "entities": [g["entity"] for g in golden[i:i + 100]], "what": f"create {len(golden[i:i + 100])} golden record(s): " + ", ".join(g["name"] for g in golden[i:i + 5])}
           for i in range(0, len(golden), 100)]
    cp = _ask_write(ctx, c, ops, f"Create {len(golden)} golden record(s) in {c['name']}") if ops else None
    cad = ctx.scope.get("cadence") or {"every": "day", "at": "06:00", "tz": "UTC"}
    item = wb.create(MODULE, "run", f"Watch: {c['name']}"[:160], who=ctx.owner, brief=f"New duplicates and gaps in {c['name']} after the masters moved in {ctx.id}.", connections=[c["id"]],
                     scope={"schedule": cad}, visibility=(db.project(ctx.id) or {}).get("visibility") or "private", team_id=(db.project(ctx.id) or {}).get("team_id"), parent=ctx.id)
    return {"summary": ("The golden records wait for their write approval in the Validation queue; " if cp else "Nothing to create; ") + f"a Run item watches {c['name']} from now on.",
            "data": {"href": f"#/m/{MODULE}/i/{item['id']}", "label": "Open the Run item", "text": cp["id"] if cp else ""}}


# ================================================================== Run & support

def r_watch(ctx: wb.Ctx) -> dict:
    c = _hub(ctx)
    if not c:
        raise wb.StepFailed("Pick the MDM hub to watch (its API connection).")
    recs = mr.from_reltio(c)
    seen = set(ctx.get("seen") or [])
    ps = mr.pairs(recs, rules_live(), refused())
    new_pairs = [p for p in ps if p["action"] != "not_match" and f"{p['a']}|{p['b']}" not in seen]
    gs = [g for g in mr.gaps(recs) if f"gap:{g['id']}" not in seen]
    ctx.put("seen", sorted(seen | {f"{p['a']}|{p['b']}" for p in ps} | {f"gap:{g['id']}" for g in mr.gaps(recs)})[-20000:])
    ctx.put("records", recs)
    ctx.put("new_pairs", new_pairs)
    ctx.put("new_gaps", gs)
    acts = mr.RELTIO.activities(c, 100)
    checks = [{"name": "pairs", "label": "New candidate duplicates", "status": "warn" if new_pairs else "pass", "measured": len(new_pairs), "detail": f"{len(new_pairs)} new since the last round"},
              {"name": "gaps", "label": "New gaps", "status": "warn" if gs else "pass", "measured": len(gs), "detail": f"{len(gs)} new"},
              {"name": "activity", "label": "Changes in the hub", "status": "pass", "measured": len(acts), "detail": f"{len(acts)} recent activit(ies) in the log"}]
    return {"summary": f"{len(new_pairs)} new candidate duplicate(s) and {len(gs)} new gap(s) in {c['name']}.", "counts": {"pairs": len(new_pairs), "gaps": len(gs)}, "data": {"checks": checks}}


def r_alert(ctx: wb.Ctx) -> dict:
    by = _by(ctx.get("records") or [])
    brk = []
    ps = ctx.get("new_pairs") or []
    if ps:
        names = sorted({by[p["a"]]["name"] for p in ps if p["a"] in by})
        brk.append({"id": "b-pairs", "what": f"{len(ps)} candidate duplicate(s): {', '.join(names[:8])}"[:300], "n": len(ps), "route": "steward", "note": "", "names": "\n".join(names)})
    gs = ctx.get("new_gaps") or []
    if gs:
        brk.append({"id": "b-gaps", "what": f"{len(gs)} record(s) with gaps: " + "; ".join(f"{g['name']} (no {', '.join(g['missing'])})" for g in gs[:6]), "n": len(gs), "route": "ticket", "note": "", "names": ""})
    ctx.put("breaks", brk)
    if not brk:
        return {"summary": "Nothing new since the last round.", "next": "report", "counts": {"breaks": 0}}
    return {"summary": f"{len(brk)} group(s) to route.", "counts": {"breaks": len(brk)}, "items": [b["what"] for b in brk],
            "data": {"columns": ["What", "Records", "Proposed route"], "rows": [[b["what"], b["n"], b["route"]] for b in brk]}}


def r_fix(ctx: wb.Ctx) -> dict:
    have = {r["id"]: r for r in ctx.records(ctx.step_id)}
    recs = [{**b, **({k: have[b["id"]][k] for k in ("route", "note") if k in have[b["id"]]} if b["id"] in have else {})} for b in ctx.get("breaks") or []]
    return {"summary": f"{len(recs)} group(s): choose who fixes each. Nothing goes out until you confirm.", "records": recs,
            "data": {"columns": ["What", "Proposed route"], "rows": [[r["what"], r["route"]] for r in recs]}}


RFIX_EDIT = wb.Edit(columns=[wb.Column("route", "Route", "select", options=(("steward", "The steward's queue (a Change item)"), ("ticket", "Raise a ticket"), ("expected", "Expected — no action"))),
                             wb.Column("note", "Note", "longtext"), wb.Column("what", "What", readonly=True)], add=False, remove=False, label="group")


def r_approve(ctx: wb.Ctx) -> dict:
    rows = []
    c = _hub(ctx)
    for b in ctx.records("fix"):
        if b["route"] == "steward":
            item = wb.create(MODULE, "change", f"Steward: {b['what']}"[:120], who=ctx.owner, brief=b["what"] + (f"\n\nNote: {b['note']}" if b.get("note") else ""),
                             connections=[c["id"]] if c else [], scope={"names": b.get("names") or ""}, visibility=(db.project(ctx.id) or {}).get("visibility") or "private",
                             team_id=(db.project(ctx.id) or {}).get("team_id"), parent=ctx.id)
            h = ctx._handoff({"kind": "change", "label": b["what"][:120], "status": "Change item started", "link": f"#/m/{MODULE}/i/{item['id']}", "output": item["id"]})
        elif b["route"] == "ticket":
            h = ctx.ticket(b["what"][:120], b["what"] + (f"\n\nNote: {b['note']}" if b.get("note") else ""), priority="P3", about=b["what"])
        else:
            h = {"kind": "expected", "status": "expected — recorded"}
        rows.append([b["what"][:160], b["route"], h.get("status"), h.get("case") or h.get("checkpoint") or h.get("output") or ""])
    return {"summary": f"{len(rows)} hand-off(s), as you approved.", "data": {"columns": ["What", "Route", "Status", "Reference"], "rows": rows}}


def r_report(ctx: wb.Ctx) -> dict:
    n = len(ctx.get("breaks") or [])
    ctx.output(f"master-data-report-{time.strftime('%Y%m%d-%H%M', time.gmtime())}.md", f"# Master data run report: {ctx.title}\n\n" + "".join(f"- {b['what']} → {b.get('route')}\n" for b in ctx.records("fix")),
               label="Run report (Markdown)")
    return {"summary": f"{n} group(s) this round.", "counts": {"groups": n}, "data": {"columns": ["Round", "Groups"], "rows": [[time.strftime("%d %b %H:%M", time.gmtime()), n]]}}


def _cards(u: dict) -> list[dict]:
    rows = [[r["a"][:30], r["b"][:30], r["decision"].replace("_", " "), r["rule"] or "", r["item"] or ""] for r in db.q("SELECT * FROM mdm_decisions ORDER BY created DESC LIMIT 20")]
    return [{"title": "Steward decisions", "columns": ["Record", "Record", "Decision", "Rule", "Work item"], "rows": rows,
             "empty": "None yet: a Change item's merges and not-a-match decisions are kept here, and a pair called not a match is never proposed again."}]


GUIDE = """# Master data — the work item

This folder is one work item of Relay's Master data module. Relay reads the hub's records (Reltio) and the masters
kept in spreadsheets, finds candidate duplicates with match rules people confirm, and proposes which record survives.
No agent is needed here: every proposal comes from a rule, and a person decides every merge."""


wb.register(wb.Pack(
    module=MODULE, guide=GUIDE,
    lineage="each golden record's crosswalks to the source systems' records (SAP, Salesforce, Zoho Books, the spreadsheet rows)",
    platforms={"hub": HUB, "masters": MASTERS},
    schemas={"finding": FIND_EDIT.columns, "pair": FIX_EDIT.columns, "rule": RULE_EDIT.columns, "row": DECIDE_EDIT.columns},
    cards=_cards,
    work={
        "assess": wb.Work(title="See every master record, how complete it is, and the duplicates, false friends and gaps", steps={
            "Connect": wb.Step(kind="platform", run=a_connect, agent="Connector", text="The hub answers through its API with your sign-in — or the spreadsheet masters are opened"),
            "Inventory": wb.Step(kind="platform", run=a_inventory, agent="Profiler", text="Every customer, supplier and product by source, with how complete each is"),
            "Health": wb.Step(kind="proof", run=a_health, view="gates", agent="Matcher",
                              text="The live match rules find duplicates (the hub's own matching compared), false friends are held apart, gaps and codes used twice are flagged"),
            "Findings": wb.Step(kind="person", run=a_findings, edit=FIND_EDIT, text="What needs attention — you keep or ignore each finding"),
            "Estimate": wb.Step(kind="deterministic", run=a_estimate, view="plan", agent="Estimator", text="The steward's queue, gaps for the source owners, false friends — with the time")}),
        "develop": wb.Work(title="Match rules proposed from the data, proven on the records, then live", steps={
            "Describe": wb.Step(kind="platform", run=d_describe, agent="Profiler", text="How full and how distinct each attribute is"),
            "Shape": wb.Step(kind="deterministic", run=d_shape, agent="Rule designer", edit=RULE_EDIT, text="The match rules, first match wins — you change, add or switch them off"),
            "Build": wb.Step(kind="deterministic", run=d_build, view="text", agent="Rule designer", text="The rules as Reltio match groups and as Relay's own rules"),
            "Prove": wb.Step(kind="proof", run=d_prove, view="gates", agent="Prover", back_to="shape", text="On the records: the false-friend guard holds, no group joins two tax ids, the hub's potential matches are found"),
            "Ship": wb.Step(kind="person", run=d_ship, view="plan", approver=True, text="The named approver confirms the rules"),
            "Run": wb.Step(kind="deterministic", run=d_run, view="link", agent="Publisher", text="The rules go live for every Change and Run item")}),
        "change": wb.Work(title="The steward's queue: merge or hold apart each candidate pair, written to the hub with approval", needs_source=True, steps={
            "Request": wb.Step(kind="platform", run=c_request, view="text", agent="Matcher", text="The candidate pairs by the live rules (only the names you give, if any)"),
            "Diagnose": wb.Step(kind="deterministic", run=c_diagnose, view="gates", agent="Matcher", text="Each pair: the rule that found it, what agrees and what does not"),
            "Fix": wb.Step(kind="deterministic", run=c_fix, agent="Steward", edit=FIX_EDIT, confirm_if=lambda ctx, out: True,
                           text="Merge, not a match or later for each pair, with the record that survives — you decide"),
            "Prove": wb.Step(kind="proof", run=c_prove, view="gates", agent="Prover", back_to="fix", text="Every record still there, the guard holds, no merge joins two tax ids, each record in one merge"),
            "Approve": wb.Step(kind="person", run=c_approve, view="plan", approver=True, text="The named approver releases the decisions"),
            "Learn": wb.Step(kind="platform", run=c_learn, view="link", agent="Publisher", text="The hub is written through its own write approval; the decisions are kept")},
            fields=[wb.Field("names", "Only these names", "longtext", help="Optional, one per line")]),
        "migrate": wb.Work(title="Move spreadsheet masters into the hub: folded, linked or created, every row accounted for", steps={
            "Discover": wb.Step(kind="platform", run=m_discover, agent="Profiler", text="The masters' rows and the hub's records"),
            "Decide": wb.Step(kind="deterministic", run=m_decide, agent="Matcher", edit=DECIDE_EDIT, text="Create, link (already in the hub), fold (a duplicate row) or skip each row"),
            "Convert": wb.Step(kind="deterministic", run=m_convert, agent="Mapper", text="Each golden record as the hub's entity, with a crosswalk per source row"),
            "Prove": wb.Step(kind="proof", run=m_prove, view="gates", agent="Reconciler", back_to="decide", text="Every row lands in exactly one place, no false friend folded, names and countries present"),
            "Hand over": wb.Step(kind="person", run=m_handover, view="plan", approver=True, text="The named owner signs off"),
            "Run": wb.Step(kind="platform", run=m_run, view="link", agent="Publisher", text="The records are created through the write approval; a Run item watches the hub")},
            fields=[wb.Field("cadence", "Watch the hub", "cadence", default={"every": "day", "at": "06:00", "tz": "UTC"})]),
        "run": wb.Work(title="Watch the hub: new duplicates go to the steward's queue, gaps to the source owner", needs_source=True, steps={
            "Watch": wb.Step(kind="platform", run=r_watch, view="gates", agent="Watcher", text="New candidate duplicates and gaps since the last round"),
            "Alert": wb.Step(kind="deterministic", run=r_alert, agent="Triage", text="Grouped by kind"),
            "Fix": wb.Step(kind="deterministic", run=r_fix, agent="Triage", edit=RFIX_EDIT, text="Relay proposes who fixes each; you confirm or change it"),
            "Approve": wb.Step(kind="platform", run=r_approve, agent="Dispatcher", text="The approved hand-offs go out: a Change item for the steward, a ticket for the source owner"),
            "Report": wb.Step(kind="deterministic", run=r_report, agent="Reporter", confirm_if=lambda ctx, out: bool(ctx.get("breaks")), text="A run report; you confirm it when something needed routing")},
            fields=[wb.Field("schedule", "Watch it", "cadence", default={"every": "day", "at": "07:00", "tz": "UTC"})]),
    }))
