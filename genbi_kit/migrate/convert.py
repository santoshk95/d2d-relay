"""The neutral model -> a report definition (definition.yaml, the schema GENBI.md describes), rules first.

build(estate, report, ...) returns the definition plus a plan: which rule made every measure, column, slicer and
visual, the lineage edges (source table -> transformation -> target table / measure), the gaps the agent must fill
(gap measures are written as BLANK () with a description so the definition still validates) and the per-visual
metadata the proof uses (source visual, categories, measures). write_project(...) puts the definition, the data,
request.md and migrate_brief.json into a dashboard-style project folder so the existing builder, gates and DAX
checker run on it unchanged.
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import yaml

from . import expr, model, rules
from .rules import Context, RuleError, _dq

W_LIMIT_TABLE = 25
DAX_TYPES = {"int": "int", "decimal": "decimal", "string": "string", "date": "date", "bool": "bool"}


class _Dumper(yaml.SafeDumper):
    pass


def _str(dumper, value):
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style="|" if "\n" in value else None)


_Dumper.add_representer(str, _str)


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")[:24] or "v"


def _measure_name(item: str, ctx: Context, taken: set[str], query: str = "") -> str:
    """A measure name that is not a column name (Power BI refuses that) and not taken by another query's item."""
    cols = {c.lower() for t in ctx.tables.values() for c in (x["name"] for x in t.get("columns") or [])} | {"date", "year", "month", "month number", "month start", "year month", "quarter", "weekday"}
    name = item
    if name.lower() in cols:
        name = f"{item} Total"
    if name.lower() in taken and query:
        name = f"{name} ({query})"
    k = 2
    base = name
    while name.lower() in taken:
        name = f"{base} {k}"; k += 1
    taken.add(name.lower())
    return name.replace("[", "(").replace("]", ")")


