"""The ontology layer (item 61; the user, 2026-11-19: "ontology layer as well where we bring default ontology and kpi as
per industry and user can also configure and change"): an organisation's business vocabulary, kept in its own database
schema and used by every dashboard it plans (genbi_kit/ontology.py).

  onto_terms        its business terms: name, kind, entity, unit, aggregation, synonyms, description (the term as JSON)
  semreview_kpis    its KPI dictionary (semreview.py, item 55): the same KPIs Semantic Review checks models against
  meta 'ontology'   the industry packs it started from ({"packs": [...], "name": ..., "applied": ..., "by": ...})

An organisation applies an industry pack (Ontology, Industry): the pack's terms and KPIs are added to its own; what it
already has stays as it is unless it asks for the pack's versions. Then BI Devs and owners change it: add, edit or remove
terms and KPIs, teach a column name to a term (from a plan's semantic model: "sls_amt means Sales"). Everyone in the
organisation reads it. With no term of its own yet, columns are tagged with the general pack.

Every plan gets it: before planning, the worker writes ontology.json (terms, KPIs, the person's own column tags) and
ontology.md (the guide the agent reads) into the dashboard's folder (write_project_files); `genbi profile` tags each
column from it, and the plan uses the dictionary's KPI names and definitions (prompts.PLAN).
"""
from __future__ import annotations

import io
import json
import re
import secrets
import time

import yaml
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from genbi_kit import ontology as O
from genbi_kit.semreview import kpis as K

from . import auth, db, store

router = APIRouter()
db.register_schema("""
-- item 61: the ontology layer: an organisation's business terms (its KPI dictionary is semreview_kpis)
CREATE TABLE IF NOT EXISTS onto_terms (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, body TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL, updated_by TEXT);
""")
META = "ontology"
MAX_IMPORT_BYTES = 2 * 1024 * 1024


def _u() -> dict:
    u = auth.current.get()
    if not u:
        raise HTTPException(401, "Sign in to D2D Relay.")
    return u


def _need_dev(u: dict) -> None:
    if not auth.is_dev(u):
        raise HTTPException(403, "Your account can read the ontology, not change it. Ask an owner or a BI Dev of your organisation.")


# ---------------------------------------------------------------- reading

def settings() -> dict:
    try:
        s = json.loads(db.meta(META) or "{}")
    except ValueError:
        s = {}
    return s if isinstance(s, dict) else {}


def terms() -> list[dict]:
    """The organisation's business terms, by name (each with its id)."""
    out = []
    for r in db.q("SELECT id, body, updated FROM onto_terms ORDER BY lower(name)"):
        try:
            t = json.loads(r["body"])
        except ValueError:
            continue
        out.append({**t, "id": r["id"], "updated": r["updated"]})
    return out


def _plain(ts: list[dict]) -> list[dict]:
    return [{k: v for k, v in t.items() if k not in ("id", "updated")} for t in ts]


def kpis() -> list[dict]:
    from . import semreview
    return semreview.kpi_entries()


def effective_terms() -> list[dict]:
    """What tags columns: the organisation's own terms first, then the general pack's terms it has no term of that
    name for (so a pack or a taught column name never drops Year, Month, Cost ...); a general term loses a tie."""
    own = _plain(terms())
    names = {t["name"].lower() for t in own}
    return own + [{**t, "_default": True} for t in O.default_terms() if t["name"].lower() not in names]


def industry_name() -> str:
    s = settings()
    return s.get("name") or ""


def questions() -> list[str]:
    """Example questions of the industry packs the organisation applied (Ask Relay's suggestions)."""
    out: list[str] = []
    for pid in settings().get("packs") or ["general"]:
        try:
            out += O.pack(pid)["questions"]
        except O.OntologyError:
            continue
    return out[:12]


# ---------------------------------------------------------------- writing

