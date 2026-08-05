# Adversarial Incompatibility Review
## Focus: Repository Indexing, Handoff Packages, Repository-Context Publication, Backup/Restore, Export/Import, Retention, and Attempt Startup

**File reviewed:** `ARCHITECTURE-SPINE.md`  
**Review date:** 2026-08-05  
**Method:** Adversarial construction of independently compliant units for each subsystem; cross-unit protocol compatibility probing; special attention to AD-36/37 interactions with AD-10/14/16/23/26/33/34.

---

## Executive Verdict

The spine is internally sophisticated and rules out many obvious races, but it contains **nine cross-unit incompatibility openings** that two fully AD-compliant implementations can fall into simultaneously. None require violating a stated rule; all arise from under-specification at the interface between units. Four are latent data-loss or consistency breaks; five are semantic divergences that cause silently wrong behavior.

---

## Finding 1 — Generation-identity collision between base-index reuse and worktree-overlay selection
**Severity:** High (silent wrong-context injection)  
**ADs implicated:** AD-36, AD-10, AD-8, AD-33

**Construction:**

*Unit A — `ensure_repo_indexed` implementation:* The AD-36 generation identity binds "tenant, canonical repository identity, immutable source commit/tree, worktree or overlay identity, CodeRecon/index schema version, feature configuration, and model/tool digest." AD-36 says base generations are "tenant-shareable." Unit A therefore keyed its base index on `(tenant_id, repo_canonical_id, commit_sha, schema_version, feature_hash, model_digest)` and intentionally omits `worktree_identity` for base generations because base generations by definition have no worktree.

*Unit B — `register_worktree` implementation:* AD-36 says a private overlay "references one base." Unit B stores the overlay's generation identity as `(tenant_id, repo_canonical_id, commit_sha, worktree_id, schema_version, feature_hash, model_digest)`. To distinguish the overlay from a base it inserts a sentinel worktree value for bases (e.g., empty string `""`).

*Incompatibility:* When the attempt startup controller (Unit C, AD-37, pre-start injection) resolves "the newest compatible committed package for the same lineage," it needs to join against index generations. If a third unit D (the indexer or a query-path component) serializes and deserializes generation identity and treats missing `worktree_id` as `""`, it classifies a base generation as "some overlay with worktree_id=empty." Units A and B are each fully AD-36 compliant. The generation-identity tuple is never fully pinned — AD-36 names the fields but does not specify sentinel values, encoding, or the null/absent distinction for the base case. Two compliant units choose incompatible identity encoding and their generation lookup tables diverge silently; the indexer may find the wrong generation (wrong overlay context) or fail to find a base it should reuse, satisfying AC-19 in isolation but not in composition.

**Gap:** AD-36 specifies identity fields but not the canonical encoding, null-field convention, or whether base vs. overlay is a type field or an absent worktree field. A single canonical generation-identity schema must be fixed.

---

## Finding 2 — Handoff selection tiebreaker collision: "stable creation sequence then package ID"
**Severity:** High (nondeterministic injection under normal operation)  
**ADs implicated:** AD-37, AD-12, AD-10

**Construction:**

*Unit A — handoff selector in the attempt controller:* AD-37 says selection uses "stable creation sequence then package ID" when no explicit request names a package. Unit A interprets "creation sequence" as the monotonically increasing `CodePlaneSessionHandoff` resource creation timestamp recorded in CRD metadata.

*Unit B — handoff selector in the restore/import-activation path:* After restore (AD-37 explicitly states "packages survive backup/restore") the restored `CodePlaneSessionHandoff` objects are assigned **new Kubernetes metadata** (AD-23: "Kubernetes UIDs/resourceVersions … are remapped"). The restore epoch gives each object a new creation timestamp. Unit B, also compliant, uses the same "creation sequence" rule but its creation timestamps are now restore-time timestamps, not the original authoring-time ones.

*Incompatibility:* On a restored cluster a lineage may have packages P1 (originally authored first) and P2 (authored second). After restore, if P2's new metadata timestamp is earlier than P1's new metadata timestamp due to restore ordering, Unit B selects P1 as "newest" and Unit A would have selected P2. Both obey AD-37 and AD-23. The tiebreaker field is not canonically defined — is it original authoring timestamp? monotonic sequence from the originating history chain? CRD creation time? The spine never states this, and the two units select different packages.

