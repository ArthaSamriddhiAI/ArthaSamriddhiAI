"""SQLAlchemy ORM for client portfolio holdings and lifecycle."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from artha.common.db.base import Base


class PortfolioHoldingRow(Base):
    """Individual holding in a client's portfolio."""

    __tablename__ = "portfolio_holdings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    investor_id: Mapped[str] = mapped_column(String(36), nullable=False)
    asset_class: Mapped[str] = mapped_column(String(32), nullable=False)
    symbol_or_id: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(String(256), nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    acquisition_date: Mapped[date] = mapped_column(Date, nullable=False)
    acquisition_price: Mapped[float] = mapped_column(Float, nullable=False)
    current_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    current_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    gain_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    gain_loss_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("ix_portfolio_investor", "investor_id"),)


class PortfolioStateRow(Base):
    """Portfolio lifecycle state: DRAFT or LIVE."""

    __tablename__ = "portfolio_states"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    investor_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")  # draft | live
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    onboarding_type: Mapped[str | None] = mapped_column(String(32), nullable=True)  # existing | partial | new_capital
    frozen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    frozen_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    unfrozen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    unfrozen_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PortfolioEditLogRow(Base):
    """Audit log for every edit made in DRAFT state."""

    __tablename__ = "portfolio_edit_log"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    investor_id: Mapped[str] = mapped_column(String(36), nullable=False)
    holding_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    action: Mapped[str] = mapped_column(String(32), nullable=False)  # add | edit | delete | freeze | unfreeze | import_csv
    field_changed: Mapped[str | None] = mapped_column(String(64), nullable=True)
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor: Mapped[str] = mapped_column(String(128), nullable=False, default="advisor")
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("ix_edit_log_investor", "investor_id"),)


class PortfolioSnapshotRow(Base):
    """Frozen snapshot of portfolio at time of LIVE transition. Immutable."""

    __tablename__ = "portfolio_snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    investor_id: Mapped[str] = mapped_column(String(36), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    holdings_json: Mapped[str] = mapped_column(Text, nullable=False)  # JSON array of all holdings at freeze time
    total_invested: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    current_value: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    frozen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    frozen_by: Mapped[str] = mapped_column(String(128), nullable=False)

    __table_args__ = (Index("ix_snapshot_investor", "investor_id"),)
