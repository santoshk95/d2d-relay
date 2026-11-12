"""Managed services & support (registry id `managed`) - running what was delivered, with SLAs from the service desk
and a monthly service report, as a consulting engagement.

Engagement  Catalogue -> SLAs -> Improve -> Act -> Report.
Catalogue   the service catalogue from what this workspace runs on Relay (dashboards, scheduled reports, the
            service desk's sources, integrations and data watched, Self-healing, change requests, live quality rule
            sets, other modules' work items): one service each, with the records behind it; a person writes who
            supports it (agents first, people for decisions), its hours and its owner.
SLAs        measured from the Service desk's own records (P12): tickets by priority in the period, resolved, with a
            due date from the service desk, met (resolved by the due date), breached, still open past due, the
            median time to resolve; duplicates grouped and work routed to agents; Self-healing cases closed and data
            incidents resolved. The attainment target is the person's (the wizard); without one the figures are
            shown, not judged.
Improve     continuous-improvement items suggested from the same records (a ticket group that keeps coming back,
            breaches by priority, Self-healing cases and data incidents left open); a person keeps, adds, gives each
            an owner and a due date and says where it goes (tracked here, a ticket, Self-healing).
Act         the approved hand-offs go out: a ticket through the service desk's own write approval (a source allowed
            to raise tickets; else the workbench joins a Service desk group or leaves a draft), a Self-healing case.
Report      the monthly service report (Word) through the P11 docs engine, every figure from sources/service.json -
            the studio's "monthly service report", built from the records; a person confirms it.
"""
from __future__ import annotations

import re
import statistics
import time

from .. import auth, db, registry, store
from .. import workbench as wb
from . import _consult as cx
from . import _narrative as nv

MODULE = "managed"
PRIO = ("P1", "P2", "P3", "P4")
PRIO_OF = {"highest": "P1", "critical": "P1", "urgent": "P1", "blocker": "P1", "high": "P2", "major": "P2", "medium": "P3", "normal": "P3", "moderate": "P3",
           "low": "P4", "lowest": "P4", "minor": "P4", "trivial": "P4"}
ROUTES = (("track", "Track it here"), ("ticket", "Raise a ticket"), ("heal", "Self-healing"))
PERIODS = (("30d", "The last 30 days"), ("month", "The last calendar month"), ("7d", "The last 7 days"))


class ServiceDeskPlatform(wb.Platform):
    label = "The Service desk and Relay's own records"
    reads = ("the Service desk's tickets and groups (Jira Service Management, Freshservice, ServiceNow through P12), Self-healing cases, data incidents "
             "and what this workspace runs on Relay - nothing is written except the hand-offs a person approves")
    simulator = "the P12 Service desk simulators (tests/mocklab/itsm_sim.py); the tests write tickets, groups and cases into the platform's tables"


DESK = ServiceDeskPlatform()


def _prio(p) -> str:
    s = str(p or "").strip()
    if re.fullmatch(r"[Pp][1-4]", s):
        return s.upper()
    return PRIO_OF.get(s.lower(), "Unprioritised")


def _window(ctx: wb.Ctx) -> tuple[float, float, str]:
    now = time.time()
    p = ctx.scope.get("period") or "30d"
    if p == "7d":
        return now - 7 * cx.DAY, now, "the last seven days"
    if p == "month":
        t = time.gmtime(now)
        y, m = (t.tm_year, t.tm_mon - 1) if t.tm_mon > 1 else (t.tm_year - 1, 12)
        start = cx.parse_day(f"{y:04d}-{m:02d}-01")
        end = cx.parse_day(f"{t.tm_year:04d}-{t.tm_mon:02d}-01")
        return start, end, time.strftime("%B %Y", time.gmtime(start + cx.DAY))
    return now - 30 * cx.DAY, now, "the last thirty days"


def _n(sql: str, args: tuple = ()) -> int:
    try:
        return int((db.one(sql, args) or {}).get("n") or 0)
    except Exception:  # noqa: BLE001 - a module this workspace never used
        return 0


