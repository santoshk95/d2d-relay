"""Business process documents (registry id `processdocs`) — interviews, a screen recording or system logs in; a BPMN 2.0
map that opens in bpmn.io-style tools and a step-by-step SOP out, corrected by the process owner before anything
proceeds, published, kept current; and a migrate mode for Visio, Word and slide-based documents.

Develop  Capture → Map → Correct → Publish → Automate → Keep current. Capture reads the interviews and transcripts into
         passages, notes the recordings for the agent (frames through ffmpeg in the agent image) and mines any event log
         (rules first: the activities, their frequent order and decisions). Map is the agent's process.yaml — steps,
         lanes, decisions, screens, fields and rules, each citing its passage or the recording's moment — checked
         strictly (one start, an end, every link real, decisions labelled, every frequent logged activity on the map);
         the BPMN 2.0 XML with its diagram is built from it and validated. The person corrects the map in place (the
         graph rules refuse a broken one), then the SOP next to where each line came from; Publish keeps the version
         (BPMN + Word SOP in the tenant's template); Automate files it to Confluence after its own approval and proposes
         the steps worth automating (Workflows, RPA, AI SDLC); Keep current links the process to its systems and roles
         in the lineage graph and, on a schedule, flags the document when one of them changes.
Assess   Connect → Inventory → Health → Findings → Estimate over existing BPMN, Visio, Word, PDF and slide documents.
Change   Request → Diagnose → Fix → Prove → Approve → Learn on a published process (a dry run against a new log).
Migrate  Collect → Convert → Check → Publish: Visio and BPMN exports converted by rules, Word and slides by the agent
         when asked; checked against how the work is really done (conformance with an event log).
Published processes are kept in `processdocs_processes` / `processdocs_versions`; RACI & operating model reads them.
"""
from __future__ import annotations

import json
import re
import secrets as _secrets
import time
from pathlib import Path

from .. import auth, connectors, db, lineage
from .. import workbench as wb
from . import _w4
from . import processdocs_bpmn as bp
from . import processdocs_publish as pub

MODULE = "processdocs"
SYSTEM = "Relay process documents"
UPLOADS = (".docx", ".pdf", ".pptx", ".txt", ".md", ".vtt", ".srt", ".html", ".mp4", ".webm", ".mov", ".png", ".jpg", ".jpeg", ".csv", ".tsv", ".xlsx", ".xes", ".log",
           ".vsdx", ".bpmn")
STEP_TYPES = (("start", "Start"), ("task", "Task"), ("user", "Task by a person in a system"), ("manual", "Manual task"), ("service", "System or agent task"),
              ("gateway", "Decision"), ("end", "End"))
LANE_KINDS = ("person", "agent", "system")

db.register_schema("""
CREATE TABLE IF NOT EXISTS processdocs_processes (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, item TEXT, version INTEGER NOT NULL DEFAULT 1, map TEXT NOT NULL, systems TEXT NOT NULL DEFAULT '[]', owner_id TEXT,
  published_by TEXT, published REAL, status TEXT NOT NULL DEFAULT 'published', flagged TEXT, created REAL NOT NULL, updated REAL NOT NULL);
CREATE TABLE IF NOT EXISTS processdocs_versions (
  process_id TEXT NOT NULL, version INTEGER NOT NULL, item TEXT, map TEXT NOT NULL, bpmn TEXT NOT NULL, published_by TEXT, published REAL NOT NULL, note TEXT,
  PRIMARY KEY (process_id, version));
""")

FILES = wb.FilesPlatform()
FILES.label = "Interviews, recordings, system logs and process exports"
FILES.uploads = UPLOADS
FILES.reads = ("interviews and transcripts (Word, PDF, .vtt), screen recordings (the agent reads their frames), system or event logs (CSV, Excel, XES) and "
               "process exports (BPMN 2.0 from Signavio, ARIS, Bizagi or Lucidchart; Visio .vsdx) — a copy in this work item's folder")
FILES.simulator = "synthetic fixtures in tests/mocklab/fixtures/processdocs/ (interview, recording + transcript, event log, Visio, BPMN, Word SOP)"


class FilingPlatform(wb.Platform):
    id = "filing"
    label = "Confluence (where the published process is filed)"
    kinds = pub.FILING
    simulator = "tests/mocklab/sims/process.py: confluence (Confluence Cloud REST v2)"
    reads = "the space and its pages; a page is written only after you approve that very version"


FILING = FilingPlatform()


# ------------------------------------------------------------------ the published processes (versions kept)

def process(pid: str, u: dict | None = None) -> dict | None:
    r = db.one("SELECT * FROM processdocs_processes WHERE id = ?", (pid,))
    if not r:
        return None
    if u is not None and r.get("item") and not auth.can_project(u, "view", db.project(r["item"])):
        return None
    return {**r, "map": _w4.j(r["map"], {}), "systems": _w4.j(r["systems"], [])}


def processes(u: dict) -> list[dict]:
    rows = [{**r, "map": _w4.j(r["map"], {}), "systems": _w4.j(r["systems"], [])} for r in db.q("SELECT * FROM processdocs_processes ORDER BY updated DESC")]
    return _w4.visible_items(u, rows)


def process_options(u: dict) -> list[tuple[str, str]]:
    return [(p["id"], f"{p['name']} · version {p['version']} · {sum(1 for s in p['map'].get('steps') or [] if s['type'] not in ('start', 'end'))} steps") for p in processes(u)]


def publish(ctx: wb.Ctx, proc: dict, xml: str, pid: str | None, note: str = "") -> dict:
    now = time.time()
    who = ctx.who or ctx.owner
    proc = {**proc, "head": ctx.get("head") or proc.get("head") or {}}
    systems = sorted({s.get("system") for s in proc["steps"] if s.get("system")})
    if pid and db.one("SELECT 1 FROM processdocs_processes WHERE id = ?", (pid,)):
        v = db.one("SELECT version FROM processdocs_processes WHERE id = ?", (pid,))["version"] + 1
        db.run("UPDATE processdocs_processes SET version = ?, map = ?, systems = ?, published_by = ?, published = ?, flagged = NULL, updated = ? WHERE id = ?",
               (v, json.dumps(proc), json.dumps(systems), who, now, now, pid))
    else:
        pid, v = "proc-" + _secrets.token_hex(4), 1
        db.run("INSERT INTO processdocs_processes (id, name, item, version, map, systems, owner_id, published_by, published, status, created, updated) VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?, 'published', ?, ?)",
               (pid, proc.get("name") or ctx.title, ctx.id, json.dumps(proc), json.dumps(systems), ctx.owner, who, now, now, now))
    db.run("INSERT OR REPLACE INTO processdocs_versions (process_id, version, item, map, bpmn, published_by, published, note) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
           (pid, v, ctx.id, json.dumps(proc), xml, who, now, note[:500] or None))
    db.audit("processdocs.publish", pid, {"version": v, "steps": len(proc["steps"]), "item": ctx.id}, who)
    return process(pid)


# ------------------------------------------------------------------ the map: records a person corrects <-> a map

def _lanes_opts(ctx: wb.Ctx):
    return [(l["id"], f"{l['name']} ({l.get('kind') or 'person'})") for l in ctx.get("lanes") or []] or [("L1", "Lane 1")]


def next_text(nxt: list[dict]) -> str:
    return "; ".join(f"{n['to']} if {n['when']}" if n.get("when") else n["to"] for n in nxt or [])


def parse_next(s: str) -> list[dict]:
    out = []
    for part in [p.strip() for p in re.split(r"[;,\n]", str(s or "")) if p.strip()]:
        m = re.match(r"^([A-Za-z_][\w.-]*)(?:\s+(?:if|when)\s+(.+))?$", part)
        out.append({"to": m.group(1), "when": (m.group(2) or "").strip()} if m else {"to": part, "when": ""})
    return out


def to_records(proc: dict, segs: dict | None = None) -> list[dict]:
    segs = segs or {}
    out = []
    for s in proc.get("steps") or []:
        refs = _w4.parse_refs(s.get("sources"))
        out.append({"id": s["id"], "step": s["id"], "name": s.get("name") or "", "type": s.get("type") or "task", "lane": s.get("lane") or "", "next": next_text(s.get("next")),
                    "instructions": s.get("instructions") or "", "system": s.get("system") or "", "screen": s.get("screen") or "", "rule": s.get("rule") or "",
                    "fields": [str(f) for f in s.get("fields") or []], "source": ", ".join(r["ref"] for r in refs), "sources": refs, "at": s.get("at") or "",
                    "where": _w4.where_text(refs, segs) + (f" at {s['at']}" if s.get("at") else ""), "cases": s.get("cases")})
    return out


