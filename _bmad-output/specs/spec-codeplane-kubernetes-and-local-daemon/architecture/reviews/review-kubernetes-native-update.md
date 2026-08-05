# Kubernetes-Native Correctness Review

**Artifact reviewed:** `architecture/ARCHITECTURE-SPINE.md`  
**Review date:** 2026-08-05  
**Verdict:** **NEEDS REVISION**

The spine has the right Kubernetes-native direction: CRDs are authoritative, large bytes stay on CSI storage, reconciliation is level-triggered, attempts are fenced, and PostgreSQL, S3, and other external state services are optional rather than required. However, several contracts needed to make those claims implementable are still ambiguous or internally inconsistent. The storage baseline, CRD/scoping model, attempt creation semantics, and CRD upgrade mechanism are release-blocking.

## Findings

### K8S-01 — Critical — The baseline StorageClass contract cannot support the stated HA and concurrency model

**Evidence**

- AD-17 requires Kubernetes HA and PVC-backed history/artifacts.
- The operational envelope requires at least two API replicas across failure domains and up to 200 concurrent jobs.
- AD-21 and AC-3 say a conforming baseline needs only a compatible/default StorageClass.
- PVC access modes and layout are deferred, while API replicas and workers are shown directly accessing the storage port.

**Problem**

A typical default StorageClass provides `ReadWriteOnce`, often with topology constraints. It does not provide a filesystem safely mountable read/write by multiple API replicas and workers on different nodes. `ReadWriteOncePod` is even narrower, and `ReadWriteMany` is not universally available. The spine also requires per-job serialized history append but does not name the in-cluster serialization owner or the filesystem-locking semantics. Consequently, “any compatible StorageClass” cannot simultaneously satisfy HA, multi-node scheduling, and a shared PVC storage adapter.

**Required correction**

Define explicit qualified storage profiles and topology:

- which PVCs are per-installation, per-tenant, per-job, and per-attempt;
- required access modes and volume binding/topology behavior for each profile;
- the single-writer/serialization mechanism for canonical history;
- whether API replicas access files directly or through an in-cluster storage controller;
- failover behavior for RWO volumes and scheduling constraints;
- minimum capacity, expansion, reclaim, encryption, fsync/locking, and corruption guarantees.

AC-3 must select and test one profile rather than accepting an undefined “conforming StorageClass.” This can remain entirely Kubernetes-native; no external state service is needed.

### K8S-02 — High — The CRD set is not complete enough to realize the stated scoping and ownership rules

**Evidence**

- AD-33 names four CRDs: `CodePlaneJob`, `CodePlaneApproval`, `CodePlaneRepositoryBinding`, and `CodePlaneExecutionAttempt`.
- AD-4 relies on authoritative namespace/installation bindings.
- AD-24 relies on a namespaced repository/ref coordination resource.
- AD-30 allows an installation-owned grant resource for selected cross-namespace references.
- AD-33 permits unspecified separately owned provenance resources.

**Problem**

The authoritative tenant binding, repository/ref coordination, cross-namespace grant, and optional provenance resource are referenced but not defined. Their omission leaves implementations to use ConfigMaps, labels, annotations, or overloaded Job status despite AD-33 expressly rejecting ad hoc state. Scope, owner, lifecycle, and cardinality are also unspecified for every CRD. There is no authoritative answer to whether tenant bootstrap requires a cluster-scoped resource or how an installation proves that a namespace belongs to it.

**Required correction**

Add a normative CRD inventory containing, for every resource: API group/version/kind, Kubernetes scope, authoritative purpose, spec owner, status owner, parent/ownerReference, finalizer, cardinality, retention/GC rule, and allowed references. Explicitly define the namespace/installation binding and repository/ref lock model. If a referenced concept deliberately uses a built-in resource rather than a CRD, name that resource and its exact ownership contract.

### K8S-03 — High — “One Job/Pod per attempt” is not guaranteed by Kubernetes Job semantics

**Evidence**

- AD-13 says one `CodePlaneExecutionAttempt` plus one Kubernetes Job/Pod is created for each attempt.
- AC-8 requires exactly one active Job/Pod per attempt and one current attempt per job.
- Worker authentication binds both Job UID and Pod UID.
- The scheduling state diagram moves to admitted through “preconditioned attempt create.”

