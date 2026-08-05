---
id: SPEC-codeplane-kubernetes-and-local-daemon
companions:
  - brownfield-constraints.md
  - mode-requirements.md
  - conformance-requirements.md
  - failure-modes.md
  - delivery-slices.md
  - architecture/ARCHITECTURE-SPINE.md
sources:
  - ../../../SPEC.md
  - ../../../README.md
  - ../../../docs/architecture.md
  - ../../../docs/configuration.md
  - ../../../docs/guide.md
  - ../../../docs/quick-start.md
  - ../../../docs/security.md
  - ../../../docs/reference/cli.md
  - ../../../docs/reference/job-states.md
  - ../../../docs/reference/sse-events.md
---

> **Canonical contract.** This SPEC and the files in `companions:` are the complete, preservation-validated contract for what to build, test, and validate. Source documents listed in frontmatter are for traceability only.

# CodePlane Kubernetes-Native and Local-Daemon Deployment Modes

## Why

CodePlane must extend from its local-first single-developer foundation into Kubernetes-native environments without sacrificing the workstation product that existing users rely on; the opportunity is broader team and cluster operation while preserving one coherent control-plane product.

## Capabilities

- **CAP-1** — `common`
  - **intent:** Operators can choose Kubernetes-native or local-daemon deployment as a fully supported product mode
  - **success:** separate clean-install acceptance runs start each mode, expose its documented product surfaces, and complete a managed job while Kubernetes mode has no local-daemon dependency and local mode has no Kubernetes, cloud-account, or hosted-control-plane dependency.
- **CAP-2** — `common`
  - **intent:** Operators receive the same core job, session, state, approval, intervention, review, resolution, artifact, analytics, and audit semantics in both modes
  - **success:** the same lifecycle fixture yields equivalent API-visible states, approvals, interventions, review/resolution outcomes, TraceForge event meaning, artifacts, analytics, and audit provenance in both modes; capability discovery and release evidence enumerate every intentional difference.
- **CAP-3** — `common`
  - **intent:** Operators can register, access, and isolate repositories and job workspaces without agents modifying the primary checkout
  - **success:** concurrent-job tests show each attempt writes only its unique workspace, primary checkouts and other attempts remain byte-for-byte unchanged, and repository publication succeeds only through the declared expected-head/ref conflict path.
- **CAP-4** — `common`
  - **intent:** Operators can select where agent execution occurs relative to the control plane and repository boundary
  - **success:** every admitted attempt exposes its execution locality and bound repository, credential, network, and policy context; admission produces a stable explicit condition and no worker starts when any required boundary is absent or invalid.
- **CAP-5** — `common`
  - **intent:** Job records, canonical events, approvals, transcripts, telemetry, trails, artifacts, and workspace outcomes remain durable according to the selected mode policy
  - **success:** restart, Pod/process loss, supported upgrade, backup/restore, and hash-verification fixtures preserve every class declared durable with its IDs, order, references, and provenance, while every loss or exclusion is represented by an explicit condition rather than success.
- **CAP-6** — `common`
  - **intent:** Operators can configure global, repository, and job behavior and supply secrets without exposing secret values through APIs, events, logs, artifacts, or UI
  - **success:** tests observe defaults < installation < repository < job precedence, the `supervised` default, and zero injected secret values in APIs, events, logs, metrics, traces, UI, exports, artifacts, caches, or terminated workload specifications.
- **CAP-7** — `common`
  - **intent:** Every command, query, approval, and agent action is evaluated against an explicit identity, authorization, and policy context appropriate to the mode
  - **success:** a role-and-resource matrix denies every unauthorized command, query, artifact, terminal, MCP, secret, and approval path; each denial and accepted delegated approval records actor, effective role, scope, policy generation, reason, and target.
- **CAP-8** — `common`
  - **intent:** Operators can define and observe job concurrency, queueing, cancellation, and fairness limits
  - **success:** repeated identical load runs produce the same admission order and stable tie-breaks, never exceed active or queued repository/identity limits, expose queue and cancellation state, and reclaim quota exactly once after terminal cleanup.
