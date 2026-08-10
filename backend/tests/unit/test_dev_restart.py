"""Tests for tools/dev_restart.py: frontend build, target-source resolution,
secret re-resolution, backend preflight, pending-request write, parent/helper
importability when run as a script, and the Story 1.2 parent-mode
preparation/handoff flow.
"""

from __future__ import annotations

import argparse
import importlib
import sys
from subprocess import CompletedProcess
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from backend.services.dev_restart.launch_profile import SecretSource, build_active_launch_profile
from backend.services.dev_restart.restart_protocol import RestartProtocolError, RestartTimeouts, get_request_paths
from tools import dev_restart

if TYPE_CHECKING:
    from pathlib import Path


def _profile(**overrides: object) -> object:
    defaults: dict[str, object] = dict(
        executable="/usr/bin/python3",
        working_directory="/home/dev/codeplane",
        host="127.0.0.1",
        port=8080,
        dev=False,
        remote=False,
        provider="local",
        tunnel_ownership=None,
        tunnel_name=None,
        password_source=SecretSource.not_required(),
        tunnel_credential_source=SecretSource.not_required(),
        started_pid=4242,
        started_process_time=1_700_000_000.5,
    )
    defaults.update(overrides)
    return build_active_launch_profile(**defaults)  # type: ignore[arg-type]


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
        patch("pathlib.Path.is_dir", return_value=True),
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
        patch("pathlib.Path.is_dir", return_value=True),
        patch(
            "tools.dev_restart.subprocess.run",
            return_value=CompletedProcess([npm_path, "run", "build"], returncode=1),
        ),
    ):
        assert dev_restart.build_frontend() is False


def test_build_frontend_installs_dependencies_when_node_modules_missing(tmp_path: Path) -> None:
    npm_path = r"C:\Program Files\nodejs\npm.cmd"
    results = [
        CompletedProcess([npm_path, "ci"], returncode=0),
        CompletedProcess([npm_path, "run", "build"], returncode=0),
    ]

    with (
        patch("tools.dev_restart._resolve_npm_command", return_value=npm_path),
        patch("tools.dev_restart.subprocess.run", side_effect=results) as mock_run,
    ):
        assert dev_restart.build_frontend(tmp_path) is True

    install_args, build_args = (call.args[0] for call in mock_run.call_args_list)
    assert install_args == [npm_path, "ci"]
    assert build_args == [npm_path, "run", "build"]


def test_build_frontend_aborts_when_dependency_install_fails(tmp_path: Path) -> None:
    npm_path = r"C:\Program Files\nodejs\npm.cmd"

    with (
        patch("tools.dev_restart._resolve_npm_command", return_value=npm_path),
        patch(
            "tools.dev_restart.subprocess.run",
            return_value=CompletedProcess([npm_path, "ci"], returncode=1),
        ) as mock_run,
    ):
        assert dev_restart.build_frontend(tmp_path) is False

    mock_run.assert_called_once_with([npm_path, "ci"], cwd=tmp_path)


def test_import_inserts_repo_root_for_direct_script_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "path", [str(dev_restart.REPO_ROOT / "tools")])

    importlib.reload(dev_restart)

    assert sys.path[0] == str(dev_restart.REPO_ROOT)


# ---------------------------------------------------------------------------
# Target-source resolution (AC 1)
# ---------------------------------------------------------------------------


class TestResolveTargetSourceRoot:
    def test_defaults_to_repo_root_when_no_source_given(self) -> None:
        assert dev_restart.resolve_target_source_root(None) == dev_restart.REPO_ROOT

    def test_resolves_explicit_valid_checkout(self, tmp_path: Path) -> None:
        (tmp_path / "backend").mkdir()
        (tmp_path / "backend" / "app_factory.py").write_text("")
        (tmp_path / "pyproject.toml").write_text("")

        assert dev_restart.resolve_target_source_root(str(tmp_path)) == tmp_path.resolve()

    def test_rejects_directory_missing_checkout_markers(self, tmp_path: Path) -> None:
        with pytest.raises(dev_restart.DevRestartError, match="does not look like a CodePlane checkout"):
            dev_restart.resolve_target_source_root(str(tmp_path))


# ---------------------------------------------------------------------------
# Secret re-resolution (AC 4) — never serializes or logs a secret value
# ---------------------------------------------------------------------------


