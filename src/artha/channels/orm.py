"""SQLAlchemy ORM rows for the N0 notification channel.

Pass 19 persistence layer. The in-memory `NotificationChannel` from Pass
14 keeps its current shape for tests + small deployments; this module
provides the persistent equivalent backed by SQLite/Postgres.

Tables:
  * `n0_alerts` — one row per alert with delivery state, timeout, dedupe
    fingerprint, closure metadata, current `N0Alert` payload (JSON).
  * `n0_engagement_events` — append-only log of advisor engagement events
    per alert.

Design choices:
  * Alert payload (full `N0Alert`) is serialised as JSON in
    `alert_json`. The columns above it index the lifecycle state for
    cheap queries; the JSON column owns the canonical truth. On
    `resolve_watch` etc. we update both columns and the JSON copy.
  * `fingerprint` is denormalised into its own indexed column so dedupe
    queries don't need to parse the JSON.
  * `payload_hash` (SHA-256 of canonical alert JSON) is recomputed on
    every write so any in-place mutation produces a fresh hash.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from artha.common.db.base import Base


class N0AlertRow(Base):
    """Persistence row for one `N0Alert` + its lifecycle state."""

    __tablename__ = "n0_alerts"

    alert_id: Mapped[str] = mapped_column(String(26), primary_key=True)
    firm_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    client_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    case_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    originator: Mapped[str] = mapped_column(String(32), nullable=False)
    tier: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(64), nullable=False)

    # Lifecycle
    delivery_state: Mapped[str] = mapped_column(
        String(16), nullable=False, default="queued", index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    timeout_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    # Dedupe + integrity
    fingerprint: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    duplicate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    # Full N0Alert payload (canonical truth)
    alert_json: Mapped[str] = mapped_column(Text, nullable=False)

    # Closure metadata (only set once delivery_state moves to terminal)
    closure_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    closure_reason: Mapped[str | None] = mapped_column(String(256), nullable=True)
    successor_alert_id: Mapped[str | None] = mapped_column(String(26), nullable=True)

    __table_args__ = (
        Index("ix_n0_alerts_fingerprint_created", "fingerprint", "created_at"),
        Index("ix_n0_alerts_firm_state", "firm_id", "delivery_state"),
    )


class N0EngagementRow(Base):
    """Append-only engagement log per alert."""

    __tablename__ = "n0_engagement_events"

    event_id: Mapped[str] = mapped_column(String(26), primary_key=True)
    alert_id: Mapped[str] = mapped_column(
        String(26), ForeignKey("n0_alerts.alert_id"), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    advisor_id: Mapped[str] = mapped_column(String(64), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")

    __table_args__ = (
        Index("ix_n0_engagement_alert_timestamp", "alert_id", "timestamp"),
    )


__all__ = ["N0AlertRow", "N0EngagementRow"]
