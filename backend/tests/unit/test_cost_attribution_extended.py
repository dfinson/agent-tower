"""Tests for cost_attribution — intent classification, phase inference, and sub-agent propagation."""

from __future__ import annotations

from backend.services.cost_attribution import (
    TurnContext,
    _classify_motivation,
    _classify_turn_intent,
    _compute_subagent_distributions,
    _infer_execution_phases,
)


def _ctx(*, cats: list[str] | None = None, cmds: list[str] | None = None, out_tok: int = 0, **kw: object) -> dict:
    """Build a minimal TurnContext dict."""
    d = {
        "phase": None,
        "cost_usd": 1.0,
        "input_tokens": 100,
        "output_tokens": out_tok,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "tool_categories": cats or [],
        "shell_commands": cmds or [],
    }
    d.update(kw)
    return d


# ---------------------------------------------------------------------------
# _infer_execution_phases (more tests supplementing existing)
# ---------------------------------------------------------------------------


class TestInferExecutionPhases:
    def test_all_none(self) -> None:
        spans = [{"execution_phase": None}, {"execution_phase": None}]
        assert _infer_execution_phases(spans) == [None, None]

    def test_single_valid(self) -> None:
        spans = [{"execution_phase": "agent_reasoning"}]
        assert _infer_execution_phases(spans) == ["agent_reasoning"]

    def test_forward_fill(self) -> None:
        spans = [
            {"execution_phase": "agent_reasoning"},
            {"execution_phase": None},
            {"execution_phase": None},
        ]
        assert _infer_execution_phases(spans) == ["agent_reasoning", "agent_reasoning", "agent_reasoning"]

    def test_backward_fill(self) -> None:
        spans = [
            {"execution_phase": None},
            {"execution_phase": "verification"},
        ]
        assert _infer_execution_phases(spans) == ["verification", "verification"]


# ---------------------------------------------------------------------------
# _classify_turn_intent — additional tests
# ---------------------------------------------------------------------------


class TestClassifyTurnIntentExtended:
    def test_shell_implementation(self) -> None:
        # sed command modifies files → implementation
        assert _classify_turn_intent(_ctx(cats=["shell"], cmds=["sed -i 's/old/new/' file.py"])) == "implementation"

    def test_agent_tool_only(self) -> None:
        assert _classify_turn_intent(_ctx(cats=["agent"])) == "investigation"

    def test_bookkeeping_only(self) -> None:
        assert _classify_turn_intent(_ctx(cats=["bookkeeping"])) == "overhead"

    def test_thinking_only(self) -> None:
        assert _classify_turn_intent(_ctx(cats=["thinking"])) == "reasoning"

    def test_no_tools_with_output(self) -> None:
        assert _classify_turn_intent(_ctx(out_tok=100)) == "communication"

    def test_no_tools_no_output(self) -> None:
        assert _classify_turn_intent(_ctx()) == "reasoning"

    def test_unknown_shell(self) -> None:
        assert _classify_turn_intent(_ctx(cats=["shell"], cmds=["some_unknown_cmd"])) == "investigation"

    def test_setup_shell(self) -> None:
        assert _classify_turn_intent(_ctx(cats=["shell"], cmds=["uv sync"])) == "setup"
        assert _classify_turn_intent(_ctx(cats=["shell"], cmds=["npm install"])) == "setup"

    def test_git_ops_shell(self) -> None:
        assert _classify_turn_intent(_ctx(cats=["shell"], cmds=["git commit -m 'fix'"])) == "git_ops"


# ---------------------------------------------------------------------------
# _compute_subagent_distributions
# ---------------------------------------------------------------------------


class TestComputeSubagentDistributions:
    def test_empty(self) -> None:
        assert _compute_subagent_distributions({}) == {}

    def test_no_subagents(self) -> None:
        contexts = {
            1: _ctx(cats=["file_write"]),
            2: _ctx(cats=["file_read"]),
        }
        assert _compute_subagent_distributions(contexts) == {}

    def test_no_invoking_turns(self) -> None:
        contexts = {
            1: {**_ctx(cats=["file_write"]), "is_subagent": True},
        }
        assert _compute_subagent_distributions(contexts) == {}

    def test_basic_propagation(self) -> None:
        contexts = {
            1: _ctx(cats=["agent"], cost_usd=5.0),  # invoking turn
            2: {**_ctx(cats=["file_write"], cost_usd=3.0), "is_subagent": True},
            3: {**_ctx(cats=["file_read"], cost_usd=2.0), "is_subagent": True},
        }
        result = _compute_subagent_distributions(contexts)
        assert 1 in result
        # Sub-agent turns: turn 2 → implementation, turn 3 → investigation
        dist = result[1]
        assert "implementation" in dist
        assert "investigation" in dist
        assert abs(sum(dist.values()) - 1.0) < 0.01

    def test_subagent_with_tool_weights(self) -> None:
        contexts = {
            1: _ctx(cats=["agent"], cost_usd=10.0),
            2: {
                **_ctx(cats=["file_write", "file_read"], cost_usd=5.0),
                "is_subagent": True,
                "tool_activity_weights": [("implementation", 3), ("investigation", 1)],
            },
        }
        result = _compute_subagent_distributions(contexts)
        assert 1 in result
        assert result[1]["implementation"] > result[1].get("investigation", 0)


# ---------------------------------------------------------------------------
# _classify_motivation
# ---------------------------------------------------------------------------


class TestClassifyMotivation:
    def test_error_recovery(self) -> None:
        nodes = [{"turn_number": 1, "is_retry": True}]
        ctx = _ctx()
        assert _classify_motivation(1, nodes, ctx) == "error_recovery"

    def test_error_kind_recovery(self) -> None:
        nodes = [{"turn_number": 1, "error_kind": "syntax_error"}]
        ctx = _ctx()
        assert _classify_motivation(1, nodes, ctx) == "error_recovery"

    def test_test_driven(self) -> None:
        nodes = [{"turn_number": 2}]
        ctx = _ctx(cats=["shell"], cmds=["pytest tests/"])
        assert _classify_motivation(2, nodes, ctx) == "test_driven_iteration"

    def test_plan_execution(self) -> None:
        nodes = [{"turn_number": 3, "plan_item_id": "ps-1"}]
        ctx = _ctx()
        assert _classify_motivation(3, nodes, ctx) == "plan_execution"

    def test_user_directed_first_turn(self) -> None:
        nodes = []
        ctx = _ctx()
        assert _classify_motivation(1, nodes, ctx) == "user_directed"

    def test_context_gathering(self) -> None:
        nodes = []
        ctx = _ctx(cats=["file_read", "file_search"])
        assert _classify_motivation(5, nodes, ctx) == "context_gathering"

    def test_agent_exploration_default(self) -> None:
        nodes = []
        ctx = _ctx()
        assert _classify_motivation(5, nodes, ctx) == "agent_exploration"
