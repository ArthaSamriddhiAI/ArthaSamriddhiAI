"""§13.3 — G2 Regulatory Boundary Engine (deterministic, time-aware).

G2 enforces SEBI / RBI / FEMA / tax rules from the curated knowledge corpus
against a `ProposedAction` + client context. Rules are time-aware:
`effective_from` / `effective_until` are first-class so a case decided on
2024-09-15 is evaluated against the rules in force on that date, not
today's rules. This makes T1 replay correct (§3.11).

Aggregation rule (§13.3.4):
  * Any BLOCK → aggregated BLOCKED.
  * Any ESCALATE_REQUIREMENT_UNMET without BLOCK → ESCALATION_REQUIRED.
  * All PASS → APPROVED.

Pass 12 ships the SEBI product-rule checks (minimum ticket size, maximum
concentration, documentation-required) and the GIFT-routing requirement
checks. RBI and FEMA depth ship in Pass 13+.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

from artha.canonical.case import CaseObject, ProposedAction
from artha.canonical.curated_knowledge import (
    CuratedKnowledgeSnapshot,
    GiftCityRoutingRequirement,
    GiftCityRoutingRule,
    ResidencyStatus,
    SebiProductRule,
)
from artha.canonical.governance import (
    G2Evaluation,
    RegulatoryRuleEvaluation,
    RegulatoryRuleSeverity,
    RegulatoryRuleStatus,
)
from artha.canonical.mandate import MandateObject
from artha.common.clock import get_clock
from artha.common.hashing import payload_hash
from artha.common.types import (
    InputsUsedManifest,
    Permission,
    RunMode,
    SourceCitation,
    SourceType,
    VehicleType,
)

logger = logging.getLogger(__name__)


class RegulatoryEngine:
    """§13.3 deterministic regulatory engine.

    `evaluate()` reads a `CuratedKnowledgeSnapshot` and produces a
    `G2Evaluation`. The engine never raises — it surfaces every
    rule outcome so the orchestrator can present a complete view.
    """

    agent_id = "regulatory_engine"

    def __init__(self, *, agent_version: str = "0.1.0") -> None:
        self._agent_version = agent_version

    def evaluate(
        self,
        case: CaseObject,
        snapshot: CuratedKnowledgeSnapshot,
        *,
        proposed_action: ProposedAction | None = None,
        residency: ResidencyStatus = ResidencyStatus.RESIDENT,
        product_domicile: str = "indian",
        mandate: MandateObject | None = None,
        decision_date: datetime | None = None,
        run_mode: RunMode = RunMode.CASE,
    ) -> G2Evaluation:
        """Run G2's rule corpus against the proposal at `decision_date`."""
        proposed_action = proposed_action or case.proposed_action
        decision_date = decision_date or case.created_at
        decision_date_only = decision_date.date()

        per_rule: list[RegulatoryRuleEvaluation] = []

        if proposed_action is not None and snapshot.sebi_rules is not None:
            per_rule.extend(
                self._eval_sebi_rules(
                    proposed_action, snapshot.sebi_rules.rules, decision_date_only
                )
            )

        if proposed_action is not None and snapshot.gift_city_rules is not None:
            per_rule.extend(
                self._eval_gift_routing_rules(
                    snapshot.gift_city_rules.rules,
                    residency,
                    product_domicile,
                )
            )

        # ----- Aggregate -----
        aggregated, blocking_reasons, escalation_reasons = self._aggregate(per_rule)

        signals_input_for_hash = self._collect_input_for_hash(
            case=case,
            snapshot=snapshot,
            proposed_action=proposed_action,
            residency=residency,
            product_domicile=product_domicile,
            mandate=mandate,
            decision_date=decision_date,
        )
        manifest = self._build_inputs_used_manifest(signals_input_for_hash)

        return G2Evaluation(
            case_id=case.case_id,
            timestamp=get_clock().now(),
            run_mode=run_mode,
            aggregated_permission=aggregated,
            per_rule_evaluations=per_rule,
            blocking_reasons=blocking_reasons,
            escalation_reasons=escalation_reasons,
            rule_corpus_version=snapshot.snapshot_version,
            decision_date=decision_date,
            inputs_used_manifest=manifest,
            input_hash=payload_hash(signals_input_for_hash),
            agent_version=self._agent_version,
        )

    # --------------------- Rule families ----------------------------

    def _eval_sebi_rules(
        self,
        proposed_action: ProposedAction,
        rules: list[SebiProductRule],
        decision_date: date,
    ) -> list[RegulatoryRuleEvaluation]:
        """Apply SEBI product rules in force on `decision_date`."""
        proposed_vehicle = self._proposed_vehicle(proposed_action)
        if proposed_vehicle is None:
            return []
        proposed_inr = float(proposed_action.ticket_size_inr) if (
            proposed_action.ticket_size_inr is not None
        ) else 0.0

        out: list[RegulatoryRuleEvaluation] = []
        for rule in rules:
            if not self._rule_in_force(rule.effective_from, rule.effective_until, decision_date):
                continue
            if rule.product_category != proposed_vehicle.value:
                continue

            citation = SourceCitation(
                source_type=SourceType.RULE,
                source_id=rule.rule_id,
                source_version=rule.effective_from.isoformat(),
            )

            # Minimum ticket size check.
            if rule.minimum_ticket_size_inr is not None:
                if proposed_inr <= 0:
                    out.append(
                        RegulatoryRuleEvaluation(
                            rule_id=rule.rule_id,
                            rule_version=rule.effective_from.isoformat(),
                            status=RegulatoryRuleStatus.ESCALATE_REQUIREMENT_UNMET,
                            severity=RegulatoryRuleSeverity.HARD,
                            citation=citation,
                            evaluation_detail=(
                                f"{rule.product_category}: ticket size missing for "
                                f"minimum-ticket rule check"
                            ),
                            requirement_unmet="ticket_size_required",
                        )
                    )
                    continue
                if proposed_inr < rule.minimum_ticket_size_inr:
                    out.append(
                        RegulatoryRuleEvaluation(
                            rule_id=rule.rule_id,
                            rule_version=rule.effective_from.isoformat(),
                            status=RegulatoryRuleStatus.BLOCK,
                            severity=RegulatoryRuleSeverity.HARD,
                            citation=citation,
                            evaluation_detail=(
                                f"{rule.product_category}: proposed ticket "
                                f"{proposed_inr:.0f} below SEBI minimum "
                                f"{rule.minimum_ticket_size_inr:.0f}"
                            ),
                        )
                    )
                else:
                    out.append(
                        RegulatoryRuleEvaluation(
                            rule_id=rule.rule_id,
                            rule_version=rule.effective_from.isoformat(),
                            status=RegulatoryRuleStatus.PASS,
                            severity=RegulatoryRuleSeverity.HARD,
                            citation=citation,
                            evaluation_detail=(
                                f"{rule.product_category}: ticket "
                                f"{proposed_inr:.0f} ≥ minimum "
                                f"{rule.minimum_ticket_size_inr:.0f}"
                            ),
                        )
                    )

            # Documentation-required: surface as ESCALATE_REQUIREMENT_UNMET so
            # the operator must produce evidence.
            for doc in rule.documentation_required:
                out.append(
                    RegulatoryRuleEvaluation(
                        rule_id=f"{rule.rule_id}#{doc}",
                        rule_version=rule.effective_from.isoformat(),
                        status=RegulatoryRuleStatus.ESCALATE_REQUIREMENT_UNMET,
                        severity=RegulatoryRuleSeverity.SOFT,
                        citation=citation,
                        evaluation_detail=(
                            f"{rule.product_category}: documentation required: {doc}"
                        ),
                        requirement_unmet=doc,
                    )
                )

        return out

    def _eval_gift_routing_rules(
        self,
        rules: list[GiftCityRoutingRule],
        residency: ResidencyStatus,
        product_domicile: str,
    ) -> list[RegulatoryRuleEvaluation]:
        """GIFT-City routing requirement check."""
        out: list[RegulatoryRuleEvaluation] = []
        for rule in rules:
            if rule.residency != residency:
                continue
            if rule.product_domicile != product_domicile:
                continue
            citation = SourceCitation(
                source_type=SourceType.RULE,
                source_id=f"GIFT_{rule.residency.value}_{rule.product_domicile}",
                source_version="snapshot",
            )

            if rule.requirement is GiftCityRoutingRequirement.UNAVAILABLE:
                out.append(
                    RegulatoryRuleEvaluation(
                        rule_id=citation.source_id,
                        rule_version=citation.source_version,
                        status=RegulatoryRuleStatus.BLOCK,
                        severity=RegulatoryRuleSeverity.HARD,
                        citation=citation,
                        evaluation_detail=(
                            f"GIFT routing for {residency.value} → {product_domicile}: "
                            f"unavailable; route={rule.route}"
                        ),
                    )
                )
            elif rule.requirement is GiftCityRoutingRequirement.REQUIRED:
                out.append(
                    RegulatoryRuleEvaluation(
                        rule_id=citation.source_id,
                        rule_version=citation.source_version,
                        status=RegulatoryRuleStatus.ESCALATE_REQUIREMENT_UNMET,
                        severity=RegulatoryRuleSeverity.HARD,
                        citation=citation,
                        evaluation_detail=(
                            f"GIFT routing for {residency.value} → {product_domicile}: "
                            f"required; mandatory route={rule.route}"
                        ),
                        requirement_unmet=f"route_{rule.route}",
                    )
                )
            else:  # OPTIONAL
                out.append(
                    RegulatoryRuleEvaluation(
                        rule_id=citation.source_id,
                        rule_version=citation.source_version,
                        status=RegulatoryRuleStatus.PASS,
                        severity=RegulatoryRuleSeverity.INFO,
                        citation=citation,
                        evaluation_detail=(
                            f"GIFT routing for {residency.value} → {product_domicile}: "
                            f"optional ({rule.route})"
                        ),
                    )
                )
        return out

    # --------------------- Aggregation ------------------------------

    def _aggregate(
        self, evaluations: list[RegulatoryRuleEvaluation]
    ) -> tuple[Permission, list[str], list[str]]:
        blocking: list[str] = []
        escalations: list[str] = []
        for ev in evaluations:
            if ev.status is RegulatoryRuleStatus.BLOCK:
                blocking.append(f"{ev.rule_id}: {ev.evaluation_detail}")
            elif ev.status is RegulatoryRuleStatus.ESCALATE_REQUIREMENT_UNMET:
                escalations.append(f"{ev.rule_id}: {ev.evaluation_detail}")

        if blocking:
            return Permission.BLOCKED, blocking, escalations
        if escalations:
            return Permission.ESCALATION_REQUIRED, [], escalations
        return Permission.APPROVED, [], []

    # --------------------- Helpers ----------------------------------

    def _proposed_vehicle(
        self, proposed_action: ProposedAction | None
    ) -> VehicleType | None:
        if proposed_action is None or not proposed_action.structure:
            return None
        try:
            return VehicleType(proposed_action.structure)
        except ValueError:
            return None

    def _rule_in_force(
        self,
        effective_from: date,
        effective_until: date | None,
        decision_date: date,
    ) -> bool:
        if decision_date < effective_from:
            return False
        if effective_until is not None and decision_date > effective_until:
            return False
        return True

    def _collect_input_for_hash(
        self,
        *,
        case: CaseObject,
        snapshot: CuratedKnowledgeSnapshot,
        proposed_action: ProposedAction | None,
        residency: ResidencyStatus,
        product_domicile: str,
        mandate: MandateObject | None,
        decision_date: datetime,
    ) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "case_id": case.case_id,
            "snapshot_version": snapshot.snapshot_version,
            "proposed_action": (
                proposed_action.model_dump(mode="json") if proposed_action else None
            ),
            "residency": residency.value,
            "product_domicile": product_domicile,
            "mandate_version": mandate.version if mandate else None,
            "decision_date": decision_date.isoformat(),
        }

    def _build_inputs_used_manifest(
        self, signals_input_for_hash: dict[str, Any]
    ) -> InputsUsedManifest:
        inputs_dict: dict[str, dict[str, str]] = {}
        for k, v in signals_input_for_hash.items():
            inputs_dict[k] = {"shape_hash": payload_hash(v) if v is not None else ""}
        return InputsUsedManifest(inputs=inputs_dict)


__all__ = ["RegulatoryEngine"]
