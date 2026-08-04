"""Job artifact and query endpoints (logs, diff, transcript, steps, timeline, snapshot, story)."""

from __future__ import annotations

import contextlib
import json
from collections import OrderedDict
from datetime import datetime  # noqa: TC003 — used in type annotation
from typing import Annotated, Any, cast

import structlog
from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.api.jobs import (
    _stringify_tool_args,
    job_to_response,
    resolve_tool_display,
    resolve_tool_display_full,
)
from backend.models.api_schemas import (
    BlastRadiusCandidate,
    BlastRadiusResponse,
    CommunitiesResponse,
    CommunityGroup,
    CoveringTestCandidate,
    CoveringTestsResponse,
    DiffFileModel,
    DiffFileSymbolImpact,
    DiffListResponse,
    FileMotivation,
    HunkMotivation,
    ImpactGraphBatchRequest,
    ImpactGraphBatchResponse,
    ImpactGraphResponse,
    ImpactReference,
    JobMotivationsResponse,
    JobSnapshotResponse,
    LineCoverageResponse,
    LineCoverageTestInfo,
    LogLinePayload,
    LogListResponse,
    MultiSessionResponse,
    PlanStepPayload,
    ProgressHeadlinePayload,
    ResolutionAction,
    ResolveJobRequest,
    ResolveJobResponse,
    RestoreRequest,
    RestoreResponse,
    ReviewStoryHeader,
    ReviewStoryResponse,
    ReviewStoryVerdict,
    SessionSegment,
    StepDiffPayload,
    StepListResponse,
    StoryBlock,
    StoryResponse,
    StructuralChange,
    StructuralDiffResponse,
    TimelineListResponse,
    TranscriptListResponse,
    TranscriptPayload,
    TranscriptSearchListResponse,
    TranscriptSearchResult,
)
from backend.models.domain import JobState, Resolution
from backend.models.events import TRANSCRIPT_KINDS, EventKind
from backend.persistence.approval_repo import ApprovalRepository
from backend.persistence.event_repo import EventRepository
from backend.persistence.step_repo import StepRepository
from backend.persistence.telemetry_spans_repo import TelemetrySpansRepository
from backend.services.artifacts.diff_service import DiffService
from backend.services.coderecon.coderecon_service import CodeReconService
from backend.services.events.event_bus import EventBus
from backend.services.git.git_service import GitError, GitService
from backend.services.job.job_service import JobService
from backend.services.merge_service import MergeService
from backend.services.runtime import RuntimeService
from backend.services.steps.diff_service import StepDiffService
from backend.services.story.review import _ADDITIVE_CAP, _ATTENTION_CAP, _BODY_CAP

log = structlog.get_logger()

router = APIRouter(tags=["jobs"], route_class=DishkaRoute)

# Event query limits
_EVENT_QUERY_DEFAULT = 2000
_EVENT_QUERY_CEILING = 5000
_HEADLINE_QUERY_LIMIT = 200

# ── Structural analysis response cache ──
# Keyed on (job_id, endpoint_name, latest_end_sha). Entries are invalidated
# when the worktree advances (new SHA = cache miss, old entry evicted).
_STRUCTURAL_CACHE: OrderedDict[tuple[str, str, str], Any] = OrderedDict()
_STRUCTURAL_CACHE_MAX_ENTRIES = 64


def _cache_get(job_id: str, endpoint: str, sha: str | None) -> Any | None:
    """Return cached response or None. Evicts stale entries for the same job+endpoint."""
    if sha is None:
        return None
    key = (job_id, endpoint, sha)
    if key in _STRUCTURAL_CACHE:
        _STRUCTURAL_CACHE.move_to_end(key)
        return _STRUCTURAL_CACHE[key]
    return None


def _cache_put(job_id: str, endpoint: str, sha: str | None, value: Any) -> None:
    """Store a response. Evicts oldest entry if cache is full."""
    if sha is None:
        return
    key = (job_id, endpoint, sha)
    _STRUCTURAL_CACHE[key] = value
    _STRUCTURAL_CACHE.move_to_end(key)
    while len(_STRUCTURAL_CACHE) > _STRUCTURAL_CACHE_MAX_ENTRIES:
        _STRUCTURAL_CACHE.popitem(last=False)


async def _ensure_repo_and_worktree(
    coderecon: CodeReconService,
    repo: str,
    worktree_path: str,
) -> str:
    """Index the repo and register the worktree so semantic_diff sees changes."""
    repo_name = await coderecon.ensure_repo_indexed(repo)
    await coderecon.register_worktree(repo_name, worktree_path)
    return repo_name


async def _enrich_files_with_symbols(
    coderecon: CodeReconService,
    files: list[DiffFileModel],
    repo: str,
    worktree_path: str,
    base: str,
    *,
    target: str | None = None,
) -> None:
    """Attach per-file symbol impact data from CodeRecon semantic_diff.

    Runs semantic_diff for the given range (base..target or base..worktree)
    and groups structural changes by file path, attaching them to the
    corresponding DiffFileModel entries.
    """
    try:
        repo_name = await _ensure_repo_and_worktree(coderecon, repo, worktree_path)
        diff_result = await coderecon.semantic_diff(
            repo_name,
            base=base,
            target=target,
            worktree=worktree_path,
        )
    except Exception:
        log.debug("enrich_symbols_failed", repo=repo, base=base, target=target, exc_info=True)
        return

    # Group structural changes by file path
    by_file: dict[str, list[DiffFileSymbolImpact]] = {}
    for c in diff_result.structural_changes:
        name = c.qualified_name or c.name
        if not name:
            continue
        impact = c.impact
        ref_tiers = _translate_ref_tiers(impact.ref_tiers) if impact and impact.ref_tiers else {}
        sym = DiffFileSymbolImpact(
            symbol=name,
            kind=c.change,
            category=_classify_category(c),
            line_range=[c.start_line, c.end_line] if c.start_line else None,
            ref_count=impact.reference_count if impact and impact.reference_count else 0,
            ref_tiers=ref_tiers,
            test_files=impact.affected_test_files if impact and impact.affected_test_files else [],
        )
        by_file.setdefault(c.path, []).append(sym)

    # Attach to file models
    for f in files:
        symbols = by_file.get(f.path)
        if symbols:
            f.symbols = symbols


async def _latest_end_sha(step_repo: StepRepository, job_id: str) -> str | None:
    """Get the latest end_sha from the job's steps — serves as cache version key."""
    all_steps = await step_repo.get_by_job(job_id)
    for step in reversed(all_steps):
        if step.end_sha:
            return step.end_sha
    return None


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
    events = await svc.list_events_by_job(job_id, [EventKind.log_line_emitted], limit=limit)
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
                job_id=event.session_id,
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
    coderecon: FromDishka[CodeReconService],
) -> DiffListResponse:
    """Return the current diff for a job.

    For running jobs, calculates a fresh diff from the worktree.
    For completed/archived jobs, returns the last stored diff snapshot.
    """
    job = await svc.get_job(job_id)

    files: list[DiffFileModel] = []

    # For active jobs with a worktree, calculate a fresh diff
    if job.state in (JobState.running, JobState.waiting_for_approval) and job.worktree_path:
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
        events = await svc.list_events_by_job(job_id, [EventKind.diff_updated])
        if not events:
            return DiffListResponse(items=[])
        raw_files = cast("list[dict[str, Any]]", events[-1].payload.get("changed_files", []))
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

    # Enrich with per-file symbol impact from CodeRecon semantic_diff
    # (backfill for historical events stored without symbols)
    already_enriched = any(f.symbols for f in files)
    if files and not already_enriched and coderecon.available and job.repo and job.worktree_path:
        await _enrich_files_with_symbols(
            coderecon,
            files,
            job.repo,
            job.worktree_path,
            job.base_ref or "HEAD",
        )

    return DiffListResponse(items=DiffService.truncate_large_files(files))


