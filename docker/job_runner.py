#!/usr/local/bin/python3
"""Each AI build in a container of its own (security audit S4; the user, 2026-11-12: "AI run in its own container").

The job runner is the only part of D2D Relay that holds Docker's control socket. It runs in its own container with no
network at all, and listens only on a Unix socket in a volume it shares with the web container, owned by the AI
engine's user (nothing else reaches it: the job containers do not get that volume). The AI engine asks it to run one
`claude` job; the runner starts a short-lived container from the web container's own image that holds only:
  - that dashboard's folder (read-write), at the same path as in the web container;
  - its organisation's visual library (read-only), when the run names one;
  - the AI engine's Claude sign-in volume (the sign-in and the run transcripts Claude Code keeps);
  - the web container's network (container:<web>): so the AI engine's network limits (S6: Anthropic only, through the
    proxy) and its API guard (S4: the AI engine's user is refused) apply to it as to the AI engine itself.
No other organisation's folders, no /data, no secrets, no Docker. All capabilities dropped, no new privileges.
It streams the job's stdout back line by line, and stops and removes the container when the job ends or the AI
engine stops listening (Stop, a timeout, a restart).

API (HTTP over the Unix socket): POST /jobs {cwd, argv, env, prompt, library} -> NDJSON lines {"o": stdout line},
then {"x": exit code, "e": the end of stderr}; GET /health.
"""
import asyncio
import io
import json
import os
import pwd
import re
import secrets
import socket
import struct
import sys
import tarfile
import time

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

SOCK = os.environ.get("D2D_JOB_RUNNER_SOCK", "/run/relay-runner/runner.sock")
DOCKER = os.environ.get("D2D_DOCKER_SOCK", "/var/run/docker.sock")
WEB = os.environ.get("D2D_JOB_WEB_CONTAINER", "d2d-relay-web")
PROJECTS = "/data/projects"
LIBRARY = "/opt/genbi/library"
# a dashboard folder: /data/projects/<id> (the platform) or /data/projects/.tenants/<organisation>/<id>
CWD = re.compile(r"^/data/projects/(\.tenants/[A-Za-z0-9_][A-Za-z0-9_-]*/)?[A-Za-z0-9_][A-Za-z0-9_.-]*$")
ENV_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
LIMITS = {"PidsLimit": 2048, "ShmSize": 512 * 1024 * 1024, "Memory": int(os.environ.get("D2D_JOB_MEMORY_MB") or 8192) * 1024 * 1024}

app = FastAPI(title="D2D Relay job runner")
WEB_INFO: dict = {}


def docker() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.AsyncHTTPTransport(uds=DOCKER), base_url="http://docker", timeout=None)


async def web_info() -> dict:
    """The web container as Docker sees it: its id and image, and where its folders come from on the host."""
    async with docker() as d:
        r = await d.get(f"/containers/{WEB}/json")
        r.raise_for_status()
        c = r.json()
    mounts = {m["Destination"]: m for m in c.get("Mounts") or []}
    return {"id": c["Id"], "image": c["Image"], "mounts": mounts, "running": c["State"]["Running"]}


def source(m: dict, sub: str = "") -> dict:
    """A mount for the job container from one of the web container's: a host folder, or a named volume."""
    if m["Type"] == "volume":
        return {"Type": "volume", "Source": m["Name"], **({"VolumeOptions": {"Subpath": sub.strip("/")}} if sub else {})}
    src = m["Source"]
    if sub:                                         # Docker Desktop reports host folders as Windows paths: keep their separator
        sep = "\\" if "\\" in src else "/"
        src = src.rstrip("/\\") + sep + sub.strip("/").replace("/", sep)
    return {"Type": "bind", "Source": src}


def tar_of(name: str, data: bytes, uid: int, gid: int) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as t:
        info = tarfile.TarInfo(name)
        info.size, info.mode, info.uid, info.gid, info.mtime = len(data), 0o600, uid, gid, int(time.time())
        t.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def frames(buf: bytearray):
    """Docker's multiplexed log stream: [stream, 0, 0, 0, size (4 bytes, big-endian)] + payload, repeated."""
    while len(buf) >= 8:
        kind, size = buf[0], struct.unpack(">I", bytes(buf[4:8]))[0]
        if len(buf) < 8 + size:
            return
        payload = bytes(buf[8:8 + size])
        del buf[:8 + size]
        yield kind, payload


@app.get("/health")
async def health():
    try:
        w = await web_info()
        return {"ok": True, "web": w["running"], "image": w["image"][:19]}
    except Exception as e:  # noqa: BLE001 - reported, the AI engine falls back to nothing (the run fails clearly)
        return JSONResponse({"ok": False, "error": str(e)[:200]}, status_code=503)


