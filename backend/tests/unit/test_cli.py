"""Tests for CLI entry points."""

from __future__ import annotations

import signal
from types import SimpleNamespace
from unittest.mock import patch

from click.testing import CliRunner

from backend.cli import (
    _find_pids_on_port,
    _find_pids_on_port_posix,
    _find_pids_on_port_windows,
    _is_server_running,
    _stop_server,
)
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


# ---------------------------------------------------------------------------
# _find_pids_on_port
# ---------------------------------------------------------------------------


def _mk_conn(pid: int | None, port: int, status: str = "LISTEN", ip: str = "0.0.0.0") -> SimpleNamespace:
    laddr = SimpleNamespace(ip=ip, port=port) if port else None
    return SimpleNamespace(pid=pid, status=status, laddr=laddr)


class TestFindPidsOnPortDispatch:
    @patch("platform.system", return_value="Windows")
    @patch("backend.cli._find_pids_on_port_windows", return_value=[111])
    @patch("backend.cli._find_pids_on_port_posix")
    def test_dispatches_to_windows(self, mock_posix, mock_windows, _mock_sys) -> None:
        assert _find_pids_on_port(8080) == [111]
        mock_windows.assert_called_once_with(8080)
        mock_posix.assert_not_called()

    @patch("platform.system", return_value="Linux")
    @patch("backend.cli._find_pids_on_port_posix", return_value=[222])
    @patch("backend.cli._find_pids_on_port_windows")
    def test_dispatches_to_posix(self, mock_windows, mock_posix, _mock_sys) -> None:
        assert _find_pids_on_port(8080) == [222]
        mock_posix.assert_called_once_with(8080)
        mock_windows.assert_not_called()


class TestFindPidsOnPortWindows:
    @patch("psutil.net_connections")
    def test_never_invokes_lsof_or_ss(self, mock_net_connections) -> None:
        """Windows path must not shell out to POSIX-only tools."""
        mock_net_connections.return_value = [_mk_conn(pid=42, port=8080)]
        with patch("subprocess.run") as mock_run:
            pids = _find_pids_on_port_windows(8080)
        mock_run.assert_not_called()
        assert pids == [42]

    @patch("psutil.net_connections")
    def test_filters_by_port_and_listen_status(self, mock_net_connections) -> None:
        mock_net_connections.return_value = [
            _mk_conn(pid=1, port=8080, status="LISTEN"),
            _mk_conn(pid=2, port=9090, status="LISTEN"),  # different port
            _mk_conn(pid=3, port=8080, status="ESTABLISHED"),  # not listening
            _mk_conn(pid=4, port=8080, status="TIME_WAIT"),  # not listening
        ]
        assert _find_pids_on_port_windows(8080) == [1]

    @patch("psutil.net_connections")
    def test_dedupes_pids(self, mock_net_connections) -> None:
        """A process can hold multiple listening sockets (IPv4 + IPv6) on the same port."""
        mock_net_connections.return_value = [
            _mk_conn(pid=7, port=8080, ip="0.0.0.0"),
            _mk_conn(pid=7, port=8080, ip="::"),
        ]
        assert _find_pids_on_port_windows(8080) == [7]

    @patch("psutil.net_connections")
    def test_no_listener_returns_empty(self, mock_net_connections) -> None:
        mock_net_connections.return_value = []
        assert _find_pids_on_port_windows(8080) == []

    @patch("psutil.net_connections")
    def test_ignores_connections_without_pid(self, mock_net_connections) -> None:
        """Sockets we can't attribute to a PID (pid=None/0) must not be returned."""
        mock_net_connections.return_value = [
            _mk_conn(pid=None, port=8080),
            _mk_conn(pid=0, port=8080),
        ]
        assert _find_pids_on_port_windows(8080) == []

    def test_access_denied_returns_empty_without_raising(self) -> None:
        import psutil

        with patch("psutil.net_connections", side_effect=psutil.AccessDenied()):
            assert _find_pids_on_port_windows(8080) == []

    def test_os_error_returns_empty_without_raising(self) -> None:
        with patch("psutil.net_connections", side_effect=OSError("boom")):
            assert _find_pids_on_port_windows(8080) == []


