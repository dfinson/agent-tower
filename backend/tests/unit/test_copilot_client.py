"""Tests for Copilot client construction helpers."""

from __future__ import annotations

from backend.services.copilot_adapter._client import copilot_client_kwargs


def test_copilot_client_kwargs_uses_github_token(monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "gh-token")
    assert copilot_client_kwargs() == {"github_token": "gh-token"}


def test_copilot_client_kwargs_falls_back_to_gh_token(monkeypatch) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setenv("GH_TOKEN", "gh-token")
    assert copilot_client_kwargs() == {"github_token": "gh-token"}


def test_copilot_client_kwargs_empty_without_token(monkeypatch) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    assert copilot_client_kwargs() == {}
