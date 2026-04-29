"""§15.10–15.12 — monitoring & reflection layer schemas.

  * §15.12.1 — `N0Alert`: the four-tier notification channel emitted by PM1, M1, E3.
  * §15.10.1 — `PM1Event`: portfolio monitoring (drift, thesis, benchmark, threshold).
  * §15.11.2 — `T2ReflectionRun`: monthly + event-triggered reflection findings.
  * §15.11.3 — `EX1Event`: deterministic exception-routing event.
  * §15.10.2 — `M1DriftReport`: M1's per-client daily breach report.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from artha.common.types import (
    AlertTier,
    ConfidenceField,
    InputsUsedManifest,
    RunMode,
    WatchState,
)

# ===========================================================================
# §15.12.1 — N0 alert (channel substrate; emitted by PM1, M1, E3, EX1)
# ===========================================================================


class N0Originator(str, Enum):
    """§10.2 — components that originate N0 alerts."""

    PM1 = "PM1"
    M1 = "M1"
    E3 = "E3"
    EX1 = "EX1"


class N0AlertCategory(str, Enum):
    """§10.2 — semantic category of an N0 alert."""

    DRIFT = "drift"
    THESIS_VALIDITY = "thesis_validity"
    BENCHMARK_DIVERGENCE = "benchmark_divergence"
    THRESHOLD_BREACH = "threshold_breach"
    MANDATE_BREACH = "mandate_breach"
    REGIME_WATCH = "regime_watch"
    EXCEPTION = "exception"


class WatchMetadata(BaseModel):
    """§10.2.3 / §15.12.1 — metadata for WATCH-tier alerts (E3-originated in MVP)."""

    model_config = ConfigDict(extra="forbid")

    probability: ConfidenceField
    confidence_band: str
    resolution_horizon_days: int
    impact_if_resolved: str
    state: WatchState = WatchState.ACTIVE_WATCH


class N0Alert(BaseModel):
    """§15.12.1 — a single notification-channel alert."""

    model_config = ConfigDict(extra="forbid")

    alert_id: str  # ULID
    originator: N0Originator
    tier: AlertTier
    category: N0AlertCategory
    case_id: str | None = None
    client_id: str
    firm_id: str
    created_at: datetime

    title: str
    body: str
    expected_action: str = ""

    # Optional structured pointers
    related_event_id: str | None = None  # T1 event id
    related_holding_id: str | None = None
    related_constraint_id: str | None = None
    watch_metadata: WatchMetadata | None = None
    delivery_state: Literal["queued", "delivered", "acknowledged", "expired"] = "queued"

    inputs_used_manifest: InputsUsedManifest = Field(default_factory=InputsUsedManifest)
    input_hash: str = ""


# ===========================================================================
# §15.10.1 — PM1Event
# ===========================================================================


class PM1EventType(str, Enum):
    """§13.6 — taxonomy of portfolio monitoring events."""

    DRIFT = "drift"
    THESIS_VALIDITY = "thesis_validity"
    BENCHMARK_DIVERGENCE = "benchmark_divergence"
    THRESHOLD_BREACH = "threshold_breach"


class ThesisValidityStatus(str, Enum):
    """§13.6 — thesis-validity outcome categories."""

    VALIDATED = "validated"
    PARTIALLY_VALIDATED = "partially_validated"
    CONTRADICTED = "contradicted"
    INDETERMINATE = "indeterminate"


class PM1DriftDetail(BaseModel):
    """§13.6 / §15.10.1 — drift-event payload."""

    model_config = ConfigDict(extra="forbid")

    dimension: Literal["l1", "l2", "l3"]
    cell_key: str
    expected_value: float
    observed_value: float
    drift_magnitude: float
    threshold_band: float


class PM1ThesisValidityDetail(BaseModel):
    """§13.6 / §15.10.1 — thesis-validity event payload."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    thesis_dimension: str
    status: ThesisValidityStatus
    rationale: str = ""
    confidence: ConfidenceField = 0.0


class PM1BenchmarkDivergenceDetail(BaseModel):
    """§13.6 / §15.10.1 — benchmark-divergence event payload."""

    model_config = ConfigDict(extra="forbid")

    benchmark_id: str
    portfolio_return_period: float
    benchmark_return_period: float
    divergence_magnitude: float
    rolling_window_days: int


class PM1ThresholdBreachDetail(BaseModel):
    """§13.6 / §15.10.1 — threshold-breach event payload."""

    model_config = ConfigDict(extra="forbid")

    threshold_rule_id: str
    observed_value: float
    breach_magnitude: float
    mandate_implication: str = ""


