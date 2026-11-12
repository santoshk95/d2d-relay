"""Excel & spreadsheet models (registry id `excel`) - from fragile workbooks to governed models: finance and planning
workbooks read, explained, fixed and rebuilt as governed SQL models with certified metrics - or kept, with checks.
Workbooks (.xlsx / .xlsm), their VBA modules (.bas) and Power Query M (.pq / .m) are uploaded; the mock lab's finance
workbooks stand in (tests/mocklab/fixtures/excel_models).

Assess   Connect -> Inventory -> Health -> Findings -> Estimate: every sheet, formula, name, link, macro and query; the
         workbook evaluated again by Relay's formula engine and compared with the numbers Excel cached; formula
         errors, numbers typed in place of an input, links to other workbooks, hidden sheets that feed nothing, tie-outs
         that do not tie out, macros writing to personal paths, queries reading local files.
Develop  Describe -> Shape -> Build -> Prove -> Ship -> Run: a governed model from a workbook - every sheet's column
         formulas translated to SQL by rules (lookups as joins, typed-in numbers as the inputs they mean), the agent
         drafting what no rule translates; built in DuckDB and proven against the workbook's own numbers; approved;
         the outputs become draft metrics in Formulas & metrics, where the four-eyes review certifies them.
Change   Request -> Diagnose -> Fix -> Prove -> Approve -> Learn: a workbook fixed - a #REF! rebuilt from its column's
         pattern, a typed-in rate replaced by its input, a link to another workbook replaced by the input it equals;
         each fix proven by evaluating the workbook again (no error left, no other number moves); approved; the fixed
         workbook handed back.
Migrate  Discover -> Decide -> Convert -> Prove -> Hand over -> Run: a set of workbooks moved out of Excel - rebuild,
         keep with checks, hand masters to Master data, retire - converted and proven like Develop.
Run      Watch -> Alert -> Fix -> Approve -> Report: each round the latest upload is read again: errors and tie-outs that do
         not tie out go to a ticket or a Change item after a person approves.
"""
from __future__ import annotations

import io
import json
import re
import time

from .. import db, registry, semantic
from .. import workbench as wb
from . import excel_rules as xr

MODULE = "excel"

db.register_schema("""
CREATE TABLE IF NOT EXISTS excel_fixes (
  id TEXT PRIMARY KEY, book TEXT NOT NULL, cell TEXT NOT NULL, old TEXT, new TEXT, kind TEXT, item TEXT, by TEXT, created REAL NOT NULL);
""")


class Workbooks(wb.Platform):
    label = "Workbooks, macros and queries you upload"
    kinds = ()
    uploads = (".xlsx", ".zip")                       # macro workbooks (.xlsm), VBA modules (.bas) and Power Query (.pq) come in a .zip
    simulator = "tests/mocklab/fixtures/excel_models (a budget model, an AR tie-out, a pricing calculator with VBA, a supplier master, Power Query M)"
    reads = "formulas with the values Excel cached, names, links, hidden sheets, VBA modules and Power Query M - the files are never changed; a fixed copy is handed back"


FILES = Workbooks()


def source(ctx: wb.Ctx) -> dict:
    paths = [ctx.dir / "data" / f["name"] for f in ctx.files(FILES.uploads)]
    if not paths:
        raise wb.StepFailed("Upload the workbooks (.xlsx), or a .zip with them and any macro workbooks (.xlsm), VBA modules (.bas) and Power Query (.pq).")
    try:
        src = xr.read_files(paths)
    except Exception as e:  # noqa: BLE001 - a damaged file is shown to the person
        raise wb.StepFailed(f"A workbook could not be read: {str(e)[:200]}") from e
    if not src["books"]:
        raise wb.StepFailed("No workbook among the uploads (.xlsx, or .xlsm in a .zip).")
    return src


def _hours(m: float) -> str:
    return f"{m / 60:.1f} h"


def _cost(h: float) -> str:
    b = registry.brand()
    rate, cur = float(b.get("hourly_rate") or 0), b.get("currency") or ""
    return f" - {cur}{rate * h:,.0f}" if rate else ""


def recompute(book: dict) -> dict:
    """Every formula evaluated again and compared with the value Excel cached."""
    bk = xr.Book(book)
    same, differ, errors, external, other = 0, [], 0, 0, 0
    for sh in book["sheets"].values():
        for a1, c in sh["cells"].items():
            if not c["f"]:
                continue
            try:
                v = bk.cell(sh["name"], a1)
            except xr.XlError:
                errors += 1
                continue
            except xr.External:
                external += 1
                continue
            except Exception:  # noqa: BLE001 - a function the engine does not know
                other += 1
                continue
            if xr.close(v, c["v"]):
                same += 1
            else:
                differ.append(f"{sh['name']}!{a1}: {v!r} recomputed, {c['v']!r} cached")
    return {"same": same, "differ": differ, "errors": errors, "external": external, "unknown": other}


# ================================================================== Assess

def a_connect(ctx: wb.Ctx) -> dict:
    rows = FILES.test(ctx)
    if not rows:
        raise wb.StepFailed("Nothing to read: upload the workbooks.")
    return {"summary": f"{len(rows)} upload(s) opened - read-only.", "counts": {"files": len(rows)},
            "data": {"columns": ["Source", "Kind", "Status", "What Relay sees", "Access"], "rows": [[r["source"], r["kind"], "opened" if r["ok"] else "refused", r["sees"], r["scope"]] for r in rows]}}


def a_inventory(ctx: wb.Ctx) -> dict:
    src = source(ctx)
    recs = []
    for b in src["books"]:
        for sh in b["sheets"].values():
            f = sum(1 for c in sh["cells"].values() if c["f"])
            recs.append({"id": f"{b['name']}|{sh['name']}", "object": f"{b['name']} > {sh['name']}", "kind": "hidden sheet" if sh["hidden"] else "sheet", "rows": sh["max_row"],
                         "formulas": f, "names": len(b["names"]), "links": len(b["links"])})
    for v in src["vba"]:
        recs.append({"id": v["name"], "object": v["name"], "kind": "VBA module", "rows": v["text"].count("\n"), "formulas": None, "names": None, "links": None})
    for q in src["pq"]:
        recs.append({"id": q["name"], "object": q["name"], "kind": "Power Query", "rows": q["text"].count("\n"), "formulas": None, "names": None, "links": None})
    n = sum(r["formulas"] or 0 for r in recs)
    ctx.evidence("The workbooks as read", {"books": [{"name": b["name"], "sheets": list(b["sheets"]), "names": b["names"], "links": b["links"]} for b in src["books"]],
                                           "vba": [v["name"] for v in src["vba"]], "pq": [q["name"] for q in src["pq"]]}, kind="inventory", ok=True)
    return {"summary": f"{len(src['books'])} workbook(s) with {sum(len(b['sheets']) for b in src['books'])} sheet(s) and {n} formula(s); {len(src['vba'])} VBA module(s) and {len(src['pq'])} Power Query quer(ies).",
            "counts": {"workbooks": len(src["books"]), "formulas": n}, "records": recs,
            "data": {"columns": ["Sheet or file", "Kind", "Rows", "Formulas", "Names", "Links"], "rows": [[r["object"], r["kind"], r["rows"], r["formulas"], r["names"], r["links"]] for r in recs]}}


