"""Connections (registry id `connect`) on the workbench — the connections hub itself, looked after as a Systems module:
every connection a person may use (an admin: every connection in the workspace), its sign-in, scope, sharing and what
uses it. The hub page (#/connections) stays where connections are made; this module checks, fixes and watches them.

Assess   each connection signed in again (read-only, as the hub's Test does) and listed in the hub's own terms;
         rules: a sign-in that fails while dashboards or work items use it, a disabled connection something still
         uses, write access shared with the whole organisation, write access nothing uses, a connection nothing has
         used for 90 days, a key or password not renewed for a year, the same source connected twice.
Change   from the assessment or a request naming connections: scope narrowed to read, sharing narrowed to the
         owner's teams, an unused connection disabled — each after a named approver confirms, by the connection's
         owner's rights (the hub's own rules: only the owner changes scope; the owner or an admin sharing and
         switching off), read back; renewing a sign-in or merging duplicates stays a step for a person.
Run      every connection signed in again on a schedule; a failing sign-in, or a disabled connection still in use, is
         a break that goes to a person (a ticket, a Change item) only after approval.
(Develop and Migrate are not offered: a connection is made in the hub, with the owner's own sign-in.)
"""
from __future__ import annotations

import json
import time

from .. import connectors, db
from .. import workbench as wb
from . import _systems as w3

MODULE = "connect"
UNUSED_DAYS = 90
RENEW_DAYS = 365
DAY = 86400.0
CHANGEABLE = {"scope": ("read",), "sharing": ("team", "me"), "enabled": ("off",)}


# ================================================================== the connections in scope

def _in_scope(ctx) -> list[dict]:
    """The item's connections when it names some; else every connection its owner may use (an admin: all of them)."""
    rows = db.q("SELECT * FROM connections ORDER BY created")
    admin = (db.user(ctx.owner) or {}).get("org_role") == "admin"
    picked = set((ctx.st.get("connections") or []))
    out = []
    for c in rows:
        if picked and c["id"] not in picked:
            continue
        if admin or connectors.shared_with(c, ctx.owner):
            out.append({**c, "config": json.loads(c["config"] or "{}")})
    return out


def _view(c: dict, uses: dict) -> dict:
    p = connectors.public(c, None, uses)
    return {"id": c["id"], "name": c["name"], "kind": c["kind"], "label": p["label"], "category": p["category"], "owner": p["owner"], "owner_id": c["owner_id"],
            "scope": p["scope"], "sharing": p["sharing"], "enabled": p["enabled"], "status": c.get("status") or "new", "error": c.get("error") or "",
            "signin": p["signin"], "auth_mode": c.get("auth_mode"), "created": c.get("created"), "last_used": c.get("last_used"), "last_test": c.get("last_test"),
            "consented": c.get("consented") or c.get("created"), "can_write": p["can_write"],
            "used_by": [u["name"] for u in p["used_by"] if not str(u.get("id") or "").startswith(f"wb-{MODULE}-")],     # looking after a connection is not a use
            "source": _source(c), "include": True}


def _source(c: dict) -> str:
    cfg = c.get("config") or {}
    for k in ("base_url", "account", "host", "server", "organization_url", "instance_url", "project"):
        if cfg.get(k):
            return f"{c['kind']}:{str(cfg[k]).rstrip('/').lower()}" + (f"/{cfg.get('organization') or cfg.get('database') or cfg.get('service_name') or ''}".rstrip("/") if k != "project" else "")
    return ""


def _retest(c: dict, who: str) -> dict:
    """Sign in again, as the hub's Test does (the vendor sees a read; Relay records status and last test)."""
    if not c.get("enabled", 1):
        return {"status": "disabled", "error": ""}
    try:
        connectors.test({**c, "_who": who})
        return {"status": "connected", "error": ""}
    except connectors.Reconsent as e:
        return {"status": "reconsent", "error": str(e)[:300]}
    except connectors.ConnectorError as e:
        return {"status": "error", "error": str(e)[:300]}
    finally:                                   # a health check is not a use: "last used" keeps what it was
        db.run("UPDATE connections SET last_used = ? WHERE id = ?", (c.get("last_used"), c["id"]))


def _days(t) -> float | None:
    return (time.time() - float(t)) / DAY if t else None


# ================================================================== the health rules (one connection view in, findings out)

