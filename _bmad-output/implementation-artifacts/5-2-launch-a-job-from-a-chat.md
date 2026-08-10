---
baseline_commit: 0ec9b790
---

# Story 5.2: Launch a Job from a Chat

Status: ready-for-dev

## Story

As a CodePlane user who has been thinking something through in a Chat,
I want to launch a real Job from that conversation,
So that I can commit to doing the work only once it's worth it, without losing the Chat.

## Acceptance Criteria

1. **Given** an open Chat with a transcript, **when** I launch a Job from it, **then** a new Job is created, seeded from the Chat's transcript, provisioning its own worktree/branch only at that moment.
2. **Given** a Job has been launched from a Chat, **when** I check the Chat afterward, **then** the Chat remains open and unchanged — it is never consumed, closed, or transformed into the Job; it is a repeatable action.
3. **Given** an open Chat, **when** I launch a second Job from it later, **then** a second, independent Job is created — one Chat can launch more than one Job over its lifetime.

## Tasks / Subtasks

- [ ] Task 1: Add minimal chat message/transcript persistence (AC: 1)
  - [ ] Add `ChatMessageRow` (`id`, `chat_id` FK to `chats.id`, `role`, `content`, `created_at`) to `backend/models/db.py`, indexed on `chat_id`.
  - [ ] Add a matching `ChatMessage` domain dataclass to `backend/models/domain.py`.
  - [ ] Add alembic migration `0059_add_chat_messages.py` creating the `chat_messages` table and index, following on from head revision `0058`.
  - [ ] Extend `backend/persistence/chat_repo.py` (`ChatRepository`) with `add_message(chat, role, content)` (inserts message, bumps `ChatRow.last_message_at`) and `list_messages(chat_id)` (ordered by `created_at`).
- [ ] Task 2: Implement `ChatService.launch_job` (AC: 1, 2, 3)
  - [ ] Add `ChatService.add_message(chat_id, role, content) -> ChatMessage`.
  - [ ] Add `ChatService.build_transcript(chat_id) -> str` — concatenates messages in order, role-prefixed (e.g. `"user: ..."`), raises if chat missing.
  - [ ] Add `ChatService.launch_job(chat_id, job_service, *, repo, base_ref=None, branch=None, model=None, sdk=None) -> Job` — builds the transcript as the seed prompt, calls `job_service.create_job(JobSpec(repo=repo, prompt=transcript, base_ref=base_ref, branch=branch, model=model, sdk=sdk))` (same job-creation function AD-10 uses for `spawn_task`), and if `chat.project_id` is still null, settles it via `repo` (no `ProjectRow` exists yet in this codebase — same as 5.1, `project_id` remains a plain nullable string). The Chat row itself is otherwise untouched: `status` stays `"open"`, no consumption/transformation. Verify `chat_service.py` still has zero `GitService` import (job creation delegated entirely to `JobService`).
- [ ] Task 3: Expose message + launch-job over the API (AC: 1, 2, 3)
  - [ ] Add `AddChatMessageRequest`, `ChatMessageResponse`, `LaunchJobFromChatRequest` (repo required, base_ref/branch/model/sdk optional), reuse `CreateJobResponse` for the launch-job result (CamelModel) in `backend/models/api_schemas.py`.
  - [ ] Add to `backend/api/chats.py`: `POST /chats/{id}/messages` (append a message, 404 if chat missing) and `POST /chats/{id}/launch-job` (thin route: 404 if chat missing, delegate to `ChatService.launch_job`, commit session, return `CreateJobResponse`).
  - [ ] `launch-job` route wires `JobService` (`FromDishka[JobService]`) alongside `ChatService`. Thin: no orchestration logic beyond the delegation.
- [ ] Task 4: Add focused tests (AC: 1, 2, 3)
  - [ ] `backend/tests/unit/test_chat_service.py`: extend with `add_message`/`build_transcript` (concatenation, ordering, missing-chat error) and `launch_job` (mocked `JobService.create_job`: seeded prompt equals transcript, chat unchanged/still open after launch, calling twice creates two independent Jobs, `project_id` settles from `repo` on first launch only, git-independence guard still passes).
  - [ ] `backend/tests/integration/test_api_chats.py`: `POST /api/chats/{id}/messages` appends and is reflected in transcript; `POST /api/chats/{id}/launch-job` creates a real Job end-to-end (reusing existing job-creation test fixtures/allowlisted repo), chat remains open afterward via `GET /api/chats/{id}`, and calling launch-job twice produces two distinct job ids.
  - [ ] Run full backend regression suite; confirm no existing tests break.

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
- Alembic: `alembic/versions/0058_add_chats.py` is the immediate reference for the new `0059_add_chat_messages.py` migration.

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

(to be filled during implementation)

### Completion Notes List

(to be filled during implementation)

### File List

(to be filled during implementation)

## Change Log

- 2026-08-10: Story created, marked ready-for-dev.
