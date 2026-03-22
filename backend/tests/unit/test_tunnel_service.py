from __future__ import annotations

import threading
from unittest.mock import patch

from backend.services.tunnel_service import RemoteProvider, TunnelWatchdog, validate_remote_provider


class _FakeProc:
    def __init__(self, *, poll_result: int | None = None, output: str = "") -> None:
        self._poll_result = poll_result
        self.stdout = _FakeStdout(output)
        self.terminated = False
        self.killed = False

    def poll(self) -> int | None:
        return self._poll_result

    def terminate(self) -> None:
        self.terminated = True

    def wait(self, timeout: int) -> int | None:
        return self._poll_result

    def kill(self) -> None:
        self.killed = True


class _FakeStdout:
    def __init__(self, output: str) -> None:
        self.output = output

    def read(self) -> str:
        return self.output


def test_validate_remote_provider_local_has_no_requirements() -> None:
    assert validate_remote_provider(RemoteProvider.local) is None


@patch("backend.services.tunnel_service.shutil.which", return_value=None)
def test_validate_remote_provider_devtunnel_requires_cli(mock_which) -> None:
    error = validate_remote_provider(RemoteProvider.devtunnel)
    assert error is not None
    assert "devtunnel" in error.lower()


@patch("backend.services.tunnel_service.shutil.which", return_value="/usr/bin/cloudflared")
def test_validate_remote_provider_cloudflare_requires_token_and_hostname(mock_which) -> None:
    error = validate_remote_provider(RemoteProvider.cloudflare)
    assert error is not None
    assert "CPL_CLOUDFLARE_HOSTNAME" in error
    assert "CPL_CLOUDFLARE_TUNNEL_TOKEN" in error


@patch("backend.services.tunnel_service.shutil.which", return_value="/usr/bin/cloudflared")
def test_validate_remote_provider_cloudflare_with_config_passes(mock_which) -> None:
    error = validate_remote_provider(
        RemoteProvider.cloudflare,
        cloudflare_hostname="codeplane.example.com",
        cloudflare_token="token",
    )
    assert error is None


def test_watchdog_detects_dead_process() -> None:
    watchdog = TunnelWatchdog(
        tunnel_url="https://example.test",
        restart_command=["devtunnel", "host", "name"],
        proc=_FakeProc(poll_result=1),
        label="devtunnel",
    )
    assert watchdog._process_running() is False


def test_watchdog_restart_process_retries_until_healthy() -> None:
    original_proc = _FakeProc(poll_result=None)
    failed_proc = _FakeProc(poll_result=1, output="transient failure")
    recovered_proc = _FakeProc(poll_result=None)
    watchdog = TunnelWatchdog(
        tunnel_url="https://example.test",
        restart_command=["devtunnel", "host", "name"],
        proc=original_proc,
        label="devtunnel",
    )
    watchdog._stop_event = threading.Event()

    with (
        patch("backend.services.tunnel_service.subprocess.Popen", side_effect=[failed_proc, recovered_proc]),
        patch.object(watchdog, "_wait_for_recovery", side_effect=[True]),
    ):
        restarted = watchdog._restart_process()

    assert restarted is True
    assert original_proc.terminated is True
    assert watchdog.proc is recovered_proc


def test_watchdog_restart_process_gives_up_after_retries() -> None:
    watchdog = TunnelWatchdog(
        tunnel_url="https://example.test",
        restart_command=["devtunnel", "host", "name"],
        proc=_FakeProc(poll_result=None),
        label="devtunnel",
    )
    watchdog._stop_event = threading.Event()
    failed_procs = [_FakeProc(poll_result=1, output=f"failure {index}") for index in range(3)]

    with patch("backend.services.tunnel_service.subprocess.Popen", side_effect=failed_procs):
        restarted = watchdog._restart_process()

    assert restarted is False
    assert watchdog.proc is failed_procs[-1]
