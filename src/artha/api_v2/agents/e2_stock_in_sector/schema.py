"""E2.StockInSector output schema — cluster 8 chunk 8.2 §4.4.

Pydantic models matching the spec JSON Schema.  Five semantic validation
rules are applied by
:class:`~artha.api_v2.agents.e2_stock_in_sector.shim.E2StockInSectorShim`.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class StockInSectorVerdict(str, Enum):
    BEST_IN_CLASS = "best_in_class"
    ABOVE_MEDIAN = "above_median"
    MEDIAN_PLAYER = "median_player"
    BELOW_MEDIAN = "below_median"
    CHALLENGED_POSITION = "challenged_position"


class SectorQuartile(str, Enum):
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


class PositioningWithinSector(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sector_quartile: SectorQuartile
    ranking_framework: str = Field(min_length=1)
    key_competitive_attributes: list[str] = Field(default_factory=list)


class SectorRelativeSignal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    signal: str = Field(min_length=1)
    direction: SignalDirection
    severity: SignalSeverity


class E2StockInSectorOutput(BaseModel):
    """Full E2.StockInSector verdict (chunk 8.2 §4.4)."""

    model_config = ConfigDict(extra="forbid")

    ticker: str = Field(min_length=1)
    sector_code: str = Field(min_length=1)
    stock_in_sector_verdict: StockInSectorVerdict
    positioning_within_sector: PositioningWithinSector
    sector_relative_signals: list[SectorRelativeSignal] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning_summary: str = Field(min_length=200)


__all__ = [
    "E2StockInSectorOutput",
    "PositioningWithinSector",
    "SectorQuartile",
    "SectorRelativeSignal",
    "SignalDirection",
    "SignalSeverity",
    "StockInSectorVerdict",
]
