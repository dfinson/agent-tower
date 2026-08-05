# Architecture Review — Lifecycle, Data-Loss, and Concurrency Risks

**Scope:** ARCHITECTURE-SPINE.md — crash-at-every-boundary analysis  
**Reviewer:** Copilot (automated)  
**Date:** 2026-08-05  
**Verdict:** CONDITIONALLY SOUND — 4 critical, 7 high, 9 medium, 5 low findings.  
The spine is unusually thorough; most risks involve under-specified crash windows, ambiguous CAS domains, and missing durable-reference ordering rather than design flaws.

---

## Critical Findings

### C-1 — History append / projection update crash window (AD-11, AD-31, AD-34)

**Risk:** The gateway `append()` fsyncs bytes and head atomically, but the subsequent CRD projection update (`CodePlaneJob.status.projection`) is a separate Kubernetes API call. A crash between fsync-ack and projection write leaves history ahead of projection. AD-12 says "history ahead repairs forward," but the repair procedure is not specified: who initiates reconciliation, what happens to in-flight SSE cursors bound to the stale projection, and whether the repair itself is idempotent under concurrent reconciler replicas.

**Classification:** CRITICAL — data committed but invisible; SSE clients may never converge without operator action.

**Fix (AD-level):** Add to AD-12: "On startup and on every projection-condition degradation, the history-status controller re-derives projection from verified head. Projection repair is leader-elected or sharded by job UID prefix and uses the same resourceVersion precondition as normal projection. SSE emission from a stale projection resumes at the last-emitted sequence after projection catches up; no gap markers are synthesized for internal lag."

---

### C-2 — Storage gateway takeover: two-writer window before CSI fence proof (AD-34)

**Risk:** AD-34 says takeover "keeps the shard unavailable until the old gateway Pod is terminated, attachment is detached or otherwise CSI-fenced, exclusive replacement mount is proven." But the proof mechanism for "exclusive replacement mount" is undefined. Between old Pod termination and new Pod mount, the CSI driver may not have fenced the old writer at the block-device level; the spine defers to "CSI profile" but never specifies a minimum fencing contract. A storage driver that merely unmounts without SCSI reservations or equivalent could allow a zombie writer's buffered writes to land after the new writer opens the device.

**Classification:** CRITICAL — two concurrent writers to canonical history PVC = silent corruption of AD-31 chain.

**Fix (AD-level):** Add to AD-34: "The minimum CSI fencing contract is: the replacement Pod MUST NOT proceed until the CSI driver confirms the old volume attachment is fully detached or the node is fenced (e.g., via `VolumeAttachment` deletion confirmation and node drain). If the CSI profile cannot prove single-writer exclusion, the storage shard enters `Degraded` and blocks all appends until operator intervention. The gateway startup sequence MUST verify head epoch and last-entry integrity hash before accepting any new append."

---

### C-3 — Handoff package selection ABA race under concurrent attempt replacement (AD-13, AD-37)

**Risk:** AD-37 selects "the newest compatible committed package for the same lineage and intended consumer using stable creation sequence then package ID." But during attempt replacement (AD-13 claim generation N → N+1), the following race exists:

1. Attempt N commits handoff package P1, advances callback epoch, then dies.
2. Attempt N+1 starts, selects P1.
3. Meanwhile, a concurrent resolution/follow-up job also creates attempt M that selects P1.
4. P1's content hash matches but its `intended consumer` field allows both. Two independent executions now fork from the same handoff with no coordination.

This is an ABA problem: the handoff identity looks the same but the execution context has diverged.

**Classification:** CRITICAL — silent divergent execution from a single handoff; the spine has no mechanism to detect or prevent this.

**Fix (AD-level):** Add to AD-37: "A handoff package, once selected by an attempt, MUST record the selecting attempt UID and claim generation in `CodePlaneSessionHandoff.status`. A second selection by a different attempt for the same lineage MUST either (a) fail closed if the first selecting attempt is still active or its outcome is not yet durably recorded, or (b) create a descendant package that binds the prior selection as provenance. Concurrent independent consumers of the same package are permitted only when explicitly declared as fan-out by policy."

---

### C-4 — Backup epoch quiesce / operation park crash leaves scheduling permanently disabled (AD-17, Backup §1–§6)

