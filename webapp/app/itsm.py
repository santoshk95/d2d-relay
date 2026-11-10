"""Service desk (ITSM) - build-plan v2, P12. Jira, Freshservice and (consolidation) ServiceNow queues of the data &
analytics team, read every few minutes with a limited service account (its credential kept by name in the secrets
store); every ticket summarised; duplicates and same-cause tickets grouped; a priority from business impact with the
reason; a route (an agent can handle it, or a person); hand-offs into work (D2D today, AI SDLC / Self-healing /
Semantics / Govern recorded as work items until those modules ship); and summary + priority written back to the
tickets **only after a person accepts the checkpoint** opened for the group (kind `itsm.writeback`).

Consolidation: a source is read-only until an admin (or the person who added it) allows comments or writes ("May
do"); other modules (Data observability, Integration analytics, AI SDLC) raise tickets and add comments only through
`request_write`, each one after its own checkpoint (kind `itsm.write`) showing exactly what will be written.

Tables (db.register_schema): itsm_sources, itsm_tickets (the cache), itsm_groups, itsm_decisions, itsm_work,
itsm_writes. Reading is the registered job kind `itsm_sync` (not an LLM run); polling runs from a lazy scheduler the
router starts (`ensure_scheduler`). Writes to a service desk go through `write_back` and `perform_write`, nowhere else.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import secrets as pysecrets
import time
import traceback

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import auth, checkpoints, db, notify, secrets_store, worker
from . import itsm_triage as triage
from .itsm_adapters import AdapterError, SignInAgain
from .itsm_adapters.freshservice import Freshservice
from .itsm_adapters.jira import Jira
from .itsm_adapters.servicenow import ServiceNow

router = APIRouter()
MODULE = "Service desk"
KIND = "itsm.writeback"
ROUTE = "#/servicedesk"
POLL_S = int(os.environ.get("ITSM_POLL_S", "30"))                # how often the scheduler looks for a source that is due
AUTO_CHECKPOINT = os.environ.get("ITSM_AUTO_CHECKPOINT", "1") == "1"   # open the group's checkpoint when triage forms it

db.register_schema("""
CREATE TABLE IF NOT EXISTS itsm_sources (
  id TEXT PRIMARY KEY, kind TEXT NOT NULL, name TEXT NOT NULL, base_url TEXT NOT NULL, account TEXT, projects TEXT NOT NULL DEFAULT '[]',
  poll_min INTEGER NOT NULL DEFAULT 5, paused INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'new', error TEXT,
  last_read REAL, next_read REAL, reads INTEGER NOT NULL DEFAULT 0, open_tickets INTEGER NOT NULL DEFAULT 0, retries INTEGER NOT NULL DEFAULT 0,
  created REAL NOT NULL, created_by TEXT, secret_name TEXT);
CREATE TABLE IF NOT EXISTS itsm_tickets (
  id TEXT PRIMARY KEY, source_id TEXT NOT NULL, key TEXT NOT NULL, vendor_id TEXT, title TEXT NOT NULL, description TEXT, status TEXT, open INTEGER NOT NULL DEFAULT 1,
  priority TEXT, reporter TEXT, reporter_email TEXT, team TEXT, created REAL, updated REAL, due REAL, labels TEXT NOT NULL DEFAULT '[]', url TEXT,
  fetched REAL, category TEXT, summary TEXT, group_id TEXT);
CREATE INDEX IF NOT EXISTS itsm_tickets_source ON itsm_tickets (source_id, open);
CREATE INDEX IF NOT EXISTS itsm_tickets_group ON itsm_tickets (group_id);
CREATE TABLE IF NOT EXISTS itsm_groups (
  id TEXT PRIMARY KEY, title TEXT NOT NULL, about TEXT, category TEXT, summary TEXT, priority TEXT, reason TEXT, route TEXT, route_reason TEXT,
  target TEXT, target_label TEXT, team TEXT, tickets INTEGER NOT NULL DEFAULT 0, people INTEGER NOT NULL DEFAULT 0, sla_due REAL, near_sla INTEGER NOT NULL DEFAULT 0,
  members TEXT NOT NULL DEFAULT '[]', fingerprint TEXT, status TEXT NOT NULL DEFAULT 'open', note TEXT, checkpoint_id TEXT,
  written REAL, written_by TEXT, written_cp TEXT, person_id TEXT, work_id TEXT, created REAL NOT NULL, updated REAL NOT NULL, closed REAL);
CREATE INDEX IF NOT EXISTS itsm_groups_status ON itsm_groups (status, priority);
CREATE TABLE IF NOT EXISTS itsm_decisions (
  id INTEGER PRIMARY KEY AUTOINCREMENT, group_id TEXT NOT NULL, action TEXT NOT NULL, who TEXT, ts REAL NOT NULL, detail TEXT);
CREATE TABLE IF NOT EXISTS itsm_work (
  id TEXT PRIMARY KEY, group_id TEXT NOT NULL, target TEXT NOT NULL, target_label TEXT, link TEXT, status TEXT NOT NULL, project TEXT, note TEXT,
  who TEXT, created REAL NOT NULL);
""")
# consolidation: what a source may do (read-only by default, like every connection), how it raises tickets, and
# every write another module asked for (a new ticket, a comment) with the per-change approval that allowed it
db.register_schema("""
CREATE TABLE IF NOT EXISTS itsm_writes (
  id TEXT PRIMARY KEY, source_id TEXT NOT NULL, op TEXT NOT NULL, target TEXT, payload TEXT NOT NULL, fingerprint TEXT NOT NULL, module TEXT NOT NULL,
  origin TEXT, link TEXT, status TEXT NOT NULL DEFAULT 'waiting', checkpoint_id TEXT, result TEXT, error TEXT, requested_by TEXT, decided_by TEXT,
  created REAL NOT NULL, updated REAL NOT NULL, written REAL);
