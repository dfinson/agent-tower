"""Tests for backend.services.events.event_pipeline — the vendor-agnostic event processor.

This is the central nervous system of all telemetry: every adapter and watcher
feeds events through EventPipeline.  These tests verify the pipeline correctly:
  - Emits transcript events for agent messages, reasoning, tool lifecycle
  - Buffers tool metadata (start→complete pairing) and computes duration
  - Records OTEL telemetry and DB writes for LLM usage and tool completions
  - Handles edge cases (orphan tools, missing starts, cleanup)
  - Maintains per-job state isolation
"""

from __future__ import annotations

import asyncio
import time
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from backend.models.domain import SessionEvent, SessionEventKind
from backend.services.events.event_pipeline import EventPipeline


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class _PipelineHarness:
    """Test harness wrapping an EventPipeline with captured emits and writes."""

    def __init__(self, sdk: str = "test") -> None:
        self.emitted: list[tuple[str, SessionEvent]] = []
        self.writes: list[Any] = []
        self.pipeline = EventPipeline(
            emit=self._emit,
            schedule_write=self._schedule_write,
            sdk=sdk,
        )
        # Mock session factory so DB writes don't crash
        mock_factory = MagicMock()
        self.pipeline.set_session_factory(mock_factory)

    async def _emit(self, job_id: str, event: SessionEvent) -> None:
        self.emitted.append((job_id, event))

    def _schedule_write(self, coro: Any) -> None:
        # Just close the coroutine to prevent warnings
        self.writes.append(coro)
        coro.close()

    def events_for(self, job_id: str) -> list[SessionEvent]:
        return [ev for jid, ev in self.emitted if jid == job_id]

    def transcript_events(self, job_id: str) -> list[SessionEvent]:
        return [
            ev for jid, ev in self.emitted
            if jid == job_id and ev.kind == SessionEventKind.transcript
        ]

    def last_payload(self, job_id: str) -> dict[str, Any]:
        events = self.events_for(job_id)
        assert events, "No events emitted"
        return events[-1].payload


@pytest.fixture
def harness() -> _PipelineHarness:
    return _PipelineHarness()


@pytest.fixture
def pipeline(harness: _PipelineHarness) -> EventPipeline:
    return harness.pipeline


# ===================================================================
# Transcript events
# ===================================================================


class TestTranscriptEvents:
    @pytest.mark.asyncio
    async def test_agent_message(self, harness: _PipelineHarness, pipeline: EventPipeline) -> None:
        await pipeline.on_agent_message("j1", "hello world")

        events = harness.transcript_events("j1")
        assert len(events) >= 1
        payload = events[0].payload
        assert payload["role"] == "agent"
        assert payload["content"] == "hello world"

    @pytest.mark.asyncio
    async def test_agent_message_with_title(self, harness: _PipelineHarness, pipeline: EventPipeline) -> None:
        await pipeline.on_agent_message("j1", "content", title="Summary")

        payload = harness.transcript_events("j1")[0].payload
        assert payload["title"] == "Summary"

    @pytest.mark.asyncio
    async def test_agent_delta(self, harness: _PipelineHarness, pipeline: EventPipeline) -> None:
        await pipeline.on_agent_delta("j1", "chunk")

        payload = harness.transcript_events("j1")[0].payload
        assert payload["role"] == "agent_delta"
        assert payload["content"] == "chunk"

    @pytest.mark.asyncio
    async def test_reasoning(self, harness: _PipelineHarness, pipeline: EventPipeline) -> None:
        await pipeline.on_reasoning("j1", "thinking...")

        payload = harness.transcript_events("j1")[0].payload
        assert payload["role"] == "reasoning"
        assert payload["content"] == "thinking..."

    @pytest.mark.asyncio
    async def test_reasoning_delta(self, harness: _PipelineHarness, pipeline: EventPipeline) -> None:
        await pipeline.on_reasoning_delta("j1", "think-chunk")

        payload = harness.transcript_events("j1")[0].payload
        assert payload["role"] == "reasoning_delta"

    @pytest.mark.asyncio
    async def test_user_message(self, harness: _PipelineHarness, pipeline: EventPipeline) -> None:
        await pipeline.on_user_message("j1", "do something")

        payload = harness.transcript_events("j1")[0].payload
        assert payload["role"] == "operator"
        assert payload["content"] == "do something"


