"""Where the AI wave's packs read their numbers (Predictive analytics first; Anomaly & risk detection and
Suggestions & recommendations reuse it): the work item's uploads (DuckDB), its warehouse connections (the guarded,
read-only live query, written once in DuckDB's dialect and transpiled by sqlglot) and **a dashboard's data** - DuckDB
over the dashboard's data folder with Ask Relay's guard (one read-only SELECT over that dashboard's own views, a row limit),
opened only when the work item's owner may open the dashboard.

A dataset is {"key", "name", "label", "where", "ref"}; ref is {"source": "file", "item", "file"} |
{"source": "connection", "connection", "object"} | {"source": "dashboard", "project", "table"}. `series()` turns one
into a time series (periods and values) by a grain - day, week, month or quarter - with one SQL aggregate."""
from __future__ import annotations

import json
import re
from pathlib import Path

from .. import askd, auth, connectors, db, store
from .. import workbench as wb

oc = wb.oc
GRAINS = (("month", "Month"), ("week", "Week"), ("day", "Day"), ("quarter", "Quarter"))
AGGS = (("sum", "Sum"), ("avg", "Average"), ("count", "Count of rows"), ("max", "Largest"), ("min", "Smallest"))
NUMERIC = ("int", "decimal", "float", "number")
VALUE_WORDS = re.compile(r"amount|value|sales|revenue|qty|quantity|units|demand|cash|cost|spend|orders?|volume|total|count|price|margin|hours|calls|tickets", re.I)


def j(s, default):
    try:
        return json.loads(s) if isinstance(s, str) and s else (s if s is not None else default)
    except ValueError:
        return default


def slug(s: str, n: int = 40) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(s).lower()).strip("-")[:n] or "x"


def fmt(v, d: int = 2) -> str:
    if v is None:
        return "-"
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    if f.is_integer() and abs(f) < 1e15:
        return f"{int(f):,}"
    return f"{f:,.{d}f}"


# ------------------------------------------------------------------ a dashboard's data as a platform and a reader

class DashboardReader(oc.Reader):
    """One table (view) of a dashboard's data, through Ask Relay's engine and guard: DuckDB views over its data folder."""
    label = "dashboard"
    sql = True

    def __init__(self, pid: str, table: str):
        try:
            self.con, self.tables = askd._extract_engine([pid], False)          # noqa: SLF001 - the dashboard's own views, as Ask Relay sees them
        except (KeyError, FileNotFoundError) as e:
            raise oc.ReadError("The dashboard has no data folder.") from e
        if table not in self.tables:
            self.close()
            raise oc.ReadError(f"{table} is not one of the dashboard's tables ({', '.join(sorted(self.tables)[:8])}).")
        self.pid, self.view = pid, table

    def run(self, sql: str) -> list[dict]:
        try:
            safe, _, _ = askd.guard_duckdb(sql, set(self.tables), connectors.guardrails()["row_limit"])
            cols, rows = askd._run_duckdb(self.con, safe, 60)                  # noqa: SLF001
        except askd.AskError as e:
            raise oc.ReadError(str(e)) from e
        return rows

    def columns(self) -> list[dict]:
        return [{"name": r[0], "kind": oc.kind_of(r[1])} for r in self.con.execute(f"DESCRIBE {oc._q(self.view)}").fetchall()]

    def count(self) -> int:
        return int(self.run(f"SELECT COUNT(*) AS n FROM {oc._q(self.view)}")[0]["n"])

    def close(self) -> None:
        try:
            self.con.close()
        except Exception:  # noqa: BLE001
            pass


def dashboards_for(u: dict) -> list[tuple[str, str]]:
    """The dashboards a person can open, for the wizard (value, label)."""
    ids = [p["id"] for p in store.dashboards()]
    vis = auth.access_map(u, ids)
    names = {p["id"]: p.get("name") or p["id"] for p in store.dashboards()}
    return [("", "None")] + [(i, names[i]) for i in ids if i in vis]


class DashboardPlatform(wb.Platform):
    id, label = "dashboards", "A dashboard's data"
    simulator = "a dashboard folder the tests write (data/*.csv), read by Ask Relay's DuckDB engine"
    reads = "the data of a dashboard you can open - DuckDB over its data folder, one guarded read-only SELECT at a time, as Ask Relay reads it"

    def test(self, ctx: wb.Ctx) -> list[dict]:
        pid = (ctx.scope.get("dashboard") or "").strip()
        if not pid:
            return []
        try:
            p = db.project(pid)
            owner = db.user(ctx.owner or "") or {}
            if not (p and auth.can_project(owner, "view", p)):
                return [{"source": pid, "kind": "Dashboard", "ok": False, "sees": "the owner of this work item cannot open that dashboard", "scope": ""}]
            _, tables = askd._extract_engine([pid], False)                     # noqa: SLF001
            return [{"source": store.load(pid).get("name") or pid, "kind": "Dashboard", "ok": True, "sees": f"{len(tables)} table(s)", "scope": "Read-only (Ask Relay's guard)"}]
        except (KeyError, FileNotFoundError):
            return [{"source": pid, "kind": "Dashboard", "ok": False, "sees": "no such dashboard", "scope": ""}]