CREATE INDEX IF NOT EXISTS itsm_writes_origin ON itsm_writes (origin, status);
""", added_columns={"itsm_sources": {"scope": "TEXT NOT NULL DEFAULT 'read'", "options": "TEXT NOT NULL DEFAULT '{}'", "scope_by": "TEXT", "scope_at": "REAL"}})

KINDS = {
    "jira": {"label": "Jira (Service Management / Software)", "short": "Jira", "connectable": True, "account_label": "Service account e-mail",
             "secret_label": "API token", "projects_label": "Project keys to read (e.g. DATA, BI)", "url_hint": "https://your-site.atlassian.net",
             "api": "Jira Cloud REST API v3: search (JQL), issue, comments, transitions, field edits"},
    "freshservice": {"label": "Freshservice", "short": "Freshservice", "connectable": True, "account_label": "", "secret_label": "API key",
                     "projects_label": "Groups (queues) to read (e.g. Analytics, Data platform)", "url_hint": "https://your-domain.freshservice.com",
                     "api": "Freshservice API v2: tickets, notes, updates"},
    "servicenow": {"label": "ServiceNow", "short": "ServiceNow", "connectable": True, "account_label": "Service account user name (empty for an OAuth token)",
                   "secret_label": "Password or OAuth token", "projects_label": "Assignment groups to read (e.g. Analytics, Data platform)",
                   "url_hint": "https://your-instance.service-now.com", "api": "ServiceNow Table API: incident (read, work notes, impact / urgency, create)"},
}
# Where a group's work goes. Modules that exist today get the real thing (D2D: a dashboard change request through the
# existing API); the others are recorded as work items with a link to the module page until their phase ships.
TARGETS = {"d2d": {"label": "D2D · Dashboards", "link": "#/d2d", "live": True, "what": "a dashboard change request"},
           "sdlc": {"label": "AI SDLC", "link": "#/m/sdlc", "live": False, "what": "a change request (P16)"},
           "heal": {"label": "Self-healing", "link": "#/m/heal", "live": False, "what": "a fix to diagnose and test (P16)"},
           "semantics": {"label": "Ontology & semantics", "link": "#/metrics", "live": True, "what": "a metric definition to settle"},
           "govern": {"label": "Govern", "link": "#/admin/people", "live": True, "what": "an access decision"}}
STATUS_LABEL = {"open": "To act on", "awaiting": "Waiting for approval", "sent_back": "Sent back", "written": "Written back", "partly": "Partly written back",
                "sent": "With a person", "handed": "Turned into work", "closed": "Closed"}
# What a source may do (the Connections hub's words). Read-only by default; even with a grant, every write waits for a
# named person's approval of exactly what is written (a checkpoint per change).
SCOPES = {"read": "Read-only", "comment": "Read & comment", "write": "Read & write — with approval"}
WRITE_KIND = "itsm.write"
OPS = {"create": "Raise a ticket", "comment": "Add a comment"}
NEEDS = {"create": ("write",), "comment": ("comment", "write")}
OPTIONS = {"jira": {"project": "Project for new tickets (key)", "issue_type": "Issue type for new tickets", "service_desk_id": "Service Management: service desk id",
                    "request_type_id": "Service Management: request type id", "sla_field": "SLA field id (Time to resolution)"},
           "freshservice": {"group": "Group for new tickets", "requester": "Requester e-mail for new tickets"},
           "servicenow": {"group": "Assignment group for new incidents", "requester": "Caller for new incidents (user name)"}}
WRITE_STATUS = {"waiting": "Waiting for approval", "written": "Written", "failed": "Not written", "sent_back": "Sent back", "refused": "Refused", "withdrawn": "Withdrawn"}
WRITE_HOOKS: dict = {}                  # origin prefix -> fn(write, event) — the module that asked hears what happened


class ItsmError(Exception):
    pass


class WriteBackRefused(ItsmError):
    """No accepted checkpoint covers this write - nothing is written."""


class WriteRefused(ItsmError):
    """The source may not do this (its scope, paused, a missing setting) - nothing is asked or written."""


# ------------------------------------------------------------------ sources

def _secret_name(sid: str) -> str:
    return f"itsm:{sid}:token"


def _src(sid: str) -> dict:
    s = db.one("SELECT * FROM itsm_sources WHERE id = ?", (sid,))
    if not s:
        raise HTTPException(404, "No such source.")
    s["projects"] = json.loads(s["projects"] or "[]")
    return s


def _opts(s: dict) -> dict:
    try:
        o = json.loads(s.get("options") or "{}")
    except ValueError:
        o = {}
    return o if isinstance(o, dict) else {}


def may(s: dict, op: str) -> bool:
    """May this source be written to in this way at all (each write still needs its own approval)?"""
    return (s.get("scope") or "read") in NEEDS.get(op, ()) and not s.get("paused")


def public_source(s: dict) -> dict:
    """Never the credential: only whether one is stored."""
    k = KINDS.get(s["kind"], {})
    scope = s.get("scope") or "read"
    u = auth.current.get()
    return {**{x: s[x] for x in ("id", "kind", "name", "base_url", "account", "projects", "poll_min", "paused", "status", "error", "last_read", "next_read",
                                 "reads", "open_tickets", "retries", "created", "created_by")},
            "scope": scope, "scope_label": SCOPES.get(scope, scope), "options": {key: v for key, v in _opts(s).items() if key in OPTIONS.get(s["kind"], {})},
            "may_create": may(s, "create"), "may_comment": may(s, "comment"), "can_grant": bool(u and (auth.is_admin(u) or u["id"] == s.get("created_by"))),
            "label": k.get("short", s["kind"]), "has_secret": secrets_store.get("org", s.get("secret_name") or _secret_name(s["id"])) is not None,
            "status_label": {"new": "Not read yet", "ok": "Connected", "sign_in": "Sign in again", "error": "Error", "paused": "Paused"}.get(
                "paused" if s["paused"] else s["status"], s["status"]),
            # for the Connections hub (read-only there): who added it and the screen that manages it — never the credential
            "owner": (db.one("SELECT name FROM users WHERE id = ?", (s["created_by"],)) or {}).get("name") if s.get("created_by") else None,
            "module": MODULE, "link": ROUTE, "category": "crm"}


def sources() -> list[dict]:
    rows = db.q("SELECT * FROM itsm_sources ORDER BY created")
    for r in rows:
        r["projects"] = json.loads(r["projects"] or "[]")
    return [public_source(r) for r in rows]


def _projects(v) -> list[str]:
    if isinstance(v, str):
        v = v.replace(";", ",").split(",")
    return [str(x).strip() for x in (v or []) if str(x).strip()][:20]


def save_source(body: dict, who: str | None, sid: str | None = None) -> dict:
    kind = (body.get("kind") or "").strip().lower() if not sid else _src(sid)["kind"]
    if kind not in KINDS:
        raise HTTPException(400, "Choose Jira, Freshservice or ServiceNow.")
    if not KINDS[kind]["connectable"]:
        raise HTTPException(400, f"{KINDS[kind]['label']} is next, not connectable yet.")
    url = (body.get("base_url") or "").strip().rstrip("/")
    if not url.startswith(("http://", "https://")):
        raise HTTPException(400, "The base URL must start with https:// (or http:// for a simulator).")
    name = (body.get("name") or f"{KINDS[kind]['short']} · {url.split('//', 1)[1].split('/')[0]}").strip()[:80]
    account = (body.get("account") or "").strip()[:200]          # Jira: the service account's e-mail (empty = bearer token)
    projects = _projects(body.get("projects"))
    try:
        poll = max(1, min(1440, int(body.get("poll_min") or 5)))
    except (TypeError, ValueError):
        raise HTTPException(400, "Poll interval must be minutes.")
    token = (body.get("token") or "").strip()
    now = time.time()
    if sid:
        db.run("UPDATE itsm_sources SET name = ?, base_url = ?, account = ?, projects = ?, poll_min = ?, next_read = ? WHERE id = ?",
               (name, url, account, json.dumps(projects), poll, now, sid))
    else:
        if not token:
            raise HTTPException(400, f"Give the service account's {KINDS[kind]['secret_label']} - it is kept in the secrets store by name only.")
        sid = "src-" + pysecrets.token_hex(4)
        db.run("INSERT INTO itsm_sources (id, kind, name, base_url, account, projects, poll_min, status, next_read, created, created_by, secret_name) "
               "VALUES (?, ?, ?, ?, ?, ?, ?, 'new', ?, ?, ?, ?)", (sid, kind, name, url, account, json.dumps(projects), poll, now, now, who, _secret_name(sid)))
    if token:
        secrets_store.put("org", _secret_name(sid), token, who)
        db.run("UPDATE itsm_sources SET status = CASE WHEN status = 'sign_in' THEN 'new' ELSE status END, error = NULL WHERE id = ?", (sid,))
    db.audit("itsm.source.save", sid, {"kind": kind, "name": name, "base_url": url, "projects": projects, "poll_min": poll, "token": "stored" if token else "kept"}, who)
    return public_source(_src(sid))


def remove_source(sid: str, who: str | None) -> None:
    s = _src(sid)
    for w in db.q("SELECT id FROM itsm_writes WHERE source_id = ? AND status = 'waiting'", (sid,)):
        _close_write(w["id"], "withdrawn", "The source was removed.", who)
    secrets_store.delete("org", s.get("secret_name") or _secret_name(sid), who)
    db.run("DELETE FROM itsm_tickets WHERE source_id = ?", (sid,))
    db.run("DELETE FROM itsm_sources WHERE id = ?", (sid,))
    db.audit("itsm.source.remove", sid, {"kind": s["kind"], "name": s["name"]}, who)
    retriage(who or "system")


def pause_source(sid: str, paused: bool, who: str | None) -> dict:
    db.run("UPDATE itsm_sources SET paused = ?, next_read = ? WHERE id = ?", (1 if paused else 0, time.time(), sid))
    db.audit("itsm.source.pause" if paused else "itsm.source.resume", sid, None, who)
    return public_source(_src(sid))


def adapter_for(s: dict):
    token = secrets_store.get("org", s.get("secret_name") or _secret_name(s["id"]))
    if not token:
        raise SignInAgain("No credential is stored for this source: add the service account's token.")
    if s["kind"] == "jira":
        return Jira(s["base_url"], s.get("account") or "", token, s["projects"], sla_field=_opts(s).get("sla_field"))
    if s["kind"] == "servicenow":
        return ServiceNow(s["base_url"], s.get("account") or "", token, s["projects"])
    return Freshservice(s["base_url"], token, s["projects"])


def set_scope(sid: str, scope: str, options: dict | None, u: dict) -> dict:
    """What the source may do, and how it raises tickets. Only an admin or the person who added it decides; audited."""
    s = _src(sid)
    if not (auth.is_admin(u) or u["id"] == s.get("created_by")):
        raise HTTPException(403, "Only an admin or the person who added this source decides what Relay may write to it.")
    if scope not in SCOPES:
        raise HTTPException(400, "Choose read, comment or write.")
    allowed = OPTIONS.get(s["kind"], {})
    opts = {**_opts(s), **{k: " ".join(str(v or "").split())[:120] for k, v in (options or {}).items() if k in allowed}}
    opts = {k: v for k, v in opts.items() if v}
    if s["kind"] == "jira" and opts.get("sla_field") and not re.match(r"^customfield_\d{3,6}$", opts["sla_field"]):
        raise HTTPException(400, "The SLA field id looks like customfield_10030.")
    if s["kind"] == "jira" and bool(opts.get("service_desk_id")) != bool(opts.get("request_type_id")):
        raise HTTPException(400, "Give both the service desk id and the request type id (or neither).")
    db.run("UPDATE itsm_sources SET scope = ?, options = ?, scope_by = ?, scope_at = ? WHERE id = ?", (scope, json.dumps(opts), u["id"], time.time(), sid))
    db.audit("itsm.source.scope", sid, {"scope": scope, "options": opts}, u["id"])
    if scope == "read":                                   # nothing may be written any more: the waiting write requests are withdrawn
        for w in db.q("SELECT id FROM itsm_writes WHERE source_id = ? AND status = 'waiting'", (sid,)):
            _close_write(w["id"], "withdrawn", "The source was made read-only.", u["id"])
    return public_source(_src(sid))


def test_source(sid: str, who: str | None) -> dict:
    s = _src(sid)
    try:
        out = adapter_for(s).test()
    except SignInAgain as e:
        db.run("UPDATE itsm_sources SET status = 'sign_in', error = ? WHERE id = ?", (str(e)[:300], sid))
        return {"ok": False, "status": "sign_in", "error": str(e)}
    except AdapterError as e:
        db.run("UPDATE itsm_sources SET status = 'error', error = ? WHERE id = ?", (str(e)[:300], sid))
        return {"ok": False, "status": "error", "error": str(e)}
    db.audit("itsm.source.test", sid, {"ok": out.get("ok"), "missing": out.get("missing")}, who)
    if out.get("ok"):
        db.run("UPDATE itsm_sources SET error = NULL, status = CASE WHEN status IN ('sign_in', 'error') THEN 'new' ELSE status END WHERE id = ?", (sid,))
    return {"ok": bool(out.get("ok")), "status": "ok" if out.get("ok") else "error", **out,
            "error": None if out.get("ok") else "Not found on the service desk: " + ", ".join(out.get("missing") or [])}


# ------------------------------------------------------------------ the cache and the sync job

def _tid(sid: str, key: str) -> str:
    return f"{sid}:{key}"


def _ticket_row(r: dict) -> dict:
    r["labels"] = json.loads(r.get("labels") or "[]")
    return r


def open_tickets(source_id: str | None = None) -> list[dict]:
    rows = db.q("SELECT * FROM itsm_tickets WHERE open = 1" + (" AND source_id = ?" if source_id else "") + " ORDER BY created", (source_id,) if source_id else ())
    return [_ticket_row(r) for r in rows]


def sync_source(sid: str, who: str | None = "scheduler") -> dict:
    """Read every open ticket of one source into the cache (new ones added, changed ones updated, vanished ones
    closed), then re-triage the whole queue. Not an LLM run: a few HTTP calls and a rules pass."""
    s = _src(sid)
    now = time.time()
    try:
        ad = adapter_for(s)
        fetched = list(ad.tickets())                 # the HTTP part first (outside the database lock)
        have_all = {r["id"]: r for r in db.q("SELECT id, updated, title FROM itsm_tickets WHERE source_id = ?", (sid,))}
        seen, added, changed, closed = set(), 0, 0, 0
        with db.transaction():
            for t in fetched:
                tid = _tid(sid, t["key"])
                seen.add(tid)
                have = have_all.get(tid)
                vals = (sid, t["key"], t["vendor_id"], t["title"], t["description"], t["status"], 1, t["priority"], t["reporter"], t["reporter_email"], t["team"],
                        t["created"], t["updated"], t["due"], json.dumps(t["labels"]), t["url"], now, tid)
                if have:
                    if (have.get("updated") or 0) != (t["updated"] or 0) or have.get("title") != t["title"]:
                        changed += 1
                    db.run("UPDATE itsm_tickets SET source_id = ?, key = ?, vendor_id = ?, title = ?, description = ?, status = ?, open = ?, priority = ?, reporter = ?, "
                           "reporter_email = ?, team = ?, created = ?, updated = ?, due = ?, labels = ?, url = ?, fetched = ? WHERE id = ?", vals)
                else:
                    added += 1
                    db.run("INSERT INTO itsm_tickets (source_id, key, vendor_id, title, description, status, open, priority, reporter, reporter_email, team, created, updated, "
                           "due, labels, url, fetched, id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", vals)
            for r in db.q("SELECT id FROM itsm_tickets WHERE source_id = ? AND open = 1", (sid,)):
                if r["id"] not in seen:
                    db.run("UPDATE itsm_tickets SET open = 0, fetched = ? WHERE id = ?", (now, r["id"]))
                    closed += 1
    except SignInAgain as e:
        db.run("UPDATE itsm_sources SET status = 'sign_in', error = ?, last_read = ?, next_read = ?, reads = reads + 1 WHERE id = ?",
               (str(e)[:300], now, now + s["poll_min"] * 60, sid))
        db.audit("itsm.sync", sid, {"ok": False, "sign_in": True, "error": str(e)[:200]}, who)
        return {"ok": False, "status": "sign_in", "error": str(e)}
    except Exception as e:  # noqa: BLE001 - the source shows the error; the scheduler tries again
        traceback.print_exc()
        db.run("UPDATE itsm_sources SET status = 'error', error = ?, last_read = ?, next_read = ?, reads = reads + 1 WHERE id = ?",
               (str(e)[:300], now, now + s["poll_min"] * 60, sid))
        db.audit("itsm.sync", sid, {"ok": False, "error": str(e)[:200]}, who)
        return {"ok": False, "status": "error", "error": str(e)}
    n_open = len(seen)
    db.run("UPDATE itsm_sources SET status = 'ok', error = NULL, last_read = ?, next_read = ?, reads = reads + 1, open_tickets = ?, retries = retries + ? WHERE id = ?",
           (now, now + s["poll_min"] * 60, n_open, ad.retries, sid))
    stats = retriage(who)
    out = {"ok": True, "status": "ok", "open": n_open, "added": added, "changed": changed, "closed": closed, "calls": ad.calls, "retries": ad.retries, **stats}
    db.audit("itsm.sync", sid, out, who)
    return out


def _fingerprint(member_ids: list[str]) -> str:
    return hashlib.sha1("\n".join(sorted(member_ids)).encode()).hexdigest()[:16]


def _gid(oldest_id: str) -> str:
    return "g-" + hashlib.sha1(oldest_id.encode()).hexdigest()[:10]


def retriage(who: str | None = "scheduler") -> dict:
    """Groups rebuilt from every open cached ticket. Ids are stable while a group's oldest ticket stays; a group whose
    tickets changed loses its open checkpoint (the subject moved on) and goes back to 'to act on'."""
    tickets = open_tickets()
    now = time.time()
    groups = triage.triage(tickets, now) if tickets else []
    live_ids, opened, withdrawn = set(), 0, 0
    with db.transaction():
        for g in groups:
            withdrawn += _store_group(g, tickets, now, live_ids, who)
    for r in db.q("SELECT id, status FROM itsm_groups WHERE closed IS NULL"):
        if r["id"] not in live_ids:
            if r["status"] == "awaiting":
                withdrawn += checkpoints.withdraw(KIND, r["id"], who=who)
            db.run("UPDATE itsm_groups SET status = 'closed', closed = ?, updated = ? WHERE id = ?", (now, now, r["id"]))
    if AUTO_CHECKPOINT:                                    # only where something may be written: a read-only source's groups wait on the screen
        ws = _writable_sources()
        for row in db.q("SELECT id, members FROM itsm_groups WHERE closed IS NULL AND status = 'open' AND checkpoint_id IS NULL AND (tickets >= 2 OR priority IN ('P1', 'P2'))"):
            if ws and any(str(m).split(":", 1)[0] in ws for m in json.loads(row["members"] or "[]")):
                open_checkpoint(row["id"], agent="Triage")
                opened += 1
    return {"tickets": len(tickets), "groups": len(groups), "checkpoints_opened": opened, "checkpoints_withdrawn": withdrawn}


def _store_group(g: dict, tickets: list[dict], now: float, live_ids: set, who: str | None) -> int:
    """One triage group into itsm_groups (insert, or update the row with the same stable id); returns how many
    checkpoints were withdrawn because the group's tickets changed."""
    withdrawn = 0
    members = [tickets[i] for i in g["members"]]
    ids = [m["id"] for m in members]
    gid = _gid(g["oldest"]["id"])
    live_ids.add(gid)
    fp = _fingerprint(ids)
    for m in members:
        db.run("UPDATE itsm_tickets SET category = ?, summary = ?, group_id = ? WHERE id = ?", (m.get("category"), m.get("summary"), gid, m["id"]))
    have = db.one("SELECT * FROM itsm_groups WHERE id = ?", (gid,))
    fields = (g["title"], g["about"], g["category"], g["summary"], g["priority"], g["reason"], g["route"], g["route_reason"], g["target"], g["target_label"],
              g["team"], g["tickets"], g["people"], g["sla_due"], g["near_sla"], json.dumps(ids), fp, now)
    if not have:
        db.run("INSERT INTO itsm_groups (title, about, category, summary, priority, reason, route, route_reason, target, target_label, team, tickets, people, sla_due, "
               "near_sla, members, fingerprint, updated, id, status, created) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?)", fields + (gid, now))
        return 0
    status, note = have["status"], have.get("note")
    if have["fingerprint"] != fp and have["status"] in ("awaiting", "sent_back", "written", "partly", "sent", "handed", "closed"):
        if have["status"] == "awaiting" and have.get("checkpoint_id"):
            withdrawn += checkpoints.withdraw(KIND, gid, who=who)
        status = "open"
        note = f"The tickets changed since it was {STATUS_LABEL.get(have['status'], have['status']).lower()}: look again." if have["status"] != "awaiting" else "The tickets changed: look again."
    keep = have["route"] if have.get("person_id") and have["status"] == "sent" else g["route"]
    db.run("UPDATE itsm_groups SET title = ?, about = ?, category = ?, summary = ?, priority = ?, reason = ?, route = ?, route_reason = ?, target = ?, target_label = ?, "
           "team = ?, tickets = ?, people = ?, sla_due = ?, near_sla = ?, members = ?, fingerprint = ?, updated = ?, status = ?, note = ?, closed = NULL, "
           "checkpoint_id = CASE WHEN ? = 'open' THEN NULL ELSE checkpoint_id END WHERE id = ?",
           fields[:6] + (keep,) + fields[7:] + (status, note, status, gid))
    return withdrawn


