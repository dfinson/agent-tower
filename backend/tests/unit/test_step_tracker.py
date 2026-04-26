"""Tests for backend.services.step_tracker step boundary detection."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from backend.models.events import DomainEvent, DomainEventKind
from backend.services.step_tracker import StepTracker, _extract_file_path


def _make_event(
    job_id: str = "job-1",
    role: str = "agent",
    content: str = "hello",
    turn_id: str = "turn-1",
    **extra: str,
) -> DomainEvent:
    payload = {"role": role, "content": content, "turn_id": turn_id, **extra}
    return DomainEvent(
        event_id=DomainEvent.make_event_id(),
        job_id=job_id,
        timestamp=datetime.now(UTC),
        kind=DomainEventKind.transcript_updated,
        payload=payload,
    )


@pytest.fixture()
def event_bus() -> AsyncMock:
    return AsyncMock()


@pytest.fixture()
def tracker(event_bus: AsyncMock) -> StepTracker:
    return StepTracker(event_bus=event_bus, git_service=None)


class TestExtractFilePath:
    """Tests for the _extract_file_path helper."""

    def test_json_file_path(self) -> None:
        assert _extract_file_path("read_file", '{"filePath": "/src/main.py"}') == "/src/main.py"

    def test_json_path_key(self) -> None:
        assert _extract_file_path("read_file", '{"path": "/src/other.py"}') == "/src/other.py"

    def test_empty_args(self) -> None:
        assert _extract_file_path("read_file", "") is None

    def test_non_json_args(self) -> None:
        assert _extract_file_path("read_file", "not json at all") is None

    def test_invalid_json(self) -> None:
        assert _extract_file_path("read_file", "{bad json") is None


class TestStepLifecycle:
    """Tests for step open/close lifecycle via transcript events."""

    @pytest.mark.asyncio
    async def test_first_event_opens_step(self, tracker: StepTracker, event_bus: AsyncMock) -> None:
        event = _make_event(role="agent", turn_id="turn-1")
        await tracker.on_transcript_event("job-1", event)

        assert tracker.current_step("job-1") is not None
        assert tracker.current_step("job-1").step_number == 1
        # Should have published step_started
        event_bus.publish.assert_called_once()
        published = event_bus.publish.call_args[0][0]
        assert published.kind == DomainEventKind.step_started

    @pytest.mark.asyncio
    async def test_turn_change_creates_new_step(self, tracker: StepTracker, event_bus: AsyncMock) -> None:
        await tracker.on_transcript_event("job-1", _make_event(turn_id="turn-1"))
        await tracker.on_transcript_event("job-1", _make_event(turn_id="turn-2"))

        current = tracker.current_step("job-1")
        assert current is not None
        assert current.step_number == 2
        assert current.turn_id == "turn-2"

    @pytest.mark.asyncio
    async def test_same_turn_no_new_step(self, tracker: StepTracker, event_bus: AsyncMock) -> None:
        await tracker.on_transcript_event("job-1", _make_event(turn_id="turn-1"))
        await tracker.on_transcript_event("job-1", _make_event(turn_id="turn-1", content="more"))

        current = tracker.current_step("job-1")
        assert current.step_number == 1

    @pytest.mark.asyncio
    async def test_operator_message_always_new_step(self, tracker: StepTracker, event_bus: AsyncMock) -> None:
        await tracker.on_transcript_event("job-1", _make_event(turn_id="turn-1"))
        # Operator with same turn_id still creates new step
        await tracker.on_transcript_event(
            "job-1", _make_event(role="operator", turn_id="turn-1", content="do something")
        )

        current = tracker.current_step("job-1")
        assert current.step_number == 2
        assert current.intent == "do something"

    @pytest.mark.asyncio
    async def test_job_terminal_closes_step(self, tracker: StepTracker, event_bus: AsyncMock) -> None:
        await tracker.on_transcript_event("job-1", _make_event(turn_id="turn-1"))
        await tracker.on_job_terminal("job-1", "completed")

        assert tracker.current_step("job-1") is None
        # Should have published step_completed
        calls = event_bus.publish.call_args_list
        completed_events = [c for c in calls if c[0][0].kind == DomainEventKind.step_completed]
        assert len(completed_events) == 1
        assert completed_events[0][0][0].payload["status"] == "completed"

    @pytest.mark.asyncio
    async def test_job_terminal_idempotent(self, tracker: StepTracker, event_bus: AsyncMock) -> None:
        await tracker.on_transcript_event("job-1", _make_event(turn_id="turn-1"))
        await tracker.on_job_terminal("job-1", "completed")
        # Second call should be a no-op
        count_before = event_bus.publish.call_count
        await tracker.on_job_terminal("job-1", "completed")
        assert event_bus.publish.call_count == count_before


class TestToolTracking:
    """Tests for tool call tracking within steps."""

    @pytest.mark.asyncio
    async def test_tool_call_increments_count(self, tracker: StepTracker, event_bus: AsyncMock) -> None:
        await tracker.on_transcript_event("job-1", _make_event(turn_id="turn-1"))
        await tracker.on_transcript_event(
            "job-1",
            _make_event(
                role="tool_call",
                turn_id="turn-1",
                tool_name="read_file",
                tool_args='{"filePath": "/src/app.py"}',
            ),
        )
        current = tracker.current_step("job-1")
        assert current.tool_count == 1
        assert "read_file" in current.tool_names

    @pytest.mark.asyncio
    async def test_file_read_tracked(self, tracker: StepTracker, event_bus: AsyncMock) -> None:
        await tracker.on_transcript_event("job-1", _make_event(turn_id="turn-1"))
        await tracker.on_transcript_event(
            "job-1",
            _make_event(
                role="tool_call",
                turn_id="turn-1",
                tool_name="read_file",
                tool_args='{"filePath": "src/main.py"}',
            ),
        )
        current = tracker.current_step("job-1")
        assert "src/main.py" in current.files_read

    @pytest.mark.asyncio
    async def test_file_write_tracked(self, tracker: StepTracker, event_bus: AsyncMock) -> None:
        await tracker.on_transcript_event("job-1", _make_event(turn_id="turn-1"))
        await tracker.on_transcript_event(
            "job-1",
            _make_event(
                role="tool_call",
                turn_id="turn-1",
                tool_name="replace_string_in_file",
                tool_args='{"filePath": "src/main.py"}',
            ),
        )
        current = tracker.current_step("job-1")
        assert "src/main.py" in current.files_written

    @pytest.mark.asyncio
    async def test_worktree_prefix_stripped(self, tracker: StepTracker, event_bus: AsyncMock) -> None:
        tracker.register_worktree("job-1", "/workspaces/project")
        await tracker.on_transcript_event("job-1", _make_event(turn_id="turn-1"))
        await tracker.on_transcript_event(
            "job-1",
            _make_event(
                role="tool_call",
                turn_id="turn-1",
                tool_name="read_file",
                tool_args='{"filePath": "/workspaces/project/src/main.py"}',
            ),
        )
        current = tracker.current_step("job-1")
        assert "src/main.py" in current.files_read


class TestAgentDelta:
    """Tests for agent_delta event handling."""

    @pytest.mark.asyncio
    async def test_agent_delta_skipped(self, tracker: StepTracker, event_bus: AsyncMock) -> None:
        """agent_delta events should not open a step."""
        event = _make_event(role="agent_delta", turn_id="turn-1")
        await tracker.on_transcript_event("job-1", event)
        assert tracker.current_step("job-1") is None


class TestReportIntent:
    """Tests for report_intent tool handling."""

    @pytest.mark.asyncio
    async def test_report_intent_updates_step(self, tracker: StepTracker, event_bus: AsyncMock) -> None:
        await tracker.on_transcript_event("job-1", _make_event(turn_id="turn-1"))
        await tracker.on_transcript_event(
            "job-1",
            _make_event(
                role="tool_call",
                turn_id="turn-1",
                tool_name="report_intent",
                tool_args='{"intent": "Refactoring auth module"}',
            ),
        )
        current = tracker.current_step("job-1")
        assert current.intent == "Refactoring auth module"


class TestCleanup:
    """Tests for cleanup method."""

    @pytest.mark.asyncio
    async def test_cleanup_removes_all_state(self, tracker: StepTracker, event_bus: AsyncMock) -> None:
        tracker.register_worktree("job-1", "/tmp/wt")
        await tracker.on_transcript_event("job-1", _make_event(turn_id="turn-1"))

        tracker.cleanup("job-1")
        assert tracker.current_step("job-1") is None
        assert "job-1" not in tracker._counters
        assert "job-1" not in tracker._worktree_paths
        assert "job-1" not in tracker._transcript_buffers

    def test_cleanup_nonexistent_job(self, tracker: StepTracker) -> None:
        # Should not raise
        tracker.cleanup("nonexistent")
