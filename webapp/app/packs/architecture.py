"""Architecture & technical design (registry id `architecture`) — the target architecture, chosen with reasons, and
P11's Present step: the architecture deck and the design pack through the docs engine; as a consulting engagement.

Engagement  the registry's journey Needs → Options → Compare → Design → Approve → Present (confirm points: Options,
            Design, Present, with the registry's words; Needs, Compare and Approve wait for a person too).
Needs       the requirements and constraints: from a Strategy & roadmap item (its target and gaps), a Tool & vendor
            selection (its requirements), a requirements sheet the person uploads — and what runs today on the
            platform (connections by kind, the systems of the lineage graph).
Options     per area (warehouse, BI, integration, automation, AI) the candidates Relay's catalogue lists, those already
            in use marked; a person picks the short list.
Compare     each short-listed option scored 1 to 5 on cost, security, skills and fit — with the reason written down.
Design      the target architecture: the best-scored option per area, the systems and flows of the knowledge map, the
            security design from the platform's own settings (read-only connections, writes by approval, secrets by
            name); a diagram drawn from it (Mermaid → the deck's native shapes).
Approve     an architecture decision record per area — context, decision, alternatives with their scores, consequences
            — approved by the named approver.
Present     the architecture deck (PowerPoint) and the design pack (Word: HLD, the diagram, the ADRs) through the P11
            docs engine, every figure sourced; a person confirms them before they go out.
"""
from __future__ import annotations

import json
import re
import time

from .. import auth, connectors, db, registry, store
from .. import workbench as wb
from . import _consult as cx
from . import _narrative as nv

MODULE = "architecture"
AREAS = [("warehouse", "Warehouse & lakehouse", ["dwh"]), ("bi", "BI & dashboards", ["bi"]), ("integration", "Integration", ["apis", "pipelines"]),
         ("automation", "Automation", ["n8n", "rpa"]), ("ai", "AI", ["agents", "assist"])]
CRITERIA = ("cost", "security", "skills", "fit")


class DesignPlatform(wb.Platform):
    label = "Relay's records, and your requirements"
    uploads = (".csv", ".xlsx", ".docx", ".pdf", ".txt", ".md")
    reads = ("a strategy and a selection made on Relay, the connections and the lineage graph (what runs today), and the requirements you upload — "
             "nothing is written")
    simulator = "the platform's own records made in the tests; a requirements sheet the tests write"


DESIGN = DesignPlatform()


def _done_items(module: str, u: dict) -> list[tuple[str, str]]:
    rows = db.q("SELECT id, title FROM wb_items WHERE module = ? AND status IN ('done', 'scheduled') ORDER BY updated DESC LIMIT 40", (module,))
    vis = auth.access_map(u, [r["id"] for r in rows]) if u else {}
    return [("", "None")] + [(r["id"], r["title"]) for r in rows if r["id"] in vis]


def _today(u: dict) -> dict:
    kinds = {}
    if u and auth.is_dev(u):
        for r in db.q("SELECT kind, COUNT(*) AS n FROM connections GROUP BY kind"):
            kinds[connectors.KINDS.get(r["kind"], {}).get("label", r["kind"])] = r["n"]
    systems = [{"system": r["system"], "nodes": r["n"]} for r in db.q("SELECT system, COUNT(*) AS n FROM lineage_nodes WHERE system <> '' GROUP BY system ORDER BY COUNT(*) DESC LIMIT 8")] \
        if u and auth.is_dev(u) else []
    return {"connections": kinds, "systems": systems, "edges": db.one("SELECT COUNT(*) AS n FROM lineage_edges")["n"] if u and auth.is_dev(u) else 0,
            "write_scoped": db.one("SELECT COUNT(*) AS n FROM connections WHERE scope = 'write'")["n"] if u and auth.is_dev(u) else 0}


# ------------------------------------------------------------------ Needs

def _may(u: dict, item: str, module: str) -> bool:
    row = db.one("SELECT module FROM wb_items WHERE id = ?", (item,))
    return bool(u and row and row["module"] == module and auth.can_project(u, "view", db.project(item)))


