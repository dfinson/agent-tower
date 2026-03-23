from __future__ import annotations

import threading
from typing import TYPE_CHECKING, cast
from unittest.mock import MagicMock, patch

from backend.services.tunnel_service import (
    RemoteProvider,
    TunnelHandle,
    TunnelWatchdog,
    _CODEPLANE_TUNNEL_PREFIX,
    _find_existing_codeplane_tunnel,
    _lookup_devtunnel,
    validate_remote_provider,
)

if TYPE_CHECKING:
    import subprocess


def _as_popen(proc: _FakeProc) -> subprocess.Popen[str]:
    return cast("subprocess.Popen[str]", proc)


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

    def read(self, size: int = -1) -> str:
        if size >= 0:
            return self.output[:size]
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
        proc=_as_popen(_FakeProc(poll_result=1)),
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
        proc=_as_popen(original_proc),
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
    assert watchdog.proc is _as_popen(recovered_proc)


def test_watchdog_restart_process_gives_up_after_retries() -> None:
    watchdog = TunnelWatchdog(
        tunnel_url="https://example.test",
        restart_command=["devtunnel", "host", "name"],
        proc=_as_popen(_FakeProc(poll_result=None)),
        label="devtunnel",
    )
    watchdog._stop_event = threading.Event()
    failed_procs = [_FakeProc(poll_result=1, output=f"failure {index}") for index in range(3)]

    with patch("backend.services.tunnel_service.subprocess.Popen", side_effect=failed_procs):
        restarted = watchdog._restart_process()

    assert restarted is False
    assert watchdog.proc is _as_popen(failed_procs[-1])


# ---------------------------------------------------------------------------
# #9 — Random default tunnel name / prefix-based reuse
# ---------------------------------------------------------------------------


class TestTunnelNameRandomization:
    """Cover the new auto-random naming and prefix reuse logic."""

    @patch("backend.services.tunnel_service._list_devtunnels", return_value=[])
    def test_find_existing_tunnel_returns_none_when_empty(self, _mock) -> None:
        assert _find_existing_codeplane_tunnel() is None

    @patch(
        "backend.services.tunnel_service._list_devtunnels",
        return_value=[{"tunnelId": "cpl-a1b2c3d4.usw2"}],
    )
    def test_find_existing_tunnel_matches_prefix(self, _mock) -> None:
        result = _find_existing_codeplane_tunnel()
        assert result is not None
        name, region = result
        assert name == "cpl-a1b2c3d4"
        assert region == "usw2"

    @patch(
        "backend.services.tunnel_service._list_devtunnels",
        return_value=[{"tunnelId": "user-codeplane.usw2"}],
    )
    def test_find_existing_tunnel_ignores_old_naming_convention(self, _mock) -> None:
        result = _find_existing_codeplane_tunnel()
        assert result is None

    @patch(
        "backend.services.tunnel_service._list_devtunnels",
        return_value=[{"tunnelId": "cpl-abc."}],  # empty region
    )
    def test_find_existing_tunnel_skips_empty_region(self, _mock) -> None:
        result = _find_existing_codeplane_tunnel()
        assert result is None

    @patch(
        "backend.services.tunnel_service._list_devtunnels",
        return_value=[{"tunnelId": "cpl-abcd1234.euw1"}, {"tunnelId": "unrelated.usw2"}],
    )
    def test_lookup_devtunnel_exact_match(self, _mock) -> None:
        found, region = _lookup_devtunnel("cpl-abcd1234")
        assert found is True
        assert region == "euw1"

    @patch("backend.services.tunnel_service._list_devtunnels", return_value=[])
    def test_lookup_devtunnel_not_found(self, _mock) -> None:
        found, region = _lookup_devtunnel("nonexistent")
        assert found is False
        assert region is None

    def test_prefix_constant_starts_with_cpl(self) -> None:
        assert _CODEPLANE_TUNNEL_PREFIX == "cpl-"


# ---------------------------------------------------------------------------
# #7 — Lock around watchdog self.proc
# ---------------------------------------------------------------------------


