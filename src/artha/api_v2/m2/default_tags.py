"""Default tag rules for the cluster 3 instrument universe (FR Entry 13.3 §2).

The chunk 4.1 default loader applies these rules at startup so a fresh
deployment ships with credibly-tagged instruments out of the box. Each
rule maps a (vehicle_type, sub_classifier) tuple to a set of cell
identifiers.

Sub-classifier varies by vehicle:

- ``mutual_fund`` / ``etf``: SEBI category (canonical key from
  :mod:`artha.api_v2.d0.instruments.sebi_mapping`)
- ``stock``: market-cap-rank bucket derived from Nifty 500 rank
- ``pms``: strategy type derived from fund name + manager heuristics
- ``aif``: SEBI AIF category ("CAT I" / "CAT II" / "CAT III long_short" /
  "CAT III long_only")
- ``unlisted_equity``: no sub-classifier; all map to
  aggressive_long_term

The rules below are encoded by sub_classifier — the loader picks the
right table based on the instrument's vehicle_type and computes the
sub_classifier on the fly. Unknown classifications fall through to an
empty tag set; the loader logs ``instrument_default_tagging_failed`` so
the CIO can address them via the chunk 4.2 admin UI.
"""

from __future__ import annotations

from typing import Iterable

from artha.api_v2.m2 import cells

# ---------------------------------------------------------------------------
# Tag-set helpers
# ---------------------------------------------------------------------------


_ALL_CELLS = frozenset(cells.ALL_CELLS)


def _all() -> frozenset[str]:
    """Universal cash-equivalent: tagged for every cell."""
    return _ALL_CELLS


def _by_risk(*risks: str) -> frozenset[str]:
    """All horizons for the given risk profiles."""
    out: set[str] = set()
    for risk in risks:
        for h in cells.HORIZONS:
            out.add(cells.cell_id(risk, h))
    return frozenset(out)


def _build(pairs: Iterable[tuple[str, str]]) -> frozenset[str]:
    """Build a tag set from explicit ``(risk, horizon)`` pairs."""
    return frozenset(cells.cell_id(r, h) for r, h in pairs)


# ---------------------------------------------------------------------------
# Mutual fund + ETF default tags by SEBI category
# ---------------------------------------------------------------------------
#
# Keys are the canonical SEBI keys from :mod:`sebi_mapping.SEBI_CATEGORY_MAP`.
# Coverage is per FR 13.3 §2.1 mapped to our 50-category SEBI taxonomy.

