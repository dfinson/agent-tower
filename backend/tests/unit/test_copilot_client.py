"""Tests for Copilot client construction helpers."""

from __future__ import annotations

from backend.services.copilot_adapter._client import copilot_github_token


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
