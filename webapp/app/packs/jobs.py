"""Job scheduling & orchestration (registry id `jobs`) - the batch estate on Control-M and AutoSys (adapters in
jobs_platforms.py), cron files, and the W2 kit's run history, diagnosis and approvals (_w2.py).

Assess   Connect -> Inventory -> Health -> Findings -> Estimate: every job with its schedule, command and the jobs it waits
         for; rules: a job that ends not OK (its cause from its own output: a renamed source column, a robot's changed
         screen), the jobs held back behind it, a password on a command line, a file that arrives late, a job running far
         longer than it used to, two versions of one job, jobs nobody schedules any more.
Change   Request -> Diagnose -> Fix -> Prove -> Approve -> Learn (Control-M): a failing job diagnosed from its runs and
         output; its definition changed in a copy (a parameter), validated by Control-M's own build (nothing written);
         the named approver releases it; after its own approval the folder is deployed, the failed order rerun, and the
         jobs that waited for it watched until they end; the fix kept as a rule.
Migrate  Discover -> Decide -> Convert -> Prove -> Hand over -> Run: cron jobs (crontab files) to Control-M: a commented-out
         line retires, each job becomes a Control-M job by rules, proven by Control-M's build and by the next run times
         on both sides agreeing, signed off, deployed after approval.
Run      Watch -> Alert -> Fix -> Approve -> Report: Control-M's orders since the last round; jobs that end not OK or wait
         behind one grouped by cause; a person routes each (a Change item, Self-healing, a rerun after approval, a ticket).
(Develop is not offered yet: a new job is designed with its pipeline - Data pipelines or Workflows hand it over.)
"""
from __future__ import annotations

import calendar
import json
import re
import time
from datetime import datetime, timedelta, timezone

from .. import connectors, db
from .. import workbench as wb
from . import _w2
from . import jobs_platforms as jp
from . import n8n as n8

MODULE = "jobs"


class SchedPlatform(wb.Platform):
    def __init__(self, label: str, kinds: tuple, uploads: tuple, simulator: str, reads: str):
        self.label, self.kinds, self.uploads, self.simulator, self.reads = label, kinds, uploads, simulator, reads


PLATFORMS = {
    "controlm": SchedPlatform("Control-M", ("controlm_api",), (".json",), jp.ControlMApi.simulator,
                              "folders and job definitions, orders and their output - read-only; a changed folder, a rerun or a new folder only after approval"),
    "autosys": SchedPlatform("AutoSys", ("autosys_aews",), (".jil",), jp.AutoSysAews.simulator, "jobs, their JIL and run history"),
    "cron": SchedPlatform("cron (crontab files)", (), (".tab", ".cron", ".txt"), "tests/mocklab/sims/schedulers.py: cron (files)", "crontab files you upload"),
}


# ================================================================== the estate

def _uploads(ctx: wb.Ctx):
    autos, rows = [], []
    for f in ctx.files(()):
        if f["name"].lower().endswith((".pdf", ".png", ".jpg")):
            continue
        got = jp.parse_file(f["name"], (ctx.dir / "data" / f["name"]).read_bytes())
        if not got.get("kind"):
            continue
        for a in got["autos"]:
            a.update(connection=None, platform_label=f"{got['kind']} (upload)", upload=f["name"])
        autos += got["autos"]
        rows.append({"source": f["name"], "kind": got["kind"], "ok": True, "sees": f"{len(got['autos'])} job(s)"})
    return autos, [], rows


def _estate(ctx: wb.Ctx):
    autos, runs, rows = _w2.read_estate(ctx, jp.SCHEDULERS, since_days=30)
    ua, ur, urow = _uploads(ctx)
    return autos + ua, runs + ur, rows + urow


def _dur(r):
    return (r["end"] - r["start"]) if r.get("end") and r.get("start") else None