# ------------------------------------------------------------------ Catalogue

def _services(u: dict) -> list[dict]:
    t = set(db.tables())
    items = cx.work_items(u, exclude=MODULE)
    by_mod: dict = {}
    for it in items:
        by_mod.setdefault(it["module"], []).append(it)
    rows = []

    def add(sid, name, n, what, module):
        if n:
            rows.append({"id": sid, "service": name, "records": n, "what": what, "module": module})
    from .. import home
    add("dashboards", "Dashboards and their review gates", len(home._visible_projects(u)), "dashboards", "bi")
    add("schedules", "Scheduled reports and alerts", _n("SELECT COUNT(*) AS n FROM schedules WHERE status = 'active'"), "active schedules", "schedule")
    if "itsm_sources" in t:
        add("servicedesk", "Service desk triage and routing", _n("SELECT COUNT(*) AS n FROM itsm_sources"), "service-desk sources", "servicedesk")
    if "intan_integrations" in t:
        add("integrations", "Integration monitoring", _n("SELECT COUNT(*) AS n FROM intan_integrations WHERE active = 1"), "integrations watched", "intan")
    if "observe_assets" in t:
        add("observability", "Data observability", _n("SELECT COUNT(*) AS n FROM observe_assets WHERE enabled = 1"), "data assets watched", "observe")
    if "heal_cases" in t:
        add("healing", "Self-healing", _n("SELECT COUNT(*) AS n FROM heal_cases"), "Self-healing cases", "heal")
    if "sdlc_requests" in t:
        add("changes", "Change requests (AI SDLC)", _n("SELECT COUNT(*) AS n FROM sdlc_requests"), "change requests", "sdlc")
    if "quality_rulesets" in t:
        add("quality", "Data quality checks", _n("SELECT COUNT(*) AS n FROM quality_rulesets WHERE status = 'live'"), "live rule sets", "quality")
    for mid, its in sorted(by_mod.items()):
        add(f"wb-{mid}", (registry.BY_ID.get(mid) or {}).get("name", mid), len(its), "work items", mid)
    return rows


def catalogue(ctx: wb.Ctx) -> dict:
    u = cx.owner_user(ctx)
    cx.need(bool(u), "The owner is not an active person in this workspace any more.")
    me = u.get("name") or ""
    fresh = [{**s, "include": True, "support": "L1 by agents; L2 and L3 by people", "hours": ctx.scope.get("hours") or "", "owner": me} for s in _services(u)]
    recs = cx.keep_edits(ctx, fresh, ("include", "support", "hours", "owner"))
    for r in recs:
        f = next((x for x in fresh if x["id"] == r["id"]), None)
        if f:
            r["records"] = f["records"]
    if not recs:
        raise wb.StepFailed("Nothing runs on Relay in this workspace yet: there is no service to support.")
    return {"summary": f"{len(recs)} service(s) run on Relay here - say who supports each, its hours and its owner.",
            "counts": {"services": len(recs)}, "records": recs,
            "data": {"columns": ["In the catalogue", "Service", "On Relay", "Support", "Hours", "Owner"],
                     "rows": [["yes" if r.get("include") else "no", r["service"], f"{r['records']} {r['what']}", r.get("support"), r.get("hours"), r.get("owner")] for r in recs]}}


def _cat_validate(recs: list[dict], ctx: wb.Ctx) -> list[str]:
    probs = [] if any(r.get("include") for r in recs) else ["Keep at least one service in the catalogue."]
    for r in recs:
        if not r.get("include"):
            continue
        if not str(r.get("support") or "").strip():
            probs.append(f"{r['service']}: who supports it?")
        if not str(r.get("hours") or "").strip():
            probs.append(f"{r['service']}: its support hours (e.g. Monday to Friday, 9 to 6).")
        if not str(r.get("owner") or "").strip():
            probs.append(f"{r['service']}: who owns it?")
    from .delivery import _text_problems
    return probs + _text_problems(recs, ("support", "hours"))


