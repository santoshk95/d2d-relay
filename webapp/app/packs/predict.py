"""Predictive analytics & forecasting (registry id `predict`) - forecasts on the tenant's own data, with their accuracy
shown before anyone relies on them.

Data      uploads (CSV, Parquet, Excel) read with DuckDB, warehouse connections through the guarded read-only query,
          and a dashboard's data through Ask Relay's engine and guard - each opened with the work item owner's access.
Methods   simple and explainable only (predict_stats): seasonal naive (the baseline), exponential smoothing
          (Holt-Winters) and a linear trend with seasonality. Each is back-tested on the latest periods it never saw;
          accuracy is MAPE and WAPE against those actuals. A person chooses the model at Prove.
Assess    Connect -> Inventory -> Health -> Findings -> Estimate: which series can be forecast, and how well.
Develop   Question -> Data -> Model -> Prove -> Share -> Watch: the data confirmed, the models compared, the back-test
          confirmed in plain words, a named approval before the forecast reaches a dashboard, a team metric draft
          (four-eyes review in Formulas & metrics), a model registry (a write request each) and a scheduled refresh.
Change    Request -> Diagnose -> Fix -> Prove -> Approve -> Learn: a live forecast's settings changed, proven first.
Migrate   Discover -> Decide -> Convert -> Prove -> Hand over -> Run: a legacy forecast (an upload) compared side by side
          with Relay's on the same periods, then moved.
Run       Watch -> Alert -> Fix -> Approve -> Report: the scheduled refresh; accuracy against the actuals that arrived;
          a drift waits for a person before a model is switched, a ticket raised or Self-healing asked.
Forecasts are versioned in `predict_forecasts` / `predict_forecast_versions`; lineage: dataset -> forecast job ->
the forecast table on the dashboard."""
from __future__ import annotations

import csv
import io
import json
import secrets as _secrets
import time

from .. import auth, db, registry, semantic, store
from .. import workbench as wb
from . import predict_data as pdat
from . import predict_registries as preg
from . import predict_stats as ps

MODULE = "predict"
SYSTEM = "Relay forecasts"
MINUTES = {"confirm the data": 15, "choose the model": 10, "approve sharing": 10}
PERIOD_DAYS = {"day": 1, "week": 7, "month": 31, "quarter": 92}

db.register_schema("""
CREATE TABLE IF NOT EXISTS predict_forecasts (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, item TEXT, version INTEGER NOT NULL DEFAULT 1, spec TEXT NOT NULL DEFAULT '[]', datasets TEXT NOT NULL DEFAULT '[]',
  methods TEXT NOT NULL DEFAULT '{}', metrics TEXT NOT NULL DEFAULT '{}', output TEXT NOT NULL DEFAULT '[]', dashboard TEXT, file TEXT, run_item TEXT,
  owner_id TEXT, published_by TEXT, published REAL, status TEXT NOT NULL DEFAULT 'live', created REAL NOT NULL, updated REAL NOT NULL);
CREATE TABLE IF NOT EXISTS predict_forecast_versions (
  forecast_id TEXT NOT NULL, version INTEGER NOT NULL, spec TEXT NOT NULL, methods TEXT NOT NULL, metrics TEXT, item TEXT, published_by TEXT,
  published REAL NOT NULL, note TEXT, PRIMARY KEY (forecast_id, version));
""")

FILES = wb.FilesPlatform()
FILES.reads = "the files you upload (CSV, Parquet, Excel): a copy in this work item's folder, read with DuckDB"
WAREHOUSE = wb.WarehousePlatform()
PLATFORMS = {"files": FILES, "warehouse": WAREHOUSE, "dashboards": pdat.DASHBOARDS, "registry": preg.PLATFORM}


# ------------------------------------------------------------------ live forecasts (versioned, per tenant through db.q)

def forecast(fid: str, u: dict | None = None) -> dict | None:
    r = db.one("SELECT * FROM predict_forecasts WHERE id = ?", (fid,))
    if not r:
        return None
    if u is not None and r.get("item") and not auth.can_project(u, "view", db.project(r["item"])):
        return None
    return {**r, **{k: pdat.j(r[k], d) for k, d in (("spec", []), ("datasets", []), ("methods", {}), ("metrics", {}), ("output", []))}}


def forecasts(u: dict) -> list[dict]:
    out = []
    for r in db.q("SELECT id FROM predict_forecasts WHERE status = 'live' ORDER BY updated DESC"):
        f = forecast(r["id"], u)
        if f:
            out.append(f)
    return out


def forecast_options(u: dict) -> list[tuple[str, str]]:
    return [(f["id"], f"{f['name']} - version {f['version']} - {len(f['spec'])} series") for f in forecasts(u)]


def publish(ctx: wb.Ctx, rows: list[dict], dsets: list[dict], methods: dict, metrics: dict, output: list[dict], fid: str | None = None,
            note: str = "", dashboard: str | None = None, file: str | None = None) -> dict:
    """A new live forecast, or a new version of one; every version is kept."""
    now = time.time()
    who = ctx.who or ctx.owner
    spec = [{k: r.get(k) for k in ("id", "label", "dataset", "date", "value", "agg", "grain", "where_col", "where_val", "horizon")} for r in rows]
    if fid and db.one("SELECT 1 FROM predict_forecasts WHERE id = ?", (fid,)):
        v = db.one("SELECT version FROM predict_forecasts WHERE id = ?", (fid,))["version"] + 1
        db.run("UPDATE predict_forecasts SET version = ?, spec = ?, datasets = ?, methods = ?, metrics = ?, output = ?, published_by = ?, published = ?, updated = ?, "
               "dashboard = COALESCE(?, dashboard), file = COALESCE(?, file) WHERE id = ?",
               (v, json.dumps(spec), json.dumps(dsets), json.dumps(methods), json.dumps(metrics), json.dumps(output), who, now, now, dashboard, file, fid))
    else:
        fid, v = "pfc-" + _secrets.token_hex(4), 1
        db.run("INSERT INTO predict_forecasts (id, name, item, version, spec, datasets, methods, metrics, output, dashboard, file, owner_id, published_by, published, status, created, updated) "
               "VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'live', ?, ?)",
               (fid, ctx.title[:160], ctx.id, json.dumps(spec), json.dumps(dsets), json.dumps(methods), json.dumps(metrics), json.dumps(output), dashboard, file,
                ctx.owner, who, now, now, now))
    db.run("INSERT OR REPLACE INTO predict_forecast_versions (forecast_id, version, spec, methods, metrics, item, published_by, published, note) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
           (fid, v, json.dumps(spec), json.dumps(methods), json.dumps(metrics), ctx.id, who, now, note[:500] or None))
    db.audit("predict.forecast.publish", fid, {"version": v, "series": len(spec), "item": ctx.id, "methods": methods}, who)
    return forecast(fid)


# ------------------------------------------------------------------ series: what a person confirms at Data

def _dmap(ctx: wb.Ctx) -> dict:
    return {d["key"]: d for d in ctx.get("datasets") or []}


def _ds_options(ctx: wb.Ctx):
    return [(d["key"], d["name"]) for d in ctx.get("datasets") or []]


def label(r: dict, dmap: dict | None = None) -> str:
    ds = (dmap or {}).get(r.get("dataset")) or {}
    base = f"{r.get('value') if r.get('agg') != 'count' else 'rows'} by {r.get('grain')}"
    if r.get("where_col") and r.get("where_val") not in (None, ""):
        base += f" - {r['where_col']} = {r['where_val']}"
    return base + (f" ({ds['name']})" if ds.get("name") else "")


def load_series(ctx: wb.Ctx, r: dict, dmap: dict) -> tuple[list[str], list[float]]:
    ds = dmap.get(r.get("dataset"))
    if not ds:
        raise wb.StepFailed(f"{r.get('label') or r.get('id')}: its dataset is not one this work item reads.")
    where = {"column": r["where_col"], "value": r.get("where_val")} if r.get("where_col") else None
    return pdat.series(ctx, ds["ref"], r.get("date") or "", r.get("value"), r.get("grain") or "month", r.get("agg") or "sum", where)


def is_forecast_table(cols: list[dict]) -> bool:
    names = {c["name"].lower() for c in cols}
    return {"forecast", "lower_80", "upper_80"} <= names


def _suggest(ctx: wb.Ctx, dsets: list[dict]) -> list[dict]:
    """One series per dataset that has a date and a number - the wizard's choices first, else Relay's guess - and one
    per value of the split-by column when the person named one (up to 12)."""
    sc = ctx.scope
    out = []
    for d in dsets:
        cols = pdat.columns(ctx, d["ref"])
        if is_forecast_table(cols):
            continue                                        # Relay's own published forecast: not a series to forecast
        dates, nums, _ = pdat.kind_cols(cols)
        date = pdat._cname(cols, sc.get("date") or "") or (dates[0] if dates else None)
        value = pdat._cname(cols, sc.get("value") or "") or pdat.best_value(nums)
        if not date or not value:
            continue
        base = {"include": True, "dataset": d["key"], "date": date, "value": value, "agg": "sum", "grain": sc.get("grain") or "month",
                "where_col": "", "where_val": "", "horizon": int(sc.get("horizon") or 6)}
        by = pdat._cname(cols, sc.get("by") or "")
        if by:
            for v in pdat.distinct(ctx, d["ref"], by, 13)[:12]:
                out.append({**base, "id": f"s-{pdat.slug(d['name'], 16)}-{pdat.slug(v, 16)}", "where_col": by, "where_val": v})
        else:
            out.append({**base, "id": f"s-{pdat.slug(d['name'], 24)}-{pdat.slug(value, 16)}"})
        if len(out) >= 24:
            break
    return out


