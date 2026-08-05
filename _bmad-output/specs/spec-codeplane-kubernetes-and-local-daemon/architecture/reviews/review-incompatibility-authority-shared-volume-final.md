---
title: 'Adversarial Incompatibility Review — SQLite Authority, CRD Projection, and Shared-Volume Durability'
target: '../ARCHITECTURE-SPINE.md'
method: 'Two-independent-implementation divergence test (both units obey every AD)'
scope: 'SQLite authority vs CRD desired/current projection; idempotency; operation ordering; attempt ownership/fences; CRD reconciliation after restart/restore; elimination of distributed multi-writer machinery'
status: draft
created: '2026-08-05'
---

# Adversarial Incompatibility Review

## Verdict

**Not yet closed — three blocking authority/split-brain holes remain.** The spine is unusually
disciplined: SQLite-first ordering, single-writer control plane, per-job hash chain, deterministic
attempt/Pod naming, CAS-bound Pod UID, and the elimination of the distributed multi-writer machinery
(the whole "Future HA / multi-tenant profile" block) are coherent and defended. But the review
constructed two implementations — **Unit A (SQLite-authoritative reconcile; CRD spec is a
write-only echo)** and **Unit B (Kubernetes-idiomatic reconcile; CRD spec is read desired
intent)** — that each satisfy every AD verbatim and yet diverge into split-brain on three axes:
(1) where user *intent* is authoritative, (2) how restore reconciles surviving etcd CRs that are
**not** in the backup set, and (3) what the single overloaded word "fence" denotes on the worker
wire. These are not style differences; they produce observably contradictory behavior and, in two
cases, a wire-incompatible worker/control protocol. Idempotency-digest membership is a fourth,
lower-severity, divergence with security relevance.

The divergences are all fixable with one or two normative sentences each. None require redesign.

---

## Method

Two teams implement the same ADs in separate rooms. A finding qualifies only if **both** resulting
units are AD-compliant (no AD is violated by either), yet the units are mutually incompatible or one
of them can reach split-brain / a stuck state. Divergences that require violating an AD are excluded.

---

## Blocking Issues

### B-1 — The authoritative source of *desired intent* is never fixed: CRD spec vs SQLite

**Where:** AD-10 (line 175), AD-11 (line 181), AD-33 (line 313), Dual-Mode table (line 367).

**The contradiction the two units exploit.** The spine calls CodePlane CRDs *both*:

- "**projections** ... of committed SQLite state ... and are **never a peer system of record**"
  (AD-10, AD-33), and
- "**desired inputs** reconciled against SQLite" / "resourceVersion-preconditioned projections of
  committed SQLite state **and desired-input reads**" (AD-10, AD-11).

A field that is simultaneously "a projection of *already-committed* SQLite state" and "a desired
*input* the reconciler *reads*" is self-contradictory: if it is already committed in SQLite it is not
an input; if it is a behavioral input, SQLite has not committed it yet. The spine never states the
one invariant that resolves this: *what is the reconciler's desired-state source of truth — SQLite,
or the CRD spec?*

**Unit A (spec-as-echo).** The reconciler derives desired state exclusively from SQLite. On every
command the API commits SQLite first (per the line 98–99 sequence), then writes CRD `spec` **and**
`status` purely as an output projection. CRD `spec` is never read as behavior. An operator's
`kubectl edit` of a Job spec is reverted on the next reconcile. This is the reading that makes AD-10's
"never a peer system of record" literally true.

**Unit B (spec-as-intent).** The reconciler follows the idiomatic Kubernetes controller pattern that
AD-11's "desired-input reads," the dedicated `codeplane-api-spec` field manager, `observedGeneration`
("intent acknowledged," line 313), and generation-matched conditions all invite: the API writes
`spec` (desired), the controller *watches spec*, drives SQLite + status. Here CRD `spec` genuinely
gates behavior.

