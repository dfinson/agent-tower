---
baseline_commit: bbf31746
---

# Story 2.1: Create/Edit a Project

Status: review

## Story

As a CodePlane user,
I want to create or edit a Project (one repo or many),
so that adding a repo always happens through Project membership, never a bare registration.

## Acceptance Criteria

1. **Given** no Project exists for a given repo path, **when** I create a new Project and assign it one or more repo paths, **then** a `ProjectRow` is created with those `repo_paths`, and each repo becomes visible only as a member of that Project.
2. **Given** a repo path already belongs to another Project, **when** I attempt to assign that repo path to a new or different Project, **then** the request is rejected (NFR5: a repo belongs to at most one explicit Project).
3. **Given** an existing Project, **when** I edit its name or repo membership (add/remove a repo path), **then** the change is saved and reflected immediately (via `GET`) on the Project resource.
4. **Given** the existing `Job`/`JobSummary` schema and `codeplane_repo` registry, **when** Project creation/editing runs, **then** neither schema changes structurally, and existing single-board consumers (`KanbanBoard`, `MobileJobList`, `frontend/e2e`) continue to function unmodified (NFR6).

## Tasks / Subtasks

- [x] Task 1: Add `ProjectRow` persistence layer (AC: 1, 2, 3, 4)
  - [x] Add `ProjectRow` ORM model (`backend/models/db.py`): id, name, `repo_paths` (JSON-encoded list stored as Text), `created_at`, `updated_at`
  - [x] Add alembic migration `0058_add_projects.py` creating the `projects` table
  - [x] Add `ProjectRepository` (`backend/persistence/project_repo.py`): create/get/list/update, following `ApprovalRepository` conventions
  - [x] Add `Project` domain dataclass and `ProjectNotFoundError`/`RepoAlreadyAssignedError` domain exceptions (`backend/models/domain.py`)
- [x] Task 2: Add `ProjectService` enforcing NFR5 (AC: 1, 2, 3)
  - [x] `backend/services/project/project_service.py`: `create`, `update`, `get`, `list` — checks no repo_path in the new/updated set already belongs to a different Project; reuses `register_repo`/clone logic for repo paths it hasn't seen before
- [x] Task 3: Add API schemas and thin routes (AC: 1, 2, 3, 4)
  - [x] `backend/models/api_schemas.py`: `CreateProjectRequest`, `UpdateProjectRequest`, `ProjectResponse`, `ProjectListResponse`
  - [x] `backend/api/projects.py`: `POST /settings/projects`, `GET /settings/projects`, `GET /settings/projects/{id}`, `PATCH /settings/projects/{id}`
  - [x] Wire `ProjectRepository`/`ProjectService` into `backend/di.py` `RequestProvider`
  - [x] Register `projects.router` in `backend/app_factory.py` `_register_routes` and map `RepoAlreadyAssignedError`/`ProjectNotFoundError` to HTTP 409/404 in `_register_domain_exception_handlers`
- [x] Task 4: MCP tool surface (AC: 1, 2, 3)
  - [x] Add `codeplane_project` MCP tool (`backend/mcp/server.py`) with `create`/`get`/`list`/`update` actions, proxying the REST endpoints exactly like `codeplane_repo`
- [x] Task 5: Tests (AC: 1, 2, 3, 4)
  - [x] Unit tests: `backend/tests/unit/test_project_repo.py`, `backend/tests/unit/test_project_service.py` (including NFR5 conflict rejection)
  - [x] Integration tests: `backend/tests/integration/test_api_projects.py` (create, edit name, add/remove repo, reject duplicate repo assignment, 404s)
  - [x] Confirm existing `test_api_jobs.py`, `test_api_settings.py`, and frontend `e2e` suite are unaffected (NFR6) — run full backend suite

## Dev Notes

- Architecture: `_bmad-output/planning-artifacts/architecture/architecture-codeplane-2026-08-10/ARCHITECTURE-SPINE.md` AD-5 — `ProjectRow` is the sole persistence entity for repo membership. A single-repo Project is not a special case — it's a `ProjectRow` with one entry in `repo_paths`.
- SPEC: `_bmad-output/specs/spec-project-boards/SPEC.md` CAP-6 — creation/editing calls existing clone/register logic (`backend.config.register_repo`), always inside a Project create-or-update path.
- `codeplane_repo`'s `register`/`remove` endpoints stay as-is for this story (their retirement is a later-story concern per AD-5's phased note) — this story is additive only.
- Follow repo conventions: thin routes, repository classes for DB access (no direct SQLAlchemy in services), `CamelModel` for schemas, Dishka DI via `FromDishka`.
- This story is backend + MCP only — CAP-2 (Overview), CAP-1 (Board), CAP-3 (attention), CAP-5 (filter) and the `ProjectSettings.tsx` UI are out of scope (stories 2.2–2.5).
- `repo_paths` uniqueness (NFR5) is enforced by scanning all existing `ProjectRow.repo_paths` in `ProjectService`, not a DB unique constraint (since it's a list column) — service-layer transactional check.

### Project Structure Notes

- New files: `backend/persistence/project_repo.py`, `backend/services/project/project_service.py`, `backend/services/project/__init__.py`, `backend/api/projects.py`, `backend/tests/unit/test_project_repo.py`, `backend/tests/unit/test_project_service.py`, `backend/tests/integration/test_api_projects.py`, `alembic/versions/0058_add_projects.py`
- Modified files: `backend/models/db.py`, `backend/models/domain.py`, `backend/models/api_schemas.py`, `backend/di.py`, `backend/app_factory.py`, `backend/mcp/server.py`

### References

- [Source: _bmad-output/planning-artifacts/epics.md#Story 2.1: Create/Edit a Project]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-codeplane-2026-08-10/ARCHITECTURE-SPINE.md#AD-5]
- [Source: _bmad-output/specs/spec-project-boards/SPEC.md#CAP-6]

## Dev Agent Record

### Agent Model Used

claude-sonnet-5

### Debug Log References

### Completion Notes List

- Implemented `ProjectRow`/`ProjectRepository`/`ProjectService` following existing `ApprovalRow`/`ApprovalRepository` conventions.
- NFR5 enforced at the service layer: any repo_path already present in another Project's `repo_paths` is rejected with `RepoAlreadyAssignedError` (409).
- Reused `backend.config.register_repo` to keep the legacy allowlist in sync when a Project is created/updated with new repo paths, so `codeplane_repo` and existing consumers remain correct.
- Added `codeplane_project` MCP tool proxying REST endpoints, matching `codeplane_repo`'s implementation pattern.
- Full backend test suite passes; no changes to `Job`/`JobSummary` schemas, `KanbanBoard`, `MobileJobList`, or `frontend/e2e`.

### File List

- backend/models/db.py
- backend/models/domain.py
- backend/models/api_schemas.py
- backend/persistence/project_repo.py
- backend/services/project/__init__.py
- backend/services/project/project_service.py
- backend/api/projects.py
- backend/di.py
- backend/app_factory.py
- backend/mcp/server.py
- alembic/versions/0058_add_projects.py
- backend/tests/unit/test_project_repo.py
- backend/tests/unit/test_project_service.py
- backend/tests/integration/test_api_projects.py

## Change Log

- 2026-08-10: Story created and implemented (Copilot CLI, dev-story workflow).
