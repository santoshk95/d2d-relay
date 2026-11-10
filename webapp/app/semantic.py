"""The semantic layer (platform plan, phase 4 + Round 5): what the data means, shared by dashboards and Ask D.

Three layers:
  context    drafted automatically from the data itself (every dashboard's data profile: tables, columns, types,
             examples, likely keys and joins; warehouse tables keyed by their warehouse object); analysts only add
             descriptions and mark sensitive columns
  metrics    per team: one definition per business metric — DAX for Power BI and SQL rendered for each warehouse
             dialect — versioned draft -> in review -> published, approved by another BI Dev / Analyst of the team
             (or an Admin). Published = certified: the badge follows the metric into dashboards and Ask D
  ontology   organisation-wide: entities (Store, Customer, …), their relationships, and how each source identifies
             them (key mappings); suggestions the machine finds — keys that match across sources by their values,
             and the same metric name defined differently by two teams (an Admin sets the organisation default)
"""
import hashlib
import json
import re
import secrets
import time
from pathlib import Path

import duckdb
import sqlglot
import yaml

from . import db, store

WAREHOUSE_DIALECTS = {"duckdb": "DuckDB (prototype)", "snowflake": "Snowflake", "bigquery": "BigQuery", "tsql": "Fabric",
                      "redshift": "Redshift", "athena": "Athena"}
BODY_KEYS = ("label", "description", "dax", "sql", "format", "folder", "synonyms", "grain")


class SemanticError(Exception):
    pass


def _norm_dax(dax: str) -> str:
    """DAX compared without whitespace or quote/case differences in table names."""
    s = re.sub(r"\s+", "", str(dax or ""))
    return re.sub(r"'([^']+)'\[", r"\1[", s).lower()


# ---------------------------------------------------------------- DAX -> SQL for simple metrics

_AGG = {"SUM": "SUM", "AVERAGE": "AVG", "MIN": "MIN", "MAX": "MAX", "DISTINCTCOUNT": "COUNT(DISTINCT", "COUNT": "COUNT"}


def _col(ref: str) -> str:
    m = re.fullmatch(r"\s*'?([^'\[]+?)'?\s*\[([^\]]+)\]\s*", ref)
    if not m:
        raise ValueError(ref)
    return f'"{m.group(1).strip()}"."{m.group(2).strip()}"'


def dax_to_sql(dax: str, measures: dict[str, str] | None = None, depth: int = 0) -> str | None:
    """SQL for the simple, common shapes (SUM / AVERAGE / MIN / MAX / COUNT / DISTINCTCOUNT of a column, COUNTROWS of a
    table, DIVIDE of two of those, + and - of them). None when the DAX needs a person to write the SQL."""
    if depth > 4:
        return None
    s = str(dax or "").strip()
    measures = measures or {}
    for op in ("+", "-"):                 # top-level + and - first, so SUM(a) - SUM(b) is two aggregates
        parts = _split_top(s, op)
        if len(parts) > 1:
            sqls = [dax_to_sql(p, measures, depth + 1) for p in parts]
            return f" {op} ".join(f"({x})" for x in sqls) if all(sqls) else None
    m = re.fullmatch(r"\[([^\]]+)\]", s)
    if m:
        inner = measures.get(m.group(1))
        return dax_to_sql(inner, measures, depth + 1) if inner else None
    m = re.fullmatch(r"(SUM|AVERAGE|MIN|MAX|DISTINCTCOUNT|COUNT)\s*\(\s*(.+?)\s*\)", s, re.I | re.S)
    if m:
        try:
            col = _col(m.group(2))
        except ValueError:
            return None
        fn = _AGG[m.group(1).upper()]
        return f"COUNT(DISTINCT {col})" if fn.startswith("COUNT(DISTINCT") else f"{fn}({col})"
    m = re.fullmatch(r"COUNTROWS\s*\(\s*'?([^'()]+?)'?\s*\)", s, re.I)
    if m:
        return "COUNT(*)"
    m = re.fullmatch(r"DIVIDE\s*\((.+)\)", s, re.I | re.S)
    if m:
        parts = _split_args(m.group(1))
        if len(parts) in (2, 3):
            a, b = dax_to_sql(parts[0], measures, depth + 1), dax_to_sql(parts[1], measures, depth + 1)
            if a and b:
                return f"CAST({a} AS DOUBLE) / NULLIF({b}, 0)"
        return None
    return None


def _split_args(s: str) -> list[str]:
    out, depth, cur, quote = [], 0, "", False
    for ch in s:
        if ch == "'" :
            quote = not quote
        if not quote and ch in "([":
            depth += 1
        elif not quote and ch in ")]":
            depth -= 1
        if ch == "," and depth == 0 and not quote:
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
    return out + ([cur.strip()] if cur.strip() else [])


def _split_top(s: str, op: str) -> list[str]:
    out, depth, cur, quote = [], 0, "", False
    for ch in s:
        if ch == "'":
            quote = not quote
        if not quote and ch in "([":
            depth += 1
        elif not quote and ch in ")]":
            depth -= 1
        if ch == op and depth == 0 and not quote:
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
    out.append(cur.strip())
    return out if all(out) else [s]


