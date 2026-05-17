"""Shared tool event enrichment for both managed adapters and session watchers.

The managed adapter (CopilotAdapter, ClaudeAdapter) and the session watchers
(SessionStateWatcher, ClaudeSessionWatcher) process the same underlying SDK
events.  This module provides the shared enrichment logic so both paths
produce identical, fully-enriched SessionEvent payloads.

Key responsibilities:
- Buffer tool.execution_start metadata until tool.execution_complete arrives
- Compute tool execution duration
- Produce enriched payloads with tool_display, tool_visibility, tool_intent, etc.
"""

from __future__ import annotations

import time
from typing import Any

from backend.models.domain import TranscriptPayload


def build_tool_running_payload(
    tool_name: str,
    tool_args: str | None,
    turn_id: str | None,
    *,
    tool_intent: str | None = None,
    tool_title: str | None = None,
) -> TranscriptPayload:
    """Build an enriched ``role=tool_running`` transcript event payload."""
    from backend.services.tool_formatters import (
        classify_tool_visibility,
        format_tool_display,
        format_tool_display_full,
    )

    return TranscriptPayload(
        role="tool_running",
        content=tool_name,
        tool_name=tool_name,
        tool_args=tool_args,
        turn_id=turn_id or "",
        tool_intent=tool_intent,
        tool_title=tool_title,
        tool_display=format_tool_display(tool_name, tool_args),
        tool_display_full=format_tool_display_full(tool_name, tool_args),
        tool_visibility=classify_tool_visibility(tool_name, tool_args),
    )


def build_tool_call_payload(
    tool_name: str,
    tool_args: str | None,
    result_text: str,
    sdk_success: bool,
    turn_id: str | None,
    duration_ms: float | None,
    *,
    tool_intent: str | None = None,
    tool_title: str | None = None,
) -> TranscriptPayload:
    """Build an enriched ``role=tool_call`` transcript event payload.

    Applies edit-success correction and issue extraction automatically.
    """
    from backend.services.tool_formatters import (
        classify_tool_visibility,
        correct_edit_success,
        extract_tool_issue,
        format_tool_display,
        format_tool_display_full,
    )

    success = sdk_success
    if not success:
        success = correct_edit_success(tool_name, success, result_text)

    tool_issue: str | None = None
    if not success:
        tool_issue = extract_tool_issue(result_text) or "Tool reported an issue"

    return TranscriptPayload(
        role="tool_call",
        content=tool_name,
        tool_name=tool_name,
        tool_args=tool_args,
        tool_result=result_text,
        tool_success=success,
        tool_issue=tool_issue,
        turn_id=turn_id or "",
        tool_intent=tool_intent,
        tool_title=tool_title,
        tool_display=format_tool_display(
            tool_name,
            tool_args,
            tool_result=result_text or None,
            tool_success=success,
        ),
        tool_display_full=format_tool_display_full(
            tool_name,
            tool_args,
            tool_result=result_text or None,
            tool_success=success,
        ),
        tool_duration_ms=int(duration_ms) if duration_ms is not None else None,
        tool_visibility=classify_tool_visibility(tool_name, tool_args),
    )


class ToolEventEnricher:
    """Stateful tool event enricher that pairs start/complete events.

    Maintains a buffer of tool metadata from execution_start events and
    produces enriched payloads when the corresponding execution_complete
    arrives.  Used by both managed adapters and session watchers.
    """

    def __init__(self) -> None:
        self._pending_tool_metadata: dict[str, dict[str, str]] = {}
        self._tool_start_times: dict[str, float] = {}

    def on_tool_start(
        self,
        tool_id: str,
        tool_name: str,
        tool_args: str | None,
        turn_id: str | None,
        *,
        tool_intent: str | None = None,
        tool_title: str | None = None,
    ) -> dict[str, Any]:
        """Buffer tool start metadata and return an enriched tool_running payload."""
        self._tool_start_times[tool_id] = time.monotonic()
        self._pending_tool_metadata[tool_id] = {
            "tool_name": tool_name,
            "tool_args": tool_args or "",
            "turn_id": turn_id or "",
            "tool_intent": tool_intent or "",
            "tool_title": tool_title or "",
        }
        return build_tool_running_payload(
            tool_name,
            tool_args,
            turn_id,
            tool_intent=tool_intent,
            tool_title=tool_title,
        )

    def on_tool_complete(
        self,
        tool_id: str,
        result_text: str,
        sdk_success: bool,
        *,
        tool_name_fallback: str = "tool",
    ) -> dict[str, Any]:
        """Consume buffered start metadata and return an enriched tool_call payload."""
        buffered = self._pending_tool_metadata.pop(tool_id, {})
        tool_name = buffered.get("tool_name", tool_name_fallback)
        tool_args = buffered.get("tool_args") or None
        turn_id = buffered.get("turn_id") or None
        tool_intent = buffered.get("tool_intent") or None
        tool_title = buffered.get("tool_title") or None

        start = self._tool_start_times.pop(tool_id, None)
        duration_ms = ((time.monotonic() - start) * 1000) if start is not None else None

        return build_tool_call_payload(
            tool_name,
            tool_args,
            result_text,
            sdk_success,
            turn_id=turn_id,
            duration_ms=duration_ms,
            tool_intent=tool_intent,
            tool_title=tool_title,
        )

    def get_buffered(self, tool_id: str) -> dict[str, str]:
        """Get buffered metadata for a tool_id (for intermediate events like partial results)."""
        return self._pending_tool_metadata.get(tool_id, {})

    def cleanup(self) -> None:
        """Clear all buffered state."""
        self._pending_tool_metadata.clear()
        self._tool_start_times.clear()
