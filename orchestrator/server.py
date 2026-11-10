"""Relay orchestrator (platform plan, phases 2 and 8): the only service that can create containers.

It manages one workspace instance per person — an agent (the Claude Code agent image) with its own storage for the
person's Claude login and settings — and exposes only: start (create on first use), stop, status, list, destroy,
upgrade, and a restart of the LiteLLM gateway. The web app decides when (first sign-in, idle, offboarding); this
service decides how, and enforces the capacity cap (MAX running instances; others wait in a start queue).

Two backends behind the same endpoints (D2D_ORCH_BACKEND):
- `docker` (default, phase 2): containers through the Docker socket (Docker Engine API over the Unix socket).
- `kubernetes` (phase 8): one Deployment (scaled to 1 to start, 0 to stop), Service and PersistentVolumeClaim per
  person, in this namespace, through the Kubernetes API with the pod's service account (a Role limited to those
  three kinds in one namespace — see deploy/kubernetes/). Projects, config and the visual library are shared
  volumes (a ReadWriteMany claim and a ConfigMap).
Instances are never deleted and recreated, except on offboarding (destroy) or when the agent image changed while
the instance was stopped (upgrade).

Every request must carry the token from /data/orch/token (created here on first start; the web app reads it).
"""
import json
import os
import re
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException

IMAGE = os.environ.get("D2D_AGENT_IMAGE", "gen-bi-agent:latest")
NETWORK = os.environ.get("D2D_NETWORK", "gen-bi_default")
PREFIX = os.environ.get("D2D_INSTANCE_PREFIX", "d2d-ws-")
MAX = int(os.environ.get("D2D_MAX_INSTANCES", "10"))
CPUS = float(os.environ.get("D2D_INSTANCE_CPUS", "2"))
MEMORY_GB = float(os.environ.get("D2D_INSTANCE_MEMORY_GB", "4"))
HOST_PROJECTS = os.environ.get("HOST_PROJECTS_DIR", "")
HOST_LIBRARY = os.environ.get("HOST_LIBRARY_DIR", "")
HOST_CONFIG = os.environ.get("HOST_CONFIG_DIR", "")
AGENT_MODEL = os.environ.get("AGENT_MODEL", "sonnet")
TOKEN_FILE = Path(os.environ.get("D2D_ORCH_TOKEN_FILE", "/data/orch/token"))
KIND = os.environ.get("D2D_ORCH_BACKEND", "docker")
UID = re.compile(r"^u-[a-z0-9-]{2,40}$")
WAITING: dict[str, float] = {}          # uid -> when it asked to start (capacity queue)

if not TOKEN_FILE.exists():
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(secrets.token_urlsafe(32))
    os.chmod(TOKEN_FILE, 0o644)          # readable by the web app (uid 1000); the volume is mounted by nobody else
TOKEN = TOKEN_FILE.read_text().strip()

app = FastAPI(title="Relay orchestrator")


def guard(x_d2d_orch: str = Header("")):
    if not secrets.compare_digest(x_d2d_orch, TOKEN):
        raise HTTPException(401, "bad token")


def _name(uid: str) -> str:
    if not UID.match(uid):
        raise HTTPException(400, "bad user id")
    return PREFIX + uid


# ---------------------------------------------------------------- Docker (phase 2)

