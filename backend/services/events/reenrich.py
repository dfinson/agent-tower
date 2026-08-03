"""Idempotent re-enrichment of persisted events through TraceForge.

Replays a job's stored ``SessionEvent`` values through a fresh
``traceforge.Enricher`` instance in temporal order so that
classification, visibility, phases, duration_ms, risk scoring, and
tool_display are backfilled on events that predate the inline
enrichment wiring.

The path is bounded (one job at a time), deterministic (same enricher,
same event order → same output), and durable-no-repeat (a marker event
prevents double processing).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog
from traceforge.enricher import Enricher as TFEnricher

from backend.models.events import EventKind, SessionEvent, new_event
from backend.services.events.event_processor import _derive_tool_display

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

log = structlog.get_logger()

# Marker event kind stored after a successful re-enrichment pass.
_REENRICH_MARKER_KIND = EventKind.reenrich_complete


async def reenrich_job_events(
    job_id: str,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    force: bool = False,
) -> int:
    """Re-enrich all persisted events for *job_id* through TraceForge.

    Returns the number of events whose metadata was updated, or 0 if the
    job was already re-enriched (unless *force* is True).

    This is safe to call multiple times — the marker event provides
    durable no-repeat semantics.
    """
    from backend.persistence.event_repo import EventRepository

    async with session_factory() as session:
        repo = EventRepository(session)

        # Check for existing marker
        if not force:
            markers = await repo.list_by_job(
                job_id, [_REENRICH_MARKER_KIND], limit=1
            )
            if markers:
                log.info("reenrich_already_complete", job_id=job_id)
                return 0

        # Load all events in storage order (temporal)
        all_events = await repo.list_all_events_by_job(job_id)
        if not all_events:
            return 0

        # Re-enrich through a fresh TF Enricher
        enricher = TFEnricher()
        updated = 0

        for event in all_events:
            try:
                enriched = enricher.process(event)
            except Exception:
                log.warning(
                    "reenrich_event_failed",
                    job_id=job_id,
                    event_id=event.id,
                    exc_info=True,
                )
                continue

            if enriched is None:
                # Buffered for pairing — will emit on completion
                continue

            events_to_update = enriched if isinstance(enriched, list) else [enriched]

            for e in events_to_update:
                e = _derive_tool_display(e)
                if e.metadata and e.metadata != event.metadata:
                    await repo.update_metadata(
                        event_id=e.id,
                        metadata=e.metadata,
                    )
                    updated += 1

        # Flush any remaining buffered events
        for orphan in enricher.flush():
            orphan = _derive_tool_display(orphan)
            if orphan.metadata:
                await repo.update_metadata(
                    event_id=orphan.id,
                    metadata=orphan.metadata,
                )
                updated += 1

        # Persist the marker event
        marker = new_event(
            session_id=job_id,
            timestamp=datetime.now(UTC),
            kind=_REENRICH_MARKER_KIND,
            payload={"updated_count": updated},
        )
        await _append_marker(session, job_id, marker)

        await session.commit()
        log.info("reenrich_complete", job_id=job_id, updated=updated)
        return updated


async def _append_marker(
    session: AsyncSession,
    job_id: str,
    marker: SessionEvent,
) -> None:
    """Persist the re-enrichment marker event."""
    from backend.models.db import EventRow

    row = EventRow(
        event_id=marker.id,
        job_id=job_id,
        kind=str(marker.kind),
        timestamp=marker.timestamp,
        payload=json.dumps(marker.payload, ensure_ascii=False, default=str),
        event_metadata=json.dumps(
            marker.metadata.model_dump(mode="json") if marker.metadata else {},
            ensure_ascii=False,
            default=str,
        ),
    )
    session.add(row)
