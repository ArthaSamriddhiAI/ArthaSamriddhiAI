"""Build an advisor-facing preview of the ingested portfolio before analysis."""

from __future__ import annotations

from artha.portfolio_analysis.ingestion.schema_validator import CanonicalPortfolio


def build_preview(portfolio: CanonicalPortfolio) -> dict:
    """Return a summary dict for the advisor to review before triggering analysis.

    Includes: total_aum, holdings_count, asset_class_breakdown, data_gaps_count,
    and a holdings table (first 50 rows with key fields).
    """
    holdings_table: list[dict] = []
    for h in portfolio.holdings[:50]:
        holdings_table.append({
            "holding_id": h.holding_id,
            "instrument_name": h.instrument_name,
            "asset_class": h.asset_class.value if hasattr(h.asset_class, "value") else h.asset_class,
            "current_value_inr": h.current_value_inr,
            "weight_pct": h.weight_pct,
            "holding_period_days": h.holding_period_days,
            "ltcg_eligible": h.ltcg_eligible,
            "data_gaps": h.data_gaps,
        })

    asset_class_breakdown = [
        {
            "asset_class": ab.asset_class,
            "total_value_inr": ab.total_value_inr,
            "weight_pct": ab.weight_pct,
            "holdings_count": ab.holdings_count,
        }
        for ab in portfolio.asset_class_breakdown
    ]

    dq = portfolio.data_quality_summary

    return {
        "total_aum": portfolio.total_value_inr,
        "holdings_count": len(portfolio.holdings),
        "asset_class_breakdown": asset_class_breakdown,
        "data_gaps_count": dq.total_data_gaps,
        "data_quality": {
            "total_holdings": dq.total_holdings,
            "holdings_with_gaps": dq.holdings_with_gaps,
            "source": dq.source,
            "note": dq.note,
        },
        "holdings_table": holdings_table,
        "truncated": len(portfolio.holdings) > 50,
    }
