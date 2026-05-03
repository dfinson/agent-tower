"""Trail activity tracker — boundary detection, grouping, and SSE emission."""

from __future__ import annotations

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
        is_new_activity, activity_label, resume_activity = self._resolve_activity_boundary(
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
        if merge_prev and prev_step and current_activity is not None and not is_new_activity and not resume_activity:
            old_turn_id = prev_step.turn_id
            prev_step.title = title
            prev_step.turn_id = turn_id  # Update scroll target to the current turn
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
                plan_item_label=self._plan_label_for(state, assigned_plan_step_id),
                plan_item_status=self._plan_status_for(state, assigned_plan_step_id),
                activity_id=current_activity.activity_id,
                activity_label=current_activity.label,
            )
            return

        # 4. Handle activity boundary
        if resume_activity is not None:
            # Returning to a plan step that already has an activity — resume it
            if current_activity is not None and current_activity is not resume_activity:
                current_activity.status = "done"
                if sister:
                    await self._refine_activity_label(job_id, sister, current_activity)
            resume_activity.status = "active"
            current_activity = resume_activity
            is_new_activity = False
        elif is_new_activity or current_activity is None:
            if current_activity is not None:
                current_activity.status = "done"
                if sister:
                    await self._refine_activity_label(job_id, sister, current_activity)
            new_act = Activity(
                activity_id=make_activity_id(),
                label=activity_label,
                status="active",
                plan_step_id=assigned_plan_step_id,
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
    ) -> tuple[bool, str, Activity | None]:
        """Determine if a new activity should start. Returns (is_new, label, resume_activity).

        When the agent returns to a plan step that already has an activity,
        ``resume_activity`` is set so the caller can reuse it instead of
        creating a duplicate.

        §13.7: Multi-signal boundary detection:
        1. Plan step change (original signal)
        2. File cluster divergence (backend → frontend shift)
        3. Operator redirect (recent operator message)
        4. No-plan fallback (detect shifts via file clusters alone)
        """
        state = self._job_state.get(job_id)
        if not state:
            return True, "Starting work", None

        prev_plan_id = state.last_classified_plan_item

        # Signal 1: Plan step change
        if assigned_plan_step_id and assigned_plan_step_id != prev_plan_id and prev_plan_id:
            # Check if an activity already exists for this plan step
            existing = next(
                (a for a in state.activities if a.plan_step_id == assigned_plan_step_id),
                None,
            )
            if existing is not None:
                return False, existing.label, existing
            label = next(
                (s.label for s in state.plan_steps if s.plan_step_id == assigned_plan_step_id),
                "Working",
            )
            return True, label, None

        # First activity
        if not state.activities:
            if assigned_plan_step_id:
                label = next(
                    (s.label for s in state.plan_steps if s.plan_step_id == assigned_plan_step_id),
                    "Starting work",
                )
            else:
                label = "Starting work"
            return True, label, None

        # Signal 2: Operator redirect — a recent operator message signals focus change
        if state.recent_messages:
            latest_msg = state.recent_messages[-1]
            if latest_msg.startswith("[operator]"):
                # Clear the signal so it only triggers once
                state.recent_messages.pop()
                return True, "Operator redirect", None

        # Signal 3: File cluster divergence — detect when the agent shifts
        # between distinct parts of the codebase (no plan required)
        if files_written and state.activity_steps:
            prev_files = self._recent_activity_files(state)
            if prev_files and self._file_clusters_diverged(prev_files, files_written):
                return True, "Switched focus", None

        return False, state.activities[-1].label, None

    @staticmethod
    def _recent_activity_files(state: TrailJobState) -> list[str]:
        """Get files from the last few activity steps for cluster comparison."""
        # Not available directly — activity_steps only have turn_id/title.
        # Use recent_tool_names as a proxy — not ideal but sufficient.
        # The real files come from the node's files column, but we don't
        # have access to trail nodes here without a DB query.
        return []

    @staticmethod
    def _file_clusters_diverged(
        prev_files: list[str], current_files: list[str],
    ) -> bool:
        """Check if file paths indicate a cluster shift (e.g. backend→frontend)."""
        if not prev_files or not current_files:
            return False

        def _top_dirs(files: list[str]) -> set[str]:
            dirs: set[str] = set()
            for f in files:
                parts = f.replace("\\", "/").split("/")
                if len(parts) > 1:
                    dirs.add(parts[0])
            return dirs

        prev_dirs = _top_dirs(prev_files)
        curr_dirs = _top_dirs(current_files)
        if not prev_dirs or not curr_dirs:
            return False
        # Diverged if there's no overlap in top-level directories
        return not prev_dirs.intersection(curr_dirs)

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
                activity.label = new_label.strip()
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
                # §13.6: Persist refined label to trail_nodes rows
                await self._persist_activity_label(
                    job_id, activity.activity_id, activity.label,
                )
        except (OSError, ValueError, KeyError):
            log.warning("activity_label_refinement_failed", job_id=job_id, exc_info=True)

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

    async def _persist_activity_label(
        self,
        job_id: str,
        activity_id: str,
        label: str,
    ) -> None:
        """Write the refined activity label back to all trail_nodes in this activity (§13.6)."""
        from sqlalchemy import update

        from backend.models.db import TrailNodeRow

        try:
            async with self._session_factory() as session:
                stmt = (
                    update(TrailNodeRow)
                    .where(TrailNodeRow.job_id == job_id)
                    .where(TrailNodeRow.activity_id == activity_id)
                    .values(activity_label=label)
                )
                await session.execute(stmt)
                await session.commit()
        except Exception:
            log.warning(
                "activity_label_persist_failed",
                job_id=job_id,
                activity_id=activity_id,
                exc_info=True,
            )

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
