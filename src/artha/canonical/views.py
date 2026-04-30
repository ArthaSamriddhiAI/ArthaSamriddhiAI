"""§14 — UI surfaces by role.

The presentation layer reads canonical objects and produces role-scoped
views. Per §14.5 permission enforcement happens at the data-access layer
(not just UI), so the view composer doubles as the access gate: callers
must supply a `ViewerContext` and the composer raises
`PermissionDeniedError` when scope is violated.

Three roles per §14.1:

  * **Advisor** (§14.2) — own assigned clients + own cases. Reads
    `RenderedArtifact`, `N0Alert`, `CaseObject`, `MandateObject`,
    `InvestorContextProfile`, drift snapshots.
  * **CIO** (§14.3) — firm-level read + construction/approval write.
    Reads `ConstructionRun`, `BucketConstructionProposal`, firm-level
    drift aggregates, T2 reflection runs.
  * **Compliance** (§14.4) — read-only across the firm. Reads T1
    history, A1 challenges, EX1 routing, override events, replay diffs.

Pass 18 ships the core views (per-client, case detail, construction
approval, firm drift, reasoning trail, override history) — enough to
demonstrate the role-scoped composition pattern. Subsequent passes
extend with the remaining §14 views without changing the core contract.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from artha.canonical.evidence_verdict import StandardEvidenceVerdict
from artha.canonical.governance import G3Evaluation
from artha.canonical.investor import InvestorContextProfile
from artha.canonical.mandate import MandateObject
from artha.canonical.monitoring import N0Alert
from artha.canonical.synthesis import IC1Deliberation, S1Synthesis
from artha.common.types import (
    AlertTier,
    Bucket,
    INRAmountField,
    PercentageField,
)

# ===========================================================================
# Roles + viewer context
# ===========================================================================


class Role(str, Enum):
    """§14.1 / Doc 2 §2.1 — four canonical human roles.

    `AUDIT` was added in Doc 2 (API specification): an external-or-internal
    audit reviewer with firm-wide read access (T1 telemetry, governance
    history, override audit trail) and zero write authority. Behaves like
    `COMPLIANCE` for read scope, denied for any mutation.
    """

    ADVISOR = "advisor"
    CIO = "cio"
    COMPLIANCE = "compliance"
    AUDIT = "audit"


class ViewerContext(BaseModel):
    """Per-call viewer identity + scope.

    `assigned_client_ids` is meaningful only for Role.ADVISOR; CIO and
    COMPLIANCE see firm-wide. The composer applies per-role rules:

      * ADVISOR: must include client_id in `assigned_client_ids`.
      * CIO: any client within `firm_id`.
      * COMPLIANCE: any client within `firm_id` (read-only).
    """

    model_config = ConfigDict(extra="forbid")

    role: Role
    user_id: str  # advisor_id / cio_id / compliance_user_id
    firm_id: str
    assigned_client_ids: frozenset[str] = Field(default_factory=frozenset)


# ===========================================================================
# Redaction record + permission denial
# ===========================================================================


class RedactionDecision(BaseModel):
    """Records one field that was filtered for the viewing role."""

    model_config = ConfigDict(extra="forbid")

    field_path: str
    reason: Literal[
        "out_of_role_scope", "out_of_firm_scope", "out_of_client_scope"
    ]


# ===========================================================================
# §14.2.1 — Advisor per-client model view
# ===========================================================================


class DriftStatusLight(str, Enum):
    """Traffic-light tier for drift status indicator."""

    GREEN = "green"  # within tolerance everywhere
    AMBER = "amber"  # informational L2/L3 breach
    RED = "red"      # action-required L1 breach


class HoldingSummaryRow(BaseModel):
    """One row of the top-N holdings table on the per-client view."""

    model_config = ConfigDict(extra="forbid")

    instrument_id: str
    instrument_name: str
    market_value_inr: INRAmountField
    share_of_aum: PercentageField


class N0InboxItem(BaseModel):
    """One inbox row composed from `N0Alert` for the advisor inbox."""

    model_config = ConfigDict(extra="forbid")

    alert_id: str
    tier: AlertTier
    title: str
    body_preview: str  # truncated to 200 chars
    related_case_id: str | None = None
    created_at: datetime


class CaseRecentRow(BaseModel):
    """One recent-case row on the per-client view."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    intent: str
    dominant_lens: str
    current_status: str
    created_at: datetime