def _f(kind, c, what, severity, fix, proposals, cause="", measured=""):
    return w3.finding(kind, c["name"], "connection", c["name"], what, severity, fix=fix, cause=cause, measured=measured, work="change", keys=[c["id"]], conn=c["id"], proposals=proposals)


def _p(c, action, field="", value="", before="", why=""):
    return {"action": action, "entity": "connection", "key": c["id"], "label": c["name"], "field": field, "value": value, "before": before, "why": why}


def rules(cs: list[dict]) -> list[dict]:
    out = []
    for c in cs:
        used = c["used_by"]
        if c["enabled"] and c["status"] in ("error", "reconsent"):
            if used:
                out.append(_f("signin_failing", c, f"{c['name']} ({c['label']}) cannot sign in — {c['error'][:200]} — and {len(used)} thing(s) use it: {', '.join(used[:4])}", "high",
                              f"{c['owner']} renews the sign-in in Connections (Renew).", [_p(c, "manual", why=f"{c['owner']} renews the sign-in in Connections › {c['name']} › Renew")],
                              cause="the stored sign-in no longer works (expired, rotated or revoked)", measured=c["status"]))
            else:
                out.append(_f("signin_failing", c, f"{c['name']} ({c['label']}) cannot sign in — {c['error'][:200]} — and nothing uses it", "medium",
                              "Switch it off (nothing uses it), or renew the sign-in if it is still needed.", [_p(c, "update", "enabled", "off", "on", "nothing uses it and it cannot sign in")],
                              cause="the stored sign-in no longer works", measured=c["status"]))
        if not c["enabled"] and used:
            out.append(_f("disabled_in_use", c, f"{c['name']} is switched off but {len(used)} thing(s) still use it: {', '.join(used[:4])} — they cannot refresh or run", "high",
                          "Switch it on again, or move those items to another connection.", [_p(c, "manual", why=f"switch {c['name']} on again, or move {', '.join(used[:3])} to another connection")],
                          cause="a connection was switched off while in use", measured="switched off"))
        if c["scope"] == "write" and c["sharing"] == "org":
            out.append(_f("write_shared_org", c, f"{c['name']} can write to {c['label']} and is shared with the whole organisation — anyone can propose writes with {c['owner']}'s sign-in", "high",
                          "Share it with the owner's teams only (writes still need a named approver).", [_p(c, "update", "sharing", "team", "org", "keep write access to the owner's teams")],
                          cause="a write-capable sign-in is open to everyone", measured="write · org"))
        if c["scope"] == "write" and not used:
            out.append(_f("write_unused", c, f"{c['name']} has write access but nothing uses it", "medium", "Narrow it to read; widen it again when a change needs it.",
                          [_p(c, "update", "scope", "read", "write", "nothing uses it to write")], cause="write access granted and not needed", measured="write · unused"))
        age = _days(c["created"]) or 0
        last = _days(c["last_used"])
        if not used and age > UNUSED_DAYS and (last is None or last > UNUSED_DAYS) and c["enabled"] and c["status"] not in ("error", "reconsent"):
            out.append(_f("unused", c, f"{c['name']} has not been used for {UNUSED_DAYS}+ days (made {age:.0f} days ago) and nothing uses it", "low",
                          "Switch it off; it can be switched on again.", [_p(c, "update", "enabled", "off", "on", f"unused for {UNUSED_DAYS}+ days")], cause="a connection nobody uses", measured=f"{age:.0f} days"))
        ren = _days(c["consented"])
        if c["auth_mode"] != "oauth" and ren is not None and ren > RENEW_DAYS and c["enabled"]:
            out.append(_f("stale_secret", c, f"{c['name']}'s {c['signin'].replace('_', ' ')} was last renewed {ren:.0f} days ago", "medium",
                          f"{c['owner']} rotates the key or password at the vendor and renews it in Connections.", [_p(c, "manual", why=f"{c['owner']} rotates the secret at {c['label']} and renews it in Connections")],
                          cause=f"a key or password older than {RENEW_DAYS} days", measured=f"{ren:.0f} days"))
    by: dict[str, list] = {}
    for c in cs:
        if c["source"]:
            by.setdefault(c["source"], []).append(c)
    for src, group in by.items():
        if len(group) > 1:
            keep = sorted(group, key=lambda x: (x["status"] != "connected", x["created"] or 0))[0]
            for c in group:
                if c is keep:
                    continue
                out.append(_f("duplicate", c, f"{c['name']} connects the same source as {keep['name']} ({src.split(':', 1)[1]})", "low",
                              f"Keep {keep['name']}; move what uses {c['name']} to it, then remove {c['name']}.",
                              [_p(c, "manual", why=f"move what uses {c['name']} to {keep['name']}, then remove {c['name']} in Connections")], cause="the same source connected twice"))
    return out


