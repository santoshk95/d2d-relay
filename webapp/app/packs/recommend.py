"""Suggestions & recommendations (registry id `recommend`) - what to do next, with reasons: explainable next-best
actions from the tenant's own numbers, each with its evidence and expected impact, sent to the person who should act
and tracked until they accept or decline it.

What existed: Ask D suggests next actions with each answer (askd.py, `actions` in every answer). This module reads
those suggestions as signals too, and adds the rest from the data:
  metric_change  a metric's latest period against the same period a year before (else the period before), and the
                 group that drives the change (predict_data: uploads, warehouses, a dashboard's data)
  forecast       a live forecast (Predictive analytics) that falls or rises over its horizon
  anomaly        an unusual number found by Anomaly & risk detection
  askd           an action Ask D suggested with one of the owner's answers
A playbook (rules, versioned) turns each signal into a suggestion: what to do, why - the numbers behind it - and the
expected impact; nothing is suggested without a signal and its numbers.
Develop  Signals -> Explain -> Suggest -> Assign -> Track: the signals read, explained in plain words, the suggestions
         confirmed by a person, the owners confirmed before anything is sent, then each sent suggestion is a
         checkpoint in its owner's Validation queue - accept, or decline with a reason - and the outcome is tracked.
Change   Request -> Diagnose -> Fix -> Prove -> Approve -> Learn: the playbook edited, dry-run on today's signals.
Run      Watch -> Alert -> Fix -> Approve -> Report: new signals on a schedule, the outcomes so far (the acceptance rate
         per rule), new suggestions only after a person confirms them."""
from __future__ import annotations

import json
import secrets as _secrets
import time

from .. import auth, checkpoints, db, notify, registry, store
from .. import workbench as wb
from . import predict_data as pdat

MODULE = "recommend"
KIND = "recommend.suggestion"
SIGNALS = {"metric_change": "A metric moved", "forecast": "A forecast moves", "anomaly": "An unusual number", "askd": "Ask D suggested it"}
DEFAULT_RULES = [
    {"id": "drop", "signal": "metric_change", "when": "down", "min_change": 10, "priority": "high", "on": True,
     "action": "Review the fall in {metric}: {change} against {base}; most of it is {group}. Agree a recovery plan with its owner.",
     "impact": "recovering half of the gap: {half_gap}"},
    {"id": "rise", "signal": "metric_change", "when": "up", "min_change": 15, "priority": "medium", "on": True,
     "action": "Plan for the rise in {metric}: {change} against {base}, led by {group}. Check capacity and stock for it.",
     "impact": "the extra {gap} a period if it holds"},
    {"id": "forecast-down", "signal": "forecast", "when": "down", "min_change": 5, "priority": "high", "on": True,
     "action": "Act before {period}: the forecast for {metric} falls {change} over the next periods.", "impact": "the forecast gap: {gap}"},
    {"id": "forecast-up", "signal": "forecast", "when": "up", "min_change": 10, "priority": "medium", "on": True,
     "action": "Prepare for {period}: the forecast for {metric} rises {change}.", "impact": "{gap} more over the horizon"},
    {"id": "anomaly", "signal": "anomaly", "when": "any", "min_change": 0, "priority": "high", "on": True,
     "action": "Check the unusual {metric} at {period}: {reason}.", "impact": "the difference from what was expected: {gap}"},
    {"id": "askd", "signal": "askd", "when": "any", "min_change": 0, "priority": "low", "on": True,
     "action": "{text}", "impact": "as Ask D's answer showed: {headline}"}]

db.register_schema("""
CREATE TABLE IF NOT EXISTS recommend_playbooks (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, item TEXT, version INTEGER NOT NULL DEFAULT 1, rules TEXT NOT NULL DEFAULT '[]', run_item TEXT, owner_id TEXT,
  published_by TEXT, published REAL, status TEXT NOT NULL DEFAULT 'live', created REAL NOT NULL, updated REAL NOT NULL);
CREATE TABLE IF NOT EXISTS recommend_suggestions (
  id TEXT PRIMARY KEY, playbook TEXT, item TEXT, rule TEXT, signal TEXT, fingerprint TEXT NOT NULL, title TEXT NOT NULL, action TEXT NOT NULL, why TEXT, impact TEXT,
  evidence TEXT NOT NULL DEFAULT '{}', assignee TEXT, status TEXT NOT NULL DEFAULT 'sent', checkpoint TEXT, comment TEXT, decided_by TEXT, decided REAL,
  created REAL NOT NULL, updated REAL NOT NULL);
CREATE INDEX IF NOT EXISTS recommend_suggestions_fp ON recommend_suggestions (fingerprint, status);
""")

FILES = wb.FilesPlatform()
WAREHOUSE = wb.WarehousePlatform()
PLATFORMS = {"files": FILES, "warehouse": WAREHOUSE, "dashboards": pdat.DASHBOARDS}


# ------------------------------------------------------------------ playbooks and suggestions

def playbook(pid: str, u: dict | None = None) -> dict | None:
    r = db.one("SELECT * FROM recommend_playbooks WHERE id = ?", (pid,))
    if not r or (u is not None and r.get("item") and not auth.can_project(u, "view", db.project(r["item"]))):
        return None
    return {**r, "rules": pdat.j(r["rules"], [])}


