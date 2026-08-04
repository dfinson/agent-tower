"""Idempotent re-enrichment of persisted events through TraceForge.

Replays a job's stored ``SessionEvent`` values through a fresh
``traceforge.Enricher`` instance in temporal order so that
classification, visibility, phases, duration_ms, risk scoring, and
tool_display are backfilled on events that predate the inline
enrichment wiring.

The path is bounded (batched pagination, not full memory load),
deterministic (same enricher, same event order → same output),
concurrency-safe (per-job asyncio lock prevents duplicate replay),
and durable-no-repeat (a marker event prevents double processing;
force deletes then re-inserts the marker).
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog
from traceforge.enricher import Enricher as TFEnricher

from backend.models.events import EventKind, SessionEvent, new_event

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

log = structlog.get_logger()

# Marker event kind stored after a successful re-enrichment pass.
_REENRICH_MARKER_KIND = EventKind.reenrich_complete

# Per-job concurrency exclusion — prevents duplicate concurrent re-enrichment.
# Bounded: locks are removed after the reenrich completes (see finally block).
_job_locks: dict[str, asyncio.Lock] = {}

# Batch size for paginated event loading.
_BATCH_SIZE = 500


def _get_job_lock(job_id: str) -> asyncio.Lock:
    """Get or create the per-job asyncio lock."""
    if job_id not in _job_locks:
        _job_locks[job_id] = asyncio.Lock()
    return _job_locks[job_id]


async def reenrich_job_events(
    job_id: str,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    force: bool = False,
) -> int:
    """Re-enrich all persisted events for *job_id* through TraceForge.

    Returns the number of events whose metadata was updated, or 0 if the
    job was already re-enriched (unless *force* is True).

    Concurrency-safe: per-job lock prevents duplicate concurrent replay.
    Bounded: events are loaded in batches of ``_BATCH_SIZE``.
    Durable: force=True deletes the old marker and inserts a fresh one.
    """
    lock = _get_job_lock(job_id)
    if lock.locked():
        log.info("reenrich_already_running", job_id=job_id)
        return 0

    async with lock:
        try:
            return await _reenrich_locked(job_id, session_factory, force=force)
        finally:
            # Remove lock from dict to prevent unbounded accumulation.
            # If another call races after removal, _get_job_lock creates a new one.
            _job_locks.pop(job_id, None)


async def _reenrich_locked(
    job_id: str,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    force: bool = False,
) -> int:
    """Core re-enrichment logic (must be called under the per-job lock)."""
    from backend.persistence.event_repo import EventRepository

    async with session_factory() as session:
        repo = EventRepository(session)

        # Check for existing marker
        markers = await repo.list_by_job(job_id, [_REENRICH_MARKER_KIND], limit=1)
        if markers and not force:
            log.info("reenrich_already_complete", job_id=job_id)
            return 0

        # If force, delete existing marker(s) first — clean slate
        if markers and force:
            for m in markers:
                await repo.delete_event(m.id)

        # Re-enrich through a fresh TF Enricher in batches
        enricher = TFEnricher(flush_on_session_end=True)
        updated = 0
        offset = 0

        while True:
            batch = await repo.list_all_events_by_job(job_id, limit=_BATCH_SIZE, offset=offset)
            if not batch:
                break

            for event in batch:
                # Skip marker events — they are internal, not replay targets
                if event.kind == _REENRICH_MARKER_KIND:
                    continue

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
                    continue

                events_to_update = enriched if isinstance(enriched, list) else [enriched]
                for e in events_to_update:
                    if e.metadata and e.metadata != event.metadata:
                        await repo.update_metadata(event_id=e.id, metadata=e.metadata)
                        updated += 1

            if len(batch) < _BATCH_SIZE:
                break
            offset += _BATCH_SIZE

        # Flush any remaining buffered events
        for orphan in enricher.flush():
            if orphan.metadata:
                await repo.update_metadata(event_id=orphan.id, metadata=orphan.metadata)
                updated += 1

        # Insert fresh marker event (old one deleted above if force)
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