def render_sql(sql: str | None) -> dict[str, str]:
    """The metric's SQL (written as DuckDB / ANSI over model tables) in every warehouse's dialect."""
    if not sql:
        return {}
    out = {}
    for d in WAREHOUSE_DIALECTS:
        try:
            out[d] = sqlglot.transpile(f"SELECT {sql}", read="duckdb", write=d)[0][len("SELECT "):]
        except sqlglot.errors.SqlglotError:
            out[d] = None
    return out


# ---------------------------------------------------------------- metrics

def _team_dev(u: dict, team_id: str) -> bool:
    from . import auth
    return auth.is_admin(u) or any(t["id"] == team_id and t["role"] == "dev" for t in u.get("teams", []))


def _clean_body(body: dict) -> dict:
    b = {k: body.get(k) for k in BODY_KEYS if body.get(k) not in (None, "", [])}
    if not b.get("dax"):
        raise SemanticError("A metric needs its DAX definition.")
    if isinstance(b.get("synonyms"), str):
        b["synonyms"] = [x.strip() for x in b["synonyms"].split(",") if x.strip()]
    if not b.get("sql"):
        derived = dax_to_sql(b["dax"])
        if derived:
            b["sql"], b["sql_derived"] = derived, True
    if b.get("sql"):
        try:
            sqlglot.parse_one(f"SELECT {b['sql']}", read="duckdb")
        except sqlglot.errors.ParseError as e:
            raise SemanticError(f"The SQL does not parse: {str(e).splitlines()[0][:200]}") from e
    return b


def _versions(mid: str) -> list[dict]:
    rows = db.q("SELECT * FROM metric_versions WHERE metric_id = ? ORDER BY version", (mid,))
    for r in rows:
        r["body"] = json.loads(r["body"])
    return rows


def metric(mid: str) -> dict:
    m = db.one("SELECT * FROM metrics WHERE id = ?", (mid,))
    if not m:
        raise SemanticError("Unknown metric")
    m["versions"] = _versions(mid)
    pub = [v for v in m["versions"] if v["status"] == "published"]
    m["published"] = pub[-1] if pub else None
    m["open"] = next((v for v in reversed(m["versions"]) if v["status"] in ("draft", "review")), None)
    team = db.one("SELECT name FROM teams WHERE id = ?", (m["team_id"],))
    m["team"] = team["name"] if team else m["team_id"]
    if m["published"]:
        m["published"]["sql_by_dialect"] = render_sql(m["published"]["body"].get("sql"))
    if m["open"]:
        m["open"]["sql_by_dialect"] = render_sql(m["open"]["body"].get("sql"))
    m["used_in"] = used_in(m["name"], m["team_id"])
    m["org_default"] = bool(db.one("SELECT 1 FROM org_defaults WHERE metric_id = ?", (mid,)))
    return m


def metrics(team_ids: list[str] | None = None) -> list[dict]:
    rows = db.q("SELECT * FROM metrics" + (f" WHERE team_id IN ({','.join('?' * len(team_ids))})" if team_ids else "")
                + " ORDER BY lower(name)", tuple(team_ids or ()))
    out = []
    for m in rows:
        vs = _versions(m["id"])
        pub = [v for v in vs if v["status"] == "published"]
        opn = next((v for v in reversed(vs) if v["status"] in ("draft", "review")), None)
        team = db.one("SELECT name FROM teams WHERE id = ?", (m["team_id"],))
        out.append({**m, "team": team["name"] if team else m["team_id"],
                    "published_version": pub[-1]["version"] if pub else None,
                    "label": (pub[-1] if pub else vs[-1])["body"].get("label") if vs else None,
                    "status": "published" if pub and not opn else (opn["status"] if opn else (vs[-1]["status"] if vs else "draft")),
                    "open_status": opn["status"] if opn else None})
    return out


def save_draft(team_id: str, name: str, body: dict, u: dict, source: str | None = None) -> dict:
    """A new draft (a new metric, or the next version of an existing one); an open draft is updated in place."""
    if not _team_dev(u, team_id):
        raise SemanticError("Only BI Devs / Analysts of the team change its metrics.")
    name = name.strip()[:120]
    if not name:
        raise SemanticError("Name the metric.")
    b = _clean_body(body)
    m = db.one("SELECT * FROM metrics WHERE team_id = ? AND lower(name) = lower(?)", (team_id, name))
    if not m:
        mid = "m-" + secrets.token_hex(5)
        db.run("INSERT INTO metrics (id, team_id, name, created, created_by) VALUES (?, ?, ?, ?, ?)", (mid, team_id, name, time.time(), u["id"]))
    else:
        mid = m["id"]
    vs = _versions(mid)
    open_v = next((v for v in vs if v["status"] in ("draft", "review")), None)
    if open_v and open_v["status"] == "review":
        raise SemanticError(f"Version {open_v['version']} is in review; approve or reject it first.")
    if open_v:
        db.run("UPDATE metric_versions SET body = ?, author_id = ?, created = ?, source = COALESCE(?, source) WHERE metric_id = ? AND version = ?",
               (json.dumps(b), u["id"], time.time(), source, mid, open_v["version"]))
        v = open_v["version"]
    else:
        v = (vs[-1]["version"] + 1) if vs else 1
        db.run("INSERT INTO metric_versions (metric_id, version, status, body, author_id, created, source) VALUES (?, ?, 'draft', ?, ?, ?, ?)",
               (mid, v, json.dumps(b), u["id"], time.time(), source))
    db.audit("metric.draft", mid, {"name": name, "version": v, "source": source}, u["id"])
    return metric(mid)


