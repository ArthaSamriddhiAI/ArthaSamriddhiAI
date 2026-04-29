"""Section 3 system-level standards as code — single source of truth.

Section 3 of the consolidation spec defines fourteen normalisation concerns that
must not be redefined per agent. Every component imports from here rather than
re-declaring rubrics, formatters, vocabulary, or protocol limits. When a component
needs an exception, the exception lives at the component level with an explicit
reference back to the standard it extends.

Sections covered here:

    3.1  Risk level rubric .... amplify_risk_level
    3.2  Confidence rubric .... ConfidenceBand, confidence_band
    3.3  Currency / number .... format_inr, format_percentage, format_basis_points, format_return
    3.4  Time horizon vocab ... TIME_HORIZON_YEARS, is_vague_time_phrase
    3.5  Counterfactual ref ... helpers live in the model_portfolio module
    3.6  Decision tier vocab .. see common.types.DecisionTier, GateResult, Permission
    3.7  Model portfolio ref .. version pin guidance; helpers in model_portfolio module
    3.8  Mandate reference .... version pin guidance; helpers in mandate module
    3.9  Investor ctx ref ..... ACTIVE_INVESTOR_CONTEXT_FIELDS, assert_field_is_active
    3.10 Override mechanics ... OverrideReasonCategory, OverrideRecord, OverrideClarificationRequest
    3.11 Telemetry schema ..... T1EventType, T1_BASE_REQUIRED_FIELDS
    3.12 Agent comms protocol . ClarificationRequest, see also 3.14
    3.13 Error/exception ...... ExceptionCategory, ExceptionRoutingDecision
    3.14 M0 briefing/clar ..... BRIEFING_TOKEN_MIN/MAX, CLARIFICATION_*, briefing_within_budget
"""

from __future__ import annotations

import re
from enum import Enum

from pydantic import BaseModel, Field

from artha.common.types import (
    Confidence,
    RiskLevel,
    TimeHorizon,
    validate_confidence,
)

# ===========================================================================
# 3.1 Risk level rubric
# ===========================================================================


def amplify_risk_level(component_levels: list[RiskLevel]) -> RiskLevel:
    """S1's amplification rule (Section 3.1): independent component risks aggregate.

    Rules:
      - Any HIGH in inputs ⇒ HIGH.
      - Three or more independent MEDIUMs ⇒ HIGH (Section 3.1: "Three independent
        MEDIUM risks across non-overlapping dimensions can aggregate to HIGH").
      - One or two MEDIUMs ⇒ MEDIUM.
      - All LOW (or only LOW + NOT_APPLICABLE) ⇒ LOW.
      - All NOT_APPLICABLE ⇒ NOT_APPLICABLE.

    The CRITICAL tier described in Section 3.1 prose is not in the canonical
    Section 15.2 enum; criticality is conveyed alongside HIGH via flags or a
    GateResult.HARD_BLOCK on E6's gate output.
    """
    actives = [level for level in component_levels if level != RiskLevel.NOT_APPLICABLE]
    if not actives:
        return RiskLevel.NOT_APPLICABLE
    if any(level == RiskLevel.HIGH for level in actives):
        return RiskLevel.HIGH
    medium_count = sum(1 for level in actives if level == RiskLevel.MEDIUM)
    if medium_count >= 3:
        return RiskLevel.HIGH
    if medium_count >= 1:
        return RiskLevel.MEDIUM
    return RiskLevel.LOW


# ===========================================================================
# 3.2 Confidence rubric
# ===========================================================================


class ConfidenceBand(str, Enum):
    """Calibration anchors per Section 3.2."""

    VIRTUALLY_CERTAIN = "virtually_certain"  # 0.95–1.00
    HIGH = "high"                            # 0.85–0.95
    MODERATE = "moderate"                    # 0.70–0.85
    LOW = "low"                              # 0.50–0.70
    UNCERTAIN = "uncertain"                  # < 0.50