def _validate_series(recs: list[dict], ctx: wb.Ctx) -> list[str]:
    """Rules first: a series that cannot be read is refused, with the reason on its row."""
    dmap = _dmap(ctx)
    probs = []
    on = [r for r in recs if r.get("include")]
    if not on:
        probs.append("Include at least one series.")
    cache: dict = {}
    for i, r in enumerate(recs, 1):
        r["problem"] = ""
        if not r.get("include"):
            continue
        ds = dmap.get(r.get("dataset"))
        p = []
        if not ds:
            p.append("pick one of the datasets")
        else:
            cols = cache.get(ds["key"]) or cache.setdefault(ds["key"], pdat.columns(ctx, ds["ref"]))
            names = {c["name"].lower() for c in cols}
            if (r.get("date") or "").lower() not in names:
                p.append(f"{r.get('date') or '(blank)'} is not a column (date)")
            if r.get("agg") != "count" and (r.get("value") or "").lower() not in names:
                p.append(f"{r.get('value') or '(blank)'} is not a column (value)")
            if r.get("where_col") and r["where_col"].lower() not in names:
                p.append(f"{r['where_col']} is not a column (filter)")
        if r.get("grain") not in dict(pdat.GRAINS):
            p.append("grain is month, week, day or quarter")
        try:
            h = int(r.get("horizon") or 0)
            if not 1 <= h <= 36:
                p.append("the horizon is 1 to 36 periods")
        except (TypeError, ValueError):
            p.append("the horizon is a number of periods")
        if p:
            r["problem"] = "; ".join(p)
            probs.append(f"Row {i}: " + r["problem"])
    return probs


SERIES_COLUMNS = [wb.Column("include", "Use", "bool"), wb.Column("dataset", "Dataset", "select", options=_ds_options), wb.Column("date", "Date column"),
                  wb.Column("value", "What to forecast"), wb.Column("agg", "How", "select", options=pdat.AGGS), wb.Column("grain", "By", "select", options=pdat.GRAINS),
                  wb.Column("where_col", "Only rows where (column)"), wb.Column("where_val", "... equals"), wb.Column("horizon", "Periods ahead", "number"),
                  wb.Column("summary", "What Relay read", readonly=True)]
SERIES_EDIT = wb.Edit(columns=SERIES_COLUMNS, validate=_validate_series, label="series")


def _series_table(recs: list[dict], dmap: dict) -> dict:
    return {"columns": ["Use", "Series", "Dataset", "Periods", "From", "To", "Gaps", "Total"],
            "rows": [["yes" if r.get("include") else "no", label(r), (dmap.get(r.get("dataset")) or {}).get("name", "?"), r.get("periods"), r.get("from"), r.get("to"),
                      r.get("gaps"), r.get("total")] for r in recs]}


def _read_rows(ctx: wb.Ctx, recs: list[dict], dmap: dict) -> list[dict]:
    for r in recs:
        r["label"] = label(r, dmap)
        if not r.get("include"):
            continue
        try:
            p, y = load_series(ctx, r, dmap)
        except wb.StepFailed as e:
            r.update(periods=0, summary=f"could not read: {str(e)[:160]}", problem=str(e)[:200])
            continue
        g = ps.gaps(p, r.get("grain") or "month")
        r.update(periods=len(p), **{"from": p[0] if p else None, "to": p[-1] if p else None}, gaps=g, total=round(sum(y), 2),
                 summary=f"{len(p)} {r.get('grain')}s, {p[0] if p else '-'} to {p[-1] if p else '-'}" + (f", {g} missing" if g else ""))
        ctx.evidence(f"Series: {r['label']}", {"series": r["label"], "rows": [{"period": a, "value": b} for a, b in zip(p, y)]}, kind="series", ok=bool(p))
    return recs


# ------------------------------------------------------------------ Develop

def d_question(ctx: wb.Ctx) -> dict:
    dsets = pdat.datasets(ctx)
    if not dsets:
        raise wb.StepFailed("Nothing to forecast from: upload the data (CSV, Parquet or Excel), pick a warehouse connection and name its tables, or choose a dashboard.")
    ctx.put("datasets", dsets)
    rows = []
    for d in dsets:
        cols = pdat.columns(ctx, d["ref"])
        dates, nums, text = pdat.kind_cols(cols)
        rows.append([d["name"], d["where"], ", ".join(dates) or "-", ", ".join(nums[:8]) or "-", ", ".join(text[:6]) or "-"])
    sug = _suggest(ctx, dsets)
    ctx.put("suggested", sug)
    if not sug:
        raise wb.StepFailed("None of the data has both a date column and a number to forecast.")
    q = (ctx.brief or "").strip() or f"Forecast {sug[0]['value']} by {sug[0]['grain']}"
    return {"summary": f"The question: {q[:200]}. {len(dsets)} dataset(s) read; Relay suggests {len(sug)} series - you confirm the data next.",
            "counts": {"datasets": len(dsets), "series suggested": len(sug)},
            "data": {"columns": ["Dataset", "Where", "Date columns", "Numbers", "Text"], "rows": rows}}


def d_data(ctx: wb.Ctx) -> dict:
    dmap = _dmap(ctx)
    have = ctx.records(ctx.step_id)                         # a person's edits survive a re-run
    recs = have or [dict(r) for r in ctx.get("suggested") or []]
    recs = _read_rows(ctx, recs, dmap)
    on = [r for r in recs if r.get("include")]
    short = [r for r in on if (r.get("periods") or 0) < 8]
    for r in short:
        r["problem"] = (r.get("problem") or f"only {r.get('periods') or 0} periods: a back-test needs at least 8")
    return {"summary": f"{len(on)} series to forecast from {len({r['dataset'] for r in on})} dataset(s)" + (f"; {len(short)} with too little history" if short else "")
            + ". Check what the model will use - change a column, the grain, the horizon or a filter - then confirm.",
            "counts": {"series": len(on), "short": len(short)}, "records": recs, "data": _series_table(recs, dmap),
            "items": [f"{r['label']}: {r.get('summary') or ''}" for r in on[:6]]}


def _backtests(ctx: wb.Ctx, rows: list[dict], dmap: dict, holdout: dict | None = None) -> dict:
    out = {}
    for r in rows:
        p, y = load_series(ctx, r, dmap)
        if len(p) < 8:
            raise wb.StepFailed(f"{r['label']}: only {len(p)} periods - a back-test needs at least 8.")
        m = ps.season_for(r.get("grain") or "month", len(p))
        bt = ps.backtest(p, y, ps.SEASON.get(r.get("grain") or "month", 1) if m > 1 else 1, int(r.get("horizon") or 6), (holdout or {}).get(r["id"]))
        bt["series"], bt["n"], bt["last"] = r["label"], len(p), p[-1]
        out[r["id"]] = bt
        ctx.evidence(f"Back-test: {r['label']}", {"series": r["label"], "holdout": bt["holdout"], "test_from": bt["test_from"], "test_to": bt["test_to"],
                                                    "rows": [{"period": pp, "actual": a, **{mm: bt["models"][mm]["forecast"][i] for mm in bt["models"]}} for i, (pp, a) in enumerate(zip(bt["periods"], bt["actual"]))],
                                                    "accuracy": {mm: {k: v for k, v in x.items() if k in ("mape", "wape", "bias", "rmse")} for mm, x in bt["models"].items()}},
                     kind="backtest", ok=True)
    return out


def _model_rows(bts: dict, chosen: dict | None = None) -> list[list]:
    rows = []
    for sid, bt in bts.items():
        for mm, x in bt["models"].items():
            rows.append([bt["series"], ps.METHODS[mm], x["mape"], x["wape"], x["bias"], "chosen" if (chosen or {}).get(sid) == mm else "recommended" if bt["recommended"] == mm else ""])
    return rows


def d_model(ctx: wb.Ctx) -> dict:
    dmap = _dmap(ctx)
    rows = [r for r in ctx.records("data") if r.get("include")]
    bts = _backtests(ctx, rows, dmap)
    ctx.put("series", rows)
    ctx.put("backtests", bts)
    beat = sum(1 for bt in bts.values() if bt["recommended"] != "seasonal_naive")
    recs = _choice_records(ctx, bts, ctx.step_id)                # a person's choice survives a re-run
    return {"summary": f"Three methods back-tested on {len(bts)} series - each trained on the history before the holdout and scored on periods it never saw. "
                       f"For {beat} of {len(bts)} series a method beats the seasonal-naive baseline. Choose the model per series (Relay's pick is preselected: "
                       "the simplest one that is accurate enough), then confirm.",
            "counts": {"series": len(bts), "methods": 3, "beat the baseline": beat}, "records": recs,
            "data": {"columns": ["Series", "Method", "MAPE %", "WAPE %", "Bias %", "Relay"], "rows": _model_rows(bts, {r["id"]: r["method"] for r in recs})},
            "items": [f"{r['series']}: {ps.METHODS[r['method']]}" for r in recs[:6]]}


def _plain(bt: dict, meth: str) -> str:
    x, base = bt["models"][meth], bt["models"]["seasonal_naive"]
    s = (f"{bt['series']}: over the {bt['holdout']} {('periods' if bt['holdout'] != 1 else 'period')} held back ({bt['test_from']} to {bt['test_to']}), "
         f"{ps.METHODS[meth].lower()} was off by {pdat.fmt(x['wape'], 1)} % of the actual total (WAPE; {pdat.fmt(x['mape'], 1)} % per period on average)")
    if meth != "seasonal_naive":
        s += f", against {pdat.fmt(base['wape'], 1)} % for the seasonal-naive baseline"
    return s + "."


