"""Crypto price pipeline — BTC, ETH, SOL via CoinGecko free API."""

from __future__ import annotations

import logging
import time
import uuid
from datetime import UTC, date, datetime, timedelta

import httpx
from sqlalchemy import func, select, String, Date, Float, BigInteger
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from artha.common.db.base import Base
from artha.data.models import PipelineRunRow

log = logging.getLogger(__name__)

COINGECKO_BASE = "https://api.coingecko.com/api/v3"

class CryptoPriceRow(Base):
    __tablename__ = "crypto_prices"
    coin_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    price_usd: Mapped[float] = mapped_column(Float, nullable=False)
    price_inr: Mapped[float | None] = mapped_column(Float, nullable=True)
    market_cap_usd: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


COINS = ["bitcoin", "ethereum", "solana", "ripple", "cardano"]


async def run_crypto_pipeline(session: AsyncSession, initial: bool = False) -> str:
    run_id = str(uuid.uuid4())
    started = datetime.now(UTC)
    run = PipelineRunRow(id=run_id, pipeline="crypto", status="running", records_added=0, started_at=started)
    session.add(run)
    await session.flush()

    total_added = 0
    try:
        days = 365 * 5 if initial else 30  # CoinGecko free: max ~365 days per call, 5yr via daily
        # Use market_chart/range for longer history
        async with httpx.AsyncClient(timeout=30.0) as client:
            for coin in COINS:
                log.info(f"  Fetching {coin}...")

                # Get latest existing date
                result = await session.execute(
                    select(func.max(CryptoPriceRow.date)).where(CryptoPriceRow.coin_id == coin)
                )
                last_date = result.scalar()

                if initial:
                    from_ts = int((datetime.now(UTC) - timedelta(days=days)).timestamp())
                elif last_date:
                    from_ts = int(datetime.combine(last_date + timedelta(days=1), datetime.min.time()).replace(tzinfo=UTC).timestamp())
                else:
                    from_ts = int((datetime.now(UTC) - timedelta(days=365)).timestamp())

                to_ts = int(datetime.now(UTC).timestamp())

                try:
                    resp = await client.get(
                        f"{COINGECKO_BASE}/coins/{coin}/market_chart/range",
                        params={"vs_currency": "usd", "from": from_ts, "to": to_ts}
                    )
                    resp.raise_for_status()
                    data = resp.json()
                except Exception as e:
                    log.warning(f"  CoinGecko error for {coin}: {e}")
                    time.sleep(2)
                    continue

                prices = data.get("prices", [])
                market_caps = data.get("market_caps", [])

                # Build market cap lookup by date
                mc_by_date = {}
                for mc in market_caps:
                    d = date.fromtimestamp(mc[0] / 1000)
                    mc_by_date[d] = int(mc[1]) if mc[1] else None

                added = 0
                seen_dates = set()
                for point in prices:
                    d = date.fromtimestamp(point[0] / 1000)
                    if d in seen_dates:
                        continue
                    seen_dates.add(d)
                    if last_date and d <= last_date:
                        continue
                    price = point[1]
                    if price is not None:
                        session.add(CryptoPriceRow(
                            coin_id=coin, date=d, price_usd=round(price, 4),
                            market_cap_usd=mc_by_date.get(d)
                        ))
                        added += 1

                total_added += added
                log.info(f"  {coin}: +{added} records")
                await session.flush()
                time.sleep(6)  # CoinGecko free: 10-30 calls/min

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
