"""Approval gate for outbound tracker writes."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

import structlog

from backend.models.domain import ApprovalResolution

if TYPE_CHECKING:
    from backend.services.job.approval_service import ApprovalService

log = structlog.get_logger()


class TrackerWriteAction(StrEnum):
    """Outbound tracker operations supported by the approval gate."""

    comment = "comment"
    transition = "transition"


@dataclass(frozen=True)
class TrackerWriteRequest:
    """Provider-independent description of a proposed tracker write."""

    tracker_link_id: str
    ticket_ref: str
    action: TrackerWriteAction
    value: str

    def approval_description(self) -> str:
        return f"{self.action.value.capitalize()} on tracker ticket {self.ticket_ref}?"

    def proposed_action(self) -> str:
        return json.dumps(
            {
                "action": self.action.value,
                "ticketRef": self.ticket_ref,
                "trackerLinkId": self.tracker_link_id,
                "value": self.value,
            },
            separators=(",", ":"),
            sort_keys=True,
        )


TrackerWriteDispatcher = Callable[[TrackerWriteRequest], Awaitable[None]]


class TrackerWriteService:
    """Execute tracker writes only after an explicit CodePlane approval."""

    def __init__(self, approval_service: ApprovalService) -> None:
        self._approval_service = approval_service

    async def execute(
        self,
        job_id: str,
        request: TrackerWriteRequest,
        dispatch: TrackerWriteDispatcher,
    ) -> bool:
        """Request approval and dispatch the write only when approved."""
        approval = await self._approval_service.create_request(
            job_id,
            request.approval_description(),
            proposed_action=request.proposed_action(),
            requires_explicit_approval=True,
        )
        resolution = await self._approval_service.wait_for_resolution(approval.id)
        if resolution == ApprovalResolution.rejected:
            log.info(
                "tracker_write_rejected",
                approval_id=approval.id,
                job_id=job_id,
                tracker_link_id=request.tracker_link_id,
                ticket_ref=request.ticket_ref,
                action=request.action,
            )
            return False

        await dispatch(request)
        log.info(
            "tracker_write_dispatched",
            approval_id=approval.id,
            job_id=job_id,
            tracker_link_id=request.tracker_link_id,
            ticket_ref=request.ticket_ref,
            action=request.action,
        )
        return True
