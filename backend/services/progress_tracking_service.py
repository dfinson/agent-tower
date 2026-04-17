"""Plan-step orchestration — unified plan-item-as-step system.

Plan items are the user-visible steps.  SDK turns are invisible
implementation details bucketed into plan items by the sister session.

Sources of plan items:
1. Native: ``manage_todo_list`` / ``TodoWrite`` tool calls
2. Inferred: sister session generates plan from first agent message

On each SDK turn boundary (step_completed), the sister session
classifies which plan item the turn belongs to and generates a
1-2 sentence summary for that item.
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

from backend.models.events import DomainEvent, DomainEventKind

if TYPE_CHECKING:
    from backend.services.event_bus import EventBus
    from backend.services.sister_session import SisterSession, SisterSessionManager

log = structlog.get_logger()

_MSG_MAX = 500
_TOOL_INTENT_MAX = 80


# ---------------------------------------------------------------------------
# Plan step model (in-memory)
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
            "files_written": self.files_written[:20] if self.files_written else [],
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


# ---------------------------------------------------------------------------
# Activity model (in-memory) — retrospective grouping for the timeline
# ---------------------------------------------------------------------------


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
# Sister session prompts
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
{{"assign_to": <index>, "summary": "<1-2 sentence summary>",
"status": "<active|done>", "updated_label": "<new label or null>"}}

RULES:
- assign_to is the 1-based index of the plan item this work belongs to.
- If the work clearly finishes this item, set status to "done".
- If work is ongoing, keep status as "active".
- Summary should describe what was specifically done in 1-2 sentences.
- Be concrete: mention files, functions, endpoints, not abstractions.
- updated_label: only set when the work scope has clearly diverged from the
  original label (e.g. label says "scan" but agent actually fixed bugs).
  Use null when the original label is still accurate.  3-8 words, imperative.
"""

