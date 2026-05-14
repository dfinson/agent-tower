"""Tests for backend.services.story.motivation — pure helpers."""

from __future__ import annotations

import json

import pytest

from backend.services.story.motivation import (
    _build_user_prompt,
    _compute_edit_key,
    _format_mini_diff,
)


# ---------------------------------------------------------------------------
# _build_user_prompt
# ---------------------------------------------------------------------------


class TestBuildUserPrompt:
    def test_with_all_fields(self):
        result = _build_user_prompt(
            tool_name="Write",
            tool_args_json='{"path": "app.py"}',
            preceding_context="Building a web app",
            job_description="Create REST API",
        )
        assert "Write" in result
        assert "Building a web app" in result

    def test_no_context(self):
        result = _build_user_prompt(
            tool_name="Edit",
            tool_args_json="{}",
            preceding_context="",
            job_description=None,
        )
        assert "Edit" in result


# ---------------------------------------------------------------------------
# _compute_edit_key
# ---------------------------------------------------------------------------


class TestComputeEditKey:
    def test_deterministic(self):
        args = {"filePath": "/src/app.py", "oldString": "a", "newString": "b"}
        key1 = _compute_edit_key("edit", args)
        key2 = _compute_edit_key("edit", args)
        assert key1 == key2

    def test_different_args(self):
        args1 = {"filePath": "/a.py", "oldString": "x"}
        args2 = {"filePath": "/b.py", "oldString": "y"}
        assert _compute_edit_key("edit", args1) != _compute_edit_key("edit", args2)

    def test_create_tool(self):
        args = {"content": "hello world"}
        result = _compute_edit_key("create_file", args)
        assert result.startswith("create:")

    def test_empty_args(self):
        result = _compute_edit_key("edit", {})
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# _format_mini_diff
# ---------------------------------------------------------------------------


class TestFormatMiniDiff:
    def test_old_new_string(self):
        args = {"oldString": "old_code", "newString": "new_code"}
        result = _format_mini_diff("Edit", args, "app.py")
        assert "old_code" in result
        assert "new_code" in result

    def test_create(self):
        args = {"content": "new file content"}
        result = _format_mini_diff("create_file", args, "new.py")
        assert "new file content" in result
        assert "CREATED" in result

    def test_empty_args(self):
        result = _format_mini_diff("edit", {}, "file.py")
        assert isinstance(result, str)
        assert "file.py" in result

    def test_no_file_path(self):
        result = _format_mini_diff("edit", {}, None)
        assert "(unknown)" in result
