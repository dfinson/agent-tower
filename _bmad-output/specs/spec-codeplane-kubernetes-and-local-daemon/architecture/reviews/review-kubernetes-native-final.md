# Final Kubernetes-Native Correctness Gate

**Artifact reviewed:** `architecture/ARCHITECTURE-SPINE.md`  
**Review date:** 2026-08-05  
**Baseline:** Kubernetes API/etcd, built-in controllers, CSI-backed PVCs, and CodePlane components only; no PostgreSQL, S3, or other external state service assumed  
**Verdict:** **FAIL — NEEDS REVISION**

The fixes materially improve the design. The tenant storage gateway removes the hidden RWX dependency, the CRD set is now closed by assertion, attempt claims precede child creation, worker bootstrap uses TokenReview and live ownership checks, CRDs have a separate OCI lifecycle, controllers are split by authority, SSA and condition semantics are separated, Leases are advisory, cleanup is phased, and backup epochs reject inconsistent captures.

The gate still fails. One critical storage-fencing defect and four high-severity contract gaps remain. In particular, a CRD writer epoch is not storage fencing for a stale process that still has an RWO volume mounted, and the worker bootstrap still permits a Kubernetes Job-created replacement Pod to satisfy the same attempt ownership checks.

## Re-evaluation of K8S-01 through K8S-12

| Prior finding | Final status | Assessment |
| --- | --- | --- |
| K8S-01 — RWO storage topology | **Open — Critical** | AD-34 correctly routes all canonical access through one tenant gateway and removes RWX from the baseline, but takeover does not prove that the previous gateway has lost write access before the epoch changes. |
| K8S-02 — CRD inventory | **Open — High** | AD-33 names ten namespaced CRDs and built-ins, but does not actually provide the promised per-kind ownership/cardinality/reference matrix; AD-30 still refers to an installation-owned cross-namespace grant absent from the closed inventory. |
| K8S-03 — attempt claim and Job/Pod identity | **Open — High** | The single-resource claim and deterministic names solve competing-reconciler creation. Kubernetes Job replacement and bootstrap identity remain inconsistent with “one Pod incarnation.” |
| K8S-04 — CRD OCI lifecycle | **Open — High** | The separate bundle and explicit workflow fix ordinary Helm lifecycle misuse. Conversion-webhook ordering and cluster-wide coordination across installations remain undefined. |
| K8S-05 — etcd budgets | **Open — High** | Per-object and field-owner ceilings exist, but child/resource retention and installation-wide etcd/watch budgets are still only called “bounded,” without bounds. |
| K8S-06 — controller topology | **Resolved at spine level; follow-up required** | AD-35 selects installation bootstrap/admission plus tenant-local reconcilers and namespace Roles. The API service-account grant topology still needs an explicit contract before manifests are frozen. |
| K8S-07 — observedGeneration and conditions | **Resolved at spine level; follow-up required** | AD-33 gives `observedGeneration` acknowledgement semantics and generation-matched `metav1.Condition` progress/completion. Per-kind finite condition catalogs remain a schema deliverable. |
| K8S-08 — resourceVersion and SSA | **Resolved** | AD-11 separates resourceVersion CAS, generation observation, one API field manager, and disjoint status/condition managers. |
| K8S-09 — watch recovery | **Resolved at spine level; test gap remains** | AD-33 now requires initial list, resourceVersion handoff, resume, 410/full relist, enqueue-all, and orphan adoption. AC-7 does not enumerate all of those failure cases. |
| K8S-10 — Lease semantics | **Resolved at spine level; follow-up required** | AD-13, AD-24, and AD-31 make Leases advisory. Names, durations, identities, permissions, and paused-old-leader tests remain unspecified. |
| K8S-11 — ownerReferences/finalizers | **Mostly resolved; medium gap remains** | AD-14 supplies an owner graph, phased cleanup, one owner per finalizer, retention-safe PVC handling, bounded retries, and audited force-finalization. Its unavailable-storage and forced-namespace-deletion behavior is not yet executable. |
| K8S-12 — backup epochs | **Resolved at spine level; follow-up required** | The barrier, flush, snapshot/copy readiness, resourceVersion/head reread, manifest, rejection, and restore gates establish a defensible non-atomic snapshot-set protocol. Participant acknowledgement state still needs a concrete schema. |

