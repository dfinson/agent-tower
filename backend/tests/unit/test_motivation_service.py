"""Tests for backend.services.motivation_service helpers and drain logic."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from backend.services.motivation_service import (
    MotivationService,
    _build_edit_prompt,
    _build_user_prompt,
    _compute_edit_key,
    _format_mini_diff,
)


class TestComputeEditKey:
    """Tests for _compute_edit_key fingerprinting."""

    def test_create_file_key(self) -> None:
        key = _compute_edit_key("create_file", {"file_text": "hello world"})
        assert key.startswith("create:")
        assert len(key) > len("create:")

    def test_replace_key(self) -> None:
        key = _compute_edit_key("replace", {"old_str": "foo", "new_str": "bar"})
        assert key.startswith("replace:")

    def test_replace_old_string_variant(self) -> None:
        key = _compute_edit_key("edit", {"oldString": "x"})
        assert key.startswith("replace:")

    def test_insert_key(self) -> None:
        key = _compute_edit_key("insert", {"insert_line": 42})
        assert key == "insert:L42"

    def test_unknown_key(self) -> None:
        key = _compute_edit_key("mysterious_tool", {"some_arg": "val"})
        assert key.startswith("unknown:")

    def test_deterministic(self) -> None:
        k1 = _compute_edit_key("create", {"file_text": "same content"})
        k2 = _compute_edit_key("create", {"file_text": "same content"})
        assert k1 == k2

    def test_different_content_different_key(self) -> None:
        k1 = _compute_edit_key("create", {"file_text": "content a"})
        k2 = _compute_edit_key("create", {"file_text": "content b"})
        assert k1 != k2


class TestFormatMiniDiff:
    """Tests for _format_mini_diff output formatting."""

    def test_create_file(self) -> None:
        result = _format_mini_diff("create_file", {"file_text": "print('hi')"}, "src/main.py")
        assert "FILE: src/main.py" in result
        assert "CREATED" in result
        assert "print('hi')" in result

    def test_replace(self) -> None:
        result = _format_mini_diff("replace", {"old_str": "foo", "new_str": "bar"}, "src/a.py")
        assert "REPLACED" in result
        assert "- foo" in result
        assert "+ bar" in result

    def test_insert(self) -> None:
        result = _format_mini_diff("insert", {"insert_line": 10, "new_text": "new code"}, "src/b.py")
        assert "INSERTED at line 10" in result
        assert "new code" in result

    def test_unknown_tool(self) -> None:
        result = _format_mini_diff("mystery", {"x": 1}, None)
        assert "FILE: (unknown)" in result
        assert "mystery" in result


class TestBuildUserPrompt:
    """Tests for _build_user_prompt assembly."""

    def test_basic_prompt(self) -> None:
        result = _build_user_prompt(
            tool_name="replace",
            tool_args_json='{"old_str": "a"}',
            preceding_context="agent said something",
        )
        assert "PRECEDING CONTEXT" in result
        assert "TOOL CALLED: replace" in result
        assert "TOOL ARGS" in result

    def test_with_job_description(self) -> None:
        result = _build_user_prompt(
            tool_name="edit",
            tool_args_json=None,
            preceding_context="context here",
            job_description="Fix the auth bug",
        )
        assert "JOB DESCRIPTION" in result
        assert "Fix the auth bug" in result

    def test_no_tool_args(self) -> None:
        result = _build_user_prompt(
            tool_name="read",
            tool_args_json=None,
            preceding_context="some context",
        )
        assert "TOOL ARGS" not in result


class TestBuildEditPrompt:
    """Tests for _build_edit_prompt assembly."""

    def test_with_all_context(self) -> None:
        result = _build_edit_prompt(
            tool_name="replace",
            parsed_args={"old_str": "x", "new_str": "y"},
            file_path="src/a.py",
            preceding_context="context",
            file_level_summary="File-level: fixed bug",
        )
        assert "FILE-LEVEL SUMMARY" in result
        assert "PRECEDING CONTEXT" in result
        assert "SPECIFIC EDIT" in result

    def test_without_optional_context(self) -> None:
        result = _build_edit_prompt(
            tool_name="create",
            parsed_args={"file_text": "content"},
            file_path="new.py",
            preceding_context=None,
            file_level_summary=None,
        )
        assert "SPECIFIC EDIT" in result
        assert "FILE-LEVEL SUMMARY" not in result


class TestMotivationServiceDrain:
    """Tests for MotivationService.drain_unsummarized."""

    @pytest.mark.asyncio
    async def test_drain_empty_returns_zero(self) -> None:
        mock_session = AsyncMock()
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_session_factory = lambda: mock_ctx  # noqa: E731

        completer = AsyncMock()
        svc = MotivationService(session_factory=mock_session_factory, completer=completer)

        with patch(
            "backend.persistence.telemetry_spans_repo.TelemetrySpansRepository"
        ) as MockRepo:
            repo_inst = AsyncMock()
            repo_inst.unsummarized_spans = AsyncMock(return_value=[])
            MockRepo.return_value = repo_inst

            count = await svc.drain_unsummarized()
            assert count == 0

    @pytest.mark.asyncio
    async def test_drain_processes_span(self) -> None:
        mock_session = AsyncMock()
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_session_factory = lambda: mock_ctx  # noqa: E731

        completer = AsyncMock()
        completer.complete = AsyncMock(return_value="Title line\nExplanation line")

        svc = MotivationService(session_factory=mock_session_factory, completer=completer)

        span = {
            "id": "span-1",
            "job_id": "job-1",
            "name": "replace",
            "tool_args_json": '{"old_str": "a"}',
            "preceding_context": "agent edited something",
        }

        with (
            patch(
                "backend.persistence.telemetry_spans_repo.TelemetrySpansRepository"
            ) as MockRepo,
            patch(
                "backend.persistence.job_repo.JobRepository"
            ) as MockJobRepo,
        ):
            repo_inst = AsyncMock()
            repo_inst.unsummarized_spans = AsyncMock(return_value=[span])
            repo_inst.set_motivation_summary = AsyncMock()
            MockRepo.return_value = repo_inst

            job_repo_inst = AsyncMock()
            job_repo_inst.get = AsyncMock(return_value=None)
            MockJobRepo.return_value = job_repo_inst

            count = await svc.drain_unsummarized()
            assert count == 1
            repo_inst.set_motivation_summary.assert_called_once_with(
                "span-1", "Title line\nExplanation line"
            )


class TestEditMotivationDrain:
    """Tests for MotivationService.drain_edit_motivations."""

    @pytest.mark.asyncio
    async def test_drain_edit_no_tool_args(self) -> None:
        mock_session = AsyncMock()
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_session_factory = lambda: mock_ctx  # noqa: E731

        completer = AsyncMock()
        svc = MotivationService(session_factory=mock_session_factory, completer=completer)

        span = {"id": "span-1", "name": "replace", "tool_args_json": None}

        with patch(
            "backend.persistence.telemetry_spans_repo.TelemetrySpansRepository"
        ) as MockRepo:
            repo_inst = AsyncMock()
            repo_inst.unenriched_edit_spans = AsyncMock(return_value=[span])
            repo_inst.set_edit_motivations = AsyncMock()
            MockRepo.return_value = repo_inst

            count = await svc.drain_edit_motivations()
            assert count == 1
            repo_inst.set_edit_motivations.assert_called_once_with("span-1", "[]")