# ================================================================== Assess

def a_connect(ctx):
    cs = _in_scope(ctx)
    if not cs:
        raise wb.StepFailed("There are no connections to look at: make one in Connections first.")
    retest = ctx.scope.get("retest", True) not in (False, "false", "no")
    ctx.put("last_used", {c["id"]: c.get("last_used") for c in cs})        # before the re-test (a sign-in is not a use)
    results = {c["id"]: _retest(c, ctx.owner) for c in cs} if retest else {}
    ctx.put("tested", results)
    bad = sum(1 for r in results.values() if r["status"] in ("error", "reconsent"))
    return {"summary": f"{len(cs)} connection(s) in scope" + (f"; each signed in again: {bad} cannot sign in." if retest else "; not signed in again (the last test is used)."),
            "counts": {"connections": len(cs), "failing": bad},
            "data": {"columns": ["Connection", "Kind", "Sign-in now"], "rows": [[c["name"], connectors.KINDS[c["kind"]]["label"], (results.get(c["id"]) or {}).get("status") or c.get("status")] for c in cs]}}


def a_inventory(ctx):
    uses = connectors.usage_map()
    have = {r["id"]: r for r in ctx.records(ctx.step_id)}
    rows = []
    for c in _in_scope(ctx):
        v = _view(connectors._row(c["id"]), uses)
        v["last_used"] = (ctx.get("last_used") or {}).get(v["id"], v["last_used"])
        if v["id"] in have:
            v["include"] = have[v["id"]].get("include", True)
        rows.append(v)
    eid = ctx.evidence("The connections in the hub's own terms", rows, kind="records", ok=True)
    return {"summary": f"{len(rows)} connection(s) across {len({r['kind'] for r in rows})} kind(s); {sum(1 for r in rows if r['scope'] == 'write')} can write, "
                       f"{sum(1 for r in rows if r['sharing'] == 'org')} are shared with everyone, {sum(1 for r in rows if not r['used_by'])} are used by nothing.",
            "records": [{**r, "object": r["label"], "system": r["name"], "evidence": eid} for r in rows], "counts": {"connections": len(rows)},
            "data": {"columns": ["Connection", "Kind", "Owner", "Scope", "Sharing", "On", "Sign-in", "Used by"],
                     "rows": [[r["name"], r["label"], r["owner"], r["scope"], r["sharing"], "yes" if r["enabled"] else "no", r["status"], len(r["used_by"])] for r in rows]}}


def a_health(ctx):
    cs = [r for r in ctx.records("inventory") if r.get("include")]
    fs = rules(cs)
    ctx.put("findings", fs)
    checks = []
    for c in cs:
        mine = [f for f in fs if f["conn"] == c["id"]]
        worst = min((f["severity"] for f in mine), key=lambda s: w3.SEV_ORDER[s], default=None)
        checks.append({"name": c["id"], "label": f"{c['name']} ({c['label']})", "status": "pass" if not mine else "fail" if worst == "high" else "warn", "severity": worst,
                       "measured": f"{c['status']} · {c['scope']} · {c['sharing']}", "expected": "signs in · used · least access",
                       "detail": "; ".join(f["what"] for f in mine)[:400] or "signs in; access fits its use"})
    checks.append(ctx.proof("references_real", label="Every finding names a connection in the hub", refs=[f["conn"] for f in fs], known=[c["id"] for c in _in_scope(ctx)]))
    eid = ctx.evidence("Health of each connection", {"checks": checks, "findings": fs}, kind="gates", ok=not fs)
    for x in checks:
        x.setdefault("evidence", eid)
    return {"summary": f"{len(fs)} finding(s) on {len({f['conn'] for f in fs})} connection(s): {sum(1 for f in fs if f['severity'] == 'high')} high.",
            "counts": {"findings": len(fs)}, "data": {"checks": checks}}


