"""The repository hosts and trackers AI SDLC talks to (build-plan v2, P16), each behind the same small interface so a
new host is one class: GitHub (the person's own P6 OAuth token), a generic Git-over-HTTP host with the Gitea API
(what the tests exercise), GitLab, Azure DevOps and Bitbucket following their public APIs, and a local path host
for the end-to-end flow (test hooks only). Trackers: Jira through P12's adapter (read a ticket), Azure Boards.

A host does four things: `creds()` for `genbi repo` (user, token - never stored here), `test()` (reachable, sees the
default branch), `open_pr(head, base, title, body)` (a pull / merge request; nothing is ever merged by Relay) and
`pr_state(number)`. Credentials come from the secrets store by name (`sdlc:<repo id>:token`, org scope) or, for
GitHub, from the person's own stored token - a run gets them injected, the page never shows them.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from urllib.parse import quote, urlparse

import httpx

from . import db, secrets_store


class HostError(Exception):
    pass


PROVIDERS = {
    "github": {"label": "GitHub", "signin": "your GitHub account (Settings > GitHub, the same sign-in publishing uses)", "api": "GitHub REST API: repos, git refs, pulls", "url_hint": "https://github.com/org/repo.git"},
    "gitea": {"label": "Gitea / generic Git over HTTP", "signin": "an account and token on the host", "api": "Gitea API v1: repos, branches, pulls (Forgejo and Gogs alike)", "url_hint": "https://git.example.com/org/repo.git"},
    "gitlab": {"label": "GitLab", "signin": "a project or personal access token (api, write_repository)", "api": "GitLab REST API v4: projects, merge_requests", "url_hint": "https://gitlab.com/group/project.git"},
    "azure": {"label": "Azure DevOps", "signin": "a personal access token (Code: read & write)", "api": "Azure DevOps REST 7.1: git/repositories, pullrequests", "url_hint": "https://dev.azure.com/org/project/_git/repo"},
    "bitbucket": {"label": "Bitbucket Cloud", "signin": "an app password (repository: write, pull requests: write)", "api": "Bitbucket API 2.0: repositories, pullrequests", "url_hint": "https://bitbucket.org/workspace/repo.git"},
    "local": {"label": "Local path (tests)", "signin": "none", "api": "a bare repository on this machine; pull requests are recorded next to it", "url_hint": "/data/projects/.sdlc/origin.git"},
}


def secret_name(rid: str) -> str:
    return f"sdlc:{rid}:token"


def _owner_repo(url: str) -> tuple[str, str]:
    p = urlparse(url).path.strip("/")
    p = p[:-4] if p.endswith(".git") else p
    parts = p.split("/")
    if len(parts) < 2:
        raise HostError(f"The URL {url} does not name owner/repository.")
    return parts[-2], parts[-1]


class Host:
    kind = ""

    def __init__(self, repo: dict):
        self.repo = repo
        self.url = repo["url"]
        self.account = repo.get("account") or ""

    def token(self) -> str | None:
        return secrets_store.get("org", secret_name(self.repo["id"]))

    def creds(self) -> tuple[str | None, str | None]:
        return (self.account or None, self.token())

    def api_base(self) -> str:
        if self.repo.get("api_url"):
            return self.repo["api_url"].rstrip("/")
        u = urlparse(self.url)
        return f"{u.scheme}://{u.netloc}"

    def _request(self, method: str, url: str, **kw) -> httpx.Response:
        try:
            r = httpx.request(method, url, timeout=30, **kw)
        except httpx.HTTPError as e:
            raise HostError(f"{PROVIDERS[self.kind]['label']}: cannot reach {urlparse(url).netloc} ({e.__class__.__name__}).") from e
        if r.status_code in (401, 403):
            raise HostError(f"{PROVIDERS[self.kind]['label']} refused the sign-in ({r.status_code}): check the token and its scopes.")
        return r

    def test(self) -> dict:  # pragma: no cover - each host overrides
        raise HostError("Not supported.")

    def open_pr(self, head: str, base: str, title: str, body: str) -> dict:  # pragma: no cover
        raise HostError("Not supported.")

    def pr_state(self, number) -> dict:  # pragma: no cover
        return {"state": "unknown", "merged": None}

    def web_url(self) -> str:
        return self.url[:-4] if self.url.endswith(".git") else self.url


class GitHub(Host):
    kind = "github"

    def token(self) -> str | None:
        return secrets_store.get(f"user:{self.repo['owner_id']}", "github_token")

    def creds(self):
        return ("x-access-token", self.token())

    def api_base(self) -> str:
        from . import publishing
        return publishing.GITHUB_API

    def _h(self) -> dict:
        t = self.token()
        if not t:
            raise HostError("Connect your GitHub account first (Settings > GitHub).")
        return {"Authorization": f"Bearer {t}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}

    def test(self) -> dict:
        o, r = _owner_repo(self.url)
        resp = self._request("GET", f"{self.api_base()}/repos/{o}/{r}", headers=self._h())
        if resp.status_code != 200:
            raise HostError(f"GitHub: {resp.text[:200]}")
        j = resp.json()
        return {"ok": True, "default_branch": j.get("default_branch") or "main", "sees": f"{j.get('full_name')} ({'private' if j.get('private') else 'public'})", "can_push": (j.get("permissions") or {}).get("push", False)}

    def open_pr(self, head, base, title, body) -> dict:
        o, r = _owner_repo(self.url)
        resp = self._request("POST", f"{self.api_base()}/repos/{o}/{r}/pulls", headers=self._h(), json={"title": title, "head": head, "base": base, "body": body})
        if resp.status_code not in (200, 201):
            raise HostError(f"GitHub did not open the pull request: {resp.text[:300]}")
        j = resp.json()
        return {"url": j.get("html_url"), "number": j.get("number"), "id": j.get("id"), "state": j.get("state")}

    def pr_state(self, number) -> dict:
        o, r = _owner_repo(self.url)
        resp = self._request("GET", f"{self.api_base()}/repos/{o}/{r}/pulls/{number}", headers=self._h())
        j = resp.json() if resp.status_code == 200 else {}
        return {"state": j.get("state"), "merged": j.get("merged")}


class Gitea(Host):
    """Generic Git over HTTP with the Gitea API (Forgejo / Gogs share it)."""
    kind = "gitea"

    def _auth(self):
        t = self.token()
        if not t:
            raise HostError("No token is stored for this repository: add the account's token.")
        return (self.account, t)

    def test(self) -> dict:
        o, r = _owner_repo(self.url)
        resp = self._request("GET", f"{self.api_base()}/api/v1/repos/{o}/{r}", auth=self._auth())
        if resp.status_code != 200:
            raise HostError(f"{self.api_base()}: {resp.status_code} {resp.text[:200]}")
        j = resp.json()
        return {"ok": True, "default_branch": j.get("default_branch") or "main", "sees": f"{j.get('full_name')} ({'private' if j.get('private') else 'public'}, {'empty' if j.get('empty') else 'with history'})", "can_push": (j.get("permissions") or {}).get("push", True)}

    def open_pr(self, head, base, title, body) -> dict:
        o, r = _owner_repo(self.url)
        last = None
        for _ in range(8):                               # the host processes a push asynchronously; the branch appears within seconds
            resp = self._request("POST", f"{self.api_base()}/api/v1/repos/{o}/{r}/pulls", auth=self._auth(), json={"head": head, "base": base, "title": title, "body": body})
            if resp.status_code in (200, 201):
                j = resp.json()
                return {"url": j.get("html_url"), "number": j.get("number"), "id": j.get("id"), "state": j.get("state")}
            last = f"{resp.status_code} {resp.text[:200]}"
            if resp.status_code == 409:
                break
            time.sleep(1.5)
        raise HostError(f"The host did not open the pull request: {last}")

    def pr_state(self, number) -> dict:
        o, r = _owner_repo(self.url)
        resp = self._request("GET", f"{self.api_base()}/api/v1/repos/{o}/{r}/pulls/{number}", auth=self._auth())
        j = resp.json() if resp.status_code == 200 else {}
        return {"state": j.get("state"), "merged": j.get("merged")}


class GitLab(Host):
    kind = "gitlab"

    def creds(self):
        return ("oauth2", self.token())

    def _h(self):
        t = self.token()
        if not t:
            raise HostError("No token is stored for this project: add an access token.")
        return {"PRIVATE-TOKEN": t}

    def _project(self) -> str:
        p = urlparse(self.url).path.strip("/")
        return quote(p[:-4] if p.endswith(".git") else p, safe="")

    def test(self) -> dict:
        resp = self._request("GET", f"{self.api_base()}/api/v4/projects/{self._project()}", headers=self._h())
        if resp.status_code != 200:
            raise HostError(f"GitLab: {resp.status_code} {resp.text[:200]}")
        j = resp.json()
        return {"ok": True, "default_branch": j.get("default_branch") or "main", "sees": j.get("path_with_namespace"), "can_push": True}

    def open_pr(self, head, base, title, body) -> dict:
        resp = self._request("POST", f"{self.api_base()}/api/v4/projects/{self._project()}/merge_requests", headers=self._h(), json={"source_branch": head, "target_branch": base, "title": title, "description": body, "remove_source_branch": False})
        if resp.status_code not in (200, 201):
            raise HostError(f"GitLab did not open the merge request: {resp.text[:300]}")
        j = resp.json()
        return {"url": j.get("web_url"), "number": j.get("iid"), "id": j.get("id"), "state": j.get("state")}


class AzureDevOps(Host):
    kind = "azure"

    def creds(self):
        return ("relay", self.token())

    def _auth(self):
        t = self.token()
        if not t:
            raise HostError("No personal access token is stored for this repository.")
        return ("", t)

    def _parts(self) -> tuple[str, str, str, str]:
        u = urlparse(self.url)
        m = re.match(r"^/([^/]+)/([^/]+)/_git/([^/]+)/?$", u.path)
        if not m:
            raise HostError("An Azure DevOps URL looks like https://dev.azure.com/org/project/_git/repo")
        return f"{u.scheme}://{u.netloc}", m.group(1), m.group(2), m.group(3)

    def test(self) -> dict:
        base, org, proj, repo = self._parts()
        resp = self._request("GET", f"{base}/{org}/{proj}/_apis/git/repositories/{repo}?api-version=7.1", auth=self._auth())
        if resp.status_code != 200:
            raise HostError(f"Azure DevOps: {resp.status_code} {resp.text[:200]}")
        j = resp.json()
        return {"ok": True, "default_branch": (j.get("defaultBranch") or "refs/heads/main").replace("refs/heads/", ""), "sees": j.get("name"), "can_push": True}

    def open_pr(self, head, base_branch, title, body) -> dict:
        base, org, proj, repo = self._parts()
        resp = self._request("POST", f"{base}/{org}/{proj}/_apis/git/repositories/{repo}/pullrequests?api-version=7.1", auth=self._auth(),
                             json={"sourceRefName": f"refs/heads/{head}", "targetRefName": f"refs/heads/{base_branch}", "title": title, "description": body})
        if resp.status_code not in (200, 201):
            raise HostError(f"Azure DevOps did not open the pull request: {resp.text[:300]}")
        j = resp.json()
        return {"url": f"{base}/{org}/{proj}/_git/{repo}/pullrequest/{j.get('pullRequestId')}", "number": j.get("pullRequestId"), "id": j.get("pullRequestId"), "state": j.get("status")}


class Bitbucket(Host):
    kind = "bitbucket"

    def _auth(self):
        t = self.token()
        if not t:
            raise HostError("No app password is stored for this repository.")
        return (self.account, t)

    def api_base(self) -> str:
        return self.repo.get("api_url") or "https://api.bitbucket.org"

    def test(self) -> dict:
        ws, slug = _owner_repo(self.url)
        resp = self._request("GET", f"{self.api_base()}/2.0/repositories/{ws}/{slug}", auth=self._auth())
        if resp.status_code != 200:
            raise HostError(f"Bitbucket: {resp.status_code} {resp.text[:200]}")
        j = resp.json()
        return {"ok": True, "default_branch": ((j.get("mainbranch") or {}).get("name")) or "main", "sees": j.get("full_name"), "can_push": True}

    def open_pr(self, head, base, title, body) -> dict:
        ws, slug = _owner_repo(self.url)
        resp = self._request("POST", f"{self.api_base()}/2.0/repositories/{ws}/{slug}/pullrequests", auth=self._auth(),
                             json={"title": title, "description": body, "source": {"branch": {"name": head}}, "destination": {"branch": {"name": base}}})
        if resp.status_code not in (200, 201):
            raise HostError(f"Bitbucket did not open the pull request: {resp.text[:300]}")
        j = resp.json()
        return {"url": ((j.get("links") or {}).get("html") or {}).get("href"), "number": j.get("id"), "id": j.get("id"), "state": j.get("state")}


class Local(Host):
    """A bare repository on a local path (tests, D2D_TEST_HOOKS): pull requests are recorded in relay-pulls.json next to it."""
    kind = "local"

    def creds(self):
        return (None, None)

    def _path(self) -> Path:
        return Path(self.url)

    def test(self) -> dict:
        p = self._path()
        if not (p / "HEAD").exists():
            raise HostError(f"{p} is not a bare repository.")
        from genbi_kit import repo as gk
        branches = gk.ls_remote(str(p))
        return {"ok": True, "default_branch": self.repo.get("default_branch") or "main", "sees": f"{len(branches)} branch(es)", "can_push": True}

    def open_pr(self, head, base, title, body) -> dict:
        f = self._path() / "relay-pulls.json"
        pulls = json.loads(f.read_text(encoding="utf-8")) if f.exists() else []
        n = len(pulls) + 1
        pulls.append({"number": n, "head": head, "base": base, "title": title, "body": body, "state": "open", "merged": False, "opened": time.time()})
        f.write_text(json.dumps(pulls, indent=1), encoding="utf-8")
        return {"url": f"file://{self._path()}#pull-{n}", "number": n, "id": n, "state": "open"}

    def pr_state(self, number) -> dict:
        f = self._path() / "relay-pulls.json"
        pulls = json.loads(f.read_text(encoding="utf-8")) if f.exists() else []
        p = next((x for x in pulls if x["number"] == number), None)
        return {"state": p.get("state") if p else "unknown", "merged": p.get("merged") if p else None}

    def web_url(self) -> str:
        return self.url


HOSTS = {c.kind: c for c in (GitHub, Gitea, GitLab, AzureDevOps, Bitbucket, Local)}


def host_for(repo: dict) -> Host:
    cls = HOSTS.get(repo["provider"])
    if not cls:
        raise HostError(f"Unknown provider {repo['provider']!r}.")
    return cls(repo)


# ------------------------------------------------------------------ trackers

def jira_ticket(source_id: str, key: str) -> dict:
    """A ticket read through P12's Jira adapter (the service desk's own source and credential)."""
    from . import itsm
    s = itsm._src(source_id)
    if s["kind"] != "jira":
        raise HostError("Only a Jira source can be read for a change request here (Freshservice tickets come through Service desk's hand-off).")
    t = itsm.adapter_for(s).issue(key)                   # already in the normalised shape (title, description, url ...)
    return {"key": t.get("key") or key, "title": t.get("title") or "", "description": t.get("description") or "", "url": t.get("url"), "priority": t.get("priority"), "reporter": t.get("reporter"), "source": s["name"]}


def azure_boards_item(org_url: str, project: str, item_id: str, pat: str) -> dict:
    """Azure Boards work item (REST 7.1): title and description; the shape the Jira read returns."""
    url = f"{org_url.rstrip('/')}/{quote(project)}/_apis/wit/workitems/{int(item_id)}?api-version=7.1"
    r = httpx.get(url, auth=("", pat), timeout=30)
    if r.status_code in (401, 403):
        raise HostError("Azure Boards refused the sign-in: check the personal access token (Work items: read).")
    if r.status_code != 200:
        raise HostError(f"Azure Boards: {r.status_code} {r.text[:200]}")
    f = r.json().get("fields") or {}
    desc = re.sub(r"<[^>]+>", " ", f.get("System.Description") or "")
    return {"key": str(item_id), "title": f.get("System.Title") or "", "description": " ".join(desc.split()), "url": f"{org_url.rstrip('/')}/{quote(project)}/_workitems/edit/{int(item_id)}",
            "priority": f.get("Microsoft.VSTS.Common.Priority"), "reporter": (f.get("System.CreatedBy") or {}).get("displayName") if isinstance(f.get("System.CreatedBy"), dict) else f.get("System.CreatedBy"), "source": "Azure Boards"}


def boards_settings(repo_id: str) -> dict:
    return json.loads(db.meta(f"sdlc:boards:{repo_id}") or "{}")


def azure_boards_comment(org_url: str, project: str, item_id: str, text: str, pat: str) -> dict:
    """A comment on an Azure Boards work item (REST 7.1-preview.4 Comments - Add). Only after a named approval."""
    url = f"{org_url.rstrip('/')}/{quote(project)}/_apis/wit/workItems/{int(item_id)}/comments?api-version=7.1-preview.4"
    r = httpx.post(url, json={"text": text}, auth=("", pat), timeout=30)
    if r.status_code in (401, 403):
        raise HostError("Azure Boards refused the sign-in: the personal access token needs Work items: read & write.")
    if r.status_code not in (200, 201):
        raise HostError(f"Azure Boards: {r.status_code} {r.text[:200]}")
    c = r.json() if r.content else {}
    return {"key": str(item_id), "id": str(c.get("id") or ""), "url": f"{org_url.rstrip('/')}/{quote(project)}/_workitems/edit/{int(item_id)}"}


def tracker_read(repo: dict, key: str) -> dict:
    if repo.get("tracker_kind") == "jira" and repo.get("tracker_source"):
        return jira_ticket(repo["tracker_source"], key)
    if repo.get("tracker_kind") == "azure_boards":
        cfg = boards_settings(repo["id"])
        pat = secrets_store.get("org", f"sdlc:{repo['id']}:boards_pat")
        if not (cfg.get("org_url") and cfg.get("project") and pat):
            raise HostError("Azure Boards is not set up on this repository (organisation URL, project and a token).")
        return azure_boards_item(cfg["org_url"], cfg["project"], key, pat)
    raise HostError("This repository has no tracker: give the request in plain words, or pick a Jira source.")
