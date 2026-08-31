"""Tests for approval-gated tracker writes (Story 3.4)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.models.db import Base, JobRow, ProjectRow
from backend.services.job.approval_service import ApprovalService
from backend.services.tracker_write_service import (
    TrackerWriteAction,
    TrackerWriteRequest,
    TrackerWriteService,
    TrackerWriteState,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


@pytest.fixture
async def session_factory() -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        session.add(
            ProjectRow(
                id="proj-1",
                name="Test Project",
                repo_paths='["/test"]',
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        await session.flush()
        session.add(
            JobRow(
                id="job-1",
                repo="/test",
                project_id="proj-1",
                prompt="test",
                state="running",
                base_ref="main",
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        await session.commit()
    yield factory
    await engine.dispose()


@pytest.fixture
def approval_service(session_factory: async_sessionmaker[AsyncSession]) -> ApprovalService:
    return ApprovalService(session_factory)


@pytest.fixture
def tracker_write_service(approval_service: ApprovalService) -> TrackerWriteService:
    return TrackerWriteService(approval_service)


async def _pending_approval(approval_service: ApprovalService):
    for _ in range(20):
        pending = await approval_service.list_pending("job-1")
        if pending:
            return pending[0]
        await asyncio.sleep(0)
    pytest.fail("Tracker write did not create an approval")


@pytest.mark.asyncio
async def test_rejected_write_uses_existing_approval_and_is_never_dispatched(
    approval_service: ApprovalService,
    tracker_write_service: TrackerWriteService,
) -> None:
    request = TrackerWriteRequest(
        tracker_link_id="link-1",
        ticket_ref="ABC-123",
        action=TrackerWriteAction.comment,
        value="Ready for review",
    )
    dispatch = AsyncMock()

    execution = asyncio.create_task(tracker_write_service.execute("job-1", request, dispatch))
    approval = await _pending_approval(approval_service)

    assert approval.requires_explicit_approval is True
    assert approval.description == "Comment on tracker ticket ABC-123?"
    assert approval.proposed_action == (
        '{"action":"comment","ticketRef":"ABC-123","trackerLinkId":"link-1","value":"Ready for review"}'
    )

    await approval_service.resolve(approval.id, "rejected")

    assert (await execution).state == TrackerWriteState.rejected
    dispatch.assert_not_awaited()


@pytest.mark.asyncio
async def test_approved_write_is_dispatched_once(
    approval_service: ApprovalService,
    tracker_write_service: TrackerWriteService,
) -> None:
    request = TrackerWriteRequest(
        tracker_link_id="link-1",
        ticket_ref="ABC-123",
        action=TrackerWriteAction.transition,
        value="Done",
    )
    dispatch = AsyncMock()

    execution = asyncio.create_task(tracker_write_service.execute("job-1", request, dispatch))
    approval = await _pending_approval(approval_service)
    await approval_service.resolve(approval.id, "approved")

    assert (await execution).state == TrackerWriteState.applied
    dispatch.assert_awaited_once_with(request)


@pytest.mark.asyncio
async def test_blanket_job_trust_cannot_auto_approve_tracker_write(
    approval_service: ApprovalService,
    tracker_write_service: TrackerWriteService,
) -> None:
    request = TrackerWriteRequest(
        tracker_link_id="link-1",
        ticket_ref="ABC-123",
        action=TrackerWriteAction.comment,
        value="Ready for review",
    )
    dispatch = AsyncMock()

    execution = asyncio.create_task(tracker_write_service.execute("job-1", request, dispatch))
    approval = await _pending_approval(approval_service)

    assert await approval_service.trust_job("job-1") == 0
    assert not execution.done()

    await approval_service.resolve(approval.id, "rejected")
    assert (await execution).state == TrackerWriteState.rejected
    dispatch.assert_not_awaited()


@pytest.mark.asyncio
async def test_provider_failure_is_reported_as_failed(
    approval_service: ApprovalService,
    tracker_write_service: TrackerWriteService,
) -> None:
    request = TrackerWriteRequest(
        tracker_link_id="link-1",
        ticket_ref="ABC-123",
        action=TrackerWriteAction.comment,
        value="Ready for review",
    )
    dispatch = AsyncMock(side_effect=RuntimeError("provider unavailable"))

    execution = asyncio.create_task(tracker_write_service.execute("job-1", request, dispatch))
    approval = await _pending_approval(approval_service)
    await approval_service.resolve(approval.id, "approved")

    outcome = await execution
    assert outcome.state == TrackerWriteState.failed
    assert outcome.applied is False
    assert outcome.error == "provider unavailable"
    dispatch.assert_awaited_once_with(request)
