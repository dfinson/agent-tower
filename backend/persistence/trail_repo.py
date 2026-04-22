"""Trail node persistence — CRUD for agent audit trail records."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from sqlalchemy import func, select, text, update

from backend.models.db import TrailNodeRow

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class TrailNodeRepository:
    """Persistence for trail nodes."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create(self, node: TrailNodeRow) -> None:
        async with self._session_factory() as session:
            session.add(node)
            await session.commit()

    async def create_many(self, nodes: list[TrailNodeRow]) -> None:
        async with self._session_factory() as session:
            session.add_all(nodes)
            await session.commit()

    async def get(self, node_id: str) -> TrailNodeRow | None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(TrailNodeRow).where(TrailNodeRow.id == node_id)
            )
            return result.scalar_one_or_none()

    async def get_by_job(
        self,
        job_id: str,
        *,
        kinds: list[str] | None = None,
        after_seq: int | None = None,
        limit: int | None = None,
    ) -> list[TrailNodeRow]:
        """Fetch trail nodes for a job in display order (anchor_seq, seq)."""
        async with self._session_factory() as session:
            stmt = select(TrailNodeRow).where(TrailNodeRow.job_id == job_id)
            if kinds:
                stmt = stmt.where(TrailNodeRow.kind.in_(kinds))
            if after_seq is not None:
                stmt = stmt.where(TrailNodeRow.seq > after_seq)
            stmt = stmt.order_by(TrailNodeRow.anchor_seq, TrailNodeRow.seq)
            if limit is not None:
                stmt = stmt.limit(limit)
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def get_pending_enrichment(
        self,
        job_id: str | None = None,
        *,
        limit: int,
    ) -> list[TrailNodeRow]:
        """Fetch nodes needing enrichment, oldest first."""
        async with self._session_factory() as session:
            stmt = select(TrailNodeRow).where(
                TrailNodeRow.enrichment.in_(["pending", "failed"])
            )
            if job_id:
                stmt = stmt.where(TrailNodeRow.job_id == job_id)
            stmt = stmt.order_by(TrailNodeRow.seq).limit(limit)
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def update_enrichment(
        self,
        node_id: str,
        *,
        kind: str | None = None,
        intent: str | None = None,
        rationale: str | None = None,
        outcome: str | None = None,
        outcome_status: str | None = None,
        tags: list[str] | None = None,
        supersedes: str | None = None,
        files: list[str] | None = None,
        enrichment: str = "complete",
    ) -> None:
        """Update a node with enrichment results."""
        async with self._session_factory() as session:
            values: dict[str, object] = {"enrichment": enrichment}
            if kind is not None:
                values["kind"] = kind
            if intent is not None:
                values["intent"] = intent
            if rationale is not None:
                values["rationale"] = rationale
            if outcome is not None:
                values["outcome"] = outcome
            if outcome_status is not None:
                values["outcome_status"] = outcome_status
            if tags is not None:
                values["tags"] = json.dumps(tags, ensure_ascii=False)
            if supersedes is not None:
                values["supersedes"] = supersedes
            if files is not None:
                values["files"] = json.dumps(files, ensure_ascii=False)
            stmt = update(TrailNodeRow).where(TrailNodeRow.id == node_id).values(**values)
            await session.execute(stmt)
            await session.commit()

    async def max_seq(self, job_id: str) -> int:
        """Return the highest seq for a job, or 0 if no nodes exist."""
        async with self._session_factory() as session:
            result = await session.execute(
                select(func.coalesce(func.max(TrailNodeRow.seq), 0)).where(
                    TrailNodeRow.job_id == job_id
                )
            )
            return result.scalar_one()

    async def get_recent_decisions(
        self,
        job_id: str,
        *,
        limit: int,
    ) -> list[TrailNodeRow]:
        """Fetch the most recent decide nodes for supersedes linking."""
        async with self._session_factory() as session:
            stmt = (
                select(TrailNodeRow)
                .where(TrailNodeRow.job_id == job_id)
                .where(TrailNodeRow.kind == "decide")
                .order_by(TrailNodeRow.seq.desc())
                .limit(limit)
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def count_by_job(self, job_id: str) -> tuple[int, int]:
        """Return (total_nodes, enriched_nodes) counts for a job."""
        async with self._session_factory() as session:
            total = await session.execute(
                select(func.count()).select_from(TrailNodeRow).where(
                    TrailNodeRow.job_id == job_id
                )
            )
            enriched = await session.execute(
                select(func.count()).select_from(TrailNodeRow).where(
                    TrailNodeRow.job_id == job_id,
                    TrailNodeRow.enrichment == "complete",
                )
            )
            return total.scalar_one(), enriched.scalar_one()

    async def get_untitled_work_nodes(self, *, limit: int) -> list[TrailNodeRow]:
        """Fetch work nodes that have a turn_id but no title (need title recovery)."""
        async with self._session_factory() as session:
            stmt = (
                select(TrailNodeRow)
                .where(TrailNodeRow.turn_id.isnot(None))
                .where(TrailNodeRow.title.is_(None))
                .where(TrailNodeRow.kind.in_(["shell", "modify", "explore"]))
                .order_by(TrailNodeRow.seq)
                .limit(limit)
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def resolve_span_ids(self, nodes: list[TrailNodeRow]) -> dict[str, list[int]]:
        """Look up telemetry span IDs for nodes that have a turn_id.

        Returns {node_id: [span_id, ...]} for nodes whose spans were found.
        Also persists the span_ids on the trail node row.
        """
        nodes_needing = [n for n in nodes if n.turn_id and not n.span_ids]
        if not nodes_needing:
            return {}

        result: dict[str, list[int]] = {}
        async with self._session_factory() as session:
            for node in nodes_needing:
                rows = await session.execute(
                    text(
                        "SELECT id FROM job_telemetry_spans "
                        "WHERE job_id = :jid AND turn_id = :tid "
                        "ORDER BY id"
                    ),
                    {"jid": node.job_id, "tid": node.turn_id},
                )
                ids = [r[0] for r in rows.fetchall()]
                if ids:
                    result[node.id] = ids
                    await session.execute(
                        update(TrailNodeRow)
                        .where(TrailNodeRow.id == node.id)
                        .values(span_ids=json.dumps(ids))
                    )
            await session.commit()
        return result

    async def fetch_motivation_summaries(
        self, nodes: list[TrailNodeRow],
    ) -> dict[str, list[dict[str, str]]]:
        """Fetch motivation_summary data from telemetry spans for trail nodes.

        Returns {node_id: [{tool_target, motivation_summary, tool_category}, ...]}.
        """
        nodes_with_turns = [n for n in nodes if n.turn_id]
        if not nodes_with_turns:
            return {}

        result: dict[str, list[dict[str, str]]] = {}
        async with self._session_factory() as session:
            for node in nodes_with_turns:
                rows = await session.execute(
                    text(
                        "SELECT tool_target, motivation_summary, tool_category, "
                        "       error_kind, is_retry "
                        "FROM job_telemetry_spans "
                        "WHERE job_id = :jid AND turn_id = :tid "
                        "  AND motivation_summary IS NOT NULL "
                        "ORDER BY id"
                    ),
                    {"jid": node.job_id, "tid": node.turn_id},
                )
                spans = [
                    {
                        "tool_target": r["tool_target"] or "",
                        "motivation_summary": r["motivation_summary"] or "",
                        "tool_category": r["tool_category"] or "",
                        "error_kind": r["error_kind"] or "",
                        "is_retry": bool(r["is_retry"]),
                    }
                    for r in rows.mappings()
                ]
                if spans:
                    result[node.id] = spans
        return result

    # ------------------------------------------------------------------
    # Semantic scaffolding queries — consumers read trail as SSOT
    # ------------------------------------------------------------------

    async def get_enriched_nodes(
        self,
        job_id: str,
        *,
        kinds: list[str] | None = None,
        exclude_kinds: list[str] | None = None,
        outcome_status: str | None = None,
    ) -> list[TrailNodeRow]:
        """Fetch enriched trail nodes with optional filtering."""
        async with self._session_factory() as session:
            stmt = (
                select(TrailNodeRow)
                .where(TrailNodeRow.job_id == job_id)
                .where(TrailNodeRow.enrichment == "complete")
            )
            if kinds:
                stmt = stmt.where(TrailNodeRow.kind.in_(kinds))
            if exclude_kinds:
                stmt = stmt.where(TrailNodeRow.kind.notin_(exclude_kinds))
            if outcome_status:
                stmt = stmt.where(TrailNodeRow.outcome_status == outcome_status)
            stmt = stmt.order_by(TrailNodeRow.anchor_seq, TrailNodeRow.seq)
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def get_failed_nodes(self, job_id: str) -> list[TrailNodeRow]:
        """Fetch nodes with outcome_status='failure' that indicate dead ends."""
        return await self.get_enriched_nodes(job_id, outcome_status="failure")

    async def get_decision_nodes(self, job_id: str) -> list[TrailNodeRow]:
        """Fetch decide + request nodes (approval and strategic decision points)."""
        return await self.get_enriched_nodes(
            job_id, kinds=["decide", "request"],
        )

    async def get_backtrack_chains(self, job_id: str) -> list[TrailNodeRow]:
        """Fetch backtrack nodes — pivots where the agent reversed course."""
        return await self.get_enriched_nodes(job_id, kinds=["backtrack"])

    async def get_work_nodes(self, job_id: str) -> list[TrailNodeRow]:
        """Fetch modify + explore + shell nodes — the actual work."""
        return await self.get_enriched_nodes(
            job_id, kinds=["modify", "explore", "shell"],
        )