def job_findings(autos: list[dict], runs: list[dict]) -> list[dict]:
    """The kit's rules (failing, secrets, retire, flaky, slow, no owner) and the scheduler's own."""
    fs = [f for f in _w2.findings(autos, runs) if f["kind"] != "api_candidate"]
    by = {a["id"]: a for a in autos}
    failing = {f["auto"] for f in fs if f["kind"] == "failing"}

    def add(a, kind, sev, what, do, **x):
        fs.append({"id": f"{kind}-{_w2.slug(a['platform'], 16)}-{_w2.slug(a['id'], 40)}", "auto": a["id"], "flow": a["name"], "platform": a.get("platform_label") or a["platform"], "kind": kind,
                   "severity": sev, "what": what, "do": do, "decision": "keep", **x})
    for a in autos:
        mine = sorted([r for r in runs if r["target"] == a["id"]], key=lambda r: r["start"] or 0)
        up = [d for d in a.get("deps") or [] if d in failing]
        waits = [r for r in mine[-3:] if r["status"] == "waiting"]
        if up and waits:
            names = [u.split(":", 1)[-1] for u in up]
            add(a, "held", "high", f"Held back for {len(waits)} order(s): it waits for {', '.join(names)}, which ends not OK", f"fix {', '.join(names)}; {a['name']} starts when it ends OK",
                upstream=names)
        if a.get("watcher"):
            late = [r for r in mine if r["status"] == "failed" and "not found within" in (r["error"] or "")]
            if late:
                add(a, "late_file", "medium", f"The file arrived late on {len(late)} of {len(mine)} day(s): the watcher timed out and what waits for it did not run",
                    "agree the arrival time with the sender, or give the watcher a longer window")
        ds = [(r["start"], _dur(r)) for r in mine if r["status"] == "success" and _dur(r)]
        if len(ds) >= 10:
            cut = max(t for t, _ in ds) - 6 * 86400
            before = sorted(d for t, d in ds if t < cut)
            after = sorted(d for t, d in ds if t >= cut)
            if before and after:
                ratio = after[len(after) // 2] / max(1, before[len(before) // 2])
                if ratio >= 2:
                    add(a, "slower", "medium", f"Runs {ratio:.1f} times longer for the last 6 days ({after[len(after) // 2] / 60:.0f} min against {before[len(before) // 2] / 60:.0f})",
                        "see what changed in its source or its target (volume, an index, a lock)")
        base = re.sub(r"_V\d+$", "", a["name"])
        if base != a["name"] and f"{a['platform']}:{base}" in by:
            add(a, "duplicate", "medium", f"A second version of {base}: both run", f"keep one of {base} and {a['name']}")
    for f in fs:
        if f["kind"] == "failing" and f.get("signature") == "screen_changed":
            f["do"] = "fix the robot in RPA (a rerun fails again: the screen changed, not the schedule)"
    return fs


def a_connect(ctx: wb.Ctx) -> dict:
    autos, runs, rows = _estate(ctx)
    if not rows:
        raise wb.StepFailed("Nothing to read: pick a scheduler connection (Control-M, AutoSys) or upload crontab files or a JIL export.")
    good = [r for r in rows if r["ok"]]
    if not good:
        raise wb.StepFailed("None of the sources answered: " + "; ".join(f"{r['source']}: {r['sees']}" for r in rows)[:600])
    n8._save(ctx, "estate.json", {"autos": autos, "runs": runs})
    for r in rows:
        ctx.evidence(f"Read: {r['source']}", r, kind="read", ok=r["ok"])
    return {"summary": f"{len(good)} of {len(rows)} source(s) answered: {len(autos)} job(s), {len(runs)} run(s) - read-only.", "counts": {"sources": len(rows), "jobs": len(autos), "runs": len(runs)},
            "data": _w2.table(["Source", "Kind", "Status", "What Relay sees"], [[r["source"], r["kind"], "answered" if r["ok"] else "refused", r["sees"]] for r in rows])}


def a_inventory(ctx: wb.Ctx) -> dict:
    est = n8._read(ctx, "estate.json", {})
    have = {r["id"]: r for r in ctx.records(ctx.step_id)}
    recs = []
    for a in est.get("autos") or []:
        h = _w2.history(est.get("runs") or [], a["id"])
        rid = f"{a['platform']}:{a['id']}"
        recs.append({"id": rid, "include": (have.get(rid) or {}).get("include", True), "flow": a["name"], "platform": a.get("platform_label") or a["platform"], "folder": a.get("folder"),
                     "schedule": a.get("schedule") or "not scheduled", "waits_for": ", ".join(d.split(":", 1)[-1] for d in a.get("deps") or []), "runs": h["runs"], "failed": h["failed"], "auto": a["id"]})
    if not recs:
        raise wb.StepFailed("The sources show no jobs.")
    return {"summary": f"{len(recs)} job(s) in {len({r['folder'] for r in recs})} folder(s), {sum(1 for r in recs if r['waits_for'])} waiting for others - untick what is out of scope.",
            "records": recs, "counts": {"jobs": len(recs)},
            "data": _w2.table(["Job", "Platform", "Folder", "Schedule", "Waits for", "Runs", "Failed"], [[r["flow"], r["platform"], r["folder"], r["schedule"], r["waits_for"], r["runs"], r["failed"]] for r in recs])}


INV_EDIT = wb.Edit(columns=[wb.Column("include", "Include", "bool"), wb.Column("flow", "Job", readonly=True), wb.Column("schedule", "Schedule", readonly=True), wb.Column("waits_for", "Waits for", readonly=True)],
                   add=False, remove=False, label="job")


def a_health(ctx: wb.Ctx) -> dict:
    autos, runs = n8._included(ctx)
    if not autos:
        raise wb.StepFailed("No job is included: tick at least one in the inventory.")
    fs = job_findings(autos, runs)
    ctx.put("findings", fs)
    eid = ctx.evidence("Findings by rule", {"rows": fs}, kind="findings", ok=True)
    checks = []
    for a in autos:
        mine = [f for f in fs if f["auto"] == a["id"]]
        worst = "fail" if any(f["severity"] == "high" for f in mine) else "warn" if any(f["severity"] == "medium" for f in mine) else "pass"
        h = _w2.history(runs, a["id"])
        checks.append(_w2.gate(f"job-{_w2.slug(a['id'])}", f"{a['name']} ({a.get('platform_label') or a['platform']})", worst, f"{h['runs']} run(s), {h['failed']} not OK", "no high or medium finding",
                               "; ".join(f["what"] for f in mine)[:400] or "healthy", evidence=eid))
    t = {k: sum(1 for f in fs if f["kind"] == k) for k in ("failing", "held", "secret", "late_file", "slower", "duplicate", "retire")}
    return {"summary": f"{len(autos)} job(s) checked: {t['failing']} ending not OK, {t['held']} held back behind them, {t['secret']} with a password on the command line, "
                       f"{t['late_file']} late file, {t['slower']} slower, {t['duplicate']} duplicate, {t['retire']} to retire.",
            "counts": {"jobs": len(autos), "findings": len(fs)}, "data": _w2.gates(checks)}


MINUTES = {"failing": 90, "held": 0, "secret": 30, "late_file": 45, "slower": 60, "duplicate": 30, "retire": 10, "flaky": 60, "no_owner": 5}


def a_estimate(ctx: wb.Ctx) -> dict:
    kept = [f for f in ctx.records("findings") if f.get("decision") != "ignore"]
    by: dict = {}
    for f in kept:
        by.setdefault(f["kind"], []).append(f)
    items = [{"title": {"failing": "Fix what ends not OK", "held": "What waits behind it (starts once fixed)", "secret": "Take passwords off command lines", "late_file": "Agree file arrival times",
                        "slower": "Find what slowed down", "duplicate": "Keep one version", "retire": "Retire what nobody schedules", "flaky": "Steady the flaky ones", "no_owner": "Name an owner"}.get(k, k),
              "detail": f"{len(v)} × {MINUTES.get(k, 30)} min", "effort": f"{len(v) * MINUTES.get(k, 30) / 60:.1f} h"} for k, v in by.items()]
    total = sum(len(v) * MINUTES.get(k, 30) for k, v in by.items()) / 60
    return {"summary": f"About {total:.1f} h for {len(kept)} finding(s).", "data": {"items": items, "total": f"{total:.1f} h", "note": "; ".join(f"{v} min to {k}" for k, v in MINUTES.items())}}


# ================================================================== Fix / change (Control-M and AutoSys)

SCHED_KINDS = ("controlm_api", "autosys_aews")


def _sched(ctx: wb.Ctx, *, write: bool = False) -> tuple[dict, object]:
    cs = [c for c in ctx.connections() if c["kind"] in SCHED_KINDS]
    if not cs:
        raise wb.StepFailed("Start the work item with the Control-M or AutoSys connection the job runs on.")
    if write and not connectors.may_write(cs[0]):
        raise wb.StepFailed(f"{cs[0]['name']} is read-only: change its scope to \"Read & write - with approval\" so the release can be approved.")
    return cs[0], (jp.ControlMApi() if cs[0]["kind"] == "controlm_api" else jp.AutoSysAews())


def _ctm(ctx: wb.Ctx, *, write: bool = False) -> dict:
    """The item's Control-M connection (a migration also has the AutoSys one it moves from)."""
    c = next((x for x in ctx.connections() if x["kind"] == "controlm_api"), None)
    if not c:
        raise wb.StepFailed("This step needs the Control-M connection.")
    if write and not connectors.may_write(c):
        raise wb.StepFailed(f"{c['name']} is read-only: change its scope to \"Read & write - with approval\" so the deploy can be approved.")
    return c


def _vars(d: dict, kind: str) -> dict:
    if kind == "controlm_api":
        return {k: v for x in d.get("Variables") or [] for k, v in x.items()}
    return dict(x.strip().split("=", 1) for x in str(d.get("envvars") or "").split(",") if "=" in x)


def c_request(ctx: wb.Ctx) -> dict:
    c, a = _sched(ctx)
    want = str(ctx.scope.get("job") or "").strip().upper()
    jobs = a.estate(c)
    j = next((x for x in jobs if x["name"].upper() == want), None)
    if not j:
        raise wb.StepFailed(f"No job named \"{ctx.scope.get('job')}\" on {c['name']}: " + ", ".join(x["name"] for x in jobs[:10]))
    runs = a.runs(c, jobs)
    mine = [r for r in runs if r["target"] == j["id"]]
    down = [x["id"] for x in jobs if j["id"] in (x.get("deps") or [])]
    n8._save(ctx, "flow.json", {"workflow": {k: v for k, v in j.items() if k != "definition"}, "definition": j["definition"], "runs": mine, "kind": c["kind"],
                                "downstream": [r for r in runs if r["target"] in down], "downstream_names": [d.split(":", 1)[1] for d in down]})
    h = _w2.history(mine, j["id"])
    note = " AutoSys's web services give a failed run's exit code, not its error words: the change comes from a rule Relay learned or from you." if c["kind"] == "autosys_aews" else ""
    return {"summary": f"{j['name']} on {c['name']}: {h['runs']} run(s), {h['failed']} ended not OK" + (f", failing for {h['failing_days']:g} day(s)" if h["failing_days"] else "")
                       + (f"; {', '.join(d.split(':', 1)[1] for d in down)} wait(s) for it." if down else ".") + note, "counts": {"runs": h["runs"], "failed": h["failed"]},
            "data": _w2.table(["Run", "Status", "Started", "Error"], [[r["id"], r["status"], _w2.when(r["start"]), (r.get("error") or "")[:160]] for r in sorted(mine, key=lambda x: -(x["start"] or 0))[:30]])}


def _learned_changes(vars_: dict) -> list[dict]:
    """Fixes Relay learned on any scheduler that name a variable and its old value - proposed where this job has that value."""
    out = []
    for r in db.q("SELECT * FROM w2_fix_rules WHERE module = ? ORDER BY updated DESC", (MODULE,)):
        f = _w2.j(r["fix"], {})
        if f.get("variable") and vars_.get(f["variable"]) == f.get("now") and f.get("new"):
            out.append({"variable": f["variable"], "now": f["now"], "new": f["new"], "why": f"learned from {r['learned_from']}: {f.get('text') or r['cause']}"})
    return out


def c_fix(ctx: wb.Ctx) -> dict:
    have = ctx.records(ctx.step_id)
    f = n8._read(ctx, "flow.json", {}) or {}
    kind = f.get("kind") or "controlm_api"
    vars_ = _vars(f.get("definition") or {}, kind)
    recs = have or []
    if not have:
        for dg in ctx.records("diagnose"):
            if dg["fix"] == "change_parameter":
                col = (re.search(r'"(\w+)": invalid identifier', dg.get("last_error") or "") or [None, ""])[1]
                var = next((k for k, v in vars_.items() if v == col), "")
                learned = (_w2.learned_fix(MODULE, dg["signature"]) or {}).get("fix", {})
                recs.append({"id": f"c-{dg['id']}", "variable": var, "now": vars_.get(var, ""), "new": str(ctx.scope.get("value") or learned.get("new") or ""), "why": dg["cure"]})
        if not recs:
            recs = [{"id": f"l-{i}", **x} for i, x in enumerate(_learned_changes(vars_))]
        if not recs and ctx.scope.get("variable"):
            v = str(ctx.scope["variable"])
            recs = [{"id": "p-0", "variable": v, "now": vars_.get(v, ""), "new": str(ctx.scope.get("value") or ""), "why": "the change you named"}]
    where = "Control-M" if kind == "controlm_api" else "AutoSys"
    return {"summary": (f"{len(recs)} change(s) to the definition, on a copy: " + "; ".join(f"{r['variable']} {r['now']} {r['new'] or '(type the new value)'}" for r in recs)
                        + f". Nothing changes on {where} until the release is approved.") if recs else "No rule knows a change for this: name the variable and its new value (the work item's fields).",
            "records": recs, "counts": {"changes": len(recs)}, "items": _fix_problems(recs, ctx)[:6],
            "data": _w2.table(["Variable", "Now", "New value", "Why"], [[r["variable"], r["now"], r["new"], r["why"]] for r in recs])}


def _fix_problems(recs, ctx) -> list[str]:
    f = n8._read(ctx, "flow.json", {}) or {}
    vars_ = set(_vars(f.get("definition") or {}, f.get("kind") or "controlm_api"))
    out = [] if recs else ["add the change: the variable and its new value"]
    for r in recs:
        if r.get("variable") not in vars_:
            out.append(f"{r.get('variable')!r} is not a variable of the job")
        if not str(r.get("new") or "").strip():
            out.append(f"type the new value for {r.get('variable')}")
        elif re.search(r"[\s%\"',=]", str(r["new"])):
            out.append(f"{r['variable']}: the value has no spaces, quotes, commas, = or %%")
    return out


FIX_EDIT = wb.Edit(columns=[wb.Column("variable", "Variable", readonly=True), wb.Column("now", "Now", readonly=True), wb.Column("new", "New value"), wb.Column("why", "Why", readonly=True)],
                   add=False, remove=False, validate=lambda recs, ctx: _fix_problems(recs, ctx), label="change")


def _changed(ctx) -> tuple[str, dict, dict]:
    f = n8._read(ctx, "flow.json", {}) or {}
    j, d = f.get("workflow") or {}, json.loads(json.dumps(f.get("definition") or {}))
    new = {r["variable"]: r["new"] for r in ctx.records("fix")}
    if (f.get("kind") or "controlm_api") == "controlm_api":
        d["Variables"] = [{k: new.get(k, v)} for x in d.get("Variables") or [] for k, v in x.items()]
    else:
        d["envvars"] = ", ".join(f"{k}={new.get(k, v)}" for k, v in _vars(d, "autosys_aews").items())
    return j.get("folder"), j, d


def c_prove(ctx: wb.Ctx) -> dict:
    f = n8._read(ctx, "flow.json", {}) or {}
    folder, j, newdef = _changed(ctx)
    old = f.get("definition") or {}
    diff = sorted(k for k in set(old) | set(newdef) if old.get(k) != newdef.get(k))
    down = f.get("downstream_names") or []
    if (f.get("kind") or "controlm_api") == "controlm_api":
        c = _ctm(ctx)
        a = jp.ControlMApi()
        full = {**(a.folders(c).get(folder) or {}), j["name"]: newdef}
        probs = a.build(c, folder, full)
        rows = [_w2.gate("scope", "Only the job's variables differ", "pass" if diff == ["Variables"] else "fail", ", ".join(diff) or "nothing", "Variables"),
                _w2.gate("build", "Control-M's build accepts the changed folder (nothing is written)", "fail" if probs else "pass", "; ".join(probs)[:300] or "valid", "valid")]
        ctx.put("folder_def", full)
        ctx.output(f"{folder}.json", json.dumps({folder: full}, indent=2), label=f"The changed folder {folder} (JSON)")
        said = "Control-M's build " + ("refuses it." if probs else "accepts the folder.")
    else:
        jil = f"update_job: {j['name']}\nenvvars: {newdef['envvars']}\n"
        back = jp.parse_jil(f"insert_job: {j['name']}   job_type: CMD\nenvvars: {newdef['envvars']}\n").get(j["name"], {})
        rows = [_w2.gate("scope", "Only the job's environment variables differ", "pass" if diff == ["envvars"] else "fail", ", ".join(diff) or "nothing", "envvars"),
                _w2.gate("jil", "The JIL reads back as written", "pass" if back.get("envvars") == newdef["envvars"] else "fail", jil.strip(), "update_job with envvars"),
                _w2.gate("server", "AutoSys checks the JIL when it is applied (its web services have no dry run): a refusal stops the release", "skip")]
        ctx.put("jil", jil)
        ctx.output(f"{j['name']}.jil", jil, label=f"The JIL update for {j['name']}")
        said = "the JIL update is ready."
    rows.append(_w2.gate("downstream", "What waits for it starts once it ends OK", "pass", ", ".join(down) or "nothing waits", detail="watched after the rerun"))
    bad = [g for g in rows if g["status"] == "fail"]
    return {"summary": f"The change touches {', '.join(diff) or 'nothing'} of {j['name']}; {said}" + (f" Then {', '.join(down)} start." if down else ""),
            "counts": {"fail": len(bad)}, "data": _w2.gates(rows), "ok": not bad}


def c_approve(ctx: wb.Ctx) -> dict:
    f = n8._read(ctx, "flow.json", {}) or {}
    folder, j, _ = _changed(ctx)
    how = (f"Deploy {folder} with the changed {j['name']}, rerun its failed order and watch what waits for it." if (f.get("kind") or "controlm_api") == "controlm_api"
           else f"Update {j['name']}'s JIL on AutoSys, restart it and watch what waits for it.")
    return {"summary": how, "data": {"items": [{"title": "The change", "detail": "; ".join(f"{r['variable']}: {r['now']} {r['new']}" for r in ctx.records("fix"))},
                                               {"title": "Then", "detail": "The change is applied, the job run again and the jobs that waited for it watched - one approval for exactly that; the fix is kept as a rule."}]}}


def c_learn(ctx: wb.Ctx) -> dict:
    p = _w2.push_of(ctx.id, ctx.step_id)
    if not p or p["status"] in ("failed", "refused"):
        c, _ = _sched(ctx, write=True)
        folder, j, _ = _changed(ctx)
        f = n8._read(ctx, "flow.json", {}) or {}
        if c["kind"] == "controlm_api":
            failed = sorted([r for r in f.get("runs") or [] if r["status"] == "failed"], key=lambda r: r["start"] or 0)
            last = failed[-1] if failed else None
            waits = [r["id"] for r in f.get("downstream") or [] if r["status"] == "waiting" and last and r.get("odate") == last.get("odate")]
            _w2.request_push(ctx, c["id"], "deploy_rerun", {"folder": folder, "definition": ctx.get("folder_def"), "rerun": [last["id"]] if last else [], "watch": waits},
                             f"Deploy {folder} on {c['name']}, rerun {j['name']} and watch what waits for it",
                             items=[f"Where: {c['name']}", f"Folder: {folder} (only {j['name']}'s variables change)", f"Rerun: {last['id'] if last else 'none'}", f"Then watched: {', '.join(waits) or 'nothing'}"])
        else:
            _w2.request_push(ctx, c["id"], "update_restart", {"job": j["name"], "jil": ctx.get("jil"), "watch": f.get("downstream_names") or []},
                             f"Update {j['name']} on {c['name']}, restart it and watch what waits for it",
                             items=[f"Where: {c['name']}", f"JIL: {ctx.get('jil')}", f"Then watched: {', '.join(f.get('downstream_names') or []) or 'nothing'}"])
    return _learn_view(ctx)


def _learn_view(ctx: wb.Ctx) -> dict:
    p = _w2.push_of(ctx.id, "learn")
    if p and p["status"] == "written":
        re_, down = p["result"].get("reruns") or [], p["result"].get("downstream") or []
        if not ctx.get("learned"):
            fx = (ctx.records("fix") or [{}])[0]
            for d in ctx.records("diagnose"):
                sig = d["signature"] if d["signature"] != "unknown" else f"param:{fx.get('variable')}"     # no error words: kept by the variable it changed
                _w2.learn_fix(ctx, sig, d["cause"], {"text": d["cure"], "variable": fx.get("variable"), "now": fx.get("now"), "new": fx.get("new")})
            ctx.put("learned", True)
        ok_ = all(r["status"] == "success" for r in re_)
        return {"summary": f"Released: the change is applied; the rerun {'ended OK' if ok_ else 'ended not OK'}" + (f"; then {', '.join(f'{x['job']} {x['status']}' for x in down)}." if down else ".")
                + " The fix is kept as a rule.", "counts": {"reruns": len(re_), "downstream": len(down)},
                "data": _w2.table(["Job", "Status"], [[r["id"], r["status"]] for r in re_] + [[x["job"], x["status"]] for x in down])}
    if p and p["status"] == "awaiting":
        return {"summary": "The change and the rerun wait for their own approval in the Validation queue.", "data": {"href": "#/validate", "label": "Open the Validation queue", "text": p["what"]}}
    return {"summary": f"Not released ({(p or {}).get('status') or 'not asked'}): run this step again.", "data": {"text": str(((p or {}).get("result") or {}).get("error") or "")}}


_w2.REFRESH["jobs.change.learn"] = _learn_view


# ================================================================== Migrate (cron or AutoSys -> Control-M)

DOW = {"0": "SUN", "1": "MON", "2": "TUE", "3": "WED", "4": "THU", "5": "FRI", "6": "SAT", "7": "SUN"}
JIL_DOW = {"mo": "MON", "tu": "TUE", "we": "WED", "th": "THU", "fr": "FRI", "sa": "SAT", "su": "SUN"}
JIL_COND = re.compile(r"\b([a-z])\((\w+)(?:,[^)]*)?\)", re.I)
JIL_VARS = (("$AUTO_JOB_NAME", "%%JOBNAME"), ("$AUTORUN", "%%RUNCOUNT"), ("%AUTO_JOB_NAME%", "%%JOBNAME"), ("%AUTORUN%", "%%RUNCOUNT"))
MOVES = ("cron", "autosys_aews")


def _jil_raw(ctx: wb.Ctx) -> tuple[list[dict], dict, list[dict]]:
    """AutoSys jobs from the connections (the whole JIL, boxes included) and the uploaded JIL files: (jobs, boxes, rows)."""
    autos, boxes, rows = [], {}, []
    for c in ctx.connections():
        if c["kind"] != "autosys_aews":
            continue
        ad = _w2.adapter(c)
        try:
            jil = jp.parse_jil(ad.req(c, "GET", "/jil/job", params={"name": "ALL"}).text)
            live = {a["name"]: a for a in ad.estate(c)}
        except Exception as e:  # noqa: BLE001 - ConnectorError / Reconsent / ScopeError: shown to the person
            raise wb.StepFailed(f"{c['name']} could not be read: {e}") from e
        db.audit("connection.read", c["id"], {"kind": c["kind"], "object": "jil", "jobs": len(jil), "module": MODULE}, ctx.who or ctx.owner)
        boxes.update({n: d for n, d in jil.items() if d["job_type"] == "BOX"})
        for n, a in live.items():
            a.update(connection=c["id"], platform_label=c["name"])
            autos.append(a)
        rows.append({"source": c["name"], "kind": "AutoSys", "ok": True, "sees": f"{len(live)} job(s), {sum(1 for d in jil.values() if d['job_type'] == 'BOX')} box(es)"})
    for f in ctx.files((".jil", ".txt")):
        text = (ctx.dir / "data" / f["name"]).read_bytes().decode("utf-8", "replace")
        if "insert_job:" not in text:
            continue
        jil = jp.parse_jil(text)
        boxes.update({n: d for n, d in jil.items() if d["job_type"] == "BOX"})
        got = jp.parse_file(f["name"], text.encode("utf-8"))["autos"]
        for a in got:
            a.update(connection=None, platform_label="AutoSys JIL (upload)", upload=f["name"])
        autos += got
        rows.append({"source": f["name"], "kind": "AutoSys JIL", "ok": True, "sees": f"{len(got)} job(s)"})
    return autos, boxes, rows


def jil_schedule(d: dict, boxes: dict) -> dict:
    """The JIL attributes that decide when a job runs: its own, or its box's when it has none (a job in a box runs when
    the box does)."""
    keys = ("date_conditions", "days_of_week", "start_times", "start_mins", "run_calendar")
    if d.get("date_conditions") != "1" and d.get("box_name") in boxes:
        b = boxes[d["box_name"]]
        return {k: b.get(k) for k in keys if b.get(k) is not None} | {"from_box": d["box_name"]}
    return {k: d.get(k) for k in keys if d.get(k) is not None}


def _times(s: dict) -> list[tuple[int, int]]:
    return [(int(t.split(":")[0]), int(t.split(":")[1])) for t in re.findall(r"\d{1,2}:\d{2}", s.get("start_times") or "")]


def jil_blockers(d: dict, s: dict) -> list[str]:
    """What rules cannot move as it stands (a person decides those)."""
    out = []
    if d["job_type"] not in ("CMD", "FW", "c", "f"):
        out.append(f"job type {d['job_type']} has no rule")
    if s.get("date_conditions") == "1" and not s.get("start_mins") and len(_times(s)) > 1:
        out.append(f"{len(_times(s))} start times a day (Control-M takes one From time per job: split it in two)")
    cond = d.get("condition") or ""
    if "|" in cond:
        out.append("an OR condition")
    if any(k.lower() != "s" for k, _ in JIL_COND.findall(cond)):
        out.append("a condition on failure, done or exit code (only success, s(), moves by rules)")
    return out


def ctm_from_jil(a: dict, s: dict, waits: list[str], feeds: bool) -> dict:
    d = a["definition"]
    cmd = d.get("command") or ""
    for x, y in JIL_VARS:
        cmd = cmd.replace(x, y)
    cmd = re.sub(r"\$\{(\w+)\}", r"%%\1", cmd)
    j = {"Type": "Job:FileWatcher:Create" if d["job_type"] in ("FW", "f") else "Job:Command", "RunAs": d.get("owner") or "etl", "Host": d.get("machine") or "",
         "Description": ((d.get("description") or "").strip('"') or a["name"]) + " (moved from AutoSys)", "CreatedBy": "relay"}
    if j["Type"] == "Job:Command":
        j["Command"] = cmd
    else:
        j.update({"Path": (d.get("watch_file") or "").replace("*", "%%$ODATE"), "SearchInterval": d.get("watch_interval") or "60", "TimeLimit": d.get("term_run_time") or "0"})
    if d.get("box_name"):
        j["SubApplication"] = d["box_name"]
    if d.get("application"):
        j["Application"] = d["application"]
    env = dict(x.strip().split("=", 1) for x in (d.get("envvars") or "").split(",") if "=" in x)
    if env:
        j["Variables"] = [{k: v} for k, v in env.items()]
    if s.get("date_conditions") == "1":
        days = ["ALL"] if (s.get("days_of_week") or "all") == "all" else [JIL_DOW.get(x.strip().lower(), x.strip().upper()) for x in s["days_of_week"].split(",")]
        if s.get("start_mins"):
            w = {"FromTime": f"00{int(str(s['start_mins']).split(',')[0]):02d}", "ToTime": ">"}
            j["Rerun"] = {"Every": "60", "Units": "Minutes", "From": "Start"}
        else:
            hh, mm = (_times(s) or [(0, 0)])[0]
            w = {"FromTime": f"{hh:02d}{mm:02d}"}
        if s.get("run_calendar"):
            w["MonthDaysCalendar"] = s["run_calendar"]
        elif days == ["ALL"]:
            w["MonthDays"] = ["ALL"]
        else:
            w["WeekDays"] = days
        j["When"] = w
    elif waits:
        j["When"] = {"MonthDays": ["ALL"]}          # AutoSys starts it when its conditions are met: ordered every day, it waits for them
    if waits:
        j["eventsToWaitFor"] = {"Type": "WaitForEvents", "Events": [{"Event": f"{x}-OK"} for x in waits]}
    if feeds:
        j["eventsToAdd"] = {"Type": "AddEvents", "Events": [{"Event": f"{a['name']}-OK"}]}
    if d.get("alarm_if_fail") == "1":
        j["If:CompletionStatus:NotOk"] = {"Type": "If:CompletionStatus", "CompletionStatus": "NOTOK", "Mail_0": {"Type": "Action:Mail", "Subject": "%%JOBNAME ended not OK", "AttachOutput": True}}
    if d.get("max_run_alarm"):
        j["Notify:ExecTime"] = {"Type": "Notify:ExecTime", "Criteria": ">", "Value": str(d["max_run_alarm"]), "Message": f"{a['name']} is running long"}
    return j


def _next_jil(s: dict, start: datetime, n: int = 5) -> list[float]:
    """The next runs from the JIL's own attributes (a separate reading from Control-M's When)."""
    if s.get("date_conditions") != "1":
        return []
    dw = s.get("days_of_week") or "all"
    days = None if dw == "all" else {list(JIL_DOW).index(x.strip().lower()) for x in dw.split(",") if x.strip().lower() in JIL_DOW}
    hours = [(h, int(str(s["start_mins"]).split(",")[0])) for h in range(24)] if s.get("start_mins") else _times(s)
    out, d = [], start.date()
    for _ in range(400):
        if days is None or d.weekday() in days:
            for hh, mm in hours:
                t = datetime(d.year, d.month, d.day, hh, mm, tzinfo=timezone.utc)
                if t > start:
                    out.append(t.timestamp())
                    if len(out) == n:
                        return out
        d += timedelta(days=1)
    return out


def m_discover(ctx: wb.Ctx) -> dict:
    autos, _, rows = _uploads(ctx)
    autos = [a for a in autos if a["platform"] == "cron"]
    jil, boxes, jrows = _jil_raw(ctx)
    autos += jil
    rows += jrows
    if not autos:
        raise wb.StepFailed("Connect AutoSys, or upload the crontab files (/etc/crontab, the users' crontabs) or a JIL export, to move them to Control-M.")
    n8._save(ctx, "estate.json", {"autos": autos, "runs": [], "boxes": boxes})
    off = sum(1 for a in autos if not a["active"])
    return {"summary": f"{len(autos)} job(s) to consider: {sum(1 for a in autos if a['platform'] == 'cron')} from cron, {len(jil)} from AutoSys"
            + (f" in {len(boxes)} box(es)" if boxes else "") + f"; {off} switched off (commented out or on ice).", "counts": {"jobs": len(autos)},
            "data": _w2.table(["Job", "From", "Schedule", "Runs as", "On"], [[a["name"], a.get("platform_label") or a["host"], a["schedule"] or "on demand", a.get("owner") or "", "yes" if a["active"] else "no"]
                                                                          for a in autos])}


def m_decide(ctx: wb.Ctx) -> dict:
    est = n8._read(ctx, "estate.json", {})
    boxes = est.get("boxes") or {}
    have = {r["id"]: r for r in ctx.records(ctx.step_id)}
    recs = []
    for a in est.get("autos") or []:
        waits = ""
        if a["platform"] == "autosys_aews":
            d = a["definition"]
            s = jil_schedule(d, boxes)
            blk = jil_blockers(d, s)
            waits = ", ".join(n for k, n in JIL_COND.findall(d.get("condition") or "") if k.lower() == "s")
            if not a["active"]:
                dec, why = "retire", "on ice in AutoSys"
            elif blk:
                dec, why = "keep", "a person moves it: " + "; ".join(blk)
            else:
                dec, why = "move", f"{a['schedule'] or ('when its conditions are met' if waits else 'on demand')}" + (f" (the box {s['from_box']}'s schedule)" if s.get("from_box") else "") + " -> a Control-M job; "
                why += ("its conditions become events: " + waits) if waits else "no conditions"
                if s.get("run_calendar"):
                    why += f"; the calendar {s['run_calendar']} must be on Control-M with the same dates"
        elif not a["active"]:
            dec, why = "retire", "commented out in the crontab"
        else:
            dec, why = "move", f"{a['schedule']} -> a Control-M job; cron had no dependencies - add the jobs it waits for in Waits for"
        rid = a["id"]
        h = have.get(rid) or {}
        recs.append({"id": rid, "auto": a["id"], "flow": a["name"], "platform": "autosys" if a["platform"] == "autosys_aews" else "cron", "decision": h.get("decision") or dec,
                     "why": h.get("why") or why, "waits_for": h.get("waits_for", waits), "fix": ""})
    return {"summary": f"{sum(1 for r in recs if r['decision'] == 'move')} to move, {sum(1 for r in recs if r['decision'] == 'retire')} to retire, {sum(1 for r in recs if r['decision'] == 'keep')} kept"
            + " - AutoSys conditions are filled in; add what each cron job waits for (cron has no dependencies).",
            "records": recs, "data": _w2.table(["Job", "From", "Decision", "Why", "Waits for"], [[r["flow"], r["platform"], r["decision"], r["why"], r["waits_for"]] for r in recs])}


def _validate_decide(recs, ctx):
    names = {r["flow"] for r in recs if r.get("decision") == "move"}
    out = [f"{r['flow']}: waits for {d}, which is not moving" for r in recs if r.get("decision") == "move"
           for d in [x.strip() for x in str(r.get("waits_for") or "").split(",") if x.strip()] if d not in names]
    est = n8._read(ctx, "estate.json", {})
    by = {a["id"]: a for a in est.get("autos") or []}
    for r in recs:
        a = by.get(r.get("auto"))
        if r.get("decision") == "move" and a and a["platform"] == "autosys_aews":
            blk = jil_blockers(a["definition"], jil_schedule(a["definition"], est.get("boxes") or {}))
            if blk:
                out.append(f"{r['flow']}: rules cannot move it as it stands ({'; '.join(blk)}) - keep it, or change it in AutoSys first")
    if not names:
        out.append("nothing is moved: decide at least one job to move")
    return out


DECIDE_EDIT = wb.Edit(columns=[wb.Column("decision", "Decision", "select", options=(("move", "Move to Control-M"), ("retire", "Retire"), ("keep", "Keep where it is"))),
                               wb.Column("waits_for", "Waits for (job names, comma separated)"), wb.Column("why", "Why", "longtext"), wb.Column("flow", "Job", readonly=True),
                               wb.Column("platform", "From", readonly=True)],
                      add=False, remove=False, validate=_validate_decide, label="job")


def ctm_job(a: dict, waits: list[str], feeds: bool) -> dict:
    mi, hr, dom, mon, dow = a["definition"]["fields"]
    d = {"Type": "Job:Command", "Command": a["command"], "RunAs": a.get("owner") or "etl", "Host": "etl-app01", "Description": f"{a['name']} (moved from cron)", "CreatedBy": "relay"}
    if hr == "*":
        d["When"] = {"MonthDays": ["ALL"], "FromTime": f"00{int(mi):02d}", "ToTime": ">"}
        d["Rerun"] = {"Every": "60", "Units": "Minutes", "From": "Start"}
    elif dow not in ("*", "0-6", "0-7"):
        d["When"] = {"WeekDays": [DOW.get(x, x) for x in dow.split(",")], "FromTime": f"{int(hr):02d}{int(mi):02d}"}
    elif dom != "*":
        d["When"] = {"MonthDays": dom.split(","), "FromTime": f"{int(hr):02d}{int(mi):02d}"}
    else:
        d["When"] = {"MonthDays": ["ALL"], "FromTime": f"{int(hr):02d}{int(mi):02d}"}
    if waits:
        d["eventsToWaitFor"] = {"Type": "WaitForEvents", "Events": [{"Event": f"{w}-OK"} for w in waits]}
    if feeds:
        d["eventsToAdd"] = {"Type": "AddEvents", "Events": [{"Event": f"{a['name']}-OK"}]}
    return d


def m_convert(ctx: wb.Ctx) -> dict:
    est = n8._read(ctx, "estate.json", {})
    by = {a["id"]: a for a in est.get("autos") or []}
    boxes = est.get("boxes") or {}
    moving = [r for r in ctx.records("decide") if r["decision"] == "move"]
    waits = {r["flow"]: [x.strip() for x in str(r.get("waits_for") or "").split(",") if x.strip()] for r in moving}
    name = str(ctx.scope.get("folder") or "LARKSPUR_FROM_CRON")
    froms = sorted({by[r["auto"]]["platform"] for r in moving})
    folder = {"Type": "Folder", "ControlmServer": "", "OrderMethod": "Automatic", "Application": "LARKSPUR_CRON" if froms == ["cron"] else "LARKSPUR_MOVED", "SubApplication": "Batch",
              "Description": "Moved from " + " and ".join("AutoSys" if f == "autosys_aews" else "cron" for f in froms) + " by Relay"}
    adhoc = {"Type": "Folder", "ControlmServer": "", "OrderMethod": "Manual", "Application": folder["Application"], "SubApplication": "Batch",
             "Description": "On-demand jobs moved from AutoSys by Relay (not ordered automatically, as in AutoSys)"}
    for r in moving:
        a = by[r["auto"]]
        feeds = any(r["flow"] in v for v in waits.values())
        if a["platform"] == "autosys_aews":
            s = jil_schedule(a["definition"], boxes)
            j = ctm_from_jil(a, s, waits[r["flow"]], feeds)
            (folder if "When" in j else adhoc)[a["name"]] = j
        else:
            folder[a["name"]] = ctm_job(a, waits[r["flow"]], feeds)
    out = {name: folder}
    if any(isinstance(v, dict) for v in adhoc.values()):
        out[f"{name}_ADHOC"] = adhoc
    ctx.put("folder_name", name)
    ctx.put("folders", sorted(out))
    n8._save(ctx, "converted.json", out)
    for fn, f in out.items():
        ctx.output(f"{fn}.json", json.dumps({fn: f}, indent=2), label=f"The Control-M folder {fn} (JSON)")
    jobs = [(fn, k, v) for fn, f in out.items() for k, v in f.items() if isinstance(v, dict)]
    return {"summary": f"{len(moving)} job(s) written as Control-M folder{'s' if len(out) > 1 else ''} {', '.join(out)} by rules - the schedule from the cron fields or the JIL, "
                       "what each waits for as events" + (", on-demand AutoSys jobs in a folder that is not ordered automatically" if len(out) > 1 else "") + ".",
            "counts": {"converted": len(moving)},
            "data": _w2.table(["Folder", "Job", "When", "Waits for"], [[fn, k, json.dumps(v.get("When")) if v.get("When") else "on demand",
                                                                     ", ".join(e["Event"] for e in (v.get("eventsToWaitFor") or {}).get("Events") or [])] for fn, k, v in jobs])}


def _next_cron(fields: list[str], start: datetime, n: int = 5) -> list[float]:
    mi, hr, dom, mon, dow = fields
    out, t = [], start.replace(second=0, microsecond=0) + timedelta(minutes=1)

    def hit(v, x, dw=False):
        if v == "*":
            return True
        vals = set()
        for part in v.split(","):
            if "-" in part:
                a, b = part.split("-")
                vals |= set(range(int(a), int(b) + 1))
            else:
                vals.add(int(part))
        return x in vals or (dw and x == 0 and 7 in vals)
    for _ in range(60 * 24 * 40):
        cw = (t.weekday() + 1) % 7
        if hit(mi, t.minute) and hit(hr, t.hour) and hit(dom, t.day) and hit(mon, t.month) and hit(dow, cw, True):
            out.append(t.timestamp())
            if len(out) == n:
                break
        t += timedelta(minutes=1)
    return out


def _next_ctm(when: dict, start: datetime, n: int = 5) -> list[float]:
    ft = str(when.get("FromTime") or "0000")
    hh, mm = int(ft[:2]), int(ft[2:])
    out, d = [], start.date()
    hourly = when.get("ToTime") == ">"
    for _ in range(400):
        md, wd = when.get("MonthDays") or ["ALL"], when.get("WeekDays") or []
        ok = (not wd or calendar.day_abbr[d.weekday()].upper() in wd) and (md == ["ALL"] or str(d.day) in md or (wd and md == ["ALL"]))
        if ok:
            for h in (range(24) if hourly else [hh]):
                t = datetime(d.year, d.month, d.day, h, mm, tzinfo=timezone.utc)
                if t > start:
                    out.append(t.timestamp())
                    if len(out) == n:
                        return out
        d += timedelta(days=1)
    return out


def m_prove(ctx: wb.Ctx) -> dict:
    conv = n8._read(ctx, "converted.json", {})
    c = _ctm(ctx)
    raw = n8._read(ctx, "estate.json", {}) or {}
    est = {a["name"]: a for a in raw.get("autos") or []}
    boxes = raw.get("boxes") or {}
    dec = {r["flow"]: r for r in ctx.records("decide")}
    probs = [p for fn, f in conv.items() for p in jp.ControlMApi().build(c, fn, f)]
    start = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    pairs, cal, demand, cond, trig = [], [], [], [], []
    for fn, f in conv.items():
        for jn, d in f.items():
            if not isinstance(d, dict) or jn not in est:
                continue
            a = est[jn]
            if a["platform"] == "cron":
                pairs.append({"case": jn, "old": _next_cron(a["definition"]["fields"], start), "new": _next_ctm(d["When"], start), "tolerance_s": 60})
                continue
            s = jil_schedule(a["definition"], boxes)
            if s.get("date_conditions") != "1" and not d.get("eventsToWaitFor"):
                demand.append((jn, "When" not in d and f.get("OrderMethod") == "Manual"))
            elif s.get("date_conditions") != "1":
                trig.append((jn, (d.get("When") or {}).get("MonthDays") == ["ALL"] and "FromTime" not in (d.get("When") or {}) and f.get("OrderMethod") == "Automatic"))
            elif s.get("run_calendar"):
                cal.append((jn, s["run_calendar"], (d.get("When") or {}).get("MonthDaysCalendar") == s["run_calendar"]))
            else:
                pairs.append({"case": jn, "old": _next_jil(s, start), "new": _next_ctm(d["When"], start), "tolerance_s": 60})
            want = {x.strip() for x in str((dec.get(jn) or {}).get("waits_for") or "").split(",") if x.strip()}
            got = {e["Event"].rsplit("-OK", 1)[0] for e in (d.get("eventsToWaitFor") or {}).get("Events") or []}
            jil = {n for k, n in JIL_COND.findall(a["definition"].get("condition") or "") if k.lower() == "s"}
            fed = all(any(e["Event"] == f"{w}-OK" for x in conv.values() for v in x.values() if isinstance(v, dict) for e in (v.get("eventsToAdd") or {}).get("Events") or []) for w in got)
            cond.append((jn, want, got, jil, fed))
    rows = [_w2.gate("build", "Control-M's build accepts the new folder" + ("s" if len(conv) > 1 else "") + " (nothing is written)", "fail" if probs else "pass", "; ".join(probs)[:300] or "valid", "valid")]
    if pairs:
        rows.append(ctx.proof("cadence", label="The next five runs fall at the same times on the old scheduler and on Control-M", pairs=pairs))
    if cond:
        bad = [jn for jn, want, got, _, fed in cond if want != got or not fed]
        moved = [jn for jn, want, _, jil, _ in cond if want != jil]
        rows.append(_w2.gate("conditions", "Each AutoSys condition is a Control-M event: waited for by the job, added by the job it names", "fail" if bad else "pass",
                             (f"different: {', '.join(bad)}" if bad else f"{len(cond)} job(s), {sum(len(x[2]) for x in cond)} condition(s) as events")
                             + (f"; changed in Decide from the JIL: {', '.join(moved)}" if moved else ""), "every condition"))
    if demand:
        bad = [jn for jn, good in demand if not good]
        rows.append(_w2.gate("on-demand", "On-demand AutoSys jobs (no date conditions) are not ordered automatically on Control-M", "fail" if bad else "pass",
                             f"different: {', '.join(bad)}" if bad else f"{len(demand)} job(s) in a Manual folder", "on demand on both"))
    if trig:
        bad = [jn for jn, good in trig if not good]
        rows.append(_w2.gate("triggered", "Jobs AutoSys starts when their conditions are met are ordered every day on Control-M, with no time, and wait for those events", "fail" if bad else "pass",
                             f"different: {', '.join(bad)}" if bad else f"{len(trig)} job(s): {', '.join(jn for jn, _ in trig)}", "started by their conditions on both"))
    for jn, calname, good in cal:
        rows.append(_w2.gate(f"calendar-{jn}", f"{jn} runs on the AutoSys calendar {calname}", "warn" if good else "fail",
                             f"Control-M's MonthDaysCalendar {calname} must hold the same dates - check it against the AutoSys calendar (autocal_asc)" if good else "the calendar is not on the job",
                             "the same calendar dates"))
    bad = [g for g in rows if g["status"] == "fail"]
    return {"summary": f"{len(pairs) + len(cal) + len(demand) + len(trig)} job(s): Control-M's build " + ("refuses" if probs else "accepts") + f" the folder{'s' if len(conv) > 1 else ''}"
                       + (f"; {rows[1]['detail']}" if pairs else "") + (f"; {len(cal)} on a calendar to check" if cal else "") + ".", "counts": {"jobs": len(pairs) + len(cal) + len(demand) + len(trig), "fail": len(bad)},
            "data": _w2.gates(rows), "ok": not bad}


def m_handover(ctx: wb.Ctx) -> dict:
    conv = n8._read(ctx, "converted.json", {})
    retire = [r["flow"] for r in ctx.records("decide") if r["decision"] == "retire"]
    kept = [r["flow"] for r in ctx.records("decide") if r["decision"] == "keep"]
    froms = {r["platform"] for r in ctx.records("decide") if r["decision"] == "move"}
    then = "The folders are deployed after their own approval; " + " ".join(
        x for x in ("comment the lines out of the crontab once Control-M runs them." if "cron" in froms else "",
                    "put the AutoSys jobs on ice (sendevent -E JOB_ON_ICE) once Control-M runs them." if "autosys" in froms else "") if x)
    return {"summary": f"Hand over {', '.join(conv)}; {len(retire)} job(s) retired" + (f", {len(kept)} kept where they are" if kept else "") + ".",
            "data": {"items": [{"title": f"Moving to Control-M ({fn})", "detail": ", ".join(k for k, v in f.items() if isinstance(v, dict))} for fn, f in conv.items()]
                     + [{"title": "Retired", "detail": ", ".join(retire) or "none"}] + ([{"title": "Kept where they are (a person moves them)", "detail": ", ".join(kept)}] if kept else [])
                     + [{"title": "Then", "detail": then}]}}


def m_run(ctx: wb.Ctx) -> dict:
    p = _w2.push_of(ctx.id, ctx.step_id)
    if not p or p["status"] in ("failed", "refused"):
        c = _ctm(ctx, write=True)
        conv = n8._read(ctx, "converted.json", {})
        _w2.request_push(ctx, c["id"], "deploy_new", {"folders": conv}, f"Deploy folder{'s' if len(conv) > 1 else ''} {', '.join(conv)} to {c['name']}",
                         items=[f"Where: {c['name']}"] + [f"Folder: {fn} (new, {sum(1 for v in f.values() if isinstance(v, dict))} job(s))" for fn, f in conv.items()])
    return _mrun_view(ctx)


def _mrun_view(ctx: wb.Ctx) -> dict:
    p = _w2.push_of(ctx.id, "run")
    if p and p["status"] == "written":
        return {"summary": f"Deployed: {', '.join(p['result'].get('folders') or [])} on Control-M; switch the old jobs off (the cron lines, the AutoSys jobs on ice) once it runs them.",
                "counts": {"deployed": len(p['result'].get('folders') or [])},
                "data": {"text": "Watch it with a Run item on the Control-M connection."}}
    if p and p["status"] == "awaiting":
        return {"summary": "The deploy waits for its own approval in the Validation queue.", "data": {"href": "#/validate", "label": "Open the Validation queue", "text": p["what"]}}
    return {"summary": f"Not deployed ({(p or {}).get('status') or 'not asked'}): run this step again.", "data": {"text": str(((p or {}).get("result") or {}).get("error") or "")}}


_w2.REFRESH["jobs.migrate.run"] = _mrun_view


# ================================================================== Develop (a new job on Control-M or AutoSys)

EVERY = (("daily", "Every day"), ("weekly", "Some days of the week"), ("monthly", "Some days of the month"), ("hourly", "Every hour"), ("demand", "On demand (not scheduled)"))
WEEK = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,63}$")
AT_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def d_describe(ctx: wb.Ctx) -> dict:
    c, ad = _sched(ctx)
    try:
        autos = ad.estate(c)
    except Exception as e:  # noqa: BLE001 - ConnectorError / Reconsent: shown to the person
        raise wb.StepFailed(f"{c['name']} could not be read: {e}") from e
    db.audit("connection.read", c["id"], {"kind": c["kind"], "jobs": len(autos), "module": MODULE}, ctx.who or ctx.owner)
    hosts = sorted({a.get("host") for a in autos if a.get("host")})
    users = sorted({a.get("owner") or (a.get("definition") or {}).get("RunAs") for a in autos if a.get("owner") or (a.get("definition") or {}).get("RunAs")})
    adds = sorted({e["Event"] for a in autos for e in (((a.get("definition") or {}).get("eventsToAdd") or {}).get("Events") or [])})
    est = {"kind": c["kind"], "jobs": sorted(a["name"] for a in autos), "hosts": hosts, "users": users, "folders": sorted({a.get("folder") for a in autos if a.get("folder")}), "adds": adds,
           "common_host": max(hosts, key=lambda h: sum(1 for a in autos if a.get("host") == h)) if hosts else "",
           "common_user": max(users, key=lambda u: sum(1 for a in autos if (a.get("owner") or (a.get("definition") or {}).get("RunAs")) == u)) if users else ""}
    n8._save(ctx, "develop-estate.json", est)
    return {"summary": f"{c['name']} ({'Control-M' if c['kind'] == 'controlm_api' else 'AutoSys'}): {len(autos)} job(s) on {len(hosts)} host(s) - the new job's name must be free, its host one the scheduler knows."
                       + (" " + ctx.brief[:200] if ctx.brief else ""), "counts": {"jobs": len(autos), "hosts": len(hosts)},
            "data": _w2.table(["Host", "Jobs on it"], [[h, sum(1 for a in autos if a.get("host") == h)] for h in hosts])}