def a_findings(ctx):
    have = {r["id"]: r for r in ctx.records(ctx.step_id)}
    fs = [{**f, **({k: have[f["id"]][k] for k in ("decision",) if k in have[f["id"]]} if f["id"] in have else {})} for f in ctx.get("findings") or []]
    fs.sort(key=lambda f: w3.SEV_ORDER[f["severity"]])
    return {"summary": f"{len(fs)} finding(s): keep what should be fixed, ignore what is expected. Nothing changes until a Change item is approved.",
            "records": fs, "counts": {"findings": len(fs)}, "items": [f["what"][:200] for f in fs[:6]],
            "data": {"columns": ["Severity", "Connection", "What", "Fix"], "rows": [[f["severity"], f["system"], f["what"], f["fix"]] for f in fs]}}


LABELS = {"signin_failing": "Sign-ins that fail", "disabled_in_use": "Switched off while in use", "write_shared_org": "Write access shared with everyone",
          "write_unused": "Write access nothing uses", "unused": "Connections nobody uses", "stale_secret": "Keys or passwords not renewed for a year", "duplicate": "The same source twice"}
MINUTES = {"signin_failing": 15, "disabled_in_use": 20, "write_shared_org": 5, "write_unused": 5, "unused": 5, "stale_secret": 30, "duplicate": 30}


def a_estimate(ctx):
    fs = [f for f in ctx.records("findings") if f.get("decision") != "ignore"]
    by: dict[str, list] = {}
    for f in fs:
        by.setdefault(f["kind"], []).append(f)
    items = [{"title": LABELS.get(k, k), "detail": f"{len(v)} × {MINUTES.get(k, 15)} min", "effort": round(len(v) * MINUTES.get(k, 15) / 60, 1)} for k, v in by.items()]
    total = round(sum(i["effort"] for i in items), 1)
    auto = sum(1 for f in fs for p in f.get("proposals") or [] if p["action"] == "update")
    return {"summary": f"About {total} hour(s) for {len(fs)} finding(s); Relay can make {auto} of the changes after approval, the rest are steps for the owners.",
            "data": {"items": items, "total": f"{total} h", "note": "Scope, sharing and switching off are changed by Relay after approval; renewing a sign-in and merging duplicates are done by the connection's owner."}}


# ================================================================== Change

def c_request(ctx):
    """The findings to act on: an assessment's kept findings (only on the item's connections when it names some), else
    the health rules run now on the connections the item or its request names."""
    picked = set(ctx.st.get("connections") or [])
    text = (ctx.brief or "").lower()
    targets = []
    src = ctx.scope.get("from_item")
    if src:
        try:
            prev = wb._load(src)
            for s in prev["steps"]:
                if s["id"] == "findings":
                    targets += [f for f in s.get("records") or [] if f.get("decision") != "ignore" and f.get("proposals") and (not picked or f["conn"] in picked)]
        except (KeyError, FileNotFoundError):
            pass
    else:
        cs = [c for c in _in_scope(ctx) if c["id"] in picked or c["name"].lower() in text]
        uses = connectors.usage_map()
        targets = rules([_view(connectors._row(c["id"]), uses) for c in cs])
    if not targets:
        raise wb.StepFailed("The request names no connection with something to change: name it (as Connections shows it) or start from an assessment.")
    ctx.put("targets", targets)
    return {"summary": f"{len(targets)} finding(s) to act on: " + "; ".join(f"{t['system']}: {t['kind'].replace('_', ' ')}" for t in targets[:5]) + ".",
            "counts": {"targets": len(targets)}, "data": {"text": (ctx.brief or "(from the assessment)") + "\n\n" + "\n".join(f"- {t['what']}" for t in targets)}}


def c_diagnose(ctx):
    uses = connectors.usage_map()
    checks, props = [], []
    for t in ctx.get("targets") or []:
        try:
            now = _view(connectors._row(t["conn"]), uses)
        except connectors.ConnectorError:
            checks.append({"name": t["id"], "label": t["what"][:160], "status": "pass", "detail": "the connection is gone — nothing to change"})
            continue
        still = [f for f in rules([now]) if f["kind"] == t["kind"]]
        if not still and t["kind"] != "duplicate":
            checks.append({"name": t["id"], "label": t["what"][:160], "status": "pass", "detail": "no longer true — nothing to change"})
            continue
        checks.append({"name": t["id"], "label": t["what"][:160], "status": "fail" if t["severity"] == "high" else "warn", "severity": t["severity"], "detail": f"Cause: {t.get('cause') or '—'}. Fix: {t['fix']}"})
        for i, p in enumerate(t["proposals"]):
            props.append({"id": f"{w3.slug(t['id'])}-{i}", "include": True, "system": t["system"], "conn": t["conn"], "finding": t["kind"], **p})
    ctx.put("proposals", props)
    return {"summary": f"{sum(1 for c in checks if c['status'] != 'pass')} problem(s) still true; {len(props)} change(s) proposed for a person to confirm — nothing has changed yet.",
            "counts": {"changes": len(props)}, "data": {"checks": checks}}