async def _job_sync(pid: str, args: dict) -> None:
    """The worker-lane form of the read (job kind itsm_sync): `worker.enqueue(<subject>, "itsm_sync", source=<id>)`."""
    await asyncio.to_thread(sync_source, args["source"], args.get("who") or "worker")


worker.register_job("itsm_sync", _job_sync, status="reading_tickets", done="Tickets read")


# ------------------------------------------------------------------ groups, the checkpoint and the write-back gate

def _grp(gid: str) -> dict:
    g = db.one("SELECT * FROM itsm_groups WHERE id = ?", (gid,))
    if not g:
        raise HTTPException(404, "No such group.")
    g["members"] = json.loads(g["members"] or "[]")
    return g


def public_group(g: dict, with_tickets: bool = False, writable: set[str] | None = None) -> dict:
    out = {k: v for k, v in g.items() if k != "members"}
    out["status_label"] = STATUS_LABEL.get(g["status"], g["status"])
    out["target_link"] = (TARGETS.get(g.get("target") or "") or {}).get("link")
    ws = writable if writable is not None else _writable_sources()
    out["writable"] = any(str(m).split(":", 1)[0] in ws for m in g.get("members") or [])
    out["written_by_name"] = _name(g.get("written_by")) if g.get("written_by") else None
    out["person_name"] = _name(g.get("person_id")) if g.get("person_id") else None
    if with_tickets:
        rows = db.q("SELECT * FROM itsm_tickets WHERE group_id = ? ORDER BY created", (g["id"],))
        srcs = {s["id"]: s for s in db.q("SELECT id, name, kind FROM itsm_sources")}
        out["ticket_list"] = [{**{k: r[k] for k in ("id", "key", "title", "status", "priority", "reporter", "team", "created", "updated", "due", "url", "summary", "category")},
                               "source": (srcs.get(r["source_id"]) or {}).get("name"), "kind": (srcs.get(r["source_id"]) or {}).get("kind"), "labels": json.loads(r["labels"] or "[]")}
                              for r in rows]
        out["decisions"] = [{**d, "detail": json.loads(d["detail"]) if d.get("detail") else None, "who_name": _name(d.get("who"))}
                            for d in db.q("SELECT * FROM itsm_decisions WHERE group_id = ? ORDER BY id DESC LIMIT 20", (g["id"],))]
        out["work"] = db.q("SELECT * FROM itsm_work WHERE group_id = ? ORDER BY created DESC", (g["id"],))
        if g.get("checkpoint_id"):
            out["checkpoint"] = checkpoints.get(g["checkpoint_id"])
    return out


