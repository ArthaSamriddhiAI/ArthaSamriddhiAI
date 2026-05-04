"""cluster_2_chunk_2_1_mandates_versions

Creates cluster 2 chunk 2.1 + 2.4 tables per FR Entry 10.7 §3:

* ``v2_mandates`` — one row per investor mandate (identity + active version
  pointer).
* ``v2_mandate_versions`` — versioned rows holding the five constraint
  families plus full amendment-lifecycle metadata.

Strangler-fig prefix retained (cluster 1 retrospective).

Revision ID: b56bb81a44b9
Revises: ef58022a56fc (cluster 1 chunk 1.2 C0 conversations)
Create Date: 2026-05-04
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "b56bb81a44b9"
down_revision: Union[str, Sequence[str], None] = "ef58022a56fc"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ``v2_mandates`` first; the FK from ``v2_mandates.active_version_id`` to
    # ``v2_mandate_versions.version_id`` uses ``use_alter=True`` so the
    # tables can be created in either order without a circular-FK error.
    op.create_table(
        "v2_mandates",
        sa.Column("mandate_id", sa.String(length=26), primary_key=True, nullable=False),
        sa.Column(
            "investor_id",
            sa.String(length=26),
            sa.ForeignKey("v2_investors.investor_id"),
            nullable=False,
        ),
        sa.Column(
            "active_version_id",
            sa.String(length=26),
            sa.ForeignKey(
                "v2_mandate_versions.version_id",
                use_alter=True,
                name="fk_v2_mandates_active_version_id",
            ),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column(
            "schema_version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.UniqueConstraint("investor_id", name="uq_v2_mandates_investor"),
    )
    op.create_index(
        "ix_v2_mandates_active_version_id",
        "v2_mandates",
        ["active_version_id"],
    )

    op.create_table(
        "v2_mandate_versions",
        sa.Column("version_id", sa.String(length=26), primary_key=True, nullable=False),
        sa.Column(
            "mandate_id",
            sa.String(length=26),
            sa.ForeignKey("v2_mandates.mandate_id"),
            nullable=False,
        ),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        # Asset allocation bands.
        sa.Column("equity_min_pct", sa.Integer(), nullable=False),
        sa.Column("equity_max_pct", sa.Integer(), nullable=False),
        sa.Column("debt_min_pct", sa.Integer(), nullable=False),
        sa.Column("debt_max_pct", sa.Integer(), nullable=False),
        sa.Column("alternatives_min_pct", sa.Integer(), nullable=False),
        sa.Column("alternatives_max_pct", sa.Integer(), nullable=False),
        # Single-position concentration.
        sa.Column("single_position_max_pct", sa.Integer(), nullable=False),
        # Liquidity floor.
        sa.Column("liquidity_floor_pct", sa.Integer(), nullable=False),
        # Sector cap.
        sa.Column("sector_max_pct", sa.Integer(), nullable=False),
        # Prohibited instruments.
        sa.Column(
            "prohibited_instruments",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        # Provenance.
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("created_via", sa.String(length=20), nullable=False),
        sa.Column(
            "parent_version_id",
            sa.String(length=26),
            sa.ForeignKey("v2_mandate_versions.version_id"),
            nullable=True,
        ),
        # Approval workflow (lazily populated).
        sa.Column("proposed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("proposed_by", sa.String(length=255), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by", sa.String(length=255), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_by", sa.String(length=255), nullable=True),
        sa.Column("rejection_reason", sa.String(length=2000), nullable=True),
        sa.Column("approval_comments", sa.String(length=2000), nullable=True),
        sa.Column("changes_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("changes_requested_by", sa.String(length=255), nullable=True),
        sa.Column("changes_requested_comments", sa.String(length=2000), nullable=True),
        # Activation.
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "mandate_id",
            "version_number",
            name="uq_v2_mandate_versions_mandate_vn",
        ),
    )
    op.create_index(
        "ix_v2_mandate_versions_mandate_id",
        "v2_mandate_versions",
        ["mandate_id"],
    )
    op.create_index(
        "ix_v2_mandate_versions_status_proposed",
        "v2_mandate_versions",
        ["status", "proposed_at"],
    )
    op.create_index(
        "ix_v2_mandate_versions_parent_version",
        "v2_mandate_versions",
        ["parent_version_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_v2_mandate_versions_parent_version",
        table_name="v2_mandate_versions",
    )
    op.drop_index(
        "ix_v2_mandate_versions_status_proposed",
        table_name="v2_mandate_versions",
    )
    op.drop_index(
        "ix_v2_mandate_versions_mandate_id",
        table_name="v2_mandate_versions",
    )
    op.drop_table("v2_mandate_versions")
    op.drop_index("ix_v2_mandates_active_version_id", table_name="v2_mandates")
    op.drop_table("v2_mandates")
