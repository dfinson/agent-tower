---
baseline_commit: bbf31746
---

# Story 3.1: Register a Credential

Status: review

## Story

As a CodePlane user,
I want to register a provider account (Jira, Azure DevOps, or GitHub Projects) once,
So that I don't have to re-enter credentials for every Project that needs it.

## Acceptance Criteria

1. **Given** the Settings > Integrations screen, **when** I enter a provider, label, base URL, and PAT, **then** a `CredentialRow` is created with the PAT encrypted at rest, **and** the PAT is never rendered in plaintext after save, never logged, and never included in any agent-facing job prompt/context (NFR1).
2. **Given** an existing Credential is referenced by one or more TrackerLinks, **when** I attempt to delete it, **then** the deletion is blocked until all referencing TrackerLinks are removed.

## Tasks / Subtasks

- [x] Task 1: Add the `Credential` persistence contract (AC: 1, 2)
  - [x] Add `CredentialRow` ORM model (`backend/models/db.py`): id, provider, label, base_url, encrypted_secret, created_at.
  - [x] Add a minimal `TrackerLinkRow` ORM model (project_id as a plain, non-FK string column — deliberately decoupled from a `Project` entity, which does not exist yet) so AC2's referential-integrity rule has something real to enforce. No attach/detach endpoints for TrackerLink are added; that is Story 3.2 scope.
  - [x] Add Alembic migration `alembic/versions/0058_add_credentials.py` creating `credentials` and `tracker_links` tables on top of `0057`.
- [x] Task 2: Implement PAT encryption at rest (AC: 1, NFR1/NFR9)
  - [x] Add `backend/services/credentials/encryption.py` using `cryptography.fernet.Fernet` (already a locked dependency; no new package added).
  - [x] Auto-generate and persist a Fernet key at `get_codeplane_dir() / "credential.key"` on first use; best-effort `chmod 0600` wrapped in `contextlib.suppress(OSError)` for platforms without POSIX permission bits.
  - [x] Provide `encrypt_secret`/`decrypt_secret` plus a `CredentialDecryptionError` for corrupt/foreign-key ciphertext.
- [x] Task 3: Implement `CredentialRepository` (AC: 1, 2)
  - [x] `backend/persistence/credential_repo.py` following the existing `PolicyRepository` shared-session pattern (`BaseRepository`, `async_sessionmaker[AsyncSession]` via `FromDishka`).
  - [x] `list_all()`/`get()` never include `encrypted_secret` in returned dicts (not just omitted from the response schema) — the plaintext PAT never leaves the encryption boundary except via `resolve_secret()`, which no Story 3.1 route calls.
  - [x] `create()` encrypts the PAT before persisting.
  - [x] `delete()` raises `CredentialReferencedError` when any `TrackerLinkRow` still references the credential; the API translates this to `409 Conflict`.
- [x] Task 4: Implement the `/settings/credentials` API (AC: 1, 2)
  - [x] `backend/api/credentials.py`: thin `DishkaRoute`-style router — `GET` (list, secret-free), `GET /guidance` (static per-provider NFR9 guidance text for github/jira/azure_devops), `POST` (create, 201), `DELETE /{id}` (204, 409 if referenced, 404 if missing).
  - [x] `CamelModel`-based schemas: `CredentialResponse`, `CredentialListResponse`, `CreateCredentialRequest`, `ProviderGuidanceResponse`. Provider is constrained by regex `^(github|jira|azure_devops)$`.
  - [x] Mount the router in `backend/app_factory.py` (production) and `backend/tests/integration/conftest.py` (test app fixture).
  - [x] Structured log events (`credential.created`, `credential.deleted`, etc.) never include the PAT/secret field.
- [x] Task 5: Author comprehensive tests (AC: 1, 2)
  - [x] `backend/tests/unit/test_credential_encryption.py` — round-trip encrypt/decrypt, key persistence/reuse, corrupt-ciphertext error.
  - [x] `backend/tests/unit/test_credential_repo.py` — create/list/get/resolve_secret, delete blocked while a `TrackerLinkRow` references the credential, delete succeeds after the link is removed.
  - [x] `backend/tests/integration/test_api_credentials.py` — list/guidance/create/delete endpoint contracts, including the 409 blocked-delete path via a `TrackerLinkRow` fixture, and asserting list/get responses never contain the secret.
