"""PreferredPortfolioEntry canonical-entity ORM (FR Entry 10.7 §5,
FR Entry 13.2).

One row per ``(risk_profile, horizon, instrument_id)`` triple — the
firm's preferred-portfolio assignment of one instrument into one cell of
the 3x3 matrix with a role (``core / satellite / optional``) and a rank
within that role.

Identity invariant: ``UNIQUE(risk_profile, horizon, instrument_id)`` —
an instrument cannot appear twice in the same cell regardless of role.
The ORM enforces this; the chunk 4.3 admin UI's "add entry" panel
filters out instruments already preferred in the target cell.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from artha.common.db.base import Base


class PreferredPortfolioEntry(Base):
    """One curated entry in one cell of the model portfolio matrix."""

    __tablename__ = "v2_preferred_portfolio_entries"

    entry_id: Mapped[str] = mapped_column(String(26), primary_key=True)

    # ----- Cell identification -----
    risk_profile: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    horizon: Mapped[str] = mapped_column(String(20), nullable=False, index=True)

    # ----- The instrument -----
    instrument_id: Mapped[str] = mapped_column(
        String(26), nullable=False, index=True
    )

    # ----- Role + rank -----
    position_role: Mapped[str] = mapped_column(
        String(15), nullable=False, index=True
    )
    rank_within_role: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # ----- Optional curator commentary -----
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ----- Provenance -----
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_by: Mapped[str] = mapped_column(String(64), nullable=False)
    created_via: Mapped[str] = mapped_column(String(20), nullable=False)
    last_modified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    last_modified_by: Mapped[str] = mapped_column(String(64), nullable=False)

    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __table_args__ = (
        UniqueConstraint(
            "risk_profile",
            "horizon",
            "instrument_id",
            name="uq_v2_preferred_portfolio_entries_cell_instrument",
        ),
        Index(
            "ix_v2_preferred_portfolio_entries_cell",
            "risk_profile",
            "horizon",
        ),
        Index(
            "ix_v2_preferred_portfolio_entries_cell_role_rank",
            "risk_profile",
            "horizon",
            "position_role",
            "rank_within_role",
        ),
    )