**Gap:** AD-37 must define "stable creation sequence" as the canonical per-job handoff sequence number from the originating `HistoryPort` chain (preserved through export/import as AD-23 preserves canonical IDs), not as Kubernetes creation timestamps, which are remapped.

---

## Finding 3 — Repository-context publication precondition races with backup quiesce barrier
**Severity:** High (backup captures partial context state / breaks restore verification)  
**ADs implicated:** AD-37, AD-34, AD-10, AD-16, Backup section §2

**Construction:**

*Unit A — repository-context publisher (checkpoint path):* AD-37 says "publishes checkpoint/termination changes with parent-generation and content-hash preconditions." A worker is running, reaches a checkpoint, calls the tenant gateway to publish a new `RepositoryContextPort` generation. This is a preconditioned write: it reads the parent generation, computes a hash, and applies.

*Unit B — backup orchestrator:* The Backup section §1 says "every API, reconciler, and storage writer durably acknowledges or times out" the mutation/scheduling barrier. §2 says the gateway "records … every authoritative PVC head." The backup controller sets the barrier, waits for acknowledgments, then proceeds to capture heads.

*Incompatibility:* Unit A (context publisher) is a **worker-side path** — workers authenticate through the control API (AD-3, AD-29, AD-34: "workers upload through the gateway"), not directly as a reconciler. The backup barrier protocol names "API, reconciler, and storage writer" acknowledgments. If the barrier implementation considers a worker context-publish "in flight" only after it reaches the gateway — but the worker has already computed its hash against a parent generation that was the last committed generation at barrier-start — the backup may:

- Commit the barrier after acknowledging the gateway write but before the worker's context-publish gateway call lands, capturing a generation head that does not include the committed context update.
- OR, the backup includes the update but the CRD projection for that generation is still in-flight when the manifest re-reads CRD resourceVersions and rejects due to mismatch.

Neither unit violates an AD. The backup AD does not specify whether the barrier acknowledgment protocol extends to worker-initiated gateway writes or only to control-plane-initiated ones. A barrier that excludes worker-pathway writes can capture inconsistent gateway/CRD state.

**Gap:** The backup barrier must explicitly scope to all gateway mutations, including those arriving via the authenticated worker path, and the barrier acknowledgment must be defined from the gateway's perspective (quiesce all writers at the gateway boundary), not just from control-plane component perspective.

---

## Finding 4 — Export optional derived-cache transfer: AD-36 "revalidates" vs. AD-23 "accepted only when every AD-36 identity field and integrity digest revalidates"
**Severity:** Medium-High (silent stale-index injection after cross-instance import)  
**ADs implicated:** AD-23, AD-36, AD-10, AD-14

**Construction:**

*Unit A — exporter:* AD-23 states that repository-index bytes "are excluded by default because they are rebuildable; an optional derived-cache transfer is accepted only when every AD-36 identity field and integrity digest revalidates." Unit A, implementing the exporter, applies the revalidation at export time on the source cluster: it checks that all AD-36 identity fields present in the `CodePlaneRepositoryIndex` CRD metadata match the bytes in the PVC storage generation and confirms the content hash. It writes a flag in the manifest: `index_revalidated: true`.

*Unit B — importer:* Unit B, implementing the import activation path, reads `index_revalidated: true` and trusts the source-time validation, skipping an independent revalidation on the destination cluster. This is compliant with AD-23 which says "accepted only when every AD-36 identity field and integrity digest revalidates" — Unit B interprets "revalidates" as requiring that revalidation occur at some point, which the exporter already did.

*Incompatibility:* AD-36 generation identity includes "model/tool digest." Between the source cluster's index build and the destination cluster's attempt startup, the CodeRecon/index schema version or model digest on the destination may differ (different installed version). The source-revalidated identity is no longer valid for the destination's feature configuration. Unit B admits a generation whose model/tool digest does not match the destination's current CodeRecon version. AC-19 says "schema, feature, or model/tool digest changes invalidate reuse" — this check is only tested within a single instance. The importer is not required by any AD to re-check destination-side tool/model compatibility before activation.

**Gap:** AD-23 must specify that for optional derived-cache transfers, revalidation includes destination-side feature/model/tool digest compatibility, not just source-side content integrity. "Revalidates" must be defined as destination-time, not export-time.

---

