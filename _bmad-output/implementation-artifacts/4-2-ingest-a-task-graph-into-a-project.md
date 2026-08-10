---
baseline_commit: 162d97a2
---

# Story 4.2: Ingest a task graph into a Project

Status: review

## Story

As a CodePlane user who has run BMAD or spec-kit,
I want to ingest my existing dependency-linked task list into a Project,
so that I don't have to hand-author board cards for work already planned.

## Acceptance Criteria

1. **Given** a Project with 2+ member repos, each containing BMAD stories or a spec-kit `tasks.md`, **when** I trigger ingestion for that Project, **then** one `TaskLink` is created per task, namespaced by `(project_id, repo_path, story_node_id)`, with `depends_on` correctly resolving to a sibling member repo's task when referenced.
2. **Given** ingestion has already run once for a Project, **when** I re-run it, **then** existing `TaskLink`s are upserted (matched by `project_id`, `repo_path`, `story_node_id`), never duplicated.
3. **Given** the source repo's story/task files, **when** ingestion runs, **then** the source files are read-only — never modified, and never ingested across a Project boundary.

## Tasks / Subtasks

- [x] Add `TaskLinkRow` persistence (AC: #1, #2)
  - [x] `TaskLinkRow` model in `backend/models/db.py` (`id`, `project_id`, `repo_path`, `story_node_id: nullable`, `depends_on: JSON list[str]`, `job_id: nullable`, `tracker_ticket_ref: nullable`, `prompt_override: nullable`, `epic_id: nullable`), with a unique constraint on `(project_id, repo_path, story_node_id)`.
  - [x] Alembic migration for the new `task_links` table (verify the true current alembic head via `git log origin/main -- alembic/versions/` immediately before finalizing, and use the next free revision number).
  - [x] `TaskLink` domain dataclass in `backend/models/domain.py`.
  - [x] `TaskLinkRepository` in `backend/persistence/task_link_repo.py`: `upsert_many` (matched by `project_id`/`repo_path`/`story_node_id`, never duplicating), `list_by_project`.
- [x] Implement stateless ingestion parsing (AC: #1, #3)
  - [x] `backend/services/recipe/parsers.py`: `parse_bmad_stories(repo_path)` reads `_bmad-output/implementation-artifacts/*.md` story files (read-only), deriving `story_node_id` from the filename stem, `epic_id` from the `{epic}-{story}-...` filename prefix, and `depends_on` from an explicit `## Dependencies` section (bare `story_node_id` for same-repo, `repo-folder-name/story_node_id` for cross-repo references).
  - [x] `parse_spec_kit_tasks(repo_path)` reads a `tasks.md` (repo root or `specs/**/tasks.md`, read-only), deriving `story_node_id` from the leading `T\d+` task id and `depends_on` from a `depends on: ...` annotation on the task line (bare id for same-repo, `repo-folder-name/task_id` for cross-repo).
  - [x] Neither parser writes to the source repo; both tolerate a missing source (return an empty list) rather than failing ingestion for the whole Project.
- [x] Implement `RecipeService.ingest_project` (AC: #1, #2, #3)
  - [x] `backend/services/recipe/recipe_service.py`: given a `project_id`, iterate every repo in `project.repo_paths`, run both parsers per repo, resolve `depends_on` cross-repo references against the full set of parsed nodes for the Project (composite `f"{repo_path}::{story_node_id}"` keys), and upsert one `TaskLinkRow` per parsed task via `TaskLinkRepository.upsert_many`.
  - [x] Re-running ingestion for the same Project never creates duplicate rows (upsert by `project_id`/`repo_path`/`story_node_id`).
  - [x] Ingestion never reads or writes outside the Project's own `project.repo_paths` and never mutates the source repos.
- [x] Expose ingestion trigger (AC: #1)
  - [x] `POST /settings/projects/{project_id}/ingest-tasks` in `backend/api/projects.py` (thin route, delegates to `RecipeService`), returning the upserted `TaskLink` set.
  - [x] `GET /settings/projects/{project_id}/task-links` to list a Project's current `TaskLink` rows (read model foundation for the later board-rendering story, AD-11).
  - [x] `ingest_tasks` action added to the existing `codeplane_project` MCP tool, mirroring the HTTP-proxy pattern of `list`/`get`/`create`/`update`.
  - [x] DI wiring for `TaskLinkRepository`/`RecipeService` in `backend/di.py`.
- [x] Tests (AC: #1, #2, #3)
  - [x] Parser unit tests with fixture BMAD story files and `tasks.md` files (same-repo and cross-repo dependency references).
  - [x] `TaskLinkRepository` unit tests (upsert insert + upsert update, list by project).
  - [x] `RecipeService.ingest_project` unit tests (multi-repo Project, cross-repo `depends_on` resolution, idempotent re-run, read-only guarantee).
  - [x] API integration test for the ingest/list endpoints.
  - [x] Run targeted test suite and lint.

## Dev Notes

- CAP-9 (`_bmad-output/specs/spec-project-boards/SPEC.md`) / AD-9 (`ARCHITECTURE-SPINE.md`): `TaskLinkRow` is a new, thin, Project-scoped table owned by a new `recipe_service.py`; ingestion is a **stateless, on-demand parser** (explicitly user-triggered), never a background watcher/poller.
- Exactly one of `story_node_id` / `tracker_ticket_ref` is guaranteed non-null at creation for any `TaskLink` — ingestion (this story) always sets `story_node_id` and leaves `tracker_ticket_ref`/`prompt_override` null. Manual assignment (Story 4.3, tracker_ticket_ref + prompt_override with null story_node_id) is a separate, independent creation path — **do not implement it here**.
- `epic_id` is purely cosmetic grouping data, only ever populated by ingestion when the source BMAD story has identifiable Epic membership (derivable unambiguously from the existing `{epic}-{story}-{slug}.md` filename convention already used in `_bmad-output/implementation-artifacts/`, matching the `epic-{N}` keys already used in `sprint-status.yaml`). Never invent/guess it — leave null when absent or ambiguous (e.g. spec-kit `tasks.md` sourced tasks always get a null `epic_id`, since spec-kit has no Epic concept).
- `story_node_id` is only unique within one repo, so `depends_on` needs a way to disambiguate cross-repo references. Store `TaskLinkRow.depends_on` as a JSON list of composite `f"{repo_path}::{story_node_id}"` strings (resolved by the service, not the parsers) so an edge always unambiguously names its target `TaskLink`, whether same-repo or a sibling member repo of the same Project.
- Ingestion is Project-scoped only: it iterates exactly `project.repo_paths` (AD-5), never any repo outside that Project's membership, and never reads/writes the source BMAD story files or spec-kit `tasks.md` — parse-only, no mutation, matching CAP-9's "never taking ownership of source repos" success criterion.
- Do NOT implement: manual ticket assignment (4.3), TaskLink board cards / `RepoBoard.tsx` rendering (4.4), auto-spawn via `spawn_task` (4.5), or tracker-write routing (4.6) — those are separate, dependent stories. This story is ingestion + persistence + read endpoints only.
- Follow existing repo conventions exactly (see Story 2.1's `ProjectRow`/`ProjectService`/`ProjectRepository`/`backend/api/projects.py`/`codeplane_project` MCP tool as the closest precedent): thin API routes delegating to a service, all DB access through a repository class, DI wiring in `backend/di.py`, `CamelModel`-based Pydantic schemas in `backend/models/api_schemas.py`, domain exceptions in `backend/models/domain.py` registered in `backend/app_factory.py`'s exception handlers.
- Story 2.1 (`ProjectRow`, `ProjectService`, repo-path uniqueness) is a **hard dependency** — must exist on `main` before this story starts (it does, merged as PR #54, commit `162d97a2`). Story 4.1 (widened sidecar recipe vocabulary, merged as `ecc42c77`) is a sibling story with no code dependency on this one — it only widened `template_service.py`'s validation vocabulary and does not touch `TaskLinkRow` at all.
- **Before creating the migration file or finalizing the PR**, run `git log origin/main -- alembic/versions/` to find the true current alembic head — multiple parallel stories may have added migrations concurrently, so re-verify the next free revision number immediately before finalizing rather than trusting a number determined earlier in the session.

### Project Structure Notes

- New: `backend/services/recipe/__init__.py`, `backend/services/recipe/recipe_service.py`, `backend/services/recipe/parsers.py`, `backend/persistence/task_link_repo.py`, `alembic/versions/00NN_add_task_links.py` (NN = next free number, re-verified at finalization time).
- Modified: `backend/models/db.py` (add `TaskLinkRow`), `backend/models/domain.py` (add `TaskLink` dataclass), `backend/models/api_schemas.py` (add `TaskLinkResponse`/`IngestTaskGraphResponse`/`TaskLinkListResponse`), `backend/api/projects.py` (add ingest/list routes), `backend/di.py` (wire `TaskLinkRepository`/`RecipeService`), `backend/mcp/server.py` (extend `codeplane_project` tool with `ingest_tasks`).
- No frontend changes in this story — `ProjectSettings.tsx`'s ingestion trigger button and `RepoBoard.tsx`'s TaskLink-card rendering are explicitly out of scope (deferred to 4.4+), matching Story 2.1's precedent of backend+MCP-only scope with frontend deferred to later stories.

### References

- [Source: `_bmad-output/planning-artifacts/epics.md#Story-42-Ingest-a-task-graph-into-a-Project`]
- [Source: `_bmad-output/specs/spec-project-boards/SPEC.md#CAP-9`]
- [Source: `_bmad-output/planning-artifacts/architecture/architecture-codeplane-2026-08-10/ARCHITECTURE-SPINE.md#AD-9`]
- [Source: `_bmad-output/implementation-artifacts/2-1-create-edit-a-project.md` — closest precedent for Project-scoped, thin-route, repository-owned persistence pattern]

## Dev Agent Record

### Agent Model Used

Claude Sonnet 5 (GitHub Copilot CLI).

### Debug Log References

- `uv run pytest backend/tests/unit/test_task_link_repo.py backend/tests/unit/test_recipe_parsers.py backend/tests/unit/test_recipe_service.py backend/tests/integration/test_api_task_links.py -q` → 29 passed.
- `uv run pytest backend/tests/unit/test_project_repo.py backend/tests/integration/test_api_projects.py backend/tests/unit -q -k "project or task_link or recipe"` → 22 passed (no regressions on Project/sidecar-adjacent tests).
- `uv run ruff check` on all new/modified files → clean (after one `--unsafe-fixes` pass for `TC003` import-into-type-checking-block on new test files).
- Alembic head re-verified via `git log`/`git ls-tree origin/main -- alembic/versions/` immediately before finalizing: still `0060_add_projects.py`. Initially used `0062_add_task_links.py`, renumbered from `0061` to `0062` after PR #58 (Story 5.2, `0061_add_chat_messages.py`) claimed `0061` concurrently from the same head.

### Completion Notes List

- Implemented `TaskLinkRow`/`TaskLink`/`TaskLinkRepository` per AD-9, with a unique `(project_id, repo_path, story_node_id)` index and upsert-by-that-key semantics (AC #2).
- Implemented stateless, read-only parsers for BMAD stories (`_bmad-output/implementation-artifacts/*.md`) and spec-kit `tasks.md`. Since neither upstream format has an established dependency-annotation convention in this codebase, I documented and used: a `## Dependencies` markdown section (bullet list) for BMAD stories, and a `depends on: ...` inline annotation for spec-kit task lines. This is a defensible, explicit convention per SPEC.md's "Assumption" callout, not a pre-existing standard — called out here and in the PR description for visibility.
- `RecipeService.ingest_project` resolves cross-repo `depends_on` references against composite `repo_path::story_node_id` keys, is idempotent (upsert, AC #2), and never reads/writes outside `project.repo_paths` (AC #3, verified by `test_ingest_never_writes_to_source_repo`).
- Added `POST .../ingest-tasks` and `GET .../task-links` thin routes, `codeplane_project` MCP actions (`ingest_tasks`, `list_task_links`), and DI wiring.
- Scope strictly excludes Stories 4.3 (manual ticket assignment), 4.4 (board rendering), 4.5 (auto-spawn), 4.6 (tracker-write routing) — confirmed no code in this PR touches those paths.
- No frontend changes, matching Story 2.1's backend+MCP-only precedent (frontend UI deferred to 4.4+).

### File List

**New:**
- `alembic/versions/0062_add_task_links.py`
- `backend/persistence/task_link_repo.py`
- `backend/services/recipe/__init__.py`
- `backend/services/recipe/parsers.py`
- `backend/services/recipe/recipe_service.py`
- `backend/tests/unit/test_task_link_repo.py`
- `backend/tests/unit/test_recipe_parsers.py`
- `backend/tests/unit/test_recipe_service.py`
- `backend/tests/integration/test_api_task_links.py`

**Modified:**
- `backend/models/db.py`
- `backend/models/domain.py`
- `backend/models/api_schemas.py`
- `backend/api/projects.py`
- `backend/di.py`
- `backend/mcp/server.py`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`
