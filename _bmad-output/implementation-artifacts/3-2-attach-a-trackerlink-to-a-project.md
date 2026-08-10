---
baseline_commit: 162d97a2
---

# Story 3.2: Attach a TrackerLink to a Project

Status: review

## Story

As a CodePlane user,
I want to attach a Credential to a Project via a TrackerLink,
So that my Project's board reflects that Project's ticket state.

## Acceptance Criteria

1. **Given** at least one Credential is registered, **when** I attach it to a Project along with an external project/board reference, **then** a `TrackerLinkRow` (Project + Credential + external ref) is created.
2. **And** a Project can have more than one TrackerLink (e.g. referencing two external boards).
3. **And** any number of Projects may attach the same Credential (Credential is global, not consumed per-attachment).

## Tasks / Subtasks

- [x] Task 1: Implement `TrackerLinkRepository` (AC: 1, 2, 3)
  - [x] `backend/persistence/tracker_link_repo.py`: `create()` validates both the Project and the Credential exist (raising `TrackerLinkProjectNotFoundError`/`TrackerLinkCredentialNotFoundError`) before inserting, since `TrackerLinkRow.project_id` is a plain string with no DB-level FK to `ProjectRow` (per Story 3.1's deliberate decoupling).
  - [x] `list_for_project(project_id)` — returns all TrackerLinks for a Project, ordered by `created_at`.
  - [x] No new ORM model or migration — `TrackerLinkRow`/`credentials`/`tracker_links` tables already exist from Story 3.1 (migration `0058_add_credentials.py`); confirmed the current alembic head is `0060_add_projects.py` and no schema change is needed for this story.
- [x] Task 2: Implement the `/projects/{project_id}/tracker-links` API (AC: 1, 2, 3)
  - [x] `backend/api/tracker_links.py`: thin `DishkaRoute`-style router mirroring the Story 3.1 `credentials.py` pattern (inline `async_sessionmaker[AsyncSession]` session, not the DI-service pattern used by `projects.py`) — `POST` (attach/create, 201, 404 if Project or Credential missing) and `GET` (list, secret-free by construction since `TrackerLinkRow` never stores a secret).
  - [x] `CamelModel`-based schemas: `TrackerLinkResponse`, `TrackerLinkListResponse`, `CreateTrackerLinkRequest`.
  - [x] Mount the router in `backend/app_factory.py` (production) and `backend/tests/integration/conftest.py` (test app fixture).
  - [x] Structured log event (`tracker_link.created`).
- [x] Task 3: Author comprehensive tests (AC: 1, 2, 3)
  - [x] `backend/tests/unit/test_tracker_link_repo.py` — create success, create raises when Project missing, create raises when Credential missing, a Project can have multiple TrackerLinks, the same Credential can attach to multiple Projects, `list_for_project` returns empty/scoped results without leaking across Projects.
  - [x] `backend/tests/integration/test_api_tracker_links.py` — attach/create endpoint contract, multiple links per Project, same Credential across multiple Projects, 404 for missing Project, 404 for missing Credential, 422 for empty `externalRef`, list endpoint (empty + scoped, no cross-Project leakage).

## Dev Notes

### Implementation Boundary

This story implements only the attach/create + list surface for `TrackerLinkRow`, on top of the schema-only anchor Story 3.1 already added. It explicitly does **not** implement:

- Ticket/board sync or polling (Story 3.3).
- Outbound write-back through `codeplane_approval` (Story 3.4).
- Per-provider PAT scope guidance UI (Story 3.5).
- Any frontend UI: Project management (Story 2.1, CAP-6) itself has no frontend surface in the codebase yet, so there is nothing for a TrackerLink attach/detach UI to hang off of yet — deferred until a Project management UI exists.
- Detach/delete endpoints — not required by this story's acceptance criteria (attach + multiplicity only); adding delete now would be scope creep beyond the literal ACs.

### Architecture Compliance

- Thin routes: `backend/api/tracker_links.py` validates input and delegates to `TrackerLinkRepository`; no orchestration logic lives in the route handlers.
- All database access goes through `TrackerLinkRepository` in `backend/persistence/`; no direct SQLAlchemy session usage in the API layer.
- Response models use the `CamelModel` base class for camelCase serialization, matching the rest of the API contract.
- `project_id` remains a plain string (not a DB-level FK), per Story 3.1's explicit decoupling decision — Project-existence is instead validated in the repository layer before insert, so the referential-integrity intent (AC1) is still enforced, just at the application layer rather than the schema layer.
- No new migration: `TrackerLinkRow` already exists from `alembic/versions/0058_add_credentials.py`; verified `0060_add_projects.py` is the current alembic head on `origin/main` with no story adding a migration in between.

### References

- [Source: `_bmad-output/planning-artifacts/epics.md#Story-32-Attach-a-TrackerLink-to-a-Project`]
- [Source: `_bmad-output/specs/spec-project-boards/SPEC.md` CAP-7, AD-6]
- [Source: `_bmad-output/implementation-artifacts/3-1-register-a-credential.md` — TrackerLinkRow anchor and explicit Story 3.2 deferral]
- [Source: `backend/api/credentials.py`, `backend/persistence/credential_repo.py` — thin router/repository pattern precedent reused here]

## Dev Agent Record

### Agent Model Used

Claude Sonnet 5 (GitHub Copilot CLI).

### Debug Log References

- `C:\Users\davidfinson\.copilot\repos\codeplane\.venv\Scripts\python.exe -m pytest backend/tests/unit/test_tracker_link_repo.py backend/tests/integration/test_api_tracker_links.py -q` → 15 passed.
- Regression smoke check: `... -m pytest backend/tests/unit/test_credential_repo.py backend/tests/integration/test_api_credentials.py backend/tests/unit/test_project_repo.py backend/tests/unit/test_project_service.py -q` → 34 passed, no regressions from wiring the new router alongside `credentials`/`projects`.
- `... -m ruff check` on all new/modified backend files → all checks passed.
- `... -m mypy backend/persistence/tracker_link_repo.py backend/api/tracker_links.py` → no issues found.
- Same `uv sync` TLS/PyPI limitation noted in Story 3.1's debug log applies in this worktree; used the pre-built venv from the main checkout (`C:\Users\davidfinson\.copilot\repos\codeplane\.venv`), invoked from within this worktree so tests exercise this branch's code.

### Completion Notes List

- Implemented `TrackerLinkRepository.create()`/`list_for_project()` and the `/projects/{project_id}/tracker-links` POST/GET API, filling the attach/create/list gap Story 3.1 deliberately left open.
- Confirmed no new ORM model or migration is required: `TrackerLinkRow` already exists from Story 3.1's `0058_add_credentials.py`; `0060_add_projects.py` remains the current alembic head on `origin/main`.
- Application-layer existence checks (Project, Credential) substitute for the DB-level FK that `project_id` deliberately lacks, per Story 3.1's decoupling rationale — both return 404 via dedicated exception types.
- No frontend changes: Project management (2.1) has no UI yet in this codebase, so a TrackerLink attach/detach UI has nothing to attach to; deferred.
- Explicitly did not implement ticket sync (3.3), approval-gated write-back (3.4), or PAT scope guidance (3.5), per story scope.

### File List

- `backend/persistence/tracker_link_repo.py` (new)
- `backend/api/tracker_links.py` (new)
- `backend/app_factory.py` (modified — mounted `tracker_links` router)
- `backend/tests/integration/conftest.py` (modified — mounted `tracker_links` router in test app fixture)
- `backend/tests/unit/test_tracker_link_repo.py` (new)
- `backend/tests/integration/test_api_tracker_links.py` (new)

## Change Log

- 2026-08-10: Implemented Story 3.2 (Attach a TrackerLink to a Project): `TrackerLinkRepository` (create + list, with Project/Credential existence validation), `/projects/{project_id}/tracker-links` API, and full test coverage. No new migration required — reused the `TrackerLinkRow` schema anchor from Story 3.1. Status set to `review`.