class TestEnsureSecretResolvable:
    def test_not_required_is_a_noop(self, tmp_path: Path) -> None:
        dev_restart.ensure_secret_resolvable(SecretSource.not_required(), tmp_path, label="x")

    def test_unreplayable_always_raises(self, tmp_path: Path) -> None:
        with pytest.raises(dev_restart.DevRestartError, match="not replayable"):
            dev_restart.ensure_secret_resolvable(SecretSource.unreplayable(), tmp_path, label="password source")

    def test_environment_source_resolves_from_target_dotenv(self, tmp_path: Path) -> None:
        (tmp_path / ".env").write_text("CPL_PASSWORD=hunter2\n")
        source = SecretSource.resolvable("environment", "CPL_PASSWORD")

        dev_restart.ensure_secret_resolvable(source, tmp_path, label="password source")

    def test_environment_source_resolves_from_process_environment(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CPL_PASSWORD", "hunter2")
        source = SecretSource.resolvable("environment", "CPL_PASSWORD")

        dev_restart.ensure_secret_resolvable(source, tmp_path, label="password source")

    def test_environment_source_raises_when_unresolvable(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CPL_PASSWORD", raising=False)
        source = SecretSource.resolvable("environment", "CPL_PASSWORD")

        with pytest.raises(dev_restart.DevRestartError, match="CPL_PASSWORD"):
            dev_restart.ensure_secret_resolvable(source, tmp_path, label="password source")

    def test_provider_login_source_resolves_when_cli_present(self, tmp_path: Path) -> None:
        source = SecretSource.resolvable("provider-login", "devtunnel")

        with patch("tools.dev_restart.shutil.which", return_value="/usr/bin/devtunnel"):
            dev_restart.ensure_secret_resolvable(source, tmp_path, label="tunnel credential source")

    def test_provider_login_source_raises_when_cli_missing(self, tmp_path: Path) -> None:
        source = SecretSource.resolvable("provider-login", "devtunnel")

        with (
            patch("tools.dev_restart.shutil.which", return_value=None),
            pytest.raises(dev_restart.DevRestartError, match="devtunnel"),
        ):
            dev_restart.ensure_secret_resolvable(source, tmp_path, label="tunnel credential source")

    def test_unrecognized_provider_raises(self, tmp_path: Path) -> None:
        source = SecretSource(kind="resolvable", provider="mystery", reference="x")

        with pytest.raises(dev_restart.DevRestartError, match="unrecognized provider"):
            dev_restart.ensure_secret_resolvable(source, tmp_path, label="tunnel credential source")

    def test_secret_value_never_appears_in_raised_error(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CPL_PASSWORD", raising=False)
        source = SecretSource.resolvable("environment", "CPL_PASSWORD")

        with pytest.raises(dev_restart.DevRestartError) as exc_info:
            dev_restart.ensure_secret_resolvable(source, tmp_path, label="password source")

        # Only the reference name may appear -- never a would-be secret value.
        assert "CPL_PASSWORD" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Backend compile/import preflight (AC 3)
# ---------------------------------------------------------------------------


class TestRunBackendPreflight:
    def test_success_runs_compileall_then_import(self, tmp_path: Path) -> None:
        with patch(
            "tools.dev_restart.subprocess.run",
            return_value=CompletedProcess([], returncode=0, stdout="", stderr=""),
        ) as mock_run:
            dev_restart.run_backend_preflight("/usr/bin/python3", tmp_path)

        assert mock_run.call_count == 2
        compile_args, import_args = (call.args[0] for call in mock_run.call_args_list)
        assert compile_args == ["/usr/bin/python3", "-m", "compileall", "-q", "backend", "tools"]
        assert import_args == ["/usr/bin/python3", "-c", "import backend.app_factory"]
        for call in mock_run.call_args_list:
            assert call.kwargs["cwd"] == str(tmp_path)

    def test_compileall_failure_raises_without_importing(self, tmp_path: Path) -> None:
        with (
            patch(
                "tools.dev_restart.subprocess.run",
                return_value=CompletedProcess([], returncode=1, stdout="SyntaxError", stderr=""),
            ) as mock_run,
            pytest.raises(dev_restart.DevRestartError, match="compileall"),
        ):
            dev_restart.run_backend_preflight("/usr/bin/python3", tmp_path)

        mock_run.assert_called_once()

    def test_import_failure_raises(self, tmp_path: Path) -> None:
        results = [
            CompletedProcess([], returncode=0, stdout="", stderr=""),
            CompletedProcess([], returncode=1, stdout="", stderr="ModuleNotFoundError"),
        ]
        with (
            patch("tools.dev_restart.subprocess.run", side_effect=results),
            pytest.raises(dev_restart.DevRestartError, match="import backend.app_factory"),
        ):
            dev_restart.run_backend_preflight("/usr/bin/python3", tmp_path)


# ---------------------------------------------------------------------------
# Pending-request write (AC 5)
# ---------------------------------------------------------------------------


class TestWritePendingRequest:
    def test_writes_secret_free_wire_contract(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CODEPLANE_HOME", str(tmp_path))
        import backend.config as config_module

        monkeypatch.setattr(config_module, "_codeplane_dir", None)

        profile = _profile(
            password_source=SecretSource.resolvable("environment", "CPL_PASSWORD"),
        )
        timeouts = RestartTimeouts()

        paths = dev_restart.write_pending_request("req-123", tmp_path / "target", profile, timeouts)

        assert paths == get_request_paths("req-123")
        import json

        payload = json.loads(paths.pending.read_text(encoding="utf-8"))
        assert payload["requestId"] == "req-123"
        assert payload["targetSourceRoot"] == str(tmp_path / "target")
        assert payload["timeouts"] == timeouts.to_dict()
        assert payload["launchProfile"] == profile.to_dict()
        assert "CPL_PASSWORD" in json.dumps(payload["launchProfile"])  # reference name only
        # SecretSource is a closed union of kind/provider/reference -- there is
        # no field a literal secret value could ever occupy, so asserting the
        # reference is present (not a value) is the strongest secret-free check.


# ---------------------------------------------------------------------------
# Parent-mode preparation ordering (AC 2, 3, 5, 6)
# ---------------------------------------------------------------------------


class TestPrepareRestartRequest:
    def _args(self, **overrides: object) -> argparse.Namespace:
        defaults = dict(
            source=None,
            adoption_seconds=None,
            response_grace_seconds=None,
            pause_wait_seconds=None,
            stop_seconds=None,
            readiness_seconds=None,
            remote_probe_seconds=None,
        )
        defaults.update(overrides)
        return argparse.Namespace(**defaults)

    def test_runs_build_then_preflight_then_write_in_order(self, tmp_path: Path) -> None:
        profile = _profile()
        call_order: list[str] = []

        def _record_build(*args: object, **kwargs: object) -> bool:
            call_order.append("build")
            return True

        def _record_preflight(*args: object, **kwargs: object) -> None:
            call_order.append("preflight")

        def _record_write(*args: object, **kwargs: object) -> MagicMock:
            call_order.append("write")
            return MagicMock()

        with (
            patch("tools.dev_restart.resolve_target_source_root", return_value=tmp_path),
            patch("backend.services.dev_restart.launch_profile.load_active_profile", return_value=profile),
            patch("backend.services.dev_restart.launch_profile.validate_launch_profile"),
            patch("tools.dev_restart.ensure_secret_resolvable"),
            patch("tools.dev_restart.build_frontend", side_effect=_record_build),
            patch("tools.dev_restart.run_backend_preflight", side_effect=_record_preflight),
            patch("tools.dev_restart.write_pending_request", side_effect=_record_write),
        ):
            dev_restart.prepare_restart_request(self._args())

        assert call_order == ["build", "preflight", "write"]

    def test_build_failure_aborts_before_preflight_or_write(self, tmp_path: Path) -> None:
        profile = _profile()

        with (
            patch("tools.dev_restart.resolve_target_source_root", return_value=tmp_path),
            patch("backend.services.dev_restart.launch_profile.load_active_profile", return_value=profile),
            patch("backend.services.dev_restart.launch_profile.validate_launch_profile"),
            patch("tools.dev_restart.ensure_secret_resolvable"),
            patch("tools.dev_restart.build_frontend", return_value=False),
            patch("tools.dev_restart.run_backend_preflight") as mock_preflight,
            patch("tools.dev_restart.write_pending_request") as mock_write,
            pytest.raises(dev_restart.DevRestartError, match="frontend build failed"),
        ):
            dev_restart.prepare_restart_request(self._args())

        mock_preflight.assert_not_called()
        mock_write.assert_not_called()

    def test_preflight_failure_aborts_before_write(self, tmp_path: Path) -> None:
        profile = _profile()

        with (
            patch("tools.dev_restart.resolve_target_source_root", return_value=tmp_path),
            patch("backend.services.dev_restart.launch_profile.load_active_profile", return_value=profile),
            patch("backend.services.dev_restart.launch_profile.validate_launch_profile"),
            patch("tools.dev_restart.ensure_secret_resolvable"),
            patch("tools.dev_restart.build_frontend", return_value=True),
            patch(
                "tools.dev_restart.run_backend_preflight",
                side_effect=dev_restart.DevRestartError("preflight boom"),
            ),
            patch("tools.dev_restart.write_pending_request") as mock_write,
            pytest.raises(dev_restart.DevRestartError, match="preflight boom"),
        ):
            dev_restart.prepare_restart_request(self._args())

        mock_write.assert_not_called()

    def test_stale_profile_aborts_before_any_side_effect(self, tmp_path: Path) -> None:
        from backend.services.dev_restart.launch_profile import LaunchProfileStaleError

        with (
            patch("tools.dev_restart.resolve_target_source_root", return_value=tmp_path),
            patch(
                "backend.services.dev_restart.launch_profile.load_active_profile",
                side_effect=LaunchProfileStaleError("stale"),
            ),
            patch("tools.dev_restart.build_frontend") as mock_build,
            patch("tools.dev_restart.run_backend_preflight") as mock_preflight,
            patch("tools.dev_restart.write_pending_request") as mock_write,
            pytest.raises(dev_restart.DevRestartError, match="invalid or stale"),
        ):
            dev_restart.prepare_restart_request(self._args())

        mock_build.assert_not_called()
        mock_preflight.assert_not_called()
        mock_write.assert_not_called()


# ---------------------------------------------------------------------------
# Parent-mode handoff (Story 1.3 spawn/adoption call from Story 1.2's flow)
# ---------------------------------------------------------------------------


class TestRunParent:
    def _args(self) -> argparse.Namespace:
        return argparse.Namespace(
            source=None,
            adoption_seconds=None,
            response_grace_seconds=None,
            pause_wait_seconds=None,
            stop_seconds=None,
            readiness_seconds=None,
            remote_probe_seconds=None,
        )

    def test_preparation_failure_never_spawns_helper(self) -> None:
        with (
            patch(
                "tools.dev_restart.prepare_restart_request",
                side_effect=dev_restart.DevRestartError("boom"),
            ),
            patch("backend.services.dev_restart.restart_helper.spawn_detached_helper") as mock_spawn,
        ):
            assert dev_restart.run_parent(self._args()) == 1

        mock_spawn.assert_not_called()

    def test_successful_adoption_returns_zero(self, tmp_path: Path) -> None:
        paths = get_request_paths("req-abc")
        timeouts = RestartTimeouts()

        with (
            patch(
                "tools.dev_restart.prepare_restart_request",
                return_value=(paths, "req-abc", timeouts),
            ),
            patch(
                "backend.services.dev_restart.restart_protocol.get_restart_log_path",
                return_value=tmp_path / "restart.log",
            ),
            patch("backend.services.dev_restart.restart_helper.spawn_detached_helper", return_value=4321),
            patch("backend.services.dev_restart.restart_helper.await_adoption", return_value=True),
        ):
            assert dev_restart.run_parent(self._args()) == 0

    def test_adoption_timeout_returns_nonzero(self, tmp_path: Path) -> None:
        paths = get_request_paths("req-abc")
        timeouts = RestartTimeouts()

        with (
            patch(
                "tools.dev_restart.prepare_restart_request",
                return_value=(paths, "req-abc", timeouts),
            ),
            patch(
                "backend.services.dev_restart.restart_protocol.get_restart_log_path",
                return_value=tmp_path / "restart.log",
            ),
            patch("backend.services.dev_restart.restart_helper.spawn_detached_helper", return_value=4321),
            patch("backend.services.dev_restart.restart_helper.await_adoption", return_value=False),
        ):
            assert dev_restart.run_parent(self._args()) == 1

    def test_spawn_failure_returns_nonzero(self, tmp_path: Path) -> None:
        paths = get_request_paths("req-abc")
        timeouts = RestartTimeouts()

        with (
            patch(
                "tools.dev_restart.prepare_restart_request",
                return_value=(paths, "req-abc", timeouts),
            ),
            patch(
                "backend.services.dev_restart.restart_protocol.get_restart_log_path",
                return_value=tmp_path / "restart.log",
            ),
            patch(
                "backend.services.dev_restart.restart_helper.spawn_detached_helper",
                side_effect=OSError("cannot fork"),
            ),
            patch("backend.services.dev_restart.restart_helper.await_adoption") as mock_await,
        ):
            assert dev_restart.run_parent(self._args()) == 1

        mock_await.assert_not_called()

    def test_restart_log_rotation_failure_returns_nonzero_without_spawning_helper(self, tmp_path: Path) -> None:
        paths = get_request_paths("req-abc")
        timeouts = RestartTimeouts()

        with (
            patch(
                "tools.dev_restart.prepare_restart_request",
                return_value=(paths, "req-abc", timeouts),
            ),
            patch(
                "backend.services.dev_restart.restart_protocol.get_restart_log_path",
                return_value=tmp_path / "restart.log",
            ),
            patch(
                "backend.services.dev_restart.restart_protocol.rotate_restart_log_if_needed",
                side_effect=RestartProtocolError("could not rotate restart.log: file is locked"),
            ),
            patch("backend.services.dev_restart.restart_helper.spawn_detached_helper") as mock_spawn,
        ):
            assert dev_restart.run_parent(self._args()) == 1

        mock_spawn.assert_not_called()
