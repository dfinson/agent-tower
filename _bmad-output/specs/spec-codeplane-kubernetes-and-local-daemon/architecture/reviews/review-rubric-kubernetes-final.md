# BMad Good-Spine Review — Kubernetes Final Gate

**Reviewed artifact:** `../ARCHITECTURE-SPINE.md`  
**Review date:** 2026-08-05  
**Scope:** Final rubric gate against the BMad good-spine checklist and the Kubernetes-native, no-PostgreSQL, no-S3 baseline. The spine was not edited.

## Verdict

**NOT READY — no critical findings remain, but one high-severity source-contract mismatch still leaves the new Kubernetes-native invariants unprotected.**

The substantive architecture blockers are closed. The spine now fixes a viable RWO storage topology, separates baseline and production installation prerequisites, scopes recovery guarantees, gives CAP-22 executable lifecycle evidence, and completes the operational envelope without requiring PostgreSQL, S3, or another external state service. However, the canonical `SPEC.md` preservation clause still protects only AD-1 through AD-32 while the spine's load-bearing Kubernetes-native decisions now extend through AD-35. Independent downstream units can therefore follow the canonical source contract while omitting the control-resource, storage-gateway, or controller-authority invariants.

## Review Method

- Ran `lint_spine.py --workspace architecture`: **0 findings**.
- Walked AD-1 through AD-35 for `Binds`, `Prevents`, and enforceable `Rule` alignment.
- Traced CAP-1 through CAP-24 through the capability map and architecture acceptance criteria.
- Rechecked the prior blockers: storage topology, installation profile, source anchor, CAP-22, and operational completeness.
- Checked the baseline specifically for hidden PostgreSQL, S3, hosted CodePlane, RWX, or other external state-service prerequisites.
- Reconciled the spine with its normative `SPEC.md`, `mode-requirements.md`, `brownfield-constraints.md`, and architecture memlog.

## Good-Spine Checklist

| Criterion | Result | Assessment |
| --- | --- | --- |
| Real divergence points covered | **Pass** | Mode composition, control/execution separation, tenancy, identity, mutation, event history, storage ownership, scheduling, repository ownership, installation, upgrade, recovery, and interoperability are fixed at the right altitude. |
| Enforceable AD Rules | **Pass** | AD-34 names mounts, access mode, writer authority, and failover fencing; AD-35 names installation versus tenant authority; acceptance criteria exercise the important seams. |
| Nothing unsafe deferred | **Pass** | Deferred storage details are implementation choices behind AD-31/AD-34. RWX and external object storage are explicitly enhanced/optional profiles, not baseline assumptions. |
| Current named technology | **Pass** | The pinned FastAPI baseline matches the lock noted by the prior review; Kubernetes 1.34-1.36 and the named stable storage APIs are coherent with the cited sources. |
| Brownfield compatibility | **Pass** | Local-daemon remains autonomous, SQLite/filesystem based, offline capable, and explicitly bounded by the OS-user trust model. Existing CLI, Git, event, restart, and frontend/backend conventions remain governed. |
| CAP-1 through CAP-24 coverage | **Pass** | Every CAP is mapped. CAP-22 now has AC-17 covering every required command and preservation behavior. |
| Stable parent/source constraints | **Fail** | The spine now points to the correct architecture `.memlog.md`, but canonical `SPEC.md` still says downstream work need preserve only AD-1 through AD-32. |
| Complete operational envelope | **Pass** | Platform/version support, chart and CRD lifecycle, install prerequisites, disconnected distribution, HA, scale, SLOs, upgrade/rollback/uninstall, security, observability, backup/restore, retention, cancellation, and migration are explicit. |
| Kubernetes-native without PostgreSQL/S3 | **Pass** | CRDs plus chart-managed controllers/gateways and CSI RWO PVCs form the baseline. PostgreSQL, S3, RWX, hosted CodePlane, and external object storage are not required. |

## Prior Blocker Closure

### Storage topology — CLOSED

AD-34 fixes one single-active storage gateway per tenant over tenant-scoped RWO PVCs. API, controller, and worker replicas do not mount canonical history/artifact PVCs; workers use the authenticated storage port and alone mount private attempt RWO/RWOP workspaces. AD-31 supplies compare-and-append, fsync, writer epoch, and stale-writer rejection. The packaging baseline requires only qualified RWO storage, not RWX/NAS or S3.

### Installation profile — CLOSED

AD-21 and the operational envelope distinguish the chart-supplied baseline from production prerequisites. The chart supplies controllers, authenticated egress, tenant storage gateways, Services, and storage configuration. Operators provide Kubernetes, qualified RWO CSI, enforcing network/metadata controls, and production/off-cluster identity and ingress inputs as applicable. AC-3 invokes those declared prerequisites and explicitly proves installation without an external database/object store.

### Source anchor — PARTIALLY CLOSED; HIGH REMAINS

The spine frontmatter now correctly anchors `.memlog.md` in the architecture workspace. The remaining mismatch is outside that corrected relative path: canonical `SPEC.md` still protects only AD-1 through AD-32, while AD-33 through AD-35 are now essential to Kubernetes-native operation.

### CAP-22 — CLOSED

AC-17 executes `cpl setup`, `doctor`, `up`, `down`, `restart`, `info`, and `version`; checks accurate diagnostics/version reporting; proves restart preservation; and prevents silent SQLite/filesystem damage. CAP-22 and CAP-13 both point to this evidence.

### Operational completeness — CLOSED

AD-17 scopes the baseline RTO/RPO to Pod, node, and logical-deletion failures while the CSI backend and cluster API backup remain available, fixes snapshot cadence and retention, and moves cluster/storage-backend disaster recovery to an independently protected enhanced profile. Backup epochs, quiescence, restore fencing, CRD lifecycle, controller authority, HA, capacity, observability, and data-safe removal are all specified.

## Critical Findings

None.

## High Findings

### H-1 — Canonical source contract does not preserve AD-33 through AD-35

**Evidence**

- `ARCHITECTURE-SPINE.md:36-40` correctly lists `../SPEC.md` and the architecture-local `.memlog.md`.
- `ARCHITECTURE-SPINE.md:309-325` adds AD-33 through AD-35:
  - AD-33 makes Kubernetes API resources the cluster control-plane model and prevents a hidden database control plane.
  - AD-34 fixes the no-RWX RWO storage-gateway topology.
  - AD-35 fixes installation-bootstrap and tenant-reconciler authority.
- `SPEC.md:120` still states that downstream work must preserve “AD-1 through AD-32 and its acceptance mapping.”

**Why this is high**

The canonical source and normative architecture companion disagree about the protected decision set. A downstream unit can satisfy the explicit canonical preservation clause while omitting precisely the three decisions that close the Kubernetes-native, no-external-state, storage-topology, and controller-authority blockers. That makes the final source chain non-convergent even though the spine itself is internally coherent.

**Required resolution**

Update the canonical preservation clause to protect AD-1 through AD-35, or replace the brittle numeric ceiling with a rule that protects every current stable AD in the normative architecture companion. Add a mechanical check that the highest protected AD equals the spine's highest AD. Do not renumber existing decisions.

## Final Gate

Once H-1 is resolved, the spine passes the BMad good-spine checklist with no remaining critical or high architecture finding. No spine content change is required for storage topology, install profile, CAP-22, operational completeness, or the Kubernetes-native/no-PostgreSQL/no-S3 baseline.
