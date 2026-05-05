"""cluster_3_chunk_3_2_instruments

Creates ``v2_instruments`` — the canonical Instrument table seeded by
the JSONFixtureAdapter (cluster 3 chunk 3.2) and read by the admin
browse endpoint, future model-portfolio entities (cluster 4), the
governance gate (cluster 8), and portfolio analytics (cluster 10).

Revision ID: 617b1d7967e5
Revises: cb221fac695d
Create Date: 2026-05-05 11:32:22.759429
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "617b1d7967e5"
down_revision: Union[str, Sequence[str], None] = "cb221fac695d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create ``v2_instruments`` with all chunk-3.2 indexes."""
    op.create_table(
        "v2_instruments",
        sa.Column("instrument_id", sa.String(length=26), primary_key=True),
        # Identifiers
        sa.Column("isin", sa.String(length=12), nullable=True),
        sa.Column("amfi_scheme_code", sa.String(length=20), nullable=True),
        sa.Column("exchange_ticker", sa.String(length=32), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("short_name", sa.String(length=100), nullable=True),
        # Classification
        sa.Column("asset_class", sa.String(length=20), nullable=False),
        sa.Column("vehicle_type", sa.String(length=40), nullable=False),
        sa.Column("sebi_category", sa.String(length=60), nullable=True),
        sa.Column("sebi_subcategory", sa.String(length=80), nullable=True),
        sa.Column(
            "classification_confidence",
            sa.String(length=10),
            nullable=False,
            server_default="high",
        ),
        # Issuer / fund house
        sa.Column("issuer_name", sa.String(length=255), nullable=True),
        sa.Column("amc_name", sa.String(length=255), nullable=True),
        # Risk
        sa.Column("riskometer_label", sa.String(length=40), nullable=True),
        # Status + lifecycle
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="active",
        ),
        sa.Column("inception_date", sa.Date(), nullable=True),
        # Source lineage
        sa.Column("source_identifier", sa.String(length=64), nullable=False),
        sa.Column("source_subkey", sa.String(length=255), nullable=True),
        sa.Column("staging_record_id", sa.String(length=26), nullable=True),
        sa.Column("adapter_run_id", sa.String(length=26), nullable=True),
        # Provenance
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "last_modified_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column(
            "schema_version", sa.Integer(), nullable=False, server_default="1"
        ),
    )
    op.create_index(
        "ix_v2_instruments_isin", "v2_instruments", ["isin"]
    )
    op.create_index(
        "ix_v2_instruments_amfi_scheme_code",
        "v2_instruments",
        ["amfi_scheme_code"],
    )
    op.create_index(
        "ix_v2_instruments_exchange_ticker",
        "v2_instruments",
        ["exchange_ticker"],
    )
    op.create_index(
        "ix_v2_instruments_asset_class", "v2_instruments", ["asset_class"]
    )
    op.create_index(
        "ix_v2_instruments_vehicle_type", "v2_instruments", ["vehicle_type"]
    )
    op.create_index(
        "ix_v2_instruments_sebi_category",
        "v2_instruments",
        ["sebi_category"],
    )
    op.create_index(
        "ix_v2_instruments_status", "v2_instruments", ["status"]
    )
    op.create_index(
        "ix_v2_instruments_source_identifier",
        "v2_instruments",
        ["source_identifier"],
    )
    op.create_index(
        "ix_v2_instruments_staging_record_id",
        "v2_instruments",
        ["staging_record_id"],
    )
    op.create_index(
        "ix_v2_instruments_adapter_run_id",
        "v2_instruments",
        ["adapter_run_id"],
    )
    op.create_index(
        "ix_v2_instruments_last_modified_at",
        "v2_instruments",
        ["last_modified_at"],
    )
    op.create_index(
        "ix_v2_instruments_class_vehicle",
        "v2_instruments",
        ["asset_class", "vehicle_type"],
    )
    op.create_index(
        "ix_v2_instruments_sebi_category_status",
        "v2_instruments",
        ["sebi_category", "status"],
    )


def downgrade() -> None:
    """Drop ``v2_instruments``."""
    op.drop_index("ix_v2_instruments_sebi_category_status", "v2_instruments")
    op.drop_index("ix_v2_instruments_class_vehicle", "v2_instruments")
    op.drop_index("ix_v2_instruments_last_modified_at", "v2_instruments")
    op.drop_index("ix_v2_instruments_adapter_run_id", "v2_instruments")
    op.drop_index("ix_v2_instruments_staging_record_id", "v2_instruments")
    op.drop_index("ix_v2_instruments_source_identifier", "v2_instruments")
    op.drop_index("ix_v2_instruments_status", "v2_instruments")
    op.drop_index("ix_v2_instruments_sebi_category", "v2_instruments")
    op.drop_index("ix_v2_instruments_vehicle_type", "v2_instruments")
    op.drop_index("ix_v2_instruments_asset_class", "v2_instruments")
    op.drop_index("ix_v2_instruments_exchange_ticker", "v2_instruments")
    op.drop_index("ix_v2_instruments_amfi_scheme_code", "v2_instruments")
    op.drop_index("ix_v2_instruments_isin", "v2_instruments")
    op.drop_table("v2_instruments")
