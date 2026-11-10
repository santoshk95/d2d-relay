"""Assess & estimate (registry id `assess`) — size an estate from what the platform already read, estimate it with
the tenant's own estimation model and rate cards, and produce the proposal pack (as a consulting engagement).

Engagement  Discover → Size → Estimate → Propose (the registry's journey and confirm points: Size, Estimate).
Discover    the estate readers reuse the inventories other modules made, as the owner may see them: Migrate BI's scans
            (every object with its type and complexity, P15), other modules' finished Assess items (their Inventory
            records), Integration analytics' integrations (P13), Data observability's watched assets (P14), and
            inventory exports a person uploads (CSV / Excel with type, name and complexity columns).
Size        the estate in each tool's own terms — object type × complexity, with counts and where they came from; a
            person keeps or drops each group and may re-grade its complexity.
Estimate    the estimation model: hours per object of each type and complexity (from this workspace's saved model,
            confirmed by a named person, else typed in now — never a default), the rate-card role that does it (RFP &
            bid response's rate cards, P11) and its wave; a contingency the person states in the wizard. Rules first:
            a row without hours, or a role without a rate card, is refused.
Propose     the estimate (effort per wave with contingency, priced with rfp.compute_price — the RFP module's own
            pricing) into sources/estimate.json, an Excel workbook, the RFP price body, and the proposal pack through
            the P11 docs engine: the proposal deck and the estimate document, every figure sourced. The confirmed model
            is saved for this workspace (versioned), so the next estimate starts from it.
"""
from __future__ import annotations

import csv
import io
import json
import secrets
import time
from pathlib import Path

from .. import auth, db, registry, store
from .. import workbench as wb
from . import _consult as cx
from . import _narrative as nv

MODULE = "assess"
HOURS_PER_DAY = 8                     # the rate cards' own convention (rfp.compute_price: an hourly card is 8 hours a day)
COMPLEXITY = ("simple", "standard", "medium", "complex", "very complex")
WAVE_OF = {"simple": "Wave 1", "standard": "Wave 1", "medium": "Wave 2", "complex": "Wave 3", "very complex": "Wave 3"}

db.register_schema("""
CREATE TABLE IF NOT EXISTS assess_models (
  id TEXT PRIMARY KEY, object_type TEXT NOT NULL, complexity TEXT NOT NULL, hours REAL NOT NULL, role TEXT, version INTEGER NOT NULL DEFAULT 1,
  item TEXT, confirmed_by TEXT, confirmed REAL NOT NULL);
""")


class RecordsPlatform(wb.Platform):
    label = "Relay's own inventories"
    reads = ("Migrate BI's scans, other modules' Assess results, Integration analytics and Data observability inventories — what the owner may see; "
             "nothing is written")
    simulator = "the platform's own records, made in the tests through the modules' APIs (the Migrate BI sample estate model)"


class ExportsPlatform(wb.FilesPlatform):
    label = "Inventory exports"
    uploads = (".csv", ".xlsx")
    reads = "an inventory you upload (CSV or Excel) with a type, a name and, when you have it, a complexity column — a copy in this work item's folder"
    simulator = "inventory exports the tests write"


RECORDS, EXPORTS = RecordsPlatform(), ExportsPlatform()


# ------------------------------------------------------------------ the estate readers

def _migbi(u: dict) -> list[dict]:
    out = []
    for m in cx.migrations(u):
        p = store.root() / m["id"] / "estate.json"
        try:
            est = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        tool = (est.get("source") or {}).get("label") or "BI estate"
        groups: dict = {}
        for r in est.get("reports") or []:
            key = (str(r.get("type") or "object"), str(r.get("complexity") or "standard"))
            groups[key] = groups.get(key, 0) + 1
        for (typ, cplx), n in groups.items():
            out.append({"source": f"migbi:{m['id']}", "where": f"{m['title']} · {tool} (Migrate BI scan)", "type": f"{tool} {typ.lower()}", "complexity": cplx, "count": n})
    return out


