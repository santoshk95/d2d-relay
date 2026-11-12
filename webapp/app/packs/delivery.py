"""Programme & delivery (registry id `delivery`) - the live Programme view, as a consulting engagement.

Engagement  Scope -> Status -> Plan -> RAID -> Report. A programme tracks records the platform already holds: work items
            of every module (the workbench), Migrate BI programmes, AI SDLC change requests, studio deliverables and RFP
            responses - only those its owner may see. Status reads each one live (journey, open decisions and how long
            they have waited, steps needing attention, proof results) with Team & agents' figures for the week; Plan
            is the waves and their milestones (owner and due date set by a person); RAID is derived from the records
            (issues: work needing attention, decisions waiting too long; risks: waves due with work still open, work
            sent back again and again; dependencies: work items started from other ones) plus what a person adds; Report
            builds the weekly status report (Word) and the steering pack (PowerPoint) through the P11 docs engine,
            every figure quoted from sources/programme.json, plan.json and raid.json.
Weekly      the `schedule` field (every week by default) re-runs the engagement from Status: Plan and RAID wait for a
            person only when something changed; the report always waits for its confirmation before it is shared.
The module page's cards are the live Programme view: every programme with its state, and every module's work in
flight across the platform (GET /api/m/delivery/programme returns the same).
"""
from __future__ import annotations

import time

from fastapi import APIRouter

from .. import auth, db, registry
from .. import workbench as wb
from . import _consult as cx
from . import _narrative as nv

MODULE = "delivery"
STATUS_RAG = {"green": "pass", "amber": "warn", "red": "fail"}
RAID_TYPES = (("Risk", "Risk"), ("Assumption", "Assumption"), ("Issue", "Issue"), ("Dependency", "Dependency"))
RAID_STATUS = (("open", "Open"), ("mitigating", "Mitigating"), ("closed", "Closed"))
RAID_KEY = {"Risk": "risks", "Assumption": "assumptions", "Issue": "issues", "Dependency": "dependencies"}


class RecordsPlatform(wb.Platform):
    label = "Relay's own records"
    reads = ("work items of every module, their checkpoints and evidence, Team & agents, Migrate BI programmes, AI SDLC change requests, "
             "studio deliverables and RFP responses - only what the programme's owner may see; nothing is written")
    simulator = "the platform's own records, made in the tests through the modules' APIs"


RECORDS = RecordsPlatform()


# ------------------------------------------------------------------ Scope

def _wanted(r: dict, mode: str, words: list[str], owner: str) -> bool:
    if mode == "mine" and r.get("owner_id") != owner and r.get("owner") != (db.user(owner) or {}).get("name"):
        return False
    hay = f"{r['title']} {r['module_name']} {r['kind']}".lower()
    return not words or any(w in hay for w in words)


def scope(ctx: wb.Ctx) -> dict:
    u = cx.owner_user(ctx)
    cx.need(bool(u), "The programme's owner is not an active person in this workspace any more.")
    recs = cx.every_record(u, exclude=MODULE)
    mode = ctx.scope.get("scope_mode") or "all"
    words = [w.strip().lower() for w in (ctx.scope.get("match") or "").splitlines() if w.strip()]
    fresh = [{"id": r["ref"], "include": _wanted(r, mode, words, ctx.owner or ""), "kind": r["kind"], "module": r["module_name"], "title": r["title"],
              "owner": r["owner"], "status": r["status_label"], "wave": "Wave 1", "link": r["link"]} for r in recs]
    rows = cx.keep_edits(ctx, fresh, ("include", "wave"))
    n_in = sum(1 for r in rows if r.get("include"))
    if not rows:
        raise wb.StepFailed("There is nothing to track yet: no work items, migrations, change requests, deliverables or RFP responses that you may see.")
    return {"summary": f"{n_in} of {len(rows)} record(s) you may see are in scope - untick what the programme does not cover and name each one's wave.",
            "counts": {"records": len(rows), "in scope": n_in, "modules": len({r['module'] for r in rows if r.get('include')})}, "records": rows,
            "items": [f"{r['module']}: {r['title']} ({r['status']})" for r in rows if r.get("include")][:8],
            "data": {"columns": ["In scope", "Wave", "Kind", "Module", "Title", "Owner", "Status"],
                     "rows": [["yes" if r.get("include") else "no", r.get("wave"), r["kind"], r["module"], r["title"], r["owner"], r["status"]] for r in rows]}}