def groups(status: str | None = None) -> list[dict]:
    rows = db.q("SELECT * FROM itsm_groups WHERE closed IS NULL ORDER BY CASE priority WHEN 'P1' THEN 0 WHEN 'P2' THEN 1 WHEN 'P3' THEN 2 ELSE 3 END, tickets DESC, created")
    out, ws = [], _writable_sources()
    for r in rows:
        r["members"] = json.loads(r["members"] or "[]")
        if status and r["status"] != status:
            continue
        out.append(public_group(r, writable=ws))
    return out


def _decision(gid: str, action: str, who: str | None, detail: dict | None = None) -> None:
    db.run("INSERT INTO itsm_decisions (group_id, action, who, ts, detail) VALUES (?, ?, ?, ?, ?)", (gid, action, who, time.time(), json.dumps(detail) if detail else None))


def _name(uid: str | None) -> str:
    """A person by name (what screens and written comments show — never a raw id); agents and the scheduler by role."""
    if not uid:
        return "Relay"
    row = db.one("SELECT name FROM users WHERE id = ?", (uid,))
    return row["name"] if row else ("Relay" if uid in ("scheduler", "worker", "system", "agent", "Triage") else "a person")


def _writable_sources() -> set[str]:
    return {r["id"] for r in db.q("SELECT id FROM itsm_sources WHERE scope IN ('comment', 'write') AND paused = 0")}


def group_writable(gid: str, members: list[str] | None = None) -> bool:
    """Can anything of this group be written back: is one of its tickets on a source that allows comments?"""
    if members is None:
        g = db.one("SELECT members FROM itsm_groups WHERE id = ?", (gid,))
        members = json.loads((g or {}).get("members") or "[]")
    ws = _writable_sources()
    return any(str(m).split(":", 1)[0] in ws for m in members)


def _evidence(g: dict) -> dict:
    rows = db.q("SELECT key, title, reporter, team, created, due, source_id FROM itsm_tickets WHERE group_id = ? ORDER BY created", (g["id"],))
    srcs = {s["id"]: s["name"] for s in db.q("SELECT id, name FROM itsm_sources")}
    return {"summary": g["summary"], "priority": g["priority"], "reason": g["reason"], "route": g["route"], "route_reason": g["route_reason"],
            "columns": ["Ticket", "Source", "Title", "Reporter", "Team", "Opened", "SLA"],
            "rows": [[r["key"], srcs.get(r["source_id"], ""), r["title"], r["reporter"], r["team"], r["created"], r["due"]] for r in rows],
            "items": [g["reason"], g["route_reason"], f"Goes to {g['target_label']} once a person decides"],
            "counts": {"tickets": g["tickets"], "people": g["people"], "near SLA": g["near_sla"]}, "fingerprint": g["fingerprint"],
            "writes": "a private comment / note with the summary, the priority and the group link on every ticket whose source allows comments "
                      "(the priority and a label too where it allows writes; nothing on a read-only source)"}


def open_checkpoint(gid: str, agent: str = "Triage", who: str | None = None) -> dict:
    """The group's checkpoint: the Validation queue shows the tickets (view table), summary, proposed priority and
    the reason; accepting it is what allows the write-back."""
    g = _grp(gid)
    c = checkpoints.open(KIND, gid, MODULE, f"Write back: {g['title']} ({g['tickets']} ticket{'s' if g['tickets'] != 1 else ''})", "table", _evidence(g),
                         link=f"{ROUTE}/{gid}", agent=agent, opened_by=who)
    db.run("UPDATE itsm_groups SET status = 'awaiting', checkpoint_id = ?, updated = ? WHERE id = ?", (c["id"], time.time(), gid))
    _decision(gid, "writeback_requested", who or agent, {"checkpoint": c["id"]})
    return c


def _on_decision(c: dict, decision: str, comment: str | None, who: str) -> None:
    gid = c["subject"]
    g = db.one("SELECT * FROM itsm_groups WHERE id = ?", (gid,))
    if not g:
        return
    if decision == "accept":
        try:
            write_back(gid, who, c["id"])
        except ItsmError as e:                      # refused (the tickets changed) or nothing could be written: back to "to act on"
            db.run("UPDATE itsm_groups SET status = 'open', note = ?, checkpoint_id = NULL, updated = ? WHERE id = ?", (str(e)[:300], time.time(), gid))
    else:
        db.run("UPDATE itsm_groups SET status = 'sent_back', note = ?, checkpoint_id = NULL, updated = ? WHERE id = ?", ((comment or "")[:500], time.time(), gid))
        _decision(gid, "sent_back", who, {"comment": (comment or "")[:500], "checkpoint": c["id"]})
        db.audit("itsm.sent_back", gid, {"comment": (comment or "")[:300]}, who)


checkpoints.register_kind(KIND, "Service desk write-back", _on_decision)


def _accepted_checkpoint(gid: str, cid: str | None) -> dict:
    """The accepted checkpoint that covers this group as it is now - or WriteBackRefused."""
    g = _grp(gid)
    c = checkpoints.get(cid) if cid else None
    if c is None:
        rows = db.q("SELECT id FROM checkpoints WHERE kind = ? AND subject = ? AND status = 'accepted' ORDER BY decided DESC LIMIT 1", (KIND, gid))
        c = checkpoints.get(rows[0]["id"]) if rows else None
    if not c or c["kind"] != KIND or c["subject"] != gid:
        raise WriteBackRefused("Nothing is written to the service desk without an accepted checkpoint for this group.")
    if c["status"] != "accepted":
        raise WriteBackRefused(f"The checkpoint for this group is {c['status'].replace('_', ' ')}, not accepted.")
    if g.get("written_cp") == c["id"]:
        raise WriteBackRefused("This approval was already used; the tickets changed, so a new approval is needed.")
    if (c.get("evidence") or {}).get("fingerprint") and c["evidence"]["fingerprint"] != g["fingerprint"]:
        raise WriteBackRefused("The group's tickets changed after the approval; a person must look again.")
    return c


