# Focused Architecture Review — Kubernetes Data Integrity and Audit

**Reviewed artifact:** `architecture/ARCHITECTURE-SPINE.md` (2026-08-05)  
**Review scope:** CRD current state versus PVC-backed canonical history; ordering and serialization; `resourceVersion`/high-water snapshot boundaries; crash recovery; idempotency; stale writers; retention/checkpoints; hashes; SSE convergence; partial import; backup/restore; Kubernetes multi-object atomicity.  
**Method:** Adversarial failure analysis across every state/history boundary, including process death, replica failover, watch reordering, stale retries, compaction, snapshot, import, and restore.

## Verdict

**REVISIONS REQUIRED — the direction is sound, but the current spine does not yet define a uniquely implementable integrity protocol.**

The document is unusually honest that Kubernetes cannot provide multi-object transactions, and it correctly requires preconditioned writes, visible degraded conditions, append-only canonical history, attempt fences, checkpoint roots, and scheduling-disabled restore verification. Those are strong foundations. The remaining gaps are not requests for implementation detail: they determine the linearization point, writer authority, recovery winner, and point-in-time meaning of the system. Different implementations can satisfy the current prose while losing, duplicating, reordering, or exposing events and while producing backups or imports that look complete but are not mutually consistent.

## Findings

### F-1 — No enforceable cross-replica serialization and durable-commit primitive for PVC history (BLOCKING)

AD-31 says the storage port “serializes append per job,” but does not define who owns that serialization or which storage primitive makes it safe. The topology has at least two API replicas and shows workers connected to storage, while Deferred leaves PVC access modes, filesystem layout, and segment format open. A process-local mutex, advisory file lock, or shared append file can all be presented as “serialized,” yet fail differently under Pod death, lease expiry, RWX filesystem caching, or failover. RWO storage also cannot simply be mounted by every API replica, while RWX does not imply portable lock, append, or cache-coherency semantics.

A canonical append needs a structural contract such as `append(job, expectedSequence, expectedHash, eventUUID, operationKey, canonicalBytes) -> committedSequence/hash`, with an atomic compare-and-advance of the head, a fenced writer authority, and an explicit durable-commit point. The architecture must choose either a single storage-owner service/shard, or a qualified CSI/filesystem protocol whose lock/fence, atomic replace, file and directory sync, torn-write recovery, and failover behavior are acceptance-tested. Direct worker writes to canonical history should be prohibited; workers should submit authenticated events to the owner.

### F-2 — A CRD snapshot plus high-water mark is not a point-in-time snapshot (HIGH)

AD-11 orders a Kubernetes command as CRD intent first and durable history second. AD-12 then calls CRD status the authoritative current-state snapshot and returns current fields, `resourceVersion`, `observedGeneration`, and a durable high-water mark from one resource. Between the CRD write and history commit, a snapshot can contain the new state while its mark precedes the event that explains that state. Replaying strictly after the mark later re-delivers a transition already reflected in the snapshot, and there is no event UUID or projection sequence attached to the snapshot that tells a client what it already includes. A crash can occur before `HistoryDegraded` is written, so that condition does not close the boundary.

The problem is larger when the current view depends on `CodePlaneApproval`, `CodePlaneExecutionAttempt`, or repository-binding objects: one object’s `resourceVersion` says nothing about the versions of the others, and Kubernetes resource versions are not a cross-object transaction token. Define a `projectionSequence/projectionHash` for the exact history prefix reflected in snapshot fields, keep accepted desired intent separate from durable projected current state, and either withhold a convergent snapshot until that projection is durable or return an explicitly non-convergent/degraded response. If a query composes multiple CRDs, it must expose the per-object versions used or materialize the bounded authoritative projection into one job resource.

### F-3 — Recovery has no deterministic winner for CRD/history disagreement (HIGH)

