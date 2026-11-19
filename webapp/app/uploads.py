"""Uploads in parts (item 64: large data). Cloudflare refuses a request over 100 MB, so a big file reaches D2D Relay in
parts: the browser asks for an upload (POST /api/uploads: the file's name and size), sends the file in parts of PART
bytes (PUT /api/uploads/<id>/<n>, each retried on its own when a connection drops), then closes it (POST .../done: the
parts are joined and their size checked). The form that uses the file (a new dashboard, a revised plan, a change
request, a DAWB hand-off, a Semantic Review) then carries the upload's id instead of the file (`uploads`: a JSON list of
{"field": <the form's file field>, "id": <upload id>}), and the endpoint reads it as if it had come with the form
(as_files), so every check a file goes through is the same.

An upload belongs to the person who started it, in their organisation's projects folder (.uploads, a dot folder: never
in backups); one that is not used within a day is removed. A file is at most MAX_GB (D2D_UPLOAD_MAX_GB, 10), and an
upload starts only when the disk has room for the file three times over (the file, its Parquet copy and a sample).
"""
from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from starlette.datastructures import UploadFile

from . import auth, store

router = APIRouter()
PART = 32 * 1024 * 1024                     # the browser's part size (well under Cloudflare's 100 MB a request)
PART_MAX = PART + 1024 * 1024
MAX_GB = float(os.environ.get("D2D_UPLOAD_MAX_GB") or 10)
KEEP_S = 24 * 3600
ID = re.compile(r"^up-[0-9a-f]{20}$")


def _root() -> Path:
    return store.root() / ".uploads"


def _u() -> dict:
    u = auth.current.get()
    if not u:
        raise HTTPException(401, "Sign in to D2D Relay.")
    return u


def _meta(uid: str) -> tuple[Path, dict]:
    if not ID.match(uid or ""):
        raise HTTPException(404, "There is no such upload.")
    d = _root() / uid
    try:
        m = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise HTTPException(404, "There is no such upload (an upload not used within a day is removed).") from None
    return d, m


def _mine(uid: str, u: dict) -> tuple[Path, dict]:
    d, m = _meta(uid)
    if m.get("owner") != u["id"]:
        raise HTTPException(404, "There is no such upload.")
    return d, m


def tidy() -> int:
    """Remove uploads older than a day (started and never used). Returns how many went."""
    n, now = 0, time.time()
    root = _root()
    if not root.is_dir():
        return 0
    for d in root.iterdir():
        try:
            if d.is_dir() and now - d.stat().st_mtime > KEEP_S:
                shutil.rmtree(d, ignore_errors=True)
                n += 1
        except OSError:
            continue
    return n