def playbooks(u: dict) -> list[dict]:
    return [p for p in (playbook(r["id"], u) for r in db.q("SELECT id FROM recommend_playbooks WHERE status = 'live' ORDER BY updated DESC")) if p]


def playbook_options(u: dict) -> list[tuple[str, str]]:
    return [(p["id"], f"{p['name']} - version {p['version']} - {len(p['rules'])} rules") for p in playbooks(u)]


def publish(ctx: wb.Ctx, rules: list[dict], pid: str | None = None) -> dict:
    now, who = time.time(), ctx.who or ctx.owner
    if pid and db.one("SELECT 1 FROM recommend_playbooks WHERE id = ?", (pid,)):
        db.run("UPDATE recommend_playbooks SET version = version + 1, rules = ?, published_by = ?, published = ?, updated = ? WHERE id = ?", (json.dumps(rules), who, now, now, pid))
    else:
        pid = "rpb-" + _secrets.token_hex(4)
        db.run("INSERT INTO recommend_playbooks (id, name, item, version, rules, owner_id, published_by, published, status, created, updated) VALUES (?, ?, ?, 1, ?, ?, ?, ?, 'live', ?, ?)",
               (pid, ctx.title[:160], ctx.id, json.dumps(rules), ctx.owner, who, now, now, now))
    db.audit("recommend.playbook.publish", pid, {"rules": len(rules), "item": ctx.id}, who)
    return playbook(pid)


def outcomes(pid: str | None = None, item: str | None = None) -> dict:
    """Sent, accepted, declined and still open - overall and per rule (the learning loop)."""
    if pid or item:
        rows = db.q("SELECT rule, status, COUNT(*) AS n FROM recommend_suggestions WHERE " + ("playbook = ?" if pid else "item = ?") + " GROUP BY rule, status", (pid or item,))
    else:
        rows = db.q("SELECT rule, status, COUNT(*) AS n FROM recommend_suggestions GROUP BY rule, status")
    out = {"sent": 0, "accepted": 0, "declined": 0, "open": 0, "rules": {}}
    for r in rows:
        k = "open" if r["status"] == "sent" else r["status"]
        out[k] = out.get(k, 0) + r["n"]
        out["sent"] += r["n"]
        out["rules"].setdefault(r["rule"], {"sent": 0, "accepted": 0, "declined": 0, "open": 0})
        out["rules"][r["rule"]][k] = out["rules"][r["rule"]].get(k, 0) + r["n"]
        out["rules"][r["rule"]]["sent"] += r["n"]
    decided = out["accepted"] + out["declined"]
    out["acceptance"] = round(100.0 * out["accepted"] / decided, 1) if decided else None
    return out


# ------------------------------------------------------------------ signals (rules over the data and over what other modules found)

def _pct(a: float, b: float) -> float | None:
    return None if not b else round(100.0 * (a - b) / abs(b), 1)


def metric_signals(ctx: wb.Ctx, dsets: list[dict]) -> list[dict]:
    out = []
    for d in dsets:
        cols = pdat.columns(ctx, d["ref"])
        dates, nums, texts = pdat.kind_cols(cols)
        value = pdat._cname(cols, ctx.scope.get("value") or "") or pdat.best_value(nums)
        if not dates or not value:
            continue
        date = dates[0]
        p, y = pdat.series(ctx, d["ref"], date, value, "month", "sum")
        if len(p) < 2:
            continue
        i_base = len(p) - 13 if len(p) >= 13 else len(p) - 2
        latest, base = y[-1], y[i_base]
        ch = _pct(latest, base)
        if ch is None:
            continue
        by = pdat._cname(cols, ctx.scope.get("by") or "") or next((t for t in texts if 1 < len(pdat.distinct(ctx, d["ref"], t, 13)) <= 12), None)
        parts = []
        if by:
            for g in pdat.distinct(ctx, d["ref"], by, 13)[:12]:
                gp, gy = pdat.series(ctx, d["ref"], date, value, "month", "sum", {"column": by, "value": g})
                gm = dict(zip(gp, gy))
                parts.append({"group": g, "latest": gm.get(p[-1], 0.0), "base": gm.get(p[i_base], 0.0)})
            for x in parts:
                x["change"] = x["latest"] - x["base"]
        gap = latest - base
        top = max(parts, key=lambda x: abs(x["change"]) if (x["change"] < 0) == (gap < 0) else -1) if parts else None
        out.append({"fingerprint": f"metric:{d['key']}:{value}:{p[-1]}", "signal": "metric_change", "dataset": d["name"], "metric": value, "period": p[-1], "base": p[i_base],
                    "latest": latest, "base_value": base, "change_pct": ch, "gap": gap, "group": f"{by} {top['group']} ({pdat.fmt(top['change'])})" if top else "spread across the whole",
                    "parts": parts, "direction": "down" if gap < 0 else "up",
                    "explain": f"{value} was {pdat.fmt(latest)} in {p[-1]} against {pdat.fmt(base)} in {p[i_base]} ({ch:+.1f} %)" + (f"; the biggest part is {by} {top['group']}: {pdat.fmt(top['change'])}" if top else "")})
    return out