SEBI_CATEGORY_TAGS: dict[str, frozenset[str]] = {
    # ---- Cash-equivalent debt / arbitrage (broad coverage) ----
    "liquid": _all(),
    "overnight": _all(),
    "money_market": _all(),
    "ultra_short_duration": _build([
        ("aggressive", "short_term"),
        ("moderate", "short_term"),
        ("moderate", "medium_term"),
        ("conservative", "short_term"),
        ("conservative", "medium_term"),
    ]),
    "arbitrage": _build([
        ("aggressive", "short_term"),
        ("moderate", "short_term"),
        ("conservative", "short_term"),
    ]),
    # ---- Debt by duration ----
    "low_duration": _build([
        ("conservative", "short_term"),
        ("conservative", "medium_term"),
        ("moderate", "short_term"),
        ("moderate", "medium_term"),
    ]),
    "short_duration": _build([
        ("conservative", "short_term"),
        ("conservative", "medium_term"),
        ("conservative", "long_term"),
        ("moderate", "short_term"),
        ("moderate", "medium_term"),
        ("moderate", "long_term"),
        ("aggressive", "short_term"),
    ]),
    "medium_duration": _build([
        ("conservative", "medium_term"),
        ("conservative", "long_term"),
        ("moderate", "medium_term"),
        ("moderate", "long_term"),
    ]),
    "medium_to_long_duration": _build([
        ("conservative", "long_term"),
        ("moderate", "long_term"),
    ]),
    "long_duration": _build([
        ("conservative", "long_term"),
        ("moderate", "long_term"),
    ]),
    "dynamic_bond": _build([
        ("conservative", "short_term"),
        ("conservative", "medium_term"),
        ("conservative", "long_term"),
        ("moderate", "short_term"),
        ("moderate", "medium_term"),
        ("moderate", "long_term"),
    ]),
    "corporate_bond": _build([
        ("conservative", "medium_term"),
        ("conservative", "long_term"),
        ("moderate", "medium_term"),
        ("moderate", "long_term"),
    ]),
    "banking_and_psu": _build([
        ("conservative", "medium_term"),
        ("conservative", "long_term"),
        ("moderate", "medium_term"),
        ("moderate", "long_term"),
    ]),
    "credit_risk": _build([
        ("moderate", "medium_term"),
        ("moderate", "long_term"),
        ("aggressive", "medium_term"),
        ("aggressive", "long_term"),
    ]),
    "floater": _build([
        ("conservative", "short_term"),
        ("conservative", "medium_term"),
        ("conservative", "long_term"),
        ("moderate", "short_term"),
        ("moderate", "medium_term"),
        ("moderate", "long_term"),
    ]),
    "gilt": _build([
        ("conservative", "medium_term"),
        ("conservative", "long_term"),
        ("moderate", "medium_term"),
        ("moderate", "long_term"),
        ("aggressive", "long_term"),
    ]),
    "gilt_10y_constant_duration": _build([
        ("conservative", "long_term"),
        ("moderate", "long_term"),
        ("aggressive", "long_term"),
    ]),
    "fixed_maturity_plan": _build([
        ("conservative", "short_term"),
        ("conservative", "medium_term"),
        ("moderate", "short_term"),
        ("moderate", "medium_term"),
    ]),
    "capital_protection_oriented": _build([
        ("conservative", "medium_term"),
        ("conservative", "long_term"),
        ("moderate", "medium_term"),
    ]),
    # ---- Hybrid ----
    "conservative_hybrid": _build([
        ("conservative", "medium_term"),
        ("conservative", "long_term"),
        ("moderate", "medium_term"),
        ("moderate", "long_term"),
    ]),
    "balanced_hybrid": _build([
        ("moderate", "medium_term"),
        ("moderate", "long_term"),
        ("aggressive", "medium_term"),
        ("aggressive", "long_term"),
    ]),
    "aggressive_hybrid": _build([
        ("moderate", "medium_term"),
        ("moderate", "long_term"),
        ("aggressive", "medium_term"),
        ("aggressive", "long_term"),
    ]),
    "equity_savings": _build([
        ("conservative", "medium_term"),
        ("conservative", "long_term"),
        ("moderate", "short_term"),
        ("moderate", "medium_term"),
    ]),
    "multi_asset_allocation": _build([
        ("moderate", "medium_term"),
        ("moderate", "long_term"),
        ("aggressive", "medium_term"),
        ("aggressive", "long_term"),
    ]),
    "dynamic_asset_allocation": _build([
        ("conservative", "long_term"),
        ("moderate", "medium_term"),
        ("moderate", "long_term"),
        ("aggressive", "medium_term"),
        ("aggressive", "long_term"),
    ]),
    # ---- Equity by cap ----
    "large_cap": _build([
        ("moderate", "medium_term"),
        ("moderate", "long_term"),
        ("aggressive", "medium_term"),
        ("aggressive", "long_term"),
    ]),
    "large_and_mid_cap": _build([
        ("moderate", "long_term"),
        ("aggressive", "medium_term"),
        ("aggressive", "long_term"),
    ]),
    "mid_cap": _build([
        ("aggressive", "medium_term"),
        ("aggressive", "long_term"),
    ]),
    "small_cap": _build([("aggressive", "long_term")]),
    "multi_cap": _build([
        ("moderate", "long_term"),
        ("aggressive", "medium_term"),
        ("aggressive", "long_term"),
    ]),
    "flexi_cap": _build([
        ("moderate", "long_term"),
        ("aggressive", "medium_term"),
        ("aggressive", "long_term"),
    ]),
    "focused": _build([
        ("aggressive", "medium_term"),
        ("aggressive", "long_term"),
    ]),
    "value": _build([
        ("moderate", "long_term"),
        ("aggressive", "medium_term"),
        ("aggressive", "long_term"),
    ]),
    "contra": _build([
        ("aggressive", "medium_term"),
        ("aggressive", "long_term"),
    ]),
    "dividend_yield": _build([
        ("conservative", "long_term"),
        ("moderate", "medium_term"),
        ("moderate", "long_term"),
    ]),
    "elss": _build([
        ("moderate", "long_term"),
        ("aggressive", "medium_term"),
        ("aggressive", "long_term"),
    ]),
    "sectoral_thematic": _build([
        ("aggressive", "medium_term"),
        ("aggressive", "long_term"),
    ]),
    "sectoral_foreign_equity": _build([
        ("aggressive", "medium_term"),
        ("aggressive", "long_term"),
    ]),
    # ---- Index / passive ----
    "index_fund": _build([
        ("moderate", "long_term"),
        ("aggressive", "medium_term"),
        ("aggressive", "long_term"),
    ]),
    "debt_index": _build([
        ("conservative", "medium_term"),
        ("conservative", "long_term"),
        ("moderate", "medium_term"),
        ("moderate", "long_term"),
    ]),
    # ---- ETFs ----
    "etf_equity": _build([
        ("moderate", "long_term"),
        ("aggressive", "medium_term"),
        ("aggressive", "long_term"),
    ]),
    "etf_debt": _build([
        ("conservative", "medium_term"),
        ("conservative", "long_term"),
        ("moderate", "medium_term"),
        ("moderate", "long_term"),
    ]),
    "etf_gold": _build([
        ("conservative", "long_term"),
        ("moderate", "medium_term"),
        ("moderate", "long_term"),
        ("aggressive", "medium_term"),
        ("aggressive", "long_term"),
    ]),
    "etf_silver": _build([
        ("moderate", "long_term"),
        ("aggressive", "medium_term"),
        ("aggressive", "long_term"),
    ]),
    "etf_commodity": _build([
        ("moderate", "long_term"),
        ("aggressive", "medium_term"),
        ("aggressive", "long_term"),
    ]),
    "etf_global": _build([
        ("aggressive", "medium_term"),
        ("aggressive", "long_term"),
        ("moderate", "long_term"),
    ]),
    # ---- FoFs ----
    "fof_domestic": _build([
        ("moderate", "long_term"),
        ("aggressive", "medium_term"),
        ("aggressive", "long_term"),
    ]),
    "fof_overseas": _build([
        ("aggressive", "medium_term"),
        ("aggressive", "long_term"),
        ("moderate", "long_term"),
    ]),
    # ---- Solution-oriented ----
    "retirement_fund": _build([
        ("conservative", "long_term"),
        ("moderate", "long_term"),
    ]),
    "childrens_fund": _build([
        ("conservative", "long_term"),
        ("moderate", "long_term"),
    ]),
}


