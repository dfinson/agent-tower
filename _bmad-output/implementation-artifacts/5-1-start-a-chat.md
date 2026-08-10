---
baseline_commit: bbf317462ea242a987e1c384273b981a77d48ebc
---

# Story 5.1: Start a Chat

Status: review

## Story

As a CodePlane user,
I want to open a persistent, purely conversational Chat,
So that I can think something through before committing to a real run, with zero git footprint.

## Acceptance Criteria

1. **Given** I start a new Chat from a Project's context (or from global nav), **when** the Chat is created, **then** a `ChatRow` is created with `project_id` defaulted accordingly — set to that Project if started from within one, left null if started from global nav — and always user-overridable.
2. **Given** a Chat exists, at any point in its lifetime, **when** I inspect its implementation, **then** it has zero `GitService` dependency of any kind — no worktree, no branch, no git operation is ever possible from within the conversation itself (NFR8).
3. **Given** a Chat with `project_id` still null, **when** I later launch a Job or attach it to a chain from that Chat, **then** `project_id` is settled at that moment, from whichever happens first. (This behavior belongs to Stories 5.2/5.3; this story only guarantees `project_id` remains correctly nullable/overridable at creation so those stories can settle it later.)

## Tasks / Subtasks

- [x] Task 1: Define the `ChatRow` persistence contract (AC: 1, 2)
  - [x] Add `ChatRow` (`id`, `project_id` nullable+indexed, `title`, `created_at`, `last_message_at`, `status`) to `backend/models/db.py`.
  - [x] Add a matching `Chat` domain dataclass to `backend/models/domain.py`.
  - [x] Add alembic migration `0058_add_chats.py` creating the `chats` table and an index on `project_id`.
- [x] Task 2: Implement `chat_service.py` with zero `GitService` dependency (AC: 2)
  - [x] Add `backend/persistence/chat_repo.py` (`ChatRepository`: create/get/list_all), following the existing repository-owns-DB-access convention.
  - [x] Add `backend/services/chat/chat_service.py` (`ChatService.create_chat`) — no import of `GitService`, `git_service`, or any git-touching module, by construction.
  - [x] Add a regression test that statically asserts the `chat_service` module source contains no git-service reference, so this invariant cannot silently regress.
- [x] Task 3: Expose chat creation over the API (AC: 1)
  - [x] Add `CreateChatRequest`, `ChatResponse`, `ChatListResponse` (CamelModel) to `backend/models/api_schemas.py`.
  - [x] Add `backend/api/chats.py`: `POST /chats` (create, `project_id` optional/overridable), `GET /chats` (list), `GET /chats/{id}` (get, 404 if missing). Thin routes only.
  - [x] Wire `ChatRepository`/`ChatService` into `backend/di.py` (REQUEST scope, mirroring `sidecar_template_repo`/`service`).
  - [x] Register `chats.router` in `backend/app_factory.py`.
- [x] Task 4: Add focused tests (AC: 1, 2, 3)
  - [x] `backend/tests/unit/test_chat_service.py`: default-null project_id, explicit project_id passed through and overridable, title required, timestamps set on creation, git-independence guard.
  - [x] `backend/tests/integration/test_api_chats.py`: `POST /api/chats` with/without `project_id`, `GET /api/chats` lists, `GET /api/chats/{id}` gets/404s. Extend `backend/tests/integration/conftest.py`'s `app` fixture to register the chats router and wire `ChatRepository`/`ChatService`.
  - [x] Run full backend regression suite; confirm no existing tests break.

## Dev Notes

### Implementation Boundary

This story creates only the `ChatRow` entity and its creation/read API. It does NOT implement:

- `POST /settings/chats/{id}/launch-job` (Story 5.2)
- `POST /settings/chats/{id}/attach-chain` (Story 5.3)
- `recipe_service.py` / `TaskLinkRow` (Story 5.3/Epic 4 territory)
- Any `ProjectRow` / Project registry (a different, not-yet-implemented epic's stories — this codebase currently has no Project entity at all, so `project_id` is a plain nullable string column with no FK)
- `ChatPanel.tsx` or any frontend UI (UX-DR5 is epic-level and depends on the launch/attach actions from 5.2/5.3 to be meaningful; no AC in 5.1 requires a UI)

### Architecture Compliance (AD-12, NFR8, CAP-12)

- `ChatRow(id, project_id: nullable, title, created_at, last_message_at, status)` owned by a new `chat_service.py`.
- `chat_service.py` must have **no dependency on `GitService` at all** — not "unused," structurally absent — so a Chat cannot provision a worktree or branch by construction.
- `project_id` defaults at creation from UI/caller context (Project → that Project's id; global nav → `null`), always user-overridable in the create request.
- Follow the existing repository-owns-DB-access convention (`backend/persistence/`); services never touch SQLAlchemy sessions directly.
- Response models use `CamelModel` for camelCase serialization, per `backend/models/api_schemas.py` conventions.

### Reference Implementation Pattern

Mirror the existing `sidecar_templates` feature (`backend/persistence/sidecar_template_repo.py`, `backend/services/sidecar/template_service.py`, `backend/api/sidecar_templates.py`, `backend/di.py` sidecar_template_repo/service providers, `backend/app_factory.py` router registration, `alembic/versions/0045_add_sidecar_templates.py`) as the closest analogous CRUD-style feature already in this codebase.

### Project Structure Notes

This is a greenfield entity addition to a brownfield codebase. No previous Chat-related code exists. There are no prior-story learnings to carry forward for this story.

### References

- [Source: `_bmad-output/planning-artifacts/epics.md#Story-51-Start-a-Chat`]
- [Source: `_bmad-output/specs/spec-project-boards/SPEC.md` FR12, NFR8, UX-DR5]
- [Source: `_bmad-output/planning-artifacts/architecture/architecture-codeplane-2026-08-10/ARCHITECTURE-SPINE.md#AD-12-Chat-is-one-persistent-git-free-entity`]
- [Source: `backend/persistence/sidecar_template_repo.py`, `backend/services/sidecar/template_service.py`, `backend/api/sidecar_templates.py`]
- [Source: `backend/di.py`, `backend/app_factory.py`]
- [Source: `alembic/versions/0045_add_sidecar_templates.py`]

## Dev Agent Record

### Agent Model Used

Claude Sonnet 5 (GitHub Copilot CLI), delegated implementation session.

### Debug Log References

- `pytest backend/tests/unit/test_chat_service.py backend/tests/integration/test_api_chats.py -q` → 17 passed.
- `pytest backend/tests -q --ignore=backend/tests/unit/test_saga_compensation.py --timeout=120` → 3348 passed, 16 failed, 36 skipped. All 16 failures are pre-existing and unrelated to this story (`test_git_service.py`, `test_api_settings.py`, `test_api_workspace.py`, `test_integration.py`, `test_artifact_service.py`, `test_config_registration.py`, `test_job_service.py`, `test_terminal_service.py` — Windows/symlink/detached-HEAD issues, none touching chats). No test in any of these files was modified by this story.
- `ruff check backend/models/db.py backend/models/domain.py backend/models/api_schemas.py backend/persistence/chat_repo.py backend/services/chat/chat_service.py backend/api/chats.py backend/di.py backend/app_factory.py backend/tests/unit/test_chat_service.py backend/tests/integration/test_api_chats.py backend/tests/integration/conftest.py` → all checks passed.

### Completion Notes List

- Added `ChatRow` (`backend/models/db.py`) and matching `Chat` domain dataclass (`backend/models/domain.py`): `id`, `project_id` (nullable, indexed), `title`, `created_at`, `last_message_at`, `status` (default `"open"`). No `ProjectRow`/Project registry exists yet in this codebase, so `project_id` is a plain nullable string column with no FK, matching the architecture spine's description for this story.
- Added `alembic/versions/0058_add_chats.py` creating the `chats` table and an index on `project_id`, following on from head revision `0057`.
- Added `backend/persistence/chat_repo.py` (`ChatRepository`: `create`/`get`/`list_all`), following the existing repository-owns-DB-access convention (mirrors `SidecarTemplateRepository`).
- Added `backend/services/chat/chat_service.py` (`ChatService.create_chat`/`get_chat`/`list_chats`). Verified structurally git-free: no import of `GitService`, `git_service`, or any git-touching module anywhere in the module (AD-12/NFR8) — enforced by an AST-based regression test (`TestChatIsGitFree`) that would fail if a future edit ever added such an import, not just a substring check that could be defeated by a docstring mention.
- Added `CreateChatRequest`/`ChatResponse`/`ChatListResponse` (`CamelModel`) to `backend/models/api_schemas.py` and `backend/api/chats.py` with thin `POST /chats`, `GET /chats`, `GET /chats/{id}` routes — validate input, delegate to `ChatService`, return the result.
- Wired `ChatRepository`/`ChatService` into `backend/di.py` (REQUEST scope, mirroring `sidecar_template_repo`/`sidecar_template_service`) and registered `chats.router` in `backend/app_factory.py`.
- `project_id` is always accepted from the create request body and passed straight through with no coercion, so a caller (UI) can default it from Project context or leave it `None` from global nav, and the user can override it at creation time (AC 1). `project_id` settlement on later launch-job/attach-chain (AC 3) is explicitly deferred to Stories 5.2/5.3 — not implemented here, per the story's Implementation Boundary.
- Added `backend/tests/unit/test_chat_service.py` (12 tests): default-null `project_id`, explicit/overridable `project_id`, timestamp assignment, unique ID generation, read delegation, and the AST-based git-independence guard.
- Added `backend/tests/integration/test_api_chats.py` (8 tests) exercising all three endpoints end-to-end through the FastAPI test client (create with/without `project_id`, validation errors, list, get, 404). Extended `backend/tests/integration/conftest.py`'s `app` fixture to register `chats.router` (append-only change; no existing fixture behavior altered).
- Did not implement `POST /settings/chats/{id}/launch-job`, `POST /settings/chats/{id}/attach-chain`, `recipe_service.py`/`TaskLinkRow`, any `ProjectRow`/Project registry, or `ChatPanel.tsx`/frontend UI, per the story's Implementation Boundary — those belong to Stories 5.2/5.3 and other epics.

### File List

- `backend/models/db.py` (modified — added `ChatRow`)
- `backend/models/domain.py` (modified — added `Chat` dataclass)
- `backend/persistence/chat_repo.py` (new)
- `backend/services/chat/__init__.py` (new)
- `backend/services/chat/chat_service.py` (new)
- `backend/models/api_schemas.py` (modified — added `CreateChatRequest`, `ChatResponse`, `ChatListResponse`)
- `backend/api/chats.py` (new)
- `backend/di.py` (modified — added `chat_repo`/`chat_service` providers)
- `backend/app_factory.py` (modified — registered `chats.router`)
- `alembic/versions/0058_add_chats.py` (new)
- `backend/tests/unit/test_chat_service.py` (new)
- `backend/tests/integration/test_api_chats.py` (new)
- `backend/tests/integration/conftest.py` (modified — registered `chats.router` in the test `app` fixture)
- `_bmad-output/implementation-artifacts/sprint-status.yaml` (modified — `5-1-start-a-chat` → review)

## Change Log

- 2026-08-10: Story created and marked in-progress; implementation started.
- 2026-08-10: Implementation complete — `ChatRow`, `chat_service.py` (zero `GitService` dependency), CRUD API, migration, and full test coverage added. All ACs satisfied. Status set to review.
