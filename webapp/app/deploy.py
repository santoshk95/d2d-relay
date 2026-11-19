"""Deployment (item 70): a published dashboard sent to the Power BI service (Microsoft Fabric), and its Power BI
project (PBIP) pushed to GitHub with a GitHub Actions workflow that deploys it to a Fabric workspace (CI/CD).

Power BI service: the dashboard's .pbix (inside its download zip) is uploaded to the workspace an owner picks, with the
Power BI REST API's Imports: POST {D2D_POWERBI_API}/v1.0/myorg/groups/<workspace>/imports?datasetDisplayName=<name>.pbix
&nameConflict=CreateOrOverwrite (multipart), then the import is polled until it Succeeded or Failed. It runs as the
organisation's own Entra app, the one Semantic Review uses (semreview_pbi: its settings, token and fixed hosts); the
app needs Member or Contributor on the workspace. A model built from uploaded files carries its data as imported when
the file was made: a refresh in the service needs the data reachable from it (a warehouse, or a gateway for files).
A dashboard keeps its name in a workspace (its earlier publishes'); a name another dashboard published there already
gets this dashboard's id added, so two dashboards never overwrite each other.

GitHub: an owner sets a repository (owner/name), a branch, a folder and a fine-grained personal access token (kept with
secrets_store, never shown again). "Push to GitHub" commits the dashboard's Power BI project under
<folder>/<dashboard name>/ through the Git data API (blobs, a tree, a commit, the branch moved on; no git binary):
the .pbip and the report and semantic model folders with a .platform file each (Fabric's Git format, so fabric-cicd
finds them), never data files, local settings or anything else that is not the project (pbip_files). The model's
DataFolder parameter is pushed as the .pbix has it (C:\\D2D Relay Data\\<report>\\data\\), never the server's folder.
The dashboard's folder in the repository is D2D Relay's: each push makes it hold exactly the project (files it no
longer has are removed). Once per repository the commit also adds WORKFLOW_PATH (templates_deploy/), which deploys
the changed dashboards to a Fabric workspace with Microsoft's fabric-cicd and a service principal from the
repository's secrets; D2D Relay never changes it afterwards. A token that may not write workflow files still pushes
the dashboard (the run says so).

Item 77 (the user, 2026-11-19: "github is a connector [that] needs to be available for the customer to configure ci/cd
and auto deployment to power bi service"): both are connectors on the Connections page (12-connections.js,
deployConnectorCards), there for every organisation without PASDACS switching them on; its owners set them up, everyone
else sees how they are set. The Organisation page points there.

Auto: owners can switch on publishing and pushing every dashboard as soon as its Power BI file is made: the worker
calls after_pbix(pid), which starts them in the background and never raises; what cannot start is recorded too, so
the dashboard shows it.

What an organisation keeps (its own schema):
  deploy_runs   one row per publish or push: who (or auto), when, where to, status, the ids and address it made, error
Settings: meta "deploy" (JSON: powerbi {workspace_id, workspace_name, auto}, github {repo, branch, folder, auto,
workflow_repos}); the token: secrets_store ("org", TOKEN_SECRET). No credits.

Hosts are fixed: D2D_POWERBI_API (semreview_pbi) and D2D_GITHUB_API (default https://api.github.com; the test stack's
stand-in tests/checks/fake_github.py). What a person types (a workspace GUID, owner/name, a branch) never decides
which host D2D Relay connects to.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import shutil
import threading
import time
import traceback
import uuid
import zipfile
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import auth, db, orgs, secrets_store, store
from . import semreview_pbi as pbi

router = APIRouter()
db.register_schema("""
-- item 70: deployment: each publish of a dashboard to the Power BI service and each push of its project to GitHub
CREATE TABLE IF NOT EXISTS deploy_runs (
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL, kind TEXT NOT NULL, via TEXT NOT NULL DEFAULT 'manual', user_id TEXT,
  status TEXT NOT NULL, step TEXT, created REAL NOT NULL, started REAL, finished REAL, version INTEGER, target TEXT,
  target_name TEXT, item_name TEXT, path TEXT, report_id TEXT, dataset_id TEXT, import_id TEXT, url TEXT,
  commit_sha TEXT, error TEXT, note TEXT);
