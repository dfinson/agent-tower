"""Pydantic request/response schemas — single source of truth for the API contract.

Base model, enums, and telemetry schemas live in ``backend.models.schemas``
sub-modules for navigability. Everything is re-exported here so existing
``from backend.models.api_schemas import X`` imports continue to work.
"""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 — Pydantic resolves annotations at runtime
from typing import TYPE_CHECKING, Any, Literal

from pydantic import ConfigDict, Field, field_validator, model_validator

from backend.models.domain import (  # noqa: TC001 — Pydantic resolves annotations at runtime
    ApprovalResolution,
    GitMergeOutcome,
    JobMode,
    JobState,
    Preset,
    Resolution,
)

# Domain-grouped sub-modules — canonical definitions for base types and telemetry.
# Re-exported here for backward compatibility.
from backend.models.schemas.base import *  # noqa: E402,F401,F403
from backend.models.schemas.metrics import *  # noqa: E402,F401,F403
from backend.models.schemas.telemetry import *  # noqa: E402,F401,F403

if TYPE_CHECKING:
    from backend.models.domain import Job


# --- Request Models ---


class CreateJobRequest(CamelModel):
    repo: str
    prompt: str
    base_ref: str | None = None
    branch: str | None = None
    title: str | None = None
    description: str | None = None
    worktree_name: str | None = None
    preset: Preset | None = None
    model: str | None = None
    sdk: str | None = None
    verify: bool | None = None
    self_review: bool | None = None
    max_turns: int | None = Field(None, ge=1, le=10)
    verify_prompt: str | None = Field(None, max_length=5000)
    self_review_prompt: str | None = Field(None, max_length=5000)
    enable_stall_detection: bool | None = None
    enable_plan_tracking: bool | None = None
    session_token: str | None = Field(None, max_length=64)
    mode: JobMode | None = None

    @model_validator(mode="before")
    @classmethod
    def _validate_mode_and_sdk(cls, values: Any) -> Any:
        mode = values.get("mode")
        if mode == JobMode.plan_implementing:
            raise ValueError("Cannot create a job in plan_implementing mode — use 'plan' or 'standard'")
        sdk = values.get("sdk")
        if sdk is not None:
            from backend.models.domain import AgentSDK

            try:
                AgentSDK(sdk)
            except ValueError:
                valid = ", ".join(e.value for e in AgentSDK)
                raise ValueError(f"Unknown SDK {sdk!r}. Valid options: {valid}") from None
        return values


class SendMessageRequest(CamelModel):
    content: str = Field(min_length=1, max_length=10_000)


class ResumeJobRequest(CamelModel):
    instruction: str | None = Field(default=None, max_length=50_000)


class ResolveGateRequest(CamelModel):
    """Operator resolution for a sidecar gate verdict."""

    action: str = Field(description="'approve' or 'reject'", pattern=r"^(approve|reject)$")
    message: str | None = Field(default=None, max_length=10_000, description="Optional follow-up message to the agent")


class ContinueJobRequest(CamelModel):
    instruction: str = Field(min_length=1, max_length=10_000)

    @model_validator(mode="after")
    def _validate_instruction_not_blank(self) -> ContinueJobRequest:
        if not self.instruction.strip():
            raise ValueError("Instruction must not be blank")
        return self


class ResolveApprovalRequest(CamelModel):
    resolution: ApprovalResolution
    notes: str | None = Field(None, max_length=10_000)


class ResolveBatchRequest(CamelModel):
    """Resolve a pending action policy batch."""

    batch_id: str
    resolution: str  # approved / rejected / partial
    approved_ids: list[str] | None = None
    trust_grant_id: str | None = None


class ResolveBatchResponse(CamelModel):
    resolved: bool


class UpdateSettingsRequest(CamelModel):
    """Structured settings update — only include fields to change."""

    max_concurrent_jobs: int | None = Field(None, ge=1, le=10)
    auto_push: bool | None = None
    cleanup_worktree: bool | None = None
    delete_branch_after_merge: bool | None = None
    artifact_retention_days: int | None = Field(None, ge=1, le=365)
    max_artifact_size_mb: int | None = Field(None, ge=1, le=10_000)
    auto_archive_days: int | None = Field(None, ge=1, le=365)
    verify: bool | None = None
    self_review: bool | None = None
    max_turns: int | None = Field(None, ge=1, le=10)
    verify_prompt: str | None = Field(None, max_length=5000)
    self_review_prompt: str | None = Field(None, max_length=5000)
    cli_sidecars: list[str] | None = Field(None, description="Sidecar names for CLI sessions; null leaves current value unchanged")


