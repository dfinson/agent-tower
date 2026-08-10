# Story 1.2: Prepare Restart Without Outage

Status: ready-for-dev

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

- [ ] Add parent-mode argument parsing and native target-source resolution to `tools/dev_restart.py`.
- [ ] Load and validate the Story 1.1 active profile before any build or process action.
- [ ] Re-resolve required secret references without serializing their values.
- [ ] Build the target frontend while the current server remains available.
- [ ] Run backend compile/import preflight with the recorded executable and target working directory.
- [ ] Atomically write the pending request with documented default and CLI-overridden timeouts.
- [ ] Add ordering and failure tests proving no pause or stop occurs during preparation.

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

To be completed by the dev agent.

### Debug Log References

### Completion Notes List

- Comprehensive developer guide generated.

### File List
