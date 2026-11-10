"""RPA (registry id `rpa`) — bots on UiPath, Blue Prism, Automation Anywhere and Power Automate Desktop (adapters in
rpa_platforms.py; the shared W2 kit _w2.py; the n8n converter and its proving steps from n8n.py).

Assess   Connect → Inventory → Health → Findings → Estimate: every connected RPA platform (and its files: .xaml, .nupkg,
         .bprelease, task-bot .json, Robin scripts) read into one inventory; health by rules — failing bots with their
         cause (a selector that no longer finds its element), credentials kept in clear (a variable's default, a Text
         data item), screen steps on systems that have an API, switched-off bots to retire, business exceptions.
Change   Request → Diagnose → Fix → Prove → Approve → Learn (UiPath): a faulting bot diagnosed from its jobs; the
         selector changed in a copy of its package (the version raised), checked by rules; the named approver releases
         it; after the release's own approval the package is uploaded, the release moved to it and a check job run; the
         fix kept as a rule.
Migrate  Discover → Decide → Convert → Prove → Hand over → Run: bots read into the neutral model; by rules a bot whose
         screens all have an API moves to n8n (screen steps become API calls), one that works a screen with no API
         (the GST portal) stays a bot; converted, proven on a test copy in n8n after approval, signed off, deployed.
Run      Watch → Alert → Fix → Approve → Report: UiPath's jobs on a schedule, failures grouped by cause, a person routes
         each (Self-healing, a ticket, the bot started again after its own approval, expected).
(Develop is not offered yet: a new bot is built in the vendor's studio; Relay finds the tasks worth one in Assess.)
"""
from __future__ import annotations

import re
from xml.etree import ElementTree as ET

from .. import db
from .. import workbench as wb
from . import _w2
from . import n8n as n8
from . import n8n_flow as nf
from . import rpa_platforms as rp

MODULE = "rpa"


class RpaPlatform(wb.Platform):
    def __init__(self, label: str, kinds: tuple, uploads: tuple, simulator: str, reads: str):
        self.label, self.kinds, self.uploads, self.simulator, self.reads = label, kinds, uploads, simulator, reads


PLATFORMS = {
    "uipath": RpaPlatform("UiPath", ("uipath_orchestrator",), (".xaml", ".nupkg"), rp.UiPathOrchestrator.simulator,
                          "releases with their package's Main.xaml, jobs and their errors — read-only; a fixed package, its release and a check job only after approval"),
    "blue_prism": RpaPlatform("Blue Prism", ("blueprism_api",), (".bprelease",), rp.BluePrismApi.simulator, "processes and sessions through the API; the design from a .bprelease export"),
    "automation_anywhere": RpaPlatform("Automation Anywhere", ("aa_control_room",), (".json",), rp.AutomationAnywhereCR.simulator, "task bots with their content and the activity list"),
    "pa_desktop": RpaPlatform("Power Automate Desktop", ("pa_desktop",), (".txt",), rp.PowerAutomateDesktopDv.simulator, "desktop flows with their Robin script and flow sessions"),
    "n8n": RpaPlatform("n8n (where bots move to)", ("n8n_api",), (), "tests/mocklab/sims/n8n.py: n8n", "test copies and deploys of the converted flows, each after its own approval"),
}


# ================================================================== the estate (connections and files)

def _uploads(ctx: wb.Ctx):
    autos, rows = [], []
    for f in ctx.files((".xaml", ".nupkg", ".bprelease", ".json", ".txt")):
        if f["name"].lower() == "payloads.json":
            continue
        got = rp.parse_file(f["name"], (ctx.dir / "data" / f["name"]).read_bytes())
        if not got.get("kind"):
            continue
        for a in got["autos"]:
            a.update(connection=None, platform_label=f"{got['kind']} (upload)", upload=f["name"])
        autos += got["autos"]
        rows.append({"source": f["name"], "kind": got["kind"], "ok": not got.get("error"), "sees": got.get("error") or f"{len(got['autos'])} bot(s)"})
    return autos, [], rows


def _estate(ctx: wb.Ctx):
    autos, runs, rows = _w2.read_estate(ctx, rp.RPA, since_days=60)
    ua, ur, urow = _uploads(ctx)
    return autos + ua, runs + ur, rows + urow


