"""AI SDLC (build-plan v2, P16): bring a Git repository and a tracker; a change request becomes an approved plan,
agent development on a branch, generated tests with security and dependency scans, a reviewer agent and a named
human review, UAT on synthetic data (DemoData), and a release a named approver accepts — one governed AI setup for
the whole team, audited per request.

Journey Request → Plan → Develop → QA → UAT → Release → Run. A request (from a tracker ticket read through P12's
Jira adapter or Azure Boards, from a Service desk hand-off, from an Integration analytics / Data observability
"code fix" work row, from a Self-healing case that needs code, or in plain words) is a folder `output/projects/<id>/`
with kind `sdlc`: request.md, repo/ (the clone — the agent has git only through `genbi repo`, with the credential
injected per run and never written to disk), repo-index.yaml (languages, test and lint commands, CODEOWNERS,
contributing notes, conventions), plan.yaml, tests/qa.json, review.yaml, uat/, release.md.

Jobs in the one sequential lane: `sdlc_plan` (LLM: files touched, risks, tests to add, estimate → checkpoint
`sdlc.plan` for a tech lead), `sdlc_dev` (LLM: small commits on `relay/<id>`; every AI call and file change logged
against the request), `sdlc_qa` (the repository's own test command in a throwaway container of the right runtime —
images present locally only, otherwise recorded as not available; generated tests counted; pip-audit / npm audit
where present; the regex secret scan always), `sdlc_review` (LLM reviewer → findings → checkpoint `sdlc.review` =
the pull request with test results, for a named human reviewer), UAT (synthetic data through the DemoData recipe
runner where the change touches data → checkpoint `sdlc.uat`, business sign-off), `sdlc_release` (after checkpoint
`sdlc.release` with a named approver: the branch is pushed and a pull / merge request opened through the host
adapter — nothing is merged by Relay; a change record and a roll-back note are written). Run links to Self-healing.
Governance: the team's AI setup (provider policy, model, budgets from the existing providers and quotas), the
policies card (which repositories, who may approve each step, required scans) in `sdlc_settings`, audit per request.
"""
from __future__ import annotations

import asyncio
import contextvars
import datetime as dt
import json
import os
import re
import secrets as _secrets
import shutil
import struct
import time
import traceback
from pathlib import Path, PureWindowsPath

import httpx
import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from genbi_kit import datagen
from genbi_kit import repo as gk

from . import auth, checkpoints, db, notify, sdlc_git, sdlc_prompts, secrets_store, store, usage, worker

router = APIRouter()
MODULE = "AI SDLC"
ROUTE = "#/sdlc"
TEST_HOOKS = os.environ.get("D2D_TEST_HOOKS") == "1"
WATCH_EVERY_S = int(os.environ.get("SDLC_WATCH_S", "300"))
QA_TIMEOUT_S = int(os.environ.get("SDLC_QA_TIMEOUT_S", "900"))
KINDS = {"plan": "sdlc.plan", "review": "sdlc.review", "uat": "sdlc.uat", "release": "sdlc.release"}
STAGES = ["request", "plan", "develop", "qa", "uat", "release", "run"]
STAGE_LABEL = {"request": "Request", "plan": "Plan", "develop": "Develop", "qa": "QA", "uat": "UAT", "release": "Release", "run": "Run"}
STAGE_OF = {"waiting": "request", "blocked": "request", "planning": "plan", "plan_review": "plan", "developing": "develop", "qa": "qa", "reviewing": "qa", "review": "qa",
            "uat": "uat", "release_review": "release", "releasing": "release", "released": "run", "closed": "run", "error": "develop"}
STATUS_LABEL = {"waiting": "Waiting to start", "blocked": "Blocked", "planning": "Planning", "plan_review": "Plan — tech lead to approve", "developing": "Developing", "qa": "QA running",
                "reviewing": "Reviewer agent reading", "review": "Review — named reviewer to approve", "uat": "UAT — business sign-off", "release_review": "Release — approver to accept",
                "releasing": "Releasing", "released": "Released — pull request open", "closed": "Closed", "error": "Run failed"}
OPEN = ("waiting", "blocked", "planning", "plan_review", "developing", "qa", "reviewing", "review", "uat", "release_review", "releasing", "error")
TEST_PATH = re.compile(r"(^|/)(tests?|spec|__tests__)(/|$)|(^|/)test_[^/]+\.py$|_test\.(py|go|js|ts)$|\.(test|spec)\.(js|ts|tsx|jsx)$|Test[A-Z]\w*\.java$", re.I)
DATA_PATH = re.compile(r"\.(sql|dtsx|xaml|dbt|yml|yaml)$|(^|/)(models|pipelines|mappings|etl|dags|migrations|sql)/", re.I)
DEFAULT_POLICY = {"repos": [], "approvers": {"plan": [], "review": [], "uat": [], "release": []},
                  "scans": {"secrets": True, "dependencies": True, "tests_must_pass": True}, "never_merge": True, "branch_prefix": "relay/"}
_sched_task = None

db.register_schema("""
CREATE TABLE IF NOT EXISTS sdlc_repos (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, provider TEXT NOT NULL, url TEXT NOT NULL, api_url TEXT, owner_id TEXT NOT NULL, account TEXT,
  default_branch TEXT NOT NULL DEFAULT 'main', tracker_kind TEXT, tracker_source TEXT, index_json TEXT, indexed REAL, status TEXT NOT NULL DEFAULT 'new',
  error TEXT, last_test REAL, created REAL NOT NULL, updated REAL NOT NULL);
CREATE TABLE IF NOT EXISTS sdlc_requests (
  id TEXT PRIMARY KEY, repo_id TEXT, title TEXT NOT NULL, text TEXT, source TEXT NOT NULL, source_id TEXT, ticket_key TEXT, ticket_url TEXT,
  status TEXT NOT NULL DEFAULT 'waiting', stage TEXT NOT NULL DEFAULT 'request', branch TEXT, base TEXT, base_sha TEXT, plan TEXT, qa TEXT, review TEXT, uat TEXT, release TEXT,
  checkpoint_id TEXT, owner_id TEXT, assignees TEXT NOT NULL DEFAULT '{}', note TEXT, work TEXT, created REAL NOT NULL, updated REAL NOT NULL, closed REAL, closed_by TEXT);
CREATE INDEX IF NOT EXISTS sdlc_requests_status ON sdlc_requests (status, updated);
CREATE TABLE IF NOT EXISTS sdlc_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT, request_id TEXT NOT NULL, ts REAL NOT NULL, kind TEXT NOT NULL, text TEXT NOT NULL, detail TEXT, who TEXT);
CREATE INDEX IF NOT EXISTS sdlc_log_req ON sdlc_log (request_id, id);
CREATE TABLE IF NOT EXISTS sdlc_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated REAL, updated_by TEXT);
""")


def _j(s, default):
    try:
        return json.loads(s) if s else default
    except ValueError:
        return default


def _when(t: float | None) -> str:
    return dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%Y-%m-%d %H:%M") if t else "—"


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")[:32] or "change"


# ------------------------------------------------------------------ policy (governance)

def policy() -> dict:
    saved = _j((db.one("SELECT value FROM sdlc_settings WHERE key = 'policy'") or {}).get("value"), {})
    out = json.loads(json.dumps(DEFAULT_POLICY))
    for k, v in saved.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k].update(v)
        else:
            out[k] = v
    return out


def save_policy(body: dict, who: str) -> dict:
    p = policy()
    if "repos" in body:
        p["repos"] = [r for r in (body.get("repos") or []) if db.one("SELECT 1 FROM sdlc_repos WHERE id = ?", (r,))]
    for step in ("plan", "review", "uat", "release"):
        if step in (body.get("approvers") or {}):
            p["approvers"][step] = [u for u in (body["approvers"][step] or []) if db.user(u)]
    for s in ("dependencies", "tests_must_pass"):
        if s in (body.get("scans") or {}):
            p["scans"][s] = bool(body["scans"][s])
    p["scans"]["secrets"] = True                       # always
    p["never_merge"] = True                            # Relay never merges
    db.run("INSERT OR REPLACE INTO sdlc_settings (key, value, updated, updated_by) VALUES ('policy', ?, ?, ?)", (json.dumps(p), time.time(), who))
    db.audit("sdlc.policy", None, p, who)
    return p


def _approver(step: str, r: dict) -> str | None:
    """The named person for a step: the policy's list first, then the request's own assignees, then its owner."""
    for uid in (policy()["approvers"].get(step) or []) + [(_j(r.get("assignees"), {}) if isinstance(r.get("assignees"), str) else (r.get("assignees") or {})).get(step)] + [r.get("owner_id")]:
        if uid and db.user(uid):
            return uid
    return None


# ------------------------------------------------------------------ repositories

def _repo(rid: str) -> dict:
    r = db.one("SELECT * FROM sdlc_repos WHERE id = ?", (rid,))
    if not r:
        raise HTTPException(404, "No such repository.")
    r["index"] = _j(r.get("index_json"), {})
    return r


def repo_public(r: dict) -> dict:
    out = {k: r.get(k) for k in ("id", "name", "provider", "url", "api_url", "owner_id", "account", "default_branch", "tracker_kind", "tracker_source", "indexed", "status", "error", "last_test", "created", "updated")}
    out["provider_label"] = (sdlc_git.PROVIDERS.get(r["provider"]) or {}).get("label") or r["provider"]
    out["has_token"] = secrets_store.get("org", sdlc_git.secret_name(r["id"])) is not None if r["provider"] != "github" else secrets_store.get(f"user:{r['owner_id']}", "github_token") is not None
    idx = r.get("index") if isinstance(r.get("index"), dict) else _j(r.get("index_json"), {})
    out["index"] = {k: idx.get(k) for k in ("main_language", "languages", "test_command", "lint_command", "runtime_image", "ci", "codeowners", "conventions", "files")} if idx else None
    out["requests"] = db.one("SELECT COUNT(*) AS n FROM sdlc_requests WHERE repo_id = ?", (r["id"],))["n"]
    out["allowed"] = not policy()["repos"] or r["id"] in policy()["repos"]
    out["writeback"] = _writeback_grant(r)
    return out


def _writeback_grant(r: dict) -> dict:
    """May the pull request link be written back to the tracker (a comment, each one after a named approval)?"""
    if r.get("tracker_kind") == "jira" and r.get("tracker_source") and "itsm_sources" in db.tables():
        s = db.one("SELECT name, scope, paused FROM itsm_sources WHERE id = ?", (r["tracker_source"],)) or {}
        ok = (s.get("scope") or "read") in ("comment", "write") and not s.get("paused")
        return {"tracker": "Jira", "source": s.get("name"), "allowed": ok,
                "why": None if ok else f"{s.get('name') or 'The Jira source'} is read-only: the Service desk allows comments on it first."}
    if r.get("tracker_kind") == "azure_boards":
        cfg = sdlc_git.boards_settings(r["id"])
        return {"tracker": "Azure Boards", "allowed": bool(cfg.get("write_back")), "why": None if cfg.get("write_back") else "Write-back is off in the repository's Azure Boards settings."}
    return {"tracker": None, "allowed": False, "why": "No tracker on this repository."}


def repos() -> list[dict]:
    return [repo_public(r) for r in db.q("SELECT * FROM sdlc_repos ORDER BY name")]


def save_repo(body: dict, u: dict, rid: str | None = None) -> dict:
    have = _repo(rid) if rid else None
    provider = body.get("provider") or (have or {}).get("provider")
    if provider not in sdlc_git.PROVIDERS or (provider == "local" and not TEST_HOOKS):
        raise HTTPException(400, "Choose the host: " + ", ".join(k for k in sdlc_git.PROVIDERS if k != "local"))
    url = str(body.get("url") or (have or {}).get("url") or "").strip()
    if provider == "local":
        if not url:
            raise HTTPException(400, "Give the path of the bare repository.")
    elif not re.match(r"^https?://[^/\s]+/\S+$", url) or "@" in url.split("://", 1)[1].split("/", 1)[0]:
        raise HTTPException(400, "Give the repository's HTTPS clone URL, without a credential in it.")
    name = str(body.get("name") or (have or {}).get("name") or url.rstrip("/").split("/")[-1].replace(".git", "")).strip()[:120]
    branch = str(body.get("default_branch") or (have or {}).get("default_branch") or "main").strip()[:80]
    tracker_kind = body.get("tracker_kind") if "tracker_kind" in body else (have or {}).get("tracker_kind")
    if tracker_kind not in (None, "", "jira", "azure_boards"):
        raise HTTPException(400, "The tracker is Jira or Azure Boards.")
    tracker_source = body.get("tracker_source") if "tracker_source" in body else (have or {}).get("tracker_source")
    if tracker_kind == "jira" and tracker_source and "itsm_sources" in db.tables() and not db.one("SELECT 1 FROM itsm_sources WHERE id = ? AND kind = 'jira'", (tracker_source,)):
        raise HTTPException(400, "Pick one of the Service desk's Jira sources.")
    now = time.time()
    rid = rid or "repo-" + _secrets.token_hex(4)
    api_url = (body.get("api_url") or (have or {}).get("api_url") or "").strip() or None
    account = (body.get("account") if "account" in body else (have or {}).get("account")) or None
    if have:
        db.run("UPDATE sdlc_repos SET name = ?, provider = ?, url = ?, api_url = ?, account = ?, default_branch = ?, tracker_kind = ?, tracker_source = ?, updated = ? WHERE id = ?",
               (name, provider, url, api_url, account, branch, tracker_kind or None, tracker_source or None, now, rid))
    else:
        db.run("INSERT INTO sdlc_repos (id, name, provider, url, api_url, owner_id, account, default_branch, tracker_kind, tracker_source, status, created, updated) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'new', ?, ?)",
               (rid, name, provider, url, api_url, u["id"], account, branch, tracker_kind or None, tracker_source or None, now, now))
    if body.get("token"):
        secrets_store.put("org", sdlc_git.secret_name(rid), str(body["token"]), u["id"])
    if tracker_kind == "azure_boards":
        if body.get("boards_org_url") or body.get("boards_project") or "boards_write_back" in body:
            cfg = sdlc_git.boards_settings(rid)              # write-back of the pull request link: off unless granted (each comment still approved)
            cfg.update({k: v for k, v in (("org_url", body.get("boards_org_url")), ("project", body.get("boards_project"))) if v})
            if "boards_write_back" in body:
                cfg["write_back"] = bool(body.get("boards_write_back"))
            db.set_meta(f"sdlc:boards:{rid}", json.dumps(cfg))
        if body.get("boards_pat"):
            secrets_store.put("org", f"sdlc:{rid}:boards_pat", str(body["boards_pat"]), u["id"])
    db.audit("sdlc.repo.save", rid, {"name": name, "provider": provider, "url": url, "token": bool(body.get("token"))}, u["id"])
    return repo_public(_repo(rid))


