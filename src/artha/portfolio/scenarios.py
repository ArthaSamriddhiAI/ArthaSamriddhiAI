"""What-If Scenario Analysis — stress testing portfolios against predefined scenarios."""

from __future__ import annotations

from typing import Any

SCENARIOS = {
    "nifty_crash_20": {"name": "Market Crash (Nifty -20%)", "shocks": {"equity": -20, "mutual_fund": -15, "pms": -18, "aif": -10, "crypto": -30}},
    "nifty_rally_30": {"name": "Bull Rally (Nifty +30%)", "shocks": {"equity": 30, "mutual_fund": 22, "pms": 25, "aif": 15, "crypto": 40}},
    "gold_surge_50": {"name": "Gold Surge (+50%)", "shocks": {"gold": 50, "silver": 45}},
    "rate_hike_100bps": {"name": "Rate Hike (+100bps)", "shocks": {"fd": 0, "bond": -5, "mutual_fund": -3, "equity": -8}},
    "rupee_depreciation_10": {"name": "INR Depreciation (-10%)", "shocks": {"equity": -5, "mutual_fund": -4, "crypto": 10, "gold": 8}},
    "covid_replay": {"name": "COVID-like Crash", "shocks": {"equity": -35, "mutual_fund": -25, "pms": -30, "aif": -20, "real_estate": -10, "crypto": -50, "gold": 15}},
    "stagflation": {"name": "Stagflation Scenario", "shocks": {"equity": -15, "mutual_fund": -10, "fd": 0, "bond": -8, "gold": 25, "real_estate": -5, "crypto": -20}},
}


def run_scenario(holdings: list[dict], scenario_id: str, current_value: float) -> dict[str, Any]:
    """Apply scenario shocks to portfolio and compute impact."""
    scenario = SCENARIOS.get(scenario_id)
    if not scenario:
        return {"error": f"Unknown scenario: {scenario_id}"}

    shocks = scenario["shocks"]
    impacted_holdings = []
    total_pre = current_value
    total_post = 0.0
    total_impact = 0.0

    for h in holdings:
        ac = h.get("asset_class", "other")
        shock_pct = shocks.get(ac, 0)
        cv = h.get("current_value", 0) or 0
        impact = cv * shock_pct / 100
        post_value = cv + impact

        impacted_holdings.append({
            "symbol": h.get("symbol_or_id", ""),
            "description": h.get("description", ""),
            "asset_class": ac,
            "pre_value": round(cv, 0),
            "shock_pct": shock_pct,
            "impact": round(impact, 0),
            "post_value": round(post_value, 0),
        })
        total_post += post_value
        total_impact += impact

    impacted_holdings.sort(key=lambda x: x["impact"])

    return {
        "scenario_id": scenario_id,
        "scenario_name": scenario["name"],
        "pre_value": round(total_pre, 0),
        "post_value": round(total_post, 0),
        "total_impact": round(total_impact, 0),
        "impact_pct": round(total_impact / total_pre * 100, 2) if total_pre > 0 else 0,
        "holdings_impact": impacted_holdings,
        "available_scenarios": list(SCENARIOS.keys()),
    }


def list_scenarios() -> list[dict]:
    return [{"id": k, "name": v["name"]} for k, v in SCENARIOS.items()]
