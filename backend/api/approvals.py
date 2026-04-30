"""Approval resolution and operator message endpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, HTTPException

from backend.models.api_schemas import (
    ApprovalListResponse,
    ApprovalResponse,
    ResolveBatchRequest,
    ResolveBatchResponse,
    ResolveApprovalRequest,
    SendMessageRequest,
    SendMessageResponse,
    TrustJobResponse,
)
from backend.services.approval_service import ApprovalService
from backend.services.runtime_service import RuntimeService

if TYPE_CHECKING:
    from backend.models.domain import Approval

router = APIRouter(tags=["approvals"], route_class=DishkaRoute)


def _to_response(approval: Approval) -> ApprovalResponse:
    return ApprovalResponse(
        id=approval.id,
        job_id=approval.job_id,
        description=approval.description,
        proposed_action=approval.proposed_action,
        requested_at=approval.requested_at,
        resolved_at=approval.resolved_at,
        resolution=approval.resolution,
        requires_explicit_approval=approval.requires_explicit_approval,
    )


@router.get("/jobs/{job_id}/approvals", response_model=ApprovalListResponse)
async def list_approvals(
    job_id: str,
    approval_service: FromDishka[ApprovalService],
) -> ApprovalListResponse:
    """List all approvals for a job."""
    approvals = await approval_service.list_for_job(job_id)
    return ApprovalListResponse(items=[_to_response(a) for a in approvals])


@router.post("/approvals/{approval_id}/resolve", response_model=ApprovalResponse)
async def resolve_approval(
    approval_id: str,
    body: ResolveApprovalRequest,
    approval_service: FromDishka[ApprovalService],
) -> ApprovalResponse:
    """Approve or reject a pending approval request."""
    approval = await approval_service.resolve(approval_id, body.resolution)
    return _to_response(approval)


@router.post("/jobs/{job_id}/approvals/trust", response_model=TrustJobResponse)
async def trust_job(
    job_id: str,
    approval_service: FromDishka[ApprovalService],
) -> TrustJobResponse:
    """Trust a job session — auto-approve all current and future permission requests."""
    count = await approval_service.trust_job(job_id)
    return TrustJobResponse(resolved=count)


@router.post("/jobs/{job_id}/messages", response_model=SendMessageResponse)
async def send_message(
    job_id: str,
    body: SendMessageRequest,
    runtime_service: FromDishka[RuntimeService],
) -> SendMessageResponse:
    """Inject an operator message into a running job's agent session."""
    from datetime import UTC, datetime

    sent = await runtime_service.send_message(job_id, body.content)
    if not sent:
        raise HTTPException(
            status_code=409,
            detail="Job is not running and could not be auto-resumed",
        )
    return SendMessageResponse(
        seq=0,
        timestamp=datetime.now(UTC),
    )


@router.post("/jobs/{job_id}/batches/resolve", response_model=ResolveBatchResponse)
async def resolve_batch(
    job_id: str,
    body: ResolveBatchRequest,
    runtime_service: FromDishka[RuntimeService],
) -> ResolveBatchResponse:
    """Resolve a pending action policy batch for a job."""
    resolved = await runtime_service.resolve_policy_batch(
        job_id=job_id,
        batch_id=body.batch_id,
        resolution=body.resolution,
        approved_ids=body.approved_ids,
        trust_grant_id=body.trust_grant_id,
    )
    if not resolved:
        raise HTTPException(
            status_code=404,
            detail="Batch not found or already resolved",
        )
    return ResolveBatchResponse(resolved=True)
