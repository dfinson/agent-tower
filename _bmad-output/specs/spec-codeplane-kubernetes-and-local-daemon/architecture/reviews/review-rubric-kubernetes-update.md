# BMad Good-Spine Review — Kubernetes-Native Update

**Reviewed artifact:** `../ARCHITECTURE-SPINE.md`  
**Review date:** 2026-08-05  
**Scope:** Architecture-spine rubric only; no spine edits were made.  
**Required baseline:** Kubernetes-native operation with no PostgreSQL, S3, hosted CodePlane, or other external state-service prerequisite.

## Verdict

**NOT READY — strong and unusually complete, but one critical storage-topology decision remains unsafely deferred and four contract gaps prevent the spine from being a fully enforceable Kubernetes-native baseline.**

The spine passes deterministic lint with zero findings, covers every CAP identifier, preserves the local-daemon brownfield model, and explicitly rejects PostgreSQL/S3/external state as prerequisites. It is not yet a good final spine because independently built storage adapters can choose incompatible PVC topologies, the clean-install criterion contradicts the production prerequisites, the RTO/RPO claim has no bounded failure domain, the canonical source chain does not stably include AD-33, and CAP-22 lacks complete acceptance evidence.

## Review Method and Evidence

- Ran the BMad deterministic spine linter against the architecture workspace: **0 findings**.
- Walked every AD for `Binds`, `Prevents`, and enforceable `Rule` semantics.
- Traced CAP-1 through CAP-24 from frontmatter through the capability map and architecture acceptance criteria.
- Compared the spine with its normative `SPEC.md`, `brownfield-constraints.md`, and `mode-requirements.md` sources only to test coverage and compatibility.
- Verified named technology against the repository manifests/locks and current upstream release sources:
  - Kubernetes currently maintains 1.34, 1.35, and 1.36, matching the spine.
  - Helm chart API v2, core `v1` PersistentVolume/PVC, and `snapshot.storage.k8s.io/v1` are current API choices.
  - The repository lock contains FastAPI 0.136.3 and upstream latest is 0.141.1; the spine's `0.115.x` statement is not current repository reality.
  - React 18.3 and Zustand 5 match the brownfield frontend manifest even though React 19.2 is upstream-current; retaining React 18 is compatible brownfield ratification, not a required architecture migration.

## Checklist Result

| Good-spine criterion | Result | Assessment |
| --- | --- | --- |
| Real divergence points covered | **Partial** | The spine binds mode composition, tenancy, identity, execution, Git ownership, consistency, event delivery, scheduling, ingress, packaging, migration, retention, and interoperability. Shared Kubernetes storage access topology is still a real unresolved divergence. |
| Enforceable AD Rules | **Partial** | Most Rules name concrete boundaries and acceptance behavior. Storage access, clean-install prerequisites, and recovery failure domains are not mutually enforceable as written. |
| Nothing unsafe deferred | **Fail** | PVC access modes and filesystem layout are deferred even though the topology requires HA API replicas, workers, and storage maintenance to access durable state. Off-cluster protection is also deferred while an unscoped RPO is claimed. |
| Current named technology | **Partial** | Kubernetes and API names are current. FastAPI `0.115.x` is stale relative to both the lock and upstream. |
| Brownfield compatibility | **Pass** | AD-2, AD-25, AD-27, AD-32, local backup behavior, local-only capability treatment, and the compatibility phases preserve the existing workstation product and explicitly avoid falsely claiming local sandboxing. |
| CAP-1 through CAP-24 coverage | **Partial** | Every CAP is named and mapped. CAP-22 is only mapped to autonomy/restart evidence and does not test the complete preserved CLI lifecycle. CAP-5/CAP-19 are structurally weakened by the unresolved storage topology. |
| Stable parent/source constraints | **Fail** | There is no inherited parent spine conflict, but the source chain points to the parent spec memlog rather than the architecture memlog, and the canonical SPEC protects only AD-1 through AD-32 while this spine adds load-bearing AD-33. |
| Complete operational envelope | **Partial** | Platform range, architecture, images/chart, disconnected install, HA, scale, SLOs, upgrade, rollback, uninstall, observability, security, backup, retention, cancellation, and interoperability are present. Storage access, install qualification, and recovery failure-domain details remain incomplete. |
| No PostgreSQL/S3/external state prerequisite | **Pass, with topology caveat** | AD-10, AD-21, AD-33, AC-3, and Deferred explicitly make CRDs plus CSI-backed PVCs the baseline and external object storage optional. The unresolved PVC topology may nevertheless force an undeclared RWX/NAS-style infrastructure requirement on some clusters. |