def submit(mid: str, version: int, u: dict) -> dict:
    m = metric(mid)
    if not _team_dev(u, m["team_id"]):
        raise SemanticError("Only BI Devs / Analysts of the team submit its metrics.")
    if not db.run("UPDATE metric_versions SET status = 'review' WHERE metric_id = ? AND version = ? AND status = 'draft'", (mid, version)):
        raise SemanticError("Only a draft can be sent for review.")
    db.audit("metric.submit", mid, {"version": version}, u["id"])
    return metric(mid)


def decide(mid: str, version: int, u: dict, approve: bool, note: str = "") -> dict:
    """Four eyes: a BI Dev / Analyst of the team other than the author approves (an Admin may approve any)."""
    from . import auth
    m = metric(mid)
    v = next((x for x in m["versions"] if x["version"] == version), None)
    if not v or v["status"] != "review":
        raise SemanticError("That version is not in review.")
    if not _team_dev(u, m["team_id"]):
        raise SemanticError("Only BI Devs / Analysts of the team review its metrics.")
    if v["author_id"] == u["id"] and not auth.is_admin(u):
        raise SemanticError("Someone other than the author reviews a metric.")
    if approve:
        db.run("UPDATE metric_versions SET status = 'superseded' WHERE metric_id = ? AND status = 'published'", (mid,))
    db.run("UPDATE metric_versions SET status = ?, reviewer_id = ?, decided = ?, note = ? WHERE metric_id = ? AND version = ?",
           ("published" if approve else "rejected", u["id"], time.time(), note[:1000], mid, version))
    db.audit("metric.approve" if approve else "metric.reject", mid, {"version": version, "note": note[:300]}, u["id"])
    if approve:
        _same_word_suggestions()
    return metric(mid)


def published(team_id: str | None) -> list[dict]:
    """Published metrics a dashboard of this team uses: the team's, plus organisation defaults of other teams for
    names the team has not defined itself."""
    rows = db.q("SELECT m.id, m.name, m.team_id, v.version, v.body FROM metrics m JOIN metric_versions v ON v.metric_id = m.id "
                "WHERE v.status = 'published'")
    out, names = [], set()
    for r in rows:
        r["body"] = json.loads(r["body"])
        if r["team_id"] == team_id:
            out.append(r)
            names.add(r["name"].lower())
    defaults = {d["metric_id"] for d in db.q("SELECT metric_id FROM org_defaults")}
    out += [r for r in rows if r["id"] in defaults and r["team_id"] != team_id and r["name"].lower() not in names]
    return out


def _project_defn(pid: str) -> dict | None:
    d = store.project_dir(pid)
    st = store.load(pid)
    v = st.get("approved") or (st["versions"][-1]["v"] if st.get("versions") else None)
    for f in ([d / "versions" / f"v{v}" / "definition.yaml"] if v else []) + [d / "definition.yaml"]:
        if f.exists():
            try:
                return yaml.safe_load(f.read_text(encoding="utf-8")) or {}
            except yaml.YAMLError:
                return None
    return None


def certification(pid: str) -> dict:
    """measure name -> {status: certified | outdated | differs, metric, version, latest} for the dashboard's measures
    that a published team (or organisation-default) metric names."""
    p = db.project(pid)
    team = p["team_id"] if p else db.DEFAULT_TEAM
    defn = _project_defn(pid) or {}
    pub = {m["name"].lower(): m for m in published(team)}
    old = {}
    for r in db.q("SELECT m.name, m.id, v.version, v.body FROM metrics m JOIN metric_versions v ON v.metric_id = m.id WHERE v.status = 'superseded'"):
        old.setdefault((r["id"], _norm_dax(json.loads(r["body"])["dax"])), r["version"])
    out = {}
    for meas in defn.get("measures") or []:
        m = pub.get(str(meas.get("name", "")).lower())
        if not m:
            continue
        mine = _norm_dax(meas.get("expression"))
        if mine == _norm_dax(m["body"]["dax"]):
            status = "certified"
        elif (m["id"], mine) in old:
            status = "outdated"
        else:
            status = "differs"
        out[meas["name"]] = {"status": status, "metric_id": m["id"], "version": m["version"], "dax": m["body"]["dax"],
                             **({"was_version": old[(m["id"], mine)]} if status == "outdated" else {})}
    return out


def used_in(name: str, team_id: str) -> list[dict]:
    out = []
    for p in db.q("SELECT id FROM projects WHERE team_id = ?", (team_id,)):
        try:
            cert = certification(p["id"])
        except (KeyError, FileNotFoundError, ValueError):
            continue
        hit = next((c for n, c in cert.items() if n.lower() == name.lower()), None)
        if hit:
            out.append({"project": p["id"], "name": store.load(p["id"]).get("name"), "status": hit["status"]})
    return out