class TestFindPidsOnPortPosix:
    @patch("subprocess.run")
    def test_uses_lsof_when_available(self, mock_run) -> None:
        mock_run.return_value = SimpleNamespace(returncode=0, stdout="123\n456\n")
        assert _find_pids_on_port_posix(8080) == [123, 456]

    @patch("subprocess.run")
    def test_dedupes_lsof_output(self, mock_run) -> None:
        mock_run.return_value = SimpleNamespace(returncode=0, stdout="123\n123\n")
        assert _find_pids_on_port_posix(8080) == [123]

    def test_falls_back_to_ss_when_lsof_missing(self) -> None:
        def fake_run(cmd, **_kwargs):
            if cmd[0] == "lsof":
                raise FileNotFoundError("lsof not found")
            return SimpleNamespace(returncode=0, stdout='tcp LISTEN 0 128 *:8080 *:* users:(("x",pid=789,fd=3))')

        with patch("subprocess.run", side_effect=fake_run):
            assert _find_pids_on_port_posix(8080) == [789]

    def test_no_listener_returns_empty_when_both_missing(self) -> None:
        with patch("subprocess.run", side_effect=FileNotFoundError):
            assert _find_pids_on_port_posix(8080) == []

    def test_genuine_ss_error_does_not_raise(self) -> None:
        """A real (non-missing-command) failure should be swallowed, not propagated."""

        def fake_run(cmd, **_kwargs):
            if cmd[0] == "lsof":
                raise FileNotFoundError("lsof not found")
            raise OSError("permission denied")

        with patch("subprocess.run", side_effect=fake_run):
            assert _find_pids_on_port_posix(8080) == []


# ---------------------------------------------------------------------------
# _is_server_running
# ---------------------------------------------------------------------------


class TestIsServerRunning:
    @patch("backend.cli._api_get", return_value=(200, {}))
    @patch("backend.cli._find_pids_on_port", return_value=[42])
    def test_health_reachable_is_running(self, _mock_pids, _mock_api) -> None:
        running, pids = _is_server_running("127.0.0.1", 8080)
        assert running is True
        assert pids == [42]

    @patch("backend.cli._api_get", return_value=(0, None))
    @patch("backend.cli._find_pids_on_port", return_value=[99])
    def test_real_listener_without_health_is_running(self, _mock_pids, _mock_api) -> None:
        """A real port listener alone (health unreachable) is still "running"."""
        running, pids = _is_server_running("127.0.0.1", 8080)
        assert running is True
        assert pids == [99]

    @patch("backend.cli._api_get", return_value=(0, None))
    @patch("backend.cli._find_pids_on_port", return_value=[])
    def test_no_listener_and_no_health_is_not_running(self, _mock_pids, _mock_api) -> None:
        """Regression: with no real listener and unreachable health, `down`/`restart`
        must report "not running" even if stale processes exist elsewhere —
        find_cpl_processes is intentionally not consulted here anymore."""
        running, pids = _is_server_running("127.0.0.1", 8080)
        assert running is False
        assert pids == []


# ---------------------------------------------------------------------------
# _stop_server
# ---------------------------------------------------------------------------