CREATE INDEX IF NOT EXISTS deploy_runs_project ON deploy_runs (project_id, created);
""")

META = "deploy"
TOKEN_SECRET = "deploy:github:token"
DEFAULT_BRANCH = "main"
DEFAULT_FOLDER = "d2d-relay"
GITHUB_API = os.environ.get("D2D_GITHUB_API", "https://api.github.com").rstrip("/")
GITHUB_WEB = os.environ.get("D2D_GITHUB_WEB", "https://github.com").rstrip("/")
WORKFLOW_PATH = ".github/workflows/d2d-relay-deploy.yml"
WORKFLOW_TEMPLATE = Path(__file__).resolve().parent / "templates_deploy" / "d2d-relay-deploy.yml"
GH_SECRETS = ("AZURE_TENANT_ID", "AZURE_CLIENT_ID", "AZURE_CLIENT_SECRET", "FABRIC_WORKSPACE_ID")
KINDS = ("powerbi", "github")
MAX_PBIX = 1024 ** 3                   # the Imports API takes a .pbix of up to 1 GB in one request
IMPORT_WAIT_S = int(os.environ.get("D2D_DEPLOY_IMPORT_WAIT_S") or 1800)
POLL_S = float(os.environ.get("D2D_DEPLOY_POLL_S") or 3)
STALE_S = 3 * 3600                     # a run still open after this long lost its thread
MAX_FILE, MAX_TOTAL, MAX_FILES = 50 * 1024 * 1024, 200 * 1024 * 1024, 5000     # what one push carries
INLINE_MAX, INLINE_TOTAL = 512 * 1024, 4 * 1024 * 1024     # text files go inside the tree request (one request)
MAX_BODY = 32 * 1024 * 1024
PARALLEL = max(int(os.environ.get("D2D_DEPLOY_PARALLEL") or 2), 1)     # publishes and pushes at once, on this server
GUID = pbi.GUID
SHA = re.compile(r"^[0-9a-f]{40}$")
REPO = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}$")
TOKEN = re.compile(r"^[A-Za-z0-9_]{20,255}$")
SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._()-]{0,79}$")
RESERVED = re.compile(r"^(con|prn|aux|nul|com[0-9]|lpt[0-9])(\..*)?$", re.I)     # names Windows cannot check out
EMPTY = "The repository is empty. Add a first file on GitHub (a README is enough), then try again."
GITIGNORE = ("# D2D Relay: files Power BI writes when this project is opened for editing. Never commit them: cache.abf\n"
             "# holds data.\n**/.pbi/localSettings.json\n**/.pbi/cache.abf\n")
# What a Power BI project folder may hold that is not the project: data, models with data, archives, logs, keys
NOT_PROJECT = {".csv", ".tsv", ".parquet", ".abf", ".pbix", ".pbit", ".xlsx", ".xlsm", ".xlsb", ".xls", ".ods", ".jsonl",
               ".ndjson", ".avro", ".orc", ".feather", ".arrow", ".db", ".sqlite", ".sqlite3", ".duckdb", ".mdb", ".accdb",
               ".pkl", ".pickle", ".npy", ".npz", ".h5", ".hdf5", ".sav", ".dta", ".sas7bdat", ".zip", ".7z", ".gz", ".tgz",
               ".tar", ".bz2", ".xz", ".rar", ".bak", ".tmp", ".log", ".env", ".pem", ".key", ".pfx", ".p12", ".jks",
               ".keystore", ".kdbx", ".ppk", ".cer", ".crt"}
NOT_PROJECT_NAMES = {"localsettings.json", "cache.abf", "credentials.json", "secrets.json", "id_rsa", "id_ed25519"}
_slots = threading.BoundedSemaphore(PARALLEL)
_start_lock = threading.Lock()
_push_locks: dict[str, threading.Lock] = {}
_BOOT = time.time()                    # a run opened before this server started cannot be going any more


class DeployError(Exception):
    """Shown to the person as it is."""

    def __init__(self, text: str, status: int = 400):
        super().__init__(text)
        self.status = status


class _Moved(Exception):
    """The branch moved while the commit was made: start again from its new head."""


# ---------------------------------------------------------------- settings

def _load() -> dict:
    try:
        s = json.loads(db.meta(META) or "{}")
    except ValueError:
        s = {}
    s = s if isinstance(s, dict) else {}
    for k in KINDS:
        s[k] = s.get(k) if isinstance(s.get(k), dict) else {}
    return s


def _save(s: dict) -> None:
    db.set_meta(META, json.dumps(s))


def token() -> str | None:
    return secrets_store.get("org", TOKEN_SECRET)


def _workflow_done(g: dict, repo: str) -> bool:
    return repo.lower() in [str(x).lower() for x in g.get("workflow_repos") or []]


def _mark_workflow(repo: str) -> None:
    s = _load()
    have = [str(x) for x in s["github"].get("workflow_repos") or []]
    if repo.lower() not in [x.lower() for x in have]:
        s["github"]["workflow_repos"] = (have + [repo.lower()])[-50:]
        _save(s)


def public(u: dict | None) -> dict:
    """What the screens may see: never the token."""
    s = _load()
    p, g = s["powerbi"], s["github"]
    return {"powerbi": {"connected": pbi.settings() is not None, "workspace_id": p.get("workspace_id"),
                        "workspace_name": p.get("workspace_name"), "auto": bool(p.get("auto")), "saved": p.get("saved")},
            "github": {"repo": g.get("repo"), "branch": g.get("branch") or DEFAULT_BRANCH, "folder": g.get("folder") or DEFAULT_FOLDER,
                       "auto": bool(g.get("auto")), "has_token": token() is not None, "saved": g.get("saved"),
                       "workflow": WORKFLOW_PATH, "workflow_added": bool(g.get("repo")) and _workflow_done(g, g["repo"]),
                       "secrets": list(GH_SECRETS)},
            "can_manage": orgs.is_owner(u)}


def clean_repo(text: str | None) -> str:
    r = (text or "").strip()
    for prefix in (GITHUB_WEB + "/", "https://github.com/", "http://github.com/", "github.com/", "git@github.com:"):
        if r.lower().startswith(prefix.lower()):
            r = r[len(prefix):]
    r = r.strip("/")
    r = r[:-4] if r.lower().endswith(".git") else r
    if not REPO.match(r) or r.split("/")[1] in (".", ".."):
        raise DeployError("The repository is its owner and name, for example contoso/bi-dashboards.")
    return r


def clean_branch(text: str | None) -> str:
    b = (text or "").strip() or DEFAULT_BRANCH
    if (len(b) > 200 or not re.fullmatch(r"[A-Za-z0-9._/-]+", b) or b.startswith(("/", ".", "-")) or b.endswith(("/", ".", ".lock"))
            or "//" in b or ".." in b or "/." in b):
        raise DeployError("That is not a branch name D2D Relay can push to (letters, digits, - _ . and /), for example main.")
    return b


def clean_folder(text: str | None) -> str:
    f = (text or "").strip().replace("\\", "/").strip("/") or DEFAULT_FOLDER
    parts = f.split("/")
    if len(f) > 200 or len(parts) > 5 or any(not SEGMENT.match(x) or x.endswith((" ", ".")) or RESERVED.match(x) for x in parts):
        raise DeployError("The folder is a path in the repository, such as d2d-relay or bi/d2d-relay (letters, digits, spaces and - _ . ( )).")
    return f


def save_powerbi(workspace_id: str | None, auto: bool, who: str) -> None:
    s = _load()
    p = dict(s["powerbi"])
    wid = (workspace_id or "").strip()
    if wid and wid.lower() != str(p.get("workspace_id") or "").lower():
        if not GUID.match(wid):
            raise DeployError("That is not a workspace id.")
        if not pbi.settings():
            raise DeployError("Connect Power BI first: an owner enters your organisation's Entra app under Connections, Power BI service.")
        try:
            hit = next((w for w in pbi.workspaces() if w["id"].lower() == wid.lower()), None)
        except pbi.PbiError as e:
            raise DeployError(str(e)) from None
        if not hit:
            raise DeployError("Your organisation's Entra app does not see that workspace. Add the app to it as Member or "
                              "Contributor, then choose it again.")
        p.update(workspace_id=hit["id"], workspace_name=hit["name"])
    elif not wid:
        p.pop("workspace_id", None)
        p.pop("workspace_name", None)
    if auto and not p.get("workspace_id"):
        raise DeployError("Choose a workspace before switching on automatic publishing.")
    p.update(auto=bool(auto), saved=time.time(), by=who)
    s["powerbi"] = p
    _save(s)
    db.audit("deploy.settings_powerbi", None, {"workspace": p.get("workspace_name"), "auto": p["auto"]}, who)


def save_github(repo: str | None, branch: str | None, folder: str | None, auto: bool, tok: str | None, who: str) -> None:
    s = _load()
    g = dict(s["github"])
    repo, branch, folder, tok = clean_repo(repo), clean_branch(branch), clean_folder(folder), (tok or "").strip()
    if tok and not TOKEN.match(tok):
        raise DeployError("That does not look like a GitHub token. Make a fine-grained personal access token (it starts with github_pat_).")
    if not tok and not token():
        raise DeployError("Enter a token for the repository: a fine-grained personal access token.")
    if tok:
        secrets_store.put("org", TOKEN_SECRET, tok, who)
    g.update(repo=repo, branch=branch, folder=folder, auto=bool(auto), saved=time.time(), by=who)
    s["github"] = g
    _save(s)
    db.audit("deploy.settings_github", None, {"repo": repo, "branch": branch, "folder": folder, "auto": g["auto"],
                                               "token_changed": bool(tok)}, who)


def remove_github(who: str) -> None:
    secrets_store.delete("org", TOKEN_SECRET, who)
    s = _load()
    s["github"] = {"workflow_repos": s["github"].get("workflow_repos") or []}      # a workflow added once stays added
    _save(s)
    db.audit("deploy.github_removed", None, None, who)


# ---------------------------------------------------------------- GitHub (the Git data API, with the organisation's token)

class GitHub:
    """The GitHub REST API for one repository."""

    def __init__(self, tok: str, repo: str):
        self.repo = repo
        self.c = httpx.Client(base_url=GITHUB_API, timeout=httpx.Timeout(30, read=120, write=120), follow_redirects=False,
                              headers={"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json",
                                       "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "D2D-Relay-Deploy/1.0"})

    def __enter__(self) -> "GitHub":
        return self

    def __exit__(self, *exc) -> None:
        self.c.close()

    def call(self, method: str, path: str, what: str, ok: tuple = (200,), **kw) -> httpx.Response:
        try:
            r = self.c.request(method, f"/repos/{self.repo}{path}", **kw)
        except httpx.HTTPError as e:
            raise DeployError(f"Could not reach GitHub ({e.__class__.__name__}).") from e
        if r.status_code not in ok:
            raise gh_error(r, what, self.repo)
        if len(r.content) > MAX_BODY:
            raise DeployError("GitHub sent more than D2D Relay reads.")
        return r


def _json(r: httpx.Response) -> dict:
    try:
        out = r.json()
    except ValueError:
        return {}
    return out if isinstance(out, dict) else {}


def gh_error(r: httpx.Response, what: str, repo: str) -> DeployError:
    msg = str(_json(r).get("message") or "")[:200]
    low = msg.lower()
    if r.status_code == 401:
        return DeployError("GitHub did not accept the token (401): it is wrong, has expired or was revoked. An owner enters a new one.")
    if r.status_code == 429 or (r.status_code == 403 and (r.headers.get("x-ratelimit-remaining") == "0" or "rate limit" in low)):
        return DeployError("GitHub's rate limit for this token was reached. Try again in a few minutes.")
    if r.status_code == 409 and "empty" in low:
        return DeployError(EMPTY)
    if r.status_code in (403, 404, 422) and "workflow" in low:
        return DeployError(f"The token may not change workflow files (GitHub said: {msg}).")
    if r.status_code == 403:
        return DeployError(f"The token may not {what} (403). Give it Contents: Read and write on {repo}." + (f" GitHub said: {msg}." if msg else ""))
    if r.status_code == 404:
        return DeployError(f"GitHub cannot find {repo}, or the token cannot see it (404). Check the name, and that the token was made "
                           "for this repository.")
    return DeployError(f"GitHub could not {what} ({r.status_code}{': ' + msg if msg else ''}).")


def git_sha(data: bytes) -> str:
    """The id git gives a file's content (a blob), to leave out of a push what is already there."""
    return hashlib.sha1(b"blob %d\x00" % len(data) + data).hexdigest()


