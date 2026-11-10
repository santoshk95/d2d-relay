"""`genbi repo` — git for the Relay agent, through the toolkit only (build-plan v2, P16 AI SDLC).

    genbi repo clone <url> [--dir repo] [--branch main] [--depth N]
    genbi repo index [--dir repo]            languages, test / lint commands, CODEOWNERS, contributing notes -> repo-index.yaml
    genbi repo branch <name> [--dir repo]    create the branch from HEAD (if new) and switch to it
    genbi repo status [--dir repo]
    genbi repo commit -m "message" [path ...] [--dir repo]    stage the named paths (default: every change) and commit
    genbi repo diff [--base <ref>] [--dir repo]               the working tree vs HEAD, or <ref>..HEAD
    genbi repo log [-n 20] [--dir repo]
    genbi repo scan [--dir repo]             the regex secret scan (keys, tokens, private keys, passwords in code)
    genbi repo push [--branch b] [--dir repo]

Git itself is dulwich (pure Python), so the agent image needs no git binary and the agent cannot run git directly:
Bash is limited to `genbi …`. The credential comes only from this process's environment — GENBI_REPO_USER and
GENBI_REPO_TOKEN, which the web app injects per run — and is never written to the clone's config, never printed.
Without it, clone and push work for public or local repositories only. The web app calls the same functions for
the clone before planning and the push at release (after a named approver accepts)."""
from __future__ import annotations

import io
import json
import os
import re
import time
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - PyYAML is in both images
    yaml = None

SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "dist", "build", "__pycache__", ".tox", ".mypy_cache", ".pytest_cache", "target", ".idea", ".vscode", "coverage"}
LANG_EXT = {".py": "Python", ".js": "JavaScript", ".mjs": "JavaScript", ".ts": "TypeScript", ".tsx": "TypeScript", ".jsx": "JavaScript", ".java": "Java", ".kt": "Kotlin", ".cs": "C#",
            ".go": "Go", ".rb": "Ruby", ".php": "PHP", ".sql": "SQL", ".sh": "Shell", ".ps1": "PowerShell", ".yaml": "YAML", ".yml": "YAML", ".json": "JSON", ".md": "Markdown",
            ".html": "HTML", ".css": "CSS", ".scala": "Scala", ".rs": "Rust", ".dtsx": "SSIS", ".xaml": "XAML", ".tf": "Terraform"}
RUNTIME = {"Python": "python:3.12-slim", "JavaScript": "node:22-slim", "TypeScript": "node:22-slim", "Java": "maven:3-eclipse-temurin-17", "Kotlin": "gradle:8-jdk17", "Go": "golang:1.23-alpine",
           "Ruby": "ruby:3.3-slim", "PHP": "php:8.3-cli", "C#": "mcr.microsoft.com/dotnet/sdk:8.0", "Rust": "rust:1-slim"}
