"""Thin wrapper around the GitHub Copilot steer API.

Sends steering commands (operator messages, abort) to a Copilot CLI
``--remote`` session via the GitHub cloud relay.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
import structlog

if TYPE_CHECKING:
    pass

log = structlog.get_logger()

_STEER_BASE = "https://api.enterprise.githubcopilot.com/agents/tasks"


class CopilotSteerClient:
    """Sends steering commands to a Copilot CLI --remote session."""

    def __init__(self, github_token: str) -> None:
        self._token = github_token
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0),
            headers={
                "Authorization": f"Bearer {github_token}",
                "Content-Type": "application/json",
            },
        )

    async def send_message(self, task_id: str, message: str) -> None:
        """POST /agents/tasks/{task_id}/steer with type=user."""
        url = f"{_STEER_BASE}/{task_id}/steer"
        resp = await self._client.post(url, json={"content": message, "type": "user"})
        resp.raise_for_status()
        log.info("copilot_steer_message_sent", task_id=task_id)

    async def abort(self, task_id: str) -> None:
        """POST /agents/tasks/{task_id}/steer with type=abort."""
        url = f"{_STEER_BASE}/{task_id}/steer"
        resp = await self._client.post(url, json={"type": "abort"})
        resp.raise_for_status()
        log.info("copilot_steer_abort_sent", task_id=task_id)

    async def close(self) -> None:
        await self._client.aclose()