CAT_EDIT = wb.Edit(columns=[wb.Column("include", "In the catalogue", "bool"), wb.Column("service", "Service", readonly=True), wb.Column("records", "On Relay", "number", readonly=True),
                            wb.Column("support", "Who supports it"), wb.Column("hours", "Support hours"), wb.Column("owner", "Owner", "select", options=cx.person_options)],
                   add=False, remove=False, validate=_cat_validate, label="service")


# ------------------------------------------------------------------ SLAs from the service desk

def slas(ctx: wb.Ctx) -> dict:
    start, end, label = _window(ctx)
    now = time.time()
    t = set(db.tables())
    tickets = db.q("SELECT * FROM itsm_tickets WHERE created < ? AND (open = 1 OR updated >= ?)", (end, start)) if "itsm_tickets" in t else []
    rows, gates = [], []
    target = ctx.scope.get("sla_target_pct")
    try:
        target = float(target) if target not in (None, "") else None
    except (TypeError, ValueError):
        target = None
    by = {}
    for p in (*PRIO, "Unprioritised"):
        ts = [x for x in tickets if _prio(x.get("priority")) == p]
        opened = [x for x in ts if start <= (x.get("created") or 0) < end]
        resolved = [x for x in ts if not x.get("open") and start <= (x.get("updated") or 0) < end]
        with_due = [x for x in resolved if x.get("due")]
        met = [x for x in with_due if (x.get("updated") or 0) <= x["due"]]
        open_late = [x for x in ts if x.get("open") and x.get("due") and x["due"] < min(now, end)]
        hours = [((x.get("updated") or 0) - (x.get("created") or 0)) / 3600 for x in resolved if x.get("created") and x.get("updated")]
        d = {"priority": p, "opened": len(opened), "resolved": len(resolved), "with_due": len(with_due), "met": len(met), "breached": len(with_due) - len(met),
             "open_late": len(open_late), "open": sum(1 for x in ts if x.get("open")), "met_pct": cx.pct(len(met), len(with_due)) or 0,
             "median_hours": round(statistics.median(hours), 1) if hours else 0}
        by[p] = d
        if not ts:
            continue
        rows.append([p, d["opened"], d["resolved"], d["met"], d["breached"], d["open_late"], f"{cx.num(d['met_pct'])} %" if d["with_due"] else "-", cx.num(d["median_hours"])])
        if d["with_due"]:
            st = "pass" if target is None or d["met_pct"] >= target else "fail"
            gates.append({"name": f"sla-{p}", "label": f"{p}: resolved by the service desk's due date", "status": st if target is not None else "warn",
                          "measured": f"{cx.num(d['met_pct'])} % ({d['met']} of {d['with_due']})", "expected": f"{cx.num(target)} %" if target is not None else "no target set",
                          "detail": f"{d['breached']} breached, {d['open_late']} still open past their due date; median {cx.num(d['median_hours'])} h to resolve"})
        else:
            gates.append({"name": f"sla-{p}", "label": f"{p}: resolved by the service desk's due date", "status": "skip", "measured": f"{d['resolved']} resolved", "expected": "",
                          "detail": "no resolved ticket carried a due date from the service desk"})
    groups = db.q("SELECT * FROM itsm_groups WHERE updated >= ? OR status = 'open'", (start,)) if "itsm_groups" in t else []
    routed = {"agent": sum(1 for g in groups if g.get("route") == "agent"), "person": sum(1 for g in groups if g.get("route") == "person")}
    heal_closed = _n("SELECT COUNT(*) AS n FROM heal_cases WHERE closed >= ? AND closed < ?", (start, end)) if "heal_cases" in t else 0
    heal_open = _n("SELECT COUNT(*) AS n FROM heal_cases WHERE closed IS NULL") if "heal_cases" in t else 0
    inc = db.q("SELECT first_seen, resolved FROM observe_incidents WHERE resolved >= ? AND resolved < ?", (start, end)) if "observe_incidents" in t else []
    inc_open = _n("SELECT COUNT(*) AS n FROM observe_incidents WHERE status IN ('open', 'proposed', 'actioned')") if "observe_incidents" in t else 0
    with_due = sum(d["with_due"] for d in by.values())
    met = sum(d["met"] for d in by.values())
    totals = {"tickets": len(tickets), "opened": sum(d["opened"] for d in by.values()), "resolved": sum(d["resolved"] for d in by.values()), "with_due": with_due,
              "met": met, "breached": with_due - met, "met_pct": cx.pct(met, with_due) or 0, "open_late": sum(d["open_late"] for d in by.values()),
              "groups": len(groups), "grouped_tickets": sum(int(g.get("tickets") or 0) for g in groups), "routed_agent": routed["agent"], "routed_person": routed["person"],
              "heal_closed": heal_closed, "heal_open": heal_open, "incidents_resolved": len(inc), "incidents_open": inc_open,
              "incident_mttr_hours": round(statistics.median([(x["resolved"] - x["first_seen"]) / 3600 for x in inc]), 1) if inc else 0}
    u = cx.owner_user(ctx)
    team = cx.team_value(u, "30d") if (ctx.scope.get("period") or "30d") != "7d" else cx.team_value(u, "7d")
    done_items = [it for it in cx.work_items(u, exclude=MODULE) if it["done"] and start <= (it["updated"] or 0) < end]
    rec = {"period": label, "start": start, "end": end, "target_pct": target, "by_priority": by, "totals": totals, "rows": rows,
           "groups": [[g["title"][:120], int(g.get("tickets") or 0), g.get("priority") or "-", g.get("route") or "-", g.get("status")] for g in sorted(groups, key=lambda g: -int(g.get("tickets") or 0))[:14]],
           "team": team, "delivered": len(done_items), "delivered_rows": [[it["module_name"], it["title"], it["work_name"]] for it in done_items[:14]],
           "method": "Resolved: closed in the service desk within the period; met: resolved by the due date the service desk set; the time to resolve runs from creation to the "
                     "service desk's last update of the closed ticket."}
    src = cx.put(ctx, "service", rec)
    ctx.evidence("Tickets read from the service desk", {"rows": [{k: x.get(k) for k in ("key", "title", "priority", "created", "updated", "due", "open", "status")} for x in tickets[:500]]},
                 kind="tickets", ok=True)
    gates.append(ctx.proof("sourced", label="Every SLA figure resolves to the service record", figures=[
        {"label": "tickets resolved", "value": totals["resolved"], "source": f"{src}#totals.resolved"}, {"label": "met by the due date", "value": totals["met"], "source": f"{src}#totals.met"},
        {"label": "breached", "value": totals["breached"], "source": f"{src}#totals.breached"}]))
    ctx.put("summary", {"period": label, "met_pct": totals["met_pct"], "resolved": totals["resolved"], "breached": totals["breached"], "when": time.time()})
    return {"summary": f"{label}: {totals['resolved']} ticket(s) resolved, {totals['met']} of {totals['with_due']} by their due date"
                       + (f" ({cx.num(totals['met_pct'])} %)" if with_due else "") + f", {totals['open_late']} open past due; {heal_closed} Self-healing case(s) closed, {len(inc)} data incident(s) resolved.",
            "counts": {"resolved": totals["resolved"], "breached": totals["breached"], "open late": totals["open_late"]}, "data": {"checks": gates}}