def _parts(size: int) -> int:
    return max(1, -(-size // PART))


class Start(BaseModel):
    name: str
    size: int


@router.post("/api/uploads")
def start(body: Start):
    u = _u()
    if not auth.is_dev(u):
        raise HTTPException(403, "Your account cannot add files in this organisation.")
    name = re.sub(r"[^\w.\- ]+", "_", Path(body.name or "").name).strip(" ._")[:200]
    if not name:
        raise HTTPException(400, "The file needs a name.")
    if body.size <= 0:
        raise HTTPException(400, f'"{name}" is empty.')
    if body.size > MAX_GB * 1024 ** 3:
        raise HTTPException(413, f'"{name}" is larger than D2D Relay takes ({MAX_GB:g} GB a file). Split it, or ask PASDACS to '
                                 "connect your warehouse.")
    tidy()
    root = _root()
    root.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(root).free
    if free < body.size * 3 + 2 * 1024 ** 3:
        raise HTTPException(507, f"There is not enough room on the D2D Relay server for \"{name}\" just now. Write to PASDACS.")
    uid = "up-" + secrets.token_hex(10)
    d = root / uid
    d.mkdir()
    (d / "meta.json").write_text(json.dumps({"owner": u["id"], "name": name, "size": int(body.size), "created": time.time(),
                                             "done": False}), encoding="utf-8")
    return {"id": uid, "part_size": PART, "parts": _parts(body.size)}


@router.put("/api/uploads/{uid}/{n}")
async def part(uid: str, n: int, request: Request):
    u = _u()
    d, m = _mine(uid, u)
    if m.get("done"):
        raise HTTPException(409, "This upload is already complete.")
    if not 0 <= n < _parts(m["size"]):
        raise HTTPException(400, "That part is not in this file.")
    tmp, size = d / f"{n:06d}.tmp", 0
    try:
        with tmp.open("wb") as out:
            async for chunk in request.stream():
                size += len(chunk)
                if size > PART_MAX:
                    raise HTTPException(413, "A part is larger than the upload's part size.")
                out.write(chunk)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    expected = min(PART, m["size"] - n * PART)
    if size != expected:
        tmp.unlink(missing_ok=True)
        raise HTTPException(400, f"Part {n + 1} arrived with {size:,} bytes, not {expected:,}: send it again.")
    os.replace(tmp, d / f"{n:06d}.part")
    return {"part": n, "bytes": size}


@router.post("/api/uploads/{uid}/done")
def done(uid: str):
    u = _u()
    d, m = _mine(uid, u)
    if m.get("done"):
        return {"id": uid, "name": m["name"], "bytes": m["size"]}
    k = _parts(m["size"])
    missing = [i + 1 for i in range(k) if not (d / f"{i:06d}.part").is_file()]
    if missing:
        raise HTTPException(409, f"Parts {', '.join(map(str, missing[:5]))} of \"{m['name']}\" have not arrived yet.")
    out = d / "file"
    with out.open("wb") as w:
        for i in range(k):
            p = d / f"{i:06d}.part"
            with p.open("rb") as r:
                shutil.copyfileobj(r, w, 4 * 1024 * 1024)
            p.unlink()
    if out.stat().st_size != m["size"]:
        out.unlink(missing_ok=True)
        raise HTTPException(400, f"\"{m['name']}\" did not arrive whole: upload it again.")
    m["done"] = True
    (d / "meta.json").write_text(json.dumps(m), encoding="utf-8")
    return {"id": uid, "name": m["name"], "bytes": m["size"]}


@router.delete("/api/uploads/{uid}")
def cancel(uid: str):
    u = _u()
    d, _ = _mine(uid, u)
    shutil.rmtree(d, ignore_errors=True)
    return {"deleted": uid}


def _refs(raw: str | None) -> list[dict]:
    try:
        items = json.loads(raw or "[]")
    except ValueError:
        raise HTTPException(400, "The list of uploaded files cannot be read.") from None
    if not isinstance(items, list) or len(items) > 200:
        raise HTTPException(400, "The list of uploaded files cannot be read.")
    return [x for x in items if isinstance(x, dict) and isinstance(x.get("id"), str)]


def as_files(raw: str | None, field: str) -> list[UploadFile]:
    """The completed uploads a form names for one of its file fields, as UploadFiles (the person's own only)."""
    u = _u()
    out = []
    for ref in _refs(raw):
        if (ref.get("field") or "files") != field:
            continue
        d, m = _mine(ref["id"], u)
        if not m.get("done") or not (d / "file").is_file():
            raise HTTPException(409, f"\"{m.get('name')}\" has not finished uploading.")
        out.append(UploadFile(file=(d / "file").open("rb"), filename=m["name"], size=m["size"]))
    return out


def discard(raw: str | None, files: list | None = None) -> None:
    """After the form is done with them: close the files and remove the uploads it named."""
    for f in files or []:
        try:
            f.file.close()
        except Exception:  # noqa: BLE001
            pass
    try:
        refs = _refs(raw)
    except HTTPException:
        return
    u = auth.current.get() or {}
    for ref in refs:
        if ID.match(ref.get("id") or ""):
            try:
                d, m = _meta(ref["id"])
            except HTTPException:
                continue
            if m.get("owner") == u.get("id"):              # only the person's own uploads
                shutil.rmtree(d, ignore_errors=True)
    tidy()
