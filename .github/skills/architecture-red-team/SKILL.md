---
name: architecture-red-team
description: >
  Deep red-team audit of CodePlane's 5 core backend subsystems. Finds non-obvious
  failure modes, race conditions, resource leaks, data corruption risks, and
  missing error handling. Produces fixes with tests.
---

# Architecture Red-Team Skill

Systematically red-team 5 core CodePlane subsystems. For each: read code → find
bugs → fix → verify. Track all findings in session memory.

## Subsystems & Key Files

### 1. Job State Machine
| File | Lines | Role |
|------|-------|------|
| `backend/models/domain.py` | ~225 | `JobState` enum, `_VALID_TRANSITIONS`, `validate_state_transition()` |
| `backend/services/job_service.py` | — | `JobService.transition_state()` — mutation entry point |
| `backend/persistence/job_repo.py` | — | `JobRepository.reset_for_resume()`, `restore_after_failed_resume()` |
| `backend/services/runtime_service.py` | ~1700 | Orchestrates lifecycle: start, pause, resume, cancel, cleanup |

**Attack surface:**
- Race between concurrent state transitions (two resume calls, cancel during approval)
- `_cleanup_job_state` partial failures leaving orphaned in-memory state
- `_ensure_terminal_state` vs `recover_on_startup` interaction on restart
- Stuck jobs: what if `_dequeue_next` throws? Queued jobs never start
- `_pending_starts` / `_queued_override_prompts` memory growth if dequeue fails

### 2. SSE Event Streaming
| File | Lines | Role |
|------|-------|------|
| `backend/services/sse_manager.py` | ~900 | `SSEManager`, `SSEConnection`, event replay, backpressure |
| `backend/api/events.py` | ~70 | `/events` SSE endpoint |
| `backend/services/event_bus.py` | ~56 | `EventBus.publish()` — fans out via `asyncio.gather` |
| `backend/models/events.py` | ~400 | `DomainEventKind` enum, event payloads |

**Attack surface:**
- Replay buffer unbounded? (should be capped at 500 events / 5 min)
- `asyncio.gather` in EventBus: one slow subscriber blocks all?
- Queue full → connection closed: does client always reconnect cleanly?
- High-frequency suppression (>20 jobs): are critical events ever suppressed?
- Race: event published between disconnect and reconnect — is replay window sufficient?
- Memory: do closed SSEConnection objects get cleaned up promptly?

### 3. Approval Flow
| File | Lines | Role |
|------|-------|------|
| `backend/services/approval_service.py` | ~200 | Request/resolve lifecycle, trust grants |
| `backend/persistence/approval_repo.py` | — | DB access |
| `backend/api/approvals.py` | ~80 | REST routes |
| `backend/models/domain.py` | — | `PermissionMode` enum |

**Attack surface:**
- Double-resolve: what prevents resolving an already-resolved approval?
- `wait_for_resolution()` timeout: does it hang forever if UI never responds?
- `trust_job()` + concurrent approval: race between trust grant and resolution
- `recover_pending_approvals()` on startup: are these re-presented to the UI?
- Approval for a canceled/failed job: does resolution still unblock the agent?
- `cleanup_job()` while `wait_for_resolution()` is blocking: deadlock?

### 4. Agent Adapter Layer
| File | Lines | Role |
|------|-------|------|
| `backend/services/agent_adapter.py` | ~160 | `AgentAdapterInterface` abstract contract |
| `backend/services/claude_adapter.py` | — | Claude SDK subprocess wrapper |
| `backend/services/copilot_adapter.py` | — | Copilot SDK wrapper |
| `backend/services/base_adapter.py` | — | Shared utilities |
| `backend/services/adapter_registry.py` | — | Factory/registry |

**Attack surface:**
- Subprocess zombie: adapter starts process, never collects exit code
- `stream_events()` generator: what if iteration is abandoned (job canceled)?
- `abort_session()` SIGTERM→SIGKILL escalation: is there a timeout?
- `send_message()` to a dead process: error propagation?
- `complete()` for sister sessions: does timeout actually work on subprocess?
- Resource cleanup: are file descriptors / pipes closed on error paths?
- Session ID reuse: can a stale session_id alias a new session?

### 5. Cost Analytics / Telemetry
| File | Lines | Role |
|------|-------|------|
| `backend/services/telemetry.py` | ~150 | OTEL setup, span start/end |
| `backend/services/cost_attribution.py` | ~300 | Post-job cost breakdown |
| `backend/persistence/telemetry_spans_repo.py` | — | Span storage |
| `backend/persistence/telemetry_summary_repo.py` | — | Summary storage |
| `backend/persistence/cost_attribution_repo.py` | — | Attribution storage |
| `backend/api/analytics.py` | — | Analytics endpoints |

**Attack surface:**
- `end_job_span()` never called: span leak, cost never attributed
- Token counts from different SDKs: normalization consistent?
- Division by zero in cost computation (zero spans, zero tokens)
- DB write failure during attribution: partial data left behind?
- Memory reader fallback vs OTLP: do metrics match?
- Concurrent jobs: are spans correctly isolated by job_id?

## Workflow

For each subsystem:

1. **Read** — Read all key files fully. Don't skim.
2. **Audit** — For each attack surface item, trace the code path. Confirm or refute.
3. **Record** — Add confirmed findings to session memory with severity and location.
4. **Fix** — Implement fixes for Critical and High findings.
5. **Verify** — Run relevant tests. Write new tests if the fix isn't covered.
6. **Commit** — One commit per subsystem: `fix: harden <subsystem> — N findings`

After all 5 subsystems: push and deploy.

## Severity Guide

| Level | Criteria | Action |
|-------|----------|--------|
| Critical | Data loss, job stuck permanently, crash loop | Fix immediately |
| High | Incorrect data, resource leak, silent failure | Fix in this pass |
| Medium | Degraded performance, missing validation | Fix if straightforward |
| Low | Code smell, minor inconsistency | Note for later |

## Session Memory Template

After each subsystem audit, update `/memories/session/red-team-findings.md`:

```
## <Subsystem Name>
### Critical
- [ ] Finding description (file:line) — STATUS

### High
- [ ] Finding description (file:line) — STATUS

### Medium
- [ ] ...
```

## Test Commands
```bash
# Backend unit tests (relevant subset)
uv run pytest backend/tests/unit/test_runtime_service.py -x -q
uv run pytest backend/tests/unit/test_api_jobs.py -x -q
uv run pytest backend/tests/unit/ -x -q --deselect backend/tests/unit/test_runtime_service.py::TestResumeFallback::test_resume_falls_back_to_handoff_when_native_resume_errors_immediately

# Frontend build check
cd frontend && npx vite build 2>&1 | tail -5
```

## Pre-existing Known Issues
- `test_resume_falls_back_to_handoff_when_native_resume_errors_immediately` — flaky race condition, pre-existing, skip in test runs
