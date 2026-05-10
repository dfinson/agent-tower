---
title: "CLI Session Import: Real-Time Observation and Steering of Native CLI Sessions"
status: draft
---

# CLI Session Import

> Users run `copilot` or `claude` in their own terminal. CodePlane observes
> every event in real time, builds the same job view as a managed session, and
> can send messages back to the running agent.

---

## 1. Problem

CodePlane currently requires launching agent sessions through its own
orchestration layer (`RuntimeService` → `AdapterRegistry` → SDK adapter).
Users who prefer running the Copilot or Claude CLIs natively get none of
CodePlane's visibility — no transcript, no timeline, no metrics, no operator
messaging.

The goal is **full parity**: an imported CLI session is
indistinguishable from a managed session in the UI. Same state machine,
same review flow, same merge/PR/discard resolution actions. CodePlane
captures the repo path and branch from session start data and operates
on the user's working directory directly.

---

## 2. Data Sources (Empirically Verified)

### 2.1 Copilot CLI (v1.0.44)

| Channel | Mode | Data |
|---------|------|------|
| OTEL File Exporter | Real-time JSONL (no batching) | Spans: `invoke_agent`, `chat <model>`, `execute_tool`. Attributes: `gen_ai.usage.input_tokens`, `output_tokens`, `github.copilot.cost`, `gen_ai.request.model`, `gen_ai.tool.call.arguments`, `gen_ai.tool.call.result`, `github.copilot.turn_id` |
| GitHub Steer API | Cloud relay, 3s poll | `POST /agents/tasks/{taskId}/steer` — user messages, permission responses, mode switch, abort |

**User setup** (one-time, in shell profile):

```bash
export COPILOT_OTEL_FILE_EXPORTER_PATH=$HOME/.copilot/codeplane-otel.jsonl
export OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=true
```

Launch sessions with `copilot --remote` to enable steering.

### 2.2 Claude CLI (v2.1.81+)

| Channel | Mode | Data |
|---------|------|------|
| HTTP Hooks | Real-time synchronous POST | 28 event types: `SessionStart`, `SessionEnd`, `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `Stop`, `SubagentStart/Stop`, `TaskCreated/Completed`, `WorktreeCreate/Remove`, etc. Payloads include `session_id`, `cwd`, `tool_name`, `tool_input`, `tool_response`, `duration_ms` |
| Hook Responses | Synchronous return | `Stop` → `{"decision":"block","reason":"..."}` injects operator messages. `PreToolUse` → `{"permissionDecision":"deny"}` blocks tools. `PostToolUse` → `{"additionalContext":"..."}` injects context |
| OTEL OTLP | Real-time HTTP | Metrics: `claude_code.cost.usage`, `claude_code.token.usage`, `claude_code.lines_of_code.count` |

**User setup** (one-time):

`~/.claude/settings.json`:
```json
{
  "hooks": {
    "PostToolUse":       [{"type": "http", "url": "http://localhost:9418/api/hooks/claude"}],
    "UserPromptSubmit":  [{"type": "http", "url": "http://localhost:9418/api/hooks/claude"}],
    "Stop":              [{"type": "http", "url": "http://localhost:9418/api/hooks/claude"}],
    "SessionStart":      [{"type": "http", "url": "http://localhost:9418/api/hooks/claude"}],
    "SessionEnd":        [{"type": "http", "url": "http://localhost:9418/api/hooks/claude"}],
    "PreToolUse":        [{"type": "http", "url": "http://localhost:9418/api/hooks/claude"}],
    "SubagentStart":     [{"type": "http", "url": "http://localhost:9418/api/hooks/claude"}],
    "SubagentStop":      [{"type": "http", "url": "http://localhost:9418/api/hooks/claude"}]
  }
}
```

Plus OTEL:
```bash
export CLAUDE_CODE_ENABLE_TELEMETRY=1
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:9418/api/otlp
```

---

## 3. Architecture

```
┌──────────────────────┐     ┌────────────────────────┐
│  Copilot OTEL File   │     │  Claude HTTP Hooks      │
│  Watcher (tail JSONL)│     │  (FastAPI POST handler)  │
└──────────┬───────────┘     └──────────┬─────────────┘
           │                            │
           ▼                            ▼
    ┌──────────────────────────────────────────┐
    │             IngestService                │
    │  ┌────────────────┐ ┌──────────────────┐ │
    │  │ OtelSpanMapper │ │ ClaudeHookMapper │ │
    │  │ (JSONL spans → │ │ (hook payloads → │ │
    │  │  DomainEvents) │ │  DomainEvents)   │ │
    │  └────────────────┘ └──────────────────┘ │
    └──────────────────┬───────────────────────┘
                       │
                       ▼
    ┌──────────────────────────────────────────┐
    │     Existing EventBus + SSE Pipeline     │
    │  (publishes to SSEManager, persists to   │
    │   EventRepository — unchanged)           │
    └──────────────────┬───────────────────────┘
                       │
                       ▼
    ┌──────────────────────────────────────────┐
    │   Frontend (unchanged except source      │
    │   badge on job cards)                    │
    └──────────────────────────────────────────┘
