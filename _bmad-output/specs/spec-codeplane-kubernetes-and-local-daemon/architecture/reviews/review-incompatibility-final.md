# Adversarial Incompatibility Review (Fresh Pass) — ARCHITECTURE-SPINE.md

**Reviewer:** Critic agent (devil's advocate)
**Date:** 2026-08-05
**Target:** `architecture/ARCHITECTURE-SPINE.md` (32 ADs, AC-1..AC-16, Capability → Architecture Map, Backup/Retention, Scheduling state diagram)
**Method:** Construct pairs of independently built implementation units one level below the spine, each obeying every applicable AD *literally*, that still diverge incompatibly. Every pair is checked against the current 32-AD text (not a prior draft) and against SPEC.md / mode-requirements.md / brownfield-constraints.md. Implementation detail that cannot cause architectural divergence is excluded.

**Relationship to prior reviews:** `review-incompatibility.md` (10 pairs + 2 cross-cutting notes against an earlier draft) is now largely closed: its cursor-opacity gap (H-1) is closed by AD-12's "opaque authenticated UTF-8 token" language; its fence-validation gap (H-4) is closed by AD-13's "byte-for-byte... under lock... regardless of attempt-row presence"; its worker-identity/JWT-forgery gap (H-7) is closed by AD-29; its snapshot/cursor race (H-6) is closed by AD-12's single-transaction snapshot+cursor read; its scheduler split-brain (H-9) is closed by AD-13's "one transactional winner across scheduler replicas"; its Git bundle-before-push gap (H-8) is closed by AD-8's recovery-bundle clause; its idempotency-in-transaction gap (Cross-2) is closed by AD-11. This pass does not re-litigate those. It looks for *new* holes the tightened spine has not yet closed.

---

## Summary Verdict

**CONDITIONAL PASS.** The spine remains architecturally coherent and its previous incompatibility class (H-1..H-10) is resolved. This fresh pass finds **12 new incompatibility pairs**: **7 Blocking** (silent state/data corruption, security-relevant scheduling starvation or trust bypass, or an untested core-boundary regression path — none of which violate any AD as written) and **5 Non-Blocking** (observable divergence, degraded UX, or bounded-scope loss, correctable before release gates). The most consequential class is **acceptance traceability**: AD-3 — the control/execution-plane boundary itself — is never named as a governing decision in any AC row, so AD-28's blanket CI gate cannot be relied on to catch a regression in the one rule the rest of the security model assumes holds.

---

## Incompatibility Pairs

---

### FR-1 — Acceptance traceability: AD-3 is untested by name

**Dimension:** Acceptance traceability
**Severity:** 🔴 Blocking
**Governing decisions:** AD-3, AD-28, AC-1..AC-16 (all)

**The pair:**

- **Unit A — Worker-protocol implementer (CAP-4/CAP-15/CAP-18):** Builds AD-3's negotiated-version handshake and required message fields, and considers the feature "acceptance-gated" because AD-28 says a release "cannot claim either mode until every applicable acceptance criterion... pass in CI." Since AD-28 does not require authoring a new AC, Unit A ships once the *existing* suite (AC-4, AC-5, AC-13) is green.
- **Unit B — Release-gate automation (AD-28 enforcement):** Implements the gate literally by iterating the AC table's "Governing decisions" column. AD-3 appears in zero AC rows (AC-4 tests isolation boundaries via AD-7/AD-8/AD-24/AD-32; AC-5 tests mutual-auth via AD-29; AC-13 tests N/N-1 functional compatibility via AD-21/AD-22 — none tests "handshake rejects unsupported protocol version *before lease issuance*," AD-3's own operative clause).

**Incompatibility:** Both units are fully AD-28-compliant. A regression that lets a scheduler issue a lease to a worker whose protocol version was never negotiated (or negotiated but not enforced pre-lease) — a literal violation of AD-3's own sentence — has no AC row that would fail in CI, because AD-28's blanket claim delegates "applicable" entirely to the AC table's own citations and nothing independently verifies that every AD has at least one governing AC. AD-26 (migration phases/conformance gating) has the same omission. The gate can be green while the control/execution boundary that CAP-15's entire threat model rests on is untested.

