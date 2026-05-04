"""cluster_1_chunk_1_3_llm_provider_config

Creates ``v2_llm_provider_config``: the SmartLLMRouter's persistent config
row, per FR Entry 16.0 §4.1.

Cluster 1 chunk 1.3 ships a *singleton* row keyed by ``config_id="singleton"``
— the column-level PK is already a string so a future cluster can version
the row by writing per-change ULIDs without a schema migration.

API keys are stored as Fernet ciphertext bytes (``LargeBinary``) in the
``*_api_key_encrypted`` columns; the deployment-level encryption key lives
in the ``SAMRIDDHI_ENCRYPTION_KEY`` env var (FR 16.0 §4.1).

All column types are portable between SQLite and Postgres per Demo-Stage
Database Addendum §1.2 (``LargeBinary`` maps to ``BLOB`` on SQLite and
``BYTEA`` on Postgres).

Revision ID: b2bb3d2def6a
Revises: ae7473a43ba2 (cluster 1 chunk 1.1 investors + households)
Create Date: 2026-05-04
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "b2bb3d2def6a"
down_revision: Union[str, Sequence[str], None] = "ae7473a43ba2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "v2_llm_provider_config",
        sa.Column("config_id", sa.String(length=64), primary_key=True, nullable=False),
        # active_provider is nullable (un-configured = no provider selected).
        sa.Column("active_provider", sa.String(length=20), nullable=True),
        # API keys: Fernet ciphertext bytes; NULL when not yet entered.
        sa.Column("mistral_api_key_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column("claude_api_key_encrypted", sa.LargeBinary(), nullable=True),
        # Default per-provider model (overridable via the settings UI).
        sa.Column(
            "default_mistral_model",
            sa.String(length=64),
            nullable=False,
            server_default="mistral-small-latest",
        ),
        sa.Column(
            "default_claude_model",
            sa.String(length=64),
            nullable=False,
            server_default="claude-sonnet-4-5-20250929",
        ),
        # Rate + timeout knobs (FR 16.0 §5).
        sa.Column(
            "rate_limit_calls_per_minute",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("60"),
        ),
        sa.Column(
            "request_timeout_seconds",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("30"),
        ),
        # Kill switch (FR 16.0 §7).
        sa.Column(
            "kill_switch_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        # Audit columns; full change history lives in T1.
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.String(length=255), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("v2_llm_provider_config")