def _workbench(u: dict) -> list[dict]:
    out = []
    for it in cx.work_items(u, exclude=MODULE):
        if it["work"] != "assess" or it["status"] not in ("done", "scheduled"):
            continue
        try:
            st = store.load(it["id"])
        except (KeyError, FileNotFoundError, ValueError):
            continue
        inv = next((s for s in st.get("steps") or [] if s["id"] == "inventory"), None)
        pack = wb.PACKS.get(it["module"])
        spec = pack.step("assess", "inventory") if pack else None
        label = (spec.edit.label if spec and spec.edit else "object")
        groups: dict = {}
        for r in (inv or {}).get("records") or []:
            if r.get("include") is False:
                continue
            key = str(r.get("complexity") or "standard")
            groups[key] = groups.get(key, 0) + 1
        for cplx, n in groups.items():
            out.append({"source": f"wb:{it['id']}", "where": f"{it['title']} ({it['module_name']} · Assess)", "type": f"{it['module_name']} {label}", "complexity": cplx, "count": n})
    return out


def _integrations(u: dict) -> list[dict]:
    if not (u and auth.is_dev(u)) or "intan_integrations" not in db.tables():
        return []
    rows = db.q("SELECT kind, via, COUNT(*) AS n FROM intan_integrations WHERE active = 1 GROUP BY kind, via")
    return [{"source": "intan", "where": "Integration analytics (the integrations it discovered)", "type": f"{(r['via'] or 'integration')} {r['kind']}".strip(),
             "complexity": "standard", "count": r["n"]} for r in rows]


def _observed(u: dict) -> list[dict]:
    if not (u and auth.is_dev(u)) or "observe_assets" not in db.tables():
        return []
    rows = db.q("SELECT layer, kind, COUNT(*) AS n FROM observe_assets WHERE enabled = 1 GROUP BY layer, kind")
    return [{"source": "observe", "where": "Data observability (the assets it watches)", "type": f"{r['layer']} {r['kind']}", "complexity": "standard", "count": r["n"]} for r in rows]


def _cols(header: list[str]) -> dict:
    h = {c.strip().lower(): i for i, c in enumerate(header)}
    pick = lambda *names: next((h[n] for n in names if n in h), None)  # noqa: E731
    return {"type": pick("type", "object type", "object_type", "kind"), "name": pick("name", "object", "object name"), "complexity": pick("complexity", "size")}


def _uploads(ctx: wb.Ctx) -> tuple[list[dict], list[str]]:
    out, notes = [], []
    for f in ctx.files((".csv", ".xlsx")):
        name = f.get("table") or f["name"]
        p = ctx.dir / "data" / name
        try:
            rows = list(csv.reader(io.StringIO(p.read_text(encoding="utf-8-sig"))))
        except (OSError, UnicodeDecodeError) as e:
            notes.append(f"{f['name']}: could not be read ({e})")
            continue
        if not rows:
            continue
        cols = _cols(rows[0])
        if cols["type"] is None:
            notes.append(f"{f['name']}: no type column (type, object type or kind) — not an inventory")
            continue
        groups: dict = {}
        for r in rows[1:]:
            if len(r) <= cols["type"] or not r[cols["type"]].strip():
                continue
            cplx = (r[cols["complexity"]].strip().lower() if cols["complexity"] is not None and len(r) > cols["complexity"] else "") or "standard"
            key = (r[cols["type"]].strip(), cplx if cplx in COMPLEXITY else "standard")
            groups[key] = groups.get(key, 0) + 1
        for (typ, cplx), n in groups.items():
            out.append({"source": f"upload:{f['name']}", "where": f"{f['name']} (uploaded inventory)", "type": typ, "complexity": cplx, "count": n})
    return out, notes


