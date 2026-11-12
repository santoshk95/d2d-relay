"""Publishing (platform plan, phase 6): review before publish, GitHub per person, exports, sharing to channels.

Review: dev -> review -> published. The person asks a named reviewer (a BI Dev / Analyst, or an Admin) to review a
version; the reviewer approves or asks for changes, with comments. With the organisation's "review required" policy
on, publishing a version needs that version approved by someone other than the person who publishes it (off by
default, so single-user installations publish as before). No direct publish to the Power BI Service: publishing
produces the PBIP download, as decided.

GitHub: each person links their own GitHub account (OAuth app set up by an Admin); "Version to GitHub" commits the
published definition, PBIP folder and check reports to a repository and branch they choose, through the Git Data
API (blobs, tree, commit, ref) - no git binary, nothing shared.

Exports: PNG and PDF of a dashboard prototype or an insight page, drawn in the agent's headless browser.
Channels: each person's own Slack or Microsoft Teams incoming webhooks (encrypted); a post carries a title, a short
text and a link back to Relay (sharing stays inside the platform: the link needs a sign-in).
"""
import base64
import json
import os
import re
import secrets
import time
from pathlib import Path
from urllib.parse import urlencode, urlparse

import httpx

from . import auth, db, secrets_store, store

GITHUB_WEB = os.environ.get("D2D_GITHUB_WEB", "https://github.com").rstrip("/")
GITHUB_API = os.environ.get("D2D_GITHUB_API", "https://api.github.com").rstrip("/")
PUBLIC_URL = os.environ.get("D2D_PUBLIC_URL", "").rstrip("/")
WEBHOOK_HOSTS = tuple(h.strip() for h in os.environ.get(
    "D2D_WEBHOOK_HOSTS", "hooks.slack.com,.webhook.office.com,.logic.azure.com,.environment.api.powerplatform.com").split(",") if h.strip())
GITHUB_FILES_MAX = 400


class PublishError(Exception):
    pass


# ---------------------------------------------------------------- policy and reviews

def policy() -> dict:
    return {"review_required": False, **json.loads(db.meta("publish_policy") or "{}")}


def save_policy(review_required: bool, who: str | None) -> dict:
    db.set_meta("publish_policy", json.dumps({"review_required": bool(review_required)}))
    db.audit("publish.policy", None, {"review_required": bool(review_required)}, who)
    return policy()


def reviews(st: dict) -> list[dict]:
    return st.get("reviews") or []


def request_review(pid: str, version: int, reviewer_id: str, note: str, u: dict) -> dict:
    st = store.load(pid)
    if not any(v["v"] == version for v in st.get("versions") or []):
        raise PublishError("Unknown version")
    r = db.user(reviewer_id)
    if not r or not auth.is_dev(r):
        raise PublishError("The reviewer must be someone in your organisation who builds dashboards.")
    if reviewer_id == u["id"]:
        raise PublishError("Ask someone else to review.")
    p = db.project(pid)
    if not auth.can_project(r, "view", p):                # let the reviewer open it
        db.run("INSERT OR IGNORE INTO shares (project_id, principal_type, principal_id, permission, created, created_by) "
               "VALUES (?, 'user', ?, 'view', ?, ?)", (pid, reviewer_id, time.time(), u["id"]))
    for x in reviews(st):
        if x["v"] == version and x["status"] == "pending":
            x["status"] = "replaced"
    rid = "r-" + secrets.token_hex(4)
    st.setdefault("reviews", []).append({"id": rid, "v": version, "requested_by": u["id"], "reviewer": reviewer_id,
                                         "status": "pending", "requested": time.time(),
                                         "comments": [{"who": u["id"], "when": time.time(), "text": note.strip()[:2000]}] if note.strip() else []})
    store.save(st)
    store.log(pid, {"kind": "user", "text": f"Asked {r['name']} to review v{version}"})
    db.audit("review.request", pid, {"version": version, "reviewer": reviewer_id}, u["id"])
    from . import notify
    notify.add(reviewer_id, "review", f"{u['name']} asked you to review {st.get('name') or pid} v{version}", note.strip()[:300],
               f"#/p/{pid}")                        # D2D Relay: the Review card (Approve, Request changes) is on Overview
    return reviews(store.load(pid))[-1]


