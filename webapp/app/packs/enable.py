"""Adoption & enablement (registry id `enable`) - people ready for the new way: who needs what, learning paths, practice
on sample data, guides and a playbook through the docs engine, and an adoption scorecard; as a consulting engagement.

Engagement  the registry's journey Roles -> Learn -> Practise -> Adopt -> Measure (its confirm point: Learn).
Roles       the workspace's people with what they do on Relay - from the audit log (each action mapped to the module it
            belongs to) and the Validation queue - classed as leads, builders, validators and business users; a
            person corrects the class and writes what each needs.
Learn       a learning path per role: the modules this workspace uses, each lesson from the module's own registry facts
            (what it does, its journey, where a person confirms) and where to open it.
Practise    who practised on sample data, not production: a dashboard of theirs built on generated demo data, or a
            person's note of where they practised.
Adopt       the guides (one per role) and the playbook for validating agent work, through the P11 docs engine - from the
            registry's facts and the workspace's own records (the checkpoint kinds in use, how long decisions take,
            how often work is accepted first time), every figure sourced.
Measure     the adoption scorecard: active people per module from the audit log, the views of delivered reports from
            an uploaded Power BI activity log, Ask Relay questions, decisions and time to validate from the Validation
            queue - against the person's targets (the wizard); the scorecard document through the docs engine. The
            `schedule` field (every week by default) measures again; a round waits for a person only below target.
"""
from __future__ import annotations

import csv
import io
import json
import re
import statistics
import time

from .. import auth, checkpoints, db, registry, store
from .. import workbench as wb
from . import _consult as cx
from . import _narrative as nv

MODULE = "enable"
ROLES = (("lead", "Lead"), ("builder", "Builder"), ("validator", "Validator"), ("business", "Business user"))
# an audit action -> the module it belongs to (work items are looked up by their id)
PREFIX = [("askd.", "askd"), ("studio.", "proposals"), ("rfp.", "rfp"), ("schedule", "schedule"), ("project.", "bi"), ("review.", "bi"), ("publish", "publish"), ("export", "publish"),
          ("page.", "publish"), ("migbi.", "migbi"), ("sdlc.", "sdlc"), ("heal.", "heal"), ("itsm.", "servicedesk"), ("intan.", "intan"), ("observe.", "observe"), ("start.", "start"),
          ("connection.", "connect"), ("metric", "metrics"), ("semantic", "semantics"), ("term.", "semantics"), ("checkpoint.accepted", "validate"), ("checkpoint.sent_back", "validate")]
NAMES = {"validate": "Validation queue", "start": "Start"}
NEEDS = {"lead": "Team & agents, the Validation queue and the Programme view", "builder": "the modules they build in, and proving work before it ships",
         "validator": "the Validation queue: reading the evidence, accepting, sending back with a note", "business": "reading the dashboards and asking Ask Relay"}
ROLE_MODULES = {"lead": ["delivery", "validate"], "builder": [], "validator": ["validate"], "business": ["bi", "askd"]}


class UsagePlatform(wb.Platform):
    label = "Relay's audit log and records, and a report activity export"
    uploads = (".csv",)
    reads = ("who did what on Relay (the audit log), the Validation queue's decisions, dashboards built on sample data - and, when you upload it, the "
             "Power BI activity log (views of the reports that were delivered); nothing is written")
    simulator = "the platform's own records made in the tests; the Power BI activity log of tests/mocklab/finops_sim.py"


USAGE = UsagePlatform()


def _module_name(mid: str) -> str:
    return NAMES.get(mid) or (registry.BY_ID.get(mid) or {}).get("short") or (registry.BY_ID.get(mid) or {}).get("name") or mid


def _audit(since: float) -> list[dict]:
    rows = db.q("SELECT ts, who, action, object FROM audit WHERE ts >= ? AND who IS NOT NULL ORDER BY ts", (since,))
    wbmod = {r["id"]: r["module"] for r in db.q("SELECT id, module FROM wb_items")}
    out = []
    for r in rows:
        a = r["action"] or ""
        mid = wbmod.get(r["object"] or "") if a.startswith("wb.") else next((m for p, m in PREFIX if a.startswith(p)), None)
        if mid:
            out.append({**r, "module": mid})
    return out


