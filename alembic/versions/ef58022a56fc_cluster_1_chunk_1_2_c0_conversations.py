"""cluster_1_chunk_1_2_c0_conversations

Creates the two cluster 1 chunk 1.2 tables per FR Entry 14.0 §3.1:

* ``v2_c0_conversations`` — one row per C0 conversation; tracks intent,
  FSM cursor, slot bag, and lifecycle status.
* ``v2_c0_messages`` — append-only message thread keyed by conversation.

Strangler-fig prefix retained (cluster 1 retrospective).

Revision ID: ef58022a56fc
Revises: b2bb3d2def6a (cluster 1 chunk 1.3 LLM provider config)
Create Date: 2026-05-04
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "ef58022a56fc"
down_revision: Union[str, Sequence[str], None] = "b2bb3d2def6a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "v2_c0_conversations",
        sa.Column("conversation_id", sa.String(length=26), primary_key=True, nullable=False),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("firm_id", sa.String(length=255), nullable=False),
        sa.Column("intent", sa.String(length=40), nullable=True),
        sa.Column("state", sa.String(length=40), nullable=False),
        sa.Column("collected_slots", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("investor_id", sa.String(length=26), nullable=True),
    )
    op.create_index(
        "ix_v2_c0_conversations_user_id", "v2_c0_conversations", ["user_id"]
    )
    op.create_index(
        "ix_v2_c0_conversations_firm_id", "v2_c0_conversations", ["firm_id"]
    )
    op.create_index(
        "ix_v2_c0_conversations_user_last_message",
        "v2_c0_conversations",
        ["user_id", "last_message_at"],
    )
    op.create_index(
        "ix_v2_c0_conversations_status", "v2_c0_conversations", ["status"]
    )

    op.create_table(
        "v2_c0_messages",
        sa.Column("message_id", sa.String(length=26), primary_key=True, nullable=False),
        sa.Column(
            "conversation_id",
            sa.String(length=26),
            sa.ForeignKey("v2_c0_conversations.conversation_id"),
            nullable=False,
        ),
        sa.Column("sender", sa.String(length=10), nullable=False),
        sa.Column("content", sa.String(length=4000), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_v2_c0_messages_conversation_id", "v2_c0_messages", ["conversation_id"]
    )
    op.create_index(
        "ix_v2_c0_messages_conversation_ts",
        "v2_c0_messages",
        ["conversation_id", "timestamp"],
    )


def downgrade() -> None:
    op.drop_index("ix_v2_c0_messages_conversation_ts", table_name="v2_c0_messages")
    op.drop_index("ix_v2_c0_messages_conversation_id", table_name="v2_c0_messages")
    op.drop_table("v2_c0_messages")

    op.drop_index("ix_v2_c0_conversations_status", table_name="v2_c0_conversations")
    op.drop_index(
        "ix_v2_c0_conversations_user_last_message", table_name="v2_c0_conversations"
    )
    op.drop_index("ix_v2_c0_conversations_firm_id", table_name="v2_c0_conversations")
    op.drop_index("ix_v2_c0_conversations_user_id", table_name="v2_c0_conversations")
    op.drop_table("v2_c0_conversations")
