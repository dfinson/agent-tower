"""Session-watching sub-package (Claude CLI + Copilot SDK)."""

from backend.services.watcher.claude import ClaudeSessionStateWatcher
from backend.services.watcher.copilot import SessionStateWatcher

__all__ = [
    "ClaudeSessionStateWatcher",
    "SessionStateWatcher",
]
