"""A stand-in for the GitHub REST API (the Git data API D2D Relay pushes with), for the D2D Relay test stack only
(never live). Standard library only. Item 70 (deployment) pushes a dashboard's Power BI project through it.

Runs inside the test web container on 0.0.0.0:9913 (item70_check.py starts it when it is not running); the stack points
the app at it with RELAY_GITHUB_API=http://d2d-relay-test-web:9913 (D2D_GITHUB_API inside).
Repositories: d2d-test/bi-dashboards and d2d-test/second-repo (default branch main, one README commit each) and
d2d-test/empty-repo (no commit: the Git data API answers 409). Tokens (Authorization: Bearer):
  GOOD          everything
  READONLY      reads only: every write is 403 "Resource not accessible by personal access token"
  NOWORKFLOW    no Workflows permission: moving a branch to a commit that changes .github/workflows/ is refused
  anything else 401 "Bad credentials"
  GET  /repos/<o>/<r>                          the repository (default_branch, private, permissions)
  GET  /repos/<o>/<r>/git/ref/heads/<branch>   404 when there is no such branch, 409 for the empty repository
  GET  /repos/<o>/<r>/git/commits/<sha>        its tree and parents
  GET  /repos/<o>/<r>/git/trees/<sha>[?recursive=1]
  POST /repos/<o>/<r>/git/blobs                {content, encoding: base64 | utf-8}
  POST /repos/<o>/<r>/git/trees                {base_tree, tree: [{path, mode, type, sha | content}]}; sha null deletes
  POST /repos/<o>/<r>/git/commits              {message, tree, parents}
  PATCH /repos/<o>/<r>/git/refs/heads/<branch> {sha, force}: 422 "Update is not a fast forward" unless it moves on
  POST /repos/<o>/<r>/git/refs                 {ref, sha}: 422 when it exists
Blob ids are git's own (sha1 of "blob <size>\\0" + content), so an unchanged file is known as git knows it.
For the tests: GET /_test/state (calls by kind), GET /_test/files?repo=&branch= (every file at the branch's head, base64),
POST /_test/reset, POST /_test/commit {repo, branch, files: {path: text or null}} (someone else pushes), POST /_test/race
{repo, branch} (the next branch move finds that someone else pushed just before: one commit, then 422).
"""
import base64
import hashlib
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

GOOD = "github_pat_STANDIN_GOOD_000000000000000000"
READONLY = "github_pat_STANDIN_READONLY_00000000000000"
NOWORKFLOW = "github_pat_STANDIN_NOWORKFLOW_000000000000"
REPOS = ("d2d-test/bi-dashboards", "d2d-test/second-repo", "d2d-test/empty-repo")
LOCK = threading.RLock()
OBJ: dict = {}                       # sha -> ("blob", bytes) | ("tree", {name: (mode, type, sha)}) | ("commit", {...})
REFS: dict = {}                      # repo -> {branch: commit sha}
STATE: dict = {}
RACE: set = set()


def bump(kind: str) -> None:
    STATE[kind] = STATE.get(kind, 0) + 1


def blob(data: bytes) -> str:
    sha = hashlib.sha1(b"blob %d\x00" % len(data) + data).hexdigest()
    OBJ[sha] = ("blob", data)
    return sha


def tree_of(entries: dict) -> str:
    sha = hashlib.sha1(b"tree " + json.dumps(sorted(entries.items())).encode()).hexdigest()
    OBJ[sha] = ("tree", dict(entries))
    return sha


def build(flat: dict) -> str:
    """A tree from {path: (mode, blob sha)}, folders made as needed."""
    here, sub = {}, {}
    for path, (mode, sha) in flat.items():
        head, _, rest = path.partition("/")
        if rest:
            sub.setdefault(head, {})[rest] = (mode, sha)
        else:
            here[head] = (mode, "blob", sha)
    for name, inner in sub.items():
        here[name] = ("040000", "tree", build(inner))
    return tree_of(here)


def flat_of(tree_sha: str, prefix: str = "") -> dict:
    out = {}
    for name, (mode, kind, sha) in OBJ[tree_sha][1].items():
        if kind == "tree":
            out.update(flat_of(sha, prefix + name + "/"))
        else:
            out[prefix + name] = (mode, sha)
    return out


def listing(tree_sha: str, recursive: bool, prefix: str = "") -> list:
    out = []
    for name, (mode, kind, sha) in sorted(OBJ[tree_sha][1].items()):
        out.append({"path": prefix + name, "mode": mode, "type": kind, "sha": sha})
        if recursive and kind == "tree":
            out.extend(listing(sha, True, prefix + name + "/"))
    return out


def commit(tree: str, parents: list, message: str) -> str:
    sha = hashlib.sha1(json.dumps([tree, parents, message, len(OBJ)]).encode()).hexdigest()
    OBJ[sha] = ("commit", {"tree": tree, "parents": parents, "message": message})
    return sha


