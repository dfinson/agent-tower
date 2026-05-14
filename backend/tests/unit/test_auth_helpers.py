"""Tests for backend.services.auth.middleware — pure helpers."""

from __future__ import annotations

from backend.services.auth.middleware import (
    _check_password,
    _create_session_token,
    _header_indicates_https,
    _origin_uses_https,
    generate_password,
    invalidate_session,
    is_password_auth_enabled,
    is_valid_token,
    set_password,
)

# ---------------------------------------------------------------------------
# _header_indicates_https
# ---------------------------------------------------------------------------


class TestHeaderIndicatesHttps:
    def test_none(self):
        assert _header_indicates_https(None) is False

    def test_empty(self):
        assert _header_indicates_https("") is False

    def test_https_literal(self):
        assert _header_indicates_https("https") is True

    def test_proto_https(self):
        assert _header_indicates_https("proto=https") is True

    def test_http(self):
        assert _header_indicates_https("http") is False

    def test_multiple_parts(self):
        assert _header_indicates_https("http, https") is True

    def test_case_insensitive(self):
        assert _header_indicates_https("HTTPS") is True


# ---------------------------------------------------------------------------
# _origin_uses_https
# ---------------------------------------------------------------------------


class TestOriginUsesHttps:
    def test_none(self):
        assert _origin_uses_https(None) is False

    def test_empty(self):
        assert _origin_uses_https("") is False

    def test_https(self):
        assert _origin_uses_https("https://example.com") is True

    def test_http(self):
        assert _origin_uses_https("http://example.com") is False


# ---------------------------------------------------------------------------
# generate_password
# ---------------------------------------------------------------------------


class TestGeneratePassword:
    def test_generates_string(self):
        pw = generate_password()
        assert isinstance(pw, str)
        assert len(pw) > 8

    def test_unique(self):
        a = generate_password()
        b = generate_password()
        assert a != b


# ---------------------------------------------------------------------------
# Password + session lifecycle
# ---------------------------------------------------------------------------


class TestPasswordLifecycle:
    def test_set_and_check(self):
        set_password("test123")
        assert is_password_auth_enabled() is True
        assert _check_password("test123") is True
        assert _check_password("wrong") is False

    def test_session_token_lifecycle(self):
        set_password("test_sess")
        token = _create_session_token()
        assert is_valid_token(token) is True
        invalidate_session(token)
        assert is_valid_token(token) is False

    def test_invalid_token(self):
        assert is_valid_token("nonexistent") is False

    def test_none_token(self):
        assert is_valid_token(None) is False
