# Deployment

Target: the homelab Kubernetes cluster, reachable only over Tailscale, deployed through
GitOps. This is the last milestone (M5), but some choices (one image, stateless pods,
migrations as a job, model weights from Garage) are made earlier so it stays simple.

## Responsibilities

| Lives in | Contents |
|---|---|
| Homelab GitOps repo (separate) | Argo CD, Tailscale Kubernetes operator, CloudNativePG operator and cluster, Garage, kube-prometheus-stack, Loki, SOPS/age key, and an Argo CD `Application` pointing at this repo's `deploy/overlays/homelab` |
| This repo | Dockerfile, Kustomize base and homelab overlay, CI workflows |

The homelab platform is a prerequisite for WP 26 and is not built by this plan.

## Image (WP 25)

`deploy/Dockerfile`, multi-stage:

1. `node` stage: `npm ci && npm run build` in `frontend/`.
2. `uv` stage: `uv sync --locked --no-dev --extra api --extra vision` into `/app/.venv`.
3. Runtime: slim Python 3.13 image, non-root user, copies the venv, `src/`, and
   `frontend/dist`. Entrypoint `hive serve` (uvicorn). No torch, no model weights.

One image serves the API and the frontend and runs migrations (`hive db upgrade`).

## CI release (WP 25)

`.github/workflows/release.yaml` on push to `main` after CI passes:

1. Build and push `ghcr.io/maxvandenhoven/hive:<git-sha>` (and `:main`).
2. Commit the new tag to `deploy/overlays/homelab/kustomization.yaml`
   (`images[].newTag`) with a conventional commit such as
   `chore(deploy): bump image to <sha>`, skipped by CI path filters to avoid loops.

Rollback is `git revert` of the bump commit.

## Manifests (WP 26)

```
deploy/
├─ base/
│  ├─ kustomization.yaml
│  ├─ deployment.yaml        # hive serve; probes /healthz, /readyz; resources; env from secret
│  ├─ service.yaml
│  ├─ ingress.yaml           # ingressClassName: tailscale, host hive → https://hive.<tailnet>.ts.net
│  ├─ servicemonitor.yaml    # scrape /metrics
│  ├─ migrate-job.yaml       # hive db upgrade; argocd.argoproj.io/hook: PreSync
│  └─ database.yaml          # CloudNativePG Database + role (or documented manual step)
└─ overlays/homelab/
   ├─ kustomization.yaml     # image tag, replicas, resources
   ├─ config.env             # HIVE_MODEL_VERSION, pool size, budgets
   └─ secrets.enc.yaml       # SOPS-encrypted: DB URL, S3 keys
```

Notes:

- Migrations run as an Argo CD PreSync Job, never on app startup, so replicas never race.
- The model is downloaded from Garage at startup (`HIVE_MODEL_VERSION`); switching or
  rolling back a model is a one-line overlay change.
- CPU requests match the worker pool: pool size = CPU request − 1. Start with one replica;
  the stateless design allows more later (each replica has its own pool).
- The Tailscale ingress provides HTTPS with a valid certificate, which the phone camera
  requires.
- Logs go to stdout as JSON for Loki; metrics via `ServiceMonitor` for Prometheus. A
  Grafana dashboard JSON (requests, decisions, overruns, pool, photo matching) lives in
  `deploy/grafana/` and is loaded by the homelab repo.

## Done when

Merging to `main` builds and pushes the image, bumps the tag, Argo CD syncs, migrations run,
and the app is reachable at `https://hive.<tailnet>.ts.net` with metrics in Grafana.
