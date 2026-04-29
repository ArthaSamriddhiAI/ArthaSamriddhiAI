"""Section 15.5.2/3 — fund_universe_l4_entry and l4_manifest_version.

L4 is the firm's approved instrument manifest, mapping each (vehicle, sub-asset-class)
cell of the model portfolio to one or more approved instruments. It is governed
separately from the model portfolio (Section 5.9): different cadence, different
approver, different blast radius.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from artha.common.types import (
    AssetClass,
    BasisPointsField,
    MandateType,
    PercentageField,
    VehicleType,
    WealthTier,
)


class L4Status(str, Enum):
    """Section 15.5.2."""

    ACTIVE = "active"
    SUSPENDED = "suspended"
    DEPRECATED = "deprecated"


class L4Operation(str, Enum):
    """Section 15.5.3 — the change-set operation types."""

    ADD = "add"
    SUBSTITUTE = "substitute"
    SUSPEND = "suspend"


class LookThroughFrequency(str, Enum):
    """Section 15.5.2 — how often the firm receives look-through holdings for this instrument."""

    DAILY = "daily"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    NONE = "none"


class FeeSchedule(BaseModel):
    """Section 15.5.2 — instrument-level fee structure used by E6.FeeNormalisation."""

    model_config = ConfigDict(extra="forbid")

    management_fee_bps: BasisPointsField = 0
    performance_fee_bps: BasisPointsField = 0
    exit_load_pct: PercentageField = 0.0
    structure_costs_bps: BasisPointsField = 0


class RedemptionMechanics(BaseModel):
    """Section 15.5.2 — redemption notice, settlement cycle, and gate provisions."""

    model_config = ConfigDict(extra="forbid")

    notice_period_iso_duration: str | None = None  # e.g. "P30D"
    settlement_cycle_days: int | None = None
    gate_provisions: dict[str, str] = Field(default_factory=dict)


class FundUniverseL4Entry(BaseModel):
    """A single approved instrument (Section 15.5.2)."""

    model_config = ConfigDict(extra="forbid")

    instrument_id: str
    instrument_name: str
    vehicle_type: VehicleType
    asset_class: AssetClass
    sub_asset_class: str
    amc_or_issuer: str

    # Eligibility filters
    minimum_aum_tier: WealthTier
    structural_eligibility: list[MandateType] = Field(default_factory=list)

    # Fees
    fee_schedule: FeeSchedule = Field(default_factory=FeeSchedule)
    fee_effective_at: date

    # Operational
    look_through_published: bool = False
    look_through_frequency: LookThroughFrequency = LookThroughFrequency.NONE
    redemption_mechanics: RedemptionMechanics | None = None
    lock_in_iso_duration: str | None = None  # e.g. "P3Y" for a three-year lock-in

    # Status / lineage
    status: L4Status = L4Status.ACTIVE
    substitute_for: str | None = None  # instrument_id of predecessor, if substitute
    substituted_at: date | None = None


class L4ManifestChange(BaseModel):
    """Section 15.5.3 — one operation in a manifest version's change-set."""

    model_config = ConfigDict(extra="forbid")

    operation: L4Operation
    instrument_id: str
    rationale: str


class CascadeImpactSummary(BaseModel):
    """Section 15.5.3 — how many clients are affected by this version, by severity."""

    model_config = ConfigDict(extra="forbid")

    clients_affected_count: int = 0
    severity_distribution: dict[str, int] = Field(default_factory=dict)


class L4ManifestVersion(BaseModel):
    """A versioned snapshot of the firm's L4 manifest (Section 15.5.3)."""

    model_config = ConfigDict(extra="forbid")

    manifest_version: str
    firm_id: str
    created_at: datetime
    effective_at: datetime
    superseded_at: datetime | None = None
    approved_by: str
    changes_from_prior: list[L4ManifestChange] = Field(default_factory=list)
    cascade_impact_summary: CascadeImpactSummary = Field(default_factory=CascadeImpactSummary)
    entries: list[FundUniverseL4Entry] = Field(default_factory=list)