# ===================================================================
# Tool lifecycle
# ===================================================================


class TestToolLifecycle:
    @pytest.mark.asyncio
    async def test_tool_start_emits_running(self, harness: _PipelineHarness, pipeline: EventPipeline) -> None:
        await pipeline.on_tool_start("j1", "t1", "read_file", '{"path": "/foo"}')

        events = harness.transcript_events("j1")
        assert any(ev.payload.get("role") == "tool_running" for ev in events)

    @pytest.mark.asyncio
    async def test_tool_start_buffers_metadata(self, pipeline: EventPipeline) -> None:
        await pipeline.on_tool_start("j1", "t1", "write_file", '{"path": "/bar"}', intent="create")

        buffered = pipeline.get_buffered_tool("t1")
        assert buffered["tool_name"] == "write_file"
        assert buffered["tool_args"] == '{"path": "/bar"}'
        assert buffered["tool_intent"] == "create"

    @pytest.mark.asyncio
    async def test_tool_complete_emits_tool_call(self, harness: _PipelineHarness, pipeline: EventPipeline) -> None:
        await pipeline.on_tool_start("j1", "t1", "read_file", '{"path": "/x"}')
        harness.emitted.clear()

        await pipeline.on_tool_complete("j1", "t1", "file contents", True)

        events = harness.transcript_events("j1")
        tool_call_events = [ev for ev in events if ev.payload.get("role") == "tool_call"]
        assert len(tool_call_events) == 1
        payload = tool_call_events[0].payload
        assert payload["tool_name"] == "read_file"
        assert payload["tool_success"] is True

    @pytest.mark.asyncio
    async def test_tool_complete_computes_duration(self, harness: _PipelineHarness, pipeline: EventPipeline) -> None:
        await pipeline.on_tool_start("j1", "t1", "bash", '{"command": "ls"}')
        # Fake a time gap
        pipeline._tool_start_times["t1"] = time.monotonic() - 0.5  # 500ms ago

        await pipeline.on_tool_complete("j1", "t1", "output", True)

        events = harness.transcript_events("j1")
        tool_call_events = [ev for ev in events if ev.payload.get("role") == "tool_call"]
        assert tool_call_events
        # Duration should be roughly 500ms (with some tolerance)
        dur = tool_call_events[0].payload.get("tool_duration_ms")
        assert dur is not None
        assert dur >= 400  # At least 400ms

    @pytest.mark.asyncio
    async def test_tool_complete_without_start(self, harness: _PipelineHarness, pipeline: EventPipeline) -> None:
        """Orphan tool_complete should not crash — graceful degradation."""
        await pipeline.on_tool_complete("j1", "orphan", "result", True)

        # Should still emit a tool_call event (with unknown tool name)
        events = harness.transcript_events("j1")
        tool_call_events = [ev for ev in events if ev.payload.get("role") == "tool_call"]
        assert len(tool_call_events) == 1

    @pytest.mark.asyncio
    async def test_tool_start_hidden(self, harness: _PipelineHarness, pipeline: EventPipeline) -> None:
        """Hidden tools don't emit tool_running but do buffer metadata."""
        await pipeline.on_tool_start("j1", "t1", "internal_tool", None, hidden=True)

        # No tool_running event
        events = harness.transcript_events("j1")
        assert not any(ev.payload.get("role") == "tool_running" for ev in events)

        # But metadata is buffered
        assert pipeline.get_buffered_tool("t1")["tool_name"] == "internal_tool"

    @pytest.mark.asyncio
    async def test_tool_complete_hidden(self, harness: _PipelineHarness, pipeline: EventPipeline) -> None:
        """Hidden tool_complete suppresses transcript but still records telemetry."""
        await pipeline.on_tool_start("j1", "t1", "read_file", None, hidden=True)
        harness.emitted.clear()
        harness.writes.clear()

        await pipeline.on_tool_complete("j1", "t1", "data", True, hidden=True)

        # No transcript events
        events = harness.transcript_events("j1")
        assert not any(ev.payload.get("role") == "tool_call" for ev in events)

        # But DB writes should have been scheduled (telemetry still recorded)
        assert len(harness.writes) > 0

    @pytest.mark.asyncio
    async def test_tool_failed(self, harness: _PipelineHarness, pipeline: EventPipeline) -> None:
        await pipeline.on_tool_start("j1", "t1", "bash", '{"command": "bad"}')
        await pipeline.on_tool_complete("j1", "t1", "error: command not found", False)

        events = harness.transcript_events("j1")
        tool_call_events = [ev for ev in events if ev.payload.get("role") == "tool_call"]
        assert tool_call_events[0].payload["tool_success"] is False

    @pytest.mark.asyncio
    async def test_tool_partial(self, harness: _PipelineHarness, pipeline: EventPipeline) -> None:
        await pipeline.on_tool_start("j1", "t1", "bash", '{"command": "ls"}')
        harness.emitted.clear()

        await pipeline.on_tool_partial("j1", "t1", "streaming output")

        events = harness.transcript_events("j1")
        assert any(ev.payload.get("role") == "tool_output_delta" for ev in events)