def remove_repo(rid: str, u: dict) -> None:
    r = _repo(rid)
    if db.one("SELECT 1 FROM sdlc_requests WHERE repo_id = ? AND status IN ({})".format(",".join("?" * len(OPEN))), (rid, *OPEN)):
        raise HTTPException(409, "Close or finish its open requests first.")
    secrets_store.delete("org", sdlc_git.secret_name(rid), u["id"])
    secrets_store.delete("org", f"sdlc:{rid}:boards_pat", u["id"])
    db.run("DELETE FROM sdlc_repos WHERE id = ?", (rid,))
    db.audit("sdlc.repo.remove", rid, {"name": r["name"]}, u["id"])


def test_repo(rid: str, who: str) -> dict:
    r = _repo(rid)
    try:
        res = sdlc_git.host_for(r).test()
        db.run("UPDATE sdlc_repos SET status = 'connected', error = NULL, last_test = ?, default_branch = COALESCE(?, default_branch) WHERE id = ?", (time.time(), res.get("default_branch"), rid))
        db.audit("sdlc.repo.test", rid, {"sees": res.get("sees")}, who)
        return {**repo_public(_repo(rid)), "sees": res.get("sees")}
    except sdlc_git.HostError as e:
        db.run("UPDATE sdlc_repos SET status = 'error', error = ?, last_test = ? WHERE id = ?", (str(e)[:300], time.time(), rid))
        raise HTTPException(400, str(e)) from e


# ------------------------------------------------------------------ requests

def _row(rid: str) -> dict:
    r = db.one("SELECT * FROM sdlc_requests WHERE id = ?", (rid,))
    if not r:
        raise HTTPException(404, "No such change request.")
    for k in ("plan", "qa", "review", "uat", "release", "assignees", "work"):
        r[k] = _j(r[k], {} if k != "work" else None)
    return r


def _set(rid: str, **kw) -> None:
    kw["updated"] = time.time()
    cols = ", ".join(f"{k} = ?" for k in kw)
    vals = tuple(json.dumps(v, default=str) if isinstance(v, (dict, list)) else v for v in kw.values())
    db.run(f"UPDATE sdlc_requests SET {cols} WHERE id = ?", vals + (rid,))


def _log(rid: str, kind: str, text: str, detail: dict | None = None, who: str | None = None) -> None:
    db.run("INSERT INTO sdlc_log (request_id, ts, kind, text, detail, who) VALUES (?, ?, ?, ?, ?, ?)", (rid, time.time(), kind, text[:1000], json.dumps(detail, default=str) if detail else None, who or "agent"))


def public(r: dict, with_detail: bool = False) -> dict:
    out = {k: r.get(k) for k in ("id", "repo_id", "title", "text", "source", "source_id", "ticket_key", "ticket_url", "status", "stage", "branch", "base", "base_sha", "plan", "qa", "review", "uat", "release",
                                  "checkpoint_id", "owner_id", "assignees", "note", "work", "created", "updated", "closed", "closed_by")}
    for k in ("plan", "qa", "review", "uat", "release"):      # a step that has not run is null, not {} (the screen shows its "not yet" state)
        out[k] = out[k] or None
    if out["release"] and out["release"].get("who"):          # the screen shows people by name, never their ids
        out["release"] = {**out["release"], "who_name": (db.user(out["release"]["who"]) or {}).get("name")}
    out["status_label"] = STATUS_LABEL.get(r["status"], r["status"])
    out["stage"] = STAGE_OF.get(r["status"], r.get("stage") or "request")
    out["stage_index"] = STAGES.index(out["stage"])
    out["open"] = r["status"] in OPEN
    out["age_s"] = round(time.time() - r["created"])
    out["source_label"] = {"words": "In plain words", "tracker": "Tracker ticket", "itsm_work": "Service desk", "intan_work": "Integration analytics", "observe_work": "Data observability", "heal": "Self-healing"}.get(r["source"], r["source"])
    if r.get("repo_id"):
        rr = db.one("SELECT * FROM sdlc_repos WHERE id = ?", (r["repo_id"],))
        out["repo"] = repo_public(rr) if rr else None
    else:
        out["repo"] = None
    if with_detail:
        out["checkpoint"] = checkpoints.get(r["checkpoint_id"]) if r.get("checkpoint_id") else None
        out["checkpoints"] = [checkpoints._public(c) for c in db.q("SELECT * FROM checkpoints WHERE subject = ? AND kind IN (?, ?, ?, ?) ORDER BY created", (r["id"], *KINDS.values()))]
        names = {u["id"]: u["name"] for u in db.q("SELECT id, name FROM users")}
        out["log"] = [{**x, "detail": _j(x["detail"], None), "who_name": names.get(x.get("who")) or ("Relay agent" if x.get("who") in (None, "agent") else "Relay")}
                      for x in db.q("SELECT * FROM sdlc_log WHERE request_id = ? ORDER BY id DESC LIMIT 200", (r["id"],))]
        out["ai_calls"] = sum(1 for x in out["log"] if x["kind"] == "ai")
        out["file_changes"] = sum(1 for x in out["log"] if x["kind"] == "file")
        d = store.ROOT / r["id"]
        out["files"] = [n for n in ("request.md", "repo-index.yaml", "plan.yaml", "tests/qa.json", "review.yaml", "uat/datagen.yaml", "release.md") if (d / n).exists()]
        try:
            st = store.load(r["id"])
            out["runs"] = st.get("runs") or []
            out["cost_usd"] = round(sum(x.get("cost_usd") or 0 for x in out["runs"]), 2)
            out["folder_status"], out["folder_error"] = st.get("status"), st.get("error")
        except (KeyError, FileNotFoundError, ValueError):
            out["runs"], out["cost_usd"], out["folder_status"], out["folder_error"] = [], 0, None, None
        try:
            out["activity"] = [{k: e.get(k) for k in ("ts", "kind", "stage", "level", "text", "tool", "detail", "who")} for e in store.activity(r["id"], 0, 600)[-40:]]
        except (KeyError, FileNotFoundError):
            out["activity"] = []
        clone = d / "repo"
        out["commits"], out["changed_files"] = [], []
        if (clone / ".git").exists() and r.get("base_sha"):
            try:
                out["commits"] = gk.log(clone, 50, since=r["base_sha"])
                out["changed_files"] = gk.changed_files(clone, r["base_sha"], "HEAD")
            except Exception:  # noqa: BLE001
                pass
        out["heal_cases"] = []
        if "heal_cases" in db.tables() and r.get("repo_id"):
            out["heal_cases"] = [{"id": c["id"], "title": c["title"], "status": c["status"]} for c in db.q("SELECT id, title, status FROM heal_cases WHERE work LIKE ? OR applied LIKE ? ORDER BY updated DESC LIMIT 5", (f'%{r["id"]}%', f'%{r["id"]}%'))]
    return out


def _folder(rid: str, title: str, text: str, who: str, extra: str = "") -> Path:
    d = store.ROOT / rid
    for sub in ("tests", "uat"):
        (d / sub).mkdir(parents=True, exist_ok=True)
    store.save({"id": rid, "kind": "sdlc", "name": title, "prompt": text[:240], "model": worker.DEFAULT_MODEL, "status": "waiting", "created": time.time(), "versions": [], "runs": [], "job": None, "error": None})
    db.add_project(rid, who if db.user(who) else db.ADMIN_ID)
    (d / "request.md").write_text(f"# Change request: {title}\n\n## What is asked ({_when(time.time())})\n\n{text}\n{extra}\n\n"
                                  "Rules: the agent works on a clone in repo/ through `genbi repo` only, never pushes; QA runs the repository's tests in a throwaway container; "
                                  "a tech lead approves the plan, a named reviewer the pull request, business users UAT on synthetic data, a named approver the release. "
                                  "Relay opens the pull request; it never merges.\n", encoding="utf-8")
    return d


def create_request(who: str, repo_id: str | None, title: str, text: str, source: str = "words", source_id: str | None = None, ticket: dict | None = None,
                   work: dict | None = None, assignees: dict | None = None, start: bool = True) -> dict:
    title = " ".join((title or "").split())[:200]
    text = (text or "").strip()
    if len(title) < 4:
        raise HTTPException(400, "Say what should change, in a few words.")
    if repo_id:
        r = _repo(repo_id)
        if policy()["repos"] and repo_id not in policy()["repos"]:
            raise HTTPException(403, f"The policy does not allow AI SDLC on {r['name']}: an Admin adds it under Policies.")
    rid = "sdlc-" + _slug(title) + "-" + _secrets.token_hex(2)
    extra = ""
    if ticket:
        extra = f"\n## Ticket {ticket.get('key')} ({ticket.get('source') or 'tracker'})\n\n{ticket.get('title') or ''}\n\n{(ticket.get('description') or '')[:6000]}\n" + (f"\nPriority: {ticket.get('priority')} · reporter: {ticket.get('reporter')}\n" if ticket.get("priority") or ticket.get("reporter") else "")
    _folder(rid, title, text or (ticket or {}).get("description") or title, who, extra)
    now = time.time()
    db.run("INSERT INTO sdlc_requests (id, repo_id, title, text, source, source_id, ticket_key, ticket_url, status, stage, owner_id, assignees, work, created, updated) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'waiting', 'request', ?, ?, ?, ?, ?)",
           (rid, repo_id, title, (text or "")[:6000], source, source_id, (ticket or {}).get("key"), (ticket or {}).get("url"), who, json.dumps(assignees or {}), json.dumps(work) if work else None, now, now))
    _log(rid, "request", f"Change request opened from {source}" + (f" (ticket {ticket['key']})" if ticket else ""), {"repo": repo_id, "source_id": source_id}, who)
    db.audit("sdlc.request.opened", rid, {"repo": repo_id, "source": source, "source_id": source_id, "title": title[:120]}, who)
    if repo_id and start:
        try:
            worker.enqueue(rid, "sdlc_plan")
            _set(rid, status="planning", stage="plan")
        except Exception as e:  # noqa: BLE001
            _set(rid, status="blocked", note=f"Planning could not start: {str(e)[:200]}")
    return _row(rid)


def start_request(rid: str, repo_id: str, who: str) -> dict:
    r = _row(rid)
    if r["status"] not in ("waiting", "blocked", "error"):
        raise HTTPException(409, f"This request is already {r['status_label'] if 'status_label' in r else r['status']}.")
    repo = _repo(repo_id)
    if policy()["repos"] and repo_id not in policy()["repos"]:
        raise HTTPException(403, f"The policy does not allow AI SDLC on {repo['name']}.")
    _set(rid, repo_id=repo_id, note=None)
    kind = {"request": "sdlc_plan", "plan": "sdlc_plan", "develop": "sdlc_dev", "qa": "sdlc_qa", "release": "sdlc_release"}.get(STAGE_OF.get(r["status"], "request"), "sdlc_plan")
    if r["status"] == "error":
        kind = {"plan": "sdlc_plan", "develop": "sdlc_dev", "qa": "sdlc_qa", "release": "sdlc_release"}.get(r.get("stage"), "sdlc_plan")
    st = worker.enqueue(rid, kind, who=who)
    _set(rid, status={"sdlc_plan": "planning", "sdlc_dev": "developing", "sdlc_qa": "qa", "sdlc_release": "releasing"}[kind], stage={"sdlc_plan": "plan", "sdlc_dev": "develop", "sdlc_qa": "qa", "sdlc_release": "release"}[kind])
    _log(rid, "decision", f"Started on {repo['name']} ({kind})", None, who)
    db.audit("sdlc.request.started", rid, {"repo": repo_id, "job": kind}, who)
    return {"job": st.get("job"), "request": public(_row(rid), with_detail=True)}


