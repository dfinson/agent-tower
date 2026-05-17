"""Tests for RetryTracker jitter functionality."""

from __future__ import annotations

from unittest.mock import patch

from backend.services.job.retry_tracker import RetryTracker


class TestCalculateDelayWithJitter:
    """Tests for calculate_delay_with_jitter(attempt)."""

    def test_zero_jitter_factor_returns_raw_delay(self) -> None:
        """With jitter_factor=0, delay equals the raw exponential backoff."""
        tracker = RetryTracker(base_delay=1.0, backoff_factor=2.0, jitter_factor=0.0)
        assert tracker.calculate_delay_with_jitter(1) == 1.0
        assert tracker.calculate_delay_with_jitter(2) == 2.0
        assert tracker.calculate_delay_with_jitter(3) == 4.0

    def test_jitter_disabled_returns_raw_delay(self) -> None:
        """With jitter=False, jitter_factor is ignored."""
        tracker = RetryTracker(base_delay=1.0, backoff_factor=2.0, jitter=False, jitter_factor=0.5)
        assert tracker.calculate_delay_with_jitter(1) == 1.0
        assert tracker.calculate_delay_with_jitter(2) == 2.0

    def test_normal_jitter_within_range(self) -> None:
        """Jittered delay falls in [base_delay, base_delay * (1 + jitter_factor)]."""
        tracker = RetryTracker(base_delay=2.0, backoff_factor=2.0, jitter_factor=0.25)
        for _ in range(100):
            delay = tracker.calculate_delay_with_jitter(1)
            assert 2.0 <= delay <= 2.0 * 1.25

    def test_jitter_scales_with_factor(self) -> None:
        """Larger jitter_factor produces a wider jitter band."""
        tracker = RetryTracker(base_delay=4.0, backoff_factor=1.0, jitter_factor=0.5)
        for _ in range(100):
            delay = tracker.calculate_delay_with_jitter(1)
            assert 4.0 <= delay <= 4.0 * 1.5

    def test_attempt_zero_returns_zero(self) -> None:
        """Attempt 0 (no retry needed) returns 0 delay."""
        tracker = RetryTracker()
        assert tracker.calculate_delay_with_jitter(0) == 0.0

    def test_negative_attempt_returns_zero(self) -> None:
        """Negative attempt values return 0 delay."""
        tracker = RetryTracker()
        assert tracker.calculate_delay_with_jitter(-1) == 0.0

    def test_max_delay_caps_before_jitter(self) -> None:
        """Delay is capped at max_delay before jitter is applied."""
        tracker = RetryTracker(
            base_delay=1.0, max_delay=10.0, backoff_factor=2.0, jitter_factor=0.25,
        )
        # attempt 100 would far exceed max_delay without cap
        for _ in range(50):
            delay = tracker.calculate_delay_with_jitter(100)
            assert 10.0 <= delay <= 10.0 * 1.25

    def test_default_jitter_factor_is_025(self) -> None:
        """Default jitter_factor is 0.25."""
        tracker = RetryTracker()
        assert tracker.jitter_factor == 0.25

    @patch("backend.services.job.retry_tracker.random.uniform", return_value=0.0)
    def test_jitter_at_lower_bound(self, _mock_uniform: object) -> None:
        """When random returns 0, delay equals raw backoff."""
        tracker = RetryTracker(base_delay=5.0, backoff_factor=2.0, jitter_factor=0.25)
        assert tracker.calculate_delay_with_jitter(1) == 5.0

    @patch("backend.services.job.retry_tracker.random.uniform")
    def test_jitter_at_upper_bound(self, mock_uniform: object) -> None:
        """When random returns max jitter, delay equals base * (1 + jitter_factor)."""
        # For base_delay=5, jitter_factor=0.25: uniform(0, 1.25) should return 1.25
        mock_uniform.return_value = 1.25
        tracker = RetryTracker(base_delay=5.0, backoff_factor=2.0, jitter_factor=0.25)
        assert tracker.calculate_delay_with_jitter(1) == 6.25