**Risk:** `CodePlaneBackupEpoch` sets a "generation-fenced mutation/scheduling barrier." If the backup controller crashes after setting the barrier but before capture or timeout, and the `BackupEpoch` resource is left in `Quiesced` with no liveness signal, scheduling remains disabled indefinitely. The spine says "every API, reconciler, and storage writer durably acknowledges or times out" but does not specify who owns the timeout or what happens if the timeout controller itself is unavailable.

**Classification:** CRITICAL — complete scheduling outage with no automatic recovery path.

**Fix (AD-level):** Add to Backup §1: "The `CodePlaneBackupEpoch` resource MUST carry an absolute UTC deadline. If the backup controller does not advance the epoch to `Captured` by the deadline, any controller observing the expired epoch MUST transition it to `Failed` and release the scheduling barrier. The deadline is operator-configurable with a default of 15 minutes. A `BackupEpoch` in `Failed` state retains its audit record but does not block scheduling."

---

## High Findings

### H-1 — Index generation GC race with late lease acquisition (AD-36)

**Risk:** AD-36 says generations are "reference-counted and leased, and GC only after every durable reference and live lease is gone." But lease acquisition by a newly starting attempt Pod and GC by the index controller are not ordered by any shared lock. Timeline:

1. Index controller observes refcount=0, lease count=0, begins GC.
2. Attempt controller selects this generation for a new Pod, writes a lease reference to `CodePlaneRepositoryIndex.status`.
3. Index controller deletes bytes (GC was already in progress).
4. Pod starts, queries the generation, gets `IntegrityFailed` or missing data.

**Classification:** HIGH — data loss of rebuildable cache, but causes attempt failure and retry storm.

**Fix:** AD-36 should specify: "GC MUST use a resourceVersion-preconditioned status update to set `GarbageCollecting` condition; lease acquisition MUST also use a resourceVersion precondition. The GC controller MUST re-read the resource after byte deletion and verify no new leases were acquired during deletion; if leases appeared, it MUST set `RebuildRequired` and abort tombstoning."

---

### H-2 — Repository-context three-way merge is non-deterministic under concurrent publication (AD-37)

**Risk:** AD-37 says "disjoint concurrent changes may merge only through deterministic three-way validation" but does not define what "deterministic" means when two publications race with the same parent generation. If attempt A publishes generation G1 (parent G0) and attempt B publishes generation G2 (parent G0) concurrently, and both succeed the parent-generation precondition against different resourceVersions, the merge must produce G3. But the merge input order (G1 base + G2 overlay, or G2 base + G1 overlay) can produce different results for non-commutative changes (e.g., two different values for the same environment key).

**Classification:** HIGH — non-deterministic merge can silently pick different winners on retry.

**Fix:** AD-37 should add: "When two sibling generations share the same parent, merge order is defined by generation creation timestamp (UTC), breaking ties by generation UID lexicographic order. Conflicting keys within the same protocol namespace (e.g., two different values for the same decision key) MUST set `Conflict` rather than merge; only structurally disjoint namespaces may auto-merge."

---

### H-3 — Import session crash leaves resources scheduling-disabled with no resume signal (AD-23)

**Risk:** `CodePlaneImportSession` records "per-object phases" and imported resources "remain scheduling-disabled and inert until … each activates through a preconditioned final step." If the import controller crashes mid-import, the session can be resumed ("Recovery resumes the same session"). But the spine does not specify how recovery is triggered — is it automatic on controller restart, or does it require operator action? Imported resources that passed validation but whose activation step never ran will be permanently inert.

**Classification:** HIGH — imported jobs silently stuck; no operator alert mechanism defined.

**Fix:** AD-23 should add: "On startup, the import controller MUST list all `CodePlaneImportSession` resources in non-terminal phases and resume processing. Each non-terminal session MUST carry an absolute deadline; expired sessions transition to `Failed` and their partially imported resources are compensated."

---

### H-4 — Finalizer ordering gap: workspace deletion vs. handoff/context publication (AD-14, AD-37)

