"""SQLAlchemy ORM models."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped

from backend.models.domain import PermissionMode

# All DateTime columns use timezone=True so timestamps are stored
# and retrieved as timezone-aware UTC values, never naive.
TZDateTime = DateTime(timezone=True)


class Base(DeclarativeBase):
    pass


class JobRow(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = Column(String, primary_key=True)
    repo: Mapped[str] = Column(String, nullable=False)
    prompt: Mapped[str] = Column(Text, nullable=False)
    state: Mapped[str] = Column(String, nullable=False)
    base_ref: Mapped[str] = Column(String, nullable=False)
    branch: Mapped[str | None] = Column(String, nullable=True)
    worktree_path: Mapped[str | None] = Column(String, nullable=True)
    session_id: Mapped[str | None] = Column(String, nullable=True)
    pr_url: Mapped[str | None] = Column(String, nullable=True)
    merge_status: Mapped[str | None] = Column(String, nullable=True)
    resolution: Mapped[str | None] = Column(String, nullable=True)
    archived_at: Mapped[datetime | None] = Column(TZDateTime, nullable=True)
    title: Mapped[str | None] = Column(String, nullable=True)
    description: Mapped[str | None] = Column(Text, nullable=True)
    worktree_name: Mapped[str | None] = Column(String, nullable=True)
    permission_mode: Mapped[str] = Column(String, nullable=False, default=PermissionMode.full_auto)
    session_count: Mapped[int] = Column(Integer, nullable=False, default=1)
    sdk_session_id: Mapped[str | None] = Column(String, nullable=True)
    model: Mapped[str | None] = Column(String, nullable=True)
    failure_reason: Mapped[str | None] = Column(String, nullable=True)
    sdk: Mapped[str] = Column(String, nullable=False, default="copilot")
    verify: Mapped[bool | None] = Column(Boolean, nullable=True)
    self_review: Mapped[bool | None] = Column(Boolean, nullable=True)
    max_turns: Mapped[int | None] = Column(Integer, nullable=True)
    verify_prompt: Mapped[str | None] = Column(Text, nullable=True)
    self_review_prompt: Mapped[str | None] = Column(Text, nullable=True)
    created_at: Mapped[datetime] = Column(TZDateTime, nullable=False)
    updated_at: Mapped[datetime] = Column(TZDateTime, nullable=False)
    completed_at: Mapped[datetime | None] = Column(TZDateTime, nullable=True)
    version: Mapped[int] = Column(Integer, nullable=False, default=1, server_default="1")
    parent_job_id: Mapped[str | None] = Column(String, ForeignKey("jobs.id"), nullable=True)
    story_text: Mapped[str | None] = Column(Text, nullable=True)


class EventRow(Base):
    __tablename__ = "events"

    id: Mapped[int] = Column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = Column(String, nullable=False, unique=True)
    job_id: Mapped[str] = Column(String, ForeignKey("jobs.id"), nullable=False)
    kind: Mapped[str] = Column(String, nullable=False)
    timestamp: Mapped[datetime] = Column(TZDateTime, nullable=False)
    payload: Mapped[str] = Column(Text, nullable=False)  # JSON

    __table_args__ = (Index("idx_events_job_id", "job_id"),)


class ApprovalRow(Base):
    __tablename__ = "approvals"

    id: Mapped[str] = Column(String, primary_key=True)
    job_id: Mapped[str] = Column(String, ForeignKey("jobs.id"), nullable=False, index=True)
    description: Mapped[str] = Column(Text, nullable=False)
    proposed_action: Mapped[str | None] = Column(Text, nullable=True)
    requested_at: Mapped[datetime] = Column(TZDateTime, nullable=False)
    resolved_at: Mapped[datetime | None] = Column(TZDateTime, nullable=True)
    resolution: Mapped[str | None] = Column(String, nullable=True)
    # Hard-blocked operations (e.g. git reset --hard) set this to True so that
    # blanket trust grants cannot auto-resolve them.
    requires_explicit_approval: Mapped[bool] = Column(Boolean, nullable=False, server_default="0")


class ArtifactRow(Base):
    __tablename__ = "artifacts"

    id: Mapped[str] = Column(String, primary_key=True)
    job_id: Mapped[str] = Column(String, ForeignKey("jobs.id"), nullable=False)
    name: Mapped[str] = Column(String, nullable=False)
    type: Mapped[str] = Column(String, nullable=False)
    mime_type: Mapped[str] = Column(String, nullable=False)
    size_bytes: Mapped[int] = Column(Integer, nullable=False)
    disk_path: Mapped[str] = Column(String, nullable=False)
    phase: Mapped[str] = Column(String, nullable=False)
    step_id: Mapped[str | None] = Column(String(36), nullable=True)
    created_at: Mapped[datetime] = Column(TZDateTime, nullable=False)


class DiffSnapshotRow(Base):
    __tablename__ = "diff_snapshots"

    id = Column(String, primary_key=True)
    job_id = Column(String, ForeignKey("jobs.id"), nullable=False)
    snapshot_at = Column(TZDateTime, nullable=False)
    diff_json = Column(Text, nullable=False)  # JSON

    __table_args__ = (Index("idx_diff_snapshots_job_id", "job_id"),)


class StepRow(Base):
    __tablename__ = "steps"

    id = Column(String(36), primary_key=True)
    job_id = Column(String(36), ForeignKey("jobs.id", ondelete="CASCADE"), index=True, nullable=False)
    step_number = Column(Integer, nullable=False)
    turn_id = Column(String(36), nullable=True)
    intent = Column(Text, nullable=False, default="")
    title = Column(String(60), nullable=True)
    status = Column(String(20), nullable=False, default="running")
    trigger = Column(String(30), nullable=False)
    tool_count = Column(Integer, nullable=False, default=0)
    agent_message = Column(Text, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    duration_ms = Column(Integer, nullable=True)
    start_sha = Column(String(40), nullable=True)
    end_sha = Column(String(40), nullable=True)
    files_read = Column(Text, nullable=True)  # JSON array
    files_written = Column(Text, nullable=True)  # JSON array
    # Transcript context at step close (migration 0020)
    preceding_context = Column(Text, nullable=True)  # JSON array

    __table_args__ = (Index("ix_steps_job_number", "job_id", "step_number"),)


class JobTelemetrySummaryRow(Base):
    """Denormalized per-job telemetry — upserted on every telemetry event."""

    __tablename__ = "job_telemetry_summary"

    job_id = Column(String, ForeignKey("jobs.id"), primary_key=True)
    sdk = Column(String, nullable=False)
    model = Column(String, nullable=False, default="")
    repo = Column(String, nullable=False, default="")
    branch = Column(String, nullable=False, default="")
    status = Column(String, nullable=False, default="running")
    created_at = Column(TZDateTime, nullable=False)
    completed_at = Column(TZDateTime, nullable=True)
    duration_ms = Column(Integer, nullable=False, default=0)
    input_tokens = Column(Integer, nullable=False, default=0)
    output_tokens = Column(Integer, nullable=False, default=0)
    cache_read_tokens = Column(Integer, nullable=False, default=0)
    cache_write_tokens = Column(Integer, nullable=False, default=0)
    total_cost_usd = Column(Float, nullable=False, default=0.0)
    premium_requests = Column(Float, nullable=False, default=0.0)
    llm_call_count = Column(Integer, nullable=False, default=0)
    total_llm_duration_ms = Column(Integer, nullable=False, default=0)
    tool_call_count = Column(Integer, nullable=False, default=0)
    tool_failure_count = Column(Integer, nullable=False, default=0)
    total_tool_duration_ms = Column(Integer, nullable=False, default=0)
    compactions = Column(Integer, nullable=False, default=0)
    tokens_compacted = Column(Integer, nullable=False, default=0)
    approval_count = Column(Integer, nullable=False, default=0)
    approval_wait_ms = Column(Integer, nullable=False, default=0)
    agent_messages = Column(Integer, nullable=False, default=0)
    operator_messages = Column(Integer, nullable=False, default=0)
    context_window_size = Column(Integer, nullable=False, default=0)
    current_context_tokens = Column(Integer, nullable=False, default=0)
    quota_json = Column(Text, nullable=True)
    updated_at = Column(TZDateTime, nullable=False)
    # Cost analytics columns (migration 0009)
    total_turns = Column(Integer, nullable=False, default=0, server_default="0")
    retry_count = Column(Integer, nullable=False, default=0, server_default="0")
    retry_cost_usd = Column(Float, nullable=False, default=0.0, server_default="0.0")
    file_read_count = Column(Integer, nullable=False, default=0, server_default="0")
    file_write_count = Column(Integer, nullable=False, default=0, server_default="0")
    unique_files_read = Column(Integer, nullable=False, default=0, server_default="0")
    file_reread_count = Column(Integer, nullable=False, default=0, server_default="0")
    peak_turn_cost_usd = Column(Float, nullable=False, default=0.0, server_default="0.0")
    avg_turn_cost_usd = Column(Float, nullable=False, default=0.0, server_default="0.0")
    cost_first_half_usd = Column(Float, nullable=False, default=0.0, server_default="0.0")
    cost_second_half_usd = Column(Float, nullable=False, default=0.0, server_default="0.0")
    diff_lines_added = Column(Integer, nullable=False, default=0, server_default="0")
    diff_lines_removed = Column(Integer, nullable=False, default=0, server_default="0")
    agent_error_count = Column(Integer, nullable=False, default=0, server_default="0")
    subagent_cost_usd = Column(Float, nullable=False, default=0.0, server_default="0")


class JobTelemetrySpanRow(Base):
    """Individual LLM or tool call — append-only."""

    __tablename__ = "job_telemetry_spans"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String, ForeignKey("jobs.id"), nullable=False)
    span_type = Column(String, nullable=False)
    name = Column(String, nullable=False)
    started_at = Column(Text, nullable=False)  # float stored as text
    duration_ms = Column(Text, nullable=False)
    attrs_json = Column(Text, nullable=False)
    created_at = Column(TZDateTime, nullable=False)
    # Cost analytics columns (migration 0008)
    tool_category = Column(String, nullable=True)
    tool_target = Column(String, nullable=True)
    turn_number = Column(Integer, nullable=True)
    execution_phase = Column(String, nullable=True)
    is_retry = Column(Boolean, nullable=True, default=False)
    retries_span_id = Column(Integer, nullable=True)
    input_tokens = Column(Integer, nullable=True)
    output_tokens = Column(Integer, nullable=True)
    cache_read_tokens = Column(Integer, nullable=True)
    cache_write_tokens = Column(Integer, nullable=True)
    cost_usd = Column(Float, nullable=True)
    tool_args_json = Column(Text, nullable=True)
    result_size_bytes = Column(Integer, nullable=True)
    error_kind = Column(String, nullable=True)
    # Transcript linkage (migration 0018)
    turn_id = Column(String, nullable=True)
    # Motivation tracking (migration 0019)
    preceding_context = Column(Text, nullable=True)
    motivation_summary = Column(Text, nullable=True)
    # Per-edit motivations with edit keys (migration 0021)
    edit_motivations = Column(Text, nullable=True)  # JSON array

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

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String, ForeignKey("jobs.id"), nullable=False)
    file_path = Column(String, nullable=False)
    access_type = Column(String, nullable=False)  # read / write
    turn_number = Column(Integer, nullable=True)
    span_id = Column(Integer, nullable=True)
    byte_count = Column(Integer, nullable=True)
    created_at = Column(TZDateTime, nullable=False)

    __table_args__ = (
        Index("idx_file_access_job", "job_id"),
        Index("idx_file_access_path", "file_path"),
    )


class CostAttributionRow(Base):
    """Per-job cost breakdown by dimension (phase, tool category, turn)."""

    __tablename__ = "job_cost_attribution"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String, ForeignKey("jobs.id"), nullable=False)
    dimension = Column(String, nullable=False)
    bucket = Column(String, nullable=False)
    cost_usd = Column(Float, nullable=False, default=0.0, server_default="0.0")
    input_tokens = Column(Integer, nullable=False, default=0, server_default="0")
    output_tokens = Column(Integer, nullable=False, default=0, server_default="0")
    call_count = Column(Integer, nullable=False, default=0, server_default="0")
    created_at = Column(TZDateTime, nullable=False)

    __table_args__ = (
        Index("idx_attr_job", "job_id"),
        Index("idx_attr_dimension", "dimension", "bucket"),
    )


class CostObservationRow(Base):
    """Cross-job cost observation or anomaly."""

    __tablename__ = "cost_observations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    category = Column(String, nullable=False)
    severity = Column(String, nullable=False)
    title = Column(String, nullable=False)
    detail = Column(Text, nullable=False)
    evidence_json = Column(Text, nullable=False)
    job_count = Column(Integer, nullable=False, default=0, server_default="0")
    total_waste_usd = Column(Float, nullable=False, default=0.0, server_default="0.0")
    first_seen_at = Column(TZDateTime, nullable=False)
    last_seen_at = Column(TZDateTime, nullable=False)
    dismissed = Column(Boolean, nullable=False, default=False, server_default="0")

    __table_args__ = (
        Index("idx_obs_category", "category"),
        Index("idx_obs_severity", "severity"),
    )


class TrailNodeRow(Base):
    """Agent audit trail node — structured intent graph."""

    __tablename__ = "trail_nodes"

    id = Column(String(36), primary_key=True)
    job_id = Column(String(36), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    seq = Column(Integer, nullable=False)
    anchor_seq = Column(Integer, nullable=False)
    parent_id = Column(String(36), nullable=True)
    kind = Column(String(20), nullable=False)
    deterministic_kind = Column(String(20), nullable=True)
    phase = Column(String(30), nullable=True)
    timestamp = Column(TZDateTime, nullable=False)
    enrichment = Column(String(10), nullable=False, server_default="pending")
    # Intent (populated by enrichment, nullable)
    intent = Column(Text, nullable=True)
    rationale = Column(Text, nullable=True)
    outcome = Column(Text, nullable=True)
    # Anchors (populated deterministically)
    step_id = Column(String(36), nullable=True)
    span_ids = Column(Text, nullable=True)  # JSON array
    turn_id = Column(String(36), nullable=True)
    files = Column(Text, nullable=True)  # JSON array
    start_sha = Column(String(40), nullable=True)
    end_sha = Column(String(40), nullable=True)
    # Transcript context (pass-through from step_completed)
    preceding_context = Column(Text, nullable=True)  # JSON snapshot
    agent_message = Column(Text, nullable=True)
    tool_names = Column(Text, nullable=True)  # JSON array
    tool_count = Column(Integer, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    # Plan/activity (populated by enrichment or native plan)
    title = Column(Text, nullable=True)
    plan_item_id = Column(String(36), nullable=True)
    plan_item_label = Column(Text, nullable=True)
    plan_item_status = Column(String(10), nullable=True)
    activity_id = Column(String(36), nullable=True)
    activity_label = Column(Text, nullable=True)
    # Edges
    supersedes = Column(String(36), nullable=True)
    tags = Column(Text, nullable=True)  # JSON array

    __table_args__ = (
        Index("ix_trail_nodes_job_id", "job_id"),
        Index("ix_trail_nodes_job_seq", "job_id", "seq"),
        Index("ix_trail_nodes_display_order", "job_id", "anchor_seq", "seq"),
        Index("ix_trail_nodes_parent", "parent_id"),
        Index("ix_trail_nodes_kind", "job_id", "kind"),
        Index("ix_trail_nodes_enrichment", "job_id", "enrichment"),
    )
