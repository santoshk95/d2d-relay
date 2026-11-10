"""Data pipelines & ETL — the rules (rules first; the agent only where none fits):

  health      what the run history and the definitions show: failing since a date, flaky, slower than usual, a password
              in the definition, not run and not scheduled (retire candidate), the same definition twice (merge
              candidate), no owner
  decide      Keep / Merge / Retire, each with its reason, and the conversion route (rules or Relay's agent)
  diagnose    a failure's cause from its error text (schema change, late file, transient, sign-in, duplicates), checked
              against the warehouse's dictionary when the cause is a missing column
  convert     an Informatica PowerCenter mapping or an ADF mapping data flow into one dbt model (SQL), expressions
              translated by pipelines_expr; what does not translate is left for the agent with the reason
  dbt         the converted models as a dbt project (models, schema.yml tests, sources.yml), in the target's dialect
"""
from __future__ import annotations

import re
import statistics

from . import pipelines_expr as px

TECH = {"LOAD_TS", "BATCH_ID", "ETL_TS", "INSERTED_AT", "UPDATED_TS"}       # set by the load, never compared


# ================================================================== health

def _streak(runs: list[dict]) -> list[dict]:
    out = []
    for r in reversed(runs):
        if r["status"] != "failed":
            break
        out.append(r)
    return list(reversed(out))


def _age(h: float) -> str:
    return f"{h:.0f} h" if h < 48 else f"{h / 24:.0f} days"


def health(jobs: list[dict], runs: list[dict], now: float, window_days: int = 30) -> list[dict]:
    """Findings, one per job and issue: {id, job, issue_kind, severity, issue, measured, evidence}."""
    by = {}
    for r in sorted(runs, key=lambda r: r.get("start") or 0):
        by.setdefault(r["job"].upper(), []).append(r)
    have_runs = {j["tool"] for j in jobs if by.get(j["name"].upper())}
    out = []

    def add(j, kind, sev, issue, measured="", ev=None):
        out.append({"id": f"{kind}-{j['tool']}-{_slug(j['name'])}", "job": j["name"], "tool": j["tool_label"], "job_id": j["id"], "issue_kind": kind, "severity": sev, "issue": issue,
                    "measured": measured, "evidence": ev or {}, "decision": "keep"})
    fps: dict = {}
    for j in jobs:
        if j.get("fingerprint") and j["tool"] not in ("fivetran",):
            fps.setdefault((j["tool"], j["fingerprint"]), []).append(j)
    for j in jobs:
        rs = [r for r in by.get(j["name"].upper(), []) if (r.get("start") or now) >= now - window_days * 86400]
        fails = [r for r in rs if r["status"] == "failed"]
        streak = _streak(rs)
        if streak and (len(streak) >= 2 or (rs and rs[-1]["status"] == "failed" and len(rs) <= 3)):
            first = streak[0]
            add(j, "failing", "high", f"fails since {_day(first.get('start'))}: {streak[-1].get('error') or 'no error text'}",
                f"{len(streak)} failed run(s) in a row", {"runs": streak[-5:]})
        elif fails and rs and len(fails) >= 2 and len(fails) / len(rs) >= 0.1:
            add(j, "flaky", "medium", f"{len(fails)} of {len(rs)} runs failed in {window_days} days — it recovers, then fails again: {fails[-1].get('error') or ''}".strip(" :"),
                f"{100 * len(fails) / len(rs):.0f} % failed", {"failures": fails[-5:]})
        ok = [r for r in rs if r["status"] == "succeeded" and r.get("start") and r.get("end")]
        if len(ok) >= 10:
            durs = [(r["end"] - r["start"]) for r in ok]
            recent, before = durs[-6:], durs[:-6]
            if before and statistics.median(recent) >= 2 * max(1.0, statistics.median(before)):
                add(j, "slow", "medium", f"the last {len(recent)} runs took {statistics.median(recent) / statistics.median(before):.1f}× as long as before",
                    f"{statistics.median(recent) / 60:.1f} min now vs {statistics.median(before) / 60:.1f} min", {"recent_s": recent, "before_s": before[-10:]})
        for s in j.get("secrets") or []:
            add(j, "secret", "high", f"a password is written in the definition ({s}) — move it to the tool's secret store", "", {"where": s})
        if j.get("broken"):
            add(j, "failing", "high", "the connection is broken: " + "; ".join(t for t in j.get("tasks") or [] if t), "setup state broken", {"tasks": j.get("tasks")})
        if j["tool"] in have_runs and not rs and (not j.get("enabled") or j.get("schedule") in ("", "manual")):
            add(j, "unused", "low", f"no run in {window_days} days and no active schedule — a retire candidate", "0 runs", {})
        elif not j.get("enabled") and j["tool"] not in have_runs and j["kind"] not in ("model",):
            add(j, "unused", "low", "its schedule is switched off — a retire candidate if nobody runs it by hand", "not scheduled", {})
        dupes = [x for x in fps.get((j["tool"], j.get("fingerprint")), []) if x["id"] != j["id"]]
        same_io = [x for x in jobs if x["id"] != j["id"] and x["tool"] == j["tool"] and x.get("target") and x.get("target") == j.get("target") and set(x["sources"]) == set(j["sources"]) and j["sources"]]
        twin = (dupes or same_io)
        if twin and _newer(j, twin[0]):
            add(j, "duplicate", "low", f"does the same as {twin[0]['name']} (same {'definition' if dupes else 'sources and target'}) — a merge candidate", "", {"twin": twin[0]["name"]})
        if j["tool"] in ("adf", "airflow", "dbt", "talend") and not j.get("owner") and j["kind"] != "model":
            add(j, "owner", "low", "no owner recorded", "", {})
    return out