@app.post("/jobs")
async def run_job(request: Request):
    body = await request.json()
    cwd, argv, env, prompt = body.get("cwd"), body.get("argv"), body.get("env") or {}, body.get("prompt") or ""
    library = body.get("library")
    if not isinstance(cwd, str) or not CWD.match(cwd) or ".." in cwd:
        raise HTTPException(400, "cwd must be a dashboard folder under /data/projects")
    if not isinstance(argv, list) or not argv or argv[0] != "claude" or not all(isinstance(a, str) for a in argv):
        raise HTTPException(400, "argv must be a claude command")
    if not isinstance(env, dict) or not all(isinstance(k, str) and ENV_KEY.match(k) and isinstance(v, str) for k, v in env.items()):
        raise HTTPException(400, "env must map names to strings")
    if library is not None and (not isinstance(library, str) or not (library == LIBRARY or library.startswith(LIBRARY + "/"))
                                or ".." in library):
        raise HTTPException(400, "library must be inside the visual library")
    w = await web_info()
    if not w["running"]:
        raise HTTPException(503, "the web container is not running")
    m = w["mounts"]
    if PROJECTS not in m or "/home/agent/.claude" not in m:
        raise HTTPException(503, "the web container has no projects or Claude sign-in mount")
    async with docker() as d:                       # the folder must exist in the web container (never create one)
        r = await d.head(f"/containers/{w['id']}/archive", params={"path": cwd})
        if r.status_code != 200:
            raise HTTPException(404, "no such dashboard folder")
    agent = pwd.getpwnam("agent")
    mounts = [{**source(m[PROJECTS], cwd[len(PROJECTS):]), "Target": cwd},
              {**source(m["/home/agent/.claude"]), "Target": "/home/agent/.claude"}]
    if library and LIBRARY in m:
        mounts.append({**source(m[LIBRARY], library[len(LIBRARY):]), "Target": library, "ReadOnly": True})
    if "/opt/genbi/config" in m:
        mounts.append({**source(m["/opt/genbi/config"]), "Target": "/opt/genbi/config", "ReadOnly": True})
    name = "d2d-relay-job-" + time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3)
    spec = {"Image": w["image"], "User": "agent", "WorkingDir": cwd, "Env": [f"{k}={v}" for k, v in env.items()],
            "Entrypoint": ["/usr/bin/tini", "--", "/usr/local/bin/python3", "-P", "/opt/relay/bin/job-run"],
            "Cmd": ["/tmp/relay-prompt", *argv], "Labels": {"d2d-relay.job": "1", "d2d-relay.cwd": cwd},
            "HostConfig": {"Mounts": mounts, "NetworkMode": f"container:{w['id']}", "CapDrop": ["ALL"],
                           "SecurityOpt": ["no-new-privileges"], "AutoRemove": False, **LIMITS}}
    async with docker() as d:
        r = await d.post("/containers/create", params={"name": name}, json=spec)
        if r.status_code != 201:
            raise HTTPException(502, f"Docker refused the job container: {r.text[:300]}")
        cid = r.json()["Id"]
        r = await d.put(f"/containers/{cid}/archive", params={"path": "/tmp"},
                        content=tar_of("relay-prompt", prompt.encode(), agent.pw_uid, agent.pw_gid),
                        headers={"Content-Type": "application/x-tar"})
        if r.status_code != 200:
            await d.delete(f"/containers/{cid}", params={"force": "true"})
            raise HTTPException(502, f"Docker refused the job's prompt: {r.text[:300]}")
        r = await d.post(f"/containers/{cid}/start")
        if r.status_code not in (204, 304):
            await d.delete(f"/containers/{cid}", params={"force": "true"})
            raise HTTPException(502, f"Docker could not start the job container: {r.text[:300]}")
    print(f"[runner] started {name} for {cwd}: " + ", ".join(f"{x['Target']}{' (read-only)' if x.get('ReadOnly') else ''}"
                                                           for x in mounts), flush=True)

    async def stream():
        out, err, ended = bytearray(), bytearray(), False
        try:
            async with docker() as d:
                async with d.stream("GET", f"/containers/{cid}/logs",
                                    params={"follow": "true", "stdout": "true", "stderr": "true"}) as r:
                    buf = bytearray()
                    async for chunk in r.aiter_bytes():
                        buf += chunk
                        for kind, payload in frames(buf):
                            if kind == 2:
                                err += payload
                                del err[:-8000]
                                continue
                            out += payload
                            while b"\n" in out:
                                line, _, rest = bytes(out).partition(b"\n")
                                out[:] = rest
                                yield json.dumps({"o": line.decode("utf-8", "replace")}) + "\n"
                if out:
                    yield json.dumps({"o": bytes(out).decode("utf-8", "replace")}) + "\n"
                code = (await d.post(f"/containers/{cid}/wait")).json().get("StatusCode", 1)
                ended = True
                yield json.dumps({"x": code, "e": bytes(err[-3000:]).decode("utf-8", "replace")}) + "\n"
        finally:                                    # done, Stop, or the AI engine went away: never leave a job running
            async with docker() as d:
                if not ended:
                    await d.post(f"/containers/{cid}/kill")
                await d.delete(f"/containers/{cid}", params={"force": "true"})
            print(f"[runner] removed {name} ({'finished' if ended else 'stopped'})", flush=True)

    return StreamingResponse(stream(), media_type="application/x-ndjson")


async def sweep() -> None:
    """Job containers a crash or a restart left behind are removed at start."""
    async with docker() as d:
        r = await d.get("/containers/json", params={"all": "true", "filters": json.dumps({"label": ["d2d-relay.job=1"]})})
        for c in r.json() if r.status_code == 200 else []:
            await d.delete(f"/containers/{c['Id']}", params={"force": "true"})
            print(f"[runner] removed a job left from before: {c['Names'][0] if c.get('Names') else c['Id'][:12]}", flush=True)


def main() -> None:
    os.makedirs(os.path.dirname(SOCK), exist_ok=True)
    if os.path.exists(SOCK):
        os.unlink(SOCK)
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.bind(SOCK)
    agent = pwd.getpwnam("agent")
    os.chown(SOCK, agent.pw_uid, agent.pw_gid)          # only the AI engine's user may connect
    os.chmod(SOCK, 0o600)
    try:
        asyncio.run(sweep())
    except Exception as e:  # noqa: BLE001 - the runner still starts; Docker is checked again on every job
        print(f"[runner] could not list old jobs: {e}", flush=True)
    print(f"[runner] serving on {SOCK} for the web container {WEB}", flush=True)
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", access_log=False))
    asyncio.run(server.serve(sockets=[s]))


if __name__ == "__main__":
    sys.exit(main())
