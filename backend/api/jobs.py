"""Job CRUD and control endpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any

import structlog
from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.di import CachedModelsBySdk
from backend.models.api_schemas import (
    ContinueJobRequest,
    CreateJobRequest,
    CreateJobResponse,
    DiffFileModel,
    DiffListResponse,
    JobListResponse,
    JobResponse,
    JobSnapshotResponse,
    LogLinePayload,
    LogListResponse,
    ModelInfoResponse,
    ModelListResponse,
    PlanStepPayload,
    ProgressHeadlinePayload,
    ResolutionAction,
    ResolveJobRequest,
    ResolveJobResponse,
    RestoreRequest,
    RestoreResponse,
    ResumeJobRequest,
    StepDiffPayload,
    StepListResponse,
    StoryBlock,
    StoryResponse,
    SuggestNamesRequest,
    SuggestNamesResponse,
    TimelineListResponse,
    TranscriptListResponse,
    TranscriptPayload,
    TranscriptSearchListResponse,
    TranscriptSearchResult,
    TurnSummaryPayload,
)
from backend.models.events import DomainEventKind
from backend.persistence.approval_repo import ApprovalRepository
from backend.persistence.event_repo import EventRepository
from backend.persistence.telemetry_spans_repo import TelemetrySpansRepository
from backend.services.diff_service import DiffService
from backend.services.event_bus import EventBus
from backend.services.git_service import GitError, GitService
from backend.services.job_service import JobService, ProgressPreview
from backend.services.merge_service import MergeService
from backend.services.naming_service import NamingService
from backend.services.runtime_service import RuntimeService
from backend.services.step_diff_service import StepDiffService
from backend.services.step_tracker import hydrate_plan_steps
from backend.services.story_service import StoryService
from backend.services.tool_formatters import format_tool_display, format_tool_display_full

if TYPE_CHECKING:
    from collections.abc import Callable

    from backend.models.domain import Job

from backend.models.domain import JobSpec, JobState, PermissionMode, Resolution

log = structlog.get_logger()

router = APIRouter(tags=["jobs"], route_class=DishkaRoute)

# Event query limits — bound the maximum rows returned from the event store.
# Default (2000) covers a typical 1–2 hour session; ceiling (5000) accommodates
# long-running jobs.  Plan/step events use the ceiling because each event is
# small and completeness matters for the UI step tracker.
_EVENT_QUERY_DEFAULT = 2000
_EVENT_QUERY_CEILING = 5000
# Progress headlines are short one-line status updates — 200 covers even
# long sessions while keeping the snapshot response compact.
_HEADLINE_QUERY_LIMIT = 200


def resolve_tool_display(payload: dict[str, Any]) -> str | None:
    """Return tool_display from payload, recomputing it from args if missing.

    Stored events pre-dating the tool_display field have no value in their
    payload, which causes the frontend to fall back to the raw tool name
    (e.g. just "Edit" instead of "Edit src/app.py").
    """
    return _resolve_display_field(payload, "tool_display", format_tool_display)


def resolve_tool_display_full(payload: dict[str, Any]) -> str | None:
    """Like _resolve_tool_display but returns the untruncated label.

    Recomputes tool_display_full from args when absent (e.g. events stored
    before this field was introduced).
    """
    return _resolve_display_field(payload, "tool_display_full", format_tool_display_full)


def _resolve_display_field(
    payload: dict[str, Any],
    field: str,
    formatter: Callable[..., str],
) -> str | None:
    stored = payload.get(field)
    if stored is not None:
        return str(stored)
    tool_name: str | None = payload.get("tool_name")
    if not tool_name:
        return None
    tool_args: str | None = payload.get("tool_args")
    tool_result = payload.get("tool_result") or None  # normalise empty string → None
    tool_success: bool = payload.get("tool_success") is not False
    return str(formatter(tool_name, tool_args, tool_result=tool_result, tool_success=tool_success))


def job_to_response(job: Job, progress_preview: ProgressPreview | None = None) -> JobResponse:
    """Map a domain Job to a JobResponse."""
    return JobResponse.from_domain(
        job,
        progress_headline=progress_preview.headline if progress_preview is not None else None,
        progress_summary=progress_preview.summary if progress_preview is not None else None,
    )


def _job_to_create_response(job: Job) -> CreateJobResponse:
    """Map a domain Job to a CreateJobResponse."""
    return CreateJobResponse(
        id=job.id,
        state=job.state,
        title=job.title,
        branch=job.branch,
        worktree_path=job.worktree_path,
        sdk=job.sdk,
        created_at=job.created_at,
    )


@router.post("/jobs/suggest-names", response_model=SuggestNamesResponse)
async def suggest_names(
    body: SuggestNamesRequest,
    naming_service: FromDishka[NamingService],
) -> SuggestNamesResponse:
    """Generate a suggested title, branch name, and worktree name for a task description.

    Uses a one-shot utility session (suggest-names is called before a job exists).
    Returns 503 if the utility LLM is not configured.
    """
    from backend.services.naming_service import NamingError

    try:
        title, description, branch_name, worktree_name = await naming_service.generate(body.prompt)
    except NamingError as exc:
        log.warning("naming_failed", exc_info=exc)
        raise HTTPException(status_code=503, detail="Naming failed") from exc

    return SuggestNamesResponse(
        title=title,
        description=description,
        branch_name=branch_name,
        worktree_name=worktree_name,
    )


@router.post("/jobs", response_model=CreateJobResponse, status_code=201)
async def create_job(
    body: CreateJobRequest,
    svc: FromDishka[JobService],
    session: FromDishka[AsyncSession],
    runtime_service: FromDishka[RuntimeService],
) -> CreateJobResponse:
    """Create a new job.

    Returns immediately with ``state=preparing``. Workspace setup and agent
    launch happen in a background task — the frontend watches progress via
    SSE ``job_setup_progress`` events.
    """
    import asyncio

    job = await svc.create_job(JobSpec(
        repo=body.repo,
        prompt=body.prompt,
        base_ref=body.base_ref,
        branch=body.branch,
        title=body.title,
        description=body.description,
        worktree_name=body.worktree_name,
        permission_mode=body.permission_mode or PermissionMode.full_auto,
        model=body.model,
        sdk=body.sdk,
        verify=body.verify,
        self_review=body.self_review,
        max_turns=body.max_turns,
        verify_prompt=body.verify_prompt,
        self_review_prompt=body.self_review_prompt,
    ))

    # Commit so the job row is visible to background tasks (separate sessions)
    await session.commit()

    # For already-failed jobs (naming failure), skip background setup
    if job.state != JobState.failed:
        # Fire-and-forget background task: setup workspace → start agent
        async def _setup_and_start() -> None:
            try:
                await runtime_service.setup_and_start(
                    job,
                    permission_mode=body.permission_mode.value if body.permission_mode else None,
                    session_token=body.session_token,
                )
            except Exception:
                log.error(
                    "background_job_setup_failed", job_id=job.id, exc_info=True
                )

        asyncio.create_task(_setup_and_start(), name=f"setup-{job.id}")

    return _job_to_create_response(job)


@router.get("/jobs", response_model=JobListResponse)
async def list_jobs(
    svc: FromDishka[JobService],
    state: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: Annotated[str | None, Query()] = None,
    archived: Annotated[bool | None, Query()] = None,
) -> JobListResponse:
    """List jobs with optional state filter and cursor pagination.

    Pass archived=true to list only archived jobs, archived=false to
    exclude them. Default (None) returns all jobs.
    """
    jobs, next_cursor, has_more = await svc.list_jobs(
        state=state,
        limit=limit,
        cursor=cursor,
        archived=archived,
    )
    progress_by_job = await svc.list_latest_progress_previews([job.id for job in jobs])
    return JobListResponse(
        items=[job_to_response(j, progress_by_job.get(j.id)) for j in jobs],
        cursor=next_cursor,
        has_more=has_more,
    )


@router.get("/jobs/{job_id}", response_model=JobResponse)
async def get_job(
    job_id: str,
    svc: FromDishka[JobService],
) -> JobResponse:
    """Get full job detail."""
    job = await svc.get_job(job_id)
    progress_preview = await svc.get_latest_progress_preview(job_id)
    return job_to_response(job, progress_preview)


@router.post("/jobs/{job_id}/cancel", response_model=JobResponse)
async def cancel_job(
    job_id: str,
    svc: FromDishka[JobService],
    runtime_service: FromDishka[RuntimeService],
) -> JobResponse:
    """Cancel a running or queued job."""
    job = await svc.cancel_job(job_id)

    # Also cancel the runtime task if running
    await runtime_service.cancel(job_id)

    return job_to_response(job)


@router.post("/jobs/{job_id}/interrupt", status_code=204)
async def interrupt_job(
    job_id: str,
    runtime_service: FromDishka[RuntimeService],
) -> None:
    """Interrupt the agent's current shell command without canceling the job.

    Sends a non-destructive interrupt (SIGINT-equivalent) to the SDK subprocess.
    The agent session stays alive and can recover or receive new instructions.
    """
    found = await runtime_service.interrupt(job_id)
    if not found:
        raise HTTPException(status_code=404, detail="No active agent session for this job")


@router.post("/jobs/{job_id}/rerun", response_model=CreateJobResponse, status_code=201)
async def rerun_job(
    job_id: str,
    svc: FromDishka[JobService],
    session: FromDishka[AsyncSession],
    runtime_service: FromDishka[RuntimeService],
) -> CreateJobResponse:
    """Create a new job from an existing job's configuration."""
    job = await svc.rerun_job(job_id)

    await session.commit()

    if job.state != JobState.failed:
        await runtime_service.start_or_enqueue(job)
        job = await svc.get_job(job.id)

    return _job_to_create_response(job)