def _newer(j: dict, other: dict) -> bool:
    """Of two twins, the one with the later-looking name (…_V2, …_COPY) is the merge candidate."""
    a, b = j["name"].upper(), other["name"].upper()
    if re.search(r"(_V\d+|_COPY|_OLD|_NEW|\d)$", a) and not re.search(r"(_V\d+|_COPY|_OLD|_NEW|\d)$", b):
        return True
    if re.search(r"(_V\d+|_COPY|_OLD|_NEW|\d)$", b) and not re.search(r"(_V\d+|_COPY|_OLD|_NEW|\d)$", a):
        return False
    return a > b


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40]


def _day(t) -> str:
    import time as _t
    return _t.strftime("%d %b %Y", _t.gmtime(t)) if t else "an unknown date"


# ================================================================== decide (Keep / Merge / Retire) and the route

ROUTES = {"rules": "Ready to convert (rules)", "agent": "Needs Relay's agent", "none": "Nothing to convert"}


def decide(jobs: list[dict], findings: list[dict]) -> list[dict]:
    fk = {}
    for f in findings:
        fk.setdefault(f["job_id"], []).append(f)
    out = []
    for j in jobs:
        fs = fk.get(j["id"], [])
        twin = next((f["evidence"].get("twin") for f in fs if f["issue_kind"] == "duplicate"), None)
        if any(f["issue_kind"] == "unused" for f in fs) or re.match(r"(?i)archive", j["name"]):
            d, why = "retire", next((f["issue"] for f in fs if f["issue_kind"] == "unused"), "an archived copy, not scheduled")
        elif twin:
            d, why = "merge", f"same as {twin}: keep that one, point its consumers there"
        else:
            d, why = "keep", "runs and is used" + ("; fix the failure on the way" if any(f["issue_kind"] == "failing" for f in fs) else "")
        route = "none" if d != "keep" else ("rules" if (j.get("logic") or {}).get("lang") in ("infa", "adf") else "agent")
        out.append({"id": j["id"], "job": j["name"], "tool": j["tool_label"], "decision": d, "into": twin or "", "why": why, "route": ROUTES[route], "route_kind": route,
                    "target": j.get("target") or "", "sources": ", ".join(j.get("sources") or [])[:300]})
    return out


def validate_decisions(recs: list[dict]) -> list[str]:
    names = {r["job"]: r for r in recs}
    probs = []
    for r in recs:
        if r.get("decision") not in ("keep", "merge", "retire"):
            probs.append(f"{r['job']}: decide keep, merge or retire")
        if r.get("decision") == "merge":
            into = names.get((r.get("into") or "").strip())
            if not into:
                probs.append(f"{r['job']}: name the job it merges into (one of this estate's jobs)")
            elif into.get("decision") != "keep":
                probs.append(f"{r['job']}: it merges into {into['job']}, which is not kept")
    return probs


# ================================================================== diagnose and fix