def c_fix(ctx):
    have = {r["id"]: r for r in ctx.records(ctx.step_id)}
    recs = [{**p, **({k: have[p["id"]][k] for k in ("include", "value") if k in have[p["id"]]} if p["id"] in have else {})} for p in ctx.get("proposals") or []]
    return {"summary": f"{len(recs)} proposed change(s): untick what should not happen, then confirm. Nothing changes until the approver releases it.",
            "records": recs, "counts": {"changes": sum(1 for r in recs if r.get("include"))},
            "data": {"columns": ["Do it", "Connection", "Change", "Field", "New value", "Why"],
                     "rows": [["yes" if r.get("include") else "no", r["system"], r["action"], r.get("field") or "", r.get("value") or "", r.get("why") or ""] for r in recs]}}


def _may(field: str, c: dict, who: str) -> str | None:
    """Why `who` may not make this change by the hub's own rules (None: they may)."""
    admin = (db.user(who) or {}).get("org_role") == "admin"
    if field == "scope" and c["owner_id"] != who:
        return "only the connection's owner changes its scope"
    if field in ("sharing", "enabled") and c["owner_id"] != who and not admin:
        return "only the connection's owner or an admin changes its sharing or switches it off"
    return None


def validate_fix(recs, ctx):
    out = []
    for r in recs:
        if r.get("include") and r["action"] == "update" and r.get("value") not in CHANGEABLE.get(r.get("field"), ()):
            out.append(f"{r['label']}: Relay only narrows access here — {r['field']} can become {' or '.join(CHANGEABLE.get(r.get('field'), ('nothing',)))}")
    return out


def c_prove(ctx):
    recs = [r for r in ctx.records("fix") if r.get("include")]
    probs = validate_fix(recs, ctx)
    if probs:
        raise wb.StepFailed("The confirmed changes have problems: " + "; ".join(probs[:5]))
    uses = connectors.usage_map()
    checks = []
    for r in recs:
        if r["action"] != "update":
            checks.append({"name": r["id"], "label": f"A person does: {r.get('why')}"[:200], "status": "warn", "detail": "the connection's owner does it in Connections"})
            continue
        c = _view(connectors._row(r["conn"]), uses)
        now = {"scope": c["scope"], "sharing": c["sharing"], "enabled": "on" if c["enabled"] else "off"}[r["field"]]
        why_not = _may(r["field"], c, ctx.owner)
        hits = c["used_by"] if r["field"] in ("enabled", "scope") else []
        checks.append({"name": r["id"], "label": f"{r['label']}: {r['field']} {now} → {r['value']}", "status": "fail" if why_not else "pass", "measured": now, "expected": r["value"],
                       "detail": why_not or (f"affects {', '.join(hits[:4])}" if hits else "nothing that uses it is affected")})
    eid = ctx.evidence("Dry run", checks, kind="diff", ok=not any(x["status"] == "fail" for x in checks))
    for x in checks:
        x["evidence"] = eid
    return {"summary": f"Dry run of {len(recs)} change(s): {sum(1 for x in checks if x['status'] == 'pass')} ready, {sum(1 for x in checks if x['status'] == 'warn')} for a person, "
                       f"{sum(1 for x in checks if x['status'] == 'fail')} not allowed — nothing was changed.", "data": {"checks": checks}}


def c_approve(ctx):
    recs = [r for r in ctx.records("fix") if r.get("include")]
    return {"summary": f"Release {sum(1 for r in recs if r['action'] == 'update')} change(s) to the connections hub" + (f"; {sum(1 for r in recs if r['action'] == 'manual')} step(s) for the owners." if any(r["action"] == "manual" for r in recs) else "."),
            "data": {"items": [{"title": r["label"], "detail": f"{r['field']} → {r['value']}" if r["action"] == "update" else f"a person: {r.get('why')}"} for r in recs]}}


