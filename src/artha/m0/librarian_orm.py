"""SQLAlchemy ORM rows for `M0.Librarian` session state.

Three tables:
  * `librarian_sessions` — session header (advisor / firm / client / lifecycle).
  * `librarian_turns` — append-only chronological turn log.
  * `librarian_pending_items` — pending ambiguities + followups, tracked
    via a single `kind` discriminator column.

`librarian_sessions.running_summary` is a TEXT column updated in place
when summary fragments arrive (the in-memory Librarian builds the
summary incrementally; we keep that pattern but persist).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from artha.common.db.base import Base


class LibrarianSessionRow(Base):
    """Persistence row for one `LibrarianSession`."""

    __tablename__ = "librarian_sessions"

    session_id: Mapped[str] = mapped_column(String(26), primary_key=True)
    advisor_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    firm_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    client_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    running_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    summary_token_budget: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1500
    )

    __table_args__ = (
        Index("ix_librarian_sessions_advisor_started", "advisor_id", "started_at"),
    )


class LibrarianTurnRow(Base):
    """Append-only chronological turn log for a Librarian session."""

    __tablename__ = "librarian_turns"

    turn_id: Mapped[str] = mapped_column(String(26), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        String(26),
        ForeignKey("librarian_sessions.session_id"),
        nullable=False,
        index=True,
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    parsed_intent: Mapped[str | None] = mapped_column(String(32), nullable=True)
    parsed_intent_confidence: Mapped[float | None] = mapped_column(
        nullable=True
    )
    downstream_event_ids_json: Mapped[str] = mapped_column(
        Text, nullable=False, default="[]"
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        Index("ix_librarian_turns_session_seq", "session_id", "sequence"),
    )


class LibrarianPendingItemRow(Base):
    """Pending ambiguities + followups for a Librarian session."""

    __tablename__ = "librarian_pending_items"

    item_id: Mapped[str] = mapped_column(String(26), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        String(26),
        ForeignKey("librarian_sessions.session_id"),
        nullable=False,
        index=True,
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # "ambiguity" / "followup"
    description: Mapped[str] = mapped_column(Text, nullable=False)
    introduced_turn_id: Mapped[str] = mapped_column(String(26), nullable=False)
    promised_by_turn_id: Mapped[str | None] = mapped_column(String(26), nullable=True)
    resolved: Mapped[bool] = mapped_column(nullable=False, default=False)
    resolved_turn_id: Mapped[str | None] = mapped_column(String(26), nullable=True)

    __table_args__ = (
        Index(
            "ix_librarian_pending_session_kind_resolved",
            "session_id", "kind", "resolved",
        ),
    )


__all__ = [
    "LibrarianPendingItemRow",
    "LibrarianSessionRow",
    "LibrarianTurnRow",
]