# ===================================================================
# File changes
# ===================================================================


class TestFileChanges:
    @pytest.mark.asyncio
    async def test_on_file_changed(self, harness: _PipelineHarness, pipeline: EventPipeline) -> None:
        await pipeline.on_file_changed("j1", "/tmp/test.py")

        events = harness.events_for("j1")
        fc_events = [ev for ev in events if ev.kind == SessionEventKind.file_changed]
        assert len(fc_events) == 1
        assert fc_events[0].payload["path"] == "/tmp/test.py"


# ===================================================================
# Session lifecycle
# ===================================================================


class TestSessionLifecycle:
    @pytest.mark.asyncio
    async def test_on_done(self, harness: _PipelineHarness, pipeline: EventPipeline) -> None:
        await pipeline.on_done("j1")

        events = harness.events_for("j1")
        assert any(ev.kind == SessionEventKind.done for ev in events)

    @pytest.mark.asyncio
    async def test_on_error(self, harness: _PipelineHarness, pipeline: EventPipeline) -> None:
        await pipeline.on_error("j1")

        events = harness.events_for("j1")
        assert any(ev.kind == SessionEventKind.error for ev in events)


# ===================================================================
# Usage / LLM telemetry
# ===================================================================


class TestUsageTelemetry:
    @pytest.mark.asyncio
    async def test_on_usage_records_otel(self, harness: _PipelineHarness, pipeline: EventPipeline) -> None:
        with patch("backend.services.analytics.telemetry") as mock_tel:
            mock_tel.tokens_input = MagicMock()
            mock_tel.tokens_output = MagicMock()
            mock_tel.tokens_cache_read = MagicMock()
            mock_tel.tokens_cache_write = MagicMock()
            mock_tel.cost_usd = MagicMock()
            mock_tel.llm_duration = MagicMock()

            await pipeline.on_usage(
                "j1",
                input_tokens=100,
                output_tokens=50,
                cache_read_tokens=10,
                cache_write_tokens=5,
                cost_usd=0.001,
                duration_ms=500.0,
                model="gpt-4",
            )

            mock_tel.tokens_input.add.assert_called_once()
            assert mock_tel.tokens_input.add.call_args[0][0] == 100
            mock_tel.tokens_output.add.assert_called_once()
            assert mock_tel.tokens_output.add.call_args[0][0] == 50
            mock_tel.cost_usd.add.assert_called_once()
            mock_tel.llm_duration.record.assert_called_once()

    @pytest.mark.asyncio
    async def test_on_usage_schedules_db_write(self, harness: _PipelineHarness, pipeline: EventPipeline) -> None:
        with patch("backend.services.analytics.telemetry") as mock_tel:
            mock_tel.tokens_input = MagicMock()
            mock_tel.tokens_output = MagicMock()
            mock_tel.tokens_cache_read = MagicMock()
            mock_tel.tokens_cache_write = MagicMock()
            mock_tel.cost_usd = MagicMock()
            mock_tel.llm_duration = MagicMock()

            await pipeline.on_usage(
                "j1",
                input_tokens=100,
                output_tokens=50,
                cost_usd=0.01,
                duration_ms=500.0,
                model="claude-sonnet",
            )

            # DB writes scheduled: increment + set_model + llm_span
            assert len(harness.writes) >= 2

    @pytest.mark.asyncio
    async def test_on_usage_advance_turn(self, pipeline: EventPipeline) -> None:
        with patch("backend.services.analytics.telemetry") as mock_tel:
            mock_tel.tokens_input = MagicMock()
            mock_tel.tokens_output = MagicMock()
            mock_tel.tokens_cache_read = MagicMock()
            mock_tel.tokens_cache_write = MagicMock()
            mock_tel.cost_usd = MagicMock()
            mock_tel.llm_duration = MagicMock()

            assert pipeline.get_turn("j1") == 0
            await pipeline.on_usage("j1", input_tokens=10, advance_turn=True)
            assert pipeline.get_turn("j1") == 1

    @pytest.mark.asyncio
    async def test_on_usage_skips_zero_duration(self, harness: _PipelineHarness, pipeline: EventPipeline) -> None:
        with patch("backend.services.analytics.telemetry") as mock_tel:
            mock_tel.tokens_input = MagicMock()
            mock_tel.tokens_output = MagicMock()
            mock_tel.tokens_cache_read = MagicMock()
            mock_tel.tokens_cache_write = MagicMock()
            mock_tel.cost_usd = MagicMock()
            mock_tel.llm_duration = MagicMock()

            await pipeline.on_usage("j1", input_tokens=10, duration_ms=0.0)

            mock_tel.llm_duration.record.assert_not_called()

    @pytest.mark.asyncio
    async def test_on_usage_subagent(self, harness: _PipelineHarness, pipeline: EventPipeline) -> None:
        with patch("backend.services.analytics.telemetry") as mock_tel:
            mock_tel.tokens_input = MagicMock()
            mock_tel.tokens_output = MagicMock()
            mock_tel.tokens_cache_read = MagicMock()
            mock_tel.tokens_cache_write = MagicMock()
            mock_tel.cost_usd = MagicMock()
            mock_tel.llm_duration = MagicMock()

            await pipeline.on_usage(
                "j1",
                input_tokens=50,
                output_tokens=25,
                cost_usd=0.005,
                duration_ms=200.0,
                is_subagent=True,
            )

            # llm_duration should be recorded with is_subagent=True
            call_attrs = mock_tel.llm_duration.record.call_args[0][1]
            assert call_attrs["is_subagent"] is True


