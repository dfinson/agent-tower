---
baseline_commit: eb2d25b4
---

# Story 5.4: Gate a chain's auto-spawn behind approval

Status: review

## Story

As a CodePlane user supervising a chain via an attached Chat,
I want the chain's next step to require my approval instead of starting automatically,
So that I stay in control of a chain I'm actively watching.

## Acceptance Criteria

1. **Given** a TaskLink chain with an attached Chat in gating mode, **when** a dependent TaskLink's dependencies become satisfied, **then** `spawn_task` creates a `codeplane_approval` entry (the same mechanism AD-7/CAP-11 already use) instead of calling the job-creation service directly, and only calls it once that approval is granted.
2. **Given** a TaskLink chain with no attached Chat, **when** a dependent TaskLink's dependencies become satisfied, **then** the existing ungated auto-spawn behavior (Story 4.5) is completely unchanged — attaching a Chat is what switches a specific chain into gated mode, nothing else does.
3. **Given** a gated chain's approval is rejected, **when** I check the chain afterward, **then** the next TaskLink is never spawned, and the chain remains stalled at that point until a manual retry or a new approval.

## Tasks / Subtasks

- [x] Task 1: Add a Project-level "is this chain gated" read (AC: 1, 2)
  - [x] Add `ChatRepository.get_attached_open_chat_for_project(project_id) -> Chat | None` in `backend/persistence/chat_repo.py`: selects a `ChatRow` with matching `project_id`, non-null `task_link_id`, and `status == "open"` (an attached-but-archived/closed Chat never gates); returns the first match (attach/detach is a 1:1-in-practice relationship per Story 5.3, so "any" attached open Chat in the Project is sufficient to gate the whole Project's chain).
  - [x] No schema change — reuses the existing `task_link_id`/`status`/`project_id` columns from Stories 5.1/5.3.
- [x] Task 2: Gate `RecipeService.handle_job_completed`'s spawn behind an approval (AC: 1, 2, 3)
  - [x] `RecipeService.__init__` gains one more optional collaborator: `chat_repo: ChatRepository | None = None` (mirrors the existing optional `job_service`/`job_repo` pattern — request-scoped call sites that never spawn/gate don't need it).
  - [x] `RecipeService` gains an optional `approval_service: ApprovalService | None = None` collaborator (same optionality pattern) — needed to create the `codeplane_approval` entry.
  - [x] In `handle_job_completed`, before spawning a satisfied candidate: if `self._chat_repo` is set, look up `get_attached_open_chat_for_project(candidate.project_id)`. If an open attached Chat exists (gated) **and** `self._approval_service` is set, call `approval_service.create_request(job_id=job_id, description=..., proposed_action=f"spawn_task:{candidate.id}")` instead of `job_service.create_job(...)`; do **not** call `set_job_id` (the TaskLink stays `job_id=None` until approved). If ungated (no attached open Chat, or `chat_repo`/`approval_service` not supplied), fall through to the exact existing immediate-spawn path — byte-for-byte unchanged (AC #2).
  - [x] Never create a second approval for the same candidate on a repeat pass: skip candidates that already have a pending approval whose `proposed_action == f"spawn_task:{candidate.id}"` (checked via `approval_service.list_pending()` filtered client-side, since approvals aren't project-scoped) so a chain with multiple simultaneously-satisfied dependents, or repeated event-bus deliveries, never double-requests.
- [x] Task 3: Add `RecipeService.spawn_approved_task_link` and wire it from the approval-resolve path (AC: 1, 3)
  - [x] `async def spawn_approved_task_link(self, task_link_id: str, *, parent_job_id: str | None) -> Job | None` in `RecipeService`: loads the `TaskLink`; returns `None` (no-op, idempotent) if it doesn't exist or already has a `job_id`; otherwise creates the job via the same `JobService.create_job(JobSpec(repo=..., prompt=..., parent_job_id=...))` call `handle_job_completed` already uses, persists `job_id` via `TaskLinkRepository.set_job_id`, and returns the new `Job` (or `None` if `set_job_id` lost a race).
  - [x] In `backend/api/approvals.py`'s `resolve_approval` route: after `approval_service.resolve(...)` succeeds, if the resolution is `approved` and `approval.proposed_action` starts with `"spawn_task:"`, extract the `task_link_id` suffix, call `recipe_service.spawn_approved_task_link(task_link_id, parent_job_id=approval.job_id)`, and if a Job was spawned, fire-and-forget `runtime_service.setup_and_start(job)` (mirrors the existing `lifespan.py` Story 4.5 subscriber's own spawn-and-start pattern) so the route itself doesn't block on session startup.
  - [x] On **rejection** (AC #3): no additional code path is needed — the TaskLink's `job_id` simply stays `None` forever until a later event re-evaluates its dependencies (a sibling dependency completing again) and creates a **new**, independent approval, which is exactly "a new approval" per the AC's wording. Add a regression test proving a rejected approval never spawns a job and the TaskLink is unaffected.
- [x] Task 4: Wire the new collaborators through DI and the Story 4.5 event-bus subscriber (AC: 1, 2)
  - [x] Extend the `recipe_service` provider in `backend/di.py` to also inject `JobService`, `JobRepository`, `ChatRepository`, and `ApprovalService` (all already provided elsewhere in the container) into `RecipeService(...)`, so the DI-resolved instance used by `backend/api/approvals.py` can both gate and spawn.
  - [x] Thread a `ChatRepository(session)` and the app's shared `ApprovalService` singleton into the manually-constructed `RecipeService` inside `backend/lifespan.py`'s `_spawn_dependent_task_links` closure (the Story 4.5 event-bus subscriber), alongside its existing `job_service`/`job_repo`.
- [x] Task 5: Add focused tests (AC: 1, 2, 3)
  - [x] `backend/tests/unit/test_chat_repo.py` (or the existing chat repo test module): `get_attached_open_chat_for_project` returns the attached open Chat, returns `None` when no Chat is attached, returns `None` when the attached Chat's `status != "open"`, returns `None` for a different Project.
  - [x] `backend/tests/unit/test_recipe_service.py`: extend with a `TestHandleJobCompletedGating` class — gated chain (attached open Chat) creates an approval instead of spawning (job_id stays None, approval created with matching `proposed_action`); ungated chain (no attached Chat, or a detached/closed one) spawns exactly as Story 4.5's existing tests assert, unchanged; a repeat `handle_job_completed` pass while an approval is already pending does not create a duplicate approval; and a `TestSpawnApprovedTaskLink` class — spawns and sets `job_id` when the TaskLink has none, is a no-op returning `None` when the TaskLink already has a `job_id` (idempotency), and is a no-op returning `None` for an unknown `task_link_id`.
  - [x] `backend/tests/integration/test_api_approvals.py`: extend with a test that resolves a `spawn_task:` approval as `approved` and asserts a new Job now exists with `parent_job_id` set and the TaskLink's `job_id` populated; and a test that resolves it `rejected` and asserts no Job is created and the TaskLink's `job_id` remains `None`.
  - [x] `backend/tests/integration/test_job_completion_spawns_tasklinks.py`: extend with an end-to-end case — Project has an attached open Chat, a dependent TaskLink's dependency completes, assert a pending approval now exists and the dependent TaskLink still has no `job_id`; then resolve that approval and assert the Job is created and started.
  - [x] Run targeted pytest (`test_chat_repo.py`, `test_recipe_service.py`, `test_api_approvals.py`, `test_job_completion_spawns_tasklinks.py`) + `ruff`/`mypy` on all changed files; confirm no regressions.

## Dev Notes

### Implementation Boundary

This story adds only: the Project-level "gated by an attached open Chat" read, the two-phase gate/spawn split in `RecipeService` (`handle_job_completed` creates an approval instead of spawning when gated; new `spawn_approved_task_link` performs the deferred spawn once approved), and the dispatch wiring in the existing `POST /api/approvals/{id}/resolve` route. It does NOT implement:

- Story 4.6 (tracker-write routing) — untouched.
- Any Epic 6 work (`codeplane_tracker`, `codeplane_pr` MCP tools) — untouched.
- A new "gating mode" flag/column on `Chat`/`ChatRow`/`TaskLink`/`TaskLinkRow` — gating is derived purely from an attached, open Chat existing for the Project, per AC #2's exact wording ("attaching a Chat is what switches ... nothing else does"). No alembic migration is needed.
- Any new "chain" entity — as in Story 5.3, a chain remains the existing `depends_on` graph among a Project's `TaskLinkRow`s; gating is evaluated per-Project, since that is the only existing scope both `TaskLink` and `Chat` share.
- Any frontend UI (chain-status narration, approve/reject affordance) beyond the pre-existing `codeplane_approval` UI, which already renders any `Approval` row regardless of what created it (per Epic 5's own note that a `tracker_write`-created approval "behaves identically to any other `codeplane_approval` entry — same UI, same resolution path"; this story's `spawn_task:`-created approvals get the same treatment for free).

### Architecture Compliance (AD-7, AD-9, AD-12, CAP-11, NFR8)

- Reuses the exact same `codeplane_approval` mechanism (`ApprovalService.create_request` / `.resolve`) that AD-7/CAP-11 already use for other gate-tier actions — no parallel approval concept is introduced, satisfying AC #1's explicit requirement.
- The two-phase split (create approval in `handle_job_completed`, defer the actual `JobService.create_job` call to a new `spawn_approved_task_link` invoked from the approval-resolve route) avoids holding any `serialized_write` transaction open while awaiting an operator decision — `handle_job_completed` already runs inside `lifespan.py`'s `serialized_write` block for Story 4.5, and a blocking `await approval_service.wait_for_resolution(...)` there would starve that write lock indefinitely.
- Ungated behavior is provably byte-identical to Story 4.5: the gating check is a pure early-branch guarded by `chat_repo is not None` and an attached-open-Chat lookup; when either is absent, control falls through to the pre-existing `job_service.create_job(...)` + `set_job_id(...)` lines untouched.
- `ChatService`/`chat_repo.py` remain zero-`GitService`-dependency (AD-12, NFR8) — the new `get_attached_open_chat_for_project` query is a plain read, no git operation, consistent with Story 5.1/5.3's structural guarantee (verified by the pre-existing AST-based `TestChatIsGitFree` guard, which this story does not touch or need to extend since it only reads `ChatRepository`, never imports `GitService`).
- `RecipeService`'s existing idempotency invariant ("one TaskLink points at zero-or-one real Job, never more", Story 4.5 AC #3) is preserved by `spawn_approved_task_link`'s own guard (no-op if `job_id` already set) exactly mirroring `set_job_id`'s existing `UPDATE ... WHERE job_id IS NULL` semantics.
- Route handlers stay thin: `backend/api/approvals.py`'s `resolve_approval` only validates the resolution outcome/proposed_action shape and delegates spawn orchestration entirely to `RecipeService`.

### Reference Implementation Pattern

- Mirror Story 4.5's existing `handle_job_completed` spawn loop (`backend/services/recipe/recipe_service.py`) for the dependency-satisfaction check and the `JobService.create_job` + `TaskLinkRepository.set_job_id` call shape — `spawn_approved_task_link` reuses that exact call shape for the deferred-spawn path.
- Mirror `backend/services/runtime/service.py::_handle_plan_session_completed`'s existing pattern of calling `approval_service.create_request(job_id=..., proposed_action=..., ...)` to raise a synthetic approval gate, and `lifespan.py`'s `_spawn_dependent_task_links` closure's fire-and-forget `runtime_service.setup_and_start(job)` pattern for starting a newly-spawned job's agent without blocking the caller.
- Mirror Story 5.3's `ChatRepository.attach_to_chain`/`detach_from_chain` query style (`select(ChatRow).where(...)`) for the new `get_attached_open_chat_for_project` read.
- Mirror `backend/api/approvals.py`'s existing `resolve_approval` route for the thin-route/delegate-to-service convention when adding the `spawn_task:` dispatch.

### Project Structure Notes

Story 4.5 (`RecipeService.handle_job_completed`, auto-spawn via `EventKind.job_completed`, PR merged to `main`) and Story 5.3 (`ChatRow.task_link_id`, `ChatService.attach_to_chain`/`detach_from_chain`/`get_chain_status`, `chain-status` endpoints, PR #67 merged to `main`) are the two prerequisites this story builds directly on top of. No new persistence entity or migration is introduced — this story is a pure behavioral gate inserted between "dependency satisfied" (already detected by 4.5) and "job created" (already performed by 4.5), keyed off whether a Chat is attached to the same Project (already modeled by 5.3).

### References

- [Source: `_bmad-output/planning-artifacts/epics.md#Story-54-Gate-a-chains-auto-spawn-behind-approval`]
- [Source: `_bmad-output/specs/spec-project-boards/SPEC.md` AD-7, CAP-11]
- [Source: `_bmad-output/implementation-artifacts/4-5-auto-spawn-the-next-task-on-completion.md`]
- [Source: `_bmad-output/implementation-artifacts/5-3-attach-a-chat-to-a-task-recipe-chain.md`]
- [Source: `backend/services/recipe/recipe_service.py`, `backend/persistence/task_link_repo.py`]
- [Source: `backend/services/chat/chat_service.py`, `backend/persistence/chat_repo.py`]
- [Source: `backend/services/job/approval_service.py`, `backend/api/approvals.py`]
- [Source: `backend/services/runtime/service.py::_handle_plan_session_completed` (existing synthetic-approval-gate pattern)]
- [Source: `backend/lifespan.py::_spawn_dependent_task_links` (existing Story 4.5 event-bus subscriber)]

## Dev Agent Record

### Agent Model Used

Claude Sonnet 5 (GitHub Copilot CLI)

### Debug Log References

- Ran targeted pytest via `uv run --no-sync pytest` pointed at the pre-built venv (network access to PyPI was unavailable in the worktree for `uv sync`).
- `backend/tests/unit/test_recipe_service.py`: 27 passed (19 pre-existing Story 4.5 tests unchanged + 8 new Story 5.4 gating/spawn tests).
- `backend/tests/unit/test_chat_repo.py`: 5 passed (new).
- `backend/tests/integration/test_api_approvals.py`: 18 passed (16 pre-existing + 2 new gated approve/reject tests).
- `backend/tests/integration/test_job_completion_spawns_tasklinks.py`: 2 passed (1 pre-existing ungated + 1 new gated end-to-end test).
- `ruff check` and `mypy` run against every changed file; no new findings versus the pre-change baseline (verified via `git stash` diff on `mypy` output).

### Completion Notes List

- Implemented gating as a pure derived read: a Project is "gated" iff it has at least one Chat with a non-null `task_link_id` and `status == "open"` attached anywhere among its TaskLinks (`ChatRepository.get_attached_open_chat_for_project`). No schema/migration change.
- `RecipeService.handle_job_completed` (Story 4.5) now branches on `_is_chain_gated`: gated candidates get a `codeplane_approval` (`proposed_action="spawn_task:{task_link_id}"`) instead of an immediate spawn; a per-invocation `list_pending()` scan prevents duplicate approvals for the same candidate. Ungated behavior is provably unchanged — the existing `job_service.create_job` + `set_job_id` path is untouched when `chat_repo`/`approval_service` are absent or no open Chat is attached.
- Added `RecipeService.spawn_approved_task_link(task_link_id, *, parent_job_id)` — idempotent deferred spawn (no-op if the TaskLink already has a `job_id` or doesn't exist), reusing the same `JobSpec` + `set_job_id` call shape as the immediate-spawn path.
- Wired `POST /api/approvals/{id}/resolve` to call `spawn_approved_task_link` and fire-and-forget `runtime_service.setup_and_start` when an approved resolution's `proposed_action` starts with `spawn_task:`. Rejection needs no additional code — the TaskLink simply keeps `job_id = None`.
- Extended `backend/di.py`'s `recipe_service` provider and `backend/lifespan.py`'s `_spawn_dependent_task_links` closure to supply the new `chat_repo`/`approval_service` collaborators.
- Explicitly excluded (out of scope per instructions): Story 4.6 (tracker-write routing) and all of Epic 6 — neither was touched.

### File List

- `_bmad-output/implementation-artifacts/5-4-gate-a-chains-auto-spawn-behind-approval.md` (new)
- `_bmad-output/implementation-artifacts/sprint-status.yaml` (modified)
- `backend/persistence/chat_repo.py` (modified)
- `backend/services/recipe/recipe_service.py` (modified)
- `backend/api/approvals.py` (modified)
- `backend/di.py` (modified)
- `backend/lifespan.py` (modified)
- `backend/tests/unit/test_chat_repo.py` (new)
- `backend/tests/unit/test_recipe_service.py` (modified)
- `backend/tests/integration/test_api_approvals.py` (modified)
- `backend/tests/integration/test_job_completion_spawns_tasklinks.py` (modified)

## Change Log

- 2026-08-12: Story created, marked ready-for-dev.
- 2026-08-12: Implementation complete — gating read, two-phase spawn/approval split, approvals-route dispatch, DI/lifespan wiring, full test coverage (unit + integration). Marked review.
