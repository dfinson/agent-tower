"""Event persistence."""

from __future__ import annotations

import json

from sqlalchemy import func, select

from backend.models.db import EventRow
from backend.models.events import DomainEvent, DomainEventKind
from backend.persistence.repository import BaseRepository


class EventRepository(BaseRepository):
    """Database access for domain event records."""

    @staticmethod
    def _to_domain(row: EventRow) -> DomainEvent:
        return DomainEvent(
            event_id=row.event_id,
            job_id=row.job_id,
            timestamp=row.timestamp,
            kind=DomainEventKind(row.kind),
            payload=json.loads(row.payload),
            db_id=row.id,
        )

    async def append(self, event: DomainEvent) -> int:
        """Persist a domain event. Returns the autoincrement DB id."""
        row = EventRow(
            event_id=event.event_id,
            job_id=event.job_id,
            kind=event.kind.value,
            timestamp=event.timestamp,
            payload=json.dumps(event.payload),
        )
        self._session.add(row)
        await self._session.flush()
        db_id = row.id
        event.db_id = db_id
        return db_id

    async def list_after(
        self,
        after_id: int,
        job_id: str | None = None,
        limit: int = 500,
    ) -> list[DomainEvent]:
        """List events with auto-increment id > after_id, optionally scoped to a job."""
        stmt = select(EventRow).where(EventRow.id > after_id).order_by(EventRow.id)
        if job_id is not None:
            stmt = stmt.where(EventRow.job_id == job_id)
        stmt = stmt.limit(limit)
        result = await self._session.execute(stmt)
        return [self._to_domain(row) for row in result.scalars().all()]

    async def list_by_job(
        self,
        job_id: str,
        kinds: list[DomainEventKind],
        limit: int = 2000,
    ) -> list[DomainEvent]:
        """List all events for a job filtered by kind, ordered by db id."""
        stmt = (
            select(EventRow)
            .where(EventRow.job_id == job_id)
            .where(EventRow.kind.in_([k.value for k in kinds]))
            .order_by(EventRow.id)
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return [self._to_domain(row) for row in result.scalars().all()]

    async def get_latest_progress_preview(self, job_id: str) -> tuple[str, str] | None:
        """Return the latest progress headline and summary for a job, if present."""
        previews = await self.list_latest_progress_previews([job_id])
        return previews.get(job_id)

    async def list_latest_progress_previews(self, job_ids: list[str]) -> dict[str, tuple[str, str]]:
        """Return the latest progress headline and summary for each requested job."""
        if not job_ids:
            return {}

        latest_ids = (
            select(
                EventRow.job_id.label("job_id"),
                func.max(EventRow.id).label("latest_id"),
            )
            .where(EventRow.job_id.in_(job_ids))
            .where(EventRow.kind == DomainEventKind.progress_headline.value)
            .group_by(EventRow.job_id)
            .subquery()
        )

        stmt = select(EventRow).join(latest_ids, EventRow.id == latest_ids.c.latest_id)
        result = await self._session.execute(stmt)

        previews: dict[str, tuple[str, str]] = {}
        for row in result.scalars().all():
            job_id = row.job_id
            payload = json.loads(row.payload)
            previews[job_id] = (
                str(payload.get("headline", "")).strip(),
                str(payload.get("summary", "")).strip(),
            )
        return previews

    async def search_transcript(
        self,
        job_id: str,
        query: str,
        roles: list[str] | None = None,
        step_id: str | None = None,
        limit: int = 50,
    ) -> list[DomainEvent]:
        """Full-text search within a job's transcript events."""
        from sqlalchemy import func, or_

        stmt = select(EventRow).where(
            EventRow.job_id == job_id,
            EventRow.kind == DomainEventKind.transcript_updated.value,
        )
        if roles:
            role_conditions = [EventRow.payload.contains(f'"role": "{role}"') for role in roles]
            stmt = stmt.where(or_(*role_conditions))
        if step_id:
            stmt = stmt.where(EventRow.payload.contains(f'"step_id": "{step_id}"'))

        # Search only content-bearing fields, not the entire JSON payload
        like_pattern = f"%{query}%"
        content_field = func.json_extract(EventRow.payload, "$.content")
        tool_name_field = func.json_extract(EventRow.payload, "$.tool_name")
        tool_display_field = func.json_extract(EventRow.payload, "$.tool_display")
        stmt = stmt.where(
            or_(
                content_field.ilike(like_pattern),
                tool_name_field.ilike(like_pattern),
                tool_display_field.ilike(like_pattern),
            )
        )
        stmt = stmt.order_by(EventRow.id).limit(limit)
        result = await self._session.execute(stmt)
        return [self._to_domain(row) for row in result.scalars().all()]