SIGNATURES = [
    ("schema", re.compile(r"(?i)ORA-00904:\s*\"?(\w+)\"?: invalid identifier|invalid column name '?(\w+)'?|column[ \"']+(\w+)[\"' ]+(?:is not found|not found|does not exist)|"
                          r"(\w+) is not found in the source|no such column:? (?:\w+\.)?(\w+)|Unrecognized name: (\w+)")),
    ("late_file", re.compile(r"(?i)file not found|has not arrived|no such file|NoSuchKey|missing file|the bank's file")),
    ("transient", re.compile(r"(?i)connection reset|timed? ?out|temporarily unavailable|deadlock|throttl|503|502")),
    ("signin", re.compile(r"(?i)login failed|authentication failed|expired|invalid credentials|unauthori[sz]ed|revoked|re-?authori[sz]e")),
    ("duplicates", re.compile(r"(?i)unique constraint|duplicate key|ORA-00001|violation of primary key")),
]
CAUSE = {"schema": "a column the job reads was renamed or dropped at the source", "late_file": "the file the job reads had not arrived when it ran",
         "transient": "a short outage or timeout at the source or the target", "signin": "the job's sign-in to a system expired or was revoked",
         "duplicates": "the load met rows that are already there", "unknown": "not one of the known causes — a person looks at the run log"}
ROUTE = {"schema": "change", "late_file": "heal", "transient": "heal", "signin": "ticket", "duplicates": "ticket", "unknown": "ticket"}


def diagnose(error: str, dictionary: dict | None = None, reads: list[str] | None = None) -> dict:
    """{"cause", "why", "column", "replacement", "route"} for one failure's error text."""
    text = error or ""
    for kind, rx in SIGNATURES:
        m = rx.search(text)
        if not m:
            continue
        out = {"cause": kind, "why": CAUSE[kind], "column": None, "replacement": None, "route": ROUTE[kind]}
        if kind == "schema":
            col = next((g for g in m.groups() if g), None)
            out["column"] = col.upper() if col else None
            if col and dictionary and reads:
                best = None
                for t in reads:
                    cols = dictionary.get(t.upper()) or []
                    if cols and col.upper() not in cols:
                        cand, score = renamed_scored(col.upper(), cols)
                        if cand and (best is None or score > best[0]):
                            best = (score, t.upper(), cand)
                if best:
                    out.update(replacement=best[2], table=best[1], why=f"{best[1]} has no {col.upper()} any more; {best[2]} looks like its new name")
        return out
    return {"cause": "unknown", "why": CAUSE["unknown"], "column": None, "replacement": None, "route": ROUTE["unknown"]}


def renamed_scored(col: str, cols: list[str]) -> tuple[str | None, float]:
    """The column that most likely replaced `col` — a prefix or suffix of it scores 1, else the closest name — and how sure."""
    import difflib
    c = col.upper()
    cands = [x for x in cols if x != c]
    for x in cands:
        if c.startswith(x + "_") or c.endswith("_" + x) or x.startswith(c + "_"):
            return x, 1.0
    best = difflib.get_close_matches(c, cands, n=1, cutoff=0.6)
    return (best[0], difflib.SequenceMatcher(None, c, best[0]).ratio()) if best else (None, 0.0)


def renamed(col: str, cols: list[str]) -> str | None:
    return renamed_scored(col, cols)[0]


def patch_text(text: str, old: str, new: str) -> tuple[str, int]:
    """Rename a column in a definition (whole words only)."""
    rx = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(old)}(?![A-Za-z0-9_])", re.I)
    return rx.subn(new, text)


# ================================================================== convert to a dbt model

def convert(j: dict, dictionary: dict) -> dict:
    """{"sql" (DuckDB), "inputs", "columns", "materialized", "unique_key", "problems", "route", "notes"} for one job."""
    lg = j.get("logic") or {}
    try:
        if lg.get("lang") == "infa":
            out = _from_infa(lg, dictionary)
        elif lg.get("lang") == "adf":
            out = _from_adf(lg, dictionary)
        else:
            return {"sql": "", "inputs": [], "columns": [], "materialized": "table", "unique_key": [], "problems": [f"{j['tool_label']} {j['kind']}s convert with Relay's agent: no rule reads their logic yet"],
                    "route": "agent", "notes": []}
    except px.Untranslatable as e:
        return {"sql": "", "inputs": [], "columns": [], "materialized": "table", "unique_key": [], "problems": [str(e)], "route": "agent", "notes": []}
    except Exception as e:  # noqa: BLE001 - a definition the rules cannot read goes to the agent, with the reason
        return {"sql": "", "inputs": [], "columns": [], "materialized": "table", "unique_key": [], "problems": [f"the rules could not read it ({e.__class__.__name__}: {str(e)[:160]})"],
                "route": "agent", "notes": []}
    out["route"] = "agent" if out["problems"] and not out["sql"] else "rules"
    return out


