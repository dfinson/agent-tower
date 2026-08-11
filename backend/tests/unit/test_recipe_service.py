"""Tests for RecipeService.ingest_project — cross-repo depends_on resolution (Story 4.2, AD-9)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest

from backend.models.domain import Job, JobState, Project, RepoNotAllowedError, TaskLink
from backend.services.recipe.recipe_service import RecipeService

if TYPE_CHECKING:
    from pathlib import Path


def _make_project(project_id: str, repo_paths: list[str]) -> Project:
    now = datetime.now(UTC)
    return Project(
        id=project_id,
        name="Test Project",
        repo_paths=repo_paths,
        created_at=now,
        updated_at=now,
    )


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
        self,
        tmp_path: Path,
        mock_task_link_repo: AsyncMock,
        mock_project_service: AsyncMock,
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
        self,
        tmp_path: Path,
        mock_task_link_repo: AsyncMock,
        mock_project_service: AsyncMock,
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
        mock_project_service.get.return_value = _make_project("proj-1", [str(backend_repo), str(frontend_repo)])

        service = RecipeService(mock_task_link_repo, mock_project_service)
        await service.ingest_project("proj-1")

        entries = mock_task_link_repo.upsert_many.call_args.args[1]
        frontend_entry = next(e for e in entries if e["story_node_id"] == "3-1-frontend-task")
        assert frontend_entry["depends_on"] == [f"{backend_repo}::2-1-backend-task"]

    @pytest.mark.asyncio
    async def test_unresolvable_cross_repo_dependency_preserved_raw(
        self,
        tmp_path: Path,
        mock_task_link_repo: AsyncMock,
        mock_project_service: AsyncMock,
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
        self,
        tmp_path: Path,
        mock_task_link_repo: AsyncMock,
        mock_project_service: AsyncMock,
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
        self,
        tmp_path: Path,
        mock_task_link_repo: AsyncMock,
        mock_project_service: AsyncMock,
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
        self,
        tmp_path: Path,
        mock_task_link_repo: AsyncMock,
        mock_project_service: AsyncMock,
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
        self,
        tmp_path: Path,
        mock_task_link_repo: AsyncMock,
        mock_project_service: AsyncMock,
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


class TestCreateManualTaskLink:
    @pytest.mark.asyncio
    async def test_creates_manual_link_for_project_member_repo(
        self,
        tmp_path: Path,
        mock_task_link_repo: AsyncMock,
        mock_project_service: AsyncMock,
    ) -> None:
        repo_path = tmp_path / "member-repo"
        repo_path.mkdir()
        mock_project_service.get.return_value = _make_project("proj-1", [str(repo_path)])
        expected = TaskLink(
            id="task-1",
            project_id="proj-1",
            repo_path=str(repo_path),
            story_node_id=None,
            depends_on=[],
            job_id=None,
            tracker_ticket_ref="JIRA-123",
            prompt_override="Implement this ticket",
            epic_id=None,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        mock_task_link_repo.create_manual.return_value = expected

        service = RecipeService(mock_task_link_repo, mock_project_service)
        result = await service.create_manual_task_link(
            project_id="proj-1",
            repo_path=str(repo_path),
            tracker_ticket_ref="JIRA-123",
            prompt_override="Implement this ticket",
        )

        assert result is expected
        mock_task_link_repo.create_manual.assert_awaited_once_with(
            project_id="proj-1",
            repo_path=str(repo_path),
            tracker_ticket_ref="JIRA-123",
            prompt_override="Implement this ticket",
        )

    @pytest.mark.asyncio
    async def test_rejects_repo_outside_project(
        self,
        tmp_path: Path,
        mock_task_link_repo: AsyncMock,
        mock_project_service: AsyncMock,
    ) -> None:
        member_repo = tmp_path / "member-repo"
        other_repo = tmp_path / "other-repo"
        member_repo.mkdir()
        other_repo.mkdir()
        mock_project_service.get.return_value = _make_project("proj-1", [str(member_repo)])

        service = RecipeService(mock_task_link_repo, mock_project_service)
        with pytest.raises(RepoNotAllowedError):
            await service.create_manual_task_link(
                project_id="proj-1",
                repo_path=str(other_repo),
                tracker_ticket_ref="JIRA-123",
                prompt_override="Implement this ticket",
            )

        mock_task_link_repo.create_manual.assert_not_awaited()


def _make_task_link(
    *,
    id: str,  # noqa: A002
    project_id: str = "proj-1",
    repo_path: str = "/repo/a",
    story_node_id: str | None = None,
    depends_on: list[str] | None = None,
    job_id: str | None = None,
    tracker_ticket_ref: str | None = None,
    prompt_override: str | None = None,
) -> TaskLink:
    now = datetime.now(UTC)
    return TaskLink(
        id=id,
        project_id=project_id,
        repo_path=repo_path,
        story_node_id=story_node_id,
        depends_on=depends_on or [],
        job_id=job_id,
        tracker_ticket_ref=tracker_ticket_ref,
        prompt_override=prompt_override,
        epic_id=None,
        created_at=now,
        updated_at=now,
    )


def _make_job(*, id: str, state: JobState, resolution: str | None = None) -> Job:  # noqa: A002
    now = datetime.now(UTC)
    return Job(
        id=id,
        repo="/repo/a",
        prompt="do the thing",
        state=state,
        base_ref="main",
        branch="feature",
        worktree_path="/tmp/wt",
        session_id=None,
        created_at=now,
        updated_at=now,
        resolution=resolution,
    )


@pytest.fixture
def mock_job_repo() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def mock_job_service() -> AsyncMock:
    return AsyncMock()


class TestHandleJobCompleted:
    """Story 4.5: auto-spawn a dependent TaskLink's job on completion."""

    @pytest.mark.asyncio
    async def test_no_op_when_job_service_not_configured(
        self, mock_task_link_repo: AsyncMock, mock_project_service: AsyncMock
    ) -> None:
        service = RecipeService(mock_task_link_repo, mock_project_service)
        result = await service.handle_job_completed("job-1", resolution="merged")
        assert result == []
        mock_task_link_repo.get_by_job_id.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_op_when_resolution_is_discarded(
        self,
        mock_task_link_repo: AsyncMock,
        mock_project_service: AsyncMock,
        mock_job_repo: AsyncMock,
        mock_job_service: AsyncMock,
    ) -> None:
        service = RecipeService(
            mock_task_link_repo, mock_project_service, job_service=mock_job_service, job_repo=mock_job_repo
        )
        result = await service.handle_job_completed("job-1", resolution="discarded")
        assert result == []
        mock_task_link_repo.get_by_job_id.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_op_when_completed_job_has_no_linked_task_link(
        self,
        mock_task_link_repo: AsyncMock,
        mock_project_service: AsyncMock,
        mock_job_repo: AsyncMock,
        mock_job_service: AsyncMock,
    ) -> None:
        mock_task_link_repo.get_by_job_id.return_value = None
        service = RecipeService(
            mock_task_link_repo, mock_project_service, job_service=mock_job_service, job_repo=mock_job_repo
        )
        result = await service.handle_job_completed("job-1", resolution="merged")
        assert result == []
        mock_job_service.create_job.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_spawns_dependent_whose_single_dependency_is_now_satisfied(
        self,
        mock_task_link_repo: AsyncMock,
        mock_project_service: AsyncMock,
        mock_job_repo: AsyncMock,
        mock_job_service: AsyncMock,
    ) -> None:
        completed_link = _make_task_link(id="link-a", story_node_id="1-1-a", job_id="job-1")
        dependent = _make_task_link(id="link-b", story_node_id="1-2-b", depends_on=["/repo/a::1-1-a"])
        mock_task_link_repo.get_by_job_id.return_value = completed_link
        mock_task_link_repo.list_by_project.return_value = [completed_link, dependent]
        mock_job_repo.get.return_value = _make_job(id="job-1", state=JobState.completed, resolution="merged")
        new_job = _make_job(id="job-2", state=JobState.preparing)
        mock_job_service.create_job.return_value = new_job
        mock_task_link_repo.set_job_id.return_value = _make_task_link(
            id="link-b", story_node_id="1-2-b", depends_on=["/repo/a::1-1-a"], job_id="job-2"
        )

        service = RecipeService(
            mock_task_link_repo, mock_project_service, job_service=mock_job_service, job_repo=mock_job_repo
        )
        result = await service.handle_job_completed("job-1", resolution="merged")

        assert result == [new_job]
        mock_job_service.create_job.assert_awaited_once()
        spec = mock_job_service.create_job.call_args.args[0]
        assert spec.repo == "/repo/a"
        assert spec.parent_job_id == "job-1"
        mock_task_link_repo.set_job_id.assert_awaited_once_with("link-b", "job-2")

    @pytest.mark.asyncio
    async def test_does_not_spawn_until_all_dependencies_satisfied(
        self,
        mock_task_link_repo: AsyncMock,
        mock_project_service: AsyncMock,
        mock_job_repo: AsyncMock,
        mock_job_service: AsyncMock,
    ) -> None:
        completed_link = _make_task_link(id="link-a", story_node_id="1-1-a", job_id="job-1")
        other_dep = _make_task_link(id="link-c", story_node_id="1-1-c", job_id=None)
        dependent = _make_task_link(
            id="link-b",
            story_node_id="1-2-b",
            depends_on=["/repo/a::1-1-a", "/repo/a::1-1-c"],
        )
        mock_task_link_repo.get_by_job_id.return_value = completed_link
        mock_task_link_repo.list_by_project.return_value = [completed_link, other_dep, dependent]
        mock_job_repo.get.return_value = _make_job(id="job-1", state=JobState.completed, resolution="merged")

        service = RecipeService(
            mock_task_link_repo, mock_project_service, job_service=mock_job_service, job_repo=mock_job_repo
        )
        result = await service.handle_job_completed("job-1", resolution="merged")

        assert result == []
        mock_job_service.create_job.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_never_spawns_a_dependent_twice(
        self,
        mock_task_link_repo: AsyncMock,
        mock_project_service: AsyncMock,
        mock_job_repo: AsyncMock,
        mock_job_service: AsyncMock,
    ) -> None:
        completed_link = _make_task_link(id="link-a", story_node_id="1-1-a", job_id="job-1")
        dependent = _make_task_link(
            id="link-b",
            story_node_id="1-2-b",
            depends_on=["/repo/a::1-1-a"],
            job_id="job-already-spawned",
        )
        mock_task_link_repo.get_by_job_id.return_value = completed_link
        mock_task_link_repo.list_by_project.return_value = [completed_link, dependent]

        service = RecipeService(
            mock_task_link_repo, mock_project_service, job_service=mock_job_service, job_repo=mock_job_repo
        )
        result = await service.handle_job_completed("job-1", resolution="merged")

        assert result == []
        mock_job_service.create_job.assert_not_awaited()
        mock_task_link_repo.set_job_id.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_dependency_target_job_in_review_state_is_not_satisfied(
        self,
        mock_task_link_repo: AsyncMock,
        mock_project_service: AsyncMock,
        mock_job_repo: AsyncMock,
        mock_job_service: AsyncMock,
    ) -> None:
        completed_link = _make_task_link(id="link-a", story_node_id="1-1-a", job_id="job-1")
        dependent = _make_task_link(id="link-b", story_node_id="1-2-b", depends_on=["/repo/a::1-1-a"])
        mock_task_link_repo.get_by_job_id.return_value = completed_link
        mock_task_link_repo.list_by_project.return_value = [completed_link, dependent]
        # The dependency target's own job is only in `review`, not `completed`.
        mock_job_repo.get.return_value = _make_job(id="job-1", state=JobState.review)

        service = RecipeService(
            mock_task_link_repo, mock_project_service, job_service=mock_job_service, job_repo=mock_job_repo
        )
        result = await service.handle_job_completed("job-1", resolution="merged")

        assert result == []
        mock_job_service.create_job.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_manually_assigned_dependent_uses_prompt_override(
        self,
        mock_task_link_repo: AsyncMock,
        mock_project_service: AsyncMock,
        mock_job_repo: AsyncMock,
        mock_job_service: AsyncMock,
    ) -> None:
        completed_link = _make_task_link(id="link-a", story_node_id="1-1-a", job_id="job-1")
        dependent = _make_task_link(
            id="link-b",
            story_node_id=None,
            depends_on=["/repo/a::1-1-a"],
            tracker_ticket_ref="JIRA-9",
            prompt_override="Do exactly this",
        )
        mock_task_link_repo.get_by_job_id.return_value = completed_link
        mock_task_link_repo.list_by_project.return_value = [completed_link, dependent]
        mock_job_repo.get.return_value = _make_job(id="job-1", state=JobState.completed, resolution="merged")
        new_job = _make_job(id="job-2", state=JobState.preparing)
        mock_job_service.create_job.return_value = new_job
        mock_task_link_repo.set_job_id.return_value = dependent

        service = RecipeService(
            mock_task_link_repo, mock_project_service, job_service=mock_job_service, job_repo=mock_job_repo
        )
        await service.handle_job_completed("job-1", resolution="merged")

        spec = mock_job_service.create_job.call_args.args[0]
        assert spec.prompt == "Do exactly this"

    @pytest.mark.asyncio
    async def test_spawn_failure_for_one_dependent_does_not_raise_or_block(
        self,
        mock_task_link_repo: AsyncMock,
        mock_project_service: AsyncMock,
        mock_job_repo: AsyncMock,
        mock_job_service: AsyncMock,
    ) -> None:
        completed_link = _make_task_link(id="link-a", story_node_id="1-1-a", job_id="job-1")
        dependent = _make_task_link(id="link-b", story_node_id="1-2-b", depends_on=["/repo/a::1-1-a"])
        mock_task_link_repo.get_by_job_id.return_value = completed_link
        mock_task_link_repo.list_by_project.return_value = [completed_link, dependent]
        mock_job_repo.get.return_value = _make_job(id="job-1", state=JobState.completed, resolution="merged")
        mock_job_service.create_job.side_effect = RepoNotAllowedError("nope")

        service = RecipeService(
            mock_task_link_repo, mock_project_service, job_service=mock_job_service, job_repo=mock_job_repo
        )
        result = await service.handle_job_completed("job-1", resolution="merged")

        assert result == []
        mock_task_link_repo.set_job_id.assert_not_awaited()
