"""Cost records, the organisation cost report and quotas (phase 7).

Every LLM run (builds, Ask Relay), live warehouse query and extract adds one row to `usage`. Rows from before phase 7
are filled in once from the records the app already kept (each dashboard's runs, the Ask Relay and query audit entries).

Quotas are monthly LLM spend limits (USD, calendar month, UTC) per person or per team: at `soft_pct` of the limit
the person is told once a month; at the limit new builds and Ask Relay questions are refused until the month ends or an
Admin raises the limit. Running work is never cut off half-way."""
import json
import time
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from . import auth, db, notify, store

router = APIRouter()

PRICE_TB = 6.25          # BigQuery on-demand list price, USD per TiB scanned (Admins can change it)


class QuotaError(Exception):
    pass


def price_tb() -> float:
    return float(db.meta("warehouse_price_tb", str(PRICE_TB)))


def team_of(uid: str | None) -> str | None:
    row = db.one("SELECT team_id FROM memberships WHERE user_id = ? ORDER BY team_id", (uid,)) if uid else None
    return row["team_id"] if row else None


def record(kind: str, user_id: str | None, *, team_id: str | None = None, step: str | None = None, model: str | None = None,
           provider: str | None = None, tokens: int = 0, cost_usd: float = 0.0, bytes_: int | None = None,
           obj: str | None = None, source: str | None = None, ts: float | None = None) -> None:
    db.run("INSERT OR IGNORE INTO usage (ts, user_id, team_id, kind, step, model, provider, tokens, cost_usd, bytes, object, source) "
           "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
           (ts or time.time(), user_id, team_id or team_of(user_id), kind, step, model, provider, int(tokens or 0),
            float(cost_usd or 0), bytes_, obj, source))


def record_run(pid: str, run: dict, index: int) -> None:
    """One agent run of a dashboard (as appended to its state)."""
    u = run.get("usage") or {}
    p = db.project(pid) or {}
    record("llm", run.get("owner") or p.get("owner_id"), team_id=p.get("team_id"), step=run.get("stage"), model=run.get("model"),
           provider=run.get("provider"), tokens=sum(v for v in u.values() if isinstance(v, (int, float))),
           cost_usd=run.get("cost_usd") or 0, obj=pid, source=f"run:{pid}:{index}:{run.get('ended')}", ts=run.get("ended"))


def warehouse_cost(bytes_: int | None) -> float:
    return (bytes_ or 0) / 2 ** 40 * price_tb()


def backfill() -> int:
    """Once: rows for everything recorded before phase 7 (idempotent: each source is recorded at most once)."""
    if db.meta("usage_backfilled"):
        return 0
    before = db.one("SELECT COUNT(*) AS n FROM usage")["n"]
    for p in store.all_projects():
        try:
            runs = store.load(p["id"]).get("runs") or []
        except (KeyError, FileNotFoundError, ValueError):
            continue
        for i, r in enumerate(runs):
            record_run(p["id"], r, i)
    for a in db.q("SELECT id, ts, who, detail FROM audit WHERE action = 'askd.question'"):
        d = json.loads(a["detail"] or "{}")
        if not d.get("cached"):
            record("llm", a["who"], step="askd", model=d.get("model"), provider=d.get("provider"), tokens=d.get("tokens") or 0,
                   cost_usd=d.get("cost_usd") or 0, obj=a["id"], source=f"audit:{a['id']}", ts=a["ts"])
    for a in db.q("SELECT id, ts, who, object, detail FROM audit WHERE action = 'query'"):
        d = json.loads(a["detail"] or "{}")
        record("warehouse", a["who"], step=d.get("kind"), bytes_=d.get("bytes_estimate"), cost_usd=warehouse_cost(d.get("bytes_estimate")),
               obj=a["object"], source=f"audit:{a['id']}", ts=a["ts"])
    db.set_meta("usage_backfilled", str(time.time()))
    return db.one("SELECT COUNT(*) AS n FROM usage")["n"] - before


# ---------------------------------------------------------------- months and quotas