@router.post("/jobs/{job_id}/pause", status_code=204)
async def pause_job(
    job_id: str,
    svc: FromDishka[JobService],
    runtime_service: FromDishka[RuntimeService],
) -> None:
    """Send a silent pause instruction to the agent of a running job."""
    await svc.get_job(job_id)
    sent = await runtime_service.pause_job(job_id)
    if not sent:
        raise HTTPException(status_code=409, detail="Job is not currently running")


@router.post("/jobs/{job_id}/continue", response_model=CreateJobResponse, status_code=201)
async def continue_job(
    job_id: str,
    body: ContinueJobRequest,
    runtime_service: FromDishka[RuntimeService],
) -> CreateJobResponse:
    """Create a follow-up job with a new instruction and parent-job handoff context."""
    try:
        job = await runtime_service.create_followup_job(job_id, body.instruction)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Follow-up instruction must not be empty") from exc

    return _job_to_create_response(job)


@router.post("/jobs/{job_id}/resume", response_model=JobResponse)
async def resume_job(
    job_id: str,
    runtime_service: FromDishka[RuntimeService],
    body: ResumeJobRequest | None = None,
) -> JobResponse:
    """Resume a completed/failed/canceled job in-place, optionally with extra instruction."""
    job = await runtime_service.resume_job(job_id, body.instruction if body is not None else None)
    return job_to_response(job)