SECRET_PATTERNS = [
    ("AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("GitHub fine-grained token", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{60,}\b")),
    ("Slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("Stripe key", re.compile(r"\b[sr]k_(live|test)_[0-9A-Za-z]{16,}\b")),
    ("private key block", re.compile(r"-----BEGIN (RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----")),
    ("JWT", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")),
    ("password in code", re.compile(r"(?i)\b(password|passwd|pwd)\s*[:=]\s*['\"][^'\"\s]{6,}['\"]")),
    ("API key or secret in code", re.compile(r"(?i)\b(api[_-]?key|secret[_-]?key|client[_-]?secret|access[_-]?token|auth[_-]?token)\s*[:=]\s*['\"][A-Za-z0-9_\-/+=]{16,}['\"]")),
    ("connection string with password", re.compile(r"(?i)(password|pwd)=[^;\s'\"]{4,}")),
]
SECRET_SKIP = {".lock", ".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip", ".parquet", ".woff", ".woff2", ".ico", ".svg", ".min.js"}
TEXT_EXT = {".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".kt", ".cs", ".go", ".rb", ".php", ".sql", ".sh", ".yaml", ".yml", ".json", ".toml", ".cfg", ".ini", ".env", ".txt", ".md", ".html", ".css", ".xml", ".properties", ".tf", ".ps1"}


class RepoError(Exception):
    pass


def _dulwich():
    try:
        from dulwich import porcelain
        from dulwich.repo import Repo
    except ImportError as e:  # pragma: no cover
        raise RepoError("dulwich is not installed in this image (pip install dulwich).") from e
    return porcelain, Repo


def _creds(creds: tuple | None = None) -> dict:
    """The credential for clone / push: given explicitly (the web app, in process) or from this run's environment
    (the agent through `genbi repo`). Never stored, never printed."""
    user, token = creds if creds else (os.environ.get("GENBI_REPO_USER"), os.environ.get("GENBI_REPO_TOKEN"))
    if not token:
        return {}
    return {"username": user or "x-access-token", "password": token}


def _author() -> bytes:
    return (os.environ.get("GENBI_REPO_AUTHOR") or "Relay agent <relay-agent@relay.invalid>").encode()


def _repo(path: Path):
    _, Repo = _dulwich()
    try:
        return Repo(str(path))
    except Exception as e:  # noqa: BLE001
        raise RepoError(f"{path} is not a git repository (clone it first: genbi repo clone <url>).") from e


def _hex(b) -> str:
    return b.decode() if isinstance(b, bytes) else str(b)


def current_branch(path: Path) -> str:
    r = _repo(path)
    chain = r.refs.follow(b"HEAD")[0]
    ref = chain[-1] if chain else b"HEAD"
    return _hex(ref).replace("refs/heads/", "")


def head(path: Path) -> str:
    try:
        return _hex(_repo(path).head())
    except KeyError:
        return ""


def remote_url(path: Path, remote: str = "origin") -> str | None:
    r = _repo(path)
    try:
        return _hex(r.get_config().get((b"remote", remote.encode()), b"url"))
    except KeyError:
        return None


def set_remote(path: Path, url: str, remote: str = "origin") -> None:
    """Name the remote of a repository made locally (tests seed a repository this way); credentials never go in."""
    if "@" in url.split("://", 1)[-1].split("/", 1)[0]:
        raise RepoError("Do not put a credential in the URL: it comes from the run's environment.")
    r = _repo(path)
    cfg = r.get_config()
    cfg.set((b"remote", remote.encode()), b"url", url.encode())
    cfg.set((b"remote", remote.encode()), b"fetch", f"+refs/heads/*:refs/remotes/{remote}/*".encode())
    cfg.write_to_path()


def init(path: Path, default_branch: str = "main"):
    porcelain, _ = _dulwich()
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    r = porcelain.init(str(path))
    r.refs.set_symbolic_ref(b"HEAD", f"refs/heads/{default_branch}".encode())
    return r


# ------------------------------------------------------------------ clone / branch / status / commit / diff / log / push

def clone(url: str, target: Path, branch: str | None = None, depth: int | None = None, creds: tuple | None = None) -> dict:
    porcelain, _ = _dulwich()
    target = Path(target)
    if target.exists() and any(target.iterdir()):
        raise RepoError(f"{target} exists and is not empty.")
    target.parent.mkdir(parents=True, exist_ok=True)
    if "@" in url.split("://", 1)[-1].split("/", 1)[0]:
        raise RepoError("Do not put a credential in the URL: it comes from the run's environment.")
    try:
        porcelain.clone(url, str(target), branch=branch.encode() if branch else None, depth=depth, errstream=io.BytesIO(), **_creds(creds))
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        if "401" in msg or "403" in msg or "nauthor" in msg or "credentials" in msg.lower():
            raise RepoError("The repository refused the sign-in (401/403): the token the web app injected is missing or has no access.") from e
        raise RepoError(f"Clone failed: {msg[:300]}") from e
    return {"dir": str(target), "branch": current_branch(target), "head": head(target), "url": url}


def branch(path: Path, name: str) -> dict:
    porcelain, _ = _dulwich()
    if not re.fullmatch(r"[A-Za-z0-9][\w./-]{0,120}", name) or name.endswith("/") or ".." in name:
        raise RepoError(f"Bad branch name {name!r}.")
    r = _repo(path)
    created = False
    if f"refs/heads/{name}".encode() not in r.refs:
        porcelain.branch_create(r, name)
        created = True
    porcelain.checkout(r, name)
    return {"branch": current_branch(path), "head": head(path), "created": created}


def status(path: Path) -> dict:
    porcelain, _ = _dulwich()
    st = porcelain.status(_repo(path))
    return {"branch": current_branch(path), "head": head(path), "staged": {k: [_hex(x) for x in v] for k, v in st.staged.items()},
            "unstaged": [_hex(x) for x in st.unstaged], "untracked": [_hex(x) for x in st.untracked]}


def commit(path: Path, message: str, paths: list[str] | None = None, author: str | None = None) -> dict:
    porcelain, _ = _dulwich()
    path = Path(path)
    r = _repo(path)
    message = (message or "").strip()
    if len(message) < 3:
        raise RepoError("Give the commit a message.")
    st = porcelain.status(r)
    changed = [_hex(x) for x in st.unstaged] + [_hex(x) for x in st.untracked]
    want = [p.strip("/").replace("\\", "/") for p in (paths or [])] or changed
    add, remove = [], []
    for p in want:
        if p.startswith(".git/") or p == ".git":
            continue
        full = path / p
        (add if full.exists() else remove).append(p)
    if add:
        porcelain.add(r, [str(path / p) for p in add])
    if remove:
        porcelain.remove(r, [str(path / p) for p in remove])
    st = porcelain.status(r)
    n = sum(len(v) for v in st.staged.values())
    if not n:
        raise RepoError("Nothing to commit: no change is staged (did you edit files under the clone?).")
    who = (author or "").encode() or _author()
    sha = porcelain.commit(r, message=message.encode(), author=who, committer=who)
    return {"commit": _hex(sha), "branch": current_branch(path), "files": n, "message": message.splitlines()[0][:120]}


def diff(path: Path, base: str | None = None, head_ref: str | None = None) -> str:
    porcelain, _ = _dulwich()
    r = _repo(path)
    buf = io.BytesIO()
    if base:
        porcelain.diff(r, commit=_resolve(r, base), commit2=_resolve(r, head_ref or "HEAD"), outstream=buf)
    else:
        porcelain.diff(r, outstream=buf)
    return buf.getvalue().decode("utf-8", errors="replace")


def _resolve(r, ref: str) -> bytes:
    if ref == "HEAD":
        return r.head()
    for cand in (ref.encode(), f"refs/heads/{ref}".encode(), f"refs/remotes/origin/{ref}".encode(), f"refs/remotes/{ref}".encode()):
        if cand in r.refs:
            return r.refs[cand]
    if re.fullmatch(r"[0-9a-f]{7,40}", ref):
        if len(ref) == 40:
            return ref.encode()
        for sha in r.object_store:
            if _hex(sha).startswith(ref):
                return sha
    raise RepoError(f"Unknown ref {ref!r}.")


def log(path: Path, n: int = 20, since: str | None = None) -> list[dict]:
    r = _repo(path)
    out = []
    try:
        head_sha = r.head()
    except KeyError:
        return out
    stop = _resolve(r, since) if since else None
    for e in r.get_walker(include=[head_sha], max_entries=n):
        if stop and e.commit.id == stop:
            break
        out.append({"sha": _hex(e.commit.id), "message": e.commit.message.decode("utf-8", errors="replace").strip(), "author": e.commit.author.decode("utf-8", errors="replace"), "time": e.commit.commit_time})
    return out


def changed_files(path: Path, base: str, head_ref: str = "HEAD") -> list[dict]:
    from dulwich.diff_tree import tree_changes
    r = _repo(path)
    a, b = _resolve(r, base), _resolve(r, head_ref)
    ta, tb = r[a].tree, r[b].tree
    out = []
    for ch in tree_changes(r.object_store, ta, tb):
        p = (ch.new.path or ch.old.path)
        out.append({"path": _hex(p), "status": ch.type})
    return out


def push(path: Path, branch_name: str | None = None, remote: str = "origin", creds: tuple | None = None) -> dict:
    porcelain, _ = _dulwich()
    r = _repo(path)
    b = branch_name or current_branch(path)
    url = remote_url(path, remote)
    if not url:
        raise RepoError(f"No remote {remote!r} in this clone.")
    spec = f"refs/heads/{b}:refs/heads/{b}".encode()
    try:
        res = porcelain.push(r, url, refspecs=[spec], outstream=io.BytesIO(), errstream=io.BytesIO(), **_creds(creds))
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        if "401" in msg or "403" in msg or "nauthor" in msg or "credentials" in msg.lower():
            raise RepoError("The repository refused the push (401/403): the token has no write access or is missing.") from e
        raise RepoError(f"Push failed: {msg[:300]}") from e
    bad = {k: v for k, v in (getattr(res, "ref_status", None) or {}).items() if v}
    if bad:
        raise RepoError("Push refused: " + "; ".join(f"{_hex(k)}: {v}" for k, v in bad.items()))
    return {"branch": b, "head": head(path), "remote": url.split("@")[-1]}


def ls_remote(url: str, creds: tuple | None = None) -> dict:
    """The branches a remote has (clone / push credentials apply); proves a repository is reachable."""
    porcelain, _ = _dulwich()
    try:
        res = porcelain.ls_remote(url, **_creds(creds))
    except Exception as e:  # noqa: BLE001
        raise RepoError(f"Cannot reach {url.split('@')[-1]}: {str(e)[:200]}") from e
    refs = getattr(res, "refs", res) or {}
    return {_hex(k).replace("refs/heads/", ""): _hex(v)[:12] for k, v in refs.items() if _hex(k).startswith("refs/heads/")}


# ------------------------------------------------------------------ the repository's conventions (indexed before planning)

def _files(root: Path, limit: int = 20000):
    n = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for f in filenames:
            n += 1
            if n > limit:
                return
            yield Path(dirpath) / f


def _read(p: Path, n: int = 4000) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")[:n]
    except OSError:
        return ""


def _codeowners(root: Path) -> list[dict]:
    for rel in ("CODEOWNERS", ".github/CODEOWNERS", "docs/CODEOWNERS"):
        p = root / rel
        if p.exists():
            out = []
            for line in _read(p, 20000).splitlines():
                line = line.split("#", 1)[0].strip()
                if line:
                    parts = line.split()
                    out.append({"pattern": parts[0], "owners": parts[1:]})
            return out
    return []


def index(path: Path) -> dict:
    """Languages, the test and lint commands, CODEOWNERS, contributing notes, CI and conventions — what the agent
    must follow. Written to repo-index.yaml next to the clone by the CLI; the web app keeps a copy on the request."""
    root = Path(path)
    if not (root / ".git").exists():
        raise RepoError(f"{root} is not a git clone.")
    counts: dict[str, int] = {}
    files = 0
    samples: list[Path] = []
    for f in _files(root):
        files += 1
        lang = LANG_EXT.get(f.suffix.lower())
        if lang:
            counts[lang] = counts.get(lang, 0) + 1
            if lang in ("Python", "JavaScript", "TypeScript", "Java", "C#", "Go") and len(samples) < 40:
                samples.append(f)
    langs = sorted(((l, n) for l, n in counts.items() if l not in ("YAML", "JSON", "Markdown", "HTML", "CSS")), key=lambda x: -x[1])
    main = langs[0][0] if langs else None
    has = lambda *names: any((root / n).exists() for n in names)  # noqa: E731
    pyproject = _read(root / "pyproject.toml") if (root / "pyproject.toml").exists() else ""
    pkg = {}
    if (root / "package.json").exists():
        try:
            pkg = json.loads(_read(root / "package.json", 200000))
        except ValueError:
            pkg = {}
    test_cmd = lint_cmd = None
    if has("Makefile") and re.search(r"^test\s*:", _read(root / "Makefile", 20000), re.M):
        test_cmd = "make test"
    elif has("pytest.ini", "conftest.py") or "[tool.pytest" in pyproject or ("tox.ini" in [p.name for p in root.iterdir()] and "pytest" in _read(root / "tox.ini")):
        test_cmd = "python -m pytest -q"
    elif (root / "tests").is_dir() and any(p.name.startswith("test") and p.suffix == ".py" for p in (root / "tests").iterdir()):
        test_cmd = "python -m pytest -q" if any("pytest" in _read(p, 20000) for p in (root / "tests").glob("test*.py")) else "python -m unittest discover -s tests -v"
    elif any(p.name.startswith("test_") and p.suffix == ".py" for p in root.iterdir()):
        test_cmd = "python -m unittest discover -v"
    elif (pkg.get("scripts") or {}).get("test"):
        test_cmd = "npm test"
    elif has("pom.xml"):
        test_cmd = "mvn -q test"
    elif has("build.gradle", "build.gradle.kts"):
        test_cmd = "gradle test"
    elif has("go.mod"):
        test_cmd = "go test ./..."
    elif any(p.suffix == ".csproj" for p in root.iterdir()):
        test_cmd = "dotnet test"
    if has("ruff.toml", ".ruff.toml") or "[tool.ruff" in pyproject:
        lint_cmd = "ruff check ."
    elif has(".flake8") or "[flake8]" in _read(root / "setup.cfg"):
        lint_cmd = "flake8"
    elif has(".eslintrc", ".eslintrc.json", ".eslintrc.js", ".eslintrc.cjs", "eslint.config.js", "eslint.config.mjs"):
        lint_cmd = "npx eslint ."
    elif has(".golangci.yml"):
        lint_cmd = "golangci-lint run"
    deps = [n for n in ("requirements.txt", "pyproject.toml", "setup.py", "Pipfile", "package.json", "package-lock.json", "pom.xml", "build.gradle", "go.mod", "Gemfile", "composer.json") if (root / n).exists()]
    ci = sorted(str(p.relative_to(root)).replace("\\", "/") for p in list((root / ".github" / "workflows").glob("*.y*ml")) + [root / n for n in (".gitlab-ci.yml", "azure-pipelines.yml", "bitbucket-pipelines.yml", "Jenkinsfile") if (root / n).exists()])
    crlf = spaces2 = spaces4 = tabs = long_lines = total = 0
    for p in samples:
        t = _read(p, 20000)
        lines = t.splitlines()
        total += len(lines)
        crlf += t.count("\r\n")
        for ln in lines:
            if ln.startswith("    "):
                spaces4 += 1
            elif ln.startswith("  "):
                spaces2 += 1
            elif ln.startswith("\t"):
                tabs += 1
            if len(ln) > 120:
                long_lines += 1
    indent = "tabs" if tabs > max(spaces2, spaces4) else "2 spaces" if spaces2 > spaces4 else "4 spaces"
    contributing = next((_read(root / n, 1500) for n in ("CONTRIBUTING.md", "CONTRIBUTING.rst", "CONTRIBUTING.txt", "docs/CONTRIBUTING.md", ".github/CONTRIBUTING.md") if (root / n).exists()), "")
    readme = next((_read(root / n, 800) for n in ("README.md", "README.rst", "README.txt", "README") if (root / n).exists()), "")
    out = {"indexed": time.time(), "files": files, "languages": [{"language": l, "files": n} for l, n in langs[:8]], "main_language": main,
           "runtime_image": RUNTIME.get(main) if main else None, "test_command": test_cmd, "lint_command": lint_cmd, "dependency_files": deps, "ci": ci,
           "codeowners": _codeowners(root), "contributing": contributing.strip(), "readme": readme.strip(), "branch": current_branch(root), "head": head(root),
           "conventions": {"indentation": indent, "line_endings": "CRLF" if crlf and crlf > total / 2 else "LF", "long_lines_over_120": long_lines, "sampled_files": len(samples)}}
    return out


def write_index(path: Path, out_file: Path | None = None) -> dict:
    out = index(path)
    target = Path(out_file) if out_file else Path(path).parent / "repo-index.yaml"
    if yaml:
        target.write_text(yaml.safe_dump(out, sort_keys=False, allow_unicode=True, width=110), encoding="utf-8")
    else:  # pragma: no cover
        target.write_text(json.dumps(out, indent=1), encoding="utf-8")
    out["file"] = str(target)
    return out


# ------------------------------------------------------------------ secret scan (always; no network, no tool needed)

def scan_secrets(path: Path, only: list[str] | None = None, max_bytes: int = 400_000) -> list[dict]:
    """Every text file (or just `only`) matched against the known key / token / password shapes; matches are masked."""
    root = Path(path)
    out = []
    targets = [root / p for p in only] if only else list(_files(root))
    for f in targets:
        if not f.is_file() or f.suffix.lower() in SECRET_SKIP or f.name.endswith(".min.js"):
            continue
        if f.suffix.lower() not in TEXT_EXT and f.name not in (".env", "Dockerfile", "Makefile") and f.suffix:
            continue
        try:
            if f.stat().st_size > max_bytes:
                continue
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            for label, rx in SECRET_PATTERNS:
                m = rx.search(line)
                if m:
                    hit = m.group(0)
                    out.append({"file": str(f.relative_to(root)).replace("\\", "/"), "line": i, "kind": label, "match": hit[:6] + "…" + hit[-3:] if len(hit) > 12 else "…"})
                    break
    return out


# ------------------------------------------------------------------ CLI

def cmd_repo(args) -> None:
    import sys
    cwd = Path.cwd()
    d = (cwd / args.dir) if not Path(args.dir).is_absolute() else Path(args.dir)
    try:
        if args.action == "clone":
            r = clone(args.url, d, args.branch, args.depth)
            print(f"Cloned {args.url} into {Path(r['dir']).name}/ (branch {r['branch']}, head {r['head'][:8]}).")
        elif args.action == "index":
            r = write_index(d, cwd / "repo-index.yaml")
            langs = ", ".join(f"{x['language']} {x['files']}" for x in r["languages"]) or "no code files"   # Python 3.11 in the agent image: no nested same-quote f-strings
            print(f"Indexed {r['files']} files: {langs}.")
            print(f"test: {r['test_command'] or 'not found'} · lint: {r['lint_command'] or 'not found'} · runtime: {r['runtime_image'] or '?'} · CODEOWNERS: {len(r['codeowners'])} rule(s) · CI: {', '.join(r['ci']) or 'none'}")
            print(f"conventions: {r['conventions']['indentation']}, {r['conventions']['line_endings']} line endings · written to repo-index.yaml")
        elif args.action == "branch":
            r = branch(d, args.name)
            print(f"On branch {r['branch']} ({'created' if r['created'] else 'existing'}, head {r['head'][:8]}).")
        elif args.action == "status":
            r = status(d)
            print(f"branch {r['branch']} · head {r['head'][:8]}")
            for k, v in r["staged"].items():
                for p in v:
                    print(f"staged {k}: {p}")
            for p in r["unstaged"]:
                print(f"changed: {p}")
            for p in r["untracked"]:
                print(f"new: {p}")
            if not any(r["staged"].values()) and not r["unstaged"] and not r["untracked"]:
                print("clean")
        elif args.action == "commit":
            r = commit(d, args.message, args.paths or None)
            print(f"[{r['branch']} {r['commit'][:8]}] {r['message']} ({r['files']} file(s))")
        elif args.action == "diff":
            text = diff(d, args.base)
            print(text if text.strip() else "(no differences)")
        elif args.action == "log":
            for e in log(d, args.n):
                print(f"{e['sha'][:8]} {time.strftime('%Y-%m-%d %H:%M', time.gmtime(e['time']))} {e['author']}: {e['message'].splitlines()[0][:100]}")
        elif args.action == "scan":
            hits = scan_secrets(d)
            for x in hits:
                print(f"{x['file']}:{x['line']}: {x['kind']} ({x['match']})")
            print(f"secret scan: {len(hits)} finding(s)")
            if hits:
                sys.exit(1)
        elif args.action == "push":
            r = push(d, args.branch)
            print(f"Pushed {r['branch']} ({r['head'][:8]}) to {r['remote']}.")
    except RepoError as e:
        print(f"genbi repo: {e}")
        sys.exit(1)