**Problem**

A Job is not a Pod identity. The Job controller may create a replacement Pod, and ordinary Job defaults allow retries. Binding an attempt to one Pod UID conflicts with Job-managed replacement. More importantly, creating an attempt resource and setting the Job's current-attempt reference are two writes, so a resourceVersion precondition alone does not explain how competing reconcilers avoid two child attempts.

The attempt fence is also described as immutable while stored in status. Status is controller-mutable; immutability needs an enforceable schema/admission rule. A fence exposed in broadly readable status must not be treated as a credential.

**Required correction**

Specify:

- the single authoritative atomic attempt claim on `CodePlaneJob`;
- deterministic child naming and adoption after crashes;
- whether each attempt means one Job or one Pod execution incarnation;
- `parallelism`, `completions`, `backoffLimit`, `restartPolicy`, deadline, deletion, and TTL behavior;
- how an unexpected replacement Pod becomes either a new fenced incarnation or a new attempt;
- where the fence lives, how write-once behavior is enforced (for example CEL validation), and how it is delivered without becoming a bearer secret.

### K8S-04 — High — Helm cannot implement the documented CRD upgrade contract by itself

**Evidence**

- AD-21 says the OCI Helm chart installs versioned CRDs.
- AD-22 requires served/storage version management, conversion/defaulting, storage migration, and rollback.
- The operational envelope says CRDs are applied before controllers.

**Problem**

CRDs placed in a chart's `crds/` directory are installed but not upgraded or deleted by Helm. Templating CRDs changes other lifecycle risks and still does not solve conversion-webhook availability, CA bootstrap, stored-version migration, or downgrade ordering. A Helm pre-upgrade Job cannot reliably validate a new CRD schema after Helm has already changed it, and cannot by itself make an unavailable conversion webhook safe. The spine therefore promises an upgrade order without naming a mechanism that can enforce it.

**Required correction**

Define the CRD lifecycle mechanism outside ordinary Helm CRD installation semantics: separate CRD chart/operator step or an explicit installer workflow, preflight before mutation, conversion webhook deployment and certificate bootstrap, `status.storedVersions` checks, storage-version migration completion, and rollback gates. State whether v1 avoids conversion webhooks by remaining schema-compatible; if not, qualify webhook outage and skew behavior.

### K8S-05 — High — etcd growth is called “bounded” but no enforceable bounds or garbage collection policy exist

**Evidence**

- AD-10 and AD-33 prohibit etcd bloat and unbounded status arrays.
- Scale includes 5,000 queued jobs.
- Approval and attempt resources are created separately, and lifecycle/audit retention can be 365 days.
- Jobs/Pods metadata are included in backup, while uninstall retains custom resources.

**Problem**

Avoiding event arrays is insufficient. Attempts, approvals, completed Jobs/Pods, conditions, immutable snapshots, and retained Job CRs can grow without limit over time. “Bounded metadata” has no byte, item, or age limit. Kubernetes' per-object limit does not protect total etcd size or watch/list cost.

**Required correction**

Set hard schema and lifecycle budgets: maximum object size, bounded condition types, maximum snapshot/reference sizes, maximum retained child resources, terminal-resource retention windows, Job TTL, and archive-before-GC rules. State which compact terminal summary remains in the Job CR and which details move to PVC history. Add long-duration churn tests that measure object count, list/watch payload, apiserver latency, and etcd footprint at and beyond AD-15.

### K8S-06 — High — Namespace isolation and Helm/controller topology are contradictory

**Evidence**

- AD-4 creates a tenant execution namespace while control services run in an installation namespace.
- AD-21 says Helm installs namespace-scoped controllers and RBAC.
- AD-30 permits an installation-scoped controller and says namespace-scoped informers are used “where practical.”
- Helm is expected to establish tenant resources in AC-3.

**Problem**

A controller confined to the installation namespace cannot watch or create resources in tenant namespaces. A controller with a ClusterRole can do so, but then it is not namespace-scoped in the security sense and compromise crosses every tenant. Deploying one controller per tenant avoids that blast radius but changes Helm lifecycle, quota scheduling, installation-wide policy, and leader election. Tenant namespace creation and binding also need cluster-scoped authority.

