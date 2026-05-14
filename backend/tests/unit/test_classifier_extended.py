"""Tests for backend.services.action_policy.classifier — classification pipeline."""

from __future__ import annotations

from backend.services.action_policy.classifier import (
    Action,
    ActionKind,
    CostContext,
    Preset,
    RepoPolicy,
    Tier,
    _apply_cost_promotion,
    _classify_file,
    _classify_mcp_tool,
    _classify_sdk_tool,
    _match_explicit_rule,
    _safe_regex_search,
    classify,
    classify_properties,
    resolve_tier,
)

# ---------------------------------------------------------------------------
# _safe_regex_search
# ---------------------------------------------------------------------------


class TestSafeRegexSearch:
    def test_simple_match(self):
        assert _safe_regex_search(r"foo", "foobar") is True

    def test_no_match(self):
        assert _safe_regex_search(r"baz", "foobar") is False

    def test_invalid_regex_returns_on_timeout(self):
        # Invalid regex should not crash
        assert _safe_regex_search(r"(", "test", on_timeout=False) is False


# ---------------------------------------------------------------------------
# resolve_tier
# ---------------------------------------------------------------------------


class TestResolveTier:
    def test_autonomous_contained(self):
        assert resolve_tier(True, True, Preset.autonomous) == Tier.observe

    def test_autonomous_not_contained(self):
        assert resolve_tier(True, False, Preset.autonomous) == Tier.gate

    def test_supervised_reversible_contained(self):
        assert resolve_tier(True, True, Preset.supervised) == Tier.observe

    def test_supervised_not_reversible(self):
        assert resolve_tier(False, True, Preset.supervised) == Tier.gate

    def test_supervised_not_contained(self):
        assert resolve_tier(True, False, Preset.supervised) == Tier.gate

    def test_locked_reversible_contained(self):
        assert resolve_tier(True, True, Preset.locked) == Tier.checkpoint

    def test_locked_not_reversible(self):
        assert resolve_tier(False, True, Preset.locked) == Tier.gate


# ---------------------------------------------------------------------------
# _classify_file
# ---------------------------------------------------------------------------


class TestClassifyFile:
    def test_outside_worktree(self):
        action = Action(kind=ActionKind.file, path="/tmp/file.py", outside_worktree=True)
        rev, cont, reason = _classify_file(action, RepoPolicy())
        assert rev is True
        assert cont is False

    def test_binary_file(self):
        action = Action(kind=ActionKind.file, path="/img.png", is_binary=True)
        rev, cont, reason = _classify_file(action, RepoPolicy())
        assert rev is True
        assert cont is True

    def test_normal_file(self):
        action = Action(kind=ActionKind.file, path="/src/app.py")
        rev, cont, reason = _classify_file(action, RepoPolicy())
        assert rev is True
        assert cont is True


# ---------------------------------------------------------------------------
# _classify_sdk_tool
# ---------------------------------------------------------------------------


class TestClassifySdkTool:
    def test_known_file_write(self):
        action = Action(kind=ActionKind.sdk_tool, tool_name="create_file")
        rev, cont, reason = _classify_sdk_tool(action, RepoPolicy())
        assert rev is True
        assert cont is True

    def test_known_shell_with_command(self):
        action = Action(kind=ActionKind.sdk_tool, tool_name="bash", command="ls -la")
        rev, cont, reason = _classify_sdk_tool(action, RepoPolicy())
        assert "shell via" in reason

    def test_unknown_safe_category(self):
        action = Action(kind=ActionKind.sdk_tool, tool_name="grep_search")
        rev, cont, reason = _classify_sdk_tool(action, RepoPolicy())
        assert rev is True
        assert cont is True

    def test_unknown_tool(self):
        action = Action(kind=ActionKind.sdk_tool, tool_name="totally_unknown_xyz")
        rev, cont, reason = _classify_sdk_tool(action, RepoPolicy())
        assert rev is False


# ---------------------------------------------------------------------------
# _classify_mcp_tool
# ---------------------------------------------------------------------------


class TestClassifyMcpTool:
    def test_default(self):
        action = Action(kind=ActionKind.mcp_tool, mcp_server="srv", mcp_tool="do_thing")
        rev, cont, reason = _classify_mcp_tool(action, RepoPolicy())
        assert rev is False
        assert cont is True

    def test_server_config_reversible(self):
        policy = RepoPolicy(mcp_configs={"srv": {"reversible": True}})
        action = Action(kind=ActionKind.mcp_tool, mcp_server="srv", mcp_tool="do_thing")
        rev, cont, reason = _classify_mcp_tool(action, policy)
        assert rev is True

    def test_tool_override_relaxes(self):
        policy = RepoPolicy(
            mcp_configs={
                "srv": {
                    "reversible": False,
                    "tool_overrides": {"read_data": {"reversible": True}},
                }
            }
        )
        action = Action(kind=ActionKind.mcp_tool, mcp_server="srv", mcp_tool="read_data")
        rev, cont, reason = _classify_mcp_tool(action, policy)
        assert rev is True

    def test_read_only_hint_trusted(self):
        policy = RepoPolicy(mcp_configs={"srv": {"trust_read_only_hint": True}})
        action = Action(
            kind=ActionKind.mcp_tool,
            mcp_server="srv",
            mcp_tool="query",
            mcp_read_only=True,
        )
        rev, cont, reason = _classify_mcp_tool(action, policy)
        assert rev is True

    def test_read_only_hint_untrusted(self):
        policy = RepoPolicy(mcp_configs={"srv": {}})
        action = Action(
            kind=ActionKind.mcp_tool,
            mcp_server="srv",
            mcp_tool="query",
            mcp_read_only=True,
        )
        rev, cont, reason = _classify_mcp_tool(action, policy)
        assert rev is False  # Not trusted