```

### Steering (messages TO the agent)

```
CodePlane UI → operator types message
       │
       ├─── Claude: store pending message → next Stop hook fires →
       │    return {"decision":"block","reason":"<message>"} →
       │    Claude reads it as next instruction
       │
       └─── Copilot: POST /agents/tasks/{taskId}/steer →
            {"content":"<message>","type":"user"} →
            CommandPoller picks up within 3s →
            injected as session.send()
```

---

## 4. Domain Model Changes

### 4.1 `backend/models/domain.py`

**`JobSource` enum** (new):

```python
class JobSource(StrEnum):
    """How the job was created."""
    managed = "managed"          # CodePlane launched the agent
    copilot_cli = "copilot_cli"  # Imported from native Copilot CLI
    claude_cli = "claude_cli"    # Imported from native Claude CLI
```

**`Job` dataclass** — add two fields:

```python
@dataclass
class Job:
    ...
    source: str = "managed"           # JobSource value
    external_session_id: str | None = None  # CLI's own session/task ID
```

**State machine** — imported jobs use the same states as managed jobs.
`IngestService` populates `repo`, `branch`, `base_ref`, and
`worktree_path` (set to the CLI's `cwd`) at session start, so the
existing review and resolution machinery works unmodified.

```
None → running → review → completed   (normal clean exit)
                        → running      (operator sends follow-up)
              → failed                 (session errored)
              → canceled               (user aborted)
```

`None → running` is already valid in `_VALID_TRANSITIONS`. No state
machine changes needed.

**How fields are populated**:

| Field | Managed session | Imported session |
|-------|----------------|------------------|
| `repo` | User selects in UI | Detected from `cwd` (`git rev-parse --show-toplevel`) |
| `branch` | CodePlane creates | Detected from `cwd` (`git rev-parse --abbrev-ref HEAD`) |
| `base_ref` | User selects in UI | Detected (`git symbolic-ref refs/remotes/origin/HEAD`, fallback `main`) |
| `worktree_path` | CodePlane creates worktree | CLI's `cwd` — from Claude hook `SessionStart.cwd` (confirmed: `cwd` is a common input field on every hook event). For Copilot: `cwd` is **not** present in OTEL spans (empirically verified v1.0.44). Must be inferred from file paths in the first `execute_tool` span's `gen_ai.tool.call.arguments`, or from `OTEL_RESOURCE_ATTRIBUTES=process.cwd=<path>` (requires adding to user setup) |
| `prompt` | User enters in UI | First user message from session (hook `UserPromptSubmit` or OTEL content capture) |

Because `repo`, `branch`, `base_ref`, and `worktree_path` are all
populated, `MergeService`, `DiffService`, and PR creation work
identically to managed sessions.

**No destructive operations for imported sessions**: When `source !=
"managed"`, CodePlane did not create the working directory or the
branch, so it must never delete them. This applies to ALL resolution
paths, not just discard:

- **Discard**: Mark job as discarded. Do NOT call `remove_worktree`
  or `git branch -D`. Leave the filesystem as-is.
- **Merge / Smart Merge**: The user's CLI session already committed
  changes to their branch. CodePlane pushes the branch and does a
  remote merge (fast-forward or merge commit via the forge API / `git
  push`). It does NOT checkout/stash/merge in the user's working
  directory — `_preserved_worktree` and `_checkout_and_merge` operate
  on `repo_path` which for imported sessions IS the user's live
  checkout. After merge, do NOT call `_post_merge_cleanup` (no
  worktree removal, no branch deletion).
- **Create PR**: Push the branch to origin, create PR. Do NOT call
  `_cleanup_worktree_only`. Branch stays — the user is still on it.
- **On default branch (branch == base_ref)**: There is nothing to
  merge — the changes are already where they belong. Skip merge
  entirely, transition to `completed` with resolution `merged`.

Implementation: `MergeService.resolve_job()` checks `job.source` and
routes to a new `_resolve_imported()` method that handles push +
remote merge without touching the local working directory.

The existing `_auto_merge` (post-session) path also needs the same
guard: when `IngestService._finalize_session()` triggers
`MergeService.merge_to_base()`, it must use the imported-session
path.

### 4.2 `backend/models/db.py` — `JobRow`

Add columns:

```python
source: Mapped[str] = mapped_column(String, nullable=False, default="managed", server_default="managed")
external_session_id: Mapped[str | None] = mapped_column(String, nullable=True)
```

### 4.3 `alembic/versions/` — new migration

```python
"""Add source and external_session_id to jobs."""

