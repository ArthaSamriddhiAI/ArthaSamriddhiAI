"""FastAPI endpoints for browsing pipeline data (stocks, MF, commodities, forex, macro, crypto)."""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from artha.common.db.session import get_session

router = APIRouter(prefix="/data", tags=["data-explorer"])


@router.get("/summary")
async def data_summary(session: AsyncSession = Depends(get_session)):
    """Get record counts and date ranges for all data tables."""
    tables = {
        "stock_prices": "SELECT COUNT(*), COUNT(DISTINCT symbol), MIN(date), MAX(date) FROM stock_prices",
        "mf_navs": "SELECT COUNT(*), COUNT(DISTINCT scheme_code), MIN(date), MAX(date) FROM mf_navs",
        "commodity_prices": "SELECT COUNT(*), COUNT(DISTINCT commodity), MIN(date), MAX(date) FROM commodity_prices",
        "forex_rates": "SELECT COUNT(*), COUNT(DISTINCT pair), MIN(date), MAX(date) FROM forex_rates",
        "macro_indicators": "SELECT COUNT(*), COUNT(DISTINCT indicator), MIN(date), MAX(date) FROM macro_indicators",
        "crypto_prices": "SELECT COUNT(*), COUNT(DISTINCT coin_id), MIN(date), MAX(date) FROM crypto_prices",
    }
    result = {}
    for table, sql in tables.items():
        try:
            r = (await session.execute(text(sql))).one()
            result[table] = {
                "records": r[0], "symbols": r[1],
                "from_date": str(r[2]) if r[2] else None,
                "to_date": str(r[3]) if r[3] else None,
            }
        except Exception:
            result[table] = {"records": 0, "symbols": 0, "from_date": None, "to_date": None}

    # Universes
    try:
        su = (await session.execute(text("SELECT COUNT(*) FROM stock_universe WHERE active=1"))).scalar()
        mu = (await session.execute(text("SELECT COUNT(*) FROM mf_universe WHERE active=1"))).scalar()
        result["stock_universe"] = su
        result["mf_universe"] = mu
    except Exception:
        pass

    return result


@router.get("/stocks")
async def get_stock_prices(
    symbol: str = Query(..., description="Stock symbol (e.g., RELIANCE)"),
    days: int = Query(30, description="Number of recent days"),
    session: AsyncSession = Depends(get_session),
):
    """Get recent stock prices for a symbol."""
    sql = text(
        "SELECT symbol, date, adj_close, volume FROM stock_prices "
        "WHERE symbol = :sym ORDER BY date DESC LIMIT :lim"
    )
    rows = (await session.execute(sql, {"sym": symbol, "lim": days})).all()
    return [{"symbol": r[0], "date": str(r[1]), "adj_close": r[2], "volume": r[3]} for r in rows]


@router.get("/stocks/latest")
async def get_latest_stock_prices(
    limit: int = Query(50, description="Number of stocks"),
    session: AsyncSession = Depends(get_session),
):
    """Get latest price for each stock (most recent date)."""
    sql = text("""
        SELECT s.symbol, s.date, s.adj_close, s.volume
        FROM stock_prices s
        INNER JOIN (SELECT symbol, MAX(date) as max_date FROM stock_prices GROUP BY symbol) m
        ON s.symbol = m.symbol AND s.date = m.max_date
        ORDER BY s.symbol LIMIT :lim
    """)
    rows = (await session.execute(sql, {"lim": limit})).all()
    return [{"symbol": r[0], "date": str(r[1]), "adj_close": round(r[2], 2), "volume": r[3]} for r in rows]


@router.get("/stocks/search")
async def search_stocks(
    q: str = Query("", description="Search by symbol prefix"),
    session: AsyncSession = Depends(get_session),
):
    """Search stock universe."""
    sql = text("SELECT symbol, nse_ticker FROM stock_universe WHERE active=1 AND symbol LIKE :q ORDER BY symbol LIMIT 20")
    rows = (await session.execute(sql, {"q": f"{q.upper()}%"})).all()
    return [{"symbol": r[0], "nse_ticker": r[1]} for r in rows]


@router.get("/mf/latest")
async def get_latest_mf_navs(
    limit: int = Query(50),
    session: AsyncSession = Depends(get_session),
):
    """Get latest NAV for each MF scheme."""
    sql = text("""
        SELECT u.scheme_code, u.scheme_name, n.date, n.nav
        FROM mf_universe u
        LEFT JOIN latest_mf_navs n ON u.scheme_code = n.scheme_code
        WHERE u.active = 1
        ORDER BY u.scheme_name
        LIMIT :lim
    """)
    rows = (await session.execute(sql, {"lim": limit})).all()
    return [{"scheme_code": r[0], "scheme_name": r[1], "date": str(r[2]) if r[2] else None, "nav": r[3]} for r in rows]


