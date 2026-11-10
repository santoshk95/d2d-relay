"""Ask D (platform plan, phase 5 + Round 5): questions about your data, answered with the numbers, a summary, next
actions and follow-up questions — every step checked.

Three scopes:
  dashboard  one dashboard: its model (tables, measures, relationships), its pages, the filters the person set, on
             the dashboard's extract (DuckDB over its data folder, the same views as the prototype)
  team       the dashboards of the person's teams they can open, plus their own warehouse connections (live)
  org        every dashboard they can open + their own connections, guided by the organisation ontology and
             organisation-default metrics; sources the ontology knows but the person cannot open are listed as
             "not included" — data is always fetched with the person's own permissions, never anyone else's

How an answer is made: Claude (the person's own AI provider, the agent's chat lane, no tools at all) gets a context
pack and replies with JSON: either a query for one of the listed engines, or the answer. The web app — never
Claude — checks each query (one read-only SELECT, only the listed tables, no file functions), runs it with the
person's permissions and hands back the rows. At most MAX_QUERIES rounds. Every number in an answer comes from a
query result; the answer shows the SQL, where it ran, the checks, and whether it used certified metrics.
"""
import hashlib
import json
import re
import secrets
import threading
import time
from pathlib import Path

import duckdb
import httpx
import sqlglot
import yaml
from sqlglot import exp

from . import auth, connectors, db, instances, providers, semantic, store
from . import usage as costs

MAX_QUERIES = 4
PREVIEW_ROWS = 50
EXTRACT_TIMEOUT_S = 60
CACHE_LIVE_S = 3600
FILE_FUNCS = re.compile(r"^(read_|scan_|parquet_|glob$|getenv$|query$|query_table$|sniff_csv$|duckdb_|pragma_|iceberg_|delta_)", re.I)

SYSTEM = """You are Ask Relay, the data assistant of D2D Relay. You answer business questions with numbers from the person's
own data, then explain them in plain language and suggest what to do next.

You cannot run anything yourself. Reply with exactly ONE JSON object and nothing else — no prose, no code fence:
  {"action": "query", "engine": "<engine id from the context>", "sql": "<one read-only SELECT>", "why": "<short>"}
    The app runs it with the person's permissions and returns up to 50 rows as JSON. Use the engine's SQL dialect
    and only the tables listed for that engine (DuckDB engines: the exact view names, quoted with double quotes).
  {"action": "answer", "query": "<id of the query the main result comes from, e.g. q2>",
   "result": {"type": "number" | "table" | "chart", "headline": "<the key number or finding, short>",
              "chart": {"kind": "bar" | "line", "x": "<column>", "y": ["<column>"]}},
   "summary": "<2-4 sentences, grounded in the numbers>",
   "actions": ["<suggestion or next course of action>", "<another>"],
   "next_questions": ["<follow-up question>", "<another>", "<a third>"],
   "metrics_used": ["<names of certified metrics whose definition you used>"],
   "not_included": ["<data the question needed that is not available here>"]}
Rules: never invent a number — every number in the answer must come from a query result. Prefer the certified
metrics' definitions (DAX for meaning, SQL for the query) whenever the question is about them, and list them in
metrics_used. At most 3 queries before answering. Keep result rows small (aggregate; LIMIT 50). If the data cannot
answer the question, say so in the summary and in not_included.
Write for a business reader: headline, summary, actions and next_questions use business words, never SQL, table or
column names (say "revenue", not "net_rev_amt"); round sensibly ($1.42M, 32.9%); keep the summary to 2-4 short sentences.
Actions are concrete things a manager could do this week. Next questions are ones a manager would naturally ask next.
D2D Relay has no certified metrics: never mention certified metrics or their absence; leave metrics_used empty.
Use not_included only for data the question needed that is missing, never for a note about definitions."""


class AskError(Exception):
    pass


# ---------------------------------------------------------------- engines

def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _project_defn(pid: str) -> dict:
    return semantic._project_defn(pid) or {}            # noqa: SLF001 - the approved (else latest) definition