def _gates(ctx: wb.Ctx, bts: dict, chosen: dict, target: float) -> list[dict]:
    checks = []
    for sid, bt in bts.items():
        meth = chosen.get(sid) or bt["recommended"]
        x, base = bt["models"][meth], bt["models"]["seasonal_naive"]
        ev = ctx.evidence(f"Prove: {bt['series']}", {"series": bt["series"], "method": meth, "plain": _plain(bt, meth), "accuracy": x, "baseline": base,
                                                      "rows": [{"period": p, "actual": a, "forecast": f} for p, a, f in zip(bt["periods"], bt["actual"], x["forecast"])]}, kind="proof", ok=True)
        beats = meth == "seasonal_naive" or (x["wape"] is not None and base["wape"] is not None and x["wape"] < base["wape"])
        checks.append({"name": f"{sid}:baseline", "label": f"{bt['series']} - beats the seasonal-naive baseline", "status": "pass" if beats and meth != "seasonal_naive" else "warn" if meth == "seasonal_naive" else "fail",
                       "measured": f"WAPE {pdat.fmt(x['wape'], 1)} %", "expected": f"below {pdat.fmt(base['wape'], 1)} %",
                       "detail": "the baseline itself is chosen: nothing simple beats it" if meth == "seasonal_naive" else ("more accurate than repeating last cycle" if beats else "less accurate than repeating last cycle"), "evidence": ev})
        ok = x["wape"] is not None and x["wape"] <= target
        checks.append({"name": f"{sid}:target", "label": f"{bt['series']} - within the accuracy target", "status": "pass" if ok else "warn",
                       "measured": f"WAPE {pdat.fmt(x['wape'], 1)} %", "expected": f"at most {pdat.fmt(target, 1)} %",
                       "detail": _plain(bt, meth), "evidence": ev})
        checks.append({"name": f"{sid}:holdout", "label": f"{bt['series']} - tested on periods the model never saw", "status": "pass",
                       "measured": f"{bt['holdout']} period(s): {bt['test_from']} to {bt['test_to']}", "expected": f"after the training data (to {bt['train_to']})",
                       "detail": "trained before the holdout, scored on it", "evidence": ev})
        enough = bt["season"] > 1
        checks.append({"name": f"{sid}:history", "label": f"{bt['series']} - enough history for the seasonal shape", "status": "pass" if enough else "warn",
                       "measured": f"{bt['n']} periods", "expected": "two full cycles", "detail": "seasonal methods used" if enough else "fewer than two cycles: the season is not modelled", "evidence": ev})
    return checks


def _validate_choice(recs: list[dict], ctx: wb.Ctx) -> list[str]:
    return [f"Row {i}: pick one of the three methods" for i, r in enumerate(recs, 1) if r.get("method") not in ps.METHODS]


CHOICE_EDIT = wb.Edit(columns=[wb.Column("method", "Model to use", "select", options=tuple(ps.METHODS.items())), wb.Column("series", "Series", readonly=True),
                               wb.Column("naive", "Seasonal naive WAPE %", "number", readonly=True), wb.Column("linear", "Linear trend WAPE %", "number", readonly=True),
                               wb.Column("ets", "Exponential smoothing WAPE %", "number", readonly=True), wb.Column("why", "Why Relay recommends it", readonly=True)],
                      add=False, remove=False, validate=_validate_choice, label="series")


def _choice_records(ctx: wb.Ctx, bts: dict, sid_step: str) -> list[dict]:
    have = {r["id"]: r for r in ctx.records(sid_step)}
    recs = []
    for sid, bt in bts.items():
        m = bt["models"]
        rec = bt["recommended"]
        recs.append({"id": sid, "series": bt["series"], "method": (have.get(sid) or {}).get("method") or rec, "naive": m["seasonal_naive"]["wape"],
                     "linear": m["linear_seasonal"]["wape"], "ets": m["ets"]["wape"], "why": f"{ps.METHODS[rec]}: {ps.WHY[rec]}; lowest error, simplest when close"})
    return recs


def _charts(ctx: wb.Ctx, bts: dict, prefix: str = "backtest") -> None:
    for sid, bt in bts.items():
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["period", "actual", *bt["models"]])
        for i, (p, a) in enumerate(zip(bt["periods"], bt["actual"])):
            w.writerow([p, a, *[bt["models"][mm]["forecast"][i] for mm in bt["models"]]])
        ctx.output(f"{prefix}-{pdat.slug(sid, 50)}.csv", buf.getvalue(), label=f"Back-test: {bt['series']} (CSV)")
        ctx.output(f"{prefix}-{pdat.slug(sid, 50)}.svg", ps.svg_chart(f"Back-test: {bt['series']}", bt["periods"], bt["actual"],
                                                                      {ps.METHODS.get(mm, "Legacy forecast"): bt["models"][mm]["forecast"] for mm in bt["models"]}), label=f"Back-test chart: {bt['series']}")


def d_prove(ctx: wb.Ctx) -> dict:
    bts = ctx.get("backtests") or {}
    chosen = {r["id"]: r["method"] for r in ctx.records("model")}
    target = float(ctx.scope.get("target") or 20)
    checks = _gates(ctx, bts, chosen, target)
    _charts(ctx, bts)
    words = [_plain(bts[sid], chosen.get(sid) or bt["recommended"]) for sid, bt in bts.items()]
    bad = sum(1 for c in checks if c["status"] == "fail")
    return {"summary": " ".join(words[:3])[:1500] + (f" ({len(words) - 3} more series below.)" if len(words) > 3 else "")
            + " Confirm to share these forecasts, or send them back to choose another model.",
            "counts": {"series": len(bts), "fail": bad, "warn": sum(1 for c in checks if c["status"] == "warn")}, "data": {"checks": checks}, "items": words[:6]}


def d_share(ctx: wb.Ctx) -> dict:
    bts = ctx.get("backtests") or {}
    chosen = {r["id"]: r["method"] for r in ctx.records("model")}
    ctx.put("chosen", chosen)
    dash = (ctx.scope.get("publish_to") or "").strip()
    dname = (store.load(dash).get("name") if dash and db.project(dash) else None) if dash else None
    cad = ctx.scope.get("cadence") or {"every": "week", "at": "06:00", "weekday": 0, "tz": "UTC"}
    regs = [c for c in ctx.connections() if c["kind"] in preg.KINDS]
    items = [{"title": bts[sid]["series"], "detail": f"{ps.METHODS[m]} - back-tested WAPE {pdat.fmt(bts[sid]['models'][m]['wape'], 1)} %, {bts[sid]['holdout']} period(s) held back"} for sid, m in chosen.items() if sid in bts]
    items.append({"title": "Where it goes", "detail": (f"the dashboard \"{dname}\" gets the forecast table forecast_{pdat.slug(ctx.title, 30)}.csv" if dname else "the forecast table stays in this work item's outputs (no dashboard chosen)")
                  + "; a team metric draft for Formulas & metrics (four-eyes review before it is certified)"})
    if regs:
        items.append({"title": "Model registry", "detail": ", ".join(f"{c['name']} ({preg.LABEL[c['kind']]})" for c in regs) + ": a registration request each - read-only until that write is approved too"})
    items.append({"title": "Then", "detail": f"a Run item refreshes the forecast {wb.schedule_text(wb.check_schedule(cad)).lower()} and watches its accuracy; a drift waits for a person"})
    approver = db.user(ctx.st.get("approver") or "") or {}
    items.append({"title": "Named approval", "detail": approver.get("name") or "the owner of this work item"})
    return {"summary": f"Share {len(chosen)} forecast(s)" + (f" to \"{dname}\"" if dname else "") + " - nothing reaches a report before this approval.", "data": {"items": items}}


def forecast_rows(ctx: wb.Ctx, rows: list[dict], dmap: dict, methods: dict, bts: dict | None = None) -> tuple[list[dict], dict]:
    """Each series refitted on its whole history with its chosen method; the 80 % range from the back-test's error."""
    out, metrics = [], {}
    for r in rows:
        p, y = load_series(ctx, r, dmap)
        grain = r.get("grain") or "month"
        m = ps.SEASON.get(grain, 1) if ps.season_for(grain, len(p)) > 1 else 1
        meth = methods.get(r["id"]) or "seasonal_naive"
        h = int(r.get("horizon") or 6)
        fc, params = ps.forecast(meth, y, m, h)
        bt = (bts or {}).get(r["id"]) or ps.backtest(p, y, m, h)
        acc = bt["models"][meth]
        half = ps.interval(acc.get("rmse"))
        for per, v in zip(ps.period_labels(p[-1], grain, h), fc):
            out.append({"series": r.get("label") or label(r, dmap), "series_id": r["id"], "period": per, "forecast": round(v, 2), "lower": round(v - half, 2),
                        "upper": round(v + half, 2), "method": meth})
        metrics[r["id"]] = {"method": meth, "wape": acc["wape"], "mape": acc["mape"], "holdout": bt["holdout"], "last": p[-1], "params": params}
    return out, metrics


def _csv(rows: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["series", "period", "forecast", "lower_80", "upper_80", "method"])
    for x in rows:
        w.writerow([x["series"], x["period"], x["forecast"], x["lower"], x["upper"], x["method"]])
    return buf.getvalue()


def to_dashboard(ctx: wb.Ctx, pid: str, name: str, text: str) -> dict:
    """The approved forecast table into a dashboard's data folder - only a dashboard the owner may change."""
    p = db.project(pid)
    owner = db.user(ctx.owner or "") or {}
    if not (p and auth.can_project(owner, "edit", p)):
        return {"ok": False, "status": "not written: the owner of this work item cannot change that dashboard"}
    d = store.project_dir(pid) / "data"
    d.mkdir(exist_ok=True)
    (d / name).write_text(text, encoding="utf-8")
    db.audit("predict.forecast.to_dashboard", pid, {"file": name, "item": ctx.id}, ctx.who or ctx.owner)
    return {"ok": True, "status": f"written to the dashboard's data as {name}", "file": name}


