---
baseline_commit: 24992120
---

# Story 3.5: See per-provider PAT scope guidance

Status: review

## Story

As a CodePlane user registering a Credential,
I want to see the minimal token scope required for my provider,
So that I don't over-grant permissions I don't need.

## Acceptance Criteria

1. **Given** I am registering a GitHub Credential, **when** I view the registration screen, **then** I see copy-paste guidance for fine-grained PAT scopes (`Issues: Read & write` for tracker writes; `Contents: Read & write` + `Pull requests: Read & write` if PR creation will also be used) (NFR9).
2. **Given** I am registering a Jira or Azure DevOps Credential, **when** I view the registration screen, **then** I see guidance stating the token cannot be scoped down further than the full account (Jira API token) or the full organization (Azure DevOps PAT), and that the approval gate — not token scope — is the real security boundary (NFR9).
3. **Given** any provider's registration screen, **when** I look for an OAuth app connection option, **then** none exists — PAT-only, confirming NFR3.

## Tasks / Subtasks

- [x] Task 1: Verify the existing `/settings/credentials/guidance` content satisfies each AC (AC: 1, 2)
  - [x] Compare `backend/api/credentials.py` `_PROVIDER_GUIDANCE` text (built as part of Story 3.1's own scope) against SPEC.md's NFR9 paragraph and this story's AC wording.
  - [x] Confirmed no content changes were needed — GitHub guidance already names `Issues: Read & write`, `Contents: Read & write`, `Pull requests: Read & write`; Jira/Azure guidance already states the token can't be scoped below full-account/full-org and names the approval gate as the real boundary.
- [x] Task 2: Add test coverage that pins each AC to the guidance content (AC: 1, 2)
  - [x] `backend/tests/integration/test_api_credentials.py`: assert the GitHub guidance string contains the exact scope phrases from AC1.
  - [x] Assert the Jira guidance string states the token can't be scoped below the full account and names the approval gate.
  - [x] Assert the Azure DevOps guidance string states org-scoping (not project-scoping), lists `Work Items: Read & write` / `Code: Read & write`, and names the approval gate.
- [x] Task 3: Verify and test the PAT-only / no-OAuth guarantee (AC: 3)
  - [x] Backend: assert no OAuth-related route is registered on the app and no OAuth field exists on `CreateCredentialRequest`.
  - [x] Frontend: `IntegrationsSettings.test.tsx` — assert no "OAuth"/"Connect account" affordance is rendered anywhere on the registration screen.
- [x] Task 4: Confirm no DB/migration changes are required (AC: 1, 2, 3)
  - [x] Checked alembic head on `origin/main` (`0059_add_credentials.py`) before starting; this story adds no schema, so no new migration file is created.
- [x] Task 5: Update sprint tracking (AC: 1, 2, 3)
  - [x] Move `3-5-see-per-provider-pat-scope-guidance` to `review` in `_bmad-output/implementation-artifacts/sprint-status.yaml` once all tests pass.

## Dev Notes

### Implementation Boundary

Story 3.1 built the `GET /settings/credentials/guidance` endpoint and the `IntegrationsSettings.tsx` guidance rendering as part of its own scope (see its Task 4/6 notes), anticipating this story's requirement. This story therefore does **not** build a new endpoint or new UI section — it verifies the existing guidance content satisfies every AC bullet verbatim and closes the test-coverage gap (nothing previously asserted the exact scope phrases or the absence of an OAuth option). Do not touch:

- Story 3.2 (attach a TrackerLink to a Project) — no attach/detach endpoints.
- Story 3.3 (view synced ticket state) — no tracker sync/polling code.
- Story 3.4 (approve a tracker write-back) — no approval-flow code.

### Architecture Compliance

- `backend/api/credentials.py::get_provider_guidance` remains a thin, static, no-DB-access route (AD-6) — this story only adds assertions, no route logic changes.
- Guidance text stays copy-paste-only and is never validated/enforced against a TrackerLink's actual scope, per NFR9 and AD-6 — Credential is deliberately global-and-reusable.
- No OAuth code path exists anywhere in `backend/api/credentials.py` or `IntegrationsSettings.tsx` (PAT-only field, `type="password"` input) — confirms NFR3.

### References

- [Source: `_bmad-output/planning-artifacts/epics.md#Story-35-See-per-provider-PAT-scope-guidance`]
- [Source: `_bmad-output/specs/spec-project-boards/SPEC.md` NFR9, NFR3]
- [Source: `_bmad-output/planning-artifacts/architecture/architecture-codeplane-2026-08-10/ARCHITECTURE-SPINE.md` AD-6]
- [Source: `backend/api/credentials.py` `_PROVIDER_GUIDANCE`, `get_provider_guidance` — existing implementation from Story 3.1]
- [Source: `frontend/src/components/IntegrationsSettings.tsx` — existing guidance rendering from Story 3.1]
- [Source: `_bmad-output/implementation-artifacts/3-1-register-a-credential.md` — prior story, same subsystem]

### Project Structure Notes

- No new files under `backend/services/` or `frontend/src/components/` are required; changes are confined to existing test files.
- Alignment with unified project structure: test additions live alongside existing `TestProviderGuidance` class in `test_api_credentials.py` and the existing `describe("IntegrationsSettings")` block in the frontend test file — no new test files needed.

## Dev Agent Record

### Agent Model Used

Claude Sonnet 5 (GitHub Copilot CLI).

### Debug Log References

- Backend: `uv run pytest` unavailable in this worktree (no `.venv`); used the main checkout's pre-built venv instead, invoked from within this worktree so tests exercise this branch's code: `C:\Users\davidfinson\.copilot\repos\codeplane\.venv\Scripts\python.exe -m pytest backend\tests\integration\test_api_credentials.py -q` → 14 passed (5 new tests added for this story). Full credential-adjacent regression run (`test_credential_encryption.py`, `test_credential_repo.py`, `test_api_credentials.py`) → 29 passed, no regressions.
- `ruff check backend\tests\integration\test_api_credentials.py backend\api\credentials.py` → all checks passed, no lint issues.
- Frontend: `frontend/node_modules` did not exist in this worktree; ran `npm install` (650 packages) before testing. `npx vitest run IntegrationsSettings` → 6 passed (1 new test added for this story). `npx vitest run SettingsScreen` (regression check) → 5 passed, no regressions. `npx eslint src/components/__tests__/IntegrationsSettings.test.tsx` → clean, no issues.
- Alembic head on `origin/main` confirmed as `0059_add_credentials.py` before starting; no migration was created, consistent with this story requiring no schema change.

### Completion Notes List

- Confirmed the `/settings/credentials/guidance` endpoint and its `_PROVIDER_GUIDANCE` content (built as part of Story 3.1's own scope) already satisfy all three ACs verbatim — no content or endpoint changes were needed.
- Closed the test-coverage gap: added backend tests pinning the exact GitHub scope phrases (`Issues: Read & write`, `Contents: Read & write`, `Pull requests: Read & write`), the Jira full-account/approval-gate wording, and the Azure DevOps org-scope/approval-gate wording (AC1, AC2).
- Added backend tests confirming no OAuth route is registered on the credentials router and `CreateCredentialRequest` has no OAuth field, plus a frontend test confirming no OAuth/Connect UI affordance renders and the PAT input remains `type="password"` (AC3/NFR3).
- No database schema changes were required; verified the current alembic head (`0059_add_credentials.py`) before concluding no migration was needed.
- Scope was strictly limited to Story 3.5 — no TrackerLink attach (3.2), tracker sync (3.3), or approval flow (3.4) code was touched.

### File List

- `backend/tests/integration/test_api_credentials.py` (modified — added `TestProviderGuidance` AC-pinning tests and OAuth-absence tests)
- `frontend/src/components/__tests__/IntegrationsSettings.test.tsx` (modified — added OAuth-absence test)
- `_bmad-output/implementation-artifacts/3-5-see-per-provider-pat-scope-guidance.md` (new — this story file)
- `_bmad-output/implementation-artifacts/sprint-status.yaml` (modified — 3-5 status transitions)

## Change Log

- 2026-08-10: Verified Story 3.1's existing `/settings/credentials/guidance` content and `IntegrationsSettings.tsx` rendering fully satisfy Story 3.5's ACs; added backend and frontend test coverage pinning each AC (exact per-provider scope phrases, approval-gate framing, and PAT-only/no-OAuth guarantee). No production code changes were required. Status set to `review`.
