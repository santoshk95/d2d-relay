"""Workflows & iPaaS (registry id `n8n`) — flows between apps, n8n first, then Power Automate, Zapier, Make, Workato,
Boomi and MuleSoft (adapters in n8n_platforms.py; the n8n workflow JSON toolkit in n8n_flow.py; the shared W2 kit _w2.py).

Assess   Connect → Inventory → Health → Findings → Estimate: every connected platform (and exports) read into one
         inventory; health by rules (failing flows with their cause, flaky ones, secrets kept in clear, switched-off flows
         to retire, screen steps where an API exists, no owner); the person keeps or ignores each finding; effort per wave.
Develop  Describe → Design → Build → Prove → Deploy → Run: the flow in plain words or from a process map (W4's published
         BPMN, or a .bpmn upload); the design drawn by rules from the map (Relay drafts it from plain words on request),
         corrected in place — credentials by name only; the agent writes the n8n workflow JSON, which Relay's rules check
         strictly (fix rounds); test executions with sample payloads on a copy in n8n after their own approval; the named
         approver signs the go-live; the deploy through n8n's API after its own approval; a Run item watches it.
Change   Request → Diagnose → Fix → Prove → Approve → Learn: a failed run diagnosed from its run history (the error, the
         node, the cause — rules first); the change made on a copy; tested; released after approval: the workflow updated
         and its failed executions re-run (one approval); the fix kept as a rule.
Migrate  Discover → Decide → Convert → Prove → Hand over → Run: flows on Power Automate, Zapier, Make, Workato, Boomi or
         MuleSoft read into the neutral model; keep, merge, retire or move by rules (a known failure moves with its fix);
         converted to n8n by rules; proven side by side — the same payloads on the old flow and on a test copy in n8n,
         each side its own approval; owner sign-off; deployed, then watched.
Run      Watch → Alert → Fix → Approve → Report: n8n's executions on a schedule; failures grouped by cause; a person
         routes each — Self-healing, a Service desk ticket (created after its own approval), a re-run (its own approval)
         or expected — and only then do the hand-offs go out.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .. import auth, connectors, db, registry
from .. import workbench as wb
from . import _w2
from . import n8n_flow as nf
from . import n8n_platforms as npf

MODULE = "n8n"
SYSTEM = "n8n"
MINUTES = {"fix a failing flow": 90, "move a credential to the store": 30, "retire a flow": 15, "move a step to n8n": 20, "look at a finding": 15}


class IpaasPlatform(wb.Platform):
    def __init__(self, label: str, kinds: tuple, uploads: tuple, simulator: str, reads: str):
        self.label, self.kinds, self.uploads, self.simulator, self.reads = label, kinds, uploads, simulator, reads


PLATFORMS = {
    "n8n": IpaasPlatform("n8n (self-hosted or cloud)", ("n8n_api",), (".json", ".bpmn"), npf.N8nApi.simulator,
                         "workflows and executions with their run data — read-only; a deploy, a test run or a re-run only after its own approval"),
    "power_automate": IpaasPlatform("Power Automate", ("power_automate_flows",), (".json",), npf.PowerAutomateFlows.simulator, "cloud flows, their definitions, connection references and runs"),
    "zapier": IpaasPlatform("Zapier", ("zapier",), (".json", ".csv"), npf.Zapier.simulator, "zaps and their steps; run history from the Zap History export (the API does not serve it)"),
    "make": IpaasPlatform("Make", ("make",), (".json",), npf.Make.simulator, "scenarios, blueprints and their logs"),
    "workato": IpaasPlatform("Workato", ("workato",), (".json",), npf.Workato.simulator, "recipes with their code, jobs and the connections' authorisation"),
    "boomi": IpaasPlatform("Boomi", ("boomi_atomsphere", "boomi"), (".xml",), npf.BoomiAtomSphere.simulator, "processes, component XML and execution records"),
    "mulesoft": IpaasPlatform("MuleSoft", ("mulesoft_anypoint", "mulesoft"), (".xml",), npf.MuleSoftAnypoint.simulator, "CloudHub 2.0 deployments and their logs; Mule 4 XML from an export"),
}
SOURCES = ("power_automate", "zapier", "make", "workato", "boomi", "mulesoft")


# ------------------------------------------------------------------ the item's files (big things stay out of project.json)

def _save(ctx: wb.Ctx, name: str, obj) -> None:
    d = ctx.dir / "sources"
    d.mkdir(exist_ok=True)
    (d / name).write_text(json.dumps(obj, indent=1, default=str, ensure_ascii=False), encoding="utf-8")


def _read(ctx: wb.Ctx, name: str, default=None):
    p = ctx.dir / "sources" / name
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _uploads(ctx: wb.Ctx) -> tuple[list[dict], list[dict], list[dict]]:
    autos, runs, rows = [], [], []
    for f in ctx.files((".json", ".xml", ".csv")):
        if f["name"].endswith(".xlsx.csv") or f["name"].lower() in ("payloads.json",):
            continue
        got = npf.parse_file(f["name"], (ctx.dir / "data" / f["name"]).read_bytes())
        if not got.get("kind"):
            continue
        for a in got["autos"]:
            a.update(connection=None, platform_label=f"{got['kind']} (upload)", upload=f["name"])
        autos += got["autos"]
        runs += got["runs"]
        rows.append({"source": f["name"], "kind": got["kind"], "ok": True, "sees": f"{len(got['autos'])} flow(s), {len(got['runs'])} run(s)" if not got.get("error") else got["error"]})
    return autos, runs, rows


def _estate(ctx: wb.Ctx, kinds: tuple | None = None) -> tuple[list[dict], list[dict], list[dict]]:
    autos, runs, rows = _w2.read_estate(ctx, kinds or npf.IPAAS, since_days=60)
    ua, ur, urow = _uploads(ctx)
    for r in ur:                                            # a Zap History export names the zap by its id
        r["target"] = next((a["id"] for a in autos + ua if a["id"] == r["target"]), r["target"])
    return autos + ua, runs + ur, rows + urow


def _target(ctx: wb.Ctx, *, write: bool = True) -> dict:
    """The n8n this item deploys to: its own n8n connection, else the owner's only one."""
    mine = [c for c in ctx.connections() if c["kind"] == "n8n_api"]
    if not mine:
        owner = ctx.owner or ""
        mine = [connectors.connection(x["id"], owner) for x in connectors.mine(owner) if x["kind"] == "n8n_api"]
    if not mine:
        raise wb.StepFailed("No n8n connection to test and deploy on: add one under Connections (scope “Read & write — with approval”), then run this step again.")
    if len(mine) > 1 and not any(c["kind"] == "n8n_api" for c in ctx.connections()):
        raise wb.StepFailed("You have several n8n connections: start the work item with the one it deploys to.")
    c = mine[0]
    if write and not connectors.may_write(c):
        raise wb.StepFailed(f"{c['name']} is read-only: change its scope to “Read & write — with approval” so a test run and the deploy can be approved.")
    return c


def _payloads(ctx: wb.Ctx) -> list[dict]:
    raw = ctx.scope.get("payloads")
    for f in ctx.files((".json",)):
        if f["name"].lower() == "payloads.json":
            raw = (ctx.dir / "data" / f["name"]).read_text(encoding="utf-8")
    if raw:
        try:
            v = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(v, dict):
                v = [v]
            return [dict(x, _case=x.get("_case") or f"payload {i + 1}") for i, x in enumerate(v) if isinstance(x, dict)][:20] or [{"_case": "an empty call"}]
        except ValueError as e:
            raise wb.StepFailed(f"The sample payloads are not JSON: {e}") from e
    return [{"_case": "an empty call"}]


def _inv_rows(autos: list[dict], runs: list[dict]) -> list[dict]:
    out = []
    for a in autos:
        h = _w2.history(runs, a["id"])
        out.append({"id": f"{a['platform']}:{a['id']}", "include": True, "flow": a["name"], "platform": a.get("platform_label") or a["platform"], "trigger": a["trigger"]["kind"],
                    "steps": len(a["steps"]), "active": "on" if a["active"] else "off", "runs": h["runs"], "failed": h["failed"], "last_run": _w2.when(h["last_run"]), "auto": a["id"]})
    return out


# ================================================================== Assess

def a_connect(ctx: wb.Ctx) -> dict:
    autos, runs, rows = _estate(ctx)
    if not rows:
        raise wb.StepFailed("Nothing to read: pick an iPaaS connection (n8n, Power Automate, Zapier, Make, Workato, Boomi, MuleSoft) or upload their exports.")
    good = [r for r in rows if r["ok"]]
    if not good:
        raise wb.StepFailed("None of the sources answered: " + "; ".join(f"{r['source']}: {r['sees']}" for r in rows)[:600])
    _save(ctx, "estate.json", {"autos": autos, "runs": runs})
    for r in rows:
        ctx.evidence(f"Read: {r['source']}", {"source": r["source"], "kind": r["kind"], "ok": r["ok"], "sees": r["sees"]}, kind="read", ok=r["ok"])
    return {"summary": f"{len(good)} of {len(rows)} source(s) answered: {len(autos)} flow(s), {len(runs)} run(s) — read-only.", "counts": {"sources": len(rows), "flows": len(autos), "runs": len(runs)},
            "data": _w2.table(["Source", "Kind", "Status", "What Relay sees"], [[r["source"], r["kind"], "answered" if r["ok"] else "refused", r["sees"]] for r in rows])}


def a_inventory(ctx: wb.Ctx) -> dict:
    est = _read(ctx, "estate.json", {})
    have = {r["id"]: r for r in ctx.records(ctx.step_id)}
    recs = [{**r, **({"include": have[r["id"]]["include"]} if r["id"] in have else {})} for r in _inv_rows(est.get("autos") or [], est.get("runs") or [])]
    if not recs:
        raise wb.StepFailed("The sources show no flows.")
    plats = sorted({r["platform"] for r in recs})
    return {"summary": f"{len(recs)} flow(s) on {len(plats)} platform(s), in each tool's own terms — untick what is out of scope.", "records": recs,
            "counts": {"flows": len(recs), "platforms": len(plats), "on": sum(1 for r in recs if r["active"] == "on")},
            "data": _w2.table(["Flow", "Platform", "Trigger", "Steps", "On", "Runs", "Failed", "Last run"], [[r["flow"], r["platform"], r["trigger"], r["steps"], r["active"], r["runs"], r["failed"], r["last_run"]] for r in recs])}


