"""E7 Mutual Fund output schema — cluster 8 chunk 8.3 §8.

Pydantic models matching the spec JSON Schema.  Seven semantic validation
rules are applied by
:class:`~artha.api_v2.agents.e7_mutual_fund.shim.E7MutualFundShim`.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class FundVerdict(str, Enum):
    POSITIVE = "positive"
    NEUTRAL_CONSTRUCTIVE = "neutral_constructive"
    NEUTRAL_CHALLENGING = "neutral_challenging"
    AVOID = "avoid"


class ContinuitySignal(str, Enum):
    STABLE_LONG_TENURE = "stable_long_tenure"
    STABLE_RECENT = "stable_recent"
    RECENTLY_CHANGED = "recently_changed"
    ROTATING = "rotating"
    KEY_PERSON_RISK = "key_person_risk"


class AlphaConsistency(str, Enum):
    CONSISTENT_POSITIVE = "consistent_positive"
    INTERMITTENT_POSITIVE = "intermittent_positive"
    NEUTRAL = "neutral"
    CONSISTENT_NEGATIVE = "consistent_negative"


class FeeVerdict(str, Enum):
    BELOW_NORM = "below_norm"
    AT_NORM = "at_norm"
    ABOVE_NORM_JUSTIFIED = "above_norm_justified"
    ABOVE_NORM_CONCERNING = "above_norm_concerning"


class CapacitySignal(str, Enum):
    AMPLE = "ample"
    APPROACHING_CAPACITY = "approaching_capacity"
    AT_CAPACITY = "at_capacity"
    SOFT_CLOSE = "soft_close"
    HARD_CLOSE = "hard_close"


class StyleConsistency(str, Enum):
    CONSISTENT_WITH_STATED_MANDATE = "consistent_with_stated_mandate"
    MINOR_DRIFT = "minor_drift"
    MATERIAL_DRIFT = "material_drift"
    STYLE_BOX_CHANGE = "style_box_change"


class PeerQuartile(str, Enum):
    TOP = "top"
    SECOND = "second"
    THIRD = "third"
    BOTTOM = "bottom"


class SignalDirection(str, Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"


class SignalSeverity(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ManagerContinuityAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manager_name: str = Field(min_length=1)
    tenure_years: float = Field(ge=0.0)
    continuity_signal: ContinuitySignal


class AlphaAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    alpha_5y_bps: int
    benchmark: str = Field(min_length=1)
    alpha_consistency: AlphaConsistency


class FeeStructureAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ter_pct: float = Field(ge=0.0)
    category_norm_pct: float = Field(ge=0.0)
    fee_verdict: FeeVerdict


class CapacityAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_aum_inr_cr: float = Field(ge=0.0)
    capacity_signal: CapacitySignal


class CategoryPositioning(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str = Field(min_length=1)
    peer_quartile: PeerQuartile
    peer_set_summary: str = Field(min_length=1)


class KeySignal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    signal: str = Field(min_length=1)
    direction: SignalDirection
    severity: SignalSeverity


class E7MutualFundOutput(BaseModel):
    """Full E7 mutual fund verdict (chunk 8.3 §8)."""

    model_config = ConfigDict(extra="forbid")

    fund_id: str = Field(min_length=1)
    fund_verdict: FundVerdict
    manager_continuity_assessment: ManagerContinuityAssessment
    alpha_assessment: AlphaAssessment
    fee_structure_assessment: FeeStructureAssessment
    capacity_assessment: CapacityAssessment
    style_consistency: StyleConsistency
    category_positioning: CategoryPositioning
    key_signals: list[KeySignal] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning_summary: str = Field(min_length=200)


__all__ = [
    "AlphaAssessment",
    "AlphaConsistency",
    "CapacityAssessment",
    "CapacitySignal",
    "CategoryPositioning",
    "ContinuitySignal",
    "E7MutualFundOutput",
    "FeeStructureAssessment",
    "FeeVerdict",
    "FundVerdict",
    "KeySignal",
    "ManagerContinuityAssessment",
    "PeerQuartile",
    "SignalDirection",
    "SignalSeverity",
    "StyleConsistency",
]