class SettingsResponse(CamelModel):
    max_concurrent_jobs: int
    auto_push: bool
    cleanup_worktree: bool
    delete_branch_after_merge: bool
    artifact_retention_days: int
    max_artifact_size_mb: int
    auto_archive_days: int
    verify: bool
    self_review: bool
    max_turns: int
    verify_prompt: str
    self_review_prompt: str
    cli_sidecars: list[str] | None


class RegisterRepoRequest(CamelModel):
    source: str
    clone_to: str | None = None


class CreateRepoRequest(CamelModel):
    path: str
    name: str | None = None


class CreateRepoResponse(CamelModel):
    path: str
    name: str


class SuggestNamesRequest(CamelModel):
    prompt: str = Field(min_length=1, max_length=50_000)
    repo: str | None = None


class SuggestNamesResponse(CamelModel):
    title: str
    description: str
    branch_name: str
    worktree_name: str


# --- Response Models ---


class CreateJobResponse(CamelModel):
    id: str
    state: JobState
    title: str | None = None
    branch: str | None = None
    worktree_path: str | None = None
    sdk: str = "copilot"
    created_at: datetime


class JobResponse(CamelModel):
    id: str
    repo: str
    prompt: str
    title: str | None = None
    description: str | None = None
    state: JobState
    base_ref: str
    worktree_path: str | None
    branch: str | None
    preset: Preset | None = None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    pr_url: str | None = None
    merge_status: GitMergeOutcome | None = None
    """Git merge operation outcome — see :class:`~backend.models.domain.GitMergeOutcome`."""
    resolution: Resolution | None = None
    """User-facing job disposition — see :class:`~backend.models.domain.Resolution`."""
    archived_at: datetime | None = None
    failure_reason: str | None = None
    progress_headline: str | None = None
    progress_summary: str | None = None
    model: str | None = None
    sdk: str = "copilot"
    worktree_name: str | None = None
    verify: bool | None = None
    self_review: bool | None = None
    max_turns: int | None = None
    verify_prompt: str | None = None
    self_review_prompt: str | None = None
    enable_stall_detection: bool | None = None
    enable_plan_tracking: bool | None = None
    parent_job_id: str | None = None
    source: str = "managed"
    external_session_id: str | None = None
    mode: JobMode = JobMode.standard
    total_cost_usd: float | None = None
    total_tokens: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    @classmethod
    def from_domain(cls, job: Job, **overrides: Any) -> JobResponse:
        """Build a JobResponse from a domain Job, with optional field overrides."""
        return cls(
            id=job.id,
            repo=job.repo,
            prompt=job.prompt,
            title=job.title,
            description=job.description,
            state=job.state,
            base_ref=job.base_ref,
            worktree_path=job.worktree_path,
            branch=job.branch,
            preset=job.preset,
            created_at=job.created_at,
            updated_at=job.updated_at,
            completed_at=job.completed_at,
            pr_url=job.pr_url,
            merge_status=job.merge_status,
            resolution=job.resolution,
            archived_at=job.archived_at,
            failure_reason=job.failure_reason,
            model=job.model,
            sdk=job.sdk,
            worktree_name=job.worktree_name,
            verify=job.verify,
            self_review=job.self_review,
            max_turns=job.max_turns,
            verify_prompt=job.verify_prompt,
            self_review_prompt=job.self_review_prompt,
            enable_stall_detection=job.enable_stall_detection,
            enable_plan_tracking=job.enable_plan_tracking,
            parent_job_id=job.parent_job_id,
            source=job.source,
            external_session_id=job.external_session_id,
            mode=JobMode(job.mode) if isinstance(job.mode, str) else JobMode.standard,
            **overrides,
        )


class JobListResponse(CamelModel):
    items: list[JobResponse]
    cursor: str | None
    has_more: bool


class SendMessageResponse(CamelModel):
    seq: int
    timestamp: datetime


class SessionResumedPayload(CamelModel):
    job_id: str
    session_number: int
    timestamp: datetime


class ApprovalResponse(CamelModel):
    id: str
    job_id: str
    description: str
    proposed_action: str | None
    requested_at: datetime
    resolved_at: datetime | None
    resolution: ApprovalResolution | None
    # True when this approval was triggered by a hard-blocked operation (e.g.
    # git reset --hard) that cannot be auto-resolved by a trust grant.
    requires_explicit_approval: bool = False
    notes: str | None = None


