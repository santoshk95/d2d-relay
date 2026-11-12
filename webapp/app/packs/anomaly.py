"""Anomaly & risk detection (registry id `anomaly`) - unusual numbers caught early, each with its reason, and a person
reviewing every finding before anything goes out.

Detectors (anomaly_rules): rules and plain statistics on metrics over time (z-score, IQR, seasonal residuals, a
business threshold) and on table rows (unusual rows per group by IQR, row rules) - no model to trust blindly. Data
comes from uploads, warehouse connections and a dashboard's data (predict_data: Ask Relay's guarded engine).
Assess   Connect -> Inventory -> Health -> Findings -> Estimate: what is watchable, and what is unusual today.
Develop  Describe -> Shape -> Build -> Prove -> Ship -> Run: detectors suggested from the data and confirmed by a person,
         compiled, proven on the history (the findings each would have raised, and how noisy it is), approved by name
         and published with a scheduled Run item.
Change   Request -> Diagnose -> Fix -> Prove -> Approve -> Learn: a live detector set edited, with a dry run.
Run      Watch -> Alert -> Fix -> Approve -> Report: the live detectors on a schedule; every new finding waits for a
         person - an alert through Reports & alerts (a schedules alert on the dashboard's measure), a ticket through
         the service desk's own write approval, expected or ignored - and only then does anything go out.
Detector sets are versioned in `anomaly_sets` / `anomaly_set_versions`; each finding and the decision on it are rows
of `anomaly_findings` (a finding decided once is not raised again)."""
from __future__ import annotations

import json
import secrets as _secrets
import time

from .. import auth, db, registry, store
from .. import workbench as wb
from . import anomaly_rules as ar
from . import predict_data as pdat

MODULE = "anomaly"
SYSTEM = "Relay anomaly detection"
MINUTES = {"confirm a detector": 5, "review a finding": 4, "set a business threshold": 10}

db.register_schema("""
CREATE TABLE IF NOT EXISTS anomaly_sets (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, item TEXT, version INTEGER NOT NULL DEFAULT 1, detectors TEXT NOT NULL DEFAULT '[]', datasets TEXT NOT NULL DEFAULT '[]',
  run_item TEXT, owner_id TEXT, published_by TEXT, published REAL, status TEXT NOT NULL DEFAULT 'live', created REAL NOT NULL, updated REAL NOT NULL);
CREATE TABLE IF NOT EXISTS anomaly_set_versions (
  set_id TEXT NOT NULL, version INTEGER NOT NULL, detectors TEXT NOT NULL, item TEXT, published_by TEXT, published REAL NOT NULL, note TEXT,
  PRIMARY KEY (set_id, version));
CREATE TABLE IF NOT EXISTS anomaly_findings (
  id TEXT PRIMARY KEY, set_id TEXT, item TEXT, fingerprint TEXT NOT NULL, detector TEXT, dataset TEXT, at TEXT, value REAL, expected TEXT, reason TEXT,
  severity TEXT, status TEXT NOT NULL DEFAULT 'new', route TEXT, decided_by TEXT, decided REAL, note TEXT, handoff TEXT, created REAL NOT NULL, updated REAL NOT NULL);
CREATE INDEX IF NOT EXISTS anomaly_findings_fp ON anomaly_findings (set_id, fingerprint);
""")

FILES = wb.FilesPlatform()
WAREHOUSE = wb.WarehousePlatform()
PLATFORMS = {"files": FILES, "warehouse": WAREHOUSE, "dashboards": pdat.DASHBOARDS}
ROUTES = (("alert", "Alert (Reports & alerts)"), ("ticket", "Raise a ticket"), ("expected", "Expected - no action"), ("ignore", "Ignore this time"))


# ------------------------------------------------------------------ detector sets (versioned) and findings

def dset(sid: str, u: dict | None = None) -> dict | None:
    r = db.one("SELECT * FROM anomaly_sets WHERE id = ?", (sid,))
    if not r:
        return None
    if u is not None and r.get("item") and not auth.can_project(u, "view", db.project(r["item"])):
        return None
    return {**r, "detectors": pdat.j(r["detectors"], []), "datasets": pdat.j(r["datasets"], [])}


def dsets(u: dict) -> list[dict]:
    return [s for s in (dset(r["id"], u) for r in db.q("SELECT id FROM anomaly_sets WHERE status = 'live' ORDER BY updated DESC")) if s]


def set_options(u: dict) -> list[tuple[str, str]]:
    return [(s["id"], f"{s['name']} - version {s['version']} - {len(s['detectors'])} detectors") for s in dsets(u)]


def publish(ctx: wb.Ctx, detectors: list[dict], datasets: list[dict], sid: str | None = None, note: str = "") -> dict:
    now, who = time.time(), ctx.who or ctx.owner
    keep = [d for d in detectors if d.get("active")]
    if sid and db.one("SELECT 1 FROM anomaly_sets WHERE id = ?", (sid,)):
        v = db.one("SELECT version FROM anomaly_sets WHERE id = ?", (sid,))["version"] + 1
        db.run("UPDATE anomaly_sets SET version = ?, detectors = ?, datasets = ?, published_by = ?, published = ?, updated = ? WHERE id = ?",
               (v, json.dumps(keep), json.dumps(datasets), who, now, now, sid))
    else:
        sid, v = "ads-" + _secrets.token_hex(4), 1
        db.run("INSERT INTO anomaly_sets (id, name, item, version, detectors, datasets, owner_id, published_by, published, status, created, updated) VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?, 'live', ?, ?)",
               (sid, ctx.title[:160], ctx.id, json.dumps(keep), json.dumps(datasets), ctx.owner, who, now, now, now))
    db.run("INSERT OR REPLACE INTO anomaly_set_versions (set_id, version, detectors, item, published_by, published, note) VALUES (?, ?, ?, ?, ?, ?, ?)",
           (sid, v, json.dumps(keep), ctx.id, who, now, note[:500] or None))
    db.audit("anomaly.set.publish", sid, {"version": v, "detectors": len(keep), "item": ctx.id}, who)
    return dset(sid)


def findings_of(sid: str, status: str | None = None) -> list[dict]:
    return db.q("SELECT * FROM anomaly_findings WHERE set_id = ?" + (" AND status = ?" if status else "") + " ORDER BY created DESC", (sid, status) if status else (sid,))


# ------------------------------------------------------------------ detectors: suggested from the data, run on it

def _dmap(ctx: wb.Ctx) -> dict:
    return {d["key"]: d for d in ctx.get("datasets") or []}


