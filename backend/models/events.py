"""Canonical internal event model."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any, TypedDict

from traceforge.types import EventMetadata, SessionEvent

if TYPE_CHECKING:
    from backend.models.api_schemas import ExecutionPhase
    from backend.models.domain import (
        ApprovalResolution,
        GitMergeOutcome,
        JobState,
        Resolution,
    )

__all__ = [
    "TRANSCRIPT_KINDS",
    "EventKind",
    "EventMetadata",
    "EventPayload",
    "SessionEvent",
    "new_event",
    "transcript_kind_for_role",
]


class EventKind(StrEnum):
    """CodePlane control-plane event kinds as open dotted TraceForge kinds.

    These are CodePlane's own kinds expressed in TraceForge's open dotted-string
    ``kind`` grammar. ``traceforge.SessionEvent.kind`` is a free-form string; this
    enum is just symbol-safe named constants for the kinds CodePlane emits — not a
    translation layer. The wire/persistence carry these dotted values verbatim.
    """

    # --- Job lifecycle ---
    job_created = "job.created"
    job_setup_progress = "job.setup_progress"
    workspace_prepared = "workspace.prepared"
    agent_session_started = "agent.session_started"
    # --- Transcript family (one CP transcript event per agent role) ---
    message_user = "message.user"
    message_assistant = "message.assistant"
    message_delta = "message.delta"
    tool_call_started = "tool.call.started"
    tool_call_completed = "tool.call.completed"
    tool_call_failed = "tool.call.failed"
    # --- Logs / diffs ---
    log_line_emitted = "log"
    diff_updated = "diff.updated"
    # --- Approvals (permissions) ---
    approval_requested = "permission.requested"
    approval_resolved = "permission.resolved"
    batch_approval_requested = "permission.batch.requested"
    batch_approval_resolved = "permission.batch.resolved"
    # --- Job state / outcomes ---
    job_review = "job.review"
    job_completed = "job.completed"
    job_failed = "job.failed"
    job_canceled = "job.canceled"
    job_state_changed = "job.state_changed"
    session_heartbeat = "session.heartbeat"
    merge_completed = "merge.completed"
    merge_conflict = "merge.conflict"
    session_resumed = "session.resumed"
    job_resolved = "job.resolved"
    job_archived = "job.archived"
    job_title_updated = "job.title_updated"
    progress_headline = "progress.headline"
    model_downgraded = "model.downgraded"
    tool_group_summary = "tool.group_summary"
    agent_plan_updated = "plan.updated"
    execution_phase_changed = "execution.phase_changed"
    telemetry_updated = "telemetry.updated"
    # --- Steps / plan ---
    step_started = "step.started"
    step_completed = "step.completed"
    step_title_generated = "step.title_generated"
    step_group_updated = "step.group_updated"
    plan_step_updated = "plan.step_updated"
    step_entries_reassigned = "step.entries_reassigned"
    turn_summary = "turn.summary"
    action_classified = "action.classified"
    policy_settings_changed = "policy.settings_changed"
    # --- Repo index ---
    repo_index_progress = "repo.index_progress"
    repo_index_complete = "repo.index_complete"
    # --- Structural health ---
    structural_warning = "structural.warning"
    stall_detected = "stall.detected"
    # --- Monitors ---
    monitor_approved = "monitor.approved"
    monitor_rejected = "monitor.rejected"
    monitor_escalated = "monitor.escalated"
    # --- Sidecars ---
    sidecar_transcript = "sidecar.transcript"
    sidecar_agent_message = "sidecar.agent_message"
    sidecar_gate_verdict = "sidecar.gate_verdict"
    sidecar_metadata_update = "sidecar.metadata_update"
    # --- Unified secondary session events (preflight, sidecars, monitors) ---
    secondary_session_started = "secondary_session.started"
    secondary_session_entry = "secondary_session.entry"
    secondary_session_completed = "secondary_session.completed"
    # --- Context handoff — emitted when context crosses a session boundary ---
    context_handoff = "context.handoff"
    job_mode_changed = "job.mode_changed"


# The transcript family: one CP "transcript" event fans out to a role-specific
# dotted kind. Role is retained in ``payload["role"]`` so consumers that branch
# on role continue to work; kind-level "is this a transcript event" checks use
# this set.
TRANSCRIPT_KINDS: frozenset[EventKind] = frozenset(
    {
        EventKind.message_user,
        EventKind.message_assistant,
        EventKind.message_delta,
        EventKind.tool_call_started,
        EventKind.tool_call_completed,
        EventKind.tool_call_failed,
    }
)


def transcript_kind_for_role(role: str, *, tool_success: bool | None = None) -> EventKind:
    """Map a transcript ``role`` to its dotted CodePlane event kind.

    Roles emitted by the adapters/watchers: ``operator``/``user`` (human input),
    ``agent``/``assistant`` (complete agent message), ``agent_delta`` (streaming
    partial), ``tool_running`` (a tool began — a *real* distinct start signal, so
    ``tool.call.started`` is genuine, not synthesized), ``tool_call`` (a tool
    finished).

    A finished tool fans out on its corrected ``tool_success`` flag: a ``False``
    value yields ``tool.call.failed`` so downstream consumers key off the kind
    rather than re-deriving success from the payload; anything else (including a
    missing flag) yields ``tool.call.completed``.
    """
    if role in ("operator", "user"):
        return EventKind.message_user
    if role in ("agent", "assistant"):
        return EventKind.message_assistant
    if role == "agent_delta":
        return EventKind.message_delta
    if role == "tool_running":
        return EventKind.tool_call_started
    if role == "tool_call":
        if tool_success is False:
            return EventKind.tool_call_failed
        return EventKind.tool_call_completed
    # Unknown roles default to a full assistant message (safest for display).
    return EventKind.message_assistant


# ---------------------------------------------------------------------------
# Typed event payloads
#
# These TypedDicts describe the *most common* payload shapes emitted by the
# service layer and consumed by SSE builders / API endpoints.  They are not
# enforced at publish time (payloads are still plain dicts internally) but
# give type-checkers enough information to validate consumer code.
# ---------------------------------------------------------------------------


class _BasePayload(TypedDict, total=False):
    """Fields injected at runtime by RuntimeService (step tracking, session tagging)."""

    step_id: str | None
    step_number: int | None
    session_number: int
    turn_id: str | None


class JobSetupProgressPayloadDict(_BasePayload, total=False):
    step: str


class JobCanceledPayloadDict(_BasePayload, total=False):
    reason: str


class StepEntriesReassignedPayloadDict(_BasePayload, total=False):
    old_step_id: str
    new_step_id: str


class EmptyPayloadDict(_BasePayload):
    """Payload for events that carry no data (e.g. job_archived)."""


class LogLinePayloadDict(_BasePayload, total=False):
    seq: int
    timestamp: str
    level: str
    message: str
    context: dict[str, Any] | None


class TranscriptPayloadDict(_BasePayload, total=False):
    seq: int
    timestamp: str
    role: str
    content: str
    title: str | None
    tool_name: str | None
    tool_args: str | None
    tool_result: str | None
    tool_success: bool | None
    tool_issue: str | None
    tool_intent: str | None
    tool_title: str | None
    tool_display: str | None
    tool_duration_ms: int | None


class DiffFilePayloadDict(TypedDict, total=False):
    path: str
    status: str
    additions: int
    deletions: int
    hunks: list[dict[str, Any]]
    write_count: int | None
    retry_count: int | None


class DiffPayloadDict(_BasePayload, total=False):
    changed_files: list[DiffFilePayloadDict]


class ApprovalRequestedPayloadDict(_BasePayload, total=False):
    approval_id: str
    description: str
    proposed_action: str | None
    timestamp: str


class ApprovalResolvedPayloadDict(_BasePayload, total=False):
    approval_id: str
    resolution: ApprovalResolution
    timestamp: str


class JobStatePayloadDict(_BasePayload, total=False):
    state: JobState
    new_state: JobState
    previous_state: JobState | None


class JobReviewPayloadDict(_BasePayload, total=False):
    pr_url: str | None
    merge_status: GitMergeOutcome | None
    resolution: Resolution | None
    model_downgraded: bool
    requested_model: str | None
    actual_model: str | None


class JobCompletedPayloadDict(_BasePayload, total=False):
    resolution: Resolution | None
    merge_status: GitMergeOutcome | None
    pr_url: str | None


class JobFailedPayloadDict(_BasePayload, total=False):
    reason: str


class SessionHeartbeatPayloadDict(_BasePayload, total=False):
    session_id: str
    timestamp: str
    last_activity_at: str
    active_tool_name: str
    active_tool_since: str


class MergeCompletedPayloadDict(_BasePayload, total=False):
    branch: str
    base_ref: str
    strategy: str
    timestamp: str


class MergeConflictPayloadDict(_BasePayload, total=False):
    branch: str
    base_ref: str
    conflict_files: list[str]
    fallback: str
    pr_url: str | None
    timestamp: str


class SessionResumedPayloadDict(_BasePayload, total=False):
    timestamp: str


class JobResolvedPayloadDict(_BasePayload, total=False):
    resolution: Resolution
    pr_url: str | None
    conflict_files: list[str] | None
    error: str | None


class JobTitleUpdatedPayloadDict(_BasePayload, total=False):
    title: str | None
    branch: str | None
    description: str | None


class ProgressHeadlinePayloadDict(_BasePayload, total=False):
    headline: str
    headline_past: str
    summary: str
    replaces_count: int


class ModelDowngradedPayloadDict(_BasePayload, total=False):
    requested_model: str
    actual_model: str


class ToolGroupSummaryPayloadDict(_BasePayload, total=False):
    summary: str


class AgentPlanStepDict(TypedDict, total=False):
    label: str
    status: str


class AgentPlanUpdatedPayloadDict(_BasePayload, total=False):
    steps: list[AgentPlanStepDict]


class ExecutionPhasePayloadDict(_BasePayload, total=False):
    phase: ExecutionPhase


class TelemetryUpdatedPayloadDict(_BasePayload, total=False):
    job_id: str
    total_cost_usd: float
    total_tokens: int
    input_tokens: int
    output_tokens: int


class StepStartedPayloadDict(_BasePayload, total=False):
    intent: str
    trigger: str


class StepCompletedPayloadDict(_BasePayload, total=False):
    status: str
    tool_count: int
    duration_ms: int
    has_summary: bool
    agent_message: str | None
    files_read: list[str]
    files_written: list[str]
    tool_names: list[str]
    start_sha: str | None
    end_sha: str | None
    preceding_context: str | None


class StepTitlePayloadDict(_BasePayload, total=False):
    title: str


class PlanStepUpdatedPayloadDict(_BasePayload, total=False):
    plan_step_id: str
    label: str
    summary: str | None
    status: str
    tool_count: int
    files_written: list[str]
    started_at: str | None
    completed_at: str | None
    duration_ms: int | None
    start_sha: str | None
    end_sha: str | None


class TurnSummaryPayloadDict(_BasePayload, total=False):
    title: str
    activity_id: str
    activity_label: str
    activity_status: str  # active | done
    is_new_activity: bool
    plan_item_id: str | None


# Union of all known payload shapes.  Used as the DomainEvent.payload type so
# consumers get useful type information.
EventPayload = (
    LogLinePayloadDict
    | TranscriptPayloadDict
    | DiffPayloadDict
    | ApprovalRequestedPayloadDict
    | ApprovalResolvedPayloadDict
    | JobSetupProgressPayloadDict
    | JobStatePayloadDict
    | JobReviewPayloadDict
    | JobCompletedPayloadDict
    | JobFailedPayloadDict
    | JobCanceledPayloadDict
    | SessionHeartbeatPayloadDict
    | MergeCompletedPayloadDict
    | MergeConflictPayloadDict
    | SessionResumedPayloadDict
    | JobResolvedPayloadDict
    | JobTitleUpdatedPayloadDict
    | ProgressHeadlinePayloadDict
    | ModelDowngradedPayloadDict
    | ToolGroupSummaryPayloadDict
    | AgentPlanUpdatedPayloadDict
    | ExecutionPhasePayloadDict
    | TelemetryUpdatedPayloadDict
    | StepStartedPayloadDict
    | StepCompletedPayloadDict
    | StepTitlePayloadDict
    | PlanStepUpdatedPayloadDict
    | TurnSummaryPayloadDict
    | StepEntriesReassignedPayloadDict
    | EmptyPayloadDict
    | dict[str, Any]
)


def new_event(
    session_id: str | None,
    kind: EventKind | str,
    payload: EventPayload | dict[str, Any],
    *,
    timestamp: datetime | None = None,
    metadata: EventMetadata | None = None,
    sequence: int | None = None,
    event_id: str | None = None,
) -> SessionEvent:
    """Construct a canonical ``traceforge.SessionEvent`` for a CodePlane job.

    Single construction point that replaces the retired ``DomainEvent`` dataclass.
    ``session_id`` carries the CodePlane job id (``""`` for job-less/global events).
    The persisted autoincrement id (the SSE resume cursor, formerly ``DomainEvent.db_id``)
    rides on ``metadata.sequence``. ``timestamp`` and event ``id`` are auto-filled when
    omitted, matching the old ``DomainEvent.for_job`` convenience.
    """
    if metadata is None:
        metadata = EventMetadata(sequence=sequence)
    elif sequence is not None:
        metadata = metadata.model_copy(update={"sequence": sequence})
    fields: dict[str, Any] = {
        "kind": str(kind),
        "session_id": session_id or "",
        "timestamp": timestamp if timestamp is not None else datetime.now(UTC),
        "payload": dict(payload),
        "metadata": metadata,
    }
    if event_id is not None:
        fields["id"] = event_id
    return SessionEvent(**fields)
