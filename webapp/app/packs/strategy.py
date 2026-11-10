"""Strategy & roadmap (registry id `strategy`) — the full engagement: what the platform finds, a maturity assessment
with its evidence, the target, the business case maths and a roadmap in waves, presented as the steering deck.

Engagement  the registry's journey: Listen → Assess → Target → Case → Roadmap → Deck (confirm points Assess,
            Roadmap and Deck; Listen, Target and Case also wait for a person, because a person writes them).
Listen      what the platform itself found (dashboards proven and published, work items by pillar, connections,
            decisions in the Validation queue, Team & agents' hours, schedules, Self-healing, integrations, watched
            data, lineage, Ask D) beside the interviews and workshops a person records (who, their role, the themes,
            where the notes are).
Assess      the maturity model: five levels (Initial, Repeatable, Defined, Managed, Optimised) on two dimensions per
            pillar (process, automation, systems, data, AI). Relay suggests level 1 where the platform shows nothing
            and 2 where it shows activity, with the counts as evidence; a person sets the score, and a score above
            what the platform shows needs its evidence (an interview, a document) — rules first.
Target      the target level per dimension and the catalogue modules that build it, with a priority.
Case        the business case: one-off costs, running costs and benefits per year, each with its source — the
            platform's own figures where it has them (Team & agents' agent hours × the hourly rate set under
            Admin › Branding; Relay's AI cost from the usage records; an Assess & estimate item's priced estimate),
            else what a person enters with where it comes from. The discount rate and the horizon are the person's
            stated assumptions; NPV, payback and the cash flows are computed here, with the formulas in the record.
Roadmap     waves from the target's gaps by priority, each with its modules, start and end month and owner.
Deck        the strategy and business-case deck (PowerPoint) and the business case and roadmap document (Word)
            through the P11 docs engine, every figure sourced; Relay can draft the wording.
"""
from __future__ import annotations

import json
import time

from .. import auth, db, home, registry, store
from .. import workbench as wb
from . import _consult as cx
from . import _narrative as nv

MODULE = "strategy"
LEVELS = {1: "Initial", 2: "Repeatable", 3: "Defined", 4: "Managed", 5: "Optimised"}
PILLAR_NAME = {p[0]: p[1] for p in registry.PILLARS}
# (pillar, dimension, evidence key in sources/discovery.json#evidence, what the evidence counts, the modules that build it)
DIMENSIONS = [
    ("process", "Documented processes", "process_items", "work items of the Process modules", ["processdocs", "brd", "raci"]),
    ("process", "Decisions with a person in the loop", "decided_90d", "decisions taken in the Validation queue in the last 90 days", ["raci", "controls"]),
    ("automation", "Scheduled and automated work", "automation", "active schedules and work items of the Automation modules", ["n8n", "rpa", "jobs", "schedule"]),
    ("automation", "Failures fixed with approval", "healing", "Self-healing cases closed and rules learned", ["heal"]),
    ("systems", "Connected systems", "connected", "connections, service-desk sources and integration sources", ["connect", "intan", "apis"]),
    ("systems", "Governed change", "changes", "AI SDLC change requests released", ["sdlc", "ship"]),
    ("data", "Trusted numbers", "trusted", "dashboards published through the review gates and live quality rule sets", ["bi", "quality", "metrics", "governance"]),
    ("data", "Watched data and lineage", "watched", "assets Data observability watches and lineage nodes", ["observe", "knowledge", "governance"]),
    ("ai", "AI in daily work", "ai_use", "Ask D questions and agent runs in the last 30 days", ["askd", "predict", "recommend"]),
    ("ai", "Governed AI", "ai_governed", "AI budgets set and decisions on agents' work in the last 30 days", ["aigov", "agents"]),
]
KINDS = (("one-off", "One-off cost"), ("running", "Running cost per year"), ("benefit", "Benefit per year"))
PRIORITY = (("high", "High"), ("medium", "Medium"), ("low", "Low"))
CODES = {"₹": "INR", "$": "USD", "€": "EUR", "£": "GBP"}


class RecordsPlatform(wb.Platform):
    label = "Relay's own records, and your notes"
    uploads = (".docx", ".pdf", ".txt", ".md", ".xlsx", ".csv")
    reads = ("what the platform holds (dashboards, work items, connections, decisions, Team & agents, usage, Self-healing, integrations, observability, lineage) "
             "and the interview notes or documents you upload — nothing is written")
    simulator = "the platform's own records, made in the tests through the modules' APIs"


RECORDS = RecordsPlatform()


def _code(cur: str) -> str:
    c = (cur or "").strip()
    return CODES.get(c, c.upper())


def _n(sql: str, args: tuple = ()) -> int:
    try:
        return int((db.one(sql, args) or {}).get("n") or 0)
    except Exception:  # noqa: BLE001 - a table of a module this workspace never used
        return 0


# ------------------------------------------------------------------ Listen: what the platform finds, and the interviews

def _ai_runs(u: dict, since: float) -> int:
    """Agent runs on a model (not the workbench's rules runs) in the projects this person may see."""
    ps = store.all_projects()
    vis = auth.access_map(u, [p["id"] for p in ps]) if u else {}
    n = 0
    for p in ps:
        if p["id"] not in vis:
            continue
        try:
            st = store.load(p["id"])
        except (KeyError, FileNotFoundError, ValueError):
            continue
        n += sum(1 for r in st.get("runs") or [] if (r.get("ended") or 0) >= since and (r.get("model") or "") != "rules")
    return n


