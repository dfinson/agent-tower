"""Domain dataclasses and value objects."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any, TypedDict

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from datetime import datetime

    from backend.models.api_schemas import ArtifactType, ExecutionPhase


class JobState(StrEnum):
    preparing = "preparing"
    queued = "queued"
    running = "running"
    waiting_for_approval = "waiting_for_approval"
    review = "review"
    completed = "completed"
    failed = "failed"
    canceled = "canceled"


# Terminal states have no further transitions
TERMINAL_STATES: frozenset[JobState] = frozenset(
    {
        JobState.completed,
        JobState.failed,
        JobState.canceled,
    }
)

# Active states (job is occupying a worktree)
ACTIVE_STATES: frozenset[JobState] = frozenset(
    {
        JobState.preparing,
        JobState.queued,
        JobState.running,
        JobState.waiting_for_approval,
        JobState.review,
    }
)


class Resolution(StrEnum):
    """User-facing disposition of a completed job.

    Distinct from ``Job.merge_status`` which tracks only the *git merge
    operation* outcome.  ``resolution`` captures the *user's decision* about
    what to do with the agent's work after it finishes.
    """

    unresolved = "unresolved"
    merged = "merged"
    pr_created = "pr_created"
    discarded = "discarded"
    conflict = "conflict"


class ApprovalResolution(StrEnum):
    """Outcome of an operator's approval decision."""

    approved = "approved"
    rejected = "rejected"


class GitMergeOutcome(StrEnum):
    """Outcome of the automatic git merge operation after an agent session.

    Distinct from :class:`Resolution` which captures the *user's decision*.
    This enum tracks only the mechanical result of the merge-back attempt.
    """

    not_merged = "not_merged"
    merged = "merged"
    conflict = "conflict"
    pr_created = "pr_created"


# Job state machine — authoritative transition table (see SPEC.md §12.2).
#
#   None ──► preparing ──► queued ──► running ──► review ──► completed
#                │            │          │  ▲        │  ▲        │
#                ▼            ▼          ▼  │        ▼  │        ▼
#             failed      canceled   waiting_for_approval     running
#               │                        │                      │
#               ▼                        ▼                      ▼
#            running                  canceled               running
#
# Terminal states (completed, failed, canceled) allow transition back
# to running for job resumption.
#
# Enforced by validate_state_transition(); all external callers go
# through JobService.transition_state().
_VALID_TRANSITIONS: dict[JobState | None, set[JobState]] = {
    None: {JobState.preparing, JobState.running, JobState.queued},
    JobState.preparing: {JobState.queued, JobState.failed, JobState.canceled},
    JobState.queued: {JobState.running, JobState.canceled},
    JobState.running: {
        JobState.waiting_for_approval,
        JobState.review,
        JobState.failed,
        JobState.canceled,
    },
    JobState.waiting_for_approval: {
        JobState.running,
        JobState.failed,
        JobState.canceled,
    },
    # Review: agent exited cleanly, awaiting operator decision
    JobState.review: {
        JobState.running,  # operator reruns / sends follow-up
        JobState.completed,  # operator resolves (merge, PR, discard)
        JobState.canceled,
    },
    # Terminal states can transition back to running for job resumption
    JobState.completed: {JobState.running},
    JobState.failed: {JobState.running},
    JobState.canceled: {JobState.running},
}


class CodePlaneError(Exception):
    """Base exception for all CodePlane domain errors."""


class ServiceInitError(CodePlaneError):
    """Raised when a service is used before required dependencies are configured."""


class JobNotFoundError(CodePlaneError):
    """Raised when a job ID does not exist."""


class StateConflictError(CodePlaneError):
    """Raised when a job action conflicts with its current state."""


class RepoNotAllowedError(CodePlaneError):
    """Raised when a repo path is not in the allowlist."""


class ApprovalNotFoundError(CodePlaneError):
    """Raised when an approval request is not found."""


class ApprovalAlreadyResolvedError(CodePlaneError):
    """Raised when attempting to resolve an already-resolved approval."""


class SDKModelMismatchError(CodePlaneError):
    """Raised when a model is incompatible with the selected SDK."""


class AgentSDK(StrEnum):
    """Supported agent SDK backends."""

    copilot = "copilot"
    claude = "claude"


class InvalidStateTransitionError(CodePlaneError):
    """Raised when a job state transition is not allowed."""

    def __init__(self, from_state: JobState | None, to_state: JobState) -> None:
        self.from_state = from_state
        self.to_state = to_state
        super().__init__(f"Invalid state transition: {from_state!r} -> {to_state!r}")


