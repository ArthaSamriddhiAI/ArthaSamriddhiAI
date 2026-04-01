"""Nifty 500 stock price pipeline — downloads adjusted close via yfinance."""

from __future__ import annotations

import logging
import time
import uuid
from datetime import UTC, date, datetime, timedelta

import yfinance as yf
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from artha.data.models import PipelineRunRow, StockPriceRow
from artha.data.universe import get_active_stocks

log = logging.getLogger(__name__)

CHUNK_SIZE = 50
CHUNK_DELAY_SEC = 2
BACKFILL_YEARS = 10


async def run_stock_pipeline(session: AsyncSession, initial: bool = False) -> str:
    """Download stock prices. Returns pipeline run ID."""
    run_id = str(uuid.uuid4())
    started = datetime.now(UTC)
    run = PipelineRunRow(
        id=run_id, pipeline="stocks", status="running",
        records_added=0, started_at=started,
    )
    session.add(run)
    await session.flush()

    total_added = 0
    try:
        stocks = await get_active_stocks(session)
        if not stocks:
            log.warning("No active stocks in universe. Run --refresh-universe first.")
            run.status = "completed"
            run.completed_at = datetime.now(UTC)
            await session.flush()
            return run_id

        log.info(f"Stock pipeline: {len(stocks)} symbols, initial={initial}")

        # Determine start date per symbol
        if initial:
            global_start = date.today() - timedelta(days=365 * BACKFILL_YEARS)
        else:
            global_start = date.today() - timedelta(days=7)  # fallback for new symbols

        # Get latest dates per symbol
        latest_dates: dict[str, date] = {}
        if not initial:
            result = await session.execute(
                select(StockPriceRow.symbol, func.max(StockPriceRow.date))
                .group_by(StockPriceRow.symbol)
            )
            latest_dates = {row[0]: row[1] for row in result.all()}

        # Build ticker list with start dates
        tickers_with_start: list[tuple[str, str, date]] = []
        for stock in stocks:
            if initial:
                start = global_start
            else:
                last = latest_dates.get(stock.symbol)
                start = (last + timedelta(days=1)) if last else global_start
            if start <= date.today():
                tickers_with_start.append((stock.symbol, stock.nse_ticker, start))

        if not tickers_with_start:
            log.info("All stocks up to date. No downloads needed.")
            run.status = "completed"
            run.completed_at = datetime.now(UTC)
            await session.flush()
            return run_id

        # Process in chunks
        chunks = [tickers_with_start[i:i + CHUNK_SIZE] for i in range(0, len(tickers_with_start), CHUNK_SIZE)]

        for chunk_idx, chunk in enumerate(chunks):
            nse_tickers = [t[1] for t in chunk]
            symbol_map = {t[1]: t[0] for t in chunk}
            earliest_start = min(t[2] for t in chunk)

            log.info(f"  Chunk {chunk_idx + 1}/{len(chunks)}: {len(nse_tickers)} tickers from {earliest_start}")

            try:
                df = yf.download(
                    tickers=nse_tickers,
                    start=str(earliest_start),
                    interval="1d",
                    auto_adjust=True,
                    progress=False,
                    threads=True,
                )
            except Exception as e:
                log.error(f"  yfinance download error: {e}")
                continue

            if df.empty:
                log.warning(f"  Empty result for chunk {chunk_idx + 1}")
                continue

            # Parse the dataframe
            chunk_added = 0
            if len(nse_tickers) == 1:
                # Single ticker: columns are Open, High, Low, Close, Volume
                ticker = nse_tickers[0]
                symbol = symbol_map[ticker]
                if "Close" in df.columns:
                    for idx, row in df.iterrows():
                        d = idx.date() if hasattr(idx, "date") else idx
                        price = row.get("Close")
                        vol = row.get("Volume")
                        if price is not None and price == price:  # NaN check
                            # Check if already exists
                            start_for_symbol = next(t[2] for t in chunk if t[0] == symbol)
                            if d >= start_for_symbol:
                                session.add(StockPriceRow(
                                    symbol=symbol, date=d,
                                    adj_close=float(price),
                                    volume=int(vol) if vol is not None and vol == vol else None,
                                ))
                                chunk_added += 1
            else:
                # Multi ticker: MultiIndex columns (metric, ticker)
                for ticker in nse_tickers:
                    symbol = symbol_map[ticker]
                    start_for_symbol = next(t[2] for t in chunk if t[0] == symbol)
                    try:
                        if ("Close", ticker) in df.columns:
                            col_close = df[("Close", ticker)]
                            col_vol = df[("Volume", ticker)] if ("Volume", ticker) in df.columns else None
                        elif "Close" in df.columns and ticker in df["Close"].columns:
                            col_close = df["Close"][ticker]
                            col_vol = df["Volume"][ticker] if "Volume" in df.columns and ticker in df["Volume"].columns else None
                        else:
                            continue

                        for idx in col_close.index:
                            d = idx.date() if hasattr(idx, "date") else idx
                            price = col_close.loc[idx]
                            if price is not None and price == price and d >= start_for_symbol:
                                vol_val = col_vol.loc[idx] if col_vol is not None else None
                                session.add(StockPriceRow(
                                    symbol=symbol, date=d,
                                    adj_close=float(price),
                                    volume=int(vol_val) if vol_val is not None and vol_val == vol_val else None,
                                ))
                                chunk_added += 1
                    except Exception as e:
                        log.warning(f"  Error parsing {ticker}: {e}")

            total_added += chunk_added
            log.info(f"  Chunk {chunk_idx + 1}: +{chunk_added} records")
            await session.flush()

            if chunk_idx < len(chunks) - 1:
                time.sleep(CHUNK_DELAY_SEC)

        run.status = "completed"
        run.records_added = total_added
        run.completed_at = datetime.now(UTC)
        log.info(f"Stock pipeline complete: {total_added} records added")

    except Exception as e:
        log.error(f"Stock pipeline failed: {e}")
        run.status = "failed"
        run.error = str(e)[:2000]
        run.completed_at = datetime.now(UTC)

    await session.flush()
    return run_id
