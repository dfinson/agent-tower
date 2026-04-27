"""Job telemetry endpoints — metrics, cost breakdown, and span detail."""

from __future__ import annotations

import structlog
from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter

from backend.models.api_schemas import JobTelemetryResponse
from backend.services.telemetry_query_service import TelemetryQueryService

router = APIRouter(tags=["jobs"], route_class=DishkaRoute)

log = structlog.get_logger()


@router.get("/jobs/{job_id}/telemetry", response_model=JobTelemetryResponse)
async def get_job_telemetry(
    job_id: str,
    telemetry_svc: FromDishka[TelemetryQueryService],
) -> JobTelemetryResponse:
    """Get telemetry data for a job run.

    Returns the persisted telemetry summary from the OTEL-backed SQLite store.
    Includes per-call span detail (tool calls, LLM calls) when available.
    """
    return await telemetry_svc.get_telemetry(job_id)