def discovery(u: dict) -> dict:
    now = time.time()
    h = home.build(u, "30d")
    t = cx.team_value(u, "30d")
    items = cx.work_items(u, exclude=MODULE)
    by_pillar = {p[0]: 0 for p in registry.PILLARS}
    for it in items:
        pl = (registry.BY_ID.get(it["module"]) or {}).get("pl")
        if pl in by_pillar:
            by_pillar[pl] += 1
    tables = set(db.tables())
    dev = bool(u and auth.is_dev(u))
    f = {"dashboards": len(store.dashboards()) if auth.is_admin(u) else len(home._visible_projects(u)), "published": (h.get("inflight") or {}).get("by_status", {}).get("published", 0),
         "work_items": len(items), "by_pillar": by_pillar, "decided_90d": len(cx.decided_checkpoints(u, now - 90 * cx.DAY)),
         "schedules_active": _n("SELECT COUNT(*) AS n FROM schedules WHERE status = 'active'"),
         "heal_closed": _n("SELECT COUNT(*) AS n FROM heal_cases WHERE closed IS NOT NULL") if "heal_cases" in tables else 0,
         "heal_rules": _n("SELECT COUNT(*) AS n FROM heal_rules WHERE origin = 'learned'") if "heal_rules" in tables else 0,
         "connections": _n("SELECT COUNT(*) AS n FROM connections") if dev else 0, "itsm_sources": _n("SELECT COUNT(*) AS n FROM itsm_sources") if dev and "itsm_sources" in tables else 0,
         "intan_sources": _n("SELECT COUNT(*) AS n FROM intan_sources") if dev and "intan_sources" in tables else 0,
         "sdlc_released": _n("SELECT COUNT(*) AS n FROM sdlc_requests WHERE status IN ('released', 'closed')") if dev and "sdlc_requests" in tables else 0,
         "rulesets": _n("SELECT COUNT(*) AS n FROM quality_rulesets WHERE status = 'live'") if "quality_rulesets" in tables else 0,
         "observed": _n("SELECT COUNT(*) AS n FROM observe_assets WHERE enabled = 1") if dev and "observe_assets" in tables else 0,
         "lineage_nodes": _n("SELECT COUNT(*) AS n FROM lineage_nodes") if dev and "lineage_nodes" in tables else 0,
         "questions_30d": (h.get("kpis") or {}).get("questions", 0), "agent_runs_30d": _ai_runs(u, now - 30 * cx.DAY),
         "quotas": _n("SELECT COUNT(*) AS n FROM quotas"), "team": t, "home": {k: (h.get("kpis") or {}).get(k) or 0 for k in ("agent_hours", "delivered", "runs", "questions", "ai_cost_usd")}}
    f["evidence"] = {"process_items": by_pillar.get("process", 0), "decided_90d": f["decided_90d"], "automation": f["schedules_active"] + by_pillar.get("automation", 0),
                     "healing": f["heal_closed"] + f["heal_rules"], "connected": f["connections"] + f["itsm_sources"] + f["intan_sources"], "changes": f["sdlc_released"],
                     "trusted": f["published"] + f["rulesets"], "watched": f["observed"] + f["lineage_nodes"], "ai_use": f["questions_30d"] + f["agent_runs_30d"],
                     "ai_governed": f["quotas"] + (t.get("decided") or 0)}
    f["read"] = now
    return f


def listen(ctx: wb.Ctx) -> dict:
    u = cx.owner_user(ctx)
    cx.need(bool(u), "The owner is not an active person in this workspace any more.")
    f = discovery(u)
    cx.put(ctx, "discovery", f)
    ctx.put("discovery", {k: v for k, v in f.items() if k != "team"})
    have = ctx.records(ctx.step_id)
    recs = have or [{"id": "i-1", "who": "", "role": "", "themes": "", "where": "", "origin": "person"}]
    facts = [["Dashboards", f["dashboards"]], ["Published through the review gates", f["published"]], ["Work items of every module", f["work_items"]],
             ["Decisions in the Validation queue, 90 days", f["decided_90d"]], ["Agent hours, 30 days", (f["team"] or {}).get("agent_hours", 0)],
             ["Active schedules", f["schedules_active"]], ["Connections", f["connections"]], ["Integration sources", f["intan_sources"]],
             ["Watched data assets", f["observed"]], ["Ask D questions, 30 days", f["questions_30d"]]]
    return {"summary": f"What Relay finds: {f['dashboards']} dashboard(s), {f['work_items']} work item(s), {f['decided_90d']} decision(s) in 90 days. "
                       "Record who you listened to and what they said — the assessment weighs both.",
            "counts": {"dashboards": f["dashboards"], "work items": f["work_items"], "interviews": sum(1 for r in recs if str(r.get("who") or "").strip())}, "records": recs,
            "data": {"columns": ["What Relay found", "Count"], "rows": facts}}


def _listen_validate(recs: list[dict], ctx: wb.Ctx) -> list[str]:
    real = [r for r in recs if str(r.get("who") or "").strip()]
    probs = [] if real else ["Record at least one interview or workshop: who, and what they said."]
    probs += [f"{r['who']}: what did they say?" for r in real if not str(r.get("themes") or "").strip()]
    return probs + _text(recs, ("who", "role", "themes", "where"))


def _text(recs: list[dict], keys: tuple) -> list[str]:
    from .delivery import _text_problems
    return _text_problems(recs, keys)


LISTEN_EDIT = wb.Edit(columns=[wb.Column("who", "Who", required=False), wb.Column("role", "Their role"), wb.Column("themes", "What they said", "longtext"),
                               wb.Column("where", "Where the notes are", help="A file you uploaded, a meeting, a document's name.")], validate=_listen_validate, label="interview")


# ------------------------------------------------------------------ Assess: the maturity model

