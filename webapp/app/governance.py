"""D2D Relay: data governance (item 22): what is kept, for how long, and how it is erased or handed back.

Erasure
  - a dashboard (DELETE /api/projects/<id>; its owner or an organisation owner): its folder (uploads, extracts,
    plan, versions, prototypes, the Power BI file and the activity log), its index rows, shares and queued jobs, the
    Ask Relay conversations about that dashboard, notifications pointing at it, cached answers that used it, and the
    AI engine's own transcripts of its runs;
  - one Ask Relay conversation (DELETE /api/askd/threads/<id>; the person who asked);
  - a whole organisation (PASDACS, on the owner's written request: `python -m app.governance erase-org`, see
    erase_org): its database schema, folders, secrets, visual library and AI transcripts. The credit history and
    its online payments (item 23) stay for the accounts, without names, email addresses or messages.
  The credit history of a dashboard (credits are money) and the audit trail stay; nightly backups (ops.py) keep
  the last 14 nights, so an erased dashboard leaves them two weeks later.

Access
  - GET /api/me/data: what D2D Relay holds about the person who asks, as a JSON file ("Download my data").

Retention (nightly, after the backup: ops.nightly -> sweep)
  - the audit trail, sign-in records and sign-in codes: LOG_DAYS (365). India's DPDP Rules 2025, rule 8(3): personal
    data, traffic data and logs of processing are kept at least a year, then erased (CERT-In asks 180 days of logs);
  - Ask Relay's answer cache: CACHE_DAYS (7);
  - online checkouts never paid (payments.py): LOG_DAYS; paid ones are accounting records and stay (eight years);
  - database dumps and exports made by hand (relay-ctl db-dump / export, kept beside the nightly backups): DUMP_DAYS (30);
  - the AI engine's transcripts: of folders that no longer exist, and any older than AI_DAYS (7; Claude Code also
    drops them after cleanupPeriodDays when a run starts: agent/managed-settings.json). Ask Relay's go as soon as it
    has answered; it keeps no auto-memory (autoMemoryEnabled false).
"""
from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from . import auth, db, instances, store

LOG_DAYS = int(os.environ.get("D2D_LOG_KEEP_DAYS", "365"))
CACHE_DAYS = int(os.environ.get("D2D_ASKD_CACHE_DAYS", "7"))
DUMP_DAYS = int(os.environ.get("D2D_DUMP_KEEP_DAYS", "30"))
AI_DAYS = 7                     # the AI engine's transcripts: cleanupPeriodDays in agent/managed-settings.json
BACKUPS = Path(os.environ.get("D2D_BACKUPS", "/data/backups"))
LIBRARY = Path(os.environ.get("GENBI_LIBRARY", "/opt/genbi/library"))
DUMPS = ("relay-db-*.dump", "pre-*.dump", "relay-export-*.tar.gz")       # made by hand (relay-ctl), never by the app

router = APIRouter()


def _u() -> dict:
    u = auth.current.get()
    if not u:
        raise HTTPException(401, "Sign in to D2D Relay.")
    return u


# ---------------------------------------------------------------- the AI engine's own records

def forget_ai(workdir: str | None = None, sessions: list[str] | None = None, missing: bool = False,
              older_than_days: float | None = None) -> int:
    """Ask the AI engine to delete Claude Code's transcripts (and the tool output saved with them) of the runs in one
    folder (workdir as POST /runs takes it), only some of its sessions, or (missing) of every folder that no longer
    exists. Returns how many records went, -1 when the engine could not be reached (its own clean-up still runs)."""
    try:
        r = httpx.post(f"{instances.SHARED_AGENT}/forget", json={"workdir": workdir, "sessions": sessions, "missing": missing,
                                                                  "older_than_days": older_than_days}, timeout=60)
        r.raise_for_status()
        return int(r.json().get("removed", 0))
    except (httpx.HTTPError, ValueError) as e:
        print(f"[governance] the AI engine could not forget {workdir or 'the folders that are gone'}: {e}", flush=True)
        return -1


# ---------------------------------------------------------------- erasing a dashboard, a conversation

def _thread_rows(tid: str) -> None:
    db.run("DELETE FROM askd_feedback WHERE message_id IN (SELECT id FROM askd_messages WHERE thread_id = ?)", (tid,))
    db.run("DELETE FROM askd_messages WHERE thread_id = ?", (tid,))
    db.run("DELETE FROM askd_threads WHERE id = ?", (tid,))


def _cache_keys(tid: str) -> list[str]:
    keys = []
    for m in db.q("SELECT body FROM askd_messages WHERE thread_id = ? AND role <> 'user'", (tid,)):
        try:
            k = json.loads(m["body"]).get("cache_key")
        except (ValueError, AttributeError):
            k = None
        if k:
            keys.append(k)
    return keys


