"""Pydantic read shapes for the case framework.

Cluster 5 chunks 5.3 (intake) and 5.5 (decision recording / case detail
UI) consume these schemas. Only the read shapes ship in chunk 5.1; the
write request bodies (CaseCreateRequest, DecisionRecordRequest, etc.)
land alongside their respective endpoints in later chunks.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field


class CaseRead(BaseModel):
    """Read shape for ``v2_cases``. All fields surfaced to the case
    detail + case list UIs.
    """

    case_id: str

    # Identity
    investor_id: str
    household_id: str | None
    opened_by: str
    assigned_to: str

    # Mode / intent / lens
    case_mode: str
    case_intent: str | None
    dominant_lens: str | None
    proposed_action: str | None
    proposed_action_amount_inr: Decimal | None
    proposed_action_products: list[str]
    materiality_manual_flag: bool

    # Lifecycle
    status: str
    status_changed_at: datetime
    snapshot_bundle_id: str | None

    # Materiality outcome
    materiality_assessed_at: datetime | None
    is_material: bool | None
    materiality_reason: str | None

    # Cost roll-up
    total_llm_cost_inr: Decimal
    total_llm_input_tokens: int
    total_llm_output_tokens: int

    # Provenance
    created_at: datetime
    created_via: str
    closed_at: datetime | None
    closed_reason: str | None
    applicable_evidence_agents: list[str]
    supersedes_case_id: str | None

    # Seed framework
    is_seed_data: bool
    seed_archetype_id: str | None
    schema_version: int


class CaseListResponse(BaseModel):
    cases: list[CaseRead]
    total: int
    limit: int
    offset: int


class EvidenceVerdictRead(BaseModel):
    verdict_id: str
    case_id: str
    agent_id: str
    produced_at: datetime
    produced_via: str
    risk_level: str | None
    confidence: Decimal | None
    drivers: dict[str, Any] | None
    flags: dict[str, Any] | None
    structured_output: dict[str, Any] | None
    reasoning_summary: str | None
    schema_version: int
    is_seed_data: bool


class PortfolioRiskAnalyticsRead(BaseModel):
    output_id: str
    case_id: str
    produced_at: datetime
    produced_via: str
    concentration_assessment: dict[str, Any] | None
    leverage_assessment: dict[str, Any] | None
    liquidity_assessment: dict[str, Any] | None
    return_quality_assessment: dict[str, Any] | None
    deployment_assessment: dict[str, Any] | None
    cascade_assessment: dict[str, Any] | None
    overall_risk_level: str | None
    overall_confidence: Decimal | None
    drivers: dict[str, Any] | None
    flags: dict[str, Any] | None
    reasoning_summary: str | None
    portfolio_analytics_input_hash: str | None
    schema_version: int
    is_seed_data: bool


class SynthesisOutputRead(BaseModel):
    synthesis_id: str
    case_id: str
    produced_at: datetime
    produced_via: str
    output_mode: str
    consensus: dict[str, Any] | None
    agreement_areas: dict[str, Any] | None
    conflict_areas: dict[str, Any] | None
    uncertainty_flag: bool | None
    uncertainty_reasons: dict[str, Any] | None
    amplification: dict[str, Any] | None
    mode_dominance: str | None
    escalation_recommended: bool | None
    escalation_reason: str | None
    counterfactual_framing: dict[str, Any] | None
    synthesis_narrative: str | None
    recommendation: str | None
    flags: dict[str, Any] | None
    reasoning_summary: str | None
    schema_version: int
    is_seed_data: bool


class IC1DeliberationRead(BaseModel):
    deliberation_id: str
    case_id: str
    produced_at: datetime
    produced_via: str
    chair_summary: str | None
    devils_advocate_position: str | None
    risk_assessment: dict[str, Any] | None
    counterfactual_engine_output: dict[str, Any] | None
    minutes: dict[str, Any]
    dissent: dict[str, Any] | None
    recommendation: str
    conditions: dict[str, Any] | None
    escalation_to_human: bool
    reasoning_summary: str | None
    schema_version: int
    is_seed_data: bool


class GovernanceResultRead(BaseModel):
    result_id: str
    case_id: str
    gate: str
    produced_at: datetime
    produced_via: str
    outcome: str
    blocking_rule_id: str | None
    blocking_rule_text: str | None
    reasoning: str | None
    override_requirements: dict[str, Any] | None
    conditions_to_attach: dict[str, Any] | None
    rule_corpus_version: str | None
    schema_version: int
    is_seed_data: bool


class A1ChallengeRead(BaseModel):
    challenge_id: str
    case_id: str
    produced_at: datetime
    produced_via: str
    counter_arguments: dict[str, Any] | None
    alternative_proposals: dict[str, Any] | None
    stress_test_scenarios: dict[str, Any] | None
    edge_cases: dict[str, Any] | None
    accountability_flags: dict[str, Any] | None
    reasoning_summary: str | None
    schema_version: int
    is_seed_data: bool


class DecisionArtifactRead(BaseModel):
    artifact_id: str
    case_id: str
    decided_at: datetime
    decided_by: str
    decision: str
    modifications: dict[str, Any] | None
    rationale: str
    conditions: dict[str, Any] | None
    evidence_packet_hash: str
    synthesis_hash: str
    governance_packet_hash: str
    portfolio_risk_hash: str | None
    ic1_hash: str | None
    a1_hash: str | None
    schema_version: int
    is_seed_data: bool


class BriefingNoteRead(BaseModel):
    briefing_id: str
    case_id: str
    produced_at: datetime
    produced_via: str
    meeting_context: str | None
    recent_activity_summary: str | None
    current_state_summary: str | None
    market_context: str | None
    prep_questions: dict[str, Any] | None
    schema_version: int
    is_seed_data: bool


class HealthReportRead(BaseModel):
    report_id: str
    case_id: str
    produced_at: datetime
    produced_via: str
    overall_health: str
    asset_allocation_status: dict[str, Any] | None
    performance_summary: dict[str, Any] | None
    drift_indicators: dict[str, Any] | None
    recommendations: dict[str, Any] | None
    schema_version: int
    is_seed_data: bool


class CaseDetailResponse(BaseModel):
    """Full case + every stage output (chunk 5.5 case detail UI)."""

    case: CaseRead
    evidence_verdicts: list[EvidenceVerdictRead]
    portfolio_risk_analytics: PortfolioRiskAnalyticsRead | None
    synthesis: SynthesisOutputRead | None
    ic1_deliberation: IC1DeliberationRead | None
    governance_results: list[GovernanceResultRead]
    a1_challenge: A1ChallengeRead | None
    decision_artifact: DecisionArtifactRead | None
    briefing_note: BriefingNoteRead | None
    health_report: HealthReportRead | None


class CaseFilters(BaseModel):
    """Query-string filter bag (cluster 5 case-list endpoint)."""

    investor_id: str | None = None
    assigned_to: str | None = None
    status: str | None = None
    case_mode: str | None = None
    limit: int = Field(default=100, ge=1, le=500)
    offset: int = Field(default=0, ge=0)


class CaseCreateRequest(BaseModel):
    """Request body for ``POST /api/v2/cases``.

    The router converts this into an ``OpenCaseRequest`` for the
    case_opener service. ``investor_id`` is required; everything else
    has sensible defaults so the simplest UI form (a quick "diagnostic"
    or "briefing" run on an investor) submits with just two fields.
    """

    investor_id: str = Field(..., description="Investor ULID")
    case_mode: str = Field(
        ...,
        description="proposed_action | scenario | diagnostic | briefing",
    )
    case_intent: str | None = None
    dominant_lens: str | None = Field(
        default=None,
        description="portfolio_shift | proposal_evaluation",
    )
    proposed_action: str | None = Field(
        default=None,
        description="Free-text description of the action under consideration",
    )
    proposed_action_amount_inr: Decimal | None = Field(
        default=None,
        ge=0,
        description="Rupee value of the proposed action (for materiality gate)",
    )
    proposed_action_products: list[str] = Field(
        default_factory=list,
        description="Product categories involved (PMS / AIF / SIF / etc.)",
    )
    materiality_manual_flag: bool = Field(
        default=False,
        description="CIO-set escape hatch to force materiality regardless of rules",
    )
    supersedes_case_id: str | None = Field(
        default=None,
        description="ULID of the case this one replaces (e.g. revised proposal)",
    )
    manual_override_evidence_agents: list[str] | None = Field(
        default=None,
        description="CIO-only override of the M0 router's evidence-agent set",
    )