def _people(u: dict) -> list[dict]:
    rows = db.q("SELECT u.id, u.name, u.org_role, m.role FROM users u LEFT JOIN memberships m ON m.user_id = u.id WHERE u.active = 1")
    ppl: dict = {}
    for r in rows:
        p = ppl.setdefault(r["id"], {"id": r["id"], "name": r["name"], "admin": r["org_role"] == "admin", "dev": False, "viewer": False})
        p["dev"] |= r["role"] == "dev"
        p["viewer"] |= r["role"] == "viewer"
    return list(ppl.values())


# ------------------------------------------------------------------ Roles

def roles(ctx: wb.Ctx) -> dict:
    now = time.time()
    acts = _audit(now - 90 * cx.DAY)
    decided = {c["decided_by"] for c in db.q("SELECT decided_by FROM checkpoints WHERE decided >= ? AND status IN ('accepted', 'sent_back')", (now - 90 * cx.DAY,)) if c["decided_by"]}
    fresh = []
    for p in _people(cx.owner_user(ctx)):
        mine = [a for a in acts if a["who"] == p["id"]]
        mods = sorted({a["module"] for a in mine})
        role = "lead" if p["admin"] else "builder" if p["dev"] else "validator" if p["id"] in decided else "business"
        fresh.append({"id": p["id"], "include": True, "person": p["name"], "role": role, "modules": ", ".join(_module_name(m) for m in mods) or "-", "actions": len(mine),
                      "last": cx.when(max((a["ts"] for a in mine), default=None)), "needs": NEEDS[role], "module_ids": mods})
    recs = cx.keep_edits(ctx, fresh, ("include", "role", "needs"))
    for r in recs:
        f = next((x for x in fresh if x["id"] == r["id"]), None)
        if f:
            r.update(modules=f["modules"], actions=f["actions"], last=f["last"], module_ids=f["module_ids"])
    cx.put(ctx, "usage_people", {"people": len(recs), "rows": [[r["person"], dict(ROLES)[r["role"]], r["modules"], r["actions"], r["last"]] for r in recs]})
    return {"summary": f"{len(recs)} people: what each does on Relay (the audit log of the last three months) - correct their role and say what each needs.",
            "counts": {"people": len(recs), **{dict(ROLES)[k].lower() + "s": sum(1 for r in recs if r["role"] == k) for k, _ in ROLES}}, "records": recs,
            "data": {"columns": ["In scope", "Person", "Role", "Uses", "Actions", "Last active", "Needs"],
                     "rows": [["yes" if r["include"] else "no", r["person"], dict(ROLES)[r["role"]], r["modules"], r["actions"], r["last"], r["needs"]] for r in recs]}}


def _roles_validate(recs: list[dict], ctx: wb.Ctx) -> list[str]:
    probs = [] if any(r.get("include") for r in recs) else ["Keep at least one person in scope."]
    probs += [f"{r['person']}: what do they need?" for r in recs if r.get("include") and not str(r.get("needs") or "").strip()]
    from .delivery import _text_problems
    return probs + _text_problems(recs, ("needs",))


ROLES_EDIT = wb.Edit(columns=[wb.Column("include", "In scope", "bool"), wb.Column("person", "Person", readonly=True), wb.Column("role", "Role", "select", options=ROLES),
                              wb.Column("modules", "Uses on Relay", readonly=True), wb.Column("actions", "Actions", "number", readonly=True), wb.Column("needs", "What they need", "longtext")],
                     add=False, remove=False, validate=_roles_validate, label="person")


# ------------------------------------------------------------------ Learn

def _in_use() -> list[str]:
    used = {a["module"] for a in _audit(time.time() - 90 * cx.DAY)}
    used |= {r["module"] for r in db.q("SELECT DISTINCT module FROM wb_items")}
    return sorted(m for m in used if m in registry.BY_ID or m in NAMES)


