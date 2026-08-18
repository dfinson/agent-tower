from unittest.mock import AsyncMock

import pytest

from backend.config import CPLConfig
from backend.services.project.repo_membership import list_managed_repo_paths


@pytest.mark.asyncio
async def test_managed_repo_paths_unions_projects_and_legacy_without_duplicates() -> None:
    project_repo = AsyncMock()
    project_repo.list_all_repo_paths.return_value = {
        "/repos/project-only": "project-1",
        "/repos/shared": "project-2",
    }
    config = CPLConfig(repos=["/repos/legacy", "/repos/shared"])

    result = await list_managed_repo_paths(config, project_repo)

    assert result == ["/repos/legacy", "/repos/project-only", "/repos/shared"]