def d_shape(ctx: wb.Ctx) -> dict:
    est = n8._read(ctx, "develop-estate.json", {})
    have = ctx.records(ctx.step_id)
    recs = have or [{"id": "job-1", "name": str(ctx.scope.get("job") or "").upper(), "command": "", "host": est.get("common_host", ""), "run_as": est.get("common_user", ""),
                     "every": "daily", "at": "02:00", "days": "", "waits_for": "", "variables": "", "description": (ctx.brief or "")[:200]}]
    return {"summary": f"{len(recs)} new job(s): name, command, host, who it runs as, when, what it waits for - rules check each before anything is built.",
            "records": recs, "counts": {"jobs": len(recs)},
            "data": _w2.table(["Job", "Host", "When", "Waits for"], [[r.get("name"), r.get("host"), _when_text(r), r.get("waits_for") or "-"] for r in recs])}


def _when_text(r: dict) -> str:
    e = r.get("every") or "daily"
    return {"daily": f"every day at {r.get('at')}", "weekly": f"{r.get('days')} at {r.get('at')}", "monthly": f"on day(s) {r.get('days')} at {r.get('at')}",
            "hourly": f"every hour at :{str(r.get('at') or '00').split(':')[-1]}", "demand": "on demand"}.get(e, e)


def _list(v) -> list[str]:
    return [x.strip() for x in re.split(r"[,;\s]+", str(v or "")) if x.strip()]