class TestStopServer:
    """`_stop_server` must only ever act on PIDs actually bound to the
    requested port. `find_cpl_processes` is a machine-wide command-line
    scan, and since `cpl down`/`cpl restart` accept an explicit `--port`,
    running multiple CodePlane instances on different ports is supported —
    so a machine-wide match must never be unioned into the kill-target list
    or the shutdown-wait condition. These tests give a different, unrelated
    instance (or a permanent self-match) a real chance to be pulled in via
    `find_cpl_processes` and assert it never is.
    """

    @patch("time.sleep", return_value=None)
    @patch("backend.services.setup.checks.find_cpl_processes")
    @patch("backend.cli._kill_process_group")
    @patch("os.kill")
    @patch("backend.cli._find_pids_on_port")
    def test_only_targets_pids_bound_to_requested_port(
        self, mock_find_pids, mock_os_kill, mock_kill_group, mock_find_cpl, _mock_sleep
    ) -> None:
        """Regression: an unrelated CodePlane instance on a different port
        (PID 200, e.g. bound to 8081) and a phantom WMIC self-match (PID
        999) must never be signalled when stopping port 8080 — and
        find_cpl_processes must not even be consulted."""
        mock_find_cpl.return_value = [200, 999]  # would-be false extra targets
        mock_find_pids.side_effect = [[100], [], []]  # initial, wait-loop check, final leftover check

        result = _stop_server(8080, timeout_seconds=5)

        assert result is True
        mock_find_cpl.assert_not_called()
        touched = {c.args[0] for c in mock_kill_group.call_args_list} | {c.args[0] for c in mock_os_kill.call_args_list}
        assert touched == {100}

    @patch("time.sleep", return_value=None)
    @patch("backend.services.setup.checks.find_cpl_processes", return_value=[999, 999, 999])
    @patch("backend.cli._kill_process_group")
    @patch("os.kill")
    @patch("backend.cli._find_pids_on_port")
    def test_wmic_self_match_cannot_extend_wait_loop_or_force_kill(
        self, mock_find_pids, _mock_os_kill, _mock_kill_group, mock_find_cpl, _mock_sleep, capsys
    ) -> None:
        """Regression: a permanently non-empty find_cpl_processes() (e.g. a
        WMIC self-match that never clears) must not keep the shutdown wait
        loop alive or trigger a false SIGKILL/force-kill message — the wait
        loop only ever consults _find_pids_on_port for the target port."""
        mock_find_pids.side_effect = [[100], [], []]

        result = _stop_server(8080, timeout_seconds=5)

        assert result is True
        mock_find_cpl.assert_not_called()
        output = capsys.readouterr().out
        assert "SIGKILL" not in output
        assert "timed out" not in output.lower()

    @patch("backend.services.setup.checks._port_is_listening", return_value=True)
    @patch("backend.cli._find_pids_on_port", return_value=[])
    def test_listener_with_unattributable_pid_fails_safely(self, _mock_find_pids, _mock_listening) -> None:
        """Regression: if something is listening on the port but no PID can
        be attributed to it (e.g. psutil.AccessDenied), this must NOT be
        silently reported as "already stopped" — nothing was verified
        stopped, and we must not widen to a machine-wide process scan to
        compensate."""
        result = _stop_server(8080)
        assert result is False

    @patch("backend.services.setup.checks._port_is_listening", return_value=False)
    @patch("backend.cli._find_pids_on_port", return_value=[])
    def test_idempotent_when_nothing_listening(self, _mock_find_pids, _mock_listening) -> None:
        """No listener at all -> cleanly report already-stopped (idempotent)."""
        result = _stop_server(8080)
        assert result is True

    @patch("time.monotonic", side_effect=[0, 0, 100])
    @patch("time.sleep", return_value=None)
    @patch("backend.cli._kill_process_group")
    @patch("os.kill")
    @patch("os.getpgid", create=True, side_effect=lambda pid: pid)
    @patch("backend.cli._find_pids_on_port")
    def test_escalates_to_sigkill_after_timeout(
        self, mock_find_pids, _mock_getpgid, _mock_os_kill, mock_kill_group, _mock_sleep, _mock_monotonic, capsys
    ) -> None:
        """Preserve existing graceful-then-force behavior for the target
        PID(s): still bound to the port after the timeout -> escalate.

        ``os.getpgid`` is stubbed (it does not exist on Windows, and on POSIX
        it would raise ``ProcessLookupError`` for the synthetic PID 100 and
        silently skip the process-group path) so both platforms exercise the
        same escalation branch. The force signal mirrors production's
        ``getattr(signal, "SIGKILL", signal.SIGTERM)`` fallback: Windows has
        no ``SIGKILL``.
        """
        mock_find_pids.side_effect = [[100], [100], [100], []]
        force_signal = getattr(signal, "SIGKILL", signal.SIGTERM)

        result = _stop_server(8080, timeout_seconds=1)

        assert result is True
        output = capsys.readouterr().out
        assert "SIGKILL" in output
        assert [c.args for c in _mock_os_kill.call_args_list] == [(100, signal.SIGTERM)]
        assert [c.args for c in mock_kill_group.call_args_list] == [
            (100, signal.SIGTERM),
            (100, force_signal),
        ]