INV_EDIT = wb.Edit(columns=[wb.Column("include", "Include", "bool"), wb.Column("flow", "Flow", readonly=True), wb.Column("platform", "Platform", readonly=True),
                            wb.Column("runs", "Runs", "number", readonly=True), wb.Column("failed", "Failed", "number", readonly=True)], add=False, remove=False, label="flow")


def _included(ctx: wb.Ctx) -> tuple[list[dict], list[dict]]:
    est = _read(ctx, "estate.json", {})
    keep = {r["auto"] for r in ctx.records("inventory") if r.get("include")}
    autos = [a for a in est.get("autos") or [] if a["id"] in keep]
    return autos, [r for r in est.get("runs") or [] if r["target"] in keep]


def a_health(ctx: wb.Ctx) -> dict:
    autos, runs = _included(ctx)
    if not autos:
        raise wb.StepFailed("No flow is included: tick at least one in the inventory.")
    fs = _w2.findings(autos, runs)
    ctx.put("findings", fs)
    for a in autos:
        _w2.lineage_auto(ctx, a)
    ctx.evidence("Findings by rule", {"rows": fs}, kind="findings", ok=True)
    checks = []
    for a in autos:
        mine = [f for f in fs if f["auto"] == a["id"]]
        worst = "fail" if any(f["severity"] == "high" for f in mine) else "warn" if any(f["severity"] == "medium" for f in mine) else "pass"
        h = _w2.history(runs, a["id"])
        checks.append(_w2.gate(f"flow-{_w2.slug(a['id'])}", f"{a['name']} ({a.get('platform_label') or a['platform']})", worst, f"{h['runs']} run(s), {h['failed']} failed",
                               "no high or medium finding", "; ".join(f["what"] for f in mine)[:400] or "healthy"))
    t = {k: sum(1 for f in fs if f["kind"] == k) for k in ("failing", "secret", "retire", "api_candidate", "flaky")}
    return {"summary": f"{len(autos)} flow(s) checked by rules: {t['failing']} failing, {t['secret']} with a credential in clear, {t['retire']} to retire, {t['api_candidate']} with screen steps an API could replace.",
            "counts": {"flows": len(autos), "findings": len(fs), "high": sum(1 for f in fs if f["severity"] == "high")}, "data": _w2.gates(checks)}


def a_findings(ctx: wb.Ctx) -> dict:
    have = {r["id"]: r for r in ctx.records(ctx.step_id)}
    recs = [{**f, **({k: have[f["id"]][k] for k in ("decision", "severity") if k in have[f["id"]]} if f["id"] in have else {})} for f in ctx.get("findings") or []]
    high = sum(1 for r in recs if r["severity"] == "high")
    return {"summary": f"{len(recs)} finding(s), {high} high — keep what matters, ignore what does not." if recs else "No finding: every included flow is healthy.", "records": recs,
            "counts": {"findings": len(recs), "high": high}, "items": [f"{r['flow']}: {r['what']}"[:240] for r in recs[:6]],
            "data": _w2.table(["Flow", "Platform", "Finding", "Severity", "What to do"], [[r["flow"], r["platform"], r["what"], r["severity"], r["do"]] for r in recs])}


FIND_EDIT = wb.Edit(columns=[wb.Column("decision", "Decision", "select", options=(("keep", "Keep"), ("ignore", "Ignore"))), wb.Column("severity", "Severity", "select", options=("high", "medium", "low")),
                             wb.Column("flow", "Flow", readonly=True), wb.Column("what", "Finding", readonly=True)], add=False, remove=False, label="finding")


def a_estimate(ctx: wb.Ctx) -> dict:
    kept = [f for f in ctx.records("findings") if f.get("decision") != "ignore"]
    autos, _ = _included(ctx)
    b = registry.brand()
    rate, cur = float(b.get("hourly_rate") or 0), b.get("currency") or ""
    fix = [f for f in kept if f["kind"] in ("failing", "flaky")]
    sec = [f for f in kept if f["kind"] == "secret"]
    ret = [f for f in kept if f["kind"] == "retire"]
    retired = {f["auto"] for f in ret}
    move = [a for a in autos if a["id"] not in retired and a["platform"] != "n8n_api"]
    waves = [("Wave 1 — fix what fails and take the secrets out", (len(fix) * MINUTES["fix a failing flow"] + len(sec) * MINUTES["move a credential to the store"]) / 60,
              f"{len(fix)} failing or flaky flow(s), {len(sec)} credential(s) kept in clear"),
             ("Wave 2 — move to n8n", sum(len(a["steps"]) for a in move) * MINUTES["move a step to n8n"] / 60, f"{len(move)} flow(s), {sum(len(a['steps']) for a in move)} step(s), converted by rules and proven side by side"),
             ("Wave 3 — retire", len(ret) * MINUTES["retire a flow"] / 60, f"{len(ret)} switched-off flow(s)")]
    items, total = [], 0.0
    for name, h, detail in waves:
        if h <= 0:
            continue
        total += h
        items.append({"title": name, "detail": detail, "effort": f"{h:.1f} h" + (f" · {cur}{rate * h:,.0f}" if rate else "")})
    assumptions = "; ".join(f"{v} min to {k}" for k, v in MINUTES.items())
    ctx.output("assessment.md", f"# Assessment: {ctx.title}\n\n" + "".join(f"## {i['title']}\n\n{i['detail']}\n\nEffort: {i['effort']}\n\n" for i in items) + f"Assumptions: {assumptions}.\n"
               + ("" if rate else "No hourly rate is set (Admin › Branding), so no cost is shown.\n"), label="Assessment (Markdown)")
    return {"summary": f"{len(items)} wave(s), about {total:.1f} h of work" + (f" ({cur}{rate * total:,.0f})" if rate else "") + ".", "counts": {"waves": len(items), "hours": round(total, 1)},
            "data": {"items": items, "total": f"{total:.1f} h", "note": f"Assumptions: {assumptions}." + ("" if rate else " Set an hourly rate under Admin › Branding to see the cost.")}}


# ================================================================== Develop

def _process(ctx: wb.Ctx) -> dict | None:
    """The process map this flow starts from: a published process (the wizard's pick, or the Business process documents
    item that handed this over), else a BPMN upload."""
    pid = ctx.scope.get("process")
    if not pid and ctx.st.get("parent"):
        try:
            par = wb._load(ctx.st["parent"])
            pid = (par.get("data") or {}).get("process_id") if par.get("module") == "processdocs" else None
        except (KeyError, FileNotFoundError):
            pid = None
    if pid and "processdocs_processes" in db.tables():
        r = db.one("SELECT * FROM processdocs_processes WHERE id = ?", (pid,))
        if r:
            return {"source": f"published process “{r['name']}” version {r['version']}", "map": _w2.j(r["map"], {}), "process_id": pid, "version": r["version"]}
    for f in ctx.files((".bpmn",)):
        from . import processdocs_bpmn as bp
        m = bp.from_bpmn((ctx.dir / "data" / f["name"]).read_text(encoding="utf-8"))
        return {"source": f"{f['name']} (BPMN 2.0)", "map": m, "process_id": None}
    return None


def process_options(u: dict) -> list[tuple[str, str]]:
    try:
        from . import processdocs
        return [("", "No — describe it in plain words")] + processdocs.process_options(u)
    except Exception:  # noqa: BLE001 - without Business process documents, plain words only
        return [("", "No — describe it in plain words")]


def d_describe(ctx: wb.Ctx) -> dict:
    p = _process(ctx)
    if not p and len(ctx.brief.strip()) < 20:
        raise wb.StepFailed("Describe the flow in a few sentences (what starts it, what it does, where the results go), or start from a process map.")
    if p:
        ctx.put("map", p["map"])
        ctx.put("map_source", p["source"])
        ctx.put("process_id", p.get("process_id"))
        steps = [s for s in p["map"].get("steps") or [] if s.get("type") not in ("end",)]
        return {"summary": f"Starting from the {p['source']}: {len(steps)} step(s) to turn into a workflow." + (" The brief is kept as context." if ctx.brief else ""),
                "counts": {"steps": len(steps)},
                "data": _w2.table(["Step", "Type", "Who", "System", "Next"], [[s.get("name"), s.get("type"), next((l["name"] for l in p["map"].get("lanes") or [] if l["id"] == s.get("lane")), ""),
                                                                              s.get("system") or "", ", ".join(n["to"] for n in s.get("next") or [])] for s in steps])}
    return {"summary": "The flow is described in plain words (no process map): Relay drafts the design from it in the next step — on your request.", "counts": {"words": len(ctx.brief.split())},
            "data": {"text": ctx.brief}}


def d_design(ctx: wb.Ctx) -> dict:
    have = ctx.records(ctx.step_id)
    notes: list[str] = []
    if have:
        recs = have
    elif ctx.get("map"):
        recs, notes = nf.design_from_map(ctx.get("map"))
    else:
        recs = []
    probs = nf.design_problems(recs) if recs else []
    summary = (f"{len(recs)} node(s) drawn by rules from the {ctx.get('map_source')}: check the trigger, each API call and its credential (by name), and the decisions' ways." if recs and ctx.get("map") and not have
               else f"{len(recs)} node(s) — correct anything in place, then confirm the design." if recs else
               "No process map: ask Relay to draft the design from your description (it proposes nodes, triggers and credentials by name), then correct it.")
    return {"summary": summary + (f" {len(probs)} problem(s) to correct first." if probs else ""), "records": recs, "counts": {"nodes": len(recs), "problems": len(probs)},
            "items": (probs or notes)[:6], "data": _design_table(recs)}


def _design_table(recs: list[dict]) -> dict:
    return _w2.table(["Node", "Type", "Role", "System", "Credential (by name)", "Next", "What it does"],
                     [[r["name"], nf.NODES.get(r["type"], ("", "", r["type"]))[2], r.get("role"), r.get("system") or "", r.get("credential") or "", r.get("next") or "", r.get("detail") or ""] for r in recs])


def _validate_design(recs: list[dict], ctx: wb.Ctx) -> list[str]:
    for r in recs:
        r["role"] = nf.NODES.get(r.get("type"), (0, r.get("role") or "action"))[1]
    return nf.design_problems(recs)


DESIGN_EDIT = wb.Edit(columns=[wb.Column("name", "Node", required=True), wb.Column("type", "Type", "select", options=nf.TYPE_OPTIONS), wb.Column("system", "System"),
                               wb.Column("credential", "Credential (by name)", help="the name of a credential stored in n8n — never the secret"),
                               wb.Column("next", "Next", help="the node(s) it leads to, separated by ; — a decision's true way first"),
                               wb.Column("detail", "What it does", "longtext")], validate=_validate_design, label="node")