def request_from_heal(case: dict, who: str) -> dict:
    """A Self-healing case whose fix needs code becomes a request waiting for a repository."""
    diag = case.get("diagnosis") or {}
    text = f"{case.get('what') or ''}\n\nSelf-healing diagnosis: {diag.get('cause') or ''}\n\nProposed: {(diag.get('fix') or {}).get('text') or ''}\n\nEvidence is in the case folder {case['id']} (evidence/)."
    return create_request(who, None, f"Code fix: {case['title']}"[:200], text, source="heal", source_id=case["id"], work={"module": "heal", "table": "heal_cases", "id": case["id"]}, start=False)


def watch_work() -> list[str]:
    """The sdlc rows P12 / P13 / P14 left become requests waiting for a repository (once each)."""
    opened = []
    tables = set(db.tables())

    def have(source, sid):
        return db.one("SELECT 1 FROM sdlc_requests WHERE source = ? AND source_id = ?", (source, sid))
    if "intan_work" in tables:
        for w in db.q("SELECT w.*, i.name AS iname, i.kind AS ikind, i.via AS via FROM intan_work w JOIN intan_integrations i ON i.id = w.integration_id WHERE w.kind = 'sdlc' AND w.status = 'drafted'"):
            if have("intan_work", w["id"]):
                continue
            b = _j(w["body"], {})
            r = create_request(w.get("approved_by") or db.ADMIN_ID, None, w["title"], f"{b.get('summary') or ''}\n\nCause: {b.get('cause') or ''}\n\nIntegration: {w['ikind']} {w['iname']} on {w.get('via') or 'its platform'}", source="intan_work", source_id=w["id"], work={"module": "intan", "table": "intan_work", "id": w["id"]}, start=False)
            opened.append(r["id"])
    if "observe_work" in tables:
        for w in db.q("SELECT w.*, i.title AS ititle, i.cause AS icause, i.check_kind FROM observe_work w JOIN observe_incidents i ON i.id = w.incident_id WHERE w.kind = 'sdlc' AND w.status = 'approved'"):
            if have("observe_work", w["id"]):
                continue
            b = _j(w["body"], {})
            r = create_request(w.get("approved_by") or db.ADMIN_ID, None, w["title"], f"{b.get('summary') or w['ititle']}\n\nCause: {b.get('cause') or w.get('icause') or ''}\n\nCheck: {w['check_kind']}", source="observe_work", source_id=w["id"], work={"module": "observe", "table": "observe_work", "id": w["id"]}, start=False)
            opened.append(r["id"])
    if "itsm_work" in tables:
        for w in db.q("SELECT w.*, g.title AS gtitle, g.summary AS gsummary, g.category AS gcat FROM itsm_work w JOIN itsm_groups g ON g.id = w.group_id WHERE w.target = 'sdlc' AND w.status = 'recorded'"):
            if have("itsm_work", w["id"]):
                continue
            keys = [t["key"] for t in db.q("SELECT key FROM itsm_tickets WHERE group_id = ? ORDER BY created", (w["group_id"],))]
            r = create_request(w.get("who") or db.ADMIN_ID, None, w["gtitle"] or "Service desk change", f"{w.get('gsummary') or ''}\n\nTickets: {', '.join(keys)}\n\n{w.get('note') or ''}", source="itsm_work", source_id=w["id"], ticket={"key": keys[0], "source": "Service desk", "title": w["gtitle"], "description": w.get("gsummary") or ""} if keys else None, work={"module": "itsm", "table": "itsm_work", "id": w["id"]}, start=False)
            opened.append(r["id"])
    return opened


def _mark_work(r: dict, status: str, who: str, link: str | None = None) -> None:
    w = r.get("work") or {}
    if not w:
        return
    try:
        if w["table"] == "intan_work":
            db.run("UPDATE intan_work SET status = ? WHERE id = ?", (status, w["id"]))
        elif w["table"] == "observe_work":
            db.run("UPDATE observe_work SET status = ?, note = COALESCE(?, note) WHERE id = ?", (status, f"AI SDLC request {r['id']}: {status}", w["id"]))
        elif w["table"] == "itsm_work":
            db.run("UPDATE itsm_work SET status = ?, link = COALESCE(?, link), note = COALESCE(note, '') || ? WHERE id = ?", (status, link, f" AI SDLC request {r['id']}: {status}.", w["id"]))
        elif w["table"] == "heal_cases":
            db.run("UPDATE heal_cases SET note = ?, updated = ? WHERE id = ?", (f"AI SDLC request {r['id']}: {status}", time.time(), w["id"]))
        db.audit("sdlc.work", w["id"], {"table": w["table"], "status": status, "request": r["id"]}, who)
    except Exception:  # noqa: BLE001
        traceback.print_exc()


# ------------------------------------------------------------------ the clone, the index, the credential

def _clone_dir(rid: str) -> Path:
    return store.ROOT / rid / "repo"


def _ensure_clone(r: dict, repo_row: dict) -> Path:
    clone = _clone_dir(r["id"])
    host = sdlc_git.host_for(repo_row)
    if not (clone / ".git").exists():
        shutil.rmtree(clone, ignore_errors=True)
        info = gk.clone(repo_row["url"], clone, repo_row.get("default_branch") or None, None, host.creds())
        _log(r["id"], "git", f"Cloned {repo_row['name']} ({info['branch']} @ {info['head'][:8]}) into repo/", {"branch": info["branch"], "head": info["head"]})
        if not r.get("base_sha"):
            _set(r["id"], base=info["branch"], base_sha=info["head"])
    return clone


def _index(r: dict, repo_row: dict, clone: Path) -> dict:
    idx = gk.write_index(clone, store.ROOT / r["id"] / "repo-index.yaml")
    db.run("UPDATE sdlc_repos SET index_json = ?, indexed = ?, default_branch = COALESCE(?, default_branch) WHERE id = ?", (json.dumps({k: v for k, v in idx.items() if k != "file"}), time.time(), idx.get("branch"), repo_row["id"]))
    _log(r["id"], "index", f"Indexed {idx['files']} files: {idx.get('main_language') or 'no code'} · test: {idx.get('test_command') or 'not found'} · lint: {idx.get('lint_command') or 'none'} · CODEOWNERS: {len(idx.get('codeowners') or [])} rule(s)",
         {k: idx.get(k) for k in ("languages", "test_command", "lint_command", "runtime_image", "ci", "conventions")})
    return idx


def _run_env(repo_row: dict) -> dict:
    user, token = sdlc_git.host_for(repo_row).creds()
    return {"GENBI_REPO_USER": user or "", "GENBI_REPO_TOKEN": token or ""}


def _log_run(rid: str, stage: str, res: dict) -> None:
    _log(rid, "ai", f"{stage}: {res.get('turns') or 0} turns · ${(res.get('cost_usd') or 0):.2f} · {res.get('model') or ''}" + ("" if res.get("ok", True) else " · failed"),
         {k: res.get(k) for k in ("model", "turns", "cost_usd", "duration_ms", "session_id", "ok")})


# ------------------------------------------------------------------ Plan

def load_yaml(p: Path) -> dict:
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def check_plan(d: Path) -> list[str]:
    p = d / "plan.yaml"
    if not p.exists():
        return ["plan.yaml was not written"]
    try:
        y = load_yaml(p)
    except Exception as e:  # noqa: BLE001
        return [f"plan.yaml does not parse: {str(e).splitlines()[0]}"]
    out = []
    if not isinstance(y, dict):
        return ["plan.yaml must be a mapping"]
    if not str(y.get("summary") or "").strip():
        out.append("summary is missing")
    files = y.get("files")
    if not isinstance(files, list) or not files or not all(isinstance(f, dict) and f.get("path") and f.get("change") for f in files):
        out.append("files must list at least one {path, change, kind}")
    else:
        for f in files:
            if f.get("kind", "modify") not in ("modify", "add", "delete"):
                out.append(f"files[{f.get('path')}].kind must be modify, add or delete")
            elif f.get("kind", "modify") != "add" and not (d / "repo" / str(f["path"])).exists():
                out.append(f"files[{f.get('path')}] does not exist in repo/ (kind add for a new file)")
    if not isinstance(y.get("tests"), list) or not y["tests"]:
        out.append("tests must list at least one test to add or change")
    if not isinstance(y.get("risks"), list):
        out.append("risks must be a list (say 'none found' with the reason if so)")
    if not isinstance(y.get("steps"), list) or not y["steps"]:
        out.append("steps must list the intended commits")
    if not isinstance(y.get("uat"), dict) or not (y["uat"].get("steps") or []):
        out.append("uat.steps must list how a business user checks it")
    if not str(y.get("rollback") or "").strip():
        out.append("rollback is missing")
    return out


def planned(rid: str, plan: dict, summary: str = "") -> dict:
    r = _row(rid)
    _set(rid, status="plan_review", stage="plan", plan=plan, note=None)
    checkpoints.withdraw(KINDS["plan"], rid, who="system")
    files, risks, tests = plan.get("files") or [], plan.get("risks") or [], plan.get("tests") or []
    est = plan.get("estimate") or {}
    ev = {"summary": plan.get("summary") or "", "items": [f"{f.get('kind', 'modify')} {f.get('path')}: {f.get('change')}" for f in files[:8]] + [f"Risk: {x.get('risk')} — {x.get('mitigation')}" for x in risks[:4]] + [f"Test: {t.get('name')} ({t.get('file')})" for t in tests[:4]],
          "counts": {"files": len(files), "risks": len(risks), "tests": len(tests), "hours": est.get("hours") or "—"}, "plan": plan, "rows": files,
          "request": {"id": rid, "title": r["title"], "source": r["source"], "ticket": r.get("ticket_key")}, "touches_data": bool(plan.get("touches_data"))}
    cp = checkpoints.open(KINDS["plan"], rid, MODULE, f"Plan: {r['title']}", "plan", ev, link=f"{ROUTE}/{rid}", assignee=_approver("plan", r), agent="Relay", opened_by="agent")
    _set(rid, checkpoint_id=cp["id"])
    _log(rid, "plan", f"Plan ready: {len(files)} file(s), {len(tests)} test(s), {len(risks)} risk(s), estimate {est.get('hours') or '—'} h — waiting for the tech lead", {"summary": (plan.get("summary") or "")[:300]})
    worker.app_note(rid, "sdlc_plan", f"Plan ready: {plan.get('summary') or ''} Waiting for the tech lead's approval.", "ok")
    db.audit("sdlc.planned", rid, {"files": len(files), "tests": len(tests), "risks": len(risks), "summary": summary[:200]}, "agent")
    return _row(rid)


async def _plan_job(pid: str, args: dict) -> None:
    r = _row(pid)
    repo_row = _repo(r["repo_id"])
    d = store.ROOT / pid
    _set(pid, status="planning", stage="plan")
    worker.app_note(pid, "sdlc_plan", "Relay is cloning the repository, indexing its conventions and planning the change." if not args.get("correction") else "Relay is planning again with the tech lead's note.")
    try:
        clone = await asyncio.to_thread(_ensure_clone, r, repo_row)
        await asyncio.to_thread(_index, r, repo_row, clone)
        r = _row(pid)
        if args.get("correction"):
            store.note(pid, "Plan sent back", args["correction"])
        res = await worker.agent(pid, "sdlc_plan", sdlc_prompts.plan(r, args.get("correction")), worker.TURNS["sdlc_plan"], "plan", system=sdlc_prompts.SYSTEM)
        _log_run(pid, "plan", res)
        for attempt in range(worker.FIX_ROUNDS + 1):
            problems = await asyncio.to_thread(check_plan, d)
            if not problems:
                break
            if attempt == worker.FIX_ROUNDS:
                raise RuntimeError(f"plan.yaml still has {len(problems)} problem(s): " + "; ".join(problems[:4]))
            worker.app_note(pid, "sdlc_plan", f"The check found {len(problems)} problem(s) in plan.yaml — Relay is fixing them.", "warn", problems)
            res = await worker.agent(pid, "sdlc_plan", sdlc_prompts.fix("plan.yaml", problems), worker.TURNS["fix"], "plan", resume=res.get("session_id"), system=sdlc_prompts.SYSTEM)
            _log_run(pid, "plan fix", res)
        planned(pid, load_yaml(d / "plan.yaml"), res.get("text") or "")
        store.update(pid, status="plan_review", job=None, error=None)
    except Exception as e:
        _set(pid, status="error", stage="plan", note=str(e)[:300])
        _log(pid, "error", f"Plan failed: {str(e)[:300]}")
        raise


worker.register_job("sdlc_plan", _plan_job, status="planning", done="Plan ready — the tech lead approves it", llm=True, turns=80, timeout_s=2400)


# ------------------------------------------------------------------ Develop

