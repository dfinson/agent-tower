"""Trail plan manager — plan inference, classification, and native plan ingestion."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog

from backend.models.events import DomainEvent, DomainEventKind
from backend.services.trail.models import (
    CONTEXT_WINDOW_SIZE,
    MESSAGE_SIGNAL_BUFFER_SIZE,
    SISTER_FAILURE_THRESHOLD,
    TOOL_NAME_VOCAB_CAP,
    PlanStep,
    TrailJobState,
    make_plan_step_id,
)
from backend.services.trail.prompts import (
    CLASSIFY_PROMPT,
    INFER_PLAN_PROMPT,
    strip_code_fences,
)

if TYPE_CHECKING:
    from backend.services.event_bus import EventBus
    from backend.services.sister_session import SisterSession, SisterSessionManager

log = structlog.get_logger()

_MAX_PLAN_ITEMS = 30


class PlanManager:
    """Plan state machine — inference, classification, native plan, finalization."""

    def __init__(
        self,
        event_bus: EventBus,
        job_state: dict[str, TrailJobState],
        sister_sessions: SisterSessionManager | None = None,
    ) -> None:
        self._event_bus = event_bus
        self._job_state = job_state
        self._sister_sessions = sister_sessions

    # ------------------------------------------------------------------
    # Transcript ingestion
    # ------------------------------------------------------------------

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
            if len(state.recent_messages) > MESSAGE_SIGNAL_BUFFER_SIZE:
                state.recent_messages = state.recent_messages[-MESSAGE_SIGNAL_BUFFER_SIZE:]

            if len(state.recent_messages) == 1 and not state.plan_established:
                await self._try_early_plan(job_id)

        if role == "tool_call" and tool_intent:
            state.recent_tool_intents.append(tool_intent)
            if len(state.recent_tool_intents) > CONTEXT_WINDOW_SIZE:
                state.recent_tool_intents = state.recent_tool_intents[-CONTEXT_WINDOW_SIZE:]

    async def feed_tool_name(self, job_id: str, tool_name: str) -> None:
        """Track tool usage for summary context and early plan trigger."""
        state = self._job_state.get(job_id)
        if not state:
            return

        if tool_name not in state.recent_tool_names:
            if len(state.recent_tool_names) < TOOL_NAME_VOCAB_CAP:
                state.recent_tool_names.append(tool_name)

        state.tool_call_count += 1
        if state.tool_call_count == 3 and not state.plan_established:
            await self._try_early_plan(job_id)

    async def _try_early_plan(self, job_id: str) -> None:
        """Infer plan from the first agent message."""
        if not self._sister_sessions:
            return
        sister = self._sister_sessions.get(job_id)
        if sister is None:
            return
        try:
            await self.infer_plan(job_id, sister)
        except (OSError, ValueError, KeyError):
            log.warning("early_plan_inference_failed", job_id=job_id, exc_info=True)

    # ------------------------------------------------------------------
    # Plan inference (no native plan)
    # ------------------------------------------------------------------

    async def infer_plan(self, job_id: str, sister: SisterSession) -> None:
        """Infer plan steps from the job prompt and first agent message."""
        state = self._job_state.get(job_id)
        if not state:
            return

        task = state.job_prompt
        first_msg = state.recent_messages[0] if state.recent_messages else ""

        if not task and not first_msg:
            return

        prompt = INFER_PLAN_PROMPT.format(task=task, first_msg=first_msg)

        try:
            raw = await sister.complete(prompt)
            raw = strip_code_fences(raw)
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
                        plan_step_id=make_plan_step_id(),
                        label=label.strip(),
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
        except (OSError, ValueError, KeyError):
            log.warning("plan_inference_failed", job_id=job_id, exc_info=True)

    # ------------------------------------------------------------------
    # Turn classification
    # ------------------------------------------------------------------

    async def classify_and_update_plan(
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
        tools = ", ".join(state.recent_tool_names)
        intents = "; ".join(state.recent_tool_intents)

        prompt = CLASSIFY_PROMPT.format(
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
            raw = strip_code_fences(raw)
            parsed = json.loads(raw)
            summary = str(parsed.get("summary", ""))
            new_status = str(parsed.get("status", "active"))
            if new_status not in ("active", "done"):
                new_status = "active"
            ul = parsed.get("updated_label")
            if isinstance(ul, str) and ul.strip():
                updated_label = ul.strip()

            raw_assign = parsed.get("assign_to")
            if isinstance(raw_assign, int) and 1 <= raw_assign <= len(steps):
                candidate = raw_assign - 1
                if steps[candidate].status != "skipped" or candidate == active_idx:
                    target_idx = candidate
            state.sister_consecutive_failures = 0
        except (OSError, ValueError, KeyError):
            state.sister_consecutive_failures += 1
            log.warning("turn_classification_failed", job_id=job_id, exc_info=True)

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

    # ------------------------------------------------------------------
    # Native plan (manage_todo_list)
    # ------------------------------------------------------------------

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
        for item in items[:_MAX_PLAN_ITEMS]:
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
                    plan_step_id=make_plan_step_id(),
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

    # ------------------------------------------------------------------
    # Finalization
    # ------------------------------------------------------------------

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

        if state.activities and state.activities[-1].status == "active":
            state.activities[-1].status = "done"

    def get_plan_steps(self, job_id: str) -> list[dict[str, str]]:
        state = self._job_state.get(job_id)
        if not state:
            return []
        return [{"label": s.label, "status": s.status} for s in state.plan_steps]

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

    # ------------------------------------------------------------------
    # Orchestration helpers (used by node_builder fire-and-forget)
    # ------------------------------------------------------------------

    async def classify_turn(
        self,
        job_id: str,
        payload: dict[str, Any],
    ) -> str | None:
        """Full classify-and-update cycle for a step_completed payload.

        Infers plan if needed, classifies turn, accumulates on fallback.
        Returns the assigned plan_step_id or None.
        """
        state = self._job_state.get(job_id)
        if not state:
            return None

        sister = self._sister_sessions.get(job_id) if self._sister_sessions else None

        if sister and state.sister_consecutive_failures >= SISTER_FAILURE_THRESHOLD:
            sister = None

        # Infer plan if needed
        if sister and not state.plan_established and not state._inferring_plan:
            state._inferring_plan = True
            try:
                await self.infer_plan(job_id, sister)
                state.sister_consecutive_failures = 0
            except (OSError, ValueError, KeyError):
                state.sister_consecutive_failures += 1
                log.warning("plan_inference_failed_circuit", job_id=job_id, failures=state.sister_consecutive_failures)
            finally:
                state._inferring_plan = False

        agent_msg = payload.get("agent_message", "") or ""
        files_written = payload.get("files_written") or []
        tool_count = payload.get("tool_count", 0)
        duration_ms = payload.get("duration_ms", 0) or 0
        start_sha = payload.get("start_sha")
        end_sha = payload.get("end_sha")
        turn_id = payload.get("turn_id")

        steps = state.plan_steps
        assigned_plan_step_id: str | None = None

        if sister and steps:
            assigned_plan_step_id = await self.classify_and_update_plan(
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

        return assigned_plan_step_id

    def get_sister(self, job_id: str) -> SisterSession | None:
        """Get the sister session for a job (with circuit breaker)."""
        state = self._job_state.get(job_id)
        if not state:
            return None
        sister = self._sister_sessions.get(job_id) if self._sister_sessions else None
        if sister and state.sister_consecutive_failures >= SISTER_FAILURE_THRESHOLD:
            return None
        return sister

    # ------------------------------------------------------------------
    # SSE emission helpers
    # ------------------------------------------------------------------

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