def a_connect(ctx: wb.Ctx) -> dict:
    autos, runs, rows = _estate(ctx)
    if not rows:
        raise wb.StepFailed("Nothing to read: pick an RPA connection (UiPath, Blue Prism, Automation Anywhere, Power Automate Desktop) or upload the bots' files.")
    good = [r for r in rows if r["ok"]]
    if not good:
        raise wb.StepFailed("None of the sources answered: " + "; ".join(f"{r['source']}: {r['sees']}" for r in rows)[:600])
    n8._save(ctx, "estate.json", {"autos": autos, "runs": runs})
    for r in rows:
        ctx.evidence(f"Read: {r['source']}", r, kind="read", ok=r["ok"])
    return {"summary": f"{len(good)} of {len(rows)} source(s) answered: {len(autos)} bot(s), {len(runs)} run(s) — read-only.", "counts": {"sources": len(rows), "bots": len(autos), "runs": len(runs)},
            "data": _w2.table(["Source", "Kind", "Status", "What Relay sees"], [[r["source"], r["kind"], "answered" if r["ok"] else "refused", r["sees"]] for r in rows])}


# ================================================================== Fix / change (UiPath)

BOT_KINDS = ("uipath_orchestrator", "pa_desktop")


def _bot_conn(ctx: wb.Ctx, *, write: bool = False) -> dict:
    cs = [c for c in ctx.connections() if c["kind"] in BOT_KINDS]
    if not cs:
        raise wb.StepFailed("Start the work item with the UiPath Orchestrator or Power Automate Desktop connection the bot runs on.")
    from .. import connectors
    if write and not connectors.may_write(cs[0]):
        raise wb.StepFailed(f"{cs[0]['name']} is read-only: change its scope to “Read & write — with approval” so the release can be approved.")
    return cs[0]


def _uipath(ctx: wb.Ctx, *, write: bool = False) -> dict:
    c = _bot_conn(ctx, write=write)
    if c["kind"] != "uipath_orchestrator":
        raise wb.StepFailed("This needs the UiPath Orchestrator connection.")
    return c


def _kind(ctx) -> str:
    return (n8._read(ctx, "flow.json", {}) or {}).get("kind") or "uipath_orchestrator"


def c_request(ctx: wb.Ctx) -> dict:
    c = _bot_conn(ctx)
    a = rp.UiPathOrchestrator() if c["kind"] == "uipath_orchestrator" else rp.PowerAutomateDesktopDv()
    want = str(ctx.scope.get("process") or ctx.brief or "").strip().lower()
    bots = a.estate(c)
    b = next((x for x in bots if x["name"].lower() == want or str(x.get("process_key") or "").lower() == want), None) or \
        next((x for x in bots if want and (x["name"].lower() in want or want in x["name"].lower())), None)
    if not b:
        raise wb.StepFailed(f"No bot named “{ctx.scope.get('process') or ctx.brief}” on {c['name']}: " + ", ".join(x["name"] for x in bots[:8]))
    runs = [r for r in a.runs(c, bots) if r["target"] == b["id"]]
    if c["kind"] == "pa_desktop":
        cd, text = a.script(c, b["id"])
        n8._save(ctx, "flow.json", {"workflow": {k: v for k, v in b.items() if k != "definition"}, "runs": runs, "xaml": text, "clientdata": cd, "kind": c["kind"]})
        what = "desktop flow"
    else:
        n8._save(ctx, "flow.json", {"workflow": {k: v for k, v in b.items() if k != "definition"}, "runs": runs, "xaml": b["definition"], "kind": c["kind"]})
        what = f"package {b['package']}"
    h = _w2.history(runs, b["id"])
    ctx.evidence(f"Runs of {b['name']}", {"rows": [{"id": r["id"], "status": r["status"], "start": _w2.iso(r["start"]), "error": r["error"]} for r in runs]}, kind="runs", ok=True)
    return {"summary": f"“{b['name']}” ({what}) on {c['name']}: {h['runs']} run(s), {h['failed']} failed" + (f", failing for {h['failing_days']:g} day(s)" if h["failing_days"] else "") + ".",
            "counts": {"runs": h["runs"], "failed": h["failed"]},
            "data": _w2.table(["Run", "State", "Started", "Error"], [[r["id"], r["status"], _w2.when(r["start"]), (r.get("error") or "")[:160]] for r in sorted(runs, key=lambda x: -(x["start"] or 0))[:40]])}