# ---------------------------------------------------------------------------
# cpl down
# ---------------------------------------------------------------------------


class TestDown:
    def test_not_running(self) -> None:
        """down exits cleanly when nothing is running."""
        runner = CliRunner()
        with (
            patch("backend.cli._is_server_running", return_value=(False, [])),
        ):
            result = runner.invoke(cli, ["down"])
        assert result.exit_code == 0
        assert "not running" in result.output.lower()

    def test_pauses_and_stops(self) -> None:
        """down pauses sessions then stops the server."""
        runner = CliRunner()
        with (
            patch("backend.cli._is_server_running", return_value=(True, [1234])),
            patch("backend.cli._pause_active_sessions") as mock_pause,
            patch("backend.cli._stop_server", return_value=True) as mock_stop,
        ):
            result = runner.invoke(cli, ["down"])
        assert result.exit_code == 0
        mock_pause.assert_called_once()
        mock_stop.assert_called_once()

    def test_force_skips_pause(self) -> None:
        """down --force skips session pausing."""
        runner = CliRunner()
        with (
            patch("backend.cli._is_server_running", return_value=(True, [1234])),
            patch("backend.cli._pause_active_sessions") as mock_pause,
            patch("backend.cli._stop_server", return_value=True),
        ):
            result = runner.invoke(cli, ["down", "--force"])
        assert result.exit_code == 0
        mock_pause.assert_not_called()


# ---------------------------------------------------------------------------
# cpl restart
# ---------------------------------------------------------------------------


class TestRestart:
    def test_no_running_instance_execs_up(self) -> None:
        """restart with no running instance goes straight to exec."""
        runner = CliRunner()
        with (
            patch("backend.cli._is_server_running", return_value=(False, [])),
            patch("os.execv") as mock_exec,
        ):
            result = runner.invoke(cli, ["restart"])
        assert "starting fresh" in result.output.lower()
        mock_exec.assert_called_once()

    def test_stops_then_execs_up(self) -> None:
        """restart stops an existing instance then execs up."""
        runner = CliRunner()
        with (
            patch("backend.cli._is_server_running", return_value=(True, [5678])),
            patch("backend.cli._pause_active_sessions"),
            patch("backend.cli._stop_server", return_value=True),
            patch("os.execv") as mock_exec,
        ):
            result = runner.invoke(cli, ["restart"])
        assert result.exit_code == 0
        mock_exec.assert_called_once()
        # The exec args should contain "up"
        args = mock_exec.call_args[0][1]
        assert "up" in args

    def test_remote_flag_forwarded(self) -> None:
        """restart --remote forwards the flag to cpl up."""
        runner = CliRunner()
        with (
            patch("backend.cli._is_server_running", return_value=(False, [])),
            patch("os.execv") as mock_exec,
        ):
            result = runner.invoke(cli, ["restart", "--remote"])  # noqa: F841
        args = mock_exec.call_args[0][1]
        assert "--remote" in args


# ---------------------------------------------------------------------------
# cpl up — active launch profile publication (Story 1.1)
# ---------------------------------------------------------------------------


async def _fake_startup(self: object, sockets: list[object] | None = None) -> None:
    """Stand-in for ``uvicorn.Server.startup`` that skips real socket
    binding and lifespan startup but still sets ``self.started`` so
    ``_LaunchProfileServer.startup`` proceeds to publish."""
    self.started = True  # type: ignore[attr-defined]