@router.get("/models", response_model=ModelListResponse)
async def list_models(
    cached_models_by_sdk: FromDishka[CachedModelsBySdk],
    sdk: str | None = Query(default=None, description="SDK id (copilot | claude). Omit for default."),
) -> ModelListResponse:
    """Return the model list for the requested SDK, cached at server startup.

    If the cache is empty for the copilot SDK (e.g. auth wasn't ready at
    startup), attempt a live fetch so the user doesn't have to restart.
    """
    resolved_sdk = sdk if sdk is not None else "copilot"
    models = cached_models_by_sdk.get(resolved_sdk, [])
    if not models and resolved_sdk == "copilot":
        try:
            from copilot import CopilotClient

            _client = CopilotClient()
            await _client.start()
            try:
                live = [m.to_dict() for m in await _client.list_models()]
                if live:
                    cached_models_by_sdk[resolved_sdk] = live  # warm the cache for next time
                    models = live
            finally:
                await _client.stop()
        except (ImportError, ConnectionError, TimeoutError, RuntimeError):
            log.debug("model_live_fetch_failed", sdk=resolved_sdk, exc_info=True)
    return ModelListResponse(items=[ModelInfoResponse.model_validate(m) for m in models])


@router.get("/jobs/{job_id}/logs", response_model=LogListResponse)
async def get_job_logs(
    job_id: str,
    svc: FromDishka[JobService],
    level: Annotated[str, Query(pattern="^(debug|info|warn|error)$")] = "debug",
    limit: Annotated[int, Query(ge=1, le=_EVENT_QUERY_CEILING)] = _EVENT_QUERY_DEFAULT,
    session: Annotated[int | None, Query(ge=1, description="Filter to a specific session number (1-based)")] = None,
) -> LogListResponse:
    """Return historical log lines for a job, filtered by minimum severity.

    ``level`` is a *minimum* severity filter (inclusive):
    - ``debug``  → all lines (debug, info, warn, error)
    - ``info``   → info, warn, error
    - ``warn``   → warn, error
    - ``error``  → error only

    ``session`` optionally restricts results to a single session number.
    Session 1 is the initial run; subsequent numbers correspond to resume/
    handoff sessions.  Omit to return logs from all sessions.
    """
    _level_order = {"debug": 0, "info": 1, "warn": 2, "error": 3}
    min_priority = _level_order.get(level, 0)
    events = await svc.list_events_by_job(job_id, [DomainEventKind.log_line_emitted], limit=limit)
    lines = []
    for event in events:
        payload = event.payload
        event_level = payload.get("level", "info")
        if _level_order.get(event_level, 1) < min_priority:
            continue
        event_session = payload.get("session_number")
        if session is not None and (event_session or 1) != session:
            continue
        lines.append(
            LogLinePayload(
                job_id=event.job_id,
                seq=payload.get("seq", 0),
                timestamp=payload.get("timestamp", event.timestamp),
                level=event_level,
                message=payload.get("message", ""),
                context=payload.get("context"),
                session_number=event_session,
            )
        )
    return LogListResponse(items=lines)