def _date_range(data_dir: Path | None, fact: dict | None, date_col: str | None) -> tuple[str, str]:
    """The Date table's span from the fact's CSV (whole years), else a safe default."""
    lo, hi = None, None
    if data_dir and fact and fact.get("file") and date_col and (data_dir / fact["file"]).exists():
        import csv
        with open(data_dir / fact["file"], encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                v = (row.get(date_col) or "")[:10]
                if len(v) == 10:
                    lo = v if lo is None or v < lo else lo
                    hi = v if hi is None or v > hi else hi
    if not lo:
        return "2024-01-01", "2026-12-31"
    return f"{lo[:4]}-01-01", f"{hi[:4]}-12-31"


def build(estate: dict, report: dict, pack: rules.RulePack | None = None, data_dir: Path | None = None, mode: str = "rules_first",
          comment: str | None = None, visuals: str = "relay") -> tuple[dict, dict]:
    """(definition, plan). mode: rules_first (gaps go to the agent), rules_only (gaps stay BLANK and are listed),
    ai_led (the whole definition is still drafted by rules, the agent is asked to rework every calculation).
    visuals: relay (Visual Atlas visuals) or builtin (Power BI's own visuals, `pbi.*`)."""
    defn, plan = _build(estate, report, pack, data_dir, mode, comment)
    if visuals == "builtin":
        swapped = {}
        for page in defn["pages"]:
            for row in page.get("rows") or []:
                for i, vis in enumerate(row["visuals"]):
                    new = rules.builtin_visual(vis)
                    if new is not vis:
                        swapped[vis["id"]] = new["type"]
                        row["visuals"][i] = new
        for pv in plan["visuals"]:
            if pv.get("def_id") in swapped:
                pv.update(type=swapped[pv["def_id"]], chart=None)
        plan["decisions"].append(f"Power BI's built-in visuals: {len(swapped)} visual(s) drawn by Power BI itself (no custom visual in the report)")
        defn["visuals_mode"] = "builtin"
    return defn, plan


def _build(estate: dict, report: dict, pack: rules.RulePack | None, data_dir: Path | None, mode: str, comment: str | None) -> tuple[dict, dict]:
    ds = model.dataset_of(estate, report)
    if not ds:
        raise RuleError(f"{report['name']}: its package {report.get('missing_dataset') or ''} is not in the estate".strip())
    if not ds.get("tables"):
        raise RuleError(f"{report['name']}: package {ds['name']} has no query subjects to build a model from")
    fact_t = next((t for t in ds["tables"] if t.get("role") == "fact"), ds["tables"][0])
    plan: dict = {"report": report["id"], "name": report["name"], "dataset": ds["id"], "mode": mode, "measures": [], "columns": [], "calculated_columns": [],
                  "filters": [], "visuals": [], "gaps": [], "unsupported": [], "lineage": [], "decisions": [], "rules_used": {}, "ai": 0}
    for f in report.get("features") or []:
        if f in rules.UNSUPPORTED_FEATURES:
            plan["unsupported"].append({"what": f, "reason": rules.UNSUPPORTED_FEATURES[f]})
    # ---- tables
    tables, rel = [], []
    for t in ds["tables"]:
        cols = []
        for c in t.get("columns") or []:
            role = c.get("role") or ("measure" if c["type"] in ("int", "decimal") else "attribute")
            hidden = role in ("measure", "key") or (t is fact_t and role == "date") or c["name"].lower().endswith("key")
            cols.append({"name": c["name"], "type": DAX_TYPES.get(c["type"], "string"), **({"hidden": True} if hidden else {})})
        tables.append({"name": t["name"], "csv": t.get("file") or f"{t['name'].lower()}.csv", "description": f"{t['name']} from {estate['source']['label']} {ds['kind']} “{ds['name']}”",
                       "columns": cols})
        plan["lineage"].append({"from": f"{ds['name']}.{t['name']}", "kind": "source_table", "to": f"{t['name']}", "detail": f"{len(cols)} columns"})
    for r in ds.get("relationships") or []:
        rel.append(f"{r['from']} -> {r['to']}")
    date_col = next((c["name"] for c in fact_t.get("columns") or [] if c.get("role") == "date" or c["type"] == "date"), None)
    has_date = bool(date_col) and not any(t["name"] == "Date" for t in tables)
    if has_date:
        start, end = _date_range(data_dir, fact_t, date_col)
        tables.append({"name": "Date", "date_table": {"start": start, "end": end, "is_past_from": f"{fact_t['name']}[{date_col}]"}})
        rel.append(f"{fact_t['name']}[{date_col}] -> Date[Date]")
    # ---- queries -> columns, filters, measures
    measures: list[dict] = []
    calc_cols: list[dict] = []
    filters: list[dict] = []
    taken: set[str] = set()
    ctxs: dict[str, Context] = {}
    item_ref: dict[tuple[str, str], dict] = {}        # (query, item) -> {"ref": "[M]" | "Table[Col]", "kind", "sql": per-visual fn}
    q_filters: dict[str, list] = {}                   # query -> [(rule id, info, filter)]
    q_where: dict[str, list[str]] = {}                # query -> SQL conditions folded into that query's visuals
    for q in report.get("queries") or []:
        ctx = Context(ds, q.get("items") or [], fact_t["name"])
        ctxs[q["name"]] = ctx
        attrs = [it for it in q.get("items") or [] if rules.is_attribute_item(it, ctx)]
        for it in attrs:
            ctx.column_items[it["name"]] = (ctx.fact, it["name"])
        for it in q.get("items") or []:
            if it["name"] in {a["name"] for a in attrs}:
                continue
            ctx.measure_names[it["name"]] = _measure_name(it["name"], ctx, taken, q["name"])
        for it in attrs:
            try:
                tr = rules.translate_attribute(it, ctx)
            except RuleError as e:
                plan["gaps"].append({"item": it["name"], "query": q["name"], "function": "?", "reason": str(e), "expression": it["expression"], "kind": "column"})
                continue
            if tr.kind == "column":
                ctx.column_items[it["name"]] = (tr.table, tr.column)
                item_ref[(q["name"], it["name"])] = {"ref": f"{tr.table}[{tr.column}]", "kind": "column", "sql": tr.sql, "table": tr.table, "column": tr.column, "rules": tr.rules}
                plan["columns"].append({"item": it["name"], "query": q["name"], "field": f"{tr.table}[{tr.column}]", "rules": sorted(set(tr.rules)), "confidence": tr.confidence})
            elif tr.dax:
                name = it["name"] if not any(c["name"].lower() == it["name"].lower() for c in (ctx.tables.get(tr.table) or {}).get("columns") or []) else f"{it['name']} (calc)"
                if not any(c["table"] == tr.table and c["name"] == name for c in calc_cols):
                    calc_cols.append({"table": tr.table, "name": name, "type": "string" if tr.text else "int" if "Year" in tr.dax and "*" in tr.dax else "string" if any(k in tr.dax for k in ("UPPER", "LOWER", "MID", "TRIM", "&")) else "decimal",
                                      "expression": tr.dax})
                ctx.column_items[it["name"]] = (tr.table, name)
                ctx.cols.setdefault(tr.table, {})[name.lower()] = {"name": name, "type": "string", "role": "attribute"}
                item_ref[(q["name"], it["name"])] = {"ref": f"{tr.table}[{name}]", "kind": "column", "sql": tr.sql, "table": tr.table, "column": name, "rules": tr.rules}
                plan["calculated_columns"].append({"item": it["name"], "query": q["name"], "field": f"{tr.table}[{name}]", "rules": sorted(set(tr.rules)), "confidence": tr.confidence, "dax": tr.dax})
                plan["lineage"].append({"from": f"{q['name']}.{it['name']}", "kind": "transform", "to": f"{tr.table}[{name}]", "detail": it["expression"]})
                for rid in tr.rules:
                    plan["rules_used"][rid] = plan["rules_used"].get(rid, 0) + 1
            else:
                for g in tr.gaps:
                    plan["gaps"].append({**g, "item": it["name"], "query": q["name"], "kind": "column"})
        q_filters[q["name"]] = []
        for f in q.get("filters") or []:
            rid, info = rules.filter_rule(f["expression"], ctx)
            if rid is None:
                plan["gaps"].append({"item": f["expression"], "query": q["name"], "function": "filter", "reason": info["reason"], "expression": f["expression"], "kind": "filter"})
                plan["decisions"].append(f"filter {f['expression']}: {info['reason']} → noted for the agent")
                continue
            q_filters[q["name"]].append((rid, info, f))
    # a constant filter every query shares becomes a report slicer with that default; one that only some queries
    # have is folded into those queries' measures (CALCULATE) and their visuals' SQL, so the other visuals keep their numbers
    consts = {qn: {(info["field"], info["default"]) for rid, info, _ in fl if rid == "cog.filter.constant"} for qn, fl in q_filters.items()}
    shared = set.intersection(*consts.values()) if consts else set()
    q_calc: dict[str, list[tuple[str, str, object]]] = {}
    for qn, fl in q_filters.items():
        ctx = ctxs[qn]
        for rid, info, f in fl:
            if rid == "cog.filter.prompt":
                if not any(x["field"] == info["field"] for x in filters):
                    filters.append({"field": info["field"], "label": info["label"]})
                    plan["filters"].append({"query": qn, "expression": f["expression"], "field": info["field"], "rule": rid, "prompt": info.get("prompt")})
                    plan["rules_used"][rid] = plan["rules_used"].get(rid, 0) + 1
                    plan["decisions"].append(f"filter {f['expression']} → slicer on {info['field']} (prompt → multi-select)")
                continue
            if (info["field"], info["default"]) in shared:
                if not any(x["field"] == info["field"] for x in filters):
                    filters.append({"field": info["field"], "label": info["label"], "default": info["default"]})
                    plan["filters"].append({"query": qn, "expression": f["expression"], "field": info["field"], "rule": rid, "default": info["default"]})
                    plan["rules_used"][rid] = plan["rules_used"].get(rid, 0) + 1
                    plan["decisions"].append(f"filter {f['expression']} → slicer on {info['field']}, default {info['default']} (every query has it)")
                continue
            m = re.match(r"^(.+?)\[(.+)\]$", info["field"])
            t, c = m.group(1), m.group(2)
            v = info["default"]
            dax_v = str(v) if isinstance(v, (int, float)) else rules._dax_str(v)
            sql_v = str(v) if isinstance(v, (int, float)) else rules._sql_str(v)
            q_calc.setdefault(qn, []).append((f"{rules.dax_col(t, c)} = {dax_v}", f"{ctx.aliases.get(t, 'f')}.{_dq(c)} = {sql_v}", t))
            plan["filters"].append({"query": qn, "expression": f["expression"], "field": info["field"], "rule": "cog.filter.measure", "default": v})
            plan["rules_used"]["cog.filter.measure"] = plan["rules_used"].get("cog.filter.measure", 0) + 1
            plan["decisions"].append(f"filter {f['expression']} → CALCULATE on {qn}'s measures and WHERE in its visuals (only this query has it)")
    for qn, conds in q_calc.items():
        q_where[qn] = [s for _, s, _ in conds]
        ctxs[qn].extra_where = q_where[qn]
        ctxs[qn].extra_tables = {t for _, _, t in conds}
        if any(t == "Date" for _, _, t in conds):
            ctxs[qn].needs_date = True
    for q in report.get("queries") or []:
        ctx = ctxs[q["name"]]
        attr_names = {it["name"] for it in q.get("items") or [] if (q["name"], it["name"]) in item_ref or it["name"] in ctx.column_items}
        for it in q.get("items") or []:
            if (q["name"], it["name"]) in item_ref or it["name"] in attr_names:
                continue
            mname = ctx.measure_names[it["name"]]
            tr = rules.translate_measure(it, ctx, pack)
            if tr.dax and q.get("name") in q_calc:
                tr.dax = f"CALCULATE ( {tr.dax}, " + ", ".join(d for d, _, _ in q_calc[q['name']]) + " )"
                tr.rules.append("cog.filter.measure")
            desc = f"{estate['source']['label']}: {it['expression']}"
            if tr.dax and not tr.gaps and mode != "ai_led":
                measures.append({"name": mname, "expression": tr.dax, "format": tr.format or "", "folder": "Converted", "description": desc})
                plan["decisions"].append(f"{it['name']} → measure [{mname}] ({', '.join(sorted(set(tr.rules))) or 'rule'})")
            else:
                reason = "; ".join(g["reason"] for g in tr.gaps) or ("the agent reworks every calculation (AI-led)" if mode == "ai_led" else "no rule")
                measures.append({"name": mname, "expression": tr.dax if (tr.dax and mode == "ai_led") else "BLANK ()", "format": tr.format or "", "folder": "Converted",
                                 "description": f"NO RULE YET — the agent writes this measure. {desc} ({reason})"})
                for g in (tr.gaps or [{"function": "ai", "reason": reason, "expression": it["expression"]}]):
                    plan["gaps"].append({**g, "item": it["name"], "query": q["name"], "measure": mname, "kind": "measure", "sql": tr.sql, "window": tr.window,
                                         "filter": " && ".join(d for d, _, _ in q_calc.get(q["name"], [])) or None})
                plan["decisions"].append(f"{it['name']} → measure [{mname}]: {reason} → agent")
            item_ref[(q["name"], it["name"])] = {"ref": f"[{mname}]", "kind": "measure", "sql": tr.sql, "window": tr.window, "format": tr.format, "rules": tr.rules, "gap": bool(tr.gaps) or mode == "ai_led"}
            plan["measures"].append({"item": it["name"], "query": q["name"], "measure": mname, "rules": sorted(set(tr.rules)), "confidence": tr.confidence, "gaps": tr.gaps, "dax": tr.dax})
            plan["lineage"].append({"from": f"{q['name']}.{it['name']}", "kind": "transform", "to": f"[{mname}]", "detail": it["expression"]})
            for rid in tr.rules:
                plan["rules_used"][rid] = plan["rules_used"].get(rid, 0) + 1
    for p in report.get("prompts") or []:
        if p.get("item") and not any(x["label"] == p["item"] for x in filters):
            q = next((qq for qq in report.get("queries") or [] if qq["name"] == p.get("query")), None)
            ref = item_ref.get((q["name"], p["item"])) if q else None
            if ref and ref["kind"] == "column":
                filters.append({"field": ref["ref"], "label": p["item"]})
                plan["filters"].append({"query": q["name"], "expression": f"prompt {p['name']}", "field": ref["ref"], "rule": "cog.filter.prompt", "prompt": p["name"]})
    # ---- pages and visuals
    pages = []
    used_tables: set[str] = {fact_t["name"]}
    for p in report.get("pages") or []:
        rows: list[list[dict]] = []
        kpis: list[dict] = []
        ids_on_page: set[str] = set()
        for v in p.get("visuals") or []:
            vr = rules.visual_rule(v)
            if vr.get("skip"):
                continue
            q = v.get("query")
            ctx = ctxs.get(q)
            if vr["type"] is None or ctx is None:
                plan["unsupported"].append({"what": f"{v['kind']} “{v.get('title') or v['id']}”", "reason": vr["reason"] if ctx else f"the visual's query {q} is not in the report"})
                plan["visuals"].append({"id": v["id"], "kind": v["kind"], "type": None, "rule": None, "confidence": "low", "reason": vr["reason"], "title": v.get("title")})
                continue
            vis, meta = _visual(v, vr, ctx, item_ref, filters, has_date, fact_t, plan)
            if vis is None:
                continue
            if vis["type"] == "atlasParts" and _signed_parts(ds, data_dir, report, q, meta):
                vis.update(type="atlasColumns", chart="clusteredBar", sort=[vis["fields"]["values"][0], "desc"])
                vr = {**vr, "rule": "cog.viz.pie.signed", "confidence": rules.RULES["cog.viz.pie.signed"][1], "reason": rules.RULES["cog.viz.pie.signed"][2]}
            base_id, k = vis["id"], 2
            while vis["id"] in ids_on_page:                   # ids are unique per page
                vis["id"] = f"{base_id}_{k}"; k += 1
            ids_on_page.add(vis["id"])
            used_tables |= set(meta.get("tables") or [])
            plan["visuals"].append({"id": v["id"], "def_id": vis["id"], "page": p["name"], "kind": v["kind"], "type": vis["type"], "chart": vis.get("chart"), "rule": vr["rule"],
                                    "confidence": vr["confidence"], "reason": vr["reason"], "title": vis.get("title"), "proof": meta})
            plan["rules_used"][vr["rule"]] = plan["rules_used"].get(vr["rule"], 0) + 1
            plan["decisions"].append(f"{v['kind']} “{v.get('title') or v['id']}” → {vis['type']}{' ' + vis['chart'] if vis.get('chart') else ''} ({vr['rule']})")
            if vis["type"] == "atlasGauges" and vis.get("chart") == "card":
                kpis.append(vis)
            else:
                if kpis:
                    rows.append(kpis); kpis = []
                if rows and len(rows[-1]) < 2 and rows[-1][0]["type"] != "atlasGauges":
                    rows[-1].append(vis)
                else:
                    rows.append([vis])
        if kpis:
            rows.insert(0, kpis)
        if rows:
            pages.append({"name": p["name"], "rows": [{"visuals": r, **({"height": 150} if r and r[0]["type"] == "atlasGauges" and r[0].get("chart") == "card" else {})} for r in rows]})
    if not pages:          # nothing drawable: one page listing the first query, so the report still builds and a person sees what it held
        q = (report.get("queries") or [{}])[0]
        ctx = ctxs.get(q.get("name"))
        if ctx:
            fields = [item_ref[(q["name"], it["name"])]["ref"] for it in q.get("items") or [] if (q["name"], it["name"]) in item_ref][:8]
            if fields:
                sql, meta = _table_sql(q["name"], [it["name"] for it in q.get("items") or [] if (q["name"], it["name"]) in item_ref][:8], ctx, item_ref, filters, has_date, fact_t)
                pages.append({"name": "Page1", "rows": [{"visuals": [{"id": "p1_list", "type": "table", "title": f"{report['name']} — data", "fields": fields, "prototype": {"sql": sql}}]}]})
                plan["visuals"].append({"id": "p1_list", "def_id": "p1_list", "page": "Page1", "kind": "list", "type": "table", "rule": "cog.viz.list", "confidence": "low",
                                        "reason": "no drawable visual: the first query as a table", "title": None, "proof": meta})
    ai_gaps = [g for g in plan["gaps"] if g.get("kind") == "measure"]
    plan["ai"] = len(ai_gaps)
    defn = {"name": _report_title(report["name"]),
            "description": f"Converted from {estate['source']['label']} {report['type'].lower()} “{report['name']}” ({report['folder']}) by Relay — rules first"
                           + (f"; {len(ai_gaps)} calculation(s) for the agent" if ai_gaps else "") + (f". Review comment: {comment}" if comment else ""),
            "tables": tables, **({"calculated_columns": calc_cols} if calc_cols else {}), "relationships": rel, "measures": measures,
            **({"filters": filters} if filters else {}), "pages": pages}
    plan["summary"] = {"tables": len(tables), "measures": len(measures), "columns": len(plan["columns"]), "calculated_columns": len(calc_cols), "filters": len(filters),
                       "visuals": sum(len(r["visuals"]) for p in pages for r in p["rows"]), "pages": len(pages), "gaps": len(plan["gaps"]), "ai": plan["ai"],
                       "unsupported": len(plan["unsupported"]), "rules": sum(plan["rules_used"].values()), "by_rule": plan["rules_used"]}
    return defn, plan


def _report_title(name: str) -> str:
    return re.sub(r"[^\w .,'()&–-]+", " ", name).strip()[:80] or "Converted report"


def _from_clause(ctx: Context, tables: set[str], has_date: bool, fact_t: dict) -> str:
    fact = fact_t["name"]
    parts = [f'{_dq(fact)} {ctx.aliases[fact]}']
    rels = {}
    for r in ctx.dataset.get("relationships") or []:
        m1 = re.match(r"^(.+?)\[(.+)\]$", r["from"]); m2 = re.match(r"^(.+?)\[(.+)\]$", r["to"])
        if m1 and m2 and m1.group(1) == fact:
            rels[m2.group(1)] = (m1.group(2), m2.group(2))
    for t in sorted(tables):
        if t in (fact, "Date"):
            continue
        if t in rels:
            fk, pk = rels[t]
            parts.append(f'LEFT JOIN {_dq(t)} {ctx.aliases[t]} ON {ctx.aliases[fact]}.{_dq(fk)} = {ctx.aliases[t]}.{_dq(pk)}')
        else:
            parts.append(f'CROSS JOIN {_dq(t)} {ctx.aliases[t]}')
    if "Date" in tables and has_date:
        parts.append(f'JOIN "Date" dt ON {ctx.aliases[fact]}.{_dq(ctx.date_col)} = dt."Date"')
    return "\n".join(parts)


def _where(filters: list[dict], ctx: Context, has_date: bool) -> tuple[str, set[str]]:
    conds, tables = list(getattr(ctx, "extra_where", []) or []), set(getattr(ctx, "extra_tables", set()) or set())
    for f in filters:
        if f.get("default") is None:
            continue
        m = re.match(r"^(.+?)\[(.+)\]$", f["field"])
        if not m:
            continue
        t, c = m.group(1), m.group(2)
        if t == "Date" and not has_date:
            continue
        tables.add(t)
        v = f["default"]
        conds.append(f"{ctx.aliases.get(t, 'f')}.{_dq(c)} = " + (str(v) if isinstance(v, (int, float)) else rules._sql_str(v)))
    return (" AND ".join(conds)), tables


def _col_sql(ref: dict, ctx: Context) -> tuple[str, set[str]]:
    return ref["sql"], {ref["table"]} if ref.get("table") else set()


def _measure_sql(q: str, name: str, ctx: Context, item_ref: dict) -> str | None:
    """The SQL of a measure for this visual (window partitions follow the visual's group columns)."""
    it = ctx.items.get(name)
    if not it:
        return None
    tr = rules.translate_measure(it, ctx, None)
    return tr.sql


def _month_sort(sql_expr: str) -> str | None:
    return 'dt."Month Number"' if sql_expr == 'dt."Month"' else 'dt."Weekday Number"' if sql_expr == 'dt."Weekday"' else None


def _table_sql(q: str, items: list[str], ctx: Context, item_ref: dict, filters: list[dict], has_date: bool, fact_t: dict, limit: int = W_LIMIT_TABLE, order_by_measure: bool = True):
    cols, groups, tables, meta_cats, meta_meas = [], [], {fact_t["name"]}, [], []
    ctx.group_cols = {(item_ref[(q, n)]["table"], item_ref[(q, n)]["column"]) for n in items if (q, n) in item_ref and item_ref[(q, n)]["kind"] == "column"}
    ctx.order_sql = []
    for n in items:
        ref = item_ref.get((q, n))
        if not ref:
            continue
        if ref["kind"] == "column":
            cols.append(f'{ref["sql"]} AS {_dq(ref["column"])}')
            groups.append(ref["sql"])
            tables.add(ref["table"])
            srt = _month_sort(ref["sql"])
            if srt:
                groups.append(srt)
            ctx.order_sql.append(srt or ref["sql"])
            meta_cats.append({"item": n, "column": ref["column"], "table": ref["table"], "sql": ref["sql"]})
    for n in items:
        ref = item_ref.get((q, n))
        if not ref or ref["kind"] != "column":
            if ref:
                sql = _measure_sql(q, n, ctx, item_ref) or "NULL"
                cols.append(f'{sql} AS {_dq(ref["ref"][1:-1])}')
                tables |= ctx.used_tables
                meta_meas.append({"item": n, "measure": ref["ref"][1:-1], "gap": ref.get("gap", False), "sql_missing": sql == "NULL"})
    where, wt = _where(filters, ctx, has_date)
    tables |= wt | ctx.used_tables
    if any(t == "Date" for t in tables):
        tables.add("Date")
    order = []
    if order_by_measure and meta_meas:
        order.append(f'{_dq(meta_meas[0]["measure"])} DESC NULLS LAST')
    order += ctx.order_sql
    sql = "SELECT " + ", ".join(cols) + "\nFROM " + _from_clause(ctx, tables, has_date, fact_t) + (f"\nWHERE {where}" if where else "") \
        + (("\nGROUP BY " + ", ".join(dict.fromkeys(groups))) if groups else "") + (("\nORDER BY " + ", ".join(order)) if order else "") + (f"\nLIMIT {limit}" if limit else "")
    return sql, {"query": q, "categories": meta_cats, "measures": meta_meas, "limit": limit, "order": "measure" if order_by_measure and meta_meas else "category", "tables": sorted(tables)}


def _signed_parts(ds: dict, data_dir: Path | None, report: dict, qname: str, meta: dict) -> bool:
    """A pie of a measure that is negative somewhere in the source (signed amounts such as GL budgets) has no shares
    to show, so the rule draws a bar chart instead. Decided on the source data itself (the simulator), never on a
    guess; without data the donut stays and the display gate is the safety net."""
    if not data_dir or not meta.get("measures"):
        return False
    query = next((qq for qq in report.get("queries") or [] if qq["name"] == qname), None)
    if not query:
        return False
    item = meta["measures"][0]["item"]
    try:
        from . import source_sim
        rows = source_sim.evaluate(ds, Path(data_dir), query, [c["item"] for c in meta.get("categories") or []], [item])
    except Exception:  # noqa: BLE001 - the simulator never blocks a conversion
        return False
    return any(isinstance(r.get(item), (int, float)) and r[item] < 0 for r in rows)


def _visual(v: dict, vr: dict, ctx: Context, item_ref: dict, filters: list[dict], has_date: bool, fact_t: dict, plan: dict):
    q = v["query"]
    kind = v["kind"]
    vid = _slug(v["id"])
    typ, chart = vr["type"], vr["chart"]
    title = v.get("title") or v["id"]
    measures = [m for m in v.get("measures") or [] if (q, m) in item_ref and item_ref[(q, m)]["kind"] == "measure"]
    cat = v.get("category") if v.get("category") and (q, v["category"]) in item_ref and item_ref[(q, v["category"])]["kind"] == "column" else None
    series = v.get("series") if v.get("series") and (q, v["series"]) in item_ref and item_ref[(q, v["series"])]["kind"] == "column" and v["series"] != cat else None
    if typ == "table":
        items = [c for c in v.get("columns") or [] if (q, c) in item_ref] or ([cat] if cat else []) + measures
        if not items:
            plan["unsupported"].append({"what": f"{kind} “{title}”", "reason": "none of its columns could be converted"})
            return None, {}
        sql, meta = _table_sql(q, items, ctx, item_ref, filters, has_date, fact_t)
        vis = {"id": vid, "type": "table", "title": title, "fields": [item_ref[(q, c)]["ref"] for c in items]}
        if meta["measures"]:
            vis["sort"] = [f'[{meta["measures"][0]["measure"]}]', "desc"]
        vis["prototype"] = {"sql": sql}
        return vis, meta
    if not measures:
        measures = [m for (qq, m), ref in item_ref.items() if qq == q and ref["kind"] == "measure"][:1]
        if not measures:
            plan["unsupported"].append({"what": f"{kind} “{title}”", "reason": "its query has no measure to draw"})
            return None, {}
    if typ in ("atlasColumns", "atlasLines", "atlasParts") and not cat:
        cat = next((c for (qq, c), ref in item_ref.items() if qq == q and ref["kind"] == "column"), None)
        if not cat:
            typ, chart = "atlasGauges", "card"
    fields: dict = {}
    items: list[str] = []
    if typ == "atlasGauges":
        fields["values"] = [item_ref[(q, m)]["ref"] for m in (measures if chart == "card" else measures[:1])]
        items = list(measures if chart == "card" else measures[:1])
        sql, meta = _table_sql(q, items, ctx, item_ref, filters, has_date, fact_t, limit=0, order_by_measure=False)
    else:
        fields["category"] = item_ref[(q, cat)]["ref"]
        if series and typ in ("atlasColumns", "atlasLines"):
            fields["series"] = item_ref[(q, series)]["ref"]
        fields["values"] = [item_ref[(q, m)]["ref"] for m in (measures[:1] if (series or typ == "atlasParts") else measures[:3])]
        items = [cat] + ([series] if "series" in fields else []) + [m for m in measures if item_ref[(q, m)]["ref"] in fields["values"]]
        sql, meta = _table_sql(q, items, ctx, item_ref, filters, has_date, fact_t, limit=0, order_by_measure=(typ == "atlasParts"))
        if typ == "atlasParts":
            sql = sql.replace("\nORDER BY", "\nORDER BY")  # top slices first (the donut's own Top N handles the rest)
    vis = {"id": vid, "type": typ, "chart": chart, "title": title, "subtitle": f"from the Cognos {kind}", "fields": fields, "prototype": {"sql": sql}}
    if typ == "atlasColumns" and chart == "clusteredBar":
        vis["sort"] = [fields["values"][0], "desc"]
    meta["kind"] = kind
    return vis, meta


# ------------------------------------------------------------------ writing the project

def dump_yaml(defn: dict) -> str:
    return yaml.dump(defn, Dumper=_Dumper, sort_keys=False, allow_unicode=True, width=200)


def write_project(d: Path, estate: dict, report: dict, defn: dict, plan: dict, source_dir: Path, mode: str = "rules_first", comment: str | None = None) -> None:
    """A dashboard-style project folder: data/ (the dataset's CSVs), definition.yaml, request.md (what the agent must
    know), migrate_brief.json (the gaps, for the agent and the fake agent in tests)."""
    d.mkdir(parents=True, exist_ok=True)
    (d / "data").mkdir(exist_ok=True)
    ds = model.dataset_of(estate, report)
    for t in ds.get("tables") or []:
        if t.get("file") and (source_dir / "data" / t["file"]).exists():
            dst = d / "data" / t["file"]
            if not dst.exists() or dst.stat().st_size != (source_dir / "data" / t["file"]).stat().st_size:
                shutil.copyfile(source_dir / "data" / t["file"], dst)
    (d / "definition.yaml").write_text(dump_yaml(defn), encoding="utf-8")
    brief = {"report": report["name"], "source": estate["source"], "mode": mode, "gaps": plan["gaps"], "unsupported": plan["unsupported"], "filters": plan["filters"],
             "visuals": [{k: v.get(k) for k in ("id", "kind", "type", "chart", "rule", "reason", "title")} for v in plan["visuals"]], "comment": comment,
             "source_queries": [{"name": q["name"], "items": q.get("items"), "filters": q.get("filters")} for q in report.get("queries") or []]}
    (d / "migrate_brief.json").write_text(json.dumps(brief, indent=1, ensure_ascii=False), encoding="utf-8")
    lines = [f"# {report['name']}", "", "## What the user asked for", "",
             f"Convert the {estate['source']['label']} {report['type'].lower()} “{report['name']}” ({report['folder']}) to Power BI with the same numbers. "
             f"definition.yaml was written by Relay's conversion rules from the report's specification; the data in data/ is the {ds['kind']} “{ds['name']}” behind it.", "",
             "## Data (in data/)", ""] + [f"- {t['file']} ({t['name']})" for t in ds.get("tables") or [] if t.get("file")]
    lines += ["", "## Conversion", "", f"- Mode: {mode.replace('_', ' ')}", f"- Calculations by rules: {len(plan['measures']) - plan['ai']} · for the agent: {plan['ai']}",
              f"- Visuals: {plan['summary']['visuals']} on {plan['summary']['pages']} page(s)" + (f" · not converted: {plan['summary']['unsupported']}" if plan["summary"]["unsupported"] else "")]
    if plan["gaps"]:
        lines += ["", "## Calculations and filters without a rule (migrate_brief.json has the detail)", ""]
        for g in plan["gaps"]:
            lines.append(f"- {g.get('item')}: {g['expression']} — {g['reason']}" + (f" → measure [{g['measure']}] is BLANK () until written" if g.get("measure") else ""))
    if plan["unsupported"]:
        lines += ["", "## Not converted (a person decides)", ""] + [f"- {u['what']}: {u['reason']}" for u in plan["unsupported"]]
    if comment:
        lines += ["", "## Review comment", "", comment]
    lines += ["", "## Custom visuals", "", "- Custom visuals: never — use the catalogue only"]
    (d / "request.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
