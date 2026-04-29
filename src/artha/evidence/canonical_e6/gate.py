"""§11.7.1 — E6 structural-flag gate (deterministic).

The gate reads I0 active-layer structural flags (capacity_trajectory,
intermediary_present, beneficiary_can_operate_current_structure) and decides
whether the proposed product can proceed:

  * PROCEED — clean for product evaluation.
  * EVALUATE_WITH_COUNTERFACTUAL — proceed but with elevated scrutiny;
    surface the model-portfolio counterfactual prominently.
  * SOFT_BLOCK — overridable with documented advisor rationale.
  * HARD_BLOCK — senior management escalation required.

Pass 10 ships the rule logic per §6.7 / §11.7.1 + tests 8/9/10. Pass 4's
`cat_ii_aif_structurally_appropriate` propagation contract feeds in here.
"""

from __future__ import annotations

from dataclasses import dataclass

from artha.canonical.investor import InvestorContextProfile
from artha.common.types import (
    CapacityTrajectory,
    GateResult,
    VehicleType,
)

# Vehicle types that count as AIF structural complexity for gate purposes.
_AIF_VEHICLES: frozenset[VehicleType] = frozenset(
    {VehicleType.AIF_CAT_1, VehicleType.AIF_CAT_2, VehicleType.AIF_CAT_3}
)

# Vehicles whose structural complexity warrants gate scrutiny.
_COMPLEX_VEHICLES: frozenset[VehicleType] = (
    _AIF_VEHICLES | {VehicleType.UNLISTED_EQUITY, VehicleType.SIF}
)


@dataclass(frozen=True)
class GateDecision:
    """Structured gate output: result + reasons + override path."""

    result: GateResult
    reasons: list[str]
    override_path: str  # "documented_advisor_rationale" / "senior_escalation" / "" for PROCEED


class E6Gate:
    """§11.7.1 deterministic structural-flag gate.

    Inputs at evaluation time:
      * `profile` — `InvestorContextProfile` carrying I0 active flags.
      * `vehicle_type` — proposed product vehicle.

    Output: a `GateDecision` whose `result` flows into `E6Verdict.gate_result`
    and whose `reasons` populate `E6Verdict.flags`.
    """

    def evaluate(
        self,
        profile: InvestorContextProfile,
        vehicle_type: VehicleType,
    ) -> GateDecision:
        """Apply the gate rules and return a structured decision."""
        reasons: list[str] = []

        # Rule 1: capacity_trajectory severely declining + AIF → HARD_BLOCK
        # (advisor cannot override unilaterally; senior escalation required).
        if (
            profile.capacity_trajectory == CapacityTrajectory.DECLINING_SEVERE
            and vehicle_type in _AIF_VEHICLES
        ):
            return GateDecision(
                result=GateResult.HARD_BLOCK,
                reasons=["capacity_trajectory_severely_declining"],
                override_path="senior_escalation",
            )

        # Rule 2: capacity_trajectory moderately declining + complex vehicle → SOFT_BLOCK
        if (
            profile.capacity_trajectory == CapacityTrajectory.DECLINING_MODERATE
            and vehicle_type in _COMPLEX_VEHICLES
        ):
            reasons.append("capacity_trajectory_declining")

        # Rule 3: beneficiary cannot operate current structure + AIF → SOFT_BLOCK
        if (
            not profile.beneficiary_can_operate_current_structure
            and vehicle_type in _AIF_VEHICLES
        ):
            reasons.append("beneficiary_agency_gap")

        # Rule 4: intermediary_present + complex vehicle → EVALUATE_WITH_COUNTERFACTUAL.
        # Per §6.5, the intermediary flag drives "conflict indicator on every
        # E6 verdict" but doesn't itself block. We surface as the milder gate
        # tier so A1's accountability surface (Pass 12) can audit the case.
        evaluate_with_counterfactual = (
            profile.intermediary_present and vehicle_type in _COMPLEX_VEHICLES
        )

        if reasons:
            return GateDecision(
                result=GateResult.SOFT_BLOCK,
                reasons=reasons,
                override_path="documented_advisor_rationale",
            )

        if evaluate_with_counterfactual:
            return GateDecision(
                result=GateResult.EVALUATE_WITH_COUNTERFACTUAL,
                reasons=["intermediary_present"],
                override_path="",
            )

        return GateDecision(result=GateResult.PROCEED, reasons=[], override_path="")
