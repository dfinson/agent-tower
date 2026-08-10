"""Tests for ProjectRepository — CRUD with DB."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import event as sa_event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.models.db import Base
from backend.persistence.database import _set_sqlite_pragmas
from backend.persistence.project_repo import ProjectRepository

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


class TestProjectRepo:
    @pytest.mark.asyncio
    async def test_create_and_get(self, session: AsyncSession) -> None:
        repo = ProjectRepository(session)
        project = await repo.create("proj-1", "My Project", ["/repo/a"])
        await session.commit()

        fetched = await repo.get("proj-1")
        assert fetched is not None
        assert fetched.id == "proj-1"
        assert fetched.name == "My Project"
        assert fetched.repo_paths == ["/repo/a"]
        assert project.id == "proj-1"

    @pytest.mark.asyncio
    async def test_get_missing_returns_none(self, session: AsyncSession) -> None:
        repo = ProjectRepository(session)
        assert await repo.get("does-not-exist") is None

    @pytest.mark.asyncio
    async def test_list_returns_all_in_creation_order(self, session: AsyncSession) -> None:
        repo = ProjectRepository(session)
        await repo.create("proj-1", "First", ["/repo/a"])
        await repo.create("proj-2", "Second", ["/repo/b"])
        await session.commit()

        projects = await repo.list()
        assert [p.id for p in projects] == ["proj-1", "proj-2"]

    @pytest.mark.asyncio
    async def test_update_name_only(self, session: AsyncSession) -> None:
        repo = ProjectRepository(session)
        await repo.create("proj-1", "Original", ["/repo/a"])
        await session.commit()

        updated = await repo.update("proj-1", name="Renamed")
        assert updated is not None
        assert updated.name == "Renamed"
        assert updated.repo_paths == ["/repo/a"]

    @pytest.mark.asyncio
    async def test_update_repo_paths(self, session: AsyncSession) -> None:
        repo = ProjectRepository(session)
        await repo.create("proj-1", "Original", ["/repo/a"])
        await session.commit()

        updated = await repo.update("proj-1", repo_paths=["/repo/a", "/repo/b"])
        assert updated is not None
        assert updated.repo_paths == ["/repo/a", "/repo/b"]

    @pytest.mark.asyncio
    async def test_update_missing_returns_none(self, session: AsyncSession) -> None:
        repo = ProjectRepository(session)
        assert await repo.update("does-not-exist", name="X") is None

    @pytest.mark.asyncio
    async def test_list_all_repo_paths(self, session: AsyncSession) -> None:
        repo = ProjectRepository(session)
        await repo.create("proj-1", "First", ["/repo/a", "/repo/b"])
        await repo.create("proj-2", "Second", ["/repo/c"])
        await session.commit()

        mapping = await repo.list_all_repo_paths()
        assert mapping == {"/repo/a": "proj-1", "/repo/b": "proj-1", "/repo/c": "proj-2"}

    @pytest.mark.asyncio
    async def test_list_all_repo_paths_excludes_project(self, session: AsyncSession) -> None:
        repo = ProjectRepository(session)
        await repo.create("proj-1", "First", ["/repo/a"])
        await repo.create("proj-2", "Second", ["/repo/c"])
        await session.commit()

        mapping = await repo.list_all_repo_paths(exclude_project_id="proj-1")
        assert mapping == {"/repo/c": "proj-2"}
