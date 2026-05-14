"""Tests for event_processor — event translation and pipeline logic."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.models.domain import SessionEvent, SessionEventKind
from backend.models.events import DomainEvent, DomainEventKind
from backend.services.events.event_bus import EventBus
from backend.services.events.event_processor import EventProcessor


@pytest.fixture
def event_bus() -> EventBus:
    return EventBus()


@pytest.fixture
def processor(event_bus: EventBus) -> EventProcessor:
    return EventProcessor(event_bus)


# ---------------------------------------------------------------------------
# _translate_event
# ---------------------------------------------------------------------------


class TestTranslateEvent:
    def test_log_event(self) -> None:
        ev = SessionEvent(kind=SessionEventKind.log, payload={"message": "hello"})
        result = EventProcessor._translate_event("j1", ev)
        assert result is not None
        assert result.kind == DomainEventKind.log_line_emitted
        assert result.job_id == "j1"

    def test_transcript_event(self) -> None:
        ev = SessionEvent(kind=SessionEventKind.transcript, payload={"role": "agent", "content": "hi"})
        result = EventProcessor._translate_event("j1", ev)
        assert result is not None
        assert result.kind == DomainEventKind.transcript_updated

    def test_approval_request_event(self) -> None:
        ev = SessionEvent(kind=SessionEventKind.approval_request, payload={"action": "rm -rf"})
        result = EventProcessor._translate_event("j1", ev)
        assert result is not None
        assert result.kind == DomainEventKind.approval_requested

    def test_error_event(self) -> None:
        ev = SessionEvent(kind=SessionEventKind.error, payload={"message": "failed"})
        result = EventProcessor._translate_event("j1", ev)
        assert result is not None
        assert result.kind == DomainEventKind.job_failed

    def test_model_downgraded_event(self) -> None:
        ev = SessionEvent(kind=SessionEventKind.model_downgraded, payload={"from": "a", "to": "b"})
        result = EventProcessor._translate_event("j1", ev)
        assert result is not None
        assert result.kind == DomainEventKind.model_downgraded

    def test_unknown_event_returns_none(self) -> None:
        ev = SessionEvent(kind=SessionEventKind.done, payload={})
        result = EventProcessor._translate_event("j1", ev)
        assert result is None

    def test_file_changed_returns_none(self) -> None:
        ev = SessionEvent(kind=SessionEventKind.file_changed, payload={"path": "a.py"})
        result = EventProcessor._translate_event("j1", ev)
        assert result is None


# ---------------------------------------------------------------------------
# process_event
# ---------------------------------------------------------------------------


class TestProcessEvent:
    @pytest.mark.asyncio
    async def test_log_event_published(self, processor: EventProcessor, event_bus: EventBus) -> None:
        received: list[DomainEvent] = []

        async def _handler(e: DomainEvent) -> None:
            if e.kind == DomainEventKind.log_line_emitted:
                received.append(e)

        event_bus.subscribe(_handler)

        ev = SessionEvent(kind=SessionEventKind.log, payload={"message": "test"})
        result = await processor.process_event("j1", ev)
        assert result is not None
        assert len(received) == 1

    @pytest.mark.asyncio
    async def test_file_changed_triggers_diff(self) -> None:
        bus = EventBus()
        diff_svc = AsyncMock()
        proc = EventProcessor(bus, diff_service=diff_svc)

        ev = SessionEvent(kind=SessionEventKind.file_changed, payload={"path": "a.py"})
        result = await proc.process_event("j1", ev, worktree_path="/w", base_ref="main")
        assert result is None
        diff_svc.on_worktree_file_modified.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_tool_call_triggers_diff(self) -> None:
        bus = EventBus()
        diff_svc = AsyncMock()
        proc = EventProcessor(bus, diff_service=diff_svc)

        ev = SessionEvent(
            kind=SessionEventKind.transcript,
            payload={"role": "tool_call", "tool_name": "write_file"},
        )
        result = await proc.process_event("j1", ev, worktree_path="/w", base_ref="main")
        assert result is not None
        diff_svc.on_worktree_file_modified.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_report_intent_skips_diff(self) -> None:
        bus = EventBus()
        diff_svc = AsyncMock()
        proc = EventProcessor(bus, diff_service=diff_svc)

        ev = SessionEvent(
            kind=SessionEventKind.transcript,
            payload={"role": "tool_call", "tool_name": "report_intent"},
        )
        result = await proc.process_event("j1", ev, worktree_path="/w", base_ref="main")
        assert result is not None
        diff_svc.on_worktree_file_modified.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_transcript_gets_synthesized_turn_id(self, processor: EventProcessor) -> None:
        ev = SessionEvent(
            kind=SessionEventKind.transcript,
            payload={"role": "tool_call", "content": "running"},
        )
        result = await processor.process_event("j1", ev)
        assert result is not None
        assert result.payload.get("turn_id") is not None

    @pytest.mark.asyncio
    async def test_turn_id_rotates_on_agent_message(self, processor: EventProcessor) -> None:
        ev1 = SessionEvent(
            kind=SessionEventKind.transcript,
            payload={"role": "tool_call", "content": "running"},
        )
        result1 = await processor.process_event("j1", ev1)
        tid1 = result1.payload["turn_id"]

        # Agent message rotates the turn_id
        ev2 = SessionEvent(
            kind=SessionEventKind.transcript,
            payload={"role": "agent", "content": "done"},
        )
        await processor.process_event("j1", ev2)

        # Next event should have a new turn_id
        ev3 = SessionEvent(
            kind=SessionEventKind.transcript,
            payload={"role": "tool_call", "content": "another"},
        )
        result3 = await processor.process_event("j1", ev3)
        tid3 = result3.payload["turn_id"]
        assert tid3 != tid1


# ---------------------------------------------------------------------------
# cleanup
# ---------------------------------------------------------------------------


class TestCleanup:
    def test_cleanup_clears_turn_ids(self, processor: EventProcessor) -> None:
        processor._turn_ids["j1"] = "some-id"
        processor.cleanup("j1")
        assert "j1" not in processor._turn_ids

    def test_cleanup_with_step_tracker(self) -> None:
        bus = EventBus()
        tracker = MagicMock()
        proc = EventProcessor(bus, step_tracker=tracker)
        proc.cleanup("j1")
        tracker.cleanup.assert_called_once_with("j1")

    def test_cleanup_with_diff_service(self) -> None:
        bus = EventBus()
        diff_svc = MagicMock()
        proc = EventProcessor(bus, diff_service=diff_svc)
        proc.cleanup("j1")
        diff_svc.cleanup.assert_called_once_with("j1")


# ---------------------------------------------------------------------------
# on_job_terminal
# ---------------------------------------------------------------------------


class TestOnJobTerminal:
    @pytest.mark.asyncio
    async def test_notifies_step_tracker(self) -> None:
        bus = EventBus()
        tracker = AsyncMock()
        proc = EventProcessor(bus, step_tracker=tracker)
        await proc.on_job_terminal("j1", "completed")
        tracker.on_job_terminal.assert_awaited_once_with("j1", "completed")

    @pytest.mark.asyncio
    async def test_no_tracker_no_error(self) -> None:
        bus = EventBus()
        proc = EventProcessor(bus)
        # Should not raise
        await proc.on_job_terminal("j1", "completed")


# ---------------------------------------------------------------------------
# register_worktree
# ---------------------------------------------------------------------------


class TestRegisterWorktree:
    def test_with_step_tracker(self) -> None:
        bus = EventBus()
        tracker = MagicMock()
        proc = EventProcessor(bus, step_tracker=tracker)
        proc.register_worktree("j1", "/tmp/wt")
        tracker.register_worktree.assert_called_once_with("j1", "/tmp/wt")

    def test_without_step_tracker(self) -> None:
        bus = EventBus()
        proc = EventProcessor(bus)
        # Should not raise
        proc.register_worktree("j1", "/tmp/wt")
