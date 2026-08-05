# Focused Operability Review — Kubernetes Update

**Artifact reviewed:** `architecture/ARCHITECTURE-SPINE.md`  
**Review date:** 2026-08-05  
**Verdict:** **NOT OPERABLE AS A SELF-CONTAINED KUBERNETES BASELINE — major revision required**

## Executive assessment

The spine has credible safety invariants: bounded CRD state, attempt fencing, explicit durability boundaries, N/N-1 compatibility, finalizer-driven cleanup, and restore verification are all useful foundations. It does not yet define a deployable and supportable Kubernetes product. Most operational promises are outcomes without the mechanisms, ownership, defaults, or failure procedures needed to achieve them.

The central claim is internally inconsistent. AD-21 and AC-3 imply that Kubernetes plus a conforming `StorageClass` is sufficient for a baseline install, while the operational envelope requires OIDC, ingress or Gateway, DNS, TLS, an authenticated job-policy egress gateway, conforming NetworkPolicy enforcement, and node-metadata protection. The chart does not install several of those components. A private-repository agent job also necessarily needs external egress, credentials, and an agent provider. Therefore AC-3 cannot be executed in the environment it describes.

## Coverage summary

| Review area | Assessment |
| --- | --- |
| Install prerequisites | Contradictory; no executable preflight or minimal/production profile |
| Controller HA | Replicas are stated, but placement, coordination, failover, and storage coupling are undefined |
| Quotas/fairness at 5,000 queued jobs | Intent exists; queue algorithm, etcd/API budgets, starvation rules, and completed-resource GC do not |
| PVC lifecycle and topology | Critical access-mode, zone, reclaim, expansion, ownership, and failover decisions are deferred |
| Snapshot fallback | Quiesced copy is not shown to satisfy consistency or five-minute RPO |
| Backup/restore drills | Verification is described; cadence, independent copies, clean-cluster recovery, and evidence are absent |
| Upgrade/rollback | Compatibility intent is good; Helm CRD mechanics and irreversible migration control are missing |
| CRD uninstall | Default retention is safe, but the destructive cleanup procedure is not safe or complete |
| Observability/conditions | Signals are named, but no condition contract, cardinality policy, alerts, or runbooks exist |
| Egress gateway | A mandatory external subsystem has no ownership, HA, scaling, or failure contract |
| Worker isolation | Desired Pod controls are strong; enforceability, admission qualification, defaults, and capacity controls are incomplete |
| Failure recovery | Fencing is strong; retry budgets and component-by-component recovery behavior are unspecified |
| Self-contained baseline | No; the stated baseline depends on substantial operator-supplied infrastructure |

## Findings

### OP-01 — Critical — The “self-contained baseline” claim is false

AD-21 says the chart has no external state prerequisite and AC-3 says a clean install needs only a conforming `StorageClass`. The operational envelope instead requires operator-supplied OIDC, ingress/Gateway, DNS, TLS, an authenticated egress gateway, NetworkPolicy enforcement, and node-metadata protection. AD-19 also explicitly makes ingress operator-managed. The chart footprint does not include an identity provider, ingress/Gateway controller, certificate automation, egress gateway, CNI, or metadata protection.

**Action:** Define two explicit installation profiles. A genuinely self-contained functional profile must install every runtime dependency needed to complete its acceptance job, including the egress-policy component, or use a clearly documented built-in alternative. A production profile may depend on operator infrastructure, but must enumerate supported implementations and required capabilities. Replace “only a conforming StorageClass” with an executable prerequisite matrix and make Helm preflight fail before mutation when any mandatory capability is absent.

### OP-02 — High — Installation has no deterministic preflight or readiness contract

The spine lists prerequisites but not how the installer proves them. “Conforming” NetworkPolicy, metadata protection, CSI behavior, and gateway bypass prevention are behavioral properties, not discoverable API presence. Snapshot support is “detected and reported,” but no destination for that report or installation consequence is defined. There is no check for default-deny support, `WaitForFirstConsumer`, volume expansion, required access mode, Pod Security admission, DNS reachability, image architecture, registry pull, certificate readiness, OIDC claim shape, or gateway connectivity.

