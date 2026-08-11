---
baseline_commit: 162d97a2
---

# Story 2.2: View Projects Overview

Status: review

## Story

As a CodePlane user,
I want to see all my Projects as cards on one overview screen,
so that I can see what exists and what needs attention without navigating into each one.

## Acceptance Criteria

1. **Given** one or more Projects are registered, **when** I load the `/repos` index route, **then** I see one card per Project, including Projects with zero active jobs (idle Projects still appear).
2. **Given** one or more Projects are registered, **when** the Overview loads, **then** each card shows active/awaiting/failed counts and last-activity, sourced from a single batch `GET /settings/projects/summary` call — never N sequential per-Project fetches.
3. **Given** a Project with no jobs at all, **when** the Overview loads, **then** its card renders with zero counts, not omitted from the grid.

## Tasks / Subtasks

- [x] Task 1: Add batch summary API schemas (AC: 1, 2, 3)
  - [x] Add `ProjectSummaryResponse` (`backend/models/api_schemas.py`): `id`, `name`, `repoPaths`, `activeJobCount`, `awaitingInputCount`, `failedCount`, `lastActivityAt`
  - [x] Add `ProjectListSummaryResponse` wrapper: `items: list[ProjectSummaryResponse]`
- [x] Task 2: Add `ProjectService` batch summary aggregation (AC: 1, 2, 3)
  - [x] Add a method that, for all Projects in one pass, buckets `JobRow` counts by `repo IN project.repo_paths`: active = `preparing`/`queued`/`running`; awaitingInput = `waiting_for_approval`/`review`/`completed` with unresolved resolution; failed = `failed`; also computes `max(updated_at)` as last activity
  - [x] Zero-job Projects still return a summary entry with all-zero counts and `lastActivityAt: null`
- [x] Task 3: Add batch summary route (AC: 1, 2, 3)
  - [x] `GET /settings/projects/summary` in `backend/api/projects.py`, registered before `/settings/projects/{project_id}` so `summary` isn't captured as an id
- [x] Task 4: Frontend API client (AC: 2)
  - [x] Add `ProjectSummaryResponse`/`ProjectListSummaryResponse` types to `frontend/src/api/schema.d.ts` and `frontend/src/api/types.ts` (hand-added additively; full wholesale regeneration deferred — see Completion Notes)
  - [x] Add `fetchProjectsSummary()` to `frontend/src/api/client.ts`
- [x] Task 5: `ProjectsOverview.tsx` card grid (AC: 1, 2, 3)
  - [x] New `frontend/src/components/ProjectsOverview.tsx`: fetches the batch summary once on load, renders one card per Project (including zero-job Projects with a "no jobs yet" affordance instead of a relative timestamp), showing active/awaiting/failed counts and last-activity
  - [x] Card click navigates to `/repos/:repoPath` using the Project's first repo path (existing route, unmodified — full per-Project board scoping is Story 2.3, out of scope here)
- [x] Task 6: Wire into `/repos` index route (AC: 1)
  - [x] Modify `RepoLayout.tsx`: remove the auto-redirect-to-first-repo effect; render `<ProjectsOverview />` at the bare `/repos` index instead of the redirect/`<Outlet />` fallback
- [x] Task 7: Tests (AC: 1, 2, 3)
  - [x] Backend unit test for the aggregation bucketing (incl. zero-job project) — `backend/tests/unit/test_project_service.py`
  - [x] Backend integration test for `GET /settings/projects/summary` (multiple projects, one with no jobs, single batch call) — `backend/tests/integration/test_api_projects.py`
  - [x] Frontend component test for `ProjectsOverview` (renders cards incl. zero-job project, single fetch call not N calls)
  - [x] Confirm existing `RepoLayout`/`DashboardScreen`/`frontend/e2e` suites are unaffected

## Dev Notes

