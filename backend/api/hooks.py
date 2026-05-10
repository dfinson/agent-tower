"""Claude CLI hook receiver endpoint.

Receives POST requests from Claude Code hooks and routes them to
IngestService for event processing. Returns hook response bodies
for steering (e.g., operator message injection via Stop hooks).
"""

from __future__ import annotations

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from backend.services.ingest_service import IngestService

router = APIRouter(tags=["hooks"], route_class=DishkaRoute)


@router.post("/hooks/claude")
async def claude_hook(
    request: Request,
    ingest: FromDishka[IngestService],
) -> JSONResponse:
    """Receive Claude CLI hook events. Returns hook response for steering."""
    body = await request.json()
    event_type = body.get("hookEventName", "")
    response_body = await ingest.ingest_claude_hook(event_type, body)
    return JSONResponse(content=response_body)
