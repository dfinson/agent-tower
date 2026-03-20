"""Tests for CLI entry points."""

from __future__ import annotations

from click.testing import CliRunner

from backend.main import cli


def test_version_command() -> None:
    from backend import __version__

    runner = CliRunner()
    result = runner.invoke(cli, ["version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_doctor_command_runs() -> None:
    """cpl doctor runs without crashing (may fail on missing deps, which is fine)."""
    runner = CliRunner()
    result = runner.invoke(cli, ["doctor"])
    # exit 0 = all clear, exit 1 = some failures — both are valid
    assert result.exit_code in (0, 1)


def test_doctor_json_output() -> None:
    """cpl doctor --json produces valid JSON."""
    import json

    runner = CliRunner()
    result = runner.invoke(cli, ["doctor", "--json"])
    assert result.exit_code in (0, 1)
    data = json.loads(result.output)
    assert "checks" in data
    assert "passed" in data
    assert "warnings" in data
    assert "failed" in data