## Actionable Findings

### R1 — CRITICAL — Shared PVC access topology is a real divergence point unsafely deferred

**Evidence**

- AD-10 makes a CSI-backed PVC implementation the required Kubernetes storage adapter and assigns it artifacts, transcripts, exports, Git bundles, retained outcomes, and canonical history (`ARCHITECTURE-SPINE.md:171-175`).
- The topology has API replicas and workers accessing the storage port (`319-328`, `343-357`), while the operational envelope requires at least two API/controller replicas across failure domains (`403`).
- Deferred explicitly leaves PVC access modes and filesystem layout to adapter implementations (`572`).
- The baseline prerequisite says only a “compatible” StorageClass, without defining whether compatibility means RWO, RWOP, RWX, one PVC per resource, or a chart-managed storage service (`399-402`).

**Why this violates the rubric**

Two teams can build mutually incompatible adapters: one can assume a shared RWX filesystem mounted by all API and worker Pods, while another can allocate RWO volumes per attempt and route bytes through a single owner. A normal default RWO StorageClass cannot support the diagram's apparent multi-node, multi-replica direct mounts. This changes scheduling, failure recovery, fencing, checksum ownership, backup quiescence, security, and whether the advertised “only a StorageClass” baseline works at all.

**Required action**

Bind one baseline storage topology and its mount/ownership rules. For example:

1. define separate private attempt/workspace PVCs and a chart-managed storage owner/service over CSI-backed PVCs, with API/workers transferring bytes through the authenticated storage port; **or**
2. explicitly require and qualify RWX, define writer serialization and tenant path isolation, and admit that RWX is a baseline StorageClass capability.

State which components mount each PVC, supported access modes/topologies, writer authority, failover/fencing, and backup quiescence. Keep PostgreSQL, S3, and external object stores optional.

### R2 — HIGH — The clean-install acceptance criterion contradicts the declared Kubernetes prerequisites

**Evidence**

- AD-21 says the baseline needs a Kubernetes API, compatible StorageClass, cluster identity/ingress prerequisites, and a qualified egress boundary (`237-241`).
- The operational envelope additionally requires OIDC, ingress/gateway, DNS, TLS, an authenticated job-policy egress gateway, NetworkPolicy enforcement, and metadata protection (`397-402`).
- AC-3 says a clean Helm install “with only a conforming StorageClass” completes a private-repository job (`511`).
- AD-7 requires all external worker egress to pass through the authenticated job-policy gateway (`153-157`), which is indispensable for a private repository or networked agent.

**Why this violates the rubric**

AC-3 cannot be executed literally on the production baseline. A conforming StorageClass alone cannot supply identity, TLS ingress, private-repository credentials, or the mandatory egress policy boundary. Implementers can either weaken AD-7/AD-21 to pass AC-3 or fail the claimed clean-install gate.

**Required action**

Define two explicit profiles:

- a cluster-internal installation smoke profile with exact chart-provided/bootstrap components and no production claim; and
- a production qualification profile listing every operator prerequisite.

State whether the chart installs the stateless authenticated egress gateway or requires one, and make AC-3 invoke the correct profile. Neither profile should require PostgreSQL, S3, or another external state service.

