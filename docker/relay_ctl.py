#!/usr/local/bin/python3
"""relay-ctl: look after Relay inside its container.

    docker exec relay relay-ctl status                 the parts, their health and the version
    docker exec relay relay-ctl restart <part>         web | agent | database | gateway
    docker exec relay relay-ctl db-dump [file|-]       a dump of the database (default: /data/backups/relay-db-<time>.dump)
    docker exec -it relay relay-ctl login              sign the AI engine in to Claude (opens Claude Code's /login)
    docker exec relay relay-ctl export [file]          database, keys, gateway settings, projects and library in one file
                                                       (default: /data/backups/relay-export-<time>.tar.gz)
    relay-ctl import <file>                            an export into a NEW install, before its first start
    relay-ctl health                                   Docker's health check: 0 when the web app, AI engine and database answer
    relay-ctl stage-import <dump>                      load this dump when a NEW data volume starts (moving an install)
    relay-ctl copy-state <folder>                      copy state/ and llm/ (keys, secrets, gateway settings) from an older install
    relay-ctl version
"""
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

PGBIN = Path("/usr/lib/postgresql/17/bin")
CONF = "/run/relay/supervisord.conf"
PARTS = ("web", "agent", "database", "gateway")


def supervisor_env() -> dict:
    out = {}
    try:
        for line in Path("/run/relay/supervisor.env").read_text().splitlines():
            k, _, v = line.partition("=")
            out[k] = v
    except OSError:
        pass
    return out


def embedded_db() -> bool:
    return supervisor_env().get("RELAY_DB_AUTOSTART") == "true"


def answers(url: str, timeout: float = 10) -> tuple[bool, dict | None]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            body = r.read()
        try:
            return True, json.loads(body)
        except ValueError:
            return True, None
    except Exception:  # noqa: BLE001
        return False, None


def db_ready() -> bool:
    """Signs in as postgres, as postgres (peer): a check that never leaves a failed sign-in in the database's log."""
    args = [str(PGBIN / "pg_isready"), "-q", "-h", "/run/postgresql", "-d", "postgres", "-U", "postgres"]
    kw = {"user": "postgres", "group": "postgres", "extra_groups": []} if os.getuid() == 0 else {}
    return subprocess.run(args, **kw).returncode == 0


def health() -> int:
    web, _ = answers("http://127.0.0.1:8000/healthz")
    agent, _ = answers("http://127.0.0.1:8090/health")
    db = db_ready() if embedded_db() else True
    bad = [n for n, ok in (("web app", web), ("AI engine", agent), ("database", db)) if not ok]
    print("healthy" if not bad else "not answering: " + ", ".join(bad))
    return 0 if not bad else 1


def ctl(*args: str) -> int:
    return subprocess.run(["supervisorctl", "-c", CONF, *args]).returncode


def status() -> int:
    print(f"RELAY by PASDACS {os.environ.get('RELAY_VERSION', '')} · commit {os.environ.get('RELAY_COMMIT', '')[:12] or 'not recorded'}")
    ctl("status")
    _, h = answers("http://127.0.0.1:8090/health", 5)
    if h:
        lanes = ", ".join(f"{k} {'busy' if v else 'free'}" for k, v in (h.get("lanes") or {}).items())
        print(f"AI engine: {lanes} · runners {', '.join(h.get('runners') or [])}")
    print("health:", end=" ", flush=True)
    return health()


def restart(part: str) -> int:
    if part not in PARTS:
        sys.exit(f"relay-ctl: the parts are {', '.join(PARTS)}")
    return ctl("restart", part)


def as_user(user: str, args: list, **kw) -> subprocess.CompletedProcess:
    if os.getuid() != 0:
        sys.exit("relay-ctl: run this as root (docker exec relay relay-ctl ...)")
    env = json.loads(Path(f"/run/relay/env/{'web' if user == 'relay' else 'agent'}.json").read_text())
    return subprocess.run(args, user=user, group=user, extra_groups=["relaydata"], env=env, **kw)


def db_dump(target: str | None) -> int:
    if not embedded_db():
        sys.exit("relay-ctl: this container does not run its own database (RELAY_DATABASE or RELAY_DATABASE_URL)")
    args = [str(PGBIN / "pg_dump"), "-h", "/run/postgresql", "-U", "relay_app", "-d", "relay", "-Fc"]
    if target == "-":
        return as_user("relay", args).returncode
    path = Path(target or time.strftime("/data/backups/relay-db-%Y%m%d-%H%M%S.dump"))
    with open(path, "wb") as out:
        r = as_user("relay", args, stdout=out)
    if r.returncode:
        path.unlink(missing_ok=True)
        return r.returncode
    print(f"{path} ({path.stat().st_size // 1024} KB)")
    return 0


def stage_import(src: str) -> int:
    p = Path(src)
    if not p.is_file():
        sys.exit(f"relay-ctl: {src} is not a file")
    dest = Path("/data/import")
    dest.mkdir(parents=True, exist_ok=True)
    os.chmod(dest, 0o700)
    shutil.copyfile(p, dest / "relay.dump")
    print(f"staged {p.name}: it is loaded at the next start, if the database is still empty (a new data volume)")
    return 0