class PM1Event(BaseModel):
    """§15.10.1 — a PM1 event captured to T1 + (when material) emitted to N0."""

    model_config = ConfigDict(extra="forbid")

    agent_id: Literal["portfolio_monitoring"] = "portfolio_monitoring"
    event_id: str  # ULID
    case_id: str | None = None
    client_id: str
    firm_id: str
    timestamp: datetime
    run_mode: RunMode = RunMode.CASE
    event_type: PM1EventType

    # Per-type payload — exactly one populated.
    drift_detail: PM1DriftDetail | None = None
    thesis_validity_detail: PM1ThesisValidityDetail | None = None
    benchmark_divergence_detail: PM1BenchmarkDivergenceDetail | None = None
    threshold_breach_detail: PM1ThresholdBreachDetail | None = None

    # Optional N0 alert pointer (when this event surfaces a notification)
    originating_n0_alert_id: str | None = None

    inputs_used_manifest: InputsUsedManifest = Field(default_factory=InputsUsedManifest)
    input_hash: str
    agent_version: str = "0.1.0"


# ===========================================================================
# §15.10.2 — M1 drift report
# ===========================================================================


class M1BreachType(str, Enum):
    """§7.7 — categories of mandate breach M1 detects."""

    ASSET_CLASS_CEILING = "asset_class_ceiling"
    ASSET_CLASS_FLOOR = "asset_class_floor"
    VEHICLE_LIMIT = "vehicle_limit"
    SECTOR_HARD_BLOCK = "sector_hard_block"
    LIQUIDITY_FLOOR = "liquidity_floor"
    LIQUIDITY_WINDOW = "liquidity_window"
    CONCENTRATION = "concentration"


class M1Breach(BaseModel):
    """§15.10.2 — one mandate breach surfaced by M1's daily sweep."""

    model_config = ConfigDict(extra="forbid")

    breach_type: M1BreachType
    constraint_id: str
    current_value: float
    limit_value: float
    breach_magnitude: float
    description: str = ""


class M1DriftReport(BaseModel):
    """§15.10.2 — per-client M1 daily report.

    The report aggregates every breach found on the sweep date. Even if no
    breaches exist, M1 emits an empty report so the daily cadence is auditable.
    """

    model_config = ConfigDict(extra="forbid")

    agent_id: Literal["mandate_drift_monitor"] = "mandate_drift_monitor"
    report_id: str  # ULID
    client_id: str
    firm_id: str
    mandate_id: str
    mandate_version: int
    sweep_date: date
    timestamp: datetime
    breaches: list[M1Breach] = Field(default_factory=list)
    out_of_bucket_flag: bool = False  # §7.10 Test 10
    n0_alert_ids: list[str] = Field(default_factory=list)
    inputs_used_manifest: InputsUsedManifest = Field(default_factory=InputsUsedManifest)
    input_hash: str
    agent_version: str = "0.1.0"


# ===========================================================================
# §15.11.3 — EX1 event
# ===========================================================================


class ExceptionCategory(str, Enum):
    """§13.9.2 — taxonomy of exception categories."""

    INPUT_DATA_MISSING = "input_data_missing"
    SCHEMA_VIOLATION = "schema_violation"
    SERVICE_UNAVAILABLE = "service_unavailable"
    COMPONENT_CONFLICT = "component_conflict"
    TIMEOUT = "timeout"
    GOVERNANCE_RULE_MISMATCH = "governance_rule_mismatch"
    CASCADING_EXCEPTION = "cascading_exception"


