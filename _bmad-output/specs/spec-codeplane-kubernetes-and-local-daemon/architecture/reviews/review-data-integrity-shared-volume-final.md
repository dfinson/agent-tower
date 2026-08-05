---
review: data-integrity-shared-volume-final
target: ../ARCHITECTURE-SPINE.md
reviewer: critic (independent, read-only)
date: 2026-08-05
scope: >
  Shared-RWX concurrency and data-loss plus backup/restore. Canonical paths/subPaths;
  private workspace isolation; mirror/ref/index/context mutations and Kubernetes Lease
  loss/expiry; no portable flock; temp/fsync/rename/parent-fsync ordering;
  SQLite-to-file reference ordering; quarantine GC; two-volume quiesce and explicitly
  non-atomic snapshots; restore attempts/fences/Leases.
verdict: CHANGES REQUESTED (3 Blocking, 2 Non-Blocking)
---

# Data-Integrity / Shared-Volume Review — ARCHITECTURE-SPINE.md

## Verdict

**CHANGES REQUESTED.** The write-ordering discipline (temp → fsync → atomic rename →
parent-dir fsync → SQLite reference) is stated crisply and *consistently* across AD-8,
AD-10, AD-31, and AD-34, and the SQLite-is-canonical / CRDs-are-projections stance
removes most dual-write hazards. However, three durability/recovery contracts are
specified at a level where two competent implementers would build **incompatible and
individually-corrupting** systems: (1) mirror mutation leans on a Kubernetes `Lease`
that provides no fencing and no interrupted-mutation recovery, while Git CAS only
covers ref publication; (2) restore rewinds the fence / claim-generation / cursor
number space with no incarnation epoch, permitting fence and deterministic-name reuse;
(3) the two-volume quiesce barrier is enforced by a wall-clock deadline across
separately-clocked worker/indexer Pods that write RWX, which — combined with the
*explicitly non-atomic* two-snapshot capture — can capture RWX bytes the SQLite
snapshot does not reference. Two more are lower-severity leak/identity gaps.

The findings below are the ones that materially threaten "no data loss / no corruption /
recoverable" — not style.

---

## Blocking Issues

### B1 — Bare-mirror mutation has no fence and no interrupted-mutation recovery; the `Lease` is advisory only