def assess(ctx: wb.Ctx) -> dict:
    f = cx.read(ctx, "discovery") or {}
    ev = f.get("evidence") or {}
    fresh = []
    for pl, dim, key, what, _mods in DIMENSIONS:
        n = int(ev.get(key) or 0)
        sug = 1 if n == 0 else 2
        fresh.append({"id": cx.slug(f"{pl}-{dim}"), "pillar": PILLAR_NAME[pl], "pillar_id": pl, "dimension": dim, "evidence": f"{n} {what}", "evidence_n": n, "evidence_key": key,
                      "suggested": sug, "score": sug, "note": ""})
    recs = cx.keep_edits(ctx, fresh, ("score", "note"))
    for r in recs:
        f2 = next((x for x in fresh if x["id"] == r["id"]), None)
        if f2:
            r.update(evidence=f2["evidence"], evidence_n=f2["evidence_n"], suggested=f2["suggested"])
    return {"summary": "Maturity on ten dimensions: Relay suggests 1 where the platform shows nothing and 2 where it shows activity — set each score; "
                       "a score above what the platform shows needs its evidence.",
            "counts": {"dimensions": len(recs), "with activity": sum(1 for r in recs if r["evidence_n"])}, "records": recs,
            "items": [f"{r['pillar']} · {r['dimension']}: {r['evidence']}" for r in recs][:8],
            "data": {"columns": ["Pillar", "Dimension", "Evidence on the platform", "Suggested", "Score"], "rows": [[r["pillar"], r["dimension"], r["evidence"], r["suggested"], r["score"]] for r in recs]}}


def _score(v) -> int | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return int(f) if f.is_integer() and 1 <= f <= 5 else None


def _assess_validate(recs: list[dict], ctx: wb.Ctx) -> list[str]:
    probs = []
    for r in recs:
        s = _score(r.get("score"))
        if s is None:
            probs.append(f"{r['dimension']}: the score is a whole number from 1 to 5.")
        elif s > int(r.get("suggested") or 1) and not str(r.get("note") or "").strip():
            probs.append(f"{r['dimension']}: a score of {s} is above what the platform shows — say where the evidence is (an interview, a document).")
    return probs + _text(recs, ("note",))


ASSESS_EDIT = wb.Edit(columns=[wb.Column("pillar", "Pillar", readonly=True), wb.Column("dimension", "Dimension", readonly=True), wb.Column("evidence", "Evidence on the platform", readonly=True),
                               wb.Column("suggested", "Suggested", "number", readonly=True), wb.Column("score", "Score (1–5)", "number", required=True),
                               wb.Column("note", "Evidence for the score", "longtext", help="Needed when the score is above what the platform shows.")],
                      add=False, remove=False, validate=_assess_validate, label="dimension")


def _put_maturity(ctx: wb.Ctx) -> dict:
    dims = []
    for r in ctx.records("assess"):
        dims.append({"pillar": r["pillar"], "pillar_id": r["pillar_id"], "dimension": r["dimension"], "score": _score(r["score"]) or 1, "level": LEVELS[_score(r["score"]) or 1],
                     "evidence": r["evidence"], "evidence_n": r["evidence_n"], "note": r.get("note") or ""})
    tgt = {r["id"]: r for r in ctx.records("target")}
    for d, r in zip(dims, ctx.records("assess")):
        t = tgt.get(r["id"])
        if t:
            d.update(target=_score(t.get("target")) or d["score"], priority=t.get("priority") or "medium", modules=t.get("modules") or "")
    pillars = []
    for pid, name in PILLAR_NAME.items():
        ds = [d for d in dims if d["pillar_id"] == pid]
        if ds:
            pillars.append({"pillar": name, "current": round(sum(d["score"] for d in ds) / len(ds), 1),
                            "target": round(sum(d.get("target", d["score"]) for d in ds) / len(ds), 1)})
    step = next((s for s in ctx.st["steps"] if s["id"] == "assess"), {})
    rec = {"dimensions": dims, "pillars": pillars, "levels": LEVELS, "average": round(sum(d["score"] for d in dims) / len(dims), 1) if dims else 0,
           "confirmed_by": cx.names().get(step.get("decided_by"), step.get("decided_by")), "confirmed": step.get("decided"),
           "rows": [[d["pillar"], d["dimension"], f"{d['score']} {d['level']}", d["evidence"], d["note"] or "—"] for d in dims],
           "gap_rows": [[d["pillar"], d["dimension"], d["score"], d.get("target", d["score"]), d.get("priority", ""), d.get("modules", "")] for d in dims if d.get("target", d["score"]) > d["score"]]}
    cx.put(ctx, "maturity", rec)
    return rec


# ------------------------------------------------------------------ Target

def target(ctx: wb.Ctx) -> dict:
    _put_maturity(ctx)
    fresh = []
    for (pl, dim, _k, _w, mods), r in zip(DIMENSIONS, ctx.records("assess")):
        s = _score(r["score"]) or 1
        names = ", ".join(registry.BY_ID[m]["short"] for m in mods if m in registry.BY_ID)
        fresh.append({"id": r["id"], "pillar": r["pillar"], "dimension": dim, "current": s, "target": min(5, s + 1), "priority": "medium", "modules": names, "module_ids": mods})
    recs = cx.keep_edits(ctx, fresh, ("target", "priority", "modules"))
    for r in recs:
        f = next((x for x in fresh if x["id"] == r["id"]), None)
        if f:
            r["current"] = f["current"]
    return {"summary": "The target level per dimension and the modules that build it — Relay starts one level above today; you set where the business needs to be.",
            "counts": {"dimensions": len(recs), "gaps": sum(1 for r in recs if (_score(r["target"]) or 0) > r["current"])}, "records": recs,
            "data": {"columns": ["Pillar", "Dimension", "Today", "Target", "Priority", "Modules"], "rows": [[r["pillar"], r["dimension"], r["current"], r["target"], r["priority"], r["modules"]] for r in recs]}}