**Risk:** AD-14 cleanup order: "stop/checkpoint worker → commit outcome/history → revoke credentials → release repository/ref → finalize retained storage → delete workspace/Pod." AD-37 says "workspace deletion cannot precede [durable resolution record]" and repository-context is published at "checkpoint/termination." But the finalizer ordering does not explicitly guarantee that repository-context publication completes before workspace deletion. If the workspace PVC is deleted while the context publication is still in-flight, the publication will fail and the context generation is lost.

**Classification:** HIGH — loss of repository-context generation, breaking future handoff chain.

**Fix:** AD-14 cleanup ordering should explicitly list context/handoff publication as a step between "commit outcome/history" and "revoke credentials": "… commit outcome/history and retention tombstone; publish pending repository-context and handoff artifacts; revoke attempt credentials; …"

---

### H-5 — Operation idempotency window expiry during backup quiesce (AD-11)

**Risk:** AD-11 says retries after the "declared ledger/history window" return `idempotency_window_expired`. During a backup epoch's quiesce phase, operations may be parked for longer than the idempotency window. When the backup completes and the client retries the parked operation, it receives `idempotency_window_expired` instead of the parked result, forcing manual recovery.

**Classification:** HIGH — client-visible failure for a correctly behaving operation.

**Fix:** AD-11 should add: "The idempotency window MUST NOT expire for operations that are in a recovery-safe parked phase due to an active `CodePlaneBackupEpoch`. The window timer suspends while the operation is parked and resumes only after the epoch is released."

---

### H-6 — Stale worker credential renewal after callback epoch advance (AD-29, AD-31)

**Risk:** AD-29 says "Claim replacement invalidates renewal and advances the AD-31 callback epoch." But the invalidation of the old credential and the epoch advance are two separate operations. A stale worker that renews its credential between the epoch advance and the credential revocation could obtain a fresh token bound to the old claim generation, then append to history with the new callback epoch (since it has a valid token). The gateway would accept the append because the token is technically valid and the callback epoch matches.

**Classification:** HIGH — stale worker appends to canonical history after replacement.

**Fix:** AD-29 should specify: "Credential renewal MUST verify that the requesting Pod UID, attempt UID, and claim generation still match the CAS-bound values on `CodePlaneJob.status.activeClaim`. Epoch advance MUST complete and be visible to the gateway before any new credential is issued for the replacement claim. The gateway MUST reject appends from credentials bound to a claim generation older than the current callback epoch's bound generation."

---

### H-7 — Retention tombstone race with legal hold application (AD-16)

**Risk:** AD-16 says "Legal hold prevents deletion" and "storage-port deletion is tombstoned, audited, and retried idempotently." But if a retention GC controller tombstones an artifact and a legal hold is applied between the tombstone write and the actual byte deletion, the idempotent retry will delete bytes that should now be held. The tombstone does not re-check hold status before deletion.

**Classification:** HIGH — legal-hold violation; compliance risk.

**Fix:** AD-16 should add: "Byte deletion MUST re-verify legal-hold status immediately before physical deletion. A tombstoned resource that acquires a legal hold between tombstoning and deletion MUST have its tombstone reversed (set back to `available`) and the hold recorded."

---

## Medium Findings

### M-1 — `ensure_repo_indexed` selection ambiguity when multiple base generations match (AD-36)

**Risk:** AD-36 says `ensure_repo_indexed` "selects or builds an exact base." "Exact" is defined by tenant, repository, commit/tree, schema version, feature config, and model/tool digest. But during a schema version upgrade, both old and new generations may exist with `Ready` condition. The selection tiebreaker is not specified.

**Classification:** MEDIUM — non-deterministic index version selection during upgrade windows.

**Fix:** AD-36 should specify: "When multiple `Ready` generations match all identity fields, select the one with the highest schema version. If schema versions also tie, select by newest creation timestamp, then UID."

---

### M-2 — `merge_index` publishes successor but source overlay retirement is not atomic (AD-36)

**Risk:** `merge_index` "publishes a verified successor target before retiring the source overlay." Between publication and retirement, both generations are `Ready` and queryable. If a concurrent query uses the source overlay after the successor is published, it gets stale results.

**Classification:** MEDIUM — brief window of stale query results during merge.

**Fix:** AD-36 should add: "The source overlay MUST transition to `Stale` atomically with (same resourceVersion precondition as) the successor publication. Query routing MUST prefer the successor when both are visible."