def metric_draft(ctx: wb.Ctx, table: str, fc_name: str) -> dict:
    """A team metric draft (Formulas & metrics): the forecast as a measure, reviewed by a second person before it is certified."""
    u = db.user(ctx.owner or "") or {}
    team = (db.project(ctx.id) or {}).get("team_id")
    if not team or not semantic._team_dev(u, team):                     # noqa: SLF001
        return {"ok": False, "status": "no draft: the owner is not a builder of the item's team"}
    try:
        m = semantic.save_draft(team, f"Forecast: {fc_name}"[:120], {"label": f"Forecast: {fc_name}"[:80], "dax": f"SUM ( '{table}'[forecast] )",
                                                                       "description": f"Relay forecast from work item {ctx.id}; the 80 % range is in lower_80 / upper_80.", "folder": "Forecasts"}, u, source=f"wb:{ctx.id}")
    except semantic.SemanticError as e:
        return {"ok": False, "status": f"no draft: {e}"}
    return {"ok": True, "status": f"metric draft \"{m['name']}\" (version {m['versions'][-1]['version']}) waits for review", "metric": m["id"]}


def _record_lineage(ctx: wb.Ctx, fc: dict, dash: str | None, file: str | None) -> None:
    job = ctx.lineage_node("job", SYSTEM, f"Forecast: {fc['name']}", label=f"Forecast: {fc['name']} (v{fc['version']})", properties={"forecast": fc["id"], "version": fc["version"]})
    for d in fc["datasets"]:
        ctx.lineage_edge(pdat.lineage_table(ctx, d["ref"]), job, "reads", {"series": sum(1 for s in fc["spec"] if s.get("dataset") == d["key"])})
    if dash and file:
        out = ctx.lineage_node("table", dash, file, label=f"{file} (dashboard data)", own=False)
        ctx.lineage_edge(job, out, "writes", {"version": fc["version"]})


def _run_item(ctx: wb.Ctx, fc: dict, cad: dict) -> str:
    rid = fc.get("run_item")
    if rid and db.one("SELECT 1 FROM wb_items WHERE id = ? AND closed IS NULL", (rid,)):
        return rid
    p = db.project(ctx.id) or {}
    item = wb.create(MODULE, "run", f"Run: {ctx.title}"[:160], who=ctx.owner, brief=f"Scheduled refresh and accuracy watch of the forecast \"{fc['name']}\", published from {ctx.id}.",
                     connections=[c for c in ctx.st.get("connections") or []], scope={"forecast": fc["id"], "schedule": cad}, approver=ctx.st.get("approver"),
                     visibility=p.get("visibility") or "private", team_id=p.get("team_id"), parent=ctx.id)
    db.run("UPDATE predict_forecasts SET run_item = ? WHERE id = ?", (item["id"], fc["id"]))
    return item["id"]


def share_out(ctx: wb.Ctx, rows: list[dict], dmap: dict, methods: dict, bts: dict | None, fid: str | None, note: str) -> tuple[dict, list[list]]:
    """Publish (a new version of) a forecast: the table as an output, the dashboard's copy, the metric draft, the
    registry requests and the lineage. Called only after the named approval."""
    out_rows, metrics = forecast_rows(ctx, rows, dmap, methods, bts)
    text = _csv(out_rows)
    ctx.output("forecast.csv", text, label="The forecast (CSV, with the 80 % range)")
    dash = (ctx.scope.get("publish_to") or "").strip() or None
    prev = forecast(fid) if fid else None
    dash = dash or (prev or {}).get("dashboard")
    name = (prev or {}).get("file") or f"forecast_{pdat.slug(ctx.title, 30).replace('-', '_')}.csv"
    rows_out = []
    wrote = to_dashboard(ctx, dash, name, text) if dash else {"ok": False, "status": "no dashboard chosen: the table is in the outputs"}
    rows_out.append(["Dashboard", wrote["status"]])
    fc = publish(ctx, rows, list(dmap.values()), methods, metrics, out_rows, fid, note, dashboard=dash if wrote["ok"] else None, file=name if wrote["ok"] else None)
    if not prev:
        md = metric_draft(ctx, name.rsplit(".", 1)[0], fc["name"])
        rows_out.append(["Formulas & metrics", md["status"]])
    for c in ctx.connections():
        if c["kind"] in preg.KINDS:
            h = preg.request_deploy(ctx, c, fc)
            rows_out.append([preg.LABEL[c["kind"]], h.get("status") or "requested"])
    _record_lineage(ctx, fc, dash if wrote["ok"] else None, name if wrote["ok"] else None)
    return fc, rows_out


def d_watch(ctx: wb.Ctx) -> dict:
    rows = ctx.get("series") or []
    fc, rows_out = share_out(ctx, rows, _dmap(ctx), ctx.get("chosen") or {}, ctx.get("backtests"), ctx.get("forecast"), "go-live from Develop")
    ctx.put("forecast", fc["id"])
    cad = wb.check_schedule(ctx.scope.get("cadence") or {"every": "week", "at": "06:00", "weekday": 0, "tz": "UTC"})
    rid = _run_item(ctx, fc, cad)
    rows_out.append(["Scheduled refresh", f"{wb.schedule_text(cad)} - Run item {rid}"])
    ctx.evidence("Shared", {"rows": [{"where": a, "what": b} for a, b in rows_out]}, kind="share", ok=True)
    return {"summary": f"Forecast \"{fc['name']}\" version {fc['version']} is live: {len(fc['output'])} forecast rows for {len(fc['spec'])} series; refreshed {wb.schedule_text(cad).lower()}.",
            "counts": {"version": fc["version"], "series": len(fc["spec"]), "rows": len(fc["output"])},
            "data": {"href": f"#/m/{MODULE}/i/{rid}", "label": "Open the Run item", "text": " - ".join(f"{a}: {b}" for a, b in rows_out)}}


# ------------------------------------------------------------------ Assess

def a_connect(ctx: wb.Ctx) -> dict:
    rows = []
    for p in (FILES, WAREHOUSE, pdat.DASHBOARDS, preg.PLATFORM):
        rows += p.test(ctx)
    if not rows:
        raise wb.StepFailed("Nothing to read: upload files, pick a warehouse or model registry connection, or choose a dashboard.")
    good = [r for r in rows if r["ok"]]
    if not good:
        raise wb.StepFailed("None of the sources answered: " + "; ".join(f"{r['source']}: {r['sees']}" for r in rows)[:600])
    return {"summary": f"{len(good)} of {len(rows)} source(s) answered - read-only.", "counts": {"sources": len(rows), "answered": len(good)},
            "data": {"columns": ["Source", "Kind", "Status", "What Relay sees", "Access"], "rows": [[r["source"], r["kind"], "answered" if r["ok"] else "refused", r["sees"], r["scope"]] for r in rows]}}


def a_inventory(ctx: wb.Ctx) -> dict:
    dsets = pdat.datasets(ctx)
    ctx.put("datasets", dsets)
    recs = []
    for d in dsets:
        cols = pdat.columns(ctx, d["ref"])
        if is_forecast_table(cols):
            continue
        dates, nums, _ = pdat.kind_cols(cols)
        best = pdat.best_value(nums)
        for dc in dates[:2]:
            for n in nums[:6]:
                recs.append({"id": f"c-{pdat.slug(d['name'], 20)}-{pdat.slug(dc, 12)}-{pdat.slug(n, 16)}", "include": n == best and dc == dates[0], "dataset": d["key"], "dataset_name": d["name"],
                             "date": dc, "value": n, "grain": ctx.scope.get("grain") or "month", "agg": "sum", "where_col": "", "where_val": "", "horizon": int(ctx.scope.get("horizon") or 6)})
    models = preg.inventory(ctx)
    ctx.put("models", models)
    if not recs and not models:
        raise wb.StepFailed("No date-and-number pairs in the data and no models in the registries: nothing to forecast yet.")
    return {"summary": f"{len(recs)} candidate series in {len(dsets)} dataset(s)" + (f" and {len(models)} model(s) already in the registries" if models else "")
            + " - the likeliest series per dataset is ticked; untick or tick what matters.",
            "counts": {"candidates": len(recs), "included": sum(1 for r in recs if r["include"]), "registry models": len(models)}, "records": recs,
            "data": {"columns": ["Use", "Dataset", "Date", "Value"], "rows": [["yes" if r["include"] else "no", r["dataset_name"], r["date"], r["value"]] for r in recs]
                     + [["(registry)", m["registry"], m["name"], f"version {m.get('version') or '-'} - {m.get('stage') or ''}"] for m in models]}}


def a_health(ctx: wb.Ctx) -> dict:
    dmap = _dmap(ctx)
    rows = [dict(r, label=label(r, dmap)) for r in ctx.records("inventory") if r.get("include")]
    if not rows:
        raise wb.StepFailed("No series is included: tick at least one in the inventory.")
    checks, findings = [], []
    for r in rows:
        try:
            p, y = load_series(ctx, r, dmap)
        except wb.StepFailed as e:
            checks.append({"name": r["id"], "label": r["label"], "status": "error", "measured": "", "expected": "", "detail": str(e)[:300]})
            continue
        m = ps.SEASON.get(r["grain"], 1)
        st = ps.strength(y, m)
        g = ps.gaps(p, r["grain"])
        zeros = sum(1 for v in y if v == 0) / len(y) if y else 0
        bt = ps.backtest(p, y, m if ps.season_for(r["grain"], len(p)) > 1 else 1, int(r.get("horizon") or 6), methods=("seasonal_naive", "ets")) if len(p) >= 8 else None
        best = min((x["wape"] for x in (bt or {}).get("models", {}).values() if x["wape"] is not None), default=None)
        grade = "good" if best is not None and best <= 15 else "fair" if best is not None and best <= 30 else "poor"
        ev = ctx.evidence(f"Health: {r['label']}", {"series": r["label"], "periods": len(p), "gaps": g, "seasonality": st, "zero_share": round(zeros, 3), "backtest": (bt or {}).get("models"),
                                                    "rows": [{"period": a, "value": b} for a, b in zip(p, y)]}, kind="profile", ok=True)
        issues = []
        if len(p) < 2 * m:
            issues.append((f"only {len(p)} periods: fewer than two full cycles, so the season cannot be learned", "high" if len(p) < 8 else "medium"))
        if g:
            issues.append((f"{g} missing period(s) inside the history", "medium"))
        if zeros > 0.3:
            issues.append((f"{zeros:.0%} of the periods are zero: an intermittent series", "medium"))
        if best is not None and best > 30:
            issues.append((f"even the best simple method is off by {pdat.fmt(best, 1)} % (WAPE) on the holdout", "high"))
        for i, (txt, sev) in enumerate(issues):
            findings.append({"id": f"{r['id']}-{i}", "series": r["label"], "issue": txt, "severity": sev, "decision": "keep", "evidence": ev})
        checks.append({"name": r["id"], "label": f"Forecastability of {r['label']}", "status": "pass" if grade == "good" and not issues else "warn" if grade != "poor" else "fail",
                       "measured": f"{len(p)} periods - best WAPE {pdat.fmt(best, 1)} %", "expected": "", "evidence": ev,
                       "detail": f"{grade}: " + (f"seasonality strength {st}" if st is not None else "no full cycles yet") + (f"; {len(issues)} issue(s)" if issues else "")})
    ctx.put("findings", findings)
    ctx.put("graded", [dict(r, grade=next((c["detail"].split(":")[0] for c in checks if c["name"] == r["id"]), "poor")) for r in rows])
    return {"summary": f"{len(rows)} series profiled and back-tested (seasonal naive and exponential smoothing); {len(findings)} issue(s) found.",
            "counts": {"series": len(rows), "issues": len(findings)}, "data": {"checks": checks}}


