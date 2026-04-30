"""SSE connection management."""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import structlog

from backend.models.api_schemas import (
    ApprovalRequestedPayload,
    ApprovalResolvedPayload,
    ApprovalResponse,
    DiffUpdatePayload,
    JobArchivedPayload,
    JobCompletedPayload,
    JobFailedPayload,
    JobResolvedPayload,
    JobReviewPayload,
    JobStateChangedPayload,
    JobTitleUpdatedPayload,
    LogLinePayload,
    MergeCompletedPayload,
    MergeConflictPayload,
    ModelDowngradedPayload,
    PlanStepPayload,
    SessionHeartbeatPayload,
    SessionResumedPayload,
    SnapshotPayload,
    StepEntriesReassignedPayload,
    TelemetryUpdatedPayload,
    ToolGroupSummaryPayload,
    TranscriptPayload,
    TurnSummaryPayload,
)
from backend.models.domain import JobState, Resolution
from backend.models.events import DomainEvent, DomainEventKind

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from backend.persistence.approval_repo import ApprovalRepository
    from backend.persistence.event_repo import EventRepository
    from backend.persistence.job_repo import JobRepository

log = structlog.get_logger()

# SSE event type mapping from domain event kinds
_SSE_EVENT_TYPE: dict[DomainEventKind, str | None] = {
    DomainEventKind.job_created: "job_state_changed",
    DomainEventKind.job_setup_progress: "job_setup_progress",
    DomainEventKind.workspace_prepared: None,  # internal only
    DomainEventKind.agent_session_started: None,  # internal only
    DomainEventKind.log_line_emitted: "log_line",
    DomainEventKind.transcript_updated: "transcript_update",
    DomainEventKind.diff_updated: "diff_update",
    DomainEventKind.approval_requested: "approval_requested",
    DomainEventKind.approval_resolved: "approval_resolved",
    DomainEventKind.batch_approval_requested: "batch_approval_requested",
    DomainEventKind.batch_approval_resolved: "batch_approval_resolved",
    DomainEventKind.job_review: "job_review",
    DomainEventKind.job_completed: "job_completed",
    DomainEventKind.job_failed: "job_failed",
    DomainEventKind.job_canceled: "job_state_changed",
    DomainEventKind.job_state_changed: "job_state_changed",
    DomainEventKind.session_heartbeat: "session_heartbeat",
    DomainEventKind.merge_completed: "merge_completed",
    DomainEventKind.merge_conflict: "merge_conflict",
    DomainEventKind.session_resumed: "session_resumed",
    DomainEventKind.job_resolved: "job_resolved",
    DomainEventKind.job_archived: "job_archived",
    DomainEventKind.job_title_updated: "job_title_updated",
    DomainEventKind.progress_headline: None,  # dead — replaced by plan_step_updated
    DomainEventKind.model_downgraded: "model_downgraded",
    DomainEventKind.tool_group_summary: "tool_group_summary",
    DomainEventKind.agent_plan_updated: None,  # dead — replaced by plan_step_updated
    DomainEventKind.telemetry_updated: "telemetry_updated",
    # Step system — internal SDK-turn tracking, not sent to frontend
    DomainEventKind.step_started: None,
    DomainEventKind.step_completed: None,
    DomainEventKind.step_title_generated: None,
    DomainEventKind.step_group_updated: None,
    # Plan steps — the only step-level event the frontend sees
    DomainEventKind.plan_step_updated: "plan_step_updated",
    DomainEventKind.step_entries_reassigned: "step_entries_reassigned",
    DomainEventKind.turn_summary: "turn_summary",
    DomainEventKind.action_classified: "action_classified",
    DomainEventKind.policy_settings_changed: "policy_settings_changed",
}

# State implied by each domain event kind (for job_state_changed payloads)
_KIND_TO_STATE: dict[DomainEventKind, str] = {
    DomainEventKind.job_created: JobState.running,
    DomainEventKind.job_review: JobState.review,
    DomainEventKind.job_completed: JobState.completed,
    DomainEventKind.job_failed: JobState.failed,
    DomainEventKind.job_canceled: JobState.canceled,
}