DESIGN_PROMPT = """Read WORK.md, then request.md: a person described a flow in plain words. Write design.json — the nodes of
an n8n workflow as a JSON list, in order, each:

  {"name": "…", "type": "<one of the node types in node_types.json>", "system": "…", "credential": "<a credential's NAME>",
   "next": "<the next node's name; a decision lists its true way first: 'A; B'>", "detail": "what it does"}

Exactly one trigger (an e-mail, a schedule, a webhook or a form) comes first. Use an HTTP request for a system's API, an
If for a decision, Microsoft Teams or Jira to hand work to a person. Credentials by name only — never a password, key
or token. Name only systems the description names; say in `detail` what you assumed."""


def _design_prompt(ctx: wb.Ctx) -> str:
    (ctx.dir / "node_types.json").write_text(json.dumps({k: v[2] for k, v in nf.NODES.items()}, indent=1), encoding="utf-8")
    return DESIGN_PROMPT


def _design_check(ctx: wb.Ctx) -> list[str]:
    p = ctx.dir / "design.json"
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return [f"design.json was not written as JSON ({str(e)[:100]})"]
    if not isinstance(d, list) or not d:
        return ["design.json must be a list of nodes"]
    return nf.design_problems([{**x, "role": nf.NODES.get(x.get("type"), (0, "action"))[1]} for x in d if isinstance(x, dict)])


def _design_after(ctx: wb.Ctx, res: dict) -> dict:
    d = json.loads((ctx.dir / "design.json").read_text(encoding="utf-8"))
    recs = [{"id": f"n{i + 1}", "origin": "agent", "role": nf.NODES[x["type"]][1], **{k: str(x.get(k) or "") for k in ("name", "type", "system", "credential", "next", "detail")}} for i, x in enumerate(d)]
    ctx.evidence("Design drafted by Relay", {"design": recs, "note": res.get("text") or ""}, kind="agent", ok=True)
    return {"summary": f"Relay drafted {len(recs)} node(s) from your description — check every one (and each credential's name) before you confirm.", "records": recs, "data": _design_table(recs),
            "counts": {"nodes": len(recs)}}


BUILD_PROMPT = """Read WORK.md, then design.json (the nodes a person confirmed: names, types, credentials by name, what each
does and where it goes next) and skeleton.json (the workflow Relay's rules wrote from it: every node with its type,
version, position and the links between them). Write workflow.json: the same workflow with every "TODO" replaced by a
real parameter — an If's condition, a Code node's JavaScript, an API call's URL path, a Teams team and channel, a Jira
project — taken from request.md and the design. Keep every node name, type and link exactly as designed; refer to
credentials by name only (never a secret); write n8n expressions as ={{ $json.field }}."""


def _build_prompt(ctx: wb.Ctx) -> str:
    design = ctx.records("design")
    (ctx.dir / "design.json").write_text(json.dumps(design, indent=1), encoding="utf-8")
    (ctx.dir / "skeleton.json").write_text(json.dumps(nf.skeleton(ctx.title, design, seed=ctx.id), indent=1), encoding="utf-8")
    return BUILD_PROMPT


def _wf_file(ctx: wb.Ctx) -> tuple[dict | None, list[str]]:
    try:
        return json.loads((ctx.dir / "workflow.json").read_text(encoding="utf-8")), []
    except OSError:
        return None, ["workflow.json was not written"]
    except ValueError as e:
        return None, [f"workflow.json is not JSON: {str(e)[:120]}"]


def _build_check(ctx: wb.Ctx) -> list[str]:
    wf, probs = _wf_file(ctx)
    return probs or nf.problems(wf, ctx.records("design"))


def _build_after(ctx: wb.Ctx, res: dict) -> dict:
    wf, _ = _wf_file(ctx)
    ctx.put("workflow_sha", _w2.sha(wf))
    ctx.output("workflow.json", json.dumps(wf, indent=2), label="The n8n workflow (JSON)")
    rows = nf.check(wf, ctx.records("design"))
    ctx.evidence("Relay's rules on the workflow", {"rows": rows}, kind="rules", ok=all(g["status"] != "fail" for g in rows))
    return {"summary": f"The workflow is written: {len(wf['nodes'])} node(s), {sum(1 for g in rows if g['status'] == 'pass')} of {len(rows)} rule(s) pass. Next: test executions with sample payloads.",
            "counts": {"nodes": len(wf["nodes"]), "rules": len(rows)},
            "data": _w2.table(["Node", "Type", "Credentials (by name)"], [[n["name"], n["type"].split(".")[-1], ", ".join(v.get("name", "") for v in (n.get("credentials") or {}).values())] for n in wf["nodes"]])}


def _workflow(ctx: wb.Ctx) -> dict:
    p = ctx.dir / "outputs" / "workflow.json"
    if not p.exists():
        raise wb.StepFailed("The workflow has not been built yet.")
    return json.loads(p.read_text(encoding="utf-8"))


def _test_rows(ctx: wb.Ctx, sid: str) -> tuple[list[dict], dict | None]:
    p = _w2.push_of(ctx.id, sid)
    rows = []
    if p and p["status"] == "written":
        for r in p["result"].get("runs") or []:
            rows.append({"name": r.get("case"), "status": "pass" if r.get("status") == "success" else "fail", "execution": r.get("execution"), "detail": r.get("error") or
                         f"{sum(1 for n in r.get('nodes') or [] if n.get('status') == 'success')} node(s) ran"})
    return rows, p


def d_prove(ctx: wb.Ctx) -> dict:
    wf = _workflow(ctx)
    rows = nf.check(wf, ctx.records("design"))
    p = _w2.push_of(ctx.id, ctx.step_id)
    if not p or p["status"] in ("failed", "refused") or p["result"].get("sha") != _w2.sha(wf) or ctx.comment:
        c = _target(ctx)
        cases = _payloads(ctx)
        _w2.request_push(ctx, c["id"], "test_run", {"workflow": wf, "payloads": cases, "sha": _w2.sha(wf)}, f"Test-run “{wf['name']}” on {c['name']} with {len(cases)} sample payload(s)",
                         items=[f"Where: {c['name']} (n8n)", f"What: a copy named “[Relay test] {wf['name']}”, triggered by a webhook of its own, removed afterwards",
                                f"Payloads: {', '.join(x['_case'] for x in cases)}", "Nothing else on the platform changes"], meta={"sha": _w2.sha(wf)})
    return _prove_view(ctx, rows)


def _prove_view(ctx: wb.Ctx, rows: list[dict] | None = None) -> dict:
    wf = _workflow(ctx)
    rows = rows if rows is not None else nf.check(wf, ctx.records("design"))
    tests, p = _test_rows(ctx, ctx.step_id)
    out = list(rows)
    if tests:
        out.append(ctx.proof("tests_run", label="Test executions with the sample payloads", results=tests))
    elif p and p["status"] == "awaiting":
        out.append(_w2.gate("tests", "Test executions with the sample payloads", "skip", detail="waiting for the test-run approval in the Validation queue"))
    elif p:
        out.append(_w2.gate("tests", "Test executions with the sample payloads", "fail", detail=f"the test run {p['status']}: {str(p['result'].get('error') or '')[:200]}"))
    bad = [g for g in out if g["status"] == "fail"]
    passed = sum(1 for t in tests if t["status"] == "pass")
    return {"summary": (f"{sum(1 for g in rows if g['status'] == 'pass')} of {len(rows)} rule(s) pass; " + (f"{passed} of {len(tests)} test execution(s) passed on n8n." if tests else
                        "the test executions wait for their own approval." if p and p["status"] == "awaiting" else "the test run did not complete.")) + (" Send it back to Build if anything fails." if bad else ""),
            "counts": {"rules": len(rows), "tests": len(tests), "passed": passed, "fail": len(bad)}, "data": _w2.gates(out), "records": [{"id": "proof", "tests": len(tests), "passed": passed}],
            "items": [f"{g['label']}: {g['detail']}"[:240] for g in bad][:6]}


def _validate_proof(recs: list[dict], ctx: wb.Ctx) -> list[str]:
    probs = _w2.push_problems(ctx.id, ctx.step_id)
    if probs:
        return probs
    tests, p = _test_rows(ctx, ctx.step_id)
    if p and tests and any(t["status"] != "pass" for t in tests):
        return [f"{sum(1 for t in tests if t['status'] != 'pass')} test execution(s) failed: send it back to Build (proven before it ships)"]
    wf = _workflow(ctx)
    bad = [g for g in nf.check(wf, ctx.records("design")) if g["status"] == "fail"]
    return [f"{g['label']}: {g['detail']}" for g in bad]


PROOF_EDIT = wb.Edit(columns=[wb.Column("tests", "Test executions", "number", readonly=True)], add=False, remove=False, validate=_validate_proof, label="proof")
_w2.REFRESH["n8n.develop.prove"] = lambda ctx: _prove_view(ctx)


def d_deploy(ctx: wb.Ctx) -> dict:
    wf = _workflow(ctx)
    c = _target(ctx)
    tests, _ = _test_rows(ctx, "prove")
    approver = db.user(ctx.st.get("approver") or "") or {}
    act = ctx.scope.get("activate", True) not in (False, "false", "no")
    return {"summary": f"Go live: “{wf['name']}” ({len(wf['nodes'])} node(s)) to {c['name']}" + (", switched on" if act else ", left switched off") + ".",
            "data": {"items": [{"title": "What goes live", "detail": f"{len(wf['nodes'])} node(s): " + ", ".join(n["name"] for n in wf["nodes"])[:400]},
                               {"title": "Credentials (by name)", "detail": ", ".join(sorted({v.get('name') for n in wf['nodes'] for v in (n.get('credentials') or {}).values()})) or "none"},
                               {"title": "What the proof showed", "detail": f"{sum(1 for t in tests if t['status'] == 'pass')} of {len(tests)} test execution(s) passed; every rule passes"},
                               {"title": "Then", "detail": "The deploy goes through n8n's API after its own approval; a Run item watches the executions and hands failures to Self-healing."},
                               {"title": "Named approval", "detail": approver.get("name") or "the owner of this work item"}]}}