# ---------------------------------------------------------------------------
# PMS strategy classification + tag mapping
# ---------------------------------------------------------------------------


PMS_STRATEGY_TAGS: dict[str, frozenset[str]] = {
    "growth_diversified": _build([
        ("moderate", "long_term"),
        ("aggressive", "medium_term"),
        ("aggressive", "long_term"),
    ]),
    "concentrated_focused": _build([
        ("aggressive", "medium_term"),
        ("aggressive", "long_term"),
    ]),
    "sectoral_thematic": _build([
        ("aggressive", "medium_term"),
        ("aggressive", "long_term"),
    ]),
    "income_dividend": _build([
        ("conservative", "long_term"),
        ("moderate", "medium_term"),
        ("moderate", "long_term"),
    ]),
    "multi_asset": _build([
        ("moderate", "long_term"),
        ("aggressive", "long_term"),
    ]),
}


def classify_pms_strategy(name: str | None, manager: str | None = None) -> str:
    """Heuristic classifier for PMS strategy types from the fund name.

    The cluster 3 fixture's PMS records carry a free-form ``fund_name``
    plus ``fund_manager``; the cluster 3 normalisation doesn't pin a
    SEBI strategy type. This heuristic inspects the fund name for
    keywords and falls back to ``growth_diversified`` (the most common
    PMS strategy) when nothing matches.
    """
    text = " ".join(filter(None, (name, manager))).lower()
    if not text:
        return "growth_diversified"
    if any(kw in text for kw in ("concentrat", "focused", "focus")):
        return "concentrated_focused"
    if any(
        kw in text
        for kw in (
            "sector",
            "thematic",
            "theme",
            "infra",
            "tech ",
            "pharma",
            "banking",
            "consumption",
            "esg",
        )
    ):
        return "sectoral_thematic"
    if any(kw in text for kw in ("dividend", "income")):
        return "income_dividend"
    if any(kw in text for kw in ("multi asset", "multi-asset", "balanced", "hybrid")):
        return "multi_asset"
    return "growth_diversified"


# ---------------------------------------------------------------------------
# AIF category classification + tag mapping
# ---------------------------------------------------------------------------


