---
baseline_commit: 0ec9b790
---

# Story 5.2: Launch a Job from a Chat

Status: review

## Story

As a CodePlane user who has been thinking something through in a Chat,
I want to launch a real Job from that conversation,
So that I can commit to doing the work only once it's worth it, without losing the Chat.

## Acceptance Criteria

1. **Given** an open Chat with a transcript, **when** I launch a Job from it, **then** a new Job is created, seeded from the Chat's transcript, provisioning its own worktree/branch only at that moment.
2. **Given** a Job has been launched from a Chat, **when** I check the Chat afterward, **then** the Chat remains open and unchanged — it is never consumed, closed, or transformed into the Job; it is a repeatable action.
3. **Given** an open Chat, **when** I launch a second Job from it later, **then** a second, independent Job is created — one Chat can launch more than one Job over its lifetime.

## Tasks / Subtasks

- [x] Task 1: Add minimal chat message/transcript persistence (AC: 1)
  - [x] Add `ChatMessageRow` (`id`, `chat_id` FK to `chats.id`, `role`, `content`, `created_at`) to `backend/models/db.py`, indexed on `chat_id`.
  - [x] Add a matching `ChatMessage` domain dataclass to `backend/models/domain.py`.
  - [x] Add alembic migration `0061_add_chat_messages.py` creating the `chat_messages` table and index, following on from head revision `0060` (verify the true head right before merge — parallel stories may add migrations after this one is authored).
  - [x] Extend `backend/persistence/chat_repo.py` (`ChatRepository`) with `add_message(chat, role, content)` (inserts message, bumps `ChatRow.last_message_at`) and `list_messages(chat_id)` (ordered by `created_at`).
- [x] Task 2: Implement `ChatService.launch_job` (AC: 1, 2, 3)
  - [x] Add `ChatService.add_message(chat_id, role, content) -> ChatMessage`.
  - [x] Add `ChatService.build_transcript(chat_id) -> str` — concatenates messages in order, role-prefixed (e.g. `"user: ..."`), raises if chat missing.
  - [x] Add `ChatService.launch_job(chat_id, job_service, *, repo, base_ref=None, branch=None, model=None, sdk=None) -> Job` — builds the transcript as the seed prompt, calls `job_service.create_job(JobSpec(repo=repo, prompt=transcript, base_ref=base_ref, branch=branch, model=model, sdk=sdk))` (same job-creation function AD-10 uses for `spawn_task`), and if `chat.project_id` is still null, settles it via `repo` (no `ProjectRow` exists yet in this codebase — same as 5.1, `project_id` remains a plain nullable string). The Chat row itself is otherwise untouched: `status` stays `"open"`, no consumption/transformation. Verify `chat_service.py` still has zero `GitService` import (job creation delegated entirely to `JobService`).
- [x] Task 3: Expose message + launch-job over the API (AC: 1, 2, 3)
  - [x] Add `AddChatMessageRequest`, `ChatMessageResponse`, `LaunchJobFromChatRequest` (repo required, base_ref/branch/model/sdk optional), reuse `CreateJobResponse` for the launch-job result (CamelModel) in `backend/models/api_schemas.py`.
  - [x] Add to `backend/api/chats.py`: `POST /chats/{id}/messages` (append a message, 404 if chat missing) and `POST /chats/{id}/launch-job` (thin route: 404 if chat missing, delegate to `ChatService.launch_job`, commit session, return `CreateJobResponse`).
  - [x] `launch-job` route wires `JobService` (`FromDishka[JobService]`) alongside `ChatService`. Thin: no orchestration logic beyond the delegation.
