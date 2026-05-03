"""Tests for backend.services.statistical_analysis -- all 7 detectors."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import event as sa_event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

from backend.models.db import Base, JobRow
from backend.models.domain import JobState
from backend.persistence.database import _set_sqlite_pragmas
from backend.persistence.telemetry_spans_repo import TelemetrySpansRepository
from backend.persistence.telemetry_summary_repo import TelemetrySummaryRepository
from backend.services.statistical_analysis import run_analysis


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
            JobRow(
                id="job-1",
                repo="/repos/test",
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


async def _add_jobs(session: AsyncSession, count: int) -> list[str]:
    now = datetime.now(UTC)
    summary = TelemetrySummaryRepository(session)
    ids = []
    for i in range(1, count + 1):
        jid = f"job-extra-{i}"
        session.add(
            JobRow(
                id=jid,
                repo="/repos/test",
                prompt=f"Task {i}",
                state=JobState.running,
                base_ref="main",
                permission_mode="full_auto",
                sdk="copilot",
                created_at=now,
                updated_at=now,
            )
        )
        ids.append(jid)
    await session.commit()
    for jid in ids:
        await summary.init_job(jid, sdk="claude", model="sonnet", repo="/repos/test", branch="main")
    await session.commit()
    return ids


@pytest.mark.asyncio
async def test_run_analysis_empty_db(session: AsyncSession) -> None:
    count = await run_analysis(session)
    await session.commit()
    assert count == 0


@pytest.mark.asyncio
async def test_phase_imbalance_not_run(session: AsyncSession) -> None:
    extra_ids = await _add_jobs(session, 3)
    now = datetime.now(UTC).isoformat()
    summary = TelemetrySummaryRepository(session)

    for jid in extra_ids:
        await summary.increment(jid, total_cost_usd=1.0, total_turns=10)
        await summary.set_turn_stats(jid, cost_first_half_usd=0.3, cost_second_half_usd=0.7)
        await summary.finalize(jid, status="completed", duration_ms=10000)
        await session.execute(
            text("""
                INSERT INTO job_cost_attribution (job_id, dimension, bucket, cost_usd,
                    input_tokens, output_tokens, call_count, created_at)
                VALUES (:jid, 'phase', 'verification', 0.8, 500, 250, 5, :now)
            """),
            {"jid": jid, "now": now},
        )
        await session.execute(
            text("""
                INSERT INTO job_cost_attribution (job_id, dimension, bucket, cost_usd,
                    input_tokens, output_tokens, call_count, created_at)
                VALUES (:jid, 'phase', 'agent_reasoning', 0.2, 500, 250, 5, :now)
            """),
            {"jid": jid, "now": now},
        )
    await session.commit()

    count = await run_analysis(session)
    await session.commit()

    result = await session.execute(
        text("SELECT COUNT(*) FROM cost_observations WHERE category = 'phase_imbalance'")
    )
    assert result.scalar() == 0


@pytest.mark.asyncio
async def test_file_reread_below_10kb_not_flagged(session: AsyncSession) -> None:
    extra_ids = await _add_jobs(session, 3)
    now = datetime.now(UTC).isoformat()

    for jid in extra_ids:
        for _ in range(5):
            await session.execute(
                text("""
                    INSERT INTO job_file_access_log
                        (job_id, file_path, access_type, byte_count, created_at)
                    VALUES (:jid, '/src/small.ts', 'read', 500, :now)
                """),
                {"jid": jid, "now": now},
            )
    await session.commit()

    count = await run_analysis(session)
    await session.commit()

    result = await session.execute(
        text("SELECT COUNT(*) FROM cost_observations WHERE category = 'file_reread'")
    )
    assert result.scalar() == 0


@pytest.mark.asyncio
async def test_file_reread_above_10kb_flagged(session: AsyncSession) -> None:
    extra_ids = await _add_jobs(session, 3)
    now = datetime.now(UTC).isoformat()

    for jid in extra_ids:
        for _ in range(4):
            await session.execute(
                text("""
                    INSERT INTO job_file_access_log
                        (job_id, file_path, access_type, byte_count, created_at)
                    VALUES (:jid, '/src/big.ts', 'read', 1024, :now)
                """),
                {"jid": jid, "now": now},
            )
    await session.commit()

    count = await run_analysis(session)
    await session.commit()

    result = await session.execute(
        text("SELECT COUNT(*) FROM cost_observations WHERE category = 'file_reread'")
    )
    assert result.scalar() == 1


@pytest.mark.asyncio
async def test_turn_escalation_below_050_not_flagged(session: AsyncSession) -> None:
    extra_ids = await _add_jobs(session, 4)
    summary = TelemetrySummaryRepository(session)

    for jid in extra_ids:
        await summary.increment(jid, total_cost_usd=0.30, total_turns=8)
        await summary.set_turn_stats(jid, cost_first_half_usd=0.10, cost_second_half_usd=0.20)
        await summary.finalize(jid, status="completed", duration_ms=10000)
    await session.commit()

    count = await run_analysis(session)
    await session.commit()

    result = await session.execute(
        text("SELECT COUNT(*) FROM cost_observations WHERE category = 'turn_escalation'")
    )
    assert result.scalar() == 0


@pytest.mark.asyncio
async def test_turn_escalation_above_050_flagged(session: AsyncSession) -> None:
    extra_ids = await _add_jobs(session, 4)
    summary = TelemetrySummaryRepository(session)

    for jid in extra_ids:
        await summary.increment(jid, total_cost_usd=2.0, total_turns=10)
        await summary.set_turn_stats(jid, cost_first_half_usd=0.25, cost_second_half_usd=1.75)
        await summary.finalize(jid, status="completed", duration_ms=10000)
    await session.commit()

    count = await run_analysis(session)
    await session.commit()

    result = await session.execute(
        text("SELECT COUNT(*) FROM cost_observations WHERE category = 'turn_escalation'")
    )
    assert result.scalar() == 1


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

    count = await run_analysis(session)
    await session.commit()

    result = await session.execute(
        text("SELECT COUNT(*) FROM cost_observations WHERE category = 'tool_failure'")
    )
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

    count = await run_analysis(session)
    await session.commit()

    result = await session.execute(
        text("SELECT COUNT(*) FROM cost_observations WHERE category = 'retry_waste'")
    )
    assert result.scalar() == 1


@pytest.mark.asyncio
async def test_compaction_storms_flagged(session: AsyncSession) -> None:
    extra_ids = await _add_jobs(session, 3)
    summary = TelemetrySummaryRepository(session)

    for jid in extra_ids:
        await summary.increment(jid, compactions=8, tokens_compacted=50000, total_turns=20)
        await summary.finalize(jid, status="completed", duration_ms=10000)
    await session.commit()

    count = await run_analysis(session)
    await session.commit()

    result = await session.execute(
        text("SELECT COUNT(*) FROM cost_observations WHERE category = 'compaction_storm'")
    )
    assert result.scalar() == 1


@pytest.mark.asyncio
async def test_cache_regression_not_triggered_without_enough_data(session: AsyncSession) -> None:
    count = await run_analysis(session)
    await session.commit()

    result = await session.execute(
        text("SELECT COUNT(*) FROM cost_observations WHERE category = 'cache_regression'")
    )
    assert result.scalar() == 0