class DockerBackend:
    kind = "docker"

    def __init__(self):
        self.api = httpx.Client(transport=httpx.HTTPTransport(uds="/var/run/docker.sock"), base_url="http://docker", timeout=60)

    def _d(self, method: str, path: str, **kw) -> httpx.Response:
        return self.api.request(method, path, **kw)

    @staticmethod
    def _host_dir(kind: str) -> str:
        """Host folders to bind into instances (Docker Desktop accepts Windows paths)."""
        if kind == "projects":
            return HOST_PROJECTS
        if kind == "library":
            return HOST_LIBRARY
        if HOST_CONFIG:
            return HOST_CONFIG
        if "\\" in HOST_PROJECTS:
            return str(PureWindowsPath(HOST_PROJECTS).parent.parent / "config")
        return str(Path(HOST_PROJECTS).parent.parent / "config")

    def _inspect(self, name: str) -> dict | None:
        r = self._d("GET", f"/containers/{name}/json")
        return r.json() if r.status_code == 200 else None

    def _image_id(self) -> str:
        r = self._d("GET", f"/images/{IMAGE}/json")
        if r.status_code != 200:
            raise HTTPException(503, f"agent image {IMAGE} is not built")
        return r.json()["Id"]

    def _state(self, c: dict | None) -> dict:
        if not c:
            return {"state": "absent"}
        st = c["State"]
        health = (st.get("Health") or {}).get("Status")
        state = "running" if st["Running"] and health in (None, "healthy") else "starting" if st["Running"] else "stopped"
        labels = c["Config"].get("Labels") or {}
        return {"state": state, "health": health, "started": st.get("StartedAt"), "finished": st.get("FinishedAt"),
                "user": labels.get("d2d.user"), "image_current": c["Image"] == self._image_id(), "name": c["Name"].lstrip("/"),
                "url": f"http://{c['Name'].lstrip('/')}:8090"}

    def running(self) -> list[str]:
        r = self._d("GET", "/containers/json", params={"filters": '{"label":["d2d.instance=1"],"status":["running"]}'})
        return [(c["Labels"] or {}).get("d2d.user") for c in r.json()]

    def _create(self, uid: str, name: str) -> None:
        vol = f"{name}-claude"
        self._d("POST", "/volumes/create", json={"Name": vol, "Labels": {"d2d.instance": "1", "d2d.user": uid}})
        binds = [f"{vol}:/home/node/.claude", f"{self._host_dir('projects')}:/data/projects",
                 f"{self._host_dir('config')}:/opt/genbi/config:ro"]
        if HOST_LIBRARY:
            binds.append(f"{HOST_LIBRARY}:/opt/genbi/library:ro")
        body = {"Image": IMAGE, "Env": [f"AGENT_MODEL={AGENT_MODEL}", f"D2D_INSTANCE_USER={uid}"],
                "Labels": {"d2d.instance": "1", "d2d.user": uid},
                "HostConfig": {"Binds": binds, "NetworkMode": NETWORK, "NanoCpus": int(CPUS * 1e9),
                               "Memory": int(MEMORY_GB * 1024 ** 3), "RestartPolicy": {"Name": "no"}}}
        r = self._d("POST", "/containers/create", params={"name": name}, json=body)
        if r.status_code not in (200, 201):
            raise HTTPException(502, f"could not create the workspace: {r.text[:300]}")

    def ok(self) -> bool:
        return self._d("GET", "/_ping").status_code == 200

    def states(self) -> list[dict]:
        r = self._d("GET", "/containers/json", params={"all": "true", "filters": '{"label":["d2d.instance=1"]}'})
        return [self._state(self._inspect(c["Id"])) for c in r.json()]

    def status(self, name: str) -> dict:
        return self._state(self._inspect(name))

    def is_running(self, name: str) -> bool:
        c = self._inspect(name)
        return bool(c and c["State"]["Running"])

    def start(self, uid: str, name: str) -> dict:
        c = self._inspect(name)
        if c and c["Image"] != self._image_id():               # upgrade: new container, same volumes
            self._d("DELETE", f"/containers/{name}", params={"force": "true"})
            c = None
        if not c:
            self._create(uid, name)
        r = self._d("POST", f"/containers/{name}/start")
        if r.status_code not in (204, 304):
            raise HTTPException(502, f"could not start the workspace: {r.text[:300]}")
        return self.status(name)

    def stop(self, name: str) -> dict:
        if self._inspect(name) is None:
            return {"state": "absent"}
        self._d("POST", f"/containers/{name}/stop", params={"t": "20"})
        return self.status(name)

    def destroy(self, name: str) -> None:
        self._d("DELETE", f"/containers/{name}", params={"force": "true", "v": "true"})
        self._d("DELETE", f"/volumes/{name}-claude", params={"force": "true"})

    def upgrade(self) -> list[str]:
        done = []
        for s in self.states():
            if s["state"] == "stopped" and not s["image_current"]:
                self._d("DELETE", f"/containers/{s['name']}", params={"force": "true"})
                self._create(s["user"], s["name"])
                done.append(s["user"])
        return done

    def restart_gateway(self) -> int:
        r = self._d("GET", "/containers/json", params={"filters": '{"label":["com.docker.compose.service=litellm"]}'})
        for c in r.json():
            self._d("POST", f"/containers/{c['Id']}/restart", params={"t": "5"})
        return len(r.json())