def validate_state_transition(from_state: JobState | None, to_state: JobState) -> None:
    """Validate a job state transition. Raises InvalidStateTransitionError if invalid."""
    valid_targets = _VALID_TRANSITIONS.get(from_state, set())
    if to_state not in valid_targets:
        raise InvalidStateTransitionError(from_state, to_state)


class PermissionMode(StrEnum):
    """Controls how the agent adapter handles SDK permission requests.

    full_auto          — Everything auto-approved within worktree. No prompts.
    observe_only       — Allow reads + grep/find. Block all writes/mutations.
    review_and_approve — Always allow read_file. Require approval for
                         shell commands (except grep/find), URL fetches,
                         and any write operations.
    """

    full_auto = "full_auto"
    observe_only = "observe_only"
    review_and_approve = "review_and_approve"

    @classmethod
    def _missing_(cls, value: object) -> PermissionMode | None:
        """Accept legacy names so existing configs and DB rows keep working."""
        import warnings

        legacy = {"auto": cls.full_auto, "read_only": cls.observe_only, "approval_required": cls.review_and_approve}
        if isinstance(value, str):
            result = legacy.get(value)
            if result is not None:
                warnings.warn(
                    f"PermissionMode '{value}' is deprecated, use '{result.value}' instead",
                    DeprecationWarning,
                    stacklevel=2,
                )
            return result
        return None


class Preset(StrEnum):
    """Action policy preset — controls how the policy router classifies agent actions.

    autonomous — Contained actions auto-approved. Non-contained actions gated.
    supervised — Reversible + contained auto-approved. Irreversible or
                 non-contained actions gated.
    strict     — Reversible + contained get checkpointed. Everything else gated.
    """

    autonomous = "autonomous"
    supervised = "supervised"
    strict = "strict"


class SessionEventKind(StrEnum):
    log = "log"
    transcript = "transcript"
    file_changed = "file_changed"
    approval_request = "approval_request"
    model_downgraded = "model_downgraded"
    done = "done"
    error = "error"


# -- Payload TypedDicts per SessionEventKind ----------------------------------


class LogPayload(TypedDict, total=False):
    seq: int
    timestamp: str
    level: str
    message: str


class TranscriptPayload(TypedDict, total=False):
    role: str
    content: str
    turn_id: str
    title: str | None
    tool_name: str
    tool_args: str | None
    tool_result: str | None
    tool_success: bool
    tool_issue: str | None
    tool_intent: str | None
    tool_title: str | None
    tool_display: str | None
    tool_display_full: str | None
    tool_duration_ms: int | None
    tool_visibility: str
    tool_call_id: str


class FileChangedPayload(TypedDict):
    path: str


class ApprovalRequestPayload(TypedDict, total=False):
    description: str
    proposed_action: str | None
    approval_id: str
    requires_explicit_approval: bool


class ModelDowngradedPayload(TypedDict):
    requested_model: str
    actual_model: str


class DonePayload(TypedDict, total=False):
    result: str


class ErrorPayload(TypedDict, total=False):
    message: str
    result: str


SessionEventPayload = (
    LogPayload
    | TranscriptPayload
    | FileChangedPayload
    | ApprovalRequestPayload
    | ModelDowngradedPayload
    | DonePayload
    | ErrorPayload
)


# -- Telemetry TypedDicts -----------------------------------------------------
# Typed structures for data flowing through the telemetry persistence layer.


class TelemetrySpanRow(TypedDict, total=False):
    """Shape of a row returned by TelemetrySpansRepository.list_for_job()."""

    id: int
    job_id: str
    span_type: str  # "tool" | "llm"
    name: str
    started_at: float
    duration_ms: float
    attrs: dict[str, Any]
    tool_category: str | None
    tool_target: str | None
    turn_number: int | None
    execution_phase: ExecutionPhase | None
    is_retry: bool | None
    retries_span_id: int | None
    input_tokens: int | None
    output_tokens: int | None
    cache_read_tokens: int | None
    cache_write_tokens: int | None
    cost_usd: float | None
    tool_args_json: str | None
    result_size_bytes: int | None
    error_kind: str | None
    turn_id: str | None
    preceding_context: str | None
    motivation_summary: str | None
    edit_motivations: str | None
    created_at: str | None


class FileChurnRow(TypedDict):
    """Shape of a row returned by TelemetrySpansRepository.file_write_churn()."""

    tool_target: str
    write_count: int
    retry_count: int


class FileAccessStatsRow(TypedDict, total=False):
    """Shape returned by FileAccessRepository.reread_stats()."""

    total_accesses: int
    unique_files: int
    total_reads: int
    total_writes: int
    reread_count: int


