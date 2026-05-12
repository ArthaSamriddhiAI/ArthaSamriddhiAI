"""E5.FundView output schema — cluster 9 chunk 9.2 §2.4."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class FundViewVerdict(str, Enum):
    POSITIVE = "positive"
    NEUTRAL_CONSTRUCTIVE = "neutral_constructive"
    NEUTRAL_CHALLENGING = "neutral_challenging"
    AVOID = "avoid"


class ContinuitySignal(str, Enum):
    STABLE_LONG_TENURE = "stable_long_tenure"
    STABLE_RECENT = "stable_recent"
    RECENTLY_CHANGED = "recently_changed"
    ROTATING = "rotating"
    KEY_PERSON_EVENT = "key_person_event"


class TrackRecordQuality(str, Enum):
    EXCEPTIONAL = "exceptional"
    STRONG = "strong"
    AVERAGE = "average"
    BELOW_AVERAGE = "below_average"
    CONCERNING = "concerning"


class DeploymentPacingSignal(str, Enum):
    PACED_WELL = "paced_well"
    AHEAD_OF_SCHEDULE = "ahead_of_schedule"
    SLOWER_THAN_EXPECTED = "slower_than_expected"
    CONCERNING_LAG = "concerning_lag"


class StrategyConsistency(str, Enum):
    CONSISTENT_WITH_MANDATE = "consistent_with_mandate"
    MINOR_FOCUS_DRIFT = "minor_focus_drift"
    MATERIAL_FOCUS_DRIFT = "material_focus_drift"
    STRATEGY_PIVOT = "strategy_pivot"


class GovernanceIntensity(str, Enum):
    LIGHT = "light"
    MODERATE = "moderate"
    INTENSIVE = "intensive"


class FeeVerdict(str, Enum):
    BELOW_CATEGORY_NORM = "below_category_norm"
    AT_CATEGORY_NORM = "at_category_norm"
    ABOVE_NORM_JUSTIFIED = "above_norm_justified"
    ABOVE_NORM_CONCERNING = "above_norm_concerning"


class SignalDirection(str, Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"


class SignalSeverity(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ManagerQualityAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manager_name: str = Field(min_length=1)
    tenure_years: float = Field(ge=0.0)
    continuity_signal: ContinuitySignal
    track_record_quality: TrackRecordQuality


class TrackRecordAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vintage_year: int
    irr_since_inception_pct: float
    dpi_ratio: float = Field(ge=0.0)
    tvpi_ratio: float = Field(ge=0.0)
    consistency_assessment: str = Field(min_length=1)


class CapacityAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_corpus_inr_cr: float = Field(ge=0.0)
    drawn_corpus_inr_cr: float = Field(ge=0.0)
    deployment_pacing_signal: DeploymentPacingSignal


class GovernanceAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intensity: GovernanceIntensity
    key_considerations: list[str] = Field(default_factory=list)


class FeeStructureAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    management_fee_pct: float = Field(ge=0.0)
    carry_pct: float = Field(ge=0.0)
    hurdle_rate_pct: float = Field(ge=0.0)
    fee_verdict: FeeVerdict


class KeySignal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    signal: str = Field(min_length=1)
    direction: SignalDirection
    severity: SignalSeverity


class E5FundViewOutput(BaseModel):
    """Full E5 AIF fund view verdict (chunk 9.2 §2.4)."""

    model_config = ConfigDict(extra="forbid")

    aif_id: str = Field(min_length=1)
    fund_view_verdict: FundViewVerdict
    manager_quality_assessment: ManagerQualityAssessment
    track_record_assessment: TrackRecordAssessment
    capacity_assessment: CapacityAssessment
    strategy_consistency: StrategyConsistency
    governance_assessment: GovernanceAssessment
    fee_structure_assessment: FeeStructureAssessment
    key_signals: list[KeySignal] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning_summary: str = Field(min_length=200)


__all__ = [
    "CapacityAssessment",
    "ContinuitySignal",
    "DeploymentPacingSignal",
    "E5FundViewOutput",
    "FeeStructureAssessment",
    "FeeVerdict",
    "FundViewVerdict",
    "GovernanceAssessment",
    "GovernanceIntensity",
    "KeySignal",
    "ManagerQualityAssessment",
    "SignalDirection",
    "SignalSeverity",
    "StrategyConsistency",
    "TrackRecordAssessment",
    "TrackRecordQuality",
]