def _lesson(mid: str) -> tuple[str, str]:
    if mid == "validate":
        return ("Read the evidence of each check, accept it, or send it back with a note: the work runs again with it.", "#/validate")
    m = registry.BY_ID[mid]
    w = "develop" if "develop" in m["work"] else (m["work"][0] if m["work"] else "engage")
    plan = registry.plan_for(m, w)
    conf = registry.confirm_for(m, w)
    return (f"{m['text']} The journey: {' '.join(plan['journey'])}. You confirm: {', '.join(c[0] for c in conf)}.", m.get("route") or f"#/m/{mid}")


def learn(ctx: wb.Ctx) -> dict:
    used = _in_use()
    people = [r for r in ctx.records("roles") if r.get("include")]
    fresh = []
    for role, label in ROLES:
        who = [p for p in people if p["role"] == role]
        if not who:
            continue
        mods = list(dict.fromkeys((ROLE_MODULES[role] or []) + sorted({m for p in who for m in p.get("module_ids") or []} if role == "builder" else [])))
        mods = [m for m in mods if m in used or m in ROLE_MODULES[role]] or (["validate"] if role == "validator" else [])
        for mid in mods:
            if mid not in registry.BY_ID and mid not in NAMES:
                continue
            text, where = _lesson(mid)
            fresh.append({"id": f"{role}-{mid}", "include": True, "role": label, "role_id": role, "module": _module_name(mid), "module_id": mid, "lesson": text, "where": where,
                          "people": len(who)})
    recs = cx.keep_edits(ctx, fresh, ("include",))
    return {"summary": f"{len({r['role'] for r in recs})} learning path(s), {len(recs)} lesson(s) - each from the module's own facts and where to open it.",
            "counts": {"paths": len({r['role'] for r in recs}), "lessons": len(recs)}, "records": recs,
            "data": {"columns": ["In the path", "Role", "Module", "Lesson", "Where"], "rows": [["yes" if r["include"] else "no", r["role"], r["module"], r["lesson"][:160], r["where"]] for r in recs]}}


LEARN_EDIT = wb.Edit(columns=[wb.Column("include", "In the path", "bool"), wb.Column("role", "Role", readonly=True), wb.Column("module", "Module", readonly=True),
                              wb.Column("lesson", "Lesson", readonly=True), wb.Column("where", "Where", readonly=True)], add=False, remove=False, label="lesson")


# ------------------------------------------------------------------ Practise

def _practised() -> dict:
    out = {}
    for p in store.dashboards():
        try:
            st = store.load(p["id"])
        except (KeyError, FileNotFoundError, ValueError):
            continue
        if any(f.get("generated") for f in st.get("files") or []):
            owner = (db.project(p["id"]) or {}).get("owner_id")
            if owner:
                out.setdefault(owner, []).append(st.get("name") or p["id"])
    return out


def practise(ctx: wb.Ctx) -> dict:
    done = _practised()
    fresh = []
    for r in ctx.records("roles"):
        if not r.get("include"):
            continue
        d = done.get(r["id"]) or []
        fresh.append({"id": r["id"], "person": r["person"], "role": dict(ROLES)[r["role"]], "practised": "yes" if d else "no", "evidence": f"a dashboard on sample data: {', '.join(d[:3])}" if d else "",
                      "note": ""})
    recs = cx.keep_edits(ctx, fresh, ("note",))
    n = sum(1 for r in recs if r["practised"] == "yes" or str(r.get("note") or "").strip())
    return {"summary": f"{n} of {len(recs)} people practised on sample data - record where the others did, or that they still need to.",
            "counts": {"people": len(recs), "practised": n}, "records": recs,
            "data": {"columns": ["Person", "Role", "Practised", "Evidence", "Note"], "rows": [[r["person"], r["role"], r["practised"], r.get("evidence") or "-", r.get("note") or ""] for r in recs]}}


def _practise_validate(recs: list[dict], ctx: wb.Ctx) -> list[str]:
    from .delivery import _text_problems
    return _text_problems(recs, ("note",))


PRACTISE_EDIT = wb.Edit(columns=[wb.Column("person", "Person", readonly=True), wb.Column("role", "Role", readonly=True), wb.Column("practised", "On sample data", readonly=True),
                                 wb.Column("evidence", "Evidence", readonly=True), wb.Column("note", "Where they practised, or what is next", "longtext")],
                        add=False, remove=False, validate=_practise_validate, label="person")


