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
    JobListResponse,
    JobResponse,
    ModelInfoResponse,
    ModelListResponse,
    ResumeJobRequest,
    SuggestNamesRequest,
    SuggestNamesResponse,
)
from backend.services.job_service import JobService, ProgressPreview
from backend.services.naming_service import NamingService
from backend.services.runtime_service import RuntimeService
from backend.services.tool_formatters import format_tool_display, format_tool_display_full

if TYPE_CHECKING:
    from collections.abc import Callable

    from backend.models.domain import Job

from backend.models.domain import JobSpec, JobState, Preset

log = structlog.get_logger()

router = APIRouter(tags=["jobs"], route_class=DishkaRoute)


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


def job_to_response(
    job: Job,
    progress_preview: ProgressPreview | None = None,
    *,
    total_cost_usd: float | int | None = None,
    total_tokens: float | int | None = None,
    input_tokens: float | int | None = None,
    output_tokens: float | int | None = None,
) -> JobResponse:
    """Map a domain Job to a JobResponse."""
    overrides: dict[str, Any] = {}
    if progress_preview is not None:
        overrides["progress_headline"] = progress_preview.headline
        overrides["progress_summary"] = progress_preview.summary
    if total_cost_usd is not None:
        overrides["total_cost_usd"] = float(total_cost_usd)
    if total_tokens is not None:
        overrides["total_tokens"] = int(total_tokens)
    if input_tokens is not None:
        overrides["input_tokens"] = int(input_tokens)
    if output_tokens is not None:
        overrides["output_tokens"] = int(output_tokens)
    return JobResponse.from_domain(job, **overrides)


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
        preset=body.preset or Preset.supervised,
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
    session: FromDishka[AsyncSession],
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
    job_ids = [job.id for job in jobs]
    progress_by_job = await svc.list_latest_progress_previews(job_ids)

    from backend.persistence.telemetry_summary_repo import TelemetrySummaryRepository
    cost_by_job = await TelemetrySummaryRepository(session).batch_cost_tokens(job_ids)

    items = []
    for j in jobs:
        ct = cost_by_job.get(j.id, {})
        items.append(job_to_response(
            j,
            progress_by_job.get(j.id),
            total_cost_usd=ct.get("total_cost_usd"),
            total_tokens=ct.get("total_tokens"),
            input_tokens=ct.get("input_tokens"),
            output_tokens=ct.get("output_tokens"),
        ))
    return JobListResponse(items=items, cursor=next_cursor, has_more=has_more)


@router.get("/jobs/{job_id}", response_model=JobResponse)
async def get_job(
    job_id: str,
    svc: FromDishka[JobService],
    session: FromDishka[AsyncSession],
) -> JobResponse:
    """Get full job detail."""
    job = await svc.get_job(job_id)
    progress_preview = await svc.get_latest_progress_preview(job_id)

    from backend.persistence.telemetry_summary_repo import TelemetrySummaryRepository
    ct = (await TelemetrySummaryRepository(session).batch_cost_tokens([job_id])).get(job_id, {})

    return job_to_response(
        job, progress_preview,
        total_cost_usd=ct.get("total_cost_usd"),
        total_tokens=ct.get("total_tokens"),
        input_tokens=ct.get("input_tokens"),
        output_tokens=ct.get("output_tokens"),
    )


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


