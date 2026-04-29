"""Base model and enum definitions shared by all schema modules."""

from __future__ import annotations

from datetime import UTC, datetime  # noqa: TC003 — Pydantic resolves at runtime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, model_validator
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    """Base model that serializes field names to camelCase.

    All datetime fields are guaranteed to include UTC timezone info,
    even when loaded from SQLite (which strips timezone).
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    @model_validator(mode="before")
    @classmethod
    def _ensure_utc_datetimes(cls, data: Any) -> Any:
        """Attach UTC to any naive datetime values before validation."""
        if isinstance(data, dict):
            for key, value in data.items():
                if isinstance(value, datetime) and value.tzinfo is None:
                    data[key] = value.replace(tzinfo=UTC)
        return data


class ErrorResponse(CamelModel):
    """Standard error response shape for HTTP error endpoints."""

    detail: str


class ResolutionAction(StrEnum):
    merge = "merge"
    smart_merge = "smart_merge"
    create_pr = "create_pr"
    discard = "discard"
    agent_merge = "agent_merge"


class ArtifactType(StrEnum):
    diff_snapshot = "diff_snapshot"
    agent_summary = "agent_summary"
    session_snapshot = "session_snapshot"
    session_log = "session_log"
    agent_plan = "agent_plan"
    telemetry_report = "telemetry_report"
    approval_history = "approval_history"
    agent_log = "agent_log"
    document = "document"
    custom = "custom"


class ExecutionPhase(StrEnum):
    environment_setup = "environment_setup"
    agent_reasoning = "agent_reasoning"
    verification = "verification"
    finalization = "finalization"
    post_completion = "post_completion"


class LogLevel(StrEnum):
    debug = "debug"
    info = "info"
    warn = "warn"
    error = "error"


class HealthStatus(StrEnum):
    healthy = "healthy"


class WorkspaceEntryType(StrEnum):
    file = "file"
    directory = "directory"


class TranscriptRole(StrEnum):
    agent = "agent"
    agent_delta = "agent_delta"
    operator = "operator"
    tool_call = "tool_call"
    tool_running = "tool_running"
    tool_output_delta = "tool_output_delta"
    reasoning = "reasoning"
    reasoning_delta = "reasoning_delta"
    divider = "divider"


class DiffLineType(StrEnum):
    context = "context"
    addition = "addition"
    deletion = "deletion"


class DiffFileStatus(StrEnum):
    added = "added"
    modified = "modified"
    deleted = "deleted"
    renamed = "renamed"
