# Final Focused Data-Integrity Gate — Kubernetes Architecture

**Reviewed artifact:** `architecture/ARCHITECTURE-SPINE.md` (2026-08-05)  
**Scope:** writer serialization, expected-head append/fsync, operation identity, projection boundaries, recovery winner, callback fencing, compaction, SSE, import quarantine, backup/restore epochs, and integrity claims.

## Verdict

**REVISIONS REQUIRED — no remaining critical defects, but six high-severity architecture defects remain.**

The revision closes the earlier gaps in expected-head append/idempotent operation identity, the basic history-versus-projection winner, import quarantine, restore identity invalidation, and the stated trust boundary for integrity claims. The remaining defects are concurrency and point-in-time holes that the current contracts and acceptance criteria cannot make safe by implementation choice alone.

## Remaining Critical/High Findings

### HIGH-1 — `CodePlaneStorageShard` CAS plus `ReadWriteOnce` is not a storage-writer fence

AD-31 and AD-34 make a resourceVersion-CAS writer epoch the authority for a single-active gateway, but changing a CRD cannot revoke an old process's ability to write an already mounted PVC. Kubernetes `ReadWriteOnce` permits multiple Pods on one node and does not itself guarantee I/O fencing of a partitioned or terminating node. An old gateway can therefore continue appending with its previously accepted epoch while a replacement owns the newer CRD epoch; the old process is precisely the component that would need to reject itself.

The baseline needs a qualified storage-level exclusion primitive: for example, `ReadWriteOncePod` plus proven CSI detach/fencing semantics, or an atomic durable epoch/lock in the storage head that every append and compaction operation validates and that a stale process cannot overwrite. Failover must not expose the new gateway until the old attachment/process is demonstrably fenced. Otherwise writer serialization and expected-head checks can still split at the same prior head.

### HIGH-2 — Callback claim revalidation remains non-atomic with canonical append

AD-31 says callback append revalidates the active attempt claim “inside” the serialized storage operation. The claim is nevertheless a Kubernetes CRD field while the append commits on PVC storage. Replacement or cancellation can update the claim after the gateway's API read and before append fsync, admitting a transition from a worker that is stale at the canonical commit point. Serializing only PVC operations does not serialize the competing CRD invalidation.

Claim invalidation and callback admission need one shared linearization protocol. Attempt replacement/cancellation must first close or advance a gateway-owned callback epoch under the per-job sequencer, and callback append must condition on that durable epoch; alternatively, every claim mutation must pass through the same sequencer before its CRD projection. “Revalidate immediately before append” is insufficient because the race remains between validation and durable commit.

### HIGH-3 — The projection boundary does not cover multi-CRD query state

AD-31 gives `CodePlaneJob` projection fields an exact history prefix, but authoritative user-visible state also resides in `CodePlaneApproval`, `CodePlaneExecutionAttempt`, repository bindings, and operations. AD-12's snapshot boundary reads one resource; no contract defines a consistent boundary for an API response composed from several independently versioned CRDs. A response can therefore pair a job projection at sequence N with an approval or attempt from an earlier or later operation while still presenting a valid job `projectionSequence`/`projectionHash`.

The architecture must either materialize every field in the convergent job snapshot from one bounded job projection or return an explicit participant/version vector tied to the operation/history prefix and define retry/degraded behavior when that vector cannot be assembled. Kubernetes resourceVersions from separate objects must not be presented as one point-in-time snapshot.

### HIGH-4 — SSE replay has no stable history/compaction epoch

AD-12 binds cursors to tenant/instance/stream and handles retention expiry, but it does not pin a segment/checkpoint generation or require epoch revalidation during replay. Compaction can remove or relocate the next segment after a cursor is accepted and after earlier events have been emitted. The stream can then terminate after a partial “successful” replay or continue from a newer checkpoint without proving a contiguous sequence/hash join. AC-7 does not combine replay with compaction fault injection.

Cursors and replay responses must carry a history/checkpoint epoch and last-delivered sequence/hash. Replay must read a pinned immutable segment set, or revalidate before each emission boundary and fail atomically with `replay_window_exceeded`/restart instructions before claiming continuity. Compaction must honor bounded reader pins or explicitly invalidate the epoch; AC-7 must exercise every compaction/replay interleaving.

### HIGH-5 — Compaction can outlive its checkpoint verifier

AD-31 correctly requires checkpoint records to outlive dependent suffixes and exports, but it does not impose the same lifetime on the signing public key, certificate chain, algorithm policy, and revocation evidence needed to verify those records. Routine key rotation or key-record garbage collection can therefore make a retained suffix, legal hold, export, or restored backup unverifiable even though the checkpoint object itself remains.

The checkpoint contract must retain self-contained verification material and trust-chain/revocation evidence for at least the maximum lifetime of every dependent suffix, hold, export, and backup. Verification policy must distinguish cryptographic invalidity from a retired-but-valid historical signer. Compaction must fail closed unless that verifier lifetime is durably established.

### HIGH-6 — `CodePlaneBackupEpoch` freezes writers but does not close in-flight operations

The backup flow requires every writer to acknowledge a barrier, records heads, exports CRDs, and rejects later version/head drift. It never requires pre-barrier accepted `CodePlaneOperation` sagas to reach a terminal boundary or a specifically defined restorable parked phase before capture. A frozen set can therefore be stable yet semantically incomplete: desired intent may be ahead of history, a participant may exist while its operation is mid-phase, or an operation may report a result whose projection has not committed. Re-reading equal versions and heads does not detect this condition, so such a set can advance last-known-good.

Barrier acknowledgment must include draining each accepted operation to a committed result/projection or durably parking it at an enumerated recovery-safe phase with all participant preconditions and next action captured. Backup validation must reject projection/history/operation-phase inconsistencies, not only post-capture drift. Restore must explicitly resume or fail those parked operations before per-job activation.

## Gate Result

**Critical:** 0  
**High:** 6  
**Decision:** Do not treat the Kubernetes data-integrity architecture as implementation-ready until the six findings above are resolved.

