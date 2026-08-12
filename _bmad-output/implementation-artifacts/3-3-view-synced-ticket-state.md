---
baseline_commit: 4e6628050b88b5caac51fb0e0377fc2819c9c32c
---

# Story 3.3: View Synced Ticket State

Status: review

## Story

As a CodePlane user,
I want to see my linked tracker's ticket/board state inside CodePlane,
so that I don't have to leave CodePlane to check status.

## Acceptance Criteria

1. **Given** a Project with an attached TrackerLink, **when** the poll interval elapses or I trigger a manual refresh, **then** ticket/board state is fetched and rendered, with no inbound webhook endpoint involved at any point (NFR2).
2. **Given** the configured poll interval, **when** I change it in settings, **then** subsequent polls honor the new interval.

## Tasks / Subtasks

- [x] Task 1: Add the tracker sync read model and configuration (AC: 1, 2)
  - [x] Add `TrackerSummaryRow`, keyed by `tracker_link_id`, with normalized ticket-state JSON, last-sync timestamp, and last error; keep it separate from `JobRow`.
  - [x] Add the Alembic migration on the current `origin/main` head and update `backend/config.py`, settings schemas/API, and frontend `Settings` type with a bounded `tracker_poll_interval_seconds` value.
  - [x] Ensure settings updates mutate the app-scoped config used by the running poller and persist to `config.yaml`.
- [x] Task 2: Implement provider-isolated ticket fetching (AC: 1)
  - [x] Add `TrackerAdapterInterface` and normalized ticket models in `backend/services/tracker_adapter.py`.
  - [x] Implement GitHub Projects, Jira, and Azure DevOps read adapters using the existing `httpx` dependency and server-side decrypted credentials; never return or log a PAT.
  - [x] Keep all provider SDK/REST response shapes behind the adapter boundary and surface explicit provider/transport/response errors.
- [x] Task 3: Implement scheduled and manual tracker sync (AC: 1, 2)
  - [x] Add `TrackerSummaryRepository` and `TrackerSyncService`; iterate every TrackerLink, fetch through the matching adapter, and upsert the separate read model.
  - [x] Start and stop the poller with FastAPI lifespan; isolate per-link failures so one provider/link cannot stop later links or future poll cycles.
  - [x] Make interval changes wake/reconfigure the running poll loop so the next wait uses the new value.
  - [x] Add a thin manual-refresh endpoint and include summary state in the project-scoped TrackerLink read response; add no webhook route.
- [x] Task 4: Render synced ticket state and manual refresh in CodePlane (AC: 1, 2)
  - [x] Add typed API client functions for Projects, TrackerLinks, summaries, and manual refresh.
  - [x] Add a reusable project-grouped tracker-state panel to Settings, showing provider/link identity, ticket title/status, last-sync/error/never-synced states, and a per-link Refresh action.
  - [x] Add the poll-interval field to Settings and preserve existing credential registration behavior.
- [x] Task 5: Author comprehensive tests (AC: 1, 2)
  - [x] Unit-test adapter normalization/error handling, summary persistence, per-link failure isolation, manual refresh, and live interval changes.
  - [x] Integration-test project-scoped summary reads/manual refresh, settings persistence, secret-free responses, and absence of any inbound tracker webhook surface.
  - [x] Component-test rendered ticket/error/empty states, manual refresh, and poll-interval editing.
  - [x] Execute the critical browser flow against a running CodePlane instance: view persisted synced state, trigger manual refresh, and change the interval.

## Dev Notes

### Implementation Boundary