def decide_review(pid: str, rid: str, decision: str, comment: str, u: dict) -> dict:
    st = store.load(pid)
    r = next((x for x in reviews(st) if x["id"] == rid), None)
    if not r or r["status"] != "pending":
        raise PublishError("That review is not open.")
    if u["id"] != r["reviewer"] and not auth.is_admin(u):
        raise PublishError("Only the reviewer decides.")
    if u["id"] == r["requested_by"]:
        raise PublishError("The person who asked for the review cannot approve it.")
    if decision not in ("approve", "changes"):
        raise PublishError("approve or changes")
    r.update(status="approved" if decision == "approve" else "changes", decided=time.time(), decided_by=u["id"])
    if comment.strip():
        r["comments"].append({"who": u["id"], "when": time.time(), "text": comment.strip()[:2000]})
    store.save(st)
    store.log(pid, {"kind": "user", "text": f"Review of v{r['v']}: " + ("approved" if decision == "approve" else "changes requested")
                    + (f" - {comment.strip()[:200]}" if comment.strip() else "")})
    db.audit("review.approve" if decision == "approve" else "review.changes", pid, {"version": r["v"]}, u["id"])
    from . import notify                              # D2D Relay: the person who asked hears the answer
    notify.add(r["requested_by"], "review", f"{u['name']} " + ("approved" if decision == "approve" else "asked for changes to")
               + f" {st.get('name') or pid} v{r['v']}", comment.strip()[:300], f"#/p/{pid}")
    return r


def comment_review(pid: str, rid: str, text: str, u: dict) -> dict:
    st = store.load(pid)
    r = next((x for x in reviews(st) if x["id"] == rid), None)
    if not r:
        raise PublishError("Unknown review")
    if u["id"] not in (r["reviewer"], r["requested_by"]) and not auth.can_project(u, "edit", db.project(pid)):
        raise PublishError("Only the people in this review comment on it.")
    r["comments"].append({"who": u["id"], "when": time.time(), "text": text.strip()[:2000]})
    store.save(st)
    return r


def approved_by(st: dict, version: int) -> dict | None:
    return next((x for x in reversed(reviews(st)) if x["v"] == version and x["status"] == "approved"), None)


def check_publish(pid: str, version: int, u: dict) -> dict | None:
    """With the policy on: the version needs an approval by someone else than the publisher."""
    st = store.load(pid)
    r = approved_by(st, version)
    if policy()["review_required"]:
        if not r:
            raise PublishError(f"v{version} needs an approved review before it is published (Request review).")
        if r["decided_by"] == u["id"]:
            raise PublishError("The reviewer who approved it cannot also publish it: ask the person who asked for the review, or another colleague.")
    return r


def my_reviews(uid: str) -> list[dict]:
    out = []
    for p in store.dashboards():
        st = store.load(p["id"])
        for r in reviews(st):
            if r["reviewer"] == uid and r["status"] == "pending":
                out.append({**r, "project": p["id"], "name": st.get("name")})
    return out


# ---------------------------------------------------------------- GitHub (each person's own account)

def github_app() -> dict:
    return json.loads(db.meta("github_app") or "{}")


def save_github_app(client_id: str, secret: str | None, who: str | None) -> dict:
    db.set_meta("github_app", json.dumps({"client_id": client_id.strip()}))
    if secret:
        secrets_store.put("org", "github:client_secret", secret, who)
    db.audit("github.app", None, {"client_id": client_id.strip()}, who)
    return {"client_id": client_id.strip(), "has_secret": secrets_store.get("org", "github:client_secret") is not None}


def github_status(uid: str) -> dict:
    info = json.loads(db.meta(f"github:{uid}") or "{}")
    return {"app_ready": bool(github_app().get("client_id")), "connected": bool(secrets_store.get(f"user:{uid}", "github_token")),
            "login": info.get("login"), "default_repo": info.get("default_repo")}


