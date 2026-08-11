"""Shared Copilot client construction helpers."""

from __future__ import annotations

import os


def copilot_github_token() -> str | None:
    """Return the GitHub token CopilotClient should use, if one is present."""
    return os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