@router.get("/jobs/{job_id}/diff", response_model=DiffListResponse)
async def get_job_diff(
    job_id: str,
    svc: FromDishka[JobService],
    diff_service: FromDishka[DiffService],
    spans_repo: FromDishka[TelemetrySpansRepository],
) -> DiffListResponse:
    """Return the current diff for a job.

    For running jobs, calculates a fresh diff from the worktree.
    For completed/archived jobs, returns the last stored diff snapshot.
    """
    job = await svc.get_job(job_id)

    files: list[DiffFileModel] = []

    # For active jobs with a worktree, calculate a fresh diff
    if (
        job.state in (JobState.running, JobState.waiting_for_approval)
        and job.worktree_path
        and job.worktree_path != job.repo
    ):
        try:
            files = await diff_service.calculate_diff(job.worktree_path, job.base_ref)
        except (GitError, OSError):
            log.warning(
                "get_job_diff_live_failed",
                job_id=job_id,
                worktree_path=str(job.worktree_path),
                base_ref=job.base_ref,
                exc_info=True,
            )

    if not files:
        # Fallback: read from event store (completed/archived/failed jobs)
        events = await svc.list_events_by_job(job_id, [DomainEventKind.diff_updated])
        if not events:
            return DiffListResponse(items=[])
        raw_files = events[-1].payload.get("changed_files", [])
        files = [DiffFileModel.model_validate(f) for f in raw_files]

    # Enrich with per-file write/retry churn data
    churn_rows = await spans_repo.file_write_churn(job_id)
    if churn_rows:
        churn_by_file = {r["tool_target"]: r for r in churn_rows}
        for f in files:
            row = churn_by_file.get(f.path)
            if row:
                f.write_count = row["write_count"]
                f.retry_count = row["retry_count"]

    return DiffListResponse(items=files)


