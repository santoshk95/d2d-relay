"""Cost & licence optimisation (registry id `finops`) - what the licences and the cloud cost, what is not used, what
could be smaller, and a savings plan a named person approves; as a consulting engagement.

Engagement  Inventory -> Findings -> Savings -> Approve -> Act.
Inventory   the exports a person uploads, recognised by their own columns: Microsoft 365's Active users report, the
            Power BI activity log, UiPath Orchestrator's robot licences, Azure Cost Management's cost details and
            Azure Monitor's CPU averages, Snowflake's warehouse metering, SHOW WAREHOUSES and load history - and the
            tenant's own price list (contract prices: what the platform cannot know). Plus Relay's own AI cost from
            its usage records. Every line in each tool's own terms; a person keeps or drops lines.
Findings    rules first, with the person's thresholds (the wizard): licences not used for N days as of the exports'
            own date (activity from the Power BI log for Power BI licences, else the export's own activity
            columns); resources whose average utilisation is below the threshold with a smaller size in the price
            list (VMs: the price difference; warehouses: the credits saved by the size's credits per hour);
            resources that are idle (under 1 %): their whole cost. Each finding with its evidence; a saving only
            where the price list gives the prices - otherwise the person enters it with its source.
Savings     the savings plan - actions, monthly and yearly savings - and the savings plan document through the
            P11 docs engine, every figure sourced.
Approve     the named approver approves the plan (nothing is changed by Relay).
Act         each approved action goes to the people who make the change: a ticket through the service desk's own
            write approval (else the workbench joins a Service desk group or leaves a ticket draft).
"""
from __future__ import annotations

import csv
import io
import json
import re
import statistics
import time
from pathlib import Path

from .. import auth, db, registry
from .. import workbench as wb
from . import _consult as cx
from . import _narrative as nv

MODULE = "finops"
IDLE_PCT = 1.0                         # under this average utilisation a resource is idle: its whole cost is the saving (stated in the plan)
KINDS = {"unused": "Unused licences", "rightsize": "Smaller size", "idle": "Idle resource"}


class ExportsPlatform(wb.FilesPlatform):
    label = "Licence and cloud-cost exports"
    uploads = (".csv", ".xlsx")
    reads = ("exports you upload - Microsoft 365 Active users, the Power BI activity log, UiPath robot licences, Azure cost details and CPU, Snowflake "
             "metering, warehouses and load - and your price list; plus Relay's own AI cost. Copies in this work item's folder; nothing is changed anywhere")
    simulator = "tests/mocklab/finops_sim.py: the exports in each tool's own columns, with unused licences and oversized resources planted"


EXPORTS = ExportsPlatform()


def _rows(ctx: wb.Ctx, f: dict) -> list[dict]:
    p = ctx.dir / "data" / (f.get("table") or f["name"])
    try:
        text = p.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return []
    rd = csv.DictReader(io.StringIO(text))
    return [{(k or "").strip().lower(): (v or "").strip() for k, v in r.items()} for r in rd]


def _num(v) -> float | None:
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _day(v) -> float | None:
    s = str(v or "").strip()[:10]
    return cx.parse_day(s) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s) else None


def read_exports(ctx: wb.Ctx) -> dict:
    """Every upload recognised by its own columns -> {kind: rows, ...}, what was not recognised, the as-of date."""
    out = {"m365": [], "pbi": [], "uipath": [], "azure": [], "metrics": [], "sf_meter": [], "sf_wh": [], "sf_load": [], "prices": [], "files": {}, "unknown": []}
    for f in ctx.files((".csv", ".xlsx")):
        rows = _rows(ctx, f)
        if not rows:
            out["unknown"].append(f["name"])
            continue
        h = set(rows[0])
        kind = ("m365" if {"user principal name", "assigned products"} <= h else "pbi" if {"userid", "activity", "creationtime"} <= h
                else "uipath" if {"robot", "license", "last login"} <= h else "azure" if {"resourceid", "costinbillingcurrency"} <= h
                else "metrics" if {"resourceid", "metric", "value"} <= h else "sf_meter" if {"warehouse_name", "credits_used"} <= h
                else "sf_wh" if {"name", "size"} <= h else "sf_load" if {"warehouse_name", "avg_running"} <= h
                else "prices" if {"sku", "monthly price"} <= h else None)
        if not kind:
            out["unknown"].append(f["name"])
            continue
        out[kind] += rows
        out["files"].setdefault(kind, []).append(f["name"])
    return out