def promote(pid: str, names: list[str], u: dict) -> list[dict]:
    """KPIs the person confirmed in a dashboard's plan (and the measures built from them) become draft team metrics,
    sent for review in one step."""
    p = db.project(pid)
    team = (p or {}).get("team_id") or db.DEFAULT_TEAM
    d = store.project_dir(pid)
    plan = {}
    if (d / "plan.yaml").exists():
        plan = yaml.safe_load((d / "plan.yaml").read_text(encoding="utf-8")) or {}
    defn = _project_defn(pid) or {}
    measures = {m["name"]: m for m in defn.get("measures") or []}
    kpis = {k["name"]: k for k in plan.get("kpis") or [] if isinstance(k, dict) and k.get("name")}
    dax_by_name = {n: m.get("expression") for n, m in measures.items()}
    out = []
    for name in names:
        k, meas = kpis.get(name) or {}, measures.get(name) or {}
        dax = meas.get("expression") or k.get("dax")
        if not dax:
            raise SemanticError(f"{name} is not a KPI or measure of this dashboard.")
        body = {"label": k.get("label"), "description": (meas.get("description") or k.get("description") or "").split(" = ")[0],
                "dax": dax, "format": meas.get("format") or k.get("format"), "folder": meas.get("folder"),
                "sql": dax_to_sql(dax, dax_by_name)}
        m = save_draft(team, name, body, u, source=pid)
        out.append(submit(m["id"], m["open"]["version"], u))
    return out


def team_metrics_file(pid: str) -> Path | None:
    """team_metrics.yaml in the project folder: the published metrics the agent must reuse (CLAUDE.md says how)."""
    p = db.project(pid)
    team = (p or {}).get("team_id") or db.DEFAULT_TEAM
    rows = published(team)
    path = store.ROOT / pid / "team_metrics.yaml"
    if not rows:
        path.unlink(missing_ok=True)
        return None
    data = {"note": "Published (certified) metrics of this team. Reuse them exactly — same name, DAX and format — "
                    "whenever the dashboard needs that metric. Do not redefine them.",
            "metrics": [{"name": r["name"], "version": r["version"], **{k: r["body"][k] for k in ("label", "description", "dax", "format", "synonyms")
                                                                       if r["body"].get(k)}} for r in rows]}
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return path


# ---------------------------------------------------------------- business terms

def terms(team_ids: list[str] | None) -> list[dict]:
    rows = db.q("SELECT * FROM terms ORDER BY lower(term)")
    rows = [r for r in rows if r["team_id"] is None or not team_ids or r["team_id"] in team_ids]
    for r in rows:
        r["synonyms"] = json.loads(r["synonyms"])
    return rows


def save_term(body: dict, u: dict, tid: str | None = None) -> dict:
    from . import auth
    team = body.get("team_id") or None
    if team is None and not auth.is_admin(u):
        raise SemanticError("Organisation-wide terms are kept by Admins; pick your team.")
    if team and not _team_dev(u, team):
        raise SemanticError("Only BI Devs / Analysts of the team edit its terms.")
    term, meaning = str(body.get("term", "")).strip()[:120], str(body.get("meaning", "")).strip()[:1000]
    if not term or not meaning:
        raise SemanticError("A term needs a name and what it means.")
    syn = body.get("synonyms") or []
    syn = [s.strip() for s in (syn.split(",") if isinstance(syn, str) else syn) if s.strip()]
    kind = body.get("kind") if body.get("kind") in ("entity", "filter", "value", "time", "term") else "term"
    tid = tid or "tm-" + secrets.token_hex(5)
    db.run("INSERT OR REPLACE INTO terms (id, team_id, term, meaning, synonyms, kind, updated, updated_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
           (tid, team, term, meaning, json.dumps(syn), kind, time.time(), u["id"]))
    db.audit("term.save", tid, {"term": term, "team": team}, u["id"])
    return next(t for t in terms(None) if t["id"] == tid)


def remove_term(tid: str, u: dict) -> None:
    from . import auth
    t = db.one("SELECT * FROM terms WHERE id = ?", (tid,))
    if not t:
        raise SemanticError("Unknown term")
    if not (auth.is_admin(u) or (t["team_id"] and _team_dev(u, t["team_id"]))):
        raise SemanticError("Only the term's team or an Admin removes it.")
    db.run("DELETE FROM terms WHERE id = ?", (tid,))
    db.audit("term.remove", tid, {"term": t["term"]}, u["id"])


# ---------------------------------------------------------------- context engine (from the data profiles)

def _sources_of(pid: str) -> tuple[dict, Path]:
    """file -> source key: a warehouse object for extracts, else <project>/<file>."""
    from . import connectors
    d = store.project_dir(pid)
    man = connectors.manifest(d)
    return {f: (f"{m['kind']}:{m['object']}" if f in man else f"{pid}/{f}") for f in
            [p.name for p in (d / "data").glob("*.csv")] + [p.name for p in (d / "data").glob("*.parquet")]
            for m in [man.get(f, {})]}, d


