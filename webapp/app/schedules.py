"""Scheduled reports and metric alerts (phase 7).

A report renders an insight page, a dashboard prototype or a fresh Ask D answer in the agent's headless browser
(PDF or PNG) and emails it from the owner's own email account; without an account it is kept for the owner to
download from the notification. An alert checks one number (a dashboard measure, or one SELECT of the owner's) on
a schedule and tells the owner - in the app, and by email when an account is chosen - when it crosses the
threshold; it fires once per crossing and re-arms when the value comes back.

Everything runs as the owner, with the owner's access at the time of the run: a dashboard or page they can no
longer open, an email account or warehouse sign-in that expired, pauses the schedule and tells them. Times are
the owner's wall-clock time in the schedule's time zone (daylight saving included)."""
import asyncio
import json
import math
import re
import secrets
import time
import traceback
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from . import askd, auth, connectors, db, mailer, notify, pages, publishing, semantic, store, usage

router = APIRouter()

FREQS = ("hourly", "daily", "weekdays", "weekly", "monthly")
OPS = {">": lambda v, t: v > t, ">=": lambda v, t: v >= t, "<": lambda v, t: v < t, "<=": lambda v, t: v <= t}
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
OUT = store.state_dir("reports")              # P17: each tenant's rendered reports apart
PAUSE_AFTER_FAILURES = 3
TICK_S = 30


class ScheduleError(Exception):
    pass


def num(v: float) -> str:
    """2,400 - 14,880,268.22 - 0.0731"""
    if v is None or not math.isfinite(v):
        return "no value"
    if float(v).is_integer():
        return f"{v:,.0f}"
    return f"{v:,.2f}" if abs(v) >= 1 else f"{v:.4g}"


class Paused(ScheduleError):
    """Needs the owner: the schedule pauses with this reason."""


# ---------------------------------------------------------------- time

def zone(tz: str) -> ZoneInfo:
    try:
        return ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError) as e:
        raise ScheduleError(f"Unknown time zone {tz!r}.") from e


def clean_cadence(c: dict) -> dict:
    freq = c.get("freq")
    if freq not in FREQS:
        raise ScheduleError("How often: hourly, daily, weekdays, weekly or monthly.")
    m = re.fullmatch(r"([01]?\d|2[0-3]):([0-5]\d)", str(c.get("time") or "08:00"))
    if not m:
        raise ScheduleError("Time must look like 08:00.")
    out = {"freq": freq, "time": f"{int(m.group(1)):02d}:{m.group(2)}"}
    if freq == "weekly":
        if int(c.get("weekday", 0)) not in range(7):
            raise ScheduleError("Pick the day of the week.")
        out["weekday"] = int(c.get("weekday", 0))
    if freq == "monthly":
        if int(c.get("day", 1)) not in range(1, 29):
            raise ScheduleError("Day of the month must be 1-28.")
        out["day"] = int(c.get("day", 1))
    return out


def next_run(c: dict, tz: str, after: float) -> float:
    """The first moment after `after` that matches the cadence, in the schedule's own time zone."""
    z = zone(tz)
    hh, mm = (int(x) for x in c["time"].split(":"))
    now = datetime.fromtimestamp(after, z)
    if c["freq"] == "hourly":
        cand = now.replace(minute=mm, second=0, microsecond=0).timestamp()
        while cand <= after:
            cand += 3600
        return cand
    for offset in range(0, 64):
        d: date = now.date() + timedelta(days=offset)
        if (c["freq"] == "weekdays" and d.weekday() > 4) or (c["freq"] == "weekly" and d.weekday() != c["weekday"]) \
                or (c["freq"] == "monthly" and d.day != c["day"]):
            continue
        cand = datetime(d.year, d.month, d.day, hh, mm, tzinfo=z).timestamp()
        if cand > after:
            return cand
    raise ScheduleError("No next run found.")


def describe(c: dict, tz: str) -> str:
    t = c["time"]
    return {"hourly": f"Every hour at :{t[3:]}", "daily": f"Every day at {t}", "weekdays": f"Weekdays at {t}",
            "weekly": f"Every {DAYS[c.get('weekday', 0)]} at {t}", "monthly": f"Day {c.get('day', 1)} of each month at {t}"}[c["freq"]] + f" ({tz})"


# ---------------------------------------------------------------- what a schedule points at

def _user(uid: str) -> dict:
    u = db.user(uid)
    if not u:
        raise Paused("Its owner's account is deactivated.")
    return u


