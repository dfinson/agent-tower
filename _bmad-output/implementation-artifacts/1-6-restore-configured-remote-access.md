# Story 1.6: Restore Configured Remote Access

Status: review

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

- [x] Preserve managed versus external tunnel ownership in launch/restart arguments.
- [x] Reuse exact Dev Tunnel or Cloudflare identity where supported.
- [x] Prevent broad connector process reuse or process scans from becoming ownership evidence.
- [x] Add reusable-origin and changed-origin handling.
- [x] Add bounded exact-origin remote probing after local readiness.
- [x] Distinguish local success from remote validation failure in logs and exit behavior.
- [x] Add managed, external, reusable, non-reusable, credential, and redaction tests.

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

Claude Sonnet 5 (GitHub Copilot CLI), Stories 1.5-1.6 sibling session, integrated by the integration-owner session.

### Debug Log References

- `uv run pytest backend/tests/unit/test_tunnel_service.py backend/tests/unit/test_restart_remote.py backend/tests/unit/test_restart_helper.py -q` -> combined pass (part of the 269-test combined suite)
- `uv run ruff check backend/services/sharing/tunnel_service.py backend/services/dev_restart/restart_remote.py` -> All checks passed

### Completion Notes List

- Comprehensive developer guide generated.
- `TunnelOwnership` enum (`external`/`managed`) is an explicit opt-in on `start_remote_access()`; `external` resolves only the exact recorded hostname/tunnel name and never starts a connector or scans local processes (AC1/AC2); `managed` always starts and owns a fresh connector.
- `TunnelHandle.origin_is_reusable` records whether the resolved origin is stable across a restart; published into `LaunchProfile.tunnel_origin_reusable` by `cli.py` (coordinated with the integration owner's `TunnelHandle.name` field, both populated together).
- New `backend/services/dev_restart/restart_remote.py`: `RemoteProbeTarget`/`RemoteProbeError`, `resolve_remote_probe_target()` (reusable origin uses the original; non-reusable uses the replacement's and reports whether it changed), `probe_remote_origin()` (bounded exact-origin reachability probe, never scans processes).
- `restart_helper.py`'s `checking_remote` phase wires these: after local readiness, a remote profile probes the resolved origin, raising `HelperAbort` on failure distinct from local `succeeded` (AC3-AC5).

### File List

- `backend/services/sharing/tunnel_service.py`
- `backend/services/dev_restart/restart_remote.py`
- `backend/tests/unit/test_tunnel_service.py`
- `backend/tests/unit/test_restart_remote.py`
- `backend/services/dev_restart/restart_helper.py` (`checking_remote` wiring)
- `backend/cli.py` (`tunnel_origin`/`tunnel_origin_reusable` publication, Story 1.1 integration)