"""Test plans & UAT scripts (registry id `testdocs`) - from requirements to signed-off tests, rules first (no agent step).

Develop  Describe -> Shape -> Build -> Prove -> Ship -> Run. The requirements come from an approved BRD (BRD & requirements)
         or an uploaded list (CSV or Excel: id, requirement, acceptance criteria one per line). Shape turns every
         Given / When / Then criterion into a test case by rules - Given becomes the preconditions, When the steps, Then
         the expected result - plus a boundary case where a criterion names a limit ("over 10,000", "within 3 days")
         and a negative case where it says what must not happen; you correct them in place. Build writes the UAT
         scripts per requirement with synthetic test data (boundary values from the criterion's own numbers), the test
         plan (Excel), the UAT scripts (Word, the tenant's template) and import files for Xray, Zephyr Scale and
         TestRail. Prove checks coverage (every requirement and criterion has a case), that every case points at a real
         requirement, that every case can run (steps, expected result, data) and flags duplicates. Ship is the business
         sign-off by the named approver. Run publishes the plan (versions kept) and links each requirement to its tests
         in the lineage graph, which BRD & requirements' Trace shows.
Change   Request -> Diagnose -> Fix -> Prove -> Approve -> Learn: a published plan against the BRD's newer version (or a new
         upload) - added, changed and removed criteria, the cases they touch, new cases suggested, retired ones marked.
Migrate  Discover -> Decide -> Convert -> Prove -> Hand over -> Run: test cases exported from TestRail, Zephyr, Xray or Excel;
         keep, merge (duplicates suggested) or retire each; converted to the target tool's import format; proven
         case for case (counts, steps and expected results unchanged, references kept); published as a plan.
Test managers: with a Jira Xray, Zephyr Scale or TestRail connection on the item, Run (and Change's Learn) asks to write
the plan's new cases there - each write after its own approval - and reads them back, case by case (testdocs_managers.py).
Without one, the import files are what a person loads.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import secrets as _secrets
import time
from pathlib import Path

from .. import auth, db
from .. import workbench as wb
from . import _w4
from . import testdocs_managers as tmg

MODULE = "testdocs"
SYSTEM = "Relay test plans"
BRD_SYSTEM = "Relay BRD"
UPLOADS = (".csv", ".tsv", ".xlsx")
TYPES = (("positive", "Positive"), ("boundary", "Boundary"), ("negative", "Negative"), ("regression", "Regression"))
PRIORITY = (("must", "Must"), ("should", "Should"), ("could", "Could"), ("wont", "Won't"))
TARGETS = (("xray", "Jira Xray (CSV importer)"), ("zephyr", "Zephyr Scale (CSV import)"), ("testrail", "TestRail (CSV import)"), ("excel", "Excel workbook"))
DECISIONS = (("keep", "Keep"), ("merge", "Merge into another case"), ("retire", "Retire"))

db.register_schema("""
CREATE TABLE IF NOT EXISTS testdocs_plans (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, item TEXT, brd_id TEXT, brd_version INTEGER, version INTEGER NOT NULL DEFAULT 1,
  requirements TEXT NOT NULL DEFAULT '[]', cases TEXT NOT NULL DEFAULT '[]', owner_id TEXT, published_by TEXT, published REAL,
  created REAL NOT NULL, updated REAL NOT NULL);
CREATE TABLE IF NOT EXISTS testdocs_versions (
  plan_id TEXT NOT NULL, version INTEGER NOT NULL, item TEXT, brd_version INTEGER, requirements TEXT NOT NULL, cases TEXT NOT NULL,
  published_by TEXT, published REAL NOT NULL, note TEXT, PRIMARY KEY (plan_id, version));
