"""ModelPricingService — single source of truth for LLM model pricing.

Fetches pricing from the LiteLLM community JSON at startup, caches locally,
and falls back to the bundled ``backend/data/model_pricing.json`` when the
network is unavailable.

Fallback chain: network fetch → local cache file → bundled JSON → empty dict.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import structlog

log = structlog.get_logger()

_LITELLM_URL = (
    "https://raw.githubusercontent.com/BerriAI/litellm/main/"
    "model_prices_and_context_window.json"
)
_PROVIDERS = frozenset({"anthropic", "openai"})
_BUNDLED_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "model_pricing.json"


def _normalize_model_key(model: str) -> str:
    """Normalize model name: lowercase, non-alnum → hyphen, deduplicate hyphens."""
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]", "-", model.lower())).strip("-")


def _extract_pricing(raw: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Transform raw LiteLLM pricing into our compact format ($/MTok)."""
    models: dict[str, dict[str, Any]] = {}
    for key, entry in raw.items():
        provider = entry.get("litellm_provider", "")
        if provider not in _PROVIDERS:
            continue
        if entry.get("mode", "") != "chat":
            continue

        input_cost = entry.get("input_cost_per_token", 0)
        output_cost = entry.get("output_cost_per_token", 0)
        if not input_cost and not output_cost:
            continue

        models[key] = {
            "provider": provider,
            "input": round(input_cost * 1_000_000, 4),
            "output": round(output_cost * 1_000_000, 4),
            "cache_read": round(entry.get("cache_read_input_token_cost", 0) * 1_000_000, 4),
            "cache_write": round(entry.get("cache_creation_input_token_cost", 0) * 1_000_000, 4),
            "max_input_tokens": entry.get("max_input_tokens", 0),
            "max_output_tokens": entry.get("max_output_tokens", 0),
        }
    return models


class ModelPricingService:
    """Manages LLM pricing data with runtime refresh and multi-tier fallback."""

    def __init__(self, *, cache_path: Path, refresh_interval_hours: int = 24) -> None:
        self._cache_path = cache_path
        self._refresh_interval = timedelta(hours=refresh_interval_hours)
        self._pricing: dict[str, dict[str, Any]] = {}
        self._fetched_at: datetime | None = None
        self._refresh_task: asyncio.Task[Any] | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, model: str) -> dict[str, Any] | None:
        """Look up pricing entry by exact key, then by normalized key."""
        entry = self._pricing.get(model)
        if entry is None:
            entry = self._pricing.get(_normalize_model_key(model))
        return entry

    def get_max_input_tokens(self, model: str) -> int | None:
        """Return a model's max input token count, or None if unknown."""
        entry = self.get(model)
        if entry and isinstance(entry.get("max_input_tokens"), (int, float)):
            return int(entry["max_input_tokens"])
        return None

    def compute_cost(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cache_read_tokens: int,
        cache_write_tokens: int,
    ) -> float:
        """Compute USD cost from token counts. Returns 0.0 if model is unknown."""
        entry = self.get(model)
        if not entry:
            return 0.0
        cost = (
            input_tokens * entry.get("input", 0)
            + output_tokens * entry.get("output", 0)
            + cache_read_tokens * entry.get("cache_read", 0)
            + cache_write_tokens * entry.get("cache_write", 0)
        ) / 1_000_000
        return float(cost)

    def pricing_age(self) -> timedelta | None:
        """How stale the current pricing data is. None if never fetched."""
        if self._fetched_at is None:
            return None
        return datetime.now(UTC) - self._fetched_at

    @property
    def model_count(self) -> int:
        return len(self._pricing)

    @property
    def all_pricing(self) -> dict[str, dict[str, Any]]:
        """Return the full pricing dict (read-only view for API endpoints)."""
        return self._pricing

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def refresh(self) -> None:
        """Fetch fresh pricing. Falls back to cache, then bundled JSON."""
        # Try network fetch
        fetched = await self._fetch_from_network()
        if fetched is not None:
            self._pricing = fetched
            self._fetched_at = datetime.now(UTC)
            self._write_cache(fetched)
            log.info("model_pricing_refreshed", source="network", count=len(fetched))
            return

        # Try local cache
        cached = self._read_cache()
        if cached is not None:
            self._pricing = cached
            log.info("model_pricing_refreshed", source="cache", count=len(cached))
            return

        # Fall back to bundled JSON
        bundled = self._read_bundled()
        if bundled is not None:
            self._pricing = bundled
            log.info("model_pricing_refreshed", source="bundled", count=len(bundled))
            return

        log.warning("model_pricing_unavailable", msg="All pricing sources failed")

    def start_background_refresh(self) -> None:
        """Spawn a background task that refreshes pricing periodically."""
        if self._refresh_task is not None:
            return
        self._refresh_task = asyncio.create_task(
            self._refresh_loop(), name="model-pricing-refresh"
        )

    async def stop(self) -> None:
        """Cancel the background refresh task."""
        if self._refresh_task is not None:
            self._refresh_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._refresh_task
            self._refresh_task = None

    # ------------------------------------------------------------------
    # Internal: fetch / cache / bundled
    # ------------------------------------------------------------------

    async def _fetch_from_network(self) -> dict[str, dict[str, Any]] | None:
        """Fetch pricing from LiteLLM GitHub. Returns None on failure."""
        import urllib.error
        import urllib.request

        def _do_fetch() -> dict[str, dict[str, Any]] | None:
            try:
                with urllib.request.urlopen(_LITELLM_URL, timeout=30) as resp:  # noqa: S310
                    raw = json.loads(resp.read())
                return _extract_pricing(raw)
            except (urllib.error.URLError, OSError, json.JSONDecodeError, ValueError) as exc:
                log.warning("model_pricing_fetch_failed", error=str(exc))
                return None

        return await asyncio.to_thread(_do_fetch)

    def _write_cache(self, pricing: dict[str, dict[str, Any]]) -> None:
        """Write pricing to local cache file with metadata."""
        try:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "_meta": {"fetched_at": datetime.now(UTC).isoformat()},
                **pricing,
            }
            self._cache_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        except OSError as exc:
            log.warning("model_pricing_cache_write_failed", error=str(exc))

    def _read_cache(self) -> dict[str, dict[str, Any]] | None:
        """Read pricing from local cache file. Returns None on failure."""
        try:
            data = json.loads(self._cache_path.read_text())
            meta = data.pop("_meta", None)
            if meta and isinstance(meta.get("fetched_at"), str):
                self._fetched_at = datetime.fromisoformat(meta["fetched_at"])
            return dict(data)
        except (OSError, json.JSONDecodeError, ValueError):
            return None

    def _read_bundled(self) -> dict[str, dict[str, Any]] | None:
        """Read the bundled pricing JSON shipped with the package."""
        try:
            return dict(json.loads(_BUNDLED_PATH.read_text()))
        except (OSError, json.JSONDecodeError):
            return None

    async def _refresh_loop(self) -> None:
        """Periodically refresh pricing data."""
        while True:
            await asyncio.sleep(self._refresh_interval.total_seconds())
            try:
                await self.refresh()
            except Exception:
                log.exception("model_pricing_background_refresh_failed")
