# AgentTower — Product Specification

---

## Table of Contents

1. [Product Overview](#1-product-overview)
2. [Technology Architecture](#2-technology-architecture)
3. [Frontend](#3-frontend)
4. [Backend](#4-backend)
5. [Live Update Model (SSE)](#5-live-update-model-sse)
6. [Execution Runtime](#6-execution-runtime)
7. [Deployment Model](#7-deployment-model)
8. [Repository and Workspace Model](#8-repository-and-workspace-model)
9. [Voice Input](#9-voice-input)
10. [Speech-to-Text](#10-speech-to-text)
11. [Configuration Model](#11-configuration-model)
12. [Canonical Internal Event Model](#12-canonical-internal-event-model)
13. [Job States](#13-job-states)
14. [Execution Phases](#14-execution-phases)
15. [User Interface](#15-user-interface)
16. [Data Model](#16-data-model)
17. [Persistence](#17-persistence)
18. [REST API](#18-rest-api)
19. [Approval System](#19-approval-system)
20. [Diff Model](#20-diff-model)
21. [Observability](#21-observability)
22. [Security Model](#22-security-model)
23. [Engineering Constraints and Pitfalls](#23-engineering-constraints-and-pitfalls)
24. [Sequence Diagrams](#24-sequence-diagrams)
25. [Ross Review: Perceived Gaps and Brainstorming Needed](#25-ross-review-perceived-gaps-and-brainstorming-needed)

---

## 1. Product Overview

AgentTower is a control tower for running and supervising coding agents.

It allows an operator to launch automated coding tasks against real repositories and observe everything the agent does in real time.

The system provides visibility into execution progress, code changes, logs, artifacts, and agent reasoning so work can be reviewed and controlled as it happens.

Operators can intervene at any time by sending instructions, approving risky actions, canceling runs, or rerunning failed tasks.

The interface can be accessed locally or remotely through a Dev Tunnel, allowing jobs to be monitored and controlled from another device such as a phone.

AgentTower turns autonomous coding agents into something observable, controllable, and safe to operate.

### Core Capabilities

| Capability | Description |
|---|---|
| Job orchestration | Launch coding tasks against local repositories |
| Live monitoring | Watch agent reasoning, logs, and code changes as they happen |
| Approval gating | Intercept and approve or reject risky actions before they execute |
| Operator intervention | Send messages, cancel, or rerun jobs at any time |
| Workspace isolation | Each job runs in its own Git worktree |
| Remote access | Dev Tunnel exposes the UI over HTTPS for phone/remote control |
| Voice input | Speak prompts and operator instructions into the browser |
| Artifact inspection | Browse files, diffs, and produced outputs from every job |

---

## 2. Technology Architecture

AgentTower is a two-tier application.

```
┌──────────────────────────────────────────────────┐
│                  Operator Browser                │
│          React + TypeScript Frontend             │
│   REST (commands/queries) + SSE (live events)   │
└────────────────────┬─────────────────────────────┘
                     │ HTTP / SSE
┌────────────────────▼─────────────────────────────┐
│             FastAPI Backend (Python)             │
│  REST API · SSE stream · Job orchestration       │
│  Git workspace mgmt · Copilot SDK adapter        │
│  Approval enforcement · Persistence coordinator  │
└──────┬──────────────┬──────────────┬─────────────┘
       │              │              │
  ┌────▼────┐   ┌─────▼─────┐  ┌───▼────┐
  │ SQLite  │   │ Git repos │  │Copilot │
  │   DB    │   │/worktrees │  │  SDK   │
  └─────────┘   └───────────┘  └────────┘
```

| Tier | Technology |
|---|---|
| Frontend | React 18, TypeScript, Vite |
| Backend | Python 3.11+, FastAPI, Uvicorn |
| Persistence | SQLite (via SQLAlchemy) |
| Agent runtime | Python Copilot SDK (wrapped behind adapter) |
| Workspace isolation | Git worktrees |
| Voice transcription | faster-whisper |
| Remote access | Dev Tunnel (HTTPS) |

---

## 3. Frontend

### 3.1 Responsibilities

- Operator console UI
- Job dashboards (Kanban / list)
- Job detail views
- Live execution monitoring
- Diff visualization
- Artifact inspection
- Workspace browsing
- Approval and operator controls
- Voice input capture

### 3.2 Communication Model

| Channel | Direction | Purpose |
|---|---|---|
| REST API | Client → Server | Commands and queries |
| SSE (`/api/events`) | Server → Client | Live runtime updates |

The frontend never polls for state. All live updates arrive via SSE. REST calls are used exclusively for actions (create job, send message, approve, cancel, etc.) and one-time data fetches.

### 3.3 Application State

Application state has a single source of truth managed by a central state store (e.g., Zustand or Redux Toolkit).

SSE events are processed centrally through a single event dispatcher that updates the store. Components subscribe to the store and never maintain their own copies of job state.

State slices:

| Slice | Contents |
|---|---|
| `jobs` | All job summaries (id, repo, state, created_at, updated_at) |
| `activeJob` | Full detail of currently viewed job |
| `approvals` | Pending approval requests |
| `settings` | Application settings |
| `ui` | Transient UI state (selected panel, filters, etc.) |

### 3.4 Component Hierarchy

```
App
├── Router
│   ├── DashboardScreen
│   │   ├── KanbanBoard (desktop)
│   │   │   ├── KanbanColumn [Active]
│   │   │   ├── KanbanColumn [Sign-off]
│   │   │   ├── KanbanColumn [Failed]
│   │   │   └── KanbanColumn [History]
│   │   └── JobList (mobile)
│   ├── JobDetailScreen
│   │   ├── JobMetadataHeader
│   │   ├── ApprovalBanner
│   │   ├── TranscriptPanel
│   │   ├── LogsPanel
│   │   ├── DiffViewer
│   │   ├── WorkspaceBrowser
│   │   ├── ArtifactViewer
│   │   └── ExecutionTimeline
│   ├── JobCreationScreen
│   │   ├── RepoSelector
│   │   ├── PromptInput
│   │   ├── VoiceInputButton
│   │   ├── ProfileSelector
│   │   └── AdvancedOptions
│   └── SettingsScreen
│       ├── GlobalConfigEditor
│       └── RepoConfigList
└── SSEProvider (global)
```

### 3.5 SSE Client

The SSE client lives in a singleton provider mounted at the app root.

Behavior:

- Connects to `/api/events` on mount
- Tracks the last received `event_id`
- On disconnect, reconnects automatically with `Last-Event-ID` header
- Dispatches each received event to the central store
- Exposes connection status to UI components

### 3.6 TypeScript Domain Models

All domain concepts are represented with explicit TypeScript interfaces. Backend API responses must match these types exactly.

```typescript
type JobState =
  | "queued"
  | "running"
  | "waiting_for_approval"
  | "succeeded"
  | "failed"
  | "canceled";

interface Job {
  id: string;
  repo: string;
  prompt: string;
  state: JobState;
  profile: string;
  baseRef: string;
  worktreePath: string;
  branch: string;
  createdAt: string;   // ISO 8601
  updatedAt: string;   // ISO 8601
  completedAt?: string;
}

interface LogLine {
  jobId: string;
  seq: number;
  timestamp: string;
  level: "debug" | "info" | "warn" | "error";
  message: string;
  context?: Record<string, unknown>;
}

interface TranscriptEntry {
  jobId: string;
  seq: number;
  timestamp: string;
  role: "agent" | "operator";
  content: string;
}

interface ApprovalRequest {
  id: string;
  jobId: string;
  riskLevel: "low" | "medium" | "high" | "critical";
  description: string;
  proposedAction: string;
  requestedAt: string;
  resolvedAt?: string;
  resolution?: "approved" | "rejected";
}

interface DiffFile {
  path: string;
  status: "added" | "modified" | "deleted" | "renamed";
  additions: number;
  deletions: number;
  hunks: DiffHunk[];
}

interface DiffHunk {
  oldStart: number;
  oldLines: number;
  newStart: number;
  newLines: number;
  lines: DiffLine[];
}

interface DiffLine {
  type: "context" | "addition" | "deletion";
  content: string;
}

interface Artifact {
  id: string;
  jobId: string;
  name: string;
  mimeType: string;
  sizeBytes: number;
  phase: ExecutionPhase;
  createdAt: string;
}

type ExecutionPhase =
  | "environment_setup"
  | "agent_reasoning"
  | "validation_and_tests"
  | "finalization"
  | "post_completion";
```

### 3.7 Performance Guidelines

- Large log and transcript lists must use virtualized rendering (e.g., `react-window` or `@tanstack/virtual`)
- Diff viewer must not render all hunks simultaneously for files with more than 500 lines
- Kanban board must not re-render all columns when a single job updates; use memoized selectors per column

---

## 4. Backend

### 4.1 Responsibilities

- REST API endpoints
- SSE event streaming
- Job orchestration
- Copilot session lifecycle management
- Git workspace management
- Artifact collection
- Approval enforcement
- Runtime monitoring
- Persistence coordination
- Voice transcription

### 4.2 Module Structure

```
backend/
├── main.py                    # FastAPI app factory
├── config.py                  # Configuration loading
├── api/
│   ├── jobs.py                # Job CRUD and control endpoints
│   ├── events.py              # SSE streaming endpoint
│   ├── artifacts.py           # Artifact retrieval endpoints
│   ├── workspace.py           # File browsing endpoints
│   ├── approvals.py           # Approval resolution endpoints
│   ├── voice.py               # Voice transcription endpoint
│   └── settings.py            # Settings management endpoints
├── services/
│   ├── job_service.py         # Job lifecycle orchestration
│   ├── runtime_service.py     # Long-running job execution manager
│   ├── git_service.py         # Git worktree and branch operations
│   ├── copilot_adapter.py     # Copilot SDK adapter (interface + impl)
│   ├── event_bus.py           # Internal event bus
│   ├── sse_manager.py         # SSE connection management
│   ├── approval_service.py    # Approval gate enforcement
│   ├── artifact_service.py    # Artifact storage and retrieval
│   ├── diff_service.py        # Diff generation and parsing
│   └── voice_service.py       # faster-whisper transcription
├── models/
│   ├── db.py                  # SQLAlchemy models
│   ├── domain.py              # Domain dataclasses/Pydantic models
│   └── events.py              # Canonical event types
├── persistence/
│   ├── repository.py          # Base repository pattern
│   ├── job_repo.py            # Job persistence
│   ├── event_repo.py          # Event persistence
│   └── artifact_repo.py       # Artifact metadata persistence
└── tests/
    ├── unit/
    └── integration/
```

### 4.3 API Routes Must Not Contain Orchestration Logic

API route handlers are thin. They:

1. Validate and parse input
2. Delegate to a service
3. Return the result

No orchestration logic, no direct database access, and no git operations belong in route handlers.

### 4.4 Copilot SDK Adapter

The Copilot SDK is wrapped behind an interface so the system is not tightly coupled to SDK types.

```python
from abc import ABC, abstractmethod
from typing import AsyncIterator
from dataclasses import dataclass

@dataclass
class SessionConfig:
    workspace_path: str
    prompt: str
    tools_enabled: bool
    approval_mode: str

@dataclass
class SessionEvent:
    kind: str          # "log", "transcript", "diff", "approval_request", "done", "error"
    payload: dict

class CopilotAdapterInterface(ABC):

    @abstractmethod
    async def create_session(self, config: SessionConfig) -> str:
        """Create a session, return session_id."""

    @abstractmethod
    async def stream_events(self, session_id: str) -> AsyncIterator[SessionEvent]:
        """Stream events from a running session."""

    @abstractmethod
    async def send_message(self, session_id: str, message: str) -> None:
        """Inject an operator message into a running session."""

    @abstractmethod
    async def cancel_session(self, session_id: str) -> None:
        """Request cancellation of a session."""
```

The production implementation (`CopilotSDKAdapter`) wraps the real SDK. A `FakeCopilotAdapter` is used in tests.

### 4.5 Internal Event Bus

The `EventBus` is the backbone of the backend. All subsystems communicate through it.

- Services publish domain events to the bus
- Persistence layer subscribes and persists events
- SSE manager subscribes and pushes events to connected clients
- Job state machine subscribes and applies transitions

The event bus is an in-process async pub/sub. It is not a message broker. All subscribers run in the same process.

---

## 5. Live Update Model (SSE)

### 5.1 Endpoint

```
GET /api/events
```

Optional query parameter to scope to a single job:

```
GET /api/events?job_id={job_id}
```

### 5.2 SSE Event Format

Each event follows the standard SSE wire format:

```
id: {event_id}
event: {event_type}
data: {json_payload}

```

### 5.3 Event Types

| Event Type | Payload Summary |
|---|---|
| `job_state_changed` | `{ job_id, previous_state, new_state, timestamp }` |
| `log_line` | `{ job_id, seq, timestamp, level, message, context }` |
| `transcript_update` | `{ job_id, seq, timestamp, role, content }` |
| `diff_update` | `{ job_id, changed_files: DiffFile[] }` |
| `approval_requested` | `{ job_id, approval_id, risk_level, description, proposed_action }` |
| `session_heartbeat` | `{ job_id, session_id, timestamp }` |

### 5.4 Reconnection and Replay

- Every SSE event carries a monotonically increasing `id`
- The client sends `Last-Event-ID` on reconnect
- The backend replays all events with `id > Last-Event-ID` from the event log in SQLite
- Replay is bounded: events older than the job's terminal state are not replayed

### 5.5 SSE Manager

The `SSEManager` service:

- Maintains the set of open SSE connections
- Subscribes to the internal event bus
- Serializes events to SSE wire format
- Broadcasts or routes events to appropriate connections
- Handles client disconnection cleanup

---

## 6. Execution Runtime

### 6.1 Job Lifecycle

When a job is created:

1. `JobService` validates the request
2. `GitService` creates the worktree and branch
3. `JobService` persists a `JobCreated` event and a `WorkspacePrepared` event
4. `RuntimeService` is asked to run the job
5. `RuntimeService` creates an asyncio task for the job
6. The task calls `CopilotAdapter.create_session()` and then `stream_events()`
7. Each SDK event is translated into a domain event and published to the event bus
8. When the session ends, the job transitions to `succeeded`, `failed`, or `canceled`

### 6.2 Runtime Service

The `RuntimeService` manages all active job tasks.

- Tracks running asyncio tasks by `job_id`
- Enforces `max_concurrent_jobs` from global config
- Enqueues jobs if at capacity (state: `queued`)
- Starts queued jobs when capacity opens
- Provides a `cancel(job_id)` method that cancels the asyncio task and calls `CopilotAdapter.cancel_session()`

### 6.3 Operator Message Injection

When an operator sends a message to a running job:

1. `POST /api/jobs/{job_id}/messages` received
2. Route delegates to `JobService.send_operator_message()`
3. Service calls `CopilotAdapter.send_message(session_id, message)`
4. A `TranscriptUpdated` event is published with `role="operator"`

### 6.4 Approval Pause

When the Copilot SDK emits an approval request event:

1. Adapter translates to `ApprovalRequested` domain event
2. Event bus delivers to `ApprovalService`
3. `ApprovalService` persists the request and pauses the session
4. Job transitions to `waiting_for_approval`
5. `ApprovalRequested` SSE event sent to frontend
6. Operator approves or rejects via `POST /api/approvals/{approval_id}/resolve`
7. `ApprovalService` records resolution and resumes the session

---

## 7. Deployment Model

AgentTower runs entirely on a single developer machine.

```
Developer Machine
├── AgentTower Backend (FastAPI on localhost:8080)
├── AgentTower Frontend (Vite dev server or static on localhost:5173)
├── SQLite database (~/.agenttower/data.db)
├── Artifact storage (~/.agenttower/artifacts/)
├── Global config (~/.agenttower/config.yaml)
├── Local git repositories (/repos/...)
└── Dev Tunnel (HTTPS tunnel to public URL)
```

### 7.1 Dev Tunnel

Dev Tunnel exposes the local application over HTTPS, enabling remote access from phones and other devices.

- The tunnel URL must be kept private (shared only with the operator)
- Authentication is required on all endpoints when accessed through the tunnel
- The backend must enforce CORS to prevent cross-origin abuse from other browser tabs

### 7.2 Startup

The system is started with a single command:

```bash
agenttower start
```

This command:

1. Loads and validates global config
2. Initializes the SQLite database (runs migrations)
3. Starts the FastAPI server
4. Optionally starts the Dev Tunnel

---

## 8. Repository and Workspace Model

### 8.1 Repository Allowlist

Only repositories listed in the global config `repos` field may be used. Any request to operate on a path not in the allowlist is rejected with `403 Forbidden`.

### 8.2 Worktree Creation

When a job starts:

1. Backend resolves the repository root from the allowlist
2. A worktree directory is created at:
   ```
   {repo_root}/{worktrees_dirname}/{job_id}/
   ```
   Default `worktrees_dirname`: `.agenttower-worktrees`
3. A new branch is created from the configured `base_branch`:
   ```
   agenttower/job-{job_id}-{slug}
   ```
   where `{slug}` is a short sanitized version of the prompt (max 40 chars, lowercase, hyphens only)

Example:

```
/repos/service-a/
/repos/service-a/.agenttower-worktrees/job-104/
/repos/service-a/.agenttower-worktrees/job-105/
```

### 8.3 Branch Naming

```
agenttower/job-{job_id}-{slug}
```

Examples:

```
agenttower/job-104-fix-null-pointer-in-user-service
agenttower/job-105-add-pagination-to-orders-api
```

### 8.4 Workspace Cleanup

On job completion (success, failure, or cancel):

- The worktree directory is retained for artifact inspection and diff browsing
- Worktrees are not automatically deleted; operators must explicitly clean them up via a settings action
- A background cleanup command may be scheduled via settings: `POST /api/settings/cleanup-worktrees`

### 8.5 Protected Paths

If a per-repository config defines `protected_paths`, the Copilot session must not modify those paths. The approval system enforces this: any file write to a protected path automatically triggers an `ApprovalRequested` event with `risk_level: critical`.

### 8.6 Concurrent Jobs on the Same Repository

Multiple jobs may target the same repository concurrently.

Isolation is guaranteed by Git worktrees: each job works in its own worktree and cannot interfere with another job's files. The base repository working tree is never modified by any job. The main branch of the repository is never written to.

---

## 9. Voice Input

### 9.1 Workflow

1. Operator presses and holds the microphone button in the browser
2. Browser requests microphone permission (`getUserMedia`)
3. `MediaRecorder` records audio chunks while button is held
4. On release, recording stops
5. Chunks are combined into a single audio blob (WebM/Opus or WAV)
6. Blob uploaded via `POST /api/voice/transcribe` as `multipart/form-data`
7. Backend transcribes and returns `{ text: "..." }`
8. Transcribed text is inserted into the active prompt or message input field

### 9.2 Frontend Implementation

```typescript
async function recordAndTranscribe(): Promise<string> {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  const recorder = new MediaRecorder(stream);
  const chunks: Blob[] = [];

  recorder.ondataavailable = (e) => chunks.push(e.data);

  await new Promise<void>((resolve) => {
    recorder.onstop = () => resolve();
    // caller triggers recorder.stop() on button release
  });

  const blob = new Blob(chunks, { type: "audio/webm" });
  const form = new FormData();
  form.append("audio", blob, "recording.webm");

  const res = await fetch("/api/voice/transcribe", { method: "POST", body: form });
  const { text } = await res.json();
  return text;
}
```

### 9.3 Voice Input Contexts

Voice input is available in two contexts:

| Context | Description |
|---|---|
| Job creation prompt | Dictate the initial task prompt |
| Operator message | Dictate a mid-run instruction to send to the agent |

---

## 10. Speech-to-Text

### 10.1 Engine

Local transcription uses `faster-whisper`.

### 10.2 Models

| Model | RAM | Latency (approx.) | Use case |
|---|---|---|---|
| `tiny.en` | ~150 MB | 100–300 ms | Low-latency, English only |
| `base.en` | 300–400 MB | 300–800 ms | Default, better accuracy |

Default model: `base.en`

### 10.3 Configuration

```yaml
voice:
  enabled: true
  model: base.en     # or tiny.en
```

### 10.4 Backend Endpoint

```
POST /api/voice/transcribe
Content-Type: multipart/form-data

Field: audio (binary)
```

Response:

```json
{
  "text": "Fix the null pointer exception in the user service."
}
```

### 10.5 Transcription Service

```python
from faster_whisper import WhisperModel

class VoiceService:
    def __init__(self, model_name: str = "base.en"):
        self._model = WhisperModel(model_name, device="cpu", compute_type="int8")

    def transcribe(self, audio_bytes: bytes) -> str:
        segments, _ = self._model.transcribe(audio_bytes)
        return " ".join(seg.text.strip() for seg in segments)
```

The model is loaded once at startup and reused across requests.

---

## 11. Configuration Model

### 11.1 Overview

Configuration exists at three layers:

| Layer | Location | Scope |
|---|---|---|
| Global | `~/.agenttower/config.yaml` | Machine-level runtime behavior |
| Per-repository | `{repo_root}/.agenttower.yml` | Repository-specific overrides |
| Per-job | Job creation payload | Single-job overrides |

### 11.2 Global Configuration

File: `~/.agenttower/config.yaml`

```yaml
server:
  host: 127.0.0.1
  port: 8080

auth:
  enabled: true
  token: "changeme"     # Bearer token for UI authentication

runtime:
  max_concurrent_jobs: 2
  worktrees_dirname: .agenttower-worktrees

voice:
  enabled: true
  model: base.en

repos:
  - /repos/service-a
  - /repos/service-b

tools:
  mcp:
    github:
      command: npx
      args: ["-y", "@modelcontextprotocol/server-github"]
    postgres:
      command: uvx
      args: ["mcp-postgres"]

profiles:
  default:
    approval_mode: standard
    allow_tools: true
  cautious:
    approval_mode: strict
    allow_tools: true
  readonly:
    approval_mode: strict
    allow_tools: false
```

#### 11.2.1 Global Tool Registry

The `tools.mcp` block defines available MCP tools by name. Each entry specifies:

- `command`: executable to run
- `args`: arguments array

The registry defines availability only. Tools are not enabled unless a per-repository config explicitly lists them in `tools.mcp.enabled`.

#### 11.2.2 Agent Profiles

Profiles define execution policies:

| Profile | approval_mode | allow_tools | Intended use |
|---|---|---|---|
| `default` | `standard` | `true` | Normal automated tasks |
| `cautious` | `strict` | `true` | Tasks touching sensitive code |
| `readonly` | `strict` | `false` | Exploration/analysis tasks |

`approval_mode` values:

- `standard`: approve only genuinely risky actions
- `strict`: approve all file writes and shell commands

### 11.3 Per-Repository Configuration

File: `{repo_root}/.agenttower.yml`

```yaml
base_branch: main
validation_command: pytest -q

protected_paths:
  - infra/
  - .github/workflows/

agent:
  profile: default

tools:
  mcp:
    enabled:
      - github
```

| Field | Description |
|---|---|
| `base_branch` | Branch to create worktree from |
| `validation_command` | Shell command to run during validation phase |
| `protected_paths` | Paths that require approval before modification |
| `agent.profile` | Default profile for jobs on this repo |
| `tools.mcp.enabled` | Which globally-defined MCP tools are active for this repo |

### 11.4 Per-Job Overrides

Provided in the job creation request body:

```json
{
  "repo": "/repos/service-a",
  "prompt": "Fix the null pointer exception in UserService.java",
  "base_ref": "main",
  "profile": "cautious",
  "run_validation": true
}
```

| Field | Required | Description |
|---|---|---|
| `repo` | Yes | Path to repository (must be in allowlist) |
| `prompt` | Yes | Task description for the agent |
| `base_ref` | No | Override base branch/commit |
| `profile` | No | Override agent profile |
| `run_validation` | No | Whether to run `validation_command` (default: true) |

---

## 12. Canonical Internal Event Model

All runtime activity is represented as structured domain events. Every event has a shared envelope:

```python
@dataclass
class DomainEvent:
    event_id: str       # UUID
    job_id: str
    timestamp: datetime
    kind: str           # One of the event type names below
    payload: dict
```

### 12.1 Event Types

| Event Kind | Trigger | Key Payload Fields |
|---|---|---|
| `JobCreated` | Job creation request accepted | `repo`, `prompt`, `profile`, `base_ref` |
| `WorkspacePrepared` | Worktree and branch created | `worktree_path`, `branch` |
| `AgentSessionStarted` | Copilot session created | `session_id` |
| `LogLineEmitted` | Agent or system log output | `seq`, `level`, `message`, `context` |
| `TranscriptUpdated` | Agent reasoning or operator message | `seq`, `role`, `content` |
| `DiffUpdated` | File changes detected in worktree | `changed_files` (list of DiffFile) |
| `ApprovalRequested` | Risky action intercepted | `approval_id`, `risk_level`, `description`, `proposed_action` |
| `ApprovalResolved` | Operator approves or rejects | `approval_id`, `resolution` |
| `ValidationStarted` | Validation phase begins | `command` |
| `ValidationCompleted` | Validation phase ends | `exit_code`, `output` |
| `JobSucceeded` | Session completed successfully | `summary` |
| `JobFailed` | Session terminated with error | `error`, `traceback` |
| `JobCanceled` | Operator canceled the job | `reason` |

### 12.2 Event Consumers

| Consumer | Events consumed | Action |
|---|---|---|
| `JobStateMachine` | All state-relevant events | Applies state transitions |
| `PersistenceSubscriber` | All events | Persists to SQLite event log |
| `SSEManager` | All events | Pushes to connected SSE clients |
| `ApprovalService` | `ApprovalRequested` | Pauses session, awaits resolution |
| `DiffService` | `WorkspacePrepared`, `JobSucceeded` | Generates and stores diff snapshots |
| `ArtifactService` | `JobSucceeded`, `ValidationCompleted` | Collects and stores artifacts |
| `TimelineBuilder` | All events | Updates job timeline view |

---

## 13. Job States

### 13.1 States

| State | Description |
|---|---|
| `queued` | Job accepted but not yet started (at capacity) |
| `running` | Agent session is active |
| `waiting_for_approval` | Session paused, awaiting operator decision |
| `succeeded` | Session completed successfully |
| `failed` | Session terminated with an error |
| `canceled` | Operator canceled the job |

### 13.2 State Transition Table

| From | Event | To |
|---|---|---|
| _(none)_ | `JobCreated` + capacity available | `running` |
| _(none)_ | `JobCreated` + at capacity | `queued` |
| `queued` | Capacity opens | `running` |
| `queued` | `JobCanceled` | `canceled` |
| `running` | `ApprovalRequested` | `waiting_for_approval` |
| `running` | `JobSucceeded` | `succeeded` |
| `running` | `JobFailed` | `failed` |
| `running` | `JobCanceled` | `canceled` |
| `waiting_for_approval` | `ApprovalResolved` (approved) | `running` |
| `waiting_for_approval` | `ApprovalResolved` (rejected) | `failed` |
| `waiting_for_approval` | `JobCanceled` | `canceled` |

Terminal states (`succeeded`, `failed`, `canceled`) have no further transitions.

### 13.3 Rerun

Rerunning a job creates a new job record. The original job is not mutated. The new job copies the original's `repo`, `prompt`, `base_ref`, and `profile`.

---

## 14. Execution Phases

| Phase | Description | Example events |
|---|---|---|
| `environment_setup` | Workspace creation, branch, dependency install | `WorkspacePrepared`, `LogLineEmitted` |
| `agent_reasoning` | Agent reads code, thinks, plans, and writes changes | `TranscriptUpdated`, `DiffUpdated`, `ApprovalRequested` |
| `validation_and_tests` | Validation command runs | `ValidationStarted`, `ValidationCompleted`, `LogLineEmitted` |
| `finalization` | Final diff snapshot, artifact collection | `DiffUpdated`, `JobSucceeded` |
| `post_completion` | Operator reviews, approves, or reruns | _(no agent events)_ |

Artifacts and timeline entries carry the phase in which they were produced. The frontend uses phase labels to group the execution timeline.

---

## 15. User Interface

### 15.1 Dashboard

**Desktop layout: Kanban board**

Columns:

| Column | States shown |
|---|---|
| Active | `queued`, `running` |
| Sign-off | `waiting_for_approval` |
| Failed | `failed` |
| History | `succeeded`, `canceled` |

Each card displays: job ID, repository name, prompt excerpt, elapsed time, and status badge.

**Mobile layout: Filtered job list**

A single scrollable list of jobs. Filter tabs at the top correspond to the Kanban columns. Tapping a job opens the Job Detail screen.

### 15.2 Job Detail Screen

Sections:

| Section | Contents |
|---|---|
| **Job Metadata Header** | Job ID, repo, branch, state badge, started/completed timestamps, profile |
| **Approval Banner** | Shown only in `waiting_for_approval` state. Displays risk level, description, proposed action, and Approve/Reject buttons |
| **Transcript Panel** | Scrolling list of agent reasoning messages and operator injections. Auto-scrolls to bottom on new entries |
| **Logs Panel** | Raw log output with level filtering (debug/info/warn/error). Virtualized list |
| **Diff Viewer** | Per-file diffs with syntax highlighting, additions/deletions counts, and hunk navigation |
| **Workspace Browser** | File tree of the worktree. Click a file to view its contents |
| **Artifact Viewer** | List of collected artifacts with download links |
| **Execution Timeline** | Chronological list of key events grouped by phase |

### 15.3 Job Creation Screen

Fields:

| Field | Type | Notes |
|---|---|---|
| Repository | Dropdown | Only repositories in allowlist |
| Prompt | Textarea + voice button | Task description |
| Base reference | Text | Default: repo's `base_branch` |
| Profile | Dropdown | Profiles from global config |
| Run validation | Toggle | Default: on |

### 15.4 Settings Screen

Sections:

- Global config viewer/editor (YAML text editor with validation)
- Repository config list (per-repo `.agenttower.yml` viewer)
- Worktree cleanup action
- Voice model selector

---

## 16. Data Model

### 16.1 SQLite Schema

#### jobs

```sql
CREATE TABLE jobs (
    id TEXT PRIMARY KEY,
    repo TEXT NOT NULL,
    prompt TEXT NOT NULL,
    state TEXT NOT NULL,
    profile TEXT NOT NULL,
    base_ref TEXT NOT NULL,
    branch TEXT,
    worktree_path TEXT,
    session_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT
);
```

#### events

```sql
CREATE TABLE events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    job_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    payload TEXT NOT NULL,        -- JSON
    FOREIGN KEY (job_id) REFERENCES jobs(id)
);
CREATE INDEX idx_events_job_id ON events(job_id);
CREATE INDEX idx_events_id ON events(id);
```

#### approvals

```sql
CREATE TABLE approvals (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    risk_level TEXT NOT NULL,
    description TEXT NOT NULL,
    proposed_action TEXT NOT NULL,
    requested_at TEXT NOT NULL,
    resolved_at TEXT,
    resolution TEXT,
    FOREIGN KEY (job_id) REFERENCES jobs(id)
);
```

#### artifacts

```sql
CREATE TABLE artifacts (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    name TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    disk_path TEXT NOT NULL,
    phase TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (job_id) REFERENCES jobs(id)
);
```

#### diff_snapshots

```sql
CREATE TABLE diff_snapshots (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    snapshot_at TEXT NOT NULL,
    diff_json TEXT NOT NULL,      -- serialized list of DiffFile
    FOREIGN KEY (job_id) REFERENCES jobs(id)
);
CREATE INDEX idx_diff_snapshots_job_id ON diff_snapshots(job_id);
```

---

## 17. Persistence

### 17.1 Storage Layout

```
~/.agenttower/
├── config.yaml
├── data.db            # SQLite database
└── artifacts/
    └── {job_id}/
        └── {artifact_id}-{name}
```

### 17.2 Migrations

Schema migrations are managed with Alembic. The backend runs `alembic upgrade head` at startup before accepting requests.

### 17.3 Persistence Layer Design

All database access is mediated through repository classes. No SQLAlchemy sessions are used directly in services or route handlers.

```python
class JobRepository:
    def create(self, job: Job) -> Job: ...
    def get(self, job_id: str) -> Job | None: ...
    def list(self, state: str | None = None) -> list[Job]: ...
    def update_state(self, job_id: str, new_state: str, updated_at: datetime) -> None: ...

class EventRepository:
    def append(self, event: DomainEvent) -> None: ...
    def list_after(self, after_event_id: int, job_id: str | None = None) -> list[DomainEvent]: ...

class ArtifactRepository:
    def create(self, artifact: Artifact) -> Artifact: ...
    def list_for_job(self, job_id: str) -> list[Artifact]: ...
    def get(self, artifact_id: str) -> Artifact | None: ...
```

---

## 18. REST API

All endpoints are prefixed with `/api`.

Authentication: `Authorization: Bearer {token}` when `auth.enabled: true`.

### 18.1 Jobs

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/jobs` | Create a new job |
| `GET` | `/api/jobs` | List all jobs (optional `?state=` filter) |
| `GET` | `/api/jobs/{job_id}` | Get full job detail |
| `POST` | `/api/jobs/{job_id}/cancel` | Cancel a running or queued job |
| `POST` | `/api/jobs/{job_id}/rerun` | Create a new job from this job's config |
| `POST` | `/api/jobs/{job_id}/messages` | Send an operator message to a running job |

#### Create Job — Request

```json
POST /api/jobs
{
  "repo": "/repos/service-a",
  "prompt": "Fix the null pointer in UserService",
  "base_ref": "main",
  "profile": "cautious",
  "run_validation": true
}
```

#### Create Job — Response

```json
201 Created
{
  "id": "job-104",
  "state": "running",
  "branch": "agenttower/job-104-fix-null-pointer-in-userservice",
  "worktree_path": "/repos/service-a/.agenttower-worktrees/job-104",
  "created_at": "2025-01-01T12:00:00Z"
}
```

### 18.2 Events (SSE)

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/events` | SSE stream for all jobs |
| `GET` | `/api/events?job_id={id}` | SSE stream scoped to one job |

### 18.3 Approvals

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/jobs/{job_id}/approvals` | List approvals for a job |
| `POST` | `/api/approvals/{approval_id}/resolve` | Approve or reject |

#### Resolve Approval — Request

```json
POST /api/approvals/{approval_id}/resolve
{
  "resolution": "approved"    // or "rejected"
}
```

### 18.4 Artifacts

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/jobs/{job_id}/artifacts` | List artifacts for a job |
| `GET` | `/api/artifacts/{artifact_id}` | Download artifact file |

### 18.5 Workspace

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/jobs/{job_id}/workspace` | List files in job's worktree |
| `GET` | `/api/jobs/{job_id}/workspace/file` | Get file contents (`?path=relative/path`) |

### 18.6 Voice

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/voice/transcribe` | Upload audio, receive transcript |

### 18.7 Settings

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/settings/global` | Get current global config |
| `PUT` | `/api/settings/global` | Update global config |
| `GET` | `/api/settings/repos` | List repo configs |
| `POST` | `/api/settings/cleanup-worktrees` | Clean up completed job worktrees |

### 18.8 Error Responses

All errors return a consistent envelope:

```json
{
  "error": {
    "code": "JOB_NOT_FOUND",
    "message": "Job job-999 does not exist."
  }
}
```

| HTTP Status | Condition |
|---|---|
| 400 | Validation error in request |
| 401 | Missing or invalid auth token |
| 403 | Repository not in allowlist, or protected path violation |
| 404 | Resource not found |
| 409 | State conflict (e.g., cancel an already-completed job) |
| 500 | Internal server error |

---

## 19. Approval System

### 19.1 Purpose

Approval gates intercept risky operations before they execute. This ensures the operator maintains control over destructive or irreversible actions.

### 19.2 Triggers

An approval request is automatically raised when the agent attempts any of the following:

| Category | Examples |
|---|---|
| Destructive file operations | `rm -rf`, mass deletion, overwriting binary files |
| Infrastructure modification | Terraform apply, Kubernetes manifest changes |
| Dangerous shell commands | `sudo`, `chmod 777`, `curl | bash` |
| Protected directory writes | Any path matching `protected_paths` in repo config |
| Secret or credential files | `.env`, `*.pem`, `*.key` |

### 19.3 Approval Request Object

```json
{
  "id": "appr-88",
  "job_id": "job-104",
  "risk_level": "high",
  "description": "Agent wants to delete all files in /tmp/build",
  "proposed_action": "rm -rf /tmp/build",
  "requested_at": "2025-01-01T12:05:00Z"
}
```

`risk_level` values: `low`, `medium`, `high`, `critical`

### 19.4 Approval Flow

1. Agent triggers a risky action
2. Copilot SDK emits approval-request event
3. Adapter translates to `ApprovalRequested` domain event
4. `ApprovalService` persists the request
5. Job transitions to `waiting_for_approval`
6. `ApprovalRequested` SSE event sent to frontend
7. Frontend renders approval banner on Job Detail screen
8. Operator clicks Approve or Reject
9. `POST /api/approvals/{id}/resolve` called
10. `ApprovalService` persists the resolution and calls `CopilotAdapter.send_message()` with the decision
11. `ApprovalResolved` domain event published
12. Job transitions back to `running`

### 19.5 Approval Mode Behavior

| Mode | Behavior |
|---|---|
| `standard` | Only actions matching the trigger list require approval |
| `strict` | All file writes and shell executions require approval |

---

## 20. Diff Model

### 20.1 Diff Generation

Diffs are generated relative to the base branch using git:

```bash
git diff {base_ref}...HEAD
```

This command is run inside the job's worktree. The output is standard unified diff format.

### 20.2 Hunk Parsing

The `DiffService` parses raw unified diff output into structured `DiffFile` and `DiffHunk` objects (see TypeScript models in Section 3.6 for the equivalent Python representation).

Parser responsibilities:

- Extract changed file paths (old and new)
- Detect file status (added, modified, deleted, renamed)
- Parse hunk headers (`@@ -a,b +c,d @@`)
- Classify each line as context, addition, or deletion
- Count additions and deletions per file

### 20.3 Diff Updates

`DiffUpdated` events are emitted:

- When the agent writes a file (debounced, at most once per 5 seconds)
- When a validation phase completes
- When the job reaches a terminal state

### 20.4 Diff Snapshots

At job completion, a final diff snapshot is stored in the `diff_snapshots` table. This snapshot represents the full set of changes produced by the job.

### 20.5 Frontend Diff Rendering

The `DiffViewer` component:

- Lists all changed files with status icons and line count badges
- Expands a file to show its hunks
- Renders each line with syntax highlighting and color coding (green for additions, red for deletions, gray for context)
- Supports collapsing unchanged context blocks
- Shows a summary bar: total files changed, total additions, total deletions

---

## 21. Observability

### 21.1 Job Health

The Job Detail screen exposes:

- Current state with color-coded badge
- Session heartbeat timestamp (updated by `session_heartbeat` SSE events every 30 seconds)
- If no heartbeat received in 90 seconds, a "Session unresponsive" warning is shown

### 21.2 Runtime Logs

Logs are streamed in real time via SSE `log_line` events.

Backend logging uses structured JSON format via Python's `structlog` library:

```python
log.info("job_started", job_id=job_id, repo=repo, profile=profile)
log.error("session_error", job_id=job_id, error=str(exc), traceback=traceback.format_exc())
```

Every log line carries:

- `timestamp`
- `level`
- `message`
- `job_id` (when applicable)
- Additional structured context fields

### 21.3 Failure Diagnostics

When a job enters `failed` state, the Job Detail screen shows:

- The error message from the `JobFailed` event payload
- The traceback (if available)
- The last log lines before failure
- The last transcript entries

### 21.4 Session Heartbeat

The backend publishes a `session_heartbeat` domain event every 30 seconds for each running session. The frontend uses these to display session health status.

---

## 22. Security Model

### 22.1 Authentication

When `auth.enabled: true` in global config:

- All REST API endpoints require `Authorization: Bearer {token}`
- The SSE endpoint requires the token as a query parameter: `/api/events?token={token}` (browsers cannot set headers on SSE connections)
- The token is a static secret stored in global config
- HTTPS is enforced by the Dev Tunnel when accessing remotely

### 22.2 Repository Allowlist

The `repos` list in global config is the authoritative allowlist.

- All job creation requests are validated against this list
- Any path traversal attempts (e.g., `../../etc/passwd`) are rejected
- The backend resolves all paths to their canonical absolute form before comparison

### 22.3 Filesystem Protections

- The backend never serves files outside of whitelisted repository paths or the artifact storage directory
- All file-read endpoints validate the requested path against the job's worktree root
- Directory traversal attacks are prevented by canonicalizing paths and asserting prefix membership

### 22.4 Approval Gating

Risky operations require explicit operator approval before execution. This prevents autonomous destructive actions, especially when the agent misunderstands intent.

### 22.5 CORS

The backend enforces CORS. By default, only `http://localhost:5173` and the Dev Tunnel origin are permitted.

---

## 23. Engineering Constraints and Pitfalls

### 23.1 Backend Rules

| Rule | Rationale |
|---|---|
| API routes must not contain orchestration logic | Routes should delegate to services; mixing concerns makes testing and refactoring difficult |
| Copilot SDK must be wrapped behind an adapter | Prevents tight coupling to SDK types; enables testing with fakes |
| Git operations must be isolated behind `GitService` | Prevents git logic from spreading across the codebase; enables mocking |
| Long-running jobs must be managed by `RuntimeService` | Central task management enables cancellation, capacity enforcement, and recovery |
| Job state transitions must be explicit | Prevents invalid state changes and makes the state machine auditable |
| Important state must be persisted | Enables restart recovery and event replay |
| Logging must include structured context | Enables filtering and correlation in production |

### 23.2 Frontend Rules

| Rule | Rationale |
|---|---|
| Application state must have a single source of truth | Prevents inconsistency between components |
| SSE events must be processed centrally | Prevents duplicate state updates and race conditions |
| Components must not duplicate job state | Components should read from the store, not maintain local copies |
| Large lists must avoid excessive re-renders | Virtualization required for log and transcript panels |
| Domain models must be strongly typed | TypeScript interfaces prevent entire classes of runtime errors |

### 23.3 Testing Requirements

| Test type | Coverage target |
|---|---|
| Unit tests | Job state machine transitions |
| Unit tests | Approval service logic |
| Unit tests | Diff parser (hunk parsing, line classification) |
| Unit tests | Config loading and validation |
| Integration tests | Git service: worktree creation, branch creation, cleanup |
| Integration tests | Concurrent jobs on same repository |
| Integration tests | Approval flow end-to-end |
| Integration tests | Job restart recovery (simulate process restart) |
| Integration tests | SSE reconnection and event replay |

### 23.4 Style Requirements

**Backend:**

- Python 3.11+
- `mypy` with strict mode for type checking
- `ruff` for linting and formatting
- `pytest` for testing

**Frontend:**

- TypeScript strict mode
- ESLint with React and TypeScript rules
- Prettier for formatting
- Vitest for unit tests
- Playwright for end-to-end tests

---

## 24. Sequence Diagrams

All diagrams use participants:

- **Operator** — human at the UI
- **React UI** — frontend application
- **FastAPI** — backend application
- **JobRuntime** — RuntimeService + asyncio task
- **CopilotSDK** — adapter-wrapped Copilot SDK
- **GitWorkspace** — GitService + worktree
- **Persistence** — SQLite via repositories
- **SSEStream** — SSEManager + client connection

---

### 24.1 Job Creation and Workspace Initialization

```
Operator -> React UI: Fill job form, click Create
React UI -> FastAPI: POST /api/jobs
FastAPI -> FastAPI: Validate repo in allowlist
FastAPI -> GitWorkspace: create_worktree(repo, base_ref, job_id)
GitWorkspace --> FastAPI: worktree_path, branch
FastAPI -> Persistence: persist JobCreated event
FastAPI -> Persistence: persist WorkspacePrepared event
FastAPI -> JobRuntime: enqueue(job)
JobRuntime -> FastAPI: job accepted (state=running or queued)
FastAPI --> React UI: 201 { job_id, state, branch, worktree_path }
React UI -> SSEStream: subscribe /api/events?job_id={id}
JobRuntime -> CopilotSDK: create_session(workspace_path, prompt)
CopilotSDK --> JobRuntime: session_id
JobRuntime -> Persistence: persist AgentSessionStarted
JobRuntime -> SSEStream: job_state_changed (queued->running)
SSEStream --> React UI: job_state_changed event
React UI -> React UI: Update job state badge
```

---

### 24.2 Agent Execution Lifecycle

```
JobRuntime -> CopilotSDK: stream_events(session_id)
loop [SDK emits events]
    CopilotSDK --> JobRuntime: SessionEvent(kind="transcript", ...)
    JobRuntime -> Persistence: persist TranscriptUpdated
    JobRuntime -> SSEStream: transcript_update
    SSEStream --> React UI: transcript_update
    React UI -> React UI: Append to TranscriptPanel

    CopilotSDK --> JobRuntime: SessionEvent(kind="log", ...)
    JobRuntime -> Persistence: persist LogLineEmitted
    JobRuntime -> SSEStream: log_line
    SSEStream --> React UI: log_line
    React UI -> React UI: Append to LogsPanel

    CopilotSDK --> JobRuntime: SessionEvent(kind="diff", ...)
    JobRuntime -> GitWorkspace: generate_diff(worktree, base_ref)
    GitWorkspace --> JobRuntime: DiffFile[]
    JobRuntime -> Persistence: persist DiffUpdated
    JobRuntime -> SSEStream: diff_update
    SSEStream --> React UI: diff_update
    React UI -> React UI: Refresh DiffViewer
end

CopilotSDK --> JobRuntime: SessionEvent(kind="done")
JobRuntime -> GitWorkspace: final_diff(worktree, base_ref)
JobRuntime -> Persistence: persist DiffUpdated (final)
JobRuntime -> Persistence: persist JobSucceeded
JobRuntime -> SSEStream: job_state_changed (running->succeeded)
SSEStream --> React UI: job_state_changed
React UI -> React UI: Show succeeded badge, enable rerun
```

---

### 24.3 Approval Pause and Resolution

```
CopilotSDK --> JobRuntime: SessionEvent(kind="approval_request", risk_level="high", ...)
JobRuntime -> FastAPI: ApprovalRequested domain event
FastAPI -> Persistence: persist ApprovalRequested
FastAPI -> Persistence: update job state = waiting_for_approval
FastAPI -> SSEStream: approval_requested event
FastAPI -> SSEStream: job_state_changed (running->waiting_for_approval)
SSEStream --> React UI: approval_requested
SSEStream --> React UI: job_state_changed
React UI -> React UI: Show ApprovalBanner with risk level + proposed action

Operator -> React UI: Click "Approve"
React UI -> FastAPI: POST /api/approvals/{id}/resolve { resolution: "approved" }
FastAPI -> Persistence: persist ApprovalResolved
FastAPI -> Persistence: update job state = running
FastAPI -> CopilotSDK: send_message(session_id, "approved")
FastAPI -> SSEStream: job_state_changed (waiting_for_approval->running)
SSEStream --> React UI: job_state_changed
React UI -> React UI: Hide ApprovalBanner, show running state
CopilotSDK -> CopilotSDK: Resume execution
```

---

### 24.4 Job Cancellation

```
Operator -> React UI: Click "Cancel Job"
React UI -> FastAPI: POST /api/jobs/{job_id}/cancel
FastAPI -> JobRuntime: cancel(job_id)
JobRuntime -> CopilotSDK: cancel_session(session_id)
CopilotSDK --> JobRuntime: session canceled
JobRuntime -> Persistence: persist JobCanceled
JobRuntime -> Persistence: update job state = canceled
JobRuntime -> SSEStream: job_state_changed (running->canceled)
SSEStream --> React UI: job_state_changed
React UI -> React UI: Show canceled badge
FastAPI --> React UI: 200 OK
```

If job is `waiting_for_approval` at cancel time:

```
FastAPI -> Persistence: persist ApprovalResolved (resolution=rejected, reason=canceled)
FastAPI -> JobRuntime: cancel(job_id)
JobRuntime -> CopilotSDK: cancel_session(session_id)
[continues as above]
```

---

### 24.5 Job Rerun

```
Operator -> React UI: Click "Rerun"
React UI -> FastAPI: POST /api/jobs/{job_id}/rerun
FastAPI -> Persistence: get original job config
FastAPI -> FastAPI: Create new job (same repo, prompt, profile, base_ref)
FastAPI -> GitWorkspace: create_worktree(repo, base_ref, new_job_id)
FastAPI -> Persistence: persist JobCreated (new job)
FastAPI -> Persistence: persist WorkspacePrepared (new job)
FastAPI -> JobRuntime: enqueue(new_job)
FastAPI --> React UI: 201 { new_job_id, state, branch }
React UI -> React UI: Navigate to new job detail
[continues as Job Creation flow]
```

---

### 24.6 SSE Reconnection and Event Replay

```
React UI -> SSEStream: GET /api/events?job_id={id}
SSEStream --> React UI: [stream opens]
React UI -> React UI: Track last_event_id from each "id:" field

note: Network interruption
React UI -> React UI: SSE connection closed
React UI -> React UI: Wait 1s (exponential backoff)
React UI -> SSEStream: GET /api/events?job_id={id}
                       Header: Last-Event-ID: {last_event_id}
SSEStream -> Persistence: EventRepository.list_after(last_event_id, job_id)
Persistence --> SSEStream: [missed events]
SSEStream --> React UI: [replay missed events in order]
SSEStream --> React UI: [continue live stream]
React UI -> React UI: Apply replayed events to store (idempotent)
React UI -> React UI: UI updated to current state
```

---

### 24.7 Voice Input Transcription Flow

```
Operator -> React UI: Press and hold microphone button
React UI -> Browser: getUserMedia({ audio: true })
Browser --> React UI: MediaStream
React UI -> Browser: new MediaRecorder(stream)
React UI -> Browser: recorder.start()

loop [while button held]
    Browser --> React UI: ondataavailable(chunk)
    React UI -> React UI: chunks.push(chunk)
end

Operator -> React UI: Release microphone button
React UI -> Browser: recorder.stop()
React UI -> React UI: blob = new Blob(chunks, { type: "audio/webm" })
React UI -> FastAPI: POST /api/voice/transcribe (multipart: audio=blob)
FastAPI -> VoiceService: transcribe(audio_bytes)
VoiceService -> faster-whisper: model.transcribe(audio_bytes)
faster-whisper --> VoiceService: segments
VoiceService --> FastAPI: "Fix the null pointer in UserService"
FastAPI --> React UI: 200 { text: "Fix the null pointer in UserService" }
React UI -> React UI: Insert text into prompt/message input
```

---

## 25. Ross Review: Perceived Gaps and Brainstorming Needed

This section documents areas that require clarification, validation, or deeper design before implementation begins.

---

### 25.1 Copilot SDK Assumptions

**Gap:** The specification assumes the Python Copilot SDK supports:
- Async event streaming
- Mid-session operator message injection
- Session cancellation
- Approval-pause/resume lifecycle

**Action needed:** Validate these capabilities against the actual SDK API. The adapter interface in Section 4.4 should be treated as aspirational until confirmed. If the SDK does not support async streaming natively, the adapter must wrap blocking calls in a thread pool executor.

**Gap:** The approval-pause mechanism assumes the SDK can hold a pending action and wait for an external signal. It is unclear whether this is modeled as a callback, a blocking call, or a polling check.

---

### 25.2 Runtime Failure Scenarios

**Gap:** The specification does not fully define behavior for:
- What happens if the FastAPI process crashes mid-job
- What happens if `git worktree add` fails (disk full, permissions)
- What happens if the Copilot SDK session silently stalls (no events, no heartbeat)

**Action needed:** Define a recovery policy for each failure scenario. The heartbeat watchdog in Section 21.4 partially addresses stalls, but the threshold and recovery action (auto-cancel vs. alert) need decision.

---

### 25.3 Restart Recovery Strategy

**Gap:** When the backend process restarts, jobs that were `running` at shutdown are left in an inconsistent state. The specification says "important state must be persisted" but does not specify the recovery procedure.

**Questions to resolve:**
- Should `running` jobs be auto-transitioned to `failed` on restart?
- Should the system attempt to reconnect to orphaned Copilot sessions?
- How are asyncio tasks reconstructed?

**Suggested approach:** On startup, query for jobs in `running` or `waiting_for_approval` state and transition them to `failed` with a `reason: "process_restarted"` payload. Provide an explicit rerun button. Do not attempt transparent resume in v1.

---

### 25.4 Repository Safety Guarantees

**Gap:** The specification guarantees that the base repository working tree is never modified. However:
- What prevents the Copilot agent from running `git checkout` or `git reset` commands that affect the base repo?
- What prevents a job from pushing to remote?

**Action needed:** The Git service should configure the worktree's environment to prevent accidental main-repo writes. Consider passing `--no-checkout` worktree flags and setting `remote.origin.pushurl` to a no-op in the worktree's local config.

---

### 25.5 Artifact Storage Growth

**Gap:** Artifacts accumulate indefinitely. There is no defined retention policy.

**Questions to resolve:**
- What is the maximum artifact size per job?
- Should there be a total artifact storage quota?
- How are old artifacts pruned?

**Suggested approach:** Add an `artifact_retention_days` field to global config. Run a daily cleanup job that removes artifacts and diff snapshots for jobs older than the retention period. Make this configurable with a default of 30 days.

---

### 25.6 Policy Engine Evolution

**Gap:** The approval trigger list in Section 19.2 is currently hardcoded. As teams use AgentTower, they will need custom rules.

**Questions to resolve:**
- Should protected paths be the only user-configurable trigger?
- Is there a future need for regex-based command pattern matching?
- Who owns the policy rules — the global config or the repo config?

**Suggested approach:** Keep v1 simple (protected paths + hardcoded trigger list). Design the `ApprovalService` with a pluggable trigger evaluator interface so custom rules can be added in v2 without architectural change.

---

### 25.7 UI Scalability Risks

**Gap:** The Kanban board design has no defined limit on the number of cards per column. The History column will grow unboundedly.

**Action needed:**
- History column should paginate or virtualize, showing the most recent N jobs
- Define what "recent" means (last 7 days? last 50 jobs?)
- SSE broadcasting all job events to all connected clients will not scale beyond ~20 concurrent jobs per operator session; this is acceptable for the single-developer deployment model but should be documented as a known constraint

---

### 25.8 Dev Tunnel Security

**Gap:** The specification states the Dev Tunnel URL "must be kept private" but does not define enforcement.

**Questions to resolve:**
- Is the Bearer token authentication sufficient for remote access security?
- Should the tunnel be restricted to authenticated Microsoft Dev Tunnels with identity-linked access?
- Is there a risk of the public tunnel URL being discovered or brute-forced?

**Suggested approach:** Require `auth.enabled: true` whenever the Dev Tunnel is active. Add a startup warning if the server is bound to `0.0.0.0` or a tunnel is active with auth disabled.

---

### 25.9 Voice Input Privacy

**Gap:** Voice audio is uploaded to the local backend and transcribed locally using faster-whisper. This is intentionally local-only.

**Action needed:** Document explicitly that no audio data is transmitted to external services. Confirm that faster-whisper does not phone home. Add a visual indicator in the UI that transcription is local.

---

### 25.10 Concurrent Approval Handling

**Gap:** If two jobs are simultaneously in `waiting_for_approval` state, the UI must clearly distinguish which approval belongs to which job.

**Action needed:**
- The Sign-off Kanban column addresses this at the dashboard level
- On mobile, if the operator navigates away from a Job Detail screen while an approval is pending, ensure a persistent notification is shown
- Define behavior if an approval request expires (e.g., operator is unreachable for > 30 minutes): timeout policy is unspecified

---

### 25.11 Branch Cleanup and PR Integration

**Gap:** The specification describes branch creation but not what happens to branches after a job succeeds.

**Questions to resolve:**
- Should AgentTower offer to open a pull request after a successful job?
- Should completed branches be auto-deleted after merge?
- Is GitHub/GitLab integration in scope?

**Suggested approach:** Keep v1 focused on local execution and observation. Leave PR creation and remote integration as explicit future features. The branch remains on disk for the operator to push manually.
