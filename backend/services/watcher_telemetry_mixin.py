"""Mixin providing shared telemetry helpers for session watchers.

Both SessionStateWatcher and ClaudeSessionWatcher accumulate telemetry
counters in memory and flush them atomically with the tail-read offset.
This mixin extracts the identical logic so both watchers inherit it
rather than duplicating it.

Concrete watchers must provide:
  - self._pending_telemetry: dict[str, dict[str, float | int]]
  - self._session_factory: async_sessionmaker
  - self._bg_tasks: set[asyncio.Task]
  - self._watcher_log_prefix: str  (e.g. "session_watcher" or "claude_watcher")
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import async_sessionmaker

log = structlog.get_logger()


class WatcherTelemetryMixin:
    """Shared telemetry accumulation and background-task helpers."""

    # Subclasses must set these (declared here for type-checker visibility)
    _pending_telemetry: dict[str, dict[str, float | int]]
    _session_factory: async_sessionmaker  # type: ignore[type-arg]
    _bg_tasks: set[asyncio.Task]  # type: ignore[type-arg]
    _watcher_log_prefix: str

    def _fire_bg(self, coro: Any, *, name: str) -> asyncio.Task:  # type: ignore[type-arg]
        """Create a background task tracked for clean shutdown."""
        task = asyncio.create_task(coro, name=name)
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)
        return task

    def _accumulate_telemetry(self, job_id: str, counters: dict[str, Any]) -> None:
        """Accumulate telemetry deltas in memory for atomic flush with offset."""
        pending = self._pending_telemetry.setdefault(job_id, {})
        for key, value in counters.items():
            pending[key] = pending.get(key, 0) + value  # type: ignore[operator]

    def _schedule_model_update(self, job_id: str, model: str) -> None:
        """Schedule a model update on the telemetry summary row."""

        async def _write() -> None:
            try:
                from backend.persistence.database import serialized_write

                async with serialized_write(self._session_factory) as session:
                    from backend.persistence.telemetry_summary_repo import TelemetrySummaryRepository

                    await TelemetrySummaryRepository(session).set_model(job_id=job_id, model=model)
            except Exception:
                log.debug(f"{self._watcher_log_prefix}_model_update_failed", job_id=job_id, exc_info=True)

        self._fire_bg(_write(), name=f"{self._watcher_log_prefix}-model-{job_id[:8]}")

    def _schedule_offset_persist(self, job_id: str, offset: int) -> None:
        """Flush accumulated telemetry + offset in a single transaction.

        Both are committed atomically so a crash-recovery replay from the old
        offset will re-derive the same deltas without double-counting.
        """
        counters = self._pending_telemetry.pop(job_id, {})

        async def _write() -> None:
            try:
                from backend.persistence.database import serialized_write

                async with serialized_write(self._session_factory) as session:
                    from backend.persistence.job_repo import JobRepository
                    from backend.persistence.telemetry_summary_repo import TelemetrySummaryRepository

                    if counters:
                        await TelemetrySummaryRepository(session).increment(job_id=job_id, **counters)
                    await JobRepository(session).update_tail_offset(job_id, offset)
            except Exception:
                log.debug(f"{self._watcher_log_prefix}_flush_failed", job_id=job_id, exc_info=True)

        self._fire_bg(_write(), name=f"{self._watcher_log_prefix}-flush-{job_id[:8]}")
