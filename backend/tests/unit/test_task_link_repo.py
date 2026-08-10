"""Tests for TaskLinkRepository — upsert-by-natural-key and project listing (Story 4.2, AD-9)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import event as sa_event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.models.db import Base
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
            [{"repo_path": "/repo/a", "story_node_id": "1-1-task", "depends_on": [], "epic_id": None}],
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
                {"repo_path": "/repo/a", "story_node_id": "T001", "depends_on": [], "epic_id": None},
                {"repo_path": "/repo/b", "story_node_id": "T001", "depends_on": [], "epic_id": None},
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