@router.get("/mf/search")
async def search_mf_schemes(
    q: str = Query("", description="Search by scheme name"),
    session: AsyncSession = Depends(get_session),
):
    """Search MF schemes."""
    sql = text("SELECT scheme_code, scheme_name FROM mf_universe WHERE active=1 AND scheme_name LIKE :q ORDER BY scheme_name LIMIT 20")
    rows = (await session.execute(sql, {"q": f"%{q}%"})).all()
    return [{"scheme_code": r[0], "scheme_name": r[1]} for r in rows]


@router.get("/mf/{scheme_code}")
async def get_mf_nav_history(
    scheme_code: str,
    days: int = Query(365),
    session: AsyncSession = Depends(get_session),
):
    """Get NAV history for a scheme."""
    sql = text("SELECT scheme_code, date, nav FROM mf_navs WHERE scheme_code = :code ORDER BY date DESC LIMIT :lim")
    rows = (await session.execute(sql, {"code": scheme_code, "lim": days})).all()
    return [{"scheme_code": r[0], "date": str(r[1]), "nav": r[2]} for r in rows]


@router.get("/commodities")
async def get_commodity_prices(
    commodity: str | None = None,
    days: int = Query(30),
    session: AsyncSession = Depends(get_session),
):
    """Get commodity prices."""
    if commodity:
        sql = text("SELECT commodity, date, price_usd, unit FROM commodity_prices WHERE commodity = :c ORDER BY date DESC LIMIT :lim")
        rows = (await session.execute(sql, {"c": commodity, "lim": days})).all()
    else:
        # Latest for each commodity
        sql = text("""
            SELECT c.commodity, c.date, c.price_usd, c.unit
            FROM commodity_prices c
            INNER JOIN (SELECT commodity, MAX(date) as md FROM commodity_prices GROUP BY commodity) m
            ON c.commodity = m.commodity AND c.date = m.md
        """)
        rows = (await session.execute(sql)).all()
    return [{"commodity": r[0], "date": str(r[1]), "price_usd": r[2], "unit": r[3]} for r in rows]


@router.get("/forex")
async def get_forex_rates(
    pair: str | None = None,
    days: int = Query(30),
    session: AsyncSession = Depends(get_session),
):
    """Get forex rates."""
    if pair:
        sql = text("SELECT pair, date, rate FROM forex_rates WHERE pair = :p ORDER BY date DESC LIMIT :lim")
        rows = (await session.execute(sql, {"p": pair, "lim": days})).all()
    else:
        sql = text("""
            SELECT f.pair, f.date, f.rate
            FROM forex_rates f
            INNER JOIN (SELECT pair, MAX(date) as md FROM forex_rates GROUP BY pair) m
            ON f.pair = m.pair AND f.date = m.md
        """)
        rows = (await session.execute(sql)).all()
    return [{"pair": r[0], "date": str(r[1]), "rate": r[2]} for r in rows]


@router.get("/macro")
async def get_macro_indicators(
    indicator: str | None = None,
    days: int = Query(30),
    session: AsyncSession = Depends(get_session),
):
    """Get macro indicators."""
    if indicator:
        sql = text("SELECT indicator, date, value, unit FROM macro_indicators WHERE indicator = :i ORDER BY date DESC LIMIT :lim")
        rows = (await session.execute(sql, {"i": indicator, "lim": days})).all()
    else:
        sql = text("""
            SELECT m.indicator, m.date, m.value, m.unit
            FROM macro_indicators m
            INNER JOIN (SELECT indicator, MAX(date) as md FROM macro_indicators GROUP BY indicator) mx
            ON m.indicator = mx.indicator AND m.date = mx.md
        """)
        rows = (await session.execute(sql)).all()
    return [{"indicator": r[0], "date": str(r[1]), "value": r[2], "unit": r[3]} for r in rows]


@router.get("/crypto")
async def get_crypto_prices(
    coin: str | None = None,
    days: int = Query(30),
    session: AsyncSession = Depends(get_session),
):
    """Get crypto prices."""
    if coin:
        sql = text("SELECT coin_id, date, price_usd FROM crypto_prices WHERE coin_id = :c ORDER BY date DESC LIMIT :lim")
        rows = (await session.execute(sql, {"c": coin, "lim": days})).all()
    else:
        sql = text("""
            SELECT c.coin_id, c.date, c.price_usd
            FROM crypto_prices c
            INNER JOIN (SELECT coin_id, MAX(date) as md FROM crypto_prices GROUP BY coin_id) m
            ON c.coin_id = m.coin_id AND c.date = m.md
        """)
        rows = (await session.execute(sql)).all()
    return [{"coin": r[0], "date": str(r[1]), "price_usd": r[2]} for r in rows]


@router.get("/market-brief")
async def get_market_brief(session: AsyncSession = Depends(get_session)):
    """AI-generated daily market brief."""
    from artha.data.market_brief import generate_market_brief
    return await generate_market_brief(session)