## Finding 5 — Retention class for handoff packages: "inherits the longest retention … of any referencing job" creates circular hold via export sessions
**Severity:** Medium (operational — storage cannot be freed; GC deadlock)  
**ADs implicated:** AD-16, AD-37, AD-23, AD-14

**Construction:**

*Unit A — retention engine:* AD-16 says "Handoff packages and repository-context generations inherit the longest retention or legal hold of any referencing job, session, attempt, export, descendant generation, or intended consumer." Unit A scans all `CodePlaneImportSession` objects with `Verified` or `Committed` status, considers them "export sessions" referencing the handoff packages listed in their manifest, and extends those packages' retention to match the import session's own 30-day retention class.

*Unit B — import compensation/cleanup:* AD-23 says a `CodePlaneImportSession` retains for 30 days. If an import session fails after partial activation and compensation runs (AD-23: "removes only resources proven created by it"), Unit B's compensation removes the import session CRD. This ends the import session's hold on the referenced handoff packages.

*Incompatibility:* If Unit A has already extended the retention of a handoff package to 30 days based on the import session reference, and Unit B's compensation removes the import session, the package's retention extension does not automatically retract — there is no AD-specified mechanism to retract an inherited retention grant when the referencing object is deleted. The retention engine must re-scan and recompute the package's hold based on remaining references. If the package was otherwise unreferenced (the source job was already GC'd at the source), the package survives 30 more days with no functional consumer. More critically: if the import session deletion itself is retried (compensation is idempotent per AD-14/23) and the retention engine races, the package may be deleted before the retry confirms it is safe to do so.

**Gap:** AD-16 must specify that retention holds are revocable (recomputed on referencing-object deletion) and that compensation paths must acquire and verify the current hold state before and after removal of any referencing object.

---

## Finding 6 — Attempt startup handoff injection: "materializes/injects before execution" races with concurrent context-publish from a predecessor attempt
**Severity:** High (successor attempt starts with stale context if predecessor publishes concurrently)  
**ADs implicated:** AD-37, AD-13, AD-14, AD-34

**Construction:**

*Unit A — predecessor attempt cleanup (finalizer path):* AD-14 cleanup order is "stop/checkpoint worker; commit outcome/history and retention tombstone; revoke credentials; release ref ownership; finalize retained storage; delete workspace/Pod." AD-37 says the predecessor publishes context at checkpoint and termination. Unit A runs as the attempt finalizer: it publishes the final repository-context generation for the predecessor attempt (AD-37 preconditioned publish) and only after that commits the outcome/history tombstone.

*Unit B — successor attempt startup (pre-start injection, AD-37):* The admission controller creates a new attempt when the recovery policy schedules one (AD-13 claim/attempt lifecycle). Before credential issuance, Unit B materializes the "newest compatible committed" repository-context generation into the attempt's private Git common directory (AD-37: "materializes one into each attempt's private Git common directory before startup"). Unit B reads the current repository-context port to find the newest committed generation.

*Incompatibility:* The AD-13 claim generation advances and a new attempt begins before the AD-14 cleanup finalizer fully completes (the predecessor may still be terminating, having stopped its worker but not yet published its final context generation). The new attempt's admission can proceed because the old claim is superseded; there is no explicit synchronization barrier between AD-14 finalizer publication and AD-13 successor startup context materialization. Unit B injects the generation that was committed before the predecessor's final checkpoint, missing the predecessor's last context update. Both units are fully compliant — AD-37 says "materializes before execution," not "after all predecessor finalizers complete," and AD-13/14 do not serialize handoff/context publication as a gate on claim-generation advance.

**Gap:** AD-37 or AD-14 must specify that context-publication by a terminating attempt is either (a) a required precondition before the AD-13 claim generation advances for the same job, or (b) discoverable-at-start via a stable pointer in the attempt/job status so the successor can detect and await its predecessor's terminal context generation before materializing.

---

## Finding 7 — AD-36 "referenced or leased" GC gate vs. AD-14 workspace deletion ordering
**Severity:** Medium (premature GC of index generation while attempt is still active)  
**ADs implicated:** AD-36, AD-14, AD-10, AD-8

**Construction:**

*Unit A — index GC controller:* AD-36 says generations are "GC only after every durable reference and live lease is gone." Unit A tracks references via `CodePlaneRepositoryIndex` reference/lease summary in status. It checks the lease summary field and, when all leases are released, marks the generation `GarbageCollecting`.