def d_run(ctx: wb.Ctx) -> dict:
    wf = _workflow(ctx)
    c = _target(ctx)
    p = _w2.push_of(ctx.id, ctx.step_id)
    if not p or p["status"] in ("failed", "refused"):
        act = ctx.scope.get("activate", True) not in (False, "false", "no")
        _w2.request_push(ctx, c["id"], "deploy", {"workflow": wf, "activate": act, "workflow_id": ctx.scope.get("workflow_id") or None},
                         f"Deploy “{wf['name']}” to {c['name']}" + (" and switch it on" if act else ""),
                         items=[f"Where: {c['name']} (n8n)", f"What: the workflow as proven ({len(wf['nodes'])} nodes)", f"Switched on: {'yes' if act else 'no'}"])
    return _run_view(ctx)


def _run_view(ctx: wb.Ctx) -> dict:
    p = _w2.push_of(ctx.id, "run")
    if p and p["status"] == "written":
        wid = p["result"].get("workflow_id")
        run_id = ctx.get("run_item")
        if not run_id and wid:
            c = _target(ctx, write=False)
            wf = _workflow(ctx)
            node = ctx.lineage_node("flow", SYSTEM, wf["name"], label=f"{wf['name']} (n8n)", properties={"workflow_id": wid, "connection": c["id"]})
            for n in wf["nodes"]:
                s = nf.system_of(str((n.get("parameters") or {}).get("url") or ""))
                if s:
                    ctx.lineage_edge(node, ctx.lineage_node("system", s, s, label=s, own=False), "calls", {"node": n["name"]})
            if ctx.get("process_id"):
                from .. import lineage
                ctx.lineage_edge(lineage.node_id("process", "Relay process documents", ctx.get("process_id")), node, "relates", {"automates": True})
            it = wb.create(MODULE, "run", f"Run: {wf['name']}"[:160], who=ctx.owner, brief=f"Watch the executions of “{wf['name']}”, deployed from {ctx.id}.", connections=[c["id"]],
                           scope={"workflows": wid, "schedule": ctx.scope.get("cadence") or {"every": "hour", "tz": "UTC"}}, approver=ctx.st.get("approver"),
                           visibility=(db.project(ctx.id) or {}).get("visibility") or "private", team_id=(db.project(ctx.id) or {}).get("team_id"), parent=ctx.id)
            ctx.put("run_item", it["id"])
            run_id = it["id"]
        return {"summary": f"Deployed to n8n as workflow {wid}" + (" and switched on" if p["result"].get("active") else "") + "; a Run item watches its executions.",
                "counts": {"deployed": 1}, "data": {"href": f"#/m/{MODULE}/i/{run_id}" if run_id else f"#/m/{MODULE}/run", "label": "Open the Run item", "text": f"n8n workflow {wid}"}}
    if p and p["status"] == "awaiting":
        return {"summary": "The deploy waits for its own approval in the Validation queue — nothing is written to n8n until a named person accepts it.", "counts": {"deployed": 0},
                "data": {"href": "#/validate", "label": "Open the Validation queue", "text": p["what"]}}
    return {"summary": f"The deploy was {p['status'] if p else 'not asked for'}: {str((p or {}).get('result', {}).get('error') or '')[:200]} Run this step again.", "counts": {"deployed": 0},
            "data": {"text": "Nothing was deployed."}}


_w2.REFRESH["n8n.develop.run"] = _run_view


# ================================================================== Fix / change

def _flow_of(ctx: wb.Ctx) -> tuple[dict, dict]:
    c = _target(ctx, write=False)
    want = str(ctx.scope.get("workflow") or "").strip().lower()
    a = npf.N8nApi()
    wfs = a.workflows(c)
    w = next((x for x in wfs if x["id"].lower() == want or x["name"].lower() == want), None) or next((x for x in wfs if want and want in x["name"].lower()), None)
    if not w:
        raise wb.StepFailed(f"No workflow named “{ctx.scope.get('workflow')}” on {c['name']}: " + ", ".join(x["name"] for x in wfs[:8]))
    return c, w


def c_request(ctx: wb.Ctx) -> dict:
    c, w = _flow_of(ctx)
    a = npf.N8nApi()
    runs = [r for r in a.runs(c, []) if r["target"] == w["id"]]
    _save(ctx, "flow.json", {"workflow": w, "runs": runs})
    ctx.put("workflow_id", w["id"])
    h = _w2.history(runs, w["id"])
    ctx.evidence(f"Run history of {w['name']}", {"rows": [{"id": r["id"], "status": r["status"], "start": _w2.iso(r["start"]), "error": r["error"], "node": r["node"]} for r in runs]}, kind="runs", ok=True)
    return {"summary": f"“{w['name']}” on {c['name']}: {h['runs']} execution(s) in its history, {h['failed']} failed" + (f", failing for {h['failing_days']:g} day(s)" if h["failing_days"] else "") + ".",
            "counts": {"runs": h["runs"], "failed": h["failed"]},
            "data": _w2.table(["Execution", "Status", "Started", "Node", "Error"], [[r["id"], r["status"], _w2.when(r["start"]), r.get("node") or "", (r.get("error") or "")[:160]] for r in sorted(runs, key=lambda x: -(x["start"] or 0))[:40]])}


def c_diagnose(ctx: wb.Ctx) -> dict:
    f = _read(ctx, "flow.json", {})
    runs = [r for r in f.get("runs") or [] if r["status"] == "failed"]
    if not runs:
        return {"summary": "No failed execution in the history: nothing to diagnose. Describe the change in the brief and correct it in the next step.", "records": [], "counts": {"failed": 0},
                "data": _w2.gates([_w2.gate("failed", "Failed executions", "pass", 0, 0, "none")])}
    groups: dict = {}
    for r in runs:
        d = _w2.diagnose(r["error"])
        groups.setdefault((d["signature"], r.get("node") or ""), {"d": d, "runs": []})["runs"].append(r)
    recs, checks = [], []
    for (sig, node), g in groups.items():
        d, rs = g["d"], g["runs"]
        rule = _w2.learned_fix(MODULE, sig)
        recs.append({"id": f"{sig}-{_w2.slug(node, 30)}", "signature": sig, "node": node, "cause": d["cause"], "cure": (rule or {}).get("fix", {}).get("text") or d["cure"], "fix": d["fix"],
                     "runs": len(rs), "last_error": rs[-1]["error"], "executions": [r["id"] for r in rs], "learned": bool(rule)})
        checks.append(_w2.gate(sig, f"{len(rs)} failed execution(s) at “{node or '?'}”", "fail", len(rs), 0, f"{d['cause']} — {(rs[-1]['error'] or '')[:200]}"))
    return {"summary": f"{len(runs)} failed execution(s), {len(recs)} cause(s): " + "; ".join(f"{r['node'] or '?'} — {r['signature'].replace('_', ' ')}" for r in recs) + ". Confirm the diagnosis before anything changes.",
            "records": recs, "counts": {"failed": len(runs), "causes": len(recs)}, "data": _w2.gates(checks), "items": [f"{r['node']}: {r['cause']}" for r in recs][:6]}


DIAG_EDIT = wb.Edit(columns=[wb.Column("node", "Failing node", readonly=True), wb.Column("cause", "Cause", "longtext"), wb.Column("runs", "Failed runs", "number", readonly=True)],
                    add=False, remove=False, label="cause")


def c_fix(ctx: wb.Ctx) -> dict:
    have = ctx.records(ctx.step_id)
    f = _read(ctx, "flow.json", {})
    w = f.get("workflow") or {}
    recs = have or []
    if not have:
        for d in ctx.records("diagnose"):
            if d["fix"] == "change_payload":
                recs.append({"id": f"c-{d['id']}", "node": d["node"], "what": "parameter", "find": "GSTR1_V1", "replace": "GSTR1_V2", "credential": "", "why": d["cure"]})
            elif d["fix"] == "rotate_credential":
                recs.append({"id": f"c-{d['id']}", "node": d["node"], "what": "credential", "find": "", "replace": "", "credential": str(ctx.scope.get("credential") or ""), "why": d["cure"]})
    fixed, applied = _apply_changes(w, recs)
    if recs and not _change_problems(recs, w):
        ctx.output("workflow-fixed.json", json.dumps(fixed, indent=2), label="The changed workflow (JSON)")
    dif = nf.diff(w, fixed) if w else []
    return {"summary": (f"{len(recs)} change(s) on a copy, rules first: " + "; ".join(f"{r['node']}: {r['find']} → {r['replace']}" if r["what"] == "parameter" else f"{r['node']}: credential → {r['credential'] or '(name it)'}"
                                                                                   for r in recs) + ". Nothing changes on n8n until the release is approved.") if recs else
            "No rule knows a change for this: add the change in place (node, what to replace and with what).", "records": recs, "counts": {"changes": len(recs), "applied": applied},
            "data": _w2.table(["Node", "What", "Find", "Replace with", "Credential (by name)", "Why"], [[r["node"], r["what"], r.get("find") or "", r.get("replace") or "", r.get("credential") or "", r.get("why") or ""] for r in recs]),
            "items": [f"{x['node']}: {x['what']} changes" for x in dif][:6]}


def _apply_changes(w: dict, recs: list[dict]) -> tuple[dict, int]:
    out, n = w, 0
    for r in recs:
        if r.get("what") == "credential" and r.get("credential"):
            out, k = nf.change_credential(out, r["node"], r["credential"])
        elif r.get("what") == "parameter" and r.get("find"):
            out, k = nf.change_param(out, r["node"], r["find"], r.get("replace") or "")
        else:
            k = 0
        n += k
    return out, n


def _change_problems(recs: list[dict], w: dict) -> list[str]:
    names = {n["name"]: n for n in w.get("nodes") or []}
    out = []
    for r in recs:
        if r.get("node") not in names:
            out.append(f"{r.get('node')}: not a node of the workflow")
            continue
        if r.get("what") == "parameter" and (not r.get("find") or r["find"] not in json.dumps(names[r["node"]].get("parameters") or {})):
            out.append(f"{r['node']}: “{r.get('find')}” is not in its parameters (nothing would change)")
        if r.get("what") == "credential" and not r.get("credential"):
            out.append(f"{r['node']}: name the renewed credential (its name in n8n, never the secret)")
        if r.get("what") == "credential" and not (names[r["node"]].get("credentials")):
            out.append(f"{r['node']}: has no credential to change")
        if r.get("what") not in ("parameter", "credential"):
            out.append(f"{r['node']}: a change is to a parameter or to a credential")
    return out


