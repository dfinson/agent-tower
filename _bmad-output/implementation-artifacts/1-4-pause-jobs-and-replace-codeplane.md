# Story 1.4: Pause Jobs and Replace CodePlane

Status: review

## Story

As a CodePlane developer,
I want the adopted helper to quiesce managed jobs and replace only the active CodePlane process,
so that self-restart proceeds without losing its coordinator or targeting unrelated processes.

## Acceptance Criteria

1. After response grace, the helper retrieves the complete running-job list before sending any pause request; retrieval failure aborts before pause or stop.
2. Every listed job receives a pause request; individual failures are logged; after the first pause request the helper always continues toward restart.
3. Stop targets only the old PID plus process creation time from the validated profile.
4. Stop completes only when that identity is absent and the configured port has no listener.
5. The helper starts exactly one replacement from the validated source with the recorded executable, working directory, host, port, dev mode, remote mode, provider, tunnel ownership, identity, and resolvable secret references.
6. The replacement receives the request nonce; child output is redirected; the helper sends no resume request.

## Tasks / Subtasks

- [x] Add response-grace and complete running-job-list retrieval.
- [x] Send and record all pause requests using existing CodePlane runtime/API behavior.
- [x] Preserve the partial-pause invariant: once pause begins, continue to replacement.
- [x] Stop only the recorded process identity and verify both identity absence and port release.
- [x] Construct one reproducible native `cpl up` launch from the profile and target source.
- [x] Pass the request nonce and redirect replacement output.
- [x] Add tests for list failure, individual pause failures, wrong PID, PID reuse, bound port, duplicate start, and no resume calls.

## Dev Notes

- Reuse existing pause and stop behavior; do not create a second job-state machine.
- Process-name scans are never ownership evidence.
- The helper is in a different process group/session and must not be included in listener shutdown.
- Existing `RuntimeService.recover_on_startup()` remains authoritative.
- Plan-mode `waiting_for_approval` recovery behavior remains unchanged.
- Expected files: `tools/dev_restart.py`, existing runtime client/service integration as needed, and focused tests.

### References

- [Source: `_bmad-output/planning-artifacts/epics.md#Story-14-Pause-Jobs-and-Replace-CodePlane`]
- [Source: `_bmad-output/specs/spec-codeplane-developer-restart/SPEC.md#CAP-4`]
- [Source: `_bmad-output/planning-artifacts/architecture/architecture-codeplane-self-restart-2026-08-07/ARCHITECTURE-SPINE.md#AD-7-Detach-before-pausing-any-job`]

## Dev Agent Record

### Agent Model Used

Claude Sonnet 5 (GitHub Copilot CLI), Stories 1.3-1.4 sibling session, integrated by the integration-owner session.

### Debug Log References

- `uv run pytest backend/tests/unit/test_restart_helper.py -q` -> 68 passed
- Post-review fixes: `uv run pytest backend/tests/unit/test_restart_helper.py -q` -> 41 passed (full-fresh module count after new regression tests added); combined suite -> 276 passed

### Completion Notes List

- Comprehensive developer guide generated.
- `_list_running_jobs()` retrieves the complete paginated running-job list before any pause is sent, raising `HelperAbort` on retrieval failure (AC1). `_pause_jobs()` sends a pause request per job and records individual failures without aborting (AC2/AD-7 partial-pause invariant); a malformed job record (missing or non-string `id`) is validated with `isinstance` inside the per-job loop, logged, and skipped rather than raised, so one bad record can never abort the batch after some jobs are already paused (fixed post-review: an earlier revision used direct `job["id"]` indexing outside the per-job guard, which would raise `KeyError` uncaught and strand the remaining jobs unpaused, violating AD-7's continue-always guarantee).
- `_stop_old_process()` stops only the recorded PID/creation-time identity and verifies both identity absence and port release (AC3/AC4), using the canonical `is_identity_alive()` helper (0.01s creation-time tolerance) before every `terminate()`/`kill()` call, instead of an inline `< 1.0s` tolerance that risked signaling an unrelated process if the old PID were reused within a second (fixed post-review; regression test `test_uses_canonical_tight_tolerance_not_a_loose_one` proves a 0.5s-later reused PID is never signaled).
- `_start_replacement()` launches exactly one `python -m backend.main up` replacement from the validated target source with the recorded executable/host/port/dev/remote/provider/tunnel-name/tunnel-ownership, the request nonce via `CODEPLANE_RESTART_NONCE`, and the request id via `CODEPLANE_RESTART_REQUEST_ID`; never calls `/resume` (AC5/AC6). `--tunnel-ownership` is now replayed exactly from `profile.tunnel_ownership` (fixed post-review: it was previously omitted from the replacement argv, so a restarted external tunnel would fall back to `cli.py`'s legacy auto-detect/process-scan path instead of resolving the exact recorded origin).

### File List

- `backend/services/dev_restart/restart_helper.py`
- `backend/tests/unit/test_restart_helper.py`