def _target_validate(recs: list[dict], ctx: wb.Ctx) -> list[str]:
    probs = []
    for r in recs:
        t = _score(r.get("target"))
        if t is None:
            probs.append(f"{r['dimension']}: the target is a whole number from 1 to 5.")
        elif t < int(r.get("current") or 1):
            probs.append(f"{r['dimension']}: the target is below today's level.")
    return probs + _text(recs, ("modules",))


TARGET_EDIT = wb.Edit(columns=[wb.Column("pillar", "Pillar", readonly=True), wb.Column("dimension", "Dimension", readonly=True), wb.Column("current", "Today", "number", readonly=True),
                               wb.Column("target", "Target (1–5)", "number", required=True), wb.Column("priority", "Priority", "select", options=PRIORITY),
                               wb.Column("modules", "What builds it")], add=False, remove=False, validate=_target_validate, label="dimension")


# ------------------------------------------------------------------ Case: the business case maths

def _estimates(u: dict) -> list[tuple[str, str]]:
    rows = db.q("SELECT id, title FROM wb_items WHERE module = 'assess' AND status IN ('done', 'scheduled') ORDER BY updated DESC LIMIT 40")
    vis = auth.access_map(u, [r["id"] for r in rows]) if u else {}
    return [("", "None")] + [(r["id"], r["title"]) for r in rows if r["id"] in vis]