- **CAP-9** — `common`
  - **intent:** Clients receive ordered live events and can reconnect to a consistent current state after interruption
  - **success:** disconnect, cursor expiry, replay-window, snapshot, duplicate, out-of-order, compaction, and slow-client fixtures converge clients to the SQLite-authoritative sequence/hash in both modes while preserving the TraceForge envelope and dotted kind and never persisting transport keepalives as domain events.
- **CAP-10** — `common`
  - **intent:** Operators can access CodePlane locally or remotely through an authenticated ingress appropriate to the mode
  - **success:** each documented local or cluster access path serves health, UI, REST, SSE, MCP, and applicable terminal/preview channels through the same authorization policy; unauthenticated probes can reach only explicitly public health or sharing surfaces.
- **CAP-11** — `common`
  - **intent:** Operators can diagnose service, job, agent, repository, storage, and event-stream health using correlated logs, metrics, traces, events, and artifacts
  - **success:** induced job, repository, SQLite, RWX, projection, worker, and egress failures emit correlated health conditions, logs, metrics, traces, events, and audit evidence that identify installation, job/attempt, component, cause class, and operator or automatic recovery action without database inspection.
- **CAP-12** — `common`
  - **intent:** CodePlane detects interrupted work and recovers or terminates it according to documented mode-specific guarantees
  - **success:** process, Pod, node, network, storage, and agent interruption fixtures reach a documented recoverable or terminal condition, reject stale work, and leave no silently running agent or orphaned approval; graceful local restart pauses and resumes the same sessions with reason `server_restart`.
- **CAP-13** — `common`
  - **intent:** Operators can install, upgrade, downgrade where supported, and remove each mode with documented compatibility and data-protection behavior
  - **success:** clean install, N/N-1 upgrade, supported rollback, incompatible-transition, uninstall, and reinstall fixtures preserve compatible configuration and referenced durable data, block before mutation when compatibility fails, and retain CRDs/PVCs unless explicit audited cleanup is requested.
- **CAP-14** — `common`
  - **intent:** Operators can move or interoperate selected repositories, configuration, policy, history, and artifacts between modes without changing shared identifiers or semantics unexpectedly
  - **success:** signed bidirectional export/import verifies hashes and history chains, preserves canonical IDs and declared portable data, remaps adapter-local identities, rebuilds or revalidates caches, keeps imports inert until validation completes, and emits an exhaustive non-portable-item report.
- **CAP-15** — `common`
  - **intent:** Each deployment exposes clear trust, filesystem, network, credential, secret, and agent-execution boundaries
  - **success:** adversarial fixtures deny undeclared filesystem, network, Kubernetes API, repository, credential, and approval access, reject forged or stale mutation identity, find no secret disclosure, and publish the explicit local OS-user and Kubernetes trusted-installation residual-risk statements.
- **CAP-16** — `kubernetes`
  - **intent:** Cluster operators can deploy and operate a Kubernetes-native CodePlane instance using supported Kubernetes packaging and lifecycle procedures
  - **success:** on each supported Kubernetes/Helm combination, a clean OCI-bundle/chart installation passes RWOP/RWX qualification, reports Ready, serves documented surfaces, completes a private-repository managed job, and uses no external database, object store, or storage gateway.
- **CAP-17** — `kubernetes`
  - **intent:** Kubernetes operators can make repositories and isolated workspaces available to agents through a declared access model
  - **success:** public and private repository fixtures acquire and integrity-check the shared mirror, create immutable-attempt workspaces, complete concurrent review and merge/PR/discard resolution with expected-head conflict handling, and reference no undeclared host path.
- **CAP-18** — `kubernetes`
  - **intent:** Kubernetes-native scheduling can place and limit control-plane and agent workloads across cluster resources
  - **success:** concurrent-load fixtures create exactly one direct Pod per accepted attempt, enforce requests/limits/deadlines/quotas, expose pending capacity, fence replacement attempts, and remove Pods, credentials, mounts, Leases, and workspaces in the required cleanup order.