def needs(ctx: wb.Ctx) -> dict:
    u = cx.owner_user(ctx)
    found = []
    sid = ctx.scope.get("strategy_item") or ""
    if sid and not _may(u, sid, "strategy"):
        raise wb.StepFailed("The strategy this design starts from is not one its owner may see.")
    sel = ctx.scope.get("selection_item") or ""
    if sel and not _may(u, sel, "selection"):
        raise wb.StepFailed("The selection this design starts from is not one its owner may see.")
    if sid:
        mat = _source_of(sid, "maturity")
        for d in (mat or {}).get("dimensions") or []:
            if d.get("target", d["score"]) > d["score"]:
                found.append({"id": f"strat-{cx.slug(d['dimension'])}", "kind": "requirement", "need": f"{d['dimension']}: from level {d['score']} to {d['target']}",
                              "source": f"Strategy {sid}, its confirmed target"})
    if sel:
        try:
            st = wb._load(sel)
            reqs = next((s.get("records") or [] for s in st["steps"] if s["id"] == "requirements"), [])
        except (KeyError, FileNotFoundError, ValueError):
            reqs = []
        for r in reqs:
            found.append({"id": f"sel-{cx.slug(r.get('ref') or r['id'])}", "kind": "requirement" if not r.get("mandatory") else "constraint", "need": r["text"],
                          "source": f"Selection {sel}, requirement {r.get('ref')}"})
    from .selection import _sheet_rows
    rows, _notes = _sheet_rows(ctx)
    for r in rows:
        found.append({"id": f"sheet-{r['ref']}", "kind": "constraint" if r.get("mandatory") else "requirement", "need": r["text"], "source": r["source"]})
    t = _today(u)
    for label, n in t["connections"].items():
        found.append({"id": f"today-{cx.slug(label)}", "kind": "constraint", "need": f"Runs today: {label} ({n} connection{'s' if n != 1 else ''})", "source": "Relay's connections"})
    for s in t["systems"][:5]:
        found.append({"id": f"lineage-{cx.slug(s['system'])}", "kind": "constraint", "need": f"Runs today: {s['system']} in the lineage graph ({s['nodes']} nodes)", "source": "the knowledge map"})
    cx.put(ctx, "today", t)
    for f in found:
        f["origin"] = "relay"
    recs = cx.keep_edits(ctx, found, ("kind", "need"))
    return {"summary": f"{len(recs)} requirement(s) and constraint(s) from the strategy, the selection, your sheet and what runs today — add what is missing.",
            "counts": {"needs": len(recs), "constraints": sum(1 for r in recs if r["kind"] == "constraint")}, "records": recs,
            "data": {"columns": ["Kind", "Need", "Source"], "rows": [[r["kind"], r["need"], r.get("source") or "added by a person"] for r in recs]}}


