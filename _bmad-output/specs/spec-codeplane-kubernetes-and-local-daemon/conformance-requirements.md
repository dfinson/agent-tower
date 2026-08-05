# Conformance Requirements

This companion is normative. `MUST`, `MUST NOT`, `SHOULD`, `SHOULD NOT`, and `MAY` have their RFC 2119 meanings. Rationale remains in `architecture/ARCHITECTURE-SPINE.md`; this file defines observable obligations and evidence.

Verification methods are closed: `unit` isolates one contract, `integration` crosses in-process/component boundaries, `conformance` runs the same normative behavior against a supported mode/profile, `chaos` injects interruption or corruption at named boundaries, and `operator inspection` verifies rendered configuration or published operational evidence.

## Product Semantics and Local Preservation

| ID | Normative statement | Governing CAPs | Governing ADs | Verification method | Required evidence |
|---|---|---|---|---|---|
| REQ-1 | Kubernetes-native and local-daemon MUST be independently installable, supported product modes; neither mode may require the other or a hosted CodePlane service. | CAP-1, CAP-16, CAP-22, CAP-24 | AD-1, AD-2, AD-21 | conformance | Two clean-install logs and completed managed-job records with prohibited dependencies unreachable. |
| REQ-2 | Both modes MUST expose equivalent job state, session, approval, intervention, cancellation, review, resolution, artifact, analytics, audit, API, and TraceForge semantics. Every difference MUST be returned by capability discovery, documented, and asserted rather than skipped. | CAP-2, CAP-9, CAP-14 | AD-1, AD-25, AD-27, AD-28 | conformance | One shared fixture's normalized API/event/audit transcript from each mode plus an intentional-difference manifest. |
| REQ-3 | Local-daemon MUST preserve `cpl setup`, `doctor`, `up`, `down`, `restart`, `info`, and `version`; MUST default policy to `supervised`; graceful shutdown MUST pause eligible active sessions and startup MUST resume them in place with reason `server_restart`. | CAP-6, CAP-12, CAP-22 | AD-2, AD-14, AD-27 | integration | CLI transcript, before/after session IDs and states, policy snapshot, and canonical restart event containing `server_restart`. |
| REQ-4 | Local-daemon MUST run FastAPI, local SQLite, local artifacts, local Git worktrees, local credentials, and the in-process event bus without Kubernetes, cloud account, or central service; offline workflows MUST fail only at an explicitly selected external operation. | CAP-1, CAP-5, CAP-24 | AD-2, AD-32 | conformance | Network-denied end-to-end run and dependency inventory showing only the selected Git/agent/tunnel/export operation requested network. |
| REQ-5 | Local-daemon MUST preserve allowlisted repositories, isolated worktrees, locally authenticated Copilot/Claude adapters, native CLI-session mirroring, local terminals, and merge/PR/discard workflows. | CAP-3, CAP-23 | AD-2, AD-8, AD-24, AD-25 | conformance | Managed and mirrored session records, worktree paths, protected-checkout hashes, and all three resolution outcomes. |
| REQ-6 | Canonical events in both modes MUST retain the TraceForge envelope, immutable event ID, per-job order/hash, and open dotted `kind`; transport keepalives MUST NOT be persisted or replayed as `session.heartbeat`, and legacy snake_case translation MUST NOT occur. | CAP-2, CAP-9 | AD-11, AD-12, AD-31 | integration | Persisted rows, SSE frames, replay output, and schema assertions across dotted unknown kinds and keepalives. |
| REQ-7 | Local-daemon MUST state that the logged-in OS user is its trust boundary and MUST NOT claim sandboxing against malicious agent code; work directories, path allowlists, scoped credential injection, redaction, and process cleanup MUST still be enforced. | CAP-15, CAP-23, CAP-24 | AD-9, AD-32 | operator inspection | Published threat statement and adversarial fixture results for path, credential, redaction, and child-process cleanup. |
| REQ-8 | Native CLI mirroring, workstation PTYs, local voice transcription, Dev Tunnel, Cloudflare tunnel, and localhost preview MUST remain local-only in v1; Kubernetes MUST expose the analogues fixed by AD-25 and MUST report unsupported parity explicitly. | CAP-2, CAP-10, CAP-23, CAP-24 | AD-25 | conformance | Capability-discovery payload and release matrix matching the local/Kubernetes analogue table. |
| REQ-59 | Configuration resolution MUST apply strict precedence `defaults < installation < repository < job` in both modes for non-secret behavior, with `supervised` at the defaults tier; higher tiers MUST override lower tiers deterministically and the effective value and source tier MUST be observable per key. | CAP-6, CAP-24 | AD-27 | integration | Layered-configuration fixture asserting effective value and source tier at all four levels, plus `supervised` when unset. |

