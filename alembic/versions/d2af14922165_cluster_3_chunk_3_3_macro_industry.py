"""cluster_3_chunk_3_3_macro_industry

Creates ``v2_macro_snapshots`` + ``v2_industry_reports`` — the
canonical macro/industry tables seeded by the JSONFixtureAdapter
(cluster 3 chunk 3.3) and read by future case-orchestration
(cluster 5+) and governance-gate (cluster 8) consumers.

Revision ID: d2af14922165
Revises: 617b1d7967e5
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d2af14922165"
down_revision: Union[str, Sequence[str], None] = "617b1d7967e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create ``v2_macro_snapshots`` + ``v2_industry_reports``."""
    # ---- v2_macro_snapshots ----
    op.create_table(
        "v2_macro_snapshots",
        sa.Column("macro_snapshot_id", sa.String(length=26), primary_key=True),
        sa.Column("country_code", sa.String(length=2), nullable=False),
        sa.Column("snapshot_period", sa.String(length=20), nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("gdp_growth_pct", sa.Float(), nullable=True),
        sa.Column("cpi_inflation_pct", sa.Float(), nullable=True),
        sa.Column("wpi_inflation_pct", sa.Float(), nullable=True),
        sa.Column("repo_rate_pct", sa.Float(), nullable=True),
        sa.Column("reverse_repo_rate_pct", sa.Float(), nullable=True),
        sa.Column("bond_yield_10y_pct", sa.Float(), nullable=True),
        sa.Column("fx_usd_inr", sa.Float(), nullable=True),
        sa.Column("unemployment_rate_pct", sa.Float(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("themes", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("source_identifier", sa.String(length=64), nullable=False),
        sa.Column("source_subkey", sa.String(length=255), nullable=True),
        sa.Column("staging_record_id", sa.String(length=26), nullable=True),
        sa.Column("adapter_run_id", sa.String(length=26), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "last_modified_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column(
            "schema_version", sa.Integer(), nullable=False, server_default="1"
        ),
        sa.UniqueConstraint(
            "country_code",
            "snapshot_period",
            name="uq_v2_macro_snapshots_country_period",
        ),
    )
    op.create_index(
        "ix_v2_macro_snapshots_country_code",
        "v2_macro_snapshots",
        ["country_code"],
    )
    op.create_index(
        "ix_v2_macro_snapshots_snapshot_period",
        "v2_macro_snapshots",
        ["snapshot_period"],
    )
    op.create_index(
        "ix_v2_macro_snapshots_snapshot_date",
        "v2_macro_snapshots",
        ["snapshot_date"],
    )
    op.create_index(
        "ix_v2_macro_snapshots_source_identifier",
        "v2_macro_snapshots",
        ["source_identifier"],
    )
    op.create_index(
        "ix_v2_macro_snapshots_staging_record_id",
        "v2_macro_snapshots",
        ["staging_record_id"],
    )
    op.create_index(
        "ix_v2_macro_snapshots_adapter_run_id",
        "v2_macro_snapshots",
        ["adapter_run_id"],
    )
    op.create_index(
        "ix_v2_macro_snapshots_last_modified_at",
        "v2_macro_snapshots",
        ["last_modified_at"],
    )
    op.create_index(
        "ix_v2_macro_snapshots_country_date",
        "v2_macro_snapshots",
        ["country_code", "snapshot_date"],
    )

    # ---- v2_industry_reports ----
    op.create_table(
        "v2_industry_reports",
        sa.Column(
            "industry_report_id", sa.String(length=26), primary_key=True
        ),
        sa.Column("industry_code", sa.String(length=40), nullable=False),
        sa.Column("industry_name", sa.String(length=120), nullable=False),
        sa.Column("report_period", sa.String(length=20), nullable=False),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("outlook", sa.String(length=10), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column(
            "key_themes", sa.JSON(), nullable=False, server_default="[]"
        ),
        sa.Column(
            "drivers", sa.JSON(), nullable=False, server_default="[]"
        ),
        sa.Column("risks", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("source_identifier", sa.String(length=64), nullable=False),
        sa.Column("source_subkey", sa.String(length=255), nullable=True),
        sa.Column("staging_record_id", sa.String(length=26), nullable=True),
        sa.Column("adapter_run_id", sa.String(length=26), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "last_modified_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column(
            "schema_version", sa.Integer(), nullable=False, server_default="1"
        ),
        sa.UniqueConstraint(
            "industry_code",
            "report_period",
            name="uq_v2_industry_reports_code_period",
        ),
    )
    op.create_index(
        "ix_v2_industry_reports_industry_code",
        "v2_industry_reports",
        ["industry_code"],
    )
    op.create_index(
        "ix_v2_industry_reports_report_period",
        "v2_industry_reports",
        ["report_period"],
    )
    op.create_index(
        "ix_v2_industry_reports_report_date",
        "v2_industry_reports",
        ["report_date"],
    )
    op.create_index(
        "ix_v2_industry_reports_outlook",
        "v2_industry_reports",
        ["outlook"],
    )
    op.create_index(
        "ix_v2_industry_reports_source_identifier",
        "v2_industry_reports",
        ["source_identifier"],
    )
    op.create_index(
        "ix_v2_industry_reports_staging_record_id",
        "v2_industry_reports",
        ["staging_record_id"],
    )
    op.create_index(
        "ix_v2_industry_reports_adapter_run_id",
        "v2_industry_reports",
        ["adapter_run_id"],
    )
    op.create_index(
        "ix_v2_industry_reports_last_modified_at",
        "v2_industry_reports",
        ["last_modified_at"],
    )
    op.create_index(
        "ix_v2_industry_reports_code_date",
        "v2_industry_reports",
        ["industry_code", "report_date"],
    )


def downgrade() -> None:
    """Drop ``v2_industry_reports`` + ``v2_macro_snapshots``."""
    for ix in (
        "ix_v2_industry_reports_code_date",
        "ix_v2_industry_reports_last_modified_at",
        "ix_v2_industry_reports_adapter_run_id",
        "ix_v2_industry_reports_staging_record_id",
        "ix_v2_industry_reports_source_identifier",
        "ix_v2_industry_reports_outlook",
        "ix_v2_industry_reports_report_date",
        "ix_v2_industry_reports_report_period",
        "ix_v2_industry_reports_industry_code",
    ):
        op.drop_index(ix, "v2_industry_reports")
    op.drop_table("v2_industry_reports")

    for ix in (
        "ix_v2_macro_snapshots_country_date",
        "ix_v2_macro_snapshots_last_modified_at",
        "ix_v2_macro_snapshots_adapter_run_id",
        "ix_v2_macro_snapshots_staging_record_id",
        "ix_v2_macro_snapshots_source_identifier",
        "ix_v2_macro_snapshots_snapshot_date",
        "ix_v2_macro_snapshots_snapshot_period",
        "ix_v2_macro_snapshots_country_code",
    ):
        op.drop_index(ix, "v2_macro_snapshots")
    op.drop_table("v2_macro_snapshots")
