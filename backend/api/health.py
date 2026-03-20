"""Health check endpoint."""

from __future__ import annotations

import time
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: TC002

from backend import __version__
from backend.api.deps import get_db_session
from backend.config import load_config
from backend.models.api_schemas import HealthResponse, HealthStatus
from backend.services.job_service import JobService

router = APIRouter(tags=["health"])

# Intentionally captured at import time — this module is first imported during
# app startup, so the value accurately represents the process start time and is
# used to compute uptime in the health endpoint.
_start_time = time.monotonic()


@router.get("/health", response_model=HealthResponse)
async def health(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> HealthResponse:
    """Return service health and status."""
    config = load_config()
    svc = JobService.from_session(session, config)
    active = await svc.count_active_jobs()
    queued = await svc.count_queued_jobs()
    return HealthResponse(
        status=HealthStatus.healthy,
        version=__version__,
        uptime_seconds=round(time.monotonic() - _start_time, 1),
        active_jobs=active,
        queued_jobs=queued,
    )
