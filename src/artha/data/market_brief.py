"""AI Market Brief — daily personalized market summary for wealth managers."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class MarketBrief(BaseModel):
    summary: str = ""
    key_moves: list[str] = Field(default_factory=list)
    sector_highlights: list[str] = Field(default_factory=list)
    client_impact: list[str] = Field(default_factory=list)
    outlook: str = ""
    data_date: str = ""
    generated_at: str = ""


async def gather_market_data(session: AsyncSession) -> dict[str, Any]:
    """Gather latest market data for brief generation."""
    data = {}

    # Macro indicators
    try:
        r = await session.execute(text("""
            SELECT m.indicator, m.value, m.date FROM macro_indicators m
            INNER JOIN (SELECT indicator, MAX(date) as md FROM macro_indicators GROUP BY indicator) mx
            ON m.indicator = mx.indicator AND m.date = mx.md
        """))
        data["macro"] = {row[0]: {"value": row[1], "date": str(row[2])} for row in r.all()}
    except Exception:
        data["macro"] = {}

    # Forex
    try:
        r = await session.execute(text("""
            SELECT f.pair, f.rate, f.date FROM forex_rates f
            INNER JOIN (SELECT pair, MAX(date) as md FROM forex_rates GROUP BY pair) mx
            ON f.pair = mx.pair AND f.date = mx.md
        """))
        data["forex"] = {row[0]: {"rate": row[1], "date": str(row[2])} for row in r.all()}
    except Exception:
        data["forex"] = {}

    # Commodities from cache
    try:
        r = await session.execute(text("SELECT commodity, price_usd, date FROM latest_commodity_prices"))
        data["commodities"] = {row[0]: {"price": row[1], "date": str(row[2])} for row in r.all()}
    except Exception:
        data["commodities"] = {}

    # Crypto from cache
    try:
        r = await session.execute(text("SELECT coin_id, price_usd, date FROM latest_crypto_prices"))
        data["crypto"] = {row[0]: {"price": row[1], "date": str(row[2])} for row in r.all()}
    except Exception:
        data["crypto"] = {}

    # Top stock gainers/losers (compare latest 2 dates)
    try:
        r = await session.execute(text("""
            SELECT s1.symbol, s1.adj_close as latest, s2.adj_close as prev,
                   ROUND((s1.adj_close - s2.adj_close) / s2.adj_close * 100, 2) as chg_pct
            FROM latest_stock_prices s1
            INNER JOIN stock_prices s2 ON s1.symbol = s2.symbol
            WHERE s2.date = (SELECT MAX(date) FROM stock_prices WHERE date < s1.date AND symbol = s1.symbol)
            AND s2.adj_close > 0
            ORDER BY chg_pct DESC LIMIT 5
        """))
        data["top_gainers"] = [{"symbol": r[0], "price": r[1], "prev": r[2], "change_pct": r[3]} for r in r.all()]
    except Exception:
        data["top_gainers"] = []

    try:
        r = await session.execute(text("""
            SELECT s1.symbol, s1.adj_close as latest, s2.adj_close as prev,
                   ROUND((s1.adj_close - s2.adj_close) / s2.adj_close * 100, 2) as chg_pct
            FROM latest_stock_prices s1
            INNER JOIN stock_prices s2 ON s1.symbol = s2.symbol
            WHERE s2.date = (SELECT MAX(date) FROM stock_prices WHERE date < s1.date AND symbol = s1.symbol)
            AND s2.adj_close > 0
            ORDER BY chg_pct ASC LIMIT 5
        """))
        data["top_losers"] = [{"symbol": r[0], "price": r[1], "prev": r[2], "change_pct": r[3]} for r in r.all()]
    except Exception:
        data["top_losers"] = []

    # Portfolio stats
    try:
        r = await session.execute(text("SELECT COUNT(DISTINCT investor_id), COUNT(*) FROM portfolio_holdings WHERE active=1"))
        row = r.one()
        data["portfolio_stats"] = {"clients": row[0], "holdings": row[1]}
    except Exception:
        data["portfolio_stats"] = {}

    return data


async def generate_market_brief(session: AsyncSession) -> MarketBrief:
    """Generate AI-powered market brief using Mistral with real data."""
    import json
    from datetime import UTC, datetime

    market_data = await gather_market_data(session)

    # Build detailed context from ACTUAL data only
    lines = ["ACTUAL MARKET DATA (use ONLY these numbers, do NOT invent any data):"]

    macro = market_data.get("macro", {})
    for key in ["INDIA_VIX", "US_10Y_YIELD", "GOLD_USD", "CRUDE_BRENT", "USDINR", "DXY"]:
        if key in macro:
            lines.append(f"  {key}: {macro[key]['value']:.2f} (as of {macro[key]['date']})")

    forex = market_data.get("forex", {})
    for pair in ["USDINR", "EURINR", "GBPINR"]:
        if pair in forex:
            lines.append(f"  {pair}: {forex[pair]['rate']:.4f} (as of {forex[pair]['date']})")

    commod = market_data.get("commodities", {})
    for c in ["GOLD", "SILVER", "CRUDE_WTI", "CRUDE_BRENT", "COPPER", "NATGAS"]:
        if c in commod:
            lines.append(f"  {c}: ${commod[c]['price']:.2f} (as of {commod[c]['date']})")

    crypto = market_data.get("crypto", {})
    for coin in ["bitcoin", "ethereum", "solana"]:
        if coin in crypto:
            lines.append(f"  {coin.title()}: ${crypto[coin]['price']:,.2f} (as of {crypto[coin]['date']})")

    gainers = market_data.get("top_gainers", [])
    if gainers:
        lines.append("  TOP GAINERS (1-day):")
        for g in gainers[:5]:
            lines.append(f"    {g['symbol']}: Rs {g['price']:.2f} ({g['change_pct']:+.2f}%)")

    losers = market_data.get("top_losers", [])
    if losers:
        lines.append("  TOP LOSERS (1-day):")
        for l in losers[:5]:
            lines.append(f"    {l['symbol']}: Rs {l['price']:.2f} ({l['change_pct']:+.2f}%)")

    ps = market_data.get("portfolio_stats", {})
    if ps:
        lines.append(f"  PORTFOLIO: {ps.get('clients', 0)} clients, {ps.get('holdings', 0)} holdings under management")

    data_context = "\n".join(lines)

    # Determine data date
    dates = []
    for section in [macro, forex, commod, crypto]:
        for v in section.values():
            if isinstance(v, dict) and "date" in v:
                dates.append(v["date"])
    data_date = max(dates) if dates else "unknown"

    try:
        from artha.llm.registry import get_provider
        from artha.llm.models import LLMMessage, LLMRequest

        llm = get_provider()
        request = LLMRequest(
            messages=[
                LLMMessage(role="system", content=(
                    "You are a senior wealth management market analyst at an Indian HNI advisory firm. "
                    "Generate a daily market brief for the advisory team. STRICT RULES:\n"
                    "1. Use ONLY the numbers provided below. Do NOT invent or hallucinate any data points.\n"
                    "2. If you don't have a specific data point (like Nifty closing), say 'data not available' or skip it.\n"
                    "3. Focus on: what the provided data MEANS for HNI portfolios.\n"
                    "4. Be concise (150-200 words). Professional but accessible tone.\n"
                    "5. End with 1-2 actionable observations for the advisory team.\n"
                    "6. Reference specific numbers from the data provided."
                )),
                LLMMessage(role="user", content=f"{data_context}\n\nGenerate today's market brief based ONLY on the above data."),
            ],
            temperature=0.3,
            max_tokens=600,
        )

        result = await llm.complete_structured(request, MarketBrief)
        result.generated_at = datetime.now(UTC).isoformat()
        result.data_date = data_date
        return result

    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Market brief AI generation failed: {e}")
        # Try simple complete (non-structured) as fallback
        try:
            resp = await llm.complete(request)
            return MarketBrief(
                summary=resp.content[:500],
                key_moves=[],
                outlook="",
                data_date=data_date,
                generated_at=datetime.now(UTC).isoformat(),
            )
        except Exception:
            pass
        return MarketBrief(
            summary=f"Market data as of {data_date}. " + " | ".join(lines[1:7]),
            key_moves=[l.strip() for l in lines[1:7] if l.strip().startswith((" ", "  "))],
            outlook="AI-generated analysis unavailable. Review raw data above.",
            data_date=data_date,
            generated_at=datetime.now(UTC).isoformat(),
        )
