"""Job CRUD and control endpoints."""

from __future__ import annotations

import contextlib
import json
from typing import TYPE_CHECKING, Annotated, Any

import structlog
from dishka.integrations.fastapi import DishkaRoute, FromDishka

log = structlog.get_logger()
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.di import CachedModelsBySdk
from backend.models.api_schemas import (
    ContinueJobRequest,
    CreateJobRequest,
    CreateJobResponse,
    DiffFileModel,
    DiffListResponse,
    FileMotivation,
    HunkMotivation,
    JobListResponse,
    JobResponse,
    JobSnapshotResponse,
    JobTelemetryResponse,
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
    TelemetryCostBucket,
    TelemetryCostDrivers,
    TelemetryFileAccess,
    TelemetryFileEntry,
    TelemetryFileStats,
    TelemetryLlmCall,
    TelemetryQuotaSnapshot,
    TelemetryReviewComplexity,
    TelemetryReviewSignals,
    TelemetryToolCall,
    TelemetryTurnEconomics,
    TimelineListResponse,
    TranscriptListResponse,
    TranscriptPayload,
    TranscriptSearchListResponse,
    TranscriptSearchResult,
    TurnSummaryPayload,
)
from backend.models.events import DomainEventKind
from backend.services.diff_service import DiffService
from backend.services.event_bus import EventBus
from backend.services.git_service import GitError, GitService
from backend.services.job_service import JobService, ProgressPreview
from backend.services.merge_service import MergeService
from backend.services.naming_service import NamingService
from backend.services.runtime_service import RuntimeService
from backend.services.sister_session import SisterSessionManager
from backend.services.story_service import StoryService
from backend.services.tool_formatters import format_tool_display, format_tool_display_full

if TYPE_CHECKING:
    from collections.abc import Callable

    from backend.models.domain import Job

from backend.models.domain import JobSpec, JobState, PermissionMode, Resolution

router = APIRouter(tags=["jobs"], route_class=DishkaRoute)


def _resolve_tool_display(payload: dict[str, Any]) -> str | None:
    """Return tool_display from payload, recomputing it from args if missing.

    Stored events pre-dating the tool_display field have no value in their
    payload, which causes the frontend to fall back to the raw tool name
    (e.g. just "Edit" instead of "Edit src/app.py").
    """
    return _resolve_display_field(payload, "tool_display", format_tool_display)


def _resolve_tool_display_full(payload: dict[str, Any]) -> str | None:
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