def _price_book(ex: dict) -> dict:
    book = {}
    for r in ex["prices"]:
        e = {"sku": r.get("sku"), "product": r.get("product") or r.get("sku"), "price": _num(r.get("monthly price")), "currency": r.get("currency") or "",
             "smaller": r.get("smaller sku") or "", "cph": _num(r.get("credits per hour"))}
        book[(e["sku"] or "").lower()] = e
        book[(e["product"] or "").lower()] = e
    return book


def _find_price(book: dict, *names: str) -> dict | None:
    for n in names:
        n = (n or "").strip().lower()
        if n and n in book:
            return book[n]
    for n in names:                                    # 'D8s v5' -> 'Azure VM D8s v5'
        n = (n or "").strip().lower()
        hit = next((e for k, e in book.items() if n and k.endswith(n)), None)
        if hit:
            return hit
    return None


# ------------------------------------------------------------------ Inventory

def inventory(ctx: wb.Ctx) -> dict:
    ex = read_exports(ctx)
    book = _price_book(ex)
    dates = [d for d in [_day(r.get("report refresh date")) for r in ex["m365"]] + [_day(r.get("date")) for r in ex["azure"]] + [_day(r.get("creationtime")) for r in ex["pbi"]] if d]
    as_of = max(dates) if dates else time.time()
    lines, users = [], {}
    # licences: who holds what, and when they last used it
    pbi_last: dict = {}
    for r in ex["pbi"]:
        d = _day(r.get("creationtime"))
        u = (r.get("userid") or "").lower()
        if d and u:
            pbi_last[u] = max(pbi_last.get(u, 0), d)
    for r in ex["m365"]:
        if str(r.get("is deleted") or "").lower() == "true":
            continue
        upn = (r.get("user principal name") or "").lower()
        acts = [d for k, v in r.items() if k.endswith("last activity date") for d in [_day(v)] if d]
        for prod in [p.strip() for p in (r.get("assigned products") or "").split("+") if p.strip()]:
            last = pbi_last.get(upn) if "power bi" in prod.lower() and ex["pbi"] else (max(acts) if acts else None)
            users.setdefault(prod.title() if prod.isupper() else prod, []).append({"who": upn, "last": last, "source": "m365"})
    for r in ex["uipath"]:
        users.setdefault(r.get("license") or "UiPath robot", []).append({"who": r.get("robot"), "last": _day(r.get("last login")), "source": "uipath"})
    for prod, us in users.items():
        pr = _find_price(book, prod)
        name = (pr or {}).get("product") or prod
        lines.append({"id": f"lic-{cx.slug(name)}", "kind": "licence", "item": name, "sku": (pr or {}).get("sku") or "", "count": len(us), "unit_price": (pr or {}).get("price"),
                      "monthly": round(len(us) * pr["price"], 2) if pr and pr.get("price") is not None else None, "currency": (pr or {}).get("currency") or "",
                      "holders": us, "from": "Microsoft 365 Active users" if us[0]["source"] == "m365" else "UiPath robot licences", "include": True})
    # Azure resources: cost over the export's days, CPU
    cpu = {}
    for r in ex["metrics"]:
        if "cpu" in (r.get("metric") or "").lower() and _num(r.get("value")) is not None:
            cpu[(r.get("resourceid") or "").lower()] = _num(r.get("value"))
    res: dict = {}
    for r in ex["azure"]:
        rid = r.get("resourceid") or ""
        x = res.setdefault(rid, {"cost": 0.0, "days": set(), "meter": r.get("metername") or "", "category": r.get("metercategory") or "", "currency": r.get("billingcurrency") or ""})
        x["cost"] += _num(r.get("costinbillingcurrency")) or 0
        if _day(r.get("date")):
            x["days"].add(_day(r.get("date")))
    for rid, x in res.items():
        days = max(1, len(x["days"]))
        name = rid.rstrip("/").split("/")[-1]
        pr = _find_price(book, x["meter"]) if x["category"].lower().startswith("virtual machine") else None
        lines.append({"id": f"res-{cx.slug(name)}", "kind": "resource", "item": name, "sku": (pr or {}).get("sku") or x["meter"], "count": 1, "unit_price": (pr or {}).get("price"),
                      "monthly": round(x["cost"] * 30 / days, 2), "currency": x["currency"], "utilisation": cpu.get(rid.lower()), "days": days,
                      "from": f"Azure cost details ({days} days)" + (", Azure Monitor CPU" if rid.lower() in cpu else ""), "include": True, "category": x["category"]})
    # Snowflake warehouses: credits over the export's days, size, load
    credit = _find_price(book, "snowflake_credit", "snowflake credit")
    size = {(r.get("name") or "").upper(): r.get("size") or "" for r in ex["sf_wh"]}
    load = {(r.get("warehouse_name") or "").upper(): _num(r.get("avg_running")) for r in ex["sf_load"]}
    whs: dict = {}
    for r in ex["sf_meter"]:
        w = whs.setdefault((r.get("warehouse_name") or "").upper(), {"credits": 0.0, "days": set()})
        w["credits"] += _num(r.get("credits_used")) or 0
        if _day(r.get("start_time")):
            w["days"].add(_day(r.get("start_time")))
    for wh, w in whs.items():
        days = max(1, len(w["days"]))
        credits_m = round(w["credits"] * 30 / days, 2)
        sz = size.get(wh, "")
        lines.append({"id": f"wh-{cx.slug(wh)}", "kind": "warehouse", "item": wh, "sku": f"SNOWFLAKE_WH_{sz.upper()}" if sz else "", "count": 1, "credits_month": credits_m,
                      "unit_price": (credit or {}).get("price"), "monthly": round(credits_m * credit["price"], 2) if credit and credit.get("price") is not None else None,
                      "currency": (credit or {}).get("currency") or "", "utilisation": round(load[wh] * 100, 1) if load.get(wh) is not None else None, "size": sz, "days": days,
                      "from": f"Snowflake metering ({days} days)" + (", load history" if wh in load else ""), "include": True})
    # Relay's own AI cost
    ai = db.one("SELECT COALESCE(SUM(cost_usd), 0) AS c FROM usage WHERE ts >= ?", (time.time() - 30 * cx.DAY,))["c"] or 0
    lines.append({"id": "relay-ai", "kind": "platform", "item": "Relay's AI runs (the last thirty days)", "sku": "", "count": 1, "unit_price": None, "monthly": round(float(ai), 2),
                  "currency": "USD", "from": "Relay's usage records", "include": True})
    rec = {"as_of": as_of, "as_of_day": cx.iso_day(as_of), "files": ex["files"], "unknown": ex["unknown"], "prices": [v for k, v in book.items() if k == (v["sku"] or "").lower()]}
    cx.put(ctx, "exports", rec)
    ctx.put("as_of", as_of)
    ctx.evidence("What the exports hold", {"rows": [{k: v for k, v in x.items() if k != "holders"} for x in lines], "files": ex["files"], "unknown": ex["unknown"]}, kind="inventory", ok=True)
    recs = cx.keep_edits(ctx, lines, ("include",))
    if not [x for x in lines if x["kind"] != "platform"]:
        raise wb.StepFailed("None of the uploads is a licence or cloud-cost export Relay recognises" + (f" ({', '.join(ex['unknown'])})" if ex["unknown"] else "")
                            + ": upload Microsoft 365 Active users, the Power BI activity log, UiPath robots, Azure cost details, Snowflake metering - and your price list.")
    return {"summary": f"{sum(1 for x in lines if x['kind'] == 'licence')} licence line(s), {sum(1 for x in lines if x['kind'] in ('resource', 'warehouse'))} resource(s) and Relay's AI cost, "
                       f"as of {rec['as_of_day']}" + (f"; not recognised: {', '.join(ex['unknown'])}" if ex["unknown"] else "") + (" - no price list, so no saving can be priced" if not ex["prices"] else "") + ".",
            "counts": {"licences": sum(x["count"] for x in lines if x["kind"] == "licence"), "resources": sum(1 for x in lines if x["kind"] in ("resource", "warehouse"))}, "records": recs,
            "data": {"columns": ["Keep", "Kind", "Item", "Count", "Monthly cost", "Utilisation %", "From"],
                     "rows": [["yes" if x.get("include") else "no", x["kind"], x["item"], x["count"], x.get("monthly"), x.get("utilisation"), x["from"]] for x in recs]}}