class _Rel:
    def __init__(self, alias, table, cols, where=None, kind="source", on=None, how="inner", default=None):
        self.alias, self.table, self.cols, self.where, self.kind, self.on, self.how, self.default = alias, table, [c.upper() for c in cols], where, kind, on or [], how, default or {}


def _resolve_table(name: str, dictionary: dict) -> str:
    n = name.upper()
    if "." in n:
        return n
    hits = [t for t in dictionary if t.split(".")[-1] == n]
    if hits:
        return sorted(hits, key=lambda t: (not t.startswith("DW."), t))[0]
    return {"STG": "STAGE.", "TMP": "STAGE.", "DIM": "DW.", "FAC": "DW.", "AGG": "MART."}.get(n[:3], "DW.") + n


def _parse_select(sql: str) -> tuple[str, list[str], str | None]:
    """(table, columns, where) of a simple Source Qualifier / source query."""
    import sqlglot
    from sqlglot import exp
    params = re.findall(r"\$\$\w+|(?<![\w:]):\w+", sql)
    clean = re.sub(r"\$\$(\w+)|(?<![\w:]):(\w+)", lambda m: f"'__p_{m.group(1) or m.group(2)}__'", sql)
    tree = sqlglot.parse_one(clean, read="oracle")
    t = tree.find(exp.Table)
    table = ".".join(p for p in (t.args.get("db") and t.db, t.name) if p) if t else ""
    cols = [c.alias_or_name.upper() for c in tree.expressions] if isinstance(tree, exp.Select) else []
    w = tree.args.get("where")
    where = w.this.sql(dialect="duckdb") if w else None
    if where and "__p_" in where:                     # a watermark filter: dbt's incremental filter, not the full build
        where = None
    return table.upper(), cols, where


