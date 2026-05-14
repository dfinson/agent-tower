"""Tests for sdk_event_mapping — SDK event type mapping and telemetry extraction."""

from __future__ import annotations

from types import SimpleNamespace

from backend.models.domain import SessionEventKind
from backend.services.sdk_event_mapping import (
    SDK_KIND_MAP,
    extract_copilot_telemetry,
    extract_result_text,
)

# ---------------------------------------------------------------------------
# SDK_KIND_MAP
# ---------------------------------------------------------------------------


class TestSdkKindMap:
    def test_task_complete(self) -> None:
        assert SDK_KIND_MAP["session.task_complete"] == SessionEventKind.done

    def test_session_error(self) -> None:
        assert SDK_KIND_MAP["session.error"] == SessionEventKind.error

    def test_assistant_message(self) -> None:
        assert SDK_KIND_MAP["assistant.message"] == SessionEventKind.transcript

    def test_file_changed(self) -> None:
        assert SDK_KIND_MAP["session.workspace_file_changed"] == SessionEventKind.file_changed

    def test_tool_execution(self) -> None:
        assert SDK_KIND_MAP["tool.execution_complete"] == SessionEventKind.transcript

    def test_reasoning(self) -> None:
        assert SDK_KIND_MAP["assistant.reasoning"] == SessionEventKind.transcript


# ---------------------------------------------------------------------------
# extract_result_text
# ---------------------------------------------------------------------------


class TestExtractResultText:
    def test_none(self) -> None:
        assert extract_result_text(None) == ""

    def test_string_content(self) -> None:
        obj = SimpleNamespace(content="hello world")
        assert extract_result_text(obj) == "hello world"

    def test_list_content(self) -> None:
        items = [SimpleNamespace(text="part1"), SimpleNamespace(text="part2")]
        obj = SimpleNamespace(content=items)
        assert extract_result_text(obj) == "part1\npart2"

    def test_list_content_with_no_text(self) -> None:
        items = [SimpleNamespace(other="x")]
        obj = SimpleNamespace(content=items)
        assert extract_result_text(obj) == ""

    def test_fallback_str(self) -> None:
        obj = SimpleNamespace(other="value")
        result = extract_result_text(obj)
        assert "value" in result  # falls back to str(obj)


# ---------------------------------------------------------------------------
# extract_copilot_telemetry
# ---------------------------------------------------------------------------


class TestExtractCopilotTelemetry:
    def test_assistant_usage(self) -> None:
        data = SimpleNamespace(
            input_tokens=100,
            output_tokens=50,
            cache_read_tokens=10,
            cache_write_tokens=5,
            cost=0.001,
            model="gpt-4",
            duration=500.0,
        )
        result = extract_copilot_telemetry("assistant.usage", data)
        assert result is not None
        assert result["input_tokens"] == 100
        assert result["output_tokens"] == 50
        assert result["cache_read_tokens"] == 10
        assert result["cache_write_tokens"] == 5
        assert result["total_cost_usd"] == 0.001
        assert result["llm_call_count"] == 1
        assert result["total_llm_duration_ms"] == 500
        assert result["_otel"]["model"] == "gpt-4"

    def test_assistant_usage_none_values(self) -> None:
        data = SimpleNamespace(
            input_tokens=None,
            output_tokens=None,
            cache_read_tokens=None,
            cache_write_tokens=None,
            cost=None,
            model=None,
            duration=None,
        )
        result = extract_copilot_telemetry("assistant.usage", data)
        assert result is not None
        assert result["input_tokens"] == 0
        assert result["output_tokens"] == 0
        assert result["total_cost_usd"] == 0

    def test_session_usage_info(self) -> None:
        data = SimpleNamespace(current_tokens=5000)
        result = extract_copilot_telemetry("session.usage_info", data)
        assert result is not None
        assert result["_context_tokens"] == 5000

    def test_compaction_complete(self) -> None:
        data = SimpleNamespace(pre_compaction_tokens=10000, post_compaction_tokens=3000)
        result = extract_copilot_telemetry("session.compaction_complete", data)
        assert result is not None
        assert result["compactions"] == 1
        assert result["tokens_compacted"] == 7000

    def test_unknown_event_returns_none(self) -> None:
        data = SimpleNamespace()
        assert extract_copilot_telemetry("unknown.event", data) is None

    def test_assistant_message_returns_counter(self) -> None:
        data = SimpleNamespace(content="hello")
        result = extract_copilot_telemetry("assistant.message", data)
        assert result is not None
        assert result.get("agent_messages") == 1