""")

FILES = wb.FilesPlatform()
FILES.label = "Requirement lists and test-case exports"
FILES.uploads = UPLOADS
FILES.reads = ("a list of requirements (id, requirement, acceptance criteria - Given / When / Then, one per line), or test cases exported "
               "from TestRail, Zephyr Scale, Xray or Excel - a copy in this work item's folder")
FILES.simulator = "the test writes its own fixtures; tests/mocklab/sims/process.py has the xray, zephyr and testrail simulators the exports mirror"


# ------------------------------------------------------------------ the published plans (versions kept)

def _plan_row(r: dict) -> dict:
    return {**r, "requirements": _w4.j(r["requirements"], []), "cases": _w4.j(r["cases"], [])}


def plan(pid: str, u: dict | None = None) -> dict | None:
    r = db.one("SELECT * FROM testdocs_plans WHERE id = ?", (pid,))
    if not r:
        return None
    if u is not None and r.get("item") and not auth.can_project(u, "view", db.project(r["item"])):
        return None
    return _plan_row(r)


def plans(u: dict) -> list[dict]:
    return _w4.visible_items(u, [_plan_row(r) for r in db.q("SELECT * FROM testdocs_plans ORDER BY updated DESC")])


def plan_options(u: dict) -> list[tuple[str, str]]:
    return [(p["id"], f"{p['name']} - version {p['version']} - {len(p['cases'])} cases") for p in plans(u)]


def _brd_options(u: dict) -> list[tuple[str, str]]:
    try:
        from . import brd
        return [("", "None - I upload a list of requirements")] + brd.document_options(u)
    except Exception:  # noqa: BLE001 - BRD & requirements not here: upload the requirements
        return [("", "None - I upload a list of requirements")]


def publish(ctx: wb.Ctx, reqs: list[dict], cases: list[dict], pid: str | None, note: str = "") -> dict:
    now = time.time()
    who = ctx.who or ctx.owner
    src = ctx.get("brd") or {}
    rq = [{k: r.get(k) for k in ("req", "title", "acceptance", "priority")} for r in reqs]
    cs = [{k: c.get(k) for k in ("id", "req", "type", "title", "preconditions", "steps", "expected", "data", "priority")} for c in cases]
    if pid and db.one("SELECT 1 FROM testdocs_plans WHERE id = ?", (pid,)):
        v = db.one("SELECT version FROM testdocs_plans WHERE id = ?", (pid,))["version"] + 1
        db.run("UPDATE testdocs_plans SET version = ?, requirements = ?, cases = ?, brd_id = ?, brd_version = ?, published_by = ?, published = ?, updated = ? WHERE id = ?",
               (v, json.dumps(rq), json.dumps(cs), src.get("id"), src.get("version"), who, now, now, pid))
    else:
        pid, v = "tp-" + _secrets.token_hex(4), 1
        db.run("INSERT INTO testdocs_plans (id, name, item, brd_id, brd_version, version, requirements, cases, owner_id, published_by, published, created, updated) "
               "VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?)",
               (pid, ctx.title[:160], ctx.id, src.get("id"), src.get("version"), json.dumps(rq), json.dumps(cs), ctx.owner, who, now, now, now))
    db.run("INSERT OR REPLACE INTO testdocs_versions (plan_id, version, item, brd_version, requirements, cases, published_by, published, note) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
           (pid, v, ctx.id, src.get("version"), json.dumps(rq), json.dumps(cs), who, now, note[:500] or None))
    db.audit("testdocs.publish", pid, {"version": v, "cases": len(cs), "requirements": len(rq), "item": ctx.id}, who)
    return plan(pid)


# ------------------------------------------------------------------ reading: requirement lists and test-case exports

def _rows(path: Path) -> list[dict]:
    if path.suffix.lower() == ".xlsx":
        import openpyxl
        book = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
        raw = [["" if v is None else str(v).strip() for v in r] for r in book.worksheets[0].iter_rows(values_only=True)]
        book.close()
    else:
        with path.open(encoding="utf-8-sig", newline="", errors="replace") as fh:
            raw = [[c.strip() for c in r] for r in csv.reader(fh, delimiter="\t" if path.suffix.lower() == ".tsv" else ",")]
    raw = [r for r in raw if any(r)]
    if not raw:
        return []
    head = [h.strip() for h in raw[0]]
    return [dict(zip(head, r + [""] * (len(head) - len(r)))) for r in raw[1:]]


def _col(row: dict, *names) -> str:
    low = {k.lower().strip(): v for k, v in row.items()}
    return next((str(low[n]).strip() for n in names if n in low and str(low[n]).strip()), "")


def _keys(rows: list[dict]) -> set:
    return {k.lower().strip() for k in (rows[0] if rows else {})}


REQ_ID = ("id", "requirement id", "req", "req id", "key", "story")
REQ_TEXT = ("requirement", "statement", "title", "summary", "description")
REQ_ACC = ("acceptance criteria", "acceptance", "criteria", "acceptance_criteria")
CASE_TITLE = ("title", "test summary", "summary", "name", "test case", "test case title")
CASE_STEPS = ("steps", "action", "steps (step)", "test script (step-by-step) - step", "test steps", "step")
CASE_EXP = ("expected result", "expected", "expected results", "steps (expected result)", "test script (step-by-step) - expected result")
CASE_REF = ("references", "requirement", "coverage (issues)", "coverage", "issue links", "refs", "requirement id")


def _tool_of(keys: set) -> str:
    if "test summary" in keys or "test type" in keys:
        return "Xray"
    if any(k.startswith("test script") for k in keys) or "objective" in keys:
        return "Zephyr Scale"
    if "references" in keys or "section" in keys or "steps (step)" in keys:
        return "TestRail"
    return "Excel"


def classify(ctx: wb.Ctx) -> dict:
    """Each upload as what it is: a requirement list or a test-case export (with the tool it came from)."""
    out = {"requirements": [], "cases": []}
    for f in ctx.files(UPLOADS):
        if f["name"].endswith(".xlsx.csv"):
            continue
        rows = _rows(ctx.dir / "data" / f["name"])
        if not rows:
            continue
        keys = _keys(rows)
        if any(k in keys for k in CASE_EXP) and any(k in keys for k in CASE_STEPS + CASE_TITLE):
            out["cases"].append((f["name"], _tool_of(keys), rows))
        elif any(k in keys for k in REQ_ACC) or (any(k in keys for k in REQ_ID) and any(k in keys for k in REQ_TEXT)):
            out["requirements"].append((f["name"], rows))
    return out


# ------------------------------------------------------------------ the rules: Given / When / Then -> test cases

GWT = re.compile(r"^\s*given\s+(?P<given>.+?),?\s+when\s+(?P<when>.+?),?\s+then\s+(?P<then>.+?)\s*\.?\s*$", re.I | re.S)
NEG = re.compile(r"\b(not|never|no|cannot|can't|is refused|is rejected|is blocked|without)\b", re.I)
LIMIT = re.compile(r"\b(over|above|more than|greater than|at least|exceeds?|under|below|less than|within|up to|at most|no more than)\s+"
                   r"(?P<cur>[₹$€£]\s?)?(?P<num>\d[\d,]*(?:\.\d+)?)\s*(?P<unit>%|percent|days?|hours?|minutes?|lakh|crore|k)?", re.I)
UPPER = ("under", "below", "less than", "within", "up to", "at most", "no more than")


def split_gwt(text: str) -> dict | None:
    m = GWT.match(str(text or "").strip())
    if not m:
        return None
    return {k: re.sub(r"\s+", " ", m.group(k)).strip().rstrip(".") for k in ("given", "when", "then")}


def limit_of(text: str) -> dict | None:
    m = LIMIT.search(str(text or ""))
    if not m:
        return None
    raw = m.group("num").replace(",", "")
    try:
        n = float(raw)
    except ValueError:
        return None
    word = m.group(1).lower()
    step = 1 if n == int(n) else 0.01
    return {"word": word, "value": n, "text": m.group(0), "unit": (m.group("unit") or "").strip(), "cur": (m.group("cur") or "").strip(),
            "upper": word in UPPER, "inclusive": word in ("at least", "within", "up to", "at most", "no more than"), "step": step}


def _fmt(n: float, cur: str = "", unit: str = "") -> str:
    s = f"{int(n):,}" if n == int(n) else f"{n:,.2f}"
    return f"{cur}{s}{(' ' + unit) if unit and unit != '%' else unit}"


def boundary_data(lim: dict) -> list[dict]:
    """The values either side of a limit and what each should do: the criterion's own number, never an invented one."""
    v, st = lim["value"], lim["step"]
    if lim["upper"]:                     # under / below / less than (the limit itself fails); within / up to / at most (it meets)
        inside, outside = (v, v + st) if lim["inclusive"] else (v - st, v)
    else:                                # over / above / more than (the limit itself fails); at least (it meets)
        inside, outside = (v, v - st) if lim["inclusive"] else (v + st, v)
    return [{"value": _fmt(inside, lim["cur"], lim["unit"]), "meets": True}, {"value": _fmt(outside, lim["cur"], lim["unit"]), "meets": False}]


def cases_for(req: dict) -> list[dict]:
    """Rules first: one positive case per criterion; a boundary case where it names a limit; a negative case where it
    says what must not happen. Every case keeps its criterion so a change can find it again."""
    out = []
    crit = [c for c in str(req.get("acceptance") or "").splitlines() if c.strip()]
    for i, c in enumerate(crit, 1):
        g = split_gwt(c)
        if not g:
            continue
        base = {"req": req["req"], "criterion": i, "criterion_text": c.strip(), "priority": req.get("priority") or "should", "origin": "rules"}
        steps = "\n".join(f"{k}. {s.strip()[:1].upper() + s.strip()[1:]}" for k, s in enumerate(re.split(r"\s+and\s+", g["when"]), 1))
        kind = "negative" if NEG.search(g["then"]) else "positive"
        out.append({**base, "id": f"TC-{req['req']}-{i:02d}", "type": kind, "title": f"{req['req']}: {g['then'][:90]}",
                    "preconditions": g["given"][:1].upper() + g["given"][1:], "steps": steps, "expected": g["then"][:1].upper() + g["then"][1:],
                    "data": "a record that matches the preconditions"})
        lim = limit_of(c)
        if lim:
            vals = boundary_data(lim)
            out.append({**base, "id": f"TC-{req['req']}-{i:02d}B", "type": "boundary", "title": f"{req['req']}: the limit \"{lim['text']}\" at its edge",
                        "preconditions": g["given"][:1].upper() + g["given"][1:], "steps": steps,
                        "expected": f"At {vals[0]['value']}: {g['then']}. At {vals[1]['value']}: it does not.",
                        "data": "; ".join(f"{x['value']} ({'meets' if x['meets'] else 'does not meet'} \"{lim['text']}\")" for x in vals)})
    return out


def _norm(s) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", str(s or "").lower())).strip()


def fingerprint(c: dict) -> str:
    return hashlib.sha1(f"{_norm(c.get('steps'))}|{_norm(c.get('expected'))}".encode()).hexdigest()[:12]


def case_problems(c: dict, reqs: set | None, retire_ok: bool = False) -> list[str]:
    who = c.get("id") or "a case"
    out = []
    if not str(c.get("id") or "").strip():
        out.append("a test case needs an id")
    if retire_ok and c.get("decision") in ("retire", "merge"):
        return out
    if not str(c.get("steps") or "").strip():
        out.append(f"{who}: write the steps")
    if not str(c.get("expected") or "").strip():
        out.append(f"{who}: write the expected result")
    if c.get("type") not in dict(TYPES):
        out.append(f"{who}: pick positive, boundary, negative or regression")
    if reqs is not None and c.get("req") not in reqs:
        out.append(f"{who}: {c.get('req') or '(none)'} is not one of the requirements")
    return out


# ------------------------------------------------------------------ Develop

def _reqs_from_brd(did: str, ctx: wb.Ctx) -> list[dict]:
    from . import brd
    d = brd.document(did, db.user(ctx.owner or "") or {})
    if not d:
        raise wb.StepFailed("The BRD is not one this work item's owner can see.")
    ctx.put("brd", {"id": d["id"], "title": d["title"], "version": d["version"]})
    out = []
    for r in d["requirements"]:
        if r.get("keep") is False:
            continue
        out.append({"id": r.get("req") or r.get("id"), "req": r.get("req") or r.get("id"), "title": (r.get("title") or r.get("statement") or "")[:200],
                    "acceptance": r.get("acceptance") or "", "priority": r.get("priority") or "should", "from": f"BRD \"{d['title']}\" version {d['version']}"})
    return out