def discover(ctx: wb.Ctx) -> dict:
    u = cx.owner_user(ctx)
    cx.need(bool(u), "The owner is not an active person in this workspace any more.")
    want = {k: ctx.scope.get(k, True) is not False for k in ("migbi", "workbench", "integrations", "observability")}
    groups = []
    for k, fn in (("migbi", _migbi), ("workbench", _workbench), ("integrations", _integrations), ("observability", _observed)):
        if want[k]:
            groups += fn(u)
    up, notes = _uploads(ctx)
    groups += up
    for g in groups:
        g["id"] = cx.slug(f"{g['source']}|{g['type']}|{g['complexity']}", 100)
    if not groups:
        raise wb.StepFailed("No inventory to size: scan an estate in Migrate BI, finish another module's Assess, or upload an inventory export (CSV or Excel with a type column)."
                            + (" " + "; ".join(notes) if notes else ""))
    by_src: dict = {}
    for g in groups:
        s = by_src.setdefault(g["source"], {"source": g["source"], "where": g["where"], "groups": 0, "objects": 0})
        s["groups"] += 1
        s["objects"] += g["count"]
    rec = {"read": time.time(), "groups": groups, "sources": list(by_src.values()), "totals": {"objects": sum(g["count"] for g in groups), "groups": len(groups), "sources": len(by_src)}}
    cx.put(ctx, "estate", rec)
    ctx.put("groups", groups)
    ctx.evidence("What the estate readers found", {"rows": groups, "notes": notes}, kind="inventory", ok=True)
    return {"summary": f"{rec['totals']['objects']} object(s) in {len(groups)} group(s) from {len(by_src)} inventor{'y' if len(by_src) == 1 else 'ies'}" + (f"; {'; '.join(notes)}" if notes else "") + ".",
            "counts": {"objects": rec["totals"]["objects"], "groups": len(groups), "inventories": len(by_src)},
            "data": {"columns": ["Inventory", "Groups", "Objects"], "rows": [[s["where"], s["groups"], s["objects"]] for s in by_src.values()]}}


# ------------------------------------------------------------------ Size

def size(ctx: wb.Ctx) -> dict:
    fresh = [{**g, "include": True} for g in ctx.get("groups") or []]
    rows = cx.keep_edits(ctx, fresh, ("include", "complexity"))
    n = sum(r["count"] for r in rows if r.get("include"))
    return {"summary": f"{n} object(s) to size, in each tool's own terms — drop what is out of scope, re-grade a group's complexity if you know better.",
            "counts": {"objects": n, "groups": sum(1 for r in rows if r.get("include"))}, "records": rows,
            "items": [f"{r['type']} · {r['complexity']}: {r['count']}" for r in rows if r.get("include")][:8],
            "data": {"columns": ["In scope", "Type", "Complexity", "Objects", "From"], "rows": [["yes" if r.get("include") else "no", r["type"], r["complexity"], r["count"], r["where"]] for r in rows]}}


def _size_validate(recs: list[dict], ctx: wb.Ctx) -> list[str]:
    return [] if any(r.get("include") for r in recs) else ["Keep at least one group in scope."]


SIZE_EDIT = wb.Edit(columns=[wb.Column("include", "In scope", "bool"), wb.Column("type", "Type", readonly=True), wb.Column("complexity", "Complexity", "select", options=tuple((c, c) for c in COMPLEXITY)),
                             wb.Column("count", "Objects", "number", readonly=True), wb.Column("where", "From", readonly=True)], add=False, remove=False, validate=_size_validate, label="group")


# ------------------------------------------------------------------ Estimate: the model × the rate cards

def _cards() -> dict:
    from .. import rfp
    return {c["role"]: c for c in rfp.rate_cards()}


def _role_options(ctx=None) -> list[tuple[str, str]]:
    return [(r, f"{r} · {c['rate']:,.2f} {c['currency']} per {c['unit']}") for r, c in _cards().items()]


def model_rows() -> dict:
    return {(r["object_type"], r["complexity"]): r for r in db.q("SELECT * FROM assess_models")}


def estimate(ctx: wb.Ctx) -> dict:
    saved = model_rows()
    who = cx.names()
    lines: dict = {}
    for g in ctx.records("size"):
        if not g.get("include"):
            continue
        key = (g["type"], g["complexity"])
        ln = lines.setdefault(key, {"id": cx.slug(f"{g['type']}|{g['complexity']}", 100), "type": g["type"], "complexity": g["complexity"], "count": 0, "from": []})
        ln["count"] += g["count"]
        ln["from"].append(g["where"])
    fresh = []
    for (typ, cplx), ln in lines.items():
        m = saved.get((typ, cplx))
        fresh.append({"id": ln["id"], "type": typ, "complexity": cplx, "count": ln["count"], "hours_each": m["hours"] if m else None, "role": (m or {}).get("role") or "",
                      "wave": WAVE_OF.get(cplx, "Wave 1"), "hours_from": (f"this workspace's model v{m['version']}, confirmed by {who.get(m['confirmed_by'], m['confirmed_by'])} on {cx.when(m['confirmed'])}"
                                                                           if m else "not in the model yet: a person sets it")})
    recs = cx.keep_edits(ctx, fresh, ("hours_each", "role", "wave"))
    for r in recs:                                    # counts are always today's sizing
        f = next((x for x in fresh if x["id"] == r["id"]), None)
        if f:
            r["count"] = f["count"]
    _compute(recs)
    missing = [r for r in recs if not r.get("hours_each")]
    cards = _cards()
    return {"summary": (f"{len(recs)} line(s) of the estimation model; {len(missing)} still need their hours — " if missing else f"{len(recs)} line(s), every one from the model — ")
                       + ("pick the rate-card role for each line" if cards else "no rate cards yet (RFP & bid response › Rate cards), so the estimate is in hours only") + ".",
            "counts": {"lines": len(recs), "need hours": len(missing), "objects": sum(r["count"] for r in recs)}, "records": recs,
            "items": [f"{r['type']} · {r['complexity']}: {r['count']} × {r.get('hours_each') or '?'} h" for r in recs][:8],
            "data": {"columns": ["Type", "Complexity", "Objects", "Hours each", "Role", "Wave", "Hours"], "rows": [[r["type"], r["complexity"], r["count"], r.get("hours_each"), r.get("role"), r.get("wave"), r.get("hours")] for r in recs]}}