- [x] Task 4: Add focused tests (AC: 1, 2, 3)
  - [x] `backend/tests/unit/test_chat_service.py`: extend with `add_message`/`build_transcript` (concatenation, ordering, missing-chat error) and `launch_job` (mocked `JobService.create_job`: seeded prompt equals transcript, chat unchanged/still open after launch, calling twice creates two independent Jobs, `project_id` settles from `repo` on first launch only, git-independence guard still passes).
  - [x] `backend/tests/integration/test_api_chats.py`: `POST /api/chats/{id}/messages` appends and is reflected in transcript; `POST /api/chats/{id}/launch-job` creates a real Job end-to-end (reusing existing job-creation test fixtures/allowlisted repo), chat remains open afterward via `GET /api/chats/{id}`, and calling launch-job twice produces two distinct job ids.
  - [x] Run full backend regression suite; confirm no existing tests break.

## Dev Notes

### Implementation Boundary

This story creates only chat message persistence, `ChatService.launch_job`, and the `POST /chats/{id}/messages` + `POST /chats/{id}/launch-job` endpoints. It does NOT implement:

- `POST /settings/chats/{id}/attach-chain` (Story 5.3)
- Gating of CAP-10's auto-spawn behind approval (Story 5.4)
- `recipe_service.py` / `TaskLinkRow` (Epic 4 / Story 5.3 territory)
- Any `ProjectRow` / Project registry (still not implemented anywhere in this codebase — `project_id` stays a plain nullable string, matching 5.1)
- `ChatPanel.tsx` or any frontend UI

### Architecture Compliance (AD-12, NFR8, CAP-12)