_INFER_PLAN_PROMPT = """\
A coding agent just started working on this task.  Based on the task \
description and the agent's first message, infer a plan of 3-6 steps.

Task: {task}

Agent's first message:
{first_msg}

Respond with JSON only:
{{"items": ["Step 1 label", "Step 2 label", ...]}}

RULES:
- 3-6 items total.
- Each label: 3-8 words, imperative mood, concrete.
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

Generate a concise title (4-10 words) describing WHAT WAS DONE, not observations.
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
{{"title": "<4-10 word outcome-focused title>", "merge_with_previous": <true|false>}}
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


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class ProgressTrackingService:
    """Orchestrates plan steps for active jobs.

    Plan items are the user-visible "steps".  SDK turns are assigned to
    plan items by the sister session.
    """

    def __init__(
        self,
        sister_sessions: SisterSessionManager,
        event_bus: EventBus,
    ) -> None:
        self._sister_sessions = sister_sessions
        self._event_bus = event_bus

        # Per-job plan steps (ordered list)
        self._plan_steps: dict[str, list[PlanStep]] = {}
        # Active plan step index per job
        self._active_idx: dict[str, int] = {}
        # Plan established? (native todo or inferred)
        self._plan_established: dict[str, bool] = {}
        # Jobs receiving native plan data
        self._native_plan_active: set[str] = set()
        # Transcript context buffers
        self._recent_messages: dict[str, list[str]] = {}
        self._recent_tool_intents: dict[str, list[str]] = {}
        self._recent_tool_names: dict[str, list[str]] = {}
        # Total tool call count per job (for early plan inference trigger)
        self._tool_call_count: dict[str, int] = {}
        # Job task prompts (for plan inference)
        self._job_prompts: dict[str, str] = {}

        # Activity timeline state (retrospective grouping)
        self._activities: dict[str, list[Activity]] = {}
        self._activity_steps: dict[str, list[ActivityStep]] = {}
        # Track last classified plan item per job for activity boundary detection
        self._last_classified_plan_item: dict[str, str] = {}  # job_id → plan_step_id

    # -- Lifecycle -----------------------------------------------------------

    async def start_tracking(self, job_id: str, prompt: str = "") -> None:
        self._plan_steps[job_id] = []
        self._active_idx[job_id] = -1
        self._plan_established[job_id] = False
        self._recent_messages[job_id] = []
        self._recent_tool_intents[job_id] = []
        self._recent_tool_names[job_id] = []
        self._tool_call_count[job_id] = 0
        self._job_prompts[job_id] = prompt
        self._activities[job_id] = []
        self._activity_steps[job_id] = []
        self._last_classified_plan_item[job_id] = ""

    def stop_tracking(self, job_id: str) -> None:
        pass

    def cleanup(self, job_id: str) -> None:
        for store in (
            self._plan_steps,
            self._active_idx,
            self._plan_established,
            self._recent_messages,
            self._recent_tool_intents,
            self._recent_tool_names,
            self._tool_call_count,
            self._job_prompts,
            self._activities,
            self._activity_steps,
            self._last_classified_plan_item,
        ):
            store.pop(job_id, None)
        self._native_plan_active.discard(job_id)

    # -- Data ingestion ------------------------------------------------------

    async def feed_transcript(
        self,
        job_id: str,
        role: str,
        content: str,
        tool_intent: str = "",
    ) -> None:
        if role == "agent" and content:
            buf = self._recent_messages.get(job_id)
            if buf is not None:
                buf.append(content[:_MSG_MAX])
                if len(buf) > 5:
                    self._recent_messages[job_id] = buf[-5:]

                # Eagerly infer plan on first agent message so steps appear
                # immediately instead of waiting for the first step_completed.
                if len(buf) == 1 and not self._plan_established.get(job_id, False):
                    await self._try_early_plan(job_id)

        if role == "tool_call" and tool_intent:
            ibuf = self._recent_tool_intents.get(job_id)
            if ibuf is not None:
                ibuf.append(tool_intent[:_TOOL_INTENT_MAX])
                if len(ibuf) > 10:
                    self._recent_tool_intents[job_id] = ibuf[-10:]

    async def _try_early_plan(self, job_id: str) -> None:
        """Infer plan from the first agent message without waiting for step_completed."""
        sister = self._sister_sessions.get(job_id)
        if sister is None:
            return
        try:
            await self._infer_plan(job_id, sister)
        except Exception:
            log.debug("early_plan_inference_failed", job_id=job_id, exc_info=True)

    async def feed_tool_name(self, job_id: str, tool_name: str) -> None:
        buf = self._recent_tool_names.get(job_id)
        if buf is not None:
            if tool_name not in buf:
                buf.append(tool_name)
            if len(buf) > 10:
                self._recent_tool_names[job_id] = buf[-10:]

        # Count total tool calls (not unique names) for early plan trigger
        count = self._tool_call_count.get(job_id, 0) + 1
        self._tool_call_count[job_id] = count
        if count == 3 and not self._plan_established.get(job_id, False):
            await self._try_early_plan(job_id)

    # -- Native plan (manage_todo_list) --------------------------------------

    async def feed_native_plan(self, job_id: str, items: list[dict[str, str]]) -> None:
        """Create/update plan steps from the agent's native todo tool."""
        status_map = {
            "not-started": "pending",
            "in-progress": "active",
            "in_progress": "active",
            "completed": "done",
            "done": "done",
            "pending": "pending",
            "active": "active",
            "skipped": "skipped",
        }

        new_labels: list[tuple[str, str]] = []
        for item in items:
            label = str(item.get("title") or item.get("content") or item.get("label") or "").strip()
            if not label:
                continue
            raw_status = str(item.get("status", "pending")).strip().lower()
            status = status_map.get(raw_status, "pending")
            new_labels.append((label, status))

        if not new_labels:
            return

        self._native_plan_active.add(job_id)

        existing = self._plan_steps.get(job_id, [])
        existing_by_label = {s.label: s for s in existing}

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

        self._plan_steps[job_id] = updated
        self._plan_established[job_id] = True

        self._active_idx[job_id] = next((i for i, s in enumerate(updated) if s.status == "active"), -1)

        for ps in updated:
            await self._emit_plan_step(job_id, ps)

        # Update card headline from active step
        active_ps = next((s for s in updated if s.status == "active"), None)
        if active_ps:
            await self._emit_card_headline(job_id, active_ps)

    # -- Plan inference (no native plan) -------------------------------------

    async def _infer_plan(self, job_id: str, sister: SisterSession) -> None:
        task = self._job_prompts.get(job_id, "")
        msgs = self._recent_messages.get(job_id, [])
        first_msg = msgs[0] if msgs else ""

        if not task and not first_msg:
            return

        prompt = _INFER_PLAN_PROMPT.format(
            task=task[:500],
            first_msg=first_msg[:500],
        )

        try:
            raw = await sister.complete(prompt, timeout=15)
            raw = raw.strip()
            if raw.startswith("```"):
                raw = re.sub(r"^```[a-zA-Z]*\n?", "", raw)
                raw = re.sub(r"\n?```$", "", raw)
                raw = raw.strip()

            parsed = json.loads(raw)
            labels = parsed.get("items", [])
            if not isinstance(labels, list) or not labels:
                return

            now = datetime.now(UTC)
            steps: list[PlanStep] = []
            for i, label in enumerate(labels[:8]):
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
                self._plan_steps[job_id] = steps
                self._active_idx[job_id] = 0
                self._plan_established[job_id] = True

                for ps in steps:
                    await self._emit_plan_step(job_id, ps)

        except Exception:
            log.debug("plan_inference_failed", job_id=job_id, exc_info=True)

    # -- Turn classification + summary generation ----------------------------

    async def on_turn_completed(
        self,
        job_id: str,
        turn_payload: dict[str, Any],
    ) -> None:
        """Called when an SDK turn (step_completed) fires."""
        sister = self._sister_sessions.get(job_id)

        # If plan not established and we have a sister session, infer one
        if sister and not self._plan_established.get(job_id, False):
            await self._infer_plan(job_id, sister)

        steps = self._plan_steps.get(job_id, [])

        tool_count = turn_payload.get("tool_count", 0)
        agent_msg = turn_payload.get("agent_message", "") or ""
        files_written = turn_payload.get("files_written", []) or []
        files_read = turn_payload.get("files_read", []) or []
        duration_ms = turn_payload.get("duration_ms", 0) or 0
        start_sha = turn_payload.get("start_sha")
        end_sha = turn_payload.get("end_sha")
        turn_id = turn_payload.get("turn_id")

        # Classify turn to a plan item using sister session.
        # Returns the plan_step_id this turn was assigned to.
        assigned_plan_step_id: str | None = None
        if sister and steps:
            assigned_plan_step_id = await self._classify_and_update(
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
        else:
            # No sister session — accumulate metrics on active step without classification
            active_idx = self._active_idx.get(job_id, 0)
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

        # Activity timeline: generate title and assign to plan-derived activity.
        if turn_id:
            await self._emit_activity_step(
                job_id,
                sister=sister,
                turn_id=turn_id,
                agent_msg=agent_msg,
                files_read=files_read,
                files_written=files_written,
                duration_ms=duration_ms,
                assigned_plan_step_id=assigned_plan_step_id,
                preceding_context=turn_payload.get("preceding_context"),
            )

    # -- Activity timeline: plan-derived grouping + focused title generation --

    def _resolve_activity_boundary(
        self,
        job_id: str,
        assigned_plan_step_id: str | None,
        files_written: list[str],
    ) -> tuple[bool, str]:
        """Determine if a new activity should start and return the activity label.

        Activity boundaries are derived from plan step transitions (when a plan
        exists) or file-scope shifts (fallback).

        Returns (is_new_activity, activity_label).
        """
        activities = self._activities.get(job_id, [])
        prev_plan_id = self._last_classified_plan_item.get(job_id, "")

        # Plan-based boundary: different plan step → new activity
        if assigned_plan_step_id and assigned_plan_step_id != prev_plan_id and prev_plan_id:
            # Find label from the plan step
            steps = self._plan_steps.get(job_id, [])
            label = next(
                (s.label for s in steps if s.plan_step_id == assigned_plan_step_id),
                "Working",
            )
            return True, label

        if not activities:
            # First activity — use plan step label or fallback
            steps = self._plan_steps.get(job_id, [])
            if assigned_plan_step_id:
                label = next(
                    (s.label for s in steps if s.plan_step_id == assigned_plan_step_id),
                    "Starting work",
                )
            else:
                label = "Starting work"
            return True, label

        # Sub-split heuristic: within the same plan step, split if the
        # dominant directory of files_written shifts significantly.
        current_activity = activities[-1]
        act_steps = self._activity_steps.get(job_id, [])
        current_act_steps = [s for s in act_steps if s.activity_id == current_activity.activity_id]
        if len(current_act_steps) >= 5:
            # Check if file scope shifted — basic heuristic based on
            # common directory prefix of recent writes vs current writes
            # (lightweight, no LLM needed). Skip for now — only plan
            # transitions drive boundaries. Can be added later.
            pass

        return False, current_activity.label

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
        """Generate an outcome-focused title for a completed turn.

        Returns (title, merge_with_previous).
        """
        if not sister:
            # Fallback: derive title from files written or agent message
            if files_written:
                return f"Edited {', '.join(files_written[:3])}", False
            if agent_msg:
                return agent_msg[:60].split("\n")[0], False
            return "Work in progress", False

        # Build rich context
        steps = self._plan_steps.get(job_id, [])
        active_label = "Unknown"
        done_count = 0
        total_count = len(steps)
        if assigned_plan_step_id:
            for s in steps:
                if s.plan_step_id == assigned_plan_step_id:
                    active_label = s.label
                if s.status == "done":
                    done_count += 1

        activities = self._activities.get(job_id, [])
        act_steps = self._activity_steps.get(job_id, [])
        current_activity = activities[-1] if activities else None
        current_act_id = current_activity.activity_id if current_activity else None
        recent_titles = [s.title for s in act_steps if s.activity_id == current_act_id][-5:]
        recent_block = "\n".join(f"  - {t}" for t in recent_titles) if recent_titles else "  (none yet)"

        tools = ", ".join(self._recent_tool_names.get(job_id, [])[-6:])
        job_prompt = self._job_prompts.get(job_id, "")

        prompt = _TITLE_PROMPT.format(
            job_prompt=job_prompt[:300] if job_prompt else "(unknown)",
            active_plan_label=active_label,
            done_count=done_count,
            total_count=total_count,
            files_read=", ".join(files_read[:8]) or "(none)",
            files_written=", ".join(files_written[:8]) or "(none)",
            tools=tools or "(none)",
            duration_s=round(duration_ms / 1000, 1),
            agent_msg=agent_msg[:_MSG_MAX] if agent_msg else "(no message)",
            recent_step_titles=recent_block,
            preceding_context=preceding_context[:1500] if preceding_context else "(none)",
        )

        title = "Work in progress"
        merge_prev = False

        try:
            raw = await sister.complete(prompt, timeout=15)
            raw = raw.strip()
            if raw.startswith("```"):
                raw = re.sub(r"^```[a-zA-Z]*\n?", "", raw)
                raw = re.sub(r"\n?```$", "", raw)
                raw = raw.strip()

            parsed = json.loads(raw)
            tt = parsed.get("title")
            if isinstance(tt, str) and tt.strip():
                title = tt.strip()[:80]
            mp = parsed.get("merge_with_previous")
            if isinstance(mp, bool):
                merge_prev = mp
        except Exception:
            log.debug("turn_title_generation_failed", job_id=job_id, exc_info=True)
            # Fallback from file context
            if files_written:
                title = f"Edited {', '.join(files_written[:3])}"
            elif agent_msg:
                title = agent_msg[:60].split("\n")[0]

        return title, merge_prev

    async def _emit_activity_step(
        self,
        job_id: str,
        *,
        sister: SisterSession | None,
        turn_id: str,
        agent_msg: str,
        files_read: list[str],
        files_written: list[str],
        duration_ms: int,
        assigned_plan_step_id: str | None,
        preceding_context: str | None = None,
    ) -> None:
        """Generate step title, resolve activity boundary, and emit turn_summary."""
        activities = self._activities.get(job_id, [])
        act_steps = self._activity_steps.get(job_id, [])

        # 1. Resolve activity boundary from plan classification
        is_new_activity, activity_label = self._resolve_activity_boundary(
            job_id,
            assigned_plan_step_id,
            files_written,
        )

        # Update plan item tracking
        if assigned_plan_step_id:
            self._last_classified_plan_item[job_id] = assigned_plan_step_id

        # 2. Generate outcome-focused title (separate, focused LLM call)
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

        current_activity = activities[-1] if activities else None

        # 3. Merge with previous step if indicated
        prev_step = act_steps[-1] if act_steps else None
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
            return

        # 4. Handle activity boundary
        if is_new_activity or current_activity is None:
            # Close previous activity and refine its label
            if current_activity is not None:
                current_activity.status = "done"
                # Fire-and-forget label refinement for the closed activity
                if sister:
                    asyncio.ensure_future(self._refine_activity_label(job_id, sister, current_activity))
            new_act = Activity(
                activity_id=_make_activity_id(),
                label=activity_label,
                status="active",
            )
            activities.append(new_act)
            self._activities[job_id] = activities
            current_activity = new_act

        # 5. Record the step and emit
        step = ActivityStep(
            turn_id=turn_id,
            title=title,
            activity_id=current_activity.activity_id,
        )
        act_steps.append(step)
        self._activity_steps[job_id] = act_steps

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

    async def _refine_activity_label(
        self,
        job_id: str,
        sister: SisterSession,
        activity: Activity,
    ) -> None:
        """Refine a closed activity's label based on completed work."""
        act_steps = self._activity_steps.get(job_id, [])
        step_titles = [s.title for s in act_steps if s.activity_id == activity.activity_id]
        if not step_titles:
            return

        prompt = _REFINE_ACTIVITY_LABEL_PROMPT.format(
            current_label=activity.label,
            step_titles="\n".join(f"  - {t}" for t in step_titles),
        )

        try:
            raw = await sister.complete(prompt, timeout=10)
            raw = raw.strip()
            if raw.startswith("```"):
                raw = re.sub(r"^```[a-zA-Z]*\n?", "", raw)
                raw = re.sub(r"\n?```$", "", raw)
                raw = raw.strip()

            parsed = json.loads(raw)
            new_label = parsed.get("label")
            if isinstance(new_label, str) and new_label.strip():
                activity.label = new_label.strip()[:80]
                # Emit an update so the frontend refreshes the activity label.
                # Re-emit the last step in this activity to carry the updated label.
                last_step = next(
                    (s for s in reversed(act_steps) if s.activity_id == activity.activity_id),
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

    async def _classify_and_update(
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
        """Classify a turn to a plan item and accumulate metrics.

        Returns the plan_step_id this turn was assigned to (or None).
        """
        active_idx = self._active_idx.get(job_id, 0)
        active_idx = max(0, min(active_idx, len(steps) - 1))

        plan_block = "\n".join(
            f"  {i + 1}. [{s.status}] {s.label}" + (f" -- {s.summary}" if s.summary else "")
            for i, s in enumerate(steps)
        )
        tools = ", ".join(self._recent_tool_names.get(job_id, [])[-6:])
        intents = "; ".join(self._recent_tool_intents.get(job_id, [])[-3:])

        prompt = _CLASSIFY_PROMPT.format(
            plan_block=plan_block,
            agent_msg=agent_msg[:300] if agent_msg else "(no message)",
            tools=tools or "(none)",
            intents=intents or "(none)",
        )

        summary = ""
        new_status = "active"
        updated_label: str | None = None
        target_idx = active_idx
        try:
            raw = await sister.complete(prompt, timeout=15)
            raw = raw.strip()
            if raw.startswith("```"):
                raw = re.sub(r"^```[a-zA-Z]*\n?", "", raw)
                raw = re.sub(r"\n?```$", "", raw)
                raw = raw.strip()

            parsed = json.loads(raw)
            summary = str(parsed.get("summary", ""))[:200]
            new_status = str(parsed.get("status", "active"))
            if new_status not in ("active", "done"):
                new_status = "active"
            ul = parsed.get("updated_label")
            if isinstance(ul, str) and ul.strip():
                updated_label = ul.strip()[:60]

            # Honor the sister session's assign_to classification.
            raw_assign = parsed.get("assign_to")
            if isinstance(raw_assign, int) and 1 <= raw_assign <= len(steps):
                candidate = raw_assign - 1  # convert 1-based → 0-based
                # Accept assignment to active, pending, or the step just
                # before active (in case classification catches up late).
                # Avoid assigning to already-done steps to prevent regression.
                if steps[candidate].status in ("active", "pending") or candidate == active_idx:
                    target_idx = candidate

        except Exception:
            log.debug("turn_classification_failed", job_id=job_id, exc_info=True)

        now = datetime.now(UTC)
        ps = steps[target_idx]

        # If the sister assigned to a different step than what the events
        # were stamped with, emit a reassignment so the frontend can move
        # transcript entries from the old step to the correct one.
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

        # Accumulate metrics on the target step.
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

        # If target is ahead of active, mark intermediate steps done and advance.
        if target_idx > active_idx:
            for i in range(active_idx, target_idx):
                if steps[i].status == "active":
                    steps[i].status = "done"
                    steps[i].completed_at = now
                    await self._emit_plan_step(job_id, steps[i])
            self._active_idx[job_id] = target_idx

        if new_status == "done" and ps.status == "active":
            ps.status = "done"
            ps.completed_at = now
            # Auto-advance to next pending step
            next_idx = next(
                (i for i in range(target_idx + 1, len(steps)) if steps[i].status == "pending"),
                -1,
            )
            if next_idx >= 0:
                steps[next_idx].status = "active"
                steps[next_idx].started_at = now
                self._active_idx[job_id] = next_idx
                await self._emit_plan_step(job_id, steps[next_idx])

        await self._emit_plan_step(job_id, ps)
        await self._emit_card_headline(job_id, ps)

        return ps.plan_step_id

    async def _generate_summary(
        self,
        job_id: str,
        sister: SisterSession,
        ps: PlanStep,
        agent_msg: str,
    ) -> None:
        intents = "; ".join(self._recent_tool_intents.get(job_id, [])[-3:])
        tools = ", ".join(self._recent_tool_names.get(job_id, [])[-6:])

        prompt = (
            f"Summarize this coding step in 1-2 sentences. Be specific.\n\n"
            f"Plan item: {ps.label}\n"
            f"Agent message: {agent_msg[:300]}\n"
            f"Tools: {tools}\n"
            f"Tool intents: {intents}\n\n"
            f"Summary:"
        )

        try:
            raw = await sister.complete(prompt, timeout=10)
            summary = raw.strip().strip('"')[:200]
            if summary:
                ps.summary = summary
        except Exception:
            log.debug("summary_generation_failed", job_id=job_id, exc_info=True)

    # -- Active plan step (for transcript tagging) ---------------------------

    def get_active_plan_step_id(self, job_id: str) -> str | None:
        steps = self._plan_steps.get(job_id, [])
        idx = self._active_idx.get(job_id, -1)
        if 0 <= idx < len(steps):
            return steps[idx].plan_step_id
        for s in reversed(steps):
            if s.status != "pending":
                return s.plan_step_id
        return steps[0].plan_step_id if steps else None

    # -- Finalization --------------------------------------------------------

    async def finalize(self, job_id: str, succeeded: bool) -> None:
        steps = self._plan_steps.get(job_id, [])
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
                ps.status = "skipped"
                await self._emit_plan_step(job_id, ps)

        # Mark the last activity as done
        activities = self._activities.get(job_id, [])
        if activities and activities[-1].status == "active":
            activities[-1].status = "done"

    def get_plan_steps(self, job_id: str) -> list[dict[str, str]]:
        return [{"label": s.label, "status": s.status} for s in self._plan_steps.get(job_id, [])]

    # -- Event emission helpers ----------------------------------------------

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


# ---------------------------------------------------------------------------
# Event bus subscriber
# ---------------------------------------------------------------------------


class _ProgressSubscriber:
    """EventBus subscriber that dispatches events to ProgressTrackingService."""

    def __init__(self, service: ProgressTrackingService) -> None:
        self._svc = service

    async def __call__(self, event: DomainEvent) -> None:
        if event.kind == DomainEventKind.step_completed:
            if event.payload.get("status") == "canceled":
                return
            await self._svc.on_turn_completed(event.job_id, event.payload)