def _validate_fix(recs: list[dict], ctx: wb.Ctx) -> list[str]:
    w = (_read(ctx, "flow.json", {}) or {}).get("workflow") or {}
    probs = _change_problems(recs, w) if recs else ["add the change: which node, what to replace and with what"]
    if not probs:
        fixed, _ = _apply_changes(w, recs)
        (ctx.dir / "outputs").mkdir(exist_ok=True)
        (ctx.dir / "outputs" / "workflow-fixed.json").write_text(json.dumps(fixed, indent=2), encoding="utf-8")
    return probs


FIX_EDIT = wb.Edit(columns=[wb.Column("node", "Node", required=True), wb.Column("what", "What changes", "select", options=(("parameter", "A parameter"), ("credential", "The credential"))),
                            wb.Column("find", "Find"), wb.Column("replace", "Replace with"), wb.Column("credential", "Credential (by name)"), wb.Column("why", "Why", readonly=True)],
                   validate=_validate_fix, label="change")


def _fixed(ctx: wb.Ctx) -> dict:
    w = (_read(ctx, "flow.json", {}) or {}).get("workflow") or {}
    fixed, _ = _apply_changes(w, ctx.records("fix"))
    return fixed


def c_prove(ctx: wb.Ctx) -> dict:
    fixed = _fixed(ctx)
    w = (_read(ctx, "flow.json", {}) or {}).get("workflow") or {}
    p = _w2.push_of(ctx.id, ctx.step_id)
    if not p or p["status"] in ("failed", "refused") or p["result"].get("sha") != _w2.sha(fixed) or ctx.comment:
        c = _target(ctx)
        cases = _payloads(ctx)
        _w2.request_push(ctx, c["id"], "test_run", {"workflow": fixed, "payloads": cases, "sha": _w2.sha(fixed)}, f"Test-run the changed “{w.get('name')}” on {c['name']} ({len(cases)} payload(s))",
                         items=[f"Where: {c['name']} (n8n)", f"What: a copy of the changed workflow named “[Relay test] {w.get('name')}”, removed afterwards", "The live workflow does not change"], meta={"sha": _w2.sha(fixed)})
    return _cprove_view(ctx)


def _cprove_view(ctx: wb.Ctx) -> dict:
    fixed = _fixed(ctx)
    w = (_read(ctx, "flow.json", {}) or {}).get("workflow") or {}
    rows = [g for g in nf.check(fixed) if g["name"] not in ("todo",)]
    dif = nf.diff(w, fixed)
    named = {r["node"] for r in ctx.records("fix")}
    stray = [d for d in dif if d["node"] not in named]
    rows.append(_w2.gate("scope", "Only the nodes named in the change differ from the live workflow", "fail" if stray or not dif else "pass", len(dif), len(named),
                         "; ".join(f"{d['node']}: {d['what']}" for d in dif) or "nothing differs"))
    tests, p = _test_rows(ctx, ctx.step_id)
    if tests:
        rows.append(ctx.proof("tests_run", label="Test executions of the changed workflow", results=tests))
    elif p and p["status"] == "awaiting":
        rows.append(_w2.gate("tests", "Test executions of the changed workflow", "skip", detail="waiting for the test-run approval in the Validation queue"))
    bad = [g for g in rows if g["status"] == "fail"]
    return {"summary": f"The change touches {', '.join(sorted({d['node'] for d in dif})) or 'nothing'}; " + (f"{sum(1 for t in tests if t['status'] == 'pass')} of {len(tests)} test execution(s) passed." if tests else "the test run waits for its own approval."),
            "counts": {"differences": len(dif), "tests": len(tests), "fail": len(bad)}, "data": _w2.gates(rows), "records": [{"id": "proof", "tests": len(tests)}],
            "items": [f"{g['label']}: {g['detail']}"[:240] for g in bad][:6]}


_w2.REFRESH["n8n.change.prove"] = _cprove_view


def _validate_cproof(recs: list[dict], ctx: wb.Ctx) -> list[str]:
    probs = _w2.push_problems(ctx.id, ctx.step_id)
    if probs:
        return probs
    tests, _ = _test_rows(ctx, ctx.step_id)
    if any(t["status"] != "pass" for t in tests):
        return ["a test execution of the changed workflow failed: send it back to Fix"]
    return []


CPROOF_EDIT = wb.Edit(columns=[wb.Column("tests", "Test executions", "number", readonly=True)], add=False, remove=False, validate=_validate_cproof, label="proof")


def c_approve(ctx: wb.Ctx) -> dict:
    w = (_read(ctx, "flow.json", {}) or {}).get("workflow") or {}
    ex = sorted({e for d in ctx.records("diagnose") for e in d.get("executions") or []})
    return {"summary": f"Release the change to “{w.get('name')}” and re-run its {len(ex)} failed execution(s).",
            "data": {"items": [{"title": "The change", "detail": "; ".join(f"{r['node']}: {r.get('find') or 'credential'} → {r.get('replace') or r.get('credential')}" for r in ctx.records("fix"))},
                               {"title": "Then", "detail": f"The workflow is updated through n8n's API and {len(ex)} failed execution(s) re-run — one approval for exactly that; the fix is kept as a rule."}]}}


def c_learn(ctx: wb.Ctx) -> dict:
    p = _w2.push_of(ctx.id, ctx.step_id)
    if not p or p["status"] in ("failed", "refused"):
        c = _target(ctx)
        w = (_read(ctx, "flow.json", {}) or {}).get("workflow") or {}
        ex = sorted({e for d in ctx.records("diagnose") for e in d.get("executions") or []})[-10:]
        _w2.request_push(ctx, c["id"], "update_retry", {"workflow_id": w.get("id"), "workflow": _fixed(ctx), "executions": ex},
                         f"Update “{w.get('name')}” on {c['name']} and re-run {len(ex)} failed execution(s)", items=[f"Where: {c['name']} (n8n)", f"Workflow: {w.get('name')}", f"Re-run: {', '.join(ex)}"])
    return _learn_view(ctx)


def _learn_view(ctx: wb.Ctx) -> dict:
    p = _w2.push_of(ctx.id, "learn")
    if p and p["status"] == "written":
        re_ = p["result"].get("reruns") or []
        good = sum(1 for r in re_ if r["status"] == "success")
        if not ctx.get("learned"):
            for d in ctx.records("diagnose"):
                _w2.learn_fix(ctx, d["signature"], d["cause"], {"text": d["cure"], "changes": [{k: r.get(k) for k in ("what", "find", "replace")} for r in ctx.records("fix") if r["node"] == d["node"]]})
            ctx.put("learned", True)
        return {"summary": f"Released: the workflow is updated and {good} of {len(re_)} re-run(s) succeeded. The fix is kept as a rule for the next failure like it.",
                "counts": {"reruns": len(re_), "succeeded": good}, "data": _w2.table(["Re-run of", "New execution", "Status", "Error"], [[r.get("of"), r.get("id") or "", r["status"], r.get("error") or ""] for r in re_])}
    if p and p["status"] == "awaiting":
        return {"summary": "The update and the re-runs wait for their own approval in the Validation queue.", "data": {"href": "#/validate", "label": "Open the Validation queue", "text": p["what"]}}
    return {"summary": f"Not released ({(p or {}).get('status') or 'not asked'}): run this step again.", "data": {"text": str(((p or {}).get("result") or {}).get("error") or "")}}


_w2.REFRESH["n8n.change.learn"] = _learn_view


# ================================================================== Migrate

def m_discover(ctx: wb.Ctx) -> dict:
    kinds = tuple(k for k in npf.IPAAS if k != "n8n_api")
    autos, runs, rows = _estate(ctx, kinds)
    autos = [a for a in autos if a["platform"] != "n8n_api"]
    if not autos:
        raise wb.StepFailed("No source flows: pick the platform's connection (Power Automate, Zapier, Make, Workato, Boomi, MuleSoft) or upload its exports.")
    _save(ctx, "estate.json", {"autos": autos, "runs": runs})
    for a in autos:
        _w2.lineage_auto(ctx, a)
    return {"summary": f"{len(autos)} flow(s) read on {len({a.get('platform_label') for a in autos})} platform(s), with {len(runs)} run(s) of history — read-only.",
            "counts": {"flows": len(autos), "runs": len(runs)}, "data": _w2.table(["Flow", "Platform", "Trigger", "Steps", "On", "Runs", "Failed"],
                                                                                    [[r["flow"], r["platform"], r["trigger"], r["steps"], r["active"], r["runs"], r["failed"]] for r in _inv_rows(autos, runs)])}


def m_decide(ctx: wb.Ctx) -> dict:
    est = _read(ctx, "estate.json", {})
    autos, runs = est.get("autos") or [], est.get("runs") or []
    have = {r["id"]: r for r in ctx.records(ctx.step_id)}
    fs = _w2.findings(autos, runs)
    seen: dict = {}
    recs = []
    for a in autos:
        mine = [f for f in fs if f["auto"] == a["id"]]
        shape = json.dumps([(s["kind"], s.get("system")) for s in a["steps"]])
        if any(f["kind"] == "retire" for f in mine):
            dec, why = "retire", next(f["what"] for f in mine if f["kind"] == "retire")
        elif shape in seen and len(a["steps"]) > 1:
            dec, why = "merge", f"does the same steps as “{seen[shape]}”"
        else:
            dec, why = "move", f"{len(a['steps'])} step(s) to n8n, converted by rules"
            seen.setdefault(shape, a["name"])
        fix = ""
        bad = next((f for f in mine if f["kind"] == "failing"), None)
        if dec == "move" and bad and bad.get("signature") == "payload_schema":
            fix, why = "GSTR1_V1=GSTR1_V2", why + f"; moves with its fix — {bad['what'][:120]}"
        elif dec == "move" and bad:
            why += f"; it fails today ({bad['what'][:100]}) — the cause moves with it unless fixed"
        if any(f["kind"] == "secret" for f in mine):
            why += "; its credential in clear becomes a credential by name in n8n"
        rid = f"{a['platform']}:{a['id']}"
        recs.append({"id": rid, "auto": a["id"], "flow": a["name"], "platform": a.get("platform_label") or a["platform"], "decision": (have.get(rid) or {}).get("decision") or dec,
                     "why": (have.get(rid) or {}).get("why") or why, "fix": (have.get(rid) or {}).get("fix", fix), "runs": _w2.history(runs, a["id"])["runs"]})
    n = {k: sum(1 for r in recs if r["decision"] == k) for k in ("move", "merge", "retire", "keep")}
    return {"summary": f"Rules suggest: {n['move']} to move, {n['merge']} to merge, {n['retire']} to retire" + (f", {n['keep']} kept where they are" if n["keep"] else "") + " — change any decision, with the reason.",
            "records": recs, "counts": n, "data": _w2.table(["Flow", "Platform", "Decision", "Why", "Fix as it moves"], [[r["flow"], r["platform"], r["decision"], r["why"], r["fix"]] for r in recs])}


