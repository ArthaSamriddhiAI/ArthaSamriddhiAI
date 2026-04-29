"""Section 15.4 — mandate_object and mandate_amendment_request.

The mandate is the legal floor and ceiling for an investor's allocation
(Section 7.1). The model portfolio (Section 15.5) is the strategic target
within those bounds. Both constrain the portfolio's shape but at different
governance layers.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from artha.common.types import (
    AssetClass,
    INRAmountField,
    MandateType,
    PercentageField,
    VehicleType,
)


class SignoffMethod(str, Enum):
    """Section 15.4.1 — how the client signed off on the mandate."""

    IN_PERSON = "in_person"
    E_SIGNATURE = "e_signature"
    SCANNED_DOCUMENT = "scanned_document"


class SignoffEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str
    captured_at: datetime
    storage_uri: str | None = None


class AssetClassLimits(BaseModel):
    """Per-asset-class min/target/max as percentages of total AUM (Section 15.4.1).

    Invariant: 0 <= min_pct <= target_pct <= max_pct <= 1.
    """

    model_config = ConfigDict(extra="forbid")

    min_pct: PercentageField
    target_pct: PercentageField
    max_pct: PercentageField

    @model_validator(mode="after")
    def _check_ordering(self) -> AssetClassLimits:
        if not (self.min_pct <= self.target_pct <= self.max_pct):
            raise ValueError(
                f"min_pct ({self.min_pct}) <= target_pct ({self.target_pct}) "
                f"<= max_pct ({self.max_pct}) must hold"
            )
        return self


class VehicleLimits(BaseModel):
    """Per-vehicle allowance with optional bounds."""

    model_config = ConfigDict(extra="forbid")

    allowed: bool = True
    min_pct: PercentageField | None = None
    max_pct: PercentageField | None = None

    @model_validator(mode="after")
    def _check_bounds(self) -> VehicleLimits:
        if self.min_pct is not None and self.max_pct is not None:
            if self.min_pct > self.max_pct:
                raise ValueError(
                    f"min_pct ({self.min_pct}) must be <= max_pct ({self.max_pct})"
                )
        return self


class SubAssetClassLimits(BaseModel):
    """Per-sub-asset-class min/target/max."""

    model_config = ConfigDict(extra="forbid")

    min_pct: PercentageField
    target_pct: PercentageField
    max_pct: PercentageField

    @model_validator(mode="after")
    def _check_ordering(self) -> SubAssetClassLimits:
        if not (self.min_pct <= self.target_pct <= self.max_pct):
            raise ValueError(
                f"min_pct ({self.min_pct}) <= target_pct ({self.target_pct}) "
                f"<= max_pct ({self.max_pct}) must hold"
            )
        return self


class ConcentrationLimits(BaseModel):
    """Section 15.4.1."""

    model_config = ConfigDict(extra="forbid")

    per_holding_max: PercentageField
    per_manager_max: PercentageField
    per_sector_max: PercentageField


class LiquidityWindow(BaseModel):
    """A specific liquidity obligation (e.g., "₹2 Cr accessible by 2030-06-01")."""

    model_config = ConfigDict(extra="forbid")

    by_date: date
    amount_inr: INRAmountField


class FamilyMemberOverrideMandate(BaseModel):
    """Per-member override fields layered on top of the family-level mandate."""

    model_config = ConfigDict(extra="forbid")

    member_id: str
    override_fields: dict[str, Any] = Field(default_factory=dict)


class MandateObject(BaseModel):
    """Canonical mandate (Section 15.4.1)."""

    model_config = ConfigDict(extra="forbid")

    mandate_id: str
    client_id: str
    firm_id: str
    version: int = 1
    created_at: datetime
    effective_at: datetime
    superseded_at: datetime | None = None
    mandate_type: MandateType

    # Constraints — keys are enum-value strings (Pydantic 2 serialises enum keys to values)
    asset_class_limits: dict[AssetClass, AssetClassLimits]
    vehicle_limits: dict[VehicleType, VehicleLimits] = Field(default_factory=dict)
    sub_asset_class_limits: dict[str, SubAssetClassLimits] = Field(default_factory=dict)
    sector_exclusions: list[str] = Field(default_factory=list)  # discouraged but allowed
    sector_hard_blocks: list[str] = Field(default_factory=list)  # prohibited
    concentration_limits: ConcentrationLimits | None = None
    liquidity_floor: PercentageField  # min portfolio liquidity required
    liquidity_windows: list[LiquidityWindow] = Field(default_factory=list)
    thematic_preferences: dict[str, Any] = Field(default_factory=dict)

    # Family-level overrides per member
    family_overrides: list[FamilyMemberOverrideMandate] = Field(default_factory=list)

    # Signoff (the SEBI-defensible legal artifact)
    signoff_method: SignoffMethod
    signoff_evidence: SignoffEvidence
    signed_by: str

    @model_validator(mode="after")
    def _check_supersedence_after_effective(self) -> MandateObject:
        if self.superseded_at is not None and self.superseded_at <= self.effective_at:
            raise ValueError(
                f"superseded_at ({self.superseded_at}) must be after "
                f"effective_at ({self.effective_at})"
            )
        return self


class MandateAmendmentType(str, Enum):
    """Section 15.4.2."""

    CONSTRAINT_ADDED = "constraint_added"
    CONSTRAINT_RELAXED = "constraint_relaxed"
    FAMILY_STRUCTURE_CHANGE = "family_structure_change"
    SECTOR_BLOCK_CHANGE = "sector_block_change"
    LIQUIDITY_CHANGE = "liquidity_change"
    OTHER = "other"


class MandateAmendmentStatus(str, Enum):
    """Section 15.4.2."""

    PENDING_SIGNOFF = "pending_signoff"
    PENDING_COMPLIANCE_REVIEW = "pending_compliance_review"
    ACTIVATED = "activated"
    REJECTED = "rejected"


class MandateAmendmentRequest(BaseModel):
    """Section 15.4.2 — the structured amendment workflow object."""

    model_config = ConfigDict(extra="forbid")

    amendment_id: str
    client_id: str
    proposed_at: datetime
    proposed_by: str  # advisor_id
    amendment_type: MandateAmendmentType
    diff: dict[str, Any]  # {"old_mandate_subset": {...}, "new_mandate_subset": {...}}
    justification: str
    compliance_check_result: dict[str, Any] = Field(default_factory=dict)
    client_signoff: SignoffEvidence | None = None
    activation_status: MandateAmendmentStatus = MandateAmendmentStatus.PENDING_SIGNOFF
