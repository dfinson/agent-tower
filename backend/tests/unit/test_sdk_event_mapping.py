"""Tests for sdk_event_mapping — SDK result text parsing."""

from __future__ import annotations

from types import SimpleNamespace

from backend.services.adapters.sdk_event_mapping import (
    extract_result_text,
)

# ---------------------------------------------------------------------------
# extract_result_text
# ---------------------------------------------------------------------------


class TestExtractResultText:
    def test_none(self) -> None:
        assert extract_result_text(None) == ""

    def test_string_content(self) -> None:
        obj = SimpleNamespace(content="hello world")
        assert extract_result_text(obj) == "hello world"

    def test_list_content(self) -> None:
        items = [SimpleNamespace(text="part1"), SimpleNamespace(text="part2")]
        obj = SimpleNamespace(content=items)
        assert extract_result_text(obj) == "part1\npart2"

    def test_list_content_with_no_text(self) -> None:
        items = [SimpleNamespace(other="x")]
        obj = SimpleNamespace(content=items)
        assert extract_result_text(obj) == ""

    def test_fallback_str(self) -> None:
        obj = SimpleNamespace(other="value")
        result = extract_result_text(obj)
        assert "value" in result  # falls back to str(obj)