# ===================================================================
# Context and compaction
# ===================================================================


class TestContextCompaction:
    @pytest.mark.asyncio
    async def test_on_context_update(self, harness: _PipelineHarness, pipeline: EventPipeline) -> None:
        with patch("backend.services.analytics.telemetry") as mock_tel:
            mock_tel.context_tokens_gauge = MagicMock()

            await pipeline.on_context_update("j1", 5000)

            mock_tel.context_tokens_gauge.set.assert_called_once_with(
                5000, {"job_id": "j1", "sdk": "test"},
            )
            assert len(harness.writes) >= 1

    @pytest.mark.asyncio
    async def test_on_compaction(self, harness: _PipelineHarness, pipeline: EventPipeline) -> None:
        with patch("backend.services.analytics.telemetry") as mock_tel:
            mock_tel.compactions_counter = MagicMock()
            mock_tel.tokens_compacted = MagicMock()
            mock_tel.context_tokens_gauge = MagicMock()

            await pipeline.on_compaction("j1", pre_tokens=10000, post_tokens=3000)

            mock_tel.compactions_counter.add.assert_called_once()
            mock_tel.tokens_compacted.add.assert_called_once_with(
                7000, {"job_id": "j1", "sdk": "test"},
            )

    @pytest.mark.asyncio
    async def test_on_model_change(self, harness: _PipelineHarness, pipeline: EventPipeline) -> None:
        await pipeline.on_model_change("j1", "gpt-4o")

        # DB write scheduled
        assert len(harness.writes) >= 1
        # Log event emitted
        events = harness.events_for("j1")
        log_events = [ev for ev in events if ev.kind == SessionEventKind.log]
        assert any("gpt-4o" in ev.payload.get("message", "") for ev in log_events)