def _can_view_target(u: dict, target: dict) -> bool:
    t = target["type"]
    if t == "page":
        try:
            pages.get(target["id"], u)
            return True
        except pages.PageError:
            return False
    if t in ("dashboard", "metric", "sql"):
        return auth.can_project(u, "view", db.project(target.get("project")))
    if t == "askd":
        scope = target.get("scope") or {}
        return scope.get("kind") != "dashboard" or auth.can_project(u, "view", db.project(scope.get("project")))
    return False


def clean_target(kind: str, t: dict, u: dict) -> dict:
    typ = t.get("type")
    if kind == "report" and typ not in ("page", "dashboard", "askd"):
        raise ScheduleError("A report sends an insight page, a dashboard or an Ask D question.")
    if kind == "alert" and typ not in ("metric", "sql"):
        raise ScheduleError("An alert checks a dashboard measure or a SQL query.")
    out: dict = {"type": typ}
    if typ == "page":
        out["id"] = str(t.get("id") or "")
    elif typ == "dashboard":
        out["project"] = str(t.get("project") or "")
        if t.get("version"):
            out["version"] = int(t["version"])
    elif typ == "askd":
        q = str(t.get("question") or "").strip()
        if not q:
            raise ScheduleError("Write the question Ask D should answer.")
        scope = t.get("scope") or {"kind": "team"}
        if scope.get("kind") not in ("dashboard", "team", "org"):
            raise ScheduleError("Ask D scope: a dashboard, your team or the organisation.")
        out.update(question=q[:1000], scope={k: scope[k] for k in ("kind", "project") if k in scope})
    else:
        out["project"] = str(t.get("project") or "")
        if typ == "metric":
            out["measure"] = str(t.get("measure") or "")
        else:
            out["sql"] = str(t.get("sql") or "").strip()[:4000]
        if t.get("op") not in OPS:
            raise ScheduleError("Condition: >, >=, < or <=.")
        try:
            out.update(op=t["op"], threshold=float(t.get("threshold")))
        except (TypeError, ValueError) as e:
            raise ScheduleError("The threshold must be a number.") from e
    if kind == "report":
        out["format"] = t.get("format") if t.get("format") in ("pdf", "png") else "pdf"
    if not _can_view_target(u, out):
        raise ScheduleError("You cannot open that dashboard or page.")
    if typ in ("metric", "sql"):
        metric_value(out, u)                     # a definition that cannot be evaluated is refused when saved
    return out


def clean_recipients(kind: str, target: dict, ids: list[str], u: dict) -> list[str]:
    """Only people in the organisation who can open what is sent; an Ask D answer uses the owner's own access, so it
    goes to the owner only."""
    ids = list(dict.fromkeys([str(i) for i in ids or []] or [u["id"]]))
    out = []
    for rid in ids:
        r = db.user(rid)
        if not r:
            raise ScheduleError("Unknown recipient.")
        if rid != u["id"] and (kind == "alert" or target["type"] == "askd"):
            raise ScheduleError("Alerts and Ask D reports go to you only (they use your own access to the data).")
        if not _can_view_target(r, target):
            raise ScheduleError(f"{r['name']} cannot open what this report sends; share it with them first.")
        out.append(rid)
    return out


# ---------------------------------------------------------------- alerts: one number

def _measure_sql(pid: str, name: str) -> str:
    defn = semantic._project_defn(pid) or {}                  # noqa: SLF001
    measures = {m["name"]: m.get("expression", "") for m in defn.get("measures") or []}
    if name not in measures:
        raise ScheduleError(f"The dashboard has no measure [{name}].")
    expr = semantic.dax_to_sql(measures[name], measures)
    if not expr:
        raise ScheduleError(f"[{name}] is too complex to check automatically; use a SQL alert instead.")
    tables = list(dict.fromkeys(re.findall(r'"([^"]+)"\."', expr)))
    if len(tables) > 1:
        raise ScheduleError(f"[{name}] uses several tables ({', '.join(tables)}); use a SQL alert instead.")
    return f'SELECT {expr} AS value' + (f' FROM "{tables[0]}"' if tables else "")


def measures(pid: str) -> list[dict]:
    defn = semantic._project_defn(pid) or {}                  # noqa: SLF001
    out = []
    for m in defn.get("measures") or []:
        try:
            _measure_sql(pid, m["name"])
            out.append({"name": m["name"], "checkable": True})
        except ScheduleError as e:
            out.append({"name": m["name"], "checkable": False, "why": str(e)})
    return out