- Story 3.3 is read-only tracker integration. Do not implement outbound comments/transitions or approvals (Story 3.4), TrackerLink detach, Project overview/board replacement, TaskLinks, or agent-facing tracker tools.
- The current branch already contains Story 3.1 (`CredentialRow`, encrypted PAT, `CredentialRepository.resolve_secret()`, Integrations UI) and Story 3.2 (`TrackerLinkRepository`, project-scoped attach/list API). Extend those surfaces; do not duplicate them.
- Project overview and Project board UI stories are not implemented yet. Render a reusable project-grouped tracker-state panel in the existing Settings screen so AC1 is demonstrable now; keep its API/types/component reusable by later overview/board work.
- No inbound webhook route, webhook secret, webhook event model, or webhook dependency may be added. Polling plus manual refresh is the complete inbound mechanism.

### Architecture Compliance

- Follow AD-7: a background poller calls providers only through `TrackerAdapterInterface`, once per `TrackerLinkRow`, and writes a separate `TrackerSummaryRow`; never write tracker data into `JobRow` or the job-status store.
- Keep FastAPI routes thin. Database access belongs in repositories under `backend/persistence/`; orchestration belongs in `TrackerSyncService`.
- The decrypted PAT remains server-side inside the adapter call boundary. API responses, structured logs, errors, frontend state, and job prompts must remain secret-free.
- Use the existing app-scoped `CPLConfig` singleton and settings mutation path. A changed interval must affect the running poller without restart.
- Start/stop the poller through `backend/lifespan.py` and close its `httpx.AsyncClient` during shutdown. Do not leave orphan tasks.
- Use `CamelModel` for wire models and camelCase on the frontend.
- Provider HTTP behavior should follow the current official APIs: GitHub GraphQL ProjectsV2 items, Jira REST v3 issue search, and Azure DevOps Work Item Tracking WIQL 7.1. Normalize all provider output to one internal ticket shape.

### Existing Files to Preserve

- `backend/api/tracker_links.py`: currently provides secret-free project-scoped attach/list and maps missing Project/Credential to 404. Preserve those contracts while adding summary/manual refresh.
- `backend/persistence/tracker_link_repo.py`: currently validates Project/Credential existence and orders links by `created_at`. Reuse it for link enumeration rather than querying TrackerLink rows in routes.
- `backend/persistence/credential_repo.py`: `resolve_secret()` is the only permitted PAT-decryption entry point for sync.
- `backend/config.py`, `backend/api/settings.py`, `backend/models/api_schemas.py`: preserve partial settings updates and persisted app-scoped mutation.
- `backend/lifespan.py`: preserve reverse-order shutdown and ensure tracker sync stops before DB engine disposal.
- `frontend/src/components/SettingsScreen.tsx`: preserve existing settings dirty/save/reset behavior and Credential UI.
- `frontend/src/components/IntegrationsSettings.tsx`: preserve global Credential registration/deletion; TrackerLink state is Project-scoped and should be a sibling panel, not folded into credential rows.

### Testing Requirements

- Use fake adapters and in-memory SQLite for deterministic unit/integration tests; automated tests must never call real tracker services.
- Prove a failed link does not prevent another link from syncing and does not terminate the poll loop.
- Prove the manual endpoint refreshes only the requested link and rejects a link outside the requested Project.
- Prove changing the interval wakes/reconfigures the existing service rather than requiring process restart.
- Assert API payloads and logs contain no plaintext or encrypted credential material.
- Because AC1 explicitly requires rendered state and manual refresh, run the real browser flow; component tests alone do not satisfy completion.

### Project Structure Notes

- New backend files: `backend/services/tracker_adapter.py`, `backend/services/tracker_sync_service.py`, `backend/persistence/tracker_summary_repo.py`, one Alembic migration.
- New frontend component: `frontend/src/components/TrackerSyncPanel.tsx`, mounted from `SettingsScreen.tsx`.
- Reuse existing `httpx`, FastAPI, SQLAlchemy, React, and Vitest/Playwright dependencies; add no package.

### References

