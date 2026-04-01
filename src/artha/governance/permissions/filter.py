"""Permissioning & action filter — maps rule evaluations to permission outcomes."""

from __future__ import annotations

from artha.governance.agents.base import ProposedAction
from artha.governance.permissions.models import (
    ActionPermission,
    PermissionOutcome,
    PermissionStatus,
)
from artha.governance.rules.models import RuleEvaluation, RuleSeverity


class PermissionFilter:
    """Transforms rule evaluations into permission outcomes.

    Logic:
    - Any HARD rule violation → REJECTED
    - Any SOFT rule violation → ESCALATION_REQUIRED
    - All rules pass → APPROVED
    """

    def evaluate(
        self,
        decision_id: str,
        actions_with_evaluations: list[tuple[ProposedAction, list[RuleEvaluation]]],
    ) -> PermissionOutcome:
        permissions: list[ActionPermission] = []

        for action, evaluations in actions_with_evaluations:
            hard_violations = [
                e for e in evaluations if not e.passed and e.severity == RuleSeverity.HARD
            ]
            soft_violations = [
                e for e in evaluations if not e.passed and e.severity == RuleSeverity.SOFT
            ]

            if hard_violations:
                status = PermissionStatus.REJECTED
                rejection_reasons = [e.message for e in hard_violations]
                escalation_reasons = []
            elif soft_violations:
                status = PermissionStatus.ESCALATION_REQUIRED
                rejection_reasons = []
                escalation_reasons = [e.message for e in soft_violations]
            else:
                status = PermissionStatus.APPROVED
                rejection_reasons = []
                escalation_reasons = []

            permissions.append(
                ActionPermission(
                    action=action,
                    status=status,
                    rule_evaluations=evaluations,
                    rejection_reasons=rejection_reasons,
                    escalation_reasons=escalation_reasons,
                )
            )

        # Determine overall status
        statuses = {p.status for p in permissions}
        if PermissionStatus.REJECTED in statuses:
            overall = PermissionStatus.REJECTED
        elif PermissionStatus.ESCALATION_REQUIRED in statuses:
            overall = PermissionStatus.ESCALATION_REQUIRED
        else:
            overall = PermissionStatus.APPROVED

        return PermissionOutcome(
            decision_id=decision_id,
            permissions=permissions,
            overall_status=overall,
            requires_human_approval=overall == PermissionStatus.ESCALATION_REQUIRED,
        )