def _job_to_response(job: Job, progress_preview: ProgressPreview | None = None) -> JobResponse:
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
    sister_sessions: FromDishka[SisterSessionManager],
) -> SuggestNamesResponse:
    """Generate a suggested title, branch name, and worktree name for a task description.

    Uses a one-shot utility session (suggest-names is called before a job exists).
    Returns 503 if the utility LLM is not configured.
    """
    from backend.services.naming_service import NamingError

    naming = NamingService(sister_sessions)
    try:
        title, description, branch_name, worktree_name = await naming.generate(body.prompt)
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
        items=[_job_to_response(j, progress_by_job.get(j.id)) for j in jobs],
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
    return _job_to_response(job, progress_preview)


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

    return _job_to_response(job)


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
    return _job_to_response(job)


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
    limit: Annotated[int, Query(ge=1, le=5000)] = 2000,
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
    session: FromDishka[AsyncSession],
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
    from backend.persistence.telemetry_spans_repo import TelemetrySpansRepository

    churn_rows = await TelemetrySpansRepository(session).file_write_churn(job_id)
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
    limit: int = Query(default=2000, ge=1, le=5000),
) -> TranscriptListResponse:
    """Return historical transcript entries for a job from the event store."""
    events = await svc.list_events_by_job(job_id, [DomainEventKind.transcript_updated], limit=limit)

    # Build a turn_id → summary map from stored tool_group_summary events so
    # that restored transcripts include AI-generated group labels.
    summary_events = await svc.list_events_by_job(job_id, [DomainEventKind.tool_group_summary], limit=5000)
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
            tool_display=_resolve_tool_display(event.payload),
            tool_display_full=_resolve_tool_display_full(event.payload),
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
    events = await svc.list_events_by_job(job_id, [DomainEventKind.plan_step_updated], limit=5000)
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
    session: FromDishka[AsyncSession],
    svc: FromDishka[JobService],
    git: FromDishka[GitService],
) -> StepDiffPayload:
    """Return the Git diff for a specific step.

    The step_id can be either a plan_step_id (ps-*) from plan_step_updated
    events, an internal step_id (step-*) from the StepRow table, or a
    turn_id from the SDK — all are looked up to find start_sha/end_sha.
    """
    start_sha: str | None = None
    end_sha: str | None = None
    step_row = None  # StepRow if found — used for preceding_context / turn_id

    # Try plan_step_updated events first (plan step IDs like ps-XXXX)
    events = await svc.list_events_by_job(job_id, [DomainEventKind.plan_step_updated], limit=5000)
    for ev in events:
        if ev.payload.get("plan_step_id") == step_id:
            # Take the latest event for this step (events are chronological)
            start = ev.payload.get("start_sha")
            end = ev.payload.get("end_sha")
            if start:
                start_sha = start
            if end:
                end_sha = end

    # Fallback: try StepRow table (internal step IDs like step-XXXX)
    if not start_sha or not end_sha:
        from sqlalchemy import select as _select

        from backend.models.db import StepRow

        result = await session.execute(_select(StepRow).where(StepRow.id == step_id))
        step_row = result.scalar_one_or_none()
        if step_row and step_row.start_sha and step_row.end_sha:
            start_sha = str(step_row.start_sha)
            end_sha = str(step_row.end_sha)

    # Fallback 2: try StepRow by turn_id (frontend passes turnId from transcript)
    if not start_sha or not end_sha:
        from sqlalchemy import select as _select

        from backend.models.db import StepRow

        result = await session.execute(_select(StepRow).where(StepRow.job_id == job_id, StepRow.turn_id == step_id))
        step_row = result.scalar_one_or_none()
        if step_row and step_row.start_sha and step_row.end_sha:
            start_sha = str(step_row.start_sha)
            end_sha = str(step_row.end_sha)

    if not start_sha or not end_sha or start_sha == end_sha:
        return StepDiffPayload(step_id=step_id, diff="", files_changed=0)

    job = await svc.get_job(job_id)
    if not job.worktree_path:
        return StepDiffPayload(step_id=step_id, diff="", files_changed=0)

    diff_text = await git.diff_range(start_sha, end_sha, cwd=job.worktree_path)
    files_changed = diff_text.count("\ndiff --git ") + (1 if diff_text.startswith("diff --git ") else 0)

    changed_files = DiffService._parse_unified_diff(diff_text)

    # Build motivation annotations from telemetry spans
    step_context: str | None = None
    file_motivations: dict[str, FileMotivation] = {}
    hunk_motivations: dict[str, HunkMotivation] = {}

    if step_row and hasattr(step_row, "preceding_context") and step_row.preceding_context:
        step_context = str(step_row.preceding_context)[:500]

    # Find the turn_id to look up telemetry spans
    turn_id_for_lookup = step_id  # The step_id is itself a turn_id in fallback 2
    if step_row and hasattr(step_row, "turn_id") and step_row.turn_id:
        turn_id_for_lookup = str(step_row.turn_id)

    try:
        from backend.persistence.telemetry_spans_repo import TelemetrySpansRepository

        spans_repo = TelemetrySpansRepository(session)
        spans = await spans_repo.file_write_spans_for_step(
            job_id=job_id, turn_id=turn_id_for_lookup,
        )
        # If no spans for exact turn_id, try job-wide motivated spans filtered by file path
        if not spans:
            all_spans = await spans_repo.motivated_spans_for_job(job_id=job_id)
            changed_paths = {f.path for f in changed_files}
            spans = [s for s in all_spans if s.get("tool_target") in changed_paths]

        # Build file-level motivations
        for span in spans:
            target = span.get("tool_target")
            summary = span.get("motivation_summary")
            if not target or not summary:
                continue
            lines = summary.strip().split("\n", 1)
            title = lines[0].strip()
            why = lines[1].strip() if len(lines) > 1 else ""
            file_motivations[target] = FileMotivation(title=title, why=why)

            # Build hunk-level motivations from edit_motivations
            edit_mots_raw = span.get("edit_motivations")
            if not edit_mots_raw:
                continue
            try:
                edit_mots = json.loads(edit_mots_raw) if isinstance(edit_mots_raw, str) else edit_mots_raw
            except (json.JSONDecodeError, TypeError):
                log.debug("edit_motivation_parse_failed", job_id=job_id, exc_info=True)
                continue
            if not isinstance(edit_mots, list) or not edit_mots:
                continue

            tool_args_raw = span.get("tool_args_json")
            parsed_args: dict[str, Any] = {}
            if tool_args_raw:
                with contextlib.suppress(json.JSONDecodeError, TypeError):
                    parsed_args = json.loads(tool_args_raw) if isinstance(tool_args_raw, str) else tool_args_raw

            # Try to match edit to a specific hunk via old_str content
            old_str = str(
                parsed_args.get("old_str", "")
                or parsed_args.get("oldString", "")
                or parsed_args.get("old_string", "")
                or ""
            )

            matched_hunk_idx: int | None = None
            # Find the file in changed_files
            for cf in changed_files:
                if cf.path != target:
                    continue
                if old_str and len(cf.hunks) > 1:
                    # Match: find the hunk whose deletion lines best contain old_str lines
                    old_lines = [l.strip() for l in old_str.strip().splitlines() if l.strip()]
                    if old_lines:
                        best_idx, best_ratio = 0, 0.0
                        for hi, hunk in enumerate(cf.hunks):
                            del_content = " ".join(
                                l.content.strip()
                                for l in hunk.lines
                                if l.type == "deletion"
                            )
                            hits = sum(1 for ol in old_lines if ol in del_content)
                            ratio = hits / len(old_lines)
                            if ratio > best_ratio:
                                best_ratio = ratio
                                best_idx = hi
                        if best_ratio >= 0.5:
                            matched_hunk_idx = best_idx
                elif len(cf.hunks) == 1:
                    matched_hunk_idx = 0
                break

            em = edit_mots[0]
            em_summary = em.get("summary", "")
            em_lines = em_summary.strip().split("\n", 1)
            em_title = em_lines[0].strip()
            em_why = em_lines[1].strip() if len(em_lines) > 1 else ""
            edit_key = em.get("edit_key", "")

            if matched_hunk_idx is not None:
                hunk_motivations[f"{target}:{matched_hunk_idx}"] = HunkMotivation(
                    edit_key=edit_key, title=em_title, why=em_why,
                )
            else:
                # Couldn't match to a hunk — attach as unmatched on file level
                if target in file_motivations:
                    file_motivations[target].unmatched_edits.append(
                        HunkMotivation(edit_key=edit_key, title=em_title, why=em_why),
                    )
    except (KeyError, ValueError, IndexError, TypeError):
        log.debug("motivation_annotation_failed", job_id=job_id, step_id=step_id, exc_info=True)

    return StepDiffPayload(
        step_id=step_id,
        diff=diff_text,
        files_changed=files_changed,
        changed_files=changed_files,
        step_context=step_context,
        file_motivations=file_motivations,
        hunk_motivations=hunk_motivations,
    )


