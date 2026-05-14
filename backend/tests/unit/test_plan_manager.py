"""Tests for trail.plan_manager — plan inference, classification, native plan ingestion."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from backend.models.events import DomainEvent, DomainEventKind
from backend.services.events.event_bus import EventBus
from backend.services.trail.models import (
    PlanStep,
    TrailJobState,
)
from backend.services.trail.plan_manager import PlanManager


def _state(**overrides: object) -> TrailJobState:
    return TrailJobState(**overrides)


@pytest.fixture
def event_bus() -> EventBus:
    return EventBus()


@pytest.fixture
def job_state() -> dict[str, TrailJobState]:
    return {}


@pytest.fixture
def manager(event_bus: EventBus, job_state: dict[str, TrailJobState]) -> PlanManager:
    return PlanManager(event_bus=event_bus, job_state=job_state)


# ---------------------------------------------------------------------------
# feed_transcript
# ---------------------------------------------------------------------------


class TestFeedTranscript:
    @pytest.mark.asyncio
    async def test_ignores_unknown_job(self, manager: PlanManager) -> None:
        await manager.feed_transcript("unknown", "agent", "hello")

    @pytest.mark.asyncio
    async def test_buffers_agent_messages(self, manager: PlanManager, job_state: dict[str, TrailJobState]) -> None:
        job_state["j1"] = _state(job_prompt="Fix bugs")
        await manager.feed_transcript("j1", "agent", "Starting work")
        assert "Starting work" in job_state["j1"].recent_messages

    @pytest.mark.asyncio
    async def test_buffers_tool_intents(self, manager: PlanManager, job_state: dict[str, TrailJobState]) -> None:
        job_state["j1"] = _state()
        await manager.feed_transcript("j1", "tool_call", "", tool_intent="reading file")
        assert "reading file" in job_state["j1"].recent_tool_intents


# ---------------------------------------------------------------------------
# feed_tool_name
# ---------------------------------------------------------------------------


class TestFeedToolName:
    @pytest.mark.asyncio
    async def test_ignores_unknown_job(self, manager: PlanManager) -> None:
        await manager.feed_tool_name("unknown", "read_file")

    @pytest.mark.asyncio
    async def test_adds_unique_tool_names(self, manager: PlanManager, job_state: dict[str, TrailJobState]) -> None:
        job_state["j1"] = _state()
        await manager.feed_tool_name("j1", "read_file")
        await manager.feed_tool_name("j1", "read_file")
        await manager.feed_tool_name("j1", "grep_search")
        assert job_state["j1"].recent_tool_names == ["read_file", "grep_search"]

    @pytest.mark.asyncio
    async def test_increments_tool_call_count(self, manager: PlanManager, job_state: dict[str, TrailJobState]) -> None:
        job_state["j1"] = _state()
        await manager.feed_tool_name("j1", "a")
        await manager.feed_tool_name("j1", "b")
        await manager.feed_tool_name("j1", "c")
        assert job_state["j1"].tool_call_count == 3


# ---------------------------------------------------------------------------
# infer_plan
# ---------------------------------------------------------------------------


class TestInferPlan:
    @pytest.mark.asyncio
    async def test_ignores_unknown_job(self, manager: PlanManager, job_state: dict[str, TrailJobState]) -> None:
        sidecar = AsyncMock()
        await manager.infer_plan("unknown", sidecar)
        sidecar.complete.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_skips_no_content(self, manager: PlanManager, job_state: dict[str, TrailJobState]) -> None:
        job_state["j1"] = _state()
        sidecar = AsyncMock()
        await manager.infer_plan("j1", sidecar)
        sidecar.complete.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_successful_inference(
        self, manager: PlanManager, job_state: dict[str, TrailJobState], event_bus: EventBus
    ) -> None:
        state = _state(job_prompt="Add tests", recent_messages=["I'll add unit tests first"])
        job_state["j1"] = state

        sidecar = AsyncMock()
        sidecar.complete.return_value = json.dumps(
            {
                "items": ["Write unit tests", "Fix lint", "Run CI"],
            }
        )

        events: list[DomainEvent] = []

        async def _handler(e: DomainEvent) -> None:
            if e.kind == DomainEventKind.plan_step_updated:
                events.append(e)

        event_bus.subscribe(_handler)

        await manager.infer_plan("j1", sidecar)

        assert state.plan_established is True
        assert len(state.plan_steps) == 3
        assert state.plan_steps[0].label == "Write unit tests"
        assert state.plan_steps[0].status == "active"
        assert state.plan_steps[1].status == "pending"
        assert len(events) == 3

    @pytest.mark.asyncio
    async def test_llm_error_tolerant(self, manager: PlanManager, job_state: dict[str, TrailJobState]) -> None:
        job_state["j1"] = _state(job_prompt="Do something", recent_messages=["Starting"])
        sidecar = AsyncMock()
        sidecar.complete.side_effect = OSError("fail")

        await manager.infer_plan("j1", sidecar)
        assert job_state["j1"].plan_established is False

    @pytest.mark.asyncio
    async def test_empty_items_no_plan(self, manager: PlanManager, job_state: dict[str, TrailJobState]) -> None:
        job_state["j1"] = _state(job_prompt="Stuff", recent_messages=["OK"])
        sidecar = AsyncMock()
        sidecar.complete.return_value = json.dumps({"items": []})

        await manager.infer_plan("j1", sidecar)
        assert job_state["j1"].plan_established is False

    @pytest.mark.asyncio
    async def test_code_fence_stripped(self, manager: PlanManager, job_state: dict[str, TrailJobState]) -> None:
        job_state["j1"] = _state(job_prompt="Task", recent_messages=["First msg"])
        sidecar = AsyncMock()
        sidecar.complete.return_value = '```json\n{"items": ["Step A"]}\n```'

        await manager.infer_plan("j1", sidecar)
        assert job_state["j1"].plan_established is True
        assert job_state["j1"].plan_steps[0].label == "Step A"


# ---------------------------------------------------------------------------
# classify_and_update_plan
# ---------------------------------------------------------------------------


class TestClassifyAndUpdatePlan:
    @pytest.mark.asyncio
    async def test_ignores_unknown_job(self, manager: PlanManager, job_state: dict[str, TrailJobState]) -> None:
        sidecar = AsyncMock()
        result = await manager.classify_and_update_plan(
            "unknown",
            sidecar,
            [],
            agent_msg="hi",
            tool_count=0,
            files_written=[],
            duration_ms=100,
            start_sha=None,
            end_sha=None,
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_successful_classification(self, manager: PlanManager, job_state: dict[str, TrailJobState]) -> None:
        steps = [
            PlanStep(plan_step_id="ps-1", label="Setup", status="active", order=0),
            PlanStep(plan_step_id="ps-2", label="Implement", status="pending", order=1),
        ]
        state = _state(plan_steps=steps, active_idx=0, plan_established=True)
        job_state["j1"] = state

        sidecar = AsyncMock()
        sidecar.complete.return_value = json.dumps(
            {
                "assign_to": 1,
                "summary": "Set up environment",
                "status": "done",
                "updated_label": None,
            }
        )

        result = await manager.classify_and_update_plan(
            "j1",
            sidecar,
            steps,
            agent_msg="Installed deps",
            tool_count=2,
            files_written=["req.txt"],
            duration_ms=500,
            start_sha="abc",
            end_sha="def",
        )
        assert result == "ps-1"
        assert steps[0].status == "done"
        assert steps[0].summary == "Set up environment"
        assert steps[0].tool_count == 2
        assert steps[0].files_written == ["req.txt"]
        assert steps[0].start_sha == "abc"
        assert steps[0].end_sha == "def"

    @pytest.mark.asyncio
    async def test_classification_failure_tolerant(
        self, manager: PlanManager, job_state: dict[str, TrailJobState]
    ) -> None:
        steps = [PlanStep(plan_step_id="ps-1", label="A", status="active", order=0)]
        state = _state(plan_steps=steps, active_idx=0)
        job_state["j1"] = state

        sidecar = AsyncMock()
        sidecar.complete.side_effect = OSError("fail")

        result = await manager.classify_and_update_plan(
            "j1",
            sidecar,
            steps,
            agent_msg="hi",
            tool_count=1,
            files_written=[],
            duration_ms=100,
            start_sha=None,
            end_sha=None,
        )
        assert result == "ps-1"
        assert state.sidecar_consecutive_failures == 1

    @pytest.mark.asyncio
    async def test_reassignment_emits_event(
        self, manager: PlanManager, job_state: dict[str, TrailJobState], event_bus: EventBus
    ) -> None:
        steps = [
            PlanStep(plan_step_id="ps-1", label="A", status="active", order=0),
            PlanStep(plan_step_id="ps-2", label="B", status="pending", order=1),
        ]
        state = _state(plan_steps=steps, active_idx=0)
        job_state["j1"] = state

        sidecar = AsyncMock()
        sidecar.complete.return_value = json.dumps(
            {
                "assign_to": 2,
                "summary": "Jumped ahead",
                "status": "active",
            }
        )

        events: list[DomainEvent] = []

        async def _handler(e: DomainEvent) -> None:
            if e.kind == DomainEventKind.step_entries_reassigned:
                events.append(e)

        event_bus.subscribe(_handler)

        await manager.classify_and_update_plan(
            "j1",
            sidecar,
            steps,
            agent_msg="Working on B now",
            tool_count=1,
            files_written=[],
            duration_ms=100,
            start_sha=None,
            end_sha=None,
            turn_id="t1",
        )
        assert len(events) == 1
        assert events[0].payload["old_step_id"] == "ps-1"
        assert events[0].payload["new_step_id"] == "ps-2"


# ---------------------------------------------------------------------------
# feed_native_plan
# ---------------------------------------------------------------------------


class TestFeedNativePlan:
    @pytest.mark.asyncio
    async def test_ignores_unknown_job(self, manager: PlanManager, job_state: dict[str, TrailJobState]) -> None:
        await manager.feed_native_plan("unknown", [])

    @pytest.mark.asyncio
    async def test_creates_plan_from_native(
        self, manager: PlanManager, job_state: dict[str, TrailJobState], event_bus: EventBus
    ) -> None:
        state = _state()
        job_state["j1"] = state

        events: list[DomainEvent] = []

        async def _handler(e: DomainEvent) -> None:
            if e.kind == DomainEventKind.plan_step_updated:
                events.append(e)

        event_bus.subscribe(_handler)

        items = [
            {"id": "1", "title": "First task", "status": "in-progress"},
            {"id": "2", "title": "Second task", "status": "not-started"},
        ]
        await manager.feed_native_plan("j1", items)

        assert state.native_plan_active is True
        assert len(state.plan_steps) == 2
        assert state.plan_steps[0].label == "First task"
        assert state.plan_steps[0].status == "active"
        assert state.plan_steps[1].status == "pending"
        assert len(events) >= 2