class ArtifactResponse(CamelModel):
    id: str
    job_id: str
    name: str
    type: ArtifactType
    mime_type: str
    size_bytes: int
    phase: ExecutionPhase
    created_at: datetime


class ArtifactListResponse(CamelModel):
    items: list[ArtifactResponse]


class ModelListResponse(CamelModel):
    items: list[ModelInfoResponse]


class LogListResponse(CamelModel):
    items: list[LogLinePayload]


class DiffListResponse(CamelModel):
    items: list[DiffFileModel]


class TranscriptListResponse(CamelModel):
    items: list[TranscriptPayload]


class StepListResponse(CamelModel):
    items: list[PlanStepPayload]


class TimelineListResponse(CamelModel):
    items: list[ProgressHeadlinePayload]


class ApprovalListResponse(CamelModel):
    items: list[ApprovalResponse]


class TranscriptSearchListResponse(CamelModel):
    items: list[TranscriptSearchResult]


class WorkspaceEntry(CamelModel):
    path: str
    type: WorkspaceEntryType
    size_bytes: int | None = None


class WorkspaceListResponse(CamelModel):
    items: list[WorkspaceEntry]
    cursor: str | None
    has_more: bool


class TranscribeResponse(CamelModel):
    text: str


class ModelInfoResponse(CamelModel):
    """Model information returned by the agent SDK."""

    model_config = ConfigDict(extra="allow")

    id: str
    name: str


class HealthResponse(CamelModel):
    status: HealthStatus
    version: str
    uptime_seconds: float
    active_jobs: int
    queued_jobs: int


class RegisterRepoResponse(CamelModel):
    path: str
    source: str
    cloned: bool


class RepoListResponse(CamelModel):
    items: list[str]


class RepoDetailResponse(CamelModel):
    path: str
    origin_url: str | None = None
    base_branch: str | None = None
    current_branch: str | None = None
    active_job_count: int = 0
    platform: str | None = None


class RepoHealthResponse(CamelModel):
    """Structural health status for a repository (§6.2)."""

    repo: str
    available: bool = False
    index_status: str | None = None  # pending | indexing | ready | error
    symbol_count: int = 0
    file_count: int = 0
    last_indexed_sha: str | None = None
    community_count: int = 0
    cycle_count: int = 0
    stale: bool = False


class RepoJobSummary(CamelModel):
    """Minimal job info for repo dashboard."""

    id: str
    title: str | None = None
    state: str
    created_at: datetime
    completed_at: datetime | None = None
    total_cost_usd: float | None = None
    model: str | None = None


class RepoCostSummary(CamelModel):
    """Aggregated cost for a repo over a time period."""

    total_cost_usd: float = 0
    total_jobs: int = 0
    total_tokens: int = 0


class RepoMemoryPreview(CamelModel):
    """Short preview of workspace memory."""

    has_memory: bool = False
    decisions_chars: int = 0
    wisdom_chars: int = 0
    archive_chars: int = 0
    decisions_preview: str = ""
    wisdom_preview: str = ""


class RepoSummaryResponse(CamelModel):
    """Aggregated overview for a single repo dashboard."""

    path: str
    origin_url: str | None = None
    base_branch: str | None = None
    current_branch: str | None = None
    platform: str | None = None
    recent_jobs: list[RepoJobSummary] = []
    active_job_count: int = 0
    cost: RepoCostSummary = RepoCostSummary()
    memory: RepoMemoryPreview = RepoMemoryPreview()
    health: RepoHealthResponse | None = None


# --- SSE Payload Models ---


class LogLinePayload(CamelModel):
    job_id: str
    seq: int
    timestamp: datetime
    level: LogLevel
    message: str
    context: dict[str, Any] | None = None
    session_number: int | None = None