def _text(data: bytes) -> str | None:
    if b"\x00" in data:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _tree(gh: GitHub, sha: str, recursive: bool = False) -> list[dict]:
    body = _json(gh.call("GET", f"/git/trees/{sha}" + ("?recursive=1" if recursive else ""), "read the repository"))
    if recursive and body.get("truncated"):
        raise DeployError("The dashboard's folder in the repository holds too many files for GitHub to list.")
    return [e for e in body.get("tree") or [] if isinstance(e, dict) and isinstance(e.get("path"), str)]


def _subtree(gh: GitHub, root: str, path: str) -> str | None:
    """The tree (folder) at path under root, or None when it is not there: one level at a time, so a big repository
    is never listed whole."""
    sha = root
    for part in [x for x in path.split("/") if x]:
        hit = next((e for e in _tree(gh, sha) if e["path"] == part and e.get("type") == "tree"), None)
        sha = str((hit or {}).get("sha") or "")
        if not SHA.match(sha):
            return None
    return sha


def _blobs_under(gh: GitHub, root: str, path: str) -> dict[str, dict]:
    sha = _subtree(gh, root, path)
    return {e["path"]: e for e in _tree(gh, sha, recursive=True) if e.get("type") == "blob"} if sha else {}


def _exists(gh: GitHub, root: str, path: str) -> bool:
    parent, _, name = path.rpartition("/")
    sha = _subtree(gh, root, parent)
    return bool(sha) and any(e["path"] == name and e.get("type") == "blob" for e in _tree(gh, sha))


def _head(gh: GitHub, branch: str) -> tuple[str, str, str | None]:
    """(the branch's last commit, its tree, the branch it is made from when it does not exist yet)."""
    r = gh.call("GET", f"/git/ref/heads/{branch}", "read the branch", ok=(200, 404))
    base = None
    if r.status_code == 404:
        base = str(_json(gh.call("GET", "", "read the repository")).get("default_branch") or "")
        if not base:
            raise DeployError(EMPTY)
        try:
            clean_branch(base)
        except DeployError:
            raise DeployError(f"The branch {branch} does not exist, and the default branch has a name D2D Relay cannot start "
                              "it from. Make the branch on GitHub first.") from None
        r = gh.call("GET", f"/git/ref/heads/{base}", "read the default branch")
    head = str((_json(r).get("object") or {}).get("sha") or "")
    if not SHA.match(head):
        raise DeployError("GitHub did not say where the branch is.")
    root = str((_json(gh.call("GET", f"/git/commits/{head}", "read the last commit")).get("tree") or {}).get("sha") or "")
    if not SHA.match(root):
        raise DeployError("GitHub did not say what the last commit holds.")
    return head, root, base


def _entries(gh: GitHub, files: dict[str, bytes], old: dict[str, dict], dest: str) -> tuple[list[dict], int]:
    """The tree entries that make dest hold exactly files: changed files (text inside the request, anything else as a
    blob of its own), and every other file under dest removed. Unchanged files are left out."""
    entries, budget, changed = [], INLINE_TOTAL, 0
    for path, data in sorted(files.items()):
        prev = old.get(path[len(dest) + 1:])
        if prev and prev.get("sha") == git_sha(data) and prev.get("mode") == "100644":
            continue
        changed += 1
        text = _text(data)
        if text is not None and len(data) <= INLINE_MAX and len(data) <= budget:
            budget -= len(data)
            entries.append({"path": path, "mode": "100644", "type": "blob", "content": text})
            continue
        b = _json(gh.call("POST", "/git/blobs", "upload a file", ok=(201,),
                          json={"content": base64.b64encode(data).decode(), "encoding": "base64"}))
        sha = str(b.get("sha") or "")
        if not SHA.match(sha):
            raise DeployError("GitHub did not take a file of the project.")
        entries.append({"path": path, "mode": "100644", "type": "blob", "sha": sha})
    for rel, e in sorted(old.items()):
        if f"{dest}/{rel}" not in files:
            entries.append({"path": f"{dest}/{rel}", "mode": e.get("mode") or "100644", "type": "blob", "sha": None})
    return entries, changed


def _commit_and_move(gh: GitHub, branch: str, root: str, head: str, entries: list[dict], message: str,
                     base: str | None) -> tuple[str, str | None]:
    tsha = str(_json(gh.call("POST", "/git/trees", "write the files", ok=(201,), json={"base_tree": root, "tree": entries})).get("sha") or "")
    if not SHA.match(tsha):
        raise DeployError("GitHub did not take the files.")
    c = _json(gh.call("POST", "/git/commits", "make the commit", ok=(201,), json={"message": message, "tree": tsha, "parents": [head]}))
    sha = str(c.get("sha") or "")
    if not SHA.match(sha):
        raise DeployError("GitHub did not make the commit.")
    if base:
        r = gh.call("POST", "/git/refs", "make the branch", ok=(201, 422), json={"ref": f"refs/heads/{branch}", "sha": sha})
    else:
        r = gh.call("PATCH", f"/git/refs/heads/{branch}", "move the branch to the new commit", ok=(200, 422), json={"sha": sha, "force": False})
    if r.status_code == 422:
        low = str(_json(r).get("message") or "").lower()
        if "fast forward" in low or "fast-forward" in low or "already exists" in low:
            raise _Moved()
        raise gh_error(r, "move the branch to the new commit", gh.repo)
    url = c.get("html_url")
    return sha, url if isinstance(url, str) and url.startswith("https://") else None