FINDINGS_EDIT = wb.Edit(columns=[wb.Column("decision", "Decision", "select", options=(("keep", "Keep"), ("ignore", "Ignore"))),
                                 wb.Column("severity", "Severity", "select", options=("high", "medium", "low")), wb.Column("series", "Series", readonly=True),
                                 wb.Column("issue", "Issue", readonly=True)], add=False, remove=False, label="finding")


def a_findings(ctx: wb.Ctx) -> dict:
    have = {r["id"]: r for r in ctx.records(ctx.step_id)}
    recs = [{**f, **({k: have[f["id"]][k] for k in ("decision", "severity")} if f["id"] in have else {})} for f in ctx.get("findings") or []]
    return {"summary": f"{len(recs)} finding(s) - keep what matters, ignore what does not." if recs else "No issues: every included series can be forecast as it is.",
            "counts": {"findings": len(recs), "high": sum(1 for r in recs if r["severity"] == "high")}, "records": recs,
            "items": [f"{r['series']}: {r['issue']}" for r in recs[:6]],
            "data": {"columns": ["Series", "Issue", "Severity"], "rows": [[r["series"], r["issue"], r["severity"]] for r in recs]}}


def a_estimate(ctx: wb.Ctx) -> dict:
    graded = ctx.get("graded") or []
    kept = [f for f in ctx.records("findings") if f.get("decision") != "ignore" and f.get("severity") == "high"]
    hot = {f["series"] for f in kept}
    waves = [("Wave 1 - ready to forecast", [g for g in graded if g["label"] not in hot]), ("Wave 2 - needs data work first", [g for g in graded if g["label"] in hot])]
    b = registry.brand()
    rate, cur = float(b.get("hourly_rate") or 0), b.get("currency") or ""
    per = sum(MINUTES.values()) / 60
    items, total = [], 0.0
    for name, gs in waves:
        if not gs:
            continue
        h = len(gs) * per + (len(gs) * 0.5 if name.startswith("Wave 2") else 0)
        total += h
        items.append({"title": name, "detail": ", ".join(f"{g['label']} ({g.get('grade')})" for g in gs), "effort": f"{h:.1f} h" + (f" - {cur}{rate * h:,.0f}" if rate else "")})
    note = "Assumptions: " + "; ".join(f"{v} min to {k}" for k, v in MINUTES.items()) + "; half an hour of data work per series in wave 2." + ("" if rate else " Set an hourly rate under Admin > Branding to see the cost.")
    ctx.output("assessment.md", f"# Forecasting assessment: {ctx.title}\n\n" + "\n".join(f"## {i['title']}\n\n{i['detail']}\n\nEffort: {i['effort']}\n" for i in items) + f"\n{note}\n", label="Assessment (Markdown)")
    return {"summary": f"{len(items)} wave(s), about {total:.1f} h of a person's time to confirm, choose and approve the forecasts.", "counts": {"waves": len(items), "hours": round(total, 1)},
            "data": {"items": items, "total": f"{total:.1f} h", "note": note}}


# ------------------------------------------------------------------ Change

def _fc_or_fail(ctx: wb.Ctx) -> dict:
    fc = forecast(ctx.scope.get("forecast") or "", db.user(ctx.owner or "") or {})
    if not fc:
        raise wb.StepFailed("The forecast this work item works on is not one its owner can see any more.")
    return fc


def _load_fc(ctx: wb.Ctx, fc: dict) -> None:
    ctx.put("forecast", fc["id"])
    ctx.put("datasets", fc["datasets"])
    ctx.put("series", fc["spec"])
    ctx.put("methods", dict(fc["methods"] or {}))
    ctx.put("version", fc["version"])


def c_request(ctx: wb.Ctx) -> dict:
    fc = _fc_or_fail(ctx)
    _load_fc(ctx, fc)
    return {"summary": f"Change to \"{fc['name']}\" (version {fc['version']}, {len(fc['spec'])} series).", "counts": {"series": len(fc["spec"]), "version": fc["version"]},
            "data": {"text": ctx.brief or "(no request text)"}}


def c_diagnose(ctx: wb.Ctx) -> dict:
    rows = ctx.get("series") or []
    bts = _backtests(ctx, rows, _dmap(ctx))
    ctx.put("before", bts)
    methods = ctx.get("methods") or {}
    checks = []
    for sid, bt in bts.items():
        cur = methods.get(sid) or "seasonal_naive"
        x, best = bt["models"][cur], bt["models"][bt["recommended"]]
        checks.append({"name": sid, "label": f"{bt['series']} - today's model ({ps.METHODS[cur]})", "status": "pass" if cur == bt["recommended"] else "warn",
                       "measured": f"WAPE {pdat.fmt(x['wape'], 1)} %", "expected": f"best now: {ps.METHODS[bt['recommended']]} at {pdat.fmt(best['wape'], 1)} %", "detail": _plain(bt, cur)})
    return {"summary": f"Today's models back-tested on today's data: {sum(1 for c in checks if c['status'] == 'pass')} of {len(checks)} are still the best simple choice.",
            "counts": {"series": len(checks)}, "data": {"checks": checks}}


def _validate_settings(recs: list[dict], ctx: wb.Ctx) -> list[str]:
    out = []
    for i, r in enumerate(recs, 1):
        if r.get("method") not in ps.METHODS:
            out.append(f"Row {i}: pick one of the three methods")
        try:
            if not 1 <= int(r.get("horizon") or 0) <= 36:
                out.append(f"Row {i}: the horizon is 1 to 36 periods")
        except (TypeError, ValueError):
            out.append(f"Row {i}: the horizon is a number")
    return out


SETTINGS_EDIT = wb.Edit(columns=[wb.Column("series", "Series", readonly=True), wb.Column("method", "Model", "select", options=tuple(ps.METHODS.items())),
                                 wb.Column("horizon", "Periods ahead", "number"), wb.Column("holdout", "Periods to hold back (blank: one cycle)", "number")],
                        add=False, remove=False, validate=_validate_settings, label="series")


def c_fix(ctx: wb.Ctx) -> dict:
    methods = ctx.get("methods") or {}
    recs = ctx.records(ctx.step_id) or [{"id": r["id"], "series": r.get("label"), "method": methods.get(r["id"]) or "seasonal_naive", "horizon": r.get("horizon") or 6, "holdout": None}
                                        for r in ctx.get("series") or []]
    return {"summary": "Change the model, the horizon or how many periods are held back for the test. Relay proves the change on the data next.",
            "records": recs, "data": {"columns": ["Series", "Model", "Periods ahead"], "rows": [[r["series"], ps.METHODS.get(r["method"], r["method"]), r["horizon"]] for r in recs]}}


def c_prove(ctx: wb.Ctx) -> dict:
    edits = {r["id"]: r for r in ctx.records("fix")}
    rows = [dict(r, horizon=int(edits.get(r["id"], {}).get("horizon") or r.get("horizon") or 6)) for r in ctx.get("series") or []]
    hold = {sid: int(e["holdout"]) for sid, e in edits.items() if e.get("holdout") not in (None, "")}
    bts = _backtests(ctx, rows, _dmap(ctx), hold)
    before = ctx.get("before") or {}
    old = ctx.get("methods") or {}
    new = {sid: e["method"] for sid, e in edits.items()}
    checks = _gates(ctx, bts, new, float(ctx.scope.get("target") or 20))
    for sid, bt in bts.items():
        o = (before.get(sid) or {}).get("models", {}).get(old.get(sid) or "seasonal_naive", {})
        n = bt["models"][new.get(sid) or "seasonal_naive"]
        worse = n["wape"] is not None and o.get("wape") is not None and n["wape"] > o["wape"]
        checks.append({"name": f"{sid}:vs", "label": f"{bt['series']} - the change against today's model", "status": "warn" if worse else "pass",
                       "measured": f"WAPE {pdat.fmt(n['wape'], 1)} %", "expected": f"today {pdat.fmt(o.get('wape'), 1)} %", "detail": "less accurate than today's model" if worse else "as accurate or better"})
    ctx.put("series", rows)
    ctx.put("backtests", bts)
    ctx.put("new_methods", new)
    _charts(ctx, bts, "change")
    return {"summary": f"The changed settings back-tested on {len(bts)} series: {sum(1 for c in checks if c['status'] == 'fail')} fail, {sum(1 for c in checks if c['status'] == 'warn')} warning(s).",
            "counts": {"series": len(bts)}, "data": {"checks": checks}}