def metric_value(target: dict, u: dict) -> float | None:
    pid = target["project"]
    sql = _measure_sql(pid, target["measure"]) if target["type"] == "metric" else target["sql"]
    con, tables = askd._extract_engine([pid], False)           # noqa: SLF001 - the dashboard's own views
    try:
        safe, _, _ = askd.guard_duckdb(sql, set(tables), 10)
        cols, rows = askd._run_duckdb(con, safe, 60)           # noqa: SLF001
    except askd.AskError as e:
        raise ScheduleError(str(e)) from e
    except Exception as e:  # noqa: BLE001 - DuckDB's message tells the person what to fix
        raise ScheduleError(f"The query failed: {str(e).splitlines()[0][:200]}") from e
    finally:
        con.close()
    if not rows or not cols:
        return None
    v = rows[0][cols[0]]
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError) as e:
        raise ScheduleError("The query must return one number.") from e


# ---------------------------------------------------------------- running one schedule

def _row(sid: str) -> dict:
    s = db.one("SELECT * FROM schedules WHERE id = ?", (sid,))
    if not s:
        raise ScheduleError("Unknown schedule.")
    for k in ("target", "cadence", "recipients", "state"):
        s[k] = json.loads(s[k])
    return s


def _state(sid: str, **kw) -> None:
    s = _row(sid)
    db.run("UPDATE schedules SET state = ? WHERE id = ?", (json.dumps({**s["state"], **kw}), sid))


def pause(s: dict, reason: str) -> None:
    db.run("UPDATE schedules SET status = 'paused', paused_reason = ?, updated = ? WHERE id = ?", (reason[:400], time.time(), s["id"]))
    notify.add(s["owner_id"], "schedule", f"Paused: {s['name']}", reason, "#/schedules")
    db.audit("schedule.paused", s["id"], {"reason": reason[:300]}, "system")


def _check_connections(u: dict, target: dict) -> None:
    """Ask D over live warehouses uses the owner's stored sign-ins; one that expired pauses the schedule."""
    if target["type"] != "askd" or target["scope"].get("kind") == "dashboard":
        return
    for c in db.q("SELECT c.name, c.status, c.error FROM connections c WHERE c.owner_id = ? AND EXISTS "
                  "(SELECT 1 FROM connection_tables t WHERE t.connection_id = c.id)", (u["id"],)):
        if c["status"] == "reconsent":
            raise Paused(f"Connection: your sign-in to {c['name']} expired. Sign in again on Connections, then resume.")


def _email_html(s: dict, lines: list[str]) -> str:
    import html as H
    link = f'<p><a href="{H.escape(publishing.PUBLIC_URL)}/#/schedules">Open Relay</a></p>' if publishing.PUBLIC_URL else ""
    return (f'<div style="font:14px/1.5 Segoe UI,Arial,sans-serif;color:#0F2A23"><h2 style="margin:0 0 8px">{H.escape(s["name"])}</h2>'
            + "".join(f"<p>{H.escape(x)}</p>" for x in lines) + link
            + '<p style="color:#8E958E;font-size:12px">Sent by Relay on your schedule. Change or pause it under Schedules.</p></div>')


def _deliver(s: dict, subject: str, lines: list[str], attachments: list[tuple[str, str, bytes]]) -> str:
    if not s["email_account_id"]:
        return "in the app"
    emails = [r["email"] for r in (db.user(rid) for rid in s["recipients"]) if r]
    try:
        mailer.send(s["email_account_id"], s["owner_id"], emails, subject, _email_html(s, lines), attachments)
    except mailer.EmailExpired as e:
        raise Paused(f"Email: {e}") from e
    except mailer.EmailError as e:
        if "Unknown email account" in str(e):
            raise Paused("Email: its email account was removed.") from e
        raise ScheduleError(str(e)) from e
    return f"emailed to {len(emails)}"


async def _render_target(t: dict, u: dict) -> tuple[bytes, str]:
    if t["type"] == "page":
        p = pages.get(t["id"], u)
        html, title = pages.html(p), p["title"]
    elif t["type"] == "dashboard":
        try:
            html = publishing.prototype_html(t["project"], t.get("version"))
        except publishing.PublishError as e:
            raise ScheduleError(str(e)) from e
        title = store.load(t["project"]).get("name") or t["project"]
    else:
        try:
            body = await askd.ask(u, t["question"], t["scope"])
        except askd.AskError as e:
            raise ScheduleError(str(e)) from e
        html, title = askd.snapshot_html(body, t["question"]), t["question"][:80]
    try:
        return await publishing.render(u["id"], html, t["format"]), title
    except publishing.PublishError as e:
        raise ScheduleError(str(e)) from e
    except httpx.HTTPError as e:
        raise ScheduleError("The AI agent (it draws the PDF) could not be reached; the next run tries again.") from e


