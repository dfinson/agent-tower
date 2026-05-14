"""Tests for ModelPricingService — pure unit tests, no network or disk."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.services.analytics.model_pricing import (
    ModelPricingService,
    _extract_pricing,
    _normalize_model_key,
)

# ---------------------------------------------------------------------------
# _normalize_model_key
# ---------------------------------------------------------------------------


class TestNormalizeModelKey:
    def test_lowercase(self) -> None:
        assert _normalize_model_key("Claude-3.5-Sonnet") == "claude-3-5-sonnet"

    def test_spaces_to_hyphens(self) -> None:
        assert _normalize_model_key("gpt 4 turbo") == "gpt-4-turbo"

    def test_special_chars(self) -> None:
        assert _normalize_model_key("model@v2.0/latest") == "model-v2-0-latest"

    def test_deduplicates_hyphens(self) -> None:
        assert _normalize_model_key("a---b") == "a-b"

    def test_strips_leading_trailing_hyphens(self) -> None:
        assert _normalize_model_key("--model--") == "model"

    def test_empty_string(self) -> None:
        assert _normalize_model_key("") == ""

    def test_already_normalized(self) -> None:
        assert _normalize_model_key("claude-3-opus") == "claude-3-opus"


# ---------------------------------------------------------------------------
# _extract_pricing
# ---------------------------------------------------------------------------


class TestExtractPricing:
    def test_filters_by_provider(self) -> None:
        raw: dict[str, Any] = {
            "model-a": {
                "litellm_provider": "anthropic",
                "mode": "chat",
                "input_cost_per_token": 3e-6,
                "output_cost_per_token": 15e-6,
            },
            "model-b": {
                "litellm_provider": "cohere",
                "mode": "chat",
                "input_cost_per_token": 1e-6,
                "output_cost_per_token": 2e-6,
            },
        }
        result = _extract_pricing(raw)
        assert "model-a" in result
        assert "model-b" not in result

    def test_filters_non_chat(self) -> None:
        raw: dict[str, Any] = {
            "embedding": {
                "litellm_provider": "openai",
                "mode": "embedding",
                "input_cost_per_token": 1e-6,
                "output_cost_per_token": 0,
            },
        }
        assert _extract_pricing(raw) == {}

    def test_skips_zero_cost(self) -> None:
        raw: dict[str, Any] = {
            "free-model": {
                "litellm_provider": "openai",
                "mode": "chat",
                "input_cost_per_token": 0,
                "output_cost_per_token": 0,
            },
        }
        assert _extract_pricing(raw) == {}

    def test_converts_to_per_mtok(self) -> None:
        raw: dict[str, Any] = {
            "claude-3-opus": {
                "litellm_provider": "anthropic",
                "mode": "chat",
                "input_cost_per_token": 15e-6,
                "output_cost_per_token": 75e-6,
            },
        }
        result = _extract_pricing(raw)
        assert result["claude-3-opus"]["input"] == 15.0
        assert result["claude-3-opus"]["output"] == 75.0

    def test_includes_cache_costs(self) -> None:
        raw: dict[str, Any] = {
            "claude-3-opus": {
                "litellm_provider": "anthropic",
                "mode": "chat",
                "input_cost_per_token": 15e-6,
                "output_cost_per_token": 75e-6,
                "cache_read_input_token_cost": 1.5e-6,
                "cache_creation_input_token_cost": 18.75e-6,
            },
        }
        result = _extract_pricing(raw)
        assert result["claude-3-opus"]["cache_read"] == 1.5
        assert result["claude-3-opus"]["cache_write"] == 18.75

    def test_includes_token_limits(self) -> None:
        raw: dict[str, Any] = {
            "gpt-4": {
                "litellm_provider": "openai",
                "mode": "chat",
                "input_cost_per_token": 10e-6,
                "output_cost_per_token": 30e-6,
                "max_input_tokens": 128000,
                "max_output_tokens": 4096,
            },
        }
        result = _extract_pricing(raw)
        assert result["gpt-4"]["max_input_tokens"] == 128000
        assert result["gpt-4"]["max_output_tokens"] == 4096

    def test_empty_raw(self) -> None:
        assert _extract_pricing({}) == {}


# ---------------------------------------------------------------------------
# ModelPricingService
# ---------------------------------------------------------------------------


class TestModelPricingServiceLookup:
    def _make_svc(self, pricing: dict[str, dict[str, Any]] | None = None) -> ModelPricingService:
        svc = ModelPricingService(cache_path=Path("/tmp/test-cache.json"))
        if pricing:
            svc._pricing = pricing
        return svc

    def test_get_exact_match(self) -> None:
        svc = self._make_svc({"claude-3-opus": {"input": 15.0}})
        assert svc.get("claude-3-opus") == {"input": 15.0}

    def test_get_normalized_fallback(self) -> None:
        svc = self._make_svc({"claude-3-opus": {"input": 15.0}})
        assert svc.get("Claude 3 Opus") == {"input": 15.0}

    def test_get_unknown_model(self) -> None:
        svc = self._make_svc({"claude-3-opus": {"input": 15.0}})
        assert svc.get("nonexistent") is None

    def test_get_max_input_tokens(self) -> None:
        svc = self._make_svc({"gpt-4": {"max_input_tokens": 128000}})
        assert svc.get_max_input_tokens("gpt-4") == 128000

    def test_get_max_input_tokens_float(self) -> None:
        svc = self._make_svc({"gpt-4": {"max_input_tokens": 128000.0}})
        assert svc.get_max_input_tokens("gpt-4") == 128000

    def test_get_max_input_tokens_unknown(self) -> None:
        svc = self._make_svc({})
        assert svc.get_max_input_tokens("gpt-4") is None

    def test_get_max_input_tokens_missing_field(self) -> None:
        svc = self._make_svc({"gpt-4": {"input": 10.0}})
        assert svc.get_max_input_tokens("gpt-4") is None


class TestComputeCost:
    def _make_svc(self) -> ModelPricingService:
        svc = ModelPricingService(cache_path=Path("/tmp/test-cache.json"))
        svc._pricing = {
            "claude-3-opus": {
                "input": 15.0,
                "output": 75.0,
                "cache_read": 1.5,
                "cache_write": 18.75,
            },
        }
        return svc

    def test_basic_cost(self) -> None:
        svc = self._make_svc()
        cost = svc.compute_cost("claude-3-opus", 1000, 500, 0, 0)
        expected = (1000 * 15.0 + 500 * 75.0) / 1_000_000
        assert cost == pytest.approx(expected)

    def test_with_cache_tokens(self) -> None:
        svc = self._make_svc()
        cost = svc.compute_cost("claude-3-opus", 0, 0, 10000, 5000)
        expected = (10000 * 1.5 + 5000 * 18.75) / 1_000_000
        assert cost == pytest.approx(expected)

    def test_unknown_model_returns_zero(self) -> None:
        svc = self._make_svc()
        assert svc.compute_cost("nonexistent", 1000, 500, 0, 0) == 0.0


class TestPricingAge:
    def test_never_fetched(self) -> None:
        svc = ModelPricingService(cache_path=Path("/tmp/test-cache.json"))
        assert svc.pricing_age() is None

    def test_after_fetch(self) -> None:
        svc = ModelPricingService(cache_path=Path("/tmp/test-cache.json"))
        svc._fetched_at = datetime.now(UTC) - timedelta(hours=2)
        age = svc.pricing_age()
        assert age is not None
        assert age.total_seconds() >= 7200


class TestCachePersistence:
    def test_write_and_read_cache(self, tmp_path: Path) -> None:
        cache_file = tmp_path / "pricing.json"
        svc = ModelPricingService(cache_path=cache_file)
        pricing = {"claude-3": {"input": 15.0, "output": 75.0}}
        svc._write_cache(pricing)

        assert cache_file.exists()

        svc2 = ModelPricingService(cache_path=cache_file)
        loaded = svc2._read_cache()
        assert loaded is not None
        assert "claude-3" in loaded
        assert loaded["claude-3"]["input"] == 15.0

    def test_read_cache_missing_file(self, tmp_path: Path) -> None:
        svc = ModelPricingService(cache_path=tmp_path / "nonexistent.json")
        assert svc._read_cache() is None

    def test_read_cache_corrupt_json(self, tmp_path: Path) -> None:
        cache_file = tmp_path / "corrupt.json"
        cache_file.write_text("not json")
        svc = ModelPricingService(cache_path=cache_file)
        assert svc._read_cache() is None

    def test_read_cache_restores_fetched_at(self, tmp_path: Path) -> None:
        cache_file = tmp_path / "pricing.json"
        svc = ModelPricingService(cache_path=cache_file)
        svc._write_cache({"model": {"input": 1.0}})
        svc2 = ModelPricingService(cache_path=cache_file)
        svc2._read_cache()
        assert svc2._fetched_at is not None


class TestBundledFallback:
    def test_read_bundled(self) -> None:
        svc = ModelPricingService(cache_path=Path("/tmp/test-cache.json"))
        bundled = svc._read_bundled()
        # The bundled JSON ships with the package
        assert bundled is not None
        assert len(bundled) > 0


@pytest.mark.asyncio
class TestRefresh:
    async def test_refresh_network_success(self, tmp_path: Path) -> None:
        svc = ModelPricingService(cache_path=tmp_path / "cache.json")
        pricing = {"claude-3": {"input": 15.0, "output": 75.0}}
        svc._fetch_from_network = AsyncMock(return_value=pricing)  # type: ignore[method-assign]

        await svc.refresh()
        assert svc._pricing == pricing
        assert svc._fetched_at is not None
        assert (tmp_path / "cache.json").exists()

    async def test_refresh_falls_back_to_cache(self, tmp_path: Path) -> None:
        cache_file = tmp_path / "cache.json"
        svc = ModelPricingService(cache_path=cache_file)
        svc._write_cache({"cached-model": {"input": 5.0}})
        svc._pricing = {}  # clear
        svc._fetch_from_network = AsyncMock(return_value=None)  # type: ignore[method-assign]

        await svc.refresh()
        assert "cached-model" in svc._pricing

    async def test_refresh_falls_back_to_bundled(self) -> None:
        svc = ModelPricingService(cache_path=Path("/tmp/nonexistent-cache.json"))
        svc._fetch_from_network = AsyncMock(return_value=None)  # type: ignore[method-assign]

        await svc.refresh()
        assert svc.model_count > 0  # bundled should have models

    async def test_refresh_all_sources_fail(self, tmp_path: Path) -> None:
        svc = ModelPricingService(cache_path=tmp_path / "nonexistent.json")
        svc._fetch_from_network = AsyncMock(return_value=None)  # type: ignore[method-assign]
        svc._read_bundled = MagicMock(return_value=None)  # type: ignore[method-assign]

        await svc.refresh()
        assert svc._pricing == {}

    async def test_model_count_property(self) -> None:
        svc = ModelPricingService(cache_path=Path("/tmp/test.json"))
        svc._pricing = {"a": {}, "b": {}, "c": {}}
        assert svc.model_count == 3

    async def test_all_pricing_property(self) -> None:
        svc = ModelPricingService(cache_path=Path("/tmp/test.json"))
        pricing = {"a": {"input": 1.0}}
        svc._pricing = pricing
        assert svc.all_pricing is pricing