def github_start(uid: str, base_url: str) -> str:
    app = github_app()
    if not app.get("client_id"):
        raise PublishError("Your administrator has not set up GitHub yet.")
    state = secrets.token_urlsafe(24)
    db.run("INSERT INTO auth_flows (state, provider, verifier, nonce, return_to, created) VALUES (?, 'github', '', ?, '#/settings', ?)",
           (state, uid, time.time()))
    return f"{GITHUB_WEB}/login/oauth/authorize?" + urlencode({"client_id": app["client_id"], "scope": "repo", "state": state,
                                                               "redirect_uri": f"{PUBLIC_URL or base_url.rstrip('/')}/auth/github/callback"})


def github_callback(state: str, code: str, base_url: str) -> str:
    flow = db.one("SELECT * FROM auth_flows WHERE state = ? AND provider = 'github'", (state,))
    db.run("DELETE FROM auth_flows WHERE state = ?", (state,))
    if not flow or time.time() - flow["created"] > 900:
        raise PublishError("The GitHub sign-in took too long or was already used.")
    uid = flow["nonce"]
    r = httpx.post(f"{GITHUB_WEB}/login/oauth/access_token", headers={"Accept": "application/json"}, timeout=20,
                   data={"client_id": github_app()["client_id"], "client_secret": secrets_store.get("org", "github:client_secret") or "",
                         "code": code, "redirect_uri": f"{PUBLIC_URL or base_url.rstrip('/')}/auth/github/callback"})
    token = r.json().get("access_token") if r.status_code == 200 else None
    if not token:
        raise PublishError("GitHub did not accept the sign-in.")
    me = _gh("GET", "/user", token).json()
    secrets_store.put(f"user:{uid}", "github_token", token, uid)
    db.set_meta(f"github:{uid}", json.dumps({**json.loads(db.meta(f"github:{uid}") or "{}"), "login": me.get("login")}))
    db.audit("github.connect", uid, {"login": me.get("login")}, uid)
    return uid


def github_disconnect(uid: str) -> None:
    secrets_store.delete(f"user:{uid}", "github_token", uid)
    db.run("DELETE FROM meta WHERE key = ?", (f"github:{uid}",))
    db.audit("github.disconnect", uid, None, uid)


def _gh(method: str, path: str, token: str, **kw) -> httpx.Response:
    r = httpx.request(method, GITHUB_API + path, headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                                                         "X-GitHub-Api-Version": "2022-11-28"}, timeout=60, **kw)
    if r.status_code == 401:
        raise PublishError("GitHub no longer accepts your sign-in: connect GitHub again in Settings.")
    return r


def _token(uid: str) -> str:
    t = secrets_store.get(f"user:{uid}", "github_token")
    if not t:
        raise PublishError("Connect your GitHub account first (Settings > GitHub).")
    return t


def github_repos(uid: str) -> list[dict]:
    r = _gh("GET", "/user/repos", _token(uid), params={"per_page": 100, "sort": "updated", "affiliation": "owner,collaborator,organization_member"})
    if r.status_code != 200:
        raise PublishError(f"GitHub: {r.text[:200]}")
    return [{"full_name": x["full_name"], "private": x["private"], "default_branch": x["default_branch"],
             "can_push": (x.get("permissions") or {}).get("push", False)} for x in r.json()]


def published_files(pid: str) -> dict[str, bytes]:
    """What goes to GitHub: the published definition, the PBIP folder and the check reports."""
    d = store.project_dir(pid)
    st = store.load(pid)
    v = st.get("approved")
    if not v or not (d / "powerbi").exists():
        raise PublishError("Publish the dashboard first: GitHub gets the published version.")
    files = {"definition.yaml": (d / "versions" / f"v{v}" / "definition.yaml").read_bytes()}
    for f in sorted((d / "powerbi").rglob("*")):
        if f.is_file() and not any(part.startswith(".") for part in f.relative_to(d / "powerbi").parts):
            files["powerbi/" + f.relative_to(d / "powerbi").as_posix()] = f.read_bytes()
    if len(files) > GITHUB_FILES_MAX:
        raise PublishError(f"{len(files)} files is more than this push supports ({GITHUB_FILES_MAX}).")
    return files