# High-frequency event types suppressed in selective mode (>20 active jobs)
_SELECTIVE_SUPPRESSED: frozenset[str] = frozenset(
    {
        "log_line",
        "transcript_update",
        "diff_update",
        "session_heartbeat",
    }
)

# Event types delivered only to job-scoped connections, never to global/dashboard.
# These are high-frequency during execution and only relevant to a user viewing
# a specific job's detail panel.
_JOB_SCOPED_ONLY: frozenset[str] = frozenset(
    {
        "telemetry_updated",
    }
)

# Replay bounds
MAX_REPLAY_EVENTS = 500
MAX_REPLAY_AGE = timedelta(minutes=5)


class SSEConnection:
    """Represents a single SSE client connection."""

    _QUEUE_WARN_THRESHOLD = 0.8  # 80% of maxsize

    def __init__(self, job_id: str | None = None) -> None:
        self.job_id = job_id  # None = all jobs
        self.queue: asyncio.Queue[str] = asyncio.Queue(maxsize=1024)
        self.closed = False

    def send(self, data: str) -> None:
        if self.closed:
            return
        try:
            self.queue.put_nowait(data)
        except asyncio.QueueFull:
            # Close the overloaded connection so the client reconnects and
            # gets missed events via replay instead of silently losing them.
            log.warning("sse_queue_full_closing_connection", job_id=self.job_id)
            self.close()

    def close(self) -> None:
        self.closed = True


def _format_sse(event_id: str | None, event_type: str, data: str) -> str:
    """Format a single SSE frame. Omits ``id:`` when *event_id* is ``None``."""
    parts: list[str] = []
    if event_id is not None:
        parts.append(f"id: {event_id}")
    parts.append(f"event: {event_type}")
    parts.append(f"data: {data}")
    return "\n".join(parts) + "\n\n"


# ---------------------------------------------------------------------------
# Generic field-map builder
# ---------------------------------------------------------------------------
# Sentinels for timestamp handling in field maps
_TS_FALLBACK = object()  # event.payload.get(key, event.timestamp)
_TS_EVENT = object()  # always event.timestamp

# FieldMap: model kwarg → (payload_key, default)
# When default is _TS_FALLBACK, falls back to event.timestamp if missing.
# When default is _TS_EVENT, always uses event.timestamp (payload_key ignored).
FieldMap = dict[str, tuple[str, object]]


def _build_from_fields(event: DomainEvent, model_cls: type, fields: FieldMap) -> str:
    """Build a Pydantic SSE payload from a declarative field map.

    Every model receives ``job_id=event.job_id`` automatically.
    """
    kwargs: dict[str, object] = {"job_id": event.job_id}
    for kwarg_name, (payload_key, default) in fields.items():
        if default is _TS_FALLBACK:
            kwargs[kwarg_name] = event.payload.get(payload_key, event.timestamp)
        elif default is _TS_EVENT:
            kwargs[kwarg_name] = event.timestamp
        else:
            kwargs[kwarg_name] = event.payload.get(payload_key, default)
    result: str = model_cls(**kwargs).model_dump_json(by_alias=True)
    return result


# ---------------------------------------------------------------------------
# Custom builders for event types with non-trivial extraction logic
# ---------------------------------------------------------------------------

_BuilderFn = Callable[[DomainEvent], str]


def _build_job_state_changed(event: DomainEvent) -> str:
    new_state = _KIND_TO_STATE.get(
        event.kind, event.payload.get("state", event.payload.get("new_state", JobState.queued))
    )
    return JobStateChangedPayload(
        job_id=event.job_id,
        previous_state=event.payload.get("previous_state"),
        new_state=new_state,
        timestamp=event.timestamp,
    ).model_dump_json(by_alias=True)


def _build_job_review(event: DomainEvent) -> str:
    return JobReviewPayload(
        job_id=event.job_id,
        pr_url=event.payload.get("pr_url"),
        merge_status=event.payload.get("merge_status"),
        resolution=event.payload.get("resolution"),
        model_downgraded=bool(event.payload.get("model_downgraded", False)),
        requested_model=event.payload.get("requested_model"),
        actual_model=event.payload.get("actual_model"),
        timestamp=event.timestamp,
    ).model_dump_json(by_alias=True)


