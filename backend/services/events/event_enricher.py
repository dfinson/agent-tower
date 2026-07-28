"""Tool-call display enrichment for the preflight-scout secondary session.

Post event-core-collapse, transcript events are produced natively as
``traceforge.SessionEvent`` by the managed adapters and the imported ingest
sources, so the old shared enrichment path (and its ``ToolEventEnricher``
start/complete pairing) is gone.  The one remaining caller is the preflight
scout, which records tool calls into its own secondary-session entry schema and
needs the same presentation fields (``tool_display``/``tool_visibility``/
``tool_issue``/edit-success correction) that the main transcript derives.

This helper returns a plain ``dict`` keyed by the secondary-session entry field
names; it is intentionally decoupled from the (now-deleted) CP-shape transcript
``TypedDict``.
"""

from __future__ import annotations

from typing import Any


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
) -> dict[str, Any]:
    """Build an enriched tool-call entry payload for the preflight scout.

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

    return {
        "content": tool_name,
        "tool_name": tool_name,
        "tool_args": tool_args,
        "tool_result": result_text,
        "tool_success": success,
        "tool_issue": tool_issue,
        "turn_id": turn_id or "",
        "tool_intent": tool_intent,
        "tool_title": tool_title,
        "tool_display": format_tool_display(
            tool_name,
            tool_args,
            tool_result=result_text or None,
            tool_success=success,
        ),
        "tool_display_full": format_tool_display_full(
            tool_name,
            tool_args,
            tool_result=result_text or None,
            tool_success=success,
        ),
        "tool_duration_ms": int(duration_ms) if duration_ms is not None else None,
        "tool_visibility": classify_tool_visibility(tool_name, tool_args),
    }