def write_back(gid: str, who: str, checkpoint_id: str | None = None) -> dict:
    """The only path to a service desk write: summary + priority + group link on every ticket of the group, after
    `_accepted_checkpoint` found the person's accepted checkpoint for exactly these tickets."""
    c = _accepted_checkpoint(gid, checkpoint_id)
    g = _grp(gid)
    rows = db.q("SELECT * FROM itsm_tickets WHERE group_id = ? ORDER BY created", (gid,))
    srcs = {s["id"]: s for s in db.q("SELECT * FROM itsm_sources")}
    for s in srcs.values():
        s["projects"] = json.loads(s["projects"] or "[]")
    adapters: dict[str, object] = {}
    keys = [r["key"] for r in rows]
    results, errors = [], []
    for r in rows:
        s = srcs.get(r["source_id"])
        if not s:
            errors.append(f"{r['key']}: its source is gone"); continue
        scope = s.get("scope") or "read"
        if scope == "read" or s.get("paused"):          # read-only by default: nothing is written to this source's tickets
            errors.append(f"{r['key']}: {s['name']} is {'paused' if s.get('paused') else 'read-only'} — nothing written"); continue
        try:
            ad = adapters.get(s["id"]) or adapters.setdefault(s["id"], adapter_for(s))
            others = [k for k in keys if k != r["key"]]
            text = (f"Relay triage - {g['priority']} ({triage.PRIORITY_LABEL[g['priority']]})\n\n{g['summary']}\n\n{g['reason']}\n\n"
                    + (f"Grouped with {len(others)} ticket{'s' if len(others) != 1 else ''}: {', '.join(others[:12])}{' …' if len(others) > 12 else ''}.\n\n" if others else "")
                    + f"{g['route_reason']} Approved by {_name(who)}; group {gid}.")
            label = f"relay-{gid}"
            if s["kind"] == "jira":
                ad.comment(r["key"], text)
                if scope == "write":                        # field edits only with write access; "comment" posts the comment alone
                    ad.edit(r["key"], {"priority": {"name": _jira_priority(g["priority"])}, "labels": sorted(set(json.loads(r["labels"] or "[]")) | {label})})
            elif s["kind"] == "servicenow":                 # a work note (internal); with write access impact / urgency set the priority
                ad.comment(r["vendor_id"] or r["key"], text)
                if scope == "write":
                    ad.set_priority(r["vendor_id"] or r["key"], g["priority"])
            else:
                ad.note(r["vendor_id"], text, private=True)
                if scope == "write":
                    ad.update(r["vendor_id"], {"priority": _fresh_priority(g["priority"]), "tags": sorted(set(json.loads(r["labels"] or "[]")) | {label})})
            results.append(r["key"])
        except SignInAgain as e:
            errors.append(f"{r['key']}: {e}")
            db.run("UPDATE itsm_sources SET status = 'sign_in', error = ? WHERE id = ?", (str(e)[:300], s["id"]))
        except (AdapterError, Exception) as e:  # noqa: BLE001 - one bad ticket does not stop the rest
            traceback.print_exc()
            errors.append(f"{r['key']}: {e}")
    now = time.time()
    status = "written" if not errors else ("partly" if results else "open")
    db.run("UPDATE itsm_groups SET status = ?, written = ?, written_by = ?, written_cp = ?, note = ?, updated = ? WHERE id = ?",
           (status, now if results else None, who if results else None, c["id"] if results else None, ("; ".join(errors)[:500] or None), now, gid))
    detail = {"checkpoint": c["id"], "written": results, "errors": errors, "priority": g["priority"]}
    _decision(gid, "writeback", who, detail)
    db.audit("itsm.writeback", gid, {"tickets": len(results), "errors": len(errors), "priority": g["priority"], "checkpoint": c["id"]}, who)
    if errors and not results:
        raise ItsmError("Nothing could be written: " + "; ".join(errors)[:300])
    return {"ok": not errors, "written": results, "errors": errors, "status": status}


def _jira_priority(p: str) -> str:
    from .itsm_adapters.jira import PRIORITY
    return PRIORITY.get(p, "Medium")


def _fresh_priority(p: str) -> int:
    from .itsm_adapters.freshservice import PRIORITY
    return PRIORITY.get(p, 2)


# ------------------------------------------------------------------ writes other modules ask for (consolidation): a new ticket, a comment
# The only way any other module writes to a service desk. The source's scope must allow it (read-only by default;
# "Read & comment" for a comment, "Read & write — with approval" for a new ticket), and a checkpoint (kind itsm.write)
# opens with exactly what will be written; the adapter writes when — and only when — a named person accepts it, once.

def register_write_hook(prefix: str, fn) -> None:
    """The module that asks hears what happened: fn(write, event), event = written | failed | sent_back | withdrawn |
    refused; `prefix` is the first part of the origin it passes (observe_work:<id>, intan_work:<id>, sdlc:<id>)."""
    WRITE_HOOKS[prefix] = fn


def _fp(sid: str, op: str, payload: dict) -> str:
    return hashlib.sha1(json.dumps([sid, op, payload], sort_keys=True).encode()).hexdigest()[:16]


def _why_not(s: dict, op: str) -> str:
    if s.get("paused"):
        return f"{s['name']} is paused: resume it before Relay writes to it."
    need = SCOPES["write"] if op == "create" else SCOPES["comment"]
    return (f"{s['name']} is {SCOPES.get(s.get('scope') or 'read', 'read-only').lower()}: to {OPS[op].lower()} it must allow “{need}”. "
            "An admin, or the person who added the source, changes that under Service desk › Sources.")


def ticket_target() -> dict | None:
    """The source new tickets go to: the first one that may raise tickets (None when no source may)."""
    for s in db.q("SELECT * FROM itsm_sources WHERE scope = 'write' AND paused = 0 ORDER BY created"):
        s["projects"] = json.loads(s["projects"] or "[]")
        return s
    return None


def _clean(s: dict, op: str, payload: dict) -> dict:
    """What will be written, normalised (the approval covers exactly this)."""
    o = _opts(s)
    if op == "comment":
        key, text = str(payload.get("key") or "").strip(), str(payload.get("text") or "").strip()
        if not key or not text:
            raise WriteRefused("A comment needs the ticket and the text.")
        return {"key": key[:40], "text": text[:4000]}
    title = " ".join(str(payload.get("title") or "").split())[:255]
    if not title:
        raise WriteRefused("A ticket needs a title.")
    out = {"title": title, "description": str(payload.get("description") or title).strip()[:8000],
           "priority": payload.get("priority") if payload.get("priority") in ("P1", "P2", "P3", "P4") else "P3",
           "labels": sorted({str(x).strip().replace(" ", "-")[:40] for x in (payload.get("labels") or []) if str(x).strip()} | {"relay"})}
    if s["kind"] == "jira":
        if o.get("service_desk_id") and o.get("request_type_id"):
            out.update(service_desk=o["service_desk_id"], request_type=o["request_type_id"])
        out["project"] = (o.get("project") or (s["projects"] or [""])[0]).upper()
        out["issue_type"] = o.get("issue_type") or "Task"
        if not out["project"] and "service_desk" not in out:
            raise WriteRefused(f"{s['name']} does not say which project new tickets go to: set it under Service desk › Sources › May do.")
    else:
        out["project"] = o.get("group") or (s["projects"] or [""])[0]
        if o.get("requester"):
            out["requester"] = o["requester"]
    return out


def _lines(s: dict, op: str, p: dict) -> list[tuple[str, str]]:
    if op == "comment":
        return [("Ticket", p["key"]), ("Comment", p["text"])]
    where = (f"service desk {p['service_desk']}, request type {p['request_type']}" if p.get("service_desk")
             else f"project {p['project']} · {p.get('issue_type')}" if s["kind"] == "jira" else f"group {p['project']}" if p.get("project") else "its default group")
    return [("Where", f"{s['name']} · {where}"), ("Title", p["title"]), ("Priority", f"{p['priority']} ({triage.PRIORITY_LABEL.get(p['priority'], '')})"),
            ("Labels", ", ".join(p["labels"])), ("Description", p["description"])]


def public_write(w: dict) -> dict:
    p = json.loads(w.get("payload") or "{}")
    s = db.one("SELECT name, kind FROM itsm_sources WHERE id = ?", (w["source_id"],)) or {}
    return {**{k: w.get(k) for k in ("id", "source_id", "op", "target", "module", "origin", "link", "status", "checkpoint_id", "error", "created", "updated", "written")},
            "op_label": OPS.get(w["op"], w["op"]), "status_label": WRITE_STATUS.get(w["status"], w["status"]), "source": s.get("name") or "a removed source",
            "payload": p, "result": json.loads(w["result"]) if w.get("result") else None, "title": p.get("title") or f"Comment on {p.get('key')}",
            "requested_by_name": _name(w.get("requested_by")) if w.get("requested_by") else None, "decided_by_name": _name(w.get("decided_by")) if w.get("decided_by") else None}


def writes(limit: int = 30) -> list[dict]:
    return [public_write(w) for w in db.q("SELECT * FROM itsm_writes ORDER BY created DESC LIMIT ?", (limit,))]