class TranscriptPayload(CamelModel):
    job_id: str
    seq: int
    timestamp: datetime
    role: TranscriptRole
    content: str
    # Optional rich fields — only present for specific roles
    title: str | None = None  # annotation title on agent messages
    turn_id: str | None = None  # groups reasoning + tool_calls + message
    tool_name: str | None = None  # role=tool_call: tool identifier
    tool_args: str | None = None  # role=tool_call: JSON-serialized arguments
    tool_result: str | None = None  # role=tool_call: text output from tool
    tool_success: bool | None = None  # role=tool_call: whether execution succeeded
    tool_issue: str | None = None  # role=tool_call: short issue summary when attention is needed
    tool_intent: str | None = None  # role=tool_call: SDK-provided intent string
    tool_title: str | None = None  # role=tool_call: SDK-provided display title
    tool_display: str | None = None  # role=tool_call: deterministic per-tool label (char-capped)
    tool_display_full: str | None = None  # role=tool_call: same label, no char truncation (CSS-based)
    tool_duration_ms: int | None = None  # role=tool_call: execution time in milliseconds
    tool_group_summary: str | None = None  # AI-generated summary for the tool group turn
    tool_visibility: str | None = None  # "hidden" | "collapsed" | "visible"
    step_id: str | None = None
    step_number: int | None = None
    # Sidecar fields — present when role == "sidecar"
    sidecar_name: str | None = None
    sidecar_icon: str | None = None
    sidecar_description: str | None = None
    sidecar_template_id: str | None = None


class ToolGroupSummaryPayload(CamelModel):
    """AI-generated one-line summary for a tool group in an agent turn."""

    job_id: str
    turn_id: str
    summary: str  # short label, e.g. "bash: ran test suite"
    timestamp: datetime


class SidecarTranscriptPayload(CamelModel):
    """Sidecar output injected into the transcript feed."""

    job_id: str
    seq: int
    timestamp: datetime
    name: str | None = None
    icon: str | None = None
    description: str | None = None
    template_id: str | None = None
    content: str = ""


class PreflightToolCallPayload(CamelModel):
    """A single tool invocation captured during the preflight session."""

    tool_name: str
    tool_args: str | None = None
    result_preview: str = ""
    duration_ms: float | None = None


class PreflightReportPayload(CamelModel):
    """Structured report from the preflight scout session."""

    job_id: str
    timestamp: datetime
    elapsed_ms: float = 0.0
    tool_calls: list[PreflightToolCallPayload] = []
    brief_length: int = 0


class DiffLineModel(CamelModel):
    type: DiffLineType
    content: str


class DiffHunkModel(CamelModel):
    old_start: int
    old_lines: int
    new_start: int
    new_lines: int
    lines: list[DiffLineModel]


class DiffFileModel(CamelModel):
    path: str
    status: DiffFileStatus
    additions: int
    deletions: int
    hunks: list[DiffHunkModel]
    write_count: int | None = None
    retry_count: int | None = None


class JobStateChangedPayload(CamelModel):
    job_id: str
    previous_state: JobState | None
    new_state: JobState
    timestamp: datetime


class ApprovalRequestedPayload(CamelModel):
    job_id: str
    approval_id: str
    description: str
    proposed_action: str | None = None
    timestamp: datetime
    requires_explicit_approval: bool = False


class ApprovalResolvedPayload(CamelModel):
    job_id: str
    approval_id: str
    resolution: ApprovalResolution
    timestamp: datetime


class DiffUpdatePayload(CamelModel):
    job_id: str
    changed_files: list[DiffFileModel]


class SessionHeartbeatPayload(CamelModel):
    job_id: str
    session_id: str
    timestamp: datetime
    last_activity_at: datetime | None = None
    active_tool_name: str | None = None
    active_tool_since: datetime | None = None


class MergeCompletedPayload(CamelModel):
    job_id: str
    branch: str
    base_ref: str
    strategy: str  # ff_only | merge
    timestamp: datetime


class MergeConflictPayload(CamelModel):
    job_id: str
    branch: str
    base_ref: str
    conflict_files: list[str]
    fallback: str  # pr_created | none
    pr_url: str | None = None
    timestamp: datetime


# --- Platform Models ---


class PlatformStatusResponse(CamelModel):
    platform: str
    authenticated: bool
    user: str | None = None
    error: str | None = None


class PlatformStatusListResponse(CamelModel):
    items: list[PlatformStatusResponse]
    timestamp: datetime


class ResolveJobRequest(CamelModel):
    action: ResolutionAction
    confirm_low_confidence: bool = False


class ResolveJobResponse(CamelModel):
    resolution: Resolution | ResolutionAction
    pr_url: str | None = None
    conflict_files: list[str] | None = None
    error: str | None = None


class JobFailedPayload(CamelModel):
    job_id: str
    reason: str
    timestamp: datetime