def confidence_band(c: Confidence) -> ConfidenceBand:
    """Map a confidence score to its Section 3.2 band."""
    validate_confidence(c)
    if c >= 0.95:
        return ConfidenceBand.VIRTUALLY_CERTAIN
    if c >= 0.85:
        return ConfidenceBand.HIGH
    if c >= 0.70:
        return ConfidenceBand.MODERATE
    if c >= 0.50:
        return ConfidenceBand.LOW
    return ConfidenceBand.UNCERTAIN


# ===========================================================================
# 3.3 Currency and number format
# ===========================================================================


_ONE_LAKH = 100_000
_ONE_CRORE = 100 * _ONE_LAKH


def format_inr(amount: float | int, *, compact: bool = True, decimals: int = 2) -> str:
    """Format INR in lakh-crore convention per Section 3.3.

    Compact form (default):
      - |amount| ≥ 1 Cr → "₹X.YY Cr"
      - |amount| ≥ 1 L  → "₹X.YY L"
      - else → "₹X,XX,XXX" lakh-crore digit grouping (always non-compact below 1 L)

    Non-compact form: always lakh-crore grouping with no L/Cr suffix.

    Examples:
      format_inr(12_345_000)           -> "₹1.23 Cr"
      format_inr(2_50_000)             -> "₹2.50 L"
      format_inr(12_345)               -> "₹12,345"
      format_inr(12_345_000, compact=False) -> "₹1,23,45,000"
    """
    sign = "-" if amount < 0 else ""
    magnitude = abs(amount)

    if compact and magnitude >= _ONE_CRORE:
        return f"{sign}₹{magnitude / _ONE_CRORE:.{decimals}f} Cr"
    if compact and magnitude >= _ONE_LAKH:
        return f"{sign}₹{magnitude / _ONE_LAKH:.{decimals}f} L"

    return f"{sign}₹{_lakh_crore_group(int(magnitude))}"


def _lakh_crore_group(n: int) -> str:
    """Insert lakh-crore separators: 12345000 -> '1,23,45,000'."""
    s = str(n)
    if len(s) <= 3:
        return s
    last_three = s[-3:]
    rest = s[:-3]
    groups: list[str] = []
    while len(rest) > 2:
        groups.insert(0, rest[-2:])
        rest = rest[:-2]
    if rest:
        groups.insert(0, rest)
    return ",".join(groups) + "," + last_three


def format_percentage(value: float, *, decimals: int = 1) -> str:
    """Format a 0-1 value as a percentage with explicit % sign (Section 3.3).

    Examples:
      format_percentage(0.124)            -> "12.4%"
      format_percentage(0.1243, decimals=2) -> "12.43%"
    """
    return f"{value * 100:.{decimals}f}%"


def format_basis_points(bps: int) -> str:
    """Render basis points compactly. One bp = 0.01 percentage point (Section 3.3)."""
    return f"{bps} bps"


def format_return(value: float, *, period: str, qualifier: str, decimals: int = 1) -> str:
    """Render a return with mandatory period and net-or-gross qualifier per Section 3.3.

    Bare "12%" is prohibited in agent outputs; this helper enforces the qualifier.

    Example:
      format_return(0.124, period="annual", qualifier="net of all costs and taxes")
        -> "12.4% net of all costs and taxes annual"
    """
    if not period.strip():
        raise ValueError("period qualifier is required (Section 3.3)")
    if not qualifier.strip():
        raise ValueError("net-or-gross qualifier is required (Section 3.3)")
    return f"{format_percentage(value, decimals=decimals)} {qualifier} {period}"


# ===========================================================================
# 3.4 Time horizon vocabulary
# ===========================================================================


TIME_HORIZON_YEARS: dict[TimeHorizon, tuple[float, float | None]] = {
    TimeHorizon.SHORT_TERM: (0.0, 3.0),
    TimeHorizon.MEDIUM_TERM: (3.0, 5.0),
    TimeHorizon.LONG_TERM: (5.0, None),
}
"""Mapping from canonical time horizon to (min_years_inclusive, max_years_exclusive_or_None)."""

