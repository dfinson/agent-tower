"""Shared event processing pipeline for agent sessions.

Both RuntimeService (managed SDK sessions) and the imported-ingestion sources
funnel ``traceforge.SessionEvent`` values through this single processor. Events
arrive already in TF-native shape (dotted ``kind``, TF payload fields); this
processor does NOT translate — it annotates and publishes:

  1. Diff triggering on file edits / tool completions
  2. turn_id synthesis + rotation for producers that don't supply one
  3. StepTracker annotation (step boundaries, step_number)
  4. TrailService step_id enrichment
  5. EventBus publishing

This is the one funnel for both producers — there is exactly one event shape.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import structlog

from backend.models.events import (
    TRANSCRIPT_KINDS,
    TRANSCRIPT_STREAMING_KINDS,
    EventKind,
    SessionEvent,
)

if TYPE_CHECKING:
    from backend.services.artifacts.diff_service import DiffService
    from backend.services.events.event_bus import EventBus
    from backend.services.steps.tracker import StepTracker
    from backend.services.trail import TrailService

log = structlog.get_logger()

# report_intent is an internal Copilot marker tool — it never mutates the
# worktree, so it must not trigger a diff recalculation.
_DIFF_SKIP_TOOL = "report_intent"


class EventProcessor:
    """Stateless event processing shared between managed and imported sessions.

    Callers provide the per-job context (worktree_path, base_ref) and this
    class applies the full processing pipeline to each ``SessionEvent``.
    """

    def __init__(
        self,
        event_bus: EventBus,
        diff_service: DiffService | None = None,
        step_tracker: StepTracker | None = None,
        trail_service: TrailService | None = None,
    ) -> None:
        self._event_bus = event_bus
        self._diff_service = diff_service
        self._step_tracker = step_tracker
        self._trail_service = trail_service
        # Synthesized turn_id per job for producers that don't provide one
        # (imported CLI sessions). Rotated on completed agent messages.
        self._turn_ids: dict[str, str] = {}

    def register_worktree(self, job_id: str, worktree_path: str) -> None:
        """Register worktree for step tracker SHA capture."""
        if self._step_tracker is not None:
            self._step_tracker.register_worktree(job_id, worktree_path)

    async def process_event(
        self,
        job_id: str,
        event: SessionEvent,
        worktree_path: str | None = None,
        base_ref: str | None = None,
    ) -> SessionEvent | None:
        """Process a TF-native ``SessionEvent`` through the standard pipeline.

        Returns the published event, or ``None`` if the event was consumed
        internally (e.g. a ``file.edited`` diff trigger) and nothing was emitted.
        """
        kind = event.kind
        diff_eligible = self._diff_service is not None and bool(worktree_path) and bool(base_ref)

        # Diff recalculation on native file-edit events — consumed, not published
        # (the FE receives file changes via the synthesized diff.updated event).
        if kind == EventKind.file_edited:
            if diff_eligible:
                assert self._diff_service is not None and worktree_path and base_ref
                await self._diff_service.on_worktree_file_modified(job_id, worktree_path, base_ref)
            return None

        # Diff recalculation on tool completions (skip internal marker tools)
        if (
            diff_eligible
            and kind == EventKind.tool_call_completed
            and event.payload.get("tool_name") != _DIFF_SKIP_TOOL
        ):
            assert self._diff_service is not None and worktree_path and base_ref
            await self._diff_service.on_worktree_file_modified(job_id, worktree_path, base_ref)

        is_transcript = kind in TRANSCRIPT_KINDS

        # Ensure transcript events carry a turn_id for step tracking. Managed
        # adapters already include one; imported sessions don't — synthesize here
        # and rotate on each completed agent message (turn boundary).
        if is_transcript:
            payload = event.payload
            if not payload.get("turn_id"):
                tid = self._turn_ids.get(job_id)
                if not tid:
                    tid = str(uuid.uuid4())
                    self._turn_ids[job_id] = tid
                payload["turn_id"] = tid
            if kind == EventKind.message_assistant:
                self._turn_ids[job_id] = str(uuid.uuid4())

        # Step tracking — annotate non-streaming transcript events with step
        # boundaries. Streaming partials (deltas, tool output chunks) are skipped.
        if is_transcript and kind not in TRANSCRIPT_STREAMING_KINDS and self._step_tracker is not None:
            await self._step_tracker.on_transcript_event(job_id, event)
            current = self._step_tracker.current_step(job_id)
            if current:
                event.payload["step_number"] = current.step_number
            # TrailService is the sole step_id authority (ps-* IDs)
            if self._trail_service is not None:
                plan_step_id = self._trail_service.get_active_plan_step_id(job_id)
                if plan_step_id:
                    event.payload["step_id"] = plan_step_id

        await self._event_bus.publish(event)
        return event

    async def on_job_terminal(self, job_id: str, outcome: str) -> None:
        """Notify step tracker of job terminal state."""
        if self._step_tracker is not None:
            await self._step_tracker.on_job_terminal(job_id, outcome)

    def cleanup(self, job_id: str) -> None:
        """Clean up per-job tracking state."""
        self._turn_ids.pop(job_id, None)
        if self._step_tracker is not None:
            self._step_tracker.cleanup(job_id)
        if self._diff_service is not None:
            self._diff_service.cleanup(job_id)