def _reqs_from_uploads(ctx: wb.Ctx) -> list[dict]:
    out = []
    for name, rows in classify(ctx)["requirements"]:
        for i, r in enumerate(rows, 2):
            rid = _col(r, *REQ_ID) or f"R{len(out) + 1}"
            acc = _col(r, *REQ_ACC)
            acc = "\n".join(x.strip() for x in re.split(r"\n|;\s*(?=given\b)", acc, flags=re.I) if x.strip())
            out.append({"id": rid, "req": rid, "title": _col(r, *REQ_TEXT)[:200], "acceptance": acc, "priority": (_col(r, "priority", "moscow") or "should").lower(),
                        "from": f"{name} row {i}"})
    return out


def requirements(ctx: wb.Ctx) -> list[dict]:
    did = ctx.scope.get("brd") or ""
    reqs = (_reqs_from_brd(did, ctx) if did else []) + _reqs_from_uploads(ctx)
    seen, out = set(), []
    for r in reqs:
        if r["req"] in seen:
            continue
        seen.add(r["req"])
        out.append(r)
    return out


def d_describe(ctx: wb.Ctx) -> dict:
    reqs = requirements(ctx)
    if not reqs:
        raise wb.StepFailed("No requirements: pick an approved BRD (BRD & requirements) or upload a list (CSV or Excel: id, requirement, acceptance criteria - "
                            "Given ... when ... then ..., one per line).")
    ctx.put("requirements", reqs)
    crit = sum(len([c for c in str(r["acceptance"]).splitlines() if c.strip()]) for r in reqs)
    bad = [r["req"] for r in reqs if any(c.strip() and not split_gwt(c) for c in str(r["acceptance"]).splitlines())]
    none = [r["req"] for r in reqs if not str(r["acceptance"]).strip()]
    src = (ctx.get("brd") or {}).get("title")
    return {"summary": f"{len(reqs)} requirement(s) with {crit} acceptance criteri{'on' if crit == 1 else 'a'}" + (f" from the BRD \"{src}\"" if src else "") +
                       (f"; {len(none)} without criteria ({', '.join(none[:4])})" if none else "") + (f"; {len(bad)} with a criterion that is not Given / When / Then" if bad else "") + ".",
            "counts": {"requirements": len(reqs), "criteria": crit},
            "items": [f"{r}: no acceptance criteria - a person writes its tests" for r in none[:6]],
            "data": {"columns": ["Requirement", "Title", "Priority", "Acceptance criteria", "From"],
                     "rows": [[r["req"], r["title"], r["priority"], r["acceptance"], r["from"]] for r in reqs]}}


def d_shape(ctx: wb.Ctx) -> dict:
    have = ctx.records(ctx.step_id)
    reqs = ctx.get("requirements") or []
    if have:
        cases = have
    else:
        cases = [c for r in reqs for c in cases_for(r)]
    for c in cases:
        c["problem"] = "; ".join(case_problems(c, {r["req"] for r in reqs}))
    kinds = {k: sum(1 for c in cases if c.get("type") == k) for k, _ in TYPES}
    uncovered = [r["req"] for r in reqs if not any(c.get("req") == r["req"] for c in cases)]
    return {"summary": f"{len(cases)} test case(s) drafted by the rules from the acceptance criteria: {kinds['positive']} positive, {kinds['boundary']} boundary, "
                       f"{kinds['negative']} negative" + (f"; {len(uncovered)} requirement(s) without a case - add them ({', '.join(uncovered[:4])})" if uncovered else "") + ".",
            "records": cases, "counts": {"cases": len(cases), "uncovered": len(uncovered)},
            "items": [f"{r}: no test case yet" for r in uncovered[:6]],
            "data": _cases_table(cases)}


def _cases_table(cases: list[dict]) -> dict:
    return {"columns": ["Case", "Requirement", "Type", "Preconditions", "Steps", "Expected result", "Test data"],
            "rows": [[c.get("id"), c.get("req"), c.get("type"), c.get("preconditions") or "", c.get("steps") or "", c.get("expected") or "", c.get("data") or ""] for c in cases]}


def _validate_cases(recs: list[dict], ctx: wb.Ctx) -> list[str]:
    reqs = {r["req"] for r in ctx.get("requirements") or []}
    out, seen = [], set()
    for c in recs:
        c.setdefault("origin", "person")
        c.setdefault("type", "positive")
        if c.get("id") in seen:
            out.append(f"{c['id']}: the id is used twice")
        seen.add(c.get("id"))
        p = case_problems(c, reqs or None)
        c["problem"] = "; ".join(p)
        out += p
    return out


CASE_COLUMNS = [wb.Column("id", "Case"), wb.Column("req", "Requirement"), wb.Column("type", "Type", "select", options=TYPES),
                wb.Column("preconditions", "Preconditions", "longtext"), wb.Column("steps", "Steps", "longtext", help="one step per line"),
                wb.Column("expected", "Expected result", "longtext"), wb.Column("data", "Test data", "longtext"), wb.Column("problem", "Problems", readonly=True)]
CASE_EDIT = wb.Edit(columns=CASE_COLUMNS, validate=_validate_cases, label="test case")


def scripts_of(reqs: list[dict], cases: list[dict]) -> list[dict]:
    """A UAT script per requirement: its cases in order, with the synthetic data each one needs."""
    out = []
    for r in reqs:
        cs = [c for c in cases if c.get("req") == r["req"]]
        if cs:
            out.append({"script": f"UAT-{r['req']}", "req": r["req"], "title": r.get("title") or r["req"], "cases": cs})
    return out


def _csv(columns: list[str], rows: list[list]) -> str:
    buf = io.StringIO()
    wr = csv.writer(buf, lineterminator="\n")
    wr.writerow(columns)
    wr.writerows(rows)
    return buf.getvalue()


def _steps(c: dict) -> list[str]:
    return [re.sub(r"^\d+\.\s*", "", s).strip() for s in str(c.get("steps") or "").splitlines() if s.strip()] or [""]


def import_files(cases: list[dict], brd_keys: dict | None = None) -> dict:
    """The import formats of the three test managers (one row per step where the tool wants it)."""
    keys = brd_keys or {}
    xr, ze, tr = [], [], []
    for c in cases:
        ref = keys.get(c.get("req")) or c.get("req") or ""
        st = _steps(c)
        for k, s in enumerate(st):
            xr.append([c["id"] if k == 0 else "", c.get("title") if k == 0 else "", "Manual" if k == 0 else "", s, c.get("data") if k == 0 else "",
                       c.get("expected") if k == len(st) - 1 else "", ref if k == 0 else ""])
            ze.append([c.get("title") if k == 0 else "", c.get("preconditions") if k == 0 else "", s, c.get("data") if k == 0 else "",
                       c.get("expected") if k == len(st) - 1 else "", ref if k == 0 else "", c["id"] if k == 0 else ""])
        tr.append([c.get("title"), c.get("req"), {"boundary": "Functional", "negative": "Functional", "regression": "Regression"}.get(c.get("type"), "Acceptance"),
                   {"must": "Critical", "should": "High", "could": "Medium"}.get(c.get("priority"), "Medium"), c.get("preconditions") or "", "\n".join(st), c.get("expected") or "", ref])
    return {"xray-import.csv": _csv(["Test ID", "Test Summary", "Test Type", "Action", "Data", "Expected Result", "Requirement"], xr),
            "zephyr-import.csv": _csv(["Name", "Precondition", "Test Script (Step-by-Step) - Step", "Test Script (Step-by-Step) - Test Data",
                                       "Test Script (Step-by-Step) - Expected Result", "Coverage (Issues)", "Key"], ze),
            "testrail-import.csv": _csv(["Title", "Section", "Type", "Priority", "Preconditions", "Steps", "Expected Result", "References"], tr)}


