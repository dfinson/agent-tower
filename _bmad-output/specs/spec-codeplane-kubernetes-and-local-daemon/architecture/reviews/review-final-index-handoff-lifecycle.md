# Final Review — AD-36/AD-37 Lifecycle, Data-Loss, and Concurrency

**Scope:** ARCHITECTURE-SPINE.md AD-36/AD-37 index and handoff lifecycle  
**Reviewer:** Copilot (automated, context-separated)  
**Date:** 2026-08-05  
**Verdict:** PASS — all prior critical and high findings from `review-lifecycle-data-loss-concurrency-index-handoff.md` are closed in the current spine text. No new critical or high risks identified within the AD-36/AD-37 ownership-gap scope. Two residual medium observations noted.

---

## Prior Critical Findings — Closure Status

### C-1 — History append / projection update crash window (AD-11, AD-31, AD-34)
**Status: CLOSED.** AD-12 now specifies bounded projection as "sole convergent current-state snapshot" naming "durable sequence/hash plus the expected participant UID/resourceVersion/operation vector." AD-31 specifies "history ahead repairs forward; projection ahead or hash mismatch fails closed." The memlog records explicit decisions for projection repair and participant-vector assembly. SSE convergence is addressed by replay-from-last-emitted-sequence semantics in AD-12.

### C-2 — Storage gateway takeover two-writer window (AD-34)
**Status: CLOSED.** AD-34 now states: "Takeover keeps the shard unavailable until the old gateway Pod is terminated, attachment is detached or otherwise CSI-fenced, exclusive replacement mount is proven, on-PVC head/epoch integrity verifies, and the durable head epoch advances atomically before readiness. Same-node overlap is forbidden; if the CSI profile cannot prove exclusion, failover stops rather than risk two writers." The memlog final gate fix confirms callback-epoch fsynced verification before readiness.

### C-3 — Handoff package selection ABA race (AD-13, AD-37)
**Status: CLOSED.** AD-37 now specifies: selection is "CAS-binds package ID/hash, selecting attempt UID, and claim generation before credentials and materialization. A second active selection for the same lineage fails closed unless an explicit fan-out policy permits it or a descendant package binds prior selection provenance." Memlog decision (line 140) confirms `packageSequence` monotonic allocation through HistoryPort and CAS-bound attempt UID/claim generation.

### C-4 — Backup epoch quiesce without timeout (AD-17, Backup §1–§6)
**Status: CLOSED.** Backup §1 now states: "a `CodePlaneBackupEpoch` sets a generation-fenced mutation/scheduling barrier for its tenant with a required absolute UTC deadline… Any controller observing an expired non-captured epoch transitions it to `Failed`, releases the barrier, and preserves the audit record." Memlog decision (line 143) confirms explicit deadline and fail-open on expiry.

---

## Prior High Findings — Closure Status

### H-1 — Index generation GC race with late lease acquisition (AD-36)
**Status: CLOSED.** AD-36 now states: "Lease acquisition and transition to `GarbageCollecting` are competing resourceVersion-preconditioned writes; `GarbageCollecting` rejects new leases, and physical deletion rechecks zero references/leases, drains in-flight queries, and for overlays waits for owning workspace deletion or retained-outcome detachment. Failed deletion leaves `RebuildRequired`, never a false tombstone." Memlog decision (line 139) confirms this exact fix.

### H-2 — Repository-context three-way merge non-determinism (AD-37)
**Status: CLOSED.** AD-37 now specifies: "Auto-merge is allowed only for distinct canonical relative paths or distinct append-only record IDs; divergent bytes for the same path/record ID preserve both candidates and set `Conflict`; sibling ordering is content hash then generation ID." Memlog decision (line 142) confirms conflict detection, deterministic sibling ordering, and explicit resolution through a preconditioned `resolve` operation.

### H-3 — Import session crash leaves resources inert (AD-23)
**Status: CLOSED.** AD-23 now states: "Recovery resumes the same session; compensation removes only resources proven created by it." The CRD table shows `CodePlaneImportSession` with `Staged`, `Verified`, `Committed` phases and 30-day retention. Memlog decision (line 143) confirms backup/import deadline validation. The spine does not explicitly say "on startup, list non-terminal sessions and resume," but the reconciler model (AD-11 watch/relist/enqueue) combined with the stated "recovery resumes the same session" makes this implicit in the Kubernetes reconciliation pattern. Accepted as structurally addressed.

