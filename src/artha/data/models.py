"""SQLAlchemy ORM models for market data pipelines."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import BigInteger, Boolean, Date, DateTime, Float, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from artha.common.db.base import Base


class StockPriceRow(Base):
    """Daily adjusted close price for Nifty 500 stocks."""

    __tablename__ = "stock_prices"

    symbol: Mapped[str] = mapped_column(String(20), primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    adj_close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    __table_args__ = (Index("ix_stock_prices_date", "date"),)


class MFNavRow(Base):
    """Daily NAV for mutual fund schemes."""

    __tablename__ = "mf_navs"

    scheme_code: Mapped[str] = mapped_column(String(10), primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    nav: Mapped[float] = mapped_column(Float, nullable=False)

    __table_args__ = (Index("ix_mf_navs_date", "date"),)


class StockUniverseRow(Base):
    """Nifty 500 constituent list."""

    __tablename__ = "stock_universe"

    symbol: Mapped[str] = mapped_column(String(20), primary_key=True)
    nse_ticker: Mapped[str] = mapped_column(String(24), nullable=False)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class MFUniverseRow(Base):
    """Tracked mutual fund schemes."""

    __tablename__ = "mf_universe"

    scheme_code: Mapped[str] = mapped_column(String(10), primary_key=True)
    scheme_name: Mapped[str] = mapped_column(String(256), nullable=False)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class PipelineRunRow(Base):
    """Pipeline execution audit log."""

    __tablename__ = "data_pipeline_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    pipeline: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    records_added: Mapped[int] = mapped_column(default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
