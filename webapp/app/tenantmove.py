"""Move one tenant between installs (P17): export, import, and the deployment pack for a dedicated install.

    python -m app.tenantmove export <tenant> [--out DIR]          a .tar.gz + a new secrets key (printed once)
    python -m app.tenantmove import <file.tar.gz> [--as-platform] [--tenant ID] [--key KEY]

The export holds the tenant's whole schema as JSON lines (every table, parents first), its control-plane rows (the
tenant, its module switches, its people's directory entries, hand-overs), its project folders, visual library and
rendered reports, and its secrets re-encrypted with a NEW key (never the install's own). `--as-platform` imports it as
the install's own workspace: a dedicated install inside the client's network (D2D_TENANCY=single,
D2D_PLATFORM_TENANT=<tenant>); otherwise it becomes a tenant of the install it is imported into.
"""
from __future__ import annotations

import argparse
import base64
import gzip
import io
import json
import os
import shutil
import sys
import tarfile
import tempfile
import time
import zipfile
from pathlib import Path

from cryptography.fernet import Fernet

from . import db, schedules, secrets_store, store

FORMAT = 1


def _rows(table: str) -> list[dict]:
    return db.q(f"SELECT * FROM {table}")


def _add_dir(tar: tarfile.TarFile, src: Path, arc: str, skip_top: set[str] | None = None) -> int:
    n = 0
    if not src.exists():
        return 0
    for path in sorted(src.rglob("*")):
        rel = path.relative_to(src)
        if skip_top and rel.parts and rel.parts[0] in skip_top:
            continue
        if path.is_file():
            tar.add(path, arcname=f"{arc}/{rel.as_posix()}", recursive=False)
            n += 1
    return n


def export(tid: str, out_dir: Path) -> dict:
    """The tenant as one .tar.gz in out_dir; returns its path, the new secrets key and what is in it."""
    t = db.one("SELECT * FROM relay.tn_tenants WHERE id = ?", (tid,))
    if not t:
        raise SystemExit(f"No tenant {tid!r}.")
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    path = out_dir / f"relay-export-{tid}-{stamp}.tar.gz"
    key = Fernet.generate_key()
    counts: dict[str, int] = {}
    with db.use(tid), tarfile.open(path, "w:gz") as tar:
        buf = io.BytesIO()
        with gzip.GzipFile(fileobj=buf, mode="wb") as gz:
            for table in db.tables():
                rows = _rows(table)
                counts[table] = len(rows)
                for r in rows:
                    gz.write((json.dumps({"table": table, "row": r}, default=str) + "\n").encode())
        _blob(tar, "db.jsonl.gz", buf.getvalue())
        control = {"tenant": dict(t),
                   "modules": db.q("SELECT * FROM relay.tn_modules WHERE tenant_id = ?", (tid,)),
                   "accounts": db.q("SELECT * FROM relay.tn_accounts WHERE home_tenant = ?", (tid,)),
                   "handovers": db.q("SELECT * FROM relay.tn_handovers WHERE tenant_id = ?", (tid,))}
        _blob(tar, "control.json", json.dumps(control, default=str, indent=1).encode())
        data = secrets_store._load()
        _blob(tar, "secrets.enc", Fernet(key).encrypt(json.dumps(data).encode()))
        files = {"projects": _add_dir(tar, store.root(), "projects", {store.TENANTS_DIR} if tid == db.PLATFORM else None),
                 "library": _add_dir(tar, store._library(Path(os.environ.get("GENBI_LIBRARY", "/opt/genbi/library"))), "library",
                                     {store.TENANTS_DIR} if tid == db.PLATFORM else None),
                 "reports": _add_dir(tar, Path(schedules.OUT), "reports")}
        manifest = {"format": FORMAT, "tenant": tid, "name": t["name"], "kind": t["kind"], "edition": t["edition"],
                    "exported": time.time(), "schema_version": db.SCHEMA_VERSION, "database": db.BACKEND, "rows": counts,
                    "files": files, "secrets": len(data)}
        _blob(tar, "manifest.json", json.dumps(manifest, indent=1).encode())
    return {"path": str(path), "key": key.decode(), "manifest": manifest}


def _blob(tar: tarfile.TarFile, name: str, data: bytes) -> None:
    info = tarfile.TarInfo(name)
    info.size, info.mtime = len(data), int(time.time())
    tar.addfile(info, io.BytesIO(data))


def _safe_members(tar: tarfile.TarFile, root: Path):
    for m in tar.getmembers():
        target = (root / m.name).resolve()
        if root.resolve() not in target.parents and target != root.resolve():
            raise SystemExit(f"Refusing an unsafe path in the export: {m.name}")
        if m.issym() or m.islnk():
            raise SystemExit(f"Refusing a link in the export: {m.name}")
        yield m