async def _report(s: dict, u: dict) -> str:
    t = s["target"]
    local = datetime.fromtimestamp(time.time(), zone(s["tz"]))
    data, title = await _render_target(t, u)
    OUT.mkdir(parents=True, exist_ok=True)
    name = re.sub(r"[^\w\- ]+", "", f"{s['name']} {local:%Y-%m-%d}").strip() + "." + t["format"]
    (OUT / f"{s['id']}.{t['format']}").write_bytes(data)
    _state(s["id"], file=name, size=len(data), rendered=time.time())
    how = _deliver(s, f"{s['name']} - {local:%a %d %b %Y}", [f"{title}: attached as {name}."],
                   [(name, "application/pdf" if t["format"] == "pdf" else "image/png", data)])
    if how == "in the app":
        notify.add(s["owner_id"], "report", f"Report ready: {s['name']}", f"{name}, {len(data) // 1024} KB", f"/api/schedules/{s['id']}/latest")
    return f"{name} ({len(data) // 1024} KB) {how}"


async def _alert(s: dict, u: dict) -> str:
    t = s["target"]
    value = await asyncio.to_thread(metric_value, t, u)
    hit = value is not None and OPS[t["op"]](value, t["threshold"])
    was = bool(s["state"].get("firing"))
    _state(s["id"], value=value, firing=hit, checked=time.time())
    what = f"[{t['measure']}]" if t["type"] == "metric" else "The value"
    vtxt = num(value)
    if hit and not was:
        name = store.load(t["project"]).get("name") or t["project"]
        line = f"{what} on {name} is {vtxt} ({t['op']} {num(t['threshold'])})."
        notify.add(s["owner_id"], "alert", f"Alert: {s['name']}", line, f"#/p/{t['project']}")
        db.audit("alert.fired", s["id"], {"value": value, "op": t["op"], "threshold": t["threshold"]}, s["owner_id"])
        how = _deliver(s, f"Alert: {s['name']}", [line], [])
        return f"fired: {vtxt} ({how})"
    return f"{vtxt} - " + ("still past the threshold" if hit else "within the threshold")


async def run(sid: str, manual: bool = False) -> dict:
    s = _row(sid)
    started = time.time()
    try:
        u = _user(s["owner_id"])
        if not _can_view_target(u, s["target"]):
            raise Paused("You can no longer open the dashboard or page it uses.")
        _check_connections(u, s["target"])
        if s["email_account_id"]:
            a = db.one("SELECT status, error FROM email_accounts WHERE id = ?", (s["email_account_id"],))
            if not a:
                raise Paused("Email: its email account was removed.")
            if a["status"] == "expired":
                raise Paused(f"Email: {a['error'] or 'the account needs to be connected again.'}")
        out = await (_report(s, u) if s["kind"] == "report" else _alert(s, u))
        db.run("UPDATE schedules SET last_run = ?, last_status = 'ok', last_error = NULL WHERE id = ?", (started, sid))
        _state(sid, failures=0)
        db.audit("schedule.run", sid, {"manual": manual, "result": out[:300]}, s["owner_id"])
        return {"ok": True, "result": out}
    except Paused as e:
        db.run("UPDATE schedules SET last_run = ?, last_status = 'paused', last_error = ? WHERE id = ?", (started, str(e)[:400], sid))
        pause(s, str(e))
        return {"ok": False, "paused": True, "error": str(e)}
    except usage.QuotaError as e:
        db.run("UPDATE schedules SET last_run = ?, last_status = 'skipped', last_error = ? WHERE id = ?", (started, str(e)[:400], sid))
        notify.add(s["owner_id"], "schedule", f"Skipped: {s['name']}", str(e), "#/schedules")
        return {"ok": False, "error": str(e)}
    except Exception as e:  # noqa: BLE001 - recorded on the schedule; repeated failures pause it
        if not isinstance(e, ScheduleError):
            traceback.print_exc()
        msg = str(e)[:400] or type(e).__name__
        n = int(s["state"].get("failures") or 0) + 1
        db.run("UPDATE schedules SET last_run = ?, last_status = 'error', last_error = ? WHERE id = ?", (started, msg, sid))
        _state(sid, failures=n)
        if n >= PAUSE_AFTER_FAILURES:
            pause(s, f"It failed {n} times in a row. Last error: {msg}")
        elif n == 1:
            notify.add(s["owner_id"], "schedule", f"Failed: {s['name']}", msg, "#/schedules")
        return {"ok": False, "error": msg}


