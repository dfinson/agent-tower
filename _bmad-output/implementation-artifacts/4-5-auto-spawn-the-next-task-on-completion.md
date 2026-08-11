---
baseline_commit: ddd1edb9
---

# Story 4.5: Auto-spawn the next task on completion

Status: review

## Story

As a CodePlane user running a task chain,
I want the next dependent task to start automatically when its prerequisite completes,
so that I don't have to manually start every step of a planned sequence.

## Acceptance Criteria

1. **Given** a TaskLink's linked Job completes successfully, **when** a dependent TaskLink's remaining dependencies are now all satisfied, **then** its `spawn_task` output route fires, calling the same job-creation service function used by `codeplane_job create` (same worktree/branch provisioning), and the resulting `job_id` is written onto that TaskLink.
2. **Given** a TaskLink with multiple unsatisfied dependencies, **when** only some of them complete, **then** `spawn_task` does not fire until every dependency is satisfied.
3. **Given** a TaskLink that already has a `job_id`, **when** its dependencies become satisfied again for any reason, **then** it is never spawned a second time — one TaskLink points at zero-or-one real Job, never more.

## Tasks / Subtasks

- [x] Add `TaskLinkRepository.set_job_id` (AC: #1, #3)
  - [ ] `async def set_job_id(self, task_link_id: str, job_id: str) -> TaskLink | None` in `backend/persistence/task_link_repo.py`: guarded conditional `UPDATE ... WHERE id = :id AND job_id IS NULL` (rows-affected check), so it's safe under concurrent completions. Returns the updated domain object, or `None` if the row doesn't exist or already had a `job_id` (AC #3). No new schema/migration — reuses the existing `job_id` column from Story 4.2.
- [x] Add a project-wide TaskLink lookup by `job_id` (AC: #1)
  - [ ] `async def get_by_job_id(self, job_id: str) -> TaskLink | None` in `TaskLinkRepository` — used to resolve "which TaskLink just completed" from the completed Job's id.
- [x] Implement dependency-satisfaction + spawn orchestration in `RecipeService` (AC: #1, #2, #3)
  - [ ] `async def handle_job_completed(self, job_id: str, *, resolution: str | None) -> list[TaskLink]` in `backend/services/recipe/recipe_service.py`:
    - Look up the TaskLink whose `job_id == job_id` (via `get_by_job_id`); if none, return `[]` (the completed job wasn't linked to any TaskLink — a plain ad-hoc job, not part of a chain).
    - If `resolution` is not `"merged"` or `"pr_created"` (e.g. `"discarded"`), return `[]` — a discarded job never satisfies a dependency even though it still reaches `job.completed`.
    - Compute the just-completed TaskLink's composite key `f"{task_link.repo_path}::{task_link.story_node_id}"` (skip entirely — return `[]` — if `story_node_id` is null; a manually-assigned TaskLink is never itself a valid `depends_on` target since composite keys are always `repo_path::story_node_id`).
    - Load every other TaskLink in the same `project_id` (`list_by_project`).
    - For each: **skip immediately if its `job_id` is already set** (AC #3 — idempotency guard, checked before any dependency computation).
    - Otherwise check full satisfaction: for every entry in its `depends_on`, resolve the target TaskLink by composite key against the full Project TaskLink set, and require the target to have a non-null `job_id` whose Job is `completed` with `resolution` in `("merged", "pr_created")` (query via `JobRepository.get`). An unresolvable target, or one whose Job isn't in that success state, makes the entry unsatisfied. Empty `depends_on` is trivially satisfied.
    - If **all** entries satisfied → build `JobSpec(repo=dependent.repo_path, prompt=<derived prompt, see Dev Notes>, parent_job_id=job_id)`, call the injected `JobService.create_job(spec)`, then `task_link_repo.set_job_id(dependent.id, new_job.id)`.
    - If job creation raises `RepoNotAllowedError`/`SDKModelMismatchError`, log and skip that dependent (never raise out of the handler — one bad dependent must not block others or crash the event-bus subscriber).
    - Return the list of TaskLinks that were actually spawned (for logging/testability).
- [x] Wire `RecipeService` with a `JobService` dependency for spawning (AC: #1)
  - [ ] Add an optional `job_service: JobService | None` constructor parameter to `RecipeService` (defaults `None` so existing DI wiring / Story 4.2-4.4 call sites requiring only ingestion/listing keep working unchanged); `handle_job_completed` is a no-op (`return []`) when `job_service` is `None`.
  - [ ] `backend/di.py`: leave the request-scoped `recipe_service` provider as-is (API routes never call `handle_job_completed`) — the job-completion path is wired independently in `backend/lifespan.py`, not through per-request DI.
- [x] Register a job-completion subscriber in `backend/lifespan.py` (AC: #1, #2, #3)
  - [ ] New `_spawn_dependent_task_links(event: SessionEvent) -> None` closure (same style as the existing `_persist_structural_analytics`/`_persist_review_story_on_resolve` subscribers already in `lifespan.py`): returns early unless `event.kind == EventKind.job_completed`; extracts `job_id = event.session_id` and `resolution = event.payload.get("resolution")`; opens a fresh session via `session_factory` inside `serialized_write(...)`, constructs `TaskLinkRepository`, `JobRepository`, `JobService.from_session(...)`, `ProjectRepository`/`ProjectService`, `RecipeService(task_link_repo, project_service, job_service=job_service)`, calls `await recipe_service.handle_job_completed(job_id, resolution=resolution)`; for every newly spawned Job, calls `await runtime.setup_and_start(job)` in a fire-and-forget background task (mirroring the MCP `codeplane_job create` handler's own `_setup_and_start` pattern) so the new job's worktree/agent actually starts. Wrap the whole handler body in `try/except Exception: log.warning(..., exc_info=True)` so a spawn failure never breaks the event bus fan-out for other subscribers.
  - [ ] `event_bus.subscribe(_spawn_dependent_task_links)`, added in `create_app`'s lifespan function after `services = await _wire_core_services(...)` (so `services.runtime_service`/`config`/`session_factory`/`event_bus` are already in scope).
- [x] Tests (AC: #1, #2, #3)
  - [ ] `backend/tests/unit/test_task_link_repo.py`: `set_job_id` persists and returns updated TaskLink; `set_job_id` returns `None` and leaves `job_id` unchanged when called a second time on the same row (AC #3 guard); `get_by_job_id` finds the right row / returns `None` when absent.
  - [ ] `backend/tests/unit/test_recipe_service.py`: extend with `handle_job_completed` cases —
    - completed job with no linked TaskLink → returns `[]`, no job created.
    - dependent with single dependency, now satisfied (`resolution="merged"`) → `JobService.create_job` called once with expected `JobSpec`, `set_job_id` called with the new job id.
    - dependent with two dependencies, only one completed → not spawned (AC #2).
    - dependent that already has a `job_id` → never spawned again even though dependencies are (re-)satisfied (AC #3).
    - dependency's Job in `review`/`failed`/`canceled` state → dependent not spawned.
    - completed job's own `resolution == "discarded"` → returns `[]`, nothing spawned.
    - `job_service is None` → no-op, returns `[]`.
  - [ ] New `backend/tests/integration/test_job_completion_spawns_tasklinks.py`: end-to-end through the event bus — publish a `job_completed` event (resolution `merged`) for a job linked to TaskLink A; assert dependent TaskLink B (whose sole dependency is A) gets a `job_id` written and a new job row exists.
  - [ ] Run targeted `pytest` on changed files + `ruff check` + `mypy` on changed backend files.

## Dev Notes

- **Prerequisites already merged to `main`:** Story 4.2 (`TaskLinkRow`/`TaskLinkRepository`/ingestion, PR #60), Story 4.3 (manual TaskLink assignment, PR #63), Story 4.4 (TaskLink cards on the board, PR #66). Confirmed via `git log origin/main -1` → `ddd1edb9` at story-draft time.
- **Scope discipline — do NOT implement:** Story 4.6 (tracker-write routing to a paired ticket), Story 5.3/5.4 (Chat attach-to-chain, approval-gated auto-spawn), or any Epic 6 (MCP-exposed chain controls) work. This story is scoped strictly to the three ACs above: detect completion → check full dependency satisfaction → spawn once → persist `job_id`.
- **What "the linked Job completes successfully" means (AC #1), precisely:** `backend/services/runtime/service.py` (~line 1119-1124) only emits `EventKind.job_completed` when a job's final `Resolution` is `merged`, `pr_created`, **or** `discarded` (all three transition `JobState` to `completed`, as opposed to landing in `review` awaiting a human). `discarded` means the user explicitly threw the work away — that is not "success" in the chaining sense, so `handle_job_completed`'s dependency-satisfaction check must additionally read the payload's `resolution` field and only treat `merged`/`pr_created` as satisfying a dependency. Read `event.payload.get("resolution")` in the subscriber and pass it into `handle_job_completed` explicitly — do not rely on event *kind* alone.
- **Dependency-satisfaction query shape:** `depends_on` is a JSON list of composite `"{repo_path}::{story_node_id}"` strings (existing convention from Story 4.2, AD-9). There is no indexed/SQL-side lookup for "which TaskLinks depend on X" — `TaskLinkRow.depends_on` is an opaque JSON `Text` column (same as the frontend's Story 4.4 approach, which also loads the full per-Project TaskLink set and computes satisfaction in-memory rather than via SQL `LIKE`). Follow that same precedent server-side: `list_by_project` + Python-side JSON-list membership checks, not a `LIKE` query (a `LIKE '%X%'` on a JSON-serialized list is a substring-matching correctness trap once two composite keys share a prefix — e.g. `"repo::t1"` vs `"repo::t10"` — so avoid it entirely).
- **What counts as a dependency target's Job being "satisfied":** the target TaskLink must have a non-null `job_id`, and that Job's persisted state/resolution must indicate success (`JobState.completed` with `resolution` in `("merged", "pr_created")` — same success set as this story's own trigger condition above, for consistency). Query the target's Job row via `JobRepository.get` rather than re-deriving state from more events — the Job row is the single source of truth for current state.
- **Prompt for the spawned job:** `JobSpec.prompt` is required and non-empty. TaskLinks created via manual assignment (Story 4.3) always have `prompt_override` set — use it verbatim. TaskLinks created via ingestion (Story 4.2) have `story_node_id` but **no persisted task description/prompt** (the parser only captures id/depends_on/epic_id, never body text — see `backend/services/recipe/parsers.py`). For an ingested dependent with no `prompt_override`, synthesize a prompt that directs the agent to the source file itself, e.g.: `f"Implement task '{dependent.story_node_id}' in this repo. Locate and follow its full task/story definition (BMAD story file under _bmad-output/implementation-artifacts/, or the matching spec-kit tasks.md entry) for complete requirements — this prompt only identifies which task to implement."` This keeps the source-of-truth read-only and in the repo (consistent with Story 4.2's "source files are read-only" constraint) rather than trying to duplicate/parse full story bodies into the TaskLink row (a larger, out-of-scope change). Document this fallback clearly in code comments since it's a load-bearing design choice not spelled out in the AC text.
- **`spawn_task` output route fields:** Story 4.1 only added `spawn_task` to `_ALLOWED_OUTPUT_ROUTES` in the sidecar schema (`backend/services/sidecar/template_service.py`) as a recipe-authoring vocabulary word — it does not yet wire any sidecar dispatch to this story's spawn logic, and this story does not need it to. This story's trigger is the **domain event bus** (`EventKind.job_completed`), directly, per the epics.md AC's own parenthetical ("likely hooking into job-completion events on the event bus") — not a sidecar/recipe dispatch pathway. No sidecar dispatcher change is needed or in scope; `spawn_task` "firing" in AC #1's language is satisfied by this event-driven code path performing the same effect (calling job creation, writing `job_id`), not by adding a new sidecar output-route handler.
- **Job-creation service function reuse (AC #1's explicit requirement):** must be the *same* function `codeplane_job create` uses — `JobService.create_job(JobSpec(...))`, immediately followed by `RuntimeService.setup_and_start(job)` in the background, exactly mirroring `backend/mcp/server.py`'s `codeplane_job` tool handler (`_register_job_tool`, `action == "create"` branch, and its `_make_job_service` helper). Do not reimplement worktree/branch provisioning — call the existing service, don't duplicate it.
- **Idempotency (AC #3) is a hard guard:** check `dependent.job_id is not None` and skip *before* doing any dependency-satisfaction computation. Implement `set_job_id` as a guarded conditional `UPDATE ... WHERE id = :id AND job_id IS NULL` (rows-affected check) rather than a read-then-write from an ORM object, so it's correct even if the subscriber runs concurrently for two sibling dependencies completing near-simultaneously.
- **Where the subscriber is wired:** follow the exact style of the existing job-lifecycle subscribers already in `backend/lifespan.py` (`_persist_structural_analytics`, `_persist_review_story_on_resolve`, `_prefetch_review_story` — all closures defined inline in `create_app`'s lifespan function, each opening its own session via `session_factory`, each subscribed via `event_bus.subscribe(...)`, each using `_fire_and_forget` for any background work). Add the new subscriber in the same section, after `services = await _wire_core_services(...)` (so `services.runtime_service` and `config` are already in scope) and after `event_bus`/`session_factory` are available.
- **Follow existing conventions:** thin route/handler pattern — no orchestration logic lives directly in `lifespan.py` beyond wiring; all decision logic (satisfaction check, spawn) lives in `RecipeService.handle_job_completed`, matching the "route handlers are thin, service layer decides" convention. Repository methods stay narrow persistence operations (`set_job_id`, `get_by_job_id`), no query logic beyond simple `WHERE`/`UPDATE`.
- **Alembic:** none expected — `job_id` already exists on `TaskLinkRow` from Story 4.2 (nullable FK to `jobs.id`); this story only ever writes into that existing column, no new column/table. **Verify the true current alembic head via `git log origin/main -- alembic/versions/` immediately before opening the PR** (known head at story-draft time: `0063_add_chat_messages.py`, but Story 5.3 may have landed a new migration in the interim per standing instruction) and rebase onto latest `origin/main` before opening the PR.
- **No frontend changes required or in scope.** Story 4.4 already renders `job_id`-linked TaskLink cards in their satisfied/normal state once a `job_id` is present (via the existing `fetchProjectTaskLinks` poll/refetch) — this story only needs to *write* `job_id` server-side; the board already reflects it on next fetch. Do not touch `frontend/`.

### Project Structure Notes

- `backend/persistence/task_link_repo.py` — extended (new `set_job_id`, `get_by_job_id` methods).
- `backend/services/recipe/recipe_service.py` — extended (new `handle_job_completed` method, optional `job_service` constructor param).
- `backend/lifespan.py` — extended (new job-completion subscriber, subscribed to the shared `EventBus`).
- `backend/di.py` — unchanged (the per-request `recipe_service` DI provider doesn't need `job_service`; the completion-subscriber path constructs its own `RecipeService` instance directly in `lifespan.py`, same as other lifespan-level subscribers that don't go through Dishka).

### References

- `_bmad-output/planning-artifacts/epics.md` — Epic 4, Story 4.5 (source of the ACs above).
- `_bmad-output/implementation-artifacts/4-2-ingest-a-task-graph-into-a-project.md` — `TaskLinkRow`/`TaskLinkRepository`/`RecipeService` foundation.
- `_bmad-output/implementation-artifacts/4-3-manually-assign-a-task-to-an-existing-ticket.md` — `prompt_override`/`tracker_ticket_ref` semantics.
- `_bmad-output/implementation-artifacts/4-4-see-tasklink-cards-on-the-board.md` — frontend dependency-satisfaction precedent (`computeSatisfaction`), confirms this story does not touch the frontend.
- `_bmad-output/implementation-artifacts/4-1-widen-the-task-recipe-vocabulary.md` — `spawn_task`/`chained` schema vocabulary (naming only; no dispatch wiring exists yet).
- `backend/services/runtime/service.py` (~line 1119-1124) — where `EventKind.job_completed` is published and the `resolution`-to-`JobState.completed` mapping.
- `backend/mcp/server.py` (`_register_job_tool`, `_make_job_service`) — the exact `create_job` + `setup_and_start` pattern to mirror.
- `backend/lifespan.py` (`_persist_structural_analytics`, `_persist_review_story_on_resolve`) — existing job-lifecycle-subscriber style to follow.

## Dev Agent Record

### Debug Log

- `ruff check` on all 6 changed/new files: passed (no errors).
- `mypy --ignore-missing-imports` on the 3 changed backend source files: 0 new errors (the only reported error, `lifespan.py:922`, is pre-existing/unrelated — a missing type annotation on `_on_title_update`'s parameter from an earlier subscriber this story did not touch).
- `mypy` on the 3 test files: 0 errors.
- Targeted `pytest` run — `test_task_link_repo.py` + `test_recipe_service.py` + `test_job_completion_spawns_tasklinks.py`: **31 passed**, 0 failed.
- One implementation bug caught by mypy and fixed: `Result.rowcount` isn't on the generic `Result[Any]` stub — added the same `# type: ignore[attr-defined]` pattern already used elsewhere in the repo (`approval_repo.py`, `job_repo.py`) for this exact SQLAlchemy stub gap.
- One test-authoring bug caught while writing the integration test: seeded `JobRow`s must have `resolution="merged"` set explicitly (it isn't implied by `state=JobState.completed`) for `RecipeService._is_satisfied` to treat a dependency as satisfied — the unit tests mock `job_repo.get`, but the integration test needed a real row with `resolution` populated.

### Completion Notes

- Implemented all 3 ACs via a new event-bus subscriber (`_spawn_dependent_task_links` in `backend/lifespan.py`) that reacts to `EventKind.job_completed`, checks `resolution` (only `merged`/`pr_created` count — `discarded` is explicitly excluded even though it also reaches `job.completed`), and delegates all satisfaction/spawn/idempotency logic to `RecipeService.handle_job_completed` (new method).
- `handle_job_completed` reuses `JobService.create_job` (same function `codeplane_job create` uses) and `RuntimeService.setup_and_start`, mirroring the MCP tool's own pattern — no worktree/branch logic duplicated.
- Idempotency (AC #3) is enforced at the DB layer via `TaskLinkRepository.set_job_id`'s guarded `UPDATE ... WHERE job_id IS NULL`, safe under concurrent sibling-dependency completions.
- Dependency satisfaction (AC #1/#2) is computed in-Python over the full Project TaskLink set (mirrors Story 4.4's frontend `computeSatisfaction`), never via SQL `LIKE`, to avoid composite-key substring-match bugs.
- Full test coverage added at unit (repo + service) and integration (real event bus, real sqlite session, mocked `GitService`/`RuntimeService`) levels — all 3 ACs and the "never spawns twice" / "discarded doesn't satisfy" / "no-op without job_service" edge cases are covered.
- Confirmed alembic head against `origin/main` immediately before opening the PR (see below) — no new migration needed; `job_id` column already existed from Story 4.2.
- **Excluded per scope instructions:** Story 4.6 (tracker-write routing), Story 5.3/5.4 (chat attach-to-chain / approval-gated spawn), any Epic 6 (MCP-exposed chain controls) work, and any sidecar/recipe dispatch wiring for `spawn_task` as a template output route (the trigger is the domain event bus directly, per the epics.md AC's own hint — no sidecar dispatcher was added or needed).

## File List

- `backend/persistence/task_link_repo.py` (modified) — added `get_by_job_id`, `set_job_id`.
- `backend/services/recipe/recipe_service.py` (modified) — added `handle_job_completed`, `_composite_key`, `_derive_prompt`, `_is_satisfied`, `_SUCCESSFUL_RESOLUTIONS`, optional `job_service`/`job_repo` constructor params.
- `backend/lifespan.py` (modified) — added `_spawn_dependent_task_links` event-bus subscriber.
- `backend/tests/unit/test_task_link_repo.py` (modified) — added `TestSetJobIdAndGetByJobId` (5 tests).
- `backend/tests/unit/test_recipe_service.py` (modified) — added `TestHandleJobCompleted` (9 tests) + `_make_task_link`/`_make_job` helpers.
- `backend/tests/integration/test_job_completion_spawns_tasklinks.py` (new) — end-to-end event-bus integration test (1 test).

## Change Log

- 2026-08-10: Story drafted from epics.md Epic 4 / Story 4.5 (bmad-create-story), following Story 4.4's completed precedent. Status → ready-for-dev.
- 2026-08-11: Implemented all 3 ACs (repository methods, `RecipeService.handle_job_completed`, `lifespan.py` event-bus subscriber), full unit + integration test coverage added, `ruff`/`mypy`/targeted `pytest` all clean. Status → review.