def _fake_server_run(self: object, sockets: list[object] | None = None) -> None:
    """Stand-in for ``uvicorn.Server.run`` that drives startup synchronously
    instead of entering the real (blocking) serve loop.

    Mirrors the real ``uvicorn.Server.run(self, sockets=None)`` signature and
    forwards ``sockets`` on to ``startup`` exactly as uvicorn does, so that
    callers passing pre-bound sockets (``cpl up --port 0``) are exercised
    rather than rejected with a ``TypeError``.
    """
    import asyncio

    asyncio.run(self.startup(sockets=sockets))  # type: ignore[attr-defined]


def _invoke_up(args: list[str], *, owning_pids: list[int] | None = None) -> tuple[object, dict[str, object] | None]:
    """Invoke ``cpl up <args>`` with all real side effects (frontend build,
    migrations, dashboard, logging, actual Uvicorn socket binding) stubbed
    out, returning the CliRunner result and the profile dict written via
    ``write_active_launch_profile`` (``None`` if it was never called).

    ``owning_pids`` overrides the listener-owner check consulted during
    publication; defaults to the current process (the happy path)."""
    import os

    from backend.services.dev_restart import launch_profile as launch_profile_module

    written: dict[str, object] | None = None
    real_write = launch_profile_module.write_active_launch_profile
    resolved_owning_pids = owning_pids if owning_pids is not None else [os.getpid()]

    def _capture_write(profile: object) -> None:
        nonlocal written
        written = profile.to_dict()  # type: ignore[attr-defined]
        real_write(profile)

    runner = CliRunner()
    fake_app = SimpleNamespace(state=SimpleNamespace())
    with (
        patch("backend.services.setup.service.validate_preflight", return_value=True),
        patch("backend.cli._build_frontend", return_value=True),
        patch("backend.console_dashboard.ConsoleLog.create_if_tty", return_value=None),
        patch("backend.logging_config.setup_logging"),
        patch("backend.persistence.database.run_migrations"),
        patch("backend.app_factory.create_app", return_value=fake_app),
        patch("backend.cli._find_pids_on_port", return_value=resolved_owning_pids),
        patch("backend.services.sharing.tunnel_service.validate_remote_provider", return_value=None),
        patch("uvicorn.Server.startup", new=_fake_startup),
        patch("uvicorn.Server.run", new=_fake_server_run),
        patch(
            "backend.services.dev_restart.launch_profile.write_active_launch_profile",
            side_effect=_capture_write,
        ),
    ):
        result = runner.invoke(cli, ["up", *args])
    return result, written


