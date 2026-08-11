---
baseline_commit: d96db821
---

# Story 5.3: Attach a Chat to a Task Recipe chain

Status: review

## Story

As a CodePlane user who would rather supervise a chain than let it run unattended,
I want to attach my Chat to a running Task Recipe chain,
So that I can narrate and watch its progress conversationally.

## Acceptance Criteria

1. **Given** an open Chat and an existing TaskLink chain, **when** I attach the Chat to that chain, **then** the Chat is linked to the chain's `task_link_id`, and if `project_id` was still null it is settled from the chain's Project at this moment.
2. **Given** a Chat attached to a chain, **when** the chain's TaskLink/Job states change, **then** the Chat's narration reflects that state via read-only polling — it never calls `GitService` or the job-creation function directly on its own.
3. **Given** a Chat attached to a chain, **when** I detach it, **then** the chain continues to exist and run exactly as before, and the Chat remains open.

## Tasks / Subtasks

- [x] Task 1: Add `task_link_id` to the Chat data model (AC: 1)
  - [x] Add nullable `task_link_id` column (FK → `task_links.id`, indexed) to `ChatRow` in `backend/models/db.py`.
  - [x] Add matching `task_link_id: str | None = None` field to the `Chat` domain dataclass in `backend/models/domain.py`.
  - [x] Add `TaskLinkNotFoundError(CodePlaneError)` to `backend/models/domain.py` (mirrors `ProjectNotFoundError`).
  - [x] Add alembic migration `0064_add_chat_task_link.py`, following on from head revision `0063_add_chat_messages.py` (re-verify the true head immediately before opening the PR — parallel stories may add migrations after this one is authored). Use `batch_alter_table` with an explicitly named foreign-key constraint (`fk_chats_task_link_id_task_links`) for SQLite batch-mode compatibility.
  - [x] Add `TaskLinkRepository.get(task_link_id) -> TaskLink | None` to `backend/persistence/task_link_repo.py`.
  - [x] Extend `ChatRepository` (`backend/persistence/chat_repo.py`) with `attach_to_chain(chat_id, task_link_id) -> Chat | None` and `detach_from_chain(chat_id) -> Chat | None`; thread `task_link_id` through `_to_domain`/`create`.
- [x] Task 2: Implement `ChatService.attach_to_chain` / `detach_from_chain` / `get_chain_status` (AC: 1, 2, 3)
  - [x] `ChatService` constructor gains optional `task_link_repo: TaskLinkRepository | None = None` and `job_repo: JobRepository | None = None` collaborators (kept optional/backward compatible with existing single-arg `ChatService(repo)` call sites and their tests).
  - [x] `attach_to_chain(chat_id, task_link_id) -> Chat | None` — returns `None` if the chat is missing; raises `TaskLinkNotFoundError` if the task_link is missing; settles `chat.project_id` from `task_link.project_id` only if `project_id` was still null; writes `task_link_id` onto the chat.
  - [x] `detach_from_chain(chat_id) -> Chat | None` — clears `task_link_id` only; the TaskLink/chain itself is never touched.
  - [x] `get_chain_status(chat_id) -> ChatChainStatus | None` — pure read: resolves the attached TaskLink (if any) and its Job (if `task_link.job_id` is set) via `TaskLinkRepository`/`JobRepository` only. Returns `None` if the chat is missing. No `GitService` import, no job-creation call — verified by the existing AST-based `TestChatIsGitFree` guard plus a dedicated "never calls JobService.create_job" test.
  - [x] Add `ChatChainStatus` dataclass (`task_link_id`, `story_node_id`, `repo_path`, `job_id`, `job_state`) to `backend/models/domain.py`.
- [x] Task 3: Expose attach/detach/chain-status over the API (AC: 1, 2, 3)
  - [x] Add `AttachChatToChainRequest` (`task_link_id`) and `ChatChainStatusResponse` (`task_link_id`, `story_node_id`, `repo_path`, `job_id`, `job_state`) to `backend/models/api_schemas.py` (both `CamelModel`); add `task_link_id: str | None = None` to `ChatResponse`.
  - [x] Add to `backend/api/chats.py`: `POST /chats/{id}/attach-chain` (404 if chat missing; propagates `TaskLinkNotFoundError` to the global 404 handler), `POST /chats/{id}/detach-chain` (404 if chat missing), `GET /chats/{id}/chain-status` (404 if chat missing). All three are thin routes — validate input, delegate to `ChatService`, return the result.
  - [x] Register a 404 exception handler for `TaskLinkNotFoundError` in `backend/app_factory.py` (mirrors the existing `ProjectNotFoundError` handler).
  - [x] Wire `TaskLinkRepository`/`JobRepository` into the `chat_service` provider in `backend/di.py`.
