"""Tests for trail.activity_tracker — activity boundary detection."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.models.events import DomainEvent, DomainEventKind
from backend.services.events.event_bus import EventBus

# Import after models to avoid circular
from backend.services.trail.activity_tracker import ActivityTracker
from backend.services.trail.models import (
    Activity,
    ActivityStep,
    PlanStep,
    TrailJobState,
)
from backend.services.trail.title_generator import TitleGenerator, TitleResult


def _state(**overrides: object) -> TrailJobState:
    defaults = dict(
        job_prompt="Fix bugs",
        plan_steps=[PlanStep(plan_step_id="ps-1", label="Fix", status="active", order=0)],
        activities=[Activity(activity_id="a1", label="Fixing", status="active")],
        activity_steps=[],
        plan_established=True,
        active_idx=0,
    )
    defaults.update(overrides)
    return TrailJobState(**defaults)


@pytest.fixture
def event_bus() -> EventBus:
    return EventBus()


@pytest.fixture
def job_state() -> dict[str, TrailJobState]:
    return {}


@pytest.fixture
def title_gen() -> TitleGenerator:
    return TitleGenerator()


@pytest.fixture
def tracker(event_bus: EventBus, job_state: dict, title_gen: TitleGenerator) -> ActivityTracker:
    return ActivityTracker(
        event_bus=event_bus,
        job_state=job_state,
        title_generator=title_gen,
    )


# ---------------------------------------------------------------------------
# emit_activity_step — guard conditions
# ---------------------------------------------------------------------------


class TestEmitActivityStepGuards:
    @pytest.mark.asyncio
    async def test_ignores_unknown_job(self, tracker: ActivityTracker) -> None:
        await tracker.emit_activity_step(
            "unknown",
            node_id="n1",
            sidecar=AsyncMock(),
            turn_id="t1",
            agent_msg="hi",
            files_read=[],
            files_written=[],
            duration_ms=100,
            assigned_plan_step_id=None,
        )

    @pytest.mark.asyncio
    async def test_returns_without_sidecar(self, tracker: ActivityTracker, job_state: dict[str, TrailJobState]) -> None:
        job_state["j1"] = _state()
        await tracker.emit_activity_step(
            "j1",
            node_id="n1",
            sidecar=None,
            turn_id="t1",
            agent_msg="hi",
            files_read=[],
            files_written=[],
            duration_ms=100,
            assigned_plan_step_id=None,
        )
        # No events, no errors — just returns


# ---------------------------------------------------------------------------
# emit_activity_step — title generation failure
# ---------------------------------------------------------------------------


class TestEmitActivityStepTitleFailure:
    @pytest.mark.asyncio
    async def test_returns_on_title_gen_failure(self, event_bus: EventBus, job_state: dict[str, TrailJobState]) -> None:
        title_gen = TitleGenerator()
        sidecar = AsyncMock()
        sidecar.complete.side_effect = OSError("fail")

        tracker = ActivityTracker(
            event_bus=event_bus,
            job_state=job_state,
            title_generator=title_gen,
        )
        job_state["j1"] = _state()

        events: list[DomainEvent] = []

        async def _handler(e: DomainEvent) -> None:
            if e.kind == DomainEventKind.turn_summary:
                events.append(e)

        event_bus.subscribe(_handler)

        await tracker.emit_activity_step(
            "j1",
            node_id="n1",
            sidecar=sidecar,
            turn_id="t1",
            agent_msg="hi",
            files_read=[],
            files_written=[],
            duration_ms=100,
            assigned_plan_step_id=None,
        )
        # No turn_summary events should be emitted on failure
        assert len(events) == 0


# ---------------------------------------------------------------------------
# emit_activity_step — same activity
# ---------------------------------------------------------------------------


class TestEmitActivityStepSameActivity:
    @pytest.mark.asyncio
    async def test_appends_step_to_current_activity(
        self, event_bus: EventBus, job_state: dict[str, TrailJobState]
    ) -> None:
        title_gen = MagicMock(spec=TitleGenerator)
        title_gen.generate = AsyncMock(
            return_value=TitleResult(
                title="Fixed auth",
                merge_with_previous=False,
                new_activity=False,
                activity_label=None,
            )
        )

        tracker = ActivityTracker(
            event_bus=event_bus,
            job_state=job_state,
            title_generator=title_gen,
        )
        state = _state()
        job_state["j1"] = state

        events: list[DomainEvent] = []

        async def _handler(e: DomainEvent) -> None:
            if e.kind == DomainEventKind.turn_summary:
                events.append(e)

        event_bus.subscribe(_handler)

        await tracker.emit_activity_step(
            "j1",
            node_id="n1",
            sidecar=AsyncMock(),
            turn_id="t1",
            agent_msg="Fixed the auth bug",
            files_read=[],
            files_written=["auth.py"],
            duration_ms=500,
            assigned_plan_step_id="ps-1",
        )

        assert len(state.activity_steps) == 1
        assert state.activity_steps[0].title == "Fixed auth"
        assert len(events) == 1
        assert events[0].payload["title"] == "Fixed auth"
        assert events[0].payload["is_new_activity"] is False


# ---------------------------------------------------------------------------
# emit_activity_step — new activity boundary
# ---------------------------------------------------------------------------


class TestEmitActivityStepNewActivity:
    @pytest.mark.asyncio
    async def test_creates_new_activity(self, event_bus: EventBus, job_state: dict[str, TrailJobState]) -> None:
        title_gen = MagicMock(spec=TitleGenerator)
        title_gen.generate = AsyncMock(
            return_value=TitleResult(
                title="Start testing",
                merge_with_previous=False,
                new_activity=True,
                activity_label="Running tests",
            )
        )

        tracker = ActivityTracker(
            event_bus=event_bus,
            job_state=job_state,
            title_generator=title_gen,
        )
        state = _state()
        job_state["j1"] = state

        events: list[DomainEvent] = []

        async def _handler(e: DomainEvent) -> None:
            if e.kind == DomainEventKind.turn_summary:
                events.append(e)

        event_bus.subscribe(_handler)

        await tracker.emit_activity_step(
            "j1",
            node_id="n1",
            sidecar=AsyncMock(),
            turn_id="t1",
            agent_msg="Now testing",
            files_read=[],
            files_written=[],
            duration_ms=100,
            assigned_plan_step_id="ps-1",
        )

        assert len(state.activities) == 2
        assert state.activities[0].status == "done"
        assert state.activities[1].label == "Running tests"
        assert state.activities[1].status == "active"
        assert events[0].payload["is_new_activity"] is True

    @pytest.mark.asyncio
    async def test_new_activity_suppressed_without_label(
        self, event_bus: EventBus, job_state: dict[str, TrailJobState]
    ) -> None:
        """When LLM says shift but gives no label and no plan step, suppress."""
        title_gen = MagicMock(spec=TitleGenerator)
        title_gen.generate = AsyncMock(
            return_value=TitleResult(
                title="Doing something",
                merge_with_previous=False,
                new_activity=True,
                activity_label=None,
            )
        )

        tracker = ActivityTracker(
            event_bus=event_bus,
            job_state=job_state,
            title_generator=title_gen,
        )
        state = _state(plan_steps=[])  # No plan steps either
        job_state["j1"] = state

        await tracker.emit_activity_step(
            "j1",
            node_id="n1",
            sidecar=AsyncMock(),
            turn_id="t1",
            agent_msg="hi",
            files_read=[],
            files_written=[],
            duration_ms=100,
            assigned_plan_step_id=None,
        )
        # Should NOT create a new activity (suppressed)
        assert len(state.activities) == 1


# ---------------------------------------------------------------------------
# emit_activity_step — merge with previous
# ---------------------------------------------------------------------------


class TestEmitActivityStepMerge:
    @pytest.mark.asyncio
    async def test_merge_replaces_previous_step(self, event_bus: EventBus, job_state: dict[str, TrailJobState]) -> None:
        title_gen = MagicMock(spec=TitleGenerator)
        title_gen.generate = AsyncMock(
            return_value=TitleResult(
                title="Retry build (merged)",
                merge_with_previous=True,
                new_activity=False,
                activity_label=None,
            )
        )

        tracker = ActivityTracker(
            event_bus=event_bus,
            job_state=job_state,
            title_generator=title_gen,
        )
        state = _state(
            activity_steps=[
                ActivityStep(turn_id="t0", title="Build attempt", activity_id="a1"),
            ],
        )
        job_state["j1"] = state

        events: list[DomainEvent] = []

        async def _handler(e: DomainEvent) -> None:
            if e.kind == DomainEventKind.turn_summary:
                events.append(e)

        event_bus.subscribe(_handler)

        await tracker.emit_activity_step(
            "j1",
            node_id="n1",
            sidecar=AsyncMock(),
            turn_id="t1",
            agent_msg="Retrying build",
            files_read=[],
            files_written=[],
            duration_ms=50,
            assigned_plan_step_id=None,
        )

        # Previous step's title is updated, no new step added
        assert len(state.activity_steps) == 1
        assert state.activity_steps[0].title == "Retry build (merged)"
        assert state.activity_steps[0].turn_id == "t1"
        assert events[0].payload.get("replaces_turn_id") == "t0"


# ---------------------------------------------------------------------------
# First turn bootstrap
# ---------------------------------------------------------------------------


class TestFirstTurnBootstrap:
    @pytest.mark.asyncio
    async def test_first_turn_creates_activity(self, event_bus: EventBus, job_state: dict[str, TrailJobState]) -> None:
        title_gen = MagicMock(spec=TitleGenerator)
        title_gen.generate = AsyncMock(
            return_value=TitleResult(
                title="Initial setup",
                merge_with_previous=False,
                new_activity=False,
                activity_label=None,
            )
        )

        tracker = ActivityTracker(
            event_bus=event_bus,
            job_state=job_state,
            title_generator=title_gen,
        )
        state = _state(activities=[], activity_steps=[])
        job_state["j1"] = state

        await tracker.emit_activity_step(
            "j1",
            node_id="n1",
            sidecar=AsyncMock(),
            turn_id="t1",
            agent_msg="Starting",
            files_read=[],
            files_written=[],
            duration_ms=100,
            assigned_plan_step_id=None,
        )

        # Should create the first activity automatically
        assert len(state.activities) >= 1