**AD Tightening:** Amend AD-28 to add: *"Every AD 1 through 32 MUST appear in the 'Governing decisions' column of at least one AC row or the Capability → Architecture Map; an AD covered only by the Capability map (not by a testable AC) MUST be flagged in the map as 'acceptance-gap' until a corresponding AC exists. CI validates this coverage mapping itself as a pre-condition of the AD-28 gate, not just the enumerated ACs."* Add an explicit AC (or amend AC-13) covering: worker presents an unsupported/negotiated-incorrectly protocol version and is rejected before any lease is issued.

---

### FR-2 — Tenant enforcement vs. scheduling: RLS "maintenance-only" bypass collides with inherently cross-tenant fair queuing

**Dimension:** Tenant enforcement / scheduling fences
**Severity:** 🔴 Blocking
**Governing decisions:** AD-30, AD-13

**The pair:**

- **Unit A — RLS policy author (AD-30):** Implements row-level security on `tenant_id`-owned tables and, per AD-30's literal text ("cross-tenant maintenance uses separate least-privilege roles and immutable audit"), grants RLS-bypass only to a narrowly-scoped `maintenance` role used by retention sweeps and admin tooling. The normal application role used by request-serving and scheduling code paths gets no bypass, since scheduling is not "maintenance."
- **Unit B — Scheduler claim-query author (AD-13):** Implements "weighted fair by tenant, then repository, then FIFO age," which requires reading queued rows across *all* tenants in one query to rank candidates before issuing a `FOR UPDATE SKIP LOCKED` claim. Unit B runs this query as the standard application role, per AD-30's separate rule that "repository contracts require explicit tenant context... and fail closed... when context is absent" — but the scheduler's tenant context is fundamentally not singular per query.

