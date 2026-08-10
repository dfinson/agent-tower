# Story 1.5: Prove Recovery and Local Readiness

Status: review

## Story

As a CodePlane developer,
I want restart completion based on recovered-process identity rather than port reachability alone,
so that I can trust that the intended replacement is ready.

## Acceptance Criteria

1. A request-specific launch nonce associates replacement startup with the restart request without creating general orchestration state.
2. No ready marker is published before existing startup recovery completes.
3. After recovery and deferred remote validation, startup atomically writes `<id>.ready.json` with request correlation and the replacement PID.
4. Local success requires the matching marker PID to own the configured listener; stale markers, unrelated PIDs, child exit, and timeout fail.
5. Existing plan-mode approval failure semantics and startup recovery remain unchanged; no duplicate resume occurs.
6. Post-stop startup or readiness failure logs a reproducible launch command and process, port, marker, and exit diagnostics without rollback.

## Tasks / Subtasks

- [x] Define the secret-free launch nonce transport from helper to replacement.
- [x] Integrate restart-specific readiness publication into `backend/lifespan.py` after existing recovery and deferred remote checks.
- [x] Atomically write the matching ready marker with replacement PID.
- [x] Add helper-side marker correlation and listener-owner validation.
- [x] Detect child exit and enforce readiness timeout.
- [x] Log reproducible manual-recovery diagnostics.
- [x] Add normal-startup, recovery-order, stale-marker, wrong-owner, timeout, and no-resume regression tests.

## Dev Notes

- An open port or successful HTTP probe alone is insufficient.
- Normal startup without a restart nonce must remain unchanged.
- Keep request marker files as local diagnostic evidence, not database or domain-event state.
- The helper does not repair or reinterpret startup recovery outcomes.
- Expected files: `backend/lifespan.py`, `tools/dev_restart.py`, and relevant lifespan/restart tests.

### References

- [Source: `_bmad-output/planning-artifacts/epics.md#Story-15-Prove-Recovery-and-Local-Readiness`]
- [Source: `_bmad-output/specs/spec-codeplane-developer-restart/SPEC.md#CAP-5`]
- [Source: `_bmad-output/planning-artifacts/architecture/architecture-codeplane-self-restart-2026-08-07/ARCHITECTURE-SPINE.md#AD-4-Helper-phases-are-bounded-diagnostics`]

## Dev Agent Record

### Agent Model Used

Claude Sonnet 5 (GitHub Copilot CLI), Stories 1.5-1.6 sibling session, integrated by the integration-owner session.

### Debug Log References

- `uv run pytest backend/tests/unit/test_lifespan.py backend/tests/unit/test_restart_helper.py -q` -> combined pass (part of the 269-test combined suite)

### Completion Notes List

- Comprehensive developer guide generated.
- `backend/lifespan.py` reads `CODEPLANE_RESTART_REQUEST_ID` (set by the helper on the replacement's env, absent on every normal `cpl up` startup so normal startup is unchanged) and `_publish_restart_readiness()` awaits existing startup recovery plus deferred remote validation before atomically writing `<id>.ready.json` ({requestId, pid, writtenAt}) via the shared `restart_protocol` helpers -- never duplicating marker-path/JSON logic.
- Helper's `_wait_for_ready()` requires the marker's `requestId` and `pid` to match, then re-loads the freshly published active launch profile and requires `profile_owns_listener()` -- recovered-process identity, not port reachability alone (AD-4). Child exit or timeout raise `HelperAbort`.
- If recovery or the deferred remote check fails/cancels, the failure is logged and re-raised; the marker is never written on that path.

### File List

- `backend/lifespan.py`
- `backend/tests/unit/test_lifespan.py`
- `backend/services/dev_restart/restart_helper.py` (`_wait_for_ready`, nonce transport)