VAGUE_TIME_PHRASES: frozenset[str] = frozenset({
    "soon",
    "down the line",
    "eventually",
    "later",
    "in the future",
    "at some point",
})


def is_vague_time_phrase(phrase: str) -> bool:
    """Detect prohibited vague temporal language (Section 3.4)."""
    return phrase.strip().lower() in VAGUE_TIME_PHRASES


# ===========================================================================
# 3.9 Investor context reference standard
# ===========================================================================


ACTIVE_INVESTOR_CONTEXT_FIELDS: frozenset[str] = frozenset({
    # Identity / audit (always active)
    "client_id",
    "firm_id",
    "created_at",
    "updated_at",
    "version",
    # Active layer (Section 6.4)
    "risk_profile",
    "time_horizon",
    "wealth_tier",
    "assigned_bucket",
    "capacity_trajectory",
    "intermediary_present",
    "intermediary_metadata",
    "beneficiary_can_operate_current_structure",
    "beneficiary_metadata",
    # Source / audit
    "data_source",
    "data_source_metadata",
    "data_gaps_flagged",
    "confidence",
    "family_member_overrides",
})


def assert_field_is_active(field_name: str) -> None:
    """Guard: agent prompts must not reference dormant I0 fields in MVP (Section 3.9).

    Use this in code paths that build agent input bundles to fail loudly if a
    dormant field accidentally leaks through.
    """
    if field_name not in ACTIVE_INVESTOR_CONTEXT_FIELDS:
        raise ValueError(
            f"investor context field '{field_name}' is dormant in MVP; "
            "see Section 6.5 activation procedure"
        )


# ===========================================================================
# 3.10 Override mechanics standard
# ===========================================================================


class OverrideReasonCategory(str, Enum):
    """Section 3.10 categorical reason for any override across the system."""

    CLIENT_SPECIFIC_CIRCUMSTANCE = "client_specific_circumstance"
    ADVISOR_JUDGEMENT_ON_CALIBRATION = "advisor_judgement_on_calibration"
    REGULATORY_CLARIFICATION = "regulatory_clarification"
    DATA_QUALITY_ISSUE = "data_quality_issue"
    OTHER = "other"


class OverrideTargetKind(str, Enum):
    """What is being overridden."""

    EVIDENCE_FINDING = "evidence_finding"
    GATE = "gate"
    HARD_RULE = "hard_rule"
    GOVERNANCE_ESCALATION = "governance_escalation"
    IC1_DISSENT = "ic1_dissent"
    A1_CHALLENGE_DISMISSAL = "a1_challenge_dismissal"


class OverrideRecord(BaseModel):
    """Structured parse of an advisor override remark (Section 3.10 step 2).

    Both the original verbatim remark and this structured parse land in T1.
    Replay reads the structured parse; audit can read the remark for context.
    """

    target_kind: OverrideTargetKind
    target_id: str  # e.g. "e6_gate" or a specific rule_id
    reason_category: OverrideReasonCategory
    rationale_text: str
    free_text_other: str | None = None  # populated when reason_category == OTHER


class OverrideClarificationRequest(BaseModel):
    """Returned by the override parser when the remark is ambiguous (Section 3.10 step 3)."""

    # one of: "multiple_target_candidates", "multiple_reason_candidates", "incoherent"
    ambiguity_kind: str
    candidates: list[str] = Field(default_factory=list)
    original_remark: str


# ===========================================================================
# 3.11 Telemetry schema standard
# ===========================================================================