INV_EDIT = wb.Edit(columns=[wb.Column("include", "Keep", "bool"), wb.Column("kind", "Kind", readonly=True), wb.Column("item", "Item", readonly=True), wb.Column("count", "Count", "number", readonly=True),
                            wb.Column("monthly", "Monthly cost", "number", readonly=True), wb.Column("utilisation", "Utilisation %", "number", readonly=True), wb.Column("from", "From", readonly=True)],
                   add=False, remove=False, label="line")


# ------------------------------------------------------------------ Findings

def findings(ctx: wb.Ctx) -> dict:
    ex = read_exports(ctx)
    book = _price_book(ex)
    idle_days = float(ctx.scope.get("idle_days") or 90)
    low = float(ctx.scope.get("low_util_pct") or 20)
    as_of = float(ctx.get("as_of") or time.time())
    lines = {x["id"]: x for x in ctx.records("inventory") if x.get("include")}
    found = []
    for x in lines.values():
        if x["kind"] == "licence":
            idle = [h for h in x.get("holders") or [] if not h.get("last") or (as_of - h["last"]) / cx.DAY >= idle_days]
            if idle:
                price = x.get("unit_price")
                found.append({"id": f"unused-{x['id']}", "kind": "unused", "item": x["item"], "count": len(idle),
                              "what": f"Remove {len(idle)} unused {x['item']} licence(s)", "evidence": f"{len(idle)} of {x['count']} holders show no activity in {cx.num(idle_days)} days as of the exports' date",
                              "who": ", ".join(h["who"] for h in idle[:12]) + (" ..." if len(idle) > 12 else ""),
                              "saving": round(len(idle) * price, 2) if price is not None else None, "saving_source": f"price list: {x['item']} at {cx.num(price, 2)} per month × {len(idle)}" if price is not None else "",
                              "currency": x.get("currency") or ""})
        elif x["kind"] == "resource" and x.get("utilisation") is not None:
            if x["utilisation"] < IDLE_PCT:
                found.append({"id": f"idle-{x['id']}", "kind": "idle", "item": x["item"], "count": 1, "what": f"Stop or remove {x['item']}",
                              "evidence": f"average CPU {cx.num(x['utilisation'], 1)} % over {x.get('days')} days", "saving": x["monthly"],
                              "saving_source": f"its own cost in the export: {cx.num(x['monthly'], 2)} per month", "currency": x.get("currency") or ""})
            elif x["utilisation"] < low:
                cur = _find_price(book, x.get("sku") or "")
                small = _find_price(book, (cur or {}).get("smaller") or "") if cur and cur.get("smaller") else None
                saving = round(x["monthly"] - small["price"], 2) if small and small.get("price") is not None else None
                found.append({"id": f"size-{x['id']}", "kind": "rightsize", "item": x["item"], "count": 1, "what": f"Resize {x['item']} to {(small or {}).get('product') or 'a smaller size'}",
                              "evidence": f"average CPU {cx.num(x['utilisation'], 1)} % over {x.get('days')} days (threshold {cx.num(low)} %)", "saving": saving,
                              "saving_source": f"its cost {cx.num(x['monthly'], 2)} less the price list's {small['product']} at {cx.num(small['price'], 2)}" if saving is not None else "",
                              "currency": x.get("currency") or ""})
        elif x["kind"] == "warehouse" and x.get("utilisation") is not None and x["utilisation"] < low:
            cur = _find_price(book, x.get("sku") or "")
            small = _find_price(book, (cur or {}).get("smaller") or "") if cur and cur.get("smaller") else None
            credit = _find_price(book, "snowflake_credit", "snowflake credit")
            saving = None
            if small and cur and cur.get("cph") and small.get("cph") is not None and credit and credit.get("price") is not None:
                saving = round(x["credits_month"] * (1 - small["cph"] / cur["cph"]) * credit["price"], 2)
            found.append({"id": f"size-{x['id']}", "kind": "rightsize", "item": x["item"], "count": 1, "what": f"Resize {x['item']} from {x.get('size')} to {(small or {}).get('product') or 'a smaller size'}",
                          "evidence": f"average running {cx.num(x['utilisation'], 1)} % of the time over {x.get('days')} days (threshold {cx.num(low)} %)", "saving": saving,
                          "saving_source": (f"{cx.num(x['credits_month'], 2)} credits a month × (1 - {cx.num(small['cph'])} ÷ {cx.num(cur['cph'])} credits per hour) × "
                                            f"{cx.num(credit['price'], 2)} per credit, from the price list") if saving is not None else "", "currency": (credit or {}).get("currency") or ""})
    for f in found:
        f.update(decision="keep", origin="relay")
    recs = cx.keep_edits(ctx, found, ("decision", "saving", "saving_source"))
    priced = [r for r in recs if r.get("saving") not in (None, "")]
    return {"summary": f"{len(recs)} finding(s): {sum(1 for r in recs if r['kind'] == 'unused')} on unused licences, {sum(1 for r in recs if r['kind'] == 'rightsize')} on sizes, "
                       f"{sum(1 for r in recs if r['kind'] == 'idle')} idle - {len(priced)} priced from your price list. Keep or ignore each; enter a saving with its source where Relay has no price.",
            "counts": {"findings": len(recs), "priced": len(priced)}, "records": recs,
            "items": [f"{r['what']}: {r['evidence']}" for r in recs][:8],
            "data": {"columns": ["Kind", "Finding", "Evidence", "Saving per month", "Where the saving comes from"],
                     "rows": [[KINDS.get(r["kind"], r["kind"]), r["what"], r["evidence"], r.get("saving"), r.get("saving_source") or "-"] for r in recs]}}


