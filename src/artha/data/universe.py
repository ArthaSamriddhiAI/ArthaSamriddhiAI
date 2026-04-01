"""Universe management — Nifty 500 stocks and mutual fund scheme lists."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from artha.data.models import MFUniverseRow, StockUniverseRow

log = logging.getLogger(__name__)


async def refresh_nifty500(session: AsyncSession) -> int:
    """Fetch current Nifty 500 constituents and upsert into stock_universe."""
    from niftystocks import ns

    symbols_ns = ns.get_nifty500_with_ns()  # ["RELIANCE.NS", "TCS.NS", ...]
    now = datetime.now(UTC)
    added = 0

    for ticker_ns in symbols_ns:
        symbol = ticker_ns.replace(".NS", "")
        existing = await session.execute(
            select(StockUniverseRow).where(StockUniverseRow.symbol == symbol)
        )
        if existing.scalar_one_or_none() is None:
            session.add(StockUniverseRow(
                symbol=symbol, nse_ticker=ticker_ns, added_at=now, active=True
            ))
            added += 1

    await session.flush()
    total = (await session.execute(
        select(StockUniverseRow).where(StockUniverseRow.active == True)
    )).scalars().all()
    log.info(f"Nifty 500 universe: {len(total)} active symbols ({added} new)")
    return added


async def get_active_stocks(session: AsyncSession) -> list[StockUniverseRow]:
    result = await session.execute(
        select(StockUniverseRow).where(StockUniverseRow.active == True)
    )
    return list(result.scalars().all())


# ── Top 50 Mutual Fund Schemes (popular Indian MFs) ──
TOP_MF_SCHEMES: dict[str, str] = {
    # Large Cap
    "100356": "Mirae Asset Large Cap Fund - Growth",
    "112324": "Axis Bluechip Fund - Growth",
    "119598": "SBI Blue Chip Fund - Growth",
    "100526": "ICICI Prudential Bluechip Fund - Growth",
    "101852": "HDFC Top 100 Fund - Growth",
    # Flexi Cap / Multi Cap
    "122639": "Parag Parikh Flexi Cap Fund - Growth",
    "100474": "HDFC Flexi Cap Fund - Growth",
    "106235": "UTI Flexi Cap Fund - Growth",
    "119775": "SBI Flexicap Fund - Growth",
    "102885": "Kotak Flexicap Fund - Growth",
    # Mid Cap
    "100473": "HDFC Mid-Cap Opportunities Fund - Growth",
    "101539": "Kotak Emerging Equity Fund - Growth",
    "105506": "DSP Midcap Fund - Growth",
    "119816": "Axis Midcap Fund - Growth",
    "125497": "SBI Magnum Midcap Fund - Growth",
    # Small Cap
    "120503": "SBI Small Cap Fund - Growth",
    "118989": "Nippon India Small Cap Fund - Growth",
    "112321": "Axis Small Cap Fund - Growth",
    "104877": "HDFC Small Cap Fund - Growth",
    "125354": "Kotak Small Cap Fund - Growth",
    # Index Funds
    "120716": "UTI Nifty 50 Index Fund - Growth",
    "100476": "HDFC Index Fund - Nifty 50 Plan - Growth",
    "109469": "ICICI Prudential Nifty 50 Index Fund - Growth",
    "140574": "Motilal Oswal Nifty 500 Index Fund - Growth",
    "149364": "Navi Nifty 50 Index Fund - Growth",
    # ELSS (Tax Saving)
    "100173": "Axis Long Term Equity Fund - Growth",
    "100516": "ICICI Prudential Long Term Equity Fund - Growth",
    "119814": "SBI Long Term Equity Fund - Growth",
    "106236": "DSP Tax Saver Fund - Growth",
    "102067": "Kotak Tax Saver Fund - Growth",
    # Balanced / Hybrid
    "100475": "HDFC Balanced Advantage Fund - Growth",
    "100507": "ICICI Prudential Balanced Advantage Fund - Growth",
    "119568": "SBI Balanced Advantage Fund - Growth",
    "106254": "DSP Dynamic Asset Allocation Fund - Growth",
    "128834": "Edelweiss Balanced Advantage Fund - Growth",
    # Debt Funds
    "100471": "HDFC Short Term Debt Fund - Growth",
    "100520": "ICICI Prudential Short Term Fund - Growth",
    "119818": "SBI Short Term Debt Fund - Growth",
    "100468": "HDFC Corporate Bond Fund - Growth",
    "100518": "ICICI Prudential Corporate Bond Fund - Growth",
    # Focused / Thematic
    "112304": "Axis Focused 25 Fund - Growth",
    "120387": "Mirae Asset Tax Saver Fund - Growth",
    "100525": "ICICI Prudential Technology Fund - Growth",
    "100174": "SBI Healthcare Opportunities Fund - Growth",
    "119505": "Nippon India Pharma Fund - Growth",
    # International
    "118639": "Motilal Oswal Nasdaq 100 FoF - Growth",
    "101859": "HDFC Developed World Indexes FoF - Growth",
    "100523": "ICICI Prudential US Bluechip Equity Fund - Growth",
    "141425": "Axis Global Innovation FoF - Growth",
    "143470": "DSP Global Innovation FoF - Growth",
}


async def seed_mf_schemes(session: AsyncSession) -> int:
    """Seed the top 50 mutual fund schemes."""
    now = datetime.now(UTC)
    added = 0

    for code, name in TOP_MF_SCHEMES.items():
        existing = await session.execute(
            select(MFUniverseRow).where(MFUniverseRow.scheme_code == code)
        )
        if existing.scalar_one_or_none() is None:
            session.add(MFUniverseRow(
                scheme_code=code, scheme_name=name, added_at=now, active=True
            ))
            added += 1

    await session.flush()
    log.info(f"MF universe: {len(TOP_MF_SCHEMES)} schemes ({added} new)")
    return added


async def get_active_mf_schemes(session: AsyncSession) -> list[MFUniverseRow]:
    result = await session.execute(
        select(MFUniverseRow).where(MFUniverseRow.active == True)
    )
    return list(result.scalars().all())
