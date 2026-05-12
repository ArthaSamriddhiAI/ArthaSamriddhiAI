"""E3.NewsScanner output schema — cluster 8 chunk 8.4 §6.

Pydantic models matching the spec JSON Schema.  Seven semantic validation
rules are applied by
:class:`~artha.api_v2.agents.e3_news_scanner.shim.E3NewsScannerShim`.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class NewsCategory(str, Enum):
    MANAGEMENT_CHANGE = "management_change"
    REGULATORY_ACTION = "regulatory_action"
    MERGER_ACQUISITION = "merger_acquisition"
    EARNINGS_GUIDANCE = "earnings_guidance"
    LITIGATION = "litigation"
    OPERATIONAL_DISRUPTION = "operational_disruption"
    CREDIT_RATING_CHANGE = "credit_rating_change"
    OWNERSHIP_CHANGE = "ownership_change"
    CORPORATE_ACTION_ROUTINE = "corporate_action_routine"
    OTHER_MATERIAL = "other_material"
    OTHER_ROUTINE = "other_routine"


class MaterialityLevel(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class SignalDirection(str, Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"


class SignalSeverity(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class NewsEvent(BaseModel):
    model_config = ConfigDict(extra="allow")  # allow published_at which is optional

    news_id: str = Field(min_length=1)
    headline: str = Field(min_length=1)
    category: NewsCategory
    materiality_level: MaterialityLevel
    warrants_cache_invalidation: bool
    rationale: str = Field(min_length=1)


class PerTickerSignals(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticker: str = Field(min_length=1)
    has_material_events: bool
    events: list[NewsEvent] = Field(default_factory=list)


class CaseLevelSignal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    signal: str = Field(min_length=1)
    direction: SignalDirection
    severity: SignalSeverity


class CacheInvalidationPush(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticker: str = Field(min_length=1)
    news_id: str = Field(min_length=1)
    invalidates_e1: bool
    invalidates_e2sis: bool
    reason: str = Field(min_length=1)


class ScanPeriod(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_: str = Field(alias="from", min_length=1)
    to: str = Field(min_length=1)

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class E3NewsScannerOutput(BaseModel):
    """Full E3.NewsScanner verdict (chunk 8.4 §6)."""

    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1)
    scan_period: ScanPeriod
    per_ticker_signals: list[PerTickerSignals] = Field(default_factory=list)
    case_level_signals: list[CaseLevelSignal] = Field(default_factory=list)
    cache_invalidation_pushes: list[CacheInvalidationPush] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning_summary: str = Field(min_length=100)


__all__ = [
    "CacheInvalidationPush",
    "CaseLevelSignal",
    "E3NewsScannerOutput",
    "MaterialityLevel",
    "NewsCategory",
    "NewsEvent",
    "PerTickerSignals",
    "ScanPeriod",
    "SignalDirection",
    "SignalSeverity",
]