### H-4 — Finalizer ordering gap: workspace deletion vs. handoff/context publication (AD-14, AD-37)
**Status: CLOSED.** AD-14 now explicitly lists: "commit and integrity-verify pending handoff-package and repository-context generations; commit outcome/history, `context.handoff`, terminal publication state, and retention tombstone; revoke attempt credentials; release repository/ref/index ownership; finalize retained storage; delete workspace/Pod." Memlog decision (line 141) adds: "predecessor terminal handoff and repository-context publication… is recorded in the job projection before a successor claim may materialize context or receive credentials. Cleanup cannot revoke access or delete workspace before publication reaches that durable state."

### H-5 — Operation idempotency window expiry during backup quiesce (AD-11)
**Status: CLOSED.** Backup §1 now states: "each accepted operation must reach committed projection or an enumerated recovery-safe parked phase with participants, preconditions, and next action durable before capture." Combined with AD-11's durable `CodePlaneOperation` ledger that preserves original results, parked operations are structurally preserved through the epoch. The explicit deadline on `BackupEpoch` bounds the park duration. While AD-11 does not literally say "window timer suspends while parked," the operation ledger ensures the result is durable regardless of timing. Accepted as structurally addressed.

### H-6 — Stale worker credential renewal after callback epoch advance (AD-29, AD-31)
**Status: CLOSED.** AD-29 now states: "Claim replacement invalidates renewal and advances the AD-31 callback epoch." AD-31 states: "cancellation/replacement advances callback epoch before projecting CRD status, and takeover verifies both epochs before readiness. Stale callbacks cannot append." Memlog decisions (lines 106, 117) confirm the callback epoch is atomically persisted/fsynced with gateway head metadata before CRD projection.

### H-7 — Retention tombstone race with legal hold application (AD-16)
**Status: CLOSED.** AD-16 now states: "Storage-port deletion uses a preconditioned tombstone, is audited and retried idempotently, and immediately revalidates all references and legal hold before physical deletion; a new reference/hold cancels deletion." Memlog decision (line 144) confirms: "deletion uses a preconditioned tombstone and immediately revalidates references and legal hold before physical deletion."

---

## Re-Test Matrix — AD-36/AD-37 Lifecycle Operations

| Operation | Specified | Crash-safe | Concurrency-safe | Data-loss-safe |
|---|---|---|---|---|
| Index build | ✅ Dedicated indexer, integrity-check before publish | ✅ Atomic publish | ✅ Identity-keyed, tenant-scoped | ✅ Rebuildable cache |
| Index publish | ✅ Atomic with integrity verification | ✅ Generation-matched conditions | ✅ resourceVersion precondition | ✅ Non-authoritative |
| Index reuse | ✅ Exact identity match required | N/A | ✅ Lease acquisition preconditioned | ✅ Immutable base |
| Index invalidation | ✅ IntegrityFailed/RebuildRequired conditions | ✅ Never false tombstone | ✅ Generation-matched | ✅ Triggers rebuild |
| Index reindex | ✅ Successor overlay from declared deltas | ✅ Pinned Git identity | ✅ Private overlay | ✅ Predecessor preserved |
| Index sync | ✅ sync_from_git with pinned identity | ✅ Same as reindex | ✅ Private overlay | ✅ Same |
| Index merge | ✅ Verified successor then Stale source | ✅ Atomic routing switch | ✅ resourceVersion preconditioned | ✅ Source preserved until Stale |
| Index drop | ✅ Release lease, schedule deletion | ✅ Deferred until gates pass | ✅ Competing preconditioned writes | ✅ Recheck zero refs |
| Index lease | ✅ Reference-counted + leased | ✅ Competing CAS with GC | ✅ resourceVersion preconditioned | ✅ GC blocked while leased |
| Index GC | ✅ GarbageCollecting rejects new leases | ✅ Failed → RebuildRequired | ✅ Recheck after byte deletion | ✅ Never false tombstone |
| Handoff stage | ✅ Immutable versioned artifact | ✅ Hash-addressed ArtifactStoragePort | ✅ HistoryPort sequence allocation | ✅ Never overwritten |
| Handoff event/sequence | ✅ packageSequence monotonic via HistoryPort | ✅ Durable allocation | ✅ Per-lineage | ✅ Survives export/import |
| Handoff select | ✅ CAS-bind attempt UID + claim generation | ✅ Before credentials | ✅ Fail-closed concurrent reuse | ✅ Package preserved |
| Handoff CAS | ✅ resourceVersion preconditioned | ✅ Durable before materialization | ✅ Single winner | ✅ N/A |
| Handoff materialize | ✅ Inject before execution | ✅ After CAS-bind | ✅ After predecessor publication | ✅ Immutable source |
| Handoff start | ✅ After validation + CAS | ✅ Credentials issued after | ✅ Fence-bound | ✅ N/A |
| Handoff Pod loss | ✅ Packages survive Pod/workspace loss | ✅ ArtifactStoragePort durable | ✅ New claim/attempt | ✅ Explicit |
| Predecessor terminal publication | ✅ Must be durable before successor materialize | ✅ In job projection | ✅ Ordered by cleanup phase | ✅ PublicationFailed explicit |
| Repo-context merge | ✅ Distinct paths auto-merge | ✅ Parent-generation precondition | ✅ Content-hash ordering | ✅ Both preserved |
| Repo-context conflict | ✅ Preserve both, set Conflict | ✅ Generation immutable | ✅ Deterministic sibling order | ✅ No data loss |
| Repo-context resolve | ✅ Preconditioned resolve naming parents | ✅ Descendant published | ✅ resourceVersion CAS | ✅ Ancestry preserved |
| Backup barriers | ✅ Absolute UTC deadline, fail-open | ✅ Epoch audit preserved | ✅ Fences all gateway writes | ✅ Parked ops durable |
| Retention deletion | ✅ Preconditioned tombstone + revalidation | ✅ Hold cancels deletion | ✅ Reference recomputation | ✅ Legal hold honored |
| Destination import | ✅ Staging, validation, preconditioned activation | ✅ Resumable session | ✅ Hash-match idempotency | ✅ Scheduling-disabled until verified |
| Local behavior | ✅ SQLite WAL, local artifact FS, Git common-dir | ✅ Mutation barrier + snapshot | ✅ Single-process serialization | ✅ Validated manifest |
| Kubernetes behavior | ✅ CRDs + tenant PVC + gateway | ✅ Fsynced head/epoch | ✅ resourceVersion everywhere | ✅ Backup/restore/export |