def _build_plan_step_updated(event: DomainEvent) -> str:
    p = event.payload
    return PlanStepPayload(
        job_id=event.job_id,
        plan_step_id=p.get("plan_step_id", ""),
        label=p.get("label", ""),
        summary=p.get("summary"),
        status=p.get("status", "pending"),
        order=p.get("order", 0),
        tool_count=p.get("tool_count", 0),
        files_written=p.get("files_written"),
        started_at=p.get("started_at"),
        completed_at=p.get("completed_at"),
        duration_ms=p.get("duration_ms"),
        start_sha=p.get("start_sha"),
        end_sha=p.get("end_sha"),
    ).model_dump_json(by_alias=True)


def _build_batch_approval_requested(event: DomainEvent) -> str:
    import json
    p = event.payload
    return json.dumps({
        "jobId": event.job_id,
        "batch_id": p.get("batch_id", ""),
        "batch_size": p.get("batch_size", 0),
        "summary": p.get("summary", ""),
        "actions": p.get("actions", []),
        "timestamp": event.timestamp.isoformat() if hasattr(event.timestamp, "isoformat") else str(event.timestamp),
    })


def _build_batch_approval_resolved(event: DomainEvent) -> str:
    import json
    p = event.payload
    return json.dumps({
        "jobId": event.job_id,
        "batch_id": p.get("batch_id", ""),
        "resolution": p.get("resolution", ""),
        "timestamp": event.timestamp.isoformat() if hasattr(event.timestamp, "isoformat") else str(event.timestamp),
    })


# ---------------------------------------------------------------------------
# Unified SSE payload registry
# ---------------------------------------------------------------------------
# Each entry is either a (ModelClass, FieldMap) tuple handled generically by
# ``_build_from_fields``, or a custom callable for event types that need
# non-trivial extraction logic.

