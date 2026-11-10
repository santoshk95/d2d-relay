"""Phase 6 endpoints: reviews, publishing policy, GitHub, exports, channels, insight pages."""
import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from pydantic import BaseModel

from . import auth, db, pages, publishing, secrets_store, store

router = APIRouter()


def _u() -> dict:
    return auth.current.get()


def _err(e: Exception, code: int = 400) -> HTTPException:
    return HTTPException(code, str(e))


# ---------------------------------------------------------------- reviews (dev -> review -> published)

class ReviewRequest(BaseModel):
    version: int
    reviewer: str
    note: str = ""


@router.post("/api/projects/{pid}/reviews")
def request_review(pid: str, body: ReviewRequest):
    try:
        return publishing.request_review(pid, body.version, body.reviewer, body.note, _u())
    except publishing.PublishError as e:
        raise _err(e)


@router.get("/api/projects/{pid}/reviews")
def project_reviews(pid: str):
    st = store.load(pid)
    names = {u["id"]: u["name"] for u in db.q("SELECT id, name FROM users")}
    return {"reviews": [{**r, "reviewer_name": names.get(r["reviewer"]), "requested_by_name": names.get(r["requested_by"]),
                         "comments": [{**c, "who_name": names.get(c["who"])} for c in r["comments"]]} for r in publishing.reviews(st)],
            "policy": publishing.policy(),
            "reviewers": [{"id": u["id"], "name": u["name"]} for u in db.q("SELECT id, name FROM users WHERE active = 1 ORDER BY lower(name)")
                          if u["id"] != _u()["id"] and auth.is_dev(db.user(u["id"]) or {})]}


class Decision(BaseModel):
    decision: str | None = None
    comment: str = ""


@router.post("/api/reviews/{pid}/{rid}")
def decide(pid: str, rid: str, body: Decision):
    """Reviewers may have view access only, so this lives outside /api/projects (checked here instead)."""
    if not auth.can_project(_u(), "view", db.project(pid)):
        raise HTTPException(404, "Unknown dashboard")
    try:
        if body.decision:
            return publishing.decide_review(pid, rid, body.decision, body.comment, _u())
        return publishing.comment_review(pid, rid, body.comment, _u())
    except publishing.PublishError as e:
        raise _err(e)


@router.get("/api/reviews")
def my_reviews():
    return {"reviews": publishing.my_reviews(_u()["id"])}


class Policy(BaseModel):
    review_required: bool


@router.get("/api/admin/publishing")
def admin_publishing():
    return {"policy": publishing.policy(), "github": {**publishing.github_app(),
                                                       "has_secret": secrets_store.get("org", "github:client_secret") is not None}}


@router.put("/api/admin/publishing")
def admin_set_publishing(body: dict):
    if "review_required" in body:
        publishing.save_policy(bool(body["review_required"]), _u()["id"])
    if body.get("github_client_id") is not None:
        publishing.save_github_app(str(body["github_client_id"]), body.get("github_client_secret"), _u()["id"])
    return admin_publishing()


# ---------------------------------------------------------------- GitHub

@router.get("/api/me/github")
def my_github():
    return publishing.github_status(_u()["id"])


@router.get("/api/me/github/start")
def github_start(request: Request):
    try:
        return RedirectResponse(publishing.github_start(_u()["id"], str(request.base_url)), 303)
    except publishing.PublishError as e:
        return RedirectResponse("/#/settings?error=" + str(e), 303)


@router.get("/auth/github/callback")
def github_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    if error:
        return RedirectResponse("/#/settings", 303)
    try:
        publishing.github_callback(state, code, str(request.base_url))
    except (publishing.PublishError, httpx.HTTPError) as e:
        return RedirectResponse("/#/settings?error=" + str(e), 303)
    return RedirectResponse("/#/settings?github=connected", 303)


@router.delete("/api/me/github")
def github_disconnect():
    publishing.github_disconnect(_u()["id"])
    return my_github()


@router.get("/api/me/github/repos")
def github_repos():
    try:
        return {"repos": publishing.github_repos(_u()["id"])}
    except (publishing.PublishError, httpx.HTTPError) as e:
        raise _err(e)


class Push(BaseModel):
    repo: str
    branch: str = "main"
    folder: str = ""
    message: str = ""


@router.post("/api/projects/{pid}/github")
def github_push(pid: str, body: Push):
    st = store.load(pid)
    try:
        return publishing.github_push(pid, _u()["id"], body.repo, body.branch, body.folder,
                                      body.message or f"{st.get('name')} v{st.get('approved')} (D2D)")
    except (publishing.PublishError, httpx.HTTPError) as e:
        raise _err(e)


# ---------------------------------------------------------------- exports and channels