DASHBOARDS = DashboardPlatform()


# ------------------------------------------------------------------ datasets of a work item

def _dataset(ref: dict, name: str, label: str, where: str) -> dict:
    key = {"file": lambda: f"file:{ref.get('file')}", "connection": lambda: f"conn:{ref.get('connection')}:{ref.get('object')}",
           "dashboard": lambda: f"dash:{ref.get('project')}:{ref.get('table')}"}[ref["source"]]()
    return {"key": key, "name": name, "label": label, "where": where, "ref": ref}


def datasets(ctx: wb.Ctx, cap: int = 25, warehouse_kinds: tuple = wb.WarehousePlatform.kinds) -> list[dict]:
    """The uploads (tables), the warehouse objects named in the scope (else the first the connection shows) and the
    tables of the dashboard chosen in the wizard."""
    out = []
    want = [x.strip().lower() for x in (ctx.scope.get("objects") or "").splitlines() if x.strip()]
    for f in ctx.files():
        if f.get("table"):
            out.append(_dataset({"source": "file", "item": ctx.id, "file": f["table"]}, Path(f["name"]).stem, f"{f['name']} (upload)", "upload"))
    for c in ctx.connections():
        if c["kind"] not in warehouse_kinds:
            continue
        try:
            objs = [o["object"] for o in connectors.browse(c)[:500]]
        except connectors.ConnectorError as e:
            raise wb.StepFailed(f"{c['name']} could not be read: {e}") from e
        pick = [o for o in objs if not want or any(o.lower() == w or o.lower().endswith("." + w) for w in want)][:cap]
        for o in pick:
            out.append(_dataset({"source": "connection", "connection": c["id"], "object": o}, o.split(".")[-1].lower(), f"{o} - {c['name']}", c["name"]))
    pid = (ctx.scope.get("dashboard") or "").strip()
    if pid:
        p = db.project(pid)
        owner = db.user(ctx.owner or "") or {}
        if not (p and auth.can_project(owner, "view", p)):
            raise wb.StepFailed("The owner of this work item cannot open the dashboard it names; pick one they can open.")
        try:
            con, tables = askd._extract_engine([pid], False)                   # noqa: SLF001
            con.close()
        except (KeyError, FileNotFoundError) as e:
            raise wb.StepFailed("That dashboard has no data to read.") from e
        nm = store.load(pid).get("name") or pid
        for t in sorted(tables)[:cap]:
            out.append(_dataset({"source": "dashboard", "project": pid, "table": t}, t, f"{t} - dashboard {nm}", f"dashboard {nm}"))
    seen: dict[str, int] = {}
    for d in out:
        seen[d["name"]] = seen.get(d["name"], 0) + 1
    for d in out:
        if seen[d["name"]] > 1:
            d["name"] = f"{d['name']}@{slug(d['where'], 20)}"
    return out


def reader(ctx: wb.Ctx, ref: dict):
    if ref.get("source") == "dashboard":
        p = db.project(ref.get("project") or "")
        owner = db.user(ctx.owner or "") or {}
        if not (p and auth.can_project(owner, "view", p)):
            raise wb.StepFailed("The owner of this work item can no longer open that dashboard.")
        return DashboardReader(ref["project"], ref["table"])
    return ctx.reader(ref)


def table_expr(r) -> str:
    if isinstance(r, DashboardReader):
        return oc._q(r.view)
    return wb.table_sql(r)


def close(r) -> None:
    if isinstance(r, DashboardReader):
        r.close()
    else:
        wb._close(r)


def columns(ctx: wb.Ctx, ref: dict) -> list[dict]:
    r = reader(ctx, ref)
    try:
        return r.columns()
    finally:
        close(r)


def kind_cols(cols: list[dict]) -> tuple[list[str], list[str], list[str]]:
    """(date columns, numeric columns, text columns) by kind."""
    dates = [c["name"] for c in cols if c["kind"] == "date"]
    nums = [c["name"] for c in cols if c["kind"] in NUMERIC and not re.search(r"(^|_)(id|key|code|no|number)$", c["name"], re.I)]
    text = [c["name"] for c in cols if c["kind"] == "string"]
    return dates, nums, text