AIF_CATEGORY_TAGS: dict[str, frozenset[str]] = {
    "cat_i": _build([("aggressive", "long_term")]),
    "cat_ii": _build([
        ("aggressive", "long_term"),
        ("moderate", "long_term"),
    ]),
    "cat_iii_long_short": _build([
        ("aggressive", "medium_term"),
        ("aggressive", "long_term"),
    ]),
    "cat_iii_long_only": _build([
        ("aggressive", "long_term"),
        ("moderate", "long_term"),
    ]),
}


def classify_aif_category(sebi_subcategory: str | None, name: str | None = None) -> str:
    """Heuristic AIF category classifier.

    Cluster 3's AIF records carry a ``sebi_subcategory`` field with
    values like "CAT I", "CAT II", "CAT III". CAT III splits further
    into long-short and long-only based on the strategy name. Defaults
    to ``cat_ii`` (the most common middle ground) when nothing matches.
    """
    text = " ".join(filter(None, (sebi_subcategory, name))).lower()
    if not text:
        return "cat_ii"
    if "cat iii" in text or "cat-iii" in text or "category iii" in text:
        if "long-short" in text or "long short" in text or "ls " in text:
            return "cat_iii_long_short"
        return "cat_iii_long_only"
    if "cat i" in text and "cat ii" not in text:
        return "cat_i"
    if "cat ii" in text:
        return "cat_ii"
    return "cat_ii"


# ---------------------------------------------------------------------------
# Listed equity by market cap rank
# ---------------------------------------------------------------------------


# Per FR 13.3 §2.4: rank-based bucketing for Nifty 500.
_LARGE_CAP = _build([
    ("moderate", "long_term"),
    ("aggressive", "medium_term"),
    ("aggressive", "long_term"),
])
_MID_CAP = _build([
    ("aggressive", "medium_term"),
    ("aggressive", "long_term"),
])
_SMALL_CAP = _build([("aggressive", "long_term")])


def listed_equity_tags_by_rank(rank: int | None) -> frozenset[str]:
    """Return default tags for a Nifty 500 stock given its market cap rank.

    Rank ranges (FR 13.3 §2.4):

    - 1-100: Large Cap → moderate_long_term, aggressive_medium_term,
      aggressive_long_term
    - 101-250: Mid Cap → aggressive_medium_term, aggressive_long_term
    - 251-500: Small Cap → aggressive_long_term

    Stocks without a known rank default to the Mid Cap tag set as a
    conservative middle ground (better to under-tag than over-tag for
    untagged stocks).
    """
    if rank is None or rank < 1:
        return _MID_CAP
    if rank <= 100:
        return _LARGE_CAP
    if rank <= 250:
        return _MID_CAP
    return _SMALL_CAP


# ---------------------------------------------------------------------------
# Unlisted equity (single rule)
# ---------------------------------------------------------------------------


UNLISTED_EQUITY_TAGS: frozenset[str] = _build([("aggressive", "long_term")])


# ---------------------------------------------------------------------------
# Top-level dispatcher
# ---------------------------------------------------------------------------


def default_tags_for_instrument(
    *,
    vehicle_type: str,
    sebi_category: str | None = None,
    name: str | None = None,
    amc_name: str | None = None,
    market_cap_rank: int | None = None,
) -> frozenset[str]:
    """Compute the default tag set for one instrument.

    Returns an empty frozenset when classification is impossible — the
    loader emits ``instrument_default_tagging_failed`` for these so the
    CIO can address them via the chunk 4.2 admin UI.
    """
    if vehicle_type in ("mutual_fund", "etf"):
        if sebi_category and sebi_category in SEBI_CATEGORY_TAGS:
            return SEBI_CATEGORY_TAGS[sebi_category]
        # Unknown SEBI category — fail fast (loader logs).
        return frozenset()
    if vehicle_type == "stock":
        return listed_equity_tags_by_rank(market_cap_rank)
    if vehicle_type == "pms":
        strategy = classify_pms_strategy(name, amc_name)
        return PMS_STRATEGY_TAGS.get(strategy, frozenset())
    if vehicle_type == "aif":
        category = classify_aif_category(sebi_category, name)
        return AIF_CATEGORY_TAGS.get(category, frozenset())
    if vehicle_type == "unlisted_equity":
        return UNLISTED_EQUITY_TAGS
    if vehicle_type == "bond":
        # Cluster 4 reserves the schema; FR 13.3 §2.6 documents bond
        # defaults but they're not implemented until cluster 17 ships
        # actual bond instruments. Return empty — loader logs.
        return frozenset()
    return frozenset()
