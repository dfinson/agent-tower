---
baseline_commit: 25562c4d
---

# Story 4.6: Route recipe tracker-writes to the paired ticket

Status: review

## Story

As a CodePlane user running a task chain paired with tracker tickets,
I want a completed task's tracker write to land on the exact ticket it's paired with,
So that status updates never land on the wrong ticket.

## Acceptance Criteria

1. **Given** a TaskLink with a `tracker_ticket_ref` set, **when** its recipe's `tracker_write` output route fires, **then** it creates a `codeplane_approval` entry (the same mechanism as Epic 3's Story 3.4) targeting that specific ticket, not any other ticket the Project might be linked to.
2. **Given** a TaskLink with no `tracker_ticket_ref` set, **when** its recipe would otherwise route to `tracker_write`, **then** that action is unavailable for that TaskLink — there is no fallback to a Project-level default ticket.
3. **Given** an approval created by a `tracker_write` output route, **when** it is approved or rejected, **then** it behaves identically to any other `codeplane_approval` entry — same UI, same resolution path.

## Tasks / Subtasks

- [x] Route a completed TaskLink's tracker write through `TrackerWriteService` (AC: #1, #2)
  - [x] Add `RecipeService._maybe_route_tracker_write(task_link, job_id)` in `backend/services/recipe/recipe_service.py`: fires for any TaskLink (ingested or manually-assigned, Story 4.3) whose linked Job just completed successfully. No-ops when `tracker_ticket_ref` is unset (AC #2 — no Project-level default fallback) or when `tracker_link_repo`/`tracker_write_service` aren't configured. Looks up the Project's `TrackerLink`(s) for routing/credential context only — the write always targets `task_link.tracker_ticket_ref`, never any other ticket (AC #1).
  - [x] Builds a `TrackerWriteRequest(tracker_link_id=..., ticket_ref=task_link.tracker_ticket_ref, action=TrackerWriteAction.comment, value=...)` and calls `TrackerWriteService.execute(job_id, request, dispatch)` — reusing Story 3.4's approval gate verbatim (AC #3), with a log-only placeholder `dispatch` since no real tracker adapter (Jira/GitHub Issues/Azure DevOps client) exists in this codebase yet (out of this story's scope).
  - [x] Fires as a fire-and-forget coroutine (never awaited inline): `TrackerWriteService.execute` blocks on the operator's approval decision, which must never delay `handle_job_completed`'s own dependent-spawn logic (Story 4.5, AC #1-#3). The built coroutine is appended to `RecipeService.pending_tracker_writes` rather than wrapped in an `asyncio.Task` here — `RecipeService` is a short-lived local constructed fresh per event in `backend/lifespan.py` with no outer reference, so any task tracked only on the instance risks garbage collection before the approval resolves. The caller (`lifespan.py`'s `_run_spawn`) drains `pending_tracker_writes` and schedules each coroutine via the module-level `_fire_and_forget` helper (app-lifetime `_ephemeral_tasks` set), mirroring the fix Story 5.4/PR #70 applied to the same bug class.
- [x] Invoke tracker-write routing from `handle_job_completed` before the dependency-graph early return (AC: #1, #2)
  - [x] Call `_maybe_route_tracker_write` immediately after resolving `completed_link` via `get_by_job_id`, and *before* the `completed_key is None` early return — a manually-assigned TaskLink (Story 4.3, no `story_node_id`) is exactly the kind most likely to be paired with a tracker ticket, and must not be skipped by dependency-graph logic that doesn't apply to it.
- [x] Wire `RecipeService` with `tracker_link_repo`/`tracker_write_service` collaborators (AC: #1, #2, #3)
  - [x] Add optional `tracker_link_repo: TrackerLinkRepository | None` and `tracker_write_service: TrackerWriteService | None` constructor parameters to `RecipeService` (default `None`, mirroring the existing optional `chat_repo`/`approval_service` pattern from Story 5.4) — existing ingestion/listing call sites (Story 4.2-4.4) are unaffected.
  - [x] `backend/lifespan.py`'s `_spawn_dependent_task_links` subscriber (Story 4.5) additionally constructs a `TrackerLinkRepository(session)` and a `TrackerWriteService(services.approval_service)`, passing both into `RecipeService`.
- [x] Tests (AC: #1, #2, #3)
  - [x] `backend/tests/unit/test_recipe_service.py`: new `TestHandleJobCompletedTrackerWrite` class —
    - TaskLink with `tracker_ticket_ref` set → `TrackerWriteService.execute` called once, targeting that TaskLink's own ticket via the resolved `TrackerLink`'s id.
    - Manually-assigned TaskLink (no `story_node_id`) whose job completes → tracker write still routes (not skipped by the dependency-graph early return).
    - TaskLink with no `tracker_ticket_ref` → `TrackerWriteService.execute` never called, no fallback lookup performed (AC #2).
    - Project with no `TrackerLink` at all → `TrackerWriteService.execute` never called (nothing to route through).
    - `tracker_write_service`/`tracker_link_repo` not configured → no-op, never raises.
  - [x] Run targeted `pytest` on changed files + `ruff check` + `mypy` on changed backend files.

## Dev Notes

- **Prerequisites already merged to `main`:** Story 3.4 (`TrackerWriteService`, PR #71), Story 3.2/3.3 (`TrackerLinkRow`/`TrackerLinkRepository`, tracker read-model), Story 4.2 (`TaskLinkRow`/`TaskLinkRepository`/ingestion), Story 4.5 (`RecipeService.handle_job_completed` auto-spawn), Story 5.4 (gated auto-spawn, PR #70). Confirmed via `git log origin/main -5` at story-draft time (`25562c4d`).
- **No new migration:** this story is read/route-only. It reuses `TaskLinkRow.tracker_ticket_ref` (Story 4.2) and `TrackerLinkRow` (Story 3.2) as-is, and dispatches through the already-existing `TrackerWriteService`/`ApprovalService` (Story 3.4) — no new columns or tables.
- **No real tracker adapter exists yet.** `TrackerWriteService.execute` takes a caller-supplied `dispatch` callable; since no Jira/GitHub Issues/Azure DevOps client exists in this codebase, this story wires a log-only placeholder dispatcher (`_log_only_tracker_write_dispatch`). Building a real adapter is out of scope — likely Story 6.1 territory (agent mid-job tracker comments), which this story deliberately does not touch to avoid overlap with the sibling session implementing it.
- **Scope discipline — do NOT implement:** Story 6.1 (agent comments/transitions a tracker ticket mid-job) or any general mid-job agent-triggered tracker writes — this story is scoped strictly to the recipe/TaskLink *completion* path, reusing `TrackerWriteService.execute()` exactly as Story 3.4 built it. No frontend UI changes (not required by any AC above).
- **Why the TrackerLink lookup, not just the ticket ref:** `TaskLinkRow.tracker_ticket_ref` is the specific ticket string; `TrackerLinkRow` (Story 3.2) is the Project-level Credential attachment (`project_id` + `credential_id` + `external_ref`) that provides routing/credential context for `TrackerWriteRequest.tracker_link_id`. A Project may have more than one `TrackerLink` (AC2 of Story 3.2); this story picks the first one found for the Project, since `TaskLinkRow` has no `tracker_link_id` column of its own to disambiguate — the actual write target is always `tracker_ticket_ref`, never affected by which `TrackerLink` is chosen.

## Dev Agent Record

### Implementation Plan

Extended `RecipeService.handle_job_completed` (Story 4.5) with a new `_maybe_route_tracker_write` step that fires immediately after resolving the completed TaskLink and before any dependency-graph logic, so it applies uniformly to both ingested and manually-assigned TaskLinks. The tracker write is dispatched via the existing `TrackerWriteService.execute()` (Story 3.4) — no new approval or dispatch mechanism was built. Wiring in `backend/lifespan.py`'s `_spawn_dependent_task_links` subscriber constructs `TrackerLinkRepository` and `TrackerWriteService` alongside the pre-existing Story 4.5/5.4 collaborators.

### Completion Notes

- All 3 acceptance criteria satisfied: tracker write targets exactly the TaskLink's own `tracker_ticket_ref` (AC #1); no `tracker_ticket_ref` → no write and no Project-level fallback (AC #2); the created approval goes through the unmodified `ApprovalService`/`TrackerWriteService` path, so it behaves identically to any other approval (AC #3).
- No new Alembic migration — verified `alembic/versions/` head is `0064_add_chat_task_link.py` at story-draft time; no schema changes were needed.
- `backend/tests/unit/test_recipe_service.py` (35 tests, including 5 new `TestHandleJobCompletedTrackerWrite` cases) and `backend/tests/integration/test_job_completion_spawns_tasklinks.py` (2 tests) pass. `ruff check` and `mypy` pass on all changed backend files (pre-existing unrelated `mypy` findings in `backend/services/dev_restart/restart_protocol.py` and `backend/services/ingest/claude_source.py` are untouched by this story).
- **Review fix (PR #73 first-round review, blocking):** the initial implementation tracked the fire-and-forget tracker-write task in an *instance-level* `RecipeService._tracker_write_tasks` set. Since `RecipeService` is constructed as a short-lived local inside `backend/lifespan.py`'s `_run_spawn()` on every `job_completed` event with no outer reference, the task (and `TrackerWriteService.execute`'s pending approval wait) could be garbage-collected once `_run_spawn()` returned — silently dropping the write. Same bug class as Story 5.4/PR #70. Fixed by having `_maybe_route_tracker_write` build the `TrackerWriteService.execute(...)` call as an unscheduled coroutine appended to a new `RecipeService.pending_tracker_writes` list, and having `lifespan.py`'s `_run_spawn` drain that list and schedule each coroutine through the existing module-level `_fire_and_forget` helper (backed by the app-lifetime `_ephemeral_tasks` set) — the same pattern already used for spawned-job setup in the same function. Updated `TestHandleJobCompletedTrackerWrite` tests to `asyncio.gather(*service.pending_tracker_writes)` instead of the old instance-tracked-task set; re-ran the full targeted suite (35 unit + 2 integration tests) and `ruff`/`mypy` — all pass.

### File List

- `backend/services/recipe/recipe_service.py`
- `backend/lifespan.py`
- `backend/tests/unit/test_recipe_service.py`

## Change Log

- Implemented Story 4.6: routed a completed TaskLink's `tracker_write` output route through the existing `TrackerWriteService` approval gate (Story 3.4), scoped to the recipe/TaskLink completion path only.
- Fixed blocking review finding: replaced instance-level fire-and-forget task tracking on `RecipeService` (GC-unsafe, same bug class as Story 5.4/PR #70) with a caller-scheduled `pending_tracker_writes` coroutine list drained by `backend/lifespan.py` via the shared module-level `_fire_and_forget` helper.