def forecast_signals(u: dict) -> list[dict]:
    out = []
    try:
        from . import predict
        fcs = predict.forecasts(u)
    except Exception:  # noqa: BLE001 - forecasting not in this workspace
        return out
    for f in fcs:
        per: dict = {}
        for x in f["output"]:
            per.setdefault(x["series"], []).append((x["period"], float(x["forecast"])))
        for series, pts in per.items():
            pts.sort()
            if len(pts) < 2:
                continue
            a, b = pts[0][1], pts[-1][1]
            ch = _pct(b, a)
            if ch is None:
                continue
            out.append({"fingerprint": f"forecast:{f['id']}:v{f['version']}:{series}", "signal": "forecast", "dataset": f["name"], "metric": series, "period": pts[-1][0], "base": pts[0][0],
                        "latest": b, "base_value": a, "change_pct": ch, "gap": b - a, "direction": "down" if b < a else "up", "group": "",
                        "explain": f"the forecast \"{f['name']}\" for {series} goes from {pdat.fmt(a)} in {pts[0][0]} to {pdat.fmt(b)} in {pts[-1][0]} ({ch:+.1f} %)"})
    return out


def anomaly_signals(u: dict) -> list[dict]:
    out = []
    try:
        from . import anomaly
        sets = anomaly.dsets(u)
    except Exception:  # noqa: BLE001
        return out
    for s in sets:
        for fnd in db.q("SELECT * FROM anomaly_findings WHERE set_id = ? AND status IN ('new', 'alerted', 'ticketed') ORDER BY created DESC LIMIT 20", (s["id"],)):
            exp = fnd.get("expected") or ""
            out.append({"fingerprint": f"anomaly:{fnd['id']}", "signal": "anomaly", "dataset": fnd["dataset"], "metric": fnd["dataset"], "period": fnd["at"], "base": "", "latest": fnd["value"],
                        "base_value": None, "change_pct": None, "gap": None, "direction": "any", "group": "", "reason": fnd["reason"], "expected": exp,
                        "explain": f"Anomaly & risk detection found {fnd['reason']} ({fnd['dataset']}, {fnd['at']})"})
    return out


def askd_signals(uid: str, limit: int = 20) -> list[dict]:
    """What Ask D already suggested with the owner's answers (the module's starting point: 'In Ask D today')."""
    out = []
    for m in db.q("SELECT m.id, m.body, m.created, t.title FROM askd_messages m JOIN askd_threads t ON t.id = m.thread_id WHERE t.user_id = ? AND m.role = 'assistant' "
                  "ORDER BY m.created DESC LIMIT ?", (uid, limit)):
        body = pdat.j(m["body"], {})
        for i, a in enumerate(body.get("actions") or []):
            out.append({"fingerprint": f"askd:{m['id']}:{i}", "signal": "askd", "dataset": "Ask D", "metric": m["title"], "period": time.strftime("%Y-%m-%d", time.gmtime(m["created"])),
                        "base": "", "latest": None, "base_value": None, "change_pct": None, "gap": None, "direction": "any", "group": "", "text": str(a)[:300],
                        "headline": (body.get("result") or {}).get("headline") or "", "summary": body.get("summary") or "", "message": m["id"],
                        "explain": f"Ask D answered \"{m['title']}\" with {((body.get('result') or {}).get('headline') or 'its numbers')} and suggested: {str(a)[:200]}"})
    return out


def gather(ctx: wb.Ctx) -> list[dict]:
    sc = ctx.scope
    u = db.user(ctx.owner or "") or {}
    sig = metric_signals(ctx, ctx.get("datasets") or [])
    if sc.get("forecasts", True) not in (False, "false", 0):
        sig += forecast_signals(u)
    if sc.get("anomalies", True) not in (False, "false", 0):
        sig += anomaly_signals(u)
    if sc.get("askd", True) not in (False, "false", 0):
        sig += askd_signals(ctx.owner or "")
    return sig


# ------------------------------------------------------------------ the playbook: signals into suggestions

class _Safe(dict):
    def __missing__(self, k):
        return "-"


def apply(rules: list[dict], signals: list[dict]) -> list[dict]:
    """Each signal through the first rule that fits it (kind, direction, size of the change): one suggestion each, with
    its numbers. A signal no rule takes is not suggested."""
    out = []
    for s in signals:
        for r in rules:
            if not r.get("on") or r.get("signal") != s["signal"]:
                continue
            if r.get("when") in ("down", "up") and s.get("direction") != r["when"]:
                continue
            if s.get("change_pct") is not None and abs(s["change_pct"]) < float(r.get("min_change") or 0):
                continue
            gap = s.get("gap")
            vals = _Safe(metric=s.get("metric"), change=f"{s['change_pct']:+.1f} %" if s.get("change_pct") is not None else "-", base=s.get("base") or "-", period=s.get("period") or "-",
                         group=s.get("group") or "-", gap=pdat.fmt(abs(gap)) if gap is not None else "-", half_gap=pdat.fmt(abs(gap) / 2) if gap is not None else "-",
                         reason=s.get("reason") or "", text=s.get("text") or "", headline=s.get("headline") or "")
            try:
                action = str(r.get("action") or "").format_map(vals)
                impact = str(r.get("impact") or "").format_map(vals)
            except (ValueError, KeyError):
                continue
            out.append({"id": "sg-" + pdat.slug(s["fingerprint"], 60), "fingerprint": s["fingerprint"], "rule": r["id"], "signal": s["signal"], "include": True,
                        "title": f"{SIGNALS[s['signal']]}: {s.get('metric')}"[:160], "action": action[:600], "why": s["explain"][:600], "impact": impact[:200],
                        "priority": r.get("priority") or "medium", "assignee": "", "route": "queue", "evidence_rows": s.get("parts") or [], "signal_data": {k: s.get(k) for k in ("dataset", "metric", "period", "base", "latest", "base_value", "change_pct", "message")}})
            break
    order = {"high": 0, "medium": 1, "low": 2}
    return sorted(out, key=lambda x: order.get(x["priority"], 3))


