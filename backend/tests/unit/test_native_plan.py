"""Tests for native plan capture from manage_todo_list / TodoWrite tool calls."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.models.events import DomainEvent, DomainEventKind
from backend.services.progress_tracking_service import ProgressTrackingService

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def event_bus() -> AsyncMock:
    return AsyncMock()


@pytest.fixture()
def sister_sessions() -> MagicMock:
    return MagicMock()


@pytest.fixture()
def service(sister_sessions: MagicMock, event_bus: AsyncMock) -> ProgressTrackingService:
    return ProgressTrackingService(sister_sessions=sister_sessions, event_bus=event_bus)


# ---------------------------------------------------------------------------
# feed_native_plan
# ---------------------------------------------------------------------------


def _step_events(event_bus: AsyncMock) -> list[DomainEvent]:
    """Extract all plan_step_updated events from mock publish calls."""
    return [
        call.args[0]
        for call in event_bus.publish.call_args_list
        if call.args[0].kind == DomainEventKind.plan_step_updated
    ]


class TestFeedNativePlan:
    """Tests for ProgressTrackingService.feed_native_plan."""

    @pytest.mark.asyncio()
    async def test_copilot_manage_todo_list(self, service: ProgressTrackingService, event_bus: AsyncMock) -> None:
        """Copilot-style todoList items are correctly mapped to plan steps."""
        await service.start_tracking("job-1")
        items = [
            {"id": 1, "title": "Explore codebase", "status": "completed"},
            {"id": 2, "title": "Implement feature", "status": "in-progress"},
            {"id": 3, "title": "Write tests", "status": "not-started"},
        ]
        await service.feed_native_plan("job-1", items)

        step_evts = _step_events(event_bus)
        assert len(step_evts) == 3
        assert all(e.job_id == "job-1" for e in step_evts)
        payloads = [e.payload for e in step_evts]
        assert payloads[0]["label"] == "Explore codebase"
        assert payloads[0]["status"] == "done"
        assert payloads[1]["label"] == "Implement feature"
        assert payloads[1]["status"] == "active"
        assert payloads[2]["label"] == "Write tests"
        assert payloads[2]["status"] == "pending"

    @pytest.mark.asyncio()
    async def test_claude_todo_write(self, service: ProgressTrackingService, event_bus: AsyncMock) -> None:
        """Claude-style todos with 'content' field are correctly mapped."""
        await service.start_tracking("job-1")
        items = [
            {"id": "1", "content": "Read source files", "status": "completed"},
            {"id": "2", "content": "Fix the bug", "status": "in_progress"},
            {"id": "3", "content": "Run tests", "status": "pending"},
        ]
        await service.feed_native_plan("job-1", items)

        step_evts = _step_events(event_bus)
        assert len(step_evts) == 3
        assert step_evts[0].payload["label"] == "Read source files"
        assert step_evts[0].payload["status"] == "done"
        assert step_evts[1].payload["label"] == "Fix the bug"
        assert step_evts[1].payload["status"] == "active"
        assert step_evts[2].payload["label"] == "Run tests"
        assert step_evts[2].payload["status"] == "pending"

    @pytest.mark.asyncio()
    async def test_duplicate_plan_not_republished(self, service: ProgressTrackingService, event_bus: AsyncMock) -> None:
        """Feeding the same plan twice still emits events (steps are individually updated)."""
        await service.start_tracking("job-1")
        items = [
            {"id": 1, "title": "Task A", "status": "in-progress"},
            {"id": 2, "title": "Task B", "status": "not-started"},
        ]
        await service.feed_native_plan("job-1", items)
        first_count = event_bus.publish.call_count

        # Feed the same items again — steps are re-emitted (statuses unchanged)
        await service.feed_native_plan("job-1", items)
        assert event_bus.publish.call_count >= first_count

    @pytest.mark.asyncio()
    async def test_updated_plan_publishes_new_events(
        self,
        service: ProgressTrackingService,
        event_bus: AsyncMock,
    ) -> None:
        """When plan steps change, new step events are published."""
        await service.start_tracking("job-1")
        items_v1 = [
            {"id": 1, "title": "Task A", "status": "in-progress"},
            {"id": 2, "title": "Task B", "status": "not-started"},
        ]
        await service.feed_native_plan("job-1", items_v1)
        first_count = event_bus.publish.call_count

        items_v2 = [
            {"id": 1, "title": "Task A", "status": "completed"},
            {"id": 2, "title": "Task B", "status": "in-progress"},
        ]
        await service.feed_native_plan("job-1", items_v2)
        assert event_bus.publish.call_count > first_count

    @pytest.mark.asyncio()
    async def test_empty_items_ignored(self, service: ProgressTrackingService, event_bus: AsyncMock) -> None:
        """Empty items list does not publish an event."""
        await service.start_tracking("job-1")
        await service.feed_native_plan("job-1", [])
        event_bus.publish.assert_not_called()

    @pytest.mark.asyncio()
    async def test_items_without_labels_skipped(self, service: ProgressTrackingService, event_bus: AsyncMock) -> None:
        """Items missing both title and content are filtered out."""
        await service.start_tracking("job-1")
        items = [
            {"id": 1, "status": "in-progress"},  # no title/content
            {"id": 2, "title": "Valid task", "status": "not-started"},
        ]
        await service.feed_native_plan("job-1", items)

        step_evts = _step_events(event_bus)
        assert len(step_evts) == 1
        assert step_evts[0].payload["label"] == "Valid task"

    @pytest.mark.asyncio()
    async def test_unknown_status_maps_to_pending(self, service: ProgressTrackingService, event_bus: AsyncMock) -> None:
        """Unknown status values default to 'pending'."""
        await service.start_tracking("job-1")
        items = [{"id": 1, "title": "Some task", "status": "weird_status"}]
        await service.feed_native_plan("job-1", items)

        step_evts = _step_events(event_bus)
        assert step_evts[0].payload["status"] == "pending"

    @pytest.mark.asyncio()
    async def test_native_plan_suppresses_llm_extraction(self, service: ProgressTrackingService) -> None:
        """Once native plan is fed, the job is flagged to suppress LLM extraction."""
        await service.start_tracking("job-1")
        items = [{"id": 1, "title": "Task", "status": "in-progress"}]
        await service.feed_native_plan("job-1", items)
        assert "job-1" in service._native_plan_active

    @pytest.mark.asyncio()
    async def test_cleanup_clears_native_flag(self, service: ProgressTrackingService) -> None:
        """Cleanup removes native plan flag."""
        await service.start_tracking("job-1")
        items = [{"id": 1, "title": "Task", "status": "in-progress"}]
        await service.feed_native_plan("job-1", items)
        assert "job-1" in service._native_plan_active

        service.cleanup("job-1")
        assert "job-1" not in service._native_plan_active


# ---------------------------------------------------------------------------
# RuntimeService._ingest_native_plan
# ---------------------------------------------------------------------------


class TestIngestNativePlan:
    """Tests for RuntimeService._ingest_native_plan parsing logic."""

    @pytest.mark.asyncio()
    async def test_copilot_payload(self, service: ProgressTrackingService, event_bus: AsyncMock) -> None:
        """Copilot-style tool_args with todoList are parsed correctly."""
        await service.start_tracking("job-1")

        # Simulate what RuntimeService._ingest_native_plan does
        payload = {
            "tool_name": "manage_todo_list",
            "tool_args": json.dumps(
                {
                    "todoList": [
                        {"id": 1, "title": "Setup project", "status": "completed"},
                        {"id": 2, "title": "Write code", "status": "in-progress"},
                    ]
                }
            ),
        }
        args = json.loads(payload["tool_args"])
        items = args.get("todoList") or args.get("todos") or []
        await service.feed_native_plan("job-1", items)

        step_evts = _step_events(event_bus)
        assert step_evts[0].payload["label"] == "Setup project"
        assert step_evts[0].payload["status"] == "done"
        assert step_evts[1].payload["label"] == "Write code"
        assert step_evts[1].payload["status"] == "active"

    @pytest.mark.asyncio()
    async def test_claude_payload(self, service: ProgressTrackingService, event_bus: AsyncMock) -> None:
        """Claude-style tool_args with todos are parsed correctly."""
        await service.start_tracking("job-1")

        payload = {
            "tool_name": "TodoWrite",
            "tool_args": json.dumps(
                {
                    "todos": [
                        {"id": "1", "content": "Investigate issue", "status": "completed"},
                        {"id": "2", "content": "Apply fix", "status": "in_progress"},
                    ]
                }
            ),
        }
        args = json.loads(payload["tool_args"])
        items = args.get("todoList") or args.get("todos") or []
        await service.feed_native_plan("job-1", items)

        step_evts = _step_events(event_bus)
        assert step_evts[0].payload["label"] == "Investigate issue"
        assert step_evts[0].payload["status"] == "done"
        assert step_evts[1].payload["label"] == "Apply fix"
        assert step_evts[1].payload["status"] == "active"