def _xaml(ctx) -> str:
    return (n8._read(ctx, "flow.json", {}) or {}).get("xaml") or ""


def _changed(ctx, recs=None) -> str:
    x = _xaml(ctx)
    for r in recs if recs is not None else ctx.records("fix"):
        if r.get("find"):
            x = x.replace(r["find"], r.get("replace") or "")
    return x


def _learned(text: str) -> list[dict]:
    """Selector fixes Relay learned on any RPA platform whose old element is in this bot's definition."""
    out = []
    for r in db.q("SELECT * FROM w2_fix_rules WHERE module = ? AND signature = 'screen_changed' ORDER BY updated DESC", (MODULE,)):
        f = _w2.j(r["fix"], {})
        if f.get("find") and f.get("replace") and f["find"] in text and not any(x["find"] == f["find"] for x in out):
            out.append({"find": f["find"], "replace": f["replace"], "why": f"learned from {r['learned_from']}: the same element changed there"})
    return out


def c_fix(ctx: wb.Ctx) -> dict:
    have = ctx.records(ctx.step_id)
    recs = have or []
    if not have:
        for d in ctx.records("diagnose"):
            if d["fix"] == "update_selector":
                el = (re.search(r"(?:id|aaname|name)='([^']+)'", d.get("last_error") or "") or [None, ""])[1]
                if el:
                    recs.append({"id": f"c-{d['id']}", "what": "selector", "find": el, "replace": str(ctx.scope.get("selector") or (_w2.learned_fix(MODULE, d["signature"]) or {}).get("fix", {}).get("replace") or ""),
                                 "why": d["cure"]})
        if not recs:                                             # the error names no element (a desktop flow): a fix learned elsewhere, if it fits
            recs = [{"id": f"l-{i}", "what": "selector", **x} for i, x in enumerate(_learned(_xaml(ctx)))]
    probs = _change_problems(recs, ctx)
    where = "Orchestrator" if _kind(ctx) == "uipath_orchestrator" else "Power Automate"
    return {"summary": (f"{len(recs)} change(s) on a copy: " + "; ".join(f"selector element “{r['find']}” → “{r['replace'] or '(type the new one)'}”" for r in recs) +
                        f". Nothing changes on {where} until the release is approved.") if recs else "No rule knows a change for this: add the selector to change and its new value.",
            "records": recs, "counts": {"changes": len(recs)}, "items": probs[:6],
            "data": _w2.table(["What", "Find", "Replace with", "Why"], [[r["what"], r.get("find") or "", r.get("replace") or "", r.get("why") or ""] for r in recs])}


def _change_problems(recs: list[dict], ctx) -> list[str]:
    x = _xaml(ctx)
    what = "Main.xaml" if _kind(ctx) == "uipath_orchestrator" else "desktop flow's script"
    out = [] if recs else ["add the change: the selector element to find and its new value"]
    for r in recs:
        if not r.get("find") or r["find"] not in x:
            out.append(f"“{r.get('find')}” is not in the bot's {what} (nothing would change)")
        if not str(r.get("replace") or "").strip():
            out.append(f"type the new value for “{r.get('find')}” (from the changed screen: its element id)")
        if re.search(r"[<>\"']", str(r.get("replace") or "")):
            out.append("the new value is an element id, without quotes or brackets")
    return out


def _validate_fix(recs, ctx):
    return _change_problems(recs, ctx)


FIX_EDIT = wb.Edit(columns=[wb.Column("find", "Find (selector element)"), wb.Column("replace", "Replace with"), wb.Column("why", "Why", readonly=True)], add=True, remove=True,
                   validate=_validate_fix, label="change")


def _next_version(v: str) -> str:
    p = [int(x) if x.isdigit() else 0 for x in str(v or "1.0.0").split(".")]
    p += [0] * (3 - len(p))
    p[2] += 1
    return ".".join(map(str, p[:3]))