def _compute(recs: list[dict]) -> None:
    for r in recs:
        h = r.get("hours_each")
        r["hours"] = round(float(r["count"]) * float(h), 2) if h not in (None, "") else None


def _est_validate(recs: list[dict], ctx: wb.Ctx) -> list[str]:
    cards = _cards()
    probs = []
    for r in recs:
        try:
            h = float(r.get("hours_each"))
        except (TypeError, ValueError):
            h = None
        if not h or h <= 0:
            probs.append(f"{r['type']} · {r['complexity']}: hours each is needed — your estimation model; Relay never assumes one.")
        if cards and r.get("role") not in cards:
            probs.append(f"{r['type']} · {r['complexity']}: pick the rate-card role that does it.")
        if not str(r.get("wave") or "").strip():
            probs.append(f"{r['type']} · {r['complexity']}: name its wave.")
    try:
        c = float(ctx.scope.get("contingency_pct"))
        if not 0 <= c <= 100:
            probs.append("The contingency must be between 0 and 100 per cent.")
    except (TypeError, ValueError):
        probs.append("State the contingency (per cent) in the wizard.")
    _compute(recs)
    return probs


EST_EDIT = wb.Edit(columns=[wb.Column("type", "Type", readonly=True), wb.Column("complexity", "Complexity", readonly=True), wb.Column("count", "Objects", "number", readonly=True),
                            wb.Column("hours_each", "Hours each", "number", help="Effort per object of this type and complexity — your estimation model."),
                            wb.Column("role", "Role (rate card)", "select", options=_role_options), wb.Column("wave", "Wave"),
                            wb.Column("hours", "Hours", "number", readonly=True), wb.Column("hours_from", "Where the hours come from", readonly=True)],
                   add=False, remove=False, validate=_est_validate, label="line")


