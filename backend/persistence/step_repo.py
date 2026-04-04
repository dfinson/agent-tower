"""Step persistence — CRUD for execution step records."""

from __future__ import annotations

import json
from datetime import datetime
from typing import cast

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.models.db import StepRow


class StepRepository:
    """Persistence for execution steps."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create(self, step: StepRow) -> None:
        async with self._session_factory() as session:
            session.add(step)
            await session.commit()

    async def complete(
        self,
        step_id: str,
        status: str,
        agent_message: str | None = None,
        tool_count: int = 0,
        completed_at: datetime | None = None,
        duration_ms: int | None = None,
        start_sha: str | None = None,
        end_sha: str | None = None,
        files_read: str | None = None,
        files_written: str | None = None,
    ) -> None:
        async with self._session_factory() as session:
            stmt = (
                update(StepRow)
                .where(StepRow.id == step_id)
                .values(
                    status=status,
                    agent_message=agent_message,
                    tool_count=tool_count,
                    completed_at=completed_at,
                    duration_ms=duration_ms,
                    start_sha=start_sha,
                    end_sha=end_sha,
                    files_read=files_read,
                    files_written=files_written,
                )
            )
            await session.execute(stmt)
            await session.commit()

    async def set_title(self, step_id: str, title: str) -> None:
        async with self._session_factory() as session:
            stmt = update(StepRow).where(StepRow.id == step_id).values(title=title)
            await session.execute(stmt)
            await session.commit()

    async def get(self, step_id: str) -> StepRow | None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(StepRow).where(StepRow.id == step_id)
            )
            return result.scalar_one_or_none()

    async def get_by_job(self, job_id: str, limit: int = 200) -> list[StepRow]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(StepRow)
                .where(StepRow.job_id == job_id)
                .order_by(StepRow.step_number)
                .limit(limit)
            )
            return list(result.scalars().all())