# ===================================================================
# Per-job state management
# ===================================================================


class TestJobState:
    def test_set_job_start_time(self, pipeline: EventPipeline) -> None:
        pipeline.set_job_start_time("j1", 1234.5)
        assert pipeline._job_start_times["j1"] == 1234.5

    def test_set_job_start_time_no_overwrite(self, pipeline: EventPipeline) -> None:
        pipeline.set_job_start_time("j1", 100.0)
        pipeline.set_job_start_time("j1", 999.0)  # should not overwrite
        assert pipeline._job_start_times["j1"] == 100.0

    def test_set_execution_phase(self, pipeline: EventPipeline) -> None:
        pipeline.set_execution_phase("j1", "verification")
        assert pipeline._current_phases["j1"] == "verification"

    def test_advance_turn(self, pipeline: EventPipeline) -> None:
        assert pipeline.get_turn("j1") == 0
        assert pipeline.advance_turn("j1") == 1
        assert pipeline.advance_turn("j1") == 2
        assert pipeline.get_turn("j1") == 2

    def test_cleanup_job(self, pipeline: EventPipeline) -> None:
        pipeline.set_job_start_time("j1")
        pipeline.set_execution_phase("j1", "test")
        pipeline.advance_turn("j1")
        pipeline._transcript_buffers["j1"] = [{"role": "agent", "content": "x"}]
        pipeline._pending_tool_metadata["tool-abc"] = {"tool_name": "read"}
        pipeline._tool_start_times["tool-abc"] = 1.0
        pipeline._job_tool_ids["j1"] = {"tool-abc"}

        pipeline.cleanup_job("j1")

        assert "j1" not in pipeline._job_start_times
        assert "j1" not in pipeline._current_phases
        assert "j1" not in pipeline._turn_counters
        assert "j1" not in pipeline._transcript_buffers
        assert "tool-abc" not in pipeline._pending_tool_metadata
        assert "tool-abc" not in pipeline._tool_start_times
        assert "j1" not in pipeline._job_tool_ids

    def test_cleanup_job_unknown(self, pipeline: EventPipeline) -> None:
        """Cleaning up a non-existent job should not raise."""
        pipeline.cleanup_job("nonexistent")  # no error


# ===================================================================
# Multi-job isolation
# ===================================================================


class TestMultiJobIsolation:
    @pytest.mark.asyncio
    async def test_events_routed_to_correct_job(self, harness: _PipelineHarness, pipeline: EventPipeline) -> None:
        await pipeline.on_agent_message("job-A", "for A")
        await pipeline.on_agent_message("job-B", "for B")

        events_a = harness.transcript_events("job-A")
        events_b = harness.transcript_events("job-B")
        assert any("for A" in ev.payload.get("content", "") for ev in events_a)
        assert any("for B" in ev.payload.get("content", "") for ev in events_b)
        assert not any("for B" in ev.payload.get("content", "") for ev in events_a)

    @pytest.mark.asyncio
    async def test_turn_counters_isolated(self, pipeline: EventPipeline) -> None:
        pipeline.advance_turn("j1")
        pipeline.advance_turn("j1")
        pipeline.advance_turn("j2")

        assert pipeline.get_turn("j1") == 2
        assert pipeline.get_turn("j2") == 1

    @pytest.mark.asyncio
    async def test_cleanup_one_job_doesnt_affect_other(self, pipeline: EventPipeline) -> None:
        pipeline.set_job_start_time("j1")
        pipeline.set_job_start_time("j2")
        pipeline.advance_turn("j1")
        pipeline.advance_turn("j2")

        pipeline.cleanup_job("j1")

        assert "j1" not in pipeline._job_start_times
        assert "j2" in pipeline._job_start_times
        assert pipeline.get_turn("j2") == 1