def context(project_ids: list[str]) -> list[dict]:
    """Tables and columns as the data shows them, merged across dashboards (a warehouse table used by two dashboards
    appears once), with the analysts' notes."""
    notes = {(n["source"], n["tbl"], n["col"]): n for n in db.q("SELECT * FROM context_notes")}
    seen: dict[str, dict] = {}
    for pid in project_ids:
        try:
            sources, d = _sources_of(pid)
            prof = json.loads((d / "profile.json").read_text(encoding="utf-8"))
        except (OSError, ValueError, KeyError):
            continue
        rels = prof.get("relationships") or []
        for t in prof.get("tables") or []:
            src = sources.get(t["file"], f"{pid}/{t['file']}")
            if src in seen:
                seen[src]["used_by"].append(pid)
                continue
            cols = []
            for c in t["columns"]:
                n = notes.get((src, t["view"], c["name"]), {})
                cols.append({**{k: c.get(k) for k in ("name", "type", "distinct", "nulls", "unique", "min", "max")},
                             "samples": (c.get("values") or c.get("examples") or [])[:6],
                             "key": bool(c.get("unique")), "description": n.get("description"), "sensitive": bool(n.get("sensitive")),
                             "origin": n.get("origin") or ("person" if n.get("description") else None), "status": n.get("status") or "confirmed"})
            joins = [r for r in rels if r["many"].startswith(t["file"] + "[") or r["one"].startswith(t["file"] + "[")]
            tn = notes.get((src, t["view"], ""), {})                 # the table's own description (empty column name)
            seen[src] = {"source": src, "table": t["view"], "file": t["file"], "rows": t["rows"], "columns": cols,
                         "joins": joins, "used_by": [pid], "warehouse": not src.startswith(f"{pid}/"),
                         "description": tn.get("description"), "origin": tn.get("origin"), "status": tn.get("status") or "confirmed"}
    return sorted(seen.values(), key=lambda x: x["source"].lower())


def sample_rows(t: dict, cols: list[str], n: int, project_ids: list[str]) -> list[dict]:
    """A few real rows of a context table (the columns asked for), read from a dashboard's data folder."""
    import duckdb
    pid = next((p for p in t.get("used_by") or [] if p in project_ids), None)
    if not pid:
        return []
    f = store.project_dir(pid) / "data" / t["file"]
    if not f.exists() or not cols:
        return []
    src = f"read_parquet('{f}')" if f.suffix == ".parquet" else f"read_csv_auto('{f}', header = true)"
    sel = ", ".join('"' + c.replace('"', '""') + '"' for c in cols)
    con = duckdb.connect()
    try:
        cur = con.execute(f"SELECT DISTINCT {sel} FROM {src} LIMIT {int(n)}")
        names = [d[0] for d in cur.description]
        return [dict(zip(names, [str(v) for v in r])) for r in cur.fetchall()]
    except duckdb.Error:
        return []
    finally:
        con.close()


def save_note(source: str, tbl: str, col: str, description: str, sensitive: bool, u: dict) -> None:
    from . import auth
    if not auth.is_dev(u):
        raise SemanticError("Only BI Devs / Analysts describe columns.")
    db.run("INSERT OR REPLACE INTO context_notes (source, tbl, col, description, sensitive, updated, updated_by, origin, status) "
           "VALUES (?, ?, ?, ?, ?, ?, ?, 'person', 'confirmed')",           # a person's words: never replaced automatically
           (source, tbl, col, description.strip()[:1000], int(bool(sensitive)), time.time(), u["id"]))
    db.audit("context.note", f"{source}/{tbl}/{col}", {"sensitive": bool(sensitive)}, u["id"])


# ---------------------------------------------------------------- organisation ontology

def ontology() -> dict:
    ents = db.q("SELECT * FROM entities ORDER BY lower(name)")
    keys = db.q("SELECT * FROM entity_keys")
    teams = {t["id"]: t["name"] for t in db.q("SELECT id, name FROM teams")}
    for e in ents:
        e["synonyms"] = json.loads(e["synonyms"])
        e["examples"] = json.loads(e.get("examples") or "[]")
        e["keys"] = [k for k in keys if k["entity_id"] == e["id"]]
        e["owner_team"] = teams.get(e["owner_team_id"])
    rels = db.q("SELECT r.from_id, r.verb, r.to_id FROM entity_relations r")
    sugg = db.q("SELECT * FROM suggestions WHERE status = 'open' ORDER BY created")
    for s in sugg:
        s["payload"] = json.loads(s["payload"])
    defaults = db.q("SELECT d.term, d.metric_id, m.team_id, t.name AS team FROM org_defaults d JOIN metrics m ON m.id = d.metric_id "
                    "JOIN teams t ON t.id = m.team_id")
    return {"entities": ents, "relations": rels, "suggestions": sugg, "defaults": defaults}


def _can_entity(u: dict, e: dict | None) -> bool:
    from . import auth
    return auth.is_admin(u) or (e is not None and e.get("owner_team_id") and _team_dev(u, e["owner_team_id"])) or \
        (e is None and auth.is_dev(u))