@router.get("/jobs/{job_id}/transcript", response_model=TranscriptListResponse)
async def get_job_transcript(
    job_id: str,
    svc: FromDishka[JobService],
    limit: int = Query(default=_EVENT_QUERY_DEFAULT, ge=1, le=_EVENT_QUERY_CEILING),
) -> TranscriptListResponse:
    """Return historical transcript entries for a job from the event store."""
    events = await svc.list_events_by_job(job_id, [DomainEventKind.transcript_updated], limit=limit)

    # Build a turn_id → summary map from stored tool_group_summary events so
    # that restored transcripts include AI-generated group labels.
    summary_events = await svc.list_events_by_job(job_id, [DomainEventKind.tool_group_summary], limit=_EVENT_QUERY_CEILING)
    group_summary_by_turn: dict[str, str] = {
        str(ev.payload.get("turn_id")): str(ev.payload.get("summary"))
        for ev in summary_events
        if ev.payload.get("turn_id") and ev.payload.get("summary")
    }

    return TranscriptListResponse(items=[
        TranscriptPayload(
            job_id=event.job_id,
            seq=event.payload.get("seq", 0),
            timestamp=event.payload.get("timestamp", event.timestamp),
            role=event.payload.get("role", "agent"),
            content=event.payload.get("content", ""),
            title=event.payload.get("title"),
            turn_id=event.payload.get("turn_id"),
            tool_name=event.payload.get("tool_name"),
            tool_args=event.payload.get("tool_args"),
            tool_result=event.payload.get("tool_result"),
            tool_success=event.payload.get("tool_success"),
            tool_issue=event.payload.get("tool_issue"),
            tool_intent=event.payload.get("tool_intent"),
            tool_title=event.payload.get("tool_title"),
            tool_display=resolve_tool_display(event.payload),
            tool_display_full=resolve_tool_display_full(event.payload),
            tool_duration_ms=event.payload.get("tool_duration_ms"),
            tool_group_summary=group_summary_by_turn.get(event.payload.get("turn_id") or ""),
        )
        for event in events
    ])


@router.get("/jobs/{job_id}/steps", response_model=StepListResponse)
async def get_job_steps(
    job_id: str,
    svc: FromDishka[JobService],
) -> StepListResponse:
    """Return plan steps for a job, hydrated from persisted PlanStepUpdated events.

    During execution, plan steps are also delivered live via SSE.  This
    endpoint lets late-joining clients catch up on steps that were emitted
    before they connected.
    """
    events = await svc.list_events_by_job(job_id, [DomainEventKind.plan_step_updated], limit=_EVENT_QUERY_CEILING)
    # De-duplicate: keep the latest event per plan_step_id (events are ordered chronologically)
    latest_by_id: dict[str, dict[str, Any]] = {}
    for ev in events:
        step_id = ev.payload.get("plan_step_id", "")
        if step_id:
            latest_by_id[step_id] = ev.payload

    # Build response preserving insertion order (first-seen order = plan order)
    seen_order: list[str] = []
    for ev in events:
        sid = ev.payload.get("plan_step_id", "")
        if sid and sid not in seen_order:
            seen_order.append(sid)

    result: list[PlanStepPayload] = []
    for sid in seen_order:
        step_payload = latest_by_id[sid]
        # Skip pending steps that were never started (dropped on finalization)
        if step_payload.get("status") == "pending":
            continue
        result.append(
            PlanStepPayload(
                job_id=job_id,
                plan_step_id=step_payload.get("plan_step_id", ""),
                label=step_payload.get("label", ""),
                summary=step_payload.get("summary"),
                status=step_payload.get("status", "pending"),
                order=step_payload.get("order", 0),
                tool_count=step_payload.get("tool_count", 0),
                files_written=step_payload.get("files_written"),
                started_at=step_payload.get("started_at"),
                completed_at=step_payload.get("completed_at"),
                duration_ms=step_payload.get("duration_ms"),
                start_sha=step_payload.get("start_sha"),
                end_sha=step_payload.get("end_sha"),
            )
        )
    return StepListResponse(items=result)


@router.get("/jobs/{job_id}/steps/{step_id}/diff", response_model=StepDiffPayload)
async def get_step_diff(
    job_id: str,
    step_id: str,
    step_diff_svc: FromDishka[StepDiffService],
) -> StepDiffPayload:
    """Return the Git diff for a specific step.

    The step_id can be either a plan_step_id (ps-*) from plan_step_updated
    events, an internal step_id (step-*) from the StepRow table, or a
    turn_id from the SDK — all are looked up to find start_sha/end_sha.
    """
    return await step_diff_svc.get_step_diff(job_id, step_id)