# ------------------------------------------------------------------ Improve

def improve(ctx: wb.Ctx) -> dict:
    rec = cx.read(ctx, "service") or {}
    t = set(db.tables())
    me = (cx.owner_user(ctx) or {}).get("name") or ""
    n_min = int(float(ctx.scope.get("repeat_min") or 3))
    found = []
    if "itsm_groups" in t:
        for g in db.q("SELECT * FROM itsm_groups WHERE status = 'open' AND tickets >= ? ORDER BY tickets DESC LIMIT 10", (n_min,)):
            found.append({"id": f"group-{g['id']}", "item": f"Fix the cause behind \"{g['title'][:90]}\"", "why": f"{g['tickets']} tickets in one group ({g.get('priority') or 'no priority'}); the service desk's group {g['id']}",
                          "route": "ticket", "about": g["title"]})
    for p, d in (rec.get("by_priority") or {}).items():
        if d.get("breached") or d.get("open_late"):
            found.append({"id": f"sla-{p}", "item": f"Review how {p} tickets are handled", "why": f"{d['breached']} breached and {d['open_late']} open past their due date ({rec.get('period')})",
                          "route": "track", "about": f"{p} tickets"})
    if "heal_cases" in t:
        for hc in db.q("SELECT id, title, created FROM heal_cases WHERE closed IS NULL AND created < ? ORDER BY created LIMIT 5", (time.time() - 7 * cx.DAY,)):
            found.append({"id": f"heal-{hc['id']}", "item": f"Close the Self-healing case \"{hc['title'][:80]}\"", "why": f"open since {cx.when(hc['created'])} (case {hc['id']})",
                          "route": "heal", "about": hc["title"]})
    if "observe_incidents" in t:
        for inc in db.q("SELECT id, title, first_seen FROM observe_incidents WHERE status IN ('open', 'proposed') ORDER BY first_seen LIMIT 5"):
            found.append({"id": f"inc-{inc['id']}", "item": f"Resolve the data incident \"{inc['title'][:80]}\"", "why": f"open since {cx.when(inc['first_seen'])} (incident {inc['id']})",
                          "route": "track", "about": inc["title"]})
    for f in found:
        f.update(owner=me, due="", status="open", origin="relay")
    recs = cx.keep_edits(ctx, found, ("owner", "due", "route", "status", "item"))
    return {"summary": f"{len(recs)} improvement item(s) from the service desk and the platform's records - keep what matters, add your own, give each an owner, "
                       "a due date and where it goes.", "counts": {"items": len(recs), "tickets": sum(1 for r in recs if r.get("route") == "ticket")}, "records": recs,
            "data": {"columns": ["Item", "Why", "Owner", "Due", "Where it goes"], "rows": [[r["item"], r.get("why") or "added by a person", r.get("owner"), r.get("due"), r.get("route")] for r in recs]}}


