"""Tests for backend.services.tool_formatters._display — pure formatters and hints."""

from __future__ import annotations

import json

from backend.services.tool_formatters._display import (
    _count_lines,
    _extract_description_from_args,
    _fmt_computer,
    _fmt_fetch_webpage,
    _fmt_get_errors,
    _fmt_manage_todo,
    _fmt_memory,
    _fmt_multi_edit,
    _fmt_multi_replace,
    _fmt_read_file,
    _fmt_read_mcp_resource,
    _fmt_rename_symbol,
    _fmt_view,
    _get_edit_strings,
    _hint_bash,
    _hint_edit_with_args,
    _hint_fetch_webpage,
    _hint_get_errors,
    _hint_memory,
    _hint_multi_edit_with_args,
    _hint_multi_replace,
    _hint_replace_string,
    _hint_subagent,
    _humanize_tool_name,
    _parse_args,
    _short_path,
    _trim_worktree_paths,
    extract_issue_from_json,
    format_tool_display,
    format_tool_display_full,
    truncate,
)

# ---------------------------------------------------------------------------
# truncate
# ---------------------------------------------------------------------------


class TestTruncate:
    def test_identity(self):
        assert truncate("hello world") == "hello world"

    def test_long_string_unchanged(self):
        s = "x" * 200
        assert truncate(s) == s


# ---------------------------------------------------------------------------
# _parse_args
# ---------------------------------------------------------------------------


class TestParseArgs:
    def test_none(self):
        assert _parse_args(None) == {}

    def test_empty_string(self):
        assert _parse_args("") == {}

    def test_valid_json_dict(self):
        assert _parse_args('{"a": 1}') == {"a": 1}

    def test_json_array_returns_empty(self):
        assert _parse_args("[1, 2]") == {}

    def test_invalid_json(self):
        assert _parse_args("not json") == {}


# ---------------------------------------------------------------------------
# extract_issue_from_json
# ---------------------------------------------------------------------------


class TestExtractIssue:
    def test_error_key(self):
        assert extract_issue_from_json({"error": "boom"}) == "boom"

    def test_nested_message(self):
        assert extract_issue_from_json({"outer": {"message": "inner"}}) == "inner"

    def test_list_search(self):
        assert extract_issue_from_json([{"detail": "found"}]) == "found"

    def test_no_match(self):
        assert extract_issue_from_json({"foo": 42}) is None

    def test_empty_string_skipped(self):
        assert extract_issue_from_json({"error": "", "message": "ok"}) == "ok"


# ---------------------------------------------------------------------------
# _short_path
# ---------------------------------------------------------------------------


class TestShortPath:
    def test_worktree_prefix_stripped(self):
        path = "/home/user/.codeplane-worktrees/my-branch/src/app.py"
        assert _short_path(path) == "…/my-branch/src/app.py"

    def test_long_absolute_path(self):
        path = "/home/user/projects/myapp/src/deep/file.py"
        assert _short_path(path) == "deep/file.py"

    def test_short_path_unchanged(self):
        assert _short_path("a/b") == "a/b"


# ---------------------------------------------------------------------------
# _trim_worktree_paths
# ---------------------------------------------------------------------------


class TestTrimWorktreePaths:
    def test_strips_worktree(self):
        cmd = "cat /home/user/.codeplane-worktrees/my-branch/src/f.py"
        assert _trim_worktree_paths(cmd) == "cat …/my-branch/src/f.py"

    def test_preserves_option(self):
        cmd = "--path=/home/user/.codeplane-worktrees/branch/f.py"
        assert _trim_worktree_paths(cmd) == "--path=…/branch/f.py"

    def test_no_worktree(self):
        cmd = "ls -la"
        assert _trim_worktree_paths(cmd) == "ls -la"


# ---------------------------------------------------------------------------
# Complex formatters
# ---------------------------------------------------------------------------


class TestFmtMultiEdit:
    def test_with_paths(self):
        args = {"edits": [{"file_path": "/src/a.py"}, {"file_path": "/src/b.py"}]}
        result = _fmt_multi_edit(args)
        assert "Edit" in result

    def test_no_paths(self):
        args = {"edits": [{}, {}]}
        result = _fmt_multi_edit(args)
        assert "2 locations" in result

    def test_empty_edits(self):
        assert _fmt_multi_edit({}) == "Edit 0 locations"


class TestFmtComputer:
    def test_screenshot(self):
        assert _fmt_computer({"action": "screenshot"}) == "Take screenshot"

    def test_key(self):
        assert _fmt_computer({"action": "key", "text": "Enter"}) == "Key: Enter"

    def test_type(self):
        assert _fmt_computer({"action": "type", "text": "hello"}) == "Type: hello"

    def test_mouse_move_with_coords(self):
        result = _fmt_computer({"action": "left_click", "coordinate": [100, 200]})
        assert "Left Click" in result
        assert "100" in result

    def test_unknown_action(self):
        assert _fmt_computer({"action": "scroll"}) == "Computer: scroll"

    def test_empty_action(self):
        assert _fmt_computer({}) == "Computer action"


