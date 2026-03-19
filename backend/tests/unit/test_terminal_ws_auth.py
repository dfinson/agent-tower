"""Tests for WebSocket authentication on the terminal endpoint."""

from __future__ import annotations

import pytest

import backend.services.auth as auth_mod
from backend.services.auth import check_websocket_auth, set_password


@pytest.fixture(autouse=True)
def _reset_auth_state() -> None:
    """Ensure each test starts with clean auth state."""
    orig_hash = auth_mod._password_hash
    orig_tokens = auth_mod._session_tokens.copy()
    yield  # type: ignore[misc]
    auth_mod._password_hash = orig_hash
    auth_mod._session_tokens = orig_tokens


class TestCheckWebsocketAuth:
    """Unit tests for check_websocket_auth()."""

    def test_no_password_configured_allows_anyone(self) -> None:
        auth_mod._password_hash = None
        assert check_websocket_auth(client_host="8.8.8.8", cookies={}) is True

    def test_password_enabled_rejects_remote_without_cookie(self) -> None:
        set_password("secret")
        assert check_websocket_auth(client_host="8.8.8.8", cookies={}) is False

    def test_password_enabled_allows_localhost_ipv4(self) -> None:
        set_password("secret")
        assert check_websocket_auth(client_host="127.0.0.1", cookies={}) is True

    def test_password_enabled_allows_localhost_ipv6(self) -> None:
        set_password("secret")
        assert check_websocket_auth(client_host="::1", cookies={}) is True

    def test_password_enabled_allows_valid_session_cookie(self) -> None:
        set_password("secret")
        token = auth_mod._create_session_token()
        assert check_websocket_auth(client_host="8.8.8.8", cookies={"cpl_session": token}) is True

    def test_password_enabled_rejects_invalid_session_cookie(self) -> None:
        set_password("secret")
        assert check_websocket_auth(client_host="8.8.8.8", cookies={"cpl_session": "bogus"}) is False

    def test_none_client_host_falls_through_to_cookie_check(self) -> None:
        set_password("secret")
        token = auth_mod._create_session_token()
        assert check_websocket_auth(client_host=None, cookies={"cpl_session": token}) is True
        assert check_websocket_auth(client_host=None, cookies={}) is False
