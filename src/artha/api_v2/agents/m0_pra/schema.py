"""M0.PortfolioRiskAnalytics output schema (chunk 7.3 §4).

Pydantic models for the structured output produced by the real LLM-
using M0.PortfolioRiskAnalytics agent. Six per-dimension assessments
plus aggregated overall_risk_level + reasoning + cascade implications.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class M0RiskLevel(str, Enum):
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    CRITICAL = "critical"


class VerdictTag(str, Enum):
    """Per-dimension verdict tag (chunk 7.3 §4.2)."""

    CLEAN = "clean"
    PROXIMITY = "proximity"
    BREACH = "breach"
    IMPROVING = "improving"  # PA/SCENARIO post-action moves favourably
    WORSENING = "worsening"  # PA/SCENARIO post-action moves unfavourably


class CascadeHorizon(str, Enum):
    NEAR_TERM = "near_term"
    MEDIUM_TERM = "medium_term"
    LONG_TERM = "long_term"


class CascadeSeverity(str, Enum):
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"


class DriverWeight(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class DimensionAssessment(BaseModel):
    """One dimension's reading + verdict_tag + optional delta."""

    model_config = ConfigDict(extra="forbid")

    reading: str = Field(min_length=1)
    verdict_tag: VerdictTag
    delta_post_action: str | None = None


class PerDimensionAssessment(BaseModel):
    """The six required dimensions per chunk 7.3 §4."""

    model_config = ConfigDict(extra="forbid")

    concentration: DimensionAssessment
    leverage: DimensionAssessment
    liquidity: DimensionAssessment
    return_quality: DimensionAssessment
    fee_drag: DimensionAssessment
    deployment: DimensionAssessment


class CascadeImplication(BaseModel):
    """One downstream consequence the action triggers."""

    model_config = ConfigDict(extra="forbid")

    implication: str = Field(min_length=1)
    horizon: CascadeHorizon
    severity: CascadeSeverity


class FlaggedProximity(BaseModel):
    """One dimension flagged as approaching ceiling/floor."""

    model_config = ConfigDict(extra="forbid")

    dimension: str = Field(min_length=1)
    current_value: str = Field(min_length=1)
    ceiling_or_floor: str = Field(min_length=1)
    distance_pct: float


class KeyRiskDriver(BaseModel):
    model_config = ConfigDict(extra="forbid")

    driver: str = Field(min_length=1)
    weight: DriverWeight


class M0PRAOutput(BaseModel):
    """The full M0.PortfolioRiskAnalytics verdict (chunk 7.3 §4)."""

    model_config = ConfigDict(extra="forbid")

    overall_risk_level: M0RiskLevel
    confidence: float = Field(ge=0.0, le=1.0)
    per_dimension_assessment: PerDimensionAssessment
    cascade_implications: list[CascadeImplication] = Field(default_factory=list)
    flagged_proximity: list[FlaggedProximity] = Field(default_factory=list)
    reasoning_summary: str = Field(min_length=200)
    key_risk_drivers: list[KeyRiskDriver] = Field(default_factory=list)


__all__ = [
    "CascadeHorizon",
    "CascadeImplication",
    "CascadeSeverity",
    "DimensionAssessment",
    "DriverWeight",
    "FlaggedProximity",
    "KeyRiskDriver",
    "M0PRAOutput",
    "M0RiskLevel",
    "PerDimensionAssessment",
    "VerdictTag",
]