def _extract_engine(pids: list[str], combined: bool) -> tuple[duckdb.DuckDBPyConnection, dict]:
    """DuckDB with read-only views over dashboards' data folders. One dashboard: its model views (as the prototype)
    and raw views. Several: one schema per dashboard with its raw views."""
    from genbi_kit import data as data_mod
    tables: dict[str, list[str]] = {}
    if not combined:
        pid = pids[0]
        d = store.project_dir(pid)
        defn = _project_defn(pid)
        try:
            from genbi_kit import definition as definition_mod
            expanded = definition_mod.expand(defn) if defn.get("tables") else None
        except Exception:  # noqa: BLE001 - an unfinished definition: raw views only
            expanded = None
        con = data_mod.connect(d, expanded)
    else:
        con = duckdb.connect()
        con.execute("SET autoinstall_known_extensions = false")
        con.execute("SET autoload_known_extensions = false")
        for pid in pids:
            d = store.project_dir(pid)
            schema = "p_" + re.sub(r"[^a-z0-9]", "_", pid.lower())
            con.execute(f"CREATE SCHEMA IF NOT EXISTS {_q(schema)}")
            for f in sorted(list((d / "data").glob("*.csv")) + list((d / "data").glob("*.parquet"))):
                src = f"read_parquet('{f}')" if f.suffix == ".parquet" else f"read_csv_auto('{f}', header = true)"
                try:
                    con.execute(f"CREATE OR REPLACE VIEW {_q(schema)}.{_q(data_mod.raw_name(f))} AS SELECT * FROM {src}")
                except duckdb.Error:
                    continue
    for schema, name in con.execute("SELECT schema_name, view_name FROM duckdb_views() WHERE NOT internal").fetchall():
        key = name if schema == "main" else f"{schema}.{name}"
        try:
            cols = [r[0] for r in con.execute(f"DESCRIBE {_q(schema)}.{_q(name)}").fetchall()]
        except duckdb.Error:
            continue
        tables[key] = cols
    return con, tables


def guard_duckdb(sql: str, allowed: set[str], limit: int) -> tuple[str, list[str], list[str]]:
    """One read-only SELECT over the listed views only, no table functions that read files or settings.
    Returns (sql with row limit, tables used, columns used)."""
    try:
        trees = [t for t in sqlglot.parse(sql, read="duckdb") if t is not None]
    except sqlglot.errors.ParseError as e:
        raise AskError(f"The SQL does not parse: {str(e).splitlines()[0][:200]}") from e
    if len(trees) != 1 or not isinstance(trees[0], (exp.Select, exp.Union, exp.Except, exp.Intersect, exp.Subquery)):
        raise AskError("Only one SELECT is allowed.")
    tree = trees[0]
    ctes = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}
    used, low = [], {a.lower(): a for a in allowed}
    for node in tree.walk():
        if isinstance(node, connectors.BLOCKED):
            raise AskError(f"{type(node).__name__} is not allowed: queries are read-only.")
        if isinstance(node, exp.Func):
            name = node.name if isinstance(node, exp.Anonymous) else node.sql_name()
            if FILE_FUNCS.match(str(name)) or type(node).__name__ in ("ReadCSV", "ReadParquet"):
                raise AskError(f"{name}() is not allowed: use the listed tables.")
        if isinstance(node, exp.Table):
            if not isinstance(node.this, exp.Identifier):
                raise AskError("Table functions are not allowed: use the listed tables.")
            full = ".".join(p for p in (node.db, node.name) if p).lower()
            if full in ctes or node.name.lower() in ctes:
                continue
            if full not in low:
                raise AskError(f"{full} is not one of the tables you can use here.")
            used.append(low[full])
    cols = sorted({c.name for c in tree.find_all(exp.Column) if c.name})
    wrapped = exp.select("*").from_(tree.subquery("d2d_q")).limit(limit).sql(dialect="duckdb")
    return wrapped, sorted(set(used)), cols


def _run_duckdb(con, sql: str, timeout: int) -> tuple[list[str], list[dict]]:
    timer = threading.Timer(timeout, con.interrupt)
    timer.start()
    try:
        cur = con.execute(sql)
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    except duckdb.InterruptException as e:
        raise AskError(f"The query took longer than {timeout}s.") from e
    except duckdb.Error as e:
        raise AskError(f"DuckDB: {str(e).splitlines()[0][:300]}") from e
    finally:
        timer.cancel()
    return cols, rows


def _live_tables(c: dict) -> dict[str, list[str]]:
    """Configured tables of a connection, with their columns (from the extract when there is one)."""
    out = {}
    for t in db.q("SELECT object, alias FROM connection_tables WHERE connection_id = ?", (c["id"],)):
        cols = []
        for p in db.q("SELECT id FROM projects"):
            try:
                m = connectors.manifest(store.project_dir(p["id"])).get(t["alias"] + ".parquet")
            except KeyError:
                continue
            if m and m.get("object") == t["object"]:
                import pyarrow.parquet as pq
                cols = pq.read_schema(store.project_dir(p["id"]) / "data" / (t["alias"] + ".parquet")).names
                break
        out[t["object"]] = cols
    return out


