"""Agent audit trail service — single source of truth for the timeline.

Subscribes to domain events and builds a structured intent graph (TrailNodes)
for every job. Absorbs all responsibilities from ProgressTrackingService:
plan management, turn classification, title generation, activity grouping,
and SSE emission.

Phase 1: Deterministic skeleton (no LLM) — fires synchronously from events
Phase 2: Async enrichment (classification + title + semantic patterns) — drain loop
"""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog
from sqlalchemy import select as sa_select

from backend.config import TrailConfig
from backend.models.db import JobRow, TrailNodeRow
from backend.models.events import DomainEvent, DomainEventKind
from backend.persistence.trail_repo import TrailNodeRepository

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from backend.services.event_bus import EventBus
    from backend.services.sister_session import SisterSession, SisterSessionManager

log = structlog.get_logger()

# Valid trail node kinds
_DETERMINISTIC_KINDS = frozenset({"goal", "explore", "modify", "request", "summarize", "delegate", "shell"})
_SEMANTIC_KINDS = frozenset({"plan", "insight", "decide", "backtrack", "verify"})
_ALL_KINDS = _DETERMINISTIC_KINDS | _SEMANTIC_KINDS


_ENRICH_SYSTEM_PROMPT = (
    "You annotate agent trail nodes with intent, rationale, outcome, and tags. "
    "You also detect semantic patterns (plan, insight, decide, backtrack, verify) "
    "from the agent's transcript. Be concrete: cite file names, function names, "
    "line numbers from the context. Keep fields terse — phrases not paragraphs. "
    "Do NOT invent details not present in the context."
)


# ---------------------------------------------------------------------------
# Prompts (absorbed from ProgressTrackingService)
# ---------------------------------------------------------------------------

_CLASSIFY_PROMPT = """\
You manage a plan for a coding task.  Given the current plan items and the \
latest completed work, determine:

1. Which plan item the work belongs to (by index, 1-based)
2. An updated 1-2 sentence summary for that item
3. Whether the item's status should change
4. If the work substantially changed scope from the original label, provide an updated_label

Current plan:
{plan_block}

Latest completed work:
- Agent message: {agent_msg}
- Tools used: {tools}
- Tool intents: {intents}

Respond with JSON only:
{{"assign_to": <index>, "summary": "<brief summary of the specific work done>",
"status": "<active|done>", "updated_label": "<new label or null>"}}

RULES:
- assign_to is the 1-based index of the plan item this work belongs to.
- If the work clearly finishes this item, set status to "done".
- If work is ongoing, keep status as "active".
- Summary should describe what was specifically done. Be concrete: mention files, functions, endpoints.
- updated_label: only set when the work scope has clearly diverged from the
  original label (e.g. label says "scan" but agent actually fixed bugs).
  Use null when the original label is still accurate.  Concise and specific.
"""

_INFER_PLAN_PROMPT = """\
A coding agent just started working on this task.  Based on the task \
description and the agent's first message, infer the natural steps for this task.

Task: {task}

Agent's first message:
{first_msg}

Respond with JSON only:
{{"items": ["Step 1 label", "Step 2 label", ...]}}

RULES:
- Each label: concise and specific.
- Cover the full task arc from start to finish.
- Be specific: mention files, components, endpoints where possible.
"""


_TITLE_PROMPT = """\
Summarize this completed agent turn for a progress timeline.

Job task: {job_prompt}
Active plan item: {active_plan_label} ({done_count}/{total_count} plan items done)

This turn:
- Files read: {files_read}
- Files written: {files_written}
- Tools used: {tools}
- Duration: {duration_s}s
- Agent message: {agent_msg}

Previous steps in this activity:
{recent_step_titles}

Agent reasoning context (recent transcript before this turn):
{preceding_context}

Generate a concise title describing WHAT WAS DONE, not observations.
The title must be an action the agent performed, not a status or finding.
Bad: "All 9 tests pass"              Good: "Ran test suite — all 9 pass"
Bad: "Issues catalogued"             Good: "Catalogued 6 code smells across 3 files"
Bad: "Reading loop.py"               Good: "Found 8 unannotated functions in loop.py"
Bad: "Editing files"                 Good: "Annotated 3 functions in prompts.py"
Bad: "Exploring codebase"            Good: "Mapped 22 Python files across 8 modules"
Bad: "Code looks clean"              Good: "Reviewed 5 modules, found no issues"

Include file names and quantities when relevant.
Use the reasoning context to explain WHY when the turn is driven by a prior
finding, error, or operator instruction — not just WHAT files changed.

merge_with_previous: set to true ONLY when this turn is a trivial retry of the
exact same operation (e.g. re-running a failed command, fixing a typo in the same
file). If the agent read new files, wrote to different files, or made meaningful
progress, this is a NEW step — set merge_with_previous to false.
When in doubt, set false.

Respond with JSON only:
{{"title": "<concise outcome-focused title>", "merge_with_previous": <true|false>}}
"""

_REFINE_ACTIVITY_LABEL_PROMPT = """\
Refine this activity group label based on the completed work.

Current label: {current_label}
Steps completed:
{step_titles}

Generate a refined 4-10 word label that accurately summarizes ALL the work.
Include quantities when helpful (e.g. "Annotated 4 files in agent/ module").

Respond with JSON only:
{{"label": "<4-10 word refined label>"}}
"""

_TOOL_INTENT_MAX = 80


# ---------------------------------------------------------------------------
# In-memory plan + activity models
# ---------------------------------------------------------------------------


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


def _make_plan_step_id() -> str:
    return f"ps-{uuid.uuid4().hex[:10]}"


def _make_activity_id() -> str:
    return f"act-{uuid.uuid4().hex[:10]}"


def _make_node_id() -> str:
    return uuid.uuid4().hex


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


# ---------------------------------------------------------------------------
# Per-job state (deterministic trail + plan + activity tracking)
# ---------------------------------------------------------------------------


@dataclass
class _TrailJobState:
    """Per-job transient state for the trail builder + plan orchestrator."""

    # Trail skeleton
    active_goal_id: str | None = None
    active_step_id: str | None = None
    current_phase: str | None = None
    next_seq: int = 1
    pending_events: list[DomainEvent] = field(default_factory=list)

    # Plan management (absorbed from ProgressTrackingService)
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
# Deterministic kind classification
# ---------------------------------------------------------------------------


