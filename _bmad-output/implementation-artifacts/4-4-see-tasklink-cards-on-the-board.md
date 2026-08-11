---
baseline_commit: d96db821
---

# Story 4.4: See TaskLink cards on the board

Status: review

## Story

As a CodePlane user watching a Project board,
I want to see task recipe nodes as cards alongside regular job cards,
so that I can see the whole graph of planned and running work in one place.

## Acceptance Criteria

1. **Given** a Project with TaskLinks created via ingestion (4.2), manual assignment (4.3), or both, **when** I view that Project's board, **then** every TaskLink renders as a card in the same column grid as job cards, through one client-side rendering pass (not a separate screen).
2. **Given** a TaskLink whose `depends_on` list has unsatisfied entries, **when** I view the board, **then** that card renders greyed out with a chained-lifetime badge, distinguishing it from an active job card.
3. **Given** a TaskLink whose dependencies are all satisfied, **when** I view the board, **then** the card renders in its normal (non-greyed) state, ready to spawn or already linked to a running `job_id`.

## Tasks / Subtasks

- [x] Resolve the owning Project for the board's `repoPath` (AC: #1)
  - [x] `fetchProjects()` in `frontend/src/api/client.ts` (`GET /settings/projects`, already exists server-side from Story 2.1 — no backend change).
  - [x] `fetchProjectTaskLinks(projectId)` in `frontend/src/api/client.ts` (`GET /settings/projects/{id}/task-links`, already exists server-side from Story 4.2 — no backend change).
  - [x] Regenerate `frontend/src/api/schema.d.ts` (`npm run generate:api` against a locally running backend) — purely refreshing stale generated types for already-shipped endpoints, no functional backend change.