def _vars_of(v) -> dict:
    out = {}
    for part in re.split(r"[;\n]+", str(v or "")):
        if part.strip():
            k, _, val = part.partition("=")
            out[k.strip()] = val.strip()
    return out


def _validate_new(recs, ctx):
    est = n8._read(ctx, "develop-estate.json", {})
    kind = est.get("kind")
    names = [str(r.get("name") or "").strip() for r in recs]
    out = []
    for r, n in zip(recs, names):
        lab = n or "a job"
        if not NAME_RE.match(n):
            out.append(f"{lab}: the name is upper case letters, digits and _ (3-64), starting with a letter")
        if n in (est.get("jobs") or []):
            out.append(f"{n}: a job of that name is already on the scheduler - pick another (changing it is a Change item)")
        if names.count(n) > 1:
            out.append(f"{n}: two new jobs share the name")
        if not str(r.get("command") or "").strip():
            out.append(f"{lab}: the command is needed")
        elif jp.secrets_in_command(str(r["command"]), lab):
            out.append(f"{lab}: the command carries a password - pass it from the scheduler's vault or a variable, never on the command line")
        if est.get("hosts") and r.get("host") not in est["hosts"]:
            out.append(f"{lab}: {r.get('host') or 'no host'} is not a host the scheduler knows ({', '.join(est['hosts'][:6])})")
        if not str(r.get("run_as") or "").strip():
            out.append(f"{lab}: who it runs as is needed")
        e = r.get("every") or "daily"
        if e not in dict(EVERY):
            out.append(f"{lab}: unknown schedule {e!r}")
        if e in ("daily", "weekly", "monthly") and not AT_RE.match(str(r.get("at") or "")):
            out.append(f"{lab}: the time is HH:MM (24 h)")
        if e == "hourly" and not re.match(r"^:?[0-5]?\d$", str(r.get("at") or "").split(":")[-1]):
            out.append(f"{lab}: an hourly job runs at a minute past the hour (for example :15)")
        if e == "weekly" and (not _list(r.get("days")) or any(d.upper()[:3] not in WEEK for d in _list(r.get("days")))):
            out.append(f"{lab}: the days of the week are MON ... SUN, comma separated")
        if e == "monthly":
            if kind == "autosys_aews":
                out.append(f"{lab}: AutoSys runs on days of the month through a calendar - create the calendar in AutoSys first, or pick days of the week")
            elif not _list(r.get("days")) or any(not (d.isdigit() and 1 <= int(d) <= 31) for d in _list(r.get("days"))):
                out.append(f"{lab}: the days of the month are 1 ... 31, comma separated")
        for w_ in _list(r.get("waits_for")):
            if w_ not in (est.get("jobs") or []) and w_ not in names:
                out.append(f"{lab}: waits for {w_}, which is neither on the scheduler nor a new job here")
            if w_ == n:
                out.append(f"{lab}: a job cannot wait for itself")
        for k in _vars_of(r.get("variables")):
            if not re.match(r"^[A-Za-z_]\w*$", k):
                out.append(f"{lab}: variable {k!r} is not a name (letters, digits, _)")
    return out