def check_dev(r: dict, clone: Path) -> list[str]:
    out = []
    st = gk.status(clone)
    if st["branch"] != r["branch"]:
        out.append(f"the clone is on branch {st['branch']}, not {r['branch']} — run `genbi repo branch {r['branch']}`")
    if st["unstaged"] or st["untracked"] or any(st["staged"].values()):
        out.append("changes are not committed: run `genbi repo status` and `genbi repo commit -m \"...\" <paths>` for each change")
    commits = gk.log(clone, 50, since=r["base_sha"]) if r.get("base_sha") else []
    if not commits:
        out.append(f"no commit on {r['branch']} yet: make the change and commit it with `genbi repo commit`")
    plan = r.get("plan") or {}
    if plan.get("tests") and r.get("base_sha"):
        files = {f["path"] for f in gk.changed_files(clone, r["base_sha"], "HEAD")}
        if not any(TEST_PATH.search(p) for p in files):
            out.append("no test file changed or added: add the tests plan.yaml names")
    if (bool(plan.get("touches_data")) or bool((plan.get("uat") or {}).get("datagen"))) and not (store.ROOT / r["id"] / "uat" / "datagen.yaml").exists():
        out.append("uat/datagen.yaml is missing: the change touches data, so write the synthetic-data recipe for UAT")
    return out


def developed(rid: str, who: str = "agent", review_ready: bool = False) -> dict:
    r = _row(rid)
    clone = _clone_dir(rid)
    st = gk.status(clone)
    if st["unstaged"] or st["untracked"]:
        try:
            c = gk.commit(clone, "Relay: changes the agent left uncommitted (committed by the app so nothing is lost)")
            _log(rid, "commit", f"{c['commit'][:8]} {c['message']} ({c['files']} file(s))", c, "app")
        except gk.RepoError:
            pass
    commits = gk.log(clone, 50, since=r["base_sha"]) if r.get("base_sha") else []
    files = gk.changed_files(clone, r["base_sha"], "HEAD") if r.get("base_sha") else []
    for c in reversed(commits):
        if not db.one("SELECT 1 FROM sdlc_log WHERE request_id = ? AND kind = 'commit' AND text LIKE ?", (rid, c["sha"][:8] + "%")):
            _log(rid, "commit", f"{c['sha'][:8]} {c['message'].splitlines()[0][:140]}", c, "agent")
    for f in files:
        if not db.one("SELECT 1 FROM sdlc_log WHERE request_id = ? AND kind = 'file' AND text = ?", (rid, f"{f['status']} {f['path']}")):
            _log(rid, "file", f"{f['status']} {f['path']}", f, "agent")
    _set(rid, status="qa", stage="qa", note=None)
    worker.app_note(rid, "sdlc_dev", f"Developed on {r['branch']}: {len(commits)} commit(s), {len(files)} file(s) changed. QA starts next.", "ok")
    db.audit("sdlc.developed", rid, {"commits": len(commits), "files": len(files)}, who)
    worker.enqueue(rid, "sdlc_qa", review_ready=review_ready)
    return _row(rid)


async def _dev_job(pid: str, args: dict) -> None:
    r = _row(pid)
    repo_row = _repo(r["repo_id"])
    _set(pid, status="developing", stage="develop")
    worker.app_note(pid, "sdlc_dev", "Relay is developing the approved plan on a branch, in small commits." if not args.get("correction") else "Relay is correcting the change with the reviewer's note.")
    try:
        clone = await asyncio.to_thread(_ensure_clone, r, repo_row)
        r = _row(pid)
        branch = r.get("branch") or f"{policy().get('branch_prefix') or 'relay/'}{pid}"
        b = await asyncio.to_thread(gk.branch, clone, branch)
        if b["created"]:
            _log(pid, "git", f"Branch {branch} created from {r.get('base')} @ {(r.get('base_sha') or '')[:8]}", b)
        _set(pid, branch=branch)
        r = _row(pid)
        if args.get("correction"):
            store.note(pid, "Sent back", args["correction"])
        idx = _repo(r["repo_id"])["index"]
        res = await worker.agent(pid, "sdlc_dev", sdlc_prompts.develop(r, idx, r["plan"] or {}, args.get("correction")), worker.TURNS["sdlc_dev"], "develop", system=sdlc_prompts.SYSTEM, env=_run_env(repo_row))
        _log_run(pid, "develop", res)
        for attempt in range(worker.FIX_ROUNDS + 1):
            problems = await asyncio.to_thread(check_dev, _row(pid), clone)
            if not problems:
                break
            if attempt == worker.FIX_ROUNDS:
                if any(p.startswith("no commit") for p in problems):
                    raise RuntimeError("The agent made no commit on the branch: " + "; ".join(problems[:3]))
                break                                   # uncommitted work is committed by the app in developed(); the rest is for the reviewer
            worker.app_note(pid, "sdlc_dev", f"The check found {len(problems)} problem(s) — Relay is fixing them.", "warn", problems)
            res = await worker.agent(pid, "sdlc_dev", sdlc_prompts.fix("the branch", problems), worker.TURNS["fix"], "develop", resume=res.get("session_id"), system=sdlc_prompts.SYSTEM, env=_run_env(repo_row))
            _log_run(pid, "develop fix", res)
        developed(pid)                                  # queues sdlc_qa: the folder's queued job must stay as enqueue left it
    except Exception as e:
        _set(pid, status="error", stage="develop", note=str(e)[:300])
        _log(pid, "error", f"Develop failed: {str(e)[:300]}")
        raise


worker.register_job("sdlc_dev", _dev_job, status="developing", done="Developed on a branch — QA runs next", llm=True, turns=150, timeout_s=3600)


# ------------------------------------------------------------------ QA: tests in a throwaway container, scans, generated tests

def _docker():
    sock = os.environ.get("D2D_DOCKER_SOCK", "/var/run/docker.sock")
    if not os.path.exists(sock):
        return None
    return httpx.Client(transport=httpx.HTTPTransport(uds=sock), base_url="http://docker", timeout=60)


def _bind(pid: str, sub: str) -> tuple[str, str] | None:
    vol = os.environ.get("D2D_PROJECTS_VOLUME")
    host = os.environ.get("HOST_PROJECTS_DIR")
    if vol:
        return f"{vol}:/data/projects", f"/data/projects/{pid}/{sub}"
    if host:
        base = str(PureWindowsPath(host) / pid / sub).replace("\\", "/") if "\\" in host or re.match(r"^[A-Za-z]:", host) else f"{host.rstrip('/')}/{pid}/{sub}"
        return f"{base}:/work", "/work"
    return None


def _demux(raw: bytes) -> str:
    out, i = [], 0
    while i + 8 <= len(raw):
        _, n = struct.unpack(">BxxxI", raw[i:i + 8])
        out.append(raw[i + 8:i + 8 + n].decode("utf-8", errors="replace"))
        i += 8 + n
    return "".join(out) if out else raw.decode("utf-8", errors="replace")


def container_run(image: str, cmd: str, pid: str, sub: str = "repo", env: dict | None = None, timeout: int = QA_TIMEOUT_S, label: str = "tests") -> dict:
    """The repository's own command in a throwaway container of its runtime: no network, the clone mounted, the
    image used only if it is present locally (Relay never pulls on its own)."""
    api = _docker()
    if api is None:
        return {"status": "skipped", "note": "no container runtime is available to this web app (no Docker socket): not run", "image": image, "cmd": cmd}
    if api.get(f"/images/{image}/json").status_code != 200:
        return {"status": "skipped", "note": f"runtime image {image} not available locally — pull it on the host to run this step; Relay never pulls images on its own", "image": image, "cmd": cmd}
    bind = _bind(pid, sub)
    if not bind:
        return {"status": "skipped", "note": "the projects folder has no host path for a bind mount (set HOST_PROJECTS_DIR or D2D_PROJECTS_VOLUME)", "image": image, "cmd": cmd}
    body = {"Image": image, "Cmd": ["sh", "-c", cmd], "WorkingDir": bind[1], "Env": [f"{k}={v}" for k, v in (env or {}).items()] + ["PYTHONDONTWRITEBYTECODE=1", "CI=1", "npm_config_update_notifier=false"],
            "Labels": {"relay.sdlc": pid, "relay.step": label}, "HostConfig": {"Binds": [bind[0]], "NetworkMode": "none", "Memory": 2 * 1024 ** 3, "NanoCpus": int(2e9), "RestartPolicy": {"Name": "no"}}}
    started = time.time()
    r = api.post("/containers/create", params={"name": f"relay-sdlc-{pid[-12:]}-{label}-{_secrets.token_hex(2)}"}, json=body)
    if r.status_code not in (200, 201):
        return {"status": "error", "note": f"could not create the container: {r.text[:200]}", "image": image, "cmd": cmd}
    cid = r.json()["Id"]
    try:
        api.post(f"/containers/{cid}/start")
        try:
            w = api.post(f"/containers/{cid}/wait", params={"condition": "not-running"}, timeout=timeout + 15)
            code = (w.json() or {}).get("StatusCode", 1)
            timed_out = False
        except httpx.ReadTimeout:
            api.post(f"/containers/{cid}/kill")
            code, timed_out = 124, True
        logs = _demux(api.get(f"/containers/{cid}/logs", params={"stdout": "1", "stderr": "1", "tail": "400"}).content)
    finally:
        api.delete(f"/containers/{cid}", params={"force": "true"})
    tail = logs[-6000:]
    return {"status": "timeout" if timed_out else ("pass" if code == 0 else "fail"), "exit": code, "output": tail, "seconds": round(time.time() - started, 1), "image": image, "cmd": cmd,
            "note": f"timed out after {timeout} s" if timed_out else None}


def run_qa(rid: str) -> dict:
    r = _row(rid)
    repo_row = _repo(r["repo_id"])
    idx = repo_row["index"] or {}
    clone = _clone_dir(rid)
    d = store.ROOT / rid
    files = gk.changed_files(clone, r["base_sha"], "HEAD") if r.get("base_sha") else []
    commits = gk.log(clone, 50, since=r["base_sha"]) if r.get("base_sha") else []
    qa = {"started": time.time(), "branch": r.get("branch"), "base": r.get("base"), "files": files, "commits": [{"sha": c["sha"][:8], "message": c["message"].splitlines()[0][:120]} for c in commits],
          "generated_tests": [f["path"] for f in files if TEST_PATH.search(f["path"])]}
    pol = policy()["scans"]
    image, test_cmd = idx.get("runtime_image"), idx.get("test_command")
    if not test_cmd:
        qa["tests"] = {"status": "skipped", "note": "no test command found in the repository (no pytest / unittest / npm test / mvn / go test marker)"}
    elif not image:
        qa["tests"] = {"status": "skipped", "note": "no runtime image is known for this repository's main language"}
    else:
        qa["tests"] = container_run(image, test_cmd, rid, "repo", label="tests")
    _log(rid, "test", f"Tests ({test_cmd or 'none'}): {qa['tests']['status']}" + (f" — {qa['tests'].get('note')}" if qa["tests"].get("note") else f" in {qa['tests'].get('seconds')} s"), {k: v for k, v in qa["tests"].items() if k != "output"})
    hits = gk.scan_secrets(clone)
    changed = {f["path"] for f in files}
    qa["secret_scan"] = {"status": "fail" if hits else "pass", "findings": hits[:50], "in_change": [h for h in hits if h["file"] in changed][:50], "scanned": "whole tree"}
    _log(rid, "scan", f"Secret scan: {len(hits)} finding(s)" + (f", {len(qa['secret_scan']['in_change'])} in this change" if hits else ""), {"findings": hits[:20]})
    if pol.get("dependencies"):
        lang = idx.get("main_language")
        if lang == "Python" and (clone / "requirements.txt").exists() and image:
            qa["dependency_scan"] = container_run(image, "python -m pip_audit -r requirements.txt 2>&1 || (python -c \"import pip_audit\" 2>/dev/null || echo 'pip-audit not installed in the runtime image')", rid, "repo", label="deps")
            qa["dependency_scan"]["tool"] = "pip-audit"
            if "not installed" in (qa["dependency_scan"].get("output") or "") or qa["dependency_scan"]["status"] == "skipped":
                qa["dependency_scan"]["status"] = "skipped"
                qa["dependency_scan"]["note"] = qa["dependency_scan"].get("note") or "pip-audit is not installed in the runtime image; nothing was downloaded (no network in QA)"
        elif lang in ("JavaScript", "TypeScript") and (clone / "package-lock.json").exists() and image:
            qa["dependency_scan"] = container_run(image, "npm audit --json --audit-level=moderate 2>&1 | head -c 20000", rid, "repo", label="deps")
            qa["dependency_scan"]["tool"] = "npm audit"
            if qa["dependency_scan"]["status"] == "fail" and "ENOTFOUND" in (qa["dependency_scan"].get("output") or "") or "network" in (qa["dependency_scan"].get("output") or "").lower():
                qa["dependency_scan"]["status"] = "skipped"
                qa["dependency_scan"]["note"] = "npm audit needs the registry; QA runs without network"
        else:
            qa["dependency_scan"] = {"status": "skipped", "note": "no pip-audit / npm audit target (requirements.txt or package-lock.json) for this repository", "tool": None}
        _log(rid, "scan", f"Dependency scan ({qa['dependency_scan'].get('tool') or '—'}): {qa['dependency_scan']['status']}" + (f" — {qa['dependency_scan'].get('note')}" if qa["dependency_scan"].get("note") else ""), {k: v for k, v in qa["dependency_scan"].items() if k != "output"})
    else:
        qa["dependency_scan"] = {"status": "skipped", "note": "dependency scan is off in the policy"}
    if idx.get("lint_command") and image:
        qa["lint"] = container_run(image, idx["lint_command"] + " 2>&1 | tail -c 4000", rid, "repo", label="lint")
        if qa["lint"]["status"] == "fail" and ("not found" in (qa["lint"].get("output") or "") or "No module named" in (qa["lint"].get("output") or "")):
            qa["lint"]["status"] = "skipped"
            qa["lint"]["note"] = "the linter is not installed in the runtime image"
    else:
        qa["lint"] = {"status": "skipped", "note": "no lint command found" if not idx.get("lint_command") else "no runtime image"}
    qa["finished"] = time.time()
    qa["gate"] = {"tests_must_pass": bool(pol.get("tests_must_pass")), "tests_ok": qa["tests"]["status"] in ("pass", "skipped"), "secrets_ok": not qa["secret_scan"]["in_change"]}
    (d / "tests" / "qa.json").write_text(json.dumps(qa, indent=1, default=str), encoding="utf-8")
    _set(rid, qa=qa)
    return qa


