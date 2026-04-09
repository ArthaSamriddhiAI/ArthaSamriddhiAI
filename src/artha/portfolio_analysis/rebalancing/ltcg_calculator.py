"""Long-term capital gains tax calculator using rules/ltcg-rates-v1.0.yaml."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

_DEFAULT_RATES_PATH = Path("rules/ltcg-rates-v1.0.yaml")


def load_ltcg_rates(path: Path | None = None) -> dict:
    """Load LTCG rate schedule from YAML.

    Returns the ``rates`` dict keyed by asset class.
    """
    p = path or _DEFAULT_RATES_PATH
    with open(p, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("rates", {})


def _resolve_rate_entry(asset_class: str, rates: dict) -> dict:
    """Resolve the rate entry for an asset class, following ``default_rate`` pointers."""
    entry = rates.get(asset_class, {})
    # PMS has a ``default_rate`` pointer to listed_equity
    if "default_rate" in entry and "short_term_threshold_days" not in entry:
        target = entry["default_rate"]
        entry = rates.get(target, entry)
    return entry


def calculate_ltcg(holding: dict, rates: dict) -> dict:
    """Calculate LTCG tax impact for a single holding.

    Parameters
    ----------
    holding : dict
        A holding dict from the canonical portfolio.
    rates : dict
        The ``rates`` section from ltcg-rates-v1.0.yaml.

    Returns
    -------
    dict with keys: tax_rate, is_ltcg_eligible, estimated_tax_amount, net_proceeds
    """
    asset_class = holding.get("asset_class", "cash")
    holding_period_days = holding.get("holding_period_days")
    current_value = holding.get("current_value_inr", 0.0)
    cost_basis = holding.get("cost_basis")

    # Cash has no tax
    if asset_class == "cash":
        return {
            "tax_rate": 0.0,
            "is_ltcg_eligible": False,
            "estimated_tax_amount": 0.0,
            "net_proceeds": current_value,
        }

    # Map PAM asset classes to LTCG rate keys
    rate_key_map: dict[str, str] = {
        "listed_equity": "listed_equity",
        "mutual_fund": "mutual_fund_equity",  # default to equity MF
        "pms": "pms",
        "aif_cat1": "aif_cat1",
        "aif_cat2": "aif_cat2",
        "aif_cat3": "aif_cat3",
        "unlisted_equity": "unlisted_equity",
    }
    rate_key = rate_key_map.get(asset_class, "listed_equity")
    rate_entry = _resolve_rate_entry(rate_key, rates)

    threshold = rate_entry.get("short_term_threshold_days", 365)
    is_ltcg = False
    if holding_period_days is not None:
        is_ltcg = holding_period_days >= threshold

    if is_ltcg:
        raw_rate = rate_entry.get("long_term_rate", 0.125)
    else:
        raw_rate = rate_entry.get("short_term_rate", 0.20)

    # Handle slab_rate — use 30% as conservative estimate
    if isinstance(raw_rate, str) and raw_rate == "slab_rate":
        tax_rate = 0.30
    else:
        tax_rate = float(raw_rate)

    # Compute estimated tax
    if cost_basis is not None and cost_basis > 0:
        gain = max(current_value - cost_basis, 0.0)
    else:
        # Without cost basis, assume full value is gain (conservative)
        gain = current_value

    # Apply LTCG exemption if applicable
    exemption = rate_entry.get("long_term_exemption_inr", 0)
    if is_ltcg and exemption > 0:
        gain = max(gain - exemption, 0.0)

    estimated_tax = gain * tax_rate
    net_proceeds = current_value - estimated_tax

    return {
        "tax_rate": tax_rate,
        "is_ltcg_eligible": is_ltcg,
        "estimated_tax_amount": round(estimated_tax, 2),
        "net_proceeds": round(net_proceeds, 2),
    }
