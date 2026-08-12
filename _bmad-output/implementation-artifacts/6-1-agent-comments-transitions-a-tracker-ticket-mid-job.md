---
baseline_commit: 25562c4d
---

# Story 6.1: Agent comments/transitions a tracker ticket mid-job

Status: review

## Story

As a developer running an agent-driven Job,
I want the agent to be able to comment on or transition the linked tracker ticket itself,
So that ticket status stays current without me doing it manually after the fact.

## Acceptance Criteria

1. **Given** an agent running inside a Job whose Project has an attached TrackerLink, **when** the agent calls `codeplane_tracker` (comment or transition), **then** CodePlane resolves the Job's Project and TrackerLink(s) server-side and creates a `codeplane_approval` entry via the exact same function CAP-11's recipe-driven `tracker_write` already calls — same approval shape regardless of caller.
2. **Given** the agent calls `codeplane_tracker`, **when** the call executes, **then** the agent never receives or handles the Credential's decrypted PAT at any point — CodePlane resolves and uses it server-side on the agent's behalf.
3. **Given** a `codeplane_tracker`-created approval is rejected, **when** I check the ticket afterward, **then** no write reaches the external tracker.

## Tasks / Subtasks

- [x] Task 1: Add a shared Job -> Project -> TrackerLink resolution helper (AC: 1)
  - [x] New `backend/services/tracker_resolution.py`: `resolve_tracker_for_job(session, job_id) -> ResolvedTracker` — looks up the Job's paired `TaskLink` via `TaskLinkRepository.get_by_job_id`, requires a non-null `tracker_ticket_ref` on it, then looks up the Project's `TrackerLink`(s) via `TrackerLinkRepository.list_for_project` and picks the first. Raises `TrackerResolutionError` (never falls back to an ambiguous default) when the Job has no TaskLink, the TaskLink has no paired ticket, or the Project has no TrackerLink attached.
  - [x] Kept intentionally minimal and additive so a future Story 4.6 (recipe-driven `tracker_write` output route) can reuse the exact same helper without this story touching `RecipeService` or the `job_completed` subscriber.