## Kubernetes Authority and Projections

| ID | Normative statement | Governing CAPs | Governing ADs | Verification method | Required evidence |
|---|---|---|---|---|---|
| REQ-9 | A Kubernetes v1 installation MUST equal one namespace, one trusted tenant, and one single-replica control-plane StatefulSet; the baseline MUST be explicitly non-HA and MUST NOT claim hostile same-installation multi-tenancy. | CAP-7, CAP-16, CAP-20, CAP-21 | AD-4, AD-30, AD-35 | operator inspection | Rendered workload cardinality, namespace binding, readiness output, and published trust/availability statement. |
| REQ-10 | The control-plane StatefulSet MUST own API, orchestration, controllers, scheduling, reconciliation, and canonical persistence; Kubernetes control components MUST NOT execute agent tools. | CAP-4, CAP-16, CAP-18 | AD-3, AD-35 | integration | Process/workload inventory and a job trace showing tool execution only in the accepted attempt Pod. |
| REQ-11 | SQLite on a private RWOP PVC mounted only by the control-plane Pod MUST be the sole authority for product intent, state, history, idempotency, audit, installation incarnation, and shared-file catalog/publication state. | CAP-5, CAP-9, CAP-19 | AD-10, AD-11, AD-31, AD-34 | conformance | Mount graph, SQLite transaction evidence, and fault-injection results proving no second writer or peer catalog. |
| REQ-12 | The v1 CRD inventory MUST be exactly `CodePlaneJob`, `CodePlaneExecutionAttempt`, `CodePlaneApproval`, `CodePlaneRepositoryBinding`, `CodePlaneBackupEpoch`, and `CodePlaneImportSession`; no feature-specific cache, index, handoff, artifact, tenant, or storage CRD MAY be added to the baseline. | CAP-5, CAP-16, CAP-19 | AD-33, AD-35, AD-36, AD-37 | operator inspection | Installed CRD inventory and schema bundle diff against the six-kind allowlist. |
| REQ-13 | Every CodePlane CRD spec/status MUST be a bounded, namespaced projection of committed SQLite state. Kubernetes Events/status arrays MUST NOT be canonical history, and CRDs MUST NOT contain shared-file paths, hashes, provenance, retention, or publication state. | CAP-5, CAP-9, CAP-19 | AD-11, AD-12, AD-33 | conformance | CRD schema inspection, size/field assertions, and projection-to-SQLite sequence/hash comparison. |
| REQ-14 | Authenticated product APIs MUST commit SQLite before projection. Direct CRD edits MUST be rejected or reverted, MUST NOT create product intent, and MUST emit an observable projection condition and audit record. | CAP-7, CAP-12, CAP-20 | AD-11, AD-33 | integration | Direct-edit fixture showing unchanged SQLite intent, reverted CRD, generation-matched condition, and audit entry. |
| REQ-15 | Projection reconciliation MUST use stable field ownership, resourceVersion preconditions, initial list/watch, 410/relist recovery, orphan adoption, and installation-incarnation plus sequence/hash convergence. | CAP-9, CAP-12, CAP-21 | AD-12, AD-33 | chaos | Watch interruption/relist transcript and final CRD/SQLite convergence proof without event-history gaps. |

## Shared Files, Repositories, and Publication