@router.get("/jobs/{job_id}/transcript/search", response_model=TranscriptSearchListResponse)
async def search_transcript(
    job_id: str,
    event_repo: FromDishka[EventRepository],
    q: str = Query(..., min_length=2, max_length=200),  # noqa: B008
    roles: list[str] | None = Query(None),  # noqa: B008
    step_id: str | None = None,
    limit: int = Query(50, le=200),  # noqa: B008
) -> TranscriptSearchListResponse:
    """Full-text search within a job's transcript events."""
    from backend.models.api_schemas import TranscriptRole

    _valid_roles = {r.value for r in TranscriptRole}
    if roles:
        roles = [r for r in roles if r in _valid_roles]

    events = await event_repo.search_transcript(job_id, q, roles=roles, step_id=step_id, limit=limit)
    results = []
    for evt in events:
        payload = evt.payload
        results.append(
            TranscriptSearchResult(
                seq=int(payload.get("seq", 0)),
                role=str(payload.get("role", "")),
                content=str(payload.get("content", "")),
                tool_name=str(payload.get("tool_name")) if payload.get("tool_name") else None,
                step_id=str(payload.get("step_id")) if payload.get("step_id") else None,
                step_number=int(payload["step_number"]) if payload.get("step_number") is not None else None,
                timestamp=evt.timestamp,
            )
        )
    return TranscriptSearchListResponse(items=results)


@router.post("/jobs/{job_id}/restore", response_model=RestoreResponse)
async def restore_to_sha(
    job_id: str,
    body: RestoreRequest,
    svc: FromDishka[JobService],
    git_service: FromDishka[GitService],
) -> RestoreResponse:
    """Reset the job's worktree to a specific commit SHA.

    Destructive — requires frontend confirmation dialog.
    Blocked while the agent is actively running.
    """
    from fastapi import HTTPException

    from backend.models.domain import JobState

    job = await svc.get_job(job_id)
    if job.state in (JobState.running, JobState.waiting_for_approval):
        raise HTTPException(
            status_code=409,
            detail="Cannot restore while the agent is running. Cancel the job first.",
        )
    if not job.worktree_path:
        raise HTTPException(status_code=404, detail="Job has no worktree.")

    await git_service.reset_hard(body.sha, cwd=job.worktree_path)
    return RestoreResponse(restored=True, sha=body.sha)


@router.get("/jobs/{job_id}/timeline", response_model=TimelineListResponse)
async def get_job_timeline(
    job_id: str,
    svc: FromDishka[JobService],
    limit: int = Query(default=200, ge=1, le=1000),
) -> TimelineListResponse:
    """Return historical progress_headline milestones for a job.

    Events with ``replaces_count > 0`` retroactively collapse earlier entries,
    so the returned list is the final milestone timeline, not raw events.
    """
    events = await svc.list_events_by_job(job_id, [DomainEventKind.progress_headline], limit=limit)

    # Replay events to reconstruct the collapsed milestone list
    milestones: list[ProgressHeadlinePayload] = []
    for event in events:
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
    return TimelineListResponse(items=milestones)


@router.get("/jobs/{job_id}/snapshot", response_model=JobSnapshotResponse)
async def get_job_snapshot(
    job_id: str,
    svc: FromDishka[JobService],
    session: FromDishka[AsyncSession],
    diff_service: FromDishka[DiffService],
    approval_repo: FromDishka[ApprovalRepository],
) -> JobSnapshotResponse:
    """Full state hydration for a single job.

    Returns the job, logs, transcript, diff, approvals, and timeline in a
    single response. Used by the frontend after SSE reconnection or page
    refresh to ensure the UI is fully consistent with backend state.
    """
    from backend.services.snapshot_helpers import assemble_snapshot

    job = await svc.get_job(job_id)
    progress_preview = await svc.get_latest_progress_preview(job_id)

    return await assemble_snapshot(
        job=job,
        progress_preview=progress_preview,
        svc=svc,
        diff_service=diff_service,
        approval_repo=approval_repo,
        resolve_display=resolve_tool_display,
        resolve_display_full=resolve_tool_display_full,
        job_to_response=job_to_response,
        filter_transcript_deltas=True,
        detect_plan_generations=True,
        exclude_pending_steps=False,
        deduplicate_turn_summaries=True,
    )