def upgrade():
    op.add_column("jobs", sa.Column("source", sa.String(), nullable=False, server_default="managed"))
    op.add_column("jobs", sa.Column("external_session_id", sa.String(), nullable=True))

def downgrade():
    op.drop_column("jobs", "external_session_id")
    op.drop_column("jobs", "source")
```

### 4.4 `backend/models/api_schemas.py`

**`JobResponse`** — add:

```python
class JobResponse(CamelModel):
    ...
    source: str = "managed"
    external_session_id: str | None = None
```

**`JobResponse.from_domain()`** — wire the two new fields.

### 4.5 `backend/models/events.py`

No new `DomainEventKind` values needed. Imported sessions emit the same
event types as managed sessions:

- `transcript_updated` — tool calls and agent messages
- `telemetry_updated` — tokens, cost, model
- `step_started` / `step_completed` — timeline activities
- `job_state_changed` — session lifecycle
- `diff_updated` — git changes (via existing `DiffService` git watcher)

### 4.6 `backend/persistence/job_repo.py`

Wire `source` and `external_session_id` in `_to_domain()` and `create()`.

---

## 5. New Backend Services

### 5.1 `backend/services/ingest_service.py` (new file)

Central coordinator for imported sessions. Responsibilities:

- On first event, detect git metadata from the CLI's working directory
  (`repo`, `branch`, `base_ref` via `GitService`)
- Auto-register the repo in CodePlane's allowlist if not already present
  (imported sessions bypass the manual "add repo" flow)
- Kick off CodeRecon indexing **in the background** — indexing can take
  minutes for large repos so the job must not block on it. The sequence:
  1. Create the job and start ingesting events immediately (no CodeRecon
     dependency — transcript, telemetry, merge all work without it)
  2. Fire an `asyncio.create_task` that calls `ensure_repo_indexed(repo)`
  3. Once indexing completes, call `register_worktree(repo_name, cwd)`
  4. Structural features (semantic diff, cycle detection, community
     analysis, step-boundary structural warnings) become available
     progressively — they were always optional and gated behind
     `coderecon_service.available` checks
  5. If the session ends before indexing finishes, structural analysis
     is skipped for that session (same as when CodeRecon is disabled)
  This mirrors `RuntimeService` where every CodeRecon call is wrapped
  in `try/except` — it's never on the critical path
- Create the `Job` record (state = `running`, source = `copilot_cli` or
  `claude_cli`, `worktree_path` = CLI's `cwd`)
- Route incoming data to the appropriate mapper
- Publish `DomainEvent`s to the existing `EventBus`
- Track per-session state (seq counters, turn IDs, telemetry accumulators)
- Store pending operator messages for Claude hook response injection
- Forward steering commands to the Copilot steer API
- On session end, transition to `review` and trigger `MergeService` (same
  post-session flow as managed sessions)

```python
class IngestService:
    def __init__(
        self,
        event_bus: EventBus,
        session_factory: async_sessionmaker[AsyncSession],
        config: CPLConfig,
        git_service: GitService | None = None,
        diff_service: DiffService | None = None,
        merge_service: MergeService | None = None,
        trail_service: TrailService | None = None,
        job_service: JobService | None = None,
        coderecon_service: CodeReconService | None = None,
    ) -> None: ...

    async def ingest_otel_span(self, span: dict) -> None:
        """Process a single OTEL JSONL span from the Copilot file watcher."""

    async def ingest_claude_hook(self, event_type: str, payload: dict) -> dict:
        """Process a Claude hook POST. Returns the hook response body."""

    async def send_operator_message(self, job_id: str, message: str) -> None:
        """Queue an operator message for delivery to the agent."""

    async def abort_session(self, job_id: str) -> None:
        """Abort the external session (steer API for Copilot, hook block for Claude)."""

    async def _create_job_from_session(self, cwd: str, source: str, session_id: str) -> Job:
        """Detect git state from cwd, create Job record with full metadata.

        1. git rev-parse --show-toplevel → repo path
        2. Auto-register repo in allowlist if missing
        3. Detect branch, base_ref
        4. Create and persist Job record (returns immediately)
        5. Fire background task: CodeRecon ensure_repo_indexed(repo)
           → on completion: register_worktree(repo_name, cwd)
           Structural features light up when indexing finishes.
           If it never finishes, the job works fine without it.
        """

    async def _finalize_session(self, job_id: str) -> None:
        """Transition to review, run post-session merge flow via MergeService."""