| ID | Normative statement | Governing CAPs | Governing ADs | Verification method | Required evidence |
|---|---|---|---|---|---|
| REQ-16 | Kubernetes MUST use one installation-scoped RWX PVC for byte custody under only `/installation/shared`, `/repos/<repo-id>/mirror.git`, `/repos/<repo-id>/workspaces/<attempt-uid>`, `/repos/<repo-id>/shared`, `/jobs/<job-id>/artifacts`, `/jobs/<job-id>/sessions`, and `/cache/<scope>/<identity>`; top-level `/sessions` and `/indexes` MUST NOT exist. | CAP-5, CAP-17, CAP-19 | AD-34 | conformance | Volume tree inventory and negative path assertions after representative workflows. |
| REQ-17 | `SharedFileStoragePort` MUST be the only generic operation boundary for shared bytes and MUST enforce SQLite-authorized publication, reference, mount, retention, and deletion; it MUST NOT become a peer catalog or feature-specific policy service. | CAP-5, CAP-14 | AD-10, AD-27, AD-34 | unit | Port contract tests and dependency graph showing application policy outside the adapter and no second catalog. |
| REQ-18 | Every shared file set MUST have one SQLite classification containing scope, lifecycle class, writer role, reader roles, behavior, relative path and hash/reference/provenance, publication protocol/state, retention/cleanup rule, backup/rebuild rule, and allowed `subPath` with access mode; incomplete classification MUST block publication and mount grants. | CAP-5, CAP-15, CAP-19 | AD-10, AD-30, AD-34 | conformance | Classification records for every fixture and field-by-field negative tests that produce stable rejection codes. |
| REQ-19 | The lifecycle class MUST be exactly one of `authoritative shared data`, `durable artifact`, `derived cache`, or `disposable workspace`; class transitions MUST be explicit SQLite operations and MUST preserve prior provenance and retention evidence. | CAP-5, CAP-14, CAP-19 | AD-10, AD-16 | unit | Enum/schema tests and transition ledger showing source class, target class, actor, reason, and references. |
| REQ-20 | Authoritative shared data MUST publish a new immutable content-addressed generation, fsync and verify it, then CAS-switch the SQLite logical pointer; readers MUST resolve only the committed pointer and conflicts MUST remain addressable. | CAP-5, CAP-12, CAP-19 | AD-10, AD-31, AD-34, AD-37 | chaos | Crash-boundary matrix around fsync/rename/CAS with pointer-to-hash verification and preserved losing generations. |
| REQ-21 | Durable artifacts MUST be immutable or append-only, stage outside the final path, fsync files, atomically rename, fsync the parent directory, and commit SQLite path/hash/provenance only afterward; multipart artifacts MUST publish their manifest last. | CAP-5, CAP-9, CAP-14 | AD-10, AD-31, AD-37 | chaos | Publication trace at each interruption point and post-recovery evidence that no partial artifact is readable. |
| REQ-22 | A mutable-singleton shared file MUST have one designated writer; cross-Pod publication MUST use a short path-scoped Lease, immutable candidate generations, fsync/verification, and SQLite pointer CAS, and MUST preserve conflicts rather than overwrite bytes behind a committed reference. | CAP-5, CAP-12, CAP-23 | AD-10, AD-30, AD-37 | conformance | Concurrent-writer results showing one committed generation, explicit conflict candidates, and stable reader resolution. |
| REQ-23 | A derived cache MUST be non-authoritative, identity-manifested, checksum-verified, atomically published by one designated builder under an identity Lease, mounted read-only to consumers, and deterministically rebuilt or bypassed under declared policy when absent, stale, corrupt, or incompatible. | CAP-3, CAP-11, CAP-17 | AD-16, AD-34, AD-36 | conformance | CodeRecon/build/analysis fixtures covering reuse, invalidation, interrupted build, corruption, read-only use, and rebuild/bypass. |
| REQ-24 | Cache GC MUST CAS SQLite from `ready` to `deleting`, deny new references/mounts, verify no reference/hold/current-or-pending mount under the same Lease, quarantine by atomic rename, recheck, and either delete or restore; interrupted phases MUST be restart-adoptable and identity reuse MUST remain blocked. | CAP-5, CAP-12, CAP-19 | AD-14, AD-16, AD-36 | chaos | GC phase ledger and crash/restart/concurrent-reference fixtures proving no referenced generation is deleted. |
| REQ-25 | A disposable workspace MUST use an immutable attempt UID, be writable only by its worker, never be reused, remain outside backup/export, and be deleted only after required outcome/artifact publication and reference/hold rechecks unless explicitly reclassified as a durable artifact. | CAP-3, CAP-12, CAP-17 | AD-8, AD-14, AD-16, AD-34 | integration | Mount matrix, workspace identity history, deletion ordering, and retained-workspace reclassification record. |
| REQ-26 | The shared bare mirror MUST live at `/repos/<repo-id>/mirror.git`; only the RWOP-bound repository-acquisition adapter may mutate it, while workers/builders mount it read-only. The Git protocol MUST use lock files, object fsync before ref publication, expected-head/ref CAS, `git fsck`, active-reference-aware maintenance, and quarantine/reacquisition after interruption or corruption. | CAP-3, CAP-17, CAP-23 | AD-8, AD-24 | chaos | Mount graph and injected Git mutation failures showing no exposed corrupt ref and successful quarantine/revalidation. |
| REQ-27 | Each Kubernetes attempt MUST materialize a private workspace at `/repos/<repo-id>/workspaces/<attempt-uid>` from a verified mirror/ref and MUST NOT accept a local absolute repository path. | CAP-3, CAP-17 | AD-8, AD-34 | integration | Workspace creation trace, source ref/object checkpoint, unique mount path, and local-path rejection. |
| REQ-28 | Before remote ref mutation, a recovery Git bundle MUST be durably published and retained until resolution success/failure is committed; merge, PR, push, and discard MUST use expected-head/ref conflict detection, and independent local/Kubernetes instances MUST NOT claim coordinated live ownership. | CAP-3, CAP-14, CAP-17, CAP-23 | AD-8, AD-24, AD-37 | conformance | Recovery-bundle hash/reference, resolution ledger, forced ref conflict, and documented ownership assignment. |
| REQ-29 | Staged, orphaned, temporary, quarantine, and conflict bytes MUST never be reported as published success. Cleanup MUST recheck SQLite references, holds, publication state, and current/pending mounts before deletion and MUST expose blocked cleanup. | CAP-5, CAP-11, CAP-12 | AD-14, AD-16, AD-36, AD-37 | chaos | Orphan sweep inventory, retained/deleted decisions, blocked condition, and restart-adopted cleanup ledger. |