def _scope_validate(recs: list[dict], ctx: wb.Ctx) -> list[str]:
    probs = [] if any(r.get("include") for r in recs) else ["Keep at least one record in scope."]
    probs += [f"{r['title']}: name its wave." for r in recs if r.get("include") and not str(r.get("wave") or "").strip()]
    probs += _text_problems(recs, ("wave",))
    return probs


def _text_problems(recs: list[dict], keys: tuple) -> list[str]:
    """Rules first: what a person writes here goes into a shared report, so it must pass the report's own checks."""
    import re

    from genbi_kit.docs.template import BRITISH, PLACEHOLDER_RE
    out = []
    for i, r in enumerate(recs, 1):
        for k in keys:
            t = str(r.get(k) or "")
            m = PLACEHOLDER_RE.search(t)
            if m:
                out.append(f"Row {i}: \"{m.group(0)}\" is placeholder text - write what is known, or leave it empty.")
            for w in re.findall(r"[A-Za-z]+", t):
                if w.lower() in BRITISH:
                    out.append(f"Row {i}: \"{w}\" - the house style spells it \"{BRITISH[w.lower()]}\".")
                    break
    return out


SCOPE_EDIT = wb.Edit(columns=[wb.Column("include", "In scope", "bool"), wb.Column("wave", "Wave", help="Records with the same wave name are planned and reported together."),
                              wb.Column("kind", "Kind", readonly=True), wb.Column("module", "Module", readonly=True), wb.Column("title", "Title", readonly=True),
                              wb.Column("status", "Status", readonly=True)], add=False, remove=False, validate=_scope_validate, label="record")


# ------------------------------------------------------------------ Status (facts, read live)

def _rag(r: dict, waiting_days: float, now: float) -> tuple[str, str]:
    if r.get("attention"):
        return "red", f"needs attention{(' at ' + r['step']) if r.get('step') else ''}"
    age = (now - r["waiting_since"]) / cx.DAY if r.get("waiting_since") else None
    if age is not None and age > waiting_days:
        return "red", f"a decision has waited {cx.num(age, 1)} days" + (f" for {', '.join(r.get('waiting_for') or [])}" if r.get("waiting_for") else "")
    if r.get("waiting"):
        return "amber", "waiting for a person" + (f" ({', '.join(r.get('waiting_for') or [])})" if r.get("waiting_for") else "")
    if r.get("done"):
        return "green", "done"
    return "green", "in progress" + (f" at {r['step']}" if r.get("step") else "")