def _from_infa(lg: dict, dic: dict) -> dict:
    T = {t["name"]: t for t in lg["transformations"]}
    conns = lg["connectors"]
    problems, notes = [], []
    rels: list[_Rel] = []
    port_of: dict[tuple[str, str], tuple[str, str]] = {}            # (instance, field) -> (instance, field) upstream
    for c in conns:
        port_of[(c["to"], c["tf"])] = (c["from"], c["ff"])
    sqs = [t for t in lg["transformations"] if t["type"] == "Source Qualifier"]
    for i, t in enumerate(sqs):
        q = t["attrs"].get("Sql Query") or ""
        if q:
            table, cols, where = _parse_select(q)
        else:
            src = next((c["from"] for c in conns if c["to"] == t["name"]), t["name"].replace("SQ_", ""))
            table, cols, where = _resolve_table(src, dic), [f["name"].upper() for f in t["fields"]], t["attrs"].get("Source Filter") or None
        rels.append(_Rel(f"s{i}", table, cols or [f["name"].upper() for f in t["fields"]], where))
    sq_alias = {t["name"]: rels[i] for i, t in enumerate(sqs)}
    joins = []
    for t in lg["transformations"]:
        if t["type"] == "Joiner":
            cond = t["attrs"].get("Join Condition") or ""
            feeding = list(dict.fromkeys(c["from"] for c in conns if c["to"] == t["name"] and c["from"] in sq_alias))
            if len(feeding) != 2:
                problems.append(f"the joiner {t['name']} joins something other than two sources")
                continue
            a, b = sq_alias[feeding[0]], sq_alias[feeding[1]]
            pairs = [(x.strip().upper(), y.strip().upper()) for x, y in (p.split("=") for p in re.split(r"(?i)\s+AND\s+", cond) if "=" in p)]
            on = [(l, r[:-1] if r.endswith("1") and r[:-1] in b.cols else r) for l, r in pairs]
            how = {"Normal Join": "inner", "Master Outer Join": "left", "Detail Outer Join": "left", "Full Outer Join": "full"}.get(t["attrs"].get("Join Type") or "", "inner")
            b.kind, b.on, b.how = "join", [(f"{a.alias}.{l}", f"{b.alias}.{r}") for l, r in on], how
            joins.append(b)
    derived: dict[str, str] = {}
    for t in lg["transformations"]:
        if t["type"] == "Expression":
            for f in t["fields"]:
                if f.get("expr") and "OUTPUT" in f["port"] and f["port"] != "INPUT/OUTPUT":
                    derived[f["name"].upper()] = f["expr"]
    filters = [t["attrs"].get("Filter Condition") for t in lg["transformations"] if t["type"] == "Filter" and t["attrs"].get("Filter Condition")]
    aggs = [t for t in lg["transformations"] if t["type"] == "Aggregator"]
    if any(t["type"] in ("Router", "Normalizer", "Java", "Stored Procedure", "Custom Transformation", "Union") for t in lg["transformations"]):
        bad = sorted({t["type"] for t in lg["transformations"] if t["type"] in ("Router", "Normalizer", "Java", "Stored Procedure", "Custom Transformation", "Union")})
        return {"sql": "", "inputs": [], "columns": [], "materialized": "table", "unique_key": [], "problems": [f"{', '.join(bad)} transformation(s): a Type 2 history or custom logic — Relay's agent drafts it (a dbt snapshot where it is history)"], "notes": []}
    li = 0
    for t in lg["transformations"]:
        if t["type"] != "Lookup Procedure":
            continue
        li += 1
        table = (t["attrs"].get("Lookup Sql Override") or "").strip()
        tname = _resolve_table(t["attrs"].get("Lookup table name") or "", dic)
        cond = t["attrs"].get("Lookup condition") or ""
        rets = [f["name"].upper() for f in t["fields"] if f["port"] == "LOOKUP/OUTPUT"]
        lk = _Rel(f"l{li}", tname, rets, t["attrs"].get("Lookup Source Filter") or None, kind="lookup", how="left")
        for part in re.split(r"(?i)\s+AND\s+", cond):
            if "=" not in part:
                continue
            lcol, port = (x.strip() for x in part.split("=", 1))
            up = port_of.get((t["name"], port))
            lk.on.append((lcol.upper(), up[1].upper() if up else port.upper()))
        lk.name = t["name"]
        if table:
            problems.append(f"the lookup {t['name']} overrides its SQL: check the converted join")
        rels.append(lk)
    base = [r for r in rels if r.kind == "source"]
    if not base:
        raise px.Untranslatable("no source qualifier to read from")

    def provider(col: str):
        c = col.upper()
        for r in rels:
            if r.kind in ("source", "join") and c in r.cols:
                return r
        for r in rels:
            if r.kind == "lookup" and c in r.cols:
                return r
        if c.endswith("1"):
            for r in joins:
                if c[:-1] in r.cols:
                    return r
        return None

    seen: set = set()

    def resolve(col: str, depth: int = 0) -> str:
        c = col.upper()
        key = c if c in derived else ("O_" + c if "O_" + c in derived else None)
        if key and depth < 12:
            sql, _, prob = px.translate(derived[key], "infa", lambda x: resolve(x, depth + 1))
            if sql is None:
                raise px.Untranslatable(f"{key}: {prob}")
            return f"({sql})"
        r = provider(c[:-1] if c.endswith("1") and not provider(c) else c)
        if r is None:
            seen.add(c)
            raise px.Untranslatable(f"no input carries the column {c}")
        return f"{r.alias}.{c[:-1] if c.endswith('1') and c not in r.cols else c}"

    for lk in [r for r in rels if r.kind == "lookup"]:
        lk.on = [(f"{lk.alias}.{a}", resolve(b)) for a, b in lk.on]
    tgt_inst = next((i["name"] for i in lg["instances"] if i["type"] == "TARGET"), None)
    tdef = (lg.get("targets") or {}).get(tgt_inst) or {}
    target = f"{tdef.get('schema') or 'DW'}.{tgt_inst}".upper() if tgt_inst else ""
    mapping = [(c["tf"].upper(), c["ff"]) for c in conns if c["to"] == tgt_inst]
    upd = any(t["type"] == "Update Strategy" and "DD_UPDATE" in (t["attrs"].get("Update Strategy Expression") or "") for t in lg["transformations"])
    select, group = [], []
    if aggs:
        ag = aggs[0]
        for f in ag["fields"]:
            if f["etype"] == "GROUPBY":
                group.append(resolve(f["name"]))
        agg_out = {f["name"].upper(): f["expr"] for f in ag["fields"] if f["etype"] != "GROUPBY" and f.get("expr")}
    for tcol, ff in mapping:
        if tcol in TECH:
            notes.append(f"{tcol} is set by the load (not converted)")
            continue
        try:
            if aggs and ff.upper() in agg_out:
                sql, _, prob = px.translate(agg_out[ff.upper()], "infa", resolve)
                if sql is None:
                    raise px.Untranslatable(prob)
                select.append(f"{sql} AS {tcol}")
            else:
                select.append(f"{resolve(ff)} AS {tcol}")
        except px.Untranslatable as e:
            problems.append(f"{tcol}: {e}")
    if not select:
        raise px.Untranslatable("no target column could be converted")
    frm = f"{base[0].table} {base[0].alias}"
    where = [f"({w})" for w in [base[0].where] if w]
    for r in rels:
        if r.kind == "join":
            frm += f"\n{'LEFT ' if r.how == 'left' else 'FULL ' if r.how == 'full' else ''}JOIN {r.table} {r.alias} ON " + " AND ".join(f"{a} = {b}" for a, b in r.on)
            if r.where:
                frm += f" AND ({_qualify(r.where, r)})"
        elif r.kind == "lookup":
            frm += f"\nLEFT JOIN {r.table} {r.alias} ON " + " AND ".join(f"{a} = {b}" for a, b in r.on) + (f" AND ({_qualify(r.where, r)})" if r.where else "")
    for w in [base[0].where] if base[0].where else []:
        where[-1:] = [f"({_qualify(w, base[0])})"]
    for flt in filters:
        sql, _, prob = px.translate(flt, "infa", resolve)
        if sql is None:
            problems.append(f"filter: {prob}")
        else:
            where.append(sql)
    sql = "SELECT " + ",\n       ".join(select) + "\nFROM " + frm + (("\nWHERE " + " AND ".join(where)) if where else "") + (("\nGROUP BY " + ", ".join(group)) if group else "")
    inputs = sorted({r.table for r in rels})
    keys = [k.upper() for k in tdef.get("keys") or []]
    if not keys and aggs:                                            # an aggregate's grain is its group-by columns
        gnames = {f["name"].upper() for f in aggs[0]["fields"] if f["etype"] == "GROUPBY"}
        keys = [tcol for tcol, ff in mapping if ff.upper() in gnames]
    return {"sql": sql, "inputs": inputs, "columns": [s.rsplit(" AS ", 1)[1] for s in select], "materialized": "incremental" if upd else "table",
            "unique_key": keys, "problems": problems, "notes": notes, "target": target}