def delete_thread(tid: str, u: dict) -> dict:
    t = db.one("SELECT id, title FROM askd_threads WHERE id = ? AND user_id = ?", (tid, u["id"]))
    if not t:
        raise HTTPException(404, "Unknown conversation")
    keys = _cache_keys(tid)
    with db.transaction():
        for k in keys:
            db.run("DELETE FROM askd_cache WHERE key = ?", (k,))
        _thread_rows(tid)
    db.audit("askd.thread_deleted", tid, {"answers_uncached": len(keys)}, u["id"])
    return {"deleted": tid}


def delete_project(pid: str, u: dict) -> dict:
    from . import worker                         # late import: worker imports a great deal
    p = db.project(pid)
    try:
        st = store.load(pid)
    except (KeyError, FileNotFoundError, ValueError):
        raise HTTPException(404, "Project not found")
    level, _ = auth.access(u, p)
    if level != "owner":
        raise HTTPException(403, "Only the dashboard's owner or an owner of the organisation can delete it.")
    if st.get("status") in worker.RUNNING or worker.current.get("pid") == pid \
            or db.one("SELECT 1 AS x FROM jobs WHERE pid = ? AND state = 'running'", (pid,)):
        raise HTTPException(409, "Relay is working on this dashboard. Stop the run first, then delete it.")
    name, rel, d = st.get("name") or pid, store.rel(pid), store.root() / pid
    threads = []
    for t in db.q("SELECT id, scope FROM askd_threads"):
        try:
            scope = json.loads(t["scope"] or "{}")
        except ValueError:
            scope = {}
        if isinstance(scope, dict) and scope.get("project") == pid:
            threads.append(t["id"])
    with db.transaction():
        for tid in threads:
            _thread_rows(tid)
        db.run("DELETE FROM askd_cache WHERE body LIKE ?", (f'%"{pid}"%',))      # cached answers that used it
        db.run("DELETE FROM shares WHERE project_id = ?", (pid,))
        db.run("DELETE FROM jobs WHERE pid = ? AND state <> 'running'", (pid,))
        db.run("DELETE FROM notifications WHERE link LIKE ?", (f"%/p/{pid}%",))
        db.run("DELETE FROM projects WHERE id = ?", (pid,))
    # out of sight at once (dot folders are never listed or backed up), then gone
    gone = d.with_name(f".deleted-{pid}-{int(time.time())}")
    files = sum(1 for f in d.rglob("*") if f.is_file()) if d.is_dir() else 0
    if d.is_dir():
        d.rename(gone)
        shutil.rmtree(gone, ignore_errors=True)
    ai = forget_ai(rel)
    db.audit("project.deleted", pid, {"name": name, "files": files, "conversations": len(threads), "ai_records": ai}, u["id"])
    return {"deleted": pid, "name": name, "files": files, "conversations": len(threads)}


@router.delete("/api/projects/{pid}")
def api_delete_project(pid: str):
    return delete_project(pid, _u())


@router.delete("/api/askd/threads/{tid}")
def api_delete_thread(tid: str):
    return delete_thread(tid, _u())


# ---------------------------------------------------------------- "Download my data"

def _body(raw: str) -> dict:
    try:
        b = json.loads(raw)
    except ValueError:
        return {}
    return b if isinstance(b, dict) else {}