def status(ctx: wb.Ctx) -> dict:
    u = cx.owner_user(ctx)
    cx.need(bool(u), "The programme's owner is not an active person in this workspace any more.")
    in_scope = [r for r in ctx.records("scope") if r.get("include")]
    live = {r["ref"]: r for r in cx.every_record(u, exclude=MODULE)}
    wd = float(ctx.scope.get("waiting_days") or 2)
    now = time.time()
    detail, gates, missing = [], [], []
    for s in in_scope:
        r = live.get(s["id"])
        if not r:
            missing.append(s["id"])
            continue
        rag, why = _rag(r, wd, now)
        age = round((now - r["waiting_since"]) / cx.DAY, 1) if r.get("waiting_since") else None
        detail.append({"ref": r["ref"], "title": r["title"], "module": r["module_name"], "kind": r["kind"], "wave": s.get("wave") or "Wave 1", "status": r["status_label"],
                       "rag": rag, "why": why, "done": bool(r.get("done")), "attention": bool(r.get("attention")), "waiting": r.get("waiting") or 0,
                       "waiting_days": age, "waiting_for": r.get("waiting_for") or [], "sent_back": r.get("sent_back") or 0, "owner": r["owner"],
                       "steps_done": r.get("steps_done"), "steps": r.get("steps"), "parent": r.get("parent"), "link": r["link"],
                       "proof_pass": r.get("proof_pass") or 0, "proof_fail": r.get("proof_fail") or 0})
        gates.append({"name": r["ref"], "label": f"{r['module_name']} - {r['title']}", "status": STATUS_RAG[rag], "measured": r["status_label"], "expected": "",
                      "detail": why + (f" - steps {r['steps_done']} of {r['steps']}" if r.get("steps") else "")})
    waves: dict = {}
    for x in detail:
        w = waves.setdefault(x["wave"], {"wave": x["wave"], "records": 0, "done": 0, "open": 0, "waiting": 0, "attention": 0, "red": 0})
        w["records"] += 1
        w["done"] += x["done"]
        w["open"] += 0 if x["done"] else 1
        w["waiting"] += 1 if x["waiting"] else 0
        w["attention"] += x["attention"]
        w["red"] += x["rag"] == "red"
    refs = {x["ref"] for x in detail}
    week = cx.decided_checkpoints(u, now - 7 * cx.DAY)
    week = [c for c in week if f"wb:{c['subject']}" in refs or f"migbi:{c['subject']}" in refs or f"sdlc:{c['subject']}" in refs
            or f"studio:{c['subject']}" in refs or f"rfp:{c['subject']}" in refs]
    acc = sum(1 for c in week if c["status"] == "accepted")
    totals = {"records": len(detail), "done": sum(x["done"] for x in detail), "open": sum(0 if x["done"] else 1 for x in detail),
              "waiting": sum(1 for x in detail if x["waiting"]), "attention": sum(x["attention"] for x in detail), "red": sum(x["rag"] == "red" for x in detail),
              "amber": sum(x["rag"] == "amber" for x in detail), "green": sum(x["rag"] == "green" for x in detail), "waves": len(waves), "missing": len(missing),
              "decided_7d": len(week), "accepted_7d": acc, "sent_back_7d": len(week) - acc, "accepted_pct_7d": cx.pct(acc, len(week)) or 0,
              "done_pct": cx.pct(sum(x["done"] for x in detail), len(detail)) or 0}
    team = cx.team_value(u, "7d")
    detail.sort(key=lambda x: (cx.natural(x["wave"]), x["module"], x["title"].lower()))
    rec = {"programme": ctx.title, "generated": now, "generated_on": cx.iso_day(now), "owner": u.get("name"), "waiting_days": wd, "totals": totals,
           "waves": sorted(waves.values(), key=lambda w: cx.natural(w["wave"])), "detail": detail, "team": team,
           "rows": [[x["wave"], x["module"], x["title"], x["status"], x["rag"], x["why"]] for x in detail]}
    src = cx.put(ctx, "programme", rec)
    nv.clear(ctx)                                    # this week's facts: last week's drafted wording no longer applies
    ctx.evidence("The programme's records, read now", {"rows": detail, "missing": missing}, kind="status", ok=not missing)
    ctx.put("summary", {"records": totals["records"], "done": totals["done"], "waiting": totals["waiting"], "attention": totals["attention"], "red": totals["red"],
                        "when": now, "waves": totals["waves"]})
    gates.append(ctx.proof("references_real", label="Every record in scope still exists and its owner may see it", refs=[s["id"] for s in in_scope], known=list(live)))
    gates.append(ctx.proof("sourced", label="Every figure of the status comes from the programme record", figures=[
        {"label": f"records in scope ({totals['records']})", "value": totals["records"], "source": f"{src}#totals.records"},
        {"label": f"done ({totals['done']})", "value": totals["done"], "source": f"{src}#totals.done"},
        {"label": f"waiting for a person ({totals['waiting']})", "value": totals["waiting"], "source": f"{src}#totals.waiting"},
        {"label": f"needs attention ({totals['attention']})", "value": totals["attention"], "source": f"{src}#totals.attention"}]))
    return {"summary": f"{totals['records']} record(s) read live: {totals['done']} done, {totals['waiting']} waiting for a person, {totals['attention']} needing attention"
                       + (f", {len(missing)} no longer visible" if missing else "") + f"; {len(week)} decision(s) this week.",
            "counts": {"records": totals["records"], "done": totals["done"], "waiting": totals["waiting"], "red": totals["red"]}, "data": {"checks": gates}}


# ------------------------------------------------------------------ Plan: waves and milestones

def _changed(ctx: wb.Ctx, fresh_ids: set[str]) -> int:
    before = {r["id"] for r in ctx.records(ctx.step_id)}
    return len(fresh_ids - before) if before else len(fresh_ids)


