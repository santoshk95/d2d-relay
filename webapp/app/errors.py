"""Relay's own crashes, for Relay Doctor (doctor/doctor.py: a service on the Windows PC next to Docker).

Every unexpected exception in Relay's own code becomes one JSON log line, event `app.error`, with a fingerprint. The
Doctor reads the web app's log, opens one incident per fingerprint, fixes the cause on a copy of the code, proves it
and deploys it (doctor/README.md).

A bug is a programming error (KeyError, TypeError, AttributeError, NameError, IndexError, ...) or a database
programming error (no such column / table, a column that does not exist), raised with Relay's own code on the stack
(webapp/app, genbi_kit). Not a bug, and never reported: what the app raises on purpose for a person (HTTPException,
AgentError, QuotaError, ValueError, a module's own *Error), timeouts and connection errors, a stopped job, a file read
while it was being written (OSError) - people already see those, and a code change would not help.

Reported from: requests (main.py's handler for unexpected exceptions), every `traceback.print_exc()` in the code
(install() wraps it, so the job worker and every background loop report without changes), asyncio tasks nobody
awaited, threads. CONTEXT adds what the code was doing (the worker sets the job kind and the project).

The fingerprint is the error type + the deepest frame in Relay's code (file and function, not the line, so an edit
above it does not open a new incident); doctor.py computes the same one from a raw traceback when the app cannot even
start. Messages are cut short and cleaned of anything that looks like a secret or an email address. One line per
fingerprint at most every EVERY_S seconds (`repeats` counts the ones in between).
"""
from __future__ import annotations

import contextvars
import hashlib
import json
import os
import re
import sys
import threading
import time
import traceback
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent                    # /srv/app in the image = webapp/app in the repository
try:
    import genbi_kit
    KIT_DIR: Path | None = Path(genbi_kit.__file__).resolve().parent
except Exception:  # noqa: BLE001 - the toolkit is optional for this module
    KIT_DIR = None
ROOTS = [(APP_DIR, "webapp/app"), (KIT_DIR, "genbi_kit")]

BUG_TYPES = {"KeyError", "TypeError", "AttributeError", "NameError", "UnboundLocalError", "IndexError", "ImportError",
             "ModuleNotFoundError", "AssertionError", "ZeroDivisionError", "RecursionError", "SyntaxError", "StopIteration"}
DB_TYPES = {"OperationalError", "ProgrammingError", "UndefinedColumn", "UndefinedTable", "UndefinedFunction", "InvalidColumnReference"}
DB_BUG = re.compile(r"no such (column|table|function)|has no column named|column .{1,80} does not exist|relation .{1,80} does not exist"
                    r"|function .{1,80} does not exist|syntax error at or near|: syntax error", re.I)
EVERY_S = 30
INSTANCE = os.environ.get("D2D_INSTANCE", "local")
CONTEXT: contextvars.ContextVar[dict] = contextvars.ContextVar("relay_error_context", default={})
RECENT: dict[str, dict] = {}          # fingerprint -> what this process has seen (Admin > Operations > Relay Doctor)
_LOCK = threading.Lock()
_ORIG_PRINT_EXC = traceback.print_exc
_CTX_KEYS = ("route", "method", "kind", "pid", "job", "tenant", "at")