# ---------------------------------------------------------------- Kubernetes (phase 8)

SA = Path("/var/run/secrets/kubernetes.io/serviceaccount")


class KubernetesBackend:
    """Plain HTTP to the API server with the pod's service account (or D2D_KUBE_API / D2D_KUBE_TOKEN for tests)."""
    kind = "kubernetes"

    def __init__(self):
        api = os.environ.get("D2D_KUBE_API", "https://kubernetes.default.svc")
        token = os.environ.get("D2D_KUBE_TOKEN") or ((SA / "token").read_text().strip() if (SA / "token").exists() else "")
        ca = os.environ.get("D2D_KUBE_CA") or (str(SA / "ca.crt") if (SA / "ca.crt").exists() else True)
        self.ns = os.environ.get("D2D_NAMESPACE") or ((SA / "namespace").read_text().strip() if (SA / "namespace").exists() else "d2d")
        self.api = httpx.Client(base_url=api, headers={"Authorization": f"Bearer {token}"} if token else {}, verify=ca, timeout=30)
        self.projects = os.environ.get("D2D_PROJECTS_PVC", "d2d-projects")
        self.library = os.environ.get("D2D_LIBRARY_PVC", "")
        self.config = os.environ.get("D2D_CONFIG_MAP", "d2d-config")
        self.claude_size = os.environ.get("D2D_INSTANCE_STORAGE", "1Gi")
        self.storage_class = os.environ.get("D2D_STORAGE_CLASS", "")
        self.pull = os.environ.get("D2D_IMAGE_PULL_POLICY", "IfNotPresent")
        self.gateway = os.environ.get("D2D_GATEWAY_DEPLOYMENT", "litellm")

    def _k(self, method: str, path: str, **kw) -> httpx.Response:
        return self.api.request(method, path, **kw)

    def _apps(self, rest: str = "") -> str:
        return f"/apis/apps/v1/namespaces/{self.ns}/deployments{rest}"

    def _core(self, kind: str, rest: str = "") -> str:
        return f"/api/v1/namespaces/{self.ns}/{kind}{rest}"

    def _check(self, r: httpx.Response, what: str, ok=(200, 201, 202)) -> httpx.Response:
        if r.status_code not in ok:
            raise HTTPException(502, f"Kubernetes refused to {what} ({r.status_code}): {r.text[:300]}")
        return r

    @staticmethod
    def _labels(uid: str) -> dict:
        return {"app.kubernetes.io/name": "d2d-workspace", "app.kubernetes.io/part-of": "d2d", "d2d.instance": "1", "d2d.user": uid}

    def _deployment(self, uid: str, name: str) -> dict:
        mounts = [{"name": "claude", "mountPath": "/home/node/.claude"}, {"name": "projects", "mountPath": "/data/projects"},
                  {"name": "config", "mountPath": "/opt/genbi/config", "readOnly": True}]
        vols = [{"name": "claude", "persistentVolumeClaim": {"claimName": f"{name}-claude"}},
                {"name": "projects", "persistentVolumeClaim": {"claimName": self.projects}},
                {"name": "config", "configMap": {"name": self.config, "optional": True}}]
        if self.library:
            mounts.append({"name": "library", "mountPath": "/opt/genbi/library", "readOnly": True})
            vols.append({"name": "library", "persistentVolumeClaim": {"claimName": self.library, "readOnly": True}})
        mem = f"{int(MEMORY_GB * 1024)}Mi"
        return {"apiVersion": "apps/v1", "kind": "Deployment", "metadata": {"name": name, "labels": self._labels(uid)},
                "spec": {"replicas": 0, "strategy": {"type": "Recreate"},           # one login volume (ReadWriteOnce)
                         "selector": {"matchLabels": {"d2d.user": uid, "app.kubernetes.io/name": "d2d-workspace"}},
                         "template": {"metadata": {"labels": self._labels(uid)},
                                      "spec": {"automountServiceAccountToken": False, "enableServiceLinks": False,
                                               "securityContext": {"runAsNonRoot": True, "runAsUser": 1000, "fsGroup": 1000},
                                               "containers": [{"name": "agent", "image": IMAGE, "imagePullPolicy": self.pull,
                                                               "env": [{"name": "AGENT_MODEL", "value": AGENT_MODEL},
                                                                       {"name": "D2D_INSTANCE_USER", "value": uid}],
                                                               "ports": [{"containerPort": 8090, "name": "http"}],
                                                               "readinessProbe": {"httpGet": {"path": "/health", "port": 8090}, "periodSeconds": 5},
                                                               "resources": {"requests": {"cpu": str(min(CPUS, 0.5)), "memory": "512Mi"},
                                                                             "limits": {"cpu": str(CPUS), "memory": mem}},
                                                               "securityContext": {"allowPrivilegeEscalation": False, "capabilities": {"drop": ["ALL"]}},
                                                               "volumeMounts": mounts}],
                                               "volumes": vols}}}}

    def _create(self, uid: str, name: str) -> None:
        pvc = {"apiVersion": "v1", "kind": "PersistentVolumeClaim", "metadata": {"name": f"{name}-claude", "labels": self._labels(uid)},
               "spec": {"accessModes": ["ReadWriteOnce"], "resources": {"requests": {"storage": self.claude_size}}}}
        if self.storage_class:
            pvc["spec"]["storageClassName"] = self.storage_class
        svc = {"apiVersion": "v1", "kind": "Service", "metadata": {"name": name, "labels": self._labels(uid)},
               "spec": {"selector": {"d2d.user": uid, "app.kubernetes.io/name": "d2d-workspace"}, "ports": [{"port": 8090, "targetPort": 8090, "name": "http"}]}}
        self._check(self._k("POST", self._core("persistentvolumeclaims"), json=pvc), "create the login volume", (200, 201, 202, 409))
        self._check(self._k("POST", self._core("services"), json=svc), "create the service", (200, 201, 202, 409))
        self._check(self._k("POST", self._apps(), json=self._deployment(uid, name)), "create the workspace", (200, 201, 202, 409))

    def _get(self, name: str) -> dict | None:
        r = self._k("GET", self._apps(f"/{name}"))
        return r.json() if r.status_code == 200 else None

    def _state(self, d: dict | None) -> dict:
        if not d:
            return {"state": "absent"}
        want, st = d["spec"].get("replicas") or 0, d.get("status") or {}
        ready = st.get("readyReplicas") or 0
        state = "stopped" if want == 0 else "running" if ready >= 1 and (st.get("updatedReplicas") or 0) >= 1 else "starting"
        name = d["metadata"]["name"]
        cond = {c["type"]: c for c in st.get("conditions") or []}
        return {"state": state, "health": "healthy" if state == "running" else None,
                "started": (cond.get("Available") or {}).get("lastTransitionTime"), "finished": None,
                "user": d["metadata"]["labels"].get("d2d.user"), "name": name,
                "image_current": d["spec"]["template"]["spec"]["containers"][0]["image"] == IMAGE,
                "url": f"http://{name}.{self.ns}.svc:8090"}

    def _scale(self, name: str, n: int) -> None:
        self._check(self._k("PATCH", self._apps(f"/{name}/scale"), json={"spec": {"replicas": n}},
                            headers={"Content-Type": "application/merge-patch+json"}), "scale the workspace")

    def _set_image(self, name: str) -> None:
        patch = {"spec": {"template": {"spec": {"containers": [{"name": "agent", "image": IMAGE}]}}}}
        self._check(self._k("PATCH", self._apps(f"/{name}"), json=patch, headers={"Content-Type": "application/strategic-merge-patch+json"}),
                    "update the workspace image")

    def _all(self) -> list[dict]:
        r = self._check(self._k("GET", self._apps(), params={"labelSelector": "d2d.instance=1"}), "list workspaces")
        return r.json().get("items") or []

    def ok(self) -> bool:
        try:
            return self._k("GET", self._apps(), params={"limit": 1}).status_code == 200
        except httpx.HTTPError:
            return False

    def running(self) -> list[str]:
        return [d["metadata"]["labels"].get("d2d.user") for d in self._all() if (d["spec"].get("replicas") or 0) > 0]

    def states(self) -> list[dict]:
        return [self._state(d) for d in self._all()]

    def status(self, name: str) -> dict:
        return self._state(self._get(name))

    def is_running(self, name: str) -> bool:
        d = self._get(name)
        return bool(d and (d["spec"].get("replicas") or 0) > 0)

    def start(self, uid: str, name: str) -> dict:
        d = self._get(name)
        if not d:
            self._create(uid, name)
        elif d["spec"]["template"]["spec"]["containers"][0]["image"] != IMAGE:
            self._set_image(name)                                # upgrade: same volumes, new image
        self._scale(name, 1)
        return self.status(name)

    def stop(self, name: str) -> dict:
        if not self._get(name):
            return {"state": "absent"}
        self._scale(name, 0)
        return self.status(name)

    def destroy(self, name: str) -> None:
        self._k("DELETE", self._apps(f"/{name}"), params={"propagationPolicy": "Foreground"})
        self._k("DELETE", self._core("services", f"/{name}"))
        self._k("DELETE", self._core("persistentvolumeclaims", f"/{name}-claude"))

    def upgrade(self) -> list[str]:
        done = []
        for s in self.states():
            if s["state"] == "stopped" and not s["image_current"]:
                self._set_image(s["name"])
                done.append(s["user"])
        return done

    def restart_gateway(self) -> int:
        stamp = datetime.now(timezone.utc).isoformat()
        r = self._k("PATCH", self._apps(f"/{self.gateway}"), headers={"Content-Type": "application/strategic-merge-patch+json"},
                    content=json.dumps({"spec": {"template": {"metadata": {"annotations": {"d2d/restartedAt": stamp}}}}}))
        return 1 if r.status_code == 200 else 0