class TestUpLaunchProfilePublication:
    def test_local_mode_no_password(self, tmp_path: object) -> None:
        with patch("backend.config.get_codeplane_dir", return_value=tmp_path):
            result, written = _invoke_up(["--no-password"])
        assert result.exit_code == 0, result.output
        assert written is not None
        assert written["remote"] is False
        assert written["provider"] == "local"
        assert written["tunnelOwnership"] is None
        assert written["passwordSource"] == {"kind": "not_required"}
        assert written["tunnelCredentialSource"] == {"kind": "not_required"}

    def test_literal_password_is_unreplayable(self, tmp_path: object) -> None:
        with patch("backend.config.get_codeplane_dir", return_value=tmp_path):
            result, written = _invoke_up(["--password", "literal-secret-do-not-leak"])
        assert result.exit_code == 0, result.output
        assert written is not None
        assert written["passwordSource"] == {"kind": "unreplayable"}
        assert "literal-secret-do-not-leak" not in result.output
        assert "literal-secret-do-not-leak" not in str(written)

    def test_env_password_is_resolvable(self, tmp_path: object) -> None:
        with (
            patch("backend.config.get_codeplane_dir", return_value=tmp_path),
            patch.dict("os.environ", {"CPL_PASSWORD": "env-secret-do-not-leak"}),
        ):
            result, written = _invoke_up([])
        assert result.exit_code == 0, result.output
        assert written is not None
        assert written["passwordSource"] == {
            "kind": "resolvable",
            "provider": "environment",
            "reference": "CPL_PASSWORD",
        }
        assert "env-secret-do-not-leak" not in result.output
        assert "env-secret-do-not-leak" not in str(written)

    def test_remote_devtunnel_credential_and_password_are_classified(self, tmp_path: object) -> None:
        from backend.services.sharing.tunnel_service import RemoteProvider, TunnelHandle

        fake_handle = TunnelHandle(
            provider=RemoteProvider.devtunnel,
            origin="https://example.devtunnels.ms",
            externally_managed=False,
            name="cpl-tunnel-abc",
            # An explicitly named tunnel identity is stable across a restart.
            origin_is_reusable=True,
        )
        with (
            patch("backend.config.get_codeplane_dir", return_value=tmp_path),
            patch("backend.services.sharing.tunnel_service.start_remote_access", return_value=fake_handle),
        ):
            result, written = _invoke_up(["--remote", "--provider", "devtunnel"])
        assert result.exit_code == 0, result.output
        assert written is not None
        assert written["remote"] is True
        assert written["provider"] == "devtunnel"
        assert written["tunnelOwnership"] == "managed"
        assert written["tunnelName"] == "cpl-tunnel-abc"
        assert written["tunnelOrigin"] == "https://example.devtunnels.ms"
        assert written["tunnelOriginReusable"] is True
        assert written["passwordSource"] == {"kind": "unreplayable"}
        assert written["tunnelCredentialSource"] == {
            "kind": "resolvable",
            "provider": "provider-login",
            "reference": "devtunnel",
        }

    def test_remote_cloudflare_access_disables_password_source(self, tmp_path: object) -> None:
        from backend.services.sharing.tunnel_service import RemoteProvider, TunnelHandle

        fake_handle = TunnelHandle(
            provider=RemoteProvider.cloudflare,
            origin="https://cpl.example.com",
            externally_managed=False,
            name="cpl.example.com",
        )
        with (
            patch("backend.config.get_codeplane_dir", return_value=tmp_path),
            patch("backend.services.sharing.tunnel_service.start_remote_access", return_value=fake_handle),
            patch.dict(
                "os.environ",
                {
                    "CPL_CLOUDFLARE_TUNNEL_TOKEN": "cf-token-do-not-leak",
                    "CPL_CLOUDFLARE_HOSTNAME": "cpl.example.com",
                },
            ),
        ):
            result, written = _invoke_up(["--remote", "--provider", "cloudflare"])
        assert result.exit_code == 0, result.output
        assert written is not None
        assert written["remote"] is True
        assert written["provider"] == "cloudflare"
        assert written["tunnelOwnership"] == "managed"
        assert written["passwordSource"] == {"kind": "not_required"}
        assert written["tunnelCredentialSource"] == {
            "kind": "resolvable",
            "provider": "environment",
            "reference": "CPL_CLOUDFLARE_TUNNEL_TOKEN",
        }
        assert "cf-token-do-not-leak" not in result.output
        assert "cf-token-do-not-leak" not in str(written)

    def test_externally_managed_tunnel_credential_not_required(self, tmp_path: object) -> None:
        from backend.services.sharing.tunnel_service import RemoteProvider, TunnelHandle

        fake_handle = TunnelHandle(
            provider=RemoteProvider.devtunnel,
            origin="https://already-running.devtunnels.ms",
            externally_managed=True,
            name="already-running",
        )
        with (
            patch("backend.config.get_codeplane_dir", return_value=tmp_path),
            patch("backend.services.sharing.tunnel_service.start_remote_access", return_value=fake_handle),
        ):
            result, written = _invoke_up(["--remote", "--provider", "devtunnel"])
        assert result.exit_code == 0, result.output
        assert written is not None
        assert written["tunnelOwnership"] == "external"
        assert written["tunnelCredentialSource"] == {"kind": "not_required"}

    def test_tunnel_ownership_flag_propagates_managed_explicitly(self, tmp_path: object) -> None:
        """``--tunnel-ownership managed`` (as replayed by restart, AD-8) must reach
        ``start_remote_access`` as an explicit ``TunnelOwnership.managed`` value,
        never left as the implicit ``None`` legacy auto-detect default."""
        from backend.services.sharing.tunnel_service import RemoteProvider, TunnelHandle, TunnelOwnership

        fake_handle = TunnelHandle(
            provider=RemoteProvider.devtunnel,
            origin="https://example.devtunnels.ms",
            externally_managed=False,
            name="cpl-tunnel-abc",
        )
        with (
            patch("backend.config.get_codeplane_dir", return_value=tmp_path),
            patch(
                "backend.services.sharing.tunnel_service.start_remote_access", return_value=fake_handle
            ) as mock_start,
        ):
            result, written = _invoke_up(["--remote", "--provider", "devtunnel", "--tunnel-ownership", "managed"])
        assert result.exit_code == 0, result.output
        assert mock_start.call_args.kwargs["ownership"] is TunnelOwnership.managed

    def test_tunnel_ownership_flag_propagates_external_explicitly(self, tmp_path: object) -> None:
        """``--tunnel-ownership external`` must reach ``start_remote_access`` as an
        explicit ``TunnelOwnership.external`` value so no connector is scanned
        for or spawned — only the recorded origin is resolved (AD-8)."""
        from backend.services.sharing.tunnel_service import RemoteProvider, TunnelHandle, TunnelOwnership

        fake_handle = TunnelHandle(
            provider=RemoteProvider.devtunnel,
            origin="https://already-running.devtunnels.ms",
            externally_managed=True,
            name="already-running",
        )
        with (
            patch("backend.config.get_codeplane_dir", return_value=tmp_path),
            patch(
                "backend.services.sharing.tunnel_service.start_remote_access", return_value=fake_handle
            ) as mock_start,
        ):
            result, written = _invoke_up(["--remote", "--provider", "devtunnel", "--tunnel-ownership", "external"])
        assert result.exit_code == 0, result.output
        assert mock_start.call_args.kwargs["ownership"] is TunnelOwnership.external

    def test_tunnel_ownership_omitted_preserves_legacy_autodetect(self, tmp_path: object) -> None:
        """When ``--tunnel-ownership`` is not passed (a normal manual ``cpl up``,
        not a restart replay), ``ownership`` stays ``None`` so the pre-existing
        auto-detect behavior is unchanged for callers that have not opted in."""
        from backend.services.sharing.tunnel_service import RemoteProvider, TunnelHandle

        fake_handle = TunnelHandle(
            provider=RemoteProvider.devtunnel,
            origin="https://example.devtunnels.ms",
            externally_managed=False,
            name="cpl-tunnel-abc",
        )
        with (
            patch("backend.config.get_codeplane_dir", return_value=tmp_path),
            patch(
                "backend.services.sharing.tunnel_service.start_remote_access", return_value=fake_handle
            ) as mock_start,
        ):
            result, written = _invoke_up(["--remote", "--provider", "devtunnel"])
        assert result.exit_code == 0, result.output
        assert mock_start.call_args.kwargs["ownership"] is None

    def test_zero_bind_host_autogenerates_unreplayable_password(self, tmp_path: object) -> None:
        with patch("backend.config.get_codeplane_dir", return_value=tmp_path):
            result, written = _invoke_up(["--host", "0.0.0.0"])
        assert result.exit_code == 0, result.output
        assert written is not None
        assert written["host"] == "0.0.0.0"
        assert written["passwordSource"] == {"kind": "unreplayable"}

    def test_publication_failure_when_pid_does_not_own_port(self, tmp_path: object) -> None:
        """If the ownership check fails, publication must raise and startup
        must not silently continue -- exercised directly via a failing
        ``_find_pids_on_port`` override layered on top of the base patch set."""
        with patch("backend.config.get_codeplane_dir", return_value=tmp_path):
            result, written = _invoke_up(["--no-password"], owning_pids=[999999])
        assert result.exit_code != 0
        assert written is None