AD-31 specifies repair for “append succeeded, status update crashed” and degradation for “status mark has no matching history,” but the full recovery matrix is absent. It does not define the winner or permitted repair for: desired state ahead of history; current projection ahead of history but high-water unchanged; history ahead of status; a CRD deleted while retained history remains; history missing while the CRD remains; same sequence with a different hash; or a restored CRD whose generation/projection does not match the restored head. “Idempotent reconciliation” is not enough because blindly deriving the CRD from history can erase newer accepted intent, while blindly appending from the CRD can invent provenance or duplicate a transition.

Specify a state/history reconciliation table with monotonic fields, legal repairs, terminal degradation cases, and operator actions. Every accepted mutation should carry a durable operation/event identity and the prior CRD projection sequence so reconciliation can prove whether it is completing an existing operation rather than synthesizing a new one. Hash disagreement at the same sequence must be fail-closed and non-repairing.

### F-4 — Worker fencing has a validation-to-append stale-write window (HIGH)

AD-13 and AD-29 require the API to validate the active attempt UID, fence, Pod/Job UIDs, service account, and live resources before accepting a callback. That validation is not atomic with the later PVC append or CRD status update. Cancellation, attempt replacement, or Job deletion can win after validation but before append, allowing an event from the now-stale worker to enter canonical history. A subsequent status precondition failure prevents projection, but it does not retract an immutable event and can poison sequence/hash ordering.

Define the callback linearization point. The history append must be conditional on the active attempt fence and the authoritative job projection revision under the same serialized per-job operation, or all job mutations and worker callbacks must pass through a single fenced per-job sequencer. A callback that loses the fence race should produce a separately scoped rejection audit record, not a canonical state-transition event. Fault injection must cover invalidation immediately before and after durable append, not only stale credentials at request ingress.

### F-5 — Retry idempotency does not make append itself idempotent (HIGH)

Consumer deduplication by event UUID in AD-12 prevents duplicate application downstream; it does not prevent duplicate canonical records. If append commits and the API dies before returning or advancing status, a retry can append the same logical operation at a new sequence, especially if it regenerates the event UUID. AD-31 promises repair but does not require uniqueness or return-the-original-outcome behavior at the storage head.

For every mutating request, persist a stable operation key, canonical request digest, deterministic/stable event UUID, state (`pending/committed/failed`), resulting sequence/hash, and response summary. The append operation must atomically enforce uniqueness and return the original result on an identical retry; reuse with different canonical bytes must fail as an idempotency conflict. This record must survive API failover and the longest supported retry/import replay window.

### F-6 — CRD-resident idempotency keys conflict with bounded-resource requirements (MEDIUM-HIGH)

The consistency convention says Kubernetes persists idempotency keys on “the authoritative resource,” while AD-10 and AD-33 require bounded CRDs and prohibit unbounded status history. A long-lived job can receive unbounded commands, approvals, callbacks, and retries. Retaining every key violates the bound; pruning keys silently makes an old retry executable again. The spine defines neither key scope and payload binding nor expiry, maximum count, outcome retention, and behavior after expiry.

Use a bounded operation resource/index or history-backed idempotency ledger with an explicit retry horizon and garbage-collection rule tied to terminal state, export/import, and retention checkpoints. Reuse after expiry must produce an explicit “idempotency window expired” result rather than be treated as a new command. The architecture should state which keys are portable and how remapped imports avoid colliding with live operations.

### F-7 — Retention checkpoints are underspecified at the exact chain-cut boundary (MEDIUM-HIGH)

AD-16 and AD-31 now require a signed or audit-protected checkpoint before prefix deletion, which fixes the broad retention/hash-chain conflict. They do not define the checkpoint’s canonical contents, how it joins to the first retained event, how concurrent append and compaction serialize, or how long the checkpoint must live. A root retained under an independently expiring retention class can disappear while suffix events, exports, backups, or legal holds still depend on it. Key rotation and unavailable/revoked signing keys are also undefined.

The checkpoint should canonically bind tenant/job identity, last removed sequence/hash, first retained sequence and its prior hash, canonicalization and hash versions, compaction epoch/cutoff, signer/key ID, and previous checkpoint root. It must commit and become durable before deletion, be retained at least as long as any dependent suffix or package, and be serialized against append using the same head protocol. Verification from checkpoint must be explicitly weaker than verification from genesis and report that provenance.

