"""Approval request persistence."""

from __future__ import annotations

from sqlalchemy import select, update

from backend.models.db import ApprovalRow
from backend.models.domain import Approval
from backend.persistence.repository import BaseRepository


class ApprovalRepository(BaseRepository):
    """Database access for approval request records."""

    @staticmethod
    def _to_domain(row: ApprovalRow) -> Approval:
        return Approval(
            id=row.id,  # type: ignore[arg-type]
            job_id=row.job_id,  # type: ignore[arg-type]
            description=row.description,  # type: ignore[arg-type]
            proposed_action=row.proposed_action,  # type: ignore[arg-type]
            requested_at=row.requested_at,  # type: ignore[arg-type]
            resolved_at=row.resolved_at,  # type: ignore[arg-type]
            resolution=row.resolution,  # type: ignore[arg-type]
        )

    async def create(self, approval: Approval) -> Approval:
        """Insert an approval request record."""
        row = ApprovalRow(
            id=approval.id,
            job_id=approval.job_id,
            description=approval.description,
            proposed_action=approval.proposed_action,
            requested_at=approval.requested_at,
            resolved_at=approval.resolved_at,
            resolution=approval.resolution,
        )
        self._session.add(row)
        await self._session.flush()
        return approval

    async def get(self, approval_id: str) -> Approval | None:
        """Get a single approval by ID."""
        stmt = select(ApprovalRow).where(ApprovalRow.id == approval_id)
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        return self._to_domain(row) if row else None

    async def list_for_job(self, job_id: str) -> list[Approval]:
        """List all approvals for a given job, ordered by requested_at."""
        stmt = select(ApprovalRow).where(ApprovalRow.job_id == job_id).order_by(ApprovalRow.requested_at)
        result = await self._session.execute(stmt)
        return [self._to_domain(row) for row in result.scalars().all()]

    async def list_pending(self, job_id: str | None = None) -> list[Approval]:
        """List unresolved approvals, optionally filtered by job_id."""
        stmt = select(ApprovalRow).where(ApprovalRow.resolution.is_(None))
        if job_id is not None:
            stmt = stmt.where(ApprovalRow.job_id == job_id)
        stmt = stmt.order_by(ApprovalRow.requested_at)
        result = await self._session.execute(stmt)
        return [self._to_domain(row) for row in result.scalars().all()]

    async def resolve(
        self,
        approval_id: str,
        resolution: str,
        resolved_at: object,
    ) -> Approval | None:
        """Mark an approval as resolved atomically. Returns updated approval or None.

        Uses UPDATE ... WHERE resolution IS NULL to prevent double-resolve race.
        Returns None if the row doesn't exist or was already resolved.
        """
        stmt = (
            update(ApprovalRow)
            .where(ApprovalRow.id == approval_id, ApprovalRow.resolution.is_(None))
            .values(resolution=resolution, resolved_at=resolved_at)
        )
        result = await self._session.execute(stmt)
        if result.rowcount == 0:  # type: ignore[attr-defined]
            return None
        await self._session.flush()
        # Re-fetch the updated row
        fetch_stmt = select(ApprovalRow).where(ApprovalRow.id == approval_id)
        fetch_result = await self._session.execute(fetch_stmt)
        row = fetch_result.scalar_one_or_none()
        return self._to_domain(row) if row else None
