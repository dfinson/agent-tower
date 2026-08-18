"""Canonical repository membership and Project repo-path helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Iterable

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from backend.config import CPLConfig
    from backend.persistence.project_repo import ProjectRepository


class ProjectRepoPathRecord(Protocol):
    """Minimal shape needed to resolve Project ownership for a repo path."""

    id: str
    repo_paths: str | None


def parse_project_repo_paths(repo_paths_json: str | None) -> list[str]:
    """Decode a persisted Project ``repo_paths`` JSON string."""
    if not repo_paths_json:
        return []
    return list(json.loads(repo_paths_json))


def normalize_repo_path(repo_path: str) -> str:
    """Canonicalize a repo path for equality checks across path spellings."""
    return str(Path(repo_path).expanduser().resolve())


def resolve_matching_project_id(
    repo_path: str,
    project_rows: Iterable[ProjectRepoPathRecord],
) -> str | None:
    """Return the sole matching Project ID for ``repo_path``, if any.

    Best-effort semantics: return a Project ID only when exactly one Project's
    persisted ``repo_paths`` contains the repo. Ambiguous or missing matches
    intentionally resolve to ``None`` so callers never guess.
    """
    normalized_repo = normalize_repo_path(repo_path)
    matches = [
        row.id
        for row in project_rows
        if any(normalize_repo_path(path) == normalized_repo for path in parse_project_repo_paths(row.repo_paths))
    ]
    return matches[0] if len(matches) == 1 else None


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