async def _qa_job(pid: str, args: dict) -> None:
    _set(pid, status="qa", stage="qa")
    worker.app_note(pid, "sdlc_qa", "QA: the repository's tests in a throwaway container, generated tests counted, dependency and secret scans.")
    try:
        qa = await asyncio.to_thread(run_qa, pid)
        t = qa["tests"]
        worker.app_note(pid, "sdlc_qa", f"Tests {t['status']}" + (f" ({t.get('note')})" if t.get("note") else "") + f" · {len(qa['generated_tests'])} test file(s) in the change · secret scan {qa['secret_scan']['status']} · dependencies {qa['dependency_scan']['status']}.",
                        "warn" if t["status"] in ("fail", "timeout") or qa["secret_scan"]["in_change"] else "ok")
        d = store.ROOT / pid
        if args.get("review_ready") and (d / "review.yaml").exists():
            reviewed(pid, load_yaml(d / "review.yaml"))
            store.update(pid, status="review", job=None, error=None)
            return
        _set(pid, status="reviewing", stage="qa")
        worker.enqueue(pid, "sdlc_review")              # leaves the folder queued with this job; resetting it would make the worker skip it
    except Exception as e:
        _set(pid, status="error", stage="qa", note=str(e)[:300])
        _log(pid, "error", f"QA failed: {str(e)[:300]}")
        raise


worker.register_job("sdlc_qa", _qa_job, status="qa", done="QA done — the reviewer agent reads the change next")


# ------------------------------------------------------------------ Review (the reviewer agent, then a named human)

def check_review(d: Path) -> list[str]:
    p = d / "review.yaml"
    if not p.exists():
        return ["review.yaml was not written"]
    try:
        y = load_yaml(p)
    except Exception as e:  # noqa: BLE001
        return [f"review.yaml does not parse: {str(e).splitlines()[0]}"]
    out = []
    if not isinstance(y, dict):
        return ["review.yaml must be a mapping"]
    if y.get("verdict") not in ("approve", "request_changes"):
        out.append("verdict must be approve or request_changes")
    if not str(y.get("summary") or "").strip():
        out.append("summary is missing")
    f = y.get("findings")
    if not isinstance(f, list) or not all(isinstance(x, dict) and x.get("text") and x.get("severity") in ("high", "medium", "low") for x in f):
        out.append("findings must be a list of {file, line, severity high|medium|low, text, fix}")
    if not isinstance(y.get("checks"), dict):
        out.append("checks must be a mapping (matches_plan, tests_added, conventions, secrets, scope)")
    return out


def reviewed(rid: str, review: dict, summary: str = "") -> dict:
    r = _row(rid)
    qa = r.get("qa") or {}
    _set(rid, status="review", stage="qa", review=review, note=None)
    checkpoints.withdraw(KINDS["review"], rid, who="system")
    findings = review.get("findings") or []
    t = qa.get("tests") or {}
    items = [f"Reviewer agent: {review.get('verdict', '').replace('_', ' ')} — {review.get('summary') or ''}",
             f"Tests ({t.get('cmd') or 'repository command'}): {t.get('status')}" + (f" — {t.get('note')}" if t.get("note") else ""),
             f"Generated tests: {len(qa.get('generated_tests') or [])} file(s) · secret scan: {(qa.get('secret_scan') or {}).get('status')} ({len((qa.get('secret_scan') or {}).get('in_change') or [])} in this change) · dependencies: {(qa.get('dependency_scan') or {}).get('status')}",
             f"{len(qa.get('commits') or [])} commit(s), {len(qa.get('files') or [])} file(s) on {r.get('branch')} from {r.get('base')}"]
    rows = [{"file": x.get("file") or "", "line": x.get("line") or "", "severity": x.get("severity"), "finding": x.get("text"), "fix": x.get("fix") or ""} for x in findings]
    ev = {"summary": f"Pull request: {r['title']} ({r.get('branch')} → {r.get('base')})", "items": items, "counts": {"findings": len(findings), "high": sum(1 for x in findings if x.get("severity") == "high"), "tests": t.get("status") or "—", "files": len(qa.get("files") or [])},
          "columns": ["file", "line", "severity", "finding", "fix"], "rows": rows, "review": review, "qa": {k: v for k, v in qa.items() if k not in ("tests",)} | {"tests": {k: v for k, v in t.items() if k != "output"}},
          "pr": {"title": r["title"], "head": r.get("branch"), "base": r.get("base"), "files": qa.get("files"), "commits": qa.get("commits")}, "request": {"id": rid, "title": r["title"]}}
    cp = checkpoints.open(KINDS["review"], rid, MODULE, f"Review the pull request: {r['title']}", "table", ev, link=f"{ROUTE}/{rid}", assignee=_approver("review", r), agent="Relay reviewer", opened_by="agent")
    _set(rid, checkpoint_id=cp["id"])
    _log(rid, "review", f"Reviewer agent: {review.get('verdict')} with {len(findings)} finding(s) — the named reviewer decides", {"summary": (review.get("summary") or "")[:300], "verdict": review.get("verdict")})
    worker.app_note(rid, "sdlc_review", f"Reviewer agent: {review.get('verdict', '').replace('_', ' ')} — {review.get('summary') or ''} Waiting for the named reviewer.", "ok" if review.get("verdict") == "approve" else "warn")
    db.audit("sdlc.reviewed", rid, {"verdict": review.get("verdict"), "findings": len(findings), "summary": summary[:200]}, "agent")
    return _row(rid)


async def _review_job(pid: str, args: dict) -> None:
    r = _row(pid)
    d = store.ROOT / pid
    _set(pid, status="reviewing", stage="qa")
    worker.app_note(pid, "sdlc_review", "The reviewer agent is reading the diff, the plan and the QA results.")
    try:
        res = await worker.agent(pid, "sdlc_review", sdlc_prompts.review(r), worker.TURNS["sdlc_review"], "review", system=sdlc_prompts.SYSTEM)
        _log_run(pid, "review", res)
        for attempt in range(worker.FIX_ROUNDS + 1):
            problems = await asyncio.to_thread(check_review, d)
            if not problems:
                break
            if attempt == worker.FIX_ROUNDS:
                raise RuntimeError(f"review.yaml still has {len(problems)} problem(s): " + "; ".join(problems[:4]))
            res = await worker.agent(pid, "sdlc_review", sdlc_prompts.fix("review.yaml", problems), worker.TURNS["fix"], "review", resume=res.get("session_id"), system=sdlc_prompts.SYSTEM)
            _log_run(pid, "review fix", res)
        reviewed(pid, load_yaml(d / "review.yaml"), res.get("text") or "")
        store.update(pid, status="review", job=None, error=None)
    except Exception as e:
        _set(pid, status="error", stage="qa", note=str(e)[:300])
        _log(pid, "error", f"Review failed: {str(e)[:300]}")
        raise


worker.register_job("sdlc_review", _review_job, status="reviewing", done="Reviewed — a named reviewer approves the pull request", llm=True, turns=60, timeout_s=1800)


# ------------------------------------------------------------------ UAT on synthetic data

def start_uat(rid: str, who: str) -> dict:
    r = _row(rid)
    plan, d = r.get("plan") or {}, store.ROOT / rid
    repo_row = _repo(r["repo_id"])
    idx = repo_row["index"] or {}
    uat = {"started": time.time(), "steps": (plan.get("uat") or {}).get("steps") or [], "touches_data": bool(plan.get("touches_data")) or bool((plan.get("uat") or {}).get("datagen")), "data": None, "tests": None}
    if uat["touches_data"]:
        recipe = d / "uat" / "datagen.yaml"
        if recipe.exists():
            try:
                (d / "uat" / "data").mkdir(exist_ok=True)
                s = datagen.run(d / "uat", "datagen.yaml")
                uat["data"] = {"tables": [{"table": t["table"], "file": t["file"], "rows": t["rows"]} for t in s["tables"]], "rows": s["rows"], "story": s.get("story") or [], "seed": s.get("seed")}
                _log(rid, "uat", f"Synthetic data generated: {len(s['tables'])} table(s), {s['rows']:,} rows (DemoData recipe, no real data)", {"tables": [t["table"] for t in s["tables"]]})
                if idx.get("test_command") and idx.get("runtime_image"):
                    uat["tests"] = container_run(idx["runtime_image"], idx["test_command"], rid, "repo", env={"RELAY_UAT_DATA": "/work/../uat/data"}, label="uat")
                    _log(rid, "uat", f"Tests on the synthetic data: {uat['tests']['status']}" + (f" — {uat['tests'].get('note')}" if uat["tests"].get("note") else ""), {k: v for k, v in uat["tests"].items() if k != "output"})
            except datagen.RecipeError as e:
                uat["data"] = {"error": str(e)[:400]}
                _log(rid, "uat", f"The synthetic-data recipe has problems: {str(e)[:200]}")
        else:
            uat["data"] = {"error": "the change touches data but uat/datagen.yaml was not written; the business user checks the steps on a copy of their own test data"}
    _set(rid, status="uat", stage="uat", uat=uat, note=None)
    checkpoints.withdraw(KINDS["uat"], rid, who="system")
    rows = [{"table": t["table"], "rows": t["rows"], "file": t["file"]} for t in ((uat["data"] or {}).get("tables") or [])]
    items = [f"Step {i + 1}: {s}" for i, s in enumerate(uat["steps"][:8])]
    if uat["data"] and uat["data"].get("tables"):
        items.insert(0, f"Synthetic data: {len(rows)} table(s), {uat['data']['rows']:,} rows — no real personal data")
    elif uat["data"] and uat["data"].get("error"):
        items.insert(0, f"Synthetic data: {uat['data']['error']}")
    else:
        items.insert(0, "The change touches no data: sign off on the steps below against the plan's acceptance criteria")
    if uat["tests"]:
        items.append(f"Tests on the synthetic data: {uat['tests']['status']}" + (f" — {uat['tests'].get('note')}" if uat["tests"].get("note") else ""))
    ev = {"summary": f"UAT: {r['title']} — business sign-off", "items": items, "counts": {"steps": len(uat["steps"]), "tables": len(rows), "rows": (uat["data"] or {}).get("rows") or 0},
          "columns": ["table", "rows", "file"], "rows": rows, "uat": uat, "request": {"id": rid, "title": r["title"]}}
    cp = checkpoints.open(KINDS["uat"], rid, MODULE, f"UAT sign-off: {r['title']}", "table", ev, link=f"{ROUTE}/{rid}", assignee=_approver("uat", r), agent="Relay", opened_by=who)
    _set(rid, checkpoint_id=cp["id"])
    worker.app_note(rid, "sdlc_uat", "UAT: " + (items[0]) + " Waiting for the business sign-off.", "ok")
    db.audit("sdlc.uat.opened", rid, {"touches_data": uat["touches_data"], "tables": len(rows), "steps": len(uat["steps"])}, who)
    return _row(rid)


# ------------------------------------------------------------------ Release (a named approver; push + pull request; never merged)

