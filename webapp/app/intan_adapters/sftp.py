"""SFTP file drops - a listing of the watched folders (an SFTP server through paramiko when installed, a local
folder, or the mock lab's HTTP listing). Each drop you describe (folder, what reads it, from / to systems) becomes
an integration; each file that arrives is a run whose volume is its size, so a file 18 % smaller than usual
stands out."""
from __future__ import annotations

import json
import os
import time

from . import base

KIND, LABEL, GROUP = "sftp", "SFTP file drops", "Files & mail"
AUTH = "SFTP user (read-only) or none for a local folder"
DOCS = "SFTP listing (paramiko) / local folder / mock-lab HTTP listing; drops described in the source settings"
CONFIG = [{"name": "url", "label": "Server", "hint": "sftp://host, a local folder, or the mock lab's http://... listing", "required": True},
          {"name": "drops", "label": "Watched drops (JSON)", "hint": '[{"name": "Bank statements SFTP -> ADF", "path": "/inbound/bank", "from_system": "Bank SFTP", "to_system": "Azure Data Factory", "schedule": "Daily 07:00", "owner": "Treasury"}]', "required": True}]
SECRETS = [{"name": "username", "label": "User"}, {"name": "password", "label": "Password or key passphrase"}]


def _listing(url: str, secrets: dict) -> list[dict]:
    if url.startswith("http"):
        c = base.Client(url, base.Client.basic(secrets.get("username") or "", secrets.get("password") or "") if secrets.get("username") else None)
        return c.get("/files").get("files") or []
    if url.startswith("sftp://"):
        try:
            import paramiko
        except ImportError as e:
            raise base.SourceError("paramiko is not installed in this image; an SFTP server needs it (a local folder or the mock lab's listing works without it).") from e
        host = url[len("sftp://"):].split("/")[0]
        t = paramiko.Transport((host.split(":")[0], int(host.split(":")[1]) if ":" in host else 22))
        t.connect(username=secrets.get("username"), password=secrets.get("password"))
        s = paramiko.SFTPClient.from_transport(t)
        out = []
        try:
            def walk(p):
                for a in s.listdir_attr(p):
                    full = p.rstrip("/") + "/" + a.filename
                    if a.st_mode and (a.st_mode & 0o40000):
                        walk(full)
                    else:
                        out.append({"path": full, "size": a.st_size, "mtime": a.st_mtime})
            walk("/")
        finally:
            s.close(); t.close()
        return out
    out = []
    for root, _, files in os.walk(url):
        for f in files:
            p = os.path.join(root, f)
            st = os.stat(p)
            out.append({"path": "/" + os.path.relpath(p, url).replace("\\", "/"), "size": st.st_size, "mtime": st.st_mtime})
    return out


def discover(cfg: dict, secrets: dict, now: float | None = None) -> dict:
    now = now or time.time()
    drops = cfg.get("drops") or []
    if isinstance(drops, str):
        drops = json.loads(drops or "[]")
    files = _listing(cfg["url"], secrets)
    out = base.empty()
    systems = {}
    for d in drops:
        for s in (d.get("from_system"), d.get("to_system")):
            if s:
                systems[s] = {"name": s, "kind": "system"}
        mine = sorted([f for f in files if f["path"].startswith(d["path"].rstrip("/") + "/")], key=lambda f: f["mtime"])
        out["integrations"].append({"ext_id": d["path"], "name": d.get("name") or f"{d.get('from_system')} {d.get('to_system')}", "kind": "File", "via": d.get("to_system"), "from_system": d.get("from_system"), "to_system": d.get("to_system"),
                                    "schedule": d.get("schedule") or "Unknown", "owner": d.get("owner"), "properties": {"path": d["path"], "files": len(mine), "latest": mine[-1]["path"] if mine else None}})
        for f in mine:
            out["runs"].append({"integration": d["path"], "ext_id": f["path"], "started": f["mtime"], "ended": f["mtime"], "status": "success", "duration_s": None, "volume": f["size"], "error": None})
    out["systems"] = list(systems.values())
    return out