def case(ctx: wb.Ctx) -> dict:
    _put_maturity(ctx)
    f = cx.read(ctx, "discovery") or {}
    b = registry.brand()
    cur = _code(b.get("currency") or "")
    rate = float(b.get("hourly_rate") or 0)
    try:
        fx = float(json.loads(db.meta("branding") or "{}").get("usd_rate") or 1)
    except (ValueError, TypeError):
        fx = 1.0
    team = f.get("team") or {}
    platform = {"currency": cur, "hourly_rate": rate, "usd_rate": fx, "agent_hours_30d": team.get("agent_hours", 0), "ai_cost_usd_30d": f.get("home", {}).get("ai_cost_usd", 0),
                "benefit_hours_year": round((team.get("agent_hours") or 0) * 12 * rate, 2), "ai_cost_year": round((f.get("home", {}).get("ai_cost_usd") or 0) * 12 * fx, 2)}
    fresh = []
    if rate:
        fresh.append({"id": "benefit-agent-hours", "kind": "benefit", "item": "Hours moved from people to agents", "amount": platform["benefit_hours_year"], "from_year": 1,
                      "source": "record:platform#benefit_hours_year", "how": f"Team & agents: {cx.num(platform['agent_hours_30d'])} agent hours in the last 30 days × 12 × the hourly rate {cx.num(rate)}",
                      "origin": "relay"})
    else:
        fresh.append({"id": "benefit-agent-hours", "kind": "benefit", "item": "Hours moved from people to agents", "amount": None, "from_year": 1, "source": "",
                      "how": "No hourly rate is set under Admin › Branding: enter the amount and where it comes from", "origin": "relay"})
    fresh.append({"id": "cost-relay-ai", "kind": "running", "item": "Relay's AI cost", "amount": platform["ai_cost_year"], "from_year": 1, "source": "record:platform#ai_cost_year",
                  "how": f"usage records: {cx.num(platform['ai_cost_usd_30d'], 2)} USD in the last 30 days × 12 × {cx.num(fx, 2)} {cur} per USD", "origin": "relay"})
    est_id = ctx.scope.get("estimate_item") or ""
    if est_id:
        try:
            est = json.loads((store.root() / est_id / "sources" / "estimate.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            est = None
        if est and est.get("priced") and _code(est.get("currency")) == cur:
            platform["estimate"] = {"item": est_id, "cost": est["totals"]["cost"], "currency": est["currency"], "hours": est["totals"]["hours_with_contingency"]}
            fresh.append({"id": "cost-estimate", "kind": "one-off", "item": "Delivering the roadmap (the Assess & estimate item)", "amount": est["totals"]["cost"], "from_year": 0,
                          "source": "record:platform#estimate.cost", "how": f"the priced estimate of {est_id}", "origin": "relay"})
        elif est:
            fresh.append({"id": "cost-estimate", "kind": "one-off", "item": "Delivering the roadmap (the Assess & estimate item)", "amount": None, "from_year": 0, "source": "",
                          "how": f"{est_id} is " + ("not priced" if not est.get("priced") else f"in {est.get('currency')}, the case is in {cur}") + ": enter the amount and its source", "origin": "relay"})
    cx.put(ctx, "platform", platform)
    recs = cx.keep_edits(ctx, fresh, ("amount", "from_year", "source", "item", "kind"))
    for r in recs:
        if r.get("origin") == "relay":
            f2 = next((x for x in fresh if x["id"] == r["id"]), None)
            if f2 and str(f2.get("source") or "").startswith("record:") and r.get("source") == f2["source"]:
                r["amount"] = f2["amount"]            # a platform figure is always today's value
    return {"summary": f"The business case in {cur or 'the workspace currency'}: Relay's own figures where it has them; add every other cost and benefit with where it comes from. "
                       f"Discount rate {cx.num(float(ctx.scope.get('discount_rate_pct') or 0))} %, horizon {cx.num(float(ctx.scope.get('horizon_years') or 0))} years (your assumptions).",
            "counts": {"lines": len(recs), "need an amount": sum(1 for r in recs if r.get("amount") in (None, ""))}, "records": recs,
            "data": {"columns": ["Kind", "Item", "Amount", "From year", "Source", "How"], "rows": [[dict(KINDS).get(r["kind"], r["kind"]), r["item"], r.get("amount"), r.get("from_year"), r.get("source") or "—", r.get("how") or ""] for r in recs]}}


def _case_validate(recs: list[dict], ctx: wb.Ctx) -> list[str]:
    probs = []
    try:
        h = int(float(ctx.scope.get("horizon_years")))
    except (TypeError, ValueError):
        h = 0
    try:
        float(ctx.scope.get("discount_rate_pct"))
    except (TypeError, ValueError):
        probs.append("State the discount rate (per cent) in the wizard.")
    if not 1 <= h <= 10:
        probs.append("The horizon is 1 to 10 years (the wizard).")
    for r in recs:
        try:
            a = float(r.get("amount"))
        except (TypeError, ValueError):
            a = None
        if a is None or a < 0:
            probs.append(f"{r.get('item') or 'A line'}: the amount is needed (zero or more).")
        if not str(r.get("source") or "").strip():
            probs.append(f"{r.get('item') or 'A line'}: where does the figure come from? A number without a source is not a business case.")
        fy = r.get("from_year")
        try:
            fy = int(float(fy))
        except (TypeError, ValueError):
            fy = None
        if r.get("kind") == "one-off" and fy not in (0, *range(1, h + 1)):
            probs.append(f"{r.get('item')}: a one-off cost falls in year 0 to {h}.")
        if r.get("kind") in ("running", "benefit") and fy not in range(1, h + 1):
            probs.append(f"{r.get('item')}: it starts in year 1 to {h}.")
    return probs + _text(recs, ("item", "source"))


CASE_EDIT = wb.Edit(columns=[wb.Column("kind", "Kind", "select", options=KINDS, required=True), wb.Column("item", "Item", required=True),
                             wb.Column("amount", "Amount", "number", help="One-off: the whole amount. Running costs and benefits: per year."),
                             wb.Column("from_year", "From year", "number", help="Year 0 is now; running costs and benefits start in year 1 or later."),
                             wb.Column("source", "Where it comes from", help="A Relay record (filled in for you), a document you uploaded, or who stated it."),
                             wb.Column("how", "How Relay computed it", readonly=True)], validate=_case_validate, label="line")


def business_case(ctx: wb.Ctx) -> dict:
    """NPV, payback and the cash flows of the confirmed lines (formulas in the record)."""
    r = float(ctx.scope.get("discount_rate_pct") or 0) / 100
    h = int(float(ctx.scope.get("horizon_years") or 0))
    platform = cx.read(ctx, "platform") or {}
    lines = [dict(x) for x in ctx.records("case")]
    years = []
    cum = 0.0
    payback = None
    for t in range(0, h + 1):
        costs = sum(float(x["amount"]) for x in lines if x["kind"] == "one-off" and int(float(x["from_year"])) == t)
        costs += sum(float(x["amount"]) for x in lines if x["kind"] == "running" and t >= 1 and t >= int(float(x["from_year"])))
        bens = sum(float(x["amount"]) for x in lines if x["kind"] == "benefit" and t >= 1 and t >= int(float(x["from_year"])))
        net = bens - costs
        disc = net / ((1 + r) ** t)
        prev = cum
        cum += net
        if payback is None and cum >= 0 and t >= 1 and net > 0:
            payback = round(((t - 1) + (-prev / net if prev < 0 else 0)) * 12, 1)
        years.append({"year": t, "costs": round(costs, 2), "benefits": round(bens, 2), "net": round(net, 2), "discounted": round(disc, 2), "cumulative": round(cum, 2)})
    npv = round(sum(y["discounted"] for y in years), 2)
    tc, tb = round(sum(y["costs"] for y in years), 2), round(sum(y["benefits"] for y in years), 2)
    rec = {"currency": platform.get("currency") or "", "discount_rate_pct": r * 100, "horizon_years": h, "years": years, "npv": npv, "npv_abs": abs(npv), "npv_negative": npv < 0,
           "payback_months": payback,
           "pays_back": payback is not None, "total_costs": tc, "total_benefits": tb, "roi_pct": round(100 * (tb - tc) / tc, 1) if tc else 0,
           "lines": [{k: x.get(k) for k in ("kind", "item", "amount", "from_year", "source", "how")} for x in lines],
           "formulas": {"net": "benefits − costs in the year", "discounted": "net ÷ (1 + discount rate)^year", "npv": "Σ discounted over years 0 to the horizon",
                        "payback": "the month the cumulative net turns positive", "roi": "(total benefits − total costs) ÷ total costs"},
           "rows": [[y["year"], cx.money(y["costs"]), cx.money(y["benefits"]), cx.money(y["net"]), cx.money(y["discounted"]), cx.money(y["cumulative"])] for y in years],
           "line_rows": [[dict(KINDS).get(x["kind"], x["kind"]), x["item"], cx.money(x["amount"]), str(int(float(x["from_year"]))), x["source"]] for x in lines]}
    cx.put(ctx, "case", rec)
    return rec


# ------------------------------------------------------------------ Roadmap

def roadmap(ctx: wb.Ctx) -> dict:
    mat = _put_maturity(ctx)
    bc = business_case(ctx)
    gaps = [d for d in mat["dimensions"] if d.get("target", d["score"]) > d["score"]]
    order = {"high": 1, "medium": 2, "low": 3}
    waves: dict = {}
    for d in gaps:
        n = order.get(d.get("priority") or "medium", 2)
        w = waves.setdefault(n, {"id": f"wave-{n}", "wave": f"Wave {n}", "dimensions": [], "modules": [], "start": "", "end": "", "owner": (cx.owner_user(ctx) or {}).get("name") or ""})
        w["dimensions"].append(d["dimension"])
        for m in [x.strip() for x in str(d.get("modules") or "").split(",") if x.strip()]:
            if m not in w["modules"]:
                w["modules"].append(m)
    fresh = [{**w, "dimensions": "; ".join(w["dimensions"]), "modules": ", ".join(w["modules"])} for _, w in sorted(waves.items())]
    recs = cx.keep_edits(ctx, fresh, ("start", "end", "owner", "modules"))
    pay = f"pays back in {cx.num(bc['payback_months'])} months" if bc["pays_back"] else f"does not pay back within {bc['horizon_years']} years"
    return {"summary": f"{len(recs)} wave(s) from the gaps, by priority — give each its months and owner. The business case: NPV {cx.money(bc['npv'], bc['currency'])} at "
                       f"{cx.num(bc['discount_rate_pct'])} % over {bc['horizon_years']} years; it {pay}.",
            "counts": {"waves": len(recs), "gaps": len(gaps)}, "records": recs,
            "items": [f"{r['wave']}: {r['dimensions']}" for r in recs] + [f"NPV {cx.money(bc['npv'], bc['currency'])}; {pay}"],
            "data": {"columns": ["Wave", "Dimensions", "Modules", "Start", "End", "Owner"], "rows": [[r["wave"], r["dimensions"], r["modules"], r.get("start"), r.get("end"), r.get("owner")] for r in recs]}}


def _month(s) -> float | None:
    return cx.parse_day(f"{str(s or '').strip()}-01") if len(str(s or "").strip()) == 7 else None


def _roadmap_validate(recs: list[dict], ctx: wb.Ctx) -> list[str]:
    probs = [] if recs else ["There is no gap between today and the target: raise a target, or close the engagement."]
    for r in recs:
        a, b = _month(r.get("start")), _month(r.get("end"))
        if a is None or b is None:
            probs.append(f"{r['wave']}: start and end are months like 2027-01.")
        elif b < a:
            probs.append(f"{r['wave']}: it ends before it starts.")
        if not str(r.get("owner") or "").strip():
            probs.append(f"{r['wave']}: who owns it?")
    return probs + _text(recs, ("modules",))


ROADMAP_EDIT = wb.Edit(columns=[wb.Column("wave", "Wave", readonly=True), wb.Column("dimensions", "Dimensions", readonly=True), wb.Column("modules", "Modules"),
                                wb.Column("start", "Start (YYYY-MM)"), wb.Column("end", "End (YYYY-MM)"), wb.Column("owner", "Owner", "select", options=cx.person_options)],
                       add=False, remove=False, validate=_roadmap_validate, label="wave")


# ------------------------------------------------------------------ Deck: the steering deck and the business case document

def _put_roadmap(ctx: wb.Ctx) -> dict:
    ws = [{k: r.get(k) for k in ("wave", "dimensions", "modules", "start", "end", "owner")} for r in ctx.records("roadmap")]
    rec = {"waves": ws, "count": len(ws), "rows": [[w["wave"], w["dimensions"], w["modules"], w["start"], w["end"], w["owner"]] for w in ws]}
    cx.put(ctx, "roadmap", rec)
    return rec


def specs(ctx: wb.Ctx) -> tuple[dict, dict, list[dict]]:
    f = cx.read(ctx, "discovery") or {}
    mat, bc, rm = cx.read(ctx, "maturity") or {}, cx.read(ctx, "case") or {}, _put_roadmap(ctx)
    cur = bc.get("currency") or ""
    day = cx.iso_day(time.time())
    interviews = [r for r in ctx.records("listen") if str(r.get("who") or "").strip()]
    cx.put(ctx, "listen", {"interviews": len(interviews), "rows": [[r["who"], r.get("role") or "—", r.get("themes") or "—", r.get("where") or "—"] for r in interviews]})
    D, C, MT = "record:discovery", "record:case", "record:maturity"
    s1, f1 = cx.say("Relay found {d} dashboards ({p} published through the review gates) and {w} work items, with {q} decisions taken by a person in the last three months.",
                    d=(f.get("dashboards", 0), f"{D}#dashboards"), p=(f.get("published", 0), f"{D}#published"), w=(f.get("work_items", 0), f"{D}#work_items"), q=(f.get("decided_90d", 0), f"{D}#decided_90d"))
    s2, f2 = cx.say("We listened to {n} people; the maturity today averages {a} out of 5.", n=(len(interviews), "record:listen#interviews"), a=(mat.get("average", 0), f"{MT}#average"))
    s3, f3 = cx.say("The business case: " + ("a negative NPV" if bc.get("npv_negative") else "an NPV") + " of {npv} at a discount rate of {r} over {h} years.",
                    npv=(bc.get("npv_abs", 0), f"{C}#npv_abs", f"money:{cur}"), r=(bc.get("discount_rate_pct", 0), f"{C}#discount_rate_pct", "%"), h=(bc.get("horizon_years", 0), f"{C}#horizon_years"))
    if bc.get("pays_back"):
        s4, f4 = cx.say("It pays back in {m} " + ("month." if float(bc["payback_months"]) == 1 else "months."), m=(bc["payback_months"], f"{C}#payback_months"))
    else:
        s4, f4 = cx.say("It does not pay back within the {h} years of the horizon.", h=(bc.get("horizon_years", 0), f"{C}#horizon_years"))
    s5, f5 = cx.say("Total costs {c} and benefits {b} over the horizon.", c=(bc.get("total_costs", 0), f"{C}#total_costs", f"money:{cur}"), b=(bc.get("total_benefits", 0), f"{C}#total_benefits", f"money:{cur}"))
    dims = mat.get("dimensions") or []
    sections = [{"title": "What we found", "blocks": [{"kind": "paragraph", "text": s1, "figures": f1}, {"kind": "paragraph", "text": s2, "figures": f2}]
                 + nv.blocks(ctx, "In short")
                 + ([{"kind": "table", "table": cx.table(["Who", "Role", "What they said", "Notes"], ch, "record:listen#rows", "The interviews and workshops")} for ch in cx.chunks((cx.read(ctx, "listen") or {}).get("rows") or [])]
                    if interviews else [])},
                {"title": "Maturity today", "blocks": [{"kind": "table", "table": cx.table(["Pillar", "Dimension", "Level", "Evidence on the platform", "Evidence for the score"], ch, f"{MT}#rows",
                                                                                         "Five levels: Initial, Repeatable, Defined, Managed, Optimised")} for ch in cx.chunks(mat.get("rows") or [])]},
                {"title": "Target and gaps", "blocks": [{"kind": "table", "table": cx.table(["Pillar", "Dimension", "Today", "Target", "Priority", "What builds it"], mat.get("gap_rows") or [["—"] * 6],
                                                                                          f"{MT}#gap_rows", "Where the business needs to be, and the modules that get it there")}]},
                {"title": "Business case", "blocks": [{"kind": "paragraph", "text": s3, "figures": f3}, {"kind": "paragraph", "text": s4, "figures": f4}, {"kind": "paragraph", "text": s5, "figures": f5},
                                                      {"kind": "table", "table": cx.table(["Kind", "Item", "Amount", "From year", "Source"], bc.get("line_rows") or [["—"] * 5], f"{C}#line_rows", "Every cost and benefit, with its source")},
                                                      {"kind": "table", "table": cx.table(["Year", "Costs", "Benefits", "Net", "Discounted", "Cumulative"], bc.get("rows") or [["—"] * 6], f"{C}#rows",
                                                                                          f"Cash flows in {cur or 'the workspace currency'}: net ÷ (1 + rate)^year, summed for the NPV")}]},
                {"title": "Roadmap", "blocks": [{"kind": "table", "table": cx.table(["Wave", "Dimensions", "Modules", "Start", "End", "Owner"], rm["rows"] or [["—"] * 6], "record:roadmap#rows", "Waves Relay can then run")}]},
                {"title": "Assumptions", "blocks": [{"kind": "bullets", "bullets": [cx.say("A discount rate of {r} and a horizon of {h} years, stated by the engagement's owner.",
                                                                                            r=(bc.get("discount_rate_pct", 0), f"{C}#discount_rate_pct", "%"), h=(bc.get("horizon_years", 0), f"{C}#horizon_years"))[0],
                                                                                     "Relay's own figures are a run rate: twelve times the last thirty days.",
                                                                                     "Every other figure carries the source a person gave it."],
                                                     "figures": cx.say("{r}{h}", r=(bc.get("discount_rate_pct", 0), f"{C}#discount_rate_pct", "%"), h=(bc.get("horizon_years", 0), f"{C}#horizon_years"))[1]}]}]
    doc = {"kind": "doc", "title": f"Business case and roadmap: {ctx.title}"[:70], "subtitle": f"Strategy & roadmap · {day}", "audience": "the steering committee", "date": day, "sections": sections}
    pillars = mat.get("pillars") or []
    k1, g1 = cx.say("{d} dashboards, {w} work items, {q} decisions by a person in three months", d=(f.get("dashboards", 0), f"{D}#dashboards"), w=(f.get("work_items", 0), f"{D}#work_items"),
                    q=(f.get("decided_90d", 0), f"{D}#decided_90d"))
    k2, g2 = cx.say("{n} people interviewed; maturity averages {a} of 5", n=(len(interviews), "record:listen#interviews"), a=(mat.get("average", 0), f"{MT}#average"))
    slides = [{"layout": "title", "title": ctx.title[:70], "subtitle": f"Strategy and business case · {day}"},
              {"layout": "bullets", "title": "What we found", "bullets": [k1, k2], "figures": g1 + g2, "notes": "Read from Relay's own records; the interviews as the engagement recorded them."},
              {"layout": "chart", "title": "Maturity today and the target", "chart": {"type": "column", "categories": [p["pillar"] for p in pillars],
                                                                                     "series": [{"name": "Today", "values": [float(p["current"]) for p in pillars]}, {"name": "Target", "values": [float(p["target"]) for p in pillars]}],
                                                                                     "unit": "level (1–5)", "source": f"{MT}#pillars", "alt": "Average maturity level per pillar today and the target"}},
              {"layout": "table", "title": "Where the gaps are", "table": cx.table(["Pillar", "Dimension", "Today", "Target", "Priority", "What builds it"], (mat.get("gap_rows") or [["—"] * 6])[:14],
                                                                                    f"{MT}#gap_rows", "The gaps between today and the target")},
              {"layout": "bullets", "title": "The business case", "bullets": [s3, s4, s5], "figures": f3 + f4 + f5,
               "notes": "NPV = Σ net ÷ (1 + rate)^year; payback is the month the cumulative net turns positive."},
              {"layout": "table", "title": "Cash flows", "table": cx.table(["Year", "Costs", "Benefits", "Net", "Discounted", "Cumulative"], (bc.get("rows") or [["—"] * 6])[:14], f"{C}#rows", f"In {cur or 'the workspace currency'}")},
              {"layout": "table", "title": "Roadmap", "table": cx.table(["Wave", "Dimensions", "Modules", "Start", "End", "Owner"], (rm["rows"] or [["—"] * 6])[:14], "record:roadmap#rows", "Waves Relay can then run")}]
    nar = ctx.get("narrative") or []
    if nar:
        slides.append({"layout": "bullets", "title": "In short", "bullets": [p["text"] for p in nar], "figures": [x for p in nar for x in p.get("figures") or []]})
    slides.append({"layout": "closing", "title": "Thank you", "bullets": [cx.brand_line()]})
    deck = {"kind": "deck", "title": f"Strategy: {ctx.title}"[:70], "subtitle": f"Steering committee · {day}", "audience": "the steering committee", "date": day,
            "sections": [{"title": "Strategy", "slides": slides}]}
    figs = [{"label": x["text"], "value": x["value"], "source": x["source"]} for x in f1 + f2 + f3 + f4 + f5 + g1 + g2]
    return doc, deck, figs


def deck(ctx: wb.Ctx) -> dict:
    doc, dk, figs = specs(ctx)
    a = cx.deliver(ctx, "business-case", doc, "Business case and roadmap")
    b = cx.deliver(ctx, "strategy-deck", dk, "Strategy deck")
    gates = [a["gate"], b["gate"], ctx.proof("sourced", label="Every figure of the deck and the document resolves to its record", figures=figs)]
    ok = a["ok"] and b["ok"] and gates[-1]["status"] == "pass"
    bc = cx.read(ctx, "case") or {}
    ctx.put("summary", {"npv": bc.get("npv"), "currency": bc.get("currency"), "payback_months": bc.get("payback_months"), "when": time.time()})
    return {"summary": ("The strategy deck and the business case document pass every check — confirm them before they go to the steering committee." if ok
                        else "The deck did not pass its checks: " + "; ".join((a["problems"] + b["problems"])[:3])),
            "ok": ok, "counts": {"documents": 2, "problems": len(a["problems"]) + len(b["problems"])}, "data": {"checks": gates}}


def _page_cards(u: dict) -> list[dict]:
    rows = db.q("SELECT id, title, status FROM wb_items WHERE module = ? ORDER BY updated DESC LIMIT 30", (MODULE,))
    vis = auth.access_map(u, [r["id"] for r in rows]) if u else {}
    out = []
    for r in rows:
        if r["id"] not in vis:
            continue
        s = (wb._load(r["id"]).get("data") or {}).get("summary") or {}
        out.append([r["title"], wb.STATUS_LABEL.get(r["status"], r["status"]), cx.money(s["npv"], s.get("currency")) if s.get("npv") is not None else "—",
                    f"{cx.num(s['payback_months'])} months" if s.get("payback_months") is not None else "—", f"#/m/{MODULE}/i/{r['id']}"])
    return [{"title": "Strategies", "columns": ["Engagement", "Status", "NPV", "Payback", "Open"], "rows": out, "empty": "No strategy engagement yet."}]


GUIDE = """# Strategy & roadmap — the work item

This folder is one strategy engagement of Relay's Strategy & roadmap module.

- `sources/discovery.json`: what the platform holds (dashboards, work items by pillar, decisions, Team & agents, usage).
- `sources/maturity.json`: the confirmed maturity scores with their evidence, the targets and the gaps.
- `sources/case.json`: the business case — every line with its source, the cash flows, NPV and payback, the formulas.
- `sources/roadmap.json`: the waves. `strategy-deck.yaml`, `business-case.yaml`: what the docs engine built.
- `narrative.yaml`: what you write when asked — a few paragraphs, every number declared with its `record:` source.

Never write a number the records do not hold; never forecast."""


wb.register(wb.Pack(
    module=MODULE, guide=GUIDE, cards=_page_cards,
    lineage="none: a strategy reads the platform's records and writes nothing back",
    platforms={"relay": RECORDS},
    schemas={"interview": LISTEN_EDIT.columns, "dimension": ASSESS_EDIT.columns, "target": TARGET_EDIT.columns, "line": CASE_EDIT.columns, "wave": ROADMAP_EDIT.columns},
    work={"engage": wb.Work(
        title="A data, automation and AI strategy: maturity with its evidence, the business case maths and a roadmap",
        needs_source=False,
        steps={
            "Listen": wb.Step(kind="deterministic", run=listen, agent="Discovery reader", edit=LISTEN_EDIT, confirm="who you listened to and what they said, beside what Relay found",
                              text="What the platform itself finds — dashboards, work items, decisions, agent hours, schedules, integrations — beside the interviews and workshops you record"),
            "Assess": wb.Step(kind="deterministic", run=assess, agent="Maturity assessor", edit=ASSESS_EDIT,
                              text="Ten dimensions across the five pillars, five levels each: Relay suggests 1 or 2 from the platform's evidence; you score each, with the evidence for anything higher"),
            "Target": wb.Step(kind="deterministic", run=target, agent="Strategist", edit=TARGET_EDIT, confirm="the target level per dimension and what builds it",
                              text="Where the business needs to be on each dimension, the modules that get it there and the priority"),
            "Case": wb.Step(kind="deterministic", run=case, agent="Business case writer", edit=CASE_EDIT, confirm="every cost and benefit with its source",
                            text="Costs and benefits per year — Relay's own figures where it has them, the rest from you with their source; your discount rate and horizon"),
            "Roadmap": wb.Step(kind="deterministic", run=roadmap, agent="Roadmapper", edit=ROADMAP_EDIT,
                               text="Waves from the gaps by priority, with their modules, months and owners — and the business case: NPV, payback, cash flows"),
            "Deck": wb.Step(kind="deterministic", run=deck, view="gates", agent="Deck writer", back_to="roadmap", confirm_if=lambda ctx, out: out["ok"],
                            actions={"wording": nv.action(("discovery", "maturity", "case", "roadmap"), "Write the story for the steering committee: where we are, where we need to be, what it is worth and how we get there.",
                                                          agent="Deck writer", rebuild=lambda ctx: deck(ctx))},
                            text="The strategy deck (PowerPoint) and the business case and roadmap (Word) through the docs engine — every figure sourced and checked")},
        fields=[wb.Field("discount_rate_pct", "Discount rate (per cent)", "number", required=True, help="Your assumption for the NPV."),
                wb.Field("horizon_years", "Horizon (years)", "number", required=True, default=5, help="1 to 10 years."),
                wb.Field("estimate_item", "The delivery cost from an estimate", "select", options=_estimates, help="A finished Assess & estimate item; its priced estimate becomes the one-off cost."),
                wb.Field("template", "Template", "select", options=cx.template_options, default="relay")])}))
