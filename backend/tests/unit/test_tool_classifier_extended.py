"""Tests for backend.services.tools.tool_classifier — pure classification functions."""

from __future__ import annotations

import json

from backend.services.tools.tool_classifier import (
    _classify_segment,
    _is_verification_segment,
    _split_shell,
    _strip_env_vars,
    classify_action_from_tools,
    classify_shell_command,
    classify_tool,
    classify_tool_activity,
    extract_file_paths,
    extract_tool_target,
    refine_shell_category,
    shell_action,
)

# ---------------------------------------------------------------------------
# _split_shell
# ---------------------------------------------------------------------------


class TestSplitShell:
    def test_simple(self):
        assert _split_shell("ls -la") == ["ls -la"]

    def test_and(self):
        assert _split_shell("cd dir && ls") == ["cd dir", "ls"]

    def test_or(self):
        assert _split_shell("cmd1 || cmd2") == ["cmd1", "cmd2"]

    def test_pipe(self):
        assert _split_shell("cat file | grep foo") == ["cat file", "grep foo"]

    def test_semicolon(self):
        assert _split_shell("cmd1; cmd2") == ["cmd1", "cmd2"]

    def test_quoted_separators(self):
        assert _split_shell('echo "a && b"') == ['echo "a && b"']

    def test_single_quoted(self):
        assert _split_shell("echo 'a | b'") == ["echo 'a | b'"]

    def test_empty(self):
        assert _split_shell("") == []


# ---------------------------------------------------------------------------
# _strip_env_vars
# ---------------------------------------------------------------------------


class TestStripEnvVars:
    def test_sudo(self):
        assert _strip_env_vars("sudo ls") == "ls"

    def test_env_vars(self):
        assert _strip_env_vars("FOO=bar cmd") == "cmd"

    def test_stacked(self):
        assert _strip_env_vars("sudo env FOO=1 cmd") == "cmd"

    def test_no_prefix(self):
        assert _strip_env_vars("cmd --flag") == "cmd --flag"


# ---------------------------------------------------------------------------
# _is_verification_segment
# ---------------------------------------------------------------------------


class TestIsVerificationSegment:
    def test_pytest(self):
        assert _is_verification_segment("pytest") is True

    def test_uv_run_pytest(self):
        assert _is_verification_segment("uv run pytest tests/") is True

    def test_jest(self):
        assert _is_verification_segment("jest --coverage") is True

    def test_make_test(self):
        assert _is_verification_segment("make test") is True

    def test_eslint(self):
        assert _is_verification_segment("eslint src/") is True

    def test_cargo_build(self):
        assert _is_verification_segment("npm run build") is True

    def test_not_verification(self):
        assert _is_verification_segment("ls -la") is False


# ---------------------------------------------------------------------------
# _classify_segment
# ---------------------------------------------------------------------------


class TestClassifySegment:
    def test_verification(self):
        assert _classify_segment("pytest tests/") == "verification"

    def test_git_write(self):
        assert _classify_segment("git commit -m 'msg'") == "git_ops"

    def test_git_read(self):
        assert _classify_segment("git diff HEAD") == "investigation"

    def test_setup(self):
        assert _classify_segment("pip install requests") == "setup"

    def test_implementation(self):
        assert _classify_segment("sed -i 's/old/new/g' file.py") == "implementation"

    def test_investigation(self):
        assert _classify_segment("cat file.py") == "investigation"

    def test_unknown(self):
        assert _classify_segment("myapp start") == "shell_other"


# ---------------------------------------------------------------------------
# classify_shell_command
# ---------------------------------------------------------------------------


class TestClassifyShellCommand:
    def test_compound_highest_priority(self):
        # verification > git_ops > investigation
        result = classify_shell_command("git diff HEAD && pytest")
        assert result == "verification"

    def test_single_git_write(self):
        assert classify_shell_command("git commit -m 'msg'") == "git_ops"

    def test_setup(self):
        assert classify_shell_command("npm install") == "setup"

    def test_empty(self):
        assert classify_shell_command("") == "shell_other"


# ---------------------------------------------------------------------------
# shell_action
# ---------------------------------------------------------------------------


