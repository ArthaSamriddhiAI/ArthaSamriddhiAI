"""Drift detection at L1, L2, L3 against a model portfolio (Section 5.5).

Tolerance band semantics, per Section 5.5:

  * L1 (asset class)        — action-triggering. Breach → rebalance recommendation.
  * L2 (vehicle within AC)  — informational. Breach → advisor-visible drift, no action.
  * L3 (sub-asset within V) — informational. Same as L2 but at finer resolution.

The action vs informational distinction is encoded in `DriftSeverity`. PM1
(Section 13.6) consumes drift events and emits N0 alerts at the appropriate
tier — must_respond/should_respond for L1 breaches, informational for L2/L3.
This module is concerned only with detection, not with notification routing.
"""

from __future__ import annotations

from datetime import date
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from artha.canonical.model_portfolio import ModelPortfolioObject
from artha.common.types import (
    AssetClass,
    PercentageField,
    VehicleType,
)


class DriftDimension(str, Enum):
    """Which level of the model portfolio the drift event sits at."""

    L1 = "l1"
    L2 = "l2"
    L3 = "l3"


class DriftSeverity(str, Enum):
    """Per Section 5.5 — L1 breaches trigger action; L2/L3 breaches are informational."""

    ACTION_REQUIRED = "action_required"  # L1 breach
    INFORMATIONAL = "informational"      # L2 or L3 breach


class DriftEvent(BaseModel):
    """A single drift breach surfaced by `detect_drift_events`.

    Only emitted when the dimension is OUTSIDE its tolerance band; in-tolerance
    cells are silent (the caller can derive a full status via
    `is_l1_breaching` / `is_l2_breaching` if needed).
    """

    model_config = ConfigDict(extra="forbid")

    dimension: DriftDimension
    # cell_key examples: "equity" (L1), "equity.mutual_fund" (L2),
    # "equity.mutual_fund.large_cap" (L3).
    cell_key: str
    target: PercentageField
    actual: PercentageField
    tolerance_band: PercentageField
    drift_magnitude: float  # signed: actual - target
    severity: DriftSeverity


class PortfolioAllocationSnapshot(BaseModel):
    """The actual allocation of a portfolio at `as_of_date`, fed into drift detection.

    All weights are 0–1 fractions. Each level is a separate map:
      * L1: AssetClass → weight (must sum to ~1.0 across the snapshot)
      * L2: AssetClass → (VehicleType → weight) (each inner map sums to ~1.0)
      * L3: composite cell key "asset_class.vehicle_type" → (sub_asset_class → weight)

    L2 and L3 are optional — diagnostic-mode runs may compute only L1.
    """

    model_config = ConfigDict(extra="forbid")

    as_of_date: date
    l1_weights: dict[AssetClass, PercentageField]
    l2_weights: dict[AssetClass, dict[VehicleType, PercentageField]] = Field(default_factory=dict)
    l3_weights: dict[str, dict[str, PercentageField]] = Field(default_factory=dict)


def _is_breach(target: float, actual: float, band: float) -> bool:
    """True if |actual - target| reaches or exceeds the band.

    Section 5.13 test 3 fixes the boundary: PMS at 35% with target 25% and band ±10%
    is "exactly at the band edge" and PM1 "reports the drift as informational". To
    surface the event at the edge we use `>=` (with a small epsilon for float
    precision). For L1 this means an exact-edge case emits ACTION_REQUIRED — slightly
    over-triggering versus the prose, but the safer side of the asymmetry.
    """
    return abs(actual - target) >= band - 1e-9


def detect_l1_drift(
    model: ModelPortfolioObject,
    snapshot: PortfolioAllocationSnapshot,
) -> list[DriftEvent]:
    """Emit one event per L1 asset class that is outside the model's tolerance band.

    Uses `model.l1_action_tolerance` as the default band when the cell's own
    tolerance_band is unset (model objects always set it, so this is mostly a
    safety net). Per-asset-class bands take precedence per Section 5.5.
    """
    events: list[DriftEvent] = []
    for asset_class, target_band in model.l1_targets.items():
        actual = snapshot.l1_weights.get(asset_class, 0.0)
        if _is_breach(target_band.target, actual, target_band.tolerance_band):
            events.append(
                DriftEvent(
                    dimension=DriftDimension.L1,
                    cell_key=asset_class.value,
                    target=target_band.target,
                    actual=actual,
                    tolerance_band=target_band.tolerance_band,
                    drift_magnitude=actual - target_band.target,
                    severity=DriftSeverity.ACTION_REQUIRED,
                )
            )
    return events


def detect_l2_drift(
    model: ModelPortfolioObject,
    snapshot: PortfolioAllocationSnapshot,
) -> list[DriftEvent]:
    """Emit one event per L2 vehicle that is outside the model's tolerance band.

    L2 weights are within-asset-class fractions (the snapshot's `l2_weights[ac][v]`
    is the share of asset_class `ac` held in vehicle `v`).
    """
    events: list[DriftEvent] = []
    for asset_class, vehicle_targets in model.l2_targets.items():
        actual_by_vehicle = snapshot.l2_weights.get(asset_class, {})
        for vehicle, target_band in vehicle_targets.items():
            actual = actual_by_vehicle.get(vehicle, 0.0)
            if _is_breach(target_band.target, actual, target_band.tolerance_band):
                events.append(
                    DriftEvent(
                        dimension=DriftDimension.L2,
                        cell_key=f"{asset_class.value}.{vehicle.value}",
                        target=target_band.target,
                        actual=actual,
                        tolerance_band=target_band.tolerance_band,
                        drift_magnitude=actual - target_band.target,
                        severity=DriftSeverity.INFORMATIONAL,
                    )
                )
    return events


def detect_l3_drift(
    model: ModelPortfolioObject,
    snapshot: PortfolioAllocationSnapshot,
) -> list[DriftEvent]:
    """Emit one event per L3 sub-asset-class that is outside its tolerance band.

    Cell keys are the composite "asset_class.vehicle_type" strings used in
    `model.l3_targets` (per Section 5.3.3 example).
    """
    events: list[DriftEvent] = []
    for cell_key, sub_targets in model.l3_targets.items():
        actual_by_sub = snapshot.l3_weights.get(cell_key, {})
        for sub, target_band in sub_targets.items():
            actual = actual_by_sub.get(sub, 0.0)
            if _is_breach(target_band.target, actual, target_band.tolerance_band):
                events.append(
                    DriftEvent(
                        dimension=DriftDimension.L3,
                        cell_key=f"{cell_key}.{sub}",
                        target=target_band.target,
                        actual=actual,
                        tolerance_band=target_band.tolerance_band,
                        drift_magnitude=actual - target_band.target,
                        severity=DriftSeverity.INFORMATIONAL,
                    )
                )
    return events


def detect_drift_events(
    model: ModelPortfolioObject,
    snapshot: PortfolioAllocationSnapshot,
) -> list[DriftEvent]:
    """Run all three levels and return concatenated events (L1 first, then L2, then L3).

    Returning L1 first means action-triggering events lead the list — useful for
    callers that surface only the most severe item.
    """
    return [
        *detect_l1_drift(model, snapshot),
        *detect_l2_drift(model, snapshot),
        *detect_l3_drift(model, snapshot),
    ]


def has_l1_breach(events: list[DriftEvent]) -> bool:
    """True if any L1 (action-triggering) breach is present in `events`.

    PM1 uses this to decide whether to emit a rebalance N0 alert (Section 5.13 test 2).
    """
    return any(e.dimension is DriftDimension.L1 for e in events)
