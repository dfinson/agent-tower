# Incompatibility Review — Kubernetes Update

**Artifact reviewed:** `architecture/ARCHITECTURE-SPINE.md` only  
**Review method:** Adversarial construction of independently implemented units that each satisfy the spine literally, followed by collision testing at their boundaries.  
**Verdict:** **NOT IMPLEMENTATION-COMPATIBLE**

The spine has strong intentions, but it does not yet constrain ownership, ordering, identity bootstrap, or storage topology enough for independently built compliant units to interoperate. Several acceptance criteria are consequently unimplementable under the stated baseline. The failures below are architecture-contract failures, not requests for implementation detail.

## Independently Compliant Units Used for Collision Testing

| Unit | Literal compliant interpretation |
| --- | --- |
| API command unit | Applies client-owned spec intent, appends required history, handles authenticated worker callbacks, and updates current status. |
| Job reconciler | Watches `CodePlaneJob`, updates conditions/`observedGeneration`, creates attempts, and finalizes jobs. |
| Attempt reconciler | Creates one Job/Pod per attempt, maintains liveness and attempt status, rejects stale attempts, and cleans up execution resources. |
| Admission reconciler | Computes tenant/repository/FIFO admission and writes bounded queue/admission status. |
| Storage/history adapter | Serializes per-job canonical appends and stores large bytes on CSI-backed PVCs. |
| Storage maintenance controller | Commits/tombstones artifacts, compacts history, snapshots PVCs, and reports degradation. |
| Identity/RBAC unit | Provisions service accounts/RBAC and verifies worker and tenant identity. |
| Upgrade unit | Applies CRDs before controllers, supports N/N-1, migrates stored versions and PVC formats, and permits bounded rollback. |
| Local adapter | Uses SQLite/filesystem/local processes while preserving shared service/API/event semantics. |

Every unit above can be built to the stated rules and still conflict with another compliant unit.

## Findings

### 1. No normative per-field ownership contract exists for CRDs and status

**Severity: Critical**

AD-11 declares broad classes of ownership (“clients own spec intent” and “controllers own designated status fields”), while AD-33 permits bounded provenance to be embedded or split into another resource. It never identifies the designated fields, condition types, finalizers, or field-manager names for each CRD. The API callback unit, job reconciler, attempt reconciler, admission reconciler, and storage controller all have legitimate reasons to update `CodePlaneJob.status`, `CodePlaneExecutionAttempt.status`, `observedGeneration`, and conditions.

Two compliant implementations can therefore:

- own the same condition entry under different field managers;
- replace one another’s conditions if the CRD does not declare `conditions` as an associative list keyed by `type`;
- disagree whether admission, attempt, history, and provenance state is embedded in `CodePlaneJob` or separately owned;
- advance one global `observedGeneration` even though only one controller has reconciled its part;
- add or remove the same finalizer with incompatible cleanup assumptions.

Resource-version retries do not resolve semantic overwrite. Server-side apply merely makes the collision visible, and force-apply is prohibited.

**Required architecture change:** Define a normative CRD/resource decomposition and an ownership table covering every spec field, status field, condition type, finalizer, ownerReference, and field-manager identity. Declare list-map keys and whether each field is SSA-, merge-patch-, or status-update-owned. Define per-controller reconciliation markers instead of relying on one ambiguous `observedGeneration`.

### 2. Attempt creation is not atomic and does not prevent duplicate live workers

**Severity: Critical**

AD-13 says optimistic `resourceVersion` preconditions select the winning attempt, but attempt creation, active-attempt publication, and Job creation are three resources/operations. Two active reconcilers can each observe no active attempt, create distinct attempt objects (especially with generated names), and create distinct Jobs before either wins the update of the job’s active-attempt reference. Both have valid immutable UIDs and fences. Rejecting the loser’s callbacks limits stale writes but does not satisfy “exactly one active Job/Pod,” resource quotas, credential exposure, or side-effect prevention.