def _xlsx(reqs: list[dict], cases: list[dict]) -> bytes:
    import openpyxl
    from openpyxl.styles import Font
    book = openpyxl.Workbook()
    ws = book.active
    ws.title = "Test cases"
    t = _cases_table(cases)
    ws.append(t["columns"])
    for r in t["rows"]:
        ws.append(r)
    ws2 = book.create_sheet("Traceability")
    ws2.append(["Requirement", "Title", "Cases"])
    for r in reqs:
        ws2.append([r["req"], r.get("title") or "", ", ".join(c["id"] for c in cases if c.get("req") == r["req"])])
    for sh in (ws, ws2):
        for c in sh[1]:
            c.font = Font(bold=True)
    buf = io.BytesIO()
    book.save(buf)
    return buf.getvalue()


def _brd_keys(ctx: wb.Ctx) -> dict:
    """The Jira / Azure Boards keys of the BRD's stories, so the import files point at the issues the tests cover."""
    did = (ctx.get("brd") or {}).get("id")
    if not did:
        return {}
    from . import brd
    d = brd.document(did) or {}
    return {s.get("req"): s.get("key") for s in d.get("stories") or [] if s.get("key")}


def write_outputs(ctx: wb.Ctx, reqs: list[dict], cases: list[dict], tag: str) -> list[dict]:
    files = import_files(cases, _brd_keys(ctx))
    ctx.output(f"test-plan-{tag}.xlsx", _xlsx(reqs, cases), label=f"Test plan {tag} (Excel: cases and traceability)")
    for name, text in files.items():
        ctx.output(name.replace(".csv", f"-{tag}.csv"), text, label={"xray": "Jira Xray import", "zephyr": "Zephyr Scale import", "testrail": "TestRail import"}[name.split("-")[0]] + f" ({tag})")
    scr = scripts_of(reqs, cases)
    secs = [{"title": f"{s['script']}: {s['title']}", "blocks": [_w4.table(["Case", "Type", "Preconditions", "Steps", "Expected result", "Test data"],
                                                                         [[c["id"], c["type"], c.get("preconditions") or "", c.get("steps") or "", c.get("expected") or "", c.get("data") or ""] for c in s["cases"]],
                                                                         f"record:testplan-{tag}#{s['script']}", f"Requirement {s['req']}")]} for s in scr]
    secs.append({"title": "Sign-off", "blocks": [_w4.para("Each script is run by a business user on the synthetic data shown; the plan is signed off by the named approver in Relay.", f"record:testplan-{tag}#plan")]})
    rec = {"plan": {"requirements": len(reqs), "cases": len(cases)}, **{s["script"]: s for s in scr}}
    info = _w4.build_doc(ctx, f"uat-scripts-{tag}", f"UAT scripts: {ctx.title}", f"{len(scr)} script(s), {len(cases)} test case(s)", secs, {f"testplan-{tag}": rec},
                         label=f"UAT scripts {tag}", audience="the business users who run and sign off the tests")
    ctx.put("doc_problems", _w4.doc_problems(info))
    return [{"title": f"test-plan-{tag}.xlsx", "detail": f"{len(cases)} cases, traceability to {len(reqs)} requirements"},
            {"title": f"uat-scripts-{tag}.docx", "detail": f"{len(scr)} UAT script(s) in your template, with an HTML preview"},
            *[{"title": n.replace(".csv", f"-{tag}.csv"), "detail": "import file - a person loads it into the tool"} for n in files]]


def d_build(ctx: wb.Ctx) -> dict:
    reqs = ctx.get("requirements") or []
    cases = ctx.records("shape")
    n = int(ctx.get("build_n") or 0) + 1
    ctx.put("build_n", n)
    items = write_outputs(ctx, reqs, cases, f"draft{n}")
    dp = ctx.get("doc_problems") or []
    return {"summary": f"{len(scripts_of(reqs, cases))} UAT script(s) built with their synthetic test data, the test plan and import files for Xray, Zephyr Scale and TestRail"
                       + (f"; the document check found: {dp[0]}" if dp else "") + ".",
            "counts": {"scripts": len(scripts_of(reqs, cases)), "cases": len(cases)}, "data": {"items": items}}


def coverage_checks(ctx: wb.Ctx, reqs: list[dict], cases: list[dict]) -> list[dict]:
    live = [c for c in cases if c.get("decision") not in ("retire", "merge")]
    ids = {r["req"] for r in reqs}
    no_case = [r["req"] for r in reqs if not any(c.get("req") == r["req"] for c in live)]
    crit_missing = []
    for r in reqs:
        for i, c in enumerate([x for x in str(r.get("acceptance") or "").splitlines() if x.strip()], 1):
            if split_gwt(c) and not any(x.get("req") == r["req"] and (x.get("criterion") == i or _norm(x.get("criterion_text")) == _norm(c)) for x in live):
                if not any(x.get("req") == r["req"] and x.get("origin") == "person" for x in live):
                    crit_missing.append(f"{r['req']} criterion {i}")
    cant = [(c["id"], case_problems(c, None)) for c in live]
    cant = [(i, p) for i, p in cant if p]
    nodata = [c["id"] for c in live if c.get("type") == "boundary" and len(re.findall(r"\d", str(c.get("data") or ""))) == 0]
    fp: dict = {}
    for c in live:
        fp.setdefault(fingerprint(c), []).append(c["id"])
    dups = [v for v in fp.values() if len(v) > 1]
    rows = [{"name": "coverage", "label": "Every requirement has at least one test case", "status": "fail" if no_case else "pass",
             "measured": f"{len(reqs) - len(no_case)} of {len(reqs)}", "expected": "every requirement", "detail": ", ".join(no_case) or "all covered",
             "evidence": ctx.evidence("Traceability: requirement -> cases", {"rows": [{"requirement": r["req"], "cases": ", ".join(c["id"] for c in live if c.get("req") == r["req"]) or "none"} for r in reqs]}, kind="proof", ok=not no_case)},
            {"name": "criteria", "label": "Every Given / When / Then criterion has its case", "status": "warn" if crit_missing else "pass",
             "measured": f"{len(crit_missing)} without a case", "expected": "none", "detail": ", ".join(crit_missing[:6]) or "every criterion"},
            ctx.proof("references_real", label="Every case points at a real requirement", refs=sorted({c.get("req") or "" for c in live}), known=sorted(ids)),
            {"name": "runnable", "label": "Every case can run: steps, an expected result and its data", "status": "fail" if cant or nodata else "pass",
             "measured": f"{len(live) - len(cant) - len(nodata)} of {len(live)}", "expected": "every case",
             "detail": "; ".join([f"{i}: {p[0]}" for i, p in cant[:3]] + [f"{i}: a boundary case without its values" for i in nodata[:3]]) or "every case has steps, an expected result and test data"},
            {"name": "duplicates", "label": "No two cases test the same thing", "status": "warn" if dups else "pass", "measured": f"{len(dups)} group(s)", "expected": "none",
             "detail": "; ".join(" = ".join(g) for g in dups[:4]) or "no duplicates"}]
    return rows


def d_prove(ctx: wb.Ctx) -> dict:
    reqs = ctx.get("requirements") or []
    cases = ctx.records("shape")
    checks = coverage_checks(ctx, reqs, cases)
    bad = [c for c in checks if c["status"] == "fail"]
    return {"summary": f"{len(cases)} case(s) over {len(reqs)} requirement(s): " + ("ready for sign-off." if not bad else f"{len(bad)} check(s) fail - {bad[0]['label'].lower()}."),
            "data": {"checks": checks}, "counts": {"cases": len(cases), "failing": len(bad)}, "ok": not bad}


def d_ship(ctx: wb.Ctx) -> dict:
    reqs = ctx.get("requirements") or []
    cases = ctx.records("shape")
    return {"summary": f"Sign off the test plan: {len(scripts_of(reqs, cases))} UAT script(s), {len(cases)} case(s) - the business approver confirms they test what was asked.",
            "data": {"items": [{"title": s["script"], "detail": f"{s['title']} - {len(s['cases'])} case(s)"} for s in scripts_of(reqs, cases)[:12]]}}


