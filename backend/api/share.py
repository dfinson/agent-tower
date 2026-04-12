"""Job sharing endpoints — generate and consume share tokens."""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING

import structlog
from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.responses import StreamingResponse

from backend.config import CPLConfig
from backend.models.api_schemas import (
    CamelModel,
    DiffFileModel,
    JobResponse,
    LogLinePayload,
    PlanStepPayload,
    ProgressHeadlinePayload,
    TranscriptPayload,
    TurnSummaryPayload,
)
from backend.models.events import DomainEventKind
from backend.services.event_bus import EventBus
from backend.services.job_service import JobService
from backend.services.share_service import ShareService
from backend.services.sse_manager import SSEConnection, SSEManager

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

log = structlog.get_logger()

router = APIRouter(tags=["sharing"], route_class=DishkaRoute)


class ShareTokenResponse(CamelModel):
    token: str
    job_id: str
    url: str


class CreateShareRequest(CamelModel):
    job_id: str | None = None  # allow body-less POST where job_id is in path


# ---------------------------------------------------------------------------
# Create a share link
# ---------------------------------------------------------------------------


@router.post("/jobs/{job_id}/share", response_model=ShareTokenResponse)
async def create_share_link(
    job_id: str,
    request: Request,
    share_service: FromDishka[ShareService],
    svc: FromDishka[JobService],
) -> ShareTokenResponse:
    """Generate a read-only share URL for a job."""
    # Ensure the job exists
    await svc.get_job(job_id)
    entry = share_service.create_token(job_id)
    base = str(request.base_url).rstrip("/")
    return ShareTokenResponse(
        token=entry.token,
        job_id=job_id,
        url=f"{base}/shared/{entry.token}",
    )


# ---------------------------------------------------------------------------
# Consume a share link — read-only job detail
# ---------------------------------------------------------------------------


@router.get("/share/{token}/job", response_model=JobResponse)
async def get_shared_job(
    token: str,
    share_service: FromDishka[ShareService],
    svc: FromDishka[JobService],
) -> JobResponse:
    """Read-only job detail via share token."""
    job_id = share_service.validate(token)
    if job_id is None:
        raise HTTPException(status_code=404, detail="Invalid or expired share link")
    job = await svc.get_job(job_id)
    progress = await svc.get_latest_progress_preview(job_id)

    # Import here to avoid circular dependency
    from backend.api.jobs import _job_to_response

    return _job_to_response(job, progress)


# ---------------------------------------------------------------------------
# Shared SSE stream — read-only events for the shared job
# ---------------------------------------------------------------------------


@router.get("/share/{token}/events", response_model=None)
async def stream_shared_events(
    token: str,
    request: Request,
    share_service: FromDishka[ShareService],
    sse_manager: FromDishka[SSEManager],
    session_factory: FromDishka[async_sessionmaker],  # type: ignore[type-arg]
) -> StreamingResponse:
    """SSE stream scoped to a shared job (read-only)."""
    job_id = share_service.validate(token)
    if job_id is None:
        raise HTTPException(status_code=404, detail="Invalid or expired share link")

    header_last_id = request.headers.get("Last-Event-ID")
    conn = SSEConnection(job_id=job_id)
    sse_manager.register(conn)

    async def event_generator() -> AsyncGenerator[str, None]:
        try:
            if header_last_id is not None:
                try:
                    numeric_id = int(header_last_id)
                    await sse_manager.replay_from_factory(conn, session_factory, numeric_id)
                except (ValueError, TypeError):
                    pass

            yield "event: session_heartbeat\ndata: {}\n\n"

            while not conn.closed:
                try:
                    data = await asyncio.wait_for(conn.queue.get(), timeout=5.0)
                    yield data
                except TimeoutError:
                    yield "event: session_heartbeat\ndata: {}\n\n"
                except (asyncio.CancelledError, GeneratorExit):
                    break
        finally:
            sse_manager.unregister(conn)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "Transfer-Encoding": "chunked",
        },
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _validate_share(share_service: ShareService, token: str) -> str:
    """Validate a share token and return the job_id, or raise 404."""
    job_id = share_service.validate(token)
    if job_id is None:
        raise HTTPException(status_code=404, detail="Invalid or expired share link")
    return job_id


