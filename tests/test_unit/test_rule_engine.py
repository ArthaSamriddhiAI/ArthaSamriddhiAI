"""Tests for the AST-sandboxed rule evaluation engine."""

from __future__ import annotations

import pytest

from artha.governance.rules.engine import RuleEngine, UnsafeExpressionError, evaluate_condition
from artha.governance.rules.models import (
    Rule,
    RuleCategory,
    RuleEvaluation,
    RuleSet,
    RuleSeverity,
)
from datetime import datetime, UTC


class TestEvaluateCondition:
    def test_simple_comparison_passes(self):
        assert evaluate_condition("weight <= 0.25", {"weight": 0.20}) is True

    def test_simple_comparison_fails(self):
        assert evaluate_condition("weight <= 0.25", {"weight": 0.30}) is False

    def test_boolean_and(self):
        assert evaluate_condition(
            "weight <= 0.25 and count >= 5", {"weight": 0.20, "count": 10}
        ) is True

    def test_boolean_or(self):
        assert evaluate_condition(
            "weight <= 0.10 or count >= 5", {"weight": 0.20, "count": 10}
        ) is True

    def test_not_expression(self):
        assert evaluate_condition(
            "not (risk == 'high' and weight > 0.10)",
            {"risk": "high", "weight": 0.05},
        ) is True

    def test_in_operator(self):
        assert evaluate_condition(
            "symbol not in restricted",
            {"symbol": "AAPL", "restricted": ["XYZ", "ABC"]},
        ) is True

    def test_arithmetic(self):
        assert evaluate_condition("a + b <= 100", {"a": 40, "b": 50}) is True

    def test_rejects_function_calls(self):
        with pytest.raises(UnsafeExpressionError):
            evaluate_condition("print('hello')", {})

    def test_rejects_imports(self):
        with pytest.raises(UnsafeExpressionError):
            evaluate_condition("__import__('os')", {})

    def test_rejects_attribute_access(self):
        with pytest.raises(UnsafeExpressionError):
            evaluate_condition("obj.method()", {"obj": object()})


class TestRuleEngine:
    def _make_rule_set(self, rules: list[Rule]) -> RuleSet:
        return RuleSet(rules=rules, created_at=datetime.now(UTC))

    def test_all_rules_pass(self):
        engine = RuleEngine()
        rule_set = self._make_rule_set([
            Rule(
                name="max_position",
                description="Max 25%",
                category=RuleCategory.EXPOSURE_LIMIT,
                severity=RuleSeverity.HARD,
                condition="action_target_weight <= max_weight",
                parameters={"max_weight": 0.25},
            ),
        ])

        results = engine.evaluate_action(rule_set, {"action_target_weight": 0.15})
        assert len(results) == 1
        assert results[0].passed is True

    def test_hard_rule_violation(self):
        engine = RuleEngine()
        rule_set = self._make_rule_set([
            Rule(
                name="max_position",
                description="Max 25%",
                category=RuleCategory.EXPOSURE_LIMIT,
                severity=RuleSeverity.HARD,
                condition="action_target_weight <= max_weight",
                parameters={"max_weight": 0.25},
            ),
        ])

        results = engine.evaluate_action(rule_set, {"action_target_weight": 0.30})
        assert len(results) == 1
        assert results[0].passed is False
        assert results[0].severity == RuleSeverity.HARD

    def test_context_snapshot_captured(self):
        engine = RuleEngine()
        rule_set = self._make_rule_set([
            Rule(
                name="test",
                description="test",
                category=RuleCategory.RISK_CONSTRAINT,
                severity=RuleSeverity.SOFT,
                condition="x > 0",
                parameters={"threshold": 10},
            ),
        ])

        results = engine.evaluate_action(rule_set, {"x": 5})
        assert results[0].context_snapshot["x"] == 5
        assert results[0].context_snapshot["threshold"] == 10

    def test_disabled_rules_skipped(self):
        engine = RuleEngine()
        rule_set = self._make_rule_set([
            Rule(
                name="disabled_rule",
                description="Disabled",
                category=RuleCategory.REGULATORY,
                severity=RuleSeverity.HARD,
                condition="False",
                enabled=False,
            ),
        ])

        results = engine.evaluate_action(rule_set, {})
        assert len(results) == 0