def ancestors(sha: str) -> set:
    seen, todo = set(), [sha]
    while todo:
        s = todo.pop()
        if s in seen or s not in OBJ:
            continue
        seen.add(s)
        todo.extend(OBJ[s][1]["parents"])
    return seen


def reset() -> None:
    OBJ.clear()
    REFS.clear()
    STATE.clear()
    RACE.clear()
    for repo in REPOS:
        REFS[repo] = {}
        if repo != "d2d-test/empty-repo":
            REFS[repo]["main"] = commit(build({"README.md": ("100644", blob(f"# {repo}\n".encode()))}), [], "Initial commit")


def workflows(commit_sha: str) -> dict:
    return {p: v for p, v in flat_of(OBJ[commit_sha][1]["tree"]).items() if p.startswith(".github/workflows/")}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code: int, body=None):
        raw = json.dumps(body if body is not None else {}).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        try:
            return json.loads(self.rfile.read(n) or b"{}") if n else {}
        except ValueError:
            return {}

    def token(self) -> str:
        return re.sub(r"^(Bearer|token)\s+", "", self.headers.get("Authorization") or "").strip()

    def route(self, method: str):
        u = urlparse(self.path)
        if u.path.startswith("/_test/"):
            return self.test(method, u)
        m = re.fullmatch(r"/repos/([^/]+/[^/]+)(/.*)?", u.path)
        tok = self.token()
        if tok not in (GOOD, READONLY, NOWORKFLOW):
            return self.send(401, {"message": "Bad credentials", "documentation_url": "https://docs.github.com/rest"})
        if not m or m.group(1) not in REPOS:
            return self.send(404, {"message": "Not Found"})
        repo, rest = m.group(1), m.group(2) or ""
        data = self.body() if method in ("POST", "PATCH") else {}
        with LOCK:
            bump(f"{method} {re.sub(r'[0-9a-f]{40}', '<sha>', re.sub(r'/heads/.*', '/heads/<branch>', rest)) or '/'}")
            if method != "GET" and tok == READONLY:
                return self.send(403, {"message": "Resource not accessible by personal access token"})
            if method == "GET" and rest == "":
                return self.send(200, {"full_name": repo, "private": True, "default_branch": "main",
                                       "permissions": {"admin": False, "push": tok != READONLY, "pull": True}})
            if not REFS[repo] and rest.startswith("/git/"):
                return self.send(409, {"message": "Git Repository is empty."})
            g = re.fullmatch(r"/git/ref/heads/(.+)", rest)
            if method == "GET" and g:
                sha = REFS[repo].get(g.group(1))
                if not sha:
                    return self.send(404, {"message": "Not Found"})
                return self.send(200, {"ref": f"refs/heads/{g.group(1)}", "object": {"sha": sha, "type": "commit"}})
            g = re.fullmatch(r"/git/commits/([0-9a-f]{40})", rest)
            if method == "GET" and g:
                o = OBJ.get(g.group(1))
                if not o or o[0] != "commit":
                    return self.send(404, {"message": "Not Found"})
                return self.send(200, {"sha": g.group(1), "tree": {"sha": o[1]["tree"]}, "message": o[1]["message"],
                                       "parents": [{"sha": p} for p in o[1]["parents"]]})
            g = re.fullmatch(r"/git/trees/([0-9a-f]{40})", rest)
            if method == "GET" and g:
                o = OBJ.get(g.group(1))
                if not o or o[0] != "tree":
                    return self.send(404, {"message": "Not Found"})
                rec = "recursive" in parse_qs(u.query)
                return self.send(200, {"sha": g.group(1), "tree": listing(g.group(1), rec), "truncated": False})
            if method == "POST" and rest == "/git/blobs":
                content = data.get("content")
                if not isinstance(content, str):
                    return self.send(422, {"message": "Invalid request: content is missing"})
                raw = base64.b64decode(content) if data.get("encoding") == "base64" else content.encode()
                bump("blobs_uploaded")
                return self.send(201, {"sha": blob(raw), "url": "stand-in"})
            if method == "POST" and rest == "/git/trees":
                base = data.get("base_tree")
                if base and (base not in OBJ or OBJ[base][0] != "tree"):
                    return self.send(422, {"message": "Invalid tree info"})
                flat = flat_of(base) if base else {}
                for e in data.get("tree") or []:
                    path = str(e.get("path") or "")
                    if not path or path.startswith("/") or "//" in path or ".." in path.split("/") or e.get("type") != "blob":
                        return self.send(422, {"message": f"tree.path contains a malformed path component: {path}"})
                    if "content" in e:
                        flat[path] = (e.get("mode") or "100644", blob(str(e["content"]).encode()))
                        bump("inline_files")
                    elif e.get("sha") is None:
                        flat.pop(path, None)
                    elif e["sha"] in OBJ and OBJ[e["sha"]][0] == "blob":
                        flat[path] = (e.get("mode") or "100644", e["sha"])
                    else:
                        return self.send(422, {"message": "Invalid tree info: unknown sha"})
                sha = build(flat)
                return self.send(201, {"sha": sha, "tree": listing(sha, False), "truncated": False})
            if method == "POST" and rest == "/git/commits":
                t, parents = data.get("tree"), data.get("parents") or []
                if t not in OBJ or OBJ[t][0] != "tree" or any(p not in OBJ for p in parents):
                    return self.send(422, {"message": "Invalid request"})
                sha = commit(t, parents, str(data.get("message") or ""))
                return self.send(201, {"sha": sha, "tree": {"sha": t}, "parents": [{"sha": p} for p in parents],
                                       "html_url": f"https://github.com/{repo}/commit/{sha}"})
            g = re.fullmatch(r"/git/refs/heads/(.+)", rest)
            if method == "PATCH" and g:
                branch, new = g.group(1), data.get("sha")
                cur = REFS[repo].get(branch)
                if not cur:
                    return self.send(422, {"message": "Reference does not exist"})
                if new not in OBJ or OBJ[new][0] != "commit":
                    return self.send(422, {"message": "Object does not exist"})
                if (repo, branch) in RACE:     # someone else pushed just before
                    RACE.discard((repo, branch))
                    files = flat_of(OBJ[cur][1]["tree"])
                    files["external.txt"] = ("100644", blob(b"pushed by someone else\n"))
                    REFS[repo][branch] = commit(build(files), [cur], "Someone else's commit")
                    return self.send(422, {"message": "Update is not a fast forward"})
                if cur not in ancestors(new) and not data.get("force"):
                    return self.send(422, {"message": "Update is not a fast forward"})
                if tok == NOWORKFLOW and workflows(new) != workflows(cur):
                    changed = sorted(set(workflows(new)) ^ set(workflows(cur)) or workflows(new))
                    return self.send(403, {"message": f"refusing to allow a Personal Access Token to create or update workflow "
                                                      f"`{changed[0] if changed else '.github/workflows'}` without `workflow` scope"})
                REFS[repo][branch] = new
                bump("branch_moved")
                return self.send(200, {"ref": f"refs/heads/{branch}", "object": {"sha": new, "type": "commit"}})
            if method == "POST" and rest == "/git/refs":
                ref, new = str(data.get("ref") or ""), data.get("sha")
                if not ref.startswith("refs/heads/") or new not in OBJ:
                    return self.send(422, {"message": "Invalid request"})
                branch = ref[len("refs/heads/"):]
                if branch in REFS[repo]:
                    return self.send(422, {"message": "Reference already exists"})
                if tok == NOWORKFLOW and workflows(new):
                    return self.send(403, {"message": "refusing to allow a Personal Access Token to create or update workflow without `workflow` scope"})
                REFS[repo][branch] = new
                bump("branch_created")
                return self.send(201, {"ref": ref, "object": {"sha": new, "type": "commit"}})
            return self.send(404, {"message": "Not Found"})

    def test(self, method: str, u):
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        with LOCK:
            if u.path == "/_test/state":
                return self.send(200, dict(STATE))
            if u.path == "/_test/reset" and method == "POST":
                reset()
                return self.send(200, {"ok": True})
            if u.path == "/_test/files":
                repo, branch = q.get("repo"), q.get("branch") or "main"
                head = (REFS.get(repo) or {}).get(branch)
                if not head:
                    return self.send(404, {"message": "no such branch"})
                files = {p: base64.b64encode(OBJ[s][1]).decode() for p, (_, s) in flat_of(OBJ[head][1]["tree"]).items()}
                return self.send(200, {"head": head, "message": OBJ[head][1]["message"], "parents": OBJ[head][1]["parents"], "files": files})
            if u.path == "/_test/commit" and method == "POST":
                data = self.body()
                repo, branch = data.get("repo"), data.get("branch") or "main"
                cur = REFS[repo][branch]
                files = flat_of(OBJ[cur][1]["tree"])
                for path, text in (data.get("files") or {}).items():
                    if text is None:
                        files.pop(path, None)
                    else:
                        files[path] = ("100644", blob(text.encode()))
                REFS[repo][branch] = commit(build(files), [cur], "A commit made on GitHub")
                return self.send(200, {"head": REFS[repo][branch]})
            if u.path == "/_test/race" and method == "POST":
                data = self.body()
                RACE.add((data.get("repo"), data.get("branch") or "main"))
                return self.send(200, {"ok": True})
        return self.send(404, {"message": "Not Found"})

    def do_GET(self):
        self.route("GET")

    def do_POST(self):
        self.route("POST")

    def do_PATCH(self):
        self.route("PATCH")


if __name__ == "__main__":
    reset()
    ThreadingHTTPServer(("0.0.0.0", 9913), H).serve_forever()