def _save_term(t: dict, u: dict, tid: str | None = None) -> dict:
    now = time.time()
    if tid:
        db.run("UPDATE onto_terms SET name = ?, body = ?, updated = ?, updated_by = ? WHERE id = ?",
               (t["name"], json.dumps(t), now, u.get("id"), tid))
    else:
        tid = "t-" + secrets.token_hex(5)
        db.run("INSERT INTO onto_terms (id, name, body, created, updated, updated_by) VALUES (?, ?, ?, ?, ?, ?)",
               (tid, t["name"], json.dumps(t), now, now, u.get("id")))
    return {**t, "id": tid, "updated": now}


def _check_term(t: dict, current: list[dict], tid: str | None) -> None:
    """One name per term, and no name or synonym two terms of one kind share (a column could not be told apart)."""
    others = [x for x in current if x.get("id") != tid]
    if any(x["name"].lower() == t["name"].lower() for x in others):
        raise O.OntologyError(f"{t['name']} is already a business term: change that one instead.")
    clash = O.conflicts(_plain(others) + [t])
    mine = [c for c in clash if t["name"] in c]
    if mine:
        raise O.OntologyError(mine[0] + ": one name tags one kind of column.")
    if len(others) + 1 > O.MAX_TERMS:
        raise O.OntologyError(f"An ontology holds up to {O.MAX_TERMS:,} business terms.")


def apply_pack(pid: str, u: dict, replace: bool = False) -> dict:
    """Add an industry pack's terms and KPIs to the organisation's (replace: the pack's versions win for names it
    already has). Returns what changed. KPIs whose name or other names belong to another KPI of the organisation are
    left out (one name stands for one KPI)."""
    from . import semreview
    p = O.pack(pid)
    have = terms()
    by_name = {t["name"].lower(): t for t in have}
    n_terms = {"added": 0, "kept": 0, "replaced": 0, "skipped": 0}
    with db.transaction():
        for t in p["terms"]:
            old = by_name.get(t["name"].lower())
            if old and not replace:
                n_terms["kept"] += 1
                continue
            try:
                _check_term(t, [x for x in have if not old or x["id"] != old["id"]], old["id"] if old else None)
            except O.OntologyError:
                n_terms["skipped"] += 1
                continue
            saved = _save_term(t, u, old["id"] if old else None)
            have = [x for x in have if not old or x["id"] != old["id"]] + [saved]
            n_terms["replaced" if old else "added"] += 1
        current = semreview.kpi_list()
        n_kpis = {"added": 0, "kept": 0, "replaced": 0, "skipped": 0}
        now = time.time()
        for k in p["kpis"]:
            old = next((x for x in current if K.norm(x["name"]) == K.norm(k["name"])), None)
            if old and not replace:
                n_kpis["kept"] += 1
                continue
            taken = semreview._names_taken(current, old["id"] if old else None)          # noqa: SLF001
            try:
                semreview._check_entry(k, taken)                                       # noqa: SLF001
            except K.KpiError:
                n_kpis["skipped"] += 1
                continue
            if len(current) >= K.MAX_KPIS and not old:
                n_kpis["skipped"] += 1
                continue
            if old:
                db.run("UPDATE semreview_kpis SET name = ?, body = ?, updated = ?, updated_by = ? WHERE id = ?",
                       (k["name"], json.dumps(k), now, u.get("id"), old["id"]))
                current = [x for x in current if x["id"] != old["id"]] + [{**k, "id": old["id"]}]
                n_kpis["replaced"] += 1
            else:
                kid = "k-" + secrets.token_hex(5)
                db.run("INSERT INTO semreview_kpis (id, name, body, created, updated, updated_by) VALUES (?, ?, ?, ?, ?, ?)",
                       (kid, k["name"], json.dumps(k), now, now, u.get("id")))
                current.append({**k, "id": kid})
                n_kpis["added"] += 1
        s = settings()
        packs = [x for x in s.get("packs") or [] if x != pid] + [pid]
        names = []
        for x in packs:
            try:
                names.append(O.pack(x)["name"])
            except O.OntologyError:
                continue
        db.set_meta(META, json.dumps({"packs": packs, "name": ", ".join(names), "applied": time.time(),
                                      "by": u.get("name") or u.get("email")}))
    db.audit("ontology.pack", pid, {"terms": n_terms, "kpis": n_kpis, "replace": replace}, u.get("id"))
    return {"pack": p["name"], "terms": n_terms, "kpis": n_kpis}