### R3 — HIGH — RTO/RPO is claimed without a failure domain that the baseline backup can survive

**Evidence**

- AD-17 promises a 60-minute RTO and five-minute RPO using Kubernetes resource backups and storage-port snapshots (`213-217`).
- The fallback backup is a filesystem snapshot/copy to “separate operator-protected PVC capacity” (`434-441`).
- CSI implementation, replication, encryption, and off-cluster copy policy are left to the operator (`441`).
- No backup cadence, snapshot retention minimum, independent failure domain, or loss scenario bounds the RTO/RPO claim.

**Why this violates the rubric**

A VolumeSnapshot or second PVC on the same CSI backend does not survive backend or cluster loss. With off-cluster/independent protection deferred, two conforming operators can interpret the same RPO against radically different failure sets. The guarantee is therefore not enforceable, and recovery may be unsafe if downstream work assumes cluster-loss protection.

**Required action**

Scope the baseline RTO/RPO to named failure domains that CRD export plus same-cluster CSI protection can actually survive (for example Pod, node, and accidental logical deletion where the storage backend remains available). Define cadence and retention. Treat full cluster/storage-backend disaster recovery as a separately qualified operator profile with an independent copy target. This preserves the no-external-state baseline without making a false disaster-recovery promise.

### R4 — HIGH — Stable source constraints do not reliably preserve load-bearing AD-33

**Evidence**

- Spine frontmatter references `../.memlog.md` (`36-40`), while the architecture workspace has its own `.memlog.md`; the relative reference resolves to the spec-level memlog rather than the architecture decision log.
- The normative SPEC says downstream work must preserve “AD-1 through AD-32.”
- The spine contains AD-33, which establishes CRDs as the Kubernetes control-plane model and prevents a hidden database control plane (`309-313`).

**Why this violates the rubric**

An update resumed from the frontmatter source can use the wrong decision memory, and a downstream implementer can comply with the canonical SPEC while omitting AD-33. That specifically weakens the Kubernetes-native/no-external-state contract.

**Required action**

Correct the architecture memlog source anchor and update the canonical source constraint to preserve AD-1 through AD-33. Add a mechanical check that the highest protected AD in the source contract equals the highest AD in the spine, without renumbering existing IDs.

### R5 — HIGH — CAP-22's preserved local CLI lifecycle is mapped but not completely accepted

**Evidence**

- CAP-22 requires `cpl setup`, `doctor`, `up`, `down`, `restart`, `info`, and `version`.
- The capability map governs CAP-22 with only AD-2 and AC-9 (`551`).
- AD-2 establishes local autonomy but does not bind those commands (`115-119`).
- AC-2 covers offline installation/jobs (`510`), and AC-9 covers restart behavior (`517`); no architecture acceptance criterion covers the other lifecycle commands or removal/data-preservation behavior.

**Why this violates the rubric**

The matrix gives the appearance of CAP-1 through CAP-24 completeness, but an implementation can remove or change `doctor`, `down`, `info`, or `version` and still pass every architecture AC. This is also a brownfield compatibility gap.

**Required action**

Add one local lifecycle acceptance criterion that exercises all CAP-22 commands, verifies diagnostics and reported version/compatibility, and proves stop/restart/removal behavior does not silently damage SQLite or filesystem state. Map CAP-22 and CAP-13 to it.

### R6 — MEDIUM — The FastAPI technology row is neither current nor the repository's locked baseline

**Evidence**

- The Stack table names FastAPI `0.115.x` and says the repository already binds the listed stack (`379-395`).
- `pyproject.toml` permits `fastapi>=0.115,<1`.
- `uv.lock` resolves FastAPI 0.136.3.
- The upstream current release at review time is 0.141.1.

**Why this violates the rubric**

The row presents a stale patch line as a bound brownfield technology. Implementers can unnecessarily downgrade to satisfy the spine or ignore the stack table, weakening its authority.