*Unit B — attempt cleanup controller (AD-14 finalizer):* In the cleanup order, workspace deletion follows "finalize retained storage." AD-36's `drop_worktree` releases the overlay reference/lease. AD-14 says workspace deletion cannot precede durable outcome record. Unit B releases the overlay lease as part of "finalize retained storage," which per AD-14 happens before "delete workspace/Pod."

*Incompatibility:* If the attempt is interrupted mid-cleanup (node failure, pod eviction), the finalizer may have released the overlay lease (step "finalize retained storage") but not yet deleted the workspace PVC. The workspace PVC is the physical backing for the private overlay's bytes. Once the lease is released, Unit A's GC controller sees zero live leases and begins GarbageCollecting. The workspace PVC still exists and may contain in-progress data that the agent partially committed. The outcome/history tombstone was committed (it precedes workspace deletion per AD-14), but the workspace PVC data referenced by that outcome may be GC'd before it's proven read by the recovery path (e.g., for artifact extraction). AD-36's "no durable reference" doesn't account for the cleanup window between lease release and PVC deletion.

**Gap:** AD-36 must distinguish between lease release (logical intent to drop) and confirmed workspace PVC deletion. The GC gate must require workspace PVC deletion confirmation, not just lease release, for overlay generations that reference live PVC-backed workspaces.

---

## Finding 8 — AD-37 "Conflict" condition and three-way merge implementation: divergent conflict detection between local and Kubernetes modes
**Severity:** Medium (cross-mode export/import produces inconsistent conflict state)  
**ADs implicated:** AD-37, AD-1, AD-23, AD-26

**Construction:**

*Unit A — local-mode repository-context publisher:* In local mode, `RepositoryContextPort` uses the "actual Git common-directory `session-handoff/` tree." AD-37 says "Disjoint concurrent changes may merge only through deterministic three-way validation; conflicting decisions, environment, or handoff records preserve both candidate generations, set `Conflict`." In local mode, Unit A implements this as a file-level three-way merge using Git's merge machinery against the common-directory tree, where "conflict" means Git merge conflict markers.

*Unit B — Kubernetes-mode repository-context publisher:* Unit B uses versioned tenant gateway generations with parent-generation preconditions. "Three-way validation" here means: read parent generation G, read both candidate content sets, compute a delta diff, attempt a semantic merge. A "conflict" is when the semantic merge cannot automatically resolve. The definition of "disjoint vs. conflicting" diverges: Git considers changes to separate files disjoint; a semantic merge may flag simultaneous changes to different keys in the same JSON file as conflicting even if they're at non-overlapping paths.

*Incompatibility:* On export from local and import into Kubernetes (or vice versa), a generation that was committed without `Conflict` in local mode may be flagged `Conflict` in the Kubernetes re-publication path, or a `Conflict` preserved in local mode may be silently merged in the Kubernetes path (because the gateway's semantic merge resolves what Git's file-level merge would not). AD-37 says "Referenced packages and context ancestry survive … signed export/import" but does not normalize the conflict-detection algorithm. AC-14 tests "repository-context ancestry" preservation but not conflict-state preservation.

**Gap:** AD-37 must define a canonical conflict-detection algorithm at the content/semantic level, independent of the storage mechanism, so that both modes produce identical conflict flags for identical input content.

---

## Finding 9 — Backup manifest "rejects the epoch if any [resourceVersion] differs" vs. AD-11 single-resource preconditioned writes creating update windows
**Severity:** Medium-High (spurious backup epoch rejection under normal operation; backup never succeeds during active job load)  
**ADs implicated:** AD-10, AD-11, AD-33, AD-34, Backup §3

**Construction:**

*Unit A — backup orchestrator:* Backup §3 says the backup "exports CodePlane CRDs and related configuration … rereads all included resourceVersions/UIDs and history heads, and rejects the epoch if any differs." Unit A does this as: quiesce (§1 barrier), capture heads (§2), then re-read all CRD resourceVersions. If any CRD has been updated since the barrier, the epoch is rejected.

