"""Cluster 4 chunk 4.1 — default tag rule tests (FR Entry 13.3 §2)."""

from __future__ import annotations

from artha.api_v2.m2 import default_tags


class TestSEBICategoryRules:
    def test_liquid_tags_all_nine_cells(self):
        tags = default_tags.SEBI_CATEGORY_TAGS["liquid"]
        assert len(tags) == 9

    def test_overnight_tags_all_nine_cells(self):
        tags = default_tags.SEBI_CATEGORY_TAGS["overnight"]
        assert len(tags) == 9

    def test_money_market_tags_all_nine_cells(self):
        tags = default_tags.SEBI_CATEGORY_TAGS["money_market"]
        assert len(tags) == 9

    def test_small_cap_tags_aggressive_long_only(self):
        tags = default_tags.SEBI_CATEGORY_TAGS["small_cap"]
        assert tags == frozenset({"aggressive_long_term"})

    def test_large_cap_tags_breadth(self):
        # Large cap: moderate_medium, moderate_long, aggressive_medium,
        # aggressive_long.
        tags = default_tags.SEBI_CATEGORY_TAGS["large_cap"]
        assert "moderate_long_term" in tags
        assert "aggressive_long_term" in tags
        assert "aggressive_medium_term" in tags
        assert "conservative_long_term" not in tags

    def test_corporate_bond_excludes_aggressive(self):
        tags = default_tags.SEBI_CATEGORY_TAGS["corporate_bond"]
        for t in tags:
            assert t.startswith(("conservative_", "moderate_"))


class TestPMSStrategyClassifier:
    def test_concentrated_keyword_classifies(self):
        assert (
            default_tags.classify_pms_strategy("Concentrated Equity Fund")
            == "concentrated_focused"
        )
        assert (
            default_tags.classify_pms_strategy("Focused Multi Cap")
            == "concentrated_focused"
        )

    def test_sectoral_keywords_classify(self):
        for n in ("Banking PMS", "Pharma Sector Strategy", "Infra Theme PMS"):
            assert default_tags.classify_pms_strategy(n) == "sectoral_thematic"

    def test_dividend_yields_to_income(self):
        assert (
            default_tags.classify_pms_strategy("Dividend Yield Strategy")
            == "income_dividend"
        )

    def test_multi_asset_keyword(self):
        assert (
            default_tags.classify_pms_strategy("Multi-Asset Hybrid")
            == "multi_asset"
        )

    def test_default_fallback(self):
        assert (
            default_tags.classify_pms_strategy("Random Equity Strategy")
            == "growth_diversified"
        )

    def test_empty_input(self):
        assert (
            default_tags.classify_pms_strategy(None)
            == "growth_diversified"
        )


class TestAIFCategoryClassifier:
    def test_cat_iii_long_short(self):
        assert (
            default_tags.classify_aif_category("CAT III long-short", None)
            == "cat_iii_long_short"
        )

    def test_cat_iii_long_only_default(self):
        assert (
            default_tags.classify_aif_category("CAT III", None)
            == "cat_iii_long_only"
        )

    def test_cat_i(self):
        assert default_tags.classify_aif_category("CAT I", None) == "cat_i"

    def test_cat_ii(self):
        assert default_tags.classify_aif_category("CAT II", None) == "cat_ii"

    def test_unknown_falls_back_to_cat_ii(self):
        assert default_tags.classify_aif_category(None, None) == "cat_ii"


class TestListedEquityByRank:
    def test_top_50_large_cap(self):
        for rank in (1, 25, 50, 100):
            tags = default_tags.listed_equity_tags_by_rank(rank)
            assert "moderate_long_term" in tags
            assert "aggressive_long_term" in tags
            assert "aggressive_medium_term" in tags

    def test_mid_cap_range(self):
        for rank in (101, 200, 250):
            tags = default_tags.listed_equity_tags_by_rank(rank)
            assert tags == frozenset({"aggressive_medium_term", "aggressive_long_term"})

    def test_small_cap_range(self):
        for rank in (251, 400, 500):
            tags = default_tags.listed_equity_tags_by_rank(rank)
            assert tags == frozenset({"aggressive_long_term"})

    def test_unknown_rank_defaults_to_mid_cap(self):
        tags = default_tags.listed_equity_tags_by_rank(None)
        assert tags == frozenset({"aggressive_medium_term", "aggressive_long_term"})


class TestTopLevelDispatcher:
    def test_mutual_fund_with_known_sebi_category(self):
        tags = default_tags.default_tags_for_instrument(
            vehicle_type="mutual_fund",
            sebi_category="liquid",
        )
        assert len(tags) == 9

    def test_mutual_fund_without_sebi_category_returns_empty(self):
        tags = default_tags.default_tags_for_instrument(
            vehicle_type="mutual_fund",
            sebi_category=None,
        )
        assert tags == frozenset()

    def test_etf_classifies_via_sebi(self):
        tags = default_tags.default_tags_for_instrument(
            vehicle_type="etf",
            sebi_category="etf_gold",
        )
        assert "aggressive_long_term" in tags

    def test_stock_uses_market_cap_rank(self):
        tags = default_tags.default_tags_for_instrument(
            vehicle_type="stock",
            market_cap_rank=10,
        )
        assert "aggressive_long_term" in tags
        assert "moderate_long_term" in tags

    def test_pms_classifies_by_name(self):
        tags = default_tags.default_tags_for_instrument(
            vehicle_type="pms",
            name="Focused Equity PMS",
        )
        assert tags == default_tags.PMS_STRATEGY_TAGS["concentrated_focused"]

    def test_aif_classifies_by_subcategory(self):
        tags = default_tags.default_tags_for_instrument(
            vehicle_type="aif",
            sebi_category="CAT II",
        )
        assert tags == default_tags.AIF_CATEGORY_TAGS["cat_ii"]

    def test_unlisted_equity_aggressive_long_only(self):
        tags = default_tags.default_tags_for_instrument(
            vehicle_type="unlisted_equity",
        )
        assert tags == frozenset({"aggressive_long_term"})

    def test_bond_returns_empty_in_cluster_4(self):
        # Bond defaults reserved for cluster 17 per FR 13.3 §2.6.
        tags = default_tags.default_tags_for_instrument(vehicle_type="bond")
        assert tags == frozenset()
