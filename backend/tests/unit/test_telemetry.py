"""Tests for backend.services.telemetry span tracking and public accessors."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from backend.services import telemetry


class TestJobSpanLifecycle:
    """Tests for start_job_span / end_job_span lifecycle."""

    def setup_method(self) -> None:
        # Clear span dict between tests
        telemetry._job_spans.clear()

    def teardown_method(self) -> None:
        # Clean up any leftover spans
        for span in list(telemetry._job_spans.values()):
            span.end()
        telemetry._job_spans.clear()

    def test_start_and_end_span(self) -> None:
        telemetry.start_job_span("job-1", sdk="claude", model="sonnet")
        assert "job-1" in telemetry._job_spans

        telemetry.end_job_span("job-1")
        assert "job-1" not in telemetry._job_spans

    def test_end_nonexistent_span_is_noop(self) -> None:
        # Should not raise
        telemetry.end_job_span("nonexistent")

    def test_start_span_attributes(self) -> None:
        telemetry.start_job_span(
            "job-attr", sdk="copilot", model="gpt-4o", repo="my/repo", branch="main"
        )
        span = telemetry._job_spans["job-attr"]
        assert span is not None
        telemetry.end_job_span("job-attr")

    def test_eviction_at_max_cap(self) -> None:
        """When _JOB_SPANS_MAX is reached, oldest entries are evicted."""
        cap = telemetry._JOB_SPANS_MAX
        # Fill to capacity
        for i in range(cap):
            telemetry.start_job_span(f"job-{i}", sdk="test")
        assert len(telemetry._job_spans) == cap

        # Adding one more should evict the oldest
        telemetry.start_job_span("job-overflow", sdk="test")
        assert len(telemetry._job_spans) == cap
        assert "job-0" not in telemetry._job_spans
        assert "job-overflow" in telemetry._job_spans

    def test_eviction_ends_stale_span(self) -> None:
        """Evicted spans have .end() called on them."""
        cap = telemetry._JOB_SPANS_MAX
        for i in range(cap):
            telemetry.start_job_span(f"job-{i}", sdk="test")

        first_span = telemetry._job_spans["job-0"]
        with patch.object(first_span, "end", wraps=first_span.end) as mock_end:
            telemetry.start_job_span("job-trigger-eviction", sdk="test")
            mock_end.assert_called_once()

    def test_multiple_start_overwrites(self) -> None:
        """Starting a span for the same job_id overwrites the previous."""
        telemetry.start_job_span("job-dup", sdk="a")
        first = telemetry._job_spans["job-dup"]
        telemetry.start_job_span("job-dup", sdk="b")
        second = telemetry._job_spans["job-dup"]
        assert first is not second
        telemetry.end_job_span("job-dup")


class TestPublicAccessors:
    """Tests for get_memory_reader and get_span_exporter."""

    def test_get_memory_reader_returns_reader(self) -> None:
        reader = telemetry.get_memory_reader()
        assert reader is telemetry._memory_reader

    def test_get_span_exporter_returns_exporter(self) -> None:
        exporter = telemetry.get_span_exporter()
        assert exporter is telemetry._span_exporter


class TestInstrumentCreation:
    """Smoke tests that instruments exist and are callable."""

    def test_counters_exist(self) -> None:
        assert telemetry.tokens_input is not None
        assert telemetry.tokens_output is not None
        assert telemetry.cost_usd is not None
        assert telemetry.compactions_counter is not None
        assert telemetry.approvals_counter is not None

    def test_histograms_exist(self) -> None:
        assert telemetry.llm_duration is not None
        assert telemetry.tool_duration is not None
        assert telemetry.approval_wait is not None

    def test_gauges_exist(self) -> None:
        assert telemetry.context_tokens_gauge is not None
        assert telemetry.context_window_gauge is not None

    def test_counter_add_does_not_raise(self) -> None:
        attrs = {"job_id": "test", "sdk": "test", "model": "test"}
        telemetry.tokens_input.add(100, attrs)
        telemetry.cost_usd.add(0.01, attrs)

    def test_histogram_record_does_not_raise(self) -> None:
        attrs = {"job_id": "test", "sdk": "test", "model": "test"}
        telemetry.llm_duration.record(123.4, attrs)
