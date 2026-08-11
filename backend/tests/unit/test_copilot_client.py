"""Tests for Copilot client construction helpers."""

from __future__ import annotations

import sys
from types import ModuleType

from backend.services.copilot_adapter._client import copilot_github_token, create_copilot_client


def test_copilot_github_token_uses_github_token(monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "gh-token")
    assert copilot_github_token() == "gh-token"


def test_copilot_github_token_falls_back_to_gh_token(monkeypatch) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setenv("GH_TOKEN", "gh-token")
    assert copilot_github_token() == "gh-token"


def test_copilot_github_token_empty_without_token(monkeypatch) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    assert copilot_github_token() is None


def test_create_copilot_client_does_not_pass_unsupported_kwargs(monkeypatch) -> None:
    class _FakeSubprocessConfig:
        def __init__(self, *, github_token: str | None = None) -> None:
            self.github_token = github_token

    class _FakeCopilotClient:
        def __init__(self, config: object | None = None) -> None:
            self.created = True
            self.config = config

    fake_module = ModuleType("copilot")
    fake_module.CopilotClient = _FakeCopilotClient  # type: ignore[attr-defined]
    fake_module.SubprocessConfig = _FakeSubprocessConfig  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "copilot", fake_module)
    monkeypatch.setenv("GITHUB_TOKEN", "gh-token")

    client = create_copilot_client()

    assert isinstance(client, _FakeCopilotClient)
    assert isinstance(client.config, _FakeSubprocessConfig)
    assert client.config.github_token == "gh-token"