async def run_due(now: float | None = None) -> list[str]:
    now = now or time.time()
    ran = []
    for s in db.q("SELECT id, cadence, tz FROM schedules WHERE status = 'active' AND next_run <= ? ORDER BY next_run", (now,)):
        nxt = next_run(json.loads(s["cadence"]), s["tz"], max(now, time.time()))
        db.run("UPDATE schedules SET next_run = ? WHERE id = ?", (nxt, s["id"]))   # moved on first: never runs twice
        await run(s["id"])
        ran.append(s["id"])
    return ran


async def scheduler() -> None:
    while True:
        await asyncio.sleep(TICK_S)
        try:
            for t in db.each_tenant():                  # P17: every tenant's schedules and notifications
                if db._module_check is None or db._module_check(t, "schedule"):
                    await run_due()
                notify.trim()
        except Exception:  # noqa: BLE001
            traceback.print_exc()


# ---------------------------------------------------------------- saving

def public(s: dict) -> dict:
    out = {k: s[k] for k in ("id", "kind", "name", "target", "cadence", "tz", "email_account_id", "recipients", "status",
                             "paused_reason", "next_run", "last_run", "last_status", "last_error", "created", "updated")}
    out["when"] = describe(s["cadence"], s["tz"])
    out["state"] = {k: v for k, v in s["state"].items() if k in ("value", "firing", "checked", "file", "size", "rendered", "failures")}
    return out


def mine(uid: str) -> list[dict]:
    return [public(_row(r["id"])) for r in db.q("SELECT id FROM schedules WHERE owner_id = ? ORDER BY created", (uid,))]


def validate(u: dict, body: dict) -> dict:
    """A schedule body checked and cleaned (nothing is saved)."""
    kind = body.get("kind")
    if kind not in ("report", "alert"):
        raise ScheduleError("A schedule is a report or an alert.")
    name = str(body.get("name") or "").strip()[:120]
    if not name:
        raise ScheduleError("Give the schedule a name.")
    tz = str(body.get("tz") or u.get("tz") or "UTC")
    zone(tz)
    cadence = clean_cadence(body.get("cadence") or {})
    target = clean_target(kind, body.get("target") or {}, u)
    recipients = clean_recipients(kind, target, body.get("recipients") or [], u)
    aid = body.get("email_account_id") or None
    if aid:
        mailer.account(aid, u["id"])
    elif kind == "report" and len(recipients) > 1:
        raise ScheduleError("Choose an email account to send this report to other people.")
    return {"kind": kind, "name": name, "target": target, "cadence": cadence, "tz": tz, "email_account_id": aid, "recipients": recipients}


def save(u: dict, body: dict, sid: str | None = None) -> dict:
    if sid:
        old = _row(sid)
        if old["owner_id"] != u["id"]:
            raise ScheduleError("Unknown schedule.")
    b = validate(u, body)
    kind, name, target, cadence, tz, aid, recipients = (b[k] for k in ("kind", "name", "target", "cadence", "tz", "email_account_id", "recipients"))
    now = time.time()
    vals = (kind, name, json.dumps(target), json.dumps(cadence), tz, aid, json.dumps(recipients), next_run(cadence, tz, now), now)
    if sid:
        db.run("UPDATE schedules SET kind = ?, name = ?, target = ?, cadence = ?, tz = ?, email_account_id = ?, recipients = ?, "
               "next_run = ?, updated = ?, status = 'active', paused_reason = NULL WHERE id = ?", vals + (sid,))
    else:
        sid = "sc-" + secrets.token_hex(5)
        db.run("INSERT INTO schedules (kind, name, target, cadence, tz, email_account_id, recipients, next_run, updated, id, owner_id, created) "
               "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", vals + (sid, u["id"], now))
    db.audit("schedule.save", sid, {"kind": kind, "name": name, "target": target["type"], "when": describe(cadence, tz)}, u["id"])
    return public(_row(sid))


def set_status(sid: str, u: dict, active: bool) -> dict:
    s = _row(sid)
    if s["owner_id"] != u["id"]:
        raise ScheduleError("Unknown schedule.")
    if active:
        db.run("UPDATE schedules SET status = 'active', paused_reason = NULL, next_run = ?, updated = ? WHERE id = ?",
               (next_run(s["cadence"], s["tz"], time.time()), time.time(), sid))
        _state(sid, failures=0)
    else:
        db.run("UPDATE schedules SET status = 'paused', paused_reason = 'Paused by you.', updated = ? WHERE id = ?", (time.time(), sid))
    db.audit("schedule.resume" if active else "schedule.pause", sid, None, u["id"])
    return public(_row(sid))