## Remaining release-blocking findings

### K8S-01 — Critical — The RWO gateway epoch does not fence a stale mounted writer

**Evidence**

- AD-31 makes `CodePlaneStorageShard` resourceVersion CAS the writer-epoch source.
- AD-34 permits failover after acquiring a new epoch and says the old epoch is rejected.
- The baseline relies on `ReadWriteOnce`, not storage-level multi-writer fencing.

**Problem**

`ReadWriteOnce` is an attachment/access-mode constraint, not a single-process writer lock. Multiple Pods on one node may use the same RWO volume, and a partitioned or paused old gateway can retain a mounted filesystem while another controller advances the CRD epoch. Checking the epoch “immediately before commit” is still a check-then-write race: the old process can pass the check, pause, and later fsync after takeover. The filesystem does not reject bytes because their CRD epoch is stale. This can fork or corrupt the canonical history and artifact head, the system's durability boundary.

**Required correction**

Define a takeover state machine that does not publish a new writable gateway until the old Pod is terminated/fenced, its attachment is detached or otherwise proven inaccessible, and the replacement exclusively mounts and verifies the volume. Same-node overlap must also be excluded. If the CSI profile cannot prove those properties, require a qualified storage-level fencing primitive or keep the shard unavailable rather than fail over. Add a paused-old-writer test that resumes between final epoch validation and fsync and proves it cannot mutate the volume.

### K8S-02 — High — The “closed” CRD inventory is internally incomplete

**Evidence**

- AD-33 calls ten named, namespaced kinds the closed v1 inventory.
- The same rule says each schema fixes parent, cardinality, references, limits, retention, field managers, conditions, and finalizer owner, but none of those values is inventoried per kind in the spine.
- AD-30 authorizes selected cross-namespace references through a “specific installation-owned grant resource,” but no grant kind or built-in resource appears in AD-33.
- Approval and authorization rules refer to policy references/generations without locating the authoritative policy object in the closed inventory.

**Problem**

An implementation can satisfy the names while choosing incompatible ownership and lifecycle models. More directly, the cross-namespace grant cannot be implemented without violating either AD-30 or AD-33. Policy authority is similarly ambiguous unless it is explicitly embedded in an existing binding.

**Required correction**

Add a normative per-kind inventory with group/version/kind, scope, parent, cardinality, spec/status/finalizer owner, allowed references, limits, and GC/retention. Add the grant kind to the closed set or remove cross-namespace grants. Locate policy authority in a named CRD field or add a policy CRD. This remains entirely Kubernetes-native.

### K8S-03 — High — A replacement Pod can authenticate as the same execution attempt

**Evidence**

- AD-13 sets `backoffLimit: 0` and `restartPolicy: Never`, then asserts “no automatic Pod replacement semantics.”
- A Kubernetes Job still reconciles toward its completion target and can create a replacement while a deleted/terminating Pod is not yet counted as a failed attempt; those two fields alone do not make a Job a one-Pod primitive.
- AD-29 validates Pod → Job → ExecutionAttempt ownership, active claim generation, and fence, but does not validate one CAS-recorded expected Pod UID for the attempt.

**Problem**

A replacement Pod owned by the same Job passes the stated ownership chain and can receive a fresh attempt credential for the same claim and fence. The protocol carries Pod UID, but no authoritative expected Pod UID is named against which it is checked. This defeats the exact-one-worker claim even though competing reconcilers are correctly serialized.

**Required correction**

Either use a directly owned Pod when one Pod incarnation is the invariant, or define every Job-created Pod incarnation as a new fenced attempt. Atomically bind the accepted Pod UID before credential issuance and reject all other Pods. Specify Job `podFailurePolicy`/`podReplacementPolicy`, termination handling, and the controller race with the built-in Job controller. AC-8 must delete and terminate Pods at each phase and prove that no replacement receives the old attempt credential.