def push(gh: GitHub, branch: str, dest: str, files: dict[str, bytes], message: str, workflow: str | None) -> dict:
    """Commit files ({path in the repository: bytes}, all under dest) on branch, so that dest holds exactly them; with
    workflow, also WORKFLOW_PATH when the branch does not have it yet. Never a forced push: when the branch moves
    meanwhile, it starts again from the new head. A refused workflow file does not stop the dashboard's own push."""
    for _ in range(4):
        head, root, base = _head(gh, branch)
        entries, changed = _entries(gh, files, _blobs_under(gh, root, dest), dest)
        wf_entry, wf_exists = None, False
        if workflow is not None:
            wf_exists = _exists(gh, root, WORKFLOW_PATH)
            if not wf_exists:
                wf_entry = {"path": WORKFLOW_PATH, "mode": "100644", "type": "blob", "content": workflow}
        out = {"files": changed, "created_branch": base, "workflow_exists": wf_exists}
        if not entries and not wf_entry:
            if base:                            # nothing to change, but the branch is made all the same
                r = gh.call("POST", "/git/refs", "make the branch", ok=(201, 422), json={"ref": f"refs/heads/{branch}", "sha": head})
                if r.status_code == 422:
                    continue
            return {**out, "commit": head, "unchanged": True}
        refused = None
        try:
            if wf_entry:
                try:
                    sha, url = _commit_and_move(gh, branch, root, head, entries + [wf_entry], message, base)
                    return {**out, "commit": sha, "url": url, "unchanged": not entries, "workflow_added": True}
                except DeployError as e:
                    refused = str(e)            # most often: the token may not write workflow files
                    if not entries:
                        return {**out, "commit": head, "unchanged": True, "workflow_refused": refused}
            sha, url = _commit_and_move(gh, branch, root, head, entries, message, base)
            return {**out, "commit": sha, "url": url, "unchanged": False, "workflow_refused": refused}
        except _Moved:
            continue
    raise DeployError("The branch kept moving while D2D Relay pushed to it (someone else is pushing). Try again in a minute.")


def test_github(repo: str, branch: str, tok: str) -> dict:
    """Whether the token reaches the repository and may write to it. The write test is a blob nobody points to (no
    commit, nothing anyone sees; GitHub removes it later)."""
    with GitHub(tok, repo) as gh:
        info = _json(gh.call("GET", "", "read the repository"))
        default = str(info.get("default_branch") or "")
        r = gh.call("GET", f"/git/ref/heads/{branch}", "read the branch", ok=(200, 404))
        exists = r.status_code == 200
        if not exists:
            if not default:
                raise DeployError(EMPTY)
            r = gh.call("GET", f"/git/ref/heads/{default}", "read the default branch")
        head = str((_json(r).get("object") or {}).get("sha") or "")
        gh.call("POST", "/git/blobs", "write to the repository", ok=(201,), json={"content": "D2D Relay connection test\n", "encoding": "utf-8"})
        root = str((_json(gh.call("GET", f"/git/commits/{head}", "read the last commit")).get("tree") or {}).get("sha") or "") if SHA.match(head) else ""
        wf = _exists(gh, root, WORKFLOW_PATH) if SHA.match(root) else False
    return {"ok": True, "repo": str(info.get("full_name") or repo), "private": bool(info.get("private")), "branch": branch,
            "branch_exists": exists, "default_branch": default or None, "workflow_exists": wf}


# ---------------------------------------------------------------- the dashboard's files

def _report_name(d: Path, st: dict) -> str:
    """The checked report in powerbi/ (its folder holds <name>.pbip with the report and model next to it)."""
    out = st.get("output") or {}
    name = out.get("report") or Path(out.get("pbix") or "").stem
    if name and (d / "powerbi" / f"{name}.pbip").is_file():
        return name
    found = sorted((d / "powerbi").glob("*.pbip")) if (d / "powerbi").is_dir() else []
    return found[0].stem if found else ""


def _skip(name: str) -> bool:
    low = name.lower()
    return low in NOT_PROJECT_NAMES or Path(low).suffix in NOT_PROJECT or low.endswith(".env") or low.startswith(".env")


def pbip_files(d: Path, report: str) -> tuple[dict[str, bytes], list[str]]:
    """The dashboard's Power BI project, {path inside the dashboard's folder: bytes}: <report>.pbip, <report>.Report/ and
    <report>.SemanticModel/, and what was left out. Never data (CSV, Parquet, Excel, a .pbix, the cache.abf of a
    project opened for editing), local settings (.pbi/), hidden files, links, keys or archives; nothing else in
    powerbi/ either."""
    src = d / "powerbi"
    pbip = src / f"{report}.pbip"
    if not report or src.is_symlink() or not pbip.is_file() or pbip.is_symlink():
        raise DeployError("This dashboard has no Power BI project to push. Make its Power BI file again, then push.", 409)
    out, skipped, total = {pbip.name: pbip.read_bytes()}, [], 0
    for top in (f"{report}.Report", f"{report}.SemanticModel"):
        base = src / top
        if not base.is_dir() or base.is_symlink():
            raise DeployError(f"The Power BI project of this dashboard is incomplete ({top} is missing). Make its Power BI file again, then push.", 409)
        for root, dirs, names in os.walk(base, followlinks=False):
            here = Path(root)
            for x in sorted(dirs):
                if x.startswith(".") or (here / x).is_symlink():
                    skipped.append((here / x).relative_to(src).as_posix() + "/")
            dirs[:] = sorted(x for x in dirs if not x.startswith(".") and not (here / x).is_symlink())
            for n in sorted(names):
                p = here / n
                rel = p.relative_to(src).as_posix()
                if n.startswith(".") or p.is_symlink() or not p.is_file() or _skip(n):
                    skipped.append(rel)
                    continue
                size = p.stat().st_size
                if size > MAX_FILE:
                    raise DeployError(f"{rel} is bigger than {MAX_FILE // 1048576} MB: too big for a repository.")
                total += size
                if total > MAX_TOTAL or len(out) >= MAX_FILES:
                    raise DeployError("The Power BI project is too big to push in one commit.")
                out[rel] = p.read_bytes()
    for p in sorted(src.iterdir()) if src.is_dir() else []:
        if p.name not in (pbip.name, f"{report}.Report", f"{report}.SemanticModel"):
            skipped.append(p.name + ("/" if p.is_dir() else ""))
    return out, skipped


def neutral_data_folder(raw: bytes, value: str) -> bytes:
    """model.bim with its DataFolder parameter set to value (where the .pbix has it), not this server's folder."""
    try:
        m = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError):
        return raw
    changed = False
    for e in ((m.get("model") or {}).get("expressions") or []) if isinstance(m, dict) else []:
        if not isinstance(e, dict) or e.get("name") != "DataFolder" or e.get("kind") != "m":
            continue
        expr = e.get("expression")
        text = "\n".join(str(x) for x in expr) if isinstance(expr, list) else str(expr or "")
        hit = re.match(r'\s*"(?:[^"]|"")*"(\s+meta\s+\[.*)$', text, re.S)
        if not hit:
            continue
        new = '"' + value.replace('"', '""') + '"' + hit.group(1)
        e["expression"] = new.split("\n") if isinstance(expr, list) else new
        changed = True
    return json.dumps(m, indent=2, ensure_ascii=False).encode("utf-8") if changed else raw


def platform_file(kind: str, name: str, logical_id: str) -> bytes:
    """An item's .platform file (Fabric's Git format), which fabric-cicd reads to find the item."""
    return (json.dumps({"$schema": "https://developer.microsoft.com/json-schemas/fabric/gitIntegration/platformProperties/2.0.0/schema.json",
                        "metadata": {"type": kind, "displayName": name},
                        "config": {"version": "2.0", "logicalId": logical_id}}, indent=2) + "\n").encode("utf-8")