class ExceptionSeverity(str, Enum):
    """§13.9 — severity of an exception."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class RoutingDecision(str, Enum):
    """§13.9.4 — how EX1 routes a given exception."""

    LOG_AND_PROCEED_WITH_FLAG = "log_and_proceed_with_flag"
    RETRY_ONCE = "retry_once"
    FALLBACK_TO_PRIOR_VERSION = "fallback_to_prior_version"
    ESCALATE_TO_ADVISOR = "escalate_to_advisor"
    ESCALATE_TO_SENIOR_ADVISOR = "escalate_to_senior_advisor"
    ESCALATE_TO_COMPLIANCE = "escalate_to_compliance"
    ESCALATE_TO_FIRM_LEADERSHIP = "escalate_to_firm_leadership"


class EX1Event(BaseModel):
    """§15.11.3 — one EX1 routing event."""

    model_config = ConfigDict(extra="forbid")

    agent_id: Literal["exception_handler"] = "exception_handler"
    event_id: str  # ULID
    timestamp: datetime
    case_id: str | None = None
    client_id: str | None = None
    firm_id: str

    originating_component: str  # e.g. "e1.financial_risk", "m0.briefer"
    originating_event_id: str | None = None
    exception_category: ExceptionCategory
    severity: ExceptionSeverity

    routing_decision: RoutingDecision
    flag_propagated: bool = False
    escalation_target_id: str | None = None  # advisor_id / supervisor_id / etc.
    cascade_depth: int = 0
    cascade_threshold_breached: bool = False

    routing_rule_table_version: str
    rationale: str = ""

    inputs_used_manifest: InputsUsedManifest = Field(default_factory=InputsUsedManifest)
    input_hash: str
    agent_version: str = "0.1.0"


# ===========================================================================
# §15.11.2 — T2 reflection run
# ===========================================================================


class T2RunType(str, Enum):
    """§13.8 — T2 cadence."""

    SCHEDULED_MONTHLY = "scheduled_monthly"
    EVENT_TRIGGERED = "event_triggered"


class T2FindingCategory(str, Enum):
    """§13.8 — analytical-category taxonomy."""

    OUTCOME_ATTRIBUTION = "outcome_attribution"
    CONFIDENCE_CALIBRATION = "confidence_calibration"
    FLAG_FIRING_RATE = "flag_firing_rate"
    BRIEFING_BIAS = "briefing_bias"
    WATCH_PROBABILITY_CALIBRATION = "watch_probability_calibration"
    DRIFT_TRIGGER_CALIBRATION = "drift_trigger_calibration"
    RULE_CORPUS_IMPACT = "rule_corpus_impact"


class T2FindingSeverity(str, Enum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class T2Finding(BaseModel):
    """§15.11.2 — one structured finding inside a reflection run."""

    model_config = ConfigDict(extra="forbid")

    finding_id: str
    category: T2FindingCategory
    severity: T2FindingSeverity = T2FindingSeverity.INFO
    observation: str
    supporting_t1_event_ids: list[str] = Field(default_factory=list)


class T2PromptUpdateProposal(BaseModel):
    """§15.11.2 — proposed prompt change for a component."""

    model_config = ConfigDict(extra="forbid")

    component_id: str  # e.g. "e1.financial_risk"
    prompt_section: str  # e.g. "system_prompt.discipline"
    proposed_change: str
    rationale: str = ""
    supporting_findings: list[str] = Field(default_factory=list)


class T2RuleUpdateProposal(BaseModel):
    """§15.11.2 — proposed G2 rule update."""

    model_config = ConfigDict(extra="forbid")

    rule_id: str
    proposed_change: str
    rationale: str = ""
    supporting_findings: list[str] = Field(default_factory=list)


class T2CalibrationCurve(BaseModel):
    """§15.11.2 — per-component calibration curve."""

    model_config = ConfigDict(extra="forbid")

    component_id: str
    sample_size: int
    curve_data: list[tuple[float, float]] = Field(default_factory=list)
    bucket_count: int = 0


class T2RunStatus(str, Enum):
    """§15.11.2 — governance-review lifecycle."""

    IN_GOVERNANCE_REVIEW = "in_governance_review"
    APPROVED = "approved"
    REJECTED = "rejected"


class T2ReflectionRun(BaseModel):
    """§15.11.2 — one reflection run."""

    model_config = ConfigDict(extra="forbid")

    agent_id: Literal["t2_reflection"] = "t2_reflection"
    run_id: str  # ULID
    run_type: T2RunType
    period_start_at: datetime
    period_end_at: datetime
    timestamp: datetime
    firm_id: str
    scope_components: list[str] = Field(default_factory=list)
    scope_case_types: list[str] = Field(default_factory=list)

    findings: list[T2Finding] = Field(default_factory=list)
    prompt_update_proposals: list[T2PromptUpdateProposal] = Field(default_factory=list)
    rule_update_proposals: list[T2RuleUpdateProposal] = Field(default_factory=list)
    calibration_curves: list[T2CalibrationCurve] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)

    status: T2RunStatus = T2RunStatus.IN_GOVERNANCE_REVIEW

    inputs_used_manifest: InputsUsedManifest = Field(default_factory=InputsUsedManifest)
    input_hash: str
    prompt_version: str = "0.1.0"
    agent_version: str = "0.1.0"


# ===========================================================================
# Internal LLM-output schema for T2 findings
# ===========================================================================


class _LlmT2Output(BaseModel):
    """Internal schema for T2's LLM-produced findings + proposals."""

    model_config = ConfigDict(extra="forbid")

    findings: list[T2Finding] = Field(default_factory=list)
    prompt_update_proposals: list[T2PromptUpdateProposal] = Field(default_factory=list)
    rule_update_proposals: list[T2RuleUpdateProposal] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    reasoning_trace: str = ""


# ===========================================================================
# Internal LLM-output schema for PM1 thesis-validity
# ===========================================================================


class _LlmPM1ThesisOutput(BaseModel):
    """Internal schema for PM1's LLM-produced thesis-validity output."""

    model_config = ConfigDict(extra="forbid")

    status: ThesisValidityStatus
    rationale: str = ""
    confidence: ConfidenceField = 0.0


__all__ = [
    "EX1Event",
    "ExceptionCategory",
    "ExceptionSeverity",
    "M1Breach",
    "M1BreachType",
    "M1DriftReport",
    "N0Alert",
    "N0AlertCategory",
    "N0Originator",
    "PM1BenchmarkDivergenceDetail",
    "PM1DriftDetail",
    "PM1Event",
    "PM1EventType",
    "PM1ThesisValidityDetail",
    "PM1ThresholdBreachDetail",
    "RoutingDecision",
    "T2CalibrationCurve",
    "T2Finding",
    "T2FindingCategory",
    "T2FindingSeverity",
    "T2PromptUpdateProposal",
    "T2ReflectionRun",
    "T2RuleUpdateProposal",
    "T2RunStatus",
    "T2RunType",
    "ThesisValidityStatus",
    "WatchMetadata",
    "_LlmPM1ThesisOutput",
    "_LlmT2Output",
]
