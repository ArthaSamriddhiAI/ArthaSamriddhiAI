"""Condense batch results for the synthesis (S1) stage.

Full verdicts are preserved separately for telemetry but NOT passed to S1.
Only the minimal per-holding summary is forwarded.
"""

from __future__ import annotations

from typing import Any


def condense_for_synthesis(batch_results: list[dict]) -> list[dict]:
    """Extract per-holding condensed summaries from batch results.

    Parameters
    ----------
    batch_results : list[dict]
        Output of ``execute_batches``.

    Returns
    -------
    list of condensed dicts, one per holding:
        {holding_id, risk_level, top_2_drivers, flags}
    """
    # Deduplicate by holding_id — if a holding was sent to multiple agents
    # (e.g. unlisted_equity → financial_risk AND unlisted_equity),
    # take the highest risk level.
    holding_summaries: dict[str, dict] = {}

    _risk_order = {"low": 0, "medium": 1, "high": 2, "critical": 3}

    for batch in batch_results:
        results = batch.get("results", [])
        for result in results:
            holding_id = result.get("holding_id")
            if not holding_id:
                continue

            output = result.get("output", {})
            risk_level = output.get("risk_level", "medium")
            drivers = output.get("drivers", [])
            flags = output.get("flags", [])

            existing = holding_summaries.get(holding_id)
            if existing is None:
                holding_summaries[holding_id] = {
                    "holding_id": holding_id,
                    "risk_level": risk_level,
                    "top_2_drivers": drivers[:2],
                    "flags": flags,
                }
            else:
                # Merge: keep highest risk level, accumulate drivers/flags
                existing_rank = _risk_order.get(existing["risk_level"], 1)
                new_rank = _risk_order.get(risk_level, 1)
                if new_rank > existing_rank:
                    existing["risk_level"] = risk_level

                # Keep best 2 drivers across agents
                all_drivers = existing["top_2_drivers"] + drivers
                # Deduplicate while preserving order
                seen: set[str] = set()
                unique_drivers: list[str] = []
                for d in all_drivers:
                    if d not in seen:
                        seen.add(d)
                        unique_drivers.append(d)
                existing["top_2_drivers"] = unique_drivers[:2]

                # Accumulate unique flags
                existing_flags = set(existing["flags"])
                for f in flags:
                    if f not in existing_flags:
                        existing["flags"].append(f)
                        existing_flags.add(f)

    return list(holding_summaries.values())