The cross-resource saga rule in AD-11 allows partial progress but provides no required claim sequence, deterministic identity, or loser behavior for this safety-critical path. Leader election is optional, so it cannot be assumed to serialize the operation.

**Required architecture change:** Specify a single-resource admission/attempt claim CAS before any execution resource is created, deterministic attempt identity per claim generation, the exact sequence for publishing the fence and creating the Job, and mandatory loser cleanup. State whether attempt creation is active/active-safe or requires one elected writer. Add a test that pauses both reconcilers after each operation boundary, not only a stale-callback test.

### 3. Worker identity requirements have a circular bootstrap

**Severity: Critical**

AD-3 and AD-29 require worker identity and messages to be bound to Job UID, Pod UID, attempt UID, fence, tenant, namespace, service account, and negotiated protocol. The controller can know the attempt and Job UID before Pod startup, but the Pod UID does not exist when the Job template, projected token, or initial worker configuration is created. A standard projected service-account token does not automatically carry the CodePlane attempt UID or fence. AD-6 simultaneously disables Kubernetes API credentials in the worker unless an adapter explicitly requires them.

An identity unit can correctly issue an audience-restricted service-account token, while a worker unit can correctly refuse to connect without all required bindings; the result is a worker that cannot bootstrap. Alternatively, putting the fence in the Pod spec makes it visible but does not cryptographically bind it to the service identity, and permitting the worker to discover itself from the Kubernetes API expands RBAC beyond the baseline.

**Required architecture change:** Define a two-stage bootstrap protocol: which claims are initially verifiable, how the worker proves Pod identity, who exchanges that proof for a CodePlane attempt credential, how the Pod UID/fence are bound, token audience/TTL/renewal behavior, and how bootstrap is revoked when the active attempt changes. Distinguish canonical attempt ID from Kubernetes object UID everywhere.

### 4. The baseline PVC claims are mutually incompatible

**Severity: Critical**

The topology requires at least two API/controller replicas across failure domains, workers, storage maintenance, and backup processes to reach PVC-backed history/artifacts. Yet AD-21/AC-3 claim that any conforming StorageClass is sufficient, while access modes and filesystem layout are deferred. A conforming `ReadWriteOnce` StorageClass cannot provide concurrent cross-node mounting to all of these units. `ReadWriteOncePod` is even narrower. `ReadWriteMany` is not universally available and cannot be silently required.

The topology also draws workers directly to storage, while AD-3 routes worker events through the authenticated control API and AD-10 assigns authoritative history to the storage adapter. A compliant worker may write uploads directly; a compliant control API may assume workers can never mutate storage. Both satisfy different diagrams/rules.

This also makes the quiesced snapshot fallback under AD-17 unsafe: no protocol defines how all API replicas, workers, and maintenance reconcilers stop and acknowledge writes at one high-water mark.

**Required architecture change:** Choose and specify one baseline topology: for example, a single-writer storage service over RWO PVCs, per-tenant/per-job PVC ownership with explicit transfer, or an explicit RWX prerequisite. Define which components may mount which PVCs, mount modes, node/failure-domain behavior, upload protocol, append serialization, and quiescence fencing. Narrow AC-3’s StorageClass claim accordingly.

### 5. Canonical history ordering has no distributed serialization contract

**Severity: High**

AD-31 says the storage port serializes append per job and returns sequence/hash, but the required Kubernetes adapter is described only as PVC-backed bytes. Multiple API replicas can concurrently append worker events, commands, audit-linked transitions, and reconciler outcomes. A Python/process lock is insufficient across replicas; ordinary filesystem append and rename do not allocate a hash-chain sequence atomically across nodes; and Kubernetes object `resourceVersion` does not cover PVC bytes.

The ordering rules also disagree about allowed states. AD-31 permits status high-water advancement only after history commit, whereas AD-12 defines behavior when history is behind status. If “status” means canonical current state, the API command saga can mutate spec/current status before durable history and create precisely the state AD-11 says must not be reported as successful. If it means only the high-water field, the degradation case should be impossible except corruption. Independent API and history units can make opposite, locally reasonable choices.

