"""Tests for latency_attribution — latency helpers and classification."""

from __future__ import annotations

from backend.services.latency_attribution import (
    _classify_turnless_span_activity,
    _compute_wall_clock,
    _percentile,
)

# ---------------------------------------------------------------------------
# _percentile
# ---------------------------------------------------------------------------


class TestPercentile:
    def test_empty(self) -> None:
        assert _percentile([], 0.5) == 0

    def test_single(self) -> None:
        assert _percentile([42], 0.5) == 42

    def test_median(self) -> None:
        assert _percentile([1, 2, 3, 4, 5], 0.5) == 3

    def test_p90(self) -> None:
        assert _percentile(list(range(1, 101)), 0.9) == 91

    def test_p0(self) -> None:
        assert _percentile([10, 20, 30], 0.0) == 10

    def test_p100_clamps(self) -> None:
        assert _percentile([10, 20, 30], 1.0) == 30


# ---------------------------------------------------------------------------
# _compute_wall_clock
# ---------------------------------------------------------------------------


class TestComputeWallClock:
    def test_empty(self) -> None:
        assert _compute_wall_clock([]) == 0

    def test_single_interval(self) -> None:
        assert _compute_wall_clock([(0.0, 100.0)]) == 100

    def test_non_overlapping(self) -> None:
        intervals = [(0.0, 50.0), (100.0, 200.0)]
        assert _compute_wall_clock(intervals) == 150

    def test_overlapping_merged(self) -> None:
        intervals = [(0.0, 100.0), (50.0, 150.0)]
        assert _compute_wall_clock(intervals) == 150

    def test_fully_contained(self) -> None:
        intervals = [(0.0, 200.0), (50.0, 100.0)]
        assert _compute_wall_clock(intervals) == 200

    def test_unsorted_input(self) -> None:
        intervals = [(100.0, 200.0), (0.0, 50.0)]
        assert _compute_wall_clock(intervals) == 150

    def test_adjacent_intervals(self) -> None:
        intervals = [(0.0, 50.0), (50.0, 100.0)]
        assert _compute_wall_clock(intervals) == 100


# ---------------------------------------------------------------------------
# _classify_turnless_span_activity
# ---------------------------------------------------------------------------


class TestClassifyTurnlessSpanActivity:
    def test_llm_span(self) -> None:
        assert _classify_turnless_span_activity({"span_type": "llm"}) == "reasoning"

    def test_approval_span(self) -> None:
        assert _classify_turnless_span_activity({"span_type": "approval"}) == "overhead"

    def test_tool_file_write(self) -> None:
        # Write tool classified by classify_tool; 'Write' maps to file_write
        assert _classify_turnless_span_activity({"span_type": "tool", "name": "Write"}) == "implementation"

    def test_tool_file_read(self) -> None:
        assert _classify_turnless_span_activity({"span_type": "tool", "name": "Read"}) == "investigation"

    def test_tool_shell(self) -> None:
        assert _classify_turnless_span_activity({"span_type": "tool", "name": "run_terminal_cmd"}) == "investigation"

    def test_unknown_span_type(self) -> None:
        assert _classify_turnless_span_activity({"span_type": "other"}) == "reasoning"

    def test_empty_span(self) -> None:
        assert _classify_turnless_span_activity({}) == "reasoning"