def remove(sid: str, u: dict) -> None:
    s = _row(sid)
    if s["owner_id"] != u["id"] and not auth.is_admin(u):
        raise ScheduleError("Unknown schedule.")
    db.run("DELETE FROM schedules WHERE id = ?", (sid,))
    for f in OUT.glob(f"{sid}.*"):
        f.unlink(missing_ok=True)
    db.audit("schedule.remove", sid, {"name": s["name"]}, u["id"])


# ---------------------------------------------------------------- endpoints

def _u() -> dict:
    return auth.current.get()


def _err(e: Exception) -> HTTPException:
    return HTTPException(404 if "Unknown schedule" in str(e) else 400, str(e))


@router.get("/api/schedules")
def list_schedules():
    u = _u()
    all_ids = [p["id"] for p in store.all_projects()]
    access = auth.access_map(u, all_ids)
    names = {p["id"]: p.get("name") for p in store.all_projects()}
    return {"schedules": mine(u["id"]), "tz": u.get("tz") or "UTC",
            "dashboards": [{"id": pid, "name": names.get(pid) or pid} for pid in access],
            "pages": [{"id": p["id"], "title": p["title"]} for p in pages.mine(u)],
            "accounts": mailer.accounts(u["id"]),
            "people": [{"id": r["id"], "name": r["name"], "email": r["email"]} for r in db.q("SELECT id, name, email FROM users WHERE active = 1 ORDER BY lower(name)")]}


class ScheduleBody(BaseModel):
    kind: str
    name: str
    target: dict
    cadence: dict
    tz: str | None = None
    email_account_id: str | None = None
    recipients: list[str] = []


@router.post("/api/schedules")
def add_schedule(body: ScheduleBody):
    try:
        return save(_u(), body.model_dump())
    except (ScheduleError, mailer.EmailError) as e:
        raise _err(e)


@router.put("/api/schedules/{sid}")
def change_schedule(sid: str, body: ScheduleBody):
    try:
        return save(_u(), body.model_dump(), sid)
    except (ScheduleError, mailer.EmailError) as e:
        raise _err(e)


@router.delete("/api/schedules/{sid}")
def delete_schedule(sid: str):
    try:
        remove(sid, _u())
    except ScheduleError as e:
        raise _err(e)
    return {"ok": True}


@router.post("/api/schedules/{sid}/{action}")
async def schedule_action(sid: str, action: str):
    try:
        s = _row(sid)
        if s["owner_id"] != _u()["id"]:
            raise ScheduleError("Unknown schedule.")
        if action == "run":
            return {**(await run(sid, manual=True)), "schedule": public(_row(sid))}
        if action in ("pause", "resume"):
            return set_status(sid, _u(), action == "resume")
    except ScheduleError as e:
        raise _err(e)
    raise HTTPException(404, "Unknown action")