BACKEND = KubernetesBackend() if KIND == "kubernetes" else DockerBackend()


# ---------------------------------------------------------------- endpoints (the same for both backends)

@app.get("/health")
def health():
    ok = BACKEND.ok()
    return {"ok": ok, "backend": BACKEND.kind, "image": IMAGE, "max": MAX, "running": len(BACKEND.running()) if ok else None}


@app.get("/instances", dependencies=[Depends(guard)])
def instances():
    return {"instances": BACKEND.states(), "max": MAX, "waiting": sorted(WAITING, key=WAITING.get), "backend": BACKEND.kind}


@app.get("/instances/{uid}", dependencies=[Depends(guard)])
def status(uid: str):
    s = BACKEND.status(_name(uid))
    if uid in WAITING and s["state"] != "running":
        s.update(state="queued", position=sorted(WAITING, key=WAITING.get).index(uid) + 1)
    return s


@app.post("/instances/{uid}/start", dependencies=[Depends(guard)])
def start(uid: str):
    """Create on first use, start when stopped, upgrade on the same volumes if the image changed while stopped.
    Over the capacity cap the person waits in the start queue (call again to move up)."""
    name = _name(uid)
    if BACKEND.is_running(name):
        WAITING.pop(uid, None)
        return BACKEND.status(name)
    running = [u for u in BACKEND.running() if u != uid]
    WAITING.setdefault(uid, time.time())
    queue = sorted(WAITING, key=WAITING.get)
    free = MAX - len(running)
    if free <= 0 or queue.index(uid) >= free:
        return {"state": "queued", "position": queue.index(uid) + 1 - max(free, 0), "max": MAX}
    s = BACKEND.start(uid, name)
    WAITING.pop(uid, None)
    return s


@app.post("/instances/{uid}/stop", dependencies=[Depends(guard)])
def stop(uid: str):
    name = _name(uid)
    WAITING.pop(uid, None)
    return BACKEND.stop(name)


@app.delete("/instances/{uid}", dependencies=[Depends(guard)])
def destroy(uid: str):
    """Offboarding only: remove the workspace and the person's login volume."""
    name = _name(uid)
    WAITING.pop(uid, None)
    BACKEND.destroy(name)
    return {"state": "absent"}


@app.post("/upgrade", dependencies=[Depends(guard)])
def upgrade():
    """Update stopped instances whose image is out of date (running ones are updated at their next start)."""
    return {"recreated": BACKEND.upgrade()}


@app.post("/services/litellm/restart", dependencies=[Depends(guard)])
def restart_gateway():
    """Load a new gateway config (the web app wrote it)."""
    return {"restarted": BACKEND.restart_gateway()}