@router.post("/jobs/{job_id}/resolve", response_model=ResolveJobResponse)
async def resolve_job(
    job_id: str,
    body: ResolveJobRequest,
    svc: FromDishka[JobService],
    session: FromDishka[AsyncSession],
    runtime_service: FromDishka[RuntimeService],
    merge_service: FromDishka[MergeService],
    event_bus: FromDishka[EventBus],
) -> ResolveJobResponse:
    """Resolve a review job: merge, create PR, discard, or resolve with agent."""
    job = await svc.validate_for_resolution(job_id)

    # agent_merge: hand the conflict back to the agent to resolve
    if body.action == ResolutionAction.agent_merge:
        if job.resolution != Resolution.conflict:
            raise HTTPException(status_code=409, detail="agent_merge is only valid when resolution is 'conflict'")

        # Retrieve conflict files from the latest merge_conflict event
        conflict_events = await svc.list_events_by_job(job_id, kinds=[DomainEventKind.merge_conflict])
        conflict_files: list[str] = []
        if conflict_events:
            conflict_files = conflict_events[-1].payload.get("conflict_files", [])

        files_detail = (
            "\nThe following files have conflicts:\n" + "\n".join(f"  - {f}" for f in conflict_files)
            if conflict_files
            else ""
        )
        conflict_prompt = (
            f"A merge conflict was detected when attempting to merge branch '{job.branch}' "
            f"into '{job.base_ref}'.{files_detail}\n\n"
            "Please resolve the merge conflicts:\n"
            "1. Run `git merge <base_ref>` in the worktree to reproduce the conflict markers\n"
            "2. Edit the conflicting files to resolve all conflicts, preserving the functional "
            "intent of both sides without compromising either set of changes\n"
            "3. Stage and commit the resolved files\n"
            "Do not make any other modifications beyond resolving the merge conflicts."
        )

        await runtime_service.resume_job(job_id, conflict_prompt)
        return ResolveJobResponse(resolution="agent_merge")

    resolution, pr_url, conflict_files_result, error, events = await svc.resolve_and_complete(
        job=job,
        action=body.action,
        merge_service=merge_service,
    )
    await session.commit()

    for event in events:
        await event_bus.publish(event)

    return ResolveJobResponse(
        resolution=resolution,
        pr_url=pr_url,
        conflict_files=conflict_files_result,
        error=error,
    )


@router.post("/jobs/{job_id}/archive", status_code=204)
async def archive_job(
    job_id: str,
    svc: FromDishka[JobService],
    session: FromDishka[AsyncSession],
    event_bus: FromDishka[EventBus],
) -> None:
    """Archive a completed job (hide from Kanban board)."""
    await svc.archive_job(job_id)
    await session.commit()
    await event_bus.publish(svc.build_job_archived_event(job_id))


@router.post("/jobs/{job_id}/unarchive", status_code=204)
async def unarchive_job(
    job_id: str,
    svc: FromDishka[JobService],
) -> None:
    """Archived jobs are final and cannot be returned to the active board."""
    await svc.get_job(job_id)
    raise HTTPException(status_code=409, detail="Archived jobs are complete; create a follow-up job instead.")


@router.get("/jobs/{job_id}/story", response_model=StoryResponse)
async def get_job_story(
    job_id: str,
    session: FromDishka[AsyncSession],
    story_service: FromDishka[StoryService],
    regenerate: bool = False,
    verbosity: str = Query(default="standard", pattern="^(summary|standard|detailed)$"),
) -> StoryResponse:
    """Return a structured code-review story with validated change references.

    Generated on demand using a cheap LLM for connective prose, with change
    references built directly from telemetry spans.  Cached on the jobs table.
    Pass ?regenerate=true to force a fresh generation.
    Verbosity: summary (one-sentence per file), standard (default), detailed (full rationale).
    """
    if regenerate:
        payload = await story_service.regenerate(session, job_id, verbosity=verbosity)
    else:
        payload = await story_service.get_or_generate(session, job_id, verbosity=verbosity)

    if not payload:
        return StoryResponse(job_id=job_id, blocks=[], cached=False, verbosity=verbosity)

    blocks = [StoryBlock(**b) for b in payload.get("blocks", [])]
    cached = not regenerate and bool(blocks)
    return StoryResponse(job_id=job_id, blocks=blocks, cached=cached, verbosity=verbosity)