def compute(ctx: wb.Ctx) -> dict:
    """The estimate from the confirmed lines: hours per wave, with the contingency, priced through the RFP module's own
    pricing (rate cards × days in the cards' currency)."""
    from .. import rfp
    lines = [dict(r) for r in ctx.records("estimate")]
    _compute(lines)
    c = float(ctx.scope.get("contingency_pct") or 0)
    cards = _cards()
    waves: dict = {}
    for r in lines:
        w = waves.setdefault(r["wave"], {"wave": r["wave"], "objects": 0, "hours": 0.0, "lines": []})
        w["objects"] += r["count"]
        w["hours"] += r["hours"] or 0
        w["lines"].append(r)
    for w in waves.values():
        w["hours"] = round(w["hours"], 2)
        w["hours_with_contingency"] = round(w["hours"] * (1 + c / 100), 2)
        w["days"] = round(w["hours_with_contingency"] / HOURS_PER_DAY, 2)
    price, cur = None, ""
    if cards:
        cur = next(iter(cards.values()))["currency"]
        body = {"currency": cur, "fx": {}, "waves": [{"name": w["wave"], "lines": [{"role": r["role"], "days": round((r["hours"] or 0) * (1 + c / 100) / HOURS_PER_DAY, 4), "module": MODULE}
                                                                           for r in w["lines"]]} for w in sorted(waves.values(), key=lambda w: cx.natural(w["wave"]))]}
        try:
            price = rfp.compute_price(body)
        except rfp.RfpError as e:
            raise wb.StepFailed(f"The rate cards could not price it: {e}") from e
        for pw in price["waves"]:
            waves[pw["name"]]["cost"] = pw["total"]
        ctx.output("rfp-price.json", json.dumps(body, indent=1), label="The price, ready for RFP & bid response (its Price step's body)")
    ws = sorted(waves.values(), key=lambda w: cx.natural(w["wave"]))
    totals = {"objects": sum(w["objects"] for w in ws), "hours": round(sum(w["hours"] for w in ws), 2), "hours_with_contingency": round(sum(w["hours_with_contingency"] for w in ws), 2),
              "days": round(sum(w["days"] for w in ws), 2), "waves": len(ws), "cost": price["totals"]["total"] if price else None}
    rec = {"currency": cur, "contingency_pct": c, "hours_per_day": HOURS_PER_DAY, "priced": bool(price),
           "lines": [{k: r.get(k) for k in ("type", "complexity", "count", "hours_each", "hours", "role", "wave", "hours_from")} for r in lines],
           "waves": [{k: w.get(k) for k in ("wave", "objects", "hours", "hours_with_contingency", "days", "cost")} for w in ws], "totals": totals,
           "rows": [[r["type"], r["complexity"], r["count"], cx.num(r["hours_each"]), cx.num(r["hours"]), r.get("role") or "—", r["wave"]] for r in lines],
           "wave_rows": [[w["wave"], w["objects"], cx.num(w["hours"]), cx.num(w["hours_with_contingency"]), cx.num(w["days"]), cx.money(w["cost"], cur) if w.get("cost") is not None else "not priced"] for w in ws],
           "rate_cards": [{"role": r, "rate": x["rate"], "currency": x["currency"], "unit": x["unit"]} for r, x in cards.items()],
           "price": price, "estate": (cx.read(ctx, "estate") or {}).get("totals")}
    if not price:
        rec["totals"]["cost"] = 0
    cx.put(ctx, "estimate", rec)
    _xlsx(ctx, rec)
    return rec


def _xlsx(ctx: wb.Ctx, rec: dict) -> None:
    import openpyxl
    book = openpyxl.Workbook()
    ws = book.active
    ws.title = "Estimate"
    ws.append(["Type", "Complexity", "Objects", "Hours each", "Hours", "Role", "Wave", "Hours from"])
    for r in rec["lines"]:
        ws.append([r["type"], r["complexity"], r["count"], r["hours_each"], r["hours"], r["role"], r["wave"], r["hours_from"]])
    w2 = book.create_sheet("Waves")
    w2.append(["Wave", "Objects", "Hours", f"Hours with {rec['contingency_pct']:g} % contingency", "Days", f"Cost ({rec['currency'] or 'not priced'})"])
    for w in rec["waves"]:
        w2.append([w["wave"], w["objects"], w["hours"], w["hours_with_contingency"], w["days"], w.get("cost")])
    w3 = book.create_sheet("Assumptions")
    for k, v in (("Contingency (per cent)", rec["contingency_pct"]), ("Hours per day (the rate cards' convention)", rec["hours_per_day"]),
                 ("Priced from", "this workspace's rate cards" if rec["priced"] else "no rate cards: not priced")):
        w3.append([k, v])
    buf = io.BytesIO()
    book.save(buf)
    ctx.output("estimate.xlsx", buf.getvalue(), label="The estimate (Excel)")


def save_model(ctx: wb.Ctx, rec: dict) -> int:
    """The confirmed hours become this workspace's estimation model (a new version of each changed line)."""
    who = ctx.who or ctx.owner
    have = model_rows()
    n = 0
    for r in rec["lines"]:
        key = (r["type"], r["complexity"])
        old = have.get(key)
        if old and abs(float(old["hours"]) - float(r["hours_each"])) < 1e-9 and (old.get("role") or "") == (r.get("role") or ""):
            continue
        now = time.time()
        if old:
            db.run("UPDATE assess_models SET hours = ?, role = ?, version = ?, item = ?, confirmed_by = ?, confirmed = ? WHERE id = ?",
                   (float(r["hours_each"]), r.get("role"), old["version"] + 1, ctx.id, who, now, old["id"]))
        else:
            db.run("INSERT INTO assess_models (id, object_type, complexity, hours, role, version, item, confirmed_by, confirmed) VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)",
                   ("am-" + secrets.token_hex(4), r["type"], r["complexity"], float(r["hours_each"]), r.get("role"), ctx.id, who, now))
        n += 1
    if n:
        db.audit("assess.model.save", ctx.id, {"lines": n}, who)
    return n


