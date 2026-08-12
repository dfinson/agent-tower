"""Shared Copilot client construction helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from copilot import CopilotClient


def create_copilot_client() -> CopilotClient:
    """Build a Copilot client."""
    from copilot import CopilotClient

    return CopilotClient()
