"""Section 15.7 — evidence agent verdict schemas.

Every E-agent (E1–E6) produces a verdict conforming to the
`StandardEvidenceVerdict` shape per §15.7.1. Per-agent extensions add
agent-specific fields (e.g. E2's `sector_evaluations`, E6's `gate_result`).

Section 11.2.2 / 11.3.2 fix the verdict structure:
  * `risk_level`, `confidence`, `drivers`, `flags` are the headline.
  * `reasoning_trace` is the audit-defence narrative — captured verbatim in
    T1, separate from the structured verdict.
  * `inputs_used_manifest` + `input_hash` enable replay correctness (§3.11).

Per-agent flag vocabularies are listed in §15.7.1; this module captures the
canonical Pydantic shapes. Specific agent classes live in
`artha.evidence.canonical_e1`, `canonical_e2`, etc.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from artha.common.types import (
    ConfidenceField,
    Driver,
    GateResult,
    InputsUsedManifest,
    INRAmountField,
    PercentageField,
    RiskLevel,
    RunMode,
)


class StandardEvidenceVerdict(BaseModel):
    """§15.7.1 — the shared shape every evidence agent verdict honours.

    Per-agent verdict types (E1Verdict, E2Verdict, ...) extend this with
    agent-specific fields. The base shape is what S1 reads when synthesising
    across the layer.
    """

    model_config = ConfigDict(extra="forbid")

    # Identity
    agent_id: str  # "financial_risk" | "industry_analyst" | etc.
    case_id: str
    timestamp: datetime
    run_mode: RunMode = RunMode.CASE

    # Headline verdict
    risk_level: RiskLevel
    confidence: ConfidenceField
    drivers: list[Driver] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    reasoning_trace: str

    # Replay + version pinning (§3.11)
    inputs_used_manifest: InputsUsedManifest = Field(default_factory=InputsUsedManifest)
    input_hash: str  # SHA-256 of the canonicalised input bundle
    model_version: str = ""
    prompt_version: str = "0.1.0"
    agent_version: str = "0.1.0"


# ===========================================================================
# E1 — Financial Risk extension (§11.2 / 15.7)
# ===========================================================================


# E1 flag vocabulary per §15.7.1
E1FlagVocabulary = Literal[
    "concentration_breach",
    "liquidity_floor_proximity",
    "leverage_amplification",
    "cascade_stress",
    "fee_drag_excessive",
    "deployment_inefficient",
    "partial_evaluation",
    "tax_basis_stale_days",
]


class E1DimensionVerdict(BaseModel):
    """Sub-verdict for a single E1 analytical dimension (§11.2.2).

    Each dimension (concentration, leverage, liquidity, etc.) carries its
    own risk + driver. The overall E1 risk is S1's responsibility; E1
    surfaces per-dimension to make the synthesis layer's job easier.
    """

    model_config = ConfigDict(extra="forbid")

    dimension: Literal[
        "concentration",
        "leverage",
        "liquidity",
        "return_quality",
        "deployment",
        "cascade",
    ]
    risk_level: RiskLevel
    summary: str  # one-sentence interpretation


class E1Verdict(StandardEvidenceVerdict):
    """E1 Financial Risk verdict — extends the standard shape with the
    six analytical dimensions and the partial-evaluation flag (§11.2.7)."""

    model_config = ConfigDict(extra="forbid")

    agent_id: Literal["financial_risk"] = "financial_risk"
    dimensions_evaluated: list[E1DimensionVerdict] = Field(default_factory=list)


# ===========================================================================
# E2 — Industry & Business Model extension (§11.3 / 15.7.2)
# ===========================================================================


# E2 flag vocabulary per §15.7.1
E2FlagVocabulary = Literal[
    "sector_weakening_concentration",
    "moat_eroding",
    "lifecycle_decline",
    "regulatory_overhang",
    "low_field_coverage",
    "data_stale_days",
]


class MoatClassification(BaseModel):
    """Per-holding moat verdict (§11.3.2)."""

    model_config = ConfigDict(extra="forbid")

    classification: Literal["none", "narrow", "wide"]
    rationale: str = ""


class IndustryLifecycleStage(BaseModel):
    """Per-sector lifecycle stage (§11.3.2)."""

    model_config = ConfigDict(extra="forbid")

    stage: Literal["emerging", "growth", "maturity", "decline"]
    rationale: str = ""


class FiveForcesScore(BaseModel):
    """Five-forces aggregate score per sector (§11.3.2).

    Each force is rated 1–5 (low to high competitive intensity). Higher
    aggregate = harder operating environment = higher industry risk.
    """

    model_config = ConfigDict(extra="forbid")

    rivalry: int = Field(ge=1, le=5)
    buyer_power: int = Field(ge=1, le=5)
    supplier_power: int = Field(ge=1, le=5)
    substitution: int = Field(ge=1, le=5)
    entry_barriers: int = Field(ge=1, le=5)


class E2SectorEvaluation(BaseModel):
    """Per-sector evaluation row in E2's verdict extension (§15.7.2)."""

    model_config = ConfigDict(extra="forbid")

    sector: str
    sub_industry: str = ""
    sector_weight: PercentageField  # share of portfolio in this sector
    moat: MoatClassification | None = None
    lifecycle: IndustryLifecycleStage | None = None
    five_forces: FiveForcesScore | None = None
    evidence: list[str] = Field(default_factory=list)