# ------------------------------------------------------------------ Adopt: the guides and the playbook

def _validation_facts(since: float) -> dict:
    cps = [checkpoints._public(r) for r in db.q("SELECT * FROM checkpoints WHERE decided >= ? AND status IN ('accepted', 'sent_back')", (since,))]
    secs = [c["seconds"] for c in cps if c.get("seconds") is not None]
    kinds: dict = {}
    for c in cps:
        k = kinds.setdefault(c["label"], {"kind": c["label"], "decided": 0, "accepted": 0})
        k["decided"] += 1
        k["accepted"] += 1 if c["status"] == "accepted" else 0
    acc = sum(1 for c in cps if c["status"] == "accepted")
    return {"decided": len(cps), "accepted": acc, "accepted_pct": cx.pct(acc, len(cps)) or 0, "median_minutes": round(statistics.median(secs) / 60, 1) if secs else 0,
            "kinds": sorted(kinds.values(), key=lambda k: -k["decided"])[:14], "open": db.one("SELECT COUNT(*) AS n FROM checkpoints WHERE status = 'open'")["n"]}


def adopt(ctx: wb.Ctx) -> dict:
    v = _validation_facts(time.time() - 90 * cx.DAY)
    v["rows"] = [[k["kind"], k["decided"], k["accepted"]] for k in v["kinds"]]
    cx.put(ctx, "validation", v)
    lessons = [r for r in ctx.records("learn") if r.get("include")]
    cx.put(ctx, "paths", {"lessons": len(lessons), "rows": [[r["role"], r["module"], r["lesson"], r["where"]] for r in lessons]})
    day = cx.iso_day(time.time())
    V = "record:validation"
    p1, f1 = cx.say("In the last three months people decided {d} checks; {a} were accepted first time, and the median decision took {m} minutes.",
                    d=(v["decided"], f"{V}#decided"), a=(v["accepted"], f"{V}#accepted"), m=(v["median_minutes"], f"{V}#median_minutes"))
    play = {"kind": "doc", "title": "Playbook: validating agent work", "subtitle": f"{ctx.title} - {day}", "audience": "everyone who confirms agent work", "date": day,
            "sections": [{"title": "Why a person confirms", "blocks": [{"kind": "paragraph", "text": "Relay's agents do the repeated work; a person confirms every step that matters. "
                                                                                                    "Nothing reaches a live system, a buyer or a client without a named approval."},
                                                                       {"kind": "paragraph", "text": p1, "figures": f1}]},
                         {"title": "How to confirm", "blocks": [{"kind": "bullets", "bullets": ["Open the check from the Validation queue or the work item; read its summary and its evidence.",
                                                                                               "Correct the rows in place when something is wrong; your changes are saved when you confirm.",
                                                                                               "Accept when it is right. Send it back with a note when it is not: the step runs again with your note.",
                                                                                               "A check named for someone else is theirs: ask them, or an admin to reassign it."]}]},
                         {"title": "The checks in this workspace", "blocks": [{"kind": "table", "table": cx.table(["Check", "Decided", "Accepted first time"], v["rows"] or [["-"] * 3], f"{V}#rows",
                                                                                                                  "Decisions of the last three months, by kind of check")}]}]}
    out = [cx.deliver(ctx, "playbook", play, "Playbook for validating agent work")]
    for role, label in ROLES:
        mine = [r for r in lessons if r["role"] == label]
        if not mine:
            continue
        guide = {"kind": "doc", "title": f"Getting started on Relay: {label.lower()}s"[:70], "subtitle": f"{ctx.title} - {day}", "audience": f"the workspace's {label.lower()}s", "date": day,
                 "sections": [{"title": "Your learning path", "blocks": [{"kind": "paragraph", "text": f"What a {label.lower()} uses on Relay in this workspace, module by module. Each lesson opens where the work is."},
                                                                         {"kind": "table", "table": cx.table(["Module", "Lesson", "Where"], [[r["module"], r["lesson"], r["where"]] for r in mine],
                                                                                                             "record:paths#rows", "From each module's own facts")}]},
                              {"title": "Practise first", "blocks": [{"kind": "paragraph", "text": "Practise on sample data, not production: New dashboard > Generate demo data builds a realistic data set with stories planted in it."}]}]}
        out.append(cx.deliver(ctx, f"guide-{role}", guide, f"Guide for {label.lower()}s"))
    gates = [o["gate"] for o in out] + [ctx.proof("sourced", label="Every figure of the playbook resolves to its record", figures=[{"label": x["text"], "value": x["value"], "source": x["source"]} for x in f1])]
    ok = all(o["ok"] for o in out) and gates[-1]["status"] == "pass"
    return {"summary": (f"The playbook and {len(out) - 1} guide(s), one per role, pass every check - confirm them before they are shared." if ok
                        else "A guide did not pass its checks: " + "; ".join(p for o in out for p in o["problems"])[:400]),
            "ok": ok, "counts": {"documents": len(out)}, "data": {"checks": gates}}