class TestFmtReadMcpResource:
    def test_with_uri(self):
        assert _fmt_read_mcp_resource({"uri": "file:///a.txt"}) == "Read MCP: file:///a.txt"

    def test_with_server(self):
        assert _fmt_read_mcp_resource({"server_name": "my-srv"}) == "Read MCP resource (my-srv)"

    def test_empty(self):
        assert _fmt_read_mcp_resource({}) == "Read MCP resource"


class TestFmtReadFile:
    def test_with_lines(self):
        result = _fmt_read_file({"filePath": "/src/app.py", "startLine": 10, "endLine": 20})
        assert "Read" in result
        assert "10-20" in result

    def test_without_lines(self):
        result = _fmt_read_file({"filePath": "/src/app.py"})
        assert "Read" in result

    def test_empty(self):
        assert _fmt_read_file({}) == "Read file"


class TestFmtMultiReplace:
    def test_with_paths(self):
        args = {"replacements": [{"filePath": "/src/a.py"}, {"filePath": "/src/b.py"}]}
        result = _fmt_multi_replace(args)
        assert "Edit" in result

    def test_empty(self):
        assert _fmt_multi_replace({}) == "Edit 0 locations"


class TestFmtMemory:
    def test_with_cmd_and_path(self):
        assert _fmt_memory({"command": "view", "path": "/notes.md"}) == "Memory view: /notes.md"

    def test_cmd_only(self):
        assert _fmt_memory({"command": "list"}) == "Memory list"

    def test_empty(self):
        assert _fmt_memory({}) == "Memory"


class TestFmtManageTodo:
    def test_with_items(self):
        assert _fmt_manage_todo({"todoList": [1, 2, 3]}) == "Update todo list (3 items)"

    def test_empty(self):
        assert _fmt_manage_todo({}) == "Update todo list"


class TestFmtGetErrors:
    def test_all_errors(self):
        assert _fmt_get_errors({}) == "Check all errors"

    def test_single_file(self):
        result = _fmt_get_errors({"filePaths": ["/src/app.py"]})
        assert "Check errors" in result

    def test_multi_files(self):
        result = _fmt_get_errors({"filePaths": ["/a.py", "/b.py"]})
        assert "2 files" in result


class TestFmtRenameSymbol:
    def test_rename(self):
        assert _fmt_rename_symbol({"oldName": "foo", "newName": "bar"}) == "Rename foo → bar"

    def test_empty(self):
        assert _fmt_rename_symbol({}) == "Rename symbol"


class TestFmtView:
    def test_with_range(self):
        result = _fmt_view({"path": "/src/app.py", "view_range": [10, 20]})
        assert "View" in result
        assert "10-20" in result

    def test_without_range(self):
        result = _fmt_view({"path": "/src/app.py"})
        assert "View" in result

    def test_open_end_range(self):
        result = _fmt_view({"path": "/src/app.py", "view_range": [10, -1]})
        assert "10–end" in result

    def test_empty(self):
        assert _fmt_view({}) == "View file"


class TestFmtFetchWebpage:
    def test_with_url(self):
        result = _fmt_fetch_webpage({"url": "https://example.com/page"})
        assert "Fetch" in result
        assert "example.com" in result

    def test_empty(self):
        assert _fmt_fetch_webpage({}) == "Fetch webpage"


# ---------------------------------------------------------------------------
# Result hint helpers
# ---------------------------------------------------------------------------


class TestCountLines:
    def test_counts_nonempty(self):
        assert _count_lines("a\n\nb\nc") == 3

    def test_empty(self):
        assert _count_lines("") == 0


class TestHintBash:
    def test_success(self):
        result = _hint_bash("line1\nline2\n", True)
        assert "2 lines" in result

    def test_failure(self):
        result = _hint_bash("error: something\ndetail", False)
        assert "FAIL" in result
        assert "error: something" in result

    def test_success_empty(self):
        assert _hint_bash("", True) == "→ done"


class TestHintReplaceString:
    def test_success(self):
        assert _hint_replace_string("", True) == "→ applied"

    def test_failure(self):
        assert _hint_replace_string("", False) == "→ FAIL: no match"


class TestHintMultiReplace:
    def test_success(self):
        assert _hint_multi_replace("", True) == "→ applied"

    def test_failure(self):
        assert _hint_multi_replace("", False) == "→ partial FAIL"


class TestGetEditStrings:
    def test_old_new_string(self):
        old, new = _get_edit_strings({"oldString": "a", "newString": "b"})
        assert old == "a"
        assert new == "b"

    def test_old_str_variant(self):
        old, new = _get_edit_strings({"old_str": "x", "new_str": "y"})
        assert old == "x"
        assert new == "y"

    def test_empty(self):
        old, new = _get_edit_strings({})
        assert old == ""
        assert new == ""


