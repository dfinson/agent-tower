"""SQLAlchemy ORM models."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# All DateTime columns use timezone=True so timestamps are stored
# and retrieved as timezone-aware UTC values, never naive.
TZDateTime = DateTime(timezone=True)


class Base(DeclarativeBase):
    pass


class JobRow(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    repo: Mapped[str] = mapped_column(String, nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(String, nullable=False)
    base_ref: Mapped[str] = mapped_column(String, nullable=False)
    branch: Mapped[str | None] = mapped_column(String, nullable=True)
    worktree_path: Mapped[str | None] = mapped_column(String, nullable=True)
    session_id: Mapped[str | None] = mapped_column(String, nullable=True)
    pr_url: Mapped[str | None] = mapped_column(String, nullable=True)
    merge_status: Mapped[str | None] = mapped_column(String, nullable=True)
    resolution: Mapped[str | None] = mapped_column(String, nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    worktree_name: Mapped[str | None] = mapped_column(String, nullable=True)
    permission_mode: Mapped[str] = mapped_column(String, nullable=False, default="full_auto")
    preset: Mapped[str] = mapped_column(String, nullable=False, server_default="supervised")
    session_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    sdk_session_id: Mapped[str | None] = mapped_column(String, nullable=True)
    model: Mapped[str | None] = mapped_column(String, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    sdk: Mapped[str] = mapped_column(String, nullable=False, default="copilot")
    verify: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    self_review: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    max_turns: Mapped[int | None] = mapped_column(Integer, nullable=True)
    verify_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    self_review_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    parent_job_id: Mapped[str | None] = mapped_column(String, ForeignKey("jobs.id"), nullable=True)
    story_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    trail_state_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON


class EventRow(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    job_id: Mapped[str] = mapped_column(String, ForeignKey("jobs.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)
    payload: Mapped[str] = mapped_column(Text, nullable=False)  # JSON

    __table_args__ = (Index("idx_events_job_id", "job_id"),)


class ApprovalRow(Base):
    __tablename__ = "approvals"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    job_id: Mapped[str] = mapped_column(String, ForeignKey("jobs.id"), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    proposed_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)
    resolution: Mapped[str | None] = mapped_column(String, nullable=True)
    # Hard-blocked operations (e.g. git reset --hard) set this to True so that
    # blanket trust grants cannot auto-resolve them.
    requires_explicit_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="0")
    # Action policy metadata (populated by action classifier)
    batch_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    tier: Mapped[str | None] = mapped_column(String(12), nullable=True)
    reversible: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    contained: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    checkpoint_ref: Mapped[str | None] = mapped_column(String(80), nullable=True)


class ArtifactRow(Base):
    __tablename__ = "artifacts"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    job_id: Mapped[str] = mapped_column(String, ForeignKey("jobs.id"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    type: Mapped[str] = mapped_column(String, nullable=False)
    mime_type: Mapped[str] = mapped_column(String, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    disk_path: Mapped[str] = mapped_column(String, nullable=False)
    phase: Mapped[str] = mapped_column(String, nullable=False)
    step_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)


class DiffSnapshotRow(Base):
    __tablename__ = "diff_snapshots"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    job_id: Mapped[str] = mapped_column(String, ForeignKey("jobs.id"), nullable=False)
    snapshot_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)
    diff_json: Mapped[str] = mapped_column(Text, nullable=False)  # JSON

    __table_args__ = (Index("idx_diff_snapshots_job_id", "job_id"),)


class StepRow(Base):
    __tablename__ = "steps"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    job_id: Mapped[str] = mapped_column(String(36), ForeignKey("jobs.id", ondelete="CASCADE"), index=True, nullable=False)
    step_number: Mapped[int] = mapped_column(Integer, nullable=False)
    turn_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    intent: Mapped[str] = mapped_column(Text, nullable=False, default="")
    title: Mapped[str | None] = mapped_column(String(60), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running")
    trigger: Mapped[str] = mapped_column(String(30), nullable=False)
    tool_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    agent_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    start_sha: Mapped[str | None] = mapped_column(String(40), nullable=True)
    end_sha: Mapped[str | None] = mapped_column(String(40), nullable=True)
    files_read: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON array
    files_written: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON array
    # Transcript context at step close (migration 0020)
    preceding_context: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON array

    __table_args__ = (Index("ix_steps_job_number", "job_id", "step_number"),)


class JobTelemetrySummaryRow(Base):
    """Denormalized per-job telemetry — upserted on every telemetry event."""

    __tablename__ = "job_telemetry_summary"

    job_id: Mapped[str] = mapped_column(String, ForeignKey("jobs.id"), primary_key=True)
    sdk: Mapped[str] = mapped_column(String, nullable=False)
    model: Mapped[str] = mapped_column(String, nullable=False, default="")
    repo: Mapped[str] = mapped_column(String, nullable=False, default="")
    branch: Mapped[str] = mapped_column(String, nullable=False, default="")
    status: Mapped[str] = mapped_column(String, nullable=False, default="running")
    created_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cache_write_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    premium_requests: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    llm_call_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_llm_duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tool_call_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tool_failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_tool_duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    compactions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_compacted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    approval_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    approval_wait_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    agent_messages: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    operator_messages: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    context_window_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    current_context_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    quota_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)
    # Cost analytics columns (migration 0009)
    total_turns: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    retry_cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0.0")
    file_read_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    file_write_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    unique_files_read: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    file_reread_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    peak_turn_cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0.0")
    avg_turn_cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0.0")
    cost_first_half_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0.0")
    cost_second_half_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0.0")
    diff_lines_added: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    diff_lines_removed: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    agent_error_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    subagent_cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0")


class JobTelemetrySpanRow(Base):
    """Individual LLM or tool call — append-only."""

    __tablename__ = "job_telemetry_spans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String, ForeignKey("jobs.id"), nullable=False)
    span_type: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    started_at: Mapped[str] = mapped_column(Text, nullable=False)  # float stored as text
    duration_ms: Mapped[str] = mapped_column(Text, nullable=False)
    attrs_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)
    # Cost analytics columns (migration 0008)
    tool_category: Mapped[str | None] = mapped_column(String, nullable=True)
    tool_target: Mapped[str | None] = mapped_column(String, nullable=True)
    turn_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    execution_phase: Mapped[str | None] = mapped_column(String, nullable=True)
    is_retry: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=False)
    retries_span_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cache_read_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cache_write_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    tool_args_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_kind: Mapped[str | None] = mapped_column(String, nullable=True)
    # Transcript linkage (migration 0018)
    turn_id: Mapped[str | None] = mapped_column(String, nullable=True)
    # Motivation tracking (migration 0019)
    preceding_context: Mapped[str | None] = mapped_column(Text, nullable=True)
    motivation_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Per-edit motivations with edit keys (migration 0021)
    edit_motivations: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON array

    __table_args__ = (
        Index("idx_spans_job", "job_id"),
        Index("idx_spans_category", "tool_category"),
        Index("idx_spans_turn", "job_id", "turn_number"),
        Index("idx_spans_phase", "execution_phase"),
        Index("idx_spans_turn_id", "job_id", "turn_id"),
    )


class JobFileAccessRow(Base):
    """Per-file read/write access log for cost analytics."""

    __tablename__ = "job_file_access_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String, ForeignKey("jobs.id"), nullable=False)
    file_path: Mapped[str] = mapped_column(String, nullable=False)
    access_type: Mapped[str] = mapped_column(String, nullable=False)  # read / write
    turn_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    span_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    byte_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)

    __table_args__ = (
        Index("idx_file_access_job", "job_id"),
        Index("idx_file_access_path", "file_path"),
    )


class CostAttributionRow(Base):
    """Per-job cost breakdown by dimension (phase, tool category, turn)."""

    __tablename__ = "job_cost_attribution"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String, ForeignKey("jobs.id"), nullable=False)
    dimension: Mapped[str] = mapped_column(String, nullable=False)
    bucket: Mapped[str] = mapped_column(String, nullable=False)
    cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0.0")
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    call_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)

    __table_args__ = (
        Index("idx_attr_job", "job_id"),
        Index("idx_attr_dimension", "dimension", "bucket"),
    )


class CostObservationRow(Base):
    """Cross-job cost observation or anomaly."""

    __tablename__ = "cost_observations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    category: Mapped[str] = mapped_column(String, nullable=False)
    severity: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_json: Mapped[str] = mapped_column(Text, nullable=False)
    job_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    total_waste_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0.0")
    first_seen_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)
    dismissed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")

    __table_args__ = (
        Index("idx_obs_category", "category"),
        Index("idx_obs_severity", "severity"),
    )


class TrailNodeRow(Base):
    """Agent audit trail node — structured intent graph."""

    __tablename__ = "trail_nodes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    job_id: Mapped[str] = mapped_column(String(36), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    anchor_seq: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    deterministic_kind: Mapped[str | None] = mapped_column(String(20), nullable=True)
    phase: Mapped[str | None] = mapped_column(String(30), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)
    enrichment: Mapped[str] = mapped_column(String(10), nullable=False, server_default="pending")
    # Intent (populated by enrichment, nullable)
    intent: Mapped[str | None] = mapped_column(Text, nullable=True)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    outcome: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Anchors (populated deterministically)
    step_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    span_ids: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON array
    turn_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    files: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON array
    start_sha: Mapped[str | None] = mapped_column(String(40), nullable=True)
    end_sha: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # Transcript context (pass-through from step_completed)
    preceding_context: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON snapshot
    agent_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    tool_names: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON array
    tool_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    diff_additions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    diff_deletions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Plan/activity (populated by enrichment or native plan)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    plan_item_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    plan_item_label: Mapped[str | None] = mapped_column(Text, nullable=True)
    plan_item_status: Mapped[str | None] = mapped_column(String(10), nullable=True)
    activity_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    activity_label: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Action policy classification
    tier: Mapped[str | None] = mapped_column(String(12), nullable=True)
    reversible: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    contained: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    tier_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    checkpoint_ref: Mapped[str | None] = mapped_column(String(80), nullable=True)
    rollback_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Edges
    supersedes: Mapped[str | None] = mapped_column(String(36), nullable=True)
    tags: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON array
    # Write sub-node columns (kind="write", children of modify nodes)
    tool_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_retry: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    error_kind: Mapped[str | None] = mapped_column(String(50), nullable=True)
    write_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    edit_motivations: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON array
    tool_display: Mapped[str | None] = mapped_column(String(200), nullable=True)
    tool_intent: Mapped[str | None] = mapped_column(Text, nullable=True)
    tool_success: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    __table_args__ = (
        Index("ix_trail_nodes_job_id", "job_id"),
        Index("ix_trail_nodes_job_seq", "job_id", "seq"),
        Index("ix_trail_nodes_display_order", "job_id", "anchor_seq", "seq"),
        Index("ix_trail_nodes_parent", "parent_id"),
        Index("ix_trail_nodes_kind", "job_id", "kind"),
        Index("ix_trail_nodes_enrichment", "job_id", "enrichment"),
    )


# ---------------------------------------------------------------------------
# Action Policy tables
# ---------------------------------------------------------------------------

class PolicyConfigRow(Base):
    __tablename__ = "policy_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    preset: Mapped[str] = mapped_column(String(20), nullable=False, server_default="supervised")
    batch_window_seconds: Mapped[float] = mapped_column(Float, nullable=False, server_default="5.0")


class PathRuleRow(Base):
    __tablename__ = "path_rules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    path_pattern: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    tier: Mapped[str] = mapped_column(String(12), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)


class ActionRuleRow(Base):
    __tablename__ = "action_rules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    match_pattern: Mapped[str] = mapped_column(Text, nullable=False)
    tier: Mapped[str] = mapped_column(String(12), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)


class CostRuleRow(Base):
    __tablename__ = "cost_rules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    condition: Mapped[str] = mapped_column(Text, nullable=False)
    promote_to: Mapped[str] = mapped_column(String(12), nullable=False)
    threshold_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)


class MCPServerConfigRow(Base):
    __tablename__ = "mcp_server_configs"

    name: Mapped[str] = mapped_column(Text, primary_key=True)
    command: Mapped[str] = mapped_column(Text, nullable=False)
    args_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    env_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    contained: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="0")
    reversible: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="0")
    trusted: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="0")
    tool_overrides_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)


class TrustGrantRow(Base):
    __tablename__ = "trust_grants"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    job_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    kinds_json: Mapped[str] = mapped_column(Text, nullable=False)
    path_pattern: Mapped[str | None] = mapped_column(Text, nullable=True)
    excludes_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    command_pattern: Mapped[str | None] = mapped_column(Text, nullable=True)
    mcp_server: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