def plan(ctx: wb.Ctx) -> dict:
    prog = cx.read(ctx, "programme") or {}
    me = (cx.owner_user(ctx) or {}).get("name") or ""
    fresh = [{"id": cx.slug(w["wave"]), "wave": w["wave"], "records": w["records"], "done": w["done"], "open": w["open"], "owner": me, "due": "", "note": ""}
             for w in prog.get("waves") or []]
    changed = _changed(ctx, {r["id"] for r in fresh})
    recs = cx.keep_edits(ctx, fresh, ("owner", "due", "note"))
    for r in recs:                                   # the counts are always today's
        w = next((x for x in fresh if x["id"] == r["id"]), None)
        if w:
            r.update(records=w["records"], done=w["done"], open=w["open"])
    nxt = [[x["wave"], x["module"], x["title"], x["status"] if x["done"] else (x["why"])] for x in prog.get("detail") or [] if not x["done"]]
    return {"summary": f"{len(recs)} wave(s): give each one its owner and due date - the plan the weekly report tracks." + (f" {changed} new since the last plan." if changed and ctx.records(ctx.step_id) else ""),
            "counts": {"waves": len(recs), "changed": changed}, "records": recs,
            "items": [f"{r['wave']}: {r['done']} of {r['records']} done, due {r.get('due') or 'not set'}" for r in recs],
            "data": {"columns": ["Wave", "Records", "Done", "Open", "Owner", "Due"], "rows": [[r["wave"], r["records"], r["done"], r["open"], r.get("owner"), r.get("due") or "-"] for r in recs]
                     + [["(next)", "", "", "", m[1], f"{m[2]}: {m[3]}"] for m in nxt[:6]]}}


def _plan_validate(recs: list[dict], ctx: wb.Ctx) -> list[str]:
    probs = []
    for r in recs:
        if not str(r.get("owner") or "").strip():
            probs.append(f"{r['wave']}: who owns it?")
        if cx.parse_day(r.get("due") or "") is None:
            probs.append(f"{r['wave']}: the due date must look like 2026-11-30.")
    return probs + _text_problems(recs, ("note",))


PLAN_EDIT = wb.Edit(columns=[wb.Column("wave", "Wave", readonly=True), wb.Column("records", "Records", "number", readonly=True), wb.Column("done", "Done", "number", readonly=True),
                             wb.Column("owner", "Owner", "select", options=cx.person_options, required=True), wb.Column("due", "Due (YYYY-MM-DD)", help="The date the wave is due, e.g. 2026-11-30."),
                             wb.Column("note", "Note", "longtext")], add=False, remove=False, validate=_plan_validate, label="wave")


# ------------------------------------------------------------------ RAID

def raid(ctx: wb.Ctx) -> dict:
    prog = cx.read(ctx, "programme") or {}
    _put_plan(ctx)                                   # the plan as confirmed: what the RAID items and the report quote
    wd = float(prog.get("waiting_days") or ctx.scope.get("waiting_days") or 2)
    now = time.time()
    me = (cx.owner_user(ctx) or {}).get("name") or ""
    detail = prog.get("detail") or []
    by_id = {x["ref"].split(":", 1)[1]: x for x in detail}
    found = []
    for i, x in enumerate(detail):
        src = f"record:programme#detail.{i}"
        if x["attention"]:
            found.append({"id": f"issue-attention-{cx.slug(x['ref'], 60)}", "type": "Issue", "title": f"{x['module']} - {x['title']} needs attention", "source": src})
        if x.get("waiting_days") is not None and x["waiting_days"] > wd:
            found.append({"id": f"issue-waiting-{cx.slug(x['ref'], 60)}", "type": "Issue", "source": src,
                          "title": f"A decision on {x['title']} has waited {cx.num(x['waiting_days'], 1)} days" + (f" for {', '.join(x['waiting_for'])}" if x.get("waiting_for") else "")})
        if (x.get("sent_back") or 0) >= 2:
            found.append({"id": f"risk-sentback-{cx.slug(x['ref'], 60)}", "type": "Risk", "source": src, "title": f"{x['title']} was sent back {x['sent_back']} times"})
        if x.get("parent"):
            p = by_id.get(x["parent"])
            found.append({"id": f"dep-{cx.slug(x['ref'], 60)}", "type": "Dependency", "source": src,
                          "title": f"{x['title']} was started from {p['title'] if p else 'work outside this programme'} ({p['status'] if p else x['parent']})"})
    for i, w in enumerate(ctx.records("plan")):
        due = cx.parse_day(w.get("due") or "")
        if due is None or not w.get("open"):
            continue
        src = f"record:plan#waves.{i}"
        if due < now:
            found.append({"id": f"issue-late-{w['id']}", "type": "Issue", "source": src, "title": f"{w['wave']} is past its due date ({w['due']}) with {w['open']} record(s) open"})
        elif due - now <= 7 * cx.DAY:
            found.append({"id": f"risk-due-{w['id']}", "type": "Risk", "source": src, "title": f"{w['wave']} is due on {w['due']} with {w['open']} record(s) still open"})
    for f in found:
        f.update(owner=me, status="open", mitigation="", origin="relay")
    have = {r["id"]: r for r in ctx.records(ctx.step_id)}
    changed = len({f["id"] for f in found} - set(have)) if have else len(found)
    recs = cx.keep_edits(ctx, found, ("owner", "status", "mitigation"))
    for rid, r in have.items():                      # a derived item that is no longer seen is closed, not dropped
        if r.get("origin") == "relay" and rid not in {f["id"] for f in found}:
            recs.append({**r, "status": "closed", "mitigation": (r.get("mitigation") or "") or f"No longer seen on {cx.iso_day(now)}."})
    counts = {t: sum(1 for r in recs if r["type"] == t and r.get("status") != "closed") for t, _ in RAID_TYPES}
    return {"summary": f"{counts['Issue']} issue(s), {counts['Risk']} risk(s), {counts['Dependency']} dependenc{'y' if counts['Dependency'] == 1 else 'ies'} from the records"
                       + (f", {counts['Assumption']} assumption(s)" if counts["Assumption"] else "") + " - add what the records cannot know, give each an owner and a mitigation.",
            "counts": {**{RAID_KEY[k]: v for k, v in counts.items()}, "changed": changed}, "records": recs,
            "items": [f"{r['type']}: {r['title']}" for r in recs if r.get("status") != "closed"][:8],
            "data": {"columns": ["Type", "What", "Owner", "Status", "Mitigation", "Source"], "rows": [[r["type"], r["title"], r.get("owner"), r.get("status"), r.get("mitigation") or "", r.get("source") or "added by a person"] for r in recs]}}