@router.get("/api/schedules/{sid}/latest")
def latest(sid: str):
    try:
        s = _row(sid)
    except ScheduleError as e:
        raise _err(e)
    u = _u()
    if s["owner_id"] != u["id"] and u["id"] not in s["recipients"]:
        raise HTTPException(404, "Unknown schedule.")
    fmt = s["target"].get("format", "pdf")
    f: Path = OUT / f"{sid}.{fmt}"
    if not f.exists():
        raise HTTPException(404, "Nothing rendered yet.")
    name = s["state"].get("file") or f"{sid}.{fmt}"
    return Response(f.read_bytes(), media_type="application/pdf" if fmt == "pdf" else "image/png",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/api/schedules-measures/{pid}")
def alert_measures(pid: str):
    p = db.project(pid)
    if p is None or not auth.can_project(_u(), "view", p):         # an unknown id is not found, for Admins too
        raise HTTPException(404, "Unknown dashboard")
    return {"measures": measures(pid)}


class Preview(BaseModel):
    target: dict


@router.post("/api/schedules-preview")
def preview_alert(body: Preview):
    """The value an alert would see right now (nothing is saved)."""
    u = _u()
    try:
        t = clean_target("alert", {**body.target, "op": body.target.get("op") or ">", "threshold": body.target.get("threshold") or 0}, u)
        return {"value": metric_value(t, u)}
    except ScheduleError as e:
        raise HTTPException(400, str(e))


class TzBody(BaseModel):
    tz: str


@router.put("/api/me/tz")
def set_tz(body: TzBody):
    try:
        zone(body.tz)
    except ScheduleError as e:
        raise HTTPException(400, str(e))
    db.run("UPDATE users SET tz = ? WHERE id = ?", (body.tz, _u()["id"]))
    return {"tz": body.tz}


@router.get("/api/admin/schedules")
def admin_schedules():
    names = {u["id"]: u["name"] for u in db.q("SELECT id, name FROM users")}
    return {"schedules": [{**public(_row(r["id"])), "owner": names.get(r["owner_id"], r["owner_id"])}
                          for r in db.q("SELECT id, owner_id FROM schedules ORDER BY created")],
            "accounts": db.q("SELECT e.id, e.kind, e.address, e.status, u.name AS owner FROM email_accounts e JOIN users u ON u.id = e.owner_id")}


# ---------------------------------------------------------------- describe it in words: the AI drafts, Relay checks, the person confirms

DRAFT_SYSTEM = """You set up scheduled reports and metric alerts in a business intelligence platform from what a person asks
in plain words. Use only the dashboards, measures, tables, pages, people and email accounts you are given; never invent
ids. When the request is too vague to set up, ask one short question instead. Reply with exactly one JSON object."""

DRAFT_SHAPE = """Reply as JSON:
{"kind": "report" | "alert",
 "name": "short name",
 "target": one of
   report: {"type": "dashboard", "project": "<dashboard id>", "format": "pdf"|"png"}
           {"type": "page", "id": "<page id>", "format": "pdf"|"png"}
           {"type": "askd", "question": "<the question to answer fresh each time>", "scope": {"kind": "team"|"org"} or {"kind": "dashboard", "project": "<id>"}, "format": "pdf"|"png"}
   alert:  {"type": "metric", "project": "<dashboard id>", "measure": "<a checkable measure>", "op": "<"|"<="|">"|">=", "threshold": <number>}
           {"type": "sql", "project": "<dashboard id>", "sql": "<one read-only DuckDB SELECT over that dashboard's tables returning one number>", "op": ..., "threshold": <number>}
 "cadence": {"freq": "hourly"|"daily"|"weekdays"|"weekly"|"monthly", "time": "HH:MM", "weekday": 0-6 (Monday = 0, weekly only), "day": 1-28 (monthly only)},
 "recipients": ["<email of each person to send it to; empty = only me>"],
 "email": true when it should be emailed (it always is when it goes to other people), false to keep it in the app,
 "explanation": "one or two sentences: what you set up and any assumption you made (e.g. the time you picked)"}
or, when you cannot tell what they want: {"question": "..."}
Prefer a dashboard measure over SQL for an alert; use SQL when the condition needs a filter (a region, a store, a period)
or the measure is not checkable. Hourly is for alerts only. Default time 08:00 for reports, 07:00 for alerts."""


def _draft_context(u: dict) -> str:
    tz = u.get("tz") or "UTC"
    now = datetime.now(zone(tz))
    names = {p["id"]: p.get("name") for p in store.all_projects()}
    pids = [p for p in auth.access_map(u, list(names)) if not p.startswith("askd-")][:12]
    lines = [f"Now: {now:%A %d %B %Y %H:%M} in {tz} (the person's time zone).", "", "Dashboards the person can open:"]
    for pid in pids:
        lines.append(f"- id {pid}: {names.get(pid) or pid}")
        try:
            ms = measures(pid)
        except Exception:  # noqa: BLE001 - a dashboard without a model yet
            ms = []
        if ms:
            lines.append("  measures: " + ", ".join(m["name"] + ("" if m["checkable"] else " (not checkable: use SQL)") for m in ms[:40]))
        try:
            con, tables = askd._extract_engine([pid], False)          # noqa: SLF001 - the same views an alert runs on
            con.close()
            lines += [f'  table "{t}": ' + ", ".join(cols[:30]) for t, cols in list(tables.items())[:10]]
        except Exception:  # noqa: BLE001
            pass
    ps = pages.mine(u)
    if ps:
        lines += ["", "Insight pages:"] + [f"- id {p['id']}: {p['title']}" for p in ps[:30]]
    people = db.q("SELECT name, email FROM users WHERE active = 1 ORDER BY lower(name)")[:80]
    lines += ["", f"The person: {u.get('name')} <{u.get('email')}>", "People in the organisation: " + ", ".join(f"{p['name']} <{p['email']}>" for p in people)]
    acc = [a for a in mailer.accounts(u["id"]) if a.get("status") == "connected"]
    lines.append("Email accounts: " + (", ".join(a["address"] for a in acc) if acc else "none connected (it can only be kept in the app)"))
    return "\n".join(lines)


def _body_from(out: dict, u: dict) -> dict:
    """The model's reply as a schedule body; every part is checked the same way as a saved schedule."""
    kind = out.get("kind")
    people = {r["email"].lower(): r["id"] for r in db.q("SELECT id, email FROM users WHERE active = 1")}
    rec = []
    for e in out.get("recipients") or []:
        rid = people.get(str(e).strip().lower())
        if not rid:
            raise ScheduleError(f"{e} is not a person in the organisation.")
        rec.append(rid)
    rec = list(dict.fromkeys(rec or [u["id"]]))
    acc = next((a["id"] for a in mailer.accounts(u["id"]) if a.get("status") == "connected"), None)
    wants_email = bool(out.get("email")) or rec != [u["id"]]
    if wants_email and not acc:
        raise Paused("To email it, connect a Gmail or Microsoft account in Settings first (or keep it in Relay).")
    body = {"kind": kind, "name": str(out.get("name") or "").strip(), "target": out.get("target") or {}, "cadence": out.get("cadence") or {},
            "tz": u.get("tz") or "UTC", "email_account_id": acc if wants_email else None, "recipients": rec}
    return validate(u, body)


def _label(t: dict) -> str:
    names = {p["id"]: p.get("name") for p in store.all_projects()}
    d = names.get(t.get("project"), t.get("project"))
    return {"dashboard": lambda: f"Dashboard - {d}", "page": lambda: f"Page - {t.get('id')}",
            "askd": lambda: f"Ask D - \"{t.get('question')}\"",
            "metric": lambda: f"[{t.get('measure')}] {t.get('op')} {num(t.get('threshold'))} - {d}",
            "sql": lambda: f"SQL {t.get('op')} {num(t.get('threshold'))} - {d}"}[t["type"]]()


async def draft(u: dict, request: str, previous: dict | None = None) -> dict:
    """Turn what the person asked into a checked schedule (nothing is saved). One retry tells the model what was wrong."""
    request = str(request or "").strip()[:2000]
    if not request:
        raise ScheduleError("Say what to send or what to watch, and when.")
    prompt = _draft_context(u) + "\n\n" + DRAFT_SHAPE + "\n\n"
    if previous:
        prompt += f"The current draft: {json.dumps(previous)[:4000]}\nChange it as the person now asks: {request}"
    else:
        prompt += f"The person asks: {request}"
    out: dict = {}
    for attempt in range(2):
        try:
            out = await askd.ask_json(u, DRAFT_SYSTEM, prompt, "schedule_draft")
        except askd.AskError as e:
            raise ScheduleError(str(e)) from e
        if out.get("question") and not out.get("kind"):
            return {"question": str(out["question"])[:500]}
        try:
            body = await asyncio.to_thread(_body_from, out, u)
            break
        except Paused as e:
            return {"problem": str(e), "explanation": out.get("explanation")}
        except (ScheduleError, mailer.EmailError) as e:
            if attempt:
                return {"problem": f"Relay could not set that up: {e}", "explanation": out.get("explanation")}
            prompt += f"\n\nYour reply {json.dumps(out)[:3000]} was refused: {e}\nFix it (or ask a question)."
    t = body["target"]
    preview: dict = {}
    if body["kind"] == "alert":
        v = await asyncio.to_thread(metric_value, t, u)
        preview = {"value": v, "fires_now": v is not None and OPS[t["op"]](v, t["threshold"])}
    people = {r["id"]: r["name"] for r in db.q("SELECT id, name FROM users")}
    what = _label(t)
    if t["type"] == "page":
        what = "Page - " + next((p["title"] for p in pages.mine(u) if p["id"] == t["id"]), t["id"])
    return {"draft": body, "explanation": str(out.get("explanation") or "")[:600],
            "summary": {"what": what, "when": describe(body["cadence"], body["tz"]),
                        "next_run": next_run(body["cadence"], body["tz"], time.time()),
                        "to": [people.get(r, r) for r in body["recipients"]],
                        "by_email": bool(body["email_account_id"])}, "preview": preview}


async def preview_report(u: dict, target: dict) -> bytes:
    """What a report would send right now, as a picture (nothing is saved or sent)."""
    t = clean_target("report", {**target, "format": "png"}, u)
    data, _ = await _render_target(t, u)
    return data


class DraftBody(BaseModel):
    request: str
    previous: dict | None = None


@router.post("/api/schedules-draft")
async def draft_schedule(body: DraftBody):
    try:
        return await draft(_u(), body.request, body.previous)
    except usage.QuotaError as e:
        raise HTTPException(429, str(e))
    except (ScheduleError, mailer.EmailError) as e:
        raise HTTPException(400, str(e))


@router.post("/api/schedules-draft/preview")
async def draft_preview(body: Preview):
    try:
        data = await preview_report(_u(), body.target)
    except usage.QuotaError as e:
        raise HTTPException(429, str(e))
    except ScheduleError as e:
        raise HTTPException(400, str(e))
    return Response(data, media_type="image/png")