def _validate_decide(recs: list[dict], ctx: wb.Ctx) -> list[str]:
    out = []
    for r in recs:
        if r.get("fix") and "=" not in r["fix"]:
            out.append(f"{r['flow']}: a fix is written old=new (for example GSTR1_V1=GSTR1_V2)")
        if r.get("decision") in ("merge", "retire", "keep") and not str(r.get("why") or "").strip():
            out.append(f"{r['flow']}: say why")
    if not any(r.get("decision") == "move" for r in recs):
        out.append("nothing is moved: decide at least one flow to move to n8n")
    return out


DECIDE_EDIT = wb.Edit(columns=[wb.Column("decision", "Decision", "select", options=(("move", "Move to n8n"), ("merge", "Merge"), ("retire", "Retire"), ("keep", "Keep where it is"))),
                               wb.Column("why", "Why", "longtext"), wb.Column("fix", "Fix as it moves (old=new)"), wb.Column("flow", "Flow", readonly=True), wb.Column("platform", "Platform", readonly=True)],
                      add=False, remove=False, validate=_validate_decide, label="flow")


def _moving(ctx: wb.Ctx) -> list[tuple[dict, dict]]:
    est = _read(ctx, "estate.json", {})
    by = {a["id"]: a for a in est.get("autos") or []}
    return [(by[r["auto"]], r) for r in ctx.records("decide") if r.get("decision") == "move" and r["auto"] in by]


def m_convert(ctx: wb.Ctx) -> dict:
    rows, out = [], {}
    for a, r in _moving(ctx):
        fixes = dict([r["fix"].split("=", 1)]) if r.get("fix") else {}
        wf, design = nf.from_auto(a, fixes=fixes)
        probs = nf.problems(wf, design)
        out[a["id"]] = {"workflow": wf, "design": design, "source": a, "fixes": fixes}
        ctx.output(f"n8n-{_w2.slug(a['name'])}.json", json.dumps(wf, indent=2), label=f"n8n workflow: {a['name']}")
        rows.append({"id": a["id"], "flow": a["name"], "from": a.get("platform_label") or a["platform"], "nodes": len(wf["nodes"]), "mapped": f"{len(a['steps'])} of {len(a['steps'])}",
                     "fix": ", ".join(f"{k} → {v}" for k, v in fixes.items()), "rules": "pass" if not probs else f"{len(probs)} to fix", "problems": "; ".join(probs)[:300]})
    if not rows:
        raise wb.StepFailed("Nothing is decided to move.")
    _save(ctx, "converted.json", out)
    ok = sum(1 for r in rows if r["rules"] == "pass")
    return {"summary": f"{len(rows)} flow(s) converted to n8n by rules; {ok} pass every rule" + (f", {len(rows) - ok} need a person (see the problems)" if ok < len(rows) else "") + ".",
            "counts": {"converted": len(rows), "pass": ok}, "records": rows,
            "data": _w2.table(["Flow", "From", "Nodes", "Steps mapped", "Fix applied", "Rules"], [[r["flow"], r["from"], r["nodes"], r["mapped"], r["fix"], r["rules"] + (f" — {r['problems']}" if r["problems"] else "")] for r in rows])}


def m_prove(ctx: wb.Ctx) -> dict:
    conv = _read(ctx, "converted.json", {})
    if not conv:
        raise wb.StepFailed("Nothing was converted.")
    tgt = _target(ctx)
    cases = _payloads(ctx)
    pn = _w2.push_of(ctx.id, ctx.step_id)
    if not pn or pn["status"] in ("failed", "refused") or ctx.comment:
        flows = [{"auto": k, "workflow": v["workflow"]} for k, v in conv.items()]
        _w2.request_push(ctx, tgt["id"], "test_runs", {"flows": flows, "payloads": cases}, f"Test-run {len(flows)} converted flow(s) on {tgt['name']} with {len(cases)} payload(s) each",
                         items=[f"Where: {tgt['name']} (n8n)", f"What: a copy of each converted flow, triggered by a webhook of its own, removed afterwards", f"Flows: {', '.join(v['workflow']['name'] for v in conv.values())}"])
    old = {}
    for k, v in conv.items():
        a = v["source"]
        if a["platform"] in npf.RUNNABLE and a.get("connection"):
            old.setdefault(a["connection"], []).append(k)
    for cid, keys in old.items():
        if not any(p["connection"] == cid and p["step"] == ctx.step_id and p["status"] in ("awaiting", "written") and not ctx.comment for p in _w2.pushes(ctx.id, ctx.step_id)):
            c = ctx.connection(cid)
            if not connectors.may_write(c):
                continue
            _w2.request_push(ctx, cid, "test_runs", {"flows": [{"auto": k, "id_key": npf.RUNNABLE[c["kind"]], "id": conv[k]["source"]["id"]} for k in keys], "payloads": cases},
                             f"Run {len(keys)} old flow(s) on {c['name']} with the same {len(cases)} payload(s)", items=[f"Where: {c['name']}", "What: the old flows run as they are, on the same payloads", "Nothing is changed"])
    return _mprove_view(ctx)


def _mprove_view(ctx: wb.Ctx) -> dict:
    conv = _read(ctx, "converted.json", {})
    est = _read(ctx, "estate.json", {})
    runs = est.get("runs") or []
    decided = {r["auto"]: r for r in ctx.records("decide")}
    res_new, res_old = {}, {}
    for p in _w2.pushes(ctx.id, ctx.step_id):
        if p["status"] != "written":
            continue
        for x in p["result"].get("flows") or []:
            (res_new if p["target"] == "n8n_api" else res_old)[x["auto"]] = x["runs"]
    rows, pairs = [], []
    for k, v in conv.items():
        for g in nf.check(v["workflow"], v["design"]):
            if g["status"] == "fail":
                rows.append({**g, "name": f"{k}-{g['name']}", "label": f"{v['source']['name']}: {g['label']}"})
        news = res_new.get(k)
        olds = res_old.get(k)
        a = v["source"]
        if olds is None and news is not None:                      # the source cannot run on demand: its own history speaks for it
            h = _w2.history(runs, a["id"])
            olds = [{"case": x.get("case"), "status": "failed" if h["failing_days"] else "success", "error": h["last_error"] if h["failing_days"] else None, "from": "history"} for x in news]
        for i, n in enumerate(news or []):
            o = (olds or [{}] * len(news))[i] if olds else {}
            why = ""
            if o.get("status") != n.get("status") and v["fixes"]:
                why = f"decided: the old flow fails ({str(o.get('error') or '')[:100]}); the moved one carries the fix {', '.join(f'{x} → {y}' for x, y in v['fixes'].items())}"
            pairs.append({"case": f"{a['name']} · {n.get('case')}", "old": {"status": o.get("status"), "detail": (o.get("error") or o.get("from") or "")[:160]},
                          "new": {"status": n.get("status"), "detail": (n.get("error") or "")[:160]}, "expected": why})
    pend = [p for p in _w2.pushes(ctx.id, ctx.step_id) if p["status"] == "awaiting"]
    if pairs:
        rows.append(ctx.proof("side_by_side", label="Old and new side by side on the same payloads", pairs=pairs))
    if pend:
        rows.append(_w2.gate("waiting", "Runs waiting for their own approval", "skip", len(pend), 0, "; ".join(p["what"] for p in pend)))
    refs = [s["label"][:60] for v in conv.values() for s in v["source"]["steps"] if s["kind"] != "trigger"]
    known = [n["name"] for v in conv.values() for n in v["workflow"]["nodes"]]
    rows.append(ctx.proof("references_real", label="Every step of the old flows has its node in the new ones", refs=refs, known=known))
    _ = decided
    bad = [g for g in rows if g["status"] == "fail"]
    return {"summary": f"{len(conv)} flow(s): " + (f"{len(pairs)} payload run(s) compared side by side" if pairs else "the side-by-side runs wait for their approvals") + (f"; {len(bad)} check(s) fail." if bad else "."),
            "counts": {"flows": len(conv), "compared": len(pairs), "fail": len(bad)}, "data": _w2.gates(rows), "records": [{"id": "proof", "compared": len(pairs)}],
            "items": [f"{g['label']}: {g['detail']}"[:240] for g in bad][:6]}


_w2.REFRESH["n8n.migrate.prove"] = _mprove_view


def _validate_mproof(recs: list[dict], ctx: wb.Ctx) -> list[str]:
    out = []
    for p in _w2.pushes(ctx.id, ctx.step_id):
        if p["status"] == "awaiting":
            out.append(f"waiting: accept “{p['what']}” in the Validation queue first")
        elif p["status"] in ("failed", "refused"):
            out.append(f"“{p['what']}” {p['status']}: run the step again")
    return out


MPROOF_EDIT = wb.Edit(columns=[wb.Column("compared", "Compared", "number", readonly=True)], add=False, remove=False, validate=_validate_mproof, label="proof")


def m_handover(ctx: wb.Ctx) -> dict:
    conv = _read(ctx, "converted.json", {})
    retire = [r["flow"] for r in ctx.records("decide") if r["decision"] == "retire"]
    return {"summary": f"Hand over {len(conv)} converted flow(s); {len(retire)} retired. The evidence pack holds every conversion and the side-by-side runs.",
            "data": {"items": [{"title": "Moving to n8n", "detail": ", ".join(v["workflow"]["name"] for v in conv.values())}, {"title": "Retired", "detail": ", ".join(retire) or "none"},
                               {"title": "Then", "detail": "The flows are deployed to n8n after their own approval and watched; switch the old flows off on their platforms once the new ones run."}]}}


def m_run(ctx: wb.Ctx) -> dict:
    conv = _read(ctx, "converted.json", {})
    c = _target(ctx)
    p = _w2.push_of(ctx.id, ctx.step_id)
    if not p or p["status"] in ("failed", "refused"):
        _w2.request_push(ctx, c["id"], "deploy_many", {"flows": [{"auto": k, "workflow": v["workflow"]} for k, v in conv.items()], "activate": ctx.scope.get("activate", True) not in (False, "false")},
                         f"Deploy {len(conv)} converted flow(s) to {c['name']}", items=[f"Where: {c['name']} (n8n)", "What: " + ", ".join(v["workflow"]["name"] for v in conv.values())])
    return _mrun_view(ctx)


