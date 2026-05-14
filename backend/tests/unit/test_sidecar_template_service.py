"""Tests for backend.services.sidecar.template_service — validation and helpers."""

from __future__ import annotations

import json

import pytest

from backend.services.sidecar.template_service import (
    _ALLOWED_CONDITIONS,
    _ALLOWED_CONTEXT_SOURCES,
    _ALLOWED_ICONS,
    _ALLOWED_LIFETIMES,
    _ALLOWED_OUTPUT_ROUTES,
    _ALLOWED_PHASES,
    _ALLOWED_SCOPES,
    _strip_markdown_fences,
    _validate_definition,
)


# ── Minimal valid definition for testing ──

def _valid_definition(**overrides) -> dict:
    base = {
        "name": "test-sidecar",
        "description": "A test sidecar",
        "phase": "midflight",
        "lifetime": "ephemeral",
        "systemPrompt": "You are a test sidecar.",
        "triggers": [
            {
                "condition": {"kind": "manual"},
                "contextSources": ["trigger_event"],
                "outputRoutes": [{"kind": "event_bus", "eventKind": "test"}],
            }
        ],
    }
    base.update(overrides)
    return base


# ── _strip_markdown_fences ──


class TestStripMarkdownFences:
    def test_no_fences(self):
        text = '{"a": 1}'
        assert _strip_markdown_fences(text) == '{"a": 1}'

    def test_json_fences(self):
        text = '```json\n{"a": 1}\n```'
        assert _strip_markdown_fences(text) == '{"a": 1}'

    def test_bare_fences(self):
        text = '```\n{"a": 1}\n```'
        assert _strip_markdown_fences(text) == '{"a": 1}'

    def test_no_closing_fence(self):
        text = '```json\n{"a": 1}'
        result = _strip_markdown_fences(text)
        assert '{"a": 1}' in result

    def test_single_line_fence(self):
        text = "```"
        result = _strip_markdown_fences(text)
        assert isinstance(result, str)

    def test_multiline_content(self):
        text = '```json\n{\n  "a": 1,\n  "b": 2\n}\n```'
        result = _strip_markdown_fences(text)
        parsed = json.loads(result)
        assert parsed == {"a": 1, "b": 2}


# ── _validate_definition ──


