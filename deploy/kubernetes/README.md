# D2D on Kubernetes

Platform plan, phase 8. The same images as `docker compose`, with:

- **Postgres** for the index (`D2D_DATABASE_URL`), a StatefulSet here — or a managed Postgres.
- **The orchestrator's Kubernetes backend** (`D2D_ORCH_BACKEND=kubernetes`). Each person's workspace is a Deployment
  `d2d-ws-<user>` (scaled to 1 to start, to 0 when idle), a Service and their own login volume. The orchestrator's
  Role covers only Deployments, Services and PersistentVolumeClaims in this namespace.
- **Network policies**: only the web app reaches the orchestrator, the agents, Postgres and the workspaces; the
  agents reach the gateway.
- `/healthz` for probes, `/metrics` for Prometheus (token from the secret).

Tested on a one-node k3s cluster with `tests/phase8_k8s_test.sh`: all pods ready, a workspace started, called,
stopped and removed, network policies enforced, metrics served.

## Overlays

| Folder | For | Shared volumes | Images |
| --- | --- | --- | --- |
| `local/` | one node: k3s, kind, Docker Desktop | ReadWriteOnce | the locally built `gen-bi-*:latest` (imported into the cluster) |
| `cluster/` | a real cluster | ReadWriteMany storage class (edit it) | your registry (edit `images:`), an nginx ingress with TLS |

## Install (local)

```bash
docker compose build
```

Import the images into the cluster. For k3s, `docker save gen-bi-webapp:latest gen-bi-agent:latest gen-bi-orchestrator:latest gen-bi-litellm:latest postgres:17.6-alpine | docker exec -i <k3s container> ctr -n k8s.io images import -`. For kind, use `kind load docker-image`.

```bash
cp deploy/kubernetes/secrets.example.env deploy/kubernetes/local/secrets.env
```

```bash
cp deploy/kubernetes/orch-token.example.env deploy/kubernetes/local/orch-token.env
```

Fill both files in (never commit them), then:

```bash
kubectl apply -k deploy/kubernetes/local
```

```bash
kubectl -n d2d port-forward svc/webapp 8000:8000
```

The models list the agents read is the `d2d-config` ConfigMap: `kubectl -n d2d create configmap d2d-config --from-file=config/models.json`.

## Moving an existing installation's data

The index (people, sharing, metrics, schedules, costs…) moves with the web app's own tool; project folders are files
to copy into the `d2d-projects` volume.

```bash
kubectl -n d2d exec deploy/webapp -- python -m app.dbmove --from-sqlite /path/to/index.db
```

## Known limits

- **DAX checker**: it runs on a Windows PC with Power BI Desktop and reads a queue folder in the projects volume.
  In a cluster the PC needs that volume (an SMB / Azure Files share), or Power BI publishing waits. Admin › Monitoring
  shows the checker's queue and warns when it falls behind; the plan's decision is to keep the PC until a client has
  no PC in the loop.
- **One web app replica**: the job worker, schedulers and watchdog run in-process.

## Other runners (Codex, Gemini, Antigravity) — the `runners` component

`runners/` adds the three runner images (`docker compose --profile runners build`) as Deployments and Services named
`agent-codex`, `agent-gemini` and `agent-antigravity` (the names the web app calls), only reachable from the web app,
with the Antigravity Google login on its own claim `d2d-agy-auth` (mounted read-only). Add it to an overlay:

```yaml
components:
  - ../runners
```

Copy the login in once (`antigravity-oauth-token` and `cache/default_project_id.txt` from the antigravity-api
gateway's login): start a pod that mounts `d2d-agy-auth` read-write, `kubectl cp` the files into it, delete the pod.

## A client's own install (P17 dedicated deployment)

Platform › Tenants › a client › Deployment › **Make the deployment pack** gives a zip with the client's export, the
settings of a one-workspace install and `kubernetes/kustomization.yaml`. Put that folder at
`deploy/kubernetes/clients/<tenant>/`, write `secrets.env` and `orch-token.env` next to it from the `.example` files
(`secret-key` = the key shown once with the pack), then:

```bash
kubectl apply -k deploy/kubernetes/clients/<tenant>
kubectl -n relay-<tenant> exec deploy/webapp -- python -m app.tenantmove import /data/backups/tenant-export.tar.gz --as-platform
```

The overlay runs in namespace `relay-<tenant>` with `D2D_TENANCY=single` and `D2D_PLATFORM_TENANT=<tenant>`, and
includes the runners component (remove that line to run Claude only). `tests/p17_k8s_check.py` renders all of it.