# ------------------------------------------------------------------ Propose: the proposal pack through the docs engine

def specs(ctx: wb.Ctx, rec: dict) -> tuple[dict, dict, list[dict]]:
    t, cur = rec["totals"], rec["currency"]
    E = "record:estimate"
    est = cx.read(ctx, "estate") or {}
    day = cx.iso_day(time.time())
    a1, f1 = cx.say("Relay read {o} objects from {s} inventories of the platform's own records and your uploads.", o=(est.get("totals", {}).get("objects", 0), "record:estate#totals.objects"),
                    s=(est.get("totals", {}).get("sources", 0), "record:estate#totals.sources"))
    a2, f2 = cx.say("{o} of them are in scope, in {w} waves: {h} hours of effort, {hc} hours with the contingency of {c}.", o=(t["objects"], f"{E}#totals.objects"),
                    w=(t["waves"], f"{E}#totals.waves"), h=(t["hours"], f"{E}#totals.hours"), hc=(t["hours_with_contingency"], f"{E}#totals.hours_with_contingency"),
                    c=(rec["contingency_pct"], f"{E}#contingency_pct", "%"))
    if rec["priced"]:
        a3, f3 = cx.say("Priced from this workspace's rate cards: {p} for {d} days.", p=(t["cost"], f"{E}#totals.cost", f"money:{cur}"), d=(t["days"], f"{E}#totals.days"))
    else:
        a3, f3 = "Not priced: this workspace has no rate cards yet, so the estimate is in hours only.", []
    asm, asm_f = cx.say("Contingency: {c}, stated by the person who asked for the estimate.", c=(rec["contingency_pct"], f"{E}#contingency_pct", "%"))
    doc_blocks = [{"kind": "paragraph", "text": a1, "figures": f1}, {"kind": "paragraph", "text": a2, "figures": f2}, {"kind": "paragraph", "text": a3, "figures": f3}] + nv.blocks(ctx)
    sections = [{"title": "What we found", "blocks": doc_blocks + [{"kind": "table", "table": cx.table(["Inventory", "Groups", "Objects"], [[s["where"], s["groups"], s["objects"]] for s in est.get("sources") or []] or [["—"] * 3],
                                                                                                      "record:estate#sources", "Where the objects were read")}]},
                {"title": "The estimate, line by line", "blocks": [{"kind": "table", "table": cx.table(["Type", "Complexity", "Objects", "Hours each", "Hours", "Role", "Wave"], ch, f"{E}#rows",
                                                                                                    "Objects × hours each, from the estimation model a named person confirmed")} for ch in cx.chunks(rec["rows"])]},
                {"title": "Waves", "blocks": [{"kind": "table", "table": cx.table(["Wave", "Objects", "Hours", "With contingency", "Days", "Cost"], rec["wave_rows"], f"{E}#wave_rows", "Effort and cost per wave")}]},
                {"title": "Assumptions", "blocks": [{"kind": "bullets", "bullets": [asm, "A day is the rate cards' working day; hours are converted to days the same way the RFP module prices."],
                                                     "figures": asm_f},
                                                    {"kind": "paragraph", "text": f"Everything here comes from Relay's own records and the inventories you uploaded, read on {day}; "
                                                                                  "the hours per object are this workspace's estimation model, confirmed by a named person."}]}]
    doc = {"kind": "doc", "title": f"Estimate: {ctx.title}"[:70], "subtitle": f"Assess & estimate · {day}", "audience": ctx.scope.get("audience") or "the client's sponsor", "date": day, "sections": sections}
    k1, g1 = cx.say("{o} objects in scope, in {w} waves", o=(t["objects"], f"{E}#totals.objects"), w=(t["waves"], f"{E}#totals.waves"))
    k2, g2 = cx.say("{h} hours with the contingency of {c}", h=(t["hours_with_contingency"], f"{E}#totals.hours_with_contingency"), c=(rec["contingency_pct"], f"{E}#contingency_pct", "%"))
    k3, g3 = (cx.say("{p} from the rate cards", p=(t["cost"], f"{E}#totals.cost", f"money:{cur}")) if rec["priced"] else ("Not priced: no rate cards in this workspace", []))
    slides = [{"layout": "title", "title": ctx.title[:70], "subtitle": f"Proposal · Assess & estimate · {day}"},
              {"layout": "bullets", "title": "The estate and the estimate", "bullets": [k1, k2, k3], "figures": g1 + g2 + g3,
               "notes": "Every figure links to the estimate record; the hours per object are the workspace's confirmed estimation model."},
              {"layout": "chart", "title": "Effort per wave", "chart": {"type": "column", "categories": [w["wave"] for w in rec["waves"]],
                                                                       "series": [{"name": "Hours with contingency", "values": [float(w["hours_with_contingency"]) for w in rec["waves"]]}],
                                                                       "unit": "hours", "source": f"{E}#waves", "alt": "Hours of effort per wave, with the contingency"}},
              {"layout": "table", "title": "Waves", "table": cx.table(["Wave", "Objects", "Hours", "With contingency", "Days", "Cost"], rec["wave_rows"][:14], f"{E}#wave_rows", "Effort and cost per wave")}]
    for i, ch in enumerate(cx.chunks(rec["rows"])):
        slides.append({"layout": "table", "title": "How it was sized" + (f" ({i + 1})" if len(rec["rows"]) > 14 else ""),
                       "table": cx.table(["Type", "Complexity", "Objects", "Hours each", "Hours", "Role", "Wave"], ch, f"{E}#rows", "The estimation model, line by line")})
    nar = ctx.get("narrative") or []
    if nar:
        slides.append({"layout": "bullets", "title": "In short", "bullets": [p["text"] for p in nar], "figures": [f for p in nar for f in p.get("figures") or []]})
    slides += [{"layout": "bullets", "title": "Next steps", "bullets": ["Agree the waves and the order with your team", "Confirm the scope of the first wave",
                                                                      "Relay runs each wave on the platform, with the proof behind every number"]},
               {"layout": "closing", "title": "Thank you", "bullets": [cx.brand_line()]}]
    deck = {"kind": "deck", "title": f"Proposal: {ctx.title}"[:70], "subtitle": f"Assess & estimate · {day}", "audience": ctx.scope.get("audience") or "the client's sponsor", "date": day,
            "sections": [{"title": "Proposal", "slides": slides}]}
    figs = [{"label": f["text"], "value": f["value"], "source": f["source"]} for f in f1 + f2 + f3 + g1 + g2 + g3]
    return doc, deck, figs