def _ds_options(ctx: wb.Ctx):
    return [(d["key"], d["name"]) for d in ctx.get("datasets") or []]


def _grain(ctx: wb.Ctx, ref: dict, date: str, value: str | None) -> str:
    want = ctx.scope.get("grain") or "month"
    p, _ = pdat.series(ctx, ref, date, value, want, "sum" if value else "count")
    return want if len(p) >= 8 or want == "day" else "day"


def suggest(ctx: wb.Ctx, dsets_: list[dict]) -> list[dict]:
    """Detectors suggested from what the data shows - rules first, nothing invented: a threshold waits for the person's
    number, switched off."""
    out = []
    for d in dsets_:
        cols = pdat.columns(ctx, d["ref"])
        dates, nums, texts = pdat.kind_cols(cols)
        value = pdat._cname(cols, ctx.scope.get("value") or "") or pdat.best_value(nums)
        if not value:
            continue
        key = next((c["name"] for c in cols if c["name"].lower().endswith(("_id", "id", "_no", "number"))), None)
        base = {"dataset": d["key"], "value": value, "agg": "sum", "severity": "medium", "active": True, "params": ""}
        if dates:
            date = pdat._cname(cols, ctx.scope.get("date") or "") or dates[0]
            grain = _grain(ctx, d["ref"], date, value)
            p, y = pdat.series(ctx, d["ref"], date, value, grain, "sum")
            seasonal_ok = len(p) >= 2 * {"day": 7, "week": 52, "month": 12, "quarter": 4}[grain]
            out.append({**base, "id": f"seasonal-{pdat.slug(d['name'], 20)}-{pdat.slug(value, 16)}", "kind": "seasonal" if seasonal_ok else "zscore", "date": date, "grain": grain,
                        "severity": "high", "why": f"{len(p)} {grain}s of {value}: " + ("a trend and a season to compare each period with" if seasonal_ok else "too short for a season: each period against the ones before it")})
            out.append({**base, "id": f"iqr-{pdat.slug(d['name'], 20)}-{pdat.slug(value, 16)}", "kind": "iqr", "date": date, "grain": grain, "active": False,
                        "why": "a robust second opinion on the same metric (off: switch it on to compare)"})
            out.append({**base, "id": f"threshold-{pdat.slug(d['name'], 20)}-{pdat.slug(value, 16)}", "kind": "threshold", "date": date, "grain": grain, "params": "> ?", "active": False,
                        "severity": "high", "why": "a business limit: Relay does not guess the number - write it (e.g. > 50000) and switch it on"})
        group = next((t for t in texts if 1 < len(pdat.distinct(ctx, d["ref"], t, 51)) <= 50), None)
        if dates and not group:
            continue                                        # a metric table: the detectors over time above cover it
        out.append({**base, "id": f"rows-{pdat.slug(d['name'], 20)}-{pdat.slug(value, 16)}", "kind": "row_iqr", "group": group or "", "key": key or "",
                    "why": f"each row's {value} against " + (f"its {group}'s usual range" if group else "the usual range")})
        r = pdat.reader(ctx, d["ref"])
        try:
            neg = r.run(f"SELECT COUNT(*) AS n FROM {pdat.table_expr(r)} WHERE CAST({pdat._qc(value)} AS DOUBLE) < 0")[0]
            negs = int({k.lower(): v for k, v in neg.items()}["n"] or 0)
        except wb.oc.ReadError:
            negs = 0
        finally:
            pdat.close(r)
        out.append({**base, "id": f"neg-{pdat.slug(d['name'], 20)}-{pdat.slug(value, 16)}", "kind": "row_rule", "params": "< 0", "key": key or "", "group": group or "", "active": bool(negs),
                    "severity": "medium", "why": f"{negs} row(s) with a negative {value} today" if negs else f"no negative {value} today: switch on if one should never happen"})
    return out


def _validate(recs: list[dict], ctx: wb.Ctx) -> list[str]:
    dmap = _dmap(ctx)
    probs = []
    for i, d in enumerate(recs, 1):
        d["problem"] = ""
        if not d.get("active"):
            continue
        _, p = ar.parse(d)
        if d.get("dataset") not in dmap:
            p.append("pick one of the datasets")
        if p:
            d["problem"] = "; ".join(p)
            probs.append(f"Row {i}: {d['problem']}")
    if not any(d.get("active") for d in recs):
        probs.append("Switch on at least one detector.")
    return probs


DET_COLUMNS = [wb.Column("active", "On", "bool"), wb.Column("kind", "Detector", "select", options=tuple(ar.KINDS.items())),
               wb.Column("dataset", "Dataset", "select", options=_ds_options), wb.Column("value", "Number"), wb.Column("date", "Date (metrics)"),
               wb.Column("grain", "By (metrics)", "select", options=pdat.GRAINS), wb.Column("group", "Per (rows)"), wb.Column("params", "Sensitivity or rule", help=ar.PARAM_HELP),
               wb.Column("severity", "Severity", "select", options=ar.SEVERITIES), wb.Column("why", "Why Relay suggests it", readonly=True)]
DET_EDIT = wb.Edit(columns=DET_COLUMNS, validate=_validate, label="detector")


def label(d: dict, dmap: dict) -> str:
    return f"{ar.KINDS.get(d.get('kind'), d.get('kind'))} - {(dmap.get(d.get('dataset')) or {}).get('name', '?')}.{d.get('value') or ''}" + (f" by {d['grain']}" if d.get("kind") in ar.SERIES_KINDS else "")