NEW_EDIT = wb.Edit(columns=[wb.Column("name", "Job name"), wb.Column("command", "Command", "longtext"), wb.Column("host", "Host"), wb.Column("run_as", "Runs as"),
                            wb.Column("every", "Runs", "select", options=EVERY), wb.Column("at", "At (HH:MM; hourly :MM)"), wb.Column("days", "Days (MON,WED or 1,15)"),
                            wb.Column("waits_for", "Waits for (job names)"), wb.Column("variables", "Variables (K=V; K2=V2)"), wb.Column("description", "What it does", "longtext")],
                   add=True, remove=True, validate=_validate_new, label="job")


def _when_ctm(r: dict) -> dict | None:
    e, at = r.get("every") or "daily", str(r.get("at") or "00:00")
    if e == "demand":
        return None
    if e == "hourly":
        return {"MonthDays": ["ALL"], "FromTime": f"00{int(at.split(':')[-1] or 0):02d}", "ToTime": ">"}
    hh, mm = at.split(":")
    w = {"FromTime": f"{int(hh):02d}{int(mm):02d}"}
    if e == "weekly":
        w["WeekDays"] = [d.upper()[:3] for d in _list(r.get("days"))]
    elif e == "monthly":
        w["MonthDays"] = [str(int(d)) for d in _list(r.get("days"))]
    else:
        w["MonthDays"] = ["ALL"]
    return w