def from_records(recs: list[dict], lanes: list[dict], name: str) -> dict:
    steps = []
    for r in recs:
        steps.append({"id": r.get("step") or r["id"], "name": r.get("name") or "", "type": r.get("type") or "task", "lane": r.get("lane") or (lanes[0]["id"] if lanes else ""),
                      "next": parse_next(r.get("next")), "instructions": r.get("instructions") or "", "system": r.get("system") or "", "screen": r.get("screen") or "",
                      "rule": r.get("rule") or "", "fields": list(r.get("fields") or []), "sources": r.get("sources") or _w4.parse_refs(r.get("source")), "at": r.get("at") or ""})
    return {"name": name, "lanes": lanes, "steps": steps}


def _validate_map(recs: list[dict], ctx: wb.Ctx) -> list[str]:
    """Rules first: a map that cannot be drawn or followed is refused — one start, an end, real links, labelled
    decisions, a lane for every step, instructions for every task."""
    have = {r.get("step") for r in recs if r.get("step")}
    n = max([int(x[1:]) for x in have if re.fullmatch(r"S\d+", str(x or ""))] + [0])
    for r in recs:
        if not r.get("step"):
            n += 1
            r["step"] = f"S{n}"
    proc = from_records(recs, ctx.get("lanes") or [], ctx.get("name") or ctx.title)
    out = bp.graph_problems(proc)
    out += [f"{s['id']} “{s['name'][:40]}”: write what the person (or agent) does — the SOP line" for s in proc["steps"] if s["type"] in ("task", "user", "manual", "service") and not s["instructions"].strip()]
    return out


MAP_COLUMNS = [wb.Column("step", "Id", readonly=True), wb.Column("name", "Step"), wb.Column("type", "Kind", "select", options=STEP_TYPES),
               wb.Column("lane", "Lane (who)", "select", options=_lanes_opts),
               wb.Column("next", "Goes on to", help="the next step ids, e.g. “S4” — a decision: “S5 if it matches; S6 if it does not”"),
               wb.Column("instructions", "What to do (the SOP line)", "longtext"), wb.Column("system", "System"), wb.Column("screen", "Screen"),
               wb.Column("rule", "Rule"), wb.Column("where", "From", readonly=True)]
MAP_EDIT = wb.Edit(columns=MAP_COLUMNS, validate=_validate_map, label="step")


def _process_view(proc: dict) -> dict:
    lane = {l["id"]: l["name"] for l in proc.get("lanes") or []}
    by = {s["id"]: s for s in proc["steps"]}
    return {"steps": [{"label": f"{s['id']} · {s['name']}" + (" (decision)" if s["type"] == "gateway" else ""), "actor": lane.get(s.get("lane"), s.get("lane") or ""),
                       "next": [f"{(by.get(n['to']) or {}).get('name', n['to'])}" + (f" ({n['when']})" if n.get("when") else "") for n in s.get("next") or []]} for s in proc["steps"]]}


def _bpmn_out(ctx: wb.Ctx, proc: dict, name: str, label: str) -> tuple[str, list[str]]:
    xml = bp.to_bpmn(proc)
    probs = bp.validate(xml)
    ctx.output(name, xml, label=label)
    ctx.evidence(f"BPMN 2.0 checks: {name}", {"rows": [{"check": "well-formed BPMN 2.0, ids, flows, start and end, a diagram shape for every node and an edge for every flow",
                                                        "status": "pass" if not probs else "fail", "problems": "; ".join(probs)}], "nodes": len(proc["steps"]),
                                               "flows": sum(len(s.get("next") or []) for s in proc["steps"])}, kind="bpmn", ok=not probs)
    return xml, probs


# ------------------------------------------------------------------ Develop

def d_capture(ctx: wb.Ctx) -> dict:
    read = _w4.read_uploads(ctx, UPLOADS)
    logs = _w4.eventlogs(ctx)
    if not read["files"]:
        raise wb.StepFailed("Upload what the process comes from: interviews or transcripts, a screen recording (with its transcript), or a system log (CSV, Excel, XES).")
    texts = sum(f["passages"] for f in read["files"])
    media = [f for f in read["files"] if f["passages"] == 0 and f["kind"].startswith(("recording", "image"))]
    mined = None
    if logs:
        lg = max(logs, key=lambda x: x["events"])
        mined = _w4.mined_map(lg)
        (ctx.dir / "sources" / "mined.json").write_text(json.dumps({"from": lg["file"], "cases": mined["cases"], "activities": mined["acts"], "map": mined}, indent=1, default=str), encoding="utf-8")
        ctx.put("log", lg["file"])
        ctx.evidence(f"Mined from {lg['file']}", {"rows": [{"activity": a, "cases": n} for a, n in sorted(mined["acts"].items(), key=lambda kv: -kv[1])], "variants": len(_w4.variants(lg["cases"])),
                                                  "events": lg["events"], "columns": lg["columns"]}, kind="mining", ok=True)
    if not texts and not media and not logs:
        raise wb.StepFailed("None of the uploads says how the work is done: add an interview, a transcript, a recording or a log.")
    data = _w4.files_table(read)
    for lg in logs:
        data["rows"].append([lg["file"], "event log", f"{len(lg['cases'])} case(s), {lg['events']} event(s), {len({e[1] for v in lg['cases'].values() for e in v})} activities", 0,
                             f"columns: {lg['columns']['case']}, {lg['columns']['activity']}, {lg['columns']['time']}" + (f"; {lg['skipped']} row(s) without a time skipped" if lg["skipped"] else "")])
    return {"summary": f"{len(read['files'])} file(s): {texts} passage(s) to cite, {len(media)} recording(s) or image(s) for the agent to look at"
            + (f", and a log of {mined['cases']} case(s) mined into {len(mined['acts'])} activities (rules first)" if mined else "") + ".",
            "counts": {"files": len(read["files"]), "passages": texts, "recordings": len(media), "cases": (mined or {}).get("cases") or 0}, "data": data}


MAP = """Read WORK.md, then sources/segments.json (every passage of the interviews and transcripts, with its id) and, when it
exists, sources/mined.json (the process an event log shows: activities, how often, and their order — rules, not
guesses). Look at the screen recordings in data/ yourself: `genbi read data/<file>` gives a video's key frames.

FILE process.yaml — the process map and its SOP lines:

process: {name: <name>, owner: <role>, trigger: <what starts it>, outcome: <what ends it>}
lanes: [{id: L1, name: AP clerk, kind: person | agent | system}]
steps:
  - id: S1
    name: Invoice e-mail arrives
    type: start | task | user | manual | service | gateway | end
    lane: L1
    system: Outlook                  # where it happens (optional)
    screen: Inbox                    # the screen in the recording (optional)
    fields: [invoice number]         # optional
    rule: "…"                        # optional, from the sources
    instructions: "Open the e-mail and save the PDF."     # the SOP line (every task)
    next: [{to: S2}]                 # a decision: [{to: S5, when: "it matches"}, {to: S6, when: "it does not"}]
    sources: [{ref: <passage id>, quote: "<its words>"}]   # a recording's moment: {ref: <video>#media} and at: "00:01:20"

One start, at least one end; every step except an end says what comes next; a decision has two or more labelled ways
out. Every activity the log shows in more than a few cases is a step on the map, under the log's own name. Cite the
passage (word for word) or the recording's moment for every step; never invent a screen, a field or a rule. British English."""


def _map_prompt(ctx: wb.Ctx) -> str:
    return MAP