def request_write(sid: str, op: str, payload: dict, *, who: str | None, module: str, origin: str | None = None, link: str | None = None,
                  assignee: str | None = None, name: str | None = None) -> dict:
    """Ask for one write. Refused at once (WriteRefused, nothing asked) when the source may not do it; otherwise a
    checkpoint opens with the exact payload and the write waits for a named person. The same origin asking again for
    the same write gets the waiting one back."""
    s = _src(sid)
    if op not in OPS:
        raise WriteRefused("Relay raises tickets and adds comments; nothing else is written for other modules.")
    if not may(s, op):
        raise WriteRefused(_why_not(s, op))
    p = _clean(s, op, payload)
    fp = _fp(sid, op, p)
    if origin:
        have = db.one("SELECT * FROM itsm_writes WHERE origin = ? AND op = ? AND status = 'waiting'", (origin, op))
        if have and have["fingerprint"] == fp:
            return public_write(have)
        if have:
            _close_write(have["id"], "withdrawn", "A newer request for the same work replaced it.", who)
    wid = "wr-" + pysecrets.token_hex(5)
    rows = _lines(s, op, p)
    now = time.time()
    db.run("INSERT INTO itsm_writes (id, source_id, op, target, payload, fingerprint, module, origin, link, status, requested_by, created, updated) "
           "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'waiting', ?, ?, ?)", (wid, sid, op, p.get("key") or p.get("project"), json.dumps(p), fp, module, origin, link, who, now, now))
    ev = {"summary": f"{OPS[op]} on {s['name']} ({KINDS[s['kind']]['short']}) for {module} — exactly this is written, once, signed with your name, after you "
                     "accept; nothing before.", "items": [f"{k}: {v[:200]}" for k, v in rows], "columns": ["What", "Will be written"], "rows": [[k, v] for k, v in rows],
          "op": op, "source": {"id": sid, "name": s["name"], "kind": s["kind"]}, "payload": p, "fingerprint": fp, "module": module, "write": wid}
    title = name or (f"{OPS[op]} on {s['name']}: {p['title']}" if op == "create" else f"Comment on {p['key']} ({s['name']})")
    cp = checkpoints.open(WRITE_KIND, wid, module, title[:200], "table", ev, link=link or f"{ROUTE}?write={wid}", assignee=assignee, agent="Relay", opened_by=who)
    db.run("UPDATE itsm_writes SET checkpoint_id = ? WHERE id = ?", (cp["id"], wid))
    db.audit("itsm.write.requested", wid, {"source": sid, "op": op, "origin": origin, "module": module, "checkpoint": cp["id"]}, who)
    return public_write(db.one("SELECT * FROM itsm_writes WHERE id = ?", (wid,)))


def _hook(wid: str, event: str) -> None:
    w = db.one("SELECT * FROM itsm_writes WHERE id = ?", (wid,))
    fn = WRITE_HOOKS.get(str((w or {}).get("origin") or "").split(":", 1)[0])
    if w and fn:
        try:
            fn(public_write(w), event)
        except Exception:  # noqa: BLE001 - the write is recorded either way
            traceback.print_exc()


def _close_write(wid: str, status: str, why: str | None, who: str | None) -> None:
    w = db.one("SELECT * FROM itsm_writes WHERE id = ?", (wid,))
    if not w or w["status"] != "waiting":
        return
    checkpoints.withdraw(WRITE_KIND, wid, who=who)
    db.run("UPDATE itsm_writes SET status = ?, error = ?, updated = ? WHERE id = ?", (status, (why or "")[:500] or None, time.time(), wid))
    db.audit(f"itsm.write.{status}", wid, {"why": (why or "")[:200]}, who)
    _hook(wid, status)


def perform_write(wid: str, who: str, checkpoint_id: str | None) -> dict:
    """The write itself: only with the accepted checkpoint for exactly this payload, used once, on a source that
    still allows it (its scope may have changed since the request)."""
    w = db.one("SELECT * FROM itsm_writes WHERE id = ?", (wid,))
    if not w:
        raise WriteBackRefused("No such write.")
    c = checkpoints.get(checkpoint_id) if checkpoint_id else None
    if not c or c["kind"] != WRITE_KIND or c["subject"] != wid or c["status"] != "accepted":
        raise WriteBackRefused("Nothing is written to the service desk without an accepted checkpoint for this write.")
    if w["status"] != "waiting":
        raise WriteBackRefused(f"This write is already {WRITE_STATUS.get(w['status'], w['status']).lower()}: its approval cannot be used again.")
    p = json.loads(w["payload"])
    if (c.get("evidence") or {}).get("fingerprint") != w["fingerprint"] or _fp(w["source_id"], w["op"], p) != w["fingerprint"]:
        _close_write(wid, "refused", "What would be written changed after the approval; ask again.", who)
        raise WriteBackRefused("What would be written changed after the approval; nothing was written.")
    s = _src(w["source_id"])
    if not may(s, w["op"]):
        why = _why_not(s, w["op"])
        db.run("UPDATE itsm_writes SET status = 'refused', error = ?, decided_by = ?, updated = ? WHERE id = ?", (why[:500], who, time.time(), wid))
        db.audit("itsm.write.refused", wid, {"why": why[:200]}, who)
        _hook(wid, "refused")
        raise WriteRefused(why)
    signed = f"\n\nWritten by Relay for {w['module']} after {_name(who)} approved it."
    try:
        ad = adapter_for(s)
        if w["op"] == "create":
            res = ad.create_issue(p.get("project") or "", p["title"], p["description"] + signed, issue_type=p.get("issue_type") or "Task", priority=p.get("priority"),
                                  labels=p.get("labels"), service_desk=p.get("service_desk"), request_type=p.get("request_type"), requester=p.get("requester"))
        else:
            res = ad.add_comment(p["key"], p["text"] + signed)
    except Exception as e:  # noqa: BLE001 - the refusal is recorded and the asker is told; nothing half-written is retried blindly
        if isinstance(e, SignInAgain):
            db.run("UPDATE itsm_sources SET status = 'sign_in', error = ? WHERE id = ?", (str(e)[:300], s["id"]))
        traceback.print_exc()
        db.run("UPDATE itsm_writes SET status = 'failed', error = ?, decided_by = ?, updated = ? WHERE id = ?", (str(e)[:500], who, time.time(), wid))
        db.audit("itsm.write.failed", wid, {"source": s["id"], "op": w["op"], "error": str(e)[:200]}, who)
        notify.add(who, "alert", f"Not written to {s['name']}", str(e)[:300], f"{ROUTE}?write={wid}")
        _hook(wid, "failed")
        raise ItsmError(f"{s['name']} did not take the write: {e}") from e
    now = time.time()
    db.run("UPDATE itsm_writes SET status = 'written', result = ?, decided_by = ?, written = ?, updated = ?, error = NULL WHERE id = ?", (json.dumps(res), who, now, now, wid))
    db.audit("itsm.write", wid, {"source": s["id"], "op": w["op"], "key": res.get("key"), "url": res.get("url"), "checkpoint": c["id"], "module": w["module"]}, who)
    _hook(wid, "written")
    return public_write(db.one("SELECT * FROM itsm_writes WHERE id = ?", (wid,)))


def _on_write_decision(c: dict, decision: str, comment: str | None, who: str) -> None:
    w = db.one("SELECT * FROM itsm_writes WHERE id = ?", (c["subject"],))
    if not w or w["status"] != "waiting":
        return
    if decision != "accept":
        db.run("UPDATE itsm_writes SET status = 'sent_back', error = ?, decided_by = ?, updated = ? WHERE id = ?", ((comment or "")[:500] or None, who, time.time(), w["id"]))
        db.audit("itsm.write.sent_back", w["id"], {"comment": (comment or "")[:200]}, who)
        _hook(w["id"], "sent_back")
        return
    try:
        perform_write(w["id"], who, c["id"])
    except ItsmError:                                        # recorded on the write, the asker's hook and the approver's notifications
        pass


checkpoints.register_kind(WRITE_KIND, "Service desk write", _on_write_decision)


def drafts() -> list[dict]:
    """Ticket drafts other modules left for the Service desk: an approved Integration analytics or Data observability
    action that should become a ticket while no source may raise one yet. 'Raise it' asks for the write."""
    tables, out = set(db.tables()), []
    busy = {w["origin"] for w in db.q("SELECT origin FROM itsm_writes WHERE origin IS NOT NULL AND status IN ('waiting', 'written')")}
    if "intan_work" in tables:
        for w in db.q("SELECT w.*, i.name AS iname FROM intan_work w JOIN intan_integrations i ON i.id = w.integration_id WHERE w.kind = 'ticket' AND w.status = 'drafted' ORDER BY w.created DESC"):
            if f"intan_work:{w['id']}" not in busy:
                b = json.loads(w["body"] or "{}")
                out.append({"origin": f"intan_work:{w['id']}", "module": "Integration analytics", "title": b.get("summary") or w["title"], "cause": b.get("cause"),
                            "priority": w.get("priority") or b.get("priority") or "P3", "created": w["created"], "link": f"#/integrations?open={w['integration_id']}",
                            "evidence": b.get("evidence") or [], "owner": b.get("owner")})
    if "observe_work" in tables:
        for w in db.q("SELECT * FROM observe_work WHERE kind = 'ticket' AND status = 'approved' ORDER BY created DESC"):
            b = json.loads(w["body"] or "{}")
            if f"observe_work:{w['id']}" not in busy and not ((b.get("handed") or {}).get("checkpoint")):
                out.append({"origin": f"observe_work:{w['id']}", "module": "Data observability", "title": b.get("summary") or w["title"], "cause": b.get("cause"),
                            "priority": w.get("priority") or b.get("priority") or "P3", "created": w["created"], "link": f"#/observability?open={w['incident_id']}",
                            "evidence": [], "owner": None, "reports": b.get("reports") or []})
    return out