def _people(ctx: wb.Ctx):
    return [("", "Choose who acts")] + [(r["id"], r["name"]) for r in db.q("SELECT id, name FROM users WHERE active = 1 ORDER BY name")]


def _validate(recs: list[dict], ctx: wb.Ctx) -> list[str]:
    probs = []
    for i, r in enumerate(recs, 1):
        if not r.get("include"):
            continue
        if not str(r.get("action") or "").strip():
            probs.append(f"Row {i}: say what to do")
        if ctx.step_id in ("assign", "fix") and not db.user(r.get("assignee") or ""):
            probs.append(f"Row {i}: choose who should act")
    if not any(r.get("include") for r in recs):
        probs.append("Keep at least one suggestion.")
    return probs


SUG_COLUMNS = [wb.Column("include", "Send", "bool"), wb.Column("title", "Suggestion", readonly=True), wb.Column("action", "What to do", "longtext"),
               wb.Column("why", "Why - the numbers", readonly=True), wb.Column("impact", "Expected impact", readonly=True),
               wb.Column("priority", "Priority", "select", options=(("high", "High"), ("medium", "Medium"), ("low", "Low")))]
SUG_EDIT = wb.Edit(columns=SUG_COLUMNS, add=False, remove=True, validate=_validate, label="suggestion")
ASSIGN_COLUMNS = [wb.Column("include", "Send", "bool"), wb.Column("title", "Suggestion", readonly=True), wb.Column("assignee", "Who should act", "select", options=_people),
                  wb.Column("route", "How", "select", options=(("queue", "Their Validation queue"), ("ticket", "A ticket (service desk)"))), wb.Column("action", "What to do", readonly=True)]
ASSIGN_EDIT = wb.Edit(columns=ASSIGN_COLUMNS, add=False, remove=False, validate=_validate, label="suggestion")


def _rows(recs: list[dict]) -> dict:
    return {"columns": ["Send", "Suggestion", "What to do", "Why", "Expected impact", "Priority"],
            "rows": [["yes" if r.get("include") else "no", r["title"], r["action"], r["why"], r["impact"], r["priority"]] for r in recs]}


def default_owner(ctx: wb.Ctx, s: dict) -> str:
    """Who should act by default: the owner of the dashboard the numbers come from, else the work item's owner."""
    for d in ctx.get("datasets") or []:
        if d["name"] == (s.get("signal_data") or {}).get("dataset") and d["ref"]["source"] == "dashboard":
            return (db.project(d["ref"]["project"]) or {}).get("owner_id") or ctx.owner or ""
    return ctx.owner or ""


def send(ctx: wb.Ctx, recs: list[dict], pbid: str | None) -> list[list]:
    """Each confirmed suggestion goes to its owner: a checkpoint in their Validation queue (accept, or decline with a
    reason), or a ticket through the service desk's own write approval. Recorded for tracking."""
    from . import anomaly
    rows, now = [], time.time()
    for r in recs:
        if not r.get("include"):
            continue
        who = r.get("assignee") or ctx.owner
        sid = "rs-" + _secrets.token_hex(5)
        ev = {"rows": r.get("evidence_rows") or [], "signal": r.get("signal_data") or {}}
        db.run("INSERT INTO recommend_suggestions (id, playbook, item, rule, signal, fingerprint, title, action, why, impact, evidence, assignee, status, created, updated) "
               "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'sent', ?, ?)", (sid, pbid, ctx.id, r["rule"], r["signal"], r["fingerprint"], r["title"], r["action"], r["why"], r["impact"],
                                                                        json.dumps(ev, default=str), who, now, now))
        if r.get("route") == "ticket":
            h = anomaly.service_desk_ticket(ctx, r["title"], f"{r['action']}\n\nWhy: {r['why']}\nExpected impact: {r['impact']}\nWork item: {wb.route_of(ctx.st)}",
                                            {"high": "P2", "medium": "P3"}.get(r.get("priority"), "P4"), about=r["title"], origin=f"recommend:{sid}")
            status = h.get("status") or "ticket"
        else:
            cp = checkpoints.open(KIND, sid, registry.BY_ID[MODULE]["name"], r["title"][:200], "table",
                                  {"summary": f"{r['action']} - {r['why']}", "items": [f"What to do: {r['action']}", f"Why: {r['why']}", f"Expected impact: {r['impact']}"],
                                   "columns": ["What", "Detail"], "rows": [["What to do", r["action"]], ["Why", r["why"]], ["Expected impact", r["impact"]], ["Priority", r.get("priority")]],
                                   "suggestion": sid, "item": {"id": ctx.id, "title": ctx.title}},
                                  link=f"#/m/{MODULE}/i/{ctx.id}", assignee=who, agent="Advisor", opened_by=ctx.who or ctx.owner)
            db.run("UPDATE recommend_suggestions SET checkpoint = ? WHERE id = ?", (cp["id"], sid))
            notify.add(who, "share", f"A suggestion for you: {r['title'][:80]}", r["action"][:200], "#/validate")
            status = "in their Validation queue"
        db.audit("recommend.suggestion.sent", sid, {"rule": r["rule"], "to": who, "route": r.get("route"), "item": ctx.id}, ctx.who or ctx.owner)
        rows.append([r["title"], (db.user(who) or {}).get("name") or who, status])
    return rows