def check_process(y: dict, segs: dict, mined: dict | None = None) -> list[str]:
    out = []
    lanes = y.get("lanes") if isinstance(y.get("lanes"), list) else []
    if not lanes:
        out.append("lanes is empty — who does the steps (people, agents, systems)")
    for i, l in enumerate(lanes, 1):
        if not isinstance(l, dict) or not l.get("id") or not l.get("name"):
            out.append(f"lane {i}: give it an id and a name")
        elif l.get("kind") and l["kind"] not in LANE_KINDS:
            out.append(f"lane {l['id']}: kind is person, agent or system")
    steps = y.get("steps") if isinstance(y.get("steps"), list) else []
    if not steps:
        return out + ["steps is empty"]
    proc = {"name": (y.get("process") or {}).get("name") if isinstance(y.get("process"), dict) else "", "lanes": [l for l in lanes if isinstance(l, dict)],
            "steps": [{**s, "next": [n for n in (s.get("next") or []) if isinstance(n, dict)]} for s in steps if isinstance(s, dict)]}
    out += bp.graph_problems(proc)
    for s in proc["steps"]:
        where = f"{s.get('id')} “{str(s.get('name') or '')[:40]}”"
        if s.get("type") in ("task", "user", "manual", "service"):
            if not str(s.get("instructions") or "").strip():
                out.append(f"{where}: write the SOP line (instructions)")
            refs = _w4.parse_refs(s.get("sources"))
            media = [r for r in refs if (segs.get(r["ref"]) or {}).get("kind") == "media"]
            if media and not str(s.get("at") or "").strip():
                out.append(f"{where}: say at what moment of the recording it happens (at: 00:01:20)")
            out += _w4.check_sources(where, refs, segs, statement=str(s.get("rule") or ""))
    if mined:
        names = {_w4.name_key(s.get("name")) for s in proc["steps"]}
        for a, n in sorted(mined.get("activities", {}).items(), key=lambda kv: -kv[1]):
            if n / max(1, mined.get("cases") or 1) >= 0.05 and _w4.name_key(a) not in names:
                out.append(f"the log shows “{a}” in {n} case(s) but the map has no step of that name")
    return out


def _mined(ctx: wb.Ctx) -> dict | None:
    p = ctx.dir / "sources" / "mined.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _map_check(ctx: wb.Ctx) -> list[str]:
    y, probs = _w4.load_yaml(ctx.dir / "process.yaml")
    return probs if probs else check_process(y, _w4.segments(ctx), _mined(ctx))


def _map_after(ctx: wb.Ctx, res: dict) -> dict:
    y, _ = _w4.load_yaml(ctx.dir / "process.yaml")
    head = y.get("process") if isinstance(y.get("process"), dict) else {}
    lanes = [{"id": l["id"], "name": l["name"], "kind": l.get("kind") or "person"} for l in y.get("lanes") or []]
    proc = {"name": head.get("name") or ctx.title, "lanes": lanes, "steps": [{**s, "next": s.get("next") or []} for s in y.get("steps") or []]}
    ctx.put("lanes", lanes)
    ctx.put("name", proc["name"])
    ctx.put("head", head)
    recs = to_records(proc, _w4.segments(ctx))
    _, probs = _bpmn_out(ctx, proc, "process-draft.bpmn", "The drafted map (BPMN 2.0)")
    ctx.evidence("The agent's map (process.yaml)", {"process": y, "summary": res.get("text") or ""}, kind="agent", ok=True)
    tasks = sum(1 for s in proc["steps"] if s["type"] not in ("start", "end", "gateway"))
    return {"summary": f"{tasks} step(s) in {len(lanes)} lane(s) with {sum(1 for s in proc['steps'] if s['type'] == 'gateway')} decision(s), each citing where it came from"
            + (f"; the BPMN check found {len(probs)} problem(s)" if probs else "; the BPMN 2.0 file opens in bpmn.io-style tools") + ". Correct the map, then confirm.",
            "counts": {"steps": tasks, "lanes": len(lanes), "decisions": sum(1 for s in proc["steps"] if s["type"] == "gateway")}, "records": recs, "data": _process_view(proc),
            "items": [f"{s['id']}: {s['name']}" for s in proc["steps"][:8]]}


def _current(ctx: wb.Ctx, sid: str = "map") -> dict:
    return from_records(ctx.records(sid), ctx.get("lanes") or [], ctx.get("name") or ctx.title)


def _sop_records(ctx: wb.Ctx, proc: dict) -> list[dict]:
    have = {r["id"]: r for r in ctx.records(ctx.step_id)}
    lane = {l["id"]: l["name"] for l in proc["lanes"]}
    segs = _w4.segments(ctx)
    out = []
    for s in proc["steps"]:
        if s["type"] in ("start", "end"):
            continue
        refs = _w4.parse_refs(s.get("sources"))
        rec = {"id": s["id"], "step": s["id"], "name": s["name"], "who": lane.get(s["lane"], s["lane"]), "instructions": s.get("instructions") or ("Decide: " + "; ".join(f"{n['when']} → {n['to']}" for n in s["next"]) if s["type"] == "gateway" else ""),
               "where": (s.get("system") or "") + (f" › {s['screen']}" if s.get("screen") else ""), "rule": s.get("rule") or "",
               "from": _w4.where_text(refs, segs) + (f" at {s['at']}" if s.get("at") else "")}
        out.append({**rec, **({"instructions": have[s["id"]]["instructions"]} if s["id"] in have else {})})
    return out


def _sop_doc(ctx: wb.Ctx, proc: dict, sop: list[dict], name: str, version: int, status: str) -> dict:
    head = ctx.get("head") or {}
    lane_rows = [[l["name"], l.get("kind") or "person", ", ".join(s["name"] for s in proc["steps"] if s["lane"] == l["id"] and s["type"] not in ("start", "end"))[:200]] for l in proc["lanes"]]
    rec = {"head": head, "lanes": proc["lanes"], "sop": sop, "steps": proc["steps"]}
    secs = [{"title": "Purpose and scope", "blocks": [_w4.para(f"{head.get('trigger') or 'The process starts as the first step says'}; it ends when {head.get('outcome') or 'the last step is done'}. Owner: {head.get('owner') or 'the process owner'}.",
                                                               f"record:{name}#head")]},
            {"title": "Who does what", "blocks": [_w4.table(["Role", "Kind", "Steps"], lane_rows, f"record:{name}#lanes", "The lanes of the map")]},
            {"title": "Procedure", "blocks": [_w4.table(["Step", "Who", "What to do", "Where", "Rule", "From"], [[f"{r['step']} {r['name']}", r["who"], r["instructions"], r["where"], r["rule"], r["from"]] for r in sop],
                                                        f"record:{name}#sop", "Step by step, each line with where it came from")]},
            {"title": "The process map", "blocks": [_w4.para(f"The BPMN 2.0 map ({name}.bpmn) opens in bpmn.io, Camunda Modeler, Signavio and other BPMN tools.", f"record:{name}#head")]}]
    return _w4.build_doc(ctx, name, f"Standard operating procedure: {proc['name']}", f"Version {version} · {status}", secs, {name: rec}, label=f"SOP version {version} ({status})",
                         audience="the people who do the work and its owner")


def d_correct(ctx: wb.Ctx) -> dict:
    proc = _current(ctx)
    xml, probs = _bpmn_out(ctx, proc, "process-corrected.bpmn", "The corrected map (BPMN 2.0)")
    if probs:
        raise wb.StepFailed("The corrected map does not make valid BPMN: " + "; ".join(probs[:4]))
    sop = _sop_records(ctx, proc)
    ctx.put("map", proc)
    edits = sum(1 for a, b in zip(ctx.records("map"), to_records(proc)) if a.get("name") != b.get("name"))
    return {"summary": f"The SOP: {len(sop)} line(s), each next to the passage or the moment of the recording it came from. Correct the wording, then confirm.",
            "records": sop, "counts": {"lines": len(sop), "edited on the map": edits}, "data": {"columns": ["Step", "Who", "What to do", "Where", "From"], "rows": [[f"{r['step']} {r['name']}", r["who"], r["instructions"], r["where"], r["from"]] for r in sop]}}


def _validate_sop(recs: list[dict], ctx: wb.Ctx) -> list[str]:
    return [f"{r['step']} “{r['name'][:40]}”: the SOP line is empty" for r in recs if not str(r.get("instructions") or "").strip()]


SOP_EDIT = wb.Edit(columns=[wb.Column("step", "Step", readonly=True), wb.Column("name", "Name", readonly=True), wb.Column("who", "Who", readonly=True),
                            wb.Column("instructions", "What to do", "longtext"), wb.Column("where", "Where", readonly=True), wb.Column("from", "From (passage or recording)", readonly=True)],
                   add=False, remove=False, validate=_validate_sop, label="line")


