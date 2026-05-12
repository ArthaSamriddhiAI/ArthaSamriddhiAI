"""cluster_8_chunks_8_1_8_4_infrastructure

Cluster 8 chunks 8.1-8.4: all infrastructure tables.

Chunk 8.1 (E3.MacroView):
  - v2_macro_regimes
  - v2_rate_policy_events
  - v2_e3mv_verdict_cache

Chunk 8.2 (E2 split + stock-level flag generalisation):
  - v2_stock_level_manual_flags  (new; replaces v2_e1_manual_flags)
    Data-migrated from v2_e1_manual_flags; old table kept for compat.
  - v2_sector_classifications
  - v2_ticker_sector_map
  - v2_sector_level_manual_flags
  - v2_e2sv_verdict_cache
  - v2_e2sis_verdict_cache

Chunk 8.3 (E7 Mutual Fund):
  - v2_quarterly_disclosure_events
  - v2_fund_level_manual_flags
  - v2_e7_verdict_cache

Chunk 8.4 (E3.NewsScanner):
  - v2_news_events

Note: v2_e1_manual_flags is kept intact so the cluster-7 E1ManualFlag
ORM mapping remains consistent with create_all.  Its data is copied
into v2_stock_level_manual_flags on upgrade; it will be dropped in a
future cleanup migration once cluster-9 is fully wired.

Revision ID: b8c1a2d3e4f5
Revises: 3527250f5461
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b8c1a2d3e4f5"
down_revision: Union[str, Sequence[str], None] = "3527250f5461"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create all cluster-8 infrastructure tables."""

    # ------------------------------------------------------------------
    # Chunk 8.2 — v2_stock_level_manual_flags
    #   Generalised per-stock flag (covers both E1 + E2.StockInSector).
    #   Adds firm_id, advisor_id (was flagged_by), active_from (was
    #   flagged_at), invalidates_e1, invalidates_e2sis.
    # ------------------------------------------------------------------
    op.create_table(
        "v2_stock_level_manual_flags",
        sa.Column("manual_flag_id", sa.String(length=64), primary_key=True),
        sa.Column("firm_id", sa.String(length=64), nullable=False),
        sa.Column("ticker", sa.String(length=64), nullable=False),
        sa.Column("advisor_id", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("active_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cleared_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cleared_by", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "invalidates_e1", sa.Boolean(), nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "invalidates_e2sis", sa.Boolean(), nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "schema_version", sa.Integer(), nullable=False,
            server_default="2",
        ),
    )
    op.create_index(
        "ix_v2_slmf_ticker",
        "v2_stock_level_manual_flags",
        ["ticker"],
    )
    op.create_index(
        "ix_v2_slmf_firm_ticker_active",
        "v2_stock_level_manual_flags",
        ["firm_id", "ticker", "is_active"],
    )

    # Data-migrate existing v2_e1_manual_flags rows (may be empty in dev).
    op.execute(
        sa.text(
            "INSERT INTO v2_stock_level_manual_flags "
            "  (manual_flag_id, firm_id, ticker, advisor_id, reason, "
            "   active_from, cleared_at, cleared_by, created_at, "
            "   invalidates_e1, invalidates_e2sis, is_active, schema_version) "
            "SELECT "
            "  manual_flag_id, "
            "  'migrated' AS firm_id, "
            "  ticker, "
            "  flagged_by AS advisor_id, "
            "  reason, "
            "  flagged_at AS active_from, "
            "  cleared_at, "
            "  cleared_by, "
            "  flagged_at AS created_at, "
            "  true AS invalidates_e1, "
            "  true AS invalidates_e2sis, "
            "  is_active, "
            "  2 AS schema_version "
            "FROM v2_e1_manual_flags"
        )
    )
    # v2_e1_manual_flags intentionally kept for ORM-metadata / create_all
    # compat; see migration docstring.

    # ------------------------------------------------------------------
    # Chunk 8.1 — Macro regime tracking
    # ------------------------------------------------------------------
    op.create_table(
        "v2_macro_regimes",
        sa.Column("regime_id", sa.String(length=64), primary_key=True),
        sa.Column("regime_name", sa.String(length=128), nullable=False),
        sa.Column("regime_category", sa.String(length=64), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("triggering_event_id", sa.String(length=64), nullable=True),
        sa.Column(
            "triggering_event_type", sa.String(length=32), nullable=False,
        ),
        sa.Column("triggered_by", sa.String(length=64), nullable=False),
        sa.Column("rationale_text", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_v2_macro_regime_active",
        "v2_macro_regimes",
        ["ended_at", "started_at"],
    )

    op.create_table(
        "v2_rate_policy_events",
        sa.Column("event_id", sa.String(length=64), primary_key=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("event_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("details_json", sa.JSON(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column(
            "is_material", sa.Boolean(), nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "materiality_reason", sa.String(length=256), nullable=True,
        ),
    )
    op.create_index(
        "ix_v2_rpe_type_date",
        "v2_rate_policy_events",
        ["event_type", "event_date"],
    )
    op.create_index(
        "ix_v2_rpe_material_date",
        "v2_rate_policy_events",
        ["is_material", "event_date"],
    )

    op.create_table(
        "v2_e3mv_verdict_cache",
        sa.Column("cache_key", sa.String(length=256), primary_key=True),
        sa.Column("firm_id", sa.String(length=64), nullable=False),
        sa.Column("macro_regime_id", sa.String(length=64), nullable=False),
        sa.Column(
            "latest_material_event_id", sa.String(length=64), nullable=True,
        ),
        sa.Column("verdict_json", sa.JSON(), nullable=False),
        sa.Column("stage_json", sa.JSON(), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column("llm_model", sa.String(length=64), nullable=False),
        sa.Column("prompt_version", sa.String(length=16), nullable=False),
        sa.Column(
            "input_tokens", sa.Integer(), nullable=False,
            server_default="0",
        ),
        sa.Column(
            "output_tokens", sa.Integer(), nullable=False,
            server_default="0",
        ),
        sa.Column(
            "cache_hit_count", sa.Integer(), nullable=False,
            server_default="0",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "last_accessed_at", sa.DateTime(timezone=True), nullable=False,
        ),
    )
    op.create_index(
        "ix_v2_e3mv_firm_regime",
        "v2_e3mv_verdict_cache",
        ["firm_id", "macro_regime_id"],
    )

    # ------------------------------------------------------------------
    # Chunk 8.2 — Sector classification + E2 caches
    # ------------------------------------------------------------------
    op.create_table(
        "v2_sector_classifications",
        sa.Column("sector_code", sa.String(length=64), primary_key=True),
        sa.Column("sector_name", sa.String(length=128), nullable=False),
        sa.Column("parent_sector", sa.String(length=64), nullable=True),
        sa.Column("nse_index_code", sa.String(length=64), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "v2_ticker_sector_map",
        sa.Column("ticker", sa.String(length=64), primary_key=True),
        sa.Column("sector_code", sa.String(length=64), primary_key=True),
        sa.Column(
            "effective_from", sa.DateTime(timezone=True), primary_key=True,
        ),
        sa.Column(
            "primary_sector", sa.Boolean(), nullable=False,
            server_default=sa.true(),
        ),
        sa.Column("weight_pct", sa.Numeric(5, 2), nullable=True),
        sa.Column(
            "effective_until", sa.DateTime(timezone=True), nullable=True,
        ),
    )
    op.create_index(
        "ix_v2_tsm_ticker_active",
        "v2_ticker_sector_map",
        ["ticker", "effective_until"],
    )

    op.create_table(
        "v2_sector_level_manual_flags",
        sa.Column("manual_flag_id", sa.String(length=64), primary_key=True),
        sa.Column("firm_id", sa.String(length=64), nullable=False),
        sa.Column("sector_code", sa.String(length=64), nullable=False),
        sa.Column("advisor_id", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("active_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cleared_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cleared_by", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False,
            server_default=sa.true(),
        ),
    )
    op.create_index(
        "ix_v2_slvmf_firm_sector_active",
        "v2_sector_level_manual_flags",
        ["firm_id", "sector_code", "is_active"],
    )

    op.create_table(
        "v2_e2sv_verdict_cache",
        sa.Column("cache_key", sa.String(length=256), primary_key=True),
        sa.Column("firm_id", sa.String(length=64), nullable=False),
        sa.Column("sector_code", sa.String(length=64), nullable=False),
        sa.Column("macro_regime_id", sa.String(length=64), nullable=False),
        sa.Column(
            "sector_manual_flag_id", sa.String(length=64), nullable=True,
        ),
        sa.Column("verdict_json", sa.JSON(), nullable=False),
        sa.Column("stage_json", sa.JSON(), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column("llm_model", sa.String(length=64), nullable=False),
        sa.Column("prompt_version", sa.String(length=16), nullable=False),
        sa.Column(
            "input_tokens", sa.Integer(), nullable=False,
            server_default="0",
        ),
        sa.Column(
            "output_tokens", sa.Integer(), nullable=False,
            server_default="0",
        ),
        sa.Column(
            "cache_hit_count", sa.Integer(), nullable=False,
            server_default="0",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "last_accessed_at", sa.DateTime(timezone=True), nullable=False,
        ),
    )
    op.create_index(
        "ix_v2_e2sv_firm_sector",
        "v2_e2sv_verdict_cache",
        ["firm_id", "sector_code"],
    )

    op.create_table(
        "v2_e2sis_verdict_cache",
        sa.Column("cache_key", sa.String(length=256), primary_key=True),
        sa.Column("firm_id", sa.String(length=64), nullable=False),
        sa.Column("ticker", sa.String(length=64), nullable=False),
        sa.Column("sector_code", sa.String(length=64), nullable=False),
        sa.Column(
            "latest_earnings_id", sa.String(length=64), nullable=True,
        ),
        sa.Column(
            "stock_manual_flag_id", sa.String(length=64), nullable=True,
        ),
        sa.Column("verdict_json", sa.JSON(), nullable=False),
        sa.Column("stage_json", sa.JSON(), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column("llm_model", sa.String(length=64), nullable=False),
        sa.Column("prompt_version", sa.String(length=16), nullable=False),
        sa.Column(
            "input_tokens", sa.Integer(), nullable=False,
            server_default="0",
        ),
        sa.Column(
            "output_tokens", sa.Integer(), nullable=False,
            server_default="0",
        ),
        sa.Column(
            "cache_hit_count", sa.Integer(), nullable=False,
            server_default="0",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "last_accessed_at", sa.DateTime(timezone=True), nullable=False,
        ),
    )
    op.create_index(
        "ix_v2_e2sis_firm_ticker",
        "v2_e2sis_verdict_cache",
        ["firm_id", "ticker"],
    )

    # ------------------------------------------------------------------
    # Chunk 8.3 — Quarterly disclosures + fund flags + E7 cache
    # ------------------------------------------------------------------
    op.create_table(
        "v2_quarterly_disclosure_events",
        sa.Column("disclosure_id", sa.String(length=64), primary_key=True),
        sa.Column("fund_id", sa.String(length=64), nullable=False),
        sa.Column("fund_name", sa.String(length=256), nullable=False),
        sa.Column("fund_category", sa.String(length=64), nullable=False),
        sa.Column("fiscal_period", sa.String(length=16), nullable=False),
        sa.Column(
            "disclosure_date", sa.DateTime(timezone=True), nullable=False,
        ),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("aum_inr_cr", sa.Numeric(15, 2), nullable=True),
        sa.Column("manager_id", sa.String(length=64), nullable=True),
        sa.Column("manager_name", sa.String(length=256), nullable=True),
        sa.Column(
            "manager_changed_this_quarter", sa.Boolean(), nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("ter_pct", sa.Numeric(5, 2), nullable=True),
        sa.Column("exit_load_pct", sa.Numeric(5, 2), nullable=True),
        sa.Column("top_holdings_json", sa.JSON(), nullable=True),
        sa.Column("portfolio_stats_json", sa.JSON(), nullable=True),
        sa.Column("performance_json", sa.JSON(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_v2_qde_fund_date",
        "v2_quarterly_disclosure_events",
        ["fund_id", "disclosure_date"],
    )

    op.create_table(
        "v2_fund_level_manual_flags",
        sa.Column("manual_flag_id", sa.String(length=64), primary_key=True),
        sa.Column("firm_id", sa.String(length=64), nullable=False),
        sa.Column("fund_id", sa.String(length=64), nullable=False),
        sa.Column("advisor_id", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("active_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cleared_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cleared_by", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False,
            server_default=sa.true(),
        ),
    )
    op.create_index(
        "ix_v2_flmf_firm_fund_active",
        "v2_fund_level_manual_flags",
        ["firm_id", "fund_id", "is_active"],
    )

    op.create_table(
        "v2_e7_verdict_cache",
        sa.Column("cache_key", sa.String(length=256), primary_key=True),
        sa.Column("firm_id", sa.String(length=64), nullable=False),
        sa.Column("fund_id", sa.String(length=64), nullable=False),
        sa.Column(
            "latest_quarterly_disclosure_id",
            sa.String(length=64),
            nullable=True,
        ),
        sa.Column(
            "fund_manual_flag_id", sa.String(length=64), nullable=True,
        ),
        sa.Column("verdict_json", sa.JSON(), nullable=False),
        sa.Column("stage_json", sa.JSON(), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column("llm_model", sa.String(length=64), nullable=False),
        sa.Column("prompt_version", sa.String(length=16), nullable=False),
        sa.Column(
            "input_tokens", sa.Integer(), nullable=False,
            server_default="0",
        ),
        sa.Column(
            "output_tokens", sa.Integer(), nullable=False,
            server_default="0",
        ),
        sa.Column(
            "cache_hit_count", sa.Integer(), nullable=False,
            server_default="0",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "last_accessed_at", sa.DateTime(timezone=True), nullable=False,
        ),
    )
    op.create_index(
        "ix_v2_e7_firm_fund",
        "v2_e7_verdict_cache",
        ["firm_id", "fund_id"],
    )

    # ------------------------------------------------------------------
    # Chunk 8.4 — News events
    # ------------------------------------------------------------------
    op.create_table(
        "v2_news_events",
        sa.Column("news_id", sa.String(length=64), primary_key=True),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("headline", sa.Text(), nullable=False),
        sa.Column("body_text", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "associated_tickers", sa.String(length=1024), nullable=True,
        ),
        sa.Column("news_category", sa.String(length=64), nullable=True),
        sa.Column(
            "is_material_seed", sa.Boolean(), nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_index(
        "ix_v2_news_published",
        "v2_news_events",
        ["published_at"],
    )
    op.create_index(
        "ix_v2_news_tickers_published",
        "v2_news_events",
        ["associated_tickers", "published_at"],
    )


def downgrade() -> None:
    """Drop all cluster-8 infrastructure tables (reverse creation order)."""

    # Chunk 8.4
    op.drop_index("ix_v2_news_tickers_published", table_name="v2_news_events")
    op.drop_index("ix_v2_news_published", table_name="v2_news_events")
    op.drop_table("v2_news_events")

    # Chunk 8.3
    op.drop_index("ix_v2_e7_firm_fund", table_name="v2_e7_verdict_cache")
    op.drop_table("v2_e7_verdict_cache")

    op.drop_index(
        "ix_v2_flmf_firm_fund_active",
        table_name="v2_fund_level_manual_flags",
    )
    op.drop_table("v2_fund_level_manual_flags")

    op.drop_index(
        "ix_v2_qde_fund_date",
        table_name="v2_quarterly_disclosure_events",
    )
    op.drop_table("v2_quarterly_disclosure_events")

    # Chunk 8.2 (caches + sector)
    op.drop_index(
        "ix_v2_e2sis_firm_ticker", table_name="v2_e2sis_verdict_cache",
    )
    op.drop_table("v2_e2sis_verdict_cache")

    op.drop_index(
        "ix_v2_e2sv_firm_sector", table_name="v2_e2sv_verdict_cache",
    )
    op.drop_table("v2_e2sv_verdict_cache")

    op.drop_index(
        "ix_v2_slvmf_firm_sector_active",
        table_name="v2_sector_level_manual_flags",
    )
    op.drop_table("v2_sector_level_manual_flags")

    op.drop_index(
        "ix_v2_tsm_ticker_active", table_name="v2_ticker_sector_map",
    )
    op.drop_table("v2_ticker_sector_map")

    op.drop_table("v2_sector_classifications")

    # Chunk 8.1
    op.drop_index(
        "ix_v2_e3mv_firm_regime", table_name="v2_e3mv_verdict_cache",
    )
    op.drop_table("v2_e3mv_verdict_cache")

    op.drop_index(
        "ix_v2_rpe_material_date", table_name="v2_rate_policy_events",
    )
    op.drop_index(
        "ix_v2_rpe_type_date", table_name="v2_rate_policy_events",
    )
    op.drop_table("v2_rate_policy_events")

    op.drop_index(
        "ix_v2_macro_regime_active", table_name="v2_macro_regimes",
    )
    op.drop_table("v2_macro_regimes")

    # Chunk 8.2 — stock-level flags (created first in upgrade)
    op.drop_index(
        "ix_v2_slmf_firm_ticker_active",
        table_name="v2_stock_level_manual_flags",
    )
    op.drop_index(
        "ix_v2_slmf_ticker", table_name="v2_stock_level_manual_flags",
    )
    op.drop_table("v2_stock_level_manual_flags")
    # v2_e1_manual_flags was intentionally kept; downgrade leaves it intact.
