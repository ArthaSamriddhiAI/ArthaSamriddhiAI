"""§10.3 — onboarding-path schemas.

The three onboarding paths (FORM / C0 / API) all converge on a canonical
`InvestorContextProfile` + `MandateObject`. This module defines:

  * `OnboardingFormPayload` (§10.3.2) — the structured form intake.
  * `OnboardingApiPayload` (§10.3.4) — the bulk API DTO.
  * `OnboardingCheckpoint` (§10.3.3) — C0's three-checkpoint protocol.
  * `OnboardingResult` — the converged output: profile + mandate + T1
    confirmation event id + per-path metadata.

Path differences are isolated to:
  * `data_source` field on the profile/mandate
  * `data_source_metadata` (form_session_id / c0_conversation_id / api_request_id)
  * `confidence` (1.0 for form/api, 0.8–0.95 for c0)
  * `data_gaps_flagged` (form/api typically empty; c0 may carry parse uncertainties)
  * `confirmation_method` captured on the T1 INVESTOR_ACTIVATED event
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from artha.canonical.investor import (
    BeneficiaryMetadata,
    DataSource,
    FamilyMemberOverride,
    IntermediaryMetadata,
)
from artha.canonical.mandate import (
    AssetClassLimits,
    ConcentrationLimits,
    FamilyMemberOverrideMandate,
    LiquidityWindow,
    SignoffMethod,
    SubAssetClassLimits,
    VehicleLimits,
)
from artha.common.types import (
    AssetClass,
    CapacityTrajectory,
    ConfidenceField,
    MandateType,
    PercentageField,
    RiskProfile,
    TimeHorizon,
    VehicleType,
    WealthTier,
)

# ===========================================================================
# Confirmation methods (§10.3.7)
# ===========================================================================


class ConfirmationMethod(str, Enum):
    """§10.3.7 — how advisor confirmed the onboarded investor."""

    FORM_SUBMIT = "form_submit"
    C0_CONFIRMATION = "c0_confirmation"
    API_ALERT_RESPONSE = "api_alert_response"


class OnboardingActivationStatus(str, Enum):
    """Lifecycle of an onboarding case."""

    DRAFT = "draft"
    PENDING_CONFIRMATION = "pending_confirmation"
    PENDING_CONFLICT_RESOLUTION = "pending_conflict_resolution"
    ACTIVATED = "activated"
    ABANDONED = "abandoned"
    EXPIRED = "expired"


# ===========================================================================
# Mandate intake — the constraint payload all three paths supply
# ===========================================================================


class MandateIntakePayload(BaseModel):
    """Mandate constraints submitted via any onboarding path.

    Common shape across FORM / C0 / API. Each handler builds this from its
    raw input then stamps it into a `MandateObject` with the right `created_at`,
    `effective_at`, `signoff_method`, etc.
    """

    model_config = ConfigDict(extra="forbid")

    mandate_type: MandateType
    asset_class_limits: dict[AssetClass, AssetClassLimits]
    vehicle_limits: dict[VehicleType, VehicleLimits] = Field(default_factory=dict)
    sub_asset_class_limits: dict[str, SubAssetClassLimits] = Field(default_factory=dict)
    sector_exclusions: list[str] = Field(default_factory=list)
    sector_hard_blocks: list[str] = Field(default_factory=list)
    concentration_limits: ConcentrationLimits | None = None
    liquidity_floor: PercentageField = 0.10
    liquidity_windows: list[LiquidityWindow] = Field(default_factory=list)
    thematic_preferences: dict[str, Any] = Field(default_factory=dict)
    family_overrides: list[FamilyMemberOverrideMandate] = Field(default_factory=list)


# ===========================================================================
# §10.3.2 — FORM payload
# ===========================================================================


class OnboardingFormPayload(BaseModel):
    """§10.3.2 — the structured form payload submitted by an advisor.

    All required fields are non-skippable per the form discipline (§10.3.2).
    Defaults for structural flags require explicit advisor confirmation; the
    handler converts those to `data_gaps_flagged` if the advisor leaves the
    confirmation checkbox unchecked.
    """

    model_config = ConfigDict(extra="forbid")

    form_session_id: str
    submitted_by_advisor_id: str
    submitted_at: datetime

    # Identity
    client_id: str
    firm_id: str

    # Active layer
    risk_profile: RiskProfile
    time_horizon: TimeHorizon
    wealth_tier: WealthTier

    # Structural flags (§6.2). Defaults documented but caller must confirm.
    capacity_trajectory: CapacityTrajectory = CapacityTrajectory.STABLE_OR_GROWING
    intermediary_present: bool = False
    intermediary_metadata: IntermediaryMetadata | None = None
    beneficiary_can_operate_current_structure: bool = True
    beneficiary_metadata: BeneficiaryMetadata | None = None
    structural_flags_advisor_confirmed: bool = False

    # Family-member overrides
    family_member_overrides: list[FamilyMemberOverride] = Field(default_factory=list)

    # Mandate constraints
    mandate: MandateIntakePayload

    # Signoff
    signoff_method: SignoffMethod = SignoffMethod.E_SIGNATURE
    signoff_evidence_id: str
    signoff_captured_at: datetime
    signed_by: str


# ===========================================================================
# §10.3.4 — API payload
# ===========================================================================


class OnboardingApiPayload(BaseModel):
    """§10.3.4 — bulk API DTO.

    The API endpoint accepts a single payload that already conforms to
    canonical shapes. The handler validates schema + builds the canonical
    objects, then issues a MUST_RESPOND N0 alert to the advisor for
    confirmation (§10.3.4 step 7).
    """

    model_config = ConfigDict(extra="forbid")

    api_request_id: str
    crm_identifier: str | None = None
    payload_received_at: datetime
    api_schema_version: str = "1.0.0"

    # Identity
    client_id: str
    firm_id: str
    advisor_id: str

    # Active layer
    risk_profile: RiskProfile
    time_horizon: TimeHorizon
    wealth_tier: WealthTier

    # Structural flags
    capacity_trajectory: CapacityTrajectory = CapacityTrajectory.STABLE_OR_GROWING
    intermediary_present: bool = False
    intermediary_metadata: IntermediaryMetadata | None = None
    beneficiary_can_operate_current_structure: bool = True
    beneficiary_metadata: BeneficiaryMetadata | None = None

    # Family overrides
    family_member_overrides: list[FamilyMemberOverride] = Field(default_factory=list)

    # Mandate
    mandate: MandateIntakePayload

    # Signoff
    signoff_method: SignoffMethod = SignoffMethod.E_SIGNATURE
    signoff_evidence_id: str
    signoff_captured_at: datetime
    signed_by: str


# ===========================================================================
# §10.3.3 — C0 path: per-checkpoint extracted state
# ===========================================================================


class OnboardingCheckpointKind(str, Enum):
    """§10.3.3 — three checkpoint stages in the C0 flow."""

    IDENTITY_KYC = "identity_kyc"
    RISK_PROFILE_HORIZON = "risk_profile_horizon"
    MANDATE_CONSTRAINTS = "mandate_constraints"


class C0CheckpointExtraction(BaseModel):
    """§10.3.3 — what the LLM extracts at one checkpoint.

    Each checkpoint produces a partial structure; the orchestrator stitches
    them together at finalisation. Fields the LLM leaves null become
    `data_gaps_flagged` entries on the final profile.
    """

    model_config = ConfigDict(extra="forbid")

    checkpoint_kind: OnboardingCheckpointKind
    extracted_fields: dict[str, Any] = Field(default_factory=dict)
    parse_confidence: ConfidenceField = 0.0
    parse_notes: str = ""


class OnboardingCheckpoint(BaseModel):
    """§10.3.3 — one checkpoint with advisor confirmation.

    `extraction` is the LLM's structured pull from the conversation.
    `confirmed` flips True only when the advisor explicitly confirms.
    `corrections` lets the advisor override specific fields.
    """

    model_config = ConfigDict(extra="forbid")

    checkpoint_kind: OnboardingCheckpointKind
    extraction: C0CheckpointExtraction
    confirmed: bool = False
    confirmed_by_advisor_id: str | None = None
    confirmed_at: datetime | None = None
    corrections: dict[str, Any] = Field(default_factory=dict)


class C0OnboardingTranscriptInput(BaseModel):
    """§10.3.3 — minimal conversation summary the C0 LLM extractor reads.

    Production wires this from the actual C0 channel + Librarian session.
    Pass 15 keeps it explicit so tests can drive deterministic parses.
    """

    model_config = ConfigDict(extra="forbid")

    c0_conversation_id: str
    advisor_id: str
    firm_id: str
    client_id: str
    transcript_text: str
    started_at: datetime
    ended_at: datetime | None = None


# ===========================================================================
# Convergence: shared result envelope
# ===========================================================================


class OnboardingConflictItem(BaseModel):
    """One mandate-vs-model conflict surfaced at activation."""

    model_config = ConfigDict(extra="forbid")

    dimension: str  # e.g. "asset_class.equity"
    mandate_value: float | None = None
    model_value: float | None = None
    description: str = ""


class OnboardingResult(BaseModel):
    """The converged output of any onboarding path.

    Per §10.3 Test 1 — same investor through any path produces identical
    canonical shapes modulo `data_source` and `data_source_metadata`. The
    `t1_confirmation_event_id` references the `INVESTOR_ACTIVATED` T1 event
    written when the advisor confirmed.
    """

    model_config = ConfigDict(extra="forbid")

    onboarding_id: str  # ULID per onboarding case
    case_id: str | None = None
    client_id: str
    firm_id: str
    advisor_id: str

    data_source: DataSource
    data_source_metadata: dict[str, str] = Field(default_factory=dict)
    confirmation_method: ConfirmationMethod
    confirmed_at: datetime | None = None
    activation_status: OnboardingActivationStatus = (
        OnboardingActivationStatus.PENDING_CONFIRMATION
    )

    # The canonical objects produced
    investor_profile_payload: dict[str, Any]  # serialised InvestorContextProfile
    mandate_payload: dict[str, Any]            # serialised MandateObject

    # Conflict surfacing (resolved before activation per §10.3.5)
    conflicts: list[OnboardingConflictItem] = Field(default_factory=list)
    conflict_resolution_path: str | None = None

    # T1
    t1_confirmation_event_id: str | None = None  # populated post-activation


__all__ = [
    "C0CheckpointExtraction",
    "C0OnboardingTranscriptInput",
    "ConfirmationMethod",
    "MandateIntakePayload",
    "OnboardingActivationStatus",
    "OnboardingApiPayload",
    "OnboardingCheckpoint",
    "OnboardingCheckpointKind",
    "OnboardingConflictItem",
    "OnboardingFormPayload",
    "OnboardingResult",
]