def _on_decision(c: dict, decision: str, comment: str | None, who: str) -> None:
    """The owner's answer to a suggestion: accepted, or declined with a reason - tracked, and told to who sent it."""
    s = db.one("SELECT * FROM recommend_suggestions WHERE id = ?", (c["subject"],))
    if not s:
        return
    status = "accepted" if decision == "accept" else "declined"
    db.run("UPDATE recommend_suggestions SET status = ?, comment = ?, decided_by = ?, decided = ?, updated = ? WHERE id = ?", (status, (comment or "")[:500] or None, who, time.time(), time.time(), s["id"]))
    db.audit(f"recommend.suggestion.{status}", s["id"], {"rule": s["rule"], "comment": (comment or "")[:200]}, who)
    owner = (db.project(s["item"]) or {}).get("owner_id") if s.get("item") else None
    if owner and owner != who:
        notify.add(owner, "share", f"Suggestion {status}: {s['title'][:80]}", (comment or "")[:200], f"#/m/{MODULE}/i/{s['item']}")


checkpoints.register_kind(KIND, "Suggestion", _on_decision)


# ------------------------------------------------------------------ Develop

def d_signals(ctx: wb.Ctx) -> dict:
    ctx.put("datasets", pdat.datasets(ctx))
    sig = gather(ctx)
    if not sig:
        raise wb.StepFailed("No signal to work from: upload or connect data with a date and a number, or let Relay read forecasts, anomaly findings and Ask D's answers.")
    sent = {r["fingerprint"] for r in db.q("SELECT fingerprint FROM recommend_suggestions")}
    sig = [s for s in sig if s["fingerprint"] not in sent]
    ctx.put("signals", sig)
    by = {}
    for s in sig:
        by[s["signal"]] = by.get(s["signal"], 0) + 1
    return {"summary": f"{len(sig)} signal(s): " + ", ".join(f"{n} {SIGNALS[k].lower()}" for k, n in by.items()) + " - not yet suggested to anyone.",
            "counts": {"signals": len(sig), **{SIGNALS[k]: n for k, n in by.items()}},
            "data": {"columns": ["Signal", "From", "What", "Period"], "rows": [[SIGNALS[s["signal"]], s["dataset"], s["metric"], s["period"]] for s in sig[:200]]}}


def d_explain(ctx: wb.Ctx) -> dict:
    sig = ctx.get("signals") or []
    for s in sig:
        ctx.evidence(f"Signal: {s['metric']} ({s['period']})", {"explain": s["explain"], "rows": s.get("parts") or [{k: s.get(k) for k in ("period", "latest", "base", "base_value", "change_pct")}]},
                     kind="signal", ok=True)
    return {"summary": f"Each of the {len(sig)} signal(s) in plain words, with the numbers behind it as evidence.", "counts": {"signals": len(sig)},
            "data": {"columns": ["Signal", "In plain words"], "rows": [[SIGNALS[s["signal"]], s["explain"]] for s in sig[:200]]}}


def _rules(ctx: wb.Ctx) -> list[dict]:
    pb = playbook(ctx.scope.get("playbook") or "", db.user(ctx.owner or "") or {}) if ctx.scope.get("playbook") else None
    return (pb or {}).get("rules") or [dict(r) for r in DEFAULT_RULES]


def d_suggest(ctx: wb.Ctx) -> dict:
    have = {r["id"]: r for r in ctx.records(ctx.step_id)}
    recs = apply(_rules(ctx), ctx.get("signals") or [])
    for r in recs:
        if r["id"] in have:
            r.update({k: have[r["id"]][k] for k in ("include", "action", "priority") if k in have[r["id"]]})
    if not recs:
        raise wb.StepFailed("No playbook rule fits today's signals: nothing to suggest (change the playbook's thresholds in a Change item).")
    return {"summary": f"{len(recs)} suggestion(s), each from a signal and a playbook rule, with the numbers behind it and the expected impact. Change the wording, drop what does not help, then confirm.",
            "counts": {"suggestions": len(recs), "high": sum(1 for r in recs if r["priority"] == "high")}, "records": recs, "data": _rows(recs),
            "items": [f"{r['title']}: {r['action'][:160]}" for r in recs[:6]]}


def d_assign(ctx: wb.Ctx) -> dict:
    have = {r["id"]: r for r in ctx.records(ctx.step_id)}
    recs = []
    for r in ctx.records("suggest"):
        if not r.get("include"):
            continue
        h = have.get(r["id"]) or {}
        recs.append({**r, "assignee": h.get("assignee") or default_owner(ctx, r), "route": h.get("route") or "queue", "include": h.get("include", True)})
    return {"summary": f"{len(recs)} suggestion(s) to send: confirm who should act on each and how it reaches them - nothing is sent before you confirm.", "records": recs,
            "data": {"columns": ["Suggestion", "Who", "How"], "rows": [[r["title"], (db.user(r["assignee"]) or {}).get("name") or "-", r["route"]] for r in recs]}}


