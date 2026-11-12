"""Insight pages (platform plan, phase 6: "idea -> insights"): a page made from Ask Relay answers or a dashboard's
prototype, private to its owner until shared - with people, a team or the organisation, like a dashboard (the same
rules: auth.access). A page is lighter than a dashboard: no review gates, no Power BI project.

Blocks: {"type": "text", "text"} - {"type": "answer", question, headline, summary, actions, data, chart, where,
certified} (a copy of an Ask Relay answer at the time it was added) - {"type": "prototype", "project", "version"}.
"""
import html as H
import json
import secrets
import time

from . import askd, auth, db, store


class PageError(Exception):
    pass


def _row(page_id: str) -> dict:
    p = db.one("SELECT * FROM pages WHERE id = ?", (page_id,))
    if not p:
        raise PageError("Unknown page")
    p["body"] = json.loads(p["body"])
    return p


def _shares(page_id: str) -> list[dict]:
    return db.q("SELECT * FROM page_shares WHERE page_id = ? AND (expires IS NULL OR expires > ?)", (page_id, time.time()))


def access(u: dict, p: dict) -> str | None:
    level, _ = auth.access(u, p, _shares(p["id"]))
    return level


def _direct(page_id: str) -> set[str]:
    """People given this page directly or through a team (told when it is shared with them)."""
    p, shares, out = _row(page_id), _shares(page_id), set()
    for r in db.q("SELECT id FROM users WHERE active = 1"):
        u = db.user(r["id"])
        level, how = auth.access(u, p, shares) if u else (None, "")
        if level and how in ("user", "team", "owner"):
            out.add(r["id"])
    return out


def get(page_id: str, u: dict, need: str = "view") -> dict:
    p = _row(page_id)
    level = access(u, p)
    if level is None or (need == "edit" and level not in ("owner", "edit")) or (need == "share" and level != "owner"):
        raise PageError("Unknown page" if level is None else "You can view this page but not change it.")
    owner = db.one("SELECT name FROM users WHERE id = ?", (p["owner_id"],))
    return {**p, "access": level, "owner": owner["name"] if owner else p["owner_id"],
            "shares": db.q("SELECT principal_type, principal_id, permission, expires FROM page_shares WHERE page_id = ?", (page_id,))
            if level == "owner" else []}


def mine(u: dict) -> list[dict]:
    out = []
    for p in db.q("SELECT * FROM pages ORDER BY updated DESC"):
        level = access(u, p)
        if level:
            owner = db.one("SELECT name FROM users WHERE id = ?", (p["owner_id"],))
            out.append({k: p[k] for k in ("id", "title", "visibility", "updated", "source", "owner_id")} |
                       {"access": level, "owner": owner["name"] if owner else "", "blocks": len(json.loads(p["body"]))})
    return out


def _answer_block(body: dict, question: str) -> dict:
    v = body.get("validation") or {}
    return {"type": "answer", "question": question, "headline": (body.get("result") or {}).get("headline"),
            "chart": (body.get("result") or {}).get("chart"), "summary": body.get("summary"), "actions": body.get("actions"),
            "data": body.get("data"), "where": v.get("where"), "certified": v.get("certified"),
            "certified_metrics": v.get("certified_metrics"), "added": time.time()}


def create(u: dict, title: str, source: dict) -> dict:
    """source: {"kind": "askd_thread", "thread"} | {"kind": "askd_message", "message"} | {"kind": "prototype", "project",
    "version"} | {"kind": "blank"}."""
    blocks, team = [], next((t["id"] for t in u.get("teams", [])), db.DEFAULT_TEAM)
    kind = source.get("kind", "blank")
    if kind == "askd_thread":
        t = askd.thread(str(source.get("thread")), u["id"])
        q = None
        for m in t["messages"]:
            if m["role"] == "user":
                q = m["body"]["text"]
            else:
                blocks.append(_answer_block(m["body"], q or ""))
        title = title or t["title"]
    elif kind == "askd_message":
        body, meta = askd.message(str(source.get("message")), u["id"])
        blocks.append(_answer_block(body, meta["question"]))
        title = title or meta["question"]
    elif kind == "prototype":
        pid = str(source.get("project"))
        if not auth.can_project(u, "view", db.project(pid)):
            raise PageError("You cannot open that dashboard.")
        st = store.load(pid)
        v = int(source.get("version") or st.get("approved") or (st["versions"][-1]["v"] if st.get("versions") else 0))
        if not v:
            raise PageError("That dashboard has no prototype yet.")
        blocks.append({"type": "prototype", "project": pid, "version": v, "name": st.get("name")})
        title = title or f"{st.get('name')} - v{v}"
    if not blocks and kind != "blank":
        raise PageError("Nothing to put on the page.")
    pid_ = "pg-" + secrets.token_hex(6)
    db.run("INSERT INTO pages (id, owner_id, team_id, title, visibility, body, source, created, updated) VALUES (?, ?, ?, ?, 'private', ?, ?, ?, ?)",
           (pid_, u["id"], team, (title or "Untitled page")[:200], json.dumps(blocks, default=str), json.dumps(source), time.time(), time.time()))
    db.audit("page.create", pid_, {"source": kind, "blocks": len(blocks)}, u["id"])
    return get(pid_, u)