def _guard_live(c: dict, sql: str) -> tuple[list[str], list[str]]:
    """Only the connection's configured tables (connectors.query adds the read-only and limit checks)."""
    dialect = connectors.KINDS[c["kind"]]["dialect"]
    try:
        tree = sqlglot.parse_one(sql, read=dialect)
    except sqlglot.errors.ParseError as e:
        raise AskError(f"The SQL does not parse as {connectors.KINDS[c['kind']]['label']} SQL: {str(e).splitlines()[0][:200]}") from e
    allowed = {o.lower(): o for o in _live_tables(c)}
    ctes = {x.alias_or_name.lower() for x in tree.find_all(exp.CTE)}
    used = []
    for t in tree.find_all(exp.Table):
        full = ".".join(p for p in (t.catalog, t.db, t.name) if p).lower()
        if t.name.lower() in ctes:
            continue
        match = allowed.get(full) or next((v for k, v in allowed.items() if k.endswith("." + full) or k == full), None)
        if not match:
            raise AskError(f"{full} is not one of the tables configured on {c['name']}.")
        used.append(match)
    return sorted(set(used)), sorted({col.name for col in tree.find_all(exp.Column) if col.name})


# ---------------------------------------------------------------- scope -> what the person may use

def scope_sources(u: dict, scope: dict) -> dict:
    kind = scope.get("kind", "team")
    all_ids = [p["id"] for p in store.dashboards()]
    access = auth.access_map(u, all_ids)
    if kind == "dashboard":
        pid = scope.get("project")
        if pid not in access:
            raise AskError("You cannot open that dashboard.")
        return {"kind": kind, "projects": [pid], "connections": [], "team_id": (db.project(pid) or {}).get("team_id")}
    my_teams = {t["id"] for t in u.get("teams", [])}
    if kind == "team":
        pids = [p for p, a in access.items() if a.get("team_id") in my_teams or a["access"] == "owner" and a["via"] == "owner"]
    else:
        pids = list(access)
    conns = db.q("SELECT id FROM connections WHERE owner_id = ?", (u["id"],))
    return {"kind": kind, "projects": sorted(pids), "connections": [c["id"] for c in conns],
            "team_id": next(iter(my_teams), db.DEFAULT_TEAM)}


def _not_included(u: dict, src: dict) -> list[str]:
    """Organisation scope: sources the ontology maps that this person cannot open (named, never read)."""
    if src["kind"] != "org":
        return []
    mine = set()
    for pid in src["projects"]:
        try:
            files, _ = semantic._sources_of(pid)     # noqa: SLF001
            mine |= set(files.values())
        except (KeyError, OSError):
            continue
    for cid in src["connections"]:
        c = connectors._row(cid)                     # noqa: SLF001
        mine |= {f"{c['kind']}:{t['object']}" for t in db.q("SELECT object FROM connection_tables WHERE connection_id = ?", (cid,))}
    out = []
    for e in semantic.ontology()["entities"]:
        for k in e["keys"]:
            if k["source"] not in mine:
                out.append(f"{e['name']}: {k['source']} › {k['tbl']} (you have no access)")
    return sorted(set(out))