_SSE_PAYLOAD_REGISTRY: dict[str, tuple[type, FieldMap] | _BuilderFn] = {
    # --- Custom builders (non-trivial extraction) ---
    "job_state_changed": _build_job_state_changed,
    "job_review": _build_job_review,
    "plan_step_updated": _build_plan_step_updated,
    "batch_approval_requested": _build_batch_approval_requested,
    "batch_approval_resolved": _build_batch_approval_resolved,
    # --- Field-map builders (declarative) ---
    "log_line": (
        LogLinePayload,
        {
            "seq": ("seq", 0),
            "timestamp": ("timestamp", _TS_FALLBACK),
            "level": ("level", "info"),
            "message": ("message", ""),
            "context": ("context", None),
        },
    ),
    "transcript_update": (
        TranscriptPayload,
        {
            "seq": ("seq", 0),
            "timestamp": ("timestamp", _TS_FALLBACK),
            "role": ("role", "agent"),
            "content": ("content", ""),
            "title": ("title", None),
            "turn_id": ("turn_id", None),
            "tool_name": ("tool_name", None),
            "tool_args": ("tool_args", None),
            "tool_result": ("tool_result", None),
            "tool_success": ("tool_success", None),
            "tool_issue": ("tool_issue", None),
            "tool_intent": ("tool_intent", None),
            "tool_title": ("tool_title", None),
            "tool_display": ("tool_display", None),
            "tool_display_full": ("tool_display_full", None),
            "tool_duration_ms": ("tool_duration_ms", None),
            "tool_visibility": ("tool_visibility", None),
            "step_id": ("step_id", None),
            "step_number": ("step_number", None),
        },
    ),
    "diff_update": (
        DiffUpdatePayload,
        {
            "changed_files": ("changed_files", []),
        },
    ),
    "approval_requested": (
        ApprovalRequestedPayload,
        {
            "approval_id": ("approval_id", ""),
            "description": ("description", ""),
            "proposed_action": ("proposed_action", None),
            "timestamp": ("timestamp", _TS_FALLBACK),
            "requires_explicit_approval": ("requires_explicit_approval", False),
        },
    ),
    "approval_resolved": (
        ApprovalResolvedPayload,
        {
            "approval_id": ("approval_id", ""),
            "resolution": ("resolution", ""),
            "timestamp": ("timestamp", _TS_FALLBACK),
        },
    ),
    "session_heartbeat": (
        SessionHeartbeatPayload,
        {
            "session_id": ("session_id", ""),
            "timestamp": ("timestamp", _TS_FALLBACK),
        },
    ),
    "merge_completed": (
        MergeCompletedPayload,
        {
            "branch": ("branch", ""),
            "base_ref": ("base_ref", ""),
            "strategy": ("strategy", ""),
            "timestamp": ("timestamp", _TS_FALLBACK),
        },
    ),
    "merge_conflict": (
        MergeConflictPayload,
        {
            "branch": ("branch", ""),
            "base_ref": ("base_ref", ""),
            "conflict_files": ("conflict_files", []),
            "fallback": ("fallback", "none"),
            "pr_url": ("pr_url", None),
            "timestamp": ("timestamp", _TS_FALLBACK),
        },
    ),
    "session_resumed": (
        SessionResumedPayload,
        {
            "session_number": ("session_number", 1),
            "timestamp": ("timestamp", _TS_FALLBACK),
        },
    ),
    "job_failed": (
        JobFailedPayload,
        {
            "reason": ("reason", "Unknown error"),
            "timestamp": ("timestamp", _TS_EVENT),
        },
    ),
    "job_completed": (
        JobCompletedPayload,
        {
            "resolution": ("resolution", None),
            "pr_url": ("pr_url", None),
            "timestamp": ("timestamp", _TS_EVENT),
        },
    ),
    "job_resolved": (
        JobResolvedPayload,
        {
            "resolution": ("resolution", Resolution.unresolved),
            "pr_url": ("pr_url", None),
            "conflict_files": ("conflict_files", None),
            "error": ("error", None),
            "timestamp": ("timestamp", _TS_EVENT),
        },
    ),
    "job_archived": (
        JobArchivedPayload,
        {
            "timestamp": ("timestamp", _TS_EVENT),
        },
    ),
    "job_title_updated": (
        JobTitleUpdatedPayload,
        {
            "title": ("title", None),
            "description": ("description", None),
            "branch": ("branch", None),
            "timestamp": ("timestamp", _TS_EVENT),
        },
    ),
    "model_downgraded": (
        ModelDowngradedPayload,
        {
            "requested_model": ("requested_model", ""),
            "actual_model": ("actual_model", ""),
            "timestamp": ("timestamp", _TS_EVENT),
        },
    ),
    "tool_group_summary": (
        ToolGroupSummaryPayload,
        {
            "turn_id": ("turn_id", ""),
            "summary": ("summary", ""),
            "timestamp": ("timestamp", _TS_EVENT),
        },
    ),
    "telemetry_updated": (
        TelemetryUpdatedPayload,
        {
            "timestamp": ("timestamp", _TS_EVENT),
        },
    ),
    "step_entries_reassigned": (
        StepEntriesReassignedPayload,
        {
            "turn_id": ("turn_id", ""),
            "old_step_id": ("old_step_id", ""),
            "new_step_id": ("new_step_id", ""),
        },
    ),
    "turn_summary": (
        TurnSummaryPayload,
        {
            "turn_id": ("turn_id", ""),
            "title": ("title", ""),
            "activity_id": ("activity_id", ""),
            "activity_label": ("activity_label", ""),
            "activity_status": ("activity_status", "active"),
            "is_new_activity": ("is_new_activity", False),
            "plan_item_id": ("plan_item_id", None),
        },
    ),
}


def _build_sse_data(event: DomainEvent, sse_type: str) -> str:
    """Serialize the domain event payload via the appropriate Pydantic SSE model.

    This ensures all SSE payloads use **camelCase** keys matching the API contract.
    """
    spec = _SSE_PAYLOAD_REGISTRY.get(sse_type)
    if spec is None:
        # Fallback (should not happen for known types)
        return json.dumps(event.payload, default=str)
    if callable(spec):
        return spec(event)
    model_cls, fields = spec
    return _build_from_fields(event, model_cls, fields)


