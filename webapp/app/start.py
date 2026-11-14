"""Start from an idea or a plan (build-plan v2, P10).

A person writes what they want, attaches anything - screen recordings, images, Word / PDF / slides, spreadsheets,
audio, links - and picks the connections the modules may read. The agent reads every attachment (`genbi read`,
its own Read tool for images, frames and PDFs) and writes analysis.yaml: three views a person confirms before
anything is built - the process map, the fields & rules, and the plan (which modules build what, in order, with the
checkpoints each will open). Each view is a checkpoint in the Validation queue (kind `start.view`); "Correct
something" sends it back with a comment, the agent re-reads with the correction and the views reopen. When all three
are confirmed the start is `planned`: plan.yaml is final and every checkpoint the plan promises is pre-registered
(`start_plan_checkpoints`, status upcoming) for the queue to show when its module opens it.

A start is a folder under output/projects/<id>/ like a dashboard (store.py), with `kind: start` in project.json:
request.md (the brief, every correction appended), attachments/ (+ .read/ caches), connections.json, analysis.yaml,
plan.yaml. Attachments stay in the tenant folder; recordings can be deleted once the process is confirmed (audited).
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import secrets
import shutil
import time
import traceback
from pathlib import Path

import yaml
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from genbi_kit import reader

from . import auth, checkpoints, connectors, db, notify, registry, start_prompts, store, worker

router = APIRouter()

db.register_schema("""
CREATE TABLE IF NOT EXISTS start_plan_checkpoints (
  id TEXT PRIMARY KEY, start_id TEXT NOT NULL, position INTEGER NOT NULL, module TEXT NOT NULL, module_name TEXT,
  name TEXT NOT NULL, view TEXT, status TEXT NOT NULL DEFAULT 'upcoming' CHECK (status IN ('upcoming', 'open', 'done', 'withdrawn')),
  checkpoint_id TEXT, link TEXT, created REAL NOT NULL, updated REAL);
CREATE INDEX IF NOT EXISTS start_plan_cp_start ON start_plan_checkpoints (start_id, position);
""")

KIND = "start.view"
MODULE = "Start"
VIEWS = [("process", "Process map"), ("fields", "Fields & rules"), ("plan", "Plan & modules")]
VIEW_LABEL = dict(VIEWS)
STATUS_READING = "reading"
RUNNING = {"queued", STATUS_READING}
MAX_BYTES = int(os.environ.get("D2D_START_MAX_MB", "500")) * 1024 * 1024
CHUNK = 1024 * 1024
TEST_HOOKS = os.environ.get("D2D_TEST_HOOKS") == "1"
ACTORS_AGENT = {"agent", "relay", "bot"}
RECORDINGS = {"video", "audio"}


class StartError(Exception):
    pass


# ---------------------------------------------------------------- the folder

def _safe_name(name: str, taken: set[str]) -> str:
    base = re.sub(r"[^\w.\- ]+", "_", Path(name or "file").name).strip(" ._") or "file"
    out = base
    while out.lower() in taken or out.startswith("."):
        out = "_" + out
    taken.add(out.lower())
    return out


def folder(pid: str) -> Path:
    return store.project_dir(pid)


def load(pid: str) -> dict:
    st = store.load(pid)
    if st.get("kind") != "start":
        raise KeyError(pid)
    return st


def _title(brief: str) -> str:
    words = re.sub(r"\s+", " ", brief).strip().split(" ")
    return " ".join(words[:7]).rstrip(".,;:") or "Start"


def _request_md(title: str, brief: str, attachments: list[dict], links: list[str], conns: list[dict], delete_recordings: bool) -> str:
    lines = [f"# {title}", "", "## What the person wants", "", brief.strip(), ""]
    lines += ["## Attachments (in attachments/)", ""] + ([f"- {a['name']} ({a['kind']}, {a['bytes']:,} bytes)" for a in attachments] or ["- (none)"]) + [""]
    if links:
        lines += ["## Links named in the brief", ""] + [f"- {l}" for l in links] + [""]
    lines += ["## Connections picked (read-only, for the modules to use later)", ""] + ([f"- {c['name']} ({c['label']})" for c in conns] or ["- (none)"]) + [""]
    lines += ["## Handling", "", "- Attachments stay in this tenant's folder; they are never sent anywhere else.",
              "- Recordings (video, audio) " + ("are deleted once the process is confirmed." if delete_recordings else "are kept until the person deletes them."), ""]
    return "\n".join(lines)


def attachments_state(pid: str, st: dict | None = None) -> list[dict]:
    """The attachment list with what the readers extracted (from the .read caches) for the Start page."""
    d = folder(pid)
    st = st or load(pid)
    out = []
    for a in st.get("attachments") or []:
        row = {**a}
        p = d / "attachments" / a["name"]
        row["present"] = p.exists()
        info = reader.cached(p) if p.exists() else None
        if info:
            row.update(read=True, read_at=info.get("read_at"), note=info.get("note") or "", text=(info.get("text") or "")[:6000],
                       truncated=bool(info.get("truncated")) or len(info.get("text") or "") > 6000,
                       frames=[f"attachments/{f}" for f in info.get("frames") or []], pages=info.get("pages"),
                       sheets=[{k: v for k, v in s.items() if k != "sample"} | {"sample": s.get("sample", [])[:3]} for s in info.get("sheets") or []],
                       width=info.get("width"), height=info.get("height"), meta=info.get("meta") or {}, error=bool(info.get("error")))
        else:
            row.update(read=False)
        out.append(row)
    return out


async def _save(upload: UploadFile, path: Path) -> int:
    size = 0
    with path.open("wb") as out:
        while chunk := await upload.read(CHUNK):
            out.write(chunk)
            size += len(chunk)
            if size > MAX_BYTES:
                raise HTTPException(413, f'"{upload.filename}" is larger than {MAX_BYTES // 1024 // 1024} MB.')
    return size


def _preread(d: Path, names: list[str]) -> None:
    """The web app's own readers fill the .read caches at upload time, so the Start page shows the text at once;
    the agent's `genbi read` (with ffmpeg for frames) refreshes them when it runs. Best effort."""
    for n in names:
        try:
            reader.read(d / "attachments" / n)
        except Exception:  # noqa: BLE001 - a file the reader cannot open is shown as such, never a failed upload
            traceback.print_exc()