- [x] Task 4: Add focused tests (AC: 1, 2, 3)
  - [x] `backend/tests/unit/test_chat_service.py`: extend with `TestChatServiceAttachToChain` (settles `project_id` only when null, missing chat → `None`, missing task_link → raises `TaskLinkNotFoundError`, re-attaching to a different chain overwrites `task_link_id`), `TestChatServiceDetachFromChain` (clears `task_link_id`, chain/TaskLink itself untouched, missing chat → `None`), `TestChatServiceGetChainStatus` (reflects TaskLink/Job state, missing chat → `None`, no attached chain → status with nulls, and a guard test asserting `JobService.create_job`/`GitService` are never invoked).
  - [x] `backend/tests/integration/test_api_chats.py`: `TestAttachChatToChain` (end-to-end attach via seeded `ProjectRow`+`TaskLinkRow` fixtures, `project_id` settling, 404s for missing chat/task_link), `TestDetachChatFromChain` (detach end-to-end, chain/TaskLink left running), `TestChainStatus` (endpoint shape, reflects Job state when present, 404 for missing chat).
  - [x] Run targeted pytest (`test_chat_service.py`, `test_api_chats.py`, `test_task_link_repo.py`) + `ruff`/`mypy` on all changed files; confirm no regressions.

## Dev Notes

### Implementation Boundary

This story adds only: the `task_link_id` column/field on Chat, `ChatService.attach_to_chain`/`detach_from_chain`/`get_chain_status`, and the three new `backend/api/chats.py` routes. It does NOT implement:

- Gating CAP-10's auto-spawn behind approval (Story 5.4) — no changes to `spawn_task` or any approval/gating mechanism.
- Any new "chain" entity — a Task Recipe chain remains the existing dependency graph among `TaskLinkRow`s within a Project (via `depends_on`); the Chat simply stores a pointer (`task_link_id`) to one node in that graph, per AC1's exact wording.
- A background poller/watcher service. AC2's "read-only polling" is a client-side UI concern (a narration strip that re-fetches `GET /chats/{id}/chain-status`) — this story implements only the pure-read endpoint the frontend would poll; no polling loop was built server-side.
- `ChatPanel.tsx` or any frontend UI/narration rendering.
- Any Epic 2/3/6 work (Project CRUD, Credentials, MCP tools) beyond the pre-existing `ProjectRepository`/`TaskLinkRepository` collaborators already merged via Stories 2.1/4.2.

### Architecture Compliance (AD-12, NFR8, CAP-12)

- `attach_to_chain` and `get_chain_status` never call `GitService` or `JobService.create_job` (or any job-creation function) directly — `chat_service.py` retains **zero dependency on `GitService`**, enforced by the pre-existing AST-based `TestChatIsGitFree` guard from Story 5.1, plus a new mock-based guard test asserting `get_chain_status` never invokes job-creation.
- `project_id` settling on attach follows the same "only if still null" rule established in Story 5.2's `launch_job` — an already-settled `project_id` is left untouched.
- Detaching (AC3) only clears the Chat's own `task_link_id` field — the TaskLink row, its `depends_on` chain, and any associated Job are completely untouched; the chain "continues to exist and run exactly as before."
- Follow the existing repository-owns-DB-access convention; `ChatService` never touches SQLAlchemy sessions directly, `TaskLinkRepository`/`JobRepository` are read-only collaborators here.
- Response models use `CamelModel` for camelCase serialization, per `backend/models/api_schemas.py` conventions.
- Exception handling mirrors `ProjectNotFoundError`: `TaskLinkNotFoundError` is a `CodePlaneError` subclass raised from the service layer and caught globally via a new `app_factory.py` exception handler returning 404 — the `attach-chain` route does not catch it locally.

### Reference Implementation Pattern

