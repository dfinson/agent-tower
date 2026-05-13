"""Shared event processing pipeline for agent sessions.

Both RuntimeService (managed SDK sessions) and IngestService (imported CLI
sessions) funnel SessionEvents through this processor.  It handles:

  1. Diff triggering on file changes / tool completions
  2. SessionEvent → DomainEvent translation
  3. StepTracker annotation (step boundaries, step_number)
  4. TrailService step_id enrichment
  5. EventBus publishing

This eliminates the duplicate logic that previously lived in IngestService.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

import structlog

from backend.models.domain import SessionEvent, SessionEventKind
from backend.models.events import DomainEvent, DomainEventKind

if TYPE_CHECKING:
    from backend.services.diff_service import DiffService
    from backend.services.event_bus import EventBus
    from backend.services.steps.tracker import StepTracker
    from backend.services.trail import TrailService

log = structlog.get_logger()


class EventProcessor:
    """Stateless event processing shared between managed and imported sessions.

    Callers provide the per-job context (worktree_path, base_ref) and this
    class applies the full processing pipeline to each SessionEvent.
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
        # Synthesized turn_id per job for callers that don't provide one
        # (SessionStateWatcher, ClaudeSessionWatcher). Rotated on agent messages.
        self._turn_ids: dict[str, str] = {}

    def register_worktree(self, job_id: str, worktree_path: str) -> None:
        """Register worktree for step tracker SHA capture."""
        if self._step_tracker is not None:
            self._step_tracker.register_worktree(job_id, worktree_path)

    async def process_event(
        self,
        job_id: str,
        session_event: SessionEvent,
        worktree_path: str | None = None,
        base_ref: str | None = None,
    ) -> DomainEvent | None:
        """Process a SessionEvent through the standard pipeline.

        Returns the published DomainEvent, or None if the event was consumed
        internally (e.g. diff trigger) and no domain event was emitted.
        """
        diff_eligible = self._diff_service is not None and worktree_path and base_ref

        # Diff recalculation on file changes
        if diff_eligible and session_event.kind == SessionEventKind.file_changed:
            assert self._diff_service is not None and worktree_path and base_ref
            await self._diff_service.on_worktree_file_modified(job_id, worktree_path, base_ref)
            return None

        # Diff recalculation on tool completions (skip internal markers)
        if (
            diff_eligible
            and session_event.kind == SessionEventKind.transcript
            and session_event.payload.get("role") == "tool_call"
            and session_event.payload.get("tool_name") != "report_intent"
        ):
            assert self._diff_service is not None and worktree_path and base_ref
            await self._diff_service.on_worktree_file_modified(job_id, worktree_path, base_ref)

        # Translate to DomainEvent
        domain_event = self._translate_event(job_id, session_event)
        if domain_event is None:
            return None

        # Ensure transcript events carry a turn_id for step tracking.
        # Managed sessions (via CopilotAdapter) already include one; discovered
        # sessions from the watchers don't.  Synthesize one here and rotate it
        # on each completed agent message (role=="agent") to mark turn boundaries.
        if domain_event.kind == DomainEventKind.transcript_updated:
            payload = domain_event.payload
            if not payload.get("turn_id"):
                tid = self._turn_ids.get(job_id)
                if not tid:
                    tid = str(uuid.uuid4())
                    self._turn_ids[job_id] = tid
                payload["turn_id"] = tid
            role = str(payload.get("role", ""))
            # Rotate turn_id after a full agent message (signals end of turn)
            if role == "agent":
                self._turn_ids[job_id] = str(uuid.uuid4())

        # Step tracking — annotate transcript events with step boundaries
        if domain_event.kind == DomainEventKind.transcript_updated and self._step_tracker is not None:
            role = str(domain_event.payload.get("role", ""))
            if role != "agent_delta":
                await self._step_tracker.on_transcript_event(job_id, domain_event)
                current = self._step_tracker.current_step(job_id)
                if current:
                    domain_event.payload["step_number"] = current.step_number
                # TrailService is the sole step_id authority (ps-* IDs)
                if self._trail_service is not None:
                    plan_step_id = self._trail_service.get_active_plan_step_id(job_id)
                    if plan_step_id:
                        domain_event.payload["step_id"] = plan_step_id

        await self._event_bus.publish(domain_event)
        return domain_event

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

    @staticmethod
    def _translate_event(job_id: str, event: SessionEvent) -> DomainEvent | None:
        """Translate a SessionEvent into a DomainEvent."""
        mapping: dict[SessionEventKind, DomainEventKind] = {
            SessionEventKind.log: DomainEventKind.log_line_emitted,
            SessionEventKind.transcript: DomainEventKind.transcript_updated,
            SessionEventKind.approval_request: DomainEventKind.approval_requested,
            SessionEventKind.error: DomainEventKind.job_failed,
            SessionEventKind.model_downgraded: DomainEventKind.model_downgraded,
        }
        kind = mapping.get(event.kind)
        if kind is None:
            return None
        return DomainEvent(
            event_id=DomainEvent.make_event_id(),
            job_id=job_id,
            timestamp=datetime.now(UTC),
            kind=kind,
            payload=cast("dict[str, Any]", event.payload),
        )