**Action:** Specify a versioned preflight Job and a post-install qualification Job. Publish machine-readable installation conditions and stable failure reasons. Distinguish fatal, production-blocking, and optional checks. Require `helm --wait` success to mean the API, controllers, storage, worker creation, identity, and egress path are ready—not merely that Deployments are available.

### OP-03 — Critical — PVC access mode and topology are unresolved architecture, not adapter detail

The API replicas, controllers, storage maintenance, and workers all interact with PVC-backed storage, but the spine defers access modes and layout. A generic `ReadWriteOnce` `StorageClass` cannot provide a multi-zone shared storage port to two API replicas and arbitrary workers. `ReadWriteOncePod` is even more restrictive; RWX is not universally available. `WaitForFirstConsumer`, zone-local PVs, node loss, detach delays, and snapshot topology can prevent failover within the claimed SLO. Per-attempt PVC creation, cache-generation ownership, reclaim policy, expansion, low-space behavior, tenant deletion, legal hold, and orphan adoption are not defined.

**Action:** Select a baseline topology: for example, require a qualified RWX class for shared history/artifacts and use per-attempt RWO PVCs, or place a replicated storage service in front of RWO volumes. Define PVC templates, access modes, binding mode, topology constraints, ownership/finalizers, reclaim behavior, expansion thresholds, capacity alerts, restore mapping, and garbage-collection state machine. Qualify failover across zones, including forced detach and a stuck `Pending` volume.

### OP-04 — High — Five thousand queued CRs have no etcd/API-server budget or lifecycle

“Bounded status” prevents unbounded arrays inside one object; it does not bound total etcd use. The spine does not cap serialized CR size, number of status writes, managed-fields growth, LIST payload size, watch fan-out, relist frequency, or retained completed CRs. A continuing workload can accumulate finalized `CodePlaneJob`, approval, binding, and attempt resources indefinitely even if each object is bounded. Controller restarts may rebuild a 5,000-item queue through expensive full LISTs, and per-position status updates could create avoidable etcd churn.

**Action:** Add a Kubernetes API capacity budget to AD-15: maximum object sizes, total objects by kind, managed-field owners, status writes per transition, controller QPS/burst, LIST/relist latency, watch-cache behavior, and etcd bytes under the load test. Persist no queue-position churn. Define archival and TTL/GC rules for completed attempts, approvals, Jobs, Pods, and eventually job CRs while retaining canonical history on the storage port. Gate release on measured etcd database growth and compaction behavior, not only job latency.

### OP-05 — High — Weighted admission is not a fairness algorithm

“Tenant, repository, then FIFO” does not define weights, tie-breaking, aging, reservation, or starvation prevention. It is unclear whether quotas cover queued, admitted, running, waiting-for-approval, and retrying work; whether one identity can fill a tenant’s 5,000 queue slots; or how quota is reclaimed after controller failure. There is no deterministic reconstruction rule after failover and no protection against a hot repository or retry storm monopolizing admission.

**Action:** Define the scheduler precisely: queue key, deterministic ordering, weighted-share calculation, aging, per-tenant/repository/identity queued and active limits, retry accounting, starvation bound, and atomic quota claim/release. Rebuild the in-memory index from authoritative CR fields without writing queue positions. Add adversarial load tests with skewed tenants, retries, cancellation, and controller restart, and assert maximum wait and API-write budgets.

### OP-06 — High — Controller HA is asserted but not operationally designed

Two replicas and a PDB do not establish HA. There is no required pod anti-affinity or topology spread, minimum available behavior during node drain, lease duration/renew/deadline settings, failover objective, clock-skew assumption, per-controller active/active safety classification, or handling of a leader stuck behind an API partition. Storage topology may make the surviving replica useless. No API Priority and Fairness or client rate-limit policy protects controllers during a storm.

**Action:** Publish a controller HA matrix. For each reconciler, state active/active versus leased ownership, lease timings, idempotency boundary, failover target, and duplicate-work behavior. Require topology spread across zones/nodes, PDB and rolling-update settings that compose, readiness that includes required dependencies, client QPS/backoff, and chaos tests for leader loss, API partition, watch closure, node drain, and simultaneous rollout.

### OP-07 — High — The filesystem-copy snapshot fallback cannot substantiate RPO/RTO