def apply_pack_cli(tid: str, pid: str) -> dict:
    """For PASDACS (python -m app.ontology apply <workspace> <pack>, or a new organisation's industry): apply a pack in
    an organisation's workspace as PASDACS."""
    with db.use(tid):
        return apply_pack(pid, {"id": "pasdacs", "name": "PASDACS"})


# ---------------------------------------------------------------- a dashboard's copy (read by genbi profile and the agent)

def project_ontology(pid: str) -> dict:
    """What a dashboard's planning gets: the organisation's terms (or the general pack's), its KPI dictionary, its
    industry, and the person's own column tags on this dashboard (project.json semantic_overrides)."""
    st = store.load(pid)
    return {"industry": industry_name(), "terms": effective_terms(), "kpis": kpis(),
            "overrides": {str(k): str(v or "") for k, v in (st.get("semantic_overrides") or {}).items()},
            "written": time.time()}


def write_project_files(pid: str, found: list[str] | None = None) -> dict:
    """ontology.json and ontology.md in the dashboard's folder (planning, building, revising). found: business terms
    the data's columns have (they and their KPIs come first in ontology.md)."""
    d = store.project_dir(pid)
    onto = project_ontology(pid)
    try:                                        # item 81: what the owners accepted about the organisation (its setup)
        from . import orgsetup
        org = orgsetup.for_project()
    except Exception:  # noqa: BLE001 - the plan goes on without it; the log says why
        import traceback
        traceback.print_exc()
        org = None
    if org:
        onto["organisation"] = org
    (d / "ontology.json").write_text(json.dumps(onto, indent=1), encoding="utf-8")
    (d / "ontology.md").write_text(O.guide(onto, found), encoding="utf-8")
    return onto


