"""Macro economic indicator pipeline — India VIX, bond yields, indices via yfinance + FRED."""

from __future__ import annotations

import logging
import time
import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select, String, Date, Float, Text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from artha.common.db.base import Base
from artha.data.models import PipelineRunRow

log = logging.getLogger(__name__)


class MacroIndicatorRow(Base):
    __tablename__ = "macro_indicators"
    indicator: Mapped[str] = mapped_column(String(64), primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(16), default="index")


# yfinance tickers for macro proxies
MACRO_TICKERS = {
    "INDIA_VIX": ("^INDIAVIX", "index"),
    "US_10Y_YIELD": ("^TNX", "pct"),
    "GOLD_USD": ("GC=F", "usd_oz"),
    "CRUDE_BRENT": ("BZ=F", "usd_bbl"),
    "USDINR": ("USDINR=X", "inr"),
    "DXY": ("DX-Y.NYB", "index"),
}


async def run_macro_pipeline(session: AsyncSession, initial: bool = False) -> str:
    import yfinance as yf

    run_id = str(uuid.uuid4())
    started = datetime.now(UTC)
    run = PipelineRunRow(id=run_id, pipeline="macro", status="running", records_added=0, started_at=started)
    session.add(run)
    await session.flush()

    total_added = 0
    try:
        start_date = date.today() - timedelta(days=365 * 10) if initial else date.today() - timedelta(days=7)

        for indicator, (ticker, unit) in MACRO_TICKERS.items():
            log.info(f"  Fetching {indicator} ({ticker})...")
            try:
                df = yf.download(ticker, start=str(start_date), progress=False, auto_adjust=True)
            except Exception as e:
                log.warning(f"  Error fetching {indicator}: {e}")
                continue

            if df.empty:
                continue

            result = await session.execute(
                select(func.max(MacroIndicatorRow.date)).where(MacroIndicatorRow.indicator == indicator)
            )
            last_date = result.scalar()

            added = 0
            close_col = df["Close"].squeeze() if "Close" in df.columns else df.iloc[:, 0]
            for idx in close_col.index:
                d = idx.date() if hasattr(idx, "date") else idx
                if last_date and d <= last_date:
                    continue
                val = float(close_col.loc[idx])
                if val is not None and val == val:
                    session.add(MacroIndicatorRow(indicator=indicator, date=d, value=round(float(val), 4), unit=unit))
                    added += 1

            total_added += added
            log.info(f"  {indicator}: +{added} records")
            await session.flush()
            time.sleep(1)

        run.status = "completed"
        run.records_added = total_added
        run.completed_at = datetime.now(UTC)
        log.info(f"Macro pipeline complete: {total_added} records")

    except Exception as e:
        log.error(f"Macro pipeline failed: {e}")
        run.status = "failed"
        run.error = str(e)[:2000]
        run.completed_at = datetime.now(UTC)

    await session.flush()
    return run_id