class CostAttributionRow(TypedDict, total=False):
    """Shape of a row returned by CostAttributionRepository.for_job()."""

    dimension: str
    bucket: str
    cost_usd: float
    input_tokens: int
    output_tokens: int
    call_count: int


class TelemetrySummaryRow(TypedDict, total=False):
    """Shape of a row returned by TelemetrySummaryRepository.get()."""

    job_id: str
    sdk: str
    model: str
    repo: str
    branch: str
    status: str
    created_at: str
    completed_at: str | None
    duration_ms: int
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    total_cost_usd: float
    premium_requests: float
    llm_call_count: int
    total_llm_duration_ms: int
    tool_call_count: int
    tool_failure_count: int
    total_tool_duration_ms: int
    compactions: int
    tokens_compacted: int
    approval_count: int
    approval_wait_ms: int
    agent_messages: int
    operator_messages: int
    context_window_size: int
    current_context_tokens: int
    quota_json: str | None
    updated_at: str
    # Added by 0009_cost_attribution
    total_turns: int
    retry_count: int
    retry_cost_usd: float
    file_read_count: int
    file_write_count: int
    unique_files_read: int
    file_reread_count: int
    peak_turn_cost_usd: float
    avg_turn_cost_usd: float
    cost_first_half_usd: float
    cost_second_half_usd: float
    diff_lines_added: int
    diff_lines_removed: int
    # Added by 0012_error_kind
    agent_error_count: int
    # Added by 0017_add_subagent_cost
    subagent_cost_usd: float


# -- Analytics aggregation TypedDicts -----------------------------------------


class AggregateStats(TypedDict, total=False):
    """Shape returned by TelemetrySummaryRepository.aggregate()."""

    total_jobs: int
    review: int
    completed: int
    succeeded: int
    failed: int
    cancelled: int
    running: int
    total_cost_usd: float
    total_tokens: int
    avg_duration_ms: float
    total_premium_requests: float
    total_tool_calls: int
    total_tool_failures: int
    total_agent_errors: int
    total_cache_read: int
    total_input_tokens: int
    total_subagent_cost_usd: float
    total_retry_cost_usd: float
    total_retry_count: int


class CostByDayRow(TypedDict):
    """Shape returned by TelemetrySummaryRepository.cost_by_day()."""

    date: str
    cost: float
    jobs: int


class CostByRepoRow(TypedDict):
    """Shape returned by TelemetrySummaryRepository.cost_by_repo()."""

    repo: str
    job_count: int
    succeeded: int
    failed: int
    total_cost_usd: float
    total_tokens: int
    tool_calls: int
    avg_duration_ms: float
    premium_requests: float


class CostByModelRow(TypedDict, total=False):
    """Shape returned by TelemetrySummaryRepository.cost_by_model()."""

    model: str
    sdk: str
    job_count: int
    total_cost_usd: float
    total_tokens: int
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    avg_duration_ms: float
    premium_requests: float
    total_turns: int
    total_tool_calls: int
    total_diff_lines: int
    cost_per_job: float
    cost_per_minute: float
    cost_per_turn: float
    cost_per_tool_call: float
    cost_per_diff_line: float
    cost_per_mtok: float
    cache_hit_rate: float


class ToolStatsRow(TypedDict, total=False):
    """Shape returned by TelemetrySpansRepository.tool_stats()."""

    name: str
    count: int
    avg_duration_ms: float
    total_duration_ms: float
    failure_count: int
    p50_duration_ms: float
    p95_duration_ms: float
    p99_duration_ms: float


class ShellCommandRow(TypedDict):
    """Shape returned by TelemetrySpansRepository.shell_command_breakdown()."""

    command: str
    call_count: int
    total_cost_usd: float
    avg_duration_ms: float
    job_count: int


class RetryCostSummary(TypedDict):
    """Shape returned by TelemetrySpansRepository.retry_cost_summary()."""

    retry_cost_usd: float
    retry_count: int
    total_spans: int
    total_cost_usd: float


class CostDimensionRow(TypedDict):
    """Shape returned by CostAttributionRepository.by_dimension()."""

    bucket: str
    cost_usd: float
    input_tokens: int
    output_tokens: int
    call_count: int
    job_count: int


class FleetCostRow(TypedDict):
    """Shape returned by CostAttributionRepository.fleet_summary()."""

    dimension: str
    bucket: str
    cost_usd: float
    input_tokens: int
    output_tokens: int
    call_count: int
    job_count: int
    avg_cost_per_job: float