def context_pack(u: dict, scope: dict) -> tuple[str, dict]:
    """The text Claude gets, and the engines the app will run queries on."""
    src = scope_sources(u, scope)
    engines: dict[str, dict] = {}
    parts = [f"Scope: {src['kind']}" + (f" — dashboard {store.load(src['projects'][0]).get('name')}" if src["kind"] == "dashboard" else "")]
    if src["projects"]:
        combined = src["kind"] != "dashboard"
        eid = "extract" if combined else f"dashboard:{src['projects'][0]}"
        con, tables = _extract_engine(src["projects"], combined)
        engines[eid] = {"kind": "extract", "con": con, "tables": tables, "projects": src["projects"]}
        names = {p: store.load(p).get("name") for p in src["projects"]}
        parts.append(f"\n## Engine `{eid}` — DuckDB over " + ("the dashboard's data (the same views as the prototype)" if not combined else
                     "the data of the dashboards you can open (one schema per dashboard: " + ", ".join(f"p_{re.sub(r'[^a-z0-9]', '_', p.lower())} = {names[p]}" for p in src["projects"]) + ")"))
        for t, cols in sorted(tables.items())[:120]:
            parts.append(f"- {t}: {', '.join(cols[:40])}")
    for cid in src["connections"]:
        c = connectors._row(cid)                     # noqa: SLF001
        if not (connectors.KINDS.get(c["kind"]) or {}).get("dialect"):
            continue                                 # an API platform (Oracle Retail MFCS …): asked about through the dashboards its objects were pulled into
        tbls = _live_tables(c)
        if not tbls:
            continue
        engines[f"live:{cid}"] = {"kind": "live", "connection": c, "tables": tbls}
        parts.append(f"\n## Engine `live:{cid}` — {connectors.KINDS[c['kind']]['label']} ({c['name']}), live, "
                     f"{connectors.KINDS[c['kind']]['dialect']} SQL, your own login")
        for obj, cols in tbls.items():
            parts.append(f"- {obj}: {', '.join(cols[:40]) or '(columns: query with LIMIT 1 to see them)'}")
    if not engines:
        raise AskError("There is no data you can ask about here yet: open a dashboard, or connect a warehouse and choose tables.")
    if src["kind"] == "dashboard":
        pid = src["projects"][0]
        defn = _project_defn(pid)
        parts.append("\n## The dashboard's model")
        for m in defn.get("measures") or []:
            parts.append(f"- measure [{m['name']}] = {m.get('expression')}" + (f" — {m['description']}" if m.get("description") else ""))
        for r in defn.get("relationships") or []:
            parts.append(f"- relationship {r}")
        pages = [p.get("name") for p in defn.get("pages") or []]
        if pages:
            parts.append("- pages: " + ", ".join(pages) + (f" (the person is on: {scope['page']})" if scope.get("page") else ""))
        if scope.get("filters"):
            parts.append("- filters the person set (apply them): " + "; ".join(f"{k} = {v}" for k, v in scope["filters"].items()))
        if scope.get("selection"):
            parts.append(f"- the person selected: {scope['selection']}")
    pub = semantic.published(src.get("team_id")) if src["kind"] != "org" else \
        [m for m in semantic.published(src.get("team_id"))] + [m for t in db.q("SELECT id FROM teams") for m in semantic.published(t["id"])]
    seen, metrics = set(), []
    for m in pub:
        if m["id"] in seen:
            continue
        seen.add(m["id"])
        metrics.append(m)
    if metrics:
        parts.append("\n## Certified metrics (prefer these definitions)")
        for m in metrics[:60]:
            b = m["body"]
            parts.append(f"- {m['name']} (v{m['version']}): {b.get('description', '')} DAX: {b['dax']}" + (f" SQL: {b['sql']}" if b.get("sql") else ""))
    if src["projects"]:                                   # what tables and columns mean (people, warehouse comments, AI drafts)
        described = []
        for t in semantic.context(src["projects"])[:40]:
            cols = [f"{c['name']}: {c['description']}" + (" (unconfirmed)" if c.get("status") == "suggested" else "") + (" [sensitive]" if c.get("sensitive") else "")
                    for c in t["columns"] if c.get("description")]
            if t.get("description") or cols:
                described.append(f"- {t['table']}" + (f" — {t['description']}" if t.get("description") else "") + (": " + "; ".join(cols[:30]) if cols else ""))
        if described:
            parts.append("\n## What the data means (descriptions; 'unconfirmed' ones are AI drafts)")
            parts += described
    terms = semantic.terms(list({t["id"] for t in u.get("teams", [])}))
    if terms:
        parts.append("\n## Business terms")
        parts += [f"- {t['term']}: {t['meaning']}" + (f" (also: {', '.join(t['synonyms'])})" if t["synonyms"] else "") for t in terms[:60]]
    if src["kind"] == "org":
        onto = semantic.ontology()
        if onto["entities"]:
            parts.append("\n## Organisation ontology (entities and where they live)")
            for e in onto["entities"]:
                parts.append(f"- {e['name']}: " + "; ".join(f"{k['source']} › {k['tbl']}[{k['col']}]" for k in e["keys"])
                             + (f" — {e.get('definition') or e.get('description')}" if (e.get("definition") or e.get("description")) else ""))
        defaults = onto["defaults"]
        if defaults:
            parts.append("- organisation defaults: " + ", ".join(f"{d['term']} = {d['team']}'s definition" for d in defaults))
    elif src["projects"]:                                   # a dashboard: the entities that live in its own data
        mine = [e for e in semantic.ontology()["entities"] if any(str(k["source"]).split("/")[0] in src["projects"] for k in e["keys"])]
        if mine:
            parts.append("\n## Business entities in this data")
            parts += [f"- {e['name']}: " + ", ".join(f"{k['tbl']}[{k['col']}]" for k in e["keys"] if str(k["source"]).split("/")[0] in src["projects"])
                      + (f" — {e.get('definition') or e.get('description')}" if (e.get("definition") or e.get("description")) else "")
                      + (f" (e.g. {'; '.join(e['examples'][:2])})" if e.get("examples") else "") for e in mine[:40]]
    ni = _not_included(u, src)
    if ni:
        parts.append("\n## Known to the organisation but not available to this person (mention if relevant, never guess)")
        parts += [f"- {x}" for x in ni[:40]]
    return "\n".join(parts), {"engines": engines, "metrics": {m["name"].lower(): m for m in metrics}, "not_included": ni, "sources": src}


