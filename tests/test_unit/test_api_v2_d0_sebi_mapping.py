"""Cluster 3 chunk 3.2 + addendum — SEBI mutual-fund category mapping tests.

Pins the canonical-category coverage assertion, the four-band asset-class
vocabulary, the case/whitespace-insensitive lookup behaviour, and the
display-form alias resolution introduced by the cluster 3 addendum.
"""

from __future__ import annotations

import pytest

from artha.api_v2.d0.instruments import sebi_mapping


class TestCoverage:
    def test_exactly_50_categories(self):
        # Chunk 3.2 base shipped 46. Cluster 3 addendum added debt_index,
        # etf_commodity, etf_global, sectoral_foreign_equity → 50 total.
        assert len(sebi_mapping.SEBI_CATEGORY_MAP) == 50

    def test_asset_classes_match_vocabulary(self):
        # Every mapped asset class is one of the four cluster-3 bands.
        for cat, (asset_class, _) in sebi_mapping.SEBI_CATEGORY_MAP.items():
            assert asset_class in sebi_mapping.ASSET_CLASSES, (
                f"{cat!r} maps to unknown asset_class {asset_class!r}"
            )

    def test_vehicle_types_match_vocabulary(self):
        for cat, (_, vehicle_type) in sebi_mapping.SEBI_CATEGORY_MAP.items():
            assert vehicle_type in sebi_mapping.VEHICLE_TYPES, (
                f"{cat!r} maps to unknown vehicle_type {vehicle_type!r}"
            )

    def test_all_four_asset_classes_have_at_least_one_category(self):
        seen = {ac for ac, _ in sebi_mapping.SEBI_CATEGORY_MAP.values()}
        assert seen == set(sebi_mapping.ASSET_CLASSES)

    def test_all_categories_returns_alphabetised(self):
        cats = sebi_mapping.all_categories()
        assert list(cats) == sorted(cats)
        assert len(cats) == 50


class TestEquityCategories:
    @pytest.mark.parametrize(
        "category",
        [
            "multi_cap",
            "flexi_cap",
            "large_cap",
            "large_and_mid_cap",
            "mid_cap",
            "small_cap",
            "elss",
            "focused",
            "sectoral_thematic",
        ],
    )
    def test_equity_category_classifies_to_equity(self, category):
        asset_class, vehicle_type = sebi_mapping.classify(category)
        assert asset_class == "equity"
        assert vehicle_type == "mutual_fund"


class TestDebtCategories:
    @pytest.mark.parametrize(
        "category",
        [
            "low_duration",
            "short_duration",
            "medium_duration",
            "long_duration",
            "corporate_bond",
            "credit_risk",
            "banking_and_psu",
            "gilt",
            "floater",
        ],
    )
    def test_debt_category_classifies_to_debt(self, category):
        asset_class, _ = sebi_mapping.classify(category)
        assert asset_class == "debt"


class TestCashCategories:
    """Liquid + Overnight + Ultra Short + Money Market + Arbitrage map to cash."""

    @pytest.mark.parametrize(
        "category",
        ["overnight", "liquid", "ultra_short_duration", "money_market", "arbitrage"],
    )
    def test_cash_management_category_classifies_to_cash(self, category):
        asset_class, _ = sebi_mapping.classify(category)
        assert asset_class == "cash"


class TestAlternativesCategories:
    @pytest.mark.parametrize(
        "category", ["multi_asset_allocation", "etf_gold", "etf_silver"]
    )
    def test_alternatives_category(self, category):
        asset_class, _ = sebi_mapping.classify(category)
        assert asset_class == "alternatives"


class TestHybridResolution:
    def test_aggressive_hybrid_classifies_to_equity(self):
        # SEBI definition: 65-80% equity allocation.
        assert sebi_mapping.classify("aggressive_hybrid")[0] == "equity"

    def test_conservative_hybrid_classifies_to_debt(self):
        # SEBI definition: 10-25% equity, dominant debt.
        assert sebi_mapping.classify("conservative_hybrid")[0] == "debt"

    def test_dynamic_asset_allocation_classifies_to_equity(self):
        # Balanced advantage funds default to equity bucket.
        assert sebi_mapping.classify("dynamic_asset_allocation")[0] == "equity"


class TestETFs:
    def test_etf_equity_uses_etf_vehicle(self):
        ac, vehicle = sebi_mapping.classify("etf_equity")
        assert ac == "equity"
        assert vehicle == "etf"

    def test_etf_debt_uses_etf_vehicle(self):
        ac, vehicle = sebi_mapping.classify("etf_debt")
        assert ac == "debt"
        assert vehicle == "etf"

    def test_etf_gold_uses_etf_vehicle_alternatives(self):
        ac, vehicle = sebi_mapping.classify("etf_gold")
        assert ac == "alternatives"
        assert vehicle == "etf"


class TestCaseInsensitivity:
    def test_uppercase_lookup(self):
        ac, vehicle = sebi_mapping.classify("LARGE_CAP")
        assert ac == "equity"
        assert vehicle == "mutual_fund"

    def test_hyphenated_lookup(self):
        ac, _ = sebi_mapping.classify("large-cap")
        assert ac == "equity"

    def test_space_separated_lookup(self):
        ac, _ = sebi_mapping.classify("Large Cap")
        assert ac == "equity"

    def test_whitespace_padded_lookup(self):
        ac, _ = sebi_mapping.classify("  small_cap  ")
        assert ac == "equity"


class TestUnknown:
    def test_unknown_category_raises(self):
        with pytest.raises(sebi_mapping.UnknownSebiCategoryError):
            sebi_mapping.classify("not_a_real_category")

    def test_is_known_returns_false_for_unknown(self):
        assert not sebi_mapping.is_known("totally_made_up")

    def test_is_known_returns_true_for_known(self):
        assert sebi_mapping.is_known("liquid")