def _find_validate(recs: list[dict], ctx: wb.Ctx) -> list[str]:
    probs = []
    for r in recs:
        if r.get("decision") != "keep":
            continue
        s = r.get("saving")
        if s in (None, ""):
            probs.append(f"{r['what']}: Relay has no price for it - enter the saving per month and where it comes from, or ignore it.")
            continue
        try:
            if float(s) < 0:
                probs.append(f"{r['what']}: a saving is zero or more.")
        except (TypeError, ValueError):
            probs.append(f"{r['what']}: the saving is a number.")
        if not str(r.get("saving_source") or "").strip():
            probs.append(f"{r['what']}: where does the saving come from? A number without a source is not a finding.")
    from .delivery import _text_problems
    return probs + _text_problems(recs, ("saving_source",))


FIND_EDIT = wb.Edit(columns=[wb.Column("decision", "Decision", "select", options=(("keep", "Keep"), ("ignore", "Ignore"))), wb.Column("what", "Finding", readonly=True),
                             wb.Column("evidence", "Evidence", readonly=True), wb.Column("saving", "Saving per month", "number"),
                             wb.Column("saving_source", "Where the saving comes from")], add=False, remove=False, validate=_find_validate, label="finding")


# ------------------------------------------------------------------ Savings: the plan and its document