def run_query(engines: dict, engine: str, sql: str, u: dict) -> dict:
    e = engines.get(engine)
    if not e:
        raise AskError(f"Unknown engine {engine}.")
    g = connectors.guardrails()
    started = time.time()
    if e["kind"] == "extract":
        safe, tables, cols = guard_duckdb(sql, set(e["tables"]), g["row_limit"])
        columns, rows = _run_duckdb(e["con"], safe, min(EXTRACT_TIMEOUT_S, g["timeout_s"]))
        return {"engine": engine, "where": "extract", "sql": sql, "sql_run": safe, "columns": columns, "rows": rows,
                "row_count": len(rows), "limited": len(rows) >= g["row_limit"], "tables": tables, "columns_used": cols,
                "seconds": round(time.time() - started, 2), "checks": ["parses as one SELECT", "only tables you can use",
                                                                       "no file or setting functions", f"row limit {g['row_limit']:,}"]}
    c = e["connection"]
    tables, cols = _guard_live(c, sql)
    r = connectors.query(c, sql, u["id"])
    checks = ["parses as one read-only SELECT", "only your configured tables", f"row limit {g['row_limit']:,}", f"timeout {g['timeout_s']}s"]
    if r.get("bytes_estimate") is not None:
        checks.append(f"dry run {r['bytes_estimate'] / 1e6:.1f} MB (limit {g['bigquery_max_gb']:g} GB)")
    return {"engine": engine, "where": "live", "sql": sql, "sql_run": r["sql"], "columns": r["columns"], "rows": r["rows"],
            "row_count": r["row_count"], "limited": r["limited"], "tables": tables, "columns_used": cols,
            "seconds": r["seconds"], "bytes_estimate": r.get("bytes_estimate"), "checks": checks}


# ---------------------------------------------------------------- talking to Claude (chat lane, no tools)

def _json_reply(text: str) -> dict | None:
    text = (text or "").strip()
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except ValueError:
        return None
    return obj if isinstance(obj, dict) and obj.get("action") in ("query", "answer") else None


def models_for(uid: str) -> dict:
    """The models Ask D may use for this person: their gateway routes, else the Claude catalog. Ask D defaults to Sonnet
    (fast and cheap for short answers) when the catalog has it."""
    from . import worker
    base = {**worker.model_catalog(), "default": worker.DEFAULT_MODEL}
    cat = providers.catalog_for(uid, base)
    if cat.get("provider") in providers.CLI_KINDS:     # Ask D always answers on Claude (no tools), not on another CLI
        cat = {**base, "provider": "claude_account"}
    ids = [m["id"] for m in cat["models"]]
    default = cat["default"] if cat.get("provider") == "litellm" else ("sonnet" if "sonnet" in ids else cat["default"])
    return {"default": default, "ids": ids, "models": cat["models"]}


def pick_model(uid: str, model: str | None) -> str:
    m = models_for(uid)
    model = (model or "").strip()
    if not model:
        return m["default"]
    if model not in m["ids"]:
        raise AskError(f"Choose a model you can use: {', '.join(m['ids'][:12])}.")
    return model


async def _claude(u: dict, prompt: str, session: str | None, workdir: str, model: str | None = None, system: str | None = None) -> dict:
    model = model or models_for(u["id"])["default"]
    cfg = providers.run_config(u["id"], model, 600)
    if cfg.get("runner"):                     # Ask D runs on Claude with no tools; another CLI's choice uses Claude
        cfg = providers.run_config(u["id"], model, 600, kind="claude_account")
    payload = {"workdir": workdir, "prompt": prompt, "system": system or SYSTEM, "model": cfg["model"], "max_turns": 2,
               "timeout_s": 600, "resume": session, "lane": "chat", "runner": "claude-code", "env": cfg["env"], "tools": []}
    url = await instances.agent_url(u["id"])
    done: dict = {}
    async with httpx.AsyncClient(timeout=httpx.Timeout(15, read=None)) as client:
        async with client.stream("POST", f"{url}/runs", json=payload) as r:
            if r.status_code == 409:
                raise AskError("Ask D is answering another question of yours — try again in a moment.")
            if r.status_code != 200:
                raise AskError(f"The AI provider refused the question: {(await r.aread()).decode(errors='replace')[:200]}")
            async for line in r.aiter_lines():
                if not line.strip():
                    continue
                ev = json.loads(line)
                if ev["kind"] == "error":
                    raise AskError(ev["text"][:300])
                if ev["kind"] == "start" and ev.get("model"):
                    done["model"] = ev["model"]
                if ev["kind"] == "done":
                    done.update(ev)
    if "kind" not in done:
        raise AskError("The AI provider stopped without an answer.")
    done["provider"] = cfg["provider"]
    return done


async def ask_json(u: dict, system: str, prompt: str, step: str, model: str | None = None) -> dict:
    """One structured request to the model (no tools, the chat lane): returns the JSON object it replied with.
    Counts against the person's quota and is recorded in the cost records under `step`."""
    costs.check(u["id"])
    res = await _claude(u, prompt, None, _workdir(u["id"]), model, system)
    use = res.get("usage") or {}
    costs.record("llm", u["id"], step=step, model=res.get("model"), provider=res.get("provider"),
                 tokens=sum(v for v in use.values() if isinstance(v, (int, float))), cost_usd=res.get("cost_usd") or 0)
    text = res.get("text") or ""
    m = re.search(r"\{.*\}", text, re.S)
    try:
        return json.loads(m.group(0)) if m else {}
    except ValueError:
        return {}