def best_value(nums: list[str]) -> str | None:
    return next((n for n in nums if VALUE_WORDS.search(n)), nums[0] if nums else None)


def _qc(name: str) -> str:
    return oc._q(name)


def _cname(cols: list[dict], name: str) -> str | None:
    """A column as the source spells it (warehouses upper-case names)."""
    low = (name or "").lower()
    return next((c["name"] for c in cols if c["name"].lower() == low), None)


def series(ctx: wb.Ctx, ref: dict, date: str, value: str | None, grain: str = "month", agg: str = "sum",
           where: dict | None = None) -> tuple[list[str], list[float]]:
    """One aggregate query: the value per period of the grain (DuckDB dialect, transpiled for a warehouse)."""
    if grain not in dict(GRAINS):
        raise wb.StepFailed(f"Unknown grain {grain!r}: month, week, day or quarter.")
    r = reader(ctx, ref)
    try:
        cols = r.columns()
        d = _cname(cols, date)
        if not d:
            raise wb.StepFailed(f"{date} is not a column of this data.")
        if agg == "count":
            ex = "COUNT(*)"
        else:
            v = _cname(cols, value or "")
            if not v:
                raise wb.StepFailed(f"{value} is not a column of this data.")
            ex = {"sum": "SUM", "avg": "AVG", "max": "MAX", "min": "MIN"}.get(agg, "SUM") + f"(CAST({_qc(v)} AS DOUBLE))"
        cond = f"{_qc(d)} IS NOT NULL"
        if where and where.get("column"):
            w = _cname(cols, where["column"])
            if not w:
                raise wb.StepFailed(f"{where['column']} is not a column of this data.")
            cond += f" AND CAST({_qc(w)} AS VARCHAR) = '" + str(where.get("value") or "").replace("'", "''") + "'"
        p = f"CAST({_qc(d)} AS DATE)" if grain == "day" else f"CAST(DATE_TRUNC('{grain}', CAST({_qc(d)} AS DATE)) AS DATE)"
        rows = r.run(f"SELECT {p} AS p, {ex} AS y FROM {table_expr(r)} WHERE {cond} GROUP BY 1 ORDER BY 1")
    except oc.ReadError as e:
        raise wb.StepFailed(f"The data could not be read: {e}") from e
    finally:
        close(r)
    out_p, out_y = [], []
    for row in rows:
        row = {k.lower(): v for k, v in row.items()}
        if row.get("p") is None:
            continue
        out_p.append(str(row["p"])[:10])
        out_y.append(float(row.get("y") or 0.0))
    return out_p, out_y


def distinct(ctx: wb.Ctx, ref: dict, column: str, cap: int = 13) -> list[str]:
    r = reader(ctx, ref)
    try:
        c = _cname(r.columns(), column)
        if not c:
            raise wb.StepFailed(f"{column} is not a column of this data.")
        rows = r.run(f"SELECT DISTINCT CAST({_qc(c)} AS VARCHAR) AS v FROM {table_expr(r)} WHERE {_qc(c)} IS NOT NULL ORDER BY 1 LIMIT {int(cap)}")
    except oc.ReadError as e:
        raise wb.StepFailed(f"The data could not be read: {e}") from e
    finally:
        close(r)
    return [str({k.lower(): v for k, v in x.items()}["v"]) for x in rows]


def rows_of(ctx: wb.Ctx, ref: dict, limit: int = 5000) -> tuple[list[dict], list[dict]]:
    """(columns, up to `limit` rows) of a dataset - for row-level rules that compare each row."""
    r = reader(ctx, ref)
    try:
        cols = r.columns()
        rows = r.run(f"SELECT * FROM {table_expr(r)} LIMIT {int(limit)}")
    except oc.ReadError as e:
        raise wb.StepFailed(f"The data could not be read: {e}") from e
    finally:
        close(r)
    return cols, [{k: v for k, v in x.items()} for x in rows]


def lineage_table(ctx: wb.Ctx, ref: dict) -> str:
    """The dataset as a shared lineage node (own=False: other modules see the same table)."""
    if ref["source"] == "connection":
        try:
            c = connectors._row(ref["connection"])                         # noqa: SLF001
            return ctx.lineage_node("table", c["kind"], ref["object"], label=f"{ref['object']} ({connectors.KINDS.get(c['kind'], {}).get('label', c['kind'])})", own=False)
        except connectors.ConnectorError:
            pass
    if ref["source"] == "dashboard":
        return ctx.lineage_node("table", ref["project"], ref["table"], label=f"{ref['table']} (dashboard data)", own=False)
    return ctx.lineage_node("table", ref.get("item") or ctx.id, ref.get("file") or "upload", label=f"{ref.get('file')} (upload)", own=False)
