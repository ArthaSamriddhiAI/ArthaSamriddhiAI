"""cluster_4_chunk_4_1_model_portfolio

Cluster 4 chunk 4.1: model portfolio data foundation.

Adds the model_portfolio_tags field plus modification metadata to
``v2_instruments`` and creates the new ``v2_preferred_portfolio_entries``
table holding cell-level curation (FR Entry 13.1 + 13.2).

The default loader (run from the lifespan hook) populates tags from the
SEBI category + vehicle type rules and inserts entries from
``data/fixtures/default_model_portfolio.json``; the migration itself
just creates the schema.

Revision ID: e60794b9c039
Revises: d2af14922165
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e60794b9c039"
down_revision: Union[str, Sequence[str], None] = "d2af14922165"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # ---- Extend v2_instruments with the model portfolio tag fields ----
    op.add_column(
        "v2_instruments",
        sa.Column(
            "model_portfolio_tags",
            sa.JSON(),
            nullable=False,
            server_default="[]",
        ),
    )
    op.add_column(
        "v2_instruments",
        sa.Column(
            "model_portfolio_tags_modified_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "v2_instruments",
        sa.Column(
            "model_portfolio_tags_modified_by",
            sa.String(length=64),
            nullable=True,
        ),
    )

    # ---- Create v2_preferred_portfolio_entries ----
    op.create_table(
        "v2_preferred_portfolio_entries",
        sa.Column("entry_id", sa.String(length=26), primary_key=True),
        sa.Column("risk_profile", sa.String(length=20), nullable=False),
        sa.Column("horizon", sa.String(length=20), nullable=False),
        sa.Column("instrument_id", sa.String(length=26), nullable=False),
        sa.Column("position_role", sa.String(length=15), nullable=False),
        sa.Column(
            "rank_within_role",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.Column("created_via", sa.String(length=20), nullable=False),
        sa.Column(
            "last_modified_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column("last_modified_by", sa.String(length=64), nullable=False),
        sa.Column(
            "schema_version",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
        sa.UniqueConstraint(
            "risk_profile",
            "horizon",
            "instrument_id",
            name="uq_v2_preferred_portfolio_entries_cell_instrument",
        ),
    )
    op.create_index(
        "ix_v2_preferred_portfolio_entries_risk_profile",
        "v2_preferred_portfolio_entries",
        ["risk_profile"],
    )
    op.create_index(
        "ix_v2_preferred_portfolio_entries_horizon",
        "v2_preferred_portfolio_entries",
        ["horizon"],
    )
    op.create_index(
        "ix_v2_preferred_portfolio_entries_instrument_id",
        "v2_preferred_portfolio_entries",
        ["instrument_id"],
    )
    op.create_index(
        "ix_v2_preferred_portfolio_entries_position_role",
        "v2_preferred_portfolio_entries",
        ["position_role"],
    )
    op.create_index(
        "ix_v2_preferred_portfolio_entries_cell",
        "v2_preferred_portfolio_entries",
        ["risk_profile", "horizon"],
    )
    op.create_index(
        "ix_v2_preferred_portfolio_entries_cell_role_rank",
        "v2_preferred_portfolio_entries",
        ["risk_profile", "horizon", "position_role", "rank_within_role"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    for ix in (
        "ix_v2_preferred_portfolio_entries_cell_role_rank",
        "ix_v2_preferred_portfolio_entries_cell",
        "ix_v2_preferred_portfolio_entries_position_role",
        "ix_v2_preferred_portfolio_entries_instrument_id",
        "ix_v2_preferred_portfolio_entries_horizon",
        "ix_v2_preferred_portfolio_entries_risk_profile",
    ):
        op.drop_index(ix, "v2_preferred_portfolio_entries")
    op.drop_table("v2_preferred_portfolio_entries")

    # SQLite can't drop columns prior to 3.35; the migration is one-way for
    # cluster-3-vintage SQLite deployments. Postgres can drop cleanly.
    with op.batch_alter_table("v2_instruments") as batch:
        batch.drop_column("model_portfolio_tags_modified_by")
        batch.drop_column("model_portfolio_tags_modified_at")
        batch.drop_column("model_portfolio_tags")