def _workdir(uid: str) -> str:
    """The agent needs an existing folder under the projects root; Ask D keeps one per person (nothing is written)."""
    name = f"askd-{re.sub(r'[^a-z0-9]', '', uid.lower())[:40] or 'user'}"
    (store.root() / name).mkdir(parents=True, exist_ok=True)
    return store.rel(name)


# ---------------------------------------------------------------- threads, answers, cache, feedback

def threads(uid: str) -> list[dict]:
    rows = db.q("SELECT * FROM askd_threads WHERE user_id = ? ORDER BY updated DESC LIMIT 100", (uid,))
    for r in rows:
        r["scope"] = json.loads(r["scope"])
    return rows


def thread(tid: str, uid: str) -> dict:
    t = db.one("SELECT * FROM askd_threads WHERE id = ? AND user_id = ?", (tid, uid))
    if not t:
        raise AskError("Unknown conversation")
    t["scope"] = json.loads(t["scope"])
    t["messages"] = [{**m, "body": json.loads(m["body"])} for m in db.q("SELECT * FROM askd_messages WHERE thread_id = ? ORDER BY created", (tid,))]
    fb = {f["message_id"]: f for f in db.q("SELECT * FROM askd_feedback WHERE user_id = ?", (uid,))}
    for m in t["messages"]:
        m["feedback"] = fb.get(m["id"])
    return t


def _cache_key(scope: dict, question: str, engines: dict, uid: str, model: str = "") -> str:
    version = []
    for e in engines.values():
        if e["kind"] == "extract":
            for pid in e["projects"]:
                d = store.project_dir(pid) / "data"
                version += [f"{f.name}:{int(f.stat().st_mtime)}" for f in sorted(d.glob("*")) if f.suffix in (".csv", ".parquet")]
        else:
            version.append(f"live:{e['connection']['id']}:{int(time.time() // CACHE_LIVE_S)}")
    norm = re.sub(r"\s+", " ", question.strip().lower())
    return hashlib.sha256(json.dumps([uid, scope, norm, sorted(version)] + ([model] if model else []), sort_keys=True).encode()).hexdigest()


async def ask(u: dict, question: str, scope: dict, thread_id: str | None = None, model: str | None = None) -> dict:
    question = question.strip()
    if not question:
        raise AskError("Ask a question.")
    model = pick_model(u["id"], model)          # checked first: nothing is saved for a model the person cannot use
    if thread_id:
        t = thread(thread_id, u["id"])
        scope = t["scope"]
    else:
        thread_id = "t-" + secrets.token_hex(6)
        db.run("INSERT INTO askd_threads (id, user_id, scope, title, created, updated) VALUES (?, ?, ?, ?, ?, ?)",
               (thread_id, u["id"], json.dumps(scope), question[:120], time.time(), time.time()))
    pack, ctx = context_pack(u, scope)
    key = _cache_key(scope, question, ctx["engines"], u["id"], model)
    hit = db.one("SELECT body FROM askd_cache WHERE key = ?", (key,))
    db.run("INSERT INTO askd_messages (id, thread_id, role, body, created) VALUES (?, ?, 'user', ?, ?)",
           ("q-" + secrets.token_hex(6), thread_id, json.dumps({"text": question}), time.time()))
    if hit:
        body = {**json.loads(hit["body"]), "cached": True, "cache_key": key}
        return _store_answer(u, thread_id, question, body, cached=True)
    costs.check(u["id"], ctx["sources"].get("team_id"))     # a cached answer is free; a new one counts against quotas
    earlier = [m for m in thread(thread_id, u["id"])["messages"][:-1]]
    history = "\n".join((f"Q: {m['body']['text']}" if m["role"] == "user" else f"A: {m['body'].get('summary', '')}") for m in earlier[-6:])
    prompt = (f"# Context\n{pack}\n\n" + (f"# Earlier in this conversation\n{history}\n\n" if history else "") + f"# Question\n{question}")
    queries: list[dict] = []
    session, usage = None, {"cost_usd": 0.0, "tokens": 0, "model": None, "provider": None}
    reply = None
    for _ in range(MAX_QUERIES + 2):
        res = await _claude(u, prompt, session, _workdir(u["id"]), model)
        session = res.get("session_id")
        usage["cost_usd"] += res.get("cost_usd") or 0
        usage["tokens"] += sum((res.get("usage") or {}).values())
        usage["model"], usage["provider"] = res.get("model") or usage["model"], res.get("provider")
        reply = _json_reply(res.get("text", ""))
        if reply is None:
            prompt = "Reply with exactly one JSON object as described (action query or answer), nothing else."
            continue
        if reply["action"] == "answer":
            break
        if len(queries) >= MAX_QUERIES:
            prompt = "That is the query limit. Answer now with the results you have (action answer)."
            continue
        qid = f"q{len(queries) + 1}"
        try:
            r = run_query(ctx["engines"], str(reply.get("engine", "")), str(reply.get("sql", "")), u)
            queries.append({"id": qid, **r, "why": reply.get("why")})
            preview = {"columns": r["columns"], "rows": r["rows"][:PREVIEW_ROWS], "row_count": r["row_count"], "limited": r["limited"]}
            prompt = f"Result of {qid} ({r['where']}): " + json.dumps(preview, default=str)[:20000]
        except (AskError, connectors.ConnectorError) as e:
            queries.append({"id": qid, "engine": reply.get("engine"), "sql": reply.get("sql"), "error": str(e)})
            prompt = f"{qid} was refused or failed: {e}. Fix the query (or answer if you cannot)."
        except Exception as e:  # noqa: BLE001 - the warehouse's message helps Claude correct the SQL
            queries.append({"id": qid, "engine": reply.get("engine"), "sql": reply.get("sql"), "error": str(e)[:300]})
            prompt = f"{qid} failed in the warehouse: {str(e)[:300]}. Fix the query (or answer if you cannot)."
    if not reply or reply["action"] != "answer":
        raise AskError("Ask D could not finish an answer. Try asking more specifically.")
    body = _finish(reply, queries, ctx, usage)
    db.run("INSERT OR REPLACE INTO askd_cache (key, body, created) VALUES (?, ?, ?)", (key, json.dumps(body, default=str), time.time()))
    return _store_answer(u, thread_id, question, {**body, "cache_key": key})