# ---------------------------------------------------------------------------
# _match_explicit_rule
# ---------------------------------------------------------------------------


class TestMatchExplicitRule:
    def test_path_rule_match(self):
        policy = RepoPolicy(path_rules=[{"path_pattern": "*.log", "tier": "observe"}])
        action = Action(kind=ActionKind.file, path="app.log")
        assert _match_explicit_rule(action, policy) == Tier.observe

    def test_path_rule_no_match(self):
        policy = RepoPolicy(path_rules=[{"path_pattern": "*.log", "tier": "observe"}])
        action = Action(kind=ActionKind.file, path="app.py")
        assert _match_explicit_rule(action, policy) is None

    def test_action_rule_shell(self):
        policy = RepoPolicy(action_rules=[{"match_pattern": r"^rm\b", "tier": "gate"}])
        action = Action(kind=ActionKind.shell, command="rm -rf /tmp/test")
        assert _match_explicit_rule(action, policy) == Tier.gate

    def test_action_rule_tool_name(self):
        policy = RepoPolicy(action_rules=[{"match_pattern": r"deploy", "tier": "gate"}])
        action = Action(kind=ActionKind.sdk_tool, tool_name="deploy_production")
        assert _match_explicit_rule(action, policy) == Tier.gate

    def test_no_rules(self):
        policy = RepoPolicy()
        action = Action(kind=ActionKind.shell, command="ls")
        assert _match_explicit_rule(action, policy) is None


# ---------------------------------------------------------------------------
# _apply_cost_promotion
# ---------------------------------------------------------------------------


class TestApplyCostPromotion:
    def test_no_rules(self):
        assert _apply_cost_promotion(Tier.observe, [], CostContext()) == Tier.observe

    def test_below_threshold(self):
        rules = [{"threshold_value": 10.0, "promote_to": "gate"}]
        assert _apply_cost_promotion(Tier.observe, rules, CostContext(job_spend_usd=5.0)) == Tier.observe

    def test_above_threshold(self):
        rules = [{"threshold_value": 10.0, "promote_to": "gate"}]
        assert _apply_cost_promotion(Tier.observe, rules, CostContext(job_spend_usd=15.0)) == Tier.gate

    def test_no_demotion(self):
        rules = [{"threshold_value": 1.0, "promote_to": "observe"}]
        assert _apply_cost_promotion(Tier.gate, rules, CostContext(job_spend_usd=5.0)) == Tier.gate

    def test_missing_threshold(self):
        rules = [{"promote_to": "gate"}]
        assert _apply_cost_promotion(Tier.observe, rules, CostContext(job_spend_usd=100.0)) == Tier.observe


# ---------------------------------------------------------------------------
# classify (full pipeline)
# ---------------------------------------------------------------------------


class TestClassify:
    def test_basic_file_supervised(self):
        action = Action(kind=ActionKind.file, path="/src/app.py")
        result = classify(action, RepoPolicy())
        assert result.tier == Tier.observe
        assert result.reversible is True
        assert result.contained is True

    def test_shell_gate_supervised(self):
        action = Action(kind=ActionKind.shell, command="rm -rf /")
        result = classify(action, RepoPolicy())
        # Shell commands are not reversible → gate in supervised mode
        assert result.tier == Tier.gate

    def test_explicit_rule_overrides(self):
        policy = RepoPolicy(action_rules=[{"match_pattern": r"ls", "tier": "observe"}])
        action = Action(kind=ActionKind.shell, command="ls -la")
        result = classify(action, policy)
        assert result.tier == Tier.observe

    def test_cost_promotion(self):
        action = Action(kind=ActionKind.file, path="/src/app.py")
        policy = RepoPolicy(cost_rules=[{"threshold_value": 1.0, "promote_to": "gate"}])
        cost = CostContext(job_spend_usd=5.0)
        result = classify(action, policy, cost)
        assert result.tier == Tier.gate

    def test_classify_properties_dispatches(self):
        action = Action(kind=ActionKind.file, path="/app.py")
        rev, cont, reason = classify_properties(action, RepoPolicy())
        assert rev is True