def c_prove(ctx: wb.Ctx) -> dict:
    old, new = _xaml(ctx), _changed(ctx)
    wf = (n8._read(ctx, "flow.json", {}) or {}).get("workflow") or {}
    rows = []
    if _kind(ctx) == "pa_desktop":
        ol, nl = old.splitlines(), new.splitlines()
        changed = [(a, b) for a, b in zip(ol, nl) if a != b]
        finds = [r["find"] for r in ctx.records("fix")]
        rows.append(_w2.gate("scope", "Only the lines with the named selectors differ", "pass" if changed and len(ol) == len(nl) and all(any(f in a for f in finds) for a, _ in changed) else "fail",
                             len(changed), len(finds), "; ".join(b.strip()[:120] for _, b in changed[:4]) or "nothing differs"))
        rows.append(_w2.gate("steps", "The script still reads as the same steps", "pass" if len(rp.robin_steps(old)[0]) == len(rp.robin_steps(new)[0]) else "fail",
                             len(rp.robin_steps(new)[0]), len(rp.robin_steps(old)[0])))
        rows.append(_w2.gate("check", "A desktop flow runs on a person's or a robot's machine: a check run is a person's step after the update", "skip"))
        ctx.output("desktop-flow.txt", new, label="The changed desktop flow (Robin)")
        bad = [g for g in rows if g["status"] == "fail"]
        return {"summary": f"The change touches {len(changed)} line(s) of “{wf.get('name')}”." + (" Send it back to Fix: " + bad[0]["detail"] if bad else ""),
                "counts": {"differences": len(changed), "fail": len(bad)}, "data": _w2.gates(rows), "ok": not bad}
    try:
        ET.fromstring(new)
        rows.append(_w2.gate("parses", "The changed Main.xaml is well-formed XAML", "pass"))
    except ET.ParseError as e:
        rows.append(_w2.gate("parses", "The changed Main.xaml is well-formed XAML", "fail", detail=str(e)[:200]))
    olds, news = rp.xaml_steps(old), rp.xaml_steps(new)
    diff = [(a["label"], a["field"], b["field"]) for a, b in zip(olds, news) if a != b]
    rows.append(_w2.gate("scope", "Only the selectors named in the change differ", "pass" if diff and len(olds) == len(news) and all(o != n for _, o, n in diff) else "fail", len(diff), len(ctx.records("fix")),
                         "; ".join(f"{lbl}: {o} → {n}" for lbl, o, n in diff) or "nothing differs"))
    ver = _next_version(wf.get("version"))
    ctx.put("version", ver)
    rows.append(_w2.gate("version", "The package version is raised (Orchestrator keeps the old one for a roll back)", "pass", f"{wf.get('version')} → {ver}"))
    rows.append(_w2.gate("check", "A check job runs right after the release (a bot runs on the production robots: there is no test copy)", "skip", detail="part of the release's own approval"))
    ctx.output("Main.xaml", new, label="The changed Main.xaml")
    bad = [g for g in rows if g["status"] == "fail"]
    return {"summary": f"The change touches {len(diff)} activity(ies); package {wf.get('version')} → {ver}." + (" Send it back to Fix: " + bad[0]["detail"] if bad else ""),
            "counts": {"differences": len(diff), "fail": len(bad)}, "data": _w2.gates(rows), "ok": not bad}


def c_approve(ctx: wb.Ctx) -> dict:
    wf = (n8._read(ctx, "flow.json", {}) or {}).get("workflow") or {}
    if _kind(ctx) == "pa_desktop":
        return {"summary": f"Update the desktop flow “{wf.get('name')}” in Power Automate.",
                "data": {"items": [{"title": "The change", "detail": "; ".join(f"{r['find']} → {r['replace']}" for r in ctx.records("fix"))},
                                   {"title": "Then", "detail": "The desktop flow's script is updated through Dataverse and read back — one approval for exactly that; its owner runs it once to check; the fix is kept as a rule."}]}}
    return {"summary": f"Release package {ctx.get('version')} of “{wf.get('name')}”, move its release to it and run a check job.",
            "data": {"items": [{"title": "The change", "detail": "; ".join(f"{r['find']} → {r['replace']}" for r in ctx.records("fix"))},
                               {"title": "Then", "detail": "The package is uploaded to Orchestrator, the release updated and one job started to check it — one approval for exactly that; the fix is kept as a rule."}]}}


