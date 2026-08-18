"""Shared Job -> Project -> TrackerLink resolution (Story 6.1, CAP-13).

Kept minimal and additive so both the agent-invoked ``codeplane_tracker`` MCP
tool (this story) and any future recipe-driven ``tracker_write`` output route
(Story 4.6) can resolve the same "which ticket does this Job's Project write
to" question without duplicating the lookup logic or coupling the two call
sites together.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import httpx

from backend.persistence.credential_repo import CredentialRepository
from backend.persistence.task_link_repo import TaskLinkRepository
from backend.persistence.tracker_link_repo import TrackerLinkRepository
from backend.persistence.tracker_summary_repo import TrackerSummaryRepository
from backend.services.tracker_adapter import (
    TrackerAdapterError,
    TrackerAdapterInterface,
    build_tracker_adapters,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from backend.services.tracker_write_service import TrackerWriteRequest


class TrackerResolutionError(Exception):
    """Raised when a Job has no resolvable paired tracker ticket."""


@dataclass(frozen=True)
class ResolvedTracker:
    """The TrackerLink and ticket a Job's writes should target."""

    tracker_link_id: str
    credential_id: str
    ticket_ref: str


async def resolve_tracker_for_job(session: AsyncSession, job_id: str) -> ResolvedTracker:
    """Resolve the TrackerLink/ticket for the TaskLink paired with ``job_id``.

    Raises ``TrackerResolutionError`` when the Job has no TaskLink, the
    TaskLink has no explicit TrackerLink/ticket pair, or the stored TrackerLink
    no longer belongs to its Project. There is no insertion-order fallback.
    """
    task_link = await TaskLinkRepository(session).get_by_job_id(job_id)
    if task_link is None:
        raise TrackerResolutionError(f"Job '{job_id}' has no associated TaskLink")
    if not task_link.tracker_link_id or not task_link.tracker_ticket_ref:
        raise TrackerResolutionError(f"TaskLink for job '{job_id}' has no explicit TrackerLink/ticket pair")

    link = await TrackerLinkRepository(session).get(task_link.tracker_link_id)
    if link is None or link["project_id"] != task_link.project_id:
        raise TrackerResolutionError(
            f"TrackerLink '{task_link.tracker_link_id}' is not attached to Project '{task_link.project_id}'"
        )

    return ResolvedTracker(
        tracker_link_id=link["id"],
        credential_id=link["credential_id"],
        ticket_ref=task_link.tracker_ticket_ref,
    )


async def dispatch_tracker_write(
    session_factory: async_sessionmaker[AsyncSession],
    request: TrackerWriteRequest,
    *,
    adapters: dict[str, TrackerAdapterInterface] | None = None,
) -> None:
    """Resolve one explicit TrackerLink and invoke its provider adapter once."""
    async with session_factory() as session:
        target = await TrackerSummaryRepository(session).get_target_by_link_id(request.tracker_link_id)
        if target is None:
            raise TrackerAdapterError(f"TrackerLink '{request.tracker_link_id}' does not exist")
        token = await CredentialRepository(session).resolve_secret(target["credential_id"])
    if token is None:
        raise TrackerAdapterError("Tracker credential could not be resolved")

    if adapters is not None:
        adapter = adapters.get(target["provider"])
        if adapter is None:
            raise TrackerAdapterError(f"Unsupported tracker provider: {target['provider']}")
        await adapter.write(
            base_url=target["base_url"],
            external_ref=target["external_ref"],
            token=token,
            ticket_ref=request.ticket_ref,
            action=request.action.value,
            value=request.value,
            email=target["email"],
        )
        return

    async with httpx.AsyncClient(timeout=httpx.Timeout(connect=10.0, read=30.0, write=15.0, pool=5.0)) as client:
        adapter = build_tracker_adapters(client).get(target["provider"])
        if adapter is None:
            raise TrackerAdapterError(f"Unsupported tracker provider: {target['provider']}")
        await adapter.write(
            base_url=target["base_url"],
            external_ref=target["external_ref"],
            token=token,
            ticket_ref=request.ticket_ref,
            action=request.action.value,
            value=request.value,
            email=target["email"],
        )