def run_detectors(ctx: wb.Ctx, dets: list[dict], dmap: dict, tag: str) -> tuple[list[dict], list[dict]]:
    """Every active detector over today's data: (gate rows, findings). Each finding has a fingerprint (detector +
    period or row key), its reason, the value and what was expected."""
    gates, found = [], []
    for d in [x for x in dets if x.get("active")]:
        params, probs = ar.parse(d)
        ds = dmap.get(d.get("dataset"))
        lab = label(d, dmap)
        if probs or not ds:
            gates.append({"name": d["id"], "label": lab, "status": "error", "measured": "", "expected": "", "detail": "; ".join(probs) or "its dataset is not read here"})
            continue
        try:
            if d["kind"] in ar.SERIES_KINDS:
                p, y = pdat.series(ctx, ds["ref"], d.get("date") or "", d.get("value"), d.get("grain") or "month", d.get("agg") or "sum")
                fs, bounds = ar.series_findings(d["kind"], params, p, y, d.get("grain") or "month")
                points = len(p)
            else:
                cols, rows = pdat.rows_of(ctx, ds["ref"], 20000)
                col = pdat._cname(cols, d.get("value") or "")
                if not col:
                    raise wb.StepFailed(f"{d.get('value')} is not a column of {ds['name']}")
                fs, bounds = ar.row_findings(d["kind"], params, rows, col, pdat._cname(cols, d.get("group") or "") or None, pdat._cname(cols, d.get("key") or "") or None)
                points = len(rows)
        except wb.StepFailed as e:
            gates.append({"name": d["id"], "label": lab, "status": "error", "measured": "", "expected": "", "detail": str(e)[:300]})
            continue
        for f in fs:
            at = f["at"] or json.dumps(f.get("row") or {}, sort_keys=True, default=str)[:200]
            found.append({"id": f"f-{pdat.slug(d['id'], 40)}-{pdat.slug(at, 40)}", "fingerprint": f"{d['id']}|{at}", "detector": d["id"], "kind": d["kind"], "dataset": ds["name"],
                          "dataset_key": ds["key"], "label": lab, "at": f["at"] or "(row)", "value": f["value"], "expected": f["expected"], "score": f.get("score"), "low": f.get("low"), "high": f.get("high"), "reason": f["reason"],
                          "severity": d.get("severity") or "medium", "row": {k: (str(v) if v is not None else None) for k, v in (f.get("row") or {}).items()} or None})
        share = ar.noise(len(fs), points)
        ev = ctx.evidence(f"{tag}: {lab}", {"detector": d, "bounds": bounds, "points": points, "rows": [{k: x.get(k) for k in ("at", "value", "expected", "score", "reason")} for x in found if x["detector"] == d["id"]][:200]},
                          kind="detector", ok=True)
        gates.append({"name": d["id"], "label": lab, "status": "pass" if not fs else "warn" if share <= 10 else "fail", "severity": d.get("severity"), "kind": d["kind"],
                      "measured": f"{len(fs)} finding(s) in {points} {'period' if d['kind'] in ar.SERIES_KINDS else 'row'}s ({share:g} %)", "expected": "a few, each with its reason",
                      "detail": ("; ".join(f"{x['at']}: {x['reason']}" for x in found if x["detector"] == d["id"])[:400] if fs else "nothing unusual") + (" - too noisy: raise k or narrow it" if share > 10 else ""),
                      "evidence": ev})
    return gates, found


def _table(dets: list[dict], dmap: dict) -> dict:
    return {"columns": ["On", "Detector", "Dataset", "Number", "By / per", "Sensitivity or rule", "Severity", "Why"],
            "rows": [["yes" if d.get("active") else "no", ar.KINDS.get(d.get("kind"), d.get("kind")), (dmap.get(d.get("dataset")) or {}).get("name", "?"), d.get("value"),
                      d.get("grain") if d.get("kind") in ar.SERIES_KINDS else d.get("group") or "-", d.get("params") or "default", d.get("severity"), d.get("why") or ""] for d in dets]}


# ------------------------------------------------------------------ hand-offs (only after a person decided)

def alert_for(ctx: wb.Ctx, f: dict, det: dict, ds: dict) -> dict:
    """An alert through Reports & alerts: a schedules alert on the dashboard's own data, owned by the item's owner - the
    latest period's value against the bound the detector used. Only for a dashboard's data (alerts check a dashboard)."""
    from .. import schedules
    if ds["ref"]["source"] != "dashboard":
        return {"ok": False, "status": "no alert: Reports & alerts checks a dashboard's data, and this finding is on an upload or a warehouse table"}
    if not wb.module_on("schedule"):
        return {"ok": False, "status": "no alert: Reports & alerts is not switched on for this workspace"}
    u = db.user(ctx.owner or "")
    if not u or det.get("kind") not in ar.SERIES_KINDS:
        return {"ok": False, "status": "no alert: an alert watches a metric over time"}
    grain, d, v, t = det.get("grain") or "month", pdat._qc(det.get("date") or ""), pdat._qc(det.get("value") or ""), pdat._qc(ds["ref"]["table"])
    per = f"CAST(DATE_TRUNC('{grain}', CAST({d} AS DATE)) AS DATE)" if grain != "day" else f"CAST({d} AS DATE)"
    sql = f"SELECT SUM(CAST({v} AS DOUBLE)) AS value FROM {t} WHERE {per} = (SELECT MAX({per}) FROM {t})"
    params, _ = ar.parse(det)
    if det["kind"] == "threshold":
        op, thr = params["op"], params["value"]
    else:
        above = (f.get("score") or 0) >= 0
        op = ">" if above else "<"
        thr = float(f.get("high") if above else f.get("low")) if f.get("high" if above else "low") is not None else float(f["value"])
    body = {"kind": "alert", "name": f"Anomaly: {det.get('value')} on {ds['name']}"[:120], "tz": "UTC", "cadence": {"freq": "daily", "time": "07:00"},
            "target": {"type": "sql", "project": ds["ref"]["project"], "sql": sql, "op": op, "threshold": round(thr, 2)}, "recipients": [u["id"]]}
    try:
        s = schedules.save(u, body)
    except schedules.ScheduleError as e:
        return {"ok": False, "status": f"no alert: {e}"}
    h = ctx._handoff({"kind": "alert", "label": body["name"], "status": f"alert set up: {s['when']} ({op} {round(thr, 2):,})", "link": "#/schedules", "schedule": s["id"]})
    return {"ok": True, "status": h["status"], "schedule": s["id"]}


def service_desk_ticket(ctx: wb.Ctx, title: str, body: str, priority: str = "P3", about: str = "", origin: str | None = None) -> dict:
    """A ticket through the service desk: on the first source that may raise tickets, its own write approval shows
    exactly what will be written; with none, the workbench's route (a matching group, else a ticket draft)."""
    try:
        from .. import itsm
        s = itsm.ticket_target()
    except Exception:  # noqa: BLE001 - no service desk module here
        s = None
    if s:
        try:
            w = itsm.request_write(s["id"], "create", {"title": title[:240], "description": body[:6000], "priority": priority, "labels": [ctx.module]}, who=ctx.who or ctx.owner,
                                   module=ctx.module_name, origin=origin, link=wb.route_of(ctx.st), name=f"Raise a ticket on {s['name']}: {title}"[:200])
            return ctx._handoff({"kind": "ticket", "label": title, "checkpoint": w.get("checkpoint_id"), "status": "awaiting the service desk's write approval",
                                 "link": f"#/servicedesk?write={w['id']}", "via": s["name"], "write": w["id"]})
        except Exception as e:  # noqa: BLE001 - refused (scope, settings): the workbench's route below
            ctx.note(f"The service desk did not take the ticket ({str(e)[:160]}); it is kept as a draft.", "warn")
    return ctx.ticket(title, body, priority=priority, about=about)


