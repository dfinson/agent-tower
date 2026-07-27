"""Tests for backend.console_dashboard — ConsoleLog, ConsoleLogHandler, _JobInfo."""

from __future__ import annotations

import logging
from unittest.mock import patch

import pytest

from backend.console_dashboard import (
    _STATE_ICON,
    _STATE_STYLE,
    _TERMINAL_STATES,
    ConsoleLog,
    ConsoleLogHandler,
    _JobInfo,
)
from backend.models.events import EventKind, SessionEvent, new_event

# ── _JobInfo ──


class TestJobInfo:
    def test_init(self):
        job = _JobInfo("job-1")
        assert job.job_id == "job-1"
        assert job.title is None

    def test_elapsed_seconds(self):
        job = _JobInfo("job-1")
        # Directly test elapsed formatting by monkey-patching started_at
        import time

        job.started_at = time.monotonic() - 30
        elapsed = job.elapsed()
        assert elapsed.endswith("s")

    def test_elapsed_minutes(self):
        import time

        job = _JobInfo("job-1")
        job.started_at = time.monotonic() - 125  # 2m 5s
        elapsed = job.elapsed()
        assert "m" in elapsed


# ── Constants ──


class TestConstants:
    def test_state_icons(self):
        assert _STATE_ICON["queued"] == "○"
        assert _STATE_ICON["running"] == "●"
        assert _STATE_ICON["completed"] == "✓"
        assert _STATE_ICON["failed"] == "✗"

    def test_state_styles(self):
        assert "green" in _STATE_STYLE["completed"]
        assert "red" in _STATE_STYLE["failed"]

    def test_terminal_states(self):
        assert frozenset({"completed", "failed", "canceled"}) == _TERMINAL_STATES


# ── ConsoleLog ──


class TestConsoleLog:
    def test_create_if_tty_non_tty(self):
        with patch("sys.stderr") as mock_stderr:
            mock_stderr.isatty.return_value = False
            result = ConsoleLog.create_if_tty()
        assert result is None

    def test_create_if_tty_with_tty(self):
        with patch("sys.stderr") as mock_stderr:
            mock_stderr.isatty.return_value = True
            result = ConsoleLog.create_if_tty()
        assert isinstance(result, ConsoleLog)

    def test_is_started_initially_false(self):
        log = ConsoleLog()
        assert log.is_started is False

    def test_start_sets_started(self):
        log = ConsoleLog()
        log.start()
        assert log.is_started is True

    def test_stop_clears_started(self):
        log = ConsoleLog()
        log.start()
        log.stop()
        assert log.is_started is False

    def test_stop_without_start(self):
        log = ConsoleLog()
        log.stop()  # Should not raise
        assert log.is_started is False

    def test_double_start(self):
        log = ConsoleLog()
        log.start()
        log.start()  # Should not raise
        assert log.is_started is True

    def test_set_server_info(self):
        log = ConsoleLog()
        log.set_server_info(
            server_url="http://localhost:8080",
            tunnel_url="https://example.ngrok.io",
            password="secret",
        )
        assert log._server_url == "http://localhost:8080"
        assert log._tunnel_url == "https://example.ngrok.io"
        assert log._password == "secret"

    def test_start_with_server_info(self):
        log = ConsoleLog()
        log.set_server_info(server_url="http://localhost:8080")
        log.start()
        assert log.is_started is True


# ── ConsoleLog._apply_event ──