class TestValidateDefinition:
    def test_valid_definition(self):
        _validate_definition(json.dumps(_valid_definition()))

    def test_invalid_json(self):
        with pytest.raises(ValueError, match="Invalid JSON"):
            _validate_definition("not json")

    def test_non_object(self):
        with pytest.raises(ValueError, match="must be a JSON object"):
            _validate_definition(json.dumps([1, 2, 3]))

    @pytest.mark.parametrize("missing_field", ["phase", "lifetime", "systemPrompt", "triggers"])
    def test_missing_required_field(self, missing_field):
        defn = _valid_definition()
        del defn[missing_field]
        with pytest.raises(ValueError, match=f"Missing required field: {missing_field!r}"):
            _validate_definition(json.dumps(defn))

    def test_invalid_scope(self):
        defn = _valid_definition(scope="invalid")
        with pytest.raises(ValueError, match="Invalid scope"):
            _validate_definition(json.dumps(defn))

    def test_valid_scopes(self):
        for scope in _ALLOWED_SCOPES:
            _validate_definition(json.dumps(_valid_definition(scope=scope)))

    def test_invalid_icon(self):
        defn = _valid_definition(icon="nonexistent")
        with pytest.raises(ValueError, match="Invalid icon"):
            _validate_definition(json.dumps(defn))

    def test_valid_icons(self):
        for icon in list(_ALLOWED_ICONS)[:5]:
            _validate_definition(json.dumps(_valid_definition(icon=icon)))

    def test_invalid_phase(self):
        defn = _valid_definition(phase="invalid")
        with pytest.raises(ValueError, match="Invalid phase"):
            _validate_definition(json.dumps(defn))

    def test_valid_phases(self):
        for phase in _ALLOWED_PHASES:
            _validate_definition(json.dumps(_valid_definition(phase=phase)))

    def test_invalid_lifetime(self):
        defn = _valid_definition(lifetime="invalid")
        with pytest.raises(ValueError, match="Invalid lifetime"):
            _validate_definition(json.dumps(defn))

    def test_valid_lifetimes(self):
        for lifetime in _ALLOWED_LIFETIMES:
            _validate_definition(json.dumps(_valid_definition(lifetime=lifetime)))

    def test_empty_system_prompt(self):
        defn = _valid_definition(systemPrompt="  ")
        with pytest.raises(ValueError, match="systemPrompt"):
            _validate_definition(json.dumps(defn))

    def test_non_string_system_prompt(self):
        defn = _valid_definition(systemPrompt=123)
        with pytest.raises(ValueError, match="systemPrompt"):
            _validate_definition(json.dumps(defn))

    def test_empty_triggers(self):
        defn = _valid_definition(triggers=[])
        with pytest.raises(ValueError, match="non-empty array"):
            _validate_definition(json.dumps(defn))

    def test_non_array_triggers(self):
        defn = _valid_definition(triggers="not-an-array")
        with pytest.raises(ValueError, match="non-empty array"):
            _validate_definition(json.dumps(defn))

    def test_non_object_trigger(self):
        defn = _valid_definition(triggers=["not-an-object"])
        with pytest.raises(ValueError, match="must be an object"):
            _validate_definition(json.dumps(defn))

    def test_invalid_context_source(self):
        defn = _valid_definition()
        defn["triggers"][0]["contextSources"] = ["invalid_source"]
        with pytest.raises(ValueError, match="not allowed"):
            _validate_definition(json.dumps(defn))

    def test_valid_context_sources(self):
        for source in _ALLOWED_CONTEXT_SOURCES:
            defn = _valid_definition()
            defn["triggers"][0]["contextSources"] = [source]
            _validate_definition(json.dumps(defn))

    def test_invalid_output_route(self):
        defn = _valid_definition()
        defn["triggers"][0]["outputRoutes"] = [{"kind": "invalid"}]
        with pytest.raises(ValueError, match="not allowed"):
            _validate_definition(json.dumps(defn))

    def test_valid_output_routes(self):
        for route_kind in _ALLOWED_OUTPUT_ROUTES:
            defn = _valid_definition()
            defn["triggers"][0]["outputRoutes"] = [{"kind": route_kind}]
            _validate_definition(json.dumps(defn))

    def test_invalid_condition(self):
        defn = _valid_definition()
        defn["triggers"][0]["condition"] = {"kind": "invalid_condition"}
        with pytest.raises(ValueError, match="not allowed"):
            _validate_definition(json.dumps(defn))

    def test_valid_conditions(self):
        for cond in _ALLOWED_CONDITIONS:
            defn = _valid_definition()
            defn["triggers"][0]["condition"] = {"kind": cond}
            _validate_definition(json.dumps(defn))


# ── Constants ──


class TestConstants:
    def test_allowed_phases(self):
        assert "preflight" in _ALLOWED_PHASES
        assert "midflight" in _ALLOWED_PHASES
        assert "postflight" in _ALLOWED_PHASES

    def test_allowed_lifetimes(self):
        assert "ephemeral" in _ALLOWED_LIFETIMES
        assert "windowed" in _ALLOWED_LIFETIMES
        assert "persistent" in _ALLOWED_LIFETIMES

    def test_allowed_scopes(self):
        assert "global" in _ALLOWED_SCOPES
        assert "repo" in _ALLOWED_SCOPES
        assert "job" in _ALLOWED_SCOPES

    def test_icons_set(self):
        assert len(_ALLOWED_ICONS) > 10
        assert "shield" in _ALLOWED_ICONS
        assert "brain" in _ALLOWED_ICONS
