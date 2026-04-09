"""Calculate net exit proceeds for HIGH/CRITICAL risk holdings."""

from __future__ import annotations

from artha.portfolio_analysis.rebalancing.ltcg_calculator import (
    calculate_ltcg,
    load_ltcg_rates,
)


def calculate_exit_proceeds(
    holdings: list[dict],
    batch_results: list[dict],
    ltcg_rates: dict | None = None,
) -> dict:
    """Identify HIGH/CRITICAL holdings and calculate net exit proceeds.

    Parameters
    ----------
    holdings : list[dict]
        Full list of holding dicts from canonical portfolio.
    batch_results : list[dict]
        Output of ``execute_batches`` — used to determine per-holding risk level.
    ltcg_rates : dict | None
        LTCG rates dict. Loaded from YAML if not provided.

    Returns
    -------
    dict with keys:
        exit_candidates (list[dict]) — one per HIGH/CRITICAL holding
        total_redeployable_inr (float) — sum of net proceeds
    """
    if ltcg_rates is None:
        ltcg_rates = load_ltcg_rates()

    # Build holding_id -> risk_level map from batch results
    risk_map: dict[str, str] = {}
    for batch in batch_results:
        for result in batch.get("results", []):
            hid = result.get("holding_id")
            if hid:
                output = result.get("output", {})
                rl = output.get("risk_level", "medium")
                # Keep worst risk level if multiple entries
                existing = risk_map.get(hid)
                if existing is None or _risk_rank(rl) > _risk_rank(existing):
                    risk_map[hid] = rl

    # Build holding_id -> holding dict lookup
    holding_map: dict[str, dict] = {}
    for h in holdings:
        hid = h.get("holding_id")
        if hid:
            holding_map[hid] = h

    exit_candidates: list[dict] = []
    total_redeployable = 0.0

    for hid, risk_level in risk_map.items():
        if risk_level not in ("high", "critical"):
            continue

        holding = holding_map.get(hid)
        if holding is None:
            continue

        # Skip cash
        if holding.get("asset_class") == "cash":
            continue

        # Calculate LTCG
        ltcg = calculate_ltcg(holding, ltcg_rates)

        candidate = {
            "holding_id": hid,
            "instrument_name": holding.get("instrument_name", "Unknown"),
            "isin_or_cin": holding.get("isin_or_cin"),
            "asset_class": holding.get("asset_class"),
            "current_value_inr": holding.get("current_value_inr", 0.0),
            "cost_basis": holding.get("cost_basis"),
            "risk_level": risk_level,
            "holding_period_days": holding.get("holding_period_days"),
            "tax_rate": ltcg["tax_rate"],
            "is_ltcg_eligible": ltcg["is_ltcg_eligible"],
            "estimated_tax_amount": ltcg["estimated_tax_amount"],
            "net_proceeds": ltcg["net_proceeds"],
        }
        exit_candidates.append(candidate)
        total_redeployable += ltcg["net_proceeds"]

    # Sort by net proceeds descending
    exit_candidates.sort(key=lambda c: c["net_proceeds"], reverse=True)

    return {
        "exit_candidates": exit_candidates,
        "total_redeployable_inr": round(total_redeployable, 2),
    }


def _risk_rank(level: str) -> int:
    return {"low": 0, "medium": 1, "high": 2, "critical": 3}.get(level, 1)