def savings(ctx: wb.Ctx) -> dict:
    kept = [r for r in ctx.records("findings") if r.get("decision") == "keep"]
    cur = next((r.get("currency") for r in kept if r.get("currency")), "")
    acts = [{"what": r["what"], "kind": KINDS.get(r["kind"], r["kind"]), "evidence": r["evidence"], "saving": round(float(r["saving"]), 2), "source": r["saving_source"], "who": r.get("who") or ""} for r in kept]
    month = round(sum(a["saving"] for a in acts), 2)
    rec = {"currency": cur, "actions": acts, "count": len(acts), "monthly": month, "yearly": round(month * 12, 2), "as_of": cx.iso_day(ctx.get("as_of")),
           "by_kind": {k: round(sum(a["saving"] for a in acts if a["kind"] == v), 2) for k, v in KINDS.items()},
           "rows": [[a["kind"], a["what"], a["evidence"], cx.money(a["saving"], cur), a["source"]] for a in acts]}
    cx.put(ctx, "savings", rec)
    S = "record:savings"
    p1, f1 = cx.say("{n} actions save {m} a month, {y} a year, as of the exports of " + rec["as_of"] + ".", n=(len(acts), f"{S}#count"), m=(month, f"{S}#monthly", f"money:{cur}"),
                    y=(rec["yearly"], f"{S}#yearly", f"money:{cur}"))
    p2, f2 = cx.say("Unused licences {u}, smaller sizes {r}, idle resources {i} a month.", u=(rec["by_kind"]["unused"], f"{S}#by_kind.unused", f"money:{cur}"),
                    r=(rec["by_kind"]["rightsize"], f"{S}#by_kind.rightsize", f"money:{cur}"), i=(rec["by_kind"]["idle"], f"{S}#by_kind.idle", f"money:{cur}"))
    day = cx.iso_day(time.time())
    doc = {"kind": "doc", "title": f"Savings plan: {ctx.title}"[:70], "subtitle": f"Cost & licence optimisation - {day}", "audience": "the budget holder and the approver", "date": day,
           "sections": [{"title": "The savings", "blocks": [{"kind": "paragraph", "text": p1, "figures": f1}, {"kind": "paragraph", "text": p2, "figures": f2}] + nv.blocks(ctx, "In short")},
                        {"title": "The actions", "blocks": [{"kind": "table", "table": cx.table(["Kind", "Action", "Evidence", "Saving per month", "Where the saving comes from"], ch or [["-"] * 5],
                                                                                              f"{S}#rows", "Each action with its evidence and the source of its saving")} for ch in cx.chunks(rec["rows"])]},
                        {"title": "Method", "blocks": [{"kind": "bullets", "bullets": ["Licences: not used for the number of days the engagement set, as of the exports' own date.",
                                                                                      "Sizes: average utilisation under the engagement's threshold, priced at the next smaller size of your price list.",
                                                                                      "Idle: average utilisation under one per cent; the saving is the resource's own cost.",
                                                                                      "A year is twelve months of the monthly saving; nothing is changed until the people who own the platforms make the change."]}]}]}
    a = cx.deliver(ctx, "savings-plan", doc, "Savings plan")
    gates = [a["gate"], ctx.proof("sourced", label="Every figure of the plan resolves to the savings record", figures=[{"label": x["text"], "value": x["value"], "source": x["source"]} for x in f1 + f2])]
    ctx.put("summary", {"monthly": month, "yearly": rec["yearly"], "currency": cur, "actions": len(acts), "when": time.time()})
    ok = a["ok"] and gates[-1]["status"] == "pass"
    return {"summary": (f"{len(acts)} action(s), {cx.money(month, cur)} a month - the savings plan passes every check." if ok else "The savings plan did not pass its checks: " + "; ".join(a["problems"][:3])),
            "ok": ok, "counts": {"actions": len(acts), "monthly": month}, "data": {"checks": gates}}