class TestHintEditWithArgs:
    def test_success_with_lines(self):
        args = json.dumps({"oldString": "a\nb", "newString": "c\nd\ne"})
        result = _hint_edit_with_args("", True, args)
        assert "3 lines" in result

    def test_success_no_args(self):
        assert _hint_edit_with_args("", True) == "→ applied"

    def test_failure(self):
        assert _hint_edit_with_args("", False) == "→ FAIL: no match"


class TestHintMultiEditWithArgs:
    def test_success(self):
        args = json.dumps({"replacements": [{"oldString": "a\nb", "newString": "c"}]})
        result = _hint_multi_edit_with_args("", True, args)
        assert "2 lines" in result

    def test_failure(self):
        assert _hint_multi_edit_with_args("", False) == "→ partial FAIL"


class TestHintGetErrors:
    def test_clean(self):
        assert _hint_get_errors("", True) == "→ clean"

    def test_with_diagnostics(self):
        result = _hint_get_errors("error 1\nerror 2", True)
        assert "2 diagnostics" in result


class TestHintSubagent:
    def test_failure(self):
        assert _hint_subagent("", False) == "→ FAIL"

    def test_success_multi_line(self):
        result = _hint_subagent("a\nb\nc", True)
        assert "done" in result

    def test_success_single_line(self):
        assert _hint_subagent("ok", True) == "→ done"


class TestHintFetchWebpage:
    def test_failure(self):
        assert _hint_fetch_webpage("", False) == "→ FAIL"

    def test_large(self):
        result = _hint_fetch_webpage("x" * 2048, True)
        assert "KB" in result

    def test_small(self):
        result = _hint_fetch_webpage("small", True)
        assert "bytes" in result


class TestHintMemory:
    def test_failure(self):
        assert _hint_memory("", False) == "→ FAIL"

    def test_with_lines(self):
        result = _hint_memory("a\nb\n", True)
        assert "2 lines" in result

    def test_empty(self):
        assert _hint_memory("", True) == "→ done"


# ---------------------------------------------------------------------------
# _humanize_tool_name
# ---------------------------------------------------------------------------


class TestHumanizeToolName:
    def test_snake_case(self):
        assert _humanize_tool_name("search_code") == "Search code"

    def test_camel_case(self):
        result = _humanize_tool_name("listAllFiles")
        assert result == "List all files"

    def test_uuid(self):
        assert _humanize_tool_name("a1b2c3d4-e5f6-7890-abcd-ef1234567890") == "Tool action"

    def test_hex(self):
        assert _humanize_tool_name("abcdef12") == "Tool action"

    def test_single_word(self):
        assert _humanize_tool_name("Bash") == "Bash"


# ---------------------------------------------------------------------------
# _extract_description_from_args
# ---------------------------------------------------------------------------


class TestExtractDescription:
    def test_description_key(self):
        args = json.dumps({"description": "Find the bug"})
        assert _extract_description_from_args(args) == "Find the bug"

    def test_query_key(self):
        args = json.dumps({"query": "search term"})
        assert _extract_description_from_args(args) == "search term"

    def test_none(self):
        assert _extract_description_from_args(None) is None

    def test_no_matching_keys(self):
        args = json.dumps({"foo": "bar"})
        assert _extract_description_from_args(args) is None


# ---------------------------------------------------------------------------
# format_tool_display / format_tool_display_full
# ---------------------------------------------------------------------------


class TestFormatToolDisplay:
    def test_known_tool(self):
        args = json.dumps({"command": "ls -la"})
        result = format_tool_display("bash", args)
        assert "ls -la" in result

    def test_unknown_tool_with_description(self):
        args = json.dumps({"description": "Do something"})
        result = format_tool_display("custom_tool", args)
        assert "Do something" in result

    def test_unknown_tool_no_args(self):
        result = format_tool_display("custom_tool", None)
        assert "Custom tool" in result

    def test_with_result_hint(self):
        args = json.dumps({"command": "echo hi"})
        result = format_tool_display("bash", args, tool_result="output\nline2", tool_success=True)
        assert "2 lines" in result

    def test_full_variant_no_truncation(self):
        args = json.dumps({"command": "very long command " * 20})
        short = format_tool_display("bash", args)
        full = format_tool_display_full("bash", args)
        # Full should be at least as long as short
        assert len(full) >= len(short)

    def test_namespaced_tool(self):
        args = json.dumps({"command": "test"})
        result = format_tool_display("mcp/bash", args)
        assert "test" in result

    def test_read_file_with_lines_hint(self):
        args = json.dumps({"filePath": "/src/app.py", "startLine": 1, "endLine": 10})
        result = format_tool_display("read_file", args, tool_result="a\nb\nc", tool_success=True)
        assert "lines" in result

    def test_edit_with_args_hint(self):
        args = json.dumps({"filePath": "/f.py", "oldString": "a\nb", "newString": "c\nd\ne"})
        result = format_tool_display("replace_string_in_file", args, tool_result="ok", tool_success=True)
        assert "3 lines" in result
