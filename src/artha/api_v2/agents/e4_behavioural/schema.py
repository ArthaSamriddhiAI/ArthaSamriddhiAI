"""E4 Behavioural output schema — cluster 9 chunk 9.3 §8."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class BehaviouralVerdict(str, Enum):
    DISCIPLINED = "disciplined"
    MODERATE_EMOTIONAL = "moderate_emotional"
    REACTIVE = "reactive"
    PANIC_PRONE = "panic_prone"
    UNTESTED = "untested"


class TradingFrequency(str, Enum):
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    VERY_HIGH = "very_high"


class MandateConsistency(str, Enum):
    CONSISTENT = "consistent"
    MOSTLY_CONSISTENT = "mostly_consistent"
    DRIFT_OBSERVED = "drift_observed"
    FREQUENTLY_DEVIATES = "frequently_deviates"


class DecisionSpeed(str, Enum):
    FAST = "fast"
    MODERATE = "moderate"
    SLOW = "slow"
    HIGHLY_DELIBERATIVE = "highly_deliberative"


class ModificationFrequency(str, Enum):
    RARE = "rare"
    OCCASIONAL = "occasional"
    FREQUENT = "frequent"
    CONSTANT = "constant"


class EscalationTendency(str, Enum):
    ACCEPTS_RECOMMENDATIONS = "accepts_recommendations"
    QUESTIONS_THEN_ACCEPTS = "questions_then_accepts"
    NEGOTIATES = "negotiates"
    FREQUENTLY_OVERRIDES = "frequently_overrides"


class PanicSeverity(str, Enum):
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"


class PreferredChannel(str, Enum):
    IN_PERSON = "in_person"
    PHONE = "phone"
    EMAIL = "email"
    WHATSAPP = "whatsapp"
    VIDEO_CALL = "video_call"
    MIXED = "mixed"


class DetailLevel(str, Enum):
    HEADLINES_ONLY = "headlines_only"
    SUMMARY = "summary"
    DETAILED = "detailed"
    EXHAUSTIVE = "exhaustive"


class BiasType(str, Enum):
    LOSS_AVERSION = "loss_aversion"
    RECENCY_BIAS = "recency_bias"
    ANCHORING = "anchoring"
    CONFIRMATION_BIAS = "confirmation_bias"
    OVERCONFIDENCE = "overconfidence"
    HERDING = "herding"
    ENDOWMENT_EFFECT = "endowment_effect"
    STATUS_QUO_BIAS = "status_quo_bias"
    OTHER = "other"


class TradingPatternSignal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    frequency: TradingFrequency
    consistency_with_mandate: MandateConsistency
    deviation_patterns: list[str] = Field(default_factory=list)


class PanicIndicator(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trigger_type: str = Field(min_length=1)
    historical_reaction: str = Field(min_length=1)
    severity: PanicSeverity


class DecisionStyle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    typical_decision_speed: DecisionSpeed
    modification_frequency: ModificationFrequency
    escalation_tendency: EscalationTendency


class CommunicationPreferences(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preferred_channel: PreferredChannel
    preferred_detail_level: DetailLevel
    preferred_cadence: str = Field(min_length=1)


class BiasSignal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bias_type: BiasType
    evidence: str = Field(min_length=10)
    advisory_implication: str = Field(min_length=1)


class E4BehaviouralOutput(BaseModel):
    """Full E4 behavioural profile verdict (chunk 9.3 §8)."""

    model_config = ConfigDict(extra="forbid")

    investor_id: str = Field(min_length=1)
    behavioural_verdict: BehaviouralVerdict
    trading_pattern_signal: TradingPatternSignal
    panic_indicators: list[PanicIndicator] = Field(default_factory=list)
    decision_style: DecisionStyle
    communication_preferences: CommunicationPreferences
    bias_signals: list[BiasSignal] = Field(default_factory=list)
    advisory_implications: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning_summary: str = Field(min_length=200)


__all__ = [
    "BehaviouralVerdict",
    "BiasSignal",
    "BiasType",
    "CommunicationPreferences",
    "DecisionSpeed",
    "DecisionStyle",
    "DetailLevel",
    "E4BehaviouralOutput",
    "EscalationTendency",
    "MandateConsistency",
    "ModificationFrequency",
    "PanicIndicator",
    "PanicSeverity",
    "PreferredChannel",
    "TradingFrequency",
    "TradingPatternSignal",
]
