"""E5.DealView output schema — cluster 9 chunk 9.2 §3.4."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class DealViewVerdict(str, Enum):
    HIGH_CONVICTION = "high_conviction"
    CONSTRUCTIVE = "constructive"
    NEUTRAL = "neutral"
    CONCERNING = "concerning"
    AVOID = "avoid"


class DealStage(str, Enum):
    SEED = "seed"
    SERIES_A = "series_a"
    SERIES_B = "series_b"
    SERIES_C = "series_c"
    SERIES_D_PLUS = "series_d_plus"
    PRE_IPO = "pre_ipo"
    MATURE_PRIVATE = "mature_private"


class StageAppropriateness(str, Enum):
    APPROPRIATE_FOR_MANDATE = "appropriate_for_mandate"
    EARLY_FOR_MANDATE = "early_for_mandate"
    LATE_FOR_MANDATE = "late_for_mandate"


class ValuationMultipleAssessment(str, Enum):
    BELOW_MARKET = "below_market"
    AT_MARKET = "at_market"
    STRETCHED = "stretched"
    FROTHY = "frothy"
    CONCERNING = "concerning"


class CoInvestorQualitySignal(str, Enum):
    TOP_TIER = "top_tier"
    TIER_1 = "tier_1"
    TIER_2 = "tier_2"
    UNKNOWN_OR_EMERGING = "unknown_or_emerging"


class SignalDirection(str, Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"


class SignalSeverity(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class StageAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_stage: DealStage
    stage_appropriateness: StageAppropriateness
    next_round_outlook: str = Field(min_length=1)


class ValuationAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    post_money_inr_cr: float = Field(ge=0.0)
    valuation_multiple_assessment: ValuationMultipleAssessment
    comparables_signal: str = Field(min_length=1)


class CoInvestorQuality(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lead_investor: str
    quality_signal: CoInvestorQualitySignal


class ExitRouteLikelihood(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ipo: float = Field(ge=0.0, le=1.0, default=0.0)
    strategic_sale: float = Field(ge=0.0, le=1.0, default=0.0)
    secondary: float = Field(ge=0.0, le=1.0, default=0.0)
    write_off: float = Field(ge=0.0, le=1.0, default=0.0)


class ExpectedExitAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    horizon_years: int = Field(ge=0)
    exit_route_likelihood: ExitRouteLikelihood


class MaterialSignal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    signal: str = Field(min_length=1)
    direction: SignalDirection
    severity: SignalSeverity


class E5DealViewOutput(BaseModel):
    """Full E5 deal view verdict (chunk 9.2 §3.4)."""

    model_config = ConfigDict(extra="forbid")

    deal_id: str = Field(min_length=1)
    deal_view_verdict: DealViewVerdict
    stage_assessment: StageAssessment
    valuation_assessment: ValuationAssessment
    co_investor_quality: CoInvestorQuality
    expected_exit_assessment: ExpectedExitAssessment
    material_signals: list[MaterialSignal] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning_summary: str = Field(min_length=200)


__all__ = [
    "CoInvestorQuality",
    "CoInvestorQualitySignal",
    "DealStage",
    "DealViewVerdict",
    "E5DealViewOutput",
    "ExpectedExitAssessment",
    "ExitRouteLikelihood",
    "MaterialSignal",
    "SignalDirection",
    "SignalSeverity",
    "StageAppropriateness",
    "StageAssessment",
    "ValuationAssessment",
    "ValuationMultipleAssessment",
]