---

### M-3 — SSE cursor epoch binding does not survive compaction boundary (AD-12, AD-31)

**Risk:** AD-12 says cursors "bind tenant, instance, stream, history/checkpoint epoch, and last sequence/hash" and "compaction honors the pin or returns `replay_window_exceeded`." But AD-31 checkpoints "bind cut boundaries" — if a compaction runs between two checkpoint roots and a cursor's pinned segment is compacted, the client gets `replay_window_exceeded` even though the data was recently live. The spine does not specify a minimum pin duration.

**Classification:** MEDIUM — client-visible replay failure during normal compaction.

**Fix:** AD-12 should specify a minimum pin TTL: "Pinned replay segments MUST remain available for at least the greater of the client's declared replay window or 1 hour. Compaction MUST NOT reclaim segments with active pins."

---

### M-4 — `drop_worktree` releases overlay reference but does not await in-flight queries (AD-36)

**Risk:** After `drop_worktree` releases the overlay reference/lease, the GC controller may begin collecting the overlay while queries from the owning attempt Pod are still in-flight against the tenant CodeRecon service.

**Classification:** MEDIUM — query failures during normal worktree teardown.

**Fix:** AD-36 should add: "Overlay lease release MUST include a grace period (default 30 seconds) during which the generation remains protected from GC. The CodeRecon service MUST drain in-flight queries for the generation before confirming release."

---

### M-5 — Local backup mutation barrier has no explicit timeout (Backup §8)

**Risk:** Local backup "enters a mutation barrier, drains or durably parks accepted operations, freezes artifact and repository-context publication." No timeout is specified. If an operation cannot be parked (e.g., a hanging agent process), the barrier blocks indefinitely.

**Classification:** MEDIUM — local backup hangs with no recovery.

**Fix:** Backup §8 should add: "The local mutation barrier has a default timeout of 5 minutes. Operations that cannot be parked within the timeout are force-interrupted and marked `interrupted` with backup-barrier provenance."

---

### M-6 — CRD archive-then-GC for terminal attempts: 24-hour window vs. export dependency (AD-15, AD-23)

**Risk:** Terminal `CodePlaneExecutionAttempt` CRs archive then GC within 24 hours (AD-15). But an export started at hour 23 may reference attempt metadata that is GC'd at hour 24 mid-export.

**Classification:** MEDIUM — export produces an incomplete manifest.

**Fix:** AD-15 should add: "GC of terminal CRs MUST be deferred while any `CodePlaneImportSession`, `CodePlaneBackupEpoch`, or export operation references or could reference the resource. The 24-hour window begins after the last such reference is released."

---

### M-7 — Weighted admission determinism under concurrent quota release (AD-13)

**Risk:** AD-13 specifies "deterministic weighted share with aging, tenant/repository/identity queued and active quotas, stable tie-breaking, and no persisted queue-position churn." But when two quota slots open simultaneously (two jobs finish at the same instant), two reconciler replicas may each independently admit a different next-in-queue job, potentially over-admitting.

**Classification:** MEDIUM — temporary over-admission above quota.

**Fix:** AD-13 should add: "Admission decisions MUST be serialized through a single admission controller leader or use resourceVersion-preconditioned quota counter updates that fail if the quota was already consumed by a concurrent admission."

---

### M-8 — `CodePlaneRepositoryRefLock` one-hour GC after durable release vs. concurrent re-acquisition (AD-24)

**Risk:** The ref lock GCs one hour after durable release. A new job attempting to acquire the same ref lock during this hour must create a new resource. But if the old resource is still present, the "exactly one active" cardinality constraint may reject the new acquisition, forcing a one-hour wait.

**Classification:** MEDIUM — unnecessary scheduling delay for sequential ref operations.

**Fix:** AD-24 should specify: "A `Released` ref lock MUST be immediately re-acquirable by a new resourceVersion-preconditioned spec update that transitions it back to `Held`. GC applies only to `Released` locks that are not re-acquired within the window."

---

### M-9 — Fail-open compatibility: worker protocol version negotiation failure mode (AD-3, AD-22)

