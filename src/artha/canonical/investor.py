"""Section 15.3.1 — investor_context_profile.

The active layer carries six bucket-mapping and structural fields plus identity
and audit. The dormant layer is specified in the spec but inactive in MVP; we
ship it as a stub with `active=False` and an empty `fields` dict. Section 6.5
lays out the staged activation procedure.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from artha.common.types import (
    Bucket,
    CapacityTrajectory,
    ConfidenceField,
    RiskProfile,
    TimeHorizon,
    WealthTier,
)
from artha.model_portfolio.buckets import derive_bucket


class DataSource(str, Enum):
    """Section 10.3.1 — the three onboarding paths converge on a canonical investor."""

    FORM = "form"
    C0 = "c0"
    API = "api"


class IntermediaryMetadata(BaseModel):
    """Section 6.2 — populated when `intermediary_present=True`.

    The full Section 6.10 dormant structure (economic interest type, influence
    level, transparency, agreement rate) is intentionally not exposed in MVP.
    """

    model_config = ConfigDict(extra="forbid")

    relationship_type: str  # ca, distributor, lawyer, family_member, community_trustee, poa
    contact: str | None = None
    authority_scope: str | None = None  # informs, advises, co-decides, decides


class BeneficiaryMetadata(BaseModel):
    """Section 6.2 — populated when `beneficiary_can_operate_current_structure=False`."""

    model_config = ConfigDict(extra="forbid")

    capacity_basis: str | None = None
    support_structure: str | None = None


class DormantWealthOriginPattern(str, Enum):
    """Section 6.9 L1 — wealth origin patterns. Inactive in MVP."""

    L1_01_FIRST_GEN_BUSINESS_BUILDER = "L1-01_first_gen_business_builder"
    L1_02_SALARIED_CORPORATE_EXECUTIVE = "L1-02_salaried_corporate_executive"
    L1_03_INHERITED_WEALTH = "L1-03_inherited_wealth"
    L1_04_PROFESSIONAL_PRACTICE = "L1-04_professional_practice"
    L1_05_REAL_ESTATE_WEALTH_BUILDER = "L1-05_real_estate_wealth_builder"
    L1_06_EQUITY_MARKETS_WEALTH_BUILDER = "L1-06_equity_markets_wealth_builder"
    L1_07_GOVERNMENT_OR_DEFENCE = "L1-07_government_or_defence"
    L1_08_NRI_OR_RETURNING_EXPATRIATE = "L1-08_nri_or_returning_expatriate"
    L1_09_MIXED = "L1-09_mixed"


class DormantLifeSituationPattern(str, Enum):
    """Section 6.9 L2 — life situation patterns. Inactive in MVP."""

    L2_01_STABLE_MULTI_DECADE_FAMILY = "L2-01_stable_multi_decade_family"
    L2_02_RECENT_MAJOR_LIFE_EVENT = "L2-02_recent_major_life_event"
    L2_03_ACTIVE_FAMILY_CONSTRUCTION = "L2-03_active_family_construction"
    L2_04_EMPTY_NEST_TRANSITION = "L2-04_empty_nest_transition"
    L2_05_RETIREMENT = "L2-05_retirement"
    L2_06_POST_DIVORCE = "L2-06_post_divorce"
    L2_07_RECENT_WIDOWHOOD = "L2-07_recent_widowhood"
    L2_08_BENEFICIARY_INHERITANCE_PHASE = "L2-08_beneficiary_inheritance_phase"
    L2_09_HEALTH_DRIVEN_CONSTRAINT = "L2-09_health_driven_constraint"


class DormantStructuralComplicationPattern(str, Enum):
    """Section 6.9 L3 — structural complications. Inactive in MVP."""

    L3_01_MATERIAL_DEBT = "L3-01_material_debt"
    L3_02_FLOATING_RATE_EXPOSURE = "L3-02_floating_rate_exposure"
    L3_03_PERSONAL_GUARANTEE_BURDEN = "L3-03_personal_guarantee_burden"
    L3_04_BUSINESS_CONCENTRATION = "L3-04_business_concentration"
    L3_05_CROSS_BORDER_COMPLEXITY = "L3-05_cross_border_complexity"
    L3_06_MULTI_GENERATIONAL_TRUST = "L3-06_multi_generational_trust"
    L3_07_FAMILY_OFFICE_GOVERNANCE = "L3-07_family_office_governance"
    L3_08_REGULATORY_RESTRICTION = "L3-08_regulatory_restriction"
    L3_09_LITIGATION_PENDING = "L3-09_litigation_pending"


class DormantPatternInteractionFlag(BaseModel):
    """Section 6.11 — non-additive constraint behaviour produced by pattern combinations.

    Examples (preserved as dormant):
      * L1-01 + L3-01 + L3-05 → HIGH cascade risk; AIF illiquidity contraindicated.
      * L2-07 + L3-03 → beneficiary agency gap requires structural review.
      * L1-02 + L2-04 → aggressive deployment opportunity; lower behavioural inertia.
      * L1-08 + L3-05 → regulatory and tax-treaty considerations dominate product choice.
    """

    model_config = ConfigDict(extra="forbid")

    interaction_id: str  # e.g. "L1-01+L3-01+L3-05"
    triggering_patterns: list[str] = Field(default_factory=list)  # the pattern keys
    interaction_effect: str  # short-form description
    downstream_consumers: list[str] = Field(default_factory=list)  # e.g. ["e6_gate", "s1"]


class DormantWorldviewIndicator(BaseModel):
    """Section 6.12 — how the investor thinks about money / risk / decisions.

    e.g. for L1-01: "earned through effort and sacrifice", "tangible assets are safe".
    """

    model_config = ConfigDict(extra="forbid")

    pattern_key: str  # e.g. "L1-01"
    indicators: list[str] = Field(default_factory=list)


class DormantResistanceFlag(BaseModel):
    """Section 6.12 — products / recommendations the investor will reflexively resist.

    e.g. for L1-01: WILL_RESIST discretionary_pms.
    """

    model_config = ConfigDict(extra="forbid")

    pattern_key: str
    will_resist: list[str] = Field(default_factory=list)


class DormantBlindSpot(BaseModel):
    """Section 6.12 — dimensions on which the investor systematically underestimates risk.

    e.g. for L1-01: underestimates_business_concentration_risk.
    """

    model_config = ConfigDict(extra="forbid")

    pattern_key: str
    blind_spots: list[str] = Field(default_factory=list)


class DormantAdvisoryFraming(BaseModel):
    """Section 6.12 — communication-level guidance per pattern.

    e.g. for L1-01: lead_with `protection`, never_lead_with `alpha-and-returns`.
    """

    model_config = ConfigDict(extra="forbid")

    pattern_key: str
    lead_with: str = ""
    never_lead_with: str = ""
    growth_edges: list[str] = Field(default_factory=list)


class DormantI0Layer(BaseModel):
    """Section 6.5 / 16.2 — the full dormant I0 layer schema, inactive in MVP.

    Per Section 3.9 agent prompts must NOT read these fields in MVP. The
    schema exists so that:
      * The data model is forward-compatible — when activation lands, no
        breaking schema change is needed.
      * Future product managers reviewing §6.5's 8-stage activation procedure
        can see the typed shapes they're enabling.
      * Migration tooling can populate dormant fields incrementally.

    `active=False` is the MVP contract. Activation flips this to True via the
    governed deployment loop (Section 6.13).
    """

    model_config = ConfigDict(extra="forbid")

    active: bool = False

    # Section 6.9 — pattern matches per layer
    matched_l1_patterns: list[DormantWealthOriginPattern] = Field(default_factory=list)
    matched_l2_patterns: list[DormantLifeSituationPattern] = Field(default_factory=list)
    matched_l3_patterns: list[DormantStructuralComplicationPattern] = Field(default_factory=list)

    # Section 6.10 — schema extensions beyond the active three booleans
    capacity_trajectory_detail: dict[str, Any] = Field(default_factory=dict)
    intermediary_metadata_detail: dict[str, Any] = Field(default_factory=dict)
    beneficiary_metadata_detail: dict[str, Any] = Field(default_factory=dict)

    # Section 6.11 — non-additive interactions
    pattern_interactions: list[DormantPatternInteractionFlag] = Field(default_factory=list)

    # Section 6.12 — communication-level layers
    worldview_indicators: list[DormantWorldviewIndicator] = Field(default_factory=list)
    resistance_flags: list[DormantResistanceFlag] = Field(default_factory=list)
    blind_spots: list[DormantBlindSpot] = Field(default_factory=list)
    advisory_framings: list[DormantAdvisoryFraming] = Field(default_factory=list)


# Backward-compatibility alias — Pass 4 / Pass 6 callers reference DormantLayerStub.
# DormantI0Layer is a strict superset; the alias keeps existing tests green.
DormantLayerStub = DormantI0Layer


class FamilyMemberOverride(BaseModel):
    """Section 15.3.1 — per-family-member overrides over the investor's profile."""

    model_config = ConfigDict(extra="forbid")

    member_id: str
    member_role: str  # patriarch, spouse, son, daughter, etc.
    override_fields: dict[str, Any] = Field(default_factory=dict)


