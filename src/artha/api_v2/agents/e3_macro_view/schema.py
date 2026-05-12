"""E3.MacroView output schema — cluster 8 chunk 8.1 §6.

Pydantic models matching the JSON Schema spec.  Six semantic validation
rules are applied by :class:`~artha.api_v2.agents.e3_macro_view.shim.E3MacroViewShim`.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class CyclePositioning(str, Enum):
    EARLY_CUTTING = "early_cutting"
    ACTIVE_CUTTING = "active_cutting"
    LATE_CUTTING_EARLY_PAUSE = "late_cutting_early_pause"
    PAUSE_HOLDING = "pause_holding"
    EARLY_TIGHTENING = "early_tightening"
    ACTIVE_TIGHTENING = "active_tightening"
    LATE_TIGHTENING_EARLY_CUTTING = "late_tightening_early_cutting"
    NEUTRAL_HOLDING = "neutral_holding"


class DirectionalSignal(str, Enum):
    FAVOURABLE = "favourable"
    NEUTRAL = "neutral"
    CHALLENGING = "challenging"


class RateEnvironment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_repo_bps: int
    regime_characterisation: str = Field(min_length=1)
    real_rate_assessment: str = Field(min_length=1)


class ForwardExpectations(BaseModel):
    model_config = ConfigDict(extra="forbid")

    next_3m: str = Field(min_length=1)
    next_6m: str = Field(min_length=1)
    next_12m: str = Field(min_length=1)


class FxView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    inr_outlook: str = Field(min_length=1)
    key_pressures: list[str] = Field(default_factory=list)


class SectorMacroImplication(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sector_code: str = Field(min_length=1)
    implication: str = Field(min_length=1)
    directional_signal: DirectionalSignal


class E3MacroViewOutput(BaseModel):
    """Full E3.MacroView verdict (chunk 8.1 §6)."""

    model_config = ConfigDict(extra="forbid")

    rate_environment: RateEnvironment
    cycle_positioning: CyclePositioning
    forward_expectations: ForwardExpectations
    fx_view: FxView
    sector_macro_implications: list[SectorMacroImplication] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning_summary: str = Field(min_length=200)


__all__ = [
    "CyclePositioning",
    "DirectionalSignal",
    "E3MacroViewOutput",
    "ForwardExpectations",
    "FxView",
    "RateEnvironment",
    "SectorMacroImplication",
]