class T1EventType(str, Enum):
    """Per Section 15.11.1 — the full T1 event_type enum.

    Each value names the originating component or sub-agent. The per-event-type
    payload sub-schema lives in the originating component's spec; this enum is
    just the dispatch label used by readers and replay.
    """

    # M0 sub-agents
    ROUTER_CLASSIFICATION = "router_classification"
    PORTFOLIO_STATE_QUERY = "portfolio_state_query"
    INDIAN_CONTEXT_QUERY = "indian_context_query"
    STITCHER_COMPOSITION = "stitcher_composition"
    BRIEFER_ACTIVATION = "briefer_activation"
    LIBRARIAN_UPDATE = "librarian_update"
    PORTFOLIO_ANALYTICS_QUERY = "portfolio_analytics_query"

    # Evidence agents (E1–E5)
    E1_VERDICT = "e1_verdict"
    E2_VERDICT = "e2_verdict"
    E3_VERDICT = "e3_verdict"
    E4_VERDICT = "e4_verdict"
    E5_VERDICT = "e5_verdict"

    # E6 internal sub-agents
    E6_ORCHESTRATOR = "e6_orchestrator"
    E6_PMS = "e6_pms"
    E6_AIF_CAT_1 = "e6_aif_cat_1"
    E6_AIF_CAT_2 = "e6_aif_cat_2"
    E6_AIF_CAT_3 = "e6_aif_cat_3"
    E6_SIF = "e6_sif"
    E6_MF = "e6_mf"
    E6_FEE_NORMALISATION = "e6_fee_normalisation"
    E6_CASCADE_ENGINE = "e6_cascade_engine"
    E6_LIQUIDITY_MANAGER = "e6_liquidity_manager"
    E6_GATE = "e6_gate"
    E6_RECOMMENDATION_SYNTHESIS = "e6_recommendation_synthesis"

    # Synthesis & deliberation
    S1_SYNTHESIS = "s1_synthesis"
    IC1_MATERIALITY_GATE = "ic1_materiality_gate"
    IC1_CHAIR = "ic1_chair"
    IC1_DEVILS_ADVOCATE = "ic1_devils_advocate"
    IC1_RISK_ASSESSOR = "ic1_risk_assessor"
    IC1_MINUTES_RECORDER = "ic1_minutes_recorder"

    # Governance & challenge
    G1_EVALUATION = "g1_evaluation"
    G2_EVALUATION = "g2_evaluation"
    G3_EVALUATION = "g3_evaluation"
    A1_CHALLENGE = "a1_challenge"

    # Monitoring
    PM1_EVENT = "pm1_event"

    # Channels
    C0_PARSE = "c0_parse"
    N0_ALERT = "n0_alert"

    # Agent communication overlays
    CLARIFICATION_REQUEST = "clarification_request"
    CLARIFICATION_RESPONSE = "clarification_response"
    BRIEFING = "briefing"

    # Decisions and overrides
    DECISION = "decision"
    OVERRIDE = "override"

    # Lifecycle / version-pin events
    MANDATE_AMENDMENT = "mandate_amendment"
    MODEL_PORTFOLIO_VERSION_PIN = "model_portfolio_version_pin"
    L4_MANIFEST_VERSION_PIN = "l4_manifest_version_pin"
    # Section 6.3: emitted when an investor's risk_profile or time_horizon
    # changes and they're re-bucketed. Additive to Section 15.11.1 enum
    # (backward-compatible per Section 15.13 minor-version rules).
    BUCKET_REMAPPING = "bucket_remapping"
    # §10.3.7 — onboarding activation event captured on every advisor confirmation
    INVESTOR_ACTIVATED = "investor_activated"

    # Cross-cutting
    EX1_EVENT = "ex1_event"
    T2_REFLECTION_RUN = "t2_reflection_run"


T1_BASE_REQUIRED_FIELDS: frozenset[str] = frozenset({
    "event_id",
    "event_type",
    "timestamp",
    "firm_id",
    "payload_hash",
    "payload",
    "version_pins",
})
"""The minimum set of fields every T1 event must populate (Section 15.11.1).

Other base fields (case_id, client_id, advisor_id, correction_of) are nullable
on the canonical schema but the slot must always be present in the persisted row.
"""


# ===========================================================================
# 3.12 + 3.14 Agent communication and clarification protocol
# ===========================================================================


# Briefing length budget per Section 3.14 / 8.8.2
BRIEFING_TOKEN_MIN = 100
BRIEFING_TOKEN_MAX = 300