```

### 5.2 `backend/services/otel_file_watcher.py` (new file)

Async file tailer for the Copilot OTEL JSONL file.

```python
class OtelFileWatcher:
    """Tails COPILOT_OTEL_FILE_EXPORTER_PATH, parses JSONL, routes to IngestService."""

    def __init__(self, path: str, ingest_service: IngestService) -> None: ...

    async def start(self) -> None:
        """Begin tailing. Called from lifespan startup."""

    async def stop(self) -> None:
        """Stop tailing. Called from lifespan shutdown."""
```

Implementation: `asyncio` loop with `os.stat()` polling for file size
changes, reads new bytes, splits on newlines, parses JSON, calls
`ingest_service.ingest_otel_span()`.

### 5.3 `backend/services/copilot_steer.py` (new file)

Thin wrapper around the GitHub steer API.

```python
class CopilotSteerClient:
    """Sends steering commands to a Copilot CLI --remote session."""

    def __init__(self, github_token: str) -> None: ...

    async def send_message(self, task_id: str, message: str) -> None:
        """POST /agents/tasks/{task_id}/steer with type=user."""

    async def abort(self, task_id: str) -> None:
        """POST /agents/tasks/{task_id}/steer with type=abort."""
```

API endpoint: `https://api.enterprise.githubcopilot.com/agents/tasks/{taskId}/steer`

Auth: Bearer token from the user's GitHub/Copilot token (same token
CodePlane already uses).

---

## 6. New API Routes

### 6.1 `backend/api/hooks.py` (new file)

Claude hook receiver endpoint:

```python
router = APIRouter(tags=["hooks"])

@router.post("/hooks/claude")
async def claude_hook(
    request: Request,
    ingest: FromDishka[IngestService],
) -> JSONResponse:
    """Receive Claude CLI hook events. Returns hook response for steering."""
    body = await request.json()
    event_type = body.get("hookEventName", "")
    response_body = await ingest.ingest_claude_hook(event_type, body)
    return JSONResponse(content=response_body)
```

### 6.2 `backend/api/ingest.py` (new file)

Operator messaging endpoints for imported sessions:

```python
router = APIRouter(tags=["ingest"])

@router.post("/jobs/{job_id}/message")
async def send_message(
    job_id: str,
    body: SendMessageRequest,
    ingest: FromDishka[IngestService],
) -> MessageResponse:
    """Send an operator message to an imported CLI session."""
    await ingest.send_operator_message(job_id, body.message)
    return MessageResponse(delivered=True)

@router.post("/jobs/{job_id}/abort")
async def abort_imported(
    job_id: str,
    ingest: FromDishka[IngestService],
) -> dict:
    """Abort an imported CLI session."""
    await ingest.abort_session(job_id)
    return {"status": "ok"}
```

### 6.3 Existing routes — `backend/api/jobs.py`

The existing `POST /jobs/{job_id}/message` endpoint (operator messages
for managed sessions) should delegate to `IngestService` when
`job.source != "managed"`. Same for `POST /jobs/{job_id}/cancel`.

No new route needed — the existing routes gain a conditional branch.

---

## 7. DI & Lifecycle Changes

### 7.1 `backend/di.py`

Register new providers:

```python
# IngestService
IngestService(
    event_bus=event_bus,
    session_factory=session_factory,
    config=config,
    git_service=git_service,
    diff_service=diff_service,
    merge_service=merge_service,
    trail_service=trail_service,
    job_service=job_service,
    coderecon_service=coderecon_service,
)

# OtelFileWatcher (only if COPILOT_OTEL_FILE_EXPORTER_PATH is set)
OtelFileWatcher(path=otel_path, ingest_service=ingest_service)

# CopilotSteerClient (only if GitHub token is available)
CopilotSteerClient(github_token=token)
```

### 7.2 `backend/lifespan.py`

Add to startup:

```python
if config.copilot_otel_path:
    watcher = container.get(OtelFileWatcher)
    await watcher.start()
```

Add to shutdown:

```python
if watcher:
    await watcher.stop()
```

### 7.3 `backend/config.py` — `CPLConfig`

Add optional config field:

```python
copilot_otel_path: str | None = None  # COPILOT_OTEL_FILE_EXPORTER_PATH
```

Read from environment at config load time.

### 7.4 `backend/app_factory.py`

Mount the new routers:

```python
from backend.api.hooks import router as hooks_router
from backend.api.ingest import router as ingest_router

app.include_router(hooks_router, prefix="/api")
app.include_router(ingest_router, prefix="/api")
```

---

## 8. Frontend Changes

### 8.1 `frontend/src/store/types.ts` — `JobSummary`

Add field:

```typescript
export interface JobSummary {
  ...
  source?: string;            // "managed" | "copilot_cli" | "claude_cli"
}
```

### 8.2 `frontend/src/api/types.ts`

No change — types are generated from OpenAPI schema. Run `openapi-typescript`
after backend changes.

### 8.3 `frontend/src/components/JobHeaderCard.tsx`

- Show a "CLI Import" badge next to the SDK badge when `source !== "managed"`
- Show the external session ID as a tooltip

### 8.4 `frontend/src/components/JobDetailScreen.tsx`

**Full parity — no conditional hiding of actions.** All buttons work:

