"""D2D Relay: the Power BI file (.pbix) every published dashboard is downloaded as.

Only Power BI Desktop can save a report as a .pbix, and it runs on Windows, not in Docker. So, like the DAX checker,
the Power BI file maker (pbix/pbix.ps1, started on the D2D Relay PC with pbix\\start-pbix.cmd) watches a queue folder
next to the projects: this module drops a request there (the checked report, zipped, and the dashboard's data folder)
and waits for its answer. The maker opens the report in Power BI Desktop, refreshes it from the CSVs, checks with Power
BI's own engine that every table loaded, and saves it as <project>/pbix/<Report>.pbix.

Every .pbix is made with its DataFolder parameter at C:\\D2D Relay Data\\<Report>\\data\\ (the maker's -DataRoot): the
data is inside the file, and unzipping the download into C:\\D2D Relay Data lets Power BI Desktop refresh it as it is.
"""
from __future__ import annotations

import json
import os
import secrets
import time
from pathlib import Path

ROOT = Path(os.environ.get("WORKSPACES", "/data/projects"))
QUEUE = Path(os.environ.get("D2D_PBIX_QUEUE") or ROOT / ".pbix")
TIMEOUT_S = int(os.environ.get("D2D_PBIX_TIMEOUT_S") or 75 * 60)
START_WAIT_S = 120              # a request nobody picks up: give up after this long without a heartbeat
STALE_S = 30                    # a heartbeat older than this: the maker is not running


class PbixError(Exception):
    """Shown to the person as it is."""


def heartbeat() -> dict | None:
    try:
        return json.loads((QUEUE / "heartbeat.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None


def available() -> dict | None:
    """The maker's heartbeat if it is running and able to work (written in the last 30 seconds, no error)."""
    beat = heartbeat()
    if not beat or time.time() - float(beat.get("time") or 0) >= STALE_S or beat.get("state") == "error":
        return None
    return beat


def not_running_text() -> str:
    beat = heartbeat()
    if beat and beat.get("state") == "error" and time.time() - float(beat.get("time") or 0) < STALE_S:
        return f"The Power BI file maker on the D2D Relay PC has stopped: {beat.get('error')}"
    return "The Power BI file maker is not running on the D2D Relay PC."


def make(project: Path, checked_zip: Path, report: str) -> dict:
    """Ask Power BI Desktop for the .pbix of this dashboard. Returns {"pbix": Path, "data_folder", "seconds", "mb"};
    PbixError when the maker is not running, does not answer, or could not make it."""
    QUEUE.mkdir(parents=True, exist_ok=True)
    rid = time.strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(3)
    out = project / "pbix" / f"{report}.pbix"
    out.unlink(missing_ok=True)
    rel = lambda p: p.relative_to(ROOT).as_posix()      # noqa: E731 - the maker resolves these inside its projects folder
    req = QUEUE / "requests"
    req.mkdir(parents=True, exist_ok=True)
    tmp = req / f"{rid}.json.tmp"
    tmp.write_text(json.dumps({"id": rid, "report": report, "zip": rel(checked_zip), "data": rel(project / "data"),
                               "out": rel(out), "created": time.time()}), encoding="utf-8")
    tmp.rename(req / f"{rid}.json")
    answer, started, last_alive = QUEUE / "results" / f"{rid}.json", time.time(), time.time()
    while not answer.exists():
        now = time.time()
        if available():
            last_alive = now
        elif now - last_alive > START_WAIT_S:
            (req / f"{rid}.json").unlink(missing_ok=True)
            raise PbixError(not_running_text())
        if now - started > TIMEOUT_S:
            (req / f"{rid}.json").unlink(missing_ok=True)
            raise PbixError(f"Power BI Desktop did not make the .pbix within {TIMEOUT_S // 60} minutes.")
        time.sleep(1)
    result = json.loads(answer.read_text(encoding="utf-8-sig"))
    answer.unlink(missing_ok=True)
    if not result.get("ok"):
        raise PbixError(f"Power BI Desktop could not make the .pbix: {result.get('error') or 'no reason given'}")
    if not out.exists():
        raise PbixError("The Power BI file maker said it was done, but the .pbix is not there.")
    return {"pbix": out, "data_folder": result.get("data_folder"), "seconds": result.get("seconds"), "mb": result.get("mb")}