def _jil_attrs(r: dict, names: list[str]) -> dict:
    e, at = r.get("every") or "daily", str(r.get("at") or "00:00")
    d = {"job_type": "CMD", "command": r["command"].strip(), "machine": r["host"], "owner": r["run_as"], "permission": ""}
    if e == "demand":
        d["date_conditions"] = "0"
    else:
        d["date_conditions"] = "1"
        d["days_of_week"] = "all" if e in ("daily", "hourly") else ",".join(dict(zip(WEEK, ("mo", "tu", "we", "th", "fr", "sa", "su")))[x.upper()[:3]] for x in _list(r.get("days")))
        if e == "hourly":
            d["start_mins"] = str(int(at.split(":")[-1] or 0))
        else:
            d["start_times"] = f'"{at}"'
    if _list(r.get("waits_for")):
        d["condition"] = " & ".join(f"s({x})" for x in _list(r.get("waits_for")))
    if r.get("description"):
        d["description"] = '"' + str(r["description"]).replace('"', "'")[:200] + '"'
    if _vars_of(r.get("variables")):
        d["envvars"] = ", ".join(f"{k}={v}" for k, v in _vars_of(r.get("variables")).items())
    d["alarm_if_fail"] = "1"
    return d


def jil_text(jobs: dict) -> str:
    return "\n\n".join(f"/* Written by Relay */\ninsert_job: {n}   job_type: {d['job_type']}\n" + "\n".join(f"{k}: {v}" for k, v in d.items() if k != "job_type") for n, d in jobs.items()) + "\n"


