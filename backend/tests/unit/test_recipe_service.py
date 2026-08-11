"""Tests for RecipeService.ingest_project — cross-repo depends_on resolution (Story 4.2, AD-9)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest

from backend.models.domain import Project
from backend.services.recipe.recipe_service import RecipeService

if TYPE_CHECKING:
    from pathlib import Path


def _make_project(project_id: str, repo_paths: list[str]) -> Project:
    now = datetime.now(UTC)
    return Project(id=project_id, name="Test Project", repo_paths=repo_paths, created_at=now, updated_at=now)


def _write_bmad_story(repo_root: Path, filename: str, body: str = "") -> None:
    stories_dir = repo_root / "_bmad-output" / "implementation-artifacts"
    stories_dir.mkdir(parents=True, exist_ok=True)
    (stories_dir / filename).write_text(body, encoding="utf-8")


@pytest.fixture
def mock_task_link_repo() -> AsyncMock:
    mock = AsyncMock()
    mock.upsert_many.side_effect = lambda project_id, entries: entries  # echo back for assertions
    return mock


@pytest.fixture
def mock_project_service() -> AsyncMock:
    return AsyncMock()


class TestIngestProject:
    @pytest.mark.asyncio
    async def test_single_repo_same_repo_dependency(
        self, tmp_path: Path, mock_task_link_repo: AsyncMock, mock_project_service: AsyncMock
    ) -> None:
        repo_a = tmp_path / "backend-repo"
        repo_a.mkdir()
        _write_bmad_story(repo_a, "1-1-first.md", "# S\n")
        _write_bmad_story(
            repo_a,
            "1-2-second.md",
            "# S\n\n## Dependencies\n\n- 1-1-first\n",
        )
        mock_project_service.get.return_value = _make_project("proj-1", [str(repo_a)])

        service = RecipeService(mock_task_link_repo, mock_project_service)
        await service.ingest_project("proj-1")

        entries = mock_task_link_repo.upsert_many.call_args.args[1]
        by_node = {e["story_node_id"]: e for e in entries}
        assert by_node["1-2-second"]["depends_on"] == [f"{repo_a}::1-1-first"]
        assert by_node["1-1-first"]["depends_on"] == []
        assert by_node["1-1-first"]["epic_id"] == "epic-1"

    @pytest.mark.asyncio
    async def test_cross_repo_dependency_resolves_to_sibling_repo(
        self, tmp_path: Path, mock_task_link_repo: AsyncMock, mock_project_service: AsyncMock
    ) -> None:
        backend_repo = tmp_path / "codeplane-backend"
        frontend_repo = tmp_path / "codeplane-frontend"
        backend_repo.mkdir()
        frontend_repo.mkdir()
        _write_bmad_story(backend_repo, "2-1-backend-task.md", "# S\n")
        _write_bmad_story(
            frontend_repo,
            "3-1-frontend-task.md",
            "# S\n\n## Dependencies\n\n- codeplane-backend/2-1-backend-task\n",
        )
        mock_project_service.get.return_value = _make_project(
            "proj-1", [str(backend_repo), str(frontend_repo)]
        )

        service = RecipeService(mock_task_link_repo, mock_project_service)
        await service.ingest_project("proj-1")

        entries = mock_task_link_repo.upsert_many.call_args.args[1]
        frontend_entry = next(e for e in entries if e["story_node_id"] == "3-1-frontend-task")
        assert frontend_entry["depends_on"] == [f"{backend_repo}::2-1-backend-task"]

    @pytest.mark.asyncio
    async def test_unresolvable_cross_repo_dependency_preserved_raw(
        self, tmp_path: Path, mock_task_link_repo: AsyncMock, mock_project_service: AsyncMock
    ) -> None:
        repo_a = tmp_path / "solo-repo"
        repo_a.mkdir()
        _write_bmad_story(
            repo_a,
            "1-1-task.md",
            "# S\n\n## Dependencies\n\n- unknown-repo/9-9-ghost\n",
        )
        mock_project_service.get.return_value = _make_project("proj-1", [str(repo_a)])

        service = RecipeService(mock_task_link_repo, mock_project_service)
        await service.ingest_project("proj-1")

        entries = mock_task_link_repo.upsert_many.call_args.args[1]
        assert entries[0]["depends_on"] == ["unknown-repo/9-9-ghost"]

    @pytest.mark.asyncio
    async def test_spec_kit_and_bmad_both_ingested(
        self, tmp_path: Path, mock_task_link_repo: AsyncMock, mock_project_service: AsyncMock
    ) -> None:
        repo_a = tmp_path / "mixed-repo"
        repo_a.mkdir()
        _write_bmad_story(repo_a, "1-1-story.md", "# S\n")
        (repo_a / "tasks.md").write_text("- [ ] T001 Spec-kit task\n", encoding="utf-8")
        mock_project_service.get.return_value = _make_project("proj-1", [str(repo_a)])

        service = RecipeService(mock_task_link_repo, mock_project_service)
        await service.ingest_project("proj-1")

        entries = mock_task_link_repo.upsert_many.call_args.args[1]
        node_ids = {e["story_node_id"] for e in entries}
        assert node_ids == {"1-1-story", "T001"}

    @pytest.mark.asyncio
    async def test_repo_with_no_source_files_yields_no_entries_but_does_not_fail(
        self, tmp_path: Path, mock_task_link_repo: AsyncMock, mock_project_service: AsyncMock
    ) -> None:
        empty_repo = tmp_path / "empty-repo"
        empty_repo.mkdir()
        mock_project_service.get.return_value = _make_project("proj-1", [str(empty_repo)])

        service = RecipeService(mock_task_link_repo, mock_project_service)
        await service.ingest_project("proj-1")

        entries = mock_task_link_repo.upsert_many.call_args.args[1]
        assert entries == []

    @pytest.mark.asyncio
    async def test_never_writes_to_source_repo(
        self, tmp_path: Path, mock_task_link_repo: AsyncMock, mock_project_service: AsyncMock
    ) -> None:
        repo_a = tmp_path / "repo-a"
        repo_a.mkdir()
        _write_bmad_story(repo_a, "1-1-story.md", "# S\n")
        story_file = repo_a / "_bmad-output" / "implementation-artifacts" / "1-1-story.md"
        before_mtime = story_file.stat().st_mtime
        before_content = story_file.read_text(encoding="utf-8")
        mock_project_service.get.return_value = _make_project("proj-1", [str(repo_a)])

        service = RecipeService(mock_task_link_repo, mock_project_service)
        await service.ingest_project("proj-1")

        assert story_file.stat().st_mtime == before_mtime
        assert story_file.read_text(encoding="utf-8") == before_content

    @pytest.mark.asyncio
    async def test_idempotent_rerun_calls_upsert_not_insert_only(
        self, tmp_path: Path, mock_task_link_repo: AsyncMock, mock_project_service: AsyncMock
    ) -> None:
        repo_a = tmp_path / "repo-a"
        repo_a.mkdir()
        _write_bmad_story(repo_a, "1-1-story.md", "# S\n")
        mock_project_service.get.return_value = _make_project("proj-1", [str(repo_a)])

        service = RecipeService(mock_task_link_repo, mock_project_service)
        await service.ingest_project("proj-1")
        await service.ingest_project("proj-1")

        assert mock_task_link_repo.upsert_many.call_count == 2
        first_entries = mock_task_link_repo.upsert_many.call_args_list[0].args[1]
        second_entries = mock_task_link_repo.upsert_many.call_args_list[1].args[1]
        assert first_entries == second_entries


class TestListTaskLinks:
    @pytest.mark.asyncio
    async def test_list_delegates_to_repo_after_project_check(
        self, mock_task_link_repo: AsyncMock, mock_project_service: AsyncMock
    ) -> None:
        mock_project_service.get.return_value = _make_project("proj-1", [])
        mock_task_link_repo.list_by_project.return_value = []

        service = RecipeService(mock_task_link_repo, mock_project_service)
        result = await service.list_task_links("proj-1")

        mock_project_service.get.assert_awaited_once_with("proj-1")
        mock_task_link_repo.list_by_project.assert_awaited_once_with("proj-1")
        assert result == []
