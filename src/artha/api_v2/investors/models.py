"""Investor + Household ORM models for cluster 1.1.

Schema per FR Entry 10.7 §2.1.

NAMING CONVENTION — table prefix: per the cluster 1 retrospective, all v2
tables added during the strangler-fig coexistence period carry a ``v2_``
prefix. The v1 codebase already declares an ``investors`` table for its
own Investor module (``src/artha/investor/models.py:InvestorRow``); we
cannot drop or shadow it. Once the v1 codebase is fully sunset (per the
strangler-fig migration plan referenced in cluster 0 chunk plan), the
prefix can be removed in a dedicated rename migration.

The logical entity (per FR 10.7 §2 "The Investor Entity") remains
"Investor"; only the physical table name carries the prefix.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from artha.common.db.base import Base


class Household(Base):
    """Minimal household entity per chunk 1.1 §scope_in.

    Cluster 1 captures only the grouping (household_id + name); family
    relationships within the household (spouse, parent-child, etc.) are
    deferred to a future cluster per the cluster 1 demo-stage addendum §1.2.
    """

    __tablename__ = "v2_households"

    household_id: Mapped[str] = mapped_column(String(26), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # The advisor who created this household; useful for "households I created"
    # selector in the new-investor form.
    created_by: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Investor(Base):
    """Canonical Investor entity per FR Entry 10.7 §2.1.

    All fields from §2.1 are present. Identity + investment-profile fields
    are advisor-entered; KYC fields are reserved (always ``pending`` in
    cluster 1 demo per Cluster 1 Demo-Stage Addendum §1.1); enrichment
    fields are written by the I0 active layer (FR 11.1) inside the same
    creation transaction (per Ideation Log §4.4).
    """

    __tablename__ = "v2_investors"

    # ULID primary key (FR 10.7 §2.2 — time-ordered, index-friendly).
    investor_id: Mapped[str] = mapped_column(String(26), primary_key=True)

    # Identity (advisor-entered)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    phone: Mapped[str] = mapped_column(String(20), nullable=False)
    pan: Mapped[str] = mapped_column(String(10), index=True, nullable=False)
    age: Mapped[int] = mapped_column(Integer, nullable=False)

    # Grouping + assignment
    household_id: Mapped[str] = mapped_column(
        String(26),
        ForeignKey("v2_households.household_id"),
        index=True,
        nullable=False,
    )
    advisor_id: Mapped[str] = mapped_column(String(255), index=True, nullable=False)

    # Investment profile (enums stored as strings for SQLite portability)
    risk_appetite: Mapped[str] = mapped_column(String(20), nullable=False)
    time_horizon: Mapped[str] = mapped_column(String(20), nullable=False)

    # KYC placeholder (FR 10.7 §2.1; demo addendum §1.1: always 'pending')
    kyc_status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    kyc_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    kyc_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # I0 enrichment (FR 11.1; written inside the creation transaction)
    life_stage: Mapped[str | None] = mapped_column(String(20), nullable=True)
    life_stage_confidence: Mapped[str | None] = mapped_column(String(10), nullable=True)
    liquidity_tier: Mapped[str | None] = mapped_column(String(20), nullable=True)
    liquidity_tier_range: Mapped[str | None] = mapped_column(String(20), nullable=True)
    enriched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    enrichment_version: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Provenance + audit
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_via: Mapped[str] = mapped_column(String(20), nullable=False)  # form|conversational|api
    duplicate_pan_acknowledged: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_modified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_modified_by: Mapped[str] = mapped_column(String(255), nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    __table_args__ = (
        # FR 10.7 §2.3 indexes: composite on (advisor_id, created_at) for
        # the advisor's-recently-created queries that the investor list page hits.
        Index("ix_v2_investors_advisor_created", "advisor_id", "created_at"),
        # PAN uniqueness per §2.3 is enforced at the application layer to
        # support the warn-and-proceed workflow (the regular index speeds the
        # duplicate-detection query). SQLite partial unique indexes work but
        # we do the check-and-warn flow at the service layer regardless.
    )
