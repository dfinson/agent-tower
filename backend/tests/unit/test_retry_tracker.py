"""Tests for RetryTracker."""

from __future__ import annotations

from backend.services.retry_tracker import RetryTracker


class TestRetryTracker:
    def test_first_call_is_not_retry(self) -> None:
        tracker = RetryTracker()
        result = tracker.record("edit_file", "main.py", span_id=1, success=True)
        assert result.is_retry is False
        assert result.prior_failure_span_id is None

    def test_second_call_after_success_is_not_retry(self) -> None:
        tracker = RetryTracker()
        tracker.record("edit_file", "main.py", span_id=1, success=True)
        result = tracker.record("edit_file", "main.py", span_id=2, success=True)
        assert result.is_retry is False

    def test_call_after_failure_is_retry(self) -> None:
        tracker = RetryTracker()
        tracker.record("edit_file", "main.py", span_id=1, success=False)
        result = tracker.record("edit_file", "main.py", span_id=2, success=True)
        assert result.is_retry is True
        assert result.prior_failure_span_id == 1

    def test_different_targets_are_independent(self) -> None:
        tracker = RetryTracker()
        tracker.record("edit_file", "main.py", span_id=1, success=False)
        result = tracker.record("edit_file", "utils.py", span_id=2, success=True)
        assert result.is_retry is False

    def test_reset_clears_history(self) -> None:
        tracker = RetryTracker()
        tracker.record("edit_file", "main.py", span_id=1, success=False)
        tracker.reset()
        result = tracker.record("edit_file", "main.py", span_id=2, success=True)
        assert result.is_retry is False

    def test_retry_finds_most_recent_failure(self) -> None:
        tracker = RetryTracker()
        tracker.record("run", "test.py", span_id=1, success=False)
        tracker.record("run", "test.py", span_id=2, success=False)
        result = tracker.record("run", "test.py", span_id=3, success=True)
        assert result.is_retry is True
        assert result.prior_failure_span_id == 2  # most recent