def _imp_validate(recs: list[dict], ctx: wb.Ctx) -> list[str]:
    probs = []
    for r in recs:
        if not str(r.get("item") or "").strip():
            probs.append("Say what the improvement is.")
            continue
        if r.get("status") == "done":
            continue
        if not str(r.get("owner") or "").strip():
            probs.append(f"{r['item'][:50]}: who owns it?")
        if cx.parse_day(r.get("due") or "") is None:
            probs.append(f"{r['item'][:50]}: its due date, like 2026-12-31.")
    from .delivery import _text_problems
    return probs + _text_problems(recs, ("item",))


IMP_EDIT = wb.Edit(columns=[wb.Column("item", "Improvement", required=True), wb.Column("why", "Why", readonly=True), wb.Column("owner", "Owner", "select", options=cx.person_options),
                            wb.Column("due", "Due (YYYY-MM-DD)"), wb.Column("route", "Where it goes", "select", options=ROUTES),
                            wb.Column("status", "Status", "select", options=(("open", "Open"), ("done", "Done")))], validate=_imp_validate, label="task")


# ------------------------------------------------------------------ Act: the approved hand-offs

def act(ctx: wb.Ctx) -> dict:
    from .. import itsm
    rows, done = [], []
    target = itsm.ticket_target() if "itsm_sources" in db.tables() else None
    for r in ctx.records("improve"):
        if r.get("status") == "done":
            continue
        title = r["item"][:200]
        body = f"{r['item']}\n\nWhy: {r.get('why') or 'added by a person'}\nOwner: {r.get('owner')}\nDue: {r.get('due')}\nWork item: {wb.route_of(ctx.st)}"
        if r.get("route") == "ticket":
            if target:
                try:
                    w = itsm.request_write(target["id"], "create", {"title": title, "description": body, "priority": "P3", "labels": ["managed-service", "improvement"]},
                                           who=ctx.who or ctx.owner, module=registry.BY_ID[MODULE]["name"], origin=f"wb:{ctx.id}:{r['id']}", link=wb.route_of(ctx.st))
                    h = ctx._handoff({"kind": "ticket", "label": title, "checkpoint": w.get("checkpoint_id"), "status": "awaiting the service desk's write approval",
                                      "link": "#/validate", "via": target["name"]})
                except itsm.WriteRefused as e:
                    h = ctx.ticket(title, body, priority="P3", about=r.get("about") or title)
                    h = {**h, "status": f"{h.get('status')} ({str(e)[:80]})"}
            else:
                h = ctx.ticket(title, body, priority="P3", about=r.get("about") or title)
        elif r.get("route") == "heal":
            h = ctx.heal(title, body, signature=f"managed:{cx.slug(r['id'], 40)}", subject={"improvement": r["id"]})
        else:
            h = {"kind": "track", "label": title, "status": f"tracked here, owned by {r.get('owner')}, due {r.get('due')}"}
        done.append(h)
        rows.append([title, {"ticket": "Ticket", "heal": "Self-healing", "track": "Tracked"}.get(h.get("kind"), h.get("kind")), h.get("status"), h.get("case") or h.get("checkpoint") or h.get("output") or ""])
    cx.put(ctx, "improve", {"count": len(ctx.records("improve")), "open": sum(1 for r in ctx.records("improve") if r.get("status") != "done"),
                            "tickets": sum(1 for h in done if h.get("kind") == "ticket"), "heal": sum(1 for h in done if h.get("kind") == "heal"),
                            "rows": [[r["item"], r.get("owner") or "-", r.get("due") or "-", dict(ROUTES).get(r.get("route"), r.get("route")), r.get("status")] for r in ctx.records("improve")]})
    return {"summary": f"{sum(1 for h in done if h.get('kind') == 'ticket')} ticket(s), {sum(1 for h in done if h.get('kind') == 'heal')} Self-healing case(s), "
                       f"{sum(1 for h in done if h.get('kind') == 'track')} tracked here - as you approved.",
            "counts": {"hand-offs": len(done)}, "data": {"columns": ["Improvement", "Where it went", "Status", "Reference"], "rows": rows}}


