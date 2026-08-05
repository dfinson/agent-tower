# Mode Requirements

This companion is normative. `common` requirements apply to both deployment modes; `kubernetes` and `local-daemon` requirements apply only to the named mode.

## Capability Index

| Capability | Scope | Intent |
|---|---|---|
| CAP-1 | `common` | Operators can choose Kubernetes-native or local-daemon deployment as a fully supported product mode |
| CAP-2 | `common` | Operators receive the same core job, session, state, approval, intervention, review, resolution, artifact, analytics, and audit semantics in both modes |
| CAP-3 | `common` | Operators can register, access, and isolate repositories and job workspaces without agents modifying the primary checkout |
| CAP-4 | `common` | Operators can select where agent execution occurs relative to the control plane and repository boundary |
| CAP-5 | `common` | Job records, canonical events, approvals, transcripts, telemetry, trails, artifacts, and workspace outcomes remain durable according to the selected mode policy |
| CAP-6 | `common` | Operators can configure global, repository, and job behavior and supply secrets without exposing secret values through APIs, events, logs, artifacts, or UI |
| CAP-7 | `common` | Every command, query, approval, and agent action is evaluated against an explicit identity, authorization, and policy context appropriate to the mode |
| CAP-8 | `common` | Operators can define and observe job concurrency, queueing, cancellation, and fairness limits |
| CAP-9 | `common` | Clients receive ordered live events and can reconnect to a consistent current state after interruption |
| CAP-10 | `common` | Operators can access CodePlane locally or remotely through an authenticated ingress appropriate to the mode |
| CAP-11 | `common` | Operators can diagnose service, job, agent, repository, storage, and event-stream health using correlated logs, metrics, traces, events, and artifacts |
| CAP-12 | `common` | CodePlane detects interrupted work and recovers or terminates it according to documented mode-specific guarantees |
| CAP-13 | `common` | Operators can install, upgrade, downgrade where supported, and remove each mode with documented compatibility and data-protection behavior |
| CAP-14 | `common` | Operators can move or interoperate selected repositories, configuration, policy, history, and artifacts between modes without changing shared identifiers or semantics unexpectedly |
| CAP-15 | `common` | Each deployment exposes clear trust, filesystem, network, credential, secret, and agent-execution boundaries |
| CAP-16 | `kubernetes` | Cluster operators can deploy and operate a Kubernetes-native CodePlane instance using supported Kubernetes packaging and lifecycle procedures |
| CAP-17 | `kubernetes` | Kubernetes operators can make repositories and isolated workspaces available to agents through a declared access model |
| CAP-18 | `kubernetes` | Kubernetes-native scheduling can place and limit control-plane and agent workloads across cluster resources |
| CAP-19 | `kubernetes` | Kubernetes-native durable state and artifacts survive pod replacement and supported upgrades to the declared durability objective |
| CAP-20 | `kubernetes` | Kubernetes-native identity, tenancy, authorization, and approval delegation support the declared organizational model |
| CAP-21 | `kubernetes` | Kubernetes-native ingress, service health, observability, scaling, and availability integrate with supported cluster operations |
| CAP-22 | `local-daemon` | A developer can install CodePlane and use cpl setup, cpl doctor, cpl up, cpl down, cpl restart, cpl info, and cpl version on a workstation |
| CAP-23 | `local-daemon` | A developer can use local repositories, Git worktrees, locally authenticated agent CLIs, native CLI-session mirroring, local terminals, and existing merge, PR, or discard workflows |
| CAP-24 | `local-daemon` | A single user can operate with local SQLite data, local artifacts and credentials, optional Dev Tunnel or Cloudflare remote access, and offline or local-first behavior |

## Requirement Matrix