def add(page_id: str, u: dict, source: dict) -> dict:
    p = get(page_id, u, "edit")
    tmp = create(u, "tmp", source)
    db.run("DELETE FROM pages WHERE id = ?", (tmp["id"],))
    db.run("UPDATE pages SET body = ?, updated = ? WHERE id = ?", (json.dumps(p["body"] + tmp["body"], default=str), time.time(), page_id))
    return get(page_id, u)


def save(page_id: str, u: dict, title: str | None, blocks: list[dict] | None) -> dict:
    p = get(page_id, u, "edit")
    if blocks is not None:
        known = {json.dumps(b, sort_keys=True, default=str) for b in p["body"]}
        clean = []
        for b in blocks:                                      # text blocks may be written; other blocks only kept or dropped
            if b.get("type") == "text":
                clean.append({"type": "text", "text": str(b.get("text", ""))[:20000]})
            elif json.dumps(b, sort_keys=True, default=str) in known:
                clean.append(b)
        p["body"] = clean
    db.run("UPDATE pages SET title = ?, body = ?, updated = ? WHERE id = ?",
           ((title or p["title"])[:200], json.dumps(p["body"], default=str), time.time(), page_id))
    db.audit("page.save", page_id, {"blocks": len(p["body"])}, u["id"])
    return get(page_id, u)


def remove(page_id: str, u: dict) -> None:
    get(page_id, u, "share")
    db.run("DELETE FROM page_shares WHERE page_id = ?", (page_id,))
    db.run("DELETE FROM pages WHERE id = ?", (page_id,))
    db.audit("page.remove", page_id, None, u["id"])


def share(page_id: str, u: dict, visibility: str, team_id: str | None, grants: list[dict]) -> dict:
    p = get(page_id, u, "share")
    if visibility not in ("private", "team", "org"):
        raise PageError("private, team or org")
    team = team_id or p["team_id"]
    if visibility == "team" and not db.one("SELECT 1 FROM teams WHERE id = ?", (team,)):
        raise PageError("Pick the team.")
    before = _direct(page_id)
    db.run("UPDATE pages SET visibility = ?, team_id = ?, updated = ? WHERE id = ?", (visibility, team, time.time(), page_id))
    db.run("DELETE FROM page_shares WHERE page_id = ?", (page_id,))
    for g in grants:
        if g.get("principal_type") not in ("user", "team", "org") or g.get("permission") not in ("view", "edit"):
            raise PageError("Each share: a person, team or the organisation, view or edit.")
        db.run("INSERT OR REPLACE INTO page_shares (page_id, principal_type, principal_id, permission, expires, created, created_by) VALUES (?, ?, ?, ?, ?, ?, ?)",
               (page_id, g["principal_type"], "*" if g["principal_type"] == "org" else g["principal_id"], g["permission"], g.get("expires"), time.time(), u["id"]))
    db.audit("page.share", page_id, {"visibility": visibility, "team": team, "shares": len(grants)}, u["id"])
    from . import notify
    notify.add_many(sorted(_direct(page_id) - before), "share", f"{u['name']} shared a page with you", p["title"], f"#/pages/{page_id}", skip=u["id"])
    return get(page_id, u)


def html(p: dict) -> str:
    """The page as one self-contained document (for PDF / PNG export)."""
    parts = []
    for b in p["body"]:
        if b["type"] == "text":
            parts.append("".join(f"<p>{H.escape(line)}</p>" for line in b["text"].split("\n") if line.strip()))
        elif b["type"] == "answer":
            parts.append(askd.snapshot_html({"result": {"headline": b.get("headline"), "chart": b.get("chart")}, "summary": b.get("summary"),
                                              "data": b.get("data"), "validation": {"certified": b.get("certified"), "where": b.get("where")}},
                                             b.get("question") or "").split('<div class="card">', 1)[1].rsplit("</div>", 1)[0])
            if b.get("actions"):
                parts.append("<ul>" + "".join(f"<li>{H.escape(a)}</li>" for a in b["actions"]) + "</ul>")
        elif b["type"] == "prototype":
            parts.append(f'<p class="q">Dashboard: {H.escape(b.get("name") or b["project"])} v{b["version"]} - open it in D2D to explore.</p>')
    return f"""<!doctype html><meta charset="utf-8"><title>{H.escape(p['title'])}</title><style>
body{{margin:0;padding:32px;font:14px/1.55 'Segoe UI',Arial,sans-serif;color:#111827;background:#fff;max-width:920px}}
h1{{font-size:28px;margin:0 0 4px}}.meta{{color:#5F655F;font-size:12px;margin-bottom:20px}}
section{{border-top:1px solid #E2E5E9;padding-top:16px;margin-top:16px}}.q{{color:#5F655F}}.h{{font-size:22px;font-weight:700;margin:4px 0}}
.b{{display:inline-block;font-size:11px;font-weight:600;padding:2px 8px;border-radius:999px;background:#EAF3F0;color:#0E5A4A;margin-right:6px}}
table{{border-collapse:collapse;font-size:12px}}td,th{{border-bottom:1px solid #EEE;padding:3px 8px;text-align:left}}.f{{display:none}}</style>
<h1>{H.escape(p['title'])}</h1><div class="meta">D2D insight page - {H.escape(p.get('owner', ''))} - {time.strftime('%Y-%m-%d %H:%M', time.gmtime(p['updated']))} UTC</div>
{''.join(f'<section>{x}</section>' for x in parts)}"""