# ------------------------------------------------------------------ Report: the monthly service report

def report(ctx: wb.Ctx) -> dict:
    rec = cx.read(ctx, "service") or {}
    imp = cx.read(ctx, "improve") or {"rows": [], "count": 0, "open": 0}
    t = rec.get("totals") or {}
    services = [[r["service"], r.get("support"), r.get("hours"), r.get("owner")] for r in ctx.records("catalogue") if r.get("include")]
    cx.put(ctx, "catalogue", {"count": len(services), "rows": services})
    S = "record:service"
    day = cx.iso_day(time.time())
    p1, f1 = cx.say("In " + str(rec.get("period")) + " the service desk resolved {r} tickets; {m} of the {d} with a due date were resolved by it, and {o} are still open past their due date.",
                    r=(t.get("resolved", 0), f"{S}#totals.resolved"), m=(t.get("met", 0), f"{S}#totals.met"), d=(t.get("with_due", 0), f"{S}#totals.with_due"), o=(t.get("open_late", 0), f"{S}#totals.open_late"))
    p2, f2 = cx.say("Relay grouped {g} ticket groups, {a} of them routed to an agent; Self-healing closed {h} cases and {i} data incidents were resolved.",
                    g=(t.get("groups", 0), f"{S}#totals.groups"), a=(t.get("routed_agent", 0), f"{S}#totals.routed_agent"), h=(t.get("heal_closed", 0), f"{S}#totals.heal_closed"),
                    i=(t.get("incidents_resolved", 0), f"{S}#totals.incidents_resolved"))
    p3, f3 = cx.say("{n} pieces of work were finished on Relay in the period; {k} improvement items are open.", n=(rec.get("delivered", 0), f"{S}#delivered"), k=(imp.get("open", 0), "record:improve#open"))
    team = rec.get("team") or {}
    p4, f4 = (cx.say("Agents worked {h} hours and people spent {p} hours deciding (Team & agents).", h=(team.get("agent_hours", 0), f"{S}#team.agent_hours"),
                     p=(team.get("people_hours", 0), f"{S}#team.people_hours")) if team else ("", []))
    blocks = [{"kind": "paragraph", "text": p1, "figures": f1}, {"kind": "paragraph", "text": p2, "figures": f2}, {"kind": "paragraph", "text": p3, "figures": f3}]
    if p4:
        blocks.append({"kind": "paragraph", "text": p4, "figures": f4})
    sections = [{"title": "The month in short", "blocks": blocks + nv.blocks(ctx, "In short")},
                {"title": "Service levels", "blocks": [{"kind": "table", "table": cx.table(["Priority", "Opened", "Resolved", "Met", "Breached", "Open past due", "Met %", "Median hours"],
                                                                                         rec.get("rows") or [["-"] * 8], f"{S}#rows", "Measured from the service desk's own tickets and due dates")},
                                                       {"kind": "paragraph", "text": rec.get("method") or ""}]},
                {"title": "What kept coming back", "blocks": [{"kind": "table", "table": cx.table(["Ticket group", "Tickets", "Priority", "Routed to", "Status"], rec.get("groups") or [["-"] * 5],
                                                                                                f"{S}#groups", "The service desk's largest ticket groups")}]},
                {"title": "What was delivered", "blocks": [{"kind": "table", "table": cx.table(["Module", "Work", "Kind"], rec.get("delivered_rows") or [["-"] * 3], f"{S}#delivered_rows",
                                                                                             "Work items finished on Relay in the period")}]},
                {"title": "Continuous improvement", "blocks": [{"kind": "table", "table": cx.table(["Improvement", "Owner", "Due", "Where it goes", "Status"], ch or [["-"] * 5], "record:improve#rows",
                                                                                                 "Agreed with the service owner")} for ch in cx.chunks(imp.get("rows") or [])]},
                {"title": "The service catalogue", "blocks": [{"kind": "table", "table": cx.table(["Service", "Support", "Hours", "Owner"], services or [["-"] * 4], "record:catalogue#rows",
                                                                                                "What is supported, by whom")}]}]
    doc = {"kind": "doc", "title": f"Service report: {ctx.title}"[:70], "subtitle": f"{rec.get('period')} - issued {day}", "audience": "the service owner and the client", "date": day, "sections": sections}
    a = cx.deliver(ctx, "service-report", doc, "Monthly service report")
    gates = [a["gate"], ctx.proof("sourced", label="Every figure of the report resolves to its record", figures=[{"label": x["text"], "value": x["value"], "source": x["source"]} for x in f1 + f2 + f3 + f4])]
    ok = a["ok"] and gates[-1]["status"] == "pass"
    return {"summary": ("The monthly service report passes every check - confirm it before it goes to the client." if ok else "The report did not pass its checks: " + "; ".join(a["problems"][:3])),
            "ok": ok, "counts": {"problems": len(a["problems"])}, "data": {"checks": gates}}


