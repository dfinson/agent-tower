"""Trail enrichment drain — async batch enrichment + title recovery."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog
from sqlalchemy.exc import SQLAlchemyError

from backend.config import TrailConfig
from backend.models.db import TrailNodeRow
from backend.models.events import DomainEvent, DomainEventKind
from backend.persistence.trail_repo import TrailNodeRepository
from backend.services.trail.models import (
    ALL_KINDS,
    SEMANTIC_KINDS,
    Activity,
    TrailJobState,
    make_activity_id,
    make_node_id,
)
from backend.services.trail.prompts import (
    ENRICH_SYSTEM_PROMPT,
    build_enrichment_prompt,
    normalize_path,
    parse_enrichment_response,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from backend.services.event_bus import EventBus
    from backend.services.sister_session import SisterSessionManager

log = structlog.get_logger()


class TrailEnricher:
    """Async batch enrichment of trail nodes + title recovery drain loop."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        event_bus: EventBus,
        sister_sessions: SisterSessionManager | None = None,
        config: TrailConfig | None = None,
        *,
        job_state: dict[str, TrailJobState] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._event_bus = event_bus
        self._sister_sessions = sister_sessions
        self._config = config or TrailConfig()
        self._repo = TrailNodeRepository(session_factory)
        self._job_state = job_state if job_state is not None else {}

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

                prompt = build_enrichment_prompt(job_nodes, goal_intent, recent_decisions)
                full_prompt = f"SYSTEM:\n{ENRICH_SYSTEM_PROMPT}\n\nUSER:\n{prompt}"
                result = await self._sister_sessions.complete(full_prompt)
                result_text = result if isinstance(result, str) else str(result)

                enrichment_data = parse_enrichment_response(result_text)
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
                        elif new_kind not in ALL_KINDS:
                            new_kind = None

                    sup = annotation.get("supersedes")
                    if sup:
                        existing = await self._repo.get(sup)
                        if not existing:
                            sup = None

                    files = annotation.get("files")
                    if files and isinstance(files, list):
                        files = [normalize_path(f) for f in files if isinstance(f, str)]
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
                    if s_kind not in SEMANTIC_KINDS:
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
                        id=make_node_id(),
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

            except (SQLAlchemyError, KeyError, ValueError, OSError):
                log.debug("trail_enrichment_failed", job_id=job_id, exc_info=True)
                for node in job_nodes:
                    try:
                        await self._repo.update_enrichment(node.id, enrichment="failed")
                    except SQLAlchemyError:
                        log.debug("enrichment_status_update_failed", node_id=node.id, exc_info=True)

        return processed

    async def drain_titles(self) -> int:
        """Recover titles for trail nodes that were created but never got titles."""
        nodes = await self._repo.get_untitled_work_nodes(limit=20)
        if not nodes:
            return 0

        processed = 0
        for node in nodes:
            try:
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

                state = self._job_state.get(node.job_id)
                activity_id = node.activity_id or make_activity_id()
                activity_label = node.activity_label or "Working"

                if state and not node.activity_id:
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

                async with self._session_factory() as session:
                    from sqlalchemy import update as sa_update
                    stmt = sa_update(TrailNodeRow).where(TrailNodeRow.id == node.id).values(
                        title=title,
                        activity_id=activity_id,
                        activity_label=activity_label,
                    )
                    await session.execute(stmt)
                    await session.commit()

                is_new_activity = node.activity_id is None
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
            except (SQLAlchemyError, KeyError, ValueError, OSError):
                log.debug("trail_title_recovery_failed", node_id=node.id, exc_info=True)

        return processed

    async def drain_loop(self) -> None:
        """Run forever, periodically processing enrichment and title recovery."""
        while True:
            try:
                count = await self.drain_enrichment()
                if count:
                    log.info("trail_enrichment_batch_processed", count=count)
                title_count = await self.drain_titles()
                if title_count:
                    log.info("trail_title_recovery_batch_processed", count=title_count)
            except Exception:
                log.warning("trail_enrichment_drain_error", exc_info=True)
            await asyncio.sleep(self._config.enrich_interval_seconds)
