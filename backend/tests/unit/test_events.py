"""Unit tests for the transcript role -> dotted EventKind mapping."""

from __future__ import annotations

import pytest

from backend.models.events import EventKind, transcript_kind_for_role


class TestTranscriptKindForRole:
    @pytest.mark.parametrize(
        ("role", "expected"),
        [
            ("operator", EventKind.message_user),
            ("user", EventKind.message_user),
            ("agent", EventKind.message_assistant),
            ("assistant", EventKind.message_assistant),
            ("agent_delta", EventKind.message_delta),
            ("tool_running", EventKind.tool_call_started),
            ("tool_call", EventKind.tool_call_completed),
            # Reasoning / streaming sub-streams collapse to the full assistant
            # message kind but keep their role as an intra-kind discriminator.
            ("reasoning", EventKind.message_assistant),
            ("reasoning_delta", EventKind.message_assistant),
            ("tool_output_delta", EventKind.message_assistant),
            ("", EventKind.message_assistant),
            ("nonsense", EventKind.message_assistant),
        ],
    )
    def test_role_maps_to_kind(self, role: str, expected: EventKind) -> None:
        assert transcript_kind_for_role(role) == expected

    def test_tool_call_defaults_to_completed_without_success_flag(self) -> None:
        assert transcript_kind_for_role("tool_call") == EventKind.tool_call_completed
        assert transcript_kind_for_role("tool_call", tool_success=None) == EventKind.tool_call_completed

    def test_tool_call_success_true_is_completed(self) -> None:
        assert transcript_kind_for_role("tool_call", tool_success=True) == EventKind.tool_call_completed

    def test_tool_call_success_false_is_failed(self) -> None:
        assert transcript_kind_for_role("tool_call", tool_success=False) == EventKind.tool_call_failed

    def test_tool_success_flag_only_affects_tool_call_role(self) -> None:
        # A False success on a non-tool_call role must not fan out to failed.
        assert transcript_kind_for_role("agent", tool_success=False) == EventKind.message_assistant