def copy_state(src: str) -> int:
    base = Path(src)
    copied = []
    for sub, mode in (("state", 0o600), ("llm", 0o640)):
        s, d = base / sub, Path("/data") / sub
        if not s.is_dir():
            continue
        d.mkdir(parents=True, exist_ok=True)
        for f in s.iterdir():
            if not f.is_file() or f.name == "index.db":     # index.db: the old SQLite index, unused with PostgreSQL
                continue
            shutil.copyfile(f, d / f.name)
            os.chown(d / f.name, 1001, 1001)
            os.chmod(d / f.name, mode)
            copied.append(f"{sub}/{f.name}")
        os.chown(d, 1001, 1001)
    print("copied: " + (", ".join(copied) or "nothing (no state/ or llm/ folder there)"))
    return 0


SKIP_PROJECT_DIRS = {".daxcheck", ".doctor", ".test-projects"}     # live queues and test copies stay with this install


def export(target: str | None) -> int:
    """Everything an install keeps, in one file: the database dump, the keys and secrets, the gateway settings, the
    projects and the visual library (for a new PC: relay-ctl import)."""
    if os.getuid() != 0:
        sys.exit("relay-ctl: run this as root (docker exec relay relay-ctl export)")
    import tarfile
    import tempfile
    path = Path(target or time.strftime("/data/backups/relay-export-%Y%m%d-%H%M%S.tar.gz"))
    with tempfile.TemporaryDirectory() as tmp:
        dump = Path(tmp) / "relay.dump"
        os.chown(tmp, 1001, 1001)
        if embedded_db() and db_dump(str(dump)):
            return 1
        manifest = {"relay": os.environ.get("RELAY_VERSION", ""), "commit": os.environ.get("RELAY_COMMIT", ""), "time": time.time(),
                    "database": dump.exists()}
        (Path(tmp) / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")

        def projects(info):
            first = info.name.split("/")[1] if info.name.count("/") else ""
            return None if first in SKIP_PROJECT_DIRS else info

        with tarfile.open(path, "w:gz") as tar:
            tar.add(Path(tmp) / "manifest.json", "manifest.json")
            if dump.exists():
                tar.add(dump, "relay.dump")
            for src, name, flt in (("/data/state", "state", lambda i: None if i.name.endswith("/index.db") else i),
                                   ("/data/llm", "llm", None), ("/data/projects", "projects", projects),
                                   ("/opt/genbi/library", "library", None)):
                if Path(src).is_dir():
                    tar.add(src, name, filter=flt)
    print(f"{path} ({path.stat().st_size // 1048576} MB). It holds the key to the saved credentials: keep it as safe as the PC.")
    return 0


def import_(src: str) -> int:
    """Before the first start on a new data volume: the projects, library, keys and gateway settings from an export,
    and its database dump staged for relay-init."""
    if os.getuid() != 0:
        sys.exit("relay-ctl: run this as root")
    import tarfile
    if (Path("/data/postgres") / "PG_VERSION").exists():
        sys.exit("relay-ctl: this install already has a database. Import into a new data volume (a new install) only.")
    if any(p.name not in SKIP_PROJECT_DIRS for p in Path("/data/projects").iterdir()) if Path("/data/projects").is_dir() else False:
        sys.exit("relay-ctl: the projects folder is not empty. Import into an empty projects folder only.")
    with tarfile.open(src, "r:*") as tar:
        names = set(tar.getnames())
        if "manifest.json" not in names:
            sys.exit("relay-ctl: this is not a Relay export (no manifest.json)")
        tmp = Path("/data/import/.unpack")
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True)
        tar.extractall(tmp, filter="data")
    # owners as relay-init sets them: projects shared by the web app and the AI engine, the rest the web app's own
    moves = (("projects", Path("/data/projects"), 1001, 1002, 0o2775, 0o664), ("library", Path("/opt/genbi/library"), 1001, 1001, 0o2755, 0o644),
             ("state", Path("/data/state"), 1001, 1001, 0o700, 0o600), ("llm", Path("/data/llm"), 1001, 1001, 0o750, 0o640))
    for name, dest, uid, gid, dmode, fmode in moves:
        if (tmp / name).is_dir():
            shutil.copytree(tmp / name, dest, dirs_exist_ok=True)
            for p in [dest, *dest.rglob("*")]:
                try:
                    os.chown(p, uid, gid)
                    os.chmod(p, dmode if p.is_dir() else fmode)
                except OSError:
                    pass
    if (tmp / "relay.dump").exists():
        shutil.move(str(tmp / "relay.dump"), "/data/import/relay.dump")
    shutil.rmtree(tmp, ignore_errors=True)
    print("imported: projects, library, keys and gateway settings; the database is loaded at the first start")
    return 0


def login() -> int:
    print("Signing the AI engine in to Claude: type /login in Claude Code, follow the link, then /exit.")
    return as_user("agent", ["claude"], cwd="/home/agent").returncode


def main(argv: list[str]) -> int:
    cmd, rest = (argv[0] if argv else "status"), argv[1:]
    if cmd == "health":
        return health()
    if cmd == "status":
        return status()
    if cmd == "restart" and rest:
        return restart(rest[0])
    if cmd == "db-dump":
        return db_dump(rest[0] if rest else None)
    if cmd == "stage-import" and rest:
        return stage_import(rest[0])
    if cmd == "copy-state" and rest:
        return copy_state(rest[0])
    if cmd == "export":
        return export(rest[0] if rest else None)
    if cmd == "import" and rest:
        return import_(rest[0])
    if cmd == "login":
        return login()
    if cmd == "version":
        print(os.environ.get("RELAY_VERSION", ""), os.environ.get("RELAY_COMMIT", ""))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
