"""Shared parsing and error-handling utilities for service-layer code."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from structlog.stdlib import BoundLogger


def ensure_dict(raw: str | dict[str, Any] | Any) -> dict[str, Any] | None:
    """Parse *raw* into a ``dict`` if possible, returning ``None`` on failure.

    Handles the common pattern of tool arguments arriving as either a
    pre-parsed ``dict`` or a JSON-encoded ``str``.
    """
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


@asynccontextmanager
async def best_effort(
    logger: BoundLogger,
    operation: str,
    *,
    level: str = "debug",
    **log_kwargs: Any,
) -> AsyncIterator[None]:
    """Suppress and log exceptions for non-critical side-effect operations.

    Usage::

        async with best_effort(log, "telemetry_artifact", job_id=job_id):
            await store_something()
    """
    try:
        yield
    except Exception:
        getattr(logger, level)(f"{operation}_failed", exc_info=True, **log_kwargs)
