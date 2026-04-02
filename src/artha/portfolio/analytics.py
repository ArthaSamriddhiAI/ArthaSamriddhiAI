"""Portfolio performance analytics — returns, benchmark comparison, attribution."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from artha.portfolio.schemas import ASSET_CLASS_LABELS


PERIODS = {
    "1M": 30, "3M": 90, "6M": 180, "1Y": 365, "3Y": 1095, "5Y": 1825, "SI": 0,
}

# Target allocations by risk category
TARGET_ALLOCATIONS: dict[str, dict[str, float]] = {
    "conservative": {"equity": 15, "mutual_fund": 25, "fd": 30, "bond": 10, "gold": 10, "insurance": 5, "ppf": 5},
    "moderately_conservative": {"equity": 20, "mutual_fund": 25, "fd": 25, "bond": 10, "gold": 10, "insurance": 5, "ppf": 5},
    "moderate": {"equity": 35, "mutual_fund": 25, "fd": 15, "bond": 5, "gold": 10, "pms": 5, "insurance": 3, "other": 2},
    "moderately_aggressive": {"equity": 45, "mutual_fund": 20, "fd": 10, "bond": 5, "gold": 5, "pms": 5, "aif": 5, "crypto": 3, "other": 2},
    "aggressive": {"equity": 55, "mutual_fund": 20, "fd": 5, "gold": 5, "pms": 5, "aif": 5, "crypto": 3, "other": 2},
}


async def compute_performance(
    session: AsyncSession,
    holdings: list[dict],
    total_invested: float,
    current_value: float,
) -> dict[str, Any]:
    """Compute portfolio returns for multiple periods."""
    today = date.today()
    overall_return = ((current_value - total_invested) / total_invested * 100) if total_invested > 0 else 0

    # Compute period returns using simple approximation
    # For each period, estimate portfolio value at period_start
    period_returns = {}
    for period_name, days in PERIODS.items():
        if period_name == "SI":
            period_returns[period_name] = round(overall_return, 2)
            continue

        period_start = today - timedelta(days=days)
        period_value = await _estimate_portfolio_value_at_date(session, holdings, period_start)

        if period_value and period_value > 0:
            ret = (current_value - period_value) / period_value * 100
            period_returns[period_name] = round(ret, 2)
        else:
            period_returns[period_name] = None

    # Benchmark (Nifty 50) returns
    benchmark_returns = await _compute_benchmark_returns(session, today)

    # Top/bottom performers
    sorted_by_return = sorted(holdings, key=lambda h: h.get("gain_loss_pct", 0))
    bottom_5 = sorted_by_return[:5]
    top_5 = sorted_by_return[-5:][::-1]

    # Attribution by asset class
    attribution = _compute_attribution(holdings, current_value)

    return {
        "period_returns": period_returns,
        "benchmark_returns": benchmark_returns,
        "alpha": {
            k: round(period_returns.get(k, 0) - benchmark_returns.get(k, 0), 2)
            for k in period_returns if period_returns.get(k) is not None and benchmark_returns.get(k) is not None
        },
        "top_performers": [{"symbol": h["symbol_or_id"], "description": h["description"], "return_pct": h.get("gain_loss_pct", 0)} for h in top_5],
        "bottom_performers": [{"symbol": h["symbol_or_id"], "description": h["description"], "return_pct": h.get("gain_loss_pct", 0)} for h in bottom_5],
        "attribution": attribution,
    }


async def _estimate_portfolio_value_at_date(
    session: AsyncSession, holdings: list[dict], target_date: date
) -> float | None:
    """Estimate portfolio value at a historical date using available price data."""
    total = 0.0
    has_data = False

    for h in holdings:
        ac = h.get("asset_class", "")
        symbol = h.get("symbol_or_id", "")
        qty = h.get("quantity", 0)
        acq_date_str = str(h.get("acquisition_date", ""))

        # Only count holdings that existed at target_date
        try:
            acq_parts = acq_date_str.split("-")
            acq_d = date(int(acq_parts[0]), int(acq_parts[1]), int(acq_parts[2]))
            if acq_d > target_date:
                continue  # Holding didn't exist yet
        except (ValueError, IndexError):
            continue

        price = None
        if ac == "equity":
            try:
                r = await session.execute(text(
                    "SELECT adj_close FROM stock_prices WHERE symbol = :s AND date <= :d ORDER BY date DESC LIMIT 1"
                ), {"s": symbol, "d": str(target_date)})
                row = r.one_or_none()
                if row:
                    price = row[0]
                    has_data = True
            except Exception:
                pass
        elif ac == "mutual_fund":
            try:
                r = await session.execute(text(
                    "SELECT nav FROM mf_navs WHERE scheme_code = :s AND date <= :d ORDER BY date DESC LIMIT 1"
                ), {"s": symbol, "d": str(target_date)})
                row = r.one_or_none()
                if row:
                    price = row[0]
                    has_data = True
            except Exception:
                pass

        if price:
            total += qty * price
        else:
            # Use acquisition price as fallback
            total += qty * h.get("acquisition_price", 0)

    return total if has_data else None


async def _compute_benchmark_returns(session: AsyncSession, today: date) -> dict[str, float]:
    """Compute Nifty 50 returns for standard periods."""
    returns = {}

    # Try to get Nifty 50 latest price
    try:
        r = await session.execute(text(
            "SELECT adj_close FROM stock_prices WHERE symbol = 'NIFTY50' ORDER BY date DESC LIMIT 1"
        ))
        latest_row = r.one_or_none()
        if not latest_row:
            return returns
        latest = latest_row[0]
    except Exception:
        return returns

    for period_name, days in PERIODS.items():
        if period_name == "SI" or days == 0:
            continue
        target = today - timedelta(days=days)
        try:
            r = await session.execute(text(
                "SELECT adj_close FROM stock_prices WHERE symbol = 'NIFTY50' AND date <= :d ORDER BY date DESC LIMIT 1"
            ), {"d": str(target)})
            row = r.one_or_none()
            if row and row[0] > 0:
                ret = (latest - row[0]) / row[0] * 100
                returns[period_name] = round(ret, 2)
        except Exception:
            pass

    return returns


def _compute_attribution(holdings: list[dict], total_value: float) -> list[dict]:
    """Compute return attribution by asset class."""
    from collections import defaultdict
    ac_data = defaultdict(lambda: {"gain": 0.0, "value": 0.0, "cost": 0.0})

    for h in holdings:
        ac = h.get("asset_class", "other")
        ac_data[ac]["gain"] += h.get("gain_loss", 0) or 0
        ac_data[ac]["value"] += h.get("current_value", 0) or 0
        ac_data[ac]["cost"] += h.get("cost_value", 0) or 0

    result = []
    for ac, data in sorted(ac_data.items(), key=lambda x: -abs(x[1]["gain"])):
        contribution = (data["gain"] / total_value * 100) if total_value > 0 else 0
        result.append({
            "asset_class": ac,
            "label": ASSET_CLASS_LABELS.get(ac, ac),
            "gain_loss": round(data["gain"], 0),
            "weight_pct": round(data["value"] / total_value * 100, 1) if total_value > 0 else 0,
            "contribution_pct": round(contribution, 2),
        })

    return result


async def check_drift(
    session: AsyncSession,
    allocation: list[dict],
    risk_category: str,
) -> dict[str, Any]:
    """Compare actual allocation vs target for the risk category."""
    target = TARGET_ALLOCATIONS.get(risk_category, TARGET_ALLOCATIONS["moderate"])

    # Build actual allocation map
    actual = {}
    for a in allocation:
        actual[a["asset_class"]] = a["percentage"]

    # Compute drift
    drift_items = []
    max_drift = 0.0
    total_drift = 0.0

    all_classes = set(list(target.keys()) + list(actual.keys()))
    for ac in sorted(all_classes):
        t = target.get(ac, 0)
        a = actual.get(ac, 0)
        drift = a - t
        abs_drift = abs(drift)
        max_drift = max(max_drift, abs_drift)
        total_drift += abs_drift
        drift_items.append({
            "asset_class": ac,
            "label": ASSET_CLASS_LABELS.get(ac, ac),
            "target_pct": round(t, 1),
            "actual_pct": round(a, 1),
            "drift_pct": round(drift, 1),
            "abs_drift": round(abs_drift, 1),
            "status": "overweight" if drift > 2 else ("underweight" if drift < -2 else "on_target"),
        })

    drift_items.sort(key=lambda x: -x["abs_drift"])
    needs_rebalance = max_drift > 5.0

    return {
        "risk_category": risk_category,
        "max_drift_pct": round(max_drift, 1),
        "total_drift_pct": round(total_drift, 1),
        "needs_rebalance": needs_rebalance,
        "drift_items": drift_items,
        "suggestions": _generate_suggestions(drift_items) if needs_rebalance else [],
    }


def _generate_suggestions(drift_items: list[dict]) -> list[str]:
    """Generate rebalance suggestions from drift data."""
    suggestions = []
    for item in drift_items:
        if item["drift_pct"] > 5:
            suggestions.append(f"Reduce {item['label']} by ~{item['drift_pct']:.0f}% (currently {item['actual_pct']:.0f}%, target {item['target_pct']:.0f}%)")
        elif item["drift_pct"] < -5:
            suggestions.append(f"Increase {item['label']} by ~{abs(item['drift_pct']):.0f}% (currently {item['actual_pct']:.0f}%, target {item['target_pct']:.0f}%)")
    return suggestions