def _raid_validate(recs: list[dict], ctx: wb.Ctx) -> list[str]:
    probs = [f"Row {i}: say what it is." for i, r in enumerate(recs, 1) if not str(r.get("title") or "").strip()]
    probs += [f"{r['title']}: an open {r['type'].lower()} needs an owner." for r in recs if r.get("status") != "closed" and r.get("type") in ("Risk", "Issue") and not str(r.get("owner") or "").strip()]
    return probs + _text_problems(recs, ("title", "mitigation"))


RAID_EDIT = wb.Edit(columns=[wb.Column("type", "Type", "select", options=RAID_TYPES, required=True), wb.Column("title", "What", required=True),
                             wb.Column("owner", "Owner", "select", options=cx.person_options), wb.Column("status", "Status", "select", options=RAID_STATUS),
                             wb.Column("mitigation", "Mitigation or next step", "longtext"), wb.Column("source", "Source", readonly=True)],
                    validate=_raid_validate, label="RAID item")


# ------------------------------------------------------------------ Report: the weekly status report and the steering pack

def _put_plan(ctx: wb.Ctx) -> dict:
    waves = [{"wave": w["wave"], "records": w.get("records") or 0, "done": w.get("done") or 0, "open": w.get("open") or 0, "owner": w.get("owner"), "due": w.get("due")}
             for w in ctx.records("plan")]
    step = next((s for s in ctx.st["steps"] if s["id"] == "plan"), {})
    rec = {"waves": waves, "count": len(waves), "confirmed_by": cx.names().get(step.get("decided_by"), step.get("decided_by")), "confirmed": step.get("decided"),
           "rows": [[w["wave"], w["records"], w["done"], w["open"], w["owner"], w["due"]] for w in waves]}
    cx.put(ctx, "plan", rec)
    return rec


def _records_for_report(ctx: wb.Ctx) -> tuple[dict, dict, dict]:
    prog = cx.read(ctx, "programme") or {}
    plan_rec = _put_plan(ctx)
    items = [r for r in ctx.records("raid")]
    open_ = [r for r in items if r.get("status") != "closed"]
    raid_rec = {"counts": {RAID_KEY[t]: sum(1 for r in open_ if r["type"] == t) for t, _ in RAID_TYPES}, "open": len(open_), "closed": len(items) - len(open_),
                "rows": [[r["type"], r["title"], r.get("owner") or "-", r.get("status"), r.get("mitigation") or "-"] for r in open_]}
    cx.put(ctx, "raid", raid_rec)
    return prog, plan_rec, raid_rec


