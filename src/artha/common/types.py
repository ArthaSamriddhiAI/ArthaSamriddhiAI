"""Domain-specific type aliases, enums, and shared structured types.

Section 15.2 of the consolidation spec is the single source of truth for cross-component
types: enums (risk_level, permission, alert_tier, bucket, etc.), shared structured types
(driver, source_citation, version_pins), and the formatting types (iso8601_*, ulid,
inr_amount, percentage, basis_points). Components reference what's here rather than
re-declaring locally.

The legacy NewType ID aliases at the top of the file pre-date the consolidation; they
remain in place for backward compatibility with the existing accountability, governance,
evidence, and execution layers. New code should prefer the canonical IDs (CaseID,
ClientID, FirmID, etc.) defined further down.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, NewType

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Legacy ID aliases (pre-consolidation; retained for compatibility)
# ---------------------------------------------------------------------------

DecisionID = NewType("DecisionID", str)
ArtifactID = NewType("ArtifactID", str)
TraceNodeID = NewType("TraceNodeID", str)
RuleID = NewType("RuleID", str)
RuleSetVersionID = NewType("RuleSetVersionID", str)
AgentID = NewType("AgentID", str)
SnapshotID = NewType("SnapshotID", str)
IntentID = NewType("IntentID", str)
OrderID = NewType("OrderID", str)
ApprovalID = NewType("ApprovalID", str)


# ---------------------------------------------------------------------------
# Canonical ID aliases (Section 15.2 + 15.11)
# ---------------------------------------------------------------------------

ULID = NewType("ULID", str)
CaseID = NewType("CaseID", str)
ClientID = NewType("ClientID", str)
FirmID = NewType("FirmID", str)
AdvisorID = NewType("AdvisorID", str)
EventID = NewType("EventID", str)
ModelPortfolioID = NewType("ModelPortfolioID", str)
MandateID = NewType("MandateID", str)
InstrumentID = NewType("InstrumentID", str)
AlertID = NewType("AlertID", str)


# ---------------------------------------------------------------------------
# Section 15.2 enums — the canonical vocabulary referenced everywhere
# ---------------------------------------------------------------------------


class RiskLevel(str, Enum):
    """Section 3.1 / 15.2. The schema-canonical risk rubric.

    Note: Section 3.1 also describes a CRITICAL tier ("hard contraindication, multiple
    drivers of high severity"). The Section 15.2 canonical enum does not include
    CRITICAL; cases at that severity are conveyed via flags (e.g. E6 gate HARD_BLOCK)
    in addition to RiskLevel.HIGH. Schema wins; gate vocabulary carries the criticality.
    """

    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class Permission(str, Enum):
    """Section 3.6 / 15.2. The G1/G2/G3 governance gate vocabulary.

    Section 3.6 prose uses "ESCALATE"; Section 15.2 schema uses "ESCALATION_REQUIRED".
    Schema wins.
    """

    APPROVED = "APPROVED"
    BLOCKED = "BLOCKED"
    ESCALATION_REQUIRED = "ESCALATION_REQUIRED"


class DecisionTier(str, Enum):
    """Section 3.6. Three tiers of system output by override semantics."""

    FINDING = "finding"          # no decisional weight
    GATE = "gate"                # graded with explicit override path
    HARD_RULE = "hard_rule"      # deterministic stop, senior-escalation override only


class Recommendation(str, Enum):
    """Section 15.2. Used by S1 synthesis and IC1 deliberation."""

    PROCEED = "proceed"
    MODIFY = "modify"
    DO_NOT_PROCEED = "do_not_proceed"
    DEFER = "defer"


class GateResult(str, Enum):
    """Section 3.6. E6's product-suitability gate vocabulary."""

    PROCEED = "PROCEED"
    EVALUATE_WITH_COUNTERFACTUAL = "EVALUATE_WITH_COUNTERFACTUAL"
    SOFT_BLOCK = "SOFT_BLOCK"
    HARD_BLOCK = "HARD_BLOCK"


class MaterialityGateResult(str, Enum):
    """Section 12.3.2. IC1's materiality gate."""

    CONVENE = "CONVENE"
    SKIP = "SKIP"


class AlertTier(str, Enum):
    """Section 10.2.2 / 15.2. Four-tier N0 vocabulary including the new WATCH tier."""

    MUST_RESPOND = "must_respond"
    SHOULD_RESPOND = "should_respond"
    WATCH = "watch"
    INFORMATIONAL = "informational"


class WatchState(str, Enum):
    """Section 10.2.3 / 15.2. Lifecycle of a contingent watch alert."""

    ACTIVE_WATCH = "active_watch"
    RESOLVED_OCCURRED = "resolved_occurred"
    RESOLVED_DID_NOT_OCCUR = "resolved_did_not_occur"


class CaseIntent(str, Enum):
    """Section 8.3.2 / 15.2. The 8-type canonical intent taxonomy owned by M0.Router."""

    CASE = "case"
    DIAGNOSTIC = "diagnostic"
    BRIEFING = "briefing"
    MONITORING_RESPONSE = "monitoring_response"
    KNOWLEDGE_QUERY = "knowledge_query"
    PROFILE_UPDATE = "profile_update"
    REBALANCE_TRIGGER = "rebalance_trigger"
    MANDATE_REVIEW = "mandate_review"


class Bucket(str, Enum):
    """Section 5.4 / 15.2. The nine model portfolio buckets (3 risk x 3 horizon)."""

    CON_ST = "CON_ST"
    CON_MT = "CON_MT"
    CON_LT = "CON_LT"
    MOD_ST = "MOD_ST"
    MOD_MT = "MOD_MT"
    MOD_LT = "MOD_LT"
    AGG_ST = "AGG_ST"
    AGG_MT = "AGG_MT"
    AGG_LT = "AGG_LT"


class RiskProfile(str, Enum):
    """Section 6.2 / 15.3.1 active layer."""

    CONSERVATIVE = "Conservative"
    MODERATE = "Moderate"
    AGGRESSIVE = "Aggressive"


class TimeHorizon(str, Enum):
    """Section 3.4 vocabulary and 15.3.1 active layer."""

    SHORT_TERM = "short_term"   # up to 3 years
    MEDIUM_TERM = "medium_term"  # 3 to 5 years
    LONG_TERM = "long_term"      # more than 5 years


class RunMode(str, Enum):
    """Section 15.2. Pipeline mode for agents shared by case and construction pipelines."""

    CASE = "case"
    DIAGNOSTIC = "diagnostic"
    BRIEFING = "briefing"
    CONSTRUCTION = "construction"


class VehicleType(str, Enum):
    """Section 5.3.2 / 15.2. The MVP vehicle universe."""

    DIRECT_EQUITY = "direct_equity"
    MUTUAL_FUND = "mutual_fund"
    PMS = "pms"
    AIF_CAT_1 = "aif_cat_1"
    AIF_CAT_2 = "aif_cat_2"
    AIF_CAT_3 = "aif_cat_3"
    SIF = "sif"
    DEBT_DIRECT = "debt_direct"
    FD = "fd"
    GOLD = "gold"
    REIT = "reit"
    INVIT = "invit"
    UNLISTED_EQUITY = "unlisted_equity"
    CASH = "cash"


class AssetClass(str, Enum):
    """Section 5.3.1 / 15.2. The MVP L1 asset class universe.

    Section 5.3.1 specifies four MVP asset classes (equity, debt, commodities, real
    estate via REITs/InvITs); 15.2 also lists `alternatives` and `cash` for forward
    compatibility (alternatives is deferred to v2 per 5.3.1; cash is the buffer per 5.6).
    """

    EQUITY = "equity"
    DEBT = "debt"
    GOLD_COMMODITIES = "gold_commodities"
    REAL_ASSETS = "real_assets"
    ALTERNATIVES = "alternatives"
    CASH = "cash"


class CapacityTrajectory(str, Enum):
    """Section 6.2 / 15.2. Active-layer structural flag for engagement capacity over time."""

    STABLE_OR_GROWING = "stable_or_growing"
    STABLE_WITH_KNOWN_DECLINE_DATES = "stable_with_known_decline_dates"
    DECLINING_MODERATE = "declining_moderate"
    DECLINING_SEVERE = "declining_severe"


class WealthTier(str, Enum):
    """Section 6.2 / 15.2. AUM-based eligibility tiers (not a bucket axis)."""

    UP_TO_25K_SIP = "up_to_25k_sip"
    SIP_25K_TO_2CR_AUM = "25k_to_2cr_aum"
    AUM_2CR_TO_5CR = "2cr_to_5cr_aum"
    AUM_5CR_TO_10CR = "5cr_to_10cr_aum"
    AUM_10CR_TO_25CR = "10cr_to_25cr_aum"
    AUM_25CR_TO_100CR = "25cr_to_100cr_aum"
    AUM_BEYOND_100CR = "beyond_100cr_aum"


class MandateType(str, Enum):
    """Section 7.4 / 15.2."""

    INDIVIDUAL = "individual"
    FAMILY_OFFICE = "family_office"
    TRUST = "trust"
    HUF = "huf"
    LLP = "llp"
    LVF = "lvf"
    CORPORATE = "corporate"


class ErrorState(str, Enum):
    """Section 3.11. Per-event error state in the telemetry envelope."""

    OK = "ok"
    PARTIAL = "partial"
    FAILED = "failed"
    ESCALATED = "escalated"


# ---------------------------------------------------------------------------
# Shared structured types (Section 15.2)
# ---------------------------------------------------------------------------


class DriverDirection(str, Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"


class DriverSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Driver(BaseModel):
    """A factor that contributed to an evidence agent's verdict (Section 15.2)."""

    factor: str
    direction: DriverDirection
    severity: DriverSeverity
    detail: str
    evidence_citation: list[str] = Field(default_factory=list)


class SourceType(str, Enum):
    RULE = "rule"
    TABLE = "table"
    CHANGELOG = "changelog"
    T1_EVENT = "t1_event"
    EXTERNAL = "external"


class SourceCitation(BaseModel):
    """Reference to the source of an assertion. Used by IndianContext, A1, T2."""

    source_type: SourceType
    source_id: str
    source_version: str


class VersionPins(BaseModel):
    """Versions of every load-bearing component used at decision time (Section 15.2).

    Captured on every T1 event so that replay reads against the exact components
    that produced the original output. Replay uses the captured pins, never the
    current versions.
    """

    model_version: str | None = None
    prompt_version: str | None = None
    rule_corpus_version: str | None = None
    mandate_version: str | None = None
    model_portfolio_version: str | None = None
    l4_manifest_version: str | None = None
    agent_version: str | None = None
    schema_version: str | None = None


class InputsUsedManifest(BaseModel):
    """Per-input source identifiers, versions, and as_of timestamps for replay (Section 15.2).

    The shape is intentionally permissive: each input is keyed by a name (e.g.
    "portfolio_state", "model_portfolio", "tax_table") and carries source identity,
    version, and as_of in its value object.
    """

    inputs: dict[str, dict[str, str]] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Confidence helpers (Section 3.2)
# ---------------------------------------------------------------------------


Confidence = float
"""A probability in [0.0, 1.0]. See `artha.common.standards.confidence_band` for the
calibration anchors (virtually_certain, high, moderate, low, uncertain) per Section 3.2.

This is the loose alias used in legacy contexts that don't use Pydantic. New canonical
schemas should use the Pydantic-validated `PercentageField` below for any 0-1 range."""


def validate_confidence(c: Confidence) -> None:
    """Raise if `c` is outside the canonical [0, 1] range."""
    if not isinstance(c, (int, float)) or not (0.0 <= float(c) <= 1.0):
        raise ValueError(f"confidence must be in [0.0, 1.0], got {c!r}")


# ---------------------------------------------------------------------------
# Constrained value types for Section 15 canonical schemas
# ---------------------------------------------------------------------------

PercentageField = Annotated[float, Field(ge=0.0, le=1.0)]
"""A 0.0–1.0 fraction (Section 3.3). Renders as 0%–100% at presentation."""

ConfidenceField = Annotated[float, Field(ge=0.0, le=1.0)]
"""A 0.0–1.0 confidence per Section 3.2 rubric."""

BasisPointsField = Annotated[int, Field(ge=0)]
"""A non-negative basis-points integer. One bp = 0.01 percentage point (Section 3.3)."""

INRAmountField = Annotated[float, Field()]
"""An INR amount. Stored as float (no constraint on sign — losses, drawdowns, gains all valid)."""