def _source_of(item: str, name: str):
    try:
        return json.loads((store.root() / item / "sources" / f"{name}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _needs_validate(recs: list[dict], ctx: wb.Ctx) -> list[str]:
    probs = [] if recs else ["Add at least one requirement or constraint."]
    probs += [f"Row {i}: say what the need is." for i, r in enumerate(recs, 1) if not str(r.get("need") or "").strip()]
    from .delivery import _text_problems
    return probs + _text_problems(recs, ("need",))


NEEDS_EDIT = wb.Edit(columns=[wb.Column("kind", "Kind", "select", options=(("requirement", "Requirement"), ("constraint", "Constraint"))), wb.Column("need", "Need", "longtext", required=True),
                              wb.Column("source", "Source", readonly=True)], validate=_needs_validate, label="need")


# ------------------------------------------------------------------ Options

def options(ctx: wb.Ctx) -> dict:
    t = cx.read(ctx, "today") or {"connections": {}, "systems": []}
    in_use = {k.lower() for k in t["connections"]} | {s["system"].lower() for s in t["systems"]}
    fresh = []
    for area, label, mods in AREAS:
        seen = []
        for m in mods:
            for p in (registry.BY_ID.get(m) or {}).get("platforms") or []:
                if p not in seen:
                    seen.append(p)
        for i, p in enumerate(seen[:8]):
            used = any(p.lower() == x or p.lower() in x or x in p.lower() for x in in_use if len(x) > 3)
            fresh.append({"id": f"{area}-{cx.slug(p)}", "area": label, "area_id": area, "option": p, "why": ("in use today" if used else f"listed by Relay's catalogue ({', '.join(mods)})"),
                          "shortlist": used or i < 2, "origin": "catalogue"})
    recs = cx.keep_edits(ctx, fresh, ("shortlist", "why"))
    for r in recs:
        if r.get("origin") == "person" and not r.get("area_id"):
            r["area_id"] = next((a for a, l, _ in AREAS if l == r.get("area")), "")
    return {"summary": f"{len(recs)} option(s) across {len(AREAS)} areas from Relay's catalogue, those in use today marked — pick the short list for each area.",
            "counts": {"options": len(recs), "short list": sum(1 for r in recs if r.get("shortlist"))}, "records": recs,
            "data": {"columns": ["Short list", "Area", "Option", "Why"], "rows": [["yes" if r.get("shortlist") else "no", r["area"], r["option"], r["why"]] for r in recs]}}


def _opt_validate(recs: list[dict], ctx: wb.Ctx) -> list[str]:
    probs = []
    for _a, label, _m in AREAS:
        if not any(r.get("shortlist") and r.get("area") == label for r in recs):
            probs.append(f"{label}: put at least one option on the short list.")
    probs += [f"{r.get('option') or 'A row'}: why is it an option?" for r in recs if not str(r.get("why") or "").strip()]
    probs += [f"{r.get('option') or 'A row'}: its area is one of {', '.join(l for _, l, _ in AREAS)}." for r in recs if r.get("area") not in [l for _, l, _ in AREAS]]
    from .delivery import _text_problems
    return probs + _text_problems(recs, ("option", "why"))


OPT_EDIT = wb.Edit(columns=[wb.Column("shortlist", "Short list", "bool"), wb.Column("area", "Area", "select", options=tuple((l, l) for _, l, _ in AREAS)),
                            wb.Column("option", "Option", required=True), wb.Column("why", "Why it is an option")], validate=_opt_validate, label="option")


# ------------------------------------------------------------------ Compare

def compare(ctx: wb.Ctx) -> dict:
    fresh = [{"id": r["id"], "area": r["area"], "option": r["option"], **{c: None for c in CRITERIA}, "reason": ""} for r in ctx.records("options") if r.get("shortlist")]
    recs = cx.keep_edits(ctx, fresh, (*CRITERIA, "reason"))
    _totals(recs)
    return {"summary": f"{len(recs)} short-listed option(s): score each 1 to 5 on cost, security, skills and fit, and write down the reason.",
            "counts": {"options": len(recs)}, "records": recs,
            "data": {"columns": ["Area", "Option", "Cost", "Security", "Skills", "Fit", "Total"], "rows": [[r["area"], r["option"], *[r.get(c) for c in CRITERIA], r.get("total")] for r in recs]}}


def _totals(recs: list[dict]) -> None:
    for r in recs:
        vals = [r.get(c) for c in CRITERIA]
        r["total"] = sum(float(v) for v in vals) if all(isinstance(v, (int, float)) for v in vals) else None


def _cmp_validate(recs: list[dict], ctx: wb.Ctx) -> list[str]:
    probs = []
    for r in recs:
        for c in CRITERIA:
            v = r.get(c)
            if not (isinstance(v, (int, float)) and float(v).is_integer() and 1 <= v <= 5):
                probs.append(f"{r['option']}: {c} is scored 1 to 5.")
                break
        if not str(r.get("reason") or "").strip():
            probs.append(f"{r['option']}: write down the reason for its scores.")
    _totals(recs)
    from .delivery import _text_problems
    return probs + _text_problems(recs, ("reason",))


CMP_EDIT = wb.Edit(columns=[wb.Column("area", "Area", readonly=True), wb.Column("option", "Option", readonly=True), *[wb.Column(c, c.title(), "number") for c in CRITERIA],
                            wb.Column("reason", "The reason", "longtext"), wb.Column("total", "Total", "number", readonly=True)], add=False, remove=False, validate=_cmp_validate, label="option")


# ------------------------------------------------------------------ Design

def _chosen(ctx: wb.Ctx) -> list[dict]:
    recs = ctx.records("compare")
    _totals(recs)
    out = []
    for _a, label, _m in AREAS:
        rs = sorted([r for r in recs if r["area"] == label], key=lambda r: -(r.get("total") or 0))
        if rs:
            out.append({"area": label, "chosen": rs[0], "others": rs[1:]})
    return out


def _mermaid(comps: list[dict], systems: list[dict]) -> str:
    def node(i, text):
        return f'N{i}["{re.sub(r"[^A-Za-z0-9 ,./()-]+", " ", text.replace("&", "and"))[:44].strip()}"]'
    by = {c["layer"]: c["component"] for c in comps}
    lines = ["graph LR"]
    src = [s["system"] for s in systems[:3]] or ["Source systems"]
    ids = {}
    for i, s in enumerate(src):
        ids[f"s{i}"] = node(f"s{i}", s)
    chain = [x for x in ("Integration", "Warehouse & lakehouse", "BI & dashboards") if x in by]
    for i, layer in enumerate(chain):
        ids[layer] = node(f"c{i}", f"{layer}: {by[layer]}")
    first = chain[0] if chain else None
    for k_ in [k for k in ids if k.startswith("s")]:
        if first:
            lines.append(f"  {ids[k_]} --> {ids[first]}")
    for a, b in zip(chain, chain[1:]):
        lines.append(f"  {ids[a]} --> {ids[b]}")
    for extra, j in (("Automation", "x1"), ("AI", "x2")):
        if extra in by and chain:
            lines.append(f"  {node(j, extra + ': ' + by[extra])} -.-> {ids[chain[-1]]}")
    return "\n".join(lines)


def design(ctx: wb.Ctx) -> dict:
    t = cx.read(ctx, "today") or {"systems": [], "write_scoped": 0, "connections": {}}
    fresh = []
    for ch in _chosen(ctx):
        c = ch["chosen"]
        fresh.append({"id": cx.slug(ch["area"]), "layer": ch["area"], "component": c["option"], "why": f"the best score of the comparison ({cx.num(c.get('total'))} of 20)",
                      "notes": ""})
    recs = cx.keep_edits(ctx, fresh, ("component", "notes"))
    security = [["Sign-in", "single sign-on per workspace; people act with their own access"], ["Connections", f"read-only by default; {t['write_scoped']} with write scope, each write approved by a named person"],
                ["Secrets", "kept by name in the secrets store, never in code or documents"], ["Tenancy", "each workspace in its own schema and folders"]]
    cx.put(ctx, "security", {"rows": security, "write_scoped": t["write_scoped"]})
    return {"summary": f"The target architecture: {', '.join(r['layer'] + ' — ' + r['component'] for r in recs)}. Correct a component, add notes, then confirm the design.",
            "counts": {"components": len(recs), "systems today": len(t["systems"])}, "records": recs,
            "data": {"columns": ["Layer", "Component", "Why", "Notes"], "rows": [[r["layer"], r["component"], r["why"], r.get("notes") or ""] for r in recs] + [[k, v, "security design", ""] for k, v in security]}}


def _design_validate(recs: list[dict], ctx: wb.Ctx) -> list[str]:
    probs = [f"{r['layer']}: name the component." for r in recs if not str(r.get("component") or "").strip()]
    from .delivery import _text_problems
    return probs + _text_problems(recs, ("component", "notes"))


DESIGN_EDIT = wb.Edit(columns=[wb.Column("layer", "Layer", readonly=True), wb.Column("component", "Component", required=True), wb.Column("why", "Why", readonly=True),
                               wb.Column("notes", "Notes (integration, security)", "longtext")], add=False, remove=False, validate=_design_validate, label="component")


# ------------------------------------------------------------------ Approve: the decision records

def approve(ctx: wb.Ctx) -> dict:
    comps = {r["layer"]: r for r in ctx.records("design")}
    needs_ = [r["need"] for r in ctx.records("needs")][:3]
    fresh = []
    for ch in _chosen(ctx):
        comp = comps.get(ch["area"]) or {}
        alts = "; ".join(f"{o['option']} ({cx.num(o.get('total'))} of 20)" for o in ch["others"]) or "none short-listed"
        fresh.append({"id": f"adr-{cx.slug(ch['area'])}", "title": f"Use {comp.get('component') or ch['chosen']['option']} for {ch['area'].lower()}",
                      "context": "; ".join(needs_) or "the requirements of this engagement", "decision": f"{comp.get('component') or ch['chosen']['option']}: {ch['chosen'].get('reason') or ''}"[:400],
                      "alternatives": alts, "consequences": "", "status": "proposed"})
    recs = cx.keep_edits(ctx, fresh, ("consequences", "status", "context"))
    return {"summary": f"{len(recs)} architecture decision record(s), one per area — write the consequences; the named approver approves them.",
            "counts": {"decisions": len(recs)}, "records": recs,
            "data": {"columns": ["Decision", "Alternatives", "Consequences"], "rows": [[r["title"], r["alternatives"], r.get("consequences") or ""] for r in recs]}}


def _adr_validate(recs: list[dict], ctx: wb.Ctx) -> list[str]:
    probs = [f"{r['title']}: what are the consequences?" for r in recs if not str(r.get("consequences") or "").strip()]
    from .delivery import _text_problems
    return probs + _text_problems(recs, ("consequences", "context"))


ADR_EDIT = wb.Edit(columns=[wb.Column("title", "Decision", readonly=True), wb.Column("context", "Context", "longtext"), wb.Column("alternatives", "Alternatives", readonly=True),
                            wb.Column("consequences", "Consequences", "longtext"), wb.Column("status", "Status", "select", options=(("proposed", "Proposed"), ("accepted", "Accepted")))],
                   add=False, remove=False, validate=_adr_validate, label="decision")


# ------------------------------------------------------------------ Present: the deck and the design pack

def present(ctx: wb.Ctx) -> dict:
    t = cx.read(ctx, "today") or {"systems": [], "connections": {}, "edges": 0}
    sec = cx.read(ctx, "security") or {"rows": []}
    comps = ctx.records("design")
    adrs = ctx.records("approve")
    cmp_ = ctx.records("compare")
    _totals(cmp_)
    rec = {"components": len(comps), "options": len(cmp_), "needs": len(ctx.records("needs")), "decisions": len(adrs), "systems": len(t["systems"]), "edges": t.get("edges") or 0,
           "component_rows": [[r["layer"], r["component"], r["why"], r.get("notes") or "—"] for r in comps],
           "compare_rows": [[r["area"], r["option"], *[str(int(r[c])) for c in CRITERIA], cx.num(r["total"]), (r.get("reason") or "")[:160]] for r in cmp_],
           "need_rows": [[r["kind"], r["need"], r.get("source") or "added by a person"] for r in ctx.records("needs")],
           "adr_rows": [[r["title"], r["decision"], r["alternatives"], r["consequences"], r["status"]] for r in adrs], "security_rows": sec["rows"]}
    cx.put(ctx, "architecture", rec)
    mer = _mermaid([{"layer": r["layer"], "component": r["component"]} for r in comps], t["systems"])
    A = "record:architecture"
    day = cx.iso_day(time.time())
    p1, f1 = cx.say("{n} requirements and constraints, {o} short-listed options compared on cost, security, skills and fit, and {d} decisions recorded.",
                    n=(rec["needs"], f"{A}#needs"), o=(rec["options"], f"{A}#options"), d=(rec["decisions"], f"{A}#decisions"))
    p2, f2 = cx.say("The knowledge map holds {s} systems and {e} flows today; the design starts from them.", s=(rec["systems"], f"{A}#systems"), e=(rec["edges"], f"{A}#edges"))
    diagram = {"mermaid": mer, "alt": "The target architecture: the source systems feed the integration layer, the warehouse and the BI layer; automation and AI work alongside",
               "source": f"{A}#component_rows"}
    doc = {"kind": "doc", "title": f"Design pack: {ctx.title}"[:70], "subtitle": f"Architecture & technical design · {day}", "audience": "the architecture board and the delivery team", "date": day,
           "sections": [{"title": "Summary", "blocks": [{"kind": "paragraph", "text": p1, "figures": f1}, {"kind": "paragraph", "text": p2, "figures": f2}] + nv.blocks(ctx, "In short")},
                        {"title": "Requirements and constraints", "blocks": [{"kind": "table", "table": cx.table(["Kind", "Need", "Source"], ch, f"{A}#need_rows", "What the design answers")}
                                                                             for ch in cx.chunks(rec["need_rows"])]},
                        {"title": "Options compared", "blocks": [{"kind": "table", "table": cx.table(["Area", "Option", "Cost", "Security", "Skills", "Fit", "Total"], [r[:7] for r in ch], f"{A}#compare_rows",
                                                                                                    "Scored 1 to 5 by a person, with the reasons in the decision records")} for ch in cx.chunks(rec["compare_rows"])]},
                        {"title": "Target architecture (HLD)", "blocks": [{"kind": "diagram", "diagram": diagram},
                                                                          {"kind": "table", "table": cx.table(["Layer", "Component", "Why", "Notes"], rec["component_rows"], f"{A}#component_rows", "The components of the target")}]},
                        {"title": "Security design", "blocks": [{"kind": "table", "table": cx.table(["Area", "Design"], rec["security_rows"], "record:security#rows", "From the platform's own settings")}]},
                        {"title": "Architecture decision records", "blocks": [{"kind": "table", "table": cx.table(["Decision", "Why", "Alternatives", "Consequences", "Status"], [r[:5] for r in ch], f"{A}#adr_rows",
                                                                                                                  "Approved by the named approver")} for ch in cx.chunks(rec["adr_rows"])]}]}
    slides = [{"layout": "title", "title": ctx.title[:70], "subtitle": f"Architecture · {day}"},
              {"layout": "bullets", "title": "What the design answers", "bullets": [p1, p2], "figures": f1 + f2},
              {"layout": "diagram", "title": "The target architecture", "diagram": diagram},
              {"layout": "table", "title": "The components", "table": cx.table(["Layer", "Component", "Why"], [r[:3] for r in rec["component_rows"]], f"{A}#component_rows", "Chosen with the reasons written down")},
              {"layout": "table", "title": "Options compared", "table": cx.table(["Area", "Option", "Cost", "Security", "Skills", "Fit", "Total"], [r[:7] for r in rec["compare_rows"]][:14], f"{A}#compare_rows", "Scored 1 to 5 by a person")},
              {"layout": "table", "title": "Decisions", "table": cx.table(["Decision", "Alternatives", "Status"], [[r[0], r[2], r[4]] for r in rec["adr_rows"]][:14], f"{A}#adr_rows", "Architecture decision records")},
              {"layout": "closing", "title": "Thank you", "bullets": [cx.brand_line()]}]
    deck = {"kind": "deck", "title": f"Architecture: {ctx.title}"[:70], "subtitle": f"Architecture & technical design · {day}", "audience": "the architecture board", "date": day,
            "sections": [{"title": "Architecture", "slides": slides}]}
    a = cx.deliver(ctx, "design-pack", doc, "Design pack (HLD and ADRs)")
    b = cx.deliver(ctx, "architecture-deck", deck, "Architecture deck")
    gates = [a["gate"], b["gate"], ctx.proof("sourced", label="Every figure of the deck and the design pack resolves to its record", figures=[{"label": x["text"], "value": x["value"], "source": x["source"]} for x in f1 + f2])]
    ok = a["ok"] and b["ok"] and gates[-1]["status"] == "pass"
    ctx.put("summary", {"components": rec["components"], "decisions": rec["decisions"], "when": time.time()})
    return {"summary": ("The architecture deck and the design pack pass every check — confirm them before they go out." if ok else "The deck did not pass its checks: " + "; ".join((a["problems"] + b["problems"])[:3])),
            "ok": ok, "counts": {"documents": 2}, "data": {"checks": gates}}


def _page_cards(u: dict) -> list[dict]:
    rows = db.q("SELECT id, title, status FROM wb_items WHERE module = ? ORDER BY updated DESC LIMIT 30", (MODULE,))
    vis = auth.access_map(u, [r["id"] for r in rows]) if u else {}
    out = []
    for r in rows:
        if r["id"] in vis:
            s = (wb._load(r["id"]).get("data") or {}).get("summary") or {}
            out.append([r["title"], wb.STATUS_LABEL.get(r["status"], r["status"]), s.get("components", "—"), s.get("decisions", "—"), f"#/m/{MODULE}/i/{r['id']}"])
    return [{"title": "Architectures", "columns": ["Engagement", "Status", "Components", "Decisions", "Open"], "rows": out, "empty": "No architecture engagement yet."}]


GUIDE = """# Architecture & technical design — the work item

This folder is one architecture engagement of Relay's Architecture & technical design module.

- `sources/today.json`: what runs today (connections by kind, the lineage graph's systems and flows).
- `sources/architecture.json`, `security.json`: the needs, the comparison, the components, the decisions.
- `design-pack.yaml`, `architecture-deck.yaml`: what the docs engine built (the same as `genbi doc|deck build`).
- `narrative.yaml`: what you write when asked — a few paragraphs, every number declared with its `record:` source.

Never write a number or a vendor fact the records do not hold."""


wb.register(wb.Pack(
    module=MODULE, guide=GUIDE, cards=_page_cards,
    lineage="none: a design reads the lineage graph and the platform's settings; it writes nothing back",
    platforms={"design": DESIGN},
    schemas={"need": NEEDS_EDIT.columns, "option": OPT_EDIT.columns, "score": CMP_EDIT.columns, "component": DESIGN_EDIT.columns, "decision": ADR_EDIT.columns},
    work={"engage": wb.Work(
        title="A target architecture chosen with reasons: options compared, the design, decision records, the deck and the design pack",
        needs_source=False,
        steps={
            "Needs": wb.Step(kind="deterministic", run=needs, agent="Requirements reader", edit=NEEDS_EDIT, confirm="the requirements and constraints the design answers"),
            "Options": wb.Step(kind="deterministic", run=options, agent="Architect", edit=OPT_EDIT),
            "Compare": wb.Step(kind="deterministic", run=compare, agent="Architect", edit=CMP_EDIT, confirm="each option's scores, with the reasons written down"),
            "Design": wb.Step(kind="deterministic", run=design, agent="Architect", edit=DESIGN_EDIT),
            "Approve": wb.Step(kind="deterministic", run=approve, agent="Decision recorder", edit=ADR_EDIT, approver=True, confirm="the architecture decision records, by the named approver"),
            "Present": wb.Step(kind="deterministic", run=present, view="gates", agent="Deck writer", back_to="approve", confirm_if=lambda ctx, out: out["ok"],
                               actions={"wording": nv.action(("architecture",), "Explain the target architecture for the board: what it answers, what was compared, what was decided.",
                                                             agent="Deck writer", rebuild=lambda ctx: present(ctx))})},
        fields=[wb.Field("strategy_item", "Start from a strategy", "select", options=lambda u: _done_items("strategy", u), help="A finished Strategy & roadmap: its target becomes requirements."),
                wb.Field("selection_item", "Start from a selection", "select", options=lambda u: _done_items("selection", u), help="A finished Tool & vendor selection: its requirements."),
                wb.Field("template", "Template", "select", options=cx.template_options, default="relay")])}))
