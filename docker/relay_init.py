#!/usr/local/bin/python3
"""RELAY by PASDACS: the container's start-up, run as root before the supervisor starts the parts.

1. Settings. The documented RELAY_* names (.env.example) are copied to the names the code reads (D2D_*), unless those
   are set themselves. Values the parts need to find each other inside the container are fixed here.
2. Folders under /data with the right owners. State (keys, secrets), the gateway's credentials and the database are
   private to the web app or PostgreSQL; projects are shared by the web app and the AI engine; the visual library is
   written by the web app and read by the AI engine. Folders an older layout left behind (the per-part stack's web
   app wrote them as uid 1000) are brought into this layout at the start.
3. The database. A new PostgreSQL cluster on the first start: no network listener at all, and each Linux user signs
   in over the Unix socket as its own database role (peer). A dump staged in /data/import (relay-ctl stage-import) is
   loaded into an empty database.
4. One environment per part, read by the launcher (docker/launch.py). The AI engine gets only what it needs, never
   the web app's keys or passwords.

D2D Relay runs this image as several containers, one role each (RELAY_ROLE, docker-compose.yml):
  all       every part in one container (the layout before the split; still works)
  database  PostgreSQL only, for the other containers: it listens on the private Docker network and the app's role
            signs in with a password (RELAY_DB_PASSWORD). Nothing else runs.
  web       the public site: web app + AI engine (+ gateway); the database is the `database` container's
  admin     the admin portal: the web app only (D2D_PORTAL=admin); no AI engine, gateway or job queue
"""
import grp
import json
import os
import pwd
import secrets
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path

PGBIN = Path("/usr/lib/postgresql/17/bin")
PGDATA = Path("/data/postgres")
SOCKET_DIR = "/run/postgresql"
RUN = Path("/run/relay")
EMBEDDED_URL = f"postgresql://relay_app@/relay?host={SOCKET_DIR}"
LIBRARY = Path("/opt/genbi/library")
SEED_LIBRARY = Path("/opt/relay/seed/library")

# RELAY_* names that are not D2D_* settings: compose's own (folders, ports, volume names) or read under their own name
NOT_MAPPED = {"RELAY_VERSION", "RELAY_COMMIT", "RELAY_EXPORT_KEY", "RELAY_DATABASE", "RELAY_GATEWAY", "RELAY_PROJECTS",
              "RELAY_BACKUPS", "RELAY_LIBRARY", "RELAY_CONFIG", "RELAY_PORT", "RELAY_LAN_IP", "RELAY_CLAUDE_VOLUME",
              "RELAY_CLAUDE_EXTERNAL", "RELAY_AGY_VOLUME", "RELAY_AGY_EXTERNAL", "RELAY_AGY_IMAGE", "RELAY_AGENT_MODEL",
              "RELAY_IMAGE", "RELAY_ROLE", "RELAY_DB_PASSWORD", "RELAY_ADMIN_PORT", "RELAY_ADMIN_PUBLIC_URL"}