## Worker Execution, Security, and Scheduling

| ID | Normative statement | Governing CAPs | Governing ADs | Verification method | Required evidence |
|---|---|---|---|---|---|
| REQ-30 | Kubernetes MUST create exactly one directly owned Pod with `restartPolicy: Never` per execution attempt; Pod names/templates MUST be deterministic and immutable, and Pod loss MUST terminate that attempt before a new claim generation and attempt are minted. | CAP-4, CAP-12, CAP-18 | AD-3, AD-13 | chaos | Claim/Attempt/Pod ownership timeline across create retries, Pod loss, and replacement with one accepted Pod UID. |
| REQ-31 | The only execution fence MUST be `attemptFence = (installation incarnation, monotonic claim generation, attempt UID)`; it MUST NOT be treated as a credential or supplemented by another epoch. Every callback, credential renewal, history append, and file/publication commit MUST transactionally compare it with current SQLite state. | CAP-7, CAP-12, CAP-18 | AD-3, AD-13, AD-29, AD-31 | conformance | Wire/schema assertion and stale/prior-incarnation callback matrix showing no state, event, or file commit. |
| REQ-32 | A worker credential MUST be short-lived, renewable, and issued only after live verification of installation/namespace, service account, direct ownership, accepted Pod UID, protocol, and fence; workers MUST authenticate the stable control Service identity and rotation MUST preserve valid attempts. | CAP-7, CAP-15, CAP-20 | AD-6, AD-29 | integration | Credential issuance/renewal trace, forged identity denials, and trust-anchor rotation during an attempt. |
| REQ-33 | Baseline workers MUST set `automountServiceAccountToken: false`, receive no Kubernetes API credential or RBAC, run non-root from immutable image digests with read-only root filesystem, dropped capabilities, `RuntimeDefault` seccomp, no privilege escalation/host access, and only declared `subPath` mounts. | CAP-15, CAP-18, CAP-20 | AD-6, AD-7, AD-30 | conformance | Rendered Pod security context, token/RBAC probes, mount inventory, and forbidden host/API access results. |
| REQ-34 | Each worker MUST have requests, limits, ephemeral-storage limit, active deadline, default-deny networking, and declared credential/egress scope. Undeclared destinations, node/cluster metadata, link-local, private control networks, and unrelated credentials MUST be denied. | CAP-4, CAP-15, CAP-18 | AD-7, AD-9 | conformance | Pod resources, NetworkPolicy/gateway decisions, destination probes, and credential-scope matrix. |
| REQ-35 | Egress gateway unavailability, DNS/control dependency loss, and policy denial MUST be distinct. Unavailability MUST set `EgressUnavailable`, pause admission, park in-flight attempts without freeing active quota or consuming retry budget, and resume safely; policy denial MUST be audited and terminal/reviewable under policy. | CAP-11, CAP-12, CAP-18 | AD-7, AD-13, AD-18 | chaos | Gateway/DNS/policy fault matrix with conditions, quota/retry counters, resume result, and denial audit. |
| REQ-36 | Secret values MUST be just-in-time, least-privilege, read-only memory-backed files and MUST never enter configuration values, URLs, APIs, events, logs, metrics, traces, UI, exports, artifacts, caches, or durable Pod specs. Rotation MUST bind new attempts to the new version and explicitly complete or restart active attempts. | CAP-6, CAP-15, CAP-20 | AD-9, AD-20 | conformance | Secret canary scan across all surfaces and active/new-attempt rotation records. |
| REQ-37 | Human OIDC roles and CodePlane authorization MUST be distinct from Kubernetes workload RBAC; authorization MUST deny by default and revalidate delegation scope, version, expiry, and revocation in the same SQLite transaction as approval commit. Agents/service identities MUST NOT self-approve. | CAP-7, CAP-20 | AD-5, AD-6, AD-35 | integration | Role matrix, revoked-at-commit race fixture, self-approval denial, and immutable audit rows. |
| REQ-38 | Admission MUST provide deterministic weighted share with aging, stable tie-breaking, and per-repository/per-identity queued and active quotas; queue position MUST NOT be persisted, and cancellation/recovery MUST release capacity exactly once. | CAP-8, CAP-18 | AD-13, AD-15 | conformance | Repeated-load order comparison, quota time series, starvation bound, and capacity reconciliation. |
| REQ-39 | Security documentation MUST state that Kubernetes improves process, API, network, credential, and mount containment over local mode but one namespace remains one trusted tenant; `subPath` is not a hostile storage boundary and cluster/storage administrators, kernel/container escape, compromised shared storage, allowed provider egress, and declared shared surfaces remain residual risks. | CAP-15, CAP-20 | AD-4, AD-7, AD-30, AD-32 | operator inspection | Released threat model containing the comparison, trust assumptions, controls, and residual-risk list. |

