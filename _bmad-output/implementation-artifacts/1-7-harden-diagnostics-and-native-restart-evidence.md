# Story 1.7: Harden Diagnostics and Native Restart Evidence

Status: ready-for-dev

## Story

As a CodePlane maintainer,
I want bounded, secret-free diagnostics and cross-platform restart evidence,
so that the developer-only feature is supportable without product infrastructure.

## Acceptance Criteria

1. Helper phases are limited to `spawned`, `pausing`, `stopping`, `starting`, `checking_health`, `checking_remote`, `succeeded`, and `failed`, with required structured fields and redacted errors.
2. Defaults are adoption 5s, response grace 2s, pause wait 10s, stop 15s, readiness 60s, and remote probe 30s; all are CLI-overridable and logged.
3. Restart logging rotates at 5 MiB with exactly one backup while preserving helper output.
4. Success safely removes request markers and lock; failed claimed requests and markers remain until explicit cleanup; abandoned requests are never auto-executed.
5. Profiles, requests, locks, markers, logs, errors, and recovery commands expose no secrets or full environment.
6. Native Windows and POSIX process tests prove helper/log survival after initiator, managed-agent, and listener process-group termination.
7. The final change adds no product API, frontend control, database migration, daemon, gateway, supervisor, service manager, deployment generation, or rollback.

## Tasks / Subtasks

- [ ] Centralize canonical phase logging and structured redaction.
- [ ] Expose and log all documented timeout overrides.
- [ ] Configure 5 MiB rotation with one backup without breaking the inherited helper handle.
- [ ] Implement safe success cleanup and failure retention.
- [ ] Add explicit diagnostic cleanup support without startup execution scans.
- [ ] Add secret-leak tests over every persisted and logged artifact.
- [ ] Add native POSIX and Windows process-level survival tests.
- [ ] Run focused backend tests, CLI tests, process tests, and regression coverage for the complete feature.
- [ ] Verify final diff contains none of the explicitly excluded infrastructure.

## Dev Notes

- This story hardens and proves behavior introduced by Stories 1.1 through 1.6; do not redesign their protocol.
- Diagnostic files are evidence, not an application lifecycle database.
- Failure must remain nonzero and reproducible; no success-shaped fallback.
- Platform branching is limited to native detachment and PID handling.
- Tests must target exact process identity, not executable names.
- Expected files: `tools/dev_restart.py`, restart/CLI/lifespan tests, and native process-test support following repository conventions.

### References

- [Source: `_bmad-output/planning-artifacts/epics.md#Story-17-Harden-Diagnostics-and-Native-Restart-Evidence`]
- [Source: `_bmad-output/specs/spec-codeplane-developer-restart/SPEC.md#CAP-7`]
- [Source: `_bmad-output/planning-artifacts/architecture/architecture-codeplane-self-restart-2026-08-07/ARCHITECTURE-SPINE.md#AD-12-Evidence-stays-local-and-secret-free`]

## Dev Agent Record

### Agent Model Used

To be completed by the dev agent.

### Debug Log References

### Completion Notes List

- Comprehensive developer guide generated.

### File List