HIGH = ("error", "breaks", "vba_path")


def a_health(ctx: wb.Ctx) -> dict:
    src = source(ctx)
    found = xr.findings(src)
    try:                                                 # a master kept in a workbook: the duplicates are Master data's
        from . import mdm_rules
        for b in src["books"]:
            for sh in b["sheets"].values():
                recs = mdm_rules._rows_to_records(b["name"], sh["name"], _rows(sh), "supplier" if re.search(r"(?i)supplier|vendor", b["name"] + sh["name"]) else "customer")
                ps = [p for p in mdm_rules.pairs(recs) if p["action"] != "not_match"] if len(recs) > 3 else []
                if ps:
                    found.append({"id": f"duplicates:{b['name']}!{sh['name']}", "kind": "duplicates", "book": b["name"], "where": sh["name"], "route": "mdm", "minutes": 3 * len(ps),
                                  "issue": f"{len(ps)} duplicate pair(s) in the master {sh['name']} - for Master data"})
    except ImportError:
        pass
    ctx.put("findings", found)
    checks = []
    for k, label in {**xr.LABEL, "duplicates": "Duplicates in masters"}.items():
        fs = [f for f in found if f["kind"] == k]
        ev = ctx.evidence(label, {"findings": fs[:300]}, kind="proof", ok=not fs)
        checks.append({"name": k, "label": label, "status": ("fail" if k in HIGH else "warn") if fs else "pass", "measured": f"{len(fs)} found", "expected": "none",
                       "detail": "; ".join(f["issue"] for f in fs[:4])[:500] or "none found", "evidence": ev})
    for b in src["books"]:
        rc = recompute(b)
        ev = ctx.evidence(f"{b['name']} evaluated again", rc, kind="proof", ok=not rc["differ"])
        checks.append({"name": f"recompute:{b['name']}", "label": f"{b['name']}: Relay's formula engine gets Excel's numbers", "status": "fail" if rc["differ"] else "pass",
                       "measured": f"{rc['same']} of {rc['same'] + len(rc['differ'])}", "expected": "all", "evidence": ev,
                       "detail": (f"{rc['same']} formula(s) agree" + (f"; {len(rc['differ'])} differ ({'; '.join(rc['differ'][:2])})" if rc["differ"] else "")
                                  + (f"; {rc['errors']} error(s)" if rc["errors"] else "") + (f"; {rc['external']} read another workbook" if rc["external"] else ""))})
    return {"summary": f"{len(found)} finding(s) in {len(src['books'])} workbook(s).", "counts": {"findings": len(found)}, "data": {"checks": checks}}


def _rows(sh: dict) -> list[list]:
    out: dict[int, dict[int, object]] = {}
    for a1, c in sh["cells"].items():
        col, row = xr.split(a1)
        out.setdefault(row, {})[col] = c["v"]
    width = max((max(r) for r in out.values() if r), default=0)
    return [[out.get(r, {}).get(cix) for cix in range(1, width + 1)] for r in sorted(out)]


def a_findings(ctx: wb.Ctx) -> dict:
    have = {r["id"]: r for r in ctx.records("findings")}
    groups: dict[tuple, list[dict]] = {}
    for f in ctx.get("findings") or []:
        groups.setdefault((f["kind"], f["book"]), []).append(f)
    recs = []
    for (k, b), fs in groups.items():
        rid = f"{k}:{b}"
        recs.append({"id": rid, "kind": k, "object": f"{b}: {', '.join(f['where'] for f in fs[:6])}" + (" ..." if len(fs) > 6 else ""), "issue": fs[0]["issue"] + (f" (and {len(fs) - 1} more like it)" if len(fs) > 1 else ""),
                     "route": fs[0]["route"], "n": len(fs), "decision": (have.get(rid) or {}).get("decision", "keep")})
    return {"summary": f"{len(recs)} group(s) of findings - keep what matters, ignore what does not.", "counts": {"groups": len(recs)}, "records": recs,
            "items": [f"{r['object']}: {r['issue']}" for r in recs[:6]],
            "data": {"columns": ["What", "Where", "Why", "Who fixes it"], "rows": [[{**xr.LABEL, "duplicates": "Duplicates in masters"}[r["kind"]], r["object"], r["issue"], r["route"]] for r in recs]}}


FIND_EDIT = wb.Edit(columns=[wb.Column("decision", "Decision", "select", options=(("keep", "Keep"), ("ignore", "Ignore"))), wb.Column("object", "Where", readonly=True),
                             wb.Column("issue", "Why", readonly=True)], add=False, remove=False, label="finding")


def a_estimate(ctx: wb.Ctx) -> dict:
    keep = {r["id"] for r in ctx.records("findings") if r.get("decision") != "ignore"}
    fs = [f for f in ctx.get("findings") or [] if f"{f['kind']}:{f['book']}" in keep or not keep]
    items, total = [], 0.0
    for routes, title, how in ((("change",), "Fixes in the workbooks", "a Change item proposes each fix by rules and proves it by evaluating the workbook again"),
                               (("ticket",), "Tie-outs for Finance", "a ticket with the rows that do not tie out"),
                               (("mdm",), "Masters for Master data", "the duplicates go to Master data's steward queue"),
                               (("retire",), "Sheets to retire", "hidden sheets that feed nothing")):
        xs = [f for f in fs if f["route"] in routes]
        if not xs:
            continue
        m = sum(f["minutes"] for f in xs)
        total += m
        items.append({"title": title, "detail": f"{len(xs)} finding(s); {how}.", "effort": _hours(m) + _cost(m / 60)})
    note = "Assumptions: 10 min per formula error, 5 per typed-in input, 15 per link to another workbook or tie-out, 15 per macro path."
    ctx.output("workbook-assessment.md", f"# Workbook assessment: {ctx.title}\n\n" + "\n".join(f"## {i['title']}\n\n{i['detail']}\n\nEffort: {i['effort']}\n" for i in items) + f"\n{note}\n",
               label="Assessment (Markdown)")
    return {"summary": f"{len(items)} group(s) of work, about {_hours(total)}{_cost(total / 60)}.", "counts": {"groups": len(items), "hours": round(total / 60, 1)},
            "data": {"items": items, "total": _hours(total), "note": note + ("" if registry.brand().get("hourly_rate") else " Set an hourly rate under Admin > Branding to see the cost.")}}