“Quiesce writers and copy to another PVC” omits the protocol that establishes a consistent cut. It does not say how every API/worker writer acknowledges the freeze, how an RWO source is mounted by the copier, how long scheduling may pause, what happens when the copy exceeds the five-minute RPO interval, or how a partial copy is resumed or discarded. A second PVC in the same cluster, zone, or storage system is not a disaster-recovery copy. Full-copy duration and capacity scale with retained history and artifacts.

**Action:** Specify a freeze epoch and high-water handshake, writer drain timeout, mount/topology procedure, copy format, resumability, bandwidth/capacity checks, and atomic last-known-good publication. Either make CSI snapshots mandatory for the five-minute production RPO or assign the copy fallback a separately measured, weaker SLO. Require an independent fault domain/off-cluster copy for disaster recovery.

### OP-08 — High — Backup/restore “drills” have no drill program

The restore flow is directionally sound, but there is no minimum cadence, backup schedule, retention count, freshness alert, clean-cluster drill, evidence artifact, owner, or failure escalation. Resource export excludes Secret values without defining how required secret material, signing keys, TLS keys, VAPID keys, OIDC client credentials, and encryption/KMS dependencies are recovered or remapped. The chart/CRD/controller versions and cluster prerequisites needed to interpret a backup are not explicitly captured.

**Action:** Define scheduled backups and a drill runbook with owners and frequency. Capture chart/image digests, CRD schemas and stored versions, backup tool version, prerequisite manifest, and required external-secret remapping without embedding plaintext secrets. Drill into a clean replacement cluster and a different failure domain; verify private-repository execution after restore. Export signed drill evidence containing measured RPO/RTO and alert when the last verified restore exceeds policy.

### OP-09 — Critical — Helm CRD upgrade and rollback mechanics are missing

“CRDs are applied before controllers” is insufficient. Helm does not upgrade or delete CRDs placed in a chart’s `crds/` directory. Templated CRDs have different ownership and rollback hazards. Conversion webhooks must remain available while old and new objects are served; a failed webhook rollout can make resources unreadable. The spine does not define who owns CRD application, how stored-version migration is paused or resumed, how writes remain N-1 compatible during migration, or how the irreversible contract gate is approved and audited.

**Action:** Define an explicit CRD lifecycle mechanism outside ordinary Helm rollback: server-side-applied CRD bundle or dedicated operator tool, compatibility/preflight ordering, conversion-webhook HA, stored-version migration checkpoints, and a block on contraction until verified backup plus rollback drill. State exactly what `helm rollback` can and cannot restore, and test failure at every phase of CRD, controller, worker, and storage migration.

### OP-10 — High — CRD uninstall can deadlock cleanup or destroy retained evidence

The default of retaining CRDs and PVCs is prudent, but “explicit audited cleanup” is not a procedure. If controllers are removed first, finalizers cannot complete. If CRDs are deleted, all custom resources vanish and Kubernetes garbage collection can race retention requirements. The design does not cover tenant namespaces, cluster-scoped RBAC, webhook configurations, Leases, snapshots, orphan PVCs, force-finalizer removal, or reinstall/adoption of retained resources.

**Action:** Define uninstall phases: disable new work, drain/cancel, verify backup, run cleanup while controllers remain, produce a retained-resource inventory, remove finalizers only under an audited break-glass policy, then remove controllers and optionally CRDs. Keep destructive CRD deletion outside normal Helm uninstall. Specify reinstall/adoption and a supported command to enumerate and purge retained PVCs/snapshots after retention expires.

### OP-11 — High — Observability promises would create cardinality problems and do not support operations

AD-18 says metrics are correlated by tenant, job, session, event, request, and execution IDs. Using those as Prometheus labels would create severe cardinality at the stated scale. The spine names only a few conditions and does not define condition ownership, transition rules, polarity, reason catalog, remediation, or aggregation. There are no required metrics, SLIs, alerts, dashboards, or runbook links for queue age, quota starvation, reconciliation lag, API throttling, leader changes, stale heartbeats, PVC pressure/Pending, snapshot freshness, restore verification, finalizer age, egress denials, or history lag.

**Action:** Establish a telemetry contract. Keep high-cardinality IDs in structured logs/traces and exemplars, not metric labels. Define a standard condition catalog per CRD with stable reasons, observed generation, last transition time, owner, and operator action. Ship baseline recording rules, SLO alerts, dashboards, and runbooks; prove AC-15 using those artifacts rather than ad hoc querying.

