"""Shared SDK event → SessionEvent mapping for Copilot SDK events.

Both CopilotAdapter (managed sessions) and SessionStateWatcher (discovered
CLI sessions) process the same Copilot SDK event types.  This module
provides the canonical mapping logic so it lives in one place.

Event-to-SessionEvent mapping with full tool enrichment is handled by
``EventPipeline``.  This module retains the shared result text parsing
utility used by the watcher's SDK event consumption.
"""

from __future__ import annotations

from typing import Any


def extract_result_text(result_obj: Any) -> str:
    """Extract plain text from an SDK tool result object."""
    if result_obj is None:
        return ""
    content = getattr(result_obj, "content", None)
    if content is not None:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                text = getattr(item, "text", None)
                if text:
                    parts.append(text)
            return "\n".join(parts)
    return str(result_obj)
