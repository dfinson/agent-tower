"""Tests for backend.services.coderecon.coderecon_tools — helper functions and constants."""

from __future__ import annotations

import json
from dataclasses import dataclass

from backend.services.coderecon.coderecon_tools import (
    _TOOL_DEFS,
    _TOOL_GUIDANCE_FULL,
    _TOOL_GUIDANCE_STANDARD,
    CodeReconToolKit,
    _item_to_dict,
    _resolve_tier,
    _serialize_result,
)

# ── _serialize_result ──


class TestSerializeResult:
    def test_string_passthrough(self):
        assert _serialize_result("hello") == "hello"

    def test_dict_to_json(self):
        result = _serialize_result({"a": 1, "b": "two"})
        parsed = json.loads(result)
        assert parsed == {"a": 1, "b": "two"}

    def test_list_of_primitives(self):
        result = _serialize_result([1, "two", True, None])
        parsed = json.loads(result)
        assert parsed == [1, "two", True, None]

    def test_list_of_dicts(self):
        result = _serialize_result([{"x": 1}, {"y": 2}])
        parsed = json.loads(result)
        assert parsed == [{"x": 1}, {"y": 2}]

    def test_list_of_objects_with_dict(self):
        @dataclass
        class Obj:
            name: str
            value: int

        result = _serialize_result([Obj("a", 1), Obj("b", 2)])
        parsed = json.loads(result)
        assert parsed[0]["name"] == "a"
        assert parsed[1]["value"] == 2

    def test_object_with_dict(self):
        @dataclass
        class Obj:
            x: int
            y: str

        result = _serialize_result(Obj(10, "hello"))
        parsed = json.loads(result)
        assert parsed["x"] == 10
        assert parsed["y"] == "hello"

    def test_fallback_to_str(self):
        result = _serialize_result(42)
        assert result == "42"

    def test_empty_list(self):
        result = _serialize_result([])
        assert json.loads(result) == []

    def test_empty_dict(self):
        result = _serialize_result({})
        assert json.loads(result) == {}


# ── _item_to_dict ──


class TestItemToDict:
    def test_primitives_passthrough(self):
        assert _item_to_dict("hello") == "hello"
        assert _item_to_dict(42) == 42
        assert _item_to_dict(3.14) == 3.14
        assert _item_to_dict(True) is True
        assert _item_to_dict(None) is None

    def test_dict_passthrough(self):
        d = {"a": 1}
        assert _item_to_dict(d) == d

    def test_object_with_dict(self):
        @dataclass
        class Foo:
            bar: int

        result = _item_to_dict(Foo(bar=7))
        assert result == {"bar": 7}

    def test_nested_dataclass_serializes_recursively(self):
        @dataclass
        class Inner:
            value: int

        @dataclass
        class Outer:
            name: str
            items: list[Inner]

        result = _item_to_dict(Outer(name="x", items=[Inner(value=1)]))
        assert result == {"name": "x", "items": [{"value": 1}]}

    def test_fallback_str(self):
        result = _item_to_dict(frozenset([1, 2]))
        assert isinstance(result, str)


# ── _resolve_tier ──


class TestResolveTier:
    def test_minimal(self):
        names = _resolve_tier("minimal")
        assert names == {"recon_impact"}

    def test_standard(self):
        names = _resolve_tier("standard")
        assert "recon_impact" in names
        assert "checkpoint" in names
        assert "graph_communities" not in names

    def test_preflight(self):
        names = _resolve_tier("preflight")
        assert names == {"recon_scout", "recon_impact", "recon", "recon_map", "scaffold"}

    def test_full(self):
        names = _resolve_tier("full")
        assert names == set(_TOOL_DEFS.keys())
        assert "graph_communities" in names
        assert "checkpoint" in names

    def test_unknown_returns_full(self):
        names = _resolve_tier("unknown_tier")
        assert names == set(_TOOL_DEFS.keys())


# ── CodeReconToolKit ──


class TestCodeReconToolKit:
    def test_defaults(self):
        kit = CodeReconToolKit()
        assert kit.claude_mcp_server is None
        assert kit.copilot_tools == []
        assert kit.system_prompt == ""
        assert kit.allowed_tool_names == []

    def test_custom_values(self):
        kit = CodeReconToolKit(
            system_prompt="prompt",
            allowed_tool_names=["recon_impact"],
        )
        assert kit.system_prompt == "prompt"
        assert kit.allowed_tool_names == ["recon_impact"]


# ── _TOOL_DEFS structure ──


class TestToolDefs:
    def test_all_have_description_and_schema(self):
        for name, defn in _TOOL_DEFS.items():
            assert "description" in defn, f"{name} missing description"
            assert "schema" in defn, f"{name} missing schema"
            assert isinstance(defn["schema"], dict)

    def test_required_tools_exist(self):
        assert "checkpoint" in _TOOL_DEFS
        assert "recon_impact" in _TOOL_DEFS
        assert "recon_scout" in _TOOL_DEFS
        assert "semantic_diff" in _TOOL_DEFS
        assert "graph_cycles" in _TOOL_DEFS
        assert "graph_communities" in _TOOL_DEFS

    def test_checkpoint_schema_has_changed_files_required(self):
        schema = _TOOL_DEFS["checkpoint"]["schema"]
        assert "changed_files" in schema["properties"]
        assert "changed_files" in schema.get("required", [])


# ── System prompt constants ──


class TestGuidancePrompts:
    def test_standard_mentions_impact(self):
        assert "recon_impact" in _TOOL_GUIDANCE_STANDARD

    def test_full_extends_standard(self):
        assert _TOOL_GUIDANCE_FULL.startswith(_TOOL_GUIDANCE_STANDARD)
        assert "graph_communities" in _TOOL_GUIDANCE_FULL
        assert "semantic_diff" in _TOOL_GUIDANCE_FULL

    def test_full_mentions_understand(self):
        assert "recon_scout" in _TOOL_GUIDANCE_FULL
