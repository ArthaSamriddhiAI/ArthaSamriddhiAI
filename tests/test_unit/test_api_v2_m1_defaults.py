"""Cluster 2 chunk 2.1 + cluster 3 chunk 3.1 — I0 defaults pure-function suite.

Pins the FR Entry 11.1 §4.1 (cluster-3 revision) + 12.1 §2.4 mappings:
every (risk_appetite, liquidity_tier) combination produces the
documented four-band defaults (equity, debt, cash, alternatives).
"""

from __future__ import annotations

import pytest

from artha.api_v2.m1.i0_defaults import compute_defaults


class TestAssetAllocationDefaults:
    def test_aggressive_yields_four_band_65_85_5_20_0_10_5_15(self):
        d = compute_defaults(risk_appetite="aggressive", liquidity_tier="essential")
        assert (d.equity_min_pct, d.equity_max_pct) == (65, 85)
        assert (d.debt_min_pct, d.debt_max_pct) == (5, 20)
        assert (d.cash_min_pct, d.cash_max_pct) == (0, 10)
        assert (d.alternatives_min_pct, d.alternatives_max_pct) == (5, 15)

    def test_moderate_yields_four_band_45_65_15_35_5_15_5_15(self):
        d = compute_defaults(risk_appetite="moderate", liquidity_tier="secondary")
        assert (d.equity_min_pct, d.equity_max_pct) == (45, 65)
        assert (d.debt_min_pct, d.debt_max_pct) == (15, 35)
        assert (d.cash_min_pct, d.cash_max_pct) == (5, 15)
        assert (d.alternatives_min_pct, d.alternatives_max_pct) == (5, 15)

    def test_conservative_yields_four_band_25_45_35_55_10_20_5_15(self):
        d = compute_defaults(risk_appetite="conservative", liquidity_tier="deep")
        assert (d.equity_min_pct, d.equity_max_pct) == (25, 45)
        assert (d.debt_min_pct, d.debt_max_pct) == (35, 55)
        assert (d.cash_min_pct, d.cash_max_pct) == (10, 20)
        assert (d.alternatives_min_pct, d.alternatives_max_pct) == (5, 15)

    def test_unknown_risk_appetite_falls_back_to_moderate(self):
        d = compute_defaults(risk_appetite="balanced", liquidity_tier="secondary")
        # Falls back to moderate's four-band defaults.
        assert (d.equity_min_pct, d.equity_max_pct) == (45, 65)
        assert (d.cash_min_pct, d.cash_max_pct) == (5, 15)

    def test_four_band_sums_satisfy_constraints(self):
        """Cluster 3 sanity check: every default profile satisfies
        sum-of-mins ≤ 100 and sum-of-maxes ≥ 100."""
        for risk in ("aggressive", "moderate", "conservative"):
            d = compute_defaults(risk_appetite=risk, liquidity_tier="secondary")
            sum_min = (
                d.equity_min_pct + d.debt_min_pct
                + d.cash_min_pct + d.alternatives_min_pct
            )
            sum_max = (
                d.equity_max_pct + d.debt_max_pct
                + d.cash_max_pct + d.alternatives_max_pct
            )
            assert sum_min <= 100, f"{risk}: sum_min={sum_min}"
            assert sum_max >= 100, f"{risk}: sum_max={sum_max}"


class TestLiquidityFloorDefaults:
    @pytest.mark.parametrize(
        "tier,expected",
        [("essential", 10), ("secondary", 20), ("deep", 30)],
    )
    def test_tier_to_floor(self, tier, expected):
        d = compute_defaults(risk_appetite="moderate", liquidity_tier=tier)
        assert d.liquidity_floor_pct == expected

    def test_unknown_tier_falls_back_to_secondary(self):
        d = compute_defaults(risk_appetite="moderate", liquidity_tier="unknown")
        assert d.liquidity_floor_pct == 20

    def test_none_inputs_fall_back_to_moderate_secondary(self):
        d = compute_defaults(risk_appetite=None, liquidity_tier=None)
        # Cluster 3 revision: moderate's four-band defaults.
        assert (d.equity_min_pct, d.equity_max_pct) == (45, 65)
        assert (d.cash_min_pct, d.cash_max_pct) == (5, 15)
        assert d.liquidity_floor_pct == 20


class TestIndustryStandardDefaults:
    def test_single_position_default_5(self):
        d = compute_defaults(risk_appetite="moderate", liquidity_tier="secondary")
        assert d.single_position_max_pct == 5

    def test_sector_cap_default_25(self):
        d = compute_defaults(risk_appetite="moderate", liquidity_tier="secondary")
        assert d.sector_max_pct == 25

    def test_prohibited_default_empty(self):
        d = compute_defaults(risk_appetite="moderate", liquidity_tier="secondary")
        assert d.prohibited_instruments == ()


class TestSourceLabels:
    def test_asset_allocation_sourced_from_risk_appetite(self):
        d = compute_defaults(risk_appetite="moderate", liquidity_tier="secondary")
        for key in (
            "equity_min_pct", "equity_max_pct", "debt_min_pct", "debt_max_pct",
            "alternatives_min_pct", "alternatives_max_pct",
        ):
            assert d.sources[key] == "i0_risk_appetite"

    def test_liquidity_sourced_from_tier(self):
        d = compute_defaults(risk_appetite="moderate", liquidity_tier="secondary")
        assert d.sources["liquidity_floor_pct"] == "i0_liquidity_tier"

    def test_single_position_and_sector_sourced_from_industry_standard(self):
        d = compute_defaults(risk_appetite="moderate", liquidity_tier="secondary")
        assert d.sources["single_position_max_pct"] == "industry_standard"
        assert d.sources["sector_max_pct"] == "industry_standard"