def import_(path: Path, *, as_platform: bool = False, tid: str | None = None, key: str | None = None) -> dict:
    """Load an export into this install (its own workspace with as_platform, else a new tenant)."""
    db.init()
    work = Path(tempfile.mkdtemp(prefix="relay-import-"))
    try:
        with tarfile.open(path, "r:gz") as tar:
            tar.extractall(work, members=list(_safe_members(tar, work)))
        manifest = json.loads((work / "manifest.json").read_text(encoding="utf-8"))
        control = json.loads((work / "control.json").read_text(encoding="utf-8"))
        src = control["tenant"]
        target = db.PLATFORM if as_platform else (tid or manifest["tenant"])
        now = time.time()
        if as_platform:
            db.run("UPDATE relay.tn_tenants SET name = ?, edition = ?, updated = ? WHERE id = ?",
                   (src["name"], src["edition"] if src["edition"] in ("enterprise", "partner", "both") else "both", now, db.PLATFORM))
        else:
            if db.one("SELECT 1 AS x FROM relay.tn_tenants WHERE id = ?", (target,)):
                raise SystemExit(f"A tenant {target!r} already exists here; import with --tenant NEW_ID.")
            parent = src.get("parent_id")                       # the same partner when it exists here, else direct
            if not (parent and db.one("SELECT 1 AS x FROM relay.tn_tenants WHERE id = ? AND kind IN ('platform', 'partner')", (parent,))):
                parent = db.PLATFORM
            db.run("INSERT INTO relay.tn_tenants (id, kind, parent_id, name, edition, status, deployment, host, partner_access, region, notes, "
                   "created, created_by, updated) VALUES (?, ?, ?, ?, ?, 'active', 'shared', NULL, ?, ?, ?, ?, 'import', ?)",
                   (target, "client" if src["kind"] == "platform" else src["kind"], parent, src["name"], src["edition"],
                    src.get("partner_access") or "open", src.get("region"), src.get("notes"), now, now))
            db.init_tenant(target)
        loaded: dict[str, int] = {}
        with db.use(target):
            have = set(db.tables())
            with gzip.open(work / "db.jsonl.gz", "rt", encoding="utf-8") as f:
                with db.transaction():
                    for line in f:
                        item = json.loads(line)
                        table, r = item["table"], item["row"]
                        if table not in have:
                            continue
                        cols = list(r)
                        db.run(f"INSERT OR IGNORE INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})", tuple(r[c] for c in cols))
                        loaded[table] = loaded.get(table, 0) + 1
            if db.BACKEND == "postgres":                     # explicit ids: move the serial sequences past them
                for table in ("audit", "usage"):
                    db.q(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), COALESCE((SELECT max(id) FROM {table}), 1))")
            secret_key = key or os.environ.get("RELAY_EXPORT_KEY") or os.environ.get("D2D_SECRET_KEY")
            secrets_n = 0
            if (work / "secrets.enc").exists() and secret_key:
                data = json.loads(secrets_store._key(secret_key.strip()).decrypt((work / "secrets.enc").read_bytes()))
                secrets_store._save(data)                    # in this install's own key
                secrets_n = len(data)
            for sub, dest in (("projects", store.root()), ("library", store._library(Path(os.environ.get("GENBI_LIBRARY", "/opt/genbi/library")))),
                              ("reports", Path(schedules.OUT))):
                if (work / sub).exists():
                    dest.mkdir(parents=True, exist_ok=True)
                    shutil.copytree(work / sub, dest, dirs_exist_ok=True)
            for a in control.get("accounts") or []:
                db.run("INSERT OR IGNORE INTO relay.tn_accounts (user_id, email, home_tenant, created) VALUES (?, ?, ?, ?)",
                       (a["user_id"], a["email"], target, a["created"]))
            for m in control.get("modules") or []:
                db.run("INSERT OR REPLACE INTO relay.tn_modules (tenant_id, module_id, enabled, updated, updated_by) VALUES (?, ?, ?, ?, 'import')",
                       (target, m["module_id"], m["enabled"], now))
            db.audit("tenant.imported", target, {"from": manifest["tenant"], "rows": sum(loaded.values()), "secrets": secrets_n}, "system")
        return {"tenant": target, "rows": loaded, "secrets": secrets_n, "files": manifest["files"]}
    finally:
        shutil.rmtree(work, ignore_errors=True)


ENV_TEMPLATE = """# RELAY by PASDACS — a dedicated install for {name} ({tid}), packed {date}
# Copy next to docker-compose.yml as .env (or into your Kubernetes secret), then import the export:
#   docker compose run --rm webapp python -m app.tenantmove import /data/backups/tenant-export.tar.gz --as-platform
D2D_TENANCY=single
D2D_PLATFORM_TENANT={tid}
D2D_PLATFORM_NAME={name}
D2D_AUTH=sso
D2D_ADMIN_EMAIL={admin}
# The secrets key was shown once when this pack was made; paste it here (it is not in the pack):
D2D_SECRET_KEY=
"""