def month_bounds(month: str | None = None) -> tuple[str, float, float]:
    now = datetime.now(timezone.utc)
    if month:
        try:
            y, m = (int(x) for x in month.split("-"))
            start = datetime(y, m, 1, tzinfo=timezone.utc)
        except (ValueError, TypeError) as e:
            raise ValueError("Month must look like 2026-10.") from e
    else:
        start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
    end = datetime(start.year + (start.month == 12), start.month % 12 + 1, 1, tzinfo=timezone.utc)
    return start.strftime("%Y-%m"), start.timestamp(), end.timestamp()


def spent(scope: str, target: str, start: float, end: float) -> float:
    if scope == "workspace":                     # P17: the usage table is the workspace's own, so its total is the workspace's spend
        return db.one("SELECT COALESCE(SUM(cost_usd), 0) AS c FROM usage WHERE kind = 'llm' AND ts >= ? AND ts < ?", (start, end))["c"]
    col = "user_id" if scope == "user" else "team_id"
    return db.one(f"SELECT COALESCE(SUM(cost_usd), 0) AS c FROM usage WHERE kind = 'llm' AND {col} = ? AND ts >= ? AND ts < ?",
                  (target, start, end))["c"]


db.register_schema("-- P17 follow-up: one monthly AI limit for the whole workspace (its own table: quotas' CHECK allows user/team only)\n"
                   "CREATE TABLE IF NOT EXISTS workspace_quota (id TEXT PRIMARY KEY, monthly_usd REAL NOT NULL, soft_pct INTEGER NOT NULL DEFAULT 80, updated REAL NOT NULL, updated_by TEXT);")


def _quota_row(scope: str, target: str) -> dict | None:
    if scope == "workspace":
        r = db.one("SELECT * FROM workspace_quota WHERE id = 'workspace'")
        return {**r, "scope": "workspace", "target_id": db.tenant()} if r else None
    return db.one("SELECT * FROM quotas WHERE scope = ? AND target_id = ?", (scope, target))


def quotas() -> list[dict]:
    ws = _quota_row("workspace", db.tenant())
    return db.q("SELECT * FROM quotas ORDER BY scope, target_id") + ([{k: ws[k] for k in ("scope", "target_id", "monthly_usd", "soft_pct", "updated", "updated_by")}] if ws else [])


def set_quota(scope: str, target: str, monthly_usd: float | None, soft_pct: int, who: str | None) -> list[dict]:
    if scope not in ("user", "team", "workspace"):
        raise ValueError("A quota is for a person, a team or the whole workspace.")
    if scope == "workspace":
        if target != db.tenant():
            raise ValueError("A workspace's limit is set inside that workspace.")
    else:
        table = "users" if scope == "user" else "teams"
        if not db.one(f"SELECT 1 FROM {table} WHERE id = ?", (target,)):
            raise ValueError("Unknown person or team.")
    if monthly_usd is None:
        if scope == "workspace":
            db.run("DELETE FROM workspace_quota WHERE id = 'workspace'")
        else:
            db.run("DELETE FROM quotas WHERE scope = ? AND target_id = ?", (scope, target))
    elif scope == "workspace":
        if monthly_usd < 0 or not 1 <= soft_pct <= 100:
            raise ValueError("The limit must be 0 or more, the warning between 1% and 100%.")
        db.run("INSERT OR REPLACE INTO workspace_quota (id, monthly_usd, soft_pct, updated, updated_by) VALUES ('workspace', ?, ?, ?, ?)",
               (float(monthly_usd), int(soft_pct), time.time(), who))
    else:
        if monthly_usd < 0 or not 1 <= soft_pct <= 100:
            raise ValueError("The limit must be 0 or more, the warning between 1% and 100%.")
        db.run("INSERT OR REPLACE INTO quotas (scope, target_id, monthly_usd, soft_pct, updated, updated_by) VALUES (?, ?, ?, ?, ?, ?)",
               (scope, target, float(monthly_usd), int(soft_pct), time.time(), who))
    db.audit("quota.set", f"{scope}:{target}", {"monthly_usd": monthly_usd, "soft_pct": soft_pct}, who)
    return quotas()