def _final(ctx: wb.Ctx) -> dict:
    proc = ctx.get("map") or _current(ctx)
    sop = {r["step"]: r for r in ctx.records("correct")}
    for s in proc["steps"]:
        if s["id"] in sop and s["type"] != "gateway":
            s["instructions"] = sop[s["id"]]["instructions"]
    return proc


def d_publish(ctx: wb.Ctx, proc: dict | None = None, note: str = "") -> dict:
    proc = proc or _final(ctx)
    pid = ctx.scope.get("process") or ctx.get("process_id")
    prev = process(pid) if pid else None
    v = (prev["version"] + 1) if prev else 1
    xml, probs = _bpmn_out(ctx, proc, f"process-v{v}.bpmn", f"The process map, version {v} (BPMN 2.0)")
    if probs:
        raise wb.StepFailed("The map does not make valid BPMN: " + "; ".join(probs[:4]))
    sop = [r for r in (ctx.records("correct") or _sop_records(ctx, proc))]
    info = _sop_doc(ctx, proc, sop, f"sop-v{v}", v, "published")
    p = publish(ctx, proc, xml, pid, note=note or f"published from {ctx.id}")
    ctx.put("process_id", p["id"])
    ctx.put("version", p["version"])
    _lineage(ctx, p)
    dp = _w4.doc_problems(info)
    return {"summary": f"“{p['name']}” version {p['version']} is published: the BPMN 2.0 map and the Word SOP (with an HTML preview) in your template"
            + (f"; the document check found {len(dp)} problem(s): {dp[0]}" if dp else "") + ". Confirm before it is filed to Confluence or SharePoint.",
            "counts": {"version": p["version"], "steps": len(proc["steps"])},
            "data": {"items": [{"title": f"process-v{v}.bpmn", "detail": "BPMN 2.0 with its diagram — opens in bpmn.io, Camunda Modeler, Signavio"},
                               {"title": f"sop-v{v}.docx", "detail": f"{len(sop)} step(s), each with where it came from"},
                               {"title": "Kept", "detail": f"version {p['version']} in the process library; every earlier version kept"}]}}


def _lineage(ctx: wb.Ctx, p: dict) -> None:
    pn = ctx.lineage_node("process", SYSTEM, p["id"], label=f"Process: {p['name']} (v{p['version']})", properties={"version": p["version"], "steps": len(p["map"]["steps"])})
    for l in p["map"].get("lanes") or []:
        rn = ctx.lineage_node("role", "Relay roles", l["name"], label=l["name"], properties={"kind": l.get("kind") or "person"}, own=False)
        ctx.lineage_edge(rn, pn, "owns", {"lane": l["id"]})
    for sysname in p["systems"]:
        sn = ctx.lineage_node("system", sysname, sysname, label=sysname, own=False)
        ctx.lineage_edge(sn, pn, "relates", {"process": p["id"]})


AUTOMATE_ROUTES = (("none", "Keep as it is"), ("n8n", "Workflows (n8n)"), ("rpa", "RPA (a bot)"), ("sdlc", "AI SDLC (a change in an app)"))


def d_automate(ctx: wb.Ctx) -> dict:
    proc = process(ctx.get("process_id")) or {"map": _final(ctx), "name": ctx.title, "version": ctx.get("version")}
    m = proc["map"]
    have = {r["id"]: r for r in ctx.records(ctx.step_id)}
    lane = {l["id"]: l for l in m.get("lanes") or []}
    by = {s["id"]: s for s in m["steps"]}
    prev: dict = {}
    for s in m["steps"]:
        for n in s.get("next") or []:
            prev.setdefault(n["to"], []).append(s["id"])
    recs = []
    for s in m["steps"]:                                  # rules first: a person's step in a system, keyed from another, by hand on a screen, or a rule
        if s["type"] not in ("task", "user", "manual"):
            continue
        kind = (lane.get(s["lane"]) or {}).get("kind") or "person"
        if kind != "person":
            continue
        before = {(by.get(p) or {}).get("system") for p in prev.get(s["id"], [])} - {None, ""}
        if s.get("rule"):
            route, why = "sdlc", "a rule a person applies by hand: change the application so it applies it"
        elif s.get("system") and s.get("fields") and before and s["system"] not in before:
            route, why = "n8n", f"keys {', '.join(s['fields'][:4])} into {s['system']} from {', '.join(sorted(before))}: a workflow between the two"
        elif s.get("screen") and s.get("system"):
            route, why = "rpa", f"done by hand on the {s['screen']} screen of {s['system']}; a bot where no API exists"
        else:
            continue
        rec = {"id": s["id"], "step": s["id"], "name": s["name"], "route": route, "why": why, "cases": s.get("cases") or ""}
        recs.append({**rec, **({"route": have[s["id"]]["route"]} if s["id"] in have else {})})
    filing = _w4.tracker_connection(ctx, pub.FILING)
    p = _w4.push_of(ctx.id, "automate")
    if filing and not p:
        if not connectors.may_write(filing):
            raise wb.StepFailed(f"{filing['name']} is read-only: change its scope to “Read & write — with approval” to file the process, or remove it to download the files.")
        v = proc.get("version")
        body = "<h2>Procedure</h2><table><tbody><tr><th>Step</th><th>Who</th><th>What to do</th></tr>" + "".join(
            f"<tr><td>{_w4.esc(r['step'] + ' ' + r['name'])}</td><td>{_w4.esc(r['who'])}</td><td>{_w4.esc(r['instructions'])}</td></tr>" for r in ctx.records("correct")) + "</tbody></table>"
        _w4.request_push(ctx, filing["id"], "page", {"title": f"{proc['name']} (version {v})", "body": body, "files": [f"process-v{v}.bpmn", f"sop-v{v}.docx"], "version": v},
                         f"File “{proc['name']}” version {v} to {filing['name']}", step="automate")
    return _automate_view(ctx, recs)


def _automate_view(ctx: wb.Ctx, recs: list[dict] | None = None) -> dict:
    recs = recs if recs is not None else ctx.records("automate")
    p = _w4.push_of(ctx.id, "automate")
    filed = ("filed: " + ", ".join(c.get("url") or c["key"] for c in (p["result"].get("created") or [])) if p and p["status"] == "written" else
             "waiting for its own approval in the Validation queue" if p and p["status"] == "awaiting" else "failed — see the activity" if p and p["status"] == "failed"
             else "not filed (no Confluence connected): the files are in the outputs")
    return {"summary": f"{len(recs)} step(s) worth automating, each with where it would go — pick or change the route; the published version is {filed}.",
            "records": recs, "counts": {"candidates": len(recs)}, "data": {"columns": ["Step", "Route", "Why"], "rows": [[f"{r['step']} {r['name']}", dict(AUTOMATE_ROUTES).get(r["route"], r["route"]), r["why"]] for r in recs]}}


_w4.REFRESH["processdocs.automate"] = lambda ctx: _automate_view(ctx)


def _validate_automate(recs: list[dict], ctx: wb.Ctx) -> list[str]:
    return _w4.push_problems(ctx.id, "automate")


AUTO_EDIT = wb.Edit(columns=[wb.Column("step", "Step", readonly=True), wb.Column("name", "Name", readonly=True), wb.Column("route", "Route", "select", options=AUTOMATE_ROUTES),
                             wb.Column("why", "Why", readonly=True)], add=False, remove=False, validate=_validate_automate, label="candidate")


