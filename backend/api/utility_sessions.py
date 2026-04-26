"""Utility session endpoints for pre-warming and releasing agent sessions."""

from __future__ import annotations

import structlog
from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, HTTPException

from backend.services.sister_session import SisterSessionManager

log = structlog.get_logger()

router = APIRouter(tags=["utility-sessions"], route_class=DishkaRoute)


@router.post("/utility-sessions/warm")
async def warm_utility_session(
    sister_sessions: FromDishka[SisterSessionManager],
) -> dict[str, str]:
    """Pre-warm a utility session for the new-job panel.

    Returns a session token that can be passed to ``POST /jobs`` or released
    via ``DELETE /utility-sessions/{token}`` if the user navigates away.
    """
    try:
        token = await sister_sessions.warm()
    except (ConnectionError, TimeoutError, OSError) as exc:
        log.warning("warm_session_failed", exc_info=exc)
        raise HTTPException(status_code=503, detail="Failed to warm session") from exc
    return {"sessionToken": token}


@router.delete("/utility-sessions/{token}", status_code=204)
async def release_utility_session(
    token: str,
    sister_sessions: FromDishka[SisterSessionManager],
) -> None:
    """Release a pre-warmed session the user didn't use."""
    found = await sister_sessions.release(token)
    if not found:
        raise HTTPException(status_code=404, detail="Session not found or already expired")
