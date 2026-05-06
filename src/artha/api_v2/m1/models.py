"""Mandate + MandateVersion ORM models — FR Entry 10.7 §3.

Schema deviations from the FR text are intentional:

- Both tables carry the ``v2_`` prefix per cluster 1's strangler-fig
  retrospective (chunk 1.1 retrospective note 1).
- ``prohibited_instruments`` is a SQLAlchemy ``JSON`` column. SQLite stores
  it as TEXT; Postgres uses JSONB. Same portability wins that
  ``v2_c0_messages.metadata_json`` enjoys.
- The ``status`` column is a plain string column — SQLite has no ENUM type.
  The application enforces the enum via :class:`MandateVersionStatus`.

The Mandate ↔ MandateVersion relationship is one-to-many keyed by
``mandate_id``. The :attr:`Mandate.active_version_id` column points to the
single :class:`MandateVersion` currently in force; FR 10.7 §3.4 + §3.5
require this row + the active version's ``status="active"`` row to stay in
sync, which the service layer (:mod:`artha.api_v2.m1.service`) enforces
within an ``async with db.begin():`` boundary on every state-changing call.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from artha.common.db.base import Base


class MandateVersionStatus(str, Enum):
    """The :class:`MandateVersion` lifecycle cursor (FR 12.2 §2)."""

    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    ACTIVE = "active"
    ARCHIVED = "archived"
    REJECTED = "rejected"


class Mandate(Base):
    """One :class:`Mandate` per investor (FR 10.7 §3.1)."""

    __tablename__ = "v2_mandates"

    mandate_id: Mapped[str] = mapped_column(String(26), primary_key=True)

    # Unique per investor — FR 10.7 §3.1: "exactly one Mandate per investor".
    investor_id: Mapped[str] = mapped_column(
        String(26),
        ForeignKey("v2_investors.investor_id"),
        nullable=False,
    )

    # Pointer to the currently-active :class:`MandateVersion`. Nullable in
    # the brief window between Mandate insert and MandateVersion insert
    # within the same transaction; non-null after the create completes.
    active_version_id: Mapped[str | None] = mapped_column(
        String(26),
        ForeignKey("v2_mandate_versions.version_id", use_alter=True),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    # Cluster 5 demo seed framework (FR 10.7 cluster-5 revision §3.2).
    is_seed_data: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, index=True,
    )
    schema_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=2
    )

    __table_args__ = (
        UniqueConstraint("investor_id", name="uq_v2_mandates_investor"),
        Index("ix_v2_mandates_active_version_id", "active_version_id"),
    )


class MandateVersion(Base):
    """One row per version of a :class:`Mandate`'s constraints (FR 10.7 §3.2)."""

    __tablename__ = "v2_mandate_versions"

    version_id: Mapped[str] = mapped_column(String(26), primary_key=True)
    mandate_id: Mapped[str] = mapped_column(
        String(26),
        ForeignKey("v2_mandates.mandate_id"),
        nullable=False,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)

    # FSM cursor — see :class:`MandateVersionStatus`.
    status: Mapped[str] = mapped_column(String(20), nullable=False)

    # ---- Constraint family 1: asset allocation bands (FR 12.1 §2) ----
    # Cluster 3 chunk 3.1: added cash_min_pct + cash_max_pct (FR 12.1 §2.5
    # cluster 2 → 3 migration). Existing records get 0,0 via Alembic default.
    equity_min_pct: Mapped[int] = mapped_column(Integer, nullable=False)
    equity_max_pct: Mapped[int] = mapped_column(Integer, nullable=False)
    debt_min_pct: Mapped[int] = mapped_column(Integer, nullable=False)
    debt_max_pct: Mapped[int] = mapped_column(Integer, nullable=False)
    cash_min_pct: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cash_max_pct: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    alternatives_min_pct: Mapped[int] = mapped_column(Integer, nullable=False)
    alternatives_max_pct: Mapped[int] = mapped_column(Integer, nullable=False)

    # ---- Constraint family 2: single-position concentration (FR 12.1 §3) ----
    single_position_max_pct: Mapped[int] = mapped_column(Integer, nullable=False)

    # ---- Constraint family 3: liquidity floor (FR 12.1 §4) ----
    liquidity_floor_pct: Mapped[int] = mapped_column(Integer, nullable=False)

    # ---- Constraint family 4: sector exposure cap (FR 12.1 §5) ----
    sector_max_pct: Mapped[int] = mapped_column(Integer, nullable=False)

    # ---- Constraint family 5: prohibited instruments (FR 12.1 §6) ----
    # JSON list of strings. Empty list = no prohibitions.
    prohibited_instruments: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list
    )

    # ---- Provenance ----
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_via: Mapped[str] = mapped_column(String(20), nullable=False)
    parent_version_id: Mapped[str | None] = mapped_column(
        String(26),
        ForeignKey("v2_mandate_versions.version_id"),
        nullable=True,
    )

    # ---- Approval workflow (FR 12.2 §5; populated lazily) ----
    proposed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    proposed_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    approved_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    rejected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    rejected_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    approval_comments: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    changes_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    changes_requested_by: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    changes_requested_comments: Mapped[str | None] = mapped_column(
        String(2000), nullable=True
    )

    # ---- Activation ----
    activated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Cluster 5 demo seed framework (FR 10.7 cluster-5 revision §3.2).
    is_seed_data: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, index=True,
    )

    __table_args__ = (
        UniqueConstraint(
            "mandate_id", "version_number", name="uq_v2_mandate_versions_mandate_vn"
        ),
        Index("ix_v2_mandate_versions_mandate_id", "mandate_id"),
        # Composite index for the CIO's pending queue (FR 10.7 §3.5).
        Index(
            "ix_v2_mandate_versions_status_proposed",
            "status",
            "proposed_at",
        ),
        Index(
            "ix_v2_mandate_versions_parent_version",
            "parent_version_id",
        ),
    )