class JobReviewPayload(CamelModel):
    """Emitted when the agent session exits cleanly and the job enters review."""

    job_id: str
    pr_url: str | None = None
    merge_status: GitMergeOutcome | None = None
    """Git merge operation outcome — see :class:`~backend.models.domain.GitMergeOutcome`."""
    resolution: Resolution | None = None
    """User-facing job disposition — see :class:`~backend.models.domain.Resolution`."""
    model_downgraded: bool = False
    requested_model: str | None = None
    actual_model: str | None = None
    timestamp: datetime


class JobCompletedPayload(CamelModel):
    """Emitted when an operator resolves a review job to a final state."""

    job_id: str
    resolution: Resolution | None = None
    pr_url: str | None = None
    timestamp: datetime


class JobResolvedPayload(CamelModel):
    job_id: str
    resolution: Resolution
    pr_url: str | None = None
    conflict_files: list[str] | None = None
    error: str | None = None
    timestamp: datetime


class ModelDowngradedPayload(CamelModel):
    job_id: str
    requested_model: str
    actual_model: str
    timestamp: datetime


class JobArchivedPayload(CamelModel):
    job_id: str
    timestamp: datetime


class JobTitleUpdatedPayload(CamelModel):
    job_id: str
    title: str | None = None
    description: str | None = None
    branch: str | None = None
    timestamp: datetime


class ProgressHeadlinePayload(CamelModel):
    job_id: str
    headline: str
    headline_past: str
    summary: str
    timestamp: datetime
    replaces_count: int = 0


PlanStepStatus = Literal["pending", "active", "done", "skipped"]


class AgentPlanStep(CamelModel):
    label: str
    status: PlanStepStatus


class AgentPlanPayload(CamelModel):
    job_id: str
    steps: list[AgentPlanStep]
    timestamp: datetime


class TelemetryUpdatedPayload(CamelModel):
    job_id: str
    timestamp: datetime
    total_cost_usd: float = 0.0
    total_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


class StepEntriesReassignedPayload(CamelModel):
    job_id: str
    turn_id: str
    old_step_id: str
    new_step_id: str


class RepoIndexProgressPayload(CamelModel):
    repo: str
    indexed: int = 0
    total: int = 0
    phase: str = "indexing"


class RepoIndexCompletePayload(CamelModel):
    repo: str


class StructuralWarningPayload(CamelModel):
    repo: str = ""
    warning_type: str = ""
    detail: str = ""


class StallDetectedPayload(CamelModel):
    job_id: str = ""
    tool_name: str = ""
    elapsed: str = ""
    reason: str = ""


class SnapshotPayload(CamelModel):
    jobs: list[JobResponse]
    pending_approvals: list[ApprovalResponse]


class JobSnapshotResponse(CamelModel):
    """Full state hydration for a single job — used after reconnect or page refresh."""

    job: JobResponse
    logs: list[LogLinePayload]
    transcript: list[TranscriptPayload]
    diff: list[DiffFileModel]
    approvals: list[ApprovalResponse]
    timeline: list[ProgressHeadlinePayload]
    steps: list[PlanStepPayload] = []
    turn_summaries: list[TurnSummaryPayload] = []


class SDKInfoResponse(CamelModel):
    id: str
    name: str
    enabled: bool
    status: Literal["ready", "not_installed", "not_configured"]
    authenticated: bool | None = None  # None = unknown / not applicable
    hint: str = ""  # actionable suggestion for the user


class SDKListResponse(CamelModel):
    default: str
    sdks: list[SDKInfoResponse]


# --- Terminal schemas (moved from backend/api/terminal.py) ---


class CreateTerminalSessionRequest(CamelModel):
    shell: str | None = None
    cwd: str | None = None
    job_id: str | None = None
    prompt_label: str | None = None


class CreateTerminalSessionResponse(CamelModel):
    id: str
    shell: str
    cwd: str
    job_id: str | None = None
    pid: int


class TerminalSessionInfo(CamelModel):
    id: str
    shell: str
    cwd: str
    job_id: str | None = None
    pid: int | None = None
    clients: int
    observer: bool = False


class TerminalSessionListResponse(CamelModel):
    items: list[TerminalSessionInfo]


class TerminalAskRequest(CamelModel):
    prompt: str
    context: str | None = None  # recent terminal output for context


class TerminalAskResponse(CamelModel):
    command: str
    explanation: str


# --- Typed response models for previously untyped dict endpoints ---


