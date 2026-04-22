"""Trail activity tracker — boundary detection, grouping, and SSE emission."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog

from backend.models.events import DomainEvent, DomainEventKind
from backend.services.trail.models import (
    Activity,
    ActivityStep,
    TrailJobState,
    make_activity_id,
)
from backend.services.trail.prompts import REFINE_ACTIVITY_LABEL_PROMPT, strip_code_fences
from backend.services.trail.title_generator import TitleGenerator

if TYPE_CHECKING:
    from backend.services.event_bus import EventBus
    from backend.services.sister_session import SisterSession

log = structlog.get_logger()


class ActivityTracker:
    """Activity boundary detection, grouping, and SSE emission."""

    def __init__(
        self,
        event_bus: EventBus,
        job_state: dict[str, TrailJobState],
        title_generator: TitleGenerator,
        session_factory: object = None,
    ) -> None:
        self._event_bus = event_bus
        self._job_state = job_state
        self._title_gen = title_generator
        self._session_factory = session_factory

    async def emit_activity_step(
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
        title, merge_prev = await self._title_gen.generate(
            job_id,
            state,
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
                activity_id=make_activity_id(),
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

        prompt = REFINE_ACTIVITY_LABEL_PROMPT.format(
            current_label=activity.label,
            step_titles="\n".join(f"  - {t}" for t in step_titles),
        )

        try:
            raw = await sister.complete(prompt)
            raw = strip_code_fences(raw)
            import json
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
        from backend.models.db import TrailNodeRow
        from sqlalchemy import update

        async with self._session_factory() as session:
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

    @staticmethod
    def _plan_label_for(state: TrailJobState, plan_step_id: str | None) -> str | None:
        if not plan_step_id:
            return None
        return next((s.label for s in state.plan_steps if s.plan_step_id == plan_step_id), None)

    @staticmethod
    def _plan_status_for(state: TrailJobState, plan_step_id: str | None) -> str | None:
        if not plan_step_id:
            return None
        return next((s.status for s in state.plan_steps if s.plan_step_id == plan_step_id), None)