def report_specs(ctx: wb.Ctx) -> tuple[dict, dict, list[dict]]:
    prog, plan_rec, raid_rec = _records_for_report(ctx)
    t = prog.get("totals") or {}
    team = prog.get("team") or {}
    day = prog.get("generated_on") or cx.iso_day(time.time())
    P = "record:programme"
    lead, f1 = cx.say("{n} records are in scope: {d} done, {w} waiting for a person and {a} needing attention.",
                      n=(t.get("records", 0), f"{P}#totals.records"), d=(t.get("done", 0), f"{P}#totals.done"), w=(t.get("waiting", 0), f"{P}#totals.waiting"),
                      a=(t.get("attention", 0), f"{P}#totals.attention"))
    wk, f2 = cx.say("This week {k} decisions were taken on them, {acc} accepted first time.", k=(t.get("decided_7d", 0), f"{P}#totals.decided_7d"),
                    acc=(t.get("accepted_7d", 0), f"{P}#totals.accepted_7d"))
    rd, f3 = cx.say("The RAID log holds {i} open issues, {r} risks and {dp} dependencies.", i=(raid_rec["counts"]["issues"], "record:raid#counts.issues"),
                    r=(raid_rec["counts"]["risks"], "record:raid#counts.risks"), dp=(raid_rec["counts"]["dependencies"], "record:raid#counts.dependencies"))
    ag, f4 = cx.say("Team & agents: agents worked {h} hours and people spent {p} hours deciding in the last seven days.",
                    h=(team.get("agent_hours", 0), f"{P}#team.agent_hours"), p=(team.get("people_hours", 0), f"{P}#team.people_hours")) if team else ("", [])
    doc_blocks = [{"kind": "paragraph", "text": lead, "figures": f1}, {"kind": "paragraph", "text": wk, "figures": f2}, {"kind": "paragraph", "text": rd, "figures": f3}]
    if ag:
        doc_blocks.append({"kind": "paragraph", "text": ag, "figures": f4})
    doc_blocks += nv.blocks(ctx, "This week in short")
    sections = [{"title": "Where the programme stands", "blocks": doc_blocks},
                {"title": "Waves and milestones", "blocks": [{"kind": "table", "table": cx.table(["Wave", "Records", "Done", "Open", "Owner", "Due"], plan_rec["rows"] or [["-"] * 6],
                                                                                              "record:plan#rows", "The plan as confirmed, with today's counts")}]},
                {"title": "Status by record", "blocks": [{"kind": "table", "table": cx.table(["Wave", "Module", "Record", "Status", "RAG", "Why"], ch or [["-"] * 6], f"{P}#rows",
                                                                                          f"Read from Relay's records on {day}")} for ch in cx.chunks(prog.get("rows") or [])]},
                {"title": "Risks, assumptions, issues and dependencies", "blocks": [{"kind": "table", "table": cx.table(["Type", "What", "Owner", "Status", "Mitigation"], ch or [["-"] * 5],
                                                                                                                        "record:raid#rows", "Open items of the RAID log")} for ch in cx.chunks(raid_rec["rows"])]},
                {"title": "How this report was made", "blocks": [{"kind": "paragraph", "text": f"Every figure in this report comes from Relay's own records, read on {day}: work items, "
                                                                                             "their checkpoints and evidence, Team & agents and the plan and RAID log a named person confirmed. "
                                                                                             "Nothing in it was estimated."}]}]
    doc = {"kind": "doc", "title": f"Status report: {ctx.title}"[:70], "subtitle": f"Week of {day}", "audience": "the programme's steering group", "date": day, "sections": sections}
    kp, k1 = cx.say("{n} records in scope, {d} done ({pc})", n=(t.get("records", 0), f"{P}#totals.records"), d=(t.get("done", 0), f"{P}#totals.done"),
                    pc=(t.get("done_pct") or 0, f"{P}#totals.done_pct", "%"))
    kw, k2 = cx.say("{w} waiting for a person, {a} needing attention", w=(t.get("waiting", 0), f"{P}#totals.waiting"), a=(t.get("attention", 0), f"{P}#totals.attention"))
    kr, k3 = cx.say("RAID log: open issues {i}, open risks {r}", i=(raid_rec["counts"]["issues"], "record:raid#counts.issues"), r=(raid_rec["counts"]["risks"], "record:raid#counts.risks"))
    slides = [{"layout": "title", "title": ctx.title[:70], "subtitle": f"Steering pack - week of {day}"},
              {"layout": "bullets", "title": "Where we are", "bullets": [kp, kw, kr], "figures": k1 + k2 + k3,
               "notes": "Read live from Relay's records; the plan and the RAID log were confirmed by a named person."}]
    if plan_rec["rows"]:
        slides.append({"layout": "chart", "title": "Done and open, wave by wave", "chart": {"type": "column", "categories": [w["wave"] for w in plan_rec["waves"]],
                       "series": [{"name": "Done", "values": [int(w["done"] or 0) for w in plan_rec["waves"]]}, {"name": "Open", "values": [int(w["open"] or 0) for w in plan_rec["waves"]]}],
                       "unit": "records", "source": "record:plan#waves", "alt": "Done and open records in each wave of the plan"}})
        slides.append({"layout": "table", "title": "Waves and milestones", "table": cx.table(["Wave", "Records", "Done", "Open", "Owner", "Due"], plan_rec["rows"][:14], "record:plan#rows", "The confirmed plan")})
    if raid_rec["rows"]:
        slides.append({"layout": "table", "title": "What needs the steering group", "table": cx.table(["Type", "What", "Owner", "Status", "Mitigation"], raid_rec["rows"][:14], "record:raid#rows", "Open RAID items")})
    nar = ctx.get("narrative") or []
    if nar:
        slides.append({"layout": "bullets", "title": "This week in short", "bullets": [p["text"] for p in nar], "figures": [f for p in nar for f in p.get("figures") or []]})
    slides.append({"layout": "closing", "title": "Thank you", "bullets": [cx.brand_line()]})
    deck = {"kind": "deck", "title": f"Steering pack: {ctx.title}"[:70], "subtitle": f"Week of {day}", "audience": "the programme's steering group", "date": day,
            "sections": [{"title": "Steering", "slides": slides}]}
    figs = [{"label": f["text"], "value": f["value"], "source": f["source"]} for f in f1 + f2 + f3 + f4 + k1 + k2 + k3]
    return doc, deck, figs