### K8S-04 — High — The CRD workflow has no safe conversion-webhook or multi-installation ordering

**Evidence**

- AD-22 applies the version-matched CRD bundle before the application chart.
- It preflights conversion-webhook/certificate availability when conversion is required.
- AD-35 allows multiple installations to share the same cluster-global CRDs when versions are compatible.

**Problem**

A new conversion implementation or certificate configuration normally ships with application components, yet the new CRD is applied before those components. “Webhook available” does not establish that the old webhook can convert every newly served/storage version. Separately, two installations can race cluster-global CRD changes; compatibility checking without a singleton owner/upgrade claim does not serialize mutation or prevent one release from contracting a version still used by another.

**Required correction**

Specify the bootstrap sequence: deploy an N/N-1-compatible webhook and CA bundle first, prove conversion for old and new objects, then mutate the CRD, migrate storage, and only later contract. Define the no-webhook additive v1 path if that is the baseline. Add a cluster-scoped CRD lifecycle owner/lock and enumerate every installation/version that must acknowledge a contract step. Fault-test webhook outage, CA rotation, concurrent installers, and rollback at every boundary.

### K8S-05 — High — etcd and watch growth still have no enforceable lifecycle budget

**Evidence**

- AD-15 caps each serialized custom resource at 256 KiB and managed-field owners at eight.
- Terminal attempts, operations, and approvals are garbage-collected by “bounded count/age,” with no count or age.
- No terminal retention rule is given for `CodePlaneJob`, storage shards, repository locks/bindings, import sessions, backup epochs, or tenant resources.
- Qualification measures etcd bytes and LIST/watch cost but supplies no pass/fail ceiling.

**Problem**

Finite object size does not bound the number of objects. A long-running installation can accumulate terminal Job CRs and other parents indefinitely, while 256 KiB multiplied by the admitted queue already permits substantial etcd and watch pressure. A measurement without a threshold is not a release gate.

**Required correction**

Set numeric per-kind maximum live/terminal counts and ages, compact terminal-summary limits, Job/Pod TTLs, archive-before-GC rules, and installation/tenant etcd plus LIST/watch payload thresholds. State overload behavior before those limits are exceeded. Run sustained churn beyond the 365-day audit horizon and require convergence below the thresholds after GC.

## Non-blocking correctness gaps to close before schema/chart freeze

1. **K8S-06:** Specify how installation API replicas receive namespace-scoped access to enrolled tenants. AD-35 covers controllers, not the API service account that reads and mutates tenant CRDs. Prefer per-tenant RoleBindings over a wildcard cluster-wide API credential.
2. **K8S-07:** Publish the finite condition types, polarity, reasons, terminality, and manager for every CRD. Saying schemas will fix them is not yet an API compatibility contract.
3. **K8S-09:** Expand AC-7 to cover 410 expiry, normal watch closure, deletion during outage, restart with an empty work queue, duplicate add/delete, stale cache reads, and orphan cleanup.
4. **K8S-10:** Fix Lease namespace/name, holder identity, duration/renew/deadline, clock-skew assumptions, loss behavior, and RBAC. Test a paused old leader resuming after takeover for repository mutation, backup, and storage maintenance.
5. **K8S-11:** Define what an administrator can do when the storage gateway is unavailable and the required tombstone/audit append cannot succeed. Replace the unenforceable statement that namespace deletion “never” bypasses ordering with detectable degraded evidence and a documented cluster-admin disaster procedure.
6. **K8S-12:** Define BackupEpoch participant discovery, acknowledgement keys, stale-participant handling, timeout outcome, and bounded acknowledgement cardinality. Ensure controllers cannot register after the barrier snapshot without being included or blocked.

## Gate decision

The architecture is substantially closer to Kubernetes-native correctness and correctly avoids a PostgreSQL, S3, or external-state baseline. It is **not implementation-ready** until K8S-01 through K8S-05 above are resolved normatively and represented in acceptance tests. K8S-06 through K8S-12 are directionally sound; their listed follow-ups should be completed before CRD schemas, RBAC, controllers, and backup formats are frozen.
