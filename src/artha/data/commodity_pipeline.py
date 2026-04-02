"""Commodity price pipeline — Gold, Silver, Crude via free APIs."""

from __future__ import annotations

import logging
import time
import uuid
from datetime import UTC, date, datetime, timedelta

import httpx
from sqlalchemy import func, select, String, Date, Float, Text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from artha.common.db.base import Base
from artha.data.models import PipelineRunRow

log = logging.getLogger(__name__)


class CommodityPriceRow(Base):
    __tablename__ = "commodity_prices"
    commodity: Mapped[str] = mapped_column(String(32), primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    price_usd: Mapped[float] = mapped_column(Float, nullable=True)
    price_inr: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit: Mapped[str] = mapped_column(String(16), default="oz")


# Use yfinance for commodity ETFs/futures as proxy — most reliable free source
COMMODITY_TICKERS = {
    "GOLD": ("GC=F", "oz"),       # Gold futures
    "SILVER": ("SI=F", "oz"),     # Silver futures
    "CRUDE_WTI": ("CL=F", "bbl"),  # WTI Crude
    "CRUDE_BRENT": ("BZ=F", "bbl"),  # Brent Crude
    "COPPER": ("HG=F", "lb"),     # Copper futures
    "NATGAS": ("NG=F", "mmbtu"),  # Natural Gas
}


async def run_commodity_pipeline(session: AsyncSession, initial: bool = False) -> str:
    import yfinance as yf

    run_id = str(uuid.uuid4())
    started = datetime.now(UTC)
    run = PipelineRunRow(id=run_id, pipeline="commodities", status="running", records_added=0, started_at=started)
    session.add(run)
    await session.flush()

    total_added = 0
    try:
        start_date = date.today() - timedelta(days=365 * 10) if initial else date.today() - timedelta(days=7)

        for commodity, (ticker, unit) in COMMODITY_TICKERS.items():
            log.info(f"  Fetching {commodity} ({ticker})...")
            try:
                df = yf.download(ticker, start=str(start_date), progress=False, auto_adjust=True)
            except Exception as e:
                log.warning(f"  Error fetching {commodity}: {e}")
                continue

            if df.empty:
                continue

            # Get latest existing date
            result = await session.execute(
                select(func.max(CommodityPriceRow.date)).where(CommodityPriceRow.commodity == commodity)
            )
            last_date = result.scalar()

            added = 0
            for idx, row in df.iterrows():
                d = idx.date() if hasattr(idx, "date") else idx
                if last_date and d <= last_date:
                    continue
                price = row.get("Close")
                if price is not None and price == price:
                    session.add(CommodityPriceRow(
                        commodity=commodity, date=d, price_usd=round(float(price), 4), unit=unit
                    ))
                    added += 1

            total_added += added
            log.info(f"  {commodity}: +{added} records")
            await session.flush()
            time.sleep(1)

        run.status = "completed"
        run.records_added = total_added
        run.completed_at = datetime.now(UTC)
        log.info(f"Commodity pipeline complete: {total_added} records")

    except Exception as e:
        log.error(f"Commodity pipeline failed: {e}")
        run.status = "failed"
        run.error = str(e)[:2000]
        run.completed_at = datetime.now(UTC)

    await session.flush()
    return run_id
