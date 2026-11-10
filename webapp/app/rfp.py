"""RFP & bid response (build-plan v2, P11). A response is a folder output/projects/<id>/ with `kind: rfp`: the pack
under attachments/ (read with the P10 reader), requirements.yaml + gonogo.yaml (the agent's read), matrix.yaml (the
compliance matrix), pricing.yaml (computed here, never by the agent), redteam.yaml (the agent's evaluator read),
builds/vN/ (the submission pack: Word, PDF, Excel matrix, portal fields as JSON, the proposal deck). Journey
Qualify → Understand → Answer → Price → Review → Submit → Learn, each step a checkpoint a named person decides:

  rfp.requirements  every requirement with id, text, page reference, kind, deadline, format rules, evaluation (table)
  rfp.gonogo        the go / no-go recommendation with reasons; a named person decides (text)
  rfp.matrix        Comply / Partial / Not / Alternative per requirement with evidence — only library items
                    (rfp_library, full-text search) and registry facts; anything else fails the check → fix round
  rfp.price         rate cards per tenant × effort per wave and module + licences + run & support, in the buyer's
                    currency, computed in Python (table)
  rfp.review ×3     technical, commercial, legal reviewers, with the agent's red-team findings as evidence
  rfp.submit        the pack in the buyer's required format + the proposal deck; accepted by a named person;
                    "submitted" records who / when / how (portal by hand, or mail through the mailer) — nothing
                    is sent automatically
  Learn             win / loss and buyer feedback; the answers of a won response are promoted into rfp_library (audited).

Portals (SAP Ariba, Coupa, Jaggaer, GeM, Loopio, Responsive) are listed, not integrated: exports and portal fields in P11."""
from __future__ import annotations

import asyncio
import json
import os
import re
import secrets
import shutil
import time
from pathlib import Path

import yaml
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

from genbi_kit import reader
from genbi_kit.docs import build as docs_build
from genbi_kit.docs import checks as docs_checks

from . import auth, checkpoints, db, mailer, notify, registry, rfp_prompts, store, worker

router = APIRouter()

KIND = "rfp"
MODULE = "RFP & bid response"
ROUTE = "#/rfp"
CP = {"requirements": "rfp.requirements", "gonogo": "rfp.gonogo", "matrix": "rfp.matrix", "price": "rfp.price", "review": "rfp.review", "submit": "rfp.submit"}
REVIEWS = [("technical", "Technical review"), ("commercial", "Commercial review"), ("legal", "Legal review")]
STATUSES = ("Comply", "Partial", "Not", "Alternative")
REQ_KINDS = ("mandatory", "scored", "information")
BUYER_TYPES = ("public", "private", "ngo", "government")
STATUS_LABEL = {"queued": "Queued", "qualifying": "Relay is reading the pack", "awaiting_requirements": "Your turn: confirm the requirements", "awaiting_gonogo": "Go / no-go: a named person decides",
                "no_go": "No-go", "answering": "Relay is drafting the matrix", "awaiting_matrix": "Your turn: the compliance matrix", "pricing": "Your turn: price it",
                "awaiting_price": "Your turn: confirm the price", "redteam": "Relay is reading it as the evaluator", "awaiting_reviews": "Reviews: technical, commercial, legal",
                "packing": "Building the submission pack", "awaiting_submit": "Your turn: accept the pack", "ready": "Ready to submit", "submitted": "Submitted", "won": "Won", "lost": "Lost",
                "withdrawn": "Withdrawn", "error": "Needs attention"}
RUNNING = {"queued", "qualifying", "answering", "redteam", "packing"}
PLATFORMS = [{"name": "SAP Ariba", "how": "portal fields exported as JSON; upload by hand"}, {"name": "Coupa", "how": "portal fields exported as JSON; upload by hand"},
             {"name": "Jaggaer", "how": "Word / PDF / Excel exports; upload by hand"}, {"name": "GeM (India)", "how": "portal fields and PDF; upload by hand"},
             {"name": "Loopio", "how": "answers exported as Excel; import by hand"}, {"name": "Responsive", "how": "answers exported as Excel; import by hand"},
             {"name": "Buyer portals & e-mail", "how": "mail through your own sending account after the submit checkpoint"}]
MAX_BYTES = int(os.environ.get("D2D_RFP_MAX_MB", "200")) * 1024 * 1024
TEST_HOOKS = os.environ.get("D2D_TEST_HOOKS") == "1"
SAFE = re.compile(r"[^\w.\- ]+")
STOP = {"the", "and", "shall", "must", "will", "with", "that", "this", "from", "have", "been", "which", "their", "supplier", "vendor", "bidder", "provide", "should", "into", "than", "such", "each", "all", "any", "for", "are", "our", "its"}

db.register_schema("""
CREATE TABLE IF NOT EXISTS rfp_library (
  id TEXT PRIMARY KEY, title TEXT NOT NULL, text TEXT NOT NULL, module TEXT, buyer_type TEXT, tags TEXT NOT NULL DEFAULT '[]',
  kind TEXT NOT NULL DEFAULT 'answer', origin TEXT, response_id TEXT, requirement_id TEXT, won INTEGER NOT NULL DEFAULT 0,
  uses INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL, created_by TEXT);
CREATE INDEX IF NOT EXISTS rfp_library_module ON rfp_library (module, buyer_type);
CREATE TABLE IF NOT EXISTS rfp_rate_cards (
  id TEXT PRIMARY KEY, role TEXT NOT NULL, rate REAL NOT NULL, currency TEXT NOT NULL DEFAULT 'INR', unit TEXT NOT NULL DEFAULT 'day',
  updated REAL NOT NULL, updated_by TEXT);
""")
if db.BACKEND == "sqlite":        # full-text search over the library (SQLite FTS5); Postgres uses LIKE over tokens
    db.register_schema("CREATE VIRTUAL TABLE IF NOT EXISTS rfp_library_fts USING fts5(id UNINDEXED, title, text, module, buyer_type, tags);")


class RfpError(Exception):
    pass


# ---------------------------------------------------------------- the past-responses library (tenant-scoped, full-text search)

def _fts_sync() -> None:
    """The FTS table mirrors rfp_library (rebuilt when their counts differ, e.g. after a restore)."""
    if db.BACKEND != "sqlite":
        return
    n = db.one("SELECT COUNT(*) AS n FROM rfp_library")["n"]
    m = db.one("SELECT COUNT(*) AS n FROM rfp_library_fts")["n"]
    if n != m:
        db.run("DELETE FROM rfp_library_fts")
        for r in db.q("SELECT id, title, text, module, buyer_type, tags FROM rfp_library"):
            db.run("INSERT INTO rfp_library_fts (id, title, text, module, buyer_type, tags) VALUES (?, ?, ?, ?, ?, ?)", (r["id"], r["title"], r["text"], r["module"] or "", r["buyer_type"] or "", r["tags"]))


def _row_public(r: dict) -> dict:
    out = dict(r)
    try:
        out["tags"] = json.loads(r.get("tags") or "[]")
    except ValueError:
        out["tags"] = []
    out["won"] = bool(r.get("won"))
    return out


def library_add(title: str, text: str, module: str | None = None, buyer_type: str | None = None, tags: list[str] | None = None, kind: str = "answer",
                origin: str | None = None, response_id: str | None = None, requirement_id: str | None = None, won: bool = False, who: str | None = None) -> dict:
    title, text = " ".join((title or "").split())[:200], (text or "").strip()[:8000]
    if not title or not text:
        raise RfpError("A library item needs a title and its text.")
    if module and module not in registry.BY_ID:
        raise RfpError(f"Unknown module id {module!r}.")
    if buyer_type and buyer_type not in BUYER_TYPES:
        raise RfpError(f"Buyer type must be one of {', '.join(BUYER_TYPES)}.")
    if kind not in ("answer", "case_study", "reference"):
        raise RfpError("Kind must be answer, case_study or reference.")
    lid = "lib-" + secrets.token_hex(4)
    tags_j = json.dumps([str(t)[:40] for t in (tags or [])][:12])
    db.run("INSERT INTO rfp_library (id, title, text, module, buyer_type, tags, kind, origin, response_id, requirement_id, won, created, created_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
           (lid, title, text, module, buyer_type, tags_j, kind, origin, response_id, requirement_id, 1 if won else 0, time.time(), who))
    if db.BACKEND == "sqlite":
        db.run("INSERT INTO rfp_library_fts (id, title, text, module, buyer_type, tags) VALUES (?, ?, ?, ?, ?, ?)", (lid, title, text, module or "", buyer_type or "", tags_j))
    db.audit("rfp.library_add", lid, {"title": title, "module": module, "kind": kind, "origin": origin, "won": won}, who)
    return _row_public(db.one("SELECT * FROM rfp_library WHERE id = ?", (lid,)))


def library_remove(lid: str, who: str | None = None) -> None:
    db.run("DELETE FROM rfp_library WHERE id = ?", (lid,))
    if db.BACKEND == "sqlite":
        db.run("DELETE FROM rfp_library_fts WHERE id = ?", (lid,))
    db.audit("rfp.library_remove", lid, None, who)


def library_items(ids: list[str]) -> list[dict]:
    out = []
    for lid in ids:
        r = db.one("SELECT * FROM rfp_library WHERE id = ?", (lid,))
        if r:
            out.append(_row_public(r))
    return out


def library_list(limit: int = 100, module: str | None = None, buyer_type: str | None = None, q: str = "") -> list[dict]:
    if q.strip():
        return library_search(q, limit, module, buyer_type)
    sql, args = "SELECT * FROM rfp_library WHERE 1 = 1", []
    if module:
        sql += " AND module = ?"; args.append(module)
    if buyer_type:
        sql += " AND buyer_type = ?"; args.append(buyer_type)
    return [_row_public(r) for r in db.q(sql + " ORDER BY won DESC, created DESC LIMIT ?", (*args, min(limit, 500)))]


def _terms(text: str) -> list[str]:
    words = [w.lower() for w in re.findall(r"[A-Za-z][A-Za-z-]{3,}", text or "")]
    seen, out = set(), []
    for w in words:
        if w not in STOP and w not in seen:
            seen.add(w)
            out.append(w)
    return out[:12]


def library_search(query: str, limit: int = 10, module: str | None = None, buyer_type: str | None = None) -> list[dict]:
    terms = _terms(query)
    if not terms:
        return []
    if db.BACKEND == "sqlite":
        _fts_sync()
        match = " OR ".join('"' + t.replace('"', "") + '"' for t in terms)
        rows = db.q("SELECT l.* FROM rfp_library_fts f JOIN rfp_library l ON l.id = f.id WHERE rfp_library_fts MATCH ? ORDER BY bm25(rfp_library_fts) LIMIT ?", (match, min(limit * 3, 200)))
    else:
        rows = db.q("SELECT * FROM rfp_library WHERE " + " OR ".join("lower(title || ' ' || text) LIKE ?" for _ in terms) + " LIMIT ?", (*[f"%{t}%" for t in terms], min(limit * 3, 200)))
        rows.sort(key=lambda r: -sum(1 for t in terms if t in (r["title"] + " " + r["text"]).lower()))
    out = [_row_public(r) for r in rows if (not module or r.get("module") == module) and (not buyer_type or r.get("buyer_type") == buyer_type)]
    return out[:limit]


# ---------------------------------------------------------------- rate cards per tenant

def rate_cards() -> list[dict]:
    return db.q("SELECT * FROM rfp_rate_cards ORDER BY role")