class TestShellAction:
    def test_test(self):
        assert shell_action("pytest") == "test"

    def test_vcs(self):
        assert shell_action("git commit -m 'msg'") == "vcs"

    def test_read(self):
        assert shell_action("cat file.py") == "read"

    def test_execute(self):
        assert shell_action("myapp start") == "execute"


# ---------------------------------------------------------------------------
# classify_action_from_tools
# ---------------------------------------------------------------------------


class TestClassifyActionFromTools:
    def test_write_priority(self):
        assert classify_action_from_tools(["file_write", "file_read"]) == "write"

    def test_shell_test(self):
        assert classify_action_from_tools(["shell"], shell_commands=["pytest"]) == "test"

    def test_delegate(self):
        assert classify_action_from_tools(["agent"]) == "delegate"

    def test_read(self):
        assert classify_action_from_tools(["file_read"]) == "read"

    def test_think_default(self):
        assert classify_action_from_tools(["thinking"]) == "think"

    def test_vcs_via_git_write(self):
        assert classify_action_from_tools(["git_write"]) == "vcs"


# ---------------------------------------------------------------------------
# classify_tool
# ---------------------------------------------------------------------------


class TestClassifyTool:
    def test_known_tool(self):
        assert classify_tool("read_file") == "file_read"
        assert classify_tool("Write") == "file_write"
        assert classify_tool("bash") == "shell"

    def test_unknown(self):
        assert classify_tool("custom_thing") == "other"

    def test_mcp_namespaced(self):
        assert classify_tool("server/bash") == "shell"

    def test_mcp_unknown(self):
        assert classify_tool("server/unknown") == "other"


# ---------------------------------------------------------------------------
# refine_shell_category
# ---------------------------------------------------------------------------


class TestRefineShellCategory:
    def test_git_write(self):
        args = json.dumps({"command": "git commit -m 'msg'"})
        assert refine_shell_category(args) == "git_write"

    def test_git_read(self):
        args = json.dumps({"command": "git diff"})
        assert refine_shell_category(args) == "git_read"

    def test_non_git(self):
        args = json.dumps({"command": "ls -la"})
        assert refine_shell_category(args) is None

    def test_none(self):
        assert refine_shell_category(None) is None


# ---------------------------------------------------------------------------
# classify_tool_activity
# ---------------------------------------------------------------------------


class TestClassifyToolActivity:
    def test_agent_delegation(self):
        assert classify_tool_activity("runSubagent") == "_delegation"

    def test_shell_with_verification(self):
        args = json.dumps({"command": "pytest tests/"})
        assert classify_tool_activity("bash", args) == "verification"

    def test_file_write(self):
        assert classify_tool_activity("Write") == "implementation"

    def test_file_read(self):
        assert classify_tool_activity("Read") == "investigation"


# ---------------------------------------------------------------------------
# extract_tool_target
# ---------------------------------------------------------------------------


class TestExtractToolTarget:
    def test_file_write(self):
        args = json.dumps({"filePath": "/src/app.py"})
        assert extract_tool_target("replace_string_in_file", args) == "/src/app.py"

    def test_shell_command(self):
        args = json.dumps({"command": "npm run build"})
        assert extract_tool_target("bash", args) == "npm"

    def test_search(self):
        args = json.dumps({"query": "find bugs"})
        assert extract_tool_target("grep_search", args) == "find bugs"

    def test_browser(self):
        args = json.dumps({"url": "https://example.com"})
        assert extract_tool_target("fetch_webpage", args) == "https://example.com"

    def test_no_args(self):
        assert extract_tool_target("bash", None) == ""


# ---------------------------------------------------------------------------
# extract_file_paths
# ---------------------------------------------------------------------------


class TestExtractFilePaths:
    def test_single_path(self):
        args = json.dumps({"filePath": "/src/app.py"})
        assert extract_file_paths("edit_file", args) == ["/src/app.py"]

    def test_multiple_keys(self):
        args = json.dumps({"path": "/a.py", "filePath": "/b.py"})
        paths = extract_file_paths("edit_file", args)
        assert "/a.py" in paths
        assert "/b.py" in paths

    def test_no_args(self):
        assert extract_file_paths("bash", None) == []