# ------------------------------------------------------------------ Assess

def a_connect(ctx: wb.Ctx) -> dict:
    rows = []
    for p in (FILES, WAREHOUSE, pdat.DASHBOARDS):
        rows += p.test(ctx)
    if not rows:
        raise wb.StepFailed("Nothing to read: upload files, pick a warehouse connection or choose a dashboard.")
    good = [r for r in rows if r["ok"]]
    if not good:
        raise wb.StepFailed("None of the sources answered: " + "; ".join(f"{r['source']}: {r['sees']}" for r in rows)[:600])
    return {"summary": f"{len(good)} of {len(rows)} source(s) answered - read-only.", "counts": {"sources": len(rows), "answered": len(good)},
            "data": {"columns": ["Source", "Kind", "Status", "What Relay sees", "Access"], "rows": [[r["source"], r["kind"], "answered" if r["ok"] else "refused", r["sees"], r["scope"]] for r in rows]}}


def a_inventory(ctx: wb.Ctx) -> dict:
    dsets_ = pdat.datasets(ctx)
    if not dsets_:
        raise wb.StepFailed("The sources show no tables or files to watch.")
    ctx.put("datasets", dsets_)
    recs = []
    for d in dsets_:
        cols = pdat.columns(ctx, d["ref"])
        dates, nums, _ = pdat.kind_cols(cols)
        recs.append({"id": d["key"], "include": bool(nums), "dataset": d["name"], "where": d["where"], "dates": ", ".join(dates) or "-", "numbers": ", ".join(nums[:6]) or "-"})
    return {"summary": f"{len(recs)} table(s) and file(s); {sum(1 for r in recs if r['include'])} with numbers to watch are included - untick what is out of scope.",
            "counts": {"found": len(recs), "included": sum(1 for r in recs if r["include"])}, "records": recs,
            "data": {"columns": ["Include", "Dataset", "Where", "Dates", "Numbers"], "rows": [["yes" if r["include"] else "no", r["dataset"], r["where"], r["dates"], r["numbers"]] for r in recs]}}


def a_health(ctx: wb.Ctx) -> dict:
    inv = {d["key"]: d for d in ctx.get("datasets") or []}
    keep = [inv[r["id"]] for r in ctx.records("inventory") if r.get("include") and r["id"] in inv]
    if not keep:
        raise wb.StepFailed("Nothing is included: tick at least one dataset in the inventory.")
    ctx.put("datasets", keep)
    dets = suggest(ctx, keep)
    ctx.put("suggested", dets)
    gates, found = run_detectors(ctx, dets, {d["key"]: d for d in keep}, "Today")
    ctx.put("found", found)
    return {"summary": f"{len(keep)} dataset(s) watched with {sum(1 for d in dets if d['active'])} detector(s) suggested from the data; {len(found)} finding(s) today.",
            "counts": {"datasets": len(keep), "detectors": sum(1 for d in dets if d["active"]), "findings": len(found)}, "data": {"checks": gates}}


FIND_EDIT = wb.Edit(columns=[wb.Column("decision", "Decision", "select", options=(("keep", "Keep"), ("ignore", "Ignore"))), wb.Column("severity", "Severity", "select", options=ar.SEVERITIES),
                             wb.Column("label", "Detector", readonly=True), wb.Column("at", "Where", readonly=True), wb.Column("reason", "Why it is unusual", readonly=True)],
                    add=False, remove=False, label="finding")


def a_findings(ctx: wb.Ctx) -> dict:
    have = {r["id"]: r for r in ctx.records(ctx.step_id)}
    recs = [{**{k: f[k] for k in ("id", "label", "at", "reason", "severity", "value", "expected")}, "decision": (have.get(f["id"]) or {}).get("decision") or "keep",
             **({"severity": have[f["id"]]["severity"]} if f["id"] in have else {})} for f in ctx.get("found") or []]
    return {"summary": f"{len(recs)} finding(s) - a person reviews each: keep what matters, ignore what does not." if recs else "Nothing unusual today with the suggested detectors.",
            "counts": {"findings": len(recs)}, "records": recs, "items": [f"{r['label']} at {r['at']}: {r['reason']}" for r in recs[:6]],
            "data": {"columns": ["Detector", "Where", "Why it is unusual", "Severity"], "rows": [[r["label"], r["at"], r["reason"], r["severity"]] for r in recs]}}


def a_estimate(ctx: wb.Ctx) -> dict:
    dets = [d for d in ctx.get("suggested") or [] if d.get("active")]
    kept = [f for f in ctx.records("findings") if f.get("decision") != "ignore"]
    b = registry.brand()
    rate, cur = float(b.get("hourly_rate") or 0), b.get("currency") or ""
    h1 = (len(dets) * MINUTES["confirm a detector"] + len(kept) * MINUTES["review a finding"]) / 60
    h2 = len({d["dataset"] for d in dets}) * MINUTES["set a business threshold"] / 60
    items = [{"title": "Wave 1 - the suggested detectors and today's findings", "detail": f"{len(dets)} detector(s) to confirm, {len(kept)} finding(s) to review", "effort": f"{h1:.1f} h" + (f" - {cur}{rate * h1:,.0f}" if rate else "")},
             {"title": "Wave 2 - business thresholds", "detail": "one limit per dataset that only a person can set", "effort": f"{h2:.1f} h" + (f" - {cur}{rate * h2:,.0f}" if rate else "")}]
    note = "Assumptions: " + "; ".join(f"{v} min to {k}" for k, v in MINUTES.items()) + "." + ("" if rate else " Set an hourly rate under Admin > Branding to see the cost.")
    ctx.output("assessment.md", f"# Anomaly assessment: {ctx.title}\n\n" + "".join(f"## {i['title']}\n\n{i['detail']}\n\nEffort: {i['effort']}\n\n" for i in items) + note + "\n", label="Assessment (Markdown)")
    return {"summary": f"About {h1 + h2:.1f} h of a person's time to put these detectors live.", "counts": {"hours": round(h1 + h2, 1)}, "data": {"items": items, "total": f"{h1 + h2:.1f} h", "note": note}}


# ------------------------------------------------------------------ Develop