# ---------------------------------------------------------------------------
# Full snapshot — everything the shared UI needs in one request
# ---------------------------------------------------------------------------


@router.get("/share/{token}/snapshot")
async def get_shared_snapshot(
    token: str,
    share_service: FromDishka[ShareService],
    svc: FromDishka[JobService],
    session: FromDishka[AsyncSession],
    event_bus: FromDishka[EventBus],
    config: FromDishka[CPLConfig],
) -> dict[str, object]:
    """Full state hydration via share token — same shape as /jobs/{id}/snapshot."""
    from backend.api.jobs import _job_to_response, _resolve_tool_display, _resolve_tool_display_full
    from backend.models.api_schemas import ApprovalResponse, JobSnapshotResponse
    from backend.models.domain import JobState
    from backend.persistence.approval_repo import ApprovalRepository

    job_id = _validate_share(share_service, token)
    job = await svc.get_job(job_id)
    progress_preview = await svc.get_latest_progress_preview(job_id)

    # Collect all sub-resources in parallel
    (
        log_events,
        transcript_events,
        timeline_events,
        summary_events,
        step_events,
        reassign_events,
        turn_summary_events,
    ) = await asyncio.gather(
        svc.list_events_by_job(job_id, [DomainEventKind.log_line_emitted], limit=2000),
        svc.list_events_by_job(job_id, [DomainEventKind.transcript_updated], limit=2000),
        svc.list_events_by_job(job_id, [DomainEventKind.progress_headline], limit=200),
        svc.list_events_by_job(job_id, [DomainEventKind.tool_group_summary], limit=5000),
        svc.list_events_by_job(job_id, [DomainEventKind.plan_step_updated], limit=5000),
        svc.list_events_by_job(job_id, [DomainEventKind.step_entries_reassigned], limit=5000),
        svc.list_events_by_job(job_id, [DomainEventKind.turn_summary], limit=5000),
    )

    # Logs
    logs = [
        LogLinePayload(
            job_id=e.job_id,
            seq=e.payload.get("seq", 0),
            timestamp=e.payload.get("timestamp", e.timestamp),
            level=e.payload.get("level", "info"),
            message=e.payload.get("message", ""),
            context=e.payload.get("context"),
        )
        for e in log_events
    ]

    # Transcript with group summaries
    group_summary_by_turn: dict[str, str] = {
        str(ev.payload.get("turn_id")): str(ev.payload.get("summary"))
        for ev in summary_events
        if ev.payload.get("turn_id") and ev.payload.get("summary")
    }
    transcript = [
        TranscriptPayload(
            job_id=e.job_id,
            seq=e.payload.get("seq", 0),
            timestamp=e.payload.get("timestamp", e.timestamp),
            role=e.payload.get("role", "agent"),
            content=e.payload.get("content", ""),
            title=e.payload.get("title"),
            turn_id=e.payload.get("turn_id"),
            tool_name=e.payload.get("tool_name"),
            tool_args=e.payload.get("tool_args"),
            tool_result=e.payload.get("tool_result"),
            tool_success=e.payload.get("tool_success"),
            tool_issue=e.payload.get("tool_issue"),
            tool_intent=e.payload.get("tool_intent"),
            tool_title=e.payload.get("tool_title"),
            tool_display=_resolve_tool_display(e.payload),
            tool_display_full=_resolve_tool_display_full(e.payload),
            tool_duration_ms=e.payload.get("tool_duration_ms"),
            tool_group_summary=group_summary_by_turn.get(e.payload.get("turn_id") or ""),
            tool_visibility=e.payload.get("tool_visibility"),
            step_id=e.payload.get("step_id"),
            step_number=e.payload.get("step_number"),
        )
        for e in transcript_events
    ]

    # Apply step reassignments
    if reassign_events:
        reassign_map: dict[str, tuple[str, str]] = {}
        for ev in reassign_events:
            tid = ev.payload.get("turn_id", "")
            old_sid = ev.payload.get("old_step_id", "")
            new_sid = ev.payload.get("new_step_id", "")
            if tid and old_sid and new_sid:
                reassign_map[tid] = (old_sid, new_sid)
        if reassign_map:
            for entry in transcript:
                key = entry.turn_id or ""
                if key in reassign_map:
                    old_sid, new_sid = reassign_map[key]
                    if entry.step_id == old_sid:
                        entry.step_id = new_sid

    # Timeline
    milestones: list[ProgressHeadlinePayload] = []
    for event in timeline_events:
        replaces = event.payload.get("replaces_count", 0)
        if replaces > 0:
            milestones = milestones[:-replaces] if replaces < len(milestones) else []
        milestones.append(
            ProgressHeadlinePayload(
                job_id=event.job_id,
                headline=event.payload.get("headline", ""),
                headline_past=event.payload.get("headline_past", ""),
                summary=event.payload.get("summary", ""),
                timestamp=event.timestamp,
            )
        )

    # Diff
    diff: list[DiffFileModel] = []
    if (
        job.state in (JobState.running, JobState.waiting_for_approval)
        and job.worktree_path
        and job.worktree_path != job.repo
    ):
        from backend.services.diff_service import DiffService
        from backend.services.git_service import GitService

        git = GitService(config)
        ds = DiffService(git_service=git, event_bus=event_bus)
        with contextlib.suppress(Exception):
            diff = await ds.calculate_diff(job.worktree_path, job.base_ref)
    if not diff:
        diff_events = await svc.list_events_by_job(job_id, [DomainEventKind.diff_updated])
        if diff_events:
            raw_files = diff_events[-1].payload.get("changed_files", [])
            diff = [DiffFileModel.model_validate(f) for f in raw_files]

    # Approvals
    approval_repo = ApprovalRepository(session)
    db_approvals = await approval_repo.list_for_job(job_id)
    approval_list: list[ApprovalResponse] = [
        ApprovalResponse(
            id=a.id,
            job_id=a.job_id,
            description=a.description,
            proposed_action=a.proposed_action,
            requested_at=a.requested_at,
            resolved_at=a.resolved_at,
            resolution=a.resolution,
        )
        for a in db_approvals
    ]

    # Plan steps
    step_latest: dict[str, dict] = {}
    step_order: list[str] = []
    for ev in step_events:
        sid = ev.payload.get("plan_step_id", "")
        if not sid:
            continue
        step_latest[sid] = ev.payload
        if sid not in step_order:
            step_order.append(sid)
    plan_steps = [
        PlanStepPayload(
            job_id=job_id,
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
        )
        for sid in step_order
        if (p := step_latest[sid]).get("status") != "pending"
    ]

    # Turn summaries
    turn_summaries = [
        TurnSummaryPayload(
            job_id=job_id,
            turn_id=ev.payload.get("turn_id", ""),
            title=ev.payload.get("title", ""),
            activity_id=ev.payload.get("activity_id", ""),
            activity_label=ev.payload.get("activity_label", ""),
            activity_status=ev.payload.get("activity_status", "active"),
            is_new_activity=bool(ev.payload.get("is_new_activity", False)),
        )
        for ev in turn_summary_events
        if ev.payload.get("turn_id") and ev.payload.get("title")
    ]

    resp = JobSnapshotResponse(
        job=_job_to_response(job, progress_preview),
        logs=logs,
        transcript=transcript,
        diff=diff,
        approvals=approval_list,
        timeline=milestones,
        steps=plan_steps,
        turn_summaries=turn_summaries,
    )
    return resp.model_dump(by_alias=True)


# ---------------------------------------------------------------------------
# Shared telemetry — read-only metrics
# ---------------------------------------------------------------------------


@router.get("/share/{token}/telemetry")
async def get_shared_telemetry(
    token: str,
    share_service: FromDishka[ShareService],
    session: FromDishka[AsyncSession],
) -> dict[str, object]:
    """Read-only telemetry data via share token."""
    job_id = _validate_share(share_service, token)

    # Delegate to the same telemetry logic used by the authenticated endpoint
    from backend.api.jobs import get_job_telemetry

    return await get_job_telemetry(job_id, session)
