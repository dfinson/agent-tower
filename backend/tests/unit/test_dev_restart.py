"""Tests for the frontend build path in tools/dev_restart.py."""

from __future__ import annotations

from subprocess import CompletedProcess
from unittest.mock import patch

import pytest

from tools import dev_restart


def test_resolve_npm_command_uses_npm_cmd_on_windows() -> None:
    npm_path = r"C:\Program Files\nodejs\npm.cmd"

    with (
        patch("tools.dev_restart.platform.system", return_value="Windows"),
        patch("tools.dev_restart.shutil.which", return_value=npm_path) as mock_which,
    ):
        assert dev_restart._resolve_npm_command() == npm_path

    mock_which.assert_called_once_with("npm.cmd")


def test_resolve_npm_command_uses_npm_on_posix() -> None:
    npm_path = "/usr/local/bin/npm"

    with (
        patch("tools.dev_restart.platform.system", return_value="Linux"),
        patch("tools.dev_restart.shutil.which", return_value=npm_path) as mock_which,
    ):
        assert dev_restart._resolve_npm_command() == npm_path

    mock_which.assert_called_once_with("npm")


def test_resolve_npm_command_reports_missing_executable() -> None:
    with (
        patch("tools.dev_restart.platform.system", return_value="Windows"),
        patch("tools.dev_restart.shutil.which", return_value=None),
        pytest.raises(FileNotFoundError, match=r"'npm\.cmd' was not found on PATH"),
    ):
        dev_restart._resolve_npm_command()


def test_build_frontend_invokes_resolved_npm_and_streams_output() -> None:
    npm_path = r"C:\Program Files\nodejs\npm.cmd"

    with (
        patch("tools.dev_restart._resolve_npm_command", return_value=npm_path),
        patch(
            "tools.dev_restart.subprocess.run",
            return_value=CompletedProcess([npm_path, "run", "build"], returncode=0),
        ) as mock_run,
    ):
        assert dev_restart.build_frontend() is True

    mock_run.assert_called_once_with([npm_path, "run", "build"], cwd=dev_restart.FRONTEND_DIR)


def test_build_frontend_preserves_failed_build_result() -> None:
    npm_path = "/usr/local/bin/npm"

    with (
        patch("tools.dev_restart._resolve_npm_command", return_value=npm_path),
        patch(
            "tools.dev_restart.subprocess.run",
            return_value=CompletedProcess([npm_path, "run", "build"], returncode=1),
        ),
    ):
        assert dev_restart.build_frontend() is False
