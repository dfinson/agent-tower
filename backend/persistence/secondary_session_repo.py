"""Secondary session persistence — CRUD for preflight, sidecar, and monitor sessions."""

from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import select, update

from backend.models.db import SecondarySessionEntryRow, SecondarySessionRow
from backend.persistence.database import serialized_write

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class SecondarySessionRepository:
    """Persistence for secondary sessions.

    Uses session_factory (not BaseRepository) for independent session-per-
    operation semantics — writes happen from event handlers outside request
    context and must commit immediately.
    """

    def __init__(self, session_factory: "async_sessionmaker[AsyncSession]") -> None:
        self._session_factory = session_factory

    # -- Session lifecycle --

    async def create_session(
        self,
        *,
        session_id: str,
        job_id: str,
        kind: str,
        name: str,
        icon: str,
        started_at: datetime,
    ) -> None:
        """Create a new secondary session record."""
        async with serialized_write(self._session_factory) as session:
            session.add(SecondarySessionRow(
                id=session_id,
                job_id=job_id,
                kind=kind,
                name=name,
                icon=icon,
                status="running",
                started_at=started_at,
                metadata_json="{}",
            ))

    async def complete_session(
        self,
        session_id: str,
        *,
        status: str,
        completed_at: datetime,
        output: str | None = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cost_usd: float = 0.0,
        metadata: dict | None = None,
    ) -> None:
        """Mark a session as completed/failed/timeout with final metrics."""
        async with serialized_write(self._session_factory) as session:
            stmt = (
                update(SecondarySessionRow)
                .where(SecondarySessionRow.id == session_id)
                .values(
                    status=status,
                    completed_at=completed_at,
                    output=output,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cost_usd=cost_usd,
                    metadata_json=json.dumps(metadata or {}),
                )
            )
            await session.execute(stmt)

    # -- Entry persistence --

    async def add_entry(
        self,
        *,
        session_id: str,
        seq: int,
        timestamp: datetime,
        kind: str,
        content: str,
        tool_name: str | None = None,
        tool_args: str | None = None,
        duration_ms: float | None = None,
    ) -> None:
        """Append a single entry (reasoning, tool_call, output, error)."""
        async with serialized_write(self._session_factory) as session:
            session.add(SecondarySessionEntryRow(
                session_id=session_id,
                seq=seq,
                timestamp=timestamp,
                kind=kind,
                content=content,
                tool_name=tool_name,
                tool_args=tool_args,
                duration_ms=duration_ms,
            ))

    async def add_entries(
        self,
        entries: list[SecondarySessionEntryRow],
    ) -> None:
        """Batch-append multiple entries."""
        if not entries:
            return
        async with serialized_write(self._session_factory) as session:
            session.add_all(entries)

    # -- Queries --

    async def get_by_job(self, job_id: str) -> list[SecondarySessionRow]:
        """Fetch all secondary sessions for a job, ordered by start time."""
        async with self._session_factory() as session:
            stmt = (
                select(SecondarySessionRow)
                .where(SecondarySessionRow.job_id == job_id)
                .order_by(SecondarySessionRow.started_at)
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def get_session(self, session_id: str) -> SecondarySessionRow | None:
        """Fetch a single session by ID."""
        async with self._session_factory() as session:
            result = await session.execute(
                select(SecondarySessionRow).where(SecondarySessionRow.id == session_id)
            )
            return result.scalar_one_or_none()

    async def get_entries(self, session_id: str) -> list[SecondarySessionEntryRow]:
        """Fetch all entries for a session, ordered by seq."""
        async with self._session_factory() as session:
            stmt = (
                select(SecondarySessionEntryRow)
                .where(SecondarySessionEntryRow.session_id == session_id)
                .order_by(SecondarySessionEntryRow.seq)
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())