KUSTOMIZATION = """# A dedicated install of RELAY by PASDACS for {name}. Put this folder at deploy/kubernetes/clients/{tid}/ in the
# Relay repository, write secrets.env and orch-token.env next to it (from secrets.env.example / orch-token.env.example:
# secret-key = the key shown once when the pack was made), then: kubectl apply -k deploy/kubernetes/clients/{tid}
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: relay-{tid}
resources:
  - ../../base
components:
  - ../../runners          # optional: Codex, Gemini and Antigravity runners (remove the line to run Claude only)
secretGenerator:
  - name: d2d-secrets
    envs: [secrets.env]
  - name: d2d-orch-token
    envs: [orch-token.env]
generatorOptions:
  disableNameSuffixHash: true
patches:
  - target:
      kind: Deployment
      name: webapp
    patch: |-
      - op: add
        path: /spec/template/spec/containers/0/env/-
        value: {{name: D2D_TENANCY, value: single}}
      - op: add
        path: /spec/template/spec/containers/0/env/-
        value: {{name: D2D_PLATFORM_TENANT, value: {tid}}}
      - op: add
        path: /spec/template/spec/containers/0/env/-
        value: {{name: D2D_PLATFORM_NAME, value: "{name}"}}
"""

SECRETS_EXAMPLE = """# Copy to secrets.env next to kustomization.yaml and fill in. Never commit the filled-in file.
postgres-password=change-me
database-url=postgresql://d2d:change-me@postgres:5432/d2d
# the key shown once when this pack was made: it opens the workspace's stored credentials
secret-key=
# the first admin's password for sign-in before the workspace's identity provider is set up
admin-password=
metrics-token=
claude-oauth-token=
"""
ORCH_EXAMPLE = """# Copy to orch-token.env: the web app <-> orchestrator token, any long random string
token=change-me-to-a-long-random-string
"""

README = """# {name} — dedicated install pack

Made by RELAY by PASDACS on {date} for the tenant `{tid}` ({kind}, {edition} edition).

| File | What it is |
|---|---|
| `tenant-export.tar.gz` | everything of this workspace: its database ({rows} rows), folders ({files} files), visual library, reports, and its secrets re-encrypted with a key shown once |
| `.env.dedicated` | the settings of a one-workspace install (`D2D_TENANCY=single`) |
| `kubernetes/kustomization.yaml` | the overlay for a Kubernetes install inside your network (with the optional runners component) |

1. Install Relay inside the network (Docker Compose or `kubectl apply -k`), with `.env.dedicated` as its settings and
   the secrets key pasted into `D2D_SECRET_KEY`.
2. Import: `python -m app.tenantmove import tenant-export.tar.gz --as-platform` (in the web app container).
3. Sign in with the workspace's identity provider (Admin › Sign-in) or the first admin's local password.

Nothing in this pack can be opened without the key; keep the key apart from the pack.
"""


def pack(tid: str) -> dict:
    """The deployment pack for a client that runs Relay inside its own network: export + .env + Kubernetes overlay."""
    from . import tenancy
    t = db.one("SELECT * FROM relay.tn_tenants WHERE id = ?", (tid,))
    with db.use(tid):
        first = db.one("SELECT email FROM users WHERE org_role = 'admin' AND active = 1 AND home_tenant IS NULL ORDER BY created LIMIT 1")
    with db.use(db.PLATFORM):
        packs = Path(tenancy.PACKS)
    packs.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="relay-pack-"))
    try:
        ex = export(tid, tmp)
        stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
        name = f"relay-pack-{tid}-{stamp}.zip"
        date = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
        fmt = {"name": t["name"], "tid": tid, "date": date, "admin": (first or {}).get("email") or "", "kind": t["kind"],
               "edition": t["edition"], "rows": sum(ex["manifest"]["rows"].values()), "files": sum(ex["manifest"]["files"].values())}
        with zipfile.ZipFile(packs / name, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(ex["path"], "tenant-export.tar.gz")
            z.writestr(".env.dedicated", ENV_TEMPLATE.format(**fmt))
            z.writestr("kubernetes/kustomization.yaml", KUSTOMIZATION.format(**fmt))
            z.writestr("kubernetes/secrets.env.example", SECRETS_EXAMPLE)
            z.writestr("kubernetes/orch-token.env.example", ORCH_EXAMPLE)
            z.writestr("README.md", README.format(**fmt))
            files = z.namelist()
        size = (packs / name).stat().st_size
        return {"name": name, "path": str(packs / name), "key": ex["key"], "bytes": size, "files": files,
                "download": f"/api/tenancy/packs/{name}", "manifest": ex["manifest"]}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m app.tenantmove", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export")
    e.add_argument("tenant")
    e.add_argument("--out", type=Path, default=Path(os.environ.get("D2D_BACKUPS", "/data/backups")))
    i = sub.add_parser("import")
    i.add_argument("file", type=Path)
    i.add_argument("--as-platform", action="store_true")
    i.add_argument("--tenant")
    i.add_argument("--key")
    a = ap.parse_args(argv)
    if a.cmd == "export":
        db.init()
        info = export(a.tenant, a.out)
        print(json.dumps({"path": info["path"], "rows": sum(info["manifest"]["rows"].values()), "files": info["manifest"]["files"]}, indent=1))
        print(f"\nSecrets key (shown once, keep it apart from the file): {info['key']}")
        return 0
    info = import_(a.file, as_platform=a.as_platform, tid=a.tenant, key=a.key)
    print(json.dumps({"tenant": info["tenant"], "rows": sum(info["rows"].values()), "secrets": info["secrets"], "files": info["files"]}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