@router.get("/jobs/{job_id}/diff-file", response_model=DiffFileModel)
async def get_job_diff_file(
    job_id: str,
    path: Annotated[str, Query(description="Relative file path within the diff")],
    svc: FromDishka[JobService],
    diff_service: FromDishka[DiffService],
) -> DiffFileModel:
    """Return the full (non-truncated) diff for a single file.

    Used by the frontend to lazily load large file diffs on demand.
    """
    job = await svc.get_job(job_id)

    file: DiffFileModel | None = None

    if job.state in (JobState.running, JobState.waiting_for_approval) and job.worktree_path:
        try:
            file = await diff_service.calculate_diff_single_file(job.worktree_path, job.base_ref, path)
        except (GitError, OSError):
            log.warning("get_job_diff_file_failed", job_id=job_id, path=path, exc_info=True)

    if file is None:
        # Fallback: read from event store
        events = await svc.list_events_by_job(job_id, [EventKind.diff_updated])
        if events:
            raw_files = cast("list[dict[str, Any]]", events[-1].payload.get("changed_files", []))
            for raw in raw_files:
                candidate = DiffFileModel.model_validate(raw)
                if candidate.path == path:
                    file = candidate
                    break

    if file is None:
        raise HTTPException(status_code=404, detail=f"File not found in diff: {path}")

    return file