def _qualify(cond: str, r: _Rel) -> str:
    """Prefix a source's own columns in its filter with its alias (WHERE STATUS <> 'Cancelled' -> s1.STATUS …)."""
    out = cond
    for c in sorted(r.cols + ["IS_CURRENT", "STATUS", "ACTIVE"], key=len, reverse=True):
        out = re.sub(rf"(?<![\w.']){c}(?![\w'])", f"{r.alias}.{c}", out, flags=re.I)
    return out


def _from_adf(lg: dict, dic: dict) -> dict:
    """A mapping data flow script: sources, joins, lookups, derives, filters, aggregates, a sink."""
    lines = "\n".join(lg.get("script") or [])
    stmts = [s.strip() for s in re.split(r"~>\s*([\w@()., ]+)\s*\n?", lines)]
    problems, notes = [], []
    rels, streams, derived, filters, group, aggm = [], {}, {}, [], [], {}
    parts = re.findall(r"(.*?)~>\s*([\w@]+(?:@\([^)]*\))?)", lines, re.S)
    for body, name in parts:
        body = body.strip()
        name = name.split("@")[0]
        m = re.match(r"^source\(output\((.*?)\)", body, re.S)
        if m:
            cols = [c.split(" as ")[0].strip().upper() for c in m.group(1).split(",") if c.strip()]
            table = (lg.get("sources") or {}).get(name) or ""
            kind = "lookup" if name.lower().startswith("lkp") else "source"
            rels.append(_Rel(name, table.upper() or _resolve_table(name, dic), cols, kind=kind, how="left" if kind == "lookup" else "inner"))
            continue
        m = re.match(r"^([\w@]+),\s*([\w@]+)\s+join\((.*?),\s*joinType:'(\w+)'", body, re.S)
        if m:
            right = next((r for r in rels if r.alias == m.group(2)), None)
            if right:
                right.kind, right.how = "join", "left" if m.group(4) == "left" else "inner"
                right.on = [(f"{x.split('@')[0]}.{x.split('@')[1].upper()}", f"{y.split('@')[0]}.{y.split('@')[1].upper()}") for x, y in
                            (p.split("==") for p in m.group(3).replace(" ", "").split("&&"))]
            continue
        m = re.match(r"^([\w@]+),\s*([\w@]+)\s+lookup\((.*?),\s*multiple:", body, re.S)
        if m:
            lk = next((r for r in rels if r.alias == m.group(2)), None)
            if lk:
                lk.kind = "lookup"
                lk.on = [(f"{lk.alias}.{y.split('@')[-1].upper()}", x.strip().upper()) for x, y in (p.split("==") for p in m.group(3).replace(" ", "").split("&&"))]
            continue
        m = re.match(r"^([\w@]+)\s+derive\((.*)\)\s*$", body, re.S)
        if m:
            for part in _split_top(m.group(2)):
                if "=" in part:
                    k, v = part.split("=", 1)
                    derived[k.strip().upper()] = v.strip()
            continue
        m = re.match(r"^([\w@]+)\s+filter\((.*)\)\s*$", body, re.S)
        if m:
            filters.append(m.group(2))
            continue
        m = re.match(r"^([\w@]+)\s+aggregate\(groupBy\((.*?)\),\s*(.*)\)\s*$", body, re.S)
        if m:
            group = [g.strip().upper() for g in m.group(2).split(",") if g.strip()]
            for part in _split_top(m.group(3)):
                k, v = part.split("=", 1)
                aggm[k.strip().upper()] = v.strip()
            continue
        if re.match(r"^([\w@]+)\s+split\(", body):
            raise px.Untranslatable("a conditional split (a Type 2 history) — Relay's agent drafts it as a dbt snapshot")
        m = re.match(r"^([\w@]+)\s+sink\((.*)\)\s*$", body, re.S)
        if m:
            keys = re.findall(r"'(\w+)'", re.search(r"keys:\[(.*?)\]", m.group(2)).group(1)) if "keys:[" in m.group(2) else []
            upsert = "upsertable:true" in m.group(2).replace(" ", "")
            streams["sink"] = {"keys": [k.upper() for k in keys], "upsert": upsert}
    base = [r for r in rels if r.kind == "source"]
    if not base:
        raise px.Untranslatable("no source in the data flow")

    def provider(c):
        for r in rels:
            if r.kind in ("source", "join") and c in r.cols:
                return r
        for r in rels:
            if r.kind == "lookup" and c in r.cols:
                return r
        return None

    def resolve(col, depth=0):
        c = col.upper()
        if c in derived and depth < 12:
            sql, _, prob = px.translate(derived[c], "adf", lambda x: resolve(x, depth + 1))
            if sql is None:
                raise px.Untranslatable(f"{c}: {prob}")
            return f"({sql})"
        r = provider(c)
        if not r:
            raise px.Untranslatable(f"no input carries the column {c}")
        return f"{r.alias}.{c}"
    for lk in [r for r in rels if r.kind == "lookup"]:
        lk.on = [(a, resolve(b)) for a, b in lk.on]
    target = (lg.get("sink") or "").upper()
    cols = [c for c, _ in (dic.get(target) or [])] if isinstance(dic.get(target), list) and dic.get(target) and isinstance(dic[target][0], tuple) else list(dic.get(target) or [])
    out_cols = [c for c in cols if c not in TECH] or list(dict.fromkeys([c for r in base for c in r.cols] + list(derived)))
    select = []
    for c in out_cols:
        try:
            if aggm and c in aggm:
                sql, _, prob = px.translate(aggm[c], "adf", resolve)
                if sql is None:
                    raise px.Untranslatable(prob)
                select.append(f"{sql} AS {c}")
            else:
                select.append(f"{resolve(c)} AS {c}")
        except px.Untranslatable as e:
            if c in (r2.cols for r2 in rels):
                problems.append(f"{c}: {e}")
            else:
                notes.append(f"{c}: the target has it, the data flow does not set it")
    frm = f"{base[0].table} {base[0].alias}"
    for r in rels:
        if r.kind == "join":
            frm += f"\n{'LEFT ' if r.how == 'left' else ''}JOIN {r.table} {r.alias} ON " + " AND ".join(f"{a} = {b}" for a, b in r.on)
        elif r.kind == "lookup" and r.on:
            frm += f"\nLEFT JOIN {r.table} {r.alias} ON " + " AND ".join(f"{a} = {b}" for a, b in r.on)
    where = []
    for flt in filters:
        sql, _, prob = px.translate(flt, "adf", resolve)
        (where.append(sql) if sql else problems.append(f"filter: {prob}"))
    grp = [resolve(g) for g in group]
    sql = "SELECT " + ",\n       ".join(select) + "\nFROM " + frm + (("\nWHERE " + " AND ".join(where)) if where else "") + (("\nGROUP BY " + ", ".join(grp)) if grp else "")
    sink = streams.get("sink") or {}
    notes.append("the data flow carries no source filters or lookup conditions beyond its joins: the proof shows whether rows differ")
    return {"sql": sql, "inputs": sorted({r.table for r in rels}), "columns": [s.rsplit(" AS ", 1)[1] for s in select], "materialized": "incremental" if sink.get("upsert") else "table",
            "unique_key": sink.get("keys") or [], "problems": problems, "notes": notes, "target": target}


