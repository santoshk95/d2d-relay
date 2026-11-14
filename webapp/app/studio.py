"""Proposals, decks & documents - the consulting studio (build-plan v2, P11).

A studio item is a folder output/projects/<id>/ with `kind: deliverable` in project.json: brief.md (what, for whom,
by when, template; every later comment appended), sources/ (the facts the agent may use: snapshots of picked
dashboards, starts, RFP responses, the practice pulse, the registry's module facts, library items, attachments
read with the P10 reader, brand.json + the tenant template files), outline.yaml, deck.yaml or doc.yaml, builds/vN/
(the .pptx / .docx, the HTML twin, the PDF, check.json). Journey Brief -> Outline -> Draft -> Check -> Review -> Final:

  Brief     POST /api/studio - type, audience, due date, template, sources, files; queues `studio_outline`
  Outline   job studio_outline (llm) -> outline.yaml; checkpoint `studio.outline` (view plan): the person reorders,
            cuts, adds (PUT .../outline) and confirms, or sends it back with a comment (the agent re-outlines)
  Draft     job studio_draft (llm) -> deck.yaml / doc.yaml; the app builds and checks it (genbi_kit.docs); failing
            checks go back to the same session (fix rounds); the build is builds/vN/
  Check     the check report on the page (sources, numbers vs source, placeholders, limits, contrast, alt text,
            house style, tenant boundary)
  Review    checkpoint `studio.final` (view link -> the HTML twin + PDF); comments in place; send back = another draft
            round with the comment
  Final     files downloadable; "File to ..." through a write-scoped connection (connectors.request_write -> a
            `connection.write` checkpoint); "Send by mail" through the mailer, only after the final is accepted;
            later edits to the YAML (PUT .../yaml) re-run the checks and reopen the review.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import re
import shutil
import time
import traceback
from pathlib import Path

import httpx
import yaml
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

from genbi_kit import reader
from genbi_kit.docs import build as docs_build
from genbi_kit.docs import checks as docs_checks
from genbi_kit.docs import spec as docs_spec
from genbi_kit.docs.sources import Resolver

from . import auth, checkpoints, connectors, db, home, mailer, notify, registry, start, store, studio_prompts, worker

router = APIRouter()

KIND = "deliverable"
MODULE = "Studio"
ROUTE = "#/studio"
CP_OUTLINE, CP_FINAL = "studio.outline", "studio.final"
TYPES = [("proposal", "Proposal & submission deck", "deck"), ("architecture", "Architecture deck", "deck"), ("hld", "HLD / LLD", "doc"),
         ("business_case", "Business case", "doc"), ("strategy", "Strategy & roadmap deck", "deck"), ("sow", "Statement of work (SoW)", "doc"),
         ("steering", "Steering pack", "deck"), ("handover", "Hand-over pack", "doc"), ("service_report", "Monthly service report", "doc"),
         ("case_study", "Case study", "doc")]
TYPE_BY_ID = {t[0]: t for t in TYPES}
MODULE_TYPE = {"architecture": "architecture", "strategy": "strategy", "assess": "proposal", "delivery": "steering", "rfp": "proposal"}
STATUS_LABEL = {"queued": "Queued", "outlining": "Relay is outlining", "awaiting_outline": "Your turn: the outline", "drafting": "Relay is drafting",
                "building": "Building and checking", "awaiting_review": "Your turn: review the draft", "final": "Final", "error": "Needs attention"}
RUNNING = {"queued", "outlining", "drafting", "building"}
MAX_BYTES = int(os.environ.get("D2D_STUDIO_MAX_MB", "100")) * 1024 * 1024
TEST_HOOKS = os.environ.get("D2D_TEST_HOOKS") == "1"
SAFE = re.compile(r"[^\w.\- ]+")
MIME = {".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation", ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".pdf": "application/pdf", ".html": "text/html; charset=utf-8", ".json": "application/json",
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".csv": "text/csv", ".txt": "text/plain; charset=utf-8", ".md": "text/markdown; charset=utf-8",
        ".yaml": "text/yaml; charset=utf-8", ".potx": "application/vnd.openxmlformats-officedocument.presentationml.template", ".dotx": "application/vnd.openxmlformats-officedocument.wordprocessingml.template"}


def mime_of(path: Path) -> str:
    return MIME.get(path.suffix.lower(), "application/octet-stream")


class StudioError(Exception):
    pass


# ---------------------------------------------------------------- the folder

def folder(pid: str) -> Path:
    return store.project_dir(pid)


def load(pid: str) -> dict:
    st = None
    for attempt in range(3):                      # a save in flight (tmp -> project.json) is not atomic on every mount: look again
        try:
            st = store.load(pid)
            break
        except (KeyError, FileNotFoundError):
            if attempt == 2:
                raise
            time.sleep(0.05)
    if not st or st.get("kind") != KIND:
        raise KeyError(pid)
    return st


def spec_name(st: dict) -> str:
    return "deck.yaml" if st.get("deliverable_kind") == "deck" else "doc.yaml"


def _note(pid: str, heading: str, body: str) -> None:
    """A dated section at the bottom of brief.md - the file the agent reads (store.note writes request.md, the dashboard's)."""
    with (folder(pid) / "brief.md").open("a", encoding="utf-8") as f:
        f.write(f"\n\n## {heading} ({time.strftime('%Y-%m-%d %H:%M')})\n\n{body.strip()}\n")


def _safe(name: str, taken: set[str]) -> str:
    base = SAFE.sub("_", Path(name or "file").name).strip(" ._") or "file"
    out = base
    while out.lower() in taken or out.startswith("."):
        out = "_" + out
    taken.add(out.lower())
    return out


def _brief_md(st: dict, sources: dict, attachments: list[dict]) -> str:
    t = TYPE_BY_ID.get(st["type"], (st["type"], st["type"], "deck"))
    lines = [f"# {st['name']}", "", f"**Deliverable:** {t[1]} ({t[2]})  ", f"**Audience:** {st.get('audience') or '-'}  ", f"**Due:** {st.get('due') or '-'}  ",
             f"**Template:** {'the tenant template' if st.get('template') == 'tenant' else 'RELAY'}", "", "## The brief", "", (st.get("brief") or "").strip() or "(none)", "",
             "## Sources (in sources/)", ""]
    for k, label in (("dashboards", "Dashboards"), ("starts", "Starts"), ("rfps", "RFP responses"), ("modules", "Module facts"), ("library", "Library items")):
        for x in sources.get(k) or []:
            lines.append(f"- {label}: {x}")
    if sources.get("practice"):
        lines.append("- Practice pulse (Home KPIs, last 30 days): practice.json")
    lines += [f"- Attachment: {a['name']} ({a['kind']})" for a in attachments] or []
    if not any(sources.values()) and not attachments:
        lines.append("- (none picked: only the registry's module facts)")
    lines += ["", "## Handling", "", "- Every figure must come from a source; a figure without one fails the check.",
              "- Nothing leaves this tenant: filing and mail need a named approval after the final is accepted.", ""]
    return "\n".join(lines)


# ---------------------------------------------------------------- sources: snapshots of platform records

def _measure_values(d: Path) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for p in sorted(d.glob("versions/v*/dax.json"), key=lambda x: int(re.sub(r"\D", "", x.parent.name) or 0)):
        try:
            dax = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for v in dax.get("values") or []:
            out[v["name"]] = {"value": v.get("value"), "text": v.get("text"), "version": p.parent.name}
    return out


def dashboard_snapshot(pid: str) -> dict:
    d = store.project_dir(pid)
    st = store.load(pid)
    plan = {}
    try:
        plan = yaml.safe_load((d / "plan.yaml").read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        pass
    values = _measure_values(d)
    measures = []
    for k in plan.get("kpis") or []:
        if isinstance(k, dict) and k.get("name"):
            v = values.get(k["name"], {})
            measures.append({"name": k["name"], "label": k.get("label") or k["name"], "description": k.get("description") or "", "format": k.get("format") or "",
                             "value": v.get("value"), "text": v.get("text"), "checked_in": v.get("version")})
    for name, v in values.items():
        if not any(m["name"] == name for m in measures):
            measures.append({"name": name, "label": name, "description": "", "format": "", "value": v.get("value"), "text": v.get("text"), "checked_in": v.get("version")})
    latest = (st.get("versions") or [{}])[-1]
    return {"id": pid, "name": st.get("name"), "status": st.get("status"), "prompt": (st.get("prompt") or "")[:600], "summary": plan.get("summary") or "",
            "pages": [p.get("name") for p in plan.get("pages") or [] if isinstance(p, dict)], "measures": measures,
            "version": latest.get("v"), "gates": latest.get("gates"), "published": bool(st.get("output")), "approved": st.get("approved"),
            "rows": st.get("data_rows"), "tables": [t.get("table") for t in st.get("data_tables") or []], "note": "values are what Power BI's engine returned for the latest checked version"}


def registry_facts() -> dict:
    mods = {}
    for m in registry.MODULES:
        if m["pl"] in ("hidden", "platform"):
            continue
        plan = registry.plan_for(m, "develop" if "develop" in m["work"] else (m["work"][0] if m["work"] else "engage"))
        mods[m["id"]] = {"id": m["id"], "name": m["name"], "sub": m["sub"], "text": m["text"], "pillar": m["pl"], "platforms": m["platforms"], "work": m["work"],
                         "status": m["status"], "journey": plan["journey"], "steps": plan["steps"], "confirm": registry.confirm_for(m, "develop" if "develop" in m["work"] else "engage")}
    return {"modules": mods, "pillars": [{"id": i, "name": n, "line": l} for i, n, l in registry.PILLARS], "brand": {k: v for k, v in registry.brand().items() if k in ("name", "full", "partner", "edition", "powered")}}


def practice_snapshot(u: dict | None) -> dict:
    data = home.build(u, "30d")
    return {"period": "30d", "kpis": data.get("kpis"), "now": data.get("now"), "trend": data.get("trend") or data.get("months"), "note": "Home KPIs: agent runs, hours, right first time, waiting for a person"}


def write_brand(d: Path, template_choice: str) -> dict:
    """sources/brand.json (+ the tenant template files) so `genbi deck build` in the agent and the app's build agree."""
    b = registry.brand()
    tpl = registry.templates()
    info = {"name": b["name"], "full": b["full"], "partner": b["partner"], "color": b["color"], "mark": b["mark"], "sender": b["sender"],
            "house_style": tpl["house_style"], "template": template_choice, "logo_light": b.get("logo_light") or ""}
    sdir = d / "sources"
    sdir.mkdir(exist_ok=True)
    for slot in ("pptx", "docx"):
        p = sdir / f"template.{slot}"
        if template_choice == "tenant" and tpl.get(slot):
            p.write_bytes(tpl[slot])
            info[f"template_{slot}_file"] = f"sources/template.{slot}"
        elif p.exists():
            p.unlink()
    (sdir / "brand.json").write_text(json.dumps(info, indent=1), encoding="utf-8")
    return info


def snapshot_sources(pid: str, picks: dict, u: dict | None) -> dict:
    """Copy the picked platform records into sources/ (only what the person may see). Returns what was written."""
    d = folder(pid)
    sdir = d / "sources"
    sdir.mkdir(exist_ok=True)
    written = {"dashboards": [], "starts": [], "rfps": [], "modules": [], "library": [], "practice": False, "skipped": []}
    (sdir / "registry.json").write_text(json.dumps(registry_facts(), indent=1, ensure_ascii=False), encoding="utf-8")
    for did in picks.get("dashboards") or []:
        p = db.project(did)
        if not p or (u and not auth.can_project(u, "view", p)):
            written["skipped"].append(did)
            continue
        try:
            snap = dashboard_snapshot(did)
        except (KeyError, FileNotFoundError, ValueError):
            written["skipped"].append(did)
            continue
        (sdir / f"dashboard-{did}.json").write_text(json.dumps(snap, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
        written["dashboards"].append(did)
    for sid in picks.get("starts") or []:
        p = db.project(sid)
        if not p or (u and not auth.can_project(u, "view", p)):
            written["skipped"].append(sid)
            continue
        try:
            st = start.load(sid)
            v = start.views(start.load_analysis(start.folder(sid)))
        except (KeyError, FileNotFoundError, ValueError):
            written["skipped"].append(sid)
            continue
        (sdir / f"start-{sid}.json").write_text(json.dumps({"id": sid, "name": st.get("name"), "status": st.get("status"), "brief": st.get("prompt"), **v}, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
        written["starts"].append(sid)
    for rid in picks.get("rfps") or []:
        p = db.project(rid)
        if not p or (u and not auth.can_project(u, "view", p)):
            written["skipped"].append(rid)
            continue
        try:
            from . import rfp
            snap = rfp.snapshot(rid)
        except Exception:  # noqa: BLE001 - a response that cannot be read is skipped, never a failed brief
            written["skipped"].append(rid)
            continue
        (sdir / f"rfp-{rid}.json").write_text(json.dumps(snap, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
        written["rfps"].append(rid)
    if picks.get("practice"):
        try:
            (sdir / "practice.json").write_text(json.dumps(practice_snapshot(u), indent=1, ensure_ascii=False, default=str), encoding="utf-8")
            written["practice"] = True
        except Exception:  # noqa: BLE001
            traceback.print_exc()
    written["modules"] = [m for m in picks.get("modules") or [] if m in registry.BY_ID]
    if picks.get("library"):
        try:
            from . import rfp
            items = rfp.library_items([str(x) for x in picks["library"]])
            (sdir / "library.json").write_text(json.dumps({"items": items}, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
            written["library"] = [i["id"] for i in items]
        except Exception:  # noqa: BLE001
            traceback.print_exc()
    return written


def _preread(d: Path, names: list[str]) -> None:
    for n in names:
        try:
            reader.read(d / "sources" / n)
        except Exception:  # noqa: BLE001
            traceback.print_exc()


# ---------------------------------------------------------------- outline.yaml: check, views, checkpoint

def load_outline(d: Path) -> dict | None:
    p = d / "outline.yaml"
    if not p.exists():
        return None
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return None
    return raw if isinstance(raw, dict) else None


def check_outline(d: Path, st: dict) -> list[str]:
    p = d / "outline.yaml"
    if not p.exists():
        return ["outline.yaml was not written"]
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        return [f"outline.yaml does not parse: {str(e).splitlines()[0][:200]}"]
    if not isinstance(raw, dict):
        return ["outline.yaml must be a mapping with story and sections"]
    deck = st.get("deliverable_kind") == "deck"
    key = "slides" if deck else "blocks"
    allowed = docs_spec.LAYOUTS if deck else docs_spec.BLOCKS
    problems = []
    if not str(raw.get("story") or "").strip():
        problems.append("story is missing - 2-3 sentences on the argument")
    secs = raw.get("sections")
    if not isinstance(secs, list) or not secs:
        return problems + ["sections is empty"]
    resolver = Resolver(d, store.ROOT)
    n = 0
    for i, s in enumerate(secs, 1):
        if not isinstance(s, dict) or not str(s.get("title") or "").strip():
            problems.append(f"sections[{i}] needs a title")
            continue
        units = s.get(key) if isinstance(s.get(key), list) else s.get("slides" if not deck else "blocks")
        if not isinstance(units, list) or not units:
            problems.append(f"section \"{s.get('title')}\" has no {key}")
            continue
        for u in units:
            n += 1
            if not isinstance(u, dict) or not str(u.get("title") or "").strip():
                problems.append(f"{key[:-1]} {n} needs a title")
                continue
            lay = str(u.get("layout") or u.get("kind") or "").lower()
            if lay not in allowed:
                problems.append(f"{key[:-1]} {n} \"{u.get('title')}\": layout must be one of {', '.join(allowed)}")
            for ref in u.get("sources") or []:
                r = resolver.resolve(str(ref))
                if not r["ok"]:
                    problems.append(f"{key[:-1]} {n} \"{u.get('title')}\": source {ref} - {r['why']}")
    if n < 3:
        problems.append(f"only {n} {key}: a deliverable needs more than that")
    return problems


def outline_view(raw: dict | None, st: dict) -> dict:
    raw = raw or {}
    deck = st.get("deliverable_kind") == "deck"
    key = "slides" if deck else "blocks"
    sections, n = [], 0
    for s in raw.get("sections") or []:
        if not isinstance(s, dict):
            continue
        units = []
        for u in (s.get(key) if isinstance(s.get(key), list) else s.get("slides" if not deck else "blocks")) or []:
            if isinstance(u, dict):
                n += 1
                units.append({"n": n, "title": str(u.get("title") or ""), "layout": str(u.get("layout") or u.get("kind") or ""), "intent": str(u.get("intent") or ""),
                              "sources": [str(x) for x in (u.get("sources") or []) if x]})
        sections.append({"title": str(s.get("title") or ""), "units": units})
    return {"story": str(raw.get("story") or ""), "sections": sections, "counts": {"sections": len(sections), "units": n, "unit": key[:-1]}}


def outline_evidence(v: dict) -> dict:
    return {"summary": f"{v['counts']['sections']} sections, {v['counts']['units']} {v['counts']['unit']}s - {v['story'][:200]}",
            "counts": {"sections": v["counts"]["sections"], v["counts"]["unit"] + "s": v["counts"]["units"]},
            "items": [f"{s['title']}: " + ", ".join(u["title"] for u in s["units"][:6]) for s in v["sections"][:8]], "rows": v["sections"]}


def _owner(pid: str) -> str | None:
    p = db.project(pid)
    return p["owner_id"] if p else None


def outlined(pid: str, summary: str = "") -> dict:
    d = folder(pid)
    st = load(pid)
    problems = check_outline(d, st)
    if problems:
        raise StudioError("; ".join(problems[:4]))
    v = outline_view(load_outline(d), st)
    st.update(status="awaiting_outline", job=None, error=None, outline_rounds=(st.get("outline_rounds") or 0) + 1, outline_summary=summary or st.get("outline_summary") or "",
              outlined=time.time(), counts={**(st.get("counts") or {}), "sections": v["counts"]["sections"], "units": v["counts"]["units"]})
    store.save(st)
    checkpoints.withdraw(CP_OUTLINE, pid, who="system")
    checkpoints.open(CP_OUTLINE, pid, MODULE, f"Outline: {st['name']}", "plan", outline_evidence(v), link=f"{ROUTE}/{pid}", assignee=_owner(pid), agent="Relay writer", opened_by="agent")
    worker.app_note(pid, "studio_outline", f"Outline ready: {v['counts']['sections']} sections, {v['counts']['units']} {v['counts']['unit']}s. Reorder, cut or add, then confirm it - or send it back with a comment.", "ok")
    db.audit("studio.outlined", pid, {"rounds": st["outline_rounds"], **v["counts"]}, "agent")
    return st


# ---------------------------------------------------------------- the build (deterministic; the app's own)

def _renderer(html: str, fmt: str = "png") -> bytes | None:
    """PNG / PDF of a page through the agent's headless Chromium (the same /render publishing uses)."""
    try:
        r = httpx.post(f"{worker.AGENT_URL}/render", json={"html": html, "format": fmt, "width": 1320}, timeout=180)
        if r.status_code != 200:
            return None
        return base64.b64decode(r.json()["data"])
    except Exception:  # noqa: BLE001 - no agent, no picture: the build says so
        return None


def build_version(pid: str, st: dict) -> dict:
    """Build the YAML into builds/vN (pptx or docx, twin, pdf when the agent can draw it, check.json)."""
    d = folder(pid)
    n = len(st.get("builds") or []) + 1
    out = d / "builds" / f"v{n}"
    shutil.rmtree(out, ignore_errors=True)
    info = docs_build.build(d / spec_name(st), out, workspace=store.ROOT, renderer=_renderer, evidence_base=f"{ROUTE}/{pid}/sources?ref=", pdf=True)
    rep = info["report"]
    made = info.get("deck") or info.get("doc") or {}
    rec = {"v": n, "when": time.time(), "ok": rep["ok"], "fails": rep["counts"]["fails"], "warnings": rep["counts"]["warnings"], "files": info["files"],
           "template": info["template"], "partner": info["partner"], "renderer": info.get("renderer"), "pdf": "pdf" in info["files"],
           "counts": {k: made.get(k) for k in ("slides", "blocks", "charts", "tables", "diagrams", "notes", "images") if made.get(k) is not None},
           "checks": [{"check": c["check"], "label": c["label"], "status": c["status"], "summary": c["summary"]} for c in rep["checks"]]}
    return rec


def check_report(pid: str, v: int, d: Path | None = None) -> dict | None:
    p = (d or store.ROOT / pid) / "builds" / f"v{v}" / "check.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _problems_of(pid: str, v: int) -> list[str]:
    rep = check_report(pid, v)
    return docs_checks.problems(rep) if rep else ["the build produced no check report"]


def reviewed(pid: str, rec: dict, summary: str = "") -> dict:
    """A build is ready for review: record it, open the final checkpoint with the twin and PDF as evidence."""
    st = load(pid)
    st.setdefault("builds", []).append(rec)
    st.update(status="awaiting_review", job=None, error=None, draft_rounds=(st.get("draft_rounds") or 0) + 1, draft_summary=summary or st.get("draft_summary") or "",
              drafted=time.time(), final=None)
    store.save(st)
    checkpoints.withdraw(CP_FINAL, pid, who="system")
    files = rec["files"]
    ev = {"summary": f"Build v{rec['v']}: " + (", ".join(f"{v} {k}" for k, v in rec["counts"].items() if v) or "built") + f" - checks {'passed' if rec['ok'] else 'FAILED (' + str(rec['fails']) + ' problems)'}"
                     + (f", {rec['warnings']} warnings" if rec["warnings"] else ""),
          "items": [f"{c['label']}: {c['summary']}" for c in rec["checks"]], "counts": {"version": rec["v"], "problems": rec["fails"], "warnings": rec["warnings"]},
          "twin": f"/api/studio/{pid}/preview/{rec['v']}", "pdf": f"/api/studio/{pid}/builds/{rec['v']}/{files['pdf']}" if files.get("pdf") else None,
          "file": f"/api/studio/{pid}/builds/{rec['v']}/{files.get('pptx') or files.get('docx')}"}
    checkpoints.open(CP_FINAL, pid, MODULE, f"Final: {st['name']} (v{rec['v']})", "link", ev, link=f"{ROUTE}/{pid}", assignee=_owner(pid), agent="Relay writer", opened_by="agent")
    worker.app_note(pid, "studio_draft", f"Draft v{rec['v']} is ready to review: " + ev["summary"] + ". Look at the preview, comment in place, then accept it or send it back.",
                    "ok" if rec["ok"] else "warn")
    db.audit("studio.drafted", pid, {"version": rec["v"], "ok": rec["ok"], "fails": rec["fails"], "warnings": rec["warnings"]}, "agent")
    return st


# ---------------------------------------------------------------- jobs

async def _outline(pid: str, args: dict) -> None:
    d = folder(pid)
    st = load(pid)
    comment = args.get("comment")
    worker.app_note(pid, "studio_outline", "Relay is outlining again with your comment." if comment else f"Relay is reading the brief and {len(st.get('attachments') or [])} attachment(s) plus the picked records, and proposing an outline.")
    prompt = studio_prompts.outline(st, d)
    if comment:
        prompt += f"\n\nThe person sent the earlier outline back with this comment (also at the bottom of brief.md):\n\n{comment.strip()}\n\nWrite outline.yaml again with it; keep what was right."
    res = await worker.agent(pid, "studio_outline", prompt, worker.TURNS["studio_outline"], "outline", system=studio_prompts.SYSTEM)
    for attempt in range(worker.FIX_ROUNDS + 1):
        problems = await asyncio.to_thread(check_outline, d, st)
        if not problems:
            break
        if attempt == worker.FIX_ROUNDS:
            raise RuntimeError(f"outline.yaml still has {len(problems)} problem(s): " + "; ".join(problems[:4]))
        worker.app_note(pid, "studio_outline", f"The check found {len(problems)} problem(s) in outline.yaml - Relay is fixing them.", "warn", problems)
        res = await worker.agent(pid, "studio_outline", "The web app checked outline.yaml and found these problems:\n\n" + "\n".join(f"- {p}" for p in problems[:25])
                                 + "\n\nFix them in outline.yaml (keep the rest) and end with one sentence on what you fixed.", worker.TURNS["fix"], "outline",
                                 resume=res.get("session_id"), system=studio_prompts.SYSTEM)
    outlined(pid, res.get("text") or "")


async def _draft(pid: str, args: dict) -> None:
    d = folder(pid)
    st = load(pid)
    comment = args.get("comment")
    worker.app_note(pid, "studio_draft", "Relay is revising the draft with your comments." if comment else "Relay is drafting from the confirmed outline - every figure with its source.")
    res = await worker.agent(pid, "studio_draft", studio_prompts.draft(st, comment), worker.TURNS["studio_draft"], "draft", system=studio_prompts.SYSTEM)
    rec = None
    for attempt in range(worker.FIX_ROUNDS + 1):
        worker.app_note(pid, "studio_draft", "Building the deliverable and running the checks: sources, numbers vs source, placeholders, limits, contrast, alt text, house style, tenant boundary...")
        store.update(pid, status="building")
        try:
            rec = await asyncio.to_thread(build_version, pid, load(pid))
        except docs_spec.DocError as e:
            rec = None
            problems = [str(e)]
        else:
            problems = _problems_of(pid, rec["v"])
            if rec["ok"] or attempt == worker.FIX_ROUNDS:
                break
            shutil.rmtree(d / "builds" / f"v{rec['v']}", ignore_errors=True)        # a failed round is rebuilt under the same number
        if attempt == worker.FIX_ROUNDS:
            break
        store.update(pid, status="drafting")
        worker.app_note(pid, "studio_draft", f"The checks found {len(problems)} problem(s) - Relay is fixing them.", "warn", problems)
        res = await worker.agent(pid, "studio_draft", studio_prompts.fix(load(pid), problems), worker.TURNS["fix"], "draft", resume=res.get("session_id"), system=studio_prompts.SYSTEM)
    if rec is None:
        raise RuntimeError(f"{spec_name(st)} could not be built: " + "; ".join(problems[:3]))
    reviewed(pid, rec, res.get("text") or "")


async def _rebuild(pid: str, args: dict) -> None:
    """Later edits to the YAML (PUT .../yaml) re-run the build and the checks; the review reopens on the new version."""
    st = load(pid)
    worker.app_note(pid, "studio_build", "Rebuilding after your edit and running every check again.")
    rec = await asyncio.to_thread(build_version, pid, st)
    reviewed(pid, rec, st.get("draft_summary") or "")


worker.register_job("studio_outline", _outline, status="outlining", done="Outline ready - confirm it in the studio", llm=True, turns=60, timeout_s=1800)
worker.register_job("studio_draft", _draft, status="drafting", done="Draft ready to review in the studio", llm=True, turns=120, timeout_s=3600)
worker.register_job("studio_build", _rebuild, status="building", done="Rebuilt - review it in the studio")


# ---------------------------------------------------------------- decisions

def _on_outline(c: dict, decision: str, comment: str | None, who: str) -> None:
    pid = c["subject"]
    try:
        st = load(pid)
    except (KeyError, FileNotFoundError):
        return
    if st["status"] != "awaiting_outline":
        return
    if decision == "accept":
        st.update(outline_confirmed={"by": who, "when": time.time(), "checkpoint": c["id"]})
        store.save(st)
        store.log(pid, {"kind": "user", "stage": "studio", "text": "Confirmed the outline" + (f" - {comment}" if comment else "")})
        db.audit("studio.outline_confirmed", pid, {"checkpoint": c["id"]}, who)
        worker.enqueue(pid, "studio_draft")
    else:
        comment = " ".join((comment or "").split())[:2000]
        _note(pid, "Outline sent back", comment)
        st.setdefault("comments", []).append({"stage": "outline", "text": comment, "who": who, "when": time.time()})
        store.save(st)
        db.audit("studio.outline_sent_back", pid, {"comment": comment[:300]}, who)
        worker.enqueue(pid, "studio_outline", comment=comment)


def _on_final(c: dict, decision: str, comment: str | None, who: str) -> None:
    pid = c["subject"]
    try:
        st = load(pid)
    except (KeyError, FileNotFoundError):
        return
    if st["status"] != "awaiting_review":
        return
    v = (st.get("builds") or [{}])[-1].get("v")
    if decision == "accept":
        st.update(status="final", final={"by": who, "when": time.time(), "checkpoint": c["id"], "version": v, "comment": (comment or "")[:500]}, job=None)
        store.save(st)
        _note(pid, "Final accepted", f"Build v{v} accepted by {who}" + (f": {comment}" if comment else ""))
        store.log(pid, {"kind": "user", "stage": "studio", "text": f"Accepted v{v} as final"})
        db.audit("studio.final", pid, {"version": v, "checkpoint": c["id"]}, who)
        owner = _owner(pid)
        if owner and owner != who:
            notify.add(owner, "review", f"Final: {st.get('name')}", f"v{v} accepted - file it or send it", f"{ROUTE}/{pid}")
    else:
        comment = " ".join((comment or "").split())[:2000]
        pending = [x for x in st.get("comments") or [] if x.get("stage") == "review" and x.get("version") == v]
        text = comment + ("".join(f"\n- {'slide' if st.get('deliverable_kind') == 'deck' else 'block'} {x.get('unit') or '?'}: {x['text']}" for x in pending) if pending else "")
        _note(pid, f"Draft v{v} sent back", text)
        st.setdefault("comments", []).append({"stage": "review", "version": v, "text": comment, "who": who, "when": time.time(), "sent_back": True})
        store.save(st)
        db.audit("studio.draft_sent_back", pid, {"version": v, "comment": comment[:300]}, who)
        worker.enqueue(pid, "studio_draft", comment=text)


checkpoints.register_kind(CP_OUTLINE, "Studio: confirm the outline", _on_outline)
checkpoints.register_kind(CP_FINAL, "Studio: accept the final", _on_final)


# ---------------------------------------------------------------- state for the page

def _build_public(pid: str, b: dict) -> dict:
    files = b.get("files") or {}
    return {**b, "links": {k: f"/api/studio/{pid}/builds/{b['v']}/{v}" for k, v in files.items() if k != "check"}, "preview": f"/api/studio/{pid}/preview/{b['v']}"}


def state(pid: str, u: dict | None = None) -> dict:
    st = load(pid)
    d = folder(pid)
    p = db.project(pid)
    names = {x["id"]: x["name"] for x in db.q("SELECT id, name FROM users")}
    cps = {c["kind"]: checkpoints._public(c) for c in db.q("SELECT * FROM checkpoints WHERE subject = ? AND status = 'open' AND kind IN (?, ?)", (pid, CP_OUTLINE, CP_FINAL))}
    builds = [_build_public(pid, b) for b in st.get("builds") or []]
    latest = builds[-1] if builds else None
    spec_text = ""
    if (d / spec_name(st)).exists():
        spec_text = (d / spec_name(st)).read_text(encoding="utf-8")
    att = []
    for a in st.get("attachments") or []:
        info = reader.cached(d / "sources" / a["name"])
        att.append({**a, "read": info is not None, "pages": (info or {}).get("pages"), "note": (info or {}).get("note") or ""})
    out = {**st, "status_label": STATUS_LABEL.get(st["status"], st["status"]), "type_label": TYPE_BY_ID.get(st["type"], (st["type"], st["type"]))[1],
           "outline": outline_view(load_outline(d), st) if (d / "outline.yaml").exists() else None, "open_checkpoints": {k: c["id"] for k, c in cps.items()},
           "builds": builds, "latest": latest, "report": check_report(pid, latest["v"], d) if latest else None, "spec": spec_text, "spec_name": spec_name(st),
           "attachments": att, "owner": p["owner_id"] if p else None, "owner_name": names.get(p["owner_id"]) if p else None,
           "position": worker.position(pid) if st["status"] == "queued" else 0, "running_since": worker.running_since(pid),
           "sources_list": sorted(x.name for x in (d / "sources").glob("*") if x.is_file()), "test_hooks": TEST_HOOKS,
           "final": {**st["final"], "by_name": names.get(st["final"].get("by"), "someone")} if st.get("final") else None,
           "outline_confirmed": {**st["outline_confirmed"], "by_name": names.get(st["outline_confirmed"].get("by"), "someone")} if st.get("outline_confirmed") else None,
           "comments": [{**x, "who_name": names.get(x.get("who"), "someone")} for x in st.get("comments") or []],
           "filed": [_filed_public(f, names) for f in st.get("filed") or []], "can_send": st.get("status") == "final"}
    if u is not None:
        out["access"] = {"can_edit": auth.can_project(u, "edit", p) and auth.is_dev(u), "can_view": auth.can_project(u, "view", p)}
    return out


def _filed_public(f: dict, names: dict) -> dict:
    """A filing request as the screen shows it: names, never ids (a request from before the hook takes its checkpoint's status)."""
    s = f.get("status")
    if not s:
        cp = db.one("SELECT status FROM checkpoints WHERE id = ?", (f.get("checkpoint"),)) or {}
        s = {"accepted": "filed", "sent_back": "sent_back"}.get(cp.get("status"), "waiting")
    return {**f, "status": s, "status_label": FILED_STATUS.get(s, s), "by_name": names.get(f.get("by"), "someone"),
            "decided_by_name": names.get(f.get("decided_by")) if f.get("decided_by") else None}


def summary_of(pid: str) -> dict:
    st = load(pid)
    return {k: st.get(k) for k in ("id", "name", "type", "deliverable_kind", "status", "audience", "due", "template", "created", "updated")} | \
           {"status_label": STATUS_LABEL.get(st["status"], st["status"]), "type_label": TYPE_BY_ID.get(st["type"], (st["type"], st["type"]))[1],
            "builds": len(st.get("builds") or []), "ok": (st.get("builds") or [{}])[-1].get("ok") if st.get("builds") else None, "final": bool(st.get("final"))}


def all_items() -> list[dict]:
    return [p for p in store.all_projects() if p.get("kind") == KIND]


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
        raise HTTPException(404, "No such studio item.")
    p = db.project(pid)
    if not auth.can_project(u, "view", p):
        raise HTTPException(404, "No such studio item.")
    if action != "view" and not (auth.can_project(u, "edit", p) and auth.is_dev(u)):
        raise HTTPException(403, "You can look at this deliverable, but only its owner or a builder it is shared with can change it.")
    return u, st


def _pickable(u: dict) -> dict:
    """The records a person may pick as sources: their dashboards and starts, RFP responses, library items, modules."""
    items = store.all_projects()
    ids = [p["id"] for p in items]
    access = auth.access_map(u, ids)
    dash = [{"id": p["id"], "name": p["name"], "status": p["status"], "published": p.get("published")} for p in items if p["id"] in access and p.get("kind") == "dashboard"]
    starts = [{"id": p["id"], "name": p["name"], "status": p["status"]} for p in items if p["id"] in access and p.get("kind") == "start"]
    rfps = [{"id": p["id"], "name": p["name"], "status": p["status"]} for p in items if p["id"] in access and p.get("kind") == "rfp"]
    lib = []
    try:
        from . import rfp
        lib = [{"id": i["id"], "title": i["title"], "module": i.get("module"), "buyer_type": i.get("buyer_type")} for i in rfp.library_list(limit=50)]
    except Exception:  # noqa: BLE001
        pass
    mods = [{"id": m["id"], "name": m["name"], "pillar": m["pl"]} for m in registry.MODULES if m["pl"] not in ("hidden", "platform")]
    return {"dashboards": dash[:60], "starts": starts[:60], "rfps": rfps[:60], "library": lib, "modules": mods, "practice": True}


@router.get("/api/studio")
def list_items():
    u = _u()
    ids = [p["id"] for p in all_items()]
    access = auth.access_map(u, ids)
    out = []
    for pid in ids:
        if pid in access:
            try:
                out.append({**summary_of(pid), "access": access[pid]["access"]})
            except (KeyError, FileNotFoundError, ValueError):
                continue
    tpl = registry.templates()
    return {"items": sorted(out, key=lambda s: -(s.get("created") or 0)), "can_create": auth.is_dev(u),
            "types": [{"id": i, "label": l, "kind": k} for i, l, k in TYPES], "templates": {"relay": True, "tenant": bool(tpl["pptx"] or tpl["docx"]), "names": tpl["names"], "house_style": tpl["house_style"]},
            "sources": _pickable(u) if auth.is_dev(u) else {}, "kinds": {k: sorted(v) for k, v in reader.KINDS.items() if k in ("doc", "sheet", "deck", "pdf", "image", "text")},
            "module_types": MODULE_TYPE}


@router.get("/api/studio/summary")
def summary():
    """For Home: counts and the latest items (an empty state when nothing exists yet)."""
    u = _u()
    ids = [p["id"] for p in all_items()]
    access = auth.access_map(u, ids)
    items = []
    for pid in ids:
        if pid in access:
            try:
                items.append(summary_of(pid))
            except (KeyError, FileNotFoundError, ValueError):
                continue
    items.sort(key=lambda s: -(s.get("updated") or s.get("created") or 0))
    return {"items": len(items), "awaiting": sum(1 for s in items if s["status"] in ("awaiting_outline", "awaiting_review")), "final": sum(1 for s in items if s["status"] == "final"),
            "running": sum(1 for s in items if s["status"] in RUNNING), "recent": items[:5], "can_create": auth.is_dev(u),
            "hint": "Brief a proposal, deck or document - drafted from Relay's facts in your template, every figure sourced."}


@router.post("/api/studio")
async def create(title: str = Form(""), type: str = Form("proposal"), brief: str = Form(""), audience: str = Form(""), due: str = Form(""),  # noqa: A002
                 template: str = Form("relay"), sources: str = Form("{}"), files: list[UploadFile] = File(default=[])):
    u = _u()
    if not auth.is_dev(u):
        raise HTTPException(403, "Only builders and admins can brief the studio; ask one to brief it for you.")
    if type not in TYPE_BY_ID:
        raise HTTPException(400, "Pick a deliverable type.")
    title = " ".join(title.split())[:120]
    if len(title) < 3:
        raise HTTPException(400, "Give the deliverable a title.")
    if len(brief.strip()) < 10:
        raise HTTPException(400, "Say what the deliverable must achieve, in a sentence or two.")
    if template not in ("relay", "tenant"):
        raise HTTPException(400, "Template must be relay or tenant.")
    tpl = registry.templates()
    if template == "tenant" and not (tpl["pptx"] or tpl["docx"]):
        raise HTTPException(400, "No tenant template is set: upload one under Admin > Branding, or use the RELAY template.")
    try:
        picks = json.loads(sources or "{}")
        assert isinstance(picks, dict)
    except (ValueError, AssertionError):
        raise HTTPException(400, "sources must be a JSON object.")
    files = [f for f in files if f.filename]
    bad = [f.filename for f in files if reader.kind_of(f.filename) not in ("doc", "sheet", "deck", "pdf", "image", "text")]
    if bad:
        raise HTTPException(400, f"Not a kind of file the studio reads: {', '.join(bad[:3])}. Attach Word, Excel or CSV, PowerPoint, PDF, images or text.")
    pid = store.new_id(title)
    d = store.ROOT / pid
    (d / "sources").mkdir(parents=True)
    taken: set[str] = {"registry.json", "brand.json", "library.json", "practice.json"}
    attachments = []
    try:
        for f in files:
            n = _safe(f.filename, taken)
            size = 0
            with (d / "sources" / n).open("wb") as out:
                while chunk := await f.read(1024 * 1024):
                    out.write(chunk)
                    size += len(chunk)
                    if size > MAX_BYTES:
                        raise HTTPException(413, f'"{f.filename}" is larger than {MAX_BYTES // 1024 // 1024} MB.')
            attachments.append({"name": n, "kind": reader.kind_of(n), "bytes": size})
    except BaseException:
        shutil.rmtree(d, ignore_errors=True)
        raise
    kind = TYPE_BY_ID[type][2]
    st = {"id": pid, "kind": KIND, "name": title, "type": type, "type_label": TYPE_BY_ID[type][1], "deliverable_kind": kind, "brief": brief.strip(), "audience": audience.strip()[:120],
          "due": due.strip()[:40], "template": template, "sources": picks, "attachments": attachments, "model": worker.DEFAULT_MODEL, "created": time.time(), "status": "queued",
          "builds": [], "comments": [], "versions": [], "runs": [], "files": [], "job": None, "error": None, "outline_rounds": 0, "draft_rounds": 0, "final": None, "filed": [], "sent": []}
    store.save(st)
    db.add_project(pid, u["id"])
    written = await asyncio.to_thread(snapshot_sources, pid, picks, u)
    write_brand(d, template)
    st["sources_written"] = written
    (d / "brief.md").write_text(_brief_md(st, written, attachments), encoding="utf-8")
    (d / "request.md").write_text(f"# {title}\n\nThis folder is a studio deliverable; brief.md holds the brief. The agent's guide for dashboards does not apply here.\n", encoding="utf-8")
    store.save(st)
    await asyncio.to_thread(_preread, d, [a["name"] for a in attachments])
    db.audit("studio.create", pid, {"name": title, "type": type, "template": template, "sources": {k: v for k, v in written.items() if v}, "attachments": [a["name"] for a in attachments]}, u["id"])
    store.log(pid, {"kind": "user", "stage": "studio", "text": f"Briefed \"{title}\" ({TYPE_BY_ID[type][1]}) with {len(attachments)} attachment(s)"})
    worker.enqueue(pid, "studio_outline")
    return state(pid, u)


@router.get("/api/studio/{pid}")
def get_item(pid: str):
    u, _ = _get(pid)
    return state(pid, u)


@router.get("/api/studio/{pid}/activity")
def activity(pid: str, after: int = 0):
    _get(pid)
    return store.activity(pid, after)


@router.get("/api/studio/{pid}/sources")
def sources(pid: str, ref: str = ""):
    """The sources list, and what a reference resolves to (the twin's evidence links land here)."""
    _, st = _get(pid)
    d = folder(pid)
    resolver = Resolver(d, store.ROOT)
    files = [{"name": x.name, "bytes": x.stat().st_size, "kind": reader.kind_of(x) or x.suffix.lstrip(".")} for x in sorted((d / "sources").glob("*")) if x.is_file()]
    out = {"files": files, "picked": st.get("sources") or {}, "written": st.get("sources_written") or {}}
    if ref:
        r = resolver.resolve(ref)
        out["ref"] = ref
        out["resolved"] = r
        if r["ok"] and r.get("path"):
            p = d / r["path"]
            if p.suffix in (".json", ".yaml", ".yml", ".md", ".csv", ".txt") and p.stat().st_size < 400_000:
                out["content"] = p.read_text(encoding="utf-8", errors="replace")[:20000]
            info = reader.cached(p)
            if info:
                out["read"] = {"text": (info.get("text") or "")[:6000], "pages": info.get("pages"), "note": info.get("note")}
    return out


@router.get("/api/studio/{pid}/source/{path:path}")
def source_file(pid: str, path: str):
    _get(pid)
    base = (folder(pid) / "sources").resolve()
    target = (base / path).resolve()
    if base not in target.parents or not target.is_file():
        raise HTTPException(404, "No such source.")
    return FileResponse(target, media_type=mime_of(target), headers={"Cache-Control": "private, no-store"})


@router.get("/api/studio/{pid}/builds/{v}/{name}")
def build_file(pid: str, v: int, name: str):
    _, st = _get(pid)
    base = (folder(pid) / "builds" / f"v{v}").resolve()
    target = (base / name).resolve()
    if base != target.parent or not target.is_file():
        raise HTTPException(404, "No such file.")
    stem = SAFE.sub("_", st["name"])[:60] or "deliverable"
    return FileResponse(target, media_type=mime_of(target), filename=f"{stem} v{v}{target.suffix}" if target.suffix in (".pptx", ".docx", ".pdf") else name, headers={"Cache-Control": "private, no-store"})


@router.get("/api/studio/{pid}/preview/{v}", response_class=HTMLResponse)
def preview(pid: str, v: int):
    _get(pid)
    p = folder(pid) / "builds" / f"v{v}" / "twin.html"
    if not p.is_file():
        raise HTTPException(404, "No preview for this version.")
    return HTMLResponse(p.read_text(encoding="utf-8"), headers={"Cache-Control": "private, no-store", "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; img-src data:"})


class OutlineIn(BaseModel):
    story: str | None = None
    sections: list


@router.put("/api/studio/{pid}/outline")
def put_outline(pid: str, body: OutlineIn):
    """The person reorders, cuts or adds before confirming; saved as outline.yaml (the agent drafts from this)."""
    u, st = _get(pid, "edit")
    if st["status"] != "awaiting_outline":
        raise HTTPException(409, f"The outline is not open for changes right now (status: {st['status']}).")
    d = folder(pid)
    raw = load_outline(d) or {}
    key = "slides" if st.get("deliverable_kind") == "deck" else "blocks"
    secs = []
    for s in body.sections:
        if not isinstance(s, dict) or not str(s.get("title") or "").strip():
            raise HTTPException(400, "Every section needs a title.")
        units = []
        for x in s.get("units") or s.get(key) or []:
            if isinstance(x, dict) and str(x.get("title") or "").strip():
                units.append({"title": str(x["title"]).strip()[:120], "layout": str(x.get("layout") or "bullets"), "intent": str(x.get("intent") or "")[:400], "sources": [str(r) for r in (x.get("sources") or []) if r]})
        secs.append({"title": str(s["title"]).strip()[:120], key: units})
    raw["sections"] = secs
    if body.story is not None:
        raw["story"] = body.story.strip()[:1500]
    (d / "outline.yaml").write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True, width=110), encoding="utf-8")
    problems = check_outline(d, st)
    if problems:
        raise HTTPException(400, "; ".join(problems[:4]))
    v = outline_view(raw, st)
    st["counts"] = {**(st.get("counts") or {}), "sections": v["counts"]["sections"], "units": v["counts"]["units"]}
    st["outline_edited"] = {"by": u["id"], "when": time.time()}
    store.save(st)
    for c in db.q("SELECT id FROM checkpoints WHERE kind = ? AND subject = ? AND status = 'open'", (CP_OUTLINE, pid)):
        db.run("UPDATE checkpoints SET evidence = ? WHERE id = ?", (json.dumps(outline_evidence(v)), c["id"]))
    store.log(pid, {"kind": "user", "stage": "studio", "text": f"Edited the outline: {v['counts']['sections']} sections, {v['counts']['units']} {v['counts']['unit']}s"})
    db.audit("studio.outline_edited", pid, v["counts"], u["id"])
    return state(pid, u)


class Comment(BaseModel):
    comment: str = ""


def _open_cp(pid: str, kind: str) -> dict:
    c = db.one("SELECT * FROM checkpoints WHERE kind = ? AND subject = ? AND status = 'open'", (kind, pid))
    if not c:
        raise HTTPException(409, "This step is not waiting for a decision right now.")
    return checkpoints._public(c)


@router.post("/api/studio/{pid}/outline/confirm")
def confirm_outline(pid: str, body: Comment | None = None):
    u, st = _get(pid, "edit")
    if st["status"] != "awaiting_outline":
        raise HTTPException(409, f"Nothing to confirm right now (status: {st['status']}).")
    checkpoints.decide(_open_cp(pid, CP_OUTLINE)["id"], "accept", u["id"], body.comment if body else None)
    return state(pid, u)


@router.post("/api/studio/{pid}/outline/send-back")
def send_back_outline(pid: str, body: Comment):
    u, st = _get(pid, "edit")
    if st["status"] != "awaiting_outline":
        raise HTTPException(409, f"Nothing to send back right now (status: {st['status']}).")
    if not body.comment.strip():
        raise HTTPException(400, "Say what to change, so Relay can outline again with it.")
    checkpoints.decide(_open_cp(pid, CP_OUTLINE)["id"], "send_back", u["id"], body.comment)
    return state(pid, u)


@router.post("/api/studio/{pid}/final/accept")
def accept_final(pid: str, body: Comment | None = None):
    u, st = _get(pid, "edit")
    if st["status"] != "awaiting_review":
        raise HTTPException(409, f"Nothing to accept right now (status: {st['status']}).")
    checkpoints.decide(_open_cp(pid, CP_FINAL)["id"], "accept", u["id"], body.comment if body else None)
    return state(pid, u)


@router.post("/api/studio/{pid}/final/send-back")
def send_back_final(pid: str, body: Comment):
    u, st = _get(pid, "edit")
    if st["status"] != "awaiting_review":
        raise HTTPException(409, f"Nothing to send back right now (status: {st['status']}).")
    if not body.comment.strip():
        raise HTTPException(400, "Say what to change; Relay drafts again with your comments.")
    checkpoints.decide(_open_cp(pid, CP_FINAL)["id"], "send_back", u["id"], body.comment)
    return state(pid, u)


class UnitComment(BaseModel):
    unit: int | None = None
    text: str


@router.post("/api/studio/{pid}/comments")
def add_comment(pid: str, body: UnitComment):
    """A comment in place on the preview (a slide / block number); they travel with the next send-back."""
    u, st = _get(pid, "edit")
    text = " ".join(body.text.split())[:1500]
    if not text:
        raise HTTPException(400, "Write the comment.")
    v = (st.get("builds") or [{}])[-1].get("v")
    st.setdefault("comments", []).append({"stage": "review", "version": v, "unit": body.unit, "text": text, "who": u["id"], "when": time.time()})
    store.save(st)
    db.audit("studio.comment", pid, {"version": v, "unit": body.unit, "text": text[:200]}, u["id"])
    return state(pid, u)


class YamlIn(BaseModel):
    yaml: str


@router.put("/api/studio/{pid}/yaml")
def put_yaml(pid: str, body: YamlIn):
    """Later edits: the person changes the YAML; the checks run again and the review reopens on a new version."""
    u, st = _get(pid, "edit")
    if st["status"] in RUNNING:
        raise HTTPException(409, "Relay is working on it - wait for the current step to finish.")
    try:
        raw = yaml.safe_load(body.yaml)
    except yaml.YAMLError as e:
        raise HTTPException(400, f"The YAML does not parse: {str(e).splitlines()[0][:200]}")
    if not isinstance(raw, dict):
        raise HTTPException(400, "The YAML must be a mapping with title, kind and sections.")
    errs = docs_spec.shape_errors(raw)
    if errs:
        raise HTTPException(400, "; ".join(errs[:5]))
    d = folder(pid)
    (d / spec_name(st)).write_text(body.yaml, encoding="utf-8")
    _note(pid, "Edited by hand", f"{spec_name(st)} changed by {u['id']}; the checks run again.")
    store.log(pid, {"kind": "user", "stage": "studio", "text": f"Edited {spec_name(st)} - rebuilding and checking"})
    if st.get("status") == "final":
        st["final"] = None
    st["status"] = "queued"
    store.save(st)
    checkpoints.withdraw(CP_FINAL, pid, who=u["id"])
    db.audit("studio.yaml_edited", pid, {"bytes": len(body.yaml)}, u["id"])
    worker.enqueue(pid, "studio_build")
    return state(pid, u)


@router.post("/api/studio/{pid}/retry")
def retry(pid: str):
    u, st = _get(pid, "edit")
    if st["status"] != "error":
        raise HTTPException(409, "Nothing to retry.")
    job = st.get("job") or {}
    kind = job.get("kind") or ("studio_outline" if not (folder(pid) / "outline.yaml").exists() else "studio_draft")
    store.log(pid, {"kind": "user", "stage": kind, "text": "Retry"})
    worker.enqueue(pid, kind, **{k: v for k, v in job.items() if k == "comment"})
    return state(pid, u)


class FileTo(BaseModel):
    connection: str
    folder: str = ""
    version: int | None = None


@router.post("/api/studio/{pid}/file", status_code=202)
def file_to(pid: str, body: FileTo):
    """File the final to SharePoint / OneDrive / Drive (any write-scoped connection): a write checkpoint opens; the
    adapter uploads only when a named person accepts it (connectors.request_write)."""
    u, st = _get(pid, "edit")
    if st.get("status") != "final":
        raise HTTPException(409, "Accept the final first: only an accepted deliverable is filed.")
    v = body.version or (st.get("final") or {}).get("version") or (st.get("builds") or [{}])[-1].get("v")
    b = next((x for x in st.get("builds") or [] if x["v"] == v), None)
    if not b:
        raise HTTPException(404, "No such version.")
    try:
        c = connectors.connection(body.connection, u["id"])
    except connectors.ConnectorError:
        raise HTTPException(400, "That connection is not yours or shared with you.")
    if not connectors.may_write(c):
        raise HTTPException(403, f"{c['name']} is {connectors.SCOPES.get(c.get('scope') or 'read')}: change its scope to \"Read & write - with approval\" under Connections first.")
    files = b["files"]
    fname = files.get("pptx") or files.get("docx")
    path = folder(pid) / "builds" / f"v{v}" / fname
    data = path.read_bytes()
    fold = re.sub(r"[^\w./\- ]+", "_", body.folder.strip().strip("/"))[:200]
    stem = SAFE.sub("_", st["name"])[:60] or "deliverable"
    target = f"{fold}/{stem} v{v}{path.suffix}" if fold else f"{stem} v{v}{path.suffix}"
    payload = {"name": f"{stem} v{v}{path.suffix}", "folder": fold, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "from": f"studio:{pid}:v{v}",
               "path": f"builds/v{v}/{fname}", "pdf": f"builds/v{v}/{files['pdf']}" if files.get("pdf") else None, "content_type": "application/vnd.openxmlformats-officedocument.presentationml.presentation" if path.suffix == ".pptx" else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
    google = c["kind"] == "gdrive" and str(c["config"].get("convert") or "").strip().lower() in ("yes", "true", "1")
    accepted_by = (db.user((st.get("final") or {}).get("by")) or {}).get("name") or "a named person"
    items = [f"File: {payload['name']} (version {v}, accepted as final by {accepted_by})", f"Into: {fold or 'the top folder'} on {c['name']} ({connectors.KINDS[c['kind']]['label']})",
             f"Size: {len(data) / 1024:,.0f} KB", ("Converted to Google " + ("Slides" if path.suffix == ".pptx" else "Docs") + " on upload") if google else "Uploaded as it is",
             "Checked again before it is sent: if the file changed after this approval, nothing is filed"]
    try:
        cp = connectors.request_write(c, target, payload, u["id"], module=MODULE, what=f"File {payload['name']} to {fold + ' on ' if fold else ''}{c['name']}", items=items,
                                      link=f"{ROUTE}/{pid}")
    except Exception as e:  # noqa: BLE001 - ScopeError and the like, as the message
        raise HTTPException(403, str(e))
    if not any(x.get("checkpoint") == cp["id"] for x in st.get("filed") or []):     # asking twice while it waits is the same approval
        st.setdefault("filed", []).append({"connection": c["id"], "connection_name": c["name"], "target": target, "version": v, "checkpoint": cp["id"], "requested": time.time(),
                                           "by": u["id"], "status": "waiting"})
    store.save(st)
    store.log(pid, {"kind": "user", "stage": "studio", "text": f"Asked to file v{v} to {c['name']}: {target} - waiting for the write approval"})
    db.audit("studio.file_requested", pid, {"connection": c["id"], "target": target, "version": v, "checkpoint": cp["id"]}, u["id"])
    return {"filed": False, "checkpoint": cp, "state": state(pid, u)}


FILED_STATUS = {"waiting": "Waiting for the write approval", "filed": "Filed", "sent_back": "Sent back - not filed", "failed": "Not filed"}


def _filed(cp: dict, event: str, result) -> None:
    """connectors' write hook (origin studio:<id>:v<n>): the filing request hears what happened - filed with its
    link (and whether Drive converted it to a Google format), sent back, or not filed and why."""
    origin = str(((cp.get("evidence") or {}).get("payload") or {}).get("from") or "").split(":")
    if len(origin) < 2:
        return
    pid = origin[1]
    try:
        st = load(pid)
    except (KeyError, FileNotFoundError):
        return
    f = next((x for x in st.get("filed") or [] if x.get("checkpoint") == cp["id"]), None)
    if not f:
        return
    f.update({"status": {"written": "filed", "sent_back": "sent_back"}.get(event, "failed"), "decided": time.time(), "decided_by": cp.get("decided_by")})
    if event == "written" and isinstance(result, dict):
        f.update({"url": result.get("url"), "converted": bool(result.get("converted"))})
    elif result:
        f["note"] = str(result)[:300]
    store.save(st)
    text = {"written": f"Filed v{f['version']} to {f['connection_name']}: {f['target']}" + (" (converted to a Google format)" if f.get("converted") else ""),
            "sent_back": f"The write approval for {f['target']} was sent back - nothing was filed"}.get(event, f"{f['target']} was not filed: {str(result)[:200]}")
    store.log(pid, {"kind": "agent", "stage": "studio", "text": text})
    if f.get("by") and f.get("by") != cp.get("decided_by"):
        notify.add(f["by"], "share" if event == "written" else "alert", text[:200], "", f"{ROUTE}/{pid}")


connectors.register_write_hook("studio", _filed)


class MailIn(BaseModel):
    account: str
    to: list[str]
    subject: str = ""
    text: str = ""
    version: int | None = None


def send_mail(pid: str, u: dict, aid: str, to: list[str], subject: str, text: str, version: int | None = None) -> dict:
    """Only an accepted final leaves by mail; the person's own sending account (mailer) carries it; audited."""
    st = load(pid)
    if st.get("status") != "final":
        raise HTTPException(409, "Accept the final first: nothing is sent before a named person accepts it.")
    v = version or (st.get("final") or {}).get("version") or (st.get("builds") or [{}])[-1].get("v")
    b = next((x for x in st.get("builds") or [] if x["v"] == v), None)
    if not b:
        raise HTTPException(404, "No such version.")
    to = [t.strip() for t in to if t and mailer.EMAIL_RE.match(t.strip())]
    if not to:
        raise HTTPException(400, "Give at least one recipient address.")
    files = b["files"]
    stem = SAFE.sub("_", st["name"])[:60] or "deliverable"
    att = []
    for key, mime in (("pptx", "application/vnd.openxmlformats-officedocument.presentationml.presentation"), ("docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"), ("pdf", "application/pdf")):
        if files.get(key):
            att.append((f"{stem} v{v}.{key}", mime, (folder(pid) / "builds" / f"v{v}" / files[key]).read_bytes()))
    b_ = registry.brand()
    subject = subject.strip()[:200] or f"{st['name']} - {TYPE_BY_ID.get(st['type'], ('', st['type']))[1]}"
    html = f"<p>{(text.strip() or 'Please find the deliverable attached.').replace(chr(10), '<br>')}</p><p style=\"color:#56626E;font-size:12px\">Sent from {b_['full']}" + (f" - {b_['powered']}" if b_["partner"] else "") + "</p>"
    try:
        mailer.send(aid, u["id"], to, subject, html, att)
    except mailer.EmailError as e:
        raise HTTPException(400, str(e))
    rec = {"to": to, "subject": subject, "version": v, "when": time.time(), "by": u["id"], "account": aid, "files": [a[0] for a in att]}
    st.setdefault("sent", []).append(rec)
    store.save(st)
    store.log(pid, {"kind": "user", "stage": "studio", "text": f"Sent v{v} by mail to {', '.join(to)}"})
    db.audit("studio.sent", pid, {"to": to, "version": v, "files": rec["files"]}, u["id"])
    return rec


@router.post("/api/studio/{pid}/mail")
def mail(pid: str, body: MailIn):
    u, _ = _get(pid, "edit")
    rec = send_mail(pid, u, body.account, body.to, body.subject, body.text, body.version)
    return {"sent": rec, "state": state(pid, u)}


@router.delete("/api/studio/{pid}")
def delete_item(pid: str):
    u, st = _get(pid, "edit")
    if st["status"] in RUNNING and worker.is_running(pid):
        raise HTTPException(409, "Relay is working on it - stop it first.")
    for k in (CP_OUTLINE, CP_FINAL):
        checkpoints.withdraw(k, pid, who=u["id"])
    db.skip_queued(pid)
    shutil.rmtree(folder(pid), ignore_errors=True)
    db.run("DELETE FROM shares WHERE project_id = ?", (pid,))
    db.run("DELETE FROM projects WHERE id = ?", (pid,))
    db.audit("studio.delete", pid, {"name": st.get("name")}, u["id"])
    return {"ok": True}


# ---------------------------------------------------------------- test hooks (D2D_TEST_HOOKS=1): a test stands in for the agent

class HookIn(BaseModel):
    yaml: str
    summary: str = ""


@router.post("/api/studio/{pid}/hook/outline")
def hook_outline(pid: str, body: HookIn):
    if not TEST_HOOKS:
        raise HTTPException(404, "Not found")
    u, st = _get(pid, "edit")
    if worker.is_running(pid):
        raise HTTPException(409, "The agent is running for this item.")
    (folder(pid) / "outline.yaml").write_text(body.yaml, encoding="utf-8")
    problems = check_outline(folder(pid), st)
    if problems:
        raise HTTPException(400, "; ".join(problems))
    db.skip_queued(pid)
    outlined(pid, body.summary)
    return state(pid, u)


@router.post("/api/studio/{pid}/hook/draft")
async def hook_draft(pid: str, body: HookIn):
    if not TEST_HOOKS:
        raise HTTPException(404, "Not found")
    u, st = _get(pid, "edit")
    if worker.is_running(pid):
        raise HTTPException(409, "The agent is running for this item.")
    try:
        raw = yaml.safe_load(body.yaml)
    except yaml.YAMLError as e:
        raise HTTPException(400, str(e)[:200])
    errs = docs_spec.shape_errors(raw) if isinstance(raw, dict) else ["not a mapping"]
    if errs:
        raise HTTPException(400, "; ".join(errs[:5]))
    (folder(pid) / spec_name(st)).write_text(body.yaml, encoding="utf-8")
    db.skip_queued(pid)
    rec = await asyncio.to_thread(build_version, pid, st)
    reviewed(pid, rec, body.summary)
    return state(pid, u)