def d_describe(ctx: wb.Ctx) -> dict:
    dsets_ = pdat.datasets(ctx)
    if not dsets_:
        raise wb.StepFailed("Nothing to watch: upload the data, pick a warehouse connection and name its tables, or choose a dashboard.")
    ctx.put("datasets", dsets_)
    rows = []
    for d in dsets_:
        cols = pdat.columns(ctx, d["ref"])
        dates, nums, texts = pdat.kind_cols(cols)
        rows.append([d["name"], d["where"], ", ".join(dates) or "-", ", ".join(nums[:6]) or "-", ", ".join(texts[:4]) or "-"])
    return {"summary": f"{len(dsets_)} dataset(s) read - read-only.", "counts": {"datasets": len(dsets_)},
            "data": {"columns": ["Dataset", "Where", "Dates", "Numbers", "Text"], "rows": rows}}


def d_shape(ctx: wb.Ctx) -> dict:
    dmap = _dmap(ctx)
    have = ctx.records(ctx.step_id)
    ids = {d["id"] for d in have}
    dets = have + [d for d in suggest(ctx, list(dmap.values())) if d["id"] not in ids]
    _validate(dets, ctx)
    on = sum(1 for d in dets if d.get("active"))
    return {"summary": f"{len(dets)} detector(s) - {on} on - suggested from the data. Change the sensitivity, write a business threshold, switch detectors on or off, then confirm the design.",
            "counts": {"detectors": len(dets), "on": on}, "records": dets, "data": _table(dets, dmap), "items": [label(d, dmap) for d in dets if d.get("active")][:6]}


def d_build(ctx: wb.Ctx) -> dict:
    import yaml
    dmap = _dmap(ctx)
    dets = [d for d in ctx.records("shape") if d.get("active")]
    probs = _validate(dets, ctx)
    if probs:
        raise wb.StepFailed("The confirmed detectors have problems: " + "; ".join(probs[:6]))
    rows, spec = [], []
    for d in dets:
        params, _ = ar.parse(d)
        ds = dmap[d["dataset"]]
        how = (f"{d.get('agg') or 'sum'} of {d['value']} by {d.get('grain')} from {ds['name']}" if d["kind"] in ar.SERIES_KINDS else f"each row of {ds['name']}" + (f" per {d['group']}" if d.get("group") else ""))
        rows.append([label(d, dmap), how, json.dumps(params)])
        spec.append({k: d.get(k) for k in ("id", "kind", "dataset", "value", "date", "grain", "agg", "group", "key", "params", "severity")} | {"parsed": params, "dataset_name": ds["name"]})
    ctx.output("detectors.yaml", yaml.safe_dump({"name": ctx.title, "detectors": spec}, sort_keys=False, allow_unicode=True), label="The detector set (YAML)")
    ctx.put("built", dets)
    return {"summary": f"{len(dets)} detector(s) compiled: each with what it reads and its parameters.", "counts": {"detectors": len(dets)},
            "data": {"columns": ["Detector", "Reads", "Parameters"], "rows": rows}}


def d_prove(ctx: wb.Ctx) -> dict:
    dets = ctx.get("built") or []
    gates, found = run_detectors(ctx, dets, _dmap(ctx), "Proof on the history")
    ctx.put("proof", {"findings": len(found), "noisy": sum(1 for g in gates if g["status"] == "fail")})
    return {"summary": f"Run on the history: {len(found)} finding(s) from {len(gates)} detector(s), each with its reason - these are what the live set would have raised. "
                       "Accept to take them to go-live, or send them back to Shape.",
            "counts": {"detectors": len(gates), "findings": len(found), "too noisy": sum(1 for g in gates if g["status"] == "fail")}, "data": {"checks": gates},
            "items": [f"{f['label']} at {f['at']}: {f['reason']}" for f in found[:6]]}


def d_ship(ctx: wb.Ctx) -> dict:
    dets = ctx.get("built") or []
    cad = ctx.scope.get("cadence") or {"every": "day", "at": "07:00", "tz": "UTC"}
    approver = db.user(ctx.st.get("approver") or "") or {}
    p = ctx.get("proof") or {}
    return {"summary": f"Go live: {len(dets)} detector(s), checked {wb.schedule_text(wb.check_schedule(cad)).lower()}.",
            "data": {"items": [{"title": "Detectors going live", "detail": ", ".join(label(d, _dmap(ctx)) for d in dets)[:600]},
                               {"title": "What the proof showed", "detail": f"{p.get('findings', 0)} finding(s) on the history, {p.get('noisy', 0)} detector(s) too noisy"},
                               {"title": "Then", "detail": "a Run item checks them on the schedule; every new finding waits for a person before an alert or a ticket goes out"},
                               {"title": "Named approval", "detail": approver.get("name") or "the owner of this work item"}]}}


def _record_lineage(ctx: wb.Ctx, s: dict) -> None:
    job = ctx.lineage_node("job", SYSTEM, f"Anomaly detection: {s['name']}", label=f"Anomaly detection: {s['name']} (v{s['version']})", properties={"set": s["id"], "version": s["version"]})
    for d in s["datasets"]:
        ctx.lineage_edge(pdat.lineage_table(ctx, d["ref"]), job, "reads", {"detectors": sum(1 for x in s["detectors"] if x.get("dataset") == d["key"])})


def _run_item(ctx: wb.Ctx, s: dict, cad: dict) -> str:
    rid = s.get("run_item")
    if rid and db.one("SELECT 1 FROM wb_items WHERE id = ? AND closed IS NULL", (rid,)):
        return rid
    p = db.project(ctx.id) or {}
    item = wb.create(MODULE, "run", f"Run: {ctx.title}"[:160], who=ctx.owner, brief=f"Scheduled checks of the detector set \"{s['name']}\", published from {ctx.id}.",
                     connections=ctx.st.get("connections") or [], scope={"set": s["id"], "schedule": cad}, approver=ctx.st.get("approver"),
                     visibility=p.get("visibility") or "private", team_id=p.get("team_id"), parent=ctx.id)
    db.run("UPDATE anomaly_sets SET run_item = ? WHERE id = ?", (item["id"], s["id"]))
    return item["id"]


def d_run(ctx: wb.Ctx) -> dict:
    s = publish(ctx, ctx.get("built") or [], list(_dmap(ctx).values()), ctx.get("set"), "go-live from Develop")
    ctx.put("set", s["id"])
    _record_lineage(ctx, s)
    cad = wb.check_schedule(ctx.scope.get("cadence") or {"every": "day", "at": "07:00", "tz": "UTC"})
    rid = _run_item(ctx, s, cad)
    return {"summary": f"Detector set \"{s['name']}\" version {s['version']} is live; the Run item checks it {wb.schedule_text(cad).lower()}.", "counts": {"version": s["version"], "detectors": len(s["detectors"])},
            "data": {"href": f"#/m/{MODULE}/i/{rid}", "label": "Open the Run item", "text": f"Version {s['version']} - {len(s['detectors'])} detector(s) - {wb.schedule_text(cad)}"}}


