"""Approval request persistence and routing."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog

from backend.models.domain import (
    Approval,
    ApprovalAlreadyResolvedError,
    ApprovalNotFoundError,
    ApprovalResolution,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from backend.persistence.approval_repo import ApprovalRepository

log = structlog.get_logger()

# Re-export for backward compatibility — canonical location is backend.models.domain
__all__ = [
    "ApprovalAlreadyResolvedError",
    "ApprovalNotFoundError",
]


class ApprovalService:
    """Persists approval requests and routes operator decisions to the adapter.

    Holds in-memory asyncio.Future objects keyed by approval_id so the
    runtime can await the operator's decision while the SDK blocks on
    its permission callback.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._lock = asyncio.Lock()
        self._pending_futures: dict[str, asyncio.Future[ApprovalResolution]] = {}
        self._approval_to_job: dict[str, str] = {}  # approval_id → job_id
        # approval_ids that require explicit operator approval and must not be
        # auto-resolved by a blanket trust grant (e.g. git reset --hard).
        self._explicit_approval_ids: set[str] = set()
        # Trust state is intentionally ephemeral (in-memory only). A server
        # restart resets all trust grants, which is the safer default: the
        # operator must re-trust after a restart rather than having stale
        # blanket approvals persist across sessions.
        self._trusted_jobs: set[str] = set()

    def _make_repo(self, session: AsyncSession) -> ApprovalRepository:
        from backend.persistence.approval_repo import ApprovalRepository

        return ApprovalRepository(session)

    async def create_request(
        self,
        job_id: str,
        description: str,
        proposed_action: str | None = None,
        *,
        requires_explicit_approval: bool = False,
    ) -> Approval:
        """Persist a new approval request and create an in-memory future for it.

        When *requires_explicit_approval* is True the approval will never be
        auto-resolved by a blanket trust grant — the operator must explicitly
        click Approve for each occurrence.  Use this for hard-blocked operations
        such as ``git reset --hard``.
        """
        approval_id = str(uuid.uuid4())
        now = datetime.now(UTC)
        approval = Approval(
            id=approval_id,
            job_id=job_id,
            description=description,
            proposed_action=proposed_action,
            requested_at=now,
            requires_explicit_approval=requires_explicit_approval,
        )
        async with self._session_factory() as session:
            repo = self._make_repo(session)
            await repo.create(approval)
            await session.commit()

        # Create a future the runtime can await
        loop = asyncio.get_running_loop()
        future: asyncio.Future[ApprovalResolution] = loop.create_future()
        async with self._lock:
            self._pending_futures[approval_id] = future
            self._approval_to_job[approval_id] = job_id
            if requires_explicit_approval:
                self._explicit_approval_ids.add(approval_id)

        log.info(
            "approval_created",
            approval_id=approval_id,
            job_id=job_id,
            requires_explicit_approval=requires_explicit_approval,
        )
        return approval

    async def resolve(self, approval_id: str, resolution: ApprovalResolution) -> Approval:
        """Resolve an approval and unblock the waiting runtime future."""
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            repo = self._make_repo(session)
            # Atomic update: only succeeds if resolution IS NULL
            updated = await repo.resolve(approval_id, resolution, now)
            if updated is None:
                # Either not found or already resolved — check which
                existing = await repo.get(approval_id)
                if existing is None:
                    raise ApprovalNotFoundError(f"Approval {approval_id} not found")
                raise ApprovalAlreadyResolvedError(f"Approval {approval_id} already resolved as {existing.resolution}")
            await session.commit()

        # Resolve the in-memory future so the runtime unblocks
        async with self._lock:
            future = self._pending_futures.pop(approval_id, None)
            self._approval_to_job.pop(approval_id, None)
            self._explicit_approval_ids.discard(approval_id)
        if future is not None and not future.done():
            future.set_result(resolution)

        log.info(
            "approval_resolved",
            approval_id=approval_id,
            resolution=resolution,
        )
        return updated

    async def wait_for_resolution(self, approval_id: str) -> ApprovalResolution:
        """Block until the operator resolves the approval. Returns resolution."""
        async with self._lock:
            future = self._pending_futures.get(approval_id)
        if future is None:
            raise ApprovalNotFoundError(f"No pending future for approval {approval_id}")
        return await future

    async def list_for_job(self, job_id: str) -> list[Approval]:
        """List all approvals for a job."""
        async with self._session_factory() as session:
            repo = self._make_repo(session)
            return await repo.list_for_job(job_id)

    async def list_pending(self, job_id: str | None = None) -> list[Approval]:
        """List unresolved approvals."""
        async with self._session_factory() as session:
            repo = self._make_repo(session)
            return await repo.list_pending(job_id)

    async def cleanup_job(self, job_id: str) -> None:
        """Cancel any pending futures for a job (e.g. on job cancel/fail).

        Also marks orphaned DB approvals as denied so they don't accumulate
        as unresolved rows across restarts.
        """
        async with self._lock:
            self._trusted_jobs.discard(job_id)
            to_remove = [
                aid
                for aid, fut in self._pending_futures.items()
                if not fut.done() and self._approval_to_job.get(aid) == job_id
            ]
            for aid in to_remove:
                fut = self._pending_futures.pop(aid, None)
                self._approval_to_job.pop(aid, None)
                self._explicit_approval_ids.discard(aid)
                if fut is not None and not fut.done():
                    fut.cancel()
        if to_remove:
            # Best-effort DB cleanup — resolve orphaned approvals so they
            # don't remain as pending rows after a restart.
            import asyncio

            async def _resolve_orphans() -> None:
                try:
                    from datetime import UTC, datetime

                    async with self._session_factory() as session:
                        repo = self._make_repo(session)
                        now = datetime.now(UTC)
                        for aid in to_remove:
                            await repo.resolve(aid, "denied", now)
                        await session.commit()
                except Exception:
                    log.warning("cleanup_orphan_resolve_failed", job_id=job_id, exc_info=True)

            try:
                loop = asyncio.get_running_loop()
                loop.create_task(_resolve_orphans(), name=f"approval-cleanup-{job_id[:8]}")
            except RuntimeError:
                log.warning("approval_cleanup_task_scheduling_failed", job_id=job_id)
            log.debug("approval_futures_canceled", job_id=job_id, count=len(to_remove))

    def is_trusted(self, job_id: str) -> bool:
        """Return True if the operator has approved all for this job."""
        return job_id in self._trusted_jobs

    async def recover_pending_approvals(self) -> int:
        """Recreate in-memory futures for approvals that survived a server restart.

        Called during ``recover_on_startup()`` so that any job still in
        ``waiting_for_approval`` state can be unblocked when the operator
        resolves the approval through the API.

        Returns the number of futures recreated.
        """
        async with self._session_factory() as session:
            repo = self._make_repo(session)
            pending = await repo.list_pending()

        loop = asyncio.get_running_loop()
        recovered = 0
        async with self._lock:
            for approval in pending:
                if approval.id in self._pending_futures:
                    continue  # already tracked (shouldn't happen, but defensive)
                future: asyncio.Future[ApprovalResolution] = loop.create_future()
                self._pending_futures[approval.id] = future
                self._approval_to_job[approval.id] = approval.job_id
                recovered += 1

        if recovered:
            log.info("approvals_recovered", count=recovered)
        return recovered

    async def trust_job(self, job_id: str) -> int:
        """Mark a job as trusted and approve all its pending requests.

        Approvals that were created with *requires_explicit_approval=True*
        (e.g. ``git reset --hard``) are intentionally skipped — those must
        always be resolved by the operator individually.

        Returns the number of approvals that were auto-resolved.
        """
        async with self._lock:
            self._trusted_jobs.add(job_id)

            # Resolve all pending futures for this job, skipping explicit ones.
            pending_ids = [
                aid
                for aid, jid in self._approval_to_job.items()
                if jid == job_id
                and aid in self._pending_futures
                and not self._pending_futures[aid].done()
                and aid not in self._explicit_approval_ids
            ]
        resolved_count = 0
        for aid in pending_ids:
            try:
                await self.resolve(aid, ApprovalResolution.approved)
                resolved_count += 1
            except (ApprovalNotFoundError, ApprovalAlreadyResolvedError):
                log.debug("trust_job_resolve_skipped", job_id=job_id, approval_id=aid)
                pass

        log.info("job_trusted", job_id=job_id, resolved=resolved_count)
        return resolved_count