def approve(ctx: wb.Ctx) -> dict:
    rec = cx.read(ctx, "savings") or {}
    cur = rec.get("currency") or ""
    return {"summary": f"Approve the savings plan: {rec.get('count', 0)} action(s), {cx.money(rec.get('monthly', 0), cur)} a month. Relay changes nothing: approved actions go to the people who make the change.",
            "data": {"items": [{"title": a["what"], "detail": a["evidence"], "effort": cx.money(a["saving"], cur) + " a month"} for a in rec.get("actions") or []],
                     "total": f"{cx.money(rec.get('monthly', 0), cur)} a month - {cx.money(rec.get('yearly', 0), cur)} a year", "note": "The savings plan document is in the outputs."}}


def act(ctx: wb.Ctx) -> dict:
    from .. import itsm
    rec = cx.read(ctx, "savings") or {}
    cur = rec.get("currency") or ""
    target = itsm.ticket_target() if "itsm_sources" in db.tables() else None
    rows = []
    for i, a in enumerate(rec.get("actions") or []):
        body = f"{a['what']}\n\nEvidence: {a['evidence']}\nSaving: {cx.money(a['saving'], cur)} a month ({a['source']})\n" + (f"Who: {a['who']}\n" if a.get("who") else "") + f"Work item: {wb.route_of(ctx.st)}"
        if target:
            try:
                w = itsm.request_write(target["id"], "create", {"title": a["what"][:200], "description": body, "priority": "P3", "labels": ["cost-saving"]},
                                       who=ctx.who or ctx.owner, module=registry.BY_ID[MODULE]["name"], origin=f"wb:{ctx.id}:{i}", link=wb.route_of(ctx.st))
                h = ctx._handoff({"kind": "ticket", "label": a["what"], "checkpoint": w.get("checkpoint_id"), "status": "awaiting the service desk's write approval", "link": "#/validate", "via": target["name"]})
            except itsm.WriteRefused as e:
                h = ctx.ticket(a["what"], body, priority="P3", about=a["what"])
                h = {**h, "status": f"{h.get('status')} ({str(e)[:80]})"}
        else:
            h = ctx.ticket(a["what"], body, priority="P3", about=a["what"])
        rows.append([a["what"], h.get("status"), h.get("checkpoint") or h.get("output") or h.get("group") or ""])
    return {"summary": f"{len(rows)} action(s) handed to the people who make the change - each through its own approval.", "counts": {"hand-offs": len(rows)},
            "data": {"columns": ["Action", "Status", "Reference"], "rows": rows}}