# ------------------------------------------------------------------ Change

def _set_or_fail(ctx: wb.Ctx) -> dict:
    s = dset(ctx.scope.get("set") or "", db.user(ctx.owner or "") or {})
    if not s:
        raise wb.StepFailed("The detector set this work item works on is not one its owner can see any more.")
    ctx.put("set", s["id"])
    ctx.put("datasets", s["datasets"])
    ctx.put("current", s["detectors"])
    ctx.put("version", s["version"])
    return s


def c_request(ctx: wb.Ctx) -> dict:
    s = _set_or_fail(ctx)
    return {"summary": f"Change to \"{s['name']}\" (version {s['version']}, {len(s['detectors'])} detectors).", "counts": {"detectors": len(s["detectors"]), "version": s["version"]},
            "data": {"text": ctx.brief or "(no request text)"}}


def c_diagnose(ctx: wb.Ctx) -> dict:
    gates, found = run_detectors(ctx, ctx.get("current") or [], _dmap(ctx), "Today")
    ctx.put("before", sorted({f["fingerprint"] for f in found}))
    return {"summary": f"Today's detectors on today's data: {len(found)} finding(s) from {len(gates)} detector(s).", "counts": {"findings": len(found)}, "data": {"checks": gates}}


def c_fix(ctx: wb.Ctx) -> dict:
    recs = ctx.records(ctx.step_id) or [dict(d) for d in ctx.get("current") or []]
    return {"summary": "Edit the detectors: change a sensitivity or a threshold, add one or switch one off. Relay dry-runs the change next.", "records": recs,
            "data": _table(recs, _dmap(ctx)), "counts": {"detectors": len(recs)}}


def c_prove(ctx: wb.Ctx) -> dict:
    after = ctx.records("fix")
    probs = _validate([d for d in after if d.get("active")], ctx) if any(d.get("active") for d in after) else ["Switch on at least one detector."]
    if probs:
        raise wb.StepFailed("The edited detectors have problems: " + "; ".join(probs[:6]))
    gates, found = run_detectors(ctx, after, _dmap(ctx), "Dry run")
    before = set(ctx.get("before") or [])
    now_ = {f["fingerprint"] for f in found}
    ctx.put("diff", {"new": len(now_ - before), "gone": len(before - now_)})
    return {"summary": f"Dry run: {len(found)} finding(s) - {len(now_ - before)} new, {len(before - now_)} no longer raised.", "counts": {"findings": len(found), "new": len(now_ - before), "gone": len(before - now_)},
            "data": {"checks": gates}}


def c_approve(ctx: wb.Ctx) -> dict:
    d = ctx.get("diff") or {}
    return {"summary": f"Release version {(ctx.get('version') or 0) + 1}: {d.get('new', 0)} new finding(s) on today's data, {d.get('gone', 0)} no longer raised.",
            "data": {"items": [{"title": "Detectors", "detail": ", ".join(label(x, _dmap(ctx)) for x in ctx.records("fix") if x.get("active"))[:600]}]}}


def c_learn(ctx: wb.Ctx) -> dict:
    s = publish(ctx, ctx.records("fix"), ctx.get("datasets") or [], ctx.get("set"), (ctx.brief or "")[:300])
    _record_lineage(ctx, s)
    return {"summary": f"Version {s['version']} of \"{s['name']}\" is live; the Run item uses it from its next check.", "counts": {"version": s["version"]},
            "data": {"href": f"#/m/{MODULE}/i/{s['run_item']}" if s.get("run_item") else f"#/m/{MODULE}/run", "label": "Open the Run item" if s.get("run_item") else "Run & support",
                     "text": f"Version {s['version']} - {len(s['detectors'])} detector(s)"}}


# ------------------------------------------------------------------ Run & support

def r_watch(ctx: wb.Ctx) -> dict:
    s = _set_or_fail(ctx)
    gates, found = run_detectors(ctx, s["detectors"], {d["key"]: d for d in s["datasets"]}, f"Run {len(ctx.st.get('rounds') or []) + 1}")
    seen = {r["fingerprint"] for r in db.q("SELECT fingerprint FROM anomaly_findings WHERE set_id = ?", (s["id"],))}
    new = [f for f in found if f["fingerprint"] not in seen]
    now = time.time()
    for f in new:
        db.run("INSERT OR IGNORE INTO anomaly_findings (id, set_id, item, fingerprint, detector, dataset, at, value, expected, reason, severity, status, created, updated) "
               "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'new', ?, ?)", ("af-" + _secrets.token_hex(5), s["id"], ctx.id, f["fingerprint"], f["detector"], f["dataset"], f["at"],
                                                                        f["value"], f["expected"], f["reason"][:500], f["severity"], now, now))
    rows = {r["fingerprint"]: r["id"] for r in db.q("SELECT id, fingerprint FROM anomaly_findings WHERE set_id = ?", (s["id"],))}
    for f in new:
        f["finding"] = rows.get(f["fingerprint"])
    ctx.put("new", new)
    _record_lineage(ctx, s)
    return {"summary": f"Version {s['version']}: {len(gates)} detector(s) run - {len(found)} finding(s), {len(new)} new since the last review.",
            "counts": {"detectors": len(gates), "findings": len(found), "new": len(new)}, "data": {"checks": gates}}


def r_alert(ctx: wb.Ctx) -> dict:
    new = ctx.get("new") or []
    if not new:
        return {"summary": "Nothing new since the last review: nothing to alert.", "next": "report", "counts": {"new": 0}}
    return {"summary": f"{len(new)} new finding(s), each with its reason - a person decides what happens to each.", "counts": {"new": len(new), "high": sum(1 for f in new if f["severity"] == "high")},
            "items": [f"{f['label']} at {f['at']}: {f['reason']}" for f in new[:6]],
            "data": {"columns": ["Detector", "Where", "Value", "Expected", "Why it is unusual", "Severity"], "rows": [[f["label"], f["at"], f["value"], f["expected"], f["reason"], f["severity"]] for f in new]}}


