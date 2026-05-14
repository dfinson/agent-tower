"""Tests for backend.services.action_policy.monitor — MonitorSession helpers."""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock

import pytest

from backend.services.action_policy.monitor import (
    MonitorSession,
    MonitorVerdict,
    _HOST_FROM_URL_RE,
    _INSTALL_PACKAGE_RE,
)


@dataclass
class FakeAction:
    kind: str = "shell"
    command: str | None = None
    path: str | None = None
    tool_name: str | None = None
    mcp_tool: str | None = None


# ── MonitorVerdict enum ──


class TestMonitorVerdict:
    def test_values(self):
        assert MonitorVerdict.approve == "approve"
        assert MonitorVerdict.reject == "reject"
        assert MonitorVerdict.escalate == "escalate"


# ── _HOST_FROM_URL_RE ──


class TestHostRegex:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("https://example.com/api", "example.com"),
            ("http://api.stripe.com:443/v1", "api.stripe.com"),
            ("//cdn.example.org/lib.js", "cdn.example.org"),
            ("no url here", None),
        ],
    )
    def test_host_extraction(self, text, expected):
        m = _HOST_FROM_URL_RE.search(text)
        if expected is None:
            assert m is None
        else:
            assert m.group(1) == expected


# ── _INSTALL_PACKAGE_RE ──


class TestInstallPackageRegex:
    @pytest.mark.parametrize(
        "text,expected_pkg",
        [
            ("npm install lodash", "lodash"),
            ("pip install requests", "requests"),
            ("uv add httpx", "httpx"),
            ("cargo add serde", "serde"),
            ("gem install rails", "rails"),
            ("composer require laravel/framework", "laravel/framework"),
            ("echo hello", None),
        ],
    )
    def test_package_extraction(self, text, expected_pkg):
        m = _INSTALL_PACKAGE_RE.search(text)
        if expected_pkg is None:
            assert m is None
        else:
            assert m.group(1) == expected_pkg


# ── MonitorSession._extract_host ──


class TestExtractHost:
    def test_command_with_url(self):
        action = FakeAction(command="curl https://api.example.com/data")
        result = MonitorSession._extract_host(action)
        assert result == "api.example.com"

    def test_command_no_url(self):
        action = FakeAction(command="ls -la")
        result = MonitorSession._extract_host(action)
        assert result is None

    def test_path_with_url(self):
        action = FakeAction(command=None, path="https://cdn.example.org/asset.js")
        result = MonitorSession._extract_host(action)
        assert result == "cdn.example.org"

    def test_path_no_url(self):
        action = FakeAction(command=None, path="/home/user/file.txt")
        result = MonitorSession._extract_host(action)
        assert result is None

    def test_no_command_no_path(self):
        action = FakeAction(command=None, path=None)
        result = MonitorSession._extract_host(action)
        assert result is None


# ── MonitorSession._extract_packages ──


class TestExtractPackages:
    def test_single_package(self):
        action = FakeAction(command="pip install requests")
        result = MonitorSession._extract_packages(action)
        assert result == ["requests"]

    def test_multiple_packages(self):
        action = FakeAction(command="pip install requests httpx aiohttp")
        result = MonitorSession._extract_packages(action)
        assert result == ["requests", "httpx", "aiohttp"]

    def test_packages_with_versions(self):
        action = FakeAction(command="pip install requests>=2.0 httpx~=0.24")
        result = MonitorSession._extract_packages(action)
        assert result == ["requests", "httpx"]

    def test_scoped_npm_package(self):
        action = FakeAction(command="npm install @types/node")
        result = MonitorSession._extract_packages(action)
        assert result == ["node"]

    def test_packages_stop_at_flag(self):
        action = FakeAction(command="pip install requests -r requirements.txt")
        result = MonitorSession._extract_packages(action)
        assert result == ["requests"]

    def test_no_install_command(self):
        action = FakeAction(command="echo hello")
        result = MonitorSession._extract_packages(action)
        assert result == []

    def test_no_command(self):
        action = FakeAction(command=None)
        result = MonitorSession._extract_packages(action)
        assert result == []

    def test_uv_add(self):
        action = FakeAction(command="uv add pytest")
        result = MonitorSession._extract_packages(action)
        assert result == ["pytest"]
