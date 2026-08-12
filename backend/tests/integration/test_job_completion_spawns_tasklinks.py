"""Integration test for Story 4.5: auto-spawn on job completion, end-to-end
through the real ``EventBus``.

Wires the same subscriber shape as ``backend/lifespan.py``'s
``_spawn_dependent_task_links`` (event bus -> RecipeService.handle_job_completed
-> RuntimeService.setup_and_start) against real repositories and a real
in-memory sqlite session, asserting the dependent TaskLink's ``job_id`` is
persisted and a new ``jobs`` row exists after the dependency's job completes.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from backend.config import CPLConfig
from backend.models.db import JobRow
from backend.models.domain import Chat, JobState
from backend.models.events import EventKind, new_event
from backend.persistence.job_repo import JobRepository
from backend.persistence.project_repo import ProjectRepository
from backend.persistence.task_link_repo import TaskLinkRepository
from backend.services.job.job_service import JobService
from backend.services.project.project_service import ProjectService
from backend.services.recipe.recipe_service import RecipeService

if TYPE_CHECKING:
    from unittest.mock import AsyncMock

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from backend.services.events.event_bus import EventBus


async def _seed_completed_job(session: AsyncSession, job_id: str, repo: str) -> None:
    now = datetime.now(UTC)
    session.add(
        JobRow(
            id=job_id,
            repo=repo,
            prompt="do the first task",
            state=JobState.completed,
            base_ref="main",
            permission_mode="full_auto",
            preset="autonomous",
            sdk="copilot",
            resolution="merged",
            created_at=now,
            updated_at=now,
        )
    )
    await session.commit()


class TestJobCompletionSpawnsTaskLinks:
    @pytest.mark.asyncio
    async def test_dependent_task_link_is_spawned_when_dependency_job_completes(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        event_bus: EventBus,
        mock_git_service: AsyncMock,
        mock_runtime_service: AsyncMock,
        tmp_path: object,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        repo_path = str(Path(str(tmp_path)).resolve())
        config = CPLConfig(repos=[repo_path])
        monkeypatch.setattr("backend.services.job.job_service.load_config", lambda: config)

        async with session_factory() as session:
            project = await ProjectRepository(session).create("proj-1", "Test Project", [repo_path])
            task_link_repo = TaskLinkRepository(session)
            created = await task_link_repo.upsert_many(
                project.id,
                [
                    {
                        "repo_path": repo_path,
                        "story_node_id": "1-1-first",
                        "depends_on": [],
                        "epic_id": "epic-1",
                    },
                    {
                        "repo_path": repo_path,
                        "story_node_id": "1-2-second",
                        "depends_on": [f"{repo_path}::1-1-first"],
                        "epic_id": "epic-1",
                    },
                ],
            )
            await session.commit()
            first_link = next(link for link in created if link.story_node_id == "1-1-first")
            second_link = next(link for link in created if link.story_node_id == "1-2-second")

            await _seed_completed_job(session, "job-first", repo_path)
            await task_link_repo.set_job_id(first_link.id, "job-first")
            await session.commit()

        async def _spawn_dependent_task_links(event: object) -> None:
            if event.kind != EventKind.job_completed:  # type: ignore[union-attr]
                return
            job_id = event.session_id  # type: ignore[union-attr]
            resolution = event.payload.get("resolution")  # type: ignore[union-attr]
            async with session_factory() as session:
                task_link_repo = TaskLinkRepository(session)
                job_repo = JobRepository(session)
                project_service = ProjectService(ProjectRepository(session), config)
                job_service = JobService.from_session(session, config, git_service=mock_git_service)
                recipe_service = RecipeService(
                    task_link_repo, project_service, job_service=job_service, job_repo=job_repo
                )
                spawned_jobs = await recipe_service.handle_job_completed(job_id, resolution=resolution)
                await session.commit()
            for job in spawned_jobs:
                await mock_runtime_service.setup_and_start(job)

        event_bus.subscribe(_spawn_dependent_task_links)

        await event_bus.publish(
            new_event(
                session_id="job-first",
                kind=EventKind.job_completed,
                payload={"resolution": "merged"},
            )
        )

        async with session_factory() as session:
            refreshed = await TaskLinkRepository(session).list_by_project(project.id)
            refreshed_second = next(link for link in refreshed if link.id == second_link.id)

        assert refreshed_second.job_id is not None
        mock_runtime_service.setup_and_start.assert_awaited_once()

        async with session_factory() as session:
            spawned_job = await JobRepository(session).get(refreshed_second.job_id)
        assert spawned_job is not None
        assert spawned_job.repo == repo_path
        assert spawned_job.parent_job_id == "job-first"

    @pytest.mark.asyncio
    async def test_gated_chain_creates_approval_instead_of_spawning(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        event_bus: EventBus,
        mock_git_service: AsyncMock,
        mock_runtime_service: AsyncMock,
        tmp_path: object,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Story 5.4, AC #1-#2: an open Chat attached to a TaskLink switches the
        whole Project's chains into gated mode — the dependent's spawn is
        deferred behind a codeplane_approval instead of firing immediately."""
        from backend.persistence.chat_repo import ChatRepository
        from backend.services.job.approval_service import ApprovalService

        repo_path = str(Path(str(tmp_path)).resolve())
        config = CPLConfig(repos=[repo_path])
        monkeypatch.setattr("backend.services.job.job_service.load_config", lambda: config)

        approval_service = ApprovalService(session_factory=session_factory)

        async with session_factory() as session:
            project = await ProjectRepository(session).create("proj-gated", "Test Gated Project", [repo_path])
            task_link_repo = TaskLinkRepository(session)
            created = await task_link_repo.upsert_many(
                project.id,
                [
                    {
                        "repo_path": repo_path,
                        "story_node_id": "1-1-first",
                        "depends_on": [],
                        "epic_id": "epic-1",
                    },
                    {
                        "repo_path": repo_path,
                        "story_node_id": "1-2-second",
                        "depends_on": [f"{repo_path}::1-1-first"],
                        "epic_id": "epic-1",
                    },
                ],
            )
            await session.commit()
            first_link = next(link for link in created if link.story_node_id == "1-1-first")
            second_link = next(link for link in created if link.story_node_id == "1-2-second")

            await _seed_completed_job(session, "job-first-gated", repo_path)
            await task_link_repo.set_job_id(first_link.id, "job-first-gated")
            await session.commit()

            # Attach an open Chat to the first TaskLink — this is the sole
            # trigger for gating a Project's chains (Story 5.3/5.4).
            import uuid as _uuid

            chat_repo = ChatRepository(session)
            now = datetime.now(UTC)
            chat = Chat(
                id=str(_uuid.uuid4()),
                project_id=project.id,
                title="ops chat",
                created_at=now,
                last_message_at=now,
                status="open",
                task_link_id=None,
            )
            await chat_repo.create(chat)
            await chat_repo.attach_to_chain(chat.id, first_link.id)
            await session.commit()

        async def _spawn_dependent_task_links(event: object) -> None:
            if event.kind != EventKind.job_completed:  # type: ignore[union-attr]
                return
            job_id = event.session_id  # type: ignore[union-attr]
            resolution = event.payload.get("resolution")  # type: ignore[union-attr]
            async with session_factory() as session:
                task_link_repo = TaskLinkRepository(session)
                job_repo = JobRepository(session)
                chat_repo = ChatRepository(session)
                project_service = ProjectService(ProjectRepository(session), config)
                job_service = JobService.from_session(session, config, git_service=mock_git_service)
                recipe_service = RecipeService(
                    task_link_repo,
                    project_service,
                    job_service=job_service,
                    job_repo=job_repo,
                    chat_repo=chat_repo,
                    approval_service=approval_service,
                )
                spawned_jobs = await recipe_service.handle_job_completed(job_id, resolution=resolution)
                await session.commit()
            for job in spawned_jobs:
                await mock_runtime_service.setup_and_start(job)

        event_bus.subscribe(_spawn_dependent_task_links)

        await event_bus.publish(
            new_event(
                session_id="job-first-gated",
                kind=EventKind.job_completed,
                payload={"resolution": "merged"},
            )
        )

        async with session_factory() as session:
            refreshed = await TaskLinkRepository(session).list_by_project(project.id)
            refreshed_second = next(link for link in refreshed if link.id == second_link.id)

        # Gated: no job was spawned, and no start was requested.
        assert refreshed_second.job_id is None
        mock_runtime_service.setup_and_start.assert_not_awaited()

        # Instead, a pending approval was created for the deferred spawn.
        pending = await approval_service.list_pending()
        assert len(pending) == 1
        assert pending[0].proposed_action == f"spawn_task:{second_link.id}"
        assert pending[0].job_id == "job-first-gated"
