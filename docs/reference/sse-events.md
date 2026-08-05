# SSE Events Reference

CodePlane uses Server-Sent Events (SSE) to push real-time updates to the frontend. Connect to `/api/events` to receive the event stream.

## Connection

```
GET /api/events
```

Connection filters and replay cursor:

| Input | Description |
|-------|-------------|
| `job_id` | Filter events for a specific job |
| `Last-Event-ID` header or query parameter | Resume after a storage cursor |

## Canonical Events

Canonical runtime events are TraceForge `SessionEvent` objects. Their `kind` is
an open dotted string and is unchanged across the event bus and persistence.
Kinds delivered through replay or SSE retain that same envelope and dotted
value. CodePlane's currently emitted kinds include:

| Family | Representative kinds |
|--------|----------------------|
| Job lifecycle | `job.created`, `job.state_changed`, `job.review`, `job.completed`, `job.failed`, `job.canceled` |
| Permissions | `permission.requested`, `permission.resolved`, `permission.batch.requested`, `permission.batch.resolved` |
| Transcript and tools | `message.user`, `message.assistant`, `message.delta`, `tool.call.started`, `tool.call.completed` |
| Data and telemetry | `log`, `diff.updated`, `telemetry.updated`, `turn.summary` |
| Session and merge | `session.heartbeat`, `session.resumed`, `merge.completed`, `merge.conflict` |

This table is illustrative, not a closed kind registry. The SSE broadcast
allowlist in `backend/services/events/sse_manager.py` determines which
canonical kinds reach clients.

## Event Format

Each canonical event frame follows the standard SSE format:

```
id: 42
event: message.assistant
data: {"id":"evt-1","session_id":"job-1","timestamp":"2026-08-05T15:00:00Z","kind":"message.assistant","payload":{"content":"Analyzing the codebase..."},"metadata":{"sequence":7}}
```

The `event:` value is the unchanged dotted `SessionEvent.kind`. The `data:`
value is the complete TraceForge envelope serialized as-is: `id`,
`session_id`, `timestamp`, `kind`, `payload`, and `metadata`. The SSE `id:` is
the storage cursor used for reconnection; it is not substituted into the
canonical envelope.

## Reconnection

The client supplies `Last-Event-ID` as a header or query parameter. The server
reads up to 501 events after that cursor to detect overflow and replays at most
500 events. If that batch overflows or its oldest event is more than five
minutes old, the server first sends an unnumbered `snapshot` frame, removes
events outside the five-minute window, and then sends the eligible canonical
events from the bounded batch. `snapshot` is transport state, not a canonical
`SessionEvent`.

## Transport Keepalive

On connection, the endpoint immediately sends:

```
event: session_heartbeat
data: {}
```

It sends the same frame whenever the event queue remains idle for five seconds.
This frame has no `id:` and is transport-only: it is not a TraceForge envelope,
is not persisted, and is not replayed.

The underscore name `session_heartbeat` is therefore only the existing SSE
keepalive framing token. It must not be confused with canonical dotted
`session.heartbeat`, which is a full domain `SessionEvent` and follows normal
persistence and replay rules. It is allowlisted for SSE, but global/dashboard
connections suppress it when more than 20 jobs are active; job-scoped
connections continue to receive it.
