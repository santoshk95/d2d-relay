"""Backups and retention (platform plan, phase 0).

Nightly: a consistent copy of the index database plus a zip of every project folder, into /data/backups (a folder
on the host: output/backups). Files larger than BIG_MB are left out (big uploaded CSVs: the originals stay in the
project folder; say so in the manifest) and so are caches and staging folders that the app rebuilds.
Retention: the last KEEP backups are kept; Parquet extract caches unused for CACHE_DAYS are removed (they are
rebuilt from the CSVs on next use). Old prototype versions and activity logs are kept (no automatic deletion of
anything a person made; an organisation can set rules later).

P17: one backup holds the platform's own workspace as before (index.db / index.jsonl.gz, secrets.enc, projects.zip),
the control plane (control.db / control.jsonl.gz) and every other tenant under tenants/<id>/ (the same three files).
"""
import asyncio
import json
import os
import shutil
import time
import traceback
import zipfile
from pathlib import Path

from . import db, store

BACKUPS = Path(os.environ.get("D2D_BACKUPS", "/data/backups"))
KEEP = int(os.environ.get("D2D_BACKUP_KEEP", "14"))
HOUR_UTC = int(os.environ.get("D2D_BACKUP_HOUR_UTC", "21"))          # 21:00 UTC = 02:30 in India
BIG_MB = int(os.environ.get("D2D_BACKUP_MAX_FILE_MB", "25"))
CACHE_DAYS = int(os.environ.get("D2D_CACHE_DAYS", "30"))
SKIP_DIRS = {".genbi", ".publish", "__pycache__", "node_modules"}      # rebuilt by the app; not worth keeping
_running = False


def backups() -> list[dict]:
    out = []
    for d in sorted(BACKUPS.glob("d2d-*"), reverse=True):
        m = d / "manifest.json"
        try:
            out.append(json.loads(m.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            out.append({"name": d.name, "incomplete": True})
    return out


def _tenant_files(target: Path) -> dict:
    """The current tenant's database copy, its (still encrypted) secrets and its project folders into target/."""
    from . import secrets_store
    target.mkdir(parents=True, exist_ok=True)
    db.backup(target / "index.db")                             # Postgres: index.jsonl.gz (every table, JSON lines)
    secrets_file, _ = secrets_store._paths()
    if secrets_file.exists():
        shutil.copy2(secrets_file, target / "secrets.enc")       # still encrypted; the key is not copied
    skipped, files, size = [], 0, 0
    base = store.root()
    with zipfile.ZipFile(target / "projects.zip", "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for path in sorted(base.rglob("*")):
            rel = path.relative_to(base)
            if not path.is_file() or rel.parts[0].startswith(".") or SKIP_DIRS & set(rel.parts):
                continue
            n = path.stat().st_size
            if n > BIG_MB * 1024 * 1024:
                skipped.append({"file": str(rel), "mb": round(n / 1048576, 1)})
                continue
            z.write(path, rel.as_posix())
            files, size = files + 1, size + n
    return {"projects": len(store.all_projects()), "files": files, "mb": round(size / 1048576, 1), "skipped_large_files": skipped}


def backup_now(who: str | None = "system") -> dict:
    """One backup: every tenant's database + project folders, and the control plane. Safe while the app runs."""
    global _running
    if _running:
        raise RuntimeError("A backup is already running.")
    _running = True
    started = time.time()
    try:
        name = time.strftime("d2d-%Y%m%d-%H%M%S", time.gmtime(started))
        target = BACKUPS / (name + ".partial")
        target.mkdir(parents=True, exist_ok=True)
        with db.use(db.PLATFORM):
            own = _tenant_files(target)                          # the platform's own workspace, laid out as before P17
        db.backup_control(target / "control.db")
        others = {}
        for t in db.each_tenant():
            if t != db.PLATFORM:
                others[t] = _tenant_files(target / "tenants" / t)
        skipped = own["skipped_large_files"] + [{**x, "tenant": t} for t, o in others.items() for x in o["skipped_large_files"]]
        manifest = {"name": name, "started": started, "seconds": round(time.time() - started, 1),
                    "projects": own["projects"] + sum(o["projects"] for o in others.values()),
                    "files": own["files"] + sum(o["files"] for o in others.values()),
                    "mb": round(own["mb"] + sum(o["mb"] for o in others.values()), 1),
                    "skipped_large_files": skipped, "key_included": False,
                    "tenants": {db.PLATFORM: {k: own[k] for k in ("projects", "files", "mb")},
                                **{t: {k: o[k] for k in ("projects", "files", "mb")} for t, o in others.items()}}}
        files, size = manifest["files"], manifest["mb"]
        (target / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        target.rename(BACKUPS / name)
        _prune()
        with db.use(db.PLATFORM):
            db.set_meta("last_backup", json.dumps(manifest))
            db.audit("backup", name, {"files": files, "mb": size, "skipped": len(skipped), "tenants": len(manifest["tenants"])}, who)
        return manifest
    finally:
        _running = False


def _prune() -> None:
    done = sorted(BACKUPS.glob("d2d-*"))
    for d in [x for x in done if x.name.endswith(".partial") and time.time() - x.stat().st_mtime > 86400]:
        shutil.rmtree(d, ignore_errors=True)
    done = [x for x in sorted(BACKUPS.glob("d2d-*")) if not x.name.endswith(".partial")]
    for d in done[:-KEEP] if KEEP > 0 else []:
        shutil.rmtree(d, ignore_errors=True)


def retention() -> dict:
    """Remove extract caches nobody used for CACHE_DAYS (they are rebuilt from the CSVs when needed)."""
    cutoff, removed, freed = time.time() - CACHE_DAYS * 86400, 0, 0
    for _t in db.each_tenant():                                 # P17: every tenant's folders
        mine = 0
        for f in store.ROOT.glob("*/.genbi/cache/*.parquet"):
            st = f.stat()
            if max(st.st_atime, st.st_mtime) < cutoff:
                freed += st.st_size
                f.unlink(missing_ok=True)
                removed += 1
                mine += 1
        if mine:
            db.audit("retention", "extract caches", {"cache_files_removed": mine, "older_than_days": CACHE_DAYS}, "system")
    return {"cache_files_removed": removed, "mb_freed": round(freed / 1048576, 1), "older_than_days": CACHE_DAYS}


def _seconds_to_next_run() -> float:
    now = time.time()
    t = time.gmtime(now)
    today = now - (t.tm_hour * 3600 + t.tm_min * 60 + t.tm_sec)
    nxt = today + HOUR_UTC * 3600
    return nxt - now if nxt > now else nxt + 86400 - now


async def nightly() -> None:
    """Backup + retention every night; also soon after start when the last backup is more than a day old."""
    await asyncio.sleep(60)
    with db.use(db.PLATFORM):
        last = json.loads(db.meta("last_backup") or "{}").get("started", 0)
    while True:
        try:
            if time.time() - last > 26 * 3600:
                await asyncio.to_thread(backup_now)
                await asyncio.to_thread(retention)
            last = time.time()
        except Exception:  # noqa: BLE001 - never take the app down for a backup
            traceback.print_exc()
            last = time.time()
        await asyncio.sleep(_seconds_to_next_run() + 5)
        last = 0