def _lineage(ctx: wb.Ctx, p: dict) -> int:
    from .. import lineage
    did = p.get("brd_id")
    plan_node = ctx.lineage_node("document", SYSTEM, p["id"], label=f"Test plan: {p['name']} (v{p['version']})")
    n = 0
    for c in p["cases"]:
        tn = ctx.lineage_node("test", f"{SYSTEM} {p['id']}", c["id"], label=f"{c['id']}: {str(c.get('title') or '')[:70]}", properties={"type": c.get("type")})
        ctx.lineage_edge(plan_node, tn, "contains")
        if did:
            rn = lineage.node_id("requirement", f"{BRD_SYSTEM} {did}", c.get("req"))
            if not db.one("SELECT 1 FROM lineage_nodes WHERE id = ?", (rn,)):
                rn = ctx.lineage_node("requirement", f"{BRD_SYSTEM} {did}", c.get("req"), label=c.get("req"), own=False)
        else:
            rn = ctx.lineage_node("requirement", SYSTEM, f"{p['id']}:{c.get('req')}", label=c.get("req"))
        ctx.lineage_edge(rn, tn, "relates", {"tested_by": c["id"]})
        n += 1
    return n


def d_run(ctx: wb.Ctx, cases: list[dict] | None = None, note: str = "") -> dict:
    reqs = ctx.get("requirements") or []
    cases = [c for c in (cases if cases is not None else ctx.records("shape")) if c.get("decision") not in ("retire", "merge")]
    probs = [x for c in cases for x in case_problems(c, {r["req"] for r in reqs} or None)]
    if probs:
        raise wb.StepFailed("The plan cannot be published: " + "; ".join(probs[:4]))
    p = publish(ctx, reqs, cases, ctx.get("plan") or ctx.scope.get("plan"), note=note or f"published from {ctx.id}")
    ctx.put("plan", p["id"])
    v = p["version"]
    items = write_outputs(ctx, reqs, cases, f"v{v}")
    links = _lineage(ctx, p)
    notes = push_cases(ctx, p, cases)
    out = {"summary": f"Version {v} of the test plan is published: {len(cases)} case(s), the UAT scripts and the import files; {links} requirement -> test link(s) in the lineage graph"
                      + (" (BRD & requirements' Trace shows them)" if p.get("brd_id") else "") + "." + (" " + "; ".join(notes) + "." if notes else ""),
           "counts": {"version": v, "cases": len(cases)}, "data": {"items": items}}
    ctx.put(f"out_{ctx.step_id}", out)
    return out


# ------------------------------------------------------------------ Change (a published plan against new requirements)

def c_request(ctx: wb.Ctx) -> dict:
    p = plan(ctx.scope.get("plan") or "", db.user(ctx.owner or "") or {})
    if not p:
        raise wb.StepFailed("The test plan this work item changes is not one its owner can see any more.")
    ctx.put("plan", p["id"])
    ctx.put("current", p["cases"])
    ctx.put("before", p["requirements"])
    if p.get("brd_id") and not ctx.scope.get("brd"):
        ctx.scope["brd"] = p["brd_id"]
    reqs = requirements(ctx) or p["requirements"]
    ctx.put("requirements", reqs)
    src = ctx.get("brd") or {}
    return {"summary": f"Change to \"{p['name']}\" version {p['version']} ({len(p['cases'])} cases) against " +
                       (f"the BRD \"{src.get('title')}\" version {src.get('version')} (the plan was built on version {p.get('brd_version')})" if src else "the uploaded requirements") + ".",
            "data": {"text": ctx.brief or "(no request text)"}, "counts": {"cases": len(p["cases"])}}


def _crit(r: dict) -> list[str]:
    return [_norm(c) for c in str(r.get("acceptance") or "").splitlines() if c.strip()]


def impact(before: list[dict], after: list[dict], cases: list[dict]) -> dict:
    b, a = {r["req"]: r for r in before}, {r["req"]: r for r in after}
    added = [k for k in a if k not in b]
    removed = [k for k in b if k not in a]
    changed = [k for k in a if k in b and _crit(a[k]) != _crit(b[k])]
    touched = [c for c in cases if c.get("req") in set(removed) | set(changed)]
    return {"added": added, "removed": removed, "changed": changed, "touched": touched}


def c_diagnose(ctx: wb.Ctx) -> dict:
    im = impact(ctx.get("before") or [], ctx.get("requirements") or [], ctx.get("current") or [])
    ctx.put("impact", {k: v if k != "touched" else [c["id"] for c in v] for k, v in im.items()})
    checks = [{"name": "added", "label": "Requirements added", "status": "warn" if im["added"] else "pass", "measured": len(im["added"]), "detail": ", ".join(im["added"]) or "none"},
              {"name": "changed", "label": "Requirements whose criteria changed", "status": "warn" if im["changed"] else "pass", "measured": len(im["changed"]), "detail": ", ".join(im["changed"]) or "none"},
              {"name": "removed", "label": "Requirements removed", "status": "warn" if im["removed"] else "pass", "measured": len(im["removed"]), "detail": ", ".join(im["removed"]) or "none"},
              {"name": "touched", "label": "Test cases touched", "status": "warn" if im["touched"] else "pass", "measured": len(im["touched"]),
               "detail": ", ".join(c["id"] for c in im["touched"][:8]) or "none",
               "evidence": ctx.evidence("What the change touches", {"rows": [{"case": c["id"], "requirement": c.get("req"),
                                                                             "why": "requirement removed" if c.get("req") in im["removed"] else "criteria changed"} for c in im["touched"]]}, kind="proof", ok=True)}]
    return {"summary": f"{len(im['added'])} requirement(s) added, {len(im['changed'])} changed, {len(im['removed'])} removed - {len(im['touched'])} test case(s) touched.",
            "data": {"checks": checks}, "counts": {"touched": len(im["touched"])}, "items": [f"{c['id']} ({c.get('req')})" for c in im["touched"][:6]]}


def c_fix(ctx: wb.Ctx) -> dict:
    have = ctx.records(ctx.step_id)
    if have:
        recs = have
    else:
        im = ctx.get("impact") or {}
        reqs = {r["req"]: r for r in ctx.get("requirements") or []}
        recs = []
        for c in ctx.get("current") or []:
            r = dict(c)
            if c.get("req") in im.get("removed", []):
                r["decision"], r["why"] = "retire", "its requirement was removed"
            elif c.get("req") in im.get("changed", []) and c.get("origin") != "person":
                r["decision"], r["why"] = "retire", "its criterion changed: replaced by the new case below"
            else:
                r["decision"], r["why"] = "keep", ""
            recs.append(r)
        for k in im.get("added", []) + im.get("changed", []):
            for n in cases_for(reqs[k]):
                if not any(x["id"] == n["id"] and x["decision"] == "keep" for x in recs):
                    nid = n["id"] if not any(x["id"] == n["id"] for x in recs) else n["id"] + "-v2"
                    recs.append({**n, "id": nid, "decision": "keep", "why": "new: from the " + ("new" if k in im.get("added", []) else "changed") + " criterion"})
    for r in recs:
        r["problem"] = "; ".join(case_problems(r, {x["req"] for x in ctx.get("requirements") or []}, retire_ok=True))
    return {"summary": f"{sum(1 for r in recs if r.get('why', '').startswith('new'))} new case(s) suggested, {sum(1 for r in recs if r.get('decision') == 'retire')} to retire - "
                       "correct them in place; a case that cannot run cannot be confirmed.",
            "records": recs, "counts": {"cases": len(recs)}, "data": {"columns": ["Case", "Requirement", "Decision", "Why", "Expected result"],
                                                                      "rows": [[r["id"], r.get("req"), r.get("decision"), r.get("why") or "", r.get("expected") or ""] for r in recs]}}


def _validate_fix(recs: list[dict], ctx: wb.Ctx) -> list[str]:
    reqs = {r["req"] for r in ctx.get("requirements") or []}
    out = []
    for r in recs:
        r.setdefault("decision", "keep")
        r.setdefault("type", "positive")
        if r["decision"] not in dict(DECISIONS):
            out.append(f"{r.get('id')}: keep, merge or retire")
        p = case_problems(r, reqs, retire_ok=True)
        if r["decision"] == "keep" and r.get("req") not in reqs:
            p = [x for x in p if "is not one of" not in x] + [f"{r.get('id')}: its requirement {r.get('req')} is gone - retire it"]
        r["problem"] = "; ".join(p)
        out += p
    return out