**Required correction**

Choose and document the controller topology. Separate installation-wide and tenant-local controllers if appropriate, with exact Role/ClusterRole verbs, namespace bootstrap ownership, informer scope, admission checks, and service accounts. Helm templates and tests must prove that omission of a namespace selector cannot widen access. Avoid wildcard resources/verbs and define who may create or bind tenant namespaces.

### K8S-07 — Medium — `observedGeneration` and condition semantics are not precise enough for sagas

**Evidence**

- AD-11 uses conditions for accepted intent, progress, history lag, and completion.
- AD-33 requires standard conditions with stable reason codes.
- Job/attempt status contains reconciliation substates.

**Problem**

The spine does not state when top-level `status.observedGeneration` advances: when a generation is merely read, when its intent is accepted, or only after all saga effects and durable history commit. These meanings differ during partial failure. It also does not define condition polarity, condition ownership, terminality, or whether every `metav1.Condition.observedGeneration` identifies the spec generation that produced it. Without this, clients can mistake a stale `Ready=True` for completion of the latest spec.

**Required correction**

Publish a condition contract per CRD: finite condition types, positive/negative polarity, owning reconciler, reasons, transition rules, and terminal behavior. Require `metav1.Condition`, list-map schema keyed by `type`, bounded condition count, and generation on every condition. Define top-level `observedGeneration` as acknowledgement only, with generation-matched conditions representing progress and completion, or select another unambiguous convention.

### K8S-08 — Medium — ResourceVersion preconditions and server-side apply ownership are conflated

**Evidence**

- The sequence diagram has the API issue “Preconditions + server-side apply.”
- AD-11 says Kubernetes mutations use resourceVersion/generation preconditions.
- Clients own spec intent; controllers own designated status fields.

**Problem**

`metadata.generation` is observational, not a general write precondition. `resourceVersion` is required for compare-and-swap updates, while SSA primarily manages field ownership and conflicts. Allowing multiple external clients to own mutable spec fields creates durable managedFields ownership conflicts and metadata growth. Conditions are especially conflict-prone unless their list schema and per-type ownership are explicit. Status updates and subresource apply also require distinct managers.

**Required correction**

Define mutation operations individually:

- external callers send expected resourceVersion/idempotency key to the CodePlane API;
- one stable API field manager owns user-intent spec fields on their behalf;
- reconcilers use status update/patch or SSA on `/status` with disjoint managers;
- generation is checked by reconcilers, not used as a substitute for resourceVersion;
- force apply is restricted to a versioned ownership migration procedure.

Specify managedFields compaction expectations and condition-type ownership.

### K8S-09 — Medium — Watch recovery is stated but not algorithmically safe

**Evidence**

- AD-33 says controllers tolerate duplicate/out-of-order delivery and relist after watch loss.
- AC-7 tests watch relist.

**Problem**

“Relist after watch loss” omits the list/watch handoff and deletion recovery. Watches can close normally, fail with an expired resourceVersion, or lose local queue state. Relisting only changed resources can miss deleted parents and leave orphaned Jobs/PVCs. There is no startup rule for adopting existing dependents or rebuilding delayed work.

**Required correction**

Require an informer-equivalent list/watch contract: initial list, watch from the returned list resourceVersion, reconnect from the last processed version, full relist on expiration, enqueue every listed object after relist, and reconcile owned dependents/orphans. Reconciliation must derive state from current objects rather than edge events. Add tests for `410 Gone`, disconnect without an error event, process restart with an empty queue, deletion during outage, duplicate add/delete, and stale cache reads.

### K8S-10 — Medium — Lease use is not explicitly advisory and does not itself fence a stale leader

**Evidence**

- AD-13 uses `coordination.k8s.io/v1 Lease` for active/standby coordination.
- AD-24 says a Lease may back liveness but cannot replace durable ref intent.

**Problem**

A controller that pauses past the Lease deadline can continue running after another controller acquires the Lease. Lease ownership alone cannot guarantee exclusive side effects. The spine protects attempt claims with resourceVersion, but does not explicitly apply a fencing generation to every non-idempotent action performed under leadership, especially storage migration, repository mutation, and backup quiescence.

**Required correction**