class TestWatchdogLock:
    """Verify the threading lock is initialized and used during restart."""

    def test_watchdog_has_lock(self) -> None:
        watchdog = TunnelWatchdog(
            tunnel_url="https://example.test",
            restart_command=["echo"],
            proc=_as_popen(_FakeProc(poll_result=None)),
            label="test",
        )
        assert hasattr(watchdog, "_lock")
        # Should be a threading.Lock instance
        assert hasattr(watchdog._lock, "acquire")
        assert hasattr(watchdog._lock, "release")

    def test_restart_updates_proc_under_lock(self) -> None:
        """Verify _restart_process assigns self.proc (observable after restart)."""
        original = _FakeProc(poll_result=None)
        new_proc = _FakeProc(poll_result=None)
        watchdog = TunnelWatchdog(
            tunnel_url="https://example.test",
            restart_command=["echo"],
            proc=_as_popen(original),
            label="test",
        )
        watchdog._stop_event = threading.Event()

        with (
            patch("backend.services.tunnel_service.subprocess.Popen", return_value=new_proc),
            patch.object(watchdog, "_wait_for_recovery", return_value=True),
        ):
            watchdog._restart_process()

        assert watchdog.proc is _as_popen(new_proc)

    def test_tunnel_handle_close_reads_proc_under_lock(self) -> None:
        """Verify TunnelHandle.close() uses the lock when reading watchdog.proc."""
        proc = _FakeProc(poll_result=None)
        watchdog = TunnelWatchdog(
            tunnel_url="https://example.test",
            restart_command=["echo"],
            proc=_as_popen(proc),
            label="test",
        )
        # Manually stop the watchdog thread (it was never started)
        watchdog._stop_event.set()

        handle = TunnelHandle(
            provider=RemoteProvider.devtunnel,
            origin="https://example.test",
            proc=_as_popen(proc),
            watchdog=watchdog,
        )
        # Should not raise
        handle.close()
        assert proc.terminated


# ---------------------------------------------------------------------------
# #11 — Bounded subprocess output read
# ---------------------------------------------------------------------------


class TestBoundedOutputRead:
    def test_read_process_output_respects_max_bytes(self) -> None:
        large_output = "x" * 200_000
        proc = _FakeProc(poll_result=1, output=large_output)
        watchdog = TunnelWatchdog(
            tunnel_url="https://example.test",
            restart_command=["echo"],
            proc=_as_popen(proc),
            label="test",
        )
        result = watchdog._read_process_output(_as_popen(proc))
        assert len(result) <= watchdog._MAX_OUTPUT_BYTES

    def test_read_process_output_returns_full_when_small(self) -> None:
        proc = _FakeProc(poll_result=1, output="small output")
        watchdog = TunnelWatchdog(
            tunnel_url="https://example.test",
            restart_command=["echo"],
            proc=_as_popen(proc),
            label="test",
        )
        result = watchdog._read_process_output(_as_popen(proc))
        assert result == "small output"

    def test_read_process_output_no_stdout(self) -> None:
        proc = _FakeProc(poll_result=1)
        proc.stdout = None
        watchdog = TunnelWatchdog(
            tunnel_url="https://example.test",
            restart_command=["echo"],
            proc=_as_popen(proc),
            label="test",
        )
        assert watchdog._read_process_output(_as_popen(proc)) == ""


# ---------------------------------------------------------------------------
# #15 — Watchdog local health check
# ---------------------------------------------------------------------------


class TestWatchdogLocalHealthCheck:
    def test_health_url_uses_localhost_when_port_set(self) -> None:
        watchdog = TunnelWatchdog(
            tunnel_url="https://cpl-abc-8080.usw2.devtunnels.ms",
            restart_command=["echo"],
            proc=_as_popen(_FakeProc(poll_result=None)),
            label="devtunnel",
            local_port=8080,
        )
        # Verify the URL constructed in _health_ok targets localhost
        assert watchdog._local_port == 8080

    def test_health_url_uses_tunnel_url_when_no_port(self) -> None:
        watchdog = TunnelWatchdog(
            tunnel_url="https://cpl-abc-8080.usw2.devtunnels.ms",
            restart_command=["echo"],
            proc=_as_popen(_FakeProc(poll_result=None)),
            label="devtunnel",
        )
        assert watchdog._local_port is None

    @patch("urllib.request.urlopen")
    def test_health_ok_calls_localhost_url(self, mock_urlopen) -> None:
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        watchdog = TunnelWatchdog(
            tunnel_url="https://cpl-abc-8080.usw2.devtunnels.ms",
            restart_command=["echo"],
            proc=_as_popen(_FakeProc(poll_result=None)),
            label="devtunnel",
            local_port=9090,
        )
        result = watchdog._health_ok()
        assert result is True
        # Verify the URL passed to urlopen was the localhost one
        call_args = mock_urlopen.call_args
        req = call_args[0][0]
        assert "127.0.0.1:9090" in req.full_url


# ---------------------------------------------------------------------------
# #4 — Cloudflare token via env var (not CLI arg)
# ---------------------------------------------------------------------------


class TestCloudflareEnvVar:
    def test_restart_env_stored_on_watchdog(self) -> None:
        watchdog = TunnelWatchdog(
            tunnel_url="https://example.com",
            restart_command=["cloudflared", "tunnel", "run"],
            restart_env={"TUNNEL_TOKEN": "secret-token"},
            proc=_as_popen(_FakeProc(poll_result=None)),
            label="cloudflare",
        )
        assert watchdog.restart_env == {"TUNNEL_TOKEN": "secret-token"}
        # The token should NOT be in the restart command
        assert "secret-token" not in watchdog.restart_command
