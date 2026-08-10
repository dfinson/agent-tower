# Story 1.5: Prove Recovery and Local Readiness

Status: ready-for-dev

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

- [ ] Define the secret-free launch nonce transport from helper to replacement.
- [ ] Integrate restart-specific readiness publication into `backend/lifespan.py` after existing recovery and deferred remote checks.
- [ ] Atomically write the matching ready marker with replacement PID.
- [ ] Add helper-side marker correlation and listener-owner validation.
- [ ] Detect child exit and enforce readiness timeout.
- [ ] Log reproducible manual-recovery diagnostics.
- [ ] Add normal-startup, recovery-order, stale-marker, wrong-owner, timeout, and no-resume regression tests.

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

To be completed by the dev agent.

### Debug Log References

### Completion Notes List

- Comprehensive developer guide generated.

### File List
