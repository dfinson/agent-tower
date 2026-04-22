"""Trail data models — shared state for the trail subsystem."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class PlanStep:
    plan_step_id: str
    label: str
    summary: str | None = None
    status: str = "pending"  # pending | active | done | failed | skipped
    order: int = 0
    tool_count: int = 0
    files_written: list[str] = field(default_factory=list)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: int = 0
    start_sha: str | None = None
    end_sha: str | None = None

    def to_event_payload(self) -> dict[str, Any]:
        return {
            "plan_step_id": self.plan_step_id,
            "label": self.label,
            "summary": self.summary,
            "status": self.status,
            "order": self.order,
            "tool_count": self.tool_count,
            "files_written": self.files_written or [],
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration_ms": self.duration_ms or None,
            "start_sha": self.start_sha,
            "end_sha": self.end_sha,
        }


@dataclass
class Activity:
    activity_id: str
    label: str
    status: str = "active"  # active | done


@dataclass
class ActivityStep:
    turn_id: str
    title: str
    activity_id: str


@dataclass
class TrailJobState:
    """Per-job transient state for the trail builder + plan orchestrator."""

    # Trail skeleton
    active_goal_id: str | None = None
    active_step_id: str | None = None
    current_phase: str | None = None
    next_seq: int = 1
    pending_events: list = field(default_factory=list)

    # Plan management
    plan_steps: list[PlanStep] = field(default_factory=list)
    active_idx: int = -1
    plan_established: bool = False
    native_plan_active: bool = False
    job_prompt: str = ""

    # Transcript context buffers
    recent_messages: list[str] = field(default_factory=list)
    recent_tool_intents: list[str] = field(default_factory=list)
    recent_tool_names: list[str] = field(default_factory=list)
    tool_call_count: int = 0

    # Activity timeline (retrospective grouping)
    activities: list[Activity] = field(default_factory=list)
    activity_steps: list[ActivityStep] = field(default_factory=list)
    last_classified_plan_item: str = ""

    # Sister session circuit breaker
    sister_consecutive_failures: int = 0
    _inferring_plan: bool = False


# ---------------------------------------------------------------------------
# ID generators
# ---------------------------------------------------------------------------


def make_plan_step_id() -> str:
    return f"ps-{uuid.uuid4().hex[:10]}"


def make_activity_id() -> str:
    return f"act-{uuid.uuid4().hex[:10]}"


def make_node_id() -> str:
    return uuid.uuid4().hex


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DETERMINISTIC_KINDS = frozenset({"goal", "explore", "modify", "request", "summarize", "delegate", "shell"})
SEMANTIC_KINDS = frozenset({"plan", "insight", "decide", "backtrack", "verify"})
ALL_KINDS = DETERMINISTIC_KINDS | SEMANTIC_KINDS

TOOL_INTENT_MAX = 80
SISTER_FAILURE_THRESHOLD = 5