def c_approve(ctx: wb.Ctx) -> dict:
    new, old = ctx.get("new_methods") or {}, ctx.get("methods") or {}
    changed = [sid for sid in new if new[sid] != old.get(sid)]
    return {"summary": f"Release version {(ctx.get('version') or 0) + 1}: {len(changed)} series change model.",
            "data": {"items": [{"title": sid, "detail": f"{ps.METHODS.get(old.get(sid), old.get(sid))} {ps.METHODS[new[sid]]}"} for sid in changed] or [{"title": "Models", "detail": "unchanged; the settings change"}]}}


def c_learn(ctx: wb.Ctx) -> dict:
    fc, rows_out = share_out(ctx, ctx.get("series") or [], _dmap(ctx), ctx.get("new_methods") or {}, ctx.get("backtests"), ctx.get("forecast"), (ctx.brief or "")[:300])
    return {"summary": f"Version {fc['version']} of \"{fc['name']}\" is live; the Run item refreshes it from its next round.", "counts": {"version": fc["version"]},
            "data": {"href": f"#/m/{MODULE}/i/{fc['run_item']}" if fc.get("run_item") else f"#/m/{MODULE}/run", "label": "Open the Run item" if fc.get("run_item") else "Run & support",
                     "text": " - ".join(f"{a}: {b}" for a, b in rows_out)}}


# ------------------------------------------------------------------ Migrate (a legacy forecast moved, side by side first)

def _legacy(ctx: wb.Ctx) -> tuple[dict | None, list[dict]]:
    """The upload that holds a forecast (a column named forecast / predicted / fcst) and the others (the actuals)."""
    dsets = pdat.datasets(ctx)
    legacy = None
    for d in dsets:
        if d["ref"]["source"] != "file":
            continue
        names = [c["name"].lower() for c in pdat.columns(ctx, d["ref"])]
        if any(n in ("forecast", "predicted", "fcst", "prediction") for n in names):
            legacy = d
            break
    return legacy, [d for d in dsets if d is not legacy]


def m_discover(ctx: wb.Ctx) -> dict:
    legacy, actuals = _legacy(ctx)
    if not legacy:
        raise wb.StepFailed("Upload the legacy forecast (a file with a period or date column and a forecast column) next to the actuals.")
    if not actuals:
        raise wb.StepFailed("Add the actuals too: an upload, a warehouse table or a dashboard.")
    cols, rows = pdat.rows_of(ctx, legacy["ref"])
    names = {c["name"].lower(): c["name"] for c in cols}
    fcol = next(names[n] for n in ("forecast", "predicted", "fcst", "prediction") if n in names)
    pcol = next((names[n] for n in ("period", "month", "date", "week", "day") if n in names), None)
    scol = next((names[n] for n in ("series", "segment", "region", "product") if n in names), None)
    if not pcol:
        raise wb.StepFailed("The legacy forecast needs a period (or date) column.")
    series: dict = {}
    for r in rows:
        series.setdefault(str(r.get(scol) or "all") if scol else "all", []).append((str(r.get(pcol))[:10], float(r.get(fcol) or 0)))
    ctx.put("legacy", {"dataset": legacy, "series": {k: sorted(v) for k, v in series.items()}, "series_col": scol})
    ctx.put("datasets", actuals)
    sug = _suggest(ctx, actuals)
    ctx.put("suggested", sug)
    return {"summary": f"The legacy forecast {legacy['name']} holds {len(series)} series ({sum(len(v) for v in series.values())} periods); the actuals come from {', '.join(d['name'] for d in actuals)}.",
            "counts": {"legacy series": len(series), "actuals": len(actuals)},
            "data": {"columns": ["Legacy series", "Periods", "From", "To"], "rows": [[k, len(v), v[0][0], v[-1][0]] for k, v in series.items()]}}


def m_decide(ctx: wb.Ctx) -> dict:
    lg = ctx.get("legacy") or {}
    dmap = _dmap(ctx)
    sug = ctx.get("suggested") or []
    have = {r["id"]: r for r in ctx.records(ctx.step_id)}
    recs = []
    for name, pts in (lg.get("series") or {}).items():
        match = next((s for s in sug if (s.get("where_val") or "").lower() == name.lower()), None) or (sug[0] if sug else None)
        if not match:
            continue
        p, y = load_series(ctx, match, dmap)
        act = dict(zip(p, y))
        both = [(per, v) for per, v in pts if per in act]
        acc = ps.accuracy([act[per] for per, _ in both], [v for _, v in both]) if both else {"wape": None, "mape": None}
        rid = f"m-{pdat.slug(name, 30)}"
        recs.append({"id": rid, "legacy": name, "series": {**match, "id": rid, "label": label(match, dmap)}, "periods": len(both), "legacy_wape": acc["wape"],
                     "decision": (have.get(rid) or {}).get("decision") or ("keep" if both else "retire"),
                     "reason": (have.get(rid) or {}).get("reason") or ("compare with Relay's methods" if both else "no actuals to compare it with")})
    ctx.put("decided", recs)
    return {"summary": f"{len(recs)} legacy series: keep (move to Relay) or retire each - with the legacy forecast's accuracy where actuals exist.",
            "counts": {"series": len(recs), "keep": sum(1 for r in recs if r["decision"] == "keep")}, "records": recs,
            "data": {"columns": ["Legacy series", "Periods with actuals", "Legacy WAPE %", "Decision"], "rows": [[r["legacy"], r["periods"], r["legacy_wape"], r["decision"]] for r in recs]}}


DECIDE_EDIT = wb.Edit(columns=[wb.Column("decision", "Decision", "select", options=(("keep", "Keep - move to Relay"), ("retire", "Retire"))), wb.Column("reason", "Why", "longtext"),
                               wb.Column("legacy", "Legacy series", readonly=True), wb.Column("legacy_wape", "Legacy WAPE %", "number", readonly=True)], add=False, remove=False, label="series")


def m_convert(ctx: wb.Ctx) -> dict:
    lg = ctx.get("legacy") or {}
    dmap = _dmap(ctx)
    kept = [r for r in ctx.records("decide") if r.get("decision") == "keep"]
    if not kept:
        raise wb.StepFailed("Nothing is kept: every legacy series was retired.")
    side, rows = {}, []
    for r in kept:
        s = r["series"]
        p, y = load_series(ctx, s, dmap)
        pts = dict((lg.get("series") or {}).get(r["legacy"]) or [])
        test = [i for i, per in enumerate(p) if per in pts]
        if not test:
            continue
        k = len(p) - test[0]
        bt = ps.backtest(p, y, ps.SEASON.get(s.get("grain") or "month", 1) if ps.season_for(s.get("grain") or "month", len(p) - k) > 1 else 1, int(s.get("horizon") or 6), k)
        leg = ps.accuracy(bt["actual"], [pts.get(per, 0.0) for per in bt["periods"]])
        bt["series"], bt["n"], bt["last"] = s["label"], len(p), p[-1]
        bt["legacy"] = {"forecast": [pts.get(per) for per in bt["periods"]], **leg}
        side[s["id"]] = bt
        for mm, x in bt["models"].items():
            rows.append([s["label"], ps.METHODS[mm], x["wape"], leg["wape"]])
    ctx.put("series", [r["series"] for r in kept])
    ctx.put("backtests", side)
    return {"summary": f"Relay's three methods fitted on the actuals before the legacy forecast's periods, for {len(side)} series.", "counts": {"series": len(side)},
            "data": {"columns": ["Series", "Relay method", "Relay WAPE %", "Legacy WAPE %"], "rows": rows}}


def m_prove(ctx: wb.Ctx) -> dict:
    bts = ctx.get("backtests") or {}
    checks = []
    chosen = {}
    for sid, bt in bts.items():
        meth = bt["recommended"]
        chosen[sid] = meth
        x, leg = bt["models"][meth], bt["legacy"]
        ev = ctx.evidence(f"Side by side: {bt['series']}", {"rows": [{"period": p, "actual": a, "legacy": lf, "relay": f} for p, a, lf, f in zip(bt["periods"], bt["actual"], leg["forecast"], x["forecast"])],
                                                           "relay": x, "legacy": {k: leg[k] for k in ("mape", "wape", "bias")}}, kind="proof", ok=True)
        better = x["wape"] is not None and leg["wape"] is not None and x["wape"] <= leg["wape"]
        checks.append({"name": sid, "label": f"{bt['series']} - Relay ({ps.METHODS[meth]}) against the legacy forecast", "status": "pass" if better else "warn",
                       "measured": f"Relay WAPE {pdat.fmt(x['wape'], 1)} %", "expected": f"legacy {pdat.fmt(leg['wape'], 1)} %", "evidence": ev,
                       "detail": "as accurate or better on the same periods" if better else "the legacy forecast was more accurate on these periods: keep it, or move and watch"})
    ctx.put("chosen", chosen)
    _charts(ctx, {sid: {**bt, "models": {**bt["models"], "legacy": {"forecast": bt["legacy"]["forecast"]}}} for sid, bt in bts.items()}, "side-by-side")
    return {"summary": f"Old and new side by side on {len(bts)} series: Relay is as accurate or better on {sum(1 for c in checks if c['status'] == 'pass')}.", "counts": {"series": len(bts)},
            "data": {"checks": checks}}


def m_handover(ctx: wb.Ctx) -> dict:
    bts = ctx.get("backtests") or {}
    return {"summary": f"Sign off the move of {len(bts)} series to Relay: the evidence pack holds the side-by-side back-tests.",
            "data": {"items": [{"title": bt["series"], "detail": f"{ps.METHODS[(ctx.get('chosen') or {}).get(sid, 'seasonal_naive')]} - Relay WAPE {pdat.fmt(bt['models'][(ctx.get('chosen') or {}).get(sid, 'seasonal_naive')]['wape'], 1)} % vs legacy {pdat.fmt(bt['legacy']['wape'], 1)} %"} for sid, bt in bts.items()]}}


