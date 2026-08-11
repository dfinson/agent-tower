"""Project CRUD orchestration (Story 2.1 / CAP-6).

``ProjectRow`` is the sole persistence entity for repo-path membership
(AD-5). Creating or editing a Project reuses the existing clone/register
logic in :mod:`backend.config` so the legacy ``codeplane_repo`` allowlist
stays authoritative and in sync — this service never duplicates or bypasses
it, only calls into it.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from backend.config import register_repo
from backend.models.domain import Project, ProjectNotFoundError, ProjectSummary, RepoAlreadyAssignedError

if TYPE_CHECKING:
    from builtins import list as builtins_list

    from backend.config import CPLConfig
    from backend.persistence.project_repo import ProjectRepository


class ProjectService:
    """Orchestrates Project creation and membership edits."""

    def __init__(self, project_repo: ProjectRepository, config: CPLConfig) -> None:
        self._project_repo = project_repo
        self._config = config

    @staticmethod
    def _resolve(repo_path: str) -> str:
        return str(Path(repo_path).expanduser().resolve())

    async def _assert_repo_paths_available(
        self, repo_paths: builtins_list[str], *, exclude_project_id: str | None
    ) -> None:
        """Raise RepoAlreadyAssignedError if any repo_path belongs to another Project (NFR5)."""
        existing = await self._project_repo.list_all_repo_paths(exclude_project_id=exclude_project_id)
        for path in repo_paths:
            owner = existing.get(path)
            if owner is not None:
                raise RepoAlreadyAssignedError(f"Repo path '{path}' already belongs to Project '{owner}'.")

    async def create(self, name: str, repo_paths: builtins_list[str]) -> Project:
        """Create a new Project, registering each repo path via the existing clone/register logic."""
        resolved = [self._resolve(p) for p in repo_paths]
        await self._assert_repo_paths_available(resolved, exclude_project_id=None)

        for path in resolved:
            register_repo(self._config, path)

        project_id = str(uuid.uuid4())
        return await self._project_repo.create(project_id, name, resolved)

    async def get(self, project_id: str) -> Project:
        project = await self._project_repo.get(project_id)
        if project is None:
            raise ProjectNotFoundError(f"Project '{project_id}' does not exist.")
        return project

    async def list(self) -> builtins_list[Project]:
        return await self._project_repo.list()

    async def update(
        self,
        project_id: str,
        name: str | None = None,
        repo_paths: builtins_list[str] | None = None,
    ) -> Project:
        """Rename a Project and/or replace its repo membership.

        When ``repo_paths`` is provided, it replaces the Project's full
        membership list (add/remove semantics are expressed by the caller
        passing the desired resulting set).
        """
        existing = await self.get(project_id)

        resolved_repo_paths: builtins_list[str] | None = None
        if repo_paths is not None:
            resolved_repo_paths = [self._resolve(p) for p in repo_paths]
            await self._assert_repo_paths_available(resolved_repo_paths, exclude_project_id=project_id)
            new_paths = set(resolved_repo_paths) - set(existing.repo_paths)
            for path in new_paths:
                register_repo(self._config, path)

        updated = await self._project_repo.update(project_id, name=name, repo_paths=resolved_repo_paths)
        if updated is None:
            raise ProjectNotFoundError(f"Project '{project_id}' does not exist.")
        return updated

    async def summary_all(self) -> builtins_list[ProjectSummary]:
        """Batch Overview summary for every Project (Story 2.2 / CAP-2).

        Computes active/awaitingInput/failed job counts and last-activity per
        Project from a single cross-Project job query — never N sequential
        per-Project fetches. Projects with no jobs at all still appear with
        all-zero counts (never omitted).
        """
        projects = await self._project_repo.list()

        all_repo_paths = sorted({path for project in projects for path in project.repo_paths})
        counts_by_repo = await self._project_repo.job_counts_by_repo(all_repo_paths)

        summaries: builtins_list[ProjectSummary] = []
        for project in projects:
            summary = ProjectSummary(id=project.id, name=project.name, repo_paths=project.repo_paths)
            for repo_path in project.repo_paths:
                bucket = counts_by_repo.get(repo_path)
                if bucket is None:
                    continue
                summary.active_job_count += bucket.active
                summary.awaiting_input_count += bucket.awaiting
                summary.failed_count += bucket.failed
                if summary.last_activity_at is None or (
                    bucket.last_activity is not None and bucket.last_activity > summary.last_activity_at
                ):
                    summary.last_activity_at = bucket.last_activity
            summaries.append(summary)
        return summaries