class FileAccessRow(TypedDict):
    """Shape returned by FileAccessRepository.most_accessed_files()."""

    file_path: str
    access_count: int
    read_count: int
    write_count: int
    job_count: int


class ModelComparisonRow(TypedDict, total=False):
    """Shape returned by TelemetrySummaryRepository.model_comparison()."""

    model: str
    sdk: str
    job_count: int
    avg_cost: float
    avg_duration_ms: float
    total_cost_usd: float
    premium_requests: float
    merged: int
    pr_created: int
    discarded: int
    failed: int
    avg_verify_turns: float | None
    verify_job_count: int
    avg_diff_lines: float
    cache_hit_rate: float
    cost_per_job: float
    cost_per_minute: float
    cost_per_turn: float
    cost_per_tool_call: float


@dataclass
class SessionEvent:
    kind: SessionEventKind
    payload: SessionEventPayload


@dataclass
class SessionConfig:
    workspace_path: str
    prompt: str
    job_id: str = ""
    sdk: str = "copilot"
    model: str | None = None
    mcp_servers: dict[str, MCPServerConfig] = field(default_factory=dict)
    protected_paths: list[str] = field(default_factory=list)
    blocking_permission_handler: Callable[[str, str], Awaitable[str]] | None = None
    # Set when resuming a job to reconnect to an existing Copilot SDK session
    resume_sdk_session_id: str | None = None


@dataclass
class JobSpec:
    """Parameters for creating a new job — bundles the inputs to JobService.create_job."""

    repo: str
    prompt: str
    base_ref: str | None = None
    branch: str | None = None
    title: str | None = None
    description: str | None = None
    worktree_name: str | None = None
    preset: Preset = Preset.supervised
    model: str | None = None
    sdk: str | None = None
    verify: bool | None = None
    self_review: bool | None = None
    max_turns: int | None = None
    verify_prompt: str | None = None
    self_review_prompt: str | None = None
    parent_job_id: str | None = None
    parent_job_context: str | None = None


@dataclass
class MCPServerConfig:
    command: str
    args: list[str]
    env: dict[str, str] | None = None


@dataclass
class Job:
    """Domain representation of a coding job.

    ``merge_status`` vs ``resolution`` — these track two distinct lifecycle phases:

    * **merge_status** — The outcome of the *git merge operation* performed
      automatically when the agent session completes.  Values are purely
      mechanical: ``not_merged`` | ``merged`` | ``conflict``.  Set once by
      ``MergeService`` and never changed by user action.

    * **resolution** — The *user-facing disposition* of the completed job,
      reflecting what the user (or auto-completion policy) decided to do with
      the agent's work.  Governed by the ``Resolution`` enum:
      ``unresolved`` | ``merged`` | ``pr_created`` | ``discarded`` | ``conflict``.
      Updated when the user explicitly resolves a job via the UI or API.
    """

    id: str
    repo: str
    prompt: str
    state: JobState
    base_ref: str
    branch: str | None
    worktree_path: str | None
    session_id: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    pr_url: str | None = None
    merge_status: GitMergeOutcome | None = None
    """Git merge operation outcome: ``not_merged`` | ``merged`` | ``conflict``."""
    resolution: Resolution | None = None
    """User-facing job disposition (see :class:`Resolution`)."""
    archived_at: datetime | None = None
    title: str | None = None
    description: str | None = None
    worktree_name: str | None = None
    preset: Preset = Preset.supervised
    session_count: int = 1
    sdk_session_id: str | None = None
    model: str | None = None
    sdk: str = "copilot"
    failure_reason: str | None = None
    verify: bool | None = None
    self_review: bool | None = None
    max_turns: int | None = None
    verify_prompt: str | None = None
    self_review_prompt: str | None = None
    version: int = 1
    parent_job_id: str | None = None


@dataclass
class Approval:
    """Domain representation of an approval request."""

    id: str
    job_id: str
    description: str
    proposed_action: str | None
    requested_at: datetime
    resolved_at: datetime | None = None
    resolution: ApprovalResolution | None = None
    # When True this approval was triggered by a hard-blocked operation (e.g.
    # git reset --hard) and MUST NOT be auto-resolved by a blanket trust grant.
    # The operator must explicitly click Approve for each occurrence.
    requires_explicit_approval: bool = False


@dataclass
class Artifact:
    """Domain representation of an artifact record."""

    id: str
    job_id: str
    name: str
    type: ArtifactType
    mime_type: str
    size_bytes: int
    disk_path: str
    phase: ExecutionPhase
    created_at: datetime