def _page_cards(u: dict) -> list[dict]:
    rows = db.q("SELECT id, title, status FROM wb_items WHERE module = ? ORDER BY updated DESC LIMIT 30", (MODULE,))
    vis = auth.access_map(u, [r["id"] for r in rows]) if u else {}
    out = []
    for r in rows:
        if r["id"] in vis:
            s = (wb._load(r["id"]).get("data") or {}).get("summary") or {}
            out.append([r["title"], wb.STATUS_LABEL.get(r["status"], r["status"]), s.get("period") or "-", f"{cx.num(s['met_pct'])} %" if s.get("met_pct") is not None else "-",
                        s.get("breached") if s.get("breached") is not None else "-", f"#/m/{MODULE}/i/{r['id']}"])
    return [{"title": "Services", "columns": ["Service", "Status", "Period", "Met", "Breached", "Open"], "rows": out, "empty": "No managed service yet."}]


GUIDE = """# Managed services & support - the work item

This folder is one managed service of Relay's Managed services & support module.

- `sources/service.json`: the period's service levels measured from the Service desk's tickets (by priority:
  resolved, met by the due date, breached, open past due, median hours), the ticket groups, Self-healing and data
  incidents, the work delivered and Team & agents' figures.
- `sources/improve.json`, `catalogue.json`: the agreed improvement items and the service catalogue.
- `service-report.yaml`: what the docs engine built (the same as `genbi doc build`).
- `narrative.yaml`: what you write when asked - a few paragraphs, every number declared with its `record:` source.

Never write a number the records do not hold."""