def _classify_step(payload: dict) -> str:
    """Assign node kind from structured step/event data. No LLM."""
    files_written = payload.get("files_written") or []
    files_read = payload.get("files_read") or []
    start_sha = payload.get("start_sha")
    end_sha = payload.get("end_sha")

    if files_written:
        return "modify"
    if start_sha and end_sha and start_sha != end_sha:
        return "modify"
    if files_read:
        return "explore"
    return "shell"


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class TrailService:
    """Builds and enriches the agent audit trail.

    Single source of truth for the timeline. Absorbs plan management,
    turn classification, title generation, activity grouping, and SSE
    emission — all previously in ProgressTrackingService.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        event_bus: EventBus,
        sister_sessions: SisterSessionManager | None = None,
        config: TrailConfig | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._event_bus = event_bus
        self._sister_sessions = sister_sessions
        self._config = config or TrailConfig()
        self._repo = TrailNodeRepository(session_factory)
        self._job_state: dict[str, _TrailJobState] = {}

    # ==================================================================
    # Event subscriber (deterministic skeleton)
    # ==================================================================

    async def handle_event(self, event: DomainEvent) -> None:
        """Domain event subscriber — builds deterministic trail nodes."""
        try:
            if event.kind == DomainEventKind.job_state_changed:
                new_state = (event.payload or {}).get("new_state")
                if new_state == "running" and event.job_id not in self._job_state:
                    await self._on_job_started(event)
            elif event.kind == DomainEventKind.session_resumed:
                await self._on_session_resumed(event)
            elif event.kind == DomainEventKind.step_completed:
                await self._on_step_completed(event)
            elif event.kind == DomainEventKind.step_started:
                self._on_step_started(event)
            elif event.kind == DomainEventKind.execution_phase_changed:
                await self._on_phase_changed(event)
            elif event.kind == DomainEventKind.approval_requested:
                await self._on_approval_requested(event)
            elif event.kind in (
                DomainEventKind.job_completed,
                DomainEventKind.job_failed,
                DomainEventKind.job_canceled,
                DomainEventKind.job_review,
            ):
                await self._on_job_terminal(event)
        except Exception:
            log.debug("trail_event_error", event_kind=event.kind, job_id=event.job_id, exc_info=True)

    async def _on_session_resumed(self, event: DomainEvent) -> None:
        """Rehydrate trail state when a job session resumes (e.g. after server restart)."""
        job_id = event.job_id
        if job_id in self._job_state:
            return  # Already tracking

        state = _TrailJobState()

        # Restore seq counter from persisted nodes
        max_seq = await self._repo.max_seq(job_id)
        state.next_seq = max_seq + 1

        # Restore goal and prompt from persisted goal node
        goal_nodes = await self._repo.get_by_job(job_id, kinds=["goal"], limit=1)
        if goal_nodes:
            state.active_goal_id = goal_nodes[0].id
            state.job_prompt = goal_nodes[0].intent or ""

        # Restore plan steps from persisted PlanStepUpdated events
        from backend.persistence.event_repo import EventRepository
        async with self._session_factory() as session:
            event_repo = EventRepository(session)
            plan_events = await event_repo.list_by_job(
                job_id, [DomainEventKind.plan_step_updated], limit=200,
            )
        if plan_events:
            # Deduplicate: keep the last event per plan_step_id
            latest_by_id: dict[str, DomainEvent] = {}
            for ev in plan_events:
                ps_id = ev.payload.get("plan_step_id")
                if ps_id:
                    latest_by_id[ps_id] = ev
            steps: list[PlanStep] = []
            for ps_id, ev in latest_by_id.items():
                p = ev.payload
                ps = PlanStep(
                    plan_step_id=ps_id,
                    label=str(p.get("label", ""))[:60],
                    status=str(p.get("status", "pending")),
                    order=p.get("order", 0) or 0,
                    summary=p.get("summary"),
                    tool_count=p.get("tool_count", 0) or 0,
                    files_written=p.get("files_written") or [],
                    duration_ms=p.get("duration_ms", 0) or 0,
                    start_sha=p.get("start_sha"),
                    end_sha=p.get("end_sha"),
                )
                steps.append(ps)
            steps.sort(key=lambda s: s.order)
            state.plan_steps = steps
            state.plan_established = bool(steps)
            state.active_idx = next(
                (i for i, s in enumerate(steps) if s.status == "active"), -1
            )

        # Restore activity timeline from persisted trail nodes with titles
        work_nodes = await self._repo.get_by_job(
            job_id, kinds=["shell", "modify", "explore"], limit=500,
        )
        for node in work_nodes:
            if node.turn_id and node.title and node.activity_id:
                act = next(
                    (a for a in state.activities if a.activity_id == node.activity_id),
                    None,
                )
                if act is None:
                    act = Activity(
                        activity_id=node.activity_id,
                        label=node.activity_label or "Working",
                        status="active",
                    )
                    state.activities.append(act)
                state.activity_steps.append(
                    ActivityStep(
                        turn_id=node.turn_id,
                        title=node.title,
                        activity_id=node.activity_id,
                    )
                )

        self._job_state[job_id] = state
        log.info(
            "trail_state_rehydrated",
            job_id=job_id,
            seq=state.next_seq,
            plan_steps=len(state.plan_steps),
            activities=len(state.activities),
        )

    async def _on_job_started(self, event: DomainEvent) -> None:
        """Create the goal node for a new job."""
        job_id = event.job_id
        state = _TrailJobState()
        self._job_state[job_id] = state

        node_id = _make_node_id()
        seq = state.next_seq
        state.next_seq += 1

        # Fetch prompt from the job row
        prompt = ""
        try:
            async with self._session_factory() as session:
                result = await session.execute(
                    sa_select(JobRow).where(JobRow.id == job_id)
                )
                row = result.scalar_one_or_none()
                if row:
                    prompt = row.prompt or ""
        except Exception:
            log.debug("trail_goal_prompt_fetch_failed", job_id=job_id, exc_info=True)

        state.job_prompt = prompt

        node = TrailNodeRow(
            id=node_id,
            job_id=job_id,
            seq=seq,
            anchor_seq=seq,
            parent_id=None,
            kind="goal",
            deterministic_kind="goal",
            phase=state.current_phase,
            timestamp=event.timestamp,
            enrichment="complete",
            intent=prompt or None,
            step_id=None,
            span_ids=None,
            turn_id=None,
            files=None,
            start_sha=None,
            end_sha=None,
        )
        state.active_goal_id = node_id
        await self._repo.create(node)
        log.debug("trail_goal_created", job_id=job_id, node_id=node_id)

    def _on_step_started(self, event: DomainEvent) -> None:
        """Track the currently active step for approval anchoring."""
        state = self._job_state.get(event.job_id)
        if state:
            state.active_step_id = event.payload.get("step_id")

    async def _on_step_completed(self, event: DomainEvent) -> None:
        """Create a deterministic trail node from step completion data.

        Stores transcript context on the node. Then triggers async plan
        classification, title generation, and SSE emission.
        """
        job_id = event.job_id
        state = self._job_state.get(job_id)
        if not state:
            return

        payload = event.payload
        if payload.get("status") == "canceled":
            return

        kind = _classify_step(payload)
        step_id = payload.get("step_id")
        turn_id = payload.get("turn_id")

        files_read = payload.get("files_read") or []
        files_written = payload.get("files_written") or []
        all_files = list(dict.fromkeys(files_written + files_read))

        agent_message = payload.get("agent_message")
        preceding_context = payload.get("preceding_context")
        tool_names = payload.get("tool_names") or []
        tool_count = payload.get("tool_count") or 0
        duration_ms = payload.get("duration_ms") or 0

        node_id = _make_node_id()
        seq = state.next_seq
        state.next_seq += 1

        node = TrailNodeRow(
            id=node_id,
            job_id=job_id,
            seq=seq,
            anchor_seq=seq,
            parent_id=state.active_goal_id,
            kind=kind,
            deterministic_kind=kind,
            phase=state.current_phase,
            timestamp=event.timestamp,
            enrichment="pending",
            step_id=step_id,
            turn_id=turn_id,
            files=json.dumps(all_files, ensure_ascii=False) if all_files else None,
            start_sha=payload.get("start_sha"),
            end_sha=payload.get("end_sha"),
            # Transcript context
            preceding_context=preceding_context,
            agent_message=agent_message,
            tool_names=json.dumps(tool_names, ensure_ascii=False) if tool_names else None,
            tool_count=tool_count,
            duration_ms=duration_ms,
        )
        await self._repo.create(node)
        log.debug(
            "trail_step_node_created",
            job_id=job_id,
            node_id=node_id,
            kind=kind,
            step_id=step_id,
        )

        # Emit any pending events waiting for this step
        if state.pending_events:
            pending = state.pending_events[:]
            state.pending_events.clear()
            for pending_event in pending:
                await self._emit_pending_event(pending_event, state, anchor_seq=seq)

        # --- Plan classification + title + SSE (fire-and-forget) ---
        asyncio.ensure_future(self._classify_and_emit(job_id, node_id, payload))

    async def _classify_and_emit(
        self,
        job_id: str,
        node_id: str,
        payload: dict[str, Any],
    ) -> None:
        """Classify turn to plan item, generate title, emit SSE events.

        Runs as a fire-and-forget task after deterministic node creation.
        Updates the trail node with plan/activity/title data.
        """
        try:
            await self._classify_and_emit_inner(job_id, node_id, payload)
        except Exception:
            log.warning(
                "classify_and_emit_failed",
                job_id=job_id,
                node_id=node_id,
                exc_info=True,
            )
            # Mark the trail node so the title drain loop can retry
            try:
                await self._repo.update_enrichment(node_id, enrichment="pending")
            except Exception:
                pass

    async def _classify_and_emit_inner(
        self,
        job_id: str,
        node_id: str,
        payload: dict[str, Any],
    ) -> None:
        """Inner implementation of classify-and-emit (unwrapped)."""
        state = self._job_state.get(job_id)
        if not state:
            return

        sister = self._sister_sessions.get(job_id) if self._sister_sessions else None

        # Circuit breaker: skip sister session if too many consecutive failures
        _SISTER_FAILURE_THRESHOLD = 5
        if sister and state.sister_consecutive_failures >= _SISTER_FAILURE_THRESHOLD:
            sister = None

        # If plan not established and we have a sister session, infer one.
        # Guard against concurrent inferences from parallel fire-and-forget tasks.
        if sister and not state.plan_established and not state._inferring_plan:
            state._inferring_plan = True
            try:
                await self._infer_plan(job_id, sister)
                state.sister_consecutive_failures = 0
            except Exception:
                state.sister_consecutive_failures += 1
                log.debug("plan_inference_failed_circuit", job_id=job_id, failures=state.sister_consecutive_failures)
            finally:
                state._inferring_plan = False

        agent_msg = payload.get("agent_message", "") or ""
        files_written = payload.get("files_written") or []
        files_read = payload.get("files_read") or []
        tool_count = payload.get("tool_count", 0)
        duration_ms = payload.get("duration_ms", 0) or 0
        start_sha = payload.get("start_sha")
        end_sha = payload.get("end_sha")
        turn_id = payload.get("turn_id")
        preceding_context = payload.get("preceding_context")

        # --- Plan classification ---
        assigned_plan_step_id: str | None = None
        steps = state.plan_steps

        if sister and steps:
            assigned_plan_step_id = await self._classify_and_update_plan(
                job_id,
                sister,
                steps,
                agent_msg=agent_msg,
                tool_count=tool_count,
                files_written=files_written,
                duration_ms=duration_ms,
                start_sha=start_sha,
                end_sha=end_sha,
                turn_id=turn_id,
            )
        elif steps:
            # No sister session — accumulate on active step
            active_idx = max(0, min(state.active_idx, len(steps) - 1))
            if 0 <= active_idx < len(steps):
                ps = steps[active_idx]
                ps.tool_count += tool_count
                ps.duration_ms += duration_ms
                for f in files_written:
                    if f not in ps.files_written:
                        ps.files_written.append(f)
                if start_sha and ps.start_sha is None:
                    ps.start_sha = start_sha
                if end_sha:
                    ps.end_sha = end_sha
                await self._emit_plan_step(job_id, ps)
                await self._emit_card_headline(job_id, ps)
                assigned_plan_step_id = ps.plan_step_id

        # --- Activity timeline: title + grouping + SSE ---
        if turn_id:
            await self._emit_activity_step(
                job_id,
                node_id=node_id,
                sister=sister,
                turn_id=turn_id,
                agent_msg=agent_msg,
                files_read=files_read,
                files_written=files_written,
                duration_ms=duration_ms,
                assigned_plan_step_id=assigned_plan_step_id,
                preceding_context=preceding_context,
            )

    async def _emit_pending_event(
        self,
        event: DomainEvent,
        state: _TrailJobState,
        anchor_seq: int,
    ) -> None:
        """Emit a deferred event (e.g. approval_requested before step_completed)."""
        job_id = event.job_id
        node_id = _make_node_id()
        seq = state.next_seq
        state.next_seq += 1

        node = TrailNodeRow(
            id=node_id,
            job_id=job_id,
            seq=seq,
            anchor_seq=anchor_seq,
            parent_id=state.active_goal_id,
            kind="request",
            deterministic_kind="request",
            phase=state.current_phase,
            timestamp=event.timestamp,
            enrichment="complete",
            intent=event.payload.get("description"),
            step_id=state.active_step_id,
        )
        await self._repo.create(node)
        log.debug("trail_request_node_created", job_id=job_id, node_id=node_id)

    async def _on_phase_changed(self, event: DomainEvent) -> None:
        """Create a summarize node for execution phase transitions."""
        job_id = event.job_id
        state = self._job_state.get(job_id)
        if not state:
            return

        phase = event.payload.get("phase", "unknown")
        state.current_phase = phase

        node_id = _make_node_id()
        seq = state.next_seq
        state.next_seq += 1

        node = TrailNodeRow(
            id=node_id,
            job_id=job_id,
            seq=seq,
            anchor_seq=seq,
            parent_id=state.active_goal_id,
            kind="summarize",
            deterministic_kind="summarize",
            phase=phase,
            timestamp=event.timestamp,
            enrichment="complete",
            intent=f"Phase: {phase}",
        )
        await self._repo.create(node)
        log.debug("trail_summarize_created", job_id=job_id, phase=phase)

    async def _on_approval_requested(self, event: DomainEvent) -> None:
        """Create a request node or defer if step hasn't completed yet."""
        job_id = event.job_id
        state = self._job_state.get(job_id)
        if not state:
            return

        if state.active_step_id:
            state.pending_events.append(event)
            log.debug("trail_request_deferred", job_id=job_id)
        else:
            node_id = _make_node_id()
            seq = state.next_seq
            state.next_seq += 1

            node = TrailNodeRow(
                id=node_id,
                job_id=job_id,
                seq=seq,
                anchor_seq=seq,
                parent_id=state.active_goal_id,
                kind="request",
                deterministic_kind="request",
                phase=state.current_phase,
                timestamp=event.timestamp,
                enrichment="complete",
                intent=event.payload.get("description"),
            )
            await self._repo.create(node)
            log.debug("trail_request_created", job_id=job_id, node_id=node_id)

    async def _on_job_terminal(self, event: DomainEvent) -> None:
        """Create a terminal summarize node and clean up."""
        job_id = event.job_id
        state = self._job_state.get(job_id)
        if not state:
            return

        node_id = _make_node_id()
        seq = state.next_seq
        state.next_seq += 1

        status = "completed" if event.kind == DomainEventKind.job_completed else "failed"
        if event.kind == DomainEventKind.job_canceled:
            status = "canceled"

        node = TrailNodeRow(
            id=node_id,
            job_id=job_id,
            seq=seq,
            anchor_seq=seq,
            parent_id=state.active_goal_id,
            kind="summarize",
            deterministic_kind="summarize",
            phase="terminal",
            timestamp=event.timestamp,
            enrichment="complete",
            intent=f"Job {status}",
        )
        await self._repo.create(node)

        del self._job_state[job_id]
        log.debug("trail_job_terminal", job_id=job_id, status=status)

    # ==================================================================
    # Data ingestion (absorbed from ProgressTrackingService)
    # ==================================================================

    async def start_tracking(self, job_id: str, prompt: str = "") -> None:
        """Initialize plan tracking for a job (called from RuntimeService)."""
        state = self._job_state.get(job_id)
        if state:
            state.job_prompt = prompt

    def stop_tracking(self, job_id: str) -> None:
        """No-op — cleanup happens in _on_job_terminal."""

    def cleanup(self, job_id: str) -> None:
        """Remove all in-memory state for a job."""
        self._job_state.pop(job_id, None)

    async def feed_transcript(
        self,
        job_id: str,
        role: str,
        content: str,
        tool_intent: str = "",
    ) -> None:
        """Buffer transcript data for plan inference and title generation."""
        state = self._job_state.get(job_id)
        if not state:
            return

        if role == "agent" and content:
            state.recent_messages.append(content)
            if len(state.recent_messages) > 5:
                state.recent_messages = state.recent_messages[-5:]

            # Eagerly infer plan on first agent message
            if len(state.recent_messages) == 1 and not state.plan_established:
                await self._try_early_plan(job_id)

        if role == "tool_call" and tool_intent:
            state.recent_tool_intents.append(tool_intent[:_TOOL_INTENT_MAX])
            if len(state.recent_tool_intents) > 10:
                state.recent_tool_intents = state.recent_tool_intents[-10:]

    async def _try_early_plan(self, job_id: str) -> None:
        """Infer plan from the first agent message."""
        if not self._sister_sessions:
            return
        sister = self._sister_sessions.get(job_id)
        if sister is None:
            return
        try:
            await self._infer_plan(job_id, sister)
        except Exception:
            log.debug("early_plan_inference_failed", job_id=job_id, exc_info=True)

    async def feed_tool_name(self, job_id: str, tool_name: str) -> None:
        """Track tool usage for summary context and early plan trigger."""
        state = self._job_state.get(job_id)
        if not state:
            return

        if tool_name not in state.recent_tool_names:
            state.recent_tool_names.append(tool_name)
        if len(state.recent_tool_names) > 10:
            state.recent_tool_names = state.recent_tool_names[-10:]

        state.tool_call_count += 1
        if state.tool_call_count == 3 and not state.plan_established:
            await self._try_early_plan(job_id)

    # ==================================================================
    # Native plan (manage_todo_list)
    # ==================================================================

    _MAX_PLAN_ITEMS = 30

    async def feed_native_plan(self, job_id: str, items: list[dict[str, str]]) -> None:
        """Create/update plan steps from the agent's native todo tool."""
        state = self._job_state.get(job_id)
        if not state:
            return

        status_map = {
            "not-started": "pending",
            "not_started": "pending",
            "in-progress": "active",
            "in_progress": "active",
            "in progress": "active",
            "completed": "done",
            "complete": "done",
            "done": "done",
            "pending": "pending",
            "active": "active",
            "skipped": "skipped",
            "failed": "failed",
            "blocked": "active",
        }

        new_labels: list[tuple[str, str]] = []
        for item in items[:self._MAX_PLAN_ITEMS]:
            label = str(item.get("title") or item.get("content") or item.get("label") or "").strip()
            if not label:
                continue
            raw_status = str(item.get("status", "pending")).strip().lower()
            status = status_map.get(raw_status, "pending")
            new_labels.append((label, status))

        if not new_labels:
            return

        state.native_plan_active = True
        existing_by_label = {s.label: s for s in state.plan_steps}

        updated: list[PlanStep] = []
        now = datetime.now(UTC)

        for i, (label, status) in enumerate(new_labels):
            ps = existing_by_label.get(label)
            if ps:
                ps.order = i
                if ps.status != status:
                    ps.status = status
                    if status == "active" and ps.started_at is None:
                        ps.started_at = now
                    elif status == "done" and ps.completed_at is None:
                        ps.completed_at = now
                updated.append(ps)
            else:
                ps = PlanStep(
                    plan_step_id=_make_plan_step_id(),
                    label=label,
                    status=status,
                    order=i,
                    started_at=now if status == "active" else None,
                    completed_at=now if status == "done" else None,
                )
                updated.append(ps)

        state.plan_steps = updated
        state.plan_established = True
        state.active_idx = next((i for i, s in enumerate(updated) if s.status == "active"), -1)

        for ps in updated:
            await self._emit_plan_step(job_id, ps)

        active_ps = next((s for s in updated if s.status == "active"), None)
        if active_ps:
            await self._emit_card_headline(job_id, active_ps)

    # ==================================================================
    # Plan inference (no native plan)
    # ==================================================================

    async def _infer_plan(self, job_id: str, sister: SisterSession) -> None:
        state = self._job_state.get(job_id)
        if not state:
            return

        task = state.job_prompt
        first_msg = state.recent_messages[0] if state.recent_messages else ""

        if not task and not first_msg:
            return

        prompt = _INFER_PLAN_PROMPT.format(task=task, first_msg=first_msg)

        try:
            raw = await sister.complete(prompt)
            raw = _strip_code_fences(raw)
            parsed = json.loads(raw)
            labels = parsed.get("items", [])
            if not isinstance(labels, list) or not labels:
                return

            now = datetime.now(UTC)
            steps: list[PlanStep] = []
            for i, label in enumerate(labels[:20]):
                if not isinstance(label, str) or not label.strip():
                    continue
                steps.append(
                    PlanStep(
                        plan_step_id=_make_plan_step_id(),
                        label=label.strip()[:60],
                        status="active" if i == 0 else "pending",
                        order=i,
                        started_at=now if i == 0 else None,
                    )
                )

            if steps:
                state.plan_steps = steps
                state.active_idx = 0
                state.plan_established = True
                for ps in steps:
                    await self._emit_plan_step(job_id, ps)
        except Exception:
            log.debug("plan_inference_failed", job_id=job_id, exc_info=True)

    # ==================================================================
    # Turn classification
    # ==================================================================

    async def _classify_and_update_plan(
        self,
        job_id: str,
        sister: SisterSession,
        steps: list[PlanStep],
        *,
        agent_msg: str,
        tool_count: int,
        files_written: list[str],
        duration_ms: int,
        start_sha: str | None,
        end_sha: str | None,
        turn_id: str | None = None,
    ) -> str | None:
        """Classify a turn to a plan item and accumulate metrics."""
        state = self._job_state.get(job_id)
        if not state:
            return None

        active_idx = max(0, min(state.active_idx, len(steps) - 1))

        plan_block = "\n".join(
            f"  {i + 1}. [{s.status}] {s.label}" + (f" -- {s.summary}" if s.summary else "")
            for i, s in enumerate(steps)
        )
        tools = ", ".join(state.recent_tool_names[-6:])
        intents = "; ".join(state.recent_tool_intents[-3:])

        prompt = _CLASSIFY_PROMPT.format(
            plan_block=plan_block,
            agent_msg=agent_msg or "(no message)",
            tools=tools or "(none)",
            intents=intents or "(none)",
        )

        summary = ""
        new_status = "active"
        updated_label: str | None = None
        target_idx = active_idx
        try:
            raw = await sister.complete(prompt)
            raw = _strip_code_fences(raw)
            parsed = json.loads(raw)
            summary = str(parsed.get("summary", ""))[:200]
            new_status = str(parsed.get("status", "active"))
            if new_status not in ("active", "done"):
                new_status = "active"
            ul = parsed.get("updated_label")
            if isinstance(ul, str) and ul.strip():
                updated_label = ul.strip()[:60]

            raw_assign = parsed.get("assign_to")
            if isinstance(raw_assign, int) and 1 <= raw_assign <= len(steps):
                candidate = raw_assign - 1
                # Allow assignment to any item including "done" (rework scenario).
                # Only skip "skipped" items.
                if steps[candidate].status != "skipped" or candidate == active_idx:
                    target_idx = candidate
            state.sister_consecutive_failures = 0
        except Exception:
            state.sister_consecutive_failures += 1
            log.debug("turn_classification_failed", job_id=job_id, exc_info=True)

        now = datetime.now(UTC)
        ps = steps[target_idx]

        # Emit reassignment if classifier moved turn to different plan item
        stamped_step_id = steps[active_idx].plan_step_id
        if target_idx != active_idx and turn_id and ps.plan_step_id != stamped_step_id:
            await self._event_bus.publish(
                DomainEvent(
                    event_id=DomainEvent.make_event_id(),
                    job_id=job_id,
                    timestamp=now,
                    kind=DomainEventKind.step_entries_reassigned,
                    payload={
                        "turn_id": turn_id,
                        "old_step_id": stamped_step_id,
                        "new_step_id": ps.plan_step_id,
                    },
                )
            )

        # Accumulate metrics
        ps.tool_count += tool_count
        ps.duration_ms += duration_ms
        for f in files_written:
            if f not in ps.files_written:
                ps.files_written.append(f)
        if start_sha and ps.start_sha is None:
            ps.start_sha = start_sha
        if end_sha:
            ps.end_sha = end_sha
        if summary:
            ps.summary = summary
        if updated_label:
            ps.label = updated_label

        if ps.status == "pending":
            ps.status = "active"
            ps.started_at = now
        elif ps.status == "done":
            # Rework: reopen a previously completed item
            ps.status = "active"
            ps.completed_at = None

        # If target is ahead of active, mark intermediate steps done
        if target_idx > active_idx:
            for i in range(active_idx, target_idx):
                if steps[i].status == "active":
                    steps[i].status = "done"
                    steps[i].completed_at = now
                    await self._emit_plan_step(job_id, steps[i])
            state.active_idx = target_idx

        if new_status == "done" and ps.status == "active":
            ps.status = "done"
            ps.completed_at = now
            next_idx = next(
                (i for i in range(target_idx + 1, len(steps)) if steps[i].status == "pending"),
                -1,
            )
            if next_idx >= 0:
                steps[next_idx].status = "active"
                steps[next_idx].started_at = now
                state.active_idx = next_idx
                await self._emit_plan_step(job_id, steps[next_idx])

        await self._emit_plan_step(job_id, ps)
        await self._emit_card_headline(job_id, ps)

        return ps.plan_step_id

    # ==================================================================
    # Title generation
    # ==================================================================

    async def _generate_turn_title(
        self,
        job_id: str,
        sister: SisterSession | None,
        *,
        agent_msg: str,
        files_read: list[str],
        files_written: list[str],
        duration_ms: int,
        assigned_plan_step_id: str | None,
        preceding_context: str | None = None,
    ) -> tuple[str, bool]:
        """Generate an outcome-focused title for a completed turn."""
        if not sister:
            if files_written:
                return f"Edited {', '.join(files_written[:3])}", False
            if agent_msg:
                return agent_msg[:60].split("\n")[0], False
            return "Work in progress", False

        state = self._job_state.get(job_id)
        if not state:
            return "Work in progress", False

        steps = state.plan_steps
        active_label = "Unknown"
        done_count = 0
        total_count = len(steps)
        if assigned_plan_step_id:
            for s in steps:
                if s.plan_step_id == assigned_plan_step_id:
                    active_label = s.label
                if s.status == "done":
                    done_count += 1

        current_act_id = state.activities[-1].activity_id if state.activities else None
        recent_titles = [s.title for s in state.activity_steps if s.activity_id == current_act_id][-5:]
        recent_block = "\n".join(f"  - {t}" for t in recent_titles) if recent_titles else "  (none yet)"

        tools = ", ".join(state.recent_tool_names[-6:])

        prompt = _TITLE_PROMPT.format(
            job_prompt=state.job_prompt or "(unknown)",
            active_plan_label=active_label,
            done_count=done_count,
            total_count=total_count,
            files_read=", ".join(files_read[:8]) or "(none)",
            files_written=", ".join(files_written[:8]) or "(none)",
            tools=tools or "(none)",
            duration_s=round(duration_ms / 1000, 1),
            agent_msg=agent_msg or "(no message)",
            recent_step_titles=recent_block,
            preceding_context=preceding_context or "(none)",
        )

        title = "Work in progress"
        merge_prev = False

        try:
            raw = await sister.complete(prompt)
            raw = _strip_code_fences(raw)
            parsed = json.loads(raw)
            tt = parsed.get("title")
            if isinstance(tt, str) and tt.strip():
                title = tt.strip()[:80]
            mp = parsed.get("merge_with_previous")
            if isinstance(mp, bool):
                merge_prev = mp
            state.sister_consecutive_failures = 0
        except Exception:
            state.sister_consecutive_failures += 1
            log.debug("turn_title_generation_failed", job_id=job_id, exc_info=True)
            if files_written:
                title = f"Edited {', '.join(files_written[:3])}"
            elif agent_msg:
                title = agent_msg[:60].split("\n")[0]

        return title, merge_prev

    # ==================================================================
    # Activity grouping + SSE emission
    # ==================================================================

    def _resolve_activity_boundary(
        self,
        job_id: str,
        assigned_plan_step_id: str | None,
        files_written: list[str],
    ) -> tuple[bool, str]:
        """Determine if a new activity should start. Returns (is_new, label)."""
        state = self._job_state.get(job_id)
        if not state:
            return True, "Starting work"

        prev_plan_id = state.last_classified_plan_item

        if assigned_plan_step_id and assigned_plan_step_id != prev_plan_id and prev_plan_id:
            label = next(
                (s.label for s in state.plan_steps if s.plan_step_id == assigned_plan_step_id),
                "Working",
            )
            return True, label

        if not state.activities:
            if assigned_plan_step_id:
                label = next(
                    (s.label for s in state.plan_steps if s.plan_step_id == assigned_plan_step_id),
                    "Starting work",
                )
            else:
                label = "Starting work"
            return True, label

        return False, state.activities[-1].label

    async def _emit_activity_step(
        self,
        job_id: str,
        *,
        node_id: str,
        sister: SisterSession | None,
        turn_id: str,
        agent_msg: str,
        files_read: list[str],
        files_written: list[str],
        duration_ms: int,
        assigned_plan_step_id: str | None,
        preceding_context: str | None = None,
    ) -> None:
        """Generate step title, resolve activity boundary, emit turn_summary, update trail node."""
        state = self._job_state.get(job_id)
        if not state:
            return

        # 1. Resolve activity boundary
        is_new_activity, activity_label = self._resolve_activity_boundary(
            job_id, assigned_plan_step_id, files_written,
        )

        if assigned_plan_step_id:
            state.last_classified_plan_item = assigned_plan_step_id

        # 2. Generate title
        title, merge_prev = await self._generate_turn_title(
            job_id,
            sister,
            agent_msg=agent_msg,
            files_read=files_read,
            files_written=files_written,
            duration_ms=duration_ms,
            assigned_plan_step_id=assigned_plan_step_id,
            preceding_context=preceding_context,
        )

        current_activity = state.activities[-1] if state.activities else None

        # 3. Merge with previous step if indicated
        prev_step = state.activity_steps[-1] if state.activity_steps else None
        if merge_prev and prev_step and current_activity is not None and not is_new_activity:
            prev_step.title = title
            await self._event_bus.publish(
                DomainEvent(
                    event_id=DomainEvent.make_event_id(),
                    job_id=job_id,
                    timestamp=datetime.now(UTC),
                    kind=DomainEventKind.turn_summary,
                    payload={
                        "turn_id": prev_step.turn_id,
                        "title": title,
                        "activity_id": current_activity.activity_id,
                        "activity_label": current_activity.label,
                        "activity_status": current_activity.status,
                        "is_new_activity": False,
                        "plan_item_id": assigned_plan_step_id,
                    },
                )
            )
            await self._update_node_timeline(
                node_id,
                title=title,
                plan_item_id=assigned_plan_step_id,
                plan_item_label=self._plan_label_for(state, assigned_plan_step_id),
                plan_item_status=self._plan_status_for(state, assigned_plan_step_id),
                activity_id=current_activity.activity_id,
                activity_label=current_activity.label,
            )
            return

        # 4. Handle activity boundary
        if is_new_activity or current_activity is None:
            if current_activity is not None:
                current_activity.status = "done"
                if sister:
                    asyncio.ensure_future(self._refine_activity_label(job_id, sister, current_activity))
            new_act = Activity(
                activity_id=_make_activity_id(),
                label=activity_label,
                status="active",
            )
            state.activities.append(new_act)
            current_activity = new_act

        # 5. Record step and emit
        step = ActivityStep(
            turn_id=turn_id,
            title=title,
            activity_id=current_activity.activity_id,
        )
        state.activity_steps.append(step)

        await self._event_bus.publish(
            DomainEvent(
                event_id=DomainEvent.make_event_id(),
                job_id=job_id,
                timestamp=datetime.now(UTC),
                kind=DomainEventKind.turn_summary,
                payload={
                    "turn_id": turn_id,
                    "title": title,
                    "activity_id": current_activity.activity_id,
                    "activity_label": current_activity.label,
                    "activity_status": current_activity.status,
                    "is_new_activity": is_new_activity,
                    "plan_item_id": assigned_plan_step_id,
                },
            )
        )

        # Update trail node with title + activity
        await self._update_node_timeline(
            node_id,
            title=title,
            plan_item_id=assigned_plan_step_id,
            plan_item_label=self._plan_label_for(state, assigned_plan_step_id),
            plan_item_status=self._plan_status_for(state, assigned_plan_step_id),
            activity_id=current_activity.activity_id,
            activity_label=current_activity.label,
        )

    async def _refine_activity_label(
        self,
        job_id: str,
        sister: SisterSession,
        activity: Activity,
    ) -> None:
        """Refine a closed activity's label based on completed work."""
        state = self._job_state.get(job_id)
        if not state:
            return

        step_titles = [s.title for s in state.activity_steps if s.activity_id == activity.activity_id]
        if not step_titles:
            return

        prompt = _REFINE_ACTIVITY_LABEL_PROMPT.format(
            current_label=activity.label,
            step_titles="\n".join(f"  - {t}" for t in step_titles),
        )

        try:
            raw = await sister.complete(prompt)
            raw = _strip_code_fences(raw)
            parsed = json.loads(raw)
            new_label = parsed.get("label")
            if isinstance(new_label, str) and new_label.strip():
                activity.label = new_label.strip()[:80]
                last_step = next(
                    (s for s in reversed(state.activity_steps) if s.activity_id == activity.activity_id),
                    None,
                )
                if last_step:
                    await self._event_bus.publish(
                        DomainEvent(
                            event_id=DomainEvent.make_event_id(),
                            job_id=job_id,
                            timestamp=datetime.now(UTC),
                            kind=DomainEventKind.turn_summary,
                            payload={
                                "turn_id": last_step.turn_id,
                                "title": last_step.title,
                                "activity_id": activity.activity_id,
                                "activity_label": activity.label,
                                "activity_status": "done",
                                "is_new_activity": False,
                                "plan_item_id": None,
                            },
                        )
                    )
        except Exception:
            log.debug("activity_label_refinement_failed", job_id=job_id, exc_info=True)

    async def _update_node_timeline(
        self,
        node_id: str,
        *,
        title: str,
        plan_item_id: str | None,
        plan_item_label: str | None,
        plan_item_status: str | None,
        activity_id: str,
        activity_label: str,
    ) -> None:
        """Update a trail node with title and plan/activity data."""
        async with self._session_factory() as session:
            from sqlalchemy import update
            stmt = update(TrailNodeRow).where(TrailNodeRow.id == node_id).values(
                title=title,
                plan_item_id=plan_item_id,
                plan_item_label=plan_item_label,
                plan_item_status=plan_item_status,
                activity_id=activity_id,
                activity_label=activity_label,
            )
            await session.execute(stmt)
            await session.commit()

    def _plan_label_for(self, state: _TrailJobState, plan_step_id: str | None) -> str | None:
        if not plan_step_id:
            return None
        return next((s.label for s in state.plan_steps if s.plan_step_id == plan_step_id), None)

    def _plan_status_for(self, state: _TrailJobState, plan_step_id: str | None) -> str | None:
        if not plan_step_id:
            return None
        return next((s.status for s in state.plan_steps if s.plan_step_id == plan_step_id), None)

    # ==================================================================
    # SSE event emission helpers
    # ==================================================================

    async def _emit_plan_step(self, job_id: str, ps: PlanStep) -> None:
        await self._event_bus.publish(
            DomainEvent(
                event_id=DomainEvent.make_event_id(),
                job_id=job_id,
                timestamp=datetime.now(UTC),
                kind=DomainEventKind.plan_step_updated,
                payload=ps.to_event_payload(),
            )
        )

    async def _emit_card_headline(self, job_id: str, ps: PlanStep) -> None:
        await self._event_bus.publish(
            DomainEvent(
                event_id=DomainEvent.make_event_id(),
                job_id=job_id,
                timestamp=datetime.now(UTC),
                kind=DomainEventKind.progress_headline,
                payload={
                    "headline": ps.label,
                    "headline_past": ps.label,
                    "summary": ps.summary or "",
                },
            )
        )

    # ==================================================================
    # Active plan step (for transcript tagging)
    # ==================================================================

    def get_active_plan_step_id(self, job_id: str) -> str | None:
        state = self._job_state.get(job_id)
        if not state:
            return None
        steps = state.plan_steps
        idx = state.active_idx
        if 0 <= idx < len(steps):
            return steps[idx].plan_step_id
        for s in reversed(steps):
            if s.status != "pending":
                return s.plan_step_id
        return steps[0].plan_step_id if steps else None

    # ==================================================================
    # Finalization
    # ==================================================================

    async def finalize(self, job_id: str, succeeded: bool) -> None:
        """Finalize plan steps on job completion."""
        state = self._job_state.get(job_id)
        if not state:
            return

        steps = state.plan_steps
        if not steps:
            return

        now = datetime.now(UTC)
        for ps in steps:
            if ps.status == "active":
                ps.status = "done" if succeeded else "failed"
                if ps.status == "done":
                    ps.completed_at = now
                await self._emit_plan_step(job_id, ps)
            elif ps.status == "pending":
                ps.status = "done" if succeeded else "skipped"
                if ps.status == "done":
                    ps.completed_at = now
                await self._emit_plan_step(job_id, ps)

        # Mark last activity done
        if state.activities and state.activities[-1].status == "active":
            state.activities[-1].status = "done"

    def get_plan_steps(self, job_id: str) -> list[dict[str, str]]:
        state = self._job_state.get(job_id)
        if not state:
            return []
        return [{"label": s.label, "status": s.status} for s in state.plan_steps]

    # ==================================================================
    # Enrichment drain loop (Phase 2 — intent/rationale/semantic nodes)
    # ==================================================================

    async def drain_enrichment(self) -> int:
        """Process a batch of nodes needing enrichment. Returns count processed."""
        if not self._sister_sessions:
            return 0

        nodes = await self._repo.get_pending_enrichment(limit=self._config.enrich_batch_size)
        if not nodes:
            return 0

        processed = 0
        by_job: dict[str, list[TrailNodeRow]] = {}
        for node in nodes:
            by_job.setdefault(node.job_id, []).append(node)

        for job_id, job_nodes in by_job.items():
            try:
                goal_nodes = await self._repo.get_by_job(job_id, kinds=["goal"], limit=1)
                goal_intent = goal_nodes[0].intent if goal_nodes else None

                recent_decisions = await self._repo.get_recent_decisions(
                    job_id, limit=self._config.enrich_decisions_context,
                )

                prompt = _build_enrichment_prompt(job_nodes, goal_intent, recent_decisions)
                full_prompt = f"SYSTEM:\n{_ENRICH_SYSTEM_PROMPT}\n\nUSER:\n{prompt}"
                result = await self._sister_sessions.complete(full_prompt)
                result_text = result if isinstance(result, str) else str(result)

                enrichment_data = _parse_enrichment_response(result_text)
                if not enrichment_data:
                    for node in job_nodes:
                        await self._repo.update_enrichment(node.id, enrichment="failed")
                    continue

                node_map = {n.id: n for n in job_nodes}
                for annotation in enrichment_data.get("annotations", []):
                    nid = annotation.get("node_id")
                    if nid not in node_map:
                        continue

                    source_node = node_map[nid]
                    new_kind = annotation.get("kind")

                    if new_kind and new_kind != source_node.kind:
                        if source_node.kind in ("modify", "explore"):
                            new_kind = None
                        elif new_kind not in _ALL_KINDS:
                            new_kind = None

                    sup = annotation.get("supersedes")
                    if sup:
                        existing = await self._repo.get(sup)
                        if not existing:
                            sup = None

                    files = annotation.get("files")
                    if files and isinstance(files, list):
                        files = [_normalize_path(f) for f in files if isinstance(f, str)]
                    else:
                        files = None

                    await self._repo.update_enrichment(
                        nid,
                        kind=new_kind,
                        intent=annotation.get("intent"),
                        rationale=annotation.get("rationale"),
                        outcome=annotation.get("outcome"),
                        tags=annotation.get("tags") if isinstance(annotation.get("tags"), list) else None,
                        supersedes=sup,
                        files=files,
                    )
                    processed += 1

                for semantic in enrichment_data.get("semantic_nodes", []):
                    s_kind = semantic.get("kind")
                    if s_kind not in _SEMANTIC_KINDS:
                        continue

                    anchor_nid = semantic.get("anchor_node_id")
                    anchor_node = node_map.get(anchor_nid) if anchor_nid else None

                    if anchor_node:
                        anchor_seq = anchor_node.anchor_seq
                        parent_id = anchor_node.parent_id
                    else:
                        anchor_seq = job_nodes[0].anchor_seq
                        parent_id = job_nodes[0].parent_id

                    state = self._job_state.get(job_id)
                    if state:
                        seq = state.next_seq
                        state.next_seq += 1
                    else:
                        seq = await self._repo.max_seq(job_id) + 1

                    sup = semantic.get("supersedes")
                    if sup:
                        existing = await self._repo.get(sup)
                        if not existing:
                            sup = None

                    s_node = TrailNodeRow(
                        id=_make_node_id(),
                        job_id=job_id,
                        seq=seq,
                        anchor_seq=anchor_seq,
                        parent_id=parent_id,
                        kind=s_kind,
                        deterministic_kind=None,
                        phase=anchor_node.phase if anchor_node else None,
                        timestamp=datetime.now(UTC),
                        enrichment="complete",
                        intent=semantic.get("intent"),
                        rationale=semantic.get("rationale"),
                        outcome=semantic.get("outcome"),
                        supersedes=sup,
                        tags=json.dumps(semantic.get("tags", []), ensure_ascii=False),
                    )
                    await self._repo.create(s_node)
                    processed += 1

            except Exception:
                log.debug("trail_enrichment_failed", job_id=job_id, exc_info=True)
                for node in job_nodes:
                    try:
                        await self._repo.update_enrichment(node.id, enrichment="failed")
                    except Exception:
                        pass

        return processed

    async def drain_loop(self) -> None:
        """Run forever, periodically processing nodes needing enrichment and title recovery."""
        while True:
            try:
                count = await self.drain_enrichment()
                if count:
                    log.info("trail_enrichment_batch_processed", count=count)
                title_count = await self.drain_titles()
                if title_count:
                    log.info("trail_title_recovery_batch_processed", count=title_count)
            except Exception:
                log.debug("trail_enrichment_drain_error", exc_info=True)
            await asyncio.sleep(self._config.enrich_interval_seconds)

    async def drain_titles(self) -> int:
        """Recover titles for trail nodes that were created but never got titles.

        This handles the case where _classify_and_emit fire-and-forget tasks
        were lost (e.g. server restart) before generating titles and emitting
        turn_summary events.
        """
        nodes = await self._repo.get_untitled_work_nodes(limit=20)
        if not nodes:
            return 0

        processed = 0
        for node in nodes:
            try:
                # Generate a fallback title from persisted data
                files_written: list[str] = []
                if node.files:
                    all_files = json.loads(node.files)
                    files_written = [f for f in all_files if isinstance(f, str)]

                if files_written:
                    title = f"Edited {', '.join(files_written[:3])}"
                elif node.agent_message:
                    title = node.agent_message[:60].split("\n")[0]
                else:
                    title = "Work in progress"

                # Determine activity grouping
                state = self._job_state.get(node.job_id)
                activity_id = node.activity_id or _make_activity_id()
                activity_label = node.activity_label or "Working"

                if state and not node.activity_id:
                    # Assign to current activity
                    if not state.activities:
                        act = Activity(
                            activity_id=activity_id,
                            label=activity_label,
                            status="active",
                        )
                        state.activities.append(act)
                    current_act = state.activities[-1]
                    activity_id = current_act.activity_id
                    activity_label = current_act.label

                # Update the trail node with the recovered title
                async with self._session_factory() as session:
                    from sqlalchemy import update as sa_update
                    stmt = sa_update(TrailNodeRow).where(TrailNodeRow.id == node.id).values(
                        title=title,
                        activity_id=activity_id,
                        activity_label=activity_label,
                    )
                    await session.execute(stmt)
                    await session.commit()

                # Emit the turn_summary event so the frontend gets it
                is_new_activity = node.activity_id is None  # first time assigning
                await self._event_bus.publish(
                    DomainEvent(
                        event_id=DomainEvent.make_event_id(),
                        job_id=node.job_id,
                        timestamp=node.timestamp,
                        kind=DomainEventKind.turn_summary,
                        payload={
                            "turn_id": node.turn_id,
                            "title": title,
                            "activity_id": activity_id,
                            "activity_label": activity_label,
                            "activity_status": "active",
                            "is_new_activity": is_new_activity,
                            "plan_item_id": node.plan_item_id,
                        },
                    )
                )
                processed += 1
            except Exception:
                log.debug("trail_title_recovery_failed", node_id=node.id, exc_info=True)

        return processed

    # ==================================================================
    # Query helpers (used by API routes)
    # ==================================================================

    async def get_trail(
        self,
        job_id: str,
        *,
        kinds: list[str] | None = None,
        flat: bool = False,
        after_seq: int | None = None,
    ) -> dict:
        """Fetch trail for a job."""
        nodes = await self._repo.get_by_job(job_id, kinds=kinds, after_seq=after_seq)
        total, enriched = await self._repo.count_by_job(job_id)

        node_dicts = [_node_to_dict(n) for n in nodes]

        if flat:
            return {
                "job_id": job_id,
                "nodes": node_dicts,
                "total_nodes": total,
                "enriched_nodes": enriched,
                "complete": total == enriched,
            }

        tree = _build_tree(node_dicts)
        return {
            "job_id": job_id,
            "nodes": tree,
            "total_nodes": total,
            "enriched_nodes": enriched,
            "complete": total == enriched,
        }

    async def get_summary(self, job_id: str) -> dict:
        """Build a lightweight trail summary from node data."""
        nodes = await self._repo.get_by_job(job_id)
        total, enriched = await self._repo.count_by_job(job_id)

        goals: list[str] = []
        approach_parts: list[str] = []
        key_decisions: list[dict] = []
        backtracks: list[dict] = []
        explore_files: set[str] = set()
        modify_files: set[str] = set()
        verify_pass = 0
        verify_fail = 0

        for node in nodes:
            files = json.loads(node.files) if node.files else []

            if node.kind == "goal" and node.intent:
                goals.append(node.intent)
            elif node.kind in ("plan", "modify") and node.intent:
                approach_parts.append(node.intent)
            elif node.kind == "decide" and node.intent:
                key_decisions.append({
                    "decision": node.intent,
                    "rationale": node.rationale,
                })
            elif node.kind == "backtrack" and node.intent:
                backtracks.append({
                    "original": node.supersedes or "(unknown)",
                    "replacement": node.intent,
                    "reason": node.rationale,
                })
            elif node.kind == "explore":
                explore_files.update(files)
            elif node.kind == "verify":
                outcome = (node.outcome or "").lower()
                if "fail" in outcome or "error" in outcome:
                    verify_fail += 1
                else:
                    verify_pass += 1

            if node.kind == "modify":
                modify_files.update(files)

        approach = " → ".join(approach_parts) if approach_parts else None

        return {
            "job_id": job_id,
            "goals": goals,
            "approach": approach,
            "key_decisions": key_decisions,
            "backtracks": backtracks,
            "files_explored": len(explore_files),
            "files_modified": len(modify_files),
            "verifications_passed": verify_pass,
            "verifications_failed": verify_fail,
            "enrichment_complete": total == enriched,
        }


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _strip_code_fences(text: str) -> str:
    """Strip markdown code fences from LLM response."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
        text = text.strip()
    return text


def _build_enrichment_prompt(
    nodes: list[TrailNodeRow],
    goal_intent: str | None,
    recent_decisions: list[TrailNodeRow],
) -> str:
    """Build the enrichment prompt for a batch of nodes."""
    parts: list[str] = []
    parts.append("AGENT TRAIL — annotate these trail nodes and detect semantic patterns.\n")

    if goal_intent:
        parts.append(f"CURRENT GOAL: {goal_intent}\n")

    parts.append("NODES TO ANNOTATE:")
    for node in nodes:
        files = json.loads(node.files) if node.files else []
        kind_note = ""
        if node.kind == "shell":
            kind_note = " (kind=shell means classification was uncertain — reclassify from transcript)"
        elif node.kind == "modify" and not files:
            kind_note = " (SHA divergence detected a write but we don't know which files)"
        parts.append(
            f"  - node_id: {node.id}, kind: {node.kind}, files: {files}{kind_note}"
        )

    # Build per-node step context (now with transcript data)
    for node in nodes:
        parts.append(f"\nSTEP CONTEXT for node {node.id}:")
        if node.agent_message:
            parts.append(f"  Agent message: {node.agent_message}")
        if node.preceding_context:
            parts.append(f"  Preceding context: {node.preceding_context}")
        if node.tool_names:
            parts.append(f"  Tools used: {node.tool_names}")
        if node.intent:
            parts.append(f"  Current intent: {node.intent}")
        files = json.loads(node.files) if node.files else []
        if files:
            parts.append(f"  Files: {', '.join(files)}")
        if node.start_sha and node.end_sha and node.start_sha != node.end_sha:
            parts.append(f"  SHA changed: {node.start_sha} → {node.end_sha}")

    if recent_decisions:
        parts.append("\nRECENT DECISIONS (for supersedes linking):")
        for d in recent_decisions:
            parts.append(f"  - node_id: {d.id}, intent: {d.intent or '(pending)'}")

    parts.append(
        "\nRespond with JSON only. Two arrays:\n"
        '1. "annotations": [{node_id, kind, intent, rationale, outcome, files, tags}]\n'
        '   - For kind=modify or kind=explore: do NOT change the kind\n'
        '   - For kind=shell: reclassify to modify, explore, or verify\n'
        '2. "semantic_nodes": [{kind, intent, rationale, outcome, tags, supersedes, anchor_node_id}]\n'
        '   - kind must be one of: plan, insight, decide, backtrack, verify\n'
        '   - anchor_node_id = the node_id of the deterministic node this semantic node relates to\n'
        '   - supersedes = node_id of prior decide node being reversed (for backtrack/decide only)\n'
    )
    return "\n".join(parts)


def _parse_enrichment_response(text: str) -> dict | None:
    """Parse LLM enrichment response."""
    text = _strip_code_fences(text)
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, ValueError):
        log.debug("trail_enrichment_parse_failed")
    return None


def _normalize_path(path: str) -> str:
    """Normalize a file path to repo-relative."""
    path = path.lstrip("./")
    if path.startswith("/"):
        path = path.lstrip("/")
    return path


def _node_to_dict(node: TrailNodeRow) -> dict:
    """Convert a TrailNodeRow to a response dict."""
    return {
        "id": node.id,
        "seq": node.seq,
        "anchor_seq": node.anchor_seq,
        "parent_id": node.parent_id,
        "kind": node.kind,
        "deterministic_kind": node.deterministic_kind,
        "phase": node.phase,
        "timestamp": node.timestamp,
        "enrichment": node.enrichment,
        "intent": node.intent,
        "rationale": node.rationale,
        "outcome": node.outcome,
        "step_id": node.step_id,
        "span_ids": json.loads(node.span_ids) if node.span_ids else [],
        "turn_id": node.turn_id,
        "files": json.loads(node.files) if node.files else [],
        "start_sha": node.start_sha,
        "end_sha": node.end_sha,
        "supersedes": node.supersedes,
        "tags": json.loads(node.tags) if node.tags else [],
        "title": node.title,
        "agent_message": node.agent_message,
        "tool_names": json.loads(node.tool_names) if node.tool_names else [],
        "tool_count": node.tool_count,
        "duration_ms": node.duration_ms,
        "plan_item_id": node.plan_item_id,
        "plan_item_label": node.plan_item_label,
        "plan_item_status": node.plan_item_status,
        "activity_id": node.activity_id,
        "activity_label": node.activity_label,
        "children": [],
    }


def _build_tree(nodes: list[dict]) -> list[dict]:
    """Build a nested tree from flat node dicts using parent_id."""
    by_id: dict[str, dict] = {}
    roots: list[dict] = []

    for n in nodes:
        by_id[n["id"]] = n

    for n in nodes:
        pid = n.get("parent_id")
        if pid and pid in by_id:
            by_id[pid]["children"].append(n)
        else:
            roots.append(n)

    return roots