def d_track(ctx: wb.Ctx) -> dict:
    rows = send(ctx, ctx.records("assign"), None)
    ctx.output("suggestions.md", "# Suggestions sent: " + ctx.title + "\n\n" + "".join(f"- {r[0]} {r[1]} ({r[2]})\n" for r in rows), label="Suggestions sent (Markdown)")
    return {"summary": f"{len(rows)} suggestion(s) sent; each owner accepts it or declines it with a reason in their Validation queue, and the outcome is tracked here.",
            "counts": {"sent": len(rows)}, "data": {"columns": ["Suggestion", "Who", "Status"], "rows": rows}}


# ------------------------------------------------------------------ Change (the playbook)

def _validate_rules(recs: list[dict], ctx: wb.Ctx) -> list[str]:
    probs = []
    for i, r in enumerate(recs, 1):
        if r.get("signal") not in SIGNALS:
            probs.append(f"Rule {i}: the signal is one of {', '.join(SIGNALS)}")
        try:
            float(r.get("min_change") or 0)
        except (TypeError, ValueError):
            probs.append(f"Rule {i}: the smallest change is a number (per cent)")
        try:
            str(r.get("action") or "").format_map(_Safe())
        except (ValueError, KeyError):
            probs.append(f"Rule {i}: the action has a broken {{placeholder}}")
    return probs


RULE_EDIT = wb.Edit(columns=[wb.Column("on", "On", "bool"), wb.Column("signal", "Signal", "select", options=tuple(SIGNALS.items())),
                             wb.Column("when", "When", "select", options=(("down", "It falls"), ("up", "It rises"), ("any", "Any"))), wb.Column("min_change", "Smallest change (%)", "number"),
                             wb.Column("action", "Suggested action", "longtext", help="Placeholders: {metric} {change} {base} {period} {group} {gap} {half_gap} {reason} {text} {headline}"),
                             wb.Column("impact", "Expected impact"), wb.Column("priority", "Priority", "select", options=(("high", "High"), ("medium", "Medium"), ("low", "Low")))],
                    validate=_validate_rules, label="rule")


def c_request(ctx: wb.Ctx) -> dict:
    pb = playbook(ctx.scope.get("playbook") or "", db.user(ctx.owner or "") or {})
    ctx.put("playbook", pb["id"] if pb else None)
    ctx.put("current", (pb or {}).get("rules") or [dict(r) for r in DEFAULT_RULES])
    ctx.put("datasets", pdat.datasets(ctx))
    return {"summary": f"Change to the playbook \"{pb['name']}\" (version {pb['version']})." if pb else "A first playbook of the tenant's own, starting from Relay's default rules.",
            "data": {"text": ctx.brief or "(no request text)"}}


def c_diagnose(ctx: wb.Ctx) -> dict:
    sig = gather(ctx)
    ctx.put("signals", sig)
    sug = apply(ctx.get("current") or [], sig)
    o = outcomes(ctx.get("playbook")) if ctx.get("playbook") else {"rules": {}}
    checks = []
    for r in ctx.get("current") or []:
        n = sum(1 for s in sug if s["rule"] == r["id"])
        oc = o["rules"].get(r["id"]) or {}
        dec = (oc.get("accepted", 0) + oc.get("declined", 0))
        rate = round(100.0 * oc.get("accepted", 0) / dec, 1) if dec else None
        checks.append({"name": r["id"], "label": f"Rule {r['id']} ({SIGNALS.get(r.get('signal'), r.get('signal'))})", "status": "warn" if rate is not None and rate < 30 else "pass",
                       "measured": f"{n} suggestion(s) today" + (f" - {rate:g} % accepted so far" if rate is not None else ""), "expected": "", "detail": r.get("action") or ""})
    return {"summary": f"Today's signals through today's playbook: {len(sug)} suggestion(s).", "counts": {"suggestions": len(sug)}, "data": {"checks": checks}}


def c_fix(ctx: wb.Ctx) -> dict:
    recs = ctx.records(ctx.step_id) or [dict(r) for r in ctx.get("current") or []]
    return {"summary": "Edit the playbook: when a rule fires, what it suggests and how urgent it is.", "records": recs,
            "data": {"columns": ["Rule", "Signal", "When", "Smallest change", "Action"], "rows": [[r["id"], r.get("signal"), r.get("when"), r.get("min_change"), r.get("action")] for r in recs]}}


def c_prove(ctx: wb.Ctx) -> dict:
    new = apply(ctx.records("fix"), ctx.get("signals") or [])
    old = apply(ctx.get("current") or [], ctx.get("signals") or [])
    ctx.put("diff", {"before": len(old), "after": len(new)})
    checks = [{"name": s["id"], "label": s["title"], "status": "pass", "measured": s["priority"], "expected": "", "detail": f"{s['action']} - {s['why']}"} for s in new[:100]]
    return {"summary": f"Dry run on today's signals: {len(new)} suggestion(s) with the edited playbook, {len(old)} with today's.", "counts": {"before": len(old), "after": len(new)},
            "data": {"checks": checks or [{"name": "none", "label": "No suggestion today", "status": "warn", "detail": "no rule fires on today's signals"}]}}


