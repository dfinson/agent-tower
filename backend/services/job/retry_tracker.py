"""Deterministic retry detection for tool calls.

A tool call is a retry if and only if a prior call with the same
(tool_name, tool_target) exists in this job and that prior call failed.
No windows, no thresholds — just a factual relationship.
"""

from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RetryResult:
    """Result of checking whether a tool call is a retry."""

    is_retry: bool
    prior_failure_span_id: int | None


class RetryTracker:
    """Tracks tool call outcomes per (tool_name, tool_target) pair."""

    def __init__(
        self,
        *,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        backoff_factor: float = 2.0,
        jitter: bool = True,
        jitter_factor: float = 0.25,
    ) -> None:
        # Maps (tool_name, tool_target) → most-recent failure span_id (or None)
        self._last_failure: dict[tuple[str, str], int | None] = defaultdict(lambda: None)
        # Maps (tool_name, tool_target) → consecutive failure count
        self._failure_count: dict[tuple[str, str], int] = defaultdict(int)
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.backoff_factor = backoff_factor
        self.jitter = jitter
        self.jitter_factor = jitter_factor

    def record(
        self,
        tool_name: str,
        tool_target: str,
        span_id: int,
        success: bool,
    ) -> RetryResult:
        """Record a tool call and check if it retries a prior failure.

        Returns a RetryResult indicating whether this is a retry and,
        if so, which prior span it retries.
        """
        key = (tool_name, tool_target)
        prior_failure_id = self._last_failure[key]

        if not success:
            self._last_failure[key] = span_id
            self._failure_count[key] += 1
        else:
            self._failure_count[key] = 0

        return RetryResult(
            is_retry=prior_failure_id is not None,
            prior_failure_span_id=prior_failure_id,
        )

    def reset(self) -> None:
        """Clear all tracked history (e.g. at start of a new job)."""
        self._last_failure.clear()
        self._failure_count.clear()

    def calculate_delay(self, tool_name: str, tool_target: str) -> float:
        """Calculate raw exponential backoff delay without jitter."""
        key = (tool_name, tool_target)
        failures = self._failure_count[key]
        if failures == 0:
            return 0.0
        return min(self.base_delay * (self.backoff_factor ** (failures - 1)), self.max_delay)

    def calculate_delay_with_jitter(self, attempt: int) -> float:
        """Calculate exponential backoff delay with uniform random jitter.

        Args:
            attempt: The 1-based attempt number (attempt 1 = first retry).

        Returns:
            Delay in seconds with jitter in [0, jitter_factor * delay] added.
        """
        if attempt <= 0:
            return 0.0
        delay = min(self.base_delay * (self.backoff_factor ** (attempt - 1)), self.max_delay)
        if delay > 0 and self.jitter:
            delay += random.uniform(0, self.jitter_factor * delay)  # noqa: S311
        return delay
