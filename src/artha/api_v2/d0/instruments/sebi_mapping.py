"""SEBI mutual-fund category → ``(asset_class, vehicle_type)`` map.

Source: SEBI Circular SEBI/HO/IMD/DF3/CIR/P/2017/114 (October 2017) and
subsequent updates establishing the standardised mutual-fund scheme
categorisation. The Indian mutual-fund universe partitions into:

- 11 equity categories
- 16 debt categories
- 7 hybrid categories
- 2 solution-oriented categories
- index funds + ETFs + FoFs (other)

For the four-band cluster-3 asset allocation (equity / debt / cash /
alternatives), every SEBI category maps to exactly one asset class. The
mapping reflects how Indian wealth managers conventionally bucket each
category for portfolio construction:

- Liquid / Overnight / Ultra Short / Money Market → cash. These are the
  cash-management vehicles in practice; they sit in the cash band, not
  the debt band.
- Arbitrage → cash. Arbitrage funds carry equity-vehicle wrapping but
  market-neutral risk; advisors use them as cash equivalents with tax
  efficiency.
- Multi-Asset Allocation → alternatives. Includes commodity exposure
  (gold) by mandate, doesn't fit cleanly into equity/debt/cash.
- Hybrid funds use the dominant asset by SEBI's definition: aggressive
  hybrid (65-80% equity) → equity; conservative hybrid (10-25% equity)
  → debt; balanced hybrid (40-60% equity) → equity for portfolio bucket
  purposes (the cluster-3 working answer; advisors can override per
  mandate context).
- Gold / Silver ETFs → alternatives. Equity ETFs of these are
  alternatives by Indian-MF convention.

The map is the source of truth: any instrument the JSONFixtureAdapter
loads with a ``sebi_category`` field gets its ``asset_class`` from this
map (so a feed that mislabels asset_class is auto-corrected). Categories
not in the map raise :class:`UnknownSebiCategoryError`, which the adapter
treats as a classification-uncertain edge and emits
``instrument_classification_uncertain``.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

#: Cluster-3 four-band asset class vocabulary.
ASSET_CLASSES: tuple[str, ...] = ("equity", "debt", "cash", "alternatives")

#: Vehicle types the catalogue currently recognises. Cluster 3 ships
#: ``mutual_fund``, ``etf``, ``stock``, ``bond``. Future clusters may add
#: ``fixed_deposit``, ``ulip``, ``aif``, etc.
VEHICLE_TYPES: tuple[str, ...] = (
    "mutual_fund",
    "etf",
    "stock",
    "bond",
)


# ---------------------------------------------------------------------------
# SEBI category map
# ---------------------------------------------------------------------------


SEBI_CATEGORY_MAP: dict[str, tuple[str, str]] = {
    # ---- Equity (11) ----
    "multi_cap": ("equity", "mutual_fund"),
    "flexi_cap": ("equity", "mutual_fund"),
    "large_cap": ("equity", "mutual_fund"),
    "large_and_mid_cap": ("equity", "mutual_fund"),
    "mid_cap": ("equity", "mutual_fund"),
    "small_cap": ("equity", "mutual_fund"),
    "dividend_yield": ("equity", "mutual_fund"),
    "value": ("equity", "mutual_fund"),
    "contra": ("equity", "mutual_fund"),
    "focused": ("equity", "mutual_fund"),
    "sectoral_thematic": ("equity", "mutual_fund"),
    "elss": ("equity", "mutual_fund"),

    # ---- Debt (16) ----
    "overnight": ("cash", "mutual_fund"),
    "liquid": ("cash", "mutual_fund"),
    "ultra_short_duration": ("cash", "mutual_fund"),
    "money_market": ("cash", "mutual_fund"),
    "low_duration": ("debt", "mutual_fund"),
    "short_duration": ("debt", "mutual_fund"),
    "medium_duration": ("debt", "mutual_fund"),
    "medium_to_long_duration": ("debt", "mutual_fund"),
    "long_duration": ("debt", "mutual_fund"),
    "dynamic_bond": ("debt", "mutual_fund"),
    "corporate_bond": ("debt", "mutual_fund"),
    "credit_risk": ("debt", "mutual_fund"),
    "banking_and_psu": ("debt", "mutual_fund"),
    "gilt": ("debt", "mutual_fund"),
    "gilt_10y_constant_duration": ("debt", "mutual_fund"),
    "floater": ("debt", "mutual_fund"),

    # ---- Hybrid (7) ----
    "conservative_hybrid": ("debt", "mutual_fund"),
    "balanced_hybrid": ("equity", "mutual_fund"),
    "aggressive_hybrid": ("equity", "mutual_fund"),
    "dynamic_asset_allocation": ("equity", "mutual_fund"),
    "multi_asset_allocation": ("alternatives", "mutual_fund"),
    "arbitrage": ("cash", "mutual_fund"),
    "equity_savings": ("equity", "mutual_fund"),

    # ---- Solution-oriented (2) ----
    "retirement_fund": ("equity", "mutual_fund"),
    "childrens_fund": ("equity", "mutual_fund"),

    # ---- Other (9) — Index, ETFs, FoFs, FMP, capital-protection ----
    "index_fund": ("equity", "mutual_fund"),
    "etf_equity": ("equity", "etf"),
    "etf_debt": ("debt", "etf"),
    "etf_gold": ("alternatives", "etf"),
    "etf_silver": ("alternatives", "etf"),
    "fof_domestic": ("equity", "mutual_fund"),
    "fof_overseas": ("equity", "mutual_fund"),
    "fixed_maturity_plan": ("debt", "mutual_fund"),
    "capital_protection_oriented": ("debt", "mutual_fund"),
}


#: Sanity check at import time — 46 entries (FR 10.7 cluster-3 revision):
#: 12 equity + 16 debt + 7 hybrid + 2 solution-oriented + 9 other.
assert len(SEBI_CATEGORY_MAP) == 46, (
    f"SEBI category map must hold exactly 46 entries; "
    f"found {len(SEBI_CATEGORY_MAP)}."
)


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------


class UnknownSebiCategoryError(ValueError):
    """Raised when a SEBI category isn't in :data:`SEBI_CATEGORY_MAP`."""


def classify(sebi_category: str) -> tuple[str, str]:
    """Return the ``(asset_class, vehicle_type)`` pair for a SEBI category.

    The lookup is case-insensitive and tolerates whitespace + hyphens by
    normalising both inputs to lowercase snake_case before matching.
    """
    normalised = _normalise(sebi_category)
    try:
        return SEBI_CATEGORY_MAP[normalised]
    except KeyError as exc:
        raise UnknownSebiCategoryError(
            f"Unknown SEBI category: {sebi_category!r}"
        ) from exc


def is_known(sebi_category: str) -> bool:
    """Cheap predicate — true if the category resolves cleanly."""
    return _normalise(sebi_category) in SEBI_CATEGORY_MAP


def all_categories() -> tuple[str, ...]:
    """Return every recognised SEBI category, sorted alphabetically.

    Used by the admin UI's filter dropdown and by tests that assert
    coverage.
    """
    return tuple(sorted(SEBI_CATEGORY_MAP.keys()))


def _normalise(value: str) -> str:
    """Lower-case + collapse hyphens/spaces to underscores."""
    return value.strip().lower().replace("-", "_").replace(" ", "_")
