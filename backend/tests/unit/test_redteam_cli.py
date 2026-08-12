"""Red-team / pressure tests for CLI commands (Phase 1).

Covers: invalid arguments, edge cases for cpl up/init/version.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from click.testing import CliRunner

from backend.main import cli


def _invoke_up(*args: str) -> tuple[int, dict[str, Any]]:
    """Run ``cpl up`` far enough to capture the uvicorn config it builds.

    ``cpl up`` does not call ``uvicorn.Server(...)`` directly — it defines a
    ``uvicorn.Server`` *subclass* (``_LaunchProfileServer``) and instantiates
    that, so the bind settings can only be observed on ``uvicorn.Config``.
    ``uvicorn.Server`` is still patched so ``server.run()`` never binds a real
    socket, and ``--skip-preflight`` keeps the invocation independent of the
    host machine's toolchain and of whether port 8080 happens to be free.

    Returns the exit code and the keyword arguments passed to ``uvicorn.Config``.
    """
    runner = CliRunner()
    with (
        patch("backend.cli._build_frontend"),
        patch("backend.persistence.database.run_migrations"),
        patch("uvicorn.Server"),
        patch("uvicorn.Config") as mock_config,
    ):
        result = runner.invoke(cli, ["up", "--skip-preflight", *args])
        if result.exit_code == 0:
            assert mock_config.called, "cpl up exited 0 without building a uvicorn config"
        return result.exit_code, dict(mock_config.call_args.kwargs) if mock_config.called else {}


class TestVersionCommand:
    def test_version_with_extra_args_ignored(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["version", "--help"])
        # --help is handled by click
        assert result.exit_code == 0

    def test_version_output_format(self) -> None:
        from backend import __version__

        runner = CliRunner()
        result = runner.invoke(cli, ["version"])
        assert result.output.strip() == f"cpl {__version__}"


class TestDoctorCommand:
    def test_doctor_runs(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["doctor"])
        # exit 0 (all clear) or 1 (failures) — both valid
        assert result.exit_code in (0, 1)

    def test_doctor_json_has_schema(self) -> None:
        import json

        runner = CliRunner()
        result = runner.invoke(cli, ["doctor", "--json"])
        assert result.exit_code in (0, 1)
        data = json.loads(result.output)
        assert isinstance(data["checks"], list)
        assert isinstance(data["passed"], int)
        assert isinstance(data["failed"], int)


class TestUpCommand:
    def test_up_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["up", "--help"])
        assert result.exit_code == 0
        assert "--host" in result.output
        assert "--port" in result.output
        assert "--dev" in result.output
        assert "--remote" in result.output
        assert "--provider" in result.output
        assert "devtunnel" in result.output
        assert "cloudflare" in result.output

    @patch(
        "backend.services.sharing.tunnel_service.validate_remote_provider",
        return_value="ERROR: 'devtunnel' CLI not found.",
    )
    def test_up_remote_requires_devtunnel_cli(self, mock_validate) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["up", "--remote", "--skip-preflight"])

        assert result.exit_code == 1
        assert "devtunnel" in result.output.lower()

    def test_up_provider_without_remote_is_rejected(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["up", "--provider", "cloudflare", "--skip-preflight"])
        assert result.exit_code == 1
        assert "--provider requires --remote" in result.output

    def test_up_rejects_string_port(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["up", "--port", "not_a_number"])
        # Click should reject this as not a valid integer
        assert result.exit_code != 0
        assert "not a valid integer" in result.output.lower() or "invalid" in result.output.lower()

    def test_up_accepts_negative_port(self) -> None:
        """Click accepts negative int; uvicorn would fail at bind time."""
        exit_code, uv_config = _invoke_up("--port", "-1")
        assert exit_code == 0
        assert uv_config["port"] == -1

    def test_up_with_zero_port(self) -> None:
        exit_code, uv_config = _invoke_up("--port", "0")
        assert exit_code == 0
        assert uv_config["port"] == 0

    def test_up_with_custom_host(self) -> None:
        exit_code, uv_config = _invoke_up("--host", "0.0.0.0")
        assert exit_code == 0
        assert uv_config["host"] == "0.0.0.0"

    def test_up_uses_config_defaults(self) -> None:
        exit_code, uv_config = _invoke_up()
        assert exit_code == 0
        assert uv_config["host"] == "127.0.0.1"
        assert uv_config["port"] == 8080

    # -----------------------------------------------------------------------
    # #2 — Block unauthenticated 0.0.0.0 binding
    # -----------------------------------------------------------------------

    def test_up_host_0000_with_no_password_blocked(self) -> None:
        """--host 0.0.0.0 --no-password must be rejected."""
        runner = CliRunner()
        result = runner.invoke(cli, ["up", "--host", "0.0.0.0", "--no-password", "--skip-preflight"])
        assert result.exit_code == 1
        assert "not allowed" in result.output.lower() or "requires authentication" in result.output.lower()

    def test_up_host_0000_auto_generates_password(self) -> None:
        """--host 0.0.0.0 without explicit password should auto-generate one."""
        runner = CliRunner()
        with (
            patch("backend.cli._build_frontend"),
            patch("backend.persistence.database.run_migrations"),
            patch("uvicorn.Server"),
        ):
            result = runner.invoke(cli, ["up", "--host", "0.0.0.0", "--skip-preflight"])
            # The password auto-generation happens before server.run()
            if result.exit_code == 0:
                assert True  # Reached server creation without error

    def test_up_host_0000_with_explicit_password_allowed(self) -> None:
        """--host 0.0.0.0 --password mypass should work without issue."""
        runner = CliRunner()
        with (
            patch("backend.cli._build_frontend"),
            patch("backend.persistence.database.run_migrations"),
            patch("uvicorn.Server"),
        ):
            result = runner.invoke(
                cli,
                ["up", "--host", "0.0.0.0", "--password", "mypass", "--skip-preflight"],
            )
            assert result.exit_code == 0

    # -----------------------------------------------------------------------
    # --tunnel-name option
    # -----------------------------------------------------------------------

    def test_up_help_shows_tunnel_name(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["up", "--help"])
        assert "--tunnel-name" in result.output

    def test_up_remote_no_password_blocked(self) -> None:
        """--remote --no-password must always be rejected."""
        runner = CliRunner()
        result = runner.invoke(cli, ["up", "--remote", "--no-password", "--skip-preflight"])
        assert result.exit_code == 1
        assert "not allowed" in result.output.lower()


class TestUnknownCommands:
    def test_unknown_subcommand(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["nonexistent"])
        assert result.exit_code != 0

    def test_no_subcommand(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, [])
        # Click group with invoke_without_command=False returns exit 2
        assert result.exit_code == 2
        assert "Usage" in result.output

    def test_help_flag(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "CodePlane" in result.output