def propose(ctx: wb.Ctx) -> dict:
    rec = compute(ctx)
    saved = save_model(ctx, rec)
    doc, deck, figs = specs(ctx, rec)
    a = cx.deliver(ctx, "estimate", doc, "Estimate")
    b = cx.deliver(ctx, "proposal-deck", deck, "Proposal deck")
    gates = [a["gate"], b["gate"], ctx.proof("sourced", label="Every figure of the proposal pack resolves to its record", figures=figs)]
    ok = a["ok"] and b["ok"] and gates[-1]["status"] == "pass"
    t = rec["totals"]
    ctx.put("summary", {"objects": t["objects"], "hours": t["hours_with_contingency"], "cost": t["cost"] if rec["priced"] else None, "currency": rec["currency"], "when": time.time()})
    return {"summary": (f"{t['objects']} object(s), {cx.num(t['hours_with_contingency'])} h with contingency" + (f", {cx.money(t['cost'], rec['currency'])}" if rec["priced"] else ", not priced")
                        + f" — the proposal deck and the estimate pass every check" + (f"; {saved} line(s) of the estimation model saved for next time" if saved else "") + "."
                        if ok else "The proposal pack did not pass its checks: " + "; ".join((a["problems"] + b["problems"])[:3])),
            "ok": ok, "counts": {"objects": t["objects"], "hours": t["hours_with_contingency"], "model lines saved": saved}, "data": {"checks": gates}}