wb.register(wb.Pack(
    module=MODULE, guide=GUIDE, cards=_page_cards,
    lineage="none: a managed service reads the service desk and the platform's records; its hand-offs go through their own approvals",
    platforms={"servicedesk": DESK},
    schemas={"service": CAT_EDIT.columns, "improvement": IMP_EDIT.columns},
    work={"engage": wb.Work(
        title="Run what was delivered: the service catalogue, SLAs from the service desk, continuous improvement and the monthly service report",
        needs_source=False, sources=False, schedule_from="SLAs", journey=["Catalogue", "SLAs", "Improve", "Act", "Report"],
        steps={
            "Catalogue": wb.Step(kind="deterministic", run=catalogue, agent="Service cataloguer", edit=CAT_EDIT, confirm="the service catalogue - each service, who supports it, its hours and owner",
                                 text="One service for each thing this workspace runs on Relay, with the records behind it; you say who supports it, its hours and its owner"),
            "SLAs": wb.Step(kind="proof", run=slas, view="gates", agent="SLA reader", confirm=False,
                            text="Service levels from the Service desk's own tickets: by priority, resolved by the due date the service desk set, breached, open past due - with Self-healing and data incidents"),
            "Improve": wb.Step(kind="deterministic", run=improve, agent="Service improver", edit=IMP_EDIT, confirm="each improvement item, its owner, its due date and where it goes",
                               text="Improvement items from the records - ticket groups that keep coming back, breaches, cases and incidents left open - and your own"),
            "Act": wb.Step(kind="platform", run=act, agent="Dispatcher",
                           text="The approved hand-offs go out: a ticket through the service desk's own write approval, a Self-healing case; the rest is tracked here"),
            "Report": wb.Step(kind="deterministic", run=report, view="gates", agent="Service reporter", back_to="improve", confirm="the monthly service report before it goes to the client",
                              confirm_if=lambda ctx, out: out["ok"],
                              actions={"wording": nv.action(("service", "improve"), "Summarise the month for the service owner: service levels, what kept coming back, what improves next.",
                                                            agent="Service reporter", rebuild=lambda ctx: report(ctx))},
                              text="The monthly service report through the docs engine - every figure from the service record, checked")},
        fields=[wb.Field("period", "Report on", "select", options=PERIODS, default="30d"),
                wb.Field("sla_target_pct", "SLA attainment target (per cent)", "number", help="The share of tickets resolved by their due date you commit to; leave it empty to show the figures without judging them."),
                wb.Field("hours", "Support hours", "text", default="", help="e.g. Monday to Friday, 9 to 6"),
                wb.Field("repeat_min", "A ticket group with this many tickets is an improvement item", "number", default=3),
                wb.Field("template", "Template", "select", options=cx.template_options, default="relay")])}))