def logical_id(pid: str, kind: str) -> str:
    """The same id at every push of a dashboard's item (fabric-cicd knows the item by it)."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"https://d2d-relay.invalid/{db.tenant()}/{pid}/{kind}"))


def commit_files(files: dict[str, bytes], report: str, item: str, dest: str, data_folder: str, pid: str) -> dict[str, bytes]:
    """{path in the repository: bytes}: the project under dest, the .platform files, the model's DataFolder as the .pbix
    has it, and a .gitignore that keeps local settings and the data cache out."""
    out = {}
    for rel, data in files.items():
        if rel == f"{report}.SemanticModel/model.bim":
            data = neutral_data_folder(data, data_folder)
        out[f"{dest}/{rel}"] = data
    for kind in ("Report", "SemanticModel"):
        out[f"{dest}/{report}.{kind}/.platform"] = platform_file(kind, item, logical_id(pid, kind))
    out[f"{dest}/.gitignore"] = GITIGNORE.encode("utf-8")
    return out


def workflow_text(branch: str, folder: str) -> str:
    return WORKFLOW_TEMPLATE.read_text(encoding="utf-8").replace("__D2D_BRANCH__", branch).replace("__D2D_FOLDER__", folder)


def leaf_name(name: str | None, pid: str) -> str:
    """A dashboard's folder name in the repository: its name, without characters a path cannot have."""
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f]+', "-", str(name or ""))
    s = re.sub(r"\s+", " ", s).strip(" .-")[:80].strip(" .-")
    if not s:
        return pid
    return f"{s} ({pid})" if RESERVED.match(s) else s


def _taken(kind: str, target: str, col: str, value: str, pid: str) -> bool:
    assert col in ("path", "item_name")
    return db.one(f"SELECT 1 AS x FROM deploy_runs WHERE kind = ? AND status = 'done' AND target = ? AND {col} = ? AND project_id <> ?",
                  (kind, target, value, pid)) is not None


def _gh_target(g: dict) -> str:
    return f"{g.get('repo')}@{g.get('branch') or DEFAULT_BRANCH}"


def _dest(pid: str, st: dict, g: dict, report: str) -> tuple[str, str]:
    """Where this dashboard goes in the repository (<folder>/<dashboard name>) and its items' name: where its last push
    to this repository and branch went, else its name now; a folder or a name another dashboard has there already gets
    this dashboard's id added."""
    target, folder = _gh_target(g), g.get("folder") or DEFAULT_FOLDER
    last = db.one("SELECT path, item_name FROM deploy_runs WHERE project_id = ? AND kind = 'github' AND status = 'done' AND target = ? "
                  "AND substr(path, 1, ?) = ? ORDER BY created DESC LIMIT 1", (pid, target, len(folder) + 1, folder + "/"))
    if last and last["path"] and last["item_name"]:
        return last["path"], last["item_name"]
    leaf = leaf_name(st.get("name"), pid)
    path = f"{folder}/{leaf}"
    if _taken("github", target, "path", path, pid):
        path = f"{folder}/{leaf} ({pid})"
    item = report if not _taken("github", target, "item_name", report, pid) else f"{report} ({pid})"
    return path, item


def _dataset_name(pid: str, ws: str, base: str) -> str:
    """A dashboard's name in a workspace: the name its earlier publishes there had (one dashboard, one report), else
    its report's name, with the dashboard's id added when another dashboard published that name there."""
    last = db.one("SELECT item_name FROM deploy_runs WHERE project_id = ? AND kind = 'powerbi' AND status = 'done' AND target = ? "
                  "ORDER BY created DESC LIMIT 1", (pid, ws))
    if last and last["item_name"]:
        return last["item_name"]
    return base if not _taken("powerbi", ws, "item_name", base, pid) else f"{base} ({pid})"


def _has_pbix(d: Path, st: dict) -> bool:
    out = st.get("output") or {}
    if not out.get("pbix"):
        return False
    return (bool(out.get("zip")) and (d / Path(str(out["zip"])).name).is_file()) or (d / "pbix" / Path(str(out["pbix"])).name).is_file()


def _pbix_file(d: Path, st: dict, rid: str) -> tuple[Path, Path | None]:
    """The dashboard's .pbix as a file to upload (taken out of its download zip into a dot folder, removed after the
    upload), and that temporary file (None when the .pbix was there already)."""
    out = st.get("output") or {}
    report = Path(out.get("pbix") or "").stem
    z = d / Path(str(out.get("zip") or "-")).name
    if out.get("zip") and z.is_file() and not z.is_symlink():
        folder = store.root() / ".deploy"
        tmp = folder / f"{rid}.pbix"
        try:
            folder.mkdir(parents=True, exist_ok=True)
            for old in folder.glob("*.pbix"):           # left by a restart in the middle of an upload
                if old.stat().st_mtime < time.time() - 6 * 3600:
                    old.unlink(missing_ok=True)
            with zipfile.ZipFile(z) as zf:
                found = [i for i in zf.infolist() if not i.is_dir() and i.filename.lower().endswith(".pbix")]
                pick = next((i for i in found if i.filename == f"{report}/{report}.pbix"), found[0] if found else None)
                if pick is None:
                    raise DeployError("The download holds no Power BI file. Make the Power BI file again, then publish.", 409)
                if pick.file_size > MAX_PBIX:
                    raise DeployError("The Power BI file is over 1 GB: the Power BI service takes bigger files only in Premium "
                                      "workspaces, through its own upload. Publish it from the download instead.")
                with zf.open(pick) as src, tmp.open("wb") as dst:
                    shutil.copyfileobj(src, dst, 1024 * 1024)
                return tmp, tmp
        except (zipfile.BadZipFile, OSError) as e:
            tmp.unlink(missing_ok=True)
            raise DeployError(f"The download could not be read ({e.__class__.__name__}). Make the Power BI file again, then publish.") from None
    loose = d / "pbix" / Path(str(out.get("pbix") or "-")).name
    if out.get("pbix") and loose.is_file() and not loose.is_symlink():
        return loose, None
    raise DeployError("This dashboard has no Power BI file yet. Make it, then publish.", 409)


# ---------------------------------------------------------------- Power BI (the Imports API, as the organisation's Entra app)

def _pbi_token() -> str:
    try:
        return pbi.token(pbi.POWERBI_SCOPE)
    except pbi.PbiError as e:
        raise DeployError(str(e)) from None


def _pbi_error(r: httpx.Response, what: str) -> DeployError:
    body = _json(r)
    err = body.get("error") if isinstance(body.get("error"), dict) else {}
    code = str(err.get("code") or body.get("errorCode") or "")
    if r.status_code == 403 or code in ("PowerBINotAuthorizedException", "Unauthorized", "InsufficientPrivileges"):
        return DeployError(f"Your organisation's Entra app may not {what} ({r.status_code}{', ' + code if code else ''}). Add the app to "
                           "the workspace as Member or Contributor, and allow service principals to use Fabric APIs (Fabric admin "
                           "portal, Developer settings).")
    return DeployError(str(pbi._error(r, what)))        # noqa: SLF001 - Semantic Review's words for the other answers