def set_rate_cards(rows: list[dict], who: str | None) -> list[dict]:
    clean = []
    for r in rows:
        role = " ".join(str(r.get("role") or "").split())[:80]
        try:
            rate = float(r.get("rate"))
        except (TypeError, ValueError):
            raise RfpError(f"Rate for {role or 'a role'} must be a number.")
        if not role or rate < 0:
            raise RfpError("Every rate card line needs a role and a rate of zero or more.")
        currency = str(r.get("currency") or "INR").strip().upper()[:6]
        unit = str(r.get("unit") or "day").strip().lower()
        if unit not in ("day", "hour"):
            raise RfpError("Unit must be day or hour.")
        clean.append((role, rate, currency, unit))
    with db.transaction():
        db.run("DELETE FROM rfp_rate_cards")
        for role, rate, currency, unit in clean:
            db.run("INSERT INTO rfp_rate_cards (id, role, rate, currency, unit, updated, updated_by) VALUES (?, ?, ?, ?, ?, ?, ?)", ("rc-" + secrets.token_hex(3), role, rate, currency, unit, time.time(), who))
    db.audit("rfp.rate_cards", None, {"roles": [c[0] for c in clean]}, who)
    return rate_cards()


# ---------------------------------------------------------------- the folder, the checks on the agent's files

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


def _yaml(d: Path, name: str) -> dict | None:
    p = d / name
    if not p.exists():
        return None
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return None
    return raw if isinstance(raw, dict) else None


def _s(v) -> str:
    return "" if v is None else str(v).strip()


def check_requirements(d: Path, st: dict) -> list[str]:
    problems = []
    raw = _yaml(d, "requirements.yaml")
    if raw is None:
        return ["requirements.yaml was not written or does not parse as a mapping"]
    buyer = raw.get("buyer") if isinstance(raw.get("buyer"), dict) else {}
    if not _s(buyer.get("name")):
        problems.append("buyer.name is missing")
    if _s(buyer.get("type")) and _s(buyer.get("type")).lower() not in BUYER_TYPES:
        problems.append(f"buyer.type must be one of {', '.join(BUYER_TYPES)}")
    reqs = raw.get("requirements")
    if not isinstance(reqs, list) or not reqs:
        problems.append("requirements is empty — list every requirement in the pack")
        reqs = []
    files = {a["name"] for a in st.get("attachments") or []}
    ids: set[str] = set()
    for i, r in enumerate(reqs, 1):
        if not isinstance(r, dict):
            problems.append(f"requirements[{i}] must be a mapping")
            continue
        rid = _s(r.get("id"))
        if not rid:
            problems.append(f"requirements[{i}] needs an id")
        elif rid in ids:
            problems.append(f"requirement id {rid} is used twice")
        ids.add(rid)
        if not _s(r.get("text")):
            problems.append(f"requirement {rid or i} needs its text")
        if _s(r.get("page")) == "":
            problems.append(f"requirement {rid or i} needs a page (or sheet) reference")
        src = _s(r.get("source"))
        if not src:
            problems.append(f"requirement {rid or i} needs its source file")
        elif files and src not in files:
            problems.append(f"requirement {rid or i}: source {src!r} is not one of the attachments ({', '.join(sorted(files))[:160]})")
        if _s(r.get("kind")).lower() not in REQ_KINDS:
            problems.append(f"requirement {rid or i}: kind must be mandatory, scored or information")
        try:
            c = float(r.get("confidence", 1))
            if not 0 <= c <= 1:
                raise ValueError
        except (TypeError, ValueError):
            problems.append(f"requirement {rid or i}: confidence must be a number between 0 and 1")
    g = _yaml(d, "gonogo.yaml")
    if g is None:
        problems.append("gonogo.yaml was not written or does not parse as a mapping")
    else:
        if _s(g.get("recommendation")).lower() not in ("go", "no-go"):
            problems.append("gonogo.recommendation must be go or no-go")
        if not isinstance(g.get("reasons"), list) or not g["reasons"]:
            problems.append("gonogo.reasons is empty")
        for f in g.get("fit") or []:
            if not isinstance(f, dict) or _s(f.get("module")) not in registry.BY_ID:
                problems.append(f"gonogo.fit: module {(f or {}).get('module') if isinstance(f, dict) else f!r} is not in the registry")
    return problems


def requirements_view(d: Path) -> dict:
    raw = _yaml(d, "requirements.yaml") or {}
    g = _yaml(d, "gonogo.yaml") or {}
    rows = []
    for r in raw.get("requirements") or []:
        if isinstance(r, dict):
            rows.append({"id": _s(r.get("id")), "text": _s(r.get("text")), "page": _s(r.get("page")), "source": _s(r.get("source")), "section": _s(r.get("section")),
                         "kind": _s(r.get("kind")).lower(), "confidence": float(r.get("confidence", 1)) if str(r.get("confidence", "")).replace(".", "", 1).isdigit() else None})
    buyer = raw.get("buyer") if isinstance(raw.get("buyer"), dict) else {}
    fmt = raw.get("format") if isinstance(raw.get("format"), dict) else {}
    sections = sorted({r["section"] for r in rows if r["section"]})
    return {"buyer": {k: _s(buyer.get(k)) for k in ("name", "type", "country", "currency")}, "deadline": _s(raw.get("deadline")),
            "format": {"submission": _s(fmt.get("submission")), "portal": _s(fmt.get("portal")), "rules": [_s(x) for x in fmt.get("rules") or []]},
            "evaluation": [{"criterion": _s(e.get("criterion")), "weight": e.get("weight")} for e in raw.get("evaluation") or [] if isinstance(e, dict)],
            "facts": [_s(x) for x in raw.get("facts") or []], "requirements": rows, "sections": sections,
            "counts": {"requirements": len(rows), "mandatory": sum(1 for r in rows if r["kind"] == "mandatory"), "scored": sum(1 for r in rows if r["kind"] == "scored"),
                       "information": sum(1 for r in rows if r["kind"] == "information"), "sections": len(sections), "low_confidence": sum(1 for r in rows if r["confidence"] is not None and r["confidence"] < 0.8)},
            "gonogo": {"recommendation": _s(g.get("recommendation")).lower(), "reasons": [_s(x) for x in g.get("reasons") or []], "risks": [_s(x) for x in g.get("risks") or []],
                       "fit": [{"module": _s(f.get("module")), "name": registry.BY_ID.get(_s(f.get("module")), {}).get("name", _s(f.get("module"))), "requirements": f.get("requirements")} for f in g.get("fit") or [] if isinstance(f, dict)],
                       "effort": _s(g.get("effort")), "deadline_ok": g.get("deadline_ok")}}


def _library_ids(d: Path) -> set[str]:
    try:
        data = json.loads((d / "sources" / "library.json").read_text(encoding="utf-8"))
        return {str(i["id"]) for i in data.get("items") or [] if isinstance(i, dict)}
    except (OSError, ValueError):
        return set()


def check_matrix(d: Path) -> list[str]:
    raw = _yaml(d, "matrix.yaml")
    if raw is None:
        return ["matrix.yaml was not written or does not parse as a mapping"]
    v = requirements_view(d)
    want = {r["id"] for r in v["requirements"]}
    lib = _library_ids(d)
    rows = raw.get("rows")
    if not isinstance(rows, list) or not rows:
        return ["matrix.rows is empty — one row per requirement"]
    problems, seen = [], set()
    for i, r in enumerate(rows, 1):
        if not isinstance(r, dict):
            problems.append(f"rows[{i}] must be a mapping")
            continue
        rid = _s(r.get("id"))
        if rid not in want:
            problems.append(f"row {i}: id {rid!r} is not a confirmed requirement")
        elif rid in seen:
            problems.append(f"requirement {rid} has two rows")
        seen.add(rid)
        status = _s(r.get("status")).capitalize()
        if status not in STATUSES:
            problems.append(f"{rid or i}: status must be Comply, Partial, Not or Alternative")
        if not _s(r.get("answer")):
            problems.append(f"{rid or i}: answer is empty")
        ev = r.get("evidence") or []
        if not isinstance(ev, list):
            problems.append(f"{rid or i}: evidence must be a list")
            ev = []
        for ref in ev:
            ref = _s(ref)
            scheme, _, rest = ref.partition(":")
            if scheme == "module":
                if rest not in registry.BY_ID:
                    problems.append(f"{rid or i}: evidence {ref} — no such module in the registry")
            elif scheme == "library":
                if rest not in lib:
                    problems.append(f"{rid or i}: evidence {ref} — not one of the library items picked for this response (sources/library.json); an answer may cite only library items and registry modules")
            else:
                problems.append(f"{rid or i}: evidence {ref!r} is not a module:<id> or library:<id> reference — nothing else may be cited")
        if status in ("Comply", "Partial", "Alternative") and not ev:
            problems.append(f"{rid or i}: a {status} answer needs at least one piece of evidence")
    missing = sorted(want - seen)
    if missing:
        problems.append(f"{len(missing)} requirement(s) have no row: " + ", ".join(missing[:10]) + (" …" if len(missing) > 10 else ""))
    return problems


def matrix_view(d: Path) -> dict:
    raw = _yaml(d, "matrix.yaml") or {}
    v = requirements_view(d)
    by = {r["id"]: r for r in v["requirements"]}
    lib = {i["id"]: i for i in library_items(sorted(_library_ids(d)))}
    rows = []
    for r in raw.get("rows") or []:
        if isinstance(r, dict):
            rid = _s(r.get("id"))
            evs = []
            for ref in r.get("evidence") or []:
                ref = _s(ref)
                scheme, _, rest = ref.partition(":")
                evs.append({"ref": ref, "kind": scheme, "name": registry.BY_ID.get(rest, {}).get("name") if scheme == "module" else (lib.get(rest) or {}).get("title") or rest,
                            "ok": (rest in registry.BY_ID) if scheme == "module" else rest in lib})
            rows.append({"id": rid, "status": _s(r.get("status")).capitalize(), "answer": _s(r.get("answer")), "evidence": evs, "note": _s(r.get("note")),
                         "requirement": (by.get(rid) or {}).get("text", ""), "kind": (by.get(rid) or {}).get("kind", ""), "page": (by.get(rid) or {}).get("page", ""), "section": (by.get(rid) or {}).get("section", "")})
    rows.sort(key=lambda r: r["id"])
    counts = {s.lower(): sum(1 for r in rows if r["status"] == s) for s in STATUSES}
    summ = raw.get("summary") if isinstance(raw.get("summary"), dict) else {}
    return {"rows": rows, "counts": {**counts, "rows": len(rows), "with_evidence": sum(1 for r in rows if r["evidence"])}, "themes": [_s(x) for x in summ.get("themes") or []],
            "evidence_used": sorted({e["ref"] for r in rows for e in r["evidence"]})}


def check_redteam(d: Path) -> list[str]:
    raw = _yaml(d, "redteam.yaml")
    if raw is None:
        return ["redteam.yaml was not written or does not parse as a mapping"]
    ids = {r["id"] for r in requirements_view(d)["requirements"]} | {"general"}
    fs = raw.get("findings")
    if not isinstance(fs, list) or not fs:
        return ["redteam.findings is empty"]
    problems = []
    for i, f in enumerate(fs, 1):
        if not isinstance(f, dict):
            problems.append(f"findings[{i}] must be a mapping")
            continue
        if _s(f.get("requirement")) not in ids:
            problems.append(f"finding {i}: requirement {f.get('requirement')!r} is not a requirement id (or 'general')")
        if _s(f.get("severity")).lower() not in ("high", "medium", "low"):
            problems.append(f"finding {i}: severity must be high, medium or low")
        if not _s(f.get("finding")):
            problems.append(f"finding {i}: finding text is empty")
    return problems


def redteam_view(d: Path) -> dict:
    raw = _yaml(d, "redteam.yaml") or {}
    fs = [{"requirement": _s(f.get("requirement")), "severity": _s(f.get("severity")).lower(), "finding": _s(f.get("finding")), "suggestion": _s(f.get("suggestion"))}
          for f in raw.get("findings") or [] if isinstance(f, dict)]
    order = {"high": 0, "medium": 1, "low": 2}
    fs.sort(key=lambda f: order.get(f["severity"], 3))
    return {"findings": fs, "summary": _s(raw.get("summary")), "counts": {k: sum(1 for f in fs if f["severity"] == k) for k in ("high", "medium", "low")}}


# ---------------------------------------------------------------- pricing (Python only)

