"""C0 conversation + message ORM models — FR Entry 14.0 §3.1.

Schema deviations from the FR text are intentional:

- ``c0_messages.metadata_json`` is a pure ``JSON`` column. SQLAlchemy maps it
  to TEXT on SQLite and JSONB on Postgres per the demo-stage DB addendum.
- Both tables carry the ``v2_`` prefix per cluster 1's strangler-fig
  retrospective (chunk 1.1 retrospective note 1).

Both tables are append-only at the application layer (writes happen via
:mod:`artha.api_v2.c0.service`; the message thread is never mutated after
write). Append-only is enforced in code, not in the DB schema (matches the
T1 ledger pattern from cluster 0).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from artha.common.db.base import Base


class Conversation(Base):
    """One C0 conversation per FR Entry 14.0 §3.1.

    A conversation owns an evolving set of slots (``collected_slots``) and a
    state-machine cursor (``state``). The state column is a string so the
    FSM can grow new states without a migration; the application enforces
    the enum (see :data:`artha.api_v2.c0.state_machine.ConversationState`).
    """

    __tablename__ = "v2_c0_conversations"

    conversation_id: Mapped[str] = mapped_column(String(26), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    firm_id: Mapped[str] = mapped_column(String(255), index=True, nullable=False)

    # Intent is null until the very first user message has been classified.
    intent: Mapped[str | None] = mapped_column(String(40), nullable=True)

    # FSM cursor; see :class:`ConversationState`.
    state: Mapped[str] = mapped_column(String(40), nullable=False)

    # Per-slot working set. JSON for portability across SQLite + Postgres.
    collected_slots: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )

    # active | completed | abandoned | error.
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    last_message_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # ``investor_id`` populated only after STATE_EXECUTING succeeds. Lets a
    # completed conversation link straight to the resulting investor record
    # without re-deriving from the slot bag.
    investor_id: Mapped[str | None] = mapped_column(String(26), nullable=True)

    __table_args__ = (
        # Sidebar lists the user's conversations newest-first; this composite
        # index makes that scan one B-tree walk.
        Index(
            "ix_v2_c0_conversations_user_last_message",
            "user_id",
            "last_message_at",
        ),
        # Background abandonment job scans active rows by last_message_at;
        # cheap once active rows are the minority.
        Index("ix_v2_c0_conversations_status", "status"),
    )


class Message(Base):
    """One turn (user or system) within a conversation.

    Cluster 1 stores text only. Rich-content cards (confirmation summary,
    success card) are reconstructed client-side from the conversation's
    ``state`` + ``collected_slots`` + ``investor_id``; we do NOT serialise
    the full card payload into ``content`` to avoid drifting from the
    canonical investor record.
    """

    __tablename__ = "v2_c0_messages"

    message_id: Mapped[str] = mapped_column(String(26), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        String(26),
        ForeignKey("v2_c0_conversations.conversation_id"),
        index=True,
        nullable=False,
    )

    # ``user`` | ``system`` — kept as a string for SQLite portability.
    sender: Mapped[str] = mapped_column(String(10), nullable=False)

    content: Mapped[str] = mapped_column(String(4000), nullable=False)

    # Per-message structured side-data: detected intent, extracted slot
    # deltas, LLM call latency, fallback flags. Schema is open; the
    # application writes consistent shapes.
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )

    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    __table_args__ = (
        # Replay one conversation's full thread in send order — the most
        # common read pattern for the chat UI on mount.
        Index(
            "ix_v2_c0_messages_conversation_ts",
            "conversation_id",
            "timestamp",
        ),
    )
