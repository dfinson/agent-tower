"""Trail title generator — produces outcome-focused titles for completed turns."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

from backend.services.trail.models import TrailJobState
from backend.services.trail.prompts import TITLE_PROMPT, strip_code_fences

if TYPE_CHECKING:
    from backend.services.sister_session import SisterSession

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
    ) -> TitleResult:
        """Generate a title and activity boundary decision for a completed turn."""
        if not sister:
            return TitleResult(
                title=self._fallback_title(agent_msg, files_written),
                merge_with_previous=False,
                new_activity=False,
                activity_label=None,
            )

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
        recent_titles = [s.title for s in state.activity_steps if s.activity_id == current_act_id]
        recent_block = "\n".join(f"  - {t}" for t in recent_titles) if recent_titles else "  (none yet)"

        tools = ", ".join(state.recent_tool_names)

        prompt = TITLE_PROMPT.format(
            job_prompt=state.job_prompt or "(unknown)",
            active_plan_label=active_label,
            done_count=done_count,
            total_count=total_count,
            files_read=", ".join(files_read) or "(none)",
            files_written=", ".join(files_written) or "(none)",
            tools=tools or "(none)",
            duration_s=round(duration_ms / 1000, 1),
            agent_msg=agent_msg or "(no message)",
            recent_step_titles=recent_block,
            preceding_context=preceding_context or "(none)",
        )

        title = "Work in progress"
        merge_prev = False
        new_activity = False
        activity_label: str | None = None

        try:
            raw = await sister.complete(prompt)
            raw = strip_code_fences(raw)
            parsed = json.loads(raw)
            tt = parsed.get("title")
            if isinstance(tt, str) and tt.strip():
                title = tt.strip()
            mp = parsed.get("merge_with_previous")
            if isinstance(mp, bool):
                merge_prev = mp
            na = parsed.get("new_activity")
            if isinstance(na, bool):
                new_activity = na
            al = parsed.get("activity_label")
            if isinstance(al, str) and al.strip():
                activity_label = al.strip()
            state.sister_consecutive_failures = 0
        except (OSError, ValueError, KeyError):
            state.sister_consecutive_failures += 1
            log.warning("turn_title_generation_failed", job_id=job_id, exc_info=True)
            title = self._fallback_title(agent_msg, files_written)

        return TitleResult(
            title=title,
            merge_with_previous=merge_prev,
            new_activity=new_activity,
            activity_label=activity_label,
        )

    @staticmethod
    def _fallback_title(agent_msg: str, files_written: list[str]) -> str:
        if files_written:
            return f"Edited {', '.join(files_written[:3])}"
        if agent_msg:
            return agent_msg.split("\n")[0]
        return "Work in progress"
