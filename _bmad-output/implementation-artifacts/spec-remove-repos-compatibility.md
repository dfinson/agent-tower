---
title: 'Remove legacy repos route compatibility'
type: 'chore'
created: '2026-08-16'
status: 'done'
review_loop_iteration: 0
baseline_commit: '1a55091ee0c0e1e3e1b074f8254a8a08a5f43701'
context:
  - '{project-root}/SPEC.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The application still exposes `/repos` and nested `/repos/:repoPath/*` routes as a compatibility surface. This preserves the obsolete repo-first information architecture after the product has adopted projects as the primary identity and navigation model.

**Approach:** Remove every legacy `/repos` application route and make `/projects` the only route family for the project shell. Update route-level tests so they verify the canonical path rather than the removed compatibility path.

## Boundaries & Constraints

**Always:** Preserve the existing project shell and all `/projects/:repoPath/*` destination behavior. Keep repository filesystem paths and API endpoints unchanged; only browser navigation paths are in scope.

**Ask First:** None.

**Never:** Add redirects, aliases, fallbacks, or other compatibility behavior for `/repos`. Do not rename backend repository API endpoints or data fields as part of this change.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Canonical project route | `/projects/<encoded-repo>/board` | The project board renders in the project shell. | Existing route error handling applies. |
| Removed legacy route | `/repos/<encoded-repo>/board` | No application route matches. | The legacy URL is intentionally unsupported. |

</frozen-after-approval>

## Code Map

- `frontend/src/App.tsx` -- owns the top-level route table and currently mounts the legacy compatibility route family.
- `frontend/src/App.test.tsx` -- verifies top-level route behavior and currently asserts the legacy board path.

## Tasks & Acceptance

**Execution:**
- [x] `frontend/src/App.tsx` -- delete the `/repos` route family while retaining the `/projects` nested route family -- eliminate the obsolete repo-first browser surface.
- [x] `frontend/src/App.test.tsx` -- change the board route test to the canonical `/projects` URL -- protect the supported navigation contract.

**Acceptance Criteria:**
- Given a user opens the root URL, when routing completes, then the project overview is reached through `/projects`.
- Given a user opens `/projects/<encoded-repo>/board`, when the route resolves, then the project board renders.
- Given source route definitions are inspected, when the application route table is evaluated, then no `/repos` route is registered.

## Spec Change Log

## Verification

**Commands:**
- `npx vitest run src/App.test.tsx` -- expected: all app route tests pass.
- `npm run typecheck` -- expected: TypeScript completes without errors.

## Suggested Review Order

**Canonical application routing**

- Makes Projects the sole browser-level shell and removes the legacy route family.
  [`App.tsx:209`](../../frontend/src/App.tsx#L209)

**Canonical route coverage**

- Confirms root and board navigation resolve through the supported project paths.
  [`App.test.tsx:82`](../../frontend/src/App.test.tsx#L82)

- Exercises project shell mounting rather than the retired repo route.
  [`RepoLayout.test.tsx:22`](../../frontend/src/components/__tests__/RepoLayout.test.tsx#L22)

- Exercises integration settings on the canonical nested project path.
  [`RepoSettings.test.tsx:94`](../../frontend/src/components/__tests__/RepoSettings.test.tsx#L94)

- Exercises board routing with an encoded repository member under Projects.
  [`RepoBoard.test.tsx:58`](../../frontend/src/components/__tests__/RepoBoard.test.tsx#L58)