**Where:** AD-8, AD-13, AD-24, AD-34 ("Mirror mutation and repository/ref publication
serialize through a Kubernetes `Lease` plus Git CAS … portable `flock` is never depended on").

**Issue.** The spine repeatedly protects *two distinct operations* with one mechanism
pair, but the mechanisms only cover one of them:

- **Ref publication** (merge/push/discard) is genuinely protected by Git
  expected-head/CAS — an atomic, fencing-equivalent compare-and-swap on the ref.
- **Mirror mutation** (`git fetch` into the bare `mirror.git`, loose-object writes,
  repack/`gc`, `sync_from_git`) has **no CAS**. Its *only* serialization is the
  Kubernetes `Lease`.

A Kubernetes `Lease` is **not a fence**. It is time-based (`leaseDurationSeconds`) and
advisory: if the holder stalls past the lease duration (GC pause, slow RWX I/O, CSI
stall) another party may acquire the `Lease` and begin a *second concurrent* fetch/repack
into the same object database while the first is still writing — the classic
"distributed lock is not a fencing token" failure. The document explicitly rejects
`flock` (which at least the kernel releases on process death) and replaces it with a
weaker, clock-driven primitive, without adding a fencing token or a filesystem-level
staging discipline for the mirror.

Compounding this: the "write to temp, atomic-rename" discipline that protects *indexes*
(AD-36: "builds in a temp directory … atomic-renames to publish; interrupted builds
never publish") and *artifacts* (AD-10) is **never applied to the mirror**. You fetch
*into* the live bare repo. So an interrupted mirror mutation (Lease loss mid-fetch, Pod
kill mid-repack) leaves a partially-written object DB with **no defined recovery** —
unlike the recovery Git bundle in AD-8, which protects the *resolution ref*, not the
mirror's internal integrity.

**Why it matters / who contends.** The single-replica baseline (AD-35) makes this feel
theoretical, but two windows create real concurrency on `/repos/<repo-id>/mirror.git`:
(a) indexer Jobs run as separate Pods and `sync_from_git`/reindex from the mirror while
the control plane fetches; (b) StatefulSet rolling restart (AD-22: "may briefly
interrupt during rolling restart") can transiently overlap an old terminating Pod and a
new starting Pod, both mounting the **RWX** volume. The RWO SQLite PVC serializes
control-plane *authority*, but the mirror lives on **RWX**, which both can mount — and
the spine never states that RWO attach/detach is the mirror-mutation fence.

**Incompatible resolutions.** Implementer A reads "serialize through a `Lease`" literally
and ships lease-only serialization (corruptible). Implementer B, knowing leases don't
fence, adds `O_EXCL` staging, a fencing token compared at write time, or routes *all*
mirror writes through the single control-plane in-process lock and forbids indexer
direct-mirror mutation. These are structurally different systems.

**Recommended fix.** State explicitly (a) what fences bare-mirror mutation against a
paused/expired `Lease` holder — e.g., a monotonic fencing token persisted in SQLite and
re-checked immediately before each destructive Git operation, and/or a hard rule that
*only the single control-plane process* mutates the mirror (indexers read a pinned
commit, never fetch); (b) the interrupted-mirror-mutation recovery contract (fetch into
a quarantine/temp objectdir + atomic promote, or `git fsck`/repack-repair on reacquire),
so mirror mutation gets the same "interrupted builds never publish" guarantee AD-36
already gives indexes.

---

### B2 — Restore rewinds the fence / claim-generation / cursor number space with no incarnation epoch → fence and deterministic-name reuse

**Where:** Backup/Recovery step 4 ("invalidates active attempts/fences/cursors, clears
the repository-ref, index, and repository-context `Lease`s"); AD-13 (deterministic
attempt/Pod names = job UID + monotonically increasing claim generation; fence fixed per
claim); AD-29 (claim replacement advances the callback fence in SQLite); AD-12 (cursors
bound to "installation, stream scope, and last SQLite sequence/hash").

**Issue.** Every fence in this design derives its safety from **monotonicity within one
SQLite lineage**: claim generation only increases (AD-13), fence advances on replacement
(AD-29), per-job sequence is monotonic (AD-31), cursors bind to a SQLite sequence/hash.
Restore **rewinds SQLite** to a captured point. After restore, claim generation, fence
values, per-job sequence, and the deterministic name `job-UID + claim-generation` all
resume from the *captured* value — i.e., they go **backwards** and will be **re-issued**.

The spine asserts restore "invalidates active attempts/fences/cursors," but that
invalidation exists only in the *reconstructed* control plane's own view. There is **no
monotonic installation-incarnation / restore-epoch counter** that makes previously-issued
fences/cursors permanently unusable. Concretely:

- **Surviving-worker adoption.** RTO scope explicitly covers "logical-deletion failures
  while the CSI backend remains available" (AD-17) — i.e., in-place restore where old
  worker Pods may still exist. A worker holding claim generation *N* and fence *F*
  (created *after* the backup captured generation *N-1*) survives. Restore rewinds SQLite
  to *N-1*; subsequent activity re-increments to *N*, re-deriving the **same** name and a
  fence in the **same** space. AD-29's "compare the fence before append" no longer
  distinguishes the ghost worker from the legitimate reissued attempt. Nothing in the
  restore steps advances the fence/claim space *beyond the maximum any worker could have
  observed pre-backup*.
- **Cursor re-validation across a rewound-then-replayed timeline.** A cursor at sequence
  *S*/hash *H* handed out before backup can, after restore, match a *replayed* sequence
  *S* whose deterministic content re-hashes to *H* — validating against a timeline that
  has since diverged, exactly the "cursor-based existence/consistency" hazard AD-12 tries
  to prevent.

**Incompatible resolutions.** Implementer A takes step 4 at face value (clears live
records, reconstructs projections) and ships restore that reuses the fence space.
Implementer B adds an incarnation/epoch that is bumped and durably recorded on every
restore, folds it into fence, deterministic names, and cursor tokens, and fences
callbacks with a stale incarnation. These diverge on a *silent-adoption* corruption that
only appears in DR drills.

**Recommended fix.** Introduce a durable, monotonic **installation incarnation (restore
epoch)** advanced on every restore, mixed into: the callback fence, the deterministic
attempt/Pod name derivation, and the opaque cursor token binding. Require restore to
advance claim-generation/fence to *strictly greater than any value any pre-restore
worker could hold* (or fence purely on incarnation), and to reject any callback or cursor
carrying a prior incarnation. State how in-place restore positively fences/deletes
surviving worker Pods rather than relying on record reconstruction.

---

### B3 — Two-volume quiesce is a wall-clock barrier across separately-clocked RWX writers; combined with non-atomic capture it can snapshot RWX bytes SQLite does not reference

**Where:** Backup steps 1–3 ("mutation/scheduling barrier … required absolute UTC
deadline; every API, reconciler, worker-callback, and RWX file-writer path durably
drains/parks and acknowledges or times out"; "snapshots or copies both … volumes";
"explicitly no cross-volume atomicity"); Consistency Conventions ("deadlines use
monotonic clocks within a process and explicit Kubernetes timestamps across processes").

**Issue.** The barrier's correctness rests on *all RWX writers* being stopped before the
RWX snapshot is taken, because the two snapshots are **explicitly non-atomic** — the only
thing making them mutually consistent is the quiesce. But RWX writers include **separate
Pods** — indexer Jobs (index publish under AD-36), worker context publication
(repository-context files under AD-37), and worker RWX writes — each with its **own
clock**. The barrier is enforced by an **absolute UTC deadline**, yet the document's own
convention says cross-process coordination must not trust monotonic deadlines, and UTC
wall clocks across Pods are subject to skew. Two failure shapes:

1. **Skewed/late writer past a sealed barrier.** An indexer or worker whose clock lags
   believes it is still inside the window and performs an RWX atomic-rename (index
   publish, context publish) *after* the control plane considers the barrier sealed and
   captures RWX. Because capture is non-atomic and SQLite was checkpointed first
   (step 2), the RWX snapshot now contains a published file the SQLite snapshot never
   references — an orphan on restore — or a torn context/index publish.

2. **Ambiguous "acknowledges or times out" semantics.** Step 1 says accepted operations
   must "acknowledge or time out"; step 3 says "Partial capture never advances
   last-known-good." It is **not stated** whether a *non-acknowledging* writer aborts the
   epoch (→ `Failed`) or whether capture proceeds while that writer is still potentially
   mid-write to RWX, nor how a non-acked worker is positively **fenced off the RWX
   volume** before the snapshot. Two implementers will choose opposite policies (abort vs.
   proceed-and-fence), with opposite data-integrity outcomes.

**Incompatible resolutions.** Implementer A: proceed at the UTC deadline, trusting acks,
no positive RWX fence → occasionally torn/orphaned RWX in the snapshot. Implementer B:
require *positive* fencing of every RWX writer (revoke worker credentials / cordon
indexer / drop RWX mount) before capture and abort the epoch on any missing ack, using
control-plane-observed ordering rather than writer wall clocks.

**Recommended fix.** Make the barrier depend on **control-plane-observed** acknowledgements
and positive fencing (credential revocation / mount removal / Lease seizure) of *every*
RWX writer class before RWX capture — not on writers self-policing a wall-clock deadline.
Define explicitly whether a missing ack aborts the epoch (recommended, consistent with
"partial capture never advances last-known-good"). Because capture is non-atomic, state
the ordering that keeps SQLite a *superset* reference of RWX (e.g., freeze/fence RWX
writers → capture RWX → checkpoint+capture SQLite last, so SQLite can only reference
bytes already frozen), or an equivalent orphan-tolerant restore reconciliation.

---

## Non-Blocking Issues

### N1 — No reclamation for orphaned `/artifacts` and `/sessions` files created before their SQLite reference commits

**Where:** AD-10 / AD-31 create-ordering ("written temp → fsync → rename → parent fsync →
then referenced in a SQLite transaction"); AD-16 delete-ordering ("preconditioned SQLite
tombstone … then unlinks the RWX file"); AD-36 defines a quarantine/GC controller **only
for indexes**.

**Issue.** The create path guarantees a crash window where the RWX file is durably
renamed but the referencing SQLite transaction has *not* committed → a file exists that
SQLite has no row for. For **indexes** this is swept (AD-36 GC + "interrupted builds never
publish"). For **artifacts, handoff packages (`/sessions`), and repository-context files**
there is **no defined orphan sweeper** — AD-16 deletion only walks *from* SQLite tombstones
outward, so a file with no SQLite row is invisible to it and leaks permanently. Two
implementers diverge: one adds a reference-anchored orphan GC for `/artifacts` and
`/sessions`; the other silently leaks RWX capacity (and, over time, defeats the RWX
capacity/qualification budgets in AD-15/AD-34).

Related, smaller: **inter-file durability ordering for multi-part handoff packages is
unspecified.** AD-37 places the package JSON at `/sessions/<job-id>/<seq>.json` with
"larger blobs under `/artifacts/<job-id>/`." If the JSON references the blob, the blob
must be durable before the JSON references it, and the JSON durable before SQLite
references it — this chained ordering is not stated, and an implementer could rename the
JSON first, yielding a committed package that references a not-yet-durable blob.

**Recommended fix.** Define a reference-anchored orphan reclamation for `/artifacts` and
`/sessions` (scan-and-quarantine files with no SQLite reference older than a grace
window, mirroring AD-36's quarantine-then-recheck), and state the intra-package durability
ordering (all referenced blobs durable → package file durable → SQLite reference).

### N2 — Workspace subPath identity and quarantine-GC reference source are under-specified

**Where:** AD-8 / Durable-Data table (`/repos/<repo-id>/workspaces/<attempt-id>`); AD-13
(deterministic names = job UID + claim generation; attempt UID separately immutable);
AD-30 ("RWX file paths derive from immutable job/attempt/repository UIDs, not labels");
AD-36 GC ("active workspace/attempt references … rechecks zero references before
unlinking").

**Issue (a) — path identity.** It is ambiguous whether `<attempt-id>` in the workspace
path is the **immutable attempt UID** or the **claim-generation-derived deterministic
name**. AD-13's retry model ("retries adopt rather than duplicate," names derive from
claim generation) versus AD-30's "UIDs, not labels" pull in different directions. This
decides whether a retry after a *lost* predecessor (no clean AD-14 cleanup) **reuses the
same directory** — inheriting a dirty/partial worktree — or gets a fresh path. AD-14 orders
workspace deletion inside cleanup, but the lost-attempt-with-no-cleanup case is exactly
when reuse-vs-fresh matters, and it is unstated. Ownership of GC for leaked workspace
directories from lost attempts is likewise not clearly assigned to a controller.

**Issue (b) — GC reference source.** AD-36's GC and `ensure_repo_indexed` both operate
"under the index `Lease`," which makes the recheck-before-unlink safe **only if**
reference *acquisition* records the reference somewhere the GC observes within the same
Lease hold. The spine never says whether "active workspace/attempt references" are
**durable SQLite rows** or **inferred from live Pods/filesystem**. If inferred from live
state, a just-selected-but-not-yet-started attempt may not yet present a reference, and GC
can delete the generation out from under it. Two implementers pick SQLite-row references
vs. live-Pod enumeration and get different race outcomes.

**Recommended fix.** State explicitly (1) that the workspace subPath component is the
immutable attempt UID (or the deterministic claim-generation name) and the consequent
reuse/fresh + cleanup-on-lost-attempt rule; (2) that index/workspace references are
**durable SQLite rows** written within the index-`Lease` critical section before build/
select returns, so GC's recheck-under-Lease is authoritative.

---

## What looks solid (no action needed)

- The **temp → fsync → atomic rename → parent-dir fsync → SQLite reference, never report
  available before the reference commits** ordering is stated identically in AD-8, AD-10,
  AD-31, and AD-34 — no drift, no dual-write-as-success.
- **SQLite is unambiguously the single source of truth**; CRDs are resourceVersion-
  preconditioned single-resource projections, generation used as observation not CAS
  (AD-11, AD-33) — this removes the largest class of split-brain hazards.
- **Delete ordering** (tombstone-in-SQLite → revalidate refs/holds → idempotent unlink,
  new reference cancels deletion) in AD-16 is coherent and correctly source-of-truth-first.
- The design is **honest about non-atomicity** (no cross-volume atomicity, no PITR,
  `Lease` is "mutual exclusion and liveness only") rather than over-claiming — the gaps
  above are about *enforcement mechanism*, not false guarantees.

---

## Decision-affecting summary

| ID | Severity | One-line |
| --- | --- | --- |
| B1 | Blocking | Bare-mirror mutation fenced only by an advisory time-based `Lease`; no fencing token, no interrupted-mutation recovery (unlike indexes). |
| B2 | Blocking | Restore rewinds fence/claim-generation/cursor space with no incarnation epoch → fence and deterministic-name reuse; surviving worker can be adopted. |
| B3 | Blocking | Two-volume quiesce trusts wall-clock deadlines across separately-clocked RWX writers; non-atomic capture can snapshot RWX bytes SQLite doesn't reference. |
| N1 | Non-Blocking | No orphan reclamation for `/artifacts` and `/sessions` files created before their SQLite reference commits; multi-part package inter-file ordering unspecified. |
| N2 | Non-Blocking | Workspace subPath identity (UID vs claim-gen name) and GC reference source (SQLite rows vs live Pods) under-specified → reuse-of-dirty-workspace and GC-under-live-reference races. |