@router.post("/api/export/project/{pid}")
async def export_prototype(pid: str, fmt: str = "pdf", version: int | None = None):
    """PDF or PNG of a dashboard's prototype: view access is enough (outside /api/projects, where POST means edit)."""
    if not auth.can_project(_u(), "view", db.project(pid)):
        raise HTTPException(404, "Unknown dashboard")
    if fmt not in ("pdf", "png"):
        raise HTTPException(400, "pdf or png")
    try:
        data = await publishing.render(_u()["id"], publishing.prototype_html(pid, version), fmt)
    except publishing.PublishError as e:
        raise _err(e)
    name = (store.load(pid).get("name") or pid).replace('"', "")
    db.audit("export", pid, {"format": fmt}, _u()["id"])
    return Response(data, media_type="application/pdf" if fmt == "pdf" else "image/png",
                    headers={"Content-Disposition": f'attachment; filename="{name}.{fmt}"'})


@router.get("/api/me/channels")
def my_channels():
    return {"channels": publishing.channels(_u()["id"])}


class Channel(BaseModel):
    name: str
    kind: str
    url: str


@router.post("/api/me/channels")
def add_channel(body: Channel):
    try:
        return {"channels": publishing.save_channel(_u()["id"], body.name, body.kind, body.url)}
    except publishing.PublishError as e:
        raise _err(e)


@router.delete("/api/me/channels/{cid}")
def remove_channel(cid: str):
    return {"channels": publishing.remove_channel(_u()["id"], cid)}


class Post(BaseModel):
    channel: str
    kind: str                # project | page
    id: str
    text: str = ""


@router.post("/api/share/channel")
def share_to_channel(body: Post, request: Request):
    """Post a link to a dashboard or page the person can open (the link still needs a sign-in to D2D)."""
    u = _u()
    if body.kind == "project":
        if not auth.can_project(u, "view", db.project(body.id)):
            raise HTTPException(404, "Unknown dashboard")
        st = store.load(body.id)
        title, frag = st.get("name") or body.id, f"#/p/{body.id}"
    elif body.kind == "page":
        try:
            p = pages.get(body.id, u)
        except pages.PageError:
            raise HTTPException(404, "Unknown page")
        title, frag = p["title"], f"#/pages/{body.id}"
    else:
        raise HTTPException(400, "project or page")
    try:
        publishing.post(u["id"], body.channel, title, body.text.strip()[:1000] or f"Shared from D2D by {u['name']}",
                        publishing.link(str(request.base_url), frag))
    except (publishing.PublishError, httpx.HTTPError) as e:
        raise _err(e)
    return {"ok": True}


# ---------------------------------------------------------------- insight pages

@router.get("/api/pages")
def list_pages():
    return {"pages": pages.mine(_u())}


class NewPage(BaseModel):
    title: str = ""
    source: dict = {"kind": "blank"}


@router.post("/api/pages")
def new_page(body: NewPage):
    try:
        return pages.create(_u(), body.title, body.source)
    except (pages.PageError, Exception) as e:  # noqa: BLE001 - askd errors too
        raise _err(e)


@router.get("/api/pages/{page_id}")
def get_page(page_id: str):
    try:
        return pages.get(page_id, _u())
    except pages.PageError:
        raise HTTPException(404, "Unknown page")


class PageEdit(BaseModel):
    title: str | None = None
    blocks: list[dict] | None = None
    add: dict | None = None


@router.put("/api/pages/{page_id}")
def edit_page(page_id: str, body: PageEdit):
    try:
        if body.add:
            return pages.add(page_id, _u(), body.add)
        return pages.save(page_id, _u(), body.title, body.blocks)
    except pages.PageError as e:
        raise _err(e, 403 if "not change" in str(e) else 404 if "Unknown" in str(e) else 400)


@router.delete("/api/pages/{page_id}")
def delete_page(page_id: str):
    try:
        pages.remove(page_id, _u())
    except pages.PageError as e:
        raise _err(e, 403)
    return list_pages()


class PageShare(BaseModel):
    visibility: str
    team_id: str | None = None
    shares: list[dict] = []


@router.put("/api/pages/{page_id}/shares")
def share_page(page_id: str, body: PageShare):
    try:
        return pages.share(page_id, _u(), body.visibility, body.team_id, body.shares)
    except pages.PageError as e:
        raise _err(e, 403 if "not change" in str(e) or "Unknown" in str(e) else 400)


@router.post("/api/pages/{page_id}/export")
async def export_page(page_id: str, fmt: str = "pdf"):
    if fmt not in ("pdf", "png"):
        raise HTTPException(400, "pdf or png")
    try:
        p = pages.get(page_id, _u())
        data = await publishing.render(_u()["id"], pages.html(p), fmt, 1000)
    except pages.PageError:
        raise HTTPException(404, "Unknown page")
    except publishing.PublishError as e:
        raise _err(e)
    db.audit("export", page_id, {"format": fmt}, _u()["id"])
    return Response(data, media_type="application/pdf" if fmt == "pdf" else "image/png",
                    headers={"Content-Disposition": f'attachment; filename="{p["title"][:60].replace(chr(34), "")}.{fmt}"'})