### OP-12 — Critical — The mandatory egress gateway is an unowned availability dependency

The gateway is the worker’s only external path and therefore sits on every clone and agent-provider call, yet it is neither installed by the chart nor described as a supported product dependency. There is no HA topology, capacity envelope for 200 workers, connection and DNS behavior, policy propagation model, worker authentication mechanism, certificate rotation, protocol support, observability, upgrade compatibility, or outage behavior. A gateway outage could consume active-job quota and trigger a retry storm.

**Action:** Make the gateway a first-class, versioned component of the chart or publish a strict adapter contract and supported implementation matrix. Define HA, sizing, timeout/circuit-breaker behavior, policy consistency, DNS/redirect handling, worker identity, credential rotation, audit signals, and failure conditions. Queue or pause work without burning retry budgets when the gateway is unavailable. Include gateway loss and partial policy rollout in scale and recovery tests.

### OP-13 — High — Worker isolation lacks enforced platform and resource defaults

The desired Pod security context is strong, but the spine does not require a Pod Security admission level, validating admission policy, or equivalent check that prevents a controller/configuration regression from weakening it. “Qualified platform” has no repeatable qualification suite. Application quotas are not connected to Kubernetes `ResourceQuota`, `LimitRange`, PriorityClass, node allocatable capacity, image-pull behavior, or namespace Pod quotas. One malformed job could request unschedulable resources indefinitely; 200 workers could displace control components unless they have separate priority/capacity.

**Action:** Ship enforceable worker templates and admission checks, namespace `ResourceQuota`/`LimitRange`, resource min/default/max policy, and dedicated control-plane priority. Define pending/scheduling timeout and stable conditions for insufficient CPU, memory, ephemeral storage, volume topology, and image pull. Run the gateway-bypass, metadata, host access, service-account token, cross-PVC, and security-context regression suite during platform qualification.

### OP-14 — High — Failure recovery stops at fencing and lacks bounded operator behavior

Attempt fencing prevents stale writes, but it does not decide recovery. The `interrupted → queued` transition has no retry budget, backoff, checkpoint age/compatibility rule, non-retryable classification, or manual intervention path. There is no matrix for API outage, etcd throttling, storage read-only/full, PVC detach, gateway outage, OIDC outage, image pull failure, node eviction, stuck Terminating Pod, finalizer failure, backup freeze timeout, or remote Git ambiguity after a push. Quota leakage and duplicate external side effects remain operational risks even when callbacks are fenced.

**Action:** Add a failure-mode recovery matrix with detection signal, condition/reason, automatic action, retry/backoff budget, quota treatment, timeout, evidence preserved, and operator runbook. Include durable reconciliation of quota claims and external side effects after restart. Release-gate recovery from controller crash at every state transition, storage exhaustion, zone loss, and prolonged dependency outage.

## Required release gates

The Kubernetes product should not be called production-ready until all of the following are executable:

1. A prerequisite matrix and preflight produce an unambiguous supported/unsupported result before installation.
2. A clean install acceptance test accurately includes every dependency needed for one private-repository agent job.
3. The 5,000-queue test reports fairness bounds, Kubernetes API load, etcd growth, relist behavior, and completed-resource GC.
4. Each supported storage topology passes node/zone loss, detach, expansion, low-space, snapshot, copy fallback, and clean-cluster restore.
5. Upgrade and rollback tests exercise the real CRD ownership mechanism and conversion/storage migrations.
6. Uninstall and reinstall prove retained-resource inventory, finalizer completion, adoption, and optional destructive purge.
7. Shipped alerts and conditions identify induced queue, controller, storage, worker, backup, and gateway failures without direct database or ad hoc cluster inspection.

## Final conclusion

The document is a strong semantic and safety spine, but not yet an operability spine. Its largest unresolved issue is that the Kubernetes baseline is presented as self-contained while outsourcing multiple mandatory control-path components. Storage topology, gateway ownership, CRD lifecycle, queue/API economics, and recovery procedures must become explicit architecture decisions—not deferred implementation choices—before the availability, scale, backup, upgrade, and clean-install acceptance claims are credible.