def _split_top(s: str) -> list[str]:
    out, depth, cur, q = [], 0, "", None
    for ch in s:
        if q:
            cur += ch
            if ch == q:
                q = None
            continue
        if ch in "'\"":
            q = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur.strip())
    return out


# ================================================================== the dbt project

def model_name(job_name: str) -> str:
    n = re.sub(r"_(LOAD|BUILD|IMPORT|EXPORT|SCD2)(_V\d+)?$", "", job_name.upper())
    return re.sub(r"[^a-z0-9_]+", "_", n.lower()).strip("_") or "model"


def layer(target: str) -> str:
    s = (target or "").split(".")[0].upper()
    return {"STAGE": "staging", "DW": "marts", "MART": "marts"}.get(s, "intermediate")


def dbt_model(conv: dict, job: dict, models: dict, dialect: str) -> tuple[str, str]:
    """(path, SQL) of one model in the target's dialect: the warehouse tables become sources, other converted models refs."""
    import sqlglot
    sql = conv["sql"]
    try:
        sql = sqlglot.transpile(sql, read="duckdb", write=dialect, pretty=True)[0] if dialect != "duckdb" else sql
    except Exception:  # noqa: BLE001 - kept in DuckDB's dialect, with a note in the header
        dialect = "duckdb"
    for t in sorted(conv["inputs"], key=len, reverse=True):
        sch, tab = t.split(".", 1) if "." in t else ("dw", t)
        rep = "{{ ref('" + models[t] + "') }}" if t in models else "{{ source('" + sch.lower() + "', '" + tab.lower() + "') }}"
        sql = re.sub(rf"(?<![\w.\"]){re.escape(t)}(?![\w\"])", rep, sql, flags=re.I)
        sql = re.sub(rf'"{sch}"\."{tab}"', rep, sql, flags=re.I)
    conf = {"materialized": conv["materialized"]}
    if conv["unique_key"] and conv["materialized"] == "incremental":
        conf["unique_key"] = [k.lower() for k in conv["unique_key"]]
    head = "{{ config(" + ", ".join(f"{k}={v!r}" for k, v in conf.items()) + ") }}\n" + f"-- converted by Relay from {job['tool_label']} {job['kind']} {job['name']} (rules); dialect {dialect}\n"
    return f"models/{layer(conv.get('target') or job.get('target'))}/{model_name(job['name'])}.sql", head + sql + "\n"