def d_build(ctx: wb.Ctx) -> dict:
    est = n8._read(ctx, "develop-estate.json", {})
    recs = ctx.records("shape")
    names = [r["name"] for r in recs]
    fed = {w_ for r in recs for w_ in _list(r.get("waits_for"))}
    if est.get("kind") == "controlm_api":
        folder = str(ctx.scope.get("folder") or "RELAY_NEW_JOBS").upper()
        f = {"Type": "Folder", "ControlmServer": "", "OrderMethod": "Automatic", "Application": "RELAY", "SubApplication": "New", "Description": f"New jobs from {ctx.title}"[:200]}
        for r in recs:
            j = {"Type": "Job:Command", "Command": r["command"].strip(), "Host": r["host"], "RunAs": r["run_as"], "Description": str(r.get("description") or r["name"])[:200], "CreatedBy": "relay"}
            if _vars_of(r.get("variables")):
                j["Variables"] = [{k: v} for k, v in _vars_of(r.get("variables")).items()]
            w = _when_ctm(r)
            if w:
                j["When"] = w
                if (r.get("every") or "") == "hourly":
                    j["Rerun"] = {"Every": "60", "Units": "Minutes", "From": "Start"}
            if _list(r.get("waits_for")):
                j["eventsToWaitFor"] = {"Type": "WaitForEvents", "Events": [{"Event": f"{x}-OK"} for x in _list(r.get("waits_for"))]}
            if r["name"] in fed:
                j["eventsToAdd"] = {"Type": "AddEvents", "Events": [{"Event": f"{r['name']}-OK"}]}
            j["If:CompletionStatus:NotOk"] = {"Type": "If:CompletionStatus", "CompletionStatus": "NOTOK", "Mail_0": {"Type": "Action:Mail", "Subject": "%%JOBNAME ended not OK", "AttachOutput": True}}
            f[r["name"]] = j
        out = {folder: f}
        if not any(isinstance(v, dict) and "When" in v for v in f.values()):
            f["OrderMethod"] = "Manual"
        n8._save(ctx, "new-definition.json", {"kind": "controlm_api", "folders": out})
        ctx.output(f"{folder}.json", json.dumps(out, indent=2), label=f"The Control-M folder {folder} (JSON)")
        what = f"Control-M folder {folder}"
    else:
        jobs = {r["name"]: _jil_attrs(r, names) for r in recs}
        text = jil_text(jobs)
        n8._save(ctx, "new-definition.json", {"kind": "autosys_aews", "jobs": jobs, "jil": text})
        ctx.output("new-jobs.jil", text, label="The new jobs (JIL)")
        what = "JIL"
    return {"summary": f"{len(recs)} job(s) written as {what} by rules - the schedule, the conditions, the variables and an alarm when it ends not OK.", "counts": {"jobs": len(recs)},
            "data": _w2.table(["Job", "When", "Waits for"], [[r["name"], _when_text(r), r.get("waits_for") or "-"] for r in recs])}


def _next_rule(r: dict, start: datetime, n: int = 5) -> list[float]:
    """The next runs from what the person asked for (a separate reading from the scheduler's own definition)."""
    e, at = r.get("every") or "daily", str(r.get("at") or "00:00")
    if e == "demand":
        return []
    if e == "hourly":
        times, ok_day = [(h, int(at.split(":")[-1] or 0)) for h in range(24)], (lambda d: True)
    else:
        hh, mm = (int(x) for x in at.split(":"))
        times = [(hh, mm)]
        if e == "weekly":
            want = {WEEK.index(x.upper()[:3]) for x in _list(r.get("days"))}
            ok_day = lambda d: d.weekday() in want  # noqa: E731
        elif e == "monthly":
            want = {int(x) for x in _list(r.get("days"))}
            ok_day = lambda d: d.day in want  # noqa: E731
        else:
            ok_day = lambda d: True  # noqa: E731
    out, d = [], start.date()
    for _ in range(800):
        if ok_day(d):
            for h, m in times:
                t = datetime(d.year, d.month, d.day, h, m, tzinfo=timezone.utc)
                if t > start:
                    out.append(t.timestamp())
                    if len(out) == n:
                        return out
        d += timedelta(days=1)
    return out


def d_prove(ctx: wb.Ctx) -> dict:
    est = n8._read(ctx, "develop-estate.json", {})
    nd = n8._read(ctx, "new-definition.json", {})
    recs = {r["name"]: r for r in ctx.records("shape")}
    start = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    c, ad = _sched(ctx)
    rows, pairs, bad_waits = [], [], []
    if nd.get("kind") == "controlm_api":
        probs = [p for fn, f in nd["folders"].items() for p in jp.ControlMApi().build(c, fn, f)]
        taken = [fn for fn in nd["folders"] if fn in (est.get("folders") or [])]
        rows.append(_w2.gate("build", "Control-M's build accepts the new folder (nothing is written)", "fail" if probs else "pass", "; ".join(probs)[:300] or "valid", "valid"))
        rows.append(_w2.gate("folder", "The folder is new (a deploy replaces a folder whole)", "fail" if taken else "pass", ", ".join(taken) or "new", "a new folder",
                             "pick another folder name in the work item" if taken else ""))
        for fn, f in nd["folders"].items():
            for jn, d in f.items():
                if not isinstance(d, dict) or jn not in recs:
                    continue
                if d.get("When"):
                    pairs.append({"case": jn, "old": _next_rule(recs[jn], start), "new": _next_ctm(d["When"], start), "tolerance_s": 60})
                for e in (d.get("eventsToWaitFor") or {}).get("Events") or []:
                    up = e["Event"].rsplit("-OK", 1)[0]
                    if up in recs:
                        continue
                    if e["Event"] not in (est.get("adds") or []):
                        bad_waits.append(f"{jn} waits for {up}, which does not add {e['Event']} on Control-M (change {up} to add it first)")
    else:
        back = jp.parse_jil(nd["jil"])
        same = all({k: v for k, v in back.get(n, {}).items()} == d for n, d in nd["jobs"].items())
        rows.append(_w2.gate("jil", "The JIL reads back as written (insert_job blocks, every attribute)", "pass" if same and set(back) == set(nd["jobs"]) else "fail",
                             f"{len(back)} job(s)", f"{len(nd['jobs'])} job(s)"))
        for jn, d in nd["jobs"].items():
            s = {k: d.get(k) for k in ("date_conditions", "days_of_week", "start_times", "start_mins") if d.get(k) is not None}
            if s.get("date_conditions") == "1":
                pairs.append({"case": jn, "old": _next_rule(recs[jn], start), "new": _next_jil(s, start), "tolerance_s": 60})
    if pairs:
        rows.append(ctx.proof("cadence", label="The next five runs fall when you asked, read from the scheduler's own definition", pairs=pairs))
    demand = [n for n, r in recs.items() if (r.get("every") or "") == "demand"]
    if demand:
        rows.append(_w2.gate("demand", "On-demand jobs are not scheduled", "pass", ", ".join(demand), "not scheduled"))
    rows.append(_w2.gate("waits", "Every job it waits for is there and signals it ended OK", "fail" if bad_waits else "pass", len(bad_waits), 0, "; ".join(bad_waits)[:300] or
                         ", ".join(f"{n} <- {r.get('waits_for')}" for n, r in recs.items() if r.get("waits_for")) or "no waits"))
    leaks = [n for n, r in recs.items() if jp.secrets_in_command(str(r.get("command") or ""), n)]
    rows.append(_w2.gate("secrets", "No password on a command line", "fail" if leaks else "pass", len(leaks), 0, ", ".join(leaks)))
    bad = [g for g in rows if g["status"] == "fail"]
    ctx.put("new_jobs", list(recs))
    return {"summary": f"{len(recs)} new job(s): " + ("; ".join(g["label"] for g in bad) if bad else "the definition is accepted, the run times are the ones asked for and every wait is real") + ".",
            "counts": {"jobs": len(recs), "fail": len(bad)}, "data": _w2.gates(rows), "ok": not bad}


def d_ship(ctx: wb.Ctx) -> dict:
    recs = ctx.records("shape")
    c, _ = _sched(ctx)
    return {"summary": f"Put {len(recs)} new job(s) on {c['name']}: the named approver signs off; then the deploy waits for its own approval.",
            "data": {"items": [{"title": r["name"], "detail": f"{_when_text(r)} on {r['host']} as {r['run_as']}" + (f"; waits for {r['waits_for']}" if r.get("waits_for") else "") + f" - {r['command'][:120]}"}
                               for r in recs]}}


def d_run(ctx: wb.Ctx) -> dict:
    p = _w2.push_of(ctx.id, ctx.step_id)
    if not p or p["status"] in ("failed", "refused"):
        c, _ = _sched(ctx, write=True)
        nd = n8._read(ctx, "new-definition.json", {})
        if nd.get("kind") == "controlm_api":
            _w2.request_push(ctx, c["id"], "deploy_new", {"folders": nd["folders"]}, f"Deploy the new folder {', '.join(nd['folders'])} to {c['name']}",
                             items=[f"Where: {c['name']}"] + [f"Job {jn}: {d.get('Command', '')[:100]}" for f in nd["folders"].values() for jn, d in f.items() if isinstance(d, dict)])
        else:
            _w2.request_push(ctx, c["id"], "insert_jobs", {"jil": nd["jil"], "jobs": sorted(nd["jobs"])}, f"Insert {len(nd['jobs'])} new job(s) into {c['name']}",
                             items=[f"Where: {c['name']}"] + [f"insert_job: {n}" for n in sorted(nd["jobs"])])
    return _drun_view(ctx)


def _drun_view(ctx: wb.Ctx) -> dict:
    p = _w2.push_of(ctx.id, "run")
    if p and p["status"] == "written":
        r = p["result"]
        on = r.get("jobs") or [j for j in ctx.get("new_jobs") or []]
        return {"summary": f"On the scheduler: {', '.join(on)}" + (f" in {', '.join(r.get('folders'))}" if r.get("folders") else "") + " - read back after the deploy. Watch them with a Run item.",
                "counts": {"deployed": len(on)}, "data": {"text": "Start a Run item on the same connection to watch the first runs."}}
    if p and p["status"] == "awaiting":
        return {"summary": "The deploy waits for its own approval in the Validation queue.", "data": {"href": "#/validate", "label": "Open the Validation queue", "text": p["what"]}}
    return {"summary": f"Not deployed ({(p or {}).get('status') or 'not asked'}): run this step again.", "data": {"text": str(((p or {}).get("result") or {}).get("error") or "")}}


_w2.REFRESH["jobs.develop.run"] = _drun_view


# ================================================================== Run (Control-M)

def r_watch(ctx: wb.Ctx) -> dict:
    c = _ctm(ctx)
    a = jp.ControlMApi()
    jobs = {j["id"]: j for j in a.estate(c)}
    every = a.runs(c, list(jobs.values()))
    newest = max([r["start"] or 0 for r in every] or [time.time()])
    since = ctx.get("since") or (newest - 86400)                       # a first round: the day before the newest order
    runs = [r for r in every if (r["start"] or 0) >= since]
    failing = {r["target"] for r in runs if r["status"] == "failed"}
    nm = lambda t: t.split(":", 1)[-1]  # noqa: E731
    fails = [{**r, "workflow": nm(r["target"])} for r in runs if r["status"] == "failed"]
    for r in runs:
        if r["status"] == "waiting" and any(d in failing for d in jobs.get(r["target"], {}).get("deps") or []):
            fails.append({**r, "workflow": nm(r["target"]), "error": f"waits for {', '.join(nm(d) for d in jobs[r['target']]['deps'] if d in failing)}, which ended not OK (transient: it starts once that is fixed)"})
    ctx.put("failures", fails)
    ctx.put("since", newest + 1)
    checks = [_w2.gate(f"job-{_w2.slug(n)}", nm(n), "fail" if any(f["target"] == n for f in fails) else "pass", ", ".join(sorted({r["status"] for r in runs if r["target"] == n})) or "no order",
                       "ended OK", next((f["error"] for f in fails if f["target"] == n), "") or "") for n in sorted({r["target"] for r in runs})]
    return {"summary": f"{len(runs)} order(s) since the last round: {sum(1 for r in runs if r['status'] == 'failed')} ended not OK, {sum(1 for f in fails if f['status'] == 'waiting')} held back behind them.",
            "counts": {"executions": len(runs), "failed": len(fails)}, "data": _w2.gates(checks or [_w2.gate("none", "Orders", "pass", 0)])}