## State, Streaming, Recovery, and Operations

| ID | Normative statement | Governing CAPs | Governing ADs | Verification method | Required evidence |
|---|---|---|---|---|---|
| REQ-40 | Each authoritative mutation MUST commit state, TraceForge history, per-job sequence/hash, idempotency claim/digest, audit, and operation ledger atomically in SQLite; a retry with different actor, policy generation, incarnation, targets, expected versions, or fence MUST fail rather than return prior success. | CAP-5, CAP-7, CAP-9 | AD-11, AD-31 | chaos | Transaction fault matrix and idempotency replay results with original result or stable mismatch/window-expired error. |
| REQ-41 | History delivery MUST be at least once with per-job ordering. Cursors MUST be opaque, authenticated, scope/incarnation/sequence/hash bound; slow clients MUST disconnect to replay, replay/retention misses MUST be explicit, and prior-incarnation cursors MUST fail without existence disclosure. | CAP-9, CAP-14 | AD-12, AD-31 | conformance | Disconnect/duplicate/compaction/expiry/slow-client traces and snapshot convergence proof. |
| REQ-42 | Cancellation MUST first durably commit intent, then stop/checkpoint work, publish or explicitly fail required outputs, commit terminal outcome/references/tombstone, revoke credentials, release Leases, finalize retained files, quarantine/delete workspace, and delete the Pod; every phase MUST be idempotent and externally observable. | CAP-8, CAP-12, CAP-18 | AD-14 | chaos | Phase-by-phase cancellation fixtures during clone, execution, approval, publication, and resolution. |
| REQ-43 | Finalizers MUST each have one owner, bounded retries, and N/N-1 adoption. Force-finalize MUST require a retention-safe tombstone and break-glass audit; storage or namespace-deletion blockage MUST expose degraded inventory and MUST NOT claim complete cleanup. | CAP-11, CAP-12, CAP-13 | AD-14, AD-22, AD-33 | chaos | Stuck-finalizer fixture, owner/retry telemetry, break-glass audit, and preserved degraded inventory. |
| REQ-44 | Class-specific retention and legal holds MUST be evaluated before deletion. Defaults are 365 days for canonical history and audit, 90 days for transcripts and telemetry, 30 days for durable artifacts and retained workspace outcomes, and seven idle days for derived caches; policy MAY change them only within AD-16 bounds. Deletion MUST tombstone, quarantine, and recheck references, holds, and mounts, and a new reference/hold MUST cancel deletion. | CAP-5, CAP-11, CAP-19 | AD-16 | integration | Retention-policy snapshot and time/race fixtures showing hold precedence, cancellation, and audit checkpoint retention. |
| REQ-45 | Logs, metrics, OTLP traces, canonical events, conditions, and immutable audit MUST correlate installation, request, job, session, event, and execution identities without high-cardinality Prometheus labels or secret/raw-terminal content. Health MUST distinguish liveness, readiness, and dependency degradation. | CAP-7, CAP-11, CAP-21 | AD-18 | conformance | Telemetry bundle for induced failures, label-cardinality checks, redaction scan, and health state transitions. |
| REQ-46 | Kubernetes ingress MUST use one authenticated control service with TLS off-cluster and common authorization for UI, REST, SSE, MCP, terminal, and preview. Preview/server fetches MUST be disabled by default and deny loopback, private/link-local/metadata/cluster/control ranges after DNS resolution and redirects. | CAP-10, CAP-15, CAP-21 | AD-19 | conformance | Protocol matrix, TLS/auth results, proxy buffering test, and SSRF/DNS-rebinding/redirect denial fixtures. |
| REQ-47 | The release gate MUST test the AD-15 one-replica scale envelope and AD-17 latency, restart-window, RTO, and RPO objectives. Failure MUST block the corresponding support claim; results MUST NOT be represented as HA. | CAP-8, CAP-9, CAP-21 | AD-15, AD-17, AD-28 | conformance | Load/SLO report with environment, percentile data, queue/relist budgets, restart and recovery timestamps. |