def semantic_view(pid: str) -> dict | None:
    """The plan screen's semantic model: every table with its columns, types, keys and business terms, the
    relationships found, the terms found in several columns and keys of one entity (profile.json), and how much of
    the data is a sample (sample.json). None before the data was read."""
    from genbi_kit import sampling
    d = store.project_dir(pid)
    try:
        prof = json.loads((d / "profile.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    tables = []
    for t in prof.get("tables") or []:
        tables.append({"file": t["file"], "rows": t["rows"], "sample_of": t.get("sample_of"),
                       "columns": [{"name": c["name"], "type": c["type"], "unique": bool(c.get("unique")), "nulls": c.get("nulls", 0),
                                    "distinct": c.get("distinct"), **({"tag": c["tag"]} if c.get("tag") else {})}
                                   for c in t.get("columns") or []]})
    sp = sampling.spec(d) or {}
    return {"tables": tables, "relationships": prof.get("relationships") or [], "semantic": prof.get("semantic") or {},
            "industry": prof.get("industry") or "", "unreadable": prof.get("unreadable") or [],
            "sample": {"method": sp.get("method"), "files": sp.get("files") or {}} if sp else None}


def mark_plan_kpis(pid: str) -> dict:
    """Which of a plan's KPIs are KPIs of the organisation's dictionary (the agent's `dictionary:` on the KPI, else its
    name or another name of a dictionary KPI): project.json plan_dictionary {KPI name: dictionary name}."""
    from genbi_kit import definition
    d = store.project_dir(pid)
    try:
        plan = definition.load(d / "plan.yaml")
    except Exception:  # noqa: BLE001
        return {}
    entries = kpis()
    m = K.Matcher(entries) if entries else None
    out = {}
    for k in plan.get("kpis") or []:
        if not m or not isinstance(k, dict):
            continue
        hit = None
        for said in (k.get("dictionary"), k.get("name")):
            if said:
                i, how, _ = m.match(str(said))
                if i is not None and how in ("name", "synonym"):
                    hit = entries[i]["name"]
                    break
        if hit:
            out[str(k.get("name"))] = hit
    store.update(pid, plan_dictionary=out)
    return out


def approval_items(st: dict) -> list[dict]:
    """Item 73 (the user, 2026-11-19: "data needs to be reviewed and let them know if any gaps or assumptions made ...
    any deviation or assumption or calculation needs to be approved"): what the person approves, one by one, before the
    plan is confirmed: the gaps and assumptions the plan lists (plan.yaml) and the analyst review found, and every KPI
    that differs from the organisation's KPI dictionary. Each has a stable id (its kind and text)."""
    import hashlib
    pr = st.get("plan_review") or {}
    items: list[dict] = []

    def add(kind: str, text, source: str) -> None:
        t = " ".join(str(text or "").split())[:600]
        if not t:
            return
        iid = kind[:3] + "-" + hashlib.sha1(f"{kind}|{t.lower()}".encode()).hexdigest()[:10]
        if all(i["id"] != iid for i in items):
            items.append({"id": iid, "kind": kind, "text": t, "source": source})
    for x in pr.get("plan_gaps") or []:
        add("gap", x, "plan")
    for x in pr.get("gaps") or []:
        add("gap", x, "review")
    for x in pr.get("plan_assumptions") or []:
        add("assumption", x, "plan")
    for x in pr.get("assumptions") or []:
        add("assumption", x, "review")
    for x in pr.get("deviations") or []:
        add("deviation", f"{x.get('kpi')}: {x.get('difference')}" + (f" (your KPI dictionary's {x['dictionary']})" if x.get("dictionary") else ""), "review")
    return items


# ---------------------------------------------------------------- a dashboard's semantic model (the plan screen)

@router.get("/api/projects/{pid}/semantic")
def project_semantic(pid: str):
    """The semantic model of a dashboard's data: its tables, columns, business terms and relationships (semantic_view),
    the terms a column can be given, and the person's own tags."""
    u = _u()
    st = store.load(pid)
    view = semantic_view(pid)
    names = [{"name": t["name"], "kind": t["kind"], **({"entity": t["entity"]} if t.get("entity") else {})} for t in effective_terms()]
    from . import db as _db
    can_edit = auth.can_project(u, "edit", _db.project(pid))
    return {"view": view, "overrides": st.get("semantic_overrides") or {}, "terms": names, "industry": industry_name(),
            "may_tag": st.get("status") == "awaiting_kpis" and can_edit, "may_teach": auth.is_dev(u) and can_edit,
            "plan_dictionary": st.get("plan_dictionary") or {}, "data_size": st.get("data_size")}


class TagsBody(BaseModel):
    overrides: dict[str, str] = {}      # {"file.csv[column]": "Term name" or "" for no term}


@router.put("/api/projects/{pid}/semantic")
async def project_tags(pid: str, body: TagsBody):
    """The person's own business terms for columns of this dashboard (free): the profile is made again with them, and
    the build uses them (ontology.json). While the plan waits for the KPIs to be confirmed."""
    import asyncio
    from genbi_kit.profile import profile
    _u()
    st = store.load(pid)
    if st.get("status") != "awaiting_kpis":
        raise HTTPException(409, "Columns can be tagged while the plan waits for you to confirm the KPIs.")
    view = semantic_view(pid) or {}
    refs = {f"{t['file']}[{c['name']}]" for t in view.get("tables") or [] for c in t["columns"]}
    known = {t["name"].lower(): t["name"] for t in effective_terms()}
    clean = dict(st.get("semantic_overrides") or {})
    for ref, term in (body.overrides or {}).items():
        if ref not in refs:
            raise HTTPException(400, f"{ref} is not a column of this dashboard's data.")
        if term and term.lower() not in known:
            raise HTTPException(400, f"{term} is not a business term of your ontology.")
        clean[ref] = known.get((term or "").lower(), "")
    store.update(pid, semantic_overrides=clean)
    write_project_files(pid)
    d = store.project_dir(pid)
    await asyncio.to_thread(profile, d)
    view = semantic_view(pid) or {}
    found = sorted({c["tag"]["term"] for t in view.get("tables") or [] for c in t["columns"] if c.get("tag")})
    write_project_files(pid, found)
    store.log(pid, {"kind": "user", "stage": "plan", "text": "Tagged columns: " + ", ".join(
        f"{r} = {t or 'no term'}" for r, t in (body.overrides or {}).items())[:500]})
    return project_semantic(pid)


# ---------------------------------------------------------------- the API

@router.get("/api/ontology")
def get_ontology():
    u = _u()
    own = terms()
    return {"industry": settings(), "packs": O.packs(), "terms": own, "kpis": len(kpis()), "may_edit": auth.is_dev(u),
            "using_default": not own, "default_terms": len(O.default_terms()) if not own else 0,
            "conflicts": O.conflicts(_plain(own)), "kinds": list(O.KINDS), "units": list(O.UNITS),
            "aggregations": list(O.AGGREGATIONS), "questions": questions()}


@router.get("/api/ontology/packs/{pid}")
def get_pack(pid: str):
    _u()
    try:
        p = O.pack(pid)
    except O.OntologyError as e:
        raise HTTPException(404, str(e)) from None
    return p


class ApplyBody(BaseModel):
    pack: str
    replace: bool = False


@router.post("/api/ontology/industry")
def apply_industry(body: ApplyBody):
    u = _u()
    _need_dev(u)
    try:
        out = apply_pack(body.pack, u, body.replace)
    except O.OntologyError as e:
        raise HTTPException(404, str(e)) from None
    return {**get_ontology(), "applied": out}


class TermBody(BaseModel):
    name: str
    kind: str = "attribute"
    entity: str | None = None
    unit: str | None = None
    aggregation: str | None = None
    synonyms: list[str] | str | None = None
    description: str | None = None
    family: str | None = None


def _term_save(body: TermBody, u: dict, tid: str | None = None) -> dict:
    try:
        t = O.clean_term(body.model_dump(exclude_none=True))
        current = terms()
        if tid and not any(x["id"] == tid for x in current):
            raise HTTPException(404, "That business term is not in the ontology.")
        _check_term(t, current, tid)
    except O.OntologyError as e:
        raise HTTPException(400, str(e)) from None
    saved = _save_term(t, u, tid)
    db.audit("ontology.term_save", saved["id"], {"name": t["name"]}, u["id"])
    return saved


@router.post("/api/ontology/terms")
def add_term(body: TermBody):
    u = _u()
    _need_dev(u)
    return _term_save(body, u)


@router.put("/api/ontology/terms/{tid}")
def edit_term(tid: str, body: TermBody):
    u = _u()
    _need_dev(u)
    return _term_save(body, u, tid)


@router.delete("/api/ontology/terms/{tid}")
def delete_term(tid: str):
    u = _u()
    _need_dev(u)
    row = db.one("SELECT name FROM onto_terms WHERE id = ?", (tid,))
    if not row:
        raise HTTPException(404, "That business term is not in the ontology.")
    db.run("DELETE FROM onto_terms WHERE id = ?", (tid,))
    db.audit("ontology.term_delete", tid, {"name": row["name"]}, u["id"])
    return {"deleted": tid}


class TeachBody(BaseModel):
    term: str                           # the term's name
    synonym: str                        # a column name, e.g. sls_amt


@router.post("/api/ontology/teach")
def teach(body: TeachBody):
    """'sls_amt means Sales': a column name becomes another name of a term (the organisation's own copy of the general
    pack's term when it has none of its own yet), so the next data with that column is tagged on its own."""
    u = _u()
    _need_dev(u)
    syn = re.sub(r"\s+", " ", body.synonym or "").strip()[:O.LIMITS["synonym"]]
    if not O.words(syn):
        raise HTTPException(400, "Give the column name to teach.")
    current = terms()
    t = next((x for x in current if x["name"].lower() == (body.term or "").strip().lower()), None)
    if not t:
        base = next((x for x in O.default_terms() if x["name"].lower() == (body.term or "").strip().lower()), None)
        if not base:
            raise HTTPException(404, "That business term is not in the ontology.")
        t = {**base}
    plain = {k: v for k, v in t.items() if k not in ("id", "updated")}
    if any(O.words(s) == O.words(syn) for s in [plain["name"]] + list(plain.get("synonyms") or [])):
        return {"term": t, "taught": False}
    plain["synonyms"] = (list(plain.get("synonyms") or []) + [syn])[-O.MAX_SYNONYMS:]
    try:
        plain = O.clean_term(plain)
        _check_term(plain, current, t.get("id"))
    except O.OntologyError as e:
        raise HTTPException(400, str(e)) from None
    saved = _save_term(plain, u, t.get("id"))
    db.audit("ontology.teach", saved["id"], {"term": plain["name"], "synonym": syn}, u["id"])
    return {"term": saved, "taught": True}


class MatchBody(BaseModel):
    columns: list[dict] = []           # [{name, type}] (type: int, decimal, string, date, bool)


@router.post("/api/ontology/match")
def match(body: MatchBody):
    """Try column names against the ontology (the Ontology screen's "Try a column name")."""
    _u()
    tagger = O.Tagger(effective_terms())
    out = []
    for c in body.columns[:200]:
        name = str(c.get("name") or "")[:120]
        typ = c.get("type") if c.get("type") in ("int", "decimal", "string", "date", "bool") else "string"
        out.append({"name": name, "type": typ, "words": O.words(name), "tag": tagger.tag({"name": name, "type": typ})})
    return {"columns": out}


@router.get("/api/ontology/export.yaml")
def export_yaml():
    _u()
    data = {"industry": industry_name(), "terms": _plain(terms()), "kpis": kpis()}
    text = yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=120)
    return Response(text, media_type="application/x-yaml; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="d2d-relay-ontology.yaml"', "Cache-Control": "no-store"})


@router.post("/api/ontology/import")
async def import_terms(file: UploadFile = File(...), replace: str = Form("0")):
    """Business terms from a YAML or JSON file ({"terms": [...]} or a list): merged by name (replace=1: the file's
    versions win). KPIs come through the KPI dictionary's own import (Semantic Review)."""
    u = _u()
    _need_dev(u)
    raw = await file.read(MAX_IMPORT_BYTES + 1)
    if len(raw) > MAX_IMPORT_BYTES:
        raise HTTPException(413, "The file is larger than 2 MB.")
    try:
        doc = yaml.safe_load(io.BytesIO(raw).read().decode("utf-8-sig"))
        items = doc.get("terms") if isinstance(doc, dict) else doc
        new = O.clean_terms(items if isinstance(items, list) else [])
    except (yaml.YAMLError, UnicodeDecodeError, O.OntologyError) as e:
        raise HTTPException(400, f"The file could not be read as business terms: {str(e).splitlines()[0][:200]}") from None
    if not new:
        raise HTTPException(400, "The file has no business terms (a list of terms, or terms: [...]).")
    have = terms()
    by = {t["name"].lower(): t for t in have}
    n = {"added": 0, "kept": 0, "replaced": 0, "skipped": 0}
    with db.transaction():
        for t in new:
            old = by.get(t["name"].lower())
            if old and replace != "1":
                n["kept"] += 1
                continue
            try:
                _check_term(t, [x for x in have if not old or x["id"] != old["id"]], old["id"] if old else None)
            except O.OntologyError:
                n["skipped"] += 1
                continue
            saved = _save_term(t, u, old["id"] if old else None)
            have = [x for x in have if not old or x["id"] != old["id"]] + [saved]
            n["replaced" if old else "added"] += 1
    db.audit("ontology.import", None, n, u["id"])
    return {**get_ontology(), "imported": n}


if __name__ == "__main__":                 # python -m app.ontology packs | apply <workspace> <pack>
    import sys
    db.init()
    if len(sys.argv) >= 2 and sys.argv[1] == "packs":
        for p in O.packs():
            print(f"{p['id']:22} {p['terms']:4} terms {p['kpis']:4} KPIs  {p['name']}")
    elif len(sys.argv) == 4 and sys.argv[1] == "apply":
        print(json.dumps(apply_pack_cli(sys.argv[2], sys.argv[3])))
    else:
        print("python -m app.ontology packs | apply <workspace> <pack>")
