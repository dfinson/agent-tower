"""Tests for backend.services.completers.narrator_completer — provider detection, token lookup, helpers."""

from __future__ import annotations

import json
import os
from pathlib import Path  # noqa: TC003
from unittest.mock import AsyncMock, patch

import pytest

from backend.services.completers.narrator_completer import (
    NarratorCompleter,
    _lookup_max_output_tokens,
)

# ── _lookup_max_output_tokens ──


class TestLookupMaxOutputTokens:
    def test_known_model(self, tmp_path: Path):
        pricing = {"claude-sonnet-4-20250514": {"max_output_tokens": 16384}}
        pricing_file = tmp_path / "pricing.json"
        pricing_file.write_text(json.dumps(pricing))
        with patch("backend.services.completers.narrator_completer._PRICING_PATH", pricing_file):
            result = _lookup_max_output_tokens("claude-sonnet-4-20250514")
        assert result == 16384

    def test_unknown_model(self, tmp_path: Path):
        pricing = {"claude-sonnet-4-20250514": {"max_output_tokens": 16384}}
        pricing_file = tmp_path / "pricing.json"
        pricing_file.write_text(json.dumps(pricing))
        with patch("backend.services.completers.narrator_completer._PRICING_PATH", pricing_file):
            result = _lookup_max_output_tokens("unknown-model")
        assert result is None

    def test_normalized_lookup(self, tmp_path: Path):
        pricing = {"claude-haiku-4-20250414": {"max_output_tokens": 8192}}
        pricing_file = tmp_path / "pricing.json"
        pricing_file.write_text(json.dumps(pricing))
        with patch("backend.services.completers.narrator_completer._PRICING_PATH", pricing_file):
            result = _lookup_max_output_tokens("claude-haiku-4-20250414")
        assert result == 8192

    def test_missing_file(self, tmp_path: Path):
        pricing_file = tmp_path / "nonexistent.json"
        with patch("backend.services.completers.narrator_completer._PRICING_PATH", pricing_file):
            result = _lookup_max_output_tokens("any-model")
        assert result is None

    def test_invalid_json(self, tmp_path: Path):
        pricing_file = tmp_path / "bad.json"
        pricing_file.write_text("not json")
        with patch("backend.services.completers.narrator_completer._PRICING_PATH", pricing_file):
            result = _lookup_max_output_tokens("any-model")
        assert result is None

    def test_missing_max_output_tokens_key(self, tmp_path: Path):
        pricing = {"claude-sonnet-4-20250514": {"cost_per_token": 0.001}}
        pricing_file = tmp_path / "pricing.json"
        pricing_file.write_text(json.dumps(pricing))
        with patch("backend.services.completers.narrator_completer._PRICING_PATH", pricing_file):
            result = _lookup_max_output_tokens("claude-sonnet-4-20250514")
        assert result is None


# ── NarratorCompleter._is_anthropic_model ──


class TestIsAnthropicModel:
    def test_claude_model(self):
        assert NarratorCompleter._is_anthropic_model("claude-sonnet-4-20250514") is True
        assert NarratorCompleter._is_anthropic_model("claude-haiku-4-20250414") is True

    def test_case_insensitive(self):
        assert NarratorCompleter._is_anthropic_model("Claude-Sonnet-4") is True
        assert NarratorCompleter._is_anthropic_model("CLAUDE-haiku") is True

    def test_non_claude_model(self):
        assert NarratorCompleter._is_anthropic_model("gpt-4o") is False
        assert NarratorCompleter._is_anthropic_model("gemini-pro") is False


# ── NarratorCompleter._detect_provider ──


class TestDetectProvider:
    def test_anthropic_provider(self):
        adapter = AsyncMock()
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test"}, clear=False):
            completer = NarratorCompleter(adapter, model="claude-haiku-4-20250414")
        assert completer._provider == "anthropic"
        assert completer._api_key == "sk-test"

    def test_openai_provider(self):
        adapter = AsyncMock()
        env = {"OPENAI_API_KEY": "sk-openai"}
        with patch.dict(os.environ, env, clear=False), patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ANTHROPIC_API_KEY", None)
            completer = NarratorCompleter(adapter, model="gpt-4o")
        assert completer._provider == "openai"

    def test_no_provider(self):
        adapter = AsyncMock()
        with patch.dict(os.environ, {}, clear=True):
            completer = NarratorCompleter(adapter, model="claude-haiku-4-20250414")
        assert completer._provider is None

    def test_available_property(self):
        adapter = AsyncMock()
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test"}, clear=False):
            completer = NarratorCompleter(adapter, model="claude-haiku-4-20250414")
        assert completer.available is True

    def test_not_available(self):
        adapter = AsyncMock()
        with patch.dict(os.environ, {}, clear=True):
            completer = NarratorCompleter(adapter, model="claude-haiku-4-20250414")
        assert completer.available is False


# ── NarratorCompleter._effective_max_tokens ──


class TestEffectiveMaxTokens:
    def test_uses_pricing_data(self):
        adapter = AsyncMock()
        with patch.dict(os.environ, {}, clear=True):
            completer = NarratorCompleter(adapter, model="claude-haiku-4-20250414")
        completer._max_output_tokens = 4096
        assert completer._effective_max_tokens() == 4096

    def test_fallback_anthropic(self):
        adapter = AsyncMock()
        with patch.dict(os.environ, {}, clear=True):
            completer = NarratorCompleter(adapter, model="claude-haiku-4-20250414")
        completer._max_output_tokens = None
        assert completer._effective_max_tokens() == 8192

    def test_fallback_openai(self):
        adapter = AsyncMock()
        with patch.dict(os.environ, {}, clear=True):
            completer = NarratorCompleter(adapter, model="gpt-4o")
        completer._max_output_tokens = None
        assert completer._effective_max_tokens() == 16384

    def test_model_property(self):
        adapter = AsyncMock()
        with patch.dict(os.environ, {}, clear=True):
            completer = NarratorCompleter(adapter, model="test-model")
        assert completer.model == "test-model"


# ── NarratorCompleter.complete fallback ──


class TestComplete:
    @pytest.mark.asyncio()
    async def test_fallback_to_adapter(self):
        """When no direct provider, falls back to adapter.complete()."""
        from backend.services.adapters.agent_adapter import CompletionResult

        adapter = AsyncMock()
        adapter.complete.return_value = CompletionResult(
            text="adapter response",
            input_tokens=10,
            output_tokens=5,
            model="test",
        )
        with patch.dict(os.environ, {}, clear=True):
            completer = NarratorCompleter(adapter, model="claude-haiku-4-20250414")
        assert completer._provider is None

        result = await completer.complete("test prompt")
        assert result == "adapter response"
        adapter.complete.assert_awaited_once_with("test prompt")

    @pytest.mark.asyncio()
    async def test_fallback_empty_text(self):
        from backend.services.adapters.agent_adapter import CompletionResult

        adapter = AsyncMock()
        adapter.complete.return_value = CompletionResult(
            text=None,
            input_tokens=0,
            output_tokens=0,
            model="test",
        )
        with patch.dict(os.environ, {}, clear=True):
            completer = NarratorCompleter(adapter, model="test-model")

        result = await completer.complete("test prompt")
        assert result == ""
