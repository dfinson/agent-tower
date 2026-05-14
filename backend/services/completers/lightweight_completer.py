"""Lightweight HTTP-based completion — bypasses the full agent SDK subprocess.

Used for fast utility tasks (naming, summaries) where spawning a full Claude
Code subprocess per call is excessive.  Falls back to the adapter's
``complete()`` when direct API access isn't available.

Supports Anthropic Messages API (Claude) and OpenAI Chat Completions API
(GPT models, Copilot proxy).
"""

from __future__ import annotations

import os
import time
from typing import TYPE_CHECKING

import httpx
import structlog

if TYPE_CHECKING:
    from backend.services.agent_adapter import AgentAdapterInterface, CompletionResult

log = structlog.get_logger()

# Timeout for a single lightweight completion call (seconds)
_HTTP_TIMEOUT = 15.0

# Recreate the httpx client after this many seconds to avoid stale connections
_CLIENT_MAX_AGE_S = 300.0


class LightweightCompleter:
    """Direct-to-API completer that avoids subprocess overhead.

    Attempts a fast httpx call to the provider's API.  If keys aren't
    configured or the call fails, falls back to ``adapter.complete()``.
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
        self._provider: str | None = None  # "anthropic" | "openai" | None
        self._api_key: str | None = None
        self._base_url: str | None = None
        self._detect_provider()

    def _detect_provider(self) -> None:
        """Detect which direct API path is available from environment."""
        anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
        if anthropic_key and self._is_anthropic_model(self._model):
            self._provider = "anthropic"
            self._api_key = anthropic_key
            self._base_url = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
            log.debug(
                "lightweight_completer_ready",
                provider="anthropic",
                model=self._model,
            )
            return

        openai_key = os.environ.get("OPENAI_API_KEY")
        if openai_key and not self._is_anthropic_model(self._model):
            self._provider = "openai"
            self._api_key = openai_key
            self._base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com")
            log.debug(
                "lightweight_completer_ready",
                provider="openai",
                model=self._model,
            )
            return

        log.debug("lightweight_completer_unavailable", model=self._model)

    @staticmethod
    def _is_anthropic_model(model: str) -> bool:
        return "claude" in model.lower()

    @property
    def available(self) -> bool:
        """True when a direct API path is configured."""
        return self._provider is not None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is not None and (time.monotonic() - self._client_created_at) > _CLIENT_MAX_AGE_S:
            await self._client.aclose()
            self._client = None
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=_HTTP_TIMEOUT)
            self._client_created_at = time.monotonic()
        return self._client

    async def complete(self, prompt: str) -> CompletionResult:
        """Fast completion — direct HTTP when possible, adapter fallback otherwise."""

        if self._provider == "anthropic":
            try:
                return await self._anthropic_complete(prompt)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in (401, 403):
                    log.error(
                        "lightweight_anthropic_auth_failed",
                        status=exc.response.status_code,
                    )
                    self._provider = None
                else:
                    log.warning(
                        "lightweight_anthropic_failed_falling_back",
                        status=exc.response.status_code,
                        exc_info=True,
                    )
            except (httpx.HTTPError, OSError, ValueError, KeyError):
                log.warning(
                    "lightweight_anthropic_failed_falling_back",
                    exc_info=True,
                )

        if self._provider == "openai":
            try:
                return await self._openai_complete(prompt)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in (401, 403):
                    log.error(
                        "lightweight_openai_auth_failed",
                        status=exc.response.status_code,
                    )
                    self._provider = None
                else:
                    log.warning(
                        "lightweight_openai_failed_falling_back",
                        status=exc.response.status_code,
                        exc_info=True,
                    )
            except (httpx.HTTPError, OSError, ValueError, KeyError):
                log.warning(
                    "lightweight_openai_failed_falling_back",
                    exc_info=True,
                )

        # Fallback to full adapter
        return await self._adapter.complete(prompt)

    async def _anthropic_complete(self, prompt: str) -> CompletionResult:
        """Call Anthropic Messages API directly."""
        from backend.services.agent_adapter import CompletionResult

        client = await self._get_client()
        resp = await client.post(
            f"{self._base_url}/v1/messages",
            headers={
                "x-api-key": self._api_key,  # type: ignore[arg-type]  # _api_key is str at runtime; narrowed from str | None above
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": self._model,
                "max_tokens": 256,
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
        """Call OpenAI Chat Completions API directly."""
        from backend.services.agent_adapter import CompletionResult

        client = await self._get_client()
        resp = await client.post(
            f"{self._base_url}/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self._model,
                "max_tokens": 256,
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