def github_push(pid: str, uid: str, repo: str, branch: str, folder: str, message: str) -> dict:
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
        raise PublishError("Choose a repository (owner/name).")
    if not re.fullmatch(r"[\w./-]{1,100}", branch) or ".." in branch:
        raise PublishError("That is not a valid branch name.")
    folder = folder.strip().strip("/")
    if folder and (not re.fullmatch(r"[\w./ -]{1,200}", folder) or ".." in folder):
        raise PublishError("That is not a valid folder.")
    token = _token(uid)
    files = published_files(pid)
    info = _gh("GET", f"/repos/{repo}", token)
    if info.status_code != 200:
        raise PublishError(f"Repository {repo} not found, or your GitHub account cannot see it.")
    ref = _gh("GET", f"/repos/{repo}/git/ref/heads/{branch}", token)
    new_branch = ref.status_code == 404
    base_ref = ref if not new_branch else _gh("GET", f"/repos/{repo}/git/ref/heads/{info.json()['default_branch']}", token)
    if base_ref.status_code != 200:
        raise PublishError("The repository has no commits yet: create one on GitHub first (e.g. a README).")
    parent = base_ref.json()["object"]["sha"]
    base_tree = _gh("GET", f"/repos/{repo}/git/commits/{parent}", token).json()["tree"]["sha"]
    tree = []
    for path, data in files.items():
        b = _gh("POST", f"/repos/{repo}/git/blobs", token, json={"content": base64.b64encode(data).decode(), "encoding": "base64"})
        if b.status_code not in (200, 201):
            raise PublishError(f"GitHub refused {path}: {b.text[:200]}")
        tree.append({"path": f"{folder}/{path}" if folder else path, "mode": "100644", "type": "blob", "sha": b.json()["sha"]})
    t = _gh("POST", f"/repos/{repo}/git/trees", token, json={"base_tree": base_tree, "tree": tree})
    c = _gh("POST", f"/repos/{repo}/git/commits", token, json={"message": message[:5000] or "Relay", "tree": t.json()["sha"], "parents": [parent]})
    if c.status_code not in (200, 201):
        raise PublishError(f"GitHub refused the commit: {c.text[:200]}")
    sha = c.json()["sha"]
    upd = (_gh("POST", f"/repos/{repo}/git/refs", token, json={"ref": f"refs/heads/{branch}", "sha": sha}) if new_branch else
           _gh("PATCH", f"/repos/{repo}/git/refs/heads/{branch}", token, json={"sha": sha, "force": False}))
    if upd.status_code not in (200, 201):
        raise PublishError(f"GitHub refused to move {branch}: {upd.text[:200]}")
    url = c.json().get("html_url") or f"{GITHUB_WEB}/{repo}/commit/{sha}"
    st = store.load(pid)
    rec = {"repo": repo, "branch": branch, "folder": folder, "commit": sha, "url": url, "files": len(files), "by": uid, "when": time.time()}
    if st.get("publishes"):
        st["publishes"][-1].setdefault("github", []).append(rec)
    store.save(st)
    db.set_meta(f"github:{uid}", json.dumps({**json.loads(db.meta(f"github:{uid}") or "{}"), "default_repo": repo}))
    store.log(pid, {"kind": "user", "text": f"Versioned v{st.get('approved')} to GitHub {repo}@{branch} ({sha[:7]})"})
    db.audit("github.push", pid, {"repo": repo, "branch": branch, "commit": sha, "files": len(files)}, uid)
    return rec


# ---------------------------------------------------------------- channels (Slack / Teams incoming webhooks)

def channels(uid: str) -> list[dict]:
    return json.loads(db.meta(f"channels:{uid}") or "[]")


