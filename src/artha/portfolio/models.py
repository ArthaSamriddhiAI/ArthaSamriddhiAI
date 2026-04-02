"""SQLAlchemy ORM for client portfolio holdings."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, Index, String, Text
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