- [x] Task 2: Add the `codeplane_tracker` MCP tool (AC: 1, 2, 3)
  - [x] `backend/mcp/server.py`: new `_register_tracker_tool`, registered alongside `_register_pr_tool` (mirrors CAP-14's `codeplane_pr` pattern — thin handler, validate input, delegate to services).
  - [x] Actions: `comment` (job_id, value = comment text) and `transition` (job_id, value = target status).
  - [x] Handler resolves the TrackerLink/ticket via `resolve_tracker_for_job`, builds a `TrackerWriteRequest` (Story 3.4's provider-independent request shape), and calls the exact same `TrackerWriteService.execute(job_id, request, dispatch)` CAP-11's recipe-driven `tracker_write` route already calls — same `codeplane_approval` entry shape regardless of caller (AC #1).
  - [x] The `dispatch` callback resolves the Credential's PAT via `CredentialRepository.resolve_secret` strictly server-side, only after approval — the agent's MCP tool call never receives, returns, or logs the decrypted secret at any point (AC #2).
  - [x] `TrackerWriteService.execute` returns `False` without invoking `dispatch` when the approval is rejected, so a rejected approval never reaches the external tracker (AC #3) — this is Story 3.4's existing gate behavior, reused unchanged.
- [x] Task 3: Add focused tests (AC: 1, 2, 3)
  - [x] `backend/tests/unit/test_tracker_resolution.py` (new): resolves the TrackerLink/ticket for a Job's paired TaskLink; raises when the Job has no TaskLink; raises when the TaskLink has no paired ticket; raises when the Project has no TrackerLink attached.
  - [x] `backend/tests/unit/test_mcp_server.py`: new `TestTrackerTool` class — missing `job_id`/`value` returns an error; unresolvable Job returns an error; a `comment` call creates an approval via `TrackerWriteService`/`ApprovalService.create_request` with `requires_explicit_approval=True` and dispatches (resolving the Credential secret) only once approved; a rejected approval never dispatches (Credential secret never resolved).
  - [x] Extended `TestMCPServerCreation.test_all_tools_registered` to include `codeplane_tracker`.
  - [x] Ran targeted pytest (`test_tracker_resolution.py`, `test_mcp_server.py`) + `ruff`/`mypy` on all changed files; confirmed no regressions.

## Dev Notes

### Implementation Boundary

This story adds only: the shared `resolve_tracker_for_job` helper, the `codeplane_tracker` MCP tool, and its tests. It does NOT implement:

- Story 4.6 (route recipe tracker-writes on completion) — untouched; `RecipeService` and the `job_completed` event subscriber are unmodified. The new `tracker_resolution.py` helper is deliberately generic/reusable so 4.6 can call it later without needing to duplicate or restructure it.
- Any real per-provider tracker API client (GitHub Projects/Jira/Azure DevOps HTTP calls) — no such adapter exists anywhere in the codebase yet (Story 3.3's read-model/polling and any write-side provider client are separate, not-yet-implemented work). This story's `dispatch` callback proves the Credential's PAT is resolved and used strictly server-side (AC #2's actual requirement) without building a new provider integration surface as a side effect.
- Any frontend UI — not required by this story's ACs.
- A new alembic migration — no schema change; the story reuses `TaskLinkRow.tracker_ticket_ref` (Story 4.2), `TrackerLinkRow` (Story 3.2), and `CredentialRow.resolve_secret` (Story 3.1), all pre-existing.

### Architecture Compliance (CAP-13, AD-6, AD-9)

- CAP-13 requires `codeplane_tracker` be "a second *caller*" of CAP-11's exact same `codeplane_approval` gate, not a second write mechanism — satisfied by calling the unmodified `TrackerWriteService.execute` (Story 3.4/PR #71) directly, with no parallel approval-creation code path.
- AC #2's "agent never receives or handles the decrypted PAT" is satisfied structurally: the MCP tool handler never calls `CredentialRepository.resolve_secret` itself or returns its result; only the `dispatch` closure (invoked by `TrackerWriteService` after approval, inside the backend process) does, and its return value is discarded rather than included in the tool's JSON response.
- TrackerLink resolution never falls back to an ambiguous Project-level default ticket (matching CAP-9's TaskLink design intent) — `resolve_tracker_for_job` raises `TrackerResolutionError` rather than guessing when a Job's TaskLink has no `tracker_ticket_ref`.
- Route/tool handlers stay thin: `codeplane_tracker` validates input, resolves via the shared helper, and delegates entirely to `TrackerWriteService` — no orchestration logic in the MCP layer itself.

### Reference Implementation Pattern

- Mirror `_register_pr_tool`/`codeplane_pr` (CAP-14, Story 6.2) for the MCP tool registration shape: thin handler, `job_id` validation, delegate to an existing service, return a small JSON-serializable dict.
- Mirror `TrackerWriteService.execute` (Story 3.4, `backend/services/tracker_write_service.py`) for the approval-then-dispatch call shape — reused verbatim, not reimplemented.
- Mirror `TaskLinkRepository.get_by_job_id` (Story 4.5) and `TrackerLinkRepository.list_for_project` (Story 3.2) for the persistence reads composed into the new resolution helper.
- Mirror `CredentialRepository.resolve_secret` (Story 3.1, already documented as "exists for future tracker-adapter use") for server-side-only PAT resolution.

### Project Structure Notes

Story 3.4 (`TrackerWriteService`, PR #71, merged) and Story 6.2 (`codeplane_pr` MCP tool pattern, merged) are the two prerequisites this story builds directly on top of. No new persistence entity or migration is introduced — this story is a new MCP tool plus a small shared resolution helper wired to entirely pre-existing tables/services.

### References

- [Source: `_bmad-output/planning-artifacts/epics.md#Story-61-Agent-commentstransitions-a-tracker-ticket-mid-job`]
- [Source: `_bmad-output/specs/spec-project-boards/SPEC.md` CAP-13]
- [Source: `backend/services/tracker_write_service.py` (Story 3.4)]
- [Source: `backend/mcp/server.py::_register_pr_tool` (Story 6.2, CAP-14 pattern)]
- [Source: `backend/persistence/task_link_repo.py`, `backend/persistence/tracker_link_repo.py`, `backend/persistence/credential_repo.py`]

## Dev Agent Record

### Agent Model Used

Claude Sonnet 5 (GitHub Copilot CLI)

### Debug Log References

- Ran targeted pytest via the pre-built main-checkout venv's Python directly (`uv sync`/`uv run` could not reach PyPI from the worktree — intermittent TLS handshake failures on several packages), pointed at this worktree's source tree.
- `backend/tests/unit/test_tracker_resolution.py`: 4 passed (new).
- `backend/tests/unit/test_mcp_server.py`: 52 passed (46 pre-existing + 6 new Story 6.1 tracker-tool tests).
- `ruff check` on all changed files: clean.
- `mypy` on all changed files: no new findings (the one pre-existing `psutil` stub warning is unrelated to this story and predates it).

### Completion Notes List

- Added `backend/services/tracker_resolution.py::resolve_tracker_for_job` — a minimal, additive Job -> TaskLink -> Project -> TrackerLink resolution helper shared by (future) Story 4.6 and this story's MCP tool, without touching `RecipeService`.
- Added the `codeplane_tracker` MCP tool (`comment`/`transition` actions) in `backend/mcp/server.py`, registered via `_register_tracker_tool`, following the exact `codeplane_pr` (CAP-14) thin-handler pattern.
- The tool builds a `TrackerWriteRequest` and calls the unmodified `TrackerWriteService.execute(job_id, request, dispatch)` from Story 3.4 — identical `codeplane_approval` shape regardless of whether the caller is this MCP tool or a future recipe-driven route.
- The `dispatch` closure resolves the Credential's PAT via `CredentialRepository.resolve_secret` only after approval, strictly server-side; its result never appears in the tool's JSON response, satisfying AC #2.
- Explicitly excluded (out of scope per instructions): Story 4.6 (`RecipeService`/`job_completed` subscriber changes) — neither was touched.

### File List

- `_bmad-output/implementation-artifacts/6-1-agent-comments-transitions-a-tracker-ticket-mid-job.md` (new)
- `_bmad-output/implementation-artifacts/sprint-status.yaml` (modified)
- `backend/services/tracker_resolution.py` (new)
- `backend/mcp/server.py` (modified)
- `backend/tests/unit/test_tracker_resolution.py` (new)
- `backend/tests/unit/test_mcp_server.py` (modified)

## Change Log

- 2026-08-12: Story created, marked ready-for-dev.
- 2026-08-12: Implementation complete — shared tracker-resolution helper, `codeplane_tracker` MCP tool wired through Story 3.4's `TrackerWriteService`, full test coverage. Marked review.
