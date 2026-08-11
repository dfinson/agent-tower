"""Tests for CI fake-agent mode."""

from __future__ import annotations

import pytest

from backend.models.domain import AgentSDK
from backend.services.adapters.adapter_registry import AdapterRegistry


def test_registry_uses_fake_adapter_in_e2e_mode(monkeypatch) -> None:
    monkeypatch.setenv("CODEPLANE_E2E_FAKE_AGENT", "1")

    registry = AdapterRegistry()
    adapter = registry.get_adapter(AgentSDK.copilot)

    assert adapter.__class__.__name__ == "E2EFakeCopilotAdapter"


@pytest.mark.asyncio
async def test_fake_model_cache_returns_static_models(monkeypatch) -> None:
    monkeypatch.setenv("CODEPLANE_E2E_FAKE_AGENT", "1")

    from backend.services.copilot_adapter._models import fetch_copilot_models_raw

    models = await fetch_copilot_models_raw()

    assert models == [
        {
            "id": "claude-sonnet-4-5-20250514",
            "name": "Claude Sonnet 4.5",
            "billing": {"multiplier": 1.0},
        }
    ]