class TrustJobResponse(CamelModel):
    resolved: int


class CleanupWorktreesResponse(CamelModel):
    removed: int


class BrowseEntry(CamelModel):
    name: str
    path: str
    is_git_repo: bool = False


class BrowseDirectoryResponse(CamelModel):
    current: str
    parent: str | None = None
    items: list[BrowseEntry]


class WorkspaceFileResponse(CamelModel):
    path: str
    content: str


# ---------------------------------------------------------------------------
# Cost Analytics / Telemetry — canonical definitions in schemas.telemetry
# (imported via star-import at module top)
# ---------------------------------------------------------------------------


class StepPayload(CamelModel):
    """Step data for REST API and SSE."""

    step_id: str
    step_number: int
    job_id: str
    turn_id: str | None = None
    intent: str
    title: str | None = None
    status: str
    trigger: str
    tool_count: int = 0
    agent_message: str | None = None
    duration_ms: int | None = None
    started_at: datetime
    completed_at: datetime | None = None
    files_read: list[str] | None = None
    files_written: list[str] | None = None
    start_sha: str | None = None
    end_sha: str | None = None
    artifact_count: int = 0


class StepTitlePayload(CamelModel):
    """SSE payload for step title generation."""

    step_id: str
    title: str


class StepGroupPayload(CamelModel):
    """SSE payload for step grouping updates."""

    job_id: str
    group_id: str
    headline: str
    headline_past: str
    step_ids: list[str]


class PlanStepPayload(CamelModel):
    """SSE payload for unified plan-step updates."""

    job_id: str
    plan_step_id: str
    label: str
    summary: str | None = None
    status: str
    order: int = 0
    tool_count: int = 0
    files_written: list[str] | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: int | None = None
    start_sha: str | None = None
    end_sha: str | None = None


class TurnSummaryPayload(CamelModel):
    """SSE payload for activity timeline turn summaries."""

    job_id: str
    turn_id: str
    title: str
    activity_id: str
    activity_label: str
    activity_status: str = "active"  # active | done
    is_new_activity: bool = False
    plan_item_id: str | None = None
    replaces_turn_id: str | None = None  # set when merge replaces a previous step's turnId


class HunkMotivation(CamelModel):
    """Per-hunk motivation annotation."""

    edit_key: str
    title: str
    why: str


class FileMotivation(CamelModel):
    """Per-file motivation annotation."""

    title: str
    why: str
    unmatched_edits: list[HunkMotivation] = []


class StepDiffPayload(CamelModel):
    """Response for step-scoped Git diff."""

    step_id: str
    diff: str
    files_changed: int
    changed_files: list[DiffFileModel] = []
    step_context: str | None = None
    file_motivations: dict[str, FileMotivation] = {}
    hunk_motivations: dict[str, HunkMotivation] = {}


class TranscriptSearchResult(CamelModel):
    """A transcript event matching a search query."""

    seq: int
    role: str
    content: str
    tool_name: str | None = None
    step_id: str | None = None
    step_number: int | None = None
    timestamp: datetime


class RestoreRequest(CamelModel):
    sha: str


class StoryBlock(CamelModel):
    """A single block in a structured code-review story.

    Block types:
    - ``narrative``: prose text connecting references and beats
    - ``reference``: validated code change with file/snippet data
    - ``beat``: cognitive turning point (decision, backtrack, insight, verify)
    """

    type: str  # "narrative" | "reference" | "beat"
    # Narrative / beat fields
    text: str | None = None
    # Beat fields
    beat_kind: str | None = None  # decide | backtrack | insight | verify
    # Reference fields (coerce int→str for legacy cached payloads)
    span_id: str | None = None

    @field_validator("span_id", mode="before")
    @classmethod
    def _coerce_span_id(cls, v: object) -> str | None:
        if v is None:
            return None
        return str(v)

    step_number: int | None = None
    step_title: str | None = None
    file: str | None = None
    why: str | None = None
    turn_id: str | None = None
    edit_count: int | None = None
    snippet: str | None = None


class StoryResponse(CamelModel):
    """Structured code-review story with validated change references
    and agent cognitive beats."""

    job_id: str
    blocks: list[StoryBlock] = []
    cached: bool = False
    verbosity: str = "standard"  # summary | standard | detailed
    beat_count: int = 0
    has_decisions: bool = False
    has_backtracks: bool = False