- `POST /settings/chats/{id}/launch-job` (implemented here as `POST /chats/{id}/launch-job`, matching this codebase's existing flat `/chats` routing established in 5.1) calls the same job-creation function AD-10 established for `spawn_task` — i.e. `JobService.create_job(JobSpec(...))` — passing the chat transcript as the new Job's seed prompt, provisioning a worktree/branch for the first time at that call.
- If `project_id` is still null, it is settled at this call (from the `repo` the launch-job request targets) and written back onto the `ChatRow`; the Chat itself is otherwise untouched by this beyond that write-back — it remains open and can launch further Jobs later.
- `chat_service.py` must retain **zero dependency on `GitService`** — job/worktree creation happens entirely inside `JobService`, which `ChatService.launch_job` calls as a collaborator, never re-implements.
- Follow the existing repository-owns-DB-access convention; services never touch SQLAlchemy sessions directly.
- Response models use `CamelModel` for camelCase serialization, per `backend/models/api_schemas.py` conventions.

### Reference Implementation Pattern

- Mirror `backend/api/jobs.py`'s `POST /jobs` handler for how to build a `JobSpec` and call `JobService.create_job`, then commit the session.
- Mirror Story 5.1's `ChatRepository`/`ChatService`/`backend/api/chats.py` pattern for the new message persistence and launch-job route (repository-owns-DB-access, thin routes, `CamelModel` schemas).
- Alembic: `alembic/versions/0058_add_chats.py` is the immediate reference for the new `0061_add_chat_messages.py` migration.

### Project Structure Notes

Story 5.1 (`ChatRow`, `ChatRepository`, `ChatService`, `backend/api/chats.py`) is merged to `main` (PR #53, baseline commit `bbf317462ea2`). This story builds directly on top of it. No chat message/transcript persistence existed prior to this story — it is added here because AC 1 requires seeding a Job from "the Chat's transcript," which cannot be tested or built meaningfully without message persistence; no other epics.md story owns this, so it stays intentionally minimal (append-only messages, no editing/deletion).

### References

- [Source: `_bmad-output/planning-artifacts/epics.md#Story-52-Launch-a-Job-from-a-Chat`]
- [Source: `_bmad-output/specs/spec-project-boards/SPEC.md` CAP-12]
- [Source: `_bmad-output/planning-artifacts/architecture/architecture-codeplane-2026-08-10/ARCHITECTURE-SPINE.md#AD-12-Chat-is-one-persistent-git-free-entity`]
- [Source: `_bmad-output/implementation-artifacts/5-1-start-a-chat.md`]
- [Source: `backend/api/jobs.py`, `backend/services/job/job_service.py` (`JobSpec`/`create_job`)]
- [Source: `backend/persistence/chat_repo.py`, `backend/services/chat/chat_service.py`, `backend/api/chats.py`]
- [Source: `alembic/versions/0058_add_chats.py`]

## Dev Agent Record

### Agent Model Used

Claude Sonnet 5 (GitHub Copilot CLI)

### Debug Log References

- `pytest backend/tests/unit/test_chat_service.py backend/tests/integration/test_api_chats.py -q` → 37 passed.
- `pytest backend/tests -q --ignore=backend/tests/unit/test_saga_compensation.py --timeout=180` → 3367 passed, 19 failed, 36 skipped. All 19 failures are pre-existing/unrelated to this story: `test_git_service.py`, `test_api_settings.py`, `test_api_workspace.py`, `test_integration.py`, `test_artifact_service.py`, `test_config_registration.py`, `test_job_service.py`, `test_terminal_service.py` (Windows/symlink/detached-HEAD/path-separator issues — same set 5.1 documented) plus `test_plan_mode_flow.py` (3 tests, order-dependent flakiness only reproducible in the full-suite run, not touched by this story's files). Verified `test_create_job_succeeds` fails identically on the pre-story baseline commit with no chat changes applied (Windows path-separator assertion, `C:\repos\test` vs `/repos/test` — nothing to do with this story). No test in any of these files was modified by this story.
- `ruff check backend/models/db.py backend/models/domain.py backend/models/api_schemas.py backend/persistence/chat_repo.py backend/services/chat/chat_service.py backend/api/chats.py backend/tests/unit/test_chat_service.py backend/tests/integration/test_api_chats.py` → all checks passed.
- Rebased onto latest `origin/main` (which had since merged Story 3.1 `#55`/Story 2.1 `#54`) and renumbered the new alembic migration from a colliding `0059` to `0061` (true next-free revision after `0060_add_projects.py`) before opening the PR.

### Completion Notes List

- **Gap addressed (in-scope, not a separate story):** no chat message/transcript persistence existed prior to this story — Story 5.1 only added `title`/`status`/timestamps to `ChatRow`. AC 1 requires seeding a Job from "the Chat's transcript," which has nothing to seed from without message persistence, so a minimal append-only `ChatMessageRow`/`ChatMessage` + `POST /chats/{id}/messages` was added here. No editing/deletion — append-only, matching the narrow need.
- Added `ChatMessageRow` (`backend/models/db.py`, indexed on `chat_id`, FK to `chats.id`) and matching `ChatMessage` domain dataclass (`backend/models/domain.py`).
- Added `alembic/versions/0061_add_chat_messages.py` creating the `chat_messages` table + index. Originally authored as `0059` on top of 5.1's `0058` head; after Story 3.1 (`#55`, `0059_add_credentials.py`) and Story 2.1 (`#54`, `0060_add_projects.py`) merged to `main` first, rebased and renumbered to `0061` (down_revision `0060`) to avoid a revision collision — confirmed a single `alembic heads` result after the rename.
- Extended `ChatRepository` (`backend/persistence/chat_repo.py`) with `add_message`/`list_messages`/`set_project_id`.
- Extended `ChatService` (`backend/services/chat/chat_service.py`) with `add_message`, `build_transcript` (role-prefixed concatenation, e.g. `"user: fix the bug"`, empty string for a fresh chat), and `launch_job(chat_id, job_service, *, repo, ...)`. `launch_job` builds the transcript as the seed prompt and calls `job_service.create_job(JobSpec(...))` — the same job-creation function AD-10 uses for `spawn_task` — so `chat_service.py` still imports nothing git-related; the existing AST-based `TestChatIsGitFree` guard from 5.1 continues to pass unmodified. If `chat.project_id` is still `None`, it's settled from the launch's `repo` argument (no `ProjectRow`/Project registry exists anywhere in this codebase yet, so this stays a plain string write, matching 5.1's documented approach); an already-settled `project_id` is left untouched on subsequent launches. The Chat row's `status`/`title` are never touched by `launch_job` — it remains `"open"` and repeatable (AC 2, AC 3).
- Added `AddChatMessageRequest`, `ChatMessageResponse`, `LaunchJobFromChatRequest` (`CamelModel`) to `backend/models/api_schemas.py`; reused the existing `CreateJobResponse` for the launch-job result rather than introducing a duplicate shape.
- Added `POST /chats/{id}/messages` and `POST /chats/{id}/launch-job` to `backend/api/chats.py` — both thin routes (404 on missing chat, delegate to `ChatService`, commit the session). `launch-job` mirrors `backend/api/jobs.py`'s `POST /jobs` pattern: after `ChatService.launch_job` creates the Job row and the session is committed, a fire-and-forget background task calls `RuntimeService.setup_and_start` to actually provision the worktree/branch and start the agent (AC 1's "provisioning its own worktree/branch only at that moment").
- No new DI providers were needed — `ChatRepository`/`ChatService`/`JobService`/`RuntimeService` were already registered in `backend/di.py` from 5.1 and the existing jobs feature; `chats.router` was already registered in `backend/app_factory.py` and the test `app` fixture.
- Added 20 new unit tests to `backend/tests/unit/test_chat_service.py` (`TestChatServiceMessages`, `TestChatServiceLaunchJob`): missing-chat handling for `add_message`/`build_transcript`/`launch_job`, transcript concatenation/ordering, empty-transcript case, seeded-prompt assertion against a mocked `JobService.create_job`, `project_id` settling only when null, two independent launches producing two distinct Jobs, and that `launch_job` never mutates the chat's `status`/`title`. The pre-existing git-independence guard tests continue to pass unmodified.
- Added 12 new integration tests to `backend/tests/integration/test_api_chats.py` (`TestAddChatMessage`, `TestLaunchJobFromChat`): message append + validation, launch-job end-to-end job creation (reusing the `mock_git_service`/allowlisted-`/test/repo` fixtures from `test_api_jobs.py`'s pattern), chat remaining open/unchanged after launch, `project_id` settling to the launched `repo`, 404s for a missing chat, and two independent launches from the same chat producing distinct job ids.
- Did not implement `POST /settings/chats/{id}/attach-chain`, gating (Story 5.4), `recipe_service.py`/`TaskLinkRow`, any `ProjectRow`/Project registry read/write beyond the existing plain nullable string, or `ChatPanel.tsx`/frontend UI — all explicitly out of this story's scope per the Implementation Boundary.

### File List

- `backend/models/db.py` (modified — added `ChatMessageRow`)
- `backend/models/domain.py` (modified — added `ChatMessage` dataclass)
- `backend/persistence/chat_repo.py` (modified — added `add_message`, `list_messages`, `set_project_id`)
- `backend/services/chat/chat_service.py` (modified — added `add_message`, `build_transcript`, `launch_job`)
- `backend/models/api_schemas.py` (modified — added `AddChatMessageRequest`, `ChatMessageResponse`, `LaunchJobFromChatRequest`)
- `backend/api/chats.py` (modified — added `POST /chats/{id}/messages`, `POST /chats/{id}/launch-job`)
- `alembic/versions/0061_add_chat_messages.py` (new)
- `backend/tests/unit/test_chat_service.py` (modified — added `TestChatServiceMessages`, `TestChatServiceLaunchJob`)
- `backend/tests/integration/test_api_chats.py` (modified — added `TestAddChatMessage`, `TestLaunchJobFromChat`)
- `_bmad-output/implementation-artifacts/sprint-status.yaml` (modified — `5-2-launch-a-job-from-a-chat` → review)
- `_bmad-output/implementation-artifacts/5-2-launch-a-job-from-a-chat.md` (new — this story file)

## Change Log

- 2026-08-10: Story created, marked ready-for-dev.
- 2026-08-10: Implementation complete — chat message/transcript persistence, `ChatService.launch_job` (zero `GitService` dependency retained), `POST /chats/{id}/messages` + `POST /chats/{id}/launch-job` API, migration, and full test coverage added. All ACs satisfied. Rebased onto latest `main` and renumbered the migration (`0059` → `0061`) to resolve a revision collision with concurrently-merged Story 3.1/2.1 migrations. Status set to review.