**Incompatibility:** Neither unit violates its AD in isolation. In production, Unit A's RLS policy blocks Unit B's cross-tenant ranking query (rows for every tenant but the request's bound context vanish), silently collapsing "weighted fair" into "only the current transaction's tenant is ever selected" — starving all other tenants — or, if Unit B's author instead grants the scheduler role RLS bypass to make the AD-13 query work at all, the scheduler becomes a de facto cross-tenant-bypass role running on every scheduling tick (not "maintenance"), with none of AD-30's audit requirement attached, quietly reintroducing the exact split-brain-ownership class AD-30 exists to prevent. AD-30 never states whether the scheduler's ranking read is "maintenance" or ordinary tenant-scoped access, and AD-13 never states how tenant-scoped RLS composes with a cross-tenant ranking query.

**AD Tightening:** Amend AD-30 to add: *"The scheduler's cross-tenant candidate-ranking read is a declared, audited exception distinct from ad hoc maintenance access: it uses a dedicated `scheduler` role, scoped to SELECT on queue-ranking columns only (no other tenant data), audited at a coarse (not per-row) grain, and is the only application-tier role permitted a blanket RLS bypass. All other cross-tenant access remains the AD-30 maintenance-role path."*

---

### FR-3 — Shared data shape: artifact checksum basis is unspecified

**Dimension:** Shared data shapes/owners
**Severity:** 🔴 Blocking
**Governing decisions:** AD-10, AD-23, AD-31, AC-12, AC-14

**The pair:**

- **Unit A — Artifact ingestion adapter (AD-10 staged→available protocol):** Computes a SHA-256 digest over the plaintext artifact bytes *before* upload and stores it as the row's "content hash," satisfying "metadata cannot report a blob available until checksum-confirmed object commit."
- **Unit B — Export/restore-drill validator (AC-12, AC-14):** Built independently, treats the object store's returned ETag (ci S3 multipart uploads, an MD5-of-part-hashes construction, not a plaintext content hash) as the authoritative "checksum" because it is the value the object-store adapter already has on hand at commit time, and AD-31's algorithm-identifier language ("export schema fixes the... algorithm identifier") is written for the *event* hash chain, not artifact blobs, leaving no adapter contract for which digest artifacts use.

**Incompatibility:** AD-10's "checksum-confirmed object commit" and AC-14's "collision is idempotent only when content hashes match" are each satisfied literally by a unit that never agreed with the other on hash input (plaintext vs. multipart ETag) or algorithm. Cross-instance import of a legitimately identical artifact fails the "content hashes match" idempotency test and is treated as a conflicting collision (AD-23: "otherwise import fails atomically"), or — worse — the restore drill's checksum validation (AC-12) silently passes because it only compares ETags against themselves rather than against a content-addressed value, so a bit-flip introduced by an intermediate transform (e.g., server-side encryption re-wrap) would never be caught.

**AD Tightening:** Amend AD-10 (or AD-31, extended to cover blobs) to add: *"Artifact content hash is SHA-256 over plaintext bytes prior to any storage-side transform, computed by the ingesting adapter and never derived from an object-store-native ETag or ciphertext. This value, not any storage-provider digest, is what AD-23 import collision detection and AC-12 restore validation compare."*

---

### FR-4 — State mutation: AD-11's row lock is scoped to lifecycle transitions, not to the whole row

**Dimension:** State mutation
**Severity:** 🟡 Non-Blocking (bounded to non-lifecycle columns; no lifecycle/security field is affected because AD-5 already locks delegation fields explicitly)
**Governing decisions:** AD-11, AD-16

**The pair:**

- **Unit A — RetentionService:** Loads a job entity, sets `retention_class` (and, on legal hold, a hold flag), and commits — a plain ORM read-modify-write, since AD-11's "current-state validation under the required row lock" is written for the job's *lifecycle* transition, and RetentionService performs no lifecycle transition.
- **Unit B — RunnerService (state-machine transition):** Independently loads the same job row inside its own AD-11 unit-of-work transaction, mutates the lifecycle `status` column, and — depending on the ORM's flush strategy — re-persists the in-memory object's other attributes, including whatever stale `retention_class`/hold value it read at the start of its transaction.

**Incompatibility:** AD-11 pins locking and atomicity for *state transitions*, but the same row also carries columns owned by other services (retention class, legal hold, quota counters) with no stated locking discipline. If Unit A's write interleaves inside Unit B's longer-running transition transaction, Unit B's commit can silently overwrite Unit A's `retention_class`/hold update with a stale value — a lost update that is legal-hold-relevant (AD-16: "Legal hold prevents deletion") without either unit violating AD-11 as written, since AD-11 never claims ownership of non-lifecycle columns on the same row.

**AD Tightening:** Amend AD-11 to add: *"Any column on a state-machine-owned row, not only the lifecycle status column, is mutated only inside a unit-of-work transaction that re-reads the row under the same required lock immediately before writing; partial-attribute ORM patches (not whole-object overwrite) are required for non-lifecycle columns owned by other services."*

---

### FR-5 — Scheduling fences: "monotonically increasing fencing token" does not say whether renewal mints a new one

**Dimension:** Scheduling/fences
**Severity:** 🔴 Blocking
**Governing decisions:** AD-13, AD-29

**The pair:**

- **Unit A — Lease renewal service:** Reads AD-13's "claims create a renewable lease and monotonically increasing fencing token" as meaning each heartbeat renewal *also* advances the fencing token (defense against a renewal race where a slow, previously-expired holder reappears). It stores the new token on the lease row at every successful heartbeat.
- **Unit B — AD-29 worker-identity binding:** Mints the worker's short-lived, audience-restricted identity *once*, at attempt start, binding "current lease/fence" as of that moment — since AD-29 describes binding at issuance and nothing requires re-minting a signed identity on every heartbeat.

**Incompatibility:** After the first successful renewal, the lease row's fence (Unit A) has advanced past the value embedded in the worker's still-valid, still-current identity token (Unit B). Every subsequent non-heartbeat callback (checkpoint, terminal data, artifact-upload notice) from the *legitimate, sole* attempt holder now fails AD-13's mandatory byte-for-byte fence comparison — indistinguishable, from the control API's point of view, from a genuine stale/zombie writer rejection. AD-13 never states whether the fencing token is per-claim (fixed for the attempt's lifetime, only its expiry extends) or per-renewal (bumped on every heartbeat); each unit picked a different, literally-compliant reading.

**AD Tightening:** Amend AD-13 to add: *"The fencing token is fixed for the lifetime of one claimed attempt; renewal extends the lease's expiry timestamp only and never changes the fencing token value. A new fencing token is minted only when a new claim (a different attempt) is issued for the job."*

---

### FR-6 — Worker authentication: "configured control-plane identity" is ambiguous between the service and the specific replica

**Dimension:** Worker authentication/protocol / multi-replica behavior
**Severity:** 🔴 Blocking
**Governing decisions:** AD-29, AD-21

**The pair:**

- **Unit A — Pod-spec templating (scheduler/worker-plane team):** Configures each worker Pod with the control API's stable Service-level identity (a rotating TLS serving certificate fronted by the ClusterIP), consistent with AD-21's "at least two API replicas" behind one Service, since no single replica is addressable by design.
- **Unit B — Worker mutual-auth handshake implementer (AD-29: "the worker authenticates the configured control-plane identity before sending credentials, events, terminal, or preview traffic"):** Implements this literally by pinning the specific TLS certificate/serving key observed during the *first* handshake for the life of the attempt, to defend against a spoofed peer — a defensible, literal reading of "authenticates the configured... identity."

**Incompatibility:** AD-21 assumes ≥2 replicas behind one Service is routine and transparent to callers; AD-29 assumes the worker verifies "the configured control-plane identity" without saying whether that identity is the rotating-cert Service (replica-agnostic) or the specific instance pinned at handshake (replica-specific). Under Unit B's reading, a routine TLS certificate rotation (an operator-owned, expected event per Deferred) or an ordinary rolling replica restart invalidates every in-flight worker's pinned trust, causing mass worker-to-control-plane authentication failure across the fleet — with neither AD-21 nor AD-29 violated, since AD-29 never states the identity is Service-scoped rather than replica-scoped.

**AD Tightening:** Amend AD-29 to add: *"'Configured control-plane identity' is the stable Service-level identity (its trust anchor, not a pinned leaf certificate or replica instance); the worker MUST re-validate against the current trust anchor on every connection rather than pinning a specific handshake's certificate, so that certificate rotation and replica restart under AD-21 never require re-establishing worker trust out of band."*

---

### FR-7 — Replay/cursors/snapshots: the replay window and the retention window are two different, unreconciled boundaries

**Dimension:** Replay/cursors/snapshots
**Severity:** 🟡 Non-Blocking (AD-12's snapshot fallback is explicitly permitted; the gap is fidelity, not correctness)
**Governing decisions:** AD-12, AD-16

**The pair:**

- **Unit A — Live-delivery/outbox implementation (AD-12):** Implements the at-least-once delivery path via a short-retention outbox/notify table, pruned frequently for performance — legitimate, since AD-12 only requires that a cursor "outside the replay window" fall back to snapshot, without defining how long the replay window is.
- **Unit B — Long-disconnected consumer (audit UI, terminal client after laptop sleep):** Assumes, per AD-16's "365 days for canonical lifecycle events," that any event still inside that 365-day retention window is still reconstructable event-by-event via cursor replay, since the canonical event table itself (not the outbox) still holds the row.

**Incompatibility:** AD-12's snapshot fallback returns *current state*, not a historical event backfill. A consumer whose cursor falls between Unit A's short outbox-replay window and AD-16's much longer 365-day retention window gets a state snapshot with no path to reconstruct the intervening event-by-event history it expected to still be able to replay, even though every event it wants is still durably stored and not yet subject to deletion. Neither AD-12 nor AD-16 is violated; "retained" and "replayable" are silently treated as synonyms by Unit B and are not by Unit A.

**AD Tightening:** Amend AD-12 to add: *"The replay window is a distinct, separately documented bound from AD-16 retention; a consumer resuming inside the retention window but outside the replay window receives the current-state snapshot plus an explicit `replay_window_exceeded` indicator, not a silent equivalence between 'retained' and 'individually replayable.'"*

---

### FR-8 — Artifact/cache/Git lifecycle: in-place cache promotion can corrupt a concurrently mounted read-only workspace

**Dimension:** Artifact/cache/Git lifecycles
**Severity:** 🔴 Blocking
**Governing decisions:** AD-8

**The pair:**

- **Unit A — Workspace acquisition adapter:** Bind-mounts the tenant-scoped bare-object cache read-only into an in-flight job's private workspace, per AD-8's "jobs mount cache content read-only," and holds that mount open for the duration of clone/checkout materialization.
- **Unit B — Trusted cache-promotion adapter:** Implements AD-8's "verifies registered remote identity and Git object integrity before atomic promotion" as an in-place update of the *same* bare-repository path — `git fetch` plus repack/GC into the existing directory — reasoning that "atomic promotion" refers to the integrity check gating the update, not necessarily to a copy-on-write directory swap.

**Incompatibility:** AD-8 requires jobs to mount the cache read-only and requires promotion to be integrity-verified, but never specifies that promotion must be a new-path/rename-swap rather than an in-place repack of the currently-mounted path. A concurrent Git repack/GC rewriting or pruning loose objects in the same directory Unit A is mid-read from (cloning/checking out) can corrupt or fail that in-flight job's workspace materialization non-atomically, even though the cache was never writable *to the job* (AD-8 satisfied) and the update was integrity-verified before being applied (AD-8 satisfied).

**AD Tightening:** Amend AD-8 to add: *"Atomic promotion MUST write verified content to a new cache generation path and repoint future acquisitions to it via rename/symlink swap; the previous generation remains immutable and unmodified until its last referencing job workspace is released, so no in-place repack or GC ever touches a path an active job has bind-mounted."*

---

### FR-9 — Export/import/hash chains: incremental re-import and schema evolution are not cross-verified against the target's existing chain

**Dimension:** Export/import/signatures/hash chains / upgrades
**Severity:** 🔴 Blocking
**Governing decisions:** AD-23, AD-31, AD-22

**The pair:**

- **Unit A — Import service (AD-23 collision handling):** Treats "collision" as event-UUID presence: for a job partially imported earlier (e.g., a prior import attempt covered sequence 1-50), it accepts a new manifest's events 51-120 as new appends, verifying only that each new event's own `prior_hash` chains from the *previous event in the same manifest* — internally self-consistent, satisfying AD-31's "verify the complete chain."
- **Unit B — Export service after an AD-22 contract migration:** Ships a later export whose canonicalization version was bumped (a migration added a new required provenance field), so events 51-120's chain, while internally self-consistent under the new version, was never cross-checked by Unit A against the *already-stored, under-the-old-version* hash of event 50 sitting in the target database.

**Incompatibility:** AD-31 requires "sequence allocation, prior-hash validation, and append are one AD-11 transaction" and that replay/import/restore "verify the complete chain and surface failure without silently repairing history," but never states whether "the complete chain" means (a) internal self-consistency of the incoming manifest, or (b) continuity against the target's previously-stored chain state at the join point. Unit A's literal reading (a) lets a manifest whose first `prior_hash` does not actually match the target's stored hash for event 50 be accepted silently — a hash-chain integrity bypass on exactly the boundary (incremental import across a canonicalization-version bump) AD-31 exists to close, while both units are individually AD-23/AD-31/AD-22-compliant.

**AD Tightening:** Amend AD-31 to add: *"On any import into a job with pre-existing canonical events, the importer MUST verify the incoming manifest's first `prior_hash` equals the target's already-stored hash of the immediately preceding event before accepting any new event; per-event canonicalization version is tracked and stored per event (not assumed globally per manifest), and verification recomputes each historical event's hash using the canonicalization version recorded for that event, never the current/latest version."*

---

### FR-10 — Local trust/backup: SQLite snapshot and the `~/.codeplane` artifact tree can be captured at incoherent instants, with no post-restore reconciliation step

**Dimension:** Local trust/backup
**Severity:** 🟡 Non-Blocking (local mode already disclaims HA/RTO-RPO guarantees; this is a gap in the *documented* recovery procedure, not a violation of a stated guarantee)
**Governing decisions:** AD-10, AD-17, backup section item 6

**The pair:**

- **Unit A — SQLite backup component:** Implements backup item 6 exactly: online-backup API from one consistent snapshot including required WAL state (or clean-shutdown + WAL checkpoint).
- **Unit B — Artifact-tree backup component:** Runs its own filesystem-level capture of `~/.codeplane` blobs immediately before or after Unit A's operation, since backup item 6's enforcement detail (online-backup API / WAL checkpoint) is written for the database specifically and nothing coordinates the two captures under one pause.

**Incompatibility:** AD-16's retention/tombstone sweep runs continuously in the same local daemon process, independent of any external backup operation. If it tombstones and deletes an artifact between Unit A's DB snapshot instant and Unit B's filesystem snapshot instant, the resulting backup set is internally incoherent (DB says available as of T; filesystem says deleted as of T+Δ), and — unlike the Kubernetes restore drill, which explicitly "validates schema, event hashes, artifact checksums, and high-water cursors" before enabling scheduling — no equivalent verification step is mandated for a restored local backup. Neither unit violates the letter of item 6, which only forbids "copying a live database or `~/.codeplane` tree," not the coherence of two otherwise-compliant point-in-time captures taken moments apart.

**AD Tightening:** Amend the backup section to add: *"Local backup captures the SQLite snapshot and the `~/.codeplane` artifact tree under one held pause of the retention/tombstone sweep, or records the exact instant of each capture so restore can reconcile them; restore runs the same missing-blob-becomes-degraded-artifact check AD-10 requires for Kubernetes before the daemon resumes scheduling."*

---

### FR-11 — Multi-replica behavior: terminal session continuity assumes opposite ownership of trust state

**Dimension:** Multi-replica behavior
**Severity:** 🟡 Non-Blocking (UX/availability degradation on terminals only; no data loss, no cross-tenant exposure)
**Governing decisions:** AD-19, AD-29, AD-21

**The pair:**

- **Unit A — Terminal WebSocket proxy (CAP-10):** Implements reconnect by opening a *new* WebSocket to the same worker Pod (resolved via the job's scheduling record), treating the worker-side PTY as the sole resumable state — since AD-19 says only that "terminals bind to one authorized job worker," which the proxy reads as a worker-side, not replica-side, binding.
- **Unit B — Worker-side terminal handler:** Under FR-6's replica-pinned reading of AD-29 (before that finding's tightening lands), treats the loss of its original handshake replica as loss of a trusted control plane and tears down the PTY rather than awaiting a fresh handshake from any valid replica.

**Incompatibility:** An ordinary rolling API-replica restart (a normal AD-21 multi-replica event, not a failure) is, under Unit A's assumption, fully transparent to the terminal session; under Unit B's assumption, it is fatal to the session. Neither AD-19 nor AD-29 states whether terminal/PTY lifecycle is scoped to the worker's connection to *a* replica or to the control-plane *service*, so the two independently built halves of one feature give the operator inconsistent behavior depending on which replica happens to restart first.

**AD Tightening:** Amend AD-19 to add: *"A terminal session's liveness is bound to the worker Pod and the job's scheduling record, never to the specific API replica that proxied or handshake-verified the connection; an API replica restart under AD-21 MUST be transparent to an in-progress terminal session once FR-6's control-plane identity fix is applied."*

---

### FR-12 — Upgrades / worker protocol: non-sticky routing plus overlapping rolling upgrades can permanently orphan a compliant worker

**Dimension:** Upgrades / worker authentication-protocol / multi-replica behavior
**Severity:** 🔴 Blocking
**Governing decisions:** AD-22, AD-21, AD-3

**The pair:**

- **Unit A — Worker Pod:** Negotiates protocol version N with whichever API replica handles its initial handshake, per AD-3, and is issued a lease. It has no guarantee, and AD-19/AD-21 impose none, that subsequent callbacks route back to that same replica (one ClusterIP, no session-affinity requirement anywhere in the spine).
- **Unit B — A later-deployed API replica:** Already running the *next* rolling upgrade's code, supporting only its own N+1/N window per AD-22 ("Control API and worker protocol support release N and N-1... in the same running binary"). If a second rolling upgrade begins before all N-1-negotiated workers have drained — nothing in AD-22 bounds how long an upgrade may take relative to worker attempt duration — Unit B correctly rejects a callback from a worker two versions behind its own supported range.

**Incompatibility:** Each replica enforces its own N/N-1 window correctly and independently (AD-22 satisfied by each), and neither AD-19 nor AD-21 requires sticky routing back to a worker's issuing replica. The compound effect is a legitimately-leased, protocol-compliant worker whose callbacks are rejected by whichever replica it happens to reach post-upgrade, with no path to reconnect to a replica still supporting its negotiated version — an operationally routine (not adversarial) event orphaning an in-flight job. AD-22's compatibility gate is a per-replica guarantee; it is never stated as a fleet-wide guarantee across an arbitrary number of overlapping rolling upgrades.

**AD Tightening:** Amend AD-22 to add: *"A worker's negotiated protocol version remains supported by every control-plane replica for the lifetime of its attempt; a second rolling upgrade MUST NOT begin while any active attempt was negotiated at a version older than the currently-deploying replicas' N-1 floor. The pre-upgrade Job (already required by AD-22) checks for in-flight attempts below the new floor and blocks the rollout until they drain or are explicitly interrupted."*

---

## Cross-Cutting Observations

### Observation 1 — AD-26 shares FR-1's traceability gap

Like AD-3, AD-26 (additive/conformance-gated migration phases) is never cited as a "Governing decision" in any AC row; it is only referenced narratively in the Migration and Compatibility Strategy table. The same AD-28 tightening in FR-1 closes this by requiring every AD to appear in at least one AC or be explicitly flagged as an acceptance gap.

### Observation 2 — Per-event canonicalization version is the root cause underlying FR-9

AD-31 treats "canonicalization version" as an export-manifest-level property ("the export schema fixes the... canonicalization version"). Once AD-22 contract migrations are expected to change canonical encoding over a job's lifetime (the spine explicitly anticipates schema evolution), canonicalization version needs to be a per-event, stored property from the outset, not something inferred from whichever migration happened to be current when a manifest was produced. This single change would also make the fix in FR-9 straightforward to implement.

---

## Severity Summary

| ID | Dimension | Severity | AD(s) to Tighten |
|---|---|---|---|
| FR-1 | Acceptance traceability (AD-3 untested) | 🔴 Blocking | AD-28, AC table |
| FR-2 | Tenant enforcement vs. scheduling (RLS bypass) | 🔴 Blocking | AD-30, AD-13 |
| FR-3 | Shared data shape (artifact checksum basis) | 🔴 Blocking | AD-10, AD-31 |
| FR-4 | State mutation (row-lock scope / lost update) | 🟡 Non-Blocking | AD-11 |
| FR-5 | Scheduling fences (fence-renewal ambiguity) | 🔴 Blocking | AD-13 |
| FR-6 | Worker authentication (replica vs. service identity) | 🔴 Blocking | AD-29 |
| FR-7 | Replay/cursors/snapshots (replay window vs. retention) | 🟡 Non-Blocking | AD-12 |
| FR-8 | Artifact/cache/Git lifecycle (in-place repack corruption) | 🔴 Blocking | AD-8 |
| FR-9 | Export/import/hash chains (incremental re-import continuity) | 🔴 Blocking | AD-31, AD-23 |
| FR-10 | Local trust/backup (DB/artifact snapshot incoherence) | 🟡 Non-Blocking | AD-10, backup §6 |
| FR-11 | Multi-replica (terminal session continuity) | 🟡 Non-Blocking | AD-19 |
| FR-12 | Upgrades (non-sticky routing orphans workers) | 🔴 Blocking | AD-22 |
| Obs-1 | Acceptance traceability (AD-26 untested) | 🟡 Non-Blocking | AD-28, AC table |
| Obs-2 | Hash-chain versioning granularity | — (root cause of FR-9) | AD-31 |