@router.get("/jobs/{job_id}/transcript/search", response_model=TranscriptSearchListResponse)
async def search_transcript(
    job_id: str,
    session: FromDishka[AsyncSession],
    q: str = Query(..., min_length=2, max_length=200),  # noqa: B008
    roles: list[str] | None = Query(None),  # noqa: B008
    step_id: str | None = None,
    limit: int = Query(50, le=200),  # noqa: B008
) -> TranscriptSearchListResponse:
    """Full-text search within a job's transcript events."""
    from backend.models.api_schemas import TranscriptRole
    from backend.persistence.event_repo import EventRepository

    _valid_roles = {r.value for r in TranscriptRole}
    if roles:
        roles = [r for r in roles if r in _valid_roles]

    event_repo = EventRepository(session)
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


@router.post("/jobs/{job_id}/restore")
async def restore_to_sha(
    job_id: str,
    body: RestoreRequest,
    svc: FromDishka[JobService],
    git: FromDishka[GitService],
) -> RestoreResponse:
    """Reset the job's worktree to a specific commit SHA.

    Destructive — requires frontend confirmation dialog.
    Blocked while the agent is actively running.
    """
    from fastapi import HTTPException

    job = await svc.get_job(job_id)
    if job.state in ("running", "agent_running"):
        raise HTTPException(
            status_code=409,
            detail="Cannot restore while the agent is running. Cancel the job first.",
        )
    if not job.worktree_path:
        raise HTTPException(status_code=404, detail="Job has no worktree.")

    await git.reset_hard(body.sha, cwd=job.worktree_path)
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