# ================================================================== Fix / change: a workbook fixed and proven

def c_request(ctx: wb.Ctx) -> dict:
    src = source(ctx)
    fs = [f for f in xr.findings(src) if f["kind"] in ("error", "hardcoded", "external")]
    if not fs:
        raise wb.StepFailed("Nothing to fix by rules: no formula error, typed-in input or link to another workbook.")
    ctx.put("findings", fs)
    return {"summary": f"{len(fs)} cell(s) to fix in {len({f['book'] for f in fs})} workbook(s).", "counts": {"cells": len(fs)},
            "data": {"text": "\n".join(f"- {f['issue']}" for f in fs[:200])}}


def _propose(book: dict, f: dict) -> dict:
    sheet, a1 = f["where"].split("!")
    old = f.get("formula") or ""
    if f["kind"] == "error":
        if "#REF!" in old:
            new, why = xr.pattern_fix(book, sheet, a1)
            return {"new": new or "", "why": why}
        return {"new": old, "why": "its formula is right: it recomputes once the cell it reads is fixed"}
    if f["kind"] == "hardcoded":
        named = xr._named_values(book)
        return {"new": xr.literal_fix(old, f["literal"], f["name"], named[f["name"]]), "why": f"the input {f['name']} instead of the typed-in {f['literal']}"}
    if f["kind"] == "external":
        bk = xr.Book(book)
        for n in xr._named_values(book):
            cand = re.sub(r"\[\d+\][A-Za-z_][\w.]*!\$?[A-Z]{1,3}\$?\d+", n, old)
            try:
                v = xr.Book(book, override={(sheet, a1): cand}).cell(sheet, a1)
            except (xr.XlError, xr.External):
                continue
            if xr.close(v, (book["sheets"][sheet]["cells"].get(a1) or {}).get("v")):
                return {"new": cand, "why": f"the linked value equals the input {n} - the link is replaced by it"}
        del bk
        return {"new": "", "why": "no input of this workbook equals the linked value - say which input it is"}
    return {"new": "", "why": ""}


def c_diagnose(ctx: wb.Ctx) -> dict:
    src = source(ctx)
    books = {b["name"]: b for b in src["books"]}
    props, checks = [], []
    for f in ctx.get("findings") or []:
        p = _propose(books[f["book"]], f)
        props.append({**f, **p})
    ctx.put("proposals", props)
    for k in ("error", "hardcoded", "external"):
        ps = [p for p in props if p["kind"] == k]
        if ps:
            known = [p for p in ps if p["new"]]
            checks.append({"name": k, "label": xr.LABEL[k], "status": "pass" if len(known) == len(ps) else "warn", "measured": f"{len(known)} of {len(ps)} proposed by rules",
                           "detail": "; ".join(f"{p['where']}: {p['new'] or '(a person says)'} - {p['why']}" for p in ps[:4])[:600]})
    return {"summary": f"{sum(1 for p in props if p['new'])} of {len(props)} fix(es) proposed by rules.", "data": {"checks": checks}}


def c_fix(ctx: wb.Ctx) -> dict:
    have = {r["id"]: r for r in ctx.records(ctx.step_id)}
    recs = []
    for p in ctx.get("proposals") or []:
        r = {"id": p["id"], "book": p["book"], "cell": p["where"], "old": p.get("formula") or "", "new": p["new"], "why": p["why"], "kind": p["kind"]}
        if p["id"] in have:
            r["new"] = have[p["id"]].get("new", r["new"])
        recs.append(r)
    return {"summary": f"{len(recs)} cell(s): the proposed formula for each - change any before you confirm.", "counts": {"cells": len(recs)}, "records": recs,
            "data": {"columns": ["Cell", "Now", "Proposed", "Why"], "rows": [[f"{r['book']} > {r['cell']}", r["old"], r["new"] or "-", r["why"]] for r in recs]}}


def _validate_fix(recs: list[dict], ctx: wb.Ctx | None = None) -> list[str]:
    out = []
    for r in recs:
        f = str(r.get("new") or "").strip()
        if not f:
            continue
        if not f.startswith("="):
            out.append(f"{r.get('cell')}: a formula starts with =")
            continue
        try:
            xr.parse(f)
        except ValueError as e:
            out.append(f"{r.get('cell')}: {e}")
    return out


FIX_EDIT = wb.Edit(columns=[wb.Column("new", "Proposed formula"), wb.Column("cell", "Cell", readonly=True), wb.Column("old", "Now", readonly=True), wb.Column("why", "Why", readonly=True)],
                   add=False, remove=True, label="cell", validate=_validate_fix)


def c_prove(ctx: wb.Ctx) -> dict:
    src = source(ctx)
    books = {b["name"]: b for b in src["books"]}
    recs = [r for r in ctx.records("fix") if r.get("new") and r["new"] != r["old"]]
    checks = []
    for name, b in books.items():
        mine = [r for r in recs if r["book"] == name]
        if not mine:
            continue
        over = {tuple(r["cell"].split("!")): r["new"] for r in mine}
        before, after = xr.Book(b), xr.Book(b, override=over)
        still, moved, fixed = [], [], 0
        for sh in b["sheets"].values():
            for a1, c in sh["cells"].items():
                if not c["f"]:
                    continue
                k = (sh["name"], a1)
                try:
                    v2 = after.cell(*k)
                except xr.External:
                    continue
                except xr.XlError as e:
                    still.append(f"{sh['name']}!{a1} ({e})")
                    continue
                try:
                    v1 = before.cell(*k)
                except xr.XlError:
                    fixed += 1
                    continue
                except xr.External:
                    continue
                if not xr.close(v1, v2) and k not in over:
                    moved.append(f"{sh['name']}!{a1}")
                if k in over and not xr.close(v1, v2):
                    moved.append(f"{sh['name']}!{a1} (the cell fixed)")
        ev = ctx.evidence(f"{name} evaluated with the fixes", {"still": still, "moved": moved, "fixed": fixed}, kind="proof", ok=not still and not moved)
        checks.append({"name": f"errors:{name}", "label": f"{name}: no error left", "status": "fail" if still else "pass", "measured": f"{fixed} cell(s) recover", "detail": ", ".join(still)[:300] or "every formula computes", "evidence": ev})
        checks.append({"name": f"moved:{name}", "label": f"{name}: no other number moves", "status": "fail" if moved else "pass", "detail": ", ".join(moved)[:300] or "only the error cells change", "evidence": ev})
    open_ = [r["cell"] for r in ctx.records("fix") if not r.get("new")]
    checks.append({"name": "open", "label": "Every cell has its fix", "status": "warn" if open_ else "pass", "detail": (", ".join(open_)[:300] + " - left as they are") if open_ else "all"})
    return {"summary": f"{len(recs)} fix(es) proven by evaluating the workbook again.", "counts": {"fixes": len(recs)}, "data": {"checks": checks}}


