"""Yahoo Finance data adapter — reads from the stock_prices table populated by the data pipeline."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from artha.data.models import StockPriceRow


class YahooFinanceSource:
    """Reads recent stock prices from the pipeline-populated stock_prices table."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @property
    def source_name(self) -> str:
        return "yahoo"

    async def fetch(self, symbols: list[str]) -> dict[str, Any]:
        """Fetch latest prices for given symbols from the local database."""
        prices: dict[str, Any] = {}

        for symbol in symbols:
            # Get latest price
            stmt = (
                select(StockPriceRow)
                .where(StockPriceRow.symbol == symbol)
                .order_by(StockPriceRow.date.desc())
                .limit(1)
            )
            result = await self._session.execute(stmt)
            latest = result.scalar_one_or_none()

            if latest is None:
                continue

            # Get 52-week high/low
            one_year_ago = date.today() - timedelta(days=365)
            stmt_hl = select(
                func.max(StockPriceRow.adj_close),
                func.min(StockPriceRow.adj_close),
            ).where(
                StockPriceRow.symbol == symbol,
                StockPriceRow.date >= one_year_ago,
            )
            hl_result = await self._session.execute(stmt_hl)
            high_low = hl_result.one_or_none()

            # Get previous day for change calculation
            stmt_prev = (
                select(StockPriceRow.adj_close)
                .where(StockPriceRow.symbol == symbol, StockPriceRow.date < latest.date)
                .order_by(StockPriceRow.date.desc())
                .limit(1)
            )
            prev_result = await self._session.execute(stmt_prev)
            prev_row = prev_result.scalar_one_or_none()

            prev_close = prev_row if prev_row else latest.adj_close
            change_pct = (latest.adj_close - prev_close) / prev_close if prev_close else 0

            prices[symbol] = {
                "price": round(latest.adj_close, 2),
                "change_pct": round(change_pct, 6),
                "volume": latest.volume or 0,
                "high_52w": round(high_low[0], 2) if high_low and high_low[0] else latest.adj_close,
                "low_52w": round(high_low[1], 2) if high_low and high_low[1] else latest.adj_close,
                "date": str(latest.date),
            }

        return prices
