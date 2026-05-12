"""Trail title generator — produces outcome-focused titles for completed turns."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

from backend.services.trail.prompts import TITLE_PROMPT, strip_code_fences

if TYPE_CHECKING:
    from backend.services.sister_session import SisterSession
    from backend.services.trail.models import TrailJobState

log = structlog.get_logger()


@dataclass(frozen=True, slots=True)
class TitleResult:
    """Result of a title generation call."""

    title: str
    merge_with_previous: bool
    new_activity: bool
    activity_label: str | None


class TitleGenerator:
    """Generates concise titles for completed agent turns via LLM or fallback."""

    async def generate(
        self,
        job_id: str,
        state: TrailJobState,
        sister: SisterSession | None,
        *,
        agent_msg: str,
        files_read: list[str],
        files_written: list[str],
        duration_ms: int,
        assigned_plan_step_id: str | None,
        preceding_context: str | None = None,
    ) -> TitleResult | None:
        """Generate a title and activity boundary decision for a completed turn.

        Returns None if the LLM call fails or sister is unavailable — caller
        should skip emitting a turn_summary rather than emitting garbage.
        """
        if not sister:
            return None

        # Build plan step context
        steps = state.plan_steps
        plan_step_label = "Unknown"
        done_count = 0
        total_count = len(steps)
        if assigned_plan_step_id:
            for s in steps:
                if s.plan_step_id == assigned_plan_step_id:
                    plan_step_label = s.label
                if s.status == "done":
                    done_count += 1

        # Current activity label and turn count within it
        current_act = state.activities[-1] if state.activities else None
        current_label = current_act.label if current_act else state.job_prompt[:60] or "Started"
        steps_in_activity = [
            s for s in state.activity_steps if current_act and s.activity_id == current_act.activity_id
        ]
        turns_in_section = len(steps_in_activity)

        # Build 3-entry recent window from step titles in current activity
        recent_titles = [s.title for s in steps_in_activity[-3:]]
        if recent_titles:
            recent_window = "\n".join(
                f"  [{turns_in_section - len(recent_titles) + i + 1}] {t}" for i, t in enumerate(recent_titles)
            )
        else:
            recent_window = "  (first turn)"

        # Build the NOW line: prefer agent message first-line, fall back to intent/tools
        now_line = self._build_now_line(agent_msg, preceding_context, state.recent_tool_names)

        prompt = TITLE_PROMPT.format(
            current_label=current_label,
            turns_in_section=turns_in_section,
            plan_step_label=plan_step_label,
            done_count=done_count,
            total_count=total_count,
            recent_window=recent_window,
            now_line=now_line,
            files_written_count=len(files_written),
            files_read_count=len(files_read),
        )

        try:
            raw = await sister.complete(prompt)
            raw = strip_code_fences(raw)
            parsed = json.loads(raw)
            title = parsed.get("title", "").strip() or None
            if not title:
                log.warning("turn_title_empty_response", job_id=job_id)
                return None
            merge_prev = parsed.get("merge_with_previous") is True
            boundary = parsed.get("boundary", "same")
            new_activity = boundary == "shift"
            activity_label: str | None = None
            al = parsed.get("label")
            if isinstance(al, str) and al.strip():
                activity_label = al.strip()
            state.sister_consecutive_failures = 0
        except (OSError, ValueError, KeyError):
            state.sister_consecutive_failures += 1
            log.warning("turn_title_generation_failed", job_id=job_id, exc_info=True)
            return None

        return TitleResult(
            title=title,
            merge_with_previous=merge_prev,
            new_activity=new_activity,
            activity_label=activity_label,
        )

    @staticmethod
    def _build_now_line(agent_msg: str, preceding_context: str | None, tool_names: list[str]) -> str:
        """Build the NOW description line from available signals."""
        if agent_msg:
            first_line = agent_msg.split("\n")[0][:120]
            return first_line
        if preceding_context:
            # Extract intent-like content from preceding context
            for line in preceding_context.split("\n"):
                line = line.strip()
                if line and not line.startswith("("):
                    return line[:120]
        if tool_names:
            return f"(tool-only turn: {', '.join(tool_names[-5:])})"
        return "(no message)"
