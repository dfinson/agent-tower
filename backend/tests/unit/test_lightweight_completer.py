"""Tests for backend.services.completers.lightweight_completer — provider detection and fallback."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

import pytest

from backend.services.completers.lightweight_completer import LightweightCompleter


class TestIsAnthropicModel:
    def test_claude_model(self):
        assert LightweightCompleter._is_anthropic_model("claude-haiku-4-5") is True

    def test_case_insensitive(self):
        assert LightweightCompleter._is_anthropic_model("CLAUDE-OPUS") is True

    def test_non_claude(self):
        assert LightweightCompleter._is_anthropic_model("gpt-4o") is False


class TestDetectProvider:
    def test_anthropic(self):
        adapter = AsyncMock()
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test"}, clear=False):
            c = LightweightCompleter(adapter, model="claude-haiku-4-5")
        assert c._provider == "anthropic"
        assert c._api_key == "sk-test"
        assert c.available is True

    def test_openai(self):
        adapter = AsyncMock()
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-openai"}, clear=False):
            os.environ.pop("ANTHROPIC_API_KEY", None)
            c = LightweightCompleter(adapter, model="gpt-4o")
        assert c._provider == "openai"
        assert c.available is True

    def test_no_keys(self):
        adapter = AsyncMock()
        with patch.dict(os.environ, {}, clear=True):
            c = LightweightCompleter(adapter, model="claude-haiku-4-5")
        assert c._provider is None
        assert c.available is False

    def test_anthropic_base_url(self):
        adapter = AsyncMock()
        with patch.dict(
            os.environ,
            {"ANTHROPIC_API_KEY": "sk-test", "ANTHROPIC_BASE_URL": "http://proxy:8000"},
            clear=False,
        ):
            c = LightweightCompleter(adapter, model="claude-haiku-4-5")
        assert c._base_url == "http://proxy:8000"


class TestCompleteFallback:
    @pytest.mark.asyncio()
    async def test_fallback_to_adapter(self):
        from backend.services.adapters.agent_adapter import CompletionResult

        adapter = AsyncMock()
        adapter.complete.return_value = CompletionResult(
            text="adapter result", input_tokens=10, output_tokens=5, model="test"
        )
        with patch.dict(os.environ, {}, clear=True):
            c = LightweightCompleter(adapter, model="test-model")
        result = await c.complete("test prompt")
        assert result.text == "adapter result"
        adapter.complete.assert_awaited_once()

    @pytest.mark.asyncio()
    async def test_client_recycling(self):
        """Client is recycled when older than max age."""
        adapter = AsyncMock()
        with patch.dict(os.environ, {}, clear=True):
            c = LightweightCompleter(adapter, model="test-model")
        # Force create a client
        c._client = None
        await c._get_client()
        assert c._client is not None

        # Set created_at to the past to trigger recycling
        c._client_created_at = 0.0
        new_client = await c._get_client()
        assert new_client is not None


class TestClose:
    @pytest.mark.asyncio()
    async def test_close_no_client(self):
        adapter = AsyncMock()
        with patch.dict(os.environ, {}, clear=True):
            c = LightweightCompleter(adapter, model="test")
        await c.close()

    @pytest.mark.asyncio()
    async def test_close_with_client(self):
        adapter = AsyncMock()
        with patch.dict(os.environ, {}, clear=True):
            c = LightweightCompleter(adapter, model="test")
        # Create a client
        await c._get_client()
        assert c._client is not None
        await c.close()
        assert c._client is None