*Unit B — any legitimate controller performing condition updates:* AD-11 says controllers own enumerated status fields/condition types and perform preconditioned writes. AD-33 says controllers use informer-driven reconciliation. During the §1 barrier, Unit B is told to "durably acknowledge or time out." Unit B acknowledges the barrier by not starting new operations but continues to update `observedGeneration` and condition statuses for already-in-progress operations that reach committed projection (because AD-11 requires no API to report success until durable boundaries commit — meaning a controller may continue writing its success status after the barrier acknowledgment).

*Incompatibility:* Unit B is compliant: it acknowledged the barrier but is still writing condition updates for committed operations. These writes change CRD resourceVersions. Unit A re-reads the CRDs after §2 and finds changed resourceVersions, rejecting the epoch. Under any non-trivial job load, there will always be operations completing and controllers writing condition updates, making backup §3 re-read permanently fail. The barrier specification says "every API, reconciler, and storage writer durably acknowledges" but does not specify "stops all writes" — acknowledging a barrier and stopping all writes are different. If AD-11 requires condition updates to complete after operations commit, and the backup requires a stable resourceVersion set, these requirements are irreconcilable unless "barrier acknowledgment" is defined as "all in-flight writes have reached their terminal status update."

**Gap:** Backup §3's re-read validation must be scoped to the specific CRD fields that constitute snapshot validity (spec, projection sequence/hash, storage reference, manifest references) rather than requiring stable overall resourceVersions. Controllers should be allowed to update non-snapshot-critical status conditions after the barrier. Alternatively, the barrier must define a "drain-to-quiescent" phase that guarantees no further status writes after acknowledgment.

---

## Cross-Cutting Observation: AD-36/37 lifecycle vs. AD-16 retention: "intended consumer" is undefined

AD-16 says handoff packages "inherit the longest retention … of any … intended consumer." AD-37 says a package records "intended consumer." These two rules together mean the retention engine needs to enumerate all objects that are "intended consumers" and find the longest applicable retention class for each.

However, "intended consumer" appears only in AD-37 as a package field and is never formally enumerated. An implementation must decide: is a follow-up job that was subsequently canceled an "intended consumer"? Is an `Absent` attempt that never started? Is an import session that referenced the package but never activated? Two independently built implementations will draw this line differently, resulting in divergent retention periods — both fully AD-compliant. This is not a single-finding incompatibility but a pervasive under-specification that affects retention, GC, and any cross-unit query for "packages I may delete."

**Gap:** AD-16 and AD-37 together must define "intended consumer" as an enumerated set of relationship types (e.g., `CodePlaneExecutionAttempt` with a specific declared-consumer field, job follow-up references, import session package references) rather than a semantic label on the package.

---

## Summary Table

| # | Subsystems | Incompatibility Class | Severity | Root Gap |
|---|---|---|---|---|
| 1 | Index identity encoding (base vs. overlay) | Silent identity divergence | High | AD-36 doesn't fix null encoding for worktree field |
| 2 | Handoff selection tiebreaker after restore | Nondeterministic package injection | High | AD-37 tiebreaker not defined as history-sequence, not Kubernetes creation time |
| 3 | Context-publish vs. backup quiesce barrier | Backup captures inconsistent gateway state | High | Backup barrier not scoped to worker-pathway gateway writes |
| 4 | Optional index cache transfer: source vs. destination revalidation | Stale model-digest index injected after import | Medium-High | AD-23 revalidation not specified as destination-side |
| 5 | Handoff retention via import session reference → compensation | GC race after compensation | Medium | AD-16 retention holds not defined as revocable on referencing-object deletion |
| 6 | Context-publish by predecessor vs. successor startup injection | Successor starts with pre-terminal context | High | No gate between AD-14 context publish and AD-13 claim advance |
| 7 | Index GC lease release vs. workspace PVC lifetime | Premature GC of overlay while PVC exists | Medium | AD-36 GC gate defined on lease, not on PVC deletion |
| 8 | Conflict detection algorithm: local Git vs. Kubernetes semantic merge | Cross-mode conflict state diverges | Medium | AD-37 doesn't fix canonical conflict-detection algorithm |
| 9 | Backup re-read stable resourceVersions vs. AD-11 post-barrier condition writes | Backup epoch always rejected under load | Medium-High | Backup §3 scopes to all resourceVersions, not snapshot-critical fields only |
| — | "Intended consumer" retention enumeration | Divergent retention periods | Cross-cutting | AD-16/37 label not enumerated as concrete relationship set |
