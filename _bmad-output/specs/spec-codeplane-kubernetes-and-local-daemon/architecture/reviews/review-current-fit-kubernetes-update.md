# Current-Fit Review — Kubernetes Update

**Review date:** 2026-08-05  
**Verdict:** Conditional pass before fixes

Authoritative upstream documentation confirmed Kubernetes 1.34-1.36 as the maintained-minor baseline, core `v1` PersistentVolume/PVC APIs, `snapshot.storage.k8s.io/v1` when installed, `coordination.k8s.io/v1` Lease, and Helm chart API v2. No hidden PostgreSQL, S3, Redis, external database, or external object-store prerequisite was found.

## Findings applied

- Helm 4.2.x is current and chart API v2 remains supported, but the spine lacked a Helm CLI qualification range. The stack now qualifies Helm 3.19.x and 4.2.x.
- Gateway API uses `gateway.networking.k8s.io/v1`, not the Ingress API group. AD-19 now names both groups correctly.
- FastAPI `0.115.x` did not match the repository lock. The stack now records 0.136.3 as the locked baseline and `>=0.115,<1` as the supported range.

## Sources

- https://kubernetes.io/releases/
- https://kubernetes.io/docs/concepts/storage/persistent-volumes/
- https://kubernetes.io/docs/concepts/storage/volume-snapshots/
- https://helm.sh/docs/topics/charts/
- https://helm.sh/docs/changelog/