def c_learn(ctx):
    """Apply the approved changes through the hub's own functions, as the item's owner, and read them back."""
    recs = [r for r in ctx.records("fix") if r.get("include")]
    checks = []
    who = ctx.owner
    for r in recs:
        if r["action"] != "update":
            h = ctx._handoff({"kind": "manual", "label": f"{r['label']}: {r.get('why')}"[:200], "status": "for the connection's owner"})
            checks.append({"name": r["id"], "label": h["label"], "status": "warn", "detail": "a step for a person"})
            continue
        try:
            if r["field"] == "scope":
                connectors.set_scope(r["conn"], who, r["value"])
            elif r["field"] == "sharing":
                connectors.set_sharing(r["conn"], who, r["value"])
            elif r["field"] == "enabled":
                connectors.set_enabled(r["conn"], who, r["value"] == "on")
            db.audit("connect.change", r["conn"], {"field": r["field"], "value": r["value"], "item": ctx.id, "approver": ctx.st.get("approver")}, who)
            c = connectors._row(r["conn"])
            now = {"scope": c.get("scope"), "sharing": c.get("sharing"), "enabled": "on" if c.get("enabled") else "off"}[r["field"]]
            checks.append({"name": r["id"], "label": f"{r['label']}: {r['field']} → {r['value']}", "status": "pass" if now == r["value"] else "fail", "measured": now, "expected": r["value"],
                           "detail": "read back in the hub"})
        except connectors.ConnectorError as e:
            checks.append({"name": r["id"], "label": f"{r['label']}: {r['field']} → {r['value']}", "status": "fail", "detail": str(e)[:200]})
    return {"summary": f"{sum(1 for x in checks if x['status'] == 'pass')} change(s) made and read back; {sum(1 for x in checks if x['status'] == 'warn')} for the owners; "
                       f"{sum(1 for x in checks if x['status'] == 'fail')} failed.", "data": {"checks": checks}, "ok": not any(x["status"] == "fail" for x in checks)}


# ================================================================== Run

def watch_connections(ctx, seen=None) -> list[dict]:
    uses = connectors.usage_map()
    out = []
    for c in _in_scope(ctx):
        t = _retest(c, ctx.owner)
        v = _view(connectors._row(c["id"]), uses)
        bad = None
        if t["status"] in ("error", "reconsent"):
            bad = f"cannot sign in: {t['error'][:200]}"
        elif not v["enabled"] and v["used_by"]:
            bad = f"switched off while {len(v['used_by'])} thing(s) use it: {', '.join(v['used_by'][:3])}"
        row = {"name": f"conn:{c['id']}", "label": f"{c['name']} ({v['label']})", "status": "fail" if bad else "pass", "measured": t["status"], "expected": "connected",
               "detail": bad or (f"signs in; used by {len(v['used_by'])}" if v["used_by"] else "signs in")}
        if bad:
            row["break"] = {"conn": c["id"], "system": c["name"], "job": c["name"], "label": f"{c['name']} sign-in" if t["status"] != "disabled" else f"{c['name']} switched off",
                            "status": "failed", "streak": 1, "error": bad, "since": c.get("last_used"), "run": "", "route": "ticket",
                            "cause": "the stored sign-in no longer works" if t["status"] != "disabled" else "switched off while in use",
                            "fix": f"{v['owner']} renews it in Connections" if t["status"] != "disabled" else "switch it on again or move what uses it"}
        out.append(row)
    return out


SPEC = w3.Spec(module=MODULE, noun="connections", system="Relay connections", entities=("connection",), monitors=[watch_connections])


def _run_work() -> wb.Work:
    w = w3.run_work(SPEC, "Watch every connection's sign-in; breaks go to a person first")
    w.needs_source = False
    w.sources = False
    old = w.steps["Watch"]

    def watch(ctx):
        checks, breaks = [], []
        for g in watch_connections(ctx):
            checks.append({k: v for k, v in g.items() if k != "break"})
            if g.get("break"):
                breaks.append(g["break"])
        ctx.put("breaks", breaks)
        eid = ctx.evidence("What was watched", {"checks": checks}, kind="watch", ok=not breaks)
        for x in checks:
            x.setdefault("evidence", eid)
        return {"summary": f"{len(checks)} connection(s) signed in again: {len(breaks)} need attention.", "counts": {"watched": len(checks), "breaks": len(breaks)}, "data": {"checks": checks}}
    w.steps["Watch"] = wb.Step(kind="proof", run=watch, view="gates", agent="Watcher", text="Every connection signed in again, read-only — the sign-in, and whether something switched off is still in use")
    del old
    return w


