"""Project persistence — the sole store for repo-path membership (AD-5)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select

from backend.models.db import ProjectRow
from backend.models.domain import Project
from backend.persistence.repository import BaseRepository

if TYPE_CHECKING:
    pass


class ProjectRepository(BaseRepository):
    """Database access for Project records."""

    @staticmethod
    def _to_domain(row: ProjectRow) -> Project:
        return Project(
            id=row.id,
            name=row.name,
            repo_paths=json.loads(row.repo_paths) if row.repo_paths else [],
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def create(self, project_id: str, name: str, repo_paths: list[str]) -> Project:
        """Insert a new Project row."""
        now = datetime.now(UTC)
        row = ProjectRow(
            id=project_id,
            name=name,
            repo_paths=json.dumps(repo_paths),
            created_at=now,
            updated_at=now,
        )
        self._session.add(row)
        await self._session.flush()
        return self._to_domain(row)

    async def get(self, project_id: str) -> Project | None:
        """Get a single Project by ID."""
        stmt = select(ProjectRow).where(ProjectRow.id == project_id)
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        return self._to_domain(row) if row else None

    async def list(self) -> list[Project]:
        """List all Projects, ordered by creation time."""
        stmt = select(ProjectRow).order_by(ProjectRow.created_at)
        result = await self._session.execute(stmt)
        return [self._to_domain(row) for row in result.scalars().all()]

    async def list_all_repo_paths(self, exclude_project_id: str | None = None) -> dict[str, str]:
        """Return a mapping of ``repo_path -> project_id`` across all Projects.

        Used by the service layer to enforce NFR5 (a repo belongs to at most
        one explicit Project). ``exclude_project_id`` omits a given Project's
        own rows, so updating a Project's own repo membership doesn't
        conflict with itself.
        """
        stmt = select(ProjectRow)
        if exclude_project_id is not None:
            stmt = stmt.where(ProjectRow.id != exclude_project_id)
        result = await self._session.execute(stmt)
        mapping: dict[str, str] = {}
        for row in result.scalars().all():
            for path in json.loads(row.repo_paths) if row.repo_paths else []:
                mapping[path] = row.id
        return mapping

    async def update(
        self,
        project_id: str,
        name: str | None = None,
        repo_paths: list[str] | None = None,
    ) -> Project | None:
        """Update a Project's name and/or repo membership. Returns None if not found."""
        stmt = select(ProjectRow).where(ProjectRow.id == project_id)
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            return None
        if name is not None:
            row.name = name
        if repo_paths is not None:
            row.repo_paths = json.dumps(repo_paths)
        row.updated_at = datetime.now(UTC)
        await self._session.flush()
        return self._to_domain(row)