class E2PortfolioQualityVerdict(BaseModel):
    """Roll-up across all sectors (§15.7.2)."""

    model_config = ConfigDict(extra="forbid")

    overall_risk_level: RiskLevel
    overall_confidence: ConfidenceField
    drivers: list[Driver] = Field(default_factory=list)


class E2Verdict(StandardEvidenceVerdict):
    """E2 Industry Analyst verdict — extends standard with per-sector + portfolio roll-up."""

    model_config = ConfigDict(extra="forbid")

    agent_id: Literal["industry_analyst"] = "industry_analyst"
    sector_evaluations: list[E2SectorEvaluation] = Field(default_factory=list)
    portfolio_quality_verdict: E2PortfolioQualityVerdict | None = None
    field_coverage_pct: PercentageField = 1.0
    data_as_of: date | None = None


# ===========================================================================
# Internal LLM-output schemas (string-typed for mock provider compatibility)
# ===========================================================================


class _LlmEvidenceCore(BaseModel):
    """Internal schema for the LLM's evidence output. The agent service maps
    this onto the canonical typed verdict after validating against the enum."""

    model_config = ConfigDict(extra="forbid")

    risk_level_value: str  # validated against RiskLevel enum
    confidence: ConfidenceField
    drivers: list[Driver] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    reasoning_trace: str


# ===========================================================================
# E3 — Macro & Policy extension (§11.4 / 15.7.3)
# ===========================================================================


# E3 flag vocabulary per §15.7.1
E3FlagVocabulary = Literal[
    "rate_cycle_inflection_imminent",
    "inflation_persistence_elevated",
    "currency_pressure_building",
    "fiscal_stress",
    "monetary_regime_transitioning",
    "structural_theme_emerging",
]


class MacroDimension(str, Enum):
    """The six macro dimensions E3 evaluates per §11.4.2."""

    RATE_ENVIRONMENT = "rate_environment"
    INFLATION = "inflation"
    CURRENCY = "currency"
    FISCAL_STANCE = "fiscal_stance"
    MONETARY_REGIME = "monetary_regime"
    STRUCTURAL_THEMES = "structural_themes"


class ConfidenceBandLabel(str, Enum):
    """Confidence band labels for watch metadata (mirrors `standards.ConfidenceBand`).

    Duplicated here to avoid `canonical/` importing from `common.standards` (cycle
    risk). The labels match Section 3.2 anchors so consumers can map between them.
    """

    VIRTUALLY_CERTAIN = "virtually_certain"
    HIGH = "high"
    MODERATE = "moderate"
    LOW = "low"
    UNCERTAIN = "uncertain"


class WatchCandidate(BaseModel):
    """Section 10.2.3 / 11.4.2 — a probability-weighted regime shift E3 is tracking.

    Pre-N0: Pass 9 emits these on E3's verdict; Pass 14 (N0 channel) wraps them
    into N0 alerts at the WATCH tier. The fields match `n0_alert.watch_metadata`
    per Section 15.12.1 so the conversion is mechanical.
    """

    model_config = ConfigDict(extra="forbid")

    dimension: MacroDimension
    probability: ConfidenceField  # 0.0–1.0 likelihood event resolves as anticipated
    confidence_band: ConfidenceBandLabel
    resolution_horizon_days: int
    impact_if_resolved: str  # short structured description of system response