def draft_payload(d: dict) -> dict:
    """The ticket a draft becomes: its summary as the title, the cause, the evidence and where it came from."""
    lines = [d.get("cause") or ""]
    if d.get("reports"):
        lines.append("Affects: " + ", ".join(d["reports"][:8]))
    if d.get("owner"):
        lines.append(f"Owner: {d['owner']}")
    for e in (d.get("evidence") or [])[:6]:
        lines.append(" · ".join(str(e.get(k)) for k in ("when", "status", "duration", "error") if e.get(k)))
    lines.append(f"From {d['module']} in Relay.")
    return {"title": d["title"], "description": "\n\n".join(x for x in lines if x), "priority": d.get("priority") or "P3", "labels": [d["module"].lower().replace(" ", "-")]}


def raise_draft(origin: str, sid: str | None, who: str) -> dict:
    d = next((x for x in drafts() if x["origin"] == origin), None)
    if not d:
        raise HTTPException(404, "No such draft (it may have been raised already).")
    s = _src(sid) if sid else ticket_target()
    if not s:
        raise WriteRefused("No source may raise tickets yet: an admin allows “Read & write — with approval” on one under Sources.")
    return request_write(s["id"], "create", draft_payload(d), who=who, module=d["module"], origin=origin, link=d["link"], name=f"Raise a ticket on {s['name']}: {d['title']}")


def accept(gid: str, who: str) -> dict:
    """'Accept & write back' on the screen: the person confirms the group with its evidence in front of them. The
    open checkpoint is accepted (signed, audited) - or one is opened and accepted in the same signed step - and the
    write-back runs through the checkpoint hook. Nothing is written any other way."""
    g = _grp(gid)
    if g["status"] in ("written",):
        raise HTTPException(409, "This group was already written back; it needs a new approval only if its tickets change.")
    if not group_writable(gid, g["members"]):
        raise ItsmError("Nothing can be written back: the tickets' sources are read-only (or paused). An admin, or the person who added a source, "
                        "allows comments under Service desk › Sources › May do.")
    cid = g.get("checkpoint_id")
    c = checkpoints.get(cid) if cid else None
    if not c or c["status"] != "open":
        c = open_checkpoint(gid, agent="Triage", who=who)
    c = checkpoints.decide(c["id"], "accept", who)
    g = _grp(gid)
    return {"checkpoint": c, "group": public_group(g, True), "state": g["status"]}


def send_to_person(gid: str, to: str, note: str | None, who: str) -> dict:
    g = _grp(gid)
    if not db.user(to):
        raise HTTPException(400, "No such person.")
    now = time.time()
    if g["status"] == "awaiting" and g.get("checkpoint_id"):
        checkpoints.reassign(g["checkpoint_id"], to, who)
    db.run("UPDATE itsm_groups SET route = 'person', person_id = ?, status = CASE WHEN status = 'awaiting' THEN 'awaiting' ELSE 'sent' END, note = ?, updated = ? WHERE id = ?",
           (to, (note or "")[:500] or None, now, gid))
    notify.add(to, "review", f"Service desk: {g['title']}", (note or g["summary"] or "")[:300], f"{ROUTE}/{gid}")
    _decision(gid, "person", who, {"to": to, "note": (note or "")[:300]})
    db.audit("itsm.person", gid, {"to": to}, who)
    return public_group(_grp(gid), True)


async def hand_off(gid: str, target: str, who: str, project: str | None = None, note: str | None = None) -> dict:
    """Turn the group into work. D2D exists today: a real dashboard change request through the existing API; the
    other targets are recorded as work items with a link until their module ships."""
    g = _grp(gid)
    if target not in TARGETS:
        raise HTTPException(400, "Choose where the work goes: " + ", ".join(TARGETS))
    t = TARGETS[target]
    wid = "w-" + pysecrets.token_hex(4)
    link, status, extra = t["link"], "recorded", {}
    text = f"{g['summary']}\n\n{g['reason']}\n\nTickets: " + ", ".join(r["key"] for r in db.q("SELECT key FROM itsm_tickets WHERE group_id = ? ORDER BY created", (gid,))) + (f"\n\n{note}" if note else "")
    if target == "d2d":
        if not project:
            raise HTTPException(400, "Choose the dashboard the change request is for.")
        from . import main as app_main                              # late import: main imports phases, which imports this module
        try:
            st = await app_main.feedback(project, text=f"Service desk group {gid}: {g['title']}\n\n{text}", version=None, files=[], images=[])
        except HTTPException as e:
            raise HTTPException(e.status_code, f"The dashboard change request was not created: {e.detail}")
        link, status, extra = f"#/p/{project}", "created", {"project": project, "dashboard": st.get("name") if isinstance(st, dict) else None}
    db.run("INSERT INTO itsm_work (id, group_id, target, target_label, link, status, project, note, who, created) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
           (wid, gid, target, t["label"], link, status, project, (note or "")[:500] or None, who, time.time()))
    db.run("UPDATE itsm_groups SET status = CASE WHEN status IN ('written', 'partly') THEN status ELSE 'handed' END, work_id = ?, target = ?, target_label = ?, updated = ? WHERE id = ?",
           (wid, target, t["label"], time.time(), gid))
    _decision(gid, "handoff", who, {"target": target, "work": wid, "status": status, **extra})
    db.audit("itsm.handoff", gid, {"target": target, "work": wid, "status": status, **extra}, who)
    return {"work": db.one("SELECT * FROM itsm_work WHERE id = ?", (wid,)), "group": public_group(_grp(gid), True)}


# ------------------------------------------------------------------ summary, quality

def summary() -> dict:
    now = time.time()
    srcs = sources()
    open_n = db.one("SELECT COUNT(*) AS n FROM itsm_tickets WHERE open = 1")["n"]
    act = db.one("SELECT COUNT(*) AS n FROM itsm_groups WHERE closed IS NULL AND status IN ('open', 'awaiting', 'sent_back')")["n"]
    agent = db.one("SELECT COALESCE(SUM(tickets), 0) AS n FROM itsm_groups WHERE closed IS NULL AND route = 'agent' AND status IN ('open', 'awaiting', 'sent_back')")["n"]
    near = db.one("SELECT COUNT(*) AS n FROM itsm_tickets WHERE open = 1 AND due IS NOT NULL AND due >= ? AND due <= ?", (now, now + triage.NEAR_SLA_H * 3600))["n"]
    groups_n = db.one("SELECT COUNT(*) AS n FROM itsm_groups WHERE closed IS NULL")["n"]
    written = db.one("SELECT COUNT(*) AS n FROM itsm_groups WHERE status IN ('written', 'partly')")["n"]
    return {"sources": len(srcs), "by_source": [{"id": s["id"], "name": s["name"], "kind": s["kind"], "label": s["label"], "status": s["status"], "status_label": s["status_label"],
                                                 "open": s["open_tickets"], "last_read": s["last_read"]} for s in srcs],
            "open_tickets": open_n, "groups": groups_n, "to_act": act, "agent": int(agent or 0), "near_sla": near, "written": written,
            "hint": None if srcs else "Connect Jira, Freshservice or ServiceNow", "route": ROUTE}


def quality() -> dict | None:
    """Precision / recall of today's groups against the mock lab's labelled tickets (fx-g<n>), when any are cached."""
    tickets = open_tickets()
    labelled = [t for t in tickets if any(str(l).startswith("fx-g") for l in t["labels"])]
    if not labelled:
        return None
    pred: dict[str, list[str]] = {}
    for t in labelled:                                   # scored within each source: the labels are per fixture
        pred.setdefault(f"{t['source_id']}:{t.get('group_id') or t['id']}", []).append(t["id"])
    truth: dict[str, list[str]] = {}
    for t in labelled:
        for l in t["labels"]:
            if str(l).startswith("fx-g"):
                truth.setdefault(f"{t['source_id']}:{l}", []).append(t["id"])
    return {**triage.pair_scores(pred, truth), "labelled": len(labelled), "of": len(tickets), "fixture": "mock lab fx-g labels"}


# ------------------------------------------------------------------ optional LLM refinement (ITSM_LLM=1)

def llm_on() -> bool:
    return os.environ.get("ITSM_LLM", "") == "1" or db.meta("itsm_llm") == "1"


