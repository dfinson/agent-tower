# Story 1.6: Restore Configured Remote Access

Status: ready-for-dev

## Story

As a remotely connected CodePlane developer,
I want restart to restore the configured tunnel behavior,
so that I can reconnect after the expected temporary interruption.

## Acceptance Criteria

1. Managed tunnel mode launches the exact recorded provider identity and owns the resulting connector.
2. External tunnel mode starts no connector, performs no process scan, and probes the exact configured hostname.
3. Reusable tunnel identities are probed at the recorded origin after local readiness.
4. For non-reusable identities, parent mode warns that origin may change; the replacement profile publishes the new origin; helper logs and probes it.
5. Remote failure is distinguished from local readiness and logs redacted provider, ownership, origin, and diagnostic details.
6. Temporary MCP, SSE, WebSocket, browser, and tunnel disconnection remains expected; users reconnect manually.

## Tasks / Subtasks

- [ ] Preserve managed versus external tunnel ownership in launch/restart arguments.
- [ ] Reuse exact Dev Tunnel or Cloudflare identity where supported.
- [ ] Prevent broad connector process reuse or process scans from becoming ownership evidence.
- [ ] Add reusable-origin and changed-origin handling.
- [ ] Add bounded exact-origin remote probing after local readiness.
- [ ] Distinguish local success from remote validation failure in logs and exit behavior.
- [ ] Add managed, external, reusable, non-reusable, credential, and redaction tests.

## Dev Notes

- Reuse `backend/services/sharing/tunnel_service.py`; do not create a second tunnel manager.
- `managed` means the replacement starts and owns the connector.
- `external` means CodePlane never scans for or controls the connector.
- Remote continuity is best effort, not an availability guarantee.
- No remote progress endpoint or stable gateway is in scope.
- Expected files: `tools/dev_restart.py`, `backend/cli.py`, tunnel service only where exact ownership needs correction, and tests.

### References

- [Source: `_bmad-output/planning-artifacts/epics.md#Story-16-Restore-Configured-Remote-Access`]
- [Source: `_bmad-output/specs/spec-codeplane-developer-restart/SPEC.md#CAP-6`]
- [Source: `_bmad-output/planning-artifacts/architecture/architecture-codeplane-self-restart-2026-08-07/ARCHITECTURE-SPINE.md#AD-8-Stable-remote-origin-is-best-effort`]

## Dev Agent Record

### Agent Model Used

To be completed by the dev agent.

### Debug Log References

### Completion Notes List

- Comprehensive developer guide generated.

### File List