**Required action**

Either name the actual reproducible lock baseline (0.136.3 at this revision) or record the repository's supported range (`>=0.115,<1`) and make `uv.lock` the patch-level authority. Do not imply that `0.115.x` is current.

## CAP-1 Through CAP-24 Trace

| CAP | Spine coverage | Result |
| --- | --- | --- |
| CAP-1 | AD-1, AD-2, AD-21, AD-26; AC-1/2/3 | Covered |
| CAP-2 | AD-1, AD-11, AD-27, AD-28, AD-31; AC-1/16 | Covered |
| CAP-3 | AD-8, AD-9, AD-24; AC-4 | Covered |
| CAP-4 | AD-3, AD-7, AD-29; locality recorded and mode choices explicit | Covered |
| CAP-5 | AD-10/11/16/31/33; AC-6/12 | **Conditional on R1** |
| CAP-6 | AD-9, AD-20, configuration conventions; AC-11 | Covered |
| CAP-7 | AD-4/5/6/29/30/33; AC-5 | Covered |
| CAP-8 | AD-13/14/15/33; AC-8/10 | Covered |
| CAP-9 | AD-11/12/31/33; AC-7 | Covered |
| CAP-10 | AD-5, AD-19, AD-25; AC-16 | Covered |
| CAP-11 | AD-15/17/18/31; AC-15 | Covered |
| CAP-12 | AD-13/14/29/33; AC-6/9/10 | Covered |
| CAP-13 | AD-21/22/26/33; AC-3/13 | Covered; local lifecycle evidence should also use R5's criterion |
| CAP-14 | AD-23/24/31; AC-14 | Covered |
| CAP-15 | AD-3 through AD-9, AD-19/20/29-32; AC-4/5/11 | Covered |
| CAP-16 | AD-21/22/33; AC-3/13 | Covered, subject to R2 |
| CAP-17 | AD-8/9; AC-3/4 | Covered |
| CAP-18 | AD-7, AD-13-15, AD-29/33; AC-8/10/15 | Covered |
| CAP-19 | AD-10/16/17/22/31/33; AC-3/12/13 | **Conditional on R1 and R3** |
| CAP-20 | AD-4-6, AD-29/30/33; AC-5 | Covered |
| CAP-21 | AD-15, AD-17-22, AD-33; AC-3/7/13/15 | Covered, subject to R2/R3 |
| CAP-22 | AD-2, AC-9 | **Incomplete acceptance; R5** |
| CAP-23 | AD-2/8/25/32; AC-2/4/16 | Covered |
| CAP-24 | AD-2/10/25/32; AC-2/12/16 | Covered |

## Positive Findings

- The spine is a real consistency contract rather than a component inventory: its ADs bind ownership, mutation, fencing, trust, and cross-mode semantics.
- AD-21 and AD-33 directly satisfy the user's central product constraint: no PostgreSQL, S3, hosted CodePlane, or hidden database control plane is required.
- AD-11 through AD-14 and AD-29 through AD-31 form a coherent distributed-consistency and worker-authentication model with explicit stale-writer rejection and visible saga failure.
- AD-32 honestly preserves the brownfield OS-user trust boundary instead of overclaiming local sandboxing.
- The intentional-difference table prevents Kubernetes work from silently deleting native mirroring, PTY, tunnel, preview, push, or offline semantics.
- Upgrade, rollback, uninstall preservation, disconnected distribution, capacity, SLO, observability, retention, backup/restore flow, and interoperability are all present; the operational envelope needs correction, not wholesale invention.

## Final Gate

The spine should not be handed to independent Kubernetes implementation units until **R1-R5** are resolved. R1 is the release-blocking architecture decision. R2-R4 are contract-coherence blockers. R5 closes the only clear CAP acceptance hole. R6 should be corrected in the same update so the technology table is authoritative.