## Backup, Portability, Packaging, and Evolution

| ID | Normative statement | Governing CAPs | Governing ADs | Verification method | Required evidence |
|---|---|---|---|---|---|
| REQ-48 | Backup MUST establish a SQLite publication barrier, reject new scheduling/publication, drain or durably park operations, revoke publication grants, stop/delete builders and workers, and verify through Kubernetes that no non-control Pod retains an RWX read-write mount. Timeout MUST abort without advancing last-known-good and MUST resume safely. | CAP-12, CAP-19 | AD-14, AD-34 | chaos | Backup phase ledger, mount inventory, timeout fixture, `Failed` condition, unchanged last-known-good, and resume trace. |
| REQ-49 | After quiescence, backup MUST freeze committed authoritative/durable references, checkpoint/fsync SQLite and included bytes, capture RWOP and RWX separately, and bind them in one checksummed manifest. It MUST NOT claim cross-volume atomicity; partial capture, drift, or missing bytes MUST reject verification. | CAP-5, CAP-19 | AD-10, AD-17, AD-31, AD-34, AD-37 | chaos | Two-volume manifest, hashes/checkpoint root, partial-capture injection, and rejected verification record. |
| REQ-50 | Backup MUST include authoritative shared data and durable artifacts, MAY omit rebuildable derived caches, and MUST exclude disposable workspaces unless reclassified as durable artifacts; etcd/CRD projection state MUST be excluded. | CAP-5, CAP-14, CAP-19 | AD-16, AD-33, AD-36, AD-37 | conformance | Backup inventory categorized by lifecycle class and negative assertions for workspaces and CRD state. |
| REQ-51 | Restore MUST verify both captures, manifest, history chains, and included hashes; rotate and durably commit a new installation incarnation; clear publication Leases; invalidate old workers, credentials, Pod names, fences, and cursors; rebuild all six CRD projections from SQLite; and keep scheduling disabled until referenced data and parked operations verify or become explicit degraded conditions. | CAP-9, CAP-12, CAP-19 | AD-12, AD-13, AD-31, AD-33, AD-34 | chaos | Restore transcript, old-identity rejection matrix, rebuilt projection comparison, and activation/degradation conditions. |
| REQ-52 | Export MUST use a signed, checksummed, versioned manifest and include selected authoritative data/durable artifacts, canonical IDs, JSONL TraceForge history/chains, policy/config without secrets, repository bindings, and optional Git bundles. Import MUST verify trust before mutation, remain inert until complete validation, preserve IDs/hashes/provenance, remap adapter-local identities, and make collisions idempotent only for matching canonical hashes. | CAP-5, CAP-6, CAP-14 | AD-23, AD-31, AD-37 | conformance | Bidirectional package manifests, signature/hash/chain results, remap table, inert staging record, and collision tests. |
| REQ-53 | Derived caches MUST be excluded from export by default and MAY transfer only after destination identity-manifest and byte revalidation; disposable workspaces MUST be excluded unless retained as durable artifacts; active jobs MUST be paused/checkpointed or marked non-resumable. | CAP-12, CAP-14 | AD-23, AD-36 | integration | Per-class export inventory, destination cache verification, retained-workspace case, and active-job portability status. |
| REQ-54 | Baseline packaging MUST be a versioned OCI Helm API-v2 chart plus version-matched OCI CRD bundle and MUST install the one-replica control plane, egress gateway, enumerated RBAC/service accounts, Services, NetworkPolicies, disruption budgets, RWOP/RWX PVCs or configuration, and optional ingress without PostgreSQL, S3, external DB/object store, or storage gateway. | CAP-13, CAP-16, CAP-21 | AD-21, AD-35 | conformance | Rendered inventory, image/chart signatures, clean-install report, and dependency/endpoint scan. |
| REQ-55 | Installation MUST fail unless cross-node/cross-Pod qualification proves RWX read-after-fsync, temp-file atomic rename visibility, parent-directory fsync behavior, crash/remount durability, stale-mount detection, and kubelet `subPath` mount/reconnect behavior; object-like or acknowledge-before-durable backends MUST be rejected. | CAP-16, CAP-19, CAP-21 | AD-21, AD-34 | conformance | Machine-readable probe results on each supported storage profile, including injected crash/remount and rejected non-conformant profile. |
| REQ-56 | SQLite, CRD, worker-protocol, and RWX-layout upgrades MUST use expand-migrate-contract, N/N-1 compatibility, resumable operation ledgers, immutable copy/fsync/hash verification, pointer CAS, rollback windows, and pre-mutation compatibility gates. Ordinary Helm rollback MUST NOT claim to roll back CRDs, and backup MUST refuse an in-flight pointer switch. | CAP-13, CAP-16, CAP-19 | AD-22 | chaos | Crash matrix across migration phases, N/N-1 handshake report, rollback outcome, CRD lifecycle record, and backup refusal. |
| REQ-57 | Delivery MUST be additive and conformance-gated, preserve established application seams and local behavior after every slice, and MUST NOT introduce a big-bang rewrite or feature-specific CodeRecon/handoff infrastructure. | CAP-1, CAP-2, CAP-13, CAP-14 | AD-26, AD-27 | conformance | Per-slice green local/shared suites, dependency-boundary checks, compatibility report, and demonstrable slice artifact. |
| REQ-58 | Active/active control-plane HA, multiple hostile tenants per installation, cross-tenant isolation, remote workers, and distributed shared-storage metadata/coordination/byte services MUST remain a Deferred profile. v1 MUST NOT preselect dedicated CodeRecon, index, handoff, or artifact infrastructure for that profile. | CAP-1, CAP-15, CAP-20, CAP-21 | AD-4, AD-30, AD-35, AD-36, AD-37 | operator inspection | Baseline manifests/API schemas and roadmap boundary statement showing no deferred-profile component or promise. |

