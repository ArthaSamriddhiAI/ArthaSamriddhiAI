"""Forex rate pipeline — major INR pairs via yfinance."""

from __future__ import annotations

import logging
import time
import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select, String, Date, Float
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from artha.common.db.base import Base
from artha.data.models import PipelineRunRow

log = logging.getLogger(__name__)


class ForexRateRow(Base):
    __tablename__ = "forex_rates"
    pair: Mapped[str] = mapped_column(String(10), primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    rate: Mapped[float] = mapped_column(Float, nullable=False)


FOREX_TICKERS = {
    "USDINR": "USDINR=X",
    "EURINR": "EURINR=X",
    "GBPINR": "GBPINR=X",
    "JPYINR": "JPYINR=X",
    "DXY": "DX-Y.NYB",  # Dollar Index
}


async def run_forex_pipeline(session: AsyncSession, initial: bool = False) -> str:
    import yfinance as yf

    run_id = str(uuid.uuid4())
    started = datetime.now(UTC)
    run = PipelineRunRow(id=run_id, pipeline="forex", status="running", records_added=0, started_at=started)
    session.add(run)
    await session.flush()

    total_added = 0
    try:
        start_date = date.today() - timedelta(days=365 * 10) if initial else date.today() - timedelta(days=7)

        for pair, ticker in FOREX_TICKERS.items():
            log.info(f"  Fetching {pair} ({ticker})...")
            try:
                df = yf.download(ticker, start=str(start_date), progress=False, auto_adjust=True)
            except Exception as e:
                log.warning(f"  Error fetching {pair}: {e}")
                continue

            if df.empty:
                continue

            result = await session.execute(
                select(func.max(ForexRateRow.date)).where(ForexRateRow.pair == pair)
            )
            last_date = result.scalar()

            added = 0
            close_col = df["Close"].squeeze() if "Close" in df.columns else df.iloc[:, 0]
            for idx in close_col.index:
                d = idx.date() if hasattr(idx, "date") else idx
                if last_date and d <= last_date:
                    continue
                rate = float(close_col.loc[idx])
                if rate is not None and rate == rate:
                    session.add(ForexRateRow(pair=pair, date=d, rate=round(rate, 4)))
                    added += 1

            total_added += added
            log.info(f"  {pair}: +{added} records")
            await session.flush()
            time.sleep(1)

        run.status = "completed"
        run.records_added = total_added
        run.completed_at = datetime.now(UTC)
        log.info(f"Forex pipeline complete: {total_added} records")

    except Exception as e:
        log.error(f"Forex pipeline failed: {e}")
        run.status = "failed"
        run.error = str(e)[:2000]
        run.completed_at = datetime.now(UTC)

    await session.flush()
    return run_id
