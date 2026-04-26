"""Shared parsing utilities for service-layer code."""

from __future__ import annotations

import json
from typing import Any


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