def report(ctx: wb.Ctx) -> dict:
    doc, deck, figs = report_specs(ctx)
    a = cx.deliver(ctx, "status-report", doc, "Weekly status report")
    b = cx.deliver(ctx, "steering-pack", deck, "Steering pack")
    gates = [a["gate"], b["gate"], ctx.proof("sourced", label="Every figure of the report resolves to its record", figures=figs)]
    ok = a["ok"] and b["ok"] and gates[-1]["status"] == "pass"
    ctx.put("last_report", time.time())
    return {"summary": ("The weekly status report (Word) and the steering pack (PowerPoint) are built and pass every check - confirm them before they are shared."
                        if ok else "The report did not pass its checks: " + "; ".join((a["problems"] + b["problems"])[:3])),
            "ok": ok, "counts": {"documents": 2, "problems": len(a["problems"]) + len(b["problems"])}, "data": {"checks": gates},
            "items": [f"{g['label']}: {g['status']}" for g in gates]}


# ------------------------------------------------------------------ the live Programme view (module page cards, API)

def live_view(u: dict) -> dict:
    recs = cx.every_record(u, exclude=MODULE)
    mods: dict = {}
    for r in recs:
        m = mods.setdefault(r["module"], {"module": r["module"], "name": r["module_name"], "records": 0, "open": 0, "waiting": 0, "attention": 0, "done": 0,
                                          "route": (registry.BY_ID.get(r["module"]) or {}).get("route") or r["link"]})
        m["records"] += 1
        m["done"] += 1 if r["done"] else 0
        m["open"] += 0 if r["done"] else 1
        m["waiting"] += 1 if r.get("waiting") else 0
        m["attention"] += 1 if r.get("attention") else 0
    progs = []
    rows = db.q("SELECT id, title, status, updated FROM wb_items WHERE module = ? AND closed IS NULL ORDER BY updated DESC", (MODULE,))
    vis = auth.access_map(u, [r["id"] for r in rows]) if u else {}
    for r in rows:
        if r["id"] not in vis:
            continue
        try:
            s = (wb._load(r["id"]).get("data") or {}).get("summary") or {}
        except (KeyError, FileNotFoundError, ValueError):
            continue
        progs.append({"id": r["id"], "title": r["title"], "status": wb.STATUS_LABEL.get(r["status"], r["status"]), "records": s.get("records"), "done": s.get("done"),
                      "waiting": s.get("waiting"), "attention": s.get("attention"), "read": cx.when(s.get("when"), "%d %b %H:%M") if s.get("when") else "-", "route": f"#/m/{MODULE}/i/{r['id']}"})
    return {"modules": sorted(mods.values(), key=lambda m: (-m["attention"], -m["waiting"], -m["open"], m["name"])), "programmes": progs,
            "totals": {"records": len(recs), "open": sum(0 if r["done"] else 1 for r in recs), "waiting": sum(1 for r in recs if r.get("waiting")),
                       "attention": sum(1 for r in recs if r.get("attention"))}}


