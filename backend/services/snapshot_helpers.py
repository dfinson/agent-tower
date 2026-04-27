"""Shared snapshot assembly — single source of truth for snapshot hydration.

Both ``/jobs/{id}/snapshot`` and ``/share/{token}/snapshot`` build the same
response shape.  This module houses the common building blocks so the route
handlers stay thin auth + delegation wrappers.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

from backend.models.api_schemas import (
    ApprovalResponse,
    DiffFileModel,
    JobSnapshotResponse,
    LogLinePayload,
    PlanStepPayload,
    ProgressHeadlinePayload,
    TranscriptPayload,
    TurnSummaryPayload,
)
from backend.models.domain import JobState
from backend.models.events import DomainEventKind
from backend.persistence.approval_repo import ApprovalRepository
from backend.services.diff_service import DiffService
from backend.services.git_service import GitError
from backend.services.job_service import JobService, ProgressPreview
from backend.services.step_tracker import hydrate_plan_steps

# Event query limits — bound the maximum rows returned from the event store.
# Default (2000) covers a typical 1–2 hour session; ceiling (5000)
# accommodates long-running jobs.  Plan/step events use the ceiling because
# each event is small and completeness matters for the UI step tracker.
EVENT_QUERY_DEFAULT = 2000
EVENT_QUERY_CEILING = 5000
# Progress headlines are short one-line status updates — 200 covers even
# long sessions while keeping the snapshot response compact.
HEADLINE_QUERY_LIMIT = 200


# ── internal helpers ────────────────────────────────────────────────────────


def _build_logs(log_events: list[Any]) -> list[LogLinePayload]:
    return [
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


def _build_transcript(
    transcript_events: list[Any],
    summary_events: list[Any],
    resolve_display: Any,
    resolve_display_full: Any,
    *,
    filter_deltas: bool,
) -> list[TranscriptPayload]:
    group_summary_by_turn: dict[str, str] = {
        str(ev.payload.get("turn_id")): str(ev.payload.get("summary"))
        for ev in summary_events
        if ev.payload.get("turn_id") and ev.payload.get("summary")
    }
    result = [
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
            tool_display=resolve_display(e.payload),
            tool_display_full=resolve_display_full(e.payload),
            tool_duration_ms=e.payload.get("tool_duration_ms"),
            tool_group_summary=group_summary_by_turn.get(e.payload.get("turn_id") or ""),
            tool_visibility=e.payload.get("tool_visibility"),
            step_id=e.payload.get("step_id"),
            step_number=e.payload.get("step_number"),
        )
        for e in transcript_events
        if not filter_deltas
        or e.payload.get("role", "agent") not in ("tool_output_delta", "reasoning_delta")
    ]
    return result


def _apply_reassignments(
    transcript: list[TranscriptPayload],
    reassign_events: list[Any],
) -> None:
    if not reassign_events:
        return
    reassign_map: dict[str, tuple[str, str]] = {}
    for ev in reassign_events:
        tid = ev.payload.get("turn_id", "")
        old_sid = ev.payload.get("old_step_id", "")
        new_sid = ev.payload.get("new_step_id", "")
        if tid and old_sid and new_sid:
            reassign_map[tid] = (old_sid, new_sid)
    if not reassign_map:
        return
    for entry in transcript:
        key = entry.turn_id or ""
        if key in reassign_map:
            old_sid, new_sid = reassign_map[key]
            if entry.step_id == old_sid:
                entry.step_id = new_sid


def _build_timeline(timeline_events: list[Any]) -> list[ProgressHeadlinePayload]:
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
    return milestones


async def _build_diff(
    job: Any,
    svc: JobService,
    diff_service: DiffService,
) -> list[DiffFileModel]:
    diff: list[DiffFileModel] = []
    if (
        job.state in (JobState.running, JobState.waiting_for_approval)
        and job.worktree_path
        and job.worktree_path != job.repo
    ):
        with contextlib.suppress(GitError, OSError):
            diff = await diff_service.calculate_diff(job.worktree_path, job.base_ref)
    if not diff:
        diff_events = await svc.list_events_by_job(
            job.id, [DomainEventKind.diff_updated]
        )
        if diff_events:
            raw_files = diff_events[-1].payload.get("changed_files", [])
            diff = [DiffFileModel.model_validate(f) for f in raw_files]
    return diff


async def _build_approvals(
    approval_repo: ApprovalRepository,
    job_id: str,
) -> list[ApprovalResponse]:
    db_approvals = await approval_repo.list_for_job(job_id)
    return [
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


def _build_turn_summaries(
    turn_summary_events: list[Any],
    job_id: str,
    *,
    deduplicate: bool,
) -> list[TurnSummaryPayload]:
    """Build turn summary payloads.

    When *deduplicate* is True, keep only the last event per turn_id but
    preserve the **first** event's ``is_new_activity`` flag (refinement
    re-emits always set it to False).
    """
    if deduplicate:
        first_new: dict[str, bool] = {}
        latest: dict[str, int] = {}
        for idx, ev in enumerate(turn_summary_events):
            tid = ev.payload.get("turn_id", "")
            if tid:
                if tid not in first_new:
                    first_new[tid] = bool(ev.payload.get("is_new_activity", False))
                latest[tid] = idx
        keep_idxs = set(latest.values())
        return [
            TurnSummaryPayload(
                job_id=job_id,
                turn_id=ev.payload.get("turn_id", ""),
                title=ev.payload.get("title", ""),
                activity_id=ev.payload.get("activity_id", ""),
                activity_label=ev.payload.get("activity_label", ""),
                activity_status=ev.payload.get("activity_status", "active"),
                is_new_activity=first_new.get(ev.payload.get("turn_id", ""), False),
            )
            for idx, ev in enumerate(turn_summary_events)
            if idx in keep_idxs and ev.payload.get("turn_id") and ev.payload.get("title")
        ]
    return [
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


# ── public API ──────────────────────────────────────────────────────────────


async def assemble_snapshot(
    *,
    job: Any,
    progress_preview: ProgressPreview | None,
    svc: JobService,
    diff_service: DiffService,
    approval_repo: ApprovalRepository,
    resolve_display: Any,
    resolve_display_full: Any,
    job_to_response: Any,
    filter_transcript_deltas: bool = True,
    detect_plan_generations: bool = True,
    exclude_pending_steps: bool = False,
    deduplicate_turn_summaries: bool = True,
) -> JobSnapshotResponse:
    """Assemble a full job snapshot response.

    Parameters control the behavioural differences between the authenticated
    ``/jobs/{id}/snapshot`` endpoint and the public ``/share/{token}/snapshot``.
    """
    job_id = job.id

    (
        log_events,
        transcript_events,
        timeline_events,
        summary_events,
        step_events,
        reassign_events,
        turn_summary_events,
    ) = await asyncio.gather(
        svc.list_events_by_job(job_id, [DomainEventKind.log_line_emitted], limit=EVENT_QUERY_DEFAULT),
        svc.list_events_by_job(job_id, [DomainEventKind.transcript_updated], limit=EVENT_QUERY_DEFAULT),
        svc.list_events_by_job(job_id, [DomainEventKind.progress_headline], limit=HEADLINE_QUERY_LIMIT),
        svc.list_events_by_job(job_id, [DomainEventKind.tool_group_summary], limit=EVENT_QUERY_CEILING),
        svc.list_events_by_job(job_id, [DomainEventKind.plan_step_updated], limit=EVENT_QUERY_CEILING),
        svc.list_events_by_job(job_id, [DomainEventKind.step_entries_reassigned], limit=EVENT_QUERY_CEILING),
        svc.list_events_by_job(job_id, [DomainEventKind.turn_summary], limit=EVENT_QUERY_CEILING),
    )

    logs = _build_logs(log_events)

    transcript = _build_transcript(
        transcript_events,
        summary_events,
        resolve_display,
        resolve_display_full,
        filter_deltas=filter_transcript_deltas,
    )
    _apply_reassignments(transcript, reassign_events)

    timeline = _build_timeline(timeline_events)

    diff = await _build_diff(job, svc, diff_service)

    approvals = await _build_approvals(approval_repo, job_id)

    plan_steps = [
        PlanStepPayload(**p)
        for p in hydrate_plan_steps(
            step_events,
            job_id,
            detect_generations=detect_plan_generations,
            exclude_pending=exclude_pending_steps,
        )
    ]

    turn_summaries = _build_turn_summaries(
        turn_summary_events,
        job_id,
        deduplicate=deduplicate_turn_summaries,
    )

    return JobSnapshotResponse(
        job=job_to_response(job, progress_preview),
        logs=logs,
        transcript=transcript,
        diff=diff,
        approvals=approvals,
        timeline=timeline,
        steps=plan_steps,
        turn_summaries=turn_summaries,
    )
