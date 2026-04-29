"""SQLAlchemy ORM for the T1 ledger.

The `t1_events` table is append-only by app-level contract — `T1Repository`
exposes only `append` and read methods; no UPDATE or DELETE paths exist. For
DB-level enforcement on Postgres deployments, a future migration may add
`REVOKE UPDATE, DELETE` grants and a "no-update" trigger; SQLite (the default
local backend) does not support those primitives.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from artha.common.db.base import Base


class T1EventRow(Base):
    """Persistence row for `T1Event`. JSON columns are serialised as Text for SQLite portability."""

    __tablename__ = "t1_events"

    # Identity (event_id is the PK; ULIDs are time-sortable so chronological scans are cheap)
    event_id: Mapped[str] = mapped_column(String(26), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

    # Scope
    firm_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    case_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    client_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    advisor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Payload + integrity
    payload_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    # Versioning + correction chain
    version_pins_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    correction_of: Mapped[str | None] = mapped_column(String(26), nullable=True)

    __table_args__ = (
        Index("ix_t1_events_case_timestamp", "case_id", "timestamp"),
        Index("ix_t1_events_client_timestamp", "client_id", "timestamp"),
    )