State that Leases optimize coordination only and are never a correctness boundary. Every side effect must remain idempotent or validate a durable CRD claim/fencing epoch immediately before commit. Define Lease namespace/name, identity, duration/skew assumptions, loss behavior, and permissions. Test a paused old leader resuming after takeover.

### K8S-11 — Medium — OwnerReference and finalizer behavior lacks failure and retention boundaries

**Evidence**

- AD-14 uses ownerReferences for propagation and finalizers for outcomes, storage, secrets, PVC/workspace cleanup, and coordination release.
- AD-30 forbids cross-namespace ownerReferences.
- Uninstall and retention rules preserve CRDs/PVC data by default.

**Problem**

The hierarchy and deletion propagation policy are not specified. A PVC ownerReference can violate retained-data policy; withholding it can leak volumes. “Revoke secrets” risks deleting operator-owned Secrets rather than only releasing ephemeral credentials. Finalizers that depend on a failed storage adapter, missing namespace, or unavailable external Git provider can block deletion indefinitely. There is no break-glass procedure or proof that evidence is committed before children disappear.

**Required correction**

Define the exact owner graph (`Job → Attempt → Job → Pod`, or its chosen equivalent), propagation policy, PVC retention ownership, and which controller owns each finalizer. Distinguish operator Secrets from per-attempt ephemeral material. Require resumable finalizer phases, bounded retry/backoff, visible failure, administrator force-finalize procedure with an audit record, and a retention-safe order of operations.

### K8S-12 — High — Backup and VolumeSnapshot semantics do not establish a consistent recovery point

**Evidence**

- AD-17 permits CSI VolumeSnapshot or quiesced filesystem copy.
- Backup quiesces writers at a durable high-water mark, exports Kubernetes resources, and snapshots PVCs.
- The platform may have many PVCs and multiple writers.

**Problem**

`VolumeSnapshot` is per volume and is not inherently application-consistent or atomic with CRD export. Multiple PVCs cannot be assumed to share a point in time unless a qualified group-snapshot capability exists. A writer may advance status or append history between quiescence, CRD export, and snapshot creation. Snapshot readiness does not prove the filesystem was flushed. The fallback copy also needs a separate failure-isolated destination and capacity contract.

**Required correction**

Define a backup epoch protocol persisted in Kubernetes state: block new appends, drain/flush every writer, record per-volume high-water marks and hashes, snapshot/copy, wait for readiness, export matching CRD resourceVersions, then release. Either require a qualified VolumeGroupSnapshot profile where used or explicitly reconcile independent snapshots through the manifest and reject nonmatching epochs. Specify restore ordering, partial-snapshot cleanup, fallback destination isolation, and tests with crashes at every phase.

## Coverage Summary

| Review area | Assessment |
| --- | --- |
| CRD set and scoping | Incomplete; authoritative resources and scope inventory missing |
| spec/status, observedGeneration, conditions | Correct direction; exact semantics and ownership missing |
| reconciliation and watch recovery | Level-triggered intent is sound; recovery algorithm underspecified |
| resourceVersion and SSA | Both present; responsibilities are conflated |
| ownerReferences/finalizers | Correct primitives; lifecycle/failure boundaries incomplete |
| Jobs/Pods per attempt | Release-blocking ambiguity around Job retries and atomic claim |
| Kubernetes Lease | Correctly limited in some places; stale-leader fencing must be universal |
| stale worker fencing | Strong identity checks; immutable fence and Pod replacement model need definition |
| PVC/StorageClass/VolumeSnapshot | Release-blocking topology and consistency gaps |
| namespace/RBAC isolation | Strong intent; controller/Helm topology contradicts it |
| Helm packaging | Baseline dependency rule is good; CRD lifecycle mechanism missing |
| upgrade/conversion | Directionally correct; not executable with ordinary Helm behavior |
| etcd bloat | Large bytes are correctly externalized; cardinality/retention bounds missing |
| external state dependency | Pass: no PostgreSQL, S3, or external state service is required |

## Release Gate

Do not treat the Kubernetes architecture as implementation-ready until K8S-01 through K8S-06 and K8S-12 have normative resolutions and acceptance tests. K8S-07 through K8S-11 should be resolved before CRD schemas and controllers are frozen because each affects API compatibility or failure recovery.