def _mrun_view(ctx: wb.Ctx) -> dict:
    p = _w2.push_of(ctx.id, "run")
    if p and p["status"] == "written":
        ids = [x["workflow_id"] for x in p["result"].get("flows") or []]
        if not ctx.get("run_item") and ids:
            c = _target(ctx, write=False)
            conv = _read(ctx, "converted.json", {})
            from .. import lineage
            for x in p["result"].get("flows") or []:
                v = conv.get(x["auto"]) or {}
                new = ctx.lineage_node("flow", SYSTEM, v.get("workflow", {}).get("name") or x["workflow_id"], label=f"{v.get('workflow', {}).get('name')} (n8n)", properties={"workflow_id": x["workflow_id"]})
                src = v.get("source") or {}
                old = lineage.node_id("flow", src.get("platform_label") or src.get("platform") or "", src.get("name") or "")
                if db.one("SELECT 1 FROM lineage_nodes WHERE id = ?", (old,)):
                    ctx.lineage_edge(old, new, "relates", {"migrated_to": True})
            it = wb.create(MODULE, "run", f"Run: {ctx.title}"[:160], who=ctx.owner, brief=f"Watch the {len(ids)} flow(s) migrated by {ctx.id}.", connections=[c["id"]],
                           scope={"workflows": ", ".join(ids), "schedule": {"every": "hour", "tz": "UTC"}}, approver=ctx.st.get("approver"),
                           visibility=(db.project(ctx.id) or {}).get("visibility") or "private", team_id=(db.project(ctx.id) or {}).get("team_id"), parent=ctx.id)
            ctx.put("run_item", it["id"])
        return {"summary": f"{len(ids)} flow(s) deployed to n8n; a Run item watches them.", "counts": {"deployed": len(ids)},
                "data": {"href": f"#/m/{MODULE}/i/{ctx.get('run_item')}" if ctx.get("run_item") else f"#/m/{MODULE}/run", "label": "Open the Run item", "text": ", ".join(ids)}}
    if p and p["status"] == "awaiting":
        return {"summary": "The deploy waits for its own approval in the Validation queue.", "data": {"href": "#/validate", "label": "Open the Validation queue", "text": p["what"]}}
    return {"summary": f"Not deployed ({(p or {}).get('status') or 'not asked'}): run this step again.", "data": {"text": str(((p or {}).get("result") or {}).get("error") or "")}}


_w2.REFRESH["n8n.migrate.run"] = _mrun_view


# ================================================================== Run & support

def r_watch(ctx: wb.Ctx) -> dict:
    c = _target(ctx, write=False)
    a = npf.N8nApi()
    want = {x.strip() for x in str(ctx.scope.get("workflows") or "").split(",") if x.strip()}
    wfs = {w["id"]: w for w in a.workflows(c) if not want or w["id"] in want or w["name"] in want}
    since = ctx.get("since") or 0
    runs = [r for r in a.runs(c, []) if r["target"] in wfs]
    new = [r for r in runs if (r["start"] or 0) > since]
    ctx.put("since", max([r["start"] or 0 for r in runs] + [since]))
    fails = [r for r in new if r["status"] == "failed"]
    ctx.put("failures", [{**r, "workflow": wfs[r["target"]]["name"]} for r in fails])
    checks = []
    for wid, w in wfs.items():
        mine = [r for r in new if r["target"] == wid]
        bad = [r for r in mine if r["status"] == "failed"]
        checks.append(_w2.gate(f"wf-{wid}", w["name"], "fail" if bad else "pass", f"{len(mine) - len(bad)} of {len(mine)} succeeded", "every execution succeeds",
                               (bad[-1]["error"] or "")[:200] if bad else ("switched on" if w.get("active") else "switched off")))
    return {"summary": f"{len(new)} new execution(s) on {len(wfs)} workflow(s) since the last round: {len(fails)} failed.", "counts": {"workflows": len(wfs), "executions": len(new), "failed": len(fails)},
            "data": _w2.gates(checks)}


def r_alert(ctx: wb.Ctx) -> dict:
    groups: dict = {}
    for r in ctx.get("failures") or []:
        d = _w2.diagnose(r["error"])
        g = groups.setdefault((r["target"], d["signature"]), {"workflow": r["workflow"], "target": r["target"], "d": d, "runs": []})
        g["runs"].append(r)
    brks = [{"id": f"b-{_w2.slug(k[0], 20)}-{k[1]}", "workflow": g["workflow"], "target": g["target"], "signature": k[1], "cause": g["d"]["cause"], "cure": g["d"]["cure"], "runs": len(g["runs"]),
             "node": g["runs"][-1].get("node") or "", "error": (g["runs"][-1].get("error") or "")[:400], "executions": [r["id"] for r in g["runs"]],
             "route": {"heal": "heal", "change": "heal", "rerun": "rerun", "person": "expected"}.get(g["d"]["route"], "heal"), "note": ""} for k, g in groups.items()]
    ctx.put("breaks", brks)
    if not brks:
        return {"summary": "Every execution succeeded: nothing to alert.", "next": "report", "counts": {"breaks": 0}}
    return {"summary": f"{sum(b['runs'] for b in brks)} failure(s) grouped into {len(brks)} cause(s), each with its likely cause.", "counts": {"breaks": len(brks)},
            "items": [f"{b['workflow']}: {b['cause']}"[:240] for b in brks[:6]],
            "data": _w2.table(["Workflow", "Failed node", "Failures", "Likely cause", "Last error"], [[b["workflow"], b["node"], b["runs"], b["cause"], b["error"][:200]] for b in brks])}


def r_fix(ctx: wb.Ctx) -> dict:
    have = {r["id"]: r for r in ctx.records(ctx.step_id)}
    recs = [{**b, **({k: have[b["id"]][k] for k in ("route", "note") if k in have[b["id"]]} if b["id"] in have else {})} for b in ctx.get("breaks") or []]
    return {"summary": f"{len(recs)} cause(s): choose who fixes each — Self-healing, a Service desk ticket, a re-run, or expected. Nothing goes out until you confirm.", "records": recs,
            "counts": {r: sum(1 for x in recs if x["route"] == r) for r in ("heal", "ticket", "rerun", "expected")},
            "data": _w2.table(["Workflow", "Cause", "Failures", "Proposed route"], [[r["workflow"], r["cause"], r["runs"], r["route"]] for r in recs])}


RFIX_EDIT = wb.Edit(columns=[wb.Column("route", "Route", "select", options=(("heal", "Self-healing"), ("ticket", "Raise a ticket"), ("rerun", "Re-run the failed executions"), ("expected", "Expected — no action"), ("ignore", "Ignore this time"))),
                             wb.Column("note", "Note for whoever fixes it", "longtext"), wb.Column("workflow", "Workflow", readonly=True), wb.Column("cause", "Cause", readonly=True)],
                    add=False, remove=False, label="cause")


def r_approve(ctx: wb.Ctx) -> dict:
    rows, out = [], []
    c = None
    for b in ctx.records("fix"):
        title = f"{b['workflow']}: {b['signature'].replace('_', ' ')} at {b['node'] or 'a node'}"
        body = f"{b['error']}\n\nLikely cause: {b['cause']}\nWhat cures it: {b['cure']}\n{('Note: ' + b['note']) if b.get('note') else ''}\nWork item: {wb.route_of(ctx.st)}"
        if b["route"] == "heal":
            h = ctx.heal(title, body, place=f"{b['workflow']} (n8n)", signature=f"n8n:{b['signature']}", subject={"workflow": b["target"], "executions": b["executions"][-5:]})
        elif b["route"] == "ticket":
            h = _w2.desk_ticket(ctx, str(ctx.scope.get("desk") or ""), title, body, priority="P2" if b["signature"] in ("credential_expired", "payload_schema") else "P3", ref=b["id"])
        elif b["route"] == "rerun":
            c = c or _target(ctx)
            cp = _w2.request_push(ctx, c["id"], "retry", {"executions": b["executions"][-10:]}, f"Re-run {len(b['executions'][-10:])} failed execution(s) of {b['workflow']}",
                                  items=[f"Where: {c['name']} (n8n)", f"Executions: {', '.join(b['executions'][-10:])}"])
            h = {"kind": "write", "label": title, "status": "awaiting approval", "checkpoint": cp["id"]}
        else:
            h = {"kind": b["route"], "label": title, "status": "expected — recorded" if b["route"] == "expected" else "ignored this time"}
        out.append(h)
        rows.append([b["workflow"], b["cause"], {"heal": "Self-healing", "ticket": "Ticket", "rerun": "Re-run", "expected": "Expected", "ignore": "Ignored"}[b["route"]], h.get("status"),
                     h.get("case") or h.get("checkpoint") or h.get("output") or ""])
    return {"summary": f"{sum(1 for h in out if h['kind'] == 'heal')} to Self-healing, {sum(1 for h in out if h['kind'] == 'ticket')} ticket(s), {sum(1 for h in out if h['kind'] == 'write')} re-run(s) awaiting approval — as you approved.",
            "data": _w2.table(["Workflow", "Cause", "Route", "Status", "Reference"], rows), "counts": {"hand-offs": len(out)}}


def r_report(ctx: wb.Ctx) -> dict:
    w = ctx.result("watch") or {}
    cn = w.get("counts") or {}
    hist = [[time.strftime("%d %b %H:%M", time.gmtime(r["ended"])), (next((s for s in r["steps"] if s["id"] == "watch"), {}).get("counts") or {}).get("executions"),
             (next((s for s in r["steps"] if s["id"] == "watch"), {}).get("counts") or {}).get("failed")] for r in (ctx.st.get("rounds") or [])[-11:]]
    hist.append([time.strftime("%d %b %H:%M", time.gmtime()), cn.get("executions"), cn.get("failed")])
    ctx.output(f"report-{time.strftime('%Y%m%d-%H%M', time.gmtime())}.md", f"# Run report: {ctx.title}\n\n- Executions: {cn.get('executions')}\n- Failed: {cn.get('failed')}\n"
               + "".join(f"- {b['workflow']}: {b['cause']} → {b['route']}\n" for b in ctx.records("fix")), label="Run report (Markdown)")
    return {"summary": f"{cn.get('executions') or 0} execution(s), {cn.get('failed') or 0} failed this round.", "counts": {"executions": cn.get("executions") or 0, "failed": cn.get("failed") or 0},
            "data": _w2.table(["Round", "Executions", "Failed"], hist)}