class AdvisorPerClientView(BaseModel):
    """§14.2.1 — single-client operational dashboard."""

    model_config = ConfigDict(extra="forbid")

    role: Literal[Role.ADVISOR] = Role.ADVISOR
    viewer_user_id: str
    firm_id: str
    client_id: str
    risk_profile: str
    time_horizon: str
    assigned_bucket: Bucket
    total_aum_inr: INRAmountField = 0.0
    deployed_inr: INRAmountField = 0.0
    cash_buffer_inr: INRAmountField = 0.0
    drift_status: DriftStatusLight = DriftStatusLight.GREEN
    drift_breaches_count: int = 0
    top_holdings: list[HoldingSummaryRow] = Field(default_factory=list)
    active_alerts: list[N0InboxItem] = Field(default_factory=list)
    recent_cases: list[CaseRecentRow] = Field(default_factory=list)
    mandate_summary: dict[str, Any] = Field(default_factory=dict)
    redactions: list[RedactionDecision] = Field(default_factory=list)


# ===========================================================================
# §14.2.3 — Advisor case-detail view
# ===========================================================================


class EvidenceVerdictSummary(BaseModel):
    """One row of the evidence drill-down on case detail."""

    model_config = ConfigDict(extra="forbid")

    agent_id: str
    risk_level: str
    confidence: float
    flags: list[str] = Field(default_factory=list)
    reasoning_excerpt: str  # first 400 chars of reasoning_trace


class AdvisorCaseDetailView(BaseModel):
    """§14.2.3 — full case detail composed for the advisor."""

    model_config = ConfigDict(extra="forbid")

    role: Literal[Role.ADVISOR] = Role.ADVISOR
    viewer_user_id: str
    firm_id: str
    case_id: str
    client_id: str
    case_intent: str
    dominant_lens: str
    rendered_artifact_text: str  # M0.Stitcher narrative
    evidence_summaries: list[EvidenceVerdictSummary] = Field(default_factory=list)
    s1_synthesis_recommendation: str | None = None
    ic1_recommendation: str | None = None
    ic1_minutes_excerpt: str | None = None
    g3_permission: str | None = None
    g3_blocking_reasons: list[str] = Field(default_factory=list)
    decision_options: list[str] = Field(default_factory=list)
    t1_replay_link: str | None = None
    redactions: list[RedactionDecision] = Field(default_factory=list)


# ===========================================================================
# §14.3.2 — CIO construction approval view
# ===========================================================================


class CellChangeSummary(BaseModel):
    """One cell change row on the construction approval surface."""

    model_config = ConfigDict(extra="forbid")

    level: Literal["l1", "l2", "l3"]
    cell_key: str
    prior_target: float | None = None
    proposed_target: float | None = None
    delta: float | None = None


class CIOConstructionApprovalView(BaseModel):
    """§14.3.2 — version diff + blast radius preview."""

    model_config = ConfigDict(extra="forbid")

    role: Literal[Role.CIO] = Role.CIO
    viewer_user_id: str
    firm_id: str
    run_id: str
    bucket: Bucket
    proposed_model_id: str
    proposed_version: str
    prior_model_id: str | None = None
    cell_changes: list[CellChangeSummary] = Field(default_factory=list)
    blast_radius_share: PercentageField = 0.0
    clients_in_bucket_count: int = 0
    clients_in_tolerance_who_breach: int = 0
    total_aum_moved_inr: INRAmountField = 0.0
    estimated_txn_cost_inr: INRAmountField = 0.0
    estimated_tax_cost_inr: INRAmountField = 0.0
    rollout_mode: str
    approval_rationale: str
    approved_for_rollout: bool = False
    redactions: list[RedactionDecision] = Field(default_factory=list)