- Mirror Story 5.2's `ChatService.launch_job` for the "settle `project_id` only if null" convention and for keeping `chat_service.py` git-free.
- Mirror the existing `ProjectNotFoundError` exception-handler registration pattern in `backend/app_factory.py` for `TaskLinkNotFoundError`.
- Mirror `backend/persistence/chat_repo.py`'s existing `add_message`/`set_project_id` pattern for the new `attach_to_chain`/`detach_from_chain` repository methods.
- Alembic: `alembic/versions/0063_add_chat_messages.py` is the immediate reference for the new `0064_add_chat_task_link.py` migration; use `batch_alter_table` with an explicitly named FK constraint (SQLite's batch/recreate-table strategy requires named constraints for `create_foreign_key`, unlike an inline `sa.ForeignKey(...)` passed to `add_column`, which fails with `ValueError: Constraint must have a name`).

### Project Structure Notes

Stories 5.1 (Chat entity, PR #53) and 5.2 (launch-job-from-chat, message persistence, PR #58) are merged to `main`. Story 4.2 (`TaskLinkRow`, `TaskLinkRepository`, ingestion of BMAD/spec-kit task graphs, PR #60) is also merged, providing the "Task Recipe chain" data model this story attaches to. This story builds directly on both: it adds the `task_link_id` pointer to `ChatRow`/`Chat` and a thin read-only layer over the already-existing `TaskLinkRepository`/`JobRepository`. No new "chain" entity is introduced — `depends_on` on `TaskLinkRow` already represents chain structure from Story 4.2.

### References

- [Source: `_bmad-output/planning-artifacts/epics.md#Story-53-Attach-a-Chat-to-a-Task-Recipe-chain`]
- [Source: `_bmad-output/specs/spec-project-boards/SPEC.md` CAP-12]
- [Source: `_bmad-output/planning-artifacts/architecture/architecture-codeplane-2026-08-10/ARCHITECTURE-SPINE.md#AD-12-Chat-is-one-persistent-git-free-entity`]
- [Source: `_bmad-output/implementation-artifacts/5-1-start-a-chat.md`]
- [Source: `_bmad-output/implementation-artifacts/5-2-launch-a-job-from-a-chat.md`]
- [Source: `backend/persistence/task_link_repo.py`, `backend/models/domain.py` (`TaskLink`)]
- [Source: `backend/services/chat/chat_service.py`, `backend/persistence/chat_repo.py`, `backend/api/chats.py`]
- [Source: `alembic/versions/0063_add_chat_messages.py`]

## Dev Agent Record

### Agent Model Used

Claude Sonnet 5 (GitHub Copilot CLI)

### Debug Log References

- `pytest backend/tests/unit/test_chat_service.py backend/tests/integration/test_api_chats.py backend/tests/unit/test_task_link_repo.py -q` → 63 passed.
- `ruff check backend/models/db.py backend/models/domain.py backend/models/api_schemas.py backend/persistence/chat_repo.py backend/persistence/task_link_repo.py backend/services/chat/chat_service.py backend/api/chats.py backend/app_factory.py backend/di.py backend/tests/unit/test_chat_service.py backend/tests/integration/test_api_chats.py` → all checks passed.
- `mypy` on the same changed-file set → 1 finding at `backend/api/chats.py:59` (`_job_to_create_response` missing a type annotation), confirmed pre-existing from Story 5.2 (not touched by this story's diff — the function already carried a `# noqa: ANN001` ruff suppression before this story). All other mypy findings are in unrelated pre-existing files (`project_repo.py`, `restart_protocol.py`, `credential_repo.py`, `reenrich.py`, `terminal_service.py`, `job_service.py`, `projects.py`, `lifespan.py`) and are unrelated to this story.
- Verified the alembic migration applies and reverts cleanly against a fresh SQLite DB: `alembic upgrade head` then `alembic downgrade -1`, both succeeded after fixing the initial `ValueError: Constraint must have a name` by naming the FK constraint explicitly and splitting `add_column`/`create_foreign_key` inside the batch operation.
- Re-ran `git log origin/main -- alembic/versions/` immediately before finalizing: the latest commit touching `alembic/versions/` on `origin/main` is still `d96db821` (Story 5.2, `0063_add_chat_messages.py`) — confirming `0063` remains the true head and `0064` is collision-free.

### Completion Notes List

- Added nullable, indexed `task_link_id` FK column to `ChatRow`/`Chat` and a new `TaskLinkNotFoundError`/`ChatChainStatus` to `backend/models/domain.py`.
- Added `alembic/versions/0064_add_chat_task_link.py` (down_revision `0063`) using `batch_alter_table` with an explicitly named foreign key (`fk_chats_task_link_id_task_links`) for SQLite compatibility; verified upgrade/downgrade round-trips cleanly on a fresh DB.
- Added `TaskLinkRepository.get(task_link_id)`.
- Extended `ChatRepository` with `attach_to_chain`/`detach_from_chain`, threading `task_link_id` through `_to_domain`/`create`.
- Extended `ChatService` with `attach_to_chain` (settles `project_id` only if null, raises `TaskLinkNotFoundError` for a missing task_link), `detach_from_chain` (clears only the Chat's own pointer), and `get_chain_status` (pure read via `TaskLinkRepository`/`JobRepository`, zero `GitService`/job-creation calls — the existing git-free AST guard plus a new dedicated mock-based guard test both pass).
- Added `AttachChatToChainRequest`/`ChatChainStatusResponse` and `task_link_id` on `ChatResponse` (`backend/models/api_schemas.py`).
- Added `POST /chats/{id}/attach-chain`, `POST /chats/{id}/detach-chain`, `GET /chats/{id}/chain-status` to `backend/api/chats.py` — thin routes delegating entirely to `ChatService`.
- Registered a 404 exception handler for `TaskLinkNotFoundError` in `backend/app_factory.py` (mirrors `ProjectNotFoundError`), and wired `TaskLinkRepository`/`JobRepository` into the `chat_service` DI provider in `backend/di.py`.
- Added 31 total unit tests (`TestChatServiceAttachToChain`, `TestChatServiceDetachFromChain`, `TestChatServiceGetChainStatus`) and 28 total integration tests (`TestAttachChatToChain`, `TestDetachChatFromChain`, `TestChainStatus`) to the existing chat test files — all 63 targeted tests pass.
- Did not implement Story 5.4 (approval gating), any new chain entity, a server-side polling/watcher loop, or `ChatPanel.tsx`/frontend UI — all explicitly out of this story's scope per the Implementation Boundary.

### File List

- `backend/models/db.py` (modified — added `ChatRow.task_link_id` column + `ix_chats_task_link_id` index)
- `backend/models/domain.py` (modified — added `Chat.task_link_id`, `TaskLinkNotFoundError`, `ChatChainStatus`)
- `backend/persistence/task_link_repo.py` (modified — added `TaskLinkRepository.get`)
- `backend/persistence/chat_repo.py` (modified — added `attach_to_chain`, `detach_from_chain`; threaded `task_link_id`)
- `backend/services/chat/chat_service.py` (modified — added `attach_to_chain`, `detach_from_chain`, `get_chain_status`)
- `backend/models/api_schemas.py` (modified — added `AttachChatToChainRequest`, `ChatChainStatusResponse`, `ChatResponse.task_link_id`)
- `backend/api/chats.py` (modified — added `POST /chats/{id}/attach-chain`, `POST /chats/{id}/detach-chain`, `GET /chats/{id}/chain-status`)
- `backend/app_factory.py` (modified — added `TaskLinkNotFoundError` 404 exception handler)
- `backend/di.py` (modified — wired `TaskLinkRepository`/`JobRepository` into `chat_service` provider)
- `alembic/versions/0064_add_chat_task_link.py` (new)
- `backend/tests/unit/test_chat_service.py` (modified — added `TestChatServiceAttachToChain`, `TestChatServiceDetachFromChain`, `TestChatServiceGetChainStatus`)
- `backend/tests/integration/test_api_chats.py` (modified — added `TestAttachChatToChain`, `TestDetachChatFromChain`, `TestChainStatus`, plus a `_seed_project_and_task_link` fixture helper)
- `_bmad-output/implementation-artifacts/sprint-status.yaml` (modified — `5-3-attach-a-chat-to-a-task-recipe-chain` → review)
- `_bmad-output/implementation-artifacts/5-3-attach-a-chat-to-a-task-recipe-chain.md` (new — this story file)

## Change Log

- 2026-08-10: Story created, marked ready-for-dev.
- 2026-08-10: Implementation complete — `task_link_id` attach/detach/chain-status added to Chat, `ChatService` extended with `attach_to_chain`/`detach_from_chain`/`get_chain_status` (zero `GitService`/job-creation dependency retained), three new thin API routes, migration `0064_add_chat_task_link.py` (verified upgrade/downgrade), and full test coverage (63 targeted tests passing). Confirmed `0063` remains the true alembic head on `origin/main` immediately before finalizing. Status set to review.