def start_release(rid: str, who: str) -> dict:
    r = _row(rid)
    qa = r.get("qa") or {}
    pol = policy()
    blockers = []
    if pol["scans"].get("tests_must_pass") and (qa.get("tests") or {}).get("status") in ("fail", "timeout"):
        blockers.append(f"the tests {qa['tests']['status']} in QA and the policy requires them to pass")
    if (qa.get("secret_scan") or {}).get("in_change"):
        blockers.append(f"{len(qa['secret_scan']['in_change'])} secret(s) found in the change")
    if not r.get("branch") or not (_clone_dir(rid) / ".git").exists():
        blockers.append("no branch to release")
    if blockers:
        _set(rid, status="blocked", stage="release", note="Release blocked: " + "; ".join(blockers))
        _log(rid, "decision", "Release blocked: " + "; ".join(blockers), None, who)
        db.audit("sdlc.release.blocked", rid, {"blockers": blockers}, who)
        return _row(rid)
    approver = _approver("release", r)
    _set(rid, status="release_review", stage="release", note=None)
    checkpoints.withdraw(KINDS["release"], rid, who="system")
    commits = qa.get("commits") or []
    ev = {"summary": f"Release {r['title']}: push {r.get('branch')} and open a pull request against {r.get('base')} — nothing is merged by Relay",
          "items": [f"{len(commits)} commit(s), {len(qa.get('files') or [])} file(s)", f"Tests: {(qa.get('tests') or {}).get('status')} · secret scan: {(qa.get('secret_scan') or {}).get('status')} · dependencies: {(qa.get('dependency_scan') or {}).get('status')}",
                    f"Reviewer agent: {(r.get('review') or {}).get('verdict', '—')} · human review and UAT accepted", f"Roll back: {(r.get('plan') or {}).get('rollback') or 'revert the merge commit'}"],
          "counts": {"commits": len(commits), "files": len(qa.get("files") or [])}, "request": {"id": rid, "title": r["title"]}, "approver": approver}
    cp = checkpoints.open(KINDS["release"], rid, MODULE, f"Release: {r['title']}", "text", ev, link=f"{ROUTE}/{rid}", assignee=approver, agent="Relay", opened_by=who)
    _set(rid, checkpoint_id=cp["id"])
    _log(rid, "decision", f"Release waits for the named approver ({(db.user(approver) or {}).get('name') if approver else 'unassigned'})", None, who)
    db.audit("sdlc.release.requested", rid, {"approver": approver}, who)
    return _row(rid)


def _change_record(r: dict, pr: dict, push: dict, who: str) -> str:
    plan, qa, review, uat = r.get("plan") or {}, r.get("qa") or {}, r.get("review") or {}, r.get("uat") or {}
    decisions = db.q("SELECT kind, name, decided_by, decided, comment FROM checkpoints WHERE subject = ? AND status = 'accepted' ORDER BY decided", (r["id"],))
    lines = [f"# Change record — {r['title']}", "", f"Request {r['id']} · source {r['source']}" + (f" · ticket {r['ticket_key']}" if r.get("ticket_key") else ""), f"Repository {_repo(r['repo_id'])['name']} · branch {r.get('branch')} → {r.get('base')} · pull request {pr.get('url')} (#{pr.get('number')}) — opened, not merged", "",
             "## What changed", "", plan.get("summary") or "", "", "### Files", ""] + [f"- {f.get('status')} {f.get('path')}" for f in qa.get("files") or []] + ["", "### Commits", ""] + [f"- {c.get('sha')} {c.get('message')}" for c in qa.get("commits") or []]
    lines += ["", "## Proof", "", f"- Tests: {(qa.get('tests') or {}).get('status')}" + (f" — {(qa.get('tests') or {}).get('note')}" if (qa.get("tests") or {}).get("note") else ""), f"- Generated tests: {len(qa.get('generated_tests') or [])} file(s)",
              f"- Secret scan: {(qa.get('secret_scan') or {}).get('status')} ({len((qa.get('secret_scan') or {}).get('findings') or [])} finding(s) in the tree, {len((qa.get('secret_scan') or {}).get('in_change') or [])} in the change)",
              f"- Dependency scan: {(qa.get('dependency_scan') or {}).get('status')}" + (f" — {(qa.get('dependency_scan') or {}).get('note')}" if (qa.get("dependency_scan") or {}).get("note") else ""),
              f"- Reviewer agent: {review.get('verdict')} — {review.get('summary') or ''} ({len(review.get('findings') or [])} finding(s))",
              f"- UAT: {len(uat.get('steps') or [])} step(s)" + (f", synthetic data {len((uat.get('data') or {}).get('tables') or [])} table(s)" if (uat.get("data") or {}).get("tables") else ""), "", "## Approvals", ""]
    lines += [f"- {c['name']} — {(db.user(c['decided_by']) or {}).get('name') or c['decided_by']} at {_when(c['decided'])}" + (f" ({c['comment']})" if c.get("comment") else "") for c in decisions]
    lines += [f"- Released by {(db.user(who) or {}).get('name') or who} at {_when(time.time())}", "", "## Roll back", "", plan.get("rollback") or "Revert the merge commit; the branch stays for reference.",
              "", f"The pull request is open on the host for the team to merge; Relay never merges. Branch head {push.get('head', '')[:12]}.", ""]
    return "\n".join(lines)


async def _release_job(pid: str, args: dict) -> None:
    r = _row(pid)
    who = args.get("who") or r.get("owner_id") or db.ADMIN_ID
    repo_row = _repo(r["repo_id"])
    host = sdlc_git.host_for(repo_row)
    _set(pid, status="releasing", stage="release")
    worker.app_note(pid, "sdlc_release", f"Releasing: pushing {r.get('branch')} and opening the pull request on {repo_row['name']}.")
    try:
        clone = _clone_dir(pid)
        push = await asyncio.to_thread(gk.push, clone, r["branch"], "origin", host.creds())
        _log(pid, "git", f"Pushed {push['branch']} ({push['head'][:8]}) to {push['remote']}", push, who)
        body = f"{(r.get('plan') or {}).get('summary') or ''}\n\nOpened by Relay for change request {pid} ({r['source']}" + (f", ticket {r['ticket_key']}" if r.get("ticket_key") else "") + \
               f").\n\nTests: {((r.get('qa') or {}).get('tests') or {}).get('status')} · secret scan: {((r.get('qa') or {}).get('secret_scan') or {}).get('status')} · reviewer agent: {(r.get('review') or {}).get('verdict')}.\n\nRoll back: {(r.get('plan') or {}).get('rollback') or 'revert the merge commit'}."
        pr = await asyncio.to_thread(host.open_pr, r["branch"], r.get("base") or repo_row["default_branch"], f"{r['title']} (Relay {pid})", body)
        _log(pid, "release", f"Pull request #{pr.get('number')} opened: {pr.get('url')} — not merged", pr, who)
        record = _change_record(r, pr, push, who)
        (store.ROOT / pid / "release.md").write_text(record, encoding="utf-8")
        rel = {"pushed": push, "pr": pr, "who": who, "when": time.time(), "change_record": "release.md", "rollback": (r.get("plan") or {}).get("rollback"), "merged": False}
        _set(pid, status="released", stage="run", release=rel, note=None)
        _mark_work(r, "done", who, f"{ROUTE}/{pid}")
        try:
            request_writeback(pid, who)                     # the pull request link back on the ticket, after its own approval
        except Exception:  # noqa: BLE001 - the release stands either way
            traceback.print_exc()
        worker.app_note(pid, "sdlc_release", f"Released: pull request #{pr.get('number')} is open on {repo_row['name']} ({pr.get('url')}). Relay does not merge; Self-healing watches what it touches once it is live.", "ok")
        db.audit("sdlc.released", pid, {"pr": pr, "branch": r["branch"], "head": push["head"]}, who)
        for uid in {who, r.get("owner_id")}:
            if uid and db.user(uid):
                notify.add(uid, "build", f"Pull request open: {r['title']}", f"#{pr.get('number')} on {repo_row['name']} — not merged by Relay.", f"{ROUTE}/{pid}")
        store.update(pid, status="released", job=None, error=None)
    except Exception as e:
        _set(pid, status="error", stage="release", note=str(e)[:300])
        _log(pid, "error", f"Release failed: {str(e)[:300]}")
        raise


worker.register_job("sdlc_release", _release_job, status="releasing", done="Released — the pull request is open")


# ------------------------------------------------------------------ the pull request link back on the ticket (consolidation)
# A comment on the Jira issue (through the Service desk's write gate: the source must allow comments, and a named
# person approves exactly the comment) or on the Azure Boards work item (the repository's write-back setting, then
# this module's own checkpoint). Never without the grant, never without the approval; the release stands either way.

WRITEBACK_KIND = "sdlc.writeback"


def _writeback_text(r: dict, pr: dict) -> str:
    qa = r.get("qa") or {}
    return (f"Relay opened pull request #{pr.get('number')} for this ticket: {pr.get('url')}\n\n"
            f"{r['title']} — tests {((qa.get('tests') or {}).get('status')) or 'not run'}, secret scan {((qa.get('secret_scan') or {}).get('status')) or '—'}, "
            "reviewed by the reviewer agent and a named reviewer, UAT signed off, release approved. Relay does not merge: the team merges it.")


def request_writeback(rid: str, who: str | None) -> dict | None:
    """Ask for the write-back of the released request's pull request link; returns what was asked (or why not)."""
    r = _row(rid)
    rel = r.get("release") or {}
    pr = rel.get("pr") or {}
    if not (r.get("ticket_key") and pr.get("url") and r.get("repo_id")):
        return None
    repo_row = _repo(r["repo_id"])
    grant = _writeback_grant(repo_row)
    text = _writeback_text(r, pr)
    approver = _approver("release", r)
    out = {"ticket": r["ticket_key"], "tracker": grant["tracker"], "text": text, "asked": time.time()}
    if not grant["allowed"]:
        out.update(status="not_allowed", note=grant["why"])
    elif grant["tracker"] == "Jira":
        from . import itsm
        try:
            wr = itsm.request_write(repo_row["tracker_source"], "comment", {"key": r["ticket_key"], "text": text}, who=who, module=MODULE, origin=f"sdlc:{rid}",
                                    link=f"{ROUTE}/{rid}", assignee=approver, name=f"Pull request link on {r['ticket_key']}: {r['title']}"[:200])
            out.update(status="waiting", write=wr["id"], checkpoint=wr["checkpoint_id"], source=wr["source"])
        except itsm.ItsmError as e:
            out.update(status="not_allowed", note=str(e)[:300])
    else:                                                    # Azure Boards: this module's own checkpoint for exactly the comment
        ev = {"summary": f"A comment on Azure Boards work item {r['ticket_key']} with the pull request link — exactly this is written, once, after you accept.",
              "items": [f"Work item: {r['ticket_key']}", f"Comment: {text[:200]}"], "columns": ["What", "Will be written"], "rows": [["Work item", r["ticket_key"]], ["Comment", text]],
              "text": text, "request": {"id": rid, "title": r["title"]}}
        cp = checkpoints.open(WRITEBACK_KIND, rid, MODULE, f"Pull request link on work item {r['ticket_key']}: {r['title']}"[:200], "table", ev, link=f"{ROUTE}/{rid}",
                              assignee=approver, agent="Relay", opened_by=who)
        out.update(status="waiting", checkpoint=cp["id"], source="Azure Boards")
    _set(rid, release={**rel, "writeback": out})
    _log(rid, "release", f"Pull request link on {r['ticket_key']}: " + ("waiting for a named approval" if out["status"] == "waiting" else f"not written — {out.get('note')}"),
         {k: out.get(k) for k in ("status", "tracker", "checkpoint", "note")}, who)
    db.audit("sdlc.writeback.requested", rid, {k: out.get(k) for k in ("status", "tracker", "ticket", "checkpoint")}, who)
    return out


def _writeback_result(rid: str, status: str, who: str | None, url: str | None = None, error: str | None = None, by: str | None = None) -> None:
    try:
        r = _row(rid)
    except HTTPException:
        return
    rel = r.get("release") or {}
    wb = {**(rel.get("writeback") or {}), "status": status, "url": url, "error": error, "by": by, "decided": time.time()}
    _set(rid, release={**rel, "writeback": wb})
    _log(rid, "release", f"Pull request link {'written to' if status == 'written' else 'not written to'} {r.get('ticket_key')}" + (f" (approved by {by})" if by and status == "written" else f": {error}" if error else ""),
         {"status": status, "url": url}, who)
    db.audit("sdlc.writeback", rid, {"status": status, "ticket": r.get("ticket_key"), "url": url}, who)


def _jira_writeback(wr: dict, event: str) -> None:
    """The Service desk's hook (origin sdlc:<id>): the comment on the Jira issue was written, or not."""
    _writeback_result(str(wr.get("origin") or "").split(":", 1)[-1], "written" if event == "written" else event, None, url=(wr.get("result") or {}).get("url"),
                      error=wr.get("error"), by=wr.get("decided_by_name"))


def _on_writeback(c: dict, decision: str, comment: str | None, who: str) -> None:
    rid = c["subject"]
    try:
        r = _row(rid)
    except HTTPException:
        return
    if decision != "accept":
        _writeback_result(rid, "sent_back", who, error=(comment or "")[:300] or None)
        return
    by = (db.user(who) or {}).get("name") or "a person"
    repo_row = _repo(r["repo_id"])
    cfg = sdlc_git.boards_settings(repo_row["id"])
    pat = secrets_store.get("org", f"sdlc:{repo_row['id']}:boards_pat")
    text = (c.get("evidence") or {}).get("text") or ""
    if not cfg.get("write_back") or not (cfg.get("org_url") and cfg.get("project") and pat):
        _writeback_result(rid, "refused", who, error="Azure Boards write-back is off or not set up for this repository any more.")
        return
    try:
        res = sdlc_git.azure_boards_comment(cfg["org_url"], cfg["project"], r["ticket_key"], text + f"\n\nWritten by Relay after {by} approved it.", pat)
    except (sdlc_git.HostError, httpx.HTTPError, ValueError) as e:
        _writeback_result(rid, "failed", who, error=str(e)[:300])
        notify.add(who, "alert", f"Not written to work item {r['ticket_key']}", str(e)[:300], f"{ROUTE}/{rid}")
        return
    _writeback_result(rid, "written", who, url=res.get("url"), by=by)


