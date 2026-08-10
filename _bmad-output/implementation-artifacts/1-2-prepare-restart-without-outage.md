# Story 1.2: Prepare Restart Without Outage

Status: review

## Story

As a CodePlane developer,
I want restart preparation to finish while the current server remains available,
so that invalid code or configuration cannot cause an avoidable outage.

## Acceptance Criteria

1. `--source` resolves to an absolute native CodePlane source, defaulting to the repository containing the invoked `tools/dev_restart.py`.
2. The target frontend builds before helper spawn, pause, or stop.
3. The recorded active executable runs `compileall` over `backend` and `tools`, then imports `backend.app_factory` from the target source without dependency synchronization or runtime mutation.
4. Remote restart validates every required secret source and stable tunnel identity; malformed, unresolved, or `unreplayable` required sources fail before outage.
5. Successful preparation atomically writes a secret-free `<id>.pending.json` containing the request ID, validated source, launch profile, and phase timeouts.
6. Every profile, source, credential, build, preflight, or request-write failure exits nonzero without sending pause or stop and leaves the listener available.

## Tasks / Subtasks

- [x] Add parent-mode argument parsing and native target-source resolution to `tools/dev_restart.py`.
- [x] Load and validate the Story 1.1 active profile before any build or process action.
- [x] Re-resolve required secret references without serializing their values.
- [x] Build the target frontend while the current server remains available.
- [x] Run backend compile/import preflight with the recorded executable and target working directory.
- [x] Atomically write the pending request with documented default and CLI-overridden timeouts.
- [x] Add ordering and failure tests proving no pause or stop occurs during preparation.

## Dev Notes

- Preserve strict ordering: profile/source/secret validation, frontend build, backend preflight, request write, then helper spawn.
- Use `uv` only for development commands. The preflight subprocess itself uses the recorded executable directly and does not run `uv sync`.
- Validate the target as a CodePlane checkout before invoking commands.
- Keep request data secret-free. Store source references only.
- Preparation does not pause jobs, stop the server, detach a helper, or perform recovery.
- Expected files: `tools/dev_restart.py`, `backend/tests/unit/test_dev_restart.py`, and the reusable launch-profile helper from Story 1.1.

### References

- [Source: `_bmad-output/planning-artifacts/epics.md#Story-12-Prepare-Restart-Without-Outage`]
- [Source: `_bmad-output/specs/spec-codeplane-developer-restart/SPEC.md#Constraints`]
- [Source: `_bmad-output/planning-artifacts/architecture/architecture-codeplane-self-restart-2026-08-07/SOLUTION-DESIGN.md#Parent-Mode`]

## Dev Agent Record

### Agent Model Used

Claude Sonnet 5 (GitHub Copilot CLI), integration-owner session.

### Debug Log References

- `uv run pytest backend/tests/unit/test_dev_restart.py -q` -> 29 passed
- `uv run pytest backend/tests/unit/test_dev_restart.py backend/tests/unit/test_restart_helper.py backend/tests/unit/test_restart_protocol.py backend/tests/unit/test_launch_profile.py backend/tests/unit/test_cli.py backend/tests/unit/test_tunnel_service.py -q` -> 220 passed
- `uv run ruff check backend/tests/unit/test_dev_restart.py tools/dev_restart.py` -> All checks passed

### Completion Notes List

- Comprehensive developer guide generated.
- Rewrote `tools/dev_restart.py` parent-mode flow: `resolve_target_source_root`, `ensure_secret_resolvable`, `run_backend_preflight`, `write_pending_request`, `_resolve_timeouts`, `prepare_restart_request`, and `run_parent` implement AC1-AC6 in the strict order profile/secret validation -> frontend build -> backend preflight -> atomic pending write -> helper spawn, with any failure aborting before pause/stop and leaving the listener untouched.
- Secret re-resolution (`ensure_secret_resolvable`) checks `resolvable` sources against the *target* source root's `.env`/environment or `shutil.which` for provider-login secrets; `unreplayable` required sources or failed resolution raise `DevRestartError` and abort before any build/preflight/write/spawn side effect (AC4, AD-5).
- `write_pending_request` writes the exact locked wire-contract shape (`requestId`, `targetSourceRoot`, `launchProfile`, `timeouts`, `createdAt`) via the shared `write_json_atomic`/`get_request_paths` from Story 1.1's protocol module -- no secret values are ever serialized.
- `run_parent` calls `restart_helper.spawn_detached_helper`/`await_adoption` (Story 1.3/1.4) after preparation succeeds; log rotation is deliberately out of scope (Story 1.7).
- Backward compatible: the pre-existing `build_frontend`/`_resolve_npm_command` tests (5) pass unchanged against the rewrite.

### File List

- `tools/dev_restart.py`
- `backend/tests/unit/test_dev_restart.py`