**Required architecture change:** Define the distributed append primitive and its fencing/lease semantics, recovery after writer death, idempotency-key-to-event mapping, and sequence allocation. Provide a state-transition table for intent, domain status, durable event, high-water update, response, and SSE publication, including every crash boundary.

### 6. Kubernetes RBAC cannot enforce the stated human authorization model as written

**Severity: High**

AD-5 says Kubernetes RBAC limits namespace/resource/verb access, but the topology exposes humans through FastAPI ingress, not through direct Kubernetes API requests. Kubernetes sees the API service account, not the OIDC user, unless the API uses Kubernetes impersonation or obtains per-user credentials. Neither is specified. A compliant API can perform application authorization and use its own broad service account; a compliant RBAC package can deny that service account tenant mutations. The former defeats the Kubernetes-RBAC claim and the latter breaks the product.

AD-21 additionally says Helm installs namespace-scoped controllers/RBAC, while AD-4 permits many tenant namespaces and AD-30 permits installation-scoped control where practical. Namespace-scoped informers cannot discover arbitrary future tenant namespaces. A controller able to provision RoleBindings in new namespaces needs installation/cluster privileges that conflict with the “namespace-scoped controllers” packaging statement.

**Required architecture change:** Separate human application authorization from Kubernetes workload RBAC explicitly, or define safe impersonation. Specify tenant namespace enrollment, authoritative namespace/tenant binding, dynamic RoleBinding provisioning, controller watch topology, and the exact cluster-scoped permissions needed. State whether one installation is cluster-singleton or how multiple installations share cluster-scoped CRDs.

### 7. Server-side apply is assigned to actors, not operations

**Severity: High**

“Clients own spec intent” is not a usable SSA contract. If each human/API client gets a unique field manager, later legitimate commands conflict on fields previously touched by another client. If all API clients share one manager, ownership no longer represents independent intent and a stale apply can overwrite a newer command unless the resourceVersion precondition is consistently embedded. Imperative commands such as cancel, resume, resolve, and approval are also not naturally mergeable desired fields.

Persisting idempotency keys “on the authoritative resource” is likewise underspecified: an unbounded key set violates bounded CRD state, while retaining only the latest key permits replay of older commands after pruning. Different units can choose incompatible retention windows and return different outcomes for the same retry.

**Required architecture change:** Define field managers by trusted subsystem, not end client; define the patch/precondition form for each command; identify atomic versus granular fields; specify conflict responses and ownership transfer; and define a bounded idempotency record with retention, hash, replay result, and durable-history linkage.

### 8. Finalizer responsibilities overlap and have no ordering or escape policy

**Severity: Critical**

AD-14 assigns finalizers outcome capture, storage-reference finalization, secret revocation, PVC/workspace deletion, and repository/ref release. These are owned by different independently compliant controllers and have hard dependencies: outcome/history must commit before workspace deletion; credential revocation may be required before Job deletion; repository locks must survive until resolution evidence is durable. Kubernetes does not order finalizers. OwnerReference propagation may delete an execution Job before an outcome controller finishes, while a storage finalizer may delete bytes another finalizer still needs.

AD-33 restricts finalizers to external cleanup, which conflicts with using them to capture internal outcomes or write canonical history. Namespace deletion, controller uninstall, expired credentials, unavailable storage, or an N-1 controller that no longer understands a new finalizer can leave resources terminating forever. “Expose progress/failure” does not define who may remove a permanently failing finalizer or what evidence is retained after forced cleanup.

**Required architecture change:** Define one cleanup orchestration owner or a durable cleanup phase machine with explicit dependency order. Assign each finalizer to one controller and external resource, define adoption across versions, namespace-termination behavior, retry/backoff/dead-letter state, operator force-removal policy, and the minimum tombstone/audit evidence required before escape.

### 9. CRD installation and N/N-1 upgrade behavior are not operationally realizable

**Severity: High**

AD-21 says Helm installs versioned CRDs and AD-22/packaging says CRDs are applied before controllers. Helm does not upgrade CRDs placed in a chart’s `crds/` directory. Templates/hooks can update them, but then lifecycle, ownership, rollback, and permissions differ. The spine does not choose a mechanism.

During rolling upgrade, old and new active/active controllers can reconcile the same resources with different defaults, condition reasons, storage formats, and field ownership. N/N-1 protocol compatibility does not make reconciliation semantics compatible. Optional leader election means version skew can produce ping-pong even when both versions are individually valid. Conversion/defaulting availability, webhook certificate lifecycle, failure policy, stored-version migration completion, and downgrade blocking are not defined.

Cluster-scoped CRDs also collide across multiple CodePlane installations: two charts can independently attempt incompatible CRD upgrades even though each installation is declared one instance.

**Required architecture change:** Specify the CRD lifecycle mechanism and cluster ownership model, conversion strategy, stored-version migration gate, mixed-controller-version ownership rules, leader/drain behavior during rollout, webhook availability, and rollback boundary. Add an explicit singleton/multi-installation rule for cluster-scoped definitions.

### 10. The CRD set is insufficiently closed for independent implementations

**Severity: High**

AD-33 mandates four CRDs, but other rules rely on an authoritative namespace/installation binding, installation-owned cross-namespace grants, policy/version references, tenant/repository admission state, storage references, imports, and repository/ref coordination resources. Some are described as resources; others may be embedded. No rule says which are CRDs, built-in resources, or application data.

One team can legitimately embed coordination and policy snapshots in `CodePlaneJob`; another can introduce separate CRDs. Their controllers, RBAC, backup manifests, finalizers, retention behavior, and upgrade paths will not interoperate. “Where ownership and size remain clear” is a design instruction, not a compatibility constraint.

**Required architecture change:** Publish the complete v1 API resource inventory with scope, identity, owner, lifecycle, size bound, backup/restore treatment, status contract, and reference rules. Mark extensible resources explicitly; do not leave core coordination resources implementation-selectable.

### 11. Tenant identity is authoritative in principle but undefined in mechanism

**Severity: High**

AD-4 requires every request and reconciliation to derive tenant identity from authoritative namespace/installation bindings, and AD-30 refers to a specific installation-owned grant resource. Neither resource or lookup protocol is defined. Namespace name is mutable only by recreation, while namespace UID changes on recreation and restore. Storage paths use immutable tenant/resource UIDs, but restored CRDs receive new UIDs and must remap old storage. A stale controller cache, recreated namespace with the same name, or imported tenant can therefore produce different tenant conclusions in compliant units.

**Required architecture change:** Define the installation and tenant-binding resource(s), immutable tenant canonical ID, namespace UID binding, enrollment/revocation sequence, cache consistency requirements, and behavior on namespace recreation/import/restore. Require every token, storage path, cursor, and reference check to use the same binding generation.

### 12. Repository/ref ownership does not cover the dangerous cross-mode case

**Severity: High**

AD-24 correctly serializes mutation within Kubernetes but explicitly leaves independent local and Kubernetes instances to operator assignment. That is not fencing: two individually compliant instances can both push/merge the same ref, and neither can detect that its ownership assignment is stale. The architecture’s stated goal is to construct independent compliant units without conflict; declaring the conflict “unsupported” does not prevent it, especially when cross-mode import/export preserves repository logical identity.

The repository lock also depends on the attempt fence, but cleanup/finalizer failure can retain a lock after an attempt is no longer current, while force-removal can release it before durable resolution evidence.

**Required architecture change:** Either narrow the product contract so a repository/ref is registered to exactly one instance with a remotely verifiable ownership lease, or add provider-side compare-and-swap expectations (expected remote OID) to every mutation and define conflict recovery. Bind lock release to durable resolution state, not merely attempt cleanup.

### 13. Local/Kubernetes “shared semantics” exclude material lifecycle differences without contracts