# Clarification length budget and round-trip cap per Section 3.14 / 9.4
CLARIFICATION_MAX_ROUNDS = 1
CLARIFICATION_RESPONSE_TOKEN_MIN = 50
CLARIFICATION_RESPONSE_TOKEN_MAX = 200


def briefing_within_budget(token_count: int) -> bool:
    """True if token count fits the M0.Briefer length contract."""
    return BRIEFING_TOKEN_MIN <= token_count <= BRIEFING_TOKEN_MAX


def clarification_response_within_budget(token_count: int) -> bool:
    """True if M0's clarification response fits its length contract."""
    return CLARIFICATION_RESPONSE_TOKEN_MIN <= token_count <= CLARIFICATION_RESPONSE_TOKEN_MAX


# Lint patterns for the M0.Briefer prompt discipline (Section 8.8.2).
# A briefing must NOT contain conclusions, risk-level assertions, or
# verdict-anticipating language. These regexes are conservative first-line
# detectors; the real lint will use a fine-tuned classifier per 17.18.
_VERDICT_ANTICIPATING_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(?:high|medium|low|critical)\s+risk\b", re.IGNORECASE),
    re.compile(
        r"\b(?:should|must|shouldn't|mustn't)\s+(?:proceed|invest|allocate|recommend|be\s+escalated)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bthis\s+(?:is|will\s+be)\s+(?:risky|safe|appropriate|inappropriate)\b",
        re.IGNORECASE,
    ),
    # Lemma forms: approve(d/al), reject(ed), block(ed), escalate(d/ion)
    re.compile(r"\b(?:approv\w*|reject\w*|block\w*|escalat\w*)\b", re.IGNORECASE),
    re.compile(
        r"\b(?:my\s+)?(?:recommendation|conclusion|verdict|assessment)\s+is\b",
        re.IGNORECASE,
    ),
)


def briefing_violates_discipline(text: str) -> tuple[bool, list[str]]:
    """First-line lint check for M0.Briefer discipline (Section 8.8.2).

    Returns (violates, reasons). Conservative — false positives are acceptable
    here; M0.Briefer regenerates on detection. A1's accountability surface
    (Section 9.6) does the real auditing.
    """
    reasons: list[str] = []
    for pattern in _VERDICT_ANTICIPATING_PATTERNS:
        if pattern.search(text):
            reasons.append(f"matches verdict-anticipating pattern: {pattern.pattern!r}")
    return (len(reasons) > 0, reasons)


class ClarificationRequest(BaseModel):
    """Section 9.4 / 15. The structured clarification request emitted by an agent."""

    requesting_agent: str
    clarification_field: str
    reason: str
    candidate_values: list[str] = Field(default_factory=list)


# ===========================================================================
# 3.13 Error and exception handling standard (EX1)
# ===========================================================================


class ExceptionCategory(str, Enum):
    """Section 13.9.2. EX1's category enum, indexed by routing rule table."""

    INPUT_DATA_MISSING = "input_data_missing"
    SCHEMA_VIOLATION = "schema_violation"
    SERVICE_UNAVAILABLE = "service_unavailable"
    CONFLICT_BETWEEN_COMPONENTS = "conflict_between_components"
    TIMEOUT = "timeout"
    GOVERNANCE_RULE_MISMATCH = "governance_rule_mismatch"
    CASCADING_EXCEPTION = "cascading_exception"


class ExceptionSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class ExceptionRoutingDecision(str, Enum):
    """Section 13.9.3."""

    ESCALATE_TO_ADVISOR = "escalate_to_advisor"
    ESCALATE_TO_COMPLIANCE = "escalate_to_compliance"
    ESCALATE_TO_FIRM_LEADERSHIP = "escalate_to_firm_leadership"
    ESCALATE_TO_SENIOR_ADVISOR = "escalate_to_senior_advisor"
    FALLBACK_TO_PRIOR_VERSION = "fallback_to_prior_version"
    RETRY_ONCE = "retry_once"
    LOG_AND_PROCEED_WITH_FLAG = "log_and_proceed_with_flag"