def r_fix(ctx: wb.Ctx) -> dict:
    have = {r["id"]: r for r in ctx.records(ctx.step_id)}
    s = dset(ctx.get("set") or "") or {"datasets": []}
    dash = {d["key"] for d in s["datasets"] if d["ref"]["source"] == "dashboard"}
    recs = []
    for f in ctx.get("new") or []:
        default = "alert" if f["kind"] in ar.SERIES_KINDS and f["dataset_key"] in dash else "ticket" if f["severity"] == "high" else "expected"
        h = have.get(f["id"]) or {}
        recs.append({**{k: f.get(k) for k in ("id", "finding", "detector", "label", "at", "reason", "severity", "value", "expected", "kind", "dataset_key", "score", "low", "high")}, "route": h.get("route") or default, "note": h.get("note") or ""})
    return {"summary": f"{len(recs)} finding(s): Relay proposes what happens to each - an alert, a ticket, expected or ignore. Nothing goes out until you confirm.", "records": recs,
            "counts": {"alerts": sum(1 for r in recs if r["route"] == "alert"), "tickets": sum(1 for r in recs if r["route"] == "ticket")},
            "data": {"columns": ["Detector", "Where", "Why it is unusual", "Proposed"], "rows": [[r["label"], r["at"], r["reason"], dict(ROUTES)[r["route"]]] for r in recs]}}


FIX_EDIT = wb.Edit(columns=[wb.Column("route", "What happens", "select", options=ROUTES), wb.Column("note", "Note", "longtext"), wb.Column("label", "Detector", readonly=True),
                            wb.Column("at", "Where", readonly=True), wb.Column("reason", "Why it is unusual", readonly=True), wb.Column("severity", "Severity", readonly=True)],
                   add=False, remove=False, label="finding")


def r_approve(ctx: wb.Ctx) -> dict:
    s = dset(ctx.get("set") or "") or {"detectors": [], "datasets": []}
    dets = {d["id"]: d for d in s["detectors"]}
    dmap = {d["key"]: d for d in s["datasets"]}
    rows, now = [], time.time()
    for r in ctx.records("fix"):
        det, ds = dets.get(r["detector"]) or {}, dmap.get(r["dataset_key"]) or {}
        if r["route"] == "alert":
            h = alert_for(ctx, r, det, ds) if det and ds else {"status": "no alert: the detector is no longer live"}
        elif r["route"] == "ticket":
            body = f"{r['reason']}\n\nDetector: {r['label']}\nWhere: {r['at']}\nValue: {r['value']} (expected {r['expected']})\n{('Note: ' + r['note']) if r.get('note') else ''}\nWork item: {wb.route_of(ctx.st)}"
            h = service_desk_ticket(ctx, f"Unusual {det.get('value') or 'value'} on {ds.get('name') or 'a dataset'} at {r['at']}"[:200], body,
                                    {"high": "P2", "medium": "P3"}.get(r["severity"], "P4"), about=ds.get("name") or "", origin=f"anomaly:{ctx.id}:{r['finding']}")
        else:
            h = {"status": {"expected": "expected - recorded, not raised again", "ignore": "ignored this time"}[r["route"]]}
        db.run("UPDATE anomaly_findings SET status = ?, route = ?, decided_by = ?, decided = ?, note = ?, handoff = ?, updated = ? WHERE id = ?",
               ({"alert": "alerted", "ticket": "ticketed", "expected": "expected", "ignore": "ignored"}[r["route"]], r["route"], ctx.who, now, (r.get("note") or "")[:500] or None,
                (h.get("status") or "")[:300], now, r["finding"]))
        rows.append([r["label"], r["at"], dict(ROUTES)[r["route"]], h.get("status") or ""])
    db.audit("anomaly.findings.decided", ctx.get("set"), {"findings": len(rows), "item": ctx.id}, ctx.who)
    return {"summary": f"{sum(1 for r in ctx.records('fix') if r['route'] == 'alert')} alert(s), {sum(1 for r in ctx.records('fix') if r['route'] == 'ticket')} ticket(s), "
                       f"{sum(1 for r in ctx.records('fix') if r['route'] in ('expected', 'ignore'))} without action - as you approved.",
            "data": {"columns": ["Detector", "Where", "Decision", "What happened"], "rows": rows}, "counts": {"decided": len(rows)}}


def r_report(ctx: wb.Ctx) -> dict:
    sid = ctx.get("set") or ""
    by = {r["status"]: r["n"] for r in db.q("SELECT status, COUNT(*) AS n FROM anomaly_findings WHERE set_id = ? GROUP BY status", (sid,))}
    rounds = (ctx.st.get("rounds") or [])[-11:]
    hist = [[time.strftime("%d %b %H:%M", time.gmtime(r["ended"])), (next((s for s in r["steps"] if s["id"] == "watch"), {}).get("counts") or {}).get("new")] for r in rounds]
    hist.append([time.strftime("%d %b %H:%M", time.gmtime()), len(ctx.get("new") or [])])
    text = f"# Anomaly run report: {ctx.title}\n\n{time.strftime('%d %B %Y %H:%M UTC', time.gmtime())}\n\n" + "".join(f"- {k}: {v}\n" for k, v in sorted(by.items())) \
        + "\n## New findings this run\n\n" + "".join(f"- {f['label']} at {f['at']}: {f['reason']}\n" for f in ctx.get("new") or []) + "\n## Recent runs\n\n" + "".join(f"- {h[0]}: {h[1]} new\n" for h in hist)
    ctx.output(f"report-{time.strftime('%Y%m%d-%H%M', time.gmtime())}.md", text, label="Run report (Markdown)")
    return {"summary": f"{len(ctx.get('new') or [])} new finding(s) this run; " + ", ".join(f"{v} {k}" for k, v in sorted(by.items())) + " in all.", "counts": {"new": len(ctx.get("new") or [])},
            "data": {"columns": ["Run", "New findings"], "rows": hist}}


def _cards(u: dict) -> list[dict]:
    rows, open_ = [], []
    for s in dsets(u):
        by = {r["status"]: r["n"] for r in db.q("SELECT status, COUNT(*) AS n FROM anomaly_findings WHERE set_id = ? GROUP BY status", (s["id"],))}
        rows.append([s["name"], f"v{s['version']}", len(s["detectors"]), by.get("new", 0), by.get("alerted", 0) + by.get("ticketed", 0), f"#/m/{MODULE}/i/{s['run_item']}" if s.get("run_item") else ""])
        open_ += [[s["name"], f["at"], f["reason"][:160], f["severity"]] for f in findings_of(s["id"], "new")[:10]]
    return [{"title": "Live detector sets", "columns": ["Detector set", "Version", "Detectors", "New findings", "Handed on", "Run item"], "rows": rows,
             "empty": "No detector set is live yet: a Develop item's Run step publishes one after its named approval."},
            {"title": "Findings waiting for a person", "columns": ["Detector set", "Where", "Why it is unusual", "Severity"], "rows": open_[:20], "empty": "Nothing waiting."}]


