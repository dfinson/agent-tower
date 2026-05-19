"""Tests for backend.services.tools.preflight_curator — constants and PreflightCurator."""

from __future__ import annotations

from backend.services.tools.preflight_curator import (
    _DISALLOWED_BUILTIN_TOOLS,
    _MAX_TURNS,
    _PREFLIGHT_SYSTEM_PROMPT,
    _SESSION_TIMEOUT_S,
    PreflightCurator,
)


class TestConstants:
    def test_max_turns(self):
        assert _MAX_TURNS == 15

    def test_session_timeout(self):
        assert _SESSION_TIMEOUT_S == 120

    def test_disallowed_tools(self):
        assert "Bash" in _DISALLOWED_BUILTIN_TOOLS
        assert "Edit" in _DISALLOWED_BUILTIN_TOOLS
        assert "Write" in _DISALLOWED_BUILTIN_TOOLS
        assert "Read" in _DISALLOWED_BUILTIN_TOOLS
        assert "Grep" in _DISALLOWED_BUILTIN_TOOLS
        assert "WebFetch" in _DISALLOWED_BUILTIN_TOOLS
        assert "WebSearch" in _DISALLOWED_BUILTIN_TOOLS
        # Ensure security-critical tools are blocked
        assert "MultiEdit" in _DISALLOWED_BUILTIN_TOOLS
        assert "Glob" in _DISALLOWED_BUILTIN_TOOLS

    def test_system_prompt_mentions_tools(self):
        assert "recon_scout" in _PREFLIGHT_SYSTEM_PROMPT
        assert "recon" in _PREFLIGHT_SYSTEM_PROMPT
        assert "scaffold" in _PREFLIGHT_SYSTEM_PROMPT
        assert "recon_impact" in _PREFLIGHT_SYSTEM_PROMPT

    def test_system_prompt_output_rules(self):
        assert "INCLUSION" in _PREFLIGHT_SYSTEM_PROMPT
        assert "VERBATIM" in _PREFLIGHT_SYSTEM_PROMPT


class TestPreflightCuratorInit:
    def test_init(self):
        from unittest.mock import AsyncMock

        adapter = AsyncMock()
        coderecon = AsyncMock()
        curator = PreflightCurator(adapter, coderecon=coderecon)
        assert curator._adapter is adapter
        assert curator._coderecon is coderecon