def _handoff(ctx: wb.Ctx, r: dict, proc: dict) -> dict:
    title = f"{r['name']} ({proc['name']})"[:150]
    brief = f"From the published process “{proc['name']}” version {proc.get('version')}, step {r['step']} {r['name']}: {r['why']}. Process map: {wb.route_of(ctx.st)}"
    if r["route"] == "sdlc":
        try:
            from .. import sdlc
            req = sdlc.create_request(ctx.who or ctx.owner, None, f"Automate: {title}", brief, source="processdocs", source_id=ctx.id, start=False)
            return ctx._handoff({"kind": "sdlc", "label": title, "status": "AI SDLC request opened (waits for a repository and a plan)", "link": f"#/sdlc/{req['id']}", "case": req["id"]})
        except Exception as e:  # noqa: BLE001 - kept as a brief below
            brief += f"\n\n(AI SDLC could not take it: {str(e)[:200]})"
    if wb.pack_of(r["route"]) and wb.module_on(r["route"]) and "develop" in wb.pack_of(r["route"]).work:      # it builds new automations

        it = wb.create(r["route"], "develop", f"Automate: {title}", who=ctx.owner, brief=brief, scope={"_source_ok": True}, start_now=False, parent=ctx.id)
        return ctx._handoff({"kind": r["route"], "label": title, "status": "work item created (not started)", "link": wb.route_of(it)})
    name = ctx.output(f"automate-{r['route']}-{r['step']}.md", f"# {title}\n\n{brief}\n", label=f"Hand-off brief: {title[:60]}")
    return ctx._handoff({"kind": r["route"], "label": title, "status": "brief ready (the module does not build new automations yet)", "output": name, "link": f"#/m/{r['route']}"})


def d_keep(ctx: wb.Ctx) -> dict:
    pid = ctx.get("process_id") or ctx.scope.get("process")
    p = process(pid)
    if not p:
        raise wb.StepFailed("The published process is not in the library any more.")
    if not ctx.get("handed"):
        for r in ctx.records("automate"):
            if r.get("route") and r["route"] != "none":
                _handoff(ctx, r, p)
        ctx.put("handed", True)
    _lineage(ctx, p)
    pn = lineage.node_id("process", SYSTEM, p["id"])
    ups = [e["from_id"] for e in db.q("SELECT from_id FROM lineage_edges WHERE to_id = ?", (pn,))]
    names = {r["id"]: r for r in db.q(f"SELECT id, kind, name, label, last_seen, properties FROM lineage_nodes WHERE id IN ({','.join('?' * len(ups))})", tuple(ups))} if ups else {}
    base = ctx.get("baseline") or {}
    changed = []
    for nid, n in names.items():
        sig = f"{n['properties']}"
        if nid in base and base[nid] != sig:
            changed.append({"id": nid, "what": f"{lineage.KIND_LABEL.get(n['kind'], n['kind'])} {n['label'] or n['name']} changed since version {p['version']} was published"})
    heal = []
    if "heal_cases" in db.tables():
        for h in db.q("SELECT id, title, place FROM heal_cases WHERE closed IS NULL"):
            if any(s.lower() in f"{h.get('title')} {h.get('place')}".lower() for s in p["systems"]):
                heal.append({"id": h["id"], "what": f"Self-healing case on {h['place'] or h['title']}: {h['title']}"})
    flags = changed + heal
    ctx.put("baseline", {nid: f"{n['properties']}" for nid, n in names.items()})
    if flags:
        db.run("UPDATE processdocs_processes SET flagged = ? WHERE id = ?", (json.dumps([f["what"] for f in flags]), p["id"]))
        db.audit("processdocs.flagged", p["id"], {"item": ctx.id, "flags": [f["what"] for f in flags][:6]}, ctx.who or "agent")
    ctx.put("flags", flags)
    return {"summary": (f"{len(flags)} change(s) since version {p['version']}: the document is flagged for review." if flags else
                        f"Watching {len(names)} system(s) and role(s) of version {p['version']}: nothing changed.") + (f" {wb.schedule_text(ctx.st.get('schedule'))}." if ctx.st.get("schedule") else ""),
            "counts": {"watched": len(names), "flags": len(flags)}, "data": {"columns": ["What changed"], "rows": [[f["what"]] for f in flags] or [["Nothing has changed"]]},
            "items": [f["what"] for f in flags[:6]]}


# ------------------------------------------------------------------ Assess (existing documents)

def a_connect(ctx: wb.Ctx) -> dict:
    read = _w4.read_uploads(ctx, UPLOADS)
    if not read["files"]:
        raise wb.StepFailed("Upload the process documents to assess: BPMN or Visio exports, Word, PDF or slide procedures.")
    return {"summary": f"{len(read['files'])} document(s) opened — read-only copies.", "counts": {"documents": len(read["files"])}, "data": _w4.files_table(read)}


def _doc_meta(path: Path) -> dict:
    if path.suffix.lower() != ".docx":
        return {}
    try:
        import docx
        cp = docx.Document(str(path)).core_properties
        return {"author": cp.author or "", "modified": cp.modified.timestamp() if cp.modified else None}
    except Exception:  # noqa: BLE001
        return {}


def a_inventory(ctx: wb.Ctx) -> dict:
    have = {r["id"]: r for r in ctx.records(ctx.step_id)}
    segs = _w4.segments(ctx)
    recs, maps = [], {}
    for f in ctx.files(UPLOADS):
        p = ctx.dir / "data" / f["name"]
        ext = p.suffix.lower()
        rec = {"id": f["name"], "file": f["name"], "include": True, "format": ext[1:].upper(), "process": Path(f["name"]).stem, "steps": None, "owner": "", "modified": ""}
        try:
            if ext == ".bpmn":
                m = bp.from_bpmn(p.read_text(encoding="utf-8"))
                maps[f["name"]] = m
                rec.update(process=m["name"], steps=sum(1 for s in m["steps"] if s["type"] not in ("start", "end")), lanes=len(m["lanes"]))
            elif ext == ".vsdx":
                m = bp.from_vsdx(p)
                maps[f["name"]] = m
                rec.update(steps=sum(1 for s in m["steps"] if s["type"] not in ("start", "end")), lanes=len(m["lanes"]))
            else:
                ss = [s for s in segs.values() if s["file"] == f["name"] and s["kind"] == "text"]
                rec.update(steps=sum(1 for s in ss if re.match(r"^\s*(\d+[.)]|step \d+)", s["text"], re.I)) or None, sop=True)
            meta = _doc_meta(p)
            rec.update(owner=meta.get("author") or "", modified=time.strftime("%Y-%m-%d", time.gmtime(meta["modified"])) if meta.get("modified") else "")
        except Exception as e:  # noqa: BLE001 - recorded as a finding
            rec["note"] = f"could not be read: {str(e)[:120]}"
        recs.append({**rec, **({"include": have[f["name"]]["include"]} if f["name"] in have else {})})
    (ctx.dir / "sources" / "maps.json").write_text(json.dumps(maps, indent=1), encoding="utf-8")
    return {"summary": f"{len(recs)} document(s): {sum(1 for r in recs if r['format'] in ('BPMN', 'VSDX'))} map(s) and {sum(1 for r in recs if r.get('sop'))} written procedure(s) — untick what is out of scope.",
            "records": recs, "counts": {"documents": len(recs)}, "data": {"columns": ["Include", "Document", "Format", "Process", "Steps", "Owner", "Last changed"],
                                                                          "rows": [["yes" if r["include"] else "no", r["file"], r["format"], r["process"], r["steps"], r["owner"] or "—", r["modified"] or "—"] for r in recs]}}


INV_EDIT = wb.Edit(columns=[wb.Column("include", "Include", "bool"), wb.Column("file", "Document", readonly=True), wb.Column("format", "Format", readonly=True),
                            wb.Column("process", "Process", readonly=True), wb.Column("steps", "Steps", "number", readonly=True)], add=False, remove=False, label="document")