**Why this is split-brain, not taste.** The `operator` and `tenant_admin` roles are backed by
Kubernetes RBAC on these namespaced CRs (AD-5, AD-35). In Unit B, a `kubectl edit` of `spec`, a
GitOps controller, or a *stale informer* becomes a **second writer of intent** that races the SQLite
operation ledger — precisely the multi-writer coordination the architecture claims to have deleted
(the "distributed projection/history machinery that existed solely to coordinate multiple writers,"
line 639). In Unit A the same edit is inert. The two units therefore disagree on the *result of an
operator action*, and only Unit B can drift into SQLite/CRD intent divergence. AC-6's "projection
update / fail-closed" tests do not disambiguate the two because they test status projection, not spec
as an input path.

**Impact:** Split-brain intent; silent reintroduction of a second writer; incompatible operator
semantics between two conforming builds.

**Severity:** Blocking.

**Recommended fix:** Add to AD-11 (or AD-33) a single invariant: *"The reconciler derives desired
state exclusively from canonical SQLite. CRD `spec` fields are write-only projections of committed
SQLite intent and are never read as behavioral input; external `spec` mutations are reverted to the
SQLite projection on the next reconcile."* Then strike or reword "desired inputs / desired-input
reads" everywhere (AD-10, AD-11, AD-33, line 367) so a CRD is described only as a projection, or
name the *one* exception object (e.g. `CodePlaneImportSession`/`CodePlaneBackupEpoch` desired phase)
if any CR spec is legitimately operator-authored.

---

### B-2 — Restore is under-specified and collides with "projection ahead → fails closed," because etcd/CRDs are outside the two-volume backup set

**Where:** AD-34 (line 319), Backup step 2 (line 494) and step 4 (line 496), AD-31 "projection ahead
or hash mismatch fails closed" (line 301).

**The gap.** The backup captures exactly **two PVCs** — the private RWO (SQLite) and the RWX data
volume (AD-34; Backup step 2). CodePlane CRs live in **etcd**, which is in neither PVC and is never
snapshotted. RPO is "equal to the two-volume snapshot cadence" with "no PITR" (AD-17). So at restore
time SQLite is rolled back up to 15 minutes, while the CodePlane CRs surviving in etcd reflect
operations that committed *after* the snapshot — i.e., the surviving CR projection sequence/hash is
**ahead** of the restored SQLite head. AD-31 declares exactly that condition a hard fail: "projection
ahead ... fails closed." Restore step 4 says only "**reconstructs bounded CRD projections from
verified SQLite state**" and "assigns new Kubernetes metadata/ownership" — it never says whether that
means *delete-and-recreate* the surviving CRs or *precondition-patch* them, nor does it exempt the
restore epoch from the fail-closed guard.

**Unit A (delete-recreate).** Restore first deletes/GCs all surviving CodePlane CRs, then recreates
them from restored SQLite with new UIDs. "Projection ahead" never arises because the ahead objects no
longer exist. Restore completes.

**Unit B (preconditioned patch).** Restore reuses surviving CRs and SSA-patches status to match
SQLite under resourceVersion preconditions (the AD-11 "single-resource, resourceVersion-preconditioned"
discipline, applied literally). Every surviving CR whose projection sequence/hash is ahead of restored
SQLite trips AD-31 "projection ahead → fails closed." Restore **deadlocks against the spine's own
integrity rule.**

Both units obey every AD. One restores; the other cannot restore after any real (non-empty) RPO
window. That is an incompatible-implementation hole on the primary recovery path — the exact
scenario AC-12 claims to validate.

**Impact:** A conforming build can be unable to complete baseline restore; two conforming builds
disagree on whether restore is even possible; ambiguity about CR identity/UID continuity after
restore.

**Severity:** Blocking.

**Recommended fix:** In Backup/Restore step 4 (and AD-31) state normatively: *"Restore authoritatively
discards surviving etcd CR state: the restore workflow first deletes/garbage-collects all CodePlane
custom resources for the installation, and the AD-31 'projection ahead' fail-closed guard is not armed
until reconstruction from restored SQLite completes and establishes a new projection epoch."* Also add
one sentence to AD-34/AD-17 making explicit that **etcd CR state is intentionally excluded from the
backup set and is always rebuilt from SQLite on restore**, so no reader assumes CR continuity across
restore.

