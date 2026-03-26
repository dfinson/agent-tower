# Cloud-Native Design Proposal

> Status: **Draft / Exploration**
> Created: 2026-03-18

CodePlane is currently a single-machine, single-process application. This document explores how to make it cloud-native (Kubernetes-first, cloud-agnostic) while preserving local-mode compatibility.

---

## Current Architecture Constraints

| Component | Current | Cloud Blocker |
|---|---|---|
| Database | SQLite (WAL mode) | Single-writer, local file |
| Agent execution | `subprocess.Popen` (in-process) | Same-machine only |
| Event bus | In-process `asyncio.gather` fan-out | Single process only |
| SSE | In-process queues per connection | Single process only |
| Git worktrees | Local filesystem under repo root | Local FS assumption |
| Artifacts | `~/.codeplane/artifacts/` on disk | Local FS assumption |
| Terminal/PTY | `pty.openpty()` + subprocess | POSIX, same machine |
| Approval routing | In-process await/resolve | Coupled to agent process |

## Three Design Options

### Design A: Pod-per-Job (Recommended Starting Point)

API stays as a monolith. Agent execution moves to ephemeral Kubernetes Jobs. DB and storage become pluggable.

- **API scaling:** Single replica (SPOF acceptable for V1)
- **Job scaling:** One K8s Job per coding task
- **Migration effort:** Low-medium
- **New services:** 0 (monolith stays)

### Design B: Split Plane

Separate control plane (API, stateless, HPA-scaled) from execution plane (runner pods), connected by a message broker (NATS / Redis Streams / RabbitMQ).

- **API scaling:** Horizontal via HPA
- **Job scaling:** One pod per coding task
- **Migration effort:** Medium
- **New services:** 2 (scheduler, broker)

### Design C: Serverless Agents

Push toward scale-to-zero compute (Knative, Fargate, Cloud Run Jobs). Durable workflow engine (Temporal / Restate) replaces the state machine. CloudEvents envelope for all events.

- **API scaling:** Scale-to-zero
- **Job scaling:** Serverless containers
- **Migration effort:** High
- **New services:** 3+ (orchestrator, event backbone, CDN)

---

## Design A — Detailed Design

### Key Insight: Two Orthogonal Axes

Agent SDK choice (**what** runs) and execution environment (**where** it runs) are independent dimensions. They must not be conflated into a single abstraction.

```
                        WHERE it runs
                   Local           │   Remote (K8s, Fargate, ...)
                ───────────────────┼───────────────────────
  WHAT    Claude │ ClaudeAdapter    │  ClaudeAdapter
  agent          │ in-process       │  in runner container
         ────────┼──────────────────┼───────────────────────
         Copilot │ CopilotAdapter   │  CopilotAdapter
                 │ in-process       │  in runner container
```

Adding a new cloud target = one new `ExecutionBackend`. Adding a new agent SDK = one new adapter. **N + M implementations, not N × M.**

### New Abstractions

#### `ExecutionBackend` — decides WHERE a session runs

```python
class ExecutionBackend(ABC):
    @abstractmethod
    async def launch(
        self, job_id: str, sdk: AgentSDK, config: SessionConfig,
    ) -> RunnerHandle: ...

    @abstractmethod
    async def teardown(self, job_id: str) -> None: ...
```

#### `RunnerHandle` — uniform channel to a running session

```python
class RunnerHandle(ABC):
    @abstractmethod
    async def stream_events(self) -> AsyncIterator[SessionEvent]: ...

    @abstractmethod
    async def send_message(self, message: str) -> None: ...

    @abstractmethod
    async def abort(self) -> None: ...

    @abstractmethod
    async def resolve_approval(self, approval_id: str, allow: bool) -> None: ...
```

### Two `ExecutionBackend` Implementations

#### `LocalExecutionBackend` (wraps current behavior)

```python
class LocalExecutionBackend(ExecutionBackend):
    async def launch(self, job_id, sdk, config) -> RunnerHandle:
        adapter = self._adapter_registry.get(sdk)
        session_id = await adapter.create_session(config)
        return LocalRunnerHandle(adapter, session_id)

    async def teardown(self, job_id) -> None:
        pass  # subprocess cleanup handled by adapter
```

`LocalRunnerHandle` delegates directly to the in-process adapter instance. Zero behavior change from today.

#### `KubernetesExecutionBackend` (new)

```python
class KubernetesExecutionBackend(ExecutionBackend):
    async def launch(self, job_id, sdk, config) -> RunnerHandle:
        manifest = self._build_job_manifest(job_id, sdk, config)
        await self._k8s_client.create_namespaced_job(self._namespace, manifest)
        endpoint = await self._await_runner_ready(job_id)
        return KubernetesRunnerHandle(endpoint, job_id)

    async def teardown(self, job_id) -> None:
        await self._k8s_client.delete_namespaced_job(...)
```

`KubernetesRunnerHandle` communicates with the runner pod over gRPC.

### Component Diagram

```
RuntimeService
  uses: ExecutionBackend (doesn't know or care which one)
  gets: RunnerHandle (uniform interface to running session)
       │                               │
       ▼                               ▼
 LocalExecutionBackend         KubernetesExecutionBackend
       │                               │
       ▼                               ▼
 LocalRunnerHandle             KubernetesRunnerHandle
 (direct method calls          (gRPC calls to runner pod,
  on adapter instance)          which runs the same adapter
                                inside the container)
       │                               │
       └───────────┬───────────────────┘
                   ▼
       AgentAdapterInterface
       (ClaudeAdapter / CopilotAdapter)
       Always the same. Doesn't know if
       it's local or in a container.
```

