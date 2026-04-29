"""§5.13 Test 7 — L4 substitution cascade.

When the construction pipeline removes Fund A and adds Fund B to a cell,
PM1 (and downstream advisor cases) need the cascade: which clients hold
Fund A today, and what's the recommended substitution.

`compute_substitution_impacts` is deterministic — it walks the client
slice list and folds in a `L4SubstitutionImpact` for every removal that
hits at least one client.
"""

from __future__ import annotations

from artha.canonical.construction import (
    ClientPortfolioSlice,
    L4SubstitutionImpact,
)


def compute_substitution_impacts(
    *,
    client_slices: list[ClientPortfolioSlice],
    removed_instrument_ids: list[str],
    replacement_map: dict[str, str],
) -> list[L4SubstitutionImpact]:
    """Return one impact per removed instrument that has affected clients.

    `replacement_map` maps removed_id → replacement_id. Removed instruments
    not in the map fall back to a sentinel `"unmapped"` replacement so
    consumers can flag them for advisor review.
    """
    impacts: list[L4SubstitutionImpact] = []
    for removed_id in removed_instrument_ids:
        affected: list[str] = []
        total_aum = 0.0
        for slice_ in client_slices:
            holding_value = float(
                slice_.holdings_by_instrument_id.get(removed_id, 0.0)
            )
            if holding_value > 0:
                affected.append(slice_.client_id)
                total_aum += holding_value
        if not affected:
            continue
        impacts.append(
            L4SubstitutionImpact(
                removed_instrument_id=removed_id,
                replacement_instrument_id=replacement_map.get(removed_id, "unmapped"),
                affected_client_ids=sorted(affected),
                total_aum_affected_inr=total_aum,
            )
        )
    return impacts


__all__ = ["compute_substitution_impacts"]