### F-8 — Hash chains detect partial corruption, not a full authorized rewrite (MEDIUM)

AD-31’s unkeyed per-job hash chain and AD-10’s plaintext SHA-256 artifact hashes detect random corruption and edits that do not recompute descendants. A writer with PVC and manifest access can replace bytes, recompute the entire chain from genesis, and update CRD marks and backup manifests. The installation audit chain has the same problem unless independently anchored; saying a checkpoint is “audit-chain-protected” is circular when both chains share the same mutable trust domain. The trust-boundary section explicitly trusts cluster/storage administrators, so the architecture should not imply evidence against that actor.

State the honest guarantee: baseline hashes detect accidental corruption and incomplete/unauthorized writes that cannot also replace the trusted anchor; they do not prove integrity against a cluster/storage administrator. If stronger tamper evidence is required, periodically sign roots with a key outside the PVC write domain and preserve them in an operator-protected/off-cluster location or append-only transparency service. Backup and export manifests also need authenticated roots, not only checksums.

### F-9 — SSE replay can race retention and lacks a stable read epoch (MEDIUM-HIGH)

AD-12 defines replay-after-mark, replay-window expiry, disconnection of slow clients, and checkpoint convergence, but not what happens when compaction deletes a segment during an active replay. A cursor accepted while sequence N is retained can read through N+K after N+1…N+J have been deleted or relocated, producing a gap unless every read is from a stable segment generation. Pausing SSE whenever history is behind status also has no bounded recovery or terminal behavior if reconciliation cannot repair the lag.

Bind cursors to a history/checkpoint epoch and last delivered sequence/hash. Replay must use a pinned immutable segment set/read snapshot, or revalidate the epoch and fail explicitly before emitting across a changed boundary. Retention must honor active bounded replay pins or force a clean `replay_window_exceeded`, never return a partial success. Define timeout and client convergence behavior for persistent `HistoryDegraded`, and test compaction at every replay boundary.

### F-10 — Partial import lacks quarantine and a durable import commit record (HIGH)

AD-23 correctly rejects a fictitious multi-resource transaction and requires staging bytes plus per-resource outcomes. However, applying some CRDs can make controllers schedule work before the rest of the manifest, history, policy, approvals, bindings, and reference remaps exist. If the process dies before it writes a failed-import condition, there may be no single resource on which to expose the failure. “Compensates” is unsafe for append-only history and for collisions with pre-existing objects whose hashes matched at validation time but changed during apply.

Introduce a durable `ImportSession`/import-operation record keyed by manifest hash, with persisted source identity, remap table, object set, expected canonical hashes, per-object phases, and terminal outcome. All imported jobs/resources must remain quarantined and scheduling-disabled under that session until bytes, history chains, references, policies, and collisions are revalidated and each job is activated through a preconditioned final step. Recovery resumes the same phases; compensation may remove only resources proven to have been created by that session and must never roll back pre-existing matched data. The report must distinguish staged, applied-inert, committed, conflicted, and orphaned outcomes.

### F-11 — The backup procedure overstates cross-object and cross-PVC consistency (HIGH)

Backup step 1 exports Kubernetes resources, then step 2 quiesces writers at a high-water mark and snapshots storage. Resource mutations can occur between those steps. Even after writer quiescence, Kubernetes cannot export several CRDs at one atomic `resourceVersion`, and baseline `VolumeSnapshot` captures one volume; snapshots of history, artifacts, caches, and per-job PVCs are not an atomic volume group. The manifest can therefore be internally checksummed while binding CRD state from one logical time to PVC heads from another. This conflicts with the otherwise honest rejection of Kubernetes multi-object transactions.

Define an application-consistent backup epoch: disable new scheduling and mutations for the selected scope, drain or durably park in-flight sagas, force all accepted operations to known terminal/history boundaries, record per-job heads, snapshot each required volume, and re-read every included CRD. The backup is valid only if all relevant object versions/UIDs and history heads remain equal to the recorded set; otherwise retry or mark it failed. Where atomic CSI group snapshots are unavailable, explicitly state that capture is per-job/per-volume quiesced consistency, not cluster-wide simultaneity, and define dependency order and allowable skew. RPO measures snapshot age, not mutual consistency, and must not substitute for this validation.

