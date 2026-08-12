"""Tests for ChatRepository — including Story 5.4's Project-level gating read."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import event as sa_event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.models.db import Base
from backend.models.domain import Chat
from backend.persistence.chat_repo import ChatRepository
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


async def _make_project(session: AsyncSession, project_id: str = "proj-1") -> str:
    project_repo = ProjectRepository(session)
    project = await project_repo.create(project_id, "Test Project", ["/repo/a"])
    await session.commit()
    return project.id


async def _make_task_link(session: AsyncSession, project_id: str, story_node_id: str) -> str:
    repo = TaskLinkRepository(session)
    results = await repo.upsert_many(
        project_id,
        [{"repo_path": "/repo/a", "story_node_id": story_node_id, "depends_on": [], "epic_id": None}],
    )
    await session.commit()
    return results[0].id


async def _make_chat(
    session: AsyncSession,
    *,
    project_id: str | None,
    task_link_id: str | None,
    status: str = "open",
) -> Chat:
    repo = ChatRepository(session)
    now = datetime.now(UTC)
    chat = Chat(
        id=str(uuid.uuid4()),
        project_id=project_id,
        title="Test chat",
        created_at=now,
        last_message_at=now,
        status=status,
        task_link_id=task_link_id,
    )
    created = await repo.create(chat)
    await session.commit()
    return created


class TestGetAttachedOpenChatForProject:
    @pytest.mark.asyncio
    async def test_returns_attached_open_chat(self, session: AsyncSession) -> None:
        project_id = await _make_project(session)
        task_link_id = await _make_task_link(session, project_id, "1-1-task")
        chat = await _make_chat(session, project_id=project_id, task_link_id=task_link_id, status="open")

        repo = ChatRepository(session)
        found = await repo.get_attached_open_chat_for_project(project_id)

        assert found is not None
        assert found.id == chat.id

    @pytest.mark.asyncio
    async def test_returns_none_when_no_chat_attached(self, session: AsyncSession) -> None:
        project_id = await _make_project(session)
        # A chat in the project exists, but is not attached to any chain.
        await _make_chat(session, project_id=project_id, task_link_id=None, status="open")

        repo = ChatRepository(session)
        found = await repo.get_attached_open_chat_for_project(project_id)

        assert found is None

    @pytest.mark.asyncio
    async def test_returns_none_when_attached_chat_not_open(self, session: AsyncSession) -> None:
        project_id = await _make_project(session)
        task_link_id = await _make_task_link(session, project_id, "1-1-task")
        await _make_chat(session, project_id=project_id, task_link_id=task_link_id, status="archived")

        repo = ChatRepository(session)
        found = await repo.get_attached_open_chat_for_project(project_id)

        assert found is None

    @pytest.mark.asyncio
    async def test_returns_none_for_different_project(self, session: AsyncSession) -> None:
        project_id = await _make_project(session, "proj-1")
        other_project_id = await _make_project(session, "proj-2")
        task_link_id = await _make_task_link(session, project_id, "1-1-task")
        await _make_chat(session, project_id=project_id, task_link_id=task_link_id, status="open")

        repo = ChatRepository(session)
        found = await repo.get_attached_open_chat_for_project(other_project_id)

        assert found is None

    @pytest.mark.asyncio
    async def test_returns_none_for_unknown_project(self, session: AsyncSession) -> None:
        repo = ChatRepository(session)
        found = await repo.get_attached_open_chat_for_project("no-such-project")

        assert found is None