def _build_derived_state_frame(event: DomainEvent, sse_id: str | None) -> str | None:
    """Build a derived ``job_state_changed`` SSE frame for events that imply a state transition.

    Returns ``None`` when *event* does not trigger a secondary frame.
    """
    if event.kind == DomainEventKind.approval_requested:
        payload = JobStateChangedPayload(
            job_id=event.job_id,
            previous_state=event.payload.get("previous_state"),
            new_state=JobState.waiting_for_approval,
            timestamp=event.timestamp,
        )
    elif event.kind == DomainEventKind.approval_resolved:
        new_state = JobState.running if event.payload.get("resolution") == "approved" else JobState.failed
        payload = JobStateChangedPayload(
            job_id=event.job_id,
            previous_state=JobState.waiting_for_approval,
            new_state=new_state,
            timestamp=event.timestamp,
        )
    elif event.kind in (DomainEventKind.job_review, DomainEventKind.job_completed, DomainEventKind.job_failed):
        payload = JobStateChangedPayload(
            job_id=event.job_id,
            previous_state=None,
            new_state=_KIND_TO_STATE[event.kind],
            timestamp=event.timestamp,
        )
    else:
        return None
    return _format_sse(sse_id, "job_state_changed", payload.model_dump_json(by_alias=True))


class SSEManager:
    """Manages open SSE connections and broadcasts events to clients.

    Responsibilities:
    - Track active SSE connections (optionally scoped to a job_id)
    - Translate domain events to SSE wire format
    - Broadcast/route events to appropriate connections
    - Support selective streaming when >20 jobs active
    - Handle disconnection cleanup
    """

    def __init__(self) -> None:
        self._connections: list[SSEConnection] = []
        self._active_job_count: int = 0

    @property
    def connection_count(self) -> int:
        return len(self._connections)

    def register(self, conn: SSEConnection) -> None:
        """Register a new SSE connection."""
        self._connections.append(conn)
        log.debug("sse_connection_opened", job_id=conn.job_id, total=len(self._connections))

    def unregister(self, conn: SSEConnection) -> None:
        """Remove a connection."""
        conn.close()
        with contextlib.suppress(ValueError):
            self._connections.remove(conn)
        log.debug("sse_connection_closed", job_id=conn.job_id, total=len(self._connections))

    def set_active_job_count(self, count: int) -> None:
        """Update the active job count for selective streaming decisions."""
        self._active_job_count = count

    async def broadcast_domain_event(self, event: DomainEvent) -> None:
        """Event bus subscriber — translate and broadcast a domain event."""
        sse_type = _SSE_EVENT_TYPE.get(event.kind)
        if sse_type is None:
            return  # internal-only event

        sse_id = str(event.db_id) if event.db_id is not None else event.event_id
        frame = _format_sse(sse_id, sse_type, _build_sse_data(event, sse_type))
        selective = self._active_job_count > 20

        # Prune connections closed since last broadcast
        self._connections = [c for c in self._connections if not c.closed]

        for conn in list(self._connections):
            if conn.closed:
                continue

            # Job-scoped connection: only deliver events for this job
            if conn.job_id is not None:
                if event.job_id != conn.job_id:
                    continue
                # Scoped connections always get full streaming
                conn.send(frame)
                continue

            # Global connections: skip job-scoped-only events entirely
            if sse_type in _JOB_SCOPED_ONLY:
                continue

            # Global connections: apply selective streaming if needed
            if selective and sse_type in _SELECTIVE_SUPPRESSED:
                continue

            conn.send(frame)

        # Emit secondary SSE events per the mapping in §5.3.1
        derived = _build_derived_state_frame(event, sse_id=None)
        if derived is not None:
            self._broadcast_frame(derived, event.job_id)

    def _broadcast_frame(self, frame: str, job_id: str) -> None:
        """Send a pre-formatted frame to all relevant connections."""
        for conn in list(self._connections):
            if conn.closed:
                continue
            if conn.job_id is not None and conn.job_id != job_id:
                continue
            conn.send(frame)

    def send_snapshot(self, conn: SSEConnection, snapshot: SnapshotPayload) -> None:
        """Send a snapshot event to a specific connection.

        Snapshot frames omit the ``id:`` field so they don't advance the
        client's ``lastEventId`` cursor — replay IDs stay monotonic with
        the DB autoincrement sequence.
        """
        frame = _format_sse(
            None,
            "snapshot",
            snapshot.model_dump_json(by_alias=True),
        )
        conn.send(frame)

    @staticmethod
    async def _fetch_pending_approvals(
        approval_repo: ApprovalRepository | None,
        job_id: str | None,
    ) -> list[ApprovalResponse]:
        """Fetch pending approvals from the database for snapshot payloads."""
        if approval_repo is None:
            return []

        pending = await approval_repo.list_pending(job_id=job_id)
        return [
            ApprovalResponse(
                id=a.id,
                job_id=a.job_id,
                description=a.description,
                proposed_action=a.proposed_action,
                requested_at=a.requested_at,
                resolved_at=a.resolved_at,
                resolution=a.resolution,
                requires_explicit_approval=a.requires_explicit_approval,
            )
            for a in pending
        ]

    async def replay_events(
        self,
        conn: SSEConnection,
        event_repo: EventRepository,
        job_repo: JobRepository,
        last_event_id: int,
        approval_repo: ApprovalRepository | None = None,
    ) -> None:
        """Replay missed events to a reconnecting client.

        If the gap is too large or too old, sends a snapshot first then
        recent events within the replay window.
        """
        cutoff = datetime.now(UTC) - MAX_REPLAY_AGE

        events = await event_repo.list_after(
            after_id=last_event_id,
            job_id=conn.job_id,
            limit=MAX_REPLAY_EVENTS + 1,  # +1 to detect overflow
        )

        needs_snapshot = False
        if len(events) > MAX_REPLAY_EVENTS:
            needs_snapshot = True
            events = events[:MAX_REPLAY_EVENTS]

        # Check if oldest event is beyond replay window
        if events and events[0].timestamp.replace(tzinfo=UTC) < cutoff:
            needs_snapshot = True

        if needs_snapshot:
            # Build and send snapshot (scoped to conn.job_id if set)
            from backend.models.api_schemas import JobResponse

            if conn.job_id is not None:
                single = await job_repo.get(conn.job_id)
                fetched_jobs = [single] if single else []
            else:
                fetched_jobs = await job_repo.list_all(include_archived=False)

            progress_by_job = await event_repo.list_latest_progress_previews([j.id for j in fetched_jobs])

            job_responses = [
                JobResponse.from_domain(
                    j,
                    progress_headline=progress_by_job.get(j.id, (None, None))[0],
                    progress_summary=progress_by_job.get(j.id, (None, None))[1],
                )
                for j in fetched_jobs
            ]
            snapshot = SnapshotPayload(
                jobs=job_responses,
                pending_approvals=await self._fetch_pending_approvals(approval_repo, conn.job_id),
            )
            self.send_snapshot(conn, snapshot)

            # Filter events to only those within the replay window
            events = [e for e in events if e.timestamp.replace(tzinfo=UTC) >= cutoff]

        # Replay the events
        for event in events:
            sse_type = _SSE_EVENT_TYPE.get(event.kind)
            if sse_type is None:
                continue
            sse_id = str(event.db_id) if event.db_id is not None else event.event_id
            frame = _format_sse(sse_id, sse_type, _build_sse_data(event, sse_type))
            conn.send(frame)

            # Mirror broadcast_domain_event(): emit a derived
            # job_state_changed frame so the client sees the state
            # transition on reconnect.  Reuse the same SSE id so the
            # replay cursor does not advance beyond the underlying event.
            derived = _build_derived_state_frame(event, sse_id=sse_id)
            if derived is not None:
                conn.send(derived)

    async def replay_from_factory(
        self,
        conn: SSEConnection,
        session_factory: async_sessionmaker[AsyncSession],
        last_event_id: int,
    ) -> None:
        """Replay missed events using a session factory.

        This is the preferred entry point from API routes — it keeps
        persistence imports inside the service layer so route modules
        never need to import repository classes directly.
        """
        from backend.persistence.approval_repo import ApprovalRepository
        from backend.persistence.event_repo import EventRepository
        from backend.persistence.job_repo import JobRepository

        async with session_factory() as session:
            event_repo = EventRepository(session)
            job_repo = JobRepository(session)
            approval_repo = ApprovalRepository(session)
            await self.replay_events(
                conn,
                event_repo,
                job_repo,
                last_event_id,
                approval_repo=approval_repo,
            )

    def close_all(self) -> None:
        """Close all connections (used during shutdown)."""
        for conn in list(self._connections):
            conn.close()
        self._connections.clear()