def _import_error(body: dict) -> str:
    e = body.get("error")
    if isinstance(e, dict):
        detail = e.get("details") or e.get("message") or ""
        if not isinstance(detail, str):
            detail = json.dumps(detail)
        text = ": ".join(x for x in (str(e.get("code") or ""), detail) if x)
        return text[:300] or "no reason given"
    return str(e or "no reason given")[:300]


def _publish(row: dict, st: dict, d: Path) -> dict:
    ws = str(row["target"] or "")
    if not GUID.match(ws):
        raise DeployError("The Power BI workspace is not set up. An owner chooses it again in the deployment settings.")
    out = st.get("output") or {}
    name = _dataset_name(row["project_id"], ws, Path(out.get("pbix") or "").stem or _report_name(d, st) or st.get("name") or row["project_id"])
    _step(row["id"], "Preparing the Power BI file", item_name=name)
    src, temp = _pbix_file(d, st, row["id"])
    try:
        url = f"{pbi.POWERBI}/v1.0/myorg/groups/{ws}/imports"
        filename = (re.sub(r"[^A-Za-z0-9._ -]+", "_", name).strip() or "dashboard")[:100] + ".pbix"
        with httpx.Client(timeout=httpx.Timeout(60, read=600, write=600), follow_redirects=False,
                          headers={"User-Agent": "D2D-Relay-Deploy/1.0"}) as c:
            _step(row["id"], "Uploading the Power BI file")
            try:
                with src.open("rb") as fh:
                    r = c.post(url, params={"datasetDisplayName": f"{name}.pbix", "nameConflict": "CreateOrOverwrite"},
                               headers={"Authorization": f"Bearer {_pbi_token()}"},
                               files={"file": (filename, fh, "application/octet-stream")})
            except httpx.HTTPError as e:
                raise DeployError(f"Could not reach the Power BI service ({e.__class__.__name__}).") from e
            if r.status_code not in (200, 201, 202):
                raise _pbi_error(r, "publish to this workspace")
            iid = str(_json(r).get("id") or "")
            if not GUID.match(iid):
                raise DeployError("The Power BI service did not say which import it started.")
            _step(row["id"], "The Power BI service is importing the file", import_id=iid)
            deadline, misses = time.time() + IMPORT_WAIT_S, 0
            while True:
                time.sleep(POLL_S)
                try:
                    g = c.get(f"{url}/{iid}", headers={"Authorization": f"Bearer {_pbi_token()}"})
                except httpx.HTTPError as e:
                    raise DeployError(f"Could not reach the Power BI service ({e.__class__.__name__}).") from e
                if g.status_code == 404 and misses < 5:          # just started: not listed yet
                    misses += 1
                    continue
                if g.status_code != 200:
                    raise _pbi_error(g, "read the import")
                body = _json(g)
                state = str(body.get("importState") or "")
                if state == "Succeeded":
                    break
                if state == "Failed":
                    raise DeployError(f"The Power BI service could not import the file: {_import_error(body).rstrip('.')}.")
                if time.time() > deadline:
                    raise DeployError(f"The Power BI service was still importing the file after {IMPORT_WAIT_S // 60} minutes. It may "
                                      "still finish: look in the workspace before publishing again.")
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)
    reports = [x for x in body.get("reports") or [] if isinstance(x, dict) and GUID.match(str(x.get("id") or ""))]
    datasets = [x for x in body.get("datasets") or [] if isinstance(x, dict) and GUID.match(str(x.get("id") or ""))]
    rep, ds = (reports or [{}])[0], (datasets or [{}])[0]
    web = rep.get("webUrl") if str(rep.get("webUrl") or "").startswith("https://") else (
        f"https://app.powerbi.com/groups/{ws}/reports/{rep['id']}" if rep.get("id") else None)
    note = None
    if out.get("refreshed") is False:
        note = ("The file holds no data yet: in the service, give the semantic model its warehouse sign-in (its settings, data "
                "source credentials), then refresh it.")
    elif not rep:
        note = "The service made no report from the file."
    return {"item_name": name, "report_id": rep.get("id"), "dataset_id": ds.get("id"), "import_id": iid, "url": web, "note": note}


# ---------------------------------------------------------------- GitHub push of one dashboard

def _push_lock(key: str) -> threading.Lock:
    with _start_lock:
        return _push_locks.setdefault(key, threading.Lock())


def commit_message(st: dict, who: str | None, via: str) -> str:
    title = f"D2D Relay: {st.get('name') or st.get('id')} (v{st.get('approved')})"
    body = ("Pushed automatically when its Power BI file was made." if via == "auto"
            else f"Pushed from D2D Relay by {who}." if who else "Pushed from D2D Relay.")
    return f"{title}\n\n{body}\n"


def _push(row: dict, st: dict, d: Path) -> dict:
    g = _load()["github"]
    tok = token()
    if not g.get("repo") or not tok:
        raise DeployError("Set up the GitHub repository first: an owner adds it and its token under Connections, GitHub.")
    repo, branch, folder = g["repo"], g.get("branch") or DEFAULT_BRANCH, g.get("folder") or DEFAULT_FOLDER
    report = _report_name(d, st)
    files, skipped = pbip_files(d, report)
    dest, item = _dest(row["project_id"], st, g, report)
    data_folder = (st.get("output") or {}).get("data_folder") or f"C:\\D2D Relay Data\\{report}\\data\\"
    tree = commit_files(files, report, item, dest, data_folder, row["project_id"])
    _step(row["id"], "Pushing to GitHub", path=dest, item_name=item, target=_gh_target(g), target_name=repo)
    workflow = None if _workflow_done(g, repo) else workflow_text(branch, folder)
    with _push_lock(f"{db.tenant()}:{repo.lower()}"), GitHub(tok, repo) as gh:
        res = push(gh, branch, dest, tree, commit_message(st, _who(row["user_id"]), row["via"]), workflow)
    if workflow is not None and (res.get("workflow_added") or res.get("workflow_exists")):
        _mark_workflow(repo)            # once per repository: never added again, whatever happens to it there
    notes = []
    if res.get("unchanged") and not res.get("workflow_added"):
        notes.append("Already up to date: nothing changed since the last push.")
    if res.get("created_branch"):
        notes.append(f"The branch {branch} was made from {res['created_branch']}.")
    if res.get("workflow_added"):
        notes.append(f"The deployment workflow was added: {WORKFLOW_PATH}.")
    if res.get("workflow_refused"):
        notes.append(f"The deployment workflow was not added. {res['workflow_refused']} Give the token Workflows: Read and write, "
                     "then push again.")
    if skipped:
        n = len(skipped)
        notes.append(f"Left out {n} item{'s' if n != 1 else ''} that {'are' if n != 1 else 'is'} not part of the project (data, local settings).")
    url = res.get("url") or f"{GITHUB_WEB}/{repo}/commit/{res['commit']}"
    return {"path": dest, "item_name": item, "commit_sha": res["commit"], "url": url, "note": " ".join(notes) or None}


# ---------------------------------------------------------------- runs

def _who(uid: str | None) -> str | None:
    r = db.one("SELECT name FROM users WHERE id = ?", (uid,)) if uid else None
    return r["name"] if r else None


FIELDS = ("step", "target", "target_name", "item_name", "path", "report_id", "dataset_id", "import_id", "url", "commit_sha", "note")


def _step(rid: str, text: str | None, **cols) -> None:
    cols = {k: v for k, v in cols.items() if k in FIELDS}
    sets = ", ".join(["step = ?"] + [f"{k} = ?" for k in cols])
    db.run(f"UPDATE deploy_runs SET {sets} WHERE id = ?", (text, *cols.values(), rid))