def save_entity(body: dict, u: dict, eid: str | None = None) -> dict:
    e = db.one("SELECT * FROM entities WHERE id = ?", (eid,)) if eid else None
    if eid and not e:
        raise SemanticError("Unknown entity")
    if not _can_entity(u, e):
        raise SemanticError("Only the owning team's BI Devs / Analysts or an Admin change this entity.")
    name = str(body.get("name") or (e or {}).get("name") or "").strip()[:80]
    if not name:
        raise SemanticError("Name the entity.")
    syn = body.get("synonyms", json.loads(e["synonyms"]) if e else [])
    syn = [s.strip() for s in (syn.split(",") if isinstance(syn, str) else syn) if s.strip()]
    owner = body.get("owner_team_id") or (e or {}).get("owner_team_id") or next((t["id"] for t in u.get("teams", []) if t["role"] == "dev"), None)
    status = body.get("status") if body.get("status") in ("draft", "published") else (e or {}).get("status", "draft")
    eid = eid or "e-" + secrets.token_hex(5)
    definition = str(body["definition"] if "definition" in body else (e or {}).get("definition") or "")[:2000]
    examples = body.get("examples") if "examples" in body else json.loads((e or {}).get("examples") or "[]")
    examples = [str(x).strip()[:300] for x in (examples.split("\n") if isinstance(examples, str) else examples or []) if str(x).strip()][:8]
    try:
        db.run("INSERT OR REPLACE INTO entities (id, name, description, synonyms, owner_team_id, status, created, updated, updated_by, "
               "definition, examples, drafted_by, drafted) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL)",
               (eid, name, str(body.get("description") or (e or {}).get("description") or "")[:1000],
                json.dumps(syn), owner, status, (e or {}).get("created") or time.time(), time.time(), u["id"], definition, json.dumps(examples)))
    except Exception as ex:  # noqa: BLE001 - unique name
        raise SemanticError("An entity with that name exists.") from ex
    for k in body.get("keys") or []:
        db.run("INSERT OR IGNORE INTO entity_keys (entity_id, source, tbl, col) VALUES (?, ?, ?, ?)", (eid, k["source"], k["tbl"], k["col"]))
    db.audit("entity.save", eid, {"name": name, "status": status}, u["id"])
    return next(x for x in ontology()["entities"] if x["id"] == eid)


def remove_entity(eid: str, u: dict) -> None:
    e = db.one("SELECT * FROM entities WHERE id = ?", (eid,))
    if not e or not _can_entity(u, e):
        raise SemanticError("Only the owning team or an Admin removes an entity.")
    for sql in ("DELETE FROM entity_keys WHERE entity_id = ?", "DELETE FROM entity_relations WHERE from_id = ? OR to_id = ?",
                "DELETE FROM entities WHERE id = ?"):
        db.run(sql, (eid, eid) if sql.count("?") == 2 else (eid,))
    db.audit("entity.remove", eid, {"name": e["name"]}, u["id"])


def relate(from_id: str, verb: str, to_id: str, u: dict, remove: bool = False) -> None:
    e = db.one("SELECT * FROM entities WHERE id = ?", (from_id,))
    if not e or not db.one("SELECT 1 FROM entities WHERE id = ?", (to_id,)) or not _can_entity(u, e):
        raise SemanticError("Unknown entity, or not yours to change.")
    verb = verb.strip()[:40] or "relates to"
    db.run("DELETE FROM entity_relations WHERE from_id = ? AND verb = ? AND to_id = ?" if remove else
           "INSERT OR IGNORE INTO entity_relations (from_id, verb, to_id) VALUES (?, ?, ?)", (from_id, verb, to_id))
    db.audit("entity.unrelate" if remove else "entity.relate", from_id, {"verb": verb, "to": to_id}, u["id"])


def _stem(col: str) -> str:
    s = re.sub(r"[^a-z0-9]", "", col.lower())
    return re.sub(r"(id|key|code|no|number|sk)$", "", s) or s


def _suggest(kind: str, fingerprint: str, payload: dict) -> None:
    fp = hashlib.sha256(fingerprint.encode()).hexdigest()[:32]
    db.run("INSERT OR IGNORE INTO suggestions (id, kind, fingerprint, payload, created) VALUES (?, ?, ?, ?, ?)",
           ("s-" + secrets.token_hex(5), kind, fp, json.dumps(payload), time.time()))


def find_key_matches(project_ids: list[str], min_overlap: float = 0.8) -> int:
    """Possible matches: key-like columns in different sources with a similar name whose values overlap (e.g. 87% of
    one side's values found on the other). Each becomes a 'needs a decision' suggestion."""
    ctx = context(project_ids)
    cands = []
    for t in ctx:
        pid = t["used_by"][0]
        path = store.project_dir(pid) / "data" / t["file"]
        for c in t["columns"]:
            if c["type"] in ("int", "string") and (c["key"] or re.search(r"(id|key|code)$", c["name"], re.I)) and c.get("distinct"):
                cands.append((t, c, path))
    found = 0
    con = duckdb.connect()
    reader = lambda p: f"read_parquet('{p}')" if p.suffix == ".parquet" else f"read_csv_auto('{p}', header = true)"  # noqa: E731
    for i, (ta, ca, pa) in enumerate(cands):
        for tb, cb, pb in cands[i + 1:]:
            if ta["source"] == tb["source"] or _stem(ca["name"]) != _stem(cb["name"]) or not _stem(ca["name"]):
                continue
            if bool(ca["key"]) == bool(cb["key"]) and not (ca["key"] and cb["key"]):
                continue                                    # need a unique side, or two keys
            try:
                a = f'SELECT DISTINCT CAST("{ca["name"]}" AS VARCHAR) v FROM {reader(pa)} LIMIT 200000'
                b = f'SELECT DISTINCT CAST("{cb["name"]}" AS VARCHAR) v FROM {reader(pb)} LIMIT 200000'
                n_a, n_b, both = con.execute(f"SELECT (SELECT count(*) FROM ({a})), (SELECT count(*) FROM ({b})), "
                                             f"(SELECT count(*) FROM ({a}) x JOIN ({b}) y USING (v))").fetchone()
            except duckdb.Error:
                continue
            share = both / max(1, min(n_a, n_b))
            if share >= min_overlap:
                name = re.sub(r"(?i)[_ ]?(id|key|code|no|number|sk)$", "", ca["name"]).replace("_", " ").strip().title() or ca["name"]
                pair = sorted([(ta["source"], ta["table"], ca["name"]), (tb["source"], tb["table"], cb["name"])])
                _suggest("key_match", "km|" + json.dumps(pair), {"entity": name, "overlap": round(share, 3), "keys": [
                    {"source": s, "tbl": t, "col": c} for s, t, c in pair]})
                found += 1
    return found


