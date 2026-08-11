---
baseline_commit: 11af41b0
---

# Story 2.5: Filter Projects by name

Status: review

## Story

As a CodePlane user with many Projects,
I want to filter the Overview and sidebar by name,
so that I can find a specific Project quickly as the list grows.

## Acceptance Criteria

1. **Given** a search/filter box on the Projects Overview and the sidebar Project list, **when** I type a partial name match, **then** only matching Project cards remain visible in both locations, and the same filter mechanism is applied generically at the card-rendering layer, so it also filters Task Recipe/TaskLink cards once Epic 4 introduces them (no Epic-2-only special case).
2. **Given** the filter text matches nothing, **when** I view the filtered list, **then** an empty state is shown, not an error.

## Tasks / Subtasks

- [x] Task 1: Add a generic, reusable name-filter utility (AC: 1)
  - [x] Create `frontend/src/lib/nameFilter.ts` exporting `matchesNameFilter(name: string, query: string): boolean` — case-insensitive substring match, trims whitespace, empty/whitespace-only query matches everything
  - [x] Unit tests in `frontend/src/lib/nameFilter.test.ts` covering case-insensitivity, partial match, empty query, whitespace query, no match
- [x] Task 2: Filter the Projects Overview grid (AC: 1, 2)
  - [x] Add a search `<input>` above the card grid in `frontend/src/components/ProjectsOverview.tsx`
  - [x] Filter the fetched `projects` list through `matchesNameFilter` (against each project's display name) before rendering `ProjectCard`s — additive only, do not modify the existing `fetchProjectsSummary` data-fetching/loading logic (avoids collision with concurrently-developed Story 2.4)
  - [x] Show a distinct "no matches" empty state when the filter yields zero results but Projects exist (separate from the existing "No Projects registered" empty state)
- [x] Task 3: Filter the sidebar Project list (AC: 1, 2)
  - [x] Add a search `<input>` to the sidebar in `frontend/src/components/RepoLayout.tsx` (visible only when the sidebar is expanded)
  - [x] Filter the fetched `repos` list through `matchesNameFilter` (against each repo's basename) before rendering the `Link` rows
  - [x] Show a "no matches" text state when filtered to zero but repos exist
- [x] Task 4: Tests (AC: 1, 2)
  - [x] Extend `frontend/src/components/__tests__/ProjectsOverview.test.tsx`: typing a filter narrows visible cards; a non-matching filter shows the no-matches empty state
  - [x] Add sidebar filter coverage for `RepoLayout.tsx` (new or extended test file)
  - [x] Run targeted vitest for changed test files, eslint/tsc on changed files; confirm no regressions

## Dev Notes

- Architecture: per epics.md AC1, the filter mechanism must be implemented generically (a single reusable helper), not as an Epic-2-only special case, since Epic 4's Task Recipe/TaskLink cards will need the same filtering later.
- This is a pure client-side, presentational change: filtering happens against data already fetched via the existing batch `GET /settings/projects/summary` call (`ProjectsOverview`) and the existing `fetchRepos` call (`RepoLayout` sidebar). No new endpoint, query param, or backend/database change is required.
- Story 2.4 (See cross-Project attention signal) is being developed concurrently in a sibling session and also touches `ProjectsOverview.tsx`/the summary endpoint. To avoid collisions, this story's changes to `ProjectsOverview.tsx` are additive-only (new search input + a filter step before render) and do not touch `fetchProjectsSummary`, the attention-signal rendering, or any other existing logic in that file.
- No alembic migration is expected for this story (confirmed against epics.md — Story 2.5 has no data-model requirement). Verify via `git log origin/main -- alembic/versions/` immediately before opening the PR per repo process.

### Project Structure Notes

- New files: `frontend/src/lib/nameFilter.ts`, `frontend/src/lib/nameFilter.test.ts`
- Modified files: `frontend/src/components/ProjectsOverview.tsx`, `frontend/src/components/RepoLayout.tsx`, `frontend/src/components/__tests__/ProjectsOverview.test.tsx`, and a sidebar filter test file

### References

- [Source: _bmad-output/planning-artifacts/epics.md#Story 2.5: Filter Projects by name]
- [Source: _bmad-output/implementation-artifacts/2-2-view-projects-overview.md]
- [Source: _bmad-output/implementation-artifacts/2-3-view-a-projects-board.md]

## Dev Agent Record

### Agent Model Used

claude-sonnet-5

### Debug Log References

### Completion Notes List

- Added a generic, reusable `matchesNameFilter(name, query)` helper in `frontend/src/lib/nameFilter.ts` (case-insensitive substring match, whitespace-trimmed, empty query matches all) so the same filter mechanism can later be reused for Task Recipe/TaskLink cards (Epic 4) per AC1 — no Epic-2-only special case.
- `ProjectsOverview.tsx`: added a search input above the grid; filtering is applied only at render time against the already-fetched `projects` list — the `fetchProjectsSummary` call, loading state, and attention-signal-adjacent rendering were left untouched to avoid colliding with the concurrently-developed Story 2.4 in a sibling session. Added a distinct "No Projects match "..."" empty state, kept separate from the existing "No Projects registered" state.
- `RepoLayout.tsx`: added a search input to the sidebar (shown only when expanded and repos exist), filtering the `repos` list by basename before rendering `Link` rows; added a "No matches" text state.
- No backend, database, or migration changes were required — pure client-side, presentational filtering over already-fetched data. Confirmed via `git log origin/main -- alembic/versions/` before opening the PR.
- Full targeted test suite passes: `nameFilter.test.ts` (6), `ProjectsOverview.test.tsx` (6, incl. 2 new filter tests), `RepoLayout.test.tsx` (3, new file) — 15/15. `eslint` and `tsc --noEmit` are clean on all touched files.

### File List

- frontend/src/lib/nameFilter.ts (new)
- frontend/src/lib/nameFilter.test.ts (new)
- frontend/src/components/ProjectsOverview.tsx
- frontend/src/components/RepoLayout.tsx
- frontend/src/components/__tests__/ProjectsOverview.test.tsx
- frontend/src/components/__tests__/RepoLayout.test.tsx (new)
- _bmad-output/implementation-artifacts/2-5-filter-projects-by-name.md (new)
- _bmad-output/implementation-artifacts/sprint-status.yaml

## Change Log

- 2026-08-10: Story created (Copilot CLI, dev-story workflow).
- 2026-08-10: Implemented name filter for Projects Overview grid and sidebar Project list; added generic `matchesNameFilter` utility and full test coverage; story moved to review.
