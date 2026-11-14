"""Per-person workspace instances (platform plan, phase 2), driven through the orchestrator service.

D2D_INSTANCES=off (default): every run goes to the shared agent container, as before.
D2D_INSTANCES=on: a person's runs go to their own instance - created on their first sign-in, started on sign-in
when stopped (the "Starting your workspace" wait), stopped after IDLE_MIN minutes without activity and never
while one of its lanes is busy, destroyed only on offboarding. The orchestrator enforces the capacity cap.
"""
import asyncio
import os
import time
import traceback
from pathlib import Path

import httpx

from . import db

ENABLED = os.environ.get("D2D_INSTANCES", "off") == "on"
ORCH = os.environ.get("D2D_ORCHESTRATOR_URL", "http://orchestrator:8095")
TOKEN_FILE = Path(os.environ.get("D2D_ORCH_TOKEN_FILE", "/data/orch/token"))
SHARED_AGENT = os.environ.get("AGENT_URL", "http://agent:8090")
IDLE_MIN = float(os.environ.get("D2D_IDLE_MINUTES", "30"))
START_WAIT_S = int(os.environ.get("D2D_START_WAIT_S", "600"))
# The all-in-one image (Dockerfile at the repo root): the gateway is a part of this container, run by its supervisor
SUPERVISOR_CONF = os.environ.get("RELAY_SUPERVISOR_CONF", "")
last_active: dict[str, float] = {}


class InstanceError(Exception):
    pass


def touch(uid: str | None) -> None:
    if uid:
        last_active[uid] = time.time()


def _headers() -> dict:
    try:
        return {"X-D2D-Orch": TOKEN_FILE.read_text().strip()}
    except OSError as e:
        raise InstanceError("The orchestrator has not started yet (no token).") from e


async def _call(method: str, path: str, timeout: float = 60) -> dict:
    async with httpx.AsyncClient(timeout=timeout) as c:
        r = await c.request(method, ORCH + path, headers=_headers())
    if r.status_code >= 400:
        raise InstanceError(f"Orchestrator: {r.text[:300]}")
    return r.json()


async def status(uid: str) -> dict:
    if not ENABLED:
        return {"state": "shared", "url": SHARED_AGENT}
    return await _call("GET", f"/instances/{uid}")


async def start(uid: str) -> dict:
    if not ENABLED:
        return {"state": "shared", "url": SHARED_AGENT}
    touch(uid)
    s = await _call("POST", f"/instances/{uid}/start")
    if s.get("state") in ("starting", "running") and not db.meta(f"instance_created:{uid}"):
        db.set_meta(f"instance_created:{uid}", str(time.time()))
        db.audit("instance.create", uid, {"name": s.get("name")}, uid)
    return s


async def _healthy(url: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=3) as c:
            return (await c.get(f"{url}/health")).status_code == 200
    except httpx.HTTPError:
        return False


async def agent_url(uid: str | None) -> str:
    """Where a run of this person goes; with instances on, waits for their instance (start queue included)."""
    if not ENABLED or not uid:
        return SHARED_AGENT
    touch(uid)
    end = time.time() + START_WAIT_S
    while time.time() < end:
        s = await start(uid)
        if s.get("state") == "running" and await _healthy(s["url"]):
            return s["url"]
        await asyncio.sleep(2)
    raise InstanceError("The workspace did not start in time (the host may be at capacity). Press Retry.")


async def stop(uid: str, reason: str, who: str | None) -> dict:
    s = await _call("POST", f"/instances/{uid}/stop")
    db.audit("instance.stop", uid, {"reason": reason}, who)
    return s


async def destroy(uid: str, who: str | None) -> dict:
    if not ENABLED:
        return {"state": "shared"}
    s = await _call("DELETE", f"/instances/{uid}")
    db.audit("instance.destroy", uid, None, who)
    return s


async def listing() -> dict:
    if not ENABLED:
        return {"enabled": False, "instances": []}
    data = await _call("GET", "/instances")
    for s in data["instances"]:
        s["last_active"] = last_active.get(s.get("user"))
    return {"enabled": True, **data, "idle_minutes": IDLE_MIN}


async def restart_gateway() -> None:
    """Load a new LiteLLM config (best effort: without the orchestrator the gateway loads it at its next start)."""
    if SUPERVISOR_CONF:                                  # one container: restart (or first start) the gateway part
        try:
            p = await asyncio.create_subprocess_exec("supervisorctl", "-c", SUPERVISOR_CONF, "restart", "gateway",
                                                     stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
            await asyncio.wait_for(p.wait(), 90)
        except (OSError, TimeoutError):
            pass
        return
    try:
        await _call("POST", "/services/litellm/restart")
    except (InstanceError, httpx.HTTPError):
        pass


async def reaper(busy_owner) -> None:
    """Stop instances idle for IDLE_MIN minutes - never one whose lanes are busy or whose owner has a job running."""
    while True:
        await asyncio.sleep(60)
        if not ENABLED:
            continue
        try:
            for s in (await _call("GET", "/instances"))["instances"]:
                uid = s.get("user")
                if s.get("state") != "running" or not uid:
                    continue
                last_active.setdefault(uid, time.time())      # first seen (e.g. after an app restart): full idle period
                if time.time() - last_active.get(uid, 0) < IDLE_MIN * 60 or uid in busy_owner():    # item 46: a set
                    continue
                try:
                    async with httpx.AsyncClient(timeout=3) as c:
                        lanes = (await c.get(f"{s['url']}/health")).json().get("lanes") or {}
                except httpx.HTTPError:
                    lanes = {}
                if any(lanes.values()):
                    continue
                await stop(uid, f"idle for {IDLE_MIN:g} minutes", "system")
        except Exception:  # noqa: BLE001 - never take the app down
            traceback.print_exc()
