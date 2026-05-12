"""E2.SectorView output schema — cluster 8 chunk 8.2 §3.4.

Pydantic models matching the spec JSON Schema.  Six semantic validation
rules are applied by :class:`~artha.api_v2.agents.e2_sector_view.shim.E2SectorViewShim`.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class SectorViewVerdict(str, Enum):
    FAVOURABLE = "favourable"
    NEUTRAL_CONSTRUCTIVE = "neutral_constructive"
    NEUTRAL_CHALLENGING = "neutral_challenging"
    CHALLENGING = "challenging"


class CycleStage(str, Enum):
    EARLY_CYCLE = "early_cycle"
    MID_CYCLE = "mid_cycle"
    LATE_CYCLE = "late_cycle"
    CONTRACTION = "contraction"
    RECOVERY = "recovery"


class StructureType(str, Enum):
    FRAGMENTED = "fragmented"
    FRAGMENTING = "fragmenting"
    CONSOLIDATING = "consolidating"
    CONSOLIDATED = "consolidated"


class RegulatoryIntensity(str, Enum):
    LIGHT = "light"
    MODERATE = "moderate"
    INTENSIVE = "intensive"


class CompetitiveStructure(BaseModel):
    model_config = ConfigDict(extra="forbid")

    structure_type: StructureType
    concentration_trend: str = Field(min_length=1)


class RegulatoryEnvironment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intensity: RegulatoryIntensity
    key_considerations: list[str] = Field(default_factory=list)


class E2SectorViewOutput(BaseModel):
    """Full E2.SectorView verdict (chunk 8.2 §3.4)."""

    model_config = ConfigDict(extra="forbid")

    sector_code: str = Field(min_length=1)
    sector_view_verdict: SectorViewVerdict
    cycle_stage: CycleStage
    dominant_themes: list[str] = Field(min_length=2, max_length=4)
    competitive_structure: CompetitiveStructure
    regulatory_environment: RegulatoryEnvironment
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning_summary: str = Field(min_length=200)


__all__ = [
    "CompetitiveStructure",
    "CycleStage",
    "E2SectorViewOutput",
    "RegulatoryEnvironment",
    "RegulatoryIntensity",
    "SectorViewVerdict",
    "StructureType",
]
