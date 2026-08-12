"""Tests for Copilot client construction helpers."""

from __future__ import annotations

import sys
from types import ModuleType

from backend.services.copilot_adapter._client import create_copilot_client


def test_create_copilot_client_uses_plain_constructor(monkeypatch) -> None:
    class _FakeCopilotClient:
        def __init__(self, config: object | None = None) -> None:
            self.created = True
            self.config = config

    fake_module = ModuleType("copilot")
    fake_module.CopilotClient = _FakeCopilotClient  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "copilot", fake_module)
    monkeypatch.setenv("GITHUB_TOKEN", "gh-token")
    monkeypatch.setenv("GH_TOKEN", "gh-token")

    client = create_copilot_client()

    assert isinstance(client, _FakeCopilotClient)
    assert client.config is None
