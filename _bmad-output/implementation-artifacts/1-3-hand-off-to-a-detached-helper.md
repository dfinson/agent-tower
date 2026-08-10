# Story 1.3: Hand Off to a Detached Helper

Status: review

## Story

As a CodePlane developer or managed agent,
I want the restart request adopted by an independent native helper,
so that restart continues after both the initiator and supervising server are interrupted.

## Acceptance Criteria

1. Parent mode opens the absolute restart log once and spawns private `--helper <request-path>` mode with stdout and stderr bound to that handle.
2. POSIX uses `start_new_session=True`; Windows uses `DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP`; stdin is detached and no unintended handles are inherited.
3. The helper writes `spawned`, acquires `restart.lock` using `O_CREAT | O_EXCL`, records exact helper identity, renames the exact pending request to claimed, and creates the matching started marker.
4. A live lock rejects concurrency; a stale lock is removed only when its PID plus creation-time identity is absent.
5. Spawn or adoption failure exits parent mode nonzero while the current server remains running.
6. Parent success requires the exact claimed request and started marker and reports only helper adoption plus the absolute log path.

## Tasks / Subtasks

- [x] Add private helper-mode parsing and exact request-path consumption.
- [x] Implement `_spawn_detached_helper()` with native POSIX and Windows branches.
- [x] Pass only the explicit log handle and detach stdin.
- [x] Implement create-exclusive lock acquisition and PID-plus-creation-time stale-lock checks.
- [x] Implement pending-to-claimed atomic rename and exact started marker.
- [x] Make parent adoption wait bounded and request-specific.
- [x] Add platform-focused spawn, lock, mismatch, timeout, and server-preservation tests.

## Dev Notes

- The parent must not pause itself before helper adoption.
- The helper must never discover or execute abandoned requests by scanning a directory.
- Use the same absolute log handle across parent and helper. Do not recompute the path in helper mode.
- Parent success means adoption, not restart completion.
- Do not implement pause, stop, start, readiness, or remote probing in this story.
- Expected primary file: `tools/dev_restart.py`; tests belong in `backend/tests/unit/test_dev_restart.py` plus native process-level coverage where supported.

### References

- [Source: `_bmad-output/planning-artifacts/epics.md#Story-13-Hand-Off-to-a-Detached-Helper`]
- [Source: `_bmad-output/planning-artifacts/architecture/architecture-codeplane-self-restart-2026-08-07/ARCHITECTURE-SPINE.md#AD-1-The-helper-survives-the-processes-it-restarts`]
- [Source: `_bmad-output/planning-artifacts/architecture/architecture-codeplane-self-restart-2026-08-07/ARCHITECTURE-SPINE.md#AD-3-Adoption-is-the-only-acceptance-boundary`]

## Dev Agent Record

### Agent Model Used

Claude Sonnet 5 (GitHub Copilot CLI), Stories 1.3-1.4 sibling session, integrated by the integration-owner session.

### Debug Log References

- `uv run pytest backend/tests/unit/test_restart_helper.py -q` -> 68 passed (including native survival + CHECKING_REMOTE wiring)
- `uv run ruff check backend/services/dev_restart/restart_helper.py backend/tests/unit/test_restart_helper.py` -> All checks passed

### Completion Notes List

- Comprehensive developer guide generated.
- `backend/services/dev_restart/restart_helper.py` implements `spawn_detached_helper()` (POSIX `start_new_session=True`; Windows `DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP`, stdin detached, stdout/stderr bound to the single inherited log handle), `await_adoption()` (bounded, request-specific), and the helper-side `run_helper()`/`_run_claimed()`/`_claim_request()` sequence: create-exclusive `restart.lock` via `acquire_restart_lock()`, PID-plus-creation-time stale-lock detection (`is_identity_alive()`), atomic pending->claimed rename, and the started marker.
- Adds a native process-level test (`TestSpawnDetachedHelperNativeSurvival`) that spawns a real detached grandchild process via a subprocess "fake parent" that exits immediately, then confirms via `psutil` that the grandchild's exact PID+creation-time identity is still alive after the spawning process has fully exited -- proving the OS-level detachment property (AD-1) rather than mocking `Popen`.
- Cherry-picked and integrated cleanly onto the shared `restart_protocol.py`/`launch_profile.py` foundation; lint issues from the initial cherry-pick were fixed by the integration owner (see commit history).

### File List

- `backend/services/dev_restart/restart_helper.py`
- `backend/tests/unit/test_restart_helper.py`
- `tools/dev_restart.py` (parent-side `spawn_detached_helper`/`await_adoption` call sites, Story 1.2)