**Risk:** AD-3 says "the worker and control API negotiate a semantic protocol version before credential issuance; … Worker handshake rejects unsupported protocol ranges before an attempt is created" (AD-22). But the behavior when a protocol version is deprecated (served but not preferred) during a rolling upgrade is not specified. A worker running the old image may negotiate a deprecated version that the new API replica no longer serves.

**Classification:** MEDIUM — attempt creation fails during rolling upgrade; retry with new image succeeds but the failure is opaque.

**Fix:** AD-22 should add: "During rolling upgrade, both N and N-1 protocol versions MUST be accepted by all API replicas until the upgrade is complete. Protocol deprecation MUST NOT remove served versions until all worker images are confirmed updated. Negotiation failure MUST return a structured error indicating the supported range and the required image version."

---

## Low Findings

### L-1 — AD-31 hash algorithm agility not specified

**Risk:** AD-31 says "each canonical entry hashes its encoding, prior hash, sequence, operation ID, and provenance" but does not name the hash algorithm or specify how algorithm transitions work across backup/restore/export boundaries.

**Classification:** LOW — future-proofing gap; no immediate risk.

**Fix:** AD-31 should specify: "The hash algorithm is identified in the checkpoint record. Algorithm transitions require a new checkpoint root; segments before and after the transition are independently verifiable."

---

### L-2 — `CodePlaneOperation` three-summary retention may lose operation provenance for long-running jobs

**Risk:** Jobs with many operations (e.g., multiple approval cycles) retain only three terminal summaries. Earlier operation provenance is lost from the CRD, even though history retains the events.

**Classification:** LOW — provenance query requires history replay rather than CRD read.

**Fix:** Acceptable as-is if documented. Add to AD-11: "Operation provenance beyond the three retained summaries is available only through history replay; CRD status is not a complete audit trail."

---

### L-3 — Local-daemon `server_restart` resume vs. SQLite WAL recovery ordering

**Risk:** AD-2 uses `server_restart` to resume in place. If the daemon crashed with uncommitted WAL frames, SQLite WAL recovery runs at open time. The spine does not specify whether job state inspection happens before or after WAL recovery, which could lead to resuming from a pre-crash state that the WAL would have corrected.

**Classification:** LOW — SQLite handles this correctly by default, but the spine should be explicit.

**Fix:** AD-2 should add: "SQLite WAL recovery MUST complete before any job state inspection or resume logic executes."

---

### L-4 — Lease-only coordination for reconcilers may cause brief dual-active during lease expiry (AD-13)

**Risk:** AD-13 says "Leases optimize coordination only" and are not durable authority. But during lease expiry (e.g., leader pod is slow-partitioned), both old and new leaders may briefly reconcile the same job, creating duplicate attempt claims. The resourceVersion precondition on `activeClaim` prevents duplicate *success*, but both reconcilers waste API calls and may cause condition flapping.

**Classification:** LOW — no data loss but noisy during partition events.

**Fix:** Acceptable; add observability: "Dual-reconciler detection MUST emit a metric and structured log entry for operator diagnosis."

---

### L-5 — Export manifest `secret-reference remapping requirements` are underspecified (Backup §4, AD-23)

**Risk:** The backup manifest "binds … secret-reference remapping requirements" but does not define what happens when the target cluster's secret references do not exist. Import validates availability, but the behavior (fail the import? import with degraded status?) is ambiguous.

**Classification:** LOW — edge case for cross-cluster migration.

**Fix:** AD-23 should add: "Missing secret references at import target set `SecretUnavailable` condition on the imported resource and block scheduling until the operator provides the referenced secret. Import does not fail globally for missing secrets."

---

## Summary Matrix

| Severity | Count | Key Theme |
|----------|-------|-----------|
| Critical | 4 | Crash windows between durable write and projection/fencing; ABA handoff selection; backup barrier without timeout |
| High | 7 | GC/lease races; finalizer ordering; credential renewal gap; legal hold race; idempotency window during backup |
| Medium | 9 | Selection ambiguity; merge non-determinism; compaction vs. cursors; rolling upgrade protocol compat |
| Low | 5 | Algorithm agility; WAL recovery ordering; lease flapping; export secret remapping |

All fixes are AD-level specification clarifications. No structural redesign is needed.