- [Source: `_bmad-output/planning-artifacts/epics.md#Story-33-View-synced-ticket-state`]
- [Source: `_bmad-output/specs/spec-project-boards/SPEC.md` CAP-7, NFR2]
- [Source: `_bmad-output/specs/spec-project-boards/ui-flows.md#CAP-7-Global-Credentials--per-Project-TrackerLinks`]
- [Source: `_bmad-output/planning-artifacts/architecture/architecture-codeplane-2026-08-10/ARCHITECTURE-SPINE.md#AD-7`]
- [Source: `_bmad-output/implementation-artifacts/3-2-attach-a-trackerlink-to-a-project.md`]
- [Source: GitHub GraphQL API reference, Jira REST API v3 issue search, Azure DevOps WIQL REST API 7.1]

## Dev Agent Record

### Agent Model Used

GPT-5.6 Sol (GitHub Copilot CLI).

### Debug Log References

- `uv run --no-sync pytest backend/tests/unit/test_config.py backend/tests/integration/test_api_settings.py backend/tests/integration/test_api_tracker_links.py backend/tests/unit/test_tracker_adapter.py backend/tests/unit/test_tracker_sync_service.py`
- `uv run --no-sync ruff check backend`
- `uv run --no-sync mypy backend/services/tracker_adapter.py backend/services/tracker_sync_service.py backend/persistence/tracker_summary_repo.py backend/api/tracker_links.py`
- `npx vitest run`
- `npm run typecheck && npm run build`
- Live Playwright acceptance against isolated CodePlane and fake Jira services; screenshot: `story-3-3-e2e.png` in the session artifacts directory.

### Completion Notes List

- Ultimate context engine analysis completed - comprehensive developer guide created.
- Added an AD-7-compliant tracker summary read model and migration, resequenced to the current mainline migration head (`0065 -> 0064`).
- Added normalized GitHub Projects, Jira, and Azure DevOps adapters behind `TrackerAdapterInterface`, with server-side credential resolution and sanitized errors.
- Added scheduled and manual synchronization with project scoping, per-link locking, failure isolation, lifecycle shutdown, and live interval wakeups.
- Added secret-free summary responses, a project-grouped Settings panel, per-link refresh, and persisted interval editing.
- Verified the required production browser flow: scheduled polling rendered a persisted Jira ticket, manual refresh completed, and a changed interval survived reload with no browser console errors.
- Frontend regression result: 24 files passed, 247 tests passed, 1 skipped. Story-specific backend result: 69 tests passed; the backend-wide Windows run terminated at 63% on the existing async timeout after unrelated platform-path failures.

### File List

- `_bmad-output/implementation-artifacts/3-3-view-synced-ticket-state.md`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`
- `alembic/versions/0065_add_tracker_summaries.py`
- `backend/api/settings.py`
- `backend/api/tracker_links.py`
- `backend/config.py`
- `backend/di.py`
- `backend/lifespan.py`
- `backend/models/api_schemas.py`
- `backend/models/db.py`
- `backend/persistence/tracker_summary_repo.py`
- `backend/services/tracker_adapter.py`
- `backend/services/tracker_sync_service.py`
- `backend/tests/integration/conftest.py`
- `backend/tests/integration/test_api_settings.py`
- `backend/tests/integration/test_api_tracker_links.py`
- `backend/tests/unit/test_config.py`
- `backend/tests/unit/test_tracker_adapter.py`
- `backend/tests/unit/test_tracker_sync_service.py`
- `frontend/src/api/client.ts`
- `frontend/src/api/types.ts`
- `frontend/src/components/SettingsScreen.tsx`
- `frontend/src/components/TrackerSyncPanel.tsx`
- `frontend/src/components/__tests__/SettingsScreen.test.tsx`
- `frontend/src/components/__tests__/TrackerSyncPanel.test.tsx`

## Change Log

- 2026-08-10: Created comprehensive Story 3.3 implementation context; status set to ready-for-dev.
- 2026-08-12: Implemented persisted tracker synchronization, manual refresh, live interval updates, and rendered ticket state; status set to review.
