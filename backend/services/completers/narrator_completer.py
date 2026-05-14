"""Narrator completer — dedicated LLM path for long-form story generation.

Unlike the lightweight completer (256 max_tokens, 15s timeout — tuned for
short metadata like naming and summaries), the narrator completer is sized
for narrative prose: it reads the model's ``max_output_tokens`` from the
pricing data and uses a longer HTTP timeout.

Implements ``Completable`` so it can be injected directly into
``StoryService``.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
import structlog

if TYPE_CHECKING:
    from backend.services.adapters.agent_adapter import AgentAdapterInterface, CompletionResult

log = structlog.get_logger()

# Story generation can produce substantial output — allow time for it.
_HTTP_TIMEOUT = 120.0

# Recreate the httpx client after this many seconds to avoid stale connections
_CLIENT_MAX_AGE_S = 300.0

# Pricing data for looking up model output limits
_PRICING_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "model_pricing.json"


def _lookup_max_output_tokens(model: str) -> int | None:
    """Read the model's max_output_tokens from the pricing dataset."""
    try:
        data = json.loads(_PRICING_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return None

    entry = data.get(model)
    if not entry:
        normalized = re.sub(r"-+", "-", re.sub(r"[^a-z0-9]", "-", model.lower())).strip("-")
        entry = data.get(normalized)
    if entry and isinstance(entry.get("max_output_tokens"), (int, float)):
        return int(entry["max_output_tokens"])
    return None


class NarratorCompleter:
    """Direct-to-API completer for long-form narrative generation.

    Same provider detection as ``LightweightCompleter`` but with output
    limits appropriate for story generation:
    - ``max_tokens`` derived from the model's actual ``max_output_tokens``
    - HTTP timeout of 120s (vs 15s for utility calls)
    - Falls back to ``adapter.complete()`` when direct API isn't available
    """

    def __init__(
        self,
        adapter: AgentAdapterInterface,
        *,
        model: str = "claude-haiku-4-20250414",
    ) -> None:
        self._adapter = adapter
        self._model = model
        self._client: httpx.AsyncClient | None = None
        self._client_created_at: float = 0.0
        self._provider: str | None = None
        self._api_key: str | None = None
        self._base_url: str | None = None
        self._max_output_tokens: int | None = _lookup_max_output_tokens(model)
        self._detect_provider()

    def _detect_provider(self) -> None:
        """Detect which direct API path is available from environment."""
        anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
        if anthropic_key and self._is_anthropic_model(self._model):
            self._provider = "anthropic"
            self._api_key = anthropic_key
            self._base_url = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
            log.debug(
                "narrator_completer_ready",
                provider="anthropic",
                model=self._model,
                max_output_tokens=self._max_output_tokens,
            )
            return

        openai_key = os.environ.get("OPENAI_API_KEY")
        if openai_key and not self._is_anthropic_model(self._model):
            self._provider = "openai"
            self._api_key = openai_key
            self._base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com")
            log.debug(
                "narrator_completer_ready",
                provider="openai",
                model=self._model,
                max_output_tokens=self._max_output_tokens,
            )
            return

        log.debug("narrator_completer_unavailable", model=self._model)

    @staticmethod
    def _is_anthropic_model(model: str) -> bool:
        return "claude" in model.lower()

    @property
    def available(self) -> bool:
        return self._provider is not None

    @property
    def model(self) -> str:
        return self._model

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is not None and (time.monotonic() - self._client_created_at) > _CLIENT_MAX_AGE_S:
            await self._client.aclose()
            self._client = None
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=_HTTP_TIMEOUT)
            self._client_created_at = time.monotonic()
        return self._client

    def _effective_max_tokens(self) -> int:
        """Return the max output tokens for API calls.

        Uses the model's actual limit from pricing data.  Falls back to
        the model-family default when the specific model isn't in the
        pricing dataset.
        """
        if self._max_output_tokens:
            return self._max_output_tokens
        # Anthropic Claude models default to 8192, OpenAI to 16384
        if self._is_anthropic_model(self._model):
            return 8192
        return 16384

    async def complete(self, prompt: str, timeout: float = 120.0) -> str:
        """Generate long-form narrative text."""
        if self._provider == "anthropic":
            try:
                result = await self._anthropic_complete(prompt)
                return result.text or ""
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in (401, 403):
                    log.error("narrator_anthropic_auth_failed", status=exc.response.status_code)
                    self._provider = None
                else:
                    log.warning(
                        "narrator_anthropic_failed_falling_back",
                        status=exc.response.status_code,
                        exc_info=True,
                    )
            except (httpx.HTTPError, OSError, ValueError, KeyError):
                log.warning("narrator_anthropic_failed_falling_back", exc_info=True)

        if self._provider == "openai":
            try:
                result = await self._openai_complete(prompt)
                return result.text or ""
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in (401, 403):
                    log.error("narrator_openai_auth_failed", status=exc.response.status_code)
                    self._provider = None
                else:
                    log.warning("narrator_openai_failed_falling_back", status=exc.response.status_code, exc_info=True)
            except (httpx.HTTPError, OSError, ValueError, KeyError):
                log.warning("narrator_openai_failed_falling_back", exc_info=True)

        # Fallback to full adapter
        result = await self._adapter.complete(prompt)
        return result.text or ""

    async def _anthropic_complete(self, prompt: str) -> CompletionResult:
        from backend.services.adapters.agent_adapter import CompletionResult

        client = await self._get_client()
        resp = await client.post(
            f"{self._base_url}/v1/messages",
            headers={
                "x-api-key": self._api_key,  # type: ignore[arg-type]
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": self._model,
                "max_tokens": self._effective_max_tokens(),
                "messages": [{"role": "user", "content": prompt}],
            },
        )
        resp.raise_for_status()
        data = resp.json()

        text_parts = []
        for block in data.get("content", []):
            if block.get("type") == "text":
                text_parts.append(block["text"])

        usage = data.get("usage", {})
        return CompletionResult(
            text="\n".join(text_parts),
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            model=data.get("model", self._model),
        )

    async def _openai_complete(self, prompt: str) -> CompletionResult:
        from backend.services.adapters.agent_adapter import CompletionResult

        client = await self._get_client()
        resp = await client.post(
            f"{self._base_url}/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self._model,
                "max_tokens": self._effective_max_tokens(),
                "messages": [{"role": "user", "content": prompt}],
            },
        )
        resp.raise_for_status()
        data = resp.json()

        text = ""
        choices = data.get("choices", [])
        if choices:
            text = choices[0].get("message", {}).get("content", "")

        usage = data.get("usage", {})
        return CompletionResult(
            text=text or "",
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            model=data.get("model", self._model),
        )

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
