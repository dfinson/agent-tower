"""Shared Copilot client construction helpers."""

from __future__ import annotations

import os


def copilot_client_kwargs() -> dict[str, str]:
    """Return auth kwargs for CopilotClient from the current environment."""
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        return {"github_token": token}
    return {}
