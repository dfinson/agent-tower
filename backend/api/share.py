"""Job sharing endpoints — generate and consume share tokens."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import structlog
from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, HTTPException, Request
from sqlalchemy.ext.asyncio import async_sessionmaker
from starlette.responses import StreamingResponse

from backend.models.api_schemas import CamelModel, JobResponse
from backend.services.job_service import JobService
from backend.services.share_service import ShareService
from backend.services.sse_manager import SSEConnection, SSEManager

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

log = structlog.get_logger()

router = APIRouter(tags=["sharing"], route_class=DishkaRoute)


class ShareTokenResponse(CamelModel):
    token: str
    job_id: str
    url: str


class CreateShareRequest(CamelModel):
    job_id: str | None = None  # allow body-less POST where job_id is in path


# ---------------------------------------------------------------------------
# Create a share link
# ---------------------------------------------------------------------------


@router.post("/jobs/{job_id}/share", response_model=ShareTokenResponse)
async def create_share_link(
    job_id: str,
    request: Request,
    share_service: FromDishka[ShareService],
    svc: FromDishka[JobService],
) -> ShareTokenResponse:
    """Generate a read-only share URL for a job."""
    # Ensure the job exists
    await svc.get_job(job_id)
    entry = share_service.create_token(job_id)
    base = str(request.base_url).rstrip("/")
    return ShareTokenResponse(
        token=entry.token,
        job_id=job_id,
        url=f"{base}/shared/{entry.token}",
    )


# ---------------------------------------------------------------------------
# Consume a share link — read-only job detail
# ---------------------------------------------------------------------------


@router.get("/share/{token}/job", response_model=JobResponse)
async def get_shared_job(
    token: str,
    share_service: FromDishka[ShareService],
    svc: FromDishka[JobService],
) -> JobResponse:
    """Read-only job detail via share token."""
    job_id = share_service.validate(token)
    if job_id is None:
        raise HTTPException(status_code=404, detail="Invalid or expired share link")
    job = await svc.get_job(job_id)
    progress = await svc.get_latest_progress_preview(job_id)

    # Import here to avoid circular dependency
    from backend.api.jobs import _job_to_response

    return _job_to_response(job, progress)


# ---------------------------------------------------------------------------
# Shared SSE stream — read-only events for the shared job
# ---------------------------------------------------------------------------


@router.get("/share/{token}/events", response_model=None)
async def stream_shared_events(
    token: str,
    request: Request,
    share_service: FromDishka[ShareService],
    sse_manager: FromDishka[SSEManager],
    session_factory: FromDishka[async_sessionmaker],  # type: ignore[type-arg]
) -> StreamingResponse:
    """SSE stream scoped to a shared job (read-only)."""
    job_id = share_service.validate(token)
    if job_id is None:
        raise HTTPException(status_code=404, detail="Invalid or expired share link")

    header_last_id = request.headers.get("Last-Event-ID")
    conn = SSEConnection(job_id=job_id)
    sse_manager.register(conn)

    async def event_generator() -> AsyncGenerator[str, None]:
        try:
            if header_last_id is not None:
                try:
                    numeric_id = int(header_last_id)
                    await sse_manager.replay_from_factory(conn, session_factory, numeric_id)
                except (ValueError, TypeError):
                    pass

            yield "event: session_heartbeat\ndata: {}\n\n"

            while not conn.closed:
                try:
                    data = await asyncio.wait_for(conn.queue.get(), timeout=5.0)
                    yield data
                except TimeoutError:
                    yield "event: session_heartbeat\ndata: {}\n\n"
                except (asyncio.CancelledError, GeneratorExit):
                    break
        finally:
            sse_manager.unregister(conn)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "Transfer-Encoding": "chunked",
        },
    )
