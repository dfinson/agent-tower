---
title: 'Chat, Project lifecycle, and multi-repository navigation'
type: 'feature'
created: '2026-08-17'
status: 'done'
baseline_commit: 'a5ba0c2c'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/specs/spec-project-boards/SPEC.md'
  - '{project-root}/_bmad-output/specs/spec-project-boards/ui-flows.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The current Project-first shell still silently chooses the first repository, Chat only appends user messages without an assistant turn, and Project membership edits can leave side effects or remove repositories without explaining consequences.

**Approach:** Harden Chat and Project ownership in services and repositories, expose a real persisted conversational turn contract, and make Project/repository context explicit and deep-linkable throughout the requested frontend surfaces.

## Boundaries & Constraints

**Always:** Preserve Project → repository → task/job context in URLs and breadcrumbs; keep Chat structurally git-free; use `{role, content}` messages with explicit sending, assistant, and failure states; retain at least one repository per Project; aggregate Project overview and Agent Runs across all members; require explicit repository selection for Jobs, Health, Cost, indexing, and repository detail; keep routes thin and database access in repositories.

**Ask First:** None; the user explicitly approved the complete cross-layer scope and autonomous implementation.

**Never:** Silently select `repoPaths[0]`; delete historical Jobs during membership edits; allow a Chat to cross Project boundaries; modify tracker adapters/MCP or TaskLink execution except unavoidable interface wiring.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Chat turn | Owned Chat plus non-empty user content | Persist user and assistant `{role, content}` messages and return assistant state | Persist the user message and return an explicit error state if completion fails |
| Chat ownership | Chat in Project A targets Project B repo/TaskLink | No mutation or execution occurs | Return a conflict |
| Project creation | Clone/register/init succeeds but Project save or dialog completion fails | Undo registration side effects where possible | Surface on-disk recovery paths that cannot be removed safely |
| Membership removal | One or more repositories removed | Require confirmation and preserve history | Block zero-repo, active-work, or TaskLink-unsafe changes with consequences |
| Multi-repo view | Project has multiple repositories | Overview totals and recent activity include every member | Partial repository-summary failures are visible and do not become first-repo fallback |
| Repository view | No member selected | Show a selector, not repository data | Do not call repo-specific APIs until selection |

</frozen-after-approval>

## Code Map

- `backend/services/chat/chat_service.py`, `backend/persistence/chat_repo.py`, `backend/api/chats.py` -- ownership, transcript, and conversational-turn lifecycle.
- `backend/services/project/project_service.py`, `backend/persistence/project_repo.py`, `backend/api/projects.py` -- membership validation, confirmation, and consequence reporting.
- `backend/models/api_schemas.py`, `backend/di.py` -- wire contracts and collaborators.
- `frontend/src/components/ProjectChats.tsx` -- deep-linked real conversation with explicit turn states.
- `frontend/src/components/CreateProjectDialog.tsx`, `RepoSettings.tsx` -- side-effect recovery, confirmation, and membership safeguards.
- `frontend/src/components/RepoLayout.tsx`, `RepoOverview.tsx`, `JobDetailScreen.tsx`, `App.tsx` -- explicit repository scope and Project/repository/job breadcrumbs.
- `frontend/src/components/NavMenuSlideout.tsx`, `CommandPalette.tsx` -- global Chat and Project-first navigation.

## Tasks & Acceptance

**Execution:**
- [x] Backend Chat files -- validate Project ownership, add scoped reads and persisted assistant turns, and retain the git-free invariant.
- [x] Backend Project files -- reject empty membership and unsafe/unconfirmed removals while preserving historical records.
- [x] Frontend lifecycle dialogs -- recover staged registration side effects and require repository-removal confirmation with consequences.
- [x] Frontend Chat/navigation -- add stable Chat routes, global entry, Project override, optimistic sending, assistant response, and inline failure state.
- [x] Frontend repository views -- aggregate overview data and remove every implicit first-member selection.
- [x] Job detail/navigation -- resolve owning Project by repository and render stable Project/repository/job breadcrumbs.
- [x] Focused backend and frontend tests -- cover ownership, zero-repo, confirmation, assistant/error turns, deep links, aggregation, and explicit selection.

**Acceptance Criteria:**
- Given a Chat and target TaskLink/repository, when their Projects differ, then the service rejects the operation before mutation.
- Given a user sends a Chat message, when completion succeeds or fails, then the persisted transcript and UI expose the corresponding assistant or error state.
- Given a Project membership edit removes repositories, when it is unconfirmed or unsafe, then it is rejected with active-work/history/TaskLink consequences and no Project becomes empty.
- Given a multi-repository Project, when overview or Agent Runs loads, then all members contribute, while repo-specific views issue no request until a member is explicit.
- Given a Project, Chat, repository, TaskLink, or Job deep link, when refreshed or traversed, then its contextual breadcrumbs and canonical URL remain intact.

## Design Notes

Chat completion uses the existing non-agentic sidecar completion surface, not a Job session, so no worktree, branch, or tool execution is introduced. Membership persistence stays atomic in the request transaction; legacy registration side effects staged by the dialog are compensated separately and any retained filesystem path is reported rather than deleted implicitly.

## Verification

**Commands:**
- `uv run pytest backend/tests/unit/test_chat_service.py backend/tests/unit/test_project_service.py backend/tests/integration/test_api_chats.py backend/tests/integration/test_api_projects.py -q` -- expected: focused backend tests pass.
- `npm test -- --run ProjectChats CreateProjectDialog RepoSettings RepoLayout RepoOverview JobDetailScreen App` from `frontend` -- expected: focused frontend tests pass.
- `npm run build` from `frontend` -- expected: TypeScript and Vite build succeeds.
- `uv run ruff check <changed backend files>` -- expected: no findings.

## Suggested Review Order

**Conversation and ownership boundaries**

- Persist one real assistant turn while keeping Chat non-agentic and git-free.
  [`chat_service.py:125`](../../backend/services/chat/chat_service.py#L125)

- Reject cross-Project repository launches and TaskLink attachments before mutation.
  [`chat_service.py:169`](../../backend/services/chat/chat_service.py#L169)

- Bind optimistic sending, assistant completion, failure recovery, and stable Chat links.
  [`ProjectChats.tsx:87`](../../frontend/src/components/ProjectChats.tsx#L87)

**Project lifecycle**

- Require confirmation and block unsafe membership removals with concrete consequences.
  [`project_service.py:69`](../../backend/services/project/project_service.py#L69)

- Compute active work, retained history, TaskLinks, and TrackerLinks in persistence.
  [`project_repo.py:121`](../../backend/persistence/project_repo.py#L121)

- Compensate staged repository registration and surface retained filesystem/index artifacts.
  [`CreateProjectDialog.tsx:109`](../../frontend/src/components/CreateProjectDialog.tsx#L109)

- Keep removal confirmation open when backend safety checks reject the change.
  [`RepoSettings.tsx:68`](../../frontend/src/components/RepoSettings.tsx#L68)

**Multi-repository navigation**

- Aggregate every member summary rather than selecting a representative repository.
  [`RepoOverview.tsx:85`](../../frontend/src/components/RepoOverview.tsx#L85)

- Require explicit URL-backed repository selection for scoped views.
  [`RepoLayout.tsx:161`](../../frontend/src/components/RepoLayout.tsx#L161)

- Resolve and display Project, repository, Task, and Job breadcrumb deep links.
  [`JobDetailScreen.tsx:578`](../../frontend/src/components/JobDetailScreen.tsx#L578)
