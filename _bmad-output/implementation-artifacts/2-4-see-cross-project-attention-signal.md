---
baseline_commit: 11af41b0
---

# Story 2.4: See cross-Project attention signal

Status: review

## Story

As a CodePlane user managing several Projects,
I want one rolled-up signal for anything needing attention across all Projects,
So that I don't have to open every board to check for problems.

## Acceptance Criteria

1. **Given** two or more Projects, at least one with an awaiting-input or failed job, **when** I view the Overview, **then** I see a single combined count (awaiting input + failed, summed across all Projects), **and** the count updates when a job's state changes, sourced from the same batch summary call as Story 2.2 (no second endpoint).
2. **Given** no Project has any awaiting-input or failed job, **when** I view the Overview, **then** the attention signal shows zero / is not alarmingly rendered.

## Tasks / Subtasks

- [x] Task 1: Compute combined attention count (AC: 1, 2)
  - [x] In `frontend/src/components/ProjectsOverview.tsx`, derive `attentionCount` via `useMemo` from the existing `projects` state (the same array populated by `fetchProjectsSummary()` used by Story 2.2) as `sum(awaitingInputCount) + sum(failedCount)` across all items — no new fetch, no new endpoint.
- [x] Task 2: Render the combined attention badge (AC: 1, 2)
  - [x] Add a small badge/pill next to the "Projects" `<h1>` heading showing `attentionCount`.
  - [x] When `attentionCount === 0`, render with neutral/muted styling (no alarming color/icon) — not omitted, just non-alarming.
  - [x] When `attentionCount > 0`, render with an attention-drawing style (e.g. warning color), consistent with existing per-card badge colors (`text-yellow-400` awaiting / `text-red-400` failed) used elsewhere in the file.
  - [x] Keep this additive: do not modify the fetch/loading logic, card grid, or `RepoLayout.tsx`; do not touch the area reserved for Story 2.5's name filter box.
- [x] Task 3: Tests (AC: 1, 2)
  - [x] Add a vitest case: multiple projects with varying `awaitingInputCount`/`failedCount` produce the correct summed badge value.
  - [x] Add a vitest case: all projects have zero awaiting/failed → badge renders non-alarming (e.g. assert absence of the alarming CSS class, or assert the neutral variant is used) and still shows `0`.
  - [x] Confirm existing `ProjectsOverview.test.tsx` cases (per-card counts, zero-job affordance, single fetch call, empty state) still pass unmodified.

## Dev Notes

- Architecture: `_bmad-output/planning-artifacts/architecture/architecture-codeplane-2026-08-10/ARCHITECTURE-SPINE.md` AD-3/AD-5 — Project is the sole summary unit; this story adds no new summary shape, it only aggregates already-fetched per-Project fields client-side.
- SPEC: `_bmad-output/specs/spec-project-boards/SPEC.md` CAP-2 — the batch `GET /settings/projects/summary` endpoint (implemented in Story 2.2) already returns `awaitingInputCount`/`failedCount` per Project; this story is explicitly scoped to *not* add a second endpoint per the AC wording ("sourced from the same batch summary call as Story 2.2").
- This story is **frontend-only**. No backend, schema, or alembic migration changes. Confirmed via `git log origin/main -- alembic/versions/` that no new migration is introduced by this story.
- Coordination note: Story 2.5 (Filter Projects by name) is running concurrently and will likely touch `ProjectsOverview.tsx`'s header/search area. Keep this story's change additive and narrowly scoped to the attention badge only — do not restructure the heading row, fetch logic, or card grid, and do not implement the filter box (that is Story 2.5, out of scope here).
- "Updates when a job's state changes" (AC: 1) is satisfied automatically since the badge derives from the same `projects` state that already refreshes via the existing `fetchProjectsSummary()` call/SSE-driven refresh path used by Story 2.2 — no separate polling/subscription needed for this story.
- Follow repo conventions: React functional components, `useMemo` for derived state, Tailwind utility classes matching existing badge styling in this file (`lucide-react` icons, `text-yellow-400`/`text-red-400` patterns).

### Project Structure Notes

- Modified files only: `frontend/src/components/ProjectsOverview.tsx`, `frontend/src/components/__tests__/ProjectsOverview.test.tsx`
- No new files, no backend files, no migrations.

### References

- [Source: _bmad-output/planning-artifacts/epics.md#Story 2.4: See cross-Project attention signal]
- [Source: _bmad-output/implementation-artifacts/2-2-view-projects-overview.md]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-codeplane-2026-08-10/ARCHITECTURE-SPINE.md#AD-3, AD-5]
- [Source: _bmad-output/specs/spec-project-boards/SPEC.md#CAP-2]

## Dev Agent Record

### Agent Model Used

claude-sonnet-5

### Debug Log References

### Completion Notes List

- Added `attentionCount` via `useMemo` in `ProjectsOverview.tsx`, summing `awaitingInputCount + failedCount` across all Projects from the existing `projects` state (already populated by Story 2.2's `fetchProjectsSummary()` — no new fetch call, no new endpoint).
- Rendered a `data-testid="attention-badge"` pill next to the "Projects" heading: neutral/muted styling (`bg-muted`, `text-muted-foreground`, class `neutral`) when zero, alarming styling (`bg-red-500/15`, `text-red-400`, `AlertTriangle` icon, class `alarming`) when > 0.
- Purely additive — no changes to fetch/loading logic, card grid, or `RepoLayout.tsx`; left the header row open for Story 2.5's filter box (not implemented here).
- 2 new vitest cases added (combined sum across projects; non-alarming zero state); all 4 pre-existing `ProjectsOverview.test.tsx` cases pass unmodified. Full frontend suite: 25 files / 261 passed, 1 pre-existing skip — no regressions.
- `npx tsc --noEmit` passes with no errors; `npx eslint` on changed files reports no issues.
- Confirmed via `git log origin/main -- alembic/versions/` that no alembic migration is introduced by this story (frontend-only change, no schema/backend touch).

### File List

- `frontend/src/components/ProjectsOverview.tsx` (modified)
- `frontend/src/components/__tests__/ProjectsOverview.test.tsx` (modified)
- `_bmad-output/implementation-artifacts/sprint-status.yaml` (modified)

## Change Log

- 2026-08-10: Story created (Copilot CLI, dev-story workflow) for backlog item `2-4-see-cross-project-attention-signal`.
- 2026-08-10: Implementation complete — combined cross-Project attention badge (awaiting+failed summed, non-alarming at zero) added to `ProjectsOverview.tsx`, sourced from the existing Story 2.2 batch summary fetch (no new endpoint). 2 new frontend tests added, full suite passes with no regressions. Status set to `review`.