def _cards(u: dict) -> list[dict]:
    v = live_view(u)
    return [{"title": "Programmes", "columns": ["Programme", "Records", "Done", "Waiting", "Attention", "Read", "Open"],
             "rows": [[p["title"], p["records"], p["done"], p["waiting"], p["attention"], p["read"], p["route"]] for p in v["programmes"]],
             "empty": "No programme yet: New work starts one from the records you can see."},
            {"title": "Work across the platform now", "columns": ["Module", "Open", "Waiting", "Attention", "Done", "Open"],
             "rows": [[m["name"], m["open"], m["waiting"], m["attention"], m["done"], m["route"]] for m in v["modules"]],
             "empty": "Nothing in flight that you may see."}]


router = APIRouter()


@router.get("/api/m/delivery/programme")
def api_programme():
    u = wb._u()
    wb._pack(MODULE)
    return live_view(u)


GUIDE = """# Programme & delivery - the work item

This folder is one programme of Relay's Programme & delivery module. It tracks records the platform already holds;
nothing here is estimated.

- `sources/programme.json`: every record in scope, read live (status, decisions waiting, RAG and why), the waves and
  Team & agents' figures for the week.
- `sources/plan.json`, `sources/raid.json`: the plan and the RAID log a person confirmed.
- `status-report.yaml`, `steering-pack.yaml`: what the docs engine built (the same as `genbi doc|deck build`).
- `narrative.yaml`: what you write when asked - a few paragraphs, every number declared with its `record:` source.

Never write a number the records do not hold."""


wb.register(wb.Pack(
    module=MODULE, guide=GUIDE, router=router, cards=_cards,
    lineage="none: a programme reads the records of other modules and writes nothing back",
    platforms={"relay": RECORDS},
    schemas={"scope": SCOPE_EDIT.columns, "wave": PLAN_EDIT.columns, "raid": RAID_EDIT.columns},
    work={"engage": wb.Work(
        title="Track a programme across modules - waves, milestones, RAID and a weekly status report",
        needs_source=False, sources=False, schedule_from="Status",
        journey=["Scope", "Status", "Plan", "RAID", "Report"],
        steps={
            "Scope": wb.Step(kind="deterministic", run=scope, agent="Programme reader", edit=SCOPE_EDIT,
                             confirm="what the programme covers - record by record, each with its wave",
                             text="Every work item, BI migration, change request, deliverable and RFP response you may see; you keep what the programme covers and name each one's wave"),
            "Status": wb.Step(kind="proof", run=status, view="gates", agent="Status reader", confirm=False,
                              text="Each record read live - its journey, open decisions and how long they have waited, what needs attention - with Team & agents' figures for the week"),
            "Plan": wb.Step(kind="deterministic", run=plan, agent="Planner", edit=PLAN_EDIT, confirm_if=lambda ctx, out: bool(ctx.who) or out["counts"].get("changed", 0) > 0,
                            text="The waves with today's counts; you give each one its owner and due date (a weekly round asks again only when a wave is new)"),
            "RAID": wb.Step(kind="deterministic", run=raid, agent="RAID keeper", edit=RAID_EDIT, confirm="the RAID log - every risk, assumption, issue and dependency, with its source",
                            confirm_if=lambda ctx, out: bool(ctx.who) or out["counts"].get("changed", 0) > 0,
                            text="Issues and risks derived from the records (work needing attention, decisions waiting too long, waves due with work open, repeated send-backs) and dependencies between work items; you add what the records cannot know"),
            "Report": wb.Step(kind="deterministic", run=report, view="gates", agent="Report writer", back_to="raid",
                              confirm="the weekly status report and the steering pack before they are shared", confirm_if=lambda ctx, out: out["ok"],
                              actions={"wording": nv.action(("programme", "plan", "raid"), "Summarise the week for the steering group: progress, what waits for a person, the main risks.",
                                                            agent="Report writer", rebuild=lambda ctx: report(ctx))},
                              text="The weekly status report (Word) and the steering pack (PowerPoint) through the docs engine - every figure from the records, checked like `genbi doc|deck check`")},
        fields=[wb.Field("scope_mode", "Which records", "select", options=(("all", "Everything I can see"), ("mine", "Only work I own")), default="all"),
                wb.Field("match", "Only records whose name or module contains", "longtext", help="One word or phrase per line; blank: no filter. You can still change the scope at the first step."),
                wb.Field("waiting_days", "A decision waiting longer than this many days is an issue", "number", default=2),
                wb.Field("template", "Template", "select", options=cx.template_options, default="relay"),
                wb.Field("schedule", "Weekly status report", "cadence", default={"every": "week", "at": "08:00", "weekday": 0, "tz": "UTC"})])}))