def _finish(rid: str, out: dict) -> None:
    cols = {k: v for k, v in out.items() if k in FIELDS and k != "step"}
    sets = ", ".join(["status = 'done'", "step = NULL", "finished = ?", "error = NULL"] + [f"{k} = ?" for k in cols])
    db.run(f"UPDATE deploy_runs SET {sets} WHERE id = ?", (time.time(), *cols.values(), rid))


def _fail(rid: str, text: str) -> None:
    db.run("UPDATE deploy_runs SET status = 'error', step = NULL, finished = ?, error = ? WHERE id = ?", (time.time(), text[:600], rid))


def _activity(pid: str, kind: str, row: dict, ok: bool, text: str) -> None:
    """A line in the dashboard's activity (never the words Power BI project: older notes are reworded as they are shown)."""
    where = row.get("target_name") or ("the workspace" if kind == "powerbi" else "the repository")
    auto = " (automatic)" if row.get("via") == "auto" else ""
    text = text.replace("Power BI project", "project")
    if kind == "powerbi":
        line = f"Published to the Power BI service, workspace {where}{auto}." if ok else f"Publishing to the Power BI service{auto} did not work: {text}"
    else:
        line = (f"Pushed to GitHub, {where}{auto}: {text}" if ok else f"Pushing to GitHub{auto} did not work: {text}")
    try:
        store.log(pid, {"kind": "app", "stage": "pbi", "level": "ok" if ok else "warn", "text": line})
    except Exception:  # noqa: BLE001 - the run is recorded anyway; a dashboard deleted meanwhile has no activity log
        pass


def _work(rid: str, tid: str) -> None:
    """One publish or push, in its own thread, inside its organisation. The activity line and the audit are written
    before the run is marked finished, so whoever sees it finished sees them too."""
    with db.use(tid):
        row = None
        try:
            with _slots:
                row = db.one("SELECT * FROM deploy_runs WHERE id = ?", (rid,))
                if not row or row["status"] != "queued":
                    return
                db.run("UPDATE deploy_runs SET status = 'running', started = ?, step = ? WHERE id = ?", (time.time(), "Starting", rid))
                try:
                    d, st = store.project_dir(row["project_id"]), store.load(row["project_id"])
                except (KeyError, OSError, ValueError):
                    raise DeployError("The dashboard is not there any more.") from None
                out = (_publish if row["kind"] == "powerbi" else _push)(row, st, d)
            fin = {**(db.one("SELECT * FROM deploy_runs WHERE id = ?", (rid,)) or row), **out}
            _activity(fin["project_id"], fin["kind"], fin, True, f"commit {str(fin.get('commit_sha') or '')[:7]}"
                      + (f". {fin['note']}" if fin.get("note") else "."))
            db.audit(f"deploy.{fin['kind']}_done", fin["project_id"], {"run": rid, "target": fin.get("target_name"),
                                                                        "commit": fin.get("commit_sha"), "report": fin.get("report_id")},
                     fin.get("user_id") or "system")
            _finish(rid, out)
        except DeployError as e:
            if row:
                _activity(row["project_id"], row["kind"], row, False, str(e))
                db.audit(f"deploy.{row['kind']}_error", row["project_id"], {"run": rid, "error": str(e)[:300]}, row.get("user_id") or "system")
            _fail(rid, str(e))
        except Exception:  # noqa: BLE001 - a bug: reported (Relay Doctor), and the run says so
            traceback.print_exc()
            _fail(rid, "It stopped on an unexpected error. Try again.")


def _expire(pid: str) -> None:
    """A dashboard's runs that cannot be going any more: opened before this server started (a restart stops them), or
    long overdue."""
    now = time.time()
    for why, before in (("It stopped when D2D Relay restarted. Try again.", _BOOT), ("It took too long and was stopped. Try again.", now - STALE_S)):
        db.run("UPDATE deploy_runs SET status = 'error', step = NULL, finished = ?, error = ? WHERE project_id = ? "
               "AND status IN ('queued', 'running') AND created < ?", (now, why, pid, before))


def _project(pid: str) -> tuple[dict, Path]:
    try:
        d = store.project_dir(pid)
        st = store.load(pid)
    except (KeyError, OSError, ValueError):
        raise DeployError("Project not found", 404) from None
    if (st.get("kind") or "dashboard") != "dashboard":
        raise DeployError("Project not found", 404)
    return st, d


def _ready(kind: str, pid: str, st: dict, d: Path) -> dict:
    """Where a publish or push of this dashboard goes, or DeployError saying what is missing first."""
    if st.get("status") != "done" or not st.get("approved"):
        raise DeployError("Only a published dashboard can be deployed. Publish it first.", 409)
    s = _load()
    if kind == "powerbi":
        p = s["powerbi"]
        if not pbi.settings():
            raise DeployError("Connect Power BI first: an owner enters your organisation's Entra app under Connections, Power BI service.")
        if not p.get("workspace_id"):
            raise DeployError("Choose the Power BI workspace first: an owner picks it under Connections, Power BI service.")
        if not _has_pbix(d, st):
            raise DeployError("This dashboard has no Power BI file yet. Make it, then publish.", 409)
        return {"target": p["workspace_id"], "target_name": p.get("workspace_name")}
    g = s["github"]
    if not g.get("repo") or not token():
        raise DeployError("Set up the GitHub repository first: an owner adds it and its token under Connections, GitHub.")
    if not _report_name(d, st):
        raise DeployError("This dashboard has no Power BI project to push. Make its Power BI file again, then push.", 409)
    return {"target": _gh_target(g), "target_name": g["repo"]}


def start(pid: str, kind: str, u: dict | None, via: str = "manual") -> dict:
    """A publish (kind powerbi) or push (github) of a published dashboard, recorded and started in the background.
    DeployError (with its HTTP status) when it cannot start; one of each kind at a time per dashboard."""
    if kind not in KINDS:
        raise DeployError("Not found", 404)
    st, d = _project(pid)
    t = _ready(kind, pid, st, d)
    uid = (u or {}).get("id")
    with _start_lock:
        _expire(pid)
        if db.one("SELECT id FROM deploy_runs WHERE project_id = ? AND kind = ? AND status IN ('queued', 'running')", (pid, kind)):
            raise DeployError(("A publish" if kind == "powerbi" else "A push") + " of this dashboard is running already.", 409)
        rid = "dp-" + secrets.token_hex(6)
        db.run("INSERT INTO deploy_runs (id, project_id, kind, via, user_id, status, step, created, version, target, target_name) "
               "VALUES (?, ?, ?, ?, ?, 'queued', ?, ?, ?, ?, ?)",
               (rid, pid, kind, via, uid, "Waiting to start", time.time(), st.get("approved"), t["target"], t["target_name"]))
    db.audit(f"deploy.{kind}", pid, {"run": rid, "via": via, "target": t["target_name"]}, uid or "system")
    threading.Thread(target=_work, args=(rid, db.tenant()), name=f"deploy-{rid}", daemon=True).start()
    return _public_run(db.one("SELECT * FROM deploy_runs WHERE id = ?", (rid,)))


def _record_refused(pid: str, kind: str, via: str, text: str) -> None:
    """An automatic publish or push that could not start: recorded, so the dashboard shows why."""
    st = {}
    try:
        st = store.load(pid)
    except (KeyError, OSError, ValueError):
        pass
    now = time.time()
    db.run("INSERT INTO deploy_runs (id, project_id, kind, via, status, created, started, finished, version, error) "
           "VALUES (?, ?, ?, ?, 'error', ?, ?, ?, ?, ?)", ("dp-" + secrets.token_hex(6), pid, kind, via, now, now, now, st.get("approved"), text[:600]))


