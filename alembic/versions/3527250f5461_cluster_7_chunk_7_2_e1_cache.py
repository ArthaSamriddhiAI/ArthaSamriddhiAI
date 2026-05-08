"""cluster_7_chunk_7_2_e1_cache

Cluster 7 chunk 7.2: E1 verdict cache + analyst manual-flag service.

Adds two tables:

- ``v2_e1_verdict_cache`` — keyed by the E1 cache string the shim
  produces (``e1:{ticker}:{earnings_id}:{manual_flag_id}``). Stores
  the structured verdict, EvidenceVerdict-shaped stage payload, raw
  LLM response text, and per-call cost telemetry.
- ``v2_e1_manual_flags`` — analyst-set flags that rotate the E1 cache
  key for a ticker (e.g. promoter pledge, audit qualification). At
  most one *active* flag per ticker at a time, enforced at the
  application layer in :mod:`agents.cache.manual_flag` (no partial-
  index syntax to keep SQLite + Postgres compatibility).

The three invalidation triggers (chunk 7.2 §3.2) — earnings auto,
manual flag, 90-day TTL — are application-layer concerns implemented
in :mod:`agents.cache.repository`. The schema only has to support
fast lookups by ``(ticker, earnings_id)`` and by ``manual_flag_id``,
plus a ``created_at`` index for TTL eviction.

Revision ID: 3527250f5461
Revises: 6da5d8b614b0
"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3527250f5461"
down_revision: Union[str, Sequence[str], None] = "6da5d8b614b0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Forward-roll the E1 verdict cache + manual-flag tables."""
    # ------------------------------------------------------------------
    # v2_e1_verdict_cache
    # ------------------------------------------------------------------
    op.create_table(
        "v2_e1_verdict_cache",
        sa.Column("cache_key", sa.String(length=200), primary_key=True),
        sa.Column("ticker", sa.String(length=40), nullable=False),
        sa.Column("earnings_id", sa.String(length=64), nullable=False),
        sa.Column("manual_flag_id", sa.String(length=26), nullable=True),
        sa.Column("prompt_version", sa.String(length=80), nullable=False),
        sa.Column("verdict_payload", sa.JSON(), nullable=False),
        sa.Column("stage_payload", sa.JSON(), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column("llm_model", sa.String(length=80), nullable=False),
        sa.Column(
            "input_tokens", sa.Integer(), nullable=False, server_default="0",
        ),
        sa.Column(
            "output_tokens", sa.Integer(), nullable=False, server_default="0",
        ),
        sa.Column("case_id", sa.String(length=26), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "schema_version", sa.Integer(), nullable=False, server_default="1",
        ),
    )
    op.create_index(
        "ix_v2_e1_verdict_cache_ticker",
        "v2_e1_verdict_cache",
        ["ticker"],
    )
    op.create_index(
        "ix_v2_e1_verdict_cache_manual_flag_id",
        "v2_e1_verdict_cache",
        ["manual_flag_id"],
    )
    op.create_index(
        "ix_v2_e1_verdict_cache_created_at",
        "v2_e1_verdict_cache",
        ["created_at"],
    )
    op.create_index(
        "ix_v2_e1_cache_ticker_earnings",
        "v2_e1_verdict_cache",
        ["ticker", "earnings_id"],
    )

    # ------------------------------------------------------------------
    # v2_e1_manual_flags
    # ------------------------------------------------------------------
    op.create_table(
        "v2_e1_manual_flags",
        sa.Column(
            "manual_flag_id", sa.String(length=26), primary_key=True,
        ),
        sa.Column("ticker", sa.String(length=40), nullable=False),
        sa.Column("flagged_by", sa.String(length=64), nullable=False),
        sa.Column(
            "flagged_at", sa.DateTime(timezone=True), nullable=False,
        ),
        sa.Column(
            "cleared_at", sa.DateTime(timezone=True), nullable=True,
        ),
        sa.Column("cleared_by", sa.String(length=64), nullable=True),
        sa.Column("reason", sa.String(length=200), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "schema_version", sa.Integer(), nullable=False, server_default="1",
        ),
    )
    op.create_index(
        "ix_v2_e1_manual_flags_ticker",
        "v2_e1_manual_flags",
        ["ticker"],
    )
    op.create_index(
        "ix_v2_e1_manual_flags_is_active",
        "v2_e1_manual_flags",
        ["is_active"],
    )
    op.create_index(
        "ix_v2_e1_manual_flags_flagged_at",
        "v2_e1_manual_flags",
        ["flagged_at"],
    )
    op.create_index(
        "ix_v2_e1_manual_flags_ticker_active",
        "v2_e1_manual_flags",
        ["ticker", "is_active"],
    )


def downgrade() -> None:
    """Roll back the E1 verdict cache + manual-flag tables."""
    op.drop_index(
        "ix_v2_e1_manual_flags_ticker_active",
        table_name="v2_e1_manual_flags",
    )
    op.drop_index(
        "ix_v2_e1_manual_flags_flagged_at",
        table_name="v2_e1_manual_flags",
    )
    op.drop_index(
        "ix_v2_e1_manual_flags_is_active",
        table_name="v2_e1_manual_flags",
    )
    op.drop_index(
        "ix_v2_e1_manual_flags_ticker",
        table_name="v2_e1_manual_flags",
    )
    op.drop_table("v2_e1_manual_flags")

    op.drop_index(
        "ix_v2_e1_cache_ticker_earnings",
        table_name="v2_e1_verdict_cache",
    )
    op.drop_index(
        "ix_v2_e1_verdict_cache_created_at",
        table_name="v2_e1_verdict_cache",
    )
    op.drop_index(
        "ix_v2_e1_verdict_cache_manual_flag_id",
        table_name="v2_e1_verdict_cache",
    )
    op.drop_index(
        "ix_v2_e1_verdict_cache_ticker",
        table_name="v2_e1_verdict_cache",
    )
    op.drop_table("v2_e1_verdict_cache")