- **CAP-19** — `kubernetes`
  - **intent:** Kubernetes-native durable state and artifacts survive pod replacement and supported upgrades to the declared durability objective
  - **success:** forced control-plane, worker, and builder Pod replacement plus node loss preserves SQLite-authoritative state and every referenced authoritative/durable file, rebuilds projection CRDs and eligible caches, and exposes explicit degradation for any missing or mismatched byte set.
- **CAP-20** — `kubernetes`
  - **intent:** Kubernetes-native identity, tenancy, authorization, and approval delegation support the declared organizational model
  - **success:** installation-binding, OIDC-role, delegation, service-account, worker-token, and network tests deny unauthorized job, repository, artifact, secret, terminal, MCP, and approval access, while operator evidence states that one namespace is one trusted tenant and hostile sibling isolation is not provided.
- **CAP-21** — `kubernetes`
  - **intent:** Kubernetes-native ingress, service health, observability, scaling, and availability integrate with supported cluster operations
  - **success:** readiness, liveness, dependency degradation, rollout, relist/churn, load, latency, restart-window, RTO/RPO, and telemetry demonstrations meet the declared single-replica objectives or report a stable failed condition without changing shared product semantics.
- **CAP-22** — `local-daemon`
  - **intent:** A developer can install CodePlane and use cpl setup, cpl doctor, cpl up, cpl down, cpl restart, cpl info, and cpl version on a workstation
  - **success:** `cpl setup`, `doctor`, `up`, `down`, `restart`, `info`, and `version` pass on a clean workstation; localhost becomes healthy, diagnostics/version are accurate, restart resumes eligible sessions with `server_restart`, and stop/removal does not silently damage local data.
- **CAP-23** — `local-daemon`
  - **intent:** A developer can use local repositories, Git worktrees, locally authenticated agent CLIs, native CLI-session mirroring, local terminals, and existing merge, PR, or discard workflows
  - **success:** managed and native mirrored Copilot/Claude sessions complete against allowlisted local repositories with isolated Git worktrees, local credentials, terminal use, and merge/PR/discard outcomes while no Kubernetes or central CodePlane service is reachable.
- **CAP-24** — `local-daemon`
  - **intent:** A single user can operate with local SQLite data, local artifacts and credentials, optional Dev Tunnel or Cloudflare remote access, and offline or local-first behavior
  - **success:** with external network disabled, local SQLite, artifacts, configuration, approvals, review, diagnostics, replay, and non-network agent fixtures operate successfully; each selected Git, agent, tunnel, OTLP, push, or remote action alone reports its explicit network dependency.

## Constraints