ROLES = ("all", "database", "web", "admin")
# What the AI engine may receive from the container's environment (everything else stays with the web app)
AGENT_PASS = {"AGENT_MODEL", "MODELS_FILE", "TZ", "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "NODE_EXTRA_CA_CERTS",
              "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "no_proxy"}
AGENT_PREFIXES = ("CLAUDE_CODE_", "ANTHROPIC_", "AGY_")


def say(msg: str) -> None:
    print(f"relay-init: {msg}", flush=True)


def ids(user: str) -> tuple[int, int]:
    p = pwd.getpwnam(user)
    return p.pw_uid, p.pw_gid


def own(path: Path, user: str | None, group: str | None = None, mode: int | None = None) -> None:
    """chown/chmod, quietly accepting folders mounted from a host that does not keep Linux owners (Windows)."""
    try:
        uid = pwd.getpwnam(user).pw_uid if user else -1
        gid = grp.getgrnam(group).gr_gid if group else -1
        os.chown(path, uid, gid)
        if mode is not None:
            os.chmod(path, mode)
    except OSError:
        pass


def folder(path: Path, user: str | None, group: str | None, mode: int) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    own(path, user, group, mode)
    return path


def entries(top: Path, depth: int | None = None):
    """Every entry under top (not top itself), without following links; depth 1 = top's own children."""
    stack = [(top, 1)]
    while stack:
        d, level = stack.pop()
        try:
            with os.scandir(d) as it:
                for e in it:
                    yield e
                    if e.is_dir(follow_symlinks=False) and (depth is None or level < depth):
                        stack.append((Path(e.path), level + 1))
        except OSError:
            continue


def lstat(e: os.DirEntry) -> os.stat_result | None:
    """None when the entry went away meanwhile (the DAX checker on the host removes its requests at any time)."""
    try:
        return e.stat(follow_symlinks=False)
    except OSError:
        return None


def open_to_all(st: os.stat_result | None) -> bool:
    """Links, entries a process on the host wrote through the mount (no Linux owner: open to everyone), and entries
    that are gone."""
    return st is None or stat.S_ISLNK(st.st_mode) or bool(st.st_mode & stat.S_IWOTH)


def unshared(st: os.stat_result | None, gid: int) -> bool:
    """A member of the projects group could not read and write it (or, for a folder, enter it and pass the group on)."""
    if open_to_all(st):
        return False
    need = stat.S_IRGRP | stat.S_IWGRP | (stat.S_IXGRP | stat.S_ISGID if stat.S_ISDIR(st.st_mode) else 0)
    return st.st_gid != gid or (st.st_mode & need) != need


def share_projects(root: Path) -> None:
    """Project folders written before the move to one container belong to the per-part web app (uid 1000, now the AI
    engine's user) with 755/644: the web app here could read them but not save them. Give them the shared layout that
    new folders get (group relaydata, group read/write, setgid folders; owners unchanged, nothing rewritten). A look at
    the first two levels decides whether the full walk is needed, so a normal start costs a few hundred stats."""
    gid = grp.getgrnam("relaydata").gr_gid
    if not any(unshared(lstat(e), gid) for e in entries(root, 2)):
        return
    fixed = 0
    for e in entries(root):
        try:
            st = lstat(e)
            if not unshared(st, gid):
                continue
            if st.st_gid != gid:
                os.chown(e.path, -1, gid, follow_symlinks=False)
            mode = stat.S_IMODE(st.st_mode) | stat.S_IRGRP | stat.S_IWGRP
            if stat.S_ISDIR(st.st_mode):
                mode |= stat.S_IXGRP | stat.S_ISGID
            elif st.st_mode & stat.S_IXUSR:
                mode |= stat.S_IXGRP
            os.chmod(e.path, mode)
            fixed += 1
        except OSError:
            continue
    if fixed:
        say(f"projects: {fixed} files and folders the web app or the AI engine could not change are now shared by both")


def own_all(root: Path, user: str) -> None:
    """The web app's own folders (visual library, backups): entries another user made there go to the web app's user,
    so it can update and prune them: the per-part stack's web app (uid 1000) before the move, or a database dump that
    `relay-ctl db-dump` wrote as root. Same two-level look first."""
    uid, gid = ids(user)
    if not any(not open_to_all(st) and st.st_uid != uid for st in (lstat(e) for e in entries(root, 2))):
        return
    fixed = 0
    for e in entries(root):
        try:
            st = lstat(e)
            if open_to_all(st) or st.st_uid == uid:
                continue
            os.chown(e.path, uid, gid, follow_symlinks=False)
            fixed += 1
        except OSError:
            continue
    if fixed:
        say(f"{root}: {fixed} files and folders made by another user now belong to the web app")


def settings() -> dict[str, str]:
    env = dict(os.environ)
    for k, v in list(env.items()):
        if k.startswith("RELAY_") and k not in NOT_MAPPED and not k.startswith("RELAY_DOCTOR_") and v != "":
            env.setdefault("D2D_" + k[len("RELAY_"):], v)
    if env.get("RELAY_AGENT_MODEL"):                 # unset: the web app follows config/models.json's default
        env.setdefault("AGENT_MODEL", env["RELAY_AGENT_MODEL"])
    env.setdefault("D2D_AUTH", "single")
    env.setdefault("D2D_ADMIN_EMAIL", "admin@local")
    env.setdefault("D2D_INSTANCE", "local")
    env.setdefault("HEAL_AUTO_DIAGNOSE", "0")
    if env.get("D2D_INSTANCES", "off") == "on":
        say("per-person workspaces need the multi-container deployment (docker-compose.dev.yml or Kubernetes): off here")
    # where the parts find each other inside this container
    env.update({
        "D2D_INSTANCES": "off",
        "AGENT_URL": "http://127.0.0.1:8090",
        "D2D_RUNNER_URLS": json.dumps({r: "http://127.0.0.1:8090" for r in ("codex", "gemini", "antigravity")}),
        "D2D_LITELLM_URL": "http://127.0.0.1:4000",
        "D2D_LITELLM_DIR": "/data/llm",
        "D2D_STATE": "/data/state",
        "D2D_BACKUPS": "/data/backups",
        "WORKSPACES": "/data/projects",
        "GENBI_LIBRARY": str(LIBRARY),
        "RELAY_SUPERVISOR_CONF": "/run/relay/supervisord.conf",
    })
    role = (env.get("RELAY_ROLE") or "all").strip().lower()
    if role not in ROLES:
        raise SystemExit(f"relay-init: RELAY_ROLE must be one of {', '.join(ROLES)}, not {role!r}")
    env["RELAY_ROLE"] = role
    env["D2D_PORTAL"] = "admin" if role == "admin" else "public"
    mode = env.get("RELAY_DATABASE", "postgres").strip().lower() or "postgres"
    if role == "database":                           # this container IS the database: always the built-in one
        if not env.get("RELAY_DB_PASSWORD"):
            raise SystemExit("relay-init: the database container needs RELAY_DB_PASSWORD (.env)")
        env["RELAY_DB"], env["D2D_DATABASE_URL"] = "embedded", EMBEDDED_URL
    elif role in ("web", "admin") and not env.get("D2D_DATABASE_URL"):
        raise SystemExit(f"relay-init: the {role} container needs RELAY_DATABASE_URL (the database container)")
    elif env.get("D2D_DATABASE_URL"):
        env["RELAY_DB"] = "external"
    elif mode == "sqlite":
        env["RELAY_DB"], env["D2D_DATABASE_URL"] = "sqlite", ""
    else:
        env["RELAY_DB"], env["D2D_DATABASE_URL"] = "embedded", EMBEDDED_URL
    return env


def folders(role: str = "all") -> None:
    folder(RUN, "root", "root", 0o755)
    folder(RUN / "env", "root", "root", 0o711)
    folder(Path("/data"), "root", "root", 0o755)
    if role == "database":                           # the database container keeps only the database (and dumps to load)
        folder(Path("/data/import"), "root", "root", 0o700)
        return
    folder(Path("/data/state"), "relay", "relay", 0o700)
    folder(Path("/data/llm"), "relay", "relay", 0o750)
    folder(Path("/data/import"), "root", "root", 0o700)
    own_all(folder(Path("/data/backups"), "relay", "relay", 0o750), "relay")
    # shared by the web app and the AI engine (setgid: new files keep the group; both run with umask 002)
    share_projects(folder(Path("/data/projects"), None, "relaydata", 0o2775))
    # written by the web app (it adds visuals that passed their checks), read by the AI engine
    own_all(folder(LIBRARY, "relay", "relay", 0o2755), "relay")
    if SEED_LIBRARY.is_dir() and not any(LIBRARY.iterdir()):
        shutil.copytree(SEED_LIBRARY, LIBRARY, dirs_exist_ok=True)
        uid, gid = ids("relay")
        for p in [LIBRARY, *LIBRARY.rglob("*")]:
            try:
                os.chown(p, uid, gid)
            except OSError:
                pass
        say("visual library: started from the visuals this image ships with")
    # the AI engine's Claude sign-in (a volume; a new one starts empty and root-owned)
    claude = Path("/home/agent/.claude")
    claude.mkdir(parents=True, exist_ok=True)
    if claude.stat().st_uid == 0:
        own(claude, "agent", "agent", 0o700)
    for p in ("/tmp", "/var/tmp"):
        os.chmod(p, 0o1777)


def run_as(user: str, args: list, **kw) -> subprocess.CompletedProcess:
    home = pwd.getpwnam(user).pw_dir
    env = {"PATH": f"{PGBIN}:/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "HOME": home, "USER": user}
    return subprocess.run([str(a) for a in args], user=user, group=user, extra_groups=[], env=env, cwd="/", **kw)


def psql(sql: str, db: str = "postgres") -> str:
    r = run_as("postgres", [PGBIN / "psql", "-X", "-h", SOCKET_DIR, "-U", "postgres", "-d", db, "-v", "ON_ERROR_STOP=1",
                            "-tAc", sql], capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f"relay-init: database setup failed: {r.stderr.strip()}")
    return r.stdout.strip()


def network_hba() -> None:
    """The database container's sign-in rules: the image's own (Unix socket, peer), plus the app's role over the
    private Docker network with its password (SCRAM). Read by PostgreSQL through -c hba_file (supervisord.conf)."""
    path = RUN / "pg_hba.conf"
    path.write_text(Path("/etc/relay/pg_hba.conf").read_text(encoding="utf-8")
                    + "# D2D Relay's database container: the web app and the admin portal over the private network\n"
                      "host    relay     relay_app  0.0.0.0/0  scram-sha-256\n"
                      "host    relay     relay_app  ::/0       scram-sha-256\n", encoding="utf-8")
    own(path, "postgres", "postgres", 0o600)


def database(password: str | None = None) -> None:
    """password: the database container (RELAY_ROLE=database) sets the app role's password at every start."""
    folder(Path(SOCKET_DIR), "postgres", "postgres", 0o2775)
    PGDATA.mkdir(parents=True, exist_ok=True)
    own(PGDATA, "postgres", "postgres", 0o700)
    fresh = not (PGDATA / "PG_VERSION").exists()
    if fresh:
        say("database: creating a new PostgreSQL 17 cluster")
        r = run_as("postgres", [PGBIN / "initdb", "-D", PGDATA, "--username=postgres", "--encoding=UTF8",
                                "--locale=C.UTF-8", "--auth-local=peer", "--auth-host=scram-sha-256"],
                   capture_output=True, text=True)
        if r.returncode:
            raise SystemExit(f"relay-init: initdb failed: {r.stderr.strip() or r.stdout.strip()}")
    conf = PGDATA / "postgresql.conf"
    if "/etc/relay/postgres.conf" not in conf.read_text(encoding="utf-8", errors="replace"):
        with conf.open("a", encoding="utf-8", newline="\n") as f:
            f.write("\n# RELAY by PASDACS: the settings below come with the image (docker/postgres.conf)\n"
                    "include_if_exists = '/etc/relay/postgres.conf'\n")
    stale = PGDATA / "postmaster.pid"
    if stale.exists():                      # nothing runs yet in this new container: the lock is from a stop that was cut short
        stale.unlink()
        say("database: removed the lock file of the last run (the container had been stopped abruptly)")
    marker = PGDATA / "relay-ready.json"
    staged = sorted(Path("/data/import").glob("*.dump"))
    if marker.exists() and not staged and not password:
        return
    log = RUN / "database-init.log"
    log.touch()
    own(log, "postgres", "postgres", 0o640)
    start = run_as("postgres", [PGBIN / "pg_ctl", "-D", PGDATA, "-l", log, "-w", "-t", "180", "start"], capture_output=True, text=True)
    if start.returncode:
        raise SystemExit("relay-init: the database did not start:\n" + log.read_text(errors="replace")[-3000:])
    try:
        if psql("SELECT 1 FROM pg_roles WHERE rolname = 'relay_app'") != "1":
            psql("CREATE ROLE relay_app LOGIN")
        if psql("SELECT 1 FROM pg_database WHERE datname = 'relay'") != "1":
            psql("CREATE DATABASE relay OWNER relay_app ENCODING 'UTF8' TEMPLATE template0")
            say("database: created the database 'relay'")
        for dump in staged:
            tables = psql("SELECT count(*) FROM pg_tables WHERE schemaname NOT IN ('pg_catalog', 'information_schema')", "relay")
            if tables != "0":
                say(f"database: {dump.name} was NOT loaded: the database already has {tables} tables. "
                    "Load a dump into a new data volume only.")
                dump.rename(dump.with_name(dump.name + ".skipped"))
                continue
            say(f"database: loading {dump.name} ({dump.stat().st_size // 1024} KB)")
            t0 = time.time()
            with dump.open("rb") as f:
                r = run_as("postgres", [PGBIN / "pg_restore", "-h", SOCKET_DIR, "-U", "postgres", "-d", "relay", "--no-owner",
                                        "--no-acl", "--role=relay_app", "--single-transaction", "--exit-on-error"],
                           stdin=f, capture_output=True, text=True)
            if r.returncode:
                raise SystemExit(f"relay-init: loading {dump.name} failed, nothing was loaded:\n{r.stderr.strip()[-3000:]}")
            n = psql("SELECT count(*) FROM pg_tables WHERE schemaname NOT IN ('pg_catalog', 'information_schema')", "relay")
            dump.rename(dump.with_name(dump.name + time.strftime(".loaded-%Y%m%d-%H%M%S")))
            say(f"database: loaded {n} tables in {time.time() - t0:.1f} s")
        if password:                                 # the database container: the app's role signs in with it
            psql("SET password_encryption = 'scram-sha-256'; ALTER ROLE relay_app PASSWORD '" + password.replace("'", "''") + "'")
            say("database: the app's role signs in with RELAY_DB_PASSWORD over the private network")
        if not marker.exists():
            marker.write_text(json.dumps({"ready": time.time(), "created": fresh}), encoding="utf-8")
            own(marker, "postgres", "postgres", 0o600)
    finally:
        run_as("postgres", [PGBIN / "pg_ctl", "-D", PGDATA, "-m", "fast", "-w", "-t", "120", "stop"], capture_output=True)


def gateway_needed(env: dict) -> bool:
    choice = env.get("RELAY_GATEWAY", "auto").strip().lower()
    if choice in ("on", "off"):
        return choice == "on"
    try:                                     # auto: only once a cloud AI provider has routes
        return bool(json.loads(Path("/data/llm/routes.json").read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return False


def write_env(role: str, env: dict, user: str) -> None:
    path = RUN / "env" / f"{role}.json"
    tmp = path.with_name(f".{role}.tmp")
    tmp.write_text(json.dumps(env, sort_keys=True), encoding="utf-8")
    uid, gid = ids(user)
    os.chown(tmp, uid, gid)
    os.chmod(tmp, 0o400)
    tmp.replace(path)


def environments(env: dict) -> None:
    base = {"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "PYTHONUNBUFFERED": "1",
            "TZ": env.get("TZ", "UTC"), "PYTHONPATH": "/opt/genbi", "WORKSPACES": "/data/projects",
            "GENBI_VISUALS": "/opt/genbi/visuals", "GENBI_VKIT": "/opt/genbi/vkit", "GENBI_LIBRARY": str(LIBRARY),
            "PLAYWRIGHT_BROWSERS_PATH": "/opt/ms-playwright", "RELAY_VERSION": env.get("RELAY_VERSION", ""),
            "RELAY_COMMIT": env.get("RELAY_COMMIT", "")}
    skip = {"HOME", "USER", "LOGNAME", "HOSTNAME", "PWD", "SHLVL", "OLDPWD", "_", "TERM"}
    web = {k: v for k, v in env.items() if k not in skip} | base | {"HOME": "/home/relay", "USER": "relay", "LOGNAME": "relay"}
    write_env("web", web, "relay")
    agent = {k: v for k, v in env.items() if k in AGENT_PASS or k.startswith(AGENT_PREFIXES)} | base | {
        "HOME": "/home/agent", "USER": "agent", "LOGNAME": "agent", "AGENT_MODEL": env.get("AGENT_MODEL") or "sonnet",
        "CLAUDE_CONFIG_DIR": "/home/agent/.claude", "CODEX_HOME": "/home/agent/.codex",
        "GEMINI_CLI_SYSTEM_SETTINGS_PATH": "/etc/gemini-cli/settings.json", "AGY_SHARED_LOGIN": "/opt/agy-login",
        "DISABLE_AUTOUPDATER": "1", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1", "NO_UPDATE_NOTIFIER": "1",
        "BASH_DEFAULT_TIMEOUT_MS": "300000", "BASH_MAX_TIMEOUT_MS": "600000"}
    write_env("agent", agent, "agent")
    gateway = {k: v for k, v in env.items() if k.startswith("LITELLM_") or k in AGENT_PASS - {"AGENT_MODEL", "MODELS_FILE"}} | base | {
        "HOME": "/home/relay", "USER": "relay", "LOGNAME": "relay", "PATH": "/opt/relay/gateway/bin:/usr/local/bin:/usr/bin:/bin",
        # LiteLLM: the model price list it ships with (no download at every start), and no feedback box in the log
        "LITELLM_LOCAL_MODEL_COST_MAP": "True", "LITELLM_DONT_SHOW_FEEDBACK_BOX": "true"}
    write_env("gateway", gateway, "relay")


def supervisor_conf(db_on: bool, gateway_on: bool, web_on: bool = True, agent_on: bool = True, db_network: bool = False) -> None:
    """The supervisor's running config: the parts to start, and a new password for its control socket (the socket
    is also limited to root and the web app's group, so the AI engine can neither read the password nor connect)."""
    text = Path("/etc/relay/supervisord.conf").read_text(encoding="utf-8")
    on = lambda b: "true" if b else "false"  # noqa: E731
    text = (text.replace("{{CONTROL_PASSWORD}}", secrets.token_urlsafe(24))
                .replace("{{DATABASE_AUTOSTART}}", on(db_on))
                .replace("{{GATEWAY_AUTOSTART}}", on(gateway_on))
                .replace("{{WEB_AUTOSTART}}", on(web_on))
                .replace("{{AGENT_AUTOSTART}}", on(agent_on))
                # the database container listens on the private Docker network, with its own sign-in rules
                .replace("{{DATABASE_ARGS}}", " -c listen_addresses=* -c hba_file=/run/relay/pg_hba.conf" if db_network else ""))
    path = RUN / "supervisord.conf"
    tmp = RUN / ".supervisord.conf.tmp"
    tmp.write_text(text, encoding="utf-8")
    os.chown(tmp, 0, grp.getgrnam("relay").gr_gid)
    os.chmod(tmp, 0o640)
    tmp.replace(path)


def main() -> int:
    env = settings()
    role = env["RELAY_ROLE"]
    folders(role)
    if role == "database":
        network_hba()
    if env["RELAY_DB"] == "embedded":
        database(env["RELAY_DB_PASSWORD"] if role == "database" else None)
    gw = gateway_needed(env) if role in ("all", "web") else False
    environments(env)
    db_on, web_on, agent_on = env["RELAY_DB"] == "embedded", role in ("all", "web", "admin"), role in ("all", "web")
    on = lambda b: "true" if b else "false"  # noqa: E731
    (RUN / "supervisor.env").write_text(f"RELAY_ROLE={role}\nRELAY_DB_AUTOSTART={on(db_on)}\nRELAY_GATEWAY_AUTOSTART={on(gw)}\n"
                                        f"RELAY_WEB_AUTOSTART={on(web_on)}\nRELAY_AGENT_AUTOSTART={on(agent_on)}\n", encoding="utf-8")
    supervisor_conf(db_on, gw, web_on, agent_on, db_network=role == "database")
    db = {"embedded": "PostgreSQL 17 in this container", "sqlite": "SQLite file in /data/state",
          "external": "an external PostgreSQL (RELAY_DATABASE_URL)"}[env["RELAY_DB"]]
    commit = env.get("RELAY_COMMIT", "")[:8]
    what = {"all": "every part", "database": "the database only", "web": "the public site (web app and AI engine)",
            "admin": "the admin portal (web app only)"}[role]
    say(f"D2D Relay {env.get('RELAY_VERSION') or ''}{f' ({commit})' if commit else ''} · role: {role}, {what} · database: {db} · "
        f"AI gateway: {'on' if gw else 'off'} · sign-in: {env['D2D_AUTH']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
