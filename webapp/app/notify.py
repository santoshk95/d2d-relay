"""In-app notifications (phase 7): build finished, shared with you, alert fired, schedule paused, quota warnings.

Each person sees only their own. Old read notifications are trimmed so the table stays small."""
import secrets
import time

from fastapi import APIRouter, HTTPException

from . import auth, db

router = APIRouter()

KINDS = {"build", "share", "alert", "schedule", "report", "quota", "review", "ops", "platform"}
KEEP_DAYS = 60
# Item 82 (the user, 2026-11-19: "only org or their task or their platform relation notification must be here not
# all"): notices about the platform itself (another organisation's request, an organisation deleted, the job runner's and
# the PC helpers' health, a self-healing hold) are PASDACS's console's. The admin portal shows them and nothing else; the
# public site never does: there a person sees their organisation's news, their own work and what PASDACS answered them.
# A platform notice is kind "platform", or (older ones) one that links into the admin portal.
PLATFORM_LINKS = ("#/requests", "#/orgs", "#/admin/", "#/payments")
PLATFORM = "(kind = 'platform' OR " + " OR ".join(f"COALESCE(link, '') LIKE '{p}%'" for p in PLATFORM_LINKS) + ")"


def _site() -> str:
    """The notices this site shows: the admin portal's are the platform's, the public site's all the others."""
    from . import portal
    return PLATFORM if portal.ADMIN else f"NOT {PLATFORM}"


def add(user_id: str | None, kind: str, title: str, body: str = "", link: str | None = None) -> None:
    if not user_id or not db.one("SELECT 1 FROM users WHERE id = ? AND active = 1", (user_id,)):
        return
    db.run("INSERT INTO notifications (id, user_id, kind, title, body, link, created) VALUES (?, ?, ?, ?, ?, ?, ?)",
           ("n-" + secrets.token_hex(6), user_id, kind if kind in KINDS else "build", title[:200], (body or "")[:1000],
            link, time.time()))


def add_many(user_ids, kind: str, title: str, body: str = "", link: str | None = None, skip: str | None = None) -> None:
    for uid in dict.fromkeys(u for u in user_ids if u and u != skip):
        add(uid, kind, title, body, link)


def team_members(team_id: str) -> list[str]:
    return [r["user_id"] for r in db.q("SELECT user_id FROM memberships WHERE team_id = ?", (team_id,))]


def mine(uid: str, limit: int = 50) -> dict:
    site = _site()
    rows = db.q(f"SELECT * FROM notifications WHERE user_id = ? AND {site} ORDER BY created DESC LIMIT ?", (uid, limit))
    unread = db.one(f"SELECT COUNT(*) AS n FROM notifications WHERE user_id = ? AND read IS NULL AND {site}", (uid,))["n"]
    return {"items": rows, "unread": unread}


def trim() -> None:
    db.run("DELETE FROM notifications WHERE read IS NOT NULL AND created < ?", (time.time() - KEEP_DAYS * 86400,))


# ---------------------------------------------------------------- endpoints (each person's own)

@router.get("/api/notifications")
def my_notifications():
    return mine(auth.current.get()["id"])


@router.post("/api/notifications/read")
def mark_all_read():
    db.run(f"UPDATE notifications SET read = ? WHERE user_id = ? AND read IS NULL AND {_site()}", (time.time(), auth.current.get()["id"]))
    return mine(auth.current.get()["id"])


@router.post("/api/notifications/{nid}/read")
def mark_read(nid: str):
    if not db.run("UPDATE notifications SET read = COALESCE(read, ?) WHERE id = ? AND user_id = ?",
                  (time.time(), nid, auth.current.get()["id"])):
        raise HTTPException(404, "Unknown notification")
    return mine(auth.current.get()["id"])