- Local-daemon mode remains a supported product mode, not compatibility, legacy, development-only, or degraded operation.
- Kubernetes-native mode must not redefine CodePlane as Kubernetes-only, cloud-only, or dependent on a vendor-hosted or central CodePlane service.
- Existing local installation, cpl up lifecycle, local repository registration, Git worktree isolation, native CLI-session mirroring, SQLite single-user operation, local credentials, tunnels, and offline/local-first behavior are preserved.
- Shared job states, canonical event meaning, approvals, operator intervention, review and resolution semantics, API contracts, and audit provenance remain consistent unless an intentional mode difference is named and validated.
- The default action-policy preset is `supervised` in both modes unless an operator explicitly selects another supported preset.
- Canonical `SessionEvent.kind` values are open dotted strings such as `job.state_changed`, `permission.requested`, and `session.heartbeat`; persistence and SSE preserve the TraceForge event envelope and dotted kind without legacy snake_case translation.
- Transport-only SSE keepalives are not canonical session heartbeat domain events and must not be persisted, replayed, or interpreted as `session.heartbeat`.
- Graceful CLI shutdown pauses active sessions before process exit, and startup resumes them in place with the canonical restart reason token `server_restart`; restart must not fail every active job.
- The Kubernetes v1 baseline is one trusted tenant per installation namespace with one single-replica control-plane StatefulSet; it is non-HA and does not claim hostile same-installation multi-tenancy.
- SQLite on a private `ReadWriteOncePod` PVC is canonical for product intent, state, history, idempotency, and installation incarnation; authenticated APIs commit SQLite first, while CRD spec/status are bounded projection-only views that reject or revert direct edits.
- One installation-scoped `ReadWriteMany` PVC provides byte custody for lifecycle-classified shared files under canonical installation, repository, job, and cache namespaces. SQLite owns each file set's scope, lifecycle class, writer/readers, behavior, path/hash/provenance reference, publication state, retention/cleanup, backup/rebuild rule, and allowed Pod subPath/access mode. Baseline workers have no Kubernetes API token or RBAC and mount only declared subPaths under explicit write ownership.
- The baseline requires no PostgreSQL, S3, external database, external object store, or storage gateway. RWX storage must pass executable cross-node/Pod fsync, atomic-rename, crash-remount, directory-fsync, and kubelet subPath qualification.
- AD-36 governs all intentionally published derived caches: identity-manifested, checksum-verified files/directories are atomically published under `/cache/<scope>/<identity>`, non-authoritative and rebuildable, read-only to consumers, and garbage-collected through SQLite-state-first, Lease-serialized quarantine/recheck. CodeRecon indexes, build outputs, analysis caches, and generated indexes are representative fixtures, not dedicated infrastructure.
- AD-37 governs durable artifacts and repository shared files: immutable or append-only bytes use atomic/manifest-last publication with SQLite path/hash/provenance references and read-only consumption; mutable singletons use designated-writer ownership, short cross-Pod Lease, immutable candidate generations, SQLite pointer CAS, and conflict preservation. Handoff packages and repository `session-handoff/` records are examples; successor selection/fencing is application-level only where consumed.
- Backup uses a SQLite-enforced publication barrier, removes all non-control RWX read-write mounts, aborts on timeout, captures authoritative shared data and durable artifacts from committed references, treats derived caches as optional/rebuildable, excludes disposable workspaces unless retained as artifacts, captures RWOP/RWX volumes without claiming cross-volume atomicity, excludes etcd CR state, and restores by rotating installation incarnation and rebuilding CR projections from SQLite.
- The kernel states product requirements and observable guarantees; `architecture/ARCHITECTURE-SPINE.md` owns the implementation invariants and operator-choice boundaries that realize them.
- Mode-specific security must preserve least privilege, repository and workspace containment, authenticated mutation, policy enforcement, secret non-disclosure, and auditable approvals.
- Deployment and upgrade procedures must protect durable state and expose incompatibility before destructive changes.
- Repository and agent credentials remain under operator control and are not copied to a central hosted service.
- All source changes, dependencies, BMAD configuration, existing documentation, and artifacts outside this spec folder are out of bounds for this run.
- `brownfield-constraints.md` is normative for preserved local-daemon guarantees and superseded-source traceability.
- `mode-requirements.md` is normative for the common/mode-specific boundary and intentional differences.
- `architecture/ARCHITECTURE-SPINE.md` is the normative architecture companion; downstream work must preserve AD-1 through AD-37 and its acceptance mapping.

## Non-goals

- Re-selecting, weakening, or bypassing AD-1 through AD-37 and their operator-choice boundaries in `architecture/ARCHITECTURE-SPINE.md`.
- Claiming active/active HA, multiple hostile tenants per installation, or a predetermined distributed shared-storage metadata/service design in the v1 baseline; future HA/multi-tenant mechanisms are chosen generically and do not presume dedicated CodeRecon, index, handoff, or artifact-type CRDs/services.
- Deprecating, subordinating, or forcing migration away from local-daemon mode.
- Making CodePlane cloud-only or dependent on a central hosted CodePlane service.
- Changing supported agent providers or redesigning job, event, approval, review, and resolution semantics unrelated to deployment mode.
- Implementing Kubernetes support, modifying source code, or producing an implementation architecture in this specification run.

## Success signal

- A release candidate passes the shared cross-mode conformance suite, a clean Kubernetes deployment completes and recovers a representative managed workflow, and an offline local-daemon installation completes managed and mirrored workflows with no cluster or hosted CodePlane dependency.

## Assumptions

- The current documented local-daemon behavior is the compatibility baseline unless a future source decision explicitly supersedes it.
- Core product semantics can be defined independently from the eventual Kubernetes implementation architecture.