class RegimeAssessment(BaseModel):
    """Per-dimension assessment within E3's verdict (§11.4.2)."""

    model_config = ConfigDict(extra="forbid")

    dimension: MacroDimension
    risk_level: RiskLevel
    confidence: ConfidenceField
    summary: str  # one-sentence regime characterisation


class E3Verdict(StandardEvidenceVerdict):
    """E3 Macro Policy verdict — extends standard with regime assessments + watch candidates.

    `watch_candidates` may be empty for routine cases. When non-empty, each entry
    becomes an N0 WATCH-tier alert (Pass 14).
    """

    model_config = ConfigDict(extra="forbid")

    agent_id: Literal["macro_policy"] = "macro_policy"
    regime_assessments: list[RegimeAssessment] = Field(default_factory=list)
    watch_candidates: list[WatchCandidate] = Field(default_factory=list)
    data_as_of: date | None = None


# ===========================================================================
# E4 — Behavioural & Historical extension (§11.5 / 15.7.4)
# ===========================================================================


# E4 flag vocabulary per §15.7.1
E4FlagVocabulary = Literal[
    "revealed_tolerance_below_stated",
    "override_pattern_inconsistent",
    "redemption_history_volatile",
    "limited_history",
    "no_history",
    "horizon_adherence_weak",
]


class BehaviouralHistorySummary(BaseModel):
    """Aggregated history for E4 to reason over (§11.5.5).

    The substrate comes from T1; this is the structured summary E4's prompt
    consumes. Tests inject in-memory summaries; Phase D wires this through a
    `BehaviouralHistoryProvider` reading T1 directly.

    `historical_window_days` and `event_count` populate E4Verdict's extension
    fields per §15.7.4. Other fields are descriptive signals the prompt cites.
    """

    model_config = ConfigDict(extra="forbid")

    historical_window_days: int = 0
    event_count: int = 0
    redemption_count_in_drawdowns: int = 0
    redemption_count_total: int = 0
    override_count: int = 0
    override_direction_more_risk: int = 0  # toward more risk
    override_direction_less_risk: int = 0
    horizon_adherence_score: ConfidenceField | None = None  # 0-1, higher = more adherent
    stated_risk_tolerance: str | None = None  # the mandate's stated tolerance
    revealed_risk_pattern: str | None = None  # qualitative summary


class E4Verdict(StandardEvidenceVerdict):
    """E4 Behavioural / Historical verdict (§15.7.4)."""

    model_config = ConfigDict(extra="forbid")

    agent_id: Literal["behavioural_historical"] = "behavioural_historical"
    historical_window_evaluated_days: int = 0
    historical_event_count: int = 0


# ===========================================================================
# E5 — Unlisted Equity Specialist extension (§11.6 / 15.7.5)
# ===========================================================================


# E5 flag vocabulary per §15.7.1
E5FlagVocabulary = Literal[
    "valuation_stale",
    "valuation_severely_stale",
    "exit_uncertainty",
    "regulatory_overlay",
    "comparables_unavailable",
]


class E5HoldingEvaluation(BaseModel):
    """Per-unlisted-holding evaluation row (§11.6.2 / 15.7.5).

    Each unlisted equity holding gets one of these. `exit_pathway_probabilities`
    must sum to 1.0 (validated; per §11.6.8 Test 6).
    """

    model_config = ConfigDict(extra="forbid")

    holding_id: str
    valuation_age_days: int
    valuation_basis: Literal[
        "last_funding_round", "third_party", "mark_to_model", "unknown"
    ] = "unknown"
    valuation_severely_stale: bool = False  # >24 months
    implied_valuation_inr: float | None = None  # from listed comparables, if any
    exit_pathway_probabilities: dict[str, ConfidenceField] = Field(default_factory=dict)
    illiquidity_premium_assessment: str = ""
    regulatory_standing: str = ""


class E5Verdict(StandardEvidenceVerdict):
    """E5 Unlisted Equity Specialist verdict (§15.7.5)."""

    model_config = ConfigDict(extra="forbid")

    agent_id: Literal["unlisted_specialist"] = "unlisted_specialist"
    per_holding_evaluations: list[E5HoldingEvaluation] = Field(default_factory=list)
    valuation_data_as_of: date | None = None
    comparable_data_as_of: date | None = None