GUIDE = """# Anomaly & risk detection - the work item

This folder is one work item of Relay's anomaly module. Detectors are rules and plain statistics run by the app
(z-score, IQR, seasonal residuals, thresholds, row rules); every finding carries its reason and its numbers, and a
person decides what happens to it. No AI step decides or invents anything here.

- `data/`: the person's uploads; `evidence/`: each detector's findings and bounds; `outputs/`: the detector set
  (YAML), the assessment and the run reports."""

FIELDS = [wb.Field("dashboard", "A dashboard's data to watch", "select", options=pdat.dashboards_for, help="Optional: read with your access, as Ask Relay does; alerts go through Reports & alerts on it."),
          wb.Field("objects", "Warehouse tables or views", "longtext", help="One per line, e.g. FINANCE.INVOICES (with a warehouse connection)."),
          wb.Field("value", "The number to watch", help="Blank: Relay picks the likeliest (amounts, quantities, counts)."), wb.Field("grain", "Metrics by", "select", options=pdat.GRAINS, default="month")]

wb.register(wb.Pack(
    module=MODULE, guide=GUIDE,
    lineage="each dataset a detector set reads, and the detector set as a job (system \"Relay anomaly detection\")",
    platforms=PLATFORMS, schemas={"detector": DET_COLUMNS, "finding": FIX_EDIT.columns}, cards=_cards,
    work={
        "assess": wb.Work(title="See what is unusual in your numbers today", needs_source=False, steps={
            "Connect": wb.Step(kind="platform", run=a_connect, agent="Connector", text="Each source is tested - uploads, warehouses and a dashboard's data - read-only, with the owner's own access"),
            "Inventory": wb.Step(kind="platform", run=a_inventory, agent="Scanner", text="Every table with numbers to watch - you untick what is out of scope",
                                 edit=wb.Edit(columns=[wb.Column("include", "Include", "bool"), wb.Column("dataset", "Dataset", readonly=True), wb.Column("where", "Where", readonly=True),
                                                       wb.Column("numbers", "Numbers", readonly=True)], add=False, remove=False, label="dataset")),
            "Health": wb.Step(kind="proof", run=a_health, view="gates", agent="Detector", text="Detectors suggested from the data run on it today: each finding with its reason - rules and statistics, no AI"),
            "Findings": wb.Step(kind="person", run=a_findings, edit=FIND_EDIT, text="A person reviews each finding: keep what matters, ignore what does not"),
            "Estimate": wb.Step(kind="deterministic", run=a_estimate, view="plan", agent="Estimator", text="The time a person needs to put the detectors live")},
            fields=FIELDS),
        "develop": wb.Work(title="Detectors suggested from your data, proven on its history, taken live", needs_source=False, steps={
            "Describe": wb.Step(kind="platform", run=d_describe, agent="Connector", text="The data read - dates, numbers and text - read-only"),
            "Shape": wb.Step(kind="deterministic", run=d_shape, agent="Detector designer", edit=DET_EDIT, confirm="the detectors - each with its sensitivity or rule and why it is suggested",
                             text="Detectors suggested from the data - seasonal residuals, z-scores, IQR, unusual rows per group, row rules; a business threshold waits for your number"),
            "Build": wb.Step(kind="deterministic", run=d_build, agent="Detector builder", text="Each detector compiled with what it reads and its parameters, exported as YAML"),
            "Prove": wb.Step(kind="proof", run=d_prove, view="gates", agent="Prover", back_to="shape", text="Every detector run on the history: the findings it would have raised, with reasons, and how noisy it is"),
            "Ship": wb.Step(kind="person", run=d_ship, view="plan", approver=True, text="The named approver confirms what goes live and how often it runs"),
            "Run": wb.Step(kind="deterministic", run=d_run, view="link", agent="Publisher", text="The detector set is published as a new version and a Run item checks it on the schedule")},
            fields=FIELDS + [wb.Field("cadence", "Once live, check", "cadence", default={"every": "day", "at": "07:00", "tz": "UTC"})]),
        "change": wb.Work(title="Change a live detector set, with a dry run first", needs_source=False, sources=False, platforms=("files", "warehouse", "dashboards"), steps={
            "Request": wb.Step(kind="deterministic", run=c_request, view="text", agent="Detector librarian", text="The change in plain words, and the live detector set it changes"),
            "Diagnose": wb.Step(kind="proof", run=c_diagnose, view="gates", agent="Prover", text="Today's detectors on today's data, so you see what they raise before anything changes"),
            "Fix": wb.Step(kind="person", run=c_fix, edit=DET_EDIT, confirm="the edited detectors", text="You edit the detectors in place"),
            "Prove": wb.Step(kind="proof", run=c_prove, view="gates", agent="Prover", back_to="fix", text="A dry run of the edited detectors, compared with today's findings"),
            "Approve": wb.Step(kind="person", run=c_approve, view="plan", approver=True, text="The named approver releases the new version"),
            "Learn": wb.Step(kind="deterministic", run=c_learn, view="link", agent="Publisher", text="The new version is published and kept; the Run item uses it from its next check")},
            fields=[wb.Field("set", "Detector set to change", "select", options=set_options, required=True)]),
        "run": wb.Work(title="Check a live detector set on a schedule; every finding goes to a person first", needs_source=False, sources=False, platforms=("files", "warehouse", "dashboards"), steps={
            "Watch": wb.Step(kind="proof", run=r_watch, view="gates", agent="Watcher", text="The live detectors run on today's data - read-only; findings already decided are not raised again"),
            "Alert": wb.Step(kind="deterministic", run=r_alert, agent="Triage", text="New findings with their reasons and the numbers behind them"),
            "Fix": wb.Step(kind="deterministic", run=r_fix, agent="Triage", edit=FIX_EDIT, text="Relay proposes what happens to each finding - an alert, a ticket, expected or ignore - and you confirm or change it"),
            "Approve": wb.Step(kind="platform", run=r_approve, agent="Dispatcher", text="What you approved goes out: an alert through Reports & alerts, a ticket through the service desk's own write approval"),
            "Report": wb.Step(kind="deterministic", run=r_report, agent="Reporter", confirm_if=lambda ctx, out: bool(ctx.get("new")), text="A run report; you confirm it when there were new findings")},
            fields=[wb.Field("set", "Detector set to check", "select", options=set_options, required=True), wb.Field("schedule", "Check it", "cadence", default={"every": "day", "at": "07:00", "tz": "UTC"})]),
    }))