def _finish(reply: dict, queries: list[dict], ctx: dict, usage: dict) -> dict:
    ok = [q for q in queries if not q.get("error")]
    main = next((q for q in ok if q["id"] == reply.get("query")), ok[-1] if ok else None)
    used = [str(n) for n in reply.get("metrics_used") or []]
    certified = [n for n in used if n.lower() in ctx["metrics"]]
    result = reply.get("result") or {}
    return {"result": {"type": result.get("type") if result.get("type") in ("number", "table", "chart") else "table",
                       "headline": str(result.get("headline") or "")[:200], "chart": result.get("chart") if isinstance(result.get("chart"), dict) else None},
            "data": {"columns": main["columns"], "rows": main["rows"][:1000], "row_count": main["row_count"], "limited": main["limited"]} if main else None,
            "summary": str(reply.get("summary") or "")[:2000], "actions": [str(a)[:400] for a in (reply.get("actions") or [])[:3]],
            "next_questions": [str(a)[:200] for a in (reply.get("next_questions") or [])[:3]],
            "validation": {"main_query": main["id"] if main else None, "queries": [{k: v for k, v in q.items() if k != "rows"} for q in queries],
                           "where": main["where"] if main else None,
                           "certified": bool(used) and len(certified) == len(used), "metrics_used": used, "certified_metrics": certified,
                           "not_included": list(dict.fromkeys([str(x) for x in reply.get("not_included") or []] + ctx["not_included"]))[:20]},
            "usage": usage}


def _store_answer(u: dict, tid: str, question: str, body: dict, cached: bool = False) -> dict:
    mid = "a-" + secrets.token_hex(6)
    db.run("INSERT INTO askd_messages (id, thread_id, role, body, created) VALUES (?, ?, 'assistant', ?, ?)",
           (mid, tid, json.dumps(body, default=str), time.time()))
    db.run("UPDATE askd_threads SET updated = ? WHERE id = ?", (time.time(), tid))
    v = body.get("validation") or {}
    if not cached:
        use = body.get("usage") or {}
        costs.record("llm", u["id"], step="askd", model=use.get("model"), provider=use.get("provider"), tokens=use.get("tokens") or 0,
                     cost_usd=use.get("cost_usd") or 0, obj=tid)
    db.audit("askd.question", tid, {"question": question[:500], "cached": cached, "where": v.get("where"),
                                    "tables": sorted({t for q in v.get("queries") or [] for t in q.get("tables") or []}),
                                    "columns": sorted({c for q in v.get("queries") or [] for c in q.get("columns_used") or []})[:80],
                                    "certified": v.get("certified"), "provider": (body.get("usage") or {}).get("provider"),
                                    "model": (body.get("usage") or {}).get("model"), "tokens": (body.get("usage") or {}).get("tokens"),
                                    "cost_usd": round((body.get("usage") or {}).get("cost_usd") or 0, 4)}, u["id"])
    return {"thread_id": tid, "message_id": mid, **body}


