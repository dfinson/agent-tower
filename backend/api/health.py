"""Health check endpoint."""

from __future__ import annotations

import time

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter

from backend import __version__
from backend.models.api_schemas import (
    HealthResponse,
    HealthStatus,
    SidecarSessionMetricsResponse,
)
from backend.services.job_service import JobService
from backend.services.sidecar.session import SidecarSessionManager

router = APIRouter(tags=["health"], route_class=DishkaRoute)

# Intentionally captured at import time — this module is first imported during
# app startup, so the value accurately represents the process start time and is
# used to compute uptime in the health endpoint.
_start_time = time.monotonic()


@router.get("/health", response_model=HealthResponse)
async def health(
    svc: FromDishka[JobService],
) -> HealthResponse:
    """Return service health and status."""
    active = await svc.count_active_jobs()
    queued = await svc.count_queued_jobs()
    return HealthResponse(
        status=HealthStatus.healthy,
        version=__version__,
        uptime_seconds=round(time.monotonic() - _start_time, 1),
        active_jobs=active,
        queued_jobs=queued,
    )


@router.get("/sidecar-sessions/metrics", response_model=SidecarSessionMetricsResponse)
def sidecar_session_metrics(
    sidecar_sessions: FromDishka[SidecarSessionManager],
) -> SidecarSessionMetricsResponse:
    """Return sidecar session metrics (global + per-job)."""
    return SidecarSessionMetricsResponse.model_validate(sidecar_sessions.get_metrics())
