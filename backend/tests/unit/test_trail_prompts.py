"""Tests for trail.prompts — prompt helpers and response parsing."""

from __future__ import annotations

from types import SimpleNamespace

from backend.services.trail.prompts import (
    normalize_path,
    parse_enrichment_response,
    strip_code_fences,
)


class TestStripCodeFences:
    def test_no_fences(self) -> None:
        assert strip_code_fences('{"key": "val"}') == '{"key": "val"}'

    def test_json_fence(self) -> None:
        text = '```json\n{"key": "val"}\n```'
        assert strip_code_fences(text) == '{"key": "val"}'

    def test_plain_fence(self) -> None:
        text = '```\nsome content\n```'
        assert strip_code_fences(text) == "some content"

    def test_whitespace(self) -> None:
        text = '  ```json\n{"key": "val"}\n```  '
        assert strip_code_fences(text) == '{"key": "val"}'

    def test_no_trailing_fence(self) -> None:
        # Just leading fence — not a complete fence block
        text = '```json\n{"key": "val"}'
        result = strip_code_fences(text)
        assert '"key"' in result


class TestNormalizePath:
    def test_relative(self) -> None:
        assert normalize_path("./src/main.py") == "src/main.py"

    def test_absolute(self) -> None:
        assert normalize_path("/home/user/project/src/main.py") == "home/user/project/src/main.py"

    def test_already_normalized(self) -> None:
        assert normalize_path("src/main.py") == "src/main.py"

    def test_leading_dot_slash(self) -> None:
        assert normalize_path("../src/main.py") == "src/main.py"


class TestParseEnrichmentResponse:
    def test_valid_json(self) -> None:
        text = '{"annotations": [{"node_id": "n1", "intent": "fix bug"}], "semantic_nodes": []}'
        result = parse_enrichment_response(text)
        assert result is not None
        assert len(result["annotations"]) == 1

    def test_with_code_fences(self) -> None:
        text = '```json\n{"annotations": [], "semantic_nodes": []}\n```'
        result = parse_enrichment_response(text)
        assert result is not None

    def test_invalid_json(self) -> None:
        result = parse_enrichment_response("not json")
        assert result is None

    def test_empty_string(self) -> None:
        result = parse_enrichment_response("")
        assert result is None