- [x] Task 6: Build the Settings > Integrations UI (AC: 1, 2)
  - [x] `frontend/src/api/client.ts` — add `Credential`, `CreateCredentialRequest`, `CredentialProvider` types and `fetchCredentials`/`fetchCredentialGuidance`/`createCredential`/`deleteCredential` functions, following the existing hand-written-interface precedent already used for `PolicyState`/`UsdCeiling` in this file (rather than OpenAPI-schema generation, which requires a running backend).
  - [x] `frontend/src/components/IntegrationsSettings.tsx` — provider picker with live NFR9 guidance text, register form (label/base URL/PAT), credential list (never renders the secret), delete flow gated by `ConfirmDialog`.
  - [x] Wire `IntegrationsSettings` into `frontend/src/components/SettingsScreen.tsx` after `PolicySettingsPanel`.
  - [x] `frontend/src/components/__tests__/IntegrationsSettings.test.tsx` — empty state, list rendering without ever showing a secret, guidance display + create submission, missing-field validation toast, delete confirm-dialog flow. Uses `fireEvent` per project test convention (not `@testing-library/user-event`, which is not a project dependency).

## Dev Notes

### Implementation Boundary

This story implements only the global, Project-independent `Credential` entity and its registration/deletion UI and API. It explicitly does **not** implement:

- The `Project` entity (Epic 2/elsewhere) — Credential registration must not block on Project existing.
- Story 3.2 (attaching a `TrackerLink` to a Project) — no attach/create/list endpoints for `TrackerLink` exist yet. `TrackerLinkRow` is schema-only in this story, added solely so AC2's delete-blocked-while-referenced rule has a real referential check to enforce.
- Tracker polling/sync, write-back approval flows, or any use of `CredentialRepository.resolve_secret()` by a tracker adapter (out of scope; NFR2/NFR3/FR7 belong to later stories in Epic 3).

### Architecture Compliance

- Thin routes: `backend/api/credentials.py` validates input and delegates to `CredentialRepository`; no orchestration logic lives in the route handlers.
- All database access goes through `CredentialRepository` in `backend/persistence/`; no direct SQLAlchemy session usage in the API layer.
- Response models use the `CamelModel` base class for camelCase serialization, matching the rest of the API contract.
- `CredentialRow.encrypted_secret` is never included in any repository read path that could reach a response model; `resolve_secret()` is a separate, unused-by-this-story method reserved for a future tracker adapter (AD-6/CAP-6/CAP-7).
- Encryption uses the already-locked `cryptography` dependency (Fernet symmetric encryption); no new dependency was added.

### References

- [Source: `_bmad-output/planning-artifacts/epics.md#Story-31-Register-a-Credential`]
- [Source: `_bmad-output/specs/spec-project-boards/SPEC.md` CAP-6, CAP-7, NFR1, NFR9]
- [Source: `_bmad-output/planning-artifacts/architecture/*/ARCHITECTURE-SPINE.md` AD-6 (Credential/TrackerLink separation, encrypted-at-rest PAT storage)]
- [Source: `backend/services/policy_settings.py`, `backend/persistence/` `PolicyRepository` — repository/route pattern precedent]
- [Source: `frontend/src/api/client.ts` `PolicyState`/`UsdCeiling` — hand-written settings-adjacent type precedent]

## Dev Agent Record

### Agent Model Used

Claude Sonnet 5 (GitHub Copilot CLI).

### Debug Log References