## Bounded Operator and Release Decisions

These choices do not reopen AD-1 through AD-37. Each owner selects a conforming implementation before the named milestone.

| Decision | Bounded choice | Owner | Resolve before |
|---|---|---|---|
| DEC-1 | CSI/StorageClass, snapshot class/controller or qualified copy fallback, and parameters that pass REQ-55. | Cluster/storage operator | Slice 4 storage qualification exit. |
| DEC-2 | Ingress or Gateway controller, DNS, certificate automation, and public endpoint policy satisfying REQ-46. | Cluster/network operator | Slice 5 security-boundary exit. |
| DEC-3 | OIDC provider, group claims, role bindings, and production session policy satisfying REQ-37. | Security owner | Slice 5 identity acceptance. |
| DEC-4 | Kubernetes Secret baseline or optional Secrets Store CSI integration and the rotation runbook satisfying REQ-36. | Security/platform owner | Slice 5 secret-rotation acceptance. |
| DEC-5 | VolumeSnapshot versus quiesced-copy backup profile, protected copy location, cadence, and restore drill schedule within REQ-48 through REQ-51. | Storage/operations owner | Slice 6 backup/restore exit. |
| DEC-6 | Whether Linux `arm64` is claimed after all immutable worker images and REQ-55 profiles qualify; absence of qualification means `amd64` only. | Release owner | Slice 7 release qualification. |
| DEC-7 | Confirm or replace AD-15 scale, AD-16 retention, and AD-17 latency/restart/RTO/RPO defaults with testable values. | Product and operations owners | Before Slice 7 release-candidate gate. |

## Traceability

### Capability Coverage

| Capability | Requirements |
|---|---|
| CAP-1 | REQ-1, REQ-4, REQ-57, REQ-58 |
| CAP-2 | REQ-2, REQ-6, REQ-8, REQ-57 |
| CAP-3 | REQ-5, REQ-23, REQ-25 through REQ-28 |
| CAP-4 | REQ-10, REQ-30, REQ-34 |
| CAP-5 | REQ-4, REQ-11 through REQ-13, REQ-16 through REQ-24, REQ-29, REQ-40, REQ-44, REQ-49, REQ-50, REQ-52 |
| CAP-6 | REQ-3, REQ-36, REQ-52, REQ-59 |
| CAP-7 | REQ-9, REQ-14, REQ-31, REQ-32, REQ-37, REQ-40, REQ-45 |
| CAP-8 | REQ-38, REQ-42, REQ-47 |
| CAP-9 | REQ-2, REQ-6, REQ-11, REQ-13, REQ-15, REQ-21, REQ-40, REQ-41, REQ-51 |
| CAP-10 | REQ-8, REQ-46 |
| CAP-11 | REQ-23, REQ-29, REQ-35, REQ-43 through REQ-45 |
| CAP-12 | REQ-3, REQ-14, REQ-15, REQ-20, REQ-22 through REQ-25, REQ-29 through REQ-31, REQ-35, REQ-42, REQ-43, REQ-48, REQ-51, REQ-53 |
| CAP-13 | REQ-43, REQ-54, REQ-56, REQ-57 |
| CAP-14 | REQ-2, REQ-17, REQ-19, REQ-21, REQ-28, REQ-41, REQ-50, REQ-52, REQ-53, REQ-57 |
| CAP-15 | REQ-7, REQ-18, REQ-32 through REQ-36, REQ-39, REQ-46, REQ-58 |
| CAP-16 | REQ-1, REQ-9 through REQ-12, REQ-54 through REQ-56 |
| CAP-17 | REQ-23, REQ-25 through REQ-28 |
| CAP-18 | REQ-10, REQ-30, REQ-31, REQ-33 through REQ-35, REQ-38, REQ-42 |
| CAP-19 | REQ-11 through REQ-13, REQ-16, REQ-18 through REQ-20, REQ-23 through REQ-25, REQ-44, REQ-48 through REQ-51, REQ-54 through REQ-56 |
| CAP-20 | REQ-9, REQ-14, REQ-32, REQ-33, REQ-36, REQ-37, REQ-39, REQ-58 |
| CAP-21 | REQ-9, REQ-15, REQ-45 through REQ-47, REQ-54, REQ-55, REQ-58 |
| CAP-22 | REQ-1, REQ-3 |
| CAP-23 | REQ-5, REQ-7, REQ-8, REQ-22, REQ-26, REQ-28 |
| CAP-24 | REQ-1, REQ-4, REQ-7, REQ-8, REQ-59 |

