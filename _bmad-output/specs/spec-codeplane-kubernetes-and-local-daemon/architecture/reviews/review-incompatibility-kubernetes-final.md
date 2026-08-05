# Final Adversarial Incompatibility Gate — Kubernetes and Local Daemon

**Artifact reviewed:** `architecture/ARCHITECTURE-SPINE.md`  
**Review date:** 2026-08-05  
**Scope:** CRD field ownership, attempt CAS and worker bootstrap, canonical-history storage, controller topology, finalizers, backup/import epochs, upgrades, and local parity.  
**Method:** Collision testing between independently implemented units that obey the spine literally. Implementation-detail follow-ups were excluded.

## Verdict

**FAIL — NOT IMPLEMENTATION-COMPATIBLE**

The reviewer fixes close the attempt-claim race, worker bootstrap circle, RWO access topology, cleanup ordering, import quarantine, backup cut validation, and CRD/Helm upgrade-order gaps. Three architecture-level incompatibilities remain: two critical and one high.

## Remaining Critical/High Findings

### 1. Critical — CRD field and condition ownership is required but still not defined

AD-11 assigns one stable API manager to intent and disjoint controller managers to “enumerated” status fields and condition types. AD-33 says every future schema fixes those owners, but the spine contains neither the enumeration nor the ownership matrix. A CRD OpenAPI schema can enforce list-map keys and field shape; it does not identify which runtime manager exclusively owns each field or condition.

Consequently, independently compliant API, admission, job, attempt, history, backup, import, and cleanup units can select different manager names or overlap on `observedGeneration`, projection fields, active claims, phases, and condition entries. Resource-version retry prevents a blind write but does not resolve semantic ownership; SSA only turns the disagreement into conflicts.

**Compatibility requirement:** Before implementation splits, publish the normative per-kind matrix named by AD-33: every spec/status field, condition type, top-level and condition-level generation marker, finalizer, owner reference, manager identity, mutation mechanism, and permitted ownership-transfer rule. The matrix must also identify the sole phase owner for each `CodePlaneOperation`, import, backup, attempt, and cleanup transition.

### 2. Critical — The storage-gateway writer epoch does not fence a stale data-plane writer

AD-31 claims the gateway writer epoch through resourceVersion CAS in `CodePlaneStorageShard`; AD-34 says failover rejects the old epoch. Neither rule requires the accepted epoch to be persisted on the PVC and compared atomically with every head update. A partitioned or paused old gateway can therefore retain its mounted RWO volume, stale epoch view, and in-flight request while a replacement wins the CRD CAS. `ReadWriteOnce` does not guarantee single-Pod access, particularly when both Pods run on one node, and a Lease is explicitly non-authoritative.

Two compliant gateways can then append against different locally believed heads or let the old gateway write after the backup epoch's final head reread. This breaks the canonical hash chain, callback fencing, and the claimed backup cut despite all control-plane CAS operations succeeding.

**Compatibility requirement:** Make the epoch a data-plane fence: durably store it with canonical head metadata, require epoch acquisition to atomically advance that stored value before serving, and make every append/compaction/snapshot barrier compare the supplied epoch and update the head in one serialized durable operation. Define recovery for an old writer resuming after takeover; service routing, Pod readiness, volume attachment, and Lease ownership cannot substitute for this check.

### 3. High — Local canonical-history ownership contradicts the shared storage contract

AD-10 says `ArtifactStoragePort` owns durable history bytes and its local adapter uses the filesystem. The topology table instead assigns local event/history replay to SQLite. AD-31 then names the tenant storage gateway as the only canonical writer even though that gateway is Kubernetes-specific. The backup procedure captures both SQLite and the artifact tree, so this ambiguity is observable during restore, export, retention, and replay.

An independently compliant local adapter can treat SQLite events as canonical while another can treat filesystem history as canonical and use SQLite only as a projection/index. They will disagree on append atomicity, checkpoint roots, compaction, missing-blob degradation, export source, and which half of a local backup is authoritative. AC-1 cannot normalize away this durability difference.

**Compatibility requirement:** Declare one local canonical-history owner and transaction boundary. If SQLite is canonical, narrow AD-10/AD-31 and define how artifact-tree references join the SQLite snapshot. If filesystem history is canonical, define SQLite as a reconstructable projection and apply expected-sequence/hash, idempotency, checkpoint, replay, backup, and restore rules equivalent to the Kubernetes gateway contract.

## Gate Result

Attempt CAS/bootstrap, finalizer ordering, backup/import epochs, controller privilege topology, and N/N-1 upgrade sequencing have no additional critical/high incompatibility after the fixes, subject to resolving the ownership and storage-fencing contracts above.
