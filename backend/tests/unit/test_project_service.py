"""Tests for ProjectService — NFR5 enforcement and repo registration reuse."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from backend.config import CPLConfig
from backend.models.domain import Project, ProjectNotFoundError, RepoAlreadyAssignedError
from backend.services.project.project_service import ProjectService


def _make_project(project_id: str, name: str, repo_paths: list[str]) -> Project:
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    return Project(id=project_id, name=name, repo_paths=repo_paths, created_at=now, updated_at=now)


@pytest.fixture
def config() -> CPLConfig:
    return CPLConfig(repos=[])


@pytest.fixture
def mock_repo() -> AsyncMock:
    return AsyncMock()


class TestProjectServiceCreate:
    @pytest.mark.asyncio
    async def test_create_registers_each_repo_path(self, mock_repo: AsyncMock, config: CPLConfig) -> None:
        mock_repo.list_all_repo_paths.return_value = {}
        mock_repo.create.return_value = _make_project("proj-1", "Test", ["/repo/a", "/repo/b"])
        service = ProjectService(mock_repo, config)

        with patch("backend.services.project.project_service.register_repo") as mock_register:
            project = await service.create("Test", ["/repo/a", "/repo/b"])

        assert project.id == "proj-1"
        assert mock_register.call_count == 2
        mock_repo.create.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_create_rejects_repo_already_assigned(self, mock_repo: AsyncMock, config: CPLConfig) -> None:
        import backend.services.project.project_service as mod

        resolved = mod.ProjectService._resolve("/repo/a")
        mock_repo.list_all_repo_paths.return_value = {resolved: "other-project"}
        service = ProjectService(mock_repo, config)

        with pytest.raises(RepoAlreadyAssignedError):
            await service.create("Test", ["/repo/a"])

        mock_repo.create.assert_not_called()


class TestProjectServiceUpdate:
    @pytest.mark.asyncio
    async def test_update_name_does_not_touch_repo_paths(self, mock_repo: AsyncMock, config: CPLConfig) -> None:
        existing = _make_project("proj-1", "Old", ["/repo/a"])
        mock_repo.get.return_value = existing
        mock_repo.update.return_value = _make_project("proj-1", "New", ["/repo/a"])
        service = ProjectService(mock_repo, config)

        with patch("backend.services.project.project_service.register_repo") as mock_register:
            updated = await service.update("proj-1", name="New")

        assert updated.name == "New"
        mock_register.assert_not_called()
        mock_repo.update.assert_awaited_once_with("proj-1", name="New", repo_paths=None)

    @pytest.mark.asyncio
    async def test_update_adds_new_repo_path_and_registers_it(
        self, mock_repo: AsyncMock, config: CPLConfig
    ) -> None:
        import backend.services.project.project_service as mod

        existing_path = mod.ProjectService._resolve("/repo/a")
        existing = _make_project("proj-1", "Test", [existing_path])
        mock_repo.get.return_value = existing
        mock_repo.list_all_repo_paths.return_value = {}
        mock_repo.update.return_value = _make_project(
            "proj-1", "Test", [existing_path, mod.ProjectService._resolve("/repo/b")]
        )
        service = ProjectService(mock_repo, config)

        with patch("backend.services.project.project_service.register_repo") as mock_register:
            updated = await service.update("proj-1", repo_paths=["/repo/a", "/repo/b"])

        assert len(updated.repo_paths) == 2
        # Only the newly added repo path should be (re-)registered.
        assert mock_register.call_count == 1

    @pytest.mark.asyncio
    async def test_update_rejects_repo_assigned_to_another_project(
        self, mock_repo: AsyncMock, config: CPLConfig
    ) -> None:
        import backend.services.project.project_service as mod

        existing = _make_project("proj-1", "Test", ["/repo/a"])
        mock_repo.get.return_value = existing
        resolved = mod.ProjectService._resolve("/repo/b")
        mock_repo.list_all_repo_paths.return_value = {resolved: "other-project"}
        service = ProjectService(mock_repo, config)

        with pytest.raises(RepoAlreadyAssignedError):
            await service.update("proj-1", repo_paths=["/repo/a", "/repo/b"])

        mock_repo.update.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_missing_project_raises_not_found(self, mock_repo: AsyncMock, config: CPLConfig) -> None:
        mock_repo.get.return_value = None
        service = ProjectService(mock_repo, config)

        with pytest.raises(ProjectNotFoundError):
            await service.update("does-not-exist", name="X")


class TestProjectServiceGetList:
    @pytest.mark.asyncio
    async def test_get_missing_raises_not_found(self, mock_repo: AsyncMock, config: CPLConfig) -> None:
        mock_repo.get.return_value = None
        service = ProjectService(mock_repo, config)

        with pytest.raises(ProjectNotFoundError):
            await service.get("does-not-exist")

    @pytest.mark.asyncio
    async def test_list_delegates_to_repo(self, mock_repo: AsyncMock, config: CPLConfig) -> None:
        projects = [_make_project("proj-1", "A", ["/repo/a"])]
        mock_repo.list.return_value = projects
        service = ProjectService(mock_repo, config)

        result = await service.list()
        assert result == projects