checkpoints.register_kind(WRITEBACK_KIND, "AI SDLC: pull request link on the ticket", _on_writeback)
try:
    from . import itsm as _itsm
    _itsm.register_write_hook("sdlc", _jira_writeback)
except Exception:  # noqa: BLE001 - without the Service desk a Jira write-back is simply not offered
    traceback.print_exc()


# ------------------------------------------------------------------ checkpoint decisions

def _send_back_to_dev(rid: str, comment: str | None, who: str, step: str) -> None:
    _set(rid, status="developing", stage="develop", note=(comment or "")[:500], checkpoint_id=None)
    _log(rid, "decision", f"{step} sent back: {(comment or '')[:300]}", None, who)
    db.audit(f"sdlc.{step}.sent_back", rid, {"comment": (comment or "")[:300]}, who)
    try:
        worker.enqueue(rid, "sdlc_dev", correction=comment, who=who)
    except Exception as e:  # noqa: BLE001
        _set(rid, status="blocked", note=f"Sent back; the correction could not start: {str(e)[:200]}")


def _on_plan(c: dict, decision: str, comment: str | None, who: str) -> None:
    rid = c["subject"]
    try:
        _row(rid)
    except HTTPException:
        return
    if decision != "accept":
        _set(rid, status="planning", stage="plan", note=(comment or "")[:500], checkpoint_id=None)
        _log(rid, "decision", f"Plan sent back: {(comment or '')[:300]}", None, who)
        db.audit("sdlc.plan.sent_back", rid, {"comment": (comment or "")[:300]}, who)
        try:
            worker.enqueue(rid, "sdlc_plan", correction=comment, who=who)
        except Exception as e:  # noqa: BLE001
            _set(rid, status="blocked", note=f"Sent back; a new plan could not start: {str(e)[:200]}")
        return
    _log(rid, "decision", "Plan approved by the tech lead" + (f": {comment[:200]}" if comment else ""), None, who)
    db.audit("sdlc.plan.accepted", rid, {"comment": (comment or "")[:200]}, who)
    try:
        worker.enqueue(rid, "sdlc_dev", who=who)
        _set(rid, status="developing", stage="develop", checkpoint_id=None, note=None)
    except Exception as e:  # noqa: BLE001
        _set(rid, status="blocked", note=f"Development could not start: {str(e)[:200]}")


def _on_review(c: dict, decision: str, comment: str | None, who: str) -> None:
    rid = c["subject"]
    try:
        _row(rid)
    except HTTPException:
        return
    if decision != "accept":
        _send_back_to_dev(rid, comment, who, "review")
        return
    _log(rid, "decision", "Pull request approved by the reviewer" + (f": {comment[:200]}" if comment else ""), None, who)
    db.audit("sdlc.review.accepted", rid, {"comment": (comment or "")[:200]}, who)
    try:
        start_uat(rid, who)
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        _set(rid, status="blocked", note=f"UAT could not start: {str(e)[:200]}")


def _on_uat(c: dict, decision: str, comment: str | None, who: str) -> None:
    rid = c["subject"]
    try:
        _row(rid)
    except HTTPException:
        return
    if decision != "accept":
        _send_back_to_dev(rid, comment, who, "uat")
        return
    _log(rid, "decision", "UAT signed off by the business" + (f": {comment[:200]}" if comment else ""), None, who)
    db.audit("sdlc.uat.accepted", rid, {"comment": (comment or "")[:200]}, who)
    start_release(rid, who)


def _on_release(c: dict, decision: str, comment: str | None, who: str) -> None:
    rid = c["subject"]
    try:
        _row(rid)
    except HTTPException:
        return
    if decision != "accept":
        _send_back_to_dev(rid, comment, who, "release")
        return
    _log(rid, "decision", "Release approved" + (f": {comment[:200]}" if comment else ""), None, who)
    db.audit("sdlc.release.accepted", rid, {"comment": (comment or "")[:200]}, who)
    try:
        worker.enqueue(rid, "sdlc_release", who=who)
        _set(rid, status="releasing", stage="release", checkpoint_id=None)
    except Exception as e:  # noqa: BLE001
        _set(rid, status="blocked", note=f"The release could not start: {str(e)[:200]}")


checkpoints.register_kind(KINDS["plan"], "AI SDLC plan", _on_plan)
checkpoints.register_kind(KINDS["review"], "AI SDLC pull request review", _on_review)
checkpoints.register_kind(KINDS["uat"], "AI SDLC UAT sign-off", _on_uat)
checkpoints.register_kind(KINDS["release"], "AI SDLC release", _on_release)


# ------------------------------------------------------------------ governance, summaries, scheduler, API

def governance() -> dict:
    from . import platform
    month, start, end = usage.month_bounds()
    spend = 0.0
    runs = 0
    for p in db.q("SELECT id FROM sdlc_requests"):       # store.all_projects() lists dashboards only
        try:
            st = store.load(p["id"])
        except (KeyError, FileNotFoundError, ValueError):
            continue
        for x in st.get("runs") or []:
            if start <= (x.get("ended") or 0) < end:
                spend += x.get("cost_usd") or 0
                runs += 1
    pol = policy()
    names = {u["id"]: u["name"] for u in db.q("SELECT id, name FROM users WHERE active = 1")}
    return {"ai": {"policy": platform.ai_policy(), "default_model": worker.DEFAULT_MODEL, "models": worker.model_labels()}, "quotas": usage.quotas(),
            "spend_month_usd": round(spend, 2), "runs_month": runs, "month": month, "policy": pol,
            "approver_names": {s: [names.get(u, u) for u in v] for s, v in pol["approvers"].items()}, "audit_30d": db.one("SELECT COUNT(*) AS n FROM audit WHERE action LIKE 'sdlc.%' AND ts >= ?", (time.time() - 30 * 86400,))["n"],
            "people": [{"id": k, "name": v} for k, v in sorted(names.items(), key=lambda kv: kv[1])]}


def summary() -> dict:
    rows = db.q("SELECT status, created, updated FROM sdlc_requests")
    now = time.time()
    open_rows = [r for r in rows if r["status"] in OPEN]
    rel = db.q("SELECT release FROM sdlc_requests WHERE status IN ('released', 'closed') AND release IS NOT NULL")
    released_30 = sum(1 for r in rel if (_j(r["release"], {}).get("when") or 0) >= now - 30 * 86400)
    return {"open": len(open_rows), "waiting_for_you": sum(1 for r in open_rows if r["status"] in ("plan_review", "review", "uat", "release_review", "waiting", "blocked")),
            "released_30d": released_30, "repos": db.one("SELECT COUNT(*) AS n FROM sdlc_repos")["n"], "by_stage": {s: sum(1 for r in open_rows if STAGE_OF.get(r["status"]) == s) for s in STAGES},
            "hint": "No change in flight" if not open_rows else None}


def requests_list(status: str = "open", limit: int = 300) -> list[dict]:
    if status == "open":
        rows = db.q(f"SELECT * FROM sdlc_requests WHERE status IN ({','.join('?' * len(OPEN))}) ORDER BY updated DESC LIMIT ?", (*OPEN, limit))
    elif status == "all":
        rows = db.q("SELECT * FROM sdlc_requests ORDER BY updated DESC LIMIT ?", (limit,))
    else:
        rows = db.q("SELECT * FROM sdlc_requests WHERE status = ? ORDER BY updated DESC LIMIT ?", (status, limit))
    out = []
    for r in rows:
        for k in ("plan", "qa", "review", "uat", "release", "assignees", "work"):
            r[k] = _j(r[k], {} if k != "work" else None)
        out.append(public(r))
    return out


async def _loop() -> None:
    while True:
        await asyncio.sleep(WATCH_EVERY_S)              # started at boot (main.py): the first pass one interval later
        try:
            for _t in db.each_tenant("sdlc"):           # P17: every tenant with AI SDLC on
                await asyncio.to_thread(watch_work)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            traceback.print_exc()


_sched_tasks: dict[int, asyncio.Task] = {}             # one watcher per event loop (the app's; a test's)


def ensure_scheduler() -> bool:
    """Start the watcher once on the app's loop. The app starts it at boot (consolidation: before, only a request on the
    event loop could, and every AI SDLC route runs in the thread pool, so it never ran); a request still makes sure it
    runs. It starts in a fresh context, never a request's tenant or person."""
    global _sched_task
    try:
        loop, here = asyncio.get_running_loop(), True
    except RuntimeError:
        loop, here = worker._loop, False
    if loop is None or loop.is_closed():
        return False
    t = _sched_tasks.get(id(loop))
    if t is not None and not t.done():
        return False

    def start() -> None:
        global _sched_task
        have = _sched_tasks.get(id(loop))
        if have is None or have.done():
            _sched_task = _sched_tasks[id(loop)] = loop.create_task(_loop(), context=contextvars.Context())
    if here:
        start()
    else:
        loop.call_soon_threadsafe(start)
    return True


def stop_scheduler() -> None:
    global _sched_task
    for t in _sched_tasks.values():
        t.cancel()
    _sched_tasks.clear()
    _sched_task = None


class RepoIn(BaseModel):
    name: str | None = None
    provider: str | None = None
    url: str | None = None
    api_url: str | None = None
    account: str | None = None
    token: str | None = None
    default_branch: str | None = None
    tracker_kind: str | None = None
    tracker_source: str | None = None
    boards_org_url: str | None = None
    boards_project: str | None = None
    boards_pat: str | None = None
    boards_write_back: bool | None = None


class RequestIn(BaseModel):
    repo_id: str | None = None
    title: str | None = None
    text: str | None = None
    ticket_key: str | None = None
    assignees: dict | None = None


class StartIn(BaseModel):
    repo_id: str


class Comment(BaseModel):
    comment: str | None = None


class PolicyIn(BaseModel):
    repos: list[str] | None = None
    approvers: dict | None = None
    scans: dict | None = None


def _u() -> dict:
    u = auth.current.get()
    if not u:
        raise HTTPException(401, "Sign in.")
    ensure_scheduler()
    return u


def _builder() -> dict:
    u = _u()
    if not auth.is_dev(u):
        raise HTTPException(403, "Only a BI Dev / Analyst or an Admin can do that.")
    return u


def _admin() -> dict:
    u = _u()
    if not auth.is_admin(u):
        raise HTTPException(403, "Only an Admin can change the policies.")
    return u


@router.get("/api/sdlc/overview")
def api_overview(status: str = "open"):
    u = _u()
    try:
        watch_work()
    except Exception:  # noqa: BLE001
        traceback.print_exc()
    jira = [{"id": s["id"], "name": s["name"]} for s in db.q("SELECT id, name FROM itsm_sources WHERE kind = 'jira'")] if "itsm_sources" in db.tables() else []
    return {"summary": summary(), "requests": requests_list(status), "repos": repos(), "policy": policy(), "governance": governance() if auth.is_dev(u) else None,
            "can_edit": auth.is_dev(u), "admin": auth.is_admin(u), "test_hooks": TEST_HOOKS, "providers": {k: v for k, v in sdlc_git.PROVIDERS.items() if k != "local" or TEST_HOOKS},
            "stages": [[s, STAGE_LABEL[s]] for s in STAGES], "jira_sources": jira, "worker": {"running": worker.current.get("pid"), "kind": worker.current.get("kind"), "waiting": worker.waiting()}}


@router.get("/api/sdlc/summary")
def api_summary():
    _u()
    return summary()


@router.get("/api/sdlc/governance")
def api_governance():
    _builder()
    return governance()


@router.get("/api/sdlc/policies")
def api_policies():
    _u()
    return policy()


@router.put("/api/sdlc/policies")
def api_set_policies(body: PolicyIn):
    u = _admin()
    return save_policy(body.model_dump(exclude_none=True), u["id"])


@router.get("/api/sdlc/repos")
def api_repos():
    _u()
    return {"items": repos(), "providers": sdlc_git.PROVIDERS}


@router.post("/api/sdlc/repos")
def api_add_repo(body: RepoIn):
    u = _builder()
    return save_repo(body.model_dump(exclude_none=True), u)


@router.put("/api/sdlc/repos/{rid}")
def api_edit_repo(rid: str, body: RepoIn):
    u = _builder()
    return save_repo(body.model_dump(exclude_none=True), u, rid)


@router.delete("/api/sdlc/repos/{rid}")
def api_remove_repo(rid: str):
    u = _builder()
    remove_repo(rid, u)
    return {"ok": True}


@router.post("/api/sdlc/repos/{rid}/test")
def api_test_repo(rid: str):
    u = _builder()
    return test_repo(rid, u["id"])


@router.get("/api/sdlc/requests")
def api_requests(status: str = "open"):
    _u()
    return {"items": requests_list(status)}


