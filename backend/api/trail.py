"""Trail endpoints — agent audit trail query API."""

from __future__ import annotations

import json
from typing import Annotated

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Query
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from backend.models.api_schemas import (
    TrailBacktrack,
    TrailKeyDecision,
    TrailNodeResponse,
    TrailResponse,
    TrailSummaryResponse,
)
from backend.services.trail_service import TrailService

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


@router.get("/jobs/{job_id}/trail")
async def get_job_trail(
    job_id: str,
    trail_service: FromDishka[TrailService],
    kinds: Annotated[str | None, Query()] = None,
    flat: Annotated[bool, Query()] = False,
    after_seq: Annotated[int | None, Query(alias="after_seq")] = None,
) -> TrailResponse:
    """Fetch the audit trail for a job."""
    kind_list = [k.strip() for k in kinds.split(",")] if kinds else None
    data = await trail_service.get_trail(
        job_id, kinds=kind_list, flat=flat, after_seq=after_seq,
    )
    nodes = [_dict_to_node_response(n) for n in data["nodes"]]
    return TrailResponse(
        job_id=data["job_id"],
        nodes=nodes,
        total_nodes=data["total_nodes"],
        enriched_nodes=data["enriched_nodes"],
        complete=data["complete"],
    )


@router.get("/jobs/{job_id}/trail/summary")
async def get_job_trail_summary(
    job_id: str,
    trail_service: FromDishka[TrailService],
) -> TrailSummaryResponse:
    """Get a lightweight trail summary for a job."""
    data = await trail_service.get_summary(job_id)
    return TrailSummaryResponse(
        job_id=data["job_id"],
        goals=data["goals"],
        approach=data.get("approach"),
        key_decisions=[
            TrailKeyDecision(decision=d["decision"], rationale=d.get("rationale"))
            for d in data.get("key_decisions", [])
        ],
        backtracks=[
            TrailBacktrack(
                original=b["original"],
                replacement=b["replacement"],
                reason=b.get("reason"),
            )
            for b in data.get("backtracks", [])
        ],
        files_explored=data.get("files_explored", 0),
        files_modified=data.get("files_modified", 0),
        verifications_passed=data.get("verifications_passed", 0),
        verifications_failed=data.get("verifications_failed", 0),
        enrichment_complete=data.get("enrichment_complete", False),
    )