def c_learn(ctx: wb.Ctx) -> dict:
    p = _w2.push_of(ctx.id, ctx.step_id)
    if not p or p["status"] in ("failed", "refused"):
        c = _bot_conn(ctx, write=True)
        f = n8._read(ctx, "flow.json", {}) or {}
        wf = f.get("workflow") or {}
        if c["kind"] == "pa_desktop":
            _w2.request_push(ctx, c["id"], "update_script", {"workflow_id": wf["id"], "script": _changed(ctx), "clientdata": f.get("clientdata"), "expect": [r["replace"] for r in ctx.records("fix")]},
                             f"Update the desktop flow “{wf.get('name')}” on {c['name']}", items=[f"Where: {c['name']}", "What: its script, with the selector changed", "Then: read back"])
        else:
            fx = ctx.records("fix")[0]
            _w2.request_push(ctx, c["id"], "release_fix", {"release_id": wf["id"], "release_key": wf["release_key"], "package": wf["package"], "version": ctx.get("version"), "find": fx["find"], "replace": fx["replace"]},
                             f"Release package {ctx.get('version')} of “{wf.get('name')}” on {c['name']} and run a check job",
                             items=[f"Where: {c['name']} (folder {c['config'].get('folder_id')})", f"Package: {wf['process_key']} {wf.get('version')} → {ctx.get('version')}",
                                    "Then: the release moves to it and one job runs to check it"])
    return _learn_view(ctx)


def _learn_view(ctx: wb.Ctx) -> dict:
    p = _w2.push_of(ctx.id, "learn")
    if p and p["status"] == "written":
        re_ = p["result"].get("reruns") or []
        good = sum(1 for r in re_ if r["status"] == "success")
        if not ctx.get("learned"):
            for d in ctx.records("diagnose"):
                _w2.learn_fix(ctx, d["signature"], d["cause"], {"text": d["cure"], "find": ctx.records("fix")[0]["find"], "replace": ctx.records("fix")[0]["replace"]})
            ctx.put("learned", True)
        if p["result"].get("updated"):
            return {"summary": "Updated: the desktop flow's script carries the new selector, read back through Dataverse. Its owner runs it once to check. The fix is kept as a rule.",
                    "counts": {"updated": 1}, "data": {"text": "Read back: the script carries " + ", ".join(p["result"].get("found") or [])}}
        return {"summary": f"Released: the release runs package {p['result'].get('version')}; the check job {'succeeded' if good == len(re_) and re_ else 'failed'}. The fix is kept as a rule.",
                "counts": {"reruns": len(re_), "succeeded": good}, "data": _w2.table(["Job", "Status", "Error"], [[r.get("id") or "", r["status"], r.get("error") or ""] for r in re_])}
    if p and p["status"] == "awaiting":
        return {"summary": "The change waits for its own approval in the Validation queue.", "data": {"href": "#/validate", "label": "Open the Validation queue", "text": p["what"]}}
    return {"summary": f"Not released ({(p or {}).get('status') or 'not asked'}): run this step again.", "data": {"text": str(((p or {}).get("result") or {}).get("error") or "")}}


_w2.REFRESH["rpa.change.learn"] = _learn_view
_w2.REFRESH["rpa.migrate.prove"] = n8._mprove_view          # the n8n steps Migrate reuses: redrawn when their writes land
_w2.REFRESH["rpa.migrate.run"] = n8._mrun_view


# ================================================================== Migrate (bots → n8n)

def m_discover(ctx: wb.Ctx) -> dict:
    autos, runs, rows = _estate(ctx)
    if not autos:
        raise wb.StepFailed("No bots: pick the RPA platform's connection or upload the bots' files.")
    n8._save(ctx, "estate.json", {"autos": autos, "runs": runs})
    for a in autos:
        _w2.lineage_auto(ctx, a, kind="flow")
    return {"summary": f"{len(autos)} bot(s) read on {len({a.get('platform_label') or a['platform'] for a in autos})} platform(s), with {len(runs)} run(s) of history — read-only.",
            "counts": {"bots": len(autos), "runs": len(runs)}, "data": _w2.table(["Bot", "Platform", "Steps", "Screen steps", "Runs"],
                                                                                [[a["name"], a.get("platform_label") or a["platform"], len(a["steps"]), sum(1 for s in a["steps"] if s.get("screen")),
                                                                                  _w2.history(runs, a["id"])["runs"]] for a in autos])}


