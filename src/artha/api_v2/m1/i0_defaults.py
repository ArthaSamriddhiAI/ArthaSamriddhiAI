"""I0-driven mandate defaults — FR Entry 12.1 §2.4 + §4.4.

Pure-function mapping from an :class:`Investor`'s I0 enrichment fields
(life_stage, liquidity_tier, risk_appetite) to the suggested constraint
values for a fresh mandate. Used by:

- The form-path API (chunk 2.1) to pre-populate the create form via the
  ``GET /api/v2/investors/{id}/mandate/defaults`` shape.
- The C0 conversational path (chunk 2.2) when the slot extractor
  recognises a "use defaults" request.
- The amendment-divergence detector (chunk 2.3 / FR 12.0 §4.3) when
  re-enrichment recomputes what the suggested defaults *would* be.

Cluster 1's I0 already produces ``life_stage`` + ``liquidity_tier`` on
every Investor (see :mod:`artha.api_v2.i0.active_layer`). M1 reads those
plus the advisor-entered ``risk_appetite`` to derive defaults.
"""

from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Suggested-default lookup tables (FR 12.1 §2.4 + §4.4)
# ---------------------------------------------------------------------------


#: Asset-allocation bands keyed by ``risk_appetite``. Values are
#: ``(equity_min, equity_max, debt_min, debt_max, alts_min, alts_max)``.
_RISK_TO_ASSET_BANDS: dict[str, tuple[int, int, int, int, int, int]] = {
    "aggressive":   (70, 90,  5, 25, 5, 15),
    "moderate":     (50, 70, 20, 40, 5, 15),
    "conservative": (30, 50, 40, 60, 5, 15),
}

#: Liquidity-floor pct keyed by I0 ``liquidity_tier``.
_TIER_TO_LIQUIDITY_FLOOR: dict[str, int] = {
    "essential": 10,
    "secondary": 20,
    "deep":      30,
}

#: Industry-standard defaults that don't derive from I0.
_DEFAULT_SINGLE_POSITION_MAX_PCT = 5
_DEFAULT_SECTOR_MAX_PCT = 25


@dataclass(frozen=True)
class MandateDefaults:
    """Cluster 2 mandate-default bundle.

    Each field carries the suggested value; ``sources`` is a parallel dict
    that names the I0 field each default came from (``"i0_liquidity_tier"``,
    ``"i0_risk_appetite"``, or ``"industry_standard"``). The frontend
    renders the source as the small "I0 source label" alongside each input
    (per chunk plan 2.1 §scope_in).
    """

    # Asset allocation
    equity_min_pct: int
    equity_max_pct: int
    debt_min_pct: int
    debt_max_pct: int
    alternatives_min_pct: int
    alternatives_max_pct: int

    # Concentration
    single_position_max_pct: int

    # Liquidity
    liquidity_floor_pct: int

    # Sector
    sector_max_pct: int

    # Prohibited list (always empty on first run)
    prohibited_instruments: tuple[str, ...]

    # Per-field provenance for the UI labels
    sources: dict[str, str]


def compute_defaults(
    *, risk_appetite: str | None, liquidity_tier: str | None
) -> MandateDefaults:
    """Build the default bundle for a freshly-enriched investor.

    Falls back to the moderate / secondary buckets when the inputs are
    ``None`` (the I0 active layer always produces values for the cluster
    1 schema, but defending against missing data keeps M1 robust against
    seed-data regressions).
    """
    risk_key = (risk_appetite or "moderate").lower()
    bands = _RISK_TO_ASSET_BANDS.get(risk_key, _RISK_TO_ASSET_BANDS["moderate"])
    tier_key = (liquidity_tier or "secondary").lower()
    liquidity_floor = _TIER_TO_LIQUIDITY_FLOOR.get(
        tier_key, _TIER_TO_LIQUIDITY_FLOOR["secondary"]
    )
    return MandateDefaults(
        equity_min_pct=bands[0],
        equity_max_pct=bands[1],
        debt_min_pct=bands[2],
        debt_max_pct=bands[3],
        alternatives_min_pct=bands[4],
        alternatives_max_pct=bands[5],
        single_position_max_pct=_DEFAULT_SINGLE_POSITION_MAX_PCT,
        liquidity_floor_pct=liquidity_floor,
        sector_max_pct=_DEFAULT_SECTOR_MAX_PCT,
        prohibited_instruments=(),
        sources={
            "equity_min_pct": "i0_risk_appetite",
            "equity_max_pct": "i0_risk_appetite",
            "debt_min_pct": "i0_risk_appetite",
            "debt_max_pct": "i0_risk_appetite",
            "alternatives_min_pct": "i0_risk_appetite",
            "alternatives_max_pct": "i0_risk_appetite",
            "single_position_max_pct": "industry_standard",
            "liquidity_floor_pct": "i0_liquidity_tier",
            "sector_max_pct": "industry_standard",
            "prohibited_instruments": "industry_standard",
        },
    )
