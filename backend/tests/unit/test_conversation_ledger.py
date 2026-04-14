"""Tests for ConversationLedger and related utilities."""

from __future__ import annotations

import pytest

from backend.services.conversation_ledger import (
    ConversationLedger,
    LedgerEntry,
    MessageCategory,
    TokenCounter,
    make_counter,
)


class TestMessageCategory:
    def test_values(self) -> None:
        assert MessageCategory.agent == "agent"
        assert MessageCategory.operator == "operator"
        assert MessageCategory.tool_result == "tool_result"
        assert MessageCategory.file_content == "file_content"


class TestLedgerEntry:
    def test_creation(self) -> None:
        entry = LedgerEntry(role="assistant", category=MessageCategory.agent, tokens=100)
        assert entry.role == "assistant"
        assert entry.category == MessageCategory.agent
        assert entry.tokens == 100

    def test_frozen(self) -> None:
        entry = LedgerEntry(role="user", category=MessageCategory.operator, tokens=50)
        with pytest.raises(AttributeError):
            entry.tokens = 99  # type: ignore[misc]


class TestConversationLedger:
    def test_empty_ledger(self) -> None:
        ledger = ConversationLedger()
        assert ledger.total_messages == 0
        assert ledger.total_tokens == 0

    def test_set_system_prompt(self) -> None:
        ledger = ConversationLedger()
        ledger.set_system_prompt(500)
        comp = ledger.composition_at_turn(500)
        assert comp.system_tokens == 500
        assert comp.overhead_tokens == 0

    def test_record_message(self) -> None:
        ledger = ConversationLedger()
        ledger.record_message("user", MessageCategory.operator, 100)
        assert ledger.total_messages == 1
        assert ledger.total_tokens == 100

    def test_composition_at_turn(self) -> None:
        ledger = ConversationLedger()
        ledger.set_system_prompt(200)
        ledger.record_message("assistant", MessageCategory.agent, 150)
        ledger.record_message("user", MessageCategory.operator, 50)
        ledger.record_message("tool", MessageCategory.tool_result, 300)
        ledger.record_message("tool", MessageCategory.file_content, 100)

        comp = ledger.composition_at_turn(900)
        assert comp.system_tokens == 200
        assert comp.history_tokens == 200  # agent(150) + operator(50)
        assert comp.tool_result_tokens == 300
        assert comp.file_content_tokens == 100
        assert comp.sdk_reported_total == 900
        assert comp.overhead_tokens == 100  # 900 - 200 - 150 - 50 - 300 - 100

    def test_multiple_messages_same_category(self) -> None:
        ledger = ConversationLedger()
        ledger.record_message("assistant", MessageCategory.agent, 100)
        ledger.record_message("assistant", MessageCategory.agent, 200)
        comp = ledger.composition_at_turn(300)
        assert comp.history_tokens == 300

    def test_total_tokens_excludes_system(self) -> None:
        ledger = ConversationLedger()
        ledger.set_system_prompt(500)
        ledger.record_message("user", MessageCategory.operator, 100)
        assert ledger.total_tokens == 100  # system prompt not counted


class TestTokenCounter:
    def test_base_class_raises(self) -> None:
        counter = TokenCounter()
        with pytest.raises(NotImplementedError):
            counter.count("hello")


class TestMakeCounter:
    def test_unknown_model_raises(self) -> None:
        with pytest.raises(ValueError, match="No local tokenizer"):
            make_counter("unknown-model-xyz")
