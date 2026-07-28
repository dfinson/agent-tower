"""Tests for StepPersistenceSubscriber."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from backend.models.events import EventKind, new_event
from backend.services.steps.persistence import StepPersistenceSubscriber


@pytest.fixture()
def step_repo() -> AsyncMock:
    return AsyncMock()


@pytest.fixture()
def subscriber(step_repo: AsyncMock) -> StepPersistenceSubscriber:
    return StepPersistenceSubscriber(step_repo=step_repo)


class TestStepPersistence:
    @pytest.mark.asyncio
    async def test_step_started_persists_row(self, subscriber: StepPersistenceSubscriber, step_repo: AsyncMock) -> None:
        now = datetime.now(UTC)
        event = new_event(
            event_id="evt-1",
            session_id="job-1",
            timestamp=now,
            kind=EventKind.step_started,
            payload={
                "step_id": "step-1",
                "step_number": 1,
                "trigger": "tool_call",
                "intent": "Edit files",
            },
        )
        await subscriber(event)
        step_repo.create.assert_called_once()
        row = step_repo.create.call_args[0][0]
        assert row.id == "step-1"
        assert row.job_id == "job-1"
        assert row.step_number == 1
        assert row.trigger == "tool_call"

    @pytest.mark.asyncio
    async def test_step_completed_updates_row(
        self,
        subscriber: StepPersistenceSubscriber,
        step_repo: AsyncMock,
    ) -> None:
        now = datetime.now(UTC)
        event = new_event(
            event_id="evt-2",
            session_id="job-1",
            timestamp=now,
            kind=EventKind.step_completed,
            payload={
                "step_id": "step-1",
                "status": "done",
                "tool_count": 5,
                "duration_ms": 1234,
            },
        )
        await subscriber(event)
        step_repo.complete.assert_called_once()

    @pytest.mark.asyncio
    async def test_unrelated_event_is_noop(self, subscriber: StepPersistenceSubscriber, step_repo: AsyncMock) -> None:
        now = datetime.now(UTC)
        event = new_event(
            event_id="evt-3", session_id="job-1", timestamp=now, kind=EventKind.job_created, payload={}
        )
        await subscriber(event)
        step_repo.create.assert_not_called()
        step_repo.complete.assert_not_called()