### F-12 — Restore verification does not define how old generations/status become valid on new objects (MEDIUM-HIGH)

Restore creates CRDs with new Kubernetes UIDs and resource versions, but the manifest binds old UIDs/generations and AD-12 treats `resourceVersion`/`observedGeneration` as snapshot evidence. Recreating a spec gives it a new generation lifecycle; restoring status fields verbatim can falsely claim the new controller has observed that generation. Owner references, active attempt/Pod identities, fences, cursors, and imported scheduling state are likewise invalid after recreation. “Remaps references” and scheduling-disabled verification mode do not say which status is provenance-only, which is recomputed, and which jobs become non-resumable.

Define a restore epoch and status reconstruction algorithm. Preserve old UID/generation/resourceVersion only as immutable source provenance, create new metadata and ownership links, invalidate active attempts/fences/cursors, derive a new bounded projection from verified history/checkpoint, and let controllers set `observedGeneration` only after observing the recreated spec. Activation should be preconditioned per job after its CRD projection, history head, artifact references, policy, and repository binding all verify. A partial restore must remain globally or per-tenant scheduling-disabled until explicitly accepted.

### F-13 — Cross-resource sagas lack a durable step ledger (MEDIUM-HIGH)

AD-11 says to persist intent, append history, create/update dependents, and publish completion or a degraded condition. A condition on the main object is not necessarily sufficient to resume a saga whose dependent object was created with an ambiguous response, whose main object was deleted, or whose next step requires distinguishing “not attempted” from “committed but response lost.” Resource-level idempotency keys do not describe the expected participant set, compensation ownership, or completed step results.

Persist a bounded saga/operation identity and step ledger containing participant canonical IDs, expected preconditions, durable event identity, completed outcomes, and next action. Dependent resources should carry the same operation identity and immutable owner provenance. Reconciliation must discover and adopt already-created dependents rather than create replacements, and completion must be a preconditioned monotonic transition. This same primitive can underpin commands, cancellation, import, and backup quiescence.

## Required Integrity Contract Before Implementation

The following minimal contract would close the structural gaps without pretending Kubernetes offers transactions:

1. **One per-job linearization protocol:** fenced writer authority plus atomic compare-and-append against `(sequence, hash)`, stable operation/event identity, and a qualified durable-commit primitive.
2. **One projection boundary:** every current-state snapshot declares the exact committed history prefix it reflects; desired intent that is not yet durable is visibly separate.
3. **One recovery matrix:** deterministic handling for CRD ahead, history ahead, mismatch, absence, stale attempt, compaction, and restore.
4. **One durable operation model:** payload-bound idempotency and resumable saga/import/backup phases with bounded retention semantics.
5. **Explicit quiescence, not fictitious atomicity:** backup/import/restore activate per resource only after verification, expose partial outcomes, and never call independently captured objects/volumes one atomic snapshot.
6. **Anchored and scoped integrity claims:** checkpoints have exact join/lifetime rules, SSE reads a stable epoch, and hash guarantees state which trusted actors can recompute them.

## Positive Observations

- AD-11 and AD-23 explicitly reject Kubernetes multi-object atomicity instead of hiding it behind controller language.
- AD-31 correctly orders history commit before high-water advancement and treats a claimed head without bytes as degraded.
- AD-12 correctly uses per-job sequence rather than Kubernetes watch order, requires replay after disconnect, and avoids persisting keepalives.
- AD-13’s immutable attempt UID/fence and AD-29’s live identity binding are the correct stale-worker foundation.
- AD-16’s checkpoint-before-compaction rule and AD-18’s audit-chain requirement are materially stronger than retention without anchors.
- Restore starts scheduling-disabled and verifies hashes/chains before execution, which is the right default even though activation semantics need tightening.

**Report path:** `_bmad-output/specs/spec-codeplane-kubernetes-and-local-daemon/architecture/reviews/review-data-integrity-kubernetes-update.md`
