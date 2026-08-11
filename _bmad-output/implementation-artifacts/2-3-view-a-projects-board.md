---
baseline_commit: 162d97a2
---

# Story 2.3: View a Project's board

Status: review

## Story

As a CodePlane user,
I want to open a Kanban board scoped to just one Project,
so that I only see that Project's jobs, never another Project's noise mixed in.

## Acceptance Criteria

1. **Given** a Project card on the Overview, **when** I click into it, **then** I land on a board at a child route of the existing `/repos/:repoPath` shell, showing only jobs belonging to that Project's member repo(s), and the board reuses the existing three-column status classifier (In Progress / Awaiting Input / Failed) unmodified.
2. **Given** the URL for a Project's board, **when** I refresh the page or share the link, **then** the same scoped board loads (state lives in the URL route param, not client-only state).

## Tasks / Subtasks

- [x] Task 1: Add repo-scoped job selectors (AC: 1)
  - [x] Extract the existing active/signoff/attention classification predicates in `frontend/src/store/selectors.ts` into named predicate functions, reused by both the existing unscoped selectors and new scoped ones (AD-1: one classifier, reused not re-implemented)
  - [x] Add `selectActiveJobsForRepo(repoPath)`, `selectSignoffJobsForRepo(repoPath)`, `selectAttentionJobsForRepo(repoPath)` selectors that apply the shared predicates plus a `job.repo === repoPath` filter
  - [x] Confirm existing `selectActiveJobs`/`selectSignoffJobs`/`selectAttentionJobs` signatures and behavior are unchanged (NFR6 — `KanbanBoard`/`MobileJobList` continue to work unmodified)