**Severity: High**

AD-1 requires mode branches to have intentional-difference contracts, but only the workstation features in AD-25 and isolation in AD-32 are clearly treated that way. AD-13/AC-9 makes local restart resume the same process/session path while Kubernetes interruption creates/replaces attempts. Local commands can commit state/history atomically; Kubernetes commands expose in-progress/degraded saga states. Local identity is one OS user; Kubernetes approvals and tenancy use versioned OIDC/RBAC bindings. Local storage is direct filesystem/SQLite; Kubernetes may pause SSE on history degradation. These differences affect observable API states, attempt provenance, event ordering, retryability, and timing.

AC-1 asks for equivalent lifecycle output without defining equivalence over attempts, conditions, degraded states, restart events, and audit actor identity. Two adapter teams can pass their own fixtures while disagreeing on what the shared contract ignores.

**Required architecture change:** Create a normative semantic parity matrix for every command and state transition: shared inputs/outputs/events, permitted extra conditions, attempt identity behavior, failure mapping, success boundary, ordering, and explicit intentional differences. Run the same black-box fixture against both modes and compare a defined normalized transcript.

### 14. Backup quiescence conflicts with availability and controller independence

**Severity: High**

The backup procedure requires storage controllers to quiesce affected writers at a durable high-water mark, but no global or per-tenant scheduling/write barrier exists. API replicas may still accept commands, workers may upload artifacts, and reconcilers may append outcomes while the storage controller snapshots. A barrier represented only in one CRD is not atomic with PVC writes; a barrier represented only in storage is invisible to APIs until after a race.

A filesystem-level snapshot/copy is claimed as a fallback for any qualified StorageClass, but a long copy under AD-15 load can exceed availability or RPO objectives and cannot be crash-consistent without a writer protocol. Local mode has an explicit retention pause and SQLite snapshot; Kubernetes lacks an equivalent defined primitive.

**Required architecture change:** Define a generation-fenced backup barrier observed by every writer, acknowledgment and timeout rules, how accepted commands are queued/rejected during quiescence, snapshot cut identity, and resume/recovery behavior. Qualify copy fallback separately by data size and RTO rather than treating it as equivalent to CSI snapshots.

## Cross-Unit Collision Summary

| Collision | Result |
| --- | --- |
| API status writer × reconcilers | SSA conflicts or lost conditions; ambiguous success/high-water state |
| Two attempt reconcilers | Two valid attempts/Jobs before active-reference CAS |
| Worker × identity unit | Cannot obtain credential already bound to not-yet-known Pod UID |
| HA API × RWO storage | Required replicas cannot concurrently mount baseline PVC |
| API replicas × history adapter | No distributed sequence/hash-chain allocator |
| Human OIDC × Kubernetes RBAC | Kubernetes authorizes the API service account, not the human |
| Finalizer controllers × owner GC | Cleanup order races and can erase required evidence |
| N controller × N-1 controller | Status/condition/default/storage ping-pong |
| Local adapter × Kubernetes adapter | Different observable success, restart, attempt, and degradation semantics |
| Backup controller × active writers | Snapshot high-water mark is not a consistent cut |

## Minimum Compatibility Gates Before Implementation

1. Freeze a complete v1 CRD inventory and per-field/controller ownership matrix.
2. Specify an executable attempt-claim and worker-credential bootstrap state machine.
3. Choose a PVC access/writer topology that works on the actual minimum StorageClass contract.
4. Define distributed history append, status/history ordering, and backup fencing protocols.
5. Define tenant binding, controller privilege topology, and the boundary between human authorization and Kubernetes RBAC.
6. Define cleanup/finalizer ordering and mixed-version controller/CRD lifecycle.
7. Publish a normalized cross-mode semantic transcript contract, including all intentional differences.

Until these gates are resolved, separate teams can implement every stated invariant and still ship components that deadlock, conflict under SSA, run duplicate workers, fail on ordinary StorageClasses, or disagree on canonical state.
