"""cluster_0_sessions_t1_events

Creates the two cluster 0 tables:

* ``sessions`` per FR Entry 17.1 §3.2 (with email/name added — see
  ``artha.api_v2.auth.models`` for the rationale, and
  ``previous_refresh_token_hash`` for theft detection per FR 17.0 §6.5).
* ``t1_events`` placeholder per Principles §5.2 (append-only ledger).
  Formal contract lives in FR Entry 9.0, authored by a future cluster.

All column types are portable between SQLite and Postgres per
Demo-Stage Database Addendum §1.2.

Revision ID: 370839f7aeeb
Revises:
Create Date: 2026-05-03

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "370839f7aeeb"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sessions",
        sa.Column("session_id", sa.String(length=26), primary_key=True, nullable=False),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("firm_id", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=50), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("refresh_token_hash", sa.LargeBinary(length=32), nullable=True),
        sa.Column("previous_refresh_token_hash", sa.LargeBinary(length=32), nullable=True),
        sa.Column("refresh_token_superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revocation_reason", sa.String(length=50), nullable=True),
        sa.Column("user_agent", sa.String(length=500), nullable=True),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])
    op.create_index(
        "ix_sessions_refresh_token_hash", "sessions", ["refresh_token_hash"]
    )
    op.create_index("ix_sessions_expires_at", "sessions", ["expires_at"])

    op.create_table(
        "t1_events",
        sa.Column("event_id", sa.String(length=26), primary_key=True, nullable=False),
        sa.Column("event_name", sa.String(length=100), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("request_id", sa.String(length=26), nullable=True),
        sa.Column("emitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("firm_id", sa.String(length=255), nullable=True),
    )
    op.create_index("ix_t1_events_event_name", "t1_events", ["event_name"])
    op.create_index("ix_t1_events_emitted_at", "t1_events", ["emitted_at"])
    op.create_index("ix_t1_events_firm_id", "t1_events", ["firm_id"])


def downgrade() -> None:
    op.drop_index("ix_t1_events_firm_id", table_name="t1_events")
    op.drop_index("ix_t1_events_emitted_at", table_name="t1_events")
    op.drop_index("ix_t1_events_event_name", table_name="t1_events")
    op.drop_table("t1_events")

    op.drop_index("ix_sessions_expires_at", table_name="sessions")
    op.drop_index("ix_sessions_refresh_token_hash", table_name="sessions")
    op.drop_index("ix_sessions_user_id", table_name="sessions")
    op.drop_table("sessions")