def dbt_yaml(converted: list[tuple[dict, dict]]) -> tuple[str, str]:
    import yaml
    models, sources = [], {}
    for j, cv in converted:
        cols = [{"name": c.lower(), **({"tests": ["not_null"]} if c in cv["unique_key"] else {})} for c in cv["columns"]]
        m = {"name": model_name(j["name"]), "description": (j.get("description") or "")[:300], "columns": cols}
        if len(cv["unique_key"]) > 1:
            m["tests"] = [{"dbt_utils.unique_combination_of_columns": {"combination_of_columns": [k.lower() for k in cv["unique_key"]]}}]
        elif cv["unique_key"]:
            cols_by = {c["name"]: c for c in cols}
            cols_by.get(cv["unique_key"][0].lower(), {}).setdefault("tests", []).append("unique")
        models.append(m)
        for t in cv["inputs"]:
            sch, tab = t.split(".", 1) if "." in t else ("dw", t)
            sources.setdefault(sch.lower(), set()).add(tab.lower())
    schema = yaml.safe_dump({"version": 2, "models": models}, sort_keys=False, allow_unicode=True)
    src = yaml.safe_dump({"version": 2, "sources": [{"name": s, "schema": s, "tables": [{"name": t} for t in sorted(ts)]} for s, ts in sorted(sources.items())]}, sort_keys=False)
    return schema, src