@router.post("/api/sdlc/requests")
def api_new_request(body: RequestIn):
    u = _builder()
    ticket = None
    title, text = body.title or "", body.text or ""
    if body.ticket_key:
        if not body.repo_id:
            raise HTTPException(400, "Pick the repository whose tracker holds the ticket.")
        try:
            ticket = sdlc_git.tracker_read(_repo(body.repo_id), body.ticket_key.strip())
        except sdlc_git.HostError as e:
            raise HTTPException(400, str(e)) from e
        except Exception as e:  # noqa: BLE001
            raise HTTPException(400, f"The ticket could not be read: {str(e)[:200]}") from e
        title = title or ticket.get("title") or body.ticket_key
        text = text or ticket.get("description") or ""
    r = create_request(u["id"], body.repo_id, title, text, source="tracker" if ticket else "words", ticket=ticket, assignees=body.assignees)
    return public(r, with_detail=True)


@router.get("/api/sdlc/requests/{rid}")
def api_request(rid: str):
    _u()
    return public(_row(rid), with_detail=True)


@router.get("/api/sdlc/requests/{rid}/file/{name:path}")
def api_request_file(rid: str, name: str):
    _u()
    _row(rid)
    if name not in ("request.md", "repo-index.yaml", "plan.yaml", "tests/qa.json", "review.yaml", "uat/datagen.yaml", "release.md"):
        raise HTTPException(404, "No such file.")
    p = store.ROOT / rid / name
    if not p.exists():
        raise HTTPException(404, "Not written yet.")
    return {"name": name, "text": p.read_text(encoding="utf-8", errors="replace")[:200000]}


@router.get("/api/sdlc/requests/{rid}/diff")
def api_request_diff(rid: str):
    _u()
    r = _row(rid)
    clone = _clone_dir(rid)
    if not (clone / ".git").exists() or not r.get("base_sha"):
        return {"diff": "", "note": "No branch yet."}
    try:
        return {"diff": gk.diff(clone, r["base_sha"])[:300000], "files": gk.changed_files(clone, r["base_sha"], "HEAD"), "commits": gk.log(clone, 50, since=r["base_sha"])}
    except gk.RepoError as e:
        return {"diff": "", "note": str(e)}


@router.get("/api/sdlc/requests/{rid}/audit")
def api_request_audit(rid: str):
    _u()
    _row(rid)
    rows = [{**x, "detail": _j(x["detail"], None)} for x in db.q("SELECT * FROM sdlc_log WHERE request_id = ? ORDER BY id", (rid,))]
    audit = [a for a in db.audit_log(500) if a.get("object") == rid or (a.get("detail") or {}).get("request") == rid]
    return {"log": rows, "audit": audit, "ai_calls": sum(1 for x in rows if x["kind"] == "ai"), "file_changes": sum(1 for x in rows if x["kind"] == "file"), "commits": sum(1 for x in rows if x["kind"] == "commit")}


@router.post("/api/sdlc/requests/{rid}/start")
def api_start(rid: str, body: StartIn):
    u = _builder()
    return start_request(rid, body.repo_id, u["id"])


@router.post("/api/sdlc/requests/{rid}/writeback")
def api_writeback(rid: str):
    """Ask again for the pull request link on the ticket (after the tracker's write grant was given, or a send-back)."""
    u = _builder()
    r = _row(rid)
    wb = (r.get("release") or {}).get("writeback") or {}
    if r["status"] not in ("released", "closed") or not (r.get("release") or {}).get("pr"):
        raise HTTPException(409, "There is no pull request to link yet: the request is not released.")
    if wb.get("status") in ("waiting", "written"):
        raise HTTPException(409, "The pull request link is already " + ("waiting for approval." if wb["status"] == "waiting" else "on the ticket."))
    out = request_writeback(rid, u["id"])
    if out is None:
        raise HTTPException(409, "This request did not come from a tracker ticket.")
    return public(_row(rid), with_detail=True)


@router.post("/api/sdlc/requests/{rid}/retry")
def api_retry(rid: str):
    u = _builder()
    r = _row(rid)
    if r["status"] not in ("error", "blocked"):
        raise HTTPException(409, "Only a failed or blocked request can be retried.")
    if not r.get("repo_id"):
        raise HTTPException(400, "Pick a repository first.")
    return start_request(rid, r["repo_id"], u["id"])


@router.post("/api/sdlc/requests/{rid}/close")
def api_close(rid: str, body: Comment):
    u = _builder()
    r = _row(rid)
    if r["closed"]:
        raise HTTPException(409, "Already closed.")
    if not (body.comment or "").strip():
        raise HTTPException(400, "Say why the request closes.")
    for k in KINDS.values():
        checkpoints.withdraw(k, rid, who=u["id"])
    _set(rid, status="closed", stage="run", note=body.comment.strip()[:500], closed=time.time(), closed_by=u["id"], checkpoint_id=None)
    _log(rid, "decision", f"Closed: {body.comment.strip()[:300]}", None, u["id"])
    _mark_work(r, "closed", u["id"])
    db.audit("sdlc.request.closed", rid, {"comment": body.comment[:300]}, u["id"])
    return public(_row(rid), with_detail=True)


# ------------------------------------------------------------------ test hooks (D2D_TEST_HOOKS=1): the agent's work, stood in for

def _hooks() -> dict:
    if not TEST_HOOKS:
        raise HTTPException(404, "Not found")
    return _builder()


SAMPLE_APP = "\"\"\"Invoice totals for the finance team (sample repository for Relay's AI SDLC).\"\"\"\n\n\ndef line_total(qty, price):\n    return qty * price\n\n\ndef invoice_total(lines):\n    # BUG: the discount is added instead of subtracted\n    return sum(line_total(q, p) for q, p, _ in lines) + sum(d for _, _, d in lines)\n"
SAMPLE_TEST = "import unittest\n\nfrom invoices import line_total\n\n\nclass LineTotalTest(unittest.TestCase):\n    def test_line_total(self):\n        self.assertEqual(line_total(3, 2.5), 7.5)\n"
SAMPLE_FIX = "\"\"\"Invoice totals for the finance team (sample repository for Relay's AI SDLC).\"\"\"\n\n\ndef line_total(qty, price):\n    return qty * price\n\n\ndef invoice_total(lines):\n    return sum(line_total(q, p) for q, p, _ in lines) - sum(d for _, _, d in lines)\n"
SAMPLE_NEW_TEST = "import unittest\n\nfrom invoices import invoice_total\n\n\nclass InvoiceTotalTest(unittest.TestCase):\n    def test_discount_is_subtracted(self):\n        self.assertEqual(invoice_total([(2, 10.0, 1.0), (1, 5.0, 0.0)]), 24.0)\n"
SAMPLE_PLAN = {"summary": "invoice_total adds the discount instead of subtracting it; subtract it and add a regression test.",
               "files": [{"path": "invoices.py", "change": "subtract the line discounts in invoice_total", "kind": "modify"}, {"path": "tests/test_invoice_total.py", "change": "regression test: discounts reduce the total", "kind": "add"}],
               "risks": [{"risk": "callers that relied on the wrong total", "mitigation": "the only caller is the report; its expected totals come from the finance team"}],
               "tests": [{"name": "test_discount_is_subtracted", "file": "tests/test_invoice_total.py", "what": "discounts reduce the total"}],
               "steps": ["Add the failing regression test", "Subtract the discount in invoice_total"], "touches_data": False,
               "uat": {"steps": ["Open the October invoice sample: the total equals lines minus discounts"], "datagen": False}, "estimate": {"hours": 1, "commits": 2}, "rollback": "Revert the merge commit; no data migration is involved.", "owners": []}
SAMPLE_REVIEW = {"verdict": "approve", "summary": "The change subtracts the discount as the request asks and adds a regression test; it matches the plan and the repository's unittest style.",
                 "findings": [{"file": "invoices.py", "line": 9, "severity": "low", "text": "a docstring on invoice_total would help the next reader", "fix": "add a one-line docstring"}],
                 "checks": {"matches_plan": True, "tests_added": True, "conventions": True, "secrets": True, "scope": True}}


def seed_sample(who: str) -> dict:
    """A bare repository on this machine with a small Python app (one bug, unittest tests, a planted key in a config
    file for the secret scan), registered as a local-path repository, and one change request waiting to start."""
    base = store.ROOT / ".sdlc-sample"
    bare = base / "origin.git"
    if not (bare / "HEAD").exists():
        shutil.rmtree(base, ignore_errors=True)
        seed = base / "seed"
        gk.init(seed)
        (seed / "invoices.py").write_text(SAMPLE_APP, encoding="utf-8")
        (seed / "tests").mkdir()
        (seed / "tests" / "__init__.py").write_text("", encoding="utf-8")
        (seed / "tests" / "test_line_total.py").write_text(SAMPLE_TEST, encoding="utf-8")
        (seed / "README.md").write_text("# Invoice totals\n\nSample repository. Tests: `python -m unittest discover -s tests -v`.\n", encoding="utf-8")
        (seed / "CODEOWNERS").write_text("invoices.py @finance-platform\n", encoding="utf-8")
        (seed / "settings.example.ini").write_text("[mail]\napi_key = \"AKIAIOSFODNN7EXAMPLE\"\n", encoding="utf-8")
        gk.commit(seed, "Invoice totals: first version")
        from dulwich import porcelain
        porcelain.init(str(bare), bare=True)
        gk.set_remote(seed, str(bare))
        gk.push(seed, "main")
        shutil.rmtree(seed, ignore_errors=True)
    repo_row = db.one("SELECT * FROM sdlc_repos WHERE url = ?", (str(bare),))
    if not repo_row:
        r = save_repo({"name": "Invoice totals (sample)", "provider": "local", "url": str(bare), "default_branch": "main"}, {"id": who})
        repo_id = r["id"]
    else:
        repo_id = repo_row["id"]
    have = db.one("SELECT id FROM sdlc_requests WHERE repo_id = ? AND source = 'words' AND status IN ({})".format(",".join("?" * len(OPEN))), (repo_id, *OPEN))
    if have:
        return {"repo": repo_id, "request": have["id"], "already": True}
    req = create_request(who, repo_id, "Invoice total adds the discount instead of subtracting it", "The finance report shows totals that are too high: invoice_total adds the line discounts. Subtract them and add a regression test.", start=False)
    db.audit("sdlc.sample", req["id"], {"repo": repo_id}, who)
    return {"repo": repo_id, "request": req["id"], "bare": str(bare)}


@router.post("/api/sdlc/test/seed")
def api_test_seed():
    u = _hooks()
    try:
        return seed_sample(u["id"])
    except gk.RepoError as e:                            # e.g. an image built before P16 has no dulwich: say so, not a bare 500
        raise HTTPException(503, str(e)) from e


@router.post("/api/sdlc/test/plan/{rid}")
def api_test_plan(rid: str):
    """Stands in for the sdlc_plan agent run: clone + index for real, plan.yaml from the sample."""
    u = _hooks()
    r = _row(rid)
    repo_row = _repo(r["repo_id"])
    clone = _ensure_clone(r, repo_row)
    _index(r, repo_row, clone)
    (store.ROOT / rid / "plan.yaml").write_text(yaml.safe_dump(SAMPLE_PLAN, sort_keys=False), encoding="utf-8")
    _log(rid, "ai", "plan (test hook stands in for the agent)", {"hook": True}, u["id"])
    problems = check_plan(store.ROOT / rid)
    if problems:
        raise HTTPException(500, "; ".join(problems))
    return public(planned(rid, SAMPLE_PLAN), with_detail=True)


@router.post("/api/sdlc/test/develop/{rid}")
def api_test_develop(rid: str):
    """Stands in for the sdlc_dev and sdlc_review agent runs: the fix and a test on relay/<id> in two commits (through
    genbi repo), review.yaml from the sample; QA then runs for real and opens the review checkpoint."""
    u = _hooks()
    r = _row(rid)
    if r["status"] not in ("developing", "plan_review", "qa", "error"):
        raise HTTPException(409, f"The request is {r['status']}.")
    repo_row = _repo(r["repo_id"])
    clone = _ensure_clone(r, repo_row)
    branch = r.get("branch") or f"{policy().get('branch_prefix') or 'relay/'}{rid}"
    gk.branch(clone, branch)
    _set(rid, branch=branch, status="developing", stage="develop")
    (clone / "tests" / "test_invoice_total.py").write_text(SAMPLE_NEW_TEST, encoding="utf-8")
    c1 = gk.commit(clone, "Add the failing regression test for invoice_total", ["tests/test_invoice_total.py"])
    (clone / "invoices.py").write_text(SAMPLE_FIX, encoding="utf-8")
    c2 = gk.commit(clone, "Subtract the discount in invoice_total", ["invoices.py"])
    _log(rid, "ai", "develop (test hook stands in for the agent): two commits", {"hook": True, "commits": [c1["commit"][:8], c2["commit"][:8]]}, u["id"])
    (store.ROOT / rid / "review.yaml").write_text(yaml.safe_dump(SAMPLE_REVIEW, sort_keys=False), encoding="utf-8")
    _log(rid, "ai", "review (test hook stands in for the reviewer agent)", {"hook": True}, u["id"])
    return public(developed(rid, u["id"], review_ready=True), with_detail=True)