def status(uid: str, team_ids: list[str] | None = None) -> list[dict]:
    """Every quota that applies to this person (their own and their teams'), with this month's spend."""
    month, start, end = month_bounds()
    teams = list(dict.fromkeys((team_ids or []) + [r["team_id"] for r in db.q("SELECT team_id FROM memberships WHERE user_id = ?", (uid,))]))
    out = []
    for scope, target in [("user", uid)] + [("team", t) for t in teams] + [("workspace", db.tenant())]:
        q = _quota_row(scope, target)
        if not q:
            continue
        used = spent(scope, target, start, end)
        level = "stop" if used >= q["monthly_usd"] else "warn" if used >= q["monthly_usd"] * q["soft_pct"] / 100 else "ok"
        name = {"name": "this workspace"} if scope == "workspace" else db.one(f"SELECT name FROM {'users' if scope == 'user' else 'teams'} WHERE id = ?", (target,))
        out.append({"scope": scope, "target_id": target, "name": name["name"] if name else target, "month": month,
                    "monthly_usd": q["monthly_usd"], "soft_pct": q["soft_pct"], "spent_usd": round(used, 4), "level": level})
    return out


def check(uid: str | None, team_id: str | None = None) -> list[dict]:
    """Before new LLM work: raises QuotaError at a hard limit; tells the person once a month at the soft limit."""
    if not uid:
        return []
    st = status(uid, [team_id] if team_id else None)
    for s in st:
        who = "Your" if s["scope"] == "user" else "This workspace's" if s["scope"] == "workspace" else f"Team {s['name']}'s"
        if s["level"] == "stop":
            raise QuotaError(f"{who} AI budget for {s['month']} is used up (${s['spent_usd']:.2f} of ${s['monthly_usd']:.2f}). "
                             "New builds and Ask Relay questions wait until next month or until an Admin raises the limit.")
        if s["level"] == "warn":
            key = f"quota_warned:{s['scope']}:{s['target_id']}:{uid}:{s['month']}"
            if not db.meta(key):
                db.set_meta(key, str(time.time()))
                notify.add(uid, "quota", f"{who} AI budget is {s['spent_usd'] / max(s['monthly_usd'], 1e-9):.0%} used",
                           f"${s['spent_usd']:.2f} of ${s['monthly_usd']:.2f} in {s['month']}. At the limit, new builds and "
                           "Ask Relay questions are paused until next month.", "#/settings")
    return st


# ---------------------------------------------------------------- the organisation cost report (Admins)

def _group(rows: list[dict], key: str, names: dict | None = None) -> list[dict]:
    out: dict = {}
    for r in rows:
        k = r.get(key) or "-"
        g = out.setdefault(k, {"key": k, "name": (names or {}).get(k, k), "runs": 0, "tokens": 0, "cost_usd": 0.0})
        g["runs"] += 1
        g["tokens"] += r["tokens"] or 0
        g["cost_usd"] += r["cost_usd"] or 0
    return sorted(out.values(), key=lambda g: -g["cost_usd"])