FIX_EDIT = wb.Edit(columns=[wb.Column("decision", "Decision", "select", options=DECISIONS), *CASE_COLUMNS[:7], wb.Column("why", "Why", readonly=True),
                            wb.Column("problem", "Problems", readonly=True)], validate=_validate_fix, label="test case")


def c_prove(ctx: wb.Ctx) -> dict:
    recs = ctx.records("fix")
    reqs = ctx.get("requirements") or []
    checks = coverage_checks(ctx, reqs, recs)
    before = {c["id"]: c for c in ctx.get("current") or []}
    changed = [r for r in recs if r["id"] not in before or r.get("decision") != "keep" or fingerprint(r) != fingerprint(before[r["id"]])]
    checks.append({"name": "diff", "label": "What changes in the plan", "status": "pass" if changed else "warn", "measured": len(changed),
                   "detail": ", ".join(f"{r['id']} ({'new' if r['id'] not in before else r.get('decision')})" for r in changed[:8]) or "nothing"})
    bad = [c for c in checks if c["status"] == "fail"]
    return {"summary": f"{len(changed)} case(s) change; " + ("every requirement is still covered." if not bad else f"{bad[0]['label'].lower()}: {bad[0]['detail']}."),
            "data": {"checks": checks}, "counts": {"changed": len(changed)}, "ok": not bad}


def c_approve(ctx: wb.Ctx) -> dict:
    recs = ctx.records("fix")
    return {"summary": f"Release the next version of the test plan: {sum(1 for r in recs if r.get('decision') == 'keep')} case(s) kept or new, "
                       f"{sum(1 for r in recs if r.get('decision') == 'retire')} retired.",
            "data": {"items": [{"title": r["id"], "detail": f"{r.get('decision')}: {r.get('why') or r.get('expected') or ''}"[:160]} for r in recs if r.get("why")][:12]}}


def c_learn(ctx: wb.Ctx) -> dict:
    return d_run(ctx, ctx.records("fix"), note=(ctx.brief or "")[:300])


# ------------------------------------------------------------------ Migrate (test cases from another tool)

def m_discover(ctx: wb.Ctx) -> dict:
    up = classify(ctx)
    if not up["cases"]:
        raise wb.StepFailed("Upload the test cases to migrate: an export from TestRail, Zephyr Scale or Xray (CSV), or an Excel sheet with title, steps and expected result.")
    cases = []
    for name, tool, rows in up["cases"]:
        cur = None
        for i, r in enumerate(rows, 2):
            title = _col(r, *CASE_TITLE)
            step_txt, exp = _col(r, *CASE_STEPS), _col(r, *CASE_EXP)
            if not title and cur:                                             # a continuation row: one more step of the same case (Xray, Zephyr)
                cur["steps"] += ("\n" if cur["steps"] and step_txt else "") + step_txt
                cur["expected"] = exp or cur["expected"]
                continue
            if not title:
                continue
            cur = {"id": _col(r, "id", "test id", "key", "case id") or f"MIG-{len(cases) + 1:03d}", "title": title[:200], "steps": step_txt, "expected": exp,
                   "preconditions": _col(r, "preconditions", "precondition", "prerequisites"), "data": _col(r, "data", "test data", "test script (step-by-step) - test data"),
                   "req": _col(r, *CASE_REF), "priority": (_col(r, "priority") or "should").lower(), "type": "regression" if "regress" in _col(r, "type", "test type").lower() else "positive",
                   "section": _col(r, "section", "folder", "component"), "file": name, "tool": tool, "row": i}
            cases.append(cur)
    for c in cases:
        c["fingerprint"] = fingerprint(c)
    ctx.put("source_cases", cases)
    tools = sorted({c["tool"] for c in cases})
    return {"summary": f"{len(cases)} test case(s) from {len(up['cases'])} export(s) ({', '.join(tools)}) - read-only copies.",
            "counts": {"cases": len(cases)}, "data": {"columns": ["Case", "Title", "Steps", "Expected result", "References", "From"],
                                                      "rows": [[c["id"], c["title"], c["steps"], c["expected"], c["req"], f"{c['file']} row {c['row']} ({c['tool']})"] for c in cases]}}


def m_decide(ctx: wb.Ctx) -> dict:
    have = {r["id"]: r for r in ctx.records(ctx.step_id)}
    cases = ctx.get("source_cases") or []
    first: dict = {}
    recs = []
    for c in cases:
        fp = c["fingerprint"]
        if not str(c.get("steps") or "").strip() and not str(c.get("expected") or "").strip():
            d, why, into = "retire", "no steps and no expected result", ""
        elif fp in first:
            d, why, into = "merge", f"the same steps and expected result as {first[fp]}", first[fp]
        else:
            first[fp] = c["id"]
            d, why, into = "keep", "", ""
        rec = {**c, "decision": d, "why": why, "into": into}
        if c["id"] in have:
            rec.update({k: have[c["id"]][k] for k in ("decision", "into") if k in have[c["id"]]})
        recs.append(rec)
    return {"summary": f"{sum(1 for r in recs if r['decision'] == 'keep')} to keep, {sum(1 for r in recs if r['decision'] == 'merge')} duplicate(s) to merge, "
                       f"{sum(1 for r in recs if r['decision'] == 'retire')} to retire - decide each, with reasons.",
            "records": recs, "counts": {"keep": sum(1 for r in recs if r["decision"] == "keep")},
            "data": {"columns": ["Case", "Title", "Decision", "Into", "Why"], "rows": [[r["id"], r["title"], r["decision"], r["into"], r["why"]] for r in recs]}}


def _validate_decide(recs: list[dict], ctx: wb.Ctx) -> list[str]:
    keep = {r["id"] for r in recs if r.get("decision") == "keep"}
    out = []
    for r in recs:
        if r.get("decision") not in dict(DECISIONS):
            out.append(f"{r.get('id')}: keep, merge or retire")
        elif r["decision"] == "merge" and r.get("into") not in keep:
            out.append(f"{r.get('id')}: merge into a case you keep (not {r.get('into') or 'nothing'})")
        elif r["decision"] == "keep":
            out += case_problems(r, None)
    return out


DECIDE_EDIT = wb.Edit(columns=[wb.Column("decision", "Decision", "select", options=DECISIONS), wb.Column("into", "Merge into"), wb.Column("title", "Title", readonly=True),
                               wb.Column("why", "Why", readonly=True)], add=False, remove=False, validate=_validate_decide, label="test case")


def m_convert(ctx: wb.Ctx) -> dict:
    kept = [r for r in ctx.records("decide") if r.get("decision") == "keep"]
    merged = {r["into"]: [] for r in ctx.records("decide") if r.get("decision") == "merge"}
    for r in ctx.records("decide"):
        if r.get("decision") == "merge":
            merged[r["into"]].append(r)
    out = []
    for r in kept:
        refs = sorted({x for x in [r.get("req")] + [m.get("req") for m in merged.get(r["id"], [])] if x})
        out.append({**{k: r.get(k) for k in ("id", "title", "preconditions", "steps", "expected", "data", "priority", "type")}, "req": ", ".join(refs),
                    "merged": ", ".join(m["id"] for m in merged.get(r["id"], []))})
    target = ctx.scope.get("target") or "xray"
    files = import_files(out)
    if target == "excel":
        ctx.output("test-cases.xlsx", _xlsx([{"req": x, "title": ""} for x in sorted({r["req"] for r in out if r["req"]})], out), label="Test cases (Excel)")
    else:
        ctx.output(f"{target}-import.csv", files[f"{target}-import.csv"], label=f"{dict(TARGETS)[target]} - import file")
    ctx.put("converted", out)
    return {"summary": f"{len(out)} case(s) converted to {dict(TARGETS)[target]}" + (f", {sum(1 for r in out if r['merged'])} with duplicates merged in" if any(r["merged"] for r in out) else "") + ".",
            "counts": {"converted": len(out)}, "data": _cases_table(out)}