def c_approve(ctx: wb.Ctx) -> dict:
    recs = [r for r in ctx.records("fix") if r.get("new") and r["new"] != r["old"]]
    return {"summary": f"{len(recs)} fix(es) to hand back, released by the named approver.",
            "data": {"items": [{"title": f"{r['book']} > {r['cell']}", "detail": f"{r['old']} {r['new']}", "effort": ""} for r in recs[:80]], "total": f"{len(recs)} fix(es)"}}


def c_learn(ctx: wb.Ctx) -> dict:
    import openpyxl
    recs = [r for r in ctx.records("fix") if r.get("new") and r["new"] != r["old"]]
    made = []
    for f in ctx.files((".xlsx", ".xlsm")):
        mine = [r for r in recs if r["book"] == f["name"]]
        if not mine:
            continue
        book = openpyxl.load_workbook(ctx.dir / "data" / f["name"], keep_vba=f["name"].lower().endswith(".xlsm"))
        for r in mine:
            sheet, a1 = r["cell"].split("!")
            book[sheet][a1] = r["new"]
        buf = io.BytesIO()
        book.save(buf)
        out = re.sub(r"\.(xlsx|xlsm)$", r"-fixed.\1", f["name"])
        ctx.output(out, buf.getvalue(), label=f"{f['name']}, fixed")
        made.append(out)
        for r in mine:
            db.run("INSERT OR REPLACE INTO excel_fixes (id, book, cell, old, new, kind, item, by, created) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                   (f"xf-{ctx.id}|{f['name']}|{r['cell']}"[:200], f["name"], r["cell"], r["old"], r["new"], r["kind"], ctx.id, ctx.who or ctx.owner, time.time()))
    db.audit("excel.fixes", ctx.id, {"fixes": len(recs), "files": made}, ctx.who or ctx.owner)
    return {"summary": f"The fixed workbook(s) are handed back: {', '.join(made) or 'none'} - Excel recalculates them when they are opened; put them back where the originals live.",
            "counts": {"fixes": len(recs)}, "data": {"href": f"#/m/{MODULE}/i/{ctx.id}", "label": "The fixed workbook", "text": ", ".join(made)}}


# ================================================================== Develop and Migrate: a governed model, proven against the workbook

def _model(ctx: wb.Ctx, books: list[dict]) -> list[dict]:
    """Every computed column of every sheet, with its SQL by rules (or a person's / the agent's), per workbook."""
    have = {r["id"]: r for r in ctx.records(ctx.step_id)}
    recs = []
    for b in books:
        named = xr._named_values(b)
        tables = {s: xr.table_of(b, s) for s in b["sheets"]}
        for s in xr.order(tables):
            t = tables[s]
            r = xr.to_sql(b, s, tables, named)
            for n, f in sorted(t["formulas"].items()):
                col = t["cols"].get(n)
                if not col:
                    continue
                rid = f"{b['name']}|{s}|{col}"
                rec = {"id": rid, "book": b["name"], "sheet": s, "column": col, "header": t["head"].get(n, col), "formula": xr.at_row(f["pattern"], f["rows"][0]),
                       "sql": r["sql"].get(col, ""), "how": "rules" if col in r["sql"] else "", "problem": r["untranslated"].get(col, "")}
                if rid in have and have[rid].get("sql") and have[rid].get("origin") in ("person", "agent"):
                    rec.update(sql=have[rid]["sql"], how=have[rid]["origin"], problem="", origin=have[rid]["origin"])
                elif rid in have and have[rid].get("sql") != rec["sql"] and have[rid].get("sql"):
                    rec.update(sql=have[rid]["sql"], how="person", problem="", origin="person")
                recs.append(rec)
    return recs


def _shape_out(recs: list[dict]) -> dict:
    n = {"rules": sum(1 for r in recs if r["how"] == "rules"), "open": sum(1 for r in recs if not r["sql"])}
    return {"summary": f"{len(recs)} computed column(s): {n['rules']} translated to SQL by rules, {n['open']} for Relay's agent or a person.", "counts": {**n, "columns": len(recs), "agent": n["open"]},
            "records": recs, "data": {"columns": ["Workbook", "Sheet", "Column", "Formula (row 2)", "How", "Why not"],
                                      "rows": [[r["book"], r["sheet"], r["header"], r["formula"], r["how"] or "-", r["problem"]] for r in recs]}}


def _validate_model(recs: list[dict], ctx: wb.Ctx | None = None) -> list[str]:
    import sqlglot
    out = []
    for r in recs:
        q = str(r.get("sql") or "").strip()
        if q:
            try:
                sqlglot.parse_one(f"SELECT {q} AS x FROM t", read="duckdb")
            except Exception as e:  # noqa: BLE001 - shown to the person
                out.append(f"{r.get('sheet')}.{r.get('header') or r.get('column')}: the SQL does not parse - {str(e).splitlines()[0][:120]}")
    return out


MODEL_EDIT = wb.Edit(columns=[wb.Column("sql", "SQL (over t, the sheet's rows)", "longtext"), wb.Column("header", "Column", readonly=True), wb.Column("sheet", "Sheet", readonly=True),
                              wb.Column("formula", "Formula", readonly=True), wb.Column("problem", "Why not by rules", readonly=True)], add=False, remove=False, label="column", validate=_validate_model)

DRAFT_WORDS = ("Read model.json: the workbook's computed columns no rule translated, each with its Excel formula, the sheets as tables "
               "(their columns) and the workbook's named inputs with their values. Write model_out.json: {\"<id>\": \"<one DuckDB SQL expression over t, "
               "the sheet's own row>\"} for every id. Read other sheets with (SELECT x.col FROM \"sheet\" x WHERE ...). Use only the tables, "
               "columns and inputs given; an input from another workbook becomes a named input of this one with the value given. Then stop.")


def _draft_prompt(ctx: wb.Ctx) -> str:
    src = source(ctx)
    todo = [r for r in ctx.records(ctx.step_id) if not r.get("sql")]
    tables, inputs = {}, {}
    for b in src["books"]:
        inputs.update(xr._named_values(b))
        for s in b["sheets"]:
            t = xr.table_of(b, s)
            tables[xr.table_name(s)] = list(t["cols"].values())
    (ctx.dir / "model.json").write_text(json.dumps({"items": [{"id": r["id"], "sheet": r["sheet"], "column": r["column"], "formula": r["formula"], "problem": r["problem"]} for r in todo],
                                                    "tables": tables, "inputs": inputs}, indent=1), encoding="utf-8")
    return DRAFT_WORDS


def _draft_check(ctx: wb.Ctx) -> list[str]:
    spec = json.loads((ctx.dir / "model.json").read_text(encoding="utf-8"))
    p = ctx.dir / "model_out.json"
    if not p.exists():
        return ["model_out.json was not written"]
    got = json.loads(p.read_text(encoding="utf-8"))
    out = []
    for it in spec["items"]:
        q = str(got.get(it["id"]) or "").strip()
        if not q:
            out.append(f"no SQL for {it['sheet']}.{it['column']}")
        for tname in re.findall(r'"([a-z0-9_]+?)(?:__model)?"', q):
            if tname not in spec["tables"]:
                out.append(f"{it['column']}: the table {tname} is not a sheet of the workbook")
    return out


def _draft_after(ctx: wb.Ctx, res: dict) -> dict:
    got = json.loads((ctx.dir / "model_out.json").read_text(encoding="utf-8"))
    recs = ctx.records(ctx.step_id)
    for r in recs:
        if r["id"] in got and not r.get("sql"):
            r.update(sql=str(got[r["id"]]).strip(), how="agent", origin="agent", problem="")
    ctx.evidence("SQL drafted by Relay", {"drafts": got, "summary": res.get("text") or ""}, kind="agent", ok=True)
    return _shape_out(recs)


def _build(ctx: wb.Ctx, books: list[dict], recs: list[dict]) -> tuple[str, list[str]]:
    parts, views = [], []
    for b in books:
        tables = {s: xr.table_of(b, s) for s in b["sheets"]}
        for s in xr.order(tables):
            ex = {r["column"]: r["sql"] for r in recs if r["book"] == b["name"] and r["sheet"] == s and r.get("sql")}
            if ex:
                parts.append(f"-- {b['name']} > {s}\n" + xr.model_sql(s, tables[s], ex) + ";")
                views.append(f"{xr.table_name(s)}__model")
    return "\n\n".join(parts), views


def _prove(ctx: wb.Ctx, books: list[dict], recs: list[dict]) -> list[dict]:
    import duckdb
    import pyarrow as pa
    checks = []
    for b in books:
        con = duckdb.connect()
        tables = {s: xr.table_of(b, s) for s in b["sheets"]}
        for s, t in tables.items():
            rows = []
            for r_ in t["data"]:
                row = {"_row": r_}
                for n, c in t["cols"].items():
                    if n not in t["formulas"]:
                        cell = b["sheets"][s]["cells"].get(f"{xr.col_l(n)}{r_}")
                        row[c] = cell["v"] if cell else None
                rows.append(row)
            if rows:
                con.register(f"{xr.table_name(s)}_in", pa.Table.from_pylist(rows))
                con.execute(f'CREATE TABLE "{xr.table_name(s)}" AS SELECT * FROM "{xr.table_name(s)}_in"')
        for s in xr.order(tables):
            t = tables[s]
            ex = {r["column"]: r["sql"] for r in recs if r["book"] == b["name"] and r["sheet"] == s and r.get("sql")}
            if not ex:
                continue
            try:
                con.execute(xr.model_sql(s, t, ex))
                got = con.execute(f'SELECT * FROM "{xr.table_name(s)}__model" ORDER BY _row').fetchall()
                names = [d[0] for d in con.description]
            except Exception as e:  # noqa: BLE001 - a SQL the person or the agent wrote
                checks.append({"name": f"{b['name']}|{s}", "label": f"{b['name']} > {s}", "status": "fail", "detail": f"the model does not run: {str(e).splitlines()[0][:200]}"})
                continue
            same, diff, skipped = 0, [], 0
            for g in got:
                d = dict(zip(names, g))
                for n, col in t["cols"].items():
                    if col not in ex:
                        continue
                    cached = (b["sheets"][s]["cells"].get(f"{xr.col_l(n)}{d['_row']}") or {}).get("v")
                    if cached in xr.ERRORS:
                        skipped += 1
                        continue
                    if xr.close(d[col], cached):
                        same += 1
                    else:
                        diff.append(f"{col} row {d['_row']}: {d[col]!r} vs {cached!r}")
            ev = ctx.evidence(f"{b['name']} > {s}: the model against the workbook", {"same": same, "differ": diff[:200], "skipped_errors": skipped, "sql": xr.model_sql(s, t, ex)}, kind="proof", ok=not diff)
            checks.append({"name": f"{b['name']}|{s}", "label": f"{b['name']} > {s}: the model gives the workbook's numbers", "status": "fail" if diff else "pass",
                           "measured": f"{same} of {same + len(diff)}", "expected": "all", "evidence": ev,
                           "detail": f"{same} value(s) agree" + (f"; {len(diff)} differ ({diff[0]})" if diff else "") + (f"; {skipped} error cell(s) of the workbook left out" if skipped else "")})
        con.close()
    open_ = [f"{r['sheet']}.{r['header']}" for r in recs if not r.get("sql")]
    checks.append({"name": "open", "label": "Every computed column is in the model", "status": "warn" if open_ else "pass", "detail": (", ".join(open_)[:300] + " - left in Excel") if open_ else "all"})
    return checks


def d_describe(ctx: wb.Ctx) -> dict:
    src = source(ctx)
    rows = []
    for b in src["books"]:
        for s in b["sheets"]:
            t = xr.table_of(b, s)
            rows.append([b["name"], s, len(t["data"]), len(t["cols"]) - len(t["formulas"]), len(t["formulas"]), ", ".join(map(str, t["totals"])) or "-"])
        for n, v in xr._named_values(b).items():
            rows.append([b["name"], f"input {n}", "", "", "", v])
    return {"summary": f"{len(src['books'])} workbook(s): their sheets as tables (input and computed columns) and their named inputs.", "counts": {"workbooks": len(src["books"])},
            "data": {"columns": ["Workbook", "Sheet", "Rows", "Input columns", "Computed columns", "Totals rows / value"], "rows": rows}}


def d_shape(ctx: wb.Ctx) -> dict:
    return _shape_out(_model(ctx, source(ctx)["books"]))


def d_build(ctx: wb.Ctx) -> dict:
    src = source(ctx)
    text, views = _build(ctx, src["books"], ctx.records("shape"))
    ctx.output("model.sql", text, label="The model (SQL views, DuckDB)")
    outs = [r for r in ctx.records("shape") if r.get("sql")]
    dax = "\n".join(f"[{r['sheet']} {r['header']}] = SUM('{r['sheet']}'[{r['header']}])" for r in outs)
    ctx.output("measures.dax", dax, label="Measures (DAX)")
    return {"summary": f"{len(views)} model view(s) and {len(outs)} measure(s).", "data": {"text": text[:20000]}}


def d_prove(ctx: wb.Ctx) -> dict:
    checks = _prove(ctx, source(ctx)["books"], ctx.records("shape"))
    return {"summary": f"{sum(1 for c in checks if c['status'] == 'pass')} of {len(checks)} proof(s) agree with the workbook.", "data": {"checks": checks}}


def d_ship(ctx: wb.Ctx) -> dict:
    outs = [r for r in ctx.records("shape") if r.get("sql")]
    return {"summary": "The named approver confirms the model, and its outputs go to Formulas & metrics as drafts.",
            "data": {"items": [{"title": f"{r['sheet']} > {r['header']}", "detail": r["sql"][:160], "effort": ""} for r in outs[:60]], "total": f"{len(outs)} column(s)"}}


def _publish(ctx: wb.Ctx, recs: list[dict]) -> list[str]:
    p = db.project(ctx.id) or {}
    team, u = p.get("team_id"), db.user(ctx.owner or "")
    if not (team and u):
        return []
    made = []
    for r in [x for x in recs if x.get("sql")][:40]:
        name = f"{r['sheet']} {r['header']}"[:120]
        try:
            semantic.save_draft(team, name, {"label": r["header"], "description": f"{r['header']} of {r['sheet']} in {r['book']}, rebuilt from the workbook (proven in {ctx.id}).",
                                              "dax": f"SUM('{r['sheet']}'[{r['header']}])", "sql": f"SUM({r['column']})", "folder": r["book"]}, u, source=f"wb:{ctx.id}")
            made.append(name)
        except semantic.SemanticError:
            continue
    return made


def d_run(ctx: wb.Ctx) -> dict:
    made = _publish(ctx, ctx.records("shape"))
    db.audit("excel.model.published", ctx.id, {"metrics": made}, ctx.who or ctx.owner)
    return {"summary": f"{len(made)} draft metric(s) in Formulas & metrics - their four-eyes review certifies them; the model's SQL is in model.sql.",
            "data": {"href": "#/metrics", "label": "Formulas & metrics", "text": ", ".join(made[:6])}}


def m_discover(ctx: wb.Ctx) -> dict:
    out = a_inventory(ctx)
    out.pop("records", None)
    return out


def m_decide(ctx: wb.Ctx) -> dict:
    src = source(ctx)
    have = {r["id"]: r for r in ctx.records(ctx.step_id)}
    found = xr.findings(src)
    recs = []
    for b in src["books"]:
        tables = {s: xr.table_of(b, s) for s in b["sheets"]}
        comp = sum(len(t["formulas"]) for t in tables.values())
        breaks = any(f["kind"] == "breaks" and f["book"] == b["name"] for f in found)
        master = not comp and any(re.search(r"(?i)supplier|customer|vendor|master", b["name"] + s) for s in b["sheets"])
        d, why = ("keep", "a tie-out: kept in Excel, checked each month") if breaks else ("mdm", "a master: its records go to Master data") if master else \
                 ("rebuild", f"{comp} computed column(s) to rebuild as a model") if comp else ("retire", "nothing computed")
        rec = {"id": b["name"], "book": b["name"], "decision": d, "why": why}
        if b["name"] in have:
            rec["decision"] = have[b["name"]].get("decision", d)
        recs.append(rec)
    n = {k: sum(1 for r in recs if r["decision"] == k) for k in ("rebuild", "keep", "mdm", "retire")}
    return {"summary": f"Rebuild {n['rebuild']}, keep with checks {n['keep']}, to Master data {n['mdm']}, retire {n['retire']}.", "counts": n, "records": recs,
            "data": {"columns": ["Workbook", "Decision", "Why"], "rows": [[r["book"], r["decision"], r["why"]] for r in recs]}}


DECIDE_EDIT = wb.Edit(columns=[wb.Column("decision", "Decision", "select", options=(("rebuild", "Rebuild as a model"), ("keep", "Keep, with checks"), ("mdm", "Hand to Master data"), ("retire", "Retire"))),
                               wb.Column("book", "Workbook", readonly=True), wb.Column("why", "Why", readonly=True)], add=False, remove=False, label="workbook")


def _rebuild(ctx: wb.Ctx) -> list[dict]:
    keep = {r["book"] for r in ctx.records("decide") if r["decision"] == "rebuild"}
    return [b for b in source(ctx)["books"] if b["name"] in keep]


def m_convert(ctx: wb.Ctx) -> dict:
    return _shape_out(_model(ctx, _rebuild(ctx)))


def m_prove(ctx: wb.Ctx) -> dict:
    books = _rebuild(ctx)
    recs = ctx.records("convert")
    text, views = _build(ctx, books, recs)
    ctx.output("model.sql", text, label="The model (SQL views, DuckDB)")
    checks = _prove(ctx, books, recs)
    return {"summary": f"{sum(1 for c in checks if c['status'] == 'pass')} of {len(checks)} proof(s) agree with the workbooks.", "data": {"checks": checks}}


def m_handover(ctx: wb.Ctx) -> dict:
    dec = ctx.records("decide")
    return {"summary": "The named owner signs off: the rebuilt models, the workbooks kept with checks, the masters for Master data.",
            "data": {"items": [{"title": r["book"], "detail": f"{r['decision']} - {r['why']}", "effort": ""} for r in dec], "total": f"{len(dec)} workbook(s)"}}


def m_run(ctx: wb.Ctx) -> dict:
    made = _publish(ctx, ctx.records("convert"))
    kept = [r["book"] for r in ctx.records("decide") if r["decision"] == "keep"]
    item = None
    if kept:
        files = [(f["name"], (ctx.dir / "data" / f["name"]).read_bytes()) for f in ctx.files((".xlsx", ".xlsm")) if f["name"] in kept]
        item = wb.create(MODULE, "run", f"Checks: {', '.join(kept)}"[:160], who=ctx.owner, brief=f"The workbooks kept in Excel after {ctx.id}, checked each round.", files=files,
                         scope={"schedule": ctx.scope.get("cadence") or {"every": "week", "at": "07:00", "tz": "UTC"}}, visibility=(db.project(ctx.id) or {}).get("visibility") or "private",
                         team_id=(db.project(ctx.id) or {}).get("team_id"), parent=ctx.id)
    return {"summary": f"{len(made)} draft metric(s) in Formulas & metrics" + (f"; a Run item checks {', '.join(kept)} from now on." if item else "."),
            "data": {"href": f"#/m/{MODULE}/i/{item['id']}" if item else "#/metrics", "label": "Open the Run item" if item else "Formulas & metrics", "text": ", ".join(made[:6])}}


# ================================================================== Run & support

def r_watch(ctx: wb.Ctx) -> dict:
    src = source(ctx)
    found = [f for f in xr.findings(src) if f["kind"] in ("error", "breaks")]
    ctx.put("found", found)
    checks = [{"name": k, "label": xr.LABEL[k], "status": "fail" if any(f["kind"] == k for f in found) else "pass", "measured": f"{sum(1 for f in found if f['kind'] == k)} found",
               "detail": "; ".join(f["issue"] for f in found if f["kind"] == k)[:400] or "none"} for k in ("error", "breaks")]
    return {"summary": f"{len(found)} problem(s) in the latest upload ({', '.join(b['name'] for b in src['books'])}).", "counts": {"problems": len(found)}, "data": {"checks": checks}}


def r_alert(ctx: wb.Ctx) -> dict:
    brk = []
    for k, route in (("breaks", "ticket"), ("error", "change")):
        fs = [f for f in ctx.get("found") or [] if f["kind"] == k]
        if fs:
            brk.append({"id": f"b-{k}", "what": "; ".join(f["issue"] for f in fs[:4])[:300], "n": len(fs), "route": route, "note": "", "kind": k})
    ctx.put("breaks", brk)
    if not brk:
        return {"summary": "Nothing to route this round.", "next": "report", "counts": {"breaks": 0}}
    return {"summary": f"{len(brk)} group(s) to route.", "counts": {"breaks": len(brk)}, "items": [b["what"] for b in brk],
            "data": {"columns": ["What", "Cells or rows", "Proposed route"], "rows": [[b["what"], b["n"], b["route"]] for b in brk]}}


def r_fix(ctx: wb.Ctx) -> dict:
    have = {r["id"]: r for r in ctx.records(ctx.step_id)}
    recs = [{**b, **({k: have[b["id"]][k] for k in ("route", "note") if k in have[b["id"]]} if b["id"] in have else {})} for b in ctx.get("breaks") or []]
    return {"summary": f"{len(recs)} group(s): choose who fixes each. Nothing goes out until you confirm.", "records": recs,
            "data": {"columns": ["What", "Proposed route"], "rows": [[r["what"], r["route"]] for r in recs]}}


RFIX_EDIT = wb.Edit(columns=[wb.Column("route", "Route", "select", options=(("ticket", "Raise a ticket"), ("change", "A Change item (fix the workbook)"), ("expected", "Expected - no action"))),
                             wb.Column("note", "Note", "longtext"), wb.Column("what", "What", readonly=True)], add=False, remove=False, label="group")


def r_approve(ctx: wb.Ctx) -> dict:
    rows = []
    for b in ctx.records("fix"):
        if b["route"] == "ticket":
            h = ctx.ticket(b["what"][:120], b["what"] + (f"\n\nNote: {b['note']}" if b.get("note") else ""), priority="P3", about=b["what"])
        elif b["route"] == "change":
            files = [(f["name"], (ctx.dir / "data" / f["name"]).read_bytes()) for f in ctx.files(FILES.uploads)]
            item = wb.create(MODULE, "change", f"Fix: {b['what']}"[:120], who=ctx.owner, brief=b["what"], files=files, visibility=(db.project(ctx.id) or {}).get("visibility") or "private",
                             team_id=(db.project(ctx.id) or {}).get("team_id"), parent=ctx.id)
            h = ctx._handoff({"kind": "change", "label": b["what"][:120], "status": "Change item started", "link": f"#/m/{MODULE}/i/{item['id']}", "output": item["id"]})
        else:
            h = {"kind": "expected", "status": "expected - recorded"}
        rows.append([b["what"][:160], b["route"], h.get("status"), h.get("case") or h.get("checkpoint") or h.get("output") or ""])
    return {"summary": f"{len(rows)} hand-off(s), as you approved.", "data": {"columns": ["What", "Route", "Status", "Reference"], "rows": rows}}


def r_report(ctx: wb.Ctx) -> dict:
    n = len(ctx.get("breaks") or [])
    ctx.output(f"workbook-report-{time.strftime('%Y%m%d-%H%M', time.gmtime())}.md", f"# Workbook run report: {ctx.title}\n\n" + "".join(f"- {b['what']} {b.get('route')}\n" for b in ctx.records("fix")),
               label="Run report (Markdown)")
    return {"summary": f"{n} group(s) this round.", "counts": {"groups": n}, "data": {"columns": ["Round", "Groups"], "rows": [[time.strftime("%d %b %H:%M", time.gmtime()), n]]}}


def _cards(u: dict) -> list[dict]:
    rows = [[r["book"], r["cell"], r["old"] or "", r["new"] or "", r["item"] or ""] for r in db.q("SELECT * FROM excel_fixes ORDER BY created DESC LIMIT 20")]
    return [{"title": "Workbook fixes handed back", "columns": ["Workbook", "Cell", "Was", "Now", "Work item"], "rows": rows,
             "empty": "None yet: a Change item proposes each fix by rules, proves it by evaluating the workbook again and hands the fixed workbook back."}]


GUIDE = """# Excel & spreadsheet models - the work item

This folder is one work item of Relay's Excel & spreadsheet models module. Relay reads the workbooks (formulas and the
values Excel cached), evaluates them again with its own formula engine and translates each sheet's column formulas into
SQL by rules; you are asked only for the formulas no rule translates.

- `model.json` (written by the app before your run): the columns to translate, each with its Excel formula; the sheets as
  tables with their columns; the workbook's named inputs with their values.
- `model_out.json`: what you write - {"<id>": "<one DuckDB SQL expression over t, the sheet's own row>"}.

Use only the tables, columns and inputs given; never invent a number."""


wb.register(wb.Pack(
    module=MODULE, guide=GUIDE,
    lineage="each workbook's sheets as the tables its model reads; the model's views feed the metrics drafted in Formulas & metrics",
    platforms={"files": FILES},
    schemas={"finding": FIND_EDIT.columns, "fix": FIX_EDIT.columns, "column": MODEL_EDIT.columns, "workbook": DECIDE_EDIT.columns},
    cards=_cards,
    work={
        "assess": wb.Work(title="See every sheet, formula, link, macro and query - and whether the numbers hold", steps={
            "Connect": wb.Step(kind="platform", run=a_connect, agent="Connector", text="The workbooks, macros and queries you upload are opened - never changed"),
            "Inventory": wb.Step(kind="platform", run=a_inventory, agent="Workbook reader", text="Every sheet with its formulas, names and links; the VBA modules and Power Query"),
            "Health": wb.Step(kind="proof", run=a_health, view="gates", agent="Formula checker",
                              text="Relay's formula engine evaluates the workbook again; errors, typed-in inputs, links to other workbooks, hidden sheets, tie-outs, macro paths"),
            "Findings": wb.Step(kind="person", run=a_findings, edit=FIND_EDIT, text="What needs attention - you keep or ignore each finding"),
            "Estimate": wb.Step(kind="deterministic", run=a_estimate, view="plan", agent="Estimator", text="Fixes, tie-outs for Finance, masters for Master data, sheets to retire - with the time")}),
        "develop": wb.Work(title="A governed model from a workbook: translated by rules, proven against its own numbers, metrics drafted", steps={
            "Describe": wb.Step(kind="platform", run=d_describe, agent="Workbook reader", text="The sheets as tables - input and computed columns - and the named inputs"),
            "Shape": wb.Step(kind="deterministic", run=d_shape, agent="Model builder", edit=MODEL_EDIT, confirm="the model - ask Relay to translate the rest first, or go on without them",
                             text="Each computed column as SQL by rules: lookups become joins, typed-in numbers the inputs they mean; Relay's agent drafts what no rule translates",
                             actions={"agent": wb.Action(label="Ask Relay to translate the rest", kind="agent", prompt=_draft_prompt, check=_draft_check, after=_draft_after, agent="Model builder (AI)",
                                                         help="The agent writes one SQL expression per column no rule translates; each is checked, then proven like the others.")}),
            "Build": wb.Step(kind="deterministic", run=d_build, view="text", agent="Model builder", text="The model as SQL views, and its measures"),
            "Prove": wb.Step(kind="proof", run=d_prove, view="gates", agent="Prover", back_to="shape", text="The model built in DuckDB from the workbook's inputs gives the workbook's own numbers"),
            "Ship": wb.Step(kind="person", run=d_ship, view="plan", approver=True, text="The named approver confirms the model"),
            "Run": wb.Step(kind="deterministic", run=d_run, view="link", agent="Publisher", text="The outputs become draft metrics in Formulas & metrics, for its four-eyes review")}),
        "change": wb.Work(title="Fix a workbook: each fix proposed by rules and proven by evaluating the workbook again", needs_source=True, steps={
            "Request": wb.Step(kind="platform", run=c_request, view="text", agent="Workbook reader", text="The formula errors, typed-in inputs and links to other workbooks"),
            "Diagnose": wb.Step(kind="deterministic", run=c_diagnose, view="gates", agent="Formula checker", text="The fix for each: the column's pattern, the input meant, the input a link equals"),
            "Fix": wb.Step(kind="deterministic", run=c_fix, agent="Formula checker", edit=FIX_EDIT, confirm_if=lambda ctx, out: True, text="The proposed formula for each cell - you confirm or change it"),
            "Prove": wb.Step(kind="proof", run=c_prove, view="gates", agent="Prover", back_to="fix", text="Evaluated again: no error left, no other number moves"),
            "Approve": wb.Step(kind="person", run=c_approve, view="plan", approver=True, text="The named approver releases the fixes"),
            "Learn": wb.Step(kind="deterministic", run=c_learn, view="link", agent="Publisher", text="The fixed workbook is handed back; the fixes are kept")}),
        "migrate": wb.Work(title="Move workbooks out of Excel: rebuild, keep with checks, masters to Master data, retire", steps={
            "Discover": wb.Step(kind="platform", run=m_discover, agent="Workbook reader", text="Every workbook, sheet, formula, macro and query"),
            "Decide": wb.Step(kind="deterministic", run=m_decide, agent="Rationaliser", edit=DECIDE_EDIT, text="Rebuild, keep with checks, hand to Master data or retire each workbook"),
            "Convert": wb.Step(kind="deterministic", run=m_convert, agent="Model builder", edit=MODEL_EDIT, confirm="the models - ask Relay to translate the rest first, or go on without them",
                               confirm_if=lambda ctx, out: bool((out.get("counts") or {}).get("agent")),
                               text="The rebuilt workbooks' computed columns as SQL by rules; the agent drafts the rest",
                               actions={"agent": wb.Action(label="Ask Relay to translate the rest", kind="agent", prompt=_draft_prompt, check=_draft_check, after=_draft_after, agent="Model builder (AI)",
                                                           help="The agent writes one SQL expression per column no rule translates.")}),
            "Prove": wb.Step(kind="proof", run=m_prove, view="gates", agent="Prover", back_to="convert", text="Each model gives its workbook's own numbers"),
            "Hand over": wb.Step(kind="person", run=m_handover, view="plan", approver=True, text="The named owner signs off"),
            "Run": wb.Step(kind="deterministic", run=m_run, view="link", agent="Publisher", text="Draft metrics in Formulas & metrics; a Run item checks the workbooks kept in Excel")},
            fields=[wb.Field("cadence", "Check the kept workbooks", "cadence", default={"every": "week", "at": "07:00", "tz": "UTC"})]),
        "run": wb.Work(title="Check a workbook each round: errors and tie-outs that do not tie out go to a person first", needs_source=True, steps={
            "Watch": wb.Step(kind="platform", run=r_watch, view="gates", agent="Watcher", text="The latest upload read again: errors and tie-outs"),
            "Alert": wb.Step(kind="deterministic", run=r_alert, agent="Triage", text="Grouped by kind"),
            "Fix": wb.Step(kind="deterministic", run=r_fix, agent="Triage", edit=RFIX_EDIT, text="Relay proposes who fixes each; you confirm or change it"),
            "Approve": wb.Step(kind="platform", run=r_approve, agent="Dispatcher", text="The approved hand-offs go out: a ticket for Finance, a Change item for the workbook"),
            "Report": wb.Step(kind="deterministic", run=r_report, agent="Reporter", confirm_if=lambda ctx, out: bool(ctx.get("breaks")), text="A run report; you confirm it when something needed routing")},
            fields=[wb.Field("schedule", "Check it", "cadence", default={"every": "week", "at": "07:00", "tz": "UTC"})]),
    }))