- Merge / Smart Merge — pushes branch and does remote merge (does NOT
  checkout/stash in the user's working directory — see §4.1)
- Create PR — pushes branch to origin, creates PR (does NOT remove
  worktree or delete branch)
- Discard — marks job as discarded, leaves filesystem untouched
- Continue / Send message — routes through `IngestService` for steering
- Cancel/Abort — routes through `IngestService`

The operator message input in `CuratedFeed` / `TranscriptPanel` works
unchanged — the existing `/jobs/{job_id}/message` endpoint delegates to
`IngestService` when `source != "managed"`.

### 8.5 `frontend/src/components/JobListScreen.tsx` (or `JobCard`)

- Show a "CLI" indicator on imported job cards
- Filter/sort: imported jobs appear in the normal job list

### 8.6 No SSE changes

The frontend's SSE handler table (`sseHandlers`) and the `useSSE` hook
require zero changes. Imported sessions emit the same event types as
managed sessions.

---

## 9. Span-to-DomainEvent Mapping

### 9.1 Copilot OTEL Spans → DomainEvents

| OTEL Span Type | DomainEvent | Payload mapping |
|---------------|-------------|-----------------|
| `execute_tool` | `transcript_updated` | `tool_name` = span name suffix, `tool_args` = `gen_ai.tool.call.arguments`, `tool_result` = `gen_ai.tool.call.result`, `role` = `tool`, `turn_id` = `github.copilot.turn_id` |
| `chat <model>` | `transcript_updated` | `content` = captured message content, `role` = `assistant`, `turn_id` = `github.copilot.turn_id` |
| `chat <model>` | `telemetry_updated` | `input_tokens` = `gen_ai.usage.input_tokens`, `output_tokens` = `gen_ai.usage.output_tokens`, `total_cost_usd` = `github.copilot.cost`, `model` = `gen_ai.response.model` |
| `invoke_agent` (end) | `job_review` + `job_state_changed` (→ review) | Session ended cleanly — triggers post-session merge flow |
| Error on any span | `job_failed` | `reason` from span status |

### 9.2 Claude Hooks → DomainEvents

| Hook Event | DomainEvent | Payload mapping |
|-----------|-------------|-----------------|
| `SessionStart` | `job_created` + `job_state_changed` (→ running) | `session_id`, `cwd` |
| `UserPromptSubmit` | `transcript_updated` | `role` = `user`, `content` = input |
| `PostToolUse` | `transcript_updated` | `role` = `tool`, `tool_name`, `tool_args` = `tool_input`, `tool_result` = `tool_response`, `duration_ms` |
| `Stop` | (turn boundary) | Emit pending `step_completed`, check for pending operator messages |
| `SessionEnd` | `job_review` + `job_state_changed` (→ review) | Session over — triggers post-session merge flow |
| `SubagentStart` | `step_started` | Subagent as a new activity section |
| `TaskCreated` | `agent_plan_updated` | Map to plan steps |

OTEL OTLP metrics (`claude_code.cost.usage`, `claude_code.token.usage`)
→ `telemetry_updated` events, accumulated per job.

---

## 10. What Doesn't Change

| Component | Why unchanged |
|-----------|--------------|
| `EventBus` / `SSEManager` | Imported sessions produce standard `DomainEvent` objects |
| `EventRepository` | Persists events identically regardless of source |
| `TrailService` | Consumes `DomainEvent`s — source-agnostic |
| `StepTracker` | Driven by `DomainEvent`s — source-agnostic |
| `SisterSessionManager` | Not applicable (no managed sister sessions) |
| `DiffService` | Works — `worktree_path` points to CLI's `cwd` |
| `MergeService` | Needs a new `_resolve_imported()` path. Existing local merge/checkout/stash logic assumes CodePlane owns the worktree — for imported sessions it must push + remote-merge instead. See §4.1 "No destructive operations" |
| `CodeReconService` | Works — `IngestService` fires background indexing task at session start. Structural features become available when indexing completes. If the repo was already indexed (e.g. previously added via settings), structural features are immediate |
| Frontend SSE handlers | All existing handlers work unchanged |
| Frontend store shape | Only additive field (`source`) |

---

## 11. Capability Matrix

| Feature | Managed | Copilot CLI Import | Claude CLI Import |
|---------|---------|-------------------|-------------------|
| Live transcript | Yes | Yes (OTEL spans) | Yes (hooks) |
| Activity timeline | Yes | Yes | Yes |
| Token/cost metrics | Yes | Yes | Yes |
| Model identification | Yes | Yes | Yes |
| Tool call detail | Yes | Yes (content capture ON) | Yes |
| Diff view | Yes | Yes (git watch on cwd) | Yes (git watch on cwd) |
| Operator messages | Yes | Yes (steer API, ~3s latency) | Yes (hook response, 0ms) |
| Tool blocking | Yes | No | Yes (PreToolUse deny) |
| Cancel/abort | Yes | Yes (steer abort) | Yes (hook block) |
| Streaming text | Yes | No (complete messages) | No (complete messages) |
| Merge/resolve | Yes (local) | Yes (push + remote) | Yes (push + remote) |
| PR creation | Yes | Yes | Yes |
| Approval flow | Yes | No | Yes (PreToolUse hook) |
| Worktree cleanup on discard | Yes (delete) | No (user's directory) | No (user's directory) |

---

## 12. File Change Summary

### New files

| File | Purpose |
|------|---------|
| `backend/services/ingest_service.py` | Central ingestion coordinator |
| `backend/services/otel_file_watcher.py` | Async JSONL file tailer for Copilot OTEL |
| `backend/services/copilot_steer.py` | GitHub steer API client |
| `backend/api/hooks.py` | Claude hook receiver route |
| `backend/api/ingest.py` | Operator messaging routes for imported jobs |
| `alembic/versions/NNNN_add_job_source.py` | DB migration |

### Modified files

| File | Change |
|------|--------|
| `backend/models/domain.py` | Add `JobSource` enum, `source` + `external_session_id` fields to `Job` |
| `backend/models/db.py` | Add `source` + `external_session_id` columns to `JobRow` |
| `backend/models/api_schemas.py` | Add `source`, `external_session_id` to `JobResponse` |
| `backend/persistence/job_repo.py` | Wire new fields in `_to_domain()` and `create()` |
| `backend/config.py` | Add `copilot_otel_path` config field |
| `backend/di.py` | Register `IngestService`, `OtelFileWatcher`, `CopilotSteerClient` |
| `backend/lifespan.py` | Start/stop `OtelFileWatcher` |
| `backend/app_factory.py` | Mount hooks + ingest routers |
| `backend/api/jobs.py` | Route operator message/cancel to `IngestService` for imported jobs. Skip worktree/branch deletion on discard when `source != "managed"` |
| `frontend/src/store/types.ts` | Add `source` to `JobSummary` |
| `frontend/src/components/JobHeaderCard.tsx` | CLI import badge |
| `frontend/src/components/JobDetailScreen.tsx` | No functional changes (full parity) — all action buttons work for imported sessions |

### Unchanged files (confirmed)

| File | Why |
|------|-----|
| `backend/services/runtime_service.py` | Only manages CodePlane-launched sessions |
| `backend/services/agent_adapter.py` | Interface for managed adapters only |
| `backend/services/base_adapter.py` | Base class for managed adapters only |
| `backend/services/adapter_registry.py` | Only creates managed adapters |
| `backend/services/event_bus.py` | Generic — accepts any `DomainEvent` |
| `backend/services/sse_manager.py` | Generic — routes any SSE event |
| `backend/api/events.py` | SSE endpoint is source-agnostic |
| `backend/models/events.py` | No new event kinds needed |
| `frontend/src/hooks/useSSE.ts` | SSE client is source-agnostic |
| `frontend/src/store/sseHandlers.ts` | Handler table is source-agnostic |

---

## 13. Open Questions

1. **Multiple concurrent CLI sessions**: The OTEL file watcher sees all
   sessions interleaved in one JSONL file. The `conversation_id` /
   `session_id` span attribute distinguishes them. Each unique session ID
   maps to a separate CodePlane job.

2. **Session recovery after CodePlane restart**: On startup, the file
   watcher should seek to the end of the OTEL file (or to a persisted
   offset) to avoid replaying historical spans. For Claude hooks, sessions
   in progress will re-fire `SessionStart` on the next hook event — the
   `IngestService` should handle idempotent job creation.

3. **GitHub token for steer API**: CodePlane needs the user's Copilot
   token to call the steer endpoint. This could be sourced from `gh auth
   token` or configured explicitly. Steering is optional — observation
   works without it.

4. **User working on main**: If the CLI session is on the default branch
   directly (no feature branch), merge is a no-op — the changes are
   already where they belong. `IngestService` should detect this at
   session start and set `base_ref == branch` so that `MergeService`
   recognizes there's nothing to merge. The review screen would show
   "already on target branch" and offer PR or mark-complete as the
   primary actions.