def _cards(u: dict) -> list[dict]:
    rows = []
    for p in _w2.visible_items(u, db.q("SELECT * FROM w2_pushes WHERE module = ? AND status = 'written' AND step = 'run' ORDER BY done DESC LIMIT 50", (MODULE,))):
        res = _w2.j(p["result"], {})
        ids = [res.get("workflow_id")] if res.get("workflow_id") else [x.get("workflow_id") for x in res.get("flows") or []]
        it = db.one("SELECT title FROM wb_items WHERE id = ?", (p["item"],)) or {}
        rows.append([it.get("title") or p["item"], ", ".join(i for i in ids if i), p["what"][:120], _w2.when(p["done"]), f"#/m/{MODULE}/i/{p['item']}"])
    return [{"title": "Flows Relay deployed", "columns": ["Work item", "n8n workflow", "What", "When", "Open"], "rows": rows,
             "empty": "Nothing deployed yet: a Develop or Migrate item's last step deploys after its own approval."}]


GUIDE = """# Workflows & iPaaS — the work item

This folder is one work item of Relay's Workflows & iPaaS module (n8n first; Power Automate, Zapier, Make, Workato,
Boomi and MuleSoft are read and migrated). Relay's rules do everything they can: the agent is asked only for what needs
judgement — a design from plain words, the parameters of an n8n workflow from a confirmed design.

- `request.md`: the brief and every decision so far.
- `node_types.json`: the n8n node types Relay writes and tests.
- `design.json`: the nodes a person confirmed — name, type, system, credential (a NAME), next, what it does.
- `skeleton.json`: the workflow Relay's rules wrote from the design; `TODO` marks what needs judgement.
- `workflow.json`: what you write when asked — n8n workflow JSON (name, nodes, connections, settings). n8n's own rules
  apply: one trigger, every connection between nodes that exist, a decision with a condition. Relay's apply on top:
  credentials by name only (never a secret), nothing invented (only the confirmed nodes and links), no TODO left.
- `data/`: the person's uploads; `sources/`: what Relay read (flows, run history); `outputs/`: the files kept.
"""

wb.register(wb.Pack(
    module=MODULE, guide=GUIDE,
    lineage="each flow as a node of its platform with the systems its steps call; a deployed workflow linked to the process map it automates; a migrated flow related to the one it replaces",
    platforms=PLATFORMS, schemas={"design": DESIGN_EDIT.columns, "finding": FIND_EDIT.columns, "change": FIX_EDIT.columns, "decision": DECIDE_EDIT.columns, "route": RFIX_EDIT.columns},
    cards=_cards,
    work={
        "assess": wb.Work(title="See every flow on your iPaaS platforms, what fails and why, and what to do next", steps={
            "Connect": wb.Step(kind="platform", run=a_connect, agent="Connector", text="Each connection signs in the vendor's way and reads flows and run history — read-only; exports are read the same"),
            "Inventory": wb.Step(kind="platform", run=a_inventory, agent="Scanner", edit=INV_EDIT, text="Every flow in the tool's own terms: its trigger, steps, runs and failures — you untick what is out of scope"),
            "Health": wb.Step(kind="proof", run=a_health, view="gates", agent="Checker", text="Rules, no AI: failing and flaky flows with their cause, secrets kept in clear, switched-off flows to retire, screen steps where an API exists"),
            "Findings": wb.Step(kind="person", run=a_findings, edit=FIND_EDIT, text="Every finding with what to do — you keep or ignore each"),
            "Estimate": wb.Step(kind="deterministic", run=a_estimate, view="plan", agent="Estimator", text="Waves: fix and secure, move to n8n, retire — the hours from stated assumptions, the cost at your hourly rate")}),
        "develop": wb.Work(title="A new n8n workflow from plain words or a process map — tested, then deployed after approval", needs_source=False, platforms=("n8n",), steps={
            "Describe": wb.Step(kind="deterministic", run=d_describe, agent="Reader", text="Your description, a published process map (Business process documents) or a BPMN upload is read"),
            "Design": wb.Step(kind="deterministic", run=d_design, agent="Flow designer", edit=DESIGN_EDIT, confirm="the workflow's nodes, their links and every credential by name",
                              text="The nodes are drawn by rules from the map — the trigger, an API call per system step, the decisions' ways; from plain words Relay drafts them on request — you correct them in place",
                              actions={"draft": wb.Action(label="Ask Relay to draft the design", kind="agent", prompt=_design_prompt, check=_design_check, after=_design_after, agent="Flow designer",
                                                          help="From your description: nodes, the trigger and credentials by name; you check it before confirming.")}),
            "Build": wb.Step(kind="agent", prompt=_build_prompt, check=_build_check, after=_build_after, agent="Flow builder", turns=40,
                             text="The agent writes the n8n workflow JSON from the confirmed design; Relay's rules check it strictly — the format n8n accepts, credentials by name, nothing invented"),
            "Prove": wb.Step(kind="proof", run=d_prove, view="gates", agent="Flow tester", edit=PROOF_EDIT, back_to="build",
                             text="Every rule, then test executions with your sample payloads on a copy in n8n — after their own approval; the copy is removed afterwards"),
            "Deploy": wb.Step(kind="person", run=d_deploy, view="plan", approver=True, text="The named approver confirms what goes live, where, and with which credentials"),
            "Run": wb.Step(kind="platform", run=d_run, view="link", agent="Deployer", text="The deploy goes through n8n's API after its own approval; a Run item then watches the executions")},
            fields=[wb.Field("process", "Start from a process map", "select", options=process_options, help="A published process from Business process documents — or describe it in plain words, or upload a .bpmn"),
                    wb.Field("payloads", "Sample payloads for the test runs", "longtext", help='JSON — one object or a list, e.g. [{"invoice": "INV-1"}]. Or upload payloads.json.'),
                    wb.Field("activate", "Switch it on when deployed", "bool", default=True)]),
        "change": wb.Work(title="Fix a failing n8n workflow from its run history, tested before it is released", needs_source=False, platforms=("n8n",), steps={
            "Request": wb.Step(kind="platform", run=c_request, agent="Run reader", text="The workflow and its executions are read — the failed ones with their error and the node that failed"),
            "Diagnose": wb.Step(kind="deterministic", run=c_diagnose, view="gates", agent="Diagnoser", edit=DIAG_EDIT, text="Each failure's own words name its cause, rules first (a schema the receiving system no longer accepts, an expired credential, a changed screen, a timeout)"),
            "Fix": wb.Step(kind="deterministic", run=c_fix, agent="Fixer", edit=FIX_EDIT, text="The change on a copy — the parameter replaced in the failing node, or the credential pointed at its renewed name — corrected in place"),
            "Prove": wb.Step(kind="proof", run=c_prove, view="gates", agent="Flow tester", edit=CPROOF_EDIT, back_to="fix", text="The changed workflow passes the rules, differs only where the change says, and runs on a test copy after its own approval"),
            "Approve": wb.Step(kind="person", run=c_approve, view="plan", approver=True, text="The named approver releases the change"),
            "Learn": wb.Step(kind="platform", run=c_learn, agent="Deployer", text="The workflow is updated and its failed executions re-run (one approval for exactly that); the fix is kept as a rule")},
            fields=[wb.Field("workflow", "Workflow to fix", "text", required=True, help="Its name or id on the n8n connection"),
                    wb.Field("credential", "Renewed credential's name (for an expired sign-in)", "text"), wb.Field("payloads", "Sample payloads for the test run", "longtext")]),
        "migrate": wb.Work(title="Move flows from Power Automate, Zapier, Make, Workato, Boomi or MuleSoft to n8n — proven side by side", platforms=("n8n", *SOURCES), steps={
            "Discover": wb.Step(kind="platform", run=m_discover, agent="Scanner", text="The source platform's flows and their run history, read-only, into one neutral model"),
            "Decide": wb.Step(kind="deterministic", run=m_decide, agent="Decider", edit=DECIDE_EDIT, text="Keep, merge, retire or move — by rules, with the reason; a flow that fails today moves with its fix"),
            "Convert": wb.Step(kind="deterministic", run=m_convert, agent="Converter", text="Each flow becomes n8n workflow JSON by rules — every step a node, credentials by name, the decided fix applied"),
            "Prove": wb.Step(kind="proof", run=m_prove, view="gates", agent="Flow tester", edit=MPROOF_EDIT, back_to="convert", text="The same payloads on the old flow and on a test copy in n8n — each side its own approval — compared run by run"),
            "Hand over": wb.Step(kind="person", run=m_handover, view="plan", approver=True, text="The owner signs off on the evidence pack"),
            "Run": wb.Step(kind="platform", run=m_run, view="link", agent="Deployer", text="The converted flows are deployed to n8n after their own approval and a Run item watches them")},
            fields=[wb.Field("payloads", "Sample payloads for the side-by-side runs", "longtext", help="JSON — the same payloads go to the old and the new flow")]),
        "run": wb.Work(title="Watch n8n's executions; failures go to Self-healing or the service desk after a person decides", needs_source=False, platforms=("n8n",), steps={
            "Watch": wb.Step(kind="platform", run=r_watch, view="gates", agent="Watcher", text="The workflows' executions since the last round, read-only"),
            "Alert": wb.Step(kind="deterministic", run=r_alert, agent="Triage", text="Failures grouped by workflow and cause, each with its likely cause — not one alert per failure"),
            "Fix": wb.Step(kind="deterministic", run=r_fix, agent="Triage", edit=RFIX_EDIT, text="Relay proposes who fixes each — Self-healing, a ticket, a re-run — and you confirm or change it"),
            "Approve": wb.Step(kind="platform", run=r_approve, agent="Dispatcher", text="The approved hand-offs go out: a Self-healing case, a Service desk ticket (created after its own approval) or a re-run (its own approval)"),
            "Report": wb.Step(kind="deterministic", run=r_report, agent="Reporter", confirm_if=lambda ctx, out: bool(ctx.get("breaks")), text="A run report against the last rounds; you confirm it when something failed")},
            fields=[wb.Field("workflows", "Workflows to watch", "text", help="Ids or names, separated by commas — blank: all of them"),
                    wb.Field("desk", "Service desk for tickets", "select", options=_w2.desk_options), wb.Field("schedule", "Watch it", "cadence", default={"every": "hour", "tz": "UTC"})]),
    }))
