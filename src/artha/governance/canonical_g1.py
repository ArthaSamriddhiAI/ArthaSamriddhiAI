"""§7.3 / §13.2 — G1 Mandate Compliance Gate (deterministic).

G1 enforces the mandate boundaries against a `ProposedAction` + current
portfolio state. Per §7.3 the gate is 100% deterministic — same inputs
always yield the same output across runs and replays.

Constraint families (§7.3.2):
  * asset-class limits (target / min / max per L1)
  * vehicle limits (allowed / max share per VehicleType)
  * sub-asset-class limits
  * concentration limits (per-holding / per-manager / per-sector)
  * sector hard-blocks + sector exclusions
  * liquidity floor + liquidity windows
  * family-member overrides (per `FamilyMemberOverrideMandate`)

Aggregation rule (§7.10 Tests 2/3):
  * Any BREACH → BLOCKED.
  * Any WARN (within proximity threshold) → ESCALATION_REQUIRED.
  * All PASS → APPROVED.

The proximity threshold defaults to 10% of the limit (configurable per firm
per §7.3). Tests 1, 2, 3, 4, 6 ship in Pass 12. Tests 5/7/8/9/10 (drift
monitor / amendment cascade / N0 priority) ship in Pass 13.
"""

from __future__ import annotations

import logging
from typing import Any

from artha.canonical.case import CaseObject, ProposedAction
from artha.canonical.governance import (
    ConstraintEvaluation,
    ConstraintEvaluationStatus,
    ConstraintType,
    G1Evaluation,
)
from artha.canonical.holding import Holding
from artha.canonical.mandate import (
    AssetClassLimits,
    FamilyMemberOverrideMandate,
    MandateObject,
    VehicleLimits,
)
from artha.common.clock import get_clock
from artha.common.hashing import payload_hash
from artha.common.types import (
    AssetClass,
    InputsUsedManifest,
    Permission,
    RunMode,
    VehicleType,
)

logger = logging.getLogger(__name__)


# Default proximity threshold for ESCALATION_REQUIRED (§7.3 — within 10% of the limit).
DEFAULT_ESCALATION_PROXIMITY: float = 0.10


