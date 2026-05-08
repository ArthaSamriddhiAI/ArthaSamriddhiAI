"""E1 output schema — cluster 7 chunk 7.1 §7.

Pydantic models matching the JSON Schema spec from chunk 7.1 §7. The
Pydantic flavour keeps validation Pythonic (no extra ``jsonschema``
dep) while still expressing the same constraints (required fields,
enum values, min/max bounds, length thresholds).

Schema is enforced at the EX1 dispatcher boundary (chunk 7.1 §3) — any
LLM-produced output that fails to round-trip through :class:`E1Output`
counts as a schema violation and triggers retry.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class E1Verdict(str, Enum):
    """The five canonical per-stock verdicts (chunk 7.1 §7)."""

    POSITIVE = "positive"
    POSITIVE_WITH_VALUATION_CAUTION = "positive_with_valuation_caution"
    HOLD_WITH_ATTENTION = "hold_with_attention"
    NEGATIVE = "negative"
    SPECIAL_SITUATION = "special_situation"


class E1FrameworkAxis(str, Enum):
    """Per-stock framework axis (chunk 7.1 §7)."""

    QUALITY_MATURITY_BEST_IN_CLASS = "quality_maturity_best_in_class"
    QUALITY_GROWTH_EMERGING = "quality_growth_emerging"
    VALUE_DISTRESSED_SPECIAL_SITUATION = "value_distressed_special_situation"
    CYCLICAL_POSITION = "cyclical_position"
    STRUCTURAL_GROWTH = "structural_growth"


class E1DriverWeight(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class E1KeyDriver(BaseModel):
    """One driver of the verdict with its relative weight."""

    model_config = ConfigDict(extra="forbid")

    driver: str = Field(min_length=1)
    weight: E1DriverWeight


class E1Framework(BaseModel):
    """Per-stock framework positioning."""

    model_config = ConfigDict(extra="forbid")

    framework_axis: E1FrameworkAxis
    axis_value: str = Field(default="")


class E1Metric(BaseModel):
    """One metric family's evaluation. Schema is intentionally loose
    here (free-form ``dict`` content) so prompts can evolve without
    cascading schema changes; semantic validation in the shim catches
    structural issues."""

    model_config = ConfigDict(extra="allow")


class E1MetricEvaluations(BaseModel):
    """The six required metric families (chunk 7.1 §7 + §8.3).

    Schema rule (chunk 7.1 §8.3): all six families must be present.
    Sub-shapes are loose — the LLM may include richer detail per
    metric, captured via the ``extra="allow"`` config on
    :class:`E1Metric`.
    """

    model_config = ConfigDict(extra="forbid")

    roce: E1Metric
    leverage: E1Metric
    earnings_quality: E1Metric
    valuation: E1Metric
    growth: E1Metric
    margins: E1Metric


class E1Output(BaseModel):
    """The full E1 verdict. Validates LLM responses end-to-end (chunk
    7.1 §7 + §8)."""

    model_config = ConfigDict(extra="forbid")

    ticker: str = Field(min_length=1)
    verdict: E1Verdict
    confidence: float = Field(ge=0.0, le=1.0)
    metric_evaluations: E1MetricEvaluations
    per_stock_framework: E1Framework
    risk_signals: list[str] = Field(default_factory=list)
    reasoning_summary: str = Field(min_length=200)
    key_drivers: list[E1KeyDriver] = Field(default_factory=list)


__all__ = [
    "E1DriverWeight",
    "E1Framework",
    "E1FrameworkAxis",
    "E1KeyDriver",
    "E1Metric",
    "E1MetricEvaluations",
    "E1Output",
    "E1Verdict",
]