def compute_price(body: dict) -> dict:
    """Effort per wave and module × the tenant's rate cards (converted with the fx map into the buyer's currency),
    plus licences and run & support; a discount at the end. Every line kept, so the checkpoint shows the maths."""
    cards = {c["role"].lower(): c for c in rate_cards()}
    if not cards:
        raise RfpError("No rate cards yet: add roles and rates under RFP › Rate cards first.")
    currency = _s(body.get("currency")).upper() or "INR"
    fx = {str(k).upper(): float(v) for k, v in (body.get("fx") or {}).items() if v}
    waves, total_days = [], 0.0
    for w in body.get("waves") or []:
        if not isinstance(w, dict):
            continue
        lines, wave_total = [], 0.0
        for ln in w.get("lines") or []:
            if not isinstance(ln, dict):
                continue
            role = _s(ln.get("role"))
            card = cards.get(role.lower())
            if not card:
                raise RfpError(f"No rate card for the role {role!r}: add it under Rate cards, or pick one of {', '.join(sorted(c['role'] for c in cards.values()))}.")
            try:
                days = float(ln.get("days") or 0)
            except (TypeError, ValueError):
                raise RfpError(f"Days for {role} must be a number.")
            if days < 0:
                raise RfpError("Days cannot be negative.")
            units = days * (8 if card["unit"] == "hour" else 1)
            card_amount = units * float(card["rate"])
            rate_fx = 1.0 if card["currency"].upper() == currency else fx.get(card["currency"].upper())
            if rate_fx is None:
                raise RfpError(f"No exchange rate from {card['currency']} to {currency}: give fx[{card['currency']}].")
            amount = round(card_amount * rate_fx, 2)
            module = _s(ln.get("module"))
            lines.append({"role": card["role"], "module": module, "module_name": registry.BY_ID.get(module, {}).get("name", module), "days": days, "rate": float(card["rate"]),
                          "rate_currency": card["currency"], "unit": card["unit"], "fx": rate_fx, "amount": amount})
            wave_total += amount
            total_days += days
        waves.append({"name": _s(w.get("name")) or f"Wave {len(waves) + 1}", "lines": lines, "total": round(wave_total, 2), "days": sum(x["days"] for x in lines)})
    licences = []
    for lc in body.get("licences") or []:
        if not isinstance(lc, dict) or not _s(lc.get("item")):
            continue
        try:
            qty, unit, months = float(lc.get("qty") or 0), float(lc.get("unit") or 0), float(lc.get("months") or 1)
        except (TypeError, ValueError):
            raise RfpError(f"Licence {lc.get('item')}: qty, unit and months must be numbers.")
        licences.append({"item": _s(lc.get("item")), "qty": qty, "unit": unit, "months": months, "amount": round(qty * unit * months, 2)})
    run = []
    for r in body.get("run_support") or []:
        if not isinstance(r, dict) or not _s(r.get("item")):
            continue
        try:
            months, per = float(r.get("months") or 0), float(r.get("per_month") or 0)
        except (TypeError, ValueError):
            raise RfpError(f"Run & support {r.get('item')}: months and per_month must be numbers.")
        run.append({"item": _s(r.get("item")), "months": months, "per_month": per, "amount": round(months * per, 2)})
    try:
        discount_pct = float(body.get("discount_pct") or 0)
    except (TypeError, ValueError):
        raise RfpError("Discount must be a number.")
    if not 0 <= discount_pct <= 100:
        raise RfpError("Discount must be between 0 and 100 per cent.")
    effort = round(sum(w["total"] for w in waves), 2)
    lic = round(sum(x["amount"] for x in licences), 2)
    rs = round(sum(x["amount"] for x in run), 2)
    subtotal = round(effort + lic + rs, 2)
    discount = round(subtotal * discount_pct / 100, 2)
    return {"currency": currency, "fx": fx, "waves": waves, "licences": licences, "run_support": run, "discount_pct": discount_pct,
            "totals": {"effort": effort, "days": total_days, "licences": lic, "run_support": rs, "subtotal": subtotal, "discount": discount, "total": round(subtotal - discount, 2)},
            "computed": time.time(), "note": "computed from the tenant's rate cards; the agent never prices"}


def price_evidence(p: dict) -> dict:
    cur = p["currency"]
    rows = [{"line": f"{w['name']}: {ln['role']}" + (f" ({ln['module_name']})" if ln.get("module") else ""), "days": ln["days"], "amount": ln["amount"]} for w in p["waves"] for ln in w["lines"]]
    rows += [{"line": f"Licence: {x['item']} × {x['qty']:g} × {x['months']:g} months", "amount": x["amount"]} for x in p["licences"]]
    rows += [{"line": f"Run & support: {x['item']} × {x['months']:g} months", "amount": x["amount"]} for x in p["run_support"]]
    t = p["totals"]
    return {"summary": f"Total {t['total']:,.2f} {cur} (effort {t['effort']:,.2f}, licences {t['licences']:,.2f}, run & support {t['run_support']:,.2f}" + (f", discount {t['discount']:,.2f}" if t["discount"] else "") + ")",
            "counts": {"waves": len(p["waves"]), "days": t["days"], "lines": len(rows)}, "items": [f"{r['line']}: {r['amount']:,.2f} {cur}" for r in rows[:10]], "rows": rows, "totals": t, "currency": cur}


# ---------------------------------------------------------------- the submission pack (through the studio engine)