# ------------------------------------------------------------------ Measure: the adoption scorecard

def _report_views(ctx: wb.Ctx) -> dict:
    views: dict = {}
    for f in ctx.files((".csv",)):
        try:
            rows = list(csv.DictReader(io.StringIO((ctx.dir / "data" / f["name"]).read_text(encoding="utf-8-sig"))))
        except (OSError, UnicodeDecodeError):
            continue
        rows = [{(k or "").strip().lower(): (v or "").strip() for k, v in r.items()} for r in rows]
        if not rows or not {"userid", "activity", "itemname"} <= set(rows[0]):
            continue
        for r in rows:
            if (r.get("activity") or "").lower() == "viewreport":
                v = views.setdefault(r["itemname"], {"report": r["itemname"], "views": 0, "viewers": set()})
                v["views"] += 1
                v["viewers"].add(r["userid"].lower())
    delivered = {(p.get("name") or "").lower() for p in store.dashboards()}
    return {"reports": [{"report": v["report"], "views": v["views"], "viewers": len(v["viewers"]), "delivered_by_relay": v["report"].lower() in delivered} for v in sorted(views.values(), key=lambda v: -v["views"])]}


def measure(ctx: wb.Ctx) -> dict:
    now = time.time()
    if ctx.who is None and not ctx.action:
        nv.clear(ctx)                                # a scheduled round: new figures, last week's drafted wording no longer applies
    acts = _audit(now - 30 * cx.DAY)
    people = [r for r in ctx.records("roles") if r.get("include")]
    ids = {r["id"] for r in people}
    mods: dict = {}
    for a in acts:
        if a["who"] in ids:
            m = mods.setdefault(a["module"], {"module": _module_name(a["module"]), "people": set(), "actions": 0})
            m["people"].add(a["who"])
            m["actions"] += 1
    active = {a["who"] for a in acts if a["who"] in ids}
    v = _validation_facts(now - 30 * cx.DAY)
    rv = _report_views(ctx)
    questions = sum(1 for a in acts if a["module"] == "askd")
    practised = sum(1 for r in ctx.records("practise") if r.get("practised") == "yes" or str(r.get("note") or "").strip())
    rec = {"people": len(people), "active": len(active), "active_pct": cx.pct(len(active), len(people)) or 0, "questions": questions, "practised": practised,
           "practised_pct": cx.pct(practised, len(people)) or 0, "validation": v, "reports": rv["reports"][:14],
           "report_views": sum(r["views"] for r in rv["reports"]), "delivered_views": sum(r["views"] for r in rv["reports"] if r["delivered_by_relay"]),
           "modules": [{"module": m["module"], "people": len(m["people"]), "actions": m["actions"]} for m in sorted(mods.values(), key=lambda m: -len(m["people"]))],
           "rows": [[m["module"], len(m["people"]), m["actions"]] for m in sorted(mods.values(), key=lambda m: -len(m["people"]))][:14],
           "report_rows": [[r["report"], r["views"], r["viewers"], "yes" if r["delivered_by_relay"] else "no"] for r in rv["reports"][:14]]}
    src = cx.put(ctx, "adoption", rec)
    gates = []
    t_active, t_minutes = ctx.scope.get("target_active_pct"), ctx.scope.get("target_minutes")
    for name, label, measured, target, better in (("active", "People active on Relay in the last thirty days", rec["active_pct"], t_active, "higher"),
                                                  ("validate", "Median time to decide a check", v["median_minutes"], t_minutes, "lower")):
        try:
            tv = float(target) if target not in (None, "") else None
        except (TypeError, ValueError):
            tv = None
        st = "warn" if tv is None else ("pass" if (measured >= tv if better == "higher" else measured <= tv) else "fail")
        gates.append({"name": name, "label": label, "status": st, "measured": f"{cx.num(measured)}{' %' if name == 'active' else ' minutes'}",
                      "expected": (f"at least {cx.num(tv)} %" if name == "active" else f"at most {cx.num(tv)} minutes") if tv is not None else "no target set", "detail": ""})
    gates.append({"name": "practised", "label": "People who practised on sample data", "status": "pass" if rec["practised"] == rec["people"] else "warn",
                  "measured": f"{rec['practised']} of {rec['people']}", "expected": "everyone in scope", "detail": ""})
    S = "record:adoption"
    p1, f1 = cx.say("{a} of {n} people were active on Relay in the last thirty days ({p}); {q} questions went to Ask Relay.", a=(rec["active"], f"{S}#active"), n=(rec["people"], f"{S}#people"),
                    p=(rec["active_pct"], f"{S}#active_pct", "%"), q=(rec["questions"], f"{S}#questions"))
    p2, f2 = cx.say("People decided {d} checks, {acc} of them accepted first time; the median decision took {m} minutes.", d=(v["decided"], f"{S}#validation.decided"),
                    acc=(v["accepted"], f"{S}#validation.accepted"), m=(v["median_minutes"], f"{S}#validation.median_minutes"))
    p3, f3 = (cx.say("The reports in the activity log were viewed {r} times; {dv} of those views were of reports Relay delivered.", r=(rec["report_views"], f"{S}#report_views"),
                     dv=(rec["delivered_views"], f"{S}#delivered_views")) if rec["reports"] else ("No report activity log was uploaded, so report views are not measured.", []))
    day = cx.iso_day(now)
    doc = {"kind": "doc", "title": f"Adoption scorecard: {ctx.title}"[:70], "subtitle": f"Week of {day}", "audience": "the lead and the sponsor", "date": day,
           "sections": [{"title": "Adoption", "blocks": [{"kind": "paragraph", "text": p1, "figures": f1}, {"kind": "paragraph", "text": p2, "figures": f2}, {"kind": "paragraph", "text": p3, "figures": f3}]
                         + nv.blocks(ctx, "In short")},
                        {"title": "Module by module", "blocks": [{"kind": "table", "table": cx.table(["Module", "People", "Actions"], rec["rows"] or [["-"] * 3], f"{S}#rows", "From the audit log, the last thirty days")}]},
                        {"title": "Report views", "blocks": [{"kind": "table", "table": cx.table(["Report", "Views", "Viewers", "Delivered by Relay"], rec["report_rows"] or [["-"] * 4], f"{S}#report_rows",
                                                                                               "From the uploaded Power BI activity log")}]}]}
    a = cx.deliver(ctx, "scorecard", doc, "Adoption scorecard")
    gates.append(a["gate"])
    gates.append(ctx.proof("sourced", label="Every figure of the scorecard resolves to its record", figures=[{"label": x["text"], "value": x["value"], "source": x["source"]} for x in f1 + f2 + f3]))
    ctx.put("summary", {"active_pct": rec["active_pct"], "median_minutes": v["median_minutes"], "people": rec["people"], "when": now})
    return {"summary": f"{rec['active']} of {rec['people']} people active ({cx.num(rec['active_pct'])} %), median decision {cx.num(v['median_minutes'])} minutes"
                       + (f", {rec['report_views']} report views" if rec["reports"] else "") + ".", "ok": a["ok"] and gates[-1]["status"] == "pass",
            "counts": {"active %": rec["active_pct"], "below target": sum(1 for g in gates if g["status"] == "fail")}, "data": {"checks": gates}}