class MandateComplianceGate:
    """§7.3 deterministic mandate compliance gate.

    Construction:
      * `escalation_proximity` — fraction of the limit within which we WARN
        (default 10%); firm-overridable per §7.3.

    `evaluate()` returns a `G1Evaluation` populated from per-constraint
    evaluations and aggregated `Permission`. The gate never raises — it
    surfaces every breach and warning so the orchestrator can present
    everything to the human.
    """

    agent_id = "mandate_compliance"

    def __init__(
        self,
        *,
        escalation_proximity: float = DEFAULT_ESCALATION_PROXIMITY,
        agent_version: str = "0.1.0",
    ) -> None:
        self._escalation_proximity = escalation_proximity
        self._agent_version = agent_version

    # --------------------- Public API --------------------------------

    def evaluate(
        self,
        case: CaseObject,
        mandate: MandateObject,
        *,
        proposed_action: ProposedAction | None = None,
        current_holdings: list[Holding] | None = None,
        current_aum_inr: float | None = None,
        family_member_id: str | None = None,
        run_mode: RunMode = RunMode.CASE,
    ) -> G1Evaluation:
        """Run G1's deterministic checklist."""
        proposed_action = proposed_action or case.proposed_action
        current_holdings = current_holdings or []
        if current_aum_inr is None:
            current_aum_inr = sum(h.market_value for h in current_holdings)

        # Resolve family-member override if applicable.
        override = self._resolve_family_override(mandate, family_member_id)

        per_constraint: list[ConstraintEvaluation] = []

        # 1) Asset-class limits.
        per_constraint.extend(
            self._eval_asset_class_limits(
                proposed_action,
                mandate,
                current_holdings,
                current_aum_inr,
                override,
            )
        )

        # 2) Vehicle limits.
        per_constraint.extend(
            self._eval_vehicle_limits(
                proposed_action,
                mandate,
                current_holdings,
                current_aum_inr,
                override,
            )
        )

        # 3) Concentration (per-holding only at gate; per-manager / per-sector
        # require analytics signals — surfaced when supplied via current_holdings).
        if mandate.concentration_limits is not None and proposed_action is not None:
            per_constraint.extend(
                self._eval_concentration_limits(
                    proposed_action,
                    mandate,
                    current_holdings,
                    current_aum_inr,
                )
            )

        # 4) Sector hard-blocks (always BREACH if hit).
        per_constraint.extend(self._eval_sector_blocks(proposed_action, mandate))

        # 5) Liquidity floor — surfaces only when caller provides an explicit
        # most-liquid-share signal via `case.routing_metadata` ("most_liquid_share").
        per_constraint.extend(self._eval_liquidity_floor(case, mandate))

        # ----- Aggregate -----
        aggregated, breach_reasons, escalation_reasons = self._aggregate(per_constraint)

        signals_input_for_hash = self._collect_input_for_hash(
            case=case,
            mandate=mandate,
            proposed_action=proposed_action,
            holdings=current_holdings,
            current_aum_inr=current_aum_inr,
            family_member_id=family_member_id,
        )
        manifest = self._build_inputs_used_manifest(signals_input_for_hash)

        return G1Evaluation(
            case_id=case.case_id,
            timestamp=get_clock().now(),
            run_mode=run_mode,
            aggregated_status=aggregated,
            per_constraint_evaluations=per_constraint,
            breach_reasons=breach_reasons,
            escalation_reasons=escalation_reasons,
            mandate_version=mandate.version,
            inputs_used_manifest=manifest,
            input_hash=payload_hash(signals_input_for_hash),
            agent_version=self._agent_version,
        )

    # --------------------- Constraint evaluations -------------------

    def _resolve_family_override(
        self,
        mandate: MandateObject,
        family_member_id: str | None,
    ) -> FamilyMemberOverrideMandate | None:
        if family_member_id is None:
            return None
        for override in mandate.family_overrides:
            if override.member_id == family_member_id:
                return override
        return None

    def _eval_asset_class_limits(
        self,
        proposed_action: ProposedAction | None,
        mandate: MandateObject,
        holdings: list[Holding],
        current_aum_inr: float,
        override: FamilyMemberOverrideMandate | None,
    ) -> list[ConstraintEvaluation]:
        evaluations: list[ConstraintEvaluation] = []
        proposed_asset_class = self._guess_asset_class_from_action(proposed_action)
        proposed_inr = float(proposed_action.ticket_size_inr) if (
            proposed_action and proposed_action.ticket_size_inr is not None
        ) else 0.0

        # Effective AUM after the proposal (for capping share calculations).
        post_aum = max(current_aum_inr + proposed_inr, 1.0)

        for asset_class, limits in mandate.asset_class_limits.items():
            current_share = self._asset_class_share(holdings, asset_class, current_aum_inr)
            proposed_share = current_share
            if proposed_asset_class is asset_class and proposed_inr > 0:
                # Add proposed exposure to numerator and denominator.
                proposed_share = (
                    current_share * current_aum_inr + proposed_inr
                ) / post_aum

            applied_limits = self._apply_asset_class_override(limits, override, asset_class)
            status = self._classify_share(proposed_share, applied_limits)

            ev = ConstraintEvaluation(
                constraint_id=f"asset_class_limit:{asset_class.value}",
                constraint_type=ConstraintType.ASSET_CLASS_LIMIT,
                status=status,
                current_value=current_share,
                proposed_value=proposed_share,
                limit_value=applied_limits.max_pct,
                family_member_id=override.member_id if override else None,
                citation=f"mandate_v{mandate.version}",
                evaluation_detail=(
                    f"asset_class={asset_class.value}: "
                    f"current={current_share:.4f} → proposed={proposed_share:.4f} "
                    f"vs [{applied_limits.min_pct:.4f}, {applied_limits.max_pct:.4f}]"
                ),
            )
            evaluations.append(ev)

        return evaluations

    def _eval_vehicle_limits(
        self,
        proposed_action: ProposedAction | None,
        mandate: MandateObject,
        holdings: list[Holding],
        current_aum_inr: float,
        override: FamilyMemberOverrideMandate | None,
    ) -> list[ConstraintEvaluation]:
        evaluations: list[ConstraintEvaluation] = []
        proposed_vehicle = self._proposed_vehicle(proposed_action)
        proposed_inr = float(proposed_action.ticket_size_inr) if (
            proposed_action and proposed_action.ticket_size_inr is not None
        ) else 0.0
        post_aum = max(current_aum_inr + proposed_inr, 1.0)

        for vehicle_type, limits in mandate.vehicle_limits.items():
            current_share = self._vehicle_share(holdings, vehicle_type, current_aum_inr)
            proposed_share = current_share
            if proposed_vehicle is vehicle_type and proposed_inr > 0:
                proposed_share = (
                    current_share * current_aum_inr + proposed_inr
                ) / post_aum

            applied_limits = self._apply_vehicle_override(limits, override, vehicle_type)
            if not applied_limits.allowed:
                if (
                    (proposed_vehicle is vehicle_type and proposed_inr > 0)
                    or current_share > 0.0
                ):
                    evaluations.append(
                        ConstraintEvaluation(
                            constraint_id=f"vehicle_limit:{vehicle_type.value}",
                            constraint_type=ConstraintType.VEHICLE_LIMIT,
                            status=ConstraintEvaluationStatus.BREACH,
                            current_value=current_share,
                            proposed_value=proposed_share,
                            limit_value=0.0,
                            family_member_id=override.member_id if override else None,
                            citation=f"mandate_v{mandate.version}",
                            evaluation_detail=(
                                f"vehicle={vehicle_type.value} not allowed; "
                                f"proposed_share={proposed_share:.4f}"
                            ),
                        )
                    )
                continue

            max_pct = applied_limits.max_pct
            if max_pct is None:
                continue  # no cap

            status = self._classify_share_against_max(proposed_share, max_pct)
            evaluations.append(
                ConstraintEvaluation(
                    constraint_id=f"vehicle_limit:{vehicle_type.value}",
                    constraint_type=ConstraintType.VEHICLE_LIMIT,
                    status=status,
                    current_value=current_share,
                    proposed_value=proposed_share,
                    limit_value=max_pct,
                    family_member_id=override.member_id if override else None,
                    citation=f"mandate_v{mandate.version}",
                    evaluation_detail=(
                        f"vehicle={vehicle_type.value}: "
                        f"current={current_share:.4f} → proposed={proposed_share:.4f} "
                        f"vs max={max_pct:.4f}"
                    ),
                )
            )
        return evaluations

    def _eval_concentration_limits(
        self,
        proposed_action: ProposedAction,
        mandate: MandateObject,
        holdings: list[Holding],
        current_aum_inr: float,
    ) -> list[ConstraintEvaluation]:
        evaluations: list[ConstraintEvaluation] = []
        if mandate.concentration_limits is None:
            return evaluations

        per_holding_max = mandate.concentration_limits.per_holding_max
        proposed_inr = float(proposed_action.ticket_size_inr) if (
            proposed_action.ticket_size_inr is not None
        ) else 0.0
        post_aum = max(current_aum_inr + proposed_inr, 1.0)

        if proposed_inr <= 0:
            return evaluations

        proposed_share = proposed_inr / post_aum
        status = self._classify_share_against_max(proposed_share, per_holding_max)
        evaluations.append(
            ConstraintEvaluation(
                constraint_id="concentration:per_holding",
                constraint_type=ConstraintType.CONCENTRATION_LIMIT,
                status=status,
                current_value=0.0,
                proposed_value=proposed_share,
                limit_value=per_holding_max,
                citation=f"mandate_v{mandate.version}",
                evaluation_detail=(
                    f"per_holding share post-trade = {proposed_share:.4f} "
                    f"vs cap {per_holding_max:.4f}"
                ),
            )
        )
        return evaluations

    def _eval_sector_blocks(
        self,
        proposed_action: ProposedAction | None,
        mandate: MandateObject,
    ) -> list[ConstraintEvaluation]:
        if proposed_action is None:
            return []
        target = (proposed_action.target_product or "").lower()
        evaluations: list[ConstraintEvaluation] = []

        for sector in mandate.sector_hard_blocks:
            if sector.lower() in target:
                evaluations.append(
                    ConstraintEvaluation(
                        constraint_id=f"sector_hard_block:{sector}",
                        constraint_type=ConstraintType.SECTOR_HARD_BLOCK,
                        status=ConstraintEvaluationStatus.BREACH,
                        citation=f"mandate_v{mandate.version}",
                        evaluation_detail=(
                            f"target product '{proposed_action.target_product}' "
                            f"matches hard-blocked sector '{sector}'"
                        ),
                    )
                )

        for sector in mandate.sector_exclusions:
            if sector.lower() in target:
                evaluations.append(
                    ConstraintEvaluation(
                        constraint_id=f"sector_exclusion:{sector}",
                        constraint_type=ConstraintType.SECTOR_EXCLUSION,
                        status=ConstraintEvaluationStatus.WARN,
                        citation=f"mandate_v{mandate.version}",
                        evaluation_detail=(
                            f"target product '{proposed_action.target_product}' "
                            f"matches sector exclusion '{sector}' (warn)"
                        ),
                    )
                )

        return evaluations

    def _eval_liquidity_floor(
        self,
        case: CaseObject,
        mandate: MandateObject,
    ) -> list[ConstraintEvaluation]:
        # Caller may stash the most-liquid-bucket share in routing_metadata.
        most_liquid_share = case.routing_metadata.get("most_liquid_share")
        if most_liquid_share is None:
            return []
        try:
            share = float(most_liquid_share)
        except (TypeError, ValueError):
            return []

        floor = mandate.liquidity_floor
        proximity_band = floor * (1.0 + self._escalation_proximity)
        if share + 1e-9 < floor:
            status = ConstraintEvaluationStatus.BREACH
        elif share < proximity_band:
            status = ConstraintEvaluationStatus.WARN
        else:
            status = ConstraintEvaluationStatus.PASS

        return [
            ConstraintEvaluation(
                constraint_id="liquidity_floor",
                constraint_type=ConstraintType.LIQUIDITY_FLOOR,
                status=status,
                current_value=share,
                limit_value=floor,
                citation=f"mandate_v{mandate.version}",
                evaluation_detail=(
                    f"most_liquid_share={share:.4f} vs floor {floor:.4f}"
                ),
            )
        ]

    # --------------------- Aggregation ------------------------------

    def _aggregate(
        self, evaluations: list[ConstraintEvaluation]
    ) -> tuple[Permission, list[str], list[str]]:
        breach_reasons: list[str] = []
        escalation_reasons: list[str] = []

        for ev in evaluations:
            if ev.status is ConstraintEvaluationStatus.BREACH:
                breach_reasons.append(f"{ev.constraint_id}: {ev.evaluation_detail}")
            elif ev.status is ConstraintEvaluationStatus.WARN:
                escalation_reasons.append(f"{ev.constraint_id}: {ev.evaluation_detail}")

        if breach_reasons:
            return Permission.BLOCKED, breach_reasons, escalation_reasons
        if escalation_reasons:
            return Permission.ESCALATION_REQUIRED, [], escalation_reasons
        return Permission.APPROVED, [], []

    # --------------------- Helpers ----------------------------------

    def _classify_share(
        self, share: float, limits: AssetClassLimits
    ) -> ConstraintEvaluationStatus:
        proximity = self._escalation_proximity
        # Lower side
        if share + 1e-9 < limits.min_pct:
            # Below min — proximity check uses proportional gap to min.
            if abs(share - limits.min_pct) <= limits.min_pct * proximity:
                return ConstraintEvaluationStatus.WARN
            return ConstraintEvaluationStatus.BREACH
        # Upper side
        if share > limits.max_pct + 1e-9:
            return ConstraintEvaluationStatus.BREACH
        if share > limits.max_pct * (1.0 - proximity):
            return ConstraintEvaluationStatus.WARN
        return ConstraintEvaluationStatus.PASS

    def _classify_share_against_max(
        self, share: float, max_pct: float
    ) -> ConstraintEvaluationStatus:
        proximity = self._escalation_proximity
        if share > max_pct + 1e-9:
            return ConstraintEvaluationStatus.BREACH
        if share > max_pct * (1.0 - proximity):
            return ConstraintEvaluationStatus.WARN
        return ConstraintEvaluationStatus.PASS

    def _asset_class_share(
        self, holdings: list[Holding], asset_class: AssetClass, current_aum_inr: float
    ) -> float:
        if current_aum_inr <= 0:
            return 0.0
        total = sum(h.market_value for h in holdings if h.asset_class is asset_class)
        return total / current_aum_inr

    def _vehicle_share(
        self, holdings: list[Holding], vehicle: VehicleType, current_aum_inr: float
    ) -> float:
        if current_aum_inr <= 0:
            return 0.0
        total = sum(h.market_value for h in holdings if h.vehicle_type is vehicle)
        return total / current_aum_inr

    def _proposed_vehicle(
        self, proposed_action: ProposedAction | None
    ) -> VehicleType | None:
        if proposed_action is None or not proposed_action.structure:
            return None
        try:
            return VehicleType(proposed_action.structure)
        except ValueError:
            return None

    def _guess_asset_class_from_action(
        self, proposed_action: ProposedAction | None
    ) -> AssetClass | None:
        """Best-effort mapping from proposed vehicle → asset class.

        Pass 12 carries a small static map; production wires this through L4
        manifest lookup so the mapping reflects the actual instrument.
        """
        vehicle = self._proposed_vehicle(proposed_action)
        if vehicle is None:
            return None
        equity_vehicles = {
            VehicleType.DIRECT_EQUITY,
            VehicleType.UNLISTED_EQUITY,
            VehicleType.PMS,
            VehicleType.AIF_CAT_3,
        }
        if vehicle in equity_vehicles:
            return AssetClass.EQUITY
        debt_vehicles = {
            VehicleType.DEBT_DIRECT,
            VehicleType.FD,
            VehicleType.AIF_CAT_2,
        }
        if vehicle in debt_vehicles:
            return AssetClass.DEBT
        if vehicle in {VehicleType.GOLD}:
            return AssetClass.GOLD_COMMODITIES
        if vehicle in {VehicleType.REIT, VehicleType.INVIT}:
            return AssetClass.REAL_ASSETS
        if vehicle is VehicleType.CASH:
            return AssetClass.CASH
        return None

    def _apply_asset_class_override(
        self,
        limits: AssetClassLimits,
        override: FamilyMemberOverrideMandate | None,
        asset_class: AssetClass,
    ) -> AssetClassLimits:
        if override is None:
            return limits
        key = f"asset_class_limits.{asset_class.value}"
        override_block = override.override_fields.get(key)
        if not isinstance(override_block, dict):
            return limits
        return AssetClassLimits(
            min_pct=float(override_block.get("min_pct", limits.min_pct)),
            target_pct=float(override_block.get("target_pct", limits.target_pct)),
            max_pct=float(override_block.get("max_pct", limits.max_pct)),
        )

    def _apply_vehicle_override(
        self,
        limits: VehicleLimits,
        override: FamilyMemberOverrideMandate | None,
        vehicle: VehicleType,
    ) -> VehicleLimits:
        if override is None:
            return limits
        key = f"vehicle_limits.{vehicle.value}"
        override_block = override.override_fields.get(key)
        if not isinstance(override_block, dict):
            return limits
        return VehicleLimits(
            allowed=bool(override_block.get("allowed", limits.allowed)),
            min_pct=override_block.get("min_pct", limits.min_pct),
            max_pct=override_block.get("max_pct", limits.max_pct),
        )

    def _collect_input_for_hash(
        self,
        *,
        case: CaseObject,
        mandate: MandateObject,
        proposed_action: ProposedAction | None,
        holdings: list[Holding],
        current_aum_inr: float,
        family_member_id: str | None,
    ) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "case_id": case.case_id,
            "mandate_id": mandate.mandate_id,
            "mandate_version": mandate.version,
            "proposed_action": (
                proposed_action.model_dump(mode="json") if proposed_action else None
            ),
            "holdings_hashes": sorted(
                f"{h.instrument_id}:{h.market_value:.2f}" for h in holdings
            ),
            "current_aum_inr": round(current_aum_inr, 2),
            "family_member_id": family_member_id,
            "escalation_proximity": self._escalation_proximity,
        }

    def _build_inputs_used_manifest(
        self, signals_input_for_hash: dict[str, Any]
    ) -> InputsUsedManifest:
        inputs_dict: dict[str, dict[str, str]] = {}
        for k, v in signals_input_for_hash.items():
            inputs_dict[k] = {"shape_hash": payload_hash(v) if v is not None else ""}
        return InputsUsedManifest(inputs=inputs_dict)


__all__ = [
    "DEFAULT_ESCALATION_PROXIMITY",
    "MandateComplianceGate",
]