- Architecture: `_bmad-output/planning-artifacts/architecture/architecture-codeplane-2026-08-10/ARCHITECTURE-SPINE.md` AD-3/AD-5 — Project is the sole summary unit; the prior repo-scoped `GET /settings/repos/{repo}/summary` shape is not retired by this story (still used by the existing per-repo tabs), only a new Project-scoped batch endpoint is added.
- SPEC: `_bmad-output/specs/spec-project-boards/SPEC.md` CAP-2 — `GET /settings/projects/{id}/summary` gaining `awaitingInputCount`/`failedCount` and the new batch `GET /settings/projects/summary` are both described; this story implements only the batch endpoint (CAP-2's Overview needs), since the single-Project `{id}/summary` variant is not required by any Story 2.2 AC.
- ui-flows.md line 16 — `/repos` bare index always renders the Overview grid, replacing `RepoLayout`'s current silent auto-redirect to the first repo.
- ui-flows.md line 98 — `ProjectsOverview` calls the batch endpoint once on load; extended summary shape is `awaitingInputCount`, `failedCount`, `activeJobCount` (`trackerSummaries` is CAP-7/out of scope for this story).
- Status bucket boundaries reuse the existing frontend classifier semantics from `frontend/src/store/selectors.ts` (`selectActiveJobs`/`selectSignoffJobs`/`selectAttentionJobs`): active = `preparing`/`queued`/`running`; awaiting = `waiting_for_approval`/`review`/unresolved `completed`; failed = `failed`.
- No DB schema change / no alembic migration expected — this is a pure aggregation over the existing `JobRow` table joined against `Project.repo_paths`, following the same pattern as the existing `active_job_count` computation in `backend/api/settings.py`'s `get_repo_summary`.
- Out of scope for this story: per-Project board routing/scoping (Story 2.3), the cross-project attention rollup badge (Story 2.4), and the name filter box (CAP-5).
- Follow repo conventions: thin routes, repository/service layering (no direct SQLAlchemy in API routes), `CamelModel` for schemas, Dishka DI via `FromDishka`.

### Project Structure Notes

- New files: `frontend/src/components/ProjectsOverview.tsx`, and its test file
- Modified files: `backend/models/api_schemas.py`, `backend/services/project/project_service.py`, `backend/api/projects.py`, `frontend/src/api/schema.d.ts`, `frontend/src/api/client.ts`, `frontend/src/components/RepoLayout.tsx`, `backend/tests/unit/test_project_service.py`, `backend/tests/integration/test_api_projects.py`

### References

- [Source: _bmad-output/planning-artifacts/epics.md#Story 2.2: View Projects Overview]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-codeplane-2026-08-10/ARCHITECTURE-SPINE.md#AD-3, AD-5]
- [Source: _bmad-output/specs/spec-project-boards/SPEC.md#CAP-2]
- [Source: _bmad-output/specs/spec-project-boards/ui-flows.md]

## Dev Agent Record

### Agent Model Used

claude-sonnet-5

### Debug Log References

### Completion Notes List

- Backend: added `RepoJobCounts`/`job_counts_by_repo()` to `ProjectRepository` (single grouped query across all repo paths, no N+1), `ProjectSummary` domain dataclass, `ProjectService.summary_all()` (one `list()` + one batch job-count call), `ProjectSummaryResponse`/`ProjectListSummaryResponse` schemas, and `GET /settings/projects/summary` route registered before `{project_id}` to avoid path-param capture. 36 backend tests added/passing (unit + integration), verified no regressions vs. baseline via `git stash` comparison of pre-existing unrelated Windows path-handling failures.
- Frontend: added `fetchProjectsSummary()` + types; hand-added the two new schema/type entries additively to `frontend/src/api/schema.d.ts`/`types.ts` rather than a wholesale OpenAPI regeneration — a full regen via `create_app()` outside the normal `cpl up`/uvicorn lifespan was found to drop several unrelated existing routes, so a full regen should go through the real server if ever needed. `npx tsc --noEmit` passes cleanly.
- Built `ProjectsOverview.tsx` card grid (active/awaiting/failed badges, "No jobs yet" affordance for zero-job Projects, single fetch on mount, click-to-navigate to `/repos/:repoPath` using the Project's first repo path). Wired into `RepoLayout.tsx` at the bare `/repos` index, replacing the prior auto-redirect-to-first-repo effect.
- Added 4 new frontend component tests (`ProjectsOverview.test.tsx`); full frontend suite (24 files / 246 passed, 1 pre-existing skip) and full targeted backend suite pass with no regressions.
- Confirmed via `git log origin/main -- alembic/versions/` that alembic head is `0058` (Story 2.1) and no new migration was needed for this story (pure aggregation query, no schema change).

### File List

- `backend/persistence/project_repo.py` (modified)
- `backend/models/domain.py` (modified)
- `backend/services/project/project_service.py` (modified)
- `backend/models/api_schemas.py` (modified)
- `backend/api/projects.py` (modified)
- `backend/tests/unit/test_project_service.py` (modified)
- `backend/tests/integration/test_api_projects.py` (modified)
- `frontend/src/api/schema.d.ts` (modified)
- `frontend/src/api/types.ts` (modified)
- `frontend/src/api/client.ts` (modified)
- `frontend/src/components/ProjectsOverview.tsx` (new)
- `frontend/src/components/RepoLayout.tsx` (modified)
- `frontend/src/components/__tests__/ProjectsOverview.test.tsx` (new)
- `_bmad-output/implementation-artifacts/sprint-status.yaml` (modified)

## Change Log

- 2026-08-10: Story created (Copilot CLI, dev-story workflow) for backlog item `2-2-view-projects-overview`.
- 2026-08-10: Implementation complete — batch `GET /settings/projects/summary` endpoint (backend), `ProjectsOverview.tsx` card grid wired into `/repos` index (frontend). 36 backend + 4 new frontend tests added, full suites pass with no regressions. Status set to `review`.
