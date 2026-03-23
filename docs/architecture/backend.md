# Backend Architecture

The backend is a FastAPI application structured around services, repositories, and an event bus.

## Layers

```
API Routes (thin handlers)
    │
    ▼
Services (business logic)
    │
    ▼
Repositories (database access)
    │
    ▼
SQLAlchemy + SQLite
```

### API Routes (`backend/api/`)

Route handlers are intentionally thin. They:

1. Validate input (via Pydantic schemas)
2. Delegate to a service method
3. Return the result

No orchestration logic lives in routes.

### Services (`backend/services/`)

Services contain all business logic. Key services:

| Service | Responsibility |
|---------|---------------|
| `RuntimeService` | Job execution orchestration — the heart of CodePlane |
| `JobService` | Job CRUD operations |
| `ApprovalService` | Approval workflow management |
| `GitService` | All Git operations (clone, branch, worktree, commit) |
| `MergeService` | Branch merging, cherry-pick, PR creation |
| `DiffService` | Diff generation between branches |
| `SSEManager` | Maps domain events to SSE frames for browser delivery |
| `EventBus` | Internal publish/subscribe event bus |
| `TerminalService` | PTY-based terminal session management |
| `VoiceService` | Audio transcription via faster-whisper |
| `TelemetryCollector` | Token usage, costs, and metrics tracking |
| `PermissionPolicy` | Enforces permission modes (auto/read_only/approval_required) |
| `PlatformAdapter` | GitHub, Azure DevOps, GitLab integrations |
| `NamingService` | AI-powered job title generation |
| `TunnelService` | Dev Tunnels lifecycle management |

### Repositories (`backend/persistence/`)

All database access goes through repository classes:

| Repository | Table |
|------------|-------|
| `JobRepository` | `jobs` |
| `ApprovalRepository` | `approvals` |
| `ArtifactRepository` | `artifacts` |
| `EventRepository` | `events` |
| `MetricsRepository` | `job_metrics` |

The `Repository` base class provides common CRUD operations. Repositories never leak SQLAlchemy sessions to the service layer.

## Event System

CodePlane uses domain events for internal communication:

```
Agent SDK action
    │
    ▼
DomainEvent created (e.g., TranscriptUpdate, LogLineEmitted)
    │
    ▼
EventBus.publish() — persists event + fans out to subscribers
    │
    ▼
SSEManager — transforms domain event into SSE frame
    │
    ▼
Browser receives SSE frame → Zustand store updates → UI re-renders
```

### Domain Events

Events are defined in `backend/models/events.py`. Each event has:

- **kind** — Event type (e.g., `job_created`, `transcript_update`, `approval_requested`)
- **job_id** — Associated job
- **payload** — Event-specific data dictionary
- **db_id** — Auto-increment ID used as monotonic SSE event ID

### Event Persistence

Events are persisted to the database, enabling:

- **Reconnection replay** — Up to 500 events within 5 minutes
- **Audit trail** — Full history of everything that happened
- **SSE resume** — `Last-Event-ID` header support

## Database

SQLite in WAL mode with SQLAlchemy 2.0 async. Alembic manages migrations.

### Session Management

The FastAPI dependency provides a database session per request:

- Auto-commit on success
- Auto-rollback on exception
- No manual session management in services

## MCP Server

The MCP server (`backend/mcp/server.py`) exposes CodePlane operations as MCP tools. It runs on the same port as the main API at `/mcp`, using HTTP transport with SSE notifications.