---

### B-3 — "Fence" is overloaded (immutable per-attempt token vs monotonic stale-callback guard), producing a wire-incompatible stale-callback check

**Where:** AD-3 message schema "the AD-13 fence" (line 125), AD-13 (line 193), AD-29 (line 289),
AD-31 (line 301).

**The overload.** The spine uses "fence" for two things that cannot both be a single field:

- AD-13: "Attempt UID and fence are **schema/CEL immutable**; the fence ... is **fixed for one claim**,
  with renewal only extending expiry." → an immutable per-attempt value.
- AD-29 / AD-31: "Claim replacement ... **advances the attempt callback fence** recorded in canonical
  SQLite; stale callbacks are rejected by comparing that fence before any history append" and
  "cancellation/replacement **advances that fence** before projecting CRD status." → a mutable,
  monotonically advanced guard.

AD-3 then puts "**the AD-13 fence**" as one field on every worker message.

**Unit A (fence == claim generation).** There is one monotonic integer — the claim generation. The
attempt's immutable CRD `fence` field is a copy of the claim generation at creation; "advancing the
fence" *means* minting a new claim/attempt (so immutability holds: the old attempt keeps its value,
the new attempt gets a higher one). The worker carries the claim generation; the append-time check
compares `msg.fence == SQLite.activeClaim.generation`. Cancellation-without-successor still bumps
`activeClaim.generation` to reject stragglers.

**Unit B (two fences).** There is an immutable per-attempt `fence` token *and* a separate mutable
`callbackEpoch`. Renewal extends expiry within the immutable fence; cancellation/replacement bumps
`callbackEpoch` while the attempt UID and its immutable fence are preserved. The worker carries the
immutable fence; the append-time check compares `callbackEpoch`.

**Why this is incompatible, not cosmetic.** AD-3 defines a *single* wire field named "the AD-13
fence." Unit A populates it with the claim generation; Unit B populates it with the immutable
attempt token and compares a *different* server-side value (`callbackEpoch`). A worker built to Unit
A's schema and a control plane built to Unit B's (or vice versa) are protocol-incompatible on the one
field whose entire job is to reject stale writers. Worse, the failure is silent-unsafe in one
direction: a callback that Unit A rejects (because the claim generation moved) can be *accepted* by a
Unit B control plane if the replacement path bumped `callbackEpoch` but the straggler still carries a
matching immutable fence — the exact "stale writer appends history" outcome AD-13/AD-29/AD-31 exist to
prevent.

**Impact:** Wire-incompatible worker/control protocol on the fence field; a real stale-callback
acceptance path in one conforming build; AC-8's "rejects stale callback fences before append" passes
for both units while they mean different things.

**Severity:** Blocking (protocol) / at minimum high Non-blocking.

**Recommended fix:** Collapse to one named concept. State in AD-13: *"The fence is the monotonic claim
generation; there is exactly one fence value per message. 'Advancing the fence' means the claim
generation increments, which necessarily produces a new attempt/claim — no in-place attempt is ever
re-fenced. The append-time check is `message.fence == SQLite.activeClaim.generation` for the owning
job."* Delete the separate phrase "attempt callback fence" (AD-29, AD-31) or explicitly define it as
an alias for the claim generation, and pin the wire field's type/semantics in the AD-3 schema.

---

## Non-Blocking Issues

### N-1 — "Canonical request digest" membership and encoding are undefined → idempotency divergence with security relevance

**Where:** AD-11 (line 181), Idempotency convention (line 429), AD-23 collision rule (line 253).

The idempotency ledger keys on a "canonical request digest," and "digest mismatch fails," but the
spine never enumerates **which fields** the digest covers or the canonical encoding. Two conforming
units diverge sharply:

- **Unit A** folds the effective actor identity and the accepted policy generation into the digest.
  A retry replayed under a *different* OIDC identity or after a policy-generation change → digest
  mismatch → fail. Safe.