class Hub(wb.Platform):
    id, label = "relay", "Relay's connections hub"

    @property
    def kinds(self) -> tuple:                # every kind the hub knows (read when asked: later packs add theirs)
        return tuple(connectors.KINDS)

    uploads = ()
    simulator = "the mock-lab simulators behind each connection"
    reads = "every connection you may use (an admin: all of them): sign-in, scope, sharing and what uses it — Relay's own records"


GUIDE = """# Connections — the work item

Relay's connections module reads the connections hub — each connection's sign-in, scope, sharing and what uses it —
and narrows access (scope to read, sharing to teams, switched off) only after a named person approves that very
change, by the hub's own rules. Renewing a sign-in is the owner's step. Never invent a connection or a use."""

wb.register(wb.Pack(
    module=MODULE, guide=GUIDE, platforms={"relay": Hub()},
    lineage="each connection as a system node; a change to its access recorded in the audit log",
    schemas={"inventory": ["include", "name", "scope", "sharing"], "finding": ["decision", "severity", "system", "what"]},
    work={
        "assess": wb.Work(title="See which connections fail, are open too widely, or nothing uses", needs_source=False, sources=False,
                          fields=[wb.Field("retest", "Sign in to each connection again", "bool", default=True)], steps={
            "Connect": wb.Step(kind="platform", run=a_connect, agent="Reader", confirm=False, text="Every connection you may use, each signed in again — read-only at the vendor"),
            "Inventory": wb.Step(kind="platform", run=a_inventory, agent="Scanner", text="Each connection in the hub's own terms: kind, owner, scope, sharing, sign-in and what uses it",
                                 edit=wb.Edit(columns=[wb.Column("include", "Include", "bool"), wb.Column("name", "Connection", readonly=True), wb.Column("scope", "Scope", readonly=True),
                                                       wb.Column("sharing", "Sharing", readonly=True)], add=False, remove=False, label="connection")),
            "Health": wb.Step(kind="proof", run=a_health, view="gates", agent="Checker", confirm=False, text="Failing sign-ins, switched-off connections in use, access wider than its use, unused and old secrets, duplicates"),
            "Findings": wb.Step(kind="deterministic", run=a_findings, agent="Checker", text="The findings, for you to keep or ignore",
                                edit=wb.Edit(columns=[wb.Column("decision", "Decision", "select", options=(("keep", "Keep"), ("ignore", "Ignore"))), wb.Column("severity", "Severity", readonly=True),
                                                      wb.Column("system", "Connection", readonly=True), wb.Column("what", "What", readonly=True)], add=False, remove=False, label="finding")),
            "Estimate": wb.Step(kind="deterministic", run=a_estimate, view="plan", agent="Estimator", text="Effort to fix what you kept, and what Relay changes itself after approval"),
        }),
        "change": wb.Work(title="Narrow a connection's access or switch it off, released with approval", needs_source=False, sources=True, steps={
            "Request": wb.Step(kind="deterministic", run=c_request, view="text", agent="Reader", confirm=False, text="From an assessment, or a request naming the connections"),
            "Diagnose": wb.Step(kind="platform", run=c_diagnose, view="gates", agent="Checker", text="Each finding checked again against the hub now"),
            "Fix": wb.Step(kind="deterministic", run=c_fix, agent="Fixer", edit=wb.Edit(columns=[wb.Column("include", "Do it", "bool"), wb.Column("system", "Connection", readonly=True),
                                                                                                 wb.Column("field", "Field", readonly=True), wb.Column("value", "New value", readonly=True),
                                                                                                 wb.Column("why", "Why", readonly=True)], add=False, remove=False, validate=validate_fix, label="change"),
                           text="The proposed changes: untick what should not happen"),
            "Prove": wb.Step(kind="proof", run=c_prove, view="gates", agent="Checker", confirm=False, text="Dry run: what changes, who may make it by the hub's rules, and what it affects"),
            "Approve": wb.Step(kind="person", run=c_approve, view="plan", approver=True, text="A named approver releases the changes"),
            "Learn": wb.Step(kind="platform", run=c_learn, view="gates", agent="Dispatcher", confirm=False, text="The changes made through the hub's own rules and read back; the owners' steps handed to them"),
        }),
        "run": _run_work(),
    }))