def c_approve(ctx: wb.Ctx) -> dict:
    d = ctx.get("diff") or {}
    return {"summary": f"Release the playbook: {d.get('after', 0)} suggestion(s) on today's signals (today's playbook: {d.get('before', 0)}).",
            "data": {"items": [{"title": r["id"], "detail": r.get("action") or ""} for r in ctx.records("fix") if r.get("on")]}}


def c_learn(ctx: wb.Ctx) -> dict:
    pb = publish(ctx, ctx.records("fix"), ctx.get("playbook"))
    return {"summary": f"Playbook \"{pb['name']}\" version {pb['version']} is live; Run items using it suggest from it from their next round.", "counts": {"version": pb["version"]},
            "data": {"href": f"#/m/{MODULE}/run", "label": "Run & support", "text": f"Version {pb['version']} - {len(pb['rules'])} rule(s)"}}


# ------------------------------------------------------------------ Run & support

def r_watch(ctx: wb.Ctx) -> dict:
    ctx.put("datasets", pdat.datasets(ctx))
    sig = gather(ctx)
    sent = {r["fingerprint"] for r in db.q("SELECT fingerprint FROM recommend_suggestions")}
    new = [s for s in sig if s["fingerprint"] not in sent]
    ctx.put("signals", new)
    o = outcomes()                                         # the learning loop counts every suggestion sent in this workspace
    ctx.put("outcomes", o)
    checks = [{"name": "signals", "label": "New signals since the last round", "status": "pass", "measured": f"{len(new)}", "expected": "", "detail": "; ".join(s["explain"] for s in new[:3])[:400] or "none"},
              {"name": "outcomes", "label": "What people did with the suggestions", "status": "warn" if o.get("acceptance") is not None and o["acceptance"] < 30 else "pass",
               "measured": f"{o.get('accepted', 0)} accepted, {o.get('declined', 0)} declined, {o.get('open', 0)} open", "expected": "",
               "detail": f"{o['acceptance']:g} % accepted" if o.get("acceptance") is not None else "no decision yet"}]
    return {"summary": f"{len(new)} new signal(s); so far {o.get('accepted', 0)} suggestion(s) accepted and {o.get('declined', 0)} declined.", "counts": {"signals": len(new), **{k: o.get(k, 0) for k in ("accepted", "declined", "open")}},
            "data": {"checks": checks}}


def r_alert(ctx: wb.Ctx) -> dict:
    sug = apply(_rules(ctx), ctx.get("signals") or [])
    ctx.put("new", sug)
    if not sug:
        return {"summary": "No new suggestion this round.", "next": "report", "counts": {"suggestions": 0}}
    return {"summary": f"{len(sug)} new suggestion(s) from new signals.", "counts": {"suggestions": len(sug)}, "items": [s["title"] for s in sug[:6]], "data": _rows(sug)}


def r_fix(ctx: wb.Ctx) -> dict:
    have = {r["id"]: r for r in ctx.records(ctx.step_id)}
    recs = [{**s, "assignee": (have.get(s["id"]) or {}).get("assignee") or default_owner(ctx, s), "route": (have.get(s["id"]) or {}).get("route") or "queue",
             "include": (have.get(s["id"]) or {}).get("include", True)} for s in ctx.get("new") or []]
    return {"summary": f"{len(recs)} new suggestion(s): confirm who should act on each - nothing is sent before you confirm.", "records": recs,
            "data": {"columns": ["Suggestion", "Who", "How"], "rows": [[r["title"], (db.user(r["assignee"]) or {}).get("name") or "-", r["route"]] for r in recs]}}


def r_approve(ctx: wb.Ctx) -> dict:
    rows = send(ctx, ctx.records("fix"), ctx.scope.get("playbook") or None)
    return {"summary": f"{len(rows)} suggestion(s) sent, as you approved.", "counts": {"sent": len(rows)}, "data": {"columns": ["Suggestion", "Who", "Status"], "rows": rows}}


def r_report(ctx: wb.Ctx) -> dict:
    o = ctx.get("outcomes") or {}
    text = f"# Suggestions report: {ctx.title}\n\n{time.strftime('%d %B %Y %H:%M UTC', time.gmtime())}\n\n- Sent: {o.get('sent', 0)}\n- Accepted: {o.get('accepted', 0)}\n- Declined: {o.get('declined', 0)}\n- Open: {o.get('open', 0)}\n"
    ctx.output(f"report-{time.strftime('%Y%m%d-%H%M', time.gmtime())}.md", text, label="Suggestions report (Markdown)")
    return {"summary": f"{o.get('accepted', 0)} accepted, {o.get('declined', 0)} declined, {o.get('open', 0)} open" + (f" - {o['acceptance']:g} % accepted." if o.get("acceptance") is not None else "."),
            "counts": {k: o.get(k, 0) for k in ("accepted", "declined", "open")}, "data": {"columns": ["Outcome", "Suggestions"], "rows": [[k, o.get(k, 0)] for k in ("accepted", "declined", "open")]}}