- [x] Task 2: Build `RepoBoard.tsx` (AC: 1, 2)
  - [x] New `frontend/src/components/RepoBoard.tsx`: reads `repoPath` via `useParams` (AD-2, same mechanism as `RepoJobs`/`RepoHealth`/`RepoCost`)
  - [x] Fetches jobs into the store on mount (`fetchJobs({ limit: 100, archived: false })` + `enrichJob`, same pattern as `DashboardScreen`) so a direct page load/refresh/shared link resolves the board without depending on another screen having already populated the store (AC 2)
  - [x] Renders a small header (back-to-overview link, matching `RepoJobs`/`RepoSettings` style) and the 3-column grid reusing `KanbanColumn` unchanged (AD-1), fed by the Task 1 selectors
  - [x] Shows `KanbanSkeleton` while the initial fetch is in flight (matching `DashboardScreen`'s loading behavior)
- [x] Task 3: Route wiring (AC: 1, 2)
  - [x] Add a lazy-loaded `<Route path=":repoPath/board" element={<RepoBoard />} />` under the existing `/repos` `RepoLayout` route in `frontend/src/App.tsx`, alongside `:repoPath/jobs`, `:repoPath/health`, etc.
- [x] Task 4: Entry point pending Story 2.2 (AC: 1)
  - [x] Since the Projects Overview (Story 2.2, click-a-card-to-open-the-board) has not landed yet, add a simple "Board" link in `RepoOverview.tsx`'s header actions area (same visual pattern as the existing Jobs/Cost/Health links) so `/repos/:repoPath/board` is reachable via the UI today; Story 2.2 supersedes this with its own click-through from the Overview grid later
- [x] Task 5: Tests (AC: 1, 2)
  - [x] Unit tests for the three new repo-scoped selectors in `frontend/src/store/__tests__/sse-events.test.ts` (repo filtering, exclusion of other repos/archived jobs, bucket semantics match the unscoped selectors)
  - [x] `frontend/src/components/__tests__/RepoBoard.test.tsx` mirroring `DashboardScreen.test.tsx`: loading skeleton, fetch-on-mount, renders columns scoped to `repoPath`, excludes jobs from other repos
  - [x] `frontend/src/App.test.tsx`: route test asserting `/repos/:repoPath/board` renders `RepoBoard`
  - [x] Run targeted frontend test files touched by this story; confirm no regressions

## Dev Notes

- Architecture: `_bmad-output/planning-artifacts/architecture/architecture-codeplane-2026-08-10/ARCHITECTURE-SPINE.md` AD-1 (one shared job-status classifier reused, not re-implemented) and AD-2 (repo scoping travels via the URL route param, child route of the existing `/repos/:repoPath` shell — no new top-level route owns repo selection).
- SPEC: `_bmad-output/specs/spec-project-boards/SPEC.md` CAP-1. `ui-flows.md`'s CAP-1 section and the architecture doc both state: *"a single-repo Project reduces to the original `job.repo === repoPath` filter."* Story 2.2 (Overview → Project awareness in the frontend, multi-repo Project grouping) has not landed and is out of scope for this story (separate story, may run in parallel) — so this story implements the board scoped to the existing single `repoPath` route param exactly as `RepoJobs`/`RepoHealth`/`RepoCost` already do. This is not a regression against the multi-repo Project case: the route contract (`repoPath` via `useParams`) is unchanged: once 2.2 wires up Project membership, `repoPath` can resolve to a multi-repo Project without any change to this story's board or route shape.
- Story 2.1 (`_bmad-output/implementation-artifacts/2-1-create-edit-a-project.md`) explicitly notes CAP-1 (this board) was out of scope for it, and that no frontend Project types/client exist yet (`schema.d.ts`/`api/types.ts` have no `Project` shapes) — confirming this story does not depend on any frontend Project plumbing.
- No backend or database changes are required for this story — it is a pure frontend addition consuming the existing job store/API.
- Follow repo conventions: Zustand store reads via named selectors (never inline arrow functions or local component state duplicating store data), reuse existing components (`KanbanColumn`, `KanbanSkeleton`) rather than forking them.

### Project Structure Notes

- New files: `frontend/src/components/RepoBoard.tsx`, `frontend/src/components/__tests__/RepoBoard.test.tsx`
- Modified files: `frontend/src/store/selectors.ts`, `frontend/src/App.tsx`, `frontend/src/App.test.tsx`, `frontend/src/components/RepoOverview.tsx`, `frontend/src/store/__tests__/sse-events.test.ts`

### References

- [Source: _bmad-output/planning-artifacts/epics.md#Story 2.3: View a Project's board]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-codeplane-2026-08-10/ARCHITECTURE-SPINE.md#AD-1]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-codeplane-2026-08-10/ARCHITECTURE-SPINE.md#AD-2]
- [Source: _bmad-output/specs/spec-project-boards/SPEC.md#CAP-1]
- [Source: _bmad-output/specs/spec-project-boards/ui-flows.md#CAP-1 — Project-scoped board]

## Dev Agent Record

### Agent Model Used

claude-sonnet-5

### Debug Log References

### Completion Notes List

- Implemented `RepoBoard.tsx` scoped to the existing `repoPath` route param (AD-2). Since Story 2.2 (Overview/multi-repo Project awareness in frontend) has not landed, the board filters by `job.repo === repoPath` per the architecture doc's own note that a single-repo Project reduces to this filter — no rework needed once 2.2 wires up multi-repo membership, since the route/component contract is unchanged.
- Extracted the existing active/signoff/attention classification logic in `selectors.ts` into shared predicate functions, reused by both the unscoped selectors (unchanged behavior/signature, NFR6) and new `selectActiveJobsForRepo`/`selectSignoffJobsForRepo`/`selectAttentionJobsForRepo` (AD-1).
- `RepoBoard` fetches jobs on mount independently of `DashboardScreen` (same `fetchJobs`/`enrichJob` pattern) so a direct page load, refresh, or shared link resolves the board without depending on another screen's fetch (AC 2).
- Added a "Board" link on `RepoOverview.tsx`'s header as a stand-in entry point until Story 2.2's Overview card click-through supersedes it.
- No backend or database changes were required; verified no `alembic/versions/` files were touched.
- Full targeted frontend test suite (selectors, RepoBoard, App routes, DashboardScreen regression) passes: 67/67. `tsc --noEmit` and `eslint` on all touched files are clean.

### File List

- frontend/src/components/RepoBoard.tsx (new)
- frontend/src/components/__tests__/RepoBoard.test.tsx (new)
- frontend/src/store/selectors.ts
- frontend/src/store/index.ts
- frontend/src/store/__tests__/sse-events.test.ts
- frontend/src/App.tsx
- frontend/src/App.test.tsx
- frontend/src/components/RepoOverview.tsx
- _bmad-output/implementation-artifacts/2-3-view-a-projects-board.md (new)
- _bmad-output/implementation-artifacts/sprint-status.yaml

## Change Log

- 2026-08-10: Story created and implemented (Copilot CLI, dev-story workflow).