# ---------------------------------------------------------------------------
# Structural Review (CodeRecon integration)
# ---------------------------------------------------------------------------


class StructuralChange(CamelModel):
    """A single structural change detected by semantic diff."""

    kind: str  # added | removed | modified | moved
    symbol: str | None = None
    file: str
    summary: str | None = None
    category: str = "non-structural"  # breaking | body | additive | non-structural
    ref_count: int = 0
    ref_tiers: dict[str, int] = Field(default_factory=dict)  # e.g. {"verified": 3, "inferred": 2, "unverified": 1}
    test_files: list[str] = Field(default_factory=list)
    risk: float = 0.0
    line_range: list[int] | None = None  # [start, end]


class StructuralDiffResponse(CamelModel):
    """Structural diff result for a job's changes."""

    job_id: str
    summary: str = ""
    changes: list[StructuralChange] = []
    available: bool = True
    merge_confidence: str | None = None  # HIGH | MEDIUM | LOW
    triage: dict[str, int] = Field(default_factory=dict)  # category → count


class SessionSegment(CamelModel):
    """Structural analysis of a single agent session."""

    session_number: int
    start_sha: str | None = None
    end_sha: str | None = None
    changes: list[StructuralChange] = []
    risk: float = 0.0
    warnings: list[dict[str, Any]] = Field(default_factory=list)


class MultiSessionResponse(CamelModel):
    """Multi-session structural intelligence for a job (§10)."""

    job_id: str
    available: bool = True
    sessions: list[SessionSegment] = []
    direction_changes: list[dict[str, Any]] = Field(default_factory=list)


class ImpactReference(CamelModel):
    """A single reference/caller in an impact graph."""

    symbol: str = ""
    file: str = ""
    line: int | None = None
    tier: str = "unverified"  # verified | inferred | unverified
    is_test: bool = False
    raw_tier: str = "UNKNOWN"


class ImpactGraphResponse(CamelModel):
    """Impact graph for a symbol — callers with tier classification."""

    job_id: str
    target: str
    available: bool = True
    total_references: int = 0
    files_affected: int = 0
    summary: str = ""
    references: list[ImpactReference] = Field(default_factory=list)


class CommunityGroup(CamelModel):
    """A module community with its grouped changes."""

    name: str
    changes: list[dict[str, Any]] = Field(default_factory=list)
    total_risk: float = 0.0


class CommunitiesResponse(CamelModel):
    """Community-grouped structural changes for a job."""

    job_id: str
    available: bool = True
    communities: list[CommunityGroup] = Field(default_factory=list)
    unclustered: list[dict[str, Any]] = Field(default_factory=list)


class ReviewStoryHeader(CamelModel):
    """Header block for the review story."""

    title: str = ""
    file_count: int = 0
    breaking_count: int = 0
    merge_confidence: str | None = None


class ReviewStoryVerdict(CamelModel):
    """Verdict section of the review story."""

    confidence: str = "MEDIUM"
    blockers: list[str] = Field(default_factory=list)
    summary: str = ""


class EdgeCaseBlockSchema(CamelModel):
    """A metadata block for non-narrative content (docs, generated, vendor, etc.)."""

    kind: str = ""
    icon: str = ""
    title: str = ""
    files: list[str] = Field(default_factory=list)
    detail: str = ""


class CommunityRollupSchema(CamelModel):
    """Community-level aggregation when body changes exceed cognitive cap."""

    name: str = ""
    change_count: int = 0
    avg_risk: float = 0.0
    highest_risk_symbol: str | None = None
    highest_risk: float = 0.0
    summary: str = ""


class PatternGroupSchema(CamelModel):
    """A group of changes sharing a common structural pattern."""

    pattern: str = ""
    count: int = 0
    files: list[str] = Field(default_factory=list)
    summary: str = ""


class ReviewStoryResponse(CamelModel):
    """Structured review story artifact (§11)."""

    job_id: str
    available: bool = True
    collapsed: bool = False
    header: ReviewStoryHeader | None = None
    attention_required: list[dict[str, Any]] = Field(default_factory=list)
    structural_concerns: list[dict[str, Any]] = Field(default_factory=list)
    what_changed: list[dict[str, Any]] = Field(default_factory=list)
    what_added: list[dict[str, Any]] = Field(default_factory=list)
    non_structural_count: int = 0
    edge_cases: list[EdgeCaseBlockSchema] = Field(default_factory=list)
    community_rollups: list[CommunityRollupSchema] = Field(default_factory=list)
    pattern_groups: list[PatternGroupSchema] = Field(default_factory=list)
    verdict: ReviewStoryVerdict | None = None