def m_prove(ctx: wb.Ctx) -> dict:
    src = {c["id"]: c for c in ctx.get("source_cases") or []}
    dec = ctx.records("decide")
    conv = {c["id"]: c for c in ctx.get("converted") or []}
    kept = [r["id"] for r in dec if r.get("decision") == "keep"]
    lost = [k for k in kept if k not in conv]
    altered = [k for k in kept if k in conv and fingerprint(conv[k]) != src[k]["fingerprint"]]
    refs_lost = [k for k in kept if k in conv and src[k].get("req") and src[k]["req"] not in str(conv[k].get("req"))]
    checks = [{"name": "counts", "label": "Every case kept is converted", "status": "fail" if lost else "pass", "measured": f"{len(conv)} of {len(kept)}", "expected": f"{len(kept)}",
               "detail": ", ".join(lost) or f"{len(src)} found = {len(kept)} kept + {sum(1 for r in dec if r.get('decision') == 'merge')} merged + {sum(1 for r in dec if r.get('decision') == 'retire')} retired"},
              {"name": "content", "label": "Steps and expected results unchanged", "status": "fail" if altered else "pass", "measured": f"{len(kept) - len(altered)} of {len(kept)}",
               "expected": "every kept case", "detail": ", ".join(altered) or "the same fingerprint before and after",
               "evidence": ctx.evidence("Old and new side by side", {"rows": [{"case": k, "before": f"{src[k]['steps']} {src[k]['expected']}", "after": f"{conv[k]['steps']} {conv[k]['expected']}" if k in conv else "missing"}
                                                                              for k in kept]}, kind="proof", ok=not altered and not lost)},
              {"name": "references", "label": "References to requirements kept", "status": "fail" if refs_lost else "pass", "measured": f"{len(refs_lost)} lost", "expected": "none",
               "detail": ", ".join(refs_lost) or "every reference kept (merged cases add theirs)"}]
    bad = [c for c in checks if c["status"] == "fail"]
    return {"summary": "Old and new side by side: " + ("every kept case converted, unchanged, with its references." if not bad else f"{bad[0]['label'].lower()} fails - {bad[0]['detail']}."),
            "data": {"checks": checks}, "ok": not bad, "counts": {"kept": len(kept)}}


def m_handover(ctx: wb.Ctx) -> dict:
    return {"summary": "Hand over: the owner signs off the migrated cases and the import file before anyone loads it.",
            "data": {"items": [{"title": f"{len(ctx.get('converted') or [])} case(s)", "detail": f"to {dict(TARGETS)[ctx.scope.get('target') or 'xray']}"}]}}


def m_run(ctx: wb.Ctx) -> dict:
    conv = ctx.get("converted") or []
    refs = sorted({x.strip() for c in conv for x in str(c.get("req") or "").split(",") if x.strip()})
    reqs = [{"req": r, "title": "", "acceptance": "", "priority": "should"} for r in refs] + ([{"req": "(none)", "title": "cases without a reference", "acceptance": "", "priority": "should"}]
                                                                                            if any(not c.get("req") for c in conv) else [])
    cases = [{**c, "req": (str(c.get("req") or "").split(",")[0].strip() or "(none)")} for c in conv]
    ctx.put("requirements", reqs)
    return d_run(ctx, cases, note="migrated")


# ------------------------------------------------------------------ test managers: the cases written after an approval, read back

db.register_schema("""
CREATE TABLE IF NOT EXISTS testdocs_tm (
  plan_id TEXT NOT NULL, connection TEXT NOT NULL, case_id TEXT NOT NULL, fingerprint TEXT, tool_key TEXT, written REAL,
  PRIMARY KEY (plan_id, connection, case_id));
""")


class TMPlatform(wb.Platform):
    def __init__(self, pid: str, label: str, kinds: tuple, simulator: str):
        self.id, self.label, self.kinds, self.simulator = pid, label, kinds, simulator
        self.reads = "the project's test cases, read-only; the plan's new cases are written only after a named person approves them, then read back"


TMS = {"xray": TMPlatform("xray", "Jira Xray (Cloud)", ("xray_cloud",), "tests/mocklab/sims/process.py: xray (GraphQL, the test importer)"),
       "zephyr": TMPlatform("zephyr", "Zephyr Scale (Cloud)", ("zephyr_scale",), "tests/mocklab/sims/process.py: zephyr (API v2: test cases and steps)"),
       "testrail": TMPlatform("testrail", "TestRail", ("testrail",), "tests/mocklab/sims/process.py: testrail (API v2: sections and cases)")}


def _tm(ctx: wb.Ctx) -> list[dict]:
    return [c for c in ctx.connections() if c["kind"] in tmg.KINDS]


def _case_payload(c: dict, keys: dict) -> dict:
    return {"ref": c["id"], "title": str(c.get("title") or c["id"]), "req": keys.get(c.get("req")) or c.get("req") or "", "type": c.get("type"), "priority": c.get("priority"),
            "preconditions": c.get("preconditions") or "", "steps": [s for s in _steps(c) if s] or [str(c.get("title") or "")], "data": c.get("data") or "", "expected": c.get("expected") or ""}


def push_cases(ctx: wb.Ctx, p: dict, cases: list[dict]) -> list[str]:
    """Ask to write the plan's cases the tool does not hold yet; a case that changed since it was written is listed for
    a person (Relay adds cases, it does not rewrite one a tester may have worked on)."""
    from .. import connectors
    notes = []
    keys = _brd_keys(ctx)
    for c in _tm(ctx):
        if not connectors.may_write(c):
            raise wb.StepFailed(f"{c['name']} is read-only: change its scope to \"Read & write - with approval\" to write the cases, or remove it from the work item to use the import files.")
        have = {r["case_id"]: r for r in db.q("SELECT * FROM testdocs_tm WHERE plan_id = ? AND connection = ?", (p["id"], c["id"]))}
        new = [x for x in cases if x["id"] not in have]
        changed = [x["id"] for x in cases if x["id"] in have and have[x["id"]]["fingerprint"] != fingerprint(x)]
        if new:
            _w4.request_push(ctx, c["id"], "cases", {"plan": f"{p['name']} v{p['version']}", "plan_id": p["id"], "cases": [_case_payload(x, keys) for x in new]},
                             f"Write {len(new)} test case(s) of \"{p['name']}\" (version {p['version']}) to {c['name']}",
                             items=[f"Where: {c['name']} ({tmg.ADAPTERS[c['kind']].label})"] + [f"{x['id']}: {str(x.get('title') or '')[:80]}" for x in new[:20]]
                             + ([f"... and {len(new) - 20} more"] if len(new) > 20 else []))
            notes.append(f"{len(new)} new case(s) wait for their write approval to {c['name']}")
        else:
            notes.append(f"{c['name']} already holds every case")
        if changed:
            notes.append(f"changed since written to {c['name']} - update by hand there: {', '.join(changed[:8])}")
    return notes