def report(month: str | None = None) -> dict:
    month, start, end = month_bounds(month)
    users = {u["id"]: u["name"] for u in db.q("SELECT id, name FROM users")}
    teams = {t["id"]: t["name"] for t in db.q("SELECT id, name FROM teams")}
    llm = db.q("SELECT * FROM usage WHERE kind = 'llm' AND ts >= ? AND ts < ?", (start, end))
    wh = db.q("SELECT * FROM usage WHERE kind = 'warehouse' AND ts >= ? AND ts < ?", (start, end))
    ex = db.q("SELECT * FROM usage WHERE kind = 'extract' AND ts >= ? AND ts < ?", (start, end))
    days: dict = {}
    t = start
    while t < min(end, time.time()):               # every day of the month so far, quiet days as zero
        days[datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d")] = 0.0
        t += 86400
    for r in llm:
        d = datetime.fromtimestamp(r["ts"], timezone.utc).strftime("%Y-%m-%d")
        days[d] = days.get(d, 0) + (r["cost_usd"] or 0)
    by_conn: dict = {}
    for r in wh:
        g = by_conn.setdefault(r["object"] or "-", {"connection": r["object"], "kind": r["step"], "queries": 0, "bytes": 0,
                                                    "cost_usd": 0.0, "people": set()})
        g["queries"] += 1
        g["bytes"] += r["bytes"] or 0
        g["cost_usd"] += r["cost_usd"] or 0
        g["people"].add(users.get(r["user_id"], r["user_id"]))
    conns = {c["id"]: c for c in db.q("SELECT id, name, kind FROM connections")}
    sizes = []
    for p in store.all_projects():
        f = store.project_dir(p["id"]) / "data" / ".extracts.json"
        if f.exists():
            try:
                m = json.loads(f.read_text(encoding="utf-8"))
            except ValueError:
                continue
            sizes.append({"project": p["id"], "name": p.get("name"), "tables": len(m), "bytes": sum(e.get("bytes") or 0 for e in m.values()),
                          "rows": sum(e.get("rows") or 0 for e in m.values())})
    prev_month = month_bounds(datetime.fromtimestamp(start - 1, timezone.utc).strftime("%Y-%m"))
    prev = db.one("SELECT COALESCE(SUM(cost_usd), 0) AS c FROM usage WHERE kind = 'llm' AND ts >= ? AND ts < ?", prev_month[1:])["c"]
    return {"month": month, "price_tb": price_tb(),
            "total": {"llm_usd": round(sum(r["cost_usd"] for r in llm), 4), "tokens": sum(r["tokens"] for r in llm), "runs": len(llm),
                      "warehouse_usd": round(sum(r["cost_usd"] for r in wh), 4), "queries": len(wh),
                      "bytes_scanned": sum(r["bytes"] or 0 for r in wh), "extracts": len(ex),
                      "extract_bytes": sum(s["bytes"] for s in sizes), "previous_llm_usd": round(prev, 4)},
            "by_user": _group(llm, "user_id", users), "by_team": _group(llm, "team_id", teams),
            "by_model": _group(llm, "model"), "by_step": _group(llm, "step"),
            "by_day": [{"day": d, "cost_usd": round(c, 4)} for d, c in sorted(days.items())],
            "warehouse": sorted(({**g, "people": sorted(g["people"]), "name": (conns.get(g["connection"]) or {}).get("name", g["connection"])}
                                 for g in by_conn.values()), key=lambda g: -g["bytes"]),
            "extracts": sorted(sizes, key=lambda s: -s["bytes"]),
            "quotas": [{**q, "name": "this workspace" if q["scope"] == "workspace" else (users if q["scope"] == "user" else teams).get(q["target_id"], q["target_id"]),
                        "spent_usd": round(spent(q["scope"], q["target_id"], start, end), 4)} for q in quotas()]}


# ---------------------------------------------------------------- endpoints

@router.get("/api/admin/costs")
def admin_costs(month: str | None = None):
    try:
        return report(month)
    except ValueError as e:
        raise HTTPException(400, str(e))


class QuotaBody(BaseModel):
    scope: str
    target_id: str
    monthly_usd: float | None = None
    soft_pct: int = 80


@router.put("/api/admin/quotas")
def admin_quota(body: QuotaBody):
    if body.scope == "workspace":
        body.target_id = db.tenant()                 # always the workspace the admin is in
    try:
        set_quota(body.scope, body.target_id, body.monthly_usd, body.soft_pct, auth.who())
    except ValueError as e:
        raise HTTPException(400, str(e))
    return report()


class PriceBody(BaseModel):
    price_tb: float


@router.put("/api/admin/costs/price")
def admin_price(body: PriceBody):
    if not 0 <= body.price_tb <= 1000:
        raise HTTPException(400, "Price per TB must be between 0 and 1000.")
    db.set_meta("warehouse_price_tb", str(body.price_tb))
    db.audit("costs.price", None, {"price_tb": body.price_tb}, auth.who())
    return report()


@router.get("/api/me/usage")
def my_usage(request: Request):
    u = auth.current.get()
    month, start, end = month_bounds()
    rows = db.q("SELECT step, model, tokens, cost_usd FROM usage WHERE kind = 'llm' AND user_id = ? AND ts >= ? AND ts < ?",
                (u["id"], start, end))
    return {"month": month, "cost_usd": round(sum(r["cost_usd"] for r in rows), 4), "tokens": sum(r["tokens"] for r in rows),
            "by_step": _group(rows, "step"), "quotas": status(u["id"])}
