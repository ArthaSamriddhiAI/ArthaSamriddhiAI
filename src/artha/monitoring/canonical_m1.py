"""§7.7 — M1 Mandate Drift Monitor (deterministic daily sweep).

M1 is the *background* mandate-monitor that scans current portfolio state
against the active mandate at a configurable cadence (daily by default).
G1 is the case-time mandate-compliance gate; M1 catches breaches that
emerge between cases as portfolio values shift OR when a mandate amendment
re-pegs the boundaries.

Per §7.10 Tests 5/9/10:
  * Test 5 — M1 catches new breach (e.g. liquidity falls below floor) within
    one daily cycle and emits a MUST_RESPOND N0 alert.
  * Test 9 — when both mandate breach AND model drift coexist, mandate breach
    is prioritised (M1's MUST_RESPOND tier overrides PM1's SHOULD_RESPOND).
  * Test 10 — out-of-bucket flag triggers single-client construction.

M1 reuses the constraint-evaluation logic from G1 conceptually but operates
on the *current state* (no proposed action) and emits an `M1DriftReport`
plus a list of `N0Alert` records.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

from artha.canonical.holding import Holding
from artha.canonical.mandate import MandateObject
from artha.canonical.monitoring import (
    M1Breach,
    M1BreachType,
    M1DriftReport,
    N0Alert,
    N0AlertCategory,
    N0Originator,
)
from artha.common.clock import get_clock
from artha.common.hashing import payload_hash
from artha.common.types import (
    AlertTier,
    AssetClass,
    InputsUsedManifest,
    VehicleType,
)
from artha.common.ulid import new_ulid

logger = logging.getLogger(__name__)


class MandateDriftMonitor:
    """§7.7 deterministic mandate-drift monitor.

    `sweep()` returns an `M1DriftReport` for the given client and emits N0
    alerts (returned alongside) for each breach. The orchestrator persists
    both via T1 and the N0 channel.
    """

    agent_id = "mandate_drift_monitor"

    def __init__(
        self,
        *,
        agent_version: str = "0.1.0",
    ) -> None:
        self._agent_version = agent_version

    # --------------------- Public API --------------------------------

    def sweep(
        self,
        *,
        client_id: str,
        firm_id: str,
        mandate: MandateObject,
        holdings: list[Holding],
        most_liquid_share: float | None = None,
        out_of_bucket_flag: bool = False,
        sweep_date: date | None = None,
    ) -> tuple[M1DriftReport, list[N0Alert]]:
        """Run M1's daily sweep on the current state."""
        sweep_date = sweep_date or self._now().date()
        breaches: list[M1Breach] = []

        current_aum_inr = sum(h.market_value for h in holdings)

        # ----- Asset-class limits (ceiling + floor) -----
        for asset_class, limits in mandate.asset_class_limits.items():
            share = self._asset_class_share(holdings, asset_class, current_aum_inr)
            if share > limits.max_pct + 1e-9:
                breaches.append(
                    M1Breach(
                        breach_type=M1BreachType.ASSET_CLASS_CEILING,
                        constraint_id=f"asset_class_limit:{asset_class.value}",
                        current_value=share,
                        limit_value=limits.max_pct,
                        breach_magnitude=share - limits.max_pct,
                        description=(
                            f"asset_class={asset_class.value} share={share:.4f} > "
                            f"max={limits.max_pct:.4f}"
                        ),
                    )
                )
            elif share + 1e-9 < limits.min_pct:
                breaches.append(
                    M1Breach(
                        breach_type=M1BreachType.ASSET_CLASS_FLOOR,
                        constraint_id=f"asset_class_limit:{asset_class.value}",
                        current_value=share,
                        limit_value=limits.min_pct,
                        breach_magnitude=limits.min_pct - share,
                        description=(
                            f"asset_class={asset_class.value} share={share:.4f} < "
                            f"min={limits.min_pct:.4f}"
                        ),
                    )
                )

        # ----- Vehicle limits -----
        for vehicle_type, limits in mandate.vehicle_limits.items():
            share = self._vehicle_share(holdings, vehicle_type, current_aum_inr)
            if not limits.allowed and share > 0.0:
                breaches.append(
                    M1Breach(
                        breach_type=M1BreachType.VEHICLE_LIMIT,
                        constraint_id=f"vehicle_limit:{vehicle_type.value}",
                        current_value=share,
                        limit_value=0.0,
                        breach_magnitude=share,
                        description=(
                            f"vehicle={vehicle_type.value} not allowed; "
                            f"current_share={share:.4f}"
                        ),
                    )
                )
            elif limits.max_pct is not None and share > limits.max_pct + 1e-9:
                breaches.append(
                    M1Breach(
                        breach_type=M1BreachType.VEHICLE_LIMIT,
                        constraint_id=f"vehicle_limit:{vehicle_type.value}",
                        current_value=share,
                        limit_value=limits.max_pct,
                        breach_magnitude=share - limits.max_pct,
                        description=(
                            f"vehicle={vehicle_type.value} share={share:.4f} > "
                            f"max={limits.max_pct:.4f}"
                        ),
                    )
                )

        # ----- Concentration (per-holding) -----
        if mandate.concentration_limits is not None and current_aum_inr > 0:
            cap = mandate.concentration_limits.per_holding_max
            for h in holdings:
                share = h.market_value / current_aum_inr
                if share > cap + 1e-9:
                    breaches.append(
                        M1Breach(
                            breach_type=M1BreachType.CONCENTRATION,
                            constraint_id=f"concentration:per_holding:{h.instrument_id}",
                            current_value=share,
                            limit_value=cap,
                            breach_magnitude=share - cap,
                            description=(
                                f"holding={h.instrument_id} share={share:.4f} > "
                                f"per_holding_max={cap:.4f}"
                            ),
                        )
                    )

        # ----- Liquidity floor -----
        if most_liquid_share is not None and most_liquid_share + 1e-9 < mandate.liquidity_floor:
            breaches.append(
                M1Breach(
                    breach_type=M1BreachType.LIQUIDITY_FLOOR,
                    constraint_id="liquidity_floor",
                    current_value=most_liquid_share,
                    limit_value=mandate.liquidity_floor,
                    breach_magnitude=mandate.liquidity_floor - most_liquid_share,
                    description=(
                        f"most_liquid_share={most_liquid_share:.4f} < "
                        f"floor={mandate.liquidity_floor:.4f}"
                    ),
                )
            )

        # ----- Build N0 alerts (one per breach) -----
        alerts: list[N0Alert] = [
            self._build_n0_alert(client_id=client_id, firm_id=firm_id, breach=b)
            for b in breaches
        ]

        if out_of_bucket_flag:
            alerts.append(self._build_out_of_bucket_alert(client_id, firm_id))

        # ----- Build report -----
        input_bundle = self._collect_input_for_hash(
            client_id=client_id,
            firm_id=firm_id,
            mandate=mandate,
            holdings=holdings,
            most_liquid_share=most_liquid_share,
            out_of_bucket_flag=out_of_bucket_flag,
            sweep_date=sweep_date,
        )

        report = M1DriftReport(
            report_id=new_ulid(),
            client_id=client_id,
            firm_id=firm_id,
            mandate_id=mandate.mandate_id,
            mandate_version=mandate.version,
            sweep_date=sweep_date,
            timestamp=self._now(),
            breaches=breaches,
            out_of_bucket_flag=out_of_bucket_flag,
            n0_alert_ids=[a.alert_id for a in alerts],
            inputs_used_manifest=self._build_inputs_used_manifest(input_bundle),
            input_hash=payload_hash(input_bundle),
            agent_version=self._agent_version,
        )
        return report, alerts

    # --------------------- Helpers ----------------------------------

    def _build_n0_alert(
        self,
        *,
        client_id: str,
        firm_id: str,
        breach: M1Breach,
    ) -> N0Alert:
        return N0Alert(
            alert_id=new_ulid(),
            originator=N0Originator.M1,
            tier=AlertTier.MUST_RESPOND,
            category=N0AlertCategory.MANDATE_BREACH,
            client_id=client_id,
            firm_id=firm_id,
            created_at=self._now(),
            title=f"Mandate breach: {breach.constraint_id}",
            body=breach.description,
            expected_action="Rebalance, amend mandate, or escalate.",
            related_constraint_id=breach.constraint_id,
        )

    def _build_out_of_bucket_alert(
        self, client_id: str, firm_id: str
    ) -> N0Alert:
        return N0Alert(
            alert_id=new_ulid(),
            originator=N0Originator.M1,
            tier=AlertTier.MUST_RESPOND,
            category=N0AlertCategory.MANDATE_BREACH,
            client_id=client_id,
            firm_id=firm_id,
            created_at=self._now(),
            title="Out-of-bucket flag set",
            body=(
                "No standard model portfolio bucket fits without clipping. "
                "Single-client construction case required per §7.10 Test 10."
            ),
            expected_action="Open single-client construction case.",
        )

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

    def _collect_input_for_hash(
        self,
        *,
        client_id: str,
        firm_id: str,
        mandate: MandateObject,
        holdings: list[Holding],
        most_liquid_share: float | None,
        out_of_bucket_flag: bool,
        sweep_date: date,
    ) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "client_id": client_id,
            "firm_id": firm_id,
            "mandate_id": mandate.mandate_id,
            "mandate_version": mandate.version,
            "sweep_date": sweep_date.isoformat(),
            "holdings_hashes": sorted(
                f"{h.instrument_id}:{h.market_value:.2f}" for h in holdings
            ),
            "most_liquid_share": (
                round(most_liquid_share, 6) if most_liquid_share is not None else None
            ),
            "out_of_bucket_flag": out_of_bucket_flag,
        }

    def _build_inputs_used_manifest(
        self, signals_input_for_hash: dict[str, Any]
    ) -> InputsUsedManifest:
        inputs_dict: dict[str, dict[str, str]] = {}
        for k, v in signals_input_for_hash.items():
            inputs_dict[k] = {"shape_hash": payload_hash(v) if v is not None else ""}
        return InputsUsedManifest(inputs=inputs_dict)

    def _now(self) -> datetime:
        return get_clock().now()


__all__ = ["MandateDriftMonitor"]
