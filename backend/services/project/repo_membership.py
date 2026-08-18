"""Canonical repository membership derived from Projects plus legacy config."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from backend.config import CPLConfig
    from backend.persistence.project_repo import ProjectRepository


async def list_managed_repo_paths(
    config: CPLConfig,
    project_repo: ProjectRepository,
) -> list[str]:
    """Return each managed repository once, with Projects as the primary source."""
    project_paths = await project_repo.list_all_repo_paths()
    return sorted(set(config.repos) | set(project_paths))


async def list_managed_repo_paths_from_factory(
    config: CPLConfig,
    session_factory: async_sessionmaker[AsyncSession],
) -> list[str]:
    """Resolve live managed membership for background services."""
    from backend.persistence.project_repo import ProjectRepository

    async with session_factory() as session:
        return await list_managed_repo_paths(config, ProjectRepository(session))
