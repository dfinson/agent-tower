"""Tests for snapshot_helpers — build functions for snapshot assembly."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from backend.services.snapshot_helpers import (
    _apply_reassignments,
    _build_logs,
    _build_timeline,
    _build_turn_summaries,
)


def _event(
    job_id: str = "j1",
    timestamp: str = "2025-01-01T00:00:00Z",
    **payload: Any,
) -> SimpleNamespace:
    return SimpleNamespace(job_id=job_id, timestamp=timestamp, payload=payload)


# ---------------------------------------------------------------------------
# _build_logs
# ---------------------------------------------------------------------------


class TestBuildLogs:
    def test_empty(self) -> None:
        assert _build_logs([]) == []

    def test_extracts_fields(self) -> None:
        ev = _event(
            seq=1,
            timestamp="2025-01-01T00:00:01Z",
            level="error",
            message="something broke",
            context={"key": "val"},
        )
        logs = _build_logs([ev])
        assert len(logs) == 1
        assert logs[0].seq == 1
        assert logs[0].level == "error"
        assert logs[0].message == "something broke"
        assert logs[0].context == {"key": "val"}

    def test_defaults(self) -> None:
        ev = _event()
        logs = _build_logs([ev])
        assert logs[0].seq == 0
        assert logs[0].level == "info"
        assert logs[0].message == ""


# ---------------------------------------------------------------------------
# _build_timeline
# ---------------------------------------------------------------------------


class TestBuildTimeline:
    def test_empty(self) -> None:
        assert _build_timeline([]) == []

    def test_appends(self) -> None:
        events = [
            _event(headline="Step 1", headline_past="Did step 1", summary="s1"),
            _event(headline="Step 2", headline_past="Did step 2", summary="s2"),
        ]
        timeline = _build_timeline(events)
        assert len(timeline) == 2
        assert timeline[0].headline == "Step 1"
        assert timeline[1].headline == "Step 2"

    def test_replaces(self) -> None:
        events = [
            _event(headline="Step 1", headline_past="", summary=""),
            _event(headline="Step 2", headline_past="", summary=""),
            _event(headline="Step 3 (replaces 2)", headline_past="", summary="", replaces_count=1),
        ]
        timeline = _build_timeline(events)
        assert len(timeline) == 2
        assert timeline[0].headline == "Step 1"
        assert timeline[1].headline == "Step 3 (replaces 2)"

    def test_replaces_all(self) -> None:
        events = [
            _event(headline="A", headline_past="", summary=""),
            _event(headline="B", headline_past="", summary=""),
            _event(headline="C", headline_past="", summary="", replaces_count=99),
        ]
        timeline = _build_timeline(events)
        assert len(timeline) == 1
        assert timeline[0].headline == "C"


# ---------------------------------------------------------------------------
# _build_turn_summaries
# ---------------------------------------------------------------------------


class TestBuildTurnSummaries:
    def test_empty(self) -> None:
        assert _build_turn_summaries([], "j1", deduplicate=False) == []

    def test_basic(self) -> None:
        events = [
            _event(
                turn_id="t1",
                title="Fixed bug",
                activity_id="a1",
                activity_label="Debugging",
                activity_status="active",
                is_new_activity=True,
            ),
        ]
        result = _build_turn_summaries(events, "j1", deduplicate=False)
        assert len(result) == 1
        assert result[0].title == "Fixed bug"
        assert result[0].is_new_activity is True

    def test_deduplicate_keeps_latest(self) -> None:
        events = [
            _event(
                turn_id="t1",
                title="First",
                activity_id="a1",
                activity_label="L",
                activity_status="active",
                is_new_activity=True,
            ),
            _event(
                turn_id="t1",
                title="Updated",
                activity_id="a1",
                activity_label="L",
                activity_status="active",
                is_new_activity=False,
            ),
        ]
        result = _build_turn_summaries(events, "j1", deduplicate=True)
        assert len(result) == 1
        assert result[0].title == "Updated"
        # First event's is_new_activity is preserved
        assert result[0].is_new_activity is True

    def test_deduplicate_replaces_turn(self) -> None:
        events = [
            _event(
                turn_id="t1",
                title="Old",
                activity_id="a1",
                activity_label="L",
                activity_status="active",
                is_new_activity=True,
            ),
            _event(
                turn_id="t2",
                title="Merged",
                activity_id="a1",
                activity_label="L",
                activity_status="active",
                is_new_activity=False,
                replaces_turn_id="t1",
            ),
        ]
        result = _build_turn_summaries(events, "j1", deduplicate=True)
        # t1 is replaced; only t2 remains, but with inherited is_new_activity
        assert len(result) == 1
        assert result[0].turn_id == "t2"
        assert result[0].is_new_activity is True

    def test_skips_empty_title(self) -> None:
        events = [
            _event(
                turn_id="t1",
                title="",
                activity_id="a1",
                activity_label="L",
                activity_status="active",
                is_new_activity=False,
            ),
        ]
        result = _build_turn_summaries(events, "j1", deduplicate=False)
        assert len(result) == 0

    def test_skips_missing_turn_id(self) -> None:
        events = [
            _event(
                title="Orphan",
                activity_id="a1",
                activity_label="L",
                activity_status="active",
                is_new_activity=False,
            ),
        ]
        result = _build_turn_summaries(events, "j1", deduplicate=False)
        assert len(result) == 0


# ---------------------------------------------------------------------------
# _apply_reassignments
# ---------------------------------------------------------------------------


class TestApplyReassignments:
    def test_empty(self) -> None:
        transcript: list[Any] = []
        _apply_reassignments(transcript, [])

    def test_reassigns_step_id(self) -> None:
        from backend.models.api_schemas import TranscriptPayload

        entry = TranscriptPayload(
            job_id="j1",
            seq=1,
            timestamp="2025-01-01T00:00:00Z",
            role="agent",
            content="hi",
            turn_id="t1",
            step_id="old-step",
        )
        reassign_events = [
            _event(turn_id="t1", old_step_id="old-step", new_step_id="new-step"),
        ]
        _apply_reassignments([entry], reassign_events)
        assert entry.step_id == "new-step"

    def test_no_match(self) -> None:
        from backend.models.api_schemas import TranscriptPayload

        entry = TranscriptPayload(
            job_id="j1",
            seq=1,
            timestamp="2025-01-01T00:00:00Z",
            role="agent",
            content="hi",
            turn_id="t2",
            step_id="old-step",
        )
        reassign_events = [
            _event(turn_id="t1", old_step_id="old-step", new_step_id="new-step"),
        ]
        _apply_reassignments([entry], reassign_events)
        assert entry.step_id == "old-step"