---

## Residual Medium Observations

### M-R1 — `ensure_repo_indexed` schema-version tiebreaker during upgrade (carried from M-1)

AD-36 identity includes "CodeRecon/index schema version" and the spine specifies exact identity matching, but the selection rule when multiple `Ready` generations match during a schema upgrade window is not explicitly stated. The spine says "selects or builds the exact identity" which implies exact schema version match. If a query arrives with the new schema version and only the old generation exists, the result is `Absent` → build. This is structurally safe but could cause unnecessary rebuilds during rolling schema upgrades if both old and new queries coexist.

**Severity:** MEDIUM — no data loss; operational efficiency concern only.

### M-R2 — Local backup mutation barrier timeout (carried from M-5)

Backup §8 specifies a mutation barrier that "drains or durably parks accepted operations" but does not specify an explicit timeout. The Kubernetes path has a required absolute UTC deadline (Backup §1). While local mode is single-process and the barrier is simpler, a hanging agent process could block the barrier indefinitely.

**Severity:** MEDIUM — local-only; no data corruption risk but operational hang.

---

## Scope Exclusions

Per instructions, pre-existing AD-1 through AD-35 concerns unrelated to the AD-36/AD-37 ownership gap are excluded. The memlog decision at line 146 explicitly states: "Focused reviewer findings outside the requested index/handoff ownership change that would alter unrelated accepted AD-1 through AD-35 remain unchanged." No AD-36/AD-37 decision regresses any AD-1 through AD-35 invariant; the new decisions explicitly preserve the existing AD-31 history chain, AD-34 storage gateway, AD-14 cleanup ordering, and AD-29 credential lifecycle.

---

## Verdict

**PASS.** All 4 prior critical and 7 prior high findings are closed in the current ARCHITECTURE-SPINE.md text and confirmed by memlog decisions. The AD-36/AD-37 lifecycle covers all requested test points (index build/publish/reuse/invalidation/reindex/sync/merge/drop/lease/GC; handoff stage/event/sequence/select/CAS/materialize/start/Pod loss; predecessor terminal publication; repository-context merge/conflict/resolve; backup barriers; retention deletion; destination import; local/Kubernetes behavior) with explicit crash, concurrency, and data-loss safety mechanisms. Two residual medium observations are noted but do not block.