def feedback(mid: str, u: dict, rating: int, corrected_sql: str | None, comment: str | None) -> None:
    m = db.one("SELECT m.id FROM askd_messages m JOIN askd_threads t ON t.id = m.thread_id WHERE m.id = ? AND t.user_id = ?", (mid, u["id"]))
    if not m:
        raise AskError("Unknown answer")
    db.run("INSERT OR REPLACE INTO askd_feedback (message_id, user_id, rating, corrected_sql, comment, created) VALUES (?, ?, ?, ?, ?, ?)",
           (mid, u["id"], 1 if rating > 0 else -1, (corrected_sql or "")[:20000] or None, (comment or "")[:2000] or None, time.time()))
    if rating < 0:                                     # a bad answer is never served again from the cache
        key = json.loads(db.one("SELECT body FROM askd_messages WHERE id = ?", (mid,))["body"]).get("cache_key")
        if key:
            db.run("DELETE FROM askd_cache WHERE key = ?", (key,))
    db.audit("askd.feedback", mid, {"rating": rating, "corrected": bool(corrected_sql)}, u["id"])


def message(mid: str, uid: str) -> tuple[dict, dict]:
    m = db.one("SELECT m.*, t.scope, t.user_id FROM askd_messages m JOIN askd_threads t ON t.id = m.thread_id WHERE m.id = ?", (mid,))
    if not m or m["user_id"] != uid:
        raise AskError("Unknown answer")
    q = db.one("SELECT body FROM askd_messages WHERE thread_id = ? AND role = 'user' AND created <= ? ORDER BY created DESC LIMIT 1",
               (m["thread_id"], m["created"]))
    return json.loads(m["body"]), {"scope": json.loads(m["scope"]), "question": json.loads(q["body"])["text"] if q else ""}


def snapshot_html(body: dict, question: str) -> str:
    """A self-contained card (no scripts, no external files) for the headless-browser PNG."""
    import html as h
    data = body.get("data") or {}
    cols, rows = data.get("columns") or [], (data.get("rows") or [])[:20]
    chart = ""
    spec = (body.get("result") or {}).get("chart")
    if spec and rows and spec.get("x") in cols and (spec.get("y") or [None])[0] in cols:
        ys = [float(r.get(spec["y"][0]) or 0) for r in rows]
        top = max(ys) or 1
        bw = 640 / max(1, len(ys))
        def short(v: float) -> str:
            a = abs(v)
            return f"{v / 1e9:.1f}B" if a >= 1e9 else f"{v / 1e6:.1f}M" if a >= 1e6 else f"{v / 1e3:.1f}K" if a >= 1e4 else f"{v:,.4g}"
        bars = "".join(f'<rect x="{i * bw + 4}" y="{200 - 170 * v / top}" width="{bw - 8}" height="{170 * v / top}" rx="3" fill="#2C7A66"/>'
                       + (f'<text x="{i * bw + bw / 2}" y="{196 - 170 * v / top}" font-size="9.5" text-anchor="middle" fill="#2F4039">{short(v)}</text>'
                          if len(ys) <= 20 else "")           # values on the bars, so the image reads on its own
                       + f'<text x="{i * bw + bw / 2}" y="216" font-size="10" text-anchor="middle" fill="#5F655F">{h.escape(str(rows[i].get(spec["x"]))[:12])}</text>'
                       for i, v in enumerate(ys))
        chart = f'<svg width="660" height="225" viewBox="0 0 660 225">{bars}</svg>'
    table = "".join("<tr>" + "".join(f"<td>{h.escape(str(r.get(c, '')))}</td>" for c in cols) + "</tr>" for r in rows)
    v = body.get("validation") or {}
    return f"""<!doctype html><meta charset="utf-8"><style>
body{{margin:0;padding:24px;font:14px/1.5 'Segoe UI',Arial,sans-serif;color:#111827;background:#F3F4F6}}
.card{{background:#fff;border:1px solid #E2E5E9;border-radius:8px;padding:20px;width:680px}}
.q{{color:#5F655F;font-size:13px}}.h{{font-size:26px;font-weight:700;margin:6px 0}}.b{{display:inline-block;font-size:11px;font-weight:600;
padding:2px 8px;border-radius:999px;background:#EAF3F0;color:#0E5A4A;margin-right:6px}}table{{border-collapse:collapse;font-size:12px;margin-top:10px}}
td,th{{border-bottom:1px solid #EEE;padding:3px 8px;text-align:left}}.f{{margin-top:12px;font-size:11px;color:#8E958E}}</style>
<div class="card"><div class="q">{h.escape(question)}</div><div class="h">{h.escape((body.get("result") or {}).get("headline") or "")}</div>
<div>{'<span class="b">Certified</span>' if v.get("certified") else '<span class="b">Ad hoc</span>'}<span class="b">{h.escape(str(v.get("where") or ""))}</span></div>
{chart}<p>{h.escape(body.get("summary") or "")}</p>
<table><tr>{''.join(f'<th>{h.escape(c)}</th>' for c in cols)}</tr>{table}</table>
<div class="f">D2D · Ask D · {time.strftime('%Y-%m-%d %H:%M')}</div></div>"""
