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

from backend.persistence.task_link_repo import TaskLinkRepository
from backend.persistence.tracker_link_repo import TrackerLinkRepository

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


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
    TaskLink has no paired tracker ticket, or its Project has no TrackerLink
    attached — never falls back to an ambiguous Project-level default ticket.
    """
    task_link = await TaskLinkRepository(session).get_by_job_id(job_id)
    if task_link is None:
        raise TrackerResolutionError(f"Job '{job_id}' has no associated TaskLink")
    if not task_link.tracker_ticket_ref:
        raise TrackerResolutionError(f"TaskLink for job '{job_id}' has no paired tracker ticket")

    links = await TrackerLinkRepository(session).list_for_project(task_link.project_id)
    if not links:
        raise TrackerResolutionError(f"Project '{task_link.project_id}' has no TrackerLink attached")

    link = links[0]
    return ResolvedTracker(
        tracker_link_id=link["id"],
        credential_id=link["credential_id"],
        ticket_ref=task_link.tracker_ticket_ref,
    )
