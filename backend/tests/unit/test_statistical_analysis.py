"""Tests for backend.services.analytics.statistical_analysis.

Covers tool_failure, retry_waste, and cache_regression detectors.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import event as sa_event
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

from backend.models.db import Base, JobRow, ProjectRow
from backend.models.domain import JobState
from backend.persistence.database import _set_sqlite_pragmas
from backend.persistence.telemetry_spans_repo import TelemetrySpansRepository
from backend.services.analytics.statistical_analysis import run_analysis


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sa_event.listen(engine.sync_engine, "connect", _set_sqlite_pragmas)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as sess:
        now = datetime.now(UTC)
        sess.add(
            ProjectRow(
                id="proj-1",
                name="Test Project",
                repo_paths='["/repos/test"]',
                created_at=now,
                updated_at=now,
            )
        )
        await sess.flush()
        sess.add(
            JobRow(
                id="job-1",
                repo="/repos/test",
                project_id="proj-1",
                prompt="Fix the bug",
                state=JobState.running,
                base_ref="main",
                permission_mode="full_auto",
                sdk="copilot",
                created_at=now,
                updated_at=now,
            )
        )
        await sess.commit()
        yield sess

    await engine.dispose()


@pytest.mark.asyncio
async def test_run_analysis_empty_db(session: AsyncSession) -> None:
    count = await run_analysis(session)
    await session.commit()
    assert count == 0


@pytest.mark.asyncio
async def test_tool_failures_high_rate_flagged(session: AsyncSession) -> None:
    spans = TelemetrySpansRepository(session)

    for i in range(12):
        success = i >= 3
        await spans.insert(
            job_id="job-1",
            span_type="tool",
            name="flaky_tool",
            started_at=float(i),
            duration_ms=50.0,
            attrs={"success": success},
        )
    await session.commit()

    _count = await run_analysis(session)
    await session.commit()

    result = await session.execute(text("SELECT COUNT(*) FROM cost_observations WHERE category = 'tool_failure'"))
    assert result.scalar() == 1


@pytest.mark.asyncio
async def test_retry_waste_flagged(session: AsyncSession) -> None:
    spans = TelemetrySpansRepository(session)

    for i in range(20):
        await spans.insert(
            job_id="job-1",
            span_type="tool",
            name="write_file",
            started_at=float(i),
            duration_ms=50.0,
            attrs={"success": True},
            is_retry=i < 6,
        )
    await session.commit()

    _count = await run_analysis(session)
    await session.commit()

    result = await session.execute(text("SELECT COUNT(*) FROM cost_observations WHERE category = 'retry_waste'"))
    assert result.scalar() == 1


@pytest.mark.asyncio
async def test_cache_regression_not_triggered_without_enough_data(session: AsyncSession) -> None:
    _count = await run_analysis(session)
    await session.commit()

    result = await session.execute(text("SELECT COUNT(*) FROM cost_observations WHERE category = 'cache_regression'"))
    assert result.scalar() == 0