def a_health(ctx: wb.Ctx) -> dict:
    maps = json.loads((ctx.dir / "sources" / "maps.json").read_text(encoding="utf-8")) if (ctx.dir / "sources" / "maps.json").exists() else {}
    inv = [r for r in ctx.records("inventory") if r.get("include")]
    checks, findings = [], []
    now = time.time()
    names = {}
    for r in inv:
        names.setdefault(_w4.name_key(r["process"]), []).append(r["file"])
        m = maps.get(r["file"])
        if m:
            gp = bp.graph_problems(m)
            xml = bp.to_bpmn(m) if not gp else ""
            vp = bp.validate(xml) if xml else gp
            if r["format"] == "BPMN":
                vp = bp.validate((ctx.dir / "data" / r["file"]).read_text(encoding="utf-8")) or gp
            checks.append({"name": f"valid-{r['file']}", "label": f"{r['file']}: a valid, connected map", "status": "fail" if vp else "pass", "measured": f"{len(m['steps'])} node(s)",
                           "expected": "BPMN 2.0, one start, an end, every step reachable", "detail": "; ".join(vp[:3]) or "valid"})
            for pr in vp[:5]:
                findings.append({"id": f"f-{_w4.slug(r['file'])}-{len(findings)}", "document": r["file"], "issue": pr, "severity": "high", "decision": "keep"})
            nolane = [s["name"] for s in m["steps"] if s["type"] not in ("start", "end") and (not m["lanes"] or "unassigned" in (next((l["name"] for l in m["lanes"] if l["id"] == s["lane"]), "") or "").lower())]
            if nolane:
                findings.append({"id": f"f-{_w4.slug(r['file'])}-lanes", "document": r["file"], "issue": f"{len(nolane)} step(s) without a role (no swimlanes)", "severity": "medium", "decision": "keep"})
        if r.get("modified"):
            age = (now - time.mktime(time.strptime(r["modified"], "%Y-%m-%d"))) / 86400
            if age > 365:
                findings.append({"id": f"f-{_w4.slug(r['file'])}-stale", "document": r["file"], "issue": f"last changed {r['modified']}: over a year old", "severity": "medium", "decision": "keep"})
        if not r.get("owner"):
            findings.append({"id": f"f-{_w4.slug(r['file'])}-owner", "document": r["file"], "issue": "no owner recorded", "severity": "low", "decision": "keep"})
    for k, fs in names.items():
        if len(fs) > 1:
            findings.append({"id": f"f-dup-{_w4.slug(k)}", "document": ", ".join(fs), "issue": f"the same process in {len(fs)} documents — they may disagree", "severity": "medium", "decision": "keep"})
    sops = [r for r in inv if r.get("sop")]
    for r in sops:
        if not any(_w4.name_key(m["name"]) == _w4.name_key(r["process"]) for m in maps.values()):
            findings.append({"id": f"f-{_w4.slug(r['file'])}-nomap", "document": r["file"], "issue": "a written procedure with no process map", "severity": "low", "decision": "keep"})
    ctx.put("findings", findings)
    checks.append(ctx.proof("references_real", label="Every document in scope was read", refs=[r["file"] for r in inv], known=[f["name"] for f in ctx.files()]))
    return {"summary": f"{len(inv)} document(s) checked: {sum(1 for c in checks if c['status'] == 'fail')} map(s) do not validate; {len(findings)} finding(s).",
            "counts": {"documents": len(inv), "findings": len(findings)}, "data": {"checks": checks}}


def a_findings(ctx: wb.Ctx) -> dict:
    have = {r["id"]: r for r in ctx.records(ctx.step_id)}
    recs = [{**f, **({"decision": have[f["id"]]["decision"]} if f["id"] in have else {})} for f in ctx.get("findings") or []]
    return {"summary": f"{len(recs)} finding(s) — keep what matters, ignore what does not.", "records": recs, "counts": {"findings": len(recs)},
            "data": {"columns": ["Document", "Issue", "Severity"], "rows": [[r["document"], r["issue"], r["severity"]] for r in recs]}}


FIND_EDIT = wb.Edit(columns=[wb.Column("decision", "Decision", "select", options=(("keep", "Keep"), ("ignore", "Ignore"))), wb.Column("document", "Document", readonly=True),
                             wb.Column("issue", "Issue", readonly=True), wb.Column("severity", "Severity", readonly=True)], add=False, remove=False, label="finding")
MINUTES = {"convert a Visio page by rules and correct it": 20, "draft a map from a written procedure (agent) and correct it": 45, "fix a problem in a map": 15, "per step to check against the work": 2}


def a_estimate(ctx: wb.Ctx) -> dict:
    from .. import registry
    inv = {r["file"]: r for r in ctx.records("inventory") if r.get("include")}
    kept = [f for f in ctx.records("findings") if f.get("decision") != "ignore"]
    items, total = [], 0.0
    for fn, r in inv.items():
        probs = sum(1 for f in kept if f["document"] == fn and f["severity"] == "high")
        base = MINUTES["convert a Visio page by rules and correct it"] if r["format"] == "VSDX" else MINUTES["draft a map from a written procedure (agent) and correct it"] if r.get("sop") else 0
        mins = base + probs * MINUTES["fix a problem in a map"] + (r.get("steps") or 0) * MINUTES["per step to check against the work"]
        total += mins / 60
        items.append({"title": r["process"], "detail": f"{r['format']}: " + ("convert to BPMN" if r["format"] == "VSDX" else "map it from the procedure" if r.get("sop") else "check and fix the map") + (f", {probs} problem(s) to fix" if probs else ""),
                      "effort": f"{mins / 60:.1f} h"})
    b = registry.brand()
    rate, cur = float(b.get("hourly_rate") or 0), b.get("currency") or ""
    note = "Assumptions: " + "; ".join(f"{v} min to {k}" for k, v in MINUTES.items()) + "." + ("" if rate else " Set an hourly rate under Admin › Branding to see the cost.")
    ctx.output("assessment.md", "# Process documents: assessment\n\n" + "\n".join(f"- {i['title']}: {i['detail']} ({i['effort']})" for i in items) + f"\n\n{note}\n", label="Assessment (Markdown)")
    return {"summary": f"About {total:.1f} h of a person's time to bring {len(items)} process document(s) to the standard (BPMN + SOP)" + (f" ({cur}{rate * total:,.0f})" if rate else "") + ".",
            "counts": {"documents": len(items), "hours": round(total, 1)}, "data": {"items": items, "total": f"{total:.1f} h", "note": note}}


# ------------------------------------------------------------------ Change (a published process)

def c_request(ctx: wb.Ctx) -> dict:
    p = process(ctx.scope.get("process") or "", db.user(ctx.owner or "") or {})
    if not p:
        raise wb.StepFailed("The process this work item changes is not one its owner can see any more.")
    _w4.read_uploads(ctx, UPLOADS, extra=_w4.request_segment(ctx))
    ctx.put("process_id", p["id"])
    ctx.put("lanes", p["map"].get("lanes") or [])
    ctx.put("name", p["name"])
    ctx.put("published", p["map"])
    ctx.put("head", p["map"].get("head") or {})
    if not ctx.st.get("approver"):                         # approvals follow the published RACI: the process's Accountable owner releases the change
        try:
            from . import raci
            acc = [x for x in raci.accountable(p["id"]) if x != ctx.owner and db.user(x)]
        except Exception:  # noqa: BLE001 - no RACI: the owner approves
            acc = []
        if acc:
            wb._mutate(ctx.id, lambda s: s.update(approver=acc[0]))
            _w4._share(ctx.id, acc[0], ctx.owner)
            ctx.note(f"The approver is {_w4.user_name(acc[0])}: Accountable for this process in its published RACI.", "ok")
    return {"summary": f"Change to “{p['name']}” version {p['version']} ({sum(1 for s in p['map']['steps'] if s['type'] not in ('start', 'end'))} steps)" + (f"; flagged: {p['flagged']}" if p.get("flagged") else "") + ".",
            "data": {"text": ctx.brief or "(no request text)"}, "counts": {"version": p["version"]}}


def c_diagnose(ctx: wb.Ctx) -> dict:
    proc = ctx.get("published") or {}
    words = {w for w in re.findall(r"[a-z0-9]+", _w4.norm(ctx.brief)) if len(w) > 3}
    touched = [s for s in proc.get("steps") or [] if words & set(re.findall(r"[a-z0-9]+", _w4.norm(f"{s['name']} {s.get('instructions')} {s.get('system')}")))]
    rows = [ctx.proof("references_real", label="The steps the request names are on the map", refs=re.findall(r"\bS\d+\b", ctx.brief) or [s["id"] for s in touched] or ["(none)"],
                      known=[s["id"] for s in proc.get("steps") or []])]
    conf = None
    for lg in _w4.eventlogs(ctx):
        conf = _w4.conformance(proc, lg)
        rows.append({"name": "conformance", "label": f"Today's map against {lg['file']}", "status": "pass" if conf["fitness"] >= 0.9 else "warn" if conf["fitness"] >= 0.7 else "fail",
                     "measured": f"{conf['fitness']:.0%} of the moves", "expected": "90 % or more", "detail": (f"the log has {', '.join(conf['missing'][:4])} not on the map" if conf["missing"] else "every logged activity is on the map"),
                     "evidence": ctx.evidence(f"Conformance with {lg['file']}", conf, kind="proof", ok=conf["fitness"] >= 0.7)})
    ctx.put("touched", [s["id"] for s in touched])
    return {"summary": f"The request touches {len(touched)} step(s): {', '.join(s['id'] + ' ' + s['name'] for s in touched[:4])}" + (f"; the map fits {conf['fitness']:.0%} of the new log" if conf else "") + ".",
            "data": {"checks": rows}, "counts": {"touched": len(touched)}, "items": [f"{s['id']}: {s['name']}" for s in touched[:6]]}