def _page_cards(u: dict) -> list[dict]:
    who = cx.names()
    model = [[r["object_type"], r["complexity"], cx.num(r["hours"]), r.get("role") or "—", f"v{r['version']}", who.get(r["confirmed_by"], r["confirmed_by"] or "—"), cx.when(r["confirmed"])]
             for r in sorted(db.q("SELECT * FROM assess_models"), key=lambda r: (r["object_type"].lower(), COMPLEXITY.index(r["complexity"]) if r["complexity"] in COMPLEXITY else 9))]
    rows = db.q("SELECT id, title FROM wb_items WHERE module = ? AND status IN ('done', 'scheduled') ORDER BY updated DESC LIMIT 30", (MODULE,))
    vis = auth.access_map(u, [r["id"] for r in rows]) if u else {}
    ests = []
    for r in rows:
        if r["id"] not in vis:
            continue
        s = (wb._load(r["id"]).get("data") or {}).get("summary") or {}
        ests.append([r["title"], s.get("objects"), cx.num(s.get("hours")), cx.money(s["cost"], s.get("currency")) if s.get("cost") is not None else "not priced", f"#/m/{MODULE}/i/{r['id']}"])
    return [{"title": "Estimation model", "columns": ["Type", "Complexity", "Hours each", "Role", "Version", "Confirmed by", "When"], "rows": model,
             "empty": "No estimation model yet: the first confirmed estimate saves one for this workspace."},
            {"title": "Estimates", "columns": ["Estimate", "Objects", "Hours", "Cost", "Open"], "rows": ests, "empty": "No finished estimate yet."}]


GUIDE = """# Assess & estimate — the work item

This folder is one estimate of Relay's Assess & estimate module. The sizing comes from inventories the platform
already holds (Migrate BI scans, other modules' Assess results, Integration analytics, Data observability) and
uploaded inventory exports; the hours per object are this workspace's estimation model, set by a named person; the
price comes from the rate cards.

- `sources/estate.json`: every group of objects with its count and where it was read.
- `sources/estimate.json`: the confirmed lines, the waves with the contingency, the price.
- `estimate.yaml`, `proposal-deck.yaml`: what the docs engine built (the same as `genbi doc|deck build`).
- `narrative.yaml`: what you write when asked — a few paragraphs, every number declared with its `record:` source.

Never write a number the records do not hold; never assume hours or rates."""


wb.register(wb.Pack(
    module=MODULE, guide=GUIDE, cards=_page_cards,
    lineage="none: an estimate reads other modules' inventories and writes nothing back",
    platforms={"relay": RECORDS, "exports": EXPORTS},
    schemas={"group": SIZE_EDIT.columns, "line": EST_EDIT.columns},
    work={"engage": wb.Work(
        title="Size an estate from what Relay already read, estimate it with your model and rate cards, and produce the proposal pack",
        needs_source=False, platforms=("relay", "exports"),
        steps={
            "Discover": wb.Step(kind="platform", run=discover, agent="Estate reader",
                                text="Migrate BI's scans, other modules' Assess results, Integration analytics and Data observability inventories — and any inventory export you upload"),
            "Size": wb.Step(kind="deterministic", run=size, agent="Sizer", edit=SIZE_EDIT,
                            text="The estate in each tool's own terms: object type × complexity with counts and where they came from — you keep, drop or re-grade each group"),
            "Estimate": wb.Step(kind="deterministic", run=estimate, agent="Estimator", edit=EST_EDIT,
                                text="Hours per object from this workspace's estimation model (or typed by you now), the rate-card role and the wave of each line; the contingency you stated"),
            "Propose": wb.Step(kind="deterministic", run=propose, view="gates", agent="Proposal writer", back_to="estimate",
                               confirm="the proposal deck and the estimate before they go out", confirm_if=lambda ctx, out: out["ok"],
                               actions={"wording": nv.action(("estate", "estimate"), "Explain the estimate for the client's sponsor: what was found, how it was sized, the waves and the price.",
                                                             agent="Proposal writer", rebuild=lambda ctx: propose(ctx))},
                               text="The estimate priced with the RFP module's rate cards, the Excel workbook, and the proposal deck and estimate document through the docs engine — every figure sourced")},
        fields=[wb.Field("contingency_pct", "Contingency (per cent)", "number", required=True, help="Stated by you and shown as an assumption in the proposal."),
                wb.Field("migbi", "Read Migrate BI's scans", "bool", default=True), wb.Field("workbench", "Read other modules' finished Assess items", "bool", default=True),
                wb.Field("integrations", "Read Integration analytics' inventory", "bool", default=True), wb.Field("observability", "Read Data observability's assets", "bool", default=True),
                wb.Field("audience", "Who the proposal is for", "text", default=""),
                wb.Field("template", "Template", "select", options=cx.template_options, default="relay")])}))