def _cards(u: dict) -> list[dict]:
    rows = []
    for s in db.q("SELECT * FROM recommend_suggestions ORDER BY created DESC LIMIT 200"):
        if s.get("item") and not auth.can_project(u, "view", db.project(s["item"])) and s.get("assignee") != u["id"]:
            continue
        rows.append([s["title"], (db.user(s.get("assignee") or "") or {}).get("name") or "-", {"sent": "open"}.get(s["status"], s["status"]), (s.get("comment") or "")[:120],
                     time.strftime("%d %b %Y", time.gmtime(s["created"])), f"#/m/{MODULE}/i/{s['item']}" if s.get("item") else ""])
    return [{"title": "Suggestions and what happened to them", "columns": ["Suggestion", "Who", "Outcome", "Their note", "Sent", "Work item"], "rows": rows[:40],
             "empty": "No suggestion has been sent yet: a Develop item's Track step sends them after the owners are confirmed."}]


GUIDE = """# Suggestions & recommendations - the work item

This folder is one work item of Relay's suggestions module. Suggestions come from signals in the data (and from
forecasts, anomaly findings and Ask D's answers) through a playbook of rules; every suggestion carries the numbers
behind it and a person confirms it, and who should act, before it is sent. No AI step invents a suggestion here.

- `evidence/`: each signal with its numbers; `outputs/`: what was sent and the reports."""

DEV_FIELDS = [wb.Field("dashboard", "A dashboard's data", "select", options=pdat.dashboards_for, help="Optional: read with your access, as Ask D does."),
              wb.Field("objects", "Warehouse tables or views", "longtext", help="One per line (with a warehouse connection)."),
              wb.Field("value", "The number that matters", help="Blank: Relay picks the likeliest (amounts, quantities, counts)."),
              wb.Field("by", "Explain the change by", help="Optional: a column with up to 12 values, e.g. region."),
              wb.Field("playbook", "Playbook", "select", options=lambda u: [("", "Relay's default rules")] + playbook_options(u)),
              wb.Field("forecasts", "Include live forecasts", "bool", default=True), wb.Field("anomalies", "Include anomaly findings", "bool", default=True),
              wb.Field("askd", "Include Ask D's suggestions", "bool", default=True)]

wb.register(wb.Pack(
    module=MODULE, guide=GUIDE, lineage="", platforms=PLATFORMS, schemas={"suggestion": SUG_COLUMNS, "assignment": ASSIGN_COLUMNS, "rule": RULE_EDIT.columns}, cards=_cards,
    work={
        "develop": wb.Work(title="Next-best actions from your numbers, each with its evidence, sent to who should act", needs_source=False, steps={
            "Signals": wb.Step(kind="platform", run=d_signals, agent="Signal reader"),
            "Explain": wb.Step(kind="deterministic", run=d_explain, agent="Explainer"),
            "Suggest": wb.Step(kind="deterministic", run=d_suggest, agent="Advisor", edit=SUG_EDIT),
            "Assign": wb.Step(kind="person", run=d_assign, edit=ASSIGN_EDIT),
            "Track": wb.Step(kind="deterministic", run=d_track, agent="Dispatcher")},
            fields=DEV_FIELDS),
        "change": wb.Work(title="Change the playbook, with a dry run on today's signals", needs_source=False, steps={
            "Request": wb.Step(kind="deterministic", run=c_request, view="text", agent="Playbook librarian", text="The change in plain words, and the playbook it changes"),
            "Diagnose": wb.Step(kind="proof", run=c_diagnose, view="gates", agent="Advisor", text="Today's signals through today's rules, with how often each rule's suggestions were accepted"),
            "Fix": wb.Step(kind="person", run=c_fix, edit=RULE_EDIT, confirm="the edited playbook", text="You edit the rules: when they fire, what they suggest, how urgent"),
            "Prove": wb.Step(kind="proof", run=c_prove, view="gates", agent="Advisor", back_to="fix", text="A dry run of the edited playbook on today's signals"),
            "Approve": wb.Step(kind="person", run=c_approve, view="plan", approver=True, text="The named approver releases the playbook"),
            "Learn": wb.Step(kind="deterministic", run=c_learn, view="link", agent="Publisher", text="The playbook is published and kept")},
            fields=[wb.Field("playbook", "Playbook to change", "select", options=lambda u: [("", "Start from Relay's default rules")] + playbook_options(u))] + DEV_FIELDS[:4]),
        "run": wb.Work(title="New suggestions on a schedule, and what people did with them", needs_source=False, steps={
            "Watch": wb.Step(kind="proof", run=r_watch, view="gates", agent="Signal reader", text="New signals since the last round, and the outcomes so far (accepted, declined, open)"),
            "Alert": wb.Step(kind="deterministic", run=r_alert, agent="Advisor", text="New suggestions from the new signals, through the playbook"),
            "Fix": wb.Step(kind="deterministic", run=r_fix, agent="Advisor", edit=ASSIGN_EDIT, text="Relay proposes who should act on each - you confirm or change it"),
            "Approve": wb.Step(kind="platform", run=r_approve, agent="Dispatcher", text="The confirmed suggestions go out: their owners' Validation queues, or a ticket through the service desk's own approval"),
            "Report": wb.Step(kind="deterministic", run=r_report, agent="Reporter", confirm_if=lambda ctx, out: bool(ctx.get("new")), text="Accepted, declined and open; you confirm it when there were new suggestions")},
            fields=DEV_FIELDS + [wb.Field("schedule", "Look for new signals", "cadence", default={"every": "week", "at": "07:00", "weekday": 0, "tz": "UTC"})]),
    }))
