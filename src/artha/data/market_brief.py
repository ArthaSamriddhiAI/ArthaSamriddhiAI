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

    # Commodities
    try:
        r = await session.execute(text("""
            SELECT c.commodity, c.price_usd, c.date FROM commodity_prices c
            INNER JOIN (SELECT commodity, MAX(date) as md FROM commodity_prices GROUP BY commodity) mx
            ON c.commodity = mx.commodity AND c.date = mx.md
        """))
        data["commodities"] = {row[0]: {"price": row[1], "date": str(row[2])} for row in r.all()}
    except Exception:
        data["commodities"] = {}

    # Crypto
    try:
        r = await session.execute(text("""
            SELECT c.coin_id, c.price_usd, c.date FROM crypto_prices c
            INNER JOIN (SELECT coin_id, MAX(date) as md FROM crypto_prices GROUP BY coin_id) mx
            ON c.coin_id = mx.coin_id AND c.date = mx.md
        """))
        data["crypto"] = {row[0]: {"price": row[1], "date": str(row[2])} for row in r.all()}
    except Exception:
        data["crypto"] = {}

    return data


async def generate_market_brief(session: AsyncSession) -> MarketBrief:
    """Generate AI-powered market brief using Mistral."""
    import json
    from datetime import UTC, datetime

    market_data = await gather_market_data(session)

    # Build prompt context
    context_parts = []
    macro = market_data.get("macro", {})
    if "INDIA_VIX" in macro:
        context_parts.append(f"India VIX: {macro['INDIA_VIX']['value']:.2f}")
    if "GOLD_USD" in macro:
        context_parts.append(f"Gold: ${macro['GOLD_USD']['value']:.2f}/oz")
    if "CRUDE_BRENT" in macro:
        context_parts.append(f"Brent Crude: ${macro['CRUDE_BRENT']['value']:.2f}/bbl")

    forex = market_data.get("forex", {})
    if "USDINR" in forex:
        context_parts.append(f"USD/INR: {forex['USDINR']['rate']:.2f}")
    if "DXY" in forex:
        context_parts.append(f"Dollar Index: {forex['DXY']['rate']:.2f}")

    crypto = market_data.get("crypto", {})
    if "bitcoin" in crypto:
        context_parts.append(f"Bitcoin: ${crypto['bitcoin']['price']:,.0f}")

    context_str = " | ".join(context_parts)

    try:
        from artha.llm.registry import get_provider
        from artha.llm.models import LLMMessage, LLMRequest

        llm = get_provider()
        request = LLMRequest(
            messages=[
                LLMMessage(role="system", content=(
                    "You are a senior wealth management market analyst. Generate a concise daily market brief "
                    "(200 words max) for a wealth manager serving HNI clients in India. Include: "
                    "1) Key market moves 2) Commodity/currency highlights 3) What it means for client portfolios. "
                    "Be specific with numbers. Professional tone."
                )),
                LLMMessage(role="user", content=f"Latest market data:\n{context_str}\n\nGenerate today's market brief."),
            ],
            temperature=0.3,
            max_tokens=512,
        )

        result = await llm.complete_structured(request, MarketBrief)
        result.generated_at = datetime.now(UTC).isoformat()
        return result

    except Exception as e:
        # Fallback: generate basic brief without AI
        return MarketBrief(
            summary=f"Market snapshot: {context_str}",
            key_moves=context_parts[:4],
            outlook="Market data loaded. AI analysis unavailable.",
            generated_at=datetime.now(UTC).isoformat(),
        )