def m_run(ctx: wb.Ctx) -> dict:
    out = d_watch(ctx)
    out["summary"] = out["summary"].replace("is live", "moved to Relay and is live")
    return out


# ------------------------------------------------------------------ Run & support (the scheduled refresh)

def r_watch(ctx: wb.Ctx) -> dict:
    fc = _fc_or_fail(ctx)
    _load_fc(ctx, fc)
    dmap = _dmap(ctx)
    target = float(ctx.scope.get("target") or 20)
    methods = ctx.get("methods") or {}
    published = {}
    for x in fc["output"]:
        published.setdefault(x["series_id"], {})[x["period"]] = x["forecast"]
    checks, issues, bts = [], [], {}
    for r in fc["spec"]:
        p, y = load_series(ctx, r, dmap)
        act = dict(zip(p, y))
        due = [(per, f) for per, f in sorted((published.get(r["id"]) or {}).items()) if per in act]
        last = (fc["metrics"].get(r["id"]) or {}).get("last")
        new = [per for per in p if last and per > last]
        meth = methods.get(r["id"]) or "seasonal_naive"
        if due:
            acc = ps.accuracy([act[per] for per, _ in due], [f for _, f in due])
            ok = acc["wape"] is not None and acc["wape"] <= target
            ev = ctx.evidence(f"Accuracy since publishing: {r.get('label')}", {"rows": [{"period": per, "actual": act[per], "forecast": f} for per, f in due], **acc}, kind="proof", ok=ok)
            checks.append({"name": f"{r['id']}:recent", "label": f"{r.get('label')} - the forecast against the actuals that arrived", "status": "pass" if ok else "fail",
                           "measured": f"WAPE {pdat.fmt(acc['wape'], 1)} % over {len(due)} period(s)", "expected": f"at most {pdat.fmt(target, 1)} %", "evidence": ev,
                           "detail": "within the target" if ok else "the forecast is drifting from what happened"})
            if not ok:
                bt = ps.backtest(p, y, ps.SEASON.get(r.get("grain") or "month", 1) if ps.season_for(r.get("grain") or "month", len(p)) > 1 else 1, int(r.get("horizon") or 6))
                bt["series"], bt["n"], bt["last"] = r.get("label"), len(p), p[-1]
                bts[r["id"]] = bt
                issues.append({"id": f"i-{r['id']}", "series_id": r["id"], "series": r.get("label"), "what": f"off by {pdat.fmt(acc['wape'], 1)} % over {len(due)} period(s)",
                               "cause": "the level or the pattern changed after the model was fitted", "method": meth, "best": bt["recommended"], "evidence": ev})
        age = (time.time() - float(fc.get("published") or time.time())) / 86400
        due_new = age > PERIOD_DAYS.get(r.get("grain") or "month", 31)          # a period should have closed since publishing
        checks.append({"name": f"{r['id']}:fresh", "label": f"{r.get('label')} - new data since the last refresh", "status": "pass" if new or not due_new else "warn",
                       "measured": f"{len(new)} new period(s)", "expected": "at least one" if due_new else "none yet (published recently)",
                       "detail": f"latest period {p[-1] if p else '-'}" if new else ("no new periods: the source has not refreshed" if due_new else f"published {age:.1f} day(s) ago: no new {r.get('grain') or 'month'} has closed yet")})
        if not new and due_new:
            issues.append({"id": f"s-{r['id']}", "series_id": r["id"], "series": r.get("label"), "what": "no new periods since the last refresh", "cause": "the source did not refresh (a load, a schedule or a sign-in)",
                           "method": meth, "best": meth})
    ctx.put("issues", issues)
    ctx.put("backtests", bts)
    out_rows, metrics = forecast_rows(ctx, fc["spec"], dmap, methods)
    ctx.output(f"forecast-{time.strftime('%Y%m%d-%H%M', time.gmtime())}.csv", _csv(out_rows), label="The refreshed forecast (CSV)")
    if fc.get("dashboard") and fc.get("file"):
        w = to_dashboard(ctx, fc["dashboard"], fc["file"], _csv(out_rows))
        ctx.note(f"Scheduled refresh: {w['status']}.")
    db.run("UPDATE predict_forecasts SET output = ?, metrics = ?, updated = ? WHERE id = ?", (json.dumps(out_rows), json.dumps({**fc["metrics"], **metrics}), time.time(), fc["id"]))
    return {"summary": f"Version {fc['version']} refreshed with the same model{'s' if len(fc['spec']) > 1 else ''}: {sum(1 for c in checks if c['status'] == 'pass')} check(s) pass, {len(issues)} issue(s).",
            "counts": {"series": len(fc["spec"]), "issues": len(issues)}, "data": {"checks": checks}}


def r_alert(ctx: wb.Ctx) -> dict:
    iss = ctx.get("issues") or []
    if not iss:
        return {"summary": "Every forecast is within its target and the data refreshed: nothing to alert.", "next": "report", "counts": {"issues": 0}}
    return {"summary": f"{len(iss)} issue(s) on {len({i['series'] for i in iss})} series, each with its likely cause.", "counts": {"issues": len(iss)},
            "items": [f"{i['series']}: {i['what']}" for i in iss[:6]],
            "data": {"columns": ["Series", "What", "Likely cause"], "rows": [[i["series"], i["what"], i["cause"]] for i in iss]}}


def r_fix(ctx: wb.Ctx) -> dict:
    have = {r["id"]: r for r in ctx.records(ctx.step_id)}
    recs = []
    for i in ctx.get("issues") or []:
        default = ("switch" if i["best"] != i["method"] else "refit") if i["id"].startswith("i-") else "ticket"
        recs.append({**i, "action": (have.get(i["id"]) or {}).get("action") or default, "note": (have.get(i["id"]) or {}).get("note") or "",
                     "proposal": f"switch to {ps.METHODS[i['best']]}" if i["best"] != i["method"] else f"refit {ps.METHODS[i['method']]} on the new data"})
    return {"summary": f"{len(recs)} issue(s): Relay proposes a fix for each - nothing changes until you confirm.", "records": recs,
            "counts": {"switch": sum(1 for r in recs if r["action"] == "switch"), "tickets": sum(1 for r in recs if r["action"] == "ticket")},
            "data": {"columns": ["Series", "What", "Proposal", "Action"], "rows": [[r["series"], r["what"], r["proposal"], r["action"]] for r in recs]}}


FIX_EDIT = wb.Edit(columns=[wb.Column("action", "Action", "select", options=(("switch", "Switch to the better model"), ("refit", "Keep the model (it refits on new data)"),
                                                                          ("ticket", "Raise a ticket"), ("heal", "Self-healing"), ("expected", "Expected - no action"))),
                            wb.Column("note", "Note", "longtext"), wb.Column("series", "Series", readonly=True), wb.Column("what", "What", readonly=True),
                            wb.Column("proposal", "Relay proposes", readonly=True)], add=False, remove=False, label="issue")


def r_approve(ctx: wb.Ctx) -> dict:
    fc = forecast(ctx.get("forecast") or "")
    recs = ctx.records("fix")
    methods = dict(ctx.get("methods") or {})
    rows, switched = [], 0
    for r in recs:
        if r["action"] == "switch":
            methods[r["series_id"]] = r["best"]
            switched += 1
            rows.append([r["series"], "Switch", f"{ps.METHODS[r['method']]} {ps.METHODS[r['best']]}"])
        elif r["action"] == "ticket":
            h = ctx.ticket(f"Forecast {r['series']}: {r['what']}", f"{r['what']}\n\nLikely cause: {r['cause']}\n{('Note: ' + r['note']) if r.get('note') else ''}\nWork item: {wb.route_of(ctx.st)}", priority="P3", about=r["series"])
            rows.append([r["series"], "Ticket", h.get("status")])
        elif r["action"] == "heal":
            h = ctx.heal(f"Forecast source stale: {r['series']}", f"{r['what']} - {r['cause']}", signature=f"predict:{r['series_id']}", subject={"series": r["series"]})
            rows.append([r["series"], "Self-healing", h.get("status")])
        else:
            rows.append([r["series"], "Recorded", {"refit": "the model refits on the new data", "expected": "expected - no action"}.get(r["action"], r["action"])])
    if switched and fc:
        nfc, _ = share_out(ctx, fc["spec"], {d["key"]: d for d in fc["datasets"]}, methods, None, fc["id"], f"model switched in Run ({switched} series)")
        rows.append(["Forecast", "New version", f"version {nfc['version']}"])
    return {"summary": f"{switched} model switch(es), {sum(1 for r in recs if r['action'] == 'ticket')} ticket(s), {sum(1 for r in recs if r['action'] == 'heal')} to Self-healing - as you approved.",
            "data": {"columns": ["Series", "Done", "Detail"], "rows": rows}, "counts": {"switched": switched}}


def r_report(ctx: wb.Ctx) -> dict:
    rounds = (ctx.st.get("rounds") or [])[-11:]
    hist = []
    for rd in rounds:
        w = next((s for s in rd["steps"] if s["id"] == "watch"), {})
        hist.append([time.strftime("%d %b %H:%M", time.gmtime(rd["ended"])), (w.get("counts") or {}).get("issues")])
    hist.append([time.strftime("%d %b %H:%M", time.gmtime()), len(ctx.get("issues") or [])])
    text = f"# Forecast run report: {ctx.title}\n\n{time.strftime('%d %B %Y %H:%M UTC', time.gmtime())}\n\n" + "".join(f"- {i['series']}: {i['what']}\n" for i in ctx.get("issues") or []) \
        + "\n## Recent runs\n\n" + "".join(f"- {h[0]}: {h[1]} issue(s)\n" for h in hist)
    ctx.output(f"report-{time.strftime('%Y%m%d-%H%M', time.gmtime())}.md", text, label="Run report (Markdown)")
    return {"summary": f"{len(ctx.get('issues') or [])} issue(s) this run; {len(hist)} run(s) in the history.", "counts": {"issues": len(ctx.get("issues") or [])},
            "data": {"columns": ["Run", "Issues"], "rows": hist}}