### Runner Pod

The runner pod is a thin gRPC shell around the existing SDK adapter code:

```
┌─ Runner Pod (ephemeral K8s Job) ──────────────┐
│  entrypoint.py                                 │
│    ├─ git clone <repo_url> /workspace          │
│    ├─ adapter = ClaudeAdapter() or             │
│    │            CopilotAdapter()               │
│    ├─ session_id = adapter.create_session(cfg) │
│    ├─ gRPC server exposes:                     │
│    │   StreamEvents → adapter.stream_events()  │
│    │   SendMessage  → adapter.send_message()   │
│    │   Abort        → adapter.abort_session()  │
│    │   ResolveApproval → unblock permission cb │
│    └─ on completion: git push, upload artifacts│
└────────────────────────────────────────────────┘
```

The pod reuses the same adapter code from the main package — no logic duplication.

### Other Infrastructure Changes

#### SQLite → PostgreSQL

Conditional dialect in `database.py`. Repository pattern means zero service-layer changes.

```python
def get_database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if url:
        return url  # "postgresql+asyncpg://..."
    return f"sqlite+aiosqlite:///{DEFAULT_DB_PATH}"
```

Swap `sa.JSON` to `JSONB` for Postgres via a single Alembic migration.

#### Artifacts → Object Storage

New `StorageBackend` abstraction with `LocalStorageBackend` (current behavior) and `S3StorageBackend` (S3-compatible: AWS, MinIO, R2, GCS interop). Wired into `ArtifactService`.

#### Git → Remote-First

Runner pod clones, branches, works, pushes. API only tracks `(repo_url, branch_name, commit_sha)`. Default to `pr_only` completion strategy in cloud mode — no local repo needed on the API pod.

### Approval Flow (Remote)

1. Runner pod's SDK permission callback fires
2. Runner emits `SessionEvent(kind=approval_request)` over gRPC stream
3. API receives it, routes to `ApprovalService`, emits SSE to frontend (unchanged)
4. User approves via REST endpoint (unchanged)
5. API calls `handle.resolve_approval(id, allow)` → gRPC to runner pod
6. Runner pod unblocks the SDK callback → agent continues

### Configuration

```yaml
runtime:
  execution_backend: local      # local | kubernetes

  kubernetes:
    namespace: codeplane
    runner_image: ghcr.io/yourorg/codeplane-runner:latest
    runner_service_account: codeplane-runner
    resource_requests: { cpu: "500m", memory: "1Gi" }
    resource_limits:   { cpu: "2",    memory: "4Gi" }
    active_deadline_seconds: 3600
```

When `execution_backend: local`, existing behavior is unchanged. No impact on current users.

### Kubernetes Resources Required

- **API Deployment** (1 replica, has ServiceAccount with `batch/jobs` CRUD permissions)
- **RBAC Role** for creating/deleting K8s Jobs and Services
- **Secrets** for DATABASE_URL, git credentials, S3 credentials
- **Optional:** PostgreSQL StatefulSet (or managed DB), MinIO (or managed object storage)

---

## Implementation Order

| Step | Effort | Description | Cloud Required? |
|---|---|---|---|
| 1 | Small | Define `ExecutionBackend` + `RunnerHandle` ABCs | No |
| 2 | Small | Implement `LocalExecutionBackend` wrapping existing adapters | No |
| 3 | Medium | Refactor `RuntimeService` to use `ExecutionBackend` | No |
| 4 | — | **Gate: verify local mode works identically** | No |
| 5 | Small | PostgreSQL support in `database.py` + Alembic migration | No |
| 6 | Small | `StorageBackend` abstraction + `S3StorageBackend` | No |
| 7 | Medium | Build runner pod image (gRPC shell around existing adapters) | Yes |
| 8 | Medium | Implement `KubernetesExecutionBackend` + `KubernetesRunnerHandle` | Yes |
| 9 | Small | Helm chart / K8s manifests | Yes |

Steps 1–6 are cloud-independent refactors that improve the codebase regardless. Steps 7–9 are the actual cloud wiring.

---

## Open Questions

| Question | Options | Recommendation |
|---|---|---|
| Terminal service in cloud? | (a) Drop it (b) WebSocket tunnel to pod (c) `kubectl exec` proxy | Drop for V1, add tunnel later |
| Runner pod networking | (a) ClusterIP Service per pod (b) Headless Service (c) Pod IP | ClusterIP, cleaned up via ownerReference |
| Git credentials in runner | (a) Mounted Secret (b) Git credential helper (c) SSH key | Mounted Secret (simplest) |
| Max job duration | K8s `activeDeadlineSeconds` | Default 1h, configurable per job |
| Runner pod failure detection | Watch K8s Job status + gRPC stream health | Both — emit `job_failed` with pod logs on unexpected termination |
| Multi-cluster / multi-cloud | Not in scope for Design A | `KubernetesExecutionBackend` could target remote API server as extension point |

---

## Path to Design B / C

The `ExecutionBackend` abstraction also enables the later designs:

- **Design B:** Extract `RuntimeService` scheduling logic into a separate service that consumes from a broker. `ExecutionBackend` stays the same — the scheduler just calls it from a different process.
- **Design C:** Replace `RuntimeService` loop with a durable workflow (Temporal/Restate). Each workflow step calls `ExecutionBackend.launch()`. The workflow engine handles retry, timeout, and state persistence.

The investment in steps 1–4 pays forward into any future architecture.