def _same_word_suggestions() -> None:
    rows = db.q("SELECT m.id, m.name, m.team_id, t.name AS team, v.body FROM metrics m JOIN metric_versions v ON v.metric_id = m.id "
                "JOIN teams t ON t.id = m.team_id WHERE v.status = 'published'")
    by: dict[str, list] = {}
    for r in rows:
        by.setdefault(r["name"].lower(), []).append(r)
    decided = {d["term"] for d in db.q("SELECT term FROM org_defaults")}
    for term, rs in by.items():
        if len({r["team_id"] for r in rs}) > 1 and len({_norm_dax(json.loads(r["body"])["dax"]) for r in rs}) > 1 and term not in decided:
            _suggest("same_word", "sw|" + term + "|" + ",".join(sorted(r["id"] for r in rs)),
                     {"term": rs[0]["name"], "options": [{"metric_id": r["id"], "team": r["team"], "dax": json.loads(r["body"])["dax"]} for r in rs]})


def decide_suggestion(sid: str, accept: bool, u: dict, choice: str | None = None) -> dict:
    from . import auth
    s = db.one("SELECT * FROM suggestions WHERE id = ? AND status = 'open'", (sid,))
    if not s:
        raise SemanticError("Unknown or decided suggestion")
    p = json.loads(s["payload"])
    if s["kind"] == "same_word":
        if not auth.is_admin(u):
            raise SemanticError("Admins choose the organisation default.")
        if accept:
            if choice not in [o["metric_id"] for o in p["options"]]:
                raise SemanticError("Choose one of the definitions.")
            db.run("INSERT OR REPLACE INTO org_defaults (term, metric_id, decided_by, decided) VALUES (?, ?, ?, ?)",
                   (p["term"].lower(), choice, u["id"], time.time()))
    elif accept:
        if not auth.is_dev(u):
            raise SemanticError("Only BI Devs / Analysts confirm key matches.")
        e = db.one("SELECT * FROM entities WHERE lower(name) = lower(?)", (p["entity"],))
        save_entity({"name": p["entity"], "keys": p["keys"]}, u, e["id"] if e else None)
    db.run("UPDATE suggestions SET status = ?, decided_by = ?, decided = ? WHERE id = ?",
           ("accepted" if accept else "dismissed", u["id"], time.time(), sid))
    db.audit("suggestion.accept" if accept else "suggestion.dismiss", sid, {"kind": s["kind"], "choice": choice}, u["id"])
    return ontology()


# ---------------------------------------------------------------- possible entities: key matches grouped for one decision each

_IDLIKE = re.compile(r"(?i)(^|[_ ]|[a-z])(id|key|code|no|number|sk|ref)$")