SECRETS = [
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}"), r"\1 <hidden>"),
    (re.compile(r"(?i)\b(password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|authorization|cookie|session)\b"
                r"(\s*[\"']?\s*[:=]\s*[\"']?)[^\s\"',;&}]+"), r"\1\2<hidden>"),
    (re.compile(r"://[^/\s:@]+:[^@\s/]+@"), "://<hidden>@"),
    (re.compile(r"\b(sk|pk|rk|ghp|gho|ghu|github_pat|xox[abprs])[-_][A-Za-z0-9_-]{8,}"), "<hidden>"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{4,}"), "<hidden>"),
    (re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+"), "<email>"),
    (re.compile(r"\b[A-Fa-f0-9]{40,}\b"), "<hex>"),
]


def scrub(text: str, limit: int) -> str:
    """Secrets and email addresses out; long text keeps its head and its end (where a traceback names the error)."""
    for rx, rep in SECRETS:
        text = rx.sub(rep, text)
    if len(text) > limit:
        head = limit // 4
        text = text[:head] + "\n... (cut) ...\n" + text[-(limit - head - 12):]
    return text


def relay_path(filename: str) -> str | None:
    """'webapp/app/home.py' for a file of Relay's own code, else None."""
    try:
        p = Path(filename).resolve()
    except (OSError, ValueError):
        return None
    for root, rel in ROOTS:
        if root is not None and (p == root or root in p.parents):
            return f"{rel}/{p.relative_to(root).as_posix()}"
    return None


def frames(exc: BaseException) -> list[dict]:
    """Relay's own frames of the traceback, outermost first."""
    out = []
    for fs in traceback.extract_tb(exc.__traceback__):
        rel = relay_path(fs.filename)
        if rel:
            out.append({"file": rel, "line": fs.lineno, "func": fs.name})
    return out


def is_bug(exc: BaseException, fr: list[dict]) -> bool:
    if not fr:
        return False
    name = type(exc).__name__
    if name in BUG_TYPES:
        return True
    module = type(exc).__module__ or ""
    if name in DB_TYPES or module.startswith(("sqlite3", "psycopg")):
        return bool(DB_BUG.search(str(exc)))
    return False


def fingerprint(type_name: str, file: str, func: str) -> str:
    """The incident key, shared with doctor/doctor.py (which reads it back from a raw traceback)."""
    return hashlib.sha1(f"{type_name}|{file}|{func}".encode()).hexdigest()[:12]


def _message(exc: BaseException) -> str:
    try:
        return str(exc) or type(exc).__name__
    except Exception:  # noqa: BLE001 - a __str__ that fails must not hide the crash
        return type(exc).__name__


def _context(c: dict) -> dict:
    return {k: scrub(str(c[k]), 160) for k in _CTX_KEYS if c.get(k) not in (None, "")}


def _tb_text(exc: BaseException) -> str:
    try:
        return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    except Exception:  # noqa: BLE001
        return f"{type(exc).__name__}: {_message(exc)}"


def report(exc: BaseException | None, where: str | None = None, **ctx) -> dict | None:
    """Log an `app.error` line for a bug (once per exception, at most every EVERY_S seconds per fingerprint).
    Returns the fingerprint's summary for a bug, None for anything else."""
    if exc is None or getattr(exc, "_relay_reported", False):
        return None
    try:
        exc._relay_reported = True                           # the worker's handler and print_exc must not report it twice
    except (AttributeError, TypeError):
        pass
    if isinstance(exc, (KeyboardInterrupt, SystemExit, GeneratorExit)) or type(exc).__name__ == "CancelledError":
        return None
    fr = frames(exc)
    if not is_bug(exc, fr):
        return None
    deep, kind, now = fr[-1], type(exc).__name__, time.time()
    c = {**CONTEXT.get(), **ctx}
    where = where or c.get("where") or "background"
    fp = fingerprint(kind, deep["file"], deep["func"])
    with _LOCK:
        r = RECENT.get(fp)
        if r is None:
            r = RECENT[fp] = {"fp": fp, "type": kind, "file": deep["file"], "func": deep["func"], "first": now, "count": 0, "printed": 0.0, "held": 0}
        r.update(count=r["count"] + 1, last=now, line=deep["line"], message=scrub(_message(exc), 300), where=where, context=_context(c))
        if now - r["printed"] < EVERY_S:
            r["held"] += 1
            return r
        held, r["held"], r["printed"] = r["held"], 0, now
        if len(RECENT) > 200:
            for old in sorted(RECENT, key=lambda k: RECENT[k]["last"])[:50]:
                RECENT.pop(old, None)
    line = {"ts": round(now, 3), "level": "error", "instance": INSTANCE, "event": "app.error", "fp": fp, "type": kind,
            "message": r["message"], "file": deep["file"], "line": deep["line"], "func": deep["func"], "where": where,
            "context": r["context"], "repeats": held, "frames": [f"{f['file']}:{f['line']} {f['func']}" for f in fr[-12:]],
            "traceback": scrub(_tb_text(exc), 8000)}
    try:
        print(json.dumps(line, default=str), file=sys.stdout, flush=True)
    except Exception:  # noqa: BLE001 - a closed stdout must never turn one crash into two
        pass
    return r


def recent(n: int = 20) -> list[dict]:
    """The bugs this process has seen, newest first (no internal counters)."""
    with _LOCK:
        rows = sorted(RECENT.values(), key=lambda r: -r["last"])[:n]
        return [{k: v for k, v in r.items() if k not in ("printed", "held")} for r in rows]


def _caller() -> str:
    """Which function called traceback.print_exc (for a background loop with no other context)."""
    try:
        f = sys._getframe(2)                                     # noqa: SLF001 - 0 = here, 1 = _print_exc, 2 = its caller
        rel = relay_path(f.f_code.co_filename) or f.f_code.co_filename
        return f"{rel.rsplit('/', 1)[-1].removesuffix('.py')}.{f.f_code.co_name}"
    except (ValueError, AttributeError):
        return ""


def _print_exc(*args, **kwargs):
    _ORIG_PRINT_EXC(*args, **kwargs)
    try:
        exc = sys.exc_info()[1]
        if exc is not None:
            report(exc, at=_caller())
    except Exception:  # noqa: BLE001 - reporting must never break the code that only wanted to print
        pass


def install() -> None:
    """Report from every traceback.print_exc() and from threads (main.py calls this once, at import)."""
    if traceback.print_exc is not _print_exc:
        traceback.print_exc = _print_exc
    if getattr(threading.excepthook, "_relay", False):
        return
    previous = threading.excepthook

    def _thread_hook(args):
        try:
            report(args.exc_value, "thread")
        finally:
            previous(args)
    _thread_hook._relay = True
    threading.excepthook = _thread_hook


def install_loop(loop) -> None:
    """Report exceptions of asyncio tasks nobody awaited ("Task exception was never retrieved")."""
    def _handler(lp, context):
        try:
            report(context.get("exception"), "task")
        finally:
            lp.default_exception_handler(context)
    loop.set_exception_handler(_handler)
