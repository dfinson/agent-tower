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
    _match_explicit_rule,
    _safe_regex_search,
    classify,
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