def c_fix(ctx: wb.Ctx) -> dict:
    recs = ctx.records(ctx.step_id) or to_records(ctx.get("published") or {"steps": []}, _w4.segments(ctx))
    return {"summary": "Change the map in place — rename, add or remove steps, re-route a decision. The graph rules refuse a broken map; Relay proves it next.", "records": recs,
            "data": _process_view(from_records(recs, ctx.get("lanes") or [], ctx.get("name") or ctx.title)), "counts": {"steps": len(recs)}}


def c_prove(ctx: wb.Ctx) -> dict:
    proc = _current(ctx, "fix")
    xml, probs = _bpmn_out(ctx, proc, "process-proposed.bpmn", "The changed map (BPMN 2.0)")
    old = {s["id"]: s for s in (ctx.get("published") or {}).get("steps") or []}
    new = {s["id"]: s for s in proc["steps"]}
    diff = {"added": [i for i in new if i not in old], "removed": [i for i in old if i not in new],
            "changed": [i for i in new if i in old and any(new[i].get(k) != old[i].get(k) for k in ("name", "type", "lane", "next", "instructions"))]}
    rows = [{"name": "bpmn", "label": "The changed map is valid BPMN 2.0 with its diagram", "status": "fail" if probs else "pass", "detail": "; ".join(probs[:3]) or "valid"},
            {"name": "diff", "label": "What changes", "status": "pass" if any(diff.values()) else "warn", "measured": sum(len(v) for v in diff.values()),
             "detail": f"{len(diff['added'])} added, {len(diff['changed'])} changed, {len(diff['removed'])} removed", "evidence": ctx.evidence("The change, step by step", diff, kind="proof", ok=True)}]
    for lg in _w4.eventlogs(ctx):
        conf = _w4.conformance(proc, lg)
        rows.append({"name": "conformance", "label": f"The changed map against {lg['file']}", "status": "pass" if conf["fitness"] >= 0.9 else "warn" if conf["fitness"] >= 0.7 else "fail",
                     "measured": f"{conf['fitness']:.0%}", "expected": "90 % or more", "detail": ", ".join(f"{x['from']} → {x['to']} ({x['times']})" for x in conf["not_allowed"][:3]) or "every move allowed",
                     "evidence": ctx.evidence(f"Conformance of the change with {lg['file']}", conf, kind="proof", ok=conf["fitness"] >= 0.7)})
    ctx.put("map", proc)
    ctx.put("diff", diff)
    return {"summary": f"{len(diff['added'])} added, {len(diff['changed'])} changed, {len(diff['removed'])} removed; " + ("the BPMN validates" if not probs else f"{len(probs)} BPMN problem(s)") + ".",
            "data": {"checks": rows}, "counts": {k: len(v) for k, v in diff.items()}, "ok": not probs}


def c_approve(ctx: wb.Ctx) -> dict:
    d = ctx.get("diff") or {}
    return {"summary": f"Release the next version: {len(d.get('added') or [])} added, {len(d.get('changed') or [])} changed, {len(d.get('removed') or [])} removed step(s).",
            "data": {"items": [{"title": k.title(), "detail": ", ".join(v) or "—"} for k, v in d.items()]}}


def c_learn(ctx: wb.Ctx) -> dict:
    proc = ctx.get("map") or _current(ctx, "fix")
    out = d_publish(ctx, proc, note=(ctx.brief or "")[:300])
    return {**out, "summary": out["summary"].replace("Confirm before it is filed to Confluence or SharePoint.", "Watching items flagging the old version are cleared.")}


# ------------------------------------------------------------------ Migrate (Visio, Word, slides)

def m_convert(ctx: wb.Ctx) -> dict:
    segs = _w4.segments(ctx)
    have = ctx.records(ctx.step_id)
    if have:
        proc = from_records(have, ctx.get("lanes") or [], ctx.get("name") or ctx.title)
        return {"summary": "Your corrections are kept.", "records": have, "data": _process_view(proc)}
    for f in ctx.files((".bpmn", ".vsdx")):
        p = ctx.dir / "data" / f["name"]
        proc = bp.from_bpmn(p.read_text(encoding="utf-8")) if p.suffix.lower() == ".bpmn" else bp.from_vsdx(p)
        for s in proc["steps"]:
            s["sources"] = [{"ref": f"{f['name']}#{s['id']}", "quote": ""}]
            s["instructions"] = s.get("instructions") or (s["name"] if s["type"] not in ("start", "end", "gateway") else "")
        ctx.put("lanes", proc["lanes"])
        ctx.put("name", proc["name"])
        ctx.put("converted_from", f["name"])
        extra = [{"id": f"{f['name']}#{s['id']}", "file": f["name"], "loc": f"shape {s['id']}", "kind": "text", "text": s["name"]} for s in proc["steps"]]
        _w4.read_uploads(ctx, UPLOADS, extra=extra, evidence=False)
        recs = to_records(proc, _w4.segments(ctx))
        gp = bp.graph_problems(proc)
        return {"summary": f"{f['name']} converted by rules: {sum(1 for s in proc['steps'] if s['type'] not in ('start', 'end'))} step(s), {sum(1 for s in proc['steps'] if s['type'] == 'gateway')} decision(s), "
                f"{len(proc['lanes'])} lane(s)" + (f"; {len(gp)} thing(s) to correct: {gp[0]}" if gp else "") + ". Correct the lanes and the SOP lines, then confirm.",
                "records": recs, "data": _process_view(proc), "counts": {"steps": len(proc["steps"]), "to correct": len(gp)}}
    docs = [f for f in ctx.files((".docx", ".pdf", ".pptx", ".txt", ".md")) if f["name"] in {s["file"] for s in segs.values()}]
    return {"summary": f"No Visio or BPMN export: ask Relay to draft the map from {', '.join(d['name'] for d in docs) or 'the documents'} (the action below), then correct it.",
            "records": [], "data": {"steps": []}, "counts": {"documents": len(docs)}}


def _convert_after(ctx: wb.Ctx, res: dict) -> dict:
    out = _map_after(ctx, res)
    out["summary"] = "Relay drafted the map from the written procedure: " + out["summary"]
    return out


def _validate_convert(recs: list[dict], ctx: wb.Ctx) -> list[str]:
    return ["the map is empty — ask Relay to draft it, or add the steps"] if not recs else _validate_map(recs, ctx)


CONVERT_EDIT = wb.Edit(columns=MAP_COLUMNS, validate=_validate_convert, label="step")


def m_check(ctx: wb.Ctx) -> dict:
    proc = _current(ctx, "convert")
    segs = _w4.segments(ctx)
    xml, probs = _bpmn_out(ctx, proc, "process-converted.bpmn", "The converted map (BPMN 2.0)")
    rows = [{"name": "bpmn", "label": "The converted map is valid BPMN 2.0 with its diagram", "status": "fail" if probs else "pass", "detail": "; ".join(probs[:3]) or "valid"},
            ctx.proof("references_real", label="Every step comes from the source document", refs=[r["ref"] for s in proc["steps"] for r in s.get("sources") or []] or ["(none)"], known=list(segs))]
    logs = _w4.eventlogs(ctx)
    for lg in logs:
        conf = _w4.conformance(proc, lg)
        rows.append({"name": "conformance", "label": f"Against how the work is really done ({lg['file']})", "status": "pass" if conf["fitness"] >= 0.9 else "warn" if conf["fitness"] >= 0.7 else "fail",
                     "measured": f"{conf['fitness']:.0%} of {conf['moves']} moves", "expected": "90 % or more",
                     "detail": ("not on the map: " + ", ".join(conf["missing"][:4]) + "; " if conf["missing"] else "") + ("never done: " + ", ".join(conf["unseen"][:4]) if conf["unseen"] else "every step is done in the log"),
                     "evidence": ctx.evidence(f"Conformance with {lg['file']}", conf, kind="proof", ok=conf["fitness"] >= 0.7)})
    if not logs:
        rows.append({"name": "conformance", "label": "Against how the work is really done", "status": "skip", "detail": "no event log or recording to check against: the process owner checks it"})
    ctx.put("map", proc)
    bad = sum(1 for r in rows if r["status"] == "fail")
    return {"summary": f"{len(rows)} check(s): " + (f"{bad} fail — send it back to Convert, or accept with the reasons" if bad else "the converted map holds up") + ".", "data": {"checks": rows}, "counts": {"failing": bad}}