def _page_cards(u: dict) -> list[dict]:
    rows = db.q("SELECT id, title, status FROM wb_items WHERE module = ? ORDER BY updated DESC LIMIT 30", (MODULE,))
    vis = auth.access_map(u, [r["id"] for r in rows]) if u else {}
    out = []
    for r in rows:
        if r["id"] in vis:
            s = (wb._load(r["id"]).get("data") or {}).get("summary") or {}
            out.append([r["title"], wb.STATUS_LABEL.get(r["status"], r["status"]), f"{cx.num(s['active_pct'])} %" if s.get("active_pct") is not None else "-",
                        f"{cx.num(s['median_minutes'])} min" if s.get("median_minutes") is not None else "-", f"#/m/{MODULE}/i/{r['id']}"])
    return [{"title": "Adoption scorecards", "columns": ["Engagement", "Status", "Active", "Time to decide", "Open"], "rows": out, "empty": "No adoption engagement yet."}]


GUIDE = """# Adoption & enablement - the work item

This folder is one adoption engagement of Relay's Adoption & enablement module.

- `sources/usage_people.json`, `paths.json`, `validation.json`, `adoption.json`: who does what on Relay (the audit
  log), the learning paths, the Validation queue's decisions and the adoption scorecard's figures.
- `playbook.yaml`, `guide-*.yaml`, `scorecard.yaml`: what the docs engine built (the same as `genbi doc build`).
- `narrative.yaml`: what you write when asked - a few paragraphs, every number declared with its `record:` source.

Never write a number the records do not hold."""


