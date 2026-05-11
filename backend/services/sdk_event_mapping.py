"""Shared SDK event → SessionEvent mapping for Copilot SDK events.

Both CopilotAdapter (managed sessions) and SessionStateWatcher (discovered
CLI sessions) process the same Copilot SDK event types.  This module
provides the canonical mapping logic so it lives in one place.

The CopilotAdapter adds enrichment on top (tool metadata buffering, intent,
visibility, duration tracking) but uses this module for the base mapping
and telemetry extraction.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from backend.models.domain import SessionEvent, SessionEventKind

if TYPE_CHECKING:
    pass

# Canonical mapping from SDK event type strings to SessionEventKind.
SDK_KIND_MAP: dict[str, SessionEventKind] = {
    "session.task_complete": SessionEventKind.done,
    "session.idle": SessionEventKind.done,
    "session.shutdown": SessionEventKind.done,
    "session.error": SessionEventKind.error,
    "assistant.message": SessionEventKind.transcript,
    "assistant.message_delta": SessionEventKind.transcript,
    "assistant.reasoning": SessionEventKind.transcript,
    "assistant.reasoning_delta": SessionEventKind.transcript,
    "user.message": SessionEventKind.transcript,
    "tool.execution_complete": SessionEventKind.transcript,
    "tool.execution_start": SessionEventKind.transcript,
    "tool.execution_partial_result": SessionEventKind.transcript,
    "session.workspace_file_changed": SessionEventKind.file_changed,
}


def map_sdk_event(kind_str: str, data: Any) -> SessionEvent | None:
    """Map a Copilot SDK event to a basic SessionEvent.

    Returns None for events that should be skipped (empty content,
    system notifications, report_intent, unrecognised types).

    This produces the *basic* payload — no tool metadata buffering,
    no visibility classification, no duration tracking.  The managed
    adapter enriches tool events further via ``_build_tool_*_payload``.
    """
    kind = SDK_KIND_MAP.get(kind_str)
    if kind is None:
        return None

    payload: dict[str, Any] = {}

    if kind == SessionEventKind.transcript:
        if kind_str == "assistant.message":
            content = str(getattr(data, "content", "") or "")
            if not content.strip():
                return None
            payload = {"role": "agent", "content": content}
        elif kind_str == "assistant.message_delta":
            delta = str(getattr(data, "delta_content", "") or "")
            if not delta:
                return None
            payload = {"role": "agent_delta", "content": delta}
        elif kind_str == "assistant.reasoning":
            content = str(getattr(data, "content", "") or "")
            payload = {"role": "reasoning", "content": content}
        elif kind_str == "assistant.reasoning_delta":
            delta = str(getattr(data, "delta_content", "") or "")
            if not delta:
                return None
            payload = {"role": "reasoning_delta", "content": delta}
        elif kind_str == "user.message":
            content = str(getattr(data, "content", "") or "")
            if "<system_notification>" in content:
                return None
            payload = {"role": "operator", "content": content}
        elif kind_str == "tool.execution_start":
            tool_name = getattr(data, "tool_name", None) or getattr(data, "mcp_tool_name", None) or "tool"
            mcp_server = getattr(data, "mcp_server_name", None)
            if mcp_server and getattr(data, "mcp_tool_name", None):
                tool_name = f"{mcp_server}/{data.mcp_tool_name}"
            if tool_name == "report_intent":
                return None
            args_str = _serialize_args(getattr(data, "arguments", None))
            payload = {
                "role": "tool_running",
                "tool_name": tool_name,
                "tool_args": args_str,
                "content": tool_name,
            }
        elif kind_str == "tool.execution_complete":
            tool_name = str(getattr(data, "tool_name", None) or "tool")
            if tool_name == "report_intent":
                return None
            success = bool(getattr(data, "success", True))
            result_text = extract_result_text(getattr(data, "result", None))
            payload = {
                "role": "tool_call",
                "tool_name": tool_name,
                "tool_result": result_text,
                "tool_success": success,
                "content": tool_name,
            }
        elif kind_str == "tool.execution_partial_result":
            chunk = str(getattr(data, "partial_output", "") or "")
            if not chunk:
                return None
            tool_name = str(getattr(data, "tool_name", None) or "tool")
            payload = {
                "role": "tool_output_delta",
                "content": chunk,
                "tool_name": tool_name,
            }
    elif kind == SessionEventKind.file_changed:
        payload = {"file": str(getattr(data, "file_path", "") or "")}
    else:
        # done / error — pass through raw dict
        payload = data.to_dict() if data and hasattr(data, "to_dict") else {}

    return SessionEvent(kind=kind, payload=payload)


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


# ---------------------------------------------------------------------------
# Copilot SDK telemetry extraction
# ---------------------------------------------------------------------------


def extract_copilot_telemetry(kind_str: str, data: Any) -> dict[str, Any] | None:
    """Extract telemetry counters from a Copilot SDK event.

    Returns a dict of DB-column-name → value suitable for accumulation
    via ``_accumulate_telemetry``, or None if this event type has no
    telemetry.  Also returns OTEL-relevant fields in a ``_otel`` key.
    """
    if kind_str == "assistant.usage":
        input_toks = int(getattr(data, "input_tokens", 0) or 0)
        output_toks = int(getattr(data, "output_tokens", 0) or 0)
        cache_read = int(getattr(data, "cache_read_tokens", 0) or 0)
        cache_write = int(getattr(data, "cache_write_tokens", 0) or 0)
        cost = float(getattr(data, "cost", 0) or 0)
        model = str(getattr(data, "model", "") or "")
        duration_ms = float(getattr(data, "duration", 0) or 0)
        return {
            "input_tokens": input_toks,
            "output_tokens": output_toks,
            "cache_read_tokens": cache_read,
            "cache_write_tokens": cache_write,
            "total_cost_usd": cost,
            "llm_call_count": 1,
            "total_llm_duration_ms": int(duration_ms),
            "_otel": {
                "model": model,
                "duration_ms": duration_ms,
            },
        }
    if kind_str == "session.usage_info":
        current = int(getattr(data, "current_tokens", 0) or 0)
        return {
            "_context_tokens": current,  # special: not accumulated, set directly
        }
    if kind_str == "session.compaction_complete":
        pre = int(getattr(data, "pre_compaction_tokens", 0) or 0)
        post = int(getattr(data, "post_compaction_tokens", 0) or 0)
        return {
            "compactions": 1,
            "tokens_compacted": max(0, pre - post),
            "_otel": {"pre": pre, "post": post},
        }
    if kind_str == "assistant.message":
        return {"agent_messages": 1}
    if kind_str == "user.message":
        return {"operator_messages": 1}
    return None


def emit_copilot_otel(kind_str: str, counters: dict[str, Any], job_id: str) -> None:
    """Emit OTEL metrics for Copilot SDK telemetry.

    Call after ``extract_copilot_telemetry`` with the returned counters dict.
    """
    from backend.services import telemetry as tel

    attrs = {"job_id": job_id, "sdk": "copilot"}
    otel = counters.get("_otel", {})

    if kind_str == "assistant.usage":
        model = otel.get("model", "")
        tel.tokens_input.add(counters["input_tokens"], {**attrs, "model": model})
        tel.tokens_output.add(counters["output_tokens"], {**attrs, "model": model})
        tel.tokens_cache_read.add(counters["cache_read_tokens"], attrs)
        tel.tokens_cache_write.add(counters["cache_write_tokens"], attrs)
        tel.cost_usd.add(counters["total_cost_usd"], attrs)
    elif kind_str == "session.usage_info":
        current = counters.get("_context_tokens", 0)
        tel.context_tokens_gauge.set(current, attrs)
    elif kind_str == "session.compaction_complete":
        tel.compactions_counter.add(1, attrs)
        tel.tokens_compacted.add(counters["tokens_compacted"], attrs)
    elif kind_str == "assistant.message":
        tel.messages_counter.add(1, {**attrs, "role": "agent"})
    elif kind_str == "user.message":
        tel.messages_counter.add(1, {**attrs, "role": "operator"})


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _serialize_args(args: Any) -> str | None:
    """Serialize tool arguments to a JSON string."""
    if args is None:
        return None
    try:
        return json.dumps(args) if not isinstance(args, str) else args
    except (TypeError, ValueError):
        return str(args)