def _webhook_ok(url: str) -> bool:
    u = urlparse(url)
    host = (u.hostname or "").lower()
    return u.scheme == "https" and any(host == h or (h.startswith(".") and host.endswith(h)) for h in WEBHOOK_HOSTS) or \
        (os.environ.get("D2D_ALLOW_HTTP_WEBHOOKS") == "1" and u.scheme == "http" and any(host == h.lstrip(".") for h in WEBHOOK_HOSTS))


def save_channel(uid: str, name: str, kind: str, url: str) -> list[dict]:
    if kind not in ("slack", "teams"):
        raise PublishError("Slack or Teams")
    if not _webhook_ok(url.strip()):
        raise PublishError("Paste an incoming webhook URL from Slack (hooks.slack.com) or a Teams workflow.")
    cid = "ch-" + secrets.token_hex(4)
    secrets_store.put(f"user:{uid}", f"channel:{cid}", url.strip(), uid)
    items = channels(uid) + [{"id": cid, "name": name.strip()[:60] or kind.title(), "kind": kind}]
    db.set_meta(f"channels:{uid}", json.dumps(items))
    db.audit("channel.add", cid, {"kind": kind}, uid)
    return items


def remove_channel(uid: str, cid: str) -> list[dict]:
    secrets_store.delete(f"user:{uid}", f"channel:{cid}", uid)
    items = [c for c in channels(uid) if c["id"] != cid]
    db.set_meta(f"channels:{uid}", json.dumps(items))
    return items


def post(uid: str, cid: str, title: str, text: str, link: str) -> None:
    ch = next((c for c in channels(uid) if c["id"] == cid), None)
    url = secrets_store.get(f"user:{uid}", f"channel:{cid}") if ch else None
    if not url or not _webhook_ok(url):
        raise PublishError("Unknown channel")
    if ch["kind"] == "slack":
        body = {"text": f"*{title}*\n{text}\n<{link}|Open in Relay>",
                "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": f"*{title}*\n{text}"}},
                           {"type": "actions", "elements": [{"type": "button", "text": {"type": "plain_text", "text": "Open in Relay"}, "url": link}]}]}
    else:
        body = {"type": "message", "attachments": [{"contentType": "application/vnd.microsoft.card.adaptive", "content": {
            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json", "type": "AdaptiveCard", "version": "1.4",
            "body": [{"type": "TextBlock", "size": "Large", "weight": "Bolder", "text": title, "wrap": True},
                     {"type": "TextBlock", "text": text, "wrap": True}],
            "actions": [{"type": "Action.OpenUrl", "title": "Open in Relay", "url": link}]}}]}
    r = httpx.post(url, json=body, timeout=20)
    if r.status_code >= 300:
        raise PublishError(f"The channel did not accept the post ({r.status_code}).")
    db.audit("channel.post", cid, {"title": title[:200], "link": link}, uid)


# ---------------------------------------------------------------- exports (agent's headless browser)

async def render(uid: str, html: str, fmt: str, width: int = 1320) -> bytes:
    from . import instances
    url = await instances.agent_url(uid) if instances.ENABLED else instances.SHARED_AGENT
    async with httpx.AsyncClient(timeout=180) as c:
        r = await c.post(f"{url}/render", json={"html": html, "format": fmt, "width": width})
    if r.status_code != 200:
        raise PublishError(f"The export could not be drawn ({r.status_code}).")
    return base64.b64decode(r.json()["data"])


def prototype_html(pid: str, v: int | None) -> str:
    d = store.project_dir(pid)
    st = store.load(pid)
    v = v or st.get("approved") or (st["versions"][-1]["v"] if st.get("versions") else None)
    f = d / "versions" / f"v{v}" / "prototype.html"
    if not v or not f.exists():
        raise PublishError("No prototype to export yet.")
    return f.read_text(encoding="utf-8")


def link(base_url: str, frag: str) -> str:
    return f"{PUBLIC_URL or base_url.rstrip('/')}/{frag}"