# ===================================================================
# Transcript ring buffer (in pipeline)
# ===================================================================


class TestPipelineTranscriptBuffer:
    @pytest.mark.asyncio
    async def test_agent_message_buffers(self, pipeline: EventPipeline) -> None:
        await pipeline.on_agent_message("j1", "hello")

        assert "j1" in pipeline._transcript_buffers
        assert len(pipeline._transcript_buffers["j1"]) == 1

    @pytest.mark.asyncio
    async def test_buffer_eviction(self, pipeline: EventPipeline) -> None:
        for i in range(pipeline._TRANSCRIPT_BUFFER_SIZE + 5):
            await pipeline.on_agent_message("j1", f"msg-{i}")

        buf = pipeline._transcript_buffers["j1"]
        assert len(buf) == pipeline._TRANSCRIPT_BUFFER_SIZE
        # Oldest should be evicted
        assert buf[0]["content"] == "msg-5"

    @pytest.mark.asyncio
    async def test_tool_complete_buffers(self, pipeline: EventPipeline) -> None:
        await pipeline.on_tool_start("j1", "t1", "read_file", '{"path": "/x"}')
        await pipeline.on_tool_complete("j1", "t1", "contents", True)

        assert "j1" in pipeline._transcript_buffers
        # Should have at least one tool_call entry
        roles = [e["role"] for e in pipeline._transcript_buffers["j1"]]
        assert "tool_call" in roles

    @pytest.mark.asyncio
    async def test_cleanup_removes_buffer(self, pipeline: EventPipeline) -> None:
        await pipeline.on_agent_message("j1", "data")
        assert "j1" in pipeline._transcript_buffers

        pipeline.cleanup_job("j1")
        assert "j1" not in pipeline._transcript_buffers


# ===================================================================
# Log event emission
# ===================================================================


class TestLogEvents:
    @pytest.mark.asyncio
    async def test_tool_start_emits_log(self, harness: _PipelineHarness, pipeline: EventPipeline) -> None:
        await pipeline.on_tool_start("j1", "t1", "write_file", None)

        events = harness.events_for("j1")
        log_events = [ev for ev in events if ev.kind == SessionEventKind.log]
        assert any("write_file" in ev.payload.get("message", "") for ev in log_events)

    @pytest.mark.asyncio
    async def test_log_seq_increments(self, harness: _PipelineHarness, pipeline: EventPipeline) -> None:
        await pipeline.on_agent_message("j1", "msg1")
        await pipeline.on_agent_message("j1", "msg2")

        events = harness.events_for("j1")
        log_events = [ev for ev in events if ev.kind == SessionEventKind.log]
        if len(log_events) >= 2:
            assert log_events[1].payload["seq"] > log_events[0].payload["seq"]

    @pytest.mark.asyncio
    async def test_compaction_emits_warn_log(self, harness: _PipelineHarness, pipeline: EventPipeline) -> None:
        with patch("backend.services.analytics.telemetry") as mock_tel:
            mock_tel.compactions_counter = MagicMock()
            mock_tel.tokens_compacted = MagicMock()
            mock_tel.context_tokens_gauge = MagicMock()

            await pipeline.on_compaction("j1", 10000, 3000)

        events = harness.events_for("j1")
        log_events = [ev for ev in events if ev.kind == SessionEventKind.log]
        warn_logs = [ev for ev in log_events if ev.payload.get("level") == "warn"]
        assert len(warn_logs) >= 1
        assert "compacted" in warn_logs[0].payload["message"].lower()