def my_data(u: dict) -> dict:
    uid, since = u["id"], time.time() - LOG_DAYS * 86400
    me = db.one("SELECT id, email, name, org_role, active, created FROM users WHERE id = ?", (uid,)) or {}
    org = db.one("SELECT name, domain, owner_id, created FROM relay.tn_orgs WHERE tenant_id = ?", (db.tenant(),))
    teams = db.q("SELECT t.name, m.role FROM memberships m JOIN teams t ON t.id = m.team_id WHERE m.user_id = ?", (uid,))
    owned = []
    for p in db.q("SELECT id, created, visibility FROM projects WHERE owner_id = ? ORDER BY created", (uid,)):
        try:
            st = store.load(p["id"])
        except (KeyError, FileNotFoundError, ValueError):
            continue
        owned.append({"id": p["id"], "name": st.get("name"), "created": p["created"], "visibility": p["visibility"],
                      "status": st.get("status"), "versions": len(st.get("versions") or []),
                      "uploaded_files": [f.get("name") for f in st.get("files") or []]})
    convs = []
    for t in db.q("SELECT id, title, scope, created, updated FROM askd_threads WHERE user_id = ? ORDER BY created", (uid,)):
        msgs = []
        for m in db.q("SELECT role, body, created FROM askd_messages WHERE thread_id = ? ORDER BY created", (t["id"],)):
            b = _body(m["body"])
            msgs.append({"role": m["role"], "when": m["created"],
                         "text": b.get("text") if m["role"] == "user" else (b.get("summary") or b.get("headline") or b.get("text"))})
        convs.append({"id": t["id"], "title": t["title"], "about": _body(t["scope"]).get("kind"), "created": t["created"],
                      "updated": t["updated"], "messages": msgs})
    audit = db.q("SELECT ts, action, object, detail FROM audit WHERE who = ? AND ts >= ? ORDER BY ts DESC LIMIT 5000", (uid, since))
    for a in audit:
        a["detail"] = _body(a["detail"] or "{}")
    return {
        "about": "What D2D Relay (PASDACS) holds about you. Your dashboards' own files are downloaded from each dashboard; "
                 "write to the address in the privacy notice (/privacy.html) to correct or erase anything here.",
        "made": time.time(),
        "you": {**me, "teams": teams},
        "organisation": {k: org[k] for k in ("name", "domain", "created")} | {"you_are_main_owner": org["owner_id"] == uid} if org else None,
        "signed_in_now": db.q("SELECT created, expires, last_seen, ip, agent FROM sessions WHERE user_id = ? ORDER BY created DESC", (uid,)),
        "dashboards_you_own": owned,
        "ask_relay_conversations": convs,
        "credit_requests": db.q("SELECT created, credits, message, status, decided, granted FROM relay.tn_credit_requests "
                                "WHERE tenant_id = ? AND user_id = ? ORDER BY created", (db.tenant(), uid)),
        "credits_used": db.q("SELECT ts, kind, delta, what, project_name FROM relay.tn_credits WHERE tenant_id = ? AND user_id = ? "
                             "ORDER BY ts", (db.tenant(), uid)),
        "payments": db.q("SELECT id AS receipt, created, paid, status, credits, amount AS amount_paise, currency, method, payment_id, "
                         "refunded AS refunded_paise FROM relay.tn_payments WHERE tenant_id = ? AND user_id = ? ORDER BY created",
                         (db.tenant(), uid)),
        f"activity_last_{LOG_DAYS}_days": audit,
    }


@router.get("/api/me/data")
def api_my_data():
    u = _u()
    out = my_data(u)
    db.audit("privacy.export", u["id"], None, u["id"])
    return JSONResponse(json.loads(json.dumps(out, default=str)), headers={
        "Content-Disposition": 'attachment; filename="d2d-relay-my-data.json"', "Cache-Control": "no-store"})


# ---------------------------------------------------------------- erasing an organisation (PASDACS, by hand)

def erase_org(tid: str, who: str) -> dict:
    """Everything an organisation put in D2D Relay, gone: run by PASDACS on the owner's written request, in the web
    container (it holds the folders and the AI engine; the admin portal's container has neither):
        docker exec -u relay -w /srv d2d-relay-web /opt/relay/bin/launch web python -m app.governance erase-org <id> "<name>"
    """
    from . import tenancy
    if tid == db.PLATFORM:
        raise HTTPException(400, "The platform's own workspace cannot be erased.")
    with db.use(db.PLATFORM):
        t = db.one("SELECT * FROM relay.tn_tenants WHERE id = ?", (tid,))
        org = db.one("SELECT * FROM relay.tn_orgs WHERE tenant_id = ?", (tid,))
    if not t or not org:
        raise HTTPException(404, "No such organisation.")
    with db.use(tid):
        if db.one("SELECT 1 AS x FROM jobs WHERE state IN ('running', 'queued')"):
            raise HTTPException(409, f"{org['name']} has a dashboard run in progress or waiting. Try again when it is done.")
        people = db.q("SELECT id FROM users")
        folders = [store.root(), store._library(LIBRARY), db.STATE / "tenants" / tid]     # noqa: SLF001
        projects = len(db.q("SELECT id FROM projects"))
    with db.use(db.PLATFORM):                       # closed first: nobody signs in or works in it from here on
        db.run("UPDATE relay.tn_tenants SET status = 'closed', updated = ?, updated_by = ?, notes = ? WHERE id = ?",
               (time.time(), who, f"Erased on request ({time.strftime('%Y-%m-%d')})", tid))
    tenancy._invalidate()                                           # noqa: SLF001
    db.drop_tenant(tid)                             # a failure from here on: run it again, the organisation is still listed
    for f in folders:
        if f.is_dir() and f != store.BASE and f != LIBRARY:
            shutil.rmtree(f, ignore_errors=True)
    with db.use(db.PLATFORM):
        with db.transaction():
            for sql in ("DELETE FROM relay.tn_orgs WHERE tenant_id = ?", "DELETE FROM relay.tn_accounts WHERE home_tenant = ?",
                        "DELETE FROM relay.tn_access WHERE tenant_id = ?", "DELETE FROM relay.tn_acting WHERE tenant_id = ?",
                        "DELETE FROM relay.tn_setup WHERE tenant_id = ?", "DELETE FROM relay.tn_modules WHERE tenant_id = ?",
                        "DELETE FROM relay.tn_handovers WHERE tenant_id = ?"):
                db.run(sql, (tid,))
            # the accounts keep what was charged and granted, without the people
            db.run("UPDATE relay.tn_credits SET user_id = NULL, user_name = NULL, project_name = NULL, note = NULL WHERE tenant_id = ?", (tid,))
            db.run("UPDATE relay.tn_credit_requests SET user_id = NULL, user_name = NULL, email = NULL, message = NULL, "
                   "decided_name = NULL, note = NULL WHERE tenant_id = ?", (tid,))
            # payments are accounting records (kept eight years): the organisation's name and the amounts stay, the people go
            db.run("UPDATE relay.tn_payments SET user_id = NULL, user_name = NULL, email = NULL WHERE tenant_id = ?", (tid,))
    tenancy._invalidate()                                           # noqa: SLF001
    ai = forget_ai(missing=True)
    # the control plane's audit only (tenancy.ctl_audit also writes to the organisation's own log, which is gone)
    db.run("INSERT INTO relay.tn_audit (ts, who, who_tenant, tenant_id, action, object, detail) VALUES (?, ?, ?, ?, ?, ?, ?)",
           (time.time(), who, db.PLATFORM, tid, "d2d.org_erased", tid, json.dumps({"name": org["name"], "domain": org["domain"],
            "people": len(people), "dashboards": projects, "ai_records": ai})))
    return {"erased": tid, "name": org["name"], "people": len(people), "dashboards": projects}