# ===========================================================================
# E6 — PMS / AIF / SIF / MF Specialist extension (§11.7 / 15.7.6)
# ===========================================================================


# E6 flag vocabulary per §15.7.1
E6FlagVocabulary = Literal[
    "gate_risk",
    "leverage_elevated",
    "tax_collision_fy27",
    "fund_level_tax_drag",
    "sub_agent_unavailable",
    "look_through_unavailable",
    "suitability_conditions_pending",
]


class FundRiskScore(str, Enum):
    """§15.7.6 — five-level quality classification per fund-risk dimension.

    Order from best to worst: strong, sound, caution, elevated, low.
    """

    STRONG = "strong"
    SOUND = "sound"
    CAUTION = "caution"
    ELEVATED = "elevated"
    LOW = "low"


class FundRiskScores(BaseModel):
    """Per-product fund-risk score block (§15.7.6)."""

    model_config = ConfigDict(extra="forbid")

    manager_quality: FundRiskScore
    strategy_consistency: FundRiskScore
    fee_reasonableness: FundRiskScore
    operational_risk: FundRiskScore
    liquidity_risk: FundRiskScore


class NormalisedReturns(BaseModel):
    """§15.7.6 — gross + net-of-all-fees returns from E6.FeeNormalisation."""

    model_config = ConfigDict(extra="forbid")

    gross_return: float | None = None
    net_of_costs_return: float | None = None
    net_of_costs_and_taxes_return: float | None = None
    counterfactual_model_portfolio_return: float | None = None
    counterfactual_delta: float | None = None  # proposed minus model_portfolio


class CascadeAssessment(BaseModel):
    """§15.7.6 — E6.CascadeEngine output: forecast cash flows + deployment modelling.

    `cash_flow_schedule` references `CascadeEvent` shapes from `canonical.holding`.
    `deployment_modelling` is firm-specific; Pass 10 carries a permissive dict.
    """

    model_config = ConfigDict(extra="forbid")

    cash_flow_schedule: list["CascadeEvent"] = Field(default_factory=list)
    deployment_modelling: dict[str, float] = Field(default_factory=dict)
    expected_distribution_inr: float = 0.0
    expected_capital_calls_inr: float = 0.0


class TaxYearProjection(BaseModel):
    """§15.7.6 — per-FY tax projection from E6.RecommendationSynthesis."""

    model_config = ConfigDict(extra="forbid")

    fy_label: str  # e.g. "FY26-27"
    estimated_tax_inr: INRAmountField = 0.0
    notes: str = ""


class LiquidityManagerOutput(BaseModel):
    """§15.7.6 — E6.LiquidityManager output."""

    model_config = ConfigDict(extra="forbid")

    cumulative_unfunded_commitment_inr: INRAmountField = 0.0
    liquidity_floor_check_result: bool = True
    most_liquid_bucket_share: PercentageField = 0.0


class SuitabilityCondition(BaseModel):
    """§15.7.6 — a structured condition the advisor must follow through on."""

    model_config = ConfigDict(extra="forbid")

    condition: str
    follow_through_check: str
    evidence_required: str


class E6Verdict(StandardEvidenceVerdict):
    """§15.7.6 — E6 PMS/AIF/SIF/MF Specialist verdict.

    `gate_result` is the structural-flag gate verdict per §11.7.1. SOFT_BLOCK
    or HARD_BLOCK overrides product analysis: the orchestrator may skip
    product sub-agents and produce a gate-only verdict (§11.7.1).
    """

    model_config = ConfigDict(extra="forbid")

    agent_id: Literal["pms_aif_specialist"] = "pms_aif_specialist"
    fund_risk_scores: FundRiskScores | None = None
    sub_agent_verdicts: list[StandardEvidenceVerdict] = Field(default_factory=list)
    normalised_returns: NormalisedReturns | None = None
    cascade_assessment: CascadeAssessment | None = None
    tax_year_projection: list[TaxYearProjection] = Field(default_factory=list)
    liquidity_manager_output: LiquidityManagerOutput | None = None
    forcing_function_disclosures: list[str] = Field(default_factory=list)
    suitability_conditions: list[SuitabilityCondition] = Field(default_factory=list)
    gate_result: GateResult


# Forward-ref resolution for CascadeAssessment.cash_flow_schedule
from artha.canonical.holding import CascadeEvent  # noqa: E402

CascadeAssessment.model_rebuild()