def m_publish(ctx: wb.Ctx) -> dict:
    proc = ctx.get("map") or _current(ctx, "convert")
    ctx.put("head", {"owner": "the process owner", "trigger": f"Converted from {ctx.get('converted_from') or 'the old documents'}", "outcome": "the last step is done"})
    return d_publish(ctx, proc, note=f"migrated from {ctx.get('converted_from') or 'documents'}")


# ------------------------------------------------------------------ the module page

def _cards(u: dict) -> list[dict]:
    rows = [[p["name"], f"v{p['version']}", sum(1 for s in p["map"].get("steps") or [] if s["type"] not in ("start", "end")), len(p["map"].get("lanes") or []), ", ".join(p["systems"]) or "—",
             "flagged for review" if p.get("flagged") else "current", f"#/m/{MODULE}/i/{p['item']}" if p.get("item") else ""] for p in processes(u)]
    return [{"title": "Published processes", "columns": ["Process", "Version", "Steps", "Lanes", "Systems", "State", "Work item"], "rows": rows,
             "empty": "No process is published yet: a Develop or Migrate item's Publish step records one."}]


GUIDE = """# Business process documents — the work item

This folder is one work item of Relay's Business process documents module. The agent drafts the map; the process
owner corrects it before anything proceeds; the app writes the BPMN 2.0 and the SOP from what the person confirmed.

- `data/`: interviews, transcripts (.vtt), screen recordings (read their frames with `genbi read data/<file>`), event
  logs (CSV, Excel, XES), Visio and BPMN exports, Word or slide procedures.
- `sources/segments.json`: every passage with its id — the things a step may cite; a recording is `<file>#media`
  (say the moment with `at: 00:01:20`).
- `sources/mined.json` (when a log was uploaded): the activities, how often and in what order — every frequent one
  must be a step on the map, under the log's own name.
- `process.yaml`: what you write — process, lanes, steps (id, name, type, lane, system, screen, fields, rule,
  instructions, next, sources).

Never invent a screen, a field, a rule or a step; say what you assumed."""


wb.register(wb.Pack(
    module=MODULE, guide=GUIDE,
    lineage="each published process with the roles (lanes) that own it and the systems it uses; Keep current flags the document when one of them changes",
    platforms={"files": FILES, "filing": FILING},
    schemas={"step": MAP_COLUMNS, "sop": SOP_EDIT.columns},
    cards=_cards,
    work={
        "assess": wb.Work(title="See which process documents you have and what it takes to bring them to the standard", steps={
            "Connect": wb.Step(kind="platform", run=a_connect, agent="Reader", text="Each document is opened — BPMN and Visio exports, Word, PDF and slide procedures — read-only"),
            "Inventory": wb.Step(kind="platform", run=a_inventory, agent="Scanner", edit=INV_EDIT, text="Every process found, in each tool's own terms — steps, lanes, owner, last changed; you untick what is out of scope"),
            "Health": wb.Step(kind="proof", run=a_health, view="gates", agent="Checker", text="Each map validated (BPMN 2.0, connected, decisions labelled), stale and ownerless documents, duplicates, procedures with no map"),
            "Findings": wb.Step(kind="person", run=a_findings, edit=FIND_EDIT, text="The findings — you keep or ignore each one"),
            "Estimate": wb.Step(kind="deterministic", run=a_estimate, view="plan", agent="Estimator", text="The time to bring each document to the standard (BPMN + SOP), with the assumptions")}),
        "develop": wb.Work(title="From interviews, a screen recording or system logs to a BPMN map and a step-by-step SOP", platforms=("files", "filing"), schedule_from="Keep current", steps={
            "Capture": wb.Step(kind="platform", run=d_capture, agent="Reader", text="Interviews, a screen recording of someone doing the task, or system logs — passages read, recordings noted for the agent, logs mined (rules first)"),
            "Map": wb.Step(kind="agent", prompt=_map_prompt, check=_map_check, after=_map_after, view="process", agent="Process mapper", edit=MAP_EDIT, turns=60,
                           text="The agent maps it — steps, lanes, decisions, screens, fields and rules, each citing its passage or the moment of the recording; BPMN 2.0 built from it"),
            "Correct": wb.Step(kind="deterministic", run=d_correct, agent="SOP writer", edit=SOP_EDIT, text="The step-by-step SOP from the corrected map, each line next to the recording or passage it came from — the process owner corrects it"),
            "Publish": wb.Step(kind="deterministic", run=d_publish, view="plan", agent="Publisher", text="The final version — BPMN 2.0 and the Word SOP in your house style — kept with every earlier version"),
            "Automate": wb.Step(kind="deterministic", run=d_automate, agent="Automation scout", edit=AUTO_EDIT, confirm="the steps worth automating, and where the version is filed",
                                confirm_if=lambda ctx, out: bool(out.get("records")) or bool(_w4.push_of(ctx.id, "automate")),
                                text="Filed to Confluence after its own approval; the steps worth automating go to Workflows, RPA or AI SDLC in one click"),
            "Keep current": wb.Step(kind="deterministic", run=d_keep, agent="Watcher", confirm="the document, flagged because something it describes changed",
                                    confirm_if=lambda ctx, out: bool(ctx.get("flags")), text="When a system, bot or role it describes changes, the document is flagged for review")},
            fields=[wb.Field("schedule", "Check it is still current", "cadence", help="How often Relay checks the systems and roles the process describes (optional).")]),
        "change": wb.Work(title="Change a published process — what it touches, the map changed in place, proven, released", needs_source=False, steps={
            "Request": wb.Step(kind="deterministic", run=c_request, view="text", agent="Reader", text="The change in plain words, the published process, any new recording or log"),
            "Diagnose": wb.Step(kind="proof", run=c_diagnose, view="gates", agent="Checker", text="The steps the request touches, and today's map against a new log"),
            "Fix": wb.Step(kind="person", run=c_fix, view="process", edit=MAP_EDIT, text="You change the map in place; the graph rules refuse a broken one"),
            "Prove": wb.Step(kind="proof", run=c_prove, view="gates", agent="Checker", back_to="fix", text="The changed map validated as BPMN 2.0, the difference step by step, and its fit with the log"),
            "Approve": wb.Step(kind="person", run=c_approve, view="plan", approver=True, text="The named approver releases the next version"),
            "Learn": wb.Step(kind="deterministic", run=c_learn, view="plan", agent="Publisher", text="The next version is published and kept")},
            fields=[wb.Field("process", "Process to change", "select", options=process_options, required=True)]),
        "migrate": wb.Work(title="Visio, Word or slide-based process documents to BPMN and the standard SOP", platforms=("files", "filing"), steps={
            "Collect": wb.Step(kind="platform", run=d_capture, agent="Reader", text="Bring Visio, Word or slide-based process documents (and a log or recording to check against)"),
            "Convert": wb.Step(kind="deterministic", run=m_convert, view="process", agent="Converter", edit=CONVERT_EDIT, confirm="the BPMN map converted from the old document, step by step",
                               text="Visio and BPMN exports converted by rules; Word and slides drafted by the agent when you ask — you correct the map",
                               actions={"draft": wb.Action(label="Ask Relay to draft the map from the documents", kind="agent", prompt=_map_prompt, check=_map_check, after=_convert_after,
                                                           agent="Process mapper", turns=60, help="The agent reads the Word or slide procedure and writes the map, each step citing its passage.")}),
            "Check": wb.Step(kind="proof", run=m_check, view="gates", agent="Checker", back_to="convert", confirm="the converted map against how the work is really done",
                             text="Checked against how the work is really done (an event log), validated as BPMN 2.0"),
            "Publish": wb.Step(kind="deterministic", run=m_publish, view="plan", agent="Publisher", confirm="the final version before it is filed",
                               text="Published and linked to the systems and people involved")}),
    }))