# ---------------------------------------------------------------- analysis.yaml: schema check, views, checkpoints

def load_analysis(d: Path) -> dict | None:
    p = d / "analysis.yaml"
    if not p.exists():
        return None
    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    return raw if isinstance(raw, dict) else None


def _num(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def check_analysis(d: Path) -> list[str]:
    """What is wrong with analysis.yaml (empty = fine). Unknown module ids, confidences outside 0-1, empty views and
    missing keys are problems the agent fixes in a resumed session, as worker._plan does for plan.yaml."""
    p = d / "analysis.yaml"
    if not p.exists():
        return ["analysis.yaml was not written"]
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        return [f"analysis.yaml does not parse: {str(e).splitlines()[0][:200]}"]
    if not isinstance(raw, dict):
        return ["analysis.yaml must be a mapping with process, fields and plan"]
    problems: list[str] = []
    proc = raw.get("process")
    steps = (proc or {}).get("steps") if isinstance(proc, dict) else None
    if not isinstance(steps, list) or not steps:
        problems.append("process.steps is empty - list the steps as the attachments show them")
    else:
        ids: set[str] = set()
        for i, s in enumerate(steps, 1):
            if not isinstance(s, dict):
                problems.append(f"process.steps[{i}] must be a mapping")
                continue
            sid = str(s.get("id") or "").strip()
            if not sid:
                problems.append(f"process.steps[{i}] needs an id")
            elif sid in ids:
                problems.append(f"process step id {sid} is used twice")
            ids.add(sid)
            for k in ("actor", "action"):
                if not str(s.get(k) or "").strip():
                    problems.append(f"process step {sid or i} needs {k}")
            if s.get("fields") is not None and not isinstance(s.get("fields"), list):
                problems.append(f"process step {sid or i}: fields must be a list")
        for i, hnd in enumerate((proc or {}).get("handoffs") or [], 1):
            if not isinstance(hnd, dict):
                problems.append(f"process.handoffs[{i}] must be a mapping with from and to")
                continue
            for k in ("from", "to"):
                if str(hnd.get(k) or "") not in ids:
                    problems.append(f"process.handoffs[{i}].{k} ({hnd.get(k)}) is not a step id")
    fields = raw.get("fields")
    if not isinstance(fields, list) or not fields:
        problems.append("fields is empty - list every field, value and rule found")
    else:
        for i, f in enumerate(fields, 1):
            if not isinstance(f, dict) or not str(f.get("field") or "").strip():
                problems.append(f"fields[{i}] needs a field name")
                continue
            c = _num(f.get("confidence"))
            if c is None or not 0 <= c <= 1:
                problems.append(f"field {f['field']}: confidence must be a number between 0 and 1 (got {f.get('confidence')!r})")
    plan = raw.get("plan")
    mods = (plan or {}).get("modules") if isinstance(plan, dict) else None
    if not isinstance(mods, list) or not mods:
        problems.append("plan.modules is empty - list the modules that build this, in order")
    else:
        for i, m in enumerate(mods, 1):
            if not isinstance(m, dict):
                problems.append(f"plan.modules[{i}] must be a mapping")
                continue
            mid = str(m.get("id") or "").strip()
            mod = registry.BY_ID.get(mid)
            if not mod or mod["pl"] in ("hidden", "platform"):
                problems.append(f"plan module {mid or i}: unknown module id (use one of the ids listed in the stage prompt)")
            if not str(m.get("builds") or "").strip():
                problems.append(f"plan module {mid or i} needs `builds`")
            cps = m.get("checkpoints")
            if not isinstance(cps, list) or not [c for c in cps if str(c or "").strip()]:
                problems.append(f"plan module {mid or i} needs at least one checkpoint name")
    return problems


def views(raw: dict | None) -> dict:
    """The three views, shaped for the page and the queue."""
    raw = raw or {}
    proc = raw.get("process") if isinstance(raw.get("process"), dict) else {}
    steps = []
    for s in proc.get("steps") or []:
        if isinstance(s, dict):
            actor = str(s.get("actor") or "")
            steps.append({"id": str(s.get("id") or ""), "actor": actor, "kind": "agent" if actor.strip().lower() in ACTORS_AGENT else "person",
                          "screen": str(s.get("screen") or ""), "action": str(s.get("action") or ""),
                          "fields": [str(x) for x in (s.get("fields") or []) if x is not None] if isinstance(s.get("fields"), list) else [],
                          "decision": str(s.get("decision") or ""), "rule": str(s.get("rule") or "")})
    handoffs = [{"from": str(x.get("from") or ""), "to": str(x.get("to") or ""), "when": str(x.get("when") if x.get("when") is not None else "")}
                for x in proc.get("handoffs") or [] if isinstance(x, dict)]
    fields = []
    for f in raw.get("fields") or []:
        if isinstance(f, dict):
            c = _num(f.get("confidence"))
            fields.append({"field": str(f.get("field") or ""), "source": str(f.get("source") or ""), "type": str(f.get("type") or ""),
                           "rule": str(f.get("rule") or ""), "example": str(f.get("example") if f.get("example") is not None else ""),
                           "confidence": round(c, 3) if c is not None else None, "where": str(f.get("where") or "")})
    plan = raw.get("plan") if isinstance(raw.get("plan"), dict) else {}
    modules = []
    for i, m in enumerate(plan.get("modules") or [], 1):
        if isinstance(m, dict):
            mod = registry.BY_ID.get(str(m.get("id") or ""))
            modules.append({"position": i, "id": str(m.get("id") or ""), "name": mod["name"] if mod else str(m.get("id") or ""),
                            "known": bool(mod), "builds": str(m.get("builds") or ""),
                            "checkpoints": [str(c) for c in (m.get("checkpoints") or []) if str(c or "").strip()] if isinstance(m.get("checkpoints"), list) else [],
                            "state": mod["status"] if mod else "unknown", "route": (mod or {}).get("route")})
    return {"summary": str(raw.get("summary") or ""),
            "process": {"steps": steps, "handoffs": handoffs, "counts": {"steps": len(steps), "decisions": sum(1 for s in steps if s["decision"]),
                                                                        "handoffs": len(handoffs), "agent_steps": sum(1 for s in steps if s["kind"] == "agent")}},
            "fields": {"rows": fields, "counts": {"fields": len(fields), "rules": sum(1 for f in fields if f["rule"]),
                                                  "low_confidence": sum(1 for f in fields if f["confidence"] is not None and f["confidence"] < 0.8)}},
            "plan": {"modules": modules, "estimate": str(plan.get("estimate") or ""), "hours_saved_month": _num(plan.get("hours_saved_month")),
                     "counts": {"modules": len(modules), "checkpoints": sum(len(m["checkpoints"]) for m in modules)}}}


def evidence(view: str, v: dict) -> dict:
    """What the Validation queue shows for a view: its rows and counts."""
    if view == "process":
        p = v["process"]
        return {"summary": f"{p['counts']['steps']} steps, {p['counts']['decisions']} decision(s), {p['counts']['handoffs']} hand-off(s); {p['counts']['agent_steps']} step(s) for an agent",
                "counts": p["counts"], "items": [f"{s['id']} - {s['actor']}: {s['action']}" + (f" - {s['decision']}" if s["decision"] else "") for s in p["steps"][:8]],
                "rows": p["steps"][:60]}
    if view == "fields":
        f = v["fields"]
        return {"summary": f"{f['counts']['fields']} fields and values, {f['counts']['rules']} rule(s); {f['counts']['low_confidence']} below 80 % confidence",
                "counts": f["counts"], "items": [f"{r['field']}: {r['example'] or '-'}" + (f" ({round(r['confidence'] * 100)} %)" if r["confidence"] is not None else "") for r in f["rows"][:8]],
                "rows": f["rows"][:80]}
    p = v["plan"]
    return {"summary": f"{p['counts']['modules']} module(s), {p['counts']['checkpoints']} checkpoint(s)" + (f"; estimate {p['estimate']}" if p["estimate"] else ""),
            "counts": p["counts"], "items": [f"{m['position']}. {m['name']}: {m['builds']} - you confirm {', '.join(m['checkpoints'])}" for m in p["modules"][:8]],
            "rows": p["modules"]}


def _owner(pid: str) -> str | None:
    p = db.project(pid)
    return p["owner_id"] if p else None


def open_views(pid: str, st: dict) -> list[dict]:
    """Withdraw what was open for this start and open the three views as checkpoints."""
    checkpoints.withdraw(KIND, pid, who="system")
    v = views(load_analysis(folder(pid)))
    out = []
    for view, label in VIEWS:
        out.append(checkpoints.open(KIND, pid, MODULE, f"{label}: {st.get('name') or pid}", view, evidence(view, v),
                                    link=f"#/start/{pid}", assignee=_owner(pid), agent="Relay reader", opened_by="agent"))
    return out


def analysed(pid: str, summary: str = "") -> dict:
    """analysis.yaml passed the check: store it, show the views, wait for the person (also the test hook's path)."""
    d = folder(pid)
    problems = check_analysis(d)
    if problems:
        raise StartError("; ".join(problems[:4]))
    st = load(pid)
    for a in st.get("attachments") or []:
        a["read"] = reader.cached(d / "attachments" / a["name"]) is not None
    v = views(load_analysis(d))
    st.update(status="awaiting_confirmation", job=None, error=None, confirmed={}, analysis_summary=summary or st.get("analysis_summary") or "",
              analysis_rounds=(st.get("analysis_rounds") or 0) + 1, analysed=time.time(),
              counts={"steps": v["process"]["counts"]["steps"], "fields": v["fields"]["counts"]["fields"], "modules": v["plan"]["counts"]["modules"]})
    store.save(st)
    open_views(pid, st)
    worker.app_note(pid, "start_read", f"Relay read {sum(1 for a in st['attachments'] if a.get('read'))} of {len(st['attachments'])} attachment(s): "
                    f"{v['process']['counts']['steps']} steps, {v['fields']['counts']['fields']} fields and rules, {v['plan']['counts']['modules']} modules. "
                    "Waiting for you to confirm the three views.", "ok")
    db.audit("start.analysed", pid, {"rounds": st["analysis_rounds"], **st["counts"]}, "agent")
    return st


# ---------------------------------------------------------------- the job (one run in the lane, fix rounds, correction re-runs)

async def _read(pid: str, args: dict) -> None:
    d = folder(pid)
    st = load(pid)
    correction, view = args.get("correction"), args.get("view")
    worker.app_note(pid, "start_read", f"Relay is reading the attachments again with your correction to the {VIEW_LABEL.get(view, 'analysis').lower()}."
                    if correction else f"Relay is reading your brief and {len(st.get('attachments') or [])} attachment(s): documents, sheets, images and recordings.")
    names = []
    for cid in st.get("connections") or []:
        try:
            c = connectors._row(cid)
            names.append(f"{c['name']} ({connectors.KINDS.get(c['kind'], {}).get('label', c['kind'])})")
        except connectors.ConnectorError:
            pass
    prompt = start_prompts.read(st, d, correction, view, names)
    res = await worker.agent(pid, "start_read", prompt, worker.TURNS["start_read"], "analysis", system=start_prompts.SYSTEM)
    for attempt in range(worker.FIX_ROUNDS + 1):
        problems = await asyncio.to_thread(check_analysis, d)
        if not problems:
            break
        if attempt == worker.FIX_ROUNDS:
            raise RuntimeError(f"analysis.yaml still has {len(problems)} problem(s): " + "; ".join(problems[:4]))
        worker.app_note(pid, "start_read", f"The check found {len(problems)} problem(s) in analysis.yaml - Relay is fixing them.", "warn", problems)
        res = await worker.agent(pid, "start_read", start_prompts.fix(problems), worker.TURNS["fix"], "analysis", resume=res.get("session_id"),
                                 system=start_prompts.SYSTEM)
    analysed(pid, res.get("text") or "")


worker.register_job("start_read", _read, status=STATUS_READING, done="Relay read your start - confirm the three views", llm=True, turns=80, timeout_s=2400)


# ---------------------------------------------------------------- decisions: confirm, correct, planned

def correct(pid: str, view: str, comment: str, who: str) -> dict:
    """A correction: appended to request.md, every open view withdrawn, the agent re-reads with it."""
    st = load(pid)
    comment = " ".join(comment.split())[:2000]
    store.note(pid, f"Correction to the {VIEW_LABEL.get(view, view).lower()}", comment)
    store.log(pid, {"kind": "user", "stage": "start_read", "text": f"Correction to the {VIEW_LABEL.get(view, view).lower()}: {comment}"})
    st.setdefault("corrections", []).append({"view": view, "comment": comment, "who": who, "when": time.time()})
    st["confirmed"] = {}
    store.save(st)
    checkpoints.withdraw(KIND, pid, who=who)
    db.audit("start.correct", pid, {"view": view, "comment": comment[:300]}, who)
    return worker.enqueue(pid, "start_read", correction=comment, view=view)


def _checkpoint_rows(pid: str, st: dict, v: dict) -> list[dict]:
    db.run("DELETE FROM start_plan_checkpoints WHERE start_id = ?", (pid,))
    rows, pos, now = [], 0, time.time()
    for m in v["plan"]["modules"]:
        mod = registry.BY_ID.get(m["id"]) or {}
        view = "prototype" if m["id"] in ("bi", "d2d") else "plan"
        for name in m["checkpoints"]:
            pos += 1
            rid = "sp-" + secrets.token_hex(5)
            link = "#/p/" + st["dashboard"] if st.get("dashboard") and m["id"] in ("bi", "d2d") else (mod.get("route") if mod.get("status") == "available" else f"#/m/{m['id']}")
            db.run("INSERT INTO start_plan_checkpoints (id, start_id, position, module, module_name, name, view, status, link, created) "
                   "VALUES (?, ?, ?, ?, ?, ?, ?, 'upcoming', ?, ?)", (rid, pid, pos, m["id"], m["name"], name, view, link, now))
            rows.append({"id": rid, "position": pos, "module": m["id"], "module_name": m["name"], "name": name, "status": "upcoming", "link": link})
    return rows


def promised(pid: str) -> list[dict]:
    """The checkpoints a planned start promises, in order (upcoming until their module opens them)."""
    return db.q("SELECT * FROM start_plan_checkpoints WHERE start_id = ? ORDER BY position", (pid,))


def link_checkpoint(pid: str, module: str, name: str, checkpoint_id: str | None, status: str = "open") -> int:
    """For the modules that run a start's plan later (P12 onwards): mark a promised checkpoint open / done."""
    return db.run("UPDATE start_plan_checkpoints SET status = ?, checkpoint_id = COALESCE(?, checkpoint_id), updated = ? "
                  "WHERE start_id = ? AND module = ? AND lower(name) = lower(?)", (status, checkpoint_id, time.time(), pid, module, name))


def delete_recordings(pid: str, who: str) -> list[str]:
    d = folder(pid)
    st = load(pid)
    gone = []
    for a in st.get("attachments") or []:
        if a.get("kind") in RECORDINGS and not a.get("deleted"):
            p = d / "attachments" / a["name"]
            p.unlink(missing_ok=True)
            reader.cache_path(p).unlink(missing_ok=True)
            shutil.rmtree(p.parent / reader.CACHE_DIR / (a["name"] + ".frames"), ignore_errors=True)
            a["deleted"] = time.time()
            a["read"] = False
            gone.append(a["name"])
    if gone:
        st["recordings_deleted"] = time.time()
        store.save(st)
        store.note(pid, "Recordings deleted", "\n".join(f"- {n}" for n in gone))
        store.log(pid, {"kind": "user", "stage": "start", "text": f"Deleted {len(gone)} recording(s): " + ", ".join(gone)})
        db.audit("start.recordings_deleted", pid, {"files": gone}, who)
    return gone


def finalise(pid: str, who: str) -> dict:
    """All three views confirmed: the plan is final, its checkpoints are promised, the person is told what is next."""
    d = folder(pid)
    st = load(pid)
    v = views(load_analysis(d))
    plan = {"start": pid, "name": st.get("name"), "planned": time.time(), "planned_by": who, "summary": v["summary"],
            "confirmations": {k: {"by": c.get("by"), "when": c.get("when")} for k, c in (st.get("confirmed") or {}).items()},
            "modules": [{"position": m["position"], "id": m["id"], "name": m["name"], "builds": m["builds"], "checkpoints": m["checkpoints"]} for m in v["plan"]["modules"]],
            "estimate": v["plan"]["estimate"] or None, "hours_saved_month": v["plan"]["hours_saved_month"],
            "connections": st.get("connections") or [], "attachments": [a["name"] for a in st.get("attachments") or []]}
    (d / "plan.yaml").write_text(yaml.safe_dump(plan, sort_keys=False, allow_unicode=True, width=110), encoding="utf-8")
    rows = _checkpoint_rows(pid, st, v)
    st.update(status="planned", planned=time.time(), planned_by=who, plan_final=True, job=None)
    store.save(st)
    store.note(pid, "Plan confirmed", "All three views were confirmed; plan.yaml is final:\n"
               + "\n".join(f"- {m['position']}. {m['name']}: {m['builds']} (you confirm {', '.join(m['checkpoints'])})" for m in v["plan"]["modules"]))
    worker.app_note(pid, "start", f"Planned: {len(v['plan']['modules'])} module(s), {len(rows)} checkpoint(s) promised - each appears in your validation "
                    "queue when its module opens it.", "ok")
    db.audit("start.planned", pid, {"modules": [m["id"] for m in v["plan"]["modules"]], "checkpoints": len(rows)}, who)
    owner = _owner(pid)
    if owner and owner != who:
        notify.add(owner, "review", f"Plan confirmed: {st.get('name')}", f"{len(rows)} checkpoints promised", f"#/start/{pid}")
    if st.get("delete_recordings"):
        delete_recordings(pid, who)
    return load(pid)


def _on_decision(c: dict, decision: str, comment: str | None, who: str) -> None:
    pid, view = c["subject"], c["view"]
    try:
        st = load(pid)
    except (KeyError, FileNotFoundError):
        return
    if decision == "accept":
        st.setdefault("confirmed", {})[view] = {"by": who, "when": time.time(), "checkpoint": c["id"]}
        store.save(st)
        store.log(pid, {"kind": "user", "stage": "start", "text": f"Confirmed the {VIEW_LABEL.get(view, view).lower()}" + (f" - {comment}" if comment else "")})
        db.audit("start.confirm", pid, {"view": view, "checkpoint": c["id"]}, who)
        if st["status"] == "awaiting_confirmation" and all(v in st["confirmed"] for v, _ in VIEWS):
            finalise(pid, who)
    else:
        if st["status"] in RUNNING:
            return
        correct(pid, view, comment or "", who)


checkpoints.register_kind(KIND, "Start: confirm a view", _on_decision)


# ---------------------------------------------------------------- the dashboard a plan starts (D2D, through POST /api/projects)

def _sheet_csvs(d: Path, st: dict) -> list[tuple[str, Path]]:
    """The spreadsheet attachments as CSVs for the dashboard: a CSV as it is, an xlsx sheet by sheet (openpyxl)."""
    out = []
    tmp = d / ".dashboard-tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir()
    for a in st.get("attachments") or []:
        p = d / "attachments" / a["name"]
        if a.get("kind") != "sheet" or not p.exists():
            continue
        if p.suffix.lower() == ".csv":
            out.append((p.name, p))
            continue
        import csv

        import openpyxl
        wb = openpyxl.load_workbook(str(p), read_only=True, data_only=True)
        for ws in wb.worksheets:
            rows = [list(r) for r in ws.iter_rows(values_only=True)]
            rows = [r for r in rows if any(v is not None and v != "" for v in r)]
            if len(rows) < 2:
                continue
            name = re.sub(r"[^\w\-]+", "_", f"{p.stem}_{ws.title}" if len(wb.worksheets) > 1 else p.stem).strip("_") + ".csv"
            with (tmp / name).open("w", encoding="utf-8", newline="") as fh:
                w = csv.writer(fh)
                for r in rows:
                    w.writerow(["" if v is None else (v.isoformat() if hasattr(v, "isoformat") else v) for v in r])
            out.append((name, tmp / name))
        wb.close()
    return out


async def start_dashboard(pid: str, who: str) -> dict:
    from . import main
    d = folder(pid)
    st = load(pid)
    if st["status"] != "planned":
        raise HTTPException(409, "Confirm the three views first: the dashboard starts from the confirmed plan.")
    if st.get("dashboard"):
        raise HTTPException(409, "This start already has its dashboard.")
    v = views(load_analysis(d))
    item = next((m for m in v["plan"]["modules"] if m["id"] in ("bi", "d2d")), None)
    if not item:
        raise HTTPException(409, "The plan has no BI & dashboards item.")
    sheets = _sheet_csvs(d, st)
    prompt = (f"{st.get('prompt', '').strip()}\n\nThis dashboard comes from the start \"{st.get('name')}\" (#/start/{pid}); the confirmed plan says: "
              f"{item['builds']}. Process steps and fields the person confirmed are in that start's analysis.")
    handles = []
    try:
        files = []
        for name, path in sheets:
            fh = path.open("rb")
            handles.append(fh)
            files.append(UploadFile(file=fh, filename=name))
        generate = not files
        proj = await main.create_project(prompt=prompt, name=st.get("name") or "", model="", look="", brand="", palette="", dark="", custom_visuals="ask",
                                         data_mode="generate" if generate else "upload", data_brief=st.get("prompt", "") if generate else "",
                                         data_size="small", data_months=12, connection_id="", tables="", visuals_mode="relay", files=files, images=[])
    finally:
        for fh in handles:
            fh.close()
        shutil.rmtree(d / ".dashboard-tmp", ignore_errors=True)
    st = load(pid)
    st["dashboard"] = proj["id"]
    store.save(st)
    db.run("UPDATE start_plan_checkpoints SET status = 'open', link = ?, updated = ? WHERE start_id = ? AND module IN ('bi', 'd2d')",
           ("#/p/" + proj["id"], time.time(), pid))
    store.note(pid, "Dashboard started", f"Dashboard {proj['name']} ({proj['id']}) created from this start" + (" with the spreadsheet attachments." if sheets else " on generated demo data."))
    store.log(pid, {"kind": "user", "stage": "start", "text": f"Started the dashboard {proj['name']}"})
    db.audit("start.dashboard", pid, {"project": proj["id"], "sheets": [n for n, _ in sheets]}, who)
    return proj


# ---------------------------------------------------------------- state for the page

def _next(st: dict, v: dict) -> list[dict]:
    rows = promised(st["id"]) if st.get("status") == "planned" else []
    out = []
    for m in v["plan"]["modules"]:
        mod = registry.BY_ID.get(m["id"]) or {}
        state = registry.state_of(mod, registry.brand()["edition"]) if mod else "unknown"
        link = ("#/p/" + st["dashboard"]) if st.get("dashboard") and m["id"] in ("bi", "d2d") else (mod.get("route") if state == "available" else f"#/m/{m['id']}") if mod else None
        out.append({**m, "state": state, "link": link, "live": state in ("available", "partly"),
                    "promised": [{k: r[k] for k in ("id", "name", "status", "link")} for r in rows if r["module"] == m["id"]],
                    "can_start_dashboard": m["id"] in ("bi", "d2d") and st.get("status") == "planned" and not st.get("dashboard")})
    return out


def state(pid: str, u: dict | None = None) -> dict:
    st = load(pid)
    d = folder(pid)
    v = views(load_analysis(d)) if (d / "analysis.yaml").exists() else None
    cps = [checkpoints._public(r) for r in db.q("SELECT * FROM checkpoints WHERE kind = ? AND subject = ? AND status = 'open'", (KIND, pid))]
    p = db.project(pid)
    names = {x["id"]: x["name"] for x in db.q("SELECT id, name FROM users")}
    conns = []
    for cid in st.get("connections") or []:
        try:
            c = connectors._row(cid)
            conns.append({"id": cid, "name": c["name"], "kind": c["kind"], "label": connectors.KINDS.get(c["kind"], {}).get("label", c["kind"]), "status": c["status"]})
        except connectors.ConnectorError:
            conns.append({"id": cid, "name": "(removed)", "kind": "", "label": "", "status": "gone"})
    out = {**st, "attachments": attachments_state(pid, st), "analysis": v, "open_checkpoints": {c["view"]: c["id"] for c in cps},
           "position": worker.position(pid) if st["status"] == "queued" else 0,
           "running_since": worker.running_since(pid),
           "connection_details": conns, "owner": p["owner_id"] if p else None, "owner_name": names.get(p["owner_id"]) if p else None,
           "confirmed": {k: {**c, "by_name": names.get(c.get("by"), c.get("by"))} for k, c in (st.get("confirmed") or {}).items()},
           "next": _next(st, v) if v else [], "promised": promised(pid) if st.get("status") == "planned" else [],
           "has_recordings": any(a.get("kind") in RECORDINGS and not a.get("deleted") for a in st.get("attachments") or []),
           "test_hooks": TEST_HOOKS}
    if u is not None:
        out["access"] = {"can_edit": auth.can_project(u, "edit", p), "can_view": auth.can_project(u, "view", p)}
    return out


def summary(pid: str) -> dict:
    st = load(pid)
    return {k: st.get(k) for k in ("id", "name", "status", "created", "updated", "planned", "counts", "dashboard", "analysis_rounds")} | \
           {"attachments": len(st.get("attachments") or []), "confirmed": len(st.get("confirmed") or {}), "prompt": (st.get("prompt") or "")[:200]}


def all_starts() -> list[dict]:
    return [p for p in store.all_projects() if p.get("kind") == "start"]


# ---------------------------------------------------------------- API

def _u() -> dict:
    u = auth.current.get()
    if not u:
        raise HTTPException(401, "Sign in.")
    return u


def _get(pid: str, action: str = "view") -> tuple[dict, dict]:
    u = _u()
    try:
        st = load(pid)
    except (KeyError, FileNotFoundError, ValueError):
        raise HTTPException(404, "No such start.")
    p = db.project(pid)
    if not auth.can_project(u, "view", p):
        raise HTTPException(404, "No such start.")
    if action != "view" and not (auth.can_project(u, "edit", p) and auth.is_dev(u)):
        raise HTTPException(403, "You can look at this start, but only its owner or a builder it is shared with can change it.")
    return u, st


@router.get("/api/start")
def list_starts():
    u = _u()
    ids = [p["id"] for p in all_starts()]
    access = auth.access_map(u, ids)
    out = []
    for pid in ids:
        if pid in access:
            try:
                out.append({**summary(pid), "access": access[pid]["access"]})
            except (KeyError, FileNotFoundError, ValueError):
                continue
    return {"starts": sorted(out, key=lambda s: -(s.get("created") or 0)), "can_start": auth.is_dev(u), "kinds": {k: sorted(v) for k, v in reader.KINDS.items()}}


@router.post("/api/start")
async def create_start(brief: str = Form(...), name: str = Form(""), links: str = Form(""), connections: str = Form("[]"),
                       delete_recordings_after: str = Form(""), files: list[UploadFile] = File(default=[])):
    u = _u()
    if not auth.is_dev(u):
        raise HTTPException(403, "Only builders and admins can start work; ask one to start it for you.")
    brief = brief.strip()
    if len(brief) < 10:
        raise HTTPException(400, "Describe what you want in a sentence or two.")
    files = [f for f in files if f.filename]
    bad = [f.filename for f in files if Path(f.filename).suffix.lower() not in reader.EXTENSIONS]
    if bad:
        raise HTTPException(400, f"Not a kind of file Relay reads: {', '.join(bad[:3])}. Attach video (mp4, webm, mov), audio (mp3, wav, m4a), images (png, jpg, webp), "
                                 "PDF, Word (docx), Excel (xlsx) or CSV, PowerPoint (pptx), or text.")
    try:
        picked = [str(c) for c in json.loads(connections or "[]")]
    except ValueError:
        picked = []
    conns = []
    for cid in dict.fromkeys(picked):
        try:
            c = connectors.connection(cid, u["id"])
        except connectors.ConnectorError:
            raise HTTPException(400, "One of the connections is not yours or shared with you.")
        conns.append({"id": cid, "name": c["name"], "label": connectors.KINDS.get(c["kind"], {}).get("label", c["kind"])})
    link_list = [l.strip() for l in re.split(r"[\n,]+", links or "") if l.strip()]
    title = name.strip()[:80] or _title(brief)
    pid = store.new_id(title)
    d = store.ROOT / pid
    (d / "attachments").mkdir(parents=True)
    taken: set[str] = set()
    attachments = []
    try:
        for f in files:
            n = _safe_name(f.filename, taken)
            size = await _save(f, d / "attachments" / n)
            attachments.append({"name": n, "kind": reader.kind_of(n), "bytes": size, "read": False})
    except BaseException:
        shutil.rmtree(d, ignore_errors=True)
        raise
    delete_after = delete_recordings_after.strip().lower() in ("1", "true", "on", "yes")
    (d / "request.md").write_text(_request_md(title, brief, attachments, link_list, conns, delete_after), encoding="utf-8")
    (d / "connections.json").write_text(json.dumps({"connections": [c["id"] for c in conns], "picked_by": u["id"], "when": time.time()}, indent=2), encoding="utf-8")
    store.save({"id": pid, "kind": "start", "name": title, "prompt": brief, "model": worker.DEFAULT_MODEL, "created": time.time(), "status": "queued",
                "attachments": attachments, "links": link_list, "connections": [c["id"] for c in conns], "delete_recordings": delete_after,
                "confirmed": {}, "corrections": [], "versions": [], "runs": [], "files": [], "job": None, "error": None, "analysis_rounds": 0})
    db.add_project(pid, u["id"])
    db.audit("start.create", pid, {"name": title, "attachments": [a["name"] for a in attachments], "connections": [c["id"] for c in conns],
                                   "links": len(link_list), "delete_recordings": delete_after}, u["id"])
    store.log(pid, {"kind": "user", "stage": "start", "text": f"Started \"{title}\" with {len(attachments)} attachment(s)"})
    await asyncio.to_thread(_preread, d, [a["name"] for a in attachments])
    for a in attachments:
        a["read"] = reader.cached(d / "attachments" / a["name"]) is not None
    store.update(pid, attachments=attachments)
    worker.enqueue(pid, "start_read")
    return state(pid, u)


@router.get("/api/start/{pid}")
def get_start(pid: str):
    u, _ = _get(pid)
    return state(pid, u)


@router.get("/api/start/{pid}/activity")
def start_activity(pid: str, after: int = 0):
    _get(pid)
    return store.activity(pid, after)


@router.get("/api/start/{pid}/file/{path:path}")
def start_file(pid: str, path: str):
    _get(pid)
    base = (folder(pid) / "attachments").resolve()
    target = (base / path).resolve()
    if base not in target.parents or not target.is_file():
        raise HTTPException(404, "No such attachment.")
    return FileResponse(target, headers={"Cache-Control": "private, no-store"})


class Comment(BaseModel):
    comment: str = ""


def _open_view(pid: str, view: str) -> dict:
    if view not in VIEW_LABEL:
        raise HTTPException(404, "No such view.")
    c = db.one("SELECT * FROM checkpoints WHERE kind = ? AND subject = ? AND view = ? AND status = 'open'", (KIND, pid, view))
    if not c:
        raise HTTPException(409, "This view is not waiting for a decision right now.")
    return checkpoints._public(c)


@router.post("/api/start/{pid}/views/{view}/confirm")
def confirm_view(pid: str, view: str, body: Comment | None = None):
    u, st = _get(pid, "edit")
    if st["status"] != "awaiting_confirmation":
        raise HTTPException(409, f"Nothing to confirm right now (status: {st['status']}).")
    c = _open_view(pid, view)
    checkpoints.decide(c["id"], "accept", u["id"], body.comment if body else None)
    return state(pid, u)


@router.post("/api/start/{pid}/views/{view}/correct")
def correct_view(pid: str, view: str, body: Comment):
    u, st = _get(pid, "edit")
    if st["status"] != "awaiting_confirmation":
        raise HTTPException(409, f"Nothing to correct right now (status: {st['status']}).")
    if not body.comment.strip():
        raise HTTPException(400, "Say what is wrong, so Relay can re-read with it.")
    c = _open_view(pid, view)
    checkpoints.decide(c["id"], "send_back", u["id"], body.comment)
    return state(pid, u)


@router.post("/api/start/{pid}/retry")
def retry_start(pid: str):
    u, st = _get(pid, "edit")
    if st["status"] != "error":
        raise HTTPException(409, "Nothing to retry.")
    job = st.get("job") or {}
    store.log(pid, {"kind": "user", "stage": "start_read", "text": "Retry"})
    worker.enqueue(pid, "start_read", **{k: v for k, v in job.items() if k in ("correction", "view")})
    return state(pid, u)


@router.post("/api/start/{pid}/recordings/delete")
def remove_recordings(pid: str):
    u, st = _get(pid, "edit")
    if st["status"] not in ("planned", "awaiting_confirmation") or not all(v in (st.get("confirmed") or {}) for v in ("process",)):
        raise HTTPException(409, "Confirm the process map first: the recordings are what it was read from.")
    gone = delete_recordings(pid, u["id"])
    if not gone:
        raise HTTPException(409, "There are no recordings to delete.")
    return state(pid, u)


@router.post("/api/start/{pid}/dashboard")
async def start_dashboard_api(pid: str):
    u, _ = _get(pid, "edit")
    proj = await start_dashboard(pid, u["id"])
    return {"start": state(pid, u), "project": {"id": proj["id"], "name": proj["name"], "status": proj["status"]}}


@router.delete("/api/start/{pid}")
def delete_start(pid: str):
    u, st = _get(pid, "edit")
    if st["status"] in RUNNING and worker.is_running(pid):
        raise HTTPException(409, "Relay is reading it - stop it first.")
    checkpoints.withdraw(KIND, pid, who=u["id"])
    db.run("DELETE FROM start_plan_checkpoints WHERE start_id = ?", (pid,))
    db.skip_queued(pid)
    shutil.rmtree(folder(pid), ignore_errors=True)
    db.run("DELETE FROM shares WHERE project_id = ?", (pid,))
    db.run("DELETE FROM projects WHERE id = ?", (pid,))
    db.audit("start.delete", pid, {"name": st.get("name")}, u["id"])
    return {"ok": True}


class AnalysisBody(BaseModel):
    yaml: str
    summary: str = ""


@router.post("/api/start/{pid}/analysis")
def test_hook_analysis(pid: str, body: AnalysisBody):
    """Tests only (D2D_TEST_HOOKS=1): an analysis written by a test stands in for the agent run."""
    if not TEST_HOOKS:
        raise HTTPException(404, "Not found")
    u, st = _get(pid, "edit")
    d = folder(pid)
    (d / "analysis.yaml").write_text(body.yaml, encoding="utf-8")
    problems = check_analysis(d)
    if problems:
        raise HTTPException(400, "; ".join(problems))
    if worker.is_running(pid):
        raise HTTPException(409, "The agent is running for this start.")
    db.skip_queued(pid)
    analysed(pid, body.summary)
    return state(pid, u)
