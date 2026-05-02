"""T1 telemetry table ORM model — cluster 0 placeholder.

Per Principles §5.2: "Every event of consequence ... is captured in T1 as an
immutable append-only ledger. T1 is the audit foundation; bit-identical
replay depends on it."

This is the minimum-viable persistence for T1 events that satisfies the
append-only invariant. The formal T1 bus contract (event ordering, transport,
retention, query indexes, GDPR-aware redaction) lives in FR Entry 9.0 which
will be authored by a future cluster (likely cluster 5 when the first agent
ships and emits operational events at volume). When that cluster runs, it
either keeps this table shape and grows around it, or migrates events out;
either way, the cluster 0 emission contract (event_name + payload + envelope
fields) is stable.

Schema is portable between SQLite and Postgres per DB Addendum §1.2 — using
SQLAlchemy ``JSON`` (TEXT-backed on SQLite, JSONB on Postgres) for the
per-event payload, no Postgres-only types or extensions.

Append-only is enforced at the application layer (no UPDATE / DELETE paths in
:mod:`artha.api_v2.observability.t1`); it is not enforced at the database
layer in cluster 0 (FR Entry 9.0 may add DB-level CHECK constraints or
table-rules later).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from artha.common.db.base import Base


class T1Event(Base):
    """One immutable telemetry event."""

    __tablename__ = "t1_events"

    # ULID, primary key. Lexicographically sortable by emission time, which
    # is convenient for time-range scans without needing a separate sort.
    event_id: Mapped[str] = mapped_column(String(26), primary_key=True)

    # Event name vocabulary is open; cluster 0 emits the names listed in
    # FR 17.0 §5, FR 17.1 §5, FR 18.0 §6. Indexed for filtering by name.
    event_name: Mapped[str] = mapped_column(String(100), index=True, nullable=False)

    # Per-event-type payload. Schema is the responsibility of the emitting
    # component; T1 stores it opaquely.
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    # Foreign key into the originating HTTP request, when there is one.
    # Null for events emitted outside an HTTP context (heartbeats, scheduled).
    request_id: Mapped[str | None] = mapped_column(String(26), nullable=True)

    # Server emission timestamp. Indexed for time-range queries.
    emitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

    # Firm scope of the event. Null for system-level events (auth flow steps
    # before the user is identified).
    firm_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