# ------------------------------------------------------------------ the module page

def _cards(u: dict) -> list[dict]:
    rows = []
    for f in forecasts(u):
        w = [m.get("wape") for m in (f["metrics"] or {}).values() if isinstance(m, dict) and m.get("wape") is not None]
        rows.append([f["name"], f"v{f['version']}", len(f["spec"]), f"{min(w):.1f}-{max(w):.1f} %" if w else "-", (db.user(f.get("published_by") or "") or {}).get("name") or "-",
                     time.strftime("%d %b %Y", time.gmtime(f["published"])) if f.get("published") else "-", f"#/m/{MODULE}/i/{f['run_item']}" if f.get("run_item") else ""])
    return [{"title": "Live forecasts", "columns": ["Forecast", "Version", "Series", "Back-tested WAPE", "Published by", "When", "Run item"], "rows": rows,
             "empty": "No forecast is live yet: a Develop item's Watch step publishes one after its Share approval."}]


GUIDE = """# Predictive analytics & forecasting - the work item

This folder is one work item of Relay's forecasting module. Forecasts are made by the app's own explainable methods
(seasonal naive, exponential smoothing, a linear trend with seasonality), back-tested on periods the model never saw
and chosen by a person. No AI step writes a number here.

- `data/`: the person's uploads; `evidence/`: the series, the back-tests and the proof of each step.
- `outputs/`: the back-test tables and charts, the forecast table (with its 80 % range), the run reports.

Never invent a number, a period or a column."""

DEV_FIELDS = [wb.Field("dashboard", "A dashboard's data to use", "select", options=pdat.dashboards_for, help="Optional: the forecast reads that dashboard's tables with your access, as Ask Relay does."),
              wb.Field("objects", "Warehouse tables or views", "longtext", help="One per line, e.g. SALES.ORDERS (with a warehouse connection)."),
              wb.Field("date", "Date column", help="Blank: the first date column."), wb.Field("value", "What to forecast", help="Blank: Relay suggests a column (amounts, quantities, counts)."),
              wb.Field("by", "One forecast per value of", help="Optional: a column with up to 12 values, e.g. region."),
              wb.Field("grain", "By", "select", options=pdat.GRAINS, default="month"), wb.Field("horizon", "Periods ahead", "number", default=6),
              wb.Field("target", "Accuracy target (WAPE %)", "number", default=20, help="A forecast off by more than this on the back-test gets a warning."),
              wb.Field("publish_to", "Publish the forecast to a dashboard", "select", options=pdat.dashboards_for, help="Its data folder gets the forecast table after the Share approval."),
              wb.Field("cadence", "Refresh it", "cadence", default={"every": "week", "at": "06:00", "weekday": 0, "tz": "UTC"})]

wb.register(wb.Pack(
    module=MODULE, guide=GUIDE,
    lineage="each dataset a forecast reads, the forecast as a job (system \"Relay forecasts\"), and the forecast table it writes to a dashboard",
    platforms=PLATFORMS,
    schemas={"series": SERIES_COLUMNS, "choice": CHOICE_EDIT.columns, "finding": FINDINGS_EDIT.columns, "issue": FIX_EDIT.columns},
    cards=_cards,
    work={
        "assess": wb.Work(title="Find what can be forecast, and how well", needs_source=False, platforms=("files", "warehouse", "dashboards", "registry"), steps={
            "Connect": wb.Step(kind="platform", run=a_connect, agent="Connector", text="Each source is tested - uploads, warehouses, a dashboard's data and model registries - read-only, with the owner's own access"),
            "Inventory": wb.Step(kind="platform", run=a_inventory, agent="Scanner", text="Every date-and-number pair that could be a series, and the models already in your registries - you tick what matters",
                                 edit=wb.Edit(columns=[wb.Column("include", "Use", "bool"), wb.Column("dataset_name", "Dataset", readonly=True), wb.Column("date", "Date", readonly=True),
                                                       wb.Column("value", "Value", readonly=True), wb.Column("grain", "By", "select", options=pdat.GRAINS)], add=False, remove=False, label="series")),
            "Health": wb.Step(kind="proof", run=a_health, view="gates", agent="Profiler", text="History, gaps, seasonality and a quick back-test of each series - how forecastable it is, measured, not guessed"),
            "Findings": wb.Step(kind="person", run=a_findings, edit=FINDINGS_EDIT, text="What stands in the way of a good forecast - you keep or ignore each finding"),
            "Estimate": wb.Step(kind="deterministic", run=a_estimate, view="plan", agent="Estimator", text="Waves by readiness and the time a person needs to confirm, choose and approve")},
            fields=[DEV_FIELDS[0], DEV_FIELDS[1], wb.Field("grain", "By", "select", options=pdat.GRAINS, default="month"), wb.Field("horizon", "Periods ahead", "number", default=6)]),
        "develop": wb.Work(title="Forecast from your data, back-tested before anyone relies on it", needs_source=False, platforms=("files", "warehouse", "dashboards", "registry"), steps={
            "Question": wb.Step(kind="deterministic", run=d_question, agent="Analyst"),
            "Data": wb.Step(kind="deterministic", run=d_data, agent="Data steward", edit=SERIES_EDIT),
            "Model": wb.Step(kind="deterministic", run=d_model, agent="Forecaster", edit=CHOICE_EDIT, confirm="the model for each series - Relay preselects the simplest one that is accurate enough"),
            "Prove": wb.Step(kind="proof", run=d_prove, view="gates", agent="Prover", back_to="model"),
            "Share": wb.Step(kind="person", run=d_share, view="plan", approver=True),
            "Watch": wb.Step(kind="deterministic", run=d_watch, view="link", agent="Publisher")},
            fields=DEV_FIELDS),
        "change": wb.Work(title="Change a live forecast, proven on the data before it is released", needs_source=False, sources=False, platforms=("files", "warehouse", "dashboards"), steps={
            "Request": wb.Step(kind="deterministic", run=c_request, view="text", agent="Forecast librarian", text="The change in plain words, and the live forecast it changes"),
            "Diagnose": wb.Step(kind="proof", run=c_diagnose, view="gates", agent="Prover", text="Today's models back-tested on today's data, so you see what still holds before anything changes"),
            "Fix": wb.Step(kind="person", run=c_fix, edit=SETTINGS_EDIT, confirm="the model and settings per series", text="You change the model, the horizon or the periods held back"),
            "Prove": wb.Step(kind="proof", run=c_prove, view="gates", agent="Prover", back_to="fix", text="The changed settings back-tested and compared with today's"),
            "Approve": wb.Step(kind="person", run=c_approve, view="plan", approver=True, text="The named approver releases the new version"),
            "Learn": wb.Step(kind="deterministic", run=c_learn, view="link", agent="Publisher", text="The new version is published and kept; the Run item refreshes it from its next round")},
            fields=[wb.Field("forecast", "Forecast to change", "select", options=forecast_options, required=True), wb.Field("target", "Accuracy target (WAPE %)", "number", default=20)]),
        "migrate": wb.Work(title="Move a legacy forecast to Relay, side by side first", needs_source=False, platforms=("files", "warehouse", "dashboards", "registry"), steps={
            "Discover": wb.Step(kind="platform", run=m_discover, agent="Scanner", text="The legacy forecast (an upload) and the actuals it should have predicted - read-only"),
            "Decide": wb.Step(kind="deterministic", run=m_decide, agent="Analyst", edit=DECIDE_EDIT, text="Keep or retire each legacy series, with how accurate it was where actuals exist"),
            "Convert": wb.Step(kind="deterministic", run=m_convert, agent="Forecaster", text="Relay's methods fitted on the actuals before the legacy forecast's periods - rules only, no AI"),
            "Prove": wb.Step(kind="proof", run=m_prove, view="gates", agent="Prover", text="Old and new side by side on the same periods, with the evidence"),
            "Hand over": wb.Step(kind="person", run=m_handover, view="plan", approver=True, text="The named approver signs off the move with the evidence pack"),
            "Run": wb.Step(kind="deterministic", run=m_run, view="link", agent="Publisher", text="The forecasts go live in Relay and a Run item refreshes and watches them")},
            fields=[DEV_FIELDS[0], DEV_FIELDS[1], DEV_FIELDS[2], DEV_FIELDS[3], DEV_FIELDS[4], DEV_FIELDS[5], DEV_FIELDS[8], DEV_FIELDS[9]]),
        "run": wb.Work(title="Refresh a live forecast on a schedule and watch its accuracy", needs_source=False, sources=False, platforms=("files", "warehouse", "dashboards", "registry"), steps={
            "Watch": wb.Step(kind="proof", run=r_watch, view="gates", agent="Watcher", text="The forecast refreshed with the approved model, and checked against the actuals that arrived since it was published"),
            "Alert": wb.Step(kind="deterministic", run=r_alert, agent="Triage", text="Drift and stale data grouped by series, each with its likely cause"),
            "Fix": wb.Step(kind="deterministic", run=r_fix, agent="Triage", edit=FIX_EDIT, text="Relay proposes a fix per issue - switch the model, keep it, a ticket or Self-healing - and you confirm or change it"),
            "Approve": wb.Step(kind="platform", run=r_approve, agent="Dispatcher", text="What you approved goes out: a new forecast version, a ticket through the service desk's own approval, or a Self-healing case"),
            "Report": wb.Step(kind="deterministic", run=r_report, agent="Reporter", confirm_if=lambda ctx, out: bool(ctx.get("issues")),
                              text="A run report against the last runs; you confirm it when there were issues")},
            fields=[wb.Field("forecast", "Forecast to watch", "select", options=forecast_options, required=True), wb.Field("target", "Accuracy target (WAPE %)", "number", default=20),
                    wb.Field("schedule", "Refresh it", "cadence", default={"every": "week", "at": "06:00", "weekday": 0, "tz": "UTC"})]),
    }))
