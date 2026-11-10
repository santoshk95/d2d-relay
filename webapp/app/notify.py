"""In-app notifications (phase 7): build finished, shared with you, alert fired, schedule paused, quota warnings.

Each person sees only their own. Old read notifications are trimmed so the table stays small."""
import secrets
import time

from fastapi import APIRouter, HTTPException

from . import auth, db

router = APIRouter()

KINDS = {"build", "share", "alert", "schedule", "report", "quota", "review", "ops"}
KEEP_DAYS = 60


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
    rows = db.q("SELECT * FROM notifications WHERE user_id = ? ORDER BY created DESC LIMIT ?", (uid, limit))
    unread = db.one("SELECT COUNT(*) AS n FROM notifications WHERE user_id = ? AND read IS NULL", (uid,))["n"]
    return {"items": rows, "unread": unread}


def trim() -> None:
    db.run("DELETE FROM notifications WHERE read IS NOT NULL AND created < ?", (time.time() - KEEP_DAYS * 86400,))


# ---------------------------------------------------------------- endpoints (each person's own)

@router.get("/api/notifications")
def my_notifications():
    return mine(auth.current.get()["id"])


@router.post("/api/notifications/read")
def mark_all_read():
    db.run("UPDATE notifications SET read = ? WHERE user_id = ? AND read IS NULL", (time.time(), auth.current.get()["id"]))
    return mine(auth.current.get()["id"])


@router.post("/api/notifications/{nid}/read")
def mark_read(nid: str):
    if not db.run("UPDATE notifications SET read = COALESCE(read, ?) WHERE id = ? AND user_id = ?",
                  (time.time(), nid, auth.current.get()["id"])):
        raise HTTPException(404, "Unknown notification")
    return mine(auth.current.get()["id"])
