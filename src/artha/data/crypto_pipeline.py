"""Crypto price pipeline — BTC, ETH, SOL via yfinance (reliable, no auth needed)."""

from __future__ import annotations

import logging
import time
import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select, String, Date, Float, BigInteger
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from artha.common.db.base import Base
from artha.data.models import PipelineRunRow

log = logging.getLogger(__name__)


class CryptoPriceRow(Base):
    __tablename__ = "crypto_prices"
    coin_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    price_usd: Mapped[float] = mapped_column(Float, nullable=False)
    price_inr: Mapped[float | None] = mapped_column(Float, nullable=True)
    market_cap_usd: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


CRYPTO_TICKERS = {
    "bitcoin": "BTC-USD",
    "ethereum": "ETH-USD",
    "solana": "SOL-USD",
    "ripple": "XRP-USD",
    "cardano": "ADA-USD",
}


async def run_crypto_pipeline(session: AsyncSession, initial: bool = False) -> str:
    import yfinance as yf

    run_id = str(uuid.uuid4())
    started = datetime.now(UTC)
    run = PipelineRunRow(id=run_id, pipeline="crypto", status="running", records_added=0, started_at=started)
    session.add(run)
    await session.flush()

    total_added = 0
    try:
        start_date = date.today() - timedelta(days=365 * 5) if initial else date.today() - timedelta(days=7)

        for coin, ticker in CRYPTO_TICKERS.items():
            log.info(f"  Fetching {coin} ({ticker})...")
            try:
                df = yf.download(ticker, start=str(start_date), progress=False, auto_adjust=True)
            except Exception as e:
                log.warning(f"  Error fetching {coin}: {e}")
                continue

            if df.empty:
                continue

            result = await session.execute(
                select(func.max(CryptoPriceRow.date)).where(CryptoPriceRow.coin_id == coin)
            )
            last_date = result.scalar()

            added = 0
            close_col = df["Close"].squeeze() if "Close" in df.columns else df.iloc[:, 0]
            for idx in close_col.index:
                d = idx.date() if hasattr(idx, "date") else idx
                if last_date and d <= last_date:
                    continue
                price = float(close_col.loc[idx])
                if price is not None and price == price:
                    session.add(CryptoPriceRow(coin_id=coin, date=d, price_usd=round(price, 2)))
                    added += 1

            total_added += added
            log.info(f"  {coin}: +{added} records")
            await session.flush()
            time.sleep(1)

        run.status = "completed"
        run.records_added = total_added
        run.completed_at = datetime.now(UTC)
        log.info(f"Crypto pipeline complete: {total_added} records")

    except Exception as e:
        log.error(f"Crypto pipeline failed: {e}")
        run.status = "failed"
        run.error = str(e)[:2000]
        run.completed_at = datetime.now(UTC)

    await session.flush()
    return run_id