def _write_sources(d: Path) -> None:
    """JSON snapshots of the YAML records, so the generated deck's figures carry record: sources that resolve."""
    sdir = d / "sources"
    sdir.mkdir(exist_ok=True)
    rv, mv = requirements_view(d), matrix_view(d)
    p = _yaml(d, "pricing.yaml") or {}
    (sdir / "requirements.json").write_text(json.dumps({**rv, "count": rv["counts"]["requirements"]}, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    (sdir / "matrix.json").write_text(json.dumps({"summary": mv["counts"], "rows": mv["rows"], "evidence": mv["evidence_used"]}, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    (sdir / "pricing.json").write_text(json.dumps(p, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    (sdir / "registry.json").write_text(json.dumps({"modules": {m["id"]: {"id": m["id"], "name": m["name"], "sub": m["sub"], "text": m["text"], "platforms": m["platforms"], "status": m["status"]}
                                                                for m in registry.MODULES if m["pl"] not in ("hidden", "platform")}}, indent=1, ensure_ascii=False), encoding="utf-8")
    b = registry.brand()
    tpl = registry.templates()
    info = {"name": b["name"], "full": b["full"], "partner": b["partner"], "color": b["color"], "house_style": tpl["house_style"], "template": "tenant" if tpl["pptx"] else "relay"}
    if tpl["pptx"]:
        (sdir / "template.pptx").write_bytes(tpl["pptx"])
        info["template_pptx_file"] = "sources/template.pptx"
    if tpl["docx"]:
        (sdir / "template.docx").write_bytes(tpl["docx"])
        info["template_docx_file"] = "sources/template.docx"
    (sdir / "brand.json").write_text(json.dumps(info, indent=1), encoding="utf-8")


def _q(s: str) -> str:
    return json.dumps(str(s))                        # a YAML-safe double-quoted scalar


def _amt(v, cur: str) -> str:
    return f"{float(v or 0):,.2f} {cur}".strip()


def _rule_figures(rules: list[str], indent: str) -> list[str]:
    """YAML `figures` lines for every number inside the buyer's format rules, sourced to the confirmed requirements record."""
    from genbi_kit.docs import spec as docs_spec
    out = []
    for i, rule in enumerate(rules):
        for tok in docs_spec.figure_tokens(rule):
            out.append(f"{indent}- {{text: {_q(tok)}, source: \"record:requirements#format.rules.{i}\"}}")
    return out


def deck_yaml(st: dict, rv: dict, mv: dict, p: dict) -> str:
    """The proposal deck from the confirmed records: every number a declared figure with a record: source."""
    buyer = rv["buyer"]["name"] or st.get("buyer") or "the buyer"
    c = mv["counts"]
    t = p.get("totals") or {}
    cur = p.get("currency") or rv["buyer"]["currency"] or ""
    fit = [f for f in rv["gonogo"]["fit"] if f["module"] in registry.BY_ID][:6]
    ev_rows = []
    lib = {i["id"]: i for i in library_items([e.split(":", 1)[1] for e in mv["evidence_used"] if e.startswith("library:")])}
    for ref in mv["evidence_used"][:12]:
        scheme, _, rest = ref.partition(":")
        name = registry.BY_ID.get(rest, {}).get("name") if scheme == "module" else (lib.get(rest) or {}).get("title", rest)
        ev_rows.append([("Relay module" if scheme == "module" else "Past response / case study"), name or rest])
    lines = ["kind: deck", f"title: {_q('Response to ' + buyer)}", f"subtitle: {_q(st.get('name') or 'Proposal and compliance summary')}", f"audience: {_q(buyer)}",
             f"date: {_q(time.strftime('%Y-%m-%d'))}", "template: " + ("tenant" if (registry.templates()["pptx"]) else "relay"), "sections:",
             "  - title: What you asked for", "    slides:", "      - layout: title", f"        title: {_q('Response to ' + buyer)}", f"        subtitle: {_q(st.get('name') or '')}",
             "      - layout: bullets", "        title: What you asked for",
             "        bullets:", f"          - {_q(str(c['rows']) + ' requirements read from the pack, every one with its page reference')}",
             f"          - {_q('Deadline: ' + (rv['deadline'] or 'as stated in the pack'))}"]
    for rule in rv["format"]["rules"][:3]:
        lines.append(f"          - {_q('Format: ' + rule)}")
    lines += ["        figures:", f"          - {{text: {_q(str(c['rows']))}, value: {c['rows']}, source: \"record:requirements#count\"}}"] + _rule_figures(rv["format"]["rules"][:3], "          ")
    lines += [
              f"        notes: {_q('Counts from the confirmed requirements list; the deadline and format rules as the pack states them.')}",
              "  - title: How we comply", "    slides:", "      - layout: chart", "        title: How we comply",
              "        chart:", "          type: column", "          categories: [Comply, Partial, Alternative, Not]",
              f"          series: [{{name: Requirements, values: [{c['comply']}, {c['partial']}, {c['alternative']}, {c['not']}]}}]",
              "          unit: requirements", "          source: \"record:matrix#summary\"",
              f"          alt: {_q(str(c['comply']) + ' comply, ' + str(c['partial']) + ' partial, ' + str(c['alternative']) + ' alternative, ' + str(c['not']) + ' not — of ' + str(c['rows']) + ' requirements')}",
              f"        notes: {_q('Every status in the compliance matrix carries its evidence: a Relay module or a past response.')}"]
    if fit:
        lines += ["      - layout: bullets", "        title: Our approach, module by module", "        bullets:"]
        for f in fit:
            m = registry.BY_ID[f["module"]]
            lines.append(f"          - {_q(m['name'] + ': ' + m['sub'])}")
        lines.append(f"        notes: {_q('The modules the requirements map to, from the go / no-go fit analysis.')}")
    if ev_rows:
        lines += ["      - layout: table", "        title: The evidence behind the answers", "        table:", "          columns: [Kind, Evidence]", "          rows:"]
        for k, n in ev_rows:
            lines.append(f"            - [{_q(k)}, {_q(n)}]")
        lines += ["          source: \"record:matrix#evidence\"", "          caption: Only Relay modules and the tenant's own past responses are cited"]
    if t:
        lines += ["  - title: Price", "    slides:", "      - layout: table", "        title: Price summary", "        table:", "          columns: [Item, Amount]", "          rows:"]
        for w in p.get("waves") or []:
            lines.append(f"            - [{_q(w['name'] + ' (' + str(w['days']) + ' days)')}, {_q(_amt(w['total'], cur))}]")
        for k, label in (("licences", "Licences"), ("run_support", "Run & support"), ("discount", "Discount"), ("total", "Total")):
            if t.get(k) or k == "total":
                lines.append(f"            - [{_q(label)}, {_q(_amt(t[k], cur))}]")
        lines += ["          source: \"record:pricing#totals\"", f"          caption: {_q('Computed from the rate cards in ' + cur + '; commercial terms per the submission pack')}"]
    lines += ["  - title: Next steps", "    slides:", "      - layout: bullets", "        title: Next steps",
              "        bullets:", f"          - {_q('Clarification questions by the dates in the pack')}", f"          - {_q('Reference calls on request')}", f"          - {_q('Mobilisation within the first wave after award')}",
              "      - layout: closing", "        title: Thank you", f"        bullets: [{_q(registry.brand()['full'])}]"]
    return "\n".join(lines) + "\n"


def response_yaml(st: dict, rv: dict, mv: dict, p: dict) -> str:
    """The written response as a document: buyer, deadline, the compliance matrix (status, answer, evidence), the price."""
    buyer = rv["buyer"]["name"] or st.get("buyer") or "the buyer"
    c = mv["counts"]
    lines = ["kind: doc", f"title: {_q('Response to ' + buyer)}", f"subtitle: {_q(st.get('name') or 'RFP response')}", f"audience: {_q(buyer)}", f"date: {_q(time.strftime('%Y-%m-%d'))}",
             "template: " + ("tenant" if registry.templates()["docx"] else "relay"), "sections:",
             "  - title: Understanding", "    blocks:", "      - kind: paragraph",
             f"        text: {_q('This response answers the ' + str(c['rows']) + ' requirements of the pack, each with its evidence. Deadline: ' + (rv['deadline'] or 'as stated in the pack') + '.')}",
             f"        figures: [{{text: {_q(str(c['rows']))}, value: {c['rows']}, source: \"record:requirements#count\"}}]"]
    if rv["format"]["rules"]:
        lines += ["      - kind: bullets", "        title: Format rules we follow", "        bullets:"] + [f"          - {_q(r)}" for r in rv["format"]["rules"][:8]]
        figs = _rule_figures(rv["format"]["rules"][:8], "          ")
        if figs:
            lines += ["        figures:"] + figs
    lines += ["  - title: Compliance matrix", "    blocks:", "      - kind: chart", "        chart:", "          type: bar", "          categories: [Comply, Partial, Alternative, Not]",
              f"          series: [{{name: Requirements, values: [{c['comply']}, {c['partial']}, {c['alternative']}, {c['not']}]}}]", "          unit: requirements",
              "          source: \"record:matrix#summary\"", f"          alt: {_q('Compliance: ' + str(c['comply']) + ' comply, ' + str(c['partial']) + ' partial, ' + str(c['alternative']) + ' alternative, ' + str(c['not']) + ' not')}"]
    rows = mv["rows"]
    for i in range(0, len(rows), 12):
        chunk = rows[i:i + 12]
        lines += ["      - kind: table", "        table:", "          columns: [Id, Status, Requirement, Answer, Evidence]", "          rows:"]
        for r in chunk:
            lines.append(f"            - [{_q(r['id'])}, {_q(r['status'])}, {_q(r['requirement'][:160])}, {_q(r['answer'][:600])}, {_q('; '.join(e['name'] or e['ref'] for e in r['evidence']))}]")
        lines += ["          source: \"record:matrix#rows\"", f"          caption: {_q('Requirements ' + chunk[0]['id'] + ' to ' + chunk[-1]['id'])}"]
    if p.get("totals"):
        t, cur = p["totals"], p["currency"]
        lines += ["  - title: Price", "    blocks:", "      - kind: table", "        table:", "          columns: [Item, Amount]", "          rows:"]
        for w in p.get("waves") or []:
            lines.append(f"            - [{_q(w['name'])}, {_q(_amt(w['total'], cur))}]")
        for k, label in (("licences", "Licences"), ("run_support", "Run & support"), ("discount", "Discount"), ("total", "Total")):
            if t.get(k) or k == "total":
                lines.append(f"            - [{_q(label)}, {_q(_amt(t[k], cur))}]")
        lines += ["          source: \"record:pricing#totals\"", f"          caption: {_q('All amounts in ' + cur + ', computed from the rate cards')}"]
    return "\n".join(lines) + "\n"


def _xlsx(d: Path, out: Path, rv: dict, mv: dict) -> None:
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Compliance matrix"
    ws.append(["Id", "Section", "Kind", "Page", "Requirement", "Status", "Answer", "Evidence", "Note"])
    for r in mv["rows"]:
        ws.append([r["id"], r["section"], r["kind"], r["page"], r["requirement"], r["status"], r["answer"], "; ".join(e["name"] or e["ref"] for e in r["evidence"]), r["note"]])
    ws2 = wb.create_sheet("Requirements")
    ws2.append(["Id", "Section", "Kind", "Page", "Source", "Requirement", "Confidence"])
    for r in rv["requirements"]:
        ws2.append([r["id"], r["section"], r["kind"], r["page"], r["source"], r["text"], r["confidence"]])
    ws3 = wb.create_sheet("Buyer")
    for k, v in (("Buyer", rv["buyer"]["name"]), ("Type", rv["buyer"]["type"]), ("Country", rv["buyer"]["country"]), ("Currency", rv["buyer"]["currency"]), ("Deadline", rv["deadline"]),
                 ("Submission", rv["format"]["submission"]), ("Portal", rv["format"]["portal"])):
        ws3.append([k, v])
    wb.save(str(out))


def build_pack(pid: str) -> dict:
    """builds/vN/: response.docx (+ .pdf when the agent can draw), matrix.xlsx, portal-fields.json, proposal-deck.pptx (+ twin), check reports."""
    from .studio import _renderer
    d = folder(pid)
    st = load(pid)
    n = len(st.get("packs") or []) + 1
    out = d / "builds" / f"v{n}"
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    _write_sources(d)
    rv, mv = requirements_view(d), matrix_view(d)
    p = _yaml(d, "pricing.yaml") or {}
    (d / "deck.yaml").write_text(deck_yaml(st, rv, mv, p), encoding="utf-8")
    (d / "response.yaml").write_text(response_yaml(st, rv, mv, p), encoding="utf-8")
    deck = docs_build.build(d / "deck.yaml", out / "deck", workspace=store.ROOT, renderer=_renderer, evidence_base=f"{ROUTE}/{pid}?ref=", name="proposal-deck", pdf=False)
    doc = docs_build.build(d / "response.yaml", out / "doc", workspace=store.ROOT, renderer=_renderer, evidence_base=f"{ROUTE}/{pid}?ref=", name="response", pdf=True)
    files = {}
    for sub, info in (("deck", deck), ("doc", doc)):
        for k, f in info["files"].items():
            src = out / sub / f
            dst = out / (f"{sub}-{f}" if f in ("twin.html", "check.json") else f)
            if src.exists():
                shutil.move(str(src), str(dst))
                files[f"{sub}_{k}"] = dst.name
    shutil.rmtree(out / "deck", ignore_errors=True)
    shutil.rmtree(out / "doc", ignore_errors=True)
    _xlsx(d, out / "matrix.xlsx", rv, mv)
    files["xlsx"] = "matrix.xlsx"
    portal = {"buyer": rv["buyer"], "deadline": rv["deadline"], "format": rv["format"], "fields": [{"id": r["id"], "status": r["status"], "answer": r["answer"], "evidence": [e["ref"] for e in r["evidence"]]} for r in mv["rows"]],
              "price": p.get("totals"), "currency": p.get("currency"), "generated": time.time(), "note": "portal fields for SAP Ariba / Coupa / Jaggaer / GeM / Loopio / Responsive — upload by hand in P11"}
    (out / "portal-fields.json").write_text(json.dumps(portal, indent=1, ensure_ascii=False), encoding="utf-8")
    files["portal"] = "portal-fields.json"
    required = rv["format"]["submission"] or "portal"
    rec = {"v": n, "when": time.time(), "ok": deck["ok"] and doc["ok"], "deck_ok": deck["ok"], "doc_ok": doc["ok"], "files": files, "required": required, "portal": rv["format"]["portal"],
           "fails": deck["report"]["counts"]["fails"] + doc["report"]["counts"]["fails"], "warnings": deck["report"]["counts"]["warnings"] + doc["report"]["counts"]["warnings"],
           "counts": {"slides": (deck.get("deck") or {}).get("slides"), "blocks": (doc.get("doc") or {}).get("blocks"), "rows": len(mv["rows"])}, "template": deck["template"], "partner": deck["partner"]}
    return rec


# ---------------------------------------------------------------- checkpoints and state moves

def _owner(pid: str) -> str | None:
    p = db.project(pid)
    return p["owner_id"] if p else None


def _person(st: dict, key: str, pid: str) -> str | None:
    uid = (st.get("people") or {}).get(key)
    return uid if uid and db.user(uid) else _owner(pid)


def _open(pid: str, st: dict, step: str, name: str, view: str, evidence: dict, assignee: str | None = None, agent: str | None = "Relay bid writer") -> dict:
    return checkpoints.open(CP[step], pid, MODULE, name, view, evidence, link=f"{ROUTE}/{pid}", assignee=assignee or _owner(pid), agent=agent, opened_by="agent" if agent else (assignee or "system"))


def requirements_read(pid: str, summary: str = "") -> dict:
    d = folder(pid)
    st = load(pid)
    problems = check_requirements(d, st)
    if problems:
        raise RfpError("; ".join(problems[:4]))
    v = requirements_view(d)
    st.update(status="awaiting_requirements", job=None, error=None, requirements_rounds=(st.get("requirements_rounds") or 0) + 1, read_summary=summary or st.get("read_summary") or "",
              buyer=v["buyer"]["name"] or st.get("buyer"), deadline=v["deadline"], counts={**(st.get("counts") or {}), **v["counts"]})
    store.save(st)
    checkpoints.withdraw(CP["requirements"], pid, who="system")
    ev = {"summary": f"{v['counts']['requirements']} requirements ({v['counts']['mandatory']} mandatory, {v['counts']['scored']} scored, {v['counts']['information']} information) in {v['counts']['sections']} sections; deadline {v['deadline'] or 'not stated'}",
          "counts": v["counts"], "items": [f"{r['id']} ({r['kind']}, p. {r['page']}): {r['text'][:90]}" for r in v["requirements"][:8]], "rows": v["requirements"][:200],
          "deadline": v["deadline"], "format": v["format"], "evaluation": v["evaluation"]}
    _open(pid, st, "requirements", f"Requirements: {st['name']}", "table", ev)
    worker.app_note(pid, "rfp_read", f"Relay read the pack: {ev['summary']}. Confirm the list, or correct it.", "ok")
    db.audit("rfp.requirements_read", pid, {"rounds": st["requirements_rounds"], **v["counts"]}, "agent")
    return st


def open_gonogo(pid: str, who: str) -> None:
    d = folder(pid)
    st = load(pid)
    v = requirements_view(d)
    g = v["gonogo"]
    st.update(status="awaiting_gonogo", requirements_confirmed={"by": who, "when": time.time()})
    store.save(st)
    ev = {"summary": f"Relay recommends {g['recommendation'].upper() or '—'}: " + "; ".join(g["reasons"][:3]), "items": [f"Reason: {r}" for r in g["reasons"]] + [f"Risk: {r}" for r in g["risks"]] + [f"Fit: {f['name']} — {f['requirements']} requirement(s)" for f in g["fit"]],
          "counts": {"requirements": v["counts"]["requirements"], "risks": len(g["risks"]), "modules": len(g["fit"])}, "text": "\n".join(g["reasons"]), "recommendation": g["recommendation"], "effort": g["effort"], "deadline_ok": g["deadline_ok"]}
    decider = _person(st, "decider", pid)
    _open(pid, st, "gonogo", f"Go / no-go: {st['name']}", "text", ev, assignee=decider)
    if decider and decider != who:
        notify.add(decider, "review", f"Go / no-go: {st['name']}", f"Relay recommends {g['recommendation'] or '—'}", f"{ROUTE}/{pid}")
    worker.app_note(pid, "rfp", f"Requirements confirmed. Go / no-go: Relay recommends {g['recommendation'] or '—'} — a named person decides.", "ok")


def matrix_drafted(pid: str, summary: str = "") -> dict:
    d = folder(pid)
    st = load(pid)
    problems = check_matrix(d)
    if problems:
        raise RfpError("; ".join(problems[:4]))
    mv = matrix_view(d)
    st.update(status="awaiting_matrix", job=None, error=None, matrix_rounds=(st.get("matrix_rounds") or 0) + 1, answer_summary=summary or st.get("answer_summary") or "", counts={**(st.get("counts") or {}), **mv["counts"]})
    store.save(st)
    checkpoints.withdraw(CP["matrix"], pid, who="system")
    c = mv["counts"]
    ev = {"summary": f"{c['rows']} answers: {c['comply']} comply, {c['partial']} partial, {c['alternative']} alternative, {c['not']} not; {len(mv['evidence_used'])} pieces of evidence (modules and library items only)",
          "counts": c, "items": [f"{r['id']} {r['status']}: {r['answer'][:80]}" for r in mv["rows"][:8]], "rows": mv["rows"][:200]}
    _open(pid, st, "matrix", f"Compliance matrix: {st['name']}", "table", ev)
    worker.app_note(pid, "rfp_answer", f"Compliance matrix drafted: {ev['summary']}. Confirm it, edit answers, or send it back.", "ok")
    db.audit("rfp.matrix_drafted", pid, {"rounds": st["matrix_rounds"], **c}, "agent")
    return st


def reviews_open(pid: str, summary: str = "") -> dict:
    d = folder(pid)
    st = load(pid)
    problems = check_redteam(d)
    if problems:
        raise RfpError("; ".join(problems[:4]))
    rt = redteam_view(d)
    st.update(status="awaiting_reviews", job=None, error=None, redteam_summary=summary or rt["summary"], reviews={})
    store.save(st)
    for key, label in REVIEWS:
        checkpoints.withdraw(CP["review"], pid, name=f"{label}: {st['name']}", who="system")
        ev = {"summary": f"{label} — red team: {rt['counts']['high']} high, {rt['counts']['medium']} medium, {rt['counts']['low']} low. {rt['summary'][:200]}",
              "counts": rt["counts"], "items": [f"[{f['severity']}] {f['requirement']}: {f['finding']}" for f in rt["findings"][:8]], "rows": rt["findings"], "review": key}
        _open(pid, st, "review", f"{label}: {st['name']}", "table", ev, assignee=_person(st, key, pid), agent="Relay red team")
    worker.app_note(pid, "rfp_redteam", f"Red-team read done: {rt['counts']['high']} high, {rt['counts']['medium']} medium, {rt['counts']['low']} low findings. Three reviews are open: technical, commercial, legal.", "ok")
    db.audit("rfp.reviews_opened", pid, rt["counts"], "agent")
    return st


def pack_built(pid: str, rec: dict) -> dict:
    st = load(pid)
    st.setdefault("packs", []).append(rec)
    st.update(status="awaiting_submit", job=None, error=None)
    store.save(st)
    checkpoints.withdraw(CP["submit"], pid, who="system")
    f = rec["files"]
    ev = {"summary": f"Submission pack v{rec['v']}: Word response, PDF, Excel matrix, portal fields (JSON) and the proposal deck — checks {'passed' if rec['ok'] else 'FAILED (' + str(rec['fails']) + ' problems)'}; the buyer wants {rec['required']}" + (f" ({rec['portal']})" if rec.get("portal") else ""),
          "items": [f"{k}: {v}" for k, v in f.items()], "counts": {"version": rec["v"], "problems": rec["fails"], "warnings": rec["warnings"], "rows": rec["counts"].get("rows")},
          "twin": f"/api/rfp/{pid}/preview/{rec['v']}/doc", "pdf": f"/api/rfp/{pid}/builds/{rec['v']}/{f['doc_pdf']}" if f.get("doc_pdf") else None, "file": f"/api/rfp/{pid}/builds/{rec['v']}/{f.get('doc_docx')}"}
    _open(pid, st, "submit", f"Submit: {st['name']} (pack v{rec['v']})", "link", ev, assignee=_person(st, "decider", pid))
    worker.app_note(pid, "rfp_pack", ev["summary"] + ". A named person accepts the pack; then it is submitted by hand on the portal or by mail.", "ok" if rec["ok"] else "warn")
    db.audit("rfp.pack_built", pid, {"version": rec["v"], "ok": rec["ok"], "files": list(f)}, "system")
    return st


# ---------------------------------------------------------------- jobs

def _pick_library(d: Path, who: str | None = None) -> list[dict]:
    """The library items the agent may cite: the best matches per requirement plus items tagged with the fit modules."""
    v = requirements_view(d)
    picked: dict[str, dict] = {}
    for r in v["requirements"]:
        for it in library_search(r["text"], 3):
            picked.setdefault(it["id"], it)
    for f in v["gonogo"]["fit"]:
        for it in library_list(10, module=f["module"]):
            picked.setdefault(it["id"], it)
    items = list(picked.values())[:120]
    (d / "sources").mkdir(exist_ok=True)
    (d / "sources" / "library.json").write_text(json.dumps({"items": items, "note": "the only library items an answer may cite (library:<id>)"}, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    return items


def _write_registry(d: Path) -> None:
    (d / "sources").mkdir(exist_ok=True)
    (d / "sources" / "registry.json").write_text(json.dumps({"modules": {m["id"]: {"id": m["id"], "name": m["name"], "sub": m["sub"], "text": m["text"], "platforms": m["platforms"], "status": m["status"],
                                                                                   "journey": registry.plan_for(m, "develop" if "develop" in m["work"] else (m["work"][0] if m["work"] else "engage"))["journey"]}
                                                                         for m in registry.MODULES if m["pl"] not in ("hidden", "platform")}}, indent=1, ensure_ascii=False), encoding="utf-8")


async def _read(pid: str, args: dict) -> None:
    d = folder(pid)
    st = load(pid)
    correction = args.get("correction")
    worker.app_note(pid, "rfp_read", "Relay is reading the pack again with your correction." if correction else f"Relay is reading the pack: {len(st.get('attachments') or [])} file(s) — every requirement, deadline, format rule and evaluation criterion.")
    _write_registry(d)
    res = await worker.agent(pid, "rfp_read", rfp_prompts.read(st, correction), worker.TURNS["rfp_read"], "requirements", system=rfp_prompts.SYSTEM)
    for attempt in range(worker.FIX_ROUNDS + 1):
        problems = await asyncio.to_thread(check_requirements, d, st)
        if not problems:
            break
        if attempt == worker.FIX_ROUNDS:
            raise RuntimeError(f"requirements.yaml still has {len(problems)} problem(s): " + "; ".join(problems[:4]))
        worker.app_note(pid, "rfp_read", f"The check found {len(problems)} problem(s) in the requirements — Relay is fixing them.", "warn", problems)
        res = await worker.agent(pid, "rfp_read", rfp_prompts.fix("requirements.yaml and gonogo.yaml", problems), worker.TURNS["fix"], "requirements", resume=res.get("session_id"), system=rfp_prompts.SYSTEM)
    requirements_read(pid, res.get("text") or "")


async def _answer(pid: str, args: dict) -> None:
    d = folder(pid)
    st = load(pid)
    correction = args.get("correction")
    worker.app_note(pid, "rfp_answer", "Relay is revising the matrix with your comment." if correction else "Relay is drafting the compliance matrix from your library and Relay's module facts — nothing else may be cited.")
    items = await asyncio.to_thread(_pick_library, d)
    _write_registry(d)
    worker.app_note(pid, "rfp_answer", f"{len(items)} library item(s) matched the requirements and are available as evidence." if items else "The library has no matching items yet: answers can cite Relay's modules only.")
    res = await worker.agent(pid, "rfp_answer", rfp_prompts.answer(correction), worker.TURNS["rfp_answer"], "matrix", system=rfp_prompts.SYSTEM)
    for attempt in range(worker.FIX_ROUNDS + 1):
        problems = await asyncio.to_thread(check_matrix, d)
        if not problems:
            break
        if attempt == worker.FIX_ROUNDS:
            raise RuntimeError(f"matrix.yaml still has {len(problems)} problem(s): " + "; ".join(problems[:4]))
        worker.app_note(pid, "rfp_answer", f"The check found {len(problems)} problem(s) in the matrix (an unknown reference is one) — Relay is fixing them.", "warn", problems)
        res = await worker.agent(pid, "rfp_answer", rfp_prompts.fix("matrix.yaml", problems), worker.TURNS["fix"], "matrix", resume=res.get("session_id"), system=rfp_prompts.SYSTEM)
    matrix_drafted(pid, res.get("text") or "")


async def _redteam(pid: str, args: dict) -> None:
    d = folder(pid)
    worker.app_note(pid, "rfp_redteam", "Relay is reading the response as the buyer's evaluator would (red team).")
    res = await worker.agent(pid, "rfp_redteam", rfp_prompts.redteam(), worker.TURNS["rfp_redteam"], "redteam", system=rfp_prompts.SYSTEM)
    for attempt in range(worker.FIX_ROUNDS + 1):
        problems = await asyncio.to_thread(check_redteam, d)
        if not problems:
            break
        if attempt == worker.FIX_ROUNDS:
            raise RuntimeError(f"redteam.yaml still has {len(problems)} problem(s): " + "; ".join(problems[:4]))
        worker.app_note(pid, "rfp_redteam", f"The check found {len(problems)} problem(s) in the findings — Relay is fixing them.", "warn", problems)
        res = await worker.agent(pid, "rfp_redteam", rfp_prompts.fix("redteam.yaml", problems), worker.TURNS["fix"], "redteam", resume=res.get("session_id"), system=rfp_prompts.SYSTEM)
    reviews_open(pid, res.get("text") or "")


async def _pack(pid: str, args: dict) -> None:
    worker.app_note(pid, "rfp_pack", "Building the submission pack: Word response, PDF, Excel matrix, portal fields and the proposal deck — through the studio engine, every figure sourced.")
    rec = await asyncio.to_thread(build_pack, pid)
    pack_built(pid, rec)


worker.register_job("rfp_read", _read, status="qualifying", done="Requirements read — confirm them in RFP & bid response", llm=True, turns=100, timeout_s=3000)
worker.register_job("rfp_answer", _answer, status="answering", done="Compliance matrix drafted — confirm it", llm=True, turns=120, timeout_s=3600)
worker.register_job("rfp_redteam", _redteam, status="redteam", done="Red-team read done — reviews are open", llm=True, turns=60, timeout_s=1800)
worker.register_job("rfp_pack", _pack, status="packing", done="Submission pack built — accept it")


def _restart_answers(pid: str, comment: str, who: str, stage: str) -> None:
    st = load(pid)
    store.note(pid, f"{stage} sent back", comment)
    st.setdefault("comments", []).append({"stage": stage, "text": comment, "who": who, "when": time.time()})
    store.save(st)
    for k in ("matrix", "price", "review", "submit"):
        checkpoints.withdraw(CP[k], pid, who=who)
    worker.enqueue(pid, "rfp_answer", correction=comment)


def _on_decision(c: dict, decision: str, comment: str | None, who: str) -> None:
    pid, kind = c["subject"], c["kind"]
    try:
        st = load(pid)
    except (KeyError, FileNotFoundError):
        return
    comment = " ".join((comment or "").split())[:2000]
    if kind == CP["requirements"]:
        if st["status"] != "awaiting_requirements":
            return
        if decision == "accept":
            db.audit("rfp.requirements_confirmed", pid, {"checkpoint": c["id"]}, who)
            open_gonogo(pid, who)
        else:
            store.note(pid, "Correction to the requirements", comment)
            st.setdefault("comments", []).append({"stage": "requirements", "text": comment, "who": who, "when": time.time()})
            store.save(st)
            db.audit("rfp.requirements_sent_back", pid, {"comment": comment[:300]}, who)
            worker.enqueue(pid, "rfp_read", correction=comment)
    elif kind == CP["gonogo"]:
        if st["status"] != "awaiting_gonogo":
            return
        if decision == "accept":
            st.update(gonogo={"decision": "go", "by": who, "when": time.time(), "comment": comment, "checkpoint": c["id"]}, status="answering")
            store.save(st)
            store.note(pid, "Go", f"Decided by {who}" + (f": {comment}" if comment else ""))
            db.audit("rfp.go", pid, {"checkpoint": c["id"]}, who)
            worker.enqueue(pid, "rfp_answer")
        else:
            st.update(gonogo={"decision": "no-go", "by": who, "when": time.time(), "comment": comment, "checkpoint": c["id"]}, status="no_go", job=None)
            store.save(st)
            store.note(pid, "No-go", f"Decided by {who}: {comment}")
            db.audit("rfp.no_go", pid, {"reason": comment[:300]}, who)
    elif kind == CP["matrix"]:
        if st["status"] != "awaiting_matrix":
            return
        if decision == "accept":
            st.update(matrix_confirmed={"by": who, "when": time.time(), "checkpoint": c["id"]})
            db.audit("rfp.matrix_confirmed", pid, {"checkpoint": c["id"]}, who)
            if st.get("price_confirmed"):               # a revision after the price was agreed: straight to the red team and the reviews
                st["status"] = "redteam"
                store.save(st)
                worker.enqueue(pid, "rfp_redteam")
            else:
                st["status"] = "pricing"
                store.save(st)
                worker.app_note(pid, "rfp", "Matrix confirmed. Now price it: effort per wave and module against your rate cards, licences, run & support.", "ok")
        else:
            db.audit("rfp.matrix_sent_back", pid, {"comment": comment[:300]}, who)
            _restart_answers(pid, comment, who, "Matrix")
    elif kind == CP["price"]:
        if st["status"] != "awaiting_price":
            return
        if decision == "accept":
            st.update(price_confirmed={"by": who, "when": time.time(), "checkpoint": c["id"]}, status="redteam")
            store.save(st)
            db.audit("rfp.price_confirmed", pid, {"checkpoint": c["id"], "total": (st.get("pricing") or {}).get("totals", {}).get("total")}, who)
            worker.enqueue(pid, "rfp_redteam")
        else:
            st.update(status="pricing")
            st.setdefault("comments", []).append({"stage": "price", "text": comment, "who": who, "when": time.time()})
            store.save(st)
            store.note(pid, "Price sent back", comment)
            db.audit("rfp.price_sent_back", pid, {"comment": comment[:300]}, who)
    elif kind == CP["review"]:
        if st["status"] != "awaiting_reviews":
            return
        key = (c.get("evidence") or {}).get("review") or "review"
        if decision == "accept":
            st.setdefault("reviews", {})[key] = {"by": who, "when": time.time(), "checkpoint": c["id"], "comment": comment}
            store.save(st)
            db.audit("rfp.review_accepted", pid, {"review": key, "checkpoint": c["id"]}, who)
            if all(k in st["reviews"] for k, _ in REVIEWS):
                st["status"] = "packing"
                store.save(st)
                worker.enqueue(pid, "rfp_pack")
        else:
            db.audit("rfp.review_sent_back", pid, {"review": key, "comment": comment[:300]}, who)
            _restart_answers(pid, f"{key} review: {comment}", who, f"{key.capitalize()} review")
    elif kind == CP["submit"]:
        if st["status"] != "awaiting_submit":
            return
        if decision == "accept":
            v = (st.get("packs") or [{}])[-1].get("v")
            st.update(status="ready", submit_accepted={"by": who, "when": time.time(), "checkpoint": c["id"], "version": v})
            store.save(st)
            store.note(pid, "Pack accepted", f"Pack v{v} accepted by {who} — ready to submit")
            db.audit("rfp.submit_accepted", pid, {"version": v, "checkpoint": c["id"]}, who)
        else:
            db.audit("rfp.submit_sent_back", pid, {"comment": comment[:300]}, who)
            _restart_answers(pid, f"Submission pack: {comment}", who, "Submission pack")


for _k in CP.values():
    checkpoints.register_kind(_k, {"rfp.requirements": "RFP: confirm the requirements", "rfp.gonogo": "RFP: go / no-go", "rfp.matrix": "RFP: confirm the compliance matrix",
                                   "rfp.price": "RFP: confirm the price", "rfp.review": "RFP: review", "rfp.submit": "RFP: accept the submission pack"}[_k], _on_decision)


# ---------------------------------------------------------------- state, snapshot

def _packs_public(pid: str, st: dict) -> list[dict]:
    out = []
    for p in st.get("packs") or []:
        out.append({**p, "links": {k: f"/api/rfp/{pid}/builds/{p['v']}/{v}" for k, v in (p.get("files") or {}).items()}, "preview": {"doc": f"/api/rfp/{pid}/preview/{p['v']}/doc", "deck": f"/api/rfp/{pid}/preview/{p['v']}/deck"}})
    return out


def state(pid: str, u: dict | None = None) -> dict:
    st = load(pid)
    d = folder(pid)
    p = db.project(pid)
    names = {x["id"]: x["name"] for x in db.q("SELECT id, name FROM users")}
    cps = [checkpoints._public(c) for c in db.q("SELECT * FROM checkpoints WHERE subject = ? AND status = 'open' AND kind LIKE 'rfp.%'", (pid,))]
    att = []
    for a in st.get("attachments") or []:
        info = reader.cached(d / "attachments" / a["name"])
        att.append({**a, "read": info is not None, "pages": (info or {}).get("pages"), "note": (info or {}).get("note") or "", "text": ((info or {}).get("text") or "")[:3000]})
    rv = requirements_view(d) if (d / "requirements.yaml").exists() else None
    packs = _packs_public(pid, st)
    out = {**st, "status_label": STATUS_LABEL.get(st["status"], st["status"]), "attachments": att, "requirements": rv, "matrix": matrix_view(d) if (d / "matrix.yaml").exists() else None,
           "redteam": redteam_view(d) if (d / "redteam.yaml").exists() else None, "open_checkpoints": [{"id": c["id"], "kind": c["kind"], "name": c["name"], "assignee": c.get("assignee_id"), "review": (c.get("evidence") or {}).get("review")} for c in cps],
           "packs": packs, "latest_pack": packs[-1] if packs else None, "owner": p["owner_id"] if p else None, "owner_name": names.get(p["owner_id"]) if p else None,
           "people_names": {k: names.get(v, v) for k, v in (st.get("people") or {}).items()}, "position": worker.position(pid) if st["status"] == "queued" else 0,
           "running_since": worker.current.get("started") if worker.current.get("pid") == pid else None, "rate_cards": rate_cards(), "test_hooks": TEST_HOOKS,
           "library_count": db.one("SELECT COUNT(*) AS n FROM rfp_library")["n"], "reviews_needed": [{"key": k, "label": l, "done": k in (st.get("reviews") or {})} for k, l in REVIEWS],
           "can_submit": st.get("status") == "ready"}
    if u is not None:
        out["access"] = {"can_edit": auth.can_project(u, "edit", p) and auth.is_dev(u), "can_view": auth.can_project(u, "view", p)}
    return out


def summary_of(pid: str) -> dict:
    st = load(pid)
    return {k: st.get(k) for k in ("id", "name", "buyer", "deadline", "status", "created", "updated", "outcome")} | \
           {"status_label": STATUS_LABEL.get(st["status"], st["status"]), "requirements": (st.get("counts") or {}).get("requirements"), "attachments": len(st.get("attachments") or [])}


def snapshot(pid: str) -> dict:
    """What the studio copies as a source (sources/rfp-<id>.json)."""
    d = folder(pid)
    st = load(pid)
    rv = requirements_view(d) if (d / "requirements.yaml").exists() else None
    mv = matrix_view(d) if (d / "matrix.yaml").exists() else None
    return {"id": pid, "name": st.get("name"), "status": st.get("status"), "buyer": (rv or {}).get("buyer") or {"name": st.get("buyer")}, "deadline": (rv or {}).get("deadline"),
            "requirements": [{k: r[k] for k in ("id", "text", "page", "kind", "section")} for r in (rv or {}).get("requirements") or []], "counts": (rv or {}).get("counts"),
            "gonogo": (rv or {}).get("gonogo"), "matrix": {"counts": (mv or {}).get("counts"), "rows": [{k: r[k] for k in ("id", "status", "answer")} for r in (mv or {}).get("rows") or []]} if mv else None,
            "pricing": (st.get("pricing") or {}).get("totals"), "currency": (st.get("pricing") or {}).get("currency"), "outcome": st.get("outcome")}


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
        raise HTTPException(404, "No such response.")
    p = db.project(pid)
    if not auth.can_project(u, "view", p):
        raise HTTPException(404, "No such response.")
    if action != "view" and not (auth.can_project(u, "edit", p) and auth.is_dev(u)):
        raise HTTPException(403, "You can look at this response, but only its owner or a builder it is shared with can change it.")
    return u, st


@router.get("/api/rfp")
def list_responses():
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
    return {"responses": sorted(out, key=lambda s: -(s.get("created") or 0)), "can_create": auth.is_dev(u), "platforms": PLATFORMS, "buyer_types": list(BUYER_TYPES),
            "library": {"count": db.one("SELECT COUNT(*) AS n FROM rfp_library")["n"], "won": db.one("SELECT COUNT(*) AS n FROM rfp_library WHERE won = 1")["n"], "recent": library_list(8)},
            "rate_cards": rate_cards(), "reviews": [{"key": k, "label": l} for k, l in REVIEWS], "kinds": sorted(reader.KINDS["doc"] | reader.KINDS["sheet"] | reader.KINDS["pdf"] | reader.KINDS["deck"] | reader.KINDS["text"])}


@router.post("/api/rfp")
async def create(name: str = Form(""), buyer: str = Form(""), buyer_type: str = Form(""), notes: str = Form(""), people: str = Form("{}"), files: list[UploadFile] = File(default=[])):
    u = _u()
    if not auth.is_dev(u):
        raise HTTPException(403, "Only builders and admins can start a response; ask one to start it for you.")
    name = " ".join(name.split())[:120]
    if len(name) < 3:
        raise HTTPException(400, "Name the response (the buyer and what they ask for).")
    files = [f for f in files if f.filename]
    if not files:
        raise HTTPException(400, "Attach the RFP pack: PDF, Word, Excel or slides.")
    bad = [f.filename for f in files if reader.kind_of(f.filename) not in ("doc", "sheet", "deck", "pdf", "text", "image")]
    if bad:
        raise HTTPException(400, f"Not a kind of file Relay reads: {', '.join(bad[:3])}.")
    if buyer_type and buyer_type not in BUYER_TYPES:
        raise HTTPException(400, f"Buyer type must be one of {', '.join(BUYER_TYPES)}.")
    try:
        ppl = {k: str(v) for k, v in json.loads(people or "{}").items() if v}
    except (ValueError, AttributeError):
        ppl = {}
    for k, v in ppl.items():
        if k not in ("decider", "technical", "commercial", "legal") or not db.user(v):
            raise HTTPException(400, f"{k}: no such person.")
    pid = store.new_id(name)
    d = store.ROOT / pid
    (d / "attachments").mkdir(parents=True)
    taken: set[str] = set()
    attachments = []
    try:
        for f in files:
            n = SAFE.sub("_", Path(f.filename).name).strip(" ._") or "file"
            while n.lower() in taken:
                n = "_" + n
            taken.add(n.lower())
            size = 0
            with (d / "attachments" / n).open("wb") as out:
                while chunk := await f.read(1024 * 1024):
                    out.write(chunk)
                    size += len(chunk)
                    if size > MAX_BYTES:
                        raise HTTPException(413, f'"{f.filename}" is larger than {MAX_BYTES // 1024 // 1024} MB.')
            attachments.append({"name": n, "kind": reader.kind_of(n), "bytes": size})
    except BaseException:
        shutil.rmtree(d, ignore_errors=True)
        raise
    st = {"id": pid, "kind": KIND, "name": name, "buyer": buyer.strip()[:120], "buyer_type": buyer_type, "notes": notes.strip()[:4000], "people": ppl, "attachments": attachments,
          "model": worker.DEFAULT_MODEL, "created": time.time(), "status": "queued", "versions": [], "runs": [], "files": [], "job": None, "error": None, "requirements_rounds": 0, "matrix_rounds": 0,
          "comments": [], "packs": [], "reviews": {}, "pricing": None, "outcome": None, "submitted": None}
    store.save(st)
    db.add_project(pid, u["id"])
    (d / "request.md").write_text(f"# {name}\n\n**Buyer:** {buyer or '(see the pack)'}  \n**Buyer type:** {buyer_type or '(see the pack)'}\n\n## What the bid team knows\n\n{notes.strip() or '(nothing added)'}\n\n"
                                  "## The pack (attachments/)\n\n" + "\n".join(f"- {a['name']} ({a['kind']}, {a['bytes']:,} bytes)" for a in attachments) + "\n\n## Rules\n\n- Requirements come from the pack, with page references.\n- Answers cite only library items and Relay's modules.\n- Nothing is submitted without a named person's acceptance.\n", encoding="utf-8")
    await asyncio.to_thread(lambda: [reader.read(d / "attachments" / a["name"]) for a in attachments])
    db.audit("rfp.create", pid, {"name": name, "buyer": buyer, "attachments": [a["name"] for a in attachments], "people": ppl}, u["id"])
    store.log(pid, {"kind": "user", "stage": "rfp", "text": f"Started the response “{name}” with {len(attachments)} file(s) in the pack"})
    worker.enqueue(pid, "rfp_read")
    return state(pid, u)


@router.get("/api/rfp/library")
def api_library(q: str = "", module: str = "", buyer_type: str = "", limit: int = 100):
    _u()
    return {"items": library_list(limit, module or None, buyer_type or None, q), "count": db.one("SELECT COUNT(*) AS n FROM rfp_library")["n"]}


class LibraryIn(BaseModel):
    title: str
    text: str
    module: str | None = None
    buyer_type: str | None = None
    tags: list[str] = []
    kind: str = "answer"


@router.post("/api/rfp/library")
def api_library_add(body: LibraryIn):
    u = _u()
    if not auth.is_dev(u):
        raise HTTPException(403, "Only builders and admins add to the library.")
    try:
        return library_add(body.title, body.text, body.module or None, body.buyer_type or None, body.tags, body.kind, origin="manual", who=u["id"])
    except RfpError as e:
        raise HTTPException(400, str(e))


@router.delete("/api/rfp/library/{lid}")
def api_library_remove(lid: str):
    u = _u()
    if not auth.is_admin(u):
        raise HTTPException(403, "Only an admin removes library items.")
    library_remove(lid, u["id"])
    return {"ok": True}


@router.get("/api/rfp/rate-cards")
def api_rate_cards():
    _u()
    return {"rate_cards": rate_cards()}


class RateCards(BaseModel):
    rows: list[dict]


@router.put("/api/rfp/rate-cards")
def api_set_rate_cards(body: RateCards):
    u = _u()
    if not auth.is_admin(u):
        raise HTTPException(403, "Only an admin changes the rate cards.")
    try:
        return {"rate_cards": set_rate_cards(body.rows, u["id"])}
    except RfpError as e:
        raise HTTPException(400, str(e))


@router.get("/api/rfp/{pid}")
def get_response(pid: str):
    u, _ = _get(pid)
    return state(pid, u)


@router.get("/api/rfp/{pid}/activity")
def activity(pid: str, after: int = 0):
    _get(pid)
    return store.activity(pid, after)


@router.get("/api/rfp/{pid}/file/{path:path}")
def pack_file(pid: str, path: str):
    _get(pid)
    base = (folder(pid) / "attachments").resolve()
    target = (base / path).resolve()
    if base not in target.parents or not target.is_file():
        raise HTTPException(404, "No such file.")
    from .studio import mime_of
    return FileResponse(target, media_type=mime_of(target), headers={"Cache-Control": "private, no-store"})


@router.get("/api/rfp/{pid}/builds/{v}/{name}")
def build_file(pid: str, v: int, name: str):
    _, st = _get(pid)
    base = (folder(pid) / "builds" / f"v{v}").resolve()
    target = (base / name).resolve()
    if base != target.parent or not target.is_file():
        raise HTTPException(404, "No such file.")
    stem = SAFE.sub("_", st["name"])[:60] or "response"
    from .studio import mime_of
    return FileResponse(target, media_type=mime_of(target), filename=f"{stem} v{v} {name}" if target.suffix in (".pptx", ".docx", ".pdf", ".xlsx", ".json") else name, headers={"Cache-Control": "private, no-store"})


@router.get("/api/rfp/{pid}/preview/{v}/{which}", response_class=HTMLResponse)
def preview(pid: str, v: int, which: str):
    _get(pid)
    p = folder(pid) / "builds" / f"v{v}" / f"{'deck' if which == 'deck' else 'doc'}-twin.html"
    if not p.is_file():
        raise HTTPException(404, "No preview for this version.")
    return HTMLResponse(p.read_text(encoding="utf-8"), headers={"Cache-Control": "private, no-store", "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; img-src data:"})


class Comment(BaseModel):
    comment: str = ""


def _cp(pid: str, kind: str, name_like: str | None = None) -> dict:
    sql, args = "SELECT * FROM checkpoints WHERE kind = ? AND subject = ? AND status = 'open'", [kind, pid]
    if name_like:
        sql += " AND name LIKE ?"
        args.append(name_like + "%")
    c = db.one(sql, tuple(args))
    if not c:
        raise HTTPException(409, "This step is not waiting for a decision right now.")
    return checkpoints._public(c)


def _decide(pid: str, step: str, decision: str, comment: str | None, who: str, name_like: str | None = None) -> None:
    if decision == "send_back" and not (comment or "").strip():
        raise HTTPException(400, "Say what to change.")
    checkpoints.decide(_cp(pid, CP[step], name_like)["id"], decision, who, comment)


@router.post("/api/rfp/{pid}/requirements/confirm")
def confirm_requirements(pid: str, body: Comment | None = None):
    u, st = _get(pid, "edit")
    if st["status"] != "awaiting_requirements":
        raise HTTPException(409, f"Nothing to confirm right now (status: {st['status']}).")
    _decide(pid, "requirements", "accept", body.comment if body else None, u["id"])
    return state(pid, u)


@router.post("/api/rfp/{pid}/requirements/send-back")
def correct_requirements(pid: str, body: Comment):
    u, st = _get(pid, "edit")
    if st["status"] != "awaiting_requirements":
        raise HTTPException(409, f"Nothing to correct right now (status: {st['status']}).")
    _decide(pid, "requirements", "send_back", body.comment, u["id"])
    return state(pid, u)


@router.post("/api/rfp/{pid}/gonogo/{decision}")
def decide_gonogo(pid: str, decision: str, body: Comment | None = None):
    """go = accept the recommendation to bid; no-go = send back with the reason. Only the named decider (or an admin)."""
    u, st = _get(pid, "edit")
    if st["status"] != "awaiting_gonogo":
        raise HTTPException(409, f"No go / no-go is open right now (status: {st['status']}).")
    decider = _person(st, "decider", pid)
    if decider and u["id"] != decider and not auth.is_admin(u):
        raise HTTPException(403, "The go / no-go is decided by the named person (or an admin).")
    if decision not in ("go", "no-go"):
        raise HTTPException(400, "Decision must be go or no-go.")
    _decide(pid, "gonogo", "accept" if decision == "go" else "send_back", (body.comment if body else "") or ("No-go" if decision == "no-go" else None), u["id"])
    return state(pid, u)


@router.post("/api/rfp/{pid}/gonogo/reopen")
def reopen_gonogo(pid: str):
    u, st = _get(pid, "edit")
    if st["status"] != "no_go":
        raise HTTPException(409, "Only a no-go can be reopened.")
    db.audit("rfp.gonogo_reopened", pid, None, u["id"])
    open_gonogo(pid, u["id"])
    return state(pid, u)


class MatrixEdit(BaseModel):
    rows: list[dict]


@router.put("/api/rfp/{pid}/matrix")
def edit_matrix(pid: str, body: MatrixEdit):
    """The bid team edits statuses, answers and evidence before confirming; the evidence rule still applies."""
    u, st = _get(pid, "edit")
    if st["status"] != "awaiting_matrix":
        raise HTTPException(409, f"The matrix is not open for changes right now (status: {st['status']}).")
    d = folder(pid)
    raw = _yaml(d, "matrix.yaml") or {"rows": []}
    by = {_s(r.get("id")): r for r in raw.get("rows") or [] if isinstance(r, dict)}
    for e in body.rows:
        rid = _s(e.get("id"))
        if rid not in by:
            raise HTTPException(400, f"{rid}: not a row of the matrix.")
        if "status" in e:
            by[rid]["status"] = _s(e["status"]).capitalize()
        if "answer" in e:
            by[rid]["answer"] = _s(e["answer"])[:8000]
        if "evidence" in e:
            by[rid]["evidence"] = [_s(x) for x in (e.get("evidence") or []) if _s(x)]
        if "note" in e:
            by[rid]["note"] = _s(e["note"])[:1000]
    raw["rows"] = list(by.values())
    (d / "matrix.yaml").write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True, width=110), encoding="utf-8")
    problems = check_matrix(d)
    if problems:
        raise HTTPException(400, "; ".join(problems[:5]))
    mv = matrix_view(d)
    st["counts"] = {**(st.get("counts") or {}), **mv["counts"]}
    st["matrix_edited"] = {"by": u["id"], "when": time.time()}
    store.save(st)
    for c in db.q("SELECT id, evidence FROM checkpoints WHERE kind = ? AND subject = ? AND status = 'open'", (CP["matrix"], pid)):
        ev = json.loads(c["evidence"] or "{}")
        ev.update(counts=mv["counts"], rows=mv["rows"][:200], items=[f"{r['id']} {r['status']}: {r['answer'][:80]}" for r in mv["rows"][:8]])
        db.run("UPDATE checkpoints SET evidence = ? WHERE id = ?", (json.dumps(ev), c["id"]))
    db.audit("rfp.matrix_edited", pid, {"rows": [_s(e.get("id")) for e in body.rows]}, u["id"])
    return state(pid, u)


@router.post("/api/rfp/{pid}/matrix/confirm")
def confirm_matrix(pid: str, body: Comment | None = None):
    u, st = _get(pid, "edit")
    if st["status"] != "awaiting_matrix":
        raise HTTPException(409, f"Nothing to confirm right now (status: {st['status']}).")
    _decide(pid, "matrix", "accept", body.comment if body else None, u["id"])
    return state(pid, u)


@router.post("/api/rfp/{pid}/matrix/send-back")
def send_back_matrix(pid: str, body: Comment):
    u, st = _get(pid, "edit")
    if st["status"] != "awaiting_matrix":
        raise HTTPException(409, f"Nothing to send back right now (status: {st['status']}).")
    _decide(pid, "matrix", "send_back", body.comment, u["id"])
    return state(pid, u)


class PriceIn(BaseModel):
    currency: str = ""
    fx: dict = {}
    waves: list[dict] = []
    licences: list[dict] = []
    run_support: list[dict] = []
    discount_pct: float = 0


@router.post("/api/rfp/{pid}/price")
def price(pid: str, body: PriceIn):
    """Compute the price from the rate cards (Python only) and open the price checkpoint with the maths as evidence."""
    u, st = _get(pid, "edit")
    if st["status"] not in ("pricing", "awaiting_price"):
        raise HTTPException(409, f"Pricing is not open right now (status: {st['status']}).")
    try:
        p = compute_price(body.model_dump())
    except RfpError as e:
        raise HTTPException(400, str(e))
    if not p["waves"] and not p["licences"] and not p["run_support"]:
        raise HTTPException(400, "Add at least one wave with effort lines, a licence or a run & support line.")
    d = folder(pid)
    (d / "pricing.yaml").write_text(yaml.safe_dump(p, sort_keys=False, allow_unicode=True, width=110), encoding="utf-8")
    st.update(pricing=p, status="awaiting_price", price_confirmed=None)
    store.save(st)
    checkpoints.withdraw(CP["price"], pid, who=u["id"])
    _open(pid, st, "price", f"Price: {st['name']}", "table", price_evidence(p), assignee=_person(st, "commercial", pid), agent=None)
    store.log(pid, {"kind": "user", "stage": "rfp", "text": f"Priced: {p['totals']['total']:,.2f} {p['currency']} from the rate cards"})
    db.audit("rfp.priced", pid, {"total": p["totals"]["total"], "currency": p["currency"], "waves": len(p["waves"])}, u["id"])
    return state(pid, u)


@router.post("/api/rfp/{pid}/price/confirm")
def confirm_price(pid: str, body: Comment | None = None):
    u, st = _get(pid, "edit")
    if st["status"] != "awaiting_price":
        raise HTTPException(409, f"Nothing to confirm right now (status: {st['status']}).")
    _decide(pid, "price", "accept", body.comment if body else None, u["id"])
    return state(pid, u)


@router.post("/api/rfp/{pid}/price/send-back")
def send_back_price(pid: str, body: Comment):
    u, st = _get(pid, "edit")
    if st["status"] != "awaiting_price":
        raise HTTPException(409, f"Nothing to send back right now (status: {st['status']}).")
    _decide(pid, "price", "send_back", body.comment, u["id"])
    return state(pid, u)


@router.post("/api/rfp/{pid}/reviews/{which}/{decision}")
def decide_review(pid: str, which: str, decision: str, body: Comment | None = None):
    u, st = _get(pid, "edit")
    label = dict(REVIEWS).get(which)
    if not label:
        raise HTTPException(404, "No such review.")
    if st["status"] != "awaiting_reviews":
        raise HTTPException(409, f"The reviews are not open right now (status: {st['status']}).")
    if decision not in ("accept", "send-back"):
        raise HTTPException(400, "Decision must be accept or send-back.")
    _decide(pid, "review", "accept" if decision == "accept" else "send_back", body.comment if body else None, u["id"], name_like=f"{label}:")
    return state(pid, u)


@router.post("/api/rfp/{pid}/submit/{decision}")
def decide_submit(pid: str, decision: str, body: Comment | None = None):
    u, st = _get(pid, "edit")
    if st["status"] != "awaiting_submit":
        raise HTTPException(409, f"The pack is not waiting for acceptance right now (status: {st['status']}).")
    if decision not in ("accept", "send-back"):
        raise HTTPException(400, "Decision must be accept or send-back.")
    _decide(pid, "submit", "accept" if decision == "accept" else "send_back", body.comment if body else None, u["id"])
    return state(pid, u)


class SubmittedIn(BaseModel):
    how: str = "portal"
    note: str = ""


@router.post("/api/rfp/{pid}/submitted")
def mark_submitted(pid: str, body: SubmittedIn):
    """A person submitted it on the portal (or by hand): who / when / how recorded; nothing is sent by Relay here."""
    u, st = _get(pid, "edit")
    if st["status"] != "ready":
        raise HTTPException(409, "Accept the submission pack first (checkpoint Submit): nothing is recorded as submitted before that.")
    how = body.how.strip().lower()[:40] or "portal"
    st.update(status="submitted", submitted={"by": u["id"], "when": time.time(), "how": how, "note": body.note.strip()[:1000], "version": (st.get("submit_accepted") or {}).get("version")})
    store.save(st)
    store.note(pid, "Submitted", f"By {u['id']} via {how}" + (f": {body.note}" if body.note else ""))
    store.log(pid, {"kind": "user", "stage": "rfp", "text": f"Submitted via {how}"})
    db.audit("rfp.submitted", pid, {"how": how, "note": body.note[:300]}, u["id"])
    return state(pid, u)


class MailIn(BaseModel):
    account: str
    to: list[str]
    subject: str = ""
    text: str = ""


@router.post("/api/rfp/{pid}/mail")
def submit_by_mail(pid: str, body: MailIn):
    """Submission by e-mail through the person's own sending account — only after the pack was accepted; recorded as submitted."""
    u, st = _get(pid, "edit")
    if st["status"] != "ready":
        raise HTTPException(409, "Accept the submission pack first: nothing is sent before a named person accepts it.")
    to = [t.strip() for t in body.to if t and mailer.EMAIL_RE.match(t.strip())]
    if not to:
        raise HTTPException(400, "Give at least one recipient address.")
    pack = (st.get("packs") or [{}])[-1]
    f = pack.get("files") or {}
    att = []
    for key, mime in (("doc_docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"), ("doc_pdf", "application/pdf"), ("xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
                      ("deck_pptx", "application/vnd.openxmlformats-officedocument.presentationml.presentation")):
        if f.get(key):
            att.append((f[key], mime, (folder(pid) / "builds" / f"v{pack['v']}" / f[key]).read_bytes()))
    b = registry.brand()
    subject = body.subject.strip()[:200] or f"Response: {st['name']}"
    html = f"<p>{(body.text.strip() or 'Please find our response attached.').replace(chr(10), '<br>')}</p><p style=\"color:#56626E;font-size:12px\">Sent from {b['full']}" + (f" · {b['powered']}" if b["partner"] else "") + "</p>"
    try:
        mailer.send(body.account, u["id"], to, subject, html, att)
    except mailer.EmailError as e:
        raise HTTPException(400, str(e))
    st.update(status="submitted", submitted={"by": u["id"], "when": time.time(), "how": "mail", "to": to, "subject": subject, "version": pack.get("v"), "files": [a[0] for a in att]})
    store.save(st)
    store.note(pid, "Submitted by mail", f"To {', '.join(to)} by {u['id']}")
    store.log(pid, {"kind": "user", "stage": "rfp", "text": f"Submitted by mail to {', '.join(to)}"})
    db.audit("rfp.submitted", pid, {"how": "mail", "to": to, "files": [a[0] for a in att]}, u["id"])
    return state(pid, u)


class OutcomeIn(BaseModel):
    result: str
    feedback: str = ""


@router.post("/api/rfp/{pid}/outcome")
def outcome(pid: str, body: OutcomeIn):
    """Learn: win / loss and the buyer's feedback; a won response's answers join the library as reusable items."""
    u, st = _get(pid, "edit")
    if st["status"] not in ("submitted", "won", "lost", "withdrawn"):
        raise HTTPException(409, "Record the outcome after the response was submitted.")
    result = body.result.strip().lower()
    if result not in ("won", "lost", "withdrawn"):
        raise HTTPException(400, "Result must be won, lost or withdrawn.")
    d = folder(pid)
    promoted = []
    if result == "won" and (st.get("outcome") or {}).get("result") != "won":
        mv = matrix_view(d)
        rv = requirements_view(d)
        have = {(r["response_id"], r["requirement_id"]) for r in db.q("SELECT response_id, requirement_id FROM rfp_library WHERE response_id = ?", (pid,))}
        for r in mv["rows"]:
            if r["status"] in ("Comply", "Partial", "Alternative") and r["answer"] and (pid, r["id"]) not in have:
                module = next((e["ref"].split(":", 1)[1] for e in r["evidence"] if e["kind"] == "module"), None)
                item = library_add(f"{r['id']}: {r['requirement'][:120]}", r["answer"], module, rv["buyer"]["type"] or st.get("buyer_type") or None,
                                   [r["status"], rv["buyer"]["name"] or st.get("buyer") or "", st["name"][:40]], "answer", origin=f"won:{pid}", response_id=pid, requirement_id=r["id"], won=True, who=u["id"])
                promoted.append(item["id"])
    st.update(status=result, outcome={"result": result, "feedback": body.feedback.strip()[:4000], "by": u["id"], "when": time.time(), "promoted": promoted})
    store.save(st)
    store.note(pid, f"Outcome: {result}", (body.feedback.strip() or "(no feedback recorded)") + (f"\n\n{len(promoted)} answer(s) promoted into the library." if promoted else ""))
    store.log(pid, {"kind": "user", "stage": "rfp", "text": f"Outcome recorded: {result}" + (f" — {len(promoted)} answers now reusable" if promoted else "")})
    db.audit("rfp.outcome", pid, {"result": result, "promoted": len(promoted), "feedback": body.feedback[:300]}, u["id"])
    return state(pid, u)


@router.post("/api/rfp/{pid}/retry")
def retry(pid: str):
    u, st = _get(pid, "edit")
    if st["status"] != "error":
        raise HTTPException(409, "Nothing to retry.")
    job = st.get("job") or {}
    kind = job.get("kind") or "rfp_read"
    store.log(pid, {"kind": "user", "stage": kind, "text": "Retry"})
    worker.enqueue(pid, kind, **{k: v for k, v in job.items() if k == "correction"})
    return state(pid, u)


@router.delete("/api/rfp/{pid}")
def delete_response(pid: str):
    u, st = _get(pid, "edit")
    if st["status"] in RUNNING and worker.current.get("pid") == pid:
        raise HTTPException(409, "Relay is working on it — stop it first.")
    for k in CP.values():
        checkpoints.withdraw(k, pid, who=u["id"])
    db.skip_queued(pid)
    shutil.rmtree(folder(pid), ignore_errors=True)
    db.run("DELETE FROM shares WHERE project_id = ?", (pid,))
    db.run("DELETE FROM projects WHERE id = ?", (pid,))
    db.audit("rfp.delete", pid, {"name": st.get("name")}, u["id"])
    return {"ok": True}


# ---------------------------------------------------------------- test hooks (D2D_TEST_HOOKS=1)

class HookIn(BaseModel):
    yaml: str = ""
    gonogo: str = ""
    summary: str = ""


def _hook_guard(pid: str) -> tuple[dict, dict]:
    if not TEST_HOOKS:
        raise HTTPException(404, "Not found")
    u, st = _get(pid, "edit")
    if worker.current.get("pid") == pid:
        raise HTTPException(409, "The agent is running for this response.")
    db.skip_queued(pid)
    return u, st


@router.post("/api/rfp/{pid}/hook/requirements")
def hook_requirements(pid: str, body: HookIn):
    u, st = _hook_guard(pid)
    d = folder(pid)
    (d / "requirements.yaml").write_text(body.yaml, encoding="utf-8")
    (d / "gonogo.yaml").write_text(body.gonogo, encoding="utf-8")
    _write_registry(d)
    problems = check_requirements(d, st)
    if problems:
        raise HTTPException(400, "; ".join(problems))
    requirements_read(pid, body.summary)
    return state(pid, u)


@router.post("/api/rfp/{pid}/hook/matrix")
def hook_matrix(pid: str, body: HookIn):
    u, st = _hook_guard(pid)
    d = folder(pid)
    _pick_library(d)
    _write_registry(d)
    (d / "matrix.yaml").write_text(body.yaml, encoding="utf-8")
    problems = check_matrix(d)
    if problems:
        raise HTTPException(400, "; ".join(problems))
    matrix_drafted(pid, body.summary)
    return state(pid, u)


@router.post("/api/rfp/{pid}/hook/redteam")
async def hook_redteam(pid: str, body: HookIn):
    u, st = _hook_guard(pid)
    d = folder(pid)
    (d / "redteam.yaml").write_text(body.yaml, encoding="utf-8")
    problems = check_redteam(d)
    if problems:
        raise HTTPException(400, "; ".join(problems))
    reviews_open(pid, body.summary)
    return state(pid, u)


@router.post("/api/rfp/{pid}/hook/pack")
async def hook_pack(pid: str):
    """Build the pack now (the worker would, after the three reviews): for the e2e test without an agent."""
    u, st = _hook_guard(pid)
    if st["status"] not in ("packing", "awaiting_reviews", "awaiting_submit"):
        raise HTTPException(409, f"Not at the packing step (status: {st['status']}).")
    rec = await asyncio.to_thread(build_pack, pid)
    pack_built(pid, rec)
    return state(pid, u)

