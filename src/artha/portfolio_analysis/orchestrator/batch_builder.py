"""Split classified holding groups into capped batches for parallel execution."""

from __future__ import annotations

import math

# Maximum holdings per batch, per agent type
_BATCH_CAPS: dict[str, int] = {
    "financial_risk": 8,
    "unlisted_equity": 4,
    "pms_aif": 4,
}

_DEFAULT_CAP = 4


def build_batches(classified: dict[str, list[dict]]) -> list[dict]:
    """Split classified groups into batches respecting per-agent caps.

    Parameters
    ----------
    classified : dict[str, list[dict]]
        Output of ``classify_holdings`` — agent_id -> holdings list.

    Returns
    -------
    list of batch dicts, each with keys:
        agent_id (str), batch_index (int), holdings (list[dict])
    """
    batches: list[dict] = []

    for agent_id, holdings in classified.items():
        if agent_id == "cash":
            # Cash holdings don't go to any agent — skip batching
            continue

        cap = _BATCH_CAPS.get(agent_id, _DEFAULT_CAP)
        num_batches = math.ceil(len(holdings) / cap) if holdings else 0

        for batch_idx in range(num_batches):
            start = batch_idx * cap
            end = start + cap
            batch_holdings = holdings[start:end]

            batches.append({
                "agent_id": agent_id,
                "batch_index": batch_idx,
                "holdings": batch_holdings,
            })

    return batches