- [x] Render TaskLink cards in the board's column grid (AC: #1, #2, #3)
  - [x] New `TaskLinkCard.tsx` component: chain-lifetime icon/badge, story-node/tracker-ticket label, repo name, satisfied vs. greyed-waiting visual state — styled consistently with the existing `JobCard.tsx`.
  - [x] `KanbanColumn.tsx`: optional `extraCards` prop to render non-job cards after the job list, used only for the "In Progress" column (a TaskLink represents planned/chained work, not a job-state outcome, matching the CAP-10 wireframe in `ui-flows.md`).
  - [x] `RepoBoard.tsx`: on mount, fetch Projects, find the one whose `repoPaths` contains the current `repoPath`; if found, fetch its full TaskLink set; render cards only for TaskLinks whose own `repoPath` matches the current board (single-repo-Project reduction, consistent with existing job filtering per Story 2.3's Dev Notes).
- [x] Compute dependency satisfaction (AC: #2, #3)
  - [x] A `dependsOn` entry (composite `"{repoPath}::{storyNodeId}"`) is satisfied when its target TaskLink is found within the full Project TaskLink set (so cross-repo dependencies resolve) **and** that target has a `jobId` whose Job (looked up from the already-populated jobs store) is in the `completed` state.
  - [x] An entry whose target cannot be resolved, or whose target's Job isn't `completed`, is unsatisfied.
  - [x] Empty `dependsOn` ⇒ trivially satisfied (AC #3's "ready to spawn" case).
- [x] Tests (AC: #1, #2, #3)
  - [x] `TaskLinkCard.test.tsx`: satisfied vs. greyed-waiting rendering, badge text/labels.
  - [x] Extend `RepoBoard.test.tsx`: TaskLink cards render in "In Progress" alongside job cards; greyed state for unsatisfied deps; normal state for satisfied/empty deps; cards scoped to the board's own repo only.
  - [x] Run targeted vitest + eslint + tsc on changed frontend files.

## Dev Notes

- **No backend changes required.** Story 4.2 (merged, PR #60) already shipped `TaskLinkRow`/`TaskLink`/`TaskLinkResponse` (including `tracker_ticket_ref`/`prompt_override`, which Story 4.3 will populate later but which already exist in the schema), `GET /settings/projects/{id}/task-links`, and `GET /settings/projects` (list, from Story 2.1). This story is a frontend-only consumer of already-shipped read endpoints — confirmed directly against `backend/models/db.py`, `backend/models/api_schemas.py`, and `backend/api/projects.py` before starting.
- **Story 4.3 status:** in PR #63, in final review, not yet merged as of this story's start. Verified it introduces no new schema/contract that 4.4 needs — `tracker_ticket_ref`/`prompt_override` already exist from 4.2. Not a blocker; explicitly not implementing 4.3's manual-assignment UI/flow here.
- Per `_bmad-output/specs/spec-project-boards/ui-flows.md` (CAP-8 through CAP-11): "`TaskLink` cards (CAP-9/CAP-10) render inside the *same* `RepoBoard` column grid as regular job cards (CAP-1), fetched by the same board via a second call (`GET /settings/projects/:id/task-links`, AD-11)." The wireframe places both a satisfied ("✓ deps satisfied") and an unsatisfied greyed ("⏳ waiting on …") TaskLink card in the "In progress" column, alongside a real job card — this story follows that placement exactly.
- `RepoBoard.tsx` (Story 2.3) currently reduces "Project" to `job.repo === repoPath` for job filtering (documented in its own header comment) since multi-repo Project wiring into the frontend job-fetch path hasn't landed yet. This story does **not** change that job-filtering reduction — it only adds a second, independent fetch (Projects list → owning Project → its TaskLinks) needed to resolve TaskLink cards, scoped defensively: if no Project claims this `repoPath` (e.g., a pre-migration bare repo), simply render zero TaskLink cards rather than erroring.
- Dependency-satisfaction rule for this story (AC #2/#3) is intentionally conservative and read-only: satisfied only requires the target TaskLink's linked Job to have reached the `completed` state (using the existing job-state classification already used by `frontend/src/store/selectors.ts`, not a new one). This is *not* Story 4.5's auto-spawn trigger logic — 4.4 only renders a visual state, it never calls any spawn/create-job endpoint itself.
- Do NOT implement: 4.3 manual assignment UI, 4.5 auto-spawn via `spawn_task`, 4.6 tracker-write routing, any Epic 5/6 (Chat, MCP tools) work, or CAP-5's name-filter integration (Story 1.5, a separate cross-cutting concern not gated by this AC).
- Follow existing conventions: components read store state via selectors (no local copies of job state), large-list virtualization is not triggered here (TaskLink counts are small, matching existing `KanbanColumn` job-card rendering which is also non-virtualized), domain types are imported from `frontend/src/api/types.ts` (re-exporting the regenerated `schema.d.ts`, never hand-written duplicates).
- **Alembic:** none expected — this is a pure read/render feature with zero backend changes. Verify the true current alembic head via `git log origin/main -- alembic/versions/` and rebase onto latest `origin/main` immediately before opening the PR, per standing instruction, even though no migration is anticipated.

### Project Structure Notes

- `frontend/src/components/RepoBoard.tsx` — extended, not rewritten.
- `frontend/src/components/KanbanColumn.tsx` — extended with an optional prop, backward compatible with existing job-only usage (`DashboardScreen`'s flat `KanbanBoard.tsx` continues to work unchanged).
- `frontend/src/components/TaskLinkCard.tsx` — new.
- `frontend/src/api/client.ts`, `frontend/src/api/types.ts`, `frontend/src/api/schema.d.ts` — extended (schema.d.ts regenerated, not hand-edited).

### References

- `_bmad-output/planning-artifacts/epics.md` — Epic 4, Story 4.4 (source of the ACs above).
- `_bmad-output/specs/spec-project-boards/SPEC.md` — CAP-10.
- `_bmad-output/specs/spec-project-boards/ui-flows.md` — CAP-8 through CAP-11 wireframe and data-flow section.
- `_bmad-output/implementation-artifacts/4-2-ingest-a-task-graph-into-a-project.md` — prerequisite story (TaskLink persistence + read endpoints).
- `_bmad-output/implementation-artifacts/2-3-view-a-projects-board.md` — prerequisite story (`RepoBoard.tsx`, job-card rendering conventions).

## Dev Agent Record

### Debug Log

- Confirmed via direct code inspection (`backend/models/db.py`, `backend/models/api_schemas.py`, `backend/api/projects.py`) that no backend changes were needed: `GET /settings/projects` and `GET /settings/projects/{id}/task-links` already existed and returned all fields needed (`repo_path`, `story_node_id`, `tracker_ticket_ref`, `depends_on`, `job_id`).
- `frontend/src/api/schema.d.ts` was stale (missing `ProjectResponse`/`TaskLinkResponse` types) — regenerated by running `create_app().openapi()` in-process, dumping to a temp `openapi.json`, and running `npx openapi-typescript` against it (no live server needed).
- Rebased onto latest `origin/main` after Story 4.3 (PR #63) merged mid-session; confirmed via `git show` that 4.3 only added a new `CreateManualTaskLinkRequest` schema and a POST endpoint — `TaskLinkResponse` itself is unchanged, so no re-regeneration of `schema.d.ts` was required after rebase.
- Verified alembic head against `origin/main`: still `0063_add_chat_messages.py` (no new migrations landed), confirming this story's "no migration needed" assumption held after rebase.

### Completion Notes

- Implemented as a frontend-only feature: `RepoBoard` resolves the Project owning its `repoPath` via `fetchProjects()`, fetches that Project's TaskLinks via `fetchProjectTaskLinks(projectId)`, computes per-TaskLink dependency satisfaction (`computeSatisfaction` helper: a `depends_on` entry is satisfied iff its target TaskLink exists in the Project's full TaskLink set and that target's `jobId` maps to a job with `state === "completed"`; empty `depends_on` is trivially satisfied), and renders `TaskLinkCard` entries in the "In Progress" `KanbanColumn` via a new optional `extraCards` prop — matching the `ui-flows.md` CAP-8–11 wireframe exactly.
- TaskLink cards are scoped to the board's own `repoPath` only (consistent with `RepoBoard`'s existing single-repo-Project job-filtering reduction).
- No backend changes were made or needed. Story 4.3 (manual assignment) merged mid-implementation but introduced no new fields relevant to 4.4's rendering — confirmed by diffing `api_schemas.py` after rebase.
- Explicitly NOT implemented (out of scope): Story 4.3's manual-assignment UI/flow, Story 4.5's auto-spawn-on-completion (`spawn_task`) logic, Story 4.6's tracker-write routing, any Epic 5/6 work, and CAP-5's name-filter integration.
- Tests: 5 new tests in `TaskLinkCard.test.tsx` (label rendering, tracker-ticket fallback, satisfied styling, greyed waiting styling, generic waiting badge) + 4 new tests added to `RepoBoard.test.tsx` (TaskLink cards render for resolved Project, greyed when dependency incomplete, satisfied once dependency completes, scoped to board's own repo only). All 15 relevant tests (9 pre-existing + new) pass. `eslint` and `tsc --noEmit` pass clean on all changed files. `DashboardScreen.test.tsx` re-run to confirm the optional `extraCards` prop addition to `KanbanColumn.tsx` didn't regress the flat-board usage — all 7 tests pass.

## File List

- `_bmad-output/implementation-artifacts/4-4-see-tasklink-cards-on-the-board.md` (new)
- `_bmad-output/implementation-artifacts/sprint-status.yaml` (modified)
- `frontend/src/api/client.ts` (modified — added `fetchProjects()`, `fetchProjectTaskLinks()`)
- `frontend/src/api/types.ts` (modified — re-exported `ProjectResponse`, `ProjectListResponse`, `TaskLinkResponse`, `TaskLinkListResponse`)
- `frontend/src/api/schema.d.ts` (modified — regenerated from live OpenAPI schema, no functional backend change)
- `frontend/src/components/TaskLinkCard.tsx` (new)
- `frontend/src/components/KanbanColumn.tsx` (modified — added optional `extraCards` prop)
- `frontend/src/components/RepoBoard.tsx` (modified — Project/TaskLink fetch, satisfaction computation, card wiring)
- `frontend/src/components/__tests__/TaskLinkCard.test.tsx` (new)
- `frontend/src/components/__tests__/RepoBoard.test.tsx` (modified — added TaskLink rendering test cases)

## Change Log

- 2026-08-10: Story drafted from epics.md Epic 4 / Story 4.4 and started (bmad-dev-story).
- 2026-08-10: Implementation complete — TaskLink cards render on `RepoBoard` per AC #1–#3, no backend changes, rebased onto `origin/main` (post Story 4.3 merge), all targeted tests/eslint/tsc pass. Status → review.