@router.get("/jobs/{job_id}/transcript", response_model=TranscriptListResponse)
async def get_job_transcript(
    job_id: str,
    svc: FromDishka[JobService],
    limit: int = Query(default=_EVENT_QUERY_DEFAULT, ge=1, le=_EVENT_QUERY_CEILING),
) -> TranscriptListResponse:
    """Return historical transcript entries for a job from the event store."""
    events = await svc.list_events_by_job(job_id, list(TRANSCRIPT_KINDS), limit=limit)

    # Include persisted sidecar events so they survive page reload.
    sidecar_events = await svc.list_events_by_job(
        job_id,
        [EventKind.sidecar_transcript, EventKind.sidecar_agent_message],
        limit=limit,
    )

    # Build a turn_id → summary map from stored tool_group_summary events so
    # that restored transcripts include AI-generated group labels.
    summary_events = await svc.list_events_by_job(
        job_id, [EventKind.tool_group_summary], limit=_EVENT_QUERY_CEILING
    )
    group_summary_by_turn: dict[str, str] = {
        str(ev.payload.get("turn_id")): str(ev.payload.get("summary"))
        for ev in summary_events
        if ev.payload.get("turn_id") and ev.payload.get("summary")
    }

    items: list[TranscriptPayload] = [
        TranscriptPayload(
            job_id=event.session_id,
            event_id=event.id,
            sequence=event.metadata.sequence,
            timestamp=(p := event.payload).get("timestamp", event.timestamp),
            kind=str(event.kind),
            content=p.get("content", ""),
            title=p.get("title"),
            turn_id=event.metadata.turn_id or p.get("turn_id"),
            tool_call_id=p.get("tool_call_id"),
            tool_name=p.get("tool_name"),
            arguments=_stringify_tool_args(p.get("arguments")),
            result=p.get("result"),
            success=p.get("success"),
            tool_issue=p.get("tool_issue"),
            tool_intent=(event.metadata.motivation.intent if event.metadata.motivation else None),
            tool_title=p.get("tool_title"),
            tool_display=p.get("tool_display") or event.metadata.tool_display,
            tool_display_full=p.get("tool_display_full") or p.get("tool_display") or event.metadata.tool_display,
            tool_duration_ms=(
                int(event.metadata.duration_ms) if event.metadata.duration_ms is not None else None
            ),
            tool_group_summary=group_summary_by_turn.get(p.get("turn_id") or ""),
        )
        for event in events
    ]

    # Append sidecar entries (kind == "sidecar.*")
    for event in sidecar_events:
        p = event.payload
        items.append(
            TranscriptPayload(
                job_id=event.session_id,
                event_id=event.id,
                sequence=event.metadata.sequence,
                timestamp=p.get("timestamp", event.timestamp),
                kind=str(event.kind),
                content=p.get("content", ""),
                sidecar_name=p.get("sidecar_name"),
                sidecar_icon=p.get("sidecar_icon"),
                sidecar_description=p.get("sidecar_description"),
                sidecar_template_id=p.get("sidecar_template_id"),
            )
        )

    # Producer-stream sequence can order the transcript only when every event
    # provides one. Otherwise retain deterministic storage query order.
    if all(item.sequence is not None for item in items):
        items.sort(key=lambda item: item.sequence or 0)

    return TranscriptListResponse(items=items)


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
    events = await svc.list_events_by_job(job_id, [EventKind.plan_step_updated], limit=_EVENT_QUERY_CEILING)
    # De-duplicate: keep the latest event per plan_step_id (events are ordered chronologically)
    latest_by_id: dict[str, dict[str, Any]] = {}
    for ev in events:
        p = ev.payload
        step_id = p.get("plan_step_id", "")
        if step_id:
            latest_by_id[step_id] = p

    # Build response preserving insertion order (first-seen order = plan order)
    seen_order: list[str] = []
    for ev in events:
        p = ev.payload
        sid = p.get("plan_step_id", "")
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
    kinds: list[str] | None = Query(None),  # noqa: B008
    step_id: str | None = None,
    limit: int = Query(50, le=200),  # noqa: B008
) -> TranscriptSearchListResponse:
    """Full-text search within a job's transcript events."""
    _valid_kinds = {k.value for k in TRANSCRIPT_KINDS}
    if kinds:
        kinds = [k for k in kinds if k in _valid_kinds]

    events = await event_repo.search_transcript(job_id, q, kinds=kinds, step_id=step_id, limit=limit)
    results = []
    for evt in events:
        payload = evt.payload
        results.append(
            TranscriptSearchResult(
                seq=int(payload.get("seq", 0)),
                kind=str(evt.kind),
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


@router.post("/jobs/{job_id}/reenrich")
async def reenrich_job(
    job_id: str,
    session_factory: FromDishka[async_sessionmaker[AsyncSession]],
    force: bool = Query(default=False),
) -> dict[str, Any]:
    """Re-enrich historical events for a job through TraceForge.

    Replays all persisted events through a fresh TraceForge Enricher so
    that classification, visibility, tool_display and other metadata are
    backfilled.  Idempotent — a marker event prevents double processing
    unless ``force=true``.
    """
    from backend.services.events.reenrich import reenrich_job_events

    updated = await reenrich_job_events(job_id, session_factory, force=force)
    return {"job_id": job_id, "updated_events": updated}


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
    events = await svc.list_events_by_job(job_id, [EventKind.progress_headline], limit=limit)

    # Replay events to reconstruct the collapsed milestone list
    milestones: list[ProgressHeadlinePayload] = []
    for event in events:
        ep = event.payload
        replaces = int(ep.get("replaces_count", 0) or 0)
        if replaces > 0:
            milestones = milestones[:-replaces] if replaces < len(milestones) else []
        milestones.append(
            ProgressHeadlinePayload(
                job_id=event.session_id,
                headline=ep.get("headline", ""),
                headline_past=ep.get("headline_past", ""),
                summary=ep.get("summary", ""),
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
    session_factory: FromDishka[async_sessionmaker[AsyncSession]],
) -> JobSnapshotResponse:
    """Full state hydration for a single job.

    Returns the job, logs, transcript, diff, approvals, and timeline in a
    single response. Used by the frontend after SSE reconnection or page
    refresh to ensure the UI is fully consistent with backend state.
    """
    from backend.services.artifacts.snapshot_helpers import assemble_snapshot

    job = await svc.get_job(job_id)
    progress_preview = await svc.get_latest_progress_preview(job_id)

    from backend.persistence.telemetry_summary_repo import TelemetrySummaryRepository

    ct = (await TelemetrySummaryRepository(session).batch_cost_tokens([job_id])).get(job_id, {})

    return await assemble_snapshot(
        job=job,
        progress_preview=progress_preview,
        svc=svc,
        diff_service=diff_service,
        approval_repo=approval_repo,
        resolve_display=resolve_tool_display,
        resolve_display_full=resolve_tool_display_full,
        job_to_response=lambda j, pp: job_to_response(
            j,
            pp,
            total_cost_usd=ct.get("total_cost_usd"),
            total_tokens=ct.get("total_tokens"),
            input_tokens=ct.get("input_tokens"),
            output_tokens=ct.get("output_tokens"),
        ),
        filter_transcript_deltas=True,
        detect_plan_generations=True,
        exclude_pending_steps=False,
        deduplicate_turn_summaries=True,
        session_factory=session_factory,
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
    coderecon: FromDishka[CodeReconService],
) -> ResolveJobResponse:
    """Resolve a review job: merge, create PR, discard, or resolve with agent."""
    job = await svc.validate_for_resolution(job_id)

    # §7.4 — Merge confidence gate: if structural confidence is LOW and this
    # is a merge action, require explicit confirmation from the operator.
    if body.action in (ResolutionAction.merge, ResolutionAction.smart_merge) and not body.confirm_low_confidence:
        try:
            if coderecon.available and job.repo and job.worktree_path:
                story = await _generate_review_story(job_id, job, coderecon)
                if story.available and story.header and story.header.merge_confidence == "LOW":
                    blocker_list = []
                    if story.verdict:
                        blocker_list = story.verdict.blockers
                    raise HTTPException(
                        status_code=409,
                        detail={
                            "reason": "low_confidence",
                            "message": "Structural analysis confidence is LOW — explicit confirmation required.",
                            "blockers": blocker_list,
                        },
                    )
        except HTTPException:
            raise
        except Exception:
            pass  # Non-critical — if we can't check confidence, allow the merge

    # agent_merge: hand the conflict back to the agent to resolve
    if body.action == ResolutionAction.agent_merge:
        if job.resolution != Resolution.conflict:
            raise HTTPException(status_code=409, detail="agent_merge is only valid when resolution is 'conflict'")

        conflict_prompt = await svc.build_conflict_resume_prompt(job_id)
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
    regenerate: bool = False,
) -> StoryResponse:
    """Return a cached code-review story for a job.

    Stories are pre-generated in the background as soon as a job enters
    review state.  This endpoint reads from the DB cache only — it never
    blocks on LLM generation.

    Pass ?regenerate=true to force a fresh generation (fire-and-forget;
    returns empty immediately and the background loop will populate it).
    """
    from sqlalchemy import text as sa_text

    # Verify job exists
    exists = await session.execute(
        sa_text("SELECT 1 FROM jobs WHERE id = :jid"),
        {"jid": job_id},
    )
    if exists.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Job not found")

    if regenerate:
        # Clear the cached column so the drain loop regenerates it
        await session.execute(
            sa_text("UPDATE jobs SET story_text = NULL WHERE id = :jid"),
            {"jid": job_id},
        )
        await session.commit()
        return StoryResponse(job_id=job_id, blocks=[], cached=False, pending=True)

    # Read from cache only
    row = await session.execute(
        sa_text("SELECT story_text FROM jobs WHERE id = :jid"),
        {"jid": job_id},
    )
    cached = row.scalar_one_or_none()
    if cached:
        import json

        try:
            payload = json.loads(cached)
            blocks = [StoryBlock(**b) for b in payload.get("blocks", [])]
            return StoryResponse(
                job_id=job_id,
                blocks=blocks,
                cached=True,
                beat_count=payload.get("beat_count", 0),
                has_decisions=payload.get("has_decisions", False),
                has_backtracks=payload.get("has_backtracks", False),
            )
        except (json.JSONDecodeError, TypeError):
            pass

    # Not yet generated — the background drain loop will produce it
    return StoryResponse(job_id=job_id, blocks=[], cached=False, pending=True)


@router.get("/jobs/{job_id}/structural-diff", response_model=StructuralDiffResponse)
async def get_job_structural_diff(
    job_id: str,
    svc: FromDishka[JobService],
    coderecon: FromDishka[CodeReconService],
    step_repo: FromDishka[StepRepository],
) -> StructuralDiffResponse:
    """Return structural diff analysis for a job's changes.

    Uses CodeRecon's semantic_diff to classify changes by structural impact
    (added/removed/modified/moved symbols) rather than raw text diff.
    Computes risk scores and merge confidence per design §9.4 and §7.4.
    """
    job = await svc.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    if not coderecon.available or not job.repo or not job.worktree_path:
        return StructuralDiffResponse(job_id=job_id, available=False)

    # Cache check — keyed on latest commit SHA in worktree
    sha = await _latest_end_sha(step_repo, job_id)
    cached: StructuralDiffResponse | None = _cache_get(job_id, "structural-diff", sha)
    if cached is not None:
        return cached

    try:
        repo_name = await _ensure_repo_and_worktree(coderecon, job.repo, job.worktree_path)
        diff_result = await coderecon.semantic_diff(
            repo_name,
            base=job.base_ref or "HEAD",
            worktree=job.worktree_path,
        )
    except Exception:
        log.warning("structural_diff_failed", job_id=job_id, exc_info=True)
        return StructuralDiffResponse(job_id=job_id, available=False)

    # Check for NEW dependency cycles (§7.4) — compare worktree vs base
    has_new_cycles = False
    wt = job.worktree_path or job.repo
    try:
        worktree_cycles = await coderecon.graph_cycles(repo_name, worktree=wt)
        if worktree_cycles.cycles:
            base_cycles = await coderecon.graph_cycles(repo_name, worktree=job.repo)
            base_keys = {c.nodes for c in base_cycles.cycles}
            for c in worktree_cycles.cycles:
                if c.nodes not in base_keys:
                    has_new_cycles = True
                    break
    except Exception:
        log.debug("structural_diff_cycles_check_failed", job_id=job_id, exc_info=True)

    changes = _build_structural_changes(diff_result.structural_changes)
    triage = _compute_triage(changes)
    confidence = _compute_merge_confidence(changes, has_new_cycles=has_new_cycles)

    result = StructuralDiffResponse(
        job_id=job_id,
        summary=diff_result.summary,
        changes=changes,
        merge_confidence=confidence,
        triage=triage,
    )
    _cache_put(job_id, "structural-diff", sha, result)
    return result


# -- Structural diff helpers --------------------------------------------------

# Category severity for risk scoring (§9.4)
_CATEGORY_SEVERITY = {
    "breaking": 1.0,
    "body": 0.5,
    "additive": 0.1,
    "non-structural": 0.0,
}


def _classify_category(c: Any) -> str:
    """Classify a structural change into review categories (§9.2)."""
    kind = c.change  # StructuralChange.change: added/removed/modified/moved
    # Breaking: signature change or removal with callers
    ref_count = c.impact.reference_count if c.impact and c.impact.reference_count else 0
    if kind == "removed":
        return "breaking" if ref_count > 0 else "non-structural"
    if kind == "modified":
        # If signature changed (old_sig != new_sig), it's breaking
        if c.old_sig is not None and c.new_sig is not None and c.old_sig != c.new_sig:
            return "breaking"
        return "body"
    if kind == "added":
        return "additive"
    if kind == "moved":
        return "body"
    return "non-structural"


def _translate_ref_tiers(raw_tiers: Any) -> dict[str, int]:
    """Collapse RefTierBreakdown into user-facing labels (§2.2).

    RefTierBreakdown has: proven, strong, anchored, unknown (all int).
    """
    result: dict[str, int] = {}
    proven = raw_tiers.proven or 0
    strong = raw_tiers.strong or 0
    anchored = raw_tiers.anchored or 0
    unknown = raw_tiers.unknown or 0
    if proven:
        result["verified"] = proven
    if strong or anchored:
        result["inferred"] = strong + anchored
    if unknown:
        result["unverified"] = unknown
    return result


def _compute_risk(category: str, ref_tiers: dict[str, int], test_files: list[Any]) -> float:
    """Composite risk score per §9.4."""
    severity = _CATEGORY_SEVERITY.get(category, 0.0)

    total_refs = sum(ref_tiers.values())
    unknown_ratio = ref_tiers.get("unverified", 0) / total_refs if total_refs > 0 else 0.0

    test_gap = 1.0 if not test_files else 0.0

    risk = (0.4 * severity) + (0.35 * unknown_ratio) + (0.25 * test_gap)
    return round(risk, 2)


def _build_structural_changes(raw_changes: list[Any]) -> list[StructuralChange]:
    """Transform coderecon StructuralChange objects into API StructuralChange models."""
    changes = []
    for c in raw_changes:
        category = _classify_category(c)

        # Extract ref tiers from impact info
        impact = c.impact
        ref_count = impact.reference_count if impact and impact.reference_count else 0
        test_files = impact.affected_test_files if impact and impact.affected_test_files else []

        ref_tiers = _translate_ref_tiers(impact.ref_tiers) if impact and impact.ref_tiers else {}

        # If reports callers but no tier breakdown, treat gap as unverified
        classified = sum(ref_tiers.values())
        if ref_count > classified:
            ref_tiers["unverified"] = ref_tiers.get("unverified", 0) + (ref_count - classified)

        risk = _compute_risk(category, ref_tiers, test_files)

        changes.append(
            StructuralChange(
                kind=c.change,
                symbol=c.qualified_name or c.name,
                file=c.path,
                summary=c.change_preview,
                category=category,
                ref_count=ref_count,
                ref_tiers=ref_tiers,
                test_files=test_files,
                risk=risk,
                line_range=[c.start_line, c.end_line] if c.start_line else None,
                coverage_confidence=(
                    impact.coverage_confidence if impact and hasattr(impact, "coverage_confidence") else None
                ),
            )
        )
    return changes


def _compute_triage(changes: list[StructuralChange]) -> dict[str, int]:
    """Count changes per category for triage bar."""
    triage: dict[str, int] = {}
    for ch in changes:
        triage[ch.category] = triage.get(ch.category, 0) + 1
    return triage


def _compute_merge_confidence(changes: list[StructuralChange], *, has_new_cycles: bool = False) -> str:
    """Merge confidence per §7.4.

    HIGH: All refs verified/inferred, no breaking with unverified, no new cycles,
          breaking changes have test coverage.
    LOW: Unverified refs on breaking changes, or new dependency cycles.
    MEDIUM: Everything else.
    """
    if has_new_cycles:
        return "LOW"

    has_unverified_breaking = False
    has_unknown_refs = False
    has_untested_breaking = False

    for ch in changes:
        if ch.ref_tiers.get("unverified", 0) > 0:
            has_unknown_refs = True
            if ch.category == "breaking":
                has_unverified_breaking = True
        if ch.category == "breaking" and not ch.test_files:
            has_untested_breaking = True

    if has_unverified_breaking:
        return "LOW"
    if has_unknown_refs or has_untested_breaking:
        return "MEDIUM"
    return "HIGH"


# -- Multi-session intelligence (§10) -----------------------------------------


@router.get("/jobs/{job_id}/multi-session", response_model=MultiSessionResponse)
async def get_job_multi_session(
    job_id: str,
    svc: FromDishka[JobService],
    step_repo: FromDishka[StepRepository],
    event_repo: FromDishka[EventRepository],
    coderecon: FromDishka[CodeReconService],
) -> MultiSessionResponse:
    """Multi-session structural intelligence.

    Returns per-session structural analysis with direction change detection
    and messy-session warnings (§10).
    """
    job = await svc.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    if not coderecon.available or not job.repo or not job.worktree_path:
        return MultiSessionResponse(job_id=job_id, available=False)

    if (job.session_count or 1) < 2:
        # Single-session job — no multi-session intelligence needed
        return MultiSessionResponse(job_id=job_id, sessions=[])

    try:
        repo_name = await _ensure_repo_and_worktree(coderecon, job.repo, job.worktree_path or job.repo)
    except Exception:
        return MultiSessionResponse(job_id=job_id, available=False)

    # Get all steps and partition by session boundaries
    steps = await step_repo.get_by_job(job_id)
    if not steps:
        return MultiSessionResponse(job_id=job_id, sessions=[])

    # Get session_resumed events to determine real session boundaries.
    # Session 1 starts at job creation; session N starts at the (N-1)th
    # session_resumed event timestamp.
    resumed_events = await event_repo.list_by_job(
        job_id,
        [EventKind.session_resumed],
        limit=100,
    )
    # Build boundary timestamps: session N starts at resumed_events[N-2].timestamp
    # (session 1 has no preceding event — it starts at epoch)
    session_boundaries: list[datetime] = []
    for ev in resumed_events:
        session_boundaries.append(ev.timestamp)

    # Assign each step to a session based on its started_at vs boundaries
    session_steps: dict[int, list[Any]] = {}
    for step in steps:
        sess_num = 1
        for i, boundary in enumerate(session_boundaries):
            if step.started_at >= boundary:
                sess_num = i + 2  # boundary[0] starts session 2
        session_steps.setdefault(sess_num, []).append(step)

    segments: list[SessionSegment] = []
    prev_added_symbols: set[str] = set()
    direction_changes: list[dict[str, Any]] = []

    for sess_num in sorted(session_steps.keys()):
        sess_steps = session_steps[sess_num]
        # Find SHA range for this session
        start_sha = next((s.start_sha for s in sess_steps if s.start_sha), None)
        end_sha = next((s.end_sha for s in reversed(sess_steps) if s.end_sha), None)

        changes: list[StructuralChange] = []
        warnings: list[dict[str, Any]] = []

        if start_sha and end_sha and start_sha != end_sha:
            try:
                diff_result = await coderecon.semantic_diff(
                    repo_name,
                    base=start_sha,
                    target=end_sha,
                    worktree=job.worktree_path,
                )
                changes = _build_structural_changes(diff_result.structural_changes)
            except Exception:
                log.debug("multi_session_diff_failed", job_id=job_id, session=sess_num, exc_info=True)

        # Direction change detection (§10.4)
        current_added = {c.symbol for c in changes if c.kind == "added" and c.symbol}
        current_modified = {c.symbol for c in changes if c.kind == "modified" and c.symbol}
        overlap = prev_added_symbols & current_modified
        if overlap and sess_num > 1:
            direction_changes.append(
                {
                    "session": sess_num,
                    "detail": f"Session {sess_num} modified {len(overlap)} symbol(s) added by Session {sess_num - 1}",
                    "symbols": sorted(overlap)[:10],
                }
            )
            warnings.append(
                {
                    "type": "direction_change",
                    "detail": f"Modified {len(overlap)} symbols from previous session",
                }
            )

        # Messy session warning (§10.6) — touches 3+ communities
        files_written: set[str] = set()
        for step in sess_steps:
            if step.files_written:
                with contextlib.suppress(ValueError, TypeError):
                    files_written.update(json.loads(step.files_written))
        if len(files_written) >= 3:
            try:
                communities = await coderecon.graph_communities(repo_name, worktree=job.worktree_path)
                file_communities: set[int] = set()
                for comm in communities.communities:
                    if files_written & set(comm.members):
                        file_communities.add(comm.community_id)
                if len(file_communities) >= 3:
                    warnings.append(
                        {
                            "type": "messy_session",
                            "detail": f"Session spans {len(file_communities)} unrelated module communities",
                            "communities": sorted(file_communities),
                        }
                    )
            except Exception:
                pass

        # Compute session risk (average of change risks)
        risk = sum(c.risk for c in changes) / max(1, len(changes)) if changes else 0.0

        segments.append(
            SessionSegment(
                session_number=sess_num,
                start_sha=start_sha,
                end_sha=end_sha,
                changes=changes,
                risk=round(risk, 2),
                warnings=warnings,
            )
        )

        # Track added symbols for next session's direction change detection
        prev_added_symbols = current_added

    return MultiSessionResponse(
        job_id=job_id,
        sessions=segments,
        direction_changes=direction_changes,
    )


# -- Impact graph drill-down (§9.5) -------------------------------------------

_IMPACT_TIER_MAP = {"high": "verified", "medium": "inferred", "unknown": "unverified"}


def _map_impact_tier(raw: str) -> str:
    return _IMPACT_TIER_MAP.get(raw, "unverified")


@router.get("/jobs/{job_id}/impact-graph/{symbol}", response_model=ImpactGraphResponse)
async def get_impact_graph(
    job_id: str,
    symbol: str,
    svc: FromDishka[JobService],
    coderecon: FromDishka[CodeReconService],
    step_repo: FromDishka[StepRepository],
) -> ImpactGraphResponse:
    """Return reference/caller graph for a symbol in the job's worktree.

    Uses ReviewKit.impact() when available; returns available=False otherwise.
    """
    job = await svc.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    if not coderecon.available or not job.repo:
        return ImpactGraphResponse(job_id=job_id, target=symbol, available=False)

    # Cache keyed on latest step SHA — invalidates when worktree advances.
    sha = await _latest_end_sha(step_repo, job_id)
    cache_key = f"impact:{symbol}"
    cached: ImpactGraphResponse | None = _cache_get(job_id, cache_key, sha)
    if cached is not None:
        return cached

    try:
        repo_name = await _ensure_repo_and_worktree(coderecon, job.repo, job.worktree_path or job.repo)
        result = await coderecon.impact(repo_name, target=symbol, worktree=job.worktree_path or job.repo)
    except Exception:
        return ImpactGraphResponse(job_id=job_id, target=symbol, available=False)

    refs: list[ImpactReference] = []
    for defn in getattr(result, "definition_sites", []):
        refs.append(
            ImpactReference(
                symbol=getattr(defn, "name", ""),
                file=getattr(defn, "file", ""),
                line=getattr(defn, "line", None),
                tier="verified",
                is_test="test" in getattr(defn, "file", "").lower(),
                raw_tier="definition",
                covered=getattr(defn, "covered", None),
                test_passed=getattr(defn, "test_passed", None),
                covering_test_ids=getattr(defn, "covering_test_ids", None) or [],
                stale=getattr(defn, "stale", None),
            )
        )
    for ref in getattr(result, "references", []):
        refs.append(
            ImpactReference(
                symbol=getattr(ref, "name", ""),
                file=getattr(ref, "file", ""),
                line=getattr(ref, "line", None),
                tier=_map_impact_tier(getattr(ref, "certainty", "unknown")),
                is_test="test" in getattr(ref, "file", "").lower(),
                raw_tier=getattr(ref, "certainty", "unknown"),
                covered=getattr(ref, "covered", None),
                test_passed=getattr(ref, "test_passed", None),
                covering_test_ids=getattr(ref, "covering_test_ids", None) or [],
                stale=getattr(ref, "stale", None),
            )
        )
    for imp in getattr(result, "import_sites", []):
        refs.append(
            ImpactReference(
                symbol=getattr(imp, "name", ""),
                file=getattr(imp, "file", ""),
                line=getattr(imp, "line", None),
                tier="inferred",
                is_test="test" in getattr(imp, "file", "").lower(),
                raw_tier="import",
                covered=getattr(imp, "covered", None),
                test_passed=getattr(imp, "test_passed", None),
                covering_test_ids=getattr(imp, "covering_test_ids", None) or [],
                stale=getattr(imp, "stale", None),
            )
        )

    files_affected = len({r.file for r in refs})

    fail_count = getattr(result, "fail_count", 0) or 0
    uncovered_count = getattr(result, "uncovered_count", 0) or 0

    response = ImpactGraphResponse(
        job_id=job_id,
        target=symbol,
        available=True,
        total_references=len(refs),
        files_affected=files_affected,
        summary=f"{len(refs)} references across {files_affected} files",
        references=refs,
        fail_count=fail_count,
        uncovered_count=uncovered_count,
    )
    _cache_put(job_id, cache_key, sha, response)
    return response


@router.post("/jobs/{job_id}/impact-graph-batch", response_model=ImpactGraphBatchResponse)
async def get_impact_graph_batch(
    job_id: str,
    body: ImpactGraphBatchRequest,
    svc: FromDishka[JobService],
    coderecon: FromDishka[CodeReconService],
    step_repo: FromDishka[StepRepository],
) -> ImpactGraphBatchResponse:
    """Return impact graphs for multiple symbols in a single request."""
    job = await svc.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    results: dict[str, ImpactGraphResponse] = {}

    if not coderecon.available or not job.repo:
        for symbol in body.symbols:
            results[symbol] = ImpactGraphResponse(job_id=job_id, target=symbol, available=False)
        return ImpactGraphBatchResponse(job_id=job_id, results=results)

    sha = await _latest_end_sha(step_repo, job_id)

    for symbol in body.symbols:
        cache_key = f"impact:{symbol}"
        cached: ImpactGraphResponse | None = _cache_get(job_id, cache_key, sha)
        if cached is not None:
            results[symbol] = cached
            continue

        try:
            repo_name = await _ensure_repo_and_worktree(coderecon, job.repo, job.worktree_path or job.repo)
            result = await coderecon.impact(repo_name, target=symbol, worktree=job.worktree_path or job.repo)
        except Exception:
            results[symbol] = ImpactGraphResponse(job_id=job_id, target=symbol, available=False)
            continue

        refs: list[ImpactReference] = []
        for defn in getattr(result, "definition_sites", []):
            refs.append(
                ImpactReference(
                    symbol=getattr(defn, "name", ""),
                    file=getattr(defn, "file", ""),
                    line=getattr(defn, "line", None),
                    tier="verified",
                    is_test="test" in getattr(defn, "file", "").lower(),
                    raw_tier="definition",
                    covered=getattr(defn, "covered", None),
                    test_passed=getattr(defn, "test_passed", None),
                    covering_test_ids=getattr(defn, "covering_test_ids", None) or [],
                    stale=getattr(defn, "stale", None),
                )
            )
        for ref in getattr(result, "references", []):
            refs.append(
                ImpactReference(
                    symbol=getattr(ref, "name", ""),
                    file=getattr(ref, "file", ""),
                    line=getattr(ref, "line", None),
                    tier=_map_impact_tier(getattr(ref, "certainty", "unknown")),
                    is_test="test" in getattr(ref, "file", "").lower(),
                    raw_tier=getattr(ref, "certainty", "unknown"),
                    covered=getattr(ref, "covered", None),
                    test_passed=getattr(ref, "test_passed", None),
                    covering_test_ids=getattr(ref, "covering_test_ids", None) or [],
                    stale=getattr(ref, "stale", None),
                )
            )
        for imp in getattr(result, "import_sites", []):
            refs.append(
                ImpactReference(
                    symbol=getattr(imp, "name", ""),
                    file=getattr(imp, "file", ""),
                    line=getattr(imp, "line", None),
                    tier="inferred",
                    is_test="test" in getattr(imp, "file", "").lower(),
                    raw_tier="import",
                    covered=getattr(imp, "covered", None),
                    test_passed=getattr(imp, "test_passed", None),
                    covering_test_ids=getattr(imp, "covering_test_ids", None) or [],
                    stale=getattr(imp, "stale", None),
                )
            )

        files_affected = len({r.file for r in refs})
        fail_count = getattr(result, "fail_count", 0) or 0
        uncovered_count = getattr(result, "uncovered_count", 0) or 0

        resp = ImpactGraphResponse(
            job_id=job_id,
            target=symbol,
            available=True,
            total_references=len(refs),
            files_affected=files_affected,
            summary=f"{len(refs)} references across {files_affected} files",
            references=refs,
            fail_count=fail_count,
            uncovered_count=uncovered_count,
        )
        _cache_put(job_id, cache_key, sha, resp)
        results[symbol] = resp

    return ImpactGraphBatchResponse(job_id=job_id, results=results)


# -- Community clustering view (§9.7) -----------------------------------------


@router.get("/jobs/{job_id}/communities", response_model=CommunitiesResponse)
async def get_job_communities(
    job_id: str,
    svc: FromDishka[JobService],
    coderecon: FromDishka[CodeReconService],
    step_repo: FromDishka[StepRepository],
) -> CommunitiesResponse:
    """Return community-grouped structural changes for a job.

    Groups changes by module community so reviewers can see which logical
    areas of the codebase are affected.
    """
    job = await svc.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    if not coderecon.available or not job.repo or not job.worktree_path:
        return CommunitiesResponse(job_id=job_id, available=False)

    # Cache check
    sha = await _latest_end_sha(step_repo, job_id)
    cached: CommunitiesResponse | None = _cache_get(job_id, "communities", sha)
    if cached is not None:
        return cached

    try:
        repo_name = await _ensure_repo_and_worktree(coderecon, job.repo, job.worktree_path)
        diff_result = await coderecon.semantic_diff(
            repo_name,
            base=job.base_ref or "HEAD",
            worktree=job.worktree_path,
        )
        communities = await coderecon.graph_communities(repo_name, worktree=job.worktree_path)
    except Exception:
        log.warning("communities_failed", job_id=job_id, exc_info=True)
        return CommunitiesResponse(job_id=job_id, available=False)

    changes = _build_structural_changes(diff_result.structural_changes)

    # Map files to communities
    file_to_community: dict[str, str] = {}
    for comm in communities.communities:
        cname = str(comm.community_id)
        for member in comm.members:
            file_to_community[member] = cname

    # Group changes by community
    grouped: dict[str, list[dict[str, Any]]] = {}
    unclustered: list[dict[str, Any]] = []
    for ch in changes:
        comm_name = file_to_community.get(ch.file)
        change_dict = ch.model_dump(by_alias=True)
        if comm_name:
            grouped.setdefault(comm_name, []).append(change_dict)
        else:
            unclustered.append(change_dict)

    result = CommunitiesResponse(
        job_id=job_id,
        communities=[
            CommunityGroup(
                name=name,
                changes=items,
                total_risk=round(sum(i.get("risk", 0) for i in items), 2),
            )
            for name, items in sorted(grouped.items(), key=lambda kv: -sum(i.get("risk", 0) for i in kv[1]))
        ],
        unclustered=unclustered,
    )
    _cache_put(job_id, "communities", sha, result)
    return result


# -- Review story artifact (§11) ----------------------------------------------


@router.get("/jobs/{job_id}/review-story", response_model=ReviewStoryResponse)
async def get_review_story(
    job_id: str,
    svc: FromDishka[JobService],
    coderecon: FromDishka[CodeReconService],
    step_repo: FromDishka[StepRepository],
) -> ReviewStoryResponse:
    """Generate a structured review story artifact (§11).

    Returns a structured document with sections: attention_required,
    structural_concerns, what_changed, what_added, session_history, verdict.
    Each section is populated from structural diff data.
    """
    job = await svc.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    if not coderecon.available or not job.repo or not job.worktree_path:
        return ReviewStoryResponse(job_id=job_id, available=False)

    sha = await _latest_end_sha(step_repo, job_id)
    cached: ReviewStoryResponse | None = _cache_get(job_id, "review-story", sha)
    if cached is not None:
        return cached

    result = await _generate_review_story(job_id, job, coderecon)
    _cache_put(job_id, "review-story", sha, result)
    return result


async def _generate_review_story(
    job_id: str,
    job: Any,
    coderecon: CodeReconService,
) -> ReviewStoryResponse:
    """Core review story generation — reusable from endpoint and subscriber.

    Applies the full §11 pipeline: edge-case extraction, density classification,
    aggregation when over cognitive budget, and community rollups.
    """
    from backend.services.story.review import classify_story

    if not coderecon.available or not job.repo or not job.worktree_path:
        return ReviewStoryResponse(job_id=job_id, available=False)

    try:
        repo_name = await _ensure_repo_and_worktree(coderecon, job.repo, job.worktree_path)
        diff_result = await coderecon.semantic_diff(
            repo_name,
            base=job.base_ref or "HEAD",
            worktree=job.worktree_path,
        )
    except Exception:
        return ReviewStoryResponse(job_id=job_id, available=False)

    changes = _build_structural_changes(diff_result.structural_changes)

    # Check for cycles
    has_new_cycles = False
    new_cycles: list[list[str]] = []
    try:
        worktree_cycles = await coderecon.graph_cycles(repo_name, worktree=job.worktree_path)
        if worktree_cycles.cycles:
            base_cycles = await coderecon.graph_cycles(repo_name, worktree="main")
            base_keys = {c.nodes for c in base_cycles.cycles}
            for c in worktree_cycles.cycles:
                if c.nodes not in base_keys:
                    has_new_cycles = True
                    new_cycles.append(sorted(c.nodes))
    except Exception:
        pass

    # Build file → community map for aggregation
    file_to_community: dict[str, str] = {}
    try:
        communities = await coderecon.graph_communities(repo_name, worktree=job.worktree_path)
        for comm in communities.communities:
            comm_name = str(comm.community_id)
            for member in comm.members:
                file_to_community[member] = comm_name
    except Exception:
        pass

    # Full §11 classification pipeline
    classification = classify_story(changes, file_to_community or None)
    remaining = classification.get("remaining_changes", changes)
    edge_cases = classification.get("edge_cases", [])
    collapsed = classification.get("collapsed", False)
    community_rollups = classification.get("community_rollups", [])
    pattern_groups = classification.get("pattern_groups", [])
    density_map = classification.get("density_map", {})

    # Categorize remaining changes (edge cases already extracted)
    breaking = [c for c in remaining if c.category == "breaking"]
    body = [c for c in remaining if c.category == "body"]
    additive = [c for c in remaining if c.category == "additive"]
    non_structural = [c for c in remaining if c.category == "non-structural"]

    # Also count edge-case files as non-structural
    edge_file_count = sum(len(e.get("files", [])) for e in edge_cases)

    # Attention required — breaking changes with full context (capped at 5)
    attention_items = []
    for ch in sorted(breaking, key=lambda c: -c.risk)[:_ATTENTION_CAP]:
        attention_items.append(
            {
                "symbol": ch.symbol,
                "file": ch.file,
                "risk": ch.risk,
                "refCount": ch.ref_count,
                "refTiers": ch.ref_tiers,
                "testFiles": ch.test_files,
                "summary": ch.summary,
                "density": density_map.get(ch.file + "::" + (ch.symbol or ""), "full"),
            }
        )
    # If more breaking changes exist, note the overflow
    if len(breaking) > _ATTENTION_CAP:
        attention_items.append(
            {
                "symbol": None,
                "summary": f"+{len(breaking) - _ATTENTION_CAP} more breaking change(s)",
                "overflow": True,
            }
        )

    # Structural concerns — cycles, unknown refs
    concerns: list[dict[str, Any]] = []
    if has_new_cycles:
        concerns.append(
            {
                "type": "new_cycles",
                "detail": f"{len(new_cycles)} new dependency cycle(s) introduced",
                "cycles": new_cycles[:3],
            }
        )
    unverified_count = sum(1 for c in remaining if c.ref_tiers.get("unverified", 0) > 0)
    if unverified_count:
        concerns.append(
            {
                "type": "unverified_references",
                "detail": f"{unverified_count} change(s) have unverified callers",
            }
        )

    # What changed — body changes, use community rollup when over cap
    what_changed: list[dict[str, Any]]
    if community_rollups:
        # Over budget → show rollups instead of individual items
        what_changed = [
            {
                "symbol": r["name"],
                "summary": r["summary"],
                "risk": r["highest_risk"],
                "community": True,
                "changeCount": r["change_count"],
            }
            for r in community_rollups
        ]
    else:
        what_changed = [
            {
                "symbol": c.symbol,
                "file": c.file,
                "risk": c.risk,
                "summary": c.summary,
                "density": density_map.get(c.file + "::" + (c.symbol or ""), "summary"),
            }
            for c in sorted(body, key=lambda c: -c.risk)[:_BODY_CAP]
        ]
        if len(body) > _BODY_CAP:
            what_changed.append(
                {
                    "symbol": None,
                    "summary": f"+{len(body) - _BODY_CAP} more body change(s)",
                    "overflow": True,
                }
            )

    # What was added (capped at 7)
    what_added = [
        {
            "symbol": c.symbol,
            "file": c.file,
            "summary": c.summary,
            "density": density_map.get(c.file + "::" + (c.symbol or ""), "summary"),
        }
        for c in additive[:_ADDITIVE_CAP]
    ]
    if len(additive) > _ADDITIVE_CAP:
        what_added.append(
            {
                "symbol": None,
                "summary": f"+{len(additive) - _ADDITIVE_CAP} more addition(s)",
                "overflow": True,
            }
        )

    # Verdict
    confidence = _compute_merge_confidence(changes, has_new_cycles=has_new_cycles)
    blockers: list[str] = []
    if has_new_cycles:
        blockers.append("New dependency cycles detected")
    if any(c.ref_tiers.get("unverified", 0) > 0 and c.category == "breaking" for c in changes):
        blockers.append("Breaking changes with unverified callers")

    # Edge-case schemas
    from backend.models.api_schemas import (
        CommunityRollupSchema,
        EdgeCaseBlockSchema,
        PatternGroupSchema,
    )

    edge_schemas = [EdgeCaseBlockSchema(**e) for e in edge_cases]
    rollup_schemas = [CommunityRollupSchema(**r) for r in community_rollups]
    pattern_schemas = [PatternGroupSchema(**p) for p in pattern_groups]

    return ReviewStoryResponse(
        job_id=job_id,
        available=True,
        collapsed=collapsed,
        header=ReviewStoryHeader(
            title=job.title or job.prompt[:60],
            file_count=len({c.file for c in changes}),
            breaking_count=len(breaking),
            merge_confidence=confidence,
        ),
        attention_required=attention_items,
        structural_concerns=concerns,
        what_changed=what_changed,
        what_added=what_added,
        non_structural_count=len(non_structural) + edge_file_count,
        edge_cases=edge_schemas,
        community_rollups=rollup_schemas,
        pattern_groups=pattern_schemas,
        verdict=ReviewStoryVerdict(
            confidence=confidence,
            blockers=blockers,
            summary=(
                "No structural concerns — safe to merge."
                if confidence == "HIGH" and not blockers
                else f"{len(blockers)} blocker(s) require attention before merge."
                if blockers
                else "Some structural uncertainty — review recommended."
            ),
        ),
    )


# ---------------------------------------------------------------------------
# Motivations endpoint (job-level)
# ---------------------------------------------------------------------------


@router.get("/jobs/{job_id}/motivations", response_model=JobMotivationsResponse)
async def get_job_motivations(
    job_id: str,
    svc: FromDishka[JobService],
    spans_repo: FromDishka[TelemetrySpansRepository],
) -> JobMotivationsResponse:
    """Return all motivation annotations for a job's changed files."""
    job = await svc.get_job(job_id)

    # Telemetry stores absolute paths; the diff API uses repo-relative paths.
    # Compute the prefix to strip so keys align with the diff contract.
    wt_prefix = ((job.worktree_path or job.repo or "") + "/").replace("//", "/")
    repo_prefix = ((job.repo or "") + "/").replace("//", "/")

    spans = await spans_repo.motivated_spans_for_job(job_id=job_id)
    file_motivations: dict[str, FileMotivation] = {}
    hunk_motivations: dict[str, HunkMotivation] = {}

    for span in spans:
        target = span.get("tool_target", "")
        summary = span.get("motivation_summary", "")
        if not target or not summary:
            continue

        # Normalize to relative path — spans created before the worktree existed
        # store repo-absolute paths, so try both prefixes.
        if target.startswith(wt_prefix):
            rel_target = target[len(wt_prefix) :]
        elif target.startswith(repo_prefix):
            rel_target = target[len(repo_prefix) :]
        else:
            rel_target = target

        # Parse motivation_summary as "Title: rest" or just use as why
        if ": " in summary and len(summary.split(": ", 1)[0]) < 80:
            title, why = summary.split(": ", 1)
        else:
            title = ""
            why = summary

        file_motivations[rel_target] = FileMotivation(title=title, why=why)

        # Parse edit_motivations JSON if present
        edit_motivations_raw = span.get("edit_motivations")
        if edit_motivations_raw:
            import json as _json

            try:
                edits = (
                    _json.loads(edit_motivations_raw) if isinstance(edit_motivations_raw, str) else edit_motivations_raw
                )
                for i, edit in enumerate(edits if isinstance(edits, list) else []):
                    key = f"{rel_target}:{i}"
                    # The stored JSON uses "summary" (not "title"/"why").
                    # Split first line as title, remainder as why.
                    em_summary = edit.get("summary", "")
                    em_lines = em_summary.strip().split("\n", 1)
                    em_title = em_lines[0].strip()
                    em_why = em_lines[1].strip() if len(em_lines) > 1 else em_summary
                    hunk_motivations[key] = HunkMotivation(
                        edit_key=edit.get("edit_key", key),
                        title=em_title,
                        why=em_why,
                    )
            except (ValueError, TypeError):
                pass

    return JobMotivationsResponse(
        job_id=job_id,
        file_motivations=file_motivations,
        hunk_motivations=hunk_motivations,
    )


# ---------------------------------------------------------------------------
# Coverage / Blast Radius endpoints
# ---------------------------------------------------------------------------


@router.get("/jobs/{job_id}/covering-tests", response_model=CoveringTestsResponse)
async def get_job_covering_tests(
    job_id: str,
    svc: FromDishka[JobService],
    coderecon: FromDishka[CodeReconService],
    file_path: Annotated[str, Query(description="Relative file path to query covering tests for")],
) -> CoveringTestsResponse:
    """Return tests that cover definitions in the given file for a job's repo."""
    job = await svc.get_job(job_id)
    if not coderecon.available or not job.repo or not job.worktree_path:
        return CoveringTestsResponse(job_id=job_id, file_path=file_path, available=False)

    try:
        repo_name = await _ensure_repo_and_worktree(coderecon, job.repo, job.worktree_path)
        result = await coderecon.covering_tests(
            repo_name,
            file_path,
            worktree=job.worktree_path,
        )
    except Exception:
        log.warning("covering_tests_failed", job_id=job_id, file_path=file_path, exc_info=True)
        return CoveringTestsResponse(job_id=job_id, file_path=file_path, available=False)

    tests_by_def = getattr(result, "tests_by_def", result)
    symbols: dict[str, list[CoveringTestCandidate]] = {}
    for symbol, candidates in tests_by_def.items():
        symbols[symbol] = [
            CoveringTestCandidate(
                test_id=c.test_id,
                source=c.source,
                distance=c.distance,
                confidence=c.confidence,
                reason=c.reason,
            )
            for c in candidates
        ]

    return CoveringTestsResponse(
        job_id=job_id,
        file_path=file_path,
        symbols=symbols,
    )


@router.get("/jobs/{job_id}/line-coverage", response_model=LineCoverageResponse)
async def get_job_line_coverage(
    job_id: str,
    svc: FromDishka[JobService],
    coderecon: FromDishka[CodeReconService],
    file_path: Annotated[str, Query(description="Relative file path to query line coverage for")],
    start_line: Annotated[int | None, Query(description="Optional start of line range")] = None,
    end_line: Annotated[int | None, Query(description="Optional end of line range")] = None,
) -> LineCoverageResponse:
    """Return per-line coverage data for gutter dot rendering in the layered diff view."""
    job = await svc.get_job(job_id)
    if not coderecon.available or not job.repo or not job.worktree_path:
        return LineCoverageResponse(job_id=job_id, file_path=file_path, available=False)

    line_range = (start_line, end_line) if start_line is not None and end_line is not None else None

    try:
        repo_name = await _ensure_repo_and_worktree(coderecon, job.repo, job.worktree_path)
        result = await coderecon.line_coverage(
            repo_name,
            file_path,
            worktree=job.worktree_path,
            line_range=line_range,
            include_tests=True,
        )
    except Exception:
        log.warning("line_coverage_failed", job_id=job_id, file_path=file_path, exc_info=True)
        return LineCoverageResponse(job_id=job_id, file_path=file_path, available=False)

    # Map tests_by_line from {int: [str]} to {str: [LineCoverageTestInfo]}
    tests_by_line: dict[str, list[LineCoverageTestInfo]] = {}
    for line_no, test_names in (result.tests_by_line or {}).items():
        tests_by_line[str(line_no)] = [
            LineCoverageTestInfo(name=name, file="", line=0, status="pass") for name in test_names
        ]

    return LineCoverageResponse(
        job_id=job_id,
        file_path=file_path,
        covered_lines=result.covered_lines,
        uncovered_lines=result.uncovered_lines,
        total_instrumented=result.total_instrumented,
        line_rate=result.line_rate,
        tests_by_line=tests_by_line,
    )


@router.get("/jobs/{job_id}/blast-radius", response_model=BlastRadiusResponse)
async def get_job_blast_radius(
    job_id: str,
    svc: FromDishka[JobService],
    coderecon: FromDishka[CodeReconService],
) -> BlastRadiusResponse:
    """Return blast radius analysis for a job's changed files."""
    job = await svc.get_job(job_id)
    if not coderecon.available or not job.repo or not job.worktree_path:
        return BlastRadiusResponse(job_id=job_id, available=False)

    # Get changed files from semantic diff
    try:
        repo_name = await _ensure_repo_and_worktree(coderecon, job.repo, job.worktree_path)
        diff_result = await coderecon.semantic_diff(
            repo_name,
            base=job.base_ref or "HEAD",
            worktree=job.worktree_path,
        )
        changed_files = list({c.path for c in diff_result.structural_changes})
    except Exception:
        log.warning("blast_radius_diff_failed", job_id=job_id, exc_info=True)
        return BlastRadiusResponse(job_id=job_id, available=False)

    if not changed_files:
        return BlastRadiusResponse(job_id=job_id, has_coverage_data=False)

    try:
        result = await coderecon.blast_radius(
            repo_name,
            changed_files,
            worktree=job.worktree_path,
        )
    except Exception:
        log.warning("blast_radius_failed", job_id=job_id, exc_info=True)
        return BlastRadiusResponse(job_id=job_id, available=False)

    candidates = [
        BlastRadiusCandidate(
            test_id=c.test_id,
            source=c.source,
            distance=c.distance,
            confidence=c.confidence,
            reason=c.reason,
        )
        for c in result.candidates
    ]

    return BlastRadiusResponse(
        job_id=job_id,
        has_coverage_data=result.has_coverage_data,
        candidates=candidates,
        coverage_gaps=result.coverage_gaps,
    )
