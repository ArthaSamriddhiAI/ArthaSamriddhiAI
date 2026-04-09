"""Pure deterministic routing — classify holdings by target analysis agent."""

from __future__ import annotations


# Mapping from asset_class to the agent(s) that should analyse it
_ROUTING_TABLE: dict[str, list[str]] = {
    "listed_equity": ["financial_risk"],
    "mutual_fund": ["financial_risk"],
    "pms": ["pms_aif"],
    "aif_cat1": ["pms_aif"],
    "aif_cat2": ["pms_aif"],
    "aif_cat3": ["pms_aif"],
    "unlisted_equity": ["unlisted_equity", "financial_risk"],  # dual routing
    "cash": ["cash"],  # no agent — passed directly to synthesis
}


def classify_holdings(holdings: list[dict]) -> dict[str, list[dict]]:
    """Group holdings by target analysis agent.

    Parameters
    ----------
    holdings : list[dict]
        List of holding dicts from the canonical portfolio.

    Returns
    -------
    dict mapping agent_id (str) to list of holding dicts.
    A holding with dual routing (e.g. unlisted_equity) appears in both groups.
    """
    classified: dict[str, list[dict]] = {}

    for holding in holdings:
        asset_class = holding.get("asset_class", "cash")
        if isinstance(asset_class, str):
            asset_class = asset_class.strip().lower()

        agents = _ROUTING_TABLE.get(asset_class, ["financial_risk"])

        for agent_id in agents:
            classified.setdefault(agent_id, []).append(holding)

    return classified
