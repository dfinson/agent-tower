"""Tests for JobRepository persistence mappings."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import event as sa_event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.models.db import Base
from backend.models.domain import JobState
from backend.persistence.database import _set_sqlite_pragmas
from backend.persistence.job_repo import JobRepository
from backend.persistence.project_repo import ProjectRepository
from backend.tests.unit.conftest import make_job

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


class TestJobRepository:
    @pytest.mark.asyncio
    async def test_create_and_get_round_trips_project_id(self, session: AsyncSession) -> None:
        project_repo = ProjectRepository(session)
        await project_repo.create("proj-1", "Payments", ["/repos/test"])

        repo = JobRepository(session)
        job = make_job(project_id="proj-1", state=JobState.preparing)
        await repo.create(job)
        await session.commit()

        fetched = await repo.get(job.id)

        assert fetched is not None
        assert fetched.project_id == "proj-1"
        assert fetched.repo == "/repos/test"