| Concern | Common requirements | Kubernetes-native requirements | Local-daemon requirements |
|---|---|---|---|
| Deployment and upgrade lifecycle | Both modes expose install, readiness, upgrade, rollback or safe failure, and removal contracts | OCI CRD bundle plus Helm deploy one non-HA control-plane replica; additive CRD/SQLite/RWX migrations and N/N-1 worker protocol are conformance-gated | Existing cpl and package lifecycle remains supported. |
| Repository and workspace access | Registered repositories are bounded and every managed job is isolated | The RWOP-bound control-plane adapter alone mutates the shared mirror; workers and derived-data builders read it, and each worker alone writes its immutable-attempt-UID RWX workspace subPath | Absolute local paths, local clones, existing credentials, and Git worktrees remain supported. |
| Agent execution locality | Every job declares execution locality and enforces workspace, credential, policy, and resource boundaries | One direct in-cluster Pod per attempt; baseline workers have no service-account token or Kubernetes API access | Agents run on the workstation and native local CLI sessions remain mirrorable. |
| Persistence and artifact durability | Declared durable records preserve canonical identifiers, ordering, provenance, and retention semantics | SQLite on private RWOP owns shared-file metadata/references/publication state; projection-only CRDs expose bounded lifecycle; installation RWX has byte custody under generic lifecycle classes; barriered backup includes authoritative/durable bytes, may omit derived caches, excludes disposable workspaces unless retained, excludes etcd, and rotates incarnation on restore | SQLite and local filesystem assets preserve the same lifecycle semantics in the supported single-user implementation. |
| Configuration and secrets | `defaults < installation < repository < job` precedence is explicit; the default action-policy preset is `supervised`; secrets never enter logs, events, artifacts, or UI | Kubernetes Secret is baseline; optional Secrets Store CSI and rotation runbook are bounded by AD-20 and DEC-4 | Local config, environment variables, CLI credential stores, and repository config remain supported. |
| Identity tenancy authorization approvals | Mutation and approvals require an auditable authorized identity and policy context | One installation namespace is one trusted tenant; CodePlane OIDC/roles authorize humans and least-privilege Kubernetes RBAC authorizes service identities | Single-user localhost trust and authenticated remote access remain supported. |
| Scheduling and concurrency | Capacity, queueing, fairness, cancellation, cleanup, and limits are observable and deterministic | One control-plane scheduler owns admission, monotonic claims, the single `attemptFence`, cancellation, and cleanup | RuntimeService-style local concurrency limits and queues remain supported semantics. |
| Event streaming | TraceForge envelopes, open dotted `SessionEvent.kind` values, ordered client convergence, bounded replay, snapshots, and job-scoped streams are shared; no legacy snake_case translation is permitted | SQLite canonical history, bounded CRD projections, and SSE replay/backpressure follow AD-12 and REQ-41; no distributed event service is baseline | In-process publication, SQLite replay, and SSE remain supported; transport keepalives are distinct from canonical `session.heartbeat` events. |
| Ingress and remote access | UI, REST, SSE, MCP, and applicable interactive channels share authenticated access rules | Protocol/security behavior is fixed by AD-19; provider selection is bounded by DEC-2 | Localhost plus optional Dev Tunnel or Cloudflare access remains supported. |
| Observability | Correlation across service, job, session, event, repository, artifact, cost, and failure data is shared | Required logs, metrics, OTLP, audit, and health behavior follow AD-18; backend/provider selection remains operator-owned | Structured local logs, health, artifacts, analytics, and optional OTEL export remain supported. |
| Failure recovery | Interruptions yield explicit states, durable evidence, bounded recovery, and no orphaned approvals or agents | Restore rotates durable installation incarnation, invalidates old workers/cursors/fences, recreates CR projections from SQLite, and explicitly degrades missing files | Graceful shutdown pauses active sessions and startup resumes them in place using reason `server_restart`; restart does not fail every active job. |
| Scaling and availability | Declared service objectives and degradation behavior are testable | Single-replica non-HA envelope, restart window, RTO/RPO, API budgets, and queue limits are tested; active/active HA is Deferred | Single-user and workstation-scale limits remain valid rather than being judged against cluster HA goals. |
| Security boundaries | Least privilege, repository containment, secret protection, authenticated mutation, policy enforcement, and auditability are invariant | Declared subPaths prevent accidental/casual sibling access; every shared file set declares writer/readers and access mode, mirror mutation stays control-plane-owned, and network/credential controls are enforced; hostile same-installation isolation is not claimed | OS-user permissions, worktree containment, localhost trust, password and tunnel gates, and local credentials remain supported. |
| Packaging | Each mode has a supported, diagnosable distribution with version and compatibility information | OCI Helm chart API v2, versioned CRD bundle, Kubernetes 1.34-1.36, and executable RWOP/RWX storage qualification | Python package and cpl entry point remain supported. |
| Migration and interoperability | Portable data is explicit, identifiers and semantics are preserved, and non-portable data is reported | Signed exports carry SQLite history plus authoritative shared data and durable artifacts; CRD metadata and paths remap, derived caches are omitted/rebuilt or fully revalidated, and disposable workspaces are excluded unless retained as artifacts | Local operation never requires migration to Kubernetes and remains independently complete. |

## Intentional Differences

- Local-daemon may trust same-machine localhost and use one OS user, while Kubernetes-native requires an explicit network identity, tenancy, and authorization contract.
- Local-daemon uses workstation paths, processes, SQLite, and local filesystem durability; Kubernetes-native uses the finalized single-replica SQLite + RWOP/RWX shared-volume composition while preserving equivalent product outcomes.
- Native CLI-session mirroring, workstation PTYs, local voice transcription, Dev Tunnel, Cloudflare tunnel, and localhost preview are resolved as local-only for v1 under AD-25 and REQ-8. Kubernetes provides managed-job terminals and previews, authenticated sharing, and optional Web Push with a durable VAPID secret; it does not ingest developer-machine sessions, and capability discovery reports every unsupported parity item.
- Availability and scale objectives are mode-specific; local single-user constraints are valid product characteristics, not failures to meet Kubernetes service levels.

## Cross-Mode Conformance

A release is conformant only when all applicable checks pass:

1. The shared job lifecycle, state transitions, `supervised` default policy, approvals, operator messages, cancellation, review, and resolution produce equivalent observable outcomes.
2. Canonical event identity, TraceForge envelope, dotted kind, ordering, replay or snapshot convergence, and audit provenance remain interpretable across modes; transport keepalives never become session heartbeat domain events.
3. Repository containment, isolated workspaces, credential boundaries, secret redaction, and policy enforcement pass mode-specific security tests.
4. Declared durable records and artifacts survive the supported restart and upgrade scenarios for that mode; local graceful restart pauses and resumes active sessions in place with reason `server_restart`.
5. Installation, diagnostics, access, observability, failure recovery, and removal procedures are demonstrable from supported packaging.
6. Every unsupported parity item is documented as an intentional difference, not silently omitted.

## Deferred Profiles and Choices

- Active/active control-plane HA, multiple hostile tenants per installation, and cross-tenant storage isolation require new architecture decisions and are not v1 guarantees. Distributed shared-storage metadata, coordination, byte services, or cache GC may be selected generically for that future profile; dedicated CodeRecon/index/handoff machinery is not presumed.
- Exact CSI/StorageClass, snapshot, ingress/gateway, certificate, OIDC, and optional secret-store providers remain operator choices subject to AD-21 qualification.
- Remote developer workers and ingestion of developer-machine native sessions remain future capabilities requiring a new trust/protocol decision.
