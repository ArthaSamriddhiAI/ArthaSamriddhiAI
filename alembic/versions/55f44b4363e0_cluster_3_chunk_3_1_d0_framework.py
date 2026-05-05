"""cluster_3_chunk_3_1_d0_framework

Creates cluster 3 chunk 3.1 framework tables:

* ``v2_staging_records`` per FR Entry 10.2 §2.1 — content-hashed audit-grade
  store of raw fetches.
* ``v2_snapshots`` per FR Entry 10.4 §2.3 — bit-identical replay snapshots.

Strangler-fig prefix retained per cluster 1 retrospective.

Revision ID: 55f44b4363e0
Revises: b56bb81a44b9 (cluster 2 chunk 2.1 mandates+versions)
Create Date: 2026-05-05
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "55f44b4363e0"
down_revision: Union[str, Sequence[str], None] = "b56bb81a44b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "v2_staging_records",
        sa.Column(
            "staging_record_id",
            sa.String(length=26),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("source_identifier", sa.String(length=64), nullable=False),
        sa.Column("source_subkey", sa.String(length=255), nullable=True),
        sa.Column("adapter_run_id", sa.String(length=26), nullable=False),
        sa.Column("raw_content", sa.JSON(), nullable=False),
        sa.Column("raw_content_format", sa.String(length=20), nullable=False),
        sa.Column("raw_content_hash", sa.String(length=64), nullable=False),
        sa.Column("raw_content_size_bytes", sa.Integer(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "source_metadata",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "schema_version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
    )
    op.create_index(
        "ix_v2_staging_records_source_identifier",
        "v2_staging_records",
        ["source_identifier"],
    )
    op.create_index(
        "ix_v2_staging_records_adapter_run_id",
        "v2_staging_records",
        ["adapter_run_id"],
    )
    op.create_index(
        "ix_v2_staging_records_raw_content_hash",
        "v2_staging_records",
        ["raw_content_hash"],
    )
    op.create_index(
        "ix_v2_staging_records_fetched_at",
        "v2_staging_records",
        ["fetched_at"],
    )
    op.create_index(
        "ix_v2_staging_records_source_run",
        "v2_staging_records",
        ["source_identifier", "adapter_run_id"],
    )

    op.create_table(
        "v2_snapshots",
        sa.Column(
            "snapshot_id", sa.String(length=26), primary_key=True, nullable=False
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("trigger_type", sa.String(length=40), nullable=False),
        sa.Column(
            "trigger_context",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column(
            "entity_counts",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("serialised_payload", sa.JSON(), nullable=False),
        sa.Column(
            "serialised_payload_size_bytes", sa.Integer(), nullable=False
        ),
        sa.Column(
            "source_metadata",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column(
            "associated_adapter_run_ids",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "verified_status",
            sa.String(length=40),
            nullable=False,
            server_default=sa.text("'never_verified'"),
        ),
        sa.Column(
            "schema_version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
    )
    op.create_index(
        "ix_v2_snapshots_created_at", "v2_snapshots", ["created_at"]
    )
    op.create_index(
        "ix_v2_snapshots_trigger_type", "v2_snapshots", ["trigger_type"]
    )
    op.create_index(
        "ix_v2_snapshots_verified_status",
        "v2_snapshots",
        ["verified_status"],
    )


def downgrade() -> None:
    op.drop_index("ix_v2_snapshots_verified_status", table_name="v2_snapshots")
    op.drop_index("ix_v2_snapshots_trigger_type", table_name="v2_snapshots")
    op.drop_index("ix_v2_snapshots_created_at", table_name="v2_snapshots")
    op.drop_table("v2_snapshots")
    op.drop_index(
        "ix_v2_staging_records_source_run", table_name="v2_staging_records"
    )
    op.drop_index(
        "ix_v2_staging_records_fetched_at", table_name="v2_staging_records"
    )
    op.drop_index(
        "ix_v2_staging_records_raw_content_hash",
        table_name="v2_staging_records",
    )
    op.drop_index(
        "ix_v2_staging_records_adapter_run_id",
        table_name="v2_staging_records",
    )
    op.drop_index(
        "ix_v2_staging_records_source_identifier",
        table_name="v2_staging_records",
    )
    op.drop_table("v2_staging_records")
