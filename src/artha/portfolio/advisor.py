"""Multi-Client Advisor Dashboard — aggregate view across all clients."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from artha.portfolio.analytics import check_drift, TARGET_ALLOCATIONS
from artha.portfolio.service import PortfolioService


async def get_advisor_dashboard(session: AsyncSession) -> dict[str, Any]:
    """Aggregate portfolio data across ALL clients."""
    # Get all investors
    try:
        r = await session.execute(text("SELECT id, name, investor_type FROM investors ORDER BY name"))
        investors = [{"id": row[0], "name": row[1], "type": row[2]} for row in r.all()]
    except Exception:
        investors = []

    if not investors:
        return {"total_aum": 0, "client_count": 0, "clients": []}

    svc = PortfolioService(session)
    total_aum = 0.0
    total_invested = 0.0
    total_gain = 0.0
    clients = []
    risk_distribution = defaultdict(int)
    attention_needed = 0
    top_holdings = defaultdict(lambda: {"count": 0, "total_value": 0})

    for inv in investors:
        try:
            summary = await svc.get_portfolio_summary(inv["id"])
        except Exception:
            continue

        cv = summary.current_value or 0
        ti = summary.total_invested or 0
        gl = summary.total_gain_loss or 0
        gl_pct = summary.total_gain_loss_pct or 0
        hc = summary.holdings_count

        total_aum += cv
        total_invested += ti
        total_gain += gl

        # Get risk profile
        risk_cat = "unknown"
        try:
            rp = await session.execute(text(
                "SELECT risk_category FROM investor_risk_profiles WHERE investor_id = :id ORDER BY computed_at DESC LIMIT 1"
            ), {"id": inv["id"]})
            row = rp.one_or_none()
            if row:
                risk_cat = row[0]
        except Exception:
            pass

        risk_distribution[risk_cat] += 1

        # Check drift
        drift_status = "ok"
        max_drift = 0
        if summary.allocation and risk_cat != "unknown":
            drift = await check_drift(session, [a.model_dump() for a in summary.allocation], risk_cat)
            max_drift = drift.get("max_drift_pct", 0)
            if drift.get("needs_rebalance"):
                drift_status = "needs_rebalance"
                attention_needed += 1

        clients.append({
            "investor_id": inv["id"],
            "name": inv["name"],
            "type": inv["type"],
            "aum": round(cv, 0),
            "invested": round(ti, 0),
            "gain_loss": round(gl, 0),
            "gain_loss_pct": round(gl_pct, 1),
            "holdings_count": hc,
            "risk_category": risk_cat.replace("_", " ").title(),
            "drift_status": drift_status,
            "max_drift_pct": round(max_drift, 1),
        })

        # Track top holdings
        for h in summary.holdings:
            key = h.symbol_or_id
            top_holdings[key]["count"] += 1
            top_holdings[key]["total_value"] += h.current_value or 0
            top_holdings[key]["description"] = h.description

    clients.sort(key=lambda x: -x["aum"])

    top_10 = sorted(top_holdings.items(), key=lambda x: -x[1]["total_value"])[:10]

    return {
        "total_aum": round(total_aum, 0),
        "total_invested": round(total_invested, 0),
        "total_gain_loss": round(total_gain, 0),
        "total_gain_loss_pct": round(total_gain / total_invested * 100, 1) if total_invested > 0 else 0,
        "client_count": len(clients),
        "attention_needed": attention_needed,
        "risk_distribution": dict(risk_distribution),
        "clients": clients,
        "top_holdings": [
            {"symbol": k, "description": v["description"], "client_count": v["count"], "total_value": round(v["total_value"], 0)}
            for k, v in top_10
        ],
    }
