"""Case framework ORM models — cluster 5 chunk 5.1.

11 tables:

- ``v2_cases`` (parent)
- ``v2_case_evidence_verdicts`` (many-per-case; one per evidence agent)
- ``v2_case_portfolio_risk_analytics`` (1-per-case)
- ``v2_case_synthesis`` (1-per-case)
- ``v2_case_ic1_deliberations`` (0-or-1; only material proposed_action /
  scenario)
- ``v2_case_governance_results`` (1-3 per case; one per gate)
- ``v2_case_a1_challenges`` (0-or-1; only proposed_action / scenario)
- ``v2_case_decision_artifacts`` (0-or-1; only proposed_action / scenario)
- ``v2_case_briefing_notes`` (0-or-1; only briefing mode)
- ``v2_case_health_reports`` (0-or-1; only diagnostic mode)
- ``v2_case_llm_call_logs`` (audit log; empty in cluster 5)

Schema notes:

- All primary keys are ULID strings (26 chars), aligning with the rest of
  the api_v2 surface.
- ``snapshot_bundle_id`` on ``v2_cases`` references cluster 3's
  ``v2_snapshots.snapshot_id``. Application-layer immutability check
  in :mod:`repository` (DB trigger would require database-specific
  syntax; SQLite + Postgres compatibility means we enforce in code).
- ``cases.health_report_id`` and ``cases.briefing_note_id`` are NOT
  modelled — the children carry the FK to ``cases`` and the lookup is
  done via JOIN. This avoids the circular FK that the spec sidesteps.
- All stage tables carry ``schema_version=1`` and ``is_seed_data=False``
  defaults.

Per FR Entry 10.7 cluster-5 revision §3.2, this chunk also extends six
existing entities (Investor, Household, Mandate, MandateVersion, the
auth ``User`` materialised via test users, and ``v2_snapshots``) with
``is_seed_data BOOLEAN NOT NULL DEFAULT false``. Investor additionally
gets ``seed_archetype_id``. Those extensions live in the existing
models / migration files modified alongside this chunk.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from artha.common.db.base import Base

# ---------------------------------------------------------------------------
# v2_cases (parent)
# ---------------------------------------------------------------------------


class Case(Base):
    """The Case row — central reasoning unit (FR 20.1 §2.1)."""

    __tablename__ = "v2_cases"

    case_id: Mapped[str] = mapped_column(String(26), primary_key=True)

    # ----- Identity / ownership -----
    investor_id: Mapped[str] = mapped_column(
        String(26), ForeignKey("v2_investors.investor_id"),
        nullable=False, index=True,
    )
    household_id: Mapped[str | None] = mapped_column(
        String(26), ForeignKey("v2_households.household_id"),
        nullable=True, index=True,
    )
    opened_by: Mapped[str] = mapped_column(String(64), nullable=False)
    assigned_to: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True
    )

    # ----- Mode / intent / lens -----
    case_mode: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    case_intent: Mapped[str | None] = mapped_column(String(40), nullable=True)
    dominant_lens: Mapped[str | None] = mapped_column(String(30), nullable=True)
    proposed_action: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Materiality inputs split out per the digest's recommendation —
    # FR 20.1 §6.3 references these as case-level fields but doesn't
    # specify column shape. We persist them so the materiality gate can
    # evaluate without re-parsing free-form proposed_action text.
    proposed_action_amount_inr: Mapped[Decimal | None] = mapped_column(
        Numeric(15, 2), nullable=True,
    )
    proposed_action_products: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list,
    )
    materiality_manual_flag: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
    )

    # ----- Status / lifecycle -----
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="opening", index=True,
    )
    status_changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True,
    )

    # ----- Snapshot pinning -----
    # FK to v2_snapshots (cluster 3). Once set, immutability is enforced
    # at the application layer (see repository.update_snapshot_bundle).
    snapshot_bundle_id: Mapped[str | None] = mapped_column(
        String(26),
        ForeignKey("v2_snapshots.snapshot_id"),
        nullable=True,
        index=True,
    )

    # ----- Materiality assessment outcome -----
    materiality_assessed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    is_material: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    materiality_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # ----- LLM cost roll-up (cluster 5: zero; cluster 7+ accrues) -----
    total_llm_cost_inr: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0"),
    )
    total_llm_input_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
    )
    total_llm_output_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
    )

    # ----- Provenance -----
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True,
    )
    created_via: Mapped[str] = mapped_column(String(30), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    closed_reason: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # ----- Cluster-5 stub: which evidence agents the router selected -----
    applicable_evidence_agents: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list,
    )

    # ----- Supersession (FR 20.4 §7.3) -----
    supersedes_case_id: Mapped[str | None] = mapped_column(
        String(26), ForeignKey("v2_cases.case_id"), nullable=True,
    )

    # ----- Seed framework (FR 19.0 / 10.7 cluster-5 revision §3.2) -----
    is_seed_data: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, index=True,
    )
    seed_archetype_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True,
    )

    schema_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1,
    )

    __table_args__ = (
        Index("ix_v2_cases_status_changed", "status", "status_changed_at"),
        Index("ix_v2_cases_mode_status", "case_mode", "status"),
        Index("ix_v2_cases_assigned_status", "assigned_to", "status"),
    )


# ---------------------------------------------------------------------------
# v2_case_evidence_verdicts
# ---------------------------------------------------------------------------


class EvidenceVerdict(Base):
    """One row per evidence agent that fired for a case (FR 20.1 §2.3)."""

    __tablename__ = "v2_case_evidence_verdicts"

    verdict_id: Mapped[str] = mapped_column(String(26), primary_key=True)
    case_id: Mapped[str] = mapped_column(
        String(26), ForeignKey("v2_cases.case_id"),
        nullable=False, index=True,
    )
    agent_id: Mapped[str] = mapped_column(String(40), nullable=False)
    produced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    produced_via: Mapped[str] = mapped_column(String(30), nullable=False)

    risk_level: Mapped[str | None] = mapped_column(String(10), nullable=True)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(3, 2), nullable=True)
    drivers: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    flags: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    structured_output: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True,
    )
    reasoning_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_seed_data: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, index=True,
    )

    __table_args__ = (
        Index("ix_evidence_case_agent", "case_id", "agent_id"),
        Index("ix_evidence_case_produced", "case_id", "produced_at"),
    )


# ---------------------------------------------------------------------------
# v2_case_portfolio_risk_analytics (1-per-case)
# ---------------------------------------------------------------------------


class PortfolioRiskAnalyticsOutput(Base):
    """M0.PortfolioRiskAnalytics output (FR 20.1 §2.4)."""

    __tablename__ = "v2_case_portfolio_risk_analytics"

    output_id: Mapped[str] = mapped_column(String(26), primary_key=True)
    case_id: Mapped[str] = mapped_column(
        String(26), ForeignKey("v2_cases.case_id"),
        nullable=False, unique=True,
    )
    produced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    produced_via: Mapped[str] = mapped_column(String(30), nullable=False)

    concentration_assessment: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True,
    )
    leverage_assessment: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True,
    )
    liquidity_assessment: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True,
    )
    return_quality_assessment: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True,
    )
    deployment_assessment: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True,
    )
    cascade_assessment: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True,
    )

    overall_risk_level: Mapped[str | None] = mapped_column(String(10), nullable=True)
    overall_confidence: Mapped[Decimal | None] = mapped_column(
        Numeric(3, 2), nullable=True,
    )

    drivers: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    flags: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    reasoning_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    portfolio_analytics_input_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True,
    )

    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_seed_data: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, index=True,
    )


# ---------------------------------------------------------------------------
# v2_case_synthesis (1-per-case)
# ---------------------------------------------------------------------------


class SynthesisOutput(Base):
    """S1 synthesis output (FR 20.1 §2.5). Mode-aware via output_mode."""

    __tablename__ = "v2_case_synthesis"

    synthesis_id: Mapped[str] = mapped_column(String(26), primary_key=True)
    case_id: Mapped[str] = mapped_column(
        String(26), ForeignKey("v2_cases.case_id"),
        nullable=False, unique=True,
    )
    produced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    produced_via: Mapped[str] = mapped_column(String(30), nullable=False)

    output_mode: Mapped[str] = mapped_column(String(20), nullable=False)

    consensus: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    agreement_areas: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True,
    )
    conflict_areas: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True,
    )
    uncertainty_flag: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    uncertainty_reasons: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True,
    )
    amplification: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True,
    )
    mode_dominance: Mapped[str | None] = mapped_column(String(30), nullable=True)
    escalation_recommended: Mapped[bool | None] = mapped_column(
        Boolean, nullable=True,
    )
    escalation_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    counterfactual_framing: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True,
    )

    synthesis_narrative: Mapped[str | None] = mapped_column(Text, nullable=True)
    recommendation: Mapped[str | None] = mapped_column(Text, nullable=True)
    flags: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    reasoning_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_seed_data: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, index=True,
    )


# ---------------------------------------------------------------------------
# v2_case_ic1_deliberations (0-or-1; material proposed_action / scenario)
# ---------------------------------------------------------------------------


class IC1Deliberation(Base):
    """IC1 deliberation output (FR 20.1 §2.6)."""

    __tablename__ = "v2_case_ic1_deliberations"

    deliberation_id: Mapped[str] = mapped_column(String(26), primary_key=True)
    case_id: Mapped[str] = mapped_column(
        String(26), ForeignKey("v2_cases.case_id"),
        nullable=False, unique=True,
    )
    produced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    produced_via: Mapped[str] = mapped_column(String(30), nullable=False)

    chair_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    devils_advocate_position: Mapped[str | None] = mapped_column(Text, nullable=True)
    risk_assessment: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True,
    )
    counterfactual_engine_output: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True,
    )
    minutes: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    dissent: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    recommendation: Mapped[str] = mapped_column(String(40), nullable=False)
    conditions: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    escalation_to_human: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True,
    )
    reasoning_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_seed_data: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, index=True,
    )


# ---------------------------------------------------------------------------
# v2_case_governance_results (1-3 per case; one per gate)
# ---------------------------------------------------------------------------


class GovernanceResult(Base):
    """G1 / G2 / G3 outcome row (FR 20.1 §2.7)."""

    __tablename__ = "v2_case_governance_results"

    result_id: Mapped[str] = mapped_column(String(26), primary_key=True)
    case_id: Mapped[str] = mapped_column(
        String(26), ForeignKey("v2_cases.case_id"),
        nullable=False, index=True,
    )
    gate: Mapped[str] = mapped_column(String(40), nullable=False)
    produced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    produced_via: Mapped[str] = mapped_column(String(30), nullable=False)

    outcome: Mapped[str] = mapped_column(String(40), nullable=False)
    blocking_rule_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    blocking_rule_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    override_requirements: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True,
    )
    conditions_to_attach: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True,
    )
    rule_corpus_version: Mapped[str | None] = mapped_column(String(40), nullable=True)

    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_seed_data: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, index=True,
    )

    __table_args__ = (
        UniqueConstraint("case_id", "gate", name="uq_governance_case_gate"),
    )


# ---------------------------------------------------------------------------
# v2_case_a1_challenges (0-or-1; proposed_action / scenario)
# ---------------------------------------------------------------------------


class A1Challenge(Base):
    """A1 challenge output (FR 20.1 §2.8). Advisory; does not gate."""

    __tablename__ = "v2_case_a1_challenges"

    challenge_id: Mapped[str] = mapped_column(String(26), primary_key=True)
    case_id: Mapped[str] = mapped_column(
        String(26), ForeignKey("v2_cases.case_id"),
        nullable=False, unique=True,
    )
    produced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    produced_via: Mapped[str] = mapped_column(String(30), nullable=False)

    counter_arguments: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True,
    )
    alternative_proposals: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True,
    )
    stress_test_scenarios: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True,
    )
    edge_cases: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    accountability_flags: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True,
    )
    reasoning_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_seed_data: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, index=True,
    )


# ---------------------------------------------------------------------------
# v2_case_decision_artifacts (0-or-1; proposed_action / scenario)
# ---------------------------------------------------------------------------


class DecisionArtifact(Base):
    """CIO decision recording with cryptographic hashes (FR 20.1 §2.9 /
    FR 20.4)."""

    __tablename__ = "v2_case_decision_artifacts"

    artifact_id: Mapped[str] = mapped_column(String(26), primary_key=True)
    case_id: Mapped[str] = mapped_column(
        String(26), ForeignKey("v2_cases.case_id"),
        nullable=False, unique=True,
    )
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    decided_by: Mapped[str] = mapped_column(String(64), nullable=False)
    decision: Mapped[str] = mapped_column(String(20), nullable=False)
    modifications: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True,
    )
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    conditions: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    # Cryptographic hashes (FR 20.4 §3 / FR 20.1 §4.3)
    evidence_packet_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    synthesis_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    governance_packet_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    portfolio_risk_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ic1_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    a1_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_seed_data: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, index=True,
    )


# ---------------------------------------------------------------------------
# v2_case_briefing_notes (0-or-1; briefing mode)
# ---------------------------------------------------------------------------


class BriefingNote(Base):
    """Briefing-mode artifact (FR 20.1 §2.10)."""

    __tablename__ = "v2_case_briefing_notes"

    briefing_id: Mapped[str] = mapped_column(String(26), primary_key=True)
    case_id: Mapped[str] = mapped_column(
        String(26), ForeignKey("v2_cases.case_id"),
        nullable=False, unique=True,
    )
    produced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    produced_via: Mapped[str] = mapped_column(String(30), nullable=False)

    meeting_context: Mapped[str | None] = mapped_column(Text, nullable=True)
    recent_activity_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    current_state_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    market_context: Mapped[str | None] = mapped_column(Text, nullable=True)
    prep_questions: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True,
    )

    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_seed_data: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, index=True,
    )


# ---------------------------------------------------------------------------
# v2_case_health_reports (0-or-1; diagnostic mode)
# ---------------------------------------------------------------------------


class HealthReport(Base):
    """Diagnostic-mode artifact (FR 20.1 §2.11)."""

    __tablename__ = "v2_case_health_reports"

    report_id: Mapped[str] = mapped_column(String(26), primary_key=True)
    case_id: Mapped[str] = mapped_column(
        String(26), ForeignKey("v2_cases.case_id"),
        nullable=False, unique=True,
    )
    produced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    produced_via: Mapped[str] = mapped_column(String(30), nullable=False)

    overall_health: Mapped[str] = mapped_column(String(40), nullable=False)
    asset_allocation_status: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True,
    )
    performance_summary: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True,
    )
    drift_indicators: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True,
    )
    recommendations: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True,
    )

    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_seed_data: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, index=True,
    )


# ---------------------------------------------------------------------------
# v2_case_llm_call_logs (audit log; empty in cluster 5)
# ---------------------------------------------------------------------------


class LLMCallLog(Base):
    """LLM call audit log (FR 20.2 §10.3 / 10.7 cluster-5 revision §3.1).

    Empty in cluster 5 (no production LLM calls). Cluster 7+ populates
    when real agents start invoking the LLM router.
    """

    __tablename__ = "v2_case_llm_call_logs"

    log_id: Mapped[str] = mapped_column(String(26), primary_key=True)
    case_id: Mapped[str] = mapped_column(
        String(26), ForeignKey("v2_cases.case_id"),
        nullable=False, index=True,
    )
    agent_id: Mapped[str] = mapped_column(String(40), nullable=False)
    produced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True,
    )

    model: Mapped[str] = mapped_column(String(80), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    estimated_cost_inr: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0"),
    )
    request_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    skill_md_version: Mapped[str | None] = mapped_column(String(20), nullable=True)

    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


__all__ = [
    "A1Challenge",
    "BriefingNote",
    "Case",
    "DecisionArtifact",
    "EvidenceVerdict",
    "GovernanceResult",
    "HealthReport",
    "IC1Deliberation",
    "LLMCallLog",
    "PortfolioRiskAnalyticsOutput",
    "SynthesisOutput",
]
