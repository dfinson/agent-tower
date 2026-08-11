"""Shared Copilot client construction helpers."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from copilot import CopilotClient


def copilot_github_token() -> str | None:
    """Return the GitHub token CopilotClient should use, if one is present."""
    return os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")


def create_copilot_client() -> CopilotClient:
    """Build a Copilot client, passing auth info only when available."""
    from copilot import CopilotClient

    client_factory: Any = CopilotClient
    token = copilot_github_token()
    return client_factory(github_token=token) if token else client_factory()