def m_decide(ctx: wb.Ctx) -> dict:
    est = n8._read(ctx, "estate.json", {})
    autos, runs = est.get("autos") or [], est.get("runs") or []
    have = {r["id"]: r for r in ctx.records(ctx.step_id)}
    fs = _w2.findings(autos, runs)
    recs = []
    for a in autos:
        mine = [f for f in fs if f["auto"] == a["id"]]
        no_api = sorted({s["system"] for s in a["steps"] if s.get("screen") and (s.get("system") in _w2.SCREEN_ONLY or not s.get("system"))})
        if any(f["kind"] == "retire" for f in mine):
            dec, why = "retire", next(f["what"] for f in mine if f["kind"] == "retire")
        elif no_api:
            dec, why = "keep", f"it works a screen with no API ({', '.join(x or 'an unknown application' for x in no_api)}): it stays a bot"
        elif any(s["kind"] == "extract" for s in a["steps"]):
            dec, why = "keep", "it reads documents (an extraction model): it stays a bot until Document processing takes the extraction over"
        else:
            scr = sorted({s["system"] for s in a["steps"] if s.get("screen")})
            dec, why = "move", f"{len(a['steps'])} step(s) to n8n" + (f"; its screens on {', '.join(scr)} become API calls" if scr else "")
        if any(f["kind"] == "secret" for f in mine):
            why += "; its credential in clear becomes a credential by name"
        rid = f"{a['platform']}:{a['id']}"
        recs.append({"id": rid, "auto": a["id"], "flow": a["name"], "platform": a.get("platform_label") or a["platform"], "decision": (have.get(rid) or {}).get("decision") or dec,
                     "why": (have.get(rid) or {}).get("why") or why, "fix": (have.get(rid) or {}).get("fix", ""), "runs": _w2.history(runs, a["id"])["runs"]})
    n = {k: sum(1 for r in recs if r["decision"] == k) for k in ("move", "merge", "retire", "keep")}
    return {"summary": f"Rules suggest: {n['move']} to move to n8n, {n['keep']} to keep as bots (a screen with no API), {n['retire']} to retire — change any decision, with the reason.",
            "records": recs, "counts": n, "data": _w2.table(["Bot", "Platform", "Decision", "Why"], [[r["flow"], r["platform"], r["decision"], r["why"]] for r in recs])}


def _api_steps(ctx):
    """Screen steps on a system with an API become API calls before conversion (the system's documented endpoint)."""
    est = n8._read(ctx, "estate.json", {})
    for a in est.get("autos") or []:
        for s in a["steps"]:
            if s.get("screen") and s.get("system") in _w2.API_SYSTEMS:
                s["kind"], s["api"] = "post", s.get("api") or f"POST {nf.SYSTEM_URL.get(s['system'], '') or '/'}"
    n8._save(ctx, "estate.json", est)


def m_convert(ctx: wb.Ctx) -> dict:
    _api_steps(ctx)
    return n8.m_convert(ctx)


# ================================================================== Run & support (UiPath jobs)

def r_watch(ctx: wb.Ctx) -> dict:
    c = _uipath(ctx)
    a = rp.UiPathOrchestrator()
    bots = {b["id"]: b for b in a.estate(c)}
    want = {x.strip().lower() for x in str(ctx.scope.get("bots") or "").split(",") if x.strip()}
    bots = {k: b for k, b in bots.items() if not want or b["name"].lower() in want or k in want}
    since = ctx.get("since") or 0
    runs = [r for r in a.runs(c, list(bots.values())) if r["target"] in bots]
    new = [r for r in runs if (r["start"] or 0) > since]
    ctx.put("since", max([r["start"] or 0 for r in runs] + [since]))
    ctx.put("failures", [{**r, "workflow": bots[r["target"]]["name"], "release_key": bots[r["target"]]["release_key"]} for r in new if r["status"] == "failed"])
    checks = []
    for k, b in bots.items():
        mine = [r for r in new if r["target"] == k]
        bad = [r for r in mine if r["status"] == "failed"]
        checks.append(_w2.gate(f"bot-{k}", b["name"], "fail" if bad else "pass", f"{len(mine) - len(bad)} of {len(mine)} succeeded", "every job succeeds",
                               (bad[0]["error"] or "")[:200] if bad else ("scheduled" if b["active"] else "switched off")))
    return {"summary": f"{len(new)} new job(s) on {len(bots)} bot(s) since the last round: {sum(1 for r in new if r['status'] == 'failed')} faulted.",
            "counts": {"bots": len(bots), "executions": len(new), "failed": sum(1 for r in new if r["status"] == "failed")}, "data": _w2.gates(checks)}


