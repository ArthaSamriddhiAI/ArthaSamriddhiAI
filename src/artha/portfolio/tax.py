"""Tax Harvesting Intelligence — STCG/LTCG classification and harvesting suggestions."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

# Indian tax rules (FY 2025-26)
EQUITY_STCG_THRESHOLD_DAYS = 365  # Listed equity/equity MF: < 1 year = STCG
DEBT_STCG_THRESHOLD_DAYS = 1095  # Debt/Gold/Others: < 3 years = STCG (old rule, simplified)
LTCG_EQUITY_RATE = 12.5  # LTCG on equity above Rs 1.25L exemption
STCG_EQUITY_RATE = 20.0  # STCG on equity
LTCG_DEBT_RATE = 20.0  # LTCG on debt (indexation benefit removed)
STCG_DEBT_SLAB_RATE = 30.0  # STCG on debt taxed at slab (assume 30%)
LTCG_EXEMPTION = 125000  # Annual LTCG exemption for equity


def compute_tax_summary(holdings: list[dict]) -> dict[str, Any]:
    """Classify holdings and compute tax exposure."""
    today = date.today()

    stcg_equity = 0.0
    ltcg_equity = 0.0
    stcg_other = 0.0
    ltcg_other = 0.0
    stcg_holdings = []
    ltcg_holdings = []

    for h in holdings:
        ac = h.get("asset_class", "other")
        gain = h.get("gain_loss", 0) or 0
        acq_str = str(h.get("acquisition_date", ""))

        try:
            parts = acq_str.split("-")
            acq_date = date(int(parts[0]), int(parts[1]), int(parts[2]))
        except (ValueError, IndexError):
            continue

        holding_days = (today - acq_date).days
        is_equity_like = ac in ("equity", "mutual_fund")  # Simplified: all MFs as equity

        if is_equity_like:
            threshold = EQUITY_STCG_THRESHOLD_DAYS
        else:
            threshold = DEBT_STCG_THRESHOLD_DAYS

        is_short_term = holding_days < threshold
        tax_type = "STCG" if is_short_term else "LTCG"

        if is_equity_like:
            rate = STCG_EQUITY_RATE if is_short_term else LTCG_EQUITY_RATE
        else:
            rate = STCG_DEBT_SLAB_RATE if is_short_term else LTCG_DEBT_RATE

        estimated_tax = max(0, gain * rate / 100) if gain > 0 else 0

        entry = {
            "symbol": h.get("symbol_or_id", ""),
            "description": h.get("description", ""),
            "asset_class": ac,
            "acquisition_date": acq_str,
            "holding_days": holding_days,
            "tax_type": tax_type,
            "unrealized_gain": round(gain, 0),
            "tax_rate": rate,
            "estimated_tax": round(estimated_tax, 0),
            "current_value": round(h.get("current_value", 0) or 0, 0),
        }

        if is_short_term:
            if is_equity_like:
                stcg_equity += gain
            else:
                stcg_other += gain
            stcg_holdings.append(entry)
        else:
            if is_equity_like:
                ltcg_equity += gain
            else:
                ltcg_other += gain
            ltcg_holdings.append(entry)

    # Compute tax after exemption
    ltcg_equity_taxable = max(0, ltcg_equity - LTCG_EXEMPTION)

    total_stcg_tax = max(0, stcg_equity * STCG_EQUITY_RATE / 100) + max(0, stcg_other * STCG_DEBT_SLAB_RATE / 100)
    total_ltcg_tax = max(0, ltcg_equity_taxable * LTCG_EQUITY_RATE / 100) + max(0, ltcg_other * LTCG_DEBT_RATE / 100)

    # Harvesting suggestions
    harvesting = _suggest_harvesting(stcg_holdings + ltcg_holdings)

    return {
        "stcg_equity": round(stcg_equity, 0),
        "stcg_other": round(stcg_other, 0),
        "ltcg_equity": round(ltcg_equity, 0),
        "ltcg_equity_taxable": round(ltcg_equity_taxable, 0),
        "ltcg_other": round(ltcg_other, 0),
        "ltcg_exemption_used": round(min(ltcg_equity, LTCG_EXEMPTION), 0),
        "total_stcg_tax": round(total_stcg_tax, 0),
        "total_ltcg_tax": round(total_ltcg_tax, 0),
        "total_estimated_tax": round(total_stcg_tax + total_ltcg_tax, 0),
        "stcg_holdings": sorted(stcg_holdings, key=lambda x: x["unrealized_gain"]),
        "ltcg_holdings": sorted(ltcg_holdings, key=lambda x: x["unrealized_gain"]),
        "harvesting_suggestions": harvesting,
    }


def _suggest_harvesting(all_holdings: list[dict]) -> list[dict]:
    """Find loss-making positions that can offset gains."""
    losers = [h for h in all_holdings if h["unrealized_gain"] < 0]
    gainers = [h for h in all_holdings if h["unrealized_gain"] > 0]

    if not losers or not gainers:
        return []

    losers.sort(key=lambda x: x["unrealized_gain"])  # Biggest loss first
    gainers.sort(key=lambda x: -x["unrealized_gain"])  # Biggest gain first

    suggestions = []
    for loser in losers[:5]:
        loss = abs(loser["unrealized_gain"])
        tax_saved = loss * loser["tax_rate"] / 100
        if tax_saved > 1000:  # Only suggest if saving > Rs 1000
            matched_gainer = gainers[0] if gainers else None
            suggestions.append({
                "action": f"Sell {loser['description']}",
                "loss_amount": round(loss, 0),
                "offset_against": matched_gainer["description"] if matched_gainer else "Overall gains",
                "estimated_tax_saving": round(tax_saved, 0),
                "tax_type": loser["tax_type"],
            })

    return suggestions
