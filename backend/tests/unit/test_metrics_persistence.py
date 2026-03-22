"""Tests for metrics persistence and cross-session aggregation."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import event as sa_event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

from backend.models.db import Base, JobRow
from backend.models.domain import JobState, PermissionMode
from backend.persistence.database import _set_sqlite_pragmas
from backend.persistence.metrics_repo import MetricsRepository
from backend.services.telemetry import QuotaSnapshot, TelemetryCollector


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sa_event.listen(engine.sync_engine, "connect", _set_sqlite_pragmas)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as sess:
        # Insert a parent job row so FK constraint is satisfied
        now = datetime.now(UTC)
        sess.add(
            JobRow(
                id="job-1",
                repo="/repos/test",
                prompt="Fix the bug",
                state=JobState.running,
                base_ref="main",
                permission_mode=PermissionMode.auto,
                sdk="copilot",
                created_at=now,
                updated_at=now,
            )
        )
        await sess.commit()
        yield sess

    await engine.dispose()


# ---------------------------------------------------------------------------
# MetricsRepository
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_metrics_repo_save_and_load(session: AsyncSession) -> None:
    repo = MetricsRepository(session)
    snapshot = {"input_tokens": 500, "output_tokens": 200, "total_cost": 0.01}

    await repo.save_snapshot("job-1", snapshot)
    await session.commit()

    loaded = await repo.load_snapshot("job-1")
    assert loaded is not None
    assert loaded["input_tokens"] == 500
    assert loaded["output_tokens"] == 200
    assert loaded["total_cost"] == 0.01


@pytest.mark.asyncio
async def test_metrics_repo_upsert(session: AsyncSession) -> None:
    repo = MetricsRepository(session)

    await repo.save_snapshot("job-1", {"input_tokens": 100})
    await session.commit()
    await repo.save_snapshot("job-1", {"input_tokens": 350})
    await session.commit()

    loaded = await repo.load_snapshot("job-1")
    assert loaded is not None
    assert loaded["input_tokens"] == 350


@pytest.mark.asyncio
async def test_metrics_repo_load_missing_returns_none(session: AsyncSession) -> None:
    repo = MetricsRepository(session)
    assert await repo.load_snapshot("no-such-job") is None


# ---------------------------------------------------------------------------
# JobTelemetry.to_snapshot / TelemetryCollector.restore_from_snapshot
# ---------------------------------------------------------------------------


def _make_collector_with_metrics(job_id: str = "job-1") -> TelemetryCollector:
    """Return a collector with some recorded activity."""
    col = TelemetryCollector()
    col.start_job(job_id, model="gpt-4o")
    col.set_main_model(job_id, "gpt-4o")
    col.record_llm_usage(
        job_id,
        model="gpt-4o",
        input_tokens=300,
        output_tokens=150,
        cost=0.005,
        duration_ms=1200,
    )
    col.record_tool_call(job_id, tool_name="read_file", duration_ms=50, success=True)
    col.record_approval(job_id, wait_ms=3000)
    col.record_message(job_id, role="agent")
    col.record_message(job_id, role="operator")
    col.record_premium_requests(job_id, count=2.5)
    col.record_quota_snapshots(
        job_id,
        snapshots={"premium": QuotaSnapshot(used_requests=2.5, entitlement_requests=10.0, remaining_percentage=75.0)},
    )
    col.end_job(job_id)
    return col


def test_to_snapshot_captures_all_cumulative_fields() -> None:
    col = _make_collector_with_metrics()
    tel = col.get("job-1")
    assert tel is not None
    snap = tel.to_snapshot()

    assert snap["input_tokens"] == 300
    assert snap["output_tokens"] == 150
    assert snap["total_tokens"] == 450
    assert snap["total_cost"] == 0.005
    assert snap["tool_call_count"] == 1
    assert snap["llm_call_count"] == 1
    assert snap["approval_count"] == 1
    assert snap["agent_messages"] == 1
    assert snap["operator_messages"] == 1
    assert snap["premium_requests"] == 2.5
    assert snap["model"] == "gpt-4o"
    assert snap["main_model"] == "gpt-4o"
    assert isinstance(snap["duration_ms"], float)
    assert snap["duration_ms"] > 0

    assert isinstance(snap["tool_calls_raw"], list)
    assert len(snap["tool_calls_raw"]) == 1
    assert snap["tool_calls_raw"][0]["name"] == "read_file"

    assert isinstance(snap["llm_calls_raw"], list)
    assert len(snap["llm_calls_raw"]) == 1

    assert "premium" in snap["quota_snapshots_raw"]


def test_restore_from_snapshot_replaces_fresh_entry() -> None:
    """Simulates process restart: fresh collector, restored from snapshot."""
    original = _make_collector_with_metrics()
    tel_orig = original.get("job-1")
    assert tel_orig is not None
    snap = tel_orig.to_snapshot()

    # New process — empty collector
    fresh = TelemetryCollector()
    fresh.start_job("job-1", model="")
    fresh.restore_from_snapshot("job-1", snap)

    tel = fresh.get("job-1")
    assert tel is not None

    # Cumulative counters carried forward
    assert tel.input_tokens == 300
    assert tel.output_tokens == 150
    assert tel.total_tokens == 450
    assert tel.total_cost == 0.005
    assert tel.tool_call_count == 1
    assert tel.llm_call_count == 1
    assert tel.approval_count == 1
    assert tel.agent_messages == 1
    assert tel.operator_messages == 1
    assert tel.premium_requests == 2.5
    assert tel.model == "gpt-4o"
    assert tel.main_model == "gpt-4o"
    assert tel.accumulated_duration_ms > 0

    # Call history restored
    assert len(tel.tool_calls) == 1
    assert tel.tool_calls[0].name == "read_file"
    assert len(tel.llm_calls) == 1

    # Quota snapshots restored
    assert "premium" in tel.quota_snapshots
    assert tel.quota_snapshots["premium"].used_requests == 2.5


def test_restore_then_continue_accumulates_correctly() -> None:
    """New session metrics add on top of the restored snapshot totals."""
    original = _make_collector_with_metrics()
    snap = original.get("job-1").to_snapshot()

    # Resumed session in a fresh collector
    fresh = TelemetryCollector()
    fresh.start_job("job-1", model="gpt-4o")
    fresh.restore_from_snapshot("job-1", snap)

    # Second session records additional usage
    fresh.record_llm_usage("job-1", model="gpt-4o", input_tokens=100, output_tokens=50, cost=0.002)
    fresh.record_tool_call("job-1", tool_name="write_file", duration_ms=80)

    tel = fresh.get("job-1")
    assert tel is not None
    assert tel.input_tokens == 400   # 300 + 100
    assert tel.output_tokens == 200  # 150 + 50
    assert tel.total_tokens == 600   # 450 + 150
    assert tel.tool_call_count == 2  # 1 + 1
    assert tel.llm_call_count == 2   # 1 + 1


def test_restore_noop_when_no_entry() -> None:
    """restore_from_snapshot is a no-op when the job has no in-memory entry."""
    col = TelemetryCollector()
    # No start_job called — should not raise
    col.restore_from_snapshot("ghost-job", {"input_tokens": 999})
    assert col.get("ghost-job") is None