wb.register(wb.Pack(
    module=MODULE, guide=GUIDE, cards=_page_cards,
    lineage="none: adoption reads the audit log and the platform's records; it writes nothing back",
    platforms={"usage": USAGE},
    schemas={"person": ROLES_EDIT.columns, "lesson": LEARN_EDIT.columns, "practice": PRACTISE_EDIT.columns},
    work={"engage": wb.Work(
        title="Make validating agent work the team's habit: who needs what, learning paths, practice, guides and a playbook, an adoption scorecard",
        needs_source=False, schedule_from="Measure",
        steps={
            "Roles": wb.Step(kind="deterministic", run=roles, agent="Usage reader", edit=ROLES_EDIT, confirm="who needs what - each person's role and what they need",
                             text="The workspace's people with what they do on Relay (the audit log) - leads, builders, validators, business users; you correct the roles and say what each needs"),
            "Learn": wb.Step(kind="deterministic", run=learn, agent="Learning designer", edit=LEARN_EDIT,
                             text="A learning path per role: the modules this workspace uses, each lesson from the module's own facts and where to open it"),
            "Practise": wb.Step(kind="deterministic", run=practise, agent="Practice tracker", edit=PRACTISE_EDIT, confirm="who practised on sample data, and what is next for the others",
                                text="Who practised on sample data, not production - a dashboard of theirs on generated demo data, or your note"),
            "Adopt": wb.Step(kind="deterministic", run=adopt, view="gates", agent="Guide writer", confirm="the guides and the playbook before they are shared", confirm_if=lambda ctx, out: out["ok"],
                             text="A guide per role and the playbook for validating agent work, through the docs engine - every figure from the workspace's records"),
            "Measure": wb.Step(kind="proof", run=measure, view="gates", agent="Adoption scorer", confirm="the adoption scorecard, when it is below target",
                               confirm_if=lambda ctx, out: out["ok"] and out["counts"].get("below target", 0) > 0,
                               actions={"wording": nv.action(("adoption",), "Summarise adoption for the sponsor: who uses Relay, how fast people decide, what is next.",
                                                             agent="Adoption scorer", rebuild=lambda ctx: measure(ctx))},
                               text="Active people per module, report views, Ask Relay, decisions and time to validate - against your targets, with the scorecard document")},
        fields=[wb.Field("target_active_pct", "Target: people active in thirty days (per cent)", "number", help="Leave empty to measure without judging."),
                wb.Field("target_minutes", "Target: median minutes to decide a check", "number"),
                wb.Field("template", "Template", "select", options=cx.template_options, default="relay"),
                wb.Field("schedule", "Measure again", "cadence", default={"every": "week", "at": "08:00", "weekday": 0, "tz": "UTC"})])}))