# ===========================================================================
# §14.3.4 — CIO firm-level drift dashboard
# ===========================================================================


class BucketDriftRow(BaseModel):
    """One bucket's drift distribution."""

    model_config = ConfigDict(extra="forbid")

    bucket: Bucket
    clients_in_tolerance: int = 0
    clients_amber: int = 0  # informational L2/L3 breach
    clients_red: int = 0    # action-required L1 breach
    mandate_breach_count: int = 0


class CIOFirmDriftDashboard(BaseModel):
    """§14.3.4 — firm-level drift aggregation across all 9 buckets."""

    model_config = ConfigDict(extra="forbid")

    role: Literal[Role.CIO] = Role.CIO
    viewer_user_id: str
    firm_id: str
    as_of_date: date
    bucket_distribution: list[BucketDriftRow] = Field(default_factory=list)
    total_clients: int = 0
    total_mandate_breaches: int = 0
    total_action_required_drifts: int = 0
    redactions: list[RedactionDecision] = Field(default_factory=list)


# ===========================================================================
# §14.4.1 — Compliance reasoning-trail view
# ===========================================================================


class ReasoningTrailEntry(BaseModel):
    """One chronological entry in the case reasoning trail."""

    model_config = ConfigDict(extra="forbid")

    timestamp: datetime
    event_type: str  # T1EventType value
    agent_id: str | None = None
    summary: str  # ≤300 chars
    payload_hash: str
    event_id: str


class ComplianceCaseReasoningTrail(BaseModel):
    """§14.4.1 — full chronological reasoning trail for a single case."""

    model_config = ConfigDict(extra="forbid")

    role: Literal[Role.COMPLIANCE] = Role.COMPLIANCE
    viewer_user_id: str
    firm_id: str
    case_id: str
    client_id: str
    entries: list[ReasoningTrailEntry] = Field(default_factory=list)
    decision_event_id: str | None = None
    override_event_ids: list[str] = Field(default_factory=list)
    replay_available: bool = True
    redactions: list[RedactionDecision] = Field(default_factory=list)


# ===========================================================================
# §14.4.2 — Compliance override-history view
# ===========================================================================


class OverrideHistoryRow(BaseModel):
    """One override event with outcome metadata."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    client_id: str
    advisor_id: str
    timestamp: datetime
    rationale_excerpt: str
    structured_category: str | None = None
    requires_compliance_review: bool = False


class ComplianceOverrideHistoryView(BaseModel):
    """§14.4.2 — firm-wide override pattern history."""

    model_config = ConfigDict(extra="forbid")

    role: Literal[Role.COMPLIANCE] = Role.COMPLIANCE
    viewer_user_id: str
    firm_id: str
    period_start: datetime
    period_end: datetime
    rows: list[OverrideHistoryRow] = Field(default_factory=list)
    total_overrides: int = 0
    compliance_review_queue_count: int = 0
    redactions: list[RedactionDecision] = Field(default_factory=list)


# ===========================================================================
# Aliases (re-export canonical objects view composers consume)
# ===========================================================================


__all__ = [
    "AdvisorCaseDetailView",
    "AdvisorPerClientView",
    "BucketDriftRow",
    "CIOConstructionApprovalView",
    "CIOFirmDriftDashboard",
    "CaseRecentRow",
    "CellChangeSummary",
    "ComplianceCaseReasoningTrail",
    "ComplianceOverrideHistoryView",
    "DriftStatusLight",
    "EvidenceVerdictSummary",
    "G3Evaluation",
    "HoldingSummaryRow",
    "IC1Deliberation",
    "InvestorContextProfile",
    "MandateObject",
    "N0Alert",
    "N0InboxItem",
    "OverrideHistoryRow",
    "ReasoningTrailEntry",
    "RedactionDecision",
    "Role",
    "S1Synthesis",
    "StandardEvidenceVerdict",
    "ViewerContext",
]
