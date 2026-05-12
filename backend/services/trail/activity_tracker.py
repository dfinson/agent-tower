"""Trail activity tracker — boundary detection, grouping, and SSE emission."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog

from backend.models.events import DomainEvent, DomainEventKind
from backend.services.trail.models import (
    Activity,
    ActivityStep,
    TrailJobState,
    make_activity_id,
)
from backend.services.trail.title_generator import TitleGenerator

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

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
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self._event_bus = event_bus
        self._job_state = job_state
        self._title_gen = title_generator
        self._session_factory: async_sessionmaker[AsyncSession] | None = session_factory

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

        if not sister:
            return

        # Track plan step for context (no longer forces boundaries).
        if assigned_plan_step_id:
            state.last_classified_plan_item = assigned_plan_step_id

        # 1. Generate title + boundary decision (single LLM call).
        #    Returns None on failure — skip this turn entirely rather than
        #    emitting garbage placeholders.
        result = await self._title_gen.generate(
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
        if result is None:
            return

        title = result.title
        merge_prev = result.merge_with_previous
        is_new_activity = result.new_activity
        llm_activity_label = result.activity_label  # May be None

        plan_step_label = self._plan_label_for(state, assigned_plan_step_id)

        # Resolve the label for any new activity.
        # LLM must provide a label when it signals shift; if it didn't,
        # fall back to plan step label or suppress.
        if is_new_activity:
            if llm_activity_label:
                activity_label = llm_activity_label
            elif plan_step_label:
                activity_label = plan_step_label
            else:
                # LLM said shift but gave no label and no plan step context.
                # Suppress — append to current activity instead of garbage.
                is_new_activity = False
                activity_label = ""  # unused
                log.debug(
                    "activity_boundary_suppressed",
                    job_id=job_id,
                    reason="llm_no_label",
                    turn_id=turn_id,
                )
        else:
            activity_label = ""  # unused when not creating

        current_activity = state.activities[-1] if state.activities else None

        # Bootstrap: first turn of a job needs a label for the initial activity.
        if current_activity is None and not is_new_activity and not activity_label:
            activity_label = llm_activity_label or plan_step_label or state.job_prompt[:60] or "Started"

        # 2. Merge with previous step if indicated
        prev_step = state.activity_steps[-1] if state.activity_steps else None
        if merge_prev and prev_step and current_activity is not None and not is_new_activity:
            old_turn_id = prev_step.turn_id
            prev_step.title = title
            prev_step.turn_id = turn_id
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
                        "is_new_activity": False,
                        "plan_item_id": assigned_plan_step_id,
                        "replaces_turn_id": old_turn_id,
                    },
                )
            )
            await self._update_node_timeline(
                node_id,
                title=title,
                plan_item_id=assigned_plan_step_id,
                plan_item_label=plan_step_label,
                plan_item_status=self._plan_status_for(state, assigned_plan_step_id),
                activity_id=current_activity.activity_id,
                activity_label=current_activity.label,
            )
            return

        # 3. Handle activity boundary (LLM-driven via contrast detection).
        if is_new_activity or current_activity is None:
            if current_activity is not None:
                current_activity.status = "done"
            new_act = Activity(
                activity_id=make_activity_id(),
                label=activity_label,
                status="active",
                plan_step_id=assigned_plan_step_id,
            )
            state.activities.append(new_act)
            current_activity = new_act

        # 4. Record step and emit
        step = ActivityStep(
            turn_id=turn_id,
            title=title,
            activity_id=current_activity.activity_id,
            files_written=files_written,
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
            plan_item_label=plan_step_label,
            plan_item_status=self._plan_status_for(state, assigned_plan_step_id),
            activity_id=current_activity.activity_id,
            activity_label=current_activity.label,
        )

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
        if self._session_factory is None:
            return

        from sqlalchemy import update

        from backend.models.db import TrailNodeRow

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