class InvestorContextProfile(BaseModel):
    """Canonical investor context (Section 15.3.1).

    The `assigned_bucket` field is derived from `risk_profile` × `time_horizon`
    via `derive_bucket()`. We validate consistency at model-validate time so the
    object cannot be persisted with a mismatched bucket pin.
    """

    model_config = ConfigDict(extra="forbid")

    # Identity / audit
    client_id: str
    firm_id: str
    created_at: datetime
    updated_at: datetime
    version: int = 1

    # Active layer (Section 6.4)
    risk_profile: RiskProfile
    time_horizon: TimeHorizon
    wealth_tier: WealthTier
    assigned_bucket: Bucket
    capacity_trajectory: CapacityTrajectory = CapacityTrajectory.STABLE_OR_GROWING
    intermediary_present: bool = False
    intermediary_metadata: IntermediaryMetadata | None = None
    beneficiary_can_operate_current_structure: bool = True
    beneficiary_metadata: BeneficiaryMetadata | None = None

    # Source / audit
    data_source: DataSource
    data_source_metadata: dict[str, Any] = Field(default_factory=dict)
    data_gaps_flagged: list[str] = Field(default_factory=list)
    confidence: ConfidenceField = 1.0

    # Dormant layer (placeholder; never populated in MVP)
    dormant_layer: DormantLayerStub = Field(default_factory=DormantLayerStub)

    # Family member overrides (optional)
    family_member_overrides: list[FamilyMemberOverride] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_bucket_consistency(self) -> InvestorContextProfile:
        expected = derive_bucket(self.risk_profile, self.time_horizon)
        if self.assigned_bucket != expected:
            raise ValueError(
                f"assigned_bucket={self.assigned_bucket.value} but "
                f"derive_bucket({self.risk_profile.value}, {self.time_horizon.value})"
                f"={expected.value}"
            )
        return self

    @model_validator(mode="after")
    def _check_intermediary_metadata_consistency(self) -> InvestorContextProfile:
        # Soft consistency: if the metadata is populated, the flag should be true.
        if self.intermediary_metadata is not None and not self.intermediary_present:
            raise ValueError(
                "intermediary_metadata is populated but intermediary_present is False"
            )
        return self

    @model_validator(mode="after")
    def _check_beneficiary_metadata_consistency(self) -> InvestorContextProfile:
        # Soft consistency: metadata is meant for the false case.
        if (
            self.beneficiary_metadata is not None
            and self.beneficiary_can_operate_current_structure
        ):
            raise ValueError(
                "beneficiary_metadata is populated but the beneficiary CAN operate"
            )
        return self