@router.get("/jobs/{job_id}/snapshot")
async def get_job_snapshot(
    job_id: str,
    svc: FromDishka[JobService],
    session: FromDishka[AsyncSession],
    diff_service: FromDishka[DiffService],
) -> JobSnapshotResponse:
    """Full state hydration for a single job.

    Returns the job, logs, transcript, diff, approvals, and timeline in a
    single response. Used by the frontend after SSE reconnection or page
    refresh to ensure the UI is fully consistent with backend state.
    """
    job = await svc.get_job(job_id)
    progress_preview = await svc.get_latest_progress_preview(job_id)

    # Collect all sub-resources in parallel via gather
    import asyncio as _aio

    logs_coro = svc.list_events_by_job(job_id, [DomainEventKind.log_line_emitted], limit=2000)
    transcript_coro = svc.list_events_by_job(job_id, [DomainEventKind.transcript_updated], limit=2000)
    timeline_coro = svc.list_events_by_job(job_id, [DomainEventKind.progress_headline], limit=200)
    summary_coro = svc.list_events_by_job(job_id, [DomainEventKind.tool_group_summary], limit=5000)
    steps_coro = svc.list_events_by_job(job_id, [DomainEventKind.plan_step_updated], limit=5000)
    reassign_coro = svc.list_events_by_job(job_id, [DomainEventKind.step_entries_reassigned], limit=5000)
    turn_summary_coro = svc.list_events_by_job(job_id, [DomainEventKind.turn_summary], limit=5000)

    (
        log_events,
        transcript_events,
        timeline_events,
        summary_events,
        step_events,
        reassign_events,
        turn_summary_events,
    ) = await _aio.gather(
        logs_coro,
        transcript_coro,
        timeline_coro,
        summary_coro,
        steps_coro,
        reassign_coro,
        turn_summary_coro,
    )

    # Build logs
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

    # Build transcript with group summaries
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
        if e.payload.get("role", "agent") not in ("tool_output_delta", "reasoning_delta")
    ]

    # Apply step reassignments so transcript entries have their final step_id.
    # Without this, hydration returns the original step_id from when the entry
    # was first persisted, causing entries to appear under the wrong step.
    if reassign_events:
        # Build a map: turn_id → (old_step_id, new_step_id) for each reassignment.
        # Later reassignments for the same turn override earlier ones.
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

    # Build timeline
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

    # Build diff (live or from snapshot)
    diff: list[DiffFileModel] = []
    if (
        job.state in (JobState.running, JobState.waiting_for_approval)
        and job.worktree_path
        and job.worktree_path != job.repo
    ):
        with contextlib.suppress(GitError, OSError):
            diff = await diff_service.calculate_diff(job.worktree_path, job.base_ref)

    if not diff:
        diff_events = await svc.list_events_by_job(job_id, [DomainEventKind.diff_updated])
        if diff_events:
            raw_files = diff_events[-1].payload.get("changed_files", [])
            diff = [DiffFileModel.model_validate(f) for f in raw_files]

    # Build approvals from DB state (includes resolution status)
    from backend.models.api_schemas import ApprovalResponse
    from backend.persistence.approval_repo import ApprovalRepository

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

    # Build plan steps: detect the latest plan generation and reconstruct it.
    #
    # The step tracker replaces the in-memory plan when re-inferring, but old
    # plan_step_updated events remain in the DB.  We detect generation
    # boundaries: a batch of ≥2 *new* step IDs appearing together marks a
    # new plan generation.  We keep only the latest generation's IDs, then
    # overlay subsequent individual updates for those IDs.

    # 1. Walk step_events chronologically and identify generation boundaries.
    #    A "generation" starts whenever we see ≥2 never-before-seen IDs in a
    #    burst (events within 5 seconds of each other).

    seen_ids: set[str] = set()
    current_gen_ids: list[str] = []  # ordered IDs for the current generation
    current_gen_start: float = 0.0

    for ev in step_events:
        sid = ev.payload.get("plan_step_id", "")
        if not sid:
            continue
        ts = ev.timestamp.timestamp() if hasattr(ev.timestamp, "timestamp") else 0.0
        is_new = sid not in seen_ids

        if is_new:
            # If this new ID is far from the current burst, start a fresh burst
            if not current_gen_ids or (ts - current_gen_start > 5.0):
                # Commit previous burst as a generation if it had ≥2 new IDs
                if len(current_gen_ids) >= 2:
                    pass  # We'll override below; just keep accumulating
                current_gen_ids = [sid]
                current_gen_start = ts
            else:
                current_gen_ids.append(sid)
            seen_ids.add(sid)

    # If the last burst had ≥2 IDs, that's the latest generation.
    # Otherwise fall back to using all seen IDs (single-step updates only).
    if len(current_gen_ids) >= 2:
        latest_gen: set[str] = set(current_gen_ids)
    else:
        latest_gen = seen_ids

    # 2. Build the plan from latest generation IDs only.
    step_latest: dict[str, dict[str, Any]] = {}
    step_order: list[str] = []
    for ev in step_events:
        sid = ev.payload.get("plan_step_id", "")
        if not sid or sid not in latest_gen:
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
        if (p := step_latest[sid])
    ]

    # Build turn summaries for the activity timeline.
    # De-duplicate by turn_id: keep the LAST event per turn_id so label
    # refinements and merge updates are reflected, but preserve the FIRST
    # event's is_new_activity flag (the re-emit from _refine_activity_label
    # always sends is_new_activity=False which would erase the boundary).
    _turn_first_new: dict[str, bool] = {}  # turn_id → first is_new_activity
    _turn_latest: dict[str, int] = {}
    for idx, ev in enumerate(turn_summary_events):
        tid = ev.payload.get("turn_id", "")
        if tid:
            if tid not in _turn_first_new:
                _turn_first_new[tid] = bool(ev.payload.get("is_new_activity", False))
            _turn_latest[tid] = idx
    _keep_idxs = set(_turn_latest.values())
    turn_summaries = [
        TurnSummaryPayload(
            job_id=job_id,
            turn_id=ev.payload.get("turn_id", ""),
            title=ev.payload.get("title", ""),
            activity_id=ev.payload.get("activity_id", ""),
            activity_label=ev.payload.get("activity_label", ""),
            activity_status=ev.payload.get("activity_status", "active"),
            is_new_activity=_turn_first_new.get(ev.payload.get("turn_id", ""), False),
        )
        for idx, ev in enumerate(turn_summary_events)
        if idx in _keep_idxs and ev.payload.get("turn_id") and ev.payload.get("title")
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
    return resp


@router.get("/jobs/{job_id}/telemetry", response_model=JobTelemetryResponse)
async def get_job_telemetry(
    job_id: str,
    session: FromDishka[AsyncSession],
) -> JobTelemetryResponse:
    """Get telemetry data for a job run.

    Returns the persisted telemetry summary from the OTEL-backed SQLite store.
    Includes per-call span detail (tool calls, LLM calls) when available.
    """
    import json
    from datetime import UTC, datetime

    from backend.persistence.cost_attribution_repo import CostAttributionRepository
    from backend.persistence.file_access_repo import FileAccessRepository
    from backend.persistence.job_repo import JobRepository
    from backend.persistence.telemetry_spans_repo import TelemetrySpansRepository
    from backend.persistence.telemetry_summary_repo import TelemetrySummaryRepository

    summary = await TelemetrySummaryRepository(session).get(job_id)
    if summary is None:
        return JobTelemetryResponse(job_id=job_id, available=False)

    job_row = await JobRepository(session).get(job_id)
    sdk = job_row.sdk if job_row else ""

    # Parse quota JSON if present
    quota_snapshots_raw = None
    if summary.get("quota_json"):
        with contextlib.suppress(json.JSONDecodeError, TypeError):
            quota_snapshots_raw = json.loads(summary["quota_json"])

    # Compute derived fields
    input_tok = summary.get("input_tokens", 0)
    output_tok = summary.get("output_tokens", 0)
    cache_read = summary.get("cache_read_tokens", 0)
    window_size = summary.get("context_window_size", 0)
    current_ctx = summary.get("current_context_tokens", 0)

    # Load span detail for tool/LLM call breakdowns
    spans = await TelemetrySpansRepository(session).list_for_job(job_id)
    attribution_rows = await CostAttributionRepository(session).for_job(job_id)
    file_stats = await FileAccessRepository(session).reread_stats(job_id)
    top_files = await FileAccessRepository(session).most_accessed_files(job_id=job_id)
    tool_calls: list[TelemetryToolCall] = []
    llm_calls: list[TelemetryLlmCall] = []
    for span in spans:
        attrs = span.get("attrs", {})
        if span.get("span_type") == "tool":
            edit_motivations = None
            if span.get("edit_motivations"):
                with contextlib.suppress(json.JSONDecodeError, TypeError):
                    edit_motivations = json.loads(span["edit_motivations"])
            tool_calls.append(
                TelemetryToolCall(
                    name=span["name"],
                    duration_ms=float(span.get("duration_ms", 0)),
                    success=attrs.get("success", True),
                    offset_sec=float(span.get("started_at", 0)),
                    motivation_summary=span.get("motivation_summary"),
                    edit_motivations=edit_motivations,
                )
            )
        elif span.get("span_type") == "llm":
            llm_calls.append(
                TelemetryLlmCall(
                    model=span["name"],
                    input_tokens=attrs.get("input_tokens", 0),
                    output_tokens=attrs.get("output_tokens", 0),
                    cache_read_tokens=attrs.get("cache_read_tokens", 0),
                    cache_write_tokens=attrs.get("cache_write_tokens", 0),
                    cost=attrs.get("cost", 0),
                    duration_ms=float(span.get("duration_ms", 0)),
                    is_subagent=attrs.get("is_subagent", False),
                    offset_sec=float(span.get("started_at", 0)),
                    call_count=attrs.get("num_turns", 1),
                )
            )

    grouped_dimensions: dict[str, list[TelemetryCostBucket]] = {}
    turn_curve: list[TelemetryCostBucket] = []
    for row in attribution_rows:
        bucket = TelemetryCostBucket(
            dimension=row.get("dimension", "unknown"),
            bucket=row.get("bucket", "unknown"),
            cost_usd=float(row.get("cost_usd", 0)),
            input_tokens=int(row.get("input_tokens", 0)),
            output_tokens=int(row.get("output_tokens", 0)),
            call_count=int(row.get("call_count", 0)),
        )
        dimension = str(row.get("dimension", "unknown"))
        grouped_dimensions.setdefault(dimension, []).append(bucket)
        if dimension == "turn":
            turn_curve.append(bucket)

    turn_curve.sort(key=lambda item: int(item.bucket) if item.bucket.isdigit() else 0)

    # For running jobs, compute live duration from created_at instead of
    # the stored 0 which is only finalized when the job completes.
    duration_ms = summary.get("duration_ms", 0)
    if duration_ms == 0 and summary.get("status") == "running" and summary.get("created_at"):
        try:
            created = datetime.fromisoformat(summary["created_at"])
            if created.tzinfo is None:
                created = created.replace(tzinfo=UTC)
            duration_ms = int((datetime.now(UTC) - created).total_seconds() * 1000)
        except (ValueError, TypeError):
            log.debug("live_duration_parse_failed", job_id=job_id, exc_info=True)

    # Review signals: test co-modifications
    spans_repo = TelemetrySpansRepository(session)
    test_co_mods = await spans_repo.test_co_modifications(job_id)

    # Review complexity tier — thresholds are calibrated against historical
    # job data: >500 diff lines ≈ top-10% by size, >20 turns ≈ extended
    # sessions, >15 unique files ≈ cross-cutting changes.
    _LARGE_DIFF_LINES = 500
    _MANY_TURNS = 20
    _MANY_FILES = 15
    signals: list[str] = []
    diff_lines = int(summary.get("diff_lines_added", 0)) + int(
        summary.get("diff_lines_removed", 0)
    )
    total_turns = int(summary.get("total_turns", 0))
    unique_files = int(file_stats.get("unique_files", 0))
    if diff_lines > _LARGE_DIFF_LINES:
        signals.append("large_diff")
    if total_turns > _MANY_TURNS:
        signals.append("many_turns")
    if unique_files > _MANY_FILES:
        signals.append("many_files")
    if test_co_mods:
        signals.append("test_co_modifications")
    tier = "quick" if not signals else ("deep" if len(signals) >= 3 else "standard")

    # Build quota snapshots if present
    quota_snapshots = None
    if quota_snapshots_raw is not None:
        quota_snapshots = {
            resource: TelemetryQuotaSnapshot(
                used_requests=snap.get("used_requests", 0),
                entitlement_requests=snap.get("entitlement_requests", 0),
                remaining_percentage=snap.get("remaining_percentage", 0),
                overage=snap.get("overage", 0),
                overage_allowed=snap.get("overage_allowed", False),
                is_unlimited=snap.get("is_unlimited", False),
                reset_date=snap.get("reset_date", ""),
            )
            for resource, snap in quota_snapshots_raw.items()
            if isinstance(snap, dict)
        }

    return JobTelemetryResponse(
        available=True,
        job_id=job_id,
        sdk=sdk,
        model=summary.get("model", ""),
        main_model=summary.get("model", ""),
        duration_ms=duration_ms,
        input_tokens=input_tok,
        output_tokens=output_tok,
        total_tokens=input_tok + output_tok + cache_read,
        cache_read_tokens=cache_read,
        cache_write_tokens=summary.get("cache_write_tokens", 0),
        total_cost=float(summary.get("total_cost_usd", 0)),
        context_window_size=window_size,
        current_context_tokens=current_ctx,
        context_utilization=(current_ctx / window_size) if window_size else 0,
        compactions=summary.get("compactions", 0),
        tokens_compacted=summary.get("tokens_compacted", 0),
        tool_call_count=summary.get("tool_call_count", 0),
        total_tool_duration_ms=summary.get("total_tool_duration_ms", 0),
        tool_calls=tool_calls,
        llm_call_count=summary.get("llm_call_count", 0),
        total_llm_duration_ms=summary.get("total_llm_duration_ms", 0),
        llm_calls=llm_calls,
        approval_count=summary.get("approval_count", 0),
        total_approval_wait_ms=summary.get("approval_wait_ms", 0),
        agent_messages=summary.get("agent_messages", 0),
        operator_messages=summary.get("operator_messages", 0),
        premium_requests=float(summary.get("premium_requests", 0)),
        cost_drivers=TelemetryCostDrivers(
            activity=grouped_dimensions.get("activity", []),
            phase=grouped_dimensions.get("phase", []),
            edit_efficiency=grouped_dimensions.get("edit_efficiency", []),
        ),
        turn_economics=TelemetryTurnEconomics(
            total_turns=int(summary.get("total_turns", 0)),
            peak_turn_cost_usd=float(summary.get("peak_turn_cost_usd", 0)),
            avg_turn_cost_usd=float(summary.get("avg_turn_cost_usd", 0)),
            cost_first_half_usd=float(summary.get("cost_first_half_usd", 0)),
            cost_second_half_usd=float(summary.get("cost_second_half_usd", 0)),
            turn_curve=turn_curve,
        ),
        file_access=TelemetryFileAccess(
            stats=TelemetryFileStats(
                total_accesses=int(file_stats.get("total_accesses", 0)),
                unique_files=int(file_stats.get("unique_files", 0)),
                total_reads=int(file_stats.get("total_reads", 0)),
                total_writes=int(file_stats.get("total_writes", 0)),
                reread_count=int(file_stats.get("reread_count", 0)),
            ),
            top_files=[
                TelemetryFileEntry(
                    file_path=str(row.get("file_path", "")),
                    access_count=int(row.get("access_count", 0)),
                    read_count=int(row.get("read_count", 0)),
                    write_count=int(row.get("write_count", 0)),
                )
                for row in top_files
            ],
        ),
        quota_snapshots=quota_snapshots,
        review_signals=TelemetryReviewSignals(test_co_modifications=test_co_mods),
        review_complexity=TelemetryReviewComplexity(tier=tier, signals=signals),
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
    job = await svc.resolve_job(job_id, body.action)

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
