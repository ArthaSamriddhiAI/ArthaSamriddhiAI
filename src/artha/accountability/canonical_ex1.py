"""§13.9 — EX1 Exception Handler (deterministic routing).

EX1 is the system-wide exception router. Every component (E1–E6, S1, IC1,
M0.*, PM1, M1, etc.) calls EX1 when it can't fulfil its contract; EX1
deterministically maps `(component, exception_category, severity)` to a
`RoutingDecision` and emits an `EX1Event`.

Per §13.9.4 the routing rule table is versioned (`routing_rule_table_version`)
so replay reproduces the historical routing. Pass 13 ships the default table
(`_DEFAULT_ROUTING_TABLE`) — firms can supply overrides at construction time.

Cascade tracking (§13.9.6): EX1 carries `cascade_depth`. When a component
fails because its dependency failed, the caller passes `cascade_depth+1`.
At the configured threshold (`cascade_threshold`, default 3) EX1 escalates
to firm leadership regardless of the per-rule decision.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from artha.canonical.monitoring import (
    EX1Event,
    ExceptionCategory,
    ExceptionSeverity,
    N0Alert,
    N0AlertCategory,
    N0Originator,
    RoutingDecision,
)
from artha.common.clock import get_clock
from artha.common.hashing import payload_hash
from artha.common.types import (
    AlertTier,
    InputsUsedManifest,
)
from artha.common.ulid import new_ulid

logger = logging.getLogger(__name__)


# Default cascade depth above which EX1 escalates to firm leadership.
DEFAULT_CASCADE_THRESHOLD = 3
DEFAULT_ROUTING_TABLE_VERSION = "default-2026.04"


@dataclass(frozen=True)
class _RoutingKey:
    """Composite key for the routing table."""

    component_prefix: str  # "" matches any component; specific prefixes win
    category: ExceptionCategory
    severity: ExceptionSeverity


# Default routing table per §13.9.4.
# More-specific entries (longer component_prefix) win over wildcards.
_DEFAULT_ROUTING_TABLE: dict[_RoutingKey, RoutingDecision] = {
    # === input_data_missing ===
    _RoutingKey("", ExceptionCategory.INPUT_DATA_MISSING, ExceptionSeverity.INFO):
        RoutingDecision.LOG_AND_PROCEED_WITH_FLAG,
    _RoutingKey("", ExceptionCategory.INPUT_DATA_MISSING, ExceptionSeverity.WARNING):
        RoutingDecision.LOG_AND_PROCEED_WITH_FLAG,
    _RoutingKey("", ExceptionCategory.INPUT_DATA_MISSING, ExceptionSeverity.ERROR):
        RoutingDecision.ESCALATE_TO_ADVISOR,
    _RoutingKey("", ExceptionCategory.INPUT_DATA_MISSING, ExceptionSeverity.CRITICAL):
        RoutingDecision.ESCALATE_TO_COMPLIANCE,

    # === schema_violation ===
    _RoutingKey("", ExceptionCategory.SCHEMA_VIOLATION, ExceptionSeverity.INFO):
        RoutingDecision.RETRY_ONCE,
    _RoutingKey("", ExceptionCategory.SCHEMA_VIOLATION, ExceptionSeverity.WARNING):
        RoutingDecision.RETRY_ONCE,
    _RoutingKey("", ExceptionCategory.SCHEMA_VIOLATION, ExceptionSeverity.ERROR):
        RoutingDecision.FALLBACK_TO_PRIOR_VERSION,
    _RoutingKey("", ExceptionCategory.SCHEMA_VIOLATION, ExceptionSeverity.CRITICAL):
        RoutingDecision.ESCALATE_TO_COMPLIANCE,

    # === service_unavailable ===
    _RoutingKey("", ExceptionCategory.SERVICE_UNAVAILABLE, ExceptionSeverity.INFO):
        RoutingDecision.LOG_AND_PROCEED_WITH_FLAG,
    _RoutingKey("", ExceptionCategory.SERVICE_UNAVAILABLE, ExceptionSeverity.WARNING):
        RoutingDecision.LOG_AND_PROCEED_WITH_FLAG,
    _RoutingKey("", ExceptionCategory.SERVICE_UNAVAILABLE, ExceptionSeverity.ERROR):
        RoutingDecision.ESCALATE_TO_ADVISOR,
    _RoutingKey("", ExceptionCategory.SERVICE_UNAVAILABLE, ExceptionSeverity.CRITICAL):
        RoutingDecision.ESCALATE_TO_FIRM_LEADERSHIP,
    # E2 → cached snapshot acceptable on service_unavailable up to ERROR
    _RoutingKey("e2", ExceptionCategory.SERVICE_UNAVAILABLE, ExceptionSeverity.ERROR):
        RoutingDecision.FALLBACK_TO_PRIOR_VERSION,
    # M0.Briefer → drop, never block
    _RoutingKey("m0.briefer", ExceptionCategory.SERVICE_UNAVAILABLE, ExceptionSeverity.WARNING):
        RoutingDecision.LOG_AND_PROCEED_WITH_FLAG,
    _RoutingKey("m0.briefer", ExceptionCategory.SERVICE_UNAVAILABLE, ExceptionSeverity.ERROR):
        RoutingDecision.LOG_AND_PROCEED_WITH_FLAG,

    # === component_conflict ===
    _RoutingKey("", ExceptionCategory.COMPONENT_CONFLICT, ExceptionSeverity.INFO):
        RoutingDecision.LOG_AND_PROCEED_WITH_FLAG,
    _RoutingKey("", ExceptionCategory.COMPONENT_CONFLICT, ExceptionSeverity.WARNING):
        RoutingDecision.ESCALATE_TO_ADVISOR,
    _RoutingKey("", ExceptionCategory.COMPONENT_CONFLICT, ExceptionSeverity.ERROR):
        RoutingDecision.ESCALATE_TO_COMPLIANCE,
    _RoutingKey("", ExceptionCategory.COMPONENT_CONFLICT, ExceptionSeverity.CRITICAL):
        RoutingDecision.ESCALATE_TO_COMPLIANCE,

    # === timeout ===
    _RoutingKey("", ExceptionCategory.TIMEOUT, ExceptionSeverity.INFO):
        RoutingDecision.RETRY_ONCE,
    _RoutingKey("", ExceptionCategory.TIMEOUT, ExceptionSeverity.WARNING):
        RoutingDecision.RETRY_ONCE,
    _RoutingKey("", ExceptionCategory.TIMEOUT, ExceptionSeverity.ERROR):
        RoutingDecision.FALLBACK_TO_PRIOR_VERSION,
    _RoutingKey("", ExceptionCategory.TIMEOUT, ExceptionSeverity.CRITICAL):
        RoutingDecision.ESCALATE_TO_ADVISOR,

    # === governance_rule_mismatch ===
    _RoutingKey("", ExceptionCategory.GOVERNANCE_RULE_MISMATCH, ExceptionSeverity.INFO):
        RoutingDecision.ESCALATE_TO_COMPLIANCE,
    _RoutingKey("", ExceptionCategory.GOVERNANCE_RULE_MISMATCH, ExceptionSeverity.WARNING):
        RoutingDecision.ESCALATE_TO_COMPLIANCE,
    _RoutingKey("", ExceptionCategory.GOVERNANCE_RULE_MISMATCH, ExceptionSeverity.ERROR):
        RoutingDecision.ESCALATE_TO_COMPLIANCE,
    _RoutingKey("", ExceptionCategory.GOVERNANCE_RULE_MISMATCH, ExceptionSeverity.CRITICAL):
        RoutingDecision.ESCALATE_TO_FIRM_LEADERSHIP,

    # === cascading_exception ===
    _RoutingKey("", ExceptionCategory.CASCADING_EXCEPTION, ExceptionSeverity.INFO):
        RoutingDecision.LOG_AND_PROCEED_WITH_FLAG,
    _RoutingKey("", ExceptionCategory.CASCADING_EXCEPTION, ExceptionSeverity.WARNING):
        RoutingDecision.ESCALATE_TO_ADVISOR,
    _RoutingKey("", ExceptionCategory.CASCADING_EXCEPTION, ExceptionSeverity.ERROR):
        RoutingDecision.ESCALATE_TO_SENIOR_ADVISOR,
    _RoutingKey("", ExceptionCategory.CASCADING_EXCEPTION, ExceptionSeverity.CRITICAL):
        RoutingDecision.ESCALATE_TO_FIRM_LEADERSHIP,
}


class ExceptionHandler:
    """§13.9 deterministic exception router.

    Construction:
      * `routing_table` — overrides the default table.
      * `cascade_threshold` — depth at which we escalate to firm leadership.
      * `routing_table_version` — version string captured on every event.
    """

    agent_id = "exception_handler"

    def __init__(
        self,
        *,
        routing_table: dict[_RoutingKey, RoutingDecision] | None = None,
        cascade_threshold: int = DEFAULT_CASCADE_THRESHOLD,
        routing_table_version: str = DEFAULT_ROUTING_TABLE_VERSION,
        agent_version: str = "0.1.0",
    ) -> None:
        self._table = dict(routing_table or _DEFAULT_ROUTING_TABLE)
        self._cascade_threshold = cascade_threshold
        self._routing_table_version = routing_table_version
        self._agent_version = agent_version

    # --------------------- Public API --------------------------------

    def route(
        self,
        *,
        firm_id: str,
        originating_component: str,
        exception_category: ExceptionCategory,
        severity: ExceptionSeverity,
        case_id: str | None = None,
        client_id: str | None = None,
        cascade_depth: int = 0,
        originating_event_id: str | None = None,
        rationale: str = "",
        flag_propagated: bool = False,
        escalation_target_id: str | None = None,
    ) -> tuple[EX1Event, N0Alert | None]:
        """Resolve the routing decision and emit an EX1Event (+ optional N0)."""
        decision = self._lookup_decision(
            originating_component, exception_category, severity
        )
        cascade_threshold_breached = cascade_depth >= self._cascade_threshold
        if cascade_threshold_breached:
            decision = RoutingDecision.ESCALATE_TO_FIRM_LEADERSHIP

        n0_alert = self._build_n0_alert(
            firm_id=firm_id,
            client_id=client_id,
            decision=decision,
            originating_component=originating_component,
            exception_category=exception_category,
            severity=severity,
            cascade_threshold_breached=cascade_threshold_breached,
        )

        input_bundle = {
            "agent_id": self.agent_id,
            "originating_component": originating_component,
            "originating_event_id": originating_event_id,
            "exception_category": exception_category.value,
            "severity": severity.value,
            "cascade_depth": cascade_depth,
            "routing_table_version": self._routing_table_version,
            "case_id": case_id,
            "client_id": client_id,
            "firm_id": firm_id,
        }

        event = EX1Event(
            event_id=new_ulid(),
            timestamp=self._now(),
            case_id=case_id,
            client_id=client_id,
            firm_id=firm_id,
            originating_component=originating_component,
            originating_event_id=originating_event_id,
            exception_category=exception_category,
            severity=severity,
            routing_decision=decision,
            flag_propagated=flag_propagated,
            escalation_target_id=escalation_target_id,
            cascade_depth=cascade_depth,
            cascade_threshold_breached=cascade_threshold_breached,
            routing_rule_table_version=self._routing_table_version,
            rationale=rationale,
            inputs_used_manifest=self._build_inputs_used_manifest(input_bundle),
            input_hash=payload_hash(input_bundle),
            agent_version=self._agent_version,
        )
        return event, n0_alert

    # --------------------- Helpers ----------------------------------

    def _lookup_decision(
        self,
        component: str,
        category: ExceptionCategory,
        severity: ExceptionSeverity,
    ) -> RoutingDecision:
        """Look up the most specific (component_prefix, category, severity) match.

        Tie-break: longer prefix wins. The "" (empty) prefix is the wildcard.
        """
        component_lower = component.lower()
        best: tuple[int, RoutingDecision] | None = None
        for key, decision in self._table.items():
            if key.category is not category or key.severity is not severity:
                continue
            prefix = key.component_prefix
            if prefix and not component_lower.startswith(prefix):
                continue
            length = len(prefix)
            if best is None or length > best[0]:
                best = (length, decision)
        if best is None:
            return RoutingDecision.LOG_AND_PROCEED_WITH_FLAG
        return best[1]

    def _build_n0_alert(
        self,
        *,
        firm_id: str,
        client_id: str | None,
        decision: RoutingDecision,
        originating_component: str,
        exception_category: ExceptionCategory,
        severity: ExceptionSeverity,
        cascade_threshold_breached: bool,
    ) -> N0Alert | None:
        # Only emit N0 for human-facing decisions.
        escalation_decisions = {
            RoutingDecision.ESCALATE_TO_ADVISOR,
            RoutingDecision.ESCALATE_TO_SENIOR_ADVISOR,
            RoutingDecision.ESCALATE_TO_COMPLIANCE,
            RoutingDecision.ESCALATE_TO_FIRM_LEADERSHIP,
        }
        if decision not in escalation_decisions:
            return None

        tier = AlertTier.MUST_RESPOND if (
            cascade_threshold_breached
            or severity is ExceptionSeverity.CRITICAL
            or decision is RoutingDecision.ESCALATE_TO_FIRM_LEADERSHIP
        ) else AlertTier.SHOULD_RESPOND

        return N0Alert(
            alert_id=new_ulid(),
            originator=N0Originator.EX1,
            tier=tier,
            category=N0AlertCategory.EXCEPTION,
            client_id=client_id or "",
            firm_id=firm_id,
            created_at=self._now(),
            title=f"Exception: {originating_component} {exception_category.value}",
            body=(
                f"severity={severity.value} routing={decision.value} "
                f"cascade_threshold_breached={cascade_threshold_breached}"
            ),
            expected_action=f"Address per routing decision: {decision.value}.",
        )

    def _build_inputs_used_manifest(
        self, signals_input_for_hash: dict[str, Any]
    ) -> InputsUsedManifest:
        inputs_dict: dict[str, dict[str, str]] = {}
        for k, v in signals_input_for_hash.items():
            inputs_dict[k] = {"shape_hash": payload_hash(v) if v is not None else ""}
        return InputsUsedManifest(inputs=inputs_dict)

    def _now(self) -> datetime:
        return get_clock().now()


__all__ = [
    "DEFAULT_CASCADE_THRESHOLD",
    "DEFAULT_ROUTING_TABLE_VERSION",
    "ExceptionHandler",
]
