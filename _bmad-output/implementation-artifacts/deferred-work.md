# Deferred work — RESOLVED

All items previously tracked in this file have been fixed directly (not deferred):

- Project chat stale-response race → fixed in `frontend/src/components/ProjectChats.tsx` (cancellation guard on the load effect).
- Unscoped chat creation → fixed in `frontend/src/components/ProjectChats.tsx` (`startChat` now blocks with an error when no owning project is found).
- Job authorization vs. project membership → fixed in `backend/services/job/job_service.py` (`validate_repo_async`/`_resolve_project_member_repos`), wired into all 3 `JobService` construction sites (`backend/di.py`, `backend/mcp/server.py`, `backend/services/runtime/service.py`). Covered by new tests in `backend/tests/unit/test_job_service.py`.
- Project onboarding flow → `CreateProjectDialog.tsx` added, wired into `ProjectsOverview.tsx`'s empty state and a persistent header action. Covered by `CreateProjectDialog.test.tsx` and new `ProjectsOverview.test.tsx` cases.
- Project-summary-as-optional-enrichment → fixed in `frontend/src/components/RepoOverview.tsx` (project-summary failure no longer fails the whole view).