class TestApplyEvent:
    def _make_event(self, kind: EventKind, job_id: str = "job-1", **payload) -> SessionEvent:
        return new_event(session_id=job_id, kind=kind, payload=payload)

    def test_job_created(self):
        log = ConsoleLog()
        log.start()
        event = self._make_event(EventKind.job_created)
        log._apply_event(event)
        assert "job-1" in log._jobs

    def test_job_state_changed(self):
        log = ConsoleLog()
        log.start()
        event = self._make_event(EventKind.job_state_changed, new_state="running")
        log._apply_event(event)
        assert "job-1" in log._jobs

    def test_job_completed(self):
        log = ConsoleLog()
        log.start()
        log._jobs["job-1"] = _JobInfo("job-1")
        event = self._make_event(EventKind.job_completed)
        log._apply_event(event)
        assert "job-1" not in log._jobs

    def test_job_failed(self):
        log = ConsoleLog()
        log.start()
        log._jobs["job-1"] = _JobInfo("job-1")
        event = self._make_event(EventKind.job_failed)
        log._apply_event(event)
        assert "job-1" not in log._jobs

    def test_job_canceled(self):
        log = ConsoleLog()
        log.start()
        log._jobs["job-1"] = _JobInfo("job-1")
        event = self._make_event(EventKind.job_canceled)
        log._apply_event(event)
        assert "job-1" not in log._jobs

    def test_job_title_updated(self):
        log = ConsoleLog()
        log.start()
        log._jobs["job-1"] = _JobInfo("job-1")
        event = self._make_event(EventKind.job_title_updated, title="My Task")
        log._apply_event(event)
        assert log._jobs["job-1"].title == "My Task"

    def test_no_job_id_ignored(self):
        log = ConsoleLog()
        log.start()
        event = new_event(session_id="", kind=EventKind.job_created, payload={})
        log._apply_event(event)
        assert len(log._jobs) == 0

    def test_approval_requested(self):
        log = ConsoleLog()
        log.start()
        log._jobs["job-1"] = _JobInfo("job-1")
        event = self._make_event(
            EventKind.approval_requested,
            description="run npm install",
        )
        log._apply_event(event)  # Should not raise

    def test_completed_with_title(self):
        log = ConsoleLog()
        log.start()
        job = _JobInfo("job-1")
        job.title = "Build feature"
        log._jobs["job-1"] = job
        event = self._make_event(EventKind.job_completed)
        log._apply_event(event)
        assert "job-1" not in log._jobs


# ── ConsoleLog.add_log_record ──


class TestAddLogRecord:
    def test_error_record(self):
        log = ConsoleLog()
        log.start()
        record = logging.LogRecord(
            name="backend.services.test",
            level=logging.ERROR,
            pathname="test.py",
            lineno=1,
            msg="Something went wrong",
            args=None,
            exc_info=None,
        )
        log.add_log_record(record)  # Should not raise

    def test_warning_record_ignored(self):
        log = ConsoleLog()
        log.start()
        record = logging.LogRecord(
            name="backend.test",
            level=logging.WARNING,
            pathname="test.py",
            lineno=1,
            msg="Just a warning",
            args=None,
            exc_info=None,
        )
        log.add_log_record(record)  # Should not raise, but not print


# ── ConsoleLog.handle_event ──


class TestHandleEvent:
    @pytest.mark.asyncio()
    async def test_handle_event(self):
        log = ConsoleLog()
        log.start()
        event = new_event(session_id="job-1", kind=EventKind.job_created, payload={})
        await log.handle_event(event)
        assert "job-1" in log._jobs


# ── ConsoleLogHandler ──


class TestConsoleLogHandler:
    def test_before_start_uses_fallback(self):
        console_log = ConsoleLog()
        formatter = logging.Formatter("%(message)s")
        filter_ = logging.Filter()
        handler = ConsoleLogHandler(console_log, formatter, filter_)
        record = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname="test.py",
            lineno=1,
            msg="Error message",
            args=None,
            exc_info=None,
        )
        handler.emit(record)  # Should use fallback

    def test_after_start_routes_to_console_log(self):
        console_log = ConsoleLog()
        console_log.start()
        formatter = logging.Formatter("%(message)s")
        filter_ = logging.Filter()
        handler = ConsoleLogHandler(console_log, formatter, filter_)
        record = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname="test.py",
            lineno=1,
            msg="Error message",
            args=None,
            exc_info=None,
        )
        handler.emit(record)  # Should route to console_log.add_log_record