def match_groups(project_ids: list[str]) -> list[dict]:
    """Open key-match suggestions joined into groups: every column connected by matching values is one possible entity
    (Category: the master list dim_category[CategoryKey] and the tables that refer to it). Each group says where it is
    (dashboard names, tables, rows, distinct values, examples), how sure D2D is, and why."""
    sugg = [s for s in db.q("SELECT * FROM suggestions WHERE status = 'open' AND kind = 'key_match' ORDER BY created")]
    if not sugg:
        return []
    parent: dict = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for s in sugg:
        s["payload"] = json.loads(s["payload"])
        ks = [(k["source"], k["tbl"], k["col"]) for k in s["payload"]["keys"]]
        for k in ks[1:]:
            parent[find(k)] = find(ks[0])
    ctx = {t["source"]: t for t in context(project_ids)}
    names = {p["id"]: p.get("name") or p["id"] for p in store.all_projects()}
    owned = {(k["source"], k["tbl"], k["col"]): k["entity_id"] for k in db.q("SELECT * FROM entity_keys")}
    ents = {e["id"]: e["name"] for e in db.q("SELECT id, name FROM entities")}
    by_name = {e["name"].lower(): e["id"] for e in db.q("SELECT id, name FROM entities")}
    groups: dict = {}
    for s in sugg:
        root = find((s["payload"]["keys"][0]["source"], s["payload"]["keys"][0]["tbl"], s["payload"]["keys"][0]["col"]))
        g = groups.setdefault(root, {"ids": [], "names": {}, "overlaps": [], "keys": set()})
        g["ids"].append(s["id"])
        g["names"][s["payload"]["entity"]] = g["names"].get(s["payload"]["entity"], 0) + 1
        g["overlaps"].append(s["payload"]["overlap"])
        g["keys"].update((k["source"], k["tbl"], k["col"]) for k in s["payload"]["keys"])
    out = []
    for root, g in groups.items():
        places, hidden = [], 0
        for src, tbl, col in sorted(g["keys"]):
            t = ctx.get(src)
            if not t:
                hidden += 1
                continue
            c = next((x for x in t["columns"] if x["name"] == col), {})
            master = bool(c.get("key"))
            places.append({"source": src, "dashboard": names.get(src.split("/")[0], src.split("/")[0]) if "/" in src else src,
                           "tbl": tbl, "col": col, "rows": t.get("rows"), "distinct": c.get("distinct"), "type": c.get("type"),
                           "role": "master" if master else "refers", "samples": [str(x) for x in (c.get("samples") or [])[:5]], "min": c.get("min"), "max": c.get("max"),
                           "description": c.get("description"), "table_description": t.get("description"),
                           "entity": ents.get(owned.get((src, tbl, col)))})
        if not places:
            continue
        name = max(g["names"], key=g["names"].get)
        distinct = max((p["distinct"] or 0) for p in places)
        idlike = sum(1 for p in places if _IDLIKE.search(p["col"]))
        dashboards = sorted({p["dashboard"] for p in places})
        tables = {(p["dashboard"], p["tbl"].lower()) for p in places}
        same_table_copies = len({p["tbl"].lower() for p in places}) == 1 and len(dashboards) > 1
        why_low = []
        if not idlike:
            why_low.append("the columns look like labels or settings, not identifiers")
        if distinct and distinct < 4:
            why_low.append(f"only {distinct} distinct values, so a match is likely by chance")
        if same_table_copies:
            why_low.append("it is the same table copied into several dashboards")
        refers = [p for p in places if p["role"] == "refers"]
        masters = [p for p in places if p["role"] == "master"]
        sample = next((p["samples"] for p in masters + places if p["samples"]), [])
        rng = next(([str(p["min"]), str(p["max"])] for p in masters + places if p.get("min") is not None), None)
        existing = next((p["entity"] for p in places if p["entity"]), None) or (ents.get(by_name.get(name.lower())))
        reason = (f"The same {name} values appear in {len(places)} columns" + (f" across {len(dashboards)} dashboards" if len(dashboards) > 1 else "")
                  + (f": {len(masters)} list{'s' if len(masters) > 1 else ''} of {name if name.endswith('s') else name + 's'}" if masters else "")
                  + (f"{' and' if masters else ':'} {len(refers)} table{'s' if len(refers) > 1 else ''} that refer{'' if len(refers) > 1 else 's'} to them" if refers else "")
                  + (". All their values match." if min(g["overlaps"]) >= 0.999 else f". At least {round(min(g['overlaps']) * 100)}% of the values match."))
        out.append({"id": root[0] + "|" + root[1] + "|" + root[2], "name": name, "suggestions": g["ids"], "places": places, "hidden": hidden,
                    "dashboards": dashboards, "tables": len(tables), "match": round(min(g["overlaps"]), 3), "distinct": distinct,
                    "samples": sample, "range": rng, "confidence": "low" if why_low else "high", "why_low": why_low, "reason": reason,
                    "existing": existing})
    out.sort(key=lambda x: (x["confidence"] != "high", -len(x["places"]), x["name"].lower()))
    return out


def decide_group(ids: list[str], accept: bool, u: dict, name: str | None = None) -> int:
    """One decision for a whole group: create (or extend) the entity with every column of it, or dismiss them all."""
    from . import auth
    rows = [r for r in (db.one("SELECT * FROM suggestions WHERE id = ? AND status = 'open' AND kind = 'key_match'", (i,)) for i in ids) if r]
    if not rows:
        raise SemanticError("Nothing left to decide; reload the page.")
    if not auth.is_dev(u):
        raise SemanticError("Only BI Devs / Analysts decide key matches.")
    if accept:
        keys = {(k["source"], k["tbl"], k["col"]) for r in rows for k in json.loads(r["payload"])["keys"]}
        name = (name or json.loads(rows[0]["payload"])["entity"]).strip()[:80]
        if not name:
            raise SemanticError("Give the entity a name.")
        e = db.one("SELECT * FROM entities WHERE lower(name) = lower(?)", (name,))
        save_entity({"name": e["name"] if e else name, "keys": [{"source": s, "tbl": t, "col": c} for s, t, c in sorted(keys)]}, u, e["id"] if e else None)
    for r in rows:
        db.run("UPDATE suggestions SET status = ?, decided_by = ?, decided = ? WHERE id = ?",
               ("accepted" if accept else "dismissed", u["id"], time.time(), r["id"]))
    db.audit("suggestion.group_accept" if accept else "suggestion.group_dismiss", rows[0]["id"], {"suggestions": len(rows), "name": name}, u["id"])
    return len(rows)