def r_approve(ctx: wb.Ctx) -> dict:
    rows, out = [], []
    keys = {f["target"]: f.get("release_key") for f in ctx.get("failures") or []}
    for b in ctx.records("fix"):
        title = f"{b['workflow']}: {b['signature'].replace('_', ' ')}"
        body = f"{b['error']}\n\nLikely cause: {b['cause']}\nWhat cures it: {b['cure']}\n{('Note: ' + b['note']) if b.get('note') else ''}\nWork item: {wb.route_of(ctx.st)}"
        if b["route"] == "heal":
            h = ctx.heal(title, body, place=f"{b['workflow']} (UiPath)", signature=f"rpa:{b['signature']}", subject={"bot": b["target"], "jobs": b["executions"][-5:]})
        elif b["route"] == "ticket":
            h = _w2.desk_ticket(ctx, str(ctx.scope.get("desk") or ""), title, body, priority="P2" if b["signature"] in ("screen_changed", "credential_expired") else "P3", ref=b["id"])
        elif b["route"] == "rerun":
            c = _uipath(ctx, write=True)
            cp = _w2.request_push(ctx, c["id"], "retry", {"releases": [keys.get(b["target"])]}, f"Start {b['workflow']} again on {c['name']}", items=[f"Where: {c['name']}", f"Bot: {b['workflow']}"])
            h = {"kind": "write", "label": title, "status": "awaiting approval", "checkpoint": cp["id"]}
        else:
            h = {"kind": b["route"], "label": title, "status": "expected — recorded" if b["route"] == "expected" else "ignored this time"}
        out.append(h)
        rows.append([b["workflow"], b["cause"], b["route"], h.get("status"), h.get("case") or h.get("checkpoint") or h.get("output") or ""])
    return {"summary": f"{sum(1 for h in out if h['kind'] == 'heal')} to Self-healing, {sum(1 for h in out if h['kind'] == 'ticket')} ticket(s), {sum(1 for h in out if h['kind'] == 'write')} restart(s) awaiting approval — as you approved.",
            "data": _w2.table(["Bot", "Cause", "Route", "Status", "Reference"], rows), "counts": {"hand-offs": len(out)}}


GUIDE = """# RPA — the work item

This folder is one work item of Relay's RPA module (UiPath, Blue Prism, Automation Anywhere, Power Automate Desktop).
Relay's rules read the bots and their runs, find what fails and why, and change a bot only through a package a named
person released. A bot that can be an API flow moves to n8n; one that works a screen with no API stays a bot. Nothing is
invented: every finding comes from a bot's own definition or its runs."""

