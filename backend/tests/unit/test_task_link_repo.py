"""Tests for TaskLinkRepository — upsert-by-natural-key and project listing (Story 4.2, AD-9)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import event as sa_event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.models.db import Base, JobRow
from backend.models.domain import JobState
from backend.persistence.database import _set_sqlite_pragmas
from backend.persistence.project_repo import ProjectRepository
from backend.persistence.task_link_repo import TaskLinkRepository

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sa_event.listen(engine.sync_engine, "connect", _set_sqlite_pragmas)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as sess:
        yield sess
    await engine.dispose()


async def _make_project(session: AsyncSession) -> str:
    project_repo = ProjectRepository(session)
    project = await project_repo.create("proj-1", "Test Project", ["/repo/a", "/repo/b"])
    await session.commit()
    return project.id


async def _make_job(session: AsyncSession, job_id: str) -> None:
    now = datetime.now(UTC)
    session.add(
        JobRow(
            id=job_id,
            repo="/repo/a",
            prompt="do the thing",
            state=JobState.completed,
            base_ref="main",
            permission_mode="full_auto",
            preset="autonomous",
            sdk="copilot",
            created_at=now,
            updated_at=now,
        )
    )
    await session.commit()


class TestTaskLinkRepoUpsert:
    @pytest.mark.asyncio
    async def test_upsert_inserts_new_rows(self, session: AsyncSession) -> None:
        project_id = await _make_project(session)
        repo = TaskLinkRepository(session)

        results = await repo.upsert_many(
            project_id,
            [
                {
                    "repo_path": "/repo/a",
                    "story_node_id": "1-1-task",
                    "depends_on": [],
                    "epic_id": "epic-1",
                },
                {
                    "repo_path": "/repo/a",
                    "story_node_id": "1-2-task",
                    "depends_on": ["/repo/a::1-1-task"],
                    "epic_id": "epic-1",
                },
            ],
        )
        await session.commit()

        assert len(results) == 2
        listed = await repo.list_by_project(project_id)
        assert {t.story_node_id for t in listed} == {"1-1-task", "1-2-task"}
        second = next(t for t in listed if t.story_node_id == "1-2-task")
        assert second.depends_on == ["/repo/a::1-1-task"]
        assert second.epic_id == "epic-1"

    @pytest.mark.asyncio
    async def test_upsert_matches_by_project_repo_story_node(self, session: AsyncSession) -> None:
        project_id = await _make_project(session)
        repo = TaskLinkRepository(session)

        await repo.upsert_many(
            project_id,
            [
                {
                    "repo_path": "/repo/a",
                    "story_node_id": "1-1-task",
                    "depends_on": [],
                    "epic_id": None,
                }
            ],
        )
        await session.commit()

        # Re-ingest with an updated depends_on — must update, not duplicate.
        await repo.upsert_many(
            project_id,
            [
                {
                    "repo_path": "/repo/a",
                    "story_node_id": "1-1-task",
                    "depends_on": ["/repo/b::2-1-task"],
                    "epic_id": "epic-1",
                }
            ],
        )
        await session.commit()

        listed = await repo.list_by_project(project_id)
        assert len(listed) == 1
        assert listed[0].depends_on == ["/repo/b::2-1-task"]
        assert listed[0].epic_id == "epic-1"

    @pytest.mark.asyncio
    async def test_same_story_node_id_different_repo_is_distinct(self, session: AsyncSession) -> None:
        project_id = await _make_project(session)
        repo = TaskLinkRepository(session)

        await repo.upsert_many(
            project_id,
            [
                {
                    "repo_path": "/repo/a",
                    "story_node_id": "T001",
                    "depends_on": [],
                    "epic_id": None,
                },
                {
                    "repo_path": "/repo/b",
                    "story_node_id": "T001",
                    "depends_on": [],
                    "epic_id": None,
                },
            ],
        )
        await session.commit()

        listed = await repo.list_by_project(project_id)
        assert len(listed) == 2
        assert {t.repo_path for t in listed} == {"/repo/a", "/repo/b"}

    @pytest.mark.asyncio
    async def test_list_by_project_empty(self, session: AsyncSession) -> None:
        project_id = await _make_project(session)
        repo = TaskLinkRepository(session)
        assert await repo.list_by_project(project_id) == []


class TestCreateManual:
    @pytest.mark.asyncio
    async def test_creates_manual_task_link_without_story_backing(self, session: AsyncSession) -> None:
        project_id = await _make_project(session)
        repo = TaskLinkRepository(session)

        created = await repo.create_manual(
            project_id=project_id,
            repo_path="/repo/a",
            tracker_ticket_ref="JIRA-123",
            prompt_override="Implement the ticket",
        )
        await session.commit()

        assert created.project_id == project_id
        assert created.repo_path == "/repo/a"
        assert created.tracker_ticket_ref == "JIRA-123"
        assert created.prompt_override == "Implement the ticket"
        assert created.story_node_id is None
        assert created.depends_on == []
        assert created.job_id is None
        assert created.epic_id is None

    @pytest.mark.asyncio
    async def test_same_ticket_ref_creates_independent_persisted_rows(self, session: AsyncSession) -> None:
        project_id = await _make_project(session)
        repo = TaskLinkRepository(session)

        first = await repo.create_manual(
            project_id=project_id,
            repo_path="/repo/a",
            tracker_ticket_ref="JIRA-123",
            prompt_override="Implement part one",
        )
        second = await repo.create_manual(
            project_id=project_id,
            repo_path="/repo/a",
            tracker_ticket_ref="JIRA-123",
            prompt_override="Implement part two",
        )
        await session.commit()

        listed = await repo.list_by_project(project_id)
        assert first.id != second.id
        assert [task.tracker_ticket_ref for task in listed] == ["JIRA-123", "JIRA-123"]
        assert [task.prompt_override for task in listed] == [
            "Implement part one",
            "Implement part two",
        ]
        assert all(task.story_node_id is None for task in listed)


class TestSetJobIdAndGetByJobId:
    """Story 4.5: guarded job_id assignment (AC #3) and completion lookup (AC #1)."""

    @pytest.mark.asyncio
    async def test_set_job_id_persists_and_returns_updated_task_link(self, session: AsyncSession) -> None:
        project_id = await _make_project(session)
        repo = TaskLinkRepository(session)

        created = await repo.upsert_many(
            project_id,
            [{"repo_path": "/repo/a", "story_node_id": "1-1-task", "depends_on": [], "epic_id": None}],
        )
        await session.commit()
        task_link_id = created[0].id
        await _make_job(session, "job-123")

        updated = await repo.set_job_id(task_link_id, "job-123")
        await session.commit()

        assert updated is not None
        assert updated.job_id == "job-123"

        listed = await repo.list_by_project(project_id)
        assert listed[0].job_id == "job-123"

    @pytest.mark.asyncio
    async def test_set_job_id_is_a_no_op_once_already_set(self, session: AsyncSession) -> None:
        project_id = await _make_project(session)
        repo = TaskLinkRepository(session)

        created = await repo.upsert_many(
            project_id,
            [{"repo_path": "/repo/a", "story_node_id": "1-1-task", "depends_on": [], "epic_id": None}],
        )
        await session.commit()
        task_link_id = created[0].id
        await _make_job(session, "job-123")
        await _make_job(session, "job-456")

        first = await repo.set_job_id(task_link_id, "job-123")
        await session.commit()
        assert first is not None and first.job_id == "job-123"

        # Second attempt with a different job id must be rejected — a
        # TaskLink is never spawned a second time (Story 4.5, AC #3).
        second = await repo.set_job_id(task_link_id, "job-456")
        await session.commit()
        assert second is None

        listed = await repo.list_by_project(project_id)
        assert listed[0].job_id == "job-123"

    @pytest.mark.asyncio
    async def test_set_job_id_returns_none_for_missing_row(self, session: AsyncSession) -> None:
        repo = TaskLinkRepository(session)
        result = await repo.set_job_id("does-not-exist", "job-1")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_by_job_id_finds_matching_row(self, session: AsyncSession) -> None:
        project_id = await _make_project(session)
        repo = TaskLinkRepository(session)

        created = await repo.upsert_many(
            project_id,
            [{"repo_path": "/repo/a", "story_node_id": "1-1-task", "depends_on": [], "epic_id": None}],
        )
        await session.commit()
        await _make_job(session, "job-123")
        await repo.set_job_id(created[0].id, "job-123")
        await session.commit()

        found = await repo.get_by_job_id("job-123")
        assert found is not None
        assert found.id == created[0].id

    @pytest.mark.asyncio
    async def test_get_by_job_id_returns_none_when_absent(self, session: AsyncSession) -> None:
        repo = TaskLinkRepository(session)
        assert await repo.get_by_job_id("does-not-exist") is None