def tm_view(ctx: wb.Ctx) -> dict:
    """The Run (or Learn) step redrawn when a write lands: the keys recorded and the cases read back from the tool."""
    base = dict(ctx.get(f"out_{ctx.step_id}") or {"summary": "", "data": {"items": []}})
    pid = ctx.get("plan")
    p = plan(pid) if pid else None
    cases = {c["id"]: c for c in (p or {}).get("cases") or []}
    done = set(ctx.get("tm_reconciled") or [])
    checks = list(ctx.get("tm_checks") or [])
    lines = []
    for x in _w4.latest_pushes(ctx.id, ctx.step_id):
        if x["target"] not in tmg.KINDS:
            continue
        if x["status"] == "awaiting":
            lines.append(f"waiting for the write approval: {x['what']}")
            continue
        if x["status"] == "failed":
            lines.append(f"not written ({str(x['result'].get('error') or '')[:160]}) - run the step again")
            continue
        res = x["result"]
        if x["approval"] not in done:
            c = ctx.connection(x["connection"])
            created = res.get("created") or []
            now = time.time()
            for k in created:
                if k["ref"] in cases:
                    db.run("INSERT OR REPLACE INTO testdocs_tm (plan_id, connection, case_id, fingerprint, tool_key, written) VALUES (?, ?, ?, ?, ?, ?)",
                           (pid, c["id"], k["ref"], fingerprint(cases[k["ref"]]), k["key"], now))
            try:
                back = tmg.read_back(c, created, res)
            except Exception as e:  # noqa: BLE001 - the write stands; the read-back is reported
                back, err = {}, str(e)[:200]
            else:
                err = ""
            bad = []
            for k in created:
                want = cases.get(k["ref"]) or {}
                got = back.get(k["key"])
                n = len([s for s in _steps(want) if s]) or 1
                if not got or _norm(got.get("title"))[:200] != _norm(want.get("title") or k["ref"])[:200] or len(got.get("steps") or []) != n:
                    bad.append(f"{k['ref']} {k['key']}" + ("" if got else " (not found)"))
            checks.append({"name": f"tm-{x['approval'][-8:]}", "label": f"{c['name']}: every written case read back - title and steps", "status": "fail" if bad or err else "pass",
                           "measured": f"{len(created) - len(bad)} of {len(created)}", "expected": f"{len(created)}",
                           "detail": err or ("; ".join(bad[:5]) if bad else ", ".join(k["key"] for k in created[:12]) + (" ..." if len(created) > 12 else ""))
                                     + ("; refused: " + "; ".join(f"{e['ref']}: {e['error']}" for e in (res.get("errors") or [])[:3]) if res.get("errors") else "")})
            done.add(x["approval"])
        lines.append(f"written to {res.get('where')}: {len(res.get('created') or [])} case(s)" + (f", {len(res.get('errors') or [])} refused" if res.get("errors") else ""))
    ctx.put("tm_reconciled", sorted(done))
    ctx.put("tm_checks", checks)
    data = dict(base.get("data") or {})
    data["items"] = list(data.get("items") or []) + [{"title": "Test manager", "detail": ln} for ln in lines] + [{"title": g["label"], "detail": f"{g['status']}: {g['measured']} - {g['detail']}"} for g in checks]
    ok_ = [g for g in checks if g["status"] == "pass"]
    return {"summary": (base.get("summary") or "") + (" " + "; ".join(lines) + "." if lines else "")
                       + (f" Read back from the tool: {sum(int(str(g['measured']).split(' of ')[0]) for g in ok_)} case(s) match." if ok_ else ""),
            "counts": {**(base.get("counts") or {}), "in the test manager": sum(len((x["result"].get("created") or [])) for x in _w4.latest_pushes(ctx.id, ctx.step_id) if x["status"] == "written")},
            "data": data}


_w4.REFRESH["testdocs.run"] = tm_view
_w4.REFRESH["testdocs.learn"] = tm_view


# ------------------------------------------------------------------ the module page

def _cards(u: dict) -> list[dict]:
    rows = [[p["name"], f"v{p['version']}", len(p["requirements"]), len(p["cases"]), sum(1 for c in p["cases"] if c.get("type") == "boundary"),
             f"#/m/{MODULE}/i/{p['item']}" if p.get("item") else ""] for p in plans(u)]
    return [{"title": "Published test plans", "columns": ["Plan", "Version", "Requirements", "Cases", "Boundary cases", "Work item"], "rows": rows,
             "empty": "No test plan is published yet: a Develop item's Run step publishes one."}]


wb.register(wb.Pack(
    module=MODULE,
    guide="# Test plans & UAT scripts - the work item\n\nTest cases are drafted by rules from the Given / When / Then acceptance criteria; people correct, "
          "prove and sign them off. No agent step; nothing invented - a boundary value is the criterion's own number.",
    lineage="each test case on the requirement it tests (from the BRD when there is one), and the plan that contains it",
    platforms={"files": FILES, **TMS},
    schemas={"test case": CASE_COLUMNS},
    cards=_cards,
    work={
        "develop": wb.Work(title="From requirements to signed-off test cases and UAT scripts", needs_source=False, steps={
            "Describe": wb.Step(kind="deterministic", run=d_describe, agent="Requirements reader",
                                text="The requirements and their Given / When / Then criteria - from an approved BRD or your list"),
            "Shape": wb.Step(kind="deterministic", run=d_shape, agent="Test designer", edit=CASE_EDIT, confirm="the test cases - preconditions, steps, expected result and test data",
                             text="A test case per criterion, a boundary case at each limit it names and a negative case for what must not happen - drafted by rules, corrected by you"),
            "Build": wb.Step(kind="deterministic", run=d_build, view="plan", agent="Script writer",
                             text="UAT scripts with synthetic test data, the test plan (Excel), the UAT scripts (Word) and import files for Xray, Zephyr Scale and TestRail"),
            "Prove": wb.Step(kind="proof", run=d_prove, view="gates", agent="Coverage checker", back_to="shape",
                             text="Every requirement and criterion covered, every case runnable and pointing at a real requirement, no duplicates"),
            "Ship": wb.Step(kind="person", run=d_ship, view="plan", approver=True, back_to="shape", text="The business approver signs off the test plan and the UAT scripts"),
            "Run": wb.Step(kind="deterministic", run=d_run, view="plan", agent="Publisher",
                           text="The plan is published (versions kept) and each requirement is linked to its tests - BRD & requirements' Trace shows them")},
            fields=[wb.Field("brd", "Approved BRD", "select", options=_brd_options, help="A BRD approved in BRD & requirements - or upload a list of requirements.")]),
        "change": wb.Work(title="Keep a test plan in step with changed requirements", needs_source=False, steps={
            "Request": wb.Step(kind="deterministic", run=c_request, view="text", agent="Reader", text="The published plan and the newer requirements (the BRD's latest version, or an upload)"),
            "Diagnose": wb.Step(kind="proof", run=c_diagnose, view="gates", agent="Impact checker", confirm="what changed in the requirements and which cases it touches",
                                text="Requirements added, changed and removed, and the test cases they touch"),
            "Fix": wb.Step(kind="person", run=c_fix, edit=FIX_EDIT, text="New cases suggested for new and changed criteria, old ones marked to retire - you correct them"),
            "Prove": wb.Step(kind="proof", run=c_prove, view="gates", agent="Coverage checker", back_to="fix", text="Every requirement still covered, every case runnable, exactly what changes"),
            "Approve": wb.Step(kind="person", run=c_approve, view="plan", approver=True, text="The named approver releases the next version"),
            "Learn": wb.Step(kind="deterministic", run=c_learn, view="plan", agent="Publisher", text="The next version is published, with its scripts, import files and links")},
            fields=[wb.Field("plan", "Test plan to change", "select", options=plan_options, required=True),
                    wb.Field("brd", "Newer BRD (optional)", "select", options=_brd_options, help="Leave empty to use the plan's own BRD at its latest version, or upload a new list.")]),
        "migrate": wb.Work(title="Move test cases from one test manager to another, proven case for case", steps={
            "Discover": wb.Step(kind="platform", run=m_discover, agent="Reader", text="The test cases exported from TestRail, Zephyr Scale, Xray or Excel - read-only"),
            "Decide": wb.Step(kind="deterministic", run=m_decide, agent="Librarian", edit=DECIDE_EDIT, confirm="keep, merge or retire each case - duplicates and empty cases suggested",
                              text="Keep, merge or retire each case, with the reasons"),
            "Convert": wb.Step(kind="deterministic", run=m_convert, agent="Converter", text="The kept cases in the target tool's import format, duplicates merged in"),
            "Prove": wb.Step(kind="proof", run=m_prove, view="gates", agent="Checker", back_to="decide", text="Every kept case converted, steps and expected results unchanged, references kept"),
            "Hand over": wb.Step(kind="person", run=m_handover, view="plan", text="The owner signs off the migrated cases"),
            "Run": wb.Step(kind="deterministic", run=m_run, view="plan", agent="Publisher", text="Published as a test plan Relay keeps in step from now on")},
            fields=[wb.Field("target", "Target tool", "select", options=TARGETS, required=True, default="xray")]),
    }))