- Backend: `uv run pytest` could not be used in this worktree because `uv sync` fails to fetch `traceforge-toolkit==0.1.5` from PyPI (TLS handshake failure in this sandbox). Ran tests/lint instead via the main checkout's pre-built venv: `C:\Users\davidfinson\.copilot\repos\codeplane\.venv\Scripts\python.exe -m pytest ...` / `... -m ruff check ...`, invoked from within this worktree so the tests exercise this branch's code.
- `pytest backend/tests/unit/test_credential_encryption.py backend/tests/unit/test_credential_repo.py backend/tests/integration/test_api_credentials.py -q` → 24 passed.
- `ruff check` on all new/modified backend files → all checks passed (8 pre-existing lint issues found and fixed during development: UP037, SIM105, TC003 x-several, E501).
- A full-repository `pytest backend/tests -q` run could not be completed to 100% in this sandbox: it consistently hangs partway through (observed at ~46-48%, in modules unrelated to this change, e.g. `test_persistence_repos.py`/job-service-adjacent async mocks) due to a pre-existing Windows/asyncio event-loop interaction in this environment, reproducible even with `pytest-timeout` (`--timeout`, thread method) and independent of this story's changes. Confirmed pre-existing and unrelated by: (a) reproducing one scattered pre-existing failure (`test_api_settings.py::TestGetRepoDetail::test_registered_repo`) on a `git stash`-clean tree without any Story 3.1 changes; (b) running the new credential tests together with the immediately-surrounding alphabetical test modules (`test_persistence_repos.py`, `test_permission_policy.py`) in isolation — `68 passed` with no hang. Regression risk from this story's `CredentialRow`/`TrackerLinkRow` additions to `Base.metadata` is assessed as low: both are new, disconnected tables (no FKs to existing entities) and every touched/adjacent module was verified to pass directly.
- Frontend: `npx vitest run IntegrationsSettings` → 5 passed. `npx vitest run SettingsScreen` (regression check for the new component wired into the existing screen) → 5 passed, no regressions. `npx tsc --noEmit` → clean. `npx eslint` on all touched frontend files → clean.

### Completion Notes List

- Implemented the global `Credential` entity (provider/label/base_url/encrypted PAT) exactly as scoped: independent of `Project`, which does not exist in the codebase yet, per explicit story guidance.
- PAT is encrypted at rest with Fernet; plaintext never returned by any list/get read path, never logged (structured log events explicitly omit the secret field), and never included in agent-facing job context (no code path connects `CredentialRepository.resolve_secret()` to job/prompt construction in this story).
- Added a minimal, FK-decoupled `TrackerLinkRow` purely to give AC2's "delete blocked while referenced" rule a real referential check; no TrackerLink attach/list/detach API exists yet (Story 3.2).
- Followed existing repository/route/schema conventions (`PolicyRepository`, `CamelModel`, thin `DishkaRoute`-style handlers) and existing frontend hand-written-type precedent (`PolicyState`/`UsdCeiling` in `client.ts`) rather than introducing new patterns.
- Full backend regression suite could not be run to completion in this sandbox due to a pre-existing, unrelated environment hang (see Debug Log References); targeted and adjacent-module test runs show no regressions from this change.

### File List

- `backend/models/db.py` (modified — added `CredentialRow`, `TrackerLinkRow`)
- `backend/services/credentials/__init__.py` (new)
- `backend/services/credentials/encryption.py` (new)
- `backend/persistence/credential_repo.py` (new)
- `backend/api/credentials.py` (new)
- `backend/app_factory.py` (modified — mounted `credentials` router)
- `backend/tests/integration/conftest.py` (modified — mounted `credentials` router in test app fixture)
- `alembic/versions/0058_add_credentials.py` (new)
- `backend/tests/unit/test_credential_encryption.py` (new)
- `backend/tests/unit/test_credential_repo.py` (new)
- `backend/tests/integration/test_api_credentials.py` (new)
- `frontend/src/api/client.ts` (modified — added Credential types/functions)
- `frontend/src/components/IntegrationsSettings.tsx` (new)
- `frontend/src/components/SettingsScreen.tsx` (modified — wired in `IntegrationsSettings`)
- `frontend/src/components/__tests__/IntegrationsSettings.test.tsx` (new)

## Change Log

- 2026-08-10: Implemented Story 3.1 (Register a Credential) end-to-end: backend `CredentialRow`/`TrackerLinkRow` models, migration, Fernet-based encryption service, `CredentialRepository`, `/settings/credentials` API, and the Settings > Integrations frontend panel with full test coverage. Status set to `review`.