def r_approve(ctx: wb.Ctx) -> dict:
    rows, out = [], []
    for b in ctx.records("fix"):
        title = f"{b['workflow']}: {b['signature'].replace('_', ' ')}"
        body = f"{b['error']}\n\nLikely cause: {b['cause']}\nWhat cures it: {b['cure']}\n{('Note: ' + b['note']) if b.get('note') else ''}\nWork item: {wb.route_of(ctx.st)}"
        if b["route"] == "heal":
            h = ctx.heal(title, body, place=f"{b['workflow']} (Control-M)", signature=f"jobs:{b['signature']}", subject={"job": b["target"], "orders": b["executions"][-5:]})
        elif b["route"] == "ticket":
            h = _w2.desk_ticket(ctx, str(ctx.scope.get("desk") or ""), title, body, priority="P2", ref=b["id"])
        elif b["route"] == "rerun":
            c = _ctm(ctx, write=True)
            cp = _w2.request_push(ctx, c["id"], "rerun", {"jobs": b["executions"][-3:]}, f"Rerun {b['workflow']} on {c['name']}", items=[f"Where: {c['name']}", f"Orders: {', '.join(b['executions'][-3:])}"])
            h = {"kind": "write", "label": title, "status": "awaiting approval", "checkpoint": cp["id"]}
        elif b["route"] == "change":
            it = wb.create(MODULE, "change", f"Fix: {b['workflow']}"[:150], who=ctx.owner, brief=f"{b['workflow']} ends not OK: {b['error']}", connections=[c_["id"] for c_ in ctx.connections() if c_["kind"] == "controlm_api"][:1],
                           scope={"job": b["workflow"]}, approver=ctx.st.get("approver"), parent=ctx.id)
            h = ctx._handoff({"kind": "change", "label": title, "status": "Change work item opened", "link": wb.route_of(it), "item": it["id"]})
        else:
            h = {"kind": b["route"], "label": title, "status": "expected - recorded" if b["route"] == "expected" else "ignored this time"}
        out.append(h)
        rows.append([b["workflow"], b["cause"], b["route"], h.get("status"), h.get("item") or h.get("case") or h.get("checkpoint") or ""])
    return {"summary": f"{len(out)} hand-off(s) as you approved.", "data": _w2.table(["Job", "Cause", "Route", "Status", "Reference"], rows), "counts": {"hand-offs": len(out)}}


RFIX_EDIT = wb.Edit(columns=[wb.Column("route", "Route", "select", options=(("change", "Open a Change work item"), ("heal", "Self-healing"), ("ticket", "Raise a ticket"), ("rerun", "Rerun (after approval)"),
                                                                       ("expected", "Expected - no action"), ("ignore", "Ignore this time"))),
                             wb.Column("note", "Note for whoever fixes it", "longtext"), wb.Column("workflow", "Job", readonly=True), wb.Column("cause", "Cause", readonly=True)], add=False, remove=False, label="cause")


GUIDE = """# Job scheduling - the work item

Relay's job scheduling reads the batch estate on Control-M, AutoSys and cron - each job, its schedule, its command and
what it waits for - finds what fails and why from the jobs' own output, and changes a definition only through a
release a named person approved. Nothing is invented: every finding comes from a definition or a run."""

wb.register(wb.Pack(
    module=MODULE, guide=GUIDE, platforms=PLATFORMS,
    lineage="each job as a node and the jobs it waits for; a migrated cron job linked to its Control-M job",
    schemas={"inventory": ["include", "flow", "schedule", "waits_for"], "finding": ["decision", "severity", "flow", "what"]},
    work={
        "assess": wb.Work(title="See which jobs fail, what waits behind them, and what is risky in the schedule", platforms=("controlm", "autosys", "cron"), steps={
            "Connect": wb.Step(kind="platform", run=a_connect, agent="Reader", text="Every connected scheduler and the uploaded crontab or JIL files, read-only"),
            "Inventory": wb.Step(kind="platform", run=a_inventory, agent="Scanner", edit=INV_EDIT, text="Every job: schedule, command, what it waits for, its runs"),
            "Health": wb.Step(kind="proof", run=a_health, view="gates", agent="Checker", text="Rules: jobs ending not OK and their cause, what is held behind them, passwords on command lines, late files, slow-downs, duplicates"),
            "Findings": wb.Step(kind="deterministic", run=n8.a_findings, agent="Checker", edit=n8.FIND_EDIT, text="The findings, for you to keep or ignore"),
            "Estimate": wb.Step(kind="deterministic", run=a_estimate, view="plan", agent="Estimator", text="Effort per kind of finding")}),
        "develop": wb.Work(title="A new job on Control-M or AutoSys - defined with you, proven on its run times and what it waits for, deployed after approval", needs_source=False,
                           platforms=("controlm", "autosys"),
                           fields=[wb.Field("job", "The new job's name (optional)"), wb.Field("folder", "Control-M folder for it (a new one)", default="RELAY_NEW_JOBS")], steps={
            "Describe": wb.Step(kind="platform", run=d_describe, agent="Reader", text="The scheduler read: its jobs, hosts and users - what the new job must fit"),
            "Shape": wb.Step(kind="deterministic", run=d_shape, agent="Designer", edit=NEW_EDIT, confirm="the new jobs: command, host, who it runs as, when, what it waits for",
                             text="The job as you want it - rules refuse a taken name, an unknown host, a password on the command line, a wait on a job that is not there"),
            "Build": wb.Step(kind="deterministic", run=d_build, agent="Builder", text="The definition by rules: a Control-M folder or AutoSys JIL, with an alarm when it ends not OK"),
            "Prove": wb.Step(kind="proof", run=d_prove, view="gates", agent="Checker", back_to="shape",
                             text="The scheduler accepts it; the next five runs fall when you asked; every wait is real; no password on a command line"),
            "Ship": wb.Step(kind="person", run=d_ship, view="plan", approver=True, text="The named approver signs the new jobs off"),
            "Run": wb.Step(kind="platform", run=d_run, view="link", agent="Deployer", text="Deployed after its own approval and read back from the scheduler")}),
        "change": wb.Work(title="Fix a failing Control-M or AutoSys job from its runs, released with approval", needs_source=False, platforms=("controlm", "autosys"), steps={
            "Request": wb.Step(kind="platform", run=c_request, agent="Run reader", text="The job, its orders and output, and what waits for it"),
            "Diagnose": wb.Step(kind="deterministic", run=n8.c_diagnose, view="gates", agent="Diagnoser", edit=n8.DIAG_EDIT, text="Each failure's own words name its cause, rules first"),
            "Fix": wb.Step(kind="deterministic", run=c_fix, agent="Fixer", edit=FIX_EDIT, text="The job's definition changed in a copy (a variable) - you confirm the new value"),
            "Prove": wb.Step(kind="proof", run=c_prove, view="gates", agent="Checker", back_to="fix", text="Only the variable differs; Control-M's build accepts the folder; what waits for it is listed"),
            "Approve": wb.Step(kind="person", run=c_approve, view="plan", approver=True, text="The named approver releases the change"),
            "Learn": wb.Step(kind="platform", run=c_learn, agent="Deployer", text="After its own approval: the folder deployed, the failed order rerun, what waited for it watched; the fix kept as a rule")},
            fields=[wb.Field("job", "Job to fix", "text", required=True, help="Its name on the scheduler"), wb.Field("variable", "Variable to change (if you know it)", "text"),
                    wb.Field("value", "New value (if you know it)", "text")]),
        "migrate": wb.Work(title="Move cron or AutoSys jobs to Control-M - the same run times and conditions, proven before it ships", platforms=("cron", "autosys", "controlm"), steps={
            "Discover": wb.Step(kind="platform", run=m_discover, agent="Scanner", text="The crontab files, and AutoSys's jobs and boxes (connected or a JIL export): every job, its schedule and user"),
            "Decide": wb.Step(kind="deterministic", run=m_decide, agent="Decider", edit=DECIDE_EDIT,
                              text="Move, retire or keep each; AutoSys's conditions filled in, what each cron job waits for added by you (cron had no dependencies)"),
            "Convert": wb.Step(kind="deterministic", run=m_convert, agent="Converter",
                               text="A Control-M folder by rules: When from the cron fields or the JIL (a box's schedule for its jobs), events for conditions, variables from envvars"),
            "Prove": wb.Step(kind="proof", run=m_prove, view="gates", agent="Checker", back_to="convert",
                             text="Control-M's build accepts it; the next five runs fall at the same times on both; every AutoSys condition is an event"),
            "Hand over": wb.Step(kind="person", run=m_handover, view="plan", approver=True, text="The owner signs off"),
            "Run": wb.Step(kind="platform", run=m_run, view="text", agent="Deployer", text="The folder is deployed after its own approval")},
            fields=[wb.Field("folder", "Control-M folder name", "text", default="LARKSPUR_FROM_CRON")]),
        "run": wb.Work(title="Watch Control-M's orders; failures go to a person first", needs_source=False, platforms=("controlm",), steps={
            "Watch": wb.Step(kind="platform", run=r_watch, view="gates", agent="Watcher", text="The orders since the last round: what ended not OK and what waits behind it"),
            "Alert": wb.Step(kind="deterministic", run=n8.r_alert, agent="Triage", text="Failures grouped by job and cause, each with its likely cause"),
            "Fix": wb.Step(kind="deterministic", run=n8.r_fix, agent="Triage", edit=RFIX_EDIT, text="Relay proposes who fixes each - a Change item, Self-healing, a rerun, a ticket - and you confirm"),
            "Approve": wb.Step(kind="platform", run=r_approve, agent="Dispatcher", text="The approved hand-offs go out"),
            "Report": wb.Step(kind="deterministic", run=n8.r_report, agent="Reporter", confirm_if=lambda ctx, out: bool(ctx.get("breaks")), text="A run report against the last rounds")},
            fields=[wb.Field("desk", "Service desk for tickets", "select", options=_w2.desk_options), wb.Field("schedule", "Watch it", "cadence", default={"every": "hour", "tz": "UTC"})]),
    }))
