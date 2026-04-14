"""Tests for tool_classifier — classify_tool, extract_tool_target, extract_file_paths."""

from __future__ import annotations

import json

import pytest

from backend.services.tool_classifier import (
    TOOL_CATEGORIES,
    classify_tool,
    extract_file_paths,
    extract_tool_target,
)


# --- classify_tool ---


class TestClassifyTool:
    @pytest.mark.parametrize(
        "tool_name,expected",
        [
            ("read_file", "file_read"),
            ("edit_file", "file_write"),
            ("grep_search", "file_search"),
            ("bash", "shell"),
            ("git_diff", "git_read"),
            ("git_commit", "git_write"),
            ("fetch_url", "browser"),
            ("task", "agent"),
            ("Think", "thinking"),
            ("report_intent", "bookkeeping"),
        ],
    )
    def test_known_tools(self, tool_name: str, expected: str) -> None:
        assert classify_tool(tool_name) == expected

    def test_unknown_tool_returns_other(self) -> None:
        assert classify_tool("totally_unknown_tool") == "other"

    def test_mcp_style_full_match(self) -> None:
        """MCP names like 'server/read_file' try full name first."""
        # Not in TOOL_CATEGORIES as full name, so falls back to after-slash
        assert classify_tool("myserver/read_file") == "file_read"

    def test_mcp_style_unknown_suffix(self) -> None:
        assert classify_tool("myserver/unknown_thing") == "other"

    def test_mcp_style_with_known_full_name(self) -> None:
        # If "server/tool" is literally in the map, it should match first
        # Since none are, just verify fallback works on nested slashes
        assert classify_tool("a/b/bash") == "shell"

    def test_all_categories_are_known_strings(self) -> None:
        """Sanity: every value in TOOL_CATEGORIES is one of the expected buckets."""
        expected_buckets = {
            "file_read", "file_write", "file_search", "shell",
            "git_read", "git_write", "browser", "agent", "thinking", "bookkeeping",
        }
        for cat in TOOL_CATEGORIES.values():
            assert cat in expected_buckets, f"Unexpected category: {cat}"


# --- extract_tool_target ---


class TestExtractToolTarget:
    def test_file_read_target(self) -> None:
        args = json.dumps({"path": "/src/main.py"})
        assert extract_tool_target("read_file", args) == "/src/main.py"

    def test_file_write_target_filePath(self) -> None:
        args = json.dumps({"filePath": "/src/app.ts"})
        assert extract_tool_target("edit_file", args) == "/src/app.ts"

    def test_file_search_returns_query(self) -> None:
        args = json.dumps({"query": "TODO"})
        assert extract_tool_target("grep_search", args) == "TODO"

    def test_file_search_returns_pattern(self) -> None:
        args = json.dumps({"pattern": "*.py"})
        assert extract_tool_target("grep_search", args) == "*.py"

    def test_shell_returns_first_word(self) -> None:
        args = json.dumps({"command": "pytest -x backend/tests"})
        assert extract_tool_target("bash", args) == "pytest"

    def test_shell_empty_command(self) -> None:
        args = json.dumps({"command": ""})
        assert extract_tool_target("bash", args) == ""

    def test_git_read_target(self) -> None:
        args = json.dumps({"path": "README.md"})
        assert extract_tool_target("git_diff", args) == "README.md"

    def test_browser_returns_url(self) -> None:
        args = json.dumps({"url": "https://example.com"})
        assert extract_tool_target("fetch_url", args) == "https://example.com"

    def test_agent_returns_empty(self) -> None:
        """Agent category has no target extraction."""
        args = json.dumps({"prompt": "do stuff"})
        assert extract_tool_target("task", args) == ""

    def test_none_args_returns_empty(self) -> None:
        assert extract_tool_target("read_file", None) == ""

    def test_bad_json_returns_empty(self) -> None:
        assert extract_tool_target("read_file", "not json {{{") == ""

    def test_non_dict_json_returns_empty(self) -> None:
        assert extract_tool_target("read_file", json.dumps([1, 2, 3])) == ""

    def test_dict_args_not_string(self) -> None:
        """Tool args can be passed as a dict directly."""
        assert extract_tool_target("read_file", {"path": "/foo.py"}) == "/foo.py"


# --- extract_file_paths ---


class TestExtractFilePaths:
    def test_single_path_key(self) -> None:
        args = json.dumps({"path": "/a.py"})
        assert extract_file_paths("read_file", args) == ["/a.py"]

    def test_multiple_path_keys(self) -> None:
        args = json.dumps({"path": "/a.py", "filePath": "/b.py"})
        paths = extract_file_paths("read_file", args)
        assert "/a.py" in paths
        assert "/b.py" in paths

    def test_list_field_files(self) -> None:
        args = json.dumps({"files": ["/x.py", "/y.py"]})
        assert extract_file_paths("edit_file", args) == ["/x.py", "/y.py"]

    def test_list_field_paths(self) -> None:
        args = json.dumps({"paths": ["/a", "/b"]})
        paths = extract_file_paths("bash", args)
        assert paths == ["/a", "/b"]

    def test_mixed_scalar_and_list(self) -> None:
        args = json.dumps({"path": "/single.py", "files": ["/multi.py"]})
        paths = extract_file_paths("edit_file", args)
        assert "/single.py" in paths
        assert "/multi.py" in paths

    def test_none_args(self) -> None:
        assert extract_file_paths("read_file", None) == []

    def test_bad_json(self) -> None:
        assert extract_file_paths("read_file", "{{bad") == []

    def test_non_dict_json(self) -> None:
        assert extract_file_paths("read_file", '"just a string"') == []

    def test_empty_values_skipped(self) -> None:
        args = json.dumps({"path": "", "file": "", "files": ["", None]})
        # Empty strings for scalar keys are skipped (not isinstance str or falsy)
        # list items: "" is falsy so skipped, None is falsy so skipped
        paths = extract_file_paths("read_file", args)
        assert paths == []

    def test_dict_args_not_string(self) -> None:
        assert extract_file_paths("read_file", {"path": "/f.py"}) == ["/f.py"]
