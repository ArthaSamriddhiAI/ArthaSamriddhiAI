"""cluster_5_chunk_5_1_case_framework

Cluster 5 chunk 5.1: case framework data foundation.

Adds:

- ``is_seed_data`` to v2_investors (+ ``seed_archetype_id``),
  v2_households, v2_mandates, v2_mandate_versions, v2_snapshots
  (FR Entry 10.7 cluster-5 revision §3.2).
- ``v2_cases`` parent table.
- Ten child stage tables: v2_case_evidence_verdicts,
  v2_case_portfolio_risk_analytics, v2_case_synthesis,
  v2_case_ic1_deliberations, v2_case_governance_results,
  v2_case_a1_challenges, v2_case_decision_artifacts,
  v2_case_briefing_notes, v2_case_health_reports, v2_case_llm_call_logs.

UNIQUE constraints per FR Entry 20.1 §3:

- ``v2_case_governance_results.(case_id, gate)`` — at most one result
  per gate per case.
- single-row stage tables (synthesis, ic1, a1, decision, briefing,
  health, portfolio_risk_analytics) UNIQUE on ``case_id``.

Snapshot pinning immutability (FR 20.1 §4.1) is enforced at the
application layer in ``cases/repository.update_snapshot_bundle`` so
the schema stays portable across SQLite + Postgres.

Revision ID: 6da5d8b614b0
Revises: e60794b9c039
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "6da5d8b614b0"
down_revision: Union[str, Sequence[str], None] = "e60794b9c039"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Forward-roll cluster 5 chunk 5.1 schema."""
    # ------------------------------------------------------------------
    # is_seed_data on existing entities (FR 10.7 cluster-5 revision §3.2)
    # ------------------------------------------------------------------
    op.add_column(
        "v2_investors",
        sa.Column(
            "is_seed_data",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "v2_investors",
        sa.Column("seed_archetype_id", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_v2_investors_is_seed_data",
        "v2_investors",
        ["is_seed_data"],
    )

    op.add_column(
        "v2_households",
        sa.Column(
            "is_seed_data",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_index(
        "ix_v2_households_is_seed_data",
        "v2_households",
        ["is_seed_data"],
    )

    op.add_column(
        "v2_mandates",
        sa.Column(
            "is_seed_data",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_index(
        "ix_v2_mandates_is_seed_data",
        "v2_mandates",
        ["is_seed_data"],
    )

    op.add_column(
        "v2_mandate_versions",
        sa.Column(
            "is_seed_data",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_index(
        "ix_v2_mandate_versions_is_seed_data",
        "v2_mandate_versions",
        ["is_seed_data"],
    )

    op.add_column(
        "v2_snapshots",
        sa.Column(
            "is_seed_data",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_index(
        "ix_v2_snapshots_is_seed_data",
        "v2_snapshots",
        ["is_seed_data"],
    )

    # ------------------------------------------------------------------
    # v2_cases — parent entity (FR 20.1 §2.1)
    # ------------------------------------------------------------------
    op.create_table(
        "v2_cases",
        sa.Column("case_id", sa.String(length=26), primary_key=True),
        # Identity / ownership
        sa.Column(
            "investor_id",
            sa.String(length=26),
            sa.ForeignKey("v2_investors.investor_id"),
            nullable=False,
        ),
        sa.Column(
            "household_id",
            sa.String(length=26),
            sa.ForeignKey("v2_households.household_id"),
            nullable=True,
        ),
        sa.Column("opened_by", sa.String(length=64), nullable=False),
        sa.Column("assigned_to", sa.String(length=64), nullable=False),
        # Mode / intent / lens
        sa.Column("case_mode", sa.String(length=20), nullable=False),
        sa.Column("case_intent", sa.String(length=40), nullable=True),
        sa.Column("dominant_lens", sa.String(length=30), nullable=True),
        sa.Column("proposed_action", sa.Text(), nullable=True),
        sa.Column(
            "proposed_action_amount_inr", sa.Numeric(15, 2), nullable=True
        ),
        sa.Column(
            "proposed_action_products",
            sa.JSON(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "materiality_manual_flag",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        # Status / lifecycle
        sa.Column(
            "status",
            sa.String(length=30),
            nullable=False,
            server_default="opening",
        ),
        sa.Column(
            "status_changed_at", sa.DateTime(timezone=True), nullable=False
        ),
        # Snapshot pinning
        sa.Column(
            "snapshot_bundle_id",
            sa.String(length=26),
            sa.ForeignKey("v2_snapshots.snapshot_id"),
            nullable=True,
        ),
        # Materiality outcome
        sa.Column(
            "materiality_assessed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("is_material", sa.Boolean(), nullable=True),
        sa.Column("materiality_reason", sa.String(length=200), nullable=True),
        # LLM cost roll-up
        sa.Column(
            "total_llm_cost_inr",
            sa.Numeric(12, 2),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "total_llm_input_tokens",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "total_llm_output_tokens",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        # Provenance
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_via", sa.String(length=30), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_reason", sa.String(length=20), nullable=True),
        # Routing decision result
        sa.Column(
            "applicable_evidence_agents",
            sa.JSON(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "supersedes_case_id",
            sa.String(length=26),
            sa.ForeignKey("v2_cases.case_id"),
            nullable=True,
        ),
        # Seed framework
        sa.Column(
            "is_seed_data",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("seed_archetype_id", sa.String(length=64), nullable=True),
        sa.Column(
            "schema_version", sa.Integer(), nullable=False, server_default="1"
        ),
    )
    op.create_index("ix_v2_cases_investor_id", "v2_cases", ["investor_id"])
    op.create_index("ix_v2_cases_household_id", "v2_cases", ["household_id"])
    op.create_index("ix_v2_cases_assigned_to", "v2_cases", ["assigned_to"])
    op.create_index("ix_v2_cases_case_mode", "v2_cases", ["case_mode"])
    op.create_index("ix_v2_cases_status", "v2_cases", ["status"])
    op.create_index(
        "ix_v2_cases_status_changed_at", "v2_cases", ["status_changed_at"]
    )
    op.create_index(
        "ix_v2_cases_snapshot_bundle_id", "v2_cases", ["snapshot_bundle_id"]
    )
    op.create_index("ix_v2_cases_created_at", "v2_cases", ["created_at"])
    op.create_index(
        "ix_v2_cases_is_seed_data", "v2_cases", ["is_seed_data"]
    )
    op.create_index(
        "ix_v2_cases_status_changed", "v2_cases", ["status", "status_changed_at"]
    )
    op.create_index(
        "ix_v2_cases_mode_status", "v2_cases", ["case_mode", "status"]
    )
    op.create_index(
        "ix_v2_cases_assigned_status", "v2_cases", ["assigned_to", "status"]
    )

    # ------------------------------------------------------------------
    # v2_case_evidence_verdicts (FR 20.1 §2.3) — many-per-case
    # ------------------------------------------------------------------
    op.create_table(
        "v2_case_evidence_verdicts",
        sa.Column("verdict_id", sa.String(length=26), primary_key=True),
        sa.Column(
            "case_id",
            sa.String(length=26),
            sa.ForeignKey("v2_cases.case_id"),
            nullable=False,
        ),
        sa.Column("agent_id", sa.String(length=40), nullable=False),
        sa.Column("produced_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("produced_via", sa.String(length=30), nullable=False),
        sa.Column("risk_level", sa.String(length=10), nullable=True),
        sa.Column("confidence", sa.Numeric(3, 2), nullable=True),
        sa.Column("drivers", sa.JSON(), nullable=True),
        sa.Column("flags", sa.JSON(), nullable=True),
        sa.Column("structured_output", sa.JSON(), nullable=True),
        sa.Column("reasoning_summary", sa.Text(), nullable=True),
        sa.Column(
            "schema_version", sa.Integer(), nullable=False, server_default="1"
        ),
        sa.Column(
            "is_seed_data",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_index(
        "ix_v2_evidence_case_id", "v2_case_evidence_verdicts", ["case_id"]
    )
    op.create_index(
        "ix_evidence_case_agent",
        "v2_case_evidence_verdicts",
        ["case_id", "agent_id"],
    )
    op.create_index(
        "ix_evidence_case_produced",
        "v2_case_evidence_verdicts",
        ["case_id", "produced_at"],
    )
    op.create_index(
        "ix_v2_evidence_is_seed_data",
        "v2_case_evidence_verdicts",
        ["is_seed_data"],
    )

    # ------------------------------------------------------------------
    # v2_case_portfolio_risk_analytics (FR 20.1 §2.4) — 1-per-case
    # ------------------------------------------------------------------
    op.create_table(
        "v2_case_portfolio_risk_analytics",
        sa.Column("output_id", sa.String(length=26), primary_key=True),
        sa.Column(
            "case_id",
            sa.String(length=26),
            sa.ForeignKey("v2_cases.case_id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("produced_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("produced_via", sa.String(length=30), nullable=False),
        sa.Column("concentration_assessment", sa.JSON(), nullable=True),
        sa.Column("leverage_assessment", sa.JSON(), nullable=True),
        sa.Column("liquidity_assessment", sa.JSON(), nullable=True),
        sa.Column("return_quality_assessment", sa.JSON(), nullable=True),
        sa.Column("deployment_assessment", sa.JSON(), nullable=True),
        sa.Column("cascade_assessment", sa.JSON(), nullable=True),
        sa.Column("overall_risk_level", sa.String(length=10), nullable=True),
        sa.Column("overall_confidence", sa.Numeric(3, 2), nullable=True),
        sa.Column("drivers", sa.JSON(), nullable=True),
        sa.Column("flags", sa.JSON(), nullable=True),
        sa.Column("reasoning_summary", sa.Text(), nullable=True),
        sa.Column(
            "portfolio_analytics_input_hash",
            sa.String(length=64),
            nullable=True,
        ),
        sa.Column(
            "schema_version", sa.Integer(), nullable=False, server_default="1"
        ),
        sa.Column(
            "is_seed_data",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_index(
        "ix_v2_pra_is_seed_data",
        "v2_case_portfolio_risk_analytics",
        ["is_seed_data"],
    )

    # ------------------------------------------------------------------
    # v2_case_synthesis (FR 20.1 §2.5) — 1-per-case
    # ------------------------------------------------------------------
    op.create_table(
        "v2_case_synthesis",
        sa.Column("synthesis_id", sa.String(length=26), primary_key=True),
        sa.Column(
            "case_id",
            sa.String(length=26),
            sa.ForeignKey("v2_cases.case_id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("produced_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("produced_via", sa.String(length=30), nullable=False),
        sa.Column("output_mode", sa.String(length=20), nullable=False),
        sa.Column("consensus", sa.JSON(), nullable=True),
        sa.Column("agreement_areas", sa.JSON(), nullable=True),
        sa.Column("conflict_areas", sa.JSON(), nullable=True),
        sa.Column("uncertainty_flag", sa.Boolean(), nullable=True),
        sa.Column("uncertainty_reasons", sa.JSON(), nullable=True),
        sa.Column("amplification", sa.JSON(), nullable=True),
        sa.Column("mode_dominance", sa.String(length=30), nullable=True),
        sa.Column("escalation_recommended", sa.Boolean(), nullable=True),
        sa.Column("escalation_reason", sa.String(length=200), nullable=True),
        sa.Column("counterfactual_framing", sa.JSON(), nullable=True),
        sa.Column("synthesis_narrative", sa.Text(), nullable=True),
        sa.Column("recommendation", sa.Text(), nullable=True),
        sa.Column("flags", sa.JSON(), nullable=True),
        sa.Column("reasoning_summary", sa.Text(), nullable=True),
        sa.Column(
            "schema_version", sa.Integer(), nullable=False, server_default="1"
        ),
        sa.Column(
            "is_seed_data",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_index(
        "ix_v2_synthesis_is_seed_data",
        "v2_case_synthesis",
        ["is_seed_data"],
    )

    # ------------------------------------------------------------------
    # v2_case_ic1_deliberations (FR 20.1 §2.6) — 0-or-1
    # ------------------------------------------------------------------
    op.create_table(
        "v2_case_ic1_deliberations",
        sa.Column("deliberation_id", sa.String(length=26), primary_key=True),
        sa.Column(
            "case_id",
            sa.String(length=26),
            sa.ForeignKey("v2_cases.case_id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("produced_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("produced_via", sa.String(length=30), nullable=False),
        sa.Column("chair_summary", sa.Text(), nullable=True),
        sa.Column("devils_advocate_position", sa.Text(), nullable=True),
        sa.Column("risk_assessment", sa.JSON(), nullable=True),
        sa.Column("counterfactual_engine_output", sa.JSON(), nullable=True),
        sa.Column("minutes", sa.JSON(), nullable=False),
        sa.Column("dissent", sa.JSON(), nullable=True),
        sa.Column("recommendation", sa.String(length=40), nullable=False),
        sa.Column("conditions", sa.JSON(), nullable=True),
        sa.Column(
            "escalation_to_human",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column("reasoning_summary", sa.Text(), nullable=True),
        sa.Column(
            "schema_version", sa.Integer(), nullable=False, server_default="1"
        ),
        sa.Column(
            "is_seed_data",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_index(
        "ix_v2_ic1_is_seed_data",
        "v2_case_ic1_deliberations",
        ["is_seed_data"],
    )

    # ------------------------------------------------------------------
    # v2_case_governance_results (FR 20.1 §2.7) — many per case (one per gate)
    # ------------------------------------------------------------------
    op.create_table(
        "v2_case_governance_results",
        sa.Column("result_id", sa.String(length=26), primary_key=True),
        sa.Column(
            "case_id",
            sa.String(length=26),
            sa.ForeignKey("v2_cases.case_id"),
            nullable=False,
        ),
        sa.Column("gate", sa.String(length=40), nullable=False),
        sa.Column("produced_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("produced_via", sa.String(length=30), nullable=False),
        sa.Column("outcome", sa.String(length=40), nullable=False),
        sa.Column("blocking_rule_id", sa.String(length=80), nullable=True),
        sa.Column("blocking_rule_text", sa.Text(), nullable=True),
        sa.Column("reasoning", sa.Text(), nullable=True),
        sa.Column("override_requirements", sa.JSON(), nullable=True),
        sa.Column("conditions_to_attach", sa.JSON(), nullable=True),
        sa.Column("rule_corpus_version", sa.String(length=40), nullable=True),
        sa.Column(
            "schema_version", sa.Integer(), nullable=False, server_default="1"
        ),
        sa.Column(
            "is_seed_data",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.UniqueConstraint("case_id", "gate", name="uq_governance_case_gate"),
    )
    op.create_index(
        "ix_v2_governance_case_id",
        "v2_case_governance_results",
        ["case_id"],
    )
    op.create_index(
        "ix_v2_governance_is_seed_data",
        "v2_case_governance_results",
        ["is_seed_data"],
    )

    # ------------------------------------------------------------------
    # v2_case_a1_challenges (FR 20.1 §2.8) — 0-or-1
    # ------------------------------------------------------------------
    op.create_table(
        "v2_case_a1_challenges",
        sa.Column("challenge_id", sa.String(length=26), primary_key=True),
        sa.Column(
            "case_id",
            sa.String(length=26),
            sa.ForeignKey("v2_cases.case_id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("produced_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("produced_via", sa.String(length=30), nullable=False),
        sa.Column("counter_arguments", sa.JSON(), nullable=True),
        sa.Column("alternative_proposals", sa.JSON(), nullable=True),
        sa.Column("stress_test_scenarios", sa.JSON(), nullable=True),
        sa.Column("edge_cases", sa.JSON(), nullable=True),
        sa.Column("accountability_flags", sa.JSON(), nullable=True),
        sa.Column("reasoning_summary", sa.Text(), nullable=True),
        sa.Column(
            "schema_version", sa.Integer(), nullable=False, server_default="1"
        ),
        sa.Column(
            "is_seed_data",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_index(
        "ix_v2_a1_is_seed_data",
        "v2_case_a1_challenges",
        ["is_seed_data"],
    )

    # ------------------------------------------------------------------
    # v2_case_decision_artifacts (FR 20.1 §2.9 / FR 20.4 §3) — 0-or-1
    # ------------------------------------------------------------------
    op.create_table(
        "v2_case_decision_artifacts",
        sa.Column("artifact_id", sa.String(length=26), primary_key=True),
        sa.Column(
            "case_id",
            sa.String(length=26),
            sa.ForeignKey("v2_cases.case_id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_by", sa.String(length=64), nullable=False),
        sa.Column("decision", sa.String(length=20), nullable=False),
        sa.Column("modifications", sa.JSON(), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("conditions", sa.JSON(), nullable=True),
        sa.Column(
            "evidence_packet_hash", sa.String(length=64), nullable=False
        ),
        sa.Column("synthesis_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "governance_packet_hash", sa.String(length=64), nullable=False
        ),
        sa.Column(
            "portfolio_risk_hash", sa.String(length=64), nullable=True
        ),
        sa.Column("ic1_hash", sa.String(length=64), nullable=True),
        sa.Column("a1_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "schema_version", sa.Integer(), nullable=False, server_default="1"
        ),
        sa.Column(
            "is_seed_data",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_index(
        "ix_v2_decision_is_seed_data",
        "v2_case_decision_artifacts",
        ["is_seed_data"],
    )

    # ------------------------------------------------------------------
    # v2_case_briefing_notes (FR 20.1 §2.10) — 0-or-1, briefing mode
    # ------------------------------------------------------------------
    op.create_table(
        "v2_case_briefing_notes",
        sa.Column("briefing_id", sa.String(length=26), primary_key=True),
        sa.Column(
            "case_id",
            sa.String(length=26),
            sa.ForeignKey("v2_cases.case_id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("produced_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("produced_via", sa.String(length=30), nullable=False),
        sa.Column("meeting_context", sa.Text(), nullable=True),
        sa.Column("recent_activity_summary", sa.Text(), nullable=True),
        sa.Column("current_state_summary", sa.Text(), nullable=True),
        sa.Column("market_context", sa.Text(), nullable=True),
        sa.Column("prep_questions", sa.JSON(), nullable=True),
        sa.Column(
            "schema_version", sa.Integer(), nullable=False, server_default="1"
        ),
        sa.Column(
            "is_seed_data",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_index(
        "ix_v2_briefing_is_seed_data",
        "v2_case_briefing_notes",
        ["is_seed_data"],
    )

    # ------------------------------------------------------------------
    # v2_case_health_reports (FR 20.1 §2.11) — 0-or-1, diagnostic mode
    # ------------------------------------------------------------------
    op.create_table(
        "v2_case_health_reports",
        sa.Column("report_id", sa.String(length=26), primary_key=True),
        sa.Column(
            "case_id",
            sa.String(length=26),
            sa.ForeignKey("v2_cases.case_id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("produced_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("produced_via", sa.String(length=30), nullable=False),
        sa.Column("overall_health", sa.String(length=40), nullable=False),
        sa.Column("asset_allocation_status", sa.JSON(), nullable=True),
        sa.Column("performance_summary", sa.JSON(), nullable=True),
        sa.Column("drift_indicators", sa.JSON(), nullable=True),
        sa.Column("recommendations", sa.JSON(), nullable=True),
        sa.Column(
            "schema_version", sa.Integer(), nullable=False, server_default="1"
        ),
        sa.Column(
            "is_seed_data",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_index(
        "ix_v2_health_is_seed_data",
        "v2_case_health_reports",
        ["is_seed_data"],
    )

    # ------------------------------------------------------------------
    # v2_case_llm_call_logs (FR 20.2 §10.3) — audit log; empty in cluster 5
    # ------------------------------------------------------------------
    op.create_table(
        "v2_case_llm_call_logs",
        sa.Column("log_id", sa.String(length=26), primary_key=True),
        sa.Column(
            "case_id",
            sa.String(length=26),
            sa.ForeignKey("v2_cases.case_id"),
            nullable=False,
        ),
        sa.Column("agent_id", sa.String(length=40), nullable=False),
        sa.Column("produced_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("model", sa.String(length=80), nullable=False),
        sa.Column(
            "input_tokens", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "output_tokens", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "estimated_cost_inr",
            sa.Numeric(12, 2),
            nullable=False,
            server_default="0",
        ),
        sa.Column("request_id", sa.String(length=80), nullable=True),
        sa.Column("skill_md_version", sa.String(length=20), nullable=True),
        sa.Column(
            "schema_version", sa.Integer(), nullable=False, server_default="1"
        ),
    )
    op.create_index(
        "ix_v2_llm_call_log_case_id", "v2_case_llm_call_logs", ["case_id"]
    )
    op.create_index(
        "ix_v2_llm_call_log_produced_at",
        "v2_case_llm_call_logs",
        ["produced_at"],
    )


def downgrade() -> None:
    """Drop cluster 5 chunk 5.1 schema in reverse order."""
    op.drop_table("v2_case_llm_call_logs")
    op.drop_table("v2_case_health_reports")
    op.drop_table("v2_case_briefing_notes")
    op.drop_table("v2_case_decision_artifacts")
    op.drop_table("v2_case_a1_challenges")
    op.drop_table("v2_case_governance_results")
    op.drop_table("v2_case_ic1_deliberations")
    op.drop_table("v2_case_synthesis")
    op.drop_table("v2_case_portfolio_risk_analytics")
    op.drop_table("v2_case_evidence_verdicts")
    op.drop_table("v2_cases")

    op.drop_index("ix_v2_snapshots_is_seed_data", "v2_snapshots")
    op.drop_column("v2_snapshots", "is_seed_data")

    op.drop_index("ix_v2_mandate_versions_is_seed_data", "v2_mandate_versions")
    op.drop_column("v2_mandate_versions", "is_seed_data")

    op.drop_index("ix_v2_mandates_is_seed_data", "v2_mandates")
    op.drop_column("v2_mandates", "is_seed_data")

    op.drop_index("ix_v2_households_is_seed_data", "v2_households")
    op.drop_column("v2_households", "is_seed_data")

    op.drop_index("ix_v2_investors_is_seed_data", "v2_investors")
    op.drop_column("v2_investors", "seed_archetype_id")
    op.drop_column("v2_investors", "is_seed_data")
