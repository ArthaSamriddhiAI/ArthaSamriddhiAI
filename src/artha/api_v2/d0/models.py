"""D0 staging + snapshot ORM models (FR Entry 10.2 §2.1 + FR Entry 10.4 §2.3).

Both tables carry the ``v2_`` prefix per cluster 1's strangler-fig
retrospective. Both store JSON content (``raw_content`` + ``serialised_payload``
+ ``source_metadata``) as portable :class:`sqlalchemy.JSON` columns —
TEXT-backed on SQLite, JSONB on Postgres.

Append-only invariant is enforced at the application layer; the schema
imposes no DB-level CHECK constraints beyond NOT NULL where required.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from artha.common.db.base import Base


class StagingRecord(Base):
    """One raw fetch persisted with its content hash (FR 10.2)."""

    __tablename__ = "v2_staging_records"

    staging_record_id: Mapped[str] = mapped_column(String(26), primary_key=True)

    # Source identification
    source_identifier: Mapped[str] = mapped_column(
        String(64), index=True, nullable=False
    )
    source_subkey: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Run association
    adapter_run_id: Mapped[str] = mapped_column(
        String(26), index=True, nullable=False
    )

    # Content
    raw_content: Mapped[Any] = mapped_column(JSON, nullable=False)
    raw_content_format: Mapped[str] = mapped_column(String(20), nullable=False)
    raw_content_hash: Mapped[str] = mapped_column(
        String(64), index=True, nullable=False
    )
    raw_content_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)

    # Metadata
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True, nullable=False
    )
    source_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )

    # Provenance
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    schema_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1
    )

    __table_args__ = (
        Index(
            "ix_v2_staging_records_source_run",
            "source_identifier",
            "adapter_run_id",
        ),
    )


class Snapshot(Base):
    """One canonical-entity-state snapshot (FR 10.4 §2.3).

    Cluster 3 uses Approach A: ``serialised_payload`` carries the full
    entity state at snapshot time as canonical-JSON bytes. ``content_hash``
    is the SHA-256 of those bytes; verification re-serialises the payload
    and recomputes.
    """

    __tablename__ = "v2_snapshots"

    snapshot_id: Mapped[str] = mapped_column(String(26), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)

    # Identity
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    trigger_type: Mapped[str] = mapped_column(String(40), nullable=False)
    trigger_context: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )

    # Content
    entity_counts: Mapped[dict[str, int]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    serialised_payload: Mapped[Any] = mapped_column(JSON, nullable=False)
    serialised_payload_size_bytes: Mapped[int] = mapped_column(
        Integer, nullable=False
    )

    # Source linkage
    source_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    associated_adapter_run_ids: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list
    )

    # Verification
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    verified_status: Mapped[str] = mapped_column(
        String(40), nullable=False, default="never_verified"
    )

    schema_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1
    )

    __table_args__ = (
        Index("ix_v2_snapshots_trigger_type", "trigger_type"),
        Index("ix_v2_snapshots_verified_status", "verified_status"),
    )
