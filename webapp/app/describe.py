"""Descriptions for the semantic layer: what tables, columns and ontology entities mean in the business.

Where a description comes from, best first:
  person     typed or accepted by a BI Dev / Analyst (never overwritten automatically)
  warehouse  the source's own column / table comment, read when a table is extracted (refreshed on every extract)
  ai         drafted by the model from names, types, real sample values, joins and the other descriptions; it stays
             "suggested" until a person accepts or edits it, and Ask D is told it is unconfirmed
Table-level descriptions are stored with an empty column name. Entities get a business definition and examples the
same way (drafted_by = 'ai' until a person saves the entity), plus live examples read from the data.
"""
import json
import time

from . import auth, db, semantic, store

DRAFT_SYSTEM = """You document data for a business intelligence platform. Write for business users, not engineers:
plain words, what the thing means in the business and how it is used, never invent facts the data does not support.
Reply with exactly one JSON object and nothing else."""


class DescribeError(Exception):
    pass


def _note(source: str, tbl: str, col: str) -> dict | None:
    return db.one("SELECT * FROM context_notes WHERE source = ? AND tbl = ? AND col = ?", (source, tbl, col))


def _put(source: str, tbl: str, col: str, text: str, origin: str, status: str, who: str | None) -> bool:
    """Store unless a better description exists: a person's is never replaced; the warehouse replaces AI drafts."""
    old = _note(source, tbl, col)
    if old and old.get("description") and old.get("origin", "person") == "person" and origin != "person":
        return False
    if old and old.get("description") and old.get("origin") == "warehouse" and origin == "ai":
        return False
    db.run("INSERT OR REPLACE INTO context_notes (source, tbl, col, description, sensitive, updated, updated_by, origin, status) "
           "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (source, tbl, col, text.strip()[:1000], (old or {}).get("sensitive") or 0, time.time(), who, origin, status))
    return True


# ---------------------------------------------------------------- the warehouse's own comments

def store_source_comments(source: str, tbl: str, comments: dict[str, str], who: str | None) -> int:
    """`comments`: {"": table comment, column: comment}. Called after an extract."""
    n = 0
    for col, text in comments.items():
        if text and str(text).strip():
            n += _put(source, tbl, col, str(text), "warehouse", "confirmed", who or "system")
    if n:
        db.audit("context.warehouse_comments", f"{source}/{tbl}", {"descriptions": n}, who or "system")
    return n


# ---------------------------------------------------------------- AI drafts for a table's missing descriptions

def _table(source: str, project_ids: list[str]) -> dict:
    t = next((x for x in semantic.context(project_ids) if x["source"] == source), None)
    if not t:
        raise DescribeError("Unknown table, or not one you can open.")
    return t


async def draft_table(u: dict, source: str, project_ids: list[str], include_all: bool = False) -> dict:
    """Draft the table description and every column description that is still missing."""
    from . import askd
    if not auth.is_dev(u):
        raise DescribeError("Only BI Devs / Analysts draft descriptions.")
    t = _table(source, project_ids)
    missing = [c for c in t["columns"] if include_all or not c.get("description")]
    if not missing and t.get("description") and not include_all:
        return {"drafted": 0, "table": t}
    others = [x for x in semantic.context(project_ids) if x["source"] != source][:20]
    lines = [f"Table `{t['table']}` (source {t['source']}, {t.get('rows') or 0:,} rows). Current table description: {t.get('description') or '(none)'}",
             "Columns (name - type - distinct values - blanks - examples - existing description):"]
    for c in t["columns"]:
        lines.append(f"- {c['name']} - {c['type']} - {c.get('distinct')} distinct - {c.get('nulls') or 0} blank - "
                     f"e.g. {', '.join(map(str, (c.get('samples') or [])[:6]))}" + (f" - values range from {c.get('min')} (lowest) to {c.get('max')} (highest)" if c.get("min") is not None else "")
                     + (f" - described: {c['description']}" if c.get("description") else "") + (" - SENSITIVE: do not repeat its values" if c.get("sensitive") else ""))
    if t.get("joins"):
        lines.append("Joins: " + "; ".join(f"{j['many']} {j['one']}" for j in t["joins"]))
    if others:
        lines.append("Other tables in the same data: " + ", ".join(f"{o['table']}" + (f" ({o['description']})" if o.get("description") else "") for o in others))
    want = [c["name"] for c in missing]
    prompt = ("\n".join(lines) + "\n\nWrite a business description (one or two sentences) for the table, and for each of these columns: "
              + ", ".join(want) + ". For each column say what it means in the business, its unit or format when clear (currency, %, date, code), "
              "and for codes or IDs what they identify. State only what the names and values show: do not claim how a number was "
              "calculated (discounts, costs, taxes) unless the data makes it clear, and say \"likely\" when you infer. Reply as JSON: {\"table\": \"...\", \"columns\": {\"<column>\": \"...\"}}")
    out = await askd.ask_json(u, DRAFT_SYSTEM, prompt, "describe")
    cols = out.get("columns") if isinstance(out.get("columns"), dict) else {}
    n = 0
    if isinstance(out.get("table"), str) and (include_all or not t.get("description")):
        n += _put(source, t["table"], "", out["table"], "ai", "suggested", u["id"])
    for c in want:
        if isinstance(cols.get(c), str) and cols[c].strip():
            n += _put(source, t["table"], c, cols[c], "ai", "suggested", u["id"])
    db.audit("context.ai_draft", f"{source}/{t['table']}", {"drafted": n}, u["id"])
    return {"drafted": n, "table": _table(source, project_ids)}


def accept(source: str, tbl: str, cols: list[str], u: dict) -> int:
    """A person confirms AI drafts as they are (editing one saves it as theirs)."""
    if not auth.is_dev(u):
        raise DescribeError("Only BI Devs / Analysts confirm descriptions.")
    n = 0
    for col in cols:
        n += db.run("UPDATE context_notes SET status = 'confirmed', updated = ?, updated_by = ? WHERE source = ? AND tbl = ? AND col = ? AND status = 'suggested'",
                    (time.time(), u["id"], source, tbl, col))
    db.audit("context.accept", f"{source}/{tbl}", {"columns": cols}, u["id"])
    return n


# ---------------------------------------------------------------- entities: definition, examples, where they are used

def _entity(eid: str) -> dict:
    e = next((x for x in semantic.ontology()["entities"] if x["id"] == eid), None)
    if not e:
        raise DescribeError("Unknown entity.")
    return e


def details(eid: str, u: dict, project_ids: list[str]) -> dict:
    """Everything about an entity: definition, examples (written and from the data), where it lives, relations,
    which dashboards and certified metrics use it."""
    e = _entity(eid)
    o = semantic.ontology()
    names = {x["id"]: x["name"] for x in o["entities"]}
    ctx = {t["source"]: t for t in semantic.context(project_ids)}
    where, live = [], []
    for k in e["keys"]:
        t = ctx.get(k["source"])
        if not t:
            where.append({**k, "visible": False})
            continue
        col = next((c for c in t["columns"] if c["name"] == k["col"]), {})
        texts = [c for c in t["columns"] if c["name"] != k["col"] and c["type"] == "string" and not c.get("sensitive")]
        label = next((c for c in texts if not c.get("key") and not c["name"].lower().endswith(("_id", "id", "_no", "_code"))), texts[0] if texts else None)
        where.append({**k, "visible": True, "table_description": t.get("description"), "column_description": col.get("description"),
                      "rows": t.get("rows"), "distinct": col.get("distinct"), "label_column": label["name"] if label else None})
        # live examples: the key's real values, next to a readable column of the same table when there is one
        rows = semantic.sample_rows(t, [k["col"]] + ([label["name"]] if label else []), 4, project_ids)
        live += [{"source": k["source"], "table": t["table"], "values": r} for r in rows]
    used_in = sorted({pid for k in e["keys"] for pid in (ctx.get(k["source"]) or {}).get("used_by", [])})
    proj_names = {p["id"]: p.get("name") for p in store.all_projects()}
    tables = {k["tbl"].lower() for k in e["keys"]}
    pub = [m for t in db.q("SELECT id, name FROM teams") for m in semantic.published(t["id"])]
    team_names = {t["id"]: t["name"] for t in db.q("SELECT id, name FROM teams")}
    metrics = [{"name": m["name"], "team": team_names.get(m.get("team_id"), m.get("team_id")), "dax": m["body"].get("dax")} for m in pub
               if any(t in str(m["body"].get("dax", "")).lower() for t in tables)][:12]
    return {**e, "examples": e.get("examples") or [], "where": where, "live_examples": live[:16],
            "relations": [{"verb": r["verb"], "to": names.get(r["to_id"]), "to_id": r["to_id"], "direction": "out"} for r in o["relations"] if r["from_id"] == eid]
            + [{"verb": r["verb"], "to": names.get(r["from_id"]), "to_id": r["from_id"], "direction": "in"} for r in o["relations"] if r["to_id"] == eid],
            "used_in": [{"id": p, "name": proj_names.get(p, p)} for p in used_in], "metrics": metrics,
            "can_edit": semantic._can_entity(u, e)}                      # noqa: SLF001


async def draft_entity(u: dict, eid: str, project_ids: list[str]) -> dict:
    """Draft the business definition, examples and other names of an entity from where it lives in the data."""
    from . import askd
    e = _entity(eid)
    if not semantic._can_entity(u, e):                                  # noqa: SLF001
        raise DescribeError("Only the owning team's BI Devs / Analysts or an Admin change this entity.")
    d = details(eid, u, project_ids)
    lines = [f"Entity: {e['name']}" + (f" (also called {', '.join(e['synonyms'])})" if e["synonyms"] else ""),
             f"Current meaning: {e.get('description') or '(none)'}", "Where it lives in the data:"]
    for w in d["where"]:
        if w.get("visible"):
            lines.append(f"- {w['source']} > {w['tbl']}[{w['col']}] - {w.get('rows') or 0:,} rows, {w.get('distinct')} distinct"
                         + (f" - table: {w['table_description']}" if w.get("table_description") else "")
                         + (f" - column: {w['column_description']}" if w.get("column_description") else ""))
    if d["live_examples"]:
        lines.append("Real records: " + "; ".join(", ".join(f"{k}={v}" for k, v in x["values"].items()) for x in d["live_examples"][:6]))
    if d["relations"]:
        lines.append("Relationships: " + "; ".join(f"{e['name']} {r['verb']} {r['to']}" if r["direction"] == "out" else f"{r['to']} {r['verb']} {e['name']}" for r in d["relations"]))
    if d["metrics"]:
        lines.append("Certified metrics using it: " + ", ".join(m["name"] for m in d["metrics"]))
    prompt = ("\n".join(lines) + "\n\nWrite: (1) `meaning`: one short line; (2) `definition`: 2-4 sentences on what this is in the business, "
              "how it is identified, and what it is used for in decisions; (3) `examples`: 3 concrete examples written for a business reader, "
              "built from the real records above (no invented values); (4) `synonyms`: other names people use. "
              "Reply as JSON: {\"meaning\": \"...\", \"definition\": \"...\", \"examples\": [\"...\"], \"synonyms\": [\"...\"]}")
    out = await askd.ask_json(u, DRAFT_SYSTEM, prompt, "describe")
    defin = str(out.get("definition") or "").strip()[:2000]
    if not defin:
        raise DescribeError("The model did not return a definition; try again.")
    ex = [str(x).strip()[:300] for x in (out.get("examples") or []) if str(x).strip()][:5]
    syn = list(dict.fromkeys(e["synonyms"] + [str(x).strip() for x in (out.get("synonyms") or []) if str(x).strip()]))[:12]
    db.run("UPDATE entities SET definition = ?, examples = ?, description = COALESCE(NULLIF(description, ''), ?), synonyms = ?, drafted_by = 'ai', drafted = ?, "
           "updated = ? WHERE id = ?", (defin, json.dumps(ex), str(out.get("meaning") or "")[:300], json.dumps(syn), time.time(), time.time(), eid))
    db.audit("entity.ai_draft", eid, {"examples": len(ex)}, u["id"])
    return details(eid, u, project_ids)