# ---------------------------------------------------------------- retention (nightly)

def sweep() -> dict:
    now = time.time()
    logs, cache = now - LOG_DAYS * 86400, now - CACHE_DAYS * 86400
    out = {"audit": 0, "signin_codes": 0, "answer_cache": 0, "dumps": 0, "unpaid_checkouts": 0}
    for _t in db.each_tenant():
        out["audit"] += db.run("DELETE FROM audit WHERE ts < ?", (logs,))
        out["answer_cache"] += db.run("DELETE FROM askd_cache WHERE created < ?", (cache,))
        out["signin_codes"] += db.run("DELETE FROM otp_codes WHERE created < ?", (logs,))
        out["signin_codes"] += db.run("DELETE FROM otp_signup WHERE created < ?", (logs,))
    with db.use(db.PLATFORM):
        out["audit"] += db.run("DELETE FROM relay.tn_audit WHERE ts < ?", (logs,))
        # online checkouts never paid (item 23); paid ones are accounting records and stay
        out["unpaid_checkouts"] += db.run("DELETE FROM relay.tn_payments WHERE status IN ('created', 'failed') AND created < ?", (logs,))
    for pattern in DUMPS:
        for f in BACKUPS.glob(pattern):
            try:
                if f.is_file() and now - f.stat().st_mtime > DUMP_DAYS * 86400:
                    f.unlink()
                    out["dumps"] += 1
            except OSError:
                pass
    out["ai_records"] = forget_ai(missing=True, older_than_days=AI_DAYS)
    with db.use(db.PLATFORM):
        db.audit("retention.sweep", None, {**out, "log_days": LOG_DAYS, "cache_days": CACHE_DAYS, "dump_days": DUMP_DAYS}, "system")
    return out


def _cli(argv: list[str]) -> int:
    """python -m app.governance erase-org <organisation id> "<its exact name>"   |   python -m app.governance sweep"""
    db.init()
    if argv[:1] == ["sweep"]:
        print(json.dumps(sweep(), indent=1))
        return 0
    if len(argv) != 3 or argv[0] != "erase-org":
        print(_cli.__doc__)
        return 2
    with db.use(db.PLATFORM):
        org = db.one("SELECT tenant_id, name, domain FROM relay.tn_orgs WHERE tenant_id = ?", (argv[1],))
    if not org:
        print(f"No organisation {argv[1]!r}. Organisations: " + ", ".join(
            f"{o['tenant_id']} ({o['name']}, @{o['domain']})" for o in db.q("SELECT tenant_id, name, domain FROM relay.tn_orgs")))
        return 1
    if argv[2].strip() != org["name"].strip():
        print(f"The name does not match: to erase {org['tenant_id']}, give its name exactly: {org['name']!r}")
        return 1
    print(json.dumps(erase_org(org["tenant_id"], "pasdacs-cli"), indent=1))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(_cli(sys.argv[1:]))
