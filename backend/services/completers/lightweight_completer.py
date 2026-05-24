"""Lightweight completion — delegates to the SDK adapter.

Used for utility tasks (naming, summaries, monitoring).  All completions
route through the agent adapter (Copilot SDK).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from backend.services.adapters.agent_adapter import AgentAdapterInterface, CompletionResult

log = structlog.get_logger()


class LightweightCompleter:
    """Completer that delegates to the agent adapter.

    All calls go through ``adapter.complete()`` which routes through the
    Copilot SDK — no API keys, no direct HTTP.
    """

    def __init__(
        self,
        adapter: AgentAdapterInterface,
        *,
        model: str = "claude-haiku-4-20250414",
        max_tokens: int = 256,
    ) -> None:
        self._adapter = adapter
        self._model = model
        self._max_tokens = max_tokens

    @property
    def available(self) -> bool:
        """Always available — completions go through the SDK adapter."""
        return True

    async def complete(self, prompt: str) -> CompletionResult:
        """Complete via the SDK adapter."""
        return await self._adapter.complete(prompt)

    async def complete_messages(
        self,
        *,
        system: str,
        messages: list[dict[str, str]],
    ) -> CompletionResult:
        """Multi-turn completion — flattened into a single prompt for the adapter."""
        flat = system + "\n\n" + "\n".join(
            f"{'User' if m['role'] == 'user' else 'Assistant'}: {m['content']}"
            for m in messages
        )
        return await self._adapter.complete(flat)

    async def close(self) -> None:
        """No-op — no resources to clean up."""
