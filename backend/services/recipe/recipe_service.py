"""Task Recipe ingestion orchestration (Story 4.2, CAP-9/AD-9).

``RecipeService.ingest_project`` is a stateless, on-demand function — never
a background watcher/poller. It is Project-scoped: it iterates exactly
``project.repo_paths`` (AD-5), parses each member repo's BMAD stories and
spec-kit ``tasks.md`` independently and read-only, resolves ``depends_on``
edges into unambiguous composite ``"{repo_path}::{story_node_id}"`` keys
across the whole Project (since ``story_node_id`` is only unique within one
repo), and upserts one ``TaskLinkRow`` per parsed task — never duplicating
across re-runs.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from backend.services.recipe.parsers import ParsedTask, parse_bmad_stories, parse_spec_kit_tasks

if TYPE_CHECKING:
    from backend.models.domain import TaskLink
    from backend.persistence.task_link_repo import TaskLinkRepository
    from backend.services.project.project_service import ProjectService


class RecipeService:
    """Orchestrates TaskLink ingestion for a Project."""

    def __init__(self, task_link_repo: TaskLinkRepository, project_service: ProjectService) -> None:
        self._task_link_repo = task_link_repo
        self._project_service = project_service

    @staticmethod
    def _resolve_dependency(raw: str, *, current_repo_path: str, repo_path_by_folder: dict[str, str]) -> str:
        """Resolve a raw (bare or ``folder/id``) dependency reference to a composite key.

        A bare id resolves against ``current_repo_path``. An id containing a
        ``/`` resolves the part before the last ``/`` as a sibling repo's
        folder name (``Path(repo_path).name``); if no member repo matches
        that folder name, the raw string is preserved as-is (best-effort,
        never raises) so a single unresolvable reference never fails the
        whole ingestion run.
        """
        if "/" in raw:
            folder, _, node_id = raw.rpartition("/")
            matched_repo = repo_path_by_folder.get(folder)
            if matched_repo is not None:
                return f"{matched_repo}::{node_id}"
            return raw
        return f"{current_repo_path}::{raw}"

    async def ingest_project(self, project_id: str) -> list[TaskLink]:
        """Ingest BMAD stories and spec-kit tasks for every member repo of a Project.

        Read-only against every source repo; never reads or writes outside
        ``project.repo_paths``. Re-running is idempotent: existing
        ``TaskLink``s are upserted by ``(project_id, repo_path,
        story_node_id)``, never duplicated.
        """
        project = await self._project_service.get(project_id)
        repo_path_by_folder = {Path(p).name: p for p in project.repo_paths}

        parsed_by_repo: dict[str, list[ParsedTask]] = {}
        for repo_path in project.repo_paths:
            parsed = parse_bmad_stories(repo_path) + parse_spec_kit_tasks(repo_path)
            parsed_by_repo[repo_path] = parsed

        entries: list[dict[str, object]] = []
        for repo_path, parsed_tasks in parsed_by_repo.items():
            for task in parsed_tasks:
                resolved_depends_on = [
                    self._resolve_dependency(
                        dep,
                        current_repo_path=repo_path,
                        repo_path_by_folder=repo_path_by_folder,
                    )
                    for dep in task.depends_on
                ]
                entries.append(
                    {
                        "repo_path": repo_path,
                        "story_node_id": task.story_node_id,
                        "depends_on": resolved_depends_on,
                        "epic_id": task.epic_id,
                    }
                )

        return await self._task_link_repo.upsert_many(project_id, entries)

    async def list_task_links(self, project_id: str) -> list[TaskLink]:
        """List every TaskLink currently persisted for a Project."""
        # Ensure the Project exists (raises ProjectNotFoundError otherwise).
        await self._project_service.get(project_id)
        return await self._task_link_repo.list_by_project(project_id)
