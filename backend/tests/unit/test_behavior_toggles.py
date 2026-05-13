"""Tests for per-job behavior toggles (enable_stall_detection, enable_plan_tracking).

Covers:
 - TrailService plan-tracking gate: disabled jobs skip plan inference
 - DB round-trip: toggle fields persist and load correctly
 - Domain model: toggles on JobSpec / Job
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.models.db import Base, JobRow
from backend.models.events import DomainEvent, DomainEventKind
from backend.services.event_bus import EventBus
from backend.services.trail import TrailService

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest.fixture
async def session_factory(engine):
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
def event_bus():
    return EventBus()


@pytest.fixture
def trail_service(session_factory, event_bus):
    return TrailService(session_factory=session_factory, event_bus=event_bus)


def _make_event(
    kind: DomainEventKind,
    job_id: str = "job-1",
    payload: dict | None = None,
) -> DomainEvent:
    return DomainEvent(
        event_id=DomainEvent.make_event_id(),
        job_id=job_id,
        timestamp=datetime.now(UTC),
        kind=kind,
        payload=payload or {},
    )


# ===================================================================
# Plan tracking toggle — TrailService gate
# ===================================================================


class TestPlanTrackingToggle:
    """Verify that disable_plan_tracking suppresses plan-related processing."""

    @pytest.mark.asyncio
    async def test_feed_transcript_skipped_when_disabled(self, trail_service: TrailService) -> None:
        trail_service.disable_plan_tracking("job-1")
        with patch.object(trail_service._plan_manager, "feed_transcript", new_callable=AsyncMock) as mock:
            await trail_service.feed_transcript("job-1", "agent", "hello")
            mock.assert_not_called()

    @pytest.mark.asyncio
    async def test_feed_transcript_allowed_when_not_disabled(self, trail_service: TrailService) -> None:
        with patch.object(trail_service._plan_manager, "feed_transcript", new_callable=AsyncMock) as mock:
            await trail_service.feed_transcript("job-1", "agent", "hello")
            mock.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_feed_tool_name_skipped_when_disabled(self, trail_service: TrailService) -> None:
        trail_service.disable_plan_tracking("job-1")
        with patch.object(trail_service._plan_manager, "feed_tool_name", new_callable=AsyncMock) as mock:
            await trail_service.feed_tool_name("job-1", "read_file")
            mock.assert_not_called()

    @pytest.mark.asyncio
    async def test_feed_native_plan_skipped_when_disabled(self, trail_service: TrailService) -> None:
        trail_service.disable_plan_tracking("job-1")
        with patch.object(trail_service._plan_manager, "feed_native_plan", new_callable=AsyncMock) as mock:
            await trail_service.feed_native_plan("job-1", [{"id": "1", "title": "t", "status": "done"}])
            mock.assert_not_called()

    @pytest.mark.asyncio
    async def test_finalize_skipped_when_disabled(self, trail_service: TrailService) -> None:
        trail_service.disable_plan_tracking("job-1")
        with patch.object(trail_service._plan_manager, "finalize", new_callable=AsyncMock) as mock:
            await trail_service.finalize("job-1", succeeded=True)
            mock.assert_not_called()

    @pytest.mark.asyncio
    async def test_finalize_allowed_when_not_disabled(self, trail_service: TrailService) -> None:
        with patch.object(trail_service._plan_manager, "finalize", new_callable=AsyncMock) as mock:
            await trail_service.finalize("job-1", succeeded=True)
            mock.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handle_event_skips_plan_for_disabled_job(self, trail_service: TrailService) -> None:
        """Transcript events for disabled jobs skip plan feed but still run node_builder."""
        # Initialize job state so the event handler doesn't bail early
        start_event = _make_event(
            DomainEventKind.job_state_changed,
            payload={"previous_state": "queued", "new_state": "running"},
        )
        await trail_service.handle_event(start_event)

        trail_service.disable_plan_tracking("job-1")

        with patch.object(trail_service._plan_manager, "feed_transcript", new_callable=AsyncMock) as feed_mock:
            event = _make_event(
                DomainEventKind.transcript_updated,
                payload={"role": "agent", "content": "I will do stuff"},
            )
            await trail_service.handle_event(event)
            feed_mock.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_event_skips_native_plan_for_disabled_job(self, trail_service: TrailService) -> None:
        """Native plan tool calls are ignored for disabled jobs."""
        start_event = _make_event(
            DomainEventKind.job_state_changed,
            payload={"previous_state": "queued", "new_state": "running"},
        )
        await trail_service.handle_event(start_event)

        trail_service.disable_plan_tracking("job-1")

        with patch.object(trail_service._plan_manager, "feed_native_plan", new_callable=AsyncMock) as plan_mock:
            event = _make_event(
                DomainEventKind.transcript_updated,
                payload={
                    "role": "tool_call",
                    "tool_name": "manage_todo_list",
                    "tool_args": '{"todoList": []}',
                    "content": "",
                },
            )
            await trail_service.handle_event(event)
            plan_mock.assert_not_called()

    def test_cleanup_removes_disabled_flag(self, trail_service: TrailService) -> None:
        trail_service.disable_plan_tracking("job-1")
        assert "job-1" in trail_service._plan_tracking_disabled
        trail_service.cleanup("job-1")
        assert "job-1" not in trail_service._plan_tracking_disabled

    @pytest.mark.asyncio
    async def test_other_job_unaffected(self, trail_service: TrailService) -> None:
        """Disabling plan tracking for one job does not affect another."""
        trail_service.disable_plan_tracking("job-1")
        with patch.object(trail_service._plan_manager, "feed_transcript", new_callable=AsyncMock) as mock:
            await trail_service.feed_transcript("job-2", "agent", "hello")
            mock.assert_awaited_once()


# ===================================================================
# DB round-trip — toggle fields persist through JobRow
# ===================================================================


class TestToggleDbRoundTrip:
    @pytest.mark.asyncio
    async def test_stall_detection_persists(self, session_factory) -> None:
        async with session_factory() as session:
            now = datetime.now(UTC)
            row = JobRow(
                id="j-stall",
                repo="https://example.com/repo",
                prompt="test",
                base_ref="main",
                state="queued",
                sdk="copilot",
                model="gpt-4o",
                created_at=now,
                updated_at=now,
                enable_stall_detection=False,
            )
            session.add(row)
            await session.commit()

        async with session_factory() as session:
            loaded = await session.get(JobRow, "j-stall")
            assert loaded is not None
            assert loaded.enable_stall_detection is False

    @pytest.mark.asyncio
    async def test_plan_tracking_persists(self, session_factory) -> None:
        async with session_factory() as session:
            now = datetime.now(UTC)
            row = JobRow(
                id="j-plan",
                repo="https://example.com/repo",
                prompt="test",
                base_ref="main",
                state="queued",
                sdk="copilot",
                model="gpt-4o",
                created_at=now,
                updated_at=now,
                enable_plan_tracking=False,
            )
            session.add(row)
            await session.commit()

        async with session_factory() as session:
            loaded = await session.get(JobRow, "j-plan")
            assert loaded is not None
            assert loaded.enable_plan_tracking is False

    @pytest.mark.asyncio
    async def test_toggles_default_to_none(self, session_factory) -> None:
        async with session_factory() as session:
            now = datetime.now(UTC)
            row = JobRow(
                id="j-default",
                repo="https://example.com/repo",
                prompt="test",
                base_ref="main",
                state="queued",
                sdk="copilot",
                model="gpt-4o",
                created_at=now,
                updated_at=now,
            )
            session.add(row)
            await session.commit()

        async with session_factory() as session:
            loaded = await session.get(JobRow, "j-default")
            assert loaded is not None
            assert loaded.enable_stall_detection is None
            assert loaded.enable_plan_tracking is None


# ===================================================================
# Domain model — JobSpec toggles
# ===================================================================


class TestDomainToggles:
    def test_jobspec_toggle_defaults(self) -> None:
        from backend.models.domain import JobSpec

        spec = JobSpec(
            repo="https://example.com/repo",
            prompt="test",
            model="gpt-4o",
        )
        assert spec.enable_stall_detection is None
        assert spec.enable_plan_tracking is None

    def test_jobspec_toggle_explicit(self) -> None:
        from backend.models.domain import JobSpec

        spec = JobSpec(
            repo="https://example.com/repo",
            prompt="test",
            model="gpt-4o",
            enable_stall_detection=False,
            enable_plan_tracking=False,
        )
        assert spec.enable_stall_detection is False
        assert spec.enable_plan_tracking is False
