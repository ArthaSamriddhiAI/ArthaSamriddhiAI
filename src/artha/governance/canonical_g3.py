"""§13.4 — G3 Action Permission Filter (deterministic aggregator).

G3 is pure aggregation logic over G1 + G2 outputs (and S1 escalation flag,
plus optional firm-policy escalations). Per §13.4.4:

  * Any BLOCKED in either G1 or G2 → permission = BLOCKED.
  * Any ESCALATION_REQUIRED without a BLOCK → permission = ESCALATION_REQUIRED.
  * S1.escalation_recommended also lifts to ESCALATION_REQUIRED if no BLOCK.
  * All APPROVED → permission = APPROVED.

Override paths (§13.4.5): firm policy may permit override on specific
constraint families (e.g. mandate breach with documented advisor rationale +
supervisor cosign). G3 surfaces the requirements; it does NOT execute the
override — the operator does.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from artha.canonical.case import CaseObject
from artha.canonical.governance import (
    ConstraintType,
    G1Evaluation,
    G2Evaluation,
    G3Evaluation,
    OverrideRequirements,
)
from artha.common.clock import get_clock
from artha.common.hashing import payload_hash
from artha.common.types import (
    InputsUsedManifest,
    Permission,
    RunMode,
)

logger = logging.getLogger(__name__)


# Default firm policy: which mandate-constraint families allow override with documented rationale.
_DEFAULT_OVERRIDABLE_CONSTRAINTS: frozenset[ConstraintType] = frozenset(
    {
        ConstraintType.ASSET_CLASS_LIMIT,
        ConstraintType.VEHICLE_LIMIT,
        ConstraintType.SUB_ASSET_CLASS_LIMIT,
        ConstraintType.SECTOR_EXCLUSION,
        ConstraintType.LIQUIDITY_FLOOR,
    }
)


class FirmPolicy(BaseModel):
    """§13.4.5 — firm-overridable inputs to G3.

    Pass 12 carries a small policy surface; future passes (Pass 13+) can wire
    deeper hooks (e.g. supervisor-cosign required for specific products).
    """

    model_config = ConfigDict(extra="forbid")

    overridable_mandate_constraints: list[ConstraintType] = Field(
        default_factory=lambda: list(_DEFAULT_OVERRIDABLE_CONSTRAINTS)
    )
    block_overridable_default: bool = True
    additional_escalation_signals: list[str] = Field(default_factory=list)


class ActionPermissionFilter:
    """§13.4 deterministic permission filter (G3)."""

    agent_id = "permission_filter"

    def __init__(
        self,
        *,
        firm_policy: FirmPolicy | None = None,
        agent_version: str = "0.1.0",
    ) -> None:
        self._firm_policy = firm_policy or FirmPolicy()
        self._agent_version = agent_version

    def evaluate(
        self,
        case: CaseObject,
        *,
        g1: G1Evaluation,
        g2: G2Evaluation,
        s1_escalation_recommended: bool = False,
        run_mode: RunMode = RunMode.CASE,
    ) -> G3Evaluation:
        """Aggregate G1 + G2 + S1 into a single permission verdict."""
        blocking: list[str] = []
        escalation: list[str] = []
        conditions: list[str] = []

        # ----- G1 contributions -----
        if g1.aggregated_status is Permission.BLOCKED:
            blocking.extend(f"g1:{r}" for r in g1.breach_reasons)
        if g1.aggregated_status is Permission.ESCALATION_REQUIRED:
            escalation.extend(f"g1:{r}" for r in g1.escalation_reasons)

        # ----- G2 contributions -----
        if g2.aggregated_permission is Permission.BLOCKED:
            blocking.extend(f"g2:{r}" for r in g2.blocking_reasons)
        if g2.aggregated_permission is Permission.ESCALATION_REQUIRED:
            escalation.extend(f"g2:{r}" for r in g2.escalation_reasons)

        # ----- S1 escalation -----
        if s1_escalation_recommended:
            escalation.append("s1:escalation_recommended")

        # ----- Firm-policy escalations -----
        for sig in self._firm_policy.additional_escalation_signals:
            escalation.append(f"firm_policy:{sig}")

        # ----- Aggregate -----
        if blocking:
            permission = Permission.BLOCKED
            override = self._build_override_requirements(g1, g2)
            # Conditions only meaningful on APPROVED — leave empty when BLOCKED.
        elif escalation:
            permission = Permission.ESCALATION_REQUIRED
            override = None
            # Surface escalation-driven conditions for advisor follow-through.
            conditions = [self._condition_for_escalation(r) for r in escalation]
        else:
            permission = Permission.APPROVED
            override = None
            conditions = []

        signals_input_for_hash = self._collect_input_for_hash(
            case=case,
            g1=g1,
            g2=g2,
            s1_escalation_recommended=s1_escalation_recommended,
        )
        manifest = self._build_inputs_used_manifest(signals_input_for_hash)

        return G3Evaluation(
            case_id=case.case_id,
            timestamp=get_clock().now(),
            run_mode=run_mode,
            permission=permission,
            blocking_reasons=blocking,
            escalation_reasons=escalation,
            override_requirements=override,
            conditions_to_attach=conditions,
            g1_input_hash=g1.input_hash,
            g2_input_hash=g2.input_hash,
            s1_escalation_recommended=s1_escalation_recommended,
            inputs_used_manifest=manifest,
            input_hash=payload_hash(signals_input_for_hash),
            agent_version=self._agent_version,
        )

    # --------------------- Helpers ----------------------------------

    def _build_override_requirements(
        self,
        g1: G1Evaluation,
        g2: G2Evaluation,
    ) -> OverrideRequirements:
        """Surface requirements when at least one breach is overridable."""
        overridable_set = set(self._firm_policy.overridable_mandate_constraints)
        overridable_breaches = [
            ev
            for ev in g1.per_constraint_evaluations
            if ev.constraint_type in overridable_set
            and ev.status.value == "breach"
        ]

        # G2 BLOCKs are regulatory — by default not overridable.
        regulatory_blocks = [r for r in g2.blocking_reasons]

        if not overridable_breaches:
            return OverrideRequirements(
                override_permitted=False,
                requires=[],
                rationale=(
                    "Override not permitted: regulatory blocks present"
                    if regulatory_blocks
                    else "Override not permitted: no overridable mandate breach"
                ),
            )

        if not self._firm_policy.block_overridable_default:
            return OverrideRequirements(
                override_permitted=False,
                requires=[],
                rationale="Firm policy disables overrides for mandate breaches",
            )

        if regulatory_blocks:
            return OverrideRequirements(
                override_permitted=False,
                requires=[],
                rationale=(
                    "Override not permitted: regulatory block in G2 supersedes "
                    "overridable mandate breach"
                ),
            )

        requires = [
            "documented_advisor_rationale",
            "supervisor_cosign",
        ]
        # If any breach is asset-class or vehicle-limit, mandate amendment is the
        # cleaner route — surface as an alternative requirement.
        breach_types = {ev.constraint_type for ev in overridable_breaches}
        if (
            ConstraintType.ASSET_CLASS_LIMIT in breach_types
            or ConstraintType.VEHICLE_LIMIT in breach_types
        ):
            requires.append("mandate_amendment_alternative")

        return OverrideRequirements(
            override_permitted=True,
            requires=requires,
            rationale=(
                "Mandate breach is overridable per firm policy; documented "
                "rationale + supervisor cosign required."
            ),
        )

    def _condition_for_escalation(self, reason: str) -> str:
        """Map an escalation reason → a follow-through condition."""
        if reason.startswith("g1:"):
            return f"document_mandate_proximity_rationale:{reason[3:]}"
        if reason.startswith("g2:"):
            return f"satisfy_regulatory_requirement:{reason[3:]}"
        if reason.startswith("s1:"):
            return "human_advisor_review_synthesis_uncertainty"
        if reason.startswith("firm_policy:"):
            return f"firm_policy_followthrough:{reason[len('firm_policy:'):]}"
        return f"address_escalation:{reason}"

    def _collect_input_for_hash(
        self,
        *,
        case: CaseObject,
        g1: G1Evaluation,
        g2: G2Evaluation,
        s1_escalation_recommended: bool,
    ) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "case_id": case.case_id,
            "g1_input_hash": g1.input_hash,
            "g2_input_hash": g2.input_hash,
            "s1_escalation_recommended": s1_escalation_recommended,
            "firm_policy": self._firm_policy.model_dump(mode="json"),
        }

    def _build_inputs_used_manifest(
        self, signals_input_for_hash: dict[str, Any]
    ) -> InputsUsedManifest:
        inputs_dict: dict[str, dict[str, str]] = {}
        for k, v in signals_input_for_hash.items():
            inputs_dict[k] = {"shape_hash": payload_hash(v) if v is not None else ""}
        return InputsUsedManifest(inputs=inputs_dict)


__all__ = ["ActionPermissionFilter", "FirmPolicy"]
