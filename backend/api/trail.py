"""Trail endpoints — agent audit trail query API."""

from __future__ import annotations

from typing import Annotated

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Query

from backend.models.api_schemas import (
    TrailBacktrack,
    TrailKeyDecision,
    TrailNodeResponse,
    TrailResponse,
    TrailSummaryResponse,
)
from backend.services.trail import TrailService

router = APIRouter(tags=["trail"], route_class=DishkaRoute)


def _dict_to_node_response(d: dict) -> TrailNodeResponse:
    """Convert a service-layer dict to a Pydantic response model."""
    children = [_dict_to_node_response(c) for c in d.get("children", [])]
    return TrailNodeResponse(
        id=d["id"],
        seq=d["seq"],
        anchor_seq=d["anchor_seq"],
        kind=d["kind"],
        deterministic_kind=d.get("deterministic_kind"),
        phase=d.get("phase"),
        timestamp=d["timestamp"],
        enrichment=d["enrichment"],
        intent=d.get("intent"),
        rationale=d.get("rationale"),
        outcome=d.get("outcome"),
        step_id=d.get("step_id"),
        span_ids=d.get("span_ids", []),
        turn_id=d.get("turn_id"),
        files=d.get("files", []),
        start_sha=d.get("start_sha"),
        end_sha=d.get("end_sha"),
        supersedes=d.get("supersedes"),
        tags=d.get("tags", []),
        children=children,
    )


@router.get("/jobs/{job_id}/trail", response_model=TrailResponse)
async def get_job_trail(
    job_id: str,
    trail_service: FromDishka[TrailService],
    kinds: Annotated[str | None, Query()] = None,
    flat: Annotated[bool, Query()] = False,
    after_seq: Annotated[int | None, Query(alias="after_seq")] = None,
) -> TrailResponse:
    """Fetch the audit trail for a job."""
    kind_list = [k.strip() for k in kinds.split(",")] if kinds else None
    trail = await trail_service.get_trail(
        job_id, kinds=kind_list, flat=flat, after_seq=after_seq,
    )
    nodes = [_dict_to_node_response(n) for n in trail["nodes"]]
    return TrailResponse(
        job_id=trail["job_id"],
        nodes=nodes,
        total_nodes=trail["total_nodes"],
        enriched_nodes=trail["enriched_nodes"],
        complete=trail["complete"],
    )


@router.get("/jobs/{job_id}/trail/summary", response_model=TrailSummaryResponse)
async def get_job_trail_summary(
    job_id: str,
    trail_service: FromDishka[TrailService],
) -> TrailSummaryResponse:
    """Get a lightweight trail summary for a job."""
    trail_summary = await trail_service.get_summary(job_id)
    return TrailSummaryResponse(
        job_id=trail_summary["job_id"],
        goals=trail_summary["goals"],
        approach=trail_summary.get("approach"),
        key_decisions=[
            TrailKeyDecision(decision=d["decision"], rationale=d.get("rationale"))
            for d in trail_summary.get("key_decisions", [])
        ],
        backtracks=[
            TrailBacktrack(
                original=b["original"],
                replacement=b["replacement"],
                reason=b.get("reason"),
            )
            for b in trail_summary.get("backtracks", [])
        ],
        files_explored=trail_summary.get("files_explored", 0),
        files_modified=trail_summary.get("files_modified", 0),
        verifications_passed=trail_summary.get("verifications_passed", 0),
        verifications_failed=trail_summary.get("verifications_failed", 0),
        enrichment_complete=trail_summary.get("enrichment_complete", False),
    )