wb.register(wb.Pack(
    module=MODULE, guide=GUIDE, platforms=PLATFORMS, cards=None,
    lineage="each bot as a flow node and the systems it touches; a migrated bot linked to its n8n flow",
    schemas={"inventory": ["include", "flow", "platform", "runs"], "finding": ["decision", "severity", "flow", "what"]},
    work={
        "assess": wb.Work(title="See which bots fail, keep secrets in clear, or could be API calls", platforms=("uipath", "blue_prism", "automation_anywhere", "pa_desktop"), steps={
            "Connect": wb.Step(kind="platform", run=a_connect, agent="Reader", text="Every connected RPA platform and the uploaded bot files, read-only"),
            "Inventory": wb.Step(kind="platform", run=n8.a_inventory, agent="Scanner", edit=n8.INV_EDIT, text="Every bot in the tool's own terms: its trigger, steps, runs and failures"),
            "Health": wb.Step(kind="proof", run=n8.a_health, view="gates", agent="Checker", text="Rules: failing bots and their cause, credentials in clear, screens with an API, switched-off bots, exceptions"),
            "Findings": wb.Step(kind="deterministic", run=n8.a_findings, agent="Checker", edit=n8.FIND_EDIT, text="The findings, for you to keep or ignore"),
            "Estimate": wb.Step(kind="deterministic", run=n8.a_estimate, view="plan", agent="Estimator", text="Waves with effort: fix what fails, take the secrets out, move what can be an API flow, retire")}),
        "change": wb.Work(title="Fix a faulting UiPath bot or desktop flow from its runs, released with approval", needs_source=False, platforms=("uipath", "pa_desktop"), steps={
            "Request": wb.Step(kind="platform", run=c_request, agent="Run reader", text="The bot and its jobs are read — the faulted ones with their error"),
            "Diagnose": wb.Step(kind="deterministic", run=n8.c_diagnose, view="gates", agent="Diagnoser", edit=n8.DIAG_EDIT, text="Each failure's own words name its cause, rules first (a changed screen, an expired credential, a timeout)"),
            "Fix": wb.Step(kind="deterministic", run=c_fix, agent="Fixer", edit=FIX_EDIT, text="The selector changed in a copy of the package — you type the new element from the changed screen"),
            "Prove": wb.Step(kind="proof", run=c_prove, view="gates", agent="Checker", back_to="fix", text="The changed Main.xaml parses, only the named selectors differ, the version is raised"),
            "Approve": wb.Step(kind="person", run=c_approve, view="plan", approver=True, text="The named approver releases the new package"),
            "Learn": wb.Step(kind="platform", run=c_learn, agent="Deployer", text="After its own approval: the package uploaded, the release moved to it, a check job run; the fix kept as a rule")},
            fields=[wb.Field("process", "Bot to fix", "text", required=True, help="Its name or process key on the UiPath connection"),
                    wb.Field("selector", "New selector element (if you know it)", "text", help="The element id on the changed screen, e.g. GSTR1_V2-upload")]),
        "migrate": wb.Work(title="Move bots to n8n where every screen has an API — proven before it ships", platforms=("uipath", "blue_prism", "automation_anywhere", "pa_desktop", "n8n"), steps={
            "Discover": wb.Step(kind="platform", run=m_discover, agent="Scanner", text="The bots and their run history, read-only, into one neutral model"),
            "Decide": wb.Step(kind="deterministic", run=m_decide, agent="Decider", edit=n8.DECIDE_EDIT, text="Move, keep as a bot, merge or retire — by rules: a screen with no API stays a bot"),
            "Convert": wb.Step(kind="deterministic", run=m_convert, agent="Converter", text="Each moving bot becomes an n8n workflow by rules — its screens become the systems' API calls, credentials by name"),
            "Prove": wb.Step(kind="proof", run=n8.m_prove, view="gates", agent="Flow tester", edit=n8.MPROOF_EDIT, back_to="convert", text="A test copy in n8n runs the same payloads, compared with the bot's own history"),
            "Hand over": wb.Step(kind="person", run=n8.m_handover, view="plan", approver=True, text="The owner signs off on the evidence pack"),
            "Run": wb.Step(kind="platform", run=n8.m_run, view="link", agent="Deployer", text="The converted flows are deployed to n8n after their own approval and watched; switch the bots off once they run")},
            fields=[wb.Field("payloads", "Sample payloads for the test runs", "longtext")]),
        "run": wb.Work(title="Watch UiPath's jobs; failures go to Self-healing or the service desk after a person decides", needs_source=False, platforms=("uipath",), steps={
            "Watch": wb.Step(kind="platform", run=r_watch, view="gates", agent="Watcher", text="The bots' jobs since the last round, read-only"),
            "Alert": wb.Step(kind="deterministic", run=n8.r_alert, agent="Triage", text="Failures grouped by bot and cause, each with its likely cause"),
            "Fix": wb.Step(kind="deterministic", run=n8.r_fix, agent="Triage", edit=n8.RFIX_EDIT, text="Relay proposes who fixes each — Self-healing, a ticket, a restart — and you confirm or change it"),
            "Approve": wb.Step(kind="platform", run=r_approve, agent="Dispatcher", text="The approved hand-offs go out: Self-healing, a ticket (after its own approval) or a restart (its own approval)"),
            "Report": wb.Step(kind="deterministic", run=n8.r_report, agent="Reporter", confirm_if=lambda ctx, out: bool(ctx.get("breaks")), text="A run report against the last rounds")},
            fields=[wb.Field("bots", "Bots to watch", "text", help="Names, separated by commas — blank: all of them"),
                    wb.Field("desk", "Service desk for tickets", "select", options=_w2.desk_options), wb.Field("schedule", "Watch it", "cadence", default={"every": "hour", "tz": "UTC"})]),
    }))
