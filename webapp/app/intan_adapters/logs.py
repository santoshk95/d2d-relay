"""System logs - lines from a log collector (the mock lab's HTTP endpoint) or files on disk, read for the jobs and
transfers they record: `job=<name> status=<ok|failed> src="<system>" dst="<system>" [kind=file|refresh|job]
[rows=N] [ms=N] [owner="..."] [file=...] [error="..."]` as key=value tokens on a timestamped line. What only the logs
know about (no inventory, no owner) is exactly what Integration analytics flags."""
from __future__ import annotations

import glob
import re
import time

from . import base

KIND, LABEL, GROUP = "logs", "System logs", "Logs"
AUTH = "API key for the log collector, or none for files"
DOCS = "key=value job lines from a collector endpoint (GET /logs?since=) or log files (glob)"
CONFIG = [{"name": "url", "label": "Collector URL or file glob", "hint": "http://collector/logs or /var/log/jobs/*.log", "required": True}]
SECRETS = [{"name": "api_key", "label": "API key (X-Api-Key)"}]
TOKEN = re.compile(r'(\w+)=("([^"]*)"|\S+)')
STAMP = re.compile(r"^(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)")


def _lines(url: str, secrets: dict, since: float) -> list[str]:
    if url.startswith("http"):
        c = base.Client(url, {"X-Api-Key": secrets.get("api_key") or ""} if secrets.get("api_key") else None)
        return c.get("/logs" if not url.rstrip("/").endswith("/logs") else "", {"since": int(since)}).get("lines") or []
    out = []
    for f in sorted(glob.glob(url)):
        with open(f, encoding="utf-8", errors="replace") as fh:
            out += [ln.rstrip("\n") for ln in fh]
    return out


def parse(line: str) -> dict | None:
    m = STAMP.match(line)
    if not m:
        return None
    kv = {k: (q or v) for k, v, q in TOKEN.findall(line[m.end():])}
    if "job" not in kv or "src" not in kv or "dst" not in kv:
        return None
    return {"ts": base.ts(m.group(1).replace(" ", "T")), **kv}


def discover(cfg: dict, secrets: dict, now: float | None = None) -> dict:
    now = now or time.time()
    out = base.empty()
    systems, integ = {}, {}
    for ln in _lines(cfg["url"], secrets, now - 42 * 86400):
        p = parse(ln)
        if not p or not p.get("ts"):
            continue
        key = p["job"]
        kind = (p.get("kind") or "job").lower()
        for s in (p["src"], p["dst"]):
            systems[s] = {"name": s, "kind": "system"}
        if key not in integ:
            what = {"file": "export", "refresh": "refresh", "job": p["job"]}.get(kind, p["job"])
            integ[key] = {"ext_id": key, "name": p.get("name") or f"{p['src']} {p['dst']} {what}", "kind": {"file": "File", "refresh": "Refresh"}.get(kind, "Job"), "via": p.get("via") or p["dst"] if kind == "refresh" else p.get("via"),
                          "from_system": p["src"], "to_system": p["dst"], "schedule": p.get("schedule") or "Unknown", "owner": p.get("owner"), "feeds": [p["dataset"]] if p.get("dataset") else [],
                          "properties": {"found_in": f"{p['src']} logs" if kind != "refresh" else f"{p['dst']} gateway logs", "host": p.get("host"), "file": p.get("file"), "runs": 0}}
            out["integrations"].append(integ[key])
        integ[key]["properties"]["runs"] += 1
        ms = float(p.get("ms") or 0)
        out["runs"].append({"integration": key, "ext_id": f"{key}-{int(p['ts'])}", "started": p["ts"], "ended": p["ts"] + ms / 1000, "status": "success" if (p.get("status") or "").lower() in ("ok", "success", "succeeded", "0") else "failed",
                            "duration_s": ms / 1000 if ms else None, "volume": float(p["rows"]) if p.get("rows") else (float(p["bytes"]) if p.get("bytes") else None), "error": p.get("error")})
    for i in out["integrations"]:
        mine = sorted(r["started"] for r in out["runs"] if r["integration"] == i["ext_id"])
        if len(mine) >= 3 and i["schedule"] == "Unknown":
            span = max(1.0, (mine[-1] - mine[0]) / 86400)
            rpd = len(mine) / span
            if rpd >= 1.5:
                i["schedule"] = f"{round(rpd)}×/day"
            elif rpd >= 0.7:
                tod = sorted(t % 86400 for t in mine)[len(mine) // 2]
                i["schedule"] = f"Daily {int(tod // 3600):02d}:{int(tod % 3600 // 60):02d} (seen in logs)"
    out["systems"] = list(systems.values())
    return out
