---
title: 'Fix Story 3.3 polling policy and commit E2E coverage'
type: 'chore'
created: '2026-08-12'
status: 'done'
review_loop_iteration: 0
baseline_commit: '8fb32f54'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** PR #74 exposes an unnecessary configurable polling interval and reports a live Playwright flow without committing a repeatable E2E spec.

**Approach:** Remove the interval configuration surface, poll every tracker link on a fixed 60-second cadence, and commit a dedicated Playwright scenario that launches isolated production assets with a fake Jira service to prove scheduled polling and manual refresh through real backend APIs.

## Boundaries & Constraints

**Always:** Use a single fixed 60-second production interval; keep manual refresh; use an isolated temporary `CODEPLANE_HOME`; migrate it to the current Alembic head; use a real CodePlane backend and production frontend build; keep Jira local and deterministic; assert zero browser console errors; terminate spawned processes and remove temporary state after the run.

**Ask First:** Any polling cadence other than 60 seconds, change to shared E2E runner defaults, or external network access.

**Never:** Retain a user-facing or persisted poll-interval setting; use the user's normal CodePlane database; contact a real tracker; replace backend behavior with Playwright route mocks; weaken the existing Story 3.3 assertions; or claim scheduled polling based only on pre-seeded browser responses.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Fixed cadence | Running tracker service | Poll loop waits 60 seconds between scheduled refresh cycles | Unit test verifies the fixed constant is used; shutdown wakes the wait immediately |
| Scheduled poll | Project, Jira credential, TrackerLink, fixed 60-second wait | Fake Jira ticket is fetched, persisted, and rendered in Settings | Poll API is retried until a bounded deadline, then the test fails with the last observed summary |
| Manual refresh | Fake Jira changes ticket status after initial poll | Refresh button causes a real backend provider call and updates rendered status | Provider/request failure fails the visible status assertion |
| Browser diagnostics | Any page interaction | No console error messages | Collected console errors are reported in the final assertion |

</frozen-after-approval>

## Code Map

- `frontend/tracker-e2e/tracker-sync.spec.ts` -- isolated live-service orchestration and Story 3.3 browser assertions.
- `frontend/playwright.tracker.config.ts` -- dedicated base URL and timeout without the shared development server.
- `frontend/package.json` -- repeatable production-build plus tracker E2E command.
- `backend/services/tracker_sync_service.py` -- fixed 60-second scheduled poll cadence and shutdown wakeup.
- `backend/config.py` -- remove tracker interval persistence and defaults.
- `backend/api/settings.py` -- remove tracker interval response/update wiring.
- `backend/models/api_schemas.py` -- remove tracker interval wire fields.
- `frontend/src/components/SettingsScreen.tsx` -- remove tracker interval control.
- `frontend/src/api/types.ts` and `frontend/src/api/schema.d.ts` -- remove the retired setting from generated/client contracts.
- `backend/tests/unit/test_config.py`, `backend/tests/integration/test_api_settings.py`, `backend/tests/unit/test_tracker_sync_service.py`, `frontend/src/components/__tests__/SettingsScreen.test.tsx` -- replace configurable-interval assertions with fixed-cadence coverage.
- `_bmad-output/implementation-artifacts/3-3-view-synced-ticket-state.md` -- committed E2E evidence and file inventory.

## Tasks & Acceptance

**Execution:**
- [x] `backend/config.py`, `backend/api/settings.py`, `backend/models/api_schemas.py` -- remove persisted/API interval configuration.
- [x] `backend/services/tracker_sync_service.py` -- replace mutable interval and interval-change wakeup with a fixed 60-second cadence while retaining prompt shutdown.
- [x] `frontend/src/components/SettingsScreen.tsx`, `frontend/src/api/types.ts`, `frontend/src/api/schema.d.ts` -- remove the settings control and contract field.
- [x] Backend and frontend Story 3.3 tests -- remove interval-editing cases and prove the fixed service cadence.
- [x] `frontend/playwright.tracker.config.ts` -- define a Chromium-only config for the isolated tracker acceptance server.
- [x] `frontend/tracker-e2e/tracker-sync.spec.ts` -- start fake Jira and CodePlane, seed through APIs, verify scheduled rendering, manual refresh, console diagnostics, and teardown.
- [x] `frontend/package.json` -- add a discoverable command that builds production assets and runs only the tracker E2E spec.
- [x] `_bmad-output/implementation-artifacts/3-3-view-synced-ticket-state.md` -- record the committed spec and final command.

**Acceptance Criteria:**
- Given a running tracker sync service, when it schedules refreshes, then the production cadence is fixed at 60 seconds and is not exposed through configuration, API, or UI.
- Given an isolated migrated CodePlane home and local fake Jira, when the fixed 60-second scheduled wait elapses, then the fetched ticket is persisted and rendered from the live backend.
- Given the rendered ticket and a changed fake Jira response, when Refresh is clicked, then the new status is visible after a real provider request.
- Given the full browser flow, when it completes, then no console errors occurred and all spawned resources are stopped.

## Spec Change Log

## Design Notes

The dedicated config avoids the shared `cpl up` runner because this scenario must control its own database and provider endpoint. The E2E test intentionally waits for the real fixed 60-second cadence so it proves the production scheduling path rather than a test-only override. The spec owns its local HTTP server and backend subprocess so the command is reproducible on Windows and CI without mutating developer state.

## Verification

**Commands:**
- `npm --prefix frontend run test:e2e:tracker` -- expected: production build succeeds and the dedicated Chromium spec passes.
- `npm --prefix frontend run typecheck` -- expected: no TypeScript errors in frontend source.
- `npm --prefix frontend run lint:e2e:tracker` -- expected: no lint findings in the dedicated config/spec.

## Suggested Review Order

**Fixed scheduling policy**

- Start with the single code-owned cadence and shutdown-safe wait.
  [`tracker_sync_service.py:23`](../../backend/services/tracker_sync_service.py#L23)

- Verify retired persisted cadence is removed during configuration saves.
  [`config.py:398`](../../backend/config.py#L398)

- Confirm settings updates reject the retired field instead of ignoring it.
  [`api_schemas.py:119`](../../backend/models/api_schemas.py#L119)

**Live acceptance boundary**

- Review deterministic Jira request validation and isolated provider behavior.
  [`tracker-sync.spec.ts:54`](../../frontend/tracker-e2e/tracker-sync.spec.ts#L54)

- Check process termination and failure-resilient temporary-state cleanup.
  [`tracker-sync.spec.ts:143`](../../frontend/tracker-e2e/tracker-sync.spec.ts#L143)

- Follow scheduled persistence, rendering, manual refresh, and browser diagnostics.
  [`tracker-sync.spec.ts:334`](../../frontend/tracker-e2e/tracker-sync.spec.ts#L334)

- Confirm dedicated Chromium timing supports startup plus the real cadence.
  [`playwright.tracker.config.ts:4`](../../frontend/playwright.tracker.config.ts#L4)

**Supporting evidence**

- Verify CI runs the isolated tracker acceptance command explicitly.
  [`ci.yml:149`](../../.github/workflows/ci.yml#L149)

- Check fixed-cadence and prompt-shutdown unit coverage.
  [`test_tracker_sync_service.py:160`](../../backend/tests/unit/test_tracker_sync_service.py#L160)
