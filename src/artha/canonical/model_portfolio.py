"""Section 15.5.1 — model_portfolio_object.

The model portfolio is a versioned, governed, three-level data object produced
by the construction pipeline (Section 5.8). Its `version` is pinned to every
case it operates on so replay reads against the exact targets in force at
decision time (Section 3.7).

Structural levels:

    L1: asset class allocation         — action-triggering tolerance (default 5%)
    L2: vehicle mix within asset class — informational tolerance (default 10%)
    L3: sub-asset-class within vehicle — informational tolerance (default 15%)

The L4 fund universe manifest is governed separately (see `canonical.l4_manifest`).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from artha.common.types import (
    AssetClass,
    Bucket,
    ConfidenceField,
    PercentageField,
    VehicleType,
)


class TargetWithTolerance(BaseModel):
    """The unit cell of the model portfolio: a strategic target with a tolerance band.

    Both `target` and `tolerance_band` are 0–1 fractions. The band is the
    action-or-info trigger threshold per Section 5.5 (e.g. 0.05 ⇒ ±5 percentage
    points around target). The actual allocation envelope is clipped to [0, 1]
    in practice — a target of 0 with a band of 0.05 gives the range [0, 5%],
    not [-5%, +5%].
    """

    model_config = ConfigDict(extra="forbid")

    target: PercentageField
    tolerance_band: PercentageField  # plus-or-minus around target, in absolute pp


class ShadowModeRollout(BaseModel):
    """Per Section 5.8.3.3 — staged rollout history of a high-blast-radius version."""

    model_config = ConfigDict(extra="forbid")

    started_at: date
    ended_at: date | None = None
    observed_metrics: dict[str, Any] = Field(default_factory=dict)


class ConstructionContext(BaseModel):
    """Section 15.5.1 — references back to the construction pipeline that produced this version."""

    model_config = ConfigDict(extra="forbid")

    construction_pipeline_run_id: str
    ic1_approval_id: str | None = None
    shadow_mode_history: list[ShadowModeRollout] = Field(default_factory=list)


class ExpectedReturnProfile(BaseModel):
    """Per-period expected return estimate for counterfactual framing (Section 15.5.1)."""

    model_config = ConfigDict(extra="forbid")

    period: str  # "1Y", "3Y", "5Y", "since_inception", "10Y", etc.
    gross_return_estimate: ConfidenceField
    net_of_costs_estimate: ConfidenceField


class CounterfactualSupport(BaseModel):
    """The model portfolio's expected profile, used by S1/E6/A1 for counterfactual references."""

    model_config = ConfigDict(extra="forbid")

    expected_return_profile: list[ExpectedReturnProfile] = Field(default_factory=list)
    expected_concentration_profile: dict[str, PercentageField] = Field(default_factory=dict)
    expected_liquidity_profile: dict[str, PercentageField] = Field(default_factory=dict)


# Default tolerance bands per Section 5.5
DEFAULT_L1_ACTION_TOLERANCE = 0.05
DEFAULT_L2_INFORMATIONAL_TOLERANCE = 0.10
DEFAULT_L3_INFORMATIONAL_TOLERANCE = 0.15

# Section 15 + 5.5: how close to 1.0 each level's targets must sum (rounding tolerance).
_ALLOCATION_SUM_EPSILON = 1e-6


class ModelPortfolioObject(BaseModel):
    """Canonical model portfolio (Section 15.5.1).

    L1 percentages must sum to 1.0 across asset classes (rounding-tolerant).
    L2 percentages within each asset class must sum to 1.0 across that class's vehicles.
    L3 percentages within each (asset_class, vehicle) cell must sum to 1.0 across the cell.

    All three sums are validated at model-validate time. A versioned model that
    fails the sum check would produce drift detection and rebalance recommendations
    against meaningless targets, so we fail loudly on construction.
    """

    model_config = ConfigDict(extra="forbid")

    model_id: str
    bucket: Bucket
    version: str  # semver "3.4.0"
    firm_id: str
    created_at: datetime
    effective_at: datetime
    superseded_at: datetime | None = None
    approved_by: str
    approval_rationale: str

    # L1: per-asset-class targets + tolerance
    l1_targets: dict[AssetClass, TargetWithTolerance]
    l1_action_tolerance: PercentageField = DEFAULT_L1_ACTION_TOLERANCE

    # L2: per-asset-class then per-vehicle-type
    l2_targets: dict[AssetClass, dict[VehicleType, TargetWithTolerance]] = Field(
        default_factory=dict
    )
    l2_informational_tolerance: PercentageField = DEFAULT_L2_INFORMATIONAL_TOLERANCE

    # L3: per-(asset_class, vehicle) cell then per-sub-asset-class string
    # Outer key is "asset_class.vehicle" composite (e.g. "equity.mf_active") to keep the
    # JSON shape flat and human-readable per the Section 5.3.3 example.
    l3_targets: dict[str, dict[str, TargetWithTolerance]] = Field(default_factory=dict)
    l3_informational_tolerance: PercentageField = DEFAULT_L3_INFORMATIONAL_TOLERANCE

    # Construction context + counterfactual support
    construction: ConstructionContext
    counterfactual: CounterfactualSupport = Field(default_factory=CounterfactualSupport)

    @model_validator(mode="after")
    def _check_l1_sums_to_one(self) -> ModelPortfolioObject:
        total = sum(t.target for t in self.l1_targets.values())
        if abs(total - 1.0) > _ALLOCATION_SUM_EPSILON:
            raise ValueError(
                f"L1 targets must sum to 1.0, got {total} "
                f"(bucket={self.bucket.value}, version={self.version})"
            )
        return self

    @model_validator(mode="after")
    def _check_l2_sums_per_asset_class(self) -> ModelPortfolioObject:
        for asset_class, vehicles in self.l2_targets.items():
            if not vehicles:
                continue
            total = sum(t.target for t in vehicles.values())
            if abs(total - 1.0) > _ALLOCATION_SUM_EPSILON:
                raise ValueError(
                    f"L2 targets for asset_class={asset_class.value} must sum to 1.0, "
                    f"got {total}"
                )
        return self

    @model_validator(mode="after")
    def _check_l3_sums_per_cell(self) -> ModelPortfolioObject:
        for cell_key, sub_targets in self.l3_targets.items():
            if not sub_targets:
                continue
            total = sum(t.target for t in sub_targets.values())
            if abs(total - 1.0) > _ALLOCATION_SUM_EPSILON:
                raise ValueError(
                    f"L3 targets for cell={cell_key!r} must sum to 1.0, got {total}"
                )
        return self

    @model_validator(mode="after")
    def _check_supersedence_after_effective(self) -> ModelPortfolioObject:
        if self.superseded_at is not None and self.superseded_at <= self.effective_at:
            raise ValueError(
                f"superseded_at ({self.superseded_at}) must be after "
                f"effective_at ({self.effective_at})"
            )
        return self