### Architecture Coverage

| Decision | Requirements |
|---|---|
| AD-1 | REQ-1, REQ-2 |
| AD-2 | REQ-1, REQ-3 through REQ-5 |
| AD-3 | REQ-10, REQ-30, REQ-31 |
| AD-4 | REQ-9, REQ-39, REQ-58 |
| AD-5 | REQ-37 |
| AD-6 | REQ-32, REQ-33, REQ-37 |
| AD-7 | REQ-33 through REQ-35, REQ-39 |
| AD-8 | REQ-5, REQ-25 through REQ-28 |
| AD-9 | REQ-7, REQ-26, REQ-34, REQ-36 |
| AD-10 | REQ-11, REQ-17 through REQ-22, REQ-49 |
| AD-11 | REQ-6, REQ-11, REQ-13, REQ-14, REQ-40 |
| AD-12 | REQ-6, REQ-13, REQ-15, REQ-41, REQ-51 |
| AD-13 | REQ-30, REQ-31, REQ-35, REQ-38, REQ-51 |
| AD-14 | REQ-24, REQ-29, REQ-42, REQ-43, REQ-48 |
| AD-15 | REQ-38, REQ-47 |
| AD-16 | REQ-19, REQ-23 through REQ-25, REQ-44, REQ-50 |
| AD-17 | REQ-47, REQ-49 |
| AD-18 | REQ-35, REQ-45 |
| AD-19 | REQ-46 |
| AD-20 | REQ-36 |
| AD-21 | REQ-1, REQ-54, REQ-55 |
| AD-22 | REQ-43, REQ-56 |
| AD-23 | REQ-52, REQ-53 |
| AD-24 | REQ-5, REQ-26, REQ-28 |
| AD-25 | REQ-2, REQ-8 |
| AD-26 | REQ-57 |
| AD-27 | REQ-1, REQ-2, REQ-3, REQ-17, REQ-57, REQ-59 |
| AD-28 | REQ-2, REQ-23, REQ-47 |
| AD-29 | REQ-31, REQ-32 |
| AD-30 | REQ-9, REQ-18, REQ-22, REQ-33, REQ-39, REQ-58 |
| AD-31 | REQ-6, REQ-20, REQ-21, REQ-31, REQ-40, REQ-41, REQ-49, REQ-51, REQ-52 |
| AD-32 | REQ-4, REQ-7, REQ-39 |
| AD-33 | REQ-12 through REQ-15, REQ-43, REQ-50, REQ-51 |
| AD-34 | REQ-11, REQ-16, REQ-18, REQ-20, REQ-23, REQ-25, REQ-27, REQ-48 through REQ-51, REQ-55 |
| AD-35 | REQ-9, REQ-10, REQ-37, REQ-54, REQ-58 |
| AD-36 | REQ-12, REQ-23, REQ-24, REQ-50, REQ-53, REQ-58 |
| AD-37 | REQ-12, REQ-20 through REQ-22, REQ-28, REQ-29, REQ-49, REQ-50, REQ-52, REQ-58 |

Every REQ row names at least one governing CAP and AD, one allowed verification method, and concrete required evidence. `failure-modes.md` maps each material failure to one or more REQs; therefore no requirement or failure mode is orphaned.
