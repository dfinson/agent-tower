# Job States Reference

Every job in CodePlane follows a state machine that governs its lifecycle.

## State Machine

```
                    ┌──────────┐
                    │  queued   │
                    └────┬─────┘
                         │ agent session starts
                         ▼
                    ┌──────────┐
              ┌─────│ running  │─────┐
              │     └────┬─────┘     │
              │          │           │
    approval  │   agent  │    error/ │
    requested │   done   │   cancel  │
              │          │           │
              ▼          ▼           ▼
    ┌─────────────┐ ┌────────┐ ┌──────────┐
    │  waiting_   │ │succeed-│ │  failed   │
    │for_approval │ │  ed    │ │          │
    └──────┬──────┘ └───┬────┘ └──────────┘
           │            │          ▲
    approve│     resolve │         │
    /reject│            ▼         │
           │     ┌──────────┐    │
           └────▶│ running  │────┘
                 └──────────┘
```

## States

| State | Description |
|-------|-------------|
| `queued` | Job created, waiting to start |
| `running` | Agent is actively executing |
| `waiting_for_approval` | Agent paused, waiting for operator to approve/reject an action |
| `succeeded` | Agent completed the task successfully |
| `failed` | Job failed due to error, cancellation, or timeout |
| `canceled` | Job was canceled by the operator |
| `resolved` | Job output was merged, PR created, or discarded |
| `paused` | Job execution paused by operator |

## Valid Transitions

| From | To | Trigger |
|------|----|---------|
| `queued` | `running` | Agent session starts |
| `running` | `waiting_for_approval` | Agent requests permission for risky action |
| `running` | `succeeded` | Agent completes task |
| `running` | `failed` | Error, timeout, or heartbeat loss |
| `running` | `canceled` | Operator cancels |
| `running` | `paused` | Operator pauses |
| `waiting_for_approval` | `running` | Operator approves |
| `waiting_for_approval` | `failed` | Operator rejects |
| `waiting_for_approval` | `canceled` | Operator cancels |
| `succeeded` | `resolved` | Operator resolves (merge/PR/discard) |
| `failed` | `queued` | Operator reruns |
| `paused` | `running` | Operator resumes |

## Restart Recovery

If the CodePlane server restarts while jobs are running:

- All `running` and `waiting_for_approval` jobs are marked as `failed`
- The failure reason is set to `"server_restart"`
- Jobs can be rerun after recovery

## Heartbeat Watchdog

The agent session emits heartbeats every 30 seconds. If a heartbeat is missed:

- **After 90 seconds:** Warning logged
- **After 5 minutes:** Job fails with reason `"heartbeat_timeout"`

## Job IDs

Jobs use sequential IDs in the format `job-{N}` (e.g., `job-1`, `job-2`, `job-3`), backed by an internal SQLite autoincrement sequence.
