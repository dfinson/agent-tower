---
title: 'Resolve project-first review findings'
type: 'bugfix'
created: '2026-08-17T21:46:03-04:00'
status: 'complete'
review_loop_iteration: 0
baseline_commit: '5edb5df13178adb3e3f5d2e5df297ec3862a5356'
context:
  - '{project-root}/SPEC.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The project-first implementation has correctness gaps across transaction ordering, tracker authentication and identity, chain scoping, Project repository membership, MCP lifecycle enforcement, and frontend navigation/actions. These gaps can start jobs before persistence is visible, route writes incorrectly, retain stale UI state, or expose legacy repository behavior.

**Approach:** Repair all reviewed behaviors using existing Project, TaskLink, TrackerLink, route/service, and generated-client patterns. Add focused regression tests for each changed contract and preserve unrelated behavior.

## Boundaries & Constraints

**Always:** Keep Project as the sole repository-membership owner; commit durable job/task state before runtime scheduling; keep network I/O outside SQLite write transactions; use provider-correct token headers; keep generated API types authoritative; expose explicit errors and destructive confirmations.

**Ask First:** No decisions remain—the user explicitly required every listed finding and authorized production/test changes.

**Never:** Reintroduce implicit first-repository selection, standalone MCP repository lifecycle mutations, Project-wide chain gating, silent stale state, or compensation of pre-existing repository registrations. Do not defer any finding or refactor unrelated areas.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|---------------|---------------------------|----------------|
| Tracker write | GitHub/Jira credential token | Provider receives a real token-derived Authorization header | Adapter errors remain sanitized |
| Synced GitHub issue | Project item contains repository identity | Persist `owner/repository#number` for later writes | Draft items retain stable item identity |
| Chain completion | Another chain in same Project has an attached Chat | Current chain auto-spawns without gating | Exact attached chain alone gates |
| Project navigation | Unknown Project or non-member repo path | Previous state is removed and explicit error/redirect shown | No stale Project details render |
| Project creation rollback | Existing legacy registration reused | Existing registration remains | Only newly-created registration is compensated |
| Job creation | Repositories loaded, none selected | Submission stays disabled with explicit selection guidance | No repository is chosen implicitly |

</frozen-after-approval>

## Code Map

- `backend/api/projects.py`, `backend/services/recipe/recipe_service.py` -- task start ordering and chain-scoped gating.
- `backend/services/tracker_adapter.py`, `backend/api/tracker_links.py` -- tracker auth, ticket identity, and validation transaction boundary.
- `backend/api/settings.py`, `backend/lifespan.py`, `backend/mcp/server.py` -- Project repository membership and MCP lifecycle.
- `frontend/src/components/ProjectChats.tsx`, `RepoSettings.tsx`, `RepoLayout.tsx` -- Project-scoped controls, errors, confirmations, and routing.
- `frontend/src/components/CreateProjectDialog.tsx`, `JobCreationScreen.tsx`, `ProjectsOverview.tsx`, `frontend/src/App.tsx` -- compensation, explicit selection, canonical navigation, and safe legacy redirects.

## Tasks & Acceptance

**Execution:**
- [x] Update backend routes/services/adapters and repository membership consumers for findings 1–4, 6, 8, and 12.
- [x] Update API response contracts/client helpers so registration provenance and chat/tracker actions are explicit.
- [x] Update frontend components for findings 5, 7, 9–11, and 13–15.
- [x] Add or adjust focused backend and frontend regression tests.
- [x] Regenerate OpenAPI TypeScript declarations and run targeted tests, backend lint/type checks, frontend lint/typecheck/build.

**Acceptance Criteria:**
- Given a TaskLink start creates durable state, when runtime setup is queued, then its transaction has already committed.
- Given tracker credentials and GitHub-synced issues, when reads or writes occur, then authentication and ticket refs are provider-valid.
- Given multiple chains in one Project, when one has an attached Chat, then only that exact chain is gated.
- Given Project-only repositories, when listing, indexing, or cleanup runs, then every Project member is included once.
- Given Project UI actions and routing failures, when users launch, attach, detach, navigate, or create work, then state is explicit, scoped, confirmed where destructive, and never silently defaulted.

## Spec Change Log

## Design Notes

Use set-union membership derived from `ProjectRepository.list_all_repo_paths()` plus legacy `config.repos` only at compatibility boundaries. Registration responses carry whether the current call added legacy membership so compensation has exact provenance.

## Verification

**Commands:**
- `uv run pytest <focused backend modules> -q` -- expected: all focused backend regressions pass.
- `uv run ruff check <changed backend files>` -- expected: zero findings.
- `npm --prefix frontend test -- --run <focused frontend tests>` -- expected: all focused component/client tests pass.
- `npm --prefix frontend run typecheck && npm --prefix frontend run lint && npm --prefix frontend run build` -- expected: all frontend checks succeed.