- **Unit B** digests only the business payload. The same replay → digest match → returns the stored
  result and treats the operation as done under the *original* actor/policy.

This is a security-relevant divergence (replay/authority confusion), and it also affects AD-23
import collision idempotency ("idempotent only when canonical hashes match") if digests ever
participate cross-boundary. Both units obey AD-11 as written.

**Recommended fix:** Enumerate the exact fields inside the canonical request digest (at least:
operation kind, target IDs, business payload, effective actor, accepted policy generation, scope) and
fix the canonical encoding (field ordering, normalization), mirroring how AD-31 already pins the
history hash's canonical encoding. State explicitly whether actor and policy generation are inside the
digest.

### N-2 — Torn multi-manager status projection is observable and unconstrained across units

**Where:** AD-11 (line 181), CRD table job-status/admission-status/history-status/cleanup-status
(line 345), AD-33 (line 313).

One `CodePlaneJob` `/status` is written by four disjoint field managers, and AD-11 requires CRD
writes to be "single-resource" — so a single logical transition touching two subtrees is two
non-atomic API calls. Both units converge (clients read current state from SQLite per AD-12/AD-33), so
this is not split-brain. But the spine does not bound the *torn-projection window*: Unit A issues the
four applies from one reconcile pass in a fixed order; Unit B runs four independent reconcile loops
with independent timing, widening the window a UI/informer can observe an internally inconsistent
Job status. Both conform. Since clients are told to converge from SQLite, this is a Non-blocking
observability note rather than a correctness hole.

**Recommended fix (optional):** State that observers must treat CRD status as eventually-consistent
and MUST resolve current state via the SQLite-backed projection sequence/hash, and (optionally) that
the four status managers are driven from a single reconcile pass to bound the torn window.

---

## Suggestions

- **S-1 — Deterministic-name zombie window (AD-13, AD-15).** Deterministic Pod names + one-hour Pod
  GC after evidence commit mean a delayed/duplicate reconcile of an *already-terminal* claim
  generation can recreate a GC'd Pod name; the CAS-bound-UID rejection (AD-29) prevents credential
  issuance, so it is harmless, but Unit A tolerates a transient zombie Pod that Unit B (recording a
  per-generation terminal tombstone that refuses any create) does not. Consider naming a terminal
  generation tombstone so both units behave identically.

---

## What Looks Solid (no action needed)

- SQLite-first ordering (line 98–99) with commit-before-projection and "no API reports transition
  success until the SQLite transaction and any required file rename commit" (AD-11) cleanly prevents
  the classic dual-write lost-update once B-1 is resolved.
- Single-replica writer + private RWO PVC + `Lease`+Git-CAS for repo/ref serialization (AD-8, AD-13,
  AD-24, AD-34) is internally consistent and does eliminate the distributed multi-writer machinery it
  claims (line 639), *provided* B-1 closes the CRD-spec-as-input back door.
- Per-job monotonic hash chain, checkpoint roots, and fail-forward/fail-closed asymmetry (AD-31) are
  coherent for replay/export; the only interaction hole is B-2's restore-vs-etcd omission.
- RWX writer ordering (temp → fsync → atomic rename → parent fsync → DB reference) is uniformly
  applied across AD-8, AD-10, AD-34, AD-37 and leaves no observed gap.

---

## Traceability (finding → ADs / ACs)

| Finding | Primary ADs | ACs that fail to disambiguate |
| --- | --- | --- |
| B-1 authority of intent | AD-10, AD-11, AD-33 | AC-1, AC-6 |
| B-2 restore vs surviving etcd CRs | AD-17, AD-31, AD-34; Backup steps 2/4 | AC-12 |
| B-3 fence overload | AD-3, AD-13, AD-29, AD-31 | AC-8 |
| N-1 digest membership | AD-11, AD-23 | AC-6 |
| N-2 torn status projection | AD-11, AD-33 | AC-6, AC-7 |
| S-1 zombie name window | AD-13, AD-15 | AC-8 |
