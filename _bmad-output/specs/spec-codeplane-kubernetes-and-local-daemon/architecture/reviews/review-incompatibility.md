# Adversarial Incompatibility Review — ARCHITECTURE-SPINE.md

**Reviewer:** Critic agent (devil's advocate)  
**Date:** 2026-08-05  
**Target:** `architecture/ARCHITECTURE-SPINE.md`  
**Method:** Construct pairs of implementation units one level below the spine that each obey every AD literally yet are silently incompatible with each other. Each pair identifies a hole in the spine's current AD coverage. All findings are reconciled against the canonical spec package (SPEC.md, mode-requirements.md, brownfield-constraints.md).

---

## Summary Verdict

The spine is architecturally coherent and well-structured. However, **10 concrete incompatibility pairs** were found across the reviewed dimensions. Six are **Blocking** (they can produce data loss, duplicate execution, divergent state, or security regression without violating any AD as written). Four are **Non-Blocking** (they produce observable divergence between modes or implementations but can be corrected before release gates). No pairs were found in the upgrade (AD-22) or export/import (AD-23) dimensions that rise above Non-Blocking.

---

## Incompatibility Pairs

---

### H-1 — Shared-data shape: `StoragePort` event cursor type

**Dimension:** Shared-data shape  
**Severity:** 🔴 Blocking  
**Governing decisions:** AD-10, AD-11, AD-12  

**The pair:**

- **Unit A — PostgreSQL event log adapter:** Implements `global_cursor` as a PostgreSQL `bigserial` sequence value (a monotonically increasing 64-bit integer) because the AD says "storage-local global cursor" and PostgreSQL sequences are the natural choice.
- **Unit B — SSE dispatcher / client resume handler:** Receives an opaque cursor from the client `Last-Event-ID` header and passes it directly into the `EventLogPort.events_after(cursor)` query.

**Incompatibility:** AD-11 says each event has a "storage-local global cursor" but does not specify its type, encoding, serialization, or comparison semantics. Unit A may serialize it as a raw integer; Unit B may serialize it as a string-encoded UUID, timestamp, or composite. On resume, the SSE handler passes an integer-formatted cursor to an implementation that now expects `bigserial`—or vice versa after a future adapter swap—producing `InvalidTextRepresentation` or silent full replay from offset 0. The local SQLite adapter independently picks `rowid` or a timestamp-based cursor. Neither is wrong under the AD.

**AD Tightening:** Amend AD-11 to add: *"The storage-local global cursor is an opaque byte string whose only contracted operations are strict ordering within one adapter instance, serialization to a UTF-8 string for SSE `id:` field and client resume header, and comparison equality against the high-water cursor returned by the snapshot endpoint. No implementation unit outside the persistence port may parse, compare numerically, or assume the type of the cursor value. The snapshot response and event subscription response carry the cursor as the same opaque string type."*

---

### H-2 — Data ownership: Artifact metadata split between PostgreSQL and object storage

**Dimension:** Data ownership / split-brain  
**Severity:** 🔴 Blocking  
**Governing decisions:** AD-10, AD-16, AD-23  

**The pair:**

- **Unit A — Artifact ingestion service:** Writes artifact metadata row to PostgreSQL (name, job ID, content hash, retention class, size) and then uploads the blob to S3. On S3 upload failure after PostgreSQL commit, it logs the error and relies on a background retry.
- **Unit B — Artifact retention/deletion worker:** Queries PostgreSQL for artifacts past their retention deadline, issues S3 `DeleteObject`, then deletes the PostgreSQL row. It does not check whether the S3 upload was ever successfully completed.

**Incompatibility:** AD-10 says PostgreSQL owns metadata and object storage owns blobs but says nothing about the required consistency protocol between them. Unit A creates a permanently orphaned PostgreSQL row whose blob never lands in S3. Unit B will attempt to delete a non-existent S3 object (returns 404) and then delete the metadata row, creating no observable error but permanently losing the artifact without the "explicit degraded artifact" guarantee stated in the Backup/Recovery section. AD-10 and AD-16 are both obeyed literally.

**AD Tightening:** Amend AD-10 to add: *"A metadata row for a blob artifact MUST carry an explicit upload-completion flag. Metadata is not queryable as 'available' until the blob is confirmed received by the object store. Deletion MUST verify the S3 delete result; a 404 on an artifact that was never marked upload-complete is recorded as a degraded artifact and tombstoned, not silently deleted. The persistence port owns this two-phase protocol; services do not implement it directly."*

---

### H-3 — State/event mutation: Approval resolution and job state divergence

**Dimension:** State/event mutation atomicity  
**Severity:** 🔴 Blocking  
**Governing decisions:** AD-11, AD-5  

**The pair:**

- **Unit A — ApprovalService:** Resolves an approval (approve or deny) by committing an `approval.resolved` event and updating the approval row inside one unit-of-work transaction. It does not update the job state in the same transaction because the AD says "every authoritative mutation and its canonical event append commit in one transaction" and the approval resolution is a single mutation.
- **Unit B — JobScheduler / RunnerService:** Watches for `approval.resolved` events (from the SSE bus or PostgreSQL notification) and then opens a new transaction to transition the job from `waiting` to `running`. Between these two independent transactions, a concurrent cancellation arrives and commits `job.canceling`, also in a separate transaction.

**Incompatibility:** The job ends up with both a `waiting → running` transition and a `waiting → canceling` transition because each unit obeys AD-11 atomically for its own mutation but neither unit owns the compound approval-then-resume state machine. The state machine diagram in the spine shows `waiting → running` and `waiting → canceling` as valid transitions but the AD never assigns ownership of the mutual exclusion between them. Neither unit violates an AD.

**AD Tightening:** Amend AD-11 or AD-13 to add: *"State machine transitions that depend on observing a prior event (e.g., a job resuming from `waiting` because an approval resolved) MUST evaluate the current state inside the same unit-of-work transaction that commits the new state and event. The scheduler or service that owns a transition is responsible for serializing it with concurrent cancellation by acquiring a row-level lock on the job record before the state check."*

---

### H-4 — Scheduling fence: Worker callback validation gap

**Dimension:** Scheduling fences  
**Severity:** 🔴 Blocking  
**Governing decisions:** AD-3, AD-13  

**The pair:**

- **Unit A — Worker Pod:** Sends authenticated worker events to the control API carrying `(job_id, attempt_id, fence_token)`. The token is the integer monotonically increasing value minted at lease claim time (AD-13).
- **Unit B — Control API worker callback handler:** Verifies that `attempt_id` matches the currently active attempt for the job, but queries the attempt table directly rather than reading the current fencing token from the lease row. It considers any attempt whose row is present and not yet finalized as active.

**Incompatibility:** After a lease expires and recovery starts a new attempt (new fencing token), the old worker Pod—still running briefly due to network partition—sends a callback with the old `fence_token` and old `attempt_id`. Unit B checks the attempt row, finds it exists (it has not yet been tombstoned by the finalizer), and accepts the stale write, committing a state event for the wrong attempt. AD-13 says "every worker write must present the current attempt and fence" but does not say the API handler must validate the fence by comparing it to the current lease's token rather than the attempt record's existence.

**AD Tightening:** Amend AD-13 to add: *"The control API worker callback port MUST validate the presented fencing token by reading the current unexpired lease row for the job and comparing the token byte-for-byte. A fence mismatch or missing lease MUST be rejected with an audited error before any state or event is written, regardless of whether an attempt row with the presented attempt_id exists."*

---

### H-5 — Worker protocol: Version negotiation and schema evolution

**Dimension:** Worker protocol  
**Severity:** 🔴 Blocking  
**Governing decisions:** AD-3, AD-22  

**The pair:**

- **Unit A — Worker Pod (N-1 image):** Speaks worker protocol version 1. It sends heartbeat events with field `heartbeat_at` (a timestamp string).
- **Unit B — Control API (N image):** In the new version, the heartbeat field was renamed to `last_seen_at` for consistency with the export schema. The protocol version advertised by the control API is still "1.0" because the change was judged non-breaking (additive field rename under the backwards compatibility rule).

**Incompatibility:** AD-22 says "worker protocol support release N and N-1 during a rolling upgrade" but does not define what constitutes a protocol version boundary or who is responsible for maintaining the version range table. Unit B's author interprets "additive" as meaning the field rename is not a protocol version bump. Unit A's worker never sends `last_seen_at`, so Unit B's heartbeat handler finds a null value, fails to update the lease heartbeat, and the lease expires—causing the job to be interrupted. Neither unit violates an AD.

**AD Tightening:** Amend AD-22 to add: *"The worker protocol version is a semantic version string negotiated in the worker handshake. A field rename, removal, or type change in any message the worker is required to send constitutes a minor or major version increment. The control API MUST simultaneously support N and N-1 protocol versions in the same running binary. The worker handshake MUST be rejected before a lease is issued if the worker's advertised protocol version is not in the supported range. The supported version range is tested as part of the rolling-upgrade acceptance criterion."*

---

### H-6 — Snapshot/replay: Snapshot high-water cursor and in-flight events

**Dimension:** Snapshots/replay  
**Severity:** 🔴 Blocking  
**Governing decisions:** AD-12  

**The pair:**

- **Unit A — Snapshot endpoint:** Produces a transactionally consistent snapshot of a job's current state and returns the highest committed event's cursor as `snapshot_cursor`. This is done inside a `REPEATABLE READ` transaction, which may exclude events committed after the snapshot transaction started but before it completed.
- **Unit B — SSE event subscription handler:** Receives `snapshot_cursor` from the client after snapshot delivery and begins streaming events strictly after that cursor. It uses `SELECT ... WHERE cursor > $snapshot_cursor ORDER BY cursor`.

**Incompatibility:** If a concurrent event commits at cursor 99 while the snapshot transaction is open at its read snapshot of cursor 98, the snapshot endpoint returns `snapshot_cursor=98`. The SSE handler streams from cursor 99 onward. But the snapshot state includes the effect of cursor 99 (because PostgreSQL `REPEATABLE READ` sees writes committed before the transaction started, and whether event 99 is visible depends on transaction start ordering). The client may receive a snapshot that reflects event 99's state change but never receives event 99 itself, or receive event 99 twice—depending on read-committed vs. repeatable-read isolation level choice. AD-12 says "returns one transactionally consistent snapshot and its high-water cursor, then events after that cursor" but does not specify the isolation level or the protocol for handling events that committed concurrently with snapshot generation.

**AD Tightening:** Amend AD-12 to add: *"The snapshot endpoint MUST execute both the state read and the high-water cursor read inside a single `SERIALIZABLE` (PostgreSQL) or equivalent isolation-level transaction, ensuring the returned cursor is the exact sequence boundary of the snapshot state. The SSE handler MUST begin streaming from `cursor >= snapshot_cursor` (inclusive), not `cursor > snapshot_cursor`, when the snapshot protocol is used, to prevent the gap. The persistence port interface defines which isolation level and boundary semantics are required."*

---

### H-7 — Auth/delegation: Worker callback authorization and tenant isolation

**Dimension:** Auth/delegation  
**Severity:** 🔴 Blocking  
**Governing decisions:** AD-5, AD-6, AD-4  

**The pair:**

- **Unit A — Worker Pod token minting (scheduler):** The scheduler mints a short-lived JWT for each worker Pod carrying `{job_id, attempt_id, tenant_id, fence_token}`. The JWT is signed with a single installation-wide HMAC key stored as a Kubernetes Secret in the control namespace.
- **Unit B — Control API worker callback middleware:** Validates the JWT signature using the installation-wide key and then trusts the `tenant_id` claim from the token to scope database queries.

**Incompatibility:** AD-6 says "API, scheduler, migration, and each tenant execution plane use distinct Kubernetes service accounts with least-privilege RBAC" but the worker protocol token is described as a JWT carrying a `tenant_id` claim validated by an installation-wide shared key. A compromised worker Pod for tenant A can forge a token with `tenant_id=B` (it knows the signing key because it was given the installation-wide secret—not a per-tenant key). The control API will accept the forged token and execute the callback in tenant B's context. Each unit obeys its AD literally: AD-6 is about service accounts (Kubernetes RBAC), not JWT signing key scoping.

**AD Tightening:** Amend AD-6 to add: *"Worker Pod authentication tokens MUST be either (a) per-tenant-signed using a key material that workers in one tenant namespace cannot obtain, or (b) issued as short-lived Kubernetes projected ServiceAccount tokens with audience restriction to the control API, where the control API verifies the token against the Kubernetes API server. The control API MUST NOT trust tenant identity from a JWT claim when the signing key is shared across tenant execution namespaces."*

---

### H-8 — Git resolution: `GitResolutionPort` and per-job workspace deletion ordering

**Dimension:** Git resolution  
**Severity:** Non-Blocking (data loss risk is bounded by the finalizer, but correctness is impacted)  
**Governing decisions:** AD-8, AD-14, AD-24  

**The pair:**

- **Unit A — GitResolutionPort (merge/PR path):** On resolution, pushes the commit from the private job workspace volume to the remote, then marks resolution as complete in the database.
- **Unit B — Job finalizer:** On `finalized` state entry (AD-14), captures workspace outcome (commit SHA + patch), then destroys the PVC, then decrements the object cache reference—regardless of whether resolution completed successfully.

**Incompatibility:** AD-8 says "Commit SHA plus patch or Git bundle is captured before workspace deletion" and AD-14 says "A finalizer idempotently captures outcomes... removes workspace resources." If Unit A's push to remote fails after partial state (e.g., the remote accepted the push but the database update timed out), Unit A retries and finds the remote ref already advanced, raising a non-fast-forward error. Unit B's finalizer has already destroyed the workspace PVC. The local bundle that would enable a recovery push is gone. Neither unit violated an AD: Unit A captured the SHA, Unit B destroyed the workspace after capture. But the SHA alone is insufficient for recovery if the push was partial and the workspace is gone.

**AD Tightening:** Amend AD-8 to add: *"Resolution capture MUST store a Git bundle (not just SHA and patch) in object storage BEFORE any push to the remote is attempted, and the bundle MUST remain available until the push is confirmed accepted by the remote and the job is finalized. The finalizer MUST NOT delete the workspace until the resolution port has either (a) confirmed remote push success and recorded it durably, or (b) recorded resolution failure and preserved the bundle for operator recovery."*

---

### H-9 — Multi-replica behavior: Scheduler replica split-brain on lease expiry detection

**Dimension:** Multi-replica behavior  
**Severity:** Non-Blocking (fencing prevents double execution, but interruption events may be emitted twice)  
**Governing decisions:** AD-13, AD-11  

**The pair:**

- **Unit A — Scheduler replica 1:** Detects lease expiry for job J (its heartbeat poll finds the lease past TTL). It commits an `interruption` event and begins recovery scheduling.
- **Unit B — Scheduler replica 2:** In the same 1-second heartbeat poll window, independently detects the same lease expiry and also commits an `interruption` event and begins recovery.

**Incompatibility:** AD-13 says "Expiry emits an interruption event and enters explicit recovery; it never silently starts a duplicate attempt." The fencing token prevents two workers from committing state, but the AD does not specify how two scheduler replicas coordinate who emits the interruption event. The `FOR UPDATE SKIP LOCKED` queue claim is for the running-to-leased transition; there is no specified lock for the expiry-detection-to-interruption-event transition. Both replicas obey AD-13 and AD-11 (each commits one atomic mutation+event), but two `interruption` events are emitted for job J. Downstream event consumers and SSE clients receive duplicate lifecycle events that violate the canonical job state machine.

**AD Tightening:** Amend AD-13 to add: *"Lease expiry detection and interruption event emission MUST be performed under a `SELECT ... FOR UPDATE` lock on the lease row (or equivalent single-writer coordination) so that exactly one scheduler replica commits the interruption event and transitions the job to `interrupted`. A scheduler replica that loses the lock on expiry detection MUST NOT emit an event."*

---

### H-10 — Export/import: Storage cursor remapping and replay window validity

**Dimension:** Export/import  
**Severity:** Non-Blocking  
**Governing decisions:** AD-23, AD-12  

**The pair:**

- **Unit A — Export service:** Exports all TraceForge events for a job with their original `global_cursor` values (which are PostgreSQL bigserial integers in the source instance). AD-23 says "storage cursors... are remapped" but the export manifest includes cursors in the JSONL to allow the importer to reconstruct order.
- **Unit B — Import service:** Imports events and assigns new `global_cursor` values using the target instance's cursor space. It preserves `per_job_sequence` (AD-23: "Canonical UUIDs and per-job sequence survive import"). The SSE replay handler uses `global_cursor` for the replay window, not `per_job_sequence`.

**Incompatibility:** After import, a client that reconnects with a `Last-Event-ID` from the source instance's cursor space (stored in their browser or application) will either (a) be told the cursor is not in the replay window and receive a full snapshot, or (b) accidentally align to the wrong position in the target's cursor space. AD-23 says "storage cursors... are remapped" without defining whether the remap is deterministic, what a client connecting with a pre-import cursor receives, or whether the import must emit a "cursor discontinuity" event. AD-12's replay/snapshot protocol is not cross-instance aware.

**AD Tightening:** Amend AD-23 to add: *"Import MUST insert a synthetic `import.cursor_discontinuity` event as the first event after the imported batch for each job, carrying the source instance ID and the original high-water cursor. SSE handlers receiving a cursor from before the discontinuity event MUST treat it as outside the replay window and fall back to snapshot. Clients MUST NOT assume cursor portability across instances."*

---

## Cross-Cutting Observations

### Missing: Worker protocol message schema is never formally specified

AD-3 names the worker protocol and its required fields `(job_id, attempt_id, execution_locality, fence_token)` but no AD binds the full message schema, versioning format, or backward-compatibility rules beyond "versioned." H-5 is one consequence; others include: unknown fields in worker events, message ordering guarantees between concurrent worker-emitted events, and whether the worker protocol carries TraceForge envelopes or a proprietary format. The spine's "Deferred" section does not list this as deferred—it is simply absent.

**Recommended AD addition:** A new AD (or extension to AD-3) should specify: (1) the worker protocol's version format, (2) the complete required message types and their mandatory fields, (3) the rule that control API and worker must negotiate protocol version before any lease is issued, and (4) that worker-side event payloads are TraceForge envelopes or explicitly mapped to canonical events at the control-API boundary.

---

### Missing: Idempotency key scope for worker writes is underspecified

The Consistency Conventions table says: *"worker writes key by attempt/event_id."* But AD-11 requires state-plus-event atomic commits. If a worker emits event E1 and the response is lost, it retransmits E1 with the same idempotency key. The control API's idempotency store must span both the event table (for deduplication) and the state table (for mutation replay). No AD binds whether the idempotency store is in the same transaction as the unit of work, whether it is per-tenant or installation-wide, or its TTL. A separate idempotency table outside the unit of work creates a two-phase commit problem identical to H-2.

**Recommended AD extension:** Extend AD-11 to specify that the idempotency key check and record are inside the same unit-of-work transaction as the state mutation and event append.

---

## Severity Summary

| ID | Dimension | Severity | AD(s) to Tighten |
|---|---|---|---|
| H-1 | Shared-data shape (cursor type) | 🔴 Blocking | AD-11, AD-12 |
| H-2 | Data ownership (artifact split-brain) | 🔴 Blocking | AD-10, AD-16 |
| H-3 | State/event mutation (approval race) | 🔴 Blocking | AD-11, AD-13 |
| H-4 | Scheduling fence (stale token acceptance) | 🔴 Blocking | AD-13 |
| H-5 | Worker protocol (version boundary) | 🔴 Blocking | AD-22 |
| H-6 | Snapshot/replay (isolation gap) | 🔴 Blocking | AD-12 |
| H-7 | Auth/delegation (JWT tenant forgery) | 🔴 Blocking | AD-6 |
| H-8 | Git resolution (bundle-before-push ordering) | 🟡 Non-Blocking | AD-8, AD-14 |
| H-9 | Multi-replica (duplicate interruption events) | 🟡 Non-Blocking | AD-13, AD-11 |
| H-10 | Export/import (cursor discontinuity) | 🟡 Non-Blocking | AD-23, AD-12 |
| Cross-1 | Worker protocol schema absence | 🟡 Non-Blocking | AD-3, new AD |
| Cross-2 | Idempotency key in unit-of-work | 🟡 Non-Blocking | AD-11 |