async def refine_with_llm(who: str | None = None) -> dict:
    """Behind a flag: one run of the sequential agent lane rewrites the groups' summaries (and, with a reason,
    priorities). The groups never change. The run works in the subject folder output/projects/servicedesk."""
    from pathlib import Path

    from . import itsm_prompts, store
    rows = [g for g in groups() if g["status"] in ("open", "awaiting", "sent_back")]
    if not rows:
        return {"refined": 0}
    pid = "servicedesk"
    d = store.ROOT / pid
    if not (d / "project.json").exists():
        d.mkdir(parents=True, exist_ok=True)
        store.save({"id": pid, "kind": "servicedesk", "name": "Service desk triage", "prompt": "Service desk triage refinement", "status": "done", "created": time.time(),
                    "versions": [], "runs": [], "job": None, "error": None})
        db.add_project(pid, who or db.ADMIN_ID)
    elif not store.load(pid).get("kind"):                # a folder made before it had a kind was listed among the dashboards
        store.update(pid, kind="servicedesk")
    payload = []
    for g in rows:
        ts = db.q("SELECT key, title, description, reporter, team, due FROM itsm_tickets WHERE group_id = ? ORDER BY created", (g["id"],))
        payload.append({"id": g["id"], "summary": g["summary"], "priority": g["priority"], "reason": g["reason"], "tickets": ts})
    Path(d / "triage_input.json").write_text(json.dumps({"groups": payload}, indent=1), encoding="utf-8")
    out_path = d / "triage_output.json"
    if out_path.exists():
        out_path.unlink()
    await worker.agent(pid, "triage", itsm_prompts.refine(len(payload)), 12, "triage")
    try:
        out = json.loads(out_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ItsmError(f"The agent did not write triage_output.json: {e}")
    by_id = {g["id"]: g for g in rows}
    n = 0
    for item in out.get("groups") or []:
        g = by_id.get(item.get("id"))
        if not g:
            continue
        summary_txt = str(item.get("summary") or "").strip()[:600]
        if summary_txt:
            db.run("UPDATE itsm_groups SET summary = ?, updated = ? WHERE id = ?", (summary_txt, time.time(), g["id"]))
            n += 1
        p = item.get("priority")
        if p in ("P1", "P2", "P3", "P4") and p != g["priority"] and str(item.get("reason") or "").strip():
            db.run("UPDATE itsm_groups SET priority = ?, reason = ?, updated = ? WHERE id = ?", (p, f"{p} ({triage.PRIORITY_LABEL[p]}): {str(item['reason']).strip()[:300]} (agent)", time.time(), g["id"]))
    db.audit("itsm.refine", None, {"groups": len(payload), "refined": n}, who)
    return {"refined": n, "groups": len(payload)}


# ------------------------------------------------------------------ the scheduler (lazy; started by the router)

_tasks: dict[int, asyncio.Task] = {}          # one polling task per event loop (the app's; a test's)
_locks: dict[int, asyncio.Lock] = {}          # reads never overlap on a loop


def _lock() -> asyncio.Lock:
    key = id(asyncio.get_running_loop())
    return _locks.setdefault(key, asyncio.Lock())


def due_sources(now: float | None = None) -> list[dict]:
    now = now or time.time()
    return [s for s in db.q("SELECT * FROM itsm_sources WHERE paused = 0 ORDER BY next_read") if (s["next_read"] or 0) <= now]


async def read_source(sid: str, who: str | None) -> dict:
    async with _lock():
        out = await asyncio.to_thread(sync_source, sid, who)
    if out.get("ok") and llm_on():
        try:
            out["refine"] = await refine_with_llm(who)
        except Exception as e:  # noqa: BLE001 - the rules' result stands
            traceback.print_exc()
            out["refine"] = {"error": str(e)[:200]}
    return out


async def tick() -> list[dict]:
    """One pass of the scheduler: every source that is due is read, in turn."""
    out = []
    for s in due_sources():
        out.append({"source": s["id"], **await read_source(s["id"], "scheduler")})
    return out


async def _loop() -> None:
    while True:
        try:
            for _t in db.each_tenant("servicedesk"):    # P17: every tenant with the Service desk on
                await tick()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - keep polling
            traceback.print_exc()
        await asyncio.sleep(POLL_S)


def ensure_scheduler() -> bool:
    """Start the polling task on the running loop once; safe to call on every request. True when it started now."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return False
    key = id(loop)
    t = _tasks.get(key)
    if t is not None and not t.done():
        return False
    _tasks[key] = loop.create_task(_loop())
    return True


def stop_scheduler() -> None:
    for t in _tasks.values():
        t.cancel()
    _tasks.clear()


# ------------------------------------------------------------------ API

class SourceIn(BaseModel):
    kind: str | None = None
    name: str | None = None
    base_url: str | None = None
    account: str | None = None
    projects: list[str] | str | None = None
    poll_min: int | None = None
    token: str | None = None


class Pause(BaseModel):
    paused: bool = True


class Person(BaseModel):
    to: str
    note: str | None = None


class Work(BaseModel):
    target: str
    project: str | None = None
    note: str | None = None


def _u() -> dict:
    u = auth.current.get()
    if not u:
        raise HTTPException(401, "Sign in.")
    return u


def _dev() -> dict:
    u = _u()
    if not auth.is_dev(u):
        raise HTTPException(403, "Only BI Devs / Analysts and admins act on the service desk.")
    return u


@router.get("/api/servicedesk")
async def api_screen():
    u = _u()
    ensure_scheduler()
    return {"summary": summary(), "groups": groups(), "sources": sources(), "kinds": KINDS, "targets": TARGETS, "quality": quality(),
            "work": db.q("SELECT * FROM itsm_work ORDER BY created DESC LIMIT 20"), "can_edit": auth.is_dev(u), "llm": llm_on(),
            "status_labels": STATUS_LABEL, "near_sla_h": triage.NEAR_SLA_H,
            # consolidation: what each source may do, the writes other modules asked for, the ticket drafts waiting for a source
            "scopes": SCOPES, "options": OPTIONS, "writes": writes(), "drafts": drafts(), "ticket_target": (ticket_target() or {}).get("name")}


class ScopeIn(BaseModel):
    scope: str
    options: dict | None = None


class RaiseIn(BaseModel):
    origin: str
    source: str | None = None


@router.put("/api/servicedesk/sources/{sid}/scope")
def api_scope(sid: str, body: ScopeIn):
    """What Relay may write to this source (read-only by default) and how it raises tickets: an admin or the person
    who added the source decides; every write still waits for a per-change approval."""
    u = _dev()
    return set_scope(sid, body.scope, body.options, u)


@router.get("/api/servicedesk/writes")
def api_writes():
    _u()
    return {"items": writes(100), "drafts": drafts()}


@router.post("/api/servicedesk/drafts/raise")
def api_raise_draft(body: RaiseIn):
    u = _dev()
    try:
        return raise_draft(body.origin, body.source, u["id"])
    except WriteRefused as e:
        raise HTTPException(409, str(e))


@router.get("/api/servicedesk/summary")
async def api_summary():
    _u()
    ensure_scheduler()
    return summary()


@router.get("/api/servicedesk/quality")
def api_quality():
    _u()
    return {"quality": quality()}


@router.get("/api/servicedesk/sources")
def api_sources():
    _u()
    return {"sources": sources(), "kinds": KINDS}


@router.post("/api/servicedesk/sources")
def api_add_source(body: SourceIn):
    u = _dev()
    return save_source(body.model_dump(), u["id"])


@router.put("/api/servicedesk/sources/{sid}")
def api_edit_source(sid: str, body: SourceIn):
    u = _dev()
    return save_source(body.model_dump(), u["id"], sid)


@router.delete("/api/servicedesk/sources/{sid}")
def api_remove_source(sid: str):
    u = _dev()
    remove_source(sid, u["id"])
    return {"ok": True}


@router.post("/api/servicedesk/sources/{sid}/test")
def api_test_source(sid: str):
    u = _dev()
    return test_source(sid, u["id"])


@router.post("/api/servicedesk/sources/{sid}/pause")
def api_pause_source(sid: str, body: Pause | None = None):
    u = _dev()
    return pause_source(sid, body.paused if body else True, u["id"])


@router.post("/api/servicedesk/sources/{sid}/read")
async def api_read_source(sid: str):
    u = _dev()
    _src(sid)
    ensure_scheduler()
    return await read_source(sid, u["id"])


@router.get("/api/servicedesk/groups/{gid}")
def api_group(gid: str):
    _u()
    return public_group(_grp(gid), True)


@router.post("/api/servicedesk/groups/{gid}/accept")
def api_accept(gid: str):
    u = _dev()
    try:
        return accept(gid, u["id"])
    except ItsmError as e:
        raise HTTPException(409, str(e))


@router.post("/api/servicedesk/groups/{gid}/checkpoint")
def api_open_checkpoint(gid: str):
    """Ask a person (the queue) rather than deciding now: opens the group's checkpoint without accepting it."""
    u = _dev()
    g = _grp(gid)
    if g.get("checkpoint_id") and (checkpoints.get(g["checkpoint_id"]) or {}).get("status") == "open":
        return {"checkpoint": checkpoints.get(g["checkpoint_id"]), "group": public_group(g, True)}
    if not group_writable(gid, g["members"]):
        raise HTTPException(409, "Nothing can be written back: the tickets' sources are read-only (or paused).")
    c = open_checkpoint(gid, agent="Triage", who=u["id"])
    return {"checkpoint": c, "group": public_group(_grp(gid), True)}


@router.post("/api/servicedesk/groups/{gid}/person")
def api_person(gid: str, body: Person):
    u = _dev()
    return send_to_person(gid, body.to, body.note, u["id"])


@router.post("/api/servicedesk/groups/{gid}/work")
async def api_work(gid: str, body: Work):
    u = _dev()
    return await hand_off(gid, body.target, u["id"], body.project, body.note)