def after_pbix(pid: str) -> None:
    """The worker calls this as soon as a dashboard's Power BI file is made (in its job, inside the organisation):
    publish it and push it when the organisation switched that on. Starts them in the background and returns at
    once; what cannot start is recorded on the dashboard. Never raises."""
    try:
        s = _load()
        for kind in KINDS:
            if not s[kind].get("auto"):
                continue
            try:
                start(pid, kind, None, "auto")
            except DeployError as e:
                if e.status != 409 or "running already" not in str(e):
                    _record_refused(pid, kind, "auto", str(e))
    except Exception:  # noqa: BLE001 - never into the worker: reported (Relay Doctor), the Power BI file is made anyway
        traceback.print_exc()


def forget(pid: str) -> None:
    """A deleted dashboard's runs (governance.delete_project may call this)."""
    db.run("DELETE FROM deploy_runs WHERE project_id = ?", (pid,))


def _public_run(r: dict) -> dict:
    url = r.get("url")
    return {"id": r["id"], "kind": r["kind"], "via": r["via"], "status": r["status"], "step": r["step"], "created": r["created"],
            "started": r["started"], "finished": r["finished"], "version": r["version"], "by": _who(r["user_id"]),
            "target_name": r["target_name"], "item_name": r["item_name"], "path": r["path"],
            "url": url if isinstance(url, str) and url.startswith("https://") else None,
            "commit": (r["commit_sha"] or "")[:7] or None, "commit_sha": r["commit_sha"], "report_id": r["report_id"],
            "dataset_id": r["dataset_id"], "error": r["error"], "note": r["note"]}


def project_state(pid: str, u: dict) -> dict:
    """A dashboard's deployments for its Overview: the last ones, and whether each kind can run now (and why not)."""
    st, d = _project(pid)
    _expire(pid)
    s = _load()
    rows = db.q("SELECT * FROM deploy_runs WHERE project_id = ? ORDER BY created DESC LIMIT 20", (pid,))
    running = {r["kind"] for r in rows if r["status"] in ("queued", "running")}
    state = {}
    for kind in KINDS:
        try:
            _ready(kind, pid, st, d)
            ready, why = True, None
        except DeployError as e:
            ready, why = False, str(e)
        state[kind] = {"ready": ready and kind not in running, "why": why, "running": kind in running, "auto": bool(s[kind].get("auto"))}
    p, g = s["powerbi"], s["github"]
    state["powerbi"].update(connected=pbi.settings() is not None,
                            workspace={"id": p["workspace_id"], "name": p.get("workspace_name")} if p.get("workspace_id") else None)
    path = None
    if g.get("repo"):
        try:
            report = _report_name(d, st)
            path = _dest(pid, st, g, report)[0] if report else None
        except Exception:  # noqa: BLE001 - only a hint on the screen
            path = None
    state["github"].update(repo=g.get("repo"), branch=g.get("branch") or DEFAULT_BRANCH, folder=g.get("folder") or DEFAULT_FOLDER, path=path)
    return {"runs": [_public_run(r) for r in rows], **state, "published": st.get("status") == "done" and bool(st.get("approved")),
            "can": {"deploy": auth.can_project(u, "publish", db.project(pid)), "manage": orgs.is_owner(u)}}


# ---------------------------------------------------------------- the API

class PowerBiSettings(BaseModel):
    workspace_id: str | None = None
    auto: bool = False


class GitHubSettings(BaseModel):
    repo: str
    branch: str | None = None
    folder: str | None = None
    auto: bool = False
    token: str | None = None


class SettingsBody(BaseModel):
    powerbi: PowerBiSettings | None = None
    github: GitHubSettings | None = None


class GitHubTest(BaseModel):
    repo: str | None = None
    branch: str | None = None
    token: str | None = None


def _u() -> dict:
    u = auth.current.get()
    if not u:
        raise HTTPException(401, "Sign in to D2D Relay.")
    return u


def _need_owner(u: dict) -> None:
    if not orgs.is_owner(u):
        raise HTTPException(403, "Only an owner of the organisation can change the deployment settings.")


def _http(e: DeployError) -> HTTPException:
    return HTTPException(e.status, str(e))


@router.get("/api/deploy/settings")
def get_settings():
    return public(_u())


@router.put("/api/deploy/settings")
def put_settings(body: SettingsBody):
    u = _u()
    _need_owner(u)
    try:
        if body.powerbi is not None:
            save_powerbi(body.powerbi.workspace_id, body.powerbi.auto, u["id"])
        if body.github is not None:
            g = body.github
            save_github(g.repo, g.branch, g.folder, g.auto, g.token, u["id"])
    except DeployError as e:
        raise _http(e)
    return public(u)


@router.delete("/api/deploy/github")
def delete_github():
    u = _u()
    _need_owner(u)
    remove_github(u["id"])
    return public(u)


@router.get("/api/deploy/powerbi/workspaces")
def powerbi_workspaces():
    """The workspaces the organisation's Entra app can see (to pick the one dashboards are published to)."""
    u = _u()
    _need_owner(u)
    if not pbi.settings():
        raise HTTPException(400, "Connect Power BI first: enter your organisation's Entra app under Connections, Power BI service.")
    try:
        ws = pbi.workspaces()
    except pbi.PbiError as e:
        raise HTTPException(400, str(e))
    return {"workspaces": [w for w in ws if str(w.get("type") or "Workspace") not in ("Personal", "AdminWorkspace")]}


@router.post("/api/deploy/github/test")
def github_test(body: GitHubTest | None = None):
    """The repository settings in the form (or the saved ones), with the token typed (or the saved one)."""
    u = _u()
    _need_owner(u)
    body = body or GitHubTest()
    g = _load()["github"]
    try:
        repo = clean_repo(body.repo or g.get("repo"))
        branch = clean_branch(body.branch or g.get("branch"))
        tok = (body.token or "").strip() or token() or ""
        if not tok:
            raise DeployError("Enter a token for the repository: a fine-grained personal access token.")
        if not TOKEN.match(tok):
            raise DeployError("That does not look like a GitHub token. Make a fine-grained personal access token (it starts with github_pat_).")
        out = test_github(repo, branch, tok)
    except DeployError as e:
        db.audit("deploy.github_test", None, {"repo": body.repo or g.get("repo"), "ok": False}, u["id"])
        raise _http(e)
    db.audit("deploy.github_test", None, {"repo": out["repo"], "ok": True}, u["id"])
    return out


@router.get("/api/projects/{pid}/deploys")
def project_deploys(pid: str):
    u = _u()
    try:
        return project_state(pid, u)
    except DeployError as e:
        raise _http(e)


def _deploy(pid: str, kind: str):
    u = _u()
    if not auth.can_project(u, "publish", db.project(pid)):
        raise HTTPException(403, "Your account can view this dashboard, not publish it.")
    try:
        run = start(pid, kind, u, "manual")
        return {"started": run, **project_state(pid, u)}
    except DeployError as e:
        raise _http(e)


@router.post("/api/projects/{pid}/deploy/powerbi")
def deploy_powerbi(pid: str):
    return _deploy(pid, "powerbi")


@router.post("/api/projects/{pid}/deploy/github")
def deploy_github(pid: str):
    return _deploy(pid, "github")


__all__ = ["router", "after_pbix", "forget", "start", "public"]
