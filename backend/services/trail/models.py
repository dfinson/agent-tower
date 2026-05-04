"""Trail data models — shared state for the trail subsystem."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, TypedDict

if TYPE_CHECKING:
    from datetime import datetime

    from backend.models.events import DomainEvent

# ---------------------------------------------------------------------------
# Buffer size constants — see context_window_eval.py for derivation
# ---------------------------------------------------------------------------

# Eval-backed: context_window_eval.py shows marginal gains < 1-2% beyond 10
# entries for file coverage and motivation context.  Used by StepTracker and
# the classify/title prompts that feed tool intents to a sister LLM.
CONTEXT_WINDOW_SIZE: int = 10

# recent_messages is a signal buffer, not a context window.  Consumers read
# only [0] (plan inference) and [-1] (operator redirect pop).  We keep a
# small window so the operator signal isn't immediately evicted by assistant
# messages; the exact number is not load-bearing.
MESSAGE_SIGNAL_BUFFER_SIZE: int = CONTEXT_WINDOW_SIZE

# Unique tool names accumulate per job.  Agents typically expose 10-30 tools;
# cap at 50 is ~2× observed maximum to prevent unbounded growth from a
# misbehaving agent while never clipping real usage.
TOOL_NAME_VOCAB_CAP: int = 50

# ---------------------------------------------------------------------------
# TypedDict response shapes for TrailQueryService
# ---------------------------------------------------------------------------


class TrailNodeDict(TypedDict):
    """Dict shape returned by ``_node_to_dict``."""

    id: str
    seq: int
    anchor_seq: int | None
    parent_id: str | None
    kind: str
    deterministic_kind: str | None
    phase: str | None
    timestamp: str | None
    enrichment: str | None
    intent: str | None
    rationale: str | None
    outcome: str | None
    step_id: str | None
    span_ids: list[str]
    turn_id: str | None
    files: list[str]
    start_sha: str | None
    end_sha: str | None
    supersedes: str | None
    tags: list[str]
    title: str | None
    agent_message: str | None
    tool_names: list[str]
    tool_count: int | None
    duration_ms: int | None
    plan_item_id: str | None
    plan_item_label: str | None
    plan_item_status: str | None
    activity_id: str | None
    activity_label: str | None
    tier: str | None
    reversible: bool | None
    contained: bool | None
    tier_reason: str | None
    checkpoint_ref: str | None
    children: list[TrailNodeDict]


class TrailResponse(TypedDict):
    """Dict shape returned by ``TrailQueryService.get_trail``."""

    job_id: str
    nodes: list[TrailNodeDict]
    total_nodes: int
    enriched_nodes: int
    complete: bool


class _DecisionDict(TypedDict):
    decision: str
    rationale: str | None


class _BacktrackDict(TypedDict):
    original: str
    replacement: str
    reason: str | None


class TrailSummary(TypedDict):
    """Dict shape returned by ``TrailQueryService.get_summary``."""

    job_id: str
    goals: list[str]
    approach: str | None
    key_decisions: list[_DecisionDict]
    backtracks: list[_BacktrackDict]
    files_explored: int
    files_modified: int
    verifications_passed: int
    verifications_failed: int
    enrichment_complete: bool


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
    native_id: str | None = None  # stable ID from agent's manage_todo_list

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
    plan_step_id: str | None = None


@dataclass
class ActivityStep:
    turn_id: str
    title: str
    activity_id: str
    files_written: list[str] = field(default_factory=list)


@dataclass
class TrailJobState:
    """Per-job transient state for the trail builder + plan orchestrator."""

    # Trail skeleton
    active_goal_id: str | None = None
    active_step_id: str | None = None
    current_phase: str | None = None
    next_seq: int = 1
    pending_events: list[DomainEvent] = field(default_factory=list)

    # Plan management
    plan_steps: list[PlanStep] = field(default_factory=list)
    active_idx: int = -1
    plan_established: bool = False
    native_plan_active: bool = False
    job_prompt: str = ""

    # Transcript context buffers
    #
    # recent_messages: signal buffer for plan inference ([0]) and operator
    # redirect detection ([-1]).  Capped to preserve those two positions
    # while bounding memory; the size itself is not load-bearing.
    #
    # recent_tool_intents: ring buffer fed into the sister-LLM classify
    # prompt.  Uses the eval-backed context_window_eval.py inflection
    # point (same reasoning as StepTracker._BUFFER_SIZE).
    #
    # recent_tool_names: accumulates *unique* names (de-duped on append).
    # Bounded by the agent's tool vocabulary; safety cap prevents abuse.
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

    def to_snapshot(self) -> dict[str, Any]:
        """Serialize transient state for persistence (§13.5)."""
        return {
            "active_goal_id": self.active_goal_id,
            "active_step_id": self.active_step_id,
            "current_phase": self.current_phase,
            "next_seq": self.next_seq,
            "plan_established": self.plan_established,
            "native_plan_active": self.native_plan_active,
            "job_prompt": self.job_prompt,
            "active_idx": self.active_idx,
            "recent_messages": list(self.recent_messages),
            "recent_tool_intents": list(self.recent_tool_intents),
            "recent_tool_names": list(self.recent_tool_names),
            "tool_call_count": self.tool_call_count,
            "last_classified_plan_item": self.last_classified_plan_item,
            "sister_consecutive_failures": self.sister_consecutive_failures,
            "plan_steps": [
                {
                    "plan_step_id": s.plan_step_id,
                    "label": s.label,
                    "status": s.status,
                    "order": s.order,
                    "summary": s.summary,
                    "tool_count": s.tool_count,
                    "files_written": s.files_written,
                    "duration_ms": s.duration_ms,
                    "start_sha": s.start_sha,
                    "end_sha": s.end_sha,
                    "native_id": s.native_id,
                }
                for s in self.plan_steps
            ],
            "activities": [
                {
                    "activity_id": a.activity_id,
                    "label": a.label,
                    "status": a.status,
                }
                for a in self.activities
            ],
            "activity_steps": [
                {
                    "turn_id": s.turn_id,
                    "title": s.title,
                    "activity_id": s.activity_id,
                }
                for s in self.activity_steps
            ],
        }

    @classmethod
    def from_snapshot(cls, data: dict[str, Any]) -> TrailJobState:
        """Restore transient state from a snapshot (§13.5)."""
        state = cls()
        state.active_goal_id = data.get("active_goal_id")
        state.active_step_id = data.get("active_step_id")
        state.current_phase = data.get("current_phase")
        state.next_seq = data.get("next_seq", 1)
        state.plan_established = data.get("plan_established", False)
        state.native_plan_active = data.get("native_plan_active", False)
        state.job_prompt = data.get("job_prompt", "")
        state.active_idx = data.get("active_idx", -1)
        state.recent_messages = data.get("recent_messages", [])
        state.recent_tool_intents = data.get("recent_tool_intents", [])
        state.recent_tool_names = data.get("recent_tool_names", [])
        state.tool_call_count = data.get("tool_call_count", 0)
        state.last_classified_plan_item = data.get("last_classified_plan_item", "")
        state.sister_consecutive_failures = data.get("sister_consecutive_failures", 0)
        state.plan_steps = [
            PlanStep(
                plan_step_id=s["plan_step_id"],
                label=s.get("label", ""),
                status=s.get("status", "pending"),
                order=s.get("order", 0),
                summary=s.get("summary"),
                tool_count=s.get("tool_count", 0),
                files_written=s.get("files_written", []),
                duration_ms=s.get("duration_ms", 0),
                start_sha=s.get("start_sha"),
                end_sha=s.get("end_sha"),
                native_id=s.get("native_id"),
            )
            for s in data.get("plan_steps", [])
        ]
        state.activities = [
            Activity(
                activity_id=a["activity_id"],
                label=a.get("label", "Working"),
                status=a.get("status", "active"),
            )
            for a in data.get("activities", [])
        ]
        state.activity_steps = [
            ActivityStep(
                turn_id=s["turn_id"],
                title=s.get("title", ""),
                activity_id=s["activity_id"],
            )
            for s in data.get("activity_steps", [])
        ]
        return state


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

DETERMINISTIC_KINDS = frozenset({"goal", "explore", "modify", "request", "summarize", "delegate", "shell", "write"})
SEMANTIC_KINDS = frozenset({"plan", "insight", "decide", "backtrack", "verify"})
ALL_KINDS = DETERMINISTIC_KINDS | SEMANTIC_KINDS

SISTER_FAILURE_THRESHOLD = 5