# TestCoModification, ReviewSignals, ReviewComplexity, and JobTelemetryReport
# are now canonical in backend.models.schemas.telemetry (star-imported above).


# ---------------------------------------------------------------------------
# Trail (agent audit trail)
# ---------------------------------------------------------------------------


class TrailNodeResponse(CamelModel):
    """A single trail node in the agent audit trail."""

    id: str
    seq: int
    anchor_seq: int
    kind: str
    deterministic_kind: str | None = None
    phase: str | None = None
    timestamp: datetime
    enrichment: str
    intent: str | None = None
    rationale: str | None = None
    outcome: str | None = None
    step_id: str | None = None
    span_ids: list[int] = []
    turn_id: str | None = None
    files: list[str] = []
    start_sha: str | None = None
    end_sha: str | None = None
    supersedes: str | None = None
    tags: list[str] = []
    # Action policy fields
    tier: str | None = None
    reversible: bool | None = None
    contained: bool | None = None
    tier_reason: str | None = None
    checkpoint_ref: str | None = None
    children: list[TrailNodeResponse] = []


TrailNodeResponse.model_rebuild()


class TrailResponse(CamelModel):
    """Trail endpoint response — flat or nested."""

    job_id: str
    nodes: list[TrailNodeResponse] = []
    total_nodes: int = 0
    enriched_nodes: int = 0
    complete: bool = False


class TrailKeyDecision(CamelModel):
    """A key decision from the trail summary."""

    decision: str
    rationale: str | None = None


class TrailBacktrack(CamelModel):
    """A backtrack from the trail summary."""

    original: str
    replacement: str
    reason: str | None = None


class TrailSummaryResponse(CamelModel):
    """Lightweight trail summary for job list cards / PR descriptions."""

    job_id: str
    goals: list[str] = []
    approach: str | None = None
    key_decisions: list[TrailKeyDecision] = []
    backtracks: list[TrailBacktrack] = []
    files_explored: int = 0
    files_modified: int = 0
    verifications_passed: int = 0
    verifications_failed: int = 0
    enrichment_complete: bool = False


# ---------------------------------------------------------------------------
# Notification schemas
# ---------------------------------------------------------------------------


class VapidKeyResponse(CamelModel):
    public_key: str


class SubscriptionRequest(CamelModel):
    endpoint: str
    keys: dict[str, str]


class UnsubscribeRequest(CamelModel):
    endpoint: str


# ---------------------------------------------------------------------------
# Share schemas
# ---------------------------------------------------------------------------


class ShareTokenResponse(CamelModel):
    token: str
    job_id: str
    url: str


class CreateShareRequest(CamelModel):
    job_id: str | None = None  # allow body-less POST where job_id is in path


# ---------------------------------------------------------------------------
# Sidecar template schemas
# ---------------------------------------------------------------------------


class GenerateSidecarRequest(CamelModel):
    description: str = Field(min_length=1, max_length=5000)


class GenerateSidecarResponse(CamelModel):
    definition: dict[str, Any]


class CreateSidecarTemplateRequest(CamelModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=500)
    definition_json: str = Field(min_length=2, max_length=50_000)


class UpdateSidecarTemplateRequest(CamelModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = Field(None, min_length=1, max_length=500)
    definition_json: str | None = Field(None, min_length=2, max_length=50_000)
    enabled: bool | None = None

    @model_validator(mode="after")
    def _at_least_one_field(self) -> UpdateSidecarTemplateRequest:
        if all(v is None for v in (self.name, self.description, self.definition_json, self.enabled)):
            raise ValueError("At least one field must be provided")
        return self


class SidecarTemplateResponse(CamelModel):
    id: str
    name: str
    description: str
    definition_json: str
    created_at: datetime
    last_used_at: datetime | None
    enabled: bool = True


class SidecarTemplateListResponse(CamelModel):
    items: list[SidecarTemplateResponse]


# ---------------------------------------------------------------------------
# Utility / operational responses
# ---------------------------------------------------------------------------


class WarmSessionResponse(CamelModel):
    session_token: str


class RestoreResponse(CamelModel):
    restored: bool
    sha: str


# SidecarSession*Metrics classes are now canonical in
# backend.models.schemas.telemetry (star-imported above).
