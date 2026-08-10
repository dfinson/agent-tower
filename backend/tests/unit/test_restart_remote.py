"""Focused tests for remote-origin resolution and probing (SPEC.md CAP-6).

Covers ``resolve_remote_probe_target`` (reusable vs non-reusable origin
selection, changed-origin detection, missing-origin failure) and
``probe_remote_origin`` (bounded reachability check against the exact
resolved origin — success, HTTP error, timeout, and unreachable cases).
"""

from __future__ import annotations

import urllib.error
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from backend.services.dev_restart.launch_profile import SecretSource, build_active_launch_profile
from backend.services.dev_restart.restart_protocol import RestartProtocolError
from backend.services.dev_restart.restart_remote import (
    RemoteProbeError,
    RemoteProbeTarget,
    probe_remote_origin,
    resolve_remote_probe_target,
)

if TYPE_CHECKING:
    from pathlib import Path

    from backend.services.dev_restart.launch_profile import LaunchProfile


@pytest.fixture(autouse=True)
def _isolated_codeplane_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point CODEPLANE_HOME at a throwaway directory (launch profiles read it lazily)."""
    monkeypatch.setenv("CODEPLANE_HOME", str(tmp_path))
    import backend.config as config_module

    monkeypatch.setattr(config_module, "_codeplane_dir", None)
    return tmp_path


def _remote_profile(**overrides: object) -> LaunchProfile:
    defaults: dict[str, object] = dict(
        executable="/usr/bin/python3",
        working_directory="/home/dev/codeplane",
        host="0.0.0.0",  # noqa: S104
        port=8080,
        dev=False,
        remote=True,
        provider="devtunnel",
        tunnel_ownership="managed",
        tunnel_name="cpl-ab12cd34",
        tunnel_origin="https://cpl-ab12cd34.devtunnels.ms",
        tunnel_origin_reusable=True,
        password_source=SecretSource.resolvable("environment", "CPL_PASSWORD"),
        tunnel_credential_source=SecretSource.resolvable("provider-login", "devtunnel"),
        started_pid=4242,
        started_process_time=1_700_000_000.5,
    )
    defaults.update(overrides)
    return build_active_launch_profile(**defaults)  # type: ignore[arg-type]


class TestResolveRemoteProbeTarget:
    def test_reusable_origin_uses_original_profile_and_reports_unchanged(self) -> None:
        original = _remote_profile(
            tunnel_origin="https://stable.devtunnels.ms",
            tunnel_origin_reusable=True,
        )
        # Even if the replacement recorded a different origin, a reusable
        # origin is authoritative from the *original* profile only.
        replacement = _remote_profile(
            tunnel_origin="https://should-be-ignored.devtunnels.ms",
            tunnel_origin_reusable=True,
        )

        target = resolve_remote_probe_target(original, replacement)

        assert target == RemoteProbeTarget(origin="https://stable.devtunnels.ms", changed=False)

    def test_non_reusable_origin_uses_replacement_profile_and_detects_change(self) -> None:
        original = _remote_profile(
            tunnel_origin="https://old-random-name.devtunnels.ms",
            tunnel_origin_reusable=False,
        )
        replacement = _remote_profile(
            tunnel_origin="https://new-random-name.devtunnels.ms",
            tunnel_origin_reusable=False,
        )

        target = resolve_remote_probe_target(original, replacement)

        assert target == RemoteProbeTarget(origin="https://new-random-name.devtunnels.ms", changed=True)

    def test_non_reusable_origin_reports_unchanged_when_identical(self) -> None:
        original = _remote_profile(
            tunnel_origin="https://same-name.devtunnels.ms",
            tunnel_origin_reusable=False,
        )
        replacement = _remote_profile(
            tunnel_origin="https://same-name.devtunnels.ms",
            tunnel_origin_reusable=False,
        )

        target = resolve_remote_probe_target(original, replacement)

        assert target == RemoteProbeTarget(origin="https://same-name.devtunnels.ms", changed=False)

    def test_reusable_origin_missing_on_original_raises(self) -> None:
        original = _remote_profile(tunnel_origin=None, tunnel_origin_reusable=True)
        replacement = _remote_profile(tunnel_origin="https://x.devtunnels.ms", tunnel_origin_reusable=True)

        with pytest.raises(RemoteProbeError, match="original launch profile"):
            resolve_remote_probe_target(original, replacement)

    def test_non_reusable_origin_missing_on_replacement_raises(self) -> None:
        original = _remote_profile(tunnel_origin="https://x.devtunnels.ms", tunnel_origin_reusable=False)
        replacement = _remote_profile(tunnel_origin=None, tunnel_origin_reusable=False)

        with pytest.raises(RemoteProbeError, match="replacement launch profile"):
            resolve_remote_probe_target(original, replacement)

    def test_reusable_none_is_treated_as_non_reusable(self) -> None:
        # tunnel_origin_reusable is bool | None on LaunchProfile; unset (None)
        # must not be mistaken for "reusable" — conservatively falls back to
        # the replacement's origin, same as an explicit False.
        original = _remote_profile(tunnel_origin="https://old.devtunnels.ms", tunnel_origin_reusable=None)
        replacement = _remote_profile(tunnel_origin="https://new.devtunnels.ms", tunnel_origin_reusable=None)

        target = resolve_remote_probe_target(original, replacement)

        assert target == RemoteProbeTarget(origin="https://new.devtunnels.ms", changed=True)

    def test_remote_probe_error_is_a_restart_protocol_error(self) -> None:
        assert issubclass(RemoteProbeError, RestartProtocolError)


class TestProbeRemoteOrigin:
    def test_probe_succeeds_on_2xx_response(self) -> None:
        class _FakeResponse:
            status = 200

            def __enter__(self) -> _FakeResponse:
                return self

            def __exit__(self, *args: object) -> None:
                return None

        with patch("urllib.request.urlopen", return_value=_FakeResponse()) as mock_urlopen:
            probe_remote_origin("https://cpl-ab12cd34.devtunnels.ms", timeout_seconds=5.0)

        (request,), kwargs = mock_urlopen.call_args
        assert request.full_url == "https://cpl-ab12cd34.devtunnels.ms/api/health"
        assert kwargs["timeout"] == 5.0

    def test_probe_strips_trailing_slash_from_origin(self) -> None:
        class _FakeResponse:
            status = 200

            def __enter__(self) -> _FakeResponse:
                return self

            def __exit__(self, *args: object) -> None:
                return None

        with patch("urllib.request.urlopen", return_value=_FakeResponse()) as mock_urlopen:
            probe_remote_origin("https://cpl-ab12cd34.devtunnels.ms/", timeout_seconds=5.0)

        (request,), _ = mock_urlopen.call_args
        assert request.full_url == "https://cpl-ab12cd34.devtunnels.ms/api/health"

    def test_probe_raises_on_non_2xx_status(self) -> None:
        class _FakeResponse:
            status = 503

            def __enter__(self) -> _FakeResponse:
                return self

            def __exit__(self, *args: object) -> None:
                return None

        with (
            patch("urllib.request.urlopen", return_value=_FakeResponse()),
            pytest.raises(RemoteProbeError, match="unhealthy status 503"),
        ):
            probe_remote_origin("https://cpl-ab12cd34.devtunnels.ms", timeout_seconds=5.0)

    def test_probe_raises_on_http_error(self) -> None:
        http_error = urllib.error.HTTPError(
            "https://cpl-ab12cd34.devtunnels.ms/api/health", 404, "not found", None, None
        )
        with (
            patch("urllib.request.urlopen", side_effect=http_error),
            pytest.raises(RemoteProbeError, match="HTTP 404"),
        ):
            probe_remote_origin("https://cpl-ab12cd34.devtunnels.ms", timeout_seconds=5.0)

    def test_probe_raises_on_timeout(self) -> None:
        with (
            patch("urllib.request.urlopen", side_effect=TimeoutError("timed out")),
            pytest.raises(RemoteProbeError, match="timed out after 2.0s"),
        ):
            probe_remote_origin("https://cpl-ab12cd34.devtunnels.ms", timeout_seconds=2.0)

    def test_probe_raises_on_socket_timeout_alias(self) -> None:
        # socket.timeout is an alias of TimeoutError in modern Python, but
        # urlopen sometimes raises it directly for read-phase timeouts.
        with (
            patch("urllib.request.urlopen", side_effect=TimeoutError("timed out")),
            pytest.raises(RemoteProbeError, match="timed out"),
        ):
            probe_remote_origin("https://cpl-ab12cd34.devtunnels.ms", timeout_seconds=2.0)

    def test_probe_raises_on_unreachable(self) -> None:
        url_error = urllib.error.URLError("Name or service not known")
        with (
            patch("urllib.request.urlopen", side_effect=url_error),
            pytest.raises(RemoteProbeError, match="unreachable"),
        ):
            probe_remote_origin("https://gone.devtunnels.ms", timeout_seconds=5.0)

    def test_probe_never_touches_local_process_apis(self) -> None:
        # CAP-6: external mode must never scan/spawn to discover the origin.
        # A successful mocked urlopen call proves no other subprocess/psutil
        # code path is exercised in this function.
        class _FakeResponse:
            status = 200

            def __enter__(self) -> _FakeResponse:
                return self

            def __exit__(self, *args: object) -> None:
                return None

        with (
            patch("urllib.request.urlopen", return_value=_FakeResponse()),
            patch("subprocess.Popen") as mock_popen,
            patch("psutil.Process") as mock_process,
        ):
            probe_remote_origin("https://cpl-ab12cd34.devtunnels.ms", timeout_seconds=5.0)

        mock_popen.assert_not_called()
        mock_process.assert_not_called()