def _page_cards(u: dict) -> list[dict]:
    rows = db.q("SELECT id, title, status FROM wb_items WHERE module = ? ORDER BY updated DESC LIMIT 30", (MODULE,))
    vis = auth.access_map(u, [r["id"] for r in rows]) if u else {}
    out = []
    for r in rows:
        if r["id"] in vis:
            s = (wb._load(r["id"]).get("data") or {}).get("summary") or {}
            out.append([r["title"], wb.STATUS_LABEL.get(r["status"], r["status"]), s.get("actions", "-"), cx.money(s["monthly"], s.get("currency")) if s.get("monthly") is not None else "-",
                        cx.money(s["yearly"], s.get("currency")) if s.get("yearly") is not None else "-", f"#/m/{MODULE}/i/{r['id']}"])
    return [{"title": "Savings plans", "columns": ["Engagement", "Status", "Actions", "A month", "A year", "Open"], "rows": out, "empty": "No savings plan yet."}]


GUIDE = """# Cost & licence optimisation - the work item

This folder is one engagement of Relay's Cost & licence optimisation module.

- `data/`: the exports the person uploaded (Microsoft 365 Active users, the Power BI activity log, UiPath robots,
  Azure cost details and CPU, Snowflake metering, warehouses and load) and their price list.
- `sources/exports.json`, `savings.json`: what was read and the savings plan (every action with its evidence and
  the source of its saving).
- `narrative.yaml`: what you write when asked - a few paragraphs, every number declared with its `record:` source.

Never write a price, a saving or a count the records do not hold."""


wb.register(wb.Pack(
    module=MODULE, guide=GUIDE, cards=_page_cards,
    lineage="none: an optimisation reads exports and changes nothing; approved actions go out as tickets",
    platforms={"exports": EXPORTS},
    schemas={"line": INV_EDIT.columns, "finding": FIND_EDIT.columns},
    work={"engage": wb.Work(
        title="Find unused licences and oversized resources in your exports, and a savings plan a named person approves",
        journey=["Inventory", "Findings", "Savings", "Approve", "Act"],
        steps={
            "Inventory": wb.Step(kind="platform", run=inventory, agent="Licence reader", edit=INV_EDIT, confirm="what was read - licences and resources, in each tool's own terms",
                                 text="Your exports recognised by their own columns, with your price list and Relay's own AI cost; you keep or drop lines"),
            "Findings": wb.Step(kind="deterministic", run=findings, agent="Cost analyst", edit=FIND_EDIT, confirm="each finding with its evidence and the source of its saving",
                                text="Unused licences, smaller sizes and idle resources by your thresholds - each with its evidence, priced from your price list"),
            "Savings": wb.Step(kind="deterministic", run=savings, view="gates", agent="Savings planner", confirm=False,
                               actions={"wording": nv.action(("savings", "exports"), "Explain the savings plan for the budget holder: what is not used, what could be smaller, what it saves.",
                                                             agent="Savings planner", rebuild=lambda ctx: savings(ctx))},
                               text="The savings plan - actions, monthly and yearly savings - and its document through the docs engine, every figure sourced"),
            "Approve": wb.Step(kind="person", run=approve, view="plan", approver=True, confirm="the savings plan - nothing is changed until the owners make the change",
                               text="The named approver approves the savings plan"),
            "Act": wb.Step(kind="platform", run=act, agent="Dispatcher", text="Each approved action goes to the people who make the change, as a ticket through the service desk's own approval")},
        fields=[wb.Field("idle_days", "A licence not used for this many days is unused", "number", required=True, default=90),
                wb.Field("low_util_pct", "Under this average utilisation (per cent) a resource could be smaller", "number", required=True, default=20),
                wb.Field("template", "Template", "select", options=cx.template_options, default="relay")])}))
