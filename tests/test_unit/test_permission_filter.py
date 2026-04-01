"""Tests for the permission filter."""

from __future__ import annotations

from artha.governance.agents.base import ProposedAction
from artha.governance.permissions.filter import PermissionFilter
from artha.governance.permissions.models import PermissionStatus
from artha.governance.rules.models import RuleEvaluation, RuleSeverity


class TestPermissionFilter:
    def test_all_pass_gives_approved(self):
        filt = PermissionFilter()
        action = ProposedAction(symbol="AAPL", action="buy", target_weight=0.10)
        evals = [
            RuleEvaluation(
                rule_id="r1", rule_name="Rule1", severity=RuleSeverity.HARD,
                passed=True, condition="x > 0",
            ),
        ]
        result = filt.evaluate("d1", [(action, evals)])
        assert result.overall_status == PermissionStatus.APPROVED
        assert not result.requires_human_approval

    def test_hard_violation_gives_rejected(self):
        filt = PermissionFilter()
        action = ProposedAction(symbol="AAPL", action="buy", target_weight=0.30)
        evals = [
            RuleEvaluation(
                rule_id="r1", rule_name="Rule1", severity=RuleSeverity.HARD,
                passed=False, condition="x <= 0.25", message="Exceeded limit",
            ),
        ]
        result = filt.evaluate("d1", [(action, evals)])
        assert result.overall_status == PermissionStatus.REJECTED

    def test_soft_violation_gives_escalation(self):
        filt = PermissionFilter()
        action = ProposedAction(symbol="AAPL", action="buy", target_weight=0.10)
        evals = [
            RuleEvaluation(
                rule_id="r1", rule_name="Rule1", severity=RuleSeverity.SOFT,
                passed=False, condition="count >= 5", message="Low diversification",
            ),
        ]
        result = filt.evaluate("d1", [(action, evals)])
        assert result.overall_status == PermissionStatus.ESCALATION_REQUIRED
        assert result.requires_human_approval

    def test_hard_overrides_soft(self):
        filt = PermissionFilter()
        action1 = ProposedAction(symbol="AAPL", action="buy", target_weight=0.10)
        evals1 = [
            RuleEvaluation(
                rule_id="r1", rule_name="Soft", severity=RuleSeverity.SOFT,
                passed=False, condition="", message="Soft fail",
            ),
        ]
        action2 = ProposedAction(symbol="MSFT", action="buy", target_weight=0.30)
        evals2 = [
            RuleEvaluation(
                rule_id="r2", rule_name="Hard", severity=RuleSeverity.HARD,
                passed=False, condition="", message="Hard fail",
            ),
        ]
        result = filt.evaluate("d1", [(action1, evals1), (action2, evals2)])
        assert result.overall_status == PermissionStatus.REJECTED
