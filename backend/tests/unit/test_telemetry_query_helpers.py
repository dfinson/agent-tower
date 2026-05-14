"""Tests for backend.services.telemetry_query_service — pure helper functions."""

from __future__ import annotations

import json

from backend.services.telemetry_query_service import (
    _SHELL_TOOL_NAMES,
    _refine_tool_category,
    _shell_display_name,
)

# ── _shell_display_name ──


class TestShellDisplayName:
    def test_no_args(self):
        assert _shell_display_name("bash", None) == "bash"

    def test_empty_args(self):
        assert _shell_display_name("bash", "") == "bash"

    def test_invalid_json(self):
        assert _shell_display_name("bash", "not json") == "bash"

    def test_simple_command(self):
        args = json.dumps({"command": "pytest"})
        assert _shell_display_name("Bash", args) == "pytest"

    def test_compound_git_command(self):
        args = json.dumps({"command": "git commit -m 'fix'"})
        assert _shell_display_name("bash", args) == "git commit"

    def test_compound_npm_command(self):
        args = json.dumps({"command": "npm install lodash"})
        assert _shell_display_name("bash", args) == "npm install"

    def test_compound_uv_command(self):
        args = json.dumps({"command": "uv run pytest"})
        assert _shell_display_name("bash", args) == "uv run"

    def test_compound_docker_command(self):
        args = json.dumps({"command": "docker build ."})
        assert _shell_display_name("bash", args) == "docker build"

    def test_compound_cargo_command(self):
        args = json.dumps({"command": "cargo test"})
        assert _shell_display_name("bash", args) == "cargo test"

    def test_compound_kubectl_command(self):
        args = json.dumps({"command": "kubectl apply -f x.yaml"})
        assert _shell_display_name("bash", args) == "kubectl apply"

    def test_cd_prefix_stripped(self):
        args = json.dumps({"command": "cd /tmp && pytest"})
        assert _shell_display_name("bash", args) == "pytest"

    def test_env_var_skipped(self):
        args = json.dumps({"command": "FOO=bar pytest"})
        assert _shell_display_name("bash", args) == "pytest"

    def test_sudo_skipped(self):
        args = json.dumps({"command": "sudo apt-get install gcc"})
        assert _shell_display_name("bash", args) == "apt-get"

    def test_path_prefix_stripped(self):
        args = json.dumps({"command": "/usr/bin/python test.py"})
        assert _shell_display_name("bash", args) == "python"

    def test_empty_command(self):
        args = json.dumps({"command": ""})
        assert _shell_display_name("bash", args) == "bash"

    def test_cmd_key_alias(self):
        args = json.dumps({"cmd": "ls -la"})
        assert _shell_display_name("bash", args) == "ls"

    def test_npx_compound(self):
        args = json.dumps({"command": "npx tsc --build"})
        assert _shell_display_name("bash", args) == "npx tsc"

    def test_subcommand_is_flag(self):
        """When the subcommand starts with -, don't include it."""
        args = json.dumps({"command": "git --version"})
        assert _shell_display_name("bash", args) == "git"

    def test_nohup_skipped(self):
        args = json.dumps({"command": "nohup python server.py"})
        assert _shell_display_name("bash", args) == "python"


# ── _refine_tool_category ──


class TestRefineToolCategory:
    def test_non_shell_tool(self):
        assert _refine_tool_category("Read", None) == "file_read"

    def test_shell_git_read(self):
        args = json.dumps({"command": "git log --oneline"})
        result = _refine_tool_category("Bash", args)
        assert result in ("git_read", "shell")

    def test_shell_no_git(self):
        args = json.dumps({"command": "ls -la"})
        result = _refine_tool_category("Bash", args)
        assert result == "shell"


# ── Constants ──


class TestShellToolNames:
    def test_contains_bash(self):
        assert "bash" in _SHELL_TOOL_NAMES
        assert "Bash" in _SHELL_TOOL_NAMES

    def test_contains_run_in_terminal(self):
        assert "run_in_terminal" in _SHELL_TOOL_NAMES
