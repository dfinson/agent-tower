"""Shared SDK event → SessionEvent mapping for Copilot SDK events.

Both CopilotAdapter (managed sessions) and SessionStateWatcher (discovered
CLI sessions) process the same Copilot SDK event types.  This module
provides the canonical mapping logic so it lives in one place.

Event-to-SessionEvent mapping with full tool enrichment is handled by
``event_enricher.ToolEventEnricher`` and the watcher's
``_map_sdk_event_enriched``.  This module retains the shared constants
(SDK_KIND_MAP), telemetry extraction, and result text parsing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from backend.models.domain import SessionEventKind

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
