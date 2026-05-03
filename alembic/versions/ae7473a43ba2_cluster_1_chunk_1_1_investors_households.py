"""cluster_1_chunk_1_1_investors_households

Creates the two cluster 1 chunk 1.1 tables:

* ``v2_investors`` per FR Entry 10.7 §2.1 (the canonical Investor entity).
* ``v2_households`` per chunk 1.1 §scope_in (minimal household grouping;
  family relationships within a household deferred per Cluster 1 Demo-Stage
  Addendum §1.2).

Note on the ``v2_`` table prefix: the v1 codebase still declares an
``investors`` table for its own Investor module. Per the strangler-fig
principle, v1 stays operational; cluster 1 namespaces its tables to avoid
the name collision. See chunk plan retrospective for details.

All column types are portable between SQLite and Postgres per
Demo-Stage Database Addendum §1.2.

Revision ID: ae7473a43ba2
Revises: 370839f7aeeb (cluster 0 sessions + t1_events)
Create Date: 2026-05-04
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op


revision: str = "ae7473a43ba2"
down_revision: Union[str, Sequence[str], None] = "370839f7aeeb"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "v2_households",
        sa.Column("household_id", sa.String(length=26), primary_key=True, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_v2_households_created_by", "v2_households", ["created_by"])

    op.create_table(
        "v2_investors",
        sa.Column("investor_id", sa.String(length=26), primary_key=True, nullable=False),
        # Identity
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("phone", sa.String(length=20), nullable=False),
        sa.Column("pan", sa.String(length=10), nullable=False),
        sa.Column("age", sa.Integer(), nullable=False),
        # Grouping + assignment
        sa.Column(
            "household_id",
            sa.String(length=26),
            sa.ForeignKey("v2_households.household_id"),
            nullable=False,
        ),
        sa.Column("advisor_id", sa.String(length=255), nullable=False),
        # Investment profile
        sa.Column("risk_appetite", sa.String(length=20), nullable=False),
        sa.Column("time_horizon", sa.String(length=20), nullable=False),
        # KYC (always 'pending' in demo per Cluster 1 Demo-Stage Addendum §1.1)
        sa.Column(
            "kyc_status",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("kyc_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("kyc_provider", sa.String(length=64), nullable=True),
        # I0 enrichment (FR 11.1)
        sa.Column("life_stage", sa.String(length=20), nullable=True),
        sa.Column("life_stage_confidence", sa.String(length=10), nullable=True),
        sa.Column("liquidity_tier", sa.String(length=20), nullable=True),
        sa.Column("liquidity_tier_range", sa.String(length=20), nullable=True),
        sa.Column("enriched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("enrichment_version", sa.String(length=64), nullable=True),
        # Provenance + audit
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("created_via", sa.String(length=20), nullable=False),
        sa.Column(
            "duplicate_pan_acknowledged",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("last_modified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_modified_by", sa.String(length=255), nullable=False),
        sa.Column(
            "schema_version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
    )
    op.create_index("ix_v2_investors_email", "v2_investors", ["email"])
    op.create_index("ix_v2_investors_pan", "v2_investors", ["pan"])
    op.create_index("ix_v2_investors_household_id", "v2_investors", ["household_id"])
    op.create_index("ix_v2_investors_advisor_id", "v2_investors", ["advisor_id"])
    op.create_index(
        "ix_v2_investors_advisor_created", "v2_investors", ["advisor_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_v2_investors_advisor_created", table_name="v2_investors")
    op.drop_index("ix_v2_investors_advisor_id", table_name="v2_investors")
    op.drop_index("ix_v2_investors_household_id", table_name="v2_investors")
    op.drop_index("ix_v2_investors_pan", table_name="v2_investors")
    op.drop_index("ix_v2_investors_email", table_name="v2_investors")
    op.drop_table("v2_investors")

    op.drop_index("ix_v2_households_created_by", table_name="v2_households")
    op.drop_table("v2_